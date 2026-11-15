#!/usr/bin/env bash
# orch-bundles-b7.sh — bench 7, orchestrator only: build the two bench 7 site bundles in order (orch-bundles.sh with bench 7's plan).
#   setsid bash tasks/bench7/orch-bundles-b7.sh > tasks/bench7/orch-bundles-<UTC>.log 2>&1 < /dev/null &
# One bundle at a time through the launcher (it refuses a dirty benchmark/ tree and a running bundle),
# each waited for by its `== bundle rc=` line with a deadline; the chain stops at the first rc != 0.
# Order matters: a compare target's scratch (benchmark/work/report/<id>/) must exist before the run
# that compares against it. Nothing here touches the cloud.
# BUNDLE_FORCE_RUNS="<run id> …" passes --force for those runs (the tool then deletes and rebuilds that
# run's scratch under benchmark/work/report/; use it only for a scratch a refused attempt left behind).
# Lines: BUNDLES start …  BUNDLE <run> launched log=…  BUNDLE <run> rc=<n> secs=<n>  BUNDLES done rc=<n>
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
DEADLINE_SECS="${BUNDLE_DEADLINE_SECS:-5400}"
cd "${ROOT}" || exit 2
B=benchmark/report/backfill
# run | env file | compare target | backfill file
PLAN="
r20261115-1131|tasks/bench7/r20261115-1131/bench7-always.env|r20261113-1351|${B}/2026-11-15-bench7-always-20k.json
r20261115-1653|tasks/bench7/r20261115-1653/bench7-adaptive.env|r20261115-1131|${B}/2026-11-15-bench7-adaptive-20k.json
"
ONLY="${1:-}"   # optional: one run id, to repeat a single bundle
echo "BUNDLES start $(date -u +%FT%TZ) head=$(git rev-parse --short=12 HEAD) only='${ONLY}'"
overall=0
while IFS='|' read -r run envf cmp bf; do
    [ -n "${run}" ] || continue
    if [ -n "${ONLY}" ] && [ "${ONLY}" != "${run}" ]; then continue; fi
    for f in "${envf}" "${bf}"; do [ -f "${f}" ] || { echo "BUNDLE ${run} missing ${f}"; overall=2; break 2; }; done
    [ -d "benchmark/work/report/${cmp}" ] || [ -d "../tn-benchmarks/runs/${cmp}" ] \
        || { echo "BUNDLE ${run} compare target ${cmp} has no scratch and no site bundle"; overall=2; break; }
    t0="$(date +%s)"
    force=""
    case " ${BUNDLE_FORCE_RUNS:-} " in *" ${run} "*) force="--force" ;; esac   # only for a run whose scratch a refused attempt left behind
    # shellcheck disable=SC2086
    out="$(bash benchmark/launch/launch.sh "${envf}" bundle --compare "${cmp}" --backfill "${bf}" ${force} 2>&1)"; lrc=$?
    printf '%s\n' "${out}" | sed 's/^/  launch: /'
    [ "${lrc}" -eq 0 ] || { echo "BUNDLE ${run} launch refused rc=${lrc}"; overall=1; break; }
    log="$(printf '%s\n' "${out}" | sed -n 's/^LAUNCHED .* log=\(.*\)$/\1/p' | head -1)"
    [ -n "${log}" ] && [ -f "${log}" ] || { echo "BUNDLE ${run} no log named by the launcher"; overall=1; break; }
    echo "BUNDLE ${run} launched $(date -u +%FT%TZ) log=${log}"
    rc=""
    while :; do
        line="$(grep -E '^== bundle (rc=|LEFT_RUNNING )' "${log}" | tail -1)"
        if [ -n "${line}" ]; then
            rc="$(printf '%s\n' "${line}" | sed -n 's/^== bundle rc=\([0-9]*\).*/\1/p')"; [ -n "${rc}" ] || rc=125
            break
        fi
        if [ "$(( $(date +%s) - t0 ))" -gt "${DEADLINE_SECS}" ]; then echo "BUNDLE ${run} no rc line after ${DEADLINE_SECS} s (still running? read ${log})"; rc=124; break; fi
        sleep 20
    done
    echo "BUNDLE ${run} rc=${rc} secs=$(( $(date +%s) - t0 )) $(date -u +%FT%TZ)"
    tail -4 "${log}" | cut -c1-300 | sed 's/^/  tail: /'
    [ "${rc}" = "0" ] || { overall=1; break; }
done <<EOF
${PLAN}
EOF
echo "BUNDLES done rc=${overall} $(date -u +%FT%TZ)"
exit "${overall}"
