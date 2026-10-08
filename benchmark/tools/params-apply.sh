#!/usr/bin/env bash
# params-apply.sh — change consensus parameters on a running fleet between sweep arms: one node at
# a time, each one restarted and back in consensus before the next is touched, and the change
# recorded as an arm (manifest.param_arms) so the report knows which values ran when.
#
# Phase A (read-only, every node of the list, up to 5 at once): where the node's parameters.yaml
#   is, its content and sha256, whether the telcoin container runs, its chain id. Any node failing
#   here stops the run before anything changes.
# Validation (local, before any restart): every node's RESULTING values against the node's own
#   startup rules (the same as deploy step 9's, bench-lib.sh bench_node_params_problems), then the
#   plan: per node, key old -> new.
# Phase B (serial; never more than one node down): save the container log as
#   /var/lib/bench-logs/telcoin-pre-arm-<arm>-<UTC>.log.gz (the harness pull collects it), keep
#   parameters.yaml.bak-<UTC>, rewrite the keys in place (`key: value  # bench-override`), restart
#   telcoin, wait until eth_chainId answers and the node's consensus has moved past where it was
#   before the restart, read the file back and print
#     PARAMS_OK <node> max=<ms> min=<ms> batch=<ms> thr=<n> vote=<ms|->
#   The first node that does not come back stops the run: non-zero exit, and the gcloud command to
#   inspect it. Only nodes whose values change are restarted; observers go first.
# Nothing to change (every node already has the values): nothing restarts, and the arm is still
#   recorded (begin = now, no_restart: true) once every node of the arm passes the readback check
#   on the file phase A read and its telcoin container runs.
#
# Usage: params-apply.sh (--nodes <file> | --from-config) --set <all|node>:<key>=<value>[,...] ... --arm <name>
#        params-apply.sh (--nodes <file> | --from-config) --stage-test <node> [--set ...]
#        params-apply.sh (--nodes <file> | --from-config) --close-arm <name>
#        (--help for every option)
# Docs:  benchmark/tools/README.md, section "params-apply".
#
# Standalone: it never sources bench-lib.sh, and with --nodes nothing of the devnet config either.
# Needs: bash (3.2 is enough), perl, awk, jq (recording) and an authenticated gcloud.
set -euo pipefail

readonly SSH_PARALLEL=5
readonly PHASE_A_SECS=120
# Phase B: the log save (gzip of the whole container log), the restart and the health wait.
readonly PHASE_B_SECS=1200
readonly REMOTE_WRAPPER=/opt/telcoin/start-telcoin.sh
readonly REMOTE_LOG_DIR=/var/lib/bench-logs
# <type>:<key>; dur = <int>ms|<int>s, int = positive integer, bool = true|false. The node's
# Parameters at ba43a1f0e (crates/config/src/node.rs). Keep in step with benchmark/config.sh
# BENCH_NODE_PARAM_KEYS (tests/test_params_apply.py compares them).
readonly PARAM_KEYS="dur:max_header_delay dur:min_header_delay dur:vote_timeout dur:max_batch_delay dur:sync_retry_delay int:header_num_of_batches_threshold int:max_header_num_of_batches int:sync_retry_nodes int:max_concurrent_requests bool:allow_private_forward_targets"
readonly TAB=$'\t'
readonly DUR_RE='^[0-9]+(ms|s)$'

usage() {
    cat <<'EOF'
Usage:
  params-apply.sh (--nodes <file> | --from-config) --set <target>:<key>=<value>[,...] [--set ...] --arm <name>
  params-apply.sh (--nodes <file> | --from-config) --stage-test <node> [--set ...]
  params-apply.sh (--nodes <file> | --from-config) --close-arm <name>

Changes consensus parameters on running nodes, one node at a time: read every node (read-only),
validate every node's resulting values, then per node save its container log, rewrite
<datadir>/parameters.yaml, restart telcoin and wait until it is back in consensus. Records the
change as an arm in <results-dir>/manifest.json (param_arms), else in param-arms.json beside the
nodes file.

Nodes:
  --nodes <file>        lines "name zone project role [hostdatadir]" (# comments allowed);
                        role validator|observer; project '-' = --project; hostdatadir = the HOST
                        directory holding parameters.yaml (default: from the node's wrapper)
  --from-config         the benchmark fleet of benchmark/config.sh (needs BENCH_RUN_ID); writes
                        results/<run>/nodes.txt and records into results/<run>/manifest.json
  --validators-only     leave observers out (default: observers are changed too)
  --project <id>        project for nodes-file lines whose project is '-' (with --from-config:
                        instead of the config's PROJECT_ID)

What to change:
  --set <t>:<k>=<v>[,<k>=<v>...]
                        <t> = all, or one node's name (a node's own --set wins over all:).
                        Keys (durations <int>ms or <int>s): max_header_delay min_header_delay
                        vote_timeout max_batch_delay sync_retry_delay; integers:
                        header_num_of_batches_threshold max_header_num_of_batches sync_retry_nodes
                        max_concurrent_requests; boolean: allow_private_forward_targets.
                        gc_depth and basefee_address are fleet-wide (refused here).
  --arm <name>          the arm's name, [a-z0-9-], unique in the record; it names the saved log
                        telcoin-pre-arm-<name>-<UTC>.log.gz on each restarted node. When every
                        node already has the values, nothing restarts and the arm is still
                        recorded (begin = now, no_restart: true)
  --stage-test <node>   read, save the log, rewrite with the CURRENT values, restart and wait on
                        that one node: proves the remote path without changing anything. Run it
                        before the first arm of a fleet. No arm is recorded.
  --close-arm <name>    set the open arm <name>'s end to now (no node is contacted)

Other:
  --results-dir <dir>   where manifest.json is (default with --from-config: results/<run>)
  --dry-run             print every gcloud argv and every remote script; contact nothing
  -h, --help            this text
EOF
}

die() { echo "params-apply: $*" >&2; exit 2; }
fatal() { echo "params-apply: $*" >&2; exit 1; }
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# --- arguments -------------------------------------------------------------------------
NODES_FILE="" FROM_CONFIG=0 ARM="" STAGE="" CLOSE="" VALIDATORS_ONLY=0 DRY=0 PROJECT="" RESULTS_DIR=""
SETS=()
HEALTH_SECS="${PARAMS_APPLY_HEALTH_SECS:-180}"
RETRY_SECS="${PARAMS_APPLY_RETRY_SECS:-10}"

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
        --stage-test) STAGE="${val}" ;;
        --close-arm) CLOSE="${val}" ;;
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
if [ -n "${CLOSE}" ]; then
    MODE=close
    [ "${#SETS[@]}" -eq 0 ] && [ -z "${STAGE}" ] && [ -z "${ARM}" ] || die "--close-arm runs on its own (no --set, --arm or --stage-test)"
elif [ -n "${STAGE}" ]; then
    MODE=stage
else
    MODE=apply
    [ "${#SETS[@]}" -gt 0 ] || die "nothing to do: give --set (with --arm), --stage-test or --close-arm"
    [ -n "${ARM}" ] || die "--set needs --arm <name>"
fi
# An arm name becomes part of a log file name the harness pull and report/provenance.py parse.
for pair in "arm:${ARM}" "close-arm:${CLOSE}"; do
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
command -v perl >/dev/null 2>&1 || die "perl is required (gcloud runs under its alarm)"
if [ "${DRY}" = 0 ] && [ "${MODE}" != stage ]; then
    command -v jq >/dev/null 2>&1 || die "jq is required (it records the arm)"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/params-apply.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/sets"

# --- the node list ---------------------------------------------------------------------
# --from-config: the fleet of benchmark/config.sh, read in a subshell (config.sh admits this
# script by name; its exports, TN_USE_VPN=0 among them, never reach this shell). A dry run writes
# the list into its scratch dir, a real run into results/<run>/nodes.txt.
if [ "${FROM_CONFIG}" = 1 ]; then
    [ -n "${BENCH_RUN_ID:-}" ] || die "--from-config needs BENCH_RUN_ID (the run whose fleet to change)"
    cfg_out="$(
        # shellcheck source=/dev/null
        { source "${REPO_ROOT}/benchmark/config.sh"; } >&2
        printf 'RESULTS=%s\nPROJECT=%s\n' "${BENCH_RESULTS_DIR}" "${PROJECT_ID}"
        for i in "${!INSTANCE_NAMES[@]}"; do
            printf 'NODE=%s %s %s\n' "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "${NODE_ROLES[$i]}"
        done
    )" || die "benchmark/config.sh refused to load (see above)"
    [ -n "${RESULTS_DIR}" ] || RESULTS_DIR="$(printf '%s\n' "${cfg_out}" | sed -n 's/^RESULTS=//p')"
    [ -n "${PROJECT}" ] || PROJECT="$(printf '%s\n' "${cfg_out}" | sed -n 's/^PROJECT=//p')"
    case "${PROJECT}" in ''|*[!a-z0-9.:-]*) die "benchmark/config.sh PROJECT_ID '${PROJECT}' is not a project id" ;; esac
    if [ "${DRY}" = 1 ]; then
        NODES_FILE="${WORK}/nodes.txt"
    else
        mkdir -p "${RESULTS_DIR}"
        NODES_FILE="${RESULTS_DIR}/nodes.txt"
    fi
    {
        echo "# name zone project role [hostdatadir] — written by params-apply.sh --from-config for ${BENCH_RUN_ID}"
        printf '%s\n' "${cfg_out}" | sed -n 's/^NODE=//p' | while read -r n z r; do echo "${n} ${z} ${PROJECT} ${r}"; done
    } > "${NODES_FILE}"
    log "nodes from benchmark/config.sh (${BENCH_RUN_ID}) -> ${NODES_FILE}"
fi
[ -f "${NODES_FILE}" ] && [ -r "${NODES_FILE}" ] || die "cannot read nodes file '${NODES_FILE}'"

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
    for tk in ${PARAM_KEYS}; do [ "${tk#*:}" != "$1" ] || { echo "${tk%%:*}"; return 0; }; done
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
        case "${t}:${v}" in
            :*) die "--set '${spec}': unknown key '${k}' (known: $(printf '%s ' ${PARAM_KEYS} | sed 's/[a-z]*://g'))" ;;
            dur:*) [[ "${v}" =~ ${DUR_RE} ]] || die "--set '${spec}': ${k}=${v} is not <int>ms or <int>s" ;;
            int:*) case "${v}" in *[!0-9]*|0*) die "--set '${spec}': ${k}=${v} is not a positive integer" ;; esac ;;
            bool:true|bool:false) ;;
            bool:*) die "--set '${spec}': ${k}=${v} is not true or false" ;;
        esac
        ! grep -q "^${k}=" "${f}" || die "--set: ${k} is given twice for ${target}"
        printf '%s=%s\n' "${k}" "${v}" >> "${f}"
    done
done

# ${WORK}/sets/merged.<node>: the node's "key=value" lines in PARAM_KEYS order; its own --set wins
# over all:. node_sets <node> prints them.
for n in "${N_NAME[@]}"; do
    awk -v keys="${PARAM_KEYS}" -v all="${WORK}/sets/all" '
        { v = substr($0, index($0, "=") + 1); k = substr($0, 1, index($0, "=") - 1)
          if (FILENAME == all) a[k] = v; else o[k] = v }
        END { n = split(keys, ks, " ")
              for (i = 1; i <= n; i++) { k = ks[i]; sub(/^[a-z]*:/, "", k)
                  if (k in o) print k "=" o[k]; else if (k in a) print k "=" a[k] } }' \
        "${WORK}/sets/all" "${WORK}/sets/node.${n}" > "${WORK}/sets/merged.${n}"
done
node_sets() { cat "${WORK}/sets/merged.$1"; }

# res_build <node> [<current yaml> [nosets]] — ${WORK}/res.<node>: "key<TAB>raw<TAB>ms" for every
# key the node will have: the current file's (raw "(block)" for a secs/nanos block) overlaid with
# its sets (not with nosets: a stage test writes the current values back).
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

# --- the record (manifest.param_arms, else param-arms.json beside the nodes file) -------
if [ -n "${RESULTS_DIR}" ] && [ -f "${RESULTS_DIR}/manifest.json" ]; then
    REC_FILE="${RESULTS_DIR}/manifest.json"
else
    REC_FILE="$(cd "$(dirname "${NODES_FILE}")" && pwd)/param-arms.json"
fi

# rec_jq <jq args...> <filter> — edit the record in place (temp file + rename; created as
# {"param_arms": []} when it is the param-arms.json and does not exist yet).
rec_jq() {
    local tmp
    [ -f "${REC_FILE}" ] || printf '{"param_arms": []}\n' > "${REC_FILE}"
    tmp="$(mktemp "${REC_FILE}.XXXXXX")"
    if jq "$@" "${REC_FILE}" > "${tmp}"; then mv "${tmp}" "${REC_FILE}"; else rm -f "${tmp}"; return 1; fi
}
# rec_count <jq filter over .param_arms> — e.g. how many arms are named <x>; 0 without a record.
rec_count() {
    [ -f "${REC_FILE}" ] || { echo 0; return 0; }
    jq -r --arg a "$1" "[(.param_arms // [])[] | $2] | length" "${REC_FILE}"
}
# vals_json <node> — its --set values as written, {"<key>": "<value>"}.
vals_json() {
    node_sets "$1" | jq -R -s -c 'split("\n") | map(select(length > 0) | capture("^(?<k>[^=]+)=(?<v>.*)$") | {(.k): .v}) | add // {}'
}

if [ "${MODE}" = close ]; then
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ "${DRY}" = 1 ]; then
        log "dry run: would set param_arms[name=${CLOSE}, end=null].end = ${now} in ${REC_FILE}"
        exit 0
    fi
    [ "$(rec_count "${CLOSE}" 'select(.name == $a and .end == null)')" -ge 1 ] \
        || fatal "no open arm named '${CLOSE}' in ${REC_FILE}"
    rec_jq --arg a "${CLOSE}" --arg t "${now}" '.param_arms |= map(if .name == $a and .end == null then .end = $t else . end)'
    log "arm ${CLOSE} closed at ${now} (${REC_FILE})"
    exit 0
fi
if [ "${MODE}" = apply ] && [ "${DRY}" = 0 ] && [ "$(rec_count "${ARM}" 'select(.name == $a)')" -gt 0 ]; then
    fatal "arm '${ARM}' is already recorded in ${REC_FILE}; give this arm a new name"
fi

# --- gcloud (helpers copied from tools/latency-probe.sh: show_argv, ssh_once, iap_ssh, pool;
#     the IAP retry rule is bench-lib.sh bench_iap_scp_down's) --------------------------------
# show_argv <argv...> — one copy-pasteable line, on stderr so a caller's stdout redirect cannot hide it.
show_argv() { { printf '  +'; printf ' %q' "$@"; printf '\n'; } >&2; }

SSH_FLAGS=(--tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=20"
           --ssh-flag="-o StrictHostKeyChecking=accept-new" --ssh-flag="-o LogLevel=ERROR")

# ssh_once <secs> <node-index> <stdin-file> <err-file> — one IAP SSH call running the stdin script
# as root, under an alarm.
ssh_once() {
    local secs="$1" i="$2" input="$3" err="$4"
    if [ "${DRY}" = 1 ]; then
        printf '  [alarm %ss, stdin < %s]' "${secs}" "${input##*/}" >&2
        show_argv gcloud compute ssh "${N_NAME[$i]}" --zone="${N_ZONE[$i]}" --project="${N_PROJ[$i]}" \
            "${SSH_FLAGS[@]}" --command="sudo bash -s"
        return 0
    fi
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
# once. Jobs report through files in ${WORK}; a dry run goes one at a time so its output stays readable.
pool() {
    local max="$1" fn="$2" item
    shift 2
    [ "${DRY}" = 0 ] || max=1
    for item in "$@"; do
        while [ "$(jobs -pr | wc -l)" -ge "${max}" ]; do sleep 1; done
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
    printf 'set -euo pipefail\nNODE=%q\nHD=%q\nROLE=%q\nW=%q\nLOGDIR=%q\n' \
        "${N_NAME[$2]}" "${N_HD[$2]}" "${N_ROLE[$2]}" "${REMOTE_WRAPPER}" "${REMOTE_LOG_DIR}"
}

# remote_common — both phases: P (the parameters file) and small helpers. The datadir rule is
# deploy step 9's (benchmark-deploy.sh postconfig_params): the wrapper's telcoin command has
# --datadir <container path>; the host side of its `-v <host>:<that path>` bind holds the file
# (no bind: a native install, the path itself). The nodes file's hostdatadir wins over both.
remote_common() {
    cat <<'REMOTE'
TAG="${TAG:-PARAMS_FAIL}"
fail() { echo "${TAG} ${NODE} $*"; exit 1; }
note() { echo "PA_NOTE ${NODE} $*"; }
if [ -n "$HD" ]; then
    P="$HD/parameters.yaml"
else
    [ -f "$W" ] || fail "no $W (docker start wrapper) and no hostdatadir in the nodes file"
    D="$(grep -v '^[[:space:]]*#' "$W" | sed -nE 's/.*--datadir[ =]([^[:space:]]+).*/\1/p' | head -1 || true)"
    [ -n "$D" ] || fail "no --datadir in $W"
    H="$(grep -v '^[[:space:]]*#' "$W" | sed -nE "s#.*-v[[:space:]]+([^[:space:]:]+):${D}([:[:space:]].*)?\$#\1#p" | head -1 || true)"
    P="${H:-$D}/parameters.yaml"
fi
[ -f "$P" ] || fail "no $P"
sha256() { { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; } | awk '{ print $1 }'; }
# rpc <method> — the node's JSON-RPC result ("" while it does not answer)
rpc() { { curl -s --max-time 3 -H 'content-type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":[]}" http://127.0.0.1:8545 || true; } | sed -n 's/.*"result":"\([^"]*\)".*/\1/p' || true; }
REMOTE
}

# phase_a_script <node-index> — read-only: the file, its sha256, container state, chain id.
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
echo "PA_YAML_BEGIN"
awk 1 "$P"
echo "PA_YAML_END"
echo "PA_OK ${NODE}"
REMOTE
}

# phase_b_script <node-index> <label> <expected sha256|-> <expected chain id|-> <setp-lines-file>
phase_b_script() {
    remote_head B "$1"
    printf 'LABEL=%q\nEXPECT_SHA=%q\nEXPECT_CHAIN=%q\nWAIT=%q\n' "$2" "$3" "$4" "${HEALTH_SECS}"
    remote_common
    cat <<'REMOTE'
sha="$(sha256 "$P")"
[ "$EXPECT_SHA" = - ] || [ "$sha" = "$EXPECT_SHA" ] || fail "$P changed since the read-only pass (sha256 $sha, read $EXPECT_SHA); nothing done, re-run"
if grep -q '# bench-override$' "$P" && [ ! -f "$P.bak" ]; then fail "$P has bench-override lines but no $P.bak"; fi

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

# 1. the container's log: a restart drops it (docker run --rm). Same file scheme as bench-lib.sh
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

# 2. parameters.yaml, rewritten in place (cat >: owner, mode and inode stay). A copy per change;
#    a file no step 9 or arm has marked yet becomes the .bak deploy step 9 restores from.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$P" "$P.bak-$STAMP" || fail "cannot copy $P to $P.bak-$STAMP"
echo "PA_BACKUP $P.bak-$STAMP"
grep -q '# bench-override$' "$P" || cp -p "$P" "$P.bak" || fail "cannot copy $P to $P.bak"
rfail() { cat "$P.bak-$STAMP" > "$P"; fail "$* (file restored, node not restarted)"; }
# setp <key> <value> — rewrite the top-level `key:` line (append it when absent), marked. From
# benchmark-deploy.sh postconfig_params.
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

# 3. restart; wait until the RPC answers (with the chain id it had) and this node's consensus has
#    moved past where it was before the restart: a validator's own round, an observer's consensus
#    number. An idle chain stays at block 0, so blocks are no measure.
echo "RESTART_AT $(date -u +%Y-%m-%dT%H:%M:%SZ)"
restart_ts="$(date +%s)"
systemctl restart telcoin || fail "systemctl restart telcoin failed"
deadline=$(( restart_ts + WAIT ))
cid=""; how=""; now=""
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
            if [ -n "$now" ] && later "$now" "$pre"; then how="$now"; fi
        fi
    fi
    if [ -n "$cid" ] && [ -n "$how" ]; then break; fi
    sleep 3
done
[ -n "$cid" ] || fail "eth_chainId did not answer on 127.0.0.1:8545 within ${WAIT} s of the restart"
if [ "$ROLE" = validator ]; then what="(epoch round) of its quorum reached/header proposed lines"; else what="consensus number"; fi
[ -n "$how" ] || fail "no consensus progress within ${WAIT} s of the restart: ${what} ${now:-none} since, ${pre:-none} before"
echo "PA_PROGRESS ${what}: ${pre:-none} -> ${how}"

# 4. what the node booted with must be what the file says (else it reads another file), and the
#    readback. pv/ms from benchmark-deploy.sh postconfig_readback.
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
    done
    [ "${bad}" = 0 ] || fatal "phase A failed on the node(s) above; nothing was changed"
fi

# --- validation and plan -------------------------------------------------------------------
# Per node: ${WORK}/w.<node> = the setp lines phase B runs; ${WORK}/chg.<node> = "key old new".
problems="" PLAN=() UNCHANGED=()
for i in "${TARGETS[@]}"; do
    n="${N_NAME[$i]}"
    : > "${WORK}/w.${n}"; : > "${WORK}/chg.${n}"
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
        PLAN+=("${i}")
        continue
    fi
    while IFS= read -r kv; do
        [ -n "${kv}" ] || continue
        k="${kv%%=*}" v="${kv#*=}" old="(not read: dry run)" form=absent
        if [ "${DRY}" = 0 ]; then
            old="(absent)"
            got="$(yaml_get "${WORK}/${n}.yaml" "${k}")"; form="${got%%"${TAB}"*}"
            case "${form}" in scalar) old="${got#*"${TAB}"}" ;; block) old="(secs/nanos block)" ;; esac
        fi
        if [ "${form}" = block ]; then
            problems="${problems}${n}: ${k} is a secs/nanos block in $(a_field "${n}" PARAMS); write it as <int>ms there first"$'\n'
            continue
        fi
        if [ "${form}" = scalar ]; then
            if [ "$(key_type "${k}")" = dur ]; then
                [ "$(to_ms "${old}")" != "$(to_ms "${v}")" ] || continue
            else
                [ "${old}" != "${v}" ] || continue
            fi
        fi
        printf 'setp %s %s\n' "${k}" "${v}" >> "${WORK}/w.${n}"
        printf '%s %s %s\n' "${k}" "${old}" "${v}" >> "${WORK}/chg.${n}"
    done <<< "$(node_sets "${n}")"
    if [ -s "${WORK}/w.${n}" ]; then PLAN+=("${i}"); else UNCHANGED+=("${i}"); fi
    [ "${DRY}" = 1 ] || problems="${problems}$(res_problems "${n}" 1)"$'\n'
done
problems="$(printf '%s' "${problems}" | grep -v '^$' || true)"
[ -z "${problems}" ] || fatal "refused before any change; with these values a node would refuse to start (or the file cannot be rewritten):"$'\n'"$(printf '%s\n' "${problems}" | sed 's/^/  /')"

# Phase B order: observers first (a canary that does not vote), then validators, list order.
ORDER=()
for role in observer validator; do
    for i in ${PLAN[@]+"${PLAN[@]}"}; do [ "${N_ROLE[$i]}" != "${role}" ] || ORDER+=("${i}"); done
done

if [ "${MODE}" = stage ]; then
    log "plan: stage test on ${STAGE}: rewrite with its current values (no change), restart, wait healthy; no arm recorded"
else
    log "plan for arm ${ARM}: ${#ORDER[@]} node(s) to restart one at a time, ${#UNCHANGED[@]} already at these values; record: ${REC_FILE}"
fi
for i in ${ORDER[@]+"${ORDER[@]}"} ${UNCHANGED[@]+"${UNCHANGED[@]}"}; do
    n="${N_NAME[$i]}"
    if [ -s "${WORK}/chg.${n}" ]; then
        printf '  %-24s %-9s %s\n' "${n}" "${N_ROLE[$i]}" "$(awk '{ printf "%s%s %s -> %s", (NR > 1 ? ", " : ""), $1, $2, $3 }' "${WORK}/chg.${n}")"
    elif [ "${MODE}" = stage ] && [ "${DRY}" = 1 ]; then
        printf '  %-24s %-9s %s\n' "${n}" "${N_ROLE[$i]}" "rewrite $(sed 's/^setp //; s/ <current value>//' "${WORK}/w.${n}" | paste -sd, -) with their current values"
    else
        printf '  %-24s %-9s %s\n' "${n}" "${N_ROLE[$i]}" "no change; not restarted"
    fi
done
# --- phase B: one node at a time -------------------------------------------------------------
LABEL="pre-arm-${ARM}"
[ "${MODE}" != stage ] || LABEL="stage-test"
BEGIN="" APPLIED=()

# record_node <node> — the node into this arm; the first one opens it (begin = its restart time)
# and closes the arm open before it (end = this begin).
record_node() {
    [ "${MODE}" = apply ] || return 0
    local n="$1" vals
    vals="$(vals_json "${n}")"
    if [ -z "${BEGIN}" ]; then
        BEGIN="$2"
        rec_jq --arg a "${ARM}" --arg b "${BEGIN}" --arg n "${n}" --argjson v "${vals}" '
            .param_arms = (((.param_arms // []) | map(if .end == null then .end = $b else . end))
                           + [{name: $a, begin: $b, end: null, nodes: {($n): $v}}])'
    else
        rec_jq --arg a "${ARM}" --arg b "${BEGIN}" --arg n "${n}" --argjson v "${vals}" '
            .param_arms |= map(if .name == $a and .begin == $b then .nodes[$n] = $v else . end)'
    fi
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

# Nothing to change: no restart, but the arm is recorded like any other (it opens with begin =
# now, by this machine's clock, and closes the arm open before it), marked no_restart. Every node
# of the arm first passes the readback check on the file phase A read, and must run its container:
# a stopped node does not run these values.
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
        [ "$(a_field "${n}" RUNNING)" = 1 ] \
            || problems="${problems}${n}: the telcoin container is NOT running, so the node does not run these values"$'\n'
        ARM_NODES+=("${n}")
    done
    problems="$(printf '%s' "${problems}" | grep -v '^$' || true)"
    [ -z "${problems}" ] || fatal "arm ${ARM} NOT recorded (nothing was restarted or changed):"$'\n'"$(printf '%s\n' "${problems}" | sed 's/^/  /')"
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    for n in ${ARM_NODES[@]+"${ARM_NODES[@]}"}; do record_node "${n}" "${now}"; done
    rec_jq --arg a "${ARM}" --arg b "${BEGIN}" '.param_arms |= map(if .name == $a and .begin == $b then .no_restart = true else . end)'
    log "arm ${ARM} recorded: 0 node(s) restarted, ${#ARM_NODES[@]} already at these values; begin ${BEGIN} (this machine's clock); recorded in ${REC_FILE}"
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
    log "phase B ${step}/${#ORDER[@]}: ${n} (${N_ROLE[$i]}): save log, rewrite, restart, wait up to ${HEALTH_SECS} s"
    if [ "${DRY}" = 1 ]; then
        echo "----- phase B script for ${n} (stdin of sudo bash -s) -----"
        cat "${WORK}/b.${n}.sh"
        echo "----- end -----"
        iap_ssh "${PHASE_B_SECS}" "${i}" "${WORK}/b.${n}.sh" "${WORK}/b.${n}.err"
        continue
    fi
    set +e
    iap_ssh "${PHASE_B_SECS}" "${i}" "${WORK}/b.${n}.sh" "${WORK}/b.${n}.err" | tee "${WORK}/b.${n}.out" \
        | while IFS= read -r l; do case "${l}" in PARAMS_OK\ *) ;; *) printf '      %s\n' "${l}" ;; esac; done
    rc="${PIPESTATUS[0]}"
    set -e
    restarted="$(sed -n 's/^RESTART_AT //p' "${WORK}/b.${n}.out" | head -1)"
    [ -z "${restarted}" ] || record_node "${n}" "${restarted}"
    okline="$(grep -E "^PARAMS_OK ${n} " "${WORK}/b.${n}.out" | tail -1 || true)"
    why=""
    if [ "${rc}" != 0 ] || [ -z "${okline}" ]; then
        why="$(grep -h '^PARAMS_FAIL ' "${WORK}/b.${n}.out" | head -1 || true)"
        why="${why:-ssh exit ${rc}: $(last_error "${WORK}/b.${n}.err")}"
    elif ! why="$(okline_matches "${n}" "${okline}")"; then
        why="readback ${why}"
    else
        why=""
    fi
    if [ -n "${why}" ]; then
        if [ -n "${restarted}" ] && [ "${MODE}" = apply ]; then
            rec_jq --arg a "${ARM}" --arg b "${BEGIN}" --arg n "${n}" '.param_arms |= map(if .name == $a and .begin == $b then .failed = $n else . end)'
        fi
        P_REMOTE="$(a_field "${n}" PARAMS)"
        BACKUP="$(sed -n 's/^PA_BACKUP //p' "${WORK}/b.${n}.out" | head -1)"
        {
            echo "params-apply: ${n} did not come back: ${why}"
            if [ -n "${restarted}" ]; then echo "  it was restarted at ${restarted} with the new file"; else echo "  it was NOT restarted"; fi
            echo "  later nodes were not touched: $(for j in "${ORDER[@]}"; do printf '%s ' "${N_NAME[$j]}"; done | sed "s/.*${n} //")"
            echo "  inspect:  gcloud compute ssh ${n} --zone=${N_ZONE[$i]} --project=${N_PROJ[$i]} --tunnel-through-iap"
            echo "  on it:    sudo docker logs --tail 200 telcoin; sudo systemctl status telcoin; ls -l ${P_REMOTE}*"
            [ -z "${BACKUP}" ] || echo "  rollback: sudo cp -p ${BACKUP} ${P_REMOTE} && sudo systemctl restart telcoin"
        } >&2
        exit 1
    fi
    echo "${okline}"
    APPLIED+=("${i}")
done

[ "${DRY}" = 0 ] || { log "dry run: nothing was contacted or changed"; exit 0; }
if [ "${MODE}" = stage ]; then
    log "stage test passed on ${STAGE}: log saved, file rewritten unchanged, restarted, back in consensus"
    exit 0
fi
# Nodes the arm's values reach that already had them: in the arm too (no --set for a node: not).
for i in ${UNCHANGED[@]+"${UNCHANGED[@]}"}; do
    [ -z "$(node_sets "${N_NAME[$i]}")" ] || record_node "${N_NAME[$i]}" "${BEGIN}"
done
log "arm ${ARM}: ${#APPLIED[@]} node(s) restarted and healthy; begin ${BEGIN}; recorded in ${REC_FILE}"
jq -c --arg a "${ARM}" --arg b "${BEGIN}" '.param_arms[] | select(.name == $a and .begin == $b)' "${REC_FILE}"
