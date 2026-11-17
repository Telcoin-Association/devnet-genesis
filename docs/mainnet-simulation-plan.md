# Launch 2: the devnet as a mainnet rehearsal

This design supersedes the sentry-node design this file described before (one sentry per
validator behind the Google load balancer); none of that design was built.

Status: built on branch `l2/launch-2` (2026-11-17), rehearsed locally, deployed with
`tasks/runbook-l2-2026-11-17.md` in the main tree.
Built on: telcoin-network `5533ff73a` (`origin/main`, no `faucet` feature), tn-node-deployment
branch `worker-gateway` (scripts 2.2.0), image `v0.3.0-devnet`.
Interface: `tasks/l2-contract.md`. Challenges met on the way: `tasks/challenges-l2.md`.

## 1. Purpose

Mainnet launches about two weeks after this rehearsal. Launch 2 rebuilds the devnet in the shape
mainnet will have and deploys it with tn-node-deployment's own scripts, so that the problems an
operator will hit show up now. Every friction with those scripts is written down as a challenge.

The shape: validators in a closed network, a worker gateway in front of each validator's
JSON-RPC, node records advertising the gateway, a P2P allowlist on each validator that follows
the chain, one public RPC node, and a fifth node that stakes after genesis and rotates into later
committees.

## 2. Topology

| VM | Role | Admission | Public edge | Gateway | P2P filter on the host |
|---|---|---|---|---|---|
| validator-1..3-devnet | genesis validators | Closed, trusts rpc-6 | Caddy, `nodeN.devnet` and `admin.nodeN.devnet` | same host: loopback 8655 -> node 127.0.0.1:8545 | committee allowlist |
| validator-4-devnet | genesis validator | Closed, trusts rpc-6 | none | on gateway-4; node RPC and health port admit gateway-4 only | committee allowlist |
| gateway-4-devnet | gateway only, no node, no keys | n/a | Caddy, `node4.devnet` | standalone -> validator-4's internal IP | none (no P2P) |
| observer-5-devnet | node 5: syncs, then stakes | Closed, trusts rpc-6 | Caddy, `node5.devnet` and `admin.node5.devnet` | same host | optional before staking |
| rpc-6-devnet | public RPC, never stakes | Open | native public RPC, `rpc.devnet` (https and wss), `admin.node6.devnet` | none | open to any source |

The obs and txgen VMs stay as they were. The transaction generator posts to
`https://rpc.devnet.telcoin.network`. The Google load balancer is gone; `rpc.devnet` is an A
record to rpc-6. Each validator's node record advertises `https://nodeN.devnet.telcoin.network/`
and no WebSocket URL; rpc-6 advertises its own edge.

In `config.sh` the fleet is seven parallel array entries: 0-3 the validators, 4 node 5, 5 rpc-6,
6 gateway-4. Node 5 keeps index 4, so every script that knew it by index still finds it; new code
finds hosts by role (`tn_indices_by_role`, `tn_node_indices`, `tn_gateway_host_index`).

## 3. Why each piece exists

### Closed validators
A validator admits only the committee, the eligible pool and the nodes it trusts. Here it trusts
exactly one node, rpc-6. A peer that is not admitted completes the QUIC handshake and is dropped
without a log line on either side (challenge 33), so node 5, before it stakes, gets nothing from
the validators and syncs only from rpc-6. That is how a new mainnet operator will join.

### A gateway in front of each validator's RPC
`worker-gateway` is an HTTP/1 POST proxy. Transaction submissions go to the validator's worker;
reads and every `tn_*`, `debug_*`, `trace_*` and `admin_*` call go to rpc-6
(`--redirect-queries https://rpc.devnet.telcoin.network`). The validator's own RPC binds
127.0.0.1, so nothing public reaches it except through the gateway, and a `tn_nodeMode` sent to
`https://nodeN` is answered by rpc-6, not by the validator. Caddy terminates TLS, sets
`X-Forwarded-For` and answers a WebSocket upgrade with 405; the gateway trusts 127.0.0.1/32 as
its proxy, so its per-client limits (100 requests/s, burst 200, 32 connections) apply to the real
client and not to Caddy. Readiness is the node's `/health/workers`; the public probe is
`/ready/any`. The installer (`setup-gateway.sh`) runs the gateway image by digest under its own
unit, `--read-only`, `--cap-drop ALL`, uid 1101, and works with the node stopped.

### Node records advertise the gateway
A node outside the committee does not process transactions itself: it forwards each submission to
the URLs in the current committee's node records (`tn-reth/src/forward.rs`: 64 tasks, public
targets only, a non-2xx answer sidelines that endpoint for 30 s). Keygen writes each validator's
gateway URL (`--rpc-http https://nodeN.devnet.telcoin.network/`, no `--rpc-ws`), so forwarded
transactions arrive through the gateways, the same way they will on mainnet.

### rpc-6, the public RPC node and open hub
rpc-6 has Open admission, and every validator and node 5 list it as trusted. It is the only node
the public talks to: it answers every read (including `tn_*`), pools submissions and forwards them
through the record URLs. It runs record forwarding, not `--forward-txs`, which bypasses the records
(challenge 9). It is also node 5's only peer before node 5 stakes. Its edge is
tn-node-deployment's native public-RPC option (`install-caddy.sh --phase rpc-enable`), which
replaces the Google load balancer.

### The committee P2P allowlist, with the VPC open
The VPC allows UDP 49590/49594 from any source to every node host. The real filter is on each
validator: an nftables table `inet tn_p2p_allow` that `tn-p2p-allow-sync` (v0.1.1, gpgv-checked)
refreshes every 5 minutes from the node's own `tn_admissionSnapshot`. The set holds the eligible
pool, the committees of epochs E-1 to E+2, the trusted and bootstrap peers, and a floor from
`committee.yaml`; the tool keeps the last good set when the node cannot answer. Mainnet operators
cannot keep /32 lists of each other's addresses in sync by hand; with this, the chain decides who
may reach a validator, and a validator that stakes appears in everyone's set at their next sync.
rpc-6 stays open to any source (`--p2p-anywhere`). Launch 1 used VPC /32 rules for consensus; they
are deleted.

### One validator with its gateway on another host
Validator 4's gateway runs on its own VM, gateway-4, as on mainnet where an operator keeps the
public edge off the validator. `node4.devnet` points at gateway-4. Validator 4's RPC cannot bind
a private address only (local readers hard-code loopback, challenge 4), so it binds 0.0.0.0 for
RPC and health, guarded twice: ufw admits gateway-4's internal IP only (`firewall-setup.sh
--gateway-from`, persisted, survives `--reset`), and the VPC rule `devnet-allow-gateway-upstream`
admits tcp 8545 and 43174 from gateway-4's internal /32 only.

## 4. Admission per role

| Role | `--admission` | trusted nodes | bootstrap peers | `committee_peers` |
|---|---|---|---|---|
| validator | closed | rpc-6 | the four genesis validators | the four genesis validators |
| observer (node 5) | closed | rpc-6 | the four genesis validators | the four genesis validators |
| rpc | open | (none) | the four genesis validators | the four genesis validators |

devnet-genesis renders only the input maps (`devnet-network-config.py maps`, `/ip4` addresses,
each BLS key as a plain `key:` line, because tn-node-deployment's renderer refuses YAML complex
keys, challenge 32). `setup-node.sh --admission … --trusted-nodes <file> --bootstrap-peers <file>`
writes the node's `network-config`; devnet-genesis then checks that file by content
(`validate --native`). At epoch 0 a non-empty `committee_peers` must list every committee member,
or the node exits 1. `TN_ADMISSION_VIA=devnet` keeps the old devnet-rendered path for the
benchmark, which also keeps its own scripts pin, the launch-1 image and no gateways.

## 5. Deploy order and why

| # | Step | # | Step |
|---|---|---|---|
| 1 | static IPs | 11 | host ufw on every VM |
| 2 | VMs | 12 | observability, on stopped nodes |
| 3 | boot wait | 13 | gateway installs, nodes still stopped |
| 4 | DNS pause | 14 | one coordinated start |
| 5 | keygen (records advertise the gateway) | 15 | rpc-6 public edge |
| 6 | genesis + release manifest | 16 | post-checks |
| 7 | admission maps | 17 | dashboards |
| 8 | VPC rules | 18 | contracts |
| 9 | obs VM | 19 | transaction generator |
| 10 | finalize, stage only (signature gate first) | 20 | committee allowlist, one validator at a time |

The order follows from four facts.

Genesis validators that start minutes apart lose the late one for a whole epoch (lesson
2026-11-02). So every node is finalized and left stopped and enabled, everything that would
restart a node is installed while it is stopped, and step 14 starts all six at one due time read
on each node's own clock (60 s lead, a warning above 10 s of spread). tn-node-deployment has no
`--no-start` (challenge 15), and its observability installer starts a stopped node whenever it
adds a flag (challenge 37), so the drivers stage by start-then-stop: each node runs alone for a
moment, never with enough peers to form a quorum.

The release is signed before anything is staged. `SHA256SUMS` names five files (the node and
gateway digests and the three chain configs) and is signed on the YubiKey; step 10 exits 3
(`RELEASE_SIG_PENDING`) until it is.

rpc-6's public edge restarts rpc-6, and a restart would start a stopped node, so step 15 comes
after the start and refuses while rpc-6 is not active. Node 5 then loses its only peer and
reconnects after its trusted-dial backoff (about 45 s), which the post-checks wait out.

The committee allowlist goes last and one validator at a time: a wrong set cuts a validator off,
and with four validators one more fault stalls the chain. After each host the driver requires
that host to hold a block made after its filter went in, so it runs once the transaction
generator makes blocks (an idle chain's head moves only at epoch closes). Node 5 is turned on only
by name, and only while rpc-6 is up.

## 6. What the rehearsals showed

- RH0 (local docker, real image, tn-node-deployment's own renderer): the admission table of §4
  works as written. Node 5 syncs only through rpc-6; a `committee_peers` missing a member stops a
  validator at epoch 0; a validator's snapshot is authoritative 3.7 s after a fresh start and
  1.2 s after a restart; while rpc-6 is down node 5's snapshot is Grace / Unresolved; the node
  image has no curl, so every probe runs on the host.
- RH3 (the real genesis and admission scripts, unedited): a working six-node chain. Validators
  CvvActive, rpc-6 Observer with Open admission, node 5 through rpc-6 only, an epoch closed with
  equal heads. The genesis Safe post-processing still holds on the new Safe v1.4.1 suite.
- RH5 (transaction path with the real gateway image): `cast send` to the RPC node returned a
  receipt with status 1 in 1.29 s, through node 1's record URL, gateway 1 and node 1's worker. 20
  sequential transfers 20/20; a 400-transfer burst 400/400 in 4.65 s with one 429; a stopped
  gateway costs one 3-6 s delay per 30 s and loses nothing.
- tn-node-deployment: the full suite (79 test files) passes on the branch; Caddy 2.8.4 and 2.11.9
  accept the generated gateway block; on a real ufw, `--ssh-from` on `main` could remove the SSH
  rule when a source was re-entered in another spelling (fixed in the branch for all three lists).
- Steps 1-8 of the deploy and step 10's signature gate (both ways) ran against fake `gcloud`,
  `ssh` and `scp` (`tasks/l2-shim`) from a fresh fake cloud, with every flag checked against the
  real parsers and no call reaching a real binary.

## 7. Known limits of this design

- The gateway image is not published by telcoin-network, CI never builds it, and `--version`
  carries no commit (challenges 2, 29). The devnet pins a digest it built; mainnet refuses to
  install a gateway until a signed scripts release pins one.
- With record forwarding the gateway is the only check in front of a validator's worker; the
  upstream public-RPC guidance (`--forward-txs`, `--sanitize-txs`) bypasses the records (9).
- One RPC node is one client to every gateway: 100 requests/s, burst 200, 32 connections per
  validator. All transfers of one sender go to one validator's gateway first. A 429 sidelines that
  gateway for 30 s; the installer renders no rate-limit flag, and the forwarder does not pass on
  the original client (10, 42). RH5 drew one 429 at about 210 forwards in one second.
- A gateway that restarts answers 503 for about 11 s and is sidelined for 30 s; the RPC node's
  warning names no endpoint, so finding the validator takes the `tn_worker_submit_usable_members`
  gauge and the gateways' rejection counters (43, 44). After a 429 the gateway closes the
  keep-alive connection without `Connection: close`; whether Caddy then returns 502 to another
  client is not verified (35).
- `tn_*`, the admission snapshot included, is public on the RPC node (12).
- A joiner's record lives only on the hub until a committee node fetches it; lookup backoff can
  delay its allowlist entry by up to 30 minutes (11). The native renderer cannot express "bootstrap
  from a hub, committee peers = the genesis set" for a joiner (8).
- The standalone validator binds RPC and health on 0.0.0.0, guarded by ufw and the VPC (4).
- The node's health listener binds loopback on this image, so monitors and rules aimed at the
  health port reach nothing; external monitors use the gateway's `/ready/any` (3, 38).
- No native scrape exists for gateway metrics, nftables counters or the sync timer: Alloy takes
  one config file (13). Gateway metrics are read on the host, `127.0.0.1:9655/metrics`.
- The committee allowlist is a manual step per host with no `--json` and no wait for an
  authoritative snapshot; the devnet driver adds both (7, 23).
- `node-record-api` does not build at `5533ff73a` (28), so the advertised URL cannot be read
  from the DHT directly; the runbook checks it through the forwarding counters instead.
- The devnet fetches tn-node-deployment by commit and bypasses MANIFEST verification;
  `MIN_ADMISSION_VERSION` is still a TODO (14).
