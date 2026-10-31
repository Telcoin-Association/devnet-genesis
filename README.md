# Telcoin Devnet

Telcoin Devnet is deployed to Google Cloud Compute VMs running Ubuntu 24.04 (project `tn-devnet`).

The fleet is five VMs: `validator-1-devnet` through `validator-4-devnet` and `observer-5-devnet`.
Nodes 1-4 are the genesis committee. Node 5 is a unified node outside the genesis committee.
`devnet-stake-node5.sh` stakes it after genesis, so the 4-seat committee rotates among 5 validators.

The docker image is publicly available at `us-docker.pkg.dev/telcoin-network/tn-public/adiri`.
`config.sh` pins it by digest in `DOCKER_IMAGE` (`<repo>@sha256:<64 hex>`). `DOCKER_IMAGE_TAG` only records the tag the digest came from.

MC is the "Master of Ceremony". MC is required until decentralized discovery is supported.

MC runs every script in this repo from one machine.
`devnet-keygen.sh` pulls each node's `node-info.yaml` into `genesis/validators/` (nodes 1-4) or `genesis/observers/` (node 5).
`devnet-genesis-build.sh` builds `genesis/committee.yaml` and `genesis/genesis.yaml` from `genesis/validators/`.
`devnet-finalize.sh` stages `committee.yaml`, `genesis.yaml` and `parameters.yaml` on every node and starts it.

## Shared deploy scripts (`common/` submodule)

Fleet and GCP scripts shared with the other Telcoin networks live in
[`deploy-networks-common`](https://github.com/Telcoin-Association/deploy-networks-common),
mounted here as the **`common/`** git submodule. Devnet's own pieces are `config.sh`, the
`devnet-*.sh` drivers, `setup-firewall.sh` and the `genesis/` state.

Clone with the submodule, or fetch it after cloning:

```bash
git clone --recurse-submodules <repo-url>
# or, if you already cloned without it:
git submodule update --init
```

`config.sh` is the single indirection point: it computes `REPO_ROOT` and exports every
setting and path the scripts need (`PARAMETERS_FILE`, `CONFIG_CADDY_SCRIPT`,
`STARTUP_SCRIPT_PATH`, ...) as absolute paths, so scripts resolve their inputs from any
working directory. Run the `devnet-*.sh` drivers from the repo root. `devnet-deploy.sh`
calls the `common/` scripts it needs; you rarely run them by hand.

To pull shared-script updates into this repo:

```bash
cd common && git pull origin main && cd ..
git add common && git commit -m "bump deploy-networks-common"
```

Right now `common` is pinned to a commit on branch `devnet/genesis-knobs`, which adds the genesis knobs below.
Do not move it back to `main` until that branch merges.

## Node model (tn-node-deployment v2)

Per-node actions run tn-node-deployment v2 on the node itself. The `devnet-*.sh` drivers call it over SSH.

- Keygen and finalize both run `setup-node.sh`, with `--phase=keygen` or `--phase=finalize`.
- Each node runs the scripts from a root-owned checkout at `/opt/telcoin-node-scripts`.
- That checkout is pinned by the `tn-scripts-ref` instance metadata, which is `config.sh` `TN_NODE_SCRIPTS_REF` (a full commit sha).
- `devnet-deploy.sh` refuses to run unless `TN_NODE_SCRIPTS_REF` is 40 hex characters.
- The `tn-node-deployment/` submodule is a local copy at the same commit, for reading. The nodes fetch their own.
- `devnet-startup.sh` is the GCP startup script. It installs docker-ce and the Ops Agent, fetches the checkout and brings up the WireGuard overlay.
- The `telcoin` service account is a system uid. `setup-node.sh` creates it; the startup script does not.
- The node records its settings in `/etc/telcoin/.node-meta` (root 0600).

Secrets never go on argv or into the environment:

- The BLS passphrase lives in `.secrets/bls-passphrase` (gitignored). It reaches the node only on stdin (`--passphrase-stdin`) and is never exported.
- The obs ingest token comes from Secret Manager and reaches the node the same way (`--token-stdin`).

The fleet is reached over IAP by default. The WireGuard overlay is break-glass only: set `TN_SSH_TRANSPORT=overlay`. See [`INSTRUCTIONS.md`](INSTRUCTIONS.md).

## Genesis knobs

`config.sh` exports these. Every one changes the genesis hash.

- `MIN_HEADER_DELAY_MS=350`, `MAX_HEADER_DELAY_MS=1000`
- `MAX_BATCH_DELAY_MS=250`
- `WORKER_FEE_CONFIG=0:0:10000000` (worker 0, EIP-1559, target 10,000,000 gas per epoch)
- `SAFE_EXTRA_OWNER=0xAee2797478Cb5EfaF1869A2e33e369421EBf520f` (the contracts admin)

`common/genesis.sh` passes the delay and fee knobs to `telcoin genesis`.
`devnet-genesis-build.sh` checks the three delays in `parameters.yaml`, then patches the governance Safe (`0x...07a0`) in `genesis.yaml`.
It sets the threshold to 1 and inserts `SAFE_EXTRA_OWNER` as the first owner, so the admin can mint and govern alone.
`GENESIS_DOCKER_USER` runs the genesis container as your own uid:gid, so it can write the workspace on rootful Linux docker.

## Closed connection admission

Every node runs closed connection admission from `<datadir>/network-config`.
`devnet-network-config.sh` renders those files into `genesis/network-config/` and installs them before the first start.
A node that starts without the file writes the default one (admission Open), so the order matters.
Re-render after every new keygen.

## Steps to deploy the network on Google Cloud Compute

1. Pin the image digest, the node 5 address and `TN_NODE_SCRIPTS_REF` in `config.sh`, and fund the node 5 address in `testnet_accounts.yaml`.
   `devnet-deploy.sh` refuses to run while any `PLACEHOLDER_` value remains.
1. For a fresh genesis, run `./devnet-teardown.sh` (dry run), then `./devnet-teardown.sh --yes`.
   Keygen refuses a node that already has keys, so new keys need new VMs.
1. Run `./devnet-deploy.sh --yes`. It runs 16 steps in order:
   1. reserve static IPs: `common/reserve-static-ips.sh`
   1. create instances: `common/create-instances.sh`
   1. wait for first-boot bootstrap on every node (serial-console completion marker)
   1. MANUAL: DNS A-records `node{N}.devnet.telcoin.network` to each static IP (always pauses for ENTER)
   1. keygen: `devnet-keygen.sh`
   1. build genesis: `devnet-genesis-build.sh`
   1. per-node network-config: `devnet-network-config.sh --yes` (before the first node start)
   1. finalize (stage + start): `devnet-finalize.sh`
   1. obs VM: `common/create-obs-instance.sh --wipe-data`
   1. host firewall (UFW): `devnet-firewall.sh --enable`, then `devnet-firewall.sh`
   1. per-node observability: `devnet-observability.sh` (needs UFW active from step 10)
   1. GCP/VPC firewall rules: `setup-firewall.sh`
   1. DNS/Caddy + load balancer: `common/dns.sh`, `common/setup-load-balancer.sh`
   1. admin dashboards: `devnet-dashboards.sh`, `common/dns.sh` (opt out: `TN_ADMIN_DASHBOARD=0`)
   1. app-contract stack: `devnet-contracts.sh --yes` (tn-contracts infra, LPs, faucet role)
   1. transaction generator: `devnet-txgen.sh --yes` (`txgen-devnet` VM, permanent service)
1. Stake node 5 once it syncs: `./devnet-stake-node5.sh` (dry run), then `./devnet-stake-node5.sh --yes`.
   Node 5 can first sit in the committee of activation epoch + 2.

The full operator runbook for the 2026-10-30 reset is [`tasks/runbook-reset-2026-10-30.md`](tasks/runbook-reset-2026-10-30.md).

### Additional notes for GCP Deployment:

- Resume a failed run with `--from N`, or run one step with `--only N`.
- `devnet-deploy.sh` has no per-node selector. If keygen or finalize fails on one node, fix it and run that driver for that node (`./devnet-keygen.sh node3`, `./devnet-finalize.sh node3`). Then continue with `--from 6` or `--from 9`.
- Static external IPs are reserved once and survive teardown, so the DNS A-records only change if an IP does.
- `devnet-teardown.sh` deletes the five node VMs and their disks. Static IPs, the obs data disk, the LB, DNS, VPC rules, `txgen-devnet` and the WireGuard hub survive.
- Each node serves `https://node{N}.devnet.telcoin.network` through Caddy (`common/dns.sh` runs `common/config-caddy.sh`).
- The global load balancer serves `https://rpc.devnet.telcoin.network`.
- The admin dashboard (Node Manager UI) is at `admin.node{N}.devnet.telcoin.network`, read-only behind basic auth. Create its credential once with `./devnet-admin-secret.sh`.
- The obs VM `obs-devnet` runs Loki, Prometheus and Grafana at `obs.devnet.telcoin.network`. It stays on Debian 12.
- UFW is the single host firewall. `setup-firewall.sh` owns the VPC rules, and tcp:22 is open only to IAP at the VPC.
- Use `gcloud compute instances get-serial-port-output INSTANCE_NAME --zone ZONE` to debug the startup script. A finished boot ends with `devnet-startup.sh complete`.

### Day-two tools

- `./devnet-basefee-check.sh --last 2`: read-only check that each epoch boundary moved worker 0's base fee as the protocol says.
- `./devnet-stake-node5.sh --yes --from-step 6 --watch-epochs 3`: watch node 5's committee membership after staking.
- `./devnet-network-config.sh --verify`: read-only re-read and validation of every node's installed network-config.
- `./devnet-dashboards.sh`: install or refresh the Node Manager UI on every node.

### WARNING: not yet v2-aware

- `devnet-update.sh` and `devnet-update-all.sh` parse a tag out of `DOCKER_IMAGE`, which is now a digest. Do not use them for an image update yet.
- `reset-network.sh` (and `devnet-update.sh --finalize`) re-runs finalize, which v2 refuses on a node that already has its unit. Reset with teardown + `devnet-deploy.sh` instead.

### Nodes

| Node | Instance | Role | Zone | Location | Execution address |
| --- | --- | --- | --- | --- | --- |
| node1 | `validator-1-devnet` | genesis validator | `us-west2-a` | LA | `0x3518b301b86ceb53b5a3dff62e55cd43ef59d024` |
| node2 | `validator-2-devnet` | genesis validator | `australia-southeast1-c` | Australia | `0x7489025dfbaad94f2366d88a62989147d9c8b5d3` |
| node3 | `validator-3-devnet` | genesis validator | `northamerica-northeast1-b` | Montreal | `0x0033a370616805b1fd275b7ffab83fc41d665ccb` |
| node4 | `validator-4-devnet` | genesis validator | `europe-west4-a` | Netherlands | `0xefaacf04b92298a88200aa50aa6bb7bfce587b17` |
| node5 | `observer-5-devnet` | unified node, staked after genesis | `europe-west2-b` | London | new key at deploy time: `config.sh` `EXECUTION_ADDRESSES[4]` |
