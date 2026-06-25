#!/bin/bash
#
# devnet-dashboards.sh — install / refresh the per-node Telcoin Node Manager UI
# (the Flask "admin dashboard", systemd telcoin-ui, binds 127.0.0.1:8080) across
# the fleet, by shipping THIS repo's PINNED tn-node-deployment/ui/ to each node and
# running its idempotent install-ui.sh --update.
#
# Why ship the pinned ui/ rather than use the node's own clone: the node clones
# tn-node-deployment's default branch at first boot, which may predate the
# server-side read-only guard (X-TN-Dashboard-Public => 403 on writes). Shipping
# the submodule-pinned ui/ guarantees the verified guard is what runs under the
# public Caddy vhost.
#
# UI-ONLY. This script does NOT touch Caddy — the admin vhost is emitted solely by
# common/config-caddy.sh (applied fleet-wide by common/dns.sh), keeping a single
# Caddyfile writer. Run this FIRST (backend live on :8080), THEN dns.sh so the
# vhost points at a service that already answers. No secret travels here — the
# basic_auth bcrypt hash lives only in the Caddy vhost, never in the UI install.
#
# Reaches nodes via the lib's transport helpers (IAP by default, or the WireGuard
# overlay when TN_SSH_TRANSPORT=overlay). The observer (node5) is treated identically
# — the UI is node-type-agnostic. Pass an optional subset of instance names to target
# just those nodes; with no args it sweeps the whole fleet. One node's failure is
# recorded and the sweep continues; the script exits non-zero if any node failed.
#
# Usage:
#   ./devnet-dashboards.sh                       # all nodes
#   ./devnet-dashboards.sh validator-1-devnet    # one (or more) by name

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${REPO_DIR}/devnet-lib.sh"

UI_SRC_DIR="${REPO_DIR}/tn-node-deployment/ui"   # this repo's pinned ui/ (submodule)
REMOTE_TARBALL="/tmp/tn-ui.tar.gz"               # staging path on each node

# --- optional instance subset (positional args) --------------------------------
# Validate any names up front so a typo fails before we touch a single node.
SELECTED=("$@")
if [ "${#SELECTED[@]}" -gt 0 ]; then
    for want in "${SELECTED[@]}"; do
        found=0
        for have in "${INSTANCE_NAMES[@]}"; do
            [ "${want}" = "${have}" ] && { found=1; break; }
        done
        [ "${found}" -eq 1 ] || { echo "❌ unknown instance '${want}' (not in INSTANCE_NAMES)" >&2; exit 1; }
    done
fi

# tn_dash_selected <instance> — true if this instance is in the subset (or no subset given).
tn_dash_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local inst="$1" s
    for s in "${SELECTED[@]}"; do [ "${s}" = "${inst}" ] && return 0; done
    return 1
}

# --- preflight: the pinned UI source must be present (else the submodule is uninit) ----
[ -d "${UI_SRC_DIR}" ]               || { echo "❌ UI source dir not found: ${UI_SRC_DIR} (is the tn-node-deployment submodule checked out?)" >&2; exit 1; }
[ -f "${UI_SRC_DIR}/install-ui.sh" ] || { echo "❌ install-ui.sh not found in ${UI_SRC_DIR}" >&2; exit 1; }
[ -f "${UI_SRC_DIR}/server.py" ]     || { echo "❌ server.py not found in ${UI_SRC_DIR}" >&2; exit 1; }

echo "=========================================="
echo "devnet admin-dashboard (Node Manager UI) rollout"
echo "Project:   ${PROJECT_ID}"
echo "UI source: ${UI_SRC_DIR}"
echo "Target:    ${TN_NODE_SCRIPTS_DIR}/ui  ->  install-ui.sh --update  (telcoin-ui on 127.0.0.1:8080)"
echo "Transport: ${TN_SSH_TRANSPORT}"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:    ${SELECTED[*]}"
echo "=========================================="

# --- pack the UI bundle ONCE -------------------------------------------------
# tar the CONTENTS of ui/ (note the trailing '.'), so extraction into
# ${TN_NODE_SCRIPTS_DIR}/ui lands server.py/install-ui.sh/static/ directly there
# (no nested ui/ui/). Explicit-template mktemp is portable across GNU + BSD.
TARBALL="$(mktemp "${TMPDIR:-/tmp}/tn-ui.XXXXXX")"
trap 'rm -f "${TARBALL}"' EXIT
tar -czf "${TARBALL}" -C "${UI_SRC_DIR}" .
echo ">>> packed UI bundle ($(wc -c < "${TARBALL}" | tr -d ' ') bytes) from ${UI_SRC_DIR}"

# Per-node remote command (root): extract our pinned ui/ over the node's checkout,
# chown to the service user, run the idempotent non-interactive installer (which
# restarts telcoin-ui to load the new code), then enable-on-boot (--update mode does
# not, so we do it explicitly). Trailing UI_REFRESH_OK is the success sentinel.
remote_cmd="set -e; \
sudo mkdir -p '${TN_NODE_SCRIPTS_DIR}/ui'; \
sudo tar -C '${TN_NODE_SCRIPTS_DIR}/ui' -xzf '${REMOTE_TARBALL}'; \
sudo chown -R '${SERVICE_USER}:${SERVICE_USER}' '${TN_NODE_SCRIPTS_DIR}/ui'; \
sudo bash '${TN_NODE_SCRIPTS_DIR}/ui/install-ui.sh' --update; \
sudo systemctl enable telcoin-ui >/dev/null 2>&1 || true; \
rm -f '${REMOTE_TARBALL}'; echo UI_REFRESH_OK"

rc=0
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"

    tn_dash_selected "${inst}" || continue

    echo ""
    echo ">>> ${inst} (${zone}): shipping pinned ui/ + install-ui.sh --update"

    # (1) copy the bundle to the node's /tmp
    if ! tn_iap_scp "${TARBALL}" "${inst}" "${zone}" "${REMOTE_TARBALL}"; then
        echo "    ❌ scp UI bundle to ${inst} failed" >&2
        rc=1
        continue
    fi

    # (2) extract + install + restart + enable (one root round-trip). Capture output so a
    # failing node prints its installer log; rc + the UI_REFRESH_OK sentinel gate success.
    if out="$(tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}" 2>&1)"; then
        echo "${out}" | sed 's/^/    /'
        if printf '%s' "${out}" | grep -q 'UI_REFRESH_OK'; then
            echo "    ✅ ${inst}: telcoin-ui installed/refreshed + enabled"
        else
            echo "    ⚠️  ${inst}: installer exited 0 but UI_REFRESH_OK missing — verify telcoin-ui by hand" >&2
            rc=1
        fi
    else
        echo "${out}" | sed 's/^/    /'
        echo "    ❌ install-ui.sh failed on ${inst}" >&2
        rc=1
    fi
done

echo ""
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "admin-dashboard rollout complete on all targeted nodes."
    echo "telcoin-ui now listens on 127.0.0.1:8080 per node. Expose it read-only at"
    echo "admin.<node>.${BASE_DOMAIN} by running ./common/dns.sh (admin vhost is default-on;"
    echo "dns.sh fetches the basic_auth hash from Secret Manager automatically). Full controls"
    echo "are over the SSH tunnel (tn-node-deployment/open-ui.sh)."
    echo "=========================================="
else
    echo "=========================================="
    echo "admin-dashboard rollout finished WITH ERRORS — see the ❌ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
