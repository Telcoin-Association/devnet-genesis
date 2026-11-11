#!/usr/bin/env bash
#
# node-persist-sampler.sh — bench-6 persist sampler. Installed by benchmark-deploy.sh step 9 when
# BENCH_PERSIST_SAMPLER=1, as /usr/local/bin/bench-persist-sampler.sh beside the node sampler, with
# tools/folio-census.py as /usr/local/bin/bench-folio-census.py, and run as ROOT by
# bench-persist-sampler.service. It writes two files and nothing else (sampler.csv stays the node
# sampler's):
#
#   <out>/<host>.persist.csv   one row every PERSIST_INTERVAL_SECS (30); header tools/persist-csv-header.txt
#   <out>/<host>.folios.txt    folio census every PERSIST_CENSUS_EVERY_SECS (900); tools/folio-census-header.txt
#
# A persist row: ts_unix and the node pid; /proc/diskstats of the disk under the data dir (sectors x 512
# as bytes); /proc/vmstat nr_dirty, nr_writeback, nr_dirtied, nr_written, workingset_refault_file,
# pgmajfault, thp_file_alloc, thp_file_fallback; /proc/meminfo MemAvailable, Cached, Dirty, Writeback;
# the node's memory cgroup (memory.current and memory.stat file, file_dirty, file_writeback,
# workingset_refault_file; cgroup v1 names as a fallback); /proc/<pid>/io. Every
# PERSIST_MDBX_EVERY_SECS (300) the row also carries mdbx.dat's size, its resident pages (fincore, or
# the census tool's --resident-only), and the summed Size of the node's mdbx.dat mappings in
# /proc/<pid>/smaps with the part whose VmFlags carry `rr`, and the resident pages at or past the used
# size of the database: the node's gauge tn_reth_mdbx_used_bytes, read from PERSIST_METRICS_URL with
# `curl -s --max-time 3`, then the census tool's --resident-only --from-bytes <used>. On the other rows
# those five are empty; the last one is also empty whenever the gauge cannot be read (an image without
# it, a node that is down).
# Every row has every column: a source that cannot be read leaves its cells empty.
#
# Nothing here reads mdbx.dat or opens the MDBX environment (no mdbx_stat): the file is stat'ed, checked
# with mincore through a mapping nobody dereferences, and found in the node's smaps and pagemap by inode.
# Page-operation counts come from the node's own `persisted output` log line and metrics.
#
# The node pid is looked up on every tick (a restart changes it): `docker inspect` of PERSIST_CONTAINER
# gives the container id and State.Pid; the node is State.Pid when its command line contains
# PERSIST_PID_MATCH, else the process of the container's cgroup whose command line does. A cached pid
# is kept while /proc/<pid>/cgroup still names the container and its command line still matches.
# PERSIST_PID (fixed) or PERSIST_PID_FILE (read every tick) replace the docker lookup (the one-VM probe).
#
# Environment (defaults in brackets):
#   PERSIST_DATA_DIR [/var/lib/telcoin]       the node's data dir; its device picks the disk
#   PERSIST_MDBX_FILE [<data dir>/db/mdbx.dat]
#   PERSIST_DISK []                           a block device name (nvme0n1) instead of the lookup
#   PERSIST_CONTAINER [telcoin]               PERSIST_PID_MATCH [telcoin node]
#   PERSIST_PID [] / PERSIST_PID_FILE []      fixed pid / file holding the pid
#   PERSIST_OUT_DIR [/var/lib/bench-sampler]  PERSIST_HOST [hostname -s]
#   PERSIST_INTERVAL_SECS [30]  PERSIST_MDBX_EVERY_SECS [300]  PERSIST_CENSUS_EVERY_SECS [900; 0 = off]
#   PERSIST_CENSUS [/usr/local/bin/bench-folio-census.py, else tools/folio-census.py beside this file]
#   PERSIST_FINCORE [fincore]                 empty = always use the census tool's --resident-only
#   PERSIST_TIMEOUT_SECS [20]                 the limit on every external call
#   PERSIST_TICKS [0 = forever]               stop after this many rows (tests, the probe)
#   PERSIST_METRICS_URL [http://127.0.0.1:<METRICS_PORT>/metrics]  the node's Prometheus endpoint; the
#                                             port as the harness reads it (bench-lib.sh prestart and
#                                             admission read): METRICS_PORT in /etc/telcoin/.node-meta,
#                                             9101 when absent, empty or set twice
#   PERSIST_ROOT []                           prefix for /proc, /sys and /etc/telcoin/.node-meta (tests)

set -uo pipefail

HEADER="ts_unix,pid,disk_rd_ios_total,disk_rd_bytes_total,disk_rd_ticks_ms_total,disk_wr_ios_total,disk_wr_bytes_total,disk_wr_ticks_ms_total,disk_flush_ios_total,disk_flush_ticks_ms_total,disk_in_flight_ios,disk_io_ticks_ms_total,vm_nr_dirty_pages,vm_nr_writeback_pages,vm_nr_dirtied_pages_total,vm_nr_written_pages_total,vm_workingset_refault_file_pages_total,vm_pgmajfault_total,vm_thp_file_alloc_total,vm_thp_file_fallback_total,mem_available_kb,mem_cached_kb,mem_dirty_kb,mem_writeback_kb,memcg_current_bytes,memcg_file_bytes,memcg_file_dirty_bytes,memcg_file_writeback_bytes,memcg_workingset_refault_file_pages_total,proc_rchar_bytes_total,proc_wchar_bytes_total,proc_syscr_total,proc_syscw_total,proc_read_bytes_total,proc_write_bytes_total,proc_cancelled_write_bytes_total,mdbx_dat_size_bytes,mdbx_dat_resident_pages,mdbx_dat_vma_bytes,mdbx_dat_rr_bytes,mdbx_dat_resident_past_used_pages"

ROOT="${PERSIST_ROOT:-}"
DATA_DIR="${PERSIST_DATA_DIR:-/var/lib/telcoin}"
MDBX="${PERSIST_MDBX_FILE:-${DATA_DIR}/db/mdbx.dat}"
DISK="${PERSIST_DISK:-}"
CONTAINER="${PERSIST_CONTAINER:-telcoin}"
MATCH="${PERSIST_PID_MATCH:-telcoin node}"
FIXED_PID="${PERSIST_PID:-}"
PID_FILE="${PERSIST_PID_FILE:-}"
OUT_DIR="${PERSIST_OUT_DIR:-/var/lib/bench-sampler}"
HOST="${PERSIST_HOST:-$(hostname -s 2>/dev/null || hostname)}"
INTERVAL="${PERSIST_INTERVAL_SECS:-30}"
MDBX_EVERY="${PERSIST_MDBX_EVERY_SECS:-300}"
CENSUS_EVERY="${PERSIST_CENSUS_EVERY_SECS:-900}"
FINCORE="${PERSIST_FINCORE-fincore}"
TO="${PERSIST_TIMEOUT_SECS:-20}"
TICKS="${PERSIST_TICKS:-0}"
CENSUS="${PERSIST_CENSUS:-}"
METRICS_URL="${PERSIST_METRICS_URL:-}"
if [ -z "${METRICS_URL}" ]; then
    _mp="$(awk 'index($0, "METRICS_PORT=") == 1 { n++; v = substr($0, 14) } END { sub(/\r$/, "", v); if (n == 1) print v }' \
        "${ROOT}/etc/telcoin/.node-meta" 2>/dev/null)" || _mp=""
    [ -n "${_mp}" ] || _mp=9101
    case "${_mp}" in
        *[!0-9]*|??????*) echo "node-persist-sampler: METRICS_PORT '${_mp}' is not a port number; no used size" >&2 ;;
        *) METRICS_URL="http://127.0.0.1:$((10#${_mp}))/metrics" ;;
    esac
fi
if [ -z "${CENSUS}" ]; then
    CENSUS=/usr/local/bin/bench-folio-census.py
    [ -f "${CENSUS}" ] || CENSUS="$(cd "$(dirname "$0")" && pwd -P)/tools/folio-census.py"
fi

for _v in INTERVAL MDBX_EVERY CENSUS_EVERY TO TICKS; do
    case "${!_v}" in
        ''|*[!0-9]*) echo "node-persist-sampler: ${_v}='${!_v}' is not a non-negative integer" >&2; exit 2 ;;
    esac
done
[ "${INTERVAL}" -ge 1 ] && [ "${TO}" -ge 2 ] || { echo "node-persist-sampler: interval must be >= 1 s, timeout >= 2 s" >&2; exit 2; }
# The 300-s and 900-s columns ride on every k-th tick (the first tick included).
MDBX_TICKS=$(( MDBX_EVERY / INTERVAL )); [ "${MDBX_TICKS}" -ge 1 ] || MDBX_TICKS=1
CENSUS_TICKS=0
if [ "${CENSUS_EVERY}" -gt 0 ]; then
    CENSUS_TICKS=$(( CENSUS_EVERY / INTERVAL )); [ "${CENSUS_TICKS}" -ge 1 ] || CENSUS_TICKS=1
fi

OUT="${OUT_DIR}/${HOST}.persist.csv"
FOLIOS="${OUT_DIR}/${HOST}.folios.txt"
mkdir -p "${OUT_DIR}" || exit 1
if [ -s "${OUT}" ]; then
    first=""
    IFS= read -r first < "${OUT}" || true
    if [ "${first}" != "${HEADER}" ]; then
        aside="${OUT}.old-$(date +%s)"
        mv -f "${OUT}" "${aside}" || exit 1
        echo "node-persist-sampler: ${OUT} had another header; moved to ${aside}" >&2
    fi
fi
[ -s "${OUT}" ] || printf '%s\n' "${HEADER}" > "${OUT}" || exit 1

# A row of empty cells after ts_unix and pid: written when the reader below produced nothing.
BLANK_TAIL=""
_n=0
IFS=, read -r -a _cols <<< "${HEADER}"
while [ "${_n}" -lt $(( ${#_cols[@]} - 2 )) ]; do BLANK_TAIL="${BLANK_TAIL},"; _n=$(( _n + 1 )); done

# ---------------------------------------------------------------- pid, cgroup, disk
pid=""
cid=""
CG=""

# cmd_matches PID — its command line (arguments joined by spaces) contains MATCH.
cmd_matches() {
    local a cmd=""
    [ -r "${ROOT}/proc/$1/cmdline" ] || return 1
    while IFS= read -r -d '' a; do cmd="${cmd}${cmd:+ }${a}"; done < "${ROOT}/proc/$1/cmdline"
    case "${cmd}" in *"${MATCH}"*) return 0 ;; esac
    return 1
}

# in_container PID — /proc/PID/cgroup names the cached container id.
in_container() {
    local line
    [ -n "${cid}" ] && [ -r "${ROOT}/proc/$1/cgroup" ] || return 1
    while IFS= read -r line || [ -n "${line}" ]; do
        case "${line}" in *"${cid}"*) return 0 ;; esac
    done < "${ROOT}/proc/$1/cgroup"
    return 1
}

# set_cgroup PID — CG = its memory cgroup directory: the v1 memory controller when listed, else v2.
set_cgroup() {
    local line
    CG=""
    [ -r "${ROOT}/proc/$1/cgroup" ] || return 0
    while IFS= read -r line || [ -n "${line}" ]; do
        case "${line}" in
            *:memory:*) CG="${ROOT}/sys/fs/cgroup/memory${line#*:memory:}"; return 0 ;;
            0::*) CG="${ROOT}/sys/fs/cgroup${line#0::}" ;;
        esac
    done < "${ROOT}/proc/$1/cgroup"
    CG="${CG%/}"
}

# resolve_pid — pid = the node's host pid this tick, or empty.
resolve_pid() {
    local out cpid p
    if [ -n "${FIXED_PID}" ] || [ -n "${PID_FILE}" ]; then
        p="${FIXED_PID}"
        [ -n "${p}" ] || { IFS= read -r p < "${PID_FILE}" || true; } 2>/dev/null
        case "${p}" in ''|*[!0-9]*) p="" ;; esac
        pid=""
        [ -n "${p}" ] && [ -d "${ROOT}/proc/${p}" ] && pid="${p}"
        return 0
    fi
    if [ -n "${pid}" ] && in_container "${pid}" && cmd_matches "${pid}"; then return 0; fi
    pid=""
    cid=""
    out="$(timeout "${TO}" docker inspect -f '{{.Id}} {{.State.Pid}}' "${CONTAINER}" 2>/dev/null)" || out=""
    case "${out}" in *" "*) ;; *) return 0 ;; esac
    cid="${out%% *}"
    cpid="${out##* }"
    case "${cpid}" in ''|0|*[!0-9]*) return 0 ;; esac
    if cmd_matches "${cpid}"; then pid="${cpid}"; return 0; fi
    # The entrypoint is not the node itself: search the container's cgroup.
    set_cgroup "${cpid}"
    [ -n "${CG}" ] && [ -r "${CG}/cgroup.procs" ] || return 0
    while IFS= read -r p || [ -n "${p}" ]; do
        if cmd_matches "${p}"; then pid="${p}"; return 0; fi
    done < "${CG}/cgroup.procs"
}

# resolve_disk — DISK = the whole disk under the data dir (a partition's parent), from its st_dev.
resolve_disk() {
    local dev maj min sys
    [ -z "${DISK}" ] || return 0
    dev="$(stat -L -c %d "${DATA_DIR}" 2>/dev/null)" || dev=""
    case "${dev}" in ''|*[!0-9]*) return 0 ;; esac
    maj=$(( ((dev >> 8) & 0xfff) | ((dev >> 32) & ~0xfff) ))
    min=$(( (dev & 0xff) | ((dev >> 12) & ~0xff) ))
    sys="${ROOT}/sys/dev/block/${maj}:${min}"
    [ -e "${sys}" ] || return 0
    sys="$(cd -P "${sys}" 2>/dev/null && pwd -P)" || return 0
    [ -e "${sys}/partition" ] && sys="${sys%/*}"
    DISK="${sys##*/}"
}

# ---------------------------------------------------------------- the 300-s columns
M_SIZE=""
M_RES=""
M_VMA=""
M_RR=""
M_PAST=""

# The gauge's value from the Prometheus text (with or without labels). It reads to the end, so curl is
# never cut off by a closed pipe (pipefail would then drop a good value).
# shellcheck disable=SC2016  # awk program text
USED_AWK='
!found && (index($0, "tn_reth_mdbx_used_bytes ") == 1 || index($0, "tn_reth_mdbx_used_bytes{") == 1) {
    s = $0
    if (index(s, "{") == 24) sub(/^.*\}/, "", s); else s = substr(s, 24)
    split(s, f, " ")
    if (f[1] ~ /^[0-9]/) { found = 1; used = f[1] }
}
END { if (found) printf "%.0f\n", used }'

# shellcheck disable=SC2016  # awk program text: $n are awk fields
SMAPS_AWK='
$1 ~ /^[0-9a-f]+-[0-9a-f]+$/ {
    cur = ($5 == ino && ($4 == dev || substr($6, length($6) - length(sfx) + 1) == sfx)); next
}
cur && $1 == "Size:" { sz = $2 * 1024; vma += sz }
cur && $1 == "VmFlags:" { for (i = 2; i <= NF; i++) if ($i == "rr") { rr += sz; break } }
END { if (NR > 0) printf "%.0f %.0f\n", vma, rr }'

mdbx_columns() {
    local st dev ino maj min devstr out used
    M_SIZE=""; M_RES=""; M_VMA=""; M_RR=""; M_PAST=""
    st="$(stat -L -c '%s %d %i' "${MDBX}" 2>/dev/null)" || st=""
    case "${st}" in *" "*" "*) ;; *) return 0 ;; esac
    M_SIZE="${st%% *}"; st="${st#* }"
    dev="${st%% *}"; ino="${st#* }"
    if [ -n "${FINCORE}" ] && command -v "${FINCORE}" >/dev/null 2>&1; then
        out="$(timeout "${TO}" "${FINCORE}" -n -r -o PAGES "${MDBX}" 2>/dev/null)" || out=""
    else
        out="$(timeout "${TO}" python3 "${CENSUS}" --file "${MDBX}" --resident-only 2>/dev/null)" || out=""
    fi
    out="${out//[[:space:]]/}"
    case "${out}" in ''|*[!0-9]*) ;; *) M_RES="${out}" ;; esac
    if [ -n "${METRICS_URL}" ]; then
        used="$(timeout "${TO}" curl -s --max-time 3 "${METRICS_URL}" 2>/dev/null | awk "${USED_AWK}")" || used=""
        case "${used}" in
            ''|*[!0-9]*) ;;
            *) out="$(timeout "${TO}" python3 "${CENSUS}" --file "${MDBX}" --resident-only --from-bytes "${used}" 2>/dev/null)" || out=""
               case "${out}" in ''|*[!0-9]*) ;; *) M_PAST="${out}" ;; esac ;;
        esac
    fi
    [ -n "${pid}" ] && [ -r "${ROOT}/proc/${pid}/smaps" ] || return 0
    maj=$(( ((dev >> 8) & 0xfff) | ((dev >> 32) & ~0xfff) ))
    min=$(( (dev & 0xff) | ((dev >> 12) & ~0xff) ))
    printf -v devstr '%02x:%02x' "${maj}" "${min}"
    out="$(timeout "${TO}" awk -v ino="${ino}" -v dev="${devstr}" -v sfx="/${MDBX##*/}" "${SMAPS_AWK}" \
        "${ROOT}/proc/${pid}/smaps" 2>/dev/null)" || out=""
    case "${out}" in
        *" "*) M_VMA="${out%% *}"; M_RR="${out#* }" ;;
    esac
}

# ---------------------------------------------------------------- the row
# One awk reads every 30-s source and prints the row in HEADER order: each value goes into v[<column>],
# and a column nobody filled prints empty, so a missing source never shifts a column.
# shellcheck disable=SC2016  # awk program text
ROW_AWK='
function num(x) { return (x ~ /^-?[0-9]+(\.[0-9]+)?$/) ? x : "" }
function kv(file, map,   line, a) {
    while ((getline line < file) > 0) { split(line, a, " "); if (a[1] in map) v[map[a[1]]] = a[2] }
    close(file)
}
BEGIN {
    v["ts_unix"] = ts; v["pid"] = pid
    if (disk != "") {
        f = root "/proc/diskstats"
        while ((getline line < f) > 0) {
            k = split(line, d, " ")
            if (k < 14 || d[3] != disk) continue
            v["disk_rd_ios_total"] = d[4]; v["disk_rd_bytes_total"] = sprintf("%.0f", d[6] * 512)
            v["disk_rd_ticks_ms_total"] = d[7]; v["disk_wr_ios_total"] = d[8]
            v["disk_wr_bytes_total"] = sprintf("%.0f", d[10] * 512); v["disk_wr_ticks_ms_total"] = d[11]
            v["disk_in_flight_ios"] = d[12]; v["disk_io_ticks_ms_total"] = d[13]
            if (k >= 20) { v["disk_flush_ios_total"] = d[19]; v["disk_flush_ticks_ms_total"] = d[20] }
        }
        close(f)
    }
    vm["nr_dirty"] = "vm_nr_dirty_pages"; vm["nr_writeback"] = "vm_nr_writeback_pages"
    vm["nr_dirtied"] = "vm_nr_dirtied_pages_total"; vm["nr_written"] = "vm_nr_written_pages_total"
    vm["workingset_refault_file"] = "vm_workingset_refault_file_pages_total"; vm["pgmajfault"] = "vm_pgmajfault_total"
    vm["thp_file_alloc"] = "vm_thp_file_alloc_total"; vm["thp_file_fallback"] = "vm_thp_file_fallback_total"
    kv(root "/proc/vmstat", vm)
    mi["MemAvailable:"] = "mem_available_kb"; mi["Cached:"] = "mem_cached_kb"
    mi["Dirty:"] = "mem_dirty_kb"; mi["Writeback:"] = "mem_writeback_kb"
    kv(root "/proc/meminfo", mi)
    if (cg != "") {
        f = cg "/memory.current"
        if ((getline line < f) > 0) v["memcg_current_bytes"] = line
        close(f)
        if (v["memcg_current_bytes"] == "") {
            f = cg "/memory.usage_in_bytes"
            if ((getline line < f) > 0) v["memcg_current_bytes"] = line
            close(f)
        }
        f = cg "/memory.stat"
        while ((getline line < f) > 0) { split(line, a, " "); st[a[1]] = a[2] }
        close(f)
        v["memcg_file_bytes"] = ("file" in st) ? st["file"] : st["cache"]
        v["memcg_file_dirty_bytes"] = ("file_dirty" in st) ? st["file_dirty"] : st["dirty"]
        v["memcg_file_writeback_bytes"] = ("file_writeback" in st) ? st["file_writeback"] : st["writeback"]
        v["memcg_workingset_refault_file_pages_total"] = st["workingset_refault_file"]
    }
    if (pid != "") {
        io["rchar:"] = "proc_rchar_bytes_total"; io["wchar:"] = "proc_wchar_bytes_total"
        io["syscr:"] = "proc_syscr_total"; io["syscw:"] = "proc_syscw_total"
        io["read_bytes:"] = "proc_read_bytes_total"; io["write_bytes:"] = "proc_write_bytes_total"
        io["cancelled_write_bytes:"] = "proc_cancelled_write_bytes_total"
        kv(root "/proc/" pid "/io", io)
    }
    v["mdbx_dat_size_bytes"] = msize; v["mdbx_dat_resident_pages"] = mres
    v["mdbx_dat_vma_bytes"] = mvma; v["mdbx_dat_rr_bytes"] = mrr; v["mdbx_dat_resident_past_used_pages"] = mpast
    n = split(header, col, ",")
    out = ""
    for (i = 1; i <= n; i++) out = out (i > 1 ? "," : "") num(v[col[i]])
    print out
}'

# ---------------------------------------------------------------- main loop
n=0
while :; do
    ts="$(date +%s)"
    resolve_pid
    CG=""
    [ -n "${pid}" ] && set_cgroup "${pid}"
    resolve_disk
    if [ $(( n % MDBX_TICKS )) -eq 0 ]; then
        mdbx_columns
    else
        M_SIZE=""; M_RES=""; M_VMA=""; M_RR=""; M_PAST=""
    fi
    row="$(timeout "${TO}" awk -v root="${ROOT}" -v ts="${ts}" -v pid="${pid}" -v disk="${DISK}" -v cg="${CG}" \
        -v msize="${M_SIZE}" -v mres="${M_RES}" -v mvma="${M_VMA}" -v mrr="${M_RR}" -v mpast="${M_PAST}" \
        -v header="${HEADER}" \
        "${ROW_AWK}" < /dev/null 2>/dev/null)" || row=""
    [ -n "${row}" ] || row="${ts},${pid}${BLANK_TAIL}"
    printf '%s\n' "${row}" >> "${OUT}"

    if [ "${CENSUS_TICKS}" -gt 0 ] && [ $(( n % CENSUS_TICKS )) -eq 0 ]; then
        census_args=(--file "${MDBX}" --proc "${ROOT}/proc" --out "${FOLIOS}" --deadline-secs "$(( TO - 5 > 1 ? TO - 5 : 1 ))")
        [ -n "${pid}" ] && census_args+=(--pid "${pid}")
        timeout "${TO}" python3 "${CENSUS}" "${census_args[@]}" < /dev/null \
            || echo "node-persist-sampler: folio census failed (rc=$?)" >&2
    fi

    n=$(( n + 1 ))
    if [ "${TICKS}" -gt 0 ] && [ "${n}" -ge "${TICKS}" ]; then exit 0; fi
    now="$(date +%s)"
    sleep "$(( INTERVAL - (now - ts) > 1 ? INTERVAL - (now - ts) : 1 ))"
done
