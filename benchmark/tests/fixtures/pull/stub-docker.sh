#!/usr/bin/env bash
# Stand-in for docker on a fake node (test_pull_logs.py fleet tests): the telcoin container of node
# $FAKE_NODE exists when $FAKE_ROOT/nodes/$FAKE_NODE/container.log does, and that file is its log.
log="${FAKE_ROOT:?}/nodes/${FAKE_NODE:?}/container.log"
case "$*" in
    "container inspect telcoin")
        [ -f "${log}" ] && exit 0
        echo "Error: No such container: telcoin" >&2; exit 1 ;;
    "logs telcoin")
        [ -f "${log}" ] || { echo "Error: No such container: telcoin" >&2; exit 1; }
        cat "${log}" ;;
    *)
        echo "stub docker: unexpected arguments: $*" >&2; exit 2 ;;
esac
