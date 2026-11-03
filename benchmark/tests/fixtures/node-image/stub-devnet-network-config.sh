#!/usr/bin/env bash
# devnet-network-config.sh stand-in, copied over the repo-root script in a test tree
# (test_node_image.py Step7Tests): logs its argv and CONFIG_FILE to $STUB_LOG; exit $STUB_NETCFG_RC.
printf 'devnet-network-config.sh %s CONFIG_FILE=%s\n' "$*" "${CONFIG_FILE:-}" >> "${STUB_LOG:?}"
exit "${STUB_NETCFG_RC:-0}"
