#!/usr/bin/env bash
# Read-only. From START (UTC, HH:MM:SS today) run epoch-reads.sh every INTERVAL seconds and append to
# allowlist-watch.log; stop when node 5's address is in the nft set of all four validators, or at END.
# Usage: bash tasks/l2/w3/s1/allowlist-watch.sh 03:25:15 04:20:00 [interval_secs] [label-prefix]
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." || exit 1
start="$(date -u -d "$1" +%s)"; end="$(date -u -d "$2" +%s)"; interval="${3:-120}"; prefix="${4:-n1}"
log="tasks/l2/w3/s1/allowlist-watch.log"
now="$(date -u +%s)"; [ "${now}" -lt "${start}" ] && sleep "$((start - now))"
k=0
while [ "$(date -u +%s)" -lt "${end}" ]; do
    k=$((k + 1)); t0="$(date -u +%s)"
    out="$(bash tasks/l2/w3/s1/epoch-reads.sh "${prefix}-$(date -u +%H%M%S)" 2>&1)"
    printf '%s\n\n' "${out}" >> "${log}"
    hits="$(printf '%s\n' "${out}" | grep -c -E '^validator-[0-9]-devnet .*NFTHITS=[1-9]')"
    echo "$(date -u +%FT%TZ) read ${k}: node 5's address in the set on ${hits} of 4 validators"
    if [ "${hits}" -eq 4 ]; then echo "ALL FOUR at $(date -u +%FT%TZ)"; exit 0; fi
    spent=$(( $(date -u +%s) - t0 )); [ "${spent}" -lt "${interval}" ] && sleep "$((interval - spent))"
done
echo "END reached without all four"; exit 3
