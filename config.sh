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
export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.10.0-adiri"


#
# GCP
#
# Instances are created WITHOUT static IPs (see create-instances.sh). GCP
# assigns an ephemeral external IP + auto internal IP at boot; each node
# self-discovers them from the metadata service. There are therefore no
# EXTERNAL_IPS / INTERNAL_IPS arrays here anymore.
#
# 1 - LA
# 2 - Australia
# 3 - Montreal
# 4 - Netherlands
# 5 - London
#
# NODE_ROLES is the single source of truth every script branches on. The
# first four are committee validators; the fifth runs as an observer
# (`node --observer`) and can later stake into a future committee via
# ConsensusRegistry.
export INSTANCE_NAMES=("validator-1-devnet" "validator-2-devnet" "validator-3-devnet" "validator-4-devnet" "observer-5-devnet")
export NODE_ROLES=("validator" "validator" "validator" "validator" "observer")
export ZONES=("us-west2-a" "australia-southeast1-c" "northamerica-northeast1-b" "europe-west4-a" "europe-west2-b")
# Per-node hostnames → node{N}.${BASE_DOMAIN}
export NODE_NAMES=("node1" "node2" "node3" "node4" "node5")
export EXECUTION_ADDRESSES=("0x3518b301b86ceb53b5a3dff62e55cd43ef59d024" "0x7489025dfbaad94f2366d88a62989147d9c8b5d3" "0x0033a370616805b1fd275b7ffab83fc41d665ccb" "0xefaacf04b92298a88200aa50aa6bb7bfce587b17" "0x89dab9f6fdc569c1bcdbd6493f25b7040b55dc79")
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
export IMAGE="projects/debian-cloud/global/images/debian-12-bookworm-v20251111"
export STARTUP_SCRIPT_PATH="${REPO_ROOT}/common/startup.sh"
export DEFAULT_PRIMARY_UDP_PORT=49590
export DEFAULT_WORKER_UDP_PORT=49594
export DEFAULT_HEALTHCHECK_TCP_PORT=43174
# External uptime monitor (Kuma VM static IP) allowed to TCP-probe the health port.
# Mirrors the cloud rule allow-validator-healthcheck-from-kuma at the host nft layer.
# Empty = no host-fw monitor rule (preserves pre-lockdown behavior).
export HEALTHCHECK_MONITOR_SRC="104.155.184.201/32"
#
# DNS / TLS
#
export BASE_DOMAIN="devnet.telcoin.network"
export LETSENCRYPT_EMAIL="devs@telcoin.org"
# Cert-domain SUFFIXES — config-apache.sh issues node{N}.<suffix> for each (the
# first is the ServerName / cert lineage). Devnet serves a single domain.
export CERT_DOMAINS=("${BASE_DOMAIN}")
#
# Genesis
#
# Epoch duration baked into genesis (devnet: 1h).
export EPOCH_DURATION_SECS=3600
# Explicit chain id passed to `telcoin genesis --chainid`.
export CHAIN_ID=32285
#
# Global L7 Load Balancer (rpc.devnet.telcoin.network)
#
export LB_NAME_PREFIX="devnet-rpc"
export LB_HOSTNAME="rpc.devnet.telcoin.network"
export LB_HEALTH_CHECK_NAME="devnet-rpc-hc"
export LB_BACKEND_SERVICE="devnet-rpc-backend"
export LB_URL_MAP="devnet-rpc-urlmap"
export LB_SSL_CERT="devnet-rpc-cert"
export LB_HTTPS_PROXY="devnet-rpc-https-proxy"
export LB_FORWARDING_RULE="devnet-rpc-fr"
export LB_GLOBAL_IP_NAME="devnet-rpc-ip"
export LB_FIREWALL_RULE="devnet-lb-allow-health-check"
#
# Governance / mint toolkit (shared Makefile + mint*.sh in common/)
#
# RPC the Safe/mint tooling talks to — devnet's own load balancer. (mint-role.sh
# previously hardcoded the TESTNET RPC; parameterizing it here fixes that bug.)
export RPC_URL="https://rpc.devnet.telcoin.network"
# Canonical TN system Safe (multisig) precompile — identical on every TN network.
export SAFE_ADDR="0x00000000000000000000000000000000000007a0"
# StablecoinManager deployment that holds the TEL mint role.
# VERIFY: this address was inherited from testnet and may differ on devnet —
# confirm the devnet StablecoinManager before any send.
export STABLECOIN_MANAGER="0x981be5999e322cb3f21511d043e8c314fda5da55"
#
# PATHS
#
export GENESISDIR="genesis/validators/"
export LOCAL_PATH="./genesis/validators/"
export REMOTE_VALIDATORS_PATH="/home/share"
export REMOTE_SHARE_PATH="/home/share/"
export GENESIS_FILE="${REPO_ROOT}/genesis/genesis.yaml"
export PARAMETERS_FILE="${REPO_ROOT}/common/parameters.yaml"
export COMMITTEE_FILE="./genesis/committee.yaml"
export UPLOAD_COMMITTEE_SCRIPT="${REPO_ROOT}/common/copy-committee.sh"
export START_VALIDATOR_NODE_SCRIPT="${REPO_ROOT}/common/start-validator-node.sh"
# Used for the observer node (NODE_ROLES==observer); scripts pick the start
# script by role.
export START_OBSERVER_NODE_SCRIPT="${REPO_ROOT}/common/start-observer-node.sh"
export CONFIG_APACHE_SCRIPT="${REPO_ROOT}/common/config-apache.sh"
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
export OBS_MACHINE_TYPE="e2-standard-2"
export OBS_HOSTNAME="obs.devnet.telcoin.network"   # A record -> OBS static IP (out of band)
export OBS_STATIC_IP_NAME="obs-devnet-ip"     # reserved by common/create-obs-instance.sh
export OBS_DATA_DISK_NAME="obs-devnet-data"   # persistent disk for Loki chunks + Grafana DB
export OBS_DATA_DISK_SIZE=100                 # GB; devnet 1h epochs, shorter retention than adiri
# Image FAMILY (not a dated build) so the VM always provisions on the latest
# non-deprecated Debian 12 image — a pinned dated image goes deprecated over time
# and makes `gcloud compute instances create` print a deprecation warning.
export OBS_IMAGE="projects/debian-cloud/global/images/family/debian-12"
# Log-push endpoint and bearer-token plumbing. OBS_PUSH_URL is seeded into each
# node's metadata by seed-node-token.sh — that is what points devnet's nodes at
# THIS obs VM rather than the adiri default baked into start-*-node.sh.
export OBS_PUSH_URL="https://${OBS_HOSTNAME}/loki/api/v1/push"
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
