#!/usr/bin/env bash
# Stand-in for the harness's `perl -e 'alarm shift; exec @ARGV' <secs> <cmd...>` (test_teardown_local_gate.py,
# test_collect_retry.py): records <secs> and the command name in $FAKE_ROOT/alarms, then execs the
# command. Any other perl use fails, so a test notices a call shape it does not model.
if [ "${1:-}" != "-e" ] || [ "${2:-}" != 'alarm shift; exec @ARGV' ]; then
    echo "stub perl: unexpected arguments: $*" >&2
    exit 2
fi
printf '%s %s\n' "$3" "$4" >> "${FAKE_ROOT:?}/alarms"
# FAKE_DESCRIBE_AWAITS_DELETE=1: the teardown's delete wait describes each instance through this wrapper
# right after issuing its delete in the background; hold such a describe (up to 10 s) until the fake's
# delete has landed (deleting.json names <zone>/<name>), so it never races the delete.
if [ -n "${FAKE_DESCRIBE_AWAITS_DELETE:-}" ] && [ "$4 $5 $6 $7" = "gcloud compute instances describe" ]; then
    zone=""
    for a in "$@"; do case "$a" in --zone=*) zone="${a#--zone=}" ;; esac; done
    n=0
    while [ "${n}" -lt 200 ] && ! grep -qF "\"${zone}/$8\"" "${FAKE_ROOT}/deleting.json" 2>/dev/null; do
        command -p sleep 0.05; n=$((n + 1))
    done
fi
shift 3
exec "$@"
