#!/usr/bin/env bash
# curl on the operator's host for the bench-obs forwards (test_node_image.py Step8Tests): bench-obs's
# Prometheus on 127.0.0.1:19090 and Grafana on 127.0.0.1:13000 answer as freshly brought up; anything
# else is the network: logged and refused (rc 97), as stub-curl-forbidden.sh.
printf 'curl %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    *127.0.0.1:19090/api/v1/query*) printf '{"status":"success","data":{"resultType":"vector","result":[]}}\n' ;;
    *127.0.0.1:19090/-/ready*) echo "Prometheus Server is Ready." ;;
    *127.0.0.1:13000/api/health*) printf '{"commit":"x","database":"ok","version":"11.4.0"}\n' ;;
    *) echo "stub curl: network access attempted: $*" >&2; exit 97 ;;
esac
