#!/usr/bin/env bash
# orch-top-e2e.sh — bench 7, orchestrator only: the end-to-end gates of the stack's top, in one chain, on a
# spare worktree: (1) the repo's own e2e sets with every switch at its default and with the bench 7 set on
# (tasks/bench7/orch-e2e-sets.sh), (2) every e2e test the stack adds, three times in a row, (3) the order
# hold model's long hunt with a fresh seed. Everything e2e goes through the second lane (one e2e job on the
# machine at a time; it holds the quiet window, so every other cargo call of this program waits meanwhile).
#   setsid bash tasks/bench7/orch-top-e2e.sh <worktree> <commit> [<wait-for-file> <wait-for-pattern>] > <log> 2>&1 < /dev/null &
# Lines: TOP-E2E start …   TOP-E2E sets rc=<rc>   TOP-E2E new-x3 rc=<rc> (<nextest summary>)   TOP-E2E hunt rc=<rc>   TOP-E2E done rc=<n> <UTC>
# Logs: <worktree>/target/tmp/orch-e2e-<commit>-<label>-<set>.log (the sets), top-<commit>-new-e2e-x3.log, top-<commit>-hunt.log.
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
LANE="${ROOT}/tasks/bench6/e2e-lane2.sh"
SLOT="${ROOT}/tasks/bench6/cargo-slot.sh"
wt="${1:?worktree}"; rev="${2:?commit}"; waitfile="${3:-}"; waitpat="${4:-}"
ON='quorum_exec_block: true; quorum_exec_block_starved_rounds: 4; vote_queue_fix: true; digest_order_hold: true; epoch_record_collect_past_uncertified: true; epoch_record_conflict_halt: true; epoch_record_recertify: true'
if [ -n "${waitfile}" ]; then until grep -q -- "${waitpat}" "${waitfile}" 2>/dev/null; do sleep 30; done; fi
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
git switch -q --detach "${rev}" || exit 2
head="$(git rev-parse --short=9 HEAD)"
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
echo "TOP-E2E start $(date -u +%FT%TZ) worktree=${wt} head=${head} pid=$$"
overall=0
bash "${ROOT}/tasks/bench7/orch-e2e-sets.sh" "${wt}" "${rev}" "off=" "on=${ON}"; rc=$?
echo "TOP-E2E sets rc=${rc} $(date -u +%FT%TZ)"; [ "${rc}" -eq 0 ] || overall=1
log="target/tmp/top-${head}-new-e2e-x3.log"
unset TN_E2E_PARAMETERS
"${LANE}" cargo nextest run --locked -p e2e-tests --test it --run-ignored all --no-fail-fast --stress-count 3 \
    --success-output never --failure-output final \
    -E 'test(/^(exec_block|epoch_close_forms|epoch_record_walk|digest_order_hold)::/)' > "${log}" 2>&1; rc=$?
echo "EXIT=${rc}" >> "${log}"
echo "TOP-E2E new-x3 rc=${rc} ($(grep -E 'Summary|Stress test' "${log}" | tail -1 | sed 's/^ *//')) $(date -u +%FT%TZ)"; [ "${rc}" -eq 0 ] || overall=1
log="target/tmp/top-${head}-hunt.log"
TN_ORDER_HOLD_HUNT_CASES=100000 "${SLOT}" cargo nextest run --locked -p tn-primary --no-capture --run-ignored only \
    -E 'test(=order_hold::model::long_hunt_order_hold)' > "${log}" 2>&1; rc=$?
echo "EXIT=${rc}" >> "${log}"
echo "TOP-E2E hunt rc=${rc} ($(grep -E 'order hold long hunt' "${log}" | tail -1)) $(date -u +%FT%TZ)"; [ "${rc}" -eq 0 ] || overall=1
echo "TOP-E2E done rc=${overall} $(date -u +%FT%TZ)"
exit "${overall}"
