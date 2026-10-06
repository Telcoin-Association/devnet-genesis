#!/usr/bin/env bash
# date on the node: `date +%s` is a counter that advances one second per call (state in
# $STUB_STATE/clock), so the remote script's wait loop ends after a bounded number of polls.
[ "$*" = "+%s" ] || { echo "stub date: unexpected: $*" >&2; exit 3; }
f="${STUB_STATE:?}/clock"; n=1700000000; [ ! -f "${f}" ] || n="$(cat "${f}")"; n=$((n + 1)); echo "${n}" > "${f}"
echo "${n}"
