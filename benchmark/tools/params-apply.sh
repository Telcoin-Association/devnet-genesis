#!/usr/bin/env bash
# params-apply.sh — put a running fleet into a benchmark arm, one node at a time: node switches
# (benchmark/arms/switches.tsv) and consensus timing parameters in each node's parameters.yaml.
# Every node is restarted and back in consensus, with its new state read back from its own log,
# before the next is touched, and the arm is recorded (manifest.param_arms) so the report knows
# which state ran when.
#
# An arm is either
#   --arm-file <file>  an arm file (benchmark/arms/README.md): the FULL switch state (every switch
#                      it does not list is at its default) plus host steps. A file that breaks the
#                      grammar is refused as a whole before any node is contacted; or
#   --set ...          the given keys only (timing keys and switches), on top of what each node has.
#
# Phase A (read-only, every node of the list, up to 5 at once): where the node's parameters.yaml
#   is, its content and sha256, whether the telcoin container runs, its chain id, the `node
#   switches` line the running container logged at its start, and whether the v2 library (the
#   committee guard) and systemd-run are there. Any node failing here stops the run before anything
#   changes. The datadir: the nodes file's hostdatadir, else DATA_DIR in /etc/telcoin/.node-meta
#   (v2), else the bind mount of the node's launch file (/usr/local/libexec/telcoin/tn-start-docker;
#   /opt/telcoin/start-telcoin.sh only when a pre-v2 node has no v2 start script). The output
#   names the launch file and the datadir's source.
# Validation (local, before any restart): every node's resulting timing values against the node's
#   own startup rules (the deploy gate's, bench-lib.sh bench_node_params_problems), and the
#   switches the running image prints against the arm's; then the plan, per node: the keys to
#   rewrite (those whose effective value in the file is not the target: a switch the file leaves
#   out is at its default, the node writes none at its default; an absent key is appended, and a
#   switch going back to its default is written out with the default, never deleted) and whether
#   it restarts: a key rewritten, its running switches differ from the arm's or cannot be read, or
#   the arm has host steps. Values compare by value: durations in ms (the node prints a zero
#   duration as 0s, the tsv spells it 0ms).
# Phase B (serial; never more than one node down; observers first), per node in one session:
#   1. the committee guard (v2 tn_committee_down_guard against the node's own RPC), up to 8
#      samples 10 s apart: one refusal is a sample, eight in a row are a deferral; after a deferral
#      60 s and 8 more; a second deferral stops the run (lessons 2026-11-05);
#   2. the container log saved as /var/lib/bench-logs/telcoin-pre-arm-<arm>-<UTC>.log.gz (the
#      harness pull collects it);
#   3. no stop within ±90 s of an epoch boundary (v2 tn_epoch_secs_left): a bounded wait, and the
#      guard again after one;
#   4. parameters.yaml.bak-<UTC> kept, the keys rewritten in place (`key: value  # bench-override`);
#   5. one transient unit, systemd-run --unit bench-arm-<arm>-<UTC>, stops telcoin, runs the arm's
#      host steps and starts telcoin, so a dropped IAP session cannot leave the node stopped; its
#      output: /var/lib/bench-logs/arm-units/<unit>.out;
#   6. wait until eth_chainId answers and the node's consensus has moved past where it was, then
#      read back the timing boot lines and the `node switches` line of THIS start:
#        SWITCHES_OK <node> <key>=<value> ...
#        PARAMS_OK <node> max=<ms> min=<ms> batch=<ms> thr=<n> vote=<ms|->
#   The first node that fails stops the run: PA_FAIL <node> <why>, exit 1, `failed` recorded, later
#   nodes untouched. When the whole fleet has read back: ARM_READY <arm> ready=<UTC> ...
# Nothing to change (every node already has the arm, and runs it): nothing restarts; the arm is
#   still recorded (begin = now, no_restart: true) once every node of the arm passes its readback
#   on what phase A read and its telcoin container runs.
#
# Usage: params-apply.sh (--nodes <file> | --from-config) --arm-file <file> [--arm <name>]
#        params-apply.sh (--nodes <file> | --from-config) --set <all|node>:<key>=<value>[,...] ... --arm <name>
#        params-apply.sh (--nodes <file> | --from-config) --stage-test <node> [--set ...]
#        params-apply.sh (--nodes <file> | --from-config) --close-arm <name> | --mark <label> | --end-mark <label>
#        (--help for every option)
# Docs:  benchmark/tools/README.md, section "params-apply".
#
# Standalone: it never sources bench-lib.sh, and with --nodes nothing of the devnet config either.
# Needs: bash (3.2 is enough), perl, awk, jq (recording) and an authenticated gcloud; on the nodes
# the v2 scripts' library (lib/common.sh) and systemd-run.
set -euo pipefail

readonly SSH_PARALLEL=5
readonly PHASE_A_SECS=120
# The node's launch file, only read (for the datadir): v2's start script (tn-node-deployment
# lib/common.sh tn_start_script_path docker); the wrapper pre-v2 nodes ran only when that is absent.
readonly REMOTE_START=/usr/local/libexec/telcoin/tn-start-docker
readonly REMOTE_LEGACY_WRAPPER=/opt/telcoin/start-telcoin.sh
readonly REMOTE_NODE_META=/etc/telcoin/.node-meta
readonly REMOTE_LOG_DIR=/var/lib/bench-logs
# The timing keys, <type>:<key>; dur = <int>ms|<int>s, int = positive integer, bool = true|false.
# The node's Parameters at ba43a1f0e (crates/config/src/node.rs). Keep in step with the literal
# export of BENCH_NODE_PARAM_KEYS in benchmark/config.sh (tests/test_params_apply.py compares them).
# The node switches are not listed here: they come from benchmark/arms/switches.tsv (load_switches).
readonly PARAM_KEYS="dur:max_header_delay dur:min_header_delay dur:vote_timeout dur:max_batch_delay dur:sync_retry_delay int:header_num_of_batches_threshold int:max_header_num_of_batches int:sync_retry_nodes int:max_concurrent_requests bool:allow_private_forward_targets"
readonly TAB=$'\t' NL=$'\n'
readonly DUR_RE='^[0-9]+(ms|s)$'
# An arm or mark name (the arm-name rule of report/make_bundle.py and benchmark/arms/README.md).
readonly ARM_NAME_RE='^[a-z0-9][a-z0-9-]{0,39}$'

usage() {
    cat <<'EOF'
Usage:
  params-apply.sh (--nodes <file> | --from-config) --arm-file <file> [--arm <name>]
  params-apply.sh (--nodes <file> | --from-config) --set <target>:<key>=<value>[,...] [--set ...] --arm <name>
  params-apply.sh (--nodes <file> | --from-config) --stage-test <node> [--set ...]
  params-apply.sh (--nodes <file> | --from-config) --close-arm <name>
  params-apply.sh (--nodes <file> | --from-config) --mark <label> | --end-mark <label>

Puts running nodes into an arm, one node at a time: read every node (read-only), validate, then
per node take the committee guard (sampled), save its container log, wait out an epoch boundary,
rewrite <datadir>/parameters.yaml, stop and start telcoin inside one transient systemd unit (with
the arm's host steps in between), wait until it is back in consensus and read its `node switches`
line back. Records the arm in <results-dir>/manifest.json (param_arms), else in param-arms.json
beside the nodes file.

Nodes:
  --nodes <file>        lines "name zone project role [hostdatadir]" (# comments allowed);
                        role validator|observer; project '-' = --project; hostdatadir = the HOST
                        directory holding parameters.yaml (default: DATA_DIR in the node's
                        /etc/telcoin/.node-meta, else the bind mount of its launch file
                        /usr/local/libexec/telcoin/tn-start-docker, or of
                        /opt/telcoin/start-telcoin.sh on a node without the v2 one)
  --from-config         the benchmark fleet of benchmark/config.sh (needs BENCH_RUN_ID); writes
                        results/<run>/nodes.txt (hostdatadir = VALIDATOR_DATA_DIR) and records
                        into results/<run>/manifest.json
  --validators-only     leave observers out (default: observers are changed too)
  --project <id>        project for nodes-file lines whose project is '-' (with --from-config:
                        instead of the config's PROJECT_ID)

What to change:
  --arm-file <file>     an arm file (benchmark/arms/README.md): the whole switch state and the
                        host steps. Every switch it does not list goes to its default. The arm's
                        name is the file's `name` line unless --arm gives another (a re-run after
                        a failure needs a new name). No --set beside it.
  --set <t>:<k>=<v>[,<k>=<v>...]
                        <t> = all, or one node's name (a node's own --set wins over all:).
                        Timing keys (durations <int>ms or <int>s): max_header_delay
                        min_header_delay vote_timeout max_batch_delay sync_retry_delay; integers:
                        header_num_of_batches_threshold max_header_num_of_batches sync_retry_nodes
                        max_concurrent_requests; boolean: allow_private_forward_targets.
                        Node switches: every key of benchmark/arms/switches.tsv, with one of its
                        arm values or its default. gc_depth and basefee_address are fleet-wide
                        (refused here).
  --arm <name>          the arm's name, [a-z0-9-], unique in the record; it names the saved log
                        telcoin-pre-arm-<name>-<UTC>.log.gz and the unit bench-arm-<name>-<UTC>
                        on each restarted node. When every node already has the arm, nothing
                        restarts and the arm is still recorded (begin = now, no_restart: true)
  --stage-test <node>   read, save the log, rewrite with the CURRENT values, restart and wait on
                        that one node: proves the remote path without changing anything. Run it
                        before the first arm of a fleet. No arm is recorded.
  --close-arm <name>    set the open arm <name>'s end (and its open marks' end) to now
  --mark <label>        open a sub-window <label> of the open arm (begin = now); it ends at
                        --end-mark <label>, the next --mark or the arm's end
  --end-mark <label>    set the open mark <label>'s end to now
                        (--close-arm, --mark and --end-mark contact no node)

Other:
  --results-dir <dir>   where manifest.json is (default with --from-config: results/<run>)
  --dry-run             print the per-node plan, every gcloud argv and every remote script;
                        contact nothing, record nothing
  -h, --help            this text

Environment (defaults in brackets): PARAMS_APPLY_HEALTH_SECS [180] back-in-consensus wait,
PARAMS_APPLY_GUARD_TRIES [8] and PARAMS_APPLY_GUARD_SECS [10] guard samples and their spacing,
PARAMS_APPLY_GUARD_DEFER_SECS [60] pause after a deferral, PARAMS_APPLY_EPOCH_MARGIN_SECS [90]
no stop this close to an epoch boundary, PARAMS_APPLY_EPOCH_WAIT_SECS [600] the longest wait for
that, PARAMS_APPLY_UNIT_SECS [600] the longest wait for the unit's start, PARAMS_APPLY_SETTLE_SECS
[120] ready = last node back + this, PARAMS_APPLY_RETRY_SECS [10] IAP retry pause,
PARAMS_APPLY_NODE_SCRIPTS_DIR [config TN_NODE_SCRIPTS_DIR, else /opt/telcoin-node-scripts],
PARAMS_APPLY_GUARD_PUBLIC_RPC [config BENCH_GUARD_PUBLIC_RPC, else http://127.0.0.1:9].
EOF
}

die() { echo "params-apply: $*" >&2; exit 2; }
fatal() { echo "params-apply: $*" >&2; exit 1; }
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# --- arguments -------------------------------------------------------------------------
NODES_FILE="" FROM_CONFIG=0 ARM="" ARM_FILE="" STAGE="" CLOSE="" MARK="" END_MARK="" VALIDATORS_ONLY=0 DRY=0
PROJECT="" RESULTS_DIR=""
SETS=()
HEALTH_SECS="${PARAMS_APPLY_HEALTH_SECS:-180}"
RETRY_SECS="${PARAMS_APPLY_RETRY_SECS:-10}"
GUARD_TRIES="${PARAMS_APPLY_GUARD_TRIES:-8}"
GUARD_SECS="${PARAMS_APPLY_GUARD_SECS:-10}"
GUARD_DEFER_SECS="${PARAMS_APPLY_GUARD_DEFER_SECS:-60}"
EPOCH_MARGIN_SECS="${PARAMS_APPLY_EPOCH_MARGIN_SECS:-90}"
EPOCH_WAIT_SECS="${PARAMS_APPLY_EPOCH_WAIT_SECS:-600}"
UNIT_SECS="${PARAMS_APPLY_UNIT_SECS:-600}"
SETTLE_SECS="${PARAMS_APPLY_SETTLE_SECS:-120}"
NODE_SCRIPTS_DIR="${PARAMS_APPLY_NODE_SCRIPTS_DIR:-}"
GUARD_RPC="${PARAMS_APPLY_GUARD_PUBLIC_RPC:-}"

while [ $# -gt 0 ]; do
    opt="$1" val=""
    case "${opt}" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY=1; shift; continue ;;
        --from-config) FROM_CONFIG=1; shift; continue ;;
        --validators-only) VALIDATORS_ONLY=1; shift; continue ;;
        --*=*) val="${opt#*=}"; opt="${opt%%=*}"; shift ;;
        --*) [ $# -ge 2 ] || die "${opt} needs a value"; val="$2"; shift 2 ;;
        *) die "unexpected argument '${opt}' (try --help)" ;;
    esac
    case "${opt}" in
        --nodes) NODES_FILE="${val}" ;;
        --set) SETS+=("${val}") ;;
        --arm) ARM="${val}" ;;
        --arm-file) ARM_FILE="${val}" ;;
        --stage-test) STAGE="${val}" ;;
        --close-arm) CLOSE="${val}" ;;
        --mark) MARK="${val}" ;;
        --end-mark) END_MARK="${val}" ;;
        --project) PROJECT="${val}" ;;
        --results-dir) RESULTS_DIR="${val}" ;;
        *) die "unknown option '${opt}' (try --help)" ;;
    esac
done

if [ "${FROM_CONFIG}" = 1 ]; then
    [ -z "${NODES_FILE}" ] || die "give --nodes or --from-config, not both"
else
    [ -n "${NODES_FILE}" ] || die "--nodes <file> or --from-config is required"
fi
if [ -n "${CLOSE}${MARK}${END_MARK}" ]; then
    for pair in "close-arm:${CLOSE}" "mark:${MARK}" "end-mark:${END_MARK}"; do
        [ -n "${pair#*:}" ] || continue
        [ "${#SETS[@]}" -eq 0 ] && [ -z "${STAGE}${ARM}${ARM_FILE}" ] && [ "${CLOSE}${MARK}${END_MARK}" = "${pair#*:}" ] \
            || die "--${pair%%:*} runs on its own (no --set, --arm, --arm-file, --stage-test, --close-arm, --mark or --end-mark)"
        MODE="${pair%%:*}"
    done
elif [ -n "${STAGE}" ]; then
    MODE=stage
    [ -z "${ARM_FILE}" ] || die "--stage-test writes the current values back; it takes no --arm-file"
elif [ -n "${ARM_FILE}" ]; then
    MODE=apply
    [ "${#SETS[@]}" -eq 0 ] || die "--arm-file is the whole switch state: no --set beside it"
else
    MODE=apply
    [ "${#SETS[@]}" -gt 0 ] || die "nothing to do: give --arm-file, --set (with --arm), --stage-test, --close-arm or --mark"
    [ -n "${ARM}" ] || die "--set needs --arm <name>"
fi
# An arm name becomes part of a log file name and a unit name the harness pull and
# report/provenance.py parse.
for pair in "arm:${ARM}" "close-arm:${CLOSE}" "mark:${MARK}" "end-mark:${END_MARK}"; do
    v="${pair#*:}"
    [ -n "${v}" ] || continue
    case "${v}" in
        -*|*-|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*) die "--${pair%%:*} '${v}' must be [a-z0-9-], not starting or ending with '-'" ;;
    esac
    [ "${#v}" -le 40 ] || die "--${pair%%:*} '${v}' is longer than 40 characters"
done
case "${PROJECT}" in *[!a-z0-9.:-]*) die "--project '${PROJECT}' is not a project id" ;; esac
case "${HEALTH_SECS}" in ''|*[!0-9]*|0*) die "PARAMS_APPLY_HEALTH_SECS='${HEALTH_SECS}' must be a positive integer" ;; esac
case "${RETRY_SECS}" in ''|*[!0-9]*) die "PARAMS_APPLY_RETRY_SECS='${RETRY_SECS}' must be an integer" ;; esac
case "${GUARD_TRIES}" in ''|*[!0-9]*|0*) die "PARAMS_APPLY_GUARD_TRIES='${GUARD_TRIES}' must be a positive integer" ;; esac
for pair in "GUARD_SECS:${GUARD_SECS}" "GUARD_DEFER_SECS:${GUARD_DEFER_SECS}" "EPOCH_MARGIN_SECS:${EPOCH_MARGIN_SECS}" \
            "EPOCH_WAIT_SECS:${EPOCH_WAIT_SECS}" "SETTLE_SECS:${SETTLE_SECS}"; do
    case "${pair#*:}" in ''|*[!0-9]*) die "PARAMS_APPLY_${pair%%:*}='${pair#*:}' must be a whole number of seconds" ;; esac
done
case "${UNIT_SECS}" in ''|*[!0-9]*|0*) die "PARAMS_APPLY_UNIT_SECS='${UNIT_SECS}' must be a positive integer" ;; esac
command -v perl >/dev/null 2>&1 || die "perl is required (gcloud runs under its alarm)"
if [ "${DRY}" = 0 ] && [ "${MODE}" != stage ]; then
    command -v jq >/dev/null 2>&1 || die "jq is required (it records the arm)"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/params-apply.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/sets"

# --- the node switches (benchmark/arms/switches.tsv, the single source of their names) ------
# SW_K/SW_T/SW_D/SW_V/SW_O[i]: key, type (bool|int|dur), default, arm values (comma list),
# optional (yes|no), in the file's row order. ALL_KEYS: PARAM_KEYS plus "<type>:<key>" per switch.
SWITCHES_TSV="${SCRIPT_DIR}/../arms/switches.tsv"
SW_K=() SW_T=() SW_D=() SW_V=() SW_O=()

# valid_val <type> <value> — rc 0 when <value> is a value of <type> as switches.tsv spells it:
# bool true|false, int a non-negative integer without leading zeros, dur <int>ms or <int>s.
valid_val() {
    local n
    case "$1:$2" in
        bool:true|bool:false|int:0) return 0 ;;
        int:[1-9]*) case "$2" in *[!0-9]*) return 1 ;; esac; [ "${#2}" -le 9 ] ;;
        dur:*ms|dur:*s)
            n="${2%ms}"; [ "${n}" != "$2" ] || n="${2%s}"
            case "${n}" in 0) return 0 ;; [1-9]*) case "${n}" in *[!0-9]*) return 1 ;; esac; [ "${#n}" -le 9 ] ;; *) return 1 ;; esac ;;
        *) return 1 ;;
    esac
}

load_switches() {
    local f="$1" ln=0 line k t d v o rest x seen=" "
    [ -f "${f}" ] && [ -r "${f}" ] || die "cannot read the switch registry ${f}"
    while IFS= read -r line || [ -n "${line}" ]; do
        ln=$((ln + 1))
        if [ "${ln}" = 1 ]; then
            [ "${line}" = "key${TAB}type${TAB}default${TAB}arm_values${TAB}topic${TAB}optional" ] \
                || die "${f}:1: not the switches.tsv header (key type default arm_values topic optional)"
            continue
        fi
        case "${line}" in ''|"${TAB}"*|*"${TAB}"|*"${TAB}${TAB}"*) die "${f}:${ln}: an empty field or line" ;; esac
        IFS="${TAB}" read -r k t d v _ o rest <<< "${line}"  # _ = the topic
        [ -n "${o}" ] && [ -z "${rest}" ] || die "${f}:${ln}: want six tab-separated fields"
        case "${k}" in [a-z]*) ;; *) die "${f}:${ln}: key '${k}' is not [a-z][a-z0-9_]*" ;; esac
        case "${k}" in *[!a-z0-9_]*) die "${f}:${ln}: key '${k}' is not [a-z][a-z0-9_]*" ;; esac
        case "${seen}" in *" ${k} "*) die "${f}:${ln}: ${k} is listed twice" ;; esac
        case " ${PARAM_KEYS} " in *":${k} "*) die "${f}:${ln}: ${k} is a timing key, not a switch" ;; esac
        case "${t}" in bool|int|dur) ;; *) die "${f}:${ln}: type '${t}' is not bool, int or dur" ;; esac
        valid_val "${t}" "${d}" || die "${f}:${ln}: default '${d}' is not a ${t}"
        for x in $(printf '%s' "${v}" | tr ',' ' '); do
            valid_val "${t}" "${x}" || die "${f}:${ln}: arm value '${x}' is not a ${t}"
        done
        case "${o}" in yes|no) ;; *) die "${f}:${ln}: optional '${o}' is not yes or no" ;; esac
        seen="${seen}${k} "
        SW_K+=("${k}") SW_T+=("${t}") SW_D+=("${d}") SW_V+=("${v}") SW_O+=("${o}")
    done < "${f}"
    [ "${#SW_K[@]}" -gt 0 ] || die "${f}: no switch rows"
}
load_switches "${SWITCHES_TSV}"
ALL_KEYS="${PARAM_KEYS}"
for i in "${!SW_K[@]}"; do ALL_KEYS="${ALL_KEYS} ${SW_T[$i]}:${SW_K[$i]}"; done
readonly ALL_KEYS

# has_line <text> <prefix> — rc 0 when a line of <text> starts with <prefix>. No pipe: under
# pipefail, `printf ... | grep -q` fails when grep exits on an early line before printf is done.
has_line() { case "${NL}$1" in *"${NL}$2"*) return 0 ;; esac; return 1; }

# sw_idx <key> — the switch's row index; rc 1 for a key that is not a switch.
sw_idx() {
    local i
    for i in "${!SW_K[@]}"; do [ "${SW_K[$i]}" != "$1" ] || { echo "${i}"; return 0; }; done
    return 1
}
# sw_arm_value <index> <value> — rc 0 when <value> is one of the row's arm values.
sw_arm_value() { case ",${SW_V[$1]}," in *",$2,"*) return 0 ;; esac; return 1; }

# --- the arm file ------------------------------------------------------------------------
# ${WORK}/arm.target: "key=value" per switch, in switches.tsv order (the arm's full state);
# ARM_HOST_STEPS: the host steps in run order (read-ahead-kb before evict-mdbx, whatever the order
# in the file), one per line; ARM_HOST_DESC the same on one line.
ARM_HOST_STEPS="" ARM_HOST_DESC="" ARM_FILE_SHA="" ARM_FILE_REL="" ARM_FILE_NAME=""

# arm_refuse <line> <why> — the whole file is refused (benchmark/arms/README.md, "What a parser refuses").
arm_refuse() { die "${ARM_FILE}:$1: $2; the arm file is refused, nothing was contacted"; }

parse_arm_file() {
    local f="$1" ln=0 line bad i k seen=" " ev=0 ra="" name=""
    bad="$(LC_ALL=C grep -an "$(printf '\r')" "${f}" | head -n 1 | cut -d: -f1 || true)"
    [ -z "${bad}" ] || arm_refuse "${bad}" "a carriage return (the file must have LF line ends)"
    bad="$(LC_ALL=C grep -an "$(printf '[^\t -~]')" "${f}" | head -n 1 | cut -d: -f1 || true)"
    [ -z "${bad}" ] || arm_refuse "${bad}" "a byte outside printable ASCII, space and tab"
    : > "${WORK}/arm.params"
    while IFS= read -r line || [ -n "${line}" ]; do
        ln=$((ln + 1))
        set -f
        # shellcheck disable=SC2086  # word splitting is the parse
        set -- ${line}
        set +f
        [ $# -gt 0 ] || continue
        case "$1" in '#'*) continue ;; esac
        case "$1" in
            name)
                [ $# -eq 2 ] || arm_refuse "${ln}" "'name' takes one value, got $(($# - 1)) (a directive has no trailing comment)"
                [ -z "${name}" ] || arm_refuse "${ln}" "a second 'name' line"
                [[ "$2" =~ ${ARM_NAME_RE} ]] || arm_refuse "${ln}" "'$2' is not an arm name ([a-z0-9][a-z0-9-]{0,39})"
                name="$2" ;;
            param)
                [ $# -eq 3 ] || arm_refuse "${ln}" "'param' takes <key> <value>, got $(($# - 1)) field(s) (a directive has no trailing comment)"
                i="$(sw_idx "$2")" || arm_refuse "${ln}" "unknown switch '$2' (benchmark/arms/switches.tsv: ${SW_K[*]})"
                case "${seen}" in *" $2 "*) arm_refuse "${ln}" "switch '$2' is given twice" ;; esac
                sw_arm_value "${i}" "$3" || arm_refuse "${ln}" "$2 $3: not one of its arm values (${SW_V[$i]})"
                seen="${seen}$2 "
                printf '%s=%s\n' "$2" "$3" >> "${WORK}/arm.params" ;;
            host)
                [ $# -ge 2 ] || arm_refuse "${ln}" "'host' takes a step (evict-mdbx, read-ahead-kb <n>)"
                case "$2" in
                    evict-mdbx)
                        [ $# -eq 2 ] || arm_refuse "${ln}" "'host evict-mdbx' takes no value, got $(($# - 2))"
                        [ "${ev}" = 0 ] || arm_refuse "${ln}" "'host evict-mdbx' is given twice"
                        ev=1 ;;
                    read-ahead-kb)
                        [ $# -eq 3 ] || arm_refuse "${ln}" "'host read-ahead-kb' takes one value (KiB), got $(($# - 2))"
                        [ -z "${ra}" ] || arm_refuse "${ln}" "'host read-ahead-kb' is given twice"
                        case "$3" in 0|[1-9]|[1-9]*[0-9]) ;; *) arm_refuse "${ln}" "read-ahead-kb '$3' is not a non-negative integer without leading zeros" ;; esac
                        case "$3" in *[!0-9]*) arm_refuse "${ln}" "read-ahead-kb '$3' is not a non-negative integer without leading zeros" ;; esac
                        [ "${#3}" -le 9 ] || arm_refuse "${ln}" "read-ahead-kb '$3' is too large"
                        ra="$3" ;;
                    *) arm_refuse "${ln}" "unknown host step '$2' (evict-mdbx, read-ahead-kb <n>)" ;;
                esac ;;
            *) arm_refuse "${ln}" "unknown directive '$1' (name, param, host; '#' starts a comment)" ;;
        esac
    done < "${f}"
    [ -n "${name}" ] || die "${ARM_FILE}: no 'name' line; the arm file is refused, nothing was contacted"
    ARM_FILE_NAME="${name}"
    : > "${WORK}/arm.target"
    for i in "${!SW_K[@]}"; do
        k="$(sed -n "s/^${SW_K[$i]}=//p" "${WORK}/arm.params")"
        printf '%s=%s\n' "${SW_K[$i]}" "${k:-${SW_D[$i]}}" >> "${WORK}/arm.target"
    done
    # The run order is fixed (README, Host steps): read-ahead, then the eviction, last before the start.
    [ -z "${ra}" ] || ARM_HOST_STEPS="read-ahead-kb ${ra}"
    [ "${ev}" = 0 ] || ARM_HOST_STEPS="${ARM_HOST_STEPS:+${ARM_HOST_STEPS}
}evict-mdbx"
    ARM_HOST_DESC="$(printf '%s\n' "${ARM_HOST_STEPS}" | awk 'NF { printf "%s%s", (n++ ? ", " : ""), $0 }')"
}

# sha256 of a local file.
local_sha256() { { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; } | awk '{ print $1 }'; }

if [ -n "${ARM_FILE}" ]; then
    [ -f "${ARM_FILE}" ] && [ -r "${ARM_FILE}" ] || die "--arm-file '${ARM_FILE}' is not a readable file"
    case "${ARM_FILE}" in *.arm) ;; *) die "--arm-file '${ARM_FILE}' is not an arm file (<name>.arm, benchmark/arms/README.md)" ;; esac
    # The bytes parsed, hashed and recorded are one copy.
    cp "${ARM_FILE}" "${WORK}/arm.file"
    parse_arm_file "${WORK}/arm.file"
    ARM_FILE_SHA="$(local_sha256 "${WORK}/arm.file")"
    abs="$(cd "$(dirname "${ARM_FILE}")" && pwd -P)/$(basename "${ARM_FILE}")"
    root="$(cd "${REPO_ROOT}" && pwd -P)"
    case "${abs}" in "${root}"/*) ARM_FILE_REL="${abs#"${root}"/}" ;; *) ARM_FILE_REL="${abs}" ;; esac
    if [ -z "${ARM}" ]; then
        ARM="${ARM_FILE_NAME}"
        case "${ARM}" in *-) die "${ARM_FILE}: arm name '${ARM}' ends with '-' (a log and unit name part); give --arm <name>" ;; esac
    fi
    [ "$(basename "${ARM_FILE}" .arm)" = "${ARM_FILE_NAME}" ] \
        || log "note: ${ARM_FILE}'s name line says '${ARM_FILE_NAME}', not the file name"
fi

# --- the node list ---------------------------------------------------------------------
# --from-config: the fleet of benchmark/config.sh, read in a subshell (config.sh admits this
# script by name; its exports, TN_USE_VPN=0 among them, never reach this shell). A dry run writes
# the list into its scratch dir, a real run into results/<run>/nodes.txt.
if [ "${FROM_CONFIG}" = 1 ]; then
    [ -n "${BENCH_RUN_ID:-}" ] || die "--from-config needs BENCH_RUN_ID (the run whose fleet to change)"
    cfg_out="$(
        # shellcheck source=/dev/null
        { source "${REPO_ROOT}/benchmark/config.sh"; } >&2
        printf 'RESULTS=%s\nPROJECT=%s\nDATADIR=%s\nSCRIPTS=%s\nGUARDRPC=%s\n' "${BENCH_RESULTS_DIR}" "${PROJECT_ID}" \
            "${VALIDATOR_DATA_DIR:-}" "${TN_NODE_SCRIPTS_DIR:-}" "${BENCH_GUARD_PUBLIC_RPC:-}"
        for i in "${!INSTANCE_NAMES[@]}"; do
            printf 'NODE=%s %s %s\n' "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "${NODE_ROLES[$i]}"
        done
    )" || die "benchmark/config.sh refused to load (see above)"
    [ -n "${RESULTS_DIR}" ] || RESULTS_DIR="$(printf '%s\n' "${cfg_out}" | sed -n 's/^RESULTS=//p')"
    [ -n "${PROJECT}" ] || PROJECT="$(printf '%s\n' "${cfg_out}" | sed -n 's/^PROJECT=//p')"
    [ -n "${NODE_SCRIPTS_DIR}" ] || NODE_SCRIPTS_DIR="$(printf '%s\n' "${cfg_out}" | sed -n 's/^SCRIPTS=//p')"
    [ -n "${GUARD_RPC}" ] || GUARD_RPC="$(printf '%s\n' "${cfg_out}" | sed -n 's/^GUARDRPC=//p')"
    case "${PROJECT}" in ''|*[!a-z0-9.:-]*) die "benchmark/config.sh PROJECT_ID '${PROJECT}' is not a project id" ;; esac
    # Every role's datadir (devnet-lib.sh tn_data_dir_for_role); the nodes-file parse checks the path.
    cfg_dd="$(printf '%s\n' "${cfg_out}" | sed -n 's/^DATADIR=//p')"
    [ -n "${cfg_dd}" ] || die "benchmark/config.sh exports no VALIDATOR_DATA_DIR"
    if [ "${DRY}" = 1 ]; then
        NODES_FILE="${WORK}/nodes.txt"
    else
        mkdir -p "${RESULTS_DIR}"
        NODES_FILE="${RESULTS_DIR}/nodes.txt"
    fi
    {
        echo "# name zone project role [hostdatadir] — written by params-apply.sh --from-config for ${BENCH_RUN_ID}"
        printf '%s\n' "${cfg_out}" | sed -n 's/^NODE=//p' | while read -r n z r; do echo "${n} ${z} ${PROJECT} ${r} ${cfg_dd}"; done
    } > "${NODES_FILE}"
    log "nodes from benchmark/config.sh (${BENCH_RUN_ID}) -> ${NODES_FILE}"
fi
[ -f "${NODES_FILE}" ] && [ -r "${NODES_FILE}" ] || die "cannot read nodes file '${NODES_FILE}'"
# The v2 scripts' checkout on the nodes (the committee guard and the epoch timing come from its
# lib/common.sh) and the guard's public fallback RPC, which must never be the real devnet's
# (bench-lib.sh bench_remote_lib_preamble): a dead local port unless the config names one.
NODE_SCRIPTS_DIR="${NODE_SCRIPTS_DIR:-/opt/telcoin-node-scripts}"
GUARD_RPC="${GUARD_RPC:-http://127.0.0.1:9}"
case "${NODE_SCRIPTS_DIR}" in /*[!A-Za-z0-9._/-]*|*..*) die "the node scripts dir '${NODE_SCRIPTS_DIR}' may hold only [A-Za-z0-9._/-]" ;; /?*) ;; *) die "the node scripts dir '${NODE_SCRIPTS_DIR}' is not an absolute path" ;; esac
case "${GUARD_RPC}" in http://*|https://*) ;; *) die "the guard's public RPC '${GUARD_RPC}' is not an http(s) URL" ;; esac
case "${GUARD_RPC}" in *[!A-Za-z0-9.:/_-]*) die "the guard's public RPC '${GUARD_RPC}' has unusual characters" ;; esac

N_NAME=() N_ZONE=() N_PROJ=() N_ROLE=() N_HD=()
zone_re='^[a-z]+-[a-z]+[0-9]+-[a-z]$'
name_re='^[a-z]([-a-z0-9]*[a-z0-9])?$'
lineno=0
while IFS= read -r line || [ -n "${line}" ]; do
    lineno=$((lineno + 1))
    line="${line%%#*}"
    set -f
    # shellcheck disable=SC2086  # word splitting is the parse
    set -- ${line}
    set +f
    [ $# -gt 0 ] || continue
    [ $# -eq 4 ] || [ $# -eq 5 ] || die "${NODES_FILE}:${lineno}: want 'name zone project role [hostdatadir]', got $# fields"
    n="$1" z="$2" p="$3" r="$4" hd="${5:-}"
    [[ "${n}" =~ ${name_re} ]] || die "${NODES_FILE}:${lineno}: '${n}' is not an instance name"
    [[ "${z}" =~ ${zone_re} ]] || die "${NODES_FILE}:${lineno}: '${z}' is not a zone (like us-west2-a)"
    if [ "${p}" = "-" ]; then
        [ -n "${PROJECT}" ] || die "${NODES_FILE}:${lineno}: project '-' needs --project"
        p="${PROJECT}"
    fi
    case "${p}" in ''|*[!a-z0-9.:-]*) die "${NODES_FILE}:${lineno}: '${p}' is not a project id" ;; esac
    case "${r}" in validator|observer) ;; *) die "${NODES_FILE}:${lineno}: role '${r}' is not validator or observer" ;; esac
    case "${hd}" in
        '') ;;
        /*) case "${hd}" in *[!A-Za-z0-9._/-]*|*..*) die "${NODES_FILE}:${lineno}: hostdatadir '${hd}' may hold only [A-Za-z0-9._/-]" ;; esac ;;
        *) die "${NODES_FILE}:${lineno}: hostdatadir '${hd}' is not an absolute path" ;;
    esac
    for seen in ${N_NAME[@]+"${N_NAME[@]}"}; do
        [ "${seen}" != "${n}" ] || die "${NODES_FILE}:${lineno}: ${n} is listed twice"
    done
    [ "${VALIDATORS_ONLY}" = 0 ] || [ "${r}" = validator ] || continue
    N_NAME+=("${n}") N_ZONE+=("${z}") N_PROJ+=("${p}") N_ROLE+=("${r}") N_HD+=("${hd}")
done < "${NODES_FILE}"
[ "${#N_NAME[@]}" -gt 0 ] || die "no nodes in ${NODES_FILE}"

# idx_of <node> — its index in the list; non-zero when absent.
idx_of() {
    local i
    for i in "${!N_NAME[@]}"; do [ "${N_NAME[$i]}" != "$1" ] || { echo "${i}"; return 0; }; done
    return 1
}

# --- keys, values, YAML ----------------------------------------------------------------
# key_type <key> — dur | int | bool, or "" for a key this tool does not set.
key_type() {
    local tk
    for tk in ${ALL_KEYS}; do [ "${tk#*:}" != "$1" ] || { echo "${tk%%:*}"; return 0; }; done
    echo ""
}

# to_ms <value> — a duration as written in parameters.yaml (500ms, 3s, 1.5s, 2m) in whole ms; ""
# for anything else. The rules of bench-lib.sh bench_params_ms.
to_ms() {
    awk -v v="${1:-}" 'BEGIN {
        if (v !~ /^[0-9]+(\.[0-9]+)?(ms|s|m)$/) exit
        u = v; sub(/^[0-9.]+/, "", u)
        n = substr(v, 1, length(v) - length(u)); i = n; f = ""
        if (index(n, ".")) { i = substr(n, 1, index(n, ".") - 1); f = substr(n, index(n, ".") + 1) }
        if (length(f) > 9) f = substr(f, 1, 9)
        mul = (u == "ms") ? 1 : ((u == "s") ? 1000 : 60000)
        printf "%d\n", i * mul + (f == "" ? 0 : int(f * mul / (10 ^ length(f))))
    }'
}

# norm_val <type> <value> — a switch value in one spelling, to compare: bool lower case, int
# without leading zeros, dur in ms; "?<value>" when it is not a value of the type.
norm_val() {
    local v
    case "$1" in
        bool) v="$(printf '%s' "$2" | tr 'A-Z' 'a-z')"; case "${v}" in true|false) echo "${v}" ;; *) echo "?$2" ;; esac ;;
        int) case "$2" in ''|*[!0-9]*) echo "?$2" ;; *) v="$(printf '%s' "$2" | sed 's/^0*//')"; echo "${v:-0}" ;; esac ;;
        dur) v="$(to_ms "$2")"; echo "${v:-?$2}" ;;
        *) echo "$2" ;;
    esac
}

# yaml_get <file> <key> — a top-level key of a parameters YAML: "scalar<TAB><value as written,
# comment and quotes stripped>", "block<TAB><ms of its secs/nanos, or empty>" (the serde form), or
# "absent". The parsing rules of bench-lib.sh bench_params_ms / bench_params_raw.
yaml_get() {
    awk -v k="$2" -v q="'" '
        blk {
            if ($0 ~ /^[ \t]*(#.*)?$/) next
            if ($0 ~ /^[ \t]/) {
                l = $0; sub(/^[ \t]+/, "", l); sub(/[ \t]*#.*$/, "", l); sub(/[ \t]+$/, "", l)
                if (l ~ /^secs:[ \t]*[0-9]+$/) { sub(/^secs:[ \t]*/, "", l); s = l }
                else if (l ~ /^nanos:[ \t]*[0-9]+$/) { sub(/^nanos:[ \t]*/, "", l); n = l }
                next
            }
            exit
        }
        index($0, k ":") == 1 {
            v = substr($0, length(k) + 2)
            sub(/^[ \t]+/, "", v); sub(/(^|[ \t]+)#.*$/, "", v); sub(/[ \t]+$/, "", v)
            if (length(v) >= 2 && ((v ~ /^".*"$/) || (substr(v, 1, 1) == q && substr(v, length(v), 1) == q))) v = substr(v, 2, length(v) - 2)
            if (v == "") { blk = 1; next }
            printf "scalar\t%s\n", v; got = 1; exit
        }
        END {
            if (got) exit
            if (!blk) { print "absent"; exit }
            if (s != "" || n != "") printf "block\t%d\n", s * 1000 + int(n / 1000000); else print "block\t"
        }' "$1"
}

# --- what to set -----------------------------------------------------------------------
# ${WORK}/sets/all and ${WORK}/sets/node.<name>: "key=value" lines, one per key.
: > "${WORK}/sets/all"
for n in "${N_NAME[@]}"; do : > "${WORK}/sets/node.${n}"; done
for spec in ${SETS[@]+"${SETS[@]}"}; do
    target="${spec%%:*}" kvs="${spec#*:}"
    [ "${target}" != "${spec}" ] && [ -n "${kvs}" ] || die "--set '${spec}': want <all|node>:<key>=<value>[,<key>=<value>...]"
    if [ "${target}" = all ]; then
        f="${WORK}/sets/all"
    else
        idx_of "${target}" >/dev/null || die "--set '${spec}': ${target} is not in the node list$([ "${VALIDATORS_ONLY}" = 0 ] || echo ' (--validators-only leaves observers out)')"
        f="${WORK}/sets/node.${target}"
    fi
    kvs="${kvs},"
    while [ -n "${kvs}" ]; do
        kv="${kvs%%,*}" kvs="${kvs#*,}"
        case "${kv}" in *=?*) ;; *) die "--set '${spec}': '${kv}' is not <key>=<value>" ;; esac
        k="${kv%%=*}" v="${kv#*=}"
        case "${k}" in
            gc_depth|basefee_address) die "--set '${spec}': ${k} must stay fleet-wide (consensus-critical); never per node" ;;
            batch_vote_timeout|parallel_fetch_request_delay_interval)
                die "--set '${spec}': ${k} is a secs/nanos block in parameters.yaml; this tool sets scalar keys only" ;;
        esac
        t="$(key_type "${k}")"
        if j="$(sw_idx "${k}")"; then
            # A switch: one of its arm values, or its default (which turns it off again).
            sw_arm_value "${j}" "${v}" || [ "${v}" = "${SW_D[$j]}" ] \
                || die "--set '${spec}': ${k}=${v} is not one of its values (${SW_V[$j]}, or the default ${SW_D[$j]}; benchmark/arms/switches.tsv)"
        else
            case "${t}:${v}" in
                :*) die "--set '${spec}': unknown key '${k}' (known: $(printf '%s ' ${ALL_KEYS} | sed 's/[a-z]*://g'))" ;;
                dur:*) [[ "${v}" =~ ${DUR_RE} ]] || die "--set '${spec}': ${k}=${v} is not <int>ms or <int>s" ;;
                int:*) case "${v}" in *[!0-9]*|0*) die "--set '${spec}': ${k}=${v} is not a positive integer" ;; esac ;;
                bool:true|bool:false) ;;
                bool:*) die "--set '${spec}': ${k}=${v} is not true or false" ;;
            esac
        fi
        ! grep -q "^${k}=" "${f}" || die "--set: ${k} is given twice for ${target}"
        printf '%s=%s\n' "${k}" "${v}" >> "${f}"
    done
done

# ${WORK}/sets/merged.<node>: the node's "key=value" lines in ALL_KEYS order; its own --set wins
# over all:. With an arm file: the arm's full switch state, the same on every node. node_sets
# <node> prints them. ${WORK}/targets.<node>: its switch lines, what the readback compares.
for n in "${N_NAME[@]}"; do
    if [ -n "${ARM_FILE}" ]; then
        cp "${WORK}/arm.target" "${WORK}/sets/merged.${n}"
    else
        awk -v keys="${ALL_KEYS}" -v all="${WORK}/sets/all" '
            { v = substr($0, index($0, "=") + 1); k = substr($0, 1, index($0, "=") - 1)
              if (FILENAME == all) a[k] = v; else o[k] = v }
            END { n = split(keys, ks, " ")
                  for (i = 1; i <= n; i++) { k = ks[i]; sub(/^[a-z]*:/, "", k)
                      if (k in o) print k "=" o[k]; else if (k in a) print k "=" a[k] } }' \
            "${WORK}/sets/all" "${WORK}/sets/node.${n}" > "${WORK}/sets/merged.${n}"
    fi
    : > "${WORK}/targets.${n}"
    while IFS= read -r kv; do
        ! sw_idx "${kv%%=*}" >/dev/null || printf '%s\n' "${kv}" >> "${WORK}/targets.${n}"
    done < "${WORK}/sets/merged.${n}"
done
node_sets() { cat "${WORK}/sets/merged.$1"; }

# res_build <node> [<current yaml> [nosets]] — ${WORK}/res.<node>: "key<TAB>raw<TAB>ms" for every
# timing key the node will have: the current file's (raw "(block)" for a secs/nanos block)
# overlaid with its sets (not with nosets: a stage test writes the current values back).
res_build() {
    local n="$1" yaml="${2:-}" tk k t got form raw kv=""
    : > "${WORK}/res.${n}"
    for tk in ${PARAM_KEYS}; do
        k="${tk#*:}" t="${tk%%:*}" raw=""
        [ "${3:-}" = nosets ] || kv="$(sed -n "s/^${k}=//p" "${WORK}/sets/merged.${n}")"
        if [ -n "${kv}" ]; then
            raw="${kv}"
        elif [ -n "${yaml}" ]; then
            got="$(yaml_get "${yaml}" "${k}")"; form="${got%%"${TAB}"*}"
            case "${form}" in
                scalar) raw="${got#*"${TAB}"}" ;;
                block) printf '%s\t(block)\t%s\n' "${k}" "${got#*"${TAB}"}" >> "${WORK}/res.${n}"; continue ;;
            esac
        fi
        [ -n "${raw}" ] || continue
        if [ "${t}" = dur ]; then
            printf '%s\t%s\t%s\n' "${k}" "${raw}" "$(to_ms "${raw}")" >> "${WORK}/res.${n}"
        else
            printf '%s\t%s\t\n' "${k}" "${raw}" >> "${WORK}/res.${n}"
        fi
    done
}
res_raw() { awk -F'\t' -v k="$2" '$1 == k { print $2; exit }' "${WORK}/res.$1"; }
res_ms() { awk -F'\t' -v k="$2" '$1 == k { print $3; exit }' "${WORK}/res.$1"; }

# res_problems <node> <full> — the startup rules the node enforces (crates/config/src/node.rs
# validate_operational_floors, consensus.rs validate_vote_timeout at ba43a1f0e; the checks of
# bench-lib.sh bench_node_params_problems): min_header_delay <= max_header_delay;
# 1 <= header_num_of_batches_threshold <= max_header_num_of_batches; vote_timeout >=
# max_header_delay + 250 ms and < 10 s. <full> = 1: the values are complete (an absent vote_timeout
# is the node's default, 5 s); 0: only what --set gives is known.
res_problems() {
    local n="$1" full="$2" mx mn vt thr cap
    mx="$(res_ms "${n}" max_header_delay)"; mn="$(res_ms "${n}" min_header_delay)"
    vt="$(res_ms "${n}" vote_timeout)"
    [ "${full}" = 0 ] || [ -n "${vt}" ] || [ -n "$(res_raw "${n}" vote_timeout)" ] || vt=5000
    thr="$(res_raw "${n}" header_num_of_batches_threshold)"; cap="$(res_raw "${n}" max_header_num_of_batches)"
    if [ -n "${mx}" ] && [ -n "${mn}" ] && [ "${mn}" -gt "${mx}" ]; then
        echo "${n}: min_header_delay ${mn} ms > max_header_delay ${mx} ms"
    fi
    if [ -n "${mx}" ] && [ -n "${vt}" ] && [ "${vt}" -lt $((mx + 250)) ]; then
        echo "${n}: vote_timeout ${vt} ms < max_header_delay ${mx} ms + 250 ms drift tolerance"
    fi
    if [ -n "${vt}" ] && [ "${vt}" -ge 10000 ]; then
        echo "${n}: vote_timeout ${vt} ms is not below the 10 s libp2p request timeout"
    fi
    case "${thr}:${cap}" in
        *[!0-9:]*|:*|*:) ;;
        *) if [ "${thr}" -lt 1 ] || [ "${thr}" -gt "${cap}" ]; then
               echo "${n}: header_num_of_batches_threshold ${thr} is outside 1..max_header_num_of_batches ${cap}"
           fi ;;
    esac
}

# Static check: what --set alone says, before any node is contacted.
problems=""
for n in "${N_NAME[@]}"; do
    res_build "${n}"
    problems="${problems}$(res_problems "${n}" 0)"$'\n'
done
problems="$(printf '%s' "${problems}" | grep -v '^$' || true)"
[ -z "${problems}" ] || fatal "refused before contacting any node; a node would refuse to start with:"$'\n'"$(printf '%s\n' "${problems}" | sed 's/^/  /')"

if [ "${MODE}" = stage ]; then
    STAGE_IDX="$(idx_of "${STAGE}")" || die "--stage-test ${STAGE}: not in the node list"
fi

# --- the switches line (`node switches`, message text, target node::switches) ----------------
# sw_line_values <line> — the key=value tokens after the message text, one "key=value" per line.
sw_line_values() {
    printf '%s\n' "$1" | awk '{
        i = index($0, "node switches"); if (!i) exit
        rest = substr($0, i + length("node switches")); sub(/^"/, "", rest)
        n = split(rest, tok, /[ \t]+/)
        for (j = 1; j <= n; j++) {
            if (tok[j] !~ /^[a-z][a-z0-9_]*=/) continue
            k = substr(tok[j], 1, index(tok[j], "=") - 1); v = substr(tok[j], index(tok[j], "=") + 1)
            gsub(/^"|"$/, "", v)
            print k "=" v
        }
        exit
    }'
}
# sw_line_ts <line> — the line's own time to the second as YYYY-MM-DDTHH:MM:SSZ (logfmt ts=, or a
# JSON "timestamp"), "" when it carries none.
sw_line_ts() {
    printf '%s\n' "$1" | awk '{
        if (match($0, /(^|[ ,{])(ts=|"timestamp":")[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/))
            print substr($0, RSTART + RLENGTH - 19, 19) "Z"
        exit
    }'
}
# switch_compare <node> <line> — the node's switch targets against the line, one line per
# disagreement: "differs <key> <line value> <target>" or "absent <key> - <target>". A key the line
# does not print is absent unless the switch is optional and the target is its default.
switch_compare() {
    local n="$1" vals kv k t j got
    vals="$(sw_line_values "$2")"
    while IFS= read -r kv; do
        [ -n "${kv}" ] || continue
        k="${kv%%=*}" t="${kv#*=}"
        j="$(sw_idx "${k}")" || continue
        if has_line "${vals}" "${k}="; then
            got="$(printf '%s\n' "${vals}" | sed -n "s/^${k}=//p" | tail -n 1)"
            [ "$(norm_val "${SW_T[$j]}" "${got}")" = "$(norm_val "${SW_T[$j]}" "${t}")" ] || echo "differs ${k} ${got} ${t}"
        elif [ "${SW_O[$j]}" = yes ] && [ "$(norm_val "${SW_T[$j]}" "${t}")" = "$(norm_val "${SW_T[$j]}" "${SW_D[$j]}")" ]; then
            :
        else
            echo "absent ${k} - ${t}"
        fi
    done < "${WORK}/targets.${n}"
}
# switch_readback <node> <line> <stop time> — rc 0 when <line> is from the start after <stop time>
# and every target of the node reads back; else rc 1 and the reason on stdout.
switch_readback() {
    local n="$1" line="$2" stop="$3" ts cmp
    if [ -z "${line}" ] || [ "${line}" = - ]; then
        echo "no 'node switches' line since the restart (an image that does not log it, or a start that did not get that far)"
        return 1
    fi
    ts="$(sw_line_ts "${line}")"
    if [ -n "${ts}" ] && [ -n "${stop}" ] && [[ "${ts}" < "${stop}" ]]; then
        echo "stale: the newest 'node switches' line (${ts}) is older than this restart (${stop})"
        return 1
    fi
    cmp="$(switch_compare "${n}" "${line}")"
    [ -n "${cmp}" ] || return 0
    printf '%s\n' "${cmp}" | awk '
        $1 == "differs" { printf "%s%s=%s (expected %s)", (c++ ? ", " : ""), $2, $3, $4 }
        $1 == "absent" { printf "%s%s is not on the line (the image does not know it; expected %s)", (c++ ? ", " : ""), $2, $4 }
        END { print "" }'
    return 1
}
# switch_values <line> — the line's switches in switches.tsv order, "k=v k=v ...".
switch_values() {
    local vals i out=""
    vals="$(sw_line_values "$1")"
    for i in "${!SW_K[@]}"; do
        if has_line "${vals}" "${SW_K[$i]}="; then
            out="${out} ${SW_K[$i]}=$(printf '%s\n' "${vals}" | sed -n "s/^${SW_K[$i]}=//p" | tail -n 1)"
        fi
    done
    printf '%s\n' "${out# }"
}

# --- the record (manifest.param_arms, else param-arms.json beside the nodes file) -------
if [ -n "${RESULTS_DIR}" ] && [ -f "${RESULTS_DIR}/manifest.json" ]; then
    REC_FILE="${RESULTS_DIR}/manifest.json"
else
    REC_FILE="$(cd "$(dirname "${NODES_FILE}")" && pwd)/param-arms.json"
fi

# rec_jq <jq args...> <filter> — edit the record in place (temp file + rename; created as
# {"param_arms": []} when it is the param-arms.json and does not exist yet). A dry run never writes.
rec_jq() {
    local tmp
    [ "${DRY}" = 0 ] || return 0
    [ -f "${REC_FILE}" ] || printf '{"param_arms": []}\n' > "${REC_FILE}"
    tmp="$(mktemp "${REC_FILE}.XXXXXX")"
    if jq "$@" "${REC_FILE}" > "${tmp}"; then mv "${tmp}" "${REC_FILE}"; else rm -f "${tmp}"; return 1; fi
}
# rec_count <name> <jq filter over .param_arms> — e.g. how many arms are named <name>; 0 without a record.
rec_count() {
    [ -f "${REC_FILE}" ] || { echo 0; return 0; }
    jq -r --arg a "$1" "[(.param_arms // [])[] | $2] | length" "${REC_FILE}"
}
# kv_json — "key=value" lines on stdin as {"key": "value"}, in their order.
kv_json() { jq -R -s -c 'split("\n") | map(select(length > 0) | capture("^(?<k>[^=]+)=(?<v>.*)$") | {(.k): .v}) | add // {}'; }
# vals_json <node> — its --set values as written, {"<key>": "<value>"}.
vals_json() { node_sets "$1" | kv_json; }
# written_json <node> — the keys phase B rewrote on it, {"<key>": "<value>"}.
written_json() { sed -n 's/^setp \([^ ]*\) \(.*\)$/\1=\2/p' "${WORK}/w.$1" | kv_json; }
# node_vals_json <node> — what `nodes` records for it: its --set values (an arm given with --set),
# the keys rewritten (an arm file).
node_vals_json() { if [ -n "${ARM_FILE}" ]; then written_json "$1"; else vals_json "$1"; fi; }

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

case "${MODE}" in
    close-arm|mark|end-mark)
        now="$(now_utc)"
        if [ "${DRY}" = 1 ]; then
            log "dry run: would ${MODE} ${CLOSE}${MARK}${END_MARK} at ${now} in ${REC_FILE}"
            exit 0
        fi
        ;;
esac
case "${MODE}" in
    close-arm)
        [ "$(rec_count "${CLOSE}" 'select(.name == $a and .end == null)')" -ge 1 ] \
            || fatal "no open arm named '${CLOSE}' in ${REC_FILE}"
        rec_jq --arg a "${CLOSE}" --arg t "${now}" '.param_arms |= map(if .name == $a and .end == null then
            (.end = $t | if (.marks | type) == "array" then .marks |= map(if .end == null then .end = $t else . end) else . end)
            else . end)'
        log "arm ${CLOSE} closed at ${now} (${REC_FILE})"
        exit 0 ;;
    mark)
        [ "$(rec_count "" 'select(.end == null)')" -ge 1 ] || fatal "no open arm in ${REC_FILE} to mark"
        [ "$(rec_count "${MARK}" 'select(.end == null) | (.marks // [])[] | select(.label == $a)')" = 0 ] \
            || fatal "the open arm already has a mark '${MARK}'; give it another label"
        rec_jq --arg l "${MARK}" --arg t "${now}" '.param_arms |= map(if .end == null then
            .marks = (((.marks // []) | map(if .end == null then .end = $t else . end)) + [{label: $l, begin: $t, end: null}])
            else . end)'
        log "mark ${MARK} opened at ${now} on the open arm $(jq -r '[(.param_arms // [])[] | select(.end == null) | .name] | join(",")' "${REC_FILE}") (${REC_FILE})"
        exit 0 ;;
    end-mark)
        [ "$(rec_count "${END_MARK}" 'select(.end == null) | (.marks // [])[] | select(.label == $a and .end == null)')" -ge 1 ] \
            || fatal "no open mark '${END_MARK}' on the open arm in ${REC_FILE}"
        rec_jq --arg l "${END_MARK}" --arg t "${now}" '.param_arms |= map(if .end == null then
            .marks |= map(if .label == $l and .end == null then .end = $t else . end) else . end)'
        log "mark ${END_MARK} ended at ${now} (${REC_FILE})"
        exit 0 ;;
esac
if [ "${MODE}" = apply ] && [ "${DRY}" = 0 ] && [ "$(rec_count "${ARM}" 'select(.name == $a)')" -gt 0 ]; then
    fatal "arm '${ARM}' is already recorded in ${REC_FILE}; give this arm a new name (--arm <name>)"
fi

# ===== HOOK: host steps (benchmark/arms/README.md "Host steps"; filled by unit H5b) ===============
# host_steps_hook <node-index> — prints the shell text that defines host_steps(), the function the
# arm's systemd-run unit (unit_script_text) calls on that node after `systemctl stop telcoin`
# returned 0 and before `systemctl start telcoin`.
#   Here: ARM_HOST_STEPS holds the arm's steps in run order, one per line ("read-ahead-kb <n>",
#   then "evict-mdbx"; empty: none); N_*[<node-index>] the node.
#   In the unit (bash, root, telcoin stopped, no `set -e`): $D the node's host datadir (db/mdbx.dat
#   is under it), $NODE, $UNIT. host_steps prints, per step it ran, one line
#       HOST_RESULT <step> <value, or - for none> <result object as one-line JSON>
#   with the per-node result of benchmark/arms/MANIFEST-FIELDS.md ({"resident_pages_before": n,
#   "resident_pages_after": n}, {"read_ahead_kb_before": n, "read_ahead_kb_after": n}, or
#   {"failed": "<reason>"}), and returns non-zero when a step failed. The unit then starts telcoin
#   anyway; the tool stops the arm at that node (PA_FAIL, `failed`) and records the results in the
#   entry's `host`.
#   rc 1 with the reason on stderr: the arm's host steps cannot run, and the tool refuses the arm
#   before contacting any node (a dry run prints its plan first).
# Restarts: the planner restarts every node of an arm that lists any host step (evict-mdbx always
# needs it; a read-ahead the node already has would not, which needs phase A to read it).
# Until H5b fills it, no host step can run: an arm that lists one is refused.
host_steps_hook() {
    if [ -n "${ARM_HOST_STEPS}" ]; then
        echo "host steps not available: this params-apply.sh cannot run ${ARM_HOST_DESC} yet (benchmark/arms/README.md, Host steps); arm ${ARM} is refused" >&2
        return 1
    fi
    echo 'host_steps() { return 0; }'
}
# ===== end of HOOK ===============================================================================

# unit_script_text <node-index> — the script the transient unit runs on the node: stop telcoin,
# the host steps, start telcoin. No `set -e`: telcoin is started whatever came before.
unit_script_text() {
    cat <<'UNIT'
#!/bin/bash
# A bench arm unit (benchmark/tools/params-apply.sh): stop telcoin, run the arm's host steps, start
# telcoin, in one transient systemd service, so that the node is started again whatever happens to
# the session that launched it. $1 = the output file (appended), $2 = the node's host datadir,
# $3 = the node, $4 = this unit.
OUT="$1" D="$2" NODE="$3" UNIT="$4"
exec >>"$OUT" 2>&1
UNIT
    cat "${WORK}/hook.${N_NAME[$1]}"
    cat <<'UNIT'
echo "STOP_AT $(date -u +%Y-%m-%dT%H:%M:%SZ) $(date +%s)"
s=0
systemctl stop telcoin || s=$?
echo "STOP_RC $s"
h=0
if [ "$s" = 0 ]; then host_steps || h=$?; else echo "HOST_SKIPPED the stop failed"; fi
echo "HOOK_RC $h"
echo "START_AT $(date -u +%Y-%m-%dT%H:%M:%SZ) $(date +%s)"
r=0
systemctl start telcoin || r=$?
echo "START_RC $r"
UNIT
}

# The hook's text and the unit script, per node, before any node is contacted: a live run refuses
# an arm whose host steps cannot run, a dry run says so after its plan.
HOOK_ERR=""
for i in "${!N_NAME[@]}"; do
    n="${N_NAME[$i]}"
    if ! host_steps_hook "${i}" > "${WORK}/hook.${n}" 2> "${WORK}/hook.err"; then
        HOOK_ERR="$(cat "${WORK}/hook.err")"
        HOOK_ERR="${HOOK_ERR:-the host-steps hook failed}"
        break
    fi
    unit_script_text "${i}" > "${WORK}/unit.${n}.sh"
    ! grep -qx 'PA_UNIT_SCRIPT' "${WORK}/unit.${n}.sh" || die "the unit script for ${n} holds the line PA_UNIT_SCRIPT"
    bash -n "${WORK}/unit.${n}.sh" 2> "${WORK}/hook.err" || die "the unit script for ${n} does not parse: $(cat "${WORK}/hook.err")"
done
if [ -n "${HOOK_ERR}" ] && [ "${DRY}" = 0 ]; then die "${HOOK_ERR}"; fi

# --- gcloud (helpers copied from tools/latency-probe.sh: show_argv, ssh_once, iap_ssh, pool;
#     the IAP retry rule is bench-lib.sh bench_iap_scp_down's) --------------------------------
# show_argv <argv...> — one copy-pasteable line, on stderr so a caller's stdout redirect cannot hide it.
show_argv() { { printf '  +'; printf ' %q' "$@"; printf '\n'; } >&2; }

SSH_FLAGS=(--tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=20"
           --ssh-flag="-o StrictHostKeyChecking=accept-new" --ssh-flag="-o LogLevel=ERROR")

# ssh_once <secs> <node-index> <stdin-file> <err-file> — one IAP SSH call running the stdin script
# as root, under an alarm. A dry run prints the argv and returns before the live call.
ssh_once() {
    local secs="$1" i="$2" input="$3" err="$4"
    if [ "${DRY}" = 1 ]; then
        printf '  [alarm %ss, stdin < %s]' "${secs}" "${input##*/}" >&2
        show_argv gcloud compute ssh "${N_NAME[$i]}" --zone="${N_ZONE[$i]}" --project="${N_PROJ[$i]}" \
            "${SSH_FLAGS[@]}" --command="sudo bash -s"
        return 0
    fi
    [ "${DRY}" = 0 ] || return 0
    perl -e 'alarm shift; exec @ARGV' "${secs}" gcloud compute ssh "${N_NAME[$i]}" --zone="${N_ZONE[$i]}" \
        --project="${N_PROJ[$i]}" "${SSH_FLAGS[@]}" --command="sudo bash -s" <"${input}" 2>"${err}"
}

# iap_ssh <same args as ssh_once> — plus one retry when IAP refuses the tunnel (4003/4033/4047:
# refused before the remote command starts, so a retry never runs a script twice).
iap_ssh() {
    local rc=0
    ssh_once "$@" || rc=$?
    if [ "${rc}" -ne 0 ] && grep -Eq '\[(4003|4033|4047): ' "$4" 2>/dev/null; then
        log "  ${N_NAME[$2]}: IAP refused the tunnel; retrying once in ${RETRY_SECS} s" >&2
        sleep "${RETRY_SECS}"
        rc=0
        ssh_once "$@" || rc=$?
    fi
    return "${rc}"
}

# pool <max> <function> <items...> — run <function> <item> in the background, at most <max> at
# once. Jobs report through files in ${WORK}; a dry run goes one at a time so its output stays
# readable. Every job runs under an alarm, so a free slot comes; the wait still has a deadline.
pool() {
    local max="$1" fn="$2" item waited
    shift 2
    [ "${DRY}" = 0 ] || max=1
    for item in "$@"; do
        waited=0
        while [ "$(jobs -pr | wc -l)" -ge "${max}" ]; do
            [ "${waited}" -lt $(( 2 * (PHASE_A_SECS + RETRY_SECS) + 60 )) ] \
                || fatal "gave up after ${waited} s waiting for a free ssh slot (the jobs run under a ${PHASE_A_SECS} s alarm)"
            sleep 1
            waited=$((waited + 1))
        done
        if [ "${DRY}" = 1 ]; then "${fn}" "${item}"; else "${fn}" "${item}" & fi
    done
    wait
}

# last_error <file> — the last few non-empty lines of a log, on one line.
last_error() { { grep -v '^[[:space:]]*$' "$1" 2>/dev/null || true; } | tail -n 3 | tr '\n' ' ' | cut -c1-500; }

# --- remote scripts (stdin of `sudo bash -s` on the node) --------------------------------
# remote_head <phase> <node-index> — the script's first lines: which node, its datadir override.
remote_head() {
    printf '# params-apply phase %s on %s\n' "$1" "${N_NAME[$2]}"
    printf 'set -euo pipefail\nNODE=%q\nHD=%q\nROLE=%q\nSTART=%q\nLEGACY=%q\nMETA=%q\nLOGDIR=%q\nSD=%q\n' \
        "${N_NAME[$2]}" "${N_HD[$2]}" "${N_ROLE[$2]}" "${REMOTE_START}" "${REMOTE_LEGACY_WRAPPER}" \
        "${REMOTE_NODE_META}" "${REMOTE_LOG_DIR}" "${NODE_SCRIPTS_DIR}"
}

# remote_common — both phases: P (the parameters file) and small helpers. The datadir, first
# found wins: the nodes file's hostdatadir; DATA_DIR in .node-meta (v2 writes it root 0600 as
# KEY=VALUE; the value is everything after the first '=', CR dropped, as the v2 library reads it;
# a key set twice has no single value and is refused, as there; deploy step 7's pre-start config,
# bench-lib.sh bench_prestart_script, reads the datadir only from there); the launch file's bind
# (the rule pre-v2 deploys used): its telcoin command has --datadir <container path>, the host side
# of its `-v <host>:<that path>` holds the file (no bind: a native install, the path itself). The
# launch file is v2's start script, else the legacy wrapper. A
# hostdatadir that disagrees with .node-meta is refused (the nodes file is then wrong).
remote_common() {
    cat <<'REMOTE'
TAG="${TAG:-PARAMS_FAIL}"
fail() { echo "${TAG} ${NODE} $*"; exit 1; }
note() { echo "PA_NOTE ${NODE} $*"; }
L=""
if [ -f "$START" ]; then L="$START"; elif [ -f "$LEGACY" ]; then L="$LEGACY"; fi
MD=""
if [ -f "$META" ]; then
    MC="$(grep -c '^DATA_DIR=' "$META" || true)"
    [ "$MC" -le 1 ] || fail "DATA_DIR is set $MC times in $META (no single value); remove the extra lines first"
    if [ "$MC" = 1 ]; then
        MD="$(sed -n 's/^DATA_DIR=//p' "$META" | tr -d '\r')"
        case "$MD" in
            /*[!A-Za-z0-9._/+-]*|*..*) fail "DATA_DIR '$MD' in $META has unusual characters" ;;
            /?*) MD="${MD%/}" ;;
            *) fail "DATA_DIR '$MD' in $META is not an absolute path" ;;
        esac
    fi
fi
if [ -n "$HD" ]; then
    [ -z "$MD" ] || [ "$MD" = "${HD%/}" ] || fail "the nodes file's hostdatadir $HD is not DATA_DIR $MD of $META"
    D="$HD" SRC="the nodes file"
elif [ -n "$MD" ]; then
    D="$MD" SRC="$META"
else
    [ -n "$L" ] || fail "no $START or $LEGACY (start script), no DATA_DIR in $META and no hostdatadir in the nodes file"
    C="$(grep -v '^[[:space:]]*#' "$L" | sed -nE 's/.*--datadir[ =]([^[:space:]]+).*/\1/p' | head -1 || true)"
    [ -n "$C" ] || fail "no --datadir in $L"
    H="$(grep -v '^[[:space:]]*#' "$L" | sed -nE "s#.*-v[[:space:]]+([^[:space:]:]+):${C}([:[:space:]].*)?\$#\1#p" | head -1 || true)"
    D="${H:-$C}" SRC="the bind mount in $L"
    [ -n "$H" ] || SRC="--datadir in $L (no bind: a native install)"
fi
P="$D/parameters.yaml"
echo "PA_LAUNCH ${L:-none}"
echo "PA_DATADIR $D (from ${SRC})"
[ -f "$P" ] || fail "no $P (datadir from ${SRC})"
sha256() { { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; } | awk '{ print $1 }'; }
# rpc <method> — the node's JSON-RPC result ("" while it does not answer)
rpc() { { curl -s --max-time 3 -H 'content-type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":[]}" http://127.0.0.1:8545 || true; } | sed -n 's/.*"result":"\([^"]*\)".*/\1/p' || true; }
REMOTE
}

# phase_a_script <node-index> — read-only: the file, its sha256, container state, chain id, the
# running container's `node switches` line, the v2 library and systemd-run.
phase_a_script() {
    remote_head A "$1"
    echo 'TAG=PA_FAIL'
    remote_common
    cat <<'REMOTE'
echo "PA_PARAMS $P"
echo "PA_SHA $(sha256 "$P")"
r=0
if [ "$(docker inspect -f '{{.State.Running}}' telcoin 2>/dev/null || true)" = true ]; then r=1; fi
echo "PA_RUNNING $r"
c="$(rpc eth_chainId)"
echo "PA_CHAIN ${c:--}"
echo "PA_MARKERS $(grep -c '# bench-override$' "$P" || true)"
if [ -f "$P.bak" ]; then echo "PA_BAK 1"; else echo "PA_BAK 0"; fi
# The switches the running container logged at its start: the first `node switches` line since
# its StartedAt (grep stops the read there; the line comes early in a start).
sw=""
if [ "$r" = 1 ]; then
    st="$(docker inspect -f '{{.State.StartedAt}}' telcoin 2>/dev/null || true)"
    if [ -n "$st" ]; then sw="$(docker logs --since "$st" telcoin 2>&1 | grep -m 1 -F 'node switches' || true)"; fi
fi
echo "PA_SWITCH_LINE ${sw:--}"
if [ -r "$SD/lib/common.sh" ]; then echo "PA_LIB 1"; else echo "PA_LIB 0"; fi
if command -v systemd-run >/dev/null 2>&1; then echo "PA_SYSTEMD_RUN 1"; else echo "PA_SYSTEMD_RUN 0"; fi
echo "PA_YAML_BEGIN"
awk 1 "$P"
echo "PA_YAML_END"
echo "PA_OK ${NODE}"
REMOTE
}

# phase_b_script <node-index> <label> <expected sha256|-> <expected chain id|-> <setp-lines-file>
phase_b_script() {
    remote_head B "$1"
    printf 'LABEL=%q\nEXPECT_SHA=%q\nEXPECT_CHAIN=%q\nWAIT=%q\nUNIT_PREFIX=%q\n' "$2" "$3" "$4" "${HEALTH_SECS}" "bench-arm-${2#pre-arm-}"
    printf 'GT=%q\nGS=%q\nGD=%q\nEM=%q\nEW=%q\nUW=%q\nGUARD_RPC=%q\n' "${GUARD_TRIES}" "${GUARD_SECS}" \
        "${GUARD_DEFER_SECS}" "${EPOCH_MARGIN_SECS}" "${EPOCH_WAIT_SECS}" "${UNIT_SECS}" "${GUARD_RPC}"
    remote_common
    cat <<'REMOTE'
sha="$(sha256 "$P")"
[ "$EXPECT_SHA" = - ] || [ "$sha" = "$EXPECT_SHA" ] || fail "$P changed since the read-only pass (sha256 $sha, read $EXPECT_SHA); nothing done, re-run"
if grep -q '# bench-override$' "$P" && [ ! -f "$P.bak" ]; then fail "$P has bench-override lines but no $P.bak"; fi
[ -r "$SD/lib/common.sh" ] || fail "no $SD/lib/common.sh (the v2 scripts' library): no committee guard; nothing done"
command -v systemd-run >/dev/null 2>&1 || fail "no systemd-run on the node; nothing done"
# tnlib <fn> <args...> — one v2 library function in a subshell (bench-lib.sh
# bench_remote_lib_preamble): DEVNET_RPC_URL, which lib/common.sh reads once as the guard's public
# fallback, is GUARD_RPC, never the real devnet's RPC.
tnlib() { ( export DEVNET_RPC_URL="$GUARD_RPC"; . "$SD/lib/common.sh"; "$@" ); }
unset TN_ALLOW_QUORUM_RISK

# Where consensus is, from a log on stdin: vmark = the highest (epoch, round) of this node's own
# 'quorum reached' / 'header proposed' lines (validators); cmark = the highest consensus number
# (consensus_number=, 'got new consensus N/', last_consensus_height=), as "0 N" (observers).
vmark() {
    awk '/quorum reached|header proposed/ {
        e = 0; r = -1
        if (match($0, /(^|[ ,{"])round"?[=:] ?"?[0-9]+/)) { s = substr($0, RSTART, RLENGTH); gsub(/[^0-9]/, "", s); r = s + 0 }
        if (match($0, /(^|[ ,{"])epoch"?[=:] ?"?[0-9]+/)) { s = substr($0, RSTART, RLENGTH); gsub(/[^0-9]/, "", s); e = s + 0 }
        if (r >= 0 && (!seen || e > me || (e == me && r > mr))) { me = e; mr = r; seen = 1 }
    } END { if (seen) printf "%d %d\n", me, mr }'
}
cmark() {
    awk '{
        if (match($0, /consensus_number"?[=:] ?"?[0-9]+/) || match($0, /got new consensus [0-9]+/) || match($0, /last_consensus_height"?[=:] ?"?[0-9]+/)) {
            s = substr($0, RSTART, RLENGTH); gsub(/[^0-9]/, "", s)
            if (!seen || s + 0 > m) { m = s + 0; seen = 1 }
        }
    } END { if (seen) printf "0 %d\n", m }'
}
mark() { if [ "$ROLE" = validator ]; then vmark; else cmark; fi; }
# later "<e> <n>" "<e0> <n0>" — 0 when the first is past the second (or there is no second)
later() {
    [ -n "$2" ] || return 0
    set -- $1 $2
    [ "$1" -gt "$3" ] || { [ "$1" -eq "$3" ] && [ "$2" -gt "$4" ]; }
}

# 1. The committee guard: v2's tn_committee_down_guard against this node's own RPC, up to GT
#    samples GS s apart. It reads one commit's authors, and a member that is up can miss one, so a
#    refusal is a sample, not a verdict; a pass that came with a warning (it could not count the
#    committee) is a refusal here. GT refusals in a row are a deferral: GD s, then GT more; a
#    second deferral stops the run. An observer passes at once.
GSAMPLES=0 GREFUSED=0 nl=$'\n'
pa_gs() { printf '%s: %s\n' "$1" "$2"; return 0; }
guard_round() {
    local t=1 g out
    while :; do
        g=0
        out="$(tnlib tn_committee_down_guard "" pa_gs 2>&1)" || g=$?
        GSAMPLES=$((GSAMPLES + 1))
        if [ "$g" = 0 ]; then case "${nl}${out}" in *"${nl}warn: "*) g=blind ;; esac; fi
        echo "PA_GUARD ${NODE} sample=${t}/${GT} rc=${g} $(printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | tail -n 1 | cut -c1-300)"
        [ "$g" != 0 ] || return 0
        GREFUSED=$((GREFUSED + 1))
        [ "$t" -lt "$GT" ] || return 1
        sleep "$GS"
        t=$((t + 1))
    done
}
guard() {
    guard_round && return 0
    echo "PA_GUARD_DEFER ${NODE} all ${GT} samples refused; again in ${GD} s"
    sleep "$GD"
    guard_round && return 0
    echo "PA_GUARD_SUMMARY ${NODE} samples=${GSAMPLES} refused=${GREFUSED}"
    fail "the committee guard refused ${GT} samples in a row twice (${GREFUSED} of ${GSAMPLES} refused); the node was not restarted"
}
guard

# 2. the container's log: a restart drops it (docker run --rm). Same file scheme as bench-lib.sh
#    bench_save_node_log, so the harness pull collects it. No container: nothing to save.
pre=""
if docker container inspect telcoin >/dev/null 2>&1; then
    n="telcoin-${LABEL}-$(date -u +%Y%m%dT%H%M%SZ).log.gz"; f="$LOGDIR/$n"
    mkdir -p "$LOGDIR" || fail "cannot create $LOGDIR"
    [ ! -e "$f" ] || fail "$f exists already"
    p="$(mktemp "$LOGDIR/.$n.XXXXXX")" || fail "cannot create a temp file in $LOGDIR"
    docker logs telcoin 2>&1 | gzip -1 > "$p" || fail "docker logs telcoin | gzip failed"
    [ "$(gzip -cd "$p" | head -c 1 | wc -c)" -eq 1 ] || fail "the telcoin container log is empty"
    { mv -n "$p" "$f" && [ ! -e "$p" ] && [ -s "$f" ]; } || fail "could not move the saved log to $f"
    echo "PA_SAVED $f"
    pre="$(docker logs --tail 20000 telcoin 2>&1 | mark || true)"
else
    note "no telcoin container: no log to save"
fi
echo "PA_PRE ${pre:--}"

# 3. No stop within EM s of an epoch boundary, either side (v2 tn_epoch_secs_left: "<secs left>
#    <epoch> <boundary unix> <duration>"; after the boundary, until the epoch closes, secs left is
#    negative; once the next epoch runs, duration - secs left is the time since the boundary).
#    Naps of at most 15 s, EW s in all; after a wait (WAITED = the seconds slept), the guard again.
SECS_RE='^-?[0-9]+$' DUR_RE='^[0-9]+$'
WAITED=0
epoch_clear() {
    local t0 now w secs dur since nap last slept=0
    t0="$(date +%s)"
    while :; do
        w="$(tnlib tn_epoch_secs_left 2>/dev/null)" || w=""
        secs="" dur=""
        read -r secs _ _ dur _ <<< "$w" || true
        now="$(date +%s)"
        if [[ "$secs" =~ $SECS_RE ]] && [[ "$dur" =~ $DUR_RE ]]; then
            since=$((dur - secs))
            if [ "$secs" -gt "$EM" ] && [ "$since" -ge "$EM" ]; then
                WAITED="$slept"
                echo "PA_EPOCH ${NODE} secs_left=${secs} since_boundary=${since} waited=${WAITED}"
                return 0
            fi
            if [ "$secs" -le "$EM" ]; then nap=$((secs + EM + 1)); else nap=$((EM - since + 1)); fi
            last="the epoch boundary is ${secs} s away, the last one ${since} s ago"
        else
            nap=10
            last="the epoch timing could not be read (${w:-no answer})"
        fi
        [ "$((now - t0))" -lt "$EW" ] || fail "gave up after ${EW} s waiting to be ${EM} s clear of an epoch boundary: ${last}; the node was not restarted"
        [ "$nap" -ge 1 ] || nap=1
        [ "$nap" -le 15 ] || nap=15
        echo "PA_EPOCH_WAIT ${NODE} ${last}; looking again in ${nap} s"
        sleep "$nap"
        slept=$((slept + nap))
    done
}
epoch_clear
if [ "$WAITED" -gt 0 ]; then note "waited ${WAITED} s for the epoch boundary: the committee guard again"; guard; fi
echo "PA_GUARD_SUMMARY ${NODE} samples=${GSAMPLES} refused=${GREFUSED}"

# 4. parameters.yaml, rewritten in place (cat >: owner, mode and inode stay). A copy per change;
#    a file without `# bench-override` lines is also kept as the .bak (the unmarked original). A file
#    with marked lines and no .bak never gets here: validation refuses it (and deploy step 7 writes its
#    overrides marked, without a .bak).
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$P" "$P.bak-$STAMP" || fail "cannot copy $P to $P.bak-$STAMP"
echo "PA_BACKUP $P.bak-$STAMP"
grep -q '# bench-override$' "$P" || cp -p "$P" "$P.bak" || fail "cannot copy $P to $P.bak"
rfail() { cat "$P.bak-$STAMP" > "$P"; fail "$* (file restored, node not restarted)"; }
# setp <key> <value> — rewrite the top-level `key:` line (append it when absent), marked. The
# rules of bench-lib.sh bench_prestart_script's setp (deploy step 7), plus a restore on failure.
setp() {
    local t
    t="$(mktemp)"
    if ! awk -v k="$1" -v v="$2" '
        index($0, k ":") == 1 { r = substr($0, length(k) + 2); sub(/^[ \t]+/, "", r); sub(/[ \t]*#.*$/, "", r)
                                if (r == "") blk = 1
                                if (!n++) print k ": " v "  # bench-override"
                                next }
        { print }
        END { if (!n) print k ": " v "  # bench-override"; exit (blk ? 3 : 0) }' "$P" > "$t"; then
        rm -f "$t"; rfail "$1 is a block (secs/nanos) in $P"
    fi
    cat "$t" > "$P"; rm -f "$t"
    [ "$(grep -c "^$1: $2  # bench-override\$" "$P" || true)" = 1 ] || rfail "$1 not rewritten in $P"
}
REMOTE
    cat "$5"
    cat <<'REMOTE'

# 5. One transient unit stops telcoin, runs the arm's host steps and starts telcoin: started by
#    systemd, not by this session, so a dropped session cannot leave the node stopped. Its script
#    and output stay in $LOGDIR/arm-units/.
UNIT="${UNIT_PREFIX}-${STAMP}"
UD="$LOGDIR/arm-units"
US="$UD/$UNIT.sh" UO="$UD/$UNIT.out"
mkdir -p "$UD" || rfail "cannot create $UD"
[ ! -e "$US" ] && [ ! -e "$UO" ] || rfail "$US or $UO exists already"
cat > "$US" <<'PA_UNIT_SCRIPT' || rfail "cannot write $US"
REMOTE
    cat "${WORK}/unit.${N_NAME[$1]}.sh"
    cat <<'REMOTE'
PA_UNIT_SCRIPT
: > "$UO" || rfail "cannot create $UO"
r=0
systemd-run --unit="$UNIT" --description="params-apply $LABEL on $NODE: stop telcoin, host steps, start telcoin" \
    --collect --quiet -- /bin/bash "$US" "$UO" "$D" "$NODE" "$UNIT" || r=$?
[ "$r" = 0 ] || rfail "systemd-run --unit=$UNIT failed (rc $r)"
echo "PA_UNIT_LAUNCHED $UNIT $(date -u +%Y-%m-%dT%H:%M:%SZ)"
udl=$(( $(date +%s) + UW ))
until grep -q '^START_RC ' "$UO" 2>/dev/null; do
    [ "$(date +%s)" -lt "$udl" ] || fail "the unit $UNIT reported no start within ${UW} s; it keeps running on its own (systemctl status $UNIT; $UO)"
    sleep 2
done
sed 's/^/PA_UNIT /' "$UO"
uval() { sed -n "s/^$1 //p" "$UO" | tail -n 1; }
stop_at="$(uval STOP_AT)"; stop_ts="${stop_at##* }"; stop_at="${stop_at%% *}"
restart_ts="$(uval START_AT)"; restart_ts="${restart_ts##* }"
echo "RESTART_AT ${stop_at}"
src="$(uval STOP_RC)" hrc="$(uval HOOK_RC)" rc="$(uval START_RC)"
[ "$src" = 0 ] || fail "systemctl stop telcoin failed in $UNIT (rc $src); the unit started it again (rc $rc)"
[ "$hrc" = 0 ] || fail "the host steps failed in $UNIT (rc $hrc): $(grep '^HOST_RESULT ' "$UO" | tail -n 1); telcoin was started again (rc $rc)"
[ "$rc" = 0 ] || fail "systemctl start telcoin failed in $UNIT (rc $rc)"
case "$stop_ts:$restart_ts" in *[!0-9:]*|:*|*:) fail "the unit $UNIT did not report its stop and start times" ;; esac

# 6. Wait until the RPC answers (with the chain id it had) and this node's consensus has moved
#    past where it was before the restart: a validator's own round, an observer's consensus
#    number. An idle chain stays at block 0, so blocks are no measure.
deadline=$(( restart_ts + WAIT ))
cid=""; how=""; now=""; prog_ts=""; prog_at=""
while [ "$(date +%s)" -lt "$deadline" ]; do
    if systemctl is-active --quiet telcoin; then
        if [ -z "$cid" ]; then
            c="$(rpc eth_chainId)"
            case "$c" in
                0x*) [ "$EXPECT_CHAIN" = - ] || [ "$c" = "$EXPECT_CHAIN" ] || fail "eth_chainId is $c after the restart, $EXPECT_CHAIN before"
                     cid="$c" ;;
            esac
        fi
        if [ -z "$how" ]; then
            now="$(docker logs telcoin --since "$restart_ts" 2>&1 | mark || true)"
            if [ -n "$now" ] && later "$now" "$pre"; then how="$now"; prog_ts="$(date +%s)"; prog_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; fi
        fi
    fi
    if [ -n "$cid" ] && [ -n "$how" ]; then break; fi
    sleep 3
done
[ -n "$cid" ] || fail "eth_chainId did not answer on 127.0.0.1:8545 within ${WAIT} s of the restart"
if [ "$ROLE" = validator ]; then what="(epoch round) of its quorum reached/header proposed lines"; else what="consensus number"; fi
[ -n "$how" ] || fail "no consensus progress within ${WAIT} s of the restart: ${what} ${now:-none} since, ${pre:-none} before"
echo "PA_PROGRESS ${what}: ${pre:-none} -> ${how}"
echo "PA_PROGRESS_AT ${prog_at}"
echo "PA_RESTART_SECS $((prog_ts - stop_ts))"

# 7. What the node booted with must be what the file says (else it reads another file), and the
#    readback. pv/ms from benchmark-deploy.sh postconfig_readback. The `node switches` line of this
#    start: the newest since the stop (the tool compares it, and its own time, with the arm).
pv() { awk -v k="$1" 'index($0, k ":") == 1 { v = substr($0, length(k) + 2); sub(/^[ \t]+/, "", v); sub(/[ \t]*#.*$/, "", v); gsub(/["\047]/, "", v); print v; exit }' "$P"; }
ms() { case "$1" in '') echo - ;; *ms) echo "${1%ms}" ;; *s) awk -v s="${1%s}" 'BEGIN { printf "%d\n", s * 1000 }' ;; *m) awk -v s="${1%m}" 'BEGIN { printf "%d\n", s * 60000 }' ;; *) echo "?" ;; esac; }
BOOT="$(docker logs telcoin --since "$restart_ts" 2>&1 | grep -iE 'set to [0-9]+ ?ms' || true)"
chk() {
    local y b
    y="$(ms "$(pv "$1")")"
    case "$y" in -|"?") return 0 ;; esac
    b="$(printf '%s\n' "$BOOT" | grep -ioE "$2 set to [0-9]+ ?ms" | tail -1 | grep -oE '[0-9]+' | head -1 || true)"
    if [ -z "$b" ]; then note "no '$2 set to' line since the restart; not compared"; return 0; fi
    [ "$b" = "$y" ] || fail "the node booted with $2 $b ms but $P says $y ms: it does not read this file"
}
chk max_header_delay 'max header delay'
chk min_header_delay 'min header delay'
chk max_batch_delay 'max batch delay'
chk vote_timeout 'vote timeout'
SW="$(docker logs telcoin --since "$stop_ts" 2>&1 | grep -F 'node switches' | tail -n 1 || true)"
echo "PA_STOP_AT ${stop_at}"
echo "PA_SWITCH_LINE ${SW:--}"
thr="$(pv header_num_of_batches_threshold)"
echo "PARAMS_OK ${NODE} max=$(ms "$(pv max_header_delay)") min=$(ms "$(pv min_header_delay)") batch=$(ms "$(pv max_batch_delay)") thr=${thr:--} vote=$(ms "$(pv vote_timeout)")"
REMOTE
}

# --- phase A: read every node ------------------------------------------------------------
TARGETS=()
if [ "${MODE}" = stage ]; then TARGETS=("${STAGE_IDX}"); else TARGETS=("${!N_NAME[@]}"); fi

phase_a_job() {
    local i="$1" n="${N_NAME[$1]}" rc=0
    phase_a_script "${i}" > "${WORK}/a.${n}.sh"
    if [ "${DRY}" = 1 ]; then
        echo "----- phase A script for ${n} (stdin of sudo bash -s) -----"
        cat "${WORK}/a.${n}.sh"
        echo "----- end -----"
    fi
    iap_ssh "${PHASE_A_SECS}" "${i}" "${WORK}/a.${n}.sh" "${WORK}/a.${n}.err" > "${WORK}/a.${n}.out" || rc=$?
    echo "${rc}" > "${WORK}/a.${n}.rc"
}

# a_field <node> <KEY> — the value of the node's phase-A line "PA_<KEY> <value>".
a_field() { sed -n "s/^PA_$2 //p" "${WORK}/a.$1.out" | head -1; }

log "phase A: reading ${#TARGETS[@]} node(s), up to ${SSH_PARALLEL} at once$([ "${DRY}" = 0 ] || echo ' (dry run)')"
pool "${SSH_PARALLEL}" phase_a_job "${TARGETS[@]}"

if [ "${DRY}" = 0 ]; then
    bad=0
    for i in "${TARGETS[@]}"; do
        n="${N_NAME[$i]}"
        if [ "$(cat "${WORK}/a.${n}.rc")" != 0 ] || ! grep -qx "PA_OK ${n}" "${WORK}/a.${n}.out"; then
            bad=1
            echo "  FAIL ${n}: $(grep -h '^PA_FAIL ' "${WORK}/a.${n}.out" | head -1 || true) $(last_error "${WORK}/a.${n}.err")" >&2
            continue
        fi
        sed -n '/^PA_YAML_BEGIN$/,/^PA_YAML_END$/p' "${WORK}/a.${n}.out" | sed '1d;$d' > "${WORK}/${n}.yaml"
        printf '  %-24s %-9s %s  container %s  chain %s  %s bench-override line(s), .bak %s\n' "${n}" "${N_ROLE[$i]}" \
            "$(a_field "${n}" PARAMS)" "$([ "$(a_field "${n}" RUNNING)" = 1 ] && echo running || echo 'NOT running')" \
            "$(a_field "${n}" CHAIN)" "$(a_field "${n}" MARKERS)" "$([ "$(a_field "${n}" BAK)" = 1 ] && echo yes || echo no)"
        printf '  %-24s launch file %s; datadir %s\n' "" "$(a_field "${n}" LAUNCH)" "$(a_field "${n}" DATADIR)"
    done
    [ "${bad}" = 0 ] || fatal "phase A failed on the node(s) above; nothing was changed"
fi

# --- validation and plan -------------------------------------------------------------------
# A dry run of an arm file reads no node: the switches it starts from are the latest recorded arm's
# (`switches`), else every default (a fresh fleet).
ASSUMED_FROM=""
if [ "${DRY}" = 1 ] && [ -n "${ARM_FILE}" ]; then
    : > "${WORK}/assumed"
    if [ -f "${REC_FILE}" ] && command -v jq >/dev/null 2>&1; then
        jq -r '[(.param_arms // [])[] | select(.switches != null)] | last // {} | .switches // {} | to_entries[] | "\(.key)=\(.value)"' \
            "${REC_FILE}" > "${WORK}/assumed" 2>/dev/null || : > "${WORK}/assumed"
        ASSUMED_FROM="$(jq -r '[(.param_arms // [])[] | select(.switches != null)] | last // {} | if .name then "the switches of arm \(.name) in the record" + (if .failed then " (it stopped at \(.failed))" else "" end) else "" end' "${REC_FILE}" 2>/dev/null || true)"
    fi
    ASSUMED_FROM="${ASSUMED_FROM:-every switch at its default (no arm with switches in ${REC_FILE})}"
fi
# assumed_of <key> — the dry run's starting value of a switch.
assumed_of() {
    local v j
    v="$(sed -n "s/^$1=//p" "${WORK}/assumed" | tail -n 1)"
    if [ -z "${v}" ]; then j="$(sw_idx "$1")" && v="${SW_D[$j]}"; fi
    printf '%s\n' "${v}"
}

# Per node: ${WORK}/w.<node> = the setp lines phase B runs; ${WORK}/chg.<node> = "key old new";
# ${WORK}/why.<node> = why it restarts (params: a key rewritten; live: its running switches are not
# the arm's; unread: they could not be read; host: the arm's host steps), empty when it does not.
problems="" PLAN=() UNCHANGED=()
for i in "${TARGETS[@]}"; do
    n="${N_NAME[$i]}"
    : > "${WORK}/w.${n}"; : > "${WORK}/chg.${n}"; : > "${WORK}/why.${n}"
    if [ "${DRY}" = 1 ]; then
        res_build "${n}"
    else
        res_build "${n}" "${WORK}/${n}.yaml" "$([ "${MODE}" != stage ] || echo nosets)"
        if [ "$(a_field "${n}" MARKERS)" != 0 ] && [ "$(a_field "${n}" BAK)" != 1 ]; then
            problems="${problems}${n}: $(a_field "${n}" PARAMS) has bench-override lines but no .bak"$'\n'
        fi
    fi
    if [ "${MODE}" = stage ]; then
        # The current values of the keys --set names (else the two header delays), written back as they are.
        keys="$(node_sets "${n}" | sed 's/=.*//')"
        [ -n "${keys}" ] || keys="max_header_delay min_header_delay"
        for k in ${keys}; do
            if [ "${DRY}" = 1 ]; then printf 'setp %s <current value>\n' "${k}" >> "${WORK}/w.${n}"; continue; fi
            got="$(yaml_get "${WORK}/${n}.yaml" "${k}")"
            v="${got#*"${TAB}"}"
            case "${got%%"${TAB}"*}:${v}" in
                scalar:*[!A-Za-z0-9._-]*|scalar:) echo "  note: ${n}: ${k} '${v}' is not rewritten (unusual characters)" ;;
                scalar:*) printf 'setp %s %s\n' "${k}" "${v}" >> "${WORK}/w.${n}"; printf '%s %s %s\n' "${k}" "${v}" "${v}" >> "${WORK}/chg.${n}" ;;
                *) echo "  note: ${n}: ${k} is not a scalar in the file (${got%%"${TAB}"*}); not rewritten" ;;
            esac
        done
        # What the restarted node should print: the file's switches (a switch it leaves out at its
        # default). Compared only when the image logs the line.
        : > "${WORK}/targets.${n}"
        if [ "${DRY}" = 0 ]; then
            for j in "${!SW_K[@]}"; do
                got="$(yaml_get "${WORK}/${n}.yaml" "${SW_K[$j]}")"
                case "${got%%"${TAB}"*}" in scalar) v="${got#*"${TAB}"}" ;; *) v="${SW_D[$j]}" ;; esac
                printf '%s=%s\n' "${SW_K[$j]}" "${v}" >> "${WORK}/targets.${n}"
            done
        fi
        echo stage > "${WORK}/why.${n}"
        PLAN+=("${i}")
        continue
    fi
    while IFS= read -r kv; do
        [ -n "${kv}" ] || continue
        k="${kv%%=*}" v="${kv#*=}" old="(not read: dry run)" form=unread
        j="$(sw_idx "${k}")" || j=""
        if [ "${DRY}" = 0 ]; then
            old="(absent)" form=absent
            got="$(yaml_get "${WORK}/${n}.yaml" "${k}")"; form="${got%%"${TAB}"*}"
            case "${form}" in scalar) old="${got#*"${TAB}"}" ;; block) old="(secs/nanos block)" ;; esac
        elif [ -n "${j}" ] && [ -n "${ASSUMED_FROM}" ]; then
            old="$(assumed_of "${k}")" form=assumed
        fi
        if [ "${form}" = block ]; then
            problems="${problems}${n}: ${k} is a secs/nanos block in $(a_field "${n}" PARAMS); write it as <int>ms there first"$'\n'
            continue
        fi
        if [ -n "${j}" ]; then
            # A switch: left out of the file, it is at its default; rewritten only when it differs.
            cur=""
            case "${form}" in absent) cur="${SW_D[$j]}" ;; scalar|assumed) cur="${old}" ;; esac
            if [ -n "${cur}" ] && [ "$(norm_val "${SW_T[$j]}" "${cur}")" = "$(norm_val "${SW_T[$j]}" "${v}")" ]; then continue; fi
        elif [ "${form}" = scalar ]; then
            if [ "$(key_type "${k}")" = dur ]; then
                [ "$(to_ms "${old}")" != "$(to_ms "${v}")" ] || continue
            else
                [ "${old}" != "${v}" ] || continue
            fi
        fi
        printf 'setp %s %s\n' "${k}" "${v}" >> "${WORK}/w.${n}"
        printf '%s %s %s\n' "${k}" "${old}" "${v}" >> "${WORK}/chg.${n}"
    done <<< "$(node_sets "${n}")"
    why=""
    [ ! -s "${WORK}/w.${n}" ] || why="params"
    # The running switches (phase A's line): a target the image does not print refuses the arm
    # before anything changes; one that differs, or no line to compare, restarts the node.
    if [ -s "${WORK}/targets.${n}" ] && [ "${DRY}" = 0 ]; then
        line="$(a_field "${n}" SWITCH_LINE)"
        if [ -z "${line}" ] || [ "${line}" = - ]; then
            why="${why:+${why},}unread"
        else
            cmp="$(switch_compare "${n}" "${line}")"
            while read -r what k got want; do
                case "${what}" in
                    absent) problems="${problems}${n}: its image does not know ${k} (its running 'node switches' line has no ${k}); the arm sets ${k}=${want}"$'\n' ;;
                esac
            done <<< "${cmp}"
            if has_line "${cmp}" "differs "; then why="${why:+${why},}live"; fi
        fi
    fi
    [ -z "${ARM_HOST_STEPS}" ] || why="${why:+${why},}host"
    printf '%s\n' "${why}" > "${WORK}/why.${n}"
    if [ -n "${why}" ]; then PLAN+=("${i}"); else UNCHANGED+=("${i}"); fi
    [ "${DRY}" = 1 ] || problems="${problems}$(res_problems "${n}" 1)"$'\n'
done
# A node that restarts needs the guard's library and systemd-run.
if [ "${DRY}" = 0 ]; then
    for i in ${PLAN[@]+"${PLAN[@]}"}; do
        n="${N_NAME[$i]}"
        [ "$(a_field "${n}" LIB)" = 1 ] || problems="${problems}${n}: no ${NODE_SCRIPTS_DIR}/lib/common.sh (the v2 scripts' library): the committee guard and the epoch timing need it"$'\n'
        [ "$(a_field "${n}" SYSTEMD_RUN)" = 1 ] || problems="${problems}${n}: no systemd-run: the stop and the start run in one transient unit"$'\n'
    done
fi
problems="$(printf '%s' "${problems}" | grep -v '^$' || true)"
[ -z "${problems}" ] || fatal "refused before any change; with these values a node would refuse to start (or the file cannot be rewritten, or the node cannot take the arm):"$'\n'"$(printf '%s\n' "${problems}" | sed 's/^/  /')"

# Phase B order: observers first (a canary that does not vote), then validators, list order.
ORDER=()
for role in observer validator; do
    for i in ${PLAN[@]+"${PLAN[@]}"}; do [ "${N_ROLE[$i]}" != "${role}" ] || ORDER+=("${i}"); done
done

if [ "${MODE}" = stage ]; then
    log "plan: stage test on ${STAGE}: rewrite with its current values (no change), restart, wait healthy; no arm recorded"
else
    log "plan for arm ${ARM}: ${#ORDER[@]} node(s) to restart one at a time, ${#UNCHANGED[@]} already in it; record: ${REC_FILE}"
fi
if [ -n "${ARM_FILE}" ]; then
    echo "  arm file ${ARM_FILE_REL} (sha256 ${ARM_FILE_SHA}); switches: $(awk '{ printf "%s%s", (NR > 1 ? " " : ""), $0 }' "${WORK}/arm.target")"
    echo "  host steps: ${ARM_HOST_DESC:-none}"
    [ "${DRY}" = 0 ] || echo "  dry run: each node starts from ${ASSUMED_FROM}; a live run reads every node and also restarts one whose running switches differ or cannot be read"
fi
for i in ${ORDER[@]+"${ORDER[@]}"} ${UNCHANGED[@]+"${UNCHANGED[@]}"}; do
    n="${N_NAME[$i]}"
    why="$(cat "${WORK}/why.${n}")"
    extra=""
    case "${why}" in ''|params|stage) ;; *) extra="; restart (${why})" ;; esac
    [ -z "${ARM_FILE}" ] || [ -z "${why}" ] || extra="; restart (${why})"
    [ -z "${ARM_HOST_STEPS}" ] || [ -z "${why}" ] || extra="${extra}; host steps: ${ARM_HOST_DESC}"
    if [ -s "${WORK}/chg.${n}" ]; then
        printf '  %-24s %-9s %s%s\n' "${n}" "${N_ROLE[$i]}" "$(awk '{ printf "%s%s %s -> %s", (NR > 1 ? ", " : ""), $1, $2, $3 }' "${WORK}/chg.${n}")" "${extra}"
    elif [ "${MODE}" = stage ] && [ "${DRY}" = 1 ]; then
        printf '  %-24s %-9s %s\n' "${n}" "${N_ROLE[$i]}" "rewrite $(sed 's/^setp //; s/ <current value>//' "${WORK}/w.${n}" | paste -sd, -) with their current values"
    elif [ -n "${why}" ]; then
        printf '  %-24s %-9s %s%s\n' "${n}" "${N_ROLE[$i]}" "no key to rewrite" "${extra}"
    else
        printf '  %-24s %-9s %s\n' "${n}" "${N_ROLE[$i]}" "no change; not restarted"
    fi
done
if [ -n "${HOOK_ERR}" ]; then die "${HOOK_ERR} (dry run: a live run refuses this arm before contacting any node)"; fi

# --- phase B: one node at a time -------------------------------------------------------------
LABEL="pre-arm-${ARM}"
[ "${MODE}" != stage ] || LABEL="stage-test"
BEGIN="" APPLIED=() LAST_PROGRESS=""
# The phase B session's alarm: the guard (up to four rounds), the epoch wait, the unit, the health
# wait and the log save. When it fires after the unit was launched, the unit still finishes.
PHASE_B_SECS=$(( 4 * GUARD_TRIES * (GUARD_SECS + 25) + 2 * GUARD_DEFER_SECS + EPOCH_WAIT_SECS + UNIT_SECS + HEALTH_SECS + 900 ))

# arm_head_json — the entry's fields beside name/begin/end: who applied it, and for an arm file
# the file, its sha256 and the full switch state.
arm_head_json() {
    if [ -n "${ARM_FILE}" ]; then
        jq -n -c --arg f "${ARM_FILE_REL}" --arg s "${ARM_FILE_SHA}" --argjson sw "$(kv_json < "${WORK}/arm.target")" \
            '{via: "params-apply", file: $f, sha256: $s, switches: $sw}'
    else
        printf '{"via": "params-apply", "file": null}\n'
    fi
}
# rec_open <begin> — the arm's entry (begin = its first restart); it closes the arm open before it,
# and that arm's open marks.
rec_open() {
    [ "${MODE}" = apply ] || return 0
    BEGIN="$1"
    rec_jq --arg a "${ARM}" --arg b "${BEGIN}" --argjson head "$(arm_head_json)" '
        .param_arms = (((.param_arms // []) | map(if .end == null then
                            (.end = $b | if (.marks | type) == "array" then .marks |= map(if .end == null then .end = $b else . end) else . end)
                        else . end))
                       + [{name: $a, begin: $b, end: null} + $head + {nodes: {}, host: [], restart_secs: {}, guard: {}, marks: []}])'
}
# rec_upd <filter> [<jq args>...] — <filter> on this arm's entry (none before the arm opened).
rec_upd() {
    local f="$1"
    shift
    [ "${MODE}" = apply ] && [ -n "${BEGIN}" ] || return 0
    rec_jq --arg a "${ARM}" --arg b "${BEGIN}" "$@" \
        ".param_arms |= map(if .name == \$a and .begin == \$b then (${f}) else . end)"
}
# rec_node <node> <values json or ""> <guard json or ""> <restart secs or ""> — the node into the arm.
rec_node() {
    [ -z "$2" ] || rec_upd '.nodes[$n] = $v' --arg n "$1" --argjson v "$2"
    [ -z "$3" ] || rec_upd '.guard[$n] = $g' --arg n "$1" --argjson g "$3"
    [ -z "$4" ] || rec_upd '.restart_secs[$n] = $r' --arg n "$1" --argjson r "$4"
}
# rec_host <node> <out file> — its HOST_RESULT lines into the entry's host steps (in run order).
rec_host() {
    local s v r
    while read -r s v r; do
        [ -n "${r}" ] || continue
        printf '%s\n' "${r}" | jq -e 'type == "object"' >/dev/null 2>&1 || r="$(jq -n -c --arg x "${r}" '{failed: ("unreadable result: " + $x)}')"
        rec_upd '.host = ((.host // []) | if any(.[]; .step == $s) then map(if .step == $s then .nodes[$n] = $r else . end)
                          else . + [{step: $s, value: (if $v == "-" then null else $v end), nodes: {($n): $r}}] end)' \
            --arg n "$1" --arg s "${s}" --arg v "${v}" --argjson r "${r}"
    done < <(sed -n 's/^PA_UNIT HOST_RESULT //p' "$2")
}

# okline_matches <node> <PARAMS_OK line> — the readback is the plan's resulting values.
okline_matches() {
    local n="$1" line="$2" want got f
    for f in "max:max_header_delay:ms" "min:min_header_delay:ms" "batch:max_batch_delay:ms" \
             "thr:header_num_of_batches_threshold:raw" "vote:vote_timeout:ms"; do
        # A secs/nanos block (never one this tool wrote) reads back as "-": not compared.
        [ "$(res_raw "${n}" "$(echo "${f}" | cut -d: -f2)")" != "(block)" ] || continue
        if [ "${f##*:}" = ms ]; then want="$(res_ms "${n}" "$(echo "${f}" | cut -d: -f2)")"
        else want="$(res_raw "${n}" "$(echo "${f}" | cut -d: -f2)")"; fi
        got="$(printf '%s\n' "${line}" | sed -n "s/.* ${f%%:*}=\([^ ]*\).*/\1/p")"
        [ "${got}" = "${want:--}" ] || { echo "${f%%:*}=${got} (expected ${want:--})"; return 1; }
    done
}

# current_line <node> — the values of the file phase A read, in the PARAMS_OK format.
current_line() {
    local n="$1" f k got v out=""
    for f in "max:max_header_delay:ms" "min:min_header_delay:ms" "batch:max_batch_delay:ms" \
             "thr:header_num_of_batches_threshold:raw" "vote:vote_timeout:ms"; do
        k="$(echo "${f}" | cut -d: -f2)" v=-
        got="$(yaml_get "${WORK}/${n}.yaml" "${k}")"
        if [ "${got%%"${TAB}"*}" = scalar ]; then
            v="${got#*"${TAB}"}"
            if [ "${f##*:}" = ms ]; then v="$(to_ms "${v}")"; v="${v:-?}"; fi
        fi
        out="${out} ${f%%:*}=${v}"
    done
    echo "PARAMS_CURRENT ${n}${out}"
}

# arm_ready <ready time> — the arm is in force on every node: record `ready`, print ARM_READY.
arm_ready() {
    rec_upd '.ready = $t' --arg t "$1"
    echo "ARM_READY ${ARM} ready=$1 restarted=${#APPLIED[@]} nodes=${#TARGETS[@]}"
}

# Nothing to change: no restart, but the arm is recorded like any other (it opens with begin =
# now, by this machine's clock, and closes the arm open before it), marked no_restart, ready =
# begin. Every node of the arm first passes the readback check on what phase A read (the file; for
# switches, the running container's line, already compared in the plan), and must run its
# container: a stopped node does not run these values.
if [ "${#ORDER[@]}" -eq 0 ]; then
    if [ "${DRY}" = 1 ]; then
        log "dry run: nothing to restart; would record arm ${ARM} (no_restart) in ${REC_FILE}"
        exit 0
    fi
    ARM_NODES=() problems=""
    for i in ${UNCHANGED[@]+"${UNCHANGED[@]}"}; do
        n="${N_NAME[$i]}"
        [ -n "$(node_sets "${n}")" ] || continue
        okline="$(current_line "${n}")"
        echo "${okline}"
        if ! why="$(okline_matches "${n}" "${okline}")"; then
            problems="${problems}${n}: $(a_field "${n}" PARAMS) reads ${why}"$'\n'
        fi
        [ ! -s "${WORK}/targets.${n}" ] || echo "SWITCHES_CURRENT ${n} $(switch_values "$(a_field "${n}" SWITCH_LINE)")"
        [ "$(a_field "${n}" RUNNING)" = 1 ] \
            || problems="${problems}${n}: the telcoin container is NOT running, so the node does not run these values"$'\n'
        ARM_NODES+=("${n}")
    done
    problems="$(printf '%s' "${problems}" | grep -v '^$' || true)"
    [ -z "${problems}" ] || fatal "arm ${ARM} NOT recorded (nothing was restarted or changed):"$'\n'"$(printf '%s\n' "${problems}" | sed 's/^/  /')"
    now="$(now_utc)"
    rec_open "${now}"
    if [ -z "${ARM_FILE}" ]; then
        for n in ${ARM_NODES[@]+"${ARM_NODES[@]}"}; do rec_node "${n}" "$(vals_json "${n}")" "" ""; done
    fi
    rec_upd '.no_restart = true'
    log "arm ${ARM} recorded: 0 node(s) restarted, ${#ARM_NODES[@]} already at these values; begin ${BEGIN} (this machine's clock); recorded in ${REC_FILE}"
    arm_ready "${BEGIN}"
    jq -c --arg a "${ARM}" --arg b "${BEGIN}" '.param_arms[] | select(.name == $a and .begin == $b)' "${REC_FILE}"
    exit 0
fi

step=0
for i in "${ORDER[@]}"; do
    step=$((step + 1))
    n="${N_NAME[$i]}"
    exp_sha="-" exp_chain="-"
    if [ "${DRY}" = 0 ]; then
        exp_sha="$(a_field "${n}" SHA)"
        exp_chain="$(a_field "${n}" CHAIN)"
    fi
    phase_b_script "${i}" "${LABEL}" "${exp_sha}" "${exp_chain}" "${WORK}/w.${n}" > "${WORK}/b.${n}.sh"
    log "phase B ${step}/${#ORDER[@]}: ${n} (${N_ROLE[$i]}): guard, save log, epoch check, rewrite, stop/start unit, wait up to ${HEALTH_SECS} s"
    if [ "${DRY}" = 1 ]; then
        echo "----- phase B script for ${n} (stdin of sudo bash -s) -----"
        cat "${WORK}/b.${n}.sh"
        echo "----- end -----"
        iap_ssh "${PHASE_B_SECS}" "${i}" "${WORK}/b.${n}.sh" "${WORK}/b.${n}.err"
        continue
    fi
    [ "${DRY}" = 0 ] || continue
    set +e
    iap_ssh "${PHASE_B_SECS}" "${i}" "${WORK}/b.${n}.sh" "${WORK}/b.${n}.err" | tee "${WORK}/b.${n}.out" \
        | while IFS= read -r l; do case "${l}" in PARAMS_OK\ *) ;; *) printf '      %s\n' "${l}" ;; esac; done
    rc="${PIPESTATUS[0]}"
    set -e
    bout="${WORK}/b.${n}.out"
    restarted="$(sed -n 's/^RESTART_AT //p' "${bout}" | head -1)"
    launched="$(sed -n 's/^PA_UNIT_LAUNCHED //p' "${bout}" | head -1)"
    # A session that dropped after the unit was launched: the node restarts on its own, so the arm
    # has begun (at about the launch).
    [ -n "${restarted}" ] || restarted="${launched#* }"
    gjson="$(sed -n 's/^PA_GUARD_SUMMARY [^ ]* samples=\([0-9][0-9]*\) refused=\([0-9][0-9]*\)$/{"samples": \1, "refused": \2}/p' "${bout}" | tail -1)"
    rsecs="$(sed -n 's/^PA_RESTART_SECS //p' "${bout}" | tail -1)"
    case "${rsecs}" in ''|*[!0-9]*) rsecs="" ;; *) rsecs="$(awk -v s="${rsecs}" 'BEGIN { printf "%.1f\n", s }')" ;; esac
    if [ -n "${restarted}" ] && [ -z "${BEGIN}" ]; then rec_open "${restarted}"; fi
    vals=""
    [ -z "${restarted}" ] || vals="$(node_vals_json "${n}")"
    rec_node "${n}" "${vals}" "${gjson}" "${rsecs}"
    rec_host "${n}" "${bout}"
    okline="$(grep -E "^PARAMS_OK ${n} " "${bout}" | tail -1 || true)"
    swline="$(sed -n 's/^PA_SWITCH_LINE //p' "${bout}" | tail -1)"
    why=""
    if [ "${rc}" != 0 ] || [ -z "${okline}" ]; then
        why="$(grep -h '^PARAMS_FAIL ' "${bout}" | head -1 | sed "s/^PARAMS_FAIL ${n} //" || true)"
        why="${why:-ssh exit ${rc}: $(last_error "${WORK}/b.${n}.err")}"
    elif ! why="$(okline_matches "${n}" "${okline}")"; then
        why="readback ${why}"
    elif [ "${MODE}" = stage ] && { [ -z "${swline}" ] || [ "${swline}" = - ]; }; then
        echo "  note: ${n} logged no 'node switches' line since the restart (an image without it); not compared"
        why=""
    elif [ -s "${WORK}/targets.${n}" ] && ! why="$(switch_readback "${n}" "${swline}" "$(sed -n 's/^PA_STOP_AT //p' "${bout}" | tail -1)")"; then
        why="switches readback: ${why}"
    else
        why=""
    fi
    if [ -n "${why}" ]; then
        rec_upd '.failed = $n' --arg n "${n}"
        echo "PA_FAIL ${n} ${why}"
        P_REMOTE="$(a_field "${n}" PARAMS)"
        BACKUP="$(sed -n 's/^PA_BACKUP //p' "${bout}" | head -1)"
        UNIT_NAME="${launched%% *}"
        {
            if [ -n "${restarted}" ]; then echo "params-apply: ${n} did not come back: ${why}"; else echo "params-apply: ${n} was not restarted: ${why}"; fi
            if [ -n "${restarted}" ]; then echo "  it was restarted at ${restarted} with the new file"; else echo "  it was NOT restarted"; fi
            [ -z "${UNIT_NAME}" ] || echo "  its stop and start ran in the unit ${UNIT_NAME}: sudo systemctl status ${UNIT_NAME}; sudo cat ${REMOTE_LOG_DIR}/arm-units/${UNIT_NAME}.out"
            echo "  later nodes were not touched: $(for j in "${ORDER[@]}"; do printf '%s ' "${N_NAME[$j]}"; done | sed "s/.*${n} //")"
            echo "  inspect:  gcloud compute ssh ${n} --zone=${N_ZONE[$i]} --project=${N_PROJ[$i]} --tunnel-through-iap"
            echo "  on it:    sudo docker logs --tail 200 telcoin; sudo systemctl status telcoin; ls -l ${P_REMOTE}*"
            [ -z "${BACKUP}" ] || [ -z "${restarted}" ] || echo "  rollback: sudo cp -p ${BACKUP} ${P_REMOTE} && sudo systemctl restart telcoin"
            [ "${MODE}" != apply ] || [ -z "${BEGIN}" ] || echo "  recorded: arm ${ARM} failed at ${n}; to resume, re-run with --arm <new name> (nodes already in the arm are not restarted)"
        } >&2
        exit 1
    fi
    [ ! -s "${WORK}/targets.${n}" ] || [ -z "${swline}" ] || [ "${swline}" = - ] || echo "SWITCHES_OK ${n} $(switch_values "${swline}")"
    echo "${okline}"
    APPLIED+=("${i}")
    pat="$(sed -n 's/^PA_PROGRESS_AT //p' "${bout}" | tail -1)"
    if [ -n "${pat}" ] && { [ -z "${LAST_PROGRESS}" ] || [[ "${LAST_PROGRESS}" < "${pat}" ]]; }; then LAST_PROGRESS="${pat}"; fi
done

[ "${DRY}" = 0 ] || { log "dry run: nothing was contacted or changed"; exit 0; }
if [ "${MODE}" = stage ]; then
    log "stage test passed on ${STAGE}: log saved, file rewritten unchanged, stopped and started in one unit, back in consensus"
    exit 0
fi
# Nodes the arm's values reach that already had them: in an arm given with --set, recorded with
# their values (no --set for a node: not); every one of them already runs the arm's switches.
for i in ${UNCHANGED[@]+"${UNCHANGED[@]}"}; do
    n="${N_NAME[$i]}"
    [ -z "${ARM_FILE}" ] && [ -n "$(node_sets "${n}")" ] && rec_node "${n}" "$(vals_json "${n}")" "" ""
    [ ! -s "${WORK}/targets.${n}" ] || echo "SWITCHES_CURRENT ${n} $(switch_values "$(a_field "${n}" SWITCH_LINE)")"
done
# ready: the last node back in consensus plus the settle time (MANIFEST-FIELDS.md).
ready="${LAST_PROGRESS:-$(now_utc)}"
ready="$(jq -rn --arg t "${ready}" --argjson s "${SETTLE_SECS}" '$t | fromdateiso8601 + $s | todateiso8601')"
log "arm ${ARM}: ${#APPLIED[@]} node(s) restarted and read back; begin ${BEGIN}; ready ${ready}; recorded in ${REC_FILE}"
arm_ready "${ready}"
jq -c --arg a "${ARM}" --arg b "${BEGIN}" '.param_arms[] | select(.name == $a and .begin == $b)' "${REC_FILE}"
