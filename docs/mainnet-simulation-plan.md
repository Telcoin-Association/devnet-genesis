# Launch 2: the devnet as a mainnet simulation

Status: design, not started.
Prerequisite: launch 1 (the 2026-10-31 reset) is live and reviewed.
Protocol reference: telcoin-network `3f9b0709c`.
Convention: "[I]" marks an inference drawn from the protocol facts below. It has not been verified against code or a running chain.

## 1. Purpose and scope

Launch 2 rebuilds the devnet so it runs the way an independently operated mainnet validator set would run. Validators admit only committee members and their own sentry. Every public-facing duty (peer discovery, gossip fan-out, sync, RPC ingress) moves to a sentry. Both firewall layers, the GCP VPC and host ufw, enforce per-node allowlists. A fifth validator joins through the path a new mainnet operator would take: mint, stake, sync through sentries, activate, rotate in.

Goals:

- Run closed admission (both directions) on a live chain and record how it behaves at boot, at epoch boundaries and when a validator joins.
- Exercise the RPC ingress path a public user hits: load balancer, sentry, JSON-RPC forward to a validator.
- Rehearse "add a 5th validator" end to end, including the firewall staging step, so the procedure is written down and timed before mainnet needs it.
- Install node releases through a GPG-signed release channel (option B, section 8) instead of a bare image digest.

Out of scope:

- Carrying node-to-node traffic over the WireGuard hub. The hub cannot do it, so validators keep public static IPs and /32 allowlists. That is also the mainnet model for independently operated validators.
- `lockdown-firewall-gcp.sh`. Never run it on devnet. IAP SSH and the 10.100.9.0/24 admin range stay.
- Container image signatures. The release model has no cosign signature anywhere; the GPG-signed `SHA256SUMS` is the trust root.
- Hiding validator IP addresses. `committee.yaml` `bootstrap_servers` already publishes every genesis validator's multiaddrs, so protection comes from admission and firewalls.

Ordering: launch 2 is a second teardown and deploy. It starts from launch 1's configuration, in which node 2 runs in us-south1 (Dallas). (`config.sh` in this tree still lists `australia-southeast1-c` for node 2; launch 1 changes that.)

## 2. Protocol facts the design rests on

All facts are as of telcoin-network `3f9b0709c`.

### 2.1 Identity and keys

- Transport is QUIC with TLS 1.3, nothing else.
- Each swarm (primary, worker 0, and so on) has its own ed25519 network key, derived deterministically from the BLS secret: `ed25519_from_bytes(hash(BLS_sign("primary network keypair")))` (`crates/config/src/keys.rs:552-557`). The PeerId derives from that public key, and the TLS certificate proves possession of it.
- The only secret on a node is `node-keys/bls.kw` plus its passphrase. Network secret keys are re-derived at every start and never stored.
- [I] A sentry is a full node identity with its own `bls.kw`. Its PeerIds stay the same as long as `bls.kw` survives, so a `trusted_nodes` entry naming a sentry stays valid across restarts. A lost `bls.kw` means new PeerIds and a re-rendered network-config on the paired validator.

### 2.2 Genesis ceremony

- Each validator contributes a `node-info.yaml`: BLS public key, a proof of possession bound to its execution address, primary and per-worker ed25519 public keys with reachable multiaddrs, and an optional RPC URL.
- `telcoin genesis` over `genesis/validators/*.yaml` checks every proof of possession and that worker counts match, then emits `genesis.yaml`, `parameters.yaml` and `committee.yaml`. The `bootstrap_servers` section of `committee.yaml` is exactly that public material.
- The ConsensusRegistry stores BLS keys and addresses only. No network key or multiaddr is on chain.
- [I] Sentries never appear in `genesis/validators/` or `committee.yaml`. Their PeerIds and multiaddrs reach other nodes only through network-config (`trusted_nodes`, `bootstrap_peers`) and through their own DHT records.

### 2.3 Discovery

- At epoch 0 a node finds peers from three sources: `committee.yaml` `bootstrap_servers` (replaced wholesale by a non-empty `bootstrap_peers`), network-config `committee_peers` (which must list every committee member if it is non-empty), and `trusted_nodes`.
- After epoch 0, peers come from BLS-signed per-swarm node records in the Kademlia DHT. A record is signed over chain id, role, worker id, network public key, up to 4 multiaddrs, a timestamp and the RPC URL. The kad publisher must equal the record's network key.
- A node pushes its records to every peer on first connect. Third-party replication is off, so a record exists only on peers its owner has connected to.
- [I] A sentry cannot forge or alter another node's record (BLS signature plus the publisher check). It can withhold one, so sentries put record availability at risk, not record integrity.

### 2.4 Closed admission

- Closed admission filters both directions. It admits PeerIds bound (by a signed record or a config stub) to BLS keys in the previous, current or next committee, plus permanent operator grants: `trusted_nodes` and `bootstrap_peers`. When `bootstrap_peers` is unset, the default bootstrap set (the 4 genesis validators) is the grant.
- Closed needs at least n - floor((n-1)/3) authenticated current-committee records, which is 3 of 4 here. With fewer, the node drops to Grace, which behaves as Open.
- Every process starts Open and stays Open until its first epoch-start window.
- `snapshot_max_age_secs` is a lease, renewed every lease/3.
- A denied peer completes the QUIC handshake before it is refused, and it is not banned. A host firewall is still needed to keep unknown peers off a validator.
- [I] From process start to the first epoch-start window, and during any Grace period, the firewalls are the only filter in front of a validator. The allowlists in section 5 are sized for that case, not for the steady state.

### 2.5 Joining, data paths and transactions

- A validator that calls `activate()` in epoch N becomes PendingActivation with `activationEpoch` N+1. Its first possible seat is N+3, decided by a random draw with `nextCommitteeSize` 4.
- Registry status never grants admission. Membership in the committee window does, and a joiner enters the window one epoch early, as "next", at N+2.
- Votes, certificate fetch and the batch quorum are direct dials among window validators, on every port. A sentry can carry DHT traffic, gossip fan-out, sync and RPC ingress. It cannot carry consensus traffic.
- Transactions are not gossiped. An observer or sentry forwards them over JSON-RPC to the URL advertised in a validator's worker record (set with `--rpc-http` at keygen).
- `tn node record` (tn-cli) uses an ephemeral identity, so a Closed node refuses it. It needs an Open peer, which in this topology means a sentry.
- [I] If the draw is uniform, node 5 wins a seat with probability 4/5 per draw, so the rehearsal may wait an extra epoch or two before N+3 arrives.

### 2.6 Release model

- tn-node-deployment node releases are a GPG-signed `SHA256SUMS` (covering `IMAGE_DIGEST`, the tarball and the three chain configs) attached to a telcoin-network GitHub release and verified with `gpgv` against `lib/release-keys/*.asc`. No image signature (cosign) exists anywhere.
- On devnet today (tn-node-deployment PR 12) a node checks only the image digest and the repository allow-list, and it refuses release tags.

### 2.7 Infrastructure constraints

- The WireGuard hub cannot carry node-to-node traffic.
- Static external IPs are regional, so each sentry's address is reserved in its validator's region.
- DNS A records are created by hand.
- The RPC load balancer keeps one zonal unmanaged instance group per node.

## 3. Topology

Ten node VMs plus the existing `obs-devnet` and txgen VMs. Every node VM is `e2-custom-4-8192` on Ubuntu 24.04 with a reserved static external IP named `<instance>-ip` (the `STATIC_IP_NAMES` pattern). Each sentry sits in its validator's region, in a different zone letter. The sentry zone letters below are proposals for L2-A.

| Idx | Instance | `NODE_ROLES` | Hostname | Zone | Admission | `trusted_nodes` | Bootstrap | Tags |
|---|---|---|---|---|---|---|---|---|
| 0 | `validator-1-devnet` | validator | node1 | us-west2-a | Closed | sentry-1 | default set (4 genesis validators) | `validator`, `validator-1` |
| 1 | `validator-2-devnet` | validator | node2 | us-south1, zone from launch 1 | Closed | sentry-2 | default set | `validator`, `validator-2` |
| 2 | `validator-3-devnet` | validator | node3 | northamerica-northeast1-b | Closed | sentry-3 | default set | `validator`, `validator-3` |
| 3 | `validator-4-devnet` | validator | node4 | europe-west4-a | Closed | sentry-4 | default set | `validator`, `validator-4` |
| 4 | `observer-5-devnet` | observer (renderer role: joiner) | node5 | europe-west2-b | Closed | sentry-5 | `bootstrap_peers` = sentry-1..5 | `validator`, `validator-5` [I] |
| 5 | `sentry-1-devnet` | sentry | sentry1 [I] | us-west2-b | Open | validator-1 | `bootstrap_peers` = validator-1, sentry-2..5 | `sentry`, `sentry-1` |
| 6 | `sentry-2-devnet` | sentry | sentry2 [I] | us-south1, other letter than node 2 | Open | validator-2 | validator-2, sentry-1,3,4,5 | `sentry`, `sentry-2` |
| 7 | `sentry-3-devnet` | sentry | sentry3 [I] | northamerica-northeast1-a | Open | validator-3 | validator-3, sentry-1,2,4,5 | `sentry`, `sentry-3` |
| 8 | `sentry-4-devnet` | sentry | sentry4 [I] | europe-west4-b | Open | validator-4 | validator-4, sentry-1,2,3,5 | `sentry`, `sentry-4` |
| 9 | `sentry-5-devnet` | sentry | sentry5 [I] | europe-west2-a | Open | node 5 | node 5, sentry-1..4 | `sentry`, `sentry-5` |
| - | `obs-devnet` | (not a node) | - | us-west2-a | - | - | - | unchanged |
| - | txgen VM | (not a node) | - | unchanged | - | - | - | unchanged |

`committee_peers` is the 4 genesis validators on every node. `trusted_nodes` entries name both the primary and the per-worker identities (a primary plus workers map).

Notes:

- sentry-5 is an optional cost. It stays in the plan to rehearse "a new validator arrives with its sentry". [I] Without it, node 5 has an empty `trusted_nodes` and keeps sentry-1..4 as `bootstrap_peers`.
- Node 5 keeps `NODE_ROLES` "observer" so existing scripts that branch on it keep working. Only the network-config renderer calls it "joiner".
- Tagging node 5 `validator-5` [I] lets it share the validator rule family from day one, including the internal-range deny in section 5.
- The hostnames `sentry1..sentry5` [I] follow the `NODE_NAMES` pattern; L2-F owns the final names and the manual A records.

Config shape for L2-A (arrays appended at indices 5..9, every array still parallel to `INSTANCE_NAMES`):

```bash
export INSTANCE_NAMES=("validator-1-devnet" "validator-2-devnet" "validator-3-devnet" "validator-4-devnet" "observer-5-devnet"
                       "sentry-1-devnet" "sentry-2-devnet" "sentry-3-devnet" "sentry-4-devnet" "sentry-5-devnet")
export NODE_ROLES=("validator" "validator" "validator" "validator" "observer"
                   "sentry" "sentry" "sentry" "sentry" "sentry")
export ZONES=("us-west2-a" "us-south1-<x>" "northamerica-northeast1-b" "europe-west4-a" "europe-west2-b"
              "us-west2-b" "us-south1-<y>" "northamerica-northeast1-a" "europe-west4-b" "europe-west2-a")
export NODE_NAMES=("node1" "node2" "node3" "node4" "node5"
                   "sentry1" "sentry2" "sentry3" "sentry4" "sentry5")
export STATIC_IP_NAMES=("validator-1-devnet-ip" "validator-2-devnet-ip" "validator-3-devnet-ip" "validator-4-devnet-ip" "observer-5-devnet-ip"
                        "sentry-1-devnet-ip" "sentry-2-devnet-ip" "sentry-3-devnet-ip" "sentry-4-devnet-ip" "sentry-5-devnet-ip")
# Index of the node each sentry fronts; empty for non-sentries.
export SENTRY_OF=("" "" "" "" "" 0 1 2 3 4)
# Per-node network tags, consumed by common/create-instances.sh (common PR).
export INSTANCE_TAGS=("validator,validator-1" "validator,validator-2" "validator,validator-3" "validator,validator-4" "validator,validator-5"
                      "sentry,sentry-1" "sentry,sentry-2" "sentry,sentry-3" "sentry,sentry-4" "sentry,sentry-5")
# Roles whose zonal unmanaged groups back devnet-rpc-backend (variable name illustrative).
export LB_BACKEND_ROLES=("sentry")
```

`EXECUTION_ADDRESSES` stays 5 entries long or gains empty entries for sentries; L2-A decides, and every loop over it must tolerate the choice. The `LB_*` names (`devnet-rpc-backend`, `devnet-rpc-urlmap`, `devnet-rpc-fr`, `devnet-rpc-ip` and so on) are unchanged.

## 4. Admission matrix

Who each node admits, by peer class, in steady state (after the node's first epoch-start window and with at least 3 authenticated current-committee records). "Window" means the BLS key is in the previous, current or next committee.

| Deciding node (mode) | Its pair (own sentry, or own validator) | Other sentries | Genesis validators | Node 5 | Unknown or ephemeral peer |
|---|---|---|---|---|---|
| validator-i (Closed) | admit: `trusted_nodes` | deny | admit: default bootstrap grant (permanent), also window | deny before N+2; admit from N+2 via window, record resolved through sentry-i | deny after the QUIC handshake; the VPC drops it first |
| node 5 (Closed) | admit sentry-5: `trusted_nodes` | admit: `bootstrap_peers` grant (permanent) | admit while in node 5's window | (self) | deny after the handshake; the VPC drops it first |
| sentry-i (Open) | admit (also `trusted_nodes`) | admit | admit; the VPC lets sentry-i reach only validator-i | admit | admit (this is how `tn node record` works) |

States outside the steady state:

| Condition | Effective mode | Filter left in front of the node |
|---|---|---|
| Process start until the first epoch-start window | Open | VPC + ufw allowlists only |
| Fewer than 3 authenticated current-committee records | Grace (= Open) | VPC + ufw allowlists only |
| `snapshot_max_age_secs` lease not renewed [I] | expected to leave Closed | VPC + ufw allowlists only |

How each node reaches Closed:

- Genesis validators dial each other directly (their VPC rules admit each other), so each holds the other three records on first connect.
- [I] Node 5 cannot reach any validator before staging, so it must fetch the genesis validators' records from the sentries. validator-i pushed its record to sentry-i on first connect, and node 5 connects to every sentry. If node 5 reports `admission_mode` = 2 before the join, the record-through-sentry path works, which is the same path the validators depend on at N+2.
- Sentries stay Open by configuration.

Why node 5's record has to sit on every sentry: a Closed validator queries the DHT only through peers it admits, which are its own sentry and its window validators. Before N+2 node 5 is in nobody's window and the validators' firewalls drop it, so the only copy validator-i can reach is the one on sentry-i. Node 5 lists all five sentries as `bootstrap_peers`, so it connects to each and pushes its record there.

Network-config shapes for L2-B. The keys are the ones the design names; the exact schema and the field that selects Closed or Open come from telcoin-network `3f9b0709c`, and L2-B owns them.

```yaml
# validator-1-devnet (renderer role: validator)
admission: closed                    # [I] key name illustrative
committee_peers: <the 4 genesis validators, primary + workers>
trusted_nodes:
  - primary: <sentry-1 primary PeerId + multiaddr>
    workers: { 0: <sentry-1 worker-0 PeerId + multiaddr> }
# bootstrap_peers omitted: committee.yaml bootstrap_servers (the 4 genesis validators) applies
```

```yaml
# sentry-1-devnet (renderer role: sentry)
admission: open                      # [I] key name illustrative
committee_peers: <the 4 genesis validators>
trusted_nodes:
  - <validator-1 primary + workers>
bootstrap_peers:                     # replaces bootstrap_servers wholesale
  - <validator-1>
  - <sentry-2> <sentry-3> <sentry-4> <sentry-5>
```

```yaml
# observer-5-devnet (renderer role: joiner)
admission: closed                    # [I] key name illustrative
committee_peers: <the 4 genesis validators>
trusted_nodes:
  - <sentry-5 primary + workers>
bootstrap_peers:
  - <sentry-1> <sentry-2> <sentry-3> <sentry-4> <sentry-5>
```

The renderer needs every sentry's and node 5's public node info (PeerIds, multiaddrs), so keygen on all 10 nodes runs before the render. Only the 4 genesis validators' `node-info.yaml` files go into `genesis/validators/`.

## 5. Firewall matrix

Both layers enforce the same allowlists. The VPC layer drops traffic before it reaches the VM; ufw is the second layer and the one that still holds if a VPC rule is wrong. P2P ports are `DEFAULT_PRIMARY_UDP_PORT` 49590 and `DEFAULT_WORKER_UDP_PORT` 49594. Every "validator-j" or "sentry-j" source below means that VM's internal and external /32 (GCP one-to-one NAT preserves the external source IP, and the listeners bind the internal one).

### 5.1 VPC layer (setup-firewall.sh)

Rule names are proposals for L2-C. Existing rules that change only their target are marked "retargeted".

| Rule | Dir | Action | Ports | Sources or destinations | Target tag | Priority |
|---|---|---|---|---|---|---|
| `devnet-validator-<i>-allow-p2p` (i = 1..5) | IN | ALLOW | udp:49590,49594 | the other validators + sentry-i (lists in 5.3) | `validator-<i>` | 1000 |
| `devnet-validator-deny-internal-p2p` | IN | DENY | udp:49590,49594 | 10.128.0.0/9 | `validator` | 1050 |
| `devnet-sentry-allow-consensus` | IN | ALLOW | udp:49590,49594 | 0.0.0.0/0 | `sentry` | 1000 |
| `devnet-allow-consensus-egress` (retargeted) | EG | ALLOW | udp:49590,49594 | all validators + all sentries | `validator` | 1000 |
| `devnet-deny-consensus-egress` (retargeted) | EG | DENY | udp:49590,49594 | 0.0.0.0/0 | `validator` | 1100 |
| `devnet-validator-<i>-allow-rpc` | IN | ALLOW | tcp:443 | sentry-i | `validator-<i>` | 1000 |
| `devnet-validator-allow-acme` [I] | IN | ALLOW | tcp:80 | 0.0.0.0/0 | `validator` | 1000 |
| `devnet-allow-web` (retargeted) | IN | ALLOW | tcp:80,443 | 0.0.0.0/0 | `sentry` | 1000 |
| `devnet-allow-health-check` (retargeted) | IN | ALLOW | tcp:43174 | `GOOGLE_HC_RANGES` | `sentry` | 1000 |
| `devnet-allow-healthcheck-from-kuma` | IN | ALLOW | tcp:43174 | `HEALTHCHECK_MONITOR_SRC` | `validator`, `sentry` | 1000 |
| existing IAP SSH rule (unchanged) | IN | ALLOW | tcp:22 | 35.235.240.0/20 | all nodes | as today |
| `default-allow-internal` (GCP default, untouched) | IN | ALLOW | all | 10.128.0.0/9 | all | 65534 |

Rationale:

- The 1050 deny exists because `default-allow-internal` (65534) would otherwise let any VM in the project, txgen and obs included, reach a validator's p2p ports. The per-validator allows at 1000 win over the deny, so internal /32s of listed peers still pass.
- The egress deny at 1100 targets validators only. Sentries are Open and keep the implied allow-all egress.
- The design lists node 5 and sentry-5 among the rules staged at the join. For egress that matters only if L2-C keeps them out of the initial destination list; including them from the start is simpler and admits nothing, because ingress and admission still gate the traffic [I].
- Validators keep tcp:80 open to the world [I] because Caddy needs the Let's Encrypt http-01 challenge for `nodeN.devnet.telcoin.network` (the probe IPs are unpublished), and the forward path in section 6 needs a valid certificate on 443.
- LB health checks move to sentries only, because only sentries back `devnet-rpc-backend`.

### 5.2 Host layer (devnet-firewall.sh driving firewall-setup.sh)

| Node | firewall-setup.sh invocation | P2P sources | Also allowed by `--enable` |
|---|---|---|---|
| validator-1..4 | `--json --enable --p2p-from <list>` | the list in 5.3 | SSH, the WireGuard overlay (10.100.0.0/16 today, which covers the 10.100.9.0/24 admin range), the Kuma monitor |
| observer-5-devnet | `--json --enable --p2p-from <list>` | sentry-5 before staging [I]; validators 1-4 added by `--stage-joiner` | same |
| sentry-1..5 | `--json --enable --p2p-anywhere` | any | same, plus `TN_LB_HC_RANGES` (LB health checks; validators no longer need it [I]) |

Changes to `devnet-firewall.sh`:

- Drop the default `--port <p> on` pass. firewall-setup.sh refuses it once a `--p2p-from` list exists.
- After `--enable`, read `--json --status` and assert the p2p sources equal the computed list for that node (validators, node 5) or show "anywhere" (sentries).
- Keep the lockout-safe order: one node at a time, open a new SSH session after each, abort on the first failure.
- Add `--stage-joiner <node>` (section 7), which updates both layers.

### 5.3 Per-node p2p source lists

| Node | P2P sources (int + ext /32 each) | tcp:443 sources |
|---|---|---|
| validator-1-devnet | validator-2, validator-3, validator-4, sentry-1; plus observer-5 after staging | sentry-1 |
| validator-2-devnet | validator-1, validator-3, validator-4, sentry-2; plus observer-5 after staging | sentry-2 |
| validator-3-devnet | validator-1, validator-2, validator-4, sentry-3; plus observer-5 after staging | sentry-3 |
| validator-4-devnet | validator-1, validator-2, validator-3, sentry-4; plus observer-5 after staging | sentry-4 |
| observer-5-devnet | sentry-5 [I]; plus validator-1..4 after staging | sentry-5 |
| sentry-1..5 | 0.0.0.0/0 | 0.0.0.0/0 |

Rules for a validator that rotates out of the committee stay in place: it remains "previous" for one epoch, and with 5 eligible validators for 4 seats every validator is in the window at some point. After the join, the static allowlist on every validator is therefore the full set of 5 validators plus its own sentry.

Command shapes:

```bash
# VPC layer: idempotent describe -> create-or-update, as today
./setup-firewall.sh

# Host layer: lockout-safe, one node at a time, SSH re-verified after each
./devnet-firewall.sh --enable
#   validator-1-devnet: sudo firewall-setup.sh --json --enable --p2p-from <v2,v3,v4,s1 int+ext /32>
#   sentry-1-devnet:    sudo env TN_LB_HC_RANGES=<GOOGLE_HC_RANGES> firewall-setup.sh --json --enable --p2p-anywhere
#   then:               sudo firewall-setup.sh --json --status   # assert p2p sources == computed list

# Join (section 7): both layers, validators 1-4 and node 5
./devnet-firewall.sh --stage-joiner node5
```

## 6. RPC path

Public RPC terminates on sentries. Validators serve RPC only to their own sentry, which forwards transactions to them.

```text
txgen VM / Safe tooling (RPC_URL)
  |  HTTPS
  v
rpc.devnet.telcoin.network  (devnet-rpc-fr on devnet-rpc-ip, devnet-rpc-https-proxy, devnet-rpc-urlmap)
  |  devnet-rpc-backend: zonal unmanaged groups for sentry-1..5 only, health check devnet-rpc-hc on tcp:43174
  v
sentry-k  Caddy :80/:443  ->  reth RPC on loopback 8545
  |  reads are served from sentry-k's own synced state
  |  eth_sendRawTransaction is not gossiped: sentry-k forwards it over JSON-RPC
  |  to the rpc URL in a validator's worker record
  v
validator-i  Caddy :443 (VPC: sentry-i only)  ->  worker transaction pool  ->  batch
```

Configuration:

- Each validator runs keygen with `--rpc-http https://nodeN.devnet.telcoin.network`, its own Caddy, so the URL lands in its worker record.
- tcp:443 on validator-i is open at the VPC only to sentry-i. tcp:80 stays open for ACME (section 5.1).
- The load balancer's backends are the sentries' zonal unmanaged groups. Validators' groups leave `devnet-rpc-backend`.
- DNS A records, all manual: `node1..node5` point at the validators' static IPs (as today), `sentry1..sentry5` point at the sentries' static IPs (new), `rpc.devnet.telcoin.network` points at `devnet-rpc-ip` (unchanged).
- [I] Sentries need no advertised RPC URL: transactions are forwarded to validators, never to observers.

The design routes each forward to the sentry's own ("owning") validator. [I] Which worker URL a sentry forwards to is chosen by the node, not by network-config. If the node picks any committee member's URL, sentry-k will reach validators other than its own, and the 443 rule on every validator must list all sentries instead of one. Confirm this at `3f9b0709c` before L2-C fixes the 443 sources (section 11).

[I] The rehearsal's own governance transactions (mint through the Safe, stake, `activate()`) go to `RPC_URL`, which is `rpc.devnet.telcoin.network`, so the join rehearsal also exercises this path.

[I] With 443 on validators restricted to their sentry, the admin dashboards at `admin.node1..4` are no longer reachable from the public internet. They stay reachable over the WireGuard overlay if the operator resolves `admin.nodeN` to the node's overlay address: overlay traffic arrives on the tunnel interface, never crosses a VPC rule, and ufw already admits 10.100.0.0/16. L2-F decides whether that is acceptable or whether 443 also admits the admin range.

## 7. Join rehearsal: adding a 5th validator

This is the written procedure for "add a 5th validator". Node 5 and sentry-5 are deployed with the rest of the fleet, but node 5 starts outside the committee and outside every validator's allowlist.

Before epoch N:

1. Mint node 5's validator NFT through the governance Safe (common mint toolkit, `RPC_URL`).
2. Stake for node 5's execution address (`devnet-stake-node5.sh`; the key lives in `NODE5_VALIDATOR_PK_SECRET`).
3. Let node 5 sync through the sentries. They are the only peers its firewall and admission allow.

| Epoch | Chain and registry | Operator | Validators 1-4 | Node 5 and sentry-5 | Observe and record |
|---|---|---|---|---|---|
| before N | NFT minted, stake recorded | mint, stake; confirm node 5 is at head | unchanged; node 5 dropped by the VPC and denied by admission | node 5 Closed, syncing from sentry-1..5, its record pushed to every sentry on first connect | node 5 head lag; node 5 `admission_mode` [I expect 2]; node 5's record present on each sentry |
| N | `activate()` sets PendingActivation, `activationEpoch` = N+1 | send `activate()` | no change | still outside the committee | tx hash, block, epoch N |
| N+1 | node 5 eligible; the committee for N+3 is drawn | call `getCommitteeValidators(N+3)`; if node 5 is listed, run `./devnet-firewall.sh --stage-joiner node5` (VPC + ufw, validators 1-4 and node 5); optionally add node 5 to validators' `trusted_nodes` | allowlists now include node 5; admission still denies it (not in any window yet) | allowlist now includes validators 1-4 | `getCommitteeValidators(N+3)` output; firewall diff; wall time from draw to staging done |
| N+2 | node 5 is "next" in every node's window | watch | each validator resolves node 5's record through its own sentry and dials it directly; `admission_fallback` dips, then returns to 0 | admitted by validators; direct connections on every port | per validator: how long `admission_fallback` stays off 0, time of first direct connection |
| N+3 | node 5 CvvActive, seated | watch | committee of 4 includes node 5; one genesis validator sits out and stays "previous" through N+4 | votes, certificates, batches | node 5 in certificates; no stall at the boundary; base fee step |
| N+4 onward | rotation continues | keep every rule | rotated-out validators stay in the allowlist | | committee per epoch; node 5 seat count |

Notes:

- If `getCommitteeValidators(N+3)` does not list node 5, nothing is staged yet. Repeat the check each epoch (N+2 for N+4, and so on) and shift the rest of the table by one epoch per miss.
- The operator has one epoch, N+1, to finish staging before node 5 becomes "next". [I] Staging earlier (right after `activate()` in epoch N) is harmless, because an allowlisted peer outside the window is still denied by admission. If the devnet epoch is short, stage in epoch N.
- The optional `trusted_nodes` entry for node 5 on validators 1-4 avoids the `admission_fallback` dip at N+2. It is a permanent grant, so the rehearsal runs without it first to measure the dip.
- `--stage-joiner node5` adds node 5's /32s to `devnet-validator-<i>-allow-p2p` and to ufw `--p2p-from` on validators 1-4, adds node 5 and sentry-5 to the egress allow destinations if L2-C holds them back from the initial list, and installs validators 1-4 in node 5's own ingress list. [I] The staged state must be recorded in `config.sh` (for example `STAGED_JOINERS=("node5")`) so that a later plain `./setup-firewall.sh` or `./devnet-firewall.sh --enable` does not drop node 5 again.

## 8. Release signing: option B and its fallback

Option B, chosen for fidelity: tn-node-deployment PR 13, "devnet release channel".

- Opt-in `--release-tag <x>-devnet` on devnet. The node resolves a GPG-signed `SHA256SUMS` and `IMAGE_DIGEST` from an operator-supplied base URL, verifies them with `gpgv` against an operator-supplied key directory, and installs the digest the signed sums name.
- Chain-config pins come from the signed sums. Devnet has no built-in pins, so this is a documented deviation from mainnet, where the pins ship in the release itself.
- Without the flag, devnet behaves as PR 12 does today: digest plus repository allow-list, release tags refused.
- What this buys: devnet operators run the same `gpgv` verification step mainnet operators run, against a devnet key instead of `lib/release-keys/*.asc`.

Command shape (flag names other than `--release-tag` are placeholders [I]; PR 13 fixes them and the entry point):

```bash
sudo ./setup-node.sh ... \
  --release-tag v<x>-devnet \
  --release-base-url <operator base URL holding SHA256SUMS, SHA256SUMS.asc, IMAGE_DIGEST> \
  --release-key-dir <directory of devnet release public keys>
```

Constraints for the PR 13 review:

- The devnet path must not weaken the mainnet or testnet path. An operator-supplied key directory or base URL is refused outside devnet.
- The key directory holds public keys only. The devnet signing key never lands on a node.
- A signature that fails to verify stops the install. There is no fallback to the unsigned digest path inside one run.

Fallback, if PR 13 is declined: reuse launch 1's laptop-signed release (`devnet-release-sign.sh`, `docs/release-signing-ceremony.md`). [I] In that model nodes keep the PR 12 digest check and the operator checks the signature before deploy, so the node itself never runs `gpgv`; confirm against `docs/release-signing-ceremony.md`.

## 9. Work units and review gates

Each unit is one opus agent with a disjoint file set and its own checkpoint under `tasks/`.

| Unit | Deliverable | Files (repo) | Depends on |
|---|---|---|---|
| L2-A | Config model: arrays appended at indices 5..9, `SENTRY_OF`, `NODE_ROLES` gains "sentry", LB backend roles, per-node `INSTANCE_TAGS`; reserve 5 sentry static IPs | `config.sh` (DG); `common/create-instances.sh` per-node tags (common PR) | launch 1 merged |
| L2-B | network-config renderer with roles validator, sentry, joiner, matching section 4 | the renderer under `genesis/network-config/` (DG) | L2-A |
| L2-C | `setup-firewall.sh` and `devnet-firewall.sh` rewrite, matching section 5 | `setup-firewall.sh`, `devnet-firewall.sh` (DG) | L2-A |
| L2-D | Join runbook (section 7) and `--stage-joiner` | runbook under `tasks/` or `docs/`; `--stage-joiner` code | L2-C |
| L2-E | tn-node-deployment PR 13, devnet release channel (section 8) | tn-node-deployment | none |
| L2-F | `dns.sh`, observability and dashboards for 10 nodes; manual A records for sentries; LB backends = sentries | `dns.sh`, obs and dashboard config (DG, common) | L2-A |
| L2-G | Reviews, second teardown and deploy, verification (section 10) | none (operates the fleet) | all |

`--stage-joiner` lives in `devnet-firewall.sh`, which L2-C rewrites. To keep file sets disjoint, either L2-D starts after L2-C lands, or L2-D puts the staging logic in a helper that `devnet-firewall.sh` sources.

Order:

```text
launch 1 live + reviewed
  -> L2-A (config model, common PR)
       -> L2-B, L2-C, L2-F in parallel      L2-E in parallel from the start
       -> L2-D after L2-C
  -> L2-G gates G1-G5
  -> second teardown + deploy
  -> verification, then the join rehearsal
```

Review gates (L2-G):

| Gate | What is checked | Pass condition |
|---|---|---|
| G0 | Launch 1 | live, reviewed, baseline numbers recorded (base fee per epoch, RPC submit-to-inclusion latency) |
| G1 | Config model | all node arrays have 10 entries; indices 5..9 are sentries; `SENTRY_OF` and `INSTANCE_TAGS` agree; node 2 in us-south1 |
| G2 | Admission shapes | rendered network-config for all 10 nodes matches section 4 row by row; `committee_peers` = 4 genesis validators everywhere; only genesis validators in `genesis/validators/` |
| G3 | Firewall matrices | `setup-firewall.sh` and `devnet-firewall.sh` dry-run output matches section 5 rule by rule and node by node; lockout-safe order kept; `lockdown-firewall-gcp.sh` not called anywhere |
| G4 | Secrets | 5 new BLS keys and passphrases (sentries) stored like the validators'; no network secret key persisted anywhere; PR 13 key directory holds public keys only; node 5 execution key only in `NODE5_VALIDATOR_PK_SECRET` |
| G5 | Release channel | PR 13 reviewed and merged, or the fallback chosen and written down |

## 10. Verification checklist

Record every number in the launch 2 review section of `tasks/todo.md`.

| # | Check | How | Expected | Record |
|---|---|---|---|---|
| V1 | Validators Closed | read `admission_mode` from each validator's metrics after its first epoch-start window | 2 on validator-1..4 | value per node; seconds from process start to Closed |
| V2 | Sentries Open | same metric on sentry-1..5 | the Open value | value per node |
| V3 | Node 5 Closed before the join [I] | same metric on observer-5-devnet | 2, via records fetched through sentries | value; time to Closed |
| V4 | Validator p2p dropped from inside the VPC | `nc -u` probe from the txgen VM to a validator's 49590, with logging on the 1050 deny | refused; deny-rule log shows the hit | probe output; log hit count |
| V5 | Sentry p2p reachable | same probe to a sentry's 49590 | accepted | probe output |
| V6 | Open peer serves records | `tn node record` against a sentry; the same against a validator | sentry returns the record; validator refuses | returned fields (role, multiaddrs, rpc) |
| V7 | Forward path | send a tx to `rpc.devnet.telcoin.network` | included | tx hash, block, serving sentry, receiving validator (Caddy log source IP), submit-to-inclusion ms |
| V8 | Firewall state | `gcloud compute firewall-rules list` and `firewall-setup.sh --json --status` per node | matches section 5 | rule count; any mismatch |
| V9 | LB backends | backend health for `devnet-rpc-backend` | 5 sentries healthy, no validator | healthy count |
| V10 | Peer sets | connected peers per validator | window validators + own sentry only | peer count per validator |
| V11 | Join | section 7 table | node 5 CvvActive at N+3 (or later, after missed draws) | N; draws missed; `admission_fallback` excursion per validator; first epoch node 5 signs a certificate |
| V12 | Rotation | committee per epoch for at least 10 epochs after N+3 [I count] | node 5 seated in some epochs, every validator out in some | committee per epoch; any stall |
| V13 | Base fee | the per-epoch base fee check from launch 1 (commit `efa3db9`) | base fee steps each epoch as in launch 1 | base fee per epoch, compared with the G0 baseline |
| V14 | Lease | `snapshot_max_age_secs` and its renewals | renews about every lease/3 | configured value; observed renewal interval |

Probe shapes for V4 to V6:

```bash
# on the txgen VM (internal source in 10.128.0.0/9, so the 1050 deny applies); argument shapes illustrative
gcloud compute firewall-rules update devnet-validator-deny-internal-p2p --enable-logging
nc -u -z -w 3 <validator-1 internal IP> 49590; echo "exit=$?"
nc -u -z -w 3 <sentry-1 internal IP> 49590;    echo "exit=$?"
tn node record <sentry-1 multiaddr>             # works
tn node record <validator-1 multiaddr>          # refused or times out
```

[I] A UDP `nc` result is weak evidence on its own: a dropped datagram and a QUIC listener that ignores a non-QUIC packet both look like silence. The deny-rule log hit (V4) and the `tn node record` contrast (V6) are the decisive signals.

## 11. Open questions and risks

| # | Item | Impact | Proposed handling |
|---|---|---|---|
| R1 | Cost of 5 extra VMs (`e2-custom-4-8192`), 5 more static IPs, and sentry sync and RPC egress | node VM count doubles (5 to 10); sentry-5 is the optional part | keep sentry-5 for the "arrives with its sentry" rehearsal; L2-G records the monthly delta after a week and decides whether sentry-5 stays |
| R2 | Record replication is off: a record lives only where its owner connected | if sentry-i restarts or misses node 5's connect, validator-i cannot resolve node 5 at N+2 | before N+2, confirm node 5's record on all 5 sentries (V3, section 7 "before N" row); keep the optional `trusted_nodes` entry ready as the fallback |
| R3 | Node 5's discovery depends on the sentries | [I] one validator unable to admit node 5 still leaves node 5 a quorum path; two leave node 5 effectively absent, which spends the committee's only fault slot (f = 1 of 4) | same as R2; do not restart sentries between N+1 and N+3 |
| R4 | Node 5's permanent grants include every sentry (`bootstrap_peers`) | a Closed validator admitting 5 Open nodes is wider than the one-sentry pattern | accept for the rehearsal; [I] after node 5 is seated its records reach the validators directly, so its `bootstrap_peers` could shrink to sentry-5; decide after V11 |
| R5 | Forward target selection (section 6) | if sentries forward to any committee validator, a 443 rule naming only the own sentry breaks transaction ingress | confirm in code at `3f9b0709c` before L2-C; if needed, list all sentries in every `devnet-validator-<i>-allow-rpc` |
| R6 | `default-allow-internal` also admits tcp:443 (and everything else) from any VM in the project | the "443 only from own sentry" rule does not hold for internal sources | [I] L2-C checks what `obs-devnet` and txgen reach on validators, then decides whether the 1050 deny also covers tcp:443 |
| R7 | PR 13 scope | it touches the release verification code mainnet relies on | review gate G5; the devnet-only flags must be refused off devnet; fallback is launch 1's laptop-signed release |
| R8 | Every process starts Open, and Grace behaves as Open | at boot and after a quorum loss, firewalls are the only filter | the allowlists are complete before any node starts; V1 records time to Closed |
| R9 | `committee_peers` on sentries names validators they cannot reach | [I] repeated dial failures and backoff noise in sentry logs | accept; note it in the runbook so it is not mistaken for a fault |
| R10 | A sentry is a single point of ingress for its validator | DHT, sync and RPC for validator-i stop if sentry-i is down; consensus does not (direct dials) | accept; V10 shows consensus peers do not depend on the sentry |
| R11 | Staged joiner state must survive reconciles | a later `./setup-firewall.sh` could drop node 5 from the allowlists | L2-D records it in `config.sh` (section 7) |
| R12 | Sentry IP change | a new IP (region move, released address) invalidates its validator's `trusted_nodes` multiaddr, the VPC lists and DNS | treat sentry static IPs like validator IPs: reserve once, never release; re-render and restart the paired validator if one changes |
| R13 | Admin dashboards behind the 443 restriction | `admin.node1..4` unreachable from the internet | reach them over the overlay, or add the admin range to the 443 rule (L2-F) |

Open questions for the operator:

1. Keep sentry-5 (R1)?
2. Accept PR 13 into tn-node-deployment, or use the fallback (R7)?
3. Run the join with or without the optional `trusted_nodes` entry first (section 7)? The plan says without, to measure the dip.
4. How many post-join epochs count as a passing rotation test (V12)?
