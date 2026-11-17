# Run facts: r20261116-2011 (from benchmark/results/r20261116-2011/manifest.json; cite, do not re-derive)

- Node image: `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, digest `sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, pinned=us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a; node commit `b1104905f1c2ca86166e51fa231bf55f3e40fde2`, version `0.1.0`; build features `faucet`.
- Storage engine named in the manifest: `tn-lmdb`.
- Generator image digest `sha256:7cefcc505201b2e40361a7d8cfe034778090b76c568cb2400369bf566c605a59`, commit `62bbd5f`.
- Machine `c3-highcpu-8`; node disk {"size_gb": 100, "type": "hyperdisk-balanced", "provisioned_iops": 20000, "provisioned_throughput": 800}; boot image `{'ref': 'projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105', 'name': 'ubuntu-2404-noble-amd64-v20261105', 'status': 'READY', 'deprecation_state': None}`.
- Harness at deploy: `14e20773c566` (dirty=True; the dirt is under tasks/, benchmark/ was at its last commit).
- Deploy: start 2026-11-16T20:12:01Z, nodes healthy 2026-11-16T20:50:47Z, contracts done 2026-11-16T21:16:45Z, step 12 done 2026-11-16T21:16:50Z; coordinated start {"due": 1794861349, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 0, "max_late_secs": 0, "ts": "2026-11-16T20:43:09Z"}.
- Arm `bench8-floor16` (benchmark/arms/bench8-floor16.arm, sha256 `4d496c53c95886afcfa930503f5f1264792e9384e9687ba15b40db5e688768cf`), applied 2026-11-16T20:35:49Z via prestart: `quorum_exec_block`=true, `quorum_exec_block_starved_rounds`=0, `quorum_exec_block_floor_outputs`=16, `vote_queue_fix`=true, `digest_order_hold`=true, `epoch_record_collect_past_uncertified`=true, `epoch_record_conflict_halt`=true, `epoch_record_recertify`=true.
- Funding: 2026-11-16T21:21:23Z to 2026-11-16T21:22:42Z.

## Blasts (real phases, `manifest.blasts[].phases`)

| blast | kind | senders × window | started | ended | rc | preamble | warmup | mixed | cooldown |
|---|---|---|---|---|---|---|---|---|---|
| 0 | light | 8 × 16 | 2026-11-16T21:22:58Z | 2026-11-16T21:35:17Z | 0 | 21:25:33–21:25:36 | 21:25:35–21:26:36 | 21:26:35–21:32:36 | 21:32:35–21:32:53 |
| 1 | light | 600 × 4 | 2026-11-16T21:35:17Z | 2026-11-16T21:47:42Z | 0 | 21:37:54–21:38:13 | 21:38:00–21:39:13 | 21:39:00–21:45:13 | 21:45:01–21:45:24 |
| 2 | load | 600 × 16 | 2026-11-16T21:47:42Z | 2026-11-16T22:40:38Z | 0 | 21:52:49–21:53:11 | 21:52:55–21:55:11 | 21:54:55–22:35:11 | 22:34:55–22:36:12 |

Times of day are UTC on the run's date; every figure's window comes from these, not from the planned phases.

## Chaos (`manifest.chaos`)

- 2026-11-16T22:26:12Z `bench-validator-05`: docker kill -s KILL telcoin (rc 0) {"planned": {"closing_epoch": 5, "boundary_unix": 1794868031, "restart_unix": 1794868272}, "crossed_boundary": true, "late_secs": 0.134}
- 2026-11-16T22:31:12Z `bench-validator-05`: systemctl start telcoin (rc 0) {"late_secs": 0.101}
- 2026-11-16T22:36:12Z `bench-observer-11`: systemctl restart telcoin (rc 0) {"late_secs": 0.074}

## End of the run

- Fleet ready check `step15` at 2026-11-16T22:49:29Z: ok=True, modes: 01=CvvActive, 02=CvvActive, 03=CvvActive, 04=CvvActive, 05=CvvActive, 06=CvvActive, 07=CvvActive, 08=CvvActive, 09=CvvActive, 10=CvvActive.
- Deploy result: {"rc": 0, "last_step": 15, "first_error": null, "started": "2026-11-16T21:16:52Z", "ended": "2026-11-16T22:53:43Z", "scope": "steps 13..15", "log": "logs/deploy-20261116T211652Z.log"}.
- Abort: null.
- Prometheus window in the manifest: {"start": "2026-11-16T20:50:47Z", "end": "2026-11-16T22:52:31Z", "end_reason": "fleet_ready", "waited_secs": 535, "confirm_secs": 180}.
- Log coverage: null.
- Archive: null.

## Lines of tasks/bench6/r20261116-2011/deploy12-20261116T201156Z.log

- `FSYNC_PROBE bench-validator-01 p50_us=1067 p95_us=1333`
- `FSYNC_PROBE bench-validator-02 p50_us=1048 p95_us=1370`
- `FSYNC_PROBE bench-validator-03 p50_us=1107 p95_us=1347`
- `FSYNC_PROBE bench-validator-04 p50_us=1181 p95_us=1532`
- `FSYNC_PROBE bench-validator-05 p50_us=1175 p95_us=1495`
- `FSYNC_PROBE bench-validator-06 p50_us=1081 p95_us=1506`
- `FSYNC_PROBE bench-validator-07 p50_us=1091 p95_us=1813`
- `FSYNC_PROBE bench-validator-08 p50_us=977 p95_us=1400`
- `FSYNC_PROBE bench-validator-09 p50_us=915 p95_us=1278`
- `FSYNC_PROBE bench-validator-10 p50_us=1010 p95_us=1303`
- `FSYNC_PROBE bench-observer-11 p50_us=1124 p95_us=1425`
- `FSYNC_PROBE_SUMMARY median_us=1081 slow=[] probe_failed=[]`
- `HOST_PROBE_SUMMARY kernel=7.0.0-1017-gcp image=20261105 ra_kb=128 uniform=yes differ=[] probe_failed=[]`
- `BENCH_DEPLOY_RESULT rc=0 last_step=12 first_error=- log=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261116-2011/logs/deploy-20261116T201156Z.log`

## By hand (the orchestrator)


## By hand (the orchestrator)

- Run 1 of bench 8 (run F: bench 7's always-on arm with `quorum_exec_block_floor_outputs` 16). Chain log `tasks/bench8/r20261116-2011/chain-20261116T201155Z.log`: deploy12 rc 0 at 21:16:51Z; idle checks passed in round 1 (up 11/11, ten `cvv_active` and one observer, eight switches on 11 nodes, the floor read back as 16 on every node); blast15 launched at once, rc 0 at 22:53:43Z; the fleet idled 0 s between the deploy's end and the blast's start.
- The endpoint sampler ran as a segment of the chain: every node's own exporter text every 60 s from 21:16:51Z to 22:53:57Z (`tasks/bench8/r20261116-2011/endpoint-samples/`, 97 rounds, 11/11 each round as far as the log shows), with the host block (clock source chrony and its offsets, the aggregate cpu line of `/proc/stat`, `clk_tck`).
- Export check (`prom-export-check.txt`, window 20:48 to 22:55Z): 41 must-haves: 33 ok, 4 lazy, 4 absent, none incomplete. Coverage: five series stopped in Prometheus after the kill (validator-03 from 22:27:45Z: `tn_engine_persist_duration_seconds_count` and the three `tn_primary_vote_exec_deficit_outputs` series; observer-11 from 22:36:15Z: `tn_executor_output_transactions_count`), nine gaps on validator-05 and the observer after their restarts, 29 expected gaps. Everything before the kill is whole on every node. `up` lacked validator-03 and the observer at the end although both nodes were healthy (the fleet-ready check at 22:49:29Z shows ten `CvvActive`): the metrics agent's lost remote-write batch (tn-node-deployment #66). The endpoint samples stand in for the stopped series.
- Exported with `--allow-missing` at 22:58:38Z: `benchmark/private/bench8-r20261116-2011/prom-export`, 400 metrics, 23,245 series, 11,999,524 points, 20 MB, window 20:38 to 22:57Z (`prom-export.log`).
- Teardown: dry rc 0 (12 instances, 2 firewall rules, 1 bucket, 13 disks; the devnet's instances present and untouched); teardown `TEARDOWN_DONE run=r20261116-2011 deleted=12 left=0 at=2026-11-16T23:10:27Z`, rc 0. Reindex: 649 files, 3,074,580,815 bytes. Archive: `ARCHIVE_VERIFY ok=1 files=626 bytes=3074284753 problems=0` to `gs://tn-devnet-benchmark-archive/runs/r20261116-2011/results/` (23:17:24Z). Local: `benchmark/results/r20261116-2011` (2.9 GB); the export and the endpoint samples are private and not in the archive: keep.
- The harness's own certification count over the load blast's whole mixed phase (`analysis/certification.json`, window "blast 2 mixed", the kill included): proposed 63,519, quorum 62,290, 98.07 %; per validator 01 100.0, 02 89.0, 03 100.0, 04 97.8, 05 99.4, 06 99.8, 07 98.8, 08 100.0, 09 100.0, 10 96.1. Run 7a by the same count: 52,702 / 50,378, 95.59 % (06 83.6, 08 85.5, 04 95.6, 10 97.7). One run each.
- Blast 1 (light, 600 × 4): mixed phase 21:39:00 to 21:45:13 (6 min) against 16 min in run 7a.
- The automatic part of this file was generated while the teardown was still running, so it reads the manifest's `archive` and log coverage as null; the manifest in the results directory has both filled (archive: 649 files, 3,074,580,815 bytes; log coverage: 11 entries).
