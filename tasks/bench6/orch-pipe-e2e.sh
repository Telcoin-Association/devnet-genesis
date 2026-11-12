#!/usr/bin/env bash
# orch-pipe-e2e.sh — bench 6, orchestrator only: the three pipelined-persist e2e tests (the SIGKILL test three
# times, the mixed fleet once, the epoch close under load once) on a worktree at a commit, through the second
# e2e lane. The e2e binary must already be built there (orch-e2e-sets2.sh builds it): target/e2e/telcoin-network.
#   tasks/bench6/orch-pipe-e2e.sh <worktree> <commit>
# Logs: <worktree>/target/tmp/orch-pipe-<commit>-<test>-<n>.log, each ending in EXIT=<rc>; last line
#   PIPE-E2E <commit> <test>-<n>=<rc> … <UTC>
set -uo pipefail
LANE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh
wt="${1:?worktree}"; rev="${2:?commit}"
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
[ "$(git rev-parse --short=9 HEAD)" = "$(git rev-parse --short=9 "${rev}")" ] || { echo "worktree ${wt} is not at ${rev}" >&2; exit 2; }
head="$(git rev-parse --short=9 HEAD)"
[ -x "$PWD/target/e2e/telcoin-network" ] || { echo "no e2e binary in ${wt}" >&2; exit 2; }
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
export TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295
export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"
unset TN_E2E_PARAMETERS
sum=""
for t in test_sigkill_mid_pipeline_replays:1 test_sigkill_mid_pipeline_replays:2 test_sigkill_mid_pipeline_replays:3 test_mixed_fleet_blocks_same:1 test_pipelined_epoch_close_under_load:1; do
    name="${t%%:*}"; n="${t##*:}"; log="target/tmp/orch-pipe-${head}-${name}-${n}.log"
    "${LANE}" cargo nextest run --locked -p e2e-tests --test it --run-ignored all -E "test(=persist_pipeline::${name})" > "${log}" 2>&1
    rc=$?; echo "EXIT=${rc}" >> "${log}"
    sum="${sum} ${name#test_}-${n}=${rc}"
done
echo "PIPE-E2E ${head}${sum} $(date -u +%FT%TZ)"
