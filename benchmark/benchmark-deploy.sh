#!/usr/bin/env bash
#
# benchmark-deploy.sh — stand up the throwaway benchmark fleet (10 validators + 1 observer,
# chain 32286, 20-min epochs) in tn-devnet, blast it from per-zone COS VMs, collect the
# evidence, and optionally tear it all down. The live devnet is never touched: no devnet
# instance, tag, rule, DNS name, LB or obs setting is created, modified or deleted.
#
# Dry run by default: without --yes it prints this run's full step plan (with the concrete
# commands) after local-only checks, and exits 0 without a single GCP call. With --yes it
# executes the steps; every gcloud mutation prints its argv first, and everything the script
# prints is also copied to results/<run>/logs/deploy-<UTC stamp>.log (a new file per invocation).
#
#    -  gate (--yes)     before ANY step: the node image probe when steps 0/5/6/7 are selected and the
#                        run has not pinned an image yet (bench-lib bench_node_image_probe: digest,
#                        telcoin -V sha, CLI flags, node-image-contract.txt strings, the EXPECT_* env);
#                        from then on every step and sub-script runs <repo>@sha256:<digest>
#                        (BENCH_DOCKER_IMAGE); manifest.json gets the probe, and consensus_parameters
#                        when step 7 (which stages PARAMETERS_FILE) is selected. Refuses sub-second
#                        delays (max_header_delay < 1000 ms) on a build not subsecond-from-genesis.
#                        Also the pinned :blast-v2-<sha> image, cloudbuild.yaml, config.bench.toml and
#                        deployments-bench.json that the selected steps need
#    0  preflight        auth + tools + no leftover bench-*/benchmark=1 resources + accounts file +
#                        empty benchmark/genesis + firewall/tag hygiene + obs-devnet disk < 70% +
#                        MACHINE_TYPE in every fleet zone and the first blaster type in every validator
#                        zone + a hyperdisk-* disk type offered in every fleet zone + quota headroom per
#                        region (vCPUs per family metric, addresses, disk); one die lists every failure;
#                        pre-snapshots
#    1  image            :blast-v2-<sha> exists, else Cloud Build builds it (synchronous);
#                        `IMAGE blast --help` must carry every contract flag (when docker exists)
#    2  instances        common/create-instances.sh on the bench profile; assert tag bench-node +
#                        label benchmark=1 on every node; label boot disks; manifest.instances[]
#    3  bootstrap        serial-console marker "devnet-startup.sh complete" on every node
#    4  firewall         benchmark-firewall.sh apply --yes
#    5  keygen           ../devnet-keygen.sh           (bench profile via CONFIG_FILE)
#    6  genesis          ../devnet-genesis-build.sh    (workspace benchmark/, chain 32286)
#    7  finalize         ../devnet-finalize.sh
#    8  observability    per node, ONE IAP session: setup-observability.sh --enable-metrics aimed at
#                        a black-hole URL, then (same session) stop Alloy, wipe its WAL, set
#                        TN_CHAIN=bench TN_NODE=<instance> + the real obs-devnet URL, start Alloy —
#                        no sample labelled network="devnet" ever leaves a bench node. Never
#                        create-obs-instance.sh, never devnet-observability.sh.
#    9  post-config      per node, ONE IAP session each, serially: reth --http.addr 0.0.0.0,
#                        assert the bench Alloy labels, restart (<=1 down at a time), wait for
#                        eth_chainId on the internal IP + consensus progressing (blocks rose, or
#                        subdag committed/quorum reached in its log — an idle chain stays at
#                        block 0), check its boot lines (git sha, max/min header + max batch delay,
#                        fork schedule) against manifest.json -> manifest.node_startup, install node-sampler
#   10  health gate      wait_healthy x11, IAP tunnel -> cast chain-id == 32286, Prometheus
#                        min by (node)(tn_primary_round{network="bench"}) rising on all 11,
#                        Prometheus: count(count by (node)(tn_engine_canonical_height{network="bench"})) == 11
#                        and no bench node has any series labelled network="devnet";
#                        recovery-schedule.py: registry epoch duration == EPOCH_DURATION_SECS -> manifest.registry_probe
#   11  contracts        (--with-contracts) tn-contracts worktree bench/<run> -> devnet-contracts.sh
#   12  IAM + bucket     secretAccessor on the bench secrets for the compute SA; gs://<bucket>
#   13  fund             benchmark-blast.sh fund --yes
#   14  blast            benchmark-blast.sh run --yes
#   15  collect          benchmark-blast.sh collect --yes + tn-transaction-generator/bench/collect-gcp-metrics.py
#   16  teardown         (--with-teardown) benchmark-teardown.sh --yes
#
# Usage:
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh                 # plan only
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --yes --with-contracts
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 9          # resume
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --only 15         # one step
#   benchmark/benchmark-deploy.sh --probe-node-image [REF]   # the gate's node image probe alone (local,
#       no run dir, no manifest; REF defaults to the configured image; with --yes a local image is
#       refused unless its repo digest is the registry's, exactly as at the gate). Expectations:
#       BENCH_DOCKER_IMAGE_EXPECT_DIGEST=sha256:<hex> BENCH_NODE_EXPECT_SHA=<7-40 hex>
#       BENCH_NODE_EXPECT_FORKS=subsecond-from-genesis|adiri-schedule|pre-subsecond
#   A resumed run (--run) keeps the node image its gate pinned (manifest node_image_pinned); a
#   BENCH_DOCKER_IMAGE naming any other image is refused.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

LAST_STEP=16
CONFIRM=0; FROM=0; ONLY=""; WITH_CONTRACTS=0; WITH_TEARDOWN=0; PRINT_POSTCONFIG=""; PRINT_OBS=""
PROBE_ONLY=0; PROBE_REF=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --from) FROM="${2:?--from needs a step number}"; shift ;;
        --from=*) FROM="${1#*=}" ;;
        --only) ONLY="${2:?--only needs a step number}"; shift ;;
        --only=*) ONLY="${1#*=}" ;;
        --with-contracts) WITH_CONTRACTS=1 ;;
        --with-teardown) WITH_TEARDOWN=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}" ;;
        --print-postconfig) PRINT_POSTCONFIG="${2:?--print-postconfig needs an instance}"; shift ;;  # review aid: print step 9's remote script
        --print-obs-script) PRINT_OBS="${2:?--print-obs-script needs an instance}"; shift ;;       # review aid: step 8's script, placeholder token
        --probe-node-image) PROBE_ONLY=1; case "${2:-}" in ''|-*) ;; *) PROBE_REF="$2"; shift ;; esac ;;
        --probe-node-image=*) PROBE_ONLY=1; PROBE_REF="${1#*=}" ;;
        -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --from N, --only N, --with-contracts, --with-teardown, --run ID, --probe-node-image [REF])" >&2; exit 1 ;;
    esac
    shift
done
is_step() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 0 ] && [ "$1" -le "${LAST_STEP}" ]; }
is_step "${FROM}" || { echo "❌ --from must be 0..${LAST_STEP}" >&2; exit 1; }
[ -z "${ONLY}" ] || is_step "${ONLY}" || { echo "❌ --only must be 0..${LAST_STEP}" >&2; exit 1; }
[ "${PROBE_ONLY}" -eq 0 ] || [ -n "${BENCH_RUN_ID:-}" ] || BENCH_RUN_ID="r00000000-0000"   # config.sh needs one
export BENCH_RUN_ID="${BENCH_RUN_ID:-}"
# A resumed run keeps the image step 1 verified (the generator checkout may have moved on).
if [ -z "${BENCH_TXGEN_SHA:-}" ] && [ -n "${BENCH_RUN_ID}" ] && [ -f "${DIR}/results/${BENCH_RUN_ID}/manifest.json" ]; then
    BENCH_TXGEN_SHA="$(jq -r '.txgen_git_sha // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    export BENCH_TXGEN_SHA
fi
# A resumed run keeps the node image its gate pinned (the tag may have moved since). An operator
# BENCH_DOCKER_IMAGE naming any other image is refused: a run never silently switches image.
NODE_PIN_FROM_MANIFEST=0
if [ "${PROBE_ONLY}" -eq 0 ] && [ -n "${BENCH_RUN_ID}" ] && [ -f "${DIR}/results/${BENCH_RUN_ID}/manifest.json" ]; then
    _pin="$(jq -r '.node_image_pinned // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    _ref="$(jq -r '.node_image_ref // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    if [ -n "${_pin}" ]; then
        if [ -n "${BENCH_DOCKER_IMAGE:-}" ] && [ "${BENCH_DOCKER_IMAGE}" != "${_pin}" ] && [ "${BENCH_DOCKER_IMAGE}" != "${_ref}" ]; then
            echo "❌ run ${BENCH_RUN_ID} is pinned to node image ${_pin} (probed from ${_ref:-?})," >&2
            echo "   but BENCH_DOCKER_IMAGE=${BENCH_DOCKER_IMAGE} names another image. A resumed run never" >&2
            echo "   switches image: unset BENCH_DOCKER_IMAGE (or set it to either ref above), or start a new run." >&2
            exit 1
        fi
        export BENCH_DOCKER_IMAGE="${_pin}"
        NODE_PIN_FROM_MANIFEST=1
    fi
    unset _pin _ref
fi
# shellcheck disable=SC2034  # read by bench-lib.sh (bench_run, manifest writers)
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"   # exports CONFIG_FILE=benchmark/config.sh for every sub-script

# --probe-node-image [REF]: the gate's node image probe alone — local, no run directory, no manifest.
if [ "${PROBE_ONLY}" -eq 1 ]; then
    bench_node_image_probe "${PROBE_REF:-${DOCKER_IMAGE}}"
    echo "pinned=${BENCH_NODE_IMAGE_PINNED} sha=${BENCH_NODE_GIT_SHA} forks=${BENCH_NODE_FORK_SCHEDULE}"
    exit 0
fi

BOOTSTRAP_TIMEOUT_SECS=600
BOOTSTRAP_POLL_SECS=15
CHAIN_ID_HEX="$(printf '0x%x' "${CHAIN_ID}")"
PROM_COUNT_QUERY="count(count by (node) (tn_engine_canonical_height{network=\"${BENCH_PROM_NETWORK_LABEL}\"}))"
PROM_LEAK_QUERY='count(count by (node) (tn_engine_canonical_height{network="devnet", node=~"bench.*"}))'
PROM_LEAK_ANY_QUERY='count(count by (node) ({network="devnet", node=~"bench.*"}))'
COLLECT_METRICS_PY="${BENCH_TXGEN_BENCH_DIR}/collect-gcp-metrics.py"
DEVNET_TXGEN_MASTER="0x46c26b4fafffaab86437b11f5cdbd1b9f7ddc844"

# run_expect <sha|forks|mhd|nhd|mbd|vt|thr> [<node-index>] — what this run's nodes must report at
# boot: the manifest (node_git_sha, node_fork_schedule, consensus_parameters.*_ms, as the gate
# recorded them) first, else this shell's node image probe / PARAMETERS_FILE. "" when neither has it.
# With a node index, that node's BENCH_NODE_PARAM_OVERRIDES value of the key wins (step 9 writes it,
# from this shell's knob, which the gate records as consensus_parameters.overrides). vt (vote_timeout)
# is only ever an override: the fleet file need not set it and older builds do not log it.
run_expect() {
    local m v="" q="" g="" key="" ov=""
    m="$(bench_manifest)"
    case "$1" in
        sha)   q='.node_git_sha';                              g="${BENCH_NODE_GIT_SHA:-}" ;;
        forks) q='.node_fork_schedule';                        g="${BENCH_NODE_FORK_SCHEDULE:-}" ;;
        mhd)   q='.consensus_parameters.max_header_delay_ms';  g="$(bench_params_ms "${PARAMETERS_FILE}" max_header_delay)"; key=max_header_delay ;;
        nhd)   q='.consensus_parameters.min_header_delay_ms';  g="$(bench_params_ms "${PARAMETERS_FILE}" min_header_delay)"; key=min_header_delay ;;
        mbd)   q='.consensus_parameters.max_batch_delay_ms';   g="$(bench_params_ms "${PARAMETERS_FILE}" max_batch_delay)"; key=max_batch_delay ;;
        vt)    key=vote_timeout ;;
        thr)   g="$(bench_params_raw "${PARAMETERS_FILE}" header_num_of_batches_threshold)"; key=header_num_of_batches_threshold ;;
        *) return 1 ;;
    esac
    [ -z "${2:-}" ] || [ -z "${key}" ] || ov="$(bench_node_override "$2" "${key}")"
    if [ -n "${ov}" ]; then
        case "${key}" in header_num_of_batches_threshold) printf '%s' "${ov}" ;; *) bench_dur_ms "${ov}" | tr -d '\n' ;; esac
        return 0
    fi
    [ -z "${q}" ] || [ ! -f "${m}" ] || v="$(jq -r "${q} // empty" "${m}" 2>/dev/null || true)"
    printf '%s' "${v:-${g}}"
}

# disk_desc — "<size> GB <type>", plus the provisioned IOPS/throughput when set (hyperdisk only).
disk_desc() {
    local p="${NODE_DISK_IOPS:+${NODE_DISK_IOPS} IOPS}"
    [ -z "${NODE_DISK_THROUGHPUT}" ] || p="${p:+${p}, }${NODE_DISK_THROUGHPUT} MiB/s"
    printf '%s GB %s%s' "${NODE_DISK_SIZE}" "${NODE_DISK_TYPE}" "${p:+ (provisioned ${p})}"
}

# fleet_zones — the distinct zones of the whole fleet, space-separated, sorted.
fleet_zones() {
    local z; z="$(printf '%s\n' "${ZONES[@]}" | sort -u | tr '\n' ' ')"
    printf '%s' "${z% }"
}

# validator_zones — the distinct zones of the validators (each validator's blaster runs in its zone).
validator_zones() {
    local i z
    z="$(for i in "${!ZONES[@]}"; do [ "${NODE_ROLES[$i]}" != "validator" ] || echo "${ZONES[$i]}"; done | sort -u | tr '\n' ' ')"
    printf '%s' "${z% }"
}

# fleet_regions — the distinct regions of the fleet, space-separated, sorted.
fleet_regions() {
    local z r; r="$(for z in "${ZONES[@]}"; do tn_region_from_zone "${z}"; echo; done | sort -u | tr '\n' ' ')"
    printf '%s' "${r% }"
}

# disk_type_check — a hyperdisk-* boot disk type must be offered in every zone the fleet uses;
# dies naming the zones that lack it. The query goes through bench_run, so a dry run (the plan)
# prints it and nothing else. Other disk types: no-op.
disk_type_check() {
    case "${NODE_DISK_TYPE}" in hyperdisk-*) ;; *) return 0 ;; esac
    local zlist out have z lacking=""
    zlist="$(fleet_zones)"
    echo "    ${NODE_DISK_TYPE} must be offered in every fleet zone (${zlist})"
    out="$(bench_run perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disk-types list --project="${PROJECT_ID}" \
        --filter="name=${NODE_DISK_TYPE} AND zone:(${zlist})" --format='value(zone.basename())' </dev/null)" \
        || bench_die "gcloud compute disk-types list failed (or gave no answer within 120 s)"
    printf '%s\n' "${out}" | grep '^ ' || true    # bench_run's argv line (and its dry-run note)
    [ "${BENCH_APPLY}" = "1" ] || return 0
    have=" $(printf '%s\n' "${out}" | { grep -v '^ ' || true; } | tr '\n' ' ')"
    for z in ${zlist}; do
        case "${have}" in *" ${z} "*) ;; *) lacking="${lacking} ${z}" ;; esac
    done
    [ -z "${lacking}" ] || bench_die "${NODE_DISK_TYPE} is not offered in:${lacking} — pick another BENCH_NODE_DISK_TYPE"
    echo "    ✓ ${NODE_DISK_TYPE} offered in all fleet zones"
}

# machine_type_check <machine-type> <knob> "<zone...>" — the type must exist in every listed zone: a
# zone without it fails the create part-way through the fleet (or the blast, an hour after the fleet
# came up). One describe per zone, each under an alarm; every zone that fails is listed in a single
# die. A dry run (the plan) prints the query and calls nothing.
machine_type_check() {
    local t="$1" knob="$2" zones="$3" z rc out bad="" n=0
    echo "    ${t} must exist in every zone it is created in (${zones})"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe ${t} --zone=<each zone> --project=${PROJECT_ID} --format='value(name)'"
        echo "      (dry run — not executed)"
        return 0
    fi
    for z in ${zones}; do
        rc=0; n=$((n + 1))
        out="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe "${t}" --zone="${z}" \
            --project="${PROJECT_ID}" --format='value(name)' </dev/null 2>&1)" || rc=$?
        [ "${rc}" -ne 0 ] || continue
        case "${rc}:${out}" in
            142:*) out="no answer within 60 s" ;;
            *"was not found"*) out="not offered in this zone" ;;
            *) out="describe failed (rc ${rc}): $(printf '%s' "${out}" | tr -s '\n' ' ' | cut -c1-200)" ;;
        esac
        bad="${bad}
     ${z}: ${out}"
    done
    [ -z "${bad}" ] || bench_die "${t} cannot be created in every zone it needs — change ZONES (benchmark/config.sh) or ${knob}:${bad}"
    echo "    ✓ ${t} offered in all ${n} zones"
}

# machine_vcpus <machine-type> <zone> — its vCPU count: from the name when the name carries it
# (<family>-custom-<vcpus>-<mb>, <family>-<class>-<vcpus>), else (--yes only) from an alarmed
# describe in <zone>; "" when unknown.
machine_vcpus() {
    local n
    case "$1" in *-custom-*) n="${1#*-custom-}"; n="${n%%-*}" ;; *) n="${1##*-}" ;; esac
    case "${n}" in ''|*[!0-9]*) n="" ;; esac
    if [ -z "${n}" ] && [ "${BENCH_APPLY}" = "1" ]; then
        n="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe "$1" --zone="$2" \
            --project="${PROJECT_ID}" --format='value(guestCpus)' </dev/null 2>/dev/null || true)"
    fi
    printf '%s' "${n}"
}

# region_needs <region> — "<quota metric> <need>" lines: what the fleet's nodes in <region> and their
# blasters (one per validator, in its zone, on the first BENCH_BLASTER_MACHINE_TYPES type) take from
# the region's quotas. vCPUs count against each type's family metric (bench_cpu_quota_metric), one sum
# when nodes and blasters share it; every node and blaster holds one external address; the blasters'
# pd-balanced boot disks count against SSD_TOTAL_GB; the node disks against HDB_TOTAL_{GB,IOPS,
# THROUGHPUT} (hyperdisk-balanced; the IOPS/throughput only when provisioned), SSD_TOTAL_GB (pd-ssd,
# pd-balanced) or DISKS_TOTAL_GB (pd-standard). A need is "?" when a vCPU count is unknown.
region_needs() {
    local region="$1" i z="" nodes=0 vals=0 bt nc bc
    for i in "${!ZONES[@]}"; do
        [ "$(tn_region_from_zone "${ZONES[$i]}")" = "${region}" ] || continue
        z="${ZONES[$i]}"; nodes=$((nodes + 1))
        [ "${NODE_ROLES[$i]}" != "validator" ] || vals=$((vals + 1))
    done
    bt="${BENCH_BLASTER_MACHINE_TYPES%% *}"
    nc="$(machine_vcpus "${MACHINE_TYPE}" "${z}")"; nc="${nc:+$(( nodes * nc ))}"
    bc="$(machine_vcpus "${bt}" "${z}")"; bc="${bc:+$(( vals * bc ))}"
    {
        echo "$(bench_cpu_quota_metric "${MACHINE_TYPE}") ${nc:-?}"
        [ "${vals}" -eq 0 ] || echo "$(bench_cpu_quota_metric "${bt}") ${bc:-?}"
        echo "IN_USE_ADDRESSES $(( nodes + vals ))"
        case "${NODE_DISK_TYPE}" in
            hyperdisk-balanced)
                echo "HDB_TOTAL_GB $(( nodes * NODE_DISK_SIZE ))"
                [ -z "${NODE_DISK_IOPS}" ] || echo "HDB_TOTAL_IOPS $(( nodes * NODE_DISK_IOPS ))"
                [ -z "${NODE_DISK_THROUGHPUT}" ] || echo "HDB_TOTAL_THROUGHPUT $(( nodes * NODE_DISK_THROUGHPUT ))" ;;
            pd-ssd|pd-balanced) echo "SSD_TOTAL_GB $(( nodes * NODE_DISK_SIZE ))" ;;
            pd-standard) echo "DISKS_TOTAL_GB $(( nodes * NODE_DISK_SIZE ))" ;;
        esac
        [ "${vals}" -eq 0 ] || echo "SSD_TOTAL_GB $(( vals * BENCH_BLASTER_BOOT_DISK_GB ))"
    } | awk '{ if (!($1 in n)) { o[++k] = $1; n[$1] = 0 } if ($2 == "?") u[$1] = 1; else n[$1] += $2 }
             END { for (i = 1; i <= k; i++) print o[i], ((o[i] in u) ? "?" : n[o[i]]) }'
}

# hdb_headroom <metric> <region> <quota-info json> <disks json> — a HDB_TOTAL_* quota's headroom in
# <region>: the value in force (`gcloud beta quotas info describe` JSON: the region's own dimension,
# else the default that applies to it) less what the region's hyperdisk-balanced disks already hold.
# "unlimited" for -1; "" when the region has no value.
hdb_headroom() {
    local f limit used
    case "$1" in
        HDB_TOTAL_GB) f=sizeGb ;;
        HDB_TOTAL_IOPS) f=provisionedIops ;;
        *) f=provisionedThroughput ;;
    esac
    limit="$(printf '%s' "$3" | jq -r --arg r "$2" '
        ([.dimensionsInfos[]? | select(.dimensions.region? == $r)]
         + [.dimensionsInfos[]? | select((.dimensions.region? // null) == null and ((.applicableLocations // []) | index($r)))])
        | .[0].details.value // empty' 2>/dev/null || true)"
    case "${limit}" in
        -1) echo unlimited; return 0 ;;
        ''|*[!0-9]*) return 0 ;;
    esac
    used="$(printf '%s' "$4" | jq -r --arg r "$2" --arg f "${f}" '
        [.[]? | select((.type // "") | endswith("/hyperdisk-balanced"))
              | select(((.zone // .region // "") | split("/") | last | sub("-[a-z]$"; "")) == $r)
              | (.[$f] // "0" | tonumber)] | add // 0 | floor' 2>/dev/null || true)"
    echo $(( limit - ${used:-0} ))
}

# quota_check — per region, the fleet's need (region_needs) against the headroom (limit - usage).
# CPU family metrics, IN_USE_ADDRESSES and SSD_TOTAL_GB/DISKS_TOTAL_GB come from `gcloud compute
# regions describe`, which lists no hyperdisk quota: the HDB_TOTAL_* limits come from the Cloud
# Quotas API (HDB-TOTAL-{GB,IOPS,THROUGHPUT}-per-project-region) and their usage from the disks
# list. Every shortfall is listed in one die; a quota that cannot be read is a warning. Every gcloud
# call is under an alarm. A dry run (the plan) prints the needs and the queries and calls nothing.
quota_check() {
    local regions r m need have json qgb="" qiops="" qtput="" disks="[]" q qj ok short=""
    regions="$(fleet_regions)"
    echo "    quota headroom (limit - usage) in each region must cover its nodes plus one blaster per validator:"
    for r in ${regions}; do
        echo "      ${r}: $(region_needs "${r}" | awk '{ printf "%s%s %s", (NR > 1 ? ", " : ""), $1, $2 }')"
    done
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute regions describe <each region> --project=${PROJECT_ID} --format=json"
        if [ "${NODE_DISK_TYPE}" = "hyperdisk-balanced" ]; then
            echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud beta quotas info describe HDB-TOTAL-<GB|IOPS|THROUGHPUT>-per-project-region --service=compute.googleapis.com --project=${PROJECT_ID} --format=json"
            echo "    + perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disks list --project=${PROJECT_ID} --format=json"
        fi
        echo "      (dry run — not executed)"
        return 0
    fi
    if [ "${NODE_DISK_TYPE}" = "hyperdisk-balanced" ]; then
        for q in GB IOPS THROUGHPUT; do
            qj="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud beta quotas info describe "HDB-TOTAL-${q}-per-project-region" \
                --service=compute.googleapis.com --project="${PROJECT_ID}" --format=json </dev/null 2>/dev/null)" || qj=""
            case "${q}" in GB) qgb="${qj}" ;; IOPS) qiops="${qj}" ;; *) qtput="${qj}" ;; esac
        done
        disks="$(perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disks list --project="${PROJECT_ID}" \
            --format=json </dev/null 2>/dev/null)" \
            || { bench_warn "gcloud compute disks list failed — existing hyperdisk usage counted as 0"; disks="[]"; }
    fi
    for r in ${regions}; do
        json="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute regions describe "${r}" --project="${PROJECT_ID}" \
            --format=json </dev/null 2>/dev/null)" \
            || bench_die "gcloud compute regions describe ${r} failed (or gave no answer within 60 s)"
        ok=""
        while read -r m need; do
            [ -n "${m}" ] || continue
            case "${m}" in
                HDB_TOTAL_GB) have="$(hdb_headroom "${m}" "${r}" "${qgb}" "${disks}")" ;;
                HDB_TOTAL_IOPS) have="$(hdb_headroom "${m}" "${r}" "${qiops}" "${disks}")" ;;
                HDB_TOTAL_THROUGHPUT) have="$(hdb_headroom "${m}" "${r}" "${qtput}" "${disks}")" ;;
                *) have="$(printf '%s' "${json}" | jq -r --arg q "${m}" \
                       '[.quotas[]? | select(.metric == $q) | (.limit - .usage) | floor][0] // empty' 2>/dev/null || true)" ;;
            esac
            if [ -z "${have}" ] || [ "${need}" = "?" ]; then
                bench_warn "${r}: ${m} not checked (need ${need}, headroom ${have:-not readable})"
            elif [ "${have}" = "unlimited" ] || [ "${have}" -ge "${need}" ]; then
                ok="${ok}, ${m} ${need}/${have}"
            else
                short="${short}
     $(printf '%-24s %-22s %10s %10s' "${r}" "${m}" "${need}" "${have}")"
            fi
        done <<EOF
$(region_needs "${r}")
EOF
        [ -z "${ok}" ] || echo "    ✓ ${r} need/headroom: ${ok#, }"
    done
    [ -z "${short}" ] || bench_die "quota shortfalls — nothing was created:
     $(printf '%-24s %-22s %10s %10s' region metric need headroom)${short}
   Raise the quota (console: IAM & Admin > Quotas; or gcloud beta quotas preferences create), or move the zone (ZONES in benchmark/config.sh)."
}

# ================================ steps ==============================================
step_0() {
    echo ">>> Step 0: preflight"
    echo "    fleet: ${#INSTANCE_NAMES[@]} x ${MACHINE_TYPE}, $(disk_desc), node image ${DOCKER_IMAGE} (git $(run_expect sha), forks $(run_expect forks); image probed at gate)"
    bench_require_tools gcloud cast jq python3 curl docker git openssl || bench_die "missing tools"
    [ "${WITH_CONTRACTS}" -eq 0 ] || bench_require_tools forge || bench_die "forge needed for --with-contracts"
    local acct; acct="$(gcloud config get-value account 2>/dev/null || true)"
    gcloud auth print-access-token >/dev/null || bench_die "gcloud auth failed — gcloud auth login"
    echo "    ✓ gcloud auth (${acct:-unknown account})"
    local left; left="$(bench_leftovers)"
    if [ -n "${left}" ]; then
        printf '%s\n' "${left}" | sed 's/^/    ✗ exists: /' >&2
        bench_die "benchmark resources from an earlier run still exist — tear them down first:
     benchmark/benchmark-teardown.sh            # dry run, then add --yes
   (or resume the run that owns them with --from N instead of starting at step 0)"
    fi
    echo "    ✓ no bench-* / benchmark=1 instance, disk, firewall rule or bucket exists"
    local accounts="${GENESIS_WORKSPACE}/testnet_accounts.yaml"
    grep -qi "${BENCH_TXGEN_MASTER_ADDRESS}" "${accounts}" || bench_die "${accounts} does not fund the bench txgen master ${BENCH_TXGEN_MASTER_ADDRESS}"
    ! grep -qi "${DEVNET_TXGEN_MASTER}" "${accounts}" || bench_die "${accounts} still funds the DEVNET txgen master"
    echo "    ✓ ${accounts} funds ${BENCH_TXGEN_MASTER_ADDRESS}"
    if [ -d "${BENCH_DIR}/genesis" ] && [ -n "$(ls -A "${BENCH_DIR}/genesis" 2>/dev/null)" ]; then
        bench_die "${BENCH_DIR}/genesis is not empty (a previous run's keys?) — benchmark-teardown.sh moves it into results/<run>/"
    fi
    echo "    ✓ benchmark/genesis empty"
    if [ ! -s "${TN_BLS_PASSPHRASE_FILE}" ]; then
        echo "    creating bench BLS passphrase ${TN_BLS_PASSPHRASE_FILE} (gitignored, mode 600, never printed)"
        ( umask 077; mkdir -p "$(dirname "${TN_BLS_PASSPHRASE_FILE}")"; openssl rand -hex 24 | tr -d '\n' > "${TN_BLS_PASSPHRASE_FILE}" )
    fi
    echo "    ✓ bench BLS passphrase present"
    local foreign
    foreign="$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json | jq -r \
        --argjson ours "$(printf '%s\n' "${BENCH_FIREWALL_RULES[@]}" | jq -R . | jq -s .)" \
        '.[] | select((.targetTags // []) | index("bench-node")) | select(.name as $n | $ours | index($n) | not) | .name')"
    [ -z "${foreign}" ] || bench_die "non-bench firewall rules target bench-node: ${foreign}"
    echo "    ✓ no non-bench firewall rule targets bench-node"
    local obs_pct
    obs_pct="$(tn_iap_ssh "${OBS_INSTANCE_NAME}" "${OBS_ZONE}" "df --output=pcent /mnt/obs-data | tail -1" 2>/dev/null | tr -dc '0-9' || true)"
    [ -n "${obs_pct}" ] || bench_die "could not read obs-devnet /mnt/obs-data usage over IAP"
    # Bench nodes ship metrics only (a few hundred MB per run into Prometheus); the guard exists
    # so a Loki disk that is already nearly full is fixed before, not during, a run.
    [ "${obs_pct}" -lt "${BENCH_OBS_DISK_MAX_PCT:-70}" ] || bench_die "obs-devnet data disk is ${obs_pct}% (>= ${BENCH_OBS_DISK_MAX_PCT:-70}%) — fix obs-devnet's disk first, or raise BENCH_OBS_DISK_MAX_PCT after checking Loki's growth rate"
    echo "    ✓ obs-devnet /mnt/obs-data ${obs_pct}%"
    machine_type_check "${MACHINE_TYPE}" BENCH_MACHINE_TYPE "$(fleet_zones)"
    machine_type_check "${BENCH_BLASTER_MACHINE_TYPES%% *}" BENCH_BLASTER_MACHINE_TYPES "$(validator_zones)"
    disk_type_check
    quota_check
    mkdir -p "${BENCH_RESULTS_DIR}"
    [ -f "${BENCH_RESULTS_DIR}/pre-instances.json" ] \
        || gcloud compute instances list --project="${PROJECT_ID}" --format=json > "${BENCH_RESULTS_DIR}/pre-instances.json"
    [ -f "${BENCH_RESULTS_DIR}/pre-firewall.json" ] \
        || gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json > "${BENCH_RESULTS_DIR}/pre-firewall.json"
    echo "    ✓ pre-snapshots in ${BENCH_RESULTS_DIR}/pre-{instances,firewall}.json"
    bench_manifest_init
}

step_1() {
    bench_require_txgen_image
    local digest tag="${BENCH_TXGEN_IMAGE##*:}" sha
    sha="${tag#blast-v2-}"
    echo ">>> Step 1: txgen image ${BENCH_TXGEN_IMAGE}"
    digest="$(bench_txgen_image_digest)"
    if [ -z "${digest}" ]; then
        # Build only what the tag claims: HEAD of a clean generator checkout.
        [ -z "${BENCH_TXGEN_IMAGE_ERROR}" ] || bench_die "cannot build: ${BENCH_TXGEN_IMAGE_ERROR}"
        [ "$(git -C "${BENCH_TXGEN_REPO}" rev-parse --short=7 HEAD)" = "${sha}" ] \
            || bench_die "tag ${tag} is not HEAD of ${BENCH_TXGEN_REPO} — check out ${sha} or unset BENCH_TXGEN_SHA/BENCH_TXGEN_IMAGE"
        [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] || bench_die "missing ${BENCH_TXGEN_CLOUDBUILD}"
        echo "    not in the registry — building it with Cloud Build (synchronous)"
        bench_run gcloud builds submit --project="${PROJECT_ID}" --config="${BENCH_TXGEN_CLOUDBUILD}" \
            --substitutions="_IMAGE=${BENCH_TXGEN_IMAGE%:*},_TAG=${tag},_GIT_SHA=${sha}" "${BENCH_TXGEN_REPO}"
        digest="$(bench_txgen_image_digest)"
        [ -n "${digest}" ] || bench_die "Cloud Build finished but ${BENCH_TXGEN_IMAGE} is still not in the registry"
    fi
    echo "    ✓ ${BENCH_TXGEN_IMAGE} = ${digest}"
    bench_txgen_cli_probe
    bench_manifest_jq --arg i "${BENCH_TXGEN_IMAGE}" --arg d "${digest}" --arg s "${sha}" \
        '.txgen_image = $i | .txgen_image_digest = $d | .txgen_git_sha = $s'
}

step_2() {
    echo ">>> Step 2: create the bench instances (common/create-instances.sh, bench profile)"
    echo "    + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/common/create-instances.sh"
    "${REPO_ROOT}/common/create-instances.sh"
    echo "    asserting tags == [bench-node] and labels.benchmark == 1 on every node"
    local i inst zone j bad=0
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        j="$(bench_instance_json "${inst}" "${zone}")"
        if [ -z "${j}" ] || ! printf '%s' "${j}" | jq -e '(.tags.items // []) == ["bench-node"] and .labels.benchmark == "1"' >/dev/null; then
            echo "    ✗ ${inst}: $(printf '%s' "${j}" | jq -c '{tags: .tags.items, labels}' 2>/dev/null || echo missing)" >&2; bad=1
        fi
    done
    if [ "${bad}" -ne 0 ]; then
        echo "❌ a bench instance is missing its bench-node tag / benchmark=1 label. Nothing else will run." >&2
        echo "   Inspect, then clean up with: benchmark/benchmark-teardown.sh --run ${BENCH_RUN_ID} (dry run first)" >&2
        exit 1
    fi
    echo "    ✓ all ${#INSTANCE_NAMES[@]} tagged bench-node + labelled benchmark=1"
    local insts="[]" disk djson shape
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        j="$(bench_instance_json "${inst}" "${zone}")"
        disk="$(printf '%s' "${j}" | jq -r '.disks[] | select(.boot) | .source | split("/") | last')"
        bench_run gcloud compute disks add-labels "${disk}" --zone="${zone}" --project="${PROJECT_ID}" \
            --labels="${BENCH_LABELS},tn-role=${NODE_ROLES[$i]}" --format=none
        djson="$(gcloud compute disks describe "${disk}" --zone="${zone}" --project="${PROJECT_ID}" --format=json)"
        shape="$(bench_machine_shape "$(printf '%s' "${j}" | jq -r '.machineType | split("/") | last')" "${zone}")"
        insts="$(printf '%s' "${insts}" | jq --argjson j "${j}" --argjson d "${djson}" --arg role "${NODE_ROLES[$i]}" \
            --arg zone "${zone}" --arg v "${shape% *}" --arg m "${shape#* }" '
            . + [{name: $j.name, role: $role, zone: $zone, instance_id: $j.id,
                  machine_type: ($j.machineType | split("/") | last), vcpus: ($v|tonumber), memory_mb: ($m|tonumber),
                  internal_ip: $j.networkInterfaces[0].networkIP,
                  external_ip: ($j.networkInterfaces[0].accessConfigs[0].natIP // null),
                  boot_disk: {name: $d.name, size_gb: ($d.sizeGb|tonumber), type: ($d.type | split("/") | last)}}]')"
    done
    bench_manifest_jq --argjson a "${insts}" '.instances = $a'
    echo "    ✓ manifest.instances[] recorded (${#INSTANCE_NAMES[@]})"
}

step_3() {
    echo ">>> Step 3: wait for first-boot bootstrap (serial marker 'devnet-startup.sh complete')"
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        bench_serial_wait "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "devnet-startup.sh complete" \
            "${BOOTSTRAP_TIMEOUT_SECS}" "${BOOTSTRAP_POLL_SECS}" \
            || bench_die "${INSTANCE_NAMES[$i]} did not finish bootstrap; serial: gcloud compute instances get-serial-port-output ${INSTANCE_NAMES[$i]} --zone=${ZONES[$i]}"
    done
}

step_4()  { echo ">>> Step 4: bench firewall rules"; "${DIR}/benchmark-firewall.sh" apply --yes --run "${BENCH_RUN_ID}"; }
step_5()  { echo ">>> Step 5: keygen";               "${REPO_ROOT}/devnet-keygen.sh"; }
step_6()  { echo ">>> Step 6: genesis (chain ${CHAIN_ID}, workspace ${GENESIS_WORKSPACE})"; "${REPO_ROOT}/devnet-genesis-build.sh"; }
step_7()  { echo ">>> Step 7: finalize (stage + start)"; "${REPO_ROOT}/devnet-finalize.sh"; }

# obs_script <instance> <region> <token> — step 8's remote script for one node (piped to
# `sudo bash -s`, so the ingest token never appears on a gcloud command line).
#
# setup-observability.sh derives TN_CHAIN from the node's NETWORK=devnet (DEVNET_CHAIN_NAME is
# readonly in tn-node-deployment), so left alone the node would remote-write
# network="devnet" chain="devnet" samples into obs-devnet. To make that impossible rather than
# brief, setup-observability.sh is pointed at a black-hole metrics URL (127.0.0.1:9, refused);
# then, in the same session and before anything can reach obs-devnet, Alloy is stopped, its WAL
# (which holds the devnet-labelled samples) is wiped, the env gets TN_CHAIN/TN_NODE/the real URL,
# and Alloy starts again. The first sample obs-devnet ever sees from a bench node is network=bench.
obs_script() {
    local inst="$1" region="$2" token="$3" hold="http://127.0.0.1:9/bench-hold"
    cat <<EOS
set -euo pipefail
fail() { echo "OBSCFG_FAIL \$*"; exit 1; }
TOKEN=$(printf '%q' "${token}")
if ! OBS_PUSH_URL='${OBS_PUSH_URL}' OBS_METRICS_PUSH_URL='${hold}' \\
    '${TN_NODE_SCRIPTS_DIR}/setup-observability.sh' --json --enable-metrics --region '${region}' \\
    --token "\${TOKEN}" --push-url '${OBS_PUSH_URL}' --metrics-push-url '${hold}' > /tmp/bench-obs.json 2>/tmp/bench-obs.err; then
    tail -5 /tmp/bench-obs.err; fail "setup-observability.sh failed"
fi
unset TOKEN
systemctl stop telcoin-alloy.service
rm -rf /var/lib/telcoin-alloy/* 2>/dev/null || true
E=/etc/telcoin/alloy/telcoin-alloy.env
[ -f "\$E" ] || fail "no \$E"
sed -i -e 's/^TN_CHAIN=.*/TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}/' -e 's/^TN_NODE=.*/TN_NODE=${inst}/' \\
    -e 's#^OBS_METRICS_PUSH_URL=.*#OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}#' "\$E"
grep -qx 'TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}' "\$E" && grep -qx 'TN_NODE=${inst}' "\$E" \\
    && grep -qx 'OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}' "\$E" || fail "alloy env not rewritten"
systemctl start telcoin-alloy.service
systemctl is-active --quiet telcoin-alloy.service || fail "telcoin-alloy not active"
echo "OBSCFG_OK ${inst} \$(tail -1 /tmp/bench-obs.json 2>/dev/null)"
EOS
}

step_8() {
    echo ">>> Step 8: per-node observability, metrics only -> ${OBS_METRICS_PUSH_URL}, labelled network=${BENCH_PROM_NETWORK_LABEL} before the first push"
    # Never common/create-obs-instance.sh (and never --wipe-data): obs-devnet is devnet's.
    # Not devnet-observability.sh either: it cannot relabel inside the setup session (see obs_script).
    local token i inst out
    token="$(tn_secret "${OBS_SECRET_NAME}")" || true
    [ -n "${token}" ] || bench_die "obs ingest token (${OBS_SECRET_NAME}) is empty"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: setup-observability.sh --enable-metrics (token redacted) + same-session relabel"
        out="$(obs_script "${inst}" "$(tn_region_from_zone "${ZONES[$i]}")" "${token}" | tn_iap_ssh_stdin "${inst}" "${ZONES[$i]}" 2>&1 || true)"
        printf '%s\n' "${out}" | grep -E 'OBSCFG_(OK|FAIL)' | cut -c1-200 | sed 's/^/      /' || true
        [[ "${out}" == *"OBSCFG_OK ${inst}"* ]] || bench_die "observability failed on ${inst}"
    done
    unset token
}

# postconfig_params <node-index> — step 9's per-node section, run before the restart: that node's
# BENCH_NODE_PARAM_OVERRIDES into <datadir>/parameters.yaml (`setp <key> <value>` lines) and
# BENCH_NODE_LOG_FILTER onto the telcoin command in the wrapper (the `F=` line; none when the knob is
# empty). It also sets P, the parameters file the readback after the restart reads.
postconfig_params() {
    local kv
    cat <<'EOS'
# 2b. this node's parameters and log filter. The datadir is the --datadir argument of the wrapper's
#     telcoin command; under docker that is the container path, so the host side of its
#     `-v <host>:<datadir>` bind is where parameters.yaml really is.
D="$(grep -v '^[[:space:]]*#' "$W" | sed -nE 's/.*--datadir[ =]([^[:space:]]+).*/\1/p' | head -1 || true)"
[ -n "$D" ] || fail "no --datadir in $W"
H="$(grep -v '^[[:space:]]*#' "$W" | sed -nE "s#.*-v[[:space:]]+([^[:space:]:]+):${D}([:[:space:]].*)?\$#\1#p" | head -1 || true)"
P="${H:-$D}/parameters.yaml"
[ -f "$P" ] || fail "no $P"
# A file an earlier step 9 rewrote (it has '# bench-override' lines) is first restored from its .bak;
# any other file becomes the .bak. Written through `cat >`, so owner, mode and inode stay.
if grep -q '# bench-override$' "$P"; then
    [ -f "$P.bak" ] || fail "$P has bench-override lines but no $P.bak"
    cat "$P.bak" > "$P"
else
    cp -p "$P" "$P.bak"
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
    bench_node_overrides "$1" | while IFS= read -r kv; do printf 'setp %s %s\n' "${kv%%=*}" "${kv#*=}"; done
    [ -n "${BENCH_NODE_LOG_FILTER:-}" ] || return 0
    printf "F='%s'; MF='%s'\n" "${BENCH_NODE_LOG_FILTER}" "${BENCH_NODE_LOG_MAX_FILES}"
    cat <<'EOS'
# the filter goes right after --datadir <dir>, once; copies an earlier run left are dropped first
[ "$(grep -v '^[[:space:]]*#' "$W" | grep -c -- '--datadir' || true)" = 1 ] || fail "not exactly one --datadir line in $W"
sed -i -E -e 's/ --log\.(stdout|file)\.filter [^[:space:]]+//g' -e 's/ --log\.file\.max-files [^[:space:]]+//g' "$W"
sed -i -E "/^[[:space:]]*#/!s#(--datadir[ =][^[:space:]]+)#\1 --log.stdout.filter ${F} --log.file.filter ${F} --log.file.max-files ${MF}#" "$W"
grep -qF -- "--log.stdout.filter ${F} --log.file.filter ${F} --log.file.max-files ${MF}" "$W" || fail "log filter not set in $W"
EOS
}

# postconfig_readback — step 9's readback after the restart, for the POSTCFG_OK line: pv <key> reads
# a top-level value of the node's parameters.yaml (P, from postconfig_params), ms turns it into ms
# (- when absent); rf / rff / rmf are the running container's --log.stdout.filter, --log.file.filter
# and --log.file.max-files ("" when not set). The two filters must be the same.
postconfig_readback() {
    cat <<'EOS'
# 3b. what the node now runs with: its parameters.yaml, and the container's command line
pv() { awk -v k="$1" 'index($0, k ":") == 1 { v = substr($0, length(k) + 2); sub(/^[ \t]+/, "", v); sub(/[ \t]*#.*$/, "", v); gsub(/["\047]/, "", v); print v; exit }' "$P"; }
ms() { case "$1" in '') echo - ;; *ms) echo "${1%ms}" ;; *s) awk -v s="${1%s}" 'BEGIN { printf "%d\n", s * 1000 }' ;; *) echo "?" ;; esac; }
CMDL="$(docker inspect -f '{{.Path}} {{join .Args " "}}' telcoin 2>/dev/null || true)"
arg() { printf '%s\n' "$CMDL" | sed -nE "s/.* $1 ([^[:space:]]+).*/\1/p" | tail -1 || true; }
rf="$(arg '--log\.stdout\.filter')"; rff="$(arg '--log\.file\.filter')"; rmf="$(arg '--log\.file\.max-files')"
[ "$rff" = "$rf" ] || fail "running --log.file.filter '$rff' differs from --log.stdout.filter '$rf'"
pthr="$(pv header_num_of_batches_threshold)"
EOS
}

# postconfig_script <instance> — step 9's remote script for one node (piped to `sudo bash -s`).
# Everything that can fail transiently (the RPC while the node restarts) is polled with a
# deadline and never trips set -e/pipefail; only the final assertions can fail the session.
# Its last line: POSTCFG_OK <inst> chain=<hex> block=<hex|?> ip=<ip> progress=<text with spaces>
#   sha=<git sha> mhd=<ms|?> nhd=<ms|?> mbd=<ms|?> vt=<ms|?> forks=<label|?>
#   max=<ms|-> min=<ms|-> batch=<ms|-> thr=<n|-> vote=<ms|-> filter=<filter|-> maxfiles=<n|->
# where sha / mhd / nhd / mbd / vt / forks come from the restarted container's boot lines (the
# `telcoin-network <ver> (<sha>) starting` line, "Max|Min header delay set to N ms", "Max batch
# delay set to N ms", "... vote timeout set to N ms" when logged, the fork-schedule line labelled
# by report/provenance.py's rules); max / min / batch / thr / vote are read back from the node's
# parameters.yaml after the restart (- = not in the file) and filter / maxfiles from the running
# container's command line (--log.stdout.filter, --log.file.max-files; - = not set). step_9 compares
# them with the run's manifest and this node's overrides.
postconfig_script() {
    local inst="$1" b64 idx
    idx="$(bench_index_of "${inst}")" || bench_die "postconfig_script: ${inst} is not a bench instance"
    b64="$(base64 < "${DIR}/node-sampler.sh" | tr -d '\n')"
    cat <<EOS
set -euo pipefail
fail() { echo "POSTCFG_FAIL \$*"; exit 1; }
W=/opt/telcoin/start-telcoin.sh
[ -f "\$W" ] || fail "no \$W (docker start wrapper)"
# 1. reth RPC on all interfaces (blasters reach it on the internal IP; no public rule admits 8545)
sed -i 's/--http\.addr 127\.0\.0\.1/--http.addr 0.0.0.0/' "\$W"
grep -q -- '--http.addr 0.0.0.0' "\$W" || fail "http.addr not rewritten"
# 2. alloy labels were set in step 8's session; assert they are still bench labels
E=/etc/telcoin/alloy/telcoin-alloy.env
grep -qx 'TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}' "\$E" && grep -qx 'TN_NODE=${inst}' "\$E" || fail "alloy env lacks bench labels (re-run step 8)"
$(postconfig_params "${idx}")
# 3. restart the node; wait until it serves chain ${CHAIN_ID} on the INTERNAL IP and consensus is
#    progressing. An idle TN chain stays at block 0 (the engine skips empty non-epoch-closing
#    consensus outputs), so progress = eth_blockNumber increased OR this node's own log shows
#    consensus progress since the restart: validators log 'subdag committed' / 'quorum reached',
#    an observer (follower) logs 'got new consensus' / 'catching up consensus blocks'.
boot_ts=\$(date +%s)
systemctl restart telcoin
restart_ts=\$(date +%s)
IP=\$(curl -sf -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip || true)
[ -n "\$IP" ] || fail "no internal IP from the metadata server"
# ECONNREFUSED right after the restart is expected: curl's failure is swallowed, empty = retry.
rpc() { { curl -s --max-time 3 -H 'content-type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"\$1\",\"params\":[]}" "http://\${IP}:8545" || true; } | sed -n 's/.*"result":"\([^"]*\)".*/\1/p' || true; }
# consensus lines in the node's docker log since the restart (never older than 45 s)
commits() {
    local now since
    now=\$(date +%s); since=\$(( now - 45 )); [ "\$since" -ge "\$restart_ts" ] || since="\$restart_ts"
    { docker logs telcoin --since "\$since" 2>&1 || true; } | grep -c -E 'subdag committed|quorum reached|got new consensus|catching up consensus blocks|skipping execution for empty|executing consensus output' || true
}
# the restarted binary's boot lines (logged once, at start): git sha, consensus delays, vote
# timeout (later builds only), fork schedule — labelled as report/provenance.py does: a
# "fork schedule (adiri)" line -> adiri-schedule; a "fork schedule:" line listing
# subsecond_timestamp before "active from genesis" -> subsecond-from-genesis; any other
# "fork schedule:" line -> pre-subsecond; none -> ?. Each pass fills only fields still empty,
# so a later read (say a transient empty docker logs) never blanks what an earlier one found.
sha=""; mhd=""; nhd=""; mbd=""; vt=""; forks=""
delay() { printf '%s\n' "\$1" | grep -ioE "\$2 set to [0-9]+ ?ms" | tail -1 | grep -oE '[0-9]+' | head -1 || true; }
prov() {
    local L fl
    L="\$({ docker logs telcoin --since "\$boot_ts" 2>&1 || true; } | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' || true)"
    [ -n "\$sha" ] || sha="\$(printf '%s\n' "\$L" | sed -nE 's/.*telcoin-network[[:space:]]+[^[:space:]]+[[:space:]]+\(([^()[:space:]]+)\)[[:space:]]+starting.*/\1/p' | tail -1 || true)"
    [ -n "\$mhd" ] || mhd="\$(delay "\$L" 'max header delay')"
    [ -n "\$nhd" ] || nhd="\$(delay "\$L" 'min header delay')"
    [ -n "\$mbd" ] || mbd="\$(delay "\$L" 'max batch delay')"
    [ -n "\$vt" ] || vt="\$(delay "\$L" 'vote timeout')"
    [ -z "\$forks" ] || return 0
    fl="\$(printf '%s\n' "\$L" | grep -iE 'fork schedule[[:space:]]*(\(adiri\)|:)' | tail -1 || true)"
    if [ -z "\$fl" ]; then forks=""
    elif printf '%s\n' "\$fl" | grep -qiE 'fork schedule[[:space:]]*\(adiri\)'; then forks=adiri-schedule
    elif printf '%s\n' "\$fl" | grep -qiE 'subsecond_timestamp[[:alnum:]_[:space:],]*active from genesis'; then forks=subsecond-from-genesis
    else forks=pre-subsecond; fi
}
booted() { [ -n "\$sha" ] && [ -n "\$mhd" ] && [ -n "\$nhd" ] && [ -n "\$mbd" ]; }
cid=""; b0=""; b=""; how=""; n=0
deadline=\$(( \$(date +%s) + \${POSTCFG_WAIT_SECS:-300} ))
while [ "\$(date +%s)" -lt "\$deadline" ]; do
    if [ -z "\$how" ] && systemctl is-active --quiet telcoin; then
        cid="\$(rpc eth_chainId)"
        if [ "\$cid" = "${CHAIN_ID_HEX}" ]; then
            b="\$(rpc eth_blockNumber)"
            if [ -n "\$b" ]; then
                if [ -z "\$b0" ]; then b0="\$b"; elif [ "\$((b))" -gt "\$((b0))" ]; then how="blocks \$((b0))->\$((b))"; fi
            fi
            if [ -z "\$how" ]; then
                n="\$(commits)"
                if [ "\${n:-0}" -ge 1 ]; then how="consensus log (\${n} subdag committed/quorum reached lines since restart)"; fi
            fi
        fi
    fi
    booted || prov
    if [ -n "\$how" ] && booted; then break; fi
    sleep 5
done
[ "\$cid" = "${CHAIN_ID_HEX}" ] || fail "eth_chainId on \${IP}:8545 = '\$cid', expected ${CHAIN_ID_HEX}"
[ -n "\$how" ] || fail "consensus not progressing: block \${b0:-none} -> \${b:-none} and no 'subdag committed|quorum reached' in docker logs since the restart"
prov   # once more: lines logged after the last poll (the fork schedule, a vote timeout)
[ -n "\$sha" ] || fail "no 'telcoin-network <version> (<sha>) starting' line in docker logs since the restart"
$(postconfig_readback)
# 4. node sampler (systemd, root)
echo '${b64}' | base64 -d > /usr/local/bin/bench-node-sampler.sh
chmod 0755 /usr/local/bin/bench-node-sampler.sh
cat > /etc/systemd/system/bench-node-sampler.service <<'UNIT'
[Unit]
Description=benchmark node sampler (CSV every 30 s -> /var/lib/bench-sampler)
After=docker.service telcoin.service
[Service]
Type=simple
ExecStart=/usr/local/bin/bench-node-sampler.sh
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now bench-node-sampler.service
systemctl is-active --quiet bench-node-sampler.service || fail "sampler not active"
echo "POSTCFG_OK ${inst} chain=\$cid block=\${b:-?} ip=\${IP} progress=\${how} sha=\${sha} mhd=\${mhd:-?} nhd=\${nhd:-?} mbd=\${mbd:-?} vt=\${vt:-?} forks=\${forks:-?} max=\$(ms "\$(pv max_header_delay)") min=\$(ms "\$(pv min_header_delay)") batch=\$(ms "\$(pv max_batch_delay)") thr=\${pthr:--} vote=\$(ms "\$(pv vote_timeout)") filter=\${rf:--} maxfiles=\${rmf:--}"
EOS
}

# postcfg_field <POSTCFG_OK line> <key> — the value of its last " <key>=<value>" ("" if absent).
postcfg_field() { printf '%s\n' "$1" | sed -n "s/.* $2=\([^ ]*\).*/\1/p" | tail -1; }

# step9_node_check <node-index> <POSTCFG_OK line> <sha> <forks> — merge the node's boot lines and
# readback into manifest.node_startup[<inst>] (sha mhd nhd mbd vt forks from the boot lines; params
# {max_header_delay_ms, min_header_delay_ms, max_batch_delay_ms, header_num_of_batches_threshold,
# vote_timeout_ms} from its parameters.yaml; log_filter / log_max_files from its command line), then
# die on the first value that differs from what this node must run (the sha matches when the node's
# starts with the expected one: a full 40-hex expectation must match in full). Delays and the
# threshold are this node's (run_expect <field> <node-index>: an override, else the manifest's). vt is
# compared only with a vote_timeout override; the log fields only when BENCH_NODE_LOG_FILTER is set.
step9_node_check() {
    local idx="$1" line="$2" w_sha="$3" w_forks="$4" inst sha mhd nhd mbd vt forks pmax pmin pbatch pthr pvote lf lmf
    local w_mhd w_nhd w_mbd w_vt w_thr src
    inst="${INSTANCE_NAMES[$idx]}"
    w_mhd="$(run_expect mhd "${idx}")"; w_nhd="$(run_expect nhd "${idx}")"; w_mbd="$(run_expect mbd "${idx}")"
    w_vt="$(run_expect vt "${idx}")"; w_thr="$(run_expect thr "${idx}")"
    sha="$(postcfg_field "${line}" sha | tr 'ABCDEF' 'abcdef')"
    mhd="$(postcfg_field "${line}" mhd)"; nhd="$(postcfg_field "${line}" nhd)"; mbd="$(postcfg_field "${line}" mbd)"
    vt="$(postcfg_field "${line}" vt)"; forks="$(postcfg_field "${line}" forks)"
    pmax="$(postcfg_field "${line}" max)"; pmin="$(postcfg_field "${line}" min)"; pbatch="$(postcfg_field "${line}" batch)"
    pthr="$(postcfg_field "${line}" thr)"; pvote="$(postcfg_field "${line}" vote)"
    lf="$(postcfg_field "${line}" filter)"; lmf="$(postcfg_field "${line}" maxfiles)"
    bench_manifest_jq --arg i "${inst}" --arg sha "${sha}" --arg mhd "${mhd}" --arg nhd "${nhd}" \
        --arg mbd "${mbd}" --arg vt "${vt}" --arg forks "${forks}" --arg pmax "${pmax}" --arg pmin "${pmin}" \
        --arg pbatch "${pbatch}" --arg pthr "${pthr}" --arg pvote "${pvote}" --arg lf "${lf}" --arg lmf "${lmf}" '
        def num: if test("^[0-9]+$") then tonumber else null end;
        def str: if . == "" or . == "?" or . == "-" then null else . end;
        .node_startup[$i] = ((.node_startup[$i] // {}) + {sha: ($sha|str), mhd: ($mhd|num), nhd: ($nhd|num),
                             mbd: ($mbd|num), vt: ($vt|num), forks: ($forks|str),
                             params: {max_header_delay_ms: ($pmax|num), min_header_delay_ms: ($pmin|num),
                                      max_batch_delay_ms: ($pbatch|num), header_num_of_batches_threshold: ($pthr|num),
                                      vote_timeout_ms: ($pvote|num)},
                             log_filter: ($lf|str), log_max_files: ($lmf|num)})' \
        || bench_die "${inst}: could not record node_startup in $(bench_manifest)"
    local stop="— stopping before any other node restarts"
    src="manifest consensus_parameters"
    [ -z "$(bench_node_overrides "${idx}")" ] || src="${src} + BENCH_NODE_PARAM_OVERRIDES"
    case "${sha}" in
        "${w_sha}"?*|"${w_sha}") ;;
        *) bench_die "${inst}: boot sha = ${sha:-<none>}, expected ${w_sha} (manifest node_git_sha) ${stop}" ;;
    esac
    [ "${mhd}" = "${w_mhd}" ] || bench_die "${inst}: max_header_delay = ${mhd:-<none>} ms, expected ${w_mhd} ms (${src}) ${stop}"
    [ "${nhd}" = "${w_nhd}" ] || bench_die "${inst}: min_header_delay = ${nhd:-<none>} ms, expected ${w_nhd} ms (${src}) ${stop}"
    [ "${mbd}" = "${w_mbd}" ] || bench_die "${inst}: max_batch_delay = ${mbd:-<none>} ms, expected ${w_mbd} ms (${src}) ${stop}"
    [ "${forks}" = "${w_forks}" ] || bench_die "${inst}: fork schedule = ${forks:-<none>}, expected ${w_forks} (manifest node_fork_schedule) ${stop}"
    # The node's parameters.yaml must say what its boot lines say.
    [ "${pmax}" = "${w_mhd}" ] && [ "${pmin}" = "${w_nhd}" ] && [ "${pbatch}" = "${w_mbd}" ] \
        || bench_die "${inst}: parameters.yaml has max/min header delay ${pmax:-?}/${pmin:-?} ms and max batch delay ${pbatch:-?} ms, expected ${w_mhd}/${w_nhd}/${w_mbd} ms (${src}) ${stop}"
    [ -z "${w_thr}" ] || [ "${pthr}" = "${w_thr}" ] \
        || bench_die "${inst}: parameters.yaml has header_num_of_batches_threshold ${pthr:-?}, expected ${w_thr} (${src}) ${stop}"
    if [ -n "${w_vt}" ]; then
        [ "${pvote}" = "${w_vt}" ] || bench_die "${inst}: parameters.yaml has vote_timeout ${pvote:-?} ms, expected ${w_vt} ms (BENCH_NODE_PARAM_OVERRIDES) ${stop}"
        case "${vt}" in ''|'?') ;; *) [ "${vt}" = "${w_vt}" ] || bench_die "${inst}: vote_timeout = ${vt} ms at boot, expected ${w_vt} ms (BENCH_NODE_PARAM_OVERRIDES) ${stop}" ;; esac
    fi
    if [ -n "${BENCH_NODE_LOG_FILTER:-}" ]; then
        [ "${lf}" = "${BENCH_NODE_LOG_FILTER}" ] && [ "${lmf}" = "${BENCH_NODE_LOG_MAX_FILES}" ] \
            || bench_die "${inst}: the node runs --log.stdout.filter ${lf:-<none>} --log.file.max-files ${lmf:-<none>}, expected ${BENCH_NODE_LOG_FILTER} / ${BENCH_NODE_LOG_MAX_FILES} (BENCH_NODE_LOG_FILTER) ${stop}"
    fi
    echo "      ✓ ${inst}: boot git ${sha}, delays ${mhd}/${nhd}/${mbd} ms, vote timeout ${vt:-?}, forks ${forks}, yaml threshold ${pthr}, log filter ${lf} — as expected"
}

step_9() {
    echo ">>> Step 9: post-config, one IAP session per node, serially (<= 1 node down at a time)"
    local i inst out line w_sha w_mhd w_nhd w_mbd w_forks
    w_sha="$(run_expect sha | tr 'ABCDEF' 'abcdef')"; w_forks="$(run_expect forks)"
    w_mhd="$(run_expect mhd)"; w_nhd="$(run_expect nhd)"; w_mbd="$(run_expect mbd)"
    if [ -z "${w_sha}" ] || [ -z "${w_forks}" ] || [ -z "${w_mhd}" ] || [ -z "${w_nhd}" ] || [ -z "${w_mbd}" ]; then
        bench_die "step 9 cannot check the nodes' boot lines: expected sha='${w_sha}' forks='${w_forks}' delays='${w_mhd}/${w_nhd}/${w_mbd}' — $(bench_manifest) lacks node_git_sha / node_fork_schedule / consensus_parameters (the gate records them when a step of 0, 5, 6, 7 runs) and no node image probe ran in this invocation"
    fi
    echo "    every node must boot git ${w_sha}, header delay max ${w_mhd} / min ${w_nhd} ms, batch delay ${w_mbd} ms, forks ${w_forks}"
    [ -z "${BENCH_NODE_PARAM_OVERRIDES}" ] || echo "    except where BENCH_NODE_PARAM_OVERRIDES='${BENCH_NODE_PARAM_OVERRIDES}' sets that node's own values"
    echo "    node log filter: ${BENCH_NODE_LOG_FILTER:-untouched (BENCH_NODE_LOG_FILTER is empty)}${BENCH_NODE_LOG_FILTER:+, --log.file.max-files ${BENCH_NODE_LOG_MAX_FILES}}"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: http.addr 0.0.0.0, assert alloy labels, parameters.yaml$( [ -z "$(bench_node_overrides "${i}")" ] || printf ' (%s)' "$(bench_node_overrides "${i}" | paste -sd, -)" ) + log filter, restart, chain-id ${CHAIN_ID_HEX} on internal IP, boot lines + readback, sampler"
        bench_save_node_log "${i}" pre-step9 || bench_warn "${inst}: container log not saved before the step-9 restart — restarting anyway"
        out="$(postconfig_script "${inst}" | tn_iap_ssh_stdin "${inst}" "${ZONES[$i]}" 2>&1 | tr -d '\r' || true)"
        printf '%s\n' "${out}" | grep -E 'POSTCFG_(OK|FAIL)' | sed 's/^/      /' || true
        line="$(printf '%s\n' "${out}" | grep -F "POSTCFG_OK ${inst} " | tail -1 || true)"
        [ -n "${line}" ] || bench_die "post-config failed on ${inst} — stopping before any other node restarts"
        step9_node_check "${i}" "${line}" "${w_sha}" "${w_forks}"
    done
}

# bench_registry_probe — read the ConsensusRegistry over the tunnel with recovery-schedule.py (the
# current epoch, its opening block, its duration, plus the boundary drill it would schedule from
# now) and require the registry's epoch duration to be EPOCH_DURATION_SECS. The JSON is recorded
# as manifest.registry_probe. A failed read (non-zero exit: an RPC error, a timeout, a Python
# traceback, or output that is not a JSON object) is retried, 3 attempts 10 s apart; a duration
# that differs is final.
bench_registry_probe() {
    local out="" dur try=1
    while :; do
        echo "    + python3 ${DIR}/recovery-schedule.py --rpc-url ${RPC_URL} --earliest-kill <now>   (attempt ${try}/3)"
        if out="$(python3 "${DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" --earliest-kill "$(date +%s)")" \
            && printf '%s' "${out}" | jq -e 'type == "object"' >/dev/null 2>&1; then
            break
        fi
        [ "${try}" -lt 3 ] || bench_die "registry probe failed 3 times, 10 s apart (recovery-schedule.py --rpc-url ${RPC_URL})"
        echo "      registry read failed — retrying in 10 s"
        try=$((try + 1)); sleep 10
    done
    dur="$(printf '%s' "${out}" | jq -r '.duration_secs // empty' 2>/dev/null || true)"
    [ "${dur}" = "${EPOCH_DURATION_SECS}" ] \
        || bench_die "ConsensusRegistry epoch duration is ${dur:-<unreadable>} s, EPOCH_DURATION_SECS is ${EPOCH_DURATION_SECS} s (registry probe: ${out})"
    bench_manifest_jq --argjson r "${out}" '.registry_probe = $r' || bench_die "could not record registry_probe in $(bench_manifest)"
    echo "    ✓ registry: epoch $(printf '%s' "${out}" | jq -r '.epoch'), duration ${dur}s == EPOCH_DURATION_SECS (manifest.registry_probe)"
}

step_10() {
    echo ">>> Step 10: health gate"
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        HEALTH_POLL_SECS=15 HEALTH_TIMEOUT_SECS=180 wait_healthy "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$(tn_service_for_role "${NODE_ROLES[$i]}")" \
            || bench_die "${INSTANCE_NAMES[$i]} not healthy"
    done
    bench_tunnel_up || bench_die "IAP tunnel failed"
    local cid
    cid="$(cast chain-id --rpc-url "${RPC_URL}")"
    [ "${cid}" = "${CHAIN_ID}" ] || bench_die "tunnel RPC reports chain ${cid}, expected ${CHAIN_ID}"
    echo "    ✓ chain id ${cid} via ${RPC_URL} (block $(cast block-number --rpc-url "${RPC_URL}" 2>/dev/null || echo '?'); an idle TN chain stays at 0 until the funder runs)"
    bench_registry_probe
    # Progress = consensus rounds, not blocks: every node's min(tn_primary_round) must rise above
    # its first sample. Re-sampled every 30 s (up to 4x) to absorb scrape + remote-write lag.
    local r0 r1="" adv="[]" tries=0 missing=" (no Prometheus sample)" inst
    r0="$(bench_prom_rounds min)"
    [ -n "${r0}" ] || bench_die "Prometheus tn_primary_round query failed"
    while [ "${tries}" -lt 4 ]; do
        sleep 30; tries=$((tries + 1))
        r1="$(bench_prom_rounds min)"
        [ -n "${r1}" ] || continue
        adv="$(bench_rounds_advanced "${r0}" "${r1}")"
        missing=""
        for inst in "${INSTANCE_NAMES[@]}"; do
            printf '%s' "${adv}" | jq -e --arg n "${inst}" 'index($n) != null' >/dev/null || missing="${missing} ${inst}"
        done
        [ -n "${missing}" ] || break
        echo "      …consensus round not yet advanced on:${missing} ($((tries * 30))s)"
    done
    [ -z "${missing}" ] || bench_die "consensus round did not advance on:${missing} (first ${r0}, last ${r1:-none})"
    echo "    ✓ consensus progressing: tn_primary_round advanced on all ${#INSTANCE_NAMES[@]} nodes ($(printf '%s' "${r1}" | jq -r '[.[]] | "rounds " + (min|tostring) + ".." + (max|tostring)'))"
    local n="" waited=0
    while [ "${waited}" -le 300 ]; do
        n="$(bench_prom_scalar "${PROM_COUNT_QUERY}")"
        [ "${n}" = "${#INSTANCE_NAMES[@]}" ] && break
        echo "      …Prometheus sees ${n:-0}/${#INSTANCE_NAMES[@]} bench nodes (${waited}s)"
        sleep 30; waited=$((waited + 30))
    done
    [ "${n}" = "${#INSTANCE_NAMES[@]}" ] || bench_die "Prometheus sees ${n:-0} bench nodes, expected ${#INSTANCE_NAMES[@]} (${PROM_COUNT_QUERY})"
    echo "    ✓ Prometheus: ${n} bench nodes reporting"
    # No bench series may ever carry devnet's labels (step 8 relabels before the first push).
    local q raw leak
    for q in "${PROM_LEAK_QUERY}" "${PROM_LEAK_ANY_QUERY}"; do
        raw="$(bench_prom_query "${q}" || true)"
        printf '%s' "${raw}" | jq -e '.status == "success"' >/dev/null 2>&1 || bench_die "Prometheus query failed: ${q}"
        leak="$(printf '%s' "${raw}" | jq -r '.data.result[0].value[1] // "0"')"
        [ "${leak}" = "0" ] || bench_die "${leak} bench node(s) have series labelled network=\"devnet\" in obs-devnet (${q})"
    done
    echo "    ✓ Prometheus: no network=\"devnet\" series from bench nodes"
    bench_manifest_ts nodes_healthy
}

step_11() {
    echo ">>> Step 11: app contracts on chain ${CHAIN_ID}"
    local out="${BENCH_RESULTS_DIR}/deployments-bench.json"
    if [ "${WITH_CONTRACTS}" -ne 1 ]; then
        echo "    skipped (no --with-contracts). Steps 13/14 need ${out}."
        [ -f "${out}" ] || bench_warn "${out} does not exist yet"
        return 0
    fi
    local wt="${BENCH_CONTRACTS_WORKTREE}" br="${BENCH_CONTRACTS_BRANCH}"
    [ -d "${BENCH_CONTRACTS_SRC_DIR}" ] || bench_die "${BENCH_CONTRACTS_SRC_DIR} missing (devnet-contracts.sh's checkout)"
    if [ ! -d "${wt}" ]; then
        mkdir -p "$(dirname "${wt}")"
        bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree add "${wt}" -b "${br}" "${BENCH_CONTRACTS_BASE_BRANCH}"
    fi
    [ "$(git -C "${wt}" rev-parse --abbrev-ref HEAD)" = "${br}" ] || bench_die "${wt} is not on ${br}"
    bench_run git -C "${wt}" submodule update --init --recursive
    # Chain 32286 routes tn-contracts to deployments-testnet.json (DeploymentsResolver.sol);
    # seed it with the devnet address book so the same CREATE2 addresses are expected.
    bench_run cp "${wt}/deployments/deployments-devnet.json" "${wt}/deployments/deployments-testnet.json"
    bench_tunnel_up || bench_die "IAP tunnel failed"
    echo "    + TN_CONTRACTS_DIR=${wt} TN_CONTRACTS_BRANCH=${br} DEPLOYMENTS_JSON=deployments/deployments-testnet.json DEVNET_RPC=${RPC_URL} EXPECTED_CHAIN_ID=${CHAIN_ID} devnet-contracts.sh --yes"
    TN_CONTRACTS_DIR="${wt}" TN_CONTRACTS_BRANCH="${br}" DEPLOYMENTS_JSON="deployments/deployments-testnet.json" \
        DEVNET_RPC="${RPC_URL}" EXPECTED_CHAIN_ID="${CHAIN_ID}" "${REPO_ROOT}/devnet-contracts.sh" --yes
    cp "${wt}/deployments/deployments-testnet.json" "${out}"
    echo "    ✓ ${out} (the worktree is never committed; teardown removes it + ${br})"
    bench_manifest_ts contracts_done
}

step_12() {
    echo ">>> Step 12: secret access for ${SERVICE_ACCOUNT} + results bucket gs://${BENCH_BUCKET}"
    local s
    for s in "${BENCH_TXGEN_MASTER_SECRET}" "${BENCH_TXGEN_SEED_SECRET}"; do
        case "${s}" in bench-txgen-*) ;; *) bench_die "unexpected secret ${s}" ;; esac
        bench_run gcloud secrets add-iam-policy-binding "${s}" --project="${PROJECT_ID}" \
            --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --format=none
    done
    if gcloud storage buckets describe "gs://${BENCH_BUCKET}" --format='value(name)' >/dev/null 2>&1; then
        echo "    bucket exists"
    else
        bench_run gcloud storage buckets create "gs://${BENCH_BUCKET}" --project="${PROJECT_ID}" \
            --location="${BENCH_BUCKET_LOCATION}" --uniform-bucket-level-access
    fi
    bench_run gcloud storage buckets update "gs://${BENCH_BUCKET}" --update-labels="${BENCH_LABELS}"
}

step_13() { echo ">>> Step 13: fund senders"; "${DIR}/benchmark-blast.sh" fund --yes --run "${BENCH_RUN_ID}"; }
step_14() { echo ">>> Step 14: blast";        "${DIR}/benchmark-blast.sh" run --yes --run "${BENCH_RUN_ID}"; }

step_15() {
    echo ">>> Step 15: collect"
    "${DIR}/benchmark-blast.sh" collect --yes --run "${BENCH_RUN_ID}"
    if [ -f "${COLLECT_METRICS_PY}" ]; then
        echo "    + python3 ${COLLECT_METRICS_PY} --manifest ${BENCH_RESULTS_DIR}/manifest.json --out ${BENCH_RESULTS_DIR}/metrics.json"
        python3 "${COLLECT_METRICS_PY}" --manifest "$(bench_manifest)" --out "${BENCH_RESULTS_DIR}/metrics.json"
    else
        bench_warn "${COLLECT_METRICS_PY} not found — metrics.json not produced (re-run --only 15 once it exists)"
        bench_manifest_note "collect: ${COLLECT_METRICS_PY} missing at $(bench_now_iso)"
    fi
    # metrics.json is new since the collect: analysis/ and the index again (non-fatal; the
    # teardown's local gate is what guards results/<run>/, the only copy of the run).
    bench_local_analysis
    bench_local_index || bench_warn "INDEX.md / CHECKSUMS.sha256 not written — the teardown writes them"
}

step_16() {
    echo ">>> Step 16: teardown"
    if [ "${WITH_TEARDOWN}" -ne 1 ]; then
        echo "    skipped (no --with-teardown). Later: benchmark/benchmark-teardown.sh --run ${BENCH_RUN_ID} --yes"
        return 0
    fi
    bench_tunnel_down
    "${DIR}/benchmark-teardown.sh" --yes --run "${BENCH_RUN_ID}"
}

# ================================ dry-run plan ==========================================
# plan_probe_line — what the gate's node image probe will check (nothing is executed here).
plan_probe_line() {
    local e="" v
    for v in BENCH_DOCKER_IMAGE_EXPECT_DIGEST BENCH_NODE_EXPECT_SHA BENCH_NODE_EXPECT_FORKS; do
        [ -z "${!v:-}" ] || e="${e} ${v}=${!v}"
    done
    [ -n "${e}" ] || e=" none set"
    if [ "${NODE_PIN_FROM_MANIFEST}" -eq 1 ]; then
        printf '%s: pinned by this run'"'"'s gate (manifest node_image_pinned, git %s, forks %s) — not probed again' \
            "${DOCKER_IMAGE}" "$(run_expect sha)" "$(run_expect forks)"
    else
        printf '%s: digest, telcoin -V sha, flag + string contract (node-image-contract.txt), EXPECT_* env (%s); at the gate when steps 0/5/6/7 run' \
            "${DOCKER_IMAGE}" "${e# }"
    fi
}

# plan_node_params — the plan's "logs" line; with BENCH_NODE_PARAM_OVERRIDES set, one line per node:
# the parameters step 9 leaves it with (the fleet file's, overrides applied); then every node whose
# parameters the node would refuse at startup.
plan_node_params() {
    local i ov vt
    if [ -n "${BENCH_NODE_LOG_FILTER}" ]; then
        echo "  logs     --log.stdout.filter/--log.file.filter ${BENCH_NODE_LOG_FILTER} --log.file.max-files ${BENCH_NODE_LOG_MAX_FILES} (BENCH_NODE_LOG_FILTER, step 9)"
    else
        echo "  logs     node command line untouched (BENCH_NODE_LOG_FILTER is empty)"
    fi
    if [ -n "${BENCH_NODE_PARAM_OVERRIDES}" ]; then
        for i in "${!INSTANCE_NAMES[@]}"; do
            ov="$(bench_node_overrides "${i}" | paste -sd, -)"
            vt="$(bench_node_param_ms "${i}" vote_timeout)"
            printf '    %-20s max_header_delay %s ms, min_header_delay %s ms, max_batch_delay %s ms, threshold %s, vote_timeout %s%s\n' \
                "${INSTANCE_NAMES[$i]}" "$(bench_node_param_ms "${i}" max_header_delay)" "$(bench_node_param_ms "${i}" min_header_delay)" \
                "$(bench_node_param_ms "${i}" max_batch_delay)" "$(bench_node_param_int "${i}" header_num_of_batches_threshold)" \
                "${vt:+${vt} ms}${vt:-5000 ms (node default)}" "${ov:+  [override ${ov}]}"
        done
    fi
    bench_node_params_problems | sed 's/^/    ✗ the node would refuse to start: /'
}

# plan_step9_lines — per node, the lines of its step-9 script that differ between nodes: the setp
# (parameters.yaml) and F= (log filter) lines.
plan_step9_lines() {
    local i l
    for i in "${!INSTANCE_NAMES[@]}"; do
        l="$(postconfig_params "${i}" | grep -E '^(setp |F=)' | paste -sd'|' - | sed 's/|/; /g')"
        printf '                       %-20s %s\n' "${INSTANCE_NAMES[$i]}:" "${l:-(nothing: no override, BENCH_NODE_LOG_FILTER empty)}"
    done
}

# plan_harness — this checkout's HEAD, ",dirty" when tracked files differ from it (local git only).
plan_harness() {
    local sha st
    sha="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
    st="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=no 2>/dev/null || true)"
    printf '%s%s' "${sha}" "${st:+,dirty}"
}

print_plan() {
    local i
    cat <<EOP
PLAN for run ${BENCH_RUN_ID} (nothing below has been executed):

  fleet    ${#INSTANCE_NAMES[@]} x ${MACHINE_TYPE}, $(disk_desc), tag ${INSTANCE_TAGS}, labels ${INSTANCE_LABELS}
  chain    ${CHAIN_ID} (${CHAIN_ID_HEX}), epoch ${EPOCH_DURATION_SECS}s, image ${DOCKER_IMAGE}${BENCH_DOCKER_IMAGE:+ (BENCH_DOCKER_IMAGE)}
  probe    $(plan_probe_line)
  params   ${PARAMETERS_FILE}: max_header_delay $(bench_params_ms "${PARAMETERS_FILE}" max_header_delay) ms, min_header_delay $(bench_params_ms "${PARAMETERS_FILE}" min_header_delay) ms, max_batch_delay $(bench_params_ms "${PARAMETERS_FILE}" max_batch_delay) ms
  per-node ${BENCH_NODE_PARAM_OVERRIDES:-none} (BENCH_NODE_PARAM_OVERRIDES; step 9 writes them into that node's parameters.yaml)
$(plan_node_params)
  harness  $(plan_harness)
  genesis  workspace ${GENESIS_WORKSPACE}, accounts ${GENESIS_WORKSPACE}/testnet_accounts.yaml
  metrics  -> ${OBS_METRICS_PUSH_URL} as network="${BENCH_PROM_NETWORK_LABEL}" (obs-devnet, metrics only)
  load     ${BENCH_TXGEN_IMAGE}, COS blasters x ${BENCH_SENDERS} senders on ${BENCH_BLASTER_MACHINE_TYPES// / -> } (next type on a zone stockout), bucket gs://${BENCH_BUCKET}
  results  ${BENCH_RESULTS_DIR}
EOP
    for i in "${!INSTANCE_NAMES[@]}"; do
        printf '    %-20s %-10s %-26s %s %s\n' "${INSTANCE_NAMES[$i]}" "${NODE_ROLES[$i]}" "${ZONES[$i]}" "${NODE_NAMES[$i]}" "${EXECUTION_ADDRESSES[$i]}"
    done
    echo "    ${#INSTANCE_NAMES[@]} instances in $(fleet_zones | wc -w | tr -d ' ') zones, $(fleet_regions | wc -w | tr -d ' ') regions"
    cat <<EOP

   -  gate           (--yes, before any step) node image probe + pin (when steps 0/5/6/7 run; see "probe" above),
                     manifest.json (+ node_* probe fields, consensus_parameters), pinned txgen image,
                     ${BENCH_TXGEN_CLOUDBUILD}, ${BENCH_TXGEN_CONFIG}, deployments-bench.json
   0  preflight      tools, auth, NO leftover bench-*/benchmark=1 instance|disk|rule|bucket, accounts, empty genesis/,
                     bench-node tag hygiene, obs-devnet df over IAP (< 70%),
                     machine types, disk type and quota headroom (below; every failure listed in one die),
                     pre-snapshots -> ${BENCH_RESULTS_DIR}/pre-{instances,firewall}.json, manifest.json
EOP
    {
        machine_type_check "${MACHINE_TYPE}" BENCH_MACHINE_TYPE "$(fleet_zones)"
        machine_type_check "${BENCH_BLASTER_MACHINE_TYPES%% *}" BENCH_BLASTER_MACHINE_TYPES "$(validator_zones)"
        disk_type_check
        quota_check
    } | sed 's/^    /                     /'
    cat <<EOP
   1  image          ${BENCH_TXGEN_IMAGE:-<unresolved: ${BENCH_TXGEN_IMAGE_ERROR}>}
                     if absent: gcloud builds submit --config=${BENCH_TXGEN_CLOUDBUILD} --substitutions=_IMAGE=${BENCH_TXGEN_IMAGE_REPO},_TAG=${BENCH_TXGEN_TAG:-blast-v2-<sha>},_GIT_SHA=${BENCH_TXGEN_SHA:-<sha>} ${BENCH_TXGEN_REPO}
                     then docker run --rm --platform linux/amd64 <image> blast --help must list: ${BENCH_TXGEN_CONTRACT_FLAGS}
   2  instances      CONFIG_FILE=benchmark/config.sh ${REPO_ROOT}/common/create-instances.sh
                     assert tags==[bench-node] + labels.benchmark=1; gcloud compute disks add-labels <boot> --labels=${BENCH_LABELS},tn-role=<role>
   3  bootstrap      serial marker 'devnet-startup.sh complete' (${BOOTSTRAP_TIMEOUT_SECS}s/node)
   4  firewall       benchmark/benchmark-firewall.sh apply --yes   (${BENCH_FIREWALL_RULES[*]} -> tag bench-node)
   5  keygen         ${REPO_ROOT}/devnet-keygen.sh           -> ${GENESIS_WORKSPACE}/genesis/{validators,observers}/
   6  genesis        ${REPO_ROOT}/devnet-genesis-build.sh    -> ${GENESIS_FILE}
   7  finalize       ${REPO_ROOT}/devnet-finalize.sh
   8  observability  per node, one IAP session: setup-observability.sh --enable-metrics -> black hole 127.0.0.1:9,
                     stop alloy, wipe /var/lib/telcoin-alloy, TN_CHAIN=${BENCH_PROM_NETWORK_LABEL} TN_NODE=<instance> OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}, start alloy
   9  post-config    per node, serial: bench_save_node_log <i> pre-step9 (container log -> /var/lib/bench-logs), then one IAP session: /opt/telcoin/start-telcoin.sh --http.addr 0.0.0.0; assert
                     bench alloy labels; restart telcoin; eth_chainId == ${CHAIN_ID_HEX} on the internal IP + consensus progressing
                     (blocks rose OR docker logs 'subdag committed|quorum reached' since restart); boot lines (git sha, delays,
                     fork schedule) == manifest node_git_sha / consensus_parameters / node_fork_schedule, else stop; bench-node-sampler.service
                     before each restart (the whole script: --print-postconfig <instance>):
$(plan_step9_lines)
  10  health gate    wait_healthy x${#INSTANCE_NAMES[@]}; gcloud compute start-iap-tunnel ${INSTANCE_NAMES[0]} 8545 --local-host-port=localhost:${BENCH_TUNNEL_PORT};
                     cast chain-id == ${CHAIN_ID}; Prometheus ${PROM_COUNT_QUERY} == ${#INSTANCE_NAMES[@]};
                     min by (node)(tn_primary_round{network="${BENCH_PROM_NETWORK_LABEL}"}) rises on every node (samples 30 s apart);
                     ${PROM_LEAK_QUERY} == 0 (and the same over every metric);
                     python3 recovery-schedule.py --rpc-url ${RPC_URL}: registry epoch duration == ${EPOCH_DURATION_SECS} -> manifest.registry_probe
  11  contracts      $([ "${WITH_CONTRACTS}" -eq 1 ] && echo "git worktree add ${BENCH_CONTRACTS_WORKTREE} -b ${BENCH_CONTRACTS_BRANCH} ${BENCH_CONTRACTS_BASE_BRANCH}" || echo "SKIPPED (pass --with-contracts)")
                     $([ "${WITH_CONTRACTS}" -eq 1 ] && echo "devnet-contracts.sh --yes (DEPLOYMENTS_JSON=deployments/deployments-testnet.json EXPECTED_CHAIN_ID=${CHAIN_ID}) -> ${BENCH_RESULTS_DIR}/deployments-bench.json")
  12  IAM + bucket   gcloud secrets add-iam-policy-binding ${BENCH_TXGEN_MASTER_SECRET}|${BENCH_TXGEN_SEED_SECRET} --member=serviceAccount:${SERVICE_ACCOUNT} --role=roles/secretmanager.secretAccessor
                     gcloud storage buckets create gs://${BENCH_BUCKET} --location=${BENCH_BUCKET_LOCATION}; update --update-labels=${BENCH_LABELS}
  13  fund           benchmark/benchmark-blast.sh fund --yes   (bench-funder, --prepare $(( 10 * BENCH_SENDERS )) senders from $(( BENCH_RUN_INDEX * 100000 )))
  14  blast          benchmark/benchmark-blast.sh run --yes    (bench-blaster-01..10, start now+${BENCH_START_DELAY_SECS}s, ${BENCH_DURATION_SECS}s mixed, chaos on v05 + observer)
  15  collect        benchmark/benchmark-blast.sh collect --yes; python3 ${COLLECT_METRICS_PY} --manifest ${BENCH_RESULTS_DIR}/manifest.json --out ${BENCH_RESULTS_DIR}/metrics.json
                     tools/cert-rate.py + tools/block-rate.py -> results/${BENCH_RUN_ID}/analysis/; INDEX.md + CHECKSUMS.sha256 (non-fatal; results/ is the only copy)
  16  teardown       $([ "${WITH_TEARDOWN}" -eq 1 ] && echo "benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" || echo "SKIPPED (pass --with-teardown; or run benchmark-teardown.sh later)")

Scope: $([ -n "${ONLY}" ] && echo "ONLY step ${ONLY}" || echo "steps ${FROM}..${LAST_STEP}")
EOP
    echo "Local checks (no GCP calls):"
    local ok=1
    bench_require_tools gcloud cast jq python3 curl docker git || ok=0
    if grep -qi "${BENCH_TXGEN_MASTER_ADDRESS}" "${GENESIS_WORKSPACE}/testnet_accounts.yaml" 2>/dev/null; then
        echo "    ✓ accounts file funds the bench txgen master"; else echo "    ✗ accounts file lacks ${BENCH_TXGEN_MASTER_ADDRESS}"; ok=0; fi
    if [ -d "${BENCH_DIR}/genesis" ] && [ -n "$(ls -A "${BENCH_DIR}/genesis" 2>/dev/null)" ]; then
        echo "    ✗ ${BENCH_DIR}/genesis is not empty"; ok=0; else echo "    ✓ benchmark/genesis empty"; fi
    if ( bench_require_txgen_image ) 2>/dev/null; then echo "    ✓ image pinned: ${BENCH_TXGEN_IMAGE}"
    else echo "    ✗ image: ${BENCH_TXGEN_IMAGE_ERROR:-tag of '${BENCH_TXGEN_IMAGE}' is not blast-v2-<sha>}"; ok=0; fi
    [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] && echo "    ✓ ${BENCH_TXGEN_CLOUDBUILD}" || { echo "    ✗ ${BENCH_TXGEN_CLOUDBUILD} missing (step 1)"; ok=0; }
    [ -f "${BENCH_TXGEN_CONFIG}" ] && echo "    ✓ ${BENCH_TXGEN_CONFIG}" || echo "    · ${BENCH_TXGEN_CONFIG} not present yet (needed by steps 13-14)"
    [ -f "${COLLECT_METRICS_PY}" ] && echo "    ✓ ${COLLECT_METRICS_PY}" || echo "    · ${COLLECT_METRICS_PY} not present yet (needed by step 15)"
    [ "${ok}" -eq 1 ] || echo "    (fix the ✗ items before --yes)"
    echo ""
    echo "DRY RUN — re-run with --yes to execute."
}

# ================================ output copy (--yes) ===================================
# deploy_log_start — from here on, everything the script prints (stdout and stderr merged, so
# the order holds) also goes to ${BENCH_RESULTS_DIR}/logs/deploy-<UTC stamp>.log. Each invocation
# creates its own file (noclobber), so a --from resume never truncates an earlier log. tee reads
# a FIFO as a background job, not a process substitution: bash 3.2 cannot wait for the latter.
# It ignores HUP INT TERM PIPE and ends at EOF, once this script and every child writing to the
# FIFO have exited: after a closed terminal or a TERM to the process group it keeps copying what
# the step-14 blast prints during its exit cleanup, and a write to a gone terminal fails inside
# tee instead of ending it (the blast's own copy ignores a dead FIFO the same way).
deploy_log_start() {
    local dir="${BENCH_RESULTS_DIR}/logs" stamp f n=0 tmp
    mkdir -p "${dir}"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    f="${dir}/deploy-${stamp}.log"
    until ( set -C; : > "${f}" ) 2>/dev/null; do
        [ -e "${f}" ] || bench_die "cannot create ${f}"
        n=$((n + 1)); f="${dir}/deploy-${stamp}-${n}.log"
    done
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/bench-deploy.XXXXXX")"
    mkfifo "${tmp}/out"
    ( trap '' HUP INT TERM PIPE; exec tee -a "${f}" ) < "${tmp}/out" &
    DEPLOY_TEE_PID=$!
    trap deploy_log_stop EXIT
    exec > "${tmp}/out" 2>&1
    rm -f "${tmp}/out"; rmdir "${tmp}"
    echo "output copied to ${f}"
}

# deploy_log_stop — EXIT trap: close our end of the FIFO so tee reads EOF, wait up to 10 s for it
# to drain (a leftover child still holding stdout must not block the exit), keep the status.
deploy_log_stop() {
    local rc=$? n=0
    exec >&- 2>&-
    while kill -0 "${DEPLOY_TEE_PID}" 2>/dev/null && [ "${n}" -lt 100 ]; do sleep 0.1; n=$((n + 1)); done
    exit "${rc}"
}

# ================================ runner ================================================
if [ -n "${PRINT_POSTCONFIG}" ]; then
    bench_index_of "${PRINT_POSTCONFIG}" >/dev/null || bench_die "${PRINT_POSTCONFIG} is not a bench instance"
    postconfig_script "${PRINT_POSTCONFIG}"
    exit 0
fi
if [ -n "${PRINT_OBS}" ]; then
    _i="$(bench_index_of "${PRINT_OBS}")" || bench_die "${PRINT_OBS} is not a bench instance"
    obs_script "${PRINT_OBS}" "$(tn_region_from_zone "${ZONES[$_i]}")" "PLACEHOLDER-TOKEN"
    exit 0
fi
if [ "${BENCH_APPLY}" = "1" ]; then deploy_log_start; fi
echo "=========================================="
echo "benchmark deploy — run ${BENCH_RUN_ID}, project ${PROJECT_ID}, chain ${CHAIN_ID}"
echo "=========================================="
if [ "${CONFIRM}" -ne 1 ]; then
    print_plan
    exit 0
fi

# --- fail-fast gate for --yes runs (M1): everything a LATER step needs is checked now, so a
# run cannot die at step 13 an hour after the fleet came up.
in_range() { if [ -n "${ONLY}" ]; then [ "${ONLY}" -eq "$1" ]; else [ "${FROM}" -le "$1" ]; fi; }
gate() {
    echo ">>> gate: prerequisites of the selected steps"
    local deps="${BENCH_DEPLOYMENTS_JSON:-${BENCH_RESULTS_DIR}/deployments-bench.json}" bad=0
    if in_range 1 || in_range 13 || in_range 14; then
        ( bench_require_txgen_image ) || bad=1
        [ -n "${BENCH_TXGEN_IMAGE}" ] && echo "    image ${BENCH_TXGEN_IMAGE}"
    fi
    if in_range 1; then
        [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] && echo "    ✓ ${BENCH_TXGEN_CLOUDBUILD}" || { echo "    ✗ missing ${BENCH_TXGEN_CLOUDBUILD}" >&2; bad=1; }
    fi
    if in_range 13 || in_range 14; then
        [ -f "${BENCH_TXGEN_CONFIG}" ] && echo "    ✓ ${BENCH_TXGEN_CONFIG}" || { echo "    ✗ missing ${BENCH_TXGEN_CONFIG}" >&2; bad=1; }
        if [ "${WITH_CONTRACTS}" -eq 1 ] && in_range 11; then
            echo "    · ${deps} will be produced by step 11"
        elif [ -f "${deps}" ]; then
            echo "    ✓ ${deps}"
        else
            echo "    ✗ missing ${deps} and step 11 will not produce it (pass --with-contracts with a range that includes 11)" >&2; bad=1
        fi
    fi
    if in_range 7 || in_range 9; then
        local probs
        probs="$(bench_node_params_problems)"
        if [ -n "${probs}" ]; then
            printf '%s\n' "${probs}" | sed 's/^/    ✗ /' >&2
            bad=1
        else
            echo "    ✓ every node's effective parameters pass the node's startup checks${BENCH_NODE_PARAM_OVERRIDES:+ (overrides: ${BENCH_NODE_PARAM_OVERRIDES})}"
        fi
    fi
    [ "${bad}" -eq 0 ] || bench_die "prerequisites missing — nothing was started"
    gate_node_image
}

# gate_node_image — pin the node image before anything can deploy it. A run whose manifest pins
# one already (a resume) keeps it. Otherwise, when a selected step creates or starts nodes from
# it (0, 5 keygen, 6 genesis, 7 finalize), bench_node_image_probe examines DOCKER_IMAGE (dies on
# any mismatch) and BENCH_DOCKER_IMAGE / DOCKER_IMAGE become its <repo>@sha256:<digest>, which
# every later step and every sub-script (they re-source config.sh) then runs.
# A probe that refuses, or a build that cannot honour the delays, stops the run before any
# manifest is written, so the run id is not pinned to an image it can never use.
GATE_PROBED=0
gate_node_image() {
    local m forks
    if [ "${NODE_PIN_FROM_MANIFEST}" -eq 1 ]; then
        echo "    node image ${DOCKER_IMAGE} (pinned by this run's gate probe: manifest node_image_pinned)"
    elif in_range 0 || in_range 5 || in_range 6 || in_range 7; then
        bench_node_image_probe "${DOCKER_IMAGE}"
        export BENCH_DOCKER_IMAGE="${BENCH_NODE_IMAGE_PINNED}" DOCKER_IMAGE="${BENCH_NODE_IMAGE_PINNED}"
        GATE_PROBED=1
        echo "    ✓ node image pinned: ${DOCKER_IMAGE} (git ${BENCH_NODE_GIT_SHA}, forks ${BENCH_NODE_FORK_SCHEDULE})"
        fork_delay_check "${BENCH_NODE_FORK_SCHEDULE}"
        return 0
    else
        echo "    node image ${DOCKER_IMAGE} (no selected step deploys it — not probed)"
    fi
    # A resume: the same check on what this run recorded (its build and its delays).
    m="$(bench_manifest)"
    [ -f "${m}" ] || return 0
    forks="$(jq -r '.node_fork_schedule // empty' "${m}" 2>/dev/null || true)"
    [ -n "${forks}" ] && jq -e '.consensus_parameters | type == "object"' "${m}" >/dev/null 2>&1 || return 0
    fork_delay_check "${forks}"
}

# run_params_mhd — the smallest max_header_delay (ms) this invocation leaves any node with, and where
# it comes from, as "<ms> <source>". The fleet value: PARAMETERS_FILE when step 7 (which stages it)
# is selected or the manifest has none recorded, else manifest.consensus_parameters. A per-node
# override below it wins: one in BENCH_NODE_PARAM_OVERRIDES, or one the manifest records as applied
# (consensus_parameters.overrides), so a single node cannot slip past fork_delay_check. "<ms>" is ""
# when unknown.
run_params_mhd() {
    local m v="" src="" i o inst
    m="$(bench_manifest)"
    if ! in_range 7 && [ -f "${m}" ]; then
        v="$(jq -r '.consensus_parameters.max_header_delay_ms // empty' "${m}" 2>/dev/null || true)"
        [ -z "${v}" ] || src="manifest consensus_parameters"
    fi
    if [ -z "${src}" ]; then v="$(bench_params_ms "${PARAMETERS_FILE}" max_header_delay)"; src="${PARAMETERS_FILE}"; fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        o="$(bench_dur_ms "$(bench_node_override "${i}" max_header_delay)")"
        if [ -n "${o}" ] && { [ -z "${v}" ] || [ "${o}" -lt "${v}" ]; }; then
            v="${o}"; src="BENCH_NODE_PARAM_OVERRIDES (${INSTANCE_NAMES[$i]})"
        fi
    done
    if [ -f "${m}" ]; then
        while read -r inst o; do
            o="$(bench_dur_ms "${o}")"
            if [ -n "${o}" ] && { [ -z "${v}" ] || [ "${o}" -lt "${v}" ]; }; then
                v="${o}"; src="manifest consensus_parameters.overrides (${inst})"
            fi
        done <<EOF
$(jq -r '.consensus_parameters.overrides // {} | to_entries[] | select(.value.max_header_delay != null) | "\(.key) \(.value.max_header_delay)"' "${m}" 2>/dev/null || true)
EOF
    fi
    printf '%s %s' "${v}" "${src}"
}

# fork_delay_check <fork schedule> — die when the nodes would run sub-second header delays on a
# build that is not subsecond-from-genesis: such a build stamps whole-second timestamps, cannot
# honour them, and the fleet would be spent measuring nothing.
fork_delay_check() {
    local forks="$1" r mhd src way
    r="$(run_params_mhd)"; mhd="${r%% *}"; src="${r#* }"
    case "${mhd}" in ''|*[!0-9]*) return 0 ;; esac
    [ "${mhd}" -lt 1000 ] && [ "${forks}" != "subsecond-from-genesis" ] || return 0
    way="a sub-second image (one the probe reports as subsecond-from-genesis) via BENCH_DOCKER_IMAGE"
    [ "${NODE_PIN_FROM_MANIFEST}" -eq 0 ] || way="${way} — on a new run: this run is pinned to ${DOCKER_IMAGE}"
    bench_die "node image ${DOCKER_IMAGE} has fork schedule ${forks}, but max_header_delay is ${mhd} ms (${src}).
   A build without sub-second timestamps from genesis stamps whole seconds and cannot honour
   sub-second delays; running it would waste the fleet. Either:
     - ${way}, or
     - BENCH_PARAMETERS_FILE=<a parameters file with delays >= 1 s> (e.g. common/parameters.yaml: 3s/1s/1s), with step 7 selected so it is staged"
}

# gate_manifest — record what the gate established: the node image probe (when it ran in this
# invocation) and the consensus parameters. PARAMETERS_FILE reaches the nodes at step 7
# (devnet-finalize.sh stages it), so consensus_parameters is (re)recorded only when step 7 is
# selected; otherwise the recorded values stay (a warning when the file has changed since), and
# step 9 checks the nodes against them.
gate_manifest() {
    local m have now
    m="$(bench_manifest)"
    if [ "${GATE_PROBED}" -eq 1 ]; then
        bench_node_probe_manifest || bench_die "could not record the node image probe in ${m}"
        have="$(jq -r '.docker_image // empty' "${m}")"
        if [ "${have}" != "${DOCKER_IMAGE}" ]; then   # an older run's manifest, resumed
            bench_manifest_note "docker_image ${have:-unset} -> ${DOCKER_IMAGE} (gate probe, $(bench_now_iso))"
            bench_manifest_jq --arg i "${DOCKER_IMAGE}" '.docker_image = $i'
        fi
        echo "    ✓ manifest: node_image_pinned, node_git_sha, node_fork_schedule, node_probe"
    fi
    have="$(jq -r '.consensus_parameters.sha256 // empty' "${m}")"
    if in_range 7; then
        bench_consensus_params_manifest || bench_die "could not record ${PARAMETERS_FILE} in ${m}"
        echo "    ✓ manifest: consensus_parameters $(jq -c '.consensus_parameters | {file, max_header_delay_ms, min_header_delay_ms, max_batch_delay_ms}' "${m}")"
    elif [ -n "${have}" ]; then
        now="$(bench_file_sha256 "${PARAMETERS_FILE}" || true)"
        [ "${have}" = "${now}" ] || bench_warn "${PARAMETERS_FILE} changed since step 7 staged it (sha256 ${have} recorded, ${now:-unreadable} now) — keeping the recorded consensus_parameters"
    else
        echo "    · consensus_parameters not recorded yet (recorded when a range including step 7 runs)"
    fi
    # The per-node part is applied by step 9, so it is recorded whenever step 9 runs (with step 7, above).
    if ! in_range 7 && in_range 9; then
        bench_node_params_manifest || bench_die "could not record the per-node parameters in ${m}"
    fi
    if in_range 7 || in_range 9; then
        echo "    ✓ manifest: consensus_parameters.overrides $(jq -c '.consensus_parameters.overrides' "${m}"), node_startup[*].log_filter ${BENCH_NODE_LOG_FILTER:-null}"
    elif [ -f "${m}" ] && [ "$(jq -c '.consensus_parameters.overrides // {}' "${m}" 2>/dev/null || true)" != "$(bench_node_overrides_json)" ]; then
        bench_warn "BENCH_NODE_PARAM_OVERRIDES differs from what step 9 applied ($(jq -c '.consensus_parameters.overrides // {}' "${m}")); it takes effect only when step 9 runs"
    fi
}

gate
# Creates manifest.json, or keeps the existing one (a resume). A failure is fatal, not hidden.
bench_manifest_init || bench_die "cannot initialise $(bench_manifest)"
jq -e '.schema == "tn-bench-manifest/v1"' "$(bench_manifest)" >/dev/null 2>&1 \
    || bench_die "$(bench_manifest) is not a readable tn-bench-manifest/v1 file — inspect it before re-running"
gate_manifest
run_step() {
    local n="$1"
    echo ""
    echo "##########################################"
    "step_${n}"
    bench_manifest_ts "step_${n}_done"
    echo "## step ${n} done"
}
if [ -n "${ONLY}" ]; then
    run_step "${ONLY}"
else
    n="${FROM}"
    while [ "${n}" -le "${LAST_STEP}" ]; do run_step "${n}"; n=$((n + 1)); done
fi
echo ""
echo "=========================================="
echo "benchmark deploy: $([ -n "${ONLY}" ] && echo "step ${ONLY}" || echo "steps ${FROM}..${LAST_STEP}") complete — ${BENCH_RESULTS_DIR}"
echo "=========================================="
