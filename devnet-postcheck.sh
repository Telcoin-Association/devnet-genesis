#!/usr/bin/env bash
#
# devnet-postcheck.sh — READ-ONLY post-checks of the launch-2 devnet: deploy step 16 (after the
# coordinated start and the rpc edge), usable any time later.
#
# Usage: ./devnet-postcheck.sh [--only <group>]... [--no-public] [target ...]
#   target       an index (0-based), INSTANCE_NAME or NODE_NAME; default: every fleet entry. Naming a
#                node also checks the host that runs its gateway; naming a gateway entry checks that
#                gateway host only.
#   --only G     run only group G (repeatable): gateway, binds, public, rpc, admission, chain
#   --no-public  skip the checks made from THIS machine over https (a rehearsal without DNS)
#
# Output: one line per check, `POSTCHECK <host> <check> ok|FAIL|not-decisive <detail>`, on stdout
# (also in <log dir>/postcheck.txt); a summary on stderr. Exit 0 when no check failed, 1 when one
# failed, 2 on a usage or config error or a missing local tool.
#
# Groups and checks:
#   gateway   per gateway host: gateway-status (setup-gateway.sh --status --json: installed, active,
#             ready true, issues 0; waits up to POSTCHECK_READY_WAIT_SECS for /ready on the probe
#             listener first), gateway-listeners (listen/probe/metrics ports on loopback only),
#             gateway-metrics (tn_worker_gateway_upstream_ready = 1)
#   binds     per node behind a gateway: rpc-bind, health-bind (same-host: 127.0.0.1 only;
#             standalone: 0.0.0.0); standalone also upstream-from-gateway (eth_chainId on the node's
#             internal IP from its gateway host), upstream-from-other (the same call from a same-host
#             validator is refused or times out), gateway-meta (GATEWAY_ALLOW_FROM / GATEWAY_UPSTREAM
#             in the node's .node-meta = the gateway's internal IP)
#   public    per node behind a gateway, from this machine: public-chainid, public-tls, public-ws
#             (an upgrade gets 405, not 101), public-ready-any (200), public-identity (tn_nodeMode and
#             tn_info's bls_public_key through https://<domain> are not this node's own answers)
#   rpc       per rpc node: rpc-https and rpc-wss (from this machine), rpc-admission (primary Open)
#   admission per validator / observer: primary swarm Closed, fallback null, every rpc node's entry
#             trusted + admitted (matched by BLS key from genesis/observers/<name>.yaml, else by slot)
#   chain     host `chain`: validators-active (CvvActive), heads (equal within POSTCHECK_HEAD_LAG),
#             consensus-progress (tn_latestConsensusHeader .number rises on every validator over
#             POSTCHECK_ROUND_GAP_SECS; an idle chain's head moves only at epoch closes, so the head
#             is not required to advance)
#
# Settling: admission, rpc-admission and the chain group need a node to have its peers. Deploy
# step 15 restarts the rpc node, node 5's only peer before it stakes, and node 5 reconnects only
# after its trusted-dial backoff (about 45 s). So these checks are judged last: the node hosts where
# one does not pass yet are re-read (node reads only) every POSTCHECK_RETRY_SECS until they pass or
# POSTCHECK_SETTLE_SECS have gone by, and a line read after such a wait says so. When the chain
# group runs, every node host is re-read together (its samples are compared across hosts).
# The other checks are judged once, from the first round, and printed first; when one of them has
# failed the run fails anyway, so there is no settle wait.
#
# Remote side: ONE ssh round trip per host (all hosts in parallel), through devnet-lib.sh's
# tn_iap_ssh_stdin with one retry on rc 255. The probe only reads: `ss -ltn`, curl to loopback or
# to a node's internal IP, `setup-gateway.sh --status --json`, a grep of /etc/telcoin/.node-meta. It
# prints key=value lines and a __tn_probe_done sentinel; the JSON is judged here with python3.
# Nothing is restarted or written on any host.
#
# Knobs: POSTCHECK_READY_WAIT_SECS (120), POSTCHECK_HEAD_LAG (5), POSTCHECK_ROUND_GAP_SECS (15),
# POSTCHECK_CONNECT_TIMEOUT (3), POSTCHECK_HTTP_TIMEOUT (10), POSTCHECK_RETRY_SECS (5),
# POSTCHECK_SETTLE_SECS (180), POSTCHECK_LOG_DIR (default <repo>/logs/<stamp>-postcheck).

set -euo pipefail

POSTCHECK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=devnet-lib.sh
source "${POSTCHECK_DIR}/devnet-lib.sh"

POSTCHECK_READY_WAIT_SECS="${POSTCHECK_READY_WAIT_SECS:-120}"
POSTCHECK_HEAD_LAG="${POSTCHECK_HEAD_LAG:-5}"
POSTCHECK_ROUND_GAP_SECS="${POSTCHECK_ROUND_GAP_SECS:-15}"
POSTCHECK_CONNECT_TIMEOUT="${POSTCHECK_CONNECT_TIMEOUT:-3}"
POSTCHECK_HTTP_TIMEOUT="${POSTCHECK_HTTP_TIMEOUT:-10}"
POSTCHECK_RETRY_SECS="${POSTCHECK_RETRY_SECS:-5}"
POSTCHECK_SETTLE_SECS="${POSTCHECK_SETTLE_SECS:-180}"

PC_GROUPS="gateway binds public rpc admission chain"
ONLY=""
NO_PUBLIC=0
SEL=""          # selected fleet indices, array order
NODE_SUBJ=""    # selected indices that run a node
GW_HOSTS=""     # indices of the gateway hosts to check
PROBE_HOSTS=""  # indices to probe
PROBE_ARGS=()   # per index: the probe's key=value words
SA_GW=() SA_GIP=() SA_NIP=() SA_WIT=()   # per standalone node: gateway index, gateway / node internal IP, witness index
RPC_MATCH=""    # snapshot match spec for the rpc nodes: "match=keys <name>=<hex>..." or "match=slot <n>"
RPC_B58=""      # the rpc nodes' BLS keys as in genesis/observers (base58), space separated
CHAIN_HEX=""
RUN_DIR=""
N_CHECKS=0 N_FAIL=0 N_ND=0
PC_DRY=0 PC_DRY_FAIL=0   # PC_DRY=1: _pc_line prints nothing and only notes a FAIL (see _pc_pending)
PC_WAITED=0              # seconds into the settle wait of its last re-read round (0: no wait)

_usage() { sed -n '6,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# Judges JSON answers (stdin) for the checks; ops: res, num <field|->, field <name>, snap, b58hex.
IFS= read -r -d '' _PC_PY <<'PY' || true
import json
import sys

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def load(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return None


def text(v):
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def norm(k):
    k = (k or "").lower()
    return k[2:] if k.startswith("0x") else k


def snap(d, r, raw, args):
    want, spec = args[0], args[1:]
    if not isinstance(d, dict):
        print("FAIL tn_admissionSnapshot unreadable: " + (" ".join(raw.split())[:80] or "<empty>"))
        return 0
    if not isinstance(r, dict):
        print("FAIL tn_admissionSnapshot error: " + text(d.get("error"))[:120])
        return 0
    prim = [s for s in r.get("swarms") or [] if isinstance(s, dict) and s.get("network") == "primary"]
    if not prim:
        print("FAIL no primary swarm in the snapshot")
        return 0
    s = prim[0]
    adm = s.get("admission") or {}
    eff, fb = adm.get("effective"), adm.get("fallback")
    head = "primary effective=%s fallback=%s connected=%s epoch=%s" % (
        eff, "null" if fb is None else fb, adm.get("connected_current"), r.get("epoch"))
    bad = []
    if s.get("available") is not True:
        bad.append("swarm not available")
    if eff != want:
        bad.append("effective %s, want %s" % (eff, want))
    if want == "Closed":
        if fb is not None:
            bad.append("fallback %s, want null" % fb)
        entries = [e for e in s.get("entries") or [] if isinstance(e, dict)]
        if spec and spec[0] == "match=keys":
            for item in spec[1:]:
                name, _, key = item.partition("=")
                hit = [e for e in entries if norm(e.get("bls_pubkey")) == key.lower()]
                if not hit:
                    bad.append("%s's BLS key is not in the entries" % name)
                elif "trusted" not in (hit[0].get("slots") or []) or hit[0].get("admitted") is not True:
                    bad.append("%s slots=%s admitted=%s" % (
                        name, ",".join(hit[0].get("slots") or []) or "-", hit[0].get("admitted")))
            head += "; rpc node matched by BLS key (genesis/observers)"
        else:
            want_n = int(spec[1]) if len(spec) > 1 else 1
            trusted = [e for e in entries if "trusted" in (e.get("slots") or [])]
            if len(trusted) != want_n:
                bad.append("%d trusted entries, want %d" % (len(trusted), want_n))
            if [e for e in trusted if e.get("admitted") is not True]:
                bad.append("a trusted entry is not admitted")
            head += "; rpc node matched by the trusted slot alone (no genesis/observers key)"
    print(("FAIL " + "; ".join(bad) + " (" + head + ")") if bad else ("ok " + head))
    return 0


def main():
    op, args = sys.argv[1], sys.argv[2:]
    raw = sys.stdin.read().strip()
    if op == "b58hex":
        raw = raw.strip("'\"")
        n = 0
        for c in raw:
            if c not in B58:
                return 1
            n = n * 58 + B58.index(c)
        body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
        print((b"\0" * (len(raw) - len(raw.lstrip("1"))) + body).hex())
        return 0
    d = load(raw)
    r = d.get("result") if isinstance(d, dict) else None
    if op == "res":
        if isinstance(d, dict) and "result" in d:
            print("ok " + text(r))
        elif isinstance(d, dict) and isinstance(d.get("error"), dict):
            e = d["error"]
            print("err %s %s" % (e.get("code"), " ".join(str(e.get("message", "")).split())[:80]))
        else:
            print("bad " + (" ".join(raw.split())[:80] or "<empty>"))
        return 0
    if op == "num":
        v = r if args[0] == "-" else (r.get(args[0]) if isinstance(r, dict) else None)
        if isinstance(v, int) and not isinstance(v, bool):
            print(v)
        elif isinstance(v, str):
            try:
                print(int(v, 16) if v.lower().startswith("0x") else int(v))
            except ValueError:
                pass
        return 0
    if op == "field":
        if isinstance(r, dict) and args[0] in r:
            print(text(r[args[0]]))
        return 0
    if op == "snap":
        return snap(d, r, raw, args)
    return 2


sys.exit(main())
PY

_pc_py() { python3 -I -c "${_PC_PY}" "$@"; }
_pc_res() { _pc_py res <<< "$1"; }
_pc_in() { case " $2 " in *" $1 "*) return 0 ;; esac; return 1; }
_pc_on() {   # _pc_on <group> — rc 0 when the group runs
    if [ -n "${ONLY}" ] && ! _pc_in "$1" "${ONLY}"; then return 1; fi
    case "$1" in public) [ "${NO_PUBLIC}" = 0 ] ;; *) return 0 ;; esac
}
_pc_short() { local k="${1:-}"; if [ "${#k}" -gt 12 ]; then printf '%s…' "${k:0:10}"; else printf '%s' "${k:-none}"; fi; }

# _pc_line <host> <check> <ok|FAIL|not-decisive> <detail> — one result line.
_pc_line() {
    if [ "${PC_DRY}" = 1 ]; then
        if [ "$3" = FAIL ]; then PC_DRY_FAIL=1; fi
        return 0
    fi
    printf 'POSTCHECK %s %s %s %s\n' "$1" "$2" "$3" "$4" | tee -a "${RUN_DIR}/postcheck.txt"
    N_CHECKS=$((N_CHECKS + 1))
    case "$3" in
        FAIL) N_FAIL=$((N_FAIL + 1)) ;;
        not-decisive) N_ND=$((N_ND + 1)) ;;
    esac
}

# ---- the remote probe ------------------------------------------------------------------------
# Sent with `declare -f` over tn_iap_ssh_stdin (runs as root under `bash -s`, no set -e). Args are
# key=value words: node=1 (chain samples, tn_nodeMode, tn_info, tn_admissionSnapshot on loopback),
# gap=<s> (second chain sample after <s>), gw=1 probe=<port> metrics=<port> wait=<s> scripts=<dir>,
# meta=1 (.node-meta GATEWAY_* keys), reach=<label>@<ip> (eth_chainId to <ip>:<port>), port=<node
# RPC port>, ct=<connect timeout>. Every command only reads.
# shellcheck disable=SC2329  # runs on the host: sent with declare -f
_pc_remote() {
    local a node=0 gw=0 meta=0 port=8545 ct=3 gap=0 pp="" mp="" gwait=0 scripts="" reach="" r k out rc code w
    for a in "$@"; do
        case "${a}" in
            node=*) node="${a#node=}" ;;
            gw=*) gw="${a#gw=}" ;;
            meta=*) meta="${a#meta=}" ;;
            port=*) port="${a#port=}" ;;
            ct=*) ct="${a#ct=}" ;;
            gap=*) gap="${a#gap=}" ;;
            probe=*) pp="${a#probe=}" ;;
            metrics=*) mp="${a#metrics=}" ;;
            wait=*) gwait="${a#wait=}" ;;
            scripts=*) scripts="${a#scripts=}" ;;
            reach=*) reach="${reach} ${a#reach=}" ;;
        esac
    done
    _pc_rj() {   # _pc_rj <url> <method> — one JSON-RPC call, the answer on one line
        curl -s --connect-timeout "${ct}" --max-time 10 -X POST -H "Content-Type: application/json" \
            --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$2\",\"params\":[]}" "$1" 2>/dev/null
    }
    echo "ss=$(ss -ltn 2>/dev/null | awk 'NR > 1 { print $4 }' | tr '\n' ' ')"
    if [ "${node}" = 1 ]; then
        echo "head1=$(_pc_rj "http://127.0.0.1:${port}" eth_blockNumber | tr -d '\r\n')"
        echo "cons1=$(_pc_rj "http://127.0.0.1:${port}" tn_latestConsensusHeader | tr -d '\r\n')"
        if [ "${gap}" -gt 0 ]; then
            sleep "${gap}"
            echo "head2=$(_pc_rj "http://127.0.0.1:${port}" eth_blockNumber | tr -d '\r\n')"
            echo "cons2=$(_pc_rj "http://127.0.0.1:${port}" tn_latestConsensusHeader | tr -d '\r\n')"
        fi
        for k in tn_nodeMode tn_info tn_admissionSnapshot; do
            echo "${k}=$(_pc_rj "http://127.0.0.1:${port}" "${k}" | tr -d '\r\n')"
        done
    fi
    if [ "${gw}" = 1 ]; then
        w=0
        while :; do
            code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${pp}/ready" 2>/dev/null)"
            if [ "${code}" = 200 ] || [ "${w}" -ge "${gwait}" ]; then break; fi
            sleep 5
            w=$((w + 5))
        done
        echo "gw_ready_code=${code}"
        echo "gw_waited=${w}"
        echo "gw_done=$(bash "${scripts}/setup-gateway.sh" --status --json 2>/dev/null | grep '"event":"done"' | tail -n 1)"
        curl -s --max-time 5 "http://127.0.0.1:${mp}/metrics" 2>/dev/null | grep '^tn_worker_gateway_upstream_ready' | sed 's/^/gw_up=/'
    fi
    for r in ${reach}; do
        rc=0
        out="$(_pc_rj "http://${r#*@}:${port}" eth_chainId)" || rc=$?
        echo "reach_${r%%@*}_rc=${rc}"
        echo "reach_${r%%@*}_body=$(printf '%s' "${out}" | tr -d '\r\n' | cut -c 1-200)"
    done
    if [ "${meta}" = 1 ]; then
        for k in GATEWAY_ALLOW_FROM GATEWAY_UPSTREAM; do
            echo "meta_${k}=$(grep "^${k}=" /etc/telcoin/.node-meta 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r')"
        done
    fi
}

# _pc_probe <i> [<words>] — run host i's probe (with <words> in place of PROBE_ARGS[i] when given);
# its lines on stdout. rc 1 with the reason on stdout when ssh
# failed or the sentinel is missing. One retry when ssh returns 255.
_pc_probe() {
    local i="$1" words="${2:-${PROBE_ARGS[$1]:-}}" script out rc=0 a
    script="$(declare -f _pc_remote)"$'\n'"_pc_remote"
    for a in ${words}; do script="${script} $(printf '%q' "${a}")"; done
    script="${script}"$'\n'"echo __tn_probe_done"$'\n'
    out="$(printf '%s' "${script}" | tn_iap_ssh_stdin "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" 2>>"${RUN_DIR}/${i}.err")" || rc=$?
    if [ "${rc}" -eq 255 ]; then
        echo "    … ssh rc 255 from ${INSTANCE_NAMES[$i]}; one retry in ${POSTCHECK_RETRY_SECS}s" >&2
        sleep "${POSTCHECK_RETRY_SECS}"
        rc=0
        out="$(printf '%s' "${script}" | tn_iap_ssh_stdin "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" 2>>"${RUN_DIR}/${i}.err")" || rc=$?
    fi
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    case "${out}" in
        *__tn_probe_done*) printf '%s\n' "${out}" ;;
        *) echo "no answer from ${INSTANCE_NAMES[$i]} (ssh rc ${rc}; stderr in ${RUN_DIR}/${i}.err)"; return 1 ;;
    esac
}

_pc_probed() { [ "$(cat "${RUN_DIR}/$1.rc" 2>/dev/null)" = 0 ]; }
_pc_kv() { sed -n "s/^$2=//p" "${RUN_DIR}/$1.out" 2>/dev/null | tail -n 1; }
_pc_jb() { if tn_json_true "$1" "$2"; then printf true; else printf false; fi; }

# _pc_addrs <ss words> <port> — the listening addresses on <port>, space separated.
_pc_addrs() { printf '%s\n' "$1" | tr ' ' '\n' | { grep -E ":$2\$" || true; } | tr '\n' ' ' | sed 's/ *$//'; }
# rc 0 when <addrs> is non-empty and every one is loopback
_pc_loopback_only() {
    [ -n "$1" ] || return 1
    [ "$(printf '%s\n' "$1" | tr ' ' '\n' | { grep -v -E '^(127\.0\.0\.1|\[::1\]):[0-9]+$' || true; } | grep -c .)" = 0 ]
}
# rc 0 when one of <addrs> listens on every interface
_pc_all_ifaces() { printf '%s\n' "$1" | tr ' ' '\n' | grep -q -E '^(0\.0\.0\.0|\*|\[::\]):[0-9]+$'; }

# _pc_http <rpc|get|ws> <url> [method] — one call from this machine. Sets H_RC (curl's rc),
# H_CODE, H_VERIFY (ssl_verify_result) and H_BODY. TLS is always verified (no -k).
H_RC=0 H_CODE="" H_VERIFY="" H_BODY=""
_pc_http() {
    local kind="$1" url="$2" bodyf="${RUN_DIR}/http.body" out="" rc=0
    : > "${bodyf}"
    case "${kind}" in
        rpc) out="$(curl -s --proto '=https' --max-time "${POSTCHECK_HTTP_TIMEOUT}" -o "${bodyf}" \
                -w '%{http_code} %{ssl_verify_result}' -X POST -H 'Content-Type: application/json' \
                --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$3\",\"params\":[]}" "${url}" 2>/dev/null)" || rc=$? ;;
        get) out="$(curl -s --proto '=https' --max-time "${POSTCHECK_HTTP_TIMEOUT}" -o "${bodyf}" \
                -w '%{http_code} %{ssl_verify_result}' "${url}" 2>/dev/null)" || rc=$? ;;
        ws) out="$(curl -s --proto '=https' --http1.1 --max-time 5 -o "${bodyf}" -w '%{http_code} %{ssl_verify_result}' \
                -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
                -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "${url}" 2>/dev/null)" || rc=$? ;;
    esac
    H_RC="${rc}"
    H_CODE="${out%% *}"
    H_VERIFY="${out#* }"
    H_BODY="$(tr -d '\r\n' < "${bodyf}")"
}

# ---- planning ----------------------------------------------------------------------------------
_pc_select() {   # prints the selected indices (array order); rc 1 on an unknown target
    local arg i hit picked="" out=""
    for arg in "$@"; do
        hit=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                picked="${picked} ${i}"; hit=1; break
            fi
        done
        if [ -z "${hit}" ]; then
            echo "❌ devnet-postcheck: unknown target '${arg}' (an index, INSTANCE_NAME or NODE_NAME)" >&2
            return 1
        fi
    done
    for i in "${!INSTANCE_NAMES[@]}"; do
        if [ "$#" -eq 0 ] || _pc_in "${i}" "${picked}"; then out="${out} ${i}"; fi
    done
    printf '%s\n' "${out# }"
}

_pc_arg() {   # _pc_arg <i> <word>... — add key=value words to host i's probe
    local i="$1" a
    shift
    for a in "$@"; do
        case "${a}" in
            *[[:space:]\'\"]*|*=) echo "❌ devnet-postcheck: bad probe argument '${a}' (check config.sh)" >&2; exit 2 ;;
        esac
        if ! _pc_in "${i}" "${PROBE_HOSTS}"; then
            PROBE_HOSTS="${PROBE_HOSTS} ${i}"
            PROBE_ARGS[i]="port=${NODE_RPC_PORT} ct=${POSTCHECK_CONNECT_TIMEOUT}"
        fi
        PROBE_ARGS[i]="${PROBE_ARGS[$i]} ${a}"
    done
}

_pc_witness() {   # _pc_witness <i> — the first validator with a same-host gateway other than i
    local w
    for w in $(tn_indices_by_role validator); do
        if [ "${w}" != "$1" ] && [ "$(tn_gateway_mode "${w}")" = same-host ]; then printf '%s\n' "${w}"; return 0; fi
    done
    return 1
}

_pc_ip() { local ip; ip="$(tn_internal_ip "$1" 2>/dev/null)" || return 1; case "${ip}" in ''|*[!0-9.]*) return 1 ;; esac; printf '%s' "${ip}"; }

_pc_plan() {
    local i g w gap=0 nip gip needs_node=0 grp
    for i in ${SEL}; do
        if tn_is_node_index "${i}"; then
            NODE_SUBJ="${NODE_SUBJ} ${i}"
            if g="$(tn_gateway_host_index "${i}")" && ! _pc_in "${g}" "${GW_HOSTS}"; then GW_HOSTS="${GW_HOSTS} ${g}"; fi
        elif [ "${NODE_ROLES[$i]}" = gateway ] && [ "${TN_GATEWAY_ENABLE:-0}" = 1 ] && ! _pc_in "${i}" "${GW_HOSTS}"; then
            GW_HOSTS="${GW_HOSTS} ${i}"
        fi
    done
    for grp in binds public rpc admission chain; do if _pc_on "${grp}"; then needs_node=1; fi; done
    if _pc_on chain; then gap="${POSTCHECK_ROUND_GAP_SECS}"; fi
    for i in ${NODE_SUBJ}; do
        if [ "${needs_node}" = 1 ]; then _pc_arg "${i}" node=1 "gap=${gap}"; fi
    done
    if _pc_on gateway; then
        for g in ${GW_HOSTS}; do
            _pc_arg "${g}" gw=1 "probe=${GATEWAY_PROBE_PORT}" "metrics=${GATEWAY_METRICS_PORT}" \
                "wait=${POSTCHECK_READY_WAIT_SECS}" "scripts=${TN_NODE_SCRIPTS_DIR}"
        done
    fi
    if _pc_on binds; then
        for i in ${NODE_SUBJ}; do
            [ "$(tn_gateway_mode "${i}")" = standalone ] || continue
            _pc_arg "${i}" meta=1
            g="$(tn_gateway_host_index "${i}")" || g=""
            w="$(_pc_witness "${i}")" || w=""
            nip="$(_pc_ip "${i}")" || nip=""
            gip=""
            if [ -n "${g}" ]; then gip="$(_pc_ip "${g}")" || gip=""; fi
            SA_GW[i]="${g}" SA_GIP[i]="${gip}" SA_NIP[i]="${nip}" SA_WIT[i]="${w}"
            [ -n "${nip}" ] || continue
            if [ -n "${g}" ]; then _pc_arg "${g}" "reach=n${i}@${nip}"; fi
            if [ -n "${w}" ]; then _pc_arg "${w}" "reach=n${i}@${nip}"; fi
        done
    fi
}

# The rpc nodes' BLS keys from genesis/<role dir>/<name>.yaml (base58, as node-info writes them).
_pc_rpc_keys() {
    local k f b58 hex keys="" n=0 all=1
    for k in $(tn_indices_by_role rpc); do
        n=$((n + 1))
        f="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis/$(tn_role_dir "${k}")/${NODE_NAMES[$k]}.yaml"
        b58="$(sed -n 's/^bls_public_key:[[:space:]]*//p' "${f}" 2>/dev/null | head -n 1 | tr -d "\"' \r")" || b58=""
        hex=""
        if [ -n "${b58}" ]; then hex="$(_pc_py b58hex <<< "${b58}")" || hex=""; fi
        if [ -z "${hex}" ]; then all=0; continue; fi
        keys="${keys} ${NODE_NAMES[$k]}=${hex}"
        RPC_B58="${RPC_B58} ${b58}"
    done
    if [ "${all}" = 1 ] && [ "${n}" -gt 0 ]; then RPC_MATCH="match=keys${keys}"; else RPC_MATCH="match=slot ${n}"; fi
}

# ---- judging ---------------------------------------------------------------------------------
_pc_gateway_checks() {   # <g>
    local g="$1" host="${INSTANCE_NAMES[$1]}" dl waited issues st ss p a desc="" bad="" lines n n1
    dl="$(_pc_kv "${g}" gw_done)"
    waited="$(_pc_kv "${g}" gw_waited)"
    if [ -z "${dl}" ]; then
        _pc_line "${host}" gateway-status FAIL "setup-gateway.sh --status --json printed no done line (/ready HTTP $(_pc_kv "${g}" gw_ready_code) after ${waited:-?}s)"
    else
        issues="$(printf '%s' "${dl}" | sed -n 's/.*"issues":\([0-9][0-9]*\).*/\1/p')"
        st="installed=$(_pc_jb "${dl}" installed) active=$(_pc_jb "${dl}" active) ready=$(_pc_jb "${dl}" ready) issues=${issues:-?} mode=$(tn_json_str "${dl}" mode)"
        if tn_json_true "${dl}" ok && tn_json_true "${dl}" installed && tn_json_true "${dl}" active \
            && tn_json_true "${dl}" ready && [ "${issues}" = 0 ]; then
            _pc_line "${host}" gateway-status ok "${st} (/ready 200 after ${waited:-?}s)"
        else
            _pc_line "${host}" gateway-status FAIL "${st} ok=$(_pc_jb "${dl}" ok) (/ready HTTP $(_pc_kv "${g}" gw_ready_code) after ${waited:-?}s of ${POSTCHECK_READY_WAIT_SECS}s)"
        fi
    fi
    ss="$(_pc_kv "${g}" ss)"
    for p in "${GATEWAY_LISTEN_PORT}" "${GATEWAY_PROBE_PORT}" "${GATEWAY_METRICS_PORT}"; do
        a="$(_pc_addrs "${ss}" "${p}")"
        desc="${desc} ${p}=[${a:-none}]"
        _pc_loopback_only "${a}" || bad=1
    done
    if [ -z "${bad}" ]; then _pc_line "${host}" gateway-listeners ok "loopback only:${desc}"
    else _pc_line "${host}" gateway-listeners FAIL "want 127.0.0.1 only:${desc}"; fi
    lines="$(sed -n 's/^gw_up=//p' "${RUN_DIR}/${g}.out")"
    n="$(printf '%s\n' "${lines}" | grep -c . || true)"
    n1="$(printf '%s\n' "${lines}" | awk 'NF && $NF + 0 == 1' | grep -c . || true)"
    if [ "${n}" -gt 0 ] && [ "${n}" = "${n1}" ]; then
        _pc_line "${host}" gateway-metrics ok "tn_worker_gateway_upstream_ready = 1 (${n} series on 127.0.0.1:${GATEWAY_METRICS_PORT})"
    else
        _pc_line "${host}" gateway-metrics FAIL "tn_worker_gateway_upstream_ready: ${n1} of ${n} series at 1: $(printf '%s' "${lines}" | tr '\n' ';' | cut -c 1-200)"
    fi
}

_pc_bind_checks() {   # <i>
    local i="$1" host="${INSTANCE_NAMES[$1]}" mode ss pair check port a
    mode="$(tn_gateway_mode "${i}")"
    case "${mode}" in same-host|standalone) ;; *) return 0 ;; esac
    ss="$(_pc_kv "${i}" ss)"
    for pair in "rpc-bind:${NODE_RPC_PORT}" "health-bind:${DEFAULT_HEALTHCHECK_TCP_PORT}"; do
        check="${pair%%:*}" port="${pair#*:}"
        a="$(_pc_addrs "${ss}" "${port}")"
        if [ "${mode}" = same-host ]; then
            if _pc_loopback_only "${a}"; then _pc_line "${host}" "${check}" ok "port ${port} on ${a} (loopback only, same-host gateway)"
            else _pc_line "${host}" "${check}" FAIL "port ${port} on [${a:-nothing}], want 127.0.0.1 only (same-host gateway)"; fi
        else
            if _pc_all_ifaces "${a}"; then _pc_line "${host}" "${check}" ok "port ${port} on ${a} (all interfaces, standalone gateway upstream)"
            else _pc_line "${host}" "${check}" FAIL "port ${port} on [${a:-nothing}], want 0.0.0.0 (standalone gateway)"; fi
        fi
    done
    if [ "${mode}" = standalone ]; then _pc_standalone_checks "${i}"; fi
}

_pc_standalone_checks() {   # <i>
    local i="$1" host="${INSTANCE_NAMES[$1]}" g="${SA_GW[$1]:-}" gip="${SA_GIP[$1]:-}" nip="${SA_NIP[$1]:-}" w="${SA_WIT[$1]:-}" rc res allow up
    if [ -z "${g}" ] || [ -z "${gip}" ] || [ -z "${nip}" ]; then
        _pc_line "${host}" upstream-from-gateway FAIL "no gateway entry or internal IP lookup failed (gateway='${g}' ip='${gip}', node ip='${nip}')"
    elif ! _pc_probed "${g}"; then
        _pc_line "${host}" upstream-from-gateway FAIL "probe of ${INSTANCE_NAMES[$g]} failed"
    else
        rc="$(_pc_kv "${g}" "reach_n${i}_rc")"
        res="$(_pc_res "$(_pc_kv "${g}" "reach_n${i}_body")")"
        if [ "${rc}" = 0 ] && [ "${res}" = "ok ${CHAIN_HEX}" ]; then
            _pc_line "${host}" upstream-from-gateway ok "${INSTANCE_NAMES[$g]} -> ${nip}:${NODE_RPC_PORT} eth_chainId=${CHAIN_HEX}"
        else
            _pc_line "${host}" upstream-from-gateway FAIL "${INSTANCE_NAMES[$g]} -> ${nip}:${NODE_RPC_PORT}: curl rc ${rc:-?}, ${res}; want ${CHAIN_HEX}"
        fi
    fi
    if [ -z "${w}" ] || [ -z "${nip}" ]; then
        _pc_line "${host}" upstream-from-other FAIL "no same-host validator to test from, or no node IP (witness='${w}' ip='${nip}')"
    elif ! _pc_probed "${w}"; then
        _pc_line "${host}" upstream-from-other FAIL "probe of ${INSTANCE_NAMES[$w]} failed"
    else
        rc="$(_pc_kv "${w}" "reach_n${i}_rc")"
        res="$(_pc_res "$(_pc_kv "${w}" "reach_n${i}_body")")"
        case "${rc}" in
            7) _pc_line "${host}" upstream-from-other ok "${INSTANCE_NAMES[$w]} -> ${nip}:${NODE_RPC_PORT} refused (curl rc 7)" ;;
            28) _pc_line "${host}" upstream-from-other ok "${INSTANCE_NAMES[$w]} -> ${nip}:${NODE_RPC_PORT} got no answer in ${POSTCHECK_CONNECT_TIMEOUT}s (curl rc 28)" ;;
            *) _pc_line "${host}" upstream-from-other FAIL "${INSTANCE_NAMES[$w]} -> ${nip}:${NODE_RPC_PORT}: curl rc ${rc:-?}, ${res}; want refused or timeout" ;;
        esac
    fi
    allow="$(_pc_kv "${i}" meta_GATEWAY_ALLOW_FROM)"
    up="$(_pc_kv "${i}" meta_GATEWAY_UPSTREAM)"
    if [ -n "${gip}" ] && { [ "${allow}" = "${gip}" ] || [ "${allow}" = "${gip}/32" ]; } && [ "${up}" = "${gip}" ]; then
        _pc_line "${host}" gateway-meta ok "GATEWAY_ALLOW_FROM=${allow} GATEWAY_UPSTREAM=${up} (gateway internal IP ${gip})"
    else
        _pc_line "${host}" gateway-meta FAIL "GATEWAY_ALLOW_FROM='${allow}' GATEWAY_UPSTREAM='${up}', want the gateway internal IP '${gip:-unknown}'"
    fi
}

_pc_identity() {   # <i> <domain> — is the public answer someone else's?
    local i="$1" dom="$2" host="${INSTANCE_NAMES[$1]}" own_mode own_key pub_mode pub_key mres mcode who="" detail
    if ! _pc_probed "${i}"; then _pc_line "${host}" public-identity FAIL "own tn_nodeMode not read (probe failed)"; return 0; fi
    own_mode="$(_pc_res "$(_pc_kv "${i}" tn_nodeMode)")"
    own_key="$(_pc_py field bls_public_key <<< "$(_pc_kv "${i}" tn_info)")"
    _pc_http rpc "https://${dom}" tn_nodeMode
    mcode="${H_CODE}"
    mres="$(_pc_res "${H_BODY}")"
    _pc_http rpc "https://${dom}" tn_info
    pub_key="$(_pc_py field bls_public_key <<< "${H_BODY}")"
    case "${own_mode}" in
        "ok "*) own_mode="${own_mode#ok }" ;;
        *) _pc_line "${host}" public-identity FAIL "own tn_nodeMode unreadable: ${own_mode}"; return 0 ;;
    esac
    case "${mres}" in
        "err -32011 "*)
            if [ "${mcode}" = 403 ]; then _pc_line "${host}" public-identity ok "tn_nodeMode via ${dom} refused by the gateway (403, -32011: no --redirect-queries); own answer ${own_mode}"
            else _pc_line "${host}" public-identity FAIL "tn_nodeMode via ${dom}: -32011 with HTTP ${mcode}, want 403"; fi
            return 0 ;;
        "ok "*) pub_mode="${mres#ok }" ;;
        *) _pc_line "${host}" public-identity FAIL "tn_nodeMode via ${dom}: curl rc ${H_RC}, HTTP ${mcode}, ${mres}"; return 0 ;;
    esac
    detail="tn_nodeMode ${pub_mode} via ${dom} (own ${own_mode})"
    if [ -n "${pub_key}" ] && [ -n "${own_key}" ]; then
        if [ -n "${RPC_B58}" ] && _pc_in "${pub_key}" "${RPC_B58}"; then who=" = the rpc node's key (query node)"; fi
        detail="${detail}; tn_info bls_public_key $(_pc_short "${pub_key}") (own $(_pc_short "${own_key}"))${who}"
        if [ "${pub_key}" = "${own_key}" ]; then
            _pc_line "${host}" public-identity FAIL "answered by this node itself: ${detail}"
        elif [ "${pub_mode}" = "${own_mode}" ] && [ "${own_mode}" != Observer ]; then
            _pc_line "${host}" public-identity FAIL "the mode is this node's own (${own_mode}) though the key differs: ${detail}"
        else
            _pc_line "${host}" public-identity ok "answered by another node: ${detail}"
        fi
    else
        detail="${detail}; tn_info key not readable (public '$(_pc_short "${pub_key}")', own '$(_pc_short "${own_key}")')"
        if [ "${pub_mode}" != "${own_mode}" ]; then _pc_line "${host}" public-identity ok "${detail}"
        elif [ "${own_mode}" = Observer ]; then _pc_line "${host}" public-identity not-decisive "${detail}"
        else _pc_line "${host}" public-identity FAIL "same answer as this node: ${detail}"; fi
    fi
}

_pc_public_checks() {   # <i>
    local i="$1" host="${INSTANCE_NAMES[$1]}" dom res
    dom="$(tn_public_domain "${i}")"
    _pc_http rpc "https://${dom}" eth_chainId
    res="$(_pc_res "${H_BODY}")"
    if [ "${H_RC}" = 0 ] && [ "${H_CODE}" = 200 ] && [ "${res}" = "ok ${CHAIN_HEX}" ]; then
        _pc_line "${host}" public-chainid ok "https://${dom} eth_chainId=${CHAIN_HEX} (${CHAIN_ID})"
    else
        _pc_line "${host}" public-chainid FAIL "https://${dom}: curl rc ${H_RC}, HTTP ${H_CODE}, ${res}; want ${CHAIN_HEX}"
    fi
    _pc_http get "https://${dom}/health"
    if [ "${H_RC}" = 0 ] && [ "${H_VERIFY}" = 0 ]; then
        _pc_line "${host}" public-tls ok "certificate for ${dom} verified by curl (CA chain and host name), GET /health HTTP ${H_CODE}"
    else
        _pc_line "${host}" public-tls FAIL "https://${dom}/health: curl rc ${H_RC} (35 handshake, 51/60 certificate), ssl_verify_result=${H_VERIFY}"
    fi
    _pc_http ws "https://${dom}/"
    if [ "${H_CODE}" = 405 ]; then _pc_line "${host}" public-ws ok "WebSocket upgrade to wss://${dom} refused: HTTP 405"
    else _pc_line "${host}" public-ws FAIL "WebSocket upgrade to wss://${dom}: HTTP ${H_CODE:-none} (curl rc ${H_RC}), want 405 (101 = upgraded)"; fi
    _pc_http get "https://${dom}/ready/any"
    if [ "${H_CODE}" = 200 ]; then _pc_line "${host}" public-ready-any ok "GET https://${dom}/ready/any 200 ${H_BODY:0:80}"
    else _pc_line "${host}" public-ready-any FAIL "GET https://${dom}/ready/any HTTP ${H_CODE:-none} (curl rc ${H_RC}) ${H_BODY:0:80}"; fi
    _pc_identity "${i}" "${dom}"
}

_pc_rpc_checks() {   # <i>
    local host="${INSTANCE_NAMES[$1]}" res
    if [ "${NO_PUBLIC}" = 0 ]; then
        _pc_http rpc "https://${RPC_HOSTNAME}" eth_chainId
        res="$(_pc_res "${H_BODY}")"
        if [ "${H_RC}" = 0 ] && [ "${H_CODE}" = 200 ] && [ "${res}" = "ok ${CHAIN_HEX}" ]; then
            _pc_line "${host}" rpc-https ok "https://${RPC_HOSTNAME} eth_chainId=${CHAIN_HEX}, certificate verified"
        else
            _pc_line "${host}" rpc-https FAIL "https://${RPC_HOSTNAME}: curl rc ${H_RC}, HTTP ${H_CODE}, ${res}; want ${CHAIN_HEX}"
        fi
        _pc_http ws "https://${RPC_HOSTNAME}/"
        if [ "${H_CODE}" = 101 ]; then _pc_line "${host}" rpc-wss ok "WebSocket upgrade to wss://${RPC_HOSTNAME}: HTTP 101"
        else _pc_line "${host}" rpc-wss FAIL "WebSocket upgrade to wss://${RPC_HOSTNAME}: HTTP ${H_CODE:-none} (curl rc ${H_RC}), want 101"; fi
    fi
}

# _pc_waited_note <i|chain> — " (read after a <n>s settle wait)" when that data was re-read
# (_pc_settle marks each re-read in the host's output), nothing otherwise.
_pc_waited_note() {
    local s="${PC_WAITED}"
    if [ "$1" != chain ]; then
        s="$(sed -n 's/^# re-read at +\([0-9][0-9]*\)s$/\1/p' "${RUN_DIR}/$1.out" 2>/dev/null | tail -n 1)"
    fi
    if [ "${s:-0}" -gt 0 ]; then printf ' (read after a %ss settle wait)' "${s}"; fi
}

_pc_rpc_admission_check() {   # <i>
    local i="$1" v
    v="$(_pc_py snap Open <<< "$(_pc_kv "${i}" tn_admissionSnapshot)")" || v=""
    case "${v}" in ok\ *|FAIL\ *) ;; *) v="FAIL snapshot not judged: ${v}" ;; esac
    _pc_line "${INSTANCE_NAMES[$i]}" rpc-admission "${v%% *}" "${v#* }$(_pc_waited_note "${i}")"
}

_pc_admission_check() {   # <i>
    local i="$1" v
    # shellcheck disable=SC2086  # RPC_MATCH is a word list (names and hex keys)
    v="$(_pc_py snap Closed ${RPC_MATCH} <<< "$(_pc_kv "${i}" tn_admissionSnapshot)")" || v=""
    case "${v}" in ok\ *|FAIL\ *) ;; *) v="FAIL snapshot not judged: ${v}" ;; esac
    _pc_line "${INSTANCE_NAMES[$i]}" admission "${v%% *}" "${v#* }$(_pc_waited_note "${i}")"
}

# _pc_settled_checks <i> — host i's checks that need its peers (rpc-admission, admission)
_pc_settled_checks() {
    if _pc_on rpc && [ "${NODE_ROLES[$1]}" = rpc ]; then _pc_rpc_admission_check "$1"; fi
    if _pc_on admission; then
        case "${NODE_ROLES[$1]}" in validator|observer) _pc_admission_check "$1" ;; esac
    fi
}

_pc_chain_checks() {
    local i v h c1 c2 nv=0 na=0 bad="" heads="" min="" max="" hbad="" cons="" cbad="" nc=0 wn
    wn="$(_pc_waited_note chain)"
    for i in ${NODE_SUBJ}; do
        if [ "${NODE_ROLES[$i]}" = validator ]; then
            nv=$((nv + 1))
            v="no-answer"
            if _pc_probed "${i}"; then v="$(_pc_res "$(_pc_kv "${i}" tn_nodeMode)")"; v="${v#ok }"; fi
            if [ "${v}" = CvvActive ]; then na=$((na + 1)); else bad="${bad} ${NODE_NAMES[$i]}=${v}"; fi
        fi
        _pc_probed "${i}" || { hbad="${hbad} ${NODE_NAMES[$i]}=no-answer"; continue; }
        h="$(_pc_py num - <<< "$(_pc_kv "${i}" head2)")"
        [ -n "${h}" ] || h="$(_pc_py num - <<< "$(_pc_kv "${i}" head1)")"
        if [ -z "${h}" ]; then hbad="${hbad} ${NODE_NAMES[$i]}=unreadable"; else
            heads="${heads} ${NODE_NAMES[$i]}=${h}"
            if [ -z "${min}" ] || [ "${h}" -lt "${min}" ]; then min="${h}"; fi
            if [ -z "${max}" ] || [ "${h}" -gt "${max}" ]; then max="${h}"; fi
        fi
        if [ "${NODE_ROLES[$i]}" = validator ]; then
            nc=$((nc + 1))
            c1="$(_pc_py num number <<< "$(_pc_kv "${i}" cons1)")"
            c2="$(_pc_py num number <<< "$(_pc_kv "${i}" cons2)")"
            cons="${cons} ${NODE_NAMES[$i]}=${c1:-?}->${c2:-?}"
            if [ -z "${c1}" ] || [ -z "${c2}" ] || [ "${c2}" -le "${c1}" ]; then cbad="${cbad} ${NODE_NAMES[$i]}"; fi
        fi
    done
    if [ "${nv}" -gt 0 ]; then
        if [ -z "${bad}" ]; then _pc_line chain validators-active ok "${na}/${nv} genesis validators report CvvActive${wn}"
        else _pc_line chain validators-active FAIL "${na}/${nv} CvvActive; not:${bad}${wn}"; fi
    fi
    if [ -n "${heads}${hbad}" ]; then
        if [ -z "${hbad}" ] && [ $((max - min)) -le "${POSTCHECK_HEAD_LAG}" ]; then
            _pc_line chain heads ok "spread $((max - min)) <= ${POSTCHECK_HEAD_LAG} blocks (eth_blockNumber, sampled in parallel):${heads}${wn}"
        else
            _pc_line chain heads FAIL "spread $(( ${max:-0} - ${min:-0} )) (max ${POSTCHECK_HEAD_LAG}):${heads}${hbad:+; unread:${hbad}}${wn}"
        fi
    fi
    if [ "${nc}" -gt 0 ]; then
        if [ -z "${cbad}" ]; then _pc_line chain consensus-progress ok "tn_latestConsensusHeader .number rose over ${POSTCHECK_ROUND_GAP_SECS}s on every validator:${cons}${wn}"
        else _pc_line chain consensus-progress FAIL "no rise over ${POSTCHECK_ROUND_GAP_SECS}s on${cbad} (tn_latestConsensusHeader .number):${cons}${wn}"; fi
    fi
}

_pc_report() {
    local h
    for h in "${!INSTANCE_NAMES[@]}"; do
        if _pc_in "${h}" "${PROBE_HOSTS}" && ! _pc_probed "${h}" && { _pc_in "${h}" "${SEL}" || _pc_in "${h}" "${GW_HOSTS}"; }; then
            _pc_line "${INSTANCE_NAMES[$h]}" probe FAIL "$(head -n 1 "${RUN_DIR}/${h}.out" 2>/dev/null)"
        fi
        if _pc_on gateway && _pc_in "${h}" "${GW_HOSTS}" && _pc_probed "${h}"; then _pc_gateway_checks "${h}"; fi
        _pc_in "${h}" "${NODE_SUBJ}" || continue
        if _pc_on binds && _pc_probed "${h}"; then _pc_bind_checks "${h}"; fi
        if _pc_on public && tn_gateway_host_index "${h}" >/dev/null; then _pc_public_checks "${h}"; fi
        if _pc_on rpc && [ "${NODE_ROLES[$h]}" = rpc ]; then _pc_rpc_checks "${h}"; fi
    done
}

# _pc_report_settled — the checks that need peers, after _pc_settle (see "Settling" above)
_pc_report_settled() {
    local h
    for h in ${NODE_SUBJ}; do
        if _pc_probed "${h}"; then _pc_settled_checks "${h}"; fi
    done
    if _pc_on chain; then _pc_chain_checks; fi
}

# _pc_pending — the node hosts to re-read: the probed ones whose rpc-admission / admission does
# not pass yet; all probed ones when anything is pending and the chain group runs (its samples are
# compared across hosts). Judged quietly (PC_DRY); call it in $( ).
_pc_pending() {
    local h out="" all=""
    PC_DRY=1
    for h in ${NODE_SUBJ}; do
        _pc_probed "${h}" || continue
        all="${all} ${h}"
        PC_DRY_FAIL=0
        _pc_settled_checks "${h}"
        if [ "${PC_DRY_FAIL}" = 1 ]; then out="${out} ${h}"; fi
    done
    PC_DRY_FAIL=0
    if _pc_on chain; then _pc_chain_checks; fi
    if [ "${PC_DRY_FAIL}" = 1 ] || { [ -n "${out}" ] && _pc_on chain; }; then out="${all}"; fi
    printf '%s' "${out}"
}

# _pc_settle — re-read the hosts _pc_pending names (node reads only, in parallel) every
# POSTCHECK_RETRY_SECS until it names none or POSTCHECK_SETTLE_SECS have gone by. A re-read is
# appended to the host's output under a "# re-read at +<n>s" line (_pc_kv takes a key's last
# value); a failed re-read leaves the output as it was. No wait when a check already failed.
_pc_settle() {
    local start="${SECONDS}" pending i a words pids p
    pending="$(_pc_pending)"
    if [ -n "${pending}" ] && [ "${N_FAIL}" -gt 0 ]; then
        echo "devnet-postcheck: ${N_FAIL} check(s) failed already, so no settle wait: the checks that need peers are judged on the first read" >&2
        return 0
    fi
    while [ -n "${pending}" ] && [ $((SECONDS - start)) -lt "${POSTCHECK_SETTLE_SECS}" ]; do
        echo "    … not settled yet on$(for i in ${pending}; do printf ' %s' "${INSTANCE_NAMES[$i]}"; done); re-reading in ${POSTCHECK_RETRY_SECS}s ($((SECONDS - start))s of ${POSTCHECK_SETTLE_SECS}s)" >&2
        sleep "${POSTCHECK_RETRY_SECS}"
        pids=""
        for i in ${pending}; do
            words=""
            for a in ${PROBE_ARGS[$i]:-}; do case "${a}" in node=*|gap=*|port=*|ct=*) words="${words} ${a}" ;; esac; done
            (
                if _pc_probe "${i}" "${words}" > "${RUN_DIR}/${i}.reread"; then
                    { echo "# re-read at +$((SECONDS - start))s"; cat "${RUN_DIR}/${i}.reread"; } >> "${RUN_DIR}/${i}.out"
                fi
            ) &
            pids="${pids} $!"
        done
        for p in ${pids}; do wait "${p}" || true; done
        PC_WAITED=$((SECONDS - start))
        pending="$(_pc_pending)"
    done
}

main() {
    local pids="" p i v missing=0
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help) _usage; exit 0 ;;
            --only)
                if [ "$#" -lt 2 ] || ! _pc_in "$2" "${PC_GROUPS}"; then
                    echo "❌ devnet-postcheck: --only takes one of: ${PC_GROUPS}" >&2; exit 2
                fi
                ONLY="${ONLY} $2"; shift 2 ;;
            --no-public) NO_PUBLIC=1; shift ;;
            --) shift; break ;;
            -*) echo "❌ devnet-postcheck: unknown option $1" >&2; _usage >&2; exit 2 ;;
            *) break ;;
        esac
    done
    tn_fleet_check || { echo "❌ devnet-postcheck: fleet arrays inconsistent (config.sh)" >&2; exit 2; }
    for v in POSTCHECK_READY_WAIT_SECS POSTCHECK_HEAD_LAG POSTCHECK_ROUND_GAP_SECS POSTCHECK_CONNECT_TIMEOUT \
        POSTCHECK_HTTP_TIMEOUT POSTCHECK_RETRY_SECS POSTCHECK_SETTLE_SECS NODE_RPC_PORT DEFAULT_HEALTHCHECK_TCP_PORT CHAIN_ID \
        GATEWAY_LISTEN_PORT GATEWAY_PROBE_PORT GATEWAY_METRICS_PORT; do
        case "${!v:-}" in ''|*[!0-9]*) echo "❌ devnet-postcheck: ${v}='${!v:-}' is not a number" >&2; exit 2 ;; esac
    done
    if ! SEL="$(_pc_select "$@")"; then exit 2; fi
    command -v python3 >/dev/null 2>&1 || { echo "❌ devnet-postcheck: python3 is required here (it judges the JSON answers)" >&2; missing=1; }
    if { _pc_on public || _pc_on rpc; } && [ "${NO_PUBLIC}" = 0 ] && ! command -v curl >/dev/null 2>&1; then
        echo "❌ devnet-postcheck: curl is required here for the https checks (or pass --no-public)" >&2; missing=1
    fi
    if [ "${TN_SSH_TRANSPORT}" = iap ] && ! command -v gcloud >/dev/null 2>&1; then
        echo "❌ devnet-postcheck: gcloud is required here (IAP ssh, internal-IP lookups)" >&2; missing=1
    fi
    [ "${missing}" = 0 ] || exit 2
    CHAIN_HEX="$(printf '0x%x' "${CHAIN_ID}")"
    RUN_DIR="${POSTCHECK_LOG_DIR:-${REPO_ROOT}/logs/$(date -u +%Y%m%dT%H%M%SZ)-postcheck}"
    mkdir -p "${RUN_DIR}"
    : > "${RUN_DIR}/postcheck.txt"
    _pc_plan
    if _pc_on admission || _pc_on public; then _pc_rpc_keys; fi
    echo "devnet-postcheck: probing${PROBE_HOSTS:+ }$(for i in ${PROBE_HOSTS}; do printf '%s ' "${INSTANCE_NAMES[$i]}"; done)(in parallel; gateway readiness wait up to ${POSTCHECK_READY_WAIT_SECS}s, settle wait up to ${POSTCHECK_SETTLE_SECS}s)" >&2
    for i in ${PROBE_HOSTS}; do
        ( rc=0; _pc_probe "${i}" > "${RUN_DIR}/${i}.out" || rc=$?; echo "${rc}" > "${RUN_DIR}/${i}.rc" ) &
        pids="${pids} $!"
    done
    for p in ${pids}; do wait "${p}" || true; done
    _pc_report
    _pc_settle
    _pc_report_settled
    echo "devnet-postcheck: ${N_CHECKS} checks, ${N_FAIL} failed, ${N_ND} not decisive; probe outputs in ${RUN_DIR}" >&2
    [ "${N_FAIL}" -eq 0 ] || exit 1
    exit 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
