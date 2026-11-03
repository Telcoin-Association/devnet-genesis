#!/usr/bin/env bash
# date on a sandbox v2 node: `date +%s` is a clock that advances one second per call (state in
# $STUB_STATE/clock, from 1767225700), so a wait loop ends after a bounded number of polls;
# `date -d <the container's StartedAt> +%s` answers 1767225600 (2026-01-01T00:00:00Z).
case "$*" in
    "+%s")
        f="${STUB_STATE:?}/clock"; n=1767225700; [ ! -f "${f}" ] || n="$(cat "${f}")"; n=$((n + 1)); echo "${n}" > "${f}"
        echo "${n}" ;;
    "-d "?*" +%s") printf 'date %s\n' "$*" >> "${STUB_LOG:?}"; echo 1767225600 ;;
    *) echo "stub date: unexpected: $*" >&2; exit 3 ;;
esac
