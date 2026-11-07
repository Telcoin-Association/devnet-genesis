#!/usr/bin/env bash
# Stand-in for sudo on a fake node (test_pull_logs.py fleet tests): the session already runs as the
# test's user, so the command runs as given.
exec "$@"
