#!/usr/bin/env bash
# Stand-in for curl (test_teardown_local_gate.py): every call is logged to $STUB_LOG. Only bench-obs's
# Prometheus, through its local forward, answers: the TSDB snapshot POST (.../admin/tsdb/snapshot)
# names the snapshot as Prometheus does ($FAKE_PROM_SNAPSHOT, or a default), and the two forwards'
# probes (/query?query=up, /api/health) succeed. Anything else is network access: it fails, as
# fixtures/node-image/stub-curl-forbidden.sh does.
printf 'curl %s\n' "$*" >> "${STUB_LOG:?}"
case " $* " in
    *"/admin/tsdb/snapshot "*)
        printf '{"status":"success","data":{"name":"%s"}}\n' "${FAKE_PROM_SNAPSHOT:-20991231T090500Z-0123456789abcdef}"
        exit 0 ;;
    *"/query?query=up "*) echo '{"status":"success","data":{"resultType":"vector","result":[]}}'; exit 0 ;;
    *"/api/health "*) echo '{"database":"ok","version":"11.4.0"}'; exit 0 ;;
esac
echo "stub curl: network access attempted: $*" >&2
exit 97
