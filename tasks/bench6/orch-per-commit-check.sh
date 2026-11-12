#!/usr/bin/env bash
# orch-per-commit-check.sh — bench 6, orchestrator only: every commit of <base>..<head> compiles alone
# (cargo check --locked --workspace --all-targets, -D warnings), in a spare worktree, through the build-slot
# wrapper. Required before the upstream stack (W8), not for the image. Hours.
#   tasks/bench6/orch-per-commit-check.sh <worktree> <base> <head>
# Resumable: a commit with an OK line in the result file is skipped. Stops between two commits when the file
# tasks/bench6/STOP-per-commit exists (nothing of this program is ever killed: touch that file instead), and
# waits while tasks/bench6/QUIET exists (the slot wrapper does). Result file, one line per commit:
#   tasks/bench6/per-commit-check-<head>.txt     OK|FAIL <sha> <secs>s <subject>
# Last line on stdout: PER-COMMIT <head> ok=<n> fail=<n> left=<n> <done|stopped> <UTC>
# Launch detached and alone in its call:  setsid bash tasks/bench6/orch-per-commit-check.sh <wt> <base> <head> > <log> 2>&1 < /dev/null &
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
SLOT="${ROOT}/tasks/bench6/cargo-slot.sh"
STOP="${ROOT}/tasks/bench6/STOP-per-commit"
wt="${1:?worktree}"; base="${2:?base}"; head="${3:?head}"
cd "${wt}" || exit 2
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "worktree ${wt} is dirty" >&2; exit 2; }
h="$(git rev-parse --short=9 "${head}")" || exit 2
res="${ROOT}/tasks/bench6/per-commit-check-${h}.txt"
touch "${res}"
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
ok=0; fail=0; left=0; state="done"
for sha in $(git rev-list --reverse "${base}..${head}"); do
    s="$(git rev-parse --short=9 "${sha}")"
    if grep -q "^OK ${s} " "${res}"; then ok=$((ok + 1)); continue; fi
    if [ -e "${STOP}" ]; then left=$((left + 1)); state=stopped; continue; fi
    git switch -q --detach "${sha}" || { echo "FAIL ${s} 0s (checkout failed)" >> "${res}"; fail=$((fail + 1)); continue; }
    t0="$(date +%s)"
    if "${SLOT}" cargo check --locked --workspace --all-targets > "target/tmp/per-commit-${s}.log" 2>&1; then
        echo "OK ${s} $(( $(date +%s) - t0 ))s $(git log -1 --format=%s "${sha}" | cut -c1-100)" >> "${res}"; ok=$((ok + 1))
    else
        echo "FAIL ${s} $(( $(date +%s) - t0 ))s $(git log -1 --format=%s "${sha}" | cut -c1-100)" >> "${res}"; fail=$((fail + 1))
    fi
done
echo "PER-COMMIT ${h} ok=${ok} fail=${fail} left=${left} ${state} $(date -u +%FT%TZ)"
