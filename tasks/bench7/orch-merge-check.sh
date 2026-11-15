#!/usr/bin/env bash
# orch-merge-check.sh — bench 7, orchestrator only: does the stack's top still build and pass beside a newer
# upstream main? Runs in a spare worktree that is already detached at a LOCAL trial merge commit (made with
# git merge-tree + git commit-tree: no branch moves, nothing is pushed), through the e2e lane so that it never
# runs beside an e2e job:
#   cargo check --locked --workspace --all-targets (warnings denied), then nextest of the packages both sides changed.
#   setsid bash tasks/bench7/orch-merge-check.sh <worktree> <packages…> > <log> 2>&1 < /dev/null &
# Lines: MERGE-CHECK start …   MERGE-CHECK check rc=<rc>   MERGE-CHECK nextest rc=<rc> (<summary>)   MERGE-CHECK done rc=<n> <UTC>
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
LANE="${ROOT}/tasks/bench6/e2e-lane2.sh"
wt="${1:?worktree}"; shift
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
head="$(git rev-parse --short=9 HEAD)"
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
echo "MERGE-CHECK start $(date -u +%FT%TZ) worktree=${wt} head=${head} parents=[$(git log -1 --format=%p)] pid=$$"
overall=0
"${LANE}" cargo check --locked --workspace --all-targets > "target/tmp/merge-check-${head}-check.log" 2>&1; rc=$?
echo "MERGE-CHECK check rc=${rc} ($(grep -E 'Finished|^error' "target/tmp/merge-check-${head}-check.log" | tail -1 | cut -c1-120)) $(date -u +%FT%TZ)"; [ "${rc}" -eq 0 ] || overall=1
pk=(); for p in "$@"; do pk+=(-p "$p"); done
if [ "${rc}" -eq 0 ] && [ "${#pk[@]}" -gt 0 ]; then
    "${LANE}" cargo nextest run --locked --no-fail-fast "${pk[@]}" > "target/tmp/merge-check-${head}-nextest.log" 2>&1; rc=$?
    echo "MERGE-CHECK nextest rc=${rc} ($(grep -E 'Summary' "target/tmp/merge-check-${head}-nextest.log" | tail -1 | sed 's/^ *//')) $(date -u +%FT%TZ)"; [ "${rc}" -eq 0 ] || overall=1
fi
echo "MERGE-CHECK done rc=${overall} $(date -u +%FT%TZ)"
exit "${overall}"
