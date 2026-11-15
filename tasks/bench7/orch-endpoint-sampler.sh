#!/usr/bin/env bash
# orch-endpoint-sampler.sh — bench 7, orchestrator only. Saves each node's OWN metrics text (the node's
# exporter on 127.0.0.1:9101, the text the metrics agent scrapes) at an interval, because the agent's remote
# write loses one batch per scrape on some nodes (tasks/checkpoint-bench7-orch.md, 12:40Z and 14:28Z of
# 2026-11-15): what Prometheus lacks for a node is recovered from these files (cumulative since the node
# process started).
# Read-only on the fleet: one ssh per node per round, `curl` of the node's exporter, nothing else.
#   tasks/bench7/orch-endpoint-sampler.sh <run> <out-dir> [--once] [--interval <secs>] [--until-file <segment log>]
#                                         [--max-secs <n>] [--nodes <name,name,...>]
# Per round one line:
#   ENDPOINT_SAMPLE run=<run> round=<n> ok=<n>/<nodes> failed=<node,...|-> <UTC>
# Files: <out-dir>/<node>-metrics-<UTC compact>.txt.gz (a failed read leaves no file).
# Ends: --once after one round; with --until-file when that file holds "== <segment> rc=" or
# "== <segment> LEFT_RUNNING " (one more round is taken after the end line); after --max-secs [10800].
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${SAMPLER_ROOT:-$(cd "${SELF_DIR}/../.." && pwd)}"
PROJECT="${SAMPLER_PROJECT:-tn-devnet}"
utc() { date -u +%FT%TZ; }
run="${1:?run id}"; out="${2:?out dir}"; shift 2
once=0; interval=60; until_file=""; max_secs=10800; only=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --once) once=1; shift ;;
        --interval) interval="${2:?}"; shift 2 ;;
        --until-file) until_file="${2:?}"; shift 2 ;;
        --max-secs) max_secs="${2:?}"; shift 2 ;;
        --nodes) only="${2:?}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
manifest="${ROOT}/benchmark/results/${run}/manifest.json"
[ -r "$manifest" ] || { echo "no manifest: $manifest" >&2; exit 2; }
mapfile -t pairs < <(python3 - "$manifest" "$only" <<'EOF'
import json, sys
z = json.load(open(sys.argv[1]))["zones_used"]
only = [n for n in sys.argv[2].split(",") if n]
for name in sorted(z):
    if not only or name in only:
        print(name, z[name])
EOF
)
[ "${#pairs[@]}" -gt 0 ] || { echo "no nodes" >&2; exit 2; }
mkdir -p "$out"
one() { # <node> <zone> <stamp>: 0 when a valid gzip with series was written
    local node="$1" zone="$2" stamp="$3" f tmp
    f="${out}/${node}-metrics-${stamp}.txt.gz"; tmp="${f}.part"
    timeout 50 gcloud compute ssh "$node" --zone="$zone" --project="$PROJECT" --tunnel-through-iap --quiet \
        --command 'curl -s --max-time 10 http://127.0.0.1:9101/metrics | gzip -1 | base64 -w0' \
        2>>"${out}/ssh.err" </dev/null | base64 -d >"$tmp" 2>/dev/null
    if gzip -t "$tmp" 2>/dev/null && [ "$(zcat "$tmp" | grep -vc '^#')" -gt 1000 ]; then
        mv "$tmp" "$f"; return 0
    fi
    rm -f "$tmp"; return 1
}
start=$(date +%s); round=0; ended=0
while :; do
    round=$((round + 1)); stamp="$(date -u +%Y%m%dT%H%M%SZ)"; t0=$(date +%s)
    rm -f "${out}/.fail."*
    for p in "${pairs[@]}"; do
        set -- $p
        ( one "$1" "$2" "$stamp" || : >"${out}/.fail.$1" ) &
    done
    wait
    failed="$(ls -a "$out" | sed -n 's/^\.fail\.//p' | paste -sd, -)"; rm -f "${out}/.fail."*
    nfail=0; [ -n "$failed" ] && nfail=$(( $(printf '%s' "$failed" | tr -cd , | wc -c) + 1 ))
    echo "ENDPOINT_SAMPLE run=${run} round=${round} ok=$(( ${#pairs[@]} - nfail ))/${#pairs[@]} failed=${failed:--} $(utc)"
    [ "$once" = 1 ] && break
    [ "$ended" = 1 ] && { echo "ENDPOINT_SAMPLE the segment ended; last round taken $(utc)"; break; }
    now=$(date +%s)
    [ $(( now - start )) -ge "$max_secs" ] && { echo "ENDPOINT_SAMPLE max-secs=${max_secs} reached $(utc)"; break; }
    left=$(( interval - (now - t0) )); [ "$left" -gt 0 ] && sleep "$left"
    if [ -n "$until_file" ] && grep -qE '^== [a-z0-9-]+ (rc=|LEFT_RUNNING )' "$until_file" 2>/dev/null; then ended=1; fi
done
