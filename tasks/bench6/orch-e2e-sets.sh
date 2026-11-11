#!/usr/bin/env bash
# orch-e2e-sets.sh — the repo's own e2e sets (restarts, epochs, sigkill; the Makefile's filters) through the e2e lane, in a
# spare worktree detached at a commit, once per "label=parameters" argument. parameters is a TN_E2E_PARAMETERS value
# ("key: value; key: value"; empty = every switch at its default). Orchestrator only: hours of lane time.
#   tasks/bench6/orch-e2e-sets.sh <worktree> <commit> <label>=<params> [<label>=<params> …]
# Logs: <worktree>/target/tmp/orch-e2e-<commit>-<label>-<set>.log, each ending in EXIT=<rc>; one summary line per label.
set -uo pipefail
SLOT=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh
LANE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh
wt="${1:?worktree}"; rev="${2:?commit}"; shift 2
[ "$#" -ge 1 ] || { echo "no label=params given" >&2; exit 64; }
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
if [ "$(git rev-parse --short=9 HEAD)" != "$(git rev-parse --short=9 "${rev}")" ]; then git switch -q --detach "${rev}" || exit 2; fi
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
export TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295
head="$(git rev-parse --short=9 HEAD)"
"${SLOT}" cargo build --locked --profile e2e --bin telcoin-network --features tn-storage/test-utils --target-dir "$PWD/target" > "target/tmp/orch-e2e-${head}-bin.log" 2>&1
rc=$?; echo "EXIT=${rc}" >> "target/tmp/orch-e2e-${head}-bin.log"
[ "${rc}" -eq 0 ] || { echo "E2E-SETS ${head} binary build failed"; exit 1; }
export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"
for arg in "$@"; do
    label="${arg%%=*}"; params="${arg#*=}"; sum=""
    if [ -n "${params}" ]; then export TN_E2E_PARAMETERS="${params}"; else unset TN_E2E_PARAMETERS; fi
    for set in restarts epochs sigkill; do
        log="target/tmp/orch-e2e-${head}-${label}-${set}.log"
        case "${set}" in
        restarts) "${LANE}" cargo nextest run --locked --no-fail-fast -p e2e-tests --test it --run-ignored all test_restarts > "${log}" 2>&1 ;;
        epochs)   "${LANE}" cargo nextest run --locked --no-fail-fast -p e2e-tests --test it --run-ignored all test_epoch > "${log}" 2>&1 ;;
        sigkill)  "${LANE}" cargo nextest run --profile sigkill --locked --no-fail-fast -p e2e-tests --test it --run-ignored all -E 'test(sigkill::)' > "${log}" 2>&1 ;;
        esac
        rc=$?; echo "EXIT=${rc}" >> "${log}"
        sum="${sum} ${set}=${rc}($(grep -E 'Summary' "${log}" | tail -1 | sed 's/^ *Summary *//' | tr -s ' ' | cut -c1-70))"
    done
    echo "E2E-SETS ${head} ${label} params=[${params}]${sum} $(date -u +%FT%TZ)"
done
