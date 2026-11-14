#!/usr/bin/env bash
# orch-fleet-health.sh — bench 7, orchestrator only: tasks/bench6/orch-fleet-health.sh with its two defects
# fixed. Each node's newest BENCH_STATUS line (node-sampler.sh, serial console) read straight with gcloud.
# Read-only. One line per node and a summary:
#   FLEET_HEALTH run=<run> nodes=<read>/<n> disk_max=<pct> (<node>) fatal_db=<sum> halt=<sum> block_min=<n> block_max=<n> <UTC>
# halt= sums the samplers' halt= (the build's fail-stop lines in each node's log since it began; a status line
# without the key, from an older sampler, adds nothing); a node with halt > 0 is named on a
# "FLEET_HEALTH HALTED <node>=<n> ..." line.
#   tasks/bench7/orch-fleet-health.sh <run> [--watch <secs> --disk-max <pct> --until-file <segment log> --max-secs <n>
#                                            --halt-baseline <n>]
# The instances are the run's manifest's (.zones_used), and each must belong to the run before it is read:
# one `gcloud compute instances list` per round gives every bench instance's run label (bench-run=<run id>,
# INSTANCE_LABELS in benchmark/config.sh). An instance of the same name with another run's label is
# reported "foreign" and not read, one not listed "absent"; when no instance of the run is left, the
# watch ends with "FLEET_HEALTH run=<run> gone <UTC>". A failed list call reads nothing that round
# ("FLEET_HEALTH run=<run> list-failed <UTC>") and is never taken for a gone fleet.
# With --watch it repeats every <secs> and ends:
#   3 when a node's disk is at or above --disk-max [80], any fatal_db > 0 or the fleet's halt sum is above
#     --halt-baseline [0] ("FLEET_HEALTH ALARM ...", naming the halted nodes);
#   0 when the file named by --until-file holds a segment's end line, "== <segment> rc=" or
#     "== <segment> LEFT_RUNNING " ("FLEET_HEALTH the walk ended (<that line>)"), or the fleet is gone;
#   4 after --max-secs [10800] whatever else ("FLEET_HEALTH run=<run> max-secs=<n> reached <UTC>").
# Without --watch: one round; exit 0, 3 (alarm), 4 (gone) or 5 (the list call failed).
# A halt alarm is the run's finding, not a fault of the harness: the blast goes on (its abort reads fatal_db only).
# A sampler's halt= never goes back down, so a watch restarted after a halt alarm passes the sum the alarm
# printed as --halt-baseline: it alarms again only on a new halt line. FLEET_HEALTH and HALTED still print the
# real sum and every node with halt > 0.
# Knobs (environment): FLEET_HEALTH_ROOT (else CHAIN_ROOT, else the repo), FLEET_HEALTH_PROJECT,
# FLEET_HEALTH_RUN_LABEL [bench-run].
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${FLEET_HEALTH_ROOT:-${CHAIN_ROOT:-$(cd "${SELF_DIR}/../.." && pwd)}}"
PROJECT="${FLEET_HEALTH_PROJECT:-tn-devnet}"
RUN_LABEL_KEY="${FLEET_HEALTH_RUN_LABEL:-bench-run}"
utc() { date -u +%FT%TZ; }
run="${1:?run id}"; shift
watch=0; dmaxlim=80; until_file=""; max_secs=10800; halt_base=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --watch) watch="${2:?}"; shift 2 ;;
        --disk-max) dmaxlim="${2:?}"; shift 2 ;;
        --until-file) until_file="${2:?}"; shift 2 ;;
        --max-secs) max_secs="${2:?}"; shift 2 ;;
        --halt-baseline) halt_base="${2:?}"; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 64 ;;
    esac
done
for v in "${watch}" "${dmaxlim}" "${max_secs}" "${halt_base}"; do
    case "${v}" in ''|*[!0-9]*) echo "--watch, --disk-max, --max-secs and --halt-baseline take whole numbers ('${v}')" >&2; exit 64 ;; esac
done
man="${ROOT}/benchmark/results/${run}/manifest.json"
[ -f "${man}" ] || { echo "no manifest for ${run}" >&2; exit 2; }
t0="$(date +%s)"
HALTED=""   # "<node>=<n> ..." of the last round's nodes with halt > 0

# list_fleet — "<name>\t<zone>\t<run label>" for every bench instance of the project; non-zero when the
# call fails (then nothing is read this round).
list_fleet() {
    local out=""
    out="$(timeout 90 gcloud compute instances list --project "${PROJECT}" --filter="name~bench-" --format=json 2>/dev/null)" || return 1
    printf '%s' "${out}" | jq -r --arg k "${RUN_LABEL_KEY}" '.[] | [.name, (.zone // "" | split("/") | last), ((.labels // {})[$k] // "")] | @tsv'
}

once() {
    local inst zone line pct fatal halt block n=0 m=0 dmax=-1 dnode="" fsum=0 hsum=0 bmin="" bmax="" fleet="" row="" lzone="" lrun="" ours=0
    HALTED=""
    fleet="$(list_fleet)" || { echo "FLEET_HEALTH run=${run} list-failed $(utc)"; return 5; }
    while IFS=$'\t' read -r inst zone; do
        m=$((m + 1))
        row="$(printf '%s\n' "${fleet}" | awk -F'\t' -v n="${inst}" '$1 == n { print; exit }')"
        if [ -z "${row}" ]; then echo "  ${inst}: absent"; continue; fi
        lzone="$(printf '%s\n' "${row}" | cut -f2)"
        lrun="$(printf '%s\n' "${row}" | cut -f3)"
        if [ "${lrun}" != "${run}" ]; then echo "  ${inst}: foreign (${RUN_LABEL_KEY}=${lrun:-none}) not read"; continue; fi
        ours=$((ours + 1))
        line="$(timeout 60 gcloud compute instances get-serial-port-output "${inst}" --zone "${lzone:-${zone}}" --project "${PROJECT}" 2>/dev/null | grep -a -F 'BENCH_STATUS ' | tail -1)"
        if [ -z "${line}" ]; then echo "  ${inst}: no BENCH_STATUS read"; continue; fi
        n=$((n + 1))
        pct="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^root_used_pct=//p' | tail -n 1)"
        fatal="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^fatal_db=//p' | tail -n 1)"
        halt="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^halt=//p' | tail -n 1)"
        block="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^block=//p' | tail -n 1)"
        echo "  ${inst}: root_used_pct=${pct:-?} fatal_db=${fatal:-?} halt=${halt:-?} block=${block:-?}"
        case "${pct}" in ''|*[!0-9]*) ;; *) if [ "${pct}" -gt "${dmax}" ]; then dmax="${pct}"; dnode="${inst}"; fi ;; esac
        case "${fatal}" in ''|*[!0-9]*) ;; *) fsum=$((fsum + fatal)) ;; esac
        case "${halt}" in ''|*[!0-9]*) ;; *)
            hsum=$((hsum + halt))
            if [ "${halt}" -gt 0 ]; then HALTED="${HALTED:+${HALTED} }${inst}=${halt}"; fi ;;
        esac
        case "${block}" in ''|*[!0-9]*) ;; *)
            if [ -z "${bmin}" ] || [ "${block}" -lt "${bmin}" ]; then bmin="${block}"; fi
            if [ -z "${bmax}" ] || [ "${block}" -gt "${bmax}" ]; then bmax="${block}"; fi ;;
        esac
    done < <(jq -r '.zones_used | to_entries[] | [.key, .value] | @tsv' "${man}")
    if [ "${ours}" = 0 ]; then echo "FLEET_HEALTH run=${run} gone $(utc)"; return 4; fi
    echo "FLEET_HEALTH run=${run} nodes=${n}/${m} disk_max=${dmax} (${dnode}) fatal_db=${fsum} halt=${hsum} block_min=${bmin:-?} block_max=${bmax:-?} $(utc)"
    if [ -n "${HALTED}" ]; then echo "FLEET_HEALTH HALTED ${HALTED} (fail-stop lines in the node log: node-sampler.sh halt=)"; fi
    if [ "${fsum}" -gt 0 ] || [ "${hsum}" -gt "${halt_base}" ] || [ "${dmax}" -ge "${dmaxlim}" ]; then return 3; fi
    return 0
}

# stop_if_done — exit when the segment named by --until-file has ended or --max-secs has passed.
stop_if_done() {
    local endl=""
    if [ -n "${until_file}" ]; then
        endl="$(grep -E '^== [A-Za-z0-9_-]+ (rc=|LEFT_RUNNING )' "${until_file}" 2>/dev/null | tail -n 1)" || endl=""
        if [ -n "${endl}" ]; then echo "FLEET_HEALTH the walk ended (${endl})"; exit 0; fi
    fi
    if [ $(( $(date +%s) - t0 )) -ge "${max_secs}" ]; then echo "FLEET_HEALTH run=${run} max-secs=${max_secs} reached $(utc)"; exit 4; fi
}

if [ "${watch}" = 0 ]; then once; exit $?; fi
while :; do
    once; rc=$?
    [ "${rc}" != 3 ] || { echo "FLEET_HEALTH ALARM (disk >= ${dmaxlim} % or fatal_db > 0 or halt > ${halt_base})${HALTED:+ halted: ${HALTED}}"; exit 3; }
    [ "${rc}" != 4 ] || exit 0
    stop_if_done
    left=$(( max_secs - ($(date +%s) - t0) ))
    if [ "${left}" -lt "${watch}" ]; then sleep "${left}"; else sleep "${watch}"; fi
    stop_if_done
done
