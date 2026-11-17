#
# GLOBAL VARIABLES
#

# Absolute path to this repo's root. Every script/file path exported below is
# anchored to it, so shared scripts in common/ resolve their inputs regardless
# of the caller's working directory. ${BASH_SOURCE[0]:-$0} resolves this file's
# own path under both bash (the deploy scripts) and zsh (manual `source`).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

#
# Docker Image
#
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-v3-patch" # steve patch for v3
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.4-adiri-patch-bootstrap"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.5-adiri-crash-2-banned-peers-patch"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-pm-patch"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-pm-patch-3"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-pm-patch-3-dup-batches"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.11.1-devnet-pop"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.12.0-devnet"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.12.1-devnet"
# ABORTED 2026-07-22 02:25Z: v0.12.1-devnet-fork722 (ConsensusRegistry fork rehearsal, F=722)
# staged through canary but the fleet stagger never launched before the T0-30 deadline; canary
# reverse-updated. DO NOT deploy fork722 after epoch 721 closes unforked: any later replay
# across the 721 boundary would fire the swap against legacy-certified history and diverge.
# Fresh-genesis reset 2026-09-17: v0.1.0-devnet is a version re-cut, NOT a downgrade
# (pushed 2026-09-17T17:32Z, sha256:f6fcef5d..., newest tag in the registry). The whole
# chain is regenerated from it, so the ConsensusRegistry it bakes into genesis is the new one.
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.12.1-devnet-fork740"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.1.0-devnet"
# Fresh-genesis reset 2026-10-30 onto tn-node-deployment v2 + image v0.2.0-devnet. v2 pins
# the image BY DIGEST: on devnet its setup-node.sh accepts only <repo>@sha256:<64 hex> and
# refuses the tag form on the node. DOCKER_IMAGE_TAG is informational (the tag the digest
# was cut from; the genesis build may use either form). Fill in the pushed digest:
# devnet-deploy.sh refuses to run while any PLACEHOLDER marker (upper case + underscore)
# remains in this file (this digest and EXECUTION_ADDRESSES[4] until the deploy fills
# them; TN_NODE_SCRIPTS_REF must be a full 40-hex sha). Comments never spell the marker
# with its underscore, so the check can grep the file as text.
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:5257e768e657586a19e31308906bfacac0df95e5ca3da29a68f818f159d4a610"  # v0.2.0-devnet (launch 1; benchmark/config.sh keeps it)
# Launch 2 (2026-11-17): node image v0.3.0-devnet (telcoin-network main 5533ff73a, no faucet
# feature) plus the worker-gateway image that fronts the nodes' public RPC (see "Launch 2"
# below). Both are pinned by digest; both were pushed on 2026-11-17 and the digest was the
# same in the push log, in the local image store and in the registry. The *_TAG values are
# informational.
export DOCKER_IMAGE_TAG="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.3.0-devnet"
export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:0aec3e7cd1457488ed052a3cff8371a235f213f57e9fc727a3a62fb7abad11c1"
export GATEWAY_IMAGE_TAG="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway:v0.3.0-devnet"
export GATEWAY_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:8b887098f5cc5cb5ebc591bc82b1347513b23ae3ecca4f22787b2e4204f8c231"

#
# Release signing (devnet rehearsal of the mainnet release model)
#
# On mainnet a release is a GPG detached signature (SHA256SUMS.asc) over SHA256SUMS, the
# hash list of IMAGE_DIGEST (the pinned image digest) and the chain configs; nodes verify
# it with gpgv against the release keys shipped in tn-node-deployment (lib/release-keys).
# Devnet rehearses that with devnet-release-sign.sh: devnet-deploy.sh step 6 runs
# `prepare` right after the genesis build (writes releases/<tag>/IMAGE_DIGEST + SHA256SUMS),
# and devnet-finalize.sh runs `verify` before any node is finalized (stops with
# RELEASE_SIG_PENDING, exit 3, until releases/<tag>/SHA256SUMS.asc exists).
# RELEASE_TAG empty disables both hooks. RELEASE_SIGNER_FPR is informational: verification
# trusts the keyring allow-list in RELEASE_KEYS_DIR, not this value. A rerun of keygen or
# the genesis build changes the chain configs, so it needs a new prepare and a new signature.
export RELEASE_TAG="v0.3.0-devnet"
export RELEASE_KEYS_DIR="${REPO_ROOT}/tn-node-deployment/lib/release-keys"
export RELEASE_SIGNER_FPR="4E36D35A4AB61B589861D01AC7173F2377CA7573"

# TN_BLS_PASSPHRASE is deliberately NOT set here. devnet-lib.sh:tn_require_bls_passphrase
# checks $TN_BLS_PASSPHRASE first, so exporting it here would shadow (and defeat) the
# gitignored ${REPO_ROOT}/.secrets/bls-passphrase mechanism. Keep the passphrase there.

#
# GCP
#
# Instances are created WITHOUT static IPs (see create-instances.sh). GCP
# assigns an ephemeral external IP + auto internal IP at boot; each node
# self-discovers them from the metadata service. There are therefore no
# EXTERNAL_IPS / INTERNAL_IPS arrays here anymore.
#
# 1 - LA
# 2 - Dallas (moved from Sydney 2026-10-31; validator-2-devnet-ip re-reserved in us-south1)
# 3 - Montreal
# 4 - Netherlands
# 5 - London
# 6 - LA (rpc-6, us-west2-b: the public RPC node)
# gateway-4 - Netherlands (europe-west4-a, next to node 4, whose worker gateway it runs)
#
# NODE_ROLES is the single source of truth every script branches on; devnet-lib.sh's
# fleet helpers (tn_node_indices, tn_indices_by_role, tn_public_domain, ...) read it and
# tn_fleet_check validates the arrays. The arrays below are PARALLEL: index i of each
# describes the same VM, and indices 0-4 keep their launch-1 meaning. Four roles:
#   validator  indices 0-3: the genesis committee (the only validators in genesis).
#   observer   index 4, node 5: a unified node outside the genesis committee (there is no
#              `--observer` flag). It syncs as an observer and is minted + staked +
#              activated after genesis by devnet-stake-node5.sh. With nextCommitteeSize 4
#              and five eligible validators, the committee is reshuffled every epoch.
#   rpc        index 5, rpc-6: the public RPC node (RPC_HOSTNAME, admission Open). It runs
#              a node but never stakes; its keys are made like an observer's and its
#              node-info lives under genesis/observers/.
#   gateway    index 6, gateway-4: runs no node and holds no keys, only the worker gateway
#              of the node its GATEWAY_FOR entry names (node 4).
# validator, observer and rpc entries run a node (tn_node_indices); a gateway entry does not.
export INSTANCE_NAMES=("validator-1-devnet" "validator-2-devnet" "validator-3-devnet" "validator-4-devnet" "observer-5-devnet" "rpc-6-devnet" "gateway-4-devnet")
export NODE_ROLES=("validator" "validator" "validator" "validator" "observer" "rpc" "gateway")
export ZONES=("us-west2-a" "us-south1-a" "northamerica-northeast1-b" "europe-west4-a" "europe-west2-b" "us-west2-b" "europe-west4-a")
# Per-VM names. Public domains come from devnet-lib.sh tn_public_domain: node{N}.${BASE_DOMAIN}
# for a validator or observer, RPC_HOSTNAME for rpc-6, and a gateway entry serves the domain
# of the node it fronts (gateway4 is a label, not a DNS name).
export NODE_NAMES=("node1" "node2" "node3" "node4" "node5" "node6" "gateway4")
# EXECUTION_ADDRESSES[4] (node 5) is a NEW key generated at deploy time with
# `cast wallet new`, funded 1,000,100 TEL in testnet_accounts.yaml; its private key
# lives only in Secret Manager (NODE5_VALIDATOR_PK_SECRET). Replace the placeholder
# with that address. The old recorded 0xb4e5ed81... disagreed with
# genesis/observers/node5.yaml and was never funded.
# EXECUTION_ADDRESSES[5] (rpc-6) is the devnet Safe, SAFE_ADDR below (written out: this
# array comes first). rpc-6 never stakes; the value only fills the node's fee-recipient field.
# EXECUTION_ADDRESSES[6] (gateway-4) is the zero address: a gateway has no keys, the entry
# only keeps the shared instance-creation metadata (EXECUTION_ADDRESS=...) well-formed.
export EXECUTION_ADDRESSES=("0x3518b301b86ceb53b5a3dff62e55cd43ef59d024" "0x7489025dfbaad94f2366d88a62989147d9c8b5d3" "0x0033a370616805b1fd275b7ffab83fc41d665ccb" "0xefaacf04b92298a88200aa50aa6bb7bfce587b17" "0xd0154a8091de71cc81b3c6f95b73d0aa129da7b8" "0x00000000000000000000000000000000000007a0" "0x0000000000000000000000000000000000000000")
export NODE5_VALIDATOR_PK_SECRET="devnet-node5-validator-pk"   # Secret Manager (tn-devnet): node 5 execution-key private key
# Reserved static external IPs — one per instance, PARALLEL to INSTANCE_NAMES. The
# Ubuntu migration pins these so the GCP consensus /32 rules + DNS A-records survive
# node restart/reuse (fixes the ephemeral-IP churn). Reserve them once with
# common/reserve-static-ips.sh BEFORE common/create-instances.sh.
export USE_STATIC_IPS=1
export STATIC_IP_NAMES=("validator-1-devnet-ip" "validator-2-devnet-ip" "validator-3-devnet-ip" "validator-4-devnet-ip" "observer-5-devnet-ip" "rpc-6-devnet-ip" "gateway-4-devnet-ip")
# Worker gateway per entry, read only when TN_GATEWAY_ENABLE=1 (see "Launch 2" below):
#   same-host   the node's own host runs its gateway behind its Caddy (node RPC on loopback)
#   standalone  the `gateway` entry whose GATEWAY_FOR names this node runs it on its own VM
#               (the node's RPC listens on its internal IP for that gateway only)
#   none        no gateway; always `none` on `rpc` and `gateway` entries
# GATEWAY_FOR is set only on a `gateway` entry: the NODE_NAMES value of the node it fronts.
export GATEWAY_MODES=("same-host" "same-host" "same-host" "standalone" "same-host" "none" "none")
export GATEWAY_FOR=("" "" "" "" "" "" "node4")
export PROJECT_ID="tn-devnet"
# All gcloud calls in scripts that source this file target PROJECT_ID,
# regardless of the operator's `gcloud config` default. Explicit --project
# flags (same value) still take precedence.
export CLOUDSDK_CORE_PROJECT="${PROJECT_ID}"
export MACHINE_TYPE="e2-custom-4-8192"
# VERIFY: this must be the tn-devnet project's default compute service account.
# The numeric prefix is the project number; confirm it matches tn-devnet with:
#   gcloud projects describe tn-devnet --format='value(projectNumber)'
export SERVICE_ACCOUNT="1095385745561-compute@developer.gserviceaccount.com"
# OS: Ubuntu 24.04 LTS (noble). The tn-node-deployment per-node model targets
# Ubuntu/Debian and devnet-startup.sh installs docker-ce from
# download.docker.com/linux/ubuntu. Family verified present in ubuntu-os-cloud.
# (NOTE: OBS_IMAGE stays Debian — common/observability obs-vm startup hardcodes the
# Debian docker apt repo; see OBS_IMAGE below.)
export IMAGE="projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
# Per-node GCP startup-script. Devnet drives tn-node-deployment, so this is devnet's
# OWN startup (apt docker-ce + ops agent + root-owned tn-node-deployment checkout at the
# tn-scripts-ref metadata sha + wgvpn overlay; v2's setup-node.sh creates the service
# account), NOT common/startup.sh (which moved to the adiri repo).
export STARTUP_SCRIPT_PATH="${REPO_ROOT}/devnet-startup.sh"
export DEFAULT_PRIMARY_UDP_PORT=49590
export DEFAULT_WORKER_UDP_PORT=49594
export DEFAULT_HEALTHCHECK_TCP_PORT=43174
# External uptime monitor (Kuma VM public IP, tn-dev-sandbox project) allowed to TCP-probe
# the health port. Drives BOTH layers: the host-ufw monitor rule (via devnet-firewall.sh ->
# firewall-setup.sh apply_kuma_rule) AND the VPC rule devnet-allow-healthcheck-from-kuma
# (setup-firewall.sh Step 5b). 104.155.184.201 is the Kuma VM (confirmed).
# Empty = no monitor rule at either layer (preserves pre-lockdown behavior).
export HEALTHCHECK_MONITOR_SRC="104.155.184.201/32"
# Google Cloud health-check probe source ranges (for the global RPC load balancer's TCP
# health check on the health port). Single source of truth: the VPC rule devnet-allow-health-check
# (setup-firewall.sh Step 5) AND the host-ufw allow (devnet-firewall.sh passes this as
# TN_LB_HC_RANGES to firewall-setup.sh --enable). Both layers must admit these or LB backends
# stay unhealthy even with the listener up. Stable, Google-published ranges.
# Launch 2 has no LB: this and HEALTHCHECK_MONITOR_SRC stay defined, but no launch-2
# driver opens a rule for either.
export GOOGLE_HC_RANGES="130.211.0.0/22,35.191.0.0/16,209.85.152.0/22,209.85.204.0/22"
#
# DNS / TLS
#
export BASE_DOMAIN="devnet.telcoin.network"
export LETSENCRYPT_EMAIL="devs@telcoin.org"
# Cert-domain SUFFIXES — config-caddy.sh issues node{N}.<suffix> for each (the
# first is the cert lineage). Devnet serves a single domain.
export CERT_DOMAINS=("${BASE_DOMAIN}")
# Caddy RPC reverse-proxy script driven by dns.sh: scp'd to each node + run as root, it reads
# the node's .node-meta RPC_PORT/WS_PORT and proxies https/wss to the right loopback ports.
# Lives in common/ (shared with adiri). Required by dns.sh + genesis.sh's Caddy step.
export CONFIG_CADDY_SCRIPT="${REPO_ROOT}/common/config-caddy.sh"
#
# Genesis
#
# Epoch duration baked into genesis (devnet: 1h).
export EPOCH_DURATION_SECS=3600
# Explicit chain id passed to `telcoin genesis --chainid`.
export CHAIN_ID=32285
# Consensus + fee knobs consumed by common/genesis.sh. EVERY one of them changes the
# genesis hash. Header/batch delays are the benchmark stage-2 final config
# (vote_timeout stays at the 5 s default).
export MIN_HEADER_DELAY_MS=350
export MAX_HEADER_DELAY_MS=1000
export MAX_BATCH_DELAY_MS=250
# `telcoin genesis --worker-fee-config` WORKER_ID:STRATEGY:VALUE (strategy 0 = EIP-1559,
# 1 = static fee). Worker 0, EIP-1559, target 10,000,000 gas per epoch; the
# permanent generator lands ~900M gas/epoch, so the EIP-1559 base fee rises 12.5 % per
# epoch from the 7 wei floor. The WorkerConfigs owner
# 0xFee0FEe0fee0fEE0FEe0fee0FEE0fEe0feE0FEe0 can change it later with setWorkerConfig.
export WORKER_FEE_CONFIG="0:0:10000000"
#
# Node deployment model (tn-node-deployment)
# ------------------------------------------
# Devnet drives per-node actions (keygen, finalize, observability, firewall) through
# the Association's tn-node-deployment tooling (run ON each node via the devnet-*.sh
# drivers), while this repo owns fleet/GCP orchestration. These parameterize the drivers.
# In v2, setup-validator.sh / setup-observer.sh are shims: the drivers call setup-node.sh
# with --phase=keygen|finalize. The node's listeners live in /etc/telcoin/node.env and
# the start script is /usr/local/libexec/telcoin/tn-start-docker.
export NODE_DEPLOY_MODE="tn-node-deployment"
export TN_INSTALL_METHOD="docker"                          # node runs the telcoin docker image
# systemd service + data-dir owner on node. v2's setup-node.sh creates it as a SYSTEM
# account (uid < 1000, NOT in the docker group); devnet-startup.sh no longer creates it.
export SERVICE_USER="telcoin"
# tn-node-deployment checkout on each node: root-owned, detached at TN_NODE_SCRIPTS_REF.
# Not under /home any more: v2's install-ui refuses a checkout owned by the service account.
export TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"
# Full 40-hex tn-node-deployment commit the fleet runs: the worker-gateway branch head
# (launch 2) once it is pushed. Until then it holds a marker value and the deploy's marker
# gate refuses to run. Launch 1 ran d9446f72; benchmark/config.sh keeps that commit.
export TN_NODE_SCRIPTS_REF="PLACEHOLDER_TN_NODE_SCRIPTS_REF"
# devnet-startup.sh is self-contained (it is GCP metadata, not sourced against this file)
# and keeps its own copy of this URL; change both together.
export TN_NODE_DEPLOY_REPO="https://github.com/Telcoin-Association/tn-node-deployment.git"
export VALIDATOR_DATA_DIR="/var/lib/telcoin"               # DATA_DIR: chain data + node-keys/ live here (unified, no role subdir)
export OBSERVER_DATA_DIR="/var/lib/telcoin"
export TN_CHAIN_SUBDIR="devnet"                            # chain-configs/<subdir> the node looks under
# Where devnet-finalize.sh stages committee/genesis/parameters so setup-node.sh
# --phase=finalize --genesis-dir finds them (matches ${CONFIG_DIR}/chain-configs/<subdir>).
export VALIDATOR_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"
export OBSERVER_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"
#
# Legacy global L7 Load Balancer (launch 1's rpc.devnet.telcoin.network)
#
# Launch 2 has no load balancer: RPC_HOSTNAME is served by rpc-6's own Caddy. These are the
# launch-1 LB resource names, read only by devnet-teardown.sh to delete that stack.
# common/setup-load-balancer.sh (which reads the old LB_ names) is no longer called.
export LEGACY_LB_NAME_PREFIX="devnet-rpc"
export LEGACY_LB_HOSTNAME="rpc.devnet.telcoin.network"
export LEGACY_LB_HEALTH_CHECK_NAME="devnet-rpc-hc"
export LEGACY_LB_BACKEND_SERVICE="devnet-rpc-backend"
export LEGACY_LB_URL_MAP="devnet-rpc-urlmap"
export LEGACY_LB_SSL_CERT="devnet-rpc-cert"
export LEGACY_LB_HTTPS_PROXY="devnet-rpc-https-proxy"
export LEGACY_LB_FORWARDING_RULE="devnet-rpc-fr"
export LEGACY_LB_GLOBAL_IP_NAME="devnet-rpc-ip"
export LEGACY_LB_FIREWALL_RULE="devnet-lb-allow-health-check"
#
# Governance / mint toolkit (shared Makefile + mint*.sh in common/)
#
# RPC the Safe/mint tooling talks to — devnet's public RPC node, rpc-6, behind its own
# Caddy (launch 1 used a load balancer at the same name). (mint-role.sh previously
# hardcoded the TESTNET RPC; parameterizing it here fixes that bug.)
export RPC_HOSTNAME="rpc.${BASE_DOMAIN}"
export RPC_URL="https://${RPC_HOSTNAME}"
# Canonical TN system Safe (multisig) precompile — identical on every TN network.
export SAFE_ADDR="0x00000000000000000000000000000000000007a0"
# Contracts admin (Secret Manager: devnet-contracts-admin-pk). devnet-genesis-build.sh
# step 6 inserts it as the FIRST owner of the registry-owner Safe (SAFE_ADDR, threshold 1)
# at genesis, so the admin can mint and govern without the other 7 owners.
export SAFE_EXTRA_OWNER="0xAee2797478Cb5EfaF1869A2e33e369421EBf520f"
# StablecoinManager deployment that holds the TEL mint role.
# VERIFY: this address was inherited from testnet and may differ on devnet —
# confirm the devnet StablecoinManager before any send.
export STABLECOIN_MANAGER="0x981be5999e322cb3f21511d043e8c314fda5da55"
#
# Launch 2: worker gateways, native admission, the public RPC node
# ----------------------------------------------------------------
# 1 = run a worker gateway (tn-node-deployment setup-gateway.sh) for every node whose
# GATEWAY_MODES entry is not `none`; any other value = no gateway anywhere (the gateway
# arrays are then ignored: tn_gateway_mode answers `none`, tn_fleet_check skips them).
export TN_GATEWAY_ENABLE=1
# How a node gets its peers/admission config. `native`: setup-node.sh --admission,
# --bootstrap-peers and --trusted-nodes, fed with maps devnet-network-config.sh renders
# into ADMISSION_MAPS_DIR (local) and installs into ADMISSION_HOST_DIR on each node host.
# `devnet`: the launch-1 path, a devnet-rendered network-config installed before the node
# starts (the benchmark profile keeps it).
export TN_ADMISSION_VIA="native"
export ADMISSION_MAPS_DIR="genesis/admission-maps"
export ADMISSION_HOST_DIR="/etc/telcoin/devnet-admission"
# The node's JSON-RPC port (loopback behind a same-host gateway, internal IP behind a
# standalone one).
export NODE_RPC_PORT=8545
# Gateway listeners on its host: client traffic (its Caddy proxies here), probes, metrics.
export GATEWAY_LISTEN_PORT=8655
export GATEWAY_PROBE_PORT=8656
export GATEWAY_METRICS_PORT=9655
# A gateway proxies every non-submission call to the public RPC node (--redirect-queries).
export GATEWAY_REDIRECT_URL="${RPC_URL}"
# VPC firewall target tags (setup-firewall.sh): consensus UDP on node hosts, 80/443 on
# Caddy hosts, the node RPC + health ports on a validator fronted by a standalone gateway.
export VPC_TAG_P2P="devnet-p2p"
export VPC_TAG_WEB="devnet-web"
export VPC_TAG_GW_UPSTREAM="devnet-gw-upstream"
# devnet-p2p-committee.sh: how long it waits per host for an authoritative admission
# snapshot before it gives up on that host.
export P2P_COMMITTEE_WAIT_SECS=300
#
# PATHS
#
export GENESISDIR="genesis/validators/"
export LOCAL_PATH="./genesis/validators/"
export REMOTE_VALIDATORS_PATH="/home/share"
export REMOTE_SHARE_PATH="/home/share/"
# Directory the genesis build works in (holds genesis/validators/, genesis/observers/,
# testnet_accounts.yaml; the docker `-v ./:/code` mount targets it). Plain assignment on
# purpose: a profile that sources this file (benchmark/config.sh) overrides it afterwards,
# so an inherited environment value can never re-point the devnet build.
export GENESIS_WORKSPACE="${REPO_ROOT}"
# The genesis image runs as uid 1101 (`USER nonroot` in etc/Dockerfile) and must write
# committee/genesis/parameters.yaml into the bind-mounted workspace. On rootful Linux
# docker (xerxes) that uid owns nothing here, so common/genesis.sh runs the container as
# the operator's own uid:gid when this is set (R6 review; Docker Desktop on the Mac hid
# the problem). Unset => adiri's historical docker argv, byte for byte.
GENESIS_DOCKER_USER="$(id -u):$(id -g)"
export GENESIS_DOCKER_USER
export GENESIS_FILE="${GENESIS_WORKSPACE}/genesis/genesis.yaml"
# `telcoin genesis` writes the ROOT parameters.yaml (the old common/ path was a shared file).
export PARAMETERS_FILE="${REPO_ROOT}/parameters.yaml"
export COMMITTEE_FILE="./genesis/committee.yaml"
export UPLOAD_COMMITTEE_SCRIPT="${REPO_ROOT}/common/copy-committee.sh"
# NOTE: the docker-image node-start scripts (start-validator-node.sh,
# start-observer-node.sh, config-apache.sh) moved out of common/ into the adiri repo.
# Devnet drives per-node actions through tn-node-deployment (devnet-keygen.sh /
# devnet-finalize.sh), so those path vars are intentionally removed here.
#
# Observability (Wave 1: centralized logs)
# ----------------------------------------
# Self-hosted Loki + Grafana + Caddy on a dedicated "obs" VM in tn-devnet. The 4
# validators + observer ship reth JSON logs to it via a per-node Alloy sidecar,
# gated on OBS_INGEST_TOKEN. Same common/ tooling adiri uses; see
# common/observability/README.md. Names are project-scoped, so reusing the adiri
# secret/disk/IP names in the tn-devnet project is fine.
#
# Central obs VM
export OBS_INSTANCE_NAME="obs-devnet"
export OBS_REGION="us-west2"                  # co-located with validator-1-devnet (us-west2-a)
export OBS_ZONE="us-west2-a"
export OBS_MACHINE_TYPE="e2-standard-4"
export OBS_HOSTNAME="obs.devnet.telcoin.network"   # A record -> OBS static IP (out of band)
export OBS_STATIC_IP_NAME="obs-devnet-ip"     # reserved by common/create-obs-instance.sh
export OBS_DATA_DISK_NAME="obs-devnet-data"   # persistent disk for Loki chunks + Grafana DB
export OBS_DATA_DISK_SIZE=300                 # GB; resized from 100 (fs was filling); devnet 1h epochs
# Image FAMILY (not a dated build) so the VM always provisions on the latest
# non-deprecated Debian 12 image — a pinned dated image goes deprecated over time
# and makes `gcloud compute instances create` print a deprecation warning.
# DELIBERATELY Debian (NOT Ubuntu like the validator IMAGE): obs-vm/startup-obs.sh
# hardcodes the Debian docker apt repo (download.docker.com/linux/debian); on Ubuntu
# the docker-ce install fails and obs bring-up times out. Porting obs to Ubuntu is a
# separate, localized change to startup-obs.sh.
export OBS_IMAGE="projects/debian-cloud/global/images/family/debian-12"
# Log-push endpoint and bearer-token plumbing. OBS_PUSH_URL is seeded into each
# node's metadata by seed-node-token.sh — that is what points devnet's nodes at
# THIS obs VM rather than the adiri default baked into start-*-node.sh.
export OBS_PUSH_URL="https://${OBS_HOSTNAME}/loki/api/v1/push"
# Metrics remote-write endpoint (Prometheus). Mirrors OBS_PUSH_URL; passed to
# tn-node-deployment's Alloy via setup-observability.sh --metrics-push-url so devnet
# metrics ship to THIS obs VM. (FIX: was referenced by seed-node-token.sh but undefined.)
export OBS_METRICS_PUSH_URL="https://${OBS_HOSTNAME}/api/v1/write"
# Prometheus external-label identity for THIS obs VM. create-obs-instance.sh passes it to
# bringup-remote.sh, which rewrites prometheus.yml's `monitor:` label on deploy (the shared
# obs bundle ships the adiri default; unset => stays obs-adiri). Keeps devnet metrics distinct.
export OBS_MONITOR="obs-devnet"
# Per-node observability opt-ins — DEFAULT-ON for devnet (logs+metrics+health+dashboard).
# devnet-observability.sh gates each setup-observability.sh --enable-* on these.
export TN_OBS_ENABLE_LOGS="${TN_OBS_ENABLE_LOGS:-1}"
export TN_OBS_ENABLE_METRICS="${TN_OBS_ENABLE_METRICS:-1}"
export TN_OBS_ENABLE_HEALTH="${TN_OBS_ENABLE_HEALTH:-1}"
export TN_OBS_ENABLE_DASHBOARD="${TN_OBS_ENABLE_DASHBOARD:-1}"
export OBS_SECRET_NAME="obs-ingest-token"          # Secret Manager (tn-devnet): Loki ingest token
export OBS_GRAFANA_SECRET_NAME="obs-grafana-admin" # Secret Manager (tn-devnet): Grafana admin pw
# Disk-usage alerting on the obs data disk. The Ops Agent (installed by
# startup-obs.sh) ships agent.googleapis.com/disk/percent_used; the policy created
# by common/observability/setup-obs-disk-alert.sh fires when /mnt/obs-data crosses
# the threshold, mailing OBS_ALERT_EMAIL. Defaults to the Let's Encrypt contact.
export OBS_ALERT_EMAIL="${OBS_ALERT_EMAIL:-${LETSENCRYPT_EMAIL}}"  # devs@telcoin.org
export OBS_DISK_ALERT_THRESHOLD=85   # %; alert when obs-data crosses this
# Admin source ranges for Grafana on a static-IP network. UNUSED on devnet: with
# ephemeral node IPs, setup-obs-firewall.sh opens :443 to 0.0.0.0/0 (token-gated),
# so there is nothing to allowlist. Kept defined for the shared script's set -u.
export OBS_ADMIN_IPS="${OBS_ADMIN_IPS:-}"
# Firewall model: tn-devnet has NO global network firewall policy (its
# setup-firewall.sh uses classic VPC firewall-rules on the `default` network).
# So setup-obs-firewall.sh takes its EPHEMERAL branch (VPC rules on the `obs`
# tag) and this var is intentionally empty. If tn-devnet ever adopts a global
# policy, set its name here and the script's static branch would apply instead.
export OBS_FIREWALL_POLICY=""
# wireguard vpn
export TN_USE_VPN=1
# Devnet host-firewall model: UFW is the SINGLE authoritative host firewall, so the
# wgvpn overlay must NOT lay a policy-drop nftables table (else UFW∩nft = an
# intersection trap). WG_NODE_FIREWALL=0 = overlay only; devnet-startup.sh passes it
# to common/wgvpn/node/wg-node-bootstrap.sh. (The pre-existing WG_NODE_ENFORCE gates
# *activation* of an already-installed table, default 0 — a different switch, left as-is.)
export WG_NODE_FIREWALL=0
# Uptime monitor (Kuma) allowed to TCP-probe the health port (43174). Canonical source
# = HEALTHCHECK_MONITOR_SRC above; mirrored to tn-node-deployment's TN_KUMA_SRC so the
# host UFW health rule and the GCP rule agree on one /32.
export TN_KUMA_SRC="${HEALTHCHECK_MONITOR_SRC}"
#
# Admin dashboard (Telcoin Node Manager UI) — MANDATORY, zero-config
# ------------------------------------------------------------------
# DEFAULT ON. devnet-dashboards.sh installs the Flask UI (telcoin-ui, 127.0.0.1:8080)
# on every node, and common/dns.sh -> config-caddy.sh fronts it at admin.<node>.${BASE_DOMAIN}.
# The public Caddy vhost stamps the unforgeable X-TN-Dashboard-Public header so server.py
# refuses every write — the public path is READ-ONLY. basic_auth gates it with one SHARED
# credential across all 5 nodes: the username below + a bcrypt hash in GCP Secret Manager.
# Management (start/stop/edit) stays on the SSH tunnel (tn-node-deployment/open-ui.sh).
#
# NO env vars to set: common/dns.sh fetches the hash from Secret Manager itself on every run
# (TN_ADMIN_HASH_SECRET). One-time setup of that secret: ./devnet-admin-secret.sh.
# Set TN_ADMIN_DASHBOARD=0 ONLY to explicitly opt out (Caddyfile then byte-identical to RPC-only).
export TN_ADMIN_DASHBOARD="${TN_ADMIN_DASHBOARD:-1}"        # 1 => install + expose the Node Manager UI (default ON)
export TN_ADMIN_AUTH_USER="${TN_ADMIN_AUTH_USER:-admin}"    # basic_auth username (shared across nodes)
export TN_ADMIN_HASH_SECRET="${TN_ADMIN_HASH_SECRET:-devnet-admin-dashboard-hash}"  # GCP Secret Manager: bcrypt hash
# NOTE: TN_ADMIN_AUTH_HASH (the bcrypt hash itself) is intentionally NOT defaulted here — it is a
# credential, auto-resolved at rollout by dns.sh from Secret Manager (or honored if pre-exported).
# It must never be committed or logged.
