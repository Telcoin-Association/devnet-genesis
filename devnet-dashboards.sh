#!/bin/bash
#
# devnet-dashboards.sh — install / refresh the per-node Telcoin Node Manager UI
# (the Flask "admin dashboard", systemd unit telcoin-ui, bound to 127.0.0.1:8080)
# across the fleet by running each node's OWN ui/install-ui.sh from the root-owned
# tn-node-deployment checkout at ${TN_NODE_SCRIPTS_DIR} (config.sh).
#
# Nothing is shipped from the operator's machine: that checkout is the pinned v2
# tree, and v2's install-ui.sh refuses a tree an administrator did not lay down —
# any symlink, any file owned by telcoin / telcoin-ui / tn-build / telcoin-alloy,
# or writable by others or a non-admin group, within 3 levels of the checkout root.
# So this script never writes, extracts over or chowns the checkout.
#
# Per node, one root round-trip over tn_iap_ssh:
#   - telcoin-ui.service already a unit file -> install-ui.sh --update. It restarts
#     the UI on the new code but leaves enable-on-boot as it was, so we enable it.
#   - otherwise -> install-ui.sh (first install). With no tty on stdin (</dev/null)
#     it starts AND enables the unit itself.
#   Then assert telcoin-ui is enabled, GET / on 127.0.0.1:8080 answers 200 (the
#   page needs no token; /api/* does) and the unit is active. install-ui.sh exits
#   0 even when the start fails, so its exit code alone proves nothing.
#
# UI-ONLY. This script does NOT touch Caddy — the admin vhost is emitted solely by
# common/config-caddy.sh (applied fleet-wide by common/dns.sh), which stamps
# X-TN-Dashboard-Public on the public vhost. v2's server.py serves such requests
# READ-ONLY: writes get 403, and so does any public GET outside its allow-list (the
# page, static files and the nodes/status/validator/network/version/system reads).
# A 403 there is EXPECTED, not a failure. Run this FIRST (backend live on :8080),
# THEN dns.sh so the vhost points at a service that already answers. No secret
# travels here — the basic_auth bcrypt hash lives only in the Caddy vhost, and the
# UI's own access token is created on the node by install-ui.sh.
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

UI_INSTALLER="${TN_NODE_SCRIPTS_DIR}/ui/install-ui.sh"   # on the node, in its root-owned checkout

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

echo "=========================================="
echo "devnet admin-dashboard (Node Manager UI) rollout"
echo "Project:   ${PROJECT_ID}"
echo "Installer: ${UI_INSTALLER} (on each node)  ->  first install, or --update when telcoin-ui exists"
echo "Service:   telcoin-ui on 127.0.0.1:8080"
echo "Transport: ${TN_SSH_TRANSPORT}"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:    ${SELECTED[*]}"
echo "=========================================="

# Per-node remote command (one root round-trip; see the header for the two paths).
# Paths are expanded here and single-quoted for the remote shell. UI_MODE= names the
# path taken; the trailing UI_REFRESH_OK is the success sentinel.
remote_cmd="set -e; \
sudo test -f '${UI_INSTALLER}' || { echo 'UI_ERR: ${UI_INSTALLER} not found (no tn-node-deployment checkout at ${TN_NODE_SCRIPTS_DIR}?)' >&2; exit 1; }; \
if systemctl list-unit-files --no-legend telcoin-ui.service 2>/dev/null | grep -q '^telcoin-ui\.service'; then \
echo UI_MODE=update; sudo bash '${UI_INSTALLER}' --update </dev/null; sudo systemctl enable --quiet telcoin-ui; \
else \
echo UI_MODE=install; sudo bash '${UI_INSTALLER}' </dev/null; \
fi; \
systemctl is-enabled --quiet telcoin-ui || { echo 'UI_ERR: telcoin-ui is not enabled on boot' >&2; exit 1; }; \
curl -fsS --max-time 3 --retry 10 --retry-delay 2 --retry-connrefused -o /dev/null http://127.0.0.1:8080/ || { echo 'UI_ERR: no HTTP 200 from GET 127.0.0.1:8080/' >&2; exit 1; }; \
systemctl is-active --quiet telcoin-ui || { echo 'UI_ERR: telcoin-ui is not active (another process on :8080?)' >&2; exit 1; }; \
echo UI_REFRESH_OK"

rc=0
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"

    tn_dash_selected "${inst}" || continue

    echo ""
    echo ">>> ${inst} (${zone}): install-ui.sh from ${TN_NODE_SCRIPTS_DIR}"

    # Capture output so a failing node prints its installer log; rc + the
    # UI_REFRESH_OK sentinel gate success. UI_MODE (install|update) names the path.
    if out="$(tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}" 2>&1)"; then ssh_rc=0; else ssh_rc=$?; fi
    echo "${out}" | sed 's/^/    /'
    mode="$(printf '%s\n' "${out}" | sed -n 's/^UI_MODE=//p' | tail -n 1)"
    if [ "${ssh_rc}" -ne 0 ]; then
        echo "    ❌ ${inst}: UI rollout failed (path: ${mode:-none, install-ui.sh not run}; rc ${ssh_rc}) — see the UI_ERR / [ERROR] lines above" >&2
        rc=1
    elif ! printf '%s' "${out}" | grep -q 'UI_REFRESH_OK'; then
        echo "    ⚠️  ${inst}: remote command exited 0 but UI_REFRESH_OK missing — verify telcoin-ui by hand" >&2
        rc=1
    elif [ "${mode}" = "update" ]; then
        echo "    ✅ ${inst}: telcoin-ui refreshed (--update), enabled, answering on 127.0.0.1:8080"
    else
        echo "    ✅ ${inst}: telcoin-ui installed (first install), enabled, answering on 127.0.0.1:8080"
    fi
done

echo ""
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "admin-dashboard rollout complete on all targeted nodes."
    echo "telcoin-ui now listens on 127.0.0.1:8080 per node. Expose it read-only at"
    echo "admin.<node>.${BASE_DOMAIN} by running ./common/dns.sh (admin vhost is default-on;"
    echo "dns.sh fetches the basic_auth hash from Secret Manager automatically). On that public"
    echo "vhost a 403 for writes or non-allow-listed reads is expected. Full controls are over"
    echo "the SSH tunnel (tn-node-deployment/open-ui.sh)."
    echo "=========================================="
else
    echo "=========================================="
    echo "admin-dashboard rollout finished WITH ERRORS — see the ❌ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
