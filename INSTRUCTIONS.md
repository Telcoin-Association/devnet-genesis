# Maintainer instructions

Day-to-day admin access to devnet nodes runs over **IAP**. At the VPC, tcp:22 is open only
to Google's IAP range (`wg-allow-iap-ssh`, 35.235.240.0/20). On each node, UFW is the single
host firewall. Every `devnet-*.sh` driver reaches the fleet over IAP by default.

The **WireGuard overlay** ("the wheel") is break-glass, for when your local IAP transport is
broken. Nodes still join it at boot (overlay only, no nftables policy: `WG_NODE_FIREWALL=0`).
The full reference (architecture, admin runbook, security model) is
[`common/wgvpn/README.md`](common/wgvpn/README.md).

## Reaching nodes day-to-day

```bash
# Once per session.
gcloud auth login
gcloud config set project tn-devnet

# A shell on a node. Zones are in config.sh ZONES and the README node table.
gcloud compute ssh validator-1-devnet --zone=us-west2-a --tunnel-through-iap

# One command on a node.
gcloud compute ssh observer-5-devnet --zone=europe-west2-b --tunnel-through-iap \
  --command='systemctl is-active telcoin'

# The same helper the drivers use (sources config.sh for you).
source ./devnet-lib.sh
tn_iap_ssh validator-2-devnet australia-southeast1-c 'sudo tail -n 50 /var/log/telcoin/telcoin.log'
```

The node scripts are the root-owned checkout at `/opt/telcoin-node-scripts`, so run them with `sudo`.
Node settings are in `/etc/telcoin/.node-meta` (root 0600). From your machine, read one key with `tn_node_meta_get <instance> <zone> <KEY>`.

## Break-glass: the overlay

### One-time setup

```bash
# 1. Install a WireGuard runtime. Key generation (step 2) does NOT need it; the tunnel does.
brew install wireguard-tools wireguard-go     # macOS
sudo apt-get install -y wireguard             # Linux

# 2. Mint your WG keypair + dedicated tnvpn SSH key and print the PUBLIC halves.
#    Idempotent: never overwrites an existing key.
./common/wgvpn/dev-setup.sh

# 3. Send the two PUBLIC keys it printed to an admin. They run add-peer.sh to assign your
#    10.100.9.<idx> and push you to the hub (and sync-access.sh if the network is locked).

# 4. Pull the latest common/ and re-run dev-setup.sh. It reads your assigned IP from the
#    registry and fills your tunnel's Address automatically.
git -C common pull && ./common/wgvpn/dev-setup.sh

# 5. Bring the tunnel up (create /etc/wireguard first: absent on a fresh macOS install).
sudo mkdir -p /etc/wireguard
sudo install -m 600 ~/.config/tnvpn/tn-wg0.conf /etc/wireguard/tn-wg0.conf
sudo wg-quick up tn-wg0                        # down again: sudo wg-quick down tn-wg0

# 6. Verify.
sudo wg show          # a recent handshake + nonzero transfer
ping -c 3 10.100.0.1  # the hub
```

Step 4 can move the `common` gitlink. Do not commit that change: the pin is deliberate (see the README).

### Using it

```bash
TN_SSH_TRANSPORT=overlay ./devnet-network-config.sh --verify   # any driver, over the overlay

source ./config.sh && source common/wgvpn/lib/wg-ssh-lib.sh
tn_ssh validator-1-devnet 'systemctl is-active telcoin'        # ssh to a node over the hub jump
```

`config.sh` sets `TN_USE_VPN=1`. Sourcing `wg-ssh-lib.sh` with that set also shadows `gcloud compute ssh|scp` with an overlay shim that ignores `--tunnel-through-iap`.
Use a separate shell for IAP. The drivers suppress the shim themselves.

Full reference (architecture, admin runbook, security model):
[`common/wgvpn/README.md`](common/wgvpn/README.md).

## Further reading

- [`docs/validator-key-provisioning.md`](docs/validator-key-provisioning.md): validator execution keys (`devnet-validator-key.sh`).
- [`docs/release-signing-ceremony.md`](docs/release-signing-ceremony.md)
- [`docs/mainnet-simulation-plan.md`](docs/mainnet-simulation-plan.md)
