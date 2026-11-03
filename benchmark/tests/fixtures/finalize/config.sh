# CONFIG_FILE for benchmark/tests/test_finalize_modes.py: a three-node fleet, two validators and
# one observer, with only what devnet-lib.sh and devnet-finalize.sh read. Both set by the test:
# FIN_FIX is this directory (finalize-parameters.yaml is PARAMETERS_FILE), FIN_WORKSPACE the
# sandbox's GENESIS_WORKSPACE, whose genesis/ holds copies of committee.yaml and genesis.yaml
# (benchmark/.gitignore ignores every genesis/ dir and parameters.yaml, hence the names here).
# The script checks those three files exist and scp's them (to the fake gcloud).
REPO_ROOT="${FIN_FIX:?FIN_FIX is set by test_finalize_modes}"
export PROJECT_ID="fin-project"
export INSTANCE_NAMES=("fin-validator-1" "fin-validator-2" "fin-observer-3")
export NODE_ROLES=("validator" "validator" "observer")
export ZONES=("zone-a1" "zone-b1" "zone-c1")
export NODE_NAMES=("node1" "node2" "node3")
export EXECUTION_ADDRESSES=("0x1111111111111111111111111111111111111111" "0x2222222222222222222222222222222222222222" "0x3333333333333333333333333333333333333333")
export DOCKER_IMAGE="registry.example.invalid/tn/node@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
export RELEASE_TAG=""
export DEFAULT_PRIMARY_UDP_PORT=49590
export DEFAULT_WORKER_UDP_PORT=49594
export DEFAULT_HEALTHCHECK_TCP_PORT=43174
export BASE_DOMAIN="example.invalid"
export SERVICE_USER="telcoin"
export TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"
export VALIDATOR_DATA_DIR="/var/lib/telcoin"
export OBSERVER_DATA_DIR="/var/lib/telcoin"
export VALIDATOR_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"
export OBSERVER_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"
export GENESIS_WORKSPACE="${FIN_WORKSPACE:?FIN_WORKSPACE is set by test_finalize_modes}"
export PARAMETERS_FILE="${REPO_ROOT}/finalize-parameters.yaml"
