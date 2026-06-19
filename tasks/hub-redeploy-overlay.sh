#!/bin/bash
#
# hub-redeploy-overlay.sh — BREAK-GLASS: redeploy the WireGuard hub ("the wheel") OVER THE
# OVERLAY instead of IAP. Use when the sanctioned path (common/wgvpn/deploy-hub.sh, or
# hub_redeploy in common/wgvpn/lib/hub-admin-lib.sh) can't reach the hub because IAP is broken
# client-side — e.g. gcloud's bundled lightweight websocket dropping the tunnel the instant it
# opens (iap_tunnel_lightweight_websocket.py). hub_redeploy is HARD-CODED to --tunnel-through-iap,
# so when IAP is down there is otherwise no way to push a registry change to the live hub.
#
# It does EXACTLY what hub_redeploy does — scp the wgvpn bundle to the hub and run the trusted
# hub/bringup-hub.sh on it (re-renders /etc/wireguard/wg0.conf from peers/registry.csv and applies
# it with `wg syncconf`, NO tunnel drop) — but reaches the hub DIRECTLY at its overlay IP
# (10.100.0.1) over the operator's WireGuard tunnel, not via IAP. The render logic is unchanged
# (bringup-hub.sh); this only swaps the transport.
#
# PRECONDITIONS (none need local sudo):
#   - the operator's WG tunnel is UP  (sudo wg-quick up tn-wg0)  and the operator is ALREADY a
#     peer on the live hub, so 10.100.0.1 is reachable. (The operator's maintainer row predates
#     this change, so the live hub already trusts them.)
#   - the local common/wgvpn/peers/registry.csv holds the desired peer set (e.g. the recreated
#     nodes' current pubkeys).
#
# Idempotent and safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
WGVPN_DIR="${REPO_ROOT}/common/wgvpn"
# Overlay constants + hub coordinates (safe to source standalone; runs no gcloud/wg at source time).
# shellcheck source=/dev/null
source "${WGVPN_DIR}/wg-config.sh"

KEY="${TN_SSH_KEY:-${TNVPN_HOME:-${HOME}/.config/tnvpn}/id_ed25519}"
HUB="${WG_TNADMIN_USER}@${WG_HUB_OVERLAY_IP}"
SSHOPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
[ -f "${KEY}" ] && SSHOPTS+=(-i "${KEY}" -o IdentitiesOnly=yes)

echo ">>> hub redeploy OVER OVERLAY -> ${HUB}"
echo "    project=${WG_HUB_PROJECT}  privkey-secret=${WG_HUB_PRIVKEY_SECRET}  bundle=${WGVPN_DIR}"

# Pre-flight: prove we can actually reach the hub over the overlay before mutating anything.
if ! ssh "${SSHOPTS[@]}" -o ConnectTimeout=8 "${HUB}" true 2>/dev/null; then
    echo "" >&2
    echo "❌ cannot ssh ${HUB} over the overlay. Is the tunnel up and are you a hub peer?" >&2
    echo "   Bring the tunnel up (local sudo), then re-run:" >&2
    echo "     sudo install -m 600 ~/.config/tnvpn/tn-wg0.conf /etc/wireguard/tn-wg0.conf" >&2
    echo "     sudo wg-quick up tn-wg0" >&2
    echo "     sudo wg show ; ping -c3 ${WG_HUB_OVERLAY_IP}" >&2
    exit 1
fi

echo ">>> [1/3] clear any stale bundle on the hub"
ssh "${SSHOPTS[@]}" "${HUB}" 'sudo rm -rf /tmp/wgvpn'

echo ">>> [2/3] push the wgvpn bundle (carries the updated registry.csv)"
scp "${SSHOPTS[@]}" -r "${WGVPN_DIR}" "${HUB}:/tmp/wgvpn"

echo ">>> [3/3] re-render wg0.conf + apply with wg syncconf (no tunnel drop)"
ssh "${SSHOPTS[@]}" "${HUB}" \
    "sudo PROJECT_ID='${WG_HUB_PROJECT}' WG_HUB_PRIVKEY_SECRET='${WG_HUB_PRIVKEY_SECRET}' bash -s" \
    < "${WGVPN_DIR}/hub/bringup-hub.sh"

echo ""
echo ">>> hub redeploy complete. The recreated devnet nodes should re-handshake within"
echo "    ~25s (PersistentKeepalive). Verify with:"
echo "      export TN_SSH_TRANSPORT=overlay; source ./devnet-lib.sh"
echo "      for n in validator-1-devnet validator-2-devnet validator-3-devnet validator-4-devnet observer-5-devnet; do"
echo "        echo \"== \$n ==\"; tn_ssh \"\$n\" 'hostname && sudo wg show wg0 latest-handshakes'; done"
