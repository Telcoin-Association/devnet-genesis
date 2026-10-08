#!/usr/bin/env bash
# Stand-in for the harness's `perl -e 'alarm shift; exec @ARGV' <secs> <cmd...>` (test_teardown_local_gate.py,
# test_collect_retry.py): records <secs> and the command name in $FAKE_ROOT/alarms, then execs the
# command. Any other perl use fails, so a test notices a call shape it does not model.
if [ "${1:-}" != "-e" ] || [ "${2:-}" != 'alarm shift; exec @ARGV' ]; then
    echo "stub perl: unexpected arguments: $*" >&2
    exit 2
fi
printf '%s %s\n' "$3" "$4" >> "${FAKE_ROOT:?}/alarms"
shift 3
exec "$@"
