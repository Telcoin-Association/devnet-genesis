#!/usr/bin/env bash
# orch-image-cut.sh — bench 8, orchestrator only (a copy of tasks/bench7/orch-image-cut.sh; the meta file goes under tasks/bench8/): build the node image from a worktree at a commit with the
# repo's own etc/Dockerfile (CARGO_FEATURES=faucet, GIT_SHA, linux/amd64; default storage engine tn-lmdb; no
# test-utils feature; the TN_TEST_* hooks unset at run time) PLUS ONE LINE appended to the final stage:
#     ENV TN_ALLOW_FAUCET_ON_CHAIN=true
# and PUSH it to the bench registry under <tag>; record the digest.
#   tasks/bench8/orch-image-cut.sh <worktree> <commit> <tag>
# Why the extra line: since #1716 a `faucet` build refuses every chain but adiri unless it is started with
# --allow-faucet-on-chain or TN_ALLOW_FAUCET_ON_CHAIN=true. The deploy's step 7 starts each node once during
# staging with a fixed argument list, before the harness can add a flag, so the allowance must be in the
# image's environment (the harness's image probe refuses a faucet build without it). The Dockerfile used is
# written to a temp file OUTSIDE the worktree (etc/Dockerfile + the one line); the worktree stays clean.
# Refuses a dirty worktree, a worktree not at <commit>, and a commit that is not on the pushed branch
# (git ls-remote of refs/heads/<branch> must equal it), so the image is always built from pushed source.
# Holds tasks/bench6/QUIET while it builds (the units' build-slot wrapper and the e2e lane wait on that file).
# Lines:
#   IMAGE-CUT start …   IMAGE-CUT build rc=<rc> secs=<n>   IMAGE-CUT digest=sha256:<hex> ref=<repo>@sha256:<hex>
#   IMAGE-CUT env: …    IMAGE-CUT version: …               IMAGE-CUT done rc=<rc>
# Writes <devnet-genesis>/tasks/bench8/image-build.meta.json (tag, digest, commit, branch, worktree, features,
# extra_env, dockerfile sha256 of the repo's file and of the one used, UTC).
# Launch detached and alone in its call:  setsid bash tasks/bench8/orch-image-cut.sh <wt> <rev> <tag> > <log> 2>&1 < /dev/null &
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
QUIET="${ROOT}/tasks/bench6/QUIET"
REPO=us-docker.pkg.dev/telcoin-network/tn-public/adiri
REMOTE=git@github.com:Telcoin-Association/telcoin-network.git
EXTRA_ENV="TN_ALLOW_FAUCET_ON_CHAIN=true"
wt="${1:?worktree}"; rev="${2:?commit}"; tag="${3:?tag}"
case "${tag}" in *[!a-z0-9.-]*|'') echo "IMAGE-CUT bad tag '${tag}'"; exit 2 ;; esac
cd "${wt}" || exit 2
head="$(git rev-parse HEAD)"
[ "$(git rev-parse "${rev}^{commit}")" = "${head}" ] || { echo "IMAGE-CUT ${wt} is at ${head}, not ${rev}"; exit 2; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "IMAGE-CUT ${wt} is dirty"; exit 2; }
branch="$(git rev-parse --abbrev-ref HEAD)"
remote_head="$(git ls-remote --heads "${REMOTE}" "${branch}" | awk '{ print $1 }')"
[ "${remote_head}" = "${head}" ] || { echo "IMAGE-CUT ${branch} on the remote is '${remote_head}', not ${head}: push first"; exit 2; }
[ -f etc/Dockerfile ] || { echo "IMAGE-CUT no etc/Dockerfile in ${wt}"; exit 2; }
# The appended ENV must land in the FINAL stage: the last FROM must be the runtime stage and nothing after
# the file's end may open another stage. Refuse a Dockerfile whose last instruction is not CMD or ENTRYPOINT.
last="$(grep -E '^[A-Z]+ ' etc/Dockerfile | tail -1 | awk '{ print $1 }')"
case "${last}" in CMD|ENTRYPOINT) ;; *) echo "IMAGE-CUT etc/Dockerfile ends in '${last}', not CMD/ENTRYPOINT: check the final stage by hand"; exit 2 ;; esac
[ ! -e "${QUIET}" ] || { echo "IMAGE-CUT a quiet window is already held (${QUIET})"; exit 2; }
meta="$(mktemp "${TMPDIR:-/tmp}/image-cut-meta.XXXXXX")"
dfile="$(mktemp "${TMPDIR:-/tmp}/image-cut-dockerfile.XXXXXX")"
trap 'rm -f "${QUIET}" "${meta}" "${dfile}"' EXIT
trap 'exit 130' INT TERM
touch "${QUIET}"
{ cat etc/Dockerfile; printf '\n# bench image only: the faucet allowance for a non-adiri chain (see tasks/bench8/orch-image-cut.sh)\nENV %s\n' "${EXTRA_ENV}"; } > "${dfile}"
df_repo="$(sha256sum etc/Dockerfile | awk '{ print $1 }')"; df_used="$(sha256sum "${dfile}" | awk '{ print $1 }')"
t0="$(date +%s)"
echo "IMAGE-CUT start $(date -u +%FT%TZ) worktree=${wt} branch=${branch} head=${head} tag=${REPO}:${tag} extra_env=${EXTRA_ENV} pid=$$"
docker buildx build -f "${dfile}" --build-arg CARGO_FEATURES=faucet --build-arg "GIT_SHA=${head}" \
    --platform linux/amd64 -t "${REPO}:${tag}" --push --metadata-file "${meta}" --progress=plain . 2>&1 \
    | grep -v '^#[0-9]* *[0-9.]* *\(Compiling\|Downloaded\|Downloading\|Checking\) ' | tail -40
rc="${PIPESTATUS[0]}"
echo "IMAGE-CUT build rc=${rc} secs=$(( $(date +%s) - t0 )) $(date -u +%FT%TZ)"
if [ "${rc}" -eq 0 ]; then
    digest="$(jq -r '."containerimage.digest" // empty' "${meta}" 2>/dev/null)"
    case "${digest}" in sha256:????????????????????????????????????????????????????????????????) ;; *) echo "IMAGE-CUT no digest in the build metadata ('${digest}')"; exit 1 ;; esac
    echo "IMAGE-CUT digest=${digest} ref=${REPO}@${digest}"
    envline="$(docker run --rm --pull always --entrypoint /usr/bin/env "${REPO}@${digest}" 2>/dev/null | grep '^TN_ALLOW_FAUCET_ON_CHAIN=' | head -1)"
    echo "IMAGE-CUT env: ${envline:-MISSING}"
    [ "${envline}" = "${EXTRA_ENV}" ] || { echo "IMAGE-CUT the pushed image does not carry ${EXTRA_ENV}"; rc=1; }
    echo "IMAGE-CUT version: $(docker run --rm "${REPO}@${digest}" telcoin --version 2>&1 | tr '\n' ' ' | cut -c1-600)"
    if [ "${rc}" -eq 0 ]; then
        jq -n --arg tag "${REPO}:${tag}" --arg digest "${digest}" --arg ref "${REPO}@${digest}" --arg sha "${head}" --arg branch "${branch}" \
            --arg wt "${wt}" --arg ts "$(date -u +%FT%TZ)" --arg features faucet --arg extra_env "${EXTRA_ENV}" \
            --arg df_repo "${df_repo}" --arg df_used "${df_used}" \
            '{tag: $tag, digest: $digest, ref: $ref, node_git_sha: $sha, branch: $branch, worktree: $wt, cargo_features: $features,
              extra_env: $extra_env, dockerfile_sha256_repo: $df_repo, dockerfile_sha256_used: $df_used, built_utc: $ts}' \
            > "${ROOT}/tasks/bench8/image-build.meta.json" || rc=1
    fi
fi
echo "IMAGE-CUT done rc=${rc} $(date -u +%FT%TZ)"
exit "${rc}"
