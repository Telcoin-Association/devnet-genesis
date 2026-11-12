#!/usr/bin/env bash
# orch-image-trial.sh — bench 6, orchestrator only: a LOCAL trial build of the node image from a worktree at a
# commit, exactly as the image cut will build it (etc/Dockerfile, CARGO_FEATURES=faucet, GIT_SHA, linux/amd64),
# loaded into the local docker and never pushed. It proves that the release build with the image's feature set
# compiles (the workspace gates build dev and test profiles with other features) and warms the cargo cache mount.
#   tasks/bench6/orch-image-trial.sh <worktree> <commit>
# Holds tasks/bench6/QUIET while it builds (the build-slot wrapper and the e2e lane's jobs wait). Lines:
#   IMAGE-TRIAL start …   IMAGE-TRIAL build rc=<rc> secs=<n>   IMAGE-TRIAL version: …   IMAGE-TRIAL done rc=<rc>
# Launch detached and alone in its call:  setsid bash tasks/bench6/orch-image-trial.sh <wt> <rev> > <log> 2>&1 < /dev/null &
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
QUIET="${ROOT}/tasks/bench6/QUIET"
wt="${1:?worktree}"; rev="${2:?commit}"
cd "${wt}" || exit 2
head="$(git rev-parse HEAD)"
[ "$(git rev-parse "${rev}^{commit}")" = "${head}" ] || { echo "IMAGE-TRIAL ${wt} is at ${head}, not ${rev}"; exit 2; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "IMAGE-TRIAL ${wt} is dirty"; exit 2; }
[ ! -e "${QUIET}" ] || { echo "IMAGE-TRIAL a quiet window is already held (${QUIET})"; exit 2; }
trap 'rm -f "${QUIET}"' EXIT
trap 'exit 130' INT TERM
touch "${QUIET}"
tag="bench6-trial:${head:0:9}"
t0="$(date +%s)"
echo "IMAGE-TRIAL start $(date -u +%FT%TZ) worktree=${wt} head=${head} tag=${tag} (local only, not pushed) pid=$$"
docker buildx build -f etc/Dockerfile --build-arg CARGO_FEATURES=faucet --build-arg "GIT_SHA=${head}" \
    --platform linux/amd64 -t "${tag}" --load --progress=plain . 2>&1 | grep -v '^#[0-9]* *[0-9.]* *\(Compiling\|Downloaded\|Downloading\|Checking\) ' | tail -60
rc="${PIPESTATUS[0]}"
echo "IMAGE-TRIAL build rc=${rc} secs=$(( $(date +%s) - t0 )) $(date -u +%FT%TZ)"
if [ "${rc}" -eq 0 ]; then
    echo "IMAGE-TRIAL version: $(docker run --rm "${tag}" telcoin --version 2>&1 | tr '\n' ' ' | cut -c1-400)"
    echo "IMAGE-TRIAL image: $(docker images --format '{{.ID}} {{.Size}}' "${tag}" | head -1)"
fi
echo "IMAGE-TRIAL done rc=${rc} $(date -u +%FT%TZ)"
exit "${rc}"
