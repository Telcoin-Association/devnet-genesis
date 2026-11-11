#!/usr/bin/env bash
# orch-gates.sh — the orchestrator's own gate runs for units whose agent was cut off after the code
# and the review were done (2026-11-11). Every cargo call goes through the bench-6 slot wrapper
# (which also waits for a quiet window to end). Logs: <worktree>/target/tmp/orch-<gate>.log, each
# ending in EXIT=<rc>; the last line printed is "ORCH-GATES <unit> <gate>=<rc> ...".
#   tasks/bench6/orch-gates.sh u7 | u0b | h9c | integ <worktree> <commit>
set -uo pipefail
SLOT=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh
LANE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh
unit="${1:?unit}"; sum=""
run() { # <gate> <cmd…>
    local gate="$1"; shift
    local log="target/tmp/orch-${gate}.log"
    "$@" > "${log}" 2>&1; local rc=$?
    echo "EXIT=${rc}" >> "${log}"
    sum="${sum} ${gate}=${rc}"
    return 0
}
node_env() {
    export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
    mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
    NIGHTLY="$(cat rust-nightly)"
}
case "${unit}" in
u7)
    cd /home/drtnarg/coding/telcoin/tn-b6-u7 || exit 2; node_env
    run fmt "${SLOT}" cargo "+${NIGHTLY}" fmt --all -- --check
    run check "${SLOT}" cargo check --locked --all-targets -p tn-worker -p tn-node
    run clippy "${SLOT}" cargo "+${NIGHTLY}" clippy --locked --all-targets --all-features -p tn-worker -- -D warnings
    run nextest "${SLOT}" cargo nextest run --locked -p tn-worker -p tn-node -E 'package(tn-worker)'
    ;;
u0b)
    cd /home/drtnarg/coding/telcoin/tn-b6-u0b || exit 2; node_env
    export TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295
    run fmt "${SLOT}" cargo "+${NIGHTLY}" fmt --all -- --check
    run check "${SLOT}" cargo check --locked --all-targets -p e2e-tests
    run clippy "${SLOT}" cargo "+${NIGHTLY}" clippy --locked --all-targets --all-features -p e2e-tests -- -D warnings
    run e2ebin "${SLOT}" cargo build --locked --profile e2e --bin telcoin-network --features tn-storage/test-utils --target-dir "$PWD/target"
    export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"
    run unit "${LANE}" cargo nextest run --locked -p e2e-tests -E 'kind(lib) | test(=common::test_log_field_reads_whole_fields)'
    run e2e "${LANE}" cargo nextest run --locked -p e2e-tests --test it --run-ignored all -E 'test(=restarts::test_restarts_store_failure_stops_the_node_mid_epoch)'
    ;;
h9c)
    cd /home/drtnarg/coding/telcoin/tn-transaction-generator || exit 2
    mkdir -p target/tmp
    run test "${SLOT}" cargo test --locked
    run fmt "${SLOT}" cargo fmt --check
    run clippy "${SLOT}" cargo clippy --locked --all-targets -- -D warnings
    run py python3 -m unittest discover -s bench/tests
    sum="${sum} golden=$(sha256sum src/blast/testdata/send-path-golden.json | cut -c1-16)"
    ;;
integ)
    # Interim cross-unit check of the integration head (NOT the W3 gates): the units were gated on their own
    # packages only, so this compiles every target of the workspace and runs every package's tests but the
    # e2e package (fixed ports: that one goes through the lane). Runs in a free unit worktree, detached at the
    # commit given, so a cherry-pick onto the integration branch cannot change files under the compiler.
    wt="${2:?worktree}"; rev="${3:?commit}"
    cd "${wt}" || exit 2
    [ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
    git switch -q --detach "${rev}" || exit 2
    node_env
    # No TN_*_FORK_EPOCH here: the repo's own `public-tests` runs the workspace's unit tests without them.
    tag="integ-$(git rev-parse --short=9 HEAD)"
    run "${tag}-fmt" "${SLOT}" cargo "+${NIGHTLY}" fmt --all -- --check
    run "${tag}-check" "${SLOT}" cargo check --locked --all-targets --workspace
    run "${tag}-clippy" "${SLOT}" cargo "+${NIGHTLY}" clippy --locked --all-targets --all-features --workspace -- -D warnings
    run "${tag}-nextest" "${SLOT}" cargo nextest run --locked --no-fail-fast --workspace --exclude e2e-tests
    unit="integ ${rev}"
    ;;
*) echo "unknown unit ${unit}" >&2; exit 64 ;;
esac
echo "ORCH-GATES ${unit}${sum} $(date -u +%FT%TZ)"
