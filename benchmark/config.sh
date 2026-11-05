#!/usr/bin/env bash
#
# benchmark/config.sh — the BENCHMARK deploy profile. A throwaway 10-validator +
# 1-observer Telcoin Network fleet in tn-devnet that is stood up, blasted, measured
# and torn down without touching the live devnet (validator-{1..4}-devnet,
# observer-5-devnet, obs-devnet, txgen-devnet, devnet-indexer).
#
# It sources the devnet ../config.sh first (so every shared constant — PROJECT_ID,
# DOCKER_IMAGE, SERVICE_ACCOUNT, ... — is inherited; the OBS_* settings come along too but are
# inert by default: the bench metrics ship to the run's own bench-obs VM, see BENCH_OBS_* below,
# and only BENCH_PROM_AUTH=1 still reads obs-devnet) and then OVERRIDES everything that
# identifies a fleet. The shared drivers
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
# devnet-network-config.sh is allowed: deploy step 7 runs it first, so every bench node holds
# a Closed-admission network-config (rendered under GENESIS_WORKSPACE, i.e. benchmark/genesis/)
# before any node starts; it reads the fleet from this file and touches nothing else.
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
    devnet-keygen.sh|devnet-genesis-build.sh|devnet-network-config.sh|devnet-finalize.sh|\
    devnet-contracts.sh|create-instances.sh|genesis.sh|copy-committee.sh|params-apply.sh) ;;
    *)
        echo "❌ '${_bench_caller}' is not allowed to run with CONFIG_FILE=benchmark/config.sh." >&2
        echo "   The benchmark profile is driven only by benchmark/benchmark-*.sh (and the shared drivers they call)." >&2
        exit 1 ;;
esac
unset _bench_caller

# --- inherit the devnet constants, then override the fleet identity -------------
# shellcheck source=../config.sh
source "${BENCH_DIR}/../config.sh"
# The release-signing gate (devnet-release-sign.sh prepare/verify, wired into deploy step 6
# and finalize) is a devnet rehearsal of the mainnet release model. The bench profile has no
# signed release and this script is not in devnet-release-sign.sh's caller allowlist, so the
# gate must be OFF here (empty RELEASE_TAG disables both hooks).
export RELEASE_TAG=""

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
# 2026-11-03: northamerica-northeast1 (Montreal) stocked out of c3-highcpu-8 in zones b and c three times in a row
# (ZONE_RESOURCE_POOL_EXHAUSTED; zone a has no c3), so validator-05 runs in us-east4-b (Ashburn), the nearest region
# with c3-highcpu-8 + hyperdisk-balanced and quota. Runs before r20261103-1922 had it in Montreal.
# Spelled out (bash 3.2 has no brace-expansion-with-padding worth trusting in an array literal).
#
export INSTANCE_NAMES=("bench-validator-01" "bench-validator-02" "bench-validator-03" "bench-validator-04" "bench-validator-05" "bench-validator-06" "bench-validator-07" "bench-validator-08" "bench-validator-09" "bench-validator-10" "bench-observer-11")
export NODE_ROLES=("validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "validator" "observer")
export ZONES=("us-west2-a" "europe-west2-b" "australia-southeast1-c" "asia-northeast1-b" "us-east4-b" "europe-west4-a" "asia-southeast1-b" "asia-east2-a" "asia-northeast3-a" "asia-south1-c" "us-west2-a")
export NODE_NAMES=("bench01" "bench02" "bench03" "bench04" "bench05" "bench06" "bench07" "bench08" "bench09" "bench10" "bench11")
# From benchmark/.secrets/exec-keys.json (gitignored); validators 01-10, then observer 11.
export EXECUTION_ADDRESSES=("0xc7d975abd962345e9a6024aab692f6bf19140f03" "0x92862b13608e00925551233f21b6f44f6acc7f91" "0x3205c561e8183aae91ef1ab26a1db3fea83bb120" "0x213aff13862c86b3159a9552cc2424b92f8cfcfc" "0x31faf1673f324c688fff60172099f944171d6ab3" "0xe47fbdfdedadd35501eb7c3f38884238bf251103" "0x58114823ab8b21c4162cc28472ff2a6810e123e2" "0x8e7abe6740a452ade8f02a1f005002976e77fb0a" "0xc2f61840713de91b60e5b5c404350d705877911e" "0x52791a4607b5944ec0da0828d0ee78205b208ef1" "0xe88cc26183754978af15a67c1597324eec9ec806")
# Stockout fallbacks: space-separated <index>:<zone>[,<zone>...] items, index = position in INSTANCE_NAMES
# (0-based). When deploy step 2's create fails because a node's zone is out of MACHINE_TYPE, that node moves
# to its next zone here, step 2 re-runs the create (existing nodes are skipped, at most 3 rounds) and writes
# results/<run>/zones.env, which every later script of the run reads (below); manifest.zone_fallbacks[] and a
# note record each move (a comparability caveat: the latency matrices lack the new zone). Step 0 checks that
# each zone offers MACHINE_TYPE (a warning, not a stop). The defaults are the alternates checked on 2026-10-06
# and 2026-11-03: 3 = validator-04 (Tokyo b -> c), 4 = validator-05 (Ashburn b -> c, a), 7 = validator-08
# (Hong Kong -> Taiwan), 8 = validator-09 (Seoul a -> b). An empty value turns fallbacks off.
export BENCH_ZONE_FALLBACKS="${BENCH_ZONE_FALLBACKS-3:asia-northeast1-c 4:us-east4-c,us-east4-a 7:asia-east1-a 8:asia-northeast3-b}"

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

# Observability: METRICS ONLY, shipped to bench-obs, the run's own throwaway Prometheus + Grafana
# VM (benchmark/obs-lib.sh: created at deploy step 2, brought up at step 8, deleted by the teardown
# after its Prometheus snapshot is pulled). No logs, no health listener exposure, no dashboards on
# the nodes; obs-devnet is never written to.
export TN_OBS_ENABLE_LOGS=0
export TN_OBS_ENABLE_METRICS=1
export TN_OBS_ENABLE_HEALTH=0
export TN_OBS_ENABLE_DASHBOARD=0
export TN_ADMIN_DASHBOARD=0
export BENCH_PROM_NETWORK_LABEL="bench"      # TN_CHAIN on the node -> network= and chain= labels
export BENCH_PROM_DATASOURCE_UID="prometheus"
# bench-obs: one VM (BENCH_OBS_MACHINE_TYPE; debian-12, 20 GB pd-balanced boot disk + a pd-ssd
# data disk with device name obs-data, mounted at /mnt/obs-data by the startup script), tag
# bench-obs, the run's labels plus tn-role=obs, an ephemeral external IP. The nodes' Alloy pushes
# to its VPC internal IP (port 9090, default-allow-internal); the operator reaches Prometheus and
# Grafana only through two IAP ssh forwards on localhost (bench_obs_tunnel_up), so no DNS, TLS,
# static IP or firewall rule.
export BENCH_OBS_INSTANCE="${BENCH_OBS_INSTANCE:-bench-obs}"
export BENCH_OBS_ZONE="${BENCH_OBS_ZONE:-us-west2-a}"
export BENCH_OBS_MACHINE_TYPE="${BENCH_OBS_MACHINE_TYPE:-e2-standard-4}"
export BENCH_OBS_DISK_GB="${BENCH_OBS_DISK_GB:-50}"
export BENCH_OBS_PROM_LOCAL_PORT="${BENCH_OBS_PROM_LOCAL_PORT:-19090}"
export BENCH_OBS_GRAFANA_LOCAL_PORT="${BENCH_OBS_GRAFANA_LOCAL_PORT:-13000}"
# 1: the teardown pulls a Prometheus TSDB snapshot (bench-obs-prometheus-<UTC>.tar.gz) before it
# deletes the VM; 0 skips it.
export BENCH_OBS_PULL_PROM="${BENCH_OBS_PULL_PROM:-1}"
# Data disk use (%) at which bench_obs_require warns. Warn-only: it never stops a run.
export BENCH_OBS_DISK_MAX_PCT="${BENCH_OBS_DISK_MAX_PCT:-70}"
export BENCH_OBS_BOOT_TIMEOUT_SECS="${BENCH_OBS_BOOT_TIMEOUT_SECS:-600}"
# 0: Prometheus answers directly on the local forward (bench-obs). 1: the old path through a Grafana
# datasource proxy with the admin password from Secret Manager; 1 also needs
# BENCH_GRAFANA_URL=https://${OBS_HOSTNAME} (the obs-devnet Grafana) — never set 1 with the local
# forward URL.
export BENCH_PROM_AUTH="${BENCH_PROM_AUTH:-0}"
export BENCH_PROM_URL="${BENCH_PROM_URL:-http://127.0.0.1:${BENCH_OBS_PROM_LOCAL_PORT}/api/v1}"
export BENCH_GRAFANA_URL="${BENCH_GRAFANA_URL:-http://127.0.0.1:${BENCH_OBS_GRAFANA_LOCAL_PORT}}"
export BENCH_PROM_RETENTION="${BENCH_PROM_RETENTION:-7d}"
# BENCH_OBS_INTERNAL_IP is deliberately left unset: bench_obs_urls fills it from the manifest (or the
# bench-obs-internal-ip.invalid placeholder in dry and print modes). Set it only to override.
# The bundle pushed to the VM, the Grafana dashboards it serves and the VM's startup script.
export BENCH_OBS_BUNDLE_DIR="${BENCH_OBS_BUNDLE_DIR:-${BENCH_DIR}/obs}"
export BENCH_OBS_DASHBOARDS_DIR="${BENCH_OBS_DASHBOARDS_DIR:-${BENCH_DIR}/../common/observability/obs-vm/grafana/dashboards}"
export BENCH_OBS_STARTUP_SCRIPT="${BENCH_OBS_STARTUP_SCRIPT:-${BENCH_DIR}/../common/observability/obs-vm/startup-obs.sh}"

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
# Per-node consensus parameters on top of PARAMETERS_FILE, written by deploy step 9 into that node's
# <datadir>/parameters.yaml before its restart. Space-separated <index>:<key>=<value>[,<key>=<value>...],
# index into INSTANCE_NAMES, e.g. "2:min_header_delay=50ms,max_header_delay=250ms 7:max_batch_delay=100ms".
# Keys: BENCH_NODE_PARAM_KEYS (the node's Parameters at ba43a1f0e, crates/config/src/node.rs); durations
# <int>ms or <int>s. gc_depth and basefee_address stay fleet-wide. Checked below; live changes between
# sweep arms are tools/params-apply.sh's job, not this knob's.
export BENCH_NODE_PARAM_OVERRIDES="${BENCH_NODE_PARAM_OVERRIDES:-}"
# <type>:<key>; dur = <int>ms|<int>s, int = positive integer, bool = true|false. Keep in step with
# tools/params-apply.sh PARAM_KEYS.
export BENCH_NODE_PARAM_KEYS="dur:max_header_delay dur:min_header_delay dur:vote_timeout dur:max_batch_delay dur:sync_retry_delay int:header_num_of_batches_threshold int:max_header_num_of_batches int:sync_retry_nodes int:max_concurrent_requests bool:allow_private_forward_targets"
# Node log filter: step 7's pre-start config puts --log.stdout.filter <f> --log.file.filter <f>
# --log.file.max-files <n> on the node's command line (step 9 checks it). The default (bench 4, the design's
# D2 filter) logs the whole primary at debug (proposer, certifier and voter: `Processing vote request from
# peer`, `Created vote`; the three cert_* =info overrides drop the per-certificate dumps), the engine and the
# consensus subscriber (execution and output timing), the worker's network side and the request-response
# protocol (batch fetches, AtCapacity denials).
# The heavy diagnostic targets are opt-in: network=debug (`request received`, the vote request's arrival at
# the voter, with the full header: the bulk), multistream_select=debug, libp2p_swarm::connection::pool=debug,
# peer-manager=debug (per-substream negotiation and connection lifecycle, needed once to prove the
# negotiation fix) and network-kad=info. With them on, r20261007-0316 logged ~1 MB per round per node:
# ~3 GB/h raw idle and ~22 GB/h under load, on disk twice (container json-file log + unit append file), and
# ~80 GB pulled at teardown; network=debug was 97 % of the bytes in a sample under load. For a diagnostic run,
# append them to the default:
#   BENCH_NODE_LOG_FILTER="<default>,multistream_select=debug,libp2p_swarm::connection::pool=debug,peer-manager=debug,network=debug,network-kad=info"
# BENCH_NODE_LOG_FILTER= (empty) leaves the node's command line as it is.
export BENCH_NODE_LOG_FILTER="${BENCH_NODE_LOG_FILTER-info,primary=debug,engine=debug,subscriber=debug,worker::network=debug,network::reqres=debug,primary::cert_validator=info,primary::cert_manager=info,primary::cert_fetcher=info}"
export BENCH_NODE_LOG_MAX_FILES="${BENCH_NODE_LOG_MAX_FILES:-20}"
# The node's unit log (/var/log/telcoin/telcoin.log): v2's logrotate cuts it at 100M (and daily), which
# split bench 3's evidence across generations. Step 7's pre-start config writes the bench's own
# /etc/logrotate.d/telcoin rotating at this size (no maxsize); empty leaves v2's file alone. The teardown
# pulls every generation either way.
export BENCH_LOGROTATE_SIZE="${BENCH_LOGROTATE_SIZE-20G}"
# Which pulled unit logs the certification check reads (tools/cert-rate.py --node-glob), current and rotated.
export BENCH_CERT_LOG_GLOB="${BENCH_CERT_LOG_GLOB:-bench-validator-*-unit-stdout*.log.gz}"
# Per-node sessions of deploy steps 7 (pre-start config) and 9 (verify) run this many at a time; 1 = one
# after the other, stopping at the first failure.
export BENCH_NODE_JOBS="${BENCH_NODE_JOBS:-4}"
# Own BLS keystore passphrase (gitignored); benchmark-deploy.sh step 0 creates it if absent.
export TN_BLS_PASSPHRASE_FILE="${BENCH_DIR}/.secrets/bls-passphrase"

# RPC for the operator-side tools (cast, devnet-contracts.sh): the IAP tunnel to
# bench-validator-01:8545 that benchmark-deploy.sh opens on this local port.
export BENCH_TUNNEL_PORT=18545
export RPC_URL="http://localhost:${BENCH_TUNNEL_PORT}"
# The quorum guard in tn-node-deployment's lib falls back to DEVNET_RPC_URL, the LIVE devnet's
# public RPC, read once when the lib is sourced. Every bench script that sources that lib on a
# node exports DEVNET_RPC_URL to this black hole first (port 9, refused), so a bench node can
# never ask the devnet whether it may restart.
export BENCH_GUARD_PUBLIC_RPC="http://127.0.0.1:9"
# Fleet readiness (bench_fleet_ready, deploy steps 8 and 13): every validator must report
# tn_nodeMode CvvActive. A validator that is not active waits for the next epoch boundary plus
# BENCH_FLEET_READY_SETTLE_SECS, never longer than the caller's cap; step 13 caps it at one epoch
# plus 5 min, so a straggler from the coordinated start has a whole boundary to rejoin. Each node
# then gets BENCH_NODE_BACK_SECS to answer. Sparse polls only (IAP throttles tight loops).
export BENCH_FLEET_READY_SETTLE_SECS="${BENCH_FLEET_READY_SETTLE_SECS:-90}"
export BENCH_FLEET_READY_MAX_WAIT_SECS="${BENCH_FLEET_READY_MAX_WAIT_SECS:-$((EPOCH_DURATION_SECS + 300))}"
export BENCH_NODE_BACK_SECS="${BENCH_NODE_BACK_SECS:-180}"

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
# action (a poll takes ~40 s; STAGE must stay below GUARD). The session starts the pre-action
# container-log save in the background, runs the action on time whatever the save's state, then
# waits up to BENCH_CHAOS_SAVE_WAIT_SECS for the save (a longer one completes on the node by
# itself); STAGE + SAVE_WAIT must stay below the outage. BENCH_STALL_NOTE_SECS: the fleet's
# highest block flat this long in the mixed phase is noted (.commit_stalls), never an abort.
export BENCH_CHAOS_STAGE_SECS="${BENCH_CHAOS_STAGE_SECS:-30}"
export BENCH_CHAOS_GUARD_SECS="${BENCH_CHAOS_GUARD_SECS:-90}"
export BENCH_CHAOS_SAVE_WAIT_SECS="${BENCH_CHAOS_SAVE_WAIT_SECS:-60}"
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
# Zones the run's nodes were created in: after a stockout moved a node (BENCH_ZONE_FALLBACKS), deploy step 2
# writes ${BENCH_RESULTS_DIR}/zones.env, one line BENCH_ZONES_USED=<zone of node 0> ... <zone of node N>. It
# replaces ZONES for every script of the run (each sources this file), so a moved node is always addressed in
# its own zone. The file is read, never sourced.
if [ -f "${BENCH_RESULTS_DIR}/zones.env" ]; then
    _bench_zones="$(sed -n 's/^BENCH_ZONES_USED=//p' "${BENCH_RESULTS_DIR}/zones.env" | tail -1 | tr -d '"\r')"
    case "${_bench_zones}" in
        *[!a-z0-9\ -]*) echo "❌ benchmark/config.sh: ${BENCH_RESULTS_DIR}/zones.env: BENCH_ZONES_USED='${_bench_zones}' may hold only zone names separated by spaces." >&2; exit 1 ;;
    esac
    read -r -a _bench_zarr <<< "${_bench_zones}"
    [ "${#_bench_zarr[@]}" -eq "${#INSTANCE_NAMES[@]}" ] || { echo "❌ benchmark/config.sh: ${BENCH_RESULTS_DIR}/zones.env lists ${#_bench_zarr[@]} zone(s), INSTANCE_NAMES has ${#INSTANCE_NAMES[@]}." >&2; exit 1; }
    export ZONES=("${_bench_zarr[@]}")
fi
# Abort thresholds (benchmark-blast.sh watchers).
export BENCH_ABORT_DISK_PCT="${BENCH_ABORT_DISK_PCT:-85}"
export BENCH_ABORT_OBS_MEM_PCT="${BENCH_ABORT_OBS_MEM_PCT:-85}"
export BENCH_ABORT_STALL_SECS="${BENCH_ABORT_STALL_SECS:-120}"
# Certification outcome (recorded after collect and at teardown, never an abort): a validator that
# certified fewer than this % of its own headers in a window where it proposed >= 50 goes into
# manifest.cert_failures, gets a log snapshot, and the teardown's local gate requires its logs.
export BENCH_CERT_FAIL_PCT="${BENCH_CERT_FAIL_PCT:-90}"
# Step 15: after a chaos kill that landed, the Prometheus window ends only once every validator is CvvActive
# again (at most BENCH_FLEET_READY_MAX_WAIT_SECS), so the metrics cover the rejoin. 0: the manifest's window.
export BENCH_COLLECT_WAIT_REJOIN="${BENCH_COLLECT_WAIT_REJOIN:-1}"
# benchmark-blast.sh: move the chaos kill to the epoch that is actually closing once it has opened.
export BENCH_CHAOS_REFRESH_SCHEDULE="${BENCH_CHAOS_REFRESH_SCHEDULE:-1}"
# The RPC tunnel's supervisor gives up after this many consecutive failed sessions (a session that held at
# least BENCH_TUNNEL_MIN_UP_SECS resets the count).
export BENCH_TUNNEL_MAX_FAILS="${BENCH_TUNNEL_MAX_FAILS:-5}"
export BENCH_TUNNEL_MIN_UP_SECS="${BENCH_TUNNEL_MIN_UP_SECS:-20}"
# Root drivers the deploy runs (devnet-finalize.sh, devnet-keygen.sh, devnet-network-config.sh): each knob
# defaults to the devnet behaviour inside its driver; the bench profile sets these only when unset. Parallel
# nodes (4 at a time), network-config in two sessions a node with every observer trusted by every validator,
# keygen reusing a node already keyed for its address, advertising its internal-IP RPC (not the
# unresolvable benchNN.bench.invalid) and printing KEYGEN_DONE per node (deploy step 5 records them).
export FINALIZE_JOBS="${FINALIZE_JOBS:-4}"
export KEYGEN_JOBS="${KEYGEN_JOBS:-4}"
export NETCFG_JOBS="${NETCFG_JOBS:-4}"
export NETCFG_FAST="${NETCFG_FAST:-1}"
export NETCFG_TRUST_OBSERVERS_EVERYWHERE="${NETCFG_TRUST_OBSERVERS_EVERYWHERE:-1}"
export KEYGEN_REUSE_EXISTING="${KEYGEN_REUSE_EXISTING:-1}"
export KEYGEN_RPC_ADVERTISE="${KEYGEN_RPC_ADVERTISE:-internal-ip}"
export KEYGEN_REPORT="${KEYGEN_REPORT:-1}"
# The admission gate (deploy step 10) warns (never stops) for a node whose denied-peer counts exceed this.
# With every observer trusted everywhere a denial is unexpected, so the bench value is 0; otherwise unset
# (no check). BENCH_ADMISSION_DENIED_MAX= (empty) turns the check off; the gate names a value that is not a
# whole number and skips the check (bench-lib.sh bench_admission_gate).
if [ "${NETCFG_TRUST_OBSERVERS_EVERYWHERE}" = "1" ]; then
    export BENCH_ADMISSION_DENIED_MAX="${BENCH_ADMISSION_DENIED_MAX-0}"
else
    export BENCH_ADMISSION_DENIED_MAX="${BENCH_ADMISSION_DENIED_MAX:-}"
fi

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
# BENCH_NODE_PARAM_OVERRIDES: <index>:<key>=<value>[,...] items, each index once and a node of the fleet.
case "${BENCH_NODE_PARAM_OVERRIDES}" in
    *[*?[]*) echo "❌ benchmark/config.sh: BENCH_NODE_PARAM_OVERRIDES='${BENCH_NODE_PARAM_OVERRIDES}' holds a glob character." >&2; exit 1 ;;
esac
_bench_seen=" "
for _bench_item in ${BENCH_NODE_PARAM_OVERRIDES}; do
    _bench_bad=""
    _bench_idx="${_bench_item%%:*}"
    case "${_bench_item}" in *:*=*) ;; *) _bench_bad="not <index>:<key>=<value>[,<key>=<value>...]" ;; esac
    case "${_bench_idx}" in ''|*[!0-9]*|0?*) _bench_bad="${_bench_bad:-index '${_bench_idx}' is not a number}" ;; esac
    if [ -z "${_bench_bad}" ] && [ "${_bench_idx}" -ge "${#INSTANCE_NAMES[@]}" ]; then _bench_bad="index ${_bench_idx} is past the last node ($(( ${#INSTANCE_NAMES[@]} - 1 )))"; fi
    case "${_bench_seen}" in *" ${_bench_idx} "*) _bench_bad="${_bench_bad:-index ${_bench_idx} appears twice (give each node one item)}" ;; esac
    _bench_seen="${_bench_seen}${_bench_idx} "
    _bench_kvs="${_bench_item#*:},"; _bench_keys=" "
    while [ -z "${_bench_bad}" ] && [ -n "${_bench_kvs}" ]; do
        _bench_kv="${_bench_kvs%%,*}"; _bench_kvs="${_bench_kvs#*,}"
        _bench_k="${_bench_kv%%=*}"; _bench_v="${_bench_kv#*=}"
        case "${_bench_kv}" in *=*) ;; *) _bench_bad="'${_bench_kv}' is not <key>=<value>"; break ;; esac
        case "${_bench_keys}" in *" ${_bench_k} "*) _bench_bad="${_bench_k} is given twice"; break ;; esac
        _bench_keys="${_bench_keys}${_bench_k} "
        case "${_bench_k}" in
            gc_depth|basefee_address) _bench_bad="${_bench_k} must stay fleet-wide (set it in PARAMETERS_FILE, never per node)"; break ;;
        esac
        _bench_t=""
        for _bench_arr in ${BENCH_NODE_PARAM_KEYS}; do [ "${_bench_arr#*:}" != "${_bench_k}" ] || _bench_t="${_bench_arr%%:*}"; done
        case "${_bench_t}:${_bench_v}" in
            :*) _bench_bad="unknown key '${_bench_k}' (known: $(printf '%s ' ${BENCH_NODE_PARAM_KEYS} | sed 's/[a-z]*://g'))" ;;
            dur:*) case "${_bench_v}" in *ms) _bench_v="${_bench_v%ms}" ;; *s) _bench_v="${_bench_v%s}" ;; *) _bench_v="" ;; esac
                case "${_bench_v}" in ''|*[!0-9]*) _bench_bad="${_bench_kv#*=} is not <int>ms or <int>s (${_bench_k})" ;; esac ;;
            int:*[!0-9]*|int:|int:0*) _bench_bad="${_bench_k}=${_bench_v} is not a positive integer" ;;
            bool:true|bool:false|int:*) ;;
            bool:*) _bench_bad="${_bench_k}=${_bench_v} is not true or false" ;;
        esac
    done
    if [ -n "${_bench_bad}" ]; then
        echo "❌ benchmark/config.sh: BENCH_NODE_PARAM_OVERRIDES item '${_bench_item}': ${_bench_bad}." >&2; exit 1
    fi
done
# BENCH_ZONE_FALLBACKS: <index>:<zone>[,<zone>...] items, each index once and a node of the fleet.
case "${BENCH_ZONE_FALLBACKS}" in
    *[*?[]*) echo "❌ benchmark/config.sh: BENCH_ZONE_FALLBACKS='${BENCH_ZONE_FALLBACKS}' holds a glob character." >&2; exit 1 ;;
esac
_bench_seen=" "
for _bench_item in ${BENCH_ZONE_FALLBACKS}; do
    _bench_bad=""
    _bench_idx="${_bench_item%%:*}"
    case "${_bench_item}" in *:?*) ;; *) _bench_bad="not <index>:<zone>[,<zone>...]" ;; esac
    case "${_bench_idx}" in ''|*[!0-9]*|0?*) _bench_bad="${_bench_bad:-index '${_bench_idx}' is not a number}" ;; esac
    if [ -z "${_bench_bad}" ] && [ "${_bench_idx}" -ge "${_bench_n}" ]; then _bench_bad="index ${_bench_idx} is past the last node ($((_bench_n - 1)))"; fi
    case "${_bench_seen}" in *" ${_bench_idx} "*) _bench_bad="${_bench_bad:-index ${_bench_idx} appears twice (give each node one item)}" ;; esac
    _bench_seen="${_bench_seen}${_bench_idx} "
    _bench_kvs="${_bench_item#*:},"
    while [ -z "${_bench_bad}" ] && [ -n "${_bench_kvs}" ]; do
        _bench_v="${_bench_kvs%%,*}"; _bench_kvs="${_bench_kvs#*,}"
        case "${_bench_v}" in
            *[!a-z0-9-]*|-*|*-) _bench_bad="'${_bench_v}' is not a zone name" ;;
            [a-z]*-[a-z]*[0-9]-[a-z]) ;;
            *) _bench_bad="'${_bench_v}' is not a zone name (<region>-<letter>, e.g. us-east4-c)" ;;
        esac
    done
    if [ -n "${_bench_bad}" ]; then
        echo "❌ benchmark/config.sh: BENCH_ZONE_FALLBACKS item '${_bench_item}': ${_bench_bad}." >&2; exit 1
    fi
done
case "${BENCH_NODE_LOG_FILTER}" in
    *[!A-Za-z0-9_:,=.-]*) echo "❌ benchmark/config.sh: BENCH_NODE_LOG_FILTER='${BENCH_NODE_LOG_FILTER}' may hold only [A-Za-z0-9_:,=.-] (target=level directives)." >&2; exit 1 ;;
esac
case "${BENCH_NODE_LOG_MAX_FILES}" in
    ''|*[!0-9]*|0*) echo "❌ benchmark/config.sh: BENCH_NODE_LOG_MAX_FILES='${BENCH_NODE_LOG_MAX_FILES}' must be a positive integer." >&2; exit 1 ;;
esac
case "${BENCH_LOGROTATE_SIZE}" in
    '') ;;
    *[!0-9KMG]*|0*|[KMG]*|*[KMG]?*|*[0-9]) echo "❌ benchmark/config.sh: BENCH_LOGROTATE_SIZE='${BENCH_LOGROTATE_SIZE}' must be <n>K, <n>M or <n>G (or empty: v2's logrotate stays)." >&2; exit 1 ;;
esac
for _bench_knob in BENCH_NODE_JOBS BENCH_TUNNEL_MAX_FAILS; do
    case "${!_bench_knob}" in
        ''|*[!0-9]*|0*) echo "❌ benchmark/config.sh: ${_bench_knob}='${!_bench_knob}' must be a positive integer." >&2; exit 1 ;;
    esac
done
for _bench_knob in BENCH_COLLECT_WAIT_REJOIN BENCH_CHAOS_REFRESH_SCHEDULE; do
    case "${!_bench_knob}" in
        0|1) ;;
        *) echo "❌ benchmark/config.sh: ${_bench_knob}='${!_bench_knob}' must be 0 or 1." >&2; exit 1 ;;
    esac
done
case "${BENCH_TUNNEL_MIN_UP_SECS}" in
    ''|*[!0-9]*|0?*) echo "❌ benchmark/config.sh: BENCH_TUNNEL_MIN_UP_SECS='${BENCH_TUNNEL_MIN_UP_SECS}' must be a non-negative integer." >&2; exit 1 ;;
esac

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
for _bench_knob in BENCH_LAG_IDX BENCH_LAG_AT_SECS BENCH_FLEET_READY_SETTLE_SECS BENCH_FLEET_READY_MAX_WAIT_SECS BENCH_NODE_BACK_SECS; do
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
unset _bench_n _bench_arr _bench_name _bench_knob _bench_pdir _bench_seen _bench_item _bench_bad _bench_idx _bench_kvs _bench_kv _bench_k _bench_v _bench_t _bench_keys _bench_zones _bench_zarr
