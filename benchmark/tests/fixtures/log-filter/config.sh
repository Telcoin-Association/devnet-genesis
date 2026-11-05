# shellcheck shell=bash
# CONFIG_FILE for benchmark/tests/test_log_filter.py: the devnet fleet's layout (four validators, then
# the observer at index 4) with fake zones and project, and only what devnet-lib.sh and
# devnet-log-filter.sh read.
export PROJECT_ID="lf-project"
export INSTANCE_NAMES=("validator-1-devnet" "validator-2-devnet" "validator-3-devnet" "validator-4-devnet" "observer-5-devnet")
export NODE_ROLES=("validator" "validator" "validator" "validator" "observer")
export ZONES=("zone-a1" "zone-b1" "zone-c1" "zone-d1" "zone-e1")
export NODE_NAMES=("node1" "node2" "node3" "node4" "node5")
export TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"
export DEFAULT_HEALTHCHECK_TCP_PORT=43174
