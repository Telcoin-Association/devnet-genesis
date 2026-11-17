# RH5: local rehearsal of the transaction path (RPC node -> record URL -> worker gateway -> validator worker -> block)

Run 2026-11-17 21:05-21:14 UTC on local docker. Node image `adiri@sha256:0aec3e7c…` (= `dg-l2/config.sh` `DOCKER_IMAGE`),
gateway image `worker-gateway@sha256:8b887098…`, both `--pull never`. dg-l2 scripts (`devnet-genesis-build.sh`,
`devnet-network-config.sh`) ran unedited through a `CONFIG_FILE` wrapper; TND's `lib/common.sh` (+ `lib/gateway.sh`) sourced
read-only. Scratch dir (kept): `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/RH5/` (`$S`).

## What this means for the real deploy
- **The path works.** A `cast send` to the RPC node (node6, `Observer`) returned a receipt with status 1 in 1.29 s; node6 pooled
  it, sealed its own batch, forwarded it to the URL in node1's record (gateway 1), gateway 1 handed it to node1's worker, node1
  proposed it, block 2. 20 sequential transfers: 20/20 in about 1 s. A 400-transfer burst: 400/400 in 4.65 s. Reads through a
  gateway are answered by the RPC node (`tn_nodeMode` = `Observer`). A dead gateway costs one 3-6 s delay per 30 s; no loss.
- **Nothing in the launch's configuration or scripts has to change for this path.** What must hold on the fleet (already the
  plan): each validator's `node-info.yaml` `workers[0].rpc.http` is ITS OWN gateway's URL (keygen `--rpc-http`, or `keytool
  set-rpc` + restart); the RPC node advertises none; node6's `parameters.yaml` keeps `allow_private_forward_targets: false`
  (the genesis build checks it, step 4 ✓); each gateway reaches its validator's RPC and `/health/workers`.
- **To decide (not blockers):**
  1. All transfers from one sender go to ONE validator first (the sender's committee slot; here node1), so one gateway carries
     a busy sender's whole load, and every gateway sees the RPC node as one client (100/s, burst 200). In Q7, about 210
     forwards to gateway 1 in a second drew one `429`; node6 demoted node1's endpoint for 30 s and moved the rest to node4 (61
     requeued). Nothing was lost. If the launch drives sustained load above about 100 tx/s through the RPC node, raise
     `--rate-limit-per-ip` on the validator gateways (`gw_render_args`, `tnd-l2-gateway/lib/gateway.sh`, renders no limit
     flag, so the binary's default applies), or have load generators post to the gateways directly.
  2. Operators: node6's demotion warning names no endpoint (Q6). Use `tn_worker_submit_usable_members` (below
     `..._expected_members`) and each gateway's `tn_worker_gateway_rejections_total` to find which validator.
  3. A gateway that is restarting (or whose validator is not accepting) answers `503`, and node6 demotes it for 30 s (Q6).
- **The deliberate difference** (only here): node6's `$S/data/node6/parameters.yaml` set `allow_private_forward_targets: true`
  after the genesis build (validators keep `false`), because the record URLs are plain-http private addresses
  (`http://172.30.105.2K:8655/`); gateways ran `--mode standalone --front none` on a docker bridge, no Caddy, no TLS. On the
  fleet: the URLs are public https names, which pass the literal check (DNS is not resolved); traffic crosses Caddy, so a stopped
  gateway behind a live Caddy should fail fast (Caddy's 502 = non-2xx = demotion) [not tested], while a dead host costs the 5 s
  per-send timeout, as seen here. The run with `false` was not done: what node6 logs for refused private URLs is not verified.

## Harness (`$S/bin/`, copied from RH3, `l2rh3` -> `l2rh5`, subnet 172.30.105.0/24, nodeN = .1N, gwK = .2K)
- `setup.sh`: RH3's keygen (`keytool generate validator` for all six) with `--rpc-http http://172.30.105.2K:8655/` for node1-4,
  none for node6; `cast wallet new --json` -> `$S/secret/wallet.json` (600); its address added to the workspace copy of
  `testnet_accounts.yaml` with balance `0xffffffffffffffffffffffffffffffff` (the file's own format). Genesis build rc 0, steps
  0-6 ✓ (`$S/logs/genesis-build.log`); `step4.sh` (RH3's): 11 maps, six network-configs (node6 `Open`), validate rc 0.
- `start.sh`: RH3's node line with `--http.addr 0.0.0.0`, `--healthcheck 0.0.0.0:43174` (what `edit-config.sh --set
  gateway_upstream` does) and `--metrics 127.0.0.1:9101` (TND `obs_metrics_reth_flags`, port `DEFAULT_METRICS_PORT`); node6's
  8545 published on `127.0.0.1:18645`. No node5.
- `gw.sh K`: sources TND `lib/common.sh` on `TN_ROOT_PREFIX=$S/tnroot`, sets `GW_IN_*` (`standalone`, `devnet`, upstream
  `172.30.105.1K`, `--front none`, redirect `http://172.30.105.16:8545`, image digest) and calls **`gw_validate_inputs`** (it
  accepted all four; the manual `GW_V_*` fallback was never used), then **`gw_render_args`**. Rendered line (gw1):
  `--listen-addr 0.0.0.0:8655 --probe-addr 127.0.0.1:8656 --metrics 127.0.0.1:9655 --upstream-rpc-url http://172.30.105.11:8545
  --upstream-readiness-url http://172.30.105.11:43174/health/workers --worker-id 0 --redirect-queries http://172.30.105.16:8545`.
  Docker options = `gw_unit_text`'s ExecStart (`--user 1101:1101 --read-only --cap-drop ALL --security-opt no-new-privileges
  --pull=never --stop-timeout 60`) with `--network l2rh5-net --ip 172.30.105.2K` instead of `--network=host`.
- Probe and metrics listen on the gateway's loopback, so `peek.sh` reads them from a throwaway container in the gateway's network
  namespace; `snap.sh` = node6 forward metrics + gateway counters; `sign.sh` presigns (`cast mktx`, fees max 100 wei, tip 1:
  `cast send` chose 15/1); `blast.py` posts and polls receipts on node6, maps each block's `miner` to the node.

## Q1 Start. Verdict: yes
node1-4 started 21:06:23.4-23.8, gw1-4 21:06:24.1-24.8, node6 21:06:31.4. Watchers (one per gateway, every second):
`/health/workers` `accepting_transactions` false at 21:06:25, **true at 21:06:27.0-27.3** on all four validators (about 3.7 s
after start); gateway `/ready` 503 until **200 at 21:06:35.06-35.36** (all four): 11 s after gateway start, 8 s after the
validator accepted (two passing polls at 5 s). At 21:08:15 (`status.sh`): node1-4 `CvvActive`, node6 `Observer`, block 1 on all
five. At the end (21:13:28): block 55 on all five, modes unchanged.

## Q2 The record. Verdict: node6 holds a usable URL for each of the four validators
node6 log (1,336 lines at 21:08): 0 lines `no committee validator has advertised a JSON-RPC endpoint` or `failed to discover
validator JSON-RPC endpoints`. Metrics: `tn_worker_submit_expected_members{network="worker-0"} 4`,
`tn_worker_submit_usable_members{network="worker-0"} 4`. No RPC or log line prints the URLs (the kad `Providing our record` lines
show the record as bytes). Which URL belongs to which validator is shown by the traffic: node1's forwards reached gw1
(172.30.105.21), node4's gw4, node2's gw2, node3's gw3 (Q3, Q6, Q7: each block's miner matches the gateway that counted it).
node-info: node1 `rpc: {http: "http://172.30.105.21:8655/", ws: ~}`, node6 `rpc: ~`.

## Q3 THE TRANSACTION. Verdict: confirmed, status 1, 1.29 s
`cast send --rpc-url http://127.0.0.1:18645 0x…bEEF --value 1000000000` from the funded key (chain id 32285, gas price 7 from the
node): 21:08:40.325 -> rc 0 at 21:08:41.615. Receipt: status `0x1`, tx `0x7ee65139…6641`, block 2 (`0x8e93c4bd…`), type 2,
gasUsed 21000, effectiveGasPrice 8. The path, from the logs (all UTC 21:08):
- node6 40.390 `batch built … worker_id=0 num_txs=1 bytes=107 gas=21000` (its own worker seals, then forwards);
- node1 40.431 `batch built … num_txs=1 … reason=drain`; 40.728 `header proposed round=100 epoch=1 num_batches=1`;
- all four 41.45 `consensus output ready number=244 … num_batches=1 total_txs=1`; node6 41.460 `next block executed … number=2`;
- block 2: `miner` = node1's execution address `0x3518b301…`, one transaction (this one).
Counters after: node6 `tn_reth_forwarded_txns_queued_total 1` (every other `tn_reth_forward*` counter 0); gw1
`tn_worker_gateway_routed_requests_total{route="worker",result="forwarded"} 1`; gw2-4 no worker or query traffic; `route="query"` 0
on all four (cast read from node6 directly). The tx hash appears in no node log at `-vvv`.

## Q4 20 more. Verdict: 20/20 confirmed, all through gateway 1
Presigned nonces 1-20, posted one by one to node6 in 0.01 s: HTTP 200 ×20; 20/20 status 1, all seen 1.01 s after the first post,
all in block 3 (miner node1). node6 queued 1 -> 21; gw1 worker forwarded 1 -> 21; gw2-4 0. No `429` (no rejections on any
gateway), 0 `demot`/`unreachable` lines on node6.

## Q5 Reads and a direct submission through gateway 1. Verdict: yes
Posted from the host to `http://172.30.105.21:8655`: `eth_getBalance` -> 200 `0xff…c42f60ab`; `tn_nodeMode` -> 200 **`Observer`**
(node1 asked directly: `CvvActive`); `eth_chainId` -> `0x7e1d`. gw1 `route="query",result="forwarded"` 0 -> 3. The 21st transfer
(nonce 21) posted to gateway 1 directly: HTTP 200, status 1 after 1.01 s, block 4 (miner node1); gw1 worker 21 -> 22, node6 queued
unchanged at 21 (it did not pass through node6).

## Q6 One failure. Verdict: every transfer confirmed; the RPC node skips the dead gateway about 30 s at a time
Deviation: I stopped **gateway 1**, not 2. Every forward from this sender goes to node1 first (Q3, Q4), so stopping gw2 would
have exercised nothing. `docker stop l2rh5-gw1` 21:09:51.87-51.97, exit 0.
- 5 transfers at 21:09:52.57: 5/5 status 1 after **6.02 s**, block 5, miner node4. Then one transfer every 10 s (7): all status 1;
  latencies 1.00, 1.51, **6.02**, 1.00, 0.50, 1.51, **4.51** s; miners node2/node3.
- node6, the only lines about it: `level=warn target=worker::forward message="demoting unreachable validator RPC endpoints from
  forward admission" demoted=1 cooldown_secs=30` at **21:09:57.159, 21:10:23.763, 21:11:01.628**. The line names no endpoint.
  Metrics at 21:11:08: `tn_reth_forward_endpoints_demoted_total 3`, `tn_worker_submit_usable_members 3` (expected 4),
  queued 33; gw2 4, gw3 3, gw4 5 worker forwards.
- Skip time: the transfers at 21:10:28/39/48 (5-25 s after the 2nd demotion) were fast; the one at 21:10:58.5 (34.7 s after)
  tried gw1 again (3.2 s to fail). That matches 30 s. But the 2nd attempt (batch built 21:10:18.76, demoted 5.0 s later) came only
  21.6 s after the 1st demotion; epoch 2 had begun at 21:10:12 (block 8, 0 txs). Inferred, not verified in code: the cooldown table
  does not survive an epoch change.
- `docker start l2rh5-gw1` 21:12:06.38. My readiness wait had a bug and 5 transfers went at 21:12:06.70, before gw1 was ready:
  gw1 answered `503` (`rejections_total{reason="no_upstream_ready"} 1`), node6 demoted it (4th line, 21:12:06.79), the 5 went to
  node4, status 1 in 1.01 s. gw1 `/ready` 200 at 21:12:18.16 (11.8 s after start). After the cooldown, 5 transfers at 21:12:40.32:
  gw1 worker forwarded 0 -> 5, block 16 miner node1, status 1 in 1.01 s, `usable_members` 4. So yes, it is used again.

## Q7 The one-client limit. Verdict: one 429, one demotion, all 400 confirmed
400 presigned transfers (nonces 44-443, 1.5 s to sign) posted to node6 with 8 threads: 0.07 s, HTTP 200 ×400. **400/400 status 1**:
first receipt 1.09 s, median 3.12 s, last 4.65 s. Blocks 17-55 (39): node1 mined 210 (37 blocks), node4 190 (block 53: 41, block 55:
149). Counters, before -> after: gw1 worker forwarded 5 -> 215 and **`rejections_total{reason="rate_limited"} 1`**; gw4 10 -> 220;
gw2 4 -> 45; gw3 3 -> 3; node6 `queued_total` 43 -> 504, **`requeued_total 61`**, `forward_endpoints_demoted_total` 4 -> 5 (one
demotion line, 21:13:01.647), `usable_members` 3 right after. No per-connection refusals on any gateway. The gateway logs no
warning line for the 429 (only the INFO `edge protections configured … rate_limiting=true … max_connections_per_ip=Some(32)`).
Not established: why gw2 received 41 forwards that no node2 block holds (likely re-sends of requeued txs mined elsewhere).

## Q8 Clean-up. Verdict: done (21:13:39)
Removed `l2rh5-node1-4`, `node6`, `gw1-4`, `watch1-4` (`docker rm -f`), `docker network rm l2rh5-net`. Then
`docker ps -a --filter name=l2rh5-` -> `[]`, `docker network ls --filter name=l2rh5-` -> `[]`; `ss -ltn` has no `:18645`, and
`curl 127.0.0.1:18645` fails (000). Container logs saved first (`$S/logs/final-*.log`). Kept in `$S`: keys, BLS passphrase
`$S/secret/pass` and throwaway wallet `$S/secret/wallet.json` (both 600, so the chain can be rebuilt from the checkpoint).
dg-l2 `git status --porcelain`: changed during the run only in files other units edit (`devnet-keygen.sh`,
`devnet-network-config.sh`, `devnet-release-sign.sh`, `tasks/l2-shim/run.sh`, mtimes 21:06:46-21:09:44; two others went clean).
None is a file my runs write; `dg-l2/__pycache__/` predates the run (20:38 UTC).

## Not verified
- The real fleet's shape: Caddy in front, https records, `--network=host`, same-host gateways, a public RPC node address.
- node6 with `allow_private_forward_targets: false` against these private URLs (expected: refused, usable members 0).
- Whether node6's forwarder sends one request per transaction or JSON-RPC batches (the gateway counted one per transaction).
- The epoch-change cooldown reset (Q6), read from timing only.
