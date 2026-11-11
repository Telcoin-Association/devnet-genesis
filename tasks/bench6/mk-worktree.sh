#!/usr/bin/env bash
# mk-worktree.sh — bench 6: one telcoin-network worktree per unit.
#   tasks/bench6/mk-worktree.sh <unit> [<base ref>]
# Creates /home/drtnarg/coding/telcoin/tn-b6-<unit> on branch b6/u-<unit> at <base> (default: the
# integration branch bench/bench6-2026-11) and checks out tn-contracts by reference to the main
# checkout's module (no network clone). Idempotent: an existing worktree is reported and left alone.
set -euo pipefail
unit="${1:?unit}"; base="${2:-bench/bench6-2026-11}"
main=/home/drtnarg/coding/telcoin/telcoin-network
wt="/home/drtnarg/coding/telcoin/tn-b6-${unit}"
if [ -e "${wt}/.git" ]; then
    echo "exists ${wt} $(git -C "${wt}" rev-parse --short=9 HEAD) $(git -C "${wt}" rev-parse --abbrev-ref HEAD)"; exit 0
fi
git -C "${main}" worktree add -b "b6/u-${unit}" "${wt}" "${base}" >/dev/null 2>&1
git -C "${wt}" submodule update --init --reference "${main}/.git/modules/tn-contracts" tn-contracts >/dev/null 2>&1 \
    || git -C "${wt}" submodule update --init tn-contracts >/dev/null 2>&1
git -C "${wt}" config rerere.enabled true
mkdir -p "${wt}/target/tmp"
echo "created ${wt} $(git -C "${wt}" rev-parse --short=9 HEAD) b6/u-${unit} submodule=$(git -C "${wt}" submodule status | cut -c1-12)"
