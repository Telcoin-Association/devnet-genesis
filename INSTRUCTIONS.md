# Maintainer instructions

Day-to-day admin access to Telcoin nodes runs over the **WireGuard overlay** ("the wheel"):
nodes have no public SSH, so you reach them through a hub you VPN into. This is the
quickstart. The full reference — architecture, admin runbook, security model — is
[`common/wgvpn/README.md`](common/wgvpn/README.md).

## One-time setup

```bash
# 1. Install a WireGuard runtime. Key generation (step 2) does NOT need it; the tunnel does.
brew install wireguard-tools wireguard-go     # macOS
sudo apt-get install -y wireguard             # Linux

# 2. Mint your WG keypair + dedicated tnvpn SSH key and print the PUBLIC halves.
#    Idempotent — never overwrites an existing key.
./common/wgvpn/dev-setup.sh

# 3. Send the two PUBLIC keys it printed to an admin. They run add-peer.sh to assign your
#    10.100.9.<idx> and push you to the hub (and sync-access.sh if the network is locked).

# 4. Pull the latest common/ and re-run dev-setup.sh — it reads your assigned IP from the
#    registry and fills your tunnel's Address automatically.
git -C common pull && ./common/wgvpn/dev-setup.sh

# 5. Bring the tunnel up (create /etc/wireguard first — absent on a fresh macOS install).
sudo mkdir -p /etc/wireguard
sudo install -m 600 ~/.config/tnvpn/tn-wg0.conf /etc/wireguard/tn-wg0.conf
sudo wg-quick up tn-wg0                        # down again: sudo wg-quick down tn-wg0

# 6. Verify.
sudo wg show          # a recent handshake + nonzero transfer
ping -c 3 10.100.0.1  # the hub
```

## Reaching nodes day-to-day

```bash
source common/wgvpn/lib/wg-ssh-lib.sh
tn_ssh validator-1-devnet 'docker ps'          # ssh to a node over the hub jump
TN_USE_VPN=1 ./common/update-staggered.sh      # reroute a fleet script over the overlay
```

Full reference (architecture, admin runbook, security model):
[`common/wgvpn/README.md`](common/wgvpn/README.md).
