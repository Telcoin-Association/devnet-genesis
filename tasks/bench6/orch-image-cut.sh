#!/usr/bin/env bash
# orch-image-cut.sh — bench 6, orchestrator only: build the node image from a worktree at a commit exactly as
# etc/Dockerfile builds it (CARGO_FEATURES=faucet, GIT_SHA, linux/amd64; no test-utils feature; the
# TN_TEST_*_DELAY_MS hooks unset at run time) and PUSH it to the bench registry under <tag>; record the digest.
#   tasks/bench6/orch-image-cut.sh <worktree> <commit> <tag>
# Refuses a dirty worktree, a worktree not at <commit>, and a commit that is not on the pushed branch
# (git ls-remote of refs/heads/<branch> must equal it), so the image is always built from pushed source.
# Holds tasks/bench6/QUIET while it builds. Lines:
#   IMAGE-CUT start …   IMAGE-CUT build rc=<rc> secs=<n>   IMAGE-CUT digest=sha256:<hex> ref=<repo>@sha256:<hex>
#   IMAGE-CUT version: …   IMAGE-CUT done rc=<rc>
# Writes <devnet-genesis>/tasks/bench6/image-build.meta.json (tag, digest, commit, branch, worktree, UTC).
# Launch detached and alone in its call:  setsid bash tasks/bench6/orch-image-cut.sh <wt> <rev> <tag> > <log> 2>&1 < /dev/null &
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
QUIET="${ROOT}/tasks/bench6/QUIET"
REPO=us-docker.pkg.dev/telcoin-network/tn-public/adiri
REMOTE=git@github.com:Telcoin-Association/telcoin-network.git
wt="${1:?worktree}"; rev="${2:?commit}"; tag="${3:?tag}"
case "${tag}" in *[!a-z0-9.-]*|'') echo "IMAGE-CUT bad tag '${tag}'"; exit 2 ;; esac
cd "${wt}" || exit 2
head="$(git rev-parse HEAD)"
[ "$(git rev-parse "${rev}^{commit}")" = "${head}" ] || { echo "IMAGE-CUT ${wt} is at ${head}, not ${rev}"; exit 2; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "IMAGE-CUT ${wt} is dirty"; exit 2; }
branch="$(git rev-parse --abbrev-ref HEAD)"
remote_head="$(git ls-remote --heads "${REMOTE}" "${branch}" | awk '{ print $1 }')"
[ "${remote_head}" = "${head}" ] || { echo "IMAGE-CUT ${branch} on the remote is '${remote_head}', not ${head}: push first"; exit 2; }
[ ! -e "${QUIET}" ] || { echo "IMAGE-CUT a quiet window is already held (${QUIET})"; exit 2; }
trap 'rm -f "${QUIET}"' EXIT
trap 'exit 130' INT TERM
touch "${QUIET}"
meta="$(mktemp "${TMPDIR:-/tmp}/image-cut-meta.XXXXXX")"
t0="$(date +%s)"
echo "IMAGE-CUT start $(date -u +%FT%TZ) worktree=${wt} branch=${branch} head=${head} tag=${REPO}:${tag} pid=$$"
docker buildx build -f etc/Dockerfile --build-arg CARGO_FEATURES=faucet --build-arg "GIT_SHA=${head}" \
    --platform linux/amd64 -t "${REPO}:${tag}" --push --metadata-file "${meta}" --progress=plain . 2>&1 \
    | grep -v '^#[0-9]* *[0-9.]* *\(Compiling\|Downloaded\|Downloading\|Checking\) ' | tail -40
rc="${PIPESTATUS[0]}"
echo "IMAGE-CUT build rc=${rc} secs=$(( $(date +%s) - t0 )) $(date -u +%FT%TZ)"
if [ "${rc}" -eq 0 ]; then
    digest="$(jq -r '."containerimage.digest" // empty' "${meta}" 2>/dev/null)"
    case "${digest}" in sha256:????????????????????????????????????????????????????????????????) ;; *) echo "IMAGE-CUT no digest in the build metadata ('${digest}')"; rm -f "${meta}"; exit 1 ;; esac
    echo "IMAGE-CUT digest=${digest} ref=${REPO}@${digest}"
    echo "IMAGE-CUT version: $(docker run --rm --pull always "${REPO}@${digest}" telcoin --version 2>&1 | grep -v -i 'pull\|digest:\|status:' | tr '\n' ' ' | cut -c1-400)"
    jq -n --arg tag "${REPO}:${tag}" --arg digest "${digest}" --arg ref "${REPO}@${digest}" --arg sha "${head}" --arg branch "${branch}" \
        --arg wt "${wt}" --arg ts "$(date -u +%FT%TZ)" --arg features faucet \
        '{tag: $tag, digest: $digest, ref: $ref, node_git_sha: $sha, branch: $branch, worktree: $wt, cargo_features: $features, built_utc: $ts}' \
        > "${ROOT}/tasks/bench6/image-build.meta.json" || rc=1
fi
rm -f "${meta}"
echo "IMAGE-CUT done rc=${rc} $(date -u +%FT%TZ)"
exit "${rc}"
