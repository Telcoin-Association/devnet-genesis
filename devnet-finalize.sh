#!/usr/bin/env bash
#
# devnet-finalize.sh — OPERATOR driver: stage the assembled genesis on every node (or a
# targeted subset), run the tn-node-deployment v2 FINALIZE phase (setup-node.sh
# --phase=finalize writes /etc/telcoin/node.env, the start script and the systemd unit,
# then starts and enables the node), and prove each node came up the way v2 says it does.
#
# Phase A, per node (a failure skips the rest of that node, never the other nodes):
#   0. local checks: DOCKER_IMAGE is <repository>@sha256:<64 hex> (v2 on devnet runs an
#      image by digest only) and the node's EXECUTION_ADDRESSES entry is 0x + 40 hex.
#   1. readiness gate (one ssh): setup-node.sh is in TN_NODE_SCRIPTS_DIR, keygen ran
#      (.node-meta records PASSPHRASE_METHOD), no telcoin unit is installed yet (v2
#      refuses to finalize over one), and <DATA_DIR>/network-config from deploy step 7
#      configures Closed admission (the file's bytes come back and are checked here; see
#      _nc_verdict). The node reads that file once, at its first start; when it is missing
#      the node writes the default (admission Open). The same ssh records where the logs
#      end (size + checksum of each log file A4 reads, and the journal cursor), so A4 reads
#      only what this finalize produced.
#   2. stage committee.yaml + genesis.yaml + parameters.yaml (PARAMETERS_FILE): scp to
#      /tmp, then `sudo install -o root -g root -m 0644` into the genesis dir (root 0755).
#      Nothing is chowned to the service user: setup-node.sh copies the three files into
#      the data dir AS the service user, which only needs to read them.
#   3. setup-node.sh --json --phase=finalize ... It counts only with ssh rc 0 AND a done
#      event carrying "ok":true (stdout is JSON events only; the human log is stderr).
#   4. wait_healthy (devnet-lib.sh): unit active AND the healthcheck port answers.
# Phase B, per node that passed phase A. Each assertion prints one ✓/✗ line with what it
# observed; any ✗ fails the node and the run.
#   A1 telcoin stays active for FINALIZE_STABLE_SECS (60), polled every
#      FINALIZE_STABLE_POLL_SECS (10), with NRestarts = 0, and is-enabled = enabled.
#      Active but not enabled is a latent outage: the node never comes back from a reboot
#      (devnet genesis reset 2026-09-17).
#   A2 .node-meta NETWORK=devnet, and DOCKER_IMAGE_DIGEST equal to the digest part of
#      DOCKER_IMAGE (v2 records ${DOCKER_IMAGE##*@}: sha256:<hex>, prefix included).
#   A3 <DATA_DIR>/network-config still configures Closed admission (the gate's check, on
#      the file as it is now). Finalize adds (or rewrites) only its `hostname: "<name>"`
#      line, from --advertised-name; that line is shown, not required.
#   A4 the logs this finalize produced hold none of `bad yaml data`, `committee_peers:`,
#      `trusted_nodes[`, `bootstrap_peers[` (config errors: the node exits at start and
#      systemd restarts it) and no `panicked`, and are not empty. Files: the unit's
#      StandardOutput/StandardError append: files (/var/log/telcoin/telcoin.log +
#      telcoin-error.log) and NODE_LOG_DIR/telcoin.log when .node-meta records one, each
#      read past the size the gate recorded; the whole file when it was absent or empty
#      then, when its first <size> bytes no longer match the gate's checksum (v2 finalize
#      truncates both append: files before the start, setup-node.sh:1231-1232), or when
#      the gate has no record of it. Journal: the unit's entries after the gate's cursor
#      (this boot when the gate got none); a journalctl error fails A4.
#   A5 ExecStart is /usr/local/libexec/telcoin/tn-start-docker; the container `telcoin` is
#      running DOCKER_IMAGE with a read-only rootfs; the docker client the unit runs
#      (MainPID) was started with --pull=never and --read-only (docker inspect does not
#      record the pull policy, so the launch line is the evidence); and no
#      TN_BLS_PASSPHRASE in /proc/<pid>/environ of the container's process (docker
#      inspect .State.Pid) or of any `telcoin node` process on the host.
#
# SECURITY: finalize takes NO secret. v2 keygen stored the BLS passphrase on the node (a
# systemd credential, or a root-only file below systemd 250) and the unit loads it from
# there, so this script never resolves, sends or logs a passphrase.
#
# Usage:
#   ./devnet-finalize.sh                    # all nodes
#   ./devnet-finalize.sh node1 node3        # subset by NODE_NAME
#   ./devnet-finalize.sh observer-5-devnet  # subset by INSTANCE_NAME
#   ./devnet-finalize.sh 0 4                # subset by index (0-based)
# An unknown target stops the run before any node is touched.
# Exit: 0 every targeted node finalized and passed A1-A5; 1 a node failed; 2 bad target.

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

FINALIZE_STABLE_SECS="${FINALIZE_STABLE_SECS:-60}"
FINALIZE_STABLE_POLL_SECS="${FINALIZE_STABLE_POLL_SECS:-10}"
TN_START_DOCKER="/usr/local/libexec/telcoin/tn-start-docker"   # v2 tn_start_script_path docker
case "${FINALIZE_STABLE_SECS}${FINALIZE_STABLE_POLL_SECS}" in
    *[!0123456789]*) echo "❌ FINALIZE_STABLE_SECS / FINALIZE_STABLE_POLL_SECS must be whole seconds" >&2; exit 2 ;;
esac
if [ "${FINALIZE_STABLE_POLL_SECS}" -lt 1 ]; then FINALIZE_STABLE_POLL_SECS=1; fi

# Same selector as devnet-network-config.sh: no args → all nodes; args may be an index
# (0-based), an INSTANCE_NAME, or a NODE_NAME. A node named twice is visited once. An
# unknown target is an error (rc 1), never a silent empty run.
tn_select_indices() {
    local out=() arg i matched
    if [ "$#" -eq 0 ]; then
        for i in "${!INSTANCE_NAMES[@]}"; do out+=("$i"); done
        printf '%s\n' "${out[@]}"; return 0
    fi
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                case " ${out[*]+"${out[*]}"} " in *" ${i} "*) ;; *) out+=("$i") ;; esac
                matched=1; break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME, or NODE_NAME)" >&2
            return 1
        fi
    done
    printf '%s\n' "${out[@]}"
}

# Resolve the targets first: an unknown one stops the run (exit 2) before anything else.
if ! SELECTION="$(tn_select_indices "$@")"; then exit 2; fi
# macOS /bin/bash is 3.2 and lacks `mapfile`; this read-loop is the portable equivalent.
INDICES=()
while IFS= read -r _idx; do
    if [ -n "${_idx}" ]; then INDICES+=("${_idx}"); fi
done <<< "${SELECTION}"
if [ "${#INDICES[@]}" -eq 0 ]; then
    echo "❌ no target nodes (INSTANCE_NAMES is empty?)" >&2
    exit 2
fi

# Local genesis artifacts produced by devnet-genesis-build.sh (in GENESIS_WORKSPACE,
# which config.sh sets to REPO_ROOT for devnet).
GENESIS_LOCAL_DIR="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis"
COMMITTEE_LOCAL="${GENESIS_LOCAL_DIR}/committee.yaml"
GENESIS_LOCAL="${GENESIS_LOCAL_DIR}/genesis.yaml"

echo ">>> verifying local genesis artifacts"
for f in "${COMMITTEE_LOCAL}" "${GENESIS_LOCAL}" "${PARAMETERS_FILE}"; do
    if [ ! -f "${f}" ]; then
        echo "❌ missing ${f}. Run ./devnet-genesis-build.sh first." >&2
        exit 1
    fi
done

# v2 on devnet takes the image by digest only (setup-node.sh refuses a tag on the node);
# say so here, before any node is touched. The digest part is what A2 compares.
IMAGE_DIGEST="${DOCKER_IMAGE##*@}"
_hex="${IMAGE_DIGEST#sha256:}"
case "${DOCKER_IMAGE}" in *@sha256:*) ;; *) _hex="" ;; esac
case "${_hex}" in *[!0123456789abcdef]*) _hex="" ;; esac
if [ "${#_hex}" -ne 64 ]; then
    echo "❌ DOCKER_IMAGE='${DOCKER_IMAGE}' is not <repository>@sha256:<64 lower-case hex> (config.sh: fill in the pushed digest)" >&2
    exit 1
fi
unset _hex

# The gate and A3 run devnet-network-config.py's validator on each node's network-config,
# with the context devnet-network-config.sh --verify gives it (the fleet in config.sh
# order, hub = the first validator), so python3 + PyYAML are needed here too.
NC_PY="${DEVNET_LIB_DIR}/devnet-network-config.py"
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import yaml' >/dev/null 2>&1; then
    echo "❌ python3 with PyYAML is needed to validate each node's network-config (sudo apt-get install python3-yaml)" >&2
    exit 1
fi
NODES_SPEC=""
HUB=""
for _n in "${!NODE_NAMES[@]}"; do
    NODES_SPEC="${NODES_SPEC:+${NODES_SPEC},}${NODE_NAMES[$_n]}=${NODE_ROLES[$_n]}"
    if [ -z "${HUB}" ] && [ "${NODE_ROLES[$_n]}" = "validator" ]; then HUB="${NODE_NAMES[$_n]}"; fi
done
unset _n
NC_CTX=(--committee "${COMMITTEE_LOCAL}" --genesis-dir "${GENESIS_LOCAL_DIR}" --nodes "${NODES_SPEC}" --hub "${HUB}")

# v2's LOG_DIR default (lib/common.sh:55): the unit appends to <dir>/<service>.log and
# <dir>/<service>-error.log (setup-node.sh:1083-1084). The gate records where those end.
TN_LOG_DIR="/var/log/telcoin"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/tn-finalize.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

# --- remote probes ------------------------------------------------------------------
# Each probe is a small root script run as `sudo bash -c '<script>' _ <args...>` over
# tn_iap_ssh. The script text comes from a quoted heredoc (nothing expands locally) and
# holds no single quote; its inputs travel as positional arguments. Its first line names
# it (`# tn-probe: <name>`), it prints KEY=value lines, and its last line is the
# __tn_probe_done sentinel, so a probe that did not run to the end is never read as a
# pass. Exit status is always the final echo's: the answer is in the lines, not the rc.

_rs_done() { echo "echo __tn_probe_done"; }

# The network-config at $nc, byte for byte as base64 on one line (shared by the gate and
# A3; _nc_verdict judges it locally). base64 keeps a BOM or a CR that _tn_probe's CR strip
# would otherwise hide.
_rs_nc_lines() {
    cat <<'EOF'
if [ -f "$nc" ]; then echo nc_present=1; echo "nc_b64=$(base64 < "$nc" | tr -d "\n")"; else echo nc_present=0; fi
EOF
}

# ready: $1 setup script, $2 service, $3 data dir to use when .node-meta has none, $4 v2
# log dir. Also prints, for A4, a logmark=<size>:<cksum crc>:<path> line per log file
# (0:-:<path> when absent) and jcursor=, the journal's last cursor.
_rs_ready() {
    cat <<'EOF'
# tn-probe: ready
setup="$1"; svc="$2"; meta=/etc/telcoin/.node-meta
if [ -f "$setup" ]; then echo setup=1; else echo setup=0; fi
if [ -f "$meta" ] && grep -q "^PASSPHRASE_METHOD=." "$meta"; then echo keygen=1; else echo keygen=0; fi
unit="/etc/systemd/system/$svc.service"
if [ -e "$unit" ] || [ -L "$unit" ]; then echo installed=1; else echo installed=0; fi
data=$(sed -n "s/^DATA_DIR=//p" "$meta" 2>/dev/null | tr -d "\r" | tail -n 1)
nodelog=$(sed -n "s/^NODE_LOG_DIR=//p" "$meta" 2>/dev/null | tr -d "\r" | tail -n 1)
for f in "$4/$svc.log" "$4/$svc-error.log" ${nodelog:+"$nodelog/telcoin.log"}; do
    if [ -f "$f" ]; then ck=$(cksum < "$f"); echo "logmark=${ck#* }:${ck%% *}:$f"; else echo "logmark=0:-:$f"; fi
done
echo "jcursor=$(journalctl -n 1 --no-pager --show-cursor -o cat 2>/dev/null | sed -n "s/^-- cursor: //p" | tail -n 1)"
nc="${data:-$3}/network-config"
echo "nc=$nc"
EOF
    _rs_nc_lines
    _rs_done
}

# network-config: $1 the file.
_rs_nc() {
    cat <<'EOF'
# tn-probe: network-config
nc="$1"
EOF
    _rs_nc_lines
    _rs_done
}

# service: $1 service.
_rs_service() {
    cat <<'EOF'
# tn-probe: service
svc="$1"
echo "active=$(systemctl is-active "$svc" 2>/dev/null)"
echo "enabled=$(systemctl is-enabled "$svc" 2>/dev/null)"
echo "nrestarts=$(systemctl show -p NRestarts --value "$svc" 2>/dev/null)"
EOF
    _rs_done
}

# logs: $1 service, $2 NODE_LOG_DIR ("" when .node-meta has none), $3 the gate's logmark
# values (space-separated), $4 the gate's journal cursor. Reads only what came after the
# gate: a file past its recorded size while its first <size> bytes still match the
# recorded checksum, else the whole file (it was absent, empty, truncated or rewritten
# since, or the gate did not see it); the journal after the cursor. files= shows, per
# file, the bytes skipped and why.
_rs_logs() {
    cat <<'EOF'
# tn-probe: logs
svc="$1"; nodelog="$2"; marks="$3"; cur="$4"; seen=""; files=""
s=$(mktemp); j=$(mktemp)
for f in $(systemctl cat "$svc" 2>/dev/null | sed -n "s/^Standard[A-Za-z]*=append://p") ${nodelog:+$nodelog/telcoin.log}; do
    case " $seen " in *" $f "*) continue ;; esac
    seen="$seen $f"
    if [ ! -f "$f" ]; then continue; fi
    off=0; why=no-gate-record
    for m in $marks; do
        size=${m%%:*}; rest=${m#*:}; crc=${rest%%:*}
        if [ "${rest#*:}" != "$f" ]; then continue; fi
        if [ "$size" = 0 ]; then why=new-since-gate
        elif [ "$(head -c "$size" "$f" | cksum)" = "$crc $size" ]; then off=$size; why=after-gate
        else why=rewritten-since-gate; fi
    done
    tail -c +$((off + 1)) "$f" >> "$s"
    files="$files $f(skip=$off,$why)"
done
if [ -n "$cur" ]; then
    journalctl -u "$svc" --after-cursor="$cur" --no-pager -o cat > "$j" 2>/dev/null; jrc=$?; jfrom=after-gate-cursor
else
    journalctl -u "$svc" -b --no-pager -o cat > "$j" 2>/dev/null; jrc=$?; jfrom=this-boot
fi
echo "files=$files"
echo "journal=$(wc -l < "$j" | tr -d " ")"
echo "journal_from=$jfrom"
echo "journal_rc=$jrc"
echo "lines=$(cat "$s" "$j" | wc -l | tr -d " ")"
for p in "bad yaml data" "committee_peers:" "trusted_nodes[" "bootstrap_peers[" "panicked"; do
    n=$(cat "$s" "$j" | grep -cF -- "$p")
    first=$(cat "$s" "$j" | grep -F -m 1 -- "$p" | tr -d "\r" | cut -c 1-160)
    echo "hit=$n|$p|$first"
done
rm -f "$s" "$j"
EOF
    _rs_done
}

# runtime: $1 service (= the container name v2 gives docker run --name).
# pgrep's pattern is written "telcoin[ ]node" so it cannot match this probe's own
# command line, which carries the pattern text.
_rs_runtime() {
    cat <<'EOF'
# tn-probe: runtime
svc="$1"
echo "execstart=$(systemctl cat "$svc" 2>/dev/null | sed -n "s/^ExecStart=//p" | tail -n 1)"
pid=$(systemctl show -p MainPID --value "$svc" 2>/dev/null)
echo "mainpid=$pid"
launch=""
if [ -n "$pid" ] && [ "$pid" != 0 ] && [ -r "/proc/$pid/cmdline" ]; then launch=$(tr "\0" " " < "/proc/$pid/cmdline"); fi
echo "launch_cmd=$(printf "%s" "$launch" | cut -c 1-40)"
case " $launch " in *" --pull=never "*) echo launch_pull=1 ;; *) echo launch_pull=0 ;; esac
case " $launch " in *" --read-only "*) echo launch_ro=1 ;; *) echo launch_ro=0 ;; esac
echo "container=$(docker inspect -f "{{.State.Running}} {{.HostConfig.ReadonlyRootfs}} {{.State.Pid}} {{.Config.Image}}" "$svc" 2>/dev/null)"
cpid=$(docker inspect -f "{{.State.Pid}}" "$svc" 2>/dev/null)
checked=""; hits=0
for p in $cpid $(pgrep -f "telcoin[ ]node" 2>/dev/null); do
    case " $checked " in *" $p "*) continue ;; esac
    if [ "$p" != 0 ] && [ -r "/proc/$p/environ" ]; then
        n=$(tr "\0" "\n" < "/proc/$p/environ" | grep -c TN_BLS_PASSPHRASE)
        hits=$((hits + n)); checked="$checked $p"
    fi
done
echo "env_pids=$checked"
echo "env_hits=$hits"
EOF
    _rs_done
}

# _tn_probe <instance> <zone> <script> [args...] — run one probe; print its output (CR
# stripped). rc 1, with the reason on stdout, when ssh failed or the sentinel is missing.
_tn_probe() {
    local inst="$1" zone="$2" script="$3" cmd a out rc=0
    shift 3
    case "${script}" in *"'"*) echo "internal: probe script holds a single quote"; return 1 ;; esac
    cmd="sudo bash -c '${script}' _"
    for a in "$@"; do
        case "${a}" in *"'"*) echo "internal: probe argument holds a single quote: ${a}"; return 1 ;; esac
        cmd="${cmd} '${a}'"
    done
    out="$(tn_iap_ssh "${inst}" "${zone}" "${cmd}" </dev/null 2>/dev/null)" || rc=$?
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    case "${out}" in
        *__tn_probe_done*) printf '%s\n' "${out}" ;;
        *) echo "no answer from ${inst} (ssh rc ${rc})"; return 1 ;;
    esac
}

# _kv <probe-output> <key> — the value of the last "key=" line ("" when absent).
_kv() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | tail -n 1; }

# _num <value> — the value when it is a non-negative integer, else 0 (a missing or
# garbled count must read as "none found", never pass a numeric test by erroring).
_num() {
    case "${1:-}" in ""|*[!0123456789]*) printf '0' ;; *) printf '%s' "$1" ;; esac
}

# _nc_verdict <node> <nc_present> <nc_b64> — does this network-config (the node's exact
# bytes) configure Closed admission for <node>? Prints one observation; rc 0 yes, 1 no.
#   (a) what the NODE's parser (serde_yaml 0.8) sees: no UTF-8 BOM (serde_yaml makes it
#       part of the first key), exactly one column-0 `admission:` whose block (up to the
#       next column-0 key) holds `mode: Closed`, and one column-0 `committee_peers:`.
#       The node ignores an unknown top-level key, so a misspelt `admission` runs Open.
#   (b) devnet-network-config.py validate --node <node>, as devnet-network-config.sh
#       --verify runs it: exact keys, shapes and content (a `hostname:` line is allowed).
#   (a) alone misses wrong content; (b) parses with PyYAML, which drops a BOM and expands
#   `<<` merge keys where serde_yaml does neither, so (a) reads the raw lines instead and
#   holds even where (b)'s own guards for those cases would not.
_nc_verdict() {
    local node="$1" present="$2" b64="$3" f bad="" shape err host
    f="${WORK}/${node}/network-config"
    if [ "${present}" != "1" ]; then echo "missing"; return 1; fi
    mkdir -p "${WORK}/${node}"
    if ! printf '%s' "${b64}" | base64 --decode > "${f}" 2>/dev/null || [ ! -s "${f}" ]; then
        echo "empty or unreadable"; return 1
    fi
    if [ "$(head -c 3 "${f}" | od -An -tx1 | tr -d ' \n')" = "efbbbf" ]; then
        bad="${bad} starts with a UTF-8 BOM;"
    fi
    shape="$(awk '
        /^admission:[ \t]*$/ { adm++; inblock = 1; next }
        /^[^ \t#]/ { inblock = 0 }
        inblock && /^[ \t]+mode:[ \t]*Closed[ \t]*$/ { closed++ }
        /^committee_peers:[ \t]*$/ { peers++ }
        END { printf "admission:x%d mode-Closed-in-it:x%d committee_peers:x%d", adm, closed, peers }' "${f}")"
    case "${shape}" in
        "admission:x1 mode-Closed-in-it:x1 committee_peers:x1") ;;
        *) bad="${bad} ${shape} (want x1 each);" ;;
    esac
    if ! err="$(python3 "${NC_PY}" validate "${NC_CTX[@]}" --node "${node}" "${f}" 2>&1 >/dev/null)"; then
        err="${err//"${f}"/network-config}"
        bad="${bad} validator: $(printf '%s\n' "${err}" | grep -c '^FAIL') error(s), first: $(printf '%s\n' "${err}" | grep -m 1 '^FAIL' | cut -c 6-220);"
    fi
    host="$(grep -m 1 '^hostname:' "${f}" || true)"
    if [ -n "${bad}" ]; then echo "NOT Closed:${bad} ${host:-no hostname line}"; return 1; fi
    echo "Closed admission, committee_peers, validator ok for ${node}; ${host:-no hostname line}"
}

# _report <node> <rc> <label> <observed> — one assertion line.
_report() {
    local mark="✓"
    if [ "$2" -ne 0 ]; then mark="✗"; fi
    printf '    %s [%s] %s: %s\n' "${mark}" "$1" "$3" "$4"
}

# --- phase B assertions (each prints one line; rc 0 pass, 1 fail) ---------------------

# A1 <inst> <zone> <node> <svc>
assert_service() {
    local inst="$1" zone="$2" node="$3" svc="$4" script out st="" en="" nr="" waited=0 polls=0 bad=""
    script="$(_rs_service)"
    while :; do
        if ! out="$(_tn_probe "${inst}" "${zone}" "${script}" "${svc}")"; then
            bad="${out} at ${waited}s"; break
        fi
        st="$(_kv "${out}" active)"; en="$(_kv "${out}" enabled)"; nr="$(_kv "${out}" nrestarts)"
        polls=$((polls + 1))
        if [ "${st}" != "active" ]; then bad="is-active=${st:-?} at ${waited}s"; break; fi
        if [ "${nr}" != "0" ]; then bad="NRestarts=${nr:-?} at ${waited}s"; break; fi
        if [ "${waited}" -ge "${FINALIZE_STABLE_SECS}" ]; then break; fi
        sleep "${FINALIZE_STABLE_POLL_SECS}"
        waited=$((waited + FINALIZE_STABLE_POLL_SECS))
    done
    if [ -z "${bad}" ] && [ "${en}" != "enabled" ]; then bad="is-enabled=${en:-?}"; fi
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A1 service" "${bad} (polls ${polls}; is-active=${st:-?} is-enabled=${en:-?} NRestarts=${nr:-?})"
        return 1
    fi
    _report "${node}" 0 "A1 service" "is-active=active for ${waited}s (${polls} polls), is-enabled=${en}, NRestarts=${nr}"
}

# A2 <inst> <zone> <node>. Also sets META_DATA_DIR / META_NODE_LOG_DIR for A3 / A4.
META_DATA_DIR=""
META_NODE_LOG_DIR=""
assert_meta() {
    local inst="$1" zone="$2" node="$3" net dig rc_net=0 rc_dig=0 rc_nl=0 bad=""
    net="$(tn_node_meta_get "${inst}" "${zone}" NETWORK)" || rc_net=$?
    dig="$(tn_node_meta_get "${inst}" "${zone}" DOCKER_IMAGE_DIGEST)" || rc_dig=$?
    META_DATA_DIR="$(tn_node_meta_get "${inst}" "${zone}" DATA_DIR)" || META_DATA_DIR=""
    META_NODE_LOG_DIR="$(tn_node_meta_get "${inst}" "${zone}" NODE_LOG_DIR 2>/dev/null)" || rc_nl=$?
    if [ "${rc_nl}" -ne 0 ]; then META_NODE_LOG_DIR=""; fi
    if [ "${rc_net}" -ne 0 ]; then net="<unread rc ${rc_net}>"; fi
    if [ "${rc_dig}" -ne 0 ]; then dig="<unread rc ${rc_dig}>"; fi
    if [ "${net}" != "devnet" ]; then bad=1; fi
    if [ "${dig}" != "${IMAGE_DIGEST}" ]; then bad=1; fi
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A2 node-meta" "NETWORK=${net} (want devnet), DOCKER_IMAGE_DIGEST=${dig} (want ${IMAGE_DIGEST})"
        return 1
    fi
    _report "${node}" 0 "A2 node-meta" "NETWORK=${net}, DOCKER_IMAGE_DIGEST=${dig}"
}

# A3 <inst> <zone> <node> <data-dir>
assert_network_config() {
    local inst="$1" zone="$2" node="$3" nc="$4/network-config" out obs
    if ! out="$(_tn_probe "${inst}" "${zone}" "$(_rs_nc)" "${nc}")"; then
        _report "${node}" 1 "A3 network-config" "${out}"; return 1
    fi
    if obs="$(_nc_verdict "${node}" "$(_kv "${out}" nc_present)" "$(_kv "${out}" nc_b64)")"; then
        _report "${node}" 0 "A3 network-config" "${nc}: ${obs}"
        return 0
    fi
    _report "${node}" 1 "A3 network-config" "${nc}: ${obs}"
    return 1
}

# A4 <inst> <zone> <node> <svc> <node-log-dir> <gate logmarks> <gate journal cursor>
assert_logs() {
    local inst="$1" zone="$2" node="$3" svc="$4" nodelog="$5" marks="$6" cursor="$7" out line rest n pat first
    local summary="" firsts="" bad="" lines files journal jrc
    if ! out="$(_tn_probe "${inst}" "${zone}" "$(_rs_logs)" "${svc}" "${nodelog}" "${marks}" "${cursor}")"; then
        _report "${node}" 1 "A4 logs" "${out}"; return 1
    fi
    files="$(_kv "${out}" files)"; lines="$(_num "$(_kv "${out}" lines)")"; jrc="$(_kv "${out}" journal_rc)"
    journal="$(_kv "${out}" journal) lines $(_kv "${out}" journal_from)"
    if [ "${jrc}" != "0" ]; then journal="${journal}, journalctl rc ${jrc:-?}"; bad=1; fi
    while IFS= read -r line; do
        case "${line}" in hit=*) ;; *) continue ;; esac
        rest="${line#hit=}"; n="${rest%%|*}"; rest="${rest#*|}"; pat="${rest%%|*}"; first="${rest#*|}"
        n="$(_num "${n}")"
        summary="${summary} '${pat}'=${n}"
        if [ "${n}" -ne 0 ]; then
            bad=1
            firsts="${firsts}"$'\n'"        first '${pat}': ${first}"
        fi
    done <<< "${out}"
    if [ -z "${summary}" ]; then bad=1; summary=" no pattern counts returned"; fi
    if [ "${lines}" -eq 0 ]; then bad=1; summary="${summary} (no log lines since the gate to scan)"; fi
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A4 logs" "${lines} lines scanned (files:${files:- none}; journal: ${journal}):${summary}${firsts}"
        return 1
    fi
    _report "${node}" 0 "A4 logs" "${lines} lines scanned (files:${files:- none}; journal: ${journal}):${summary}"
}

# A5 <inst> <zone> <node> <svc>
assert_runtime() {
    local inst="$1" zone="$2" node="$3" svc="$4" out exe pull ro cont running rofs cimg pids hits obs bad=""
    if ! out="$(_tn_probe "${inst}" "${zone}" "$(_rs_runtime)" "${svc}")"; then
        _report "${node}" 1 "A5 runtime" "${out}"; return 1
    fi
    exe="$(_kv "${out}" execstart)"; pull="$(_kv "${out}" launch_pull)"; ro="$(_kv "${out}" launch_ro)"
    cont="$(_kv "${out}" container)"; pids="$(_kv "${out}" env_pids)"; hits="$(_kv "${out}" env_hits)"
    running="${cont%% *}"; rofs="${cont#* }"; rofs="${rofs%% *}"; cimg="${cont##* }"
    if [ "${exe}" != "${TN_START_DOCKER}" ]; then bad="${bad} ExecStart;"; fi
    if [ "${running}" != "true" ]; then bad="${bad} container-not-running;"; fi
    if [ "${rofs}" != "true" ]; then bad="${bad} rootfs-not-read-only;"; fi
    if [ "${cimg}" != "${DOCKER_IMAGE}" ]; then bad="${bad} image;"; fi
    if [ "${pull}" != "1" ]; then bad="${bad} no--pull=never;"; fi
    if [ "${ro}" != "1" ]; then bad="${bad} no--read-only;"; fi
    if [ -z "${pids// /}" ]; then bad="${bad} no-node-pid-checked;"; fi
    if [ "${hits}" != "0" ]; then bad="${bad} TN_BLS_PASSPHRASE-in-environ;"; fi
    obs="ExecStart=${exe:-?}; container running=${running:-?} ReadonlyRootfs=${rofs:-?} image=${cimg:-?}; MainPID $(_kv "${out}" mainpid) '$(_kv "${out}" launch_cmd)...' --pull=never=${pull:-?} --read-only=${ro:-?}; TN_BLS_PASSPHRASE in environ of pids [${pids# }]: ${hits:-?}"
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A5 runtime" "MISS:${bad} ${obs}"; return 1
    fi
    _report "${node}" 0 "A5 runtime" "${obs}"
}

echo ">>> finalize targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"
echo ">>> image ${DOCKER_IMAGE}"

finalized=()   # "index" of nodes that passed phase A
LOG_MARKS=()        # by index: the gate's logmark values, for A4
JOURNAL_CURSORS=()  # by index: the gate's journal cursor, for A4
verified=()
failed=()

# --- phase A: gate, stage, finalize, health ------------------------------------------
for i in "${INDICES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    addr="${EXECUTION_ADDRESSES[$i]}"
    role="$(tn_node_role "$i")"
    gdir="$(tn_genesis_dir_for_role "${role}")"
    ddir="$(tn_data_dir_for_role "${role}")"
    setup="$(tn_setup_script_for_role "${role}")"
    service="$(tn_service_for_role "${role}")"

    echo ""
    echo ">>> [${node}] finalize on ${inst} (${zone}) role=${role} service=${service}"

    # --- Step 0: local checks ------------------------------------------------------
    case "${addr}" in
        0x*) _ahex="${addr#0x}" ;;
        *) _ahex="" ;;
    esac
    case "${_ahex}" in *[!0123456789abcdefABCDEF]*) _ahex="" ;; esac
    if [ "${#_ahex}" -ne 40 ]; then
        echo "❌ [${node}] EXECUTION_ADDRESSES[${i}]='${addr}' is not 0x + 40 hex (config.sh)"
        failed+=("${node}: bad execution address"); continue
    fi

    # --- Step 1: readiness gate ----------------------------------------------------
    if ! gate="$(_tn_probe "${inst}" "${zone}" "$(_rs_ready)" "${setup}" "${service}" "${ddir}" "${TN_LOG_DIR}")"; then
        echo "❌ [${node}] readiness gate: ${gate}"
        failed+=("${node}: readiness gate (no answer)"); continue
    fi
    gate_bad=""
    if [ "$(_kv "${gate}" setup)" != "1" ]; then gate_bad="${gate_bad} ${setup} missing (fetch the node scripts);"; fi
    if [ "$(_kv "${gate}" keygen)" != "1" ]; then gate_bad="${gate_bad} no keygen record in /etc/telcoin/.node-meta (run ./devnet-keygen.sh);"; fi
    if [ "$(_kv "${gate}" installed)" != "0" ]; then gate_bad="${gate_bad} a ${service} unit is already installed (v2 refuses finalize over it: edit-config.sh, or remove-node.sh first);"; fi
    if ! nc_obs="$(_nc_verdict "${node}" "$(_kv "${gate}" nc_present)" "$(_kv "${gate}" nc_b64)")"; then
        gate_bad="${gate_bad} $(_kv "${gate}" nc) ${nc_obs} (run ./devnet-network-config.sh --yes ${node});"
    fi
    if [ -n "${gate_bad}" ]; then
        echo "❌ [${node}] not ready to finalize:${gate_bad}"
        failed+=("${node}: readiness gate"); continue
    fi
    echo ">>> [${node}] ready: setup-node.sh present, keygen recorded, no unit yet, $(_kv "${gate}" nc): ${nc_obs}"
    # Where the logs end before this finalize: A4 reads only what comes after.
    LOG_MARKS[i]="$(printf '%s\n' "${gate}" | sed -n 's/^logmark=//p' | tr '\n' ' ')"
    JOURNAL_CURSORS[i]="$(_kv "${gate}" jcursor)"

    # --- Step 2: stage genesis files (root-owned 0644) ------------------------------
    echo ">>> [${node}] staging committee/genesis/parameters to ${gdir}"
    stage_ok=1
    tn_iap_scp "${COMMITTEE_LOCAL}" "${inst}" "${zone}" "/tmp/committee.yaml" || stage_ok=0
    tn_iap_scp "${GENESIS_LOCAL}"   "${inst}" "${zone}" "/tmp/genesis.yaml"   || stage_ok=0
    tn_iap_scp "${PARAMETERS_FILE}" "${inst}" "${zone}" "/tmp/parameters.yaml" || stage_ok=0
    if [ "${stage_ok}" -ne 1 ]; then
        echo "❌ [${node}] failed to scp one or more genesis files"
        failed+=("${node}: scp"); continue
    fi
    stage_cmd="sudo install -d -o root -g root -m 0755 '${gdir%/*}' '${gdir}'"
    for f in committee.yaml genesis.yaml parameters.yaml; do
        stage_cmd="${stage_cmd} && sudo install -o root -g root -m 0644 /tmp/${f} '${gdir}/${f}'"
    done
    stage_cmd="${stage_cmd}; rc=\$?; rm -f /tmp/committee.yaml /tmp/genesis.yaml /tmp/parameters.yaml; exit \$rc"
    echo ">>> [${node}] running: ${stage_cmd}"
    if ! tn_iap_ssh "${inst}" "${zone}" "${stage_cmd}"; then
        echo "❌ [${node}] failed to install genesis files into ${gdir}"
        failed+=("${node}: stage"); continue
    fi
    echo ">>> [${node}] genesis staged in ${gdir} (root:root 0644)"

    # The node binds its P2P listeners to the INTERNAL IP (mirrors devnet-keygen.sh's
    # --listener-*). v2 writes them to /etc/telcoin/node.env, and finalize refuses to run
    # without both (an empty one would start a node with no listener).
    intIP="$(tn_node_int_ip "${inst}" "${zone}")"
    if [ -z "${intIP}" ]; then
        echo "❌ [${node}] could not resolve internal IP for listener multiaddrs"
        failed+=("${node}: internal IP"); continue
    fi
    # Finalize rewrites PUBLIC_IP / EXTERNAL_PRIMARY_ADDR / EXTERNAL_WORKER_ADDR in
    # .node-meta from its OWN flags (keygen does not keep them), so pass the same values
    # keygen passed or the fields stay empty for the UI and update tooling.
    extIP="$(tn_node_ext_ip "${inst}" "${zone}")"
    if [ -z "${extIP}" ]; then
        echo "❌ [${node}] could not resolve external IP for the advertised multiaddrs"
        failed+=("${node}: external IP"); continue
    fi

    # --- Step 3: finalize (node.env + start script + unit; start + enable) ----------
    finalize_args=(
        --json
        --phase=finalize
        --network devnet
        --install-method docker
        # Must equal what keygen recorded in .node-meta (finalize stops on a mismatch).
        --docker-image "${DOCKER_IMAGE}"
        # setup-node.sh looks here FIRST for genesis/committee/parameters.yaml.
        --genesis-dir "${gdir}"
        --data-dir "${ddir}"
        --service-user "${SERVICE_USER}"
        # Finalize rewrites VALIDATOR_ADDRESS in .node-meta from this flag (empty without
        # it), and its post-start check_validator_onchain_status probes the
        # ConsensusRegistry with it.
        --address "${addr}"
        # Finalize alone writes the network-config `hostname: "<name>"` line
        # (step_write_config -> write_advertised_name); keygen does not keep the name, so
        # pass the value keygen passes, the bare NODE_NAME.
        --advertised-name "${node}"
        # The node's own public, operator-facing endpoints, served by its Caddy edge
        # (https -> reth RPC :8545, wss -> reth WS :8546). Recorded in .node-meta
        # (PUBLIC_RPC_URL / PUBLIC_WS_URL) for the UI and tooling; never sent to the
        # network. No --rpc-domain: devnet's Caddy is config-caddy.sh (common/dns.sh).
        --public-rpc-url "https://${node}.${BASE_DOMAIN}"
        --public-ws-url "wss://${node}.${BASE_DOMAIN}"
        --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --external-primary "/ip4/${extIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --external-worker "/ip4/${extIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --public-ip "${extIP}"
        # Bakes `--healthcheck 43174` (TN_KUMA_PORT) into the start script's node line, so
        # the node opens the listener Uptime Kuma and the GCP LB probe. Needs nothing
        # else on devnet (is_testnet_like); the host-firewall rule is devnet-firewall.sh's.
        --enable-healthcheck-monitor
    )
    finalize_cmd="sudo bash '${setup}'"
    for a in "${finalize_args[@]}"; do finalize_cmd="${finalize_cmd} '${a}'"; done
    echo ">>> [${node}] running: ${finalize_cmd}"

    fin_rc=0
    fin_out="$(tn_iap_ssh "${inst}" "${zone}" "${finalize_cmd}" </dev/null)" || fin_rc=$?
    if [ -n "${fin_out}" ]; then printf '%s\n' "${fin_out}" | sed 's/^/    json: /'; fi
    fin_done="$(tn_json_done_line "${fin_out}")"
    if [ "${fin_rc}" -ne 0 ] || ! tn_json_true "${fin_done}" ok; then
        echo "❌ [${node}] finalize failed (ssh rc ${fin_rc}; done: ${fin_done:-none})"
        failed+=("${node}: finalize"); continue
    fi
    echo ">>> [${node}] finalize ok"

    # --- Step 4: health gate ----------------------------------------------------------
    if ! wait_healthy "${inst}" "${zone}" "${service}"; then
        echo "❌ [${node}] not healthy after finalize"
        failed+=("${node}: health"); continue
    fi
    finalized+=("${i}")
done

# --- phase B: post-finalize assertions -----------------------------------------------
if [ "${#finalized[@]}" -gt 0 ]; then
    echo ""
    echo ">>> post-finalize assertions (${#finalized[@]} node(s); stability window ${FINALIZE_STABLE_SECS}s every ${FINALIZE_STABLE_POLL_SECS}s)"
fi
for i in ${finalized[@]+"${finalized[@]}"}; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    service="$(tn_service_for_role "$(tn_node_role "$i")")"
    echo ">>> [${node}] asserting ${inst}"
    misses=0
    assert_service "${inst}" "${zone}" "${node}" "${service}" || misses=$((misses + 1))
    assert_meta "${inst}" "${zone}" "${node}" || misses=$((misses + 1))
    data_dir="${META_DATA_DIR:-$(tn_data_dir_for_role "$(tn_node_role "$i")")}"
    assert_network_config "${inst}" "${zone}" "${node}" "${data_dir}" || misses=$((misses + 1))
    assert_logs "${inst}" "${zone}" "${node}" "${service}" "${META_NODE_LOG_DIR}" \
        "${LOG_MARKS[$i]:-}" "${JOURNAL_CURSORS[$i]:-}" || misses=$((misses + 1))
    assert_runtime "${inst}" "${zone}" "${node}" "${service}" || misses=$((misses + 1))
    if [ "${misses}" -eq 0 ]; then
        verified+=("${node} (${service})")
    else
        failed+=("${node}: ${misses} assertion(s) failed")
    fi
done

echo ""
echo "========================================="
echo "finalize summary"
echo "========================================="
echo "finalized + verified (${#verified[@]}):"
for n in ${verified[@]+"${verified[@]}"}; do echo "  - ${n}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    exit 1
fi
echo "all targeted nodes finalized, started, enabled and verified."
