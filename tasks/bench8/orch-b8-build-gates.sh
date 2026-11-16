#!/usr/bin/env bash
# orch-b8-build-gates.sh — bench 8 program, orchestrator only: the cargo gates of the bench 8 node build
# (bench/bench8-2026-11) on its own worktree, through the build-slot wrapper (no e2e here).
#   setsid bash tasks/bench8/orch-b8-build-gates.sh <worktree> > <log> 2>&1 < /dev/null &
# Stages: check (the workspace, all targets, warnings denied), fmt, clippy and nextest for the crates the
# build touches (tn-primary tn-config tn-engine tn-reth tn-metrics, and tn-node, which reads the config),
# the golden tests of the floor by name.
# Lines: B8-GATES start …   B8-GATES <stage> rc=<rc> (<summary>) <UTC>   B8-GATES done rc=<n> <UTC>
# Logs: <worktree>/target/tmp/b8-gates-<commit>-<stage>.log, each ending in EXIT=<rc>.
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
SLOT="${ROOT}/tasks/bench6/cargo-slot.sh"
wt="${1:?worktree}"
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
head="$(git rev-parse --short=9 HEAD)"
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
NIGHTLY="$(cat rust-nightly)"
PK=(-p tn-primary -p tn-config -p tn-engine -p tn-reth -p tn-metrics -p tn-node)
echo "B8-GATES start $(date -u +%FT%TZ) worktree=${wt} head=${head} pid=$$"
overall=0
run() { # <stage> <summary-grep> <cmd…>
    local stage="$1" pat="$2"; shift 2
    local log="target/tmp/b8-gates-${head}-${stage}.log"
    "$@" > "${log}" 2>&1; local rc=$?
    echo "EXIT=${rc}" >> "${log}"
    echo "B8-GATES ${stage} rc=${rc} ($(grep -E "${pat}" "${log}" | tail -1 | sed 's/^ *//' | cut -c1-140)) $(date -u +%FT%TZ)"
    [ "${rc}" -eq 0 ] || overall=1
}
run check 'Finished|^error' "${SLOT}" cargo check --locked --workspace --all-targets
run fmt 'Diff in|EXIT' "${SLOT}" cargo "+${NIGHTLY}" fmt --all -- --check
run clippy 'Finished|^error' "${SLOT}" cargo "+${NIGHTLY}" clippy --locked --all-targets "${PK[@]}" -- -D warnings
run nextest 'Summary' "${SLOT}" cargo nextest run --locked --no-fail-fast "${PK[@]}"
run golden 'Summary' "${SLOT}" cargo nextest run --locked -p tn-primary \
    -E 'test(test_quorum_exec_block_floor_golden_table) | test(test_quorum_exec_block_floor_parameter_sixteen) | test(test_header_proposed_reports_exec_quorum_and_floor) | test(test_digest_order_bookkeeping_keeps_payloads_golden)'
echo "B8-GATES done rc=${overall} $(date -u +%FT%TZ)"
exit "${overall}"
