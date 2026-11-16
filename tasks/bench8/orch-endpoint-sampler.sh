#!/usr/bin/env bash
# orch-endpoint-sampler.sh — bench 8 (bench 7's sampler plus --stop-file and --parent-pid, so the run chain
# runs it as a segment; the project from config.sh), orchestrator only. Saves each node's OWN metrics text (the node's
# exporter on 127.0.0.1:9101, the text the metrics agent scrapes) at an interval, because the agent's remote
# write loses one batch per scrape on some nodes (tasks/checkpoint-bench7-orch.md, 12:40Z and 14:28Z of
# 2026-11-15): what Prometheus lacks for a node is recovered from these files (cumulative since the node
# process started).
# Read-only on the fleet: one ssh per node per round. In that one session: `curl` of the node's exporter, the
# time daemon's status (`chronyc -n tracking`, else `timedatectl timesync-status`, else the word none), the
# first line of /proc/stat and `getconf CLK_TCK`; nothing else.
#   tasks/bench8/orch-endpoint-sampler.sh <run> <out-dir> [--once] [--interval <secs>] [--until-file <segment log>]
#                                         [--max-secs <n>] [--nodes <name,name,...>] [--stop-file <file>]
#                                         [--parent-pid <pid>]
# Per round one line:
#   ENDPOINT_SAMPLE run=<run> round=<n> ok=<n>/<nodes> failed=<node,...|-> host=<ok|missing:node,...> <UTC>
# Files: <out-dir>/<node>-metrics-<UTC compact>.txt.gz (a failed read leaves no file) and, beside it,
# <out-dir>/<node>-host-<UTC compact>.txt (the host readings; none when the block is missing or malformed,
# and the node is then named in host=missing:). The session prints the metrics payload as before (one base64
# line), a line break, the marker line TN_HOST_READINGS_V1, then the host block, which is saved as printed:
#   clock <chrony|timesyncd|none>
#   <chrony's "Last offset", "RMS offset", "System time" lines | timesyncd's "Offset:" line | nothing>
#   cpu <user> <nice> <system> <idle> <iowait> <irq> <softirq> <steal> ...   (jiffies since boot)
#   clk_tck <n>
# Everything before the marker line is the payload; a session without the marker still saves the metrics.
# Reader: tasks/bench8/orch-host-readings.py <out-dir>.
# Ends: --once after one round; with --until-file when that file holds "== <segment> rc=" or
# "== <segment> LEFT_RUNNING " (one more round is taken after the end line); after --max-secs [10800]; at once
# (checked every second, no further round) when the --stop-file exists or the --parent-pid process is gone:
#   ENDPOINT_SAMPLE stop-file <name> seen; ended <UTC>  |  ENDPOINT_SAMPLE parent pid=<pid> gone; ended <UTC>
# The project: SAMPLER_PROJECT, else PROJECT_ID of <root>/config.sh.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${SAMPLER_ROOT:-$(cd "${SELF_DIR}/../.." && pwd)}"
PROJECT="${SAMPLER_PROJECT:-}"
[ -n "$PROJECT" ] || PROJECT="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}PROJECT_ID="\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\2/p' "${ROOT}/config.sh" 2>/dev/null | head -n 1)"
[ -n "$PROJECT" ] || { echo "no project: set SAMPLER_PROJECT or PROJECT_ID in ${ROOT}/config.sh" >&2; exit 2; }
utc() { date -u +%FT%TZ; }
run="${1:?run id}"; out="${2:?out dir}"; shift 2
once=0; interval=60; until_file=""; max_secs=10800; only=""; stop_file=""; parent_pid=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --once) once=1; shift ;;
        --interval) interval="${2:?}"; shift 2 ;;
        --until-file) until_file="${2:?}"; shift 2 ;;
        --max-secs) max_secs="${2:?}"; shift 2 ;;
        --nodes) only="${2:?}"; shift 2 ;;
        --stop-file) stop_file="${2:?}"; shift 2 ;;
        --parent-pid) parent_pid="${2:?}"; shift 2 ;;
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
HOST_MARK=TN_HOST_READINGS_V1
# The session's command: the metrics payload exactly as before, then the marker line, then the host block.
# A missing chronyc or timedatectl only leaves its reading empty; the session never fails on it.
REMOTE='curl -s --max-time 10 http://127.0.0.1:9101/metrics | gzip -1 | base64 -w0; echo; echo '"${HOST_MARK}"'; '\
'c="$(chronyc -n tracking 2>/dev/null | grep -E "^(Last offset|RMS offset|System time) ")"; '\
'if [ -n "$c" ]; then echo "clock chrony"; printf "%s\n" "$c"; '\
'else c="$(timedatectl timesync-status 2>/dev/null | grep -E "^ *Offset:")"; '\
'if [ -n "$c" ]; then echo "clock timesyncd"; printf "%s\n" "$c"; else echo "clock none"; fi; fi; '\
'head -n 1 /proc/stat; echo "clk_tck $(getconf CLK_TCK)"'
# host_ok <file>: 0 when it holds one clock line, one aggregate cpu line with 8 counters and one clk_tck line.
host_ok() {
    awk '$1 == "clock" && NF == 2 && ($2 == "chrony" || $2 == "timesyncd" || $2 == "none") { c++ }
         $1 == "cpu" && NF >= 9 { ok = 1; for (i = 2; i <= 9; i++) if ($i !~ /^[0-9]+$/) ok = 0; if (ok) p++ }
         $1 == "clk_tck" && NF == 2 && $2 ~ /^[0-9]+$/ && $2 > 0 { k++ }
         END { exit !(c == 1 && p == 1 && k == 1) }' "$1" 2>/dev/null
}
one() { # <node> <zone> <stamp>: 0 when a valid gzip with series was written; .nohost.<node> without host readings
    local node="$1" zone="$2" stamp="$3" f tmp raw h
    f="${out}/${node}-metrics-${stamp}.txt.gz"; tmp="${f}.part"; raw="${out}/.ssh.${node}"
    h="${out}/${node}-host-${stamp}.txt"
    timeout 50 gcloud compute ssh "$node" --zone="$zone" --project="$PROJECT" --tunnel-through-iap --quiet \
        --command "$REMOTE" 2>>"${out}/ssh.err" </dev/null >"$raw"
    awk -v m="$HOST_MARK" '$0 == m { exit } { print }' "$raw" | base64 -d >"$tmp" 2>/dev/null
    awk -v m="$HOST_MARK" 'f { print } $0 == m { f = 1 }' "$raw" >"${h}.part"
    if host_ok "${h}.part"; then mv "${h}.part" "$h"; else rm -f "${h}.part"; : >"${out}/.nohost.${node}"; fi
    rm -f "$raw"
    if gzip -t "$tmp" 2>/dev/null && [ "$(zcat "$tmp" | grep -vc '^#')" -gt 1000 ]; then
        mv "$tmp" "$f"; return 0
    fi
    rm -f "$tmp"; return 1
}
# stop_reason — prints why the caller wants the sampler to end now; non-zero when it does not.
stop_reason() {
    if [ -n "$stop_file" ] && [ -e "$stop_file" ]; then echo "stop-file ${stop_file##*/} seen"; return 0; fi
    if [ -n "$parent_pid" ] && ! kill -0 "$parent_pid" 2>/dev/null; then echo "parent pid=${parent_pid} gone"; return 0; fi
    return 1
}
start=$(date +%s); round=0; ended=0
while :; do
    round=$((round + 1)); stamp="$(date -u +%Y%m%dT%H%M%SZ)"; t0=$(date +%s)
    rm -f "${out}/.fail."* "${out}/.nohost."*
    for p in "${pairs[@]}"; do
        set -- $p
        ( one "$1" "$2" "$stamp" || : >"${out}/.fail.$1" ) &
    done
    wait
    failed="$(ls -a "$out" | sed -n 's/^\.fail\.//p' | paste -sd, -)"; rm -f "${out}/.fail."*
    nfail=0; [ -n "$failed" ] && nfail=$(( $(printf '%s' "$failed" | tr -cd , | wc -c) + 1 ))
    nohost="$(ls -a "$out" | sed -n 's/^\.nohost\.//p' | paste -sd, -)"; rm -f "${out}/.nohost."*
    echo "ENDPOINT_SAMPLE run=${run} round=${round} ok=$(( ${#pairs[@]} - nfail ))/${#pairs[@]} failed=${failed:--} host=${nohost:+missing:}${nohost:-ok} $(utc)"
    [ "$once" = 1 ] && break
    [ "$ended" = 1 ] && { echo "ENDPOINT_SAMPLE the segment ended; last round taken $(utc)"; break; }
    now=$(date +%s)
    [ $(( now - start )) -ge "$max_secs" ] && { echo "ENDPOINT_SAMPLE max-secs=${max_secs} reached $(utc)"; break; }
    left=$(( interval - (now - t0) ))
    while [ "$left" -gt 0 ]; do why="$(stop_reason)" && break; sleep 1; left=$((left - 1)); done
    why="$(stop_reason)" && { echo "ENDPOINT_SAMPLE ${why}; ended $(utc)"; break; }
    if [ -n "$until_file" ] && grep -qE '^== [a-z0-9-]+ (rc=|LEFT_RUNNING )' "$until_file" 2>/dev/null; then ended=1; fi
done
