#!/usr/bin/env bash
# curl on the node: the metadata server's internal IP, the node's JSON-RPC (chain id
# $STUB_CHAIN_HEX; a block number that rises by one per call, kept in $STUB_STATE/block), and
# bench-obs's Prometheus readiness (http://<ip>:9090/-/ready, step 8): ready, or with
# STUB_OBS_READY=0 unreachable (rc 7, curl's "failed to connect").
printf 'curl %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    *metadata.google.internal*) printf '192.0.2.7' ;;
    *eth_chainId*) printf '{"jsonrpc":"2.0","id":1,"result":"%s"}' "${STUB_CHAIN_HEX:?}" ;;
    *eth_blockNumber*)
        f="${STUB_STATE:?}/block"; n=3; [ ! -f "${f}" ] || n="$(cat "${f}")"; n=$((n + 1)); echo "${n}" > "${f}"
        printf '{"jsonrpc":"2.0","id":1,"result":"0x%x"}' "${n}" ;;
    *:9090/-/ready*) [ "${STUB_OBS_READY:-1}" = 1 ] || exit 7; echo "Prometheus Server is Ready." ;;
    *) echo "stub curl: unexpected: $*" >&2; exit 7 ;;
esac
