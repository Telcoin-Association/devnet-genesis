# Run facts: r20261115-1131 (from benchmark/results/r20261115-1131/manifest.json; cite, do not re-derive)

- Node image: `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c`, digest `sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c`, pinned=us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c; node commit `91a15e22376fa1277c107824e738dce689792c56`, version `0.1.0`; build features `faucet`.
- Storage engine named in the manifest: `tn-lmdb`.
- Generator image digest `sha256:7cefcc505201b2e40361a7d8cfe034778090b76c568cb2400369bf566c605a59`, commit `62bbd5f`.
- Machine `c3-highcpu-8`; node disk {"size_gb": 100, "type": "hyperdisk-balanced", "provisioned_iops": 20000, "provisioned_throughput": 800}; boot image `{'ref': 'projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105', 'name': 'ubuntu-2404-noble-amd64-v20261105', 'status': 'READY', 'deprecation_state': None}`.
- Harness at deploy: `d8483104c39c` (dirty=True; the dirt is under tasks/, benchmark/ was at its last commit).
- Deploy: start 2026-11-15T11:31:38Z, nodes healthy 2026-11-15T12:07:04Z, contracts done 2026-11-15T12:24:33Z, step 12 done 2026-11-15T12:24:39Z; coordinated start {"due": 1794743498, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 0, "max_late_secs": 0, "ts": "2026-11-15T11:59:06Z"}.
- Arm `bench7-always` (benchmark/arms/bench7-always.arm, sha256 `cc559678205a6cc334c3f391c4075f911bae723ec12d742a602ee4e4a413ffb0`), applied 2026-11-15T11:51:38Z via prestart: `quorum_exec_block`=true, `quorum_exec_block_starved_rounds`=0, `vote_queue_fix`=true, `digest_order_hold`=true, `epoch_record_collect_past_uncertified`=true, `epoch_record_conflict_halt`=true, `epoch_record_recertify`=true.
- Funding: 2026-11-15T12:44:58Z to 2026-11-15T12:46:21Z.

## Blasts (real phases, `manifest.blasts[].phases`)

| blast | kind | senders × window | started | ended | rc | preamble | warmup | mixed | cooldown |
|---|---|---|---|---|---|---|---|---|---|
| 0 | light | 8 × 16 | 2026-11-15T12:46:43Z | 2026-11-15T12:59:26Z | 0 | 12:49:20–12:50:06 | 12:49:21–12:51:06 | 12:50:21–12:57:06 | 12:56:21–12:57:30 |
| 1 | light | 600 × 4 | 2026-11-15T12:59:26Z | 2026-11-15T13:20:44Z | 0 | 13:02:04–13:12:05 | 13:02:11–13:13:05 | 13:03:11–13:19:05 | 13:09:11–13:19:24 |
| 2 | load | 600 × 16 | 2026-11-15T13:20:44Z | 2026-11-15T14:13:48Z | 0 | 13:25:51–13:26:23 | 13:25:58–13:28:23 | 13:27:58–14:08:23 | 14:07:58–14:08:33 |

Times of day are UTC on the run's date; every figure's window comes from these, not from the planned phases.

## Chaos (`manifest.chaos`)

- 2026-11-15T13:41:35Z `bench-validator-05`: docker kill -s KILL telcoin (rc 0) {"planned": {"closing_epoch": 5, "boundary_unix": 1794750154, "restart_unix": 1794750395}, "crossed_boundary": true, "late_secs": 0.1}
- 2026-11-15T13:46:35Z `bench-validator-05`: systemctl start telcoin (rc 0) {"late_secs": 0.115}
- 2026-11-15T13:51:35Z `bench-observer-11`: systemctl restart telcoin (rc 0) {"late_secs": 0.116}

## End of the run

- Fleet ready check `step15` at 2026-11-15T14:17:58Z: ok=True, modes: 01=CvvActive, 02=CvvActive, 03=CvvActive, 04=CvvActive, 05=CvvActive, 06=CvvActive, 07=CvvActive, 08=CvvActive, 09=CvvActive, 10=CvvActive.
- Deploy result: {"rc": 0, "last_step": 15, "first_error": null, "started": "2026-11-15T12:40:20Z", "ended": "2026-11-15T14:22:25Z", "scope": "steps 13..15", "log": "logs/deploy-20261115T124020Z.log"}.
- Abort: null.
- Prometheus window in the manifest: {"start": "2026-11-15T12:07:04Z", "end": "2026-11-15T14:21:00Z", "end_reason": "fleet_ready", "waited_secs": 235, "confirm_secs": 180}.
- Log coverage: [{"inst": "bench-validator-01", "generations": 1, "first_ts": "2026-11-15T11:43:50Z", "last_ts": "2026-11-15T14:28:24Z", "due": "2026-11-15T11:51:38Z", "blast_end": "2026-11-15T14:12:05Z", "ok": true, "checked_at": "2026-11-15T14:38:32Z"}, {"inst": "bench-validator-02", "generations": 1, "first_ts": "2026-11-15T11:43:57Z", "last_ts": "2026-11-15T14:28:25Z", "due": "2026-11-15T11:51:38Z", "blast_end": "2026-11-15T14:12:05Z", "ok": true, "checked_at": "2026-11-15T14:38:32Z"}, {"inst": "bench-validator-03", "generations": 1, "first_ts": "2026-11-15T11:44:15Z", "last_ts": "2026-11-15T14:28:29Z", ".
- Archive: {"kind": "local", "path": "/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261115-1131", "verified_at": "2026-11-15T14:38:32Z", "files": 650, "bytes": 2971858952, "final_index_at": "2026-11-15T14:42:18Z", "reindexed_at": "2026-11-15T14:43:04Z"}.

## Lines of tasks/bench6/r20261115-1131/deploy12-20261115T113133Z.log

- `FSYNC_PROBE bench-validator-01 p50_us=1036 p95_us=1286`
- `FSYNC_PROBE bench-validator-02 p50_us=1230 p95_us=1681`
- `FSYNC_PROBE bench-validator-03 p50_us=1044 p95_us=1317`
- `FSYNC_PROBE bench-validator-04 p50_us=1181 p95_us=1516`
- `FSYNC_PROBE bench-validator-05 p50_us=1147 p95_us=1445`
- `FSYNC_PROBE bench-validator-06 p50_us=1206 p95_us=1609`
- `FSYNC_PROBE bench-validator-07 p50_us=1224 p95_us=1649`
- `FSYNC_PROBE bench-validator-08 p50_us=828 p95_us=1154`
- `FSYNC_PROBE bench-validator-09 p50_us=1028 p95_us=1284`
- `FSYNC_PROBE bench-validator-10 p50_us=916 p95_us=1359`
- `FSYNC_PROBE bench-observer-11 p50_us=1020 p95_us=1223`
- `FSYNC_PROBE_SUMMARY median_us=1044 slow=[] probe_failed=[]`
- `HOST_PROBE_SUMMARY kernel=7.0.0-1017-gcp image=20261105 ra_kb=128 uniform=yes differ=[] probe_failed=[]`
- `BENCH_DEPLOY_RESULT rc=0 last_step=12 first_error=- log=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261115-1131/logs/deploy-20261115T113133Z.log`

## By hand (the orchestrator)

- Run 7a, form `always` (`quorum_exec_block_starved_rounds` 0). Chain log `tasks/bench7/r20261115-1131/chain-20261115T113132Z.log`.
- The idle check stopped the chain (12:30:02Z): `up=10/11 missing=bench-validator-09`; modes ok (ten `CvvActive`, one observer), switches ok (seven gauges at 1 on 11 nodes). The blast was launched by hand at 12:40:20Z; the fleet idled 15.7 min between the deploy's end and the blast's start.
- **bench-validator-09's Prometheus series are partial for the whole run** (the node itself was healthy and its logs are whole): its metrics agent lost one remote-write batch of every scrape. Not in Prometheus for validator-09: `up`, `scrape_*`, `tn_engine_root_seconds`, `tn_executor_output_transactions`, `tn_primary_vote_stage_seconds`, `tn_primary_uncertified_report_dropped_total`, `tn_reth_persist_save_blocks_seconds`, `tn_storage_tndb_write_stall_seconds`, `tn_worker_batch_report_seconds`, `tn_worker_batch_size_bytes`, `reth_storage_providers_database_{insert_header_numbers,insert_transaction_senders,save_blocks_sf}`, `reth_trie_{branches,leaves}_added`. A figure over validators from one of these names nine validators, not ten, and says so.
- What stands in for it: `benchmark/private/bench7-r20261115-1131/endpoint-snapshots/bench-validator-09-metrics-20261115T142307Z.txt.gz` (and validator-08's, for comparison): the node's own exporter text after the blast, cumulative since the process started (11:59:06Z), so whole-run totals of every histogram and counter exist for validator-09, without a time series.
- On every node (not new in bench 7): the agent's target label `network` replaces the node's own `network` label (`primary` / `worker-0`), so about 910 series pairs collapse into one, about 110 of them with different values (the `tn_network_*` per-network counters). A per-network figure cannot be read from Prometheus in this run; the endpoint snapshots hold both.
- One action on the live fleet besides the harness's own: `sudo systemctl restart telcoin-alloy.service` on bench-validator-09 at 12:37:50Z (the metrics agent only; the node was not touched). It changed nothing.
- Metric export: window 11:46:38Z to 14:27:13Z, step 15 s, 397 metrics, 22,504 series (`benchmark/private/bench7-r20261115-1131/prom-export/`, `INDEX.tsv`); check lines in `tasks/bench7/r20261115-1131/prom-export-check.txt` (38 must-haves: 27 ok, 4 lazy, 4 absent because nothing was counted, 3 incomplete = validator-09 only); exported with `--allow-missing`.
- Fleet health at the blast's end: 11 of 11 nodes, `fatal_db=0`, `halt=0`, every node at block 98,322, disk at most 26 % (`tasks/bench7/r20261115-1131/fleet-health-blast15-20261115T124039Z.log`).
- Teardown: `TEARDOWN_DONE run=r20261115-1131 deleted=12 left=0 at=2026-11-15T14:42:38Z`. Archive: `ARCHIVE_VERIFY ok=1 files=627 problems=0` to `gs://tn-devnet-benchmark-archive/runs/r20261115-1131/results/`.
- No preliminary read was written for this run.

## Found by the analysis (the orchestrator adds these as units hand back; cite the unit's file, not this list)

- The arms summary of this run (`benchmark/private/bench7-r20261115-1131/A1/arms/arms.json`, sha256 `f03035c8…75fb`) has TWO rows only: `bench7-always/L` (blast 0, 12:51:06–12:56:21Z) and `bench7-always/M16` (blast 2, 13:28:23–13:41:35Z, cut at the kill). Blast 1 has no row ("empty window after clipping": no second of blast 1 had all ten generators in their mixed phase). Its per-node blocks (`order_hold_by_node`, `vote_forms_by_node`, `order_hold_fleet`) sit under `summary_rows[i]`, not at the top level. A unit that needs blast 1 or the part of blast 2 after the kill extracts it itself and says so.
- Blast 1 (600 × 4) has no window with all ten generators in their mixed phase: generator 06's preamble wait ran its full 600 s after validator-06 lost 737 head-of-line preamble steps from 67 senders (in blast 0, generators 02 and 06 lost 88 steps each and needed about 45 s) (`A1/preamble.json`, `A1/kpis.md`). The KPI analysis gives blast 1 over the nine other generators' common window instead (`01-M4-nine`). The loss analysis owns the explanation.
- No `output executed` line of this build carries `persist_wait_ms`, `seed_ms` or `pipelined=`: there is no S12b stage (`A1/stages.md`).
- Certification (`A2/numbers.json`, `A2/certification.md`): blast 2's mixed phase certified 95.59 % of 52,702 own headers fleet-wide; validators 06 and 08 are the low ones; the rejoin of validator-05 (first `cvv_active` sample 14:16:23Z; the log's `CvvActive` line 14:16:03.711Z) falls AFTER blast 2's end (14:08:23Z), so the window "B2-postrejoin" is empty in this run. Lost own headers per validator and window: `A2/numbers.json` → `lost_own_headers.windows[<window>][NN|fleet]`.
- Decisions on units' questions: `tasks/bench7/analysis-decisions.md`.
