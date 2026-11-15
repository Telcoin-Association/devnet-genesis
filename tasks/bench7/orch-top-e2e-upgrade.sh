#!/usr/bin/env bash
# orch-top-e2e-upgrade.sh — bench 7, orchestrator only: the repo's rolling-upgrade e2e set (make test-upgrade,
# crates/e2e-tests/tests/it/upgrade.rs: four validators upgraded in place, one at a time, from a previous node
# binary to this tree's) on the stack's top, with every switch at its default and with the stack's set on.
# orch-top-e2e-n.sh ran the set without a previous binary (`make test-upgrade` refuses: rc 2, no test ran);
# this builds one first with the repo's own target (make build-e2e-bin-prev TN_PREV_REF=<ref>: a detached
# worktree under target/prev-src, that ref's own Makefile and Cargo.lock, target/prev-e2e).
#   setsid bash tasks/bench7/orch-top-e2e-upgrade.sh <worktree> <commit> <prev ref> [<wait-for-file> <wait-for-pattern>] > <log> 2>&1 < /dev/null &
# Lines: TOP-UPGRADE start …   TOP-UPGRADE prev rc=<rc> (<the build's last line>)   E2E-SETS … (orch-e2e-sets.sh)   TOP-UPGRADE done rc=<n> <UTC>
# Logs: <worktree>/target/tmp/top-<commit>-prev-build.log, orch-e2e-<commit>-<label>-upgrade.log (overwritten).
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
LANE="${ROOT}/tasks/bench6/e2e-lane2.sh"
wt="${1:?worktree}"; rev="${2:?commit}"; prev="${3:?previous ref}"; waitfile="${4:-}"; waitpat="${5:-}"
ON='quorum_exec_block: true; quorum_exec_block_starved_rounds: 4; vote_queue_fix: true; digest_order_hold: true; epoch_record_collect_past_uncertified: true; epoch_record_recertify: true'
if [ -n "${waitfile}" ]; then until grep -q -- "${waitpat}" "${waitfile}" 2>/dev/null; do sleep 30; done; fi
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
[ "$(git rev-parse HEAD)" = "$(git rev-parse "${rev}^{commit}")" ] || { echo "worktree ${wt} is not at ${rev}" >&2; exit 2; }
head="$(git rev-parse --short=9 HEAD)"
mkdir -p "$PWD/target/tmp"
echo "TOP-UPGRADE start $(date -u +%FT%TZ) worktree=${wt} head=${head} prev=$(git rev-parse --short=9 "${prev}^{commit}") pid=$$"
log="target/tmp/top-${head}-prev-build.log"
# The previous binary is built as that ref builds it: none of this program's RUSTFLAGS.
env -u RUSTFLAGS -u CARGO_TARGET_DIR CARGO_INCREMENTAL=0 "${LANE}" make build-e2e-bin-prev TN_PREV_REF="${prev}" > "${log}" 2>&1; rc=$?
echo "EXIT=${rc}" >> "${log}"
echo "TOP-UPGRADE prev rc=${rc} ($(grep -E 'build-e2e-bin-prev:' "${log}" | tail -1 | cut -c1-200)) $(date -u +%FT%TZ)"
[ "${rc}" -eq 0 ] || { echo "TOP-UPGRADE done rc=1 $(date -u +%FT%TZ)"; exit 1; }
E2E_SETS="upgrade" bash "${ROOT}/tasks/bench7/orch-e2e-sets.sh" "${wt}" "${rev}" "off=" "on=${ON}"; rc=$?
echo "TOP-UPGRADE done rc=${rc} $(date -u +%FT%TZ)"
exit "${rc}"
