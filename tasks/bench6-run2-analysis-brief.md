# Bench 6 — run 2 and run 2b analysis brief (the headline runs)

Written by the orchestrator, its only writer, on 2026-11-13.
Read `tasks/bench6-agent-rules.md` first (sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Investigations and analysis units", "HAND BACK"), then this file, then your own unit.
Both fleets are deleted: every input is local and nothing is fetched.

## 0. The two runs and their paths

| | run 2 (the headline) | run 2b |
|---|---|---|
| run id | `r20261113-1351` | `r20261113-1630` |
| node disk | 100 GB Hyperdisk Balanced, 20,000 IOPS, 800 MiB/s (bench 5's) | the same disk provisioned at 50,000 IOPS |
| everything else | identical: image `adiri@sha256:874537ff…` (2df831e3c), generator 62bbd5f, bench 5's ten zones, `c3-highcpu-8`, epoch 1,200 s, `benchmark/arms/final.arm` applied before the first start | |

For each run `<R>`:
- Results: `benchmark/results/<R>/` (read-only): `manifest.json` (`param_arms[0]` = `final` via prestart, `blasts[]` with real phases, `blast_runs[]`, `log_rate[]`, `commit_stalls[]`, `fund`, the chaos record), `blast-0-*/` and `blast-1-*/` (the two light blasts), top-level `blasters/` and `funder/` (blast 2, the load blast), `logs/`, `persist/<node>.csv` and `.folios.txt`, `metrics.json`, `analysis/`.
- Node log layout: as in run 1 (`tasks/bench6-run1-analysis-brief.md` §0, the trap paragraph): `…-unit-stdout.log.gz` is the whole node log; other `telcoin-*` files are tails or snapshots. Validator-05 and the observer have a pre-kill and a pre-restart snapshot.
- Prefiltered logs: `benchmark/work/prefilter/<R>/logs/`.
- Node metrics exported before the teardown: `benchmark/private/bench6-<R>/prom-export/` (`INDEX.tsv`; step 15 s; counters reset at a node's restart: validator-05 and the observer restart inside blast 2).
- Your output directory: `benchmark/private/bench6-r20261113-1351/<unit>/` (one directory per unit for both runs; name every table's run). Your checkpoint: `tasks/checkpoint-bench6-r2-<unit>.md`.
- Scratch: `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/r2-<unit>/` (nothing over 200 MB); bigger extracts under `benchmark/work/bench6-scratch/r2-<unit>/`.
- Run 1's units left working readers: `benchmark/private/bench6-r20261112-1520/<unit>/scripts/` (or `bin/`, or the `.py` files beside the outputs) and their hand-backs in `tasks/checkpoint-bench6-r1-<unit>.md`. Start from them; point them at the new run; say what you had to change.
- Run 1's results, for comparison only: `benchmark/private/bench6-r20261112-1520/` (`A7/verdicts.md`, `cross-unit-notes.md`, `A8/writes-model.md`, `I-7`, `I-8`, `I-9` `findings.md`).
- Bench 5 (r20261107-1504), the run the headline is compared with: `tasks/bench5-report-r20261107-1504.md`, `benchmark/private/bench5-r20261107-1504/{A1,A2,A3,A4n,A6}/`, `benchmark/report/backfill/2026-11-07-main-fixes.json`.

## 1. Run facts (cite, do not re-derive)

Run 2, `r20261113-1351`:
- A first deployment (`r20261113-1327`) failed at key generation and was torn down before any node started; it is not part of the run.
- Deploy 13:51:36Z to 14:33:39Z; `final` applied at step 7 (`param_arms[0]`, sha256 e90b61c8…): `quorum_exec_block` (starved rounds 0, the always-on form), `vote_queue_fix`, `epoch_record_state_check`, `mdbx_random_advice` on; every other switch at its default; no host step. Ten validators CvvActive.
- Fsync probe median 1,060 µs; validators 04 and 05 flagged slow (1,285 and 1,284 µs p50).
- Blasts: 0 light 8 × 16 (mixed 14:44:38-14:51:02Z); 1 light 600 × 4 (14:57:06-15:03:54Z); 2 load 600 × 16 with the chaos plan (mixed 15:16:22-15:56:49Z, 2,400 s planned).
- Chaos in blast 2: validator-05 killed 15:40:59Z, started 15:45:59Z; the outage crossed an epoch boundary (epoch 5 opened 15:41:58Z); observer restarted 15:50:59Z. Every validator was CvvActive again before the collect.
- All ten generators `BENCH_BLAST_DONE rc=0`; blast segment rc 0 at 16:09:48Z; teardown left nothing; archive verified.
- The teardown's certification check: no validator below 90 % of its own headers.
- Orchestrator's preliminary read (Prometheus, verify): blast 2 executed 4,597 / 5,308 / 5,327 tx/s (min / median / max over validators; the minimum is the killed one), 3,872 transactions per output, persist 0.370 s per output, refused-behind votes 0, vote timeouts 0; blast 1 6,224 tx/s; blast 0 700 tx/s.
- During the first light blast every node's prefault writes ran at 1.16-1.19 times its newly allocated pages (run 1's skipped-prefault state read 0.25-0.33; investigation I-9).

Run 2b, `r20261113-1630` (the same sequence and checks; node disks confirmed at 50,000 provisioned IOPS, 800 MiB/s):
- Deploy 16:30:48Z to 17:14:11Z; `final` applied at step 7 (the same sha256), ready 16:50:28Z. Fsync probe median 1,006 µs; validator-06 flagged slow (1,226 µs).
- Blasts: 0 light 8 × 16; 1 light 600 × 4; 2 load 600 × 16 with the chaos plan (take every phase time from `manifest.blasts[].phases`).
- Chaos in blast 2: epoch 4 opened 18:02:19Z; validator-05 killed 18:21:20Z, started 18:26:20Z; the outage crossed the boundary (epoch 5 opened 18:22:20Z); observer restarted 18:31:20Z.
- All ten generators done 18:40:43Z; blast segment rc 0 at 18:51:32Z.
- Orchestrator's preliminary read (Prometheus, verify): blast 2 executed 6,090 / 7,361 / 7,371 tx/s (min / median / max; the minimum is the killed validator), 5,856 transactions per output, persist 0.260 s per output (commit 0.130, save 0.130), refused-behind votes 266 over the fleet (106 on one validator), vote timeouts 0; blast 1 6,388 tx/s; blast 0 703 tx/s.
  Run 1's model extrapolated an execution-bound 8,600-10,300 tx/s at this IOPS limit; the measured rate is below it.

Known from the epoch-record investigation of run 1 and run 2 (`benchmark/private/bench6-r20261113-1351/E-1/findings.md`, `E-2/findings.md`; its scripts take a run's extracts and run unchanged on run 2b):
- Every epoch close of run 2 certified its record with at least 7 of 10 validators on one hash and one closing block; the loaded closes had 7 to 9 signers, the close inside the outage 9.
- After its five-minute outage validator-05 fetched the certified record, replayed the close onto the fleet's block, and stayed a follower (CvvInactive, 383 `rejoin not ready` lines) until 16:02:39.6Z, about 16 minutes, so it also missed signing the next record.
- The error line `failed to reach quorum on epoch close` is a false alarm in these runs (9 times at 6 closes of run 1 and run 2; the record was certified by the network each time).

## 2. What the analysis must answer

1. The headline against bench 5 (3,449 tx/s; its seen p50 at 600 × 16; its floor latency) and against the design's acceptance lines (`benchmark/private/bench6-prep/design/design-harness--arms-and-runs.md` §5 "Acceptance"), each line measured, with the three the orchestrator told the user to expect as failures on this disk named as such if they fail (commit time per transaction at or under 45 µs; execution lag at or under 8 outputs at saturation; 98 % certification in a blast's first two minutes). The start criterion is `late_secs` at most 10 (loosened from 5 with the user's knowledge).
2. What bound each run at full load: run 1 found the disk's 20,000 write IOPS (rate = 20,000 over the writes per transaction). Does run 2 sit at that limit through its 40 minutes, and does its rate decay with the database as run 1's model said (`A8/writes-model.md` §3a: a 40-minute mean of about 5,150-5,650 tx/s, falling by about a third)? In run 2b, at 50,000 IOPS, what binds: the model said execution, at 8,600-10,300 tx/s.
3. The write pattern on a fresh deployment with the advice on from the first process: amplification per node (device bytes over page bytes, with write count, write size and sync count beside it), large folios, prefault against growth per process. Bench 5 amplified on every node; run 1's observer did in its first process.
4. The vote fix under a kill: own-header certification per validator per window, refused votes, vote-lock wait, through the kill, the boundary inside the outage and the rejoin.
5. Recovery: validator-05 from kill to CvvActive, rejoin episodes, what it replayed; the epoch closes under load (commit gap, signers; validator-02 lagged at every loaded close of run 1); the observer's restart.
6. What the chosen configuration leaves unfixed, measured: gap resends and landings at or past 300 s, transactions unlanded after the tail (the pool switches are off), the far validators' share of committed certificates (the grace is off).
7. Run 2 against run 2b, line by line: everything above, plus where the time per transaction goes in each.

## 3. Reading rules

The user's rules of run 1 hold (`tasks/bench6-run1-analysis-brief.md` §3): write count, sync count, write size and commit time beside any byte ratio; a figure names its window and its denominator; one node is not the fleet; a fit is not a mechanism; say plainly what could not be measured.
Every per-run figure of blast 2 says whether its window includes the outage of validator-05 (15:40:59-15:45:59Z in run 2) and whether validator-05 is in the median.

## 4. Units

Wave 1, in parallel, each on both runs:

- **r2-A1** generator KPIs: per blast landed tx/s, seen and land p50 / p95 / p99, floor KPIs, Little's law at 600 × 4, errors by code, resends by cause, landings at or past 300 s, unlanded after the tail, per-generator landing over time through the kill (validator-05's generator), `late_secs`, the fund's `still_short`. The comparison table against bench 5's KPIs. Outputs `kpis.json`, `kpis.md`, `vs-bench5.md`.
- **r2-A2** certification and votes: per window and validator, own-header certification, refused votes, `lock_ms`, exec lag, round time, the far validators' committed share; the two-minute warm-up figure; the windows around the kill and the rejoin. Outputs `numbers.json`, `certification.md`.
- **r2-A3a** recovery and closes: validator-05's kill, start, modes, rejoin and replay in each run, and why it stayed a follower for about 16 minutes after a 5-minute outage in run 2 (the `rejoin not ready` reasons over time, against the node code's rejoin rule and bench 5's rejoin finding in `tasks/bench5-report-r20261107-1504.md`); the observer's restart; each epoch close of run 2b read with the epoch-record investigation's scripts (`benchmark/private/bench6-r20261113-1351/E-1/scripts/`, which ran on run 2 already: reuse its run-2 table, add run 2b's), with commit gap and signers. Outputs `recovery.md`, `closes.md`.
- **r2-A3b** log census: the halt, fatal-database, fork and panic check over every full log of both runs; the warn and error templates that are new against run 1's census (`benchmark/private/bench6-r20261112-1520/A3/census.json`) or more than ten times its rate per minute, with counts per node and per blast. One extraction pass per node, four nodes at a time. Outputs `census.md`, `census.json`.
- **r2-A4e** the engine: per blast and, for blast 2, per five-minute bucket and per validator: the engine's split per transaction (recover, evm, root, finish, save, commit, wait), busy, queue, transactions per output; what binds each run at full load, and in run 2b what stands between the measured rate and the execute cost per transaction. Outputs `engine.md`, `engine.json`.
- **r2-A4p** the disk: per blast and per minute of blast 2: device writes per second against the provisioned limit (20,000 and 50,000), writes per transaction, write size, sync count, amplification (device bytes over page bytes), prefault against growth per process, folios, database size; the check of run 1's model (`benchmark/private/bench6-r20261112-1520/A8/writes-model.md`, `model.json`) against both runs' measured decay. Outputs `disk.md`, `model-check.md`, `disk.json`.
- **r2-A6** land-path stages: `benchmark/tools/stage-latency.py` (it now reads the node's fields without a shim) per blast window, the floor's stages against bench 5's and run 1's. Outputs `stages.md`, `stages-<run>-<index>.json`.

Wave 2:
- **r2-A7** acceptance verdicts and the comparison tables (run 2 against bench 5; run 2b against run 2), from the wave-1 outputs only. Outputs `acceptance.md`, `comparison.md`.
- **P** backfill for the bundle (`benchmark/report/backfill/` in the schema of `2026-11-07-main-fixes.json`), then the orchestrator's `bundle` segment.
- **A5** the report `tasks/bench6-report-r20261113-1351.md` in the bench-5 report's structure, from the unit outputs only, with the scrub rules of the earlier reports.

## 5. Hand back

Status and checkpoint path; the output files; the five numbers that matter most with their cites, for each run; what you could not measure; what you would ask the orchestrator to decide.
A summary, never file contents.
