#!/bin/bash
#
# devnet-startup.sh — GCP metadata `startup-script` for every devnet node.
#
# Runs ON each freshly-created Ubuntu 24.04 (noble) node at first boot, as ROOT,
# with NO repo checkout present. It is therefore SELF-CONTAINED: it does NOT
# source devnet-lib.sh / config.sh (those live in the operator's repo, not on the
# node). create-instances.sh wires this file in via
#   --metadata-from-file=startup-script=${REPO_ROOT}/devnet-startup.sh
# and delivers the wireguard bootstrap via
#   --metadata-from-file=...,wg-node-bootstrap=common/wgvpn/node/wg-node-bootstrap.sh
#
# Responsibilities (all idempotent — startup-scripts can re-run on reboot):
#   1. install docker-ce + git + jq from download.docker.com (noble apt repo)
#   2. install the Google Cloud Ops Agent (purge any legacy Stackdriver agent first)
#   3. create the `telcoin` service user (+ docker group)
#   4. clone the tn-node-deployment scripts to /home/telcoin/telcoin-node-scripts
#   5. record this node's external/internal IP + consensus/health ports to
#      /etc/telcoin/devnet-ips.env
#   6. bring up the wireguard OVERLAY ONLY (WG_NODE_FIREWALL=0 — no policy-drop
#      nft table; UFW stays the single host firewall)
#
# It deliberately does NOT run keygen — that is SSH-orchestrated by
# devnet-keygen.sh so the operator owns the BLS passphrase and timing.
#
# All progress is logged to stdout; GCP captures it in the serial console
# (gcloud compute instances get-serial-port-output <inst>).

set -euo pipefail

log() { echo ">>> [devnet-startup] $*"; }

SERVICE_USER="telcoin"
TN_NODE_SCRIPTS_DIR="/home/${SERVICE_USER}/telcoin-node-scripts"
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
log "step 1/6: installing docker-ce + git + jq"
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
log "step 2/6: installing Google Cloud Ops Agent (purge legacy first)"
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
# Step 3: telcoin service user (+ docker group). Idempotent.
# ----------------------------------------------------------------------------
log "step 3/6: ensuring '${SERVICE_USER}' service user"
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "${SERVICE_USER}"
    log "created user ${SERVICE_USER}"
else
    log "user ${SERVICE_USER} already exists"
fi
# Add to docker group so the install-method=docker node can drive the daemon.
if getent group docker >/dev/null 2>&1; then
    usermod -aG docker "${SERVICE_USER}" || true
fi

# ----------------------------------------------------------------------------
# Step 4: clone tn-node-deployment scripts (non-interactive). Idempotent: if the
# dir exists, fast-forward it instead of re-cloning. Default path is the public
# https clone; an install.sh in the repo (if present) is run with --yes.
# ----------------------------------------------------------------------------
log "step 4/6: installing tn-node-deployment scripts to ${TN_NODE_SCRIPTS_DIR}"
if [ -d "${TN_NODE_SCRIPTS_DIR}/.git" ]; then
    log "scripts dir already a git checkout — pulling latest"
    git -C "${TN_NODE_SCRIPTS_DIR}" pull --ff-only || log "git pull failed (keeping existing checkout)"
elif [ -d "${TN_NODE_SCRIPTS_DIR}" ] && [ -n "$(ls -A "${TN_NODE_SCRIPTS_DIR}" 2>/dev/null)" ]; then
    log "scripts dir present and non-empty (non-git) — leaving as-is"
else
    rm -rf "${TN_NODE_SCRIPTS_DIR}"
    git clone --depth=1 "${TN_NODE_DEPLOY_REPO}" "${TN_NODE_SCRIPTS_DIR}"
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TN_NODE_SCRIPTS_DIR}" || true
# If the repo ships a non-interactive installer, run it. Best-effort; the raw
# setup-*.sh scripts are usable from the checkout regardless.
if [ -x "${TN_NODE_SCRIPTS_DIR}/install.sh" ]; then
    log "running tn-node-deployment install.sh --yes"
    "${TN_NODE_SCRIPTS_DIR}/install.sh" --yes || log "install.sh returned nonzero (checkout still usable)"
fi

# ----------------------------------------------------------------------------
# Step 5: record this node's IPs + consensus/health ports for later tooling.
# Read external/internal IP from the GCP metadata server. Mode 644.
# ----------------------------------------------------------------------------
log "step 5/6: writing /etc/telcoin/devnet-ips.env"
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
# Step 6: wireguard OVERLAY ONLY. Fetch the bootstrap from metadata and run it
# with WG_NODE_FIREWALL=0 (NOT injected by create-instances.sh, so set here) so
# it lays the overlay WITHOUT a policy-drop nft table — UFW stays authoritative.
# The bootstrap self-fetches every other WG_* value from metadata. Non-fatal: a
# wg failure must NOT take the node down (IAP SSH still works regardless).
# ----------------------------------------------------------------------------
log "step 6/6: bringing up wireguard overlay (WG_NODE_FIREWALL=0)"
WG_BOOTSTRAP=$(curl -sf -H "Metadata-Flavor: Google" "${METADATA_BASE}/instance/attributes/wg-node-bootstrap" 2>/dev/null || true)
if [ -n "${WG_BOOTSTRAP}" ]; then
    printf '%s' "${WG_BOOTSTRAP}" | WG_NODE_FIREWALL=0 bash -s || echo "wg bootstrap failed (node still up)"
else
    log "no wg-node-bootstrap in metadata — skipping overlay (hub not deployed?)"
fi

log "devnet-startup.sh complete — node ready for SSH-orchestrated keygen/finalize"
