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
        --arg ep "${EPOCH_DURATION_SECS}" --arg di "${DOCKER_IMAGE}" --arg ti "${BENCH_TXGEN_IMAGE}" \
        --arg p "${PROJECT_ID}" --arg g "${BENCH_GRAFANA_URL}" --arg uid "${BENCH_PROM_DATASOURCE_UID}" \
        --arg nl "${BENCH_PROM_NETWORK_LABEL}" --arg now "$(bench_now_iso)" '
        {schema: "tn-bench-manifest/v1", run_id: $run, fleet: $fleet, machine_type: $mt,
         node_disk: {size_gb: ($ds|tonumber), type: $dt}, chain_id: ($cid|tonumber),
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
