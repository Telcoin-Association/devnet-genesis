# CONFIG_FILE for benchmark/tests/test_keygen.py: a four-node fleet, three validators and one
# observer, with only what devnet-lib.sh and devnet-keygen.sh read. KG_ROOT is set by the test
# (the sandbox: REPO_ROOT, so the per-run log dir lands there) and GENESIS_WORKSPACE is the
# sandbox's workspace dir, where the node-info files are collected.
# shellcheck disable=SC2034  # sourced: devnet-lib.sh and devnet-keygen.sh read REPO_ROOT (unexported, as config.sh)
REPO_ROOT="${KG_ROOT:?KG_ROOT is set by test_keygen}"
export PROJECT_ID="kg-project"
export INSTANCE_NAMES=("kg-validator-1" "kg-validator-2" "kg-validator-3" "kg-observer-4")
export NODE_ROLES=("validator" "validator" "validator" "observer")
export ZONES=("zone-a1" "zone-b1" "zone-c1" "zone-d1")
export NODE_NAMES=("node1" "node2" "node3" "node4")
export EXECUTION_ADDRESSES=("0x1111111111111111111111111111111111111111" "0x2222222222222222222222222222222222222222" "0x3333333333333333333333333333333333333333" "0x4444444444444444444444444444444444444444")
export DOCKER_IMAGE="registry.example.invalid/tn/node@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
export DEFAULT_PRIMARY_UDP_PORT=49590
export DEFAULT_WORKER_UDP_PORT=49594
export BASE_DOMAIN="example.invalid"
export SERVICE_USER="telcoin"
export TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"
export VALIDATOR_DATA_DIR="/var/lib/telcoin"
export OBSERVER_DATA_DIR="/var/lib/telcoin"
export GENESIS_WORKSPACE="${KG_WORKSPACE:?KG_WORKSPACE is set by test_keygen}"
