#!/usr/bin/env bash
# curl on a fake node (tests/test_params_apply.py): the node's JSON-RPC answers eth_chainId.
printf 'curl %s\n' "$*" >> "${STUB_NODE_DIR:?}/calls.log"
case "$*" in
    *eth_chainId*) printf '{"jsonrpc":"2.0","id":1,"result":"0x7e1e"}' ;;
    *) echo "fake curl: unexpected: $*" >&2; exit 7 ;;
esac
