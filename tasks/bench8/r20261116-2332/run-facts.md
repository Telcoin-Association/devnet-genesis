# Run facts: r20261116-2332 (from benchmark/results/r20261116-2332/manifest.json; cite, do not re-derive)

- Node image: `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, digest `sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, pinned=us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a; node commit `b1104905f1c2ca86166e51fa231bf55f3e40fde2`, version `0.1.0`; build features `faucet`.
- Storage engine named in the manifest: `tn-lmdb`.
- Generator image digest `sha256:7cefcc505201b2e40361a7d8cfe034778090b76c568cb2400369bf566c605a59`, commit `62bbd5f`.
- Machine `c3-highcpu-8`; node disk {"size_gb": 100, "type": "hyperdisk-balanced", "provisioned_iops": 20000, "provisioned_throughput": 800}; boot image `{'ref': 'projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105', 'name': 'ubuntu-2404-noble-amd64-v20261105', 'status': 'READY', 'deprecation_state': None}`.
- Harness at deploy: `037b8c85c856` (dirty=True; the dirt is under tasks/, benchmark/ was at its last commit).
- Deploy: start 2026-11-16T23:32:50Z, nodes healthy 2026-11-17T00:07:43Z, contracts done 2026-11-17T00:16:11Z, step 12 done 2026-11-17T00:16:16Z; coordinated start {"due": 1794873136, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 0, "max_late_secs": 0, "ts": "2026-11-16T23:59:56Z"}.
- Arm `bench8-control` (benchmark/arms/bench8-control.arm, sha256 `4ab67735ee8fe28580da804a725fac51b76053036f0c47749b7680a452d8cd7f`), applied 2026-11-16T23:52:16Z via prestart: `quorum_exec_block`=true, `quorum_exec_block_starved_rounds`=0, `quorum_exec_block_floor_outputs`=8, `vote_queue_fix`=true, `digest_order_hold`=true, `epoch_record_collect_past_uncertified`=true, `epoch_record_conflict_halt`=true, `epoch_record_recertify`=true.
- Funding: 2026-11-17T00:21:03Z to 2026-11-17T00:22:24Z.

## Blasts (real phases, `manifest.blasts[].phases`)

| blast | kind | senders × window | started | ended | rc | preamble | warmup | mixed | cooldown |
|---|---|---|---|---|---|---|---|---|---|
| 0 | light | 8 × 16 | 2026-11-17T00:22:44Z | 2026-11-17T00:35:06Z | 0 | 00:25:19–00:25:59 | 00:25:20–00:26:59 | 00:26:20–00:32:59 | 00:32:20–00:33:26 |
| 1 | light | 600 × 4 | 2026-11-17T00:35:06Z | 2026-11-17T00:47:31Z | 0 | 00:37:42–00:38:08 | 00:37:49–00:39:08 | 00:38:49–00:45:08 | 00:44:49–00:45:13 |
| 2 | load | 600 × 16 | 2026-11-17T00:47:31Z | 2026-11-17T01:40:18Z | 0 | 00:52:37–00:52:53 | 00:52:44–00:54:53 | 00:54:44–01:34:53 | 01:34:44–01:35:18 |

Times of day are UTC on the run's date; every figure's window comes from these, not from the planned phases.

## Chaos (`manifest.chaos`)

- 2026-11-17T01:22:43Z `bench-validator-05`: docker kill -s KILL telcoin (rc 0) {"planned": {"closing_epoch": 4, "boundary_unix": 1794878622, "restart_unix": 1794878863}, "crossed_boundary": true, "late_secs": 0.016}
- 2026-11-17T01:27:43Z `bench-validator-05`: systemctl start telcoin (rc 0) {"late_secs": 0.049}
- 2026-11-17T01:32:43Z `bench-observer-11`: systemctl restart telcoin (rc 0) {"late_secs": 0.086}

## End of the run

- Fleet ready check `step15` at 2026-11-17T02:06:00Z: ok=True, modes: 01=CvvActive, 02=CvvActive, 03=CvvActive, 04=CvvActive, 05=CvvActive, 06=CvvActive, 07=CvvActive, 08=CvvActive, 09=CvvActive, 10=CvvActive.
- Deploy result: {"rc": 0, "last_step": 15, "first_error": null, "started": "2026-11-17T00:16:32Z", "ended": "2026-11-17T02:07:11Z", "scope": "steps 13..15", "log": "logs/deploy-20261117T001632Z.log"}.
- Abort: null.
- Prometheus window in the manifest: {"start": "2026-11-17T00:07:43Z", "end": "2026-11-17T02:06:00Z", "end_reason": "max_wait", "waited_secs": 1366, "confirm_secs": null}.
- Log coverage: [{"inst": "bench-validator-01", "generations": 1, "first_ts": "2026-11-16T23:44:56Z", "last_ts": "2026-11-17T02:15:56Z", "due": "2026-11-16T23:52:16Z", "blast_end": "2026-11-17T01:38:33Z", "ok": true, "checked_at": "2026-11-17T02:23:55Z"}, {"inst": "bench-validator-02", "generations": 1, "first_ts": "2026-11-16T23:45:09Z", "last_ts": "2026-11-17T02:15:58Z", "due": "2026-11-16T23:52:16Z", "blast_end": "2026-11-17T01:38:33Z", "ok": true, "checked_at": "2026-11-17T02:23:55Z"}, {"inst": "bench-validator-03", "generations": 1, "first_ts": "2026-11-16T23:45:21Z", "last_ts": "2026-11-17T02:16:01Z", ".
- Archive: {"kind": "local", "path": "/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261116-2332", "verified_at": "2026-11-17T02:23:55Z", "files": 649, "bytes": 2992767362, "final_index_at": "2026-11-17T02:28:12Z", "reindexed_at": "2026-11-17T02:28:53Z"}.

## Lines of tasks/bench6/r20261116-2332/deploy12-20261116T233247Z.log

- `FSYNC_PROBE bench-validator-01 p50_us=1156 p95_us=1524`
- `FSYNC_PROBE bench-validator-02 p50_us=1079 p95_us=1507`
- `FSYNC_PROBE bench-validator-03 p50_us=1027 p95_us=1327`
- `FSYNC_PROBE bench-validator-04 p50_us=1221 p95_us=1662`
- `FSYNC_PROBE bench-validator-05 p50_us=1062 p95_us=1308`
- `FSYNC_PROBE bench-validator-06 p50_us=1065 p95_us=1355`
- `FSYNC_PROBE bench-validator-07 p50_us=1126 p95_us=1596`
- `FSYNC_PROBE bench-validator-08 p50_us=1130 p95_us=1448`
- `FSYNC_PROBE bench-validator-09 p50_us=989 p95_us=1263`
- `FSYNC_PROBE bench-validator-10 p50_us=939 p95_us=1213`
- `FSYNC_PROBE bench-observer-11 p50_us=995 p95_us=1328`
- `FSYNC_PROBE_SUMMARY median_us=1065 slow=[] probe_failed=[]`
- `HOST_PROBE_SUMMARY kernel=7.0.0-1017-gcp image=20261105 ra_kb=128 uniform=yes differ=[] probe_failed=[]`
- `BENCH_DEPLOY_RESULT rc=0 last_step=12 first_error=- log=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261116-2332/logs/deploy-20261116T233247Z.log`

## By hand (the orchestrator)


## By hand (the orchestrator)

- Run 2 of bench 8 (run C: the control; bench 7's always-on arm on bench 8's image, `quorum_exec_block_floor_outputs` 8). It differs from run 1 (`r20261116-2011`) only in the arm's floor. Chain log `tasks/bench8/r20261116-2332/chain-20261116T233246Z.log`: deploy12 rc 0 and idle checks passed at 00:16:32Z (up for bench-observer-11 and bench-validator-10 came through the endpoint fallback; ten `cvv_active` and one observer; eight switches on 11 nodes; the floor read back as 8 on every node); blast15 rc 0 at 02:07:22Z; the fleet-ready check passed at 02:06:00Z after waiting 1,272 s (run 1: 260 s).
- The load blast's mixed phase began 54 min 48 s after the coordinated start (run 1: 71 min 46 s; the deploy's steps between the start and the blast were faster), so the epochs sit differently under the load than in run 1: take the epoch boundaries from validator-01's lines.
- The endpoint sampler ran from 00:16:32Z to the chain's end (`tasks/bench8/r20261116-2332/endpoint-samples/`, 2,520 files).
- Export check (`prom-export-check.txt`, window 00:05 to 02:10Z): 41 must-haves: 30 ok, 4 lazy, 4 absent, 3 incomplete: Prometheus has no `tn_primary_vote_stage_seconds_count` for validator-10, no `tn_engine_persist_duration_seconds_count` for validators 03 and 10 and no `tn_reth_persist_commit_seconds_count` for validator-03, for the whole run (the metrics agent's lost remote-write batch, tn-node-deployment #66). The endpoint samples stand in.
- Exported with `--allow-missing` at 02:15:02Z: `benchmark/private/bench8-r20261116-2332/prom-export`, 400 metrics, 22,974 series, 11,013,831 points, 20 MB, window 23:55 to 02:14Z.
- Teardown: dry rc 0 (12 instances, 2 firewall rules, 1 bucket, 13 disks; the devnet's instances present and untouched); `TEARDOWN_DONE run=r20261116-2332 deleted=12 left=0 at=2026-11-17T02:28:38Z`, rc 0. Reindex: 649 files, 2,992,767,362 bytes. Archive: `ARCHIVE_VERIFY ok=1 files=626 bytes=2992471535 problems=0` to `gs://tn-devnet-benchmark-archive/runs/r20261116-2332/results/` (02:35:53Z).
- The harness's own certification count over the load blast's whole mixed phase (`analysis/certification.json`, "blast 2 mixed", the kill included): proposed 52,873, quorum 51,458, 97.32 %; per validator 01 99.9, 02 92.2, 03 98.2, 04 98.5, 05 96.8, 06 98.5, 07 98.1, 08 99.3, 09 93.3, 10 98.5. By the same count: run 1 (floor 16) 63,519 / 62,290, 98.07 %; run 7a (floor 8) 52,702 / 50,378, 95.59 %. One run each.
