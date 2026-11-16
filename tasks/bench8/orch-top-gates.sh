#!/usr/bin/env bash
# orch-top-gates.sh — bench 8 program, orchestrator only: every gate of the switch-free top
# (refactor/remove-bench-switches), each ONCE (no off arm is left), in one chain on a spare worktree.
#   setsid bash tasks/bench8/orch-top-gates.sh <worktree> <commit> <prev ref> [<stage>...] > <log> 2>&1 < /dev/null &
# Stages, in this order unless named: cargo sets x3 upgrade restore hunt
#   cargo    fmt --check; ./etc/ci-lanes.sh clippy; cargo nextest run --locked --workspace
#   sets     make test-restarts, test-epochs, test-sigkill, test-e2e-resync (tasks/bench7/orch-e2e-sets.sh, no parameters)
#   x3       every e2e test the stack adds, three times in a row
#   upgrade  make build-e2e-bin-prev TN_PREV_REF=<prev ref>, then make test-upgrade three times (a SKIPPED line fails the stage)
#   restore  the three state_export_import tests
#   hunt     the order hold model's long hunt, 100,000 cases
# Everything e2e goes through the second lane (one e2e job on the machine at a time).
# Lines: TOP8 start …   TOP8 <stage> rc=<rc> (<summary>) <UTC>   TOP8 done rc=<n> <UTC>
# Logs: <worktree>/target/tmp/top8-<commit>-<stage>*.log, each ending in EXIT=<rc>.
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
LANE="${ROOT}/tasks/bench6/e2e-lane2.sh"
SLOT="${ROOT}/tasks/bench6/cargo-slot.sh"
wt="${1:?worktree}"; rev="${2:?commit}"; prev="${3:?previous ref}"; shift 3
stages="${*:-cargo sets x3 upgrade restore hunt}"
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "${rev}^{commit}")" ]; then git switch -q --detach "${rev}" || exit 2; fi
head="$(git rev-parse --short=9 HEAD)"
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
unset TN_E2E_PARAMETERS CARGO_TARGET_DIR
NIGHTLY="$(cat rust-nightly)"
echo "TOP8 start $(date -u +%FT%TZ) worktree=${wt} head=${head} prev=$(git rev-parse --short=9 "${prev}^{commit}") stages=[${stages}] pid=$$"
overall=0
note() { # <stage> <rc> <summary>
    echo "TOP8 $1 rc=$2 ($3) $(date -u +%FT%TZ)"; [ "$2" -eq 0 ] || overall=1
}
for stage in ${stages}; do
    case "${stage}" in
        cargo)
            log="target/tmp/top8-${head}-fmt.log"
            "${SLOT}" cargo "+${NIGHTLY}" fmt --all -- --check > "${log}" 2>&1; rc=$?; echo "EXIT=${rc}" >> "${log}"
            note fmt "${rc}" "$(grep -c '^Diff in' "${log}") diffs"
            log="target/tmp/top8-${head}-clippy.log"
            "${SLOT}" ./etc/ci-lanes.sh clippy > "${log}" 2>&1; rc=$?; echo "EXIT=${rc}" >> "${log}"
            note clippy "${rc}" "$(grep -cE '^(warning|error)' "${log}") warning or error lines"
            log="target/tmp/top8-${head}-nextest.log"
            "${SLOT}" cargo nextest run --locked --workspace --no-fail-fast > "${log}" 2>&1; rc=$?; echo "EXIT=${rc}" >> "${log}"
            note nextest "${rc}" "$(grep -E 'Summary' "${log}" | tail -1 | sed 's/^ *//')"
            ;;
        sets)
            E2E_SETS="restarts epochs sigkill resync" bash "${ROOT}/tasks/bench7/orch-e2e-sets.sh" "${wt}" "${rev}" "plain="; rc=$?
            note sets "${rc}" "see the E2E-SETS lines above"
            ;;
        x3)
            log="target/tmp/top8-${head}-new-e2e-x3.log"
            "${LANE}" cargo nextest run --locked -p e2e-tests --test it --run-ignored all --no-fail-fast --stress-count 3 \
                --success-output never --failure-output final \
                -E 'test(/^(exec_block|epoch_close_forms|epoch_record_walk|digest_order_hold)::/)' > "${log}" 2>&1; rc=$?
            echo "EXIT=${rc}" >> "${log}"
            note x3 "${rc}" "$(grep -E 'Summary|Stress test' "${log}" | tail -1 | sed 's/^ *//')"
            ;;
        upgrade)
            log="target/tmp/top8-${head}-prev-build.log"
            # The previous binary is built as that ref builds it: none of this program's RUSTFLAGS.
            env -u RUSTFLAGS -u CARGO_TARGET_DIR CARGO_INCREMENTAL=0 "${LANE}" make build-e2e-bin-prev TN_PREV_REF="${prev}" > "${log}" 2>&1; rc=$?
            echo "EXIT=${rc}" >> "${log}"
            note prev-build "${rc}" "$(grep -E 'build-e2e-bin-prev:' "${log}" | tail -1 | cut -c1-160)"
            if [ "${rc}" -eq 0 ]; then
                # Three runs of make test-upgrade (the rolling test and the mixed-binary vote test). A passing
                # test's output is kept (NEXTEST_SUCCESS_OUTPUT=final): the vote test prints its counts, and a
                # SKIPPED line there means the previous binary had no execution-delay hook.
                NEXTEST_SUCCESS_OUTPUT=final E2E_SETS="upgrade" bash "${ROOT}/tasks/bench7/orch-e2e-sets.sh" "${wt}" "${rev}" "run1=" "run2=" "run3="; rc=$?
                skipped="$(grep -l 'SKIPPED' target/tmp/orch-e2e-${head}-run[123]-upgrade.log 2>/dev/null | wc -l)"
                [ "${skipped}" -eq 0 ] || rc=1
                note upgrade "${rc}" "three runs, ${skipped} with a SKIPPED line; see the E2E-SETS lines above"
            fi
            ;;
        restore)
            log="target/tmp/top8-${head}-restore-e2e.log"
            "${LANE}" cargo nextest run --locked -p e2e-tests --test it --run-ignored all --no-fail-fast \
                --success-output never --failure-output final \
                -E 'test(/^state_export_import::/)' > "${log}" 2>&1; rc=$?
            echo "EXIT=${rc}" >> "${log}"
            note restore "${rc}" "$(grep -E 'Summary' "${log}" | tail -1 | sed 's/^ *//')"
            ;;
        hunt)
            log="target/tmp/top8-${head}-hunt.log"
            TN_ORDER_HOLD_HUNT_CASES=100000 "${SLOT}" cargo nextest run --locked -p tn-primary --no-capture --run-ignored only \
                -E 'test(=order_hold::model::long_hunt_order_hold)' > "${log}" 2>&1; rc=$?
            echo "EXIT=${rc}" >> "${log}"
            note hunt "${rc}" "$(grep -E 'order hold long hunt' "${log}" | tail -1 | cut -c1-160)"
            ;;
        *) echo "unknown stage ${stage}" >&2; exit 64 ;;
    esac
done
echo "TOP8 done rc=${overall} $(date -u +%FT%TZ)"
exit "${overall}"
