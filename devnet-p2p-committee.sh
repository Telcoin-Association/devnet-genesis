#!/usr/bin/env bash
#
# devnet-p2p-committee.sh — turn on tn-node-deployment's committee P2P allowlist
# (`firewall-setup.sh --p2p-committee on`) on each validator, ONE HOST AT A TIME, and prove
# after each host that the committee is still whole. Deploy step 20.
#
# After this step a validator's P2P ports accept UDP only from the sources its node lists
# (committee windows, the eligible pool, trusted and bootstrap peers): an nft table
# `inet tn_p2p_allow` that tn-p2p-allow-sync refreshes from the node's tn_admissionSnapshot
# every 5 minutes. A wrong allowlist cuts a validator off from its committee, which with
# four validators is one fault away from a stall, so this driver is conservative: it checks
# the committee is whole before the first change, changes one host, asserts, and stops the
# sweep at the first doubt (later hosts are reported untouched).
#
# usage: ./devnet-p2p-committee.sh [--yes] [--status] [--off] [--allow-rpc] [target ...]
#   (no flag)    dry run: per host, the remote commands and what will be asserted; no ssh
#   --yes        turn it on (steps 1-6 below, per host)
#   --status     read-only: per host the state, the `check` verdict and the counters
#   --off --yes  the documented way back: `firewall-setup.sh --p2p-committee off` per host,
#                one at a time, with the same committee-whole assertion (--off alone: dry run)
#   --allow-rpc  let an `rpc` entry be a target (refused otherwise: its P2P is meant to stay
#                open to any source)
#   target       an index (0-based), an INSTANCE_NAME or a NODE_NAME. None = every index of
#                role `validator`, in array order. Node 5 (`observer`) only when named. A
#                `gateway` entry (no node) is refused.
#
# Exit: 0 ok · 1 a host failed (the sweep stopped there; later hosts untouched) or, with
# --status, a host that should be on is not `check` ok or did not answer · 2 usage or config
# · 3 a host's admission snapshot did not become authoritative within P2P_COMMITTEE_WAIT_SECS
# (nothing was changed on that host; later hosts untouched).
#
# Per host, with --yes (step 0 runs once, before the first host: every validator's unit is
# active, tn_nodeMode is CvvActive and the heads are within P2P_COMMITTEE_HEAD_LAG):
#   1. pre-state, one read-only round trip: the node unit is active; ufw is active;
#      /usr/sbin/nft exists; .node-meta P2P_COMMITTEE (already `on` -> `already-on`, step 2
#      is skipped, steps 3-5 still run: `on` then resyncs); tn_nodeMode (a validator must be
#      CvvActive); the head block number.
#   2. poll tn_admissionSnapshot on 127.0.0.1:${NODE_RPC_PORT} ON THE HOST (the node image
#      has no curl; the VM has) until the primary swarm has `available` true, `tracked_epoch`
#      set and `admission.fallback` null or "Unresolved" (the allow-sync tool's own rule),
#      at most P2P_COMMITTEE_WAIT_SECS; on timeout print the last effective/fallback, exit 3.
#   3. `sudo bash <scripts>/firewall-setup.sh --p2p-committee on </dev/null`: rc 0 on; rc 1
#      refused, nothing changed (retried every P2P_COMMITTEE_RETRY_SECS, at most
#      P2P_COMMITTEE_RETRIES times, while its text matches PC_RETRY_RE below; any other rc 1
#      fails the host); rc 2 undone (fails, nothing changed); rc 3 partial (fails; the kill
#      switch is printed first: P2P may be partly filtered).
#   4. `sudo tn-p2p-allow-sync check` must exit 0 (verdict `ok`: every current committee
#      address is in the set); then `firewall-setup.sh --p2p-committee status` (allowlist
#      and counters lines). Exit 1 or 3: the kill switch, then the missing addresses.
#   5. the committee is whole before the next host, within P2P_COMMITTEE_SETTLE_SECS: this
#      host's tn_nodeMode is what step 1 read; every validator's unit is active and
#      CvvActive; all heads (read in parallel) within P2P_COMMITTEE_HEAD_LAG blocks; with
#      P2P_COMMITTEE_REQUIRE_ADVANCE=1 this host's head is higher than in step 1 (the
#      transaction generator runs from deploy step 19, so blocks come every few seconds).
#      With 0 (an idle chain makes a block only at an epoch close) the whole settle time is
#      waited and the rest is asserted at its end.
#   6. prints `P2P_COMMITTEE <instance> on epoch=<n> v4=<n> v6=<n> keys=<n> check=ok
#      mode=<mode> head=<n>` (EPOCH, ALLOWED_V4, ALLOWED_V6, KEYS from the tool's status).
#
# Knobs (environment): P2P_COMMITTEE_WAIT_SECS (config.sh, 300; an environment value wins)
# · P2P_COMMITTEE_POLL_SECS (5) · P2P_COMMITTEE_RETRY_SECS (15) · P2P_COMMITTEE_RETRIES (8)
# · P2P_COMMITTEE_SETTLE_SECS (60) · P2P_COMMITTEE_HEAD_LAG (5) ·
# P2P_COMMITTEE_REQUIRE_ADVANCE (1). Read-only probes get one extra try on ssh rc 255; the
# mutating `on` / `off` calls get none from this script.
#
# nftables.service: this driver NEVER starts or enables nftables.service and NEVER writes
# /etc/nftables.conf. Ubuntu's stock /etc/nftables.conf begins with `flush ruleset`, which
# would wipe docker's and ufw's rules. tn-node-deployment installs its own units
# (telcoin-p2p-allow.service loads only its own table at boot; telcoin-p2p-allow-sync.timer
# refreshes it); this script only calls firewall-setup.sh.
#
# Node 5 (observer) is never a default target. Before it stakes, its only peer is the RPC
# node (rpc-6), and its snapshot is authoritative only while that peer is up (while rpc-6
# is down node 5 sits in Grace / Unresolved and `on` cannot be turned on there). So turn it
# on there, if at all, by name (`--yes node5`) while rpc-6 is up and node 5 has synced;
# step 5 then asserts node 5 keeps the mode step 1 read (Observer before it stakes). Nothing
# needs re-running on the validators when node 5 joins: once it is eligible, their
# allowlists pick up its address at their next 5-minute sync, which is what the join
# rehearsal watches.
#
# Kill switch (one host): on the host, `sudo bash <scripts>/firewall-setup.sh --p2p-committee
# off` (it never needs the tool or the node). In an emergency run that on the host directly:
# `--off --yes` here stops at the first host after which the committee is not whole.
#
# Logs: logs/<stamp>-p2p-committee/<instance>.log (every remote answer), committee.log
# (the committee-whole probes).

set -euo pipefail

PC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_pc_env_wait="${P2P_COMMITTEE_WAIT_SECS:-}"
# shellcheck source=devnet-lib.sh
source "${PC_DIR}/devnet-lib.sh"
# config.sh assigns P2P_COMMITTEE_WAIT_SECS unconditionally; an operator's value wins.
[ -n "${_pc_env_wait}" ] && P2P_COMMITTEE_WAIT_SECS="${_pc_env_wait}"
unset _pc_env_wait

tn_fleet_check || exit 2

PC_TOOL="/usr/local/libexec/telcoin/tn-p2p-allow-sync"
PC_ALLOW_DIR="/var/lib/telcoin-p2p-allow"
# firewall-setup.sh's rc-1 texts that mean "the snapshot is not usable yet" (retried). They are
# the texts of its fw_allow_reason_text: the generic "the admission snapshot of the node is not
# authoritative[ (<reason>)]", the empty-set text "the snapshot lists no addresses beyond the
# floor and static list", and "the node RPC does not answer on 127.0.0.1 (rpc-unreachable)".
# Its other refusals (a node release without tn_admissionSnapshot, ufw not active, a missing
# nft) do not clear by waiting and are not retried.
PC_RETRY_RE='not authoritative|lists no addresses beyond the floor|rpc-unreachable'

P2P_COMMITTEE_WAIT_SECS="${P2P_COMMITTEE_WAIT_SECS:-300}"
P2P_COMMITTEE_POLL_SECS="${P2P_COMMITTEE_POLL_SECS:-5}"
P2P_COMMITTEE_RETRY_SECS="${P2P_COMMITTEE_RETRY_SECS:-15}"
P2P_COMMITTEE_RETRIES="${P2P_COMMITTEE_RETRIES:-8}"
P2P_COMMITTEE_SETTLE_SECS="${P2P_COMMITTEE_SETTLE_SECS:-60}"
P2P_COMMITTEE_HEAD_LAG="${P2P_COMMITTEE_HEAD_LAG:-5}"
P2P_COMMITTEE_REQUIRE_ADVANCE="${P2P_COMMITTEE_REQUIRE_ADVANCE:-1}"

pc_usage() { sed -n '15,25p' "${PC_DIR}/devnet-p2p-committee.sh" | sed 's/^# \{0,1\}//'; }

for _k in P2P_COMMITTEE_WAIT_SECS P2P_COMMITTEE_POLL_SECS P2P_COMMITTEE_RETRY_SECS \
    P2P_COMMITTEE_RETRIES P2P_COMMITTEE_SETTLE_SECS P2P_COMMITTEE_HEAD_LAG NODE_RPC_PORT; do
    case "${!_k:-}" in
        ''|*[!0-9]*) echo "❌ ${_k} must be a non-negative integer (got '${!_k:-}')" >&2; exit 2 ;;
    esac
done
case "${P2P_COMMITTEE_REQUIRE_ADVANCE}" in
    0|1) ;;
    *) echo "❌ P2P_COMMITTEE_REQUIRE_ADVANCE must be 0 or 1 (got '${P2P_COMMITTEE_REQUIRE_ADVANCE}')" >&2; exit 2 ;;
esac
[ "${P2P_COMMITTEE_POLL_SECS}" -ge 1 ] || { echo "❌ P2P_COMMITTEE_POLL_SECS must be at least 1" >&2; exit 2; }

YES=0; STATUS=0; OFF=0; ALLOW_RPC=0; ARGS=()
for _a in "$@"; do
    case "${_a}" in
        --yes) YES=1 ;;
        --status) STATUS=1 ;;
        --off) OFF=1 ;;
        --allow-rpc) ALLOW_RPC=1 ;;
        -h|--help) pc_usage; exit 0 ;;
        -*) echo "❌ unknown option: ${_a}" >&2; pc_usage >&2; exit 2 ;;
        *) ARGS+=("${_a}") ;;
    esac
done
if [ "${STATUS}" -eq 1 ] && [ "${OFF}" -eq 1 ]; then
    echo "❌ --status and --off do not go together" >&2; pc_usage >&2; exit 2
fi
VERB=on
[ "${OFF}" -eq 1 ] && VERB=off

PC_VALIDATORS=()
for _i in $(tn_indices_by_role validator); do PC_VALIDATORS+=("${_i}"); done
if [ "${#PC_VALIDATORS[@]}" -eq 0 ]; then
    echo "❌ no entry of role validator in NODE_ROLES" >&2; exit 2
fi

# pc_resolve <target> — the index an index / INSTANCE_NAME / NODE_NAME names; rc 1 if none.
pc_resolve() {
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        if [ "$1" = "${i}" ] || [ "$1" = "${INSTANCE_NAMES[$i]}" ] || [ "$1" = "${NODE_NAMES[$i]}" ]; then
            printf '%s\n' "${i}"; return 0
        fi
    done
    return 1
}

TARGETS=()
if [ "${#ARGS[@]}" -eq 0 ]; then
    TARGETS=("${PC_VALIDATORS[@]}")
else
    for _a in "${ARGS[@]}"; do
        _i="$(pc_resolve "${_a}")" || {
            echo "❌ unknown target: ${_a} (expected an index, INSTANCE_NAME or NODE_NAME)" >&2; exit 2; }
        case "${NODE_ROLES[$_i]}" in
            validator|observer) ;;
            rpc)
                if [ "${ALLOW_RPC}" -ne 1 ]; then
                    echo "❌ ${INSTANCE_NAMES[$_i]} is the rpc node: its P2P is meant to stay open to any source (pass --allow-rpc to target it anyway)" >&2
                    exit 2
                fi ;;
            gateway) echo "❌ ${INSTANCE_NAMES[$_i]} is a gateway entry (no node, no P2P): refused" >&2; exit 2 ;;
            *) echo "❌ ${INSTANCE_NAMES[$_i]} has role '${NODE_ROLES[$_i]}': refused" >&2; exit 2 ;;
        esac
        case " ${TARGETS[*]+"${TARGETS[*]}"} " in *" ${_i} "*) ;; *) TARGETS+=("${_i}") ;; esac
    done
fi

# --- remote commands ---------------------------------------------------------------------

# PC_PROBE_BODY — one read-only round trip ON THE HOST (quoted heredoc: nothing expands
# here; p and svc are set in front of it by pc_probe_cmd). Always ends with one
# "__tn_pc_probe ..." line, so the ssh rc reflects transport only.
IFS= read -r -d '' PC_PROBE_BODY <<'EOF' || true
u="$(systemctl is-active "$svc" 2>/dev/null)"
f="$(sudo ufw status 2>/dev/null | sed -n 's/^Status: //p' | head -n 1)"
if [ -x /usr/sbin/nft ]; then n=yes; else n=no; fi
c="$(sudo sed -n 's/^P2P_COMMITTEE=//p' /etc/telcoin/.node-meta 2>/dev/null | tail -n 1)"
rpc() { curl -s --max-time 5 -H 'Content-Type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":[]}" "http://127.0.0.1:$p" 2>/dev/null; }
m="$(rpc tn_nodeMode | sed -n 's/.*"result":"\([A-Za-z]*\)".*/\1/p')"
x="$(rpc eth_blockNumber | sed -n 's/.*"result":"\(0x[0-9a-fA-F]*\)".*/\1/p')"
h=""; [ -n "$x" ] && h="$(printf '%d' "$x" 2>/dev/null)"
echo "__tn_pc_probe unit=${u:-unknown} ufw=${f:-unknown} nft=$n committee=${c:-off} mode=${m:-unknown} head=${h:-unknown}"
EOF

# PC_SNAP_BODY — the raw tn_admissionSnapshot answer on one "__tn_pc_snap" line.
IFS= read -r -d '' PC_SNAP_BODY <<'EOF' || true
r="$(curl -s --max-time 5 -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"tn_admissionSnapshot","params":[]}' "http://127.0.0.1:$p" 2>/dev/null | tr -d '\n')"
printf '__tn_pc_snap %s\n' "${r:-none}"
EOF

# PC_SNAP_PY — judges one JSON-RPC answer locally (stdin) by the allow-sync tool's rule for
# an authoritative snapshot; prints "auth=yes|no epoch= effective= fallback= why=".
IFS= read -r -d '' PC_SNAP_PY <<'EOF' || true
import json, sys
def out(auth, ep=None, eff=None, fb=None, why="-"):
    s = lambda v: "null" if v is None else str(v)
    print("auth=%s epoch=%s effective=%s fallback=%s why=%s" % (auth, s(ep), s(eff), s(fb), why))
    sys.exit(0)
try:
    doc = json.loads(sys.stdin.read().strip())
except ValueError:
    out("no", why="no-snapshot")
if not isinstance(doc, dict) or "result" not in doc:
    out("no", why="rpc-error")
snap = doc["result"]
if not isinstance(snap, dict) or snap.get("version") != 1:
    out("no", why="version")
prim = [w for w in (snap.get("swarms") or []) if isinstance(w, dict) and w.get("network") == "primary"]
if not prim:
    out("no", why="no-primary")
w = prim[0]
adm = w.get("admission") if isinstance(w.get("admission"), dict) else None
ep = w.get("tracked_epoch")
eff = adm.get("effective") if adm else None
fb = adm.get("fallback") if adm else None
if w.get("available") is not True:
    out("no", ep, eff, fb, "unavailable")
if isinstance(ep, bool) or not isinstance(ep, int):
    out("no", ep, eff, fb, "no-tracked-epoch")
if adm is None:
    out("no", ep, eff, fb, "no-admission")
if fb not in (None, "Unresolved"):
    out("no", ep, eff, fb, "fallback")
aep = adm.get("epoch")
if isinstance(aep, int) and not isinstance(aep, bool) and ep < aep:
    out("no", ep, eff, fb, "tracked-behind-admission")
out("yes", ep, eff, fb)
EOF

pc_probe_cmd() { printf 'p=%s; svc=%s\n%s' "${NODE_RPC_PORT}" "$(tn_service_for_role validator)" "${PC_PROBE_BODY}"; }
pc_snap_cmd() { printf 'p=%s\n%s' "${NODE_RPC_PORT}" "${PC_SNAP_BODY}"; }
# pc_fw_cmd <on|off> — the mutating call; its rc travels back on a sentinel line.
pc_fw_cmd() {
    printf '%s' "sudo bash '${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh' --p2p-committee $1 </dev/null 2>&1; echo \"__tn_pc_rc=\$?\""
}
# pc_check_cmd — read-only: the tool's check (rc on a sentinel), its status keys (live, then
# the status file), firewall-setup.sh's human status. Section markers delimit each part.
pc_check_cmd() {
    printf '%s' "echo __tn_pc_check_begin; sudo '${PC_TOOL}' check 2>&1; echo \"__tn_pc_check_rc=\$?\"; echo __tn_pc_sect_status; sudo '${PC_TOOL}' status 2>/dev/null; sudo cat '${PC_ALLOW_DIR}/status' 2>/dev/null; echo __tn_pc_sect_fw; sudo bash '${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh' --p2p-committee status </dev/null 2>&1; echo __tn_pc_end"
}

# --- helpers -----------------------------------------------------------------------------

pc_field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | head -n 1; }
pc_kv() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | tail -n 1; }
pc_isnum() { case "${1:-}" in ''|*[!0-9]*) return 1 ;; esac; return 0; }

# pc_ssh_ro <idx> <cmd> <log> — a read-only round trip: stdout = the answer (CR stripped),
# stderr to <log>; one extra try on rc 255 (the lib already retries transport faults).
pc_ssh_ro() {
    local out rc=0
    out="$(tn_iap_ssh "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}" "$2" </dev/null 2>>"$3")" || rc=$?
    if [ "${rc}" -eq 255 ]; then
        echo "ssh rc 255 on ${INSTANCE_NAMES[$1]}: one more try" >>"$3"
        rc=0
        out="$(tn_iap_ssh "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}" "$2" </dev/null 2>>"$3")" || rc=$?
    fi
    printf '%s\n' "${out}" | tr -d '\r'
    return "${rc}"
}

# pc_probe <idx> <log> — prints "unit= ufw= nft= committee= mode= head="; rc 1 on no answer.
pc_probe() {
    local out
    out="$(pc_ssh_ro "$1" "$(pc_probe_cmd)" "$2")" || true
    out="$(printf '%s\n' "${out}" | grep '^__tn_pc_probe ' | tail -n 1)" || true
    [ -n "${out}" ] || return 1
    printf '%s\n' "${out#__tn_pc_probe }"
}

# pc_kill_switch <idx> — printed FIRST whenever a host may be left partly filtered.
pc_kill_switch() {
    local inst="${INSTANCE_NAMES[$1]}"
    {
        echo "    🛑 KILL SWITCH for ${inst}: P2P on ${inst} may be partly filtered. To open it to every source again:"
        echo "         gcloud compute ssh ${inst} --zone=${ZONES[$1]} --project=${PROJECT_ID} --tunnel-through-iap --command=\"sudo bash '${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh' --p2p-committee off </dev/null\""
        echo "       (or ./devnet-p2p-committee.sh --off --yes ${inst})"
    } >&2
}

# pc_wait_snapshot <idx> <log> — step 2. rc 0 authoritative; rc 1 not within the wait.
pc_wait_snapshot() {
    local i="$1" log="$2" start="${SECONDS}" el raw ev last=""
    echo "    + (every ${P2P_COMMITTEE_POLL_SECS}s, at most ${P2P_COMMITTEE_WAIT_SECS}s) curl tn_admissionSnapshot on 127.0.0.1:${NODE_RPC_PORT}"
    while :; do
        el=$((SECONDS - start))
        raw="$(pc_ssh_ro "${i}" "$(pc_snap_cmd)" "${log}")" || true
        raw="$(printf '%s\n' "${raw}" | sed -n 's/^__tn_pc_snap //p' | tail -n 1)"
        echo "snapshot (${el}s): ${raw:-no answer}" >>"${log}"
        ev="$(printf '%s\n' "${raw:-none}" | python3 -I -c "${PC_SNAP_PY}")" || ev="auth=no why=parser-failed"
        if [ "$(pc_field "${ev}" auth)" = yes ]; then
            echo "    snapshot authoritative (${el}s): epoch=$(pc_field "${ev}" epoch) effective=$(pc_field "${ev}" effective) fallback=$(pc_field "${ev}" fallback)"
            return 0
        fi
        if [ "${el}" -ge "${P2P_COMMITTEE_WAIT_SECS}" ]; then
            echo "    ❌ the admission snapshot of ${INSTANCE_NAMES[$i]} is not authoritative after ${el}s: last seen effective=$(pc_field "${ev}" effective) fallback=$(pc_field "${ev}" fallback) ($(pc_field "${ev}" why)). Nothing was changed on ${INSTANCE_NAMES[$i]}." >&2
            return 1
        fi
        if [ "${ev}" != "${last}" ]; then
            echo "    … not authoritative yet (${el}s): effective=$(pc_field "${ev}" effective) fallback=$(pc_field "${ev}" fallback) ($(pc_field "${ev}" why))"
            last="${ev}"
        fi
        sleep "${P2P_COMMITTEE_POLL_SECS}"
    done
}

# pc_run_fw <idx> <on|off> <log> — one firewall-setup.sh call; sets PC_FW_RC (the script's
# rc, or "none" when no sentinel came back) and PC_FW_TEXT (its output).
pc_run_fw() {
    local out
    echo "    + $(pc_fw_cmd "$2")"
    out="$(tn_iap_ssh "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}" "$(pc_fw_cmd "$2")" </dev/null 2>>"$3")" || true
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    { echo "--- firewall-setup.sh --p2p-committee $2"; printf '%s\n' "${out}"; } >>"$3"
    PC_FW_RC="$(printf '%s\n' "${out}" | sed -n 's/^__tn_pc_rc=//p' | tail -n 1)"
    [ -n "${PC_FW_RC}" ] || PC_FW_RC=none
    PC_FW_TEXT="$(printf '%s\n' "${out}" | grep -v '^__tn_pc_rc=' | sed '/^$/d')" || PC_FW_TEXT=""
}
pc_show_fw() { [ -z "${PC_FW_TEXT}" ] || printf '%s\n' "${PC_FW_TEXT}" | sed 's/^/      | /'; }

# pc_on <idx> <log> — step 3 with its retries. rc 0 on, rc 1 failed.
pc_on() {
    local i="$1" log="$2" inst="${INSTANCE_NAMES[$1]}" tries=0
    while :; do
        pc_run_fw "${i}" on "${log}"
        case "${PC_FW_RC}" in
            0) pc_show_fw; echo "    on: rc 0"; return 0 ;;
            1)
                pc_show_fw
                if printf '%s\n' "${PC_FW_TEXT}" | grep -E -q -i -- "${PC_RETRY_RE}"; then
                    if [ "${tries}" -lt "${P2P_COMMITTEE_RETRIES}" ]; then
                        tries=$((tries + 1))
                        echo "    … refused, snapshot not authoritative yet (nothing was changed): retry ${tries}/${P2P_COMMITTEE_RETRIES} in ${P2P_COMMITTEE_RETRY_SECS}s"
                        sleep "${P2P_COMMITTEE_RETRY_SECS}"
                        continue
                    fi
                    echo "    ❌ ${inst}: still not authoritative after ${tries} retries (rc 1). Nothing was changed on ${inst}." >&2
                else
                    echo "    ❌ firewall-setup.sh refused --p2p-committee on on ${inst} (rc 1). Nothing was changed on ${inst}." >&2
                fi
                return 1 ;;
            2) pc_show_fw; echo "    ❌ ${inst}: a step after the sync failed and was undone (rc 2). Nothing was changed on ${inst}." >&2; return 1 ;;
            3) pc_kill_switch "${i}"; pc_show_fw; echo "    ❌ ${inst}: partial (rc 3): the undo was incomplete." >&2; return 1 ;;
            *) pc_kill_switch "${i}"; pc_show_fw; echo "    ❌ ${inst}: no exit status from firewall-setup.sh (rc ${PC_FW_RC}; see ${log}): the outcome is unknown." >&2; return 1 ;;
        esac
    done
}

# pc_check_parse <answer> — sets PCK_* from a pc_check_cmd answer.
pc_check_parse() {
    local t="$1" ch st fw
    PCK_DONE=0
    case "${t}" in *__tn_pc_end*) PCK_DONE=1 ;; esac
    ch="$(printf '%s\n' "${t}" | sed -n '/^__tn_pc_check_begin$/,/^__tn_pc_check_rc=/p' | sed '1d;$d')"
    PCK_RC="$(pc_kv "${t}" __tn_pc_check_rc)"
    PCK_RESULT="$(printf '%s\n' "${ch}" | grep '^result=' | tail -n 1)" || PCK_RESULT=""
    PCK_VERDICT="$(pc_field "${PCK_RESULT}" result)"
    PCK_MISSING="$(printf '%s\n' "${ch}" | grep -E '^(missing|mismatch) ')" || PCK_MISSING=""
    st="$(printf '%s\n' "${t}" | sed -n '/^__tn_pc_sect_status$/,/^__tn_pc_sect_fw$/p')"
    PCK_EPOCH="$(pc_kv "${st}" EPOCH)"; PCK_V4="$(pc_kv "${st}" ALLOWED_V4)"
    PCK_V6="$(pc_kv "${st}" ALLOWED_V6)"; PCK_KEYS="$(pc_kv "${st}" KEYS)"
    PCK_ACCEPT="$(pc_kv "${st}" COUNTER_ACCEPT_PACKETS)"; PCK_DROP="$(pc_kv "${st}" COUNTER_DROP_PACKETS)"
    fw="$(printf '%s\n' "${t}" | sed -n '/^__tn_pc_sect_fw$/,/^__tn_pc_end$/p')"
    PCK_FW_ALLOW="$(printf '%s\n' "${fw}" | grep 'P2P committee allowlist: ' | head -n 1 | sed 's/^[[:space:]]*//')" || PCK_FW_ALLOW=""
    PCK_FW_COUNT="$(printf '%s\n' "${fw}" | grep 'P2P committee allowlist counters: ' | head -n 1 | sed 's/^[[:space:]]*//')" || PCK_FW_COUNT=""
}

# pc_check <idx> <log> — step 4. rc 0 check ok; rc 1 not ok (kill switch printed first).
pc_check() {
    local i="$1" log="$2" inst="${INSTANCE_NAMES[$1]}" out
    echo "    + sudo ${PC_TOOL} check; sudo ${PC_TOOL} status; sudo cat ${PC_ALLOW_DIR}/status; sudo bash ${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh --p2p-committee status"
    out="$(pc_ssh_ro "${i}" "$(pc_check_cmd)" "${log}")" || true
    { echo "--- check / status"; printf '%s\n' "${out}"; } >>"${log}"
    pc_check_parse "${out}"
    if [ "${PCK_DONE}" -ne 1 ] || [ -z "${PCK_RC}" ]; then
        pc_kill_switch "${i}"
        echo "    ❌ no complete answer to the check from ${inst} (see ${log}): the allowlist is on but unverified." >&2
        return 1
    fi
    if [ "${PCK_RC}" != 0 ] || [ "${PCK_VERDICT}" != ok ]; then
        pc_kill_switch "${i}"
        echo "    ❌ tn-p2p-allow-sync check on ${inst}: exit ${PCK_RC}, ${PCK_RESULT:-no result line}" >&2
        [ -z "${PCK_MISSING}" ] || printf '%s\n' "${PCK_MISSING}" | sed 's/^/         /' >&2
        return 1
    fi
    echo "    check: ${PCK_RESULT} (exit 0)"
    [ -z "${PCK_FW_ALLOW}" ] || echo "    ${PCK_FW_ALLOW}"
    [ -z "${PCK_FW_COUNT}" ] || echo "    ${PCK_FW_COUNT}"
    return 0
}

# pc_whole <me|-> <want-mode|unknown> <pre-head|-> <need-advance 0|1> <settle-secs> — step 5
# (and step 0 with "- unknown - 0 0"). Probes every validator (and <me>) in parallel each
# round until every condition holds (with need-advance 0: at the end of the settle time).
# rc 0 whole (PC_ME_MODE / PC_ME_HEAD set), rc 1 not whole within <settle-secs>.
pc_whole() {
    local me="$1" want="$2" pre="$3" adv="$4" settle="$5" log="${RUN_LOG_DIR}/committee.log"
    local start="${SECONDS}" el i p u m h lo hi bad detail
    local set_=("${PC_VALIDATORS[@]}")
    if [ "${me}" != - ]; then
        case " ${set_[*]} " in *" ${me} "*) ;; *) set_+=("${me}") ;; esac
    fi
    while :; do
        el=$((SECONDS - start)); bad=""; detail=""; lo=""; hi=""; PC_ME_MODE=""; PC_ME_HEAD=""
        for i in "${set_[@]}"; do
            ( pc_probe "${i}" "${log}" >"${PC_TMP}/probe.${i}" || : >"${PC_TMP}/probe.${i}" ) &
        done
        wait
        for i in "${set_[@]}"; do
            p="$(cat "${PC_TMP}/probe.${i}")"
            u="$(pc_field "${p}" unit)"; m="$(pc_field "${p}" mode)"; h="$(pc_field "${p}" head)"
            detail="${detail} ${NODE_NAMES[$i]}=${m:-?}@${h:-?}"
            [ "${u}" = active ] || bad="${bad} ${INSTANCE_NAMES[$i]}:unit=${u:-no-answer}"
            if [ "${NODE_ROLES[$i]}" = validator ] && [ "${m}" != CvvActive ]; then
                bad="${bad} ${INSTANCE_NAMES[$i]}:mode=${m:-?}"
            fi
            if [ "${i}" = "${me}" ]; then
                PC_ME_MODE="${m}"; PC_ME_HEAD="${h}"
                if [ "${want}" != unknown ] && [ "${m}" != "${want}" ] && [ "${NODE_ROLES[$i]}" != validator ]; then
                    bad="${bad} ${INSTANCE_NAMES[$i]}:mode=${m:-?}(was ${want})"
                fi
            fi
            if pc_isnum "${h}"; then
                if [ -z "${lo}" ] || [ "${h}" -lt "${lo}" ]; then lo="${h}"; fi
                if [ -z "${hi}" ] || [ "${h}" -gt "${hi}" ]; then hi="${h}"; fi
            else
                bad="${bad} ${INSTANCE_NAMES[$i]}:head=?"
            fi
        done
        if [ -n "${lo}" ] && [ $((hi - lo)) -gt "${P2P_COMMITTEE_HEAD_LAG}" ]; then
            bad="${bad} heads ${lo}..${hi} differ by more than ${P2P_COMMITTEE_HEAD_LAG}"
        fi
        if [ "${me}" != - ] && [ "${adv}" -eq 1 ]; then
            if ! pc_isnum "${PC_ME_HEAD}" || ! pc_isnum "${pre}" || [ "${PC_ME_HEAD}" -le "${pre}" ]; then
                bad="${bad} ${INSTANCE_NAMES[$me]}:head ${pre}->${PC_ME_HEAD:-?} not advanced"
            fi
        fi
        echo "round (${el}s):${detail} |${bad:- ok}" >>"${log}"
        if [ -z "${bad}" ] && { [ "${adv}" -eq 1 ] || [ "${el}" -ge "${settle}" ]; }; then
            echo "    committee whole (${el}s):${detail}"
            return 0
        fi
        if [ "${el}" -ge "${settle}" ]; then
            echo "    ❌ the committee is not whole after ${el}s:${bad}   [${detail# } ]" >&2
            return 1
        fi
        echo "    … ${el}s/${settle}s:${bad:- settling}"
        sleep "${P2P_COMMITTEE_POLL_SECS}"
    done
}

# pc_step5 <idx> <want> <pre-head> <adv> — the step-5 header line + pc_whole.
pc_step5() {
    echo "    committee-whole check (≤ ${P2P_COMMITTEE_SETTLE_SECS}s): ${INSTANCE_NAMES[$1]} mode ${2}$([ "$4" -eq 1 ] && printf ', head > %s' "$3"); every validator active + CvvActive; heads within ${P2P_COMMITTEE_HEAD_LAG}"
    pc_whole "$1" "$2" "$3" "$4" "${P2P_COMMITTEE_SETTLE_SECS}"
}

# pc_host_on <idx> — steps 1-6 on one host. rc 0 ok, 1 failed, 3 snapshot timeout.
pc_host_on() {
    local i="$1" inst="${INSTANCE_NAMES[$1]}" role="${NODE_ROLES[$1]}" log p u f n c m h line
    log="${RUN_LOG_DIR}/${inst}.log"
    echo ""
    echo ">>> ${inst} (${ZONES[$i]}, ${role}): --p2p-committee on"
    p="$(pc_probe "${i}" "${log}")" || p=""
    if [ -z "${p}" ]; then
        echo "    ❌ ${inst} did not answer the read-only probe (see ${log}). Nothing was changed on ${inst}." >&2
        return 1
    fi
    u="$(pc_field "${p}" unit)"; f="$(pc_field "${p}" ufw)"; n="$(pc_field "${p}" nft)"
    c="$(pc_field "${p}" committee)"; m="$(pc_field "${p}" mode)"; h="$(pc_field "${p}" head)"
    echo "    before: unit=${u} ufw=${f} nft=${n} P2P_COMMITTEE=${c} mode=${m} head=${h}"
    local why=""
    [ "${u}" = active ] || why="the node unit is not active (${u})"
    [ -n "${why}" ] || [ "${f}" = active ] || why="ufw is not active (${f}): turn the host firewall on first (./devnet-firewall.sh --enable)"
    [ -n "${why}" ] || [ "${n}" = yes ] || why="/usr/sbin/nft is missing (the startup script installs nftables on first boot)"
    [ -n "${why}" ] || [ "${m}" != unknown ] || why="tn_nodeMode is unreadable on 127.0.0.1:${NODE_RPC_PORT}"
    [ -n "${why}" ] || pc_isnum "${h}" || why="the head block number is unreadable"
    if [ -z "${why}" ] && [ "${role}" = validator ] && [ "${m}" != CvvActive ]; then
        why="a validator in mode ${m}, not CvvActive: the committee is not whole"
    fi
    if [ -n "${why}" ]; then
        echo "    ❌ ${inst}: ${why}. Nothing was changed on ${inst}." >&2
        return 1
    fi
    if [ "${c}" = on ]; then
        echo "    already-on: .node-meta has P2P_COMMITTEE=on; 'on' resyncs it (no snapshot wait; steps 3-5 still run)"
    else
        pc_wait_snapshot "${i}" "${log}" || return 3
    fi
    pc_on "${i}" "${log}" || return 1
    pc_check "${i}" "${log}" || return 1
    if ! pc_step5 "${i}" "${m}" "${h}" "${P2P_COMMITTEE_REQUIRE_ADVANCE}"; then
        echo "    ❌ stopping the sweep after ${inst}: ${inst}'s own check was ok, but if its allowlist is the cause:" >&2
        pc_kill_switch "${i}"
        return 1
    fi
    line="P2P_COMMITTEE ${inst} on epoch=${PCK_EPOCH:-?} v4=${PCK_V4:-?} v6=${PCK_V6:-?} keys=${PCK_KEYS:-?} check=${PCK_VERDICT} mode=${PC_ME_MODE} head=${PC_ME_HEAD}"
    echo "${line}"
    PC_SUMMARY+=("${line}")
    return 0
}

# pc_host_off <idx> — the way back on one host. rc 0 ok, 1 failed.
pc_host_off() {
    local i="$1" inst="${INSTANCE_NAMES[$1]}" role="${NODE_ROLES[$1]}" log p m h c want adv line
    log="${RUN_LOG_DIR}/${inst}.log"
    echo ""
    echo ">>> ${inst} (${ZONES[$i]}, ${role}): --p2p-committee off"
    p="$(pc_probe "${i}" "${log}")" || p=""
    m="$(pc_field "${p}" mode)"; h="$(pc_field "${p}" head)"; c="$(pc_field "${p}" committee)"
    echo "    before: unit=$(pc_field "${p}" unit) P2P_COMMITTEE=${c:-?} mode=${m:-?} head=${h:-?}"
    want="${m:-unknown}"
    adv="${P2P_COMMITTEE_REQUIRE_ADVANCE}"
    if [ "${adv}" -eq 1 ] && ! pc_isnum "${h}"; then
        echo "    ⚠️  no head before the change on ${inst}: its head is not required to advance"
        adv=0
    fi
    pc_run_fw "${i}" off "${log}"
    pc_show_fw
    case "${PC_FW_RC}" in
        0) echo "    off: rc 0" ;;
        1) echo "    ❌ firewall-setup.sh refused --p2p-committee off on ${inst} (rc 1)." >&2; return 1 ;;
        3) pc_kill_switch "${i}"; echo "    ❌ ${inst}: off was partial (rc 3); see journalctl -t tn-p2p-allow on the host." >&2; return 1 ;;
        *) pc_kill_switch "${i}"; echo "    ❌ ${inst}: no exit status from firewall-setup.sh (rc ${PC_FW_RC}; see ${log}): the outcome is unknown." >&2; return 1 ;;
    esac
    pc_step5 "${i}" "${want}" "${h:--}" "${adv}" || return 1
    line="P2P_COMMITTEE ${inst} off mode=${PC_ME_MODE} head=${PC_ME_HEAD}"
    echo "${line}"
    PC_SUMMARY+=("${line}")
    return 0
}

# pc_status_host <idx> — read-only. rc 1 when the host should be on and check is not ok, or
# when it did not answer.
pc_status_host() {
    local i="$1" inst="${INSTANCE_NAMES[$1]}" log out p c verdict
    log="${RUN_LOG_DIR}/${inst}.log"
    echo ""
    echo ">>> ${inst} (${ZONES[$i]}, ${NODE_ROLES[$i]}): status"
    out="$(pc_ssh_ro "${i}" "$(pc_probe_cmd)
$(pc_check_cmd)" "${log}")" || true
    { echo "--- probe / check / status"; printf '%s\n' "${out}"; } >>"${log}"
    p="$(printf '%s\n' "${out}" | grep '^__tn_pc_probe ' | tail -n 1)" || p=""
    pc_check_parse "${out}"
    if [ -z "${p}" ] || [ "${PCK_DONE}" -ne 1 ]; then
        echo "    ❌ ${inst} did not answer (see ${log})." >&2
        echo "P2P_COMMITTEE_STATUS ${inst} state=unknown check=unknown"
        return 1
    fi
    p="${p#__tn_pc_probe }"
    c="$(pc_field "${p}" committee)"
    verdict="${PCK_VERDICT:-none}"
    [ "${c}" = on ] || [ -n "${PCK_VERDICT}" ] || verdict="n/a"
    echo "    state: P2P_COMMITTEE=${c} unit=$(pc_field "${p}" unit) mode=$(pc_field "${p}" mode) head=$(pc_field "${p}" head)"
    echo "    check: ${PCK_RESULT:-no result line} (exit ${PCK_RC:-?})"
    [ -z "${PCK_MISSING}" ] || printf '%s\n' "${PCK_MISSING}" | sed 's/^/      /'
    [ -z "${PCK_FW_ALLOW}" ] || echo "    ${PCK_FW_ALLOW}"
    [ -z "${PCK_FW_COUNT}" ] || echo "    ${PCK_FW_COUNT}"
    echo "P2P_COMMITTEE_STATUS ${inst} state=${c} check=${verdict} accept=${PCK_ACCEPT:-?} drop=${PCK_DROP:-?}"
    if [ "${c}" = on ] && { [ "${PCK_RC}" != 0 ] || [ "${verdict}" != ok ]; }; then
        echo "    ❌ ${inst} should be on but check is not ok." >&2
        return 1
    fi
    return 0
}

# pc_dry_run — no ssh: the remote commands and the assertions, per host.
pc_dry_run() {
    local i inst
    echo ""
    echo "DRY RUN (no --yes): nothing is touched. The read-only probe run on a host (steps 0, 1, 5):"
    pc_probe_cmd | sed 's/^/    | /'
    echo ""
    if [ "${VERB}" = on ]; then
        echo "step 0 (once): the probe on every validator (${PC_VALIDATORS[*]}): unit active, CvvActive, heads within ${P2P_COMMITTEE_HEAD_LAG}"
    fi
    for i in "${TARGETS[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo ""
        echo ">>> ${inst} (${ZONES[$i]}, ${NODE_ROLES[$i]}): --p2p-committee ${VERB}"
        if [ "${VERB}" = on ]; then
            echo "    1. probe: assert unit active, ufw active, /usr/sbin/nft present, mode and head readable$([ "${NODE_ROLES[$i]}" = validator ] && printf ', mode CvvActive'); P2P_COMMITTEE=on -> already-on (step 2 skipped)"
            echo "    2. every ${P2P_COMMITTEE_POLL_SECS}s, at most ${P2P_COMMITTEE_WAIT_SECS}s (else exit 3, nothing changed):"
            pc_snap_cmd | sed 's/^/       | /'
            echo "       assert: primary swarm available=true, tracked_epoch set, admission.fallback null|Unresolved"
            echo "    3. + $(pc_fw_cmd on)"
            echo "       rc 1 matching /${PC_RETRY_RE}/: retry every ${P2P_COMMITTEE_RETRY_SECS}s, at most ${P2P_COMMITTEE_RETRIES} times; rc 1 other, 2: fail (nothing changed); 3: fail, kill switch first"
            echo "    4. + $(pc_check_cmd)"
            echo "       assert: check exits 0 with result=ok (else kill switch, missing addresses)"
        else
            echo "    1. probe: record mode and head"
            echo "    3. + $(pc_fw_cmd off)"
            echo "       assert: rc 0 (1 refused, 3 partial: fail)"
        fi
        echo "    5. within ${P2P_COMMITTEE_SETTLE_SECS}s: ${inst}'s mode as in step 1$([ "${P2P_COMMITTEE_REQUIRE_ADVANCE}" -eq 1 ] && printf ', its head above step 1'); every validator active + CvvActive; heads within ${P2P_COMMITTEE_HEAD_LAG}"
        if [ "${VERB}" = on ]; then
            echo "    6. P2P_COMMITTEE ${inst} on epoch=<n> v4=<n> v6=<n> keys=<n> check=ok mode=<mode> head=<n>"
        else
            echo "    6. P2P_COMMITTEE ${inst} off mode=<mode> head=<n>"
        fi
    done
}

# --- main --------------------------------------------------------------------------------

PC_MODE_TEXT="dry run (--p2p-committee ${VERB})"
[ "${YES}" -eq 1 ] && PC_MODE_TEXT="--p2p-committee ${VERB}"
[ "${STATUS}" -eq 1 ] && PC_MODE_TEXT="status (read-only)"
_names=""
for _i in "${TARGETS[@]}"; do _names="${_names} ${INSTANCE_NAMES[$_i]}"; done
echo "=========================================="
echo "devnet committee P2P allowlist (tn-node-deployment firewall-setup.sh --p2p-committee)"
echo "Project:  ${PROJECT_ID}"
echo "Mode:     ${PC_MODE_TEXT}"
echo "Targets: ${_names}"
echo "Knobs:    wait=${P2P_COMMITTEE_WAIT_SECS}s poll=${P2P_COMMITTEE_POLL_SECS}s retries=${P2P_COMMITTEE_RETRIES}x${P2P_COMMITTEE_RETRY_SECS}s settle=${P2P_COMMITTEE_SETTLE_SECS}s head-lag=${P2P_COMMITTEE_HEAD_LAG} require-advance=${P2P_COMMITTEE_REQUIRE_ADVANCE}"

if [ "${STATUS}" -eq 0 ] && [ "${YES}" -eq 0 ]; then
    echo "=========================================="
    pc_dry_run
    exit 0
fi

if [ "${STATUS}" -eq 0 ] && [ "${VERB}" = on ] && ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 is needed to judge the admission snapshot" >&2; exit 2
fi
RUN_LOG_DIR="${PC_DIR}/logs/$(date +%Y%m%d_%H%M%S)-p2p-committee"
PC_TMP="${RUN_LOG_DIR}/.probe"
mkdir -p "${PC_TMP}"
echo "Logs:     ${RUN_LOG_DIR}"
echo "=========================================="

if [ "${STATUS}" -eq 1 ]; then
    rc=0
    for _i in "${TARGETS[@]}"; do
        pc_status_host "${_i}" || rc=1
    done
    exit "${rc}"
fi

PC_SUMMARY=()
ok_hosts=(); failed_hosts=(); untouched=()
rc=0
if [ "${VERB}" = on ]; then
    echo ""
    echo ">>> step 0: the committee is whole before any change"
    if ! pc_whole - unknown - 0 0; then
        echo "❌ the committee is not whole before the sweep: nothing was changed anywhere." >&2
        echo "untouched: ${_names# }"
        exit 1
    fi
fi
for _i in "${TARGETS[@]}"; do
    if [ "${rc}" -ne 0 ]; then
        untouched+=("${INSTANCE_NAMES[$_i]}")
        continue
    fi
    _hrc=0
    if [ "${VERB}" = on ]; then
        pc_host_on "${_i}" || _hrc=$?
    else
        pc_host_off "${_i}" || _hrc=$?
    fi
    if [ "${_hrc}" -eq 0 ]; then
        ok_hosts+=("${INSTANCE_NAMES[$_i]}")
    else
        failed_hosts+=("${INSTANCE_NAMES[$_i]}")
        rc="${_hrc}"
        [ "${rc}" -eq 3 ] || rc=1
    fi
done

echo ""
echo "=========================================="
[ "${#PC_SUMMARY[@]}" -eq 0 ] || printf '%s\n' "${PC_SUMMARY[@]}"
[ "${#ok_hosts[@]}" -eq 0 ] || echo "ok:        ${ok_hosts[*]}"
[ "${#failed_hosts[@]}" -eq 0 ] || echo "FAILED:    ${failed_hosts[*]}"
[ "${#untouched[@]}" -eq 0 ] || echo "untouched: ${untouched[*]} (sweep stopped; re-run with these names once the failure is fixed)"
echo "logs: ${RUN_LOG_DIR}"
if [ "${rc}" -eq 0 ]; then
    echo "--p2p-committee ${VERB} done on every target; the committee is whole."
else
    echo "--p2p-committee ${VERB} stopped WITH ERRORS (exit ${rc}): see the ❌ lines above." >&2
fi
echo "=========================================="
exit "${rc}"
