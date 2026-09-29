#!/usr/bin/env bash
#
# benchmark/bench-lib.sh — shared helpers for benchmark/benchmark-*.sh.
#
# Sources ../devnet-lib.sh with CONFIG_FILE pointed at benchmark/config.sh, so every
# devnet helper (tn_iap_ssh, wait_healthy, tn_secret, ...) runs against the BENCH fleet,
# then refuses to continue unless the profile really is loaded. Scripts must set
# BENCH_RUN_ID (flag/env) before sourcing this file; config.sh enforces it.
#
# Conventions:
#   BENCH_APPLY=1  set by --yes. Without it, bench_run only PRINTS the argv (dry run).
#   Every GCP mutation goes through bench_run, which prints its argv first.

BENCH_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export CONFIG_FILE="${BENCH_LIB_DIR}/config.sh"
# shellcheck source=../devnet-lib.sh
source "${BENCH_LIB_DIR}/../devnet-lib.sh"

if [ "${TN_PROFILE:-}" != "benchmark" ]; then
    echo "❌ bench-lib.sh: TN_PROFILE is '${TN_PROFILE:-}', expected 'benchmark' — refusing to run." >&2
    exit 1
fi
if [ "${TN_SSH_TRANSPORT}" != "iap" ] || [ "${TN_USE_VPN}" != "0" ]; then
    echo "❌ bench-lib.sh: the bench fleet is IAP-only (TN_SSH_TRANSPORT=iap TN_USE_VPN=0)." >&2
    exit 1
fi

BENCH_APPLY="${BENCH_APPLY:-0}"
# Names the benchmark may never create, modify or delete (firewall rules, instances, disks).
BENCH_PROTECTED_RE='^(devnet-|default-|obs-|wg-|allow-)'
# A pull marker counts for this long after its pull (see "pull markers"). A node keeps logging, so
# an older marker no longer covers what is on the node and the node is pulled again. Fixed here,
# not a knob: set unconditionally so the environment cannot stretch it.
BENCH_MARKER_MAX_AGE_SECS=900
export BENCH_TXGEN_BENCH_DIR="${BENCH_TXGEN_REPO}/bench"

# --- logging / execution ----------------------------------------------------------
bench_log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
bench_die() { echo "❌ $*" >&2; exit 1; }
bench_warn() { echo "⚠ $*" >&2; }

# bench_run <argv...> — print the argv (shell-quoted), then execute it only when
# BENCH_APPLY=1. Returns the command's status (0 in dry run).
bench_run() {
    printf '    +'; printf ' %q' "$@"; printf '\n'
    if [ "${BENCH_APPLY}" = "1" ]; then
        "$@"
    else
        echo "      (dry run — not executed)"
    fi
}

# bench_require_tools <bin...>
bench_require_tools() {
    local b missing=0
    for b in "$@"; do
        if command -v "${b}" >/dev/null 2>&1; then echo "    ✓ ${b}"; else echo "    ✗ ${b} not on PATH" >&2; missing=1; fi
    done
    [ "${missing}" -eq 0 ]
}

# --- name guards ------------------------------------------------------------------
# bench_is_protected <name> — 0 if the name belongs to devnet / shared infrastructure.
bench_is_protected() { printf '%s' "$1" | grep -Eq "${BENCH_PROTECTED_RE}"; }

# bench_assert_bench_name <kind> <name> — die unless ^bench- and not protected.
bench_assert_bench_name() {
    case "$2" in bench-*) ;; *) bench_die "$1 '$2' does not start with bench- — refusing." ;; esac
    if bench_is_protected "$2"; then bench_die "$1 '$2' matches the protected pattern ${BENCH_PROTECTED_RE}."; fi
}

# bench_in_list <needle> <hay...>
bench_in_list() { local n="$1" h; shift; for h in "$@"; do [ "${h}" = "${n}" ] && return 0; done; return 1; }

# bench_index_of <instance> — index into INSTANCE_NAMES ("" + rc 1 if absent).
bench_index_of() {
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        [ "${INSTANCE_NAMES[$i]}" = "$1" ] && { printf '%s' "$i"; return 0; }
    done
    return 1
}

# bench_devnet_denylist — the instance names devnet owns, from a CLEAN ../config.sh in a
# subshell (no CONFIG_FILE, so no bench overrides), plus the devnet singletons.
bench_devnet_denylist() {
    env -u CONFIG_FILE -u TN_PROFILE bash -c 'source "$1" >/dev/null 2>&1 || exit 1; printf "%s\n" "${INSTANCE_NAMES[@]}"' _ "${REPO_ROOT}/config.sh"
    printf '%s\n' obs-devnet txgen-devnet devnet-indexer
}

# --- time -------------------------------------------------------------------------
bench_now_unix() { date -u +%s; }
bench_now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
bench_iso_from_unix() { date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }

# --- results + manifest -----------------------------------------------------------
bench_manifest() { printf '%s' "${BENCH_RESULTS_DIR}/manifest.json"; }

# bench_manifest_init — write the tn-bench-manifest/v1 skeleton (never overwrites, so a
# --from resume keeps the timestamps already recorded).
bench_manifest_init() {
    local f; f="$(bench_manifest)"
    mkdir -p "${BENCH_RESULTS_DIR}"
    if [ -f "${f}" ]; then echo "    manifest exists: ${f} (kept)"; return 0; fi
    jq -n \
        --arg run "${BENCH_RUN_ID}" --arg fleet "${BENCH_FLEET}" --arg mt "${MACHINE_TYPE}" \
        --arg ds "${NODE_DISK_SIZE}" --arg dt "${NODE_DISK_TYPE}" --arg cid "${CHAIN_ID}" \
        --arg diops "${NODE_DISK_IOPS}" --arg dtput "${NODE_DISK_THROUGHPUT}" \
        --arg ep "${EPOCH_DURATION_SECS}" --arg di "${DOCKER_IMAGE}" --arg ti "${BENCH_TXGEN_IMAGE}" \
        --arg p "${PROJECT_ID}" --arg g "${BENCH_GRAFANA_URL}" --arg uid "${BENCH_PROM_DATASOURCE_UID}" \
        --arg nl "${BENCH_PROM_NETWORK_LABEL}" --arg now "$(bench_now_iso)" '
        def num_or_null: if . == "" then null else tonumber end;
        {schema: "tn-bench-manifest/v1", run_id: $run, fleet: $fleet, machine_type: $mt,
         node_disk: {size_gb: ($ds|tonumber), type: $dt, provisioned_iops: ($diops|num_or_null),
                     provisioned_throughput: ($dtput|num_or_null)}, chain_id: ($cid|tonumber),
         epoch_duration_secs: ($ep|tonumber), docker_image: $di, txgen_image: $ti, project: $p,
         prometheus: {grafana_url: $g, datasource_uid: $uid, network_label: $nl},
         timestamps: {deploy_start: $now}, phases: [], chaos: [], instances: [], blasters: [],
         abort: null, notes: []}' > "${f}"
    echo "    ✓ manifest initialised: ${f}"
}

# bench_manifest_jq <jq-args...> <filter> — edit the manifest in place (atomic). No-op
# (with a note) when the manifest does not exist yet, e.g. in a dry run.
bench_manifest_jq() {
    local f tmp; f="$(bench_manifest)"
    if [ ! -f "${f}" ]; then echo "      (no manifest yet — skipped manifest update)"; return 0; fi
    tmp="$(mktemp "${f}.XXXXXX")"
    if jq "$@" "${f}" > "${tmp}"; then mv "${tmp}" "${f}"; else rm -f "${tmp}"; return 1; fi
}

# bench_manifest_ts <key> [iso] — timestamps[key] = iso (default now).
bench_manifest_ts() { bench_manifest_jq --arg k "$1" --arg v "${2:-$(bench_now_iso)}" '.timestamps[$k] = $v'; }

# bench_manifest_note <text>
bench_manifest_note() { bench_manifest_jq --arg n "$1" '.notes += [$n]'; }

# --- GCP reads ----------------------------------------------------------------------
# bench_instance_json <inst> <zone> — describe JSON ("" if absent).
bench_instance_json() {
    gcloud compute instances describe "$1" --zone="$2" --project="${PROJECT_ID}" --format=json 2>/dev/null || true
}

# bench_machine_shape <machine-type> <zone> — "<vcpus> <memory_mb>".
bench_machine_shape() {
    case "$1" in
        *-custom-*-*)
            local rest="${1#*-custom-}"
            printf '%s %s' "${rest%%-*}" "${rest##*-}" ;;
        *)
            gcloud compute machine-types describe "$1" --zone="$2" --project="${PROJECT_ID}" \
                --format='value(guestCpus,memoryMb)' 2>/dev/null | tr '\t' ' ' ;;
    esac
}

# bench_serial <inst> <zone> — the instance's serial console (port 1) via the REST API.
# No SSH/IAP involved, so it is safe to poll (still keep >= BENCH_POLL_SECS between rounds).
bench_serial() {
    gcloud compute instances get-serial-port-output "$1" --zone="$2" --project="${PROJECT_ID}" 2>/dev/null || true
}

# bench_serial_last <inst> <zone> <token> — the last serial line containing <token>.
bench_serial_last() {
    local out; out="$(bench_serial "$1" "$2")"
    printf '%s\n' "${out}" | grep -F -- "$3" | tail -1 || true
}

# bench_serial_wait <inst> <zone> <marker> <timeout-secs> <poll-secs> — capture-then-match
# (no `| grep -q`: it would SIGPIPE the serial stream under pipefail; devnet-deploy.sh step 3).
bench_serial_wait() {
    local inst="$1" zone="$2" marker="$3" timeout="$4" poll="$5" waited=0 out
    while [ "${waited}" -lt "${timeout}" ]; do
        out="$(bench_serial "${inst}" "${zone}")"
        if [[ "${out}" == *"${marker}"* ]]; then
            echo "      ✓ ${inst}: '${marker}' (after ${waited}s)"
            return 0
        fi
        sleep "${poll}"
        waited=$((waited + poll))
        echo "      …${inst} waiting for '${marker}' (${waited}s/${timeout}s)"
    done
    echo "      ❌ ${inst}: '${marker}' not seen within ${timeout}s" >&2
    return 1
}

# bench_iap_scp_down <inst> <zone> <remote-src> <local-dest> (IAP; remote -> local)
bench_iap_scp_down() {
    gcloud compute scp "$1:$3" "$4" --zone="$2" --project="${PROJECT_ID}" \
        --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
}

# --- node logs ---------------------------------------------------------------------
# Nodes run `docker run --rm`: a killed or restarted container takes its log with it. Steps
# that stop a container save its log here first (bench_save_node_log); the pull collects them.
BENCH_NODE_LOG_DIR="/var/lib/bench-logs"

# bench_save_node_log <node-index> <label> — on node INSTANCE_NAMES[<node-index>], write the
# current container's unfiltered log to ${BENCH_NODE_LOG_DIR}/telcoin-<label>-<UTC stamp>.log.gz.
# Call it before anything kills, restarts or pauses the container. <label> is [a-z0-9-].
# Non-zero when there is no telcoin container, its log is empty, or the file did not land.
# On the node it writes nothing when the container is missing, never replaces a file, and never
# deletes: a failed write leaves a dot-named temp file that no pull collects. Dry run: prints only.
bench_save_node_log() {
    local idx="${1:-}" label="${2:-}" inst zone name cmd script
    case "${idx}" in ''|*[!0-9]*) echo "❌ bench_save_node_log <node-index> <label>: bad index '${idx}'" >&2; return 1 ;; esac
    inst="${INSTANCE_NAMES[$idx]:-}"; zone="${ZONES[$idx]:-}"
    [ -n "${inst}" ] && [ -n "${zone}" ] || { echo "❌ bench_save_node_log: no node at index ${idx}" >&2; return 1; }
    # Spelled out, not a-z: a range can match capitals under some locales.
    case "${label}" in
        ''|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
            echo "❌ bench_save_node_log: label '${label}' must be non-empty [a-z0-9-]" >&2; return 1 ;;
    esac
    name="telcoin-${label}-$(date -u +%Y%m%dT%H%M%SZ).log.gz"
    # Runs as root on the node; $1 = dir, $2 = file name. gzip of no input is still 20 bytes,
    # so emptiness is checked on the decompressed first byte, then -s on the final file.
    # shellcheck disable=SC2016  # expanded by the remote bash
    script='d=$1; f=$1/$2; docker container inspect telcoin >/dev/null || exit 1; mkdir -p "$d" || exit 1; if [ -e "$f" ]; then echo "$f exists already" >&2; exit 1; fi; p=$(mktemp "$d/.$2.XXXXXX") || exit 1; docker logs telcoin 2>&1 | gzip -1 > "$p" || exit 1; [ "$(gzip -cd "$p" | head -c 1 | wc -c)" -eq 1 ] || { echo "the telcoin container log is empty" >&2; exit 1; }; mv -n "$p" "$f" && [ ! -e "$p" ] && [ -s "$f" ]'
    cmd="sudo bash -o pipefail -c '${script}' _ ${BENCH_NODE_LOG_DIR} ${name}"
    printf '    +'; printf ' %q' tn_iap_ssh "${inst}" "${zone}" "${cmd}"; printf '\n'
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    if ! tn_iap_ssh "${inst}" "${zone}" "${cmd}"; then
        echo "      ✗ ${inst}: container log NOT saved (no telcoin container, empty log, or ssh failed)" >&2
        return 1
    fi
    echo "      ✓ ${inst}: container log saved on the node as ${BENCH_NODE_LOG_DIR}/${name}"
}

# The node's systemd unit appends the container's stdout and stderr to these files
# (setup-node.sh: StandardOutput=append:, StandardError=append:). They outlive a container
# restart, not the VM. Pairs of <stream>:<node file>; the pull names the copy <inst>-unit-<stream>.log.gz.
BENCH_NODE_UNIT_LOGS="stdout:/var/log/telcoin/telcoin.log stderr:/var/log/telcoin/telcoin-error.log"

# _bench_pull_node_log <inst> <zone> <remote-cmd> <out> — <remote-cmd>'s stdout over IAP ssh
# into a temp file beside <out>, renamed to <out> once complete. rc 0 = landed; 1 = nothing to
# copy (no telcoin container, or its log is empty; normal); 2 = the transfer failed. Only a
# landed log is kept; otherwise the temp file is dropped.
_bench_pull_node_log() {
    local tmp
    tmp="$(mktemp "$4.XXXXXX")" || return 2
    if ! tn_iap_ssh "$1" "$2" "$3" > "${tmp}"; then
        rm -f "${tmp}"
        echo "      ✗ $1: current-container log: ssh or docker on the node failed" >&2
        return 2
    fi
    # gzip of no input is still 20 bytes, so judge the decompressed first byte.
    if [ "$(gzip -cd "${tmp}" 2>/dev/null | head -c 1 | wc -c)" -ne 1 ]; then
        rm -f "${tmp}"
        echo "      - $1: no current-container log (no telcoin container, or its log is empty)"
        return 1
    fi
    if [ -s "$4" ]; then
        echo "      ✗ $1: $4 appeared during the pull; this copy is ${tmp}" >&2
        return 2
    fi
    mv "${tmp}" "$4" || return 2
    echo "      ✓ $1 -> $4"
}

# _bench_unit_log_cmd <node-file> — remote command that streams <node-file> gzipped on the
# node; no output (rc 0) when the file is missing or empty. It only reads.
_bench_unit_log_cmd() {
    # shellcheck disable=SC2016  # expanded by the remote bash
    printf "sudo bash -c '%s' _ %s" '[ -s "$1" ] || exit 0; gzip -1 < "$1"' "$1"
}

# _bench_pull_unit_log <inst> <zone> <node-file> <out> — one of BENCH_NODE_UNIT_LOGS, gzipped on
# the node as it streams, into a temp file beside <out>, renamed to <out>. A non-empty <out> is
# kept and no ssh is made. rc 0 = landed or already here; 1 = missing or empty on the node
# (normal); 2 = the transfer failed.
_bench_pull_unit_log() {
    local tmp
    if [ -s "$4" ]; then return 0; fi
    tmp="$(mktemp "$4.XXXXXX")" || return 2
    if ! tn_iap_ssh "$1" "$2" "$(_bench_unit_log_cmd "$3")" > "${tmp}"; then
        rm -f "${tmp}"
        echo "      ✗ $1: $3: ssh or gzip on the node failed" >&2
        return 2
    fi
    if [ ! -s "${tmp}" ]; then
        rm -f "${tmp}"
        echo "      - $1: $3 is missing or empty on the node"
        return 1
    fi
    if [ -s "$4" ]; then
        echo "      ✗ $1: $4 appeared during the pull; this copy is ${tmp}" >&2
        return 2
    fi
    mv "${tmp}" "$4" || return 2
    echo "      ✓ $1 -> $4"
}

# _bench_log_name_ok <name> — 0 for a plain *.log.gz file name: [A-Za-z0-9._-] only, first
# character alphanumeric. Such a name is safe unquoted on a command line and literal to tar.
_bench_log_name_ok() {
    case "$1" in *[!A-Za-z0-9._-]*) return 1 ;; [A-Za-z0-9]*.log.gz) return 0 ;; *) return 1 ;; esac
}

# _bench_saved_log_cmd_skip [<name>...] — remote command that streams a tar of the node's
# ${BENCH_NODE_LOG_DIR}/*.log.gz minus the given file names (passed as arguments; a name that is
# not a plain *.log.gz name is dropped). No saved logs = empty output, rc 0.
_bench_saved_log_cmd_skip() {
    local n have="" script
    for n in "$@"; do _bench_log_name_ok "${n}" && have="${have} ${n}"; done
    # shellcheck disable=SC2016  # expanded by the remote bash
    script='d=$1; shift; [ -d "$d" ] || exit 0; cd "$d" || exit 1; shopt -s nullglob; keep=(); for f in *.log.gz; do for s in "$@"; do [ "$f" = "$s" ] && continue 2; done; keep+=("$f"); done; [ ${#keep[@]} -eq 0 ] || tar -cf - -- "${keep[@]}"'
    printf "sudo bash -o pipefail -c '%s' _ %s%s" "${script}" "${BENCH_NODE_LOG_DIR}" "${have}"
}

# _bench_saved_log_cmd <dest> <inst> — _bench_saved_log_cmd_skip minus every name <dest> already
# holds non-empty for <inst>: the plan's command. The pull itself skips only the names a marker of
# the instance vouches for (_bench_pull_node), so a file an earlier instance left is sent again.
_bench_saved_log_cmd() {
    local f n have=()
    for f in "$1/$2"-*.log.gz; do
        [ -s "${f}" ] || continue
        n="${f##*/}"; have+=("${n#"$2"-}")
    done
    _bench_saved_log_cmd_skip "${have[@]+"${have[@]}"}"
}

# _bench_unstamp_names [<file>...] — each file name, minus its directory and minus a trailing
# -<UTC stamp> before .log.gz: the name a copy stamped because its name was taken would have had.
# One per line; other names unchanged.
_bench_unstamp_names() {
    local n b
    for n in "$@"; do
        n="${n##*/}"; b="${n%.log.gz}"
        case "${b##*-}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) n="${b%-*}.log.gz" ;; esac
        printf '%s\n' "${n}"
    done
}

# _bench_log_sources_of <inst> [<file>...] — what those logs of <inst> are, on one line, e.g.
# "current-container log, 2 saved log(s), unit stdout, unit stderr" (only those present). Judged
# by name (a stamped copy by its unstamped name): <inst>-telcoin.log.gz is the current
# container's, <inst>-unit-<stream>.log.gz a unit file, any other a saved log. Non-zero and no
# output for none.
_bench_log_sources_of() {
    local inst="$1" n cur=0 saved=0 uo=0 ue=0 got=""
    shift
    for n in $(_bench_unstamp_names "$@"); do
        case "${n#"${inst}"-}" in
            telcoin.log.gz) cur=1 ;;
            unit-stdout.log.gz) uo=1 ;;
            unit-stderr.log.gz) ue=1 ;;
            *) saved=$((saved + 1)) ;;
        esac
    done
    [ "${cur}" -eq 0 ] || got="current-container log"
    [ "${saved}" -eq 0 ] || got="${got:+${got}, }${saved} saved log(s)"
    [ "${uo}" -eq 0 ] || got="${got:+${got}, }unit stdout"
    [ "${ue}" -eq 0 ] || got="${got:+${got}, }unit stderr"
    [ -n "${got}" ] && printf '%s\n' "${got}"
}

# _bench_logs_here <dest> <inst> — the plain names of the non-empty <inst>-*.log.gz files in
# <dest>, one per line. Reads <dest> only.
_bench_logs_here() {
    local f
    for f in "$1/$2"-*.log.gz; do
        [ -f "${f}" ] && [ -s "${f}" ] && _bench_log_name_ok "${f##*/}" && printf '%s\n' "${f##*/}"
    done
    return 0
}

# bench_node_log_sources <dest> <inst> — which logs of <inst> <dest> holds, whoever left them (see
# _bench_log_sources_of). Non-zero and no output when it holds none. Reads <dest> only.
bench_node_log_sources() {
    # shellcheck disable=SC2046  # plain file names, one per line
    _bench_log_sources_of "$2" $(_bench_logs_here "$1" "$2")
}

# _bench_in_lines <needle> <lines> — 0 when <needle> is one of the newline-separated <lines>.
_bench_in_lines() { case $'\n'"$2"$'\n' in *$'\n'"$1"$'\n'*) return 0 ;; esac; return 1; }

# _bench_instance_ident <inst> <zone> — "<numeric id> <creationTimestamp>" of the instance that
# holds the name <inst> now; no output when it cannot be looked up. A read (instances describe).
_bench_instance_ident() {
    bench_instance_json "$1" "$2" \
        | jq -r 'select((.id // "" | tostring) | test("^[0-9]+$")) | "\(.id) \(.creationTimestamp // "?")"' 2>/dev/null || true
}

# --- pull markers ------------------------------------------------------------------------
# Every fleet reuses the instance names, so a marker binds the logs to one instance, not to a
# name. A node that passes a pull gets <dest>/<inst>.pulled, or <inst>.pulled-<UTC stamp> when
# that name is taken (no marker is ever replaced or deleted):
#   tn-bench-pulled/v2
#   instance <inst>
#   id <numeric instance id>
#   created <creationTimestamp>
#   run <BENCH_RUN_ID>
#   pulled <UTC time>
#   sources <what the logs are>
#   file <bytes> <file name>        one line per log in <dest> it vouches for
#   end
# A marker counts only while its id is the id of the instance that holds the name now, every
# file it lists is here at the listed size, and its pull is at most BENCH_MARKER_MAX_AGE_SECS old
# (after that the node has logged more than the marker covers: it is pulled again, and the new
# copies land beside the old ones). The pull never rewrites a file, so name + size is
# enough to tell this instance's logs from a file of the same name an earlier instance left or a
# copy cut short; a checksum would add a read of every log for no case the tooling can produce.
# Anything else (the older one-line format, another id, a file gone or resized, a partial or
# unreadable marker, a stale or future pull time) counts as no marker: the node is pulled again.
BENCH_PULL_MARKER_V="tn-bench-pulled/v2"

# _bench_marker_verdict <marker> <dest> <inst> <id> — one line: "accepted — ..." or "not accepted
# — <why>", for the instance <id> that holds <inst> now. rc 0 = accepted. Reads only.
_bench_marker_verdict() {
    local m="$1" d="$2" inst="$3" want="$4" head="" k a b ln=0 end=0 mi="" mid="" mc="" mr="" mp="" files="" bad="" s nf=0
    if [ ! -f "${m}" ] || [ ! -r "${m}" ]; then echo "not accepted — not a readable file"; return 1; fi
    IFS= read -r head < "${m}" || true
    if [ "${head}" != "${BENCH_PULL_MARKER_V}" ]; then echo "not accepted — older format, names no instance id"; return 1; fi
    while IFS=' ' read -r k a b; do
        ln=$((ln + 1))
        [ "${ln}" -gt 1 ] || continue
        if [ "${end}" -eq 1 ]; then bad="text after its end line"; break; fi
        case "${k}" in
            instance) mi="${a}" ;;
            id) mid="${a}" ;;
            created) mc="${a}" ;;
            run) mr="${a}" ;;
            pulled) mp="${a}" ;;
            sources) ;;
            file) files="${files}${a} ${b}"$'\n' ;;
            end) end=1 ;;
            *) bad="unrecognised line '${k}'"; break ;;
        esac
    done < "${m}"
    if [ -n "${bad}" ]; then echo "not accepted — ${bad}"; return 1; fi
    if [ "${end}" -ne 1 ]; then echo "not accepted — incomplete (no end line)"; return 1; fi
    if [ "${mi}" != "${inst}" ]; then echo "not accepted — it is for '${mi}'"; return 1; fi
    case "${mid}" in ''|*[!0-9]*) echo "not accepted — no valid instance id in it"; return 1 ;; esac
    case "${want}" in ''|*[!0-9]*) echo "not accepted — the id of the ${inst} that exists now is unknown (marker: ${mid})"; return 1 ;; esac
    if [ "${mid}" != "${want}" ]; then
        echo "not accepted — it is for instance ${mid} (created ${mc:-?}); ${inst} now is instance ${want}"
        return 1
    fi
    # Fresh only: pulled within BENCH_MARKER_MAX_AGE_SECS, and not in the future. The fixed-width
    # UTC form compares as a 14-digit number.
    local now since
    case "${mp}" in
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
        *) echo "not accepted — no valid pull time in it"; return 1 ;;
    esac
    now="$(bench_now_unix)"
    if ! since="$(bench_iso_from_unix $((now - BENCH_MARKER_MAX_AGE_SECS)))" || ! now="$(bench_iso_from_unix "${now}")"; then
        echo "not accepted — the current time could not be read"; return 1
    fi
    if [ "${mp//[!0-9]/}" -lt "${since//[!0-9]/}" ]; then
        echo "not accepted — pulled ${mp}, more than $((BENCH_MARKER_MAX_AGE_SECS / 60)) min ago; the node has logged since"
        return 1
    fi
    if [ "${mp//[!0-9]/}" -gt "${now//[!0-9]/}" ]; then echo "not accepted — pulled ${mp}, which is in the future"; return 1; fi
    while IFS=' ' read -r a b; do
        [ -n "${a}${b}" ] || continue
        case "${a}" in ''|*[!0-9]*|0) echo "not accepted — bad size '${a}' for '${b}'"; return 1 ;; esac
        case "${b}" in "${inst}"-*.log.gz) ;; *) echo "not accepted — lists '${b}', not a log of ${inst}"; return 1 ;; esac
        _bench_log_name_ok "${b}" || { echo "not accepted — bad file name '${b}'"; return 1; }
        if [ ! -f "${d}/${b}" ]; then echo "not accepted — ${b} is gone"; return 1; fi
        s="$(wc -c < "${d}/${b}" | tr -d ' ')" || s="?"
        if [ "${s}" != "${a}" ]; then echo "not accepted — ${b} is ${s} bytes, the marker says ${a}"; return 1; fi
        nf=$((nf + 1))
    done <<< "${files}"
    if [ "${nf}" -eq 0 ]; then echo "not accepted — it lists no log"; return 1; fi
    echo "accepted — instance ${mid} (created ${mc:-?}), run ${mr:-?}, pulled ${mp:-?}; its ${nf} log(s) are here at their recorded sizes"
}

# bench_node_markers_report <dest> <inst> <id> — one line per marker of <inst> in <dest> saying
# whether it vouches for the logs of instance <id> (the one that holds <inst> now) and why.
# rc 0 when one does. Reads <dest> only.
bench_node_markers_report() {
    local m v rc=1 n=0
    for m in "$1/$2.pulled" "$1/$2".pulled-*; do
        [ -e "${m}" ] || [ -L "${m}" ] || continue
        n=$((n + 1))
        if v="$(_bench_marker_verdict "${m}" "$1" "$2" "$3")"; then rc=0; fi
        echo "        marker ${m##*/}: ${v}"
    done
    [ "${n}" -gt 0 ] || echo "        no marker"
    return "${rc}"
}

# bench_node_marker_ok <dest> <inst> <id> — bench_node_markers_report without the report.
bench_node_marker_ok() { bench_node_markers_report "$@" > /dev/null; }

# bench_node_vouched_logs <dest> <inst> <id> — the file names the accepted markers of <inst> in
# <dest> vouch for, one per line (none when no marker is accepted). Reads <dest> only.
bench_node_vouched_logs() {
    local m
    for m in "$1/$2.pulled" "$1/$2".pulled-*; do
        [ -f "${m}" ] || continue
        _bench_marker_verdict "${m}" "$1" "$2" "$3" > /dev/null || continue
        sed -n 's/^file [0-9][0-9]* //p' "${m}"
    done | LC_ALL=C sort -u
}

# bench_node_saved_sources <dest> <inst> <id> — _bench_log_sources_of the vouched logs.
bench_node_saved_sources() {
    # shellcheck disable=SC2046  # plain file names, one per line
    _bench_log_sources_of "$2" $(bench_node_vouched_logs "$1" "$2" "$3")
}

# bench_node_logs_saved <dest> <inst> — 0 when a marker in <dest> vouches for the logs of the
# instance that holds the name <inst> now (its id looked up; see "pull markers").
bench_node_logs_saved() {
    local i ident
    i="$(bench_index_of "$2")" || return 1
    ident="$(_bench_instance_ident "$2" "${ZONES[$i]}")"
    bench_node_marker_ok "$1" "$2" "${ident%% *}"
}

# _bench_write_marker <dest> <inst> <id> <created> <sources> <file>... — write the marker (see
# "pull markers") through a dot-named temp file and a no-clobber rename to <inst>.pulled, or to
# <inst>.pulled-<UTC stamp> when that name is taken. Prints the marker's path. A failed write
# leaves the dot-named temp file, which no reader looks at.
_bench_write_marker() {
    local d="$1" inst="$2" id="$3" ct="$4" src="$5" tmp m f s
    shift 5
    tmp="$(mktemp "${d}/.${inst}.pulled.XXXXXX")" || return 1
    {
        printf '%s\n' "${BENCH_PULL_MARKER_V}" "instance ${inst}" "id ${id}" "created ${ct}" \
            "run ${BENCH_RUN_ID}" "pulled $(bench_now_iso)" "sources ${src}"
        for f in "$@"; do
            s="$(wc -c < "${d}/${f}" | tr -d ' ')" || return 1
            printf 'file %s %s\n' "${s}" "${f}"
        done
        echo end
    } >> "${tmp}" || return 1
    m="${d}/${inst}.pulled"
    [ ! -e "${m}" ] || m="${d}/${inst}.pulled-$(date -u +%Y%m%dT%H%M%SZ)"
    if mv -n "${tmp}" "${m}" && [ ! -e "${tmp}" ]; then printf '%s\n' "${m}"; return 0; fi
    echo "      ✗ ${inst}: marker not written: ${m} exists (the new one is ${tmp})" >&2
    return 1
}

# _bench_pull_saved_logs <inst> <zone> <remote-cmd> <dest> — one ssh session streams a tar of
# the node's saved logs into a temp file; each member lands as <dest>/<inst>-<file name>
# through a temp file and a rename, never over a non-empty file. A member whose name is taken
# (the node was not told to skip it: no marker of this instance vouches for the file here) lands
# beside it as <inst>-<file name minus .log.gz>-<UTC stamp>.log.gz. Non-zero if the ssh, the tar
# or any member failed. A node without saved logs is normal (rc 0).
_bench_pull_saved_logs() {
    local tarf list n out tmp rc=0
    tarf="$(mktemp "$4/$1-saved.XXXXXX")" || return 1
    if ! tn_iap_ssh "$1" "$2" "$3" > "${tarf}"; then
        rm -f "${tarf}"
        echo "      ✗ $1: saved logs: ssh or tar on the node failed" >&2
        return 1
    fi
    if [ ! -s "${tarf}" ]; then rm -f "${tarf}"; return 0; fi
    if ! list="$(tar -tf "${tarf}")"; then
        rm -f "${tarf}"
        echo "      ✗ $1: saved logs: the stream is not a readable tar" >&2
        return 1
    fi
    while IFS= read -r n; do
        [ -n "${n}" ] || continue
        if ! _bench_log_name_ok "${n}"; then
            echo "      ✗ $1: saved logs: unexpected tar member '${n}' — not extracted" >&2; rc=1; continue
        fi
        out="$4/$1-${n}"
        if [ -s "${out}" ]; then
            out="$4/$1-${n%.log.gz}-$(date -u +%Y%m%dT%H%M%SZ).log.gz"
            echo "      - $1: $4/$1-${n} is here but not vouched for by this instance — kept; this copy -> ${out}"
            if [ -e "${out}" ]; then echo "      ✗ $1: ${out} exists too — saved log ${n} not copied" >&2; rc=1; continue; fi
        fi
        tmp="$(mktemp "${out}.XXXXXX")" || { rc=1; continue; }
        if ! tar -xOf "${tarf}" "${n}" > "${tmp}" || [ ! -s "${tmp}" ]; then
            rm -f "${tmp}"
            echo "      ✗ $1: saved log ${n} could not be extracted" >&2; rc=1; continue
        fi
        if [ -s "${out}" ]; then
            echo "      ✗ $1: ${out} appeared during the pull; this copy is ${tmp}" >&2; rc=1; continue
        fi
        if mv "${tmp}" "${out}"; then echo "      ✓ $1 -> ${out}"
        else echo "      ✗ $1: saved log ${n} not renamed into ${out}; this copy is ${tmp}" >&2; rc=1; fi
    done <<< "${list}"
    rm -f "${tarf}"
    return "${rc}"
}

# _bench_pull_node <inst> <zone> <log-cmd> <out> <saved-cmd> <dest> — one node, three sources:
# its current container's log, its saved logs, the unit's append files. The instance's id is
# looked up before and after; no id, or a different one after, fails the node. Only logs this
# pull wrote, or logs an accepted marker of this instance vouches for, count: a file an earlier
# instance of the same name left is kept, never counts, and this pull's copy of that source
# lands beside it under a stamped name (<saved-cmd>, the plan's command, is sent with its skip
# list narrowed to the vouched names). The node passes when no transfer failed and at least one
# log counts; only then does it get a marker (see "pull markers"). It says what it got.
_bench_pull_node() {
    local inst="$1" zone="$2" dest="$6" ident ident2 id vouched vbase before after n p r uout skip=() new="" stale=0 got m xfer=0
    ident="$(_bench_instance_ident "${inst}" "${zone}")"
    if [ -z "${ident}" ]; then
        echo "      ✗ ${inst}: its instance id could not be looked up — not pulled (the marker must name it)" >&2
        return 1
    fi
    id="${ident%% *}"
    vouched="$(bench_node_vouched_logs "${dest}" "${inst}" "${id}")"
    # shellcheck disable=SC2086  # plain file names
    vbase="$(_bench_unstamp_names ${vouched})"   # a stamped copy stands for the node's file of that name
    before="$(_bench_logs_here "${dest}" "${inst}")"
    r=0; _bench_pull_node_log "${inst}" "${zone}" "$3" "$4" || r=$?
    [ "${r}" -le 1 ] || xfer=1
    for n in ${vouched} ${vbase}; do skip+=("${n#"${inst}"-}"); done
    _bench_pull_saved_logs "${inst}" "${zone}" "$(_bench_saved_log_cmd_skip "${skip[@]+"${skip[@]}"}")" "${dest}" || xfer=1
    for p in ${BENCH_NODE_UNIT_LOGS}; do
        uout="${dest}/${inst}-unit-${p%%:*}.log.gz"
        _bench_in_lines "${uout##*/}" "${vbase}" && continue   # this instance's copy: not copied again
        [ ! -s "${uout}" ] || uout="${dest}/${inst}-unit-${p%%:*}-$(date -u +%Y%m%dT%H%M%SZ).log.gz"
        r=0; _bench_pull_unit_log "${inst}" "${zone}" "${p#*:}" "${uout}" || r=$?
        [ "${r}" -le 1 ] || xfer=1
    done
    after="$(_bench_logs_here "${dest}" "${inst}")"
    for n in ${after}; do
        if ! _bench_in_lines "${n}" "${before}"; then new="${new} ${n}"
        elif ! _bench_in_lines "${n}" "${vouched}"; then stale=$((stale + 1)); fi
    done
    vouched="$(bench_node_vouched_logs "${dest}" "${inst}" "${id}")"   # re-read: still here, same sizes
    # shellcheck disable=SC2086  # plain file names
    got="$(_bench_log_sources_of "${inst}" ${new} ${vouched})" || got=""
    if [ "${xfer}" -ne 0 ]; then
        echo "      ✗ ${inst}: a transfer failed (see above) — got so far: ${got:-nothing}" >&2
        return 1
    fi
    if [ -z "${got}" ]; then
        echo "      ✗ ${inst}: no log from any source (current container, saved logs, unit files)$([ "${stale}" -eq 0 ] || echo "; the ${stale} log(s) of this name already here are not vouched for by a marker of this instance and do not count")" >&2
        return 1
    fi
    ident2="$(_bench_instance_ident "${inst}" "${zone}")"
    if [ "${ident2}" != "${ident}" ]; then
        echo "      ✗ ${inst}: the instance changed during the pull (${ident} -> ${ident2:-not found}) — no marker" >&2
        return 1
    fi
    # shellcheck disable=SC2086  # plain file names
    m="$(_bench_write_marker "${dest}" "${inst}" "${id}" "${ident#* }" "${got}" ${new} ${vouched})" || return 1
    if ! _bench_marker_verdict "${m}" "${dest}" "${inst}" "${id}" > /dev/null; then
        echo "      ✗ ${inst}: its new marker ${m##*/} does not verify — not saved" >&2
        return 1
    fi
    echo "      ✓ ${inst}: ${got}"
}

# bench_pull_node_logs <dest-dir> — every node's logs, 4 nodes at a time, from three sources:
# the current container's unfiltered log, gzipped on the node, to <instance>-telcoin.log.gz;
# every log bench_save_node_log saved on the node to <instance>-<file name>; the unit's append
# files (BENCH_NODE_UNIT_LOGS), gzipped on the node, to <instance>-unit-{stdout,stderr}.log.gz.
# A non-empty current-container log already there is kept and the new copy is named
# <instance>-telcoin-<UTC stamp>.log.gz. A saved log or unit file already there is not copied
# again when a marker of the same instance (same id) vouches for it; otherwise it is kept and the
# new copy gets a stamped name (_bench_pull_node). A node passes when no transfer failed and it
# has at least one log this pull wrote or its marker vouches for; it then gets a marker naming
# its instance id (see "pull markers"). Per node: two instance lookups (reads), and up to 4 ssh
# sessions: current log, saved-log tar, one per unit file. Non-zero, naming the nodes, if any
# node failed. Creates <dest-dir> but never its parent. Dry run: one line per session, no
# lookup, nothing created.
bench_pull_node_logs() {
    local dest="${1:-}" jobs=4 stamp i p inst out uout scmd failed="" pids=() names=()
    # No container is normal (rc 0, no output). Any other failed inspect (daemon down, sudo) fails
    # the session: docker exits 1 for both, so they are told apart by its "No such container" text.
    # shellcheck disable=SC2016  # expanded by the remote bash
    local cmd='bash -o pipefail -c '"'"'e=$(sudo docker container inspect telcoin 2>&1 >/dev/null) || { case $e in *"No such container"*) exit 0 ;; esac; echo "docker container inspect failed: $e" >&2; exit 1; }; sudo docker logs telcoin 2>&1 | gzip -1'"'"
    [ -n "${dest}" ] || { echo "❌ bench_pull_node_logs <dest-dir>" >&2; return 1; }
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    # Only <dest> itself: a missing parent (a run's results directory) is never created here.
    if [ "${BENCH_APPLY}" = "1" ] && [ ! -d "${dest}" ] && ! mkdir "${dest}"; then
        echo "❌ bench_pull_node_logs: could not create ${dest} (its parent must exist already)" >&2
        return 1
    fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        out="${dest}/${inst}-telcoin.log.gz"
        [ -s "${out}" ] && out="${dest}/${inst}-telcoin-${stamp}.log.gz"
        scmd="$(_bench_saved_log_cmd "${dest}" "${inst}")"
        # One printf per line: the workers of earlier nodes print while this loop runs.
        printf '    +%s > %q\n' "$(printf ' %q' tn_iap_ssh "${inst}" "${ZONES[$i]}" "${cmd}")" "${out}"
        printf '      +%s | tar -> %q-<file>\n' "$(printf ' %q' tn_iap_ssh "${inst}" "${ZONES[$i]}" "${scmd}")" "${dest}/${inst}"
        for p in ${BENCH_NODE_UNIT_LOGS}; do
            uout="${dest}/${inst}-unit-${p%%:*}.log.gz"
            if [ -s "${uout}" ]; then echo "      - ${uout} already here — not copied again if this instance's marker vouches for it, else copied beside it"; continue; fi
            printf '      +%s > %q\n' "$(printf ' %q' tn_iap_ssh "${inst}" "${ZONES[$i]}" "$(_bench_unit_log_cmd "${p#*:}")")" "${uout}"
        done
        [ "${BENCH_APPLY}" = "1" ] || continue
        if [ "${#pids[@]}" -ge "${jobs}" ]; then
            wait "${pids[0]}" || failed="${failed} ${names[0]}"
            pids=("${pids[@]:1}"); names=("${names[@]:1}")
        fi
        _bench_pull_node "${inst}" "${ZONES[$i]}" "${cmd}" "${out}" "${scmd}" "${dest}" &
        pids+=("$!"); names+=("${inst}")
    done
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    for i in "${!pids[@]}"; do
        wait "${pids[$i]}" || failed="${failed} ${names[$i]}"
    done
    if [ -n "${failed}" ]; then echo "❌ node logs not pulled from:${failed}" >&2; return 1; fi
    echo "    ✓ logs of ${#INSTANCE_NAMES[@]} nodes in ${dest}"
}

# --- operator-side RPC tunnel (IAP -> bench-validator-01:8545 on localhost) --------
bench_tunnel_pidfile() { printf '%s' "${BENCH_RESULTS_DIR}/tunnel.pid"; }

bench_tunnel_up() {
    local pidf pid waited=0; pidf="$(bench_tunnel_pidfile)"
    if [ -f "${pidf}" ] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "    tunnel already up (pid $(cat "${pidf}")) -> ${RPC_URL}"; return 0
    fi
    printf '    + gcloud compute start-iap-tunnel %s 8545 --local-host-port=localhost:%s --zone=%s --project=%s &\n' \
        "${INSTANCE_NAMES[0]}" "${BENCH_TUNNEL_PORT}" "${ZONES[0]}" "${PROJECT_ID}"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    mkdir -p "${BENCH_RESULTS_DIR}"
    nohup gcloud compute start-iap-tunnel "${INSTANCE_NAMES[0]}" 8545 \
        --local-host-port="localhost:${BENCH_TUNNEL_PORT}" --zone="${ZONES[0]}" --project="${PROJECT_ID}" \
        > "${BENCH_RESULTS_DIR}/tunnel.log" 2>&1 &
    pid=$!
    echo "${pid}" > "${pidf}"
    while [ "${waited}" -lt 45 ]; do
        if cast chain-id --rpc-url "${RPC_URL}" >/dev/null 2>&1; then
            echo "    ✓ tunnel up (pid ${pid}) -> ${RPC_URL}"; return 0
        fi
        kill -0 "${pid}" 2>/dev/null || break
        sleep 3; waited=$((waited + 3))
    done
    echo "❌ IAP tunnel to ${INSTANCE_NAMES[0]}:8545 did not come up; see ${BENCH_RESULTS_DIR}/tunnel.log" >&2
    return 1
}

bench_tunnel_down() {
    local pidf p; pidf="$(bench_tunnel_pidfile)"
    if [ -f "${pidf}" ]; then
        p="$(cat "${pidf}")"
        kill "${p}" 2>/dev/null && echo "    stopped tunnel pid ${p}"
        rm -f "${pidf}"
    fi
}

# --- Prometheus (obs-devnet, through the Grafana datasource proxy) -----------------
# bench_prom_query <promql> — raw JSON. The Grafana admin password comes from Secret
# Manager and reaches curl on STDIN (-K -), never on a command line.
bench_prom_query() {
    local pw esc
    pw="$(tn_secret "${OBS_GRAFANA_SECRET_NAME}")" || return 1
    esc="$(printf '%s' "${pw}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    printf 'user = "admin:%s"\n' "${esc}" | curl -sS --max-time 20 -K - --get \
        --data-urlencode "query=$1" \
        "${BENCH_GRAFANA_URL}/api/datasources/proxy/uid/${BENCH_PROM_DATASOURCE_UID}/api/v1/query"
}

# bench_prom_rounds <min|max> — {"<node>": epoch*1e8+round, ...} for every bench node from
# `<agg> by (node) (tn_primary_round{network="bench"})`; "" if the query failed. Consensus
# rounds advance on an idle chain, block height does not (the engine skips empty
# non-epoch-closing outputs, so an unloaded TN chain sits at block 0).
bench_prom_rounds() {
    # Rounds restart at 0 every epoch, so an epoch boundary would read as "no node advanced".
    # epoch * 1e8 + round is monotonic across the boundary (rounds never reach 1e8 in an epoch).
    bench_prom_query "$1 by (node) (tn_epoch_current{network=\"${BENCH_PROM_NETWORK_LABEL}\"}) * 100000000 + $1 by (node) (tn_primary_round{network=\"${BENCH_PROM_NETWORK_LABEL}\"})" 2>/dev/null \
        | jq -c 'select(.status == "success") | [.data.result[] | {key: .metric.node, value: (.value[1] | tonumber)}] | from_entries' 2>/dev/null || true
}

# bench_rounds_advanced <before-json> <after-json> — JSON array of the nodes whose round in
# <after> is strictly greater than in <before> (a node absent from <before> never counts).
bench_rounds_advanced() {
    jq -cn --argjson a "$1" --argjson b "$2" '[$b | to_entries[] | select(.value > ($a[.key] // infinite)) | .key]'
}

# bench_prom_scalar <promql> — first sample value ("" when the vector is empty).
bench_prom_scalar() { bench_prom_query "$1" | jq -r '.data.result[0].value[1] // empty' 2>/dev/null || true; }

# --- Cloud Monitoring (REST, no SSH) -------------------------------------------------
# bench_monitoring_max <filter> [lookback-secs] — max of the newest point of every series
# matching <filter> ("" when none). The access token goes to curl on STDIN.
bench_monitoring_max() {
    local tok now start
    tok="$(gcloud auth print-access-token 2>/dev/null)" || return 0   # "" = unavailable, never fatal
    now="$(bench_now_unix)"; start=$((now - ${2:-600}))
    printf 'header = "Authorization: Bearer %s"\n' "${tok}" | curl -sS --max-time 20 -K - --get \
        --data-urlencode "filter=$1" \
        --data-urlencode "interval.startTime=$(bench_iso_from_unix "${start}")" \
        --data-urlencode "interval.endTime=$(bench_iso_from_unix "${now}")" \
        "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/timeSeries" \
        | jq -r '[.timeSeries[]?.points[0].value | (.doubleValue // .int64Value // empty) | tonumber] | max // empty' 2>/dev/null || true
}

# --- load-generator image (:blast-v2-<sha>) --------------------------------------------
# bench_require_txgen_image — die unless BENCH_TXGEN_IMAGE is a :blast-v2-<sha> image.
bench_require_txgen_image() {
    [ -n "${BENCH_TXGEN_IMAGE}" ] || bench_die "no txgen image: ${BENCH_TXGEN_IMAGE_ERROR:-BENCH_TXGEN_SHA unset}"
    case "${BENCH_TXGEN_IMAGE}" in *@*) bench_die "BENCH_TXGEN_IMAGE must be a tag, not a digest ref" ;; esac
    case "${BENCH_TXGEN_IMAGE##*:}" in
        blast-v2-?*) ;;
        *) bench_die "txgen image tag '${BENCH_TXGEN_IMAGE##*:}' is not blast-v2-<sha> (${BENCH_TXGEN_IMAGE}); the old :blast harness lacks the blast-v2 CLI" ;;
    esac
}

# bench_txgen_image_digest — registry digest of BENCH_TXGEN_IMAGE ("" if the tag is absent).
bench_txgen_image_digest() {
    gcloud artifacts docker images describe "${BENCH_TXGEN_IMAGE}" --format='value(image_summary.digest)' 2>/dev/null || true
}

# bench_txgen_cli_probe — when docker is available, run `IMAGE blast --help` and require every
# flag of the CLI contract. A throwaway --config dir holds the registry login, so the
# operator's docker config is never touched. BENCH_SKIP_CLI_PROBE=1 skips it.
BENCH_TXGEN_CONTRACT_FLAGS="--nodes --senders --sender-start --window --warmup-secs --duration-secs --cooldown-secs --receipts --deployments-path --label --run-id --out --stdout-json --prepare --fund-tel"
bench_txgen_cli_probe() {
    if [ "${BENCH_SKIP_CLI_PROBE:-0}" = "1" ]; then bench_warn "BENCH_SKIP_CLI_PROBE=1 — blast --help probe skipped"; return 0; fi
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
        bench_warn "docker not available — skipping the '${BENCH_TXGEN_IMAGE} blast --help' CLI probe"; return 0
    fi
    local cfg help f missing=""
    cfg="$(mktemp -d)"
    gcloud auth print-access-token 2>/dev/null \
        | docker --config "${cfg}" login -u oauth2accesstoken --password-stdin "https://${BENCH_TXGEN_IMAGE%%/*}" >/dev/null 2>&1 || true
    help="$(docker --config "${cfg}" run --rm --platform linux/amd64 "${BENCH_TXGEN_IMAGE}" blast --help 2>&1 || true)"
    rm -rf "${cfg}"
    for f in ${BENCH_TXGEN_CONTRACT_FLAGS}; do
        printf '%s\n' "${help}" | grep -Eq -- "(^|[^a-z-])${f}([^a-z-]|$)" || missing="${missing} ${f}"
    done
    if [ -n "${missing}" ]; then
        printf '%s\n' "${help}" | head -15 >&2
        bench_die "${BENCH_TXGEN_IMAGE} 'blast --help' lacks:${missing} (or the image could not be run; BENCH_SKIP_CLI_PROBE=1 to skip)"
    fi
    echo "    ✓ ${BENCH_TXGEN_IMAGE} blast --help carries every contract flag (incl. --stdout-json)"
}

# --- leftovers (anything the benchmark could have created) -----------------------------
# bench_bucket_names — buckets that are ours by label benchmark=1 OR by name tn-devnet-bench-*
# (step 12 labels in a second call, so an unlabelled bucket must still be found).
bench_bucket_names() {
    gcloud storage buckets list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r '.[] | select(((.labels.benchmark // "") == "1") or (.name | startswith("tn-devnet-bench-"))) | .name' || true
}

# bench_leftovers — one line per existing instance / disk / firewall rule / bucket that is
# named ^bench- (tn-devnet-bench- for buckets) or labelled benchmark=1. Empty = clean project.
bench_leftovers() {
    gcloud compute instances list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r '.[] | select((.name | test("^bench-")) or ((.labels.benchmark // "") == "1")) | "instance " + .name' || true
    gcloud compute disks list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r '.[] | select((.name | test("^bench-")) or ((.labels.benchmark // "") == "1")) | "disk " + .name' || true
    gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r '.[] | select((.name | test("^bench-")) or ((.targetTags // []) | index("bench-node"))) | "firewall-rule " + .name' || true
    bench_bucket_names | sed 's/^/bucket /'
}

# bench_obs_mem_pct — obs-devnet memory used % from the Ops Agent (empty if unavailable).
bench_obs_mem_pct() {
    local id
    id="$(gcloud compute instances describe "${OBS_INSTANCE_NAME}" --zone="${OBS_ZONE}" --project="${PROJECT_ID}" --format='value(id)' 2>/dev/null)" || true
    [ -n "${id}" ] || return 0
    bench_monitoring_max "metric.type=\"agent.googleapis.com/memory/percent_used\" AND metric.labels.state=\"used\" AND resource.labels.instance_id=\"${id}\""
}
