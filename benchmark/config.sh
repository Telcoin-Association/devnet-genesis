#!/usr/bin/env bash
#
# benchmark/config.sh — the BENCHMARK deploy profile. A throwaway 10-validator +
# 1-observer Telcoin Network fleet in tn-devnet that is stood up, blasted, measured
# and torn down without touching the live devnet (validator-{1..4}-devnet,
# observer-5-devnet, obs-devnet, txgen-devnet, devnet-indexer).
#
# It sources the devnet ../config.sh first (so every shared constant — PROJECT_ID,
# DOCKER_IMAGE, SERVICE_ACCOUNT, the OBS_* endpoints the bench metrics ship to — is
# inherited) and then OVERRIDES everything that identifies a fleet. The shared drivers
# pick it up through CONFIG_FILE, which only benchmark/*.sh set (in-process):
#
#   CONFIG_FILE=benchmark/config.sh   devnet-lib.sh, common/create-instances.sh,
#                                     common/genesis.sh all honour it
#
# Never `source` this file in an interactive shell: its exports (TN_OBS_ENABLE_*=0,
# CHAIN_ID, ...) would leak into a later devnet run from that shell. It refuses to.
#
# Required: BENCH_RUN_ID (rYYYYMMDD-HHMM, e.g. r20260923-0100). It names the results
# dir, the GCS bucket and the bench-run label on every resource.
#
# Default fleet shape ("c3-hdb"): c3-highcpu-8 + 100 GB hyperdisk-balanced provisioned at
# 20000 IOPS / 800 MiB/s, consensus timing from benchmark/consensus-parameters.yaml. The e2
# baseline ("A") is BENCH_MACHINE_TYPE=e2-custom-4-8192 BENCH_NODE_DISK_TYPE=pd-ssd.

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# --- refuse to be loaded where it could do damage ------------------------------
# 1) interactive shells (see header). 2) any caller that is not on the ALLOWLIST below:
# benchmark/benchmark-*.sh plus exactly the shared drivers benchmark-deploy.sh invokes.
# Everything else (the devnet-only drivers that manage DNS, the LB, the obs VM, the devnet
# VPC rules, txgen-devnet, updates, wgvpn, ...) is refused, including scripts added later.
# devnet-observability.sh is deliberately NOT allowed: step 8 relabels Alloy in the same
# session as setup-observability.sh, which the devnet driver cannot do (it would ship
# bench metrics labelled network="devnet" to obs-devnet).
case "$-" in
    *i*)
        if [ "${BENCH_ALLOW_INTERACTIVE:-0}" != "1" ]; then
            echo "❌ benchmark/config.sh must not be sourced in an interactive shell (its exports would leak into devnet runs)." >&2
            return 1 2>/dev/null || exit 1
        fi ;;
esac
_bench_caller="$(basename -- "${0:-}")"
case "${_bench_caller}" in
    benchmark-deploy.sh|benchmark-firewall.sh|benchmark-blast.sh|benchmark-teardown.sh|\
    devnet-keygen.sh|devnet-genesis-build.sh|devnet-finalize.sh|devnet-contracts.sh|\
    create-instances.sh|genesis.sh|copy-committee.sh) ;;
    *)
        echo "❌ '${_bench_caller}' is not allowed to run with CONFIG_FILE=benchmark/config.sh." >&2
        echo "   The benchmark profile is driven only by benchmark/benchmark-*.sh (and the shared drivers they call)." >&2
        exit 1 ;;
esac
unset _bench_caller

# --- inherit the devnet constants, then override the fleet identity -------------
# shellcheck source=../config.sh
source "${BENCH_DIR}/../config.sh"

export TN_PROFILE="benchmark"
export BENCH_DIR

# Run id: required, lower-case (it becomes a GCS bucket suffix and a label value).
if [ -z "${BENCH_RUN_ID:-}" ]; then
    echo "❌ BENCH_RUN_ID is required (format rYYYYMMDD-HHMM, e.g. BENCH_RUN_ID=r$(date -u +%Y%m%d-%H%M))." >&2
    exit 1
fi
case "${BENCH_RUN_ID}" in
    r*[!a-z0-9-]*|[!r]*) echo "❌ BENCH_RUN_ID='${BENCH_RUN_ID}' must start with 'r' and use only [a-z0-9-]." >&2; exit 1 ;;
esac
if [ "${#BENCH_RUN_ID}" -gt 40 ]; then
    echo "❌ BENCH_RUN_ID is longer than 40 chars." >&2; exit 1
fi
export BENCH_RUN_ID

#
# Fleet: 10 validators + 1 observer, one validator in each of ten regions (APAC-weighted), the
# observer beside validator-01 in us-west2-a. ZONES[0] also hosts the funder and the IAP tunnel;
# index 2 (Sydney) is BENCH_LAG_IDX's default and index 4 (Montreal) CHAOS_KILL_IDX's.
# Two planned zones cannot host c3-highcpu-8 (tasks/regions/evaluation.md, 2026-10-06):
# asia-southeast2 (Jakarta) offers it in no zone, so validator-07 runs in Singapore
# (asia-southeast1-b); asia-south1 (Mumbai) offers it only in zone c. Alternates checked there:
# asia-northeast1-c (v04), asia-east1-a (v08), asia-northeast3-b (v09).
# Spelled out (bash 3.2 has no brace-expansion-with-padding worth trusting in an array literal).
#
export INSTANCE_NAMES=("bench-validator-01" "bench-validator-02" "bench-validator-03" "bench-validator-04" "bench-validator-05" "bench-validator-06" "bench-validator-07" "bench-validator-08" "bench-validator-09" "bench-validator-10" "bench-observer-11")
export NODE_ROLES=("validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "observer")
export ZONES=("us-west2-a" "europe-west2-b" "australia-southeast1-c" "asia-northeast1-b" "northamerica-northeast1-b" "europe-west4-a" "asia-southeast1-b" "asia-east2-a" "asia-northeast3-a" "asia-south1-c" "us-west2-a")
export NODE_NAMES=("bench01" "bench02" "bench03" "bench04" "bench05" "bench06" "bench07" "bench08" "bench09" "bench10" "bench11")
# From benchmark/.secrets/exec-keys.json (gitignored); validators 01-10, then observer 11.
export EXECUTION_ADDRESSES=("0xc7d975abd962345e9a6024aab692f6bf19140f03" "0x92862b13608e00925551233f21b6f44f6acc7f91" "0x3205c561e8183aae91ef1ab26a1db3fea83bb120" "0x213aff13862c86b3159a9552cc2424b92f8cfcfc" "0x31faf1673f324c688fff60172099f944171d6ab3" "0xe47fbdfdedadd35501eb7c3f38884238bf251103" "0x58114823ab8b21c4162cc28472ff2a6810e123e2" "0x8e7abe6740a452ade8f02a1f005002976e77fb0a" "0xc2f61840713de91b60e5b5c404350d705877911e" "0x52791a4607b5944ec0da0828d0ee78205b208ef1" "0xe88cc26183754978af15a67c1597324eec9ec806")

# Ephemeral external IPs: nothing reserved, nothing to release at teardown.
export USE_STATIC_IPS=0
export STATIC_IP_NAMES=()

# Genesis identity. 32286 is NOT devnet's 32285, so the chains can never be confused
# (and tn-contracts routes it to deployments-testnet.json — see benchmark-deploy.sh step 11).
export CHAIN_ID=32286
export EPOCH_DURATION_SECS=1200

# Transport: IAP only. No overlay: the bench nodes never join the WireGuard wheel, so
# TN_USE_VPN must be 0 (devnet's =1 installs a gcloud shim that drops --tunnel-through-iap).
export TN_USE_VPN=0
export TN_SSH_TRANSPORT=iap
# Skip the overlay branch of common/create-instances.sh: wg-config.sh only sources the
# coords file when `[ -f ]` holds, which /dev/null (a char device) never satisfies, and
# the WG_ENABLED gate needs both of these non-empty.
export WG_HUB_COORDS_FILE=/dev/null
unset WG_HUB_ENDPOINT WG_HUB_PUBKEY

# Node image. ../config.sh exports the live devnet's unconditionally (an env DOCKER_IMAGE never
# survives it), so the bench pins its own through BENCH_DOCKER_IMAGE: a tag or repo@sha256:<digest>.
export DOCKER_IMAGE="${BENCH_DOCKER_IMAGE:-${DOCKER_IMAGE}}"

# Machines. Default c3-highcpu-8 + hyperdisk-balanced (the c3-hdb shape of the 29 Sep run);
# override per sizing sweep. e2/n1 cannot attach hyperdisk, so they need BENCH_NODE_DISK_TYPE=pd-ssd.
export MACHINE_TYPE="${BENCH_MACHINE_TYPE:-c3-highcpu-8}"
export NODE_DISK_SIZE="${BENCH_NODE_DISK_SIZE:-100}"   # GB boot disk (create-instances.sh --create-disk size=)
export NODE_DISK_TYPE="${BENCH_NODE_DISK_TYPE:-hyperdisk-balanced}"
# Provisioned IOPS / throughput (MiB/s): hyperdisk only. On hyperdisk-balanced an UNSET knob
# defaults to 20000 / 800; an explicitly empty one (BENCH_NODE_DISK_IOPS=) is not passed to
# gcloud, so the disk gets the type's default. On any other type both default to empty.
case "${NODE_DISK_TYPE}" in
    hyperdisk-balanced)
        export NODE_DISK_IOPS="${BENCH_NODE_DISK_IOPS-20000}"
        export NODE_DISK_THROUGHPUT="${BENCH_NODE_DISK_THROUGHPUT-800}" ;;
    *)   # other hyperdisk-* types provision only IOPS (extreme) or only throughput: set them explicitly
        export NODE_DISK_IOPS="${BENCH_NODE_DISK_IOPS:-}"
        export NODE_DISK_THROUGHPUT="${BENCH_NODE_DISK_THROUGHPUT:-}" ;;
esac
# Fleet label for the manifest/report, derived from the machine + disk shape: A = e2 baseline
# on pd-ssd, B = c3 on pd-ssd, <family>-hdb on hyperdisk-balanced (c3-hdb, n4-hdb), else the
# machine type. An explicit BENCH_FLEET always wins. (The first c3 run was mislabelled "A".)
case "${MACHINE_TYPE}:${NODE_DISK_TYPE}" in
    e2-custom-4-8192:pd-ssd) _bench_fleet="A" ;;
    c3-highcpu-8:pd-ssd)     _bench_fleet="B" ;;
    *:hyperdisk-balanced)    _bench_fleet="${MACHINE_TYPE%%-*}-hdb" ;;
    *)                       _bench_fleet="${MACHINE_TYPE}" ;;
esac
export BENCH_FLEET="${BENCH_FLEET:-${_bench_fleet}}"
unset _bench_fleet
# Tag + labels. ONLY bench-node: none of devnet's tags (validator, http-server,
# https-server, lb-health-check), so no devnet VPC rule, LB backend or health check can
# ever select a bench node. create-instances.sh appends tn-role=<role> per node.
export INSTANCE_TAGS="bench-node"
export INSTANCE_LABELS="benchmark=1,network=bench,bench-run=${BENCH_RUN_ID}"

# No public names: nothing resolves under .invalid (RFC 6761), so no cert, no DNS, no Caddy.
export BASE_DOMAIN="bench.invalid"
export CERT_DOMAINS=("${BASE_DOMAIN}")
export HEALTHCHECK_MONITOR_SRC=""
export TN_KUMA_SRC=""

# Observability: METRICS ONLY, shipped to obs-devnet (the OBS_* endpoints are inherited).
# No logs (obs-devnet's Loki disk is devnet's), no health listener exposure, no dashboards.
export TN_OBS_ENABLE_LOGS=0
export TN_OBS_ENABLE_METRICS=1
export TN_OBS_ENABLE_HEALTH=0
export TN_OBS_ENABLE_DASHBOARD=0
export TN_ADMIN_DASHBOARD=0
export BENCH_PROM_NETWORK_LABEL="bench"      # TN_CHAIN on the node -> network= and chain= labels
export BENCH_GRAFANA_URL="https://${OBS_HOSTNAME}"
export BENCH_PROM_DATASOURCE_UID="prometheus"

# Genesis workspace: everything the build reads/writes lives under benchmark/.
export GENESIS_WORKSPACE="${BENCH_DIR}"
export GENESIS_FILE="${GENESIS_WORKSPACE}/genesis/genesis.yaml"
export COMMITTEE_FILE="${GENESIS_WORKSPACE}/genesis/committee.yaml"
# Consensus timing. The node reads parameters.yaml from its datadir, staged from this file by
# devnet-finalize.sh; genesis.yaml carries no header delays. Never benchmark/parameters.yaml:
# `telcoin genesis` writes that name into the workspace at deploy step 6 (self-check below).
export PARAMETERS_FILE="${BENCH_PARAMETERS_FILE:-${BENCH_DIR}/consensus-parameters.yaml}"
# Absolute: the drivers re-source this file after changing directory.
case "${PARAMETERS_FILE}" in /*) ;; *) PARAMETERS_FILE="$(pwd -P)/${PARAMETERS_FILE}" ;; esac
export PARAMETERS_FILE
# Own BLS keystore passphrase (gitignored); benchmark-deploy.sh step 0 creates it if absent.
export TN_BLS_PASSPHRASE_FILE="${BENCH_DIR}/.secrets/bls-passphrase"

# RPC for the operator-side tools (cast, devnet-contracts.sh): the IAP tunnel to
# bench-validator-01:8545 that benchmark-deploy.sh opens on this local port.
export BENCH_TUNNEL_PORT=18545
export RPC_URL="http://localhost:${BENCH_TUNNEL_PORT}"

# Load generator (COS blasters). BENCH_TXGEN_IMAGE, not TXGEN_IMAGE: devnet-txgen.sh
# reads ${TXGEN_IMAGE:-...} as its VM OS image, so exporting that name here would leak.
export BENCH_TXGEN_REPO="${BENCH_TXGEN_REPO:-$(cd "${REPO_ROOT}/.." && pwd)/tn-transaction-generator}"
# The image is pinned to a generator commit: :blast-v2-<sha7>. The old :blast tag is the
# 2026-08-28 harness without the blast-v2 CLI, so it is never a default. BENCH_TXGEN_SHA may be
# given explicitly; otherwise it is the generator checkout's HEAD, and only when the tree is
# clean (a dirty tree would build an image that no commit describes). A missing SHA does not
# stop this file from loading (teardown/firewall need no image); it leaves BENCH_TXGEN_IMAGE
# empty with the reason in BENCH_TXGEN_IMAGE_ERROR, and bench_require_txgen_image refuses.
export BENCH_TXGEN_IMAGE_REPO="us-west2-docker.pkg.dev/tn-devnet/txgen/tn-transaction-generator"
export BENCH_TXGEN_IMAGE_ERROR=""
if [ -z "${BENCH_TXGEN_SHA:-}" ]; then
    if ! git -C "${BENCH_TXGEN_REPO}" rev-parse --git-dir >/dev/null 2>&1; then
        BENCH_TXGEN_IMAGE_ERROR="${BENCH_TXGEN_REPO} is not a git checkout; set BENCH_TXGEN_SHA"
    elif [ -n "$(git -C "${BENCH_TXGEN_REPO}" status --porcelain --untracked-files=no 2>/dev/null)" ] \
      || [ -n "$(git -C "${BENCH_TXGEN_REPO}" ls-files --others --exclude-standard -- src Cargo.toml Cargo.lock Dockerfile build.rs 2>/dev/null)" ]; then
        BENCH_TXGEN_IMAGE_ERROR="${BENCH_TXGEN_REPO} has uncommitted changes; commit them or set BENCH_TXGEN_SHA"
    else
        BENCH_TXGEN_SHA="$(git -C "${BENCH_TXGEN_REPO}" rev-parse --short=7 HEAD 2>/dev/null || true)"
        [ -n "${BENCH_TXGEN_SHA}" ] || BENCH_TXGEN_IMAGE_ERROR="cannot read HEAD of ${BENCH_TXGEN_REPO}"
    fi
fi
export BENCH_TXGEN_SHA="${BENCH_TXGEN_SHA:-}"
export BENCH_TXGEN_TAG="${BENCH_TXGEN_SHA:+blast-v2-${BENCH_TXGEN_SHA}}"
export BENCH_TXGEN_IMAGE="${BENCH_TXGEN_IMAGE:-${BENCH_TXGEN_TAG:+${BENCH_TXGEN_IMAGE_REPO}:${BENCH_TXGEN_TAG}}}"
export BENCH_TXGEN_CLOUDBUILD="${BENCH_TXGEN_REPO}/cloudbuild.yaml"
export BENCH_TXGEN_CONFIG="${BENCH_TXGEN_CONFIG:-${BENCH_TXGEN_REPO}/config.bench.toml}"
export BENCH_TXGEN_MASTER_ADDRESS="0xb1F7fB246DDF3F621442368e4122b087b1Ea3C8E"
export BENCH_TXGEN_MASTER_SECRET="bench-txgen-master-key"
export BENCH_TXGEN_SEED_SECRET="bench-txgen-children-seed"
# Blaster machine types, tried in this order: a create that fails because the zone is out of the
# type (a stockout) is retried at once on the next one, and the type used is recorded as
# manifest blasters[].machine_type. Keep them one shape (2 vCPU). BENCH_BLASTER_MACHINE_TYPE=<type>
# pins a single type (no fallback) and wins over the list. Boot disk: BENCH_BLASTER_BOOT_DISK_GB of
# pd-balanced (SSD_TOTAL_GB quota). Both are read by benchmark-blast.sh create_vm and deploy step 0.
[ -z "${BENCH_BLASTER_MACHINE_TYPE:-}" ] || BENCH_BLASTER_MACHINE_TYPES="${BENCH_BLASTER_MACHINE_TYPE}"
export BENCH_BLASTER_MACHINE_TYPES="${BENCH_BLASTER_MACHINE_TYPES:-e2-standard-2 n2-standard-2 n2d-standard-2}"
case "${BENCH_BLASTER_MACHINE_TYPES}" in
    ''|' '*|*' '|*'  '*|*[!a-z0-9\ -]*) echo "❌ benchmark/config.sh: BENCH_BLASTER_MACHINE_TYPES='${BENCH_BLASTER_MACHINE_TYPES}' must be machine types separated by single spaces." >&2; exit 1 ;;
esac
export BENCH_BLASTER_BOOT_DISK_GB=20
export BENCH_SENDERS="${BENCH_SENDERS:-600}"            # per blaster
export BENCH_RUN_INDEX="${BENCH_RUN_INDEX:-0}"          # re-blast on the same fleet with fresh senders
export BENCH_WARMUP_SECS="${BENCH_WARMUP_SECS:-120}"
export BENCH_DURATION_SECS="${BENCH_DURATION_SECS:-2400}"
export BENCH_COOLDOWN_SECS="${BENCH_COOLDOWN_SECS:-180}"
export BENCH_PREAMBLE_SECS="${BENCH_PREAMBLE_SECS:-90}" # estimate of the generator's own preamble
export BENCH_START_DELAY_SECS="${BENCH_START_DELAY_SECS:-300}"
export BENCH_POLL_SECS="${BENCH_POLL_SECS:-240}"        # >= 240: IAP/serial polling lesson
# Boundary timing reads the registry and its preceding closing block over the RPC tunnel.
# BENCH_CHAOS_TIMING=mixed retains the original offsets from workload start.
# BENCH_CHAOS=0 skips all three.
export BENCH_CHAOS="${BENCH_CHAOS:-1}"
export BENCH_CHAOS_TIMING="${BENCH_CHAOS_TIMING:-epoch}"
export BENCH_CHAOS_MIN_LOAD_SECS="${BENCH_CHAOS_MIN_LOAD_SECS:-600}"
export BENCH_CHAOS_BEFORE_CLOSE_SECS="${BENCH_CHAOS_BEFORE_CLOSE_SECS:-59}"
export BENCH_CHAOS_DOWNTIME_SECS="${BENCH_CHAOS_DOWNTIME_SECS:-300}"
export BENCH_CHAOS_OBS_AFTER_BACK_SECS="${BENCH_CHAOS_OBS_AFTER_BACK_SECS:-300}"
export BENCH_CHAOS_KILL_AT_SECS="${BENCH_CHAOS_KILL_AT_SECS:-900}"
export BENCH_CHAOS_BACK_AT_SECS="${BENCH_CHAOS_BACK_AT_SECS:-1200}"
export BENCH_CHAOS_OBS_AT_SECS="${BENCH_CHAOS_OBS_AT_SECS:-1500}"
# Chaos timing (benchmark-blast.sh): each action's IAP session opens BENCH_CHAOS_STAGE_SECS before
# it is due and waits on the node's clock; no poll starts within BENCH_CHAOS_GUARD_SECS of a due
# action (a poll takes ~40 s; STAGE must stay below GUARD). BENCH_STALL_NOTE_SECS: the fleet's
# highest block flat this long in the mixed phase is noted (.commit_stalls), never an abort.
export BENCH_CHAOS_STAGE_SECS="${BENCH_CHAOS_STAGE_SECS:-30}"
export BENCH_CHAOS_GUARD_SECS="${BENCH_CHAOS_GUARD_SECS:-90}"
export BENCH_STALL_NOTE_SECS="${BENCH_STALL_NOTE_SECS:-60}"
export BENCH_STALL_NOTE_MAX_ROUNDS="${BENCH_STALL_NOTE_MAX_ROUNDS:-4}"   # rounds may rise by this much and still count as flat
# Lag injection (BENCH_LAG_INJECT=1): pause one validator's container at BENCH_LAG_AT_SECS after
# the mixed phase starts, for BENCH_LAG_PAUSE_SECS. BENCH_LAG_IDX is zero-based; the default 2
# (bench-validator-03) has its own blaster; with BENCH_CHAOS=1 it must not be the node chaos kills.
export BENCH_LAG_INJECT="${BENCH_LAG_INJECT:-0}"
export BENCH_LAG_IDX="${BENCH_LAG_IDX:-2}"
export BENCH_LAG_AT_SECS="${BENCH_LAG_AT_SECS:-300}"
export BENCH_LAG_PAUSE_SECS="${BENCH_LAG_PAUSE_SECS:-180}"
export BENCH_TRAP_WAIT_SECS="${BENCH_TRAP_WAIT_SECS:-300}"  # interrupted run: wait this long for DONE markers
# App contracts (benchmark-deploy.sh step 11): a throwaway worktree of the SAME tn-contracts
# checkout devnet-contracts.sh uses, on a bench/<run> branch that is never committed to.
export BENCH_CONTRACTS_SRC_DIR="${BENCH_CONTRACTS_SRC_DIR:-$(cd "${REPO_ROOT}/.." && pwd)/tn-contracts-devnet-relaunch}"
export BENCH_CONTRACTS_BASE_BRANCH="deploy/devnet-relaunch"
export BENCH_CONTRACTS_WORKTREE="${BENCH_DIR}/work/tn-contracts"
export BENCH_CONTRACTS_BRANCH="bench/${BENCH_RUN_ID}"
export BENCH_BUCKET="tn-devnet-bench-${BENCH_RUN_ID}"
export BENCH_BUCKET_LOCATION="${BENCH_BUCKET_LOCATION:-us-west2}"
export BENCH_FIREWALL_RULES=("bench-allow-consensus" "bench-allow-iap-rpc")
export BENCH_LABELS="benchmark=1,network=bench,bench-run=${BENCH_RUN_ID}"
# The only copy of a run: nothing is archived to a bucket. The teardown's local gate checks it holds
# every node's logs before anything is deleted (bench_local_gate_check); back results/ up by hand.
export BENCH_RESULTS_DIR="${BENCH_DIR}/results/${BENCH_RUN_ID}"
# Abort thresholds (benchmark-blast.sh watchers).
export BENCH_ABORT_DISK_PCT="${BENCH_ABORT_DISK_PCT:-85}"
export BENCH_ABORT_OBS_MEM_PCT="${BENCH_ABORT_OBS_MEM_PCT:-85}"
export BENCH_ABORT_STALL_SECS="${BENCH_ABORT_STALL_SECS:-120}"
# Certification outcome (recorded after collect and at teardown, never an abort): a validator that
# certified fewer than this % of its own headers in a window where it proposed >= 50 goes into
# manifest.cert_failures, gets a log snapshot, and the teardown's local gate requires its logs.
export BENCH_CERT_FAIL_PCT="${BENCH_CERT_FAIL_PCT:-90}"

# --- self-checks: a mis-edit here must fail before anything reaches GCP ---------
_bench_n="${#INSTANCE_NAMES[@]}"
for _bench_arr in "NODE_ROLES:${#NODE_ROLES[@]}" "ZONES:${#ZONES[@]}" "NODE_NAMES:${#NODE_NAMES[@]}" "EXECUTION_ADDRESSES:${#EXECUTION_ADDRESSES[@]}"; do
    if [ "${_bench_arr#*:}" -ne "${_bench_n}" ]; then
        echo "❌ benchmark/config.sh: ${_bench_arr%%:*} has ${_bench_arr#*:} entries, INSTANCE_NAMES has ${_bench_n}." >&2
        exit 1
    fi
done
for _bench_name in "${INSTANCE_NAMES[@]}"; do
    case "${_bench_name}" in
        bench-*) ;;
        *) echo "❌ benchmark/config.sh: instance '${_bench_name}' does not start with bench-." >&2; exit 1 ;;
    esac
done
if [ "${CHAIN_ID}" = "32285" ]; then
    echo "❌ benchmark/config.sh: CHAIN_ID is devnet's 32285." >&2; exit 1
fi
if [ "${GENESIS_WORKSPACE}" = "${REPO_ROOT}" ]; then
    echo "❌ benchmark/config.sh: GENESIS_WORKSPACE resolves to the devnet repo root." >&2; exit 1
fi
if [ "${INSTANCE_TAGS}" != "bench-node" ]; then
    echo "❌ benchmark/config.sh: INSTANCE_TAGS must be exactly bench-node." >&2; exit 1
fi
# Compared by canonical directory (relative, ../ and symlinked-dir spellings); need not exist yet.
_bench_pdir="$(cd "$(dirname -- "${PARAMETERS_FILE}")" 2>/dev/null && pwd -P)"
if [ -n "${_bench_pdir}" ] && [ "${_bench_pdir}/$(basename -- "${PARAMETERS_FILE}")" = "$(cd "${BENCH_DIR}" && pwd -P)/parameters.yaml" ]; then
    echo "❌ benchmark/config.sh: PARAMETERS_FILE='${PARAMETERS_FILE}' resolves to benchmark/parameters.yaml, which \`telcoin genesis\` overwrites at deploy step 6; use benchmark/consensus-parameters.yaml." >&2; exit 1
fi
if [ ! -f "${PARAMETERS_FILE}" ] || [ ! -r "${PARAMETERS_FILE}" ]; then
    echo "❌ benchmark/config.sh: PARAMETERS_FILE='${PARAMETERS_FILE}' is not a readable regular file." >&2; exit 1
fi
case "${MACHINE_TYPE}:${NODE_DISK_TYPE}" in
    e2-*:hyperdisk-*|n1-*:hyperdisk-*)
        echo "❌ benchmark/config.sh: MACHINE_TYPE='${MACHINE_TYPE}' cannot attach a ${NODE_DISK_TYPE} disk; set BENCH_NODE_DISK_TYPE=pd-ssd." >&2; exit 1 ;;
esac
for _bench_knob in NODE_DISK_IOPS NODE_DISK_THROUGHPUT; do
    case "${!_bench_knob}" in
        '') continue ;;
        *[!0-9]*|0*) echo "❌ benchmark/config.sh: BENCH_${_bench_knob}='${!_bench_knob}' must be a positive integer." >&2; exit 1 ;;
    esac
    case "${NODE_DISK_TYPE}" in
        hyperdisk-*) ;;
        *) echo "❌ benchmark/config.sh: BENCH_${_bench_knob} is set but BENCH_NODE_DISK_TYPE='${NODE_DISK_TYPE}'; provisioned IOPS/throughput need a hyperdisk-* type." >&2; exit 1 ;;
    esac
done
for _bench_knob in BENCH_CHAOS BENCH_LAG_INJECT; do
    case "${!_bench_knob}" in
        0|1) ;;
        *) echo "❌ benchmark/config.sh: ${_bench_knob}='${!_bench_knob}' must be 0 or 1." >&2; exit 1 ;;
    esac
done
for _bench_knob in BENCH_LAG_IDX BENCH_LAG_AT_SECS; do
    case "${!_bench_knob}" in
        ''|*[!0-9]*|0?*) echo "❌ benchmark/config.sh: ${_bench_knob}='${!_bench_knob}' must be a non-negative integer." >&2; exit 1 ;;
    esac
done
case "${BENCH_LAG_PAUSE_SECS}" in
    ''|*[!0-9]*|0*) echo "❌ benchmark/config.sh: BENCH_LAG_PAUSE_SECS='${BENCH_LAG_PAUSE_SECS}' must be a positive integer." >&2; exit 1 ;;
esac
if [ "${BENCH_LAG_IDX}" -ge "${_bench_n}" ] || [ "${NODE_ROLES[$BENCH_LAG_IDX]}" != "validator" ]; then
    echo "❌ benchmark/config.sh: BENCH_LAG_IDX=${BENCH_LAG_IDX} (${INSTANCE_NAMES[$BENCH_LAG_IDX]:-no such node}) is not a validator." >&2; exit 1
fi
# 4 = CHAOS_KILL_IDX in benchmark-blast.sh (bench-validator-05); keep the two in step.
if [ "${BENCH_CHAOS}" = "1" ] && [ "${BENCH_LAG_IDX}" -eq 4 ]; then
    echo "❌ benchmark/config.sh: BENCH_LAG_IDX=4 (${INSTANCE_NAMES[4]}) is the node the chaos schedule kills; pick another validator or set BENCH_CHAOS=0." >&2; exit 1
fi
unset _bench_n _bench_arr _bench_name _bench_knob _bench_pdir
