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
# the common and tn-node-deployment submodules (null when not available).
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
    for f in ${BENCH_TXGEN_CONTRACT_FLAGS}; do
        printf '%s\n' "${help}" | grep -Eq -- "(^|[^a-z-])${f}([^a-z-]|$)" || missing="${missing} ${f}"
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
BENCH_NODE_FLAGS_NODE="--datadir --log.stdout.format --http --http.addr --ws --ws.addr --healthcheck --metrics"
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
        printf '%s\n' "${help}" | LC_ALL=C grep -Eq -- "(^|[^a-z.-])${re}([^a-z.-]|$)" || missing="${missing} ${f}"
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
                                 max_batch_delay_ms: ($batch | num_or_null)}'
}

# --- local results: results/<run>/ is the only copy ------------------------------------------
# Nothing is copied to a persistent bucket. The run bucket gs://tn-devnet-bench-<run> is only the
# blasters' upload transport: the teardown copies it into results/<run>/bucket/ and deletes it.
# So the teardown's local gate proves, before its first delete, that results/<run>/ holds every
# node's logs and the manifest, and leaves INDEX.md and CHECKSUMS.sha256 beside them. Back
# results/ up outside the repo: it is gitignored and on one disk.

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
        analysis/*) echo "06|analysis/*|other analysis output|bench_local_analysis" ;;
        metrics.json) echo "07|metrics.json|Cloud Monitoring + Prometheus series over the run window|deploy step 15 (tn-transaction-generator collect-gcp-metrics.py)" ;;
        pre-instances.json|pre-firewall.json) echo "08|pre-instances.json, pre-firewall.json|project snapshot before the run (the teardown compares the devnet rule to it)|benchmark-deploy.sh preflight" ;;
        deployments-bench.json) echo "09|deployments-bench.json|app contract addresses on the bench chain|deploy step 11" ;;
        tunnel.log|tunnel.pid) echo "10|tunnel.log, tunnel.pid|local IAP tunnel to the first node's RPC|bench_tunnel_up (deploy step 10)" ;;
        chaos-remote.log) echo "11|chaos-remote.log|output of the staged chaos sessions on the nodes|benchmark-blast.sh run (chaos)" ;;
        logs/*.pulled|logs/*.pulled-*) echo "12|logs/<node>.pulled*|pull markers: which instance id each node log came from|teardown log gate (bench_pull_node_logs)" ;;
        logs/*-recovery-*.tgz) echo "13|logs/<node>-recovery-<id>.*.tgz|service journal + sampler files of the node (recovery evidence)|teardown (recovery-lib.sh bench_pull_recovery_evidence)" ;;
        logs/*-telcoin-cert-fail-*.log.gz) echo "16|logs/<node>-telcoin-cert-fail-<UTC>.log.gz|container log of a validator below the certification threshold, saved when the outcome was recorded (listed in manifest.cert_failures[].logs; the local gate requires it)|bench_cert_failures_snapshot (collect, teardown before the local gate)" ;;
        logs/*-unit-stdout*.log.gz|logs/*-unit-stderr*.log.gz) echo "14|logs/<node>-unit-{stdout,stderr}.log.gz|the unit's append files /var/log/telcoin/telcoin{,-error}.log: every container run's output since setup|teardown log gate (bench_pull_node_logs)" ;;
        logs/*-telcoin.log.gz|logs/*-telcoin-[0-9]*Z.log.gz) echo "15|logs/<node>-telcoin.log.gz|the current container's log at the pull|teardown log gate (bench_pull_node_logs)" ;;
        logs/*.log.gz) echo "16|logs/<node>-<saved>.log.gz|container logs saved on the node before a restart, kill or pause (pre-step9, pre-kill, ...)|bench_save_node_log (deploy step 9, blast chaos); pulled by the teardown" ;;
        logs/deploy-*.log) echo "17|logs/deploy-*.log|benchmark-deploy.sh output, one file per invocation|benchmark-deploy.sh" ;;
        logs/blast-*.log) echo "18|logs/blast-<action>-*.log|benchmark-blast.sh output, one file per invocation|benchmark-blast.sh" ;;
        logs/create-*.log) echo "19|logs/create-<vm>.log|load VM create output (current blast index)|benchmark-blast.sh fund/run" ;;
        sampler/*.csv) echo "20|sampler/<node>.csv|node-sampler.sh rows every 30 s (memory, I/O, PSI, disk, block)|benchmark-blast.sh collect" ;;
        sampler/*.epochs.txt) echo "21|sampler/<node>.epochs.txt|epoch-file inventory of the node every minute|benchmark-blast.sh collect" ;;
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
        echo "Generated $(bench_now_iso). This directory is the only copy of the run: no bucket keeps"
        echo "another. Back it up outside the repo. \`CHECKSUMS.sha256\` holds the SHA-256 of every"
        echo "other file; check them with \`shasum -a 256 -c CHECKSUMS.sha256\` (Linux: \`sha256sum -c\`)"
        echo "from this directory."
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

# bench_local_analysis — results/<run>/analysis/cert-rate.md (tools/cert-rate.py over the pulled
# validator logs, windows from the manifest; only once the teardown has pulled them) and
# block-rate.md (tools/block-rate.py over the run dir). Informational: a tool that fails leaves a
# warning and no file, never a non-zero status. Dry run: prints the commands.
bench_local_analysis() {
    local d="${BENCH_RESULTS_DIR}" a="${BENCH_RESULTS_DIR}/analysis" t="${BENCH_DIR}/tools" name tmp err rc
    echo "    analysis -> ${a}/ (informational)"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "      + python3 ${t}/cert-rate.py --logs ${d}/logs --windows ${d}/manifest.json > ${a}/cert-rate.md"
        echo "      + python3 ${t}/block-rate.py --run ${d} > ${a}/block-rate.md"
        echo "      (dry run — not executed)"
        return 0
    fi
    command -v python3 >/dev/null 2>&1 || { bench_warn "python3 not on PATH — no analysis"; return 0; }
    mkdir -p "${a}" || { bench_warn "could not create ${a} — no analysis"; return 0; }
    for name in cert-rate block-rate; do
        if [ "${name}" = cert-rate ] && ! compgen -G "${d}/logs/bench-validator-*.log.gz" >/dev/null; then
            echo "      - cert-rate: no validator log in logs/ yet (the teardown pulls them)"
            continue
        fi
        tmp="$(mktemp "${a}/.${name}.md.XXXXXX")" || { bench_warn "${name}: no temp file"; continue; }
        rc=0
        if [ "${name}" = cert-rate ]; then
            err="$(python3 "${t}/cert-rate.py" --logs "${d}/logs" --windows "${d}/manifest.json" 2>&1 > "${tmp}")" || rc=$?
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
# --format json over the validator logs in <logs dir>, kept raw as analysis/certification.json beside
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
    local logs="${1:-}" mf="${2:-}" base a pct tmp err rc=0 present before after i p f
    base="$(dirname -- "${mf:-.}")"
    a="${base}/analysis"
    echo "    certification -> ${a}/certification.json and manifest.certification (informational)"
    if [ -z "${logs}" ] || [ -z "${mf}" ]; then
        bench_warn "bench_certification_record <logs dir> <manifest>: missing argument — not recorded"
        return 0
    fi
    pct="$(_bench_cert_fail_pct)"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "      + python3 ${BENCH_DIR}/tools/cert-rate.py --logs ${logs} --windows ${mf} --format json > ${a}/certification.json"
        echo "      + manifest.certification, .certification_meta and .cert_failures (below ${pct} % in a window with >= ${BENCH_CERT_MIN_PROPOSED} proposed)"
        echo "      (dry run — not executed)"
        return 0
    fi
    if ! compgen -G "${logs}/bench-validator-*.log.gz" >/dev/null; then
        bench_warn "certification: no validator log in ${logs} yet (the teardown pulls them) — not recorded"
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
    err="$(python3 "${BENCH_DIR}/tools/cert-rate.py" --logs "${logs}" --windows "${mf}" --format json 2>&1 > "${tmp}")" || rc=$?
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
# -telcoin-cert-fail-*.log.gz snapshot, -unit-stdout.log.gz and its stamped copies. Non-empty only.
_bench_cert_logs_here() {
    local f n s='[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z'
    for f in "$1/$2"-*.log.gz; do
        [ -f "${f}" ] && [ -s "${f}" ] || continue
        n="${f##*/}"
        _bench_log_name_ok "${n}" || continue
        # shellcheck disable=SC2254  # ${s} is a glob on purpose
        case "${n#"$2"-}" in
            telcoin.log.gz|telcoin-cert-fail-*.log.gz|unit-stdout.log.gz|telcoin-${s}.log.gz|unit-stdout-${s}.log.gz) printf '%s\n' "${f}" ;;
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
# here), and every certification log of the instance on disk (_bench_cert_logs_here). An instance
# already gone (a teardown after an abort), outside the fleet, or whose save failed gets its logs on
# disk and a manifest note. One line per instance. Returns 0 whatever happens: the local gate decides.
# Dry run: says what it would do.
bench_cert_failures_snapshot() {
    local logs="${1:-}" mf="${2:-}" base insts inst idx zone rc err out name snap why f add n
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
            rc=0
            err="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "${inst}" --zone="${zone}" \
                --project="${PROJECT_ID}" --format=json </dev/null 2>&1 >/dev/null)" || rc=$?
            if [ "${rc}" -ne 0 ] && printf '%s\n' "${err}" | grep -qi 'not found'; then
                why="instance gone"
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
        if [ -n "${why}" ]; then
            echo "      ⚠ ${inst}: ${why} — no snapshot; ${n} log(s) on disk listed in cert_failures[].logs"
            _bench_cert_jq "${mf}" --arg n "certification: ${inst}: ${why} at $(bench_now_iso) — no cert-fail snapshot; cert_failures[].logs lists the ${n} log(s) on disk" \
                '.notes = ((.notes // []) + [$n])' || true
        elif [ -s "${snap}" ]; then
            echo "      ✓ ${inst}: snapshot $(_bench_cert_rel "${base}" "${snap}"); ${n} log(s) listed in cert_failures[].logs"
        else
            echo "      ✗ ${inst}: snapshot $(_bench_cert_rel "${base}" "${snap}") is on the node only; listed with ${n} log(s), so the local gate refuses until it is here"
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

# bench_obs_mem_pct — obs-devnet memory used % from the Ops Agent (empty if unavailable).
bench_obs_mem_pct() {
    local id
    id="$(gcloud compute instances describe "${OBS_INSTANCE_NAME}" --zone="${OBS_ZONE}" --project="${PROJECT_ID}" --format='value(id)' 2>/dev/null)" || true
    [ -n "${id}" ] || return 0
    bench_monitoring_max "metric.type=\"agent.googleapis.com/memory/percent_used\" AND metric.labels.state=\"used\" AND resource.labels.instance_id=\"${id}\""
}
