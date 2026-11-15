# Run facts: r20261115-1653 (from benchmark/results/r20261115-1653/manifest.json; cite, do not re-derive)

- Node image: `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c`, digest `sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c`, pinned=us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c; node commit `91a15e22376fa1277c107824e738dce689792c56`, version `0.1.0`; build features `faucet`.
- Storage engine named in the manifest: `tn-lmdb`.
- Generator image digest `sha256:7cefcc505201b2e40361a7d8cfe034778090b76c568cb2400369bf566c605a59`, commit `62bbd5f`.
- Machine `c3-highcpu-8`; node disk {"size_gb": 100, "type": "hyperdisk-balanced", "provisioned_iops": 20000, "provisioned_throughput": 800}; boot image `{'ref': 'projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105', 'name': 'ubuntu-2404-noble-amd64-v20261105', 'status': 'READY', 'deprecation_state': None}`.
- Harness at deploy: `2ff39153a9d0` (dirty=True; the dirt is under tasks/, benchmark/ was at its last commit).
- Deploy: start 2026-11-15T16:53:30Z, nodes healthy 2026-11-15T17:29:46Z, contracts done 2026-11-15T17:40:35Z, step 12 done 2026-11-15T17:40:41Z; coordinated start {"due": 1794762830, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 0, "max_late_secs": 0, "ts": "2026-11-15T17:21:38Z"}.
- Arm `bench7-adaptive` (benchmark/arms/bench7-adaptive.arm, sha256 `41babf9189f3cd2491fc07cc29510be760bda9fcb0e6702ae2541c086ed9727e`), applied 2026-11-15T17:13:50Z via prestart: `quorum_exec_block`=true, `quorum_exec_block_starved_rounds`=4, `vote_queue_fix`=true, `digest_order_hold`=true, `epoch_record_collect_past_uncertified`=true, `epoch_record_conflict_halt`=true, `epoch_record_recertify`=true.
- Funding: 2026-11-15T17:51:27Z to 2026-11-15T17:52:51Z.

## Blasts (real phases, `manifest.blasts[].phases`)

| blast | kind | senders × window | started | ended | rc | preamble | warmup | mixed | cooldown |
|---|---|---|---|---|---|---|---|---|---|
| 0 | light | 8 × 16 | 2026-11-15T17:53:09Z | 2026-11-15T18:05:36Z | 0 | 17:55:44–17:55:47 | 17:55:45–17:56:47 | 17:56:45–18:02:47 | 18:02:45–18:03:17 |
| 1 | light | 600 × 4 | 2026-11-15T18:05:36Z | 2026-11-15T18:18:04Z | 0 | 18:08:13–18:08:33 | 18:08:19–18:09:33 | 18:09:19–18:15:33 | 18:15:19–18:15:36 |
| 2 | load | 600 × 16 | 2026-11-15T18:18:04Z | 2026-11-15T19:10:51Z | 0 | 18:23:13–18:23:31 | 18:23:20–18:25:31 | 18:25:20–19:05:31 | 19:05:20–19:05:53 |

Times of day are UTC on the run's date; every figure's window comes from these, not from the planned phases.

## Chaos (`manifest.chaos`)

- 2026-11-15T18:44:01Z `bench-validator-05`: docker kill -s KILL telcoin (rc 0) {"planned": {"closing_epoch": 4, "boundary_unix": 1794768300, "restart_unix": 1794768541}, "crossed_boundary": true, "late_secs": 0.162}
- 2026-11-15T18:49:01Z `bench-validator-05`: systemctl start telcoin (rc 0) {"late_secs": 0.067}
- 2026-11-15T18:54:01Z `bench-observer-11`: systemctl restart telcoin (rc 0) {"late_secs": 0.097}

## End of the run

- Fleet ready check `step15` at 2026-11-15T19:14:43Z: ok=True, modes: 01=CvvActive, 02=CvvActive, 03=CvvActive, 04=CvvActive, 05=CvvActive, 06=CvvActive, 07=CvvActive, 08=CvvActive, 09=CvvActive, 10=CvvActive.
- Deploy result: {"rc": 0, "last_step": 15, "first_error": null, "started": "2026-11-15T17:46:24Z", "ended": "2026-11-15T19:19:08Z", "scope": "steps 13..15", "log": "logs/deploy-20261115T174624Z.log"}.
- Abort: null.
- Prometheus window in the manifest: {"start": "2026-11-15T17:29:46Z", "end": "2026-11-15T19:17:46Z", "end_reason": "fleet_ready", "waited_secs": 230, "confirm_secs": 180}.
- Log coverage: [{"inst": "bench-validator-01", "generations": 1, "first_ts": "2026-11-15T17:06:18Z", "last_ts": "2026-11-15T19:23:49Z", "due": "2026-11-15T17:13:50Z", "blast_end": "2026-11-15T19:09:09Z", "ok": true, "checked_at": "2026-11-15T19:30:45Z"}, {"inst": "bench-validator-02", "generations": 1, "first_ts": "2026-11-15T17:06:25Z", "last_ts": "2026-11-15T19:23:50Z", "due": "2026-11-15T17:13:50Z", "blast_end": "2026-11-15T19:09:09Z", "ok": true, "checked_at": "2026-11-15T19:30:45Z"}, {"inst": "bench-validator-03", "generations": 1, "first_ts": "2026-11-15T17:06:45Z", "last_ts": "2026-11-15T19:23:53Z", ".
- Archive: {"kind": "local", "path": "/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261115-1653", "verified_at": "2026-11-15T19:30:45Z", "files": 649, "bytes": 2632508353, "final_index_at": "2026-11-15T19:33:54Z", "reindexed_at": "2026-11-15T19:34:24Z"}.

## Lines of tasks/bench6/r20261115-1653/deploy12-20261115T165326Z.log

- `FSYNC_PROBE bench-validator-01 p50_us=1000 p95_us=1264`
- `FSYNC_PROBE bench-validator-02 p50_us=1091 p95_us=1696`
- `FSYNC_PROBE bench-validator-03 p50_us=1074 p95_us=1300`
- `FSYNC_PROBE bench-validator-04 p50_us=1152 p95_us=1627`
- `FSYNC_PROBE bench-validator-05 p50_us=1099 p95_us=1343`
- `FSYNC_PROBE bench-validator-06 p50_us=1153 p95_us=1435`
- `FSYNC_PROBE bench-validator-07 p50_us=1102 p95_us=1546`
- `FSYNC_PROBE bench-validator-08 p50_us=1054 p95_us=1434`
- `FSYNC_PROBE bench-validator-09 p50_us=1028 p95_us=1297`
- `FSYNC_PROBE bench-validator-10 p50_us=1066 p95_us=1435`
- `FSYNC_PROBE bench-observer-11 p50_us=965 p95_us=1217`
- `FSYNC_PROBE_SUMMARY median_us=1074 slow=[] probe_failed=[]`
- `HOST_PROBE_SUMMARY kernel=7.0.0-1017-gcp image=20261105 ra_kb=128 uniform=yes differ=[] probe_failed=[]`
- `BENCH_DEPLOY_RESULT rc=0 last_step=12 first_error=- log=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261115-1653/logs/deploy-20261115T165326Z.log`

## By hand (the orchestrator)

- Run 7b, form `adaptive` (`quorum_exec_block_starved_rounds` 4). Chain log `tasks/bench7/r20261115-1653/chain-20261115T165325Z.log`.
- This is the SECOND attempt at run 7b. The first, `r20261115-1450`, was lost: the cloud login expired 16 minutes into its blast segment (16:24Z), during the first light blast; its load blast never ran; its fleet was torn down at 16:53:02Z. It is not a bench 7 run and no figure comes from it. This run used a fresh fleet, the same image digest and an env identical but for the run id.
- The idle check stopped the chain (17:45:57Z): `up=10/11 missing=bench-validator-05`; modes ok (ten `CvvActive`, one observer), switches ok (seven gauges at 1 on 11 nodes). The blast was launched by hand at 17:46:24Z; the fleet idled 5.6 min between the deploy's end (17:40:48Z) and the blast's launch (run 7a: 15.7 min). The validator-05 kill therefore fell in closing epoch 4 here and in closing epoch 5 in run 7a (`manifest.chaos[0].planned.closing_epoch`).
- **Prometheus series are partial for two validators** (the nodes were healthy; their logs are whole): the metrics agent lost one remote-write batch of every scrape on each.
  - bench-validator-01, the whole run: `tn_engine_persist_duration_seconds` is not in Prometheus (the export's check names it; about 1,800 of its ~4,200 series are missing in all: check `INDEX.tsv` and the series' `node` label before you take a figure over validators from the export).
  - bench-validator-05, from its start until its kill (18:44:01Z): `up`, `tn_reth_persist_save_blocks_seconds`, `tn_executor_output_transactions` and about 500 other series are not in Prometheus; after its restart (18:49:01Z, a new process) they are.
  - A figure over validators taken from a series one of them lacks names the validators it covers and says so.
- **What stands in for it, for EVERY node: per-minute samples of each node's own metrics endpoint** (`benchmark/private/bench7-r20261115-1653/endpoint-snapshots/<node>-metrics-<UTC>.txt.gz`, the exporter's text as the agent scrapes it, 5,100 series a node): one sample of all 11 at 17:46:24Z (before the blast), then every 60 s from 17:46:32Z to 19:19:36Z (94 rounds; validator-05 has no sample in the five rounds of its outage, 18:44:37–18:48:36Z, and its counters restart from zero at its restart). Counters and histograms are cumulative since the node process started, so the difference of two samples is that window's total; the node's own `network` label (`primary` / `worker-0`) is intact there. Run 7a has no such samples (only two end-of-run snapshots), so a per-minute figure exists for this run only.
- On every node (as in run 7a): the agent's target label `network` replaces the node's own, so about 910 series pairs collapse into one in Prometheus; the endpoint samples hold both.
- No action on the live fleet besides the harness's own and the read-only samples (one `curl` of the node's exporter over ssh per node per minute, against the agent's four scrapes a minute).
- Metric export: window 17:08:30Z to 19:19:50Z, step 15 s, 397 metrics, 22,759 series, every `INDEX.tsv` row ok (`benchmark/private/bench7-r20261115-1653/prom-export/`); check lines in `tasks/bench7/r20261115-1653/prom-export-check.txt` (29 ok, 3 lazy, 4 with nothing or almost nothing counted, 1 incomplete = validator-01's `tn_engine_persist_duration_seconds`); exported with `--allow-missing`. The check asks "any sample in the window", so validator-05's pre-kill gap does not show in it.
- Fleet health at the blast's end: 11 of 11 nodes, `fatal_db=0`, `halt=0`, blocks 96,259–96,263, disk at most 25 % (`tasks/bench7/r20261115-1653/fleet-health-blast15-20261115T174624Z.log`).
- Teardown: `TEARDOWN_DONE run=r20261115-1653 deleted=12 left=0 at=2026-11-15T19:34:12Z`. Reindex: 649 files, 2,632,508,353 bytes.
- Archive: `ARCHIVE_VERIFY ok=1 run=r20261115-1653 files=626 bytes=2632212196 objects=626 problems=0` to `gs://tn-devnet-benchmark-archive/runs/r20261115-1653/results/` (19:39:59Z); no bench instance listed afterwards (19:40:01Z). The metric export and the endpoint samples are under `benchmark/private/` and are NOT in the archive.
- No preliminary read was written for this run.

## Found by the analysis (the orchestrator adds these as units hand back; cite the unit's file, not this list)

- The arms summary of this run (`benchmark/private/bench7-r20261115-1653/A1/arms/arms.json`, sha256 `b15f7d00…7bfd`) has THREE rows: blast 0 (L), blast 1 (M4: all ten generators overlap in its mixed phase for 346 s) and blast 2 cut at the kill (M16, 18:25:31–18:44:01Z). Per-node blocks sit under `summary_rows[i]`. Run 7a's has no blast-1 row.
- No generator lost preamble steps or had its preamble wait cut in this run (`A1/preamble.json`); in run 7a generator 06's wait ran its full 600 s in blast 1.
- In the light blasts the generators of validators 02 and 06 (the two far validators) land far less than the rest: blast 0, 2.2 and 1.8 tx/s against a median of 88.3 for the other eight, seen p50 56.5 and 62.1 s; blast 1, 169.6 and 157.0 tx/s against 1,186.6 (`A1/kpis.md`). Counted by the KPI analysis; the loss analysis owns the explanation.
- Decisions on units' questions: `tasks/bench7/analysis-decisions.md`.
