#!/usr/bin/env bash
# l2-shim/run.sh — rehearse ./devnet-deploy.sh --yes against a fake outside world (README.md).
#
# Usage: tasks/l2-shim/run.sh [--from N] [--to N] [--only N] [--keep] [--state DIR] [--sig pending|ok]
#   --from/--to/--only  the deploy step range (default 1..20); passed to devnet-deploy.sh
#   --state DIR         the fake cloud to use; an existing DIR continues an earlier run (needed for
#                       --from N > 1). Default: a fresh temporary directory
#   --keep              keep a temporary state directory (always kept with --state)
#   --sig pending       no signature on the release manifest: the run must stop at step 10 with exit 3
#   --sig ok            the shim signs SHA256SUMS with a throwaway key once step 6 wrote it
# Env: L2_SHIM_TND (tn-node-deployment checkout whose script flags are checked; default
#      ../tnd-l2-gateway next to this worktree).
# Exit: 0 the range ran clean · 1 not clean (see the report) · 2 usage or setup problem.
set -euo pipefail

SHIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WT="$(cd "${SHIM_DIR}/../.." && pwd)"
TND_DIR="${L2_SHIM_TND:-$(cd "${WT}/.." && pwd)/tnd-l2-gateway}"

FROM=1; TO=20; ONLY=""; KEEP=0; STATE_DIR=""; SIG=pending
die() { echo "run.sh: $1" >&2; exit 2; }
while [ $# -gt 0 ]; do
    case "$1" in
        --from) FROM="${2:-}"; shift 2 || die "--from needs a value" ;;
        --to) TO="${2:-}"; shift 2 || die "--to needs a value" ;;
        --only) ONLY="${2:-}"; shift 2 || die "--only needs a value" ;;
        --keep) KEEP=1; shift ;;
        --state) STATE_DIR="${2:-}"; shift 2 || die "--state needs a value" ;;
        --sig) SIG="${2:-}"; shift 2 || die "--sig needs a value" ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) die "unknown argument '$1'" ;;
    esac
done
for n in "${FROM}" "${TO}" ${ONLY:+"${ONLY}"}; do
    case "${n}" in ''|*[!0-9]*) die "step numbers are 1..20 (got '${n}')" ;; esac
    [ "${n}" -ge 1 ] && [ "${n}" -le 20 ] || die "step numbers are 1..20 (got '${n}')"
done
case "${SIG}" in pending|ok) ;; *) die "--sig is pending or ok" ;; esac
RANGE=(--from "${FROM}" --to "${TO}")
if [ -n "${ONLY}" ]; then FROM="${ONLY}"; TO="${ONLY}"; RANGE=(--only "${ONLY}"); fi

PY="$(command -v python3)" || die "python3 not found"
command -v rsync >/dev/null || die "rsync not found"
command -v gpg >/dev/null || die "gpg not found"
[ -f "${WT}/common/reserve-static-ips.sh" ] || die "${WT}/common is not checked out"
[ -f "${TND_DIR}/setup-node.sh" ] || die "no tn-node-deployment checkout at ${TND_DIR} (set L2_SHIM_TND)"
REF="$(git -C "${TND_DIR}" rev-parse HEAD)"

if [ -z "${STATE_DIR}" ]; then
    STATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/l2-shim.XXXXXX")"
else
    KEEP=1
    mkdir -p "${STATE_DIR}"
fi
STATE="$(cd "${STATE_DIR}" && pwd)"
FRESH=1; [ -f "${STATE}/cloud.json" ] && FRESH=0
[ "${FROM}" -gt 1 ] && [ "${FRESH}" = 1 ] && echo "run.sh: note: --from ${FROM} on a fresh state: nothing from steps 1..$((FROM - 1)) exists" >&2

# Logs of an earlier run in this state move aside, so this report is about this run only.
if [ -f "${STATE}/calls.log" ]; then
    prev="${STATE}/previous-runs/$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "${prev}"
    for f in calls.log findings.log sentinel.log remote-detail.log deploy-output.log; do
        [ -f "${STATE}/${f}" ] && mv "${STATE}/${f}" "${prev}/"
    done
fi

# 1. A snapshot of the worktree: every driver runs from it, so logs/, genesis/ and releases/ are
#    written there and never into the worktree. No .git, no tasks/, no .secrets/, no submodule
#    tn-node-deployment/ (the hosts get fakes of the scripts instead), no benchmark/.
excl=(--exclude=/.git --exclude=/.claude/ --exclude=/tasks/ --exclude=/tn-node-deployment/
      --exclude=/logs/ --exclude=/.secrets/ --exclude=/benchmark/)
if [ "${FRESH}" = 1 ]; then
    rsync -a "${excl[@]}" "${WT}/" "${STATE}/repo/"
else
    rsync -a "${excl[@]}" --exclude=/genesis/ --exclude=/releases/ "${WT}/" "${STATE}/repo/"
fi
# A driver committed without its exec bit stops devnet-deploy.sh with exit 126. That is a FINDING, never
# repaired silently: L2_SHIM_CHMOD_DRIVERS=1 sets +x on the snapshot copy only (to rehearse past it) and the
# report keeps one FLAGCHECK-free "MODE" finding per file, so the run is NOT CLEAN either way.
for f in "${STATE}"/repo/devnet-*.sh; do
    [ -x "${f}" ] && continue
    printf 'MODE\tstep=-\t-\t%s is not executable (git mode 100644) but devnet-deploy.sh runs it directly\t-\tfatal\n' \
        "$(basename "${f}")" >> "${STATE}/findings.log"
    if [ "${L2_SHIM_CHMOD_DRIVERS:-0}" = 1 ]; then chmod +x "${f}"; fi
done

# 2. The flag table, from the real argument parsers of the tn-node-deployment branch.
"${PY}" "${SHIM_DIR}/fakes.py" gen-flags "${TND_DIR}" > "${STATE}/flags.json"

# 3. CONFIG_FILE wrapper: config.sh as committed, plus the one placeholder and the keyring.
mkdir -p "${STATE}/release-keys" "${STATE}/fake-secrets" "${STATE}/poison/gcloud-config" "${STATE}/poison/docker"
cat > "${STATE}/config-shim.sh" <<EOF
# l2-shim CONFIG_FILE wrapper (generated): the snapshot's config.sh, then the rehearsal's values.
# shellcheck disable=SC1091
source "${STATE}/repo/config.sh"
export TN_NODE_SCRIPTS_REF="${REF}"
export RELEASE_KEYS_DIR="${STATE}/release-keys"
EOF
RELEASE_TAG_V="$(bash -c 'source "$1" >/dev/null 2>&1; printf %s "${RELEASE_TAG:-}"' _ "${STATE}/config-shim.sh")"

# 4. The fake cloud as the teardown left it: none of the seven fleet VMs, the five old nodes'
#    static IPs reserved, the obs VM kept (the teardown never deletes it), no legacy load
#    balancer; fake secrets; a fake BLS passphrase; a throwaway release key.
if [ "${FRESH}" = 1 ]; then
    export L2_SHIM_STATE="${STATE}" L2_SHIM_ORIG_PATH="${PATH}"
    {
        bash -c 'set -e; source "$1" >/dev/null
                 for i in "${!INSTANCE_NAMES[@]}"; do
                     r=0; [ "${i}" -le 4 ] && r=1
                     printf "%s %s %s %s\n" "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "${STATIC_IP_NAMES[$i]}" "${r}"
                 done
                 printf "vm %s %s %s %s\n" "${OBS_INSTANCE_NAME}" "${OBS_ZONE}" "${OBS_STATIC_IP_NAME}" "${OBS_DATA_MOUNT:-/mnt/obs-data}"
                 printf "disk %s %s %s %s\n" "${OBS_DATA_DISK_NAME:-${OBS_INSTANCE_NAME}-data}" "${OBS_ZONE}" \
                     "${OBS_DATA_DISK_SIZE_GB:-300}" "${OBS_INSTANCE_NAME}"' _ "${STATE}/config-shim.sh"
        for s in obs-ingest-token obs-grafana-admin devnet-admin-dashboard-password devnet-admin-dashboard-hash \
                 devnet-contracts-admin-pk devnet-txgen-age-key; do
            printf 'secret %s\n' "${s}"
        done
    } | "${PY}" "${SHIM_DIR}/fakes.py" init
    printf 'l2-shim-fake-bls-passphrase\n' > "${STATE}/fake-secrets/bls-passphrase"
    chmod 600 "${STATE}/fake-secrets/bls-passphrase"
    mkdir -p "${STATE}/gnupg" && chmod 700 "${STATE}/gnupg"
    gpg --homedir "${STATE}/gnupg" --batch --quiet --passphrase '' \
        --quick-gen-key 'l2-shim throwaway release key <l2-shim@example.invalid>' ed25519 sign 2d
    gpg --homedir "${STATE}/gnupg" --batch --armor --export > "${STATE}/release-keys/l2-shim-throwaway.asc"
fi

# 5. The environment of the rehearsal. The fakes are FIRST on PATH; the sentinel directory comes
#    right after and refuses network tools that have no fake. Real binaries reached anyway (an
#    absolute path) find a poisoned environment: an empty gcloud config (no account), no docker
#    socket, a dead proxy for curl/cast.
export L2_SHIM_STATE="${STATE}" L2_SHIM_DIR="${SHIM_DIR}" L2_SHIM_PY="${PY}" L2_SHIM_SIG="${SIG}"
L2_SHIM_REAL_CAST="$(command -v cast || true)"
export L2_SHIM_REAL_CAST L2_SHIM_ORIG_PATH="${PATH}"
export L2_SHIM_RELEASE_DIR="${STATE}/repo/releases/${RELEASE_TAG_V}"
export CONFIG_FILE="${STATE}/config-shim.sh"
export TN_BLS_PASSPHRASE_FILE="${STATE}/fake-secrets/bls-passphrase"
unset TN_BLS_PASSPHRASE TN_SKIP_RELEASE_SIG TN_SSH_TRANSPORT
export CLOUDSDK_CONFIG="${STATE}/poison/gcloud-config" DOCKER_HOST="unix://${STATE}/poison/no-docker.sock"
export DOCKER_CONFIG="${STATE}/poison/docker" ETH_RPC_URL="http://127.0.0.1:9"
export HTTP_PROXY="http://127.0.0.1:9" HTTPS_PROXY="http://127.0.0.1:9" ALL_PROXY="http://127.0.0.1:9"
export http_proxy="${HTTP_PROXY}" https_proxy="${HTTPS_PROXY}" all_proxy="${ALL_PROXY}" NO_PROXY="" no_proxy=""
export PATH="${SHIM_DIR}/bin:${SHIM_DIR}/sentinel:${PATH}"

# Blind spots of the PATH method, listed (not fatal): absolute paths or a reset PATH in a driver.
blind="$(cd "${STATE}/repo" && grep -nE '(^|[^[:alnum:]_.])/(usr/)?s?bin/(gcloud|ssh|scp|docker|curl|cast|forge|dig)([^[:alnum:]_-]|$)|command -p |env -i |(^|[[:space:];])PATH=' \
            ./*.sh 2>/dev/null | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' || true)"
[ -n "${blind}" ] && printf 'run.sh: PATH blind spots (a call here would bypass the fakes):\n%s\n' "${blind}" >&2

echo "run.sh: state ${STATE} (fresh=${FRESH}); steps ${FROM}..${TO}; --sig ${SIG}; scripts ref ${REF}"
echo "pre" > "${STATE}/current_step"
export L2_SHIM_FROM="${FROM}"
rc=0
( cd "${STATE}/repo" && "${PY}" "${SHIM_DIR}/fakes.py" pty-run "${STATE}/deploy-output.log" -- \
      ./devnet-deploy.sh --yes "${RANGE[@]}" ) || rc=$?
res=0
"${PY}" "${SHIM_DIR}/fakes.py" report --rc "${rc}" --from "${FROM}" --to "${TO}" --sig "${SIG}" || res=$?
gpgconf --homedir "${STATE}/gnupg" --kill all >/dev/null 2>&1 || true
if [ "${KEEP}" = 1 ]; then
    echo "run.sh: state kept: ${STATE}  (resume: tasks/l2-shim/run.sh --state ${STATE} --from <N>)"
else
    rm -rf "${STATE}"
fi
exit "${res}"
