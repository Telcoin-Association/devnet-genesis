# Verification: devnet launch 1 (the 2026-10-31 reset, relaunched 2026-11-02)

Captured 2026-11-02 from xerxes (`/home/drtnarg/coding/telcoin/devnet-genesis`) by unit V1. Every
item gives the command, the value seen and the UTC time. Read-only throughout: no node, contract or
config was changed. IAP use was capped at one ssh per node per section, with no polling loops. The
remote reads ran as script files from the session scratchpad (`.../scratchpad/V1/`).

## Header

| item | value |
|---|---|
| c1 | `b1b49be` config: v0.2.0-devnet digest, node 5 address; key + release-signing tooling; docs |
| c2 | `ee6078a` config: node 2 moves from Sydney to Dallas (us-south1-a) |
| c3 | `6807ece` genesis: v0.2.0-devnet chain, signed release manifest, per-node network-config |
| HEAD at capture | `50c920a` stake-node5: accept cast's resolved revert output; launch-1 run notes |
| image | `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:5257e768e657586a19e31308906bfacac0df95e5ca3da29a68f818f159d4a610` (tag v0.2.0-devnet, telcoin-network 3f9b0709c) |
| node scripts | tn-node-deployment `d9446f720026fa5ce8b64fce9074e56b05b3f4eb` (TN_NODE_SCRIPTS_REF) |
| chain | 32285 (0x7e1d), epoch duration 3600 s, boundaries at :33:56 |
| first quorum | 2026-11-02 15:33:56Z (validators 1-3; deploy step 8 started 15:32:30Z) |
| NODE2_IP | 34.174.181.214 (us-south1-a, Dallas) |
| head at capture | 17:44:08Z `tn --rpc https://rpc.devnet.telcoin.network status`: epoch 3, consensus 12158, height 6425 on nodes 1-4, 6424 on node 5; next boundary 18:33:56Z |

## 1. Fleet

Command: one IAP ssh per node, 17:45:06Z to 17:45:33Z, sequential, all `ssh_rc=0`:
`tn_iap_ssh_stdin <instance> <zone> < scratchpad/V1/s1-remote.sh`. The remote script (as root, read-only)
runs `systemctl is-active telcoin telcoin-alloy.service`, `systemctl is-enabled telcoin`,
`systemctl show -p NRestarts,ActiveEnterTimestamp telcoin`, `grep -E '^(NETWORK|DOCKER_IMAGE_DIGEST)=' /etc/telcoin/.node-meta`
(the grep `tn_node_meta_get` runs), `id -u telcoin`,
`tr '\0' '\n' < /proc/<pid>/environ | grep -c PASSPHRASE` over the container pid (`docker inspect -f '{{.State.Pid}}' telcoin`)
plus every `telcoin node` pid, and `ufw status verbose`. It also sends `tn_nodeMode`, `eth_blockNumber` and
`tn_latestConsensusHeader` to `127.0.0.1:8545`.

| node | time | telcoin / alloy | enabled | NRestarts, active since | NETWORK | DOCKER_IMAGE_DIGEST | telcoin uid | PASSPHRASE hits (pids) | ufw | tn_nodeMode | eth_blockNumber | consensus no. (epoch, max round) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| validator-1 (us-west2-a) | 17:45:10Z | active / active | enabled | 0, 16:47:09Z | devnet | sha256:5257e768…a610 | 999 (`/bin/false`) | 0 (24576, 24532) | active; deny in; 49590+49594/udp ALLOW (v4+v6) | CvvActive | 0x1936 = 6454 | 12254 (3, 2108) |
| validator-2 (us-south1-a) | 17:45:14Z | active / active | enabled | 0, 16:40:28Z | devnet | sha256:5257e768…a610 | 999 | 0 (22681, 22568) | same | CvvActive | 0x193e = 6462 | 12261 (3, 2122) |
| validator-3 (northamerica-northeast1-b) | 17:45:19Z | active / active | enabled | 0, 16:46:02Z | devnet | sha256:5257e768…a610 | 999 | 0 (22583, 22538) | same | CvvActive | 0x193e = 6462 | 12269 (3, 2138) |
| validator-4 (europe-west4-a) | 17:45:25Z | active / active | enabled | 0, 16:59:17Z | devnet | sha256:5257e768…a610 | 999 | 0 (23033, 22988) | same | CvvActive | 0x193e = 6462 | 12278 (3, 2156) |
| observer-5 (europe-west2-b) | 17:45:32Z | active / active | enabled | 0, 16:48:38Z | devnet | sha256:5257e768…a610 | 999 | 0 (21667, 21556) | same | Observer | 0x1944 = 6468 | 12290 (3, 2180) |

- The full digest on all 5 nodes is `sha256:5257e768e657586a19e31308906bfacac0df95e5ca3da29a68f818f159d4a610`,
  which matches config.sh `DOCKER_IMAGE`.
- Container (`docker inspect telcoin`) on all 5: running, `User` 999:987, ReadonlyRootfs true.
- ufw line, identical on all 5: `Status: active`, `Default: deny (incoming), allow (outgoing), deny (routed)`,
  and `49590/udp ALLOW IN Anywhere` plus `49594/udp ALLOW IN Anywhere` (also the v6 rules).
- Node 5 reads Observer, as expected before its first seat. Epoch 4 starts 18:33:56Z and epoch 5, node 5's first seat, starts 19:33:56Z (`tn status` at 17:44:08Z gives the next boundary as 18:33:56Z, and epochs are 3600 s). V2 re-reads it after 19:33:56Z.
- The "active since" times are the restarts from deploy step 11 and its recovery (16:40-16:59Z). NRestarts is 0
  everywhere, so systemd has not restarted any unit since then.

Finalize post-checks (deploy step 8, `logs/deploy-20261102T1532Z-from8.log` lines 418-534, run 15:32:30Z-15:44:36Z):

| node | A1 service (60 s, 7 polls) | A2 node-meta | A3 network-config | A4 logs (lines, patterns) | A5 runtime (TN_BLS_PASSPHRASE in environ) | result |
|---|---|---|---|---|---|---|
| node1 | ✓ active, enabled, NRestarts 0 | ✓ devnet, 5257e768…a610 | ✓ Closed admission, committee_peers, hostname "node1" | ✓ 4276, all 0 | ✓ tn-start-docker, RO rootfs, pinned digest, 0 | 5/5 |
| node2 | ✓ | ✓ | ✓ Closed, "node2" | ✓ 6460, all 0 | ✓ 0 | 5/5 |
| node3 | ✓ | ✓ | ✓ Closed, "node3" | ✓ 8708, all 0 | ✓ 0 | 5/5 |
| node4 | ✓ | ✓ | ✗ `no answer from validator-4-devnet (ssh rc 255)` (line 500) | ✓ 9665, all 0 | ✓ 0 | 4/5 |
| node5 | ✓ | ✓ | ✓ Closed, "node5" | ✓ 4133, all 0 | ✓ 0 | 5/5 |

- Node 4's A3 failed on a transient IAP drop. The A4 and A5 ssh calls to the same node, made right after it,
  succeeded. A3 was re-run read-only at 15:46Z: `./devnet-network-config.sh --verify node4`
  (`logs/network-config-verify-node4-20261102T1546Z.log`) gave `ok /tmp/tn-network-config.iL7S2O/node4.installed is a valid network-config for node4`
  and `all targeted nodes: verify ok.` Counting that re-check, the post-checks pass 25/25.
- The rendered sources `genesis/network-config/node{1..5}.yaml` all carry `mode: Closed` (line 2).

## 2. Consensus progress

Command: `bash scratchpad/V1/s2.sh`, public RPC only. It sends `tn_latestConsensusHeader` to
`https://node1.devnet.telcoin.network` and `eth_blockNumber` to `https://rpc.devnet.telcoin.network`
(the LB), twice, 60 s apart. Then it reads `eth_getBlockByNumber` timestamps for the head and head-200.

| sample | UTC | node 1 consensus number | epoch | max round in the commit | commit_timestamp | LB eth_blockNumber |
|---|---|---|---|---|---|---|
| s1 | 17:46:21Z | 12366 | 3 | 2332 | 1793641580 | 0x195a = 6490 |
| s2 | 17:47:21Z | 12461 | 3 | 2522 | 1793641641 | 0x1990 = 6544 |
| delta (60 s) | | +95 commits | | +190 rounds | +61 s | +54 blocks |

- Node 1 committed 95 sub-dags per minute over 190 rounds, i.e. one commit every 2 rounds.
- The LB produced 54 blocks per minute over the 60 s window. On block timestamps, blocks 6344 to 6544
  run from 17:42:35Z to 17:47:09Z: 200 blocks in 274 s, or 43.8 blocks/min.
- The section 1 probes at 17:45Z also show progress across nodes: consensus numbers 12254, 12261, 12269,
  12278 and 12290 on nodes 1-5, read 4-6 s apart. Every commit carried headers from 3-4 distinct
  authors.

## 3. Admission

Commands:
- One IAP ssh to obs-devnet (us-west2-a) at 17:48:19Z-17:48:29Z (`scratchpad/V1/s37-remote.sh`; its Loki reads came
  back empty, so §7 made its own ssh). Inside the prometheus container it runs
  `wget -qO- http://localhost:9090/api/v1/label/__name__/values | tr ',' '\n' | grep -i admission` and the
  instant query `{__name__=~".*admission.*"}`, evaluated at 1793641700.917 (17:48:20Z).
- One IAP ssh to validator-1 at 17:48:56Z (`scratchpad/V1/s3-v1-remote.sh`):
  `curl -s 127.0.0.1:9101/metrics | grep -E '^tn_network_(admission|closed_admission)'`. This is the node's
  own endpoint, before Alloy relabels it.

Metric names found on the obs Prometheus: `tn_network_admission_mode`, `tn_network_admission_fallback`,
`tn_network_admission_connected_current`, `tn_network_admission_required_current`,
`tn_network_admission_resolved_current`, `tn_network_admission_contradicted`,
`tn_network_closed_admission_denied_total{direction}` and `tn_network_source_admission_denied_total{direction,reason}`.
These match the names the runbook expected.

| node | admission_mode | admission_fallback | required | resolved | connected | contradicted | closed_admission_denied in / out |
|---|---|---|---|---|---|---|---|
| validator-1 | 2 | 0 | 3 | 4 | 3 | 0 | 0 / 0 |
| validator-2 | 2 | 0 | 3 | 4 | 3 | 0 | 180 / 149 |
| validator-3 | 2 | 0 | 3 | 4 | 3 | 0 | 160 / 163 |
| validator-4 | 2 | 0 | 3 | 4 | 3 | 0 | 126 / 138 |
| observer-5 | 2 | 0 | 3 | 4 | 1 | 0 | 0 / 0 |

- Nodes 1-4 report mode 2 (Closed) with fallback 0, as expected. Node 5 also reports Closed (2) with
  fallback 0, matching its rendered `mode: Closed`.
- `tn_network_source_admission_denied_total` is 0 for every reason and direction on all 5 nodes.
- Validator-1 read locally gives the same values for both networks: `tn_network_admission_mode{network="primary"} 2`,
  `{network="worker-0"} 2`, `admission_fallback` 0/0, required 3/3, resolved 4/4, connected 3/3,
  closed-admission denied 0 in all four directions.
- The network-config side (finalize A3, §1) reads `Closed admission, committee_peers, validator ok` on nodes 1, 2, 3 and 5,
  plus node 4 by the read-only re-verify at 15:46Z. The rendered `genesis/network-config/node{1..5}.yaml` all have
  `mode: Closed`.
- **New finding (obs label collision, not investigated further):** the node exports each admission
  gauge twice, as `network="primary"` and `network="worker-0"`. The Alloy relabel in
  `tn-node-deployment/lib/observability.sh:417-420` (`target_label = "network"`, `replacement = sys.env("TN_CHAIN")`)
  overwrites that label with `devnet`, so the two series reach Prometheus with the same label set and
  are stored as one series per node per metric. As a result, primary and worker values cannot be told
  apart centrally. Today both values are equal on validator-1, so §3 holds for both networks there.
  For nodes 2-5 the central value stands for both networks but proves only one of them.

## 4. Governance

Commands: `bash scratchpad/V1/s4.sh` at 17:47:25Z (head 6544), which runs `cast call … --rpc-url https://rpc.devnet.telcoin.network`,
and then `tn --rpc https://rpc.devnet.telcoin.network {safe 0x…07a0 | gov get-worker 0 | fees}` at 17:49:18Z.

| item | command | value |
|---|---|---|
| Safe version | `cast call 0x…07a0 'VERSION()(string)'`; `tn safe 0x…07a0` | "1.4.1"; `version: 1.4.1` |
| Safe threshold | `cast call 0x…07a0 'getThreshold()(uint256)'`; `tn safe` | 1; `threshold: 1-of-8` |
| Safe owners | `cast call 0x…07a0 'getOwners()(address[])'` | 8: 0xAee2797478Cb5EfaF1869A2e33e369421EBf520f (first), 0x2358CF87…4e65, 0x389C4bd7…034b, 0xDE5346d1…1e88, 0xf5b39446…d538, 0xDCe4Ef76…B5BA, 0xa21B09Ff…f248, 0x5b9e7050…97Fc |
| Safe nonce | `cast call 0x…07a0 'nonce()(uint256)'` | 1. It was 0 at U3c (17:15Z); the mint exec in §11 consumed nonce 0. |
| Safe modules | `tn safe` | (none) |
| Registry owner | `cast call 0x07E1…7E1 'owner()(address)'` | 0x00000000000000000000000000000000000007A0 (the Safe) |
| WorkerConfigs worker 0 | `cast call 0xFee0…FEe0 'getWorkerConfig(uint16)(uint8,uint64,uint184)' 0`; `tn gov get-worker 0` | (0, 10000000, 9): strategy 0 eip1559, target 10,000,000, base fee 9 wei (epoch 3). U3c read it as 8 at 17:15Z, in epoch 2. |
| current epoch | `cast call 0x07E1…7E1 'getCurrentEpoch()(uint32)'` | 3 |
| eligible validators / next committee size | `getEligibleValidatorCount()`, `getNextCommitteeSize()` | 5 / 4 |
| committee(2) | `getCommitteeValidators(uint32)(…[])` 2 | 0xefaacf04 (node4), 0x0033a370 (node3), 0x7489025d (node2), 0x3518b301 (node1) |
| committee(3) (current) | same, 3 | 0x0033a370 (node3), 0x3518b301 (node1), 0x7489025d (node2), 0xefaacf04 (node4); node 5 absent |
| committee(4) | same, 4 | node3, node1, node2, node4; node 5 absent |
| committee(5) | same, 5 | 0x0033a370 (node3), 0x3518b301 (node1), 0x7489025d (node2), **0xd0154a80 (node5)**. Node 4 (0xefaacf04) is drawn out of epoch 5. |

The `tn status` reading is in the header and §10: all 5 nodes report epoch 3 at 17:44:08Z.

## 5. Base fee

Command: `./devnet-basefee-check.sh --last 2`, run at 17:46:43Z-17:46:47Z (default `--rpc` = config.sh
`RPC_URL` = https://rpc.devnet.telcoin.network; expected target from `WORKER_FEE_CONFIG="0:0:10000000"`).
Exit 0.

```
rpc https://rpc.devnet.telcoin.network  chain 32285  tip 6498  current epoch 3 (started @5689, duration 3600s)
WorkerConfigs(0) @latest(6498): strategy 0 (eip1559)  target 10000000  data 9  | expected target 10000000
boundary      blocks       gas_used                target                 fee_N       fee_N1_expected         fee_N1_actual  verdict  notes
1->2            1262       52106278              10000000                     7                     8                     8     PASS  blocks 2..1263, 1.4s
2->3            4425      620184018              10000000                     8                     9                     9     PASS  blocks 1264..5688, 2.2s
summary: 2 boundaries  PASS 2  FAIL 0  SKIP 0  | 28 RPC requests, 4.0s wall
```

- Boundary 1→2 (16:33:56Z): 1262 blocks used 52,106,278 gas, 5.2× the target, and the fee went 7 → 8 wei.
  That is the +1 wei minimum rise; 12.5 % of 7 rounds down to 0.
- Boundary 2→3 (17:33:56Z): 4425 blocks used 620,184,018 gas, 62× the target, so the gas was clamped to
  2× target. The fee went 8 → 9 wei (+12.5 % = +1 wei).
- Boundary 0→1 is outside `--last 2`. It was also run, at 17:46:55Z: `./devnet-basefee-check.sh --epoch 0` gives
  `0->1  1 block  gas 0  fee 7 -> 7 (expected 7)  FAIL gas_used < target (no load?)`, exit 1. The FAIL is the load
  check only. Epoch 0 was a single block because the genesis timestamp was 2 days old, so it closed at once. With
  `--formula-only` (17:47:01Z) the same boundary gives `PASS`, exit 0. The step formula holds at all 3 boundaries.

## 6. Txgen

Commands:
- One IAP ssh to txgen-devnet (us-west2-a), started 17:50:27Z (`scratchpad/V1/s6-remote.sh`). The header lines
  returned. My own 200 s alarm then killed the call (rc 142) during a slow full-journal grep, before the
  two journal/metrics samples. No second txgen ssh was made, per the one-ssh-per-section rule. The two
  samples were taken instead from the generator's journal as shipped to Loki and from the chain.
- Loki and Prometheus through Grafana's datasource proxy, over HTTPS (no IAP), 17:57:18Z-17:58:19Z:
  `bash scratchpad/V1/s6g.sh`. Grafana admin is read from Secret Manager `obs-grafana-admin` into a shell
  variable and passed to curl on stdin (`-K -`); it was never printed.
- Chain: `python3 -I scratchpad/V1/s6-gas.py` (17:55:21Z) and `s6-chain.py` (17:57:26Z), both `eth_getBlockByNumber` on the LB.

| check | command | value |
|---|---|---|
| unit state | `systemctl is-active / is-enabled tn-transaction-generator.service` (17:50:31Z) | active / enabled |
| unit details | `systemctl show -p ActiveEnterTimestamp -p NRestarts -p MainPID` | MainPID 274611, **NRestarts 69**, **ActiveEnterTimestamp Fri 2026-10-30 21:50:48 UTC** |
| alloy on txgen | `systemctl is-active alloy` | active |
| journal "tx submitted" before step 16 | `journalctl -u … --since '2026-11-02 15:30 UTC' --until '17:35 UTC' \| grep -c '"tx submitted"'` | **13189**; first at 2026-11-02T16:13:50.263Z, last at 17:34:59.2Z |
| "tx submitted" sample 1 | Loki `sum(count_over_time({node="txgen-devnet"} \|= "tx submitted" [<since 17:38:00Z>]))` at 17:57:18Z | 1782 |
| "tx submitted" sample 2 | the same at 17:58:19Z (61 s later) | **1816 (+34)** |
| "tx submitted" per minute | Loki `count_over_time(…[1m])`, step 60 s, 17:47-17:57Z | 58, 155, 42, 88, 112, 39, 8, 23, 97, 29, 34 (mean 62/min) |
| ERROR lines since 17:38Z | Loki `{node="txgen-devnet", level="ERROR"}` | 0 (no series) |
| `txgen_*` metrics | Prometheus `sum by (outcome) (txgen_tx_submitted_total)` at 17:57:18Z and 17:58:19Z | **empty both times**. `max_over_time(timestamp(txgen_tx_submitted_total)[6h:1m])` = **17:39:40Z**, the last sample. `up{job="txgen"}` = 1, and the txgen job carries 5 series now, i.e. only scrape meta. The 127.0.0.1:9090 `grep ^txgen_` sample on the VM was not reached (see above). |
| chain load, last 20 blocks | blocks 6771..6790 (17:54:41Z-17:55:09Z, 28 s) | gasUsed sum **2,090,112**, 26 txs, gasLimit 30,000,000, baseFeePerGas 9 |
| chain load per minute | blocks 6139..6839 by minute, 17:39-17:57Z | 8-132 txs/min and 0.30M-6.69M gas/min. 8 distinct senders, top 0x65f55e7e… (147 txs). |

- The rising check passes on the journal: +34 "tx submitted" lines in 61 s, and on-chain tx flow continues every
  minute. The metrics half cannot be measured: Prometheus has no `txgen_*` sample after 17:39:40Z. That fits
  step 16's own log (`logs/deploy-20261102T1715Z-only16.log` line 590, `❌ no txgen_* metrics on 127.0.0.1:9090`,
  followed by `✓ observability wired` and `## step 16 done`).
- Step 16's startup-marker check (`only16.log` lines 567-571) printed `❌ MISSING` for all five markers ("deployments loaded",
  "rpc client ready", "master wallet loaded", "child wallets derived", "wallets ready"). It still printed
  `✓ service active with the expected startup markers` (line 572), because only `is-active` gates.
- **Load began before step 16.** The generator already on txgen-devnet from the previous chain submitted its first tx
  to the new chain at 16:13:50Z, as the LB came up. The first line is `master_funding:chi…`. Block 2, the first
  block with a tx, is at 16:13:51Z. Epoch 1 (blocks 2..1263) holds 1919 txs from 9 senders and the epoch-2 load is
  620M gas (§5). The same child wallets (0x65f55e7e…, 0xe6fedacd…) send in epoch 1 and after 17:38Z. The plan's
  "submitting since 17:40Z" understates this. The unit's ActiveEnterTimestamp (2026-10-30 21:50:48Z) and NRestarts 69
  do not show a restart by step 16 at ~17:38Z. Not investigated (see §12 V1-b).

## 7. Observability

Commands:
- One IAP ssh to obs-devnet, 17:55:09Z-17:56:18Z (`scratchpad/V1/s7-remote.sh`). The host curl talks to the
  container IPs (loki 172.18.0.3:3100, prometheus 172.18.0.2:9090), since neither publishes a host port. The §3 ssh
  (17:48Z) tried `docker exec prometheus wget http://loki:3100/…` and got empty answers from Loki, so this run used
  the container IPs.
- `gcloud compute instances describe obs-devnet` and `gcloud compute disks describe obs-devnet-data` (17:55:17Z).

| check | exact query | value |
|---|---|---|
| Loki hosts, last 15 min | `GET /loki/api/v1/label/node/values?start=<now-900s>` | 6: observer-5-devnet, validator-1-devnet, validator-2-devnet, validator-3-devnet, validator-4-devnet (+ txgen-devnet) |
| Loki lines per node, 15 min | `sum by (node) (count_over_time({chain="devnet"}[15m]))` at 17:55:09Z | validator-1 1,722,564; validator-2 1,297,194; validator-3 1,038,051; validator-4 495,940; observer-5 180,105; txgen 2,035 |
| Loki labels | `GET /loki/api/v1/labels` | chain, filename, image_version, job, level, node, region, service, service_name, unit, validator_address (+ `__stream_shard__`) |
| Loki /ready | `GET /ready` | `Ingester not ready: waiting for 15s after being ready`. The queries above answered in the same second, so this is the ingester's ring-settle message, not an outage. |
| Prometheus `up` | `count by (job, node) (up)` at 17:55:18Z | `job="telcoin-node"` = 1 for validator-1..4 and observer-5 (5/5); `job="txgen"` node txgen-devnet = 1; `job="prometheus"` = 1 |
| Prometheus `tn_*` series | `count by (node) ({__name__=~"tn_.+"})` | validator-1 669, validator-2 854, validator-3 855, validator-4 849, observer-5 858 (5/5) |
| Prometheus `tn_info` | `count by (node) (tn_info)` | 1 per node, 5/5 |
| sample freshness | `max by (node) (time() - timestamp(tn_network_admission_mode))` | 0.9-12.5 s (v2 0.97, v4 0.94, v1 2.89, v3 9.55, o5 12.49) |
| obs VM | `gcloud compute instances describe obs-devnet --zone us-west2-a --format='value(status,…natIP,disks[].source.basename(),disks[].deviceName)'` | RUNNING, 34.20.241.60, disks `obs-devnet` + **`obs-devnet-data` (deviceName obs-data)** |
| data disk | `gcloud compute disks describe obs-devnet-data --format='value(status,sizeGb,users.basename())'` | READY, 300 GB, users = obs-devnet (attached) |
| disk use | `df -h /mnt/obs-data` (on the VM) | /dev/sda 295G, 6.2G used (3 %) at 17:48Z; 7.7G (3 %) at 17:56Z |
| containers | `docker ps` (17:48Z) | caddy, grafana 11.4.0, loki 3.3.2, prometheus v3.1.0, all `Up 2 hours` (redeployed in step 9 at ~15:48Z) |

- The txgen's Loki `job` label is `loki.source.journal.txgen`, not the `job = "txgen"` set in its Alloy config
  (see the series list in `s6g-out.txt`). The obs-ssh txgen queries in this section filtered on `job="txgen"`, so
  they matched nothing. The `node="txgen-devnet"` queries in §6 do match. The obs-side txgen counts in §6 come
  from those.

## 8. Edge

Command: `bash scratchpad/V1/s8.sh`, 17:53:41Z-17:54Z, run from xerxes. It uses the gcloud calls with a 60 s alarm,
then curl, openssl and dig.

| check | command | value |
|---|---|---|
| LB health | `gcloud compute backend-services get-health devnet-rpc-backend --global --project=tn-devnet --format=json` (17:53:41Z) | 5/5 HEALTHY: devnet-rpc-ig-1 validator-1 10.168.15.204:80, ig-2 validator-2 10.206.0.2:80, ig-3 validator-3 10.162.0.48:80, ig-4 validator-4 10.164.0.48:80, ig-5 observer-5 10.154.0.49:80 |
| LB backends | `gcloud compute backend-services describe devnet-rpc-backend --global --format='value(backends[].group)'` | 5 groups. Node 2's is `zones/us-south1-a/instanceGroups/devnet-rpc-ig-2` (Dallas). |
| chain id via the LB | `curl -d '{"method":"eth_chainId",…}' https://rpc.devnet.telcoin.network` (17:53:47Z) | `0x7e1d` |
| chain id per node | the same against `https://node{1..5}.devnet.telcoin.network` | `0x7e1d` ×5 |
| admin dashboards, no auth | `curl -s -o /dev/null -w '%{http_code}' https://admin.node{1..5}.devnet.telcoin.network/` (17:53:48Z) | 401 ×5 |
| admin dashboards, with auth | not run | Secret Manager `devnet-admin-dashboard-hash` holds only the bcrypt hash, not the password, so the 200 cannot be shown from xerxes. |
| TLS node 1-5 | `echo \| openssl s_client -connect nodeN.devnet.telcoin.network:443 -servername … \| openssl x509 -noout -issuer -subject -enddate` (17:53:50Z) | node1 `issuer=C=US, O=Let's Encrypt, CN=YE2`, notAfter Jan 31 15:01:14 2027 GMT; **node2 `O=Let's Encrypt, CN=YE2`, CN=node2.devnet.telcoin.network, notAfter Jan 31 15:05:07 2027 GMT**; node3 LE YE2, Jan 31 15:07:07 2027; **node4 `O=Let's Encrypt, CN=YE1`, CN=node4.devnet.telcoin.network, notAfter Jan 31 15:09:35 2027 GMT**; node5 LE YE2, Jan 31 15:12:32 2027 |
| TLS LB | the same, against rpc.devnet.telcoin.network | `O=Google Trust Services, CN=WR3` (Google-managed cert), notAfter Jan 4 19:10:23 2027 GMT |
| `curl -sI` node2 / node4 | `curl -sI https://node{2,4}.devnet.telcoin.network` | `HTTP/2 405`, `allow: POST, OPTIONS`, CORS `*` on both. Caddy serves h2 and the RPC answers HEAD with 405, as expected. |
| WSS | `curl --http1.1 -H 'Upgrade: websocket' … https://node1.devnet.telcoin.network/ws` | 101 |
| DNS | `dig +short …` | node1 35.236.51.63, **node2 34.174.181.214**, node3 34.19.189.1, node4 34.7.93.35, node5 35.242.150.70, **admin.node2 34.174.181.214**, rpc 34.96.110.84, obs 34.20.241.60 |

All five node certificates expire on Jan 31 2027, about 90 days after this launch, so they were issued by step 13
today. Step 13 needed 4 attempts (see §12).

## 9. Release signature

- From deploy step 8's gate, `logs/deploy-20261102T1532Z-from8.log` line 14, also in
  `logs/release-verify-20261102T1528Z.log`:
  `[GNUPG:] VALIDSIG 4E36D35A4AB61B589861D01AC7173F2377CA7573 2026-11-02 1793633247 0 4 0 1 8 00 4E36D35A4AB61B589861D01AC7173F2377CA7573`
  Signature timestamp 1793633247 = 2026-11-02T15:27:27Z; key id C7173F2377CA7573; pubkey algo 1 (RSA), hash algo 8 (SHA-256).
  Line 18 reads `✓ release v0.2.0-devnet: SHA256SUMS.asc verified against the release keys`.
- Re-run at 17:55:30Z, `./devnet-release-sign.sh verify </dev/null`: the same VALIDSIG line,
  `✓ SHA256SUMS: IMAGE_DIGEST genesis.yaml committee.yaml parameters.yaml match the current files`,
  `✓ IMAGE_DIGEST = DOCKER_IMAGE (…adiri@sha256:5257e768…a610)`, `release v0.2.0-devnet verified`, rc 0.
- `releases/v0.2.0-devnet/SHA256SUMS` (321 B), with `sha256sum` of the current files run at 17:55Z:

  | file | SHA256SUMS | sha256sum now |
  |---|---|---|
  | IMAGE_DIGEST | 6ea635f54ca77d7dfc6d43713dafa4fe8adcd221298a81938fa4cc8bcb6b6646 | same |
  | genesis.yaml | 67bc0e0d16be1b567f5f996c32c23c6835e415c83fd575bc305c88339517a3a6 | same (genesis/genesis.yaml) |
  | committee.yaml | 046008b37c3c586d79e5a7056f7d2d0ebf058190f86f6d56e5ba1e6ecd51b54e | same (genesis/committee.yaml) |
  | parameters.yaml | ef669af21abaf85ef0e91d966e8f6c8d88632d6f60a59ea31503a3067bc2595b | same |

- `IMAGE_DIGEST` (122 B) = `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:5257e768e657586a19e31308906bfacac0df95e5ca3da29a68f818f159d4a610`,
  which is byte-equal to config.sh `DOCKER_IMAGE` (line 42). The same digest is in `.node-meta` on 5/5 nodes (§1).

## 10. tn-cli

tn-cli-dev 6962def (`~/.cargo/bin/tn`). U3c logs were taken at 17:15Z, all `--rpc https://rpc.devnet.telcoin.network`, run from
the scratchpad, no signer. The V1 re-reads are at 17:44:08Z and 17:49:18Z.

| command | log | key lines | exit |
|---|---|---|---|
| `tn status` | `logs/tn-cli-u3c-status-20261102T1715Z.log` (17:15:54Z) | node1-5 epoch 2, consensus 9505, height 4864; `next epoch boundary 2026-11-02T17:33:56Z` | 0 |
| `tn status` (V1) | scratchpad `s0-status.txt` (17:44:08Z) | node1-4 epoch 3, consensus 12158, height 6425; node5 epoch 3, 12158, 6424; next boundary 18:33:56Z | 0 |
| `tn fees` | `logs/tn-cli-u3c-fees-20261102T1715Z.log` | `0  0 eip1559  10000000  8  8` (worker, strategy, value, data, base fee) | 0 |
| `tn fees` (V1) | scratchpad `s4-tn.txt` (17:49:18Z) | `0  0 eip1559  10000000  9  9` (epoch 3) | 0 |
| `tn safe 0x…07a0` | `logs/tn-cli-u3c-safe-20261102T1715Z.log` | `version: 1.4.1`, `threshold: 1-of-8`, first owner 0xAee2797478Cb5EfaF1869A2e33e369421EBf520f, `nonce: 0`, `modules: (none)` | 0 |
| `tn safe 0x…07a0` (V1) | `s4-tn.txt` (17:49:18Z) | same, but `nonce: 1` (after the node-5 mint) | 0 |
| `tn gov get-worker 0` | `logs/tn-cli-u3c-getworker-20261102T1715Z.log` | `0  0 eip1559  10000000  8  8` | 0 |
| `tn gov get-worker 0` (V1) | `s4-tn.txt` | `0  0 eip1559  10000000  9  9` | 0 |
| `tn node record --addr 0x3518…d024 --bootstrap /ip4/35.236.51.63/udp/49594/quic-v1/p2p/12D3KooWN3CN…` | `logs/tn-cli-u3c-noderecord-20261102T1715Z.log` (17:16:08Z) | `error: no bootstrap peer reachable: every dial failed or timed out; …` after 5 s, run once. This is the expected refusal under Closed admission: an unlisted peer is not admitted. | 1 |
| `cargo test --locked` | `logs/tn-cli-u3c-cargotest-20261102T1719Z.log` | `test result` lines sum to 193 passed, 0 failed | 0 |

Faucet (`logs/tn-cli-u3c-faucet-20261102T1714Z.log`, 17:14:33Z, block 4832):
- `0xb781…`, the old default, has `type: EOA, code size: 0 bytes` on devnet. It is the live Adiri faucet,
  so tn-cli now picks the faucet default per network.
- The devnet faucet is the StablecoinManager proxy 0xf09a4e512cf87ecac839d732681959cefd83ecb9: 122-byte
  ERC1967 proxy, implementation 0x1dbff83198957a4dca66233e35855340b7e13ecc (13360 bytes), which inherits
  TNFaucet. Drip selector 0x9e353a1e, dripTo 0x5d2d812b. `getEnabledXYZs count: 23`, `isEnabledXYZ(native): true`,
  `baselineDripCooldown: 86400`.
- An eUSD `dripTo(probe, eUSD, 1e8)` eth_call returns `0x` (success), and MINTER_ROLE is held on 23/23 eXYZ.
- The native drip reverts `0x37f33ed8 = LowLevelCallFailure(bytes)`: `hasMintRole(0xf09a)` is false
  (the governance Safe 0x…07a0 is true).
- Remedy, simulated only: `grantMintRole(0xf09a)` on 0x…07e1, sent from the Safe, returns `0x`. The same
  call from the owner EOA 0xAee2 gives `PrecompileError`, so it has to be a Safe transaction. Not executed.

## 11. Node 5 staking

Source: `logs/stake-node5-20261102T1721Z.log` (`./devnet-stake-node5.sh --yes --watch-epochs 3`, started 17:21Z; the watch
was still running at capture, log last written 17:34:17Z). Cross-checked at 17:47:25Z with `bash scratchpad/V1/s4.sh`
(`eth_getTransactionReceipt`, `eth_getBlockByNumber`, `cast call`, `cast balance` on the LB).

Preflight, all ✓: chain id 32285, registry owner = Safe, node 5 address = config = node-info, nextCommitteeSize 4,
eligible 4, epoch 2, node 5 not minted, Safe 1-of-8 nonce 0, stake v0 = 1e24 wei, gas price 8 wei, node 5 balance 1,000,100 TEL,
both Secret Manager keys match their addresses, stake simulation reverts only `InvalidTokenId` (pre-mint).

| step | tx | block (time) | epoch | status, gasUsed, effectiveGasPrice | result |
|---|---|---|---|---|---|
| mint via Safe `execTransaction` (Safe nonce 0, safeTxHash 0x2d81b0eb…541c) | 0x926ac790f6865b04af4781a098497ea28d84cb83660aaab691f49531344d4822 | 5025 (17:21:47Z) | 2 | 1, 220915, 9 wei | getValidator = status Undefined (0), activationEpoch 0 (NFT minted) |
| stake 1,000,000 TEL from node 5 | 0x5cce190b67b343bb757389cbe76d303be4ebc06d45cf3ef32643a351bec80cc8 | 5026 (17:21:51Z) | 2 | 1, 415295, 9 wei; value 1000000000000000000000000 | status Staked (1), activationEpoch 4294967295 |
| sync gate | n/a | n/a | 2 | node 5 head 5026, node 1 head 5026 (lag 0), tn_nodeMode Observer | ✓ |
| activate() from node 5 | 0x1ce1763e193ef9df866db9c324fe4fd3a3ba78a69b31a22b9cfdf6bd05b86cf5 | 5027 (17:21:54Z) | 2 | 1, 131566, 9 wei | status PendingActivation (2), activationEpoch 3 |
| watch | n/a | n/a | 2→3 | 24 polls at 30 s show `epoch 2: PendingActivation`; one poll hit `Connection timed out` on the LB, and the watch continued | `✓ node 5 Active in epoch 3 (activationEpoch 3)` (~17:34Z) |

- Committee lines from the watch (and identical in the V1 re-read at 17:47:25Z):
  - committee(3): 0x0033a370…, 0x3518b301…, 0x7489025d…, 0xefaacf04… (node5 out, drawn before activation)
  - committee(4): the same four (node5 out, drawn before activation)
  - committee(5): 0x0033a370…, 0x3518b301…, 0x7489025d…, **0xd0154a8091de71cc81b3c6f95b73d0aa129da7b8**
    (`node 5 IN; CHANGED vs 4`). Node 4, 0xefaacf04, sits out epoch 5.
- `getValidator(0xd015…)` at 17:47:25Z: `(0xd0154a8091dE71Cc81B3C6F95b73D0aA129dA7b8, 3, 0, 3, false, 0, 0)` = activationEpoch 3,
  exitEpoch 0, status 3 (Active), not retired.
- Node 5's balance (`cast balance 0xd0154a8091de71cc81b3c6f95b73d0aa129da7b8`, 17:47:25Z) is 99999999999995078251 wei =
  99.999999999995078251 TEL, nonce 2. It started at 1,000,100 TEL. The 1,000,000 TEL stake and gas
  (415295 + 131566) × 9 wei = 4,921,749 wei account for the change exactly, since 100e18 − 99999999999995078251 = 4,921,749.
- Node 5 reads `tn_nodeMode = Observer` at 17:45:32Z (§1). It is expected to switch to CvvActive when epoch 5 starts at 19:33:56Z (V2). Note that tasks/plan.md says "≈20:34Z", which is when epoch 5 ends.

## 12. Findings carried from the plan (pointers only, not re-investigated)

| id | finding | numbers | pointer |
|---|---|---|---|
| F1 | A genesis validator that starts more than 50 rounds after its peers is stranded for the rest of the epoch | validators 1-3 reached quorum at 15:33:56Z; validator-4's unit started at 15:34:33Z (+36 s) and sat at round 0/1 as CvvInactive (`batch builder not started …`), following the chain only by state-sync; CvvActive again after the 16:33:56Z boundary (probe 16:37Z) | tasks/plan.md (FINDING launch-1 F1); tasks/lessons.md:3; tasks/todo.md ("launch 1, F1": two-phase finalize) |
| F2 | The observability sweep's "after" probe accepts CvvActive at 0 s, but a restarted member is missing from commits for ~30-60 s, so the next node's quorum guard refuses | validator-3 was refused at 16:40:33-16:40:53Z, ~20-30 s after validator-2's restart; recovery 16:43-16:59Z, and every restart was back in commits within ~60 s | tasks/plan.md D3d + recovery; tasks/todo.md ("launch 1, F2") |
| dns | common/dns.sh Phase 4 probes ~1 s after the Caddy reload with no retry, so it loses the race against first-time Let's Encrypt issuance | step 13 passed on attempt 4 (16:13Z); nodes 1, 3 and 4 each lost once (node 1: cert at 15:59:45Z, probe at 15:59:46Z) | tasks/plan.md D3c; tasks/checkpoint-l1-deploy.md D3c; tasks/todo.md (common/dns.sh bounded retry) |
| txgen secrets | master.key and children.seed live only on the Mac and, sops-encrypted, on the txgen VM | step 16's 2nd attempt failed on a missing `tn-transaction-generator/secrets/master.key`; recovered from the VM with the Secret Manager age identity (master 0x46c26b4f…, genesis-funded) | tasks/plan.md step 16; tasks/todo.md (mirror to Secret Manager) |
| sops/age | Local prerequisites of step 16 were missing on xerxes | step 16's 1st attempt failed; the user installed sops 3.9.4 and age 1.2.1 | tasks/plan.md step 16 |
| faucet mint role | Native TEL drips revert until the Safe grants mint to the faucet | `hasMintRole(0xf09a…)` = false; the fix is one Safe tx to 0x…07e1 with calldata `0xc2e3273d…f09a4e512cf87ecac839d732681959cefd83ecb9`, simulated OK from the Safe and not executed | §10; tasks/checkpoint-l1-U3c.md; tasks/todo.md (native TEL faucet) |
| node-4 A3 | One transient IAP drop in a post-check fails the whole deploy segment | finalize exited 1 at 15:44:36Z on node 4 A3 (ssh rc 255); the read-only re-verify at 15:46Z was ok | §1; tasks/lessons.md:24 |
| stake preflight | `revert_selector` did not parse cast 1.8's resolved revert names | dry run at 17:13Z exited 1 silently; patched in the working tree, and the 17:15Z dry run gave `✓ preflight passed` (logs/stake-node5-dry-20261102T1715Z.log); committed as 50c920a at 17:43:18Z | tasks/checkpoint-l1-S1.md; tasks/todo.md |

New in V1 (recorded here, not investigated further):

| id | observation | numbers | pointer |
|---|---|---|---|
| V1-a | The Alloy relabel overwrites the node's `network` label (`primary` / `worker-0`) with the chain name, so Prometheus holds one series per node per admission metric | locally on validator-1: 2 series per metric; on the obs Prometheus: 1 series per node | §3; tn-node-deployment/lib/observability.sh:417-420 (same rule at common/observability/node-agent/config.alloy:123) |
| V1-b | The txgen generator installed for the previous chain loaded the new chain before step 16; systemd records no step-16 restart; no `txgen_*` metrics since 17:39:40Z | the first "tx submitted" to the new chain is at 16:13:50Z, with 13,189 by 17:35Z; the unit shows ActiveEnterTimestamp 2026-10-30 21:50:48Z and NRestarts 69; `txgen_tx_submitted_total`'s last Prometheus sample is at 17:39:40Z; step 16's marker check printed 5 × `❌ MISSING` and `❌ no txgen_* metrics` but passed | §6; logs/deploy-20261102T1715Z-only16.log:567-572, 590 |
| V1-c | The txgen Loki stream's `job` label is `loki.source.journal.txgen`, not the configured `txgen` | queries on `job="txgen"` return 0 series; queries on `node="txgen-devnet"` work | §7; devnet-txgen.sh:510-518 |
| V1-d | The seat time for node 5 in the plan is one epoch late | epoch 5 runs 19:33:56Z-20:33:56Z (epoch 3 started at block 5689; next boundary 18:33:56Z); the plan says "≈20:34Z" | §1, §11; tasks/plan.md Wave 4 |
| V1-e | committee(5) seats node 5 in place of node 4 | committee(5) = node3, node1, node2, node5; node 4 (0xefaacf04) sits out epoch 5 | §4, §11 |

## Summary

| # | check | result | number |
|---|---|---|---|
| 1 | fleet: units, enabled, node-meta, uid, PASSPHRASE, ufw, mode, head | pass | 5/5 active+active+enabled, NRestarts 0; NETWORK devnet + digest 5257e768…a610 on 5/5; uid 999; PASSPHRASE hits 0 ×5; ufw active, deny-in, 49590/49594 udp ×5; CvvActive ×4 + Observer; heads 6454-6468 at 17:45Z |
| 1b | finalize post-checks | pass (after re-verify) | 24/25 in the run + node 4 A3 re-verified ok = 25/25 |
| 2 | consensus progress | pass | +95 commits, +190 rounds, +54 blocks in 60 s; 43.8 blocks/min over 200 blocks |
| 3 | admission | pass | mode 2 and fallback 0 on 5/5; source denials 0; network-config Closed 5/5 |
| 4 | governance | pass | Safe 1.4.1, 8 owners (0xAee2… first), threshold 1, nonce 1; worker 0 = (0, 10000000, 9); epoch 3; committee(3) = genesis 4 |
| 5 | base fee | pass | 1→2: 7→8, 2→3: 8→9 (PASS 2, rc 0); 0→1 formula PASS (load check FAIL, by design: 1-block epoch) |
| 6 | txgen | pass, partly unmeasured | unit active; Loki "tx submitted" 1782→1816 (+34 in 61 s); last 20 blocks 2,090,112 gas; **txgen_* metrics: none since 17:39:40Z** |
| 7 | observability | pass | Loki 5/5 nodes in 15 min (180k-1.72M lines); Prometheus up = 1 ×5, tn_* 669-858 series ×5; obs RUNNING, obs-devnet-data attached (3 % used) |
| 8 | edge | pass (200 not tested) | LB 5/5 HEALTHY; eth_chainId 0x7e1d ×6; admin 401 ×5; node2 LE YE2, node4 LE YE1; DNS node2 = 34.174.181.214 |
| 9 | release signature | pass | VALIDSIG 4E36D35A4AB61B589861D01AC7173F2377CA7573 at 15:27:27Z; 4/4 sums match; IMAGE_DIGEST == DOCKER_IMAGE |
| 10 | tn-cli | pass | status/fees/safe/get-worker exit 0; node record refused (exit 1, as expected); 193 tests pass; faucet = 0xf09a…, native drip needs grantMintRole |
| 11 | node 5 staking | pass (so far) | mint/stake/activate in blocks 5025/5026/5027 (epoch 2, 17:21:47-54Z); Active in epoch 3; committee(5) includes node 5; balance 99.999999999995078251 TEL |
| 12 | findings | n/a | 8 carried, 5 new (V1-a..e) |

## Verdict

Launch 1 is live and verified as of 17:58Z on 2026-11-02:
- Chain 32285 is on the signed v0.2.0-devnet release: VALIDSIG by 4E36…7573, and the image digest 5257e768…a610 is on all 5 nodes.
- The four genesis validators are CvvActive and commit 95 sub-dags/min. The LB serves all five backends.
- Closed admission holds everywhere (mode 2, fallback 0).
- The base fee stepped 7→8→9 wei exactly as the formula requires at both loaded boundaries.
- Node 5 is staked and Active (activationEpoch 3) and is drawn into committee(5).

Three things were not measured:
- the txgen's own Prometheus counter, because the generator has exported no `txgen_*` series since 17:39:40Z (V1-b);
- the admin dashboards' authenticated 200, because only the hash is in Secret Manager;
- the txgen loopback `/metrics`, because the one txgen ssh was cut short by my own alarm.

V1 added five observations to §12. The one that most changes the record is that the previous chain's txgen unit
was loading the new chain from 16:13:50Z, not from 17:40Z. None of these blocks launch 1.

## To be appended by V2

- [ ] Node 5 seated: at or after 19:33:56Z (the start of epoch 5; tasks/plan.md says ≈20:34Z, see V1-d),
  `tn_nodeMode` = CvvActive on node 5, node 5's authority in node 1's `tn_latestConsensusHeader` authors, and
  validator-4's mode while it sits out epoch 5.
- [ ] Committee membership over at least 3 epochs: 5, 6 and 7, from `logs/stake-node5-20261102T1721Z.log` (the watch ends ≈22:34Z)
  and `getCommitteeValidators(uint32)` for each epoch. Record which epochs seat node 5 and which validator sits out.
- [ ] Admission around node 5's first seat: `tn_network_admission_fallback` on nodes 1-4 (the runbook expects a
  temporary fallback 4 until node 5's record arrives), then back to 0. Read it on the node, because of the
  label collision V1-a.
- [ ] Base fee after more boundaries: `./devnet-basefee-check.sh --last 4` once 3→4 (18:33:56Z) and 4→5 (19:33:56Z)
  have closed. Expect +12.5 % per epoch while gas ≥ 2× target: 9→10→11 (rounded, with at least +1 wei).
- [ ] Optional, if V1-b is fixed first: txgen `txgen_tx_submitted_total` rising between two reads, and the
  authenticated admin 200.
