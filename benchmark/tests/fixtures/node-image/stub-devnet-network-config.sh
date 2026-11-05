#!/usr/bin/env bash
# devnet-network-config.sh stand-in, copied over the repo-root script in a test tree
# (test_node_image.py Step7Tests): logs its argv and CONFIG_FILE to $STUB_LOG; exit $STUB_NETCFG_RC.
printf 'devnet-network-config.sh %s CONFIG_FILE=%s\n' "$*" "${CONFIG_FILE:-}" >> "${STUB_LOG:?}"
# STUB_NETCFG_STRAY=<secs>: leave a child behind that holds this script's stdout (the deploy log's FIFO)
# for that long, then prints a line (test_node_image.py: the result line must stay the last one).
[ -z "${STUB_NETCFG_STRAY:-}" ] || ( sleep "${STUB_NETCFG_STRAY}"; echo "STRAY LINE from a leftover child" ) &
exit "${STUB_NETCFG_RC:-0}"
