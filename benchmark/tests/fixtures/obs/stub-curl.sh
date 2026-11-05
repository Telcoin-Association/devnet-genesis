#!/usr/bin/env bash
# Stand-in for curl (test_obs.py). Every call appends its arguments, space-joined, to
# $FAKE_ROOT/curl-calls. Answers:
#   -XPOST <url>/admin/tsdb/snapshot   {"status":"success","data":{"name":"$FAKE_SNAPSHOT_NAME"}};
#                                      rc 7 when $FAKE_ROOT/curl-snapshot-fail exists
#   <url>/query?query=up, <url>/api/health
#                                      an answer once $FAKE_TUNNEL_LOG holds a `tunnel: start` line
#                                      for the URL's local port (the forward is up), else rc 7;
#                                      $FAKE_ROOT/prom-down fails the Prometheus query and
#                                      $FAKE_ROOT/grafana-down the Grafana health check even then
# Anything else: rc 2.
printf '%s\n' "$*" >> "${FAKE_ROOT:?}/curl-calls"
url=""; post=0
for a in "$@"; do
    case "${a}" in http://*|https://*) url="${a}" ;; -XPOST) post=1 ;; esac
done
port="${url#http://127.0.0.1:}"; port="${port%%/*}"
forward_up() { grep -q "^tunnel: start .* local=${port} " "${FAKE_TUNNEL_LOG:?}" 2>/dev/null; }
case "${url}" in
    */admin/tsdb/snapshot)
        [ "${post}" = 1 ] || { echo "stub curl: the snapshot needs -XPOST" >&2; exit 2; }
        [ ! -e "${FAKE_ROOT}/curl-snapshot-fail" ] || { echo "curl: (7) Failed to connect to 127.0.0.1 port ${port}" >&2; exit 7; }
        printf '{"status":"success","data":{"name":"%s"}}\n' "${FAKE_SNAPSHOT_NAME:-20261105T120000Z-1a2b3c4d5e6f7a8b}" ;;
    */query\?query=up)
        forward_up && [ ! -e "${FAKE_ROOT}/prom-down" ] || exit 7
        echo '{"status":"success","data":{"resultType":"vector","result":[]}}' ;;
    */api/health)
        forward_up && [ ! -e "${FAKE_ROOT}/grafana-down" ] || exit 7
        echo '{"database":"ok","version":"11.4.0"}' ;;
    *)
        echo "stub curl: unexpected call: $*" >&2; exit 2 ;;
esac
