# Plan: r20261006-0053 stall root cause, patch, log preservation, re-run (2026-10-06)

Inputs: benchmark/private/followups.md (r20261006-0053 section), node logs in
benchmark/results/r20261006-0053/logs/ (11 nodes: telcoin.log.gz, unit-stdout, pre-kill for v05,
recovery tgz = sampler.csv + sampler.epochs.txt + telcoin.journal). Logs exist; the "no node logs"
note in followups applies to the 23 Sep runs only. Debug filter was OFF (no level=debug lines).

## Wave 1 — investigate (parallel, read-only, opus)
- [x] L1 stall timeline for the failing validators 03/04/10 (tasks/stall/L1-failing.md)
- [x] L3 timeline for the certifying validators + v05 restart + pre-kill baseline (tasks/stall/L3-survivors.md)
- [x] L2 code trace at 964087e02: proposer re-propose, certifier vote collection, Canceled source,
      quorum math, epoch-close window (tasks/stall/L2-code.md)
- [x] H1 harness audit: log preservation to GCS before deletes; chaos lateness; IAP 4033 retry;
      chaos note; stall note in watcher (tasks/stall/H1-harness.md)
- [x] T1 txgen preamble diagnosis; FIX implemented: tn-transaction-generator fix/preamble-gap-repair 9f61303 (unpushed, not built; next txgen image) (batch-shaped tx loss + slow inclusion on au-se1; harness stopgap: --preamble-timeout-secs; real fix in txgen) (tasks/stall/T1-preamble.md)

## Wave 2 — decide + patch
- [x] Orchestrator synthesis: root cause statement with evidence (tasks/stall/ROOT-CAUSE.md)
- [x] telcoin-network: fix/certifier-keep-inflight-on-repropose off main (9b4bca750 + 963b59980), 3 new tests, 290/290 crate tests
- [x] merged into devnet-bench-10-5-2026 = ba43a1f0e (certifier/proposer tests 39/39 on the merge); both branches pushed
- [ ] devnet-genesis: harness fixes on a branch off main, commits as we go
      - [x] teardown: archive gate (14141d0) — live GCS path NOT yet exercised: teardown --yes on r20261006-0053 was blocked by the permission classifier; first live use = step 12/15 + teardown of the new run. OPERATOR: `benchmark/benchmark-teardown.sh --run r20261006-0053 --yes` archives the stall run's logs (fleet already gone).
      - [x] never delete logs; archive bucket excluded from teardown candidates by name and label
      - [x] chaos staged on the node clock, IAP 4033 retry, boundary verdict, stall note (3a31603); live chaos-stage-test pending (needs a fleet)
      - [x] tests green: 238 (suite), shellcheck 0.9 clean

## Wave 3 — rebuild + run
- [x] make docker-adiri TAG=mmap-subsecond-certfix-10-6-2026 from ba43a1f0e → digest 9d2d249e… but fork schedule = adiri-schedule (gate refuses sub-second delays). LESSON: bench images are `make docker-devnet` builds (no adiri feature; prev probe had 0 adiri strings).
- [x] make docker-devnet TAG=mmap-subsecond-certfix-10-6-2026 → digest sha256:caeb6be2f2732658841fa760b75e1adcec37d3a966a413fb48be8d1b9c32313e, sha ba43a1f0e, forks subsecond-from-genesis (probe ok)
- [x] probe ok; digest pinned via BENCH_DOCKER_IMAGE_EXPECT_DIGEST
- [x] RUN r20261006-0458 launched 04:59 UTC: steps 0-13 ok (11x POSTCFG_OK sha ba43a1f0e; archive bucket created at step 12; chaos-stage-test live on observer: late 0.016 s)
- [x] step 14 attempt 1 FAILED 05:51 UTC: GCE stockout e2-standard-2 in australia-southeast1-c for bench-blaster-03/04; exit cleanup deleted the 8 blasters, fleet kept, manifest abort=interrupted (index 0 archived by the harness on retry)
- [x] RESUME index 1 (05:53) FAILED the same way (e2 stockout, australia-southeast1-c)
- [x] RESUME index 2 (n2-standard-2 blasters) COMPLETE 07:05 UTC: 10 blasters, phases preamble 06:05:38 / mixed 06:09:08-06:49:08 / cooldown to 06:52:08; collect ok; collect-time archive FAILED (exclude regex leading ^ = gcloud ^DELIM^ list syntax) → fixed f89823d, verified with rsync --dry-run.
- [x] TEARDOWN DONE 07:25 UTC: 11 logs + 11 evidence pulled; archive gate verified 60 files before any delete (07:13:56); final sync 07:24:53; 319 objects under gs://tn-devnet-benchmark-archive/runs/r20261006-0458/; 'left nothing behind'; 0 bench instances; buckets = archive + cloudbuild only
- [x] A1 KPIs DONE: all-gen mean 3,889.6 tx/s (0053: 3,319.6; 29 Sep 4,177.2); best60 4,737; landed 11.50M; ttl p50/p95 3.38/17.98; commit p95 5.75-6.25 (UP; rounds 0.90/s vs 1.21/s); 1/10 generators hit the preamble limit (8/10 before); v05 catch-up 750 s (cvv_inactive 06:42:25-06:54:55), failed reports 0; NEW: 372 s inclusion gap 06:48:21-06:54:33 while only blasters 03/04 sent (asked A2 to explain). Backfill draft report/backfill/2026-10-06-certfix.json (8 placeholders). HB follow-up DONE (eef693a): stall note requires flat rounds; A2 node-log agent running (tasks/stall/A2-logs.md)
- [x] STALL DID NOT RECUR: kill 06:36:58.139 (59 s before the 06:37:57 boundary, late 0.139 s), restart 06:41:58.179 (late 0.179 s); blocks 28764 → 31876 between the 06:38:38 and 06:42:38 polls (~13 blocks/s on 9 validators); epoch 4 opened 06:37:59 during the outage; commit_stalls null, abort null. v05 cvv_inactive at 06:42:38 (catching up).
- [ ] analysis after collect: cert_rate.py (v03/v04 rates vs 0%), stall-scan, windows, recovery (catch-up secs), bundle with --blast-index 2 + backfill (blaster n2-standard-2); followups.md section

## Wave 4 — wrap
- [ ] tasks/todo.md review section, lessons.md, memory update

## Wave 2 status
- HA (archive gate + IAP retry) and HB (chaos timing/note, stall note, F1-F7) launched on bench/preserve-logs-and-harness-fixes.
- L3 verdict: 03/04/10 re-sent the SAME header; survivors recast votes every 250-500 ms; never certified. XA/XB drew ~1,000 recasts each in baseline (chronically slow to certify). Hypothesis: the far validators cannot certify within max_header_delay; the 7 fast ones formed every quorum until one was killed.
