#!/usr/bin/env bash
# Stand-in for sudo on a sandbox node of fake-gcloud.py (test_teardown_local_gate.py): runs the
# command as the caller. The sandbox is <node>/, with <node>/bin first on PATH.
exec "$@"
