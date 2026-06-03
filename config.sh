#
# GLOBAL VARIABLES
#

#
# Docker Image
#
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-v3-patch" # steve patch for v3
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.4-adiri-patch-bootstrap"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.5-adiri-crash-2-banned-peers-patch"
export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-pm-patch"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-pm-patch-3"
# export DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.9.2-adiri-pm-patch-3-dup-batches"

#
# GCP
#
# NOTE: dead variable - retained for future observer support but no longer referenced.
export OBSERVER_INSTANCE="observer-validator-5"
# 1 - LA
# 2 - Australia
# 3 - Montreal
# 4 - Netherlands
# 5 - London
export VALIDATOR_NAMES=("validator-1-adiri" "validator-2-adiri" "validator-3-adiri" "validator-4-adiri" "validator-5-adiri")
export INSTANCE_NAMES=("validator-1-adiri" "validator-2-adiri" "validator-3-adiri" "validator-4-adiri" "validator-5-adiri")
export ZONES=("us-west2-a" "australia-southeast1-c" "northamerica-northeast1-b" "europe-west4-a" "europe-west2-b")
# export INSTANCE_NAMES=("validator-1-adiri")
# export ZONES=("us-west2-a")
export NODE_NAMES=("node1" "node2" "node3" "node4" "node5")
# export _REGIONS=("us-west2" "us-east4" "us-east5" "us-central1" "us-central1")
export EXTERNAL_IPS=("34.102.122.126" "34.40.242.29" "35.203.41.59" "34.141.203.172" "34.105.191.161")
export INTERNAL_IPS=("10.168.0.7" "10.152.0.6" "10.162.0.6" "10.164.0.44" "10.154.0.46")
export EXECUTION_ADDRESSES=("0x3518b301b86ceb53b5a3dff62e55cd43ef59d024" "0x7489025dfbaad94f2366d88a62989147d9c8b5d3" "0x0033a370616805b1fd275b7ffab83fc41d665ccb" "0xefaacf04b92298a88200aa50aa6bb7bfce587b17" "0x89dab9f6fdc569c1bcdbd6493f25b7040b55dc79")
export PROJECT_ID="tn-devnet"
export MACHINE_TYPE="e2-custom-4-8192"
export SERVICE_ACCOUNT="1095385745561-compute@developer.gserviceaccount.com"
export IMAGE="projects/debian-cloud/global/images/debian-12-bookworm-v20251111"
export STARTUP_SCRIPT_PATH="startup.sh"
export DEFAULT_PRIMARY_UDP_PORT=49590
export DEFAULT_WORKER_UDP_PORT=49594
export DEFAULT_HEALTHCHECK_TCP_PORT=43174
#
# Global L7 Load Balancer (rpc.telcoin.network)
#
export LB_NAME_PREFIX="adiri-rpc"
export LB_HOSTNAME="rpc.telcoin.network"
export LB_HEALTH_CHECK_NAME="adiri-rpc-hc"
export LB_BACKEND_SERVICE="adiri-rpc-backend"
export LB_URL_MAP="adiri-rpc-urlmap"
export LB_SSL_CERT="adiri-rpc-cert"
export LB_HTTPS_PROXY="adiri-rpc-https-proxy"
export LB_FORWARDING_RULE="adiri-rpc-fr"
export LB_GLOBAL_IP_NAME="adiri-rpc-ip"
export LB_FIREWALL_RULE="adiri-lb-allow-health-check"
#
# PATHS
#
export GENESISDIR="genesis/validators/"
export LOCAL_PATH="./genesis/validators/"
export REMOTE_VALIDATORS_PATH="/home/share"
export REMOTE_SHARE_PATH="/home/share/"
export GENESIS_FILE="./genesis/genesis.yaml"
export PARAMETERS_FILE="./parameters.yaml"
export COMMITTEE_FILE="./genesis/committee.yaml"
export UPLOAD_COMMITTEE_SCRIPT="./copy-committee.sh"
export START_VALIDATOR_NODE_SCRIPT="./start-validator-node.sh"
# NOTE: dead variable - retained for future observer support but no longer referenced.
export START_OBSERVER_NODE_SCRIPT="./start-observer-node.sh"
export CONFIG_APACHE_SCRIPT="./config-apache.sh"
