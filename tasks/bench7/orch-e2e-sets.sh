#!/usr/bin/env bash
# orch-e2e-sets.sh — bench 7, orchestrator only: the repo's own e2e sets (restarts, epochs, sigkill)
# on a spare worktree detached at a commit, once per "label=parameters" argument, through the second
# e2e lane (one e2e job on the machine at a time; lane 1 holds another session's parked queue).
# Unlike bench 6's runner this one calls main's own Makefile targets (test-restarts, test-epochs,
# test-sigkill), so the fork pins, the binary's features and the nextest filters are the repo's and
# cannot drift from it. parameters is a TN_E2E_PARAMETERS value ("key: value; key: value"; empty =
# every switch at its default).
#   setsid bash tasks/bench7/orch-e2e-sets.sh <worktree> <commit> <label>=<params> [...] > <log> 2>&1 < /dev/null &
# Optional: E2E_SETS="restarts epochs" limits the sets (default: restarts epochs sigkill).
# Logs: <worktree>/target/tmp/orch-e2e-<commit>-<label>-<set>.log, each ending in EXIT=<rc>.
# Lines: E2E-SETS start …   E2E-SETS <commit> <label> params=[…] <set>=<rc>(<nextest summary>) … <UTC>   E2E-SETS done rc=<n>
set -uo pipefail
LANE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh
wt="${1:?worktree}"; rev="${2:?commit}"; shift 2
[ "$#" -ge 1 ] || { echo "no label=params given" >&2; exit 64; }
SETS="${E2E_SETS:-restarts epochs sigkill}"
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "${rev}^{commit}")" ]; then git switch -q --detach "${rev}" || exit 2; fi
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
unset CARGO_TARGET_DIR
head="$(git rev-parse --short=9 HEAD)"
echo "E2E-SETS start $(date -u +%FT%TZ) worktree=${wt} head=${head} sets=[${SETS}] labels=$# pid=$$"
overall=0
for arg in "$@"; do
    label="${arg%%=*}"; params="${arg#*=}"; sum=""
    case "${label}" in *[!A-Za-z0-9_.-]*|'') echo "bad label '${label}'" >&2; exit 64 ;; esac
    if [ -n "${params}" ]; then export TN_E2E_PARAMETERS="${params}"; else unset TN_E2E_PARAMETERS; fi
    for set in ${SETS}; do
        log="target/tmp/orch-e2e-${head}-${label}-${set}.log"
        case "${set}" in
            restarts) "${LANE}" make test-restarts > "${log}" 2>&1 ;;
            epochs)   "${LANE}" make test-epochs > "${log}" 2>&1 ;;
            sigkill)  "${LANE}" make test-sigkill > "${log}" 2>&1 ;;
            *) echo "unknown set ${set}" >&2; exit 64 ;;
        esac
        rc=$?; echo "EXIT=${rc}" >> "${log}"
        [ "${rc}" -eq 0 ] || overall=1
        sum="${sum} ${set}=${rc}($(grep -E 'Summary' "${log}" | tail -1 | sed 's/^ *Summary *//' | tr -s ' ' | cut -c1-80))"
    done
    echo "E2E-SETS ${head} ${label} params=[${params}]${sum} $(date -u +%FT%TZ)"
done
echo "E2E-SETS done rc=${overall} $(date -u +%FT%TZ)"
exit "${overall}"
