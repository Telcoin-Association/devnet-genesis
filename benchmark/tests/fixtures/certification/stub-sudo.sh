#!/usr/bin/env bash
# Stand-in for sudo on a fake node (test_certification.py): runs the command as given, with the
# node's log directory ($FAKE_NODE_LOG_DIR, the harness's BENCH_NODE_LOG_DIR) mapped to this node's
# own directory, $FAKE_ROOT/nodes/$FAKE_NODE. So the harness's real remote scripts (the log save,
# the saved-log tar) run here, unchanged, against a directory per node.
args=()
for a in "$@"; do
    if [ "${a}" = "${FAKE_NODE_LOG_DIR:?}" ]; then args+=("${FAKE_ROOT:?}/nodes/${FAKE_NODE:?}"); else args+=("${a}"); fi
done
exec "${args[@]}"
