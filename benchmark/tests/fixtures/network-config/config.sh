# CONFIG_FILE for benchmark/tests/test_network_config.py: five nodes, three validators (node1 is
# the hub) and two observers, with only what devnet-lib.sh and devnet-network-config.sh read. The
# test sets NETCFG_TREE (the sandbox copy of the scripts) and NETCFG_WORKSPACE (whose genesis/ holds
# copies of fleet/committee.yaml, fleet/validators and fleet/observers; benchmark/.gitignore ignores
# every genesis/ dir, hence the fixture's own name for it).
# shellcheck disable=SC2034  # read by the scripts that source this file
REPO_ROOT="${NETCFG_TREE:?NETCFG_TREE is set by test_network_config}"
export PROJECT_ID="nc-project"
export INSTANCE_NAMES=("nc-validator-1" "nc-validator-2" "nc-validator-3" "nc-observer-4" "nc-observer-5")
export NODE_ROLES=("validator" "validator" "validator" "observer" "observer")
export ZONES=("zone-a1" "zone-b1" "zone-c1" "zone-d1" "zone-e1")
export NODE_NAMES=("node1" "node2" "node3" "node4" "node5")
export SERVICE_USER="telcoin"
export TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"
export VALIDATOR_DATA_DIR="/var/lib/telcoin"
export OBSERVER_DATA_DIR="/var/lib/telcoin"
export VALIDATOR_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"
export OBSERVER_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"
export GENESIS_WORKSPACE="${NETCFG_WORKSPACE:?NETCFG_WORKSPACE is set by test_network_config}"
