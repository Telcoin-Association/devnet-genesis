#!/usr/bin/env bash
#
# node-sampler.sh — on-node resource sampler for the benchmark fleet. Installed by
# benchmark-deploy.sh step 9 as /usr/local/bin/bench-node-sampler.sh and run as ROOT by
# bench-node-sampler.service. Every SAMPLER_INTERVAL_SECS (30) it appends ONE row to
# /var/lib/bench-sampler/<hostname>.csv, columns exactly per the sampler contract in
# tn-transaction-generator/bench/schema/README.md (header first, empty = unavailable):
#
#   ts_unix,pid,rss_anon_kb,rss_file_kb,rss_total_kb,io_write_bytes,io_read_bytes,
#   psi_mem_some_avg10,psi_io_some_avg10,psi_cpu_some_avg10,db_bytes,static_files_bytes,
#   epochs_bytes,cache_bytes,epoch_bytes,loadavg1,oom_count,root_used_pct
#
# The node runs `docker run --rm --name telcoin ... telcoin node` (tn-node-deployment
# setup-node.sh), with the data dir /var/lib/telcoin bind-mounted at /home/nonroot. `pid` is
# the in-container `telcoin node` process as seen from the host: `pgrep -f 'telcoin node'`
# narrowed to the container's cgroup (the host-side `docker run` client matches the same
# pattern and is excluded that way).
#
# Every SAMPLER_STATUS_EVERY samples (default 4 = 2 min) it also writes one
#   BENCH_STATUS host=<h> ts=<unix> root_used_pct=<n> fatal_db=<n> block=<n> rss_total_kb=<n>
# line to the serial console, so benchmark-blast.sh's abort watchers can read disk, the
# FatalDBFailure count and chain progress over the GCP REST API instead of polling IAP SSH.
#
# SAMPLER_ONCE=1 writes a single row and exits (smoke test).

set -uo pipefail

INTERVAL="${SAMPLER_INTERVAL_SECS:-30}"
STATUS_EVERY="${SAMPLER_STATUS_EVERY:-4}"
DATA_DIR="${SAMPLER_DATA_DIR:-/var/lib/telcoin}"
CONTAINER="${SAMPLER_CONTAINER:-telcoin}"
RPC="${SAMPLER_RPC:-http://127.0.0.1:8545}"
OUT_DIR="${SAMPLER_OUT_DIR:-/var/lib/bench-sampler}"
CONSOLE="${SAMPLER_CONSOLE:-/dev/ttyS0}"
HOST="$(hostname -s 2>/dev/null || hostname)"
OUT="${OUT_DIR}/${HOST}.csv"
OLD_HEADER="ts_unix,pid,rss_anon_kb,rss_file_kb,rss_total_kb,io_write_bytes,io_read_bytes,psi_mem_some_avg10,psi_io_some_avg10,psi_cpu_some_avg10,db_bytes,static_files_bytes,epochs_bytes,cache_bytes,epoch_bytes,loadavg1,oom_count,root_used_pct"
HEADER="${OLD_HEADER},block"
INVENTORY="${OUT_DIR}/${HOST}.epochs.txt"

mkdir -p "${OUT_DIR}"
if [ -s "${OUT}" ]; then
    IFS= read -r existing_header < "${OUT}"
    if [ "${existing_header}" = "${OLD_HEADER}" ]; then
        # Preserve old samples with a blank block field when the sampler is upgraded.
        awk 'NR == 1 { print $0 ",block"; next } { print $0 "," }' "${OUT}" > "${OUT}.upgrade" \
            && mv "${OUT}.upgrade" "${OUT}" || exit 1
    elif [ "${existing_header}" != "${HEADER}" ]; then
        echo "unrecognized sampler CSV header: ${OUT}" >&2
        exit 1
    fi
fi
[ -s "${OUT}" ] || printf '%s\n' "${HEADER}" > "${OUT}"

cid=""
pid=""

# telcoin_pid — the containerised `telcoin node` pid (cached until it disappears).
telcoin_pid() {
    if [ -n "${pid}" ] && [ -d "/proc/${pid}" ] && grep -q "telcoin" "/proc/${pid}/cmdline" 2>/dev/null; then
        printf '%s' "${pid}"; return 0
    fi
    pid=""
    cid="$(docker inspect -f '{{.Id}}' "${CONTAINER}" 2>/dev/null || true)"
    [ -n "${cid}" ] || return 0
    local p
    for p in $(pgrep -f 'telcoin node' 2>/dev/null); do
        if grep -q "${cid}" "/proc/${p}/cgroup" 2>/dev/null; then pid="${p}"; break; fi
    done
    # Fallback: the container's init process (the image's entrypoint is the binary itself).
    [ -n "${pid}" ] || pid="$(docker inspect -f '{{.State.Pid}}' "${CONTAINER}" 2>/dev/null | grep -v '^0$' || true)"
    printf '%s' "${pid}"
}

status_kv() { awk -v k="$2:" '$1 == k { print $2; exit }' "$1" 2>/dev/null; }
io_kv() { awk -v k="$2:" '$1 == k { print $2; exit }' "$1" 2>/dev/null; }
psi_some() { awk '$1 == "some" { for (i = 2; i <= NF; i++) if ($i ~ /^avg10=/) { sub(/^avg10=/, "", $i); print $i; exit } }' "/proc/pressure/$1" 2>/dev/null; }
dir_bytes() { [ -d "$1" ] && du -sb "$1" 2>/dev/null | awk '{print $1}'; }
root_pct() { df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9'; }

block_number() {
    local hex
    hex="$(curl -s --max-time 3 -H 'content-type: application/json' \
        --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' "${RPC}" 2>/dev/null \
        | sed -n 's/.*"result":"0x\([0-9a-fA-F]*\)".*/\1/p')"
    [ -n "${hex}" ] && printf '%d' "0x${hex}"
}

last_status_ts=""
last_inventory_ts=0
n=0
while :; do
    ts="$(date +%s)"
    p="$(telcoin_pid)"
    rss_anon=""; rss_file=""; rss_total=""; io_w=""; io_r=""
    if [ -n "${p}" ] && [ -r "/proc/${p}/status" ]; then
        rss_anon="$(status_kv "/proc/${p}/status" RssAnon)"
        rss_file="$(status_kv "/proc/${p}/status" RssFile)"
        rss_total="$(status_kv "/proc/${p}/status" VmRSS)"
        io_w="$(io_kv "/proc/${p}/io" write_bytes)"
        io_r="$(io_kv "/proc/${p}/io" read_bytes)"
    fi
    psi_m="$(psi_some memory)"; psi_i="$(psi_some io)"; psi_c="$(psi_some cpu)"
    db="$(dir_bytes "${DATA_DIR}/db")"
    sf="$(dir_bytes "${DATA_DIR}/static_files")"
    ep_s="$(dir_bytes "${DATA_DIR}/consensus-db/epochs")"
    cache="$(dir_bytes "${DATA_DIR}/consensus-db/cache")"
    ep="$(dir_bytes "${DATA_DIR}/consensus-db/epoch")"
    load1="$(awk '{print $1}' /proc/loadavg 2>/dev/null)"
    ooms="$(dmesg 2>/dev/null | grep -ci 'out of memory' || true)"
    rootp="$(root_pct)"
    block="$(block_number)"
    if [ $((ts - last_inventory_ts)) -ge 60 ]; then
        printf 'BENCH_EPOCH_FILES ts=%s host=%s\n' "${ts}" "${HOST}" >> "${INVENTORY}"
        ls -laR --full-time -- "${DATA_DIR}/consensus-db/epochs" >> "${INVENTORY}" 2>&1 || true
        last_inventory_ts="${ts}"
    fi
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "${ts}" "${p}" "${rss_anon}" "${rss_file}" "${rss_total}" "${io_w}" "${io_r}" \
        "${psi_m}" "${psi_i}" "${psi_c}" "${db}" "${sf}" "${ep_s}" "${cache}" "${ep}" \
        "${load1}" "${ooms}" "${rootp}" "${block}" >> "${OUT}"

    n=$((n + 1))
    # First sample, then every STATUS_EVERY-th (0 disables the status line).
    if [ "${STATUS_EVERY}" -gt 0 ] && [ $(( (n - 1) % STATUS_EVERY )) -eq 0 ]; then
        since="${last_status_ts:-$((ts - INTERVAL * STATUS_EVERY))}"
        fatal="$(docker logs --since "${since}" "${CONTAINER}" 2>&1 | grep -c 'FatalDBFailure' || true)"
        line="BENCH_STATUS host=${HOST} ts=${ts} root_used_pct=${rootp:-} fatal_db=${fatal:-0} block=${block} rss_total_kb=${rss_total:-}"
        { [ -w "${CONSOLE}" ] && printf '%s\n' "${line}" > "${CONSOLE}"; } 2>/dev/null || true
        printf '%s\n' "${line}"   # journal copy
        last_status_ts="${ts}"
    fi

    [ "${SAMPLER_ONCE:-0}" = "1" ] && exit 0
    sleep "$(( INTERVAL - ( $(date +%s) - ts ) > 1 ? INTERVAL - ( $(date +%s) - ts ) : 1 ))"
done
