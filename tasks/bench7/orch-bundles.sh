#!/usr/bin/env bash
# orch-bundles.sh — bench 7 program, orchestrator only: build the four bench-6 site bundles in order.
#   setsid bash tasks/bench7/orch-bundles.sh > tasks/bench7/orch-bundles-<UTC>.log 2>&1 < /dev/null &
# One bundle at a time through the launcher (it refuses a dirty benchmark/ tree and a running bundle),
# each waited for by its `== bundle rc=` line with a deadline; the chain stops at the first rc != 0.
# Order matters: a compare target's scratch (benchmark/work/report/<id>/) must exist before the run
# that compares against it. Nothing here touches the cloud.
# Lines: BUNDLES start …  BUNDLE <run> launched log=…  BUNDLE <run> rc=<n> secs=<n>  BUNDLES done rc=<n>
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
DEADLINE_SECS="${BUNDLE_DEADLINE_SECS:-5400}"
cd "${ROOT}" || exit 2
B=benchmark/report/backfill
# run | env file | compare target | backfill file
PLAN="
r20261113-1351|tasks/bench6/r20261113-1351/bench6-run2.env|r20261107-1504|${B}/2026-11-13-bench6-always-20k.json
r20261113-1630|tasks/bench6/r20261113-1630/bench6-run2b.env|r20261113-1351|${B}/2026-11-13-bench6-always-50k.json
r20261113-2118|tasks/bench6/r20261113-2118/bench6-run3.env|r20261113-1351|${B}/2026-11-13-bench6-adaptive-20k.json
r20261114-0000|tasks/bench6/r20261114-0000/bench6-run3.env|r20261113-1630|${B}/2026-11-13-bench6-adaptive-50k.json
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
    out="$(bash benchmark/launch/launch.sh "${envf}" bundle --compare "${cmp}" --backfill "${bf}" 2>&1)"; lrc=$?
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
