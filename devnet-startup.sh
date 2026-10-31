#!/bin/bash
#
# devnet-startup.sh — GCP metadata `startup-script` for every devnet node.
#
# Runs ON each freshly-created Ubuntu 24.04 (noble) node at first boot, as ROOT,
# with NO repo checkout present. It is therefore SELF-CONTAINED: it does NOT
# source devnet-lib.sh / config.sh (those live in the operator's repo, not on the
# node). create-instances.sh wires this file in via
#   --metadata-from-file=startup-script=${REPO_ROOT}/devnet-startup.sh
# delivers the wireguard bootstrap via
#   --metadata-from-file=...,wg-node-bootstrap=common/wgvpn/node/wg-node-bootstrap.sh
# and pins the tn-node-deployment scripts via the instance metadata attribute
#   tn-scripts-ref=${TN_NODE_SCRIPTS_REF}
#
# Responsibilities (all idempotent — startup-scripts can re-run on reboot):
#   1. install docker-ce + git + jq from download.docker.com (noble apt repo)
#   2. install the Google Cloud Ops Agent (purge any legacy Stackdriver agent first)
#   3. fetch the tn-node-deployment (v2) scripts at the pinned ref `tn-scripts-ref`
#      into /opt/telcoin-node-scripts, ROOT-owned. (It used to clone the default
#      branch into /home/telcoin/telcoin-node-scripts and chown it to telcoin.) A
#      missing ref, an abbreviated sha or a failed fetch exits 1.
#   4. record this node's external/internal IP + consensus/health ports to
#      /etc/telcoin/devnet-ips.env
#   5. bring up the wireguard OVERLAY ONLY (WG_NODE_FIREWALL=0 — no policy-drop
#      nft table; UFW stays the single host firewall)
#
# It deliberately does NOT create the `telcoin` service account: v2's setup-node.sh
# creates it as a SYSTEM account (UID 1-999, no login shell) and refuses one that is
# not, or that is in the docker/sudo/adm/wheel group (lib/common.sh
# tn_service_user_ok). An existing account v2 would refuse only draws a WARNING here.
# Nor does it run keygen — that is SSH-orchestrated by devnet-keygen.sh so the
# operator owns the BLS passphrase and timing.
#
# All progress is logged to stdout; GCP captures it in the serial console
# (gcloud compute instances get-serial-port-output <inst>). devnet-deploy.sh waits
# for the final "devnet-startup.sh complete" line; every fatal path exits before it.

set -euo pipefail

log() { echo ">>> [devnet-startup] $*"; }
# die: log a FATAL line and exit 1 — before the completion marker, so devnet-deploy.sh stops.
die() { log "FATAL: $*"; exit 1; }

SERVICE_USER="telcoin"
# v2 runs its scripts from this checkout. It stays ROOT-owned and is never chowned to
# the service user: ui/install-ui.sh refuses a checkout owned or writable by telcoin.
TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"
# ASSUMPTION: tn-node-deployment is a PUBLIC GitHub repo, so an unauthenticated
# https clone works on a bare node with no deploy key. If it is private, bake a
# read-only deploy key / token into metadata and adjust TN_NODE_DEPLOY_REPO.
TN_NODE_DEPLOY_REPO="https://github.com/Telcoin-Association/tn-node-deployment.git"

PRIMARY_UDP_PORT="49590"
WORKER_UDP_PORT="49594"
HEALTHCHECK_TCP_PORT="43174"

METADATA_BASE="http://metadata.google.internal/computeMetadata/v1"
md() { curl -sf -H "Metadata-Flavor: Google" "${METADATA_BASE}/$1" 2>/dev/null || true; }

# ----------------------------------------------------------------------------
# Step 1: docker-ce + git + jq (Ubuntu 24.04 noble). Idempotent: skip if docker
# is already present from a prior boot.
# ----------------------------------------------------------------------------
log "step 1/5: installing docker-ce + git + jq"
if command -v docker >/dev/null 2>&1; then
    log "docker already installed — skipping apt setup"
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg git jq

    # Docker's official apt repo + keyring (mirrors the standard docker install).
    install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
    fi
    # Pin the noble codename explicitly (config.sh's IMAGE is ubuntu-2404-lts).
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin git jq
    systemctl enable --now docker || true
    log "docker-ce installed"
fi

# ----------------------------------------------------------------------------
# Step 2: Google Cloud Ops Agent. Purge any legacy Stackdriver agent, then install the
# new Ops Agent so this node ships host metrics (agent.googleapis.com/*) and the GCP
# console never nags to "upgrade". Runs after Step 1 so curl is present. Non-fatal: the
# `|| log` suppresses set -e on any internal failure (mirrors the wg-bootstrap pattern
# below) — monitoring must NEVER take a node down.
#
# install_ops_agent is a MIRROR of common/ops-agent-install.sh — keep the two in sync. A
# startup-script runs before any repo exists on the node, so it cannot source that file.
# ----------------------------------------------------------------------------
log "step 2/5: installing Google Cloud Ops Agent (purge legacy first)"
# ----- mirror of common/ops-agent-install.sh:install_ops_agent — keep in sync -----
install_ops_agent() {
    local SUDO="" pkg tmp
    [ "$(id -u)" -ne 0 ] && SUDO=sudo

    # 1. Purge any legacy Monitoring/Logging agent — THIS is what clears the GCP console's
    #    "upgrade to the Ops Agent" banner (the Ops Agent installer leaves it in place).
    for pkg in stackdriver-agent google-fluentd; do
        if dpkg -s "${pkg}" >/dev/null 2>&1; then
            echo "[ops-agent] removing legacy ${pkg}"
            # shellcheck disable=SC2086  # $SUDO is intentionally empty when already root
            $SUDO apt-get remove -y "${pkg}" || true
        fi
    done

    # 2. Install the Ops Agent unless it is already present (idempotent re-runs). Download
    #    into a throwaway temp dir so we never clobber the caller's CWD or files.
    if dpkg -s google-cloud-ops-agent >/dev/null 2>&1; then
        echo "[ops-agent] google-cloud-ops-agent already installed"
    else
        echo "[ops-agent] installing google-cloud-ops-agent"
        tmp="$(mktemp -d 2>/dev/null)" || return 0
        if curl -fsSL -o "${tmp}/add-ops-agent-repo.sh" \
                https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh; then
            # shellcheck disable=SC2086  # $SUDO is intentionally empty when already root
            $SUDO bash "${tmp}/add-ops-agent-repo.sh" --also-install || true
        else
            echo "[ops-agent] WARNING: installer download failed (skipping; non-fatal)"
        fi
        rm -rf "${tmp}" || true
    fi

    # 3. Report status (diagnostic only — never fail on it).
    # shellcheck disable=SC2086  # $SUDO is intentionally empty when already root
    if $SUDO systemctl is-active --quiet google-cloud-ops-agent 2>/dev/null; then
        echo "[ops-agent] google-cloud-ops-agent active"
    else
        echo "[ops-agent] google-cloud-ops-agent not active yet (may still be starting)"
    fi
    return 0
}
# ----- end mirror -----
install_ops_agent || log "ops-agent install failed (non-fatal)"

# ----------------------------------------------------------------------------
# Service-account check (diagnostic only — no account is created here). v2's
# setup-node.sh creates `telcoin` itself as a system account and refuses an
# existing one with a UID outside 1-999 or in docker/sudo/adm/wheel (lib/common.sh
# tn_service_user_ok; its UID-1101 legacy exception is not mirrored, devnet never
# made that account). A fresh VM has no such account, so this never fires there.
# ----------------------------------------------------------------------------
log "check: '${SERVICE_USER}' account (tn-node-deployment setup-node.sh creates it later)"
if SVC_UID="$(id -u "${SERVICE_USER}" 2>/dev/null)"; then
    SVC_PROBLEMS=""
    if [ "${SVC_UID}" -ge 1000 ]; then
        SVC_PROBLEMS="UID ${SVC_UID} is not a system account (v2 needs 1-999)"
    fi
    for g in $(id -nG "${SERVICE_USER}" 2>/dev/null); do
        case "${g}" in
            docker|sudo|adm|wheel) SVC_PROBLEMS="${SVC_PROBLEMS:+${SVC_PROBLEMS}; }member of the ${g} group" ;;
        esac
    done
    if [ -n "${SVC_PROBLEMS}" ]; then
        log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        log "WARNING: '${SERVICE_USER}' already exists and v2 setup-node.sh will REFUSE it: ${SVC_PROBLEMS}"
        log "WARNING: recreate the VM (or userdel ${SERVICE_USER}) before keygen/finalize"
        log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    else
        log "'${SERVICE_USER}' exists as a system account (UID ${SVC_UID}) outside the admin groups"
    fi
else
    log "no '${SERVICE_USER}' account yet (expected on a fresh VM)"
fi

# ----------------------------------------------------------------------------
# Step 3: tn-node-deployment scripts at the PINNED ref, in a ROOT-owned checkout.
# The ref is the instance metadata attribute tn-scripts-ref (create-instances.sh
# sets it from TN_NODE_SCRIPTS_REF): a full 40-hex commit sha (preferred: a reboot
# re-fetches the same tree) or a branch name (a reboot moves to the branch tip).
# `git clone --branch` rejects a sha and a remote serves a commit only by its full
# sha (an abbreviated one fails "couldn't find remote ref"), so: init once, fetch
# the one commit, check it out detached (first boot only; a reboot keeps the
# checkout as it is). The checkout stays root's and is never
# chowned to the service user — v2's ui/install-ui.sh refuses a checkout the node
# account owns or can write. v2 runs from the checkout; there is no install.sh
# step (it needs a signed release). Every failure here exits 1, so the completion
# marker is never printed and devnet-deploy.sh stops at this node.
# ----------------------------------------------------------------------------
log "step 3/5: fetching tn-node-deployment scripts into ${TN_NODE_SCRIPTS_DIR} (root-owned)"
TN_SCRIPTS_REF="$(md instance/attributes/tn-scripts-ref)"
[ -n "${TN_SCRIPTS_REF}" ] \
    || die "instance metadata attribute tn-scripts-ref is empty; a node without a pinned scripts ref must not come up (set TN_NODE_SCRIPTS_REF and recreate the instance)"
TN_SCRIPTS_REF_IS_SHA=0
if [[ "${TN_SCRIPTS_REF}" =~ ^[0-9a-f]{40}$ ]]; then
    TN_SCRIPTS_REF_IS_SHA=1
elif [[ "${TN_SCRIPTS_REF}" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
    die "tn-scripts-ref '${TN_SCRIPTS_REF}' looks like an abbreviated or upper-case sha; the remote serves a commit only by its full lower-case 40-hex sha (or use a branch name)"
elif [[ ! "${TN_SCRIPTS_REF}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]; then
    die "tn-scripts-ref '${TN_SCRIPTS_REF}' is neither a 40-hex sha nor a plain branch name"
fi
umask 022   # no group/world-writable files: install-ui.sh refuses them
if [ -d "${TN_NODE_SCRIPTS_DIR}/.git" ]; then
    # Reboot: keep the checkout as it is. The fleet moves nodes to a newer ref with
    # devnet-lib.sh's tn_cmd_refresh_scripts, and re-fetching the (older) metadata ref here
    # would silently revert that; a transient fetch failure must not stop the WireGuard
    # overlay step below either (R6 review). First boot still fails loud on a bad ref.
    TN_SCRIPTS_HEAD="$(git -C "${TN_NODE_SCRIPTS_DIR}" rev-parse HEAD 2>/dev/null || echo '?')"
    log "existing checkout at ${TN_SCRIPTS_HEAD} — leaving it alone (metadata ref ${TN_SCRIPTS_REF})"
else
    log "new checkout of ${TN_NODE_DEPLOY_REPO} at ${TN_SCRIPTS_REF}"
    git init -q "${TN_NODE_SCRIPTS_DIR}" || die "git init ${TN_NODE_SCRIPTS_DIR} failed"
    git -C "${TN_NODE_SCRIPTS_DIR}" remote add origin "${TN_NODE_DEPLOY_REPO}" \
        || die "git remote add origin ${TN_NODE_DEPLOY_REPO} failed"
    git -C "${TN_NODE_SCRIPTS_DIR}" fetch --depth=1 origin "${TN_SCRIPTS_REF}" \
        || die "could not fetch tn-scripts-ref '${TN_SCRIPTS_REF}' from ${TN_NODE_DEPLOY_REPO}"
    git -C "${TN_NODE_SCRIPTS_DIR}" checkout -q --detach FETCH_HEAD \
        || die "could not check out tn-scripts-ref '${TN_SCRIPTS_REF}' in ${TN_NODE_SCRIPTS_DIR}"
    TN_SCRIPTS_HEAD="$(git -C "${TN_NODE_SCRIPTS_DIR}" rev-parse HEAD)" \
        || die "git rev-parse HEAD failed in ${TN_NODE_SCRIPTS_DIR}"
    log "tn-node-deployment scripts at ${TN_SCRIPTS_HEAD} (tn-scripts-ref ${TN_SCRIPTS_REF})"
    if [ "${TN_SCRIPTS_REF_IS_SHA}" -eq 1 ]; then
        case "${TN_SCRIPTS_HEAD}" in
            "${TN_SCRIPTS_REF}"*) ;;
            *) die "checked-out HEAD ${TN_SCRIPTS_HEAD} is not tn-scripts-ref ${TN_SCRIPTS_REF}" ;;
        esac
    fi
fi

# ----------------------------------------------------------------------------
# Step 4: record this node's IPs + consensus/health ports for later tooling.
# Read external/internal IP from the GCP metadata server. Mode 644.
# ----------------------------------------------------------------------------
log "step 4/5: writing /etc/telcoin/devnet-ips.env"
EXTERNAL_IP="$(md instance/network-interfaces/0/access-configs/0/external-ip)"
INTERNAL_IP="$(md instance/network-interfaces/0/ip)"
mkdir -p /etc/telcoin
umask 022
cat > /etc/telcoin/devnet-ips.env <<EOF
# Written by devnet-startup.sh at first boot. Consumed by node tooling.
EXTERNAL_IP=${EXTERNAL_IP}
INTERNAL_IP=${INTERNAL_IP}
PRIMARY_UDP_PORT=${PRIMARY_UDP_PORT}
WORKER_UDP_PORT=${WORKER_UDP_PORT}
HEALTHCHECK_TCP_PORT=${HEALTHCHECK_TCP_PORT}
EOF
chmod 644 /etc/telcoin/devnet-ips.env
log "recorded EXTERNAL_IP=${EXTERNAL_IP:-<unset>} INTERNAL_IP=${INTERNAL_IP:-<unset>}"

# ----------------------------------------------------------------------------
# Step 5: wireguard OVERLAY ONLY. Fetch the bootstrap from metadata and run it
# with WG_NODE_FIREWALL=0 (NOT injected by create-instances.sh, so set here) so
# it lays the overlay WITHOUT a policy-drop nft table — UFW stays authoritative.
# The bootstrap self-fetches every other WG_* value from metadata. Non-fatal: a
# wg failure must NOT take the node down (IAP SSH still works regardless).
# ----------------------------------------------------------------------------
log "step 5/5: bringing up wireguard overlay (WG_NODE_FIREWALL=0)"
WG_BOOTSTRAP=$(curl -sf -H "Metadata-Flavor: Google" "${METADATA_BASE}/instance/attributes/wg-node-bootstrap" 2>/dev/null || true)
if [ -n "${WG_BOOTSTRAP}" ]; then
    printf '%s' "${WG_BOOTSTRAP}" | WG_NODE_FIREWALL=0 bash -s || echo "wg bootstrap failed (node still up)"
else
    log "no wg-node-bootstrap in metadata — skipping overlay (hub not deployed?)"
fi

log "devnet-startup.sh complete — node ready for SSH-orchestrated keygen/finalize"
