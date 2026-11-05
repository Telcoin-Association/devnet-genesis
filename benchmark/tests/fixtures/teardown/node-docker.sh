#!/usr/bin/env bash
# Stand-in for docker on a sandbox node of fake-gcloud.py (test_teardown_local_gate.py). The node
# has a telcoin container when <node>/docker.log exists; `docker logs telcoin` prints that file.
node="$(cd "$(dirname "$0")/.." && pwd)"
case "$*" in
    "container inspect telcoin")
        [ -f "${node}/docker.log" ] && exit 0
        echo "Error: No such container: telcoin" >&2; exit 1 ;;
    "logs telcoin")
        [ -f "${node}/docker.log" ] || { echo "Error: No such container: telcoin" >&2; exit 1; }
        cat "${node}/docker.log" ;;
    *) echo "stub docker: unexpected arguments: $*" >&2; exit 2 ;;
esac
