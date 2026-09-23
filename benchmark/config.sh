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
export BENCH_FLEET="${BENCH_FLEET:-A}"

#
# Fleet: 10 validators + 1 observer, two per region across devnet's five regions,
# the observer beside validator-01 in us-west2-a. Spelled out (bash 3.2 has no
# brace-expansion-with-padding worth trusting in an array literal).
#
export INSTANCE_NAMES=("bench-validator-01" "bench-validator-02" "bench-validator-03" "bench-validator-04" "bench-validator-05" "bench-validator-06" "bench-validator-07" "bench-validator-08" "bench-validator-09" "bench-validator-10" "bench-observer-11")
export NODE_ROLES=("validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "observer")
export ZONES=("us-west2-a" "us-west2-a" "australia-southeast1-c" "australia-southeast1-c" "northamerica-northeast1-b" "northamerica-northeast1-b" "europe-west4-a" "europe-west4-a" "europe-west2-b" "europe-west2-b" "us-west2-a")
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

# Machines. Same shape as devnet unless overridden for a sizing sweep.
export MACHINE_TYPE="${BENCH_MACHINE_TYPE:-e2-custom-4-8192}"
export NODE_DISK_SIZE="${BENCH_NODE_DISK_SIZE:-100}"   # GB boot disk (create-instances.sh --create-disk size=)
export NODE_DISK_TYPE="${BENCH_NODE_DISK_TYPE:-pd-ssd}"
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
export PARAMETERS_FILE="${REPO_ROOT}/common/parameters.yaml"
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
export BENCH_BLASTER_MACHINE_TYPE="${BENCH_BLASTER_MACHINE_TYPE:-e2-standard-2}"
export BENCH_SENDERS="${BENCH_SENDERS:-600}"            # per blaster
export BENCH_RUN_INDEX="${BENCH_RUN_INDEX:-0}"          # re-blast on the same fleet with fresh senders
export BENCH_WARMUP_SECS="${BENCH_WARMUP_SECS:-120}"
export BENCH_DURATION_SECS="${BENCH_DURATION_SECS:-2400}"
export BENCH_COOLDOWN_SECS="${BENCH_COOLDOWN_SECS:-180}"
export BENCH_PREAMBLE_SECS="${BENCH_PREAMBLE_SECS:-90}" # estimate of the generator's own preamble
export BENCH_START_DELAY_SECS="${BENCH_START_DELAY_SECS:-300}"
export BENCH_POLL_SECS="${BENCH_POLL_SECS:-240}"        # >= 240: IAP/serial polling lesson
# Chaos schedule, seconds after the mixed phase starts (kill v05, restart it, restart observer).
export BENCH_CHAOS_KILL_AT_SECS="${BENCH_CHAOS_KILL_AT_SECS:-900}"
export BENCH_CHAOS_BACK_AT_SECS="${BENCH_CHAOS_BACK_AT_SECS:-1200}"
export BENCH_CHAOS_OBS_AT_SECS="${BENCH_CHAOS_OBS_AT_SECS:-1500}"
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
export BENCH_RESULTS_DIR="${BENCH_DIR}/results/${BENCH_RUN_ID}"
# Abort thresholds (benchmark-blast.sh watchers).
export BENCH_ABORT_DISK_PCT="${BENCH_ABORT_DISK_PCT:-85}"
export BENCH_ABORT_OBS_MEM_PCT="${BENCH_ABORT_OBS_MEM_PCT:-85}"
export BENCH_ABORT_STALL_SECS="${BENCH_ABORT_STALL_SECS:-120}"

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
unset _bench_n _bench_arr _bench_name
