# Run facts: r20261117-1401 (from benchmark/results/r20261117-1401/manifest.json; cite, do not re-derive)

- Node image: `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, digest `sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, pinned=us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a; node commit `b1104905f1c2ca86166e51fa231bf55f3e40fde2`, version `0.1.0`; build features `faucet`.
- Storage engine named in the manifest: `tn-lmdb`.
- Generator image digest `sha256:7cefcc505201b2e40361a7d8cfe034778090b76c568cb2400369bf566c605a59`, commit `62bbd5f`.
- Machine `c3-highcpu-8`; node disk {"size_gb": 100, "type": "hyperdisk-balanced", "provisioned_iops": 20000, "provisioned_throughput": 800}; boot image `{'ref': 'projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105', 'name': 'ubuntu-2404-noble-amd64-v20261105', 'status': 'READY', 'deprecation_state': None}`.
- Harness at deploy: `7e75b189b140` (dirty=True; the dirt is under tasks/, benchmark/ was at its last commit).
- Deploy: start 2026-11-17T14:01:40Z, nodes healthy 2026-11-17T14:37:46Z, contracts done 2026-11-17T14:46:48Z, step 12 done 2026-11-17T14:46:55Z; coordinated start {"due": 1794925272, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 0, "max_late_secs": 0, "ts": "2026-11-17T14:29:04Z"}.
- Arm `bench8-control` (benchmark/arms/bench8-control.arm, sha256 `4ab67735ee8fe28580da804a725fac51b76053036f0c47749b7680a452d8cd7f`), applied 2026-11-17T14:21:12Z via prestart: `quorum_exec_block`=true, `quorum_exec_block_starved_rounds`=0, `quorum_exec_block_floor_outputs`=8, `vote_queue_fix`=true, `digest_order_hold`=true, `epoch_record_collect_past_uncertified`=true, `epoch_record_conflict_halt`=true, `epoch_record_recertify`=true.
- Funding: 2026-11-17T14:52:10Z to 2026-11-17T14:53:38Z.

## Blasts (real phases, `manifest.blasts[].phases`)

| blast | kind | senders × window | started | ended | rc | preamble | warmup | mixed | cooldown |
|---|---|---|---|---|---|---|---|---|---|
| 0 | light | 8 × 16 | 2026-11-17T14:53:56Z | 2026-11-17T15:06:21Z | 0 | 14:56:32–14:56:49 | 14:56:34–14:57:49 | 14:57:34–15:03:49 | 15:03:34–15:04:05 |
| 1 | light | 600 × 4 | 2026-11-17T15:06:21Z | 2026-11-17T15:18:44Z | 0 | 15:08:57–15:09:23 | 15:09:04–15:10:23 | 15:10:04–15:16:23 | 15:16:04–15:16:32 |
| 2 | load | 300 × 4 | 2026-11-17T15:18:44Z | 2026-11-17T16:24:12Z | 1 | 15:23:49–15:25:19 | 15:25:19–15:27:19 | 15:27:19–16:07:19 | 16:07:19–16:10:19 |

Times of day are UTC on the run's date; every figure's window comes from these, not from the planned phases.

## Chaos (`manifest.chaos`)

- 2026-11-17T15:51:36Z `bench-validator-05`: docker kill -s KILL telcoin (rc 1) {"planned": {"closing_epoch": 4, "boundary_unix": 1794930755, "restart_unix": 1794930996}, "late_secs": null}
- 2026-11-17T15:56:37Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:00:38Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:01:37Z `bench-observer-11`: systemctl restart telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:04:38Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:05:38Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:09:38Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:09:40Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:13:41Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:17:41Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:17:43Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:21:44Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:24:06Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}
- 2026-11-17T16:24:12Z `bench-validator-05`: systemctl start telcoin (rc 1) {"late_secs": null}

## End of the run

- Fleet ready check `step13` at 2026-11-17T14:48:11Z: ok=True, modes: 01=CvvActive, 02=CvvActive, 03=CvvActive, 04=CvvActive, 05=CvvActive, 06=CvvActive, 07=CvvActive, 08=CvvActive, 09=CvvActive, 10=CvvActive.
- Deploy result: {"rc": 0, "last_step": 15, "first_error": null, "started": "2026-11-17T18:39:55Z", "ended": "2026-11-17T18:44:28Z", "scope": "steps 15..15", "log": "logs/deploy-20261117T183955Z.log"}.
- Abort: null.
- Prometheus window in the manifest: {"start": "2026-11-17T14:37:46Z", "end": "2026-11-17T18:39:55Z", "end_reason": "no_chaos", "waited_secs": 0, "confirm_secs": null}.
- Log coverage: [{"inst": "bench-validator-01", "generations": 1, "first_ts": "2026-11-17T14:13:48Z", "last_ts": "2026-11-17T18:45:46Z", "due": "2026-11-17T14:21:12Z", "blast_end": "2026-11-17T16:24:07Z", "ok": true, "checked_at": "2026-11-17T19:01:48Z"}, {"inst": "bench-validator-02", "generations": 1, "first_ts": "2026-11-17T14:14:01Z", "last_ts": "2026-11-17T18:45:48Z", "due": "2026-11-17T14:21:12Z", "blast_end": "2026-11-17T16:24:07Z", "ok": true, "checked_at": "2026-11-17T19:01:48Z"}, {"inst": "bench-validator-03", "generations": 1, "first_ts": "2026-11-17T14:14:14Z", "last_ts": "2026-11-17T18:45:50Z", ".
- Archive: {"kind": "local", "path": "/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261117-1401", "verified_at": "2026-11-17T19:01:48Z", "files": 647, "bytes": 4192186497, "final_index_at": "2026-11-17T19:02:43Z", "reindexed_at": "2026-11-17T19:03:24Z"}.

## Lines of tasks/bench6/r20261117-1401/deploy12-20261117T140137Z.log

- `FSYNC_PROBE bench-validator-01 p50_us=1084 p95_us=1378`
- `FSYNC_PROBE bench-validator-02 p50_us=1093 p95_us=1547`
- `FSYNC_PROBE bench-validator-03 p50_us=915 p95_us=1090`
- `FSYNC_PROBE bench-validator-04 p50_us=1117 p95_us=1535`
- `FSYNC_PROBE bench-validator-05 p50_us=1210 p95_us=1800`
- `FSYNC_PROBE bench-validator-06 p50_us=1207 p95_us=1589`
- `FSYNC_PROBE bench-validator-07 p50_us=1187 p95_us=1564`
- `FSYNC_PROBE bench-validator-08 p50_us=845 p95_us=1198`
- `FSYNC_PROBE bench-validator-09 p50_us=949 p95_us=1184`
- `FSYNC_PROBE bench-validator-10 p50_us=1036 p95_us=1522`
- `FSYNC_PROBE bench-observer-11 p50_us=1054 p95_us=1393`
- `FSYNC_PROBE_SUMMARY median_us=1084 slow=[] probe_failed=[]`
- `HOST_PROBE_SUMMARY kernel=7.0.0-1017-gcp image=20261105 ra_kb=128 uniform=yes differ=[] probe_failed=[]`
- `BENCH_DEPLOY_RESULT rc=0 last_step=12 first_error=- log=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/results/r20261117-1401/logs/deploy-20261117T140137Z.log`

## By hand (the orchestrator)


## By hand (the orchestrator)

- Run 3 of bench 8 (run R: the control arm, `quorum_exec_block_floor_outputs` 8, at reduced load: the load blast with 300 senders per generator at window 4; about 5,300 tx/s wanted; the run is void outside 4,500 to 6,500 tx/s). Chain log `tasks/bench8/r20261117-1401/chain-20261117T140136Z.log`: deploy12 rc 0 and idle checks passed at 14:47:01Z; blast15 launched at once.
- **The gcloud login died during the run** (between 15:31:19Z, the endpoint sampler's last good round, and 15:35:58Z, the fleet watch's first failed listing; the login was made at 13:59Z). The generators kept running on the fleet: blast 2's mixed phase ran from 15:27:19Z to 16:07:19Z. Every driver step that needed ssh after 15:35Z failed.
- **No kill happened.** `manifest.chaos` lists the kill of validator-05 at 15:51:36Z and every later start and restart with rc 1: none of them reached a node (their ssh could not authenticate). Validator-05 ran through the whole blast; the observer was not restarted. The chaos entries of the manifest are attempts, not events.
- Blast 2 has rc 1 in the manifest because its collection failed; its phases are the driver's schedule (preamble 15:23:49, warmup 15:25:19, mixed 15:27:19 to 16:07:19, cooldown to 16:10:19). The harness's `analysis/certification.json` has no window for blast 2.
- Endpoint samples exist from 14:47:09Z to 15:31:19Z only (45 rounds; `tasks/bench8/r20261117-1401/endpoint-samples/`).
- Prometheus was exported through the still-open forward at 16:30:32Z, before the new login: `benchmark/private/bench8-r20261117-1401/prom-export`, 393 metrics, 22,420 series, 10,159,346 points, window 14:20 to 16:30Z. Check: 27 ok, 3 lazy, 5 absent, 6 incomplete (validators 05 and 03 lack some series in Prometheus: the metrics agent's lost batch).
- After a new login at 18:39Z: the collection (`step15`) rc 0 at 18:44:29Z (`BENCH_DEPLOY_RESULT rc=0 last_step=15`); teardown-dry rc 0 (22 instances: the ten generators were still up; 2 firewall rules, 1 bucket, 23 disks; the devnet's instances present); the teardown deleted every cloud resource and then stopped with rc 128 at its last local step (`git -C …/tn-contracts-devnet-relaunch worktree remove`: that path no longer exists on this machine; the contracts repository is at `…/tn-contracts`); a read-only pass showed no bench instance, disk, firewall rule, bucket or binding left; a re-run of the teardown with `BENCH_CONTRACTS_SRC_DIR` set to the repository's present path (launch file `bench8-reduced-teardown2.env`) removed the run's contracts worktree and its `bench/r20261117-1401` branch and ended `TEARDOWN_DONE run=r20261117-1401 deleted=0 left=0 at=2026-11-17T19:03:06Z`, rc 0. The fleet idled from 16:10Z to about 18:50Z.
- Reindex: 647 files, 4,192,186,497 bytes. Archive: `ARCHIVE_VERIFY ok=1 files=624 bytes=4191890137 problems=0` to `gs://tn-devnet-benchmark-archive/runs/r20261117-1401/results/` (19:11:59Z).
- The generators' own results for the load blast are in `benchmark/results/r20261117-1401/blasters/bench-blaster-NN.json`.
