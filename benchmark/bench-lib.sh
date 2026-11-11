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
# not a knob: set unconditionally so the environment cannot stretch it. The one way past it is
# BENCH_TEARDOWN_TRUST_MARKERS=1 (exactly "1"), which accepts an older marker that is otherwise
# intact (see _bench_marker_verdict).
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

# bench_is_stockout <gcloud output> — 0 when a create failed because the zone has run out of the
# machine type (code ZONE_RESOURCE_POOL_EXHAUSTED[_WITH_DETAILS], reason: stockout). gcloud wraps
# its YAML error ("does not have\n  enough resources"), so whitespace is folded before matching.
# The same matcher as benchmark-blast.sh's is_stockout (load VMs); this one serves the node creates.
bench_is_stockout() {
    case "$(printf '%s' "$1" | tr -s ' \t\n' '   ')" in
        *ZONE_RESOURCE_POOL_EXHAUSTED*|*stockout*|*"does not have enough resources"*) return 0 ;;
    esac
    return 1
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

# _bench_git_head <dir> — HEAD of the git work tree whose top level is exactly <dir>; "" otherwise
# (e.g. a submodule that is not checked out, whose directory belongs to the superproject).
_bench_git_head() {
    local top
    top="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" || return 0
    [ "$(cd "${top}" && pwd -P)" = "$(cd "$1" && pwd -P)" ] || return 0
    git -C "$1" rev-parse HEAD 2>/dev/null || true
}

# bench_manifest_init — write the tn-bench-manifest/v1 skeleton (never overwrites, so a
# --from resume keeps the timestamps already recorded). harness records this checkout: its HEAD,
# whether tracked files differ from it (dirty; untracked files do not count), and the HEADs of
# the common and tn-node-deployment submodules (null when not available). prometheus.grafana_url is
# BENCH_GRAFANA_URL: the local forward to the run's bench-obs Grafana (bench_obs_tunnel_up).
bench_manifest_init() {
    local f st dirty=null; f="$(bench_manifest)"
    mkdir -p "${BENCH_RESULTS_DIR}"
    if [ -f "${f}" ]; then echo "    manifest exists: ${f} (kept)"; return 0; fi
    if st="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=no 2>/dev/null)"; then
        if [ -n "${st}" ]; then dirty=true; else dirty=false; fi
    fi
    jq -n \
        --arg hsha "$(_bench_git_head "${REPO_ROOT}")" --argjson hdirty "${dirty}" \
        --arg hcommon "$(_bench_git_head "${REPO_ROOT}/common")" \
        --arg htnd "$(_bench_git_head "${REPO_ROOT}/tn-node-deployment")" \
        --arg run "${BENCH_RUN_ID}" --arg fleet "${BENCH_FLEET}" --arg mt "${MACHINE_TYPE}" \
        --arg ds "${NODE_DISK_SIZE}" --arg dt "${NODE_DISK_TYPE}" --arg cid "${CHAIN_ID}" \
        --arg diops "${NODE_DISK_IOPS}" --arg dtput "${NODE_DISK_THROUGHPUT}" \
        --arg ep "${EPOCH_DURATION_SECS}" --arg di "${DOCKER_IMAGE}" --arg ti "${BENCH_TXGEN_IMAGE}" \
        --arg p "${PROJECT_ID}" --arg g "${BENCH_GRAFANA_URL}" --arg uid "${BENCH_PROM_DATASOURCE_UID}" \
        --arg nl "${BENCH_PROM_NETWORK_LABEL}" --arg now "$(bench_now_iso)" '
        def num_or_null: if . == "" then null else tonumber end;
        def str_or_null: if . == "" then null else . end;
        {schema: "tn-bench-manifest/v1", run_id: $run, fleet: $fleet, machine_type: $mt,
         node_disk: {size_gb: ($ds|tonumber), type: $dt, provisioned_iops: ($diops|num_or_null),
                     provisioned_throughput: ($dtput|num_or_null)}, chain_id: ($cid|tonumber),
         epoch_duration_secs: ($ep|tonumber), docker_image: $di, txgen_image: $ti, project: $p,
         harness: {sha: ($hsha|str_or_null), dirty: $hdirty,
                   submodules: {common: ($hcommon|str_or_null), "tn-node-deployment": ($htnd|str_or_null)}},
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

# The node-log pull machinery (bench_pull_stream, the unit-log span and rotated generations, the
# coverage check, the bench logrotate text) lives beside this file. Without it no teardown can pull
# a complete record, so a missing or unreadable copy stops here.
if [ ! -r "${BENCH_LIB_DIR}/pull-lib.sh" ]; then
    echo "❌ bench-lib.sh: ${BENCH_LIB_DIR}/pull-lib.sh is missing or unreadable — refusing to run." >&2
    exit 1
fi
# shellcheck source=pull-lib.sh
. "${BENCH_LIB_DIR}/pull-lib.sh"

# The bench-obs VM (the run's own Prometheus + Grafana: create, boot, bring-up, its two local
# forwards, the Prometheus snapshot pull) lives beside this file too. Every Prometheus read of the
# run goes to it, so a missing or unreadable copy stops here the same way.
if [ ! -r "${BENCH_LIB_DIR}/obs-lib.sh" ]; then
    echo "❌ bench-lib.sh: ${BENCH_LIB_DIR}/obs-lib.sh is missing or unreadable — refusing to run." >&2
    exit 1
fi
# shellcheck source=obs-lib.sh
. "${BENCH_LIB_DIR}/obs-lib.sh"

# --- files ------------------------------------------------------------------------------
# bench_file_sha256 <file> — the file's SHA-256 in lower-case hex (shasum or sha256sum,
# whichever exists). Non-zero and no output when the file cannot be read.
bench_file_sha256() {
    local h
    [ -f "${1:-}" ] && [ -r "$1" ] || return 1
    if command -v shasum >/dev/null 2>&1; then h="$(shasum -a 256 < "$1")" || return 1
    elif command -v sha256sum >/dev/null 2>&1; then h="$(sha256sum < "$1")" || return 1
    else return 1; fi
    printf '%s\n' "${h%% *}"
}

# bench_params_ms <file> <key> — a top-level duration of a consensus parameters YAML in whole
# milliseconds: `key: 500ms`, `key: 3s`, `key: 1.5s`, `key: 2m`, or the serde block form (`key:`
# then indented `secs: N` and `nanos: M`). Sub-millisecond parts are dropped. "" when the key is
# absent, the file unreadable or the value none of those forms; never fatal.
bench_params_ms() {
    [ -r "${1:-}" ] && [ -n "${2:-}" ] || return 0
    awk -v k="$2" -v q="'" '
        function dur(v,   u, n, i, f, mul) {
            if (v !~ /^[0-9]+(\.[0-9]+)?(ms|s|m)$/) return ""
            u = v; sub(/^[0-9.]+/, "", u)
            n = substr(v, 1, length(v) - length(u)); i = n; f = ""
            if (index(n, ".")) { i = substr(n, 1, index(n, ".") - 1); f = substr(n, index(n, ".") + 1) }
            if (length(f) > 9) f = substr(f, 1, 9)
            mul = (u == "ms") ? 1 : ((u == "s") ? 1000 : 60000)
            return sprintf("%d", i * mul + (f == "" ? 0 : int(f * mul / (10 ^ length(f)))))
        }
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
            r = dur(v); if (r != "") print r
            got = 1; exit
        }
        END { if (!got && blk && (s != "" || n != "")) printf "%d\n", s * 1000 + int(n / 1000000) }
    ' "$1"
}

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

# bench_cpu_quota_metric <machine-type> — the regional quota metric the type's vCPUs count
# against, by machine family (the part before the first '-'): c3 -> C3_CPUS, c3d -> C3D_CPUS,
# n2 -> N2_CPUS, n2d -> N2D_CPUS, n4 -> N4_CPUS; e2, n1 and any other family -> CPUS.
bench_cpu_quota_metric() {
    case "${1%%-*}" in
        c3) echo C3_CPUS ;;
        c3d) echo C3D_CPUS ;;
        n2) echo N2_CPUS ;;
        n2d) echo N2D_CPUS ;;
        n4) echo N4_CPUS ;;
        *) echo CPUS ;;
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

# bench_iap_scp_down <inst> <zone> <remote-src> <local-dest> (IAP; remote -> local). The copy lands
# as <local-dest>.part and is renamed, so a cut-off copy never stands in for the file. IAP can
# refuse a tunnel it grants seconds later (4033 on a healthy node at the r20261006-0053 collect;
# 4003 and 4047 are the same class): only those are retried, up to BENCH_IAP_RETRIES attempts
# (default 3), 10 s then 20 s apart. Every attempt has a 300 s alarm and a closed stdin.
bench_iap_scp_down() {
    local tries="${BENCH_IAP_RETRIES:-3}" try=1 rc err
    case "${tries}" in ''|*[!0-9]*|0*) bench_warn "BENCH_IAP_RETRIES='${tries}' is not a positive integer — using 3"; tries=3 ;; esac
    err="$(mktemp)" || return 1
    while :; do
        rc=0
        perl -e 'alarm shift; exec @ARGV' 300 gcloud compute scp "$1:$3" "$4.part" --zone="$2" --project="${PROJECT_ID}" \
            --tunnel-through-iap --scp-flag="-o ConnectTimeout=20" </dev/null 2>"${err}" || rc=$?
        if [ "${rc}" -eq 0 ]; then
            rm -f "${err}"
            mv -f "$4.part" "$4"
            return
        fi
        cat "${err}" >&2
        rm -f "$4.part"
        if [ "${try}" -ge "${tries}" ] || ! grep -Eq '\[(4003|4033|4047): ' "${err}"; then
            rm -f "${err}"
            return "${rc}"
        fi
        echo "      … $1: IAP refused the tunnel (attempt ${try}/${tries}); retrying in $((try * 10)) s" >&2
        sleep "$((try * 10))"
        try=$((try + 1))
    done
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

# _bench_pull_node_log <inst> <zone> <remote-cmd> <out> — <remote-cmd>'s gzip stream (the current
# container's log) through bench_pull_stream (pull-lib.sh): every attempt into a fresh temp file,
# checked with gzip -t, renamed to <out> once complete, so a retried transfer never appends to a
# cut-off one. A zero-byte <out> (a leftover) is removed first; a non-empty one is never pulled
# over. rc 0 = landed; 1 = nothing to copy (no telcoin container, or its log is empty; normal);
# 2 = the transfer failed; 3 = gcloud needs re-authentication (BENCH_PULL_STOP_FILE). Only a
# landed log is kept.
_bench_pull_node_log() {
    local r=0
    if [ -s "$4" ]; then echo "      ✗ $1: $4 is here already — not pulled over it" >&2; return 2; fi
    if [ -e "$4" ] && ! rm -f -- "$4"; then echo "      ✗ $1: the empty $4 could not be removed" >&2; return 2; fi
    bench_pull_stream "$1" "$2" gz "$4" cmd "$3" || r=$?
    case "${r}" in
        0) ;;
        1) echo "      - $1: no current-container log (no telcoin container, or its log is empty)"; return 1 ;;
        3) echo "      ✗ $1: current-container log: gcloud needs re-authentication — not pulled" >&2; return 3 ;;
        *) echo "      ✗ $1: current-container log: ssh or docker on the node failed" >&2; return 2 ;;
    esac
    # gzip of no input is still 20 bytes, so judge the decompressed first byte.
    if [ "$(gzip -cd "$4" 2>/dev/null | head -c 1 | wc -c)" -ne 1 ]; then
        rm -f "$4"
        echo "      - $1: no current-container log (no telcoin container, or its log is empty)"
        return 1
    fi
    echo "      ✓ $1 -> $4"
}

# _bench_unit_log_cmd <node-file> — remote command that streams <node-file> gzipped on the
# node; no output (rc 0) when the file is missing or empty. It only reads.
_bench_unit_log_cmd() {
    # shellcheck disable=SC2016  # expanded by the remote bash
    printf "sudo bash -c '%s' _ %s" '[ -s "$1" ] || exit 0; gzip -1 < "$1"' "$1"
}

# _bench_pull_unit_log <inst> <zone> <node-file> <out> — one of BENCH_NODE_UNIT_LOGS, gzipped on
# the node as it streams, through bench_pull_stream (a fresh temp file per attempt, gzip -t, then the
# rename to <out>). A non-empty <out> is kept and no ssh is made; a zero-byte one (a leftover) is
# removed and pulled again. rc 0 = landed or already here;
# 1 = missing or empty on the node (normal); 2 = the transfer failed; 3 = gcloud needs
# re-authentication (BENCH_PULL_STOP_FILE).
_bench_pull_unit_log() {
    local r=0
    if [ -s "$4" ]; then return 0; fi
    if [ -e "$4" ] && ! rm -f -- "$4"; then echo "      ✗ $1: the empty $4 could not be removed" >&2; return 2; fi
    bench_pull_stream "$1" "$2" gz "$4" cmd "$(_bench_unit_log_cmd "$3")" || r=$?
    case "${r}" in
        0) echo "      ✓ $1 -> $4" ;;
        1) echo "      - $1: $3 is missing or empty on the node"; return 1 ;;
        3) echo "      ✗ $1: $3: gcloud needs re-authentication — not pulled" >&2; return 3 ;;
        *) echo "      ✗ $1: $3: ssh or gzip on the node failed" >&2; return 2 ;;
    esac
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
# -<UTC stamp> before .log.gz (or before .rotated-<N>.log.gz): the name a copy stamped because its
# name was taken would have had. One per line; other names unchanged.
_bench_unstamp_names() {
    local n b r
    for n in "$@"; do
        n="${n##*/}"; b="${n%.log.gz}"; r=""
        case "${b##*.}" in
            rotated-*) case "${b##*.rotated-}" in ''|*[!0-9]*) ;; *) r=".${b##*.}"; b="${b%.*}" ;; esac ;;
        esac
        case "${b##*-}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) n="${b%-*}${r}.log.gz" ;; esac
        printf '%s\n' "${n}"
    done
}

# _bench_log_sources_of <inst> [<file>...] — what those logs of <inst> are, on one line, e.g.
# "current-container log, 2 saved log(s), unit stdout, unit stderr, 1 rotated unit stdout log(s)"
# (only those present). Judged by name (a stamped copy by its unstamped name):
# <inst>-telcoin.log.gz is the current container's, <inst>-unit-<stream>.log.gz a unit file,
# <inst>-unit-<stream>.rotated-<N>.log.gz an earlier generation of one (logrotate), any other a
# saved log. Non-zero and no output for none.
_bench_log_sources_of() {
    local inst="$1" n cur=0 saved=0 uo=0 ue=0 ur=0 er=0 got=""
    shift
    for n in $(_bench_unstamp_names "$@"); do
        case "${n#"${inst}"-}" in
            telcoin.log.gz) cur=1 ;;
            unit-stdout.log.gz) uo=1 ;;
            unit-stderr.log.gz) ue=1 ;;
            unit-stdout.rotated-*.log.gz) ur=$((ur + 1)) ;;
            unit-stderr.rotated-*.log.gz) er=$((er + 1)) ;;
            *) saved=$((saved + 1)) ;;
        esac
    done
    [ "${cur}" -eq 0 ] || got="current-container log"
    [ "${saved}" -eq 0 ] || got="${got:+${got}, }${saved} saved log(s)"
    [ "${uo}" -eq 0 ] || got="${got:+${got}, }unit stdout"
    [ "${ue}" -eq 0 ] || got="${got:+${got}, }unit stderr"
    [ "${ur}" -eq 0 ] || got="${got:+${got}, }${ur} rotated unit stdout log(s)"
    [ "${er}" -eq 0 ] || got="${got:+${got}, }${er} rotated unit stderr log(s)"
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
# BENCH_TEARDOWN_TRUST_MARKERS=1 lifts the age rule only: a marker older than the window counts
# when everything else above holds, and its verdict says so. It is for a teardown re-run after an
# interrupted one, when the logs the marker vouches for are the ones wanted and the lines the node
# logged since (an idling fleet) are not worth pulling again.
BENCH_PULL_MARKER_V="tn-bench-pulled/v2"

# _bench_marker_verdict <marker> <dest> <inst> <id> — one line: "accepted — ..." or "not accepted
# — <why>", for the instance <id> that holds <inst> now. rc 0 = accepted. A marker older than
# BENCH_MARKER_MAX_AGE_SECS is accepted only with BENCH_TEARDOWN_TRUST_MARKERS=1, and its line then
# ends "(BENCH_TEARDOWN_TRUST_MARKERS=1)". Reads only.
_bench_marker_verdict() {
    local m="$1" d="$2" inst="$3" want="$4" head="" k a b ln=0 end=0 mi="" mid="" mc="" mr="" mp="" files="" bad="" s nf=0 trusted=""
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
    # Fresh only: pulled within BENCH_MARKER_MAX_AGE_SECS (unless BENCH_TEARDOWN_TRUST_MARKERS=1),
    # and never in the future. The fixed-width UTC form compares as a 14-digit number.
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
        if [ "${BENCH_TEARDOWN_TRUST_MARKERS:-0}" != "1" ]; then
            echo "not accepted — pulled ${mp}, more than $((BENCH_MARKER_MAX_AGE_SECS / 60)) min ago; the node has logged since"
            return 1
        fi
        trusted=" (BENCH_TEARDOWN_TRUST_MARKERS=1)"
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
    echo "accepted — instance ${mid} (created ${mc:-?}), run ${mr:-?}, pulled ${mp:-?}; its ${nf} log(s) are here at their recorded sizes${trusted}"
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
# the node's saved logs, through bench_pull_stream (a fresh temp file per attempt, tar -tf before
# it counts); each member lands as <dest>/<inst>-<file name> through a temp file and a rename,
# never over a non-empty file. A member whose name is taken (the node was not told to skip it: no
# marker of this instance vouches for the file here) lands beside it as <inst>-<file name minus
# .log.gz>-<UTC stamp>.log.gz. rc 1 if the ssh, the tar or any member failed; 3 when gcloud needs
# re-authentication (BENCH_PULL_STOP_FILE). A node without saved logs is normal (rc 0).
_bench_pull_saved_logs() {
    local tarf list n out tmp rc=0 r=0
    tarf="$(mktemp "$4/$1-saved.XXXXXX")" || return 1
    bench_pull_stream "$1" "$2" tar "${tarf}" cmd "$3" || r=$?
    case "${r}" in
        0) ;;
        1) rm -f "${tarf}"; return 0 ;;
        3) rm -f "${tarf}"; echo "      ✗ $1: saved logs: gcloud needs re-authentication — not pulled" >&2; return 3 ;;
        *) rm -f "${tarf}"; echo "      ✗ $1: saved logs: ssh or tar on the node failed" >&2; return 1 ;;
    esac
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

# _bench_pull_rc <rc> — fold one pull's status into the caller's xfer (a transfer failed) and stop
# (gcloud needs re-authentication: every later session would fail the same way) flags. rc 0 and 1
# (landed, nothing to copy) change nothing; an existing BENCH_PULL_STOP_FILE (another node's pull
# found it) stops this node too.
_bench_pull_rc() {
    case "$1" in
        0|1) ;;
        3) xfer=1; stop=1 ;;
        *) xfer=1 ;;
    esac
    if [ -n "${BENCH_PULL_STOP_FILE:-}" ] && [ -e "${BENCH_PULL_STOP_FILE}" ]; then xfer=1; stop=1; fi
    return 0
}

# _bench_pull_node <inst> <zone> <log-cmd> <out> <saved-cmd> <dest> — one node, in this order: the
# span of its unit logs (bench_pull_unit_span: <dest>/<inst>.logspan, every generation on the node
# before anything is copied), its current container's log, its saved logs, the unit's append files,
# and their rotated generations (bench_pull_rotated_logs: <inst>-unit-<stream>.rotated-<N>.log.gz).
# Every transfer goes through bench_pull_stream (pull-lib.sh). The instance's id is looked up
# before and after; no id, or a different one after, fails the node. Only logs this pull wrote, or
# logs an accepted marker of this instance vouches for, count: a file an earlier instance of the
# same name left is kept, never counts, and this pull's copy of that source lands beside it under a
# stamped name (<saved-cmd>, the plan's command, is sent with its skip list narrowed to the vouched
# names). A stamped copy byte-identical to the file it stands beside is dropped
# (bench_drop_if_identical) and that file counts as this pull's. The node passes when no transfer
# failed and at least one log counts; only then does it get a marker (see "pull markers"). It says
# what it got. rc 3 when gcloud needs re-authentication (no further session is opened).
_bench_pull_node() {
    local inst="$1" zone="$2" dest="$6" ident ident2 id vouched vbase before after n u p r uout skip=() rskip=() new="" stale=0 got m xfer=0 stop=0 nl=$'\n'
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
    # The span script prints a LOGSPAN line per stream even for a missing file, so an empty answer
    # (rc 1) is a broken session: like any failed span it fails the node (no marker), and a
    # <inst>.logspan an earlier pass left is removed, so the coverage check never reads it as now.
    r=0; bench_pull_unit_span "${inst}" "${zone}" "${dest}" || r=$?
    case "${r}" in
        0) ;;
        1) echo "      ✗ ${inst}: the span session answered nothing" >&2; r=2 ;;
        *) echo "      ✗ ${inst}: the span of its unit logs was not recorded (rc ${r})" >&2 ;;
    esac
    if [ "${r}" -ne 0 ] && [ -e "${dest}/${inst}.logspan" ]; then
        rm -f -- "${dest}/${inst}.logspan" && echo "      - ${inst}: the ${inst}.logspan of an earlier pull is removed (it no longer describes the node)" >&2
    fi
    _bench_pull_rc "${r}"
    if [ "${stop}" -eq 0 ]; then
        r=0; _bench_pull_node_log "${inst}" "${zone}" "$3" "$4" || r=$?
        _bench_pull_rc "${r}"
    fi
    for n in ${vouched} ${vbase}; do skip+=("${n#"${inst}"-}"); done
    if [ "${stop}" -eq 0 ]; then
        r=0; _bench_pull_saved_logs "${inst}" "${zone}" "$(_bench_saved_log_cmd_skip "${skip[@]+"${skip[@]}"}")" "${dest}" || r=$?
        _bench_pull_rc "${r}"
    fi
    for p in ${BENCH_NODE_UNIT_LOGS}; do
        [ "${stop}" -eq 0 ] || break
        uout="${dest}/${inst}-unit-${p%%:*}.log.gz"
        _bench_in_lines "${uout##*/}" "${vbase}" && continue   # this instance's copy: not copied again
        [ ! -s "${uout}" ] || uout="${dest}/${inst}-unit-${p%%:*}-$(date -u +%Y%m%dT%H%M%SZ).log.gz"
        r=0; _bench_pull_unit_log "${inst}" "${zone}" "${p#*:}" "${uout}" || r=$?
        _bench_pull_rc "${r}"
    done
    if [ "${stop}" -eq 0 ]; then
        # The node-side names (unit-<stream>.rotated-<N>.log.gz) this instance's marker vouches for.
        for n in ${vbase}; do
            case "${n#"${inst}"-}" in unit-*.rotated-*.log.gz) rskip+=("${n#"${inst}"-}") ;; esac
        done
        r=0; bench_pull_rotated_logs "${inst}" "${zone}" "${dest}" "${rskip[@]+"${rskip[@]}"}" || r=$?
        [ "${r}" -le 1 ] || echo "      ✗ ${inst}: rotated unit logs: not all pulled (rc ${r})" >&2
        _bench_pull_rc "${r}"
    fi
    after="$(_bench_logs_here "${dest}" "${inst}")"
    for n in ${after}; do
        _bench_in_lines "${n}" "${before}" && continue
        # A stamped copy that matches the file it stands beside byte for byte (gzip -1 of the same
        # bytes is the same file): the copy goes, and the file it matches is this pull's.
        u="$(_bench_unstamp_names "${n}")"
        if [ "${u}" != "${n}" ] && _bench_in_lines "${u}" "${before}"; then
            bench_drop_if_identical "${dest}/${n}" "${dest}/${u}" || true
            if [ ! -e "${dest}/${n}" ]; then
                echo "      - ${inst}: ${u} counts as this pull's (the copy just pulled was identical)"
                n="${u}"
            fi
        fi
        _bench_in_lines "${n}" "${new}" || new="${new}${new:+${nl}}${n}"
    done
    vouched="$(bench_node_vouched_logs "${dest}" "${inst}" "${id}")"   # re-read: still here, same sizes
    for n in ${vouched}; do _bench_in_lines "${n}" "${new}" || new="${new}${new:+${nl}}${n}"; done
    for n in ${before}; do _bench_in_lines "${n}" "${new}" || stale=$((stale + 1)); done
    # shellcheck disable=SC2086  # plain file names
    got="$(_bench_log_sources_of "${inst}" ${new})" || got=""
    if [ "${stop}" -ne 0 ]; then
        echo "      ✗ ${inst}: gcloud needs re-authentication — stopped (got so far: ${got:-nothing})" >&2
        return 3
    fi
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
    m="$(_bench_write_marker "${dest}" "${inst}" "${id}" "${ident#* }" "${got}" ${new})" || return 1
    if ! _bench_marker_verdict "${m}" "${dest}" "${inst}" "${id}" > /dev/null; then
        echo "      ✗ ${inst}: its new marker ${m##*/} does not verify — not saved" >&2
        return 1
    fi
    echo "      ✓ ${inst}: ${got}"
}

# bench_pull_node_logs <dest-dir> — every node's logs, 4 nodes at a time (_bench_pull_node): first
# the span of its unit logs (<instance>.logspan), then the current container's unfiltered log,
# gzipped on the node, to <instance>-telcoin.log.gz; every log bench_save_node_log saved on the node
# to <instance>-<file name>; the unit's append files (BENCH_NODE_UNIT_LOGS), gzipped on the node, to
# <instance>-unit-{stdout,stderr}.log.gz; and their logrotate generations to
# <instance>-unit-{stdout,stderr}.rotated-<N>.log.gz. A non-empty current-container log already
# there is kept and the new copy is named <instance>-telcoin-<UTC stamp>.log.gz. A saved log, unit
# file or rotated generation already there is not copied again when a marker of the same instance
# (same id) vouches for it; otherwise it is kept and the new copy gets a stamped name (dropped again
# when byte-identical). A node passes when no transfer failed and it has at least one log this pull
# wrote or its marker vouches for; it then gets a marker naming its instance id (see "pull
# markers"). Every transfer is bench_pull_stream's (pull-lib.sh). When one of them finds that gcloud
# needs re-authentication it touches BENCH_PULL_STOP_FILE (a temp file of this call when unset): no
# node is started after that, and the call fails saying how many were not attempted. Non-zero,
# naming the nodes, if any node failed. Creates <dest-dir> but never its parent. Dry run: one line
# per session, no lookup, nothing created.
bench_pull_node_logs() {
    local dest="${1:-}" jobs=4 stamp i p inst out uout scmd failed="" pids=() names=() skipped=0 stopd=""
    local BENCH_PULL_STOP_FILE="${BENCH_PULL_STOP_FILE:-}"
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
    if [ "${BENCH_APPLY}" = "1" ] && [ -z "${BENCH_PULL_STOP_FILE}" ]; then
        stopd="$(mktemp -d "${TMPDIR:-/tmp}/bench-pull-stop.XXXXXX")" || { echo "❌ bench_pull_node_logs: no temp directory" >&2; return 1; }
        BENCH_PULL_STOP_FILE="${stopd}/stop"
    fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        out="${dest}/${inst}-telcoin.log.gz"
        [ -s "${out}" ] && out="${dest}/${inst}-telcoin-${stamp}.log.gz"
        scmd="$(_bench_saved_log_cmd "${dest}" "${inst}")"
        # One printf per line: the workers of earlier nodes print while this loop runs.
        printf '    + bench_pull_unit_span %q %q %q   # LOGSPAN per unit log generation -> %q\n' "${inst}" "${ZONES[$i]}" "${dest}" "${dest}/${inst}.logspan"
        printf '      +%s > %q\n' "$(printf ' %q' tn_iap_ssh "${inst}" "${ZONES[$i]}" "${cmd}")" "${out}"
        printf '      +%s | tar -> %q-<file>\n' "$(printf ' %q' tn_iap_ssh "${inst}" "${ZONES[$i]}" "${scmd}")" "${dest}/${inst}"
        for p in ${BENCH_NODE_UNIT_LOGS}; do
            uout="${dest}/${inst}-unit-${p%%:*}.log.gz"
            if [ -s "${uout}" ]; then echo "      - ${uout} already here — not copied again if this instance's marker vouches for it, else copied beside it"; continue; fi
            printf '      +%s > %q\n' "$(printf ' %q' tn_iap_ssh "${inst}" "${ZONES[$i]}" "$(_bench_unit_log_cmd "${p#*:}")")" "${uout}"
        done
        printf '      + bench_pull_rotated_logs %q %q %q   # each <unit file>.1 gzipped, .<N>.gz as is -> %q-unit-<stream>.rotated-<N>.log.gz\n' \
            "${inst}" "${ZONES[$i]}" "${dest}" "${dest}/${inst}"
        [ "${BENCH_APPLY}" = "1" ] || continue
        if [ "${#pids[@]}" -ge "${jobs}" ]; then
            wait "${pids[0]}" || failed="${failed} ${names[0]}"
            pids=("${pids[@]:1}"); names=("${names[@]:1}")
        fi
        if [ -e "${BENCH_PULL_STOP_FILE}" ]; then skipped=$((skipped + 1)); continue; fi
        _bench_pull_node "${inst}" "${ZONES[$i]}" "${cmd}" "${out}" "${scmd}" "${dest}" &
        pids+=("$!"); names+=("${inst}")
    done
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    for i in "${!pids[@]}"; do
        wait "${pids[$i]}" || failed="${failed} ${names[$i]}"
    done
    if [ -e "${BENCH_PULL_STOP_FILE}" ]; then
        [ -z "${stopd}" ] || rm -rf "${stopd}"
        echo "❌ node logs: gcloud needs re-authentication; ${skipped} node(s) not attempted$([ -z "${failed}" ] || echo "; not pulled from:${failed}") — run: gcloud auth login, then run this again" >&2
        return 1
    fi
    [ -z "${stopd}" ] || rm -rf "${stopd}"
    if [ -n "${failed}" ]; then echo "❌ node logs not pulled from:${failed}" >&2; return 1; fi
    echo "    ✓ logs of ${#INSTANCE_NAMES[@]} nodes in ${dest}"
}

# --- operator-side tunnels (IAP -> bench-validator-01:8545, bench-obs:9090/3000 on localhost) ----
bench_tunnel_pidfile() { printf '%s' "${BENCH_RESULTS_DIR}/tunnel.pid"; }

# BENCH_TUNNEL_SUPERVISOR — the ssh-mode tunnel supervisor, run by _bench_tunnel_start as
#   bash -c "${BENCH_TUNNEL_SUPERVISOR}" tn-bench-tunnel-supervisor <inst> <zone> <project> <local port> <host:port>
# in its own session, appending to tunnel.log. One IAP ssh session carries a local port-forward to
# <host:port> as seen from <inst> (the RPC tunnel: 127.0.0.1:8545), shared by every request. Each
# start logs
#   tunnel: start <ISO> mode=ssh target=<inst>:<port> local=<local port> pid=<ssh pid>
# and each exit `tunnel: exit <ISO> rc= up=<s>s fails=<n>/<max>`. A session that stayed up at least
# BENCH_TUNNEL_MIN_UP_SECS (20) is a drop, not a failure: the count of consecutive failures starts
# again. After BENCH_TUNNEL_MAX_FAILS (5) consecutive failures it gives up (exit 1). After every exit
# it asks GCP for the instance; "not found" (the teardown deleted it) ends the supervisor (exit 0).
# Otherwise it restarts 3 s later.
# shellcheck disable=SC2016  # expanded by the supervisor's bash
IFS= read -r -d '' BENCH_TUNNEL_SUPERVISOR <<'EOS' || true
fails=0
while :; do
    [ "${fails}" -lt "${BENCH_TUNNEL_MAX_FAILS:-5}" ] || { echo "tunnel: giving up after ${fails} consecutive failures at $(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 1; }
    t0="$(date +%s)"
    gcloud compute ssh "$1" --zone="$2" --project="$3" --tunnel-through-iap \
        --ssh-flag="-N" --ssh-flag="-L" --ssh-flag="localhost:$4:$5" \
        --ssh-flag="-o ServerAliveInterval=15" --ssh-flag="-o ServerAliveCountMax=3" \
        --ssh-flag="-o ExitOnForwardFailure=yes" --ssh-flag="-o StrictHostKeyChecking=accept-new" \
        </dev/null &
    child=$!
    echo "tunnel: start $(date -u +%Y-%m-%dT%H:%M:%SZ) mode=ssh target=$1:${5##*:} local=$4 pid=${child}"
    rc=0; wait "${child}" || rc=$?
    up=$(( $(date +%s) - t0 ))
    if [ "${up}" -ge "${BENCH_TUNNEL_MIN_UP_SECS:-20}" ]; then fails=0; else fails=$((fails + 1)); fi
    echo "tunnel: exit $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=${rc} up=${up}s fails=${fails}/${BENCH_TUNNEL_MAX_FAILS:-5}"
    if perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "$1" --zone="$2" --project="$3" \
        --format='value(status)' </dev/null 2>&1 >/dev/null | grep -qi 'not found'; then
        echo "tunnel: $1 is gone (instances describe: not found) at $(date -u +%Y-%m-%dT%H:%M:%SZ); not restarting"
        exit 0
    fi
    [ "${fails}" -ge "${BENCH_TUNNEL_MAX_FAILS:-5}" ] || { echo "tunnel: restarting in 3 s"; sleep 3; }
done
EOS

# _bench_tunnel_start <pidfile> <inst> <zone> <local-port> <remote-host:port> <probe-cmd> <desc> — one
# supervised ssh-mode forward, localhost:<local-port> -> <remote-host:port> as seen from <inst>
# (bench_tunnel_up's RPC tunnel; obs-lib.sh's bench_obs_tunnel_up for bench-obs:9090 and :3000).
# <pidfile>'s process alive: says so and returns 0. Else prints the plan line; a dry run
# (BENCH_APPLY != 1) stops there with rc 0. Otherwise BENCH_TUNNEL_SUPERVISOR in its own session
# (the pidfile holds the supervisor, a session leader, so bench_tunnel_down kills the whole group;
# its $0 is tn-bench-tunnel-supervisor so the teardown's pgrep finds it), appending to tunnel.log,
# then up to 45 s for `eval <probe-cmd>` to succeed through it (rc 0 with the ✓ line naming <desc>);
# a supervisor that exits or a probe that never answers is rc 1. The supervisor outlives its caller,
# so it is born with fds 5 and 6 closed: the deploy's log descriptors stay the deploy's own, and its
# EXIT trap can still write its result line to them.
_bench_tunnel_start() {
    local pidf="$1" inst="$2" zone="$3" lport="$4" target="$5" probe="$6" desc="$7" pid waited=0
    local maxf="${BENCH_TUNNEL_MAX_FAILS:-5}" minup="${BENCH_TUNNEL_MIN_UP_SECS:-20}"
    if [ -f "${pidf}" ] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "    tunnel already up (pid $(cat "${pidf}")) -> ${desc}"; return 0
    fi
    case "${maxf}" in ''|*[!0-9]*|0*) bench_warn "BENCH_TUNNEL_MAX_FAILS='${maxf}' is not a positive integer — using 5"; maxf=5 ;; esac
    case "${minup}" in ''|*[!0-9]*) bench_warn "BENCH_TUNNEL_MIN_UP_SECS='${minup}' is not a whole number of seconds — using 20"; minup=20 ;; esac
    printf '    + gcloud compute ssh %s --zone=%s --project=%s --tunnel-through-iap --ssh-flag=-N --ssh-flag=-L --ssh-flag=localhost:%s:%s ... &   (supervised: restarted on a drop, gives up after %s consecutive failures shorter than %s s or when the instance is gone; >> %s)\n' \
        "${inst}" "${zone}" "${PROJECT_ID}" "${lport}" "${target}" "${maxf}" "${minup}" "${BENCH_RESULTS_DIR}/tunnel.log"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    mkdir -p "${BENCH_RESULTS_DIR}"
    BENCH_TUNNEL_MAX_FAILS="${maxf}" BENCH_TUNNEL_MIN_UP_SECS="${minup}" \
        nohup setsid bash -c "${BENCH_TUNNEL_SUPERVISOR}" tn-bench-tunnel-supervisor \
        "${inst}" "${zone}" "${PROJECT_ID}" "${lport}" "${target}" \
        5>&- 6>&- >> "${BENCH_RESULTS_DIR}/tunnel.log" 2>&1 &
    pid=$!
    echo "${pid}" > "${pidf}"
    while [ "${waited}" -lt 45 ]; do
        if eval "${probe}" >/dev/null 2>&1; then
            echo "    ✓ tunnel up (pid ${pid}) -> ${desc}"; return 0
        fi
        kill -0 "${pid}" 2>/dev/null || break
        sleep 3; waited=$((waited + 3))
    done
    echo "❌ IAP tunnel to ${inst}:${target##*:} did not come up; see ${BENCH_RESULTS_DIR}/tunnel.log" >&2
    return 1
}

# bench_tunnel_up — the local RPC tunnel to INSTANCE_NAMES[0]:8545 on localhost:BENCH_TUNNEL_PORT.
# BENCH_TUNNEL_MODE=ssh (default): _bench_tunnel_start, probed with `cast chain-id`. Any other
# value: one `gcloud compute start-iap-tunnel` (a websocket per connection; about 1 connection in 50
# was lost on 2026-11-03, SSL WRONG_VERSION_NUMBER on the handshake, which is why ssh is the
# default). Both append to tunnel.log, one `tunnel: start <ISO> mode= target= local= pid=` line per
# start. The plan line names the command of the mode in use. Waits up to 45 s for `cast chain-id`
# through it.
bench_tunnel_up() {
    local pidf pid waited=0 mode="${BENCH_TUNNEL_MODE:-ssh}" maxf="${BENCH_TUNNEL_MAX_FAILS:-5}" minup="${BENCH_TUNNEL_MIN_UP_SECS:-20}"
    pidf="$(bench_tunnel_pidfile)"
    if [ "${mode}" = "ssh" ]; then
        # shellcheck disable=SC2016  # the probe is eval'd by _bench_tunnel_start
        _bench_tunnel_start "${pidf}" "${INSTANCE_NAMES[0]}" "${ZONES[0]}" "${BENCH_TUNNEL_PORT}" "127.0.0.1:8545" \
            'cast chain-id --rpc-url "${RPC_URL}"' "${RPC_URL}"
        return
    fi
    if [ -f "${pidf}" ] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "    tunnel already up (pid $(cat "${pidf}")) -> ${RPC_URL}"; return 0
    fi
    case "${maxf}" in ''|*[!0-9]*|0*) bench_warn "BENCH_TUNNEL_MAX_FAILS='${maxf}' is not a positive integer — using 5"; maxf=5 ;; esac
    case "${minup}" in ''|*[!0-9]*) bench_warn "BENCH_TUNNEL_MIN_UP_SECS='${minup}' is not a whole number of seconds — using 20"; minup=20 ;; esac
    printf '    + gcloud compute start-iap-tunnel %s 8545 --local-host-port=localhost:%s --zone=%s --project=%s &   (BENCH_TUNNEL_MODE=%s; >> %s)\n' \
        "${INSTANCE_NAMES[0]}" "${BENCH_TUNNEL_PORT}" "${ZONES[0]}" "${PROJECT_ID}" "${mode}" "${BENCH_RESULTS_DIR}/tunnel.log"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    mkdir -p "${BENCH_RESULTS_DIR}"
    nohup gcloud compute start-iap-tunnel "${INSTANCE_NAMES[0]}" 8545 \
        --local-host-port="localhost:${BENCH_TUNNEL_PORT}" --zone="${ZONES[0]}" --project="${PROJECT_ID}" \
        5>&- 6>&- >> "${BENCH_RESULTS_DIR}/tunnel.log" 2>&1 &
    pid=$!
    echo "tunnel: start $(bench_now_iso) mode=websocket target=${INSTANCE_NAMES[0]}:8545 local=${BENCH_TUNNEL_PORT} pid=${pid}" \
        >> "${BENCH_RESULTS_DIR}/tunnel.log"
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

# bench_tunnel_down — stops every tunnel of the run: the RPC tunnel (bench_tunnel_pidfile) and every
# other ${BENCH_RESULTS_DIR}/tunnel*.pid (the bench-obs forwards), each pidfile removed after.
bench_tunnel_down() {
    local rpcf pidf p what; rpcf="$(bench_tunnel_pidfile)"
    for pidf in "${rpcf}" "${BENCH_RESULTS_DIR}"/tunnel*.pid; do
        [ -f "${pidf}" ] || continue
        p="$(cat "${pidf}")"; what=""
        [ "${pidf}" = "${rpcf}" ] || what=" (${pidf##*/})"
        # the ssh-mode supervisor is a session leader: kill its whole group (supervisor + gcloud + ssh)
        { kill -- -"${p}" 2>/dev/null || kill "${p}" 2>/dev/null; } && echo "    stopped tunnel pid ${p}${what}"
        rm -f "${pidf}"
    done
}

# --- Prometheus (bench-obs through its local forward; obs-devnet through the Grafana proxy) ----
# bench_prom_query <promql> — raw JSON. BENCH_PROM_AUTH=0 (the default): the run's own bench-obs
# Prometheus API at BENCH_PROM_URL (the local forward of bench_obs_tunnel_up), no credentials.
# BENCH_PROM_AUTH=1: through the Grafana datasource proxy at BENCH_GRAFANA_URL; the Grafana admin
# password comes from Secret Manager and reaches curl on STDIN (-K -), never on a command line.
# That password is obs-devnet's, so a BENCH_GRAFANA_URL on the local bench-obs forward is refused
# before the secret is read: it must never be sent to another Grafana.
bench_prom_query() {
    local pw esc
    if [ "${BENCH_PROM_AUTH:-0}" = 0 ]; then
        curl -sS --max-time 20 --get --data-urlencode "query=$1" "${BENCH_PROM_URL}/query"
    else
        case "${BENCH_GRAFANA_URL}" in
            http://127.0.0.1:*|http://localhost:*)
                echo "❌ bench_prom_query: BENCH_PROM_AUTH=1 needs BENCH_GRAFANA_URL to point at the obs-devnet Grafana, not the bench-obs forward (${BENCH_GRAFANA_URL})" >&2
                return 1 ;;
        esac
        pw="$(tn_secret "${OBS_GRAFANA_SECRET_NAME}")" || return 1
        esc="$(printf '%s' "${pw}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
        printf 'user = "admin:%s"\n' "${esc}" | curl -sS --max-time 20 -K - --get \
            --data-urlencode "query=$1" \
            "${BENCH_GRAFANA_URL}/api/datasources/proxy/uid/${BENCH_PROM_DATASOURCE_UID}/api/v1/query"
    fi
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
    tok="$(perl -e 'alarm 90; exec @ARGV' gcloud auth print-access-token </dev/null 2>/dev/null)" || return 0   # "" = unavailable, never fatal
    now="$(bench_now_unix)"; start=$((now - ${2:-600}))
    printf 'header = "Authorization: Bearer %s"\n' "${tok}" | curl -sS --max-time 20 -K - --get \
        --data-urlencode "filter=$1" \
        --data-urlencode "interval.startTime=$(bench_iso_from_unix "${start}")" \
        --data-urlencode "interval.endTime=$(bench_iso_from_unix "${now}")" \
        "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/timeSeries" \
        | jq -r '[.timeSeries[]?.points[0].value | (.doubleValue // .int64Value // empty) | tonumber] | max // empty' 2>/dev/null || true
}

# --- container images (digest, pin) -------------------------------------------------------
# Tags are mutable: a step that must run the bytes an earlier step examined names the image as
# <repo>@sha256:<digest>, resolved once (bench_image_digest) and pinned (bench_image_pin).
BENCH_MANIFEST_ACCEPT="application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"

# _bench_is_digest <s> — 0 for sha256:<64 lower-case hex>.
_bench_is_digest() {
    local h="${1#sha256:}"
    [ "${h}" != "${1:-}" ] && [ "${#h}" -eq 64 ] || return 1
    case "${h}" in *[!0123456789abcdef]*) return 1 ;; esac
}

# _bench_gcp_registry_host <host> — 0 for an Artifact Registry or Container Registry host: the
# only hosts the operator's gcloud access token is ever sent to.
_bench_gcp_registry_host() {
    case "$1" in *-docker.pkg.dev|gcr.io|*.gcr.io) return 0 ;; esac
    return 1
}

# bench_image_digest <ref> — the digest (sha256:<64 hex>) the registry serves for <ref> now; ""
# when it cannot be resolved (never fatal). A <repo>@sha256:<digest> ref answers from the ref.
# Otherwise `gcloud artifacts docker images describe` (needs read access to that repository's
# project), then a HEAD on https://<host>/v2/<path>/manifests/<tag> read from its
# Docker-Content-Digest header, for Google registry hosts only; the access token reaches curl
# on STDIN (-K -), never on a command line.
bench_image_digest() {
    local ref="${1:-}" d host rest path tag tok hdr
    case "${ref}" in
        *@sha256:*) d="sha256:${ref##*@sha256:}"; _bench_is_digest "${d}" && printf '%s\n' "${d}"; return 0 ;;
        '') return 0 ;;
    esac
    # gcloud once hung here for 10+ minutes (credential-store contention); a 90 s alarm and a
    # closed stdin make a stuck describe fall through to the registry HEAD below instead.
    d="$(perl -e 'alarm 90; exec @ARGV' gcloud artifacts docker images describe "${ref}" \
        --format='value(image_summary.digest)' </dev/null 2>/dev/null || true)"
    if _bench_is_digest "${d}"; then printf '%s\n' "${d}"; return 0; fi
    case "${ref}" in */*) ;; *) return 0 ;; esac
    host="${ref%%/*}"; rest="${ref#*/}"
    _bench_gcp_registry_host "${host}" || return 0
    case "${rest##*/}" in *:*) path="${rest%:*}"; tag="${rest##*:}" ;; *) path="${rest}"; tag="latest" ;; esac
    tok="$(perl -e 'alarm 90; exec @ARGV' gcloud auth print-access-token </dev/null 2>/dev/null)" || return 0
    [ -n "${tok}" ] || return 0
    hdr="$(printf 'header = "Authorization: Bearer %s"\n' "${tok}" | curl -sS -I --max-time 20 -K - \
        -H "Accept: ${BENCH_MANIFEST_ACCEPT}" "https://${host}/v2/${path}/manifests/${tag}" 2>/dev/null || true)"
    d="$(printf '%s\n' "${hdr}" | tr -d '\r' \
        | awk 'NR == 1 && $2 != "200" { exit } tolower($1) == "docker-content-digest:" { print $2; exit }')"
    if _bench_is_digest "${d}"; then printf '%s\n' "${d}"; fi
    return 0
}

# bench_image_pin <ref> <digest> — <repo>@<digest>: <ref> minus any @digest and any :tag.
# Non-zero and no output unless <digest> is sha256:<64 hex>.
bench_image_pin() {
    local r="${1%%@*}"
    _bench_is_digest "${2:-}" || return 1
    case "${r##*/}" in *:*) r="${r%:*}" ;; esac
    printf '%s@%s\n' "${r}" "$2"
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
bench_txgen_image_digest() { bench_image_digest "${BENCH_TXGEN_IMAGE}"; }

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
    perl -e 'alarm 90; exec @ARGV' gcloud auth print-access-token </dev/null 2>/dev/null \
        | docker --config "${cfg}" login -u oauth2accesstoken --password-stdin "https://${BENCH_TXGEN_IMAGE%%/*}" >/dev/null 2>&1 || true
    help="$(docker --config "${cfg}" run --rm --platform linux/amd64 "${BENCH_TXGEN_IMAGE}" blast --help 2>&1 || true)"
    rm -rf "${cfg}"
    # The landings export (BENCH_LANDINGS_SAMPLE > 0) adds two flags the bench-4 image lacks; require
    # them here so an old blaster image fails in preflight, not on its VM.
    local flags="${BENCH_TXGEN_CONTRACT_FLAGS}"
    [ "${BENCH_LANDINGS_SAMPLE:-0}" = "0" ] || flags="${flags} --landings-out --landings-sample"
    for f in ${flags}; do
        grep -Eq -- "(^|[^a-z-])${f}([^a-z-]|$)" <<<"${help}" || missing="${missing} ${f}"
    done
    if [ -n "${missing}" ]; then
        printf '%s\n' "${help}" | head -15 >&2
        bench_die "${BENCH_TXGEN_IMAGE} 'blast --help' lacks:${missing} (or the image could not be run; BENCH_SKIP_CLI_PROBE=1 to skip)"
    fi
    echo "    ✓ ${BENCH_TXGEN_IMAGE} blast --help carries every contract flag (incl. --stdout-json)"
}

# --- node image (the binary under test) ------------------------------------------------------
# What the benchmark requires of the node image; bench_node_image_probe checks it before any
# fleet exists. Fixed here, not knobs. The strings the binary must carry: node-image-contract.txt.
BENCH_NODE_CONTRACT_FILE="${BENCH_LIB_DIR}/node-image-contract.txt"
BENCH_NODE_BIN="/usr/local/bin/telcoin"
# --log.* filter flags: the pre-start script (deploy step 7) puts BENCH_NODE_LOG_FILTER /
# BENCH_NODE_LOG_MAX_FILES on the command line.
BENCH_NODE_FLAGS_NODE="--datadir --log.stdout.format --log.stdout.filter --log.file.filter --log.file.max-files --http --http.addr --ws --ws.addr --healthcheck --metrics"
BENCH_NODE_FLAGS_GENESIS="--datadir --chain-id --bls-passphrase-source --accounts --epoch-duration-in-secs --min-header-delay-ms --max-header-delay-ms"
BENCH_NODE_FLAGS_KEYTOOL="--datadir --address --external-primary-addr --external-worker-addrs"

# _bench_help_missing <help-text> <flag...> — the flags <help-text> lacks, each with a leading
# space ("" = all there). The word-boundary match of bench_txgen_cli_probe, with the flag's dots
# literal and '.' counted as part of a flag, so --http.addr does not stand in for --http.
_bench_help_missing() {
    local help="$1" f re missing=""
    shift
    for f in "$@"; do
        re="$(printf '%s' "${f}" | sed 's/[.]/[.]/g')"
        LC_ALL=C grep -Eq -- "(^|[^a-z.-])${re}([^a-z.-]|$)" <<<"${help}" || missing="${missing} ${f}"
    done
    printf '%s' "${missing}"
}

# _bench_node_exec <image> <arg...> — run the node binary itself (not the image's entrypoint) in a
# throwaway amd64 container. Never pulls: the probe has pulled <image> by digest already.
_bench_node_exec() {
    local img="$1"; shift
    docker run --rm --pull=never --platform linux/amd64 --entrypoint "${BENCH_NODE_BIN}" "${img}" "$@"
}

# _bench_node_help_check <image> <flags> <subcommand...> — die unless `telcoin <subcommand...>
# --help` lists every flag of the space-separated <flags> (the first 15 help lines go to stderr).
_bench_node_help_check() {
    local img="$1" flags="$2" help missing
    shift 2
    help="$(_bench_node_exec "${img}" "$@" --help 2>&1 || true)"
    # shellcheck disable=SC2086  # <flags> is a space-separated list
    missing="$(_bench_help_missing "${help}" ${flags})"
    if [ -n "${missing}" ]; then
        printf '%s\n' "${help}" | head -15 >&2
        bench_die "node image ${img}: 'telcoin $* --help' lacks:${missing}"
    fi
}

# _bench_node_image_probe_run <ref> — the body of bench_node_image_probe, in a subshell so its
# EXIT trap removes the temp dirs and the container it created however it ends, without touching
# the caller's traps. Progress on stdout, refusals through bench_die (which ends the subshell),
# the results on fd 3 as KEY<TAB>value lines.
_bench_node_image_probe_run() (
    ref="$1"; work=""; cfg=""; cid=""
    trap '[ -z "${cid}" ] || docker rm -f "${cid}" >/dev/null 2>&1; [ -z "${cfg}" ] || rm -rf "${cfg}"; [ -z "${work}" ] || rm -rf "${work}"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    # The expectations first: a malformed one must not cost a pull.
    exp_digest="${BENCH_DOCKER_IMAGE_EXPECT_DIGEST:-}"
    exp_sha="$(printf '%s' "${BENCH_NODE_EXPECT_SHA:-}" | tr 'ABCDEF' 'abcdef')"
    exp_forks="${BENCH_NODE_EXPECT_FORKS:-}"
    if [ -n "${exp_digest}" ] && ! _bench_is_digest "${exp_digest}"; then
        bench_die "BENCH_DOCKER_IMAGE_EXPECT_DIGEST='${exp_digest}' is not sha256:<64 lower-case hex>"
    fi
    case "${exp_sha}" in
        '') ;;
        *[!0123456789abcdef]*) bench_die "BENCH_NODE_EXPECT_SHA='${BENCH_NODE_EXPECT_SHA}' is not a hex git sha" ;;
        *) [ "${#exp_sha}" -ge 7 ] && [ "${#exp_sha}" -le 40 ] || bench_die "BENCH_NODE_EXPECT_SHA='${BENCH_NODE_EXPECT_SHA}' must be 7-40 hex characters" ;;
    esac
    case "${exp_forks}" in
        ''|subsecond-from-genesis|adiri-schedule|pre-subsecond) ;;
        *) bench_die "BENCH_NODE_EXPECT_FORKS='${exp_forks}' is not one of: subsecond-from-genesis adiri-schedule pre-subsecond" ;;
    esac
    [ -f "${BENCH_NODE_CONTRACT_FILE}" ] && [ -r "${BENCH_NODE_CONTRACT_FILE}" ] \
        || bench_die "node image contract ${BENCH_NODE_CONTRACT_FILE} is missing"

    # 1. docker: mandatory, no skip knob.
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
        bench_die "the node image probe needs a running docker (it is mandatory: the benchmark never runs a node image it has not examined)"
    fi

    # 2. The digest the tag names now; everything after this uses <repo>@<digest>.
    digest="$(bench_image_digest "${ref}")"
    [ -n "${digest}" ] || bench_die "node image ${ref}: no registry digest (tag absent, or no read access to its repository)"
    pinned="$(bench_image_pin "${ref}" "${digest}")" || bench_die "node image ${ref}: cannot pin to ${digest}"
    if [ -n "${exp_digest}" ] && [ "${exp_digest}" != "${digest}" ]; then
        bench_die "node image ${ref} resolves to ${digest}, not BENCH_DOCKER_IMAGE_EXPECT_DIGEST=${exp_digest}"
    fi
    echo "    ✓ node image digest: ${digest}"
    echo "    ✓ pinned ref: ${pinned}"

    # 3. Pull by digest, logged in through a throwaway --config dir (the operator's docker config
    # is never touched; the access token goes only to a Google registry host).
    work="$(mktemp -d)" && cfg="$(mktemp -d)" || bench_die "mktemp failed"
    case "${ref}" in
        */*) if _bench_gcp_registry_host "${ref%%/*}"; then
                 perl -e 'alarm 90; exec @ARGV' gcloud auth print-access-token </dev/null 2>/dev/null \
                     | docker --config "${cfg}" login -u oauth2accesstoken --password-stdin "https://${ref%%/*}" >/dev/null 2>&1 || true
             fi ;;
    esac
    if docker --config "${cfg}" pull --quiet --platform linux/amd64 "${pinned}" >/dev/null 2>"${work}/pull.err"; then
        img="${pinned}"
    elif docker image inspect "${ref}" >/dev/null 2>&1; then
        # A local image (tests, or an offline host). Its bytes are the pinned ones only when its
        # repo digests say so; an applied run refuses anything else.
        rd="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "${ref}" 2>/dev/null || true)"
        if _bench_in_lines "${pinned}" "${rd}"; then
            bench_warn "pull of ${pinned} failed; probing the local ${ref}, whose repo digest is ${digest}"
        elif [ "${BENCH_APPLY:-0}" = "1" ]; then
            tail -3 "${work}/pull.err" >&2
            bench_die "pull of ${pinned} failed and the local ${ref} is not ${digest} — refusing to certify other bytes than the fleet would run"
        else
            bench_warn "pull of ${pinned} failed ($(tail -1 "${work}/pull.err")); dry run: probing the LOCAL ${ref}, NOT verified to be ${digest}"
        fi
        img="${ref}"
    else
        tail -5 "${work}/pull.err" >&2
        bench_die "node image ${pinned} could not be pulled, and ${ref} is not a local image"
    fi
    rm -rf "${cfg}"; cfg=""

    # 4. Version and git sha, from the binary itself.
    vout="$(_bench_node_exec "${img}" -V 2>"${work}/v.err")" \
        || { tail -5 "${work}/v.err" >&2; bench_die "node image ${img}: '${BENCH_NODE_BIN} -V' failed"; }
    vline="$(printf '%s\n' "${vout}" | awk 'NF { print; exit }')"
    re='^([^[:space:]]+ )?(v?[0-9][^[:space:]]*) [(]([0-9a-f]+|unknown)[)][[:space:]]*$'
    [[ "${vline}" =~ ${re} ]] || bench_die "node image ${img}: cannot parse '-V' output '${vline}' (want '[name ]<version> (<git sha>)')"
    version="${BASH_REMATCH[2]}"; sha="${BASH_REMATCH[3]}"
    if [ "${sha}" = "unknown" ]; then
        bench_die "node image ${img}: '-V' says '${vline}' — image built without git metadata; refuse to benchmark an image whose source cannot be named"
    fi
    lout="$(_bench_node_exec "${img}" --version 2>&1)" || bench_die "node image ${img}: '${BENCH_NODE_BIN} --version' failed"
    case "${lout}" in
        *"Commit SHA:"*)
            csha="$(printf '%s\n' "${lout}" | awk '/Commit SHA:/ { sub(/.*Commit SHA:[ \t]*/, ""); print $1; exit }')"
            case "${csha}" in
                ''|*[!0123456789abcdef]*) bench_die "node image ${img}: '--version' Commit SHA '${csha}' is not a git sha" ;;
                "${sha}"*) sha="${csha}" ;;   # the longer of the two
            esac
            case "${sha}" in
                "${csha}"*) ;;
                *) bench_die "node image ${img}: '-V' names ${sha} but '--version' names Commit SHA ${csha}" ;;
            esac ;;
    esac
    if [ -n "${exp_sha}" ]; then
        case "${sha}" in
            "${exp_sha}"*) ;;
            *) bench_die "node image ${img} is git ${sha}, not BENCH_NODE_EXPECT_SHA=${exp_sha}" ;;
        esac
    fi
    echo "    ✓ version ${version}, git sha ${sha}"

    # 5. The CLI flags the deploy passes.
    _bench_node_help_check "${img}" "${BENCH_NODE_FLAGS_NODE}" node
    _bench_node_help_check "${img}" "${BENCH_NODE_FLAGS_GENESIS}" genesis
    _bench_node_help_check "${img}" "${BENCH_NODE_FLAGS_KEYTOOL}" keytool generate validator
    echo "    ✓ flags ok: node, genesis, keytool generate validator --help carry every contract flag"

    # 6. The contract strings, counted in the binary copied out of the image.
    cid="$(docker create --pull=never --platform linux/amd64 --entrypoint "${BENCH_NODE_BIN}" "${img}" 2>"${work}/c.err")" \
        || { tail -3 "${work}/c.err" >&2; bench_die "node image ${img}: docker create failed"; }
    docker cp -L "${cid}:${BENCH_NODE_BIN}" "${work}/telcoin" >/dev/null 2>"${work}/c.err" \
        || { tail -3 "${work}/c.err" >&2; bench_die "node image ${img}: cannot copy ${BENCH_NODE_BIN} out of it"; }
    docker rm -f "${cid}" >/dev/null 2>&1; cid=""
    [ -s "${work}/telcoin" ] || bench_die "node image ${img}: ${BENCH_NODE_BIN} is empty"
    : > "${work}/counts"
    ln=0; n=0; nreq=0; nsub=0; sub_all=1; forbid=""; missing=""
    while IFS= read -r line || [ -n "${line}" ]; do
        ln=$((ln + 1))
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        case "${line}" in ''|'#'*) continue ;; esac
        d="${line%% *}"; s="${line#* }"; s="${s#"${s%%[! ]*}"}"
        if [ "${d}" = "${line}" ] || [ -z "${s}" ]; then
            bench_die "${BENCH_NODE_CONTRACT_FILE}:${ln}: '${line}' is not '<directive> <string>'"
        fi
        c="$(LC_ALL=C grep -a -c -F -- "${s}" "${work}/telcoin")"
        [ "$?" -le 1 ] && [ -n "${c}" ] || bench_die "grep failed on the copied binary"
        printf '%s\t%s\n' "${c}" "${s}" >> "${work}/counts"
        n=$((n + 1))
        case "${d}" in
            require) nreq=$((nreq + 1)); [ "${c}" -gt 0 ] || missing="${missing}"$'\n'"      ${s}" ;;
            require-if-subsecond) nsub=$((nsub + 1)); [ "${c}" -gt 0 ] || sub_all=0 ;;
            forbid-if-subsecond) [ "${c}" -eq 0 ] || forbid="${forbid} '${s}'" ;;
            *) bench_die "${BENCH_NODE_CONTRACT_FILE}:${ln}: unknown directive '${d}'" ;;
        esac
    done < "${BENCH_NODE_CONTRACT_FILE}"
    [ "${nreq}" -gt 0 ] || bench_die "${BENCH_NODE_CONTRACT_FILE} has no require line"
    [ -z "${missing}" ] || bench_die "node image ${img}: ${BENCH_NODE_BIN} lacks these contract strings:${missing}"
    if [ "${nsub}" -gt 0 ] && [ "${sub_all}" -eq 1 ]; then
        [ -z "${forbid}" ] || bench_die "node image ${img}: image carries both markers: the sub-second ones and${forbid}"
        forks="subsecond-from-genesis"
    elif [ -n "${forbid}" ]; then
        forks="adiri-schedule"
    else
        forks="pre-subsecond"
    fi
    if [ -n "${exp_forks}" ] && [ "${exp_forks}" != "${forks}" ]; then
        bench_die "node image ${img}: fork schedule is ${forks}, not BENCH_NODE_EXPECT_FORKS=${exp_forks}"
    fi
    strings="$(jq -Rnc '[inputs | capture("^(?<c>[0-9]+)\t(?<s>.*)$") | {key: .s, value: (.c | tonumber)}] | from_entries' < "${work}/counts")" \
        || bench_die "could not build the string counts JSON"
    echo "    ✓ fork schedule: ${forks}"
    echo "    ✓ ${n} contract strings checked (${nreq} required, all present)"

    # 7. Hand the results to bench_node_image_probe.
    printf '%s\t%s\n' BENCH_NODE_PROBE_AT "$(bench_now_iso)" BENCH_NODE_IMAGE_REF "${ref}" \
        BENCH_NODE_IMAGE_DIGEST "${digest}" BENCH_NODE_IMAGE_PINNED "${pinned}" BENCH_NODE_VERSION "${version}" \
        BENCH_NODE_GIT_SHA "${sha}" BENCH_NODE_FORK_SCHEDULE "${forks}" BENCH_NODE_FLAGS_OK 1 \
        BENCH_NODE_STRINGS_JSON "${strings}" >&3
)

# bench_node_image_probe <ref> — examine the node image the fleet will run; die on any failure.
# Resolves <ref> to its registry digest (BENCH_DOCKER_IMAGE_EXPECT_DIGEST, when set, must match),
# pulls <repo>@<digest>, runs ${BENCH_NODE_BIN} -V and --version (a git sha is required, the two
# must agree, and BENCH_NODE_EXPECT_SHA, 7-40 hex, must prefix it), checks the CLI flags of
# node / genesis / keytool generate validator --help, and counts every string of
# node-image-contract.txt in the binary: each `require` must be present; the fork schedule is
# subsecond-from-genesis (all require-if-subsecond present, refused if a forbid-if-subsecond one is
# too), adiri-schedule (a forbid-if-subsecond present) or pre-subsecond (neither), and must equal
# BENCH_NODE_EXPECT_FORKS when that is set. Needs docker; there is no skip. A pull failure falls
# back to a local image of <ref> (tests); unless its repo digest is <digest>, only in a dry run.
# Exports BENCH_NODE_PROBE_AT, BENCH_NODE_IMAGE_REF, BENCH_NODE_IMAGE_DIGEST,
# BENCH_NODE_IMAGE_PINNED, BENCH_NODE_VERSION, BENCH_NODE_GIT_SHA, BENCH_NODE_FORK_SCHEDULE,
# BENCH_NODE_FLAGS_OK=1 and BENCH_NODE_STRINGS_JSON ({"<string>": <count>, ...}).
bench_node_image_probe() {
    local res="" rc=0 k v
    [ -n "${1:-}" ] || bench_die "bench_node_image_probe <image-ref>"
    echo "    probing node image ${1}"
    { res="$(_bench_node_image_probe_run "$1" 3>&1 1>&4)" || rc=$?; } 4>&1
    [ "${rc}" -eq 0 ] || exit "${rc}"
    while IFS="$(printf '\t')" read -r k v; do
        case "${k}" in
            BENCH_NODE_PROBE_AT|BENCH_NODE_IMAGE_REF|BENCH_NODE_IMAGE_DIGEST|BENCH_NODE_IMAGE_PINNED|\
            BENCH_NODE_VERSION|BENCH_NODE_GIT_SHA|BENCH_NODE_FORK_SCHEDULE|BENCH_NODE_FLAGS_OK|BENCH_NODE_STRINGS_JSON)
                printf -v "${k}" '%s' "${v}"
                export "${k?}" ;;
        esac
    done <<< "${res}"
    [ "${BENCH_NODE_FLAGS_OK:-}" = "1" ] && [ "${BENCH_NODE_IMAGE_REF:-}" = "$1" ] \
        || bench_die "node image probe of $1 returned no result"
}

# bench_node_probe_manifest — record this shell's bench_node_image_probe in the manifest:
# node_image_ref, node_image_digest, node_image_pinned, node_version, node_git_sha,
# node_fork_schedule and node_probe {at, flags_ok, strings}. Non-zero when no probe has run.
bench_node_probe_manifest() {
    if [ -z "${BENCH_NODE_IMAGE_DIGEST:-}" ] || [ -z "${BENCH_NODE_STRINGS_JSON:-}" ]; then
        echo "❌ bench_node_probe_manifest: no node image probe in this shell (run bench_node_image_probe first)" >&2
        return 1
    fi
    bench_manifest_jq --arg ref "${BENCH_NODE_IMAGE_REF}" --arg dg "${BENCH_NODE_IMAGE_DIGEST}" \
        --arg pin "${BENCH_NODE_IMAGE_PINNED}" --arg ver "${BENCH_NODE_VERSION}" --arg sha "${BENCH_NODE_GIT_SHA}" \
        --arg fs "${BENCH_NODE_FORK_SCHEDULE}" --arg at "${BENCH_NODE_PROBE_AT}" --arg ok "${BENCH_NODE_FLAGS_OK:-}" \
        --argjson strings "${BENCH_NODE_STRINGS_JSON}" '
        .node_image_ref = $ref | .node_image_digest = $dg | .node_image_pinned = $pin
        | .node_version = $ver | .node_git_sha = $sha | .node_fork_schedule = $fs
        | .node_probe = {at: $at, flags_ok: ($ok == "1"), strings: $strings}'
}

# bench_consensus_params_manifest — record PARAMETERS_FILE in the manifest: consensus_parameters
# {file (its basename), sha256, max_header_delay_ms, min_header_delay_ms, max_batch_delay_ms}; a
# key the file lacks (or cannot be read as a duration) is null. Non-zero when the file is unreadable.
# Then the per-node part (bench_node_params_manifest): consensus_parameters.overrides and
# node_startup[<instance>].log_filter / .log_max_files.
bench_consensus_params_manifest() {
    local f="${PARAMETERS_FILE:-}" sha
    if ! sha="$(bench_file_sha256 "${f}")"; then
        echo "❌ bench_consensus_params_manifest: cannot read PARAMETERS_FILE '${f}'" >&2
        return 1
    fi
    bench_manifest_jq --arg file "${f##*/}" --arg sha "${sha}" \
        --arg max "$(bench_params_ms "${f}" max_header_delay)" \
        --arg min "$(bench_params_ms "${f}" min_header_delay)" \
        --arg batch "$(bench_params_ms "${f}" max_batch_delay)" '
        def num_or_null: if . == "" then null else tonumber end;
        .consensus_parameters = {file: $file, sha256: $sha, max_header_delay_ms: ($max | num_or_null),
                                 min_header_delay_ms: ($min | num_or_null),
                                 max_batch_delay_ms: ($batch | num_or_null)}' || return 1
    bench_node_params_manifest
}

# --- per-node consensus parameters and node log filter ------------------------------------------
# BENCH_NODE_PARAM_OVERRIDES (config.sh checks its syntax and keys) puts per-node values on top of
# PARAMETERS_FILE; the pre-start script of deploy step 7 (bench_prestart_script) writes them into each
# node's <datadir>/parameters.yaml, and BENCH_NODE_LOG_FILTER onto its command line, while the unit is
# stopped, before the coordinated start; step 9 only reads them back (it restarts nothing). Live changes
# between sweep arms are tools/params-apply.sh's (it records manifest.param_arms), not these helpers'.

# bench_node_overrides <node-index> — that node's overrides, one "<key>=<value>" per line (none: no output).
bench_node_overrides() {
    local item
    for item in ${BENCH_NODE_PARAM_OVERRIDES:-}; do
        [ "${item%%:*}" = "${1:-}" ] || continue
        printf '%s\n' "${item#*:}" | tr ',' '\n'
    done
}

# bench_node_override <node-index> <key> — the node's override of <key> as written ("" when none).
bench_node_override() { bench_node_overrides "$1" | sed -n "s/^$2=//p" | tail -1; }

# bench_dur_ms <value> — a knob duration (<int>ms or <int>s) in ms; "" for anything else.
bench_dur_ms() {
    awk -v v="${1:-}" 'BEGIN {
        if (v ~ /^[0-9]+ms$/) { sub(/ms$/, "", v); printf "%d\n", v }
        else if (v ~ /^[0-9]+s$/) { sub(/s$/, "", v); printf "%d\n", v * 1000 }
    }'
}

# bench_params_raw <file> <key> — a top-level scalar of a parameters YAML as written (comment and
# quotes stripped); "" when absent, unreadable or a block.
bench_params_raw() {
    [ -r "${1:-}" ] && [ -n "${2:-}" ] || return 0
    awk -v k="$2" 'index($0, k ":") == 1 {
        v = substr($0, length(k) + 2); sub(/^[ \t]+/, "", v); sub(/(^|[ \t]+)#.*$/, "", v); sub(/[ \t]+$/, "", v)
        gsub(/^["\047]|["\047]$/, "", v); print v; exit }' "$1"
}

# bench_node_param_ms <node-index> <key> — what the pre-start script leaves node <node-index> with for a
# duration key, in ms: its override, else PARAMETERS_FILE's value ("" when the file lacks the key).
bench_node_param_ms() {
    local ov
    ov="$(bench_node_override "$1" "$2")"
    if [ -n "${ov}" ]; then bench_dur_ms "${ov}"; else bench_params_ms "${PARAMETERS_FILE}" "$2"; fi
}

# bench_node_param_int <node-index> <key> — the same for an integer key.
bench_node_param_int() {
    local ov
    ov="$(bench_node_override "$1" "$2")"
    printf '%s' "${ov:-$(bench_params_raw "${PARAMETERS_FILE}" "$2")}"
}

# bench_node_params_problems — one line per node whose effective parameters the node would refuse at
# startup (crates/config/src/node.rs validate_operational_floors, consensus.rs validate_vote_timeout
# at ba43a1f0e): min_header_delay > max_header_delay, header_num_of_batches_threshold outside
# 1..max_header_num_of_batches, vote_timeout (5 s when unset) below max_header_delay + 250 ms (the
# drift tolerance, sub-second builds) or at/above 10 s. No output when every node is fine.
bench_node_params_problems() {
    local i inst mx mn vt thr cap
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        mx="$(bench_node_param_ms "${i}" max_header_delay)"; mn="$(bench_node_param_ms "${i}" min_header_delay)"
        vt="$(bench_node_param_ms "${i}" vote_timeout)"; vt="${vt:-5000}"
        thr="$(bench_node_param_int "${i}" header_num_of_batches_threshold)"
        cap="$(bench_node_param_int "${i}" max_header_num_of_batches)"
        if [ -n "${mx}" ] && [ -n "${mn}" ] && [ "${mn}" -gt "${mx}" ]; then
            echo "${inst}: min_header_delay ${mn} ms > max_header_delay ${mx} ms"
        fi
        if [ -n "${mx}" ] && [ "${vt}" -lt $((mx + 250)) ]; then
            echo "${inst}: vote_timeout ${vt} ms < max_header_delay ${mx} ms + 250 ms drift tolerance"
        fi
        [ "${vt}" -lt 10000 ] || echo "${inst}: vote_timeout ${vt} ms is not below the 10 s libp2p request timeout"
        case "${thr}:${cap}" in
            *[!0-9:]*|:*|*:) ;;
            *) if [ "${thr}" -lt 1 ] || [ "${thr}" -gt "${cap}" ]; then
                   echo "${inst}: header_num_of_batches_threshold ${thr} is outside 1..max_header_num_of_batches ${cap}"
               fi ;;
        esac
    done
}

# bench_node_overrides_json — BENCH_NODE_PARAM_OVERRIDES as compact JSON {<instance>: {<key>: "<value>"}}.
bench_node_overrides_json() {
    local i kv
    for i in "${!INSTANCE_NAMES[@]}"; do
        bench_node_overrides "${i}" | while IFS= read -r kv; do
            printf '%s\t%s\t%s\n' "${INSTANCE_NAMES[$i]}" "${kv%%=*}" "${kv#*=}"
        done
    done | jq -c -R -s 'split("\n") | map(select(length > 0) | split("\t")) | reduce .[] as $r ({}; .[$r[0]][$r[1]] = $r[2])'
}

# bench_node_params_manifest — record what the pre-start script (deploy step 7) applies per node:
# consensus_parameters.overrides = {<instance>: {<key>: "<value>"}} (nodes with overrides only; {} when none), and
# node_startup[<instance>].log_filter / .log_max_files (null when BENCH_NODE_LOG_FILTER is empty:
# the node's command line is left as it is). Step 9 (verify only) overwrites both log fields with what
# it reads back from the running node.
bench_node_params_manifest() {
    local ov insts mf=""
    ov="$(bench_node_overrides_json)" || return 1
    insts="$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R -s 'split("\n") | map(select(length > 0))')" || return 1
    [ -z "${BENCH_NODE_LOG_FILTER:-}" ] || mf="${BENCH_NODE_LOG_MAX_FILES:-}"
    bench_manifest_jq --argjson ov "${ov}" --argjson insts "${insts}" --arg f "${BENCH_NODE_LOG_FILTER:-}" \
        --arg mf "${mf}" '
        .consensus_parameters = ((.consensus_parameters // {}) + {overrides: $ov})
        | reduce $insts[] as $i (.; .node_startup[$i] = ((.node_startup[$i] // {})
            + {log_filter: (if $f == "" then null else $f end),
               log_max_files: (if $mf == "" then null else ($mf | tonumber) end)}))'
}

# --- local results: results/<run>/ until the run is archived ---------------------------------
# Since 2026-10-08 the canonical copy of a finished run is the project's GCS archive bucket for
# bench runs (benchmark/README.md names it); results/<run>/ is a transient working copy, pruned
# only after the archive is verified to hold every file at the same size and MD5. The run bucket
# gs://tn-devnet-bench-<run> is only the blasters' upload transport: the teardown copies it into
# results/<run>/bucket/ and deletes it. So the teardown's local gate proves, before its first
# delete, that results/<run>/ holds every node's logs and the manifest, and leaves INDEX.md and
# CHECKSUMS.sha256 beside them.

# _bench_sha256_cmd — the SHA-256 tool, printed one word per line: shasum -a 256 where it exists
# (macOS), else sha256sum (Linux). Both print "<hex>  <file>" and both check with -c.
_bench_sha256_cmd() {
    if command -v shasum >/dev/null 2>&1; then printf '%s\n' shasum -a 256
    elif command -v sha256sum >/dev/null 2>&1; then printf '%s\n' sha256sum
    else echo "❌ neither shasum nor sha256sum is on PATH" >&2; return 1; fi
}

# _bench_results_files <dir> — every regular file under <dir> as a path relative to it, sorted,
# one per line, except CHECKSUMS.sha256 and its temp files.
_bench_results_files() {
    (cd "$1" && find . -type f ! -path ./CHECKSUMS.sha256 ! -path './.CHECKSUMS.sha256.*' | sed 's#^\./##' | LC_ALL=C sort)
}

# _bench_results_totals <dir> — "<files> <bytes>" over _bench_results_files <dir>.
_bench_results_totals() {
    (cd "$1" && find . -type f ! -path ./CHECKSUMS.sha256 ! -path './.CHECKSUMS.sha256.*' -exec wc -c {} + \
        | awk '!(NF == 2 && $2 == "total") { n++; b += $1 } END { printf "%d %d\n", n, b }')
}

# _bench_index_kind <path> — "<order>|<group>|<what it is>|<written by>" for a path relative to
# results/<run>/, from the patterns below (first match wins); unknown paths get order 99 and their
# own row. INDEX.md lists the groups by <order>.
_bench_index_kind() {
    case "$1" in
        .DS_Store|*/.DS_Store) echo "29|.DS_Store, */.DS_Store|macOS Finder metadata|not the harness" ;;
        manifest.json) echo "01|manifest.json|run manifest: fleet, image, parameters, phases, blast, chaos, stalls, notes, archive (local gate)|benchmark-deploy.sh, benchmark-blast.sh, benchmark-teardown.sh" ;;
        INDEX.md) echo "02|INDEX.md|this index|bench_local_index (collect, deploy step 15, teardown)" ;;
        CHECKSUMS.sha256) echo "03|CHECKSUMS.sha256|SHA-256 of every other file here; check: shasum -a 256 -c CHECKSUMS.sha256|bench_local_index (collect, deploy step 15, teardown)" ;;
        analysis/cert-rate.md) echo "04|analysis/cert-rate.md|per-validator certification rate per window (tools/cert-rate.py)|bench_local_analysis (collect, deploy step 15, teardown)" ;;
        analysis/block-rate.md) echo "05|analysis/block-rate.md|rounds/s, blocks/s, tx/s and commit latency per window (tools/block-rate.py)|bench_local_analysis (collect, deploy step 15, teardown)" ;;
        analysis/certification.json) echo "04|analysis/certification.json|tools/cert-rate.py --format json: the certification outcome behind manifest.certification and .cert_failures|bench_certification_record (collect, teardown before the local gate)" ;;
        # Analysis the harness does not write (a sweep's summaries, per-arm tables, often added after
        # the teardown; --reindex indexes them): a row per top-level file, one per directory.
        analysis/*/*) echo "06|${1%"${1#analysis/*/}"}*|other analysis output, one directory|not the harness" ;;
        analysis/*) echo "06|$1|other analysis output|not the harness" ;;
        metrics.json) echo "07|metrics.json|Cloud Monitoring + Prometheus series over the run window|deploy step 15 (tn-transaction-generator collect-gcp-metrics.py)" ;;
        pre-instances.json|pre-firewall.json) echo "08|pre-instances.json, pre-firewall.json|project snapshot before the run (the teardown compares the devnet rule to it)|benchmark-deploy.sh preflight" ;;
        deployments-bench.json) echo "09|deployments-bench.json|app contract addresses on the bench chain|deploy step 11" ;;
        tunnel.log|tunnel.pid) echo "10|tunnel.log, tunnel.pid|local IAP tunnel to the first node's RPC (tunnel.log is appended: one 'tunnel: start' line per start)|bench_tunnel_up (deploy step 10)" ;;
        tunnel*.pid) echo "10|tunnel-<forward>.pid|supervisor pid of a local IAP forward to bench-obs (tunnel-obs-prom.pid: Prometheus :9090, tunnel-obs-grafana.pid: Grafana :3000; their starts are in tunnel.log)|bench_obs_tunnel_up (obs-lib.sh: deploy, blast run, teardown)" ;;
        bench-obs-prometheus-*.tar.gz|logs/bench-obs-prometheus-*.tar.gz) echo "13|${1%bench-obs-prometheus-*}bench-obs-prometheus-<UTC>.tar.gz|snapshot of the bench-obs Prometheus TSDB (admin API), every series of the run; untar and point a Prometheus at it|bench_obs_prom_snapshot_pull (obs-lib.sh: teardown before the local gate)" ;;
        last-deploy.status) echo "08|last-deploy.status|the last deploy invocation's outcome: rc, last step, first error, start and end, scope, log|benchmark-deploy.sh" ;;
        zones.env) echo "08|zones.env|the zone each node was created in (BENCH_ZONES_USED; config.sh reads it back)|benchmark-deploy.sh step 2" ;;
        chaos-remote.log) echo "11|chaos-remote.log|output of the staged chaos sessions on the nodes|benchmark-blast.sh run (chaos)" ;;
        logs/*.pulled|logs/*.pulled-*) echo "12|logs/<node>.pulled*|pull markers: which instance id each node log came from|teardown log gate (bench_pull_node_logs)" ;;
        logs/*-recovery-*.tgz) echo "13|logs/<node>-recovery-<id>.*.tgz|service journal + sampler files of the node (recovery evidence)|teardown (recovery-lib.sh bench_pull_recovery_evidence)" ;;
        logs/*-telcoin-cert-fail-*.log.gz) echo "16|logs/<node>-telcoin-cert-fail-<UTC>.log.gz|container log of a validator below the certification threshold, saved when the outcome was recorded (listed in manifest.cert_failures[].logs; the local gate requires it)|bench_cert_failures_snapshot (collect, teardown before the local gate)" ;;
        logs/*-unit-stdout*.rotated-[0-9]*.log.gz|logs/*-unit-stderr*.rotated-[0-9]*.log.gz) echo "14|logs/<node>-unit-{stdout,stderr}.rotated-<N>.log.gz|earlier generations of the unit's append files (logrotate: telcoin{,-error}.log.1 gzipped on the node, .<N>.gz as they were)|teardown log gate (bench_pull_node_logs: bench_pull_rotated_logs)" ;;
        logs/*-unit-stdout*.log.gz|logs/*-unit-stderr*.log.gz) echo "14|logs/<node>-unit-{stdout,stderr}.log.gz|the unit's append files /var/log/telcoin/telcoin{,-error}.log: every container run's output since setup (or since the last logrotate)|teardown log gate (bench_pull_node_logs)" ;;
        logs/*.logspan) echo "12|logs/<node>.logspan|LOGSPAN lines: every unit log generation on the node at the pull (bytes, first and last line time)|teardown log gate (bench_pull_node_logs: bench_pull_unit_span)" ;;
        logs/*-telcoin.log.gz|logs/*-telcoin-[0-9]*Z.log.gz) echo "15|logs/<node>-telcoin.log.gz|the current container's log at the pull|teardown log gate (bench_pull_node_logs)" ;;
        logs/*.log.gz) echo "16|logs/<node>-<saved>.log.gz|container logs saved on the node before a restart, kill or pause (pre-kill, ...; runs before the coordinated start also pre-step9)|bench_save_node_log (blast chaos; deploy step 9 in runs before the coordinated start); pulled by the teardown" ;;
        logs/deploy-*.log) echo "17|logs/deploy-*.log|benchmark-deploy.sh output, one file per invocation|benchmark-deploy.sh" ;;
        logs/blast-*.log) echo "18|logs/blast-<action>-*.log|benchmark-blast.sh output, one file per invocation|benchmark-blast.sh" ;;
        logs/create-instances-*.log) echo "17|logs/create-instances-<UTC>.log|create-instances.sh output of deploy step 2 (stockouts and zone fallbacks)|benchmark-deploy.sh step 2" ;;
        logs/keygen-*.log) echo "17|logs/keygen-<UTC>.log|devnet-keygen.sh output of deploy step 5 (KEYGEN_DONE lines)|benchmark-deploy.sh step 5" ;;
        logs/create-*.log) echo "19|logs/create-<vm>.log|load VM create output (current blast index)|benchmark-blast.sh fund/run" ;;
        sampler/*.csv) echo "20|sampler/<node>.csv|node-sampler.sh rows every 30 s (memory, I/O, PSI, disk, block)|benchmark-blast.sh collect" ;;
        sampler/*.epochs.txt) echo "21|sampler/<node>.epochs.txt|epoch-file inventory of the node every minute|benchmark-blast.sh collect" ;;
        persist/*.csv) echo "21|persist/<node>.csv|node-persist-sampler.sh rows every 30 s (data-disk I/O, dirty and writeback pages, refaults, memcg, the node's /proc io; mdbx.dat size and residency every 300 s; BENCH_PERSIST_SAMPLER=1)|benchmark-blast.sh collect" ;;
        persist/*.folios.txt) echo "21|persist/<node>.folios.txt|folio-order census of the node's mdbx.dat every 900 s (tools/folio-census.py; BENCH_PERSIST_SAMPLER=1)|benchmark-blast.sh collect" ;;
        blasters/*) echo "22|blasters/*|blaster results (<vm>.json), txgen and docker logs|benchmark-blast.sh collect (from the run bucket)" ;;
        funder/*) echo "23|funder/*|funder output (prepare.json) and logs|benchmark-blast.sh collect (from the run bucket)" ;;
        meta/*) echo "24|meta/<vm>/*|arguments and node URLs each load VM was created with|benchmark-blast.sh fund/run" ;;
        blast-*/*) echo "25|blast-<index>-<UTC>/*|an earlier blast index set aside, with its manifest copy|benchmark-blast.sh run (archive_prev_blast)" ;;
        funder-*/*) echo "26|funder-<index>-<UTC>/*|an earlier funder output set aside, with its manifest copy|benchmark-blast.sh fund" ;;
        bucket/*) echo "27|bucket/<run bucket>/*|copy of the run bucket gs://tn-devnet-bench-<run>, taken before its delete|benchmark-teardown.sh" ;;
        genesis*/*) echo "28|genesis*/*|genesis workspace: committee, genesis and validator files (keys: never publish)|benchmark-teardown.sh (moves benchmark/genesis)" ;;
        *) echo "99|$1|not known to the harness|?" ;;
    esac
}

# _bench_write_index <dir> — <dir>/INDEX.md: one row per file group (_bench_index_kind) with its
# file count, every unknown file on a row of its own. Written through a temp file.
_bench_write_index() {
    local d="$1" tmp
    tmp="$(mktemp "${d}/.INDEX.md.XXXXXX")" || return 1
    {
        echo "# results/$(basename -- "${d}")/ — index"
        echo ""
        echo "Generated $(bench_now_iso). This directory is a working copy of the run: the canonical copy is"
        echo "the project's archive bucket for bench runs (benchmark/README.md names it; tools/archive-run.sh"
        echo "copies the run there and tools/archive-verify.py checks every file's size and MD5)."
        echo "\`CHECKSUMS.sha256\` holds the SHA-256 of every other file; check them with"
        echo "\`shasum -a 256 -c CHECKSUMS.sha256\` (Linux: \`sha256sum -c\`) from this directory."
        echo ""
        echo "| files | path | what it is | written by |"
        echo "|------:|------|------------|------------|"
        { _bench_results_files "${d}" | grep -v -x -e 'INDEX\.md' -e '\.INDEX\.md\..*' || true; printf '%s\n' INDEX.md CHECKSUMS.sha256; } \
            | while IFS= read -r f; do _bench_index_kind "${f}"; done \
            | LC_ALL=C sort | uniq -c \
            | awk '{ n = $1; sub(/^ *[0-9]+ /, ""); split($0, a, "|"); printf "| %d | `%s` | %s | %s |\n", n, a[2], a[3], a[4] }'
    } > "${tmp}" || { rm -f "${tmp}"; return 1; }
    mv "${tmp}" "${d}/INDEX.md"
}

# _bench_write_checksums <dir> — <dir>/CHECKSUMS.sha256 over _bench_results_files <dir>, written
# through a temp file. Paths are relative to <dir>.
_bench_write_checksums() {
    local d="$1" tmp sha
    sha="$(_bench_sha256_cmd)" || return 1
    tmp="$(mktemp "${d}/.CHECKSUMS.sha256.XXXXXX")" || return 1
    # shellcheck disable=SC2086  # the tool and its flags, one word each
    if ! (cd "${d}" && _bench_results_files . | tr '\n' '\0' | xargs -0 ${sha}) > "${tmp}"; then
        rm -f "${tmp}"; return 1
    fi
    mv "${tmp}" "${d}/CHECKSUMS.sha256"
}

# bench_local_index [<jq argument>... <filter>] — results/<run>/INDEX.md, then CHECKSUMS.sha256.
# With arguments, it first runs bench_manifest_jq with them and records manifest.archive.files and
# .bytes: the count and total size of what CHECKSUMS.sha256 then covers, the manifest at its final
# size included. Non-zero when a write failed. Dry run: says what it would write.
bench_local_index() {
    local d="${BENCH_RESULTS_DIR}" t prev="" i
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "      (dry run) would write ${d}/INDEX.md and ${d}/CHECKSUMS.sha256$([ "$#" -eq 0 ] || echo ', and set manifest.archive')"
        return 0
    fi
    [ -d "${d}" ] || { echo "❌ ${d} does not exist" >&2; return 1; }
    _bench_write_index "${d}" || { echo "❌ could not write ${d}/INDEX.md" >&2; return 1; }
    if [ "$#" -gt 0 ]; then
        bench_manifest_jq "$@" || return 1
        # The totals include manifest.json, which grows as they are written into it: repeat until
        # they describe the file they are written in (two or three passes).
        for i in 1 2 3 4 5; do
            t="$(_bench_results_totals "${d}")" || return 1
            [ "${t}" != "${prev}" ] || break
            bench_manifest_jq --argjson n "${t% *}" --argjson b "${t#* }" '.archive.files = $n | .archive.bytes = $b' || return 1
            prev="${t}"
        done
    fi
    _bench_write_checksums "${d}" || { echo "❌ could not write ${d}/CHECKSUMS.sha256" >&2; return 1; }
    t="$(_bench_results_totals "${d}")"
    echo "    ✓ ${d}/INDEX.md and CHECKSUMS.sha256: ${t% *} file(s), ${t#* } bytes"
}

# bench_local_gate_check [<inst>...] — what results/<run>/ must hold before the teardown deletes
# anything: for each <inst>, non-empty logs/<inst>-telcoin.log.gz, logs/<inst>-unit-stdout.log.gz
# and logs/<inst>-recovery-*.tgz (the names bench_pull_node_logs and bench_pull_recovery_evidence
# write); manifest.json, parsing as JSON; and every path in manifest.cert_failures[].logs[]
# (relative to results/<run>/ unless absolute), non-empty. Reads only. Prints a ✓ line, or one
# ✗ line per missing file; non-zero when anything is missing.
bench_local_gate_check() {
    local d="${BENCH_RESULTS_DIR}" inst f p ok miss=() nf=0 mf="${BENCH_RESULTS_DIR}/manifest.json" cf
    for inst in "$@"; do
        for f in "logs/${inst}-telcoin.log.gz" "logs/${inst}-unit-stdout.log.gz"; do
            if [ -s "${d}/${f}" ]; then nf=$((nf + 1)); else miss+=("${f}"); fi
        done
        ok=0
        for p in "${d}/logs/${inst}-recovery-"*.tgz; do [ -s "${p}" ] && ok=1; done
        if [ "${ok}" -eq 1 ]; then nf=$((nf + 1)); else miss+=("logs/${inst}-recovery-*.tgz"); fi
    done
    if [ ! -s "${mf}" ]; then
        miss+=("manifest.json")
    elif ! jq -e 'type == "object"' "${mf}" >/dev/null 2>&1; then
        miss+=("manifest.json (does not parse as a JSON object)")
    else
        nf=$((nf + 1))
        cf="$(jq -r '[(.cert_failures // [])[]? | objects | (.logs // [])[]? | strings] | unique[]' "${mf}")" || cf=""
        while IFS= read -r p; do
            [ -n "${p}" ] || continue
            case "${p}" in /*) f="${p}" ;; *) f="${d}/${p}" ;; esac
            if [ -s "${f}" ]; then nf=$((nf + 1)); else miss+=("${p} (manifest.cert_failures)"); fi
        done <<< "${cf}"
    fi
    if [ "${#miss[@]}" -gt 0 ]; then
        for f in "${miss[@]}"; do echo "    ✗ missing or empty: ${f}"; done
        return 1
    fi
    echo "    ✓ ${nf} required file(s) present and non-empty: logs of ${#} node(s) (container, unit stdout, recovery evidence), manifest.json$([ -z "${cf}" ] || echo ', manifest.cert_failures logs')"
}

# _bench_cert_log_glob — the file glob tools/cert-rate.py reads the validator logs by
# (BENCH_CERT_LOG_GLOB, default bench-validator-*-unit-stdout*.log.gz): the unit's append files and
# their rotated generations hold the whole run once, where the container logs, saved logs and
# snapshots repeat parts of it (cert-rate.py counts a line once per node, but reads every copy).
_bench_cert_log_glob() { printf '%s\n' "${BENCH_CERT_LOG_GLOB:-bench-validator-*-unit-stdout*.log.gz}"; }

# bench_local_analysis — results/<run>/analysis/cert-rate.md (tools/cert-rate.py --node-glob
# <_bench_cert_log_glob> over the pulled validator logs, windows from the manifest; only once the
# teardown has pulled them) and block-rate.md (tools/block-rate.py over the run dir). Informational:
# a tool that fails leaves a warning and no file, never a non-zero status. BENCH_TEARDOWN_SKIP_ANALYSIS=1
# skips both (the pass reads every pulled log; run it later by hand). Dry run: prints the commands.
bench_local_analysis() {
    local d="${BENCH_RESULTS_DIR}" a="${BENCH_RESULTS_DIR}/analysis" t="${BENCH_DIR}/tools" name tmp err rc g
    g="$(_bench_cert_log_glob)"
    echo "    analysis -> ${a}/ (informational)"
    if [ "${BENCH_TEARDOWN_SKIP_ANALYSIS:-0}" = "1" ]; then
        echo "      - skipped (BENCH_TEARDOWN_SKIP_ANALYSIS=1): python3 ${t}/cert-rate.py --logs ${d}/logs --windows ${d}/manifest.json --node-glob '${g}' and ${t}/block-rate.py --run ${d} can be run by hand"
        return 0
    fi
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "      + python3 ${t}/cert-rate.py --logs ${d}/logs --windows ${d}/manifest.json --node-glob '${g}' > ${a}/cert-rate.md"
        echo "      + python3 ${t}/block-rate.py --run ${d} > ${a}/block-rate.md"
        echo "      (dry run — not executed)"
        return 0
    fi
    command -v python3 >/dev/null 2>&1 || { bench_warn "python3 not on PATH — no analysis"; return 0; }
    mkdir -p "${a}" || { bench_warn "could not create ${a} — no analysis"; return 0; }
    for name in cert-rate block-rate; do
        if [ "${name}" = cert-rate ] && ! compgen -G "${d}/logs/${g}" >/dev/null; then
            echo "      - cert-rate: no validator log in logs/ yet (the teardown pulls them; glob ${g})"
            continue
        fi
        tmp="$(mktemp "${a}/.${name}.md.XXXXXX")" || { bench_warn "${name}: no temp file"; continue; }
        rc=0
        if [ "${name}" = cert-rate ]; then
            err="$(python3 "${t}/cert-rate.py" --logs "${d}/logs" --windows "${d}/manifest.json" --node-glob "${g}" 2>&1 > "${tmp}")" || rc=$?
        else
            err="$(python3 "${t}/block-rate.py" --run "${d}" 2>&1 > "${tmp}")" || rc=$?
        fi
        if [ "${rc}" -eq 0 ] && [ -s "${tmp}" ]; then
            mv "${tmp}" "${a}/${name}.md" && echo "      ✓ ${a}/${name}.md"
        else
            rm -f "${tmp}"
            bench_warn "${name}.py failed — ${a}/${name}.md not written: $(printf '%s\n' "${err:-no output}" | tail -1)"
        fi
    done
    return 0
}

# --- certification outcome -------------------------------------------------------------------
# A validator whose own headers are not certified (a far node in fast rounds) is a result of the
# run, recorded with its logs, not something found later by hand. After every collect, and at the
# teardown after the log and evidence pulls and before the local gate:
#   bench_certification_record    tools/cert-rate.py over the pulled validator logs ->
#                                 analysis/certification.json, manifest.certification, .certification_meta
#                                 and .cert_failures
#   bench_cert_failures_snapshot  per failing validator still up: a labelled container-log snapshot
#                                 (telcoin-cert-fail-<UTC>.log.gz) pulled into logs/, and its logs listed
#                                 in .cert_failures[].logs[], which the local gate then requires
# A validator fails a window in which it proposed at least BENCH_CERT_MIN_PROPOSED headers and
# certified fewer than BENCH_CERT_FAIL_PCT % of them (config.sh, default 90). Both functions only
# warn: they return 0 whatever happens, and the local gate decides. The minimum is fixed here, not
# a knob: fewer proposals than that in a window say too little to judge it.
BENCH_CERT_MIN_PROPOSED=50

# _bench_cert_fail_pct — BENCH_CERT_FAIL_PCT as an integer from 0 to 100; anything else warns and gives 90.
_bench_cert_fail_pct() {
    local p="${BENCH_CERT_FAIL_PCT:-90}"
    case "${p}" in [0-9]|[0-9][0-9]|100) printf '%s\n' "$((10#${p}))"; return 0 ;; esac
    bench_warn "BENCH_CERT_FAIL_PCT='${p}' is not an integer from 0 to 100 — using 90"
    printf '90\n'
}

# _bench_cert_validators_json — the fleet's validators (NODE_ROLES; the observer never proposes) as a JSON array.
_bench_cert_validators_json() {
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        [ "${NODE_ROLES[$i]:-}" != "validator" ] || printf '%s\n' "${INSTANCE_NAMES[$i]}"
    done | jq -R . | jq -s -c .
}

# _bench_cert_rel <base dir> <path> — <path> relative to <base dir> when it lies under it, else as given.
_bench_cert_rel() { case "$2" in "$1"/*) printf '%s\n' "${2#"$1"/}" ;; *) printf '%s\n' "$2" ;; esac; }

# _bench_cert_jq <file> <jq-args...> <filter> — an in-place, atomic jq edit of <file> (as bench_manifest_jq).
_bench_cert_jq() {
    local f="$1" tmp
    shift
    tmp="$(mktemp "${f}.XXXXXX")" || return 1
    if jq "$@" "${f}" > "${tmp}"; then mv -f "${tmp}" "${f}"; else rm -f "${tmp}"; return 1; fi
}

# _bench_cert_insts <manifest> — the string .inst of every manifest.cert_failures[] entry, sorted, one per line.
_bench_cert_insts() { jq -r '[(.cert_failures // [])[]? | objects | .inst | strings] | unique[]' "$1" 2>/dev/null || true; }

# bench_certification_record <logs dir> <manifest> — tools/cert-rate.py --windows <manifest>
# --format json --node-glob <_bench_cert_log_glob> over the validator logs in <logs dir>, kept raw as analysis/certification.json beside
# the manifest, and recorded in the manifest:
#   certification       {<inst>: {<window>: {proposed, certified, rate_pct, own_cert_share_pct,
#                        own_leader_share_pct, not_committed_pct}}}: every validator and window
#                        cert-rate.py reports (windows "arm <name>", "phase <name>", "run"), replaced
#   certification_meta  {fail_below_pct, min_proposed, windows (in cert-rate.py's order), source, recorded_at}
#   cert_failures       one entry per validator that certified fewer than fail_below_pct % of its own
#                       headers in a window where it proposed >= min_proposed: {inst, window (the
#                       worst), rate_pct, proposed, certified, windows (every failing one), logs}
# Re-running merges cert_failures by instance. An instance judged now (proposed >= min_proposed in
# some window) gets the new verdict, keeping the logs[] of its earlier entry still on disk; one that
# passes now loses its entry (a manifest note; its files stay). An entry of an instance not judged now
# is kept, its logs[] cut to the files still on disk; an entry without a string inst is not touched.
# Skipped with a warning while <logs dir> holds no validator log or the manifest has no phases or
# param_arms. Returns 0 whatever happens: a failure leaves a warning and the manifest as it was.
# Dry run: prints what it would run.
bench_certification_record() {
    local logs="${1:-}" mf="${2:-}" base a pct tmp err rc=0 present before after i p f g
    base="$(dirname -- "${mf:-.}")"
    g="$(_bench_cert_log_glob)"
    a="${base}/analysis"
    echo "    certification -> ${a}/certification.json and manifest.certification (informational)"
    if [ -z "${logs}" ] || [ -z "${mf}" ]; then
        bench_warn "bench_certification_record <logs dir> <manifest>: missing argument — not recorded"
        return 0
    fi
    pct="$(_bench_cert_fail_pct)"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "      + python3 ${BENCH_DIR}/tools/cert-rate.py --logs ${logs} --windows ${mf} --format json --node-glob '${g}' > ${a}/certification.json"
        echo "      + manifest.certification, .certification_meta and .cert_failures (below ${pct} % in a window with >= ${BENCH_CERT_MIN_PROPOSED} proposed)"
        echo "      (dry run — not executed)"
        return 0
    fi
    if ! compgen -G "${logs}/${g}" >/dev/null; then
        # Nothing pulled yet (a collect before the teardown): no node log (<node>-*.log.gz, every log the
        # teardown's pull writes) and no pull marker (<node>.pulled*). Not a problem: the teardown records it.
        if ! compgen -G "${logs}/*.log.gz" >/dev/null && ! compgen -G "${logs}/*.pulled" >/dev/null \
            && ! compgen -G "${logs}/*.pulled-*" >/dev/null; then
            echo "    certification: deferred to the teardown (node logs are pulled there)"
            return 0
        fi
        bench_warn "certification: no validator log in ${logs} yet (the teardown pulls them; glob ${g}) — not recorded"
        return 0
    fi
    if ! jq -e '[(.param_arms // [])[]?, (.phases // [])[]? | objects | select((.begin // .start) and .end)] | length > 0' \
        "${mf}" >/dev/null 2>&1; then
        bench_warn "certification: ${mf} has no phases or param_arms yet (or does not parse) — not recorded"
        return 0
    fi
    command -v python3 >/dev/null 2>&1 || { bench_warn "certification: python3 not on PATH — not recorded"; return 0; }
    mkdir -p "${a}" || { bench_warn "certification: could not create ${a} — not recorded"; return 0; }
    tmp="$(mktemp "${a}/.certification.json.XXXXXX")" || { bench_warn "certification: no temp file in ${a} — not recorded"; return 0; }
    err="$(python3 "${BENCH_DIR}/tools/cert-rate.py" --logs "${logs}" --windows "${mf}" --format json --node-glob "${g}" 2>&1 > "${tmp}")" || rc=$?
    if [ "${rc}" -ne 0 ] || ! jq -e '(.windows | type) == "array" and (.nodes | type) == "object"' "${tmp}" >/dev/null 2>&1; then
        rm -f "${tmp}"
        bench_warn "certification: cert-rate.py failed (exit ${rc}) — not recorded: $(printf '%s\n' "${err:-its output is not a cert-rate report}" | tail -1)"
        return 0
    fi
    mv -f "${tmp}" "${a}/certification.json" || { rm -f "${tmp}"; bench_warn "certification: ${a}/certification.json not written — not recorded"; return 0; }
    # The logs earlier entries list that are still on disk: the merge keeps only those. (No case
    # statement in here: bash 3.2 misparses one inside a command substitution.)
    present="$(jq -r '[(.cert_failures // [])[]? | objects | (.logs // [])[]? | strings] | unique[]' "${mf}" \
        | while IFS= read -r p; do
            f="${base}/${p}"; [ "${p#/}" = "${p}" ] || f="${p}"
            [ ! -s "${f}" ] || printf '%s\n' "${p}"
        done | jq -R . | jq -s -c .)" || present='[]'
    before="$(_bench_cert_insts "${mf}")"
    if ! _bench_cert_jq "${mf}" --slurpfile doc "${a}/certification.json" --argjson vals "$(_bench_cert_validators_json)" \
        --argjson present "${present}" --argjson pct "${pct}" --argjson minp "${BENCH_CERT_MIN_PROPOSED}" \
        --arg src "analysis/certification.json" --arg now "$(bench_now_iso)" '
        def judged($m): (.proposed // 0) >= $m and (.rate_pct | type) == "number";
        def among($a; $x): any($a[]; . == $x);
        [($doc[0].windows // [])[]? | objects | select((.name | type) == "string")] as $w
        | (reduce $vals[] as $v ({};
              ([$w[] | select((.nodes[$v]? | type) == "object")
                     | {key: .name, value: (.nodes[$v] | {proposed, certified: .quorum, rate_pct,
                         own_cert_share_pct: .own_cert_pct, own_leader_share_pct: .own_leader_pct, not_committed_pct})}]
               | from_entries) as $row
              | if $row == {} then . else . + {($v): $row} end)) as $cert
        | [$cert | to_entries[] | select([.value[] | judged($minp)] | any) | .key] as $judged
        | [$cert | to_entries[] | .key as $i
           | [.value | to_entries[] | select((.value | judged($minp)) and .value.rate_pct < $pct) | {window: .key} + .value] as $fails
           | select($fails | length > 0)
           | (reduce $fails[] as $f (null; if . == null or $f.rate_pct < .rate_pct then $f else . end)) as $worst
           | {inst: $i, window: $worst.window, rate_pct: $worst.rate_pct, proposed: $worst.proposed,
              certified: $worst.certified, windows: [$fails[].window], logs: []}] as $new
        | [(.cert_failures // [])[]? | objects] as $old
        | .certification = $cert
        | .certification_meta = {fail_below_pct: $pct, min_proposed: $minp, windows: [$w[].name], source: $src, recorded_at: $now}
        | .cert_failures = (
            [$new[] | .inst as $i
             | .logs = ([$old[] | select(.inst == $i) | (.logs // [])[]? | strings | select(among($present; .))] | unique)]
            + [$old[] | select((.inst | type) != "string")]
            + [$old[] | select((.inst | type) == "string") | .inst as $i
               | select((among([$new[].inst]; $i) or among($judged; $i)) | not)
               | .logs = [(.logs // [])[]? | strings | select(among($present; .))]])'; then
        bench_warn "certification: the manifest update failed — ${mf} kept as it was"
        return 0
    fi
    after="$(_bench_cert_insts "${mf}")"
    for i in ${before}; do
        _bench_in_lines "${i}" "${after}" && continue
        echo "      - ${i}: no longer below ${pct} % — its cert_failures entry is dropped (its logs stay in logs/)"
        _bench_cert_jq "${mf}" --arg n "certification: ${i} no longer below ${pct} % at $(bench_now_iso); its cert_failures entry was dropped, its logs stay in logs/" \
            '.notes = ((.notes // []) + [$n])' || true
    done
    # One line per validator: its verdict; then any entry kept from an earlier record.
    jq -r --argjson minp "${BENCH_CERT_MIN_PROPOSED}" --argjson pct "${pct}" '
        (.certification // {}) as $c
        | [(.cert_failures // [])[]? | objects | select((.inst | type) == "string")] as $cf
        | ($c | to_entries[] | .key as $i
           | ([$cf[] | select(.inst == $i)] | first) as $f
           | [.value | to_entries[] | select((.value.proposed // 0) >= $minp and (.value.rate_pct | type) == "number")] as $j
           | if $f then "      ✗ \($i): \($f.rate_pct) % of \($f.proposed) own headers certified in \($f.window) (below \($pct) % in: \($f.windows // [] | join(", ")))"
             elif ($j | length) == 0 then "      - \($i): fewer than \($minp) headers proposed in every window — not judged"
             else ($j | min_by(.value.rate_pct)) as $lo
                  | "      ✓ \($i): at or above \($pct) % in every window it was judged in (lowest \($lo.value.rate_pct) % in \($lo.key))"
             end),
          ($cf[] | select($c[.inst] == null)
           | "      ✗ \(.inst): kept from an earlier record (not in this report): \(.rate_pct) % in \(.window)")' "${mf}" || true
    return 0
}

# _bench_cert_logs_here <logs dir> <inst> — the certification logs of <inst> in <logs dir>, full
# paths, one per line: <inst>-telcoin.log.gz and its stamped copies (-telcoin-<UTC>.log.gz), every
# -telcoin-cert-fail-*.log.gz snapshot, -unit-stdout.log.gz and its stamped copies, and every
# rotated generation -unit-stdout.rotated-<N>.log.gz (stamped: -unit-stdout-<UTC>.rotated-<N>.log.gz).
# Non-empty only.
_bench_cert_logs_here() {
    local f n s='[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z'
    for f in "$1/$2"-*.log.gz; do
        [ -f "${f}" ] && [ -s "${f}" ] || continue
        n="${f##*/}"
        _bench_log_name_ok "${n}" || continue
        # shellcheck disable=SC2254  # ${s} is a glob on purpose
        case "${n#"$2"-}" in
            telcoin.log.gz|telcoin-cert-fail-*.log.gz|unit-stdout.log.gz|telcoin-${s}.log.gz|unit-stdout-${s}.log.gz) printf '%s\n' "${f}" ;;
            unit-stdout.rotated-[0-9]*.log.gz|unit-stdout-${s}.rotated-[0-9]*.log.gz) printf '%s\n' "${f}" ;;
        esac
    done
    return 0
}

# bench_cert_failures_snapshot <logs dir> <manifest> — for every instance in manifest.cert_failures[]:
# when the instance still exists (describe, under an alarm; a describe that fails for any other
# reason than "not found" tries anyway), bench_save_node_log <idx> cert-fail saves its container
# log on the node as telcoin-cert-fail-<UTC>.log.gz, and the node's saved logs <logs dir> lacks are
# pulled in (_bench_pull_saved_logs with _bench_saved_log_cmd), the snapshot as
# <inst>-telcoin-cert-fail-<UTC>.log.gz. Its cert_failures[].logs[] (paths relative to the manifest's
# directory) then gains that snapshot, even when its pull failed (the local gate refuses until it is
# here), and every certification log of the instance on disk (_bench_cert_logs_here). A snapshot of
# this very instance (same id) that a pull marker already vouches for (a teardown re-run: the pull
# brought it in as a saved log) is listed again, not taken again. An instance already gone (a
# teardown after an abort), outside the fleet, or whose save failed gets its logs on disk and a
# manifest note. One line per instance, ending in what the listed logs are. Returns 0 whatever
# happens: the local gate decides. Dry run: says what it would do.
bench_cert_failures_snapshot() {
    local logs="${1:-}" mf="${2:-}" base insts inst idx zone rc err out name snap why f add n jf id had src
    base="$(dirname -- "${mf:-.}")"
    echo "    certification snapshots -> ${logs}/ (informational; the local gate requires what manifest.cert_failures[].logs lists)"
    if [ -z "${logs}" ] || [ -z "${mf}" ]; then
        bench_warn "bench_cert_failures_snapshot <logs dir> <manifest>: missing argument — no snapshot"
        return 0
    fi
    if [ ! -f "${mf}" ]; then echo "      - no manifest at ${mf} — nothing to snapshot"; return 0; fi
    insts="$(_bench_cert_insts "${mf}")"
    if [ -z "${insts}" ]; then echo "      ✓ no validator in manifest.cert_failures — no snapshot"; return 0; fi
    for inst in ${insts}; do
        case "${inst}" in
            *[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
                bench_warn "certification: '${inst}' in manifest.cert_failures is not an instance name — skipped"; continue ;;
        esac
        idx="$(bench_index_of "${inst}")" || idx=""
        if [ "${BENCH_APPLY}" != "1" ]; then
            if [ -n "${idx}" ]; then
                echo "      + ${inst}: if it still exists, bench_save_node_log ${idx} cert-fail and pull its new saved logs into ${logs}/; list its snapshot, container and unit-stdout logs in cert_failures[].logs"
            else
                echo "      + ${inst}: not a node of this fleet — list its logs in ${logs}/ only"
            fi
            continue
        fi
        snap=""; why=""
        if [ -z "${idx}" ]; then
            why="not a node of this fleet (INSTANCE_NAMES)"
        else
            zone="${ZONES[$idx]}"
            rc=0; id=""; had=""
            jf="$(mktemp)" || jf=/dev/null
            err="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "${inst}" --zone="${zone}" \
                --project="${PROJECT_ID}" --format=json </dev/null 2>&1 >"${jf}")" || rc=$?
            [ "${rc}" -ne 0 ] || id="$(jq -r '(.id // "") | tostring' "${jf}" 2>/dev/null)" || id=""
            [ "${jf}" = /dev/null ] || rm -f "${jf}"
            case "${id}" in ''|*[!0-9]*) id="" ;; esac
            # A snapshot of this instance that its pull marker vouches for: taken already, not again.
            if [ -n "${id}" ]; then
                had="$(bench_node_vouched_logs "${logs}" "${inst}" "${id}" | grep -E "^${inst}-telcoin-cert-fail-[0-9]{8}T[0-9]{6}Z\.log\.gz\$" | tail -1)" || had=""
            fi
            if [ "${rc}" -ne 0 ] && printf '%s\n' "${err}" | grep -qi 'not found'; then
                why="instance gone"
            elif [ -n "${had}" ]; then
                snap="${logs}/${had}"
                echo "      - ${inst}: $(_bench_cert_rel "${base}" "${snap}") is this instance's snapshot (instance ${id}; a pull marker vouches for it) — not taken again"
            else
                [ "${rc}" -eq 0 ] || bench_warn "certification: ${inst}: describe failed (exit ${rc}) — trying the snapshot anyway"
                rc=0
                out="$(bench_save_node_log "${idx}" cert-fail </dev/null)" || rc=$?
                [ -z "${out}" ] || printf '%s\n' "${out}"
                name="$(printf '%s\n' "${out}" | sed -n "s#.* saved on the node as ${BENCH_NODE_LOG_DIR}/##p" | tail -1)"
                case "${name}" in telcoin-cert-fail-*.log.gz) ;; *) name="" ;; esac
                if [ "${rc}" -ne 0 ] || [ -z "${name}" ] || ! _bench_log_name_ok "${name}"; then
                    why="its container log could not be saved (see above)"
                else
                    snap="${logs}/${inst}-${name}"
                    if { [ -d "${logs}" ] || mkdir "${logs}"; } \
                        && _bench_pull_saved_logs "${inst}" "${zone}" "$(_bench_saved_log_cmd "${logs}" "${inst}")" "${logs}" </dev/null \
                        && [ -s "${snap}" ]; then :
                    else
                        bench_warn "certification: ${inst}: ${name} is saved on the node but not pulled — the local gate requires $(_bench_cert_rel "${base}" "${snap}") until a re-run pulls it"
                    fi
                fi
            fi
        fi
        add="$({ [ -z "${snap}" ] || printf '%s\n' "${snap}"; _bench_cert_logs_here "${logs}" "${inst}"; } \
            | while IFS= read -r f; do _bench_cert_rel "${base}" "${f}"; done | LC_ALL=C sort -u | jq -R . | jq -s -c .)" || add='[]'
        if ! _bench_cert_jq "${mf}" --arg i "${inst}" --argjson add "${add}" \
            '.cert_failures |= map(if type == "object" and .inst == $i then .logs = ([(.logs // [])[]? | strings] + $add | unique) else . end)'; then
            bench_warn "certification: ${inst}: manifest.cert_failures[].logs not updated"
            continue
        fi
        n="$(printf '%s' "${add}" | jq length)"
        # What the listed logs are (_bench_log_sources_of, by name), for the line below.
        # shellcheck disable=SC2046  # plain file names
        src="$(_bench_log_sources_of "${inst}" $(printf '%s' "${add}" | jq -r '.[]'))" || src="none"
        if [ -n "${why}" ]; then
            echo "      ⚠ ${inst}: ${why} — no snapshot; ${n} log(s) on disk listed in cert_failures[].logs: ${src}"
            _bench_cert_jq "${mf}" --arg n "certification: ${inst}: ${why} at $(bench_now_iso) — no cert-fail snapshot; cert_failures[].logs lists the ${n} log(s) on disk" \
                '.notes = ((.notes // []) + [$n])' || true
        elif [ -s "${snap}" ]; then
            echo "      ✓ ${inst}: snapshot $(_bench_cert_rel "${base}" "${snap}"); ${n} log(s) listed in cert_failures[].logs: ${src}"
        else
            echo "      ✗ ${inst}: snapshot $(_bench_cert_rel "${base}" "${snap}") is on the node only; listed with ${n} log(s), so the local gate refuses until it is here: ${src}"
        fi
    done
    return 0
}

# bench_certification_summary <manifest> — one line: the certification outcome the manifest records.
bench_certification_summary() {
    jq -r '
        if (.certification | type) != "object" then "not recorded (no validator log or phase when it ran)"
        else (.certification_meta.fail_below_pct // 90) as $p
            | [(.cert_failures // [])[]? | objects | select((.inst | type) == "string")] as $f
            | if ($f | length) == 0 then "no validator below \($p) % of its own headers certified (\(.certification | length) validator(s))"
              else "\($f | length) validator(s) below \($p) %: \([$f[] | "\(.inst) \(.rate_pct) % in \(.window)"] | join(", ")); logs in manifest.cert_failures"
              end
        end' "$1" 2>/dev/null || echo "not recorded (manifest unreadable)"
}

# --- leftovers (anything the benchmark could have created) -----------------------------
# bench_bucket_names — buckets that are ours by label benchmark=1 OR by name tn-devnet-bench-*
# (step 12 labels in a second call, so an unlabelled bucket must still be found). The teardown
# deletes what this lists, after copying each into results/<run>/bucket/.
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

# bench_obs_mem_pct — the bench-obs VM's memory used % from the Ops Agent (empty if unavailable).
bench_obs_mem_pct() {
    local id
    id="$(gcloud compute instances describe "${BENCH_OBS_INSTANCE}" --zone="${BENCH_OBS_ZONE}" --project="${PROJECT_ID}" --format='value(id)' 2>/dev/null)" || true
    [ -n "${id}" ] || return 0
    bench_monitoring_max "metric.type=\"agent.googleapis.com/memory/percent_used\" AND metric.labels.state=\"used\" AND resource.labels.instance_id=\"${id}\""
}

# --- v2 nodes: pre-start config, node mode, fleet readiness, admission -------------------------
# Bench 3 runs the nodes on the tn-node-deployment v2 scripts: unit `telcoin`, start script
# /usr/local/libexec/telcoin/tn-start-docker (one `docker run` line, rendered by the v2 lib), node
# metadata /etc/telcoin/.node-meta (root 0600, KEY=VALUE) and the scripts' root-owned checkout at
# TN_NODE_SCRIPTS_DIR. Nothing here edits the start script with sed: launch flags go through the
# lib's own tn_launch_flag_set, which the lib's other writers respect. Every node read is one IAP
# session. A caller that loops over the fleet retries a failed read once, a few seconds later (one
# failed ssh is never evidence about the node), and never polls tightly (IAP throttles that).

# bench_remote_lib_preamble — the shell text every bench remote script that sources the v2 lib
# starts with. SD is the scripts' checkout on the node. tnlib <fn> <args...> runs one v2 lib
# function in a subshell, with DEVNET_RPC_URL set to BENCH_GUARD_PUBLIC_RPC first: lib/common.sh
# reads that name once, readonly, as the quorum guard's public fallback, which must never be the
# real devnet's RPC. lib/common.sh switches on `set -euo pipefail` where it is sourced, so call it
# as `tnlib f ... || rc=$?` or `v="$(tnlib f ...)" || rc=$?`. meta <KEY> prints one value of
# /etc/telcoin/.node-meta the way v2's meta_get reads it (the text after the first '=', a trailing
# CR dropped): rc 1 when the key is absent or the file unreadable, rc 2 (nothing printed) when the
# key is set more than once.
bench_remote_lib_preamble() {
    printf 'SD=%q\n' "${TN_NODE_SCRIPTS_DIR:-/opt/telcoin-node-scripts}"
    # shellcheck disable=SC2016  # $SD and $@ are the remote shell's
    printf 'tnlib(){ ( export DEVNET_RPC_URL=%q; . "$SD/lib/common.sh"; "$@" ); }\n' "${BENCH_GUARD_PUBLIC_RPC:-http://127.0.0.1:9}"
    cat <<'EOS'
meta(){ [ -r /etc/telcoin/.node-meta ] || return 1; awk -v k="$1" 'index($0, k "=") == 1 { n++; v = substr($0, length(k) + 2) } END { sub(/\r$/, "", v); if (n == 1) print v; exit (n == 1 ? 0 : (n ? 2 : 1)) }' /etc/telcoin/.node-meta; }
EOS
}

# bench_prestart_script <inst> — the pre-start remote script of one node: deploy step 7 runs it
# between `devnet-finalize.sh --stage-only` and `--start-all`, as root
# (`bench_prestart_script <inst> | tn_iap_ssh_stdin <inst> <zone>`). The unit is stopped, so what
# it changes is what the coordinated start runs, and nothing restarts. In order:
#   1. the checkout at SD is TN_NODE_SCRIPTS_REF
#   2. `systemctl is-active telcoin` = inactive
#   3. D = DATA_DIR from .node-meta, read once
#   4. S (the start script) mounts D at the container's /home/nonroot
#   5. MP = METRICS_PORT from .node-meta (9101 when absent or empty, as obs_metrics_port; 1-65535)
#   6. tn_launch_flag_set S: --http.addr 0.0.0.0, --ws.addr 0.0.0.0, --metrics 127.0.0.1:<MP> (byte for
#      byte what setup-observability.sh --enable-metrics renders, so step 8 finds it on the node command
#      and restarts nothing) and, when BENCH_NODE_LOG_FILTER is set, --log.stdout.filter <F>,
#      --log.file.filter <F>, --log.file.max-files <BENCH_NODE_LOG_MAX_FILES>; when BENCH_NODE_DB_SYNC_MODE
#      is set (durable|safe-no-sync), --db.sync-mode <it> (unset: no flag, the image's default, durable;
#      safe-no-sync is never for a published run). rc 1 (the flag already reads that value) is accepted,
#      so a re-run converges; any other rc fails, naming it.
#   7a. <D>/parameters.yaml.bak: `cp -p` of the file as the stage left it, unless one is there already
#      (paramsbak=written|kept). A file that already holds `# bench-override` lines and has no .bak fails:
#      it is not the original. tools/params-apply.sh treats marked lines without a .bak as an error.
#   7. this node's BENCH_NODE_PARAM_OVERRIDES into <D>/parameters.yaml with setp, the rewrite the old step 9
#      used (lines marked `# bench-override`; a re-run rewrites the same lines).
#      The file must then hold exactly one marked line per override, so a marked line an earlier run
#      left for an override this run no longer has fails instead of lingering.
#   7b. when BENCH_LOGROTATE_SIZE is set (<digits>K|M|G): /etc/logrotate.d/telcoin becomes
#      bench_logrotate_text (pull-lib.sh: the v2 template without `maxsize`, rotating at that size), its
#      @LOGGLOB@ and @GROUP@ filled from the node's v2 lib (DEFAULT_LOG_DIR/*.log, TN_LOG_GROUP),
#      written by `tnlib tn_write_root_file /etc/logrotate.d/telcoin 0644`; `logrotate -d` must parse it
#      (logrotate=<size>). Unset: the node's logrotate config stays as it is (logrotate=-).
#   8. every flag of 6 read back with tn_launch_flag_get
#   9. S is root:root 755 and passes bash -n
#  10. the unit is still inactive
#  11. when BENCH_NODE_READ_AHEAD_KB is set: the host step read-ahead-kb <it> (bench_host_step_script
#      has the same body): the data disk's queue/read_ahead_kb written, then read back
#  12. when BENCH_NODE_EVICT_MDBX=1: the host step evict-mdbx, <D>/db/mdbx.dat dropped from the page
#      cache (fsync, posix_fadvise DONTNEED; its residency must then read 0); the last thing before
#      the start, the order the arm tool keeps (arms/README.md)
#      Each of 11 and 12 prints its HOST_STEP line (bench_host_step_script); a failed one prints the
#      HOST_STEP failed line, then PRECFG_FAIL.
#  With BENCH_ARM_FILE (the first-start arm; BENCH_NODE_EVICT_MDBX/BENCH_NODE_READ_AHEAD_KB unset beside
#  it): 7c writes every switch of the arm that is away from its default (bench_arm_writes) with setp,
#  marked and counted with the overrides (params=), and 11/12 run the arm's host steps instead of the
#  knobs'. A BENCH_NODE_PARAM_OVERRIDES item that sets a switch is refused beside it.
# Last line (contract C5b):
#   PRECFG_OK <inst> datadir=<D> http=0.0.0.0 ws=0.0.0.0 metrics=127.0.0.1:<port> filter=<F|->
#     maxfiles=<MF|-> params=<n overrides> owner=root:root mode=755 unit=inactive logrotate=<size|->
#     paramsbak=<written|kept>[ dbsync=<BENCH_NODE_DB_SYNC_MODE>, only when that is set]
#     [ ra=<old>-><new>, only when BENCH_NODE_READ_AHEAD_KB is set][ evict=<before>/<after>, only
#     when BENCH_NODE_EVICT_MDBX=1 (resident pages of mdbx.dat)]
# Any failure prints `PRECFG_FAIL <inst> <reason>` and exits 1. Prints the script only (no GCP call);
# non-zero and nothing printed for an instance outside the fleet, a TN_NODE_SCRIPTS_REF that is
# not 40 lower-case hex, a BENCH_LOGROTATE_SIZE that is not <digits>K|M|G, a BENCH_NODE_DB_SYNC_MODE
# other than empty, durable or safe-no-sync, a BENCH_NODE_EVICT_MDBX other than empty, 0 or 1, or a
# BENCH_NODE_READ_AHEAD_KB that is not empty or an integer without leading zeros. Every knob unset
# (BENCH_NODE_EVICT_MDBX empty or 0): the script is byte for byte bench 4's.
# Step 7 sends bench_fsync_probe_script ahead of it in the same session (below).
bench_prestart_script() {
    local inst="${1:-}" idx ref="${TN_NODE_SCRIPTS_REF:-}" kv nov lrs="${BENCH_LOGROTATE_SIZE:-}" lrt=""
    local dbs="${BENCH_NODE_DB_SYNC_MODE:-}" ev="${BENCH_NODE_EVICT_MDBX:-}" ra="${BENCH_NODE_READ_AHEAD_KB:-}" sfx
    local arm="${BENCH_ARM_FILE:-}" aw="" an=0 asrc=""
    idx="$(bench_index_of "${inst}")" || { echo "❌ bench_prestart_script: '${inst}' is not a bench instance" >&2; return 1; }
    case "${ref}" in
        *[!0123456789abcdef]*|'') echo "❌ bench_prestart_script: TN_NODE_SCRIPTS_REF='${ref}' is not 40 lower-case hex" >&2; return 1 ;;
    esac
    [ "${#ref}" -eq 40 ] || { echo "❌ bench_prestart_script: TN_NODE_SCRIPTS_REF='${ref}' is not 40 lower-case hex" >&2; return 1; }
    if [ -n "${lrs}" ]; then
        case "${lrs%[KMG]}" in
            ''|*[!0-9]*) echo "❌ bench_prestart_script: BENCH_LOGROTATE_SIZE='${lrs}' is not <digits>K|M|G (e.g. 20G)" >&2; return 1 ;;
        esac
        [ "${lrs%[KMG]}" != "${lrs}" ] || { echo "❌ bench_prestart_script: BENCH_LOGROTATE_SIZE='${lrs}' is not <digits>K|M|G (e.g. 20G)" >&2; return 1; }
        lrt="$(bench_logrotate_text "${lrs}")" && [ -n "${lrt}" ] \
            || { echo "❌ bench_prestart_script: bench_logrotate_text ${lrs} gave no text" >&2; return 1; }
    fi
    case "${dbs}" in
        ''|durable|safe-no-sync) ;;
        *) echo "❌ bench_prestart_script: BENCH_NODE_DB_SYNC_MODE='${dbs}' is not empty, durable or safe-no-sync" >&2; return 1 ;;
    esac
    case "${ev}" in
        ''|0|1) ;;
        *) echo "❌ bench_prestart_script: BENCH_NODE_EVICT_MDBX='${ev}' is not empty, 0 or 1" >&2; return 1 ;;
    esac
    case "${ra}" in
        *[!0-9]*|0?*) echo "❌ bench_prestart_script: BENCH_NODE_READ_AHEAD_KB='${ra}' is not empty or an integer without leading zeros (KiB)" >&2; return 1 ;;
    esac
    if [ -n "${arm}" ]; then
        # The first-start arm: its switches join this node's setp lines (7c), its host steps are 11/12.
        [ "${ev:-0}" = 0 ] && [ -z "${ra}" ] \
            || { echo "❌ bench_prestart_script: BENCH_ARM_FILE sets the host steps itself; BENCH_NODE_EVICT_MDBX and BENCH_NODE_READ_AHEAD_KB must stay unset beside it" >&2; return 1; }
        bench_arm_state_load "${arm}" || return 1
        kv="$(bench_arm_override_conflicts | head -n 1)"
        [ -z "${kv}" ] || { echo "❌ bench_prestart_script: ${kv}" >&2; return 1; }
        aw="$(bench_arm_writes)"
        an="$(printf '%s' "${aw}" | grep -c . || true)"
        ra="$(bench_arm_host_value read-ahead-kb)"
        [ -z "$(bench_arm_host_value evict-mdbx)" ] || ev=1
        asrc="arm ${BENCH_ARM_NAME}"
    fi
    nov="$(( $(bench_node_overrides "${idx}" | grep -c . || true) + an ))"
    echo 'set -euo pipefail'
    printf 'fail(){ echo "PRECFG_FAIL %s $*"; exit 1; }\n' "${inst}"
    bench_remote_lib_preamble
    printf "REF='%s'; NOV=%s\n" "${ref}" "${nov}"
    if [ -n "${lrs}" ]; then
        printf "LRS='%s'; LRT=%q\n" "${lrs}" "${lrt}"
    else
        echo "LRS=''   # BENCH_LOGROTATE_SIZE is empty: the node's logrotate config stays as it is"
    fi
    if [ -n "${BENCH_NODE_LOG_FILTER:-}" ]; then
        printf "F='%s'; MF='%s'\n" "${BENCH_NODE_LOG_FILTER}" "${BENCH_NODE_LOG_MAX_FILES}"
    else
        echo "F=''; MF=''   # BENCH_NODE_LOG_FILTER is empty: the node's log flags stay as they are"
    fi
    cat <<'EOS'
# 1. the v2 scripts' checkout is the pinned commit
h="$(git -C "$SD" rev-parse HEAD 2>/dev/null || true)"
[ "$h" = "$REF" ] || fail "$SD is at '${h:-?}', want $REF"
# 2. the unit is stopped (devnet-finalize.sh --stage-only): nothing below starts or restarts it
u="$(systemctl is-active telcoin 2>/dev/null || true)"
[ "$u" = inactive ] || fail "unit telcoin is '${u:-?}', want inactive"
# 3. the datadir, read once
r=0; D="$(meta DATA_DIR)" || r=$?
[ "$r" = 0 ] || fail "DATA_DIR unreadable in /etc/telcoin/.node-meta (meta rc $r)"
case "$D" in /?*) ;; *) fail "DATA_DIR '$D' in /etc/telcoin/.node-meta is not an absolute path" ;; esac
# 4. the start script, which must mount the datadir at the container's home
S=/usr/local/libexec/telcoin/tn-start-docker
[ -f "$S" ] || fail "no $S"
grep -qF " -v $D:/home/nonroot " "$S" || fail "$S does not mount $D at /home/nonroot"
# 5. the metrics port as obs_metrics_port reads it: METRICS_PORT, 9101 when absent or empty
r=0; MP="$(meta METRICS_PORT)" || r=$?
case "$r" in 0|1) ;; *) fail "METRICS_PORT is set more than once in /etc/telcoin/.node-meta" ;; esac
[ -n "$MP" ] || MP=9101
case "$MP" in *[!0-9]*|??????*) fail "METRICS_PORT '$MP' is not a port number" ;; esac
MP=$((10#$MP))
[ "$MP" -ge 1 ] && [ "$MP" -le 65535 ] || fail "METRICS_PORT $MP is not a port number (1-65535)"
# 6. launch flags: rc 0 = set, rc 1 = already that value; anything else fails
setf(){ local rc=0; tnlib tn_launch_flag_set "$S" "$1" "$2" || rc=$?; case "$rc" in 0|1) ;; *) fail "tn_launch_flag_set $1 $2: rc $rc" ;; esac; }
getf(){ local v rc=0; v="$(tnlib tn_launch_flag_get "$S" "$1")" || rc=$?; [ "$rc" = 0 ] || fail "tn_launch_flag_get $1: rc $rc"; [ "$v" = "$2" ] || fail "$1 reads '$v' in $S, want '$2'"; }
setf --http.addr 0.0.0.0
setf --ws.addr 0.0.0.0
setf --metrics "127.0.0.1:$MP"
EOS
    if [ -n "${BENCH_NODE_LOG_FILTER:-}" ]; then
        cat <<'EOS'
setf --log.stdout.filter "$F"
setf --log.file.filter "$F"
setf --log.file.max-files "$MF"
EOS
    fi
    [ -z "${dbs}" ] || printf 'setf --db.sync-mode %s\n' "${dbs}"
    cat <<'EOS'
# 7. this node's consensus parameter overrides (setp), marked `# bench-override`
P="$D/parameters.yaml"
[ -f "$P" ] || fail "no $P"
# 7a. the stage's file is kept as $P.bak (params-apply.sh's convention); an existing .bak is the original
if [ -f "$P.bak" ]; then BAK=kept
elif grep -q '  # bench-override$' "$P"; then fail "$P has '# bench-override' lines and no $P.bak (not the stage's original)"
else cp -p "$P" "$P.bak" || fail "cannot copy $P to $P.bak"; BAK=written
fi
# setp <key> <value> — rewrite the top-level `key:` line in place (append it when absent), marked.
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
        rm -f "$t"; fail "$1 is a block (secs/nanos) in $P; write it as <int>ms there"
    fi
    cat "$t" > "$P"; rm -f "$t"
    [ "$(grep -c "^$1: $2  # bench-override\$" "$P" || true)" = 1 ] || fail "$1 not rewritten in $P"
}
EOS
    bench_node_overrides "${idx}" | while IFS= read -r kv; do printf 'setp %s %s\n' "${kv%%=*}" "${kv#*=}"; done
    if [ -n "${aw}" ]; then
        echo "# 7c. the switches of arm ${BENCH_ARM_NAME} (BENCH_ARM_FILE, sha256 ${BENCH_ARM_SHA256}) away from their default, marked as the overrides are"
        printf '%s\n' "${aw}" | while IFS= read -r kv; do printf 'setp %s %s\n' "${kv%%=*}" "${kv#*=}"; done
    fi
    cat <<'EOS'
m="$(grep -c '  # bench-override$' "$P" || true)"
[ "$m" = "$NOV" ] || fail "$P has $m '# bench-override' line(s), this node has $NOV override(s) (a marked line from an earlier run?)"
EOS
    if [ -n "${lrs}" ]; then
        cat <<'EOS'
# 7b. the bench logrotate config: the v2 template without maxsize, rotating at $LRS, from the node's v2 lib
r=0; LD="$(tnlib eval 'printf "%s" "${DEFAULT_LOG_DIR:-}"')" || r=$?
[ "$r" = 0 ] && [ -n "$LD" ] || fail "DEFAULT_LOG_DIR unreadable from $SD/lib/common.sh (rc $r)"
r=0; LG="$(tnlib eval 'printf "%s" "${TN_LOG_GROUP:-}"')" || r=$?
[ "$r" = 0 ] && [ -n "$LG" ] || fail "TN_LOG_GROUP unreadable from $SD/lib/common.sh (rc $r)"
g="$LD/*.log"; t="${LRT//@LOGGLOB@/"$g"}"; t="${t//@GROUP@/"$LG"}"
case "$t" in *@LOGGLOB@*|*@GROUP@*) fail "the logrotate text still holds a placeholder" ;; esac
r=0; tnlib tn_write_root_file /etc/logrotate.d/telcoin 0644 <<< "$t" || r=$?
[ "$r" = 0 ] || fail "tn_write_root_file /etc/logrotate.d/telcoin 0644: rc $r"
logrotate -d /etc/logrotate.d/telcoin >/dev/null 2>&1 || fail "logrotate -d does not parse /etc/logrotate.d/telcoin"
EOS
    fi
    cat <<'EOS'
# 8. read every flag back
getf --http.addr 0.0.0.0
getf --ws.addr 0.0.0.0
getf --metrics "127.0.0.1:$MP"
EOS
    if [ -n "${BENCH_NODE_LOG_FILTER:-}" ]; then
        cat <<'EOS'
getf --log.stdout.filter "$F"
getf --log.file.filter "$F"
getf --log.file.max-files "$MF"
EOS
    fi
    [ -z "${dbs}" ] || printf 'getf --db.sync-mode %s\n' "${dbs}"
    cat <<'EOS'
# 9. the start script is still root:root 755 and parses
o="$(stat -c '%U:%G %a' "$S" 2>/dev/null || true)"
[ "$o" = "root:root 755" ] || fail "$S is '${o:-?}', want root:root 755"
bash -n "$S" || fail "$S does not parse (bash -n)"
# 10. still stopped
u="$(systemctl is-active telcoin 2>/dev/null || true)"
[ "$u" = inactive ] || fail "unit telcoin is '${u:-?}' after the pre-start config, want inactive"
EOS
    sfx="${dbs:+ dbsync=${dbs}}"
    if [ -n "${ra}" ]; then
        echo "# 11. host step read-ahead-kb ${ra} (${asrc:-BENCH_NODE_READ_AHEAD_KB}): the data disk's queue/read_ahead_kb, written and read back"
        _bench_host_step_wrappers prestart "${inst}" read-ahead-kb "${ra}"
        _bench_host_step_body read-ahead-kb "${ra}"
        echo 'RA_OLD=$HS_A; RA_NEW=$HS_B'
        # shellcheck disable=SC2016  # the node's shell expands them, in the PRECFG_OK line
        sfx="${sfx}"' ra=${RA_OLD}->${RA_NEW}'
    fi
    if [ "${ev}" = 1 ]; then
        echo "# 12. host step evict-mdbx (${asrc:-BENCH_NODE_EVICT_MDBX=1}): mdbx.dat out of the page cache, the last thing before the start"
        _bench_host_step_wrappers prestart "${inst}" evict-mdbx -
        _bench_host_step_body evict-mdbx -
        echo 'EV_BEFORE=$HS_A; EV_AFTER=$HS_B'
        # shellcheck disable=SC2016  # the node's shell expands them, in the PRECFG_OK line
        sfx="${sfx}"' evict=${EV_BEFORE}/${EV_AFTER}'
    fi
    printf 'echo "PRECFG_OK %s datadir=$D http=0.0.0.0 ws=0.0.0.0 metrics=127.0.0.1:$MP filter=${F:--} maxfiles=${MF:--} params=$NOV owner=root:root mode=755 unit=$u logrotate=${LRS:--} paramsbak=${BAK:--}%s"\n' "${inst}" "${sfx}"
}

# bench_fsync_probe_script <inst> — the disk probe deploy step 7 sends first in each node's pre-start
# session, ahead of bench_prestart_script (whose text it leaves alone). It runs in a subshell and only
# prints, so nothing in it can stop the session. The directory is the node's datadir as the pre-start
# script reads it: D = DATA_DIR from /etc/telcoin/.node-meta through the lib preamble's meta (the host
# path the start script mounts at the container's /home/nonroot, where the node's databases live).
# python3 (stdlib only; the bench nodes run the Ubuntu cloud image, which ships it) creates a temp file
# there, times 200 x (write 4 KB + os.fsync), removes the file, and prints one line:
#   FSYNC_PROBE <inst> p50_us=<n> p95_us=<n>     nearest-rank percentiles of the 200, integer µs
#   FSYNC_PROBE <inst> probe_failed <reason>    no python3, DATA_DIR unusable, an I/O error, 60 s passed
# In step 7 the unit is stopped (stage-only), so the node's own I/O is not in the numbers; the pre-start
# script that follows refuses a node whose unit is not. Prints the script only (no GCP call); non-zero
# and nothing printed for an instance outside the fleet.
bench_fsync_probe_script() {
    local inst="${1:-}"
    bench_index_of "${inst}" >/dev/null || { echo "❌ bench_fsync_probe_script: '${inst}' is not a bench instance" >&2; return 1; }
    echo '# fsync probe on the datadir (bench_fsync_probe_script): a subshell that only prints; the pre-start script follows'
    echo '('
    bench_remote_lib_preamble
    printf 'I=%q\n' "${inst}"
    cat <<'EOS'
pf(){ echo "FSYNC_PROBE $I probe_failed $*"; exit 0; }
r=0; D="$(meta DATA_DIR)" || r=$?
[ "$r" = 0 ] || pf "DATA_DIR unreadable in /etc/telcoin/.node-meta (meta rc $r)"
case "$D" in /?*) ;; *) pf "DATA_DIR '$D' in /etc/telcoin/.node-meta is not an absolute path" ;; esac
[ -d "$D" ] || pf "DATA_DIR $D is not a directory"
command -v python3 >/dev/null 2>&1 || pf "no python3 on the node"
r=0; python3 - "$D" "$I" <<'PY' || r=$?
import os, signal, sys, tempfile, time
d, inst = sys.argv[1], sys.argv[2]
def expired(signum, frame):
    raise RuntimeError("not done after 60 s")
signal.signal(signal.SIGALRM, expired)
signal.alarm(60)
path = None
try:
    fd, path = tempfile.mkstemp(prefix=".bench-fsync-probe.", dir=d)
    buf, lap = os.urandom(4096), []
    try:
        for _ in range(200):
            t0 = time.perf_counter()
            os.write(fd, buf)
            os.fsync(fd)
            lap.append(time.perf_counter() - t0)
    finally:
        os.close(fd)
    lap.sort()
    def us(q):
        return int(round(lap[-(-len(lap) * q // 100) - 1] * 1e6))
    print("FSYNC_PROBE %s p50_us=%d p95_us=%d" % (inst, us(50), us(95)))
except Exception as e:
    print("FSYNC_PROBE %s probe_failed %s: %s" % (inst, type(e).__name__, " ".join(str(e).split())))
finally:
    signal.alarm(0)
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
PY
[ "$r" = 0 ] || pf "python3 exited $r"
EOS
    echo ') || true'
}

# bench_fsync_probe_record <inst> — node_startup[<inst>].fsync_probe from that node's pre-start session
# output on stdin (CRs dropped): the last line that starts `FSYNC_PROBE <inst> ` gives
#   {"p50_us":<n>,"p95_us":<n>}                 from `p50_us=<n> p95_us=<n>` (integers)
#   {"probe_failed":true,"reason":"<text>"}    from `probe_failed <reason>`, a malformed line, or no line
# One JSON object, rc 0 (a probe that failed never stops step 7).
bench_fsync_probe_record() {
    local inst="${1:-}" line rest v
    line="$(awk -v p="FSYNC_PROBE ${inst} " 'index($0, p) == 1 { l = $0 } END { print l }')" || line=""
    rest="${line#"FSYNC_PROBE ${inst} "}"
    v="$(printf '%s\n' "${rest}" | sed -nE 's/^p50_us=(0|[1-9][0-9]{0,11}) p95_us=(0|[1-9][0-9]{0,11})$/\1 \2/p')" || v=""
    if [ -n "${line}" ] && [ -n "${v}" ]; then
        jq -n -c --argjson a "${v% *}" --argjson b "${v#* }" '{p50_us: $a, p95_us: $b}'
        return 0
    fi
    if [ -z "${line}" ]; then
        rest="no FSYNC_PROBE line in the session output"
    else
        case "${rest}" in
            "probe_failed "*) rest="${rest#probe_failed }" ;;
            probe_failed) rest="(no reason given)" ;;
            *) rest="unparsed: ${rest}" ;;
        esac
    fi
    jq -n -c --arg r "${rest}" '{probe_failed: true, reason: $r}'
}

# bench_fsync_probe_summary <manifest> <inst…> — one line on the fleet's fsync probes, read from
# node_startup[<inst>].fsync_probe in <manifest> (an instance without a record is left out):
#   FSYNC_PROBE_SUMMARY median_us=<n|-> slow=[<inst> …] probe_failed=[<inst> …]
# median_us is the median p50 of the nodes that measured (failed probes are not in it; an even count
# takes the mean of the middle two, rounded down); slow lists the nodes whose p50 is more than 20 % over
# it (5 p50 > 6 median). The line starts with "⚠ " when slow or probe_failed lists anyone. rc 0 always:
# a slow disk is a finding for the analysis, never a reason to stop.
bench_fsync_probe_summary() {
    local m="${1:-}" out
    [ "$#" -eq 0 ] || shift
    out="$(jq -r --arg ii "$*" '
        [($ii | split(" ") | map(select(. != "")))[] as $i
         | {i: $i, f: (.node_startup[$i].fsync_probe // null)} | select(.f != null)] as $r
        | [$r[] | select((.f | type) == "object" and (.f.p50_us | type) == "number")] as $ok
        | [$r[] | select(((.f | type) == "object" and (.f.p50_us | type) == "number") | not) | .i] as $bad
        | ($ok | map(.f.p50_us) | sort) as $s | ($s | length) as $n
        | (if $n == 0 then null elif $n % 2 == 1 then $s[($n - 1) / 2]
           else (($s[$n / 2 - 1] + $s[$n / 2]) / 2 | floor) end) as $med
        | [$ok[] | select($med != null and .f.p50_us * 5 > $med * 6) | .i] as $slow
        | (if ($slow | length) + ($bad | length) > 0 then "⚠ " else "" end)
          + "FSYNC_PROBE_SUMMARY median_us=\($med // "-") slow=[\($slow | join(" "))] probe_failed=[\($bad | join(" "))]"
    ' "${m}" 2>/dev/null)" || out=""
    [ -n "${out}" ] || out="⚠ FSYNC_PROBE_SUMMARY median_us=- slow=[] probe_failed=[] (cannot read ${m})"
    printf '%s\n' "${out}"
    return 0
}

# --- host probe and host steps (bench 6) ------------------------------------------------------
# Pure script builders and local parsers; the callers (deploy step 7, tools/params-apply.sh, the
# one-VM probe) send the scripts and record the lines. Manifest names: arms/MANIFEST-FIELDS.md.

# _bench_host_py — the python3 program (stdlib only; the Ubuntu 24.04 image ships python3, fincore,
# findmnt and lsblk) behind the host probe and the host steps, run as `python3 - <mode> ...`:
#   probe <inst> <datadir> <start script>  one line `HOST_PROBE <inst> <json>` (the frozen keys of
#                                          node_startup[inst].host, in table order; a field it cannot
#                                          read is null), or `HOST_PROBE <inst> probe_failed <reason>`
#   evict-mdbx <datadir>                   one line `ok <before> <after>` or `failed <reason>`
#   read-ahead-kb <datadir> <KiB>          one line `ok <before> <after>` or `failed <reason>`
# It never touches a page of mdbx.dat: residency is fincore's count, or (fincore missing or
# failing) mincore over a read-only map that nothing reads. mdbx_dat_folios is null: the folio
# census (tools/folio-census.py) resolves folio orders through the node's own page table, and
# before the start no process maps the file. Every external call has a 10-s timeout and the whole
# program a 30-s alarm.
_bench_host_py() {
    cat <<'EOS'
import ctypes, json, mmap, os, re, shlex, signal, subprocess, sys

PS = mmap.PAGESIZE
LOWBIT = bytes(b & 1 for b in range(256))
THP = "/sys/kernel/mm/transparent_hugepage/"
VM = ("dirty_ratio", "dirty_background_ratio", "dirty_bytes", "dirty_background_bytes",
      "dirty_expire_centisecs", "dirty_writeback_centisecs", "swappiness", "vfs_cache_pressure")
_libc = []


class StepFailed(Exception):
    pass


def why(e):
    return "%s: %s" % (type(e).__name__, " ".join(str(e).split()))


def run(argv):
    """stdout of argv, or None when it is missing, fails or takes over 10 s."""
    try:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=10, universal_newlines=True, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def text(path):
    try:
        with open(path, errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def number(path):
    t = text(path)
    return int(t) if t is not None and re.match(r"^[0-9]+$", t) else None


def active(path):
    """The active entry of a sysfs choice file ("always [madvise] never" -> "madvise"), else its text."""
    t = text(path)
    m = re.search(r"\[([^]]*)\]", t or "")
    return m.group(1) if m else t


def key_value(path, key, sep):
    """The value of the first `<key><sep>` line of <path>, shell quotes removed."""
    for line in (text(path) or "").splitlines():
        k, s, v = line.partition(sep)
        if s and k.strip() == key:
            return " ".join(shlex.split(v))
    return None


def mem_total_kb():
    for line in (text("/proc/meminfo") or "").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1])
    return None


def libc():
    if not _libc:
        c = ctypes.CDLL(None, use_errno=True)
        c.mmap.restype = ctypes.c_void_p
        c.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long)
        c.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
        c.mincore.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
        _libc.append(c)
    return _libc[0]


class Mapped(object):
    """<path> mapped shared and read-only. Mapping faults no page in, and nothing reads the map."""

    def __init__(self, path):
        self.addr = None
        self.fd = os.open(path, os.O_RDONLY)
        self.size = os.fstat(self.fd).st_size
        self.pages = (self.size + PS - 1) // PS
        if self.size:
            c = libc()
            a = c.mmap(None, self.size, mmap.PROT_READ, mmap.MAP_SHARED, self.fd, 0)
            if not a or a == ctypes.c_void_p(-1).value:
                e = ctypes.get_errno()
                self.close()
                raise OSError(e, "mmap: " + os.strerror(e))
            self.addr = a

    def resident(self):
        """mincore of the map: one byte per page, 1 when the page cache holds the page."""
        vec = (ctypes.c_ubyte * max(self.pages, 1))()
        if self.pages and libc().mincore(self.addr, self.size, vec) != 0:
            e = ctypes.get_errno()
            raise OSError(e, "mincore: " + os.strerror(e))
        return bytes(vec)[:self.pages].translate(LOWBIT)

    def close(self):
        if self.addr:
            libc().munmap(self.addr, self.size)
            self.addr = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def resident_pages(path):
    """Resident pages of <path>: fincore's count when fincore runs, else mincore over an untouched map."""
    out = (run(["fincore", "--noheadings", "--raw", "--output", "PAGES", path]) or "").strip()
    if re.match(r"^[0-9]+$", out):
        return int(out)
    m = Mapped(path)
    try:
        return m.resident().count(1)
    finally:
        m.close()


def mount_of(d):
    """(source, fstype, options) of the mount holding <d>, from findmnt."""
    try:
        fs = json.loads(run(["findmnt", "--json", "--output", "SOURCE,FSTYPE,OPTIONS", "--target", d]))
        fs = fs["filesystems"][0]
        return fs.get("source"), fs.get("fstype"), fs.get("options")
    except (TypeError, ValueError, KeyError, IndexError):
        return None, None, None


def data_disk(d, source):
    """The block device whose queue serves <d>: lsblk's PKNAME of the mount source (the disk under a
    partition), else its KNAME (a whole disk, a device-mapper volume), else the device number of <d>
    through /sys/dev/block (a partition's parent); the first with a /sys/block/<name>/queue wins."""
    names = []
    if source:
        try:
            dev = json.loads(run(["lsblk", "--json", "--nodeps", "--output", "PKNAME,KNAME",
                                  re.sub(r"\[.*$", "", source)]))["blockdevices"][0]
            names += [dev.get("pkname"), dev.get("kname")]
        except (TypeError, ValueError, KeyError, IndexError):
            pass
    try:
        st = os.stat(d)
        link = "/sys/dev/block/%d:%d" % (os.major(st.st_dev), os.minor(st.st_dev))
        if os.path.exists(link):
            real = os.path.realpath(link)
            part = os.path.exists(os.path.join(real, "partition"))
            names.append(os.path.basename(os.path.dirname(real) if part else real))
    except OSError:
        pass
    names = [n for n in names if n]
    for n in names:
        if os.path.isdir("/sys/block/%s/queue" % n):
            return n
    return names[0] if names else None


def docker_bytes(v):
    """docker's --memory value in bytes (k/m/g/t/p are powers of 1024)."""
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?) ?([kmgtp]?)i?b?$", v, re.I)
    return int(float(m.group(1)) * 1024 ** "_kmgtp".index(m.group(2).lower() or "_")) if m else None


def container_memory(start):
    """The --memory (-m) of the docker run line in the node's start script: what HostConfig.Memory holds once
    the unit starts it; 0 when the line has none; None without a readable start script or docker run line."""
    lines = [l for l in (text(start) or "").splitlines()
             if re.search(r"(^|[\s/])docker run\s", l) and not l.lstrip().startswith("#")]
    if not lines:
        return None
    toks = shlex.split(lines[-1])
    for k, tok in enumerate(toks):
        if tok in ("--memory", "-m") and k + 1 < len(toks):
            return docker_bytes(toks[k + 1])
        if tok.startswith("--memory="):
            return docker_bytes(tok[len("--memory="):])
    return 0


def field(f, *a):
    try:
        return f(*a)
    except Exception:
        return None


def probe(d, start):
    h = {"kernel": text("/proc/sys/kernel/osrelease"), "cmdline": text("/proc/cmdline"),
         "os_release": field(key_value, "/etc/os-release", "PRETTY_NAME", "="),
         "image_serial": field(key_value, "/etc/cloud/build.info", "serial", ":"),
         "mem_total_kb": field(mem_total_kb), "nproc": field(lambda: len(os.sched_getaffinity(0))),
         "datadir": d}
    src, fstype, opts = field(mount_of, d) or (None, None, None)
    disk = field(data_disk, d, src)
    h.update([("datadir_mount_source", src), ("datadir_fstype", fstype), ("datadir_mount_options", opts),
              ("disk", disk)])
    q = "/sys/block/%s/queue/" % disk
    for k in ("read_ahead_kb", "max_sectors_kb", "max_hw_sectors_kb", "scheduler", "nr_requests"):
        h[k] = None if disk is None else active(q + k) if k == "scheduler" else number(q + k)
    for k in ("enabled", "defrag", "shmem_enabled"):
        h["thp_" + k] = active(THP + k)
    h["khugepaged_defrag"] = active(THP + "khugepaged/defrag")
    for k in VM:
        h["vm_" + k] = number("/proc/sys/vm/" + k)
    h["container_memory_limit_bytes"] = field(container_memory, start)
    path = os.path.join(d, "db", "mdbx.dat")
    exists = os.path.isfile(path)
    h["mdbx_dat_size_bytes"] = field(lambda: os.stat(path).st_size) if exists else None
    h["mdbx_dat_resident_pages"] = field(resident_pages, path) if exists else None
    h["mdbx_dat_folios"] = None   # no process maps mdbx.dat before the start (see above)
    h["lru_gen_enabled"] = text("/sys/kernel/mm/lru_gen/enabled")
    return h


def evict(d):
    """Resident pages of <d>/db/mdbx.dat before and after fsync + posix_fadvise(DONTNEED); (0, 0) when the
    file is not there (a node that never started has nothing of it cached)."""
    path = os.path.join(d, "db", "mdbx.dat")
    if not os.path.exists(path):
        return 0, 0
    before = resident_pages(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)
    after = resident_pages(path)
    if after:
        raise StepFailed("%s keeps %d resident page(s) after fsync and posix_fadvise DONTNEED (%d before)"
                         % (path, after, before))
    return before, after


def read_ahead(d, kb):
    """queue/read_ahead_kb of the disk under <d> before and after writing <kb> to it."""
    disk = data_disk(d, mount_of(d)[0])
    if not disk:
        raise StepFailed("no block device found under %s" % d)
    q = "/sys/block/%s/queue/read_ahead_kb" % disk
    before = number(q)
    if before is None:
        raise StepFailed("cannot read %s" % q)
    try:
        with open(q, "w") as f:
            f.write("%d\n" % kb)
    except OSError as e:
        raise StepFailed("cannot write %d to %s: %s" % (kb, q, why(e)))
    after = number(q)
    if after != kb:
        raise StepFailed("%s reads %s after writing %d (it was %d; the kernel keeps whole pages)" % (q, after, kb, before))
    return before, after


def expired(signum, frame):
    raise RuntimeError("not done after 30 s")


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(30)
    try:
        if mode == "probe":
            try:
                line = "%s %s" % (argv[2], json.dumps(probe(argv[3], argv[4]), separators=(",", ":")))
            except Exception as e:
                line = "%s probe_failed %s" % (argv[2], why(e))
            print("HOST_PROBE " + line)
            return
        try:
            if mode == "evict-mdbx":
                print("ok %d %d" % evict(argv[2]))
            elif mode == "read-ahead-kb":
                print("ok %d %d" % read_ahead(argv[2], int(argv[3])))
            else:
                print("failed unknown mode '%s'" % mode)
        except StepFailed as e:
            print("failed %s" % e)
        except Exception as e:
            print("failed %s" % why(e))
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main(sys.argv)
EOS
}

# _bench_host_name_ok <inst> — rc 0 when <inst> is a GCE instance name the host scripts may embed
# (a lower-case letter, then up to 62 of [a-z0-9-]); the fleet's names and the one-VM probe's pass.
_bench_host_name_ok() {
    case "${1:-}" in ''|[!a-z]*|*[!a-z0-9-]*) return 1 ;; esac
    [ "${#1}" -le 63 ]
}

# _bench_host_step_wrappers <prestart|standalone> <inst> <step> <value|-> — the hsok/hsfail pair a
# host step body reports through. Both print the step's HOST_STEP line (hsok its result fields,
# hsfail `failed <reason>`). prestart: hsok returns and hsfail ends the pre-start script through its
# fail (PRECFG_FAIL); standalone: both end the step's subshell, hsok with 0 and hsfail with 1.
_bench_host_step_wrappers() {
    local mode="$1" inst="$2" step="$3" v="$4"
    if [ "${mode}" = prestart ]; then
        printf 'hsok(){ echo "HOST_STEP %s %s %s $*"; }\n' "${inst}" "${step}" "${v}"
        printf 'hsfail(){ echo "HOST_STEP %s %s %s failed $*"; fail "host step %s: $*"; }\n' "${inst}" "${step}" "${v}" "${step}"
    else
        printf 'hsok(){ echo "HOST_STEP %s %s %s $*"; exit 0; }\n' "${inst}" "${step}" "${v}"
        printf 'hsfail(){ echo "HOST_STEP %s %s %s failed $*"; exit 1; }\n' "${inst}" "${step}" "${v}"
    fi
}

# _bench_host_step_body <evict-mdbx|read-ahead-kb> <value|-> — the remote shell of one host step, the
# same text in bench_prestart_script (11, 12) and in bench_host_step_script: reads D (the datadir),
# runs _bench_host_py's mode, leaves the before/after numbers in HS_A/HS_B and reports them through
# hsok "<key_before>=<n> <key_after>=<n>"; any failure goes to hsfail "<reason>".
# evict-mdbx: at a fresh start (deploy step 7) mdbx.dat holds only genesis, and libmdbx drops every
# page past the used size from the cache when it opens the file, so there the eviction changes
# little. It matters when an arm restarts a node whose cache is warm (tools/params-apply.sh).
_bench_host_step_body() {
    local step="$1" v="$2" a b args
    case "${step}" in
        evict-mdbx) a=resident_pages_before; b=resident_pages_after; args='"$D"' ;;
        read-ahead-kb) a=read_ahead_kb_before; b=read_ahead_kb_after; args="\"\$D\" ${v}" ;;
        *) echo "❌ _bench_host_step_body: unknown step '${step}'" >&2; return 1 ;;
    esac
    echo 'command -v python3 >/dev/null 2>&1 || hsfail "no python3 on the node"'
    printf "r=0; o=\"\$(python3 - %s %s <<'PY'\n" "${step}" "${args}"
    _bench_host_py
    printf 'PY\n)" || r=$?\n'
    cat <<'EOS'
HS_A=''; HS_B=''
case "$o" in
    "ok "*) HS_A="${o#ok }"; HS_B="${HS_A#* }"; HS_A="${HS_A%% *}"; [ "ok $HS_A $HS_B" = "$o" ] || HS_B='' ;;
    "failed "*) hsfail "${o#failed }" ;;
    *) hsfail "python3 exited $r${o:+: $o}" ;;
esac
case "$HS_A:$HS_B" in :*|*:|*[!0-9:]*) hsfail "python3 printed '$o'" ;; esac
EOS
    printf 'hsok "%s=$HS_A %s=$HS_B"\n' "${a}" "${b}"
}

# bench_host_step_script <inst> evict-mdbx [<datadir>]
# bench_host_step_script <inst> read-ahead-kb <KiB> [<datadir>]
# One host step as a remote script, for a node whose unit is stopped (deploy step 7 runs the same
# body inside bench_prestart_script; tools/params-apply.sh runs it between a node's stop and start).
# Run as root (`bash -s`, or embedded in a longer script). <datadir> defaults to DATA_DIR from
# /etc/telcoin/.node-meta. The text is one subshell that sets HOST_STEP_RC (0 the step held, 1 it
# failed) and never stops the script around it, set -e or not; it prints exactly one line:
#   HOST_STEP <inst> evict-mdbx - resident_pages_before=<n> resident_pages_after=<n>
#   HOST_STEP <inst> read-ahead-kb <KiB> read_ahead_kb_before=<n> read_ahead_kb_after=<n>
#   HOST_STEP <inst> <step> <KiB|-> failed <reason>
# evict-mdbx: fsync of <datadir>/db/mdbx.dat, then posix_fadvise(DONTNEED) over it; its resident
# pages (fincore, else mincore) must then read 0. No mdbx.dat: 0/0. read-ahead-kb: writes <KiB> to
# /sys/block/<disk>/queue/read_ahead_kb of the disk under <datadir> and reads it back (the kernel
# keeps whole pages, so a value that is not a multiple of 4 reads back lower and fails). The lines
# map onto host_steps entries through bench_host_step_record. <datadir> `-` takes the datadir from
# the surrounding script at run time: the text keeps it as RD="${D:-}" and sets D="$RD" after the
# literal D line (an empty or
# unset $D there falls back to DATA_DIR, as no <datadir> does). Prints the script only (no GCP
# call); non-zero and nothing printed for a bad instance name, step, KiB or datadir.
bench_host_step_script() {
    local inst="${1:-}" step="${2:-}" v="-" d=""
    _bench_host_name_ok "${inst}" || { echo "❌ bench_host_step_script: '${inst}' is not an instance name" >&2; return 1; }
    case "${step}" in
        evict-mdbx) [ "$#" -le 3 ] || { echo "❌ bench_host_step_script: evict-mdbx takes [<datadir>] only" >&2; return 1; }
                    d="${3:-}" ;;
        read-ahead-kb)
            v="${3:-}"; d="${4:-}"
            case "${v}" in ''|*[!0-9]*|0?*) echo "❌ bench_host_step_script: read-ahead-kb '${v}' is not an integer without leading zeros (KiB)" >&2; return 1 ;; esac
            [ "$#" -le 4 ] || { echo "❌ bench_host_step_script: read-ahead-kb takes <KiB> [<datadir>] only" >&2; return 1; } ;;
        *) echo "❌ bench_host_step_script: unknown step '${step}' (evict-mdbx, read-ahead-kb)" >&2; return 1 ;;
    esac
    case "${d}" in ''|-|/?*) ;; *) echo "❌ bench_host_step_script: datadir '${d}' is not an absolute path (or -)" >&2; return 1 ;; esac
    echo "# host step ${step} (bench_host_step_script): one subshell, one HOST_STEP line; HOST_STEP_RC 0 = held, 1 = failed"
    echo 'HOST_STEP_RC=0'
    echo '('
    bench_remote_lib_preamble
    # shellcheck disable=SC2016  # `-`: the node's shell expands $D, the surrounding script's datadir
    [ "${d}" != - ] || echo 'RD="${D:-}"'
    printf 'D=%q\n' "${d}"
    # shellcheck disable=SC2016  # as above
    [ "${d}" != - ] || echo 'D="$RD"'
    _bench_host_step_wrappers standalone "${inst}" "${step}" "${v}"
    cat <<'EOS'
if [ -z "$D" ]; then
    r=0; D="$(meta DATA_DIR)" || r=$?
    [ "$r" = 0 ] || hsfail "DATA_DIR unreadable in /etc/telcoin/.node-meta (meta rc $r)"
fi
case "$D" in /?*) ;; *) hsfail "datadir '$D' is not an absolute path" ;; esac
[ -d "$D" ] || hsfail "datadir $D is not a directory"
EOS
    _bench_host_step_body "${step}" "${v}"
    echo ') || HOST_STEP_RC=$?'
}

# bench_host_step_record <inst> — the host steps of one node from a session's output on stdin (CRs
# dropped): one JSON array, one entry per line that starts `HOST_STEP <inst> `, in order, each
#   {"step": "evict-mdbx"|"read-ahead-kb", "value": null|"<KiB>", "result": <result>}
# with <result> {"resident_pages_before": n, "resident_pages_after": n},
# {"read_ahead_kb_before": n, "read_ahead_kb_after": n} or {"failed": "<reason>"} (a line it cannot
# parse gives {"failed": "unparsed: <line>"}): node_startup[inst].host_steps, and the per-node
# result of a param_arms[].host entry (arms/MANIFEST-FIELDS.md). No line: []. rc 0 always.
bench_host_step_record() {
    local inst="${1:-}" out
    out="$(awk -v p="HOST_STEP ${inst} " 'index($0, p) == 1 { print substr($0, length(p) + 1) }' | jq -R -s -c '
        [split("\n")[] | select(length > 0) | . as $l | split(" ") as $w | $w[0] as $s | ($w[1] // "") as $v
         | ({"evict-mdbx": ["resident_pages_before", "resident_pages_after"],
             "read-ahead-kb": ["read_ahead_kb_before", "read_ahead_kb_after"]}[$s]) as $k
         | (if $s == "evict-mdbx" then $v == "-" else ($v | test("^(0|[1-9][0-9]*)$")) end) as $vok
         | {step: $s, value: (if $v == "-" or $v == "" then null else $v end),
            result: (if $k == null or ($vok | not) then {failed: ("unparsed: " + $l)}
                     elif $w[2] == "failed" then {failed: ($w[3:] | join(" ") | if . == "" then "(no reason given)" else . end)}
                     elif ($w | length) == 4 and ($w[2] | test("^" + $k[0] + "=(0|[1-9][0-9]{0,17})$"))
                          and ($w[3] | test("^" + $k[1] + "=(0|[1-9][0-9]{0,17})$"))
                     then {($k[0]): ($w[2] | ltrimstr($k[0] + "=") | tonumber),
                           ($k[1]): ($w[3] | ltrimstr($k[1] + "=") | tonumber)}
                     else {failed: ("unparsed: " + $l)} end)}]' 2>/dev/null)" || out=""
    printf '%s\n' "${out:-[]}"
    return 0
}

# bench_host_probe_script <inst> [<datadir>] — the pre-start host probe: deploy step 7 sends it after
# bench_fsync_probe_script in each node's pre-start session (the one-VM probe sends it alone, with
# its <datadir>). A subshell that only prints, so nothing in it stops the session; it takes well
# under a second on a node (a 30-s alarm bounds it) and prints exactly one line:
#   HOST_PROBE <inst> <json>                   node_startup[inst].host, compact, the frozen keys in order
#   HOST_PROBE <inst> probe_failed <reason>    no python3, the datadir unusable, the program failed
# <datadir> defaults to DATA_DIR from /etc/telcoin/.node-meta (as bench_fsync_probe_script reads it);
# the memory limit is read off the docker run line of /usr/local/libexec/telcoin/tn-start-docker
# (the unit is stopped, so no container is there to inspect); mdbx_dat_folios is null (no process
# maps mdbx.dat yet, and the folio census resolves through one). Run it before any host step: its
# read_ahead_kb is the value the node booted with, which an arm without the read-ahead step puts
# back. <datadir> `-` takes the datadir from the surrounding script at run time (RD="${D:-}" before
# the literal D line, D="$RD" after it; empty or
# unset there: DATA_DIR). Prints the script only (no GCP call); non-zero and nothing printed for a
# bad instance name or a <datadir> that is neither absolute nor `-`.
bench_host_probe_script() {
    local inst="${1:-}" d="${2:-}"
    _bench_host_name_ok "${inst}" || { echo "❌ bench_host_probe_script: '${inst}' is not an instance name" >&2; return 1; }
    case "${d}" in ''|-|/?*) ;; *) echo "❌ bench_host_probe_script: datadir '${d}' is not an absolute path (or -)" >&2; return 1 ;; esac
    echo '# host probe (bench_host_probe_script): a subshell that only prints one HOST_PROBE line'
    echo '('
    bench_remote_lib_preamble
    # shellcheck disable=SC2016  # `-`: the node's shell expands $D, the surrounding script's datadir
    [ "${d}" != - ] || echo 'RD="${D:-}"'
    printf 'I=%q\nD=%q\n' "${inst}" "${d}"
    # shellcheck disable=SC2016  # as above
    [ "${d}" != - ] || echo 'D="$RD"'
    cat <<'EOS'
hp(){ echo "HOST_PROBE $I probe_failed $*"; exit 0; }
if [ -z "$D" ]; then
    r=0; D="$(meta DATA_DIR)" || r=$?
    [ "$r" = 0 ] || hp "DATA_DIR unreadable in /etc/telcoin/.node-meta (meta rc $r)"
fi
case "$D" in /?*) ;; *) hp "datadir '$D' is not an absolute path" ;; esac
[ -d "$D" ] || hp "datadir $D is not a directory"
command -v python3 >/dev/null 2>&1 || hp "no python3 on the node"
r=0; python3 - probe "$I" "$D" /usr/local/libexec/telcoin/tn-start-docker <<'PY' || r=$?
EOS
    _bench_host_py
    cat <<'EOS'
PY
[ "$r" = 0 ] || hp "python3 exited $r"
EOS
    echo ') || true'
}

# _bench_host_fields — the keys of node_startup[inst].host in table order, each <key>:<s|i|o>
# (string, integer or the folio object; any may be null). arms/MANIFEST-FIELDS.md is the contract.
_bench_host_fields() {
    printf '%s\n' "kernel:s cmdline:s os_release:s image_serial:s mem_total_kb:i nproc:i datadir:s" \
        "datadir_mount_source:s datadir_fstype:s datadir_mount_options:s disk:s read_ahead_kb:i" \
        "max_sectors_kb:i max_hw_sectors_kb:i scheduler:s nr_requests:i thp_enabled:s thp_defrag:s" \
        "thp_shmem_enabled:s khugepaged_defrag:s vm_dirty_ratio:i vm_dirty_background_ratio:i" \
        "vm_dirty_bytes:i vm_dirty_background_bytes:i vm_dirty_expire_centisecs:i" \
        "vm_dirty_writeback_centisecs:i vm_swappiness:i vm_vfs_cache_pressure:i" \
        "container_memory_limit_bytes:i mdbx_dat_size_bytes:i mdbx_dat_resident_pages:i mdbx_dat_folios:o" \
        "lru_gen_enabled:s" | tr '\n' ' '
}

# _bench_host_uniform_fields — the fields HOST_PROBE_SUMMARY compares across the fleet.
_bench_host_uniform_fields() {
    printf '%s' "kernel image_serial datadir_fstype datadir_mount_options read_ahead_kb max_sectors_kb scheduler " \
        "nr_requests thp_enabled thp_defrag thp_shmem_enabled khugepaged_defrag vm_dirty_ratio " \
        "vm_dirty_background_ratio vm_dirty_bytes vm_dirty_background_bytes vm_dirty_expire_centisecs " \
        "vm_dirty_writeback_centisecs vm_swappiness vm_vfs_cache_pressure " "nproc container_memory_limit_bytes " \
        "lru_gen_enabled"
}

# bench_host_probe_record <inst> — node_startup[<inst>].host from that node's session output on stdin
# (CRs dropped): the last line that starts `HOST_PROBE <inst> ` gives
#   the host object, its keys exactly _bench_host_fields' in that order   from `<json>`
#   {"probe_failed":true,"reason":"<text>"}    from `probe_failed <reason>`, JSON that is not an object
#                                              with every key at its type ("unparsed: ..."), or no line
# One JSON object on one line, rc 0 (a failed probe never stops step 7).
bench_host_probe_record() {
    local inst="${1:-}" line rest out=""
    line="$(awk -v p="HOST_PROBE ${inst} " 'index($0, p) == 1 { l = $0 } END { print l }')" || line=""
    rest="${line#"HOST_PROBE ${inst} "}"
    if [ -z "${line}" ]; then
        rest="no HOST_PROBE line in the session output"
    else
        case "${rest}" in
            "{"*)
                out="$(printf '%s\n' "${rest}" | jq -c --arg f "$(_bench_host_fields)" '
                    ($f | split(" ") | map(select(. != "") | split(":"))) as $fs
                    | def ok($t): if . == null then true elif $t == "s" then type == "string"
                                  elif $t == "i" then type == "number" and . == floor and . >= 0
                                  else type == "object" and all(to_entries[];
                                       (.key | test("^(0|[1-9][0-9]?)$")) and (.value | type) == "number") end;
                    if type != "object" then {probe_failed: true, reason: "unparsed: not a JSON object"}
                    else . as $h
                    | [$fs[] | .[0] as $k | select(($h | has($k)) | not) | $k] as $miss
                    | [$fs[] | . as [$k, $t] | select(($h | has($k)) and (($h[$k] | ok($t)) | not)) | $k] as $bad
                    | if ($miss | length) > 0 then {probe_failed: true, reason: ("unparsed: no " + ($miss | join(", ")))}
                      elif ($bad | length) > 0 then {probe_failed: true, reason: ("unparsed: wrong type: " + ($bad | join(", ")))}
                      else reduce $fs[] as [$k, $t] ({}; .[$k] = $h[$k]) end
                    end' 2>/dev/null)" || out=""
                [ -n "${out}" ] || rest="unparsed: not JSON: ${rest:0:120}" ;;
            "probe_failed "*) rest="${rest#probe_failed }" ;;
            probe_failed) rest="(no reason given)" ;;
            *) rest="unparsed: ${rest:0:120}" ;;
        esac
    fi
    [ -n "${out}" ] || out="$(jq -n -c --arg r "${rest}" '{probe_failed: true, reason: $r}')"
    printf '%s\n' "${out}"
    return 0
}

# bench_host_probe_summary <manifest> <inst…> — one line on the fleet's host probes, read from
# node_startup[<inst>].host in <manifest> (an instance without a record is left out):
#   [⚠ ]HOST_PROBE_SUMMARY kernel=<v> image=<serial> ra_kb=<n> uniform=yes|no differ=[<inst> …] probe_failed=[<inst> …]
# Each value is the most common one among the nodes that probed (a tie goes to the first in the
# order given, the fleet's), `-` when none probed or that value is null. differ lists, in that
# order, the nodes whose value of any _bench_host_uniform_fields field is not the most common one;
# uniform=yes when a node probed and differ is empty. "⚠ " leads when uniform=no or probe_failed
# lists a node. rc 0 always: a host difference is a finding for the analysis, never a reason to stop.
bench_host_probe_summary() {
    local m="${1:-}" out
    [ "$#" -eq 0 ] || shift
    out="$(jq -r --arg ii "$*" --arg uf "$(_bench_host_uniform_fields)" '
        def mode($ok; $k): [$ok[] | .h[$k] | tojson] as $v
            | if ($v | length) == 0 then null
              else [range(0; $v | length) as $j | {s: $v[$j], n: ([$v[] | select(. == $v[$j])] | length)}] as $c
                   | ($c | map(.n) | max) as $top | first($c[] | select(.n == $top)) | .s end;
        def show($common; $k): ($common[$k] // "null" | fromjson) as $x | if $x == null then "-" else ($x | tostring) end;
        [($ii | split(" ") | map(select(. != "")))[] as $i
         | {i: $i, h: (.node_startup[$i].host // null)} | select(.h != null)] as $r
        | [$r[] | select((.h | type) == "object" and (.h.probe_failed // false) != true)] as $ok
        | [$r[] | select(((.h | type) == "object" and (.h.probe_failed // false) != true) | not) | .i] as $bad
        | ($uf | split(" ") | map(select(. != ""))) as $u
        | (reduce $u[] as $k ({}; .[$k] = mode($ok; $k))) as $common
        | [$ok[] | . as $n | select(any($u[]; ($n.h[.] | tojson) != $common[.])) | .i] as $differ
        | (($ok | length) > 0 and ($differ | length) == 0) as $uni
        | (if ($uni | not) or ($bad | length) > 0 then "⚠ " else "" end)
          + "HOST_PROBE_SUMMARY kernel=\(show($common; "kernel")) image=\(show($common; "image_serial"))"
          + " ra_kb=\(show($common; "read_ahead_kb")) uniform=\(if $uni then "yes" else "no" end)"
          + " differ=[\($differ | join(" "))] probe_failed=[\($bad | join(" "))]"
    ' "${m}" 2>/dev/null)" || out=""
    [ -n "${out}" ] || out="⚠ HOST_PROBE_SUMMARY kernel=- image=- ra_kb=- uniform=no differ=[] probe_failed=[] (cannot read ${m})"
    printf '%s\n' "${out}"
    return 0
}

# --- the first-start arm (BENCH_ARM_FILE; deploy step 7) -----------------------------------------
# With BENCH_ARM_FILE set, deploy step 7 starts the fleet in that arm (the headline run: no restart).
# The arm file is read by tools/params-apply.sh, the one parser of its grammar (arms/README.md), in its
# local mode `--arm-file <file> --print-state`, whose output is fixed:
#   ARM_NAME <name>
#   ARM_SHA256 <lower-case hex of the file's bytes>
#   ARM_SWITCH <key> <bool|int|dur> <value>    one per row of arms/switches.tsv, in its order (defaults included)
#   ARM_HOST <read-ahead-kb|evict-mdbx> <KiB|->  zero or more, in run order
# The switches go into each node's parameters.yaml through the pre-start script's setp (the per-node
# override path), the host steps through its host-step code; the comparisons below follow the arm
# tool's rules (bool by case, int without leading zeros, dur by its value in ms).
BENCH_SWITCHES_TSV="${BENCH_LIB_DIR}/arms/switches.tsv"
BENCH_ARM_STATE_FOR=""; BENCH_ARM_NAME=""; BENCH_ARM_SHA256=""; BENCH_ARM_SWITCHES=""; BENCH_ARM_HOST=""

# _bench_switch_rows — arms/switches.tsv without its header: "<key> <type> <default> <optional>" per row.
_bench_switch_rows() {
    awk -F'\t' 'NR > 1 && NF == 6 { print $1, $2, $3, $6 }' "${BENCH_SWITCHES_TSV}"
}

# _bench_switch_norm <bool|int|dur> <value> — the value in one spelling, to compare (the arm tool's
# norm_val): bool lower case, int without leading zeros, dur in whole ms (<n>ms, <n>s, <n>m, decimals
# allowed); "?<value>" for anything else.
_bench_switch_norm() {
    local v
    case "$1" in
        bool) v="$(printf '%s' "$2" | tr 'A-Z' 'a-z')"; case "${v}" in true|false) echo "${v}" ;; *) echo "?$2" ;; esac ;;
        int) case "$2" in ''|*[!0-9]*) echo "?$2" ;; *) v="$(printf '%s' "$2" | sed 's/^0*//')"; echo "${v:-0}" ;; esac ;;
        dur) v="$(awk -v v="$2" 'BEGIN {
                 if (v !~ /^[0-9]+(\.[0-9]+)?(ms|s|m)$/) exit
                 u = v; sub(/^[0-9.]+/, "", u)
                 n = substr(v, 1, length(v) - length(u)); i = n; f = ""
                 if (index(n, ".")) { i = substr(n, 1, index(n, ".") - 1); f = substr(n, index(n, ".") + 1) }
                 if (length(f) > 9) f = substr(f, 1, 9)
                 mul = (u == "ms") ? 1 : ((u == "s") ? 1000 : 60000)
                 printf "%d\n", i * mul + (f == "" ? 0 : int(f * mul / (10 ^ length(f)))) }')"
             echo "${v:-?$2}" ;;
        *) echo "?$2" ;;
    esac
}

# bench_arm_state_load [<arm file>] — read the arm (default BENCH_ARM_FILE) once through
# `tools/params-apply.sh --arm-file <file> --print-state` into BENCH_ARM_NAME, BENCH_ARM_SHA256,
# BENCH_ARM_SWITCHES ("<key> <type> <value>" per switch, tsv order) and BENCH_ARM_HOST ("<step>
# <KiB|->" per host step, run order); BENCH_ARM_STATE_FOR names the file they belong to, and a second
# call for the same file reads nothing. Call it in the shell that uses them (never in $(...)). rc 1
# with the reason on stderr when the tool refuses the file, or its output is not the fixed format
# (every switches.tsv row once, in order, with its type), or ARM_SHA256 is not the file's.
bench_arm_state_load() {
    local f="${1:-${BENCH_ARM_FILE:-}}" out err rc=0 line w1 w2 w3 w4 w5 name="" sha="" sw="" host="" rows want got
    [ -n "${f}" ] || { echo "❌ bench_arm_state_load: no arm file (BENCH_ARM_FILE is empty)" >&2; return 1; }
    [ "${BENCH_ARM_STATE_FOR}" != "${f}" ] || return 0
    err="$(mktemp "${TMPDIR:-/tmp}/bench-arm-state.XXXXXX")" || { echo "❌ bench_arm_state_load: no temp file" >&2; return 1; }
    out="$(bash "${BENCH_LIB_DIR}/tools/params-apply.sh" --arm-file "${f}" --print-state 2>"${err}")" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        echo "❌ ${f}: tools/params-apply.sh --print-state refused the arm (rc ${rc}): $(tr '\n' ' ' < "${err}" | cut -c1-400)" >&2
        rm -f "${err}"; return 1
    fi
    rm -f "${err}"
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        w1="" w2="" w3="" w4="" w5=""
        read -r w1 w2 w3 w4 w5 <<< "${line}"
        case "${w1}" in
            ARM_NAME) [ -z "${name}" ] && [ -n "${w2}" ] && [ -z "${w3}" ] || w1="?"; name="${w2}" ;;
            ARM_SHA256) [ -z "${sha}" ] && [ -n "${w2}" ] && [ -z "${w3}" ] || w1="?"; sha="${w2}" ;;
            ARM_SWITCH) [ -n "${w4}" ] && [ -z "${w5}" ] || w1="?"; sw="${sw}${w2} ${w3} ${w4}"$'\n' ;;
            ARM_HOST) [ -n "${w3}" ] && [ -z "${w4}" ] || w1="?"; host="${host}${w2} ${w3}"$'\n' ;;
            *) w1="?" ;;
        esac
        [ "${w1}" != "?" ] || { echo "❌ ${f}: --print-state printed '${line}' (want ARM_NAME, ARM_SHA256, ARM_SWITCH, ARM_HOST lines of the fixed format)" >&2; return 1; }
    done <<< "${out}"
    case "${name}" in ''|[!a-z0-9]*|*[!a-z0-9-]*) echo "❌ ${f}: --print-state gave the arm name '${name}' ([a-z0-9][a-z0-9-]{0,39})" >&2; return 1 ;; esac
    [ "${#name}" -le 40 ] || { echo "❌ ${f}: --print-state gave the arm name '${name}' ([a-z0-9][a-z0-9-]{0,39})" >&2; return 1; }
    case "${sha}" in *[!0-9a-f]*|'') sha="?${sha}" ;; esac
    [ "${#sha}" -eq 64 ] || { echo "❌ ${f}: --print-state gave ARM_SHA256 '${sha#?}', not 64 lower-case hex" >&2; return 1; }
    got="$(bench_file_sha256 "${f}")" || got=""
    [ "${got}" = "${sha}" ] || { echo "❌ ${f}: ARM_SHA256 ${sha} is not the file's sha256 (${got:-unreadable})" >&2; return 1; }
    rows="$(_bench_switch_rows | awk '{ print $1, $2 }')"
    want="$(printf '%s\n' "${sw}" | awk 'NF { print $1, $2 }')"
    [ -n "${rows}" ] && [ "${want}" = "${rows}" ] || { echo "❌ ${f}: --print-state's ARM_SWITCH lines are not every arms/switches.tsv row once, in order, with its type" >&2; return 1; }
    while read -r w1 w2 w3; do
        [ -n "${w1}" ] || continue
        case "$(_bench_switch_norm "${w2}" "${w3}")" in '?'*) echo "❌ ${f}: --print-state gave ${w1}=${w3}, not a ${w2}" >&2; return 1 ;; esac
    done <<< "${sw}"
    while read -r w1 w2; do
        [ -n "${w1}" ] || continue
        w3=ok
        case "${w1}:${w2}" in
            evict-mdbx:-|read-ahead-kb:0) ;;
            read-ahead-kb:[1-9]*) case "${w2}" in *[!0-9]*) w3=bad ;; esac ;;
            *) w3=bad ;;
        esac
        [ "${w3}" = ok ] || { echo "❌ ${f}: --print-state gave the host step '${w1} ${w2}' (evict-mdbx -, read-ahead-kb <KiB>)" >&2; return 1; }
    done <<< "${host}"
    BENCH_ARM_NAME="${name}"; BENCH_ARM_SHA256="${sha}"; BENCH_ARM_SWITCHES="${sw}"; BENCH_ARM_HOST="${host}"
    BENCH_ARM_STATE_FOR="${f}"
}

# bench_file_sha256 <file> — its lower-case hex SHA-256 (sha256sum, else shasum -a 256).
bench_file_sha256() {
    { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; } | awk 'NR == 1 { print $1 }'
}

# bench_arm_writes — the loaded arm's switches that differ from their switches.tsv default (by value),
# "<key>=<value>" per line in tsv order: what the pre-start script writes into every node's
# parameters.yaml. A switch at its default is left out (the node reads an absent key as its default),
# so an integer switch is never written as 0.
bench_arm_writes() {
    local k t v rk rt rd
    while read -r k t v; do
        [ -n "${k}" ] || continue
        while read -r rk rt rd _; do
            [ "${rk}" = "${k}" ] || continue
            [ "$(_bench_switch_norm "${t}" "${v}")" = "$(_bench_switch_norm "${rt}" "${rd}")" ] || printf '%s=%s\n' "${k}" "${v}"
        done <<< "$(_bench_switch_rows)"
    done <<< "${BENCH_ARM_SWITCHES}"
}

# bench_arm_host_value <step> — the loaded arm's value of host step <step> ("-" for evict-mdbx); ""
# when the arm does not list it.
bench_arm_host_value() {
    printf '%s\n' "${BENCH_ARM_HOST}" | awk -v s="$1" '$1 == s { print $2; exit }'
}

# bench_arm_switches_json — the loaded arm's full switch state as compact JSON {key: "value"} (tsv order).
bench_arm_switches_json() {
    printf '%s\n' "${BENCH_ARM_SWITCHES}" | jq -R -s -c 'split("\n") | map(select(length > 0) | split(" ") | {(.[0]): .[2]}) | add // {}'
}

# bench_arm_override_conflicts — one line per BENCH_NODE_PARAM_OVERRIDES item that sets a node switch
# (arms/switches.tsv) while BENCH_ARM_FILE is set: the arm states every switch for every node, so a
# per-node value beside it would contradict it. No output when there is none (or no arm file).
bench_arm_override_conflicts() {
    local i kv k rk
    [ -n "${BENCH_ARM_FILE:-}" ] || return 0
    for i in "${!INSTANCE_NAMES[@]}"; do
        bench_node_overrides "${i}" | while IFS= read -r kv; do
            k="${kv%%=*}"
            while read -r rk _; do
                [ "${rk}" != "${k}" ] || echo "BENCH_NODE_PARAM_OVERRIDES sets the node switch ${k} on ${INSTANCE_NAMES[$i]} beside BENCH_ARM_FILE (the arm states every switch on every node; set it in the arm file)"
            done <<< "$(_bench_switch_rows)"
        done
    done
}

# bench_switch_line_values <line> — the key=value tokens after the `node switches` message text of a
# node's log line, one "key=value" per line (quotes dropped); nothing when the line lacks the text.
bench_switch_line_values() {
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

# bench_switch_readback <expected JSON {key: "value"}> <node switches line> — rc 0 when the line
# shows every switch of arms/switches.tsv at its expected value (a key the JSON lacks: its default),
# compared by value (_bench_switch_norm). A key the line does not print passes only for an optional
# switch expected at its default. Otherwise rc 1 and one line: the disagreements
# ("<key>=<logged> (expected <value>)", "<key> is not on the line (expected <value>)"), or why the
# line cannot be read.
bench_switch_readback() {
    local exp="$1" line="$2" vals k t d o want got out=""
    [ -n "${line}" ] && [ "${line}" != "-" ] || { echo "no 'node switches' line in the node's log since its start (an image that does not log it?)"; return 1; }
    vals="$(bench_switch_line_values "${line}")"
    [ -n "${vals}" ] || { echo "the line holds no key=value after 'node switches': ${line:0:200}"; return 1; }
    while read -r k t d o; do
        [ -n "${k}" ] || continue
        want="$(printf '%s' "${exp}" | jq -r --arg k "${k}" '.[$k] // empty' 2>/dev/null)" || want=""
        want="${want:-${d}}"
        got="$(printf '%s\n' "${vals}" | sed -n "s/^${k}=//p" | tail -n 1)"
        if printf '%s\n' "${vals}" | grep -q "^${k}="; then
            [ "$(_bench_switch_norm "${t}" "${got}")" = "$(_bench_switch_norm "${t}" "${want}")" ] \
                || out="${out}, ${k}=${got} (expected ${want})"
        elif [ "${o}" = yes ] && [ "$(_bench_switch_norm "${t}" "${want}")" = "$(_bench_switch_norm "${t}" "${d}")" ]; then
            :
        else
            out="${out}, ${k} is not on the line (expected ${want})"
        fi
    done <<< "$(_bench_switch_rows)"
    [ -n "${out}" ] || return 0
    echo "${out#, }"
    return 1
}

# _bench_node_mode_cmd — the remote command bench_node_mode runs (one tn_iap_ssh, no sudo): the
# node's raw tn_nodeMode answer from its RPC on 127.0.0.1:8545; never non-zero on the node.
_bench_node_mode_cmd() {
    printf '%s' "curl -s --max-time 10 -H 'content-type: application/json' --data '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tn_nodeMode\",\"params\":[]}' http://127.0.0.1:8545 || true"
}

# _bench_node_idx_zone <caller> <node-index> — "<inst> <zone>" of INSTANCE_NAMES[<node-index>];
# non-zero with a message on stderr for a bad index.
_bench_node_idx_zone() {
    local inst zone
    case "${2:-}" in ''|*[!0-9]*) echo "❌ $1: bad node index '${2:-}'" >&2; return 1 ;; esac
    inst="${INSTANCE_NAMES[$2]:-}"; zone="${ZONES[$2]:-}"
    [ -n "${inst}" ] && [ -n "${zone}" ] || { echo "❌ $1: no node at index $2" >&2; return 1; }
    printf '%s %s\n' "${inst}" "${zone}"
}

# bench_node_mode <node-index> — the node's tn_nodeMode (CvvActive, CvvInactive or Observer), read
# with one ssh (_bench_node_mode_cmd). Empty and rc 1 when it cannot be read: ssh failed, the RPC
# did not answer, or the answer carries no result string.
bench_node_mode() {
    local iz out mode
    iz="$(_bench_node_idx_zone bench_node_mode "${1:-}")" || return 1
    out="$(tn_iap_ssh "${iz% *}" "${iz#* }" "$(_bench_node_mode_cmd)" </dev/null)" || return 1
    mode="$(printf '%s\n' "${out}" | tr -d '\r' | sed -n 's/.*"result"[[:space:]]*:[[:space:]]*"\([A-Za-z0-9_]\{1,40\}\)".*/\1/p' | head -1)"
    [ -n "${mode}" ] || return 1
    printf '%s\n' "${mode}"
}

# _bench_ro_retry <fn> <args...> — run a read-only node read; when it fails, run it once more
# BENCH_RO_RETRY_SECS (default 5) later. Its output and status are the last attempt's.
_bench_ro_retry() {
    local s="${BENCH_RO_RETRY_SECS:-5}"
    case "${s}" in ''|*[!0-9]*) s=5 ;; esac
    "$@" && return 0
    sleep "${s}"
    "$@"
}

# _bench_next_boundary — the unix time of the next epoch boundary after now: the ConsensusRegistry's
# current epoch opened at epoch_start_unix and lasts duration_secs (recovery-schedule.py over the
# RPC tunnel at RPC_URL, as deploy step 10's registry probe; 120 s alarm). Non-zero and nothing
# printed when the registry cannot be read.
_bench_next_boundary() {
    local now out
    now="$(bench_now_unix)"
    out="$(perl -e 'alarm shift; exec @ARGV' 120 python3 "${BENCH_LIB_DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" \
        --earliest-kill "${now}" </dev/null 2>/dev/null)" || return 1
    printf '%s' "${out}" | jq -er --argjson now "${now}" '
        (.epoch_start_unix | numbers) as $s | (.duration_secs | numbers) as $d | select($d > 0)
        | if $s > $now then $s else $s + $d * (((($now - $s) / $d) | floor) + 1) end' 2>/dev/null
}

# bench_fleet_ready <max-wait-secs> <label> — rc 0 when every validator (NODE_ROLES) reports
# tn_nodeMode CvvActive. At most two sparse passes over the validators, no tight polling (IAP):
# pass 1 reads each once (a failed read once more, BENCH_RO_RETRY_SECS later). If any is not
# CvvActive and <max-wait-secs> > 0, it sleeps until the next epoch boundary (a pending validator
# joins there; _bench_next_boundary) plus BENCH_FLEET_READY_SETTLE_SECS, never past <max-wait-secs>
# after the start (the whole cap when the registry cannot be read), then pass 2 reads every
# validator again and gives the ones still not CvvActive one more read BENCH_NODE_BACK_SECS after
# pass 2 began. Records manifest.fleet_ready = {label, ts, ok, waited_secs (the seconds slept between
# reads), passes, modes: {<inst>: <mode>|null (unreadable)}} and merges the readable modes into
# manifest.fleet_modes (an unreadable node's entry is dropped). rc 1 lists every validator not
# CvvActive on stderr.
bench_fleet_ready() {
    local max="${1:-}" label="${2:-}" settle="${BENCH_FLEET_READY_SETTLE_SECS:-90}" back="${BENCH_NODE_BACK_SECS:-180}"
    local t0 now i m fm passes=1 waited=0 s b p2 notready="" nval=0 modes ok=false
    case "${max}" in ''|*[!0-9]*) echo "❌ bench_fleet_ready <max-wait-secs> <label>: bad max-wait '${max}'" >&2; return 1 ;; esac
    [ -n "${label}" ] || { echo "❌ bench_fleet_ready <max-wait-secs> <label>: no label" >&2; return 1; }
    case "${settle}" in ''|*[!0-9]*) settle=90 ;; esac
    case "${back}" in ''|*[!0-9]*) back=180 ;; esac
    t0="$(bench_now_unix)"
    fm=()
    echo "    fleet ready (${label}): every validator CvvActive (max wait ${max}s)"
    for i in "${!INSTANCE_NAMES[@]}"; do
        [ "${NODE_ROLES[$i]:-}" = "validator" ] || continue
        nval=$((nval + 1))
        m="$(_bench_ro_retry bench_node_mode "${i}")" || m=""
        fm[$i]="${m}"
        [ "${m}" = "CvvActive" ] || notready="${notready} ${INSTANCE_NAMES[$i]}=${m:-unreadable}"
    done
    if [ -n "${notready}" ] && [ "${max}" -gt 0 ]; then
        passes=2
        now="$(bench_now_unix)"
        if b="$(_bench_next_boundary)" && [ -n "${b}" ]; then
            s=$((b + settle - now))
            echo "      not CvvActive:${notready}; next epoch boundary $(bench_iso_from_unix "${b}") + ${settle}s settle"
        else
            s="${max}"
            bench_warn "fleet ready (${label}): the registry (${RPC_URL:-no RPC_URL}) cannot be read; waiting the whole cap"
            echo "      not CvvActive:${notready}"
        fi
        [ "${s}" -le $((t0 + max - now)) ] || s=$((t0 + max - now))
        [ "${s}" -ge 0 ] || s=0
        echo "      waiting ${s}s, then one more pass"
        sleep "${s}"; waited=$((waited + s))
        p2="$(bench_now_unix)"; notready=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            [ "${NODE_ROLES[$i]:-}" = "validator" ] || continue
            m="$(_bench_ro_retry bench_node_mode "${i}")" || m=""
            fm[$i]="${m}"
            [ "${m}" = "CvvActive" ] || notready="${notready} ${i}"
        done
        if [ -n "${notready}" ] && [ "${back}" -gt 0 ]; then
            now="$(bench_now_unix)"; s=$((p2 + back - now)); [ "${s}" -ge 0 ] || s=0
            echo "      still not CvvActive:$(for i in ${notready}; do printf ' %s' "${INSTANCE_NAMES[$i]}"; done); one more read in ${s}s"
            sleep "${s}"; waited=$((waited + s))
            for i in ${notready}; do
                m="$(_bench_ro_retry bench_node_mode "${i}")" || m=""
                fm[$i]="${m}"
            done
        fi
        notready=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            [ "${NODE_ROLES[$i]:-}" = "validator" ] || continue
            [ "${fm[$i]:-}" = "CvvActive" ] || notready="${notready} ${INSTANCE_NAMES[$i]}=${fm[$i]:-unreadable}"
        done
    fi
    [ -n "${notready}" ] || ok=true
    modes="$(for i in "${!INSTANCE_NAMES[@]}"; do
        [ "${NODE_ROLES[$i]:-}" = "validator" ] || continue
        printf '%s\t%s\n' "${INSTANCE_NAMES[$i]}" "${fm[$i]:-}"
    done | jq -c -R -s 'split("\n") | map(select(length > 0) | split("\t")) | map({key: .[0], value: (if (.[1] // "") == "" then null else .[1] end)}) | from_entries')" || modes=""
    [ -n "${modes}" ] || modes='{}'
    bench_manifest_jq --arg label "${label}" --arg ts "$(bench_now_iso)" --argjson ok "${ok}" \
        --argjson w "${waited}" --argjson p "${passes}" --argjson modes "${modes}" '
        .fleet_ready = {label: $label, ts: $ts, ok: $ok, waited_secs: $w, passes: $p, modes: $modes}
        | .fleet_modes = (((.fleet_modes // {}) + $modes) | with_entries(select(.value | type == "string")))' \
        || bench_warn "fleet ready (${label}): could not record fleet_ready in $(bench_manifest)"
    if [ "${ok}" = true ]; then
        echo "    ✓ fleet ready (${label}): ${nval}/${nval} validators CvvActive (passes ${passes}, waited ${waited}s)"
        return 0
    fi
    echo "    ✗ fleet not ready (${label}) after ${passes} pass(es), waited ${waited}s; not CvvActive:${notready}" >&2
    return 1
}

# _bench_admission_read_script — the remote script of bench_admission_read (root, on stdin): the
# three admission families from the node's metrics endpoint (METRICS_PORT from .node-meta, 9101
# when absent or empty, as obs_metrics_port), then NODE_MODE=<tn_nodeMode|->. Never non-zero.
_bench_admission_read_script() {
    echo 'set -u'
    bench_remote_lib_preamble
    cat <<'EOS'
r=0; P="$(meta METRICS_PORT)" || r=$?
[ "$r" -le 1 ] || echo "METRICS_PORT is set more than once in /etc/telcoin/.node-meta; reading 9101" >&2
[ -n "$P" ] || P=9101
case "$P" in
    *[!0-9]*|??????*) echo "METRICS_PORT '$P' is not a port number; no metrics read" >&2 ;;
    *) curl -s --max-time 10 "http://127.0.0.1:$((10#$P))/metrics" 2>/dev/null \
           | grep -E '^tn_network_(admission_mode|admission_fallback|closed_admission_denied_total)[{ ]' || true ;;
esac
m="$(curl -s --max-time 10 -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"tn_nodeMode","params":[]}' http://127.0.0.1:8545 2>/dev/null \
    | sed -n 's/.*"result"[[:space:]]*:[[:space:]]*"\([A-Za-z0-9_]\{1,40\}\)".*/\1/p' | head -1 || true)"
echo "NODE_MODE=${m:--}"
EOS
}

# bench_admission_read <node-index> — one IAP session (_bench_admission_read_script on stdin, run as
# root): the node's /metrics lines matching
#   ^tn_network_(admission_mode|admission_fallback|closed_admission_denied_total)[{ ]
# then one line NODE_MODE=<tn_nodeMode|->. A node that serves no metrics prints only the NODE_MODE
# line. rc 1 when the session failed or did not reach its NODE_MODE line.
bench_admission_read() {
    local iz out
    iz="$(_bench_node_idx_zone bench_admission_read "${1:-}")" || return 1
    out="$(_bench_admission_read_script | tn_iap_ssh_stdin "${iz% *}" "${iz#* }")" || return 1
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    printf '%s\n' "${out}" | grep -q '^NODE_MODE=' || return 1
    printf '%s\n' "${out}" | grep -E '^tn_network_(admission_mode|admission_fallback|closed_admission_denied_total)[{ ]' || true
    printf '%s\n' "${out}" | grep '^NODE_MODE=' | tail -1
}

# bench_admission_parse — Prometheus text (bench_admission_read's output, or a whole /metrics body
# plus its NODE_MODE line) on stdin -> these k=v lines on stdout, in this order:
#   mode_primary=<int|->  tn_network_admission_mode with network="primary"
#   mode_worker=<int|->   tn_network_admission_mode whose network label starts with "worker"
#   fallback=<int|->      the highest tn_network_admission_fallback over all its series
#   fallback_n=<n>        how many tn_network_admission_fallback series there are
#   denied_in=<n>         sum of tn_network_closed_admission_denied_total whose direction starts with "in"
#   denied_out=<n>        sum of the other series of that counter (any other direction, or none)
#   node_mode=<str|->     the NODE_MODE= line
# Exact family names only (a decoy such as tn_network_source_admission_denied_total never counts);
# labels in any order, extra labels ignored; a value may be written 2 or 2.0 and may be followed by a
# timestamp; spaces and tabs between fields. A mode or fallback written as something other than a
# whole number makes that key "-". Several series of one mode (e.g. two workers): the lowest wins, so
# one worker that is not Closed shows. "-" = no such series.
bench_admission_parse() {
    awk '
        BEGIN { ABSENT = "\001" }
        function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
        function isnum(v) { return v ~ /^[+-]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][+-]?[0-9]+)?$/ }
        function isint(v) { return isnum(v) && (v + 0 == int(v + 0)) }
        # lab(s, key) — the value of label <key> in the label text <s> ("a=\"x\",b=\"y\""); ABSENT if none.
        function lab(s, key,    rest, k, v, c, i, n) {
            rest = s
            while (1) {
                sub(/^[ \t,]+/, "", rest)
                if (!match(rest, /^[A-Za-z_][A-Za-z0-9_]*[ \t]*=[ \t]*"/)) return ABSENT
                k = substr(rest, 1, RLENGTH); sub(/[ \t]*=.*$/, "", k)
                rest = substr(rest, RLENGTH + 1)
                v = ""; n = length(rest)
                for (i = 1; i <= n; i++) {
                    c = substr(rest, i, 1)
                    if (c == "\\") { i++; v = v substr(rest, i, 1); continue }
                    if (c == "\"") break
                    v = v c
                }
                if (i > n) return ABSENT
                rest = substr(rest, i + 1)
                if (k == key) return v
            }
        }
        function take(w, v) {
            if (!isint(v)) { bad[w] = 1; return }
            if (!(w in m) || v + 0 < m[w]) m[w] = v + 0
        }
        { sub(/\r$/, "") }
        /^NODE_MODE=/ { nm = trim(substr($0, 11)); next }
        /^[ \t]*(#|$)/ { next }
        {
            line = $0; b = index(line, "{")
            if (b) {
                e = 0
                for (i = length(line); i > b; i--) if (substr(line, i, 1) == "}") { e = i; break }
                if (!e) next
                name = trim(substr(line, 1, b - 1)); lbl = substr(line, b + 1, e - b - 1); rest = substr(line, e + 1)
            } else {
                if (!match(line, /^[^ \t]+/)) next
                name = substr(line, 1, RLENGTH); lbl = ""; rest = substr(line, RLENGTH + 1)
            }
            if (split(trim(rest), f, "[ \t]+") < 1) next
            v = f[1]
            if (name == "tn_network_admission_mode") {
                net = lab(lbl, "network")
                if (net == "primary") take("p", v)
                else if (net != ABSENT && substr(net, 1, 6) == "worker") take("w", v)
            } else if (name == "tn_network_admission_fallback") {
                fn++
                if (!isint(v)) fbad = 1
                else if (!fseen || v + 0 > fb) { fb = v + 0; fseen = 1 }
            } else if (name == "tn_network_closed_admission_denied_total") {
                if (!isnum(v)) next
                d = lab(lbl, "direction")
                if (d != ABSENT && substr(d, 1, 2) == "in") din += v; else dout += v
            }
        }
        END {
            printf "mode_primary=%s\n", (("p" in m) && !bad["p"]) ? sprintf("%d", m["p"]) : "-"
            printf "mode_worker=%s\n", (("w" in m) && !bad["w"]) ? sprintf("%d", m["w"]) : "-"
            printf "fallback=%s\n", (fseen && !fbad) ? sprintf("%d", fb) : "-"
            printf "fallback_n=%d\n", fn
            printf "denied_in=%.0f\n", din
            printf "denied_out=%.0f\n", dout
            printf "node_mode=%s\n", (nm == "") ? "-" : nm
        }'
}

# _bench_adm_kv <key> <parsed-text> — the value of <key> in bench_admission_parse output ("" if none).
_bench_adm_kv() { printf '%s\n' "$2" | sed -n "s/^$1=//p" | tail -1; }

# _bench_adm_closed <mode> — 0 when an admission mode value is Closed (2). Mutation anchor M1: keep verbatim.
_bench_adm_closed(){ [ "${1:-}" = 2 ]; }

# _bench_adm_mode_name / _bench_adm_fallback_name <n> — the node's names for those values
# (telcoin-network crates/network-libp2p/src/metrics.rs at 3f9b0709).
_bench_adm_mode_name() { case "$1" in 0) echo Open ;; 1) echo Grace ;; 2) echo Closed ;; *) echo unknown ;; esac; }
_bench_adm_fallback_name() { case "$1" in 0) echo healthy ;; 1) echo missing ;; 2) echo stale ;; 3) echo contradictory ;; 4) echo unresolved ;; *) echo unknown ;; esac; }

# bench_admission_verdict <inst> <parsed-text> — judge bench_admission_parse output. Closed = primary
# and worker mode both Closed (_bench_adm_closed) and at least one fallback series, all 0. Prints
#   ADM_OK <inst> primary=2 worker=2 fallback=0 denied_in=<n> denied_out=<n> mode=<node_mode>     rc 0
#   ADM_BAD <inst> <reason>[; <reason>...] [primary=<p> worker=<w> fallback=<f> fallback_n=<n> mode=<m>]   rc 1
bench_admission_verdict() {
    local inst="${1:-}" p="${2:-}" mp mw fb fn di dout nm why=""
    mp="$(_bench_adm_kv mode_primary "${p}")"; mw="$(_bench_adm_kv mode_worker "${p}")"
    fb="$(_bench_adm_kv fallback "${p}")"; fn="$(_bench_adm_kv fallback_n "${p}")"
    di="$(_bench_adm_kv denied_in "${p}")"; dout="$(_bench_adm_kv denied_out "${p}")"
    nm="$(_bench_adm_kv node_mode "${p}")"
    case "${mp:--}" in
        -) why="no primary series" ;;
        *) _bench_adm_closed "${mp}" || why="primary mode ${mp} ($(_bench_adm_mode_name "${mp}")), not 2" ;;
    esac
    case "${mw:--}" in
        -) why="${why:+${why}; }no worker series" ;;
        *) _bench_adm_closed "${mw}" || why="${why:+${why}; }worker mode ${mw} ($(_bench_adm_mode_name "${mw}")), not 2" ;;
    esac
    case "${fn:-0}" in
        ''|*[!0-9]*|0) why="${why:+${why}; }no fallback series" ;;
        *) case "${fb:--}" in
               0) ;;
               -) why="${why:+${why}; }fallback unreadable" ;;
               *) why="${why:+${why}; }fallback ${fb} ($(_bench_adm_fallback_name "${fb}")), not 0" ;;
           esac ;;
    esac
    if [ -z "${why}" ]; then
        echo "ADM_OK ${inst} primary=${mp} worker=${mw} fallback=${fb} denied_in=${di:-0} denied_out=${dout:-0} mode=${nm:--}"
        return 0
    fi
    echo "ADM_BAD ${inst} ${why} [primary=${mp:--} worker=${mw:--} fallback=${fb:--} fallback_n=${fn:-0} mode=${nm:--}]"
    return 1
}

# _bench_adm_only_fallback <parsed-text> — 0 when the one defect is a non-zero fallback (both modes
# Closed, fallback series present). The node sets the mode gauge before the fallback gauge, so a
# node returning to Closed can be scraped for a moment with mode 2 and fallback 1.
_bench_adm_only_fallback() {
    local fb
    _bench_adm_closed "$(_bench_adm_kv mode_primary "$1")" && _bench_adm_closed "$(_bench_adm_kv mode_worker "$1")" || return 1
    case "$(_bench_adm_kv fallback_n "$1")" in ''|*[!0-9]*|0) return 1 ;; esac
    fb="$(_bench_adm_kv fallback "$1")"
    case "${fb}" in ''|-|0) return 1 ;; esac
    return 0
}

# bench_admission_gate — every node of INSTANCE_NAMES must be Closed (bench_admission_verdict). Per
# node: bench_admission_read (a failed session once more, BENCH_RO_RETRY_SECS later), parsed and
# judged; a node whose only defect is a non-zero fallback is read once more ~10 s later (the node
# sets the mode gauge before the fallback gauge, so a node returning to Closed can be scraped for a
# moment with mode 2 and fallback 1), then judged on that read. Prints every ADM_OK / ADM_BAD line
# (a node that could not be read: `ADM_BAD <inst> ssh failed (2 attempts) [...]`). Records
# manifest.admission[] = {inst, mode_primary, mode_worker, fallback (int|null), denied_in,
# denied_out (int), node_mode (str|null), ts}, one entry per node, replacing that node's earlier
# entry, and merges the readable node modes into manifest.fleet_modes. When BENCH_ADMISSION_DENIED_MAX
# is set (a whole number), every node read whose denied_in or denied_out is above it gets
#   ADM_WARN <inst> denied_in=<n> denied_out=<n> max=<max>
# and manifest.admission_denied_check = {max, over: [inst...], ts} records the check; it never fails
# the gate (a node redialling a peer that does not trust it is counted there, not refused). Then dies
# listing every node that is not Closed.
bench_admission_gate() {
    local i inst raw parsed line entries="" bad="" rc dmax="${BENCH_ADMISSION_DENIED_MAX:-}" di dout over=""
    case "${dmax}" in
        '') ;;
        *[!0-9]*) bench_warn "BENCH_ADMISSION_DENIED_MAX='${dmax}' is not a whole number — no denied-count check"; dmax="" ;;
        *) dmax="$((10#${dmax}))" ;;
    esac
    echo "    admission: every node Closed (primary and worker mode 2), fallback 0"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        rc=0; raw="$(_bench_ro_retry bench_admission_read "${i}")" || rc=$?
        if [ "${rc}" -ne 0 ]; then raw=""; fi
        parsed="$(printf '%s\n' "${raw}" | bench_admission_parse)"
        if [ "${rc}" -eq 0 ] && _bench_adm_only_fallback "${parsed}"; then
            echo "      ${inst}: fallback $(_bench_adm_kv fallback "${parsed}") with both modes Closed; reading again in 10 s"
            sleep 10
            rc=0; raw="$(_bench_ro_retry bench_admission_read "${i}")" || rc=$?
            if [ "${rc}" -ne 0 ]; then raw=""; fi
            parsed="$(printf '%s\n' "${raw}" | bench_admission_parse)"
        fi
        if [ "${rc}" -ne 0 ]; then
            line="ADM_BAD ${inst} ssh failed (2 attempts) [primary=- worker=- fallback=- fallback_n=0 mode=-]"
        else
            line="$(bench_admission_verdict "${inst}" "${parsed}")" || true
        fi
        printf '%s\n' "${line}"
        case "${line}" in ADM_OK\ *) ;; *) bad="${bad} ${inst}" ;; esac
        if [ -n "${dmax}" ] && [ "${rc}" -eq 0 ]; then
            di="$(_bench_adm_kv denied_in "${parsed}")"; dout="$(_bench_adm_kv denied_out "${parsed}")"
            case "${di:-0}${dout:-0}" in *[!0-9]*) di=0; dout=0 ;; esac
            if [ "${di:-0}" -gt "${dmax}" ] || [ "${dout:-0}" -gt "${dmax}" ]; then
                echo "ADM_WARN ${inst} denied_in=${di:-0} denied_out=${dout:-0} max=${dmax}"
                over="${over} ${inst}"
            fi
        fi
        entries="${entries}$(jq -cn --arg inst "${inst}" --arg ts "$(bench_now_iso)" \
            --arg mp "$(_bench_adm_kv mode_primary "${parsed}")" --arg mw "$(_bench_adm_kv mode_worker "${parsed}")" \
            --arg fb "$(_bench_adm_kv fallback "${parsed}")" --arg di "$(_bench_adm_kv denied_in "${parsed}")" \
            --arg dout "$(_bench_adm_kv denied_out "${parsed}")" --arg nm "$(_bench_adm_kv node_mode "${parsed}")" '
            def int_or_null: if . == "" or . == "-" then null else tonumber end;
            {inst: $inst, mode_primary: ($mp | int_or_null), mode_worker: ($mw | int_or_null),
             fallback: ($fb | int_or_null), denied_in: (($di | int_or_null) // 0),
             denied_out: (($dout | int_or_null) // 0),
             node_mode: (if $nm == "" or $nm == "-" then null else $nm end), ts: $ts}')"$'\n'
    done
    if ! printf '%s' "${entries}" | jq -s -e 'length > 0' >/dev/null 2>&1 \
        || ! bench_manifest_jq --argjson new "$(printf '%s' "${entries}" | jq -s -c .)" '
            ($new | map(.inst)) as $ni
            | .admission = ([(.admission // [])[] | select(if type == "object" then (.inst as $i | any($ni[]; . == $i) | not) else true end)] + $new)
            | .fleet_modes = (((.fleet_modes // {}) + ($new | map({key: .inst, value: .node_mode}) | from_entries))
                              | with_entries(select(.value | type == "string")))'; then
        bench_warn "admission: could not record admission[] / fleet_modes in $(bench_manifest)"
    fi
    if [ -n "${dmax}" ]; then
        # shellcheck disable=SC2086  # instance names, one word each
        if ! bench_manifest_jq --argjson max "${dmax}" --argjson over "$(printf '%s\n' ${over} | jq -R 'select(length > 0)' | jq -s -c .)" \
            --arg ts "$(bench_now_iso)" '.admission_denied_check = {max: $max, over: $over, ts: $ts}'; then
            bench_warn "admission: could not record admission_denied_check in $(bench_manifest)"
        fi
        if [ -n "${over}" ]; then
            bench_warn "admission: denied counts above ${dmax} on:${over} (ADM_WARN above; not fatal)"
        else
            echo "    ✓ admission: denied_in and denied_out at most ${dmax} on every node read"
        fi
    fi
    [ -z "${bad}" ] || bench_die "admission is not Closed on:${bad}"
    echo "    ✓ admission: all ${#INSTANCE_NAMES[@]} nodes Closed, fallback 0 (manifest.admission)"
}
