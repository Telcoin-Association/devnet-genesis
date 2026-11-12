#!/usr/bin/env bash
# orch-fleet-health.sh — bench 6, orchestrator only: each node's newest BENCH_STATUS line (node-sampler.sh, serial
# console) read straight with gcloud, because run-arms.sh's own health check reads no node on a real fleet (its
# parser expects "<node>: BENCH_STATUS …" and the serial line carries a syslog prefix; found live 2026-11-12).
# Read-only. One line per node and a summary:
#   FLEET_HEALTH run=<run> nodes=<read>/<n> disk_max=<pct> (<node>) fatal_db=<sum> block_min=<n> block_max=<n> <UTC>
#   tasks/bench6/orch-fleet-health.sh <run> [--watch <secs> --disk-max <pct> --until-file <path-with-rc-line>]
# With --watch it repeats every <secs> and exits 3 when a node's disk is at or above --disk-max [80] or any
# fatal_db > 0, and 0 when the file named by --until-file holds a line "== arms rc=" (the walk ended).
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
run="${1:?run id}"; shift
watch=0; dmaxlim=80; until_file=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --watch) watch="${2:?}"; shift 2 ;;
        --disk-max) dmaxlim="${2:?}"; shift 2 ;;
        --until-file) until_file="${2:?}"; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 64 ;;
    esac
done
man="${ROOT}/benchmark/results/${run}/manifest.json"
[ -f "${man}" ] || { echo "no manifest for ${run}" >&2; exit 2; }
once() {
    local inst zone line pct fatal block n=0 m=0 dmax=-1 dnode="" fsum=0 bmin="" bmax=""
    while IFS=$'\t' read -r inst zone; do
        m=$((m + 1))
        line="$(timeout 60 gcloud compute instances get-serial-port-output "${inst}" --zone "${zone}" --project tn-devnet 2>/dev/null | grep -a -F 'BENCH_STATUS ' | tail -1)"
        if [ -z "${line}" ]; then echo "  ${inst}: no BENCH_STATUS read"; continue; fi
        n=$((n + 1))
        pct="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^root_used_pct=//p' | tail -n 1)"
        fatal="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^fatal_db=//p' | tail -n 1)"
        block="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^block=//p' | tail -n 1)"
        echo "  ${inst}: root_used_pct=${pct:-?} fatal_db=${fatal:-?} block=${block:-?}"
        case "${pct}" in ''|*[!0-9]*) ;; *) if [ "${pct}" -gt "${dmax}" ]; then dmax="${pct}"; dnode="${inst}"; fi ;; esac
        case "${fatal}" in ''|*[!0-9]*) ;; *) fsum=$((fsum + fatal)) ;; esac
        case "${block}" in ''|*[!0-9]*) ;; *)
            if [ -z "${bmin}" ] || [ "${block}" -lt "${bmin}" ]; then bmin="${block}"; fi
            if [ -z "${bmax}" ] || [ "${block}" -gt "${bmax}" ]; then bmax="${block}"; fi ;;
        esac
    done < <(jq -r '.zones_used | to_entries[] | [.key, .value] | @tsv' "${man}")
    echo "FLEET_HEALTH run=${run} nodes=${n}/${m} disk_max=${dmax} (${dnode}) fatal_db=${fsum} block_min=${bmin:-?} block_max=${bmax:-?} $(date -u +%FT%TZ)"
    if [ "${fsum}" -gt 0 ] || [ "${dmax}" -ge "${dmaxlim}" ]; then return 3; fi
    return 0
}
if [ "${watch}" = 0 ]; then once; exit $?; fi
while :; do
    once || { rc=$?; [ "${rc}" != 3 ] || { echo "FLEET_HEALTH ALARM (disk >= ${dmaxlim} % or fatal_db > 0)"; exit 3; }; }
    if [ -n "${until_file}" ] && grep -qE '^== arms (rc=|LEFT_RUNNING )' "${until_file}" 2>/dev/null; then echo "FLEET_HEALTH the walk ended"; exit 0; fi
    sleep "${watch}"
done
