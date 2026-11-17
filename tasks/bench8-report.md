# Bench 8 report: r20261116-2011 (floor 16), r20261116-2332 (control) and r20261117-1401 (reduced load)

Private record for the repository owner; assembled 2026-11-17 from one file per section (`tasks/bench8/report/s<N>.md`, each with a sources note beside it). One run per configuration: no figure here carries a significance claim. Nothing of bench 8 is published.

## 1. Summary

Bench 8 asked why header certification before the kill fell to about 94 % in bench 7's always-on run 7a (`r20261115-1131`).
It ran three fleet runs on one node build (`bench/bench8-2026-11` at b1104905f) with ten validators, each configuration once, so no difference below carries a significance claim.

| run | floor, load blast | window | executed tx/s | certified % | under-held % |
|---|---|---|---:|---:|---:|
| 1 (F) `r20261116-2011` | 16, 600 × 16 | before the kill, 1,877 s | not computed | 97.618 | 3.43 |
| 2 (C) `r20261116-2332` | 8, 600 × 16 | before the kill, 1,679 s | 9,473.1 | 96.899 | 7.82 |
| 3 (R) `r20261117-1401` | 8, 300 × 4 | whole mixed phase, 2,400 s (no kill) | 5,181.6 | 99.955 | 0.02 |
| 3 (R) | | its first 1,679 s | 5,354.7 | 99.948 | 0.02 |
| 7a (bench 7) | 8, 600 × 16 | before the kill, 817 s | 9,289 (bench 7's count) | 93.997 | 12.08 |

Executed is validator-01's count over the window (§3.6); 7a's rate is bench 7's chain count over its whole mixed phase, a different window.
Run 3's window starts 85 s after its load began; over the generators' own phase it executed 5,356.8 tx/s.
Run 1's first 817 s read 99.895 %, as clean as run 3: the contrast between full and reduced load is in the longer windows.

The answer:
- [measured] Headers are lost on the validators at the front of execution while four or more other voters are further behind than the floor: in run 2, 1,251 of 1,258 lost headers came from authors at most 2 outputs behind, and the certified share fell from 99.40 % with three such voters to 82.26 % with four; the step is partly definitional, but the outcome is not (headers not under-held were lost at about 0.1 %, under-held ones at 40 % with four or more behind, the laggards' own headers almost never) (§4.1).
- [measured] Run 1's other path is the same root: on 193 of validator-02's 230 headers cut off while enough voters held the block, the quorum was the bare seven, the three lagging voters answered `superseded`, and the round ended at the author's next header; on 37 more a seventh voter also voted and the round was still lost (§4.2).
- [measured, the cause inferred as a timing fit] The voters fall behind because the executors are saturated: at 0.959 to 0.984 busy in run 2 the tips drifted up to 53 outputs apart, while at 0.555 to 0.589 in run 3 none fell more than 2 behind and the loss went away; all ten validators executed the same transactions, and run 3's uneven ingress on validators 02 and 06 only concentrated its 31 residual losses (§4.4).
- [measured] A floor of 16 kept the first load epoch clean (99.919 %) and not the second (95.988 %), so depth moves the threshold and does not remove the drift (§4.3).
- [measured] In run 2 two validators late to a loaded epoch close drew internal-error vote answers, were demoted, and sat out about nine minutes each, one spare voter fewer for the fleet; this did not happen in runs 1 and 3 (§4.5).

New in bench 8: the bare-quorum path and the round's end at the author's next header; the reduced-load contrast; the internal error and the demotion at a loaded close; and the far validators' step, now measured (in 96 to 98 % of pairs a far certificate reaches a near validator after its next header, which never names it; 17 to 30 % committed) and read in code (§4.6).

Not known (§7): why some executors run slower at saturation, and which; whether a named block with a margin above the bare quorum, or back-pressure, removes the loss at full load; why run 2's validator-10's persist time rose; why the far validators' ingress was so low at reduced load; and what a second run of any configuration would read.

For the owner (§5.6): whether bench 8 ends here, as the plan's rule says after run 3 ("stop"); whether and when the local issue draft on the epoch close is posted, given the freeze; whether a comment for #1870 is drafted; which suggestion of §5, if any, to pursue, and whether before or after the launch; whether anything of bench 8 is published.
The stack bench 8's build came from is merged into main (#1862; main at 5533ff73a) without its switches, and nothing from bench 8 is posted or published.

## 2. Run facts and provenance

Every line here is measured from the manifests, the run facts or the first looks unless it is marked.
`s2.sources.md` names the file and line or key of each.

### 2.1 The build and the machines

All three runs ran one node image: digest `sha256:e81f54d6d605efb75a72b405ac19b9e61a922e72ba91dbb20f87d5e97a3e9a1a`, node commit b1104905f on `bench/bench8-2026-11`, version 0.1.0, build feature `faucet`, storage engine `tn-lmdb`.
The build is bench 7's image commit plus one bench-only parameter and new log fields.
The parameter is `quorum_exec_block_floor_outputs` (default 8): the proposer names the quorum value floored at the ring entry that many block-bearing outputs back from its own tip; no voter code reads it [read from code, as `tasks/bench8/node-fields.md` records it].
At 8 the named block equals the earlier build's on all 20 golden rows; at 16, 8 of the 20 rows differ.
The new log fields are on `header proposed`, `vote path timing`, the lines that end a vote round at the author, two new lines (`leader schedule updated`, `certificate accepted`) and the engine's per-output lines; `node-fields.md` lists them verbatim.
The generator image was the same in all three runs (digest `sha256:7cefcc50…`, commit 62bbd5f).

The fleet was ten validators and one observer on `c3-highcpu-8`, each with a 100 GB hyperdisk-balanced disk at 20,000 provisioned IOPS and 800 MB/s, Ubuntu 24.04 of 2026-11-05, kernel 7.0.0-1017-gcp, read-ahead 128 KB.
The host probe found the nodes uniform in every run.
The fsync probe's median at deploy was 1,081 µs (run 1), 1,065 µs (run 2) and 1,084 µs (run 3), with no slow node in any run.
The harness at deploy was 14e20773c566, 037b8c85c856 and 7e75b189b140; each was dirty only under `tasks/`, with `benchmark/` at its last commit.

Run 1 used the arm `bench8-floor16`, runs 2 and 3 the arm `bench8-control`.
Both arms set the same eight switches (`quorum_exec_block` on, `quorum_exec_block_starved_rounds` 0, `vote_queue_fix`, `digest_order_hold` and the three `epoch_record_*` switches) and differ only in the floor, 16 against 8.
In runs 1 and 2 the idle check read the floor back on every node; run 3's run facts say the idle checks passed and do not name the floor.

### 2.2 Timelines

Times are UTC; run 1 is on 2026-11-16, run 2 crosses midnight into 2026-11-17, run 3 is on 2026-11-17.

| event | run 1 (F) | run 2 (C) | run 3 (R) |
|---|---|---|---|
| deploy start | 20:12:01 | 23:32:50 | 14:01:40 |
| arm applied (prestart) | 20:35:49 | 23:52:16 | 14:21:12 |
| coordinated start, 11 of 11 nodes, spread 0 s | 20:43:09 | 23:59:56 | 14:29:04 |
| nodes healthy | 20:50:47 | 00:07:43 | 14:37:46 |
| contracts done; step 12 done | 21:16:45; 21:16:50 | 00:16:11; 00:16:16 | 14:46:48; 14:46:55 |
| funding | 21:21:23 to 21:22:42 | 00:21:03 to 00:22:24 | 14:52:10 to 14:53:38 |
| blast 0, light, 8 × 16, mixed phase | 21:26:35 to 21:32:36 | 00:26:20 to 00:32:59 | 14:57:34 to 15:03:49 |
| blast 1, light, 600 × 4, mixed phase | 21:39:00 to 21:45:13 | 00:38:49 to 00:45:08 | 15:10:04 to 15:16:23 |
| blast 2, load: senders × window | 600 × 16 | 600 × 16 | 300 × 4 |
| blast 2 whole, rc | 21:47:42 to 22:40:38, rc 0 | 00:47:31 to 01:40:18, rc 0 | 15:18:44 to 16:24:12, rc 1 (its collection failed) |
| blast 2 mixed phase, manifest | 21:54:55 to 22:35:11 | 00:54:44 to 01:34:53 | 15:27:19 to 16:07:19 (the driver's schedule) |
| blast 2 mixed phase, generators' own | the same as the manifest | the same as the manifest | 15:25:54 to 16:05:54 (generators 02 and 06: 15:26:15 to 16:06:15) |
| kill of validator-05 | 22:26:12 | 01:22:43 | none: attempted at 15:51:36, rc 1, never reached the node |
| validator-05 started | 22:31:12 | 01:27:43 | none: 12 attempts from 15:56:37 to 16:24:12, all rc 1 |
| observer restarted | 22:36:12 | 01:32:43 | none: attempted at 16:01:37, rc 1 |
| fleet-ready check after the blasts | 22:49:29, ten `CvvActive` | 02:06:00, ten `CvvActive` | none; the only check is 14:48:11, before the blasts |
| deploy steps 13 to 15 end | 22:53:43 | 02:07:11 | 18:44:28 (step 15 alone, after a new login) |
| Prometheus export | 22:58:38 | 02:15:02 | 16:30:32 (before the new login) |
| teardown done | 23:10:27 | 02:28:38 | 19:03:06 (a second pass; the first stopped with rc 128, §6) |
| archive verified | 23:17:24 | 02:35:53 | 19:11:59 |

In run 3 the cloud login died between 15:31:19 and 15:35:58, and every driver step that needed a remote shell after that failed (§6).
The manifest's chaos entries for run 3 are attempts, not events: validator-05 ran through the whole load blast and the observer was not restarted.

### 2.3 What differs between the runs apart from the planned change

There is one run per configuration; nothing in this list is controlled.

Blast 1's mixed phase lasted 6 min 13 s in run 1 and 6 min 19 s in runs 2 and 3, against 15 min 54 s in 7a (the run facts and AF1 round these to 6 and 16 min).
Run 1's load blast began about 18 min earlier in the chain's life than 7a's: 86 against 104 min after validator-01's first header, about 10 of those minutes from the shorter blast 1.
Run 2's load mixed phase began 54 min 48 s after the coordinated start, against 71 min 46 s in run 1; the deploy's steps between the start and the blast were faster.
Run 3's began 56 min 50 s after the coordinated start by the generators' own phase, 58 min 15 s by the driver's [arithmetic on the run facts' times].

The load blast sits differently in the epochs (from validator-01's `header proposed` epoch field; an epoch is 20 min):

| run | the mixed phase starts | later boundaries | the 817-s window lies in |
|---|---|---|---|
| 1 | 7 min 43 s into epoch 4 (21:47:12 to 22:07:21) | epoch 5 from 22:07:21, epoch 6 from 22:27:31 | epoch 4, plus 71 s of epoch 5 |
| 2 | 11 min 1 s into epoch 3 (from 00:43:43.4) | epoch 4 from 01:03:51.9, epoch 5 from 01:23:51.5 | the last 548 s of epoch 3 and the first 269 s of epoch 4 |
| 3 | 14 min 42 s into epoch 3, by the driver's window | epoch 4 from 15:32:36, epoch 5 from 15:52:36 | the last 318 s of epoch 3 and the first 499 s of epoch 4 |
| 7a | 5 min 23 s into epoch 5 (13:22:35 to 13:42:41) | epoch 6 from 13:42:41 | epoch 5, ending 66 s before epoch 6 |

The 269 s and 499 s are arithmetic on the window and the boundary.

The kill came 1,877 s into the mixed phase in run 1 (in epoch 5, 79 s before epoch 6 by the bucket labels), 1,679 s in run 2 (in epoch 4, 68 s before epoch 5), never in run 3, and 817 s in 7a.
The manifest plans the kill against an epoch close (its `planned.closing_epoch` was 5 in run 1 and 4 in runs 2 and 3), so the kill moves with the epoch layout [inferred from the manifest's fields].
Run 1's window before the kill is therefore 2.3 times 7a's and holds the epoch 4 to 5 boundary; run 2's holds the epoch 3 to 4 boundary.
Run 3 has no kill, so its windows are cut at the same lengths (817 s and 1,679 s) and over the whole mixed phase.

Run 3's windows are offset from its load.
The manifest's phases for blast 2 are the driver's schedule, 85 s after the generators' own, and were never corrected because the collection failed.
So run 3's W-mixed misses the load's first 85 s and holds 85 s with almost no load: only generators 02 and 06, which started 21 s late, sent until 16:06:15; 10,334 of their transactions landed and validator-01 executed 28,893 in those 85 s, 0.23 % of the window's.
That moves the rate (5,181.6 tx/s over W-mixed against 5,356.8 over the generators' phase) and not the certification (Wgen: 99.955 % certified, 0.02 % under-held).

Run 3's ingress was uneven.
Validators 02 and 06 received and batched about 100 tx/s each (827 batches and 114.3 tx/s; 768 batches and 103.0 tx/s) against 564 to 682 tx/s (4,896 to 5,776 batches) for the other eight.
Generators 02 and 06 landed 107.5 and 95.4 tx/s of their own, against 573 to 682 tx/s for the other eight, at an inclusion latency p50 of 10 to 17 s.
Run 2 was uneven too, but less: 488 to 1,260 tx/s per generator, latency p50 907 to 3,036 ms.
The cause is not measured; a closed loop of 1,200 transactions in flight at about 11 s per round trip comes to about 100 tx/s [inferred, AF3].
Every validator executed the same outputs and transactions in run 3 (5,072 and 17,788,630 in the figure-check's count), so the unevenness is on the ingress and batch side, not in execution.

Two other differences in the fleet:
- in run 2, validator-10 proposed 2,830 headers in W-prekill against about 4,190 for each other validator (§3.4; the reason is §4.5's);
- in run 3, validator-05 was present for the whole load blast and the observer was never restarted.

The manifest records two different waits after the blasts, and they are not the same thing.
`fleet_ready` (label `step15`) is the fleet-ready check: it passed after 260 s in run 1 (22:49:29) and after 1,272 s in run 2 (02:06:00), with ten `CvvActive` in both.
`prom_window` is the wait that sets the end of the Prometheus window: 535 s in run 1, ending with reason `fleet_ready` after a 180-s confirmation; 1,366 s in run 2, ending with reason `max_wait`, so run 2's window was closed by its time limit and not by a confirmed ready fleet.
Run 3 has neither after its blasts: its only `fleet_ready` entry is the check before them (label `step13`, 14:48:11), and its `prom_window` ends with reason `no_chaos`.

### 2.4 What Prometheus lacks, per run, and what stands in

In all three runs the gaps come from the metrics agent's lost remote-write batches (tn-node-deployment #66).
None of the three first looks used Prometheus as an input.

Run 1, export check over 20:48 to 22:55: 41 must-haves, 33 ok, 4 lazy, 4 absent, none incomplete.
Five series stopped after the kill: on validator-03 from 22:27:45 `tn_engine_persist_duration_seconds_count` and the three `tn_primary_vote_exec_deficit_outputs` series, on the observer from 22:36:15 `tn_executor_output_transactions_count`.
There were nine gaps on validator-05 and the observer after their restarts and 29 expected gaps; everything before the kill is whole on every node.
At the end `up` lacked validator-03 and the observer although both were healthy.
Stand-in: the endpoint sampler read every node's own exporter every 60 s from 21:16:51 to 22:53:57, 97 rounds, 11 of 11 nodes in each round as far as its log shows.
Export: 400 metrics, 23,245 series, 11,999,524 points, 20 MB, window 20:38 to 22:57.

Run 2, export check over 00:05 to 02:10: 30 ok, 4 lazy, 4 absent, 3 incomplete.
For the whole run Prometheus has no `tn_primary_vote_stage_seconds_count` for validator-10, no `tn_engine_persist_duration_seconds_count` for validators 03 and 10 and no `tn_reth_persist_commit_seconds_count` for validator-03.
At the idle check `up` for the observer and validator-10 came through the endpoint fallback.
Stand-in: endpoint samples from 00:16:32 to the chain's end, 2,520 files.
Export: 400 metrics, 22,974 series, 11,013,831 points, 20 MB, window 23:55 to 02:14.

Run 3, export check (taken at 16:30:32 through the still-open forward): 27 ok, 3 lazy, 5 absent, 6 incomplete; validators 05 and 03 lack some series.
Endpoint samples exist only from 14:47:09 to 15:31:19 (45 rounds), when the login died, so nothing stands in for the missing series after 15:31:19.
Export: 393 metrics, 22,420 series, 10,159,346 points, 17 MB, window 14:20 to 16:30.

### 2.5 What is archived and what is private

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| archive verify (`gs://tn-devnet-benchmark-archive/runs/<run>/results/`) | 626 files, 3,074,284,753 bytes, 0 problems | 626 files, 2,992,471,535 bytes, 0 problems | 624 files, 4,191,890,137 bytes, 0 problems |
| local reindex (`benchmark/results/<run>`) | 649 files, 3,074,580,815 bytes | 649 files, 2,992,767,362 bytes | 647 files, 4,192,186,497 bytes |
| teardown | 12 instances deleted, 0 left | 12 deleted, 0 left | every cloud resource deleted (22 instances: the ten generators were still up), then rc 128 at the last local step; a second pass deleted 0, left 0 |

The local reindex counts 23 files more than the archive verify in each run; the run facts do not say which.
Run 1's manifest has `archive` and `log coverage` empty (null) while its run facts record the archive verify; runs 2 and 3 have both fields filled.
Private and not in the archive: the Prometheus exports (`benchmark/private/bench8-<run>/prom-export`), the endpoint samples (`tasks/bench8/<run>/endpoint-samples/`), the analyses (`benchmark/private/bench8-<run>/`) and their scratch (`benchmark/work/bench8-scratch/`).
Run 1's run facts say to keep the export and the samples; runs 2 and 3 keep theirs in the same places.
Run 3's generators' own results are in the archived results directory, under `blasters/`.

## 3. The numbers

Every figure here is measured unless a line says otherwise.
Each comes from the JSON beside a figure-checked first look (AF1 for run 1, AF2 for run 2, AF3 for run 3) or from the run facts; `s3.sources.md` names the file and key.
There is one run per configuration, so no difference below carries a significance claim.
This section says what a row is and nothing more; the reading is in §4.

### 3.0 The windows

Times are UTC.
All windows of runs 1 and 2 start at the load blast's mixed phase as the manifest gives it, which matched the generators' own phases in those runs.
Run 3's manifest phases are the driver's schedule, 85 s later than the generators' own mixed phase (15:25:54 to 16:05:54); its windows W-817, W-1679 and W-mixed start at the driver's 15:27:19, and Wgen is the generators' own phase.
The counting unit for certification is a validator's own `header proposed` line.

| run | window | from | to | length |
|---|---|---|---|---:|
| 1 (F, floor 16) | W-817 | 21:54:55 | 22:08:32 | 817 s |
| 1 | W-prekill | 21:54:55 | 22:26:12 (the kill) | 1,877 s |
| 1 | W-e5 (supplementary: run 1's epoch 5 at 7a's offset into its epoch) | 22:12:44 | 22:26:12 | 808 s |
| 1 | B2 (the whole mixed phase) | 21:54:55 | 22:35:11 | 2,416 s |
| 2 (C, floor 8) | W-817 | 00:54:44 | 01:08:21 | 817 s |
| 2 | W-prekill | 00:54:44 | 01:22:43 (the kill) | 1,679 s |
| 2 | B2 | 00:54:44 | 01:34:53 | 2,409 s |
| 3 (R, floor 8, reduced load) | W-817 | 15:27:19 | 15:40:56 | 817 s |
| 3 | W-1679 (run 2's W-prekill length; no kill happened) | 15:27:19 | 15:55:18 | 1,679 s |
| 3 | W-mixed (the driver's mixed phase) | 15:27:19 | 16:07:19 | 2,400 s |
| 3 | Wgen (the generators' own mixed phase) | 15:25:54 | 16:05:54 | 2,400 s |
| 7a (bench 7, floor 8) | W-817 (7a's B2-prekill) | 13:27:58 | 13:41:35 (the kill) | 817 s |

### 3.1 The plan's two numbers per window

The plan's two numbers are the fleet's certified share of headers and the share of headers that were under-held.
Under-held: the block the header named was held by at most 5 of the other voters when the header was proposed.
Lost: a proposed header that never reached a quorum.
"k ≥ 4" is the share of rounds in which four or more headers were under-held.

| | r1 W-817 | r1 W-prekill | r2 W-817 | r2 W-prekill | r3 W-817 | r3 W-1679 | r3 W-mixed | 7a W-817 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| headers | 22,965 | 50,715 | 20,273 | 40,567 | 23,426 | 48,146 | 68,865 | 20,758 |
| certified % | 99.895 | 97.618 | 98.51 | 96.899 | 99.949 | 99.948 | 99.955 | 93.997 |
| lost | 24 | 1,208 | 302 | 1,258 | 12 | 25 | 31 | 1,246 |
| under-held headers | 6 | 1,741 | 1,199 | 3,174 | 6 | 12 | 12 | 2,508 |
| under-held % | 0.03 | 3.43 | 5.91 | 7.82 | 0.03 | 0.02 | 0.02 | 12.08 |
| certified % of the under-held | 100.0 | 59.1 | 76.48 | 61.56 | 100.0 | 100.0 | 100.0 | 54.39 |
| certified % of the others | 99.9 | 98.99 | 99.9 | 99.9 | 99.95 | 99.95 | 99.95 | 99.44 |
| lost that were under-held / not | 0 / 24 | 712 / 496 | 282 / 20 | 1,220 / 38 | 0 / 12 | 0 / 25 | 0 / 31 | 1,144 / 102 |
| rounds with k ≥ 4 | 0.04 % | 3.8 % | 8.04 % | 7.75 % | 0.04 % | 0.04 % | 0.03 % | 11.12 % |

Two more windows, same counts:
- run 1 W-e5: 20,685 headers, 95.504 % certified, 930 lost, 1,587 under-held (7.67 %), 61.75 % of the under-held and 98.31 % of the others certified, k ≥ 4 in 9.28 % of rounds;
- run 3 Wgen: 68,859 headers, 99.955 % certified, 31 lost, 12 under-held (0.02 %).

### 3.2 Fleet certification per 300-s bucket of B2 (run 3: of W-mixed)

Definition (bench 7's A2, unchanged): per author, `quorum reached` lines over `header proposed` lines in the bucket; quorum lines for headers proposed just before a bucket count inside it, so a bucket can read above 100.
Each cell is certified % (proposed / reached), then the epoch from validator-01's `header proposed` epoch field and validator-05's state where it changed.

| b | run 1 | run 2 | run 3 | 7a |
|---|---|---|---|---|
| 0 | 21:54:55, e4: 99.84 (8,580 / 8,566) | 00:54:44, e3: 97.66 (7,938 / 7,752) | 15:27:19, e3: 99.93 (8,617 / 8,611) | 13:27:58, e5: 93.93 (8,198 / 7,700) |
| 1 | 21:59:55, e4: 99.99 (8,552 / 8,551) | 00:59:44, e3, e4 from 01:03:51: 98.37 (6,990 / 6,876) | 15:32:19, e3, e4 from 15:32:36: 99.92 (8,578 / 8,571) | 13:32:58, e5: 93.37 (6,988 / 6,525) |
| 2 | 22:04:55, e4, e5 from 22:07:21: 99.83 (8,179 / 8,165) | 01:04:44, e4: 99.99 (7,352 / 7,351) | 15:37:19, e4: 99.99 (8,613 / 8,612) | 13:37:58, e5, e6 from 13:42:41; 05 killed at +217 s: 95.93 (7,174 / 6,882) |
| 3 | 22:09:55, e5: 93.94 (8,251 / 7,751) | 01:09:44, e4: 96.35 (6,637 / 6,395) | 15:42:19, e4: 100.01 (8,614 / 8,615) | 13:42:58; 05 started at +217 s: 97.17 (6,579 / 6,393) |
| 4 | 22:14:55, e5: 95.13 (7,808 / 7,428) | 01:14:44, e4: 92.53 (7,186 / 6,649) | 15:47:19, e4: 99.94 (8,617 / 8,612) | 13:47:58: 95.36 (5,886 / 5,613) |
| 5 | 22:19:55, e5: 96.70 (7,458 / 7,212) | 01:19:44, e4, e5 from 01:23:51; 05 killed at +179 s: 96.98 (6,361 / 6,169) | 15:52:19, e4, e5 from 15:52:36: 99.90 (8,582 / 8,573) | 13:52:58: 96.02 (5,508 / 5,289) |
| 6 | 22:24:55, e5, e6 from 22:27:31; 05 killed at +77 s: 98.98 (6,671 / 6,603) | 01:24:44, e5; 05 started at +179 s: 99.01 (5,240 / 5,188) | 15:57:19, e5: 99.95 (8,621 / 8,617) | 13:57:58: 96.22 (5,402 / 5,198) |
| 7 | 22:29:55 to 22:35:11, e6; 05 started at +77 s: 99.93 (8,020 / 8,014) | 01:29:44 to 01:34:53, e5: 98.24 (5,169 / 5,078) | 16:02:19 to 16:07:19, e5, almost no load after 16:05:54: 100.0 (8,623 / 8,623) | 14:02:58 to 14:08:23: 97.29 (6,967 / 6,778) |

Validator-05 proposed no header between its start and B2's end in runs 1, 2 and 7a, so their buckets after the start have nine authors.
In run 3 no kill happened (§2) and validator-05 was in every bucket.
7a's epochs after bucket 2 are not labelled in the source.
Spans: run 1 93.94 to 99.99, run 2 92.53 to 99.99, run 3 99.90 to 100.01.

### 3.3 Per-epoch segments

Each segment is the window cut at validator-01's epoch boundary (run 2's at 01:03:52, the scripts taking whole seconds), with the same counts as 3.1.

| run, segment | from to | length | headers | certified % | lost | under-held % | certified % of under-held / others | k ≥ 4 |
|---|---|---:|---:|---:|---:|---:|---|---:|
| r1 e4 part (+7:43 into e4) | 21:54:55 to 22:07:21 | 746 s | 21,030 | 99.919 | 17 | 0.02 | 100.0 / 99.92 | 0.0 % |
| r1 e5 part (to the kill) | 22:07:21 to 22:26:12 | 1,131 s | 29,685 | 95.988 | 1,191 | 5.85 | 58.99 / 98.29 | 6.46 % |
| r2 e3 part (+11:01 into e3) | 00:54:44 to 01:03:52 | 548 s | 13,727 | 97.807 | 301 | 8.73 | 76.48 / 99.85 | 12.31 % |
| r2 e4 part (to the kill, 68 s before e5) | 01:03:52 to 01:22:43 | 1,131 s | 26,840 | 96.434 | 957 | 7.36 | 52.51 / 99.92 | 5.53 % |
| r3 e3 part (+14:42 into e3) | 15:27:19 to 15:32:37 | 318 s | 9,119 | 99.945 | 5 | 0.07 | 100.0 / 99.95 | 0.11 % |
| r3 e4 whole | 15:32:37 to 15:52:37 | 1,200 s | 34,424 | 99.954 | 16 | 0.02 | 100.0 / 99.95 | 0.03 % |
| r3 e5 part | 15:52:37 to 16:07:19 | 882 s | 25,322 | 99.961 | 10 | 0.0 | none under-held / 99.96 | 0.0 % |

Run 1's and run 2's segments add back to their W-prekill; run 3's add back to W-mixed (68,865 headers, 31 lost).
7a's W-817 lies inside its epoch 5 (13:22:35 to 13:42:41), from +5:23 to 66 s before epoch 6, so it has one segment, the window itself.

### 3.4 Per author: lost headers

Each cell: headers proposed, certified %, lost, under-held.

| author | r1 W-prekill (1,877 s) | r2 W-prekill (1,679 s) | r3 W-1679 | 7a W-817 |
|---|---|---|---|---|
| 01 | 5,080, 100.0, 0, 0 | 4,195, 99.95, 2, 52 | 4,829, 100.0, 0, 2 | 2,077, 100.0, 0, 0 |
| 02 | 5,054, 86.05, 705, 566 | 4,193, 89.6, 436, 788 | 4,759, 99.75, 12, 0 | 2,072, 99.71, 6, 47 |
| 03 | 5,074, 99.98, 1, 0 | 4,192, 97.59, 101, 266 | 4,830, 100.0, 0, 1 | 2,077, 97.16, 59, 299 |
| 04 | 5,080, 97.26, 139, 441 | 4,194, 99.9, 4, 128 | 4,829, 100.0, 0, 1 | 2,076, 94.08, 123, 482 |
| 05 | 5,080, 99.37, 32, 158 | 4,194, 96.76, 136, 513 | 4,829, 99.96, 2, 1 | 2,076, 100.0, 0, 0 |
| 06 | 5,032, 99.8, 10, 0 | 4,193, 98.02, 83, 212 | 4,758, 99.79, 10, 0 | 2,073, 62.71, 773, 886 |
| 07 | 5,079, 98.54, 74, 247 | 4,194, 97.97, 85, 287 | 4,829, 100.0, 0, 2 | 2,077, 100.0, 0, 0 |
| 08 | 5,079, 100.0, 0, 1 | 4,194, 99.21, 33, 303 | 4,830, 100.0, 0, 2 | 2,077, 86.42, 282, 702 |
| 09 | 5,079, 100.0, 0, 1 | 4,188, 91.0, 377, 625 | 4,830, 100.0, 0, 2 | 2,077, 99.86, 3, 92 |
| 10 | 5,078, 95.14, 247, 327 | 2,830, 99.96, 1, 0 | 4,823, 99.98, 1, 1 | 2,076, 100.0, 0, 0 |
| fleet lost | 1,208 | 1,258 | 25 | 1,246 |

Lost per author in the 817-s windows:
- run 1: 02 10, 06 9, 05 2, 10 2, 03 1, the rest 0 (24);
- run 2: 07 85, 02 84, 06 83, 05 38, 08 5, 04 4, 01 1, 09 1, 10 1, 03 0 (302); validator-10 proposed 1,373 headers in run 2's W-817 against about 2,100 for the others, and 2,830 against about 4,190 in its W-prekill;
- run 3: 02 6, 06 6, the rest 0 (12);
- run 3 over W-mixed: 02 14, 06 13, 05 3, 10 1, the rest 0 (31).

Per author in run 1's W-e5, certified %: 02 77.2, 10 88.2, 04 94.8, 07 96.4, 05 98.6, 06 99.95 (1 lost), the rest 100.

### 3.5 The distance named and the share at the floor

Distance: the proposer's execution tip minus the block its header named, counted in block-bearing outputs.
Basis: which rule picked the named block, the floor (the tip minus the floor's depth), the block a quorum held, or the tip itself.
At the floor: distance equal to the floor's depth (16 in run 1, 8 in runs 2, 3 and 7a).

| window | mean | p50 | p95 | at the floor | above 8 | below the floor | basis floor / quorum / tip |
|---|---:|---:|---:|---:|---:|---:|---|
| r1 W-817 | 14.481 | 16 | 16 | 73.13 % (= 16) | 94.87 % | not given | 69.34 / 30.52 / 0.13 % |
| r1 W-prekill | 14.735 | 16 | 16 | 77.83 % (= 16) | 94.17 % | not given | 73.67 / 26.1 / 0.22 % |
| r2 W-817 | 7.191 | 8 | 8 | 87.48 % (= 8) | 0 | 12.52 % | 86.03 / 5.99 / 7.98 % |
| r2 W-prekill | 7.081 | 8 | 8 | 86.83 % (= 8) | 0 | 13.17 % | 85.79 / 4.21 / 10.0 % |
| r3 W-817 | 7.962 | 8 | 8 | 99.2 % (= 8) | 0 | 0.8 % | 56.89 / 42.98 / 0.13 % |
| r3 W-1679 | 7.962 | 8 | 8 | 99.2 % (= 8) | 0 | 0.8 % | 57.06 / 42.82 / 0.12 % |
| r3 W-mixed | 7.974 | 8 | 8 | 99.44 % (= 8) | 0 | 0.56 % | 56.75 / 43.16 / 0.09 % |
| 7a W-817 | 7.608 | 8 | 8 | not in 7a's JSON | 0 [inferred: a floor of 8 caps the distance; p95 8 measured] | not given | 78.03 / 21.96 / 0.01 % |

No header in run 1 named a block more than 16 outputs back (0 % above 16).
Run 1's node-side count of headers whose named block equalled the floor (`floor_eq_named_pct` in the cross-check JSON) equals the share at 16 in both windows.

Per author, mean distance and the share of headers whose basis was the floor:

| author | r1 W-prekill | r2 W-prekill | r3 W-1679 | 7a W-817 |
|---|---|---|---|---|
| 01 | 15.851, 90.91 % | 7.939, 98.69 % | 7.961, 52.35 % | 7.906, 79.83 % |
| 02 | 15.863, 93.81 % | 7.96, 98.35 % | 7.961, 58.21 % | 7.772, 82.48 % |
| 03 | 13.832, 33.52 % | 7.948, 98.23 % | 7.963, 58.01 % | 8, 100.0 % |
| 04 | 15.906, 98.92 % | 7.946, 97.23 % | 7.963, 55.5 % | 8, 100.0 % |
| 05 | 15.904, 98.88 % | 7.962, 99.26 % | 7.962, 55.46 % | 6.974, 21.15 % |
| 06 | 10.916, 16.51 % | 7.193, 83.21 % | 7.962, 58.6 % | 8, 100.0 % |
| 07 | 15.907, 94.82 % | 3.02, 32.83 % | 7.963, 57.53 % | 7.19, 57.73 % |
| 08 | 11.333, 12.78 % | 7.96, 99.05 % | 7.963, 60.83 % | 8, 100.0 % |
| 09 | 15.907, 97.32 % | 7.813, 91.81 % | 7.963, 57.62 % | 8, 98.7 % |
| 10 | 15.899, 98.8 % | 4.102, 46.43 % | 7.96, 56.5 % | 6.243, 40.41 % |

### 3.6 The achieved rate

Executed: validator-01's executed transactions over the window; landed: the generators' own count of transactions that landed; chain: the chain's transactions per second as one generator's results read them.
Validator-02's executed rate is given as a check.

| run, window | executed tx/s (v01) | landed tx/s | chain tx/s | v02 executed tx/s | transactions, outputs (v01) |
|---|---:|---:|---:|---:|---|
| r2 W-mixed (B2, 2,409 s) | 9,210.9 | 9,163.2 | 9,171.1 | 9,165.0 | 22,189,000, 2,790 |
| r2 gen-mixed (2,400 s) | 9,214.6 | 9,189.4 | 9,205.5 | 9,169.4 | 22,115,141, 2,778 |
| r2 W-817 | 10,067.7 | 10,013.9 | 10,061.3 | 9,993.0 | 8,225,307, 1,042 |
| r2 W-prekill | 9,473.1 | 9,464.6 | 9,487.6 | 9,467.9 | 15,905,342, 2,055 |
| r3 W-mixed (the driver's, 2,400 s) | 5,181.6 | 5,175.4 | 5,171.1 | 5,181.6 | 12,435,822, 3,350 |
| r3 gen-mixed (the generators', 2,400 s) | 5,356.8 | 5,354.8 | 5,357.9 | 5,356.8 | 12,856,399, 3,452 |
| r3 W-817 | 5,340.6 | 5,338.9 | 5,338.9 | 5,340.6 | 4,363,275, 1,174 |
| r3 W-1679 | 5,354.7 | 5,357.3 | 5,357.3 | 5,354.7 | 8,990,511, 2,413 |

Run 3's validity band was 4,500 to 6,500 tx/s; the first look reads it inside the band by both counts in every window (verdict valid).
Run 3's W-mixed reads lower than its gen-mixed because W-mixed misses the load's first 85 s and holds 85 s with almost no load (§2).

Per 300-s bucket of B2 (run 3: of W-mixed), executed / landed tx/s:

| b | run 2 | run 3 |
|---|---|---|
| 0 | 10,481.3 / 10,448.2 | 5,341.2 / 5,356.9 |
| 1 | 10,128.1 / 10,056.1 | 5,302.9 / 5,285.6 |
| 2 | 9,534.8 / 9,442.9 | 5,376.3 / 5,386.7 |
| 3 | 9,112.3 / 9,188.3 | 5,406.5 / 5,403.4 |
| 4 | 8,658.8 / 8,638.7 | 5,385.7 / 5,386.9 |
| 5 | 8,383.1 / 8,401.1 | 5,314.2 / 5,319.3 |
| 6 | 8,732.3 / 8,715.1 | 5,416.4 / 5,403.7 |
| 7 | 8,672.5 / 8,437.0 | 3,909.5 / 3,860.5 |

Run 1's rate was not computed by any bench 8 analysis.
Run 7a's rate by bench 7's definition (chain tx/s over the window in which all ten generators were in their mixed phase, 2,375 s, the kill inside) was 9,289 tx/s (bench 7 report, §1); that window and count differ from the ones above, so it is beside the table, not in it.

### 3.7 The engines' busy share

Busy: the sum of execute and persist milliseconds per 120-s bucket, divided by 120 s, as the median over 13 full buckets.
Windows: run 2's W-prekill (00:54:44 to 01:22:43) and run 3's W-1679 (15:27:19 to 15:55:18).
Each cell: median busy (highest single bucket); outputs per 120 s; execute ms and persist ms per output.

| validator | run 2 (full load) | run 3 (reduced load) |
|---|---|---|
| 01 | 0.982 (0.987); 143; 429.5, 351.1 | 0.555 (0.585); 173; 221.3, 164.8 |
| 02 | 0.965 (0.987); 140; 415.4, 346.4 | 0.589 (0.620); 173; 219.5, 192.8 |
| 03 | 0.973 (0.988); 145; 400.5, 360.5 | 0.569 (0.600); 173; 221.4, 174.8 |
| 04 | 0.982 (0.989); 139; 422.7, 358.0 | 0.567 (0.602); 173; 220.4, 173.2 |
| 05 | 0.959 (0.988); 140; 404.2, 373.5 | 0.581 (0.621); 173; 228.4, 179.3 |
| 06 | 0.984 (0.992); 143; 424.7, 384.3 | 0.567 (0.603); 173; 224.2, 172.9 |
| 07 | 0.982 (0.991); 142; 427.6, 387.8 | 0.574 (0.605); 173; 218.9, 179.6 |
| 08 | 0.981 (0.995); 142; 415.7, 359.6 | 0.565 (0.591); 173; 219.2, 172.7 |
| 09 | 0.979 (0.988); 145; 414.5, 345.0 | 0.571 (0.597); 173; 223.3, 174.4 |
| 10 | 0.983 (0.989); 145; 442.9, 362.7 | 0.566 (0.606); 173; 222.8, 173.3 |

Run 1's and 7a's busy shares are not in the bench 8 analyses.

### 3.8 The harness's own count, as a cross-check

The harness counts `quorum reached` over `header proposed` per validator over the load blast's whole mixed phase, the kill included (`analysis/certification.json`, window "blast 2 mixed").
The first looks recomputed it with bench 7's A2 definition over B2 and got the harness's counts exactly in runs 1 and 2.

| run | proposed | reached | certified % | per validator |
|---|---:|---:|---:|---|
| 1 (floor 16) | 63,519 | 62,290 | 98.07 | 01 100.0, 02 89.0, 03 100.0, 04 97.8, 05 99.4, 06 99.8, 07 98.8, 08 100.0, 09 100.0, 10 96.1 |
| 2 (floor 8) | 52,873 | 51,458 | 97.32 | 01 99.9, 02 92.2, 03 98.2, 04 98.5, 05 96.8, 06 98.5, 07 98.1, 08 99.3, 09 93.3, 10 98.5 |
| 3 (reduced load) | none | none | none | the harness has no window for run 3's load blast (§6) |
| 7a (floor 8) | 52,702 | 50,378 | 95.59 | 06 83.6, 08 85.5, 04 95.6, 10 97.7 (the others not in the run facts) |

In place of the missing run 3 count, the same A2 definition over run 3's W-mixed gives 68,834 of 68,865, 99.95 %.

## 4. Findings, ranked by what they change

Each statement is marked measured, read from code, inferred, or a timing fit.
Runs 1, 2 and 3 each ran once, and so did bench 7's run 7a, so no comparison here carries a significance claim.
The windows are those of §3.0; the counting unit for certification is a validator's own `header proposed` line unless a line says otherwise.
"Behind" means the distance from the fleet's execution lead, in block-bearing outputs, as run 1's epoch-5 analysis (A-E5) and run 2's first look (A-F2) define it.

### 4.1 Who loses headers, and when

Headers are lost on the validators at the front of execution, at moments when four or more of the other voters are further behind than the floor.

[measured, run 2, W-prekill] Of the 1,258 lost headers, 1,251 came from authors at most 2 outputs behind the lead.
Authors 3 to 8 behind lost 6 of 9,065 headers; authors more than 8 behind lost 1 of 10,569, and that one is validator-10's header at the epoch close (§4.5).
[measured, run 1, W-prekill] With the same script and a threshold of 8 (in-sample, and not the threshold that fits floor 16), 1,190 of 1,208 lost headers came from authors at most 2 behind.
[measured, run 1, epoch 5] The five validators that spent 1,000 s or more over 8 outputs behind (01, 03, 06, 08, 09) lost 6 of their own headers between them; the other five lost 30 to 697 each.

The losers are not a fixed set; they are whoever leads at the time (§3.4).
[measured, run 2] The leaders changed at the e3→e4 boundary.
In e3, validators 06 and 07 led and lost 83 and 85 headers, while 03, 09 and 10 trailed.
In e4, 06 and 07 fell up to 25 and 47 outputs behind (minute medians) and lost nothing, while 03 and 09 led and lost 101 and 377.
A per-author total over a window that crosses a boundary therefore mixes two regimes.
Not every leader loses: validator-04 led in run 2's e3 and lost 4.

The step sits between three and four voters behind.
[measured, run 2, W-prekill] k counts the other voters whose latest header tip was more than 8 outputs behind the lead when the header was proposed, leaving out voters whose latest header line was more than 5 s old.
Certified: 99.40 % at k = 3 (13,917 headers), 82.26 % at k = 4 (5,947 headers); 99.73 % over all k ≤ 3 and 81.33 % over all k ≥ 4.
1,160 of the 1,258 lost headers had both the author at the lead and k ≥ 4.
With stale voters counted as behind instead of left out (the figure-check's recount), the step stays: 99.90 % at k ≤ 3 (33 lost of 33,556) against 82.53 % at k ≥ 4 (1,225 lost of 7,011).
[measured, run 2, per minute] The 4 minutes with four or more voters over 8 behind (by minute median) were all below 99 % (88.28 to 93.08 %).
Of the 24 minutes with three or fewer, 14 were below 99 %, and in each of those 14 a fourth validator's median sat at 6 to 8, just inside the floor.
[inferred] The minute median misses voters sitting just inside the floor, and it missed validator-10 in the minutes it proposed nothing.

What is definitional and what is observed, as run 2's figure-check words it.
The k table is not independent evidence of the mechanism, because it uses the same voter tips as the under-held definition.
A leader that names its floor block while four or more others are more than 8 behind is under-held by quorum arithmetic: it needs 6 of the other 9 voters to hold the block, and four non-holders leave 5.
Over all k ≥ 4 headers only 46.5 % are under-held, because not every author is at the lead.
What the data add is the outcome [measured, the figure-check's recount, run 2, W-prekill]:
- headers that were not under-held were lost at about 0.1 % whatever k was (33 of 34,059 at k ≤ 3, 5 of 3,334 at k ≥ 4);
- under-held headers at k ≥ 4 were lost at 40 % (1,159 of 2,901);
- the laggards' own headers were almost never lost (1 of 10,569 from authors more than 8 behind);
- the voters' own deficit fields, which k does not use, agree: in run 2's W-817, 8,341 of 8,341 `behind` answers carried an execution deficit.
[measured, A-F2's cross-check table, not rechecked by its figure-check] In the same window, 26,127 of 26,129 `superseded` answers carried a deficit, against 1,819 of 149,359 `created` answers (1.22 %).

Run 3 could not test the step: k was 0 for all 68,865 headers (§4.4).
Run 7a fits the same picture on bench 7's figures: 1,144 of its 1,246 lost headers in W-817 were under-held (§3.1).

### 4.2 The second path in run 1 is the same root

At floor 16, 496 of run 1's 1,208 lost headers in W-prekill were not under-held, against 38 of 1,258 in run 2 at floor 8 (§3.1).
A-E5 took the worst five minutes of run 1 apart, validator-02 first, and these headers fail on the same lagging voters as the under-held ones.

[measured, run 1, validator-02, bucket b3, 22:09:55 to 22:14:55] Validator-02 proposed 824 headers and lost 412.
Its round-end lines: 412 `quorum reached`, 411 `header uncertified reason=canceled`, 1 `reason=no_certificate`; the quorum threshold is 7.
The 412 lost headers split three ways:
- 182 under-held (3 to 5 holders at the proposal);
- 230 cut off by validator-02's own next header while at least 6 voters held the named block, every one with at least one `superseded` answer (the figure-check checked all 230);
- 0 refused for another reason.
Validators 04, 05 and 07 answered `created` on all 412 lost headers; 06 and 08 answered `superseded` on 410 of them, and 03 on 371.

The bare quorum of seven.
On 193 of the 230 cut-off headers the count was exactly seven: validator-02 itself plus 01, 04, 05, 07, 09 and 10 answered `created`, and 03, 06 and 08 answered `superseded`.
Six holders among the other nine is not a margin; it is the minimum.
On the other 37, a seventh voter also answered `created` and two answered `superseded`, so one vote was spare, and the round was still lost.
On 223 of the 230 the round ended with 6 votes counted, one short [measured by the figure-check].

The round's end at the author's next header.
All 411 `canceled` lines are logged 0.6 to 21.2 ms after validator-02's next own `header proposed` line (p50 1.4 ms) [measured].
That a round ends at the author's next header is shown by this timing, not by a field of the round-end line.
Validator-02's rounds (own header to next own header) ran p50 354 ms, p95 400 ms; the other authors in the same window ran 354 / 407 ms, so its rounds were not shorter than the fleet's [measured].
What sets the 354 ms is not measured.
[inferred] Validators 06 and 08, and usually 03, lacked the block validator-02 named, waited, and were superseded by validator-02's later request about 708 ms after arrival; on the 193 bare-quorum headers, any one of the six `created` votes landing after validator-02's next header cancels the round.

Validator-02 sat at the execution lead from 22:10; in epoch 4 it had trailed the leaders, 04 and 05, by 2 to 8 outputs [measured].
The same split in narrower windows, corrected by the figure-check [measured]: validator-04 (22:12:00 to 22:14:00) lost 62, all under-held; validator-10 (22:14:30 to 22:17:00) lost 81, of which 38 were under-held, 43 cut off with 6 or more holders at arrival, and 0 other.
Over the whole W-prekill, 343 of validator-02's 705 lost headers (49 %) were not under-held at the proposal, and 462 (66 %) were held by at least 6 others when cancelled: two different measures, both putting a large part of its loss outside the under-held path [measured, A-F1].

Why this is the same root [inferred]: both paths need the same three to five voters to be behind in execution.
An under-held header fails because too few voters hold its block; a cut-off header fails because exactly enough hold it, so one late vote leaves the round short when the author's next header ends it.
Neither path appears when the voters are in step (run 3, §4.4).
Not known: why the second path is large at floor 16 and almost absent at floor 8 (run 2's lost headers held by 6 or more others when cancelled: 20 of validator-02's 436, 18 of 05's 136, 8 of 03's 101, 4 of 09's 377); there is one run per floor.
Not measured: when each vote reached validator-02; the count of votes created before its next header uses two hosts' clocks.

### 4.3 What the floor does and does not do

Runs 1 and 2 differ only in the floor, 16 against 8; there is one run per floor.
[measured, §3.3] In the first epoch under load, run 1's e4 part read 99.919 % certified with 0.02 % under-held (17 lost); run 2's e3 part read 97.807 % with 8.73 % (301 lost).
In the second, run 1's e5 part read 95.988 % with 5.85 % (1,191 lost); run 2's e4 part read 96.434 % with 7.36 % (957 lost).
[measured, A-E5 Q5] Run 1's e4 was clean although several voters were more than 8 behind (minute medians up to 17 for 03 and 21 for 06), and run 1's own k table at a threshold of 8 shows no step (k = 4: 99.98 % certified).
[inferred, a timing fit] The threshold moves with the floor: the loss needs four or more voters beyond the floor's depth, not beyond 8.

The deeper floor bought the first load epoch and not the second.
[measured, A-E5 Q5] The spread collapsed at the e4→e5 boundary (at 22:07 every minute median was 4 or less, except 06 at 15) and regrew within 2 to 4 minutes, wider than in e4: by 22:11 to 22:12 five voters were 14 or more behind (01, 03, 06, 08, 09), against two or three at most in e4.
[measured, A-E5 Q4] On 12 to 18 % of validator-02's floor-named headers in buckets b3 to b5, no quorum of voters held even the floor block; the figure-check rechecked only b3's row (81.7 % of floor headers with 6 or more holders by the voters' fields).
[measured, §3.5] No header in run 1 named a block more than 16 back, and 73 to 78 % named one exactly 16 back.
The floor also moved part of the loss onto the bare-quorum path of §4.2 [measured split; why, not known].

The plan's rule for run 1 (the plan, Step 5d; the file is named in the sources note):

| Run | Single change | Result | Next |
|---|---|---|---|
| 1, F | floor 16 | certification at least 99.0 % with under-held under 1 % | the loss acts only through under-held headers: run R |
| | | at most 97.3 % | another path: run H (no hold), then a voter-wait parameter |
| | | between | run C (control repeat) first |

[measured, §3.1] W-prekill, the window before the kill as the rule is written, read 97.618 % and 3.43 %: the "between" row, run C, which was run 2.
W-817 read 99.895 % and 0.03 %: the first row; but W-817 lies almost wholly in run 1's clean e4.
The supplementary W-e5 (run 1's epoch 5 at 7a's offset into its epoch) read 95.504 % and 7.67 %, which is in the "at most 97.3 %" row.
W-prekill's 97.618 % sits 0.3 points from the 97.3 bound, inside run 1's own bucket spread of 93.94 to 99.99 % (§3.2).
Against 7a, aligned by epoch, run 1 read 95.50 % and 7.67 % where 7a read 94.00 % and 12.08 %; A-F1 calls that a timing fit, not a mechanism.

### 4.4 The root: saturated executors drift tens of outputs apart; with slack none falls behind

Runs 2 and 3 differ only in the load blast: 600 senders × window 16 against 300 × 4, on the same build at floor 8; one run each.
[measured, §3.7] The engines' busy share (execute plus persist time per 120 s, median over 13 buckets) was 0.959 to 0.984 per validator in run 2 (the highest single bucket 0.995) and 0.555 to 0.589 in run 3 (the highest 0.621).
[measured, A-F3 §3] In run 3 every validator's minute median distance behind was 0 in all 40 minutes, the largest distance any validator reached was 2 outputs (validator-01), and no validator spent a second more than 8 behind; of 68,865 headers, 66,931 were proposed at 0 behind, 1,930 at 1 and 4 at 2.
[measured, A-F2 §2] In run 2 at least one validator was more than 8 behind in 27 of 28 minutes, minute medians reached 53 (validator-10) and 47 (validator-07), and validator-10 spent 1,633 s more than 8 behind (its 541-s silence charged at its last distance).
[measured, §3.1] Run 3 read 99.948 % certified with 0.02 % under-held over W-1679 and 99.955 % with 0.02 % over W-mixed, against 96.899 % and 7.82 % in run 2's W-prekill.

The contrast is in the longer windows.
The first 817 s alone do not separate reduced from full load: run 1 at full load read 99.895 % and 0.03 % there (the figure-check of A-F3).
Over 1,679 s and the whole mixed phase run 3 read 99.948 % and 99.955 %, against 96.899 % in run 2 and 97.618 % in run 1 over their windows before the kill.

The uneven load in run 3 is on the ingress side and only concentrates the residual loss.
[measured, A-F3's figure-check] All ten validators executed the same 5,072 outputs and 17,788,630 transactions, so every engine had the slack.
[measured, A-F3 §1] The generators for validators 02 and 06 landed 107.5 and 95.4 tx/s against 573 to 682 tx/s for the other eight, and those two validators built batches at 114.3 and 103.0 tx/s against 564 to 682; the cause is not measured.
They proposed about 103 fewer headers each and lost 27 of the 31; without them, 4 of 55,256 headers were lost (99.993 %).
The 31 lost headers all sat at k = 0 and none was under-held; q2 labels their non-voters `error / held at proposal`, so this is not the execution-deficit path [measured label, not interpreted].

[a timing fit, not a mechanism] At about 57 % busy every engine had about 40 % slack and no execution tip fell behind; at about 97 % busy the tips drifted tens of outputs apart and the loss of §4.1 followed.
Other things also differed between runs 2 and 3 [measured, A-F3 §7]: run 3 proposed 28.7 headers per second fleet-wide against 24.2; it had more, smaller outputs (173 against 140 per 120 s on validator-02, at 219.5 against 415.4 ms of execute time per output); validator-10 voted throughout (§4.5); and there was no kill.
Which validators fall behind at saturation, and why, is not measured: run 2's per-validator medians in §3.7 are whole-window figures and were not tested against who lagged when.

The plan's rule for run 3 (the same file, Step 5d):

| Run | Single change | Result | Next |
|---|---|---|---|
| 2, R | load blast at about 5,300 tx/s (void outside 4,500-6,500) | under-held under 1 % and at least 99.0 % | the cause is the spread of execution tips at full load; stop |
| | | under-held at least 5 % | the build makes the spread at any load; H next |

Run 3 ran at 5,356.8 tx/s executed over the generators' own mixed phase (5,181.6 over the driver's window, §3.6), inside the band, and selected the first row in all three windows; by the plan, bench 8's runs stop there.

### 4.5 The lagging validator at an epoch close

Sources: the local issue draft `tasks/issue-bodies/bench8-lagging-validator-at-epoch-boundary.md`, figure-checked against the raw logs and the code (`…/notes/bench8-lagging-validator-at-epoch-boundary.figcheck.md`), and A-F2 §6.
The draft is not posted; it waits for the owner's review.

[measured, run 2] Validator-10, never restarted, was behind in execution when the other validators closed epoch 3 under load.
By A-F2's minute medians it ran 25 to 53 outputs behind the lead in e3; its own log at the demotion reads `backlog_outputs=15 exec_lag_rounds=30`, a different measure at a different moment.
Its lag built from 00:54 to 00:58, when its persist time per output was 377 and 414 ms against 279 and 282 ms on validator-02 (A-F3 reproduces those four figures).

The internal error [measured].
Its round-3276 header of epoch 3 went out at 01:03:43.240, 71 ms after the last of the others logged `epoch boundary detected` (01:03:43.075 to 01:03:43.169).
Every voter answered `Failed to return pending certificate manager result` (62 answers from all nine voters), then, once in epoch 4, `Invalid epoch. Peer proposed epoch 3, but expected 4` (154 answers until 01:04:06.695); each was logged as `fatal request for requested vote`, with 23 re-proposals in 22 s.
The two sources disagree on when the internal-error answers stopped: the issue draft gives 01:03:55.411, A-F2 gives 01:03:52; the issue draft's times were checked against the raw log.
[read from code, on the build and on main at 5533ff73a] The vote path waits on a reply from the certificate manager and turns a dropped reply into `HeaderError::PendingCertificateOneshot`; the manager answers only until its loop returns on shutdown; the certifier treats any error answer as fatal for that voter and header.
[inferred from the times] Each voter's epoch-3 certificate manager had stopped at the close while its vote handler still took epoch-3 requests; validator-02, a voter, logged `Certifier received shutdown` at 01:03:43.156 and `Starting epoch` at 01:03:48.265.

The demotion and the nine minutes [measured].
Validator-10 logged the boundary 23.8 s after the others; at 01:04:09.429 it logged `we are behind, go to catchup mode!` with `epoch=4 exec_epoch=3 number=None`, `round=41`, `gc_window=40`, `reason=epoch_behind`.
[read from code] `number=None` is the certificate rule of `behind_consensus`: a node still executing the previous epoch passes only while the new epoch's round is at most `gc_depth.max(6)`, 40 here; it was demoted at round 41.
Its `rejoin not ready … reason=round_gap` lines had the handled round 30 to 80 rounds behind the newest (48 to 66 by minute from 01:05 to 01:09); at 01:12:43.824 it rejoined through the 20-round window and was `CvvActive` at 01:12:44.092.
It was out 8 min 35 s, proposed no header for 541 s (01:03:43.240 to 01:12:44.716), answered 15,821 vote requests `behind`, and signed no vote until its promotion.

Twice in run 2, never in runs 1 and 3.
[measured] Validator-07 did the same at the next close (e4→e5, 01:23:51), after the planned kill of validator-05: 54 internal-error answers from eight voters about its round-2938 header of epoch 4, demotion at `round=41`, 8 min 40 s inactive, 550 s without a header, 15,758 `behind` answers and none signed.
It had been 39 to 47 outputs behind (minute medians) from 01:12:44 to the kill (A-F2 §2).
[measured] In run 1 no validator went more than 30 s without a header, apart from start-up and the planned kill (the issue draft).
[measured, absence of matches] In run 3 no validator's gap between its own headers exceeded 1.13 s, no internal-error answer appeared in the blast, and no catch-up line appeared in any log (A-F3 §6).

How it feeds §4.1 [inferred].
With validator-10 out, the fleet voted with nine members for most of run 2's W-prekill: a quorum of 7 with one spare voter fewer than in run 1, where `behind` answers numbered 2 in W-817.
A-F2 calls this the main confound of the run 1 against run 2 comparison.
Run 2's e4 was clean for its first 6 minutes (99.99 % in bucket b2), and the loss came back from 01:09:44, once 06 and 07 were more than 8 behind while validator-10 was silent [measured times].
Two checks bound the confound [measured]: the under-held counts do not depend on validator-10's stale tip (a stand-in leaves them at 1,199 and 3,174), but k leaves validator-10 out during its gap, so k there may be one short.
The two findings feed each other: the drift of §4.4 put validator-10 and validator-07 tens of outputs behind at a loaded close, and the demotion then took a voter out for nine minutes [inferred].

### 4.6 The far validators

Source: `benchmark/private/bench8-far/far.md` (A-FAR), figure-checked.
Far means validators 02 and 06, the only two in Europe; near means the other eight.
Windows: light blast 1 of each run and run 3's load blast.

[measured] The far validators are still the outliers in every window.
Their generators landed 95 to 200 tx/s against 573 to 1,223 tx/s for the near ones, and they built 0.39 to 0.68 batches per second against 2.44 to 4.80.
[inferred, as in #1870, not measured separately] The generators keep a fixed number of transactions in flight, so their send rate follows the latency.

The step, measured with bench 8's new log lines.
[measured, run 1 light blast 1 and run 3 load blast] In 96 to 98 % of (near receiver, far certificate) pairs, the far round-r certificate entered the receiver's aggregator after that receiver had already logged its own round r+1 header (p50 200 to 229 ms after).
76 to 88 % of far certificates were named by no near round r+1 header, and fewer than 1 % by 4 or more of the nine others (0.00 to 0.65 %).
In every pair where the certificate arrived after the receiver's own r+1 header, that header does not name it: 0 of 8,428 and 8,731 pairs in run 1's light blast 1, 0 of 53,141 and 53,759 in run 3's load blast.
[read from code, at b1104905f and byte-identical on main at 5533ff73a] The proposer takes its parent set when it builds round r+1 and moves to r+1; a parent set that arrives later takes the `Less` arm of `process_parents` and is dropped, and a late round-r certificate has no other route into a later header.
[measured] Far certificates were committed at 17 to 30 % (node side, all four windows), against 99.94 to 100 % for the near control; every far certificate named by 4 or more round r+1 headers was committed.
[measured] Validators 02 and 06 have a leader-schedule score of 0 at p50 and sit in `bad` in every update inside each analysed window; [inferred] they never lead, which closes the leader path to commit too; the scoring code was not read.

Why those two [measured, with unmeasured clock offsets on the cross-clock figures].
A far validator's own certificate forms 286 to 297 ms after its own header (p50), against 134 to 182 ms for a near one, and reaches the near validators 262 to 284 ms (p50) after their own quorum moment.
[inferred, a fit to geography, not a measured mechanism] A quorum of 7 forms among the near validators without Europe, so they build round r+1 before the European certificates arrive.

What it does not do.
The step costs commits, not certificates: the far validators' own headers reach a quorum at about the rate they are proposed (run 1 light blast 1: 1,530 quorums for 1,531 headers on validator-02, 1,524 for 1,531 on 06) [measured].
It is a separate problem from §4.1 to §4.4.
Validator-02 is far and was the largest loser in runs 1 and 2, but A-E5 places its run-1 loss at the execution lead (§4.2); whether its distance makes its bare quorum later is not measured (§7).
Before the runs this step was inferred (bench 7, the no-run analysis N5); the order and the naming are now measured, and the drop is read from code.
Upstream issue #1870 already describes the far validators; a comment with these figures would be a local draft, written only on the owner's word, and nothing is posted during the freeze.

### 4.7 What did not happen

Only what a source states.
- Run 3 had no kill: the planned kill failed after the cloud login died (§2, §6.1).
- Run 3 had no validator silence, no internal-error vote answer in the blast and no catch-up line in any validator's log; the last is an absence of matches, and the node's exact mode-line text was not verified (A-F3 §6).
- Run 3's generators lost nothing: every generator's submitted count equals its landed count, with 0 RPC errors (A-F3 §1).
- In run 1 no validator went more than 30 s without a header, apart from start-up and the planned kill (the issue draft).
- In run 2 validator-10 was never restarted; it fell out through demotion, not a crash (the issue draft).
- In runs 1 and 2, as in 7a, validator-05 proposed no header between its restart and the end of B2 (§3.2).
No analysis looked across runs 1 and 2 as a whole for crashes or restarts beyond these, and this section claims nothing about them.

### 4.8 Against what was concluded before the runs

`tasks/bench8/no-run-findings.md` drew five conclusions from bench 7's data.
The runs bear out these:
- Most lost headers were under-held (5.51 of 7a's 6.00 lost points): in run 2, 1,220 of 1,258 (97.0 %).
- The voters that lacked the block were the same three to five validators for minutes at a time, a set that changes over the blast: run 2's per-minute table shows it, and the set swapped at the e3→e4 boundary (§4.1).
- Every executor was saturated under the load blast (7a: busy 980 to 1,009 ms per s): run 2 read 0.959 to 0.984, and run 3 adds the other side, that at 0.555 to 0.589 no tip falls behind (§4.4).
- The header is dead before a lagging voter's wait of about 1,000 ms binds, because the author's next header decides: run 1 shows every cancelled round of validator-02 in b3 ending within 21.2 ms of its next header (§4.2); bench 8 tested no voter wait.
- The far validators' uncommitted certificates are a commit problem apart from the certification loss: the step is now measured and read in code (§4.6).

The runs change these:
- "Floor 16 would have put every pre-kill header within a quorum's reach" was inferred from bench 7's spread never exceeding 16; in run 1's second load epoch five voters were 14 or more behind and on 12 to 18 % of validator-02's floor-named headers no quorum held even the floor block (§4.3).
- The not-under-held remainder was small in 7a (0.49 of 6.00 points) and tied to validator-06 and runs of losses; in run 1 it was 496 of 1,208 lost headers, and it is the bare-quorum path of §4.2, which the no-run analyses did not name.
- Before the runs, the far validators had a second symptom, under-held headers certified less under load (N2); in bench 8 validator-02's large losses are placed at the execution lead, and the two causes are not separated (§4.6).
- The lagging validator at an epoch close (§4.5) is new; nothing before the runs predicted it.

Not tested by the runs: the own-chain order hold (N3; run H never ran) and a longer or shorter voter wait.

## 5. What this means for the node

Everything here is a suggestion.
None was built or tried in bench 8, and each rests on one run per configuration.
Each names the finding of §4 it comes from.

Where the code stands: the stack of pull requests bench 8's build came from is merged into main (#1862, squash 8c75f7582; main at 5533ff73a), without its runtime switches.
Bench 8's build was bench 7's image commit with the switches on, plus a bench-only parameter for the floor's depth and log fields; neither the parameter nor the fields are in what merged.
The code paths that §4.5 and §4.6 read are the same on main.

### 5.1 The floor's depth is not a fix by itself (§4.3)

Suggestion: do not take a deeper floor upstream as the fix for the certification loss.
At floor 16 run 1's first load epoch was clean (99.919 %), but in the second the spread grew past 16 for enough voters that the loss came back (95.988 %), and part of it moved to the bare-quorum path of §4.2.
[inferred, a timing fit] A deeper floor moves the threshold at which the loss starts; it does not stop execution tips drifting further apart.
There is one run per floor, and the floor at 16 was read in two epochs only.

### 5.2 A named block with a margin above the bare quorum (§4.2)

Suggestion: when the proposer chooses the execution block its header names, choose the newest block held by one more voter than the quorum needs (seven of the other nine by their last known tips, not six), floored as now.
[inferred] On the 193 bare-quorum headers of run 1's worst five minutes this would have left a spare vote, so one late vote would no longer end the round one short.
It is not enough on its own: on 37 headers a seventh voter did answer `created` and the round was still lost (§4.2).
Its cost is an older named block, and how much older is not known: no bench 8 analysis computed the named block's age.
A second lever, tied to the same finding, is the round's end at the author's next header: on 223 of 230 cut-off headers the round ended with 6 votes counted.
[inferred] Letting a header that is one vote short stay open a little past the author's next header would let a late vote count, at a cost to the round rate that bench 8 cannot size.
§7.2 names the run that would test the first lever.

### 5.3 Execution capacity, or back-pressure, as the root (§4.4)

Suggestion: treat the drift of execution tips as the thing to fix.
[a timing fit] At about 57 % busy no validator fell more than 2 outputs behind and certification read 99.95 %; at about 97 % busy the tips drifted tens of outputs apart and the loss of §4.1 followed.
Two directions, both untried:
- more execution headroom at the same load: in run 2 persist took 345 to 388 ms per output against 400 to 443 ms of execute time (§3.7), so the store's write path is close to half the busy time, and §7.1 and §7.4 would say whether it is also what separates the laggards;
- back-pressure: keep consensus from running further ahead of a node's own execution than the floor can cover, for example by slowing batch acceptance or proposals while the node's execution backlog is past a bound.
[inferred] Back-pressure trades peak rate for certification; bench 8 measured neither the trade nor the bound.

### 5.4 The vote answer for a closed epoch (§4.5)

Suggestion, from the local issue draft: in the vote path, check the header's epoch against a closed epoch before the round trip to the certificate manager, or map the dropped reply in `identify_unknown_certificates`, and answer with the existing `InvalidEpoch`.
[inferred] The late proposer would then see an epoch answer instead of a fatal vote error from every voter.
This removes a misleading error; it would not by itself keep the late validator in the committee, which is §5.5.

### 5.5 The rejoin rule under load (§4.5)

Suggestion, from the same draft: the certificate rule of `behind_consensus` could measure lateness in outputs, as the header rule beside it does, rather than in the new epoch's rounds.
[measured] Under run 2's load two validators that were tens of outputs behind at a close were demoted at round 41 of the new epoch and were out about nine minutes each, coming back through the 20-round rejoin window.
[inferred] Each demotion left the fleet one spare voter short of a quorum of 7 for those minutes, which feeds the loss of §4.1.
§7.3 names what would measure the rejoin window's cost before choosing a rule.

### 5.6 What is the owner's decision, and what could go upstream

The upstream codebase is frozen before the mainnet launch, so nothing is posted.
For the owner to decide:
- whether bench 8 ends here, as the plan's rule says after run 3 ("stop"), or a run from §7 follows;
- whether the issue draft `tasks/issue-bodies/bench8-lagging-validator-at-epoch-boundary.md` is posted after review, and in which form: the draft itself proposes part 1 as a short issue and part 2 as a comment on #1806;
- whether a comment for #1870 with §4.6's measurements is drafted, locally and on the owner's word;
- which of 5.2 to 5.5, if any, is pursued, and whether before the launch or after it;
- whether any of bench 8 is published; nothing is now.

What could go upstream later, once the owner reviews it: the issue draft (5.4 and 5.5 are its suggestions) and the #1870 comment.
5.2 and 5.3 are not ready for upstream: they are untried, and the owner's rule is that a fix a bench run confirms goes upstream as unconditional behaviour, with switches kept to bench builds; neither has been benched.

## 6. Friction and harness

What cost fleet time or data in bench 8, what was fixed, and what to fix before the next run.
Sources are in `s6.sources.md`; none of this section is figure-checked except where a line says so.

### 6.1 The cloud login died 1.5 h into run 3

The login for run 3 was made at 13:59 and the run launched at 14:01.
It stopped working between 15:31:19 (the endpoint sampler's last round with 11 of 11 nodes) and 15:35:58 (the fleet watch's first failed listing), with "Reauthentication failed. cannot prompt during non-interactive execution".
The load blast ran on, because the generators run on their own machines; every driver step that needed a remote shell after 15:35 failed.
What that cost:
- no kill: the planned kill of validator-05 at 15:51:36 and all 13 later starts and restarts failed (rc 1), so run 3 has no kill and no rejoin to compare with runs 1 and 2;
- blast 2's collection failed (rc 1), so the manifest kept the driver's schedule for the load's phases, 85 s after the generators' own (§2.3);
- the harness wrote no certification window for the load blast (6.5);
- the endpoint samples stop at 15:31:19 (45 rounds), so nothing stands in for the Prometheus series validators 03 and 05 lack after that time;
- there was no fleet-ready check after the blasts;
- the fleet (22 instances at the dry teardown, the ten generators included) idled from about 16:10 to about 18:50, 2 h 40 min, until a new login at 18:39.

Prometheus was exported first, at 16:30:32, through the forward that was still open; then the collection (step 15) ran at 18:44 after the new login, then the teardown and the archive.
The lesson recorded on 2026-11-17 sets three rules: a token watcher beside the chain at every launch that reports the first failure; no reliance on a login's age, and a new login before the chaos step of any run whose login is more than an hour old; and when the token is dead with the fleet up, export metrics first, then log in, collect, tear down and archive.

### 6.2 The contracts path that went away

Run 3's teardown deleted every cloud resource and then stopped with rc 128 at its last local step, `git -C …/tn-contracts-devnet-relaunch worktree remove`.
That path no longer exists on this machine; the contracts repository is at `…/tn-contracts`.
A read-only pass showed no bench instance, disk, firewall rule, bucket or binding left.
A second teardown with `BENCH_CONTRACTS_SRC_DIR` set to the repository's present path (launch file `bench8-reduced-teardown2.env`) removed the run's contracts worktree and its `bench/r20261117-1401` branch and ended `TEARDOWN_DONE … deleted=0 left=0` at 19:03:06, rc 0.
Left as it was, the next deploy would have failed at the same default.
On the owner's instruction, commit 1db706d makes `benchmark/config.sh` default `BENCH_CONTRACTS_SRC_DIR` to `../tn-contracts`, updates step 11 of `benchmark/README.md`, and lists the change in `benchmark/tests/test_node_image.py` as a deliberate difference from the frozen bench 5 snapshot.
Fixed; nothing is left to do for the next run.

### 6.3 The metrics agent's lost batches, and what the endpoint sampler saved

In each run Prometheus lacks series because the metrics agent lost remote-write batches (tn-node-deployment #66); §2.4 has the list per run.
Bench 8 ran an endpoint sampler as a segment of the run chain: every node's own exporter text every 60 s, with a host block (the clock source and its offsets, the aggregate CPU line, `clk_tck`).
What it saved:
- run 1: the five series that stopped in Prometheus after the kill (validator-03 from 22:27:45, the observer from 22:36:15), covered by 97 rounds from 21:16:51 to 22:53:57;
- run 2: the series Prometheus never had for the whole run (vote-stage timing on validator-10, engine persist time on validators 03 and 10, the persist commit on validator-03), covered from 00:16:32 to the chain's end (2,520 files);
- run 3: only 14:47:09 to 15:31:19, because the sampler needed the same login.
`up` was also wrong at times: run 1's lacked validator-03 and the observer at the end while both were healthy, and in run 2 the idle check's `up` for the observer and validator-10 came through the sampler's fallback.
None of the three first looks used Prometheus or the samples as an input; their figures come from the node logs and the generators' results.

### 6.4 The harness gate's launch-caused failure, and its fix

The whole-suite harness gate before run 1 (2026-11-16, 18:44:40 to 19:33:09, 2,909 s, the host otherwise quiet) ran 1,640 tests and failed one: the SIGINT subtest of `test_keygen.SignalTests.test_a_signal_stops_every_node_job_and_its_gcloud` (rc 0, expected 130), in the suite and again alone.
The mutation checker passed its 555 cases.
The cause was the gate's launch, not the harness: the wrapper was started as a background job (`( setsid bash … & )`) from a non-interactive shell, and such a job inherits SIGINT and SIGQUIT as ignored (`SigIgn` 0x6 in the child, 0 without the `&`), which a shell cannot undo, so the test's SIGINT did nothing [measured on the host].
The wrapper `tasks/bench6/orch-harness-gate.sh` was fixed, and the failed module re-run alone with default signal dispositions passed: 30 tests in 30.9 s (19:51:06 to 19:51:38).
With the full run's other results, the gate was taken as passed.

### 6.5 Gaps in `analysis/certification.json`

The harness's own certification count (§3.8) has two kinds of gap.
In run 1 its `.nodes` gives no authority for validator-09, and that validator's prefiltered log has no `auth=` line; the run 1 first look took the authority from the `authority=` field of the whole log.
Run 2's first look took all ten authorities from `.nodes`; run 3's first look records one deviation in the authority mapping, which this section does not detail.
For run 3 the file has no window for the load blast at all, because the blast's rc was 1; its blast 1 mixed phase reads 99.94 %.
The first looks' own count over the same windows (§3.8) stands in for the missing run 3 figure.

### 6.6 The manifest's phases for run 3

The manifest's phases for run 3's load blast are the driver's schedule (preamble 15:23:49, warmup 15:25:19, mixed 15:27:19 to 16:07:19, cooldown to 16:10:19), not what the generators did (mixed 15:25:54 to 16:05:54).
In runs 1 and 2 the manifest's phases were corrected from the generators' results during the collection [inferred]; in run 3 the collection failed, so they never were.
Every run 3 window in §3 that starts at 15:27:19 carries that 85-s offset; Wgen is the generators' own phase, and the certification figures do not move between the two (§3.1).
The run facts first gave the driver's times as the load's mixed phase; the run 3 figure-check flagged that line, and the run facts now give the generators' times (§8.3).

### 6.7 Smaller records that disagree

- Run 1's manifest has `archive` and `log coverage` empty although the archive was verified (§2.5).
- The wait for the fleet-ready check is 535 s in run 1's manifest against 260 s in run 2's run facts, and 1,366 s (end reason `max_wait`) in run 2's manifest against 1,272 s in its run facts (§2.3).
- The local results directory holds 23 files more than the archive verify counts, in every run (§2.5).

### 6.8 One more item from the lessons

On 2026-11-17 a separate piece of work in the same working tree checked for bench processes and instances, found none and reported "no bench run in flight" while bench 8 had committed a minute earlier, had uncommitted edits in `benchmark/config.sh` and started a harness gate three minutes later; that gate calls the root drivers the other work was about to edit in place.
No run was lost to it.

### 6.9 What to fix before the next run

Fixed already:
- the contracts default (commit 1db706d);
- the harness gate's wrapper (signal dispositions).

Still open, each a suggestion unless a source says otherwise:
- run a token watcher beside every chain and take a new login before the chaos step of a run whose login is more than an hour old (the lesson's rules);
- when a blast's collection fails, take its phases from the generators' own results before any window is cut [suggestion];
- give the harness's certification count a window for a blast whose collection failed, and an authority for every validator [suggestion];
- keep the endpoint sampler, and make it independent of the cloud login if it can be [suggestion]; the lost batches themselves are tn-node-deployment #66;
- fill the manifest's `archive` and `log coverage` fields in every run, and record the fleet-ready wait one way [suggestion].

## 7. Open questions and what a next run could test

Each question names what is known, the measurement that would answer it, and whether the saved data of runs 1 to 3 can give it or a new run is needed.
Any run proposed here is one run per configuration unless it says otherwise.

### 7.1 Why some executors run slower at saturation

Known [measured]: at 0.959 to 0.984 busy, run 2's execution tips drifted up to 53 outputs apart, and which validators fell behind changed at the e3→e4 boundary (§4.1, §4.4).
Validator-10's persist time was 377 and 414 ms per output at 00:54 to 00:58 against 279 and 282 ms on validator-02 (§4.5).
In run 1, A-E5 did not extract the laggards' engine lines, so why 06 and 08 grew 20 to 31 outputs behind is open (its Q3 rows after 22:13 were not rechecked by its figure-check).
Before the runs, N4 found the laggards 2 to 8 % costlier per transaction in execute time and could not tell cause from effect (no-run findings §4).
Measurement, from saved data first: per validator and per minute, `execute_ms`, `persist_ms` and, where the line carries it, `cpu_ms` per output and per transaction (the `output executed` fields in `tasks/bench8/node-fields.md`; no bench 8 analysis read `cpu_ms`), set against that validator's distance behind, on both sides of each epoch boundary in runs 1 and 2.
If persist leads the lag, the next step is the disk's write count and sync time per output on those minutes, with the bytes beside them.
A new run is needed only if the logs cannot separate cause from effect.

### 7.2 Whether a floor at the ring's depth plus a margin removes the loss at full load

Known: floor 16 removed the loss in the first load epoch and not in the second, and moved part of it onto headers held by exactly six of the other nine (§4.2, §4.3).
The floor names a ring entry that many outputs back from the proposer's tip, or the oldest entry of a shorter ring (`tasks/bench8/node-fields.md`).
Measurement, a new run at full load (600 × 16, the kill in the same place): a node that names the newest block held by at least 7 of the other 9 by their last known tips, one voter above the bare quorum, floored at the ring's oldest entry.
Read the plan's two numbers over the window before the kill and per epoch segment, the share of headers at exactly six holders, and the named block's age in outputs, which no bench 8 analysis computed.
This needs a node change and a run; it tests the suggestion in §5.2.

### 7.3 The cost of the rejoin window

Known [measured, run 2]: two demotions at loaded closes, each about nine minutes out (8 min 35 s and 8 min 40 s), the handled round 30 to 80 rounds behind the newest until it came within the 20-round window; both catch-ups finished under load (§4.5).
Not known: whether main without the stack falls this far behind at a loaded close (not run under this load), and how much of run 2's loss the nine voters caused.
Measurement, from saved data: for each demotion, the minutes out, the round gap per minute, and the fleet's certified share and spare voters while the member was out, against the same epoch's minutes before it.
For the code path, the issue draft's test (not built): slow one validator with `TN_TEST_EXECUTION_DELAY_MS` so it reaches a close seconds late; its last header should draw an epoch answer, not a fatal vote error.

### 7.4 Why run 2's validator-10's persist time rose

Known: the rise from 00:54 to 00:58, before the close, is measured on its own `output executed` lines; Prometheus has no persist series for validator-10 in run 2 (§2.4).
Measurement, from saved data: its `persist_ms` and `cpu_ms` per output and per block from 00:50 to 01:04 against validator-02's, and its disk's operations and latency for the same minutes from whichever source of §2.4 covers them.
If nothing on the host explains it, the next run should log the store's size and the disk's write count per output on every validator.

### 7.5 The far validators' ingress at reduced load

Known [measured, run 3]: the generators for validators 02 and 06 landed 107.5 and 95.4 tx/s at a mixed-phase latency of 10.1 and 16.6 s (p50), and the two nodes built batches at 114.3 and 103.0 tx/s; the cause is not measured.
[inferred] A closed loop of 1,200 transactions in flight per generator at about 11 s per round trip comes to about 100 tx/s.
Measurement: where the 10 to 17 s go for a far generator's transactions (the generator's send to the RPC's accept, the node's pool admission, the wait for a batch), on one clock; and, as a control in a new run, one far generator pointed at a near validator's RPC.

### 7.6 Why the bare-quorum path is large at floor 16, and whether validator-02's distance adds to it

Known: on 223 of validator-02's 230 cut-off headers in run 1's b3 the round ended with 6 votes counted, though at least six voters held the block (§4.2); validator-02 is one of the two European validators (§4.6).
Measurement, from saved data: the `vote_arrivals` time per voter on validator-02's own clock for those headers (A-E5 did not compute it), and the share of headers at exactly six holders against seven or more, per floor, in runs 1 and 2.

### 7.7 Run 3's residual loss

Known [measured]: 31 lost headers at reduced load, all at k = 0, none under-held, labelled `error / held at proposal`, 27 of them on validators 02 and 06 (§4.4).
Measurement, from saved data: the round-end reason and each non-voter's answer for those 31 headers.

### 7.8 One run per configuration

Every comparison in this report rests on one run per configuration, and the epoch position of the load blast differs between runs (§2.3).
Run 2's certified share in its first 817 s (98.51 %) and 7a's (93.997 %) come from windows that sit in different epochs, so they do not give a run-to-run spread.
Measurement: a second full-load control run with the load blast placed at the same offset into its epoch as one of the existing runs, read over the same windows.

## 8. Appendix

### 8.1 Evidence index

One line per finding of §4.
P = `benchmark/private`; AF1, AF2, AF3 = `P/bench8-r20261116-2011/AF1`, `P/bench8-r20261116-2332/AF2`, `P/bench8-r20261117-1401/AF3`.
Each first look has its figure-check beside it (`figcheck.md`); the JSON named is where the figures are.

| § | finding | analysis | figure-check | JSON and keys |
|---|---|---|---|---|
| 4.1 | who loses headers and when | AF1, AF2 and AF3 `first-look.md` §1 and §2 (the prediction test) | each `figcheck.md`; AF2's checks the k ≤ 3 / k ≥ 4 split and the 0–2 / 3–8 / above 8 split exactly (lines 25, 34) | `af1-numbers.json`, `af2-numbers.json`, `af3-numbers.json`: `t1.<window>.authors`, `uh_lost`, `others_lost`, `rounds_k_ge4_pct`; `q2-<run>-<window>.json` (`fleet.certified_pct`, `fleet.lost`, `authors`); `q4u-<run>-<window>.json` (`fleet.under_held`, `under_held_pct`, `under_held_certified_pct`, `others_certified_pct`, `rounds_k_ge4_pct`); `pred-r1-Wprekill.json`, `pred-r2-Wprekill.json` (AF2), `pred-r3-W1679.json`, `pred-r3-Wmixed.json` (AF3): `minutes`, `per_header_by_k`, `per_header_by_author_distance`, `lost_by_author_distance_and_k`, `per_validator` |
| 4.2 | the second path in run 1 is the same root | `P/bench8-r20261116-2011/AE5/epoch5.md` | `AE5/figcheck.md` (about 215 checked, 10 wrong in 4 errors, 5 weak) | no JSON beside AE5 (its scripts are in `AE5/scripts/`); the counts it builds on: `af1-numbers.json` `t1["r1 Wprekill"]` (`uh_lost` 712, `others_lost` 496), `af2-numbers.json` `segments["r1 e5"]`, `q2-`/`q4u-r20261116-2011-We5.json` |
| 4.3 | what the floor does and does not do | AF1 §3 and §6, AF2 §4 and §5 | AF1 and AF2 `figcheck.md` | `af1-numbers.json` `distance.W817`, `distance.Wprekill` (`eq16_pct`, `gt8_pct`, `gt16_pct`); `xcheck-r20261116-2011.json` `floor_eq_named_pct`; `af2-numbers.json` `distance`, `segments["r1 e4"|"r1 e5"|"r2 e3"|"r2 e4"]`, `t1.<window>.basis_pct` |
| 4.4 | the root: executors at about 97 % busy drift apart, at about 57 % none falls behind | AF3 §1, §3, §4 and the engines paragraph; AF2 §2 | AF3 `figcheck.md` (busy share and the spread 0 / 1 / 2 outputs behind for 66,931 / 1,930 / 4 headers recomputed) | `AF3/rate-engine.json` `<run>.engines.NN.median_over_120s_buckets.busy_exec_persist`, `.max_busy_exec_persist`, `<run>.windows`; `pred-r3-W1679.json`, `pred-r3-Wmixed.json`, `pred-r2-Wprekill.json` `per_validator`, `minutes` |
| 4.5 | the lagging validator at an epoch close | `P/bench8-r20261116-2332/AV10/validator-10.md` (not figure-checked as a whole); AF2 §6.1; the local issue draft `tasks/issue-bodies/bench8-lagging-validator-at-epoch-boundary.md` | `tasks/issue-bodies/notes/bench8-lagging-validator-at-epoch-boundary.figcheck.md` (82 figures, 75 matched, 5 wrong, 2 not traceable); AF2 `figcheck.md` error 1 | `af2-numbers.json` `t1["r2 Wprekill"].authors.10` (2,830 headers), `buckets.b6`/`b7.r2.per_author.07`; no JSON beside AV10 |
| 4.6 | the far validators | see §4.6's sources | | |
| 4.7 | what did not happen | see §4.7's sources | | |

### 8.2 Definitions

Counting unit: a validator's own `header proposed` line; every certification figure counts headers, not rounds or certificates.
Certified: a proposed header that reached a quorum; certified % = (headers − lost) / headers.
Lost: a proposed header that never reached a quorum.
Under-held: at the proposal, the execution block the header named was held by at most 5 of the other voters.
k ≥ 4: the share of rounds in which four or more headers were under-held.
Distance named: the proposer's execution tip minus the block its header named, counted in block-bearing outputs.
Basis: which rule picked the named block, the floor, the block a quorum held, or the tip (`basis_pct` in the JSON).
At the floor: distance named equal to the floor's depth (16 in run 1, 8 elsewhere).
Distance behind the lead: a validator's own execution tip in block-bearing outputs against the lead, the highest latest tip in the fleet (q3's definition); n8 counts the validators whose median distance in a minute is above 8.
Busy share: the sum of execute and persist milliseconds per 120-s bucket divided by 120 s, as the median over 13 full buckets; busy (task) uses the task time of `output execution task finished` instead.
Bucket certification (bench 7's A2 definition): per author, `quorum reached` lines over `header proposed` lines in the bucket; it can read above 100.
The harness's count: the same ratio per validator over the whole mixed phase, kill included, from `analysis/certification.json`.
Rates: executed is validator-01's executed transactions per second; landed is the generators' own count; chain is the chain's rate as one generator's results read it.

Windows (all start at the load blast's mixed phase unless stated):
- W-817: the first 817 s, the length of 7a's window before its kill;
- W-prekill: from the start to the kill, 1,877 s in run 1 and 1,679 s in run 2;
- W-1679: the first 1,679 s of run 3, run 2's W-prekill length, as run 3 had no kill;
- W-mixed and B2: the whole mixed phase (run 3's W-mixed is the driver's schedule, 85 s late);
- Wgen: run 3's mixed phase by the generators' own results;
- W-e5: run 1's epoch 5 at 7a's offset into its epoch, 22:12:44 to 22:26:12;
- segments: a window cut at validator-01's epoch boundaries.

### 8.3 Corrections by the figure-checks that changed a statement to the owner

Each item changed a sentence in a file the owner reads (a first look, the run facts or the issue draft).
Whether a statement was also said to the owner live is not in these sources.

- AF1 E1: "7a's heaviest losers were 03, 06 and 08" was wrong; by lost headers in 7a's W-817 they were 06 (773), 08 (282), 04 (123) and 03 (59).
- AF1 W3: "so run 1's load blast began one epoch earlier" was too strong; blast 1 differed by 9 min 41 s (6:13 against 15:54) and the chain's age at the load by 17 min 41 s; the first look now says 18 min earlier, about 10 of them from blast 1, and calls the epoch alignment a timing fit.
- AF1 W4: the harness's own `rate_pct` fields read 95.6 and 98.1; the two-decimal 95.59 and 98.07 come from its counts.
- AF1 W1: in run 1's W-e5 validator-06 certified 99.95 % (1 lost), not 100.
- AF1 E2: a sentence on deficit answers ("Most deficit answers are refusals, which carry open=true by the field's definition") was flagged wrong; the replacement is in AF1's figure-check.
- AF2 error 1: run 2's §6.1 said validator-10's round-3276 header drew `Failed to return pending certificate manager result` from all nine voters, "216 error lines"; the 216 are failed vote requests between 01:03:43.3 and 01:04:06.7, of which 62 carry that message and 154 carry `Invalid epoch. Peer proposed epoch 3, but expected 4`.
- AF3 error 2: "its last 85 s carry no load" became "almost no load": generators 02 and 06 sent until 16:06:15, 10,334 transactions landed and validator-01 executed 28,893 in those 85 s.
- AF3 error 1: the generators' cooldown ended within 1 to 26 s, not 2 to 26.
- AF3's figure-check flagged the run facts' line giving the driver's 15:27:19 to 16:07:19 as the load's mixed phase; the run facts now give the generators' 15:25:54 to 16:05:54.
- AF3 W3: the plan's row was quoted with a paraphrase; it reads "under-held under 1 % and at least 99.0 % → the cause is the spread …" (plan line 115, as quoted in `tasks/bench8/no-run-findings.figcheck-B.md` line 81).
- AE5: four errors, among them "No lost header lacked a superseded answer" (its line 109) and "the five validators that lost nothing (01, 03, 06, 08, 09) are exactly the five that were behind" (its line 160), and the splits of validator-04's and validator-10's losses (lines 117 to 120); the replacements are in `AE5/figcheck.md`.
- The issue draft: 5 of 82 figures wrong; the switch list read as complete but the arm also set `digest_order_hold` and the three `epoch_record_*` switches; validator-07's 54 internal-error answers came from eight voters because validator-05 was down by plan at that close; and the earlier prediction (#1806) of a catch-up the node "cannot finish under load" did not hold here, as validator-10's finished under load (rejoined at 01:12:43).

### 8.4 What was not computed

- Run 1's achieved rate, and run 1's and 7a's engine busy share.
- Under-held after the kill and over the whole of B2 (runs 1 and 2); run 3 had no kill.
- The holders-at-cancel tables beyond q2's labels (all three runs).
- The per-voter vote-return times, and the named block's age (runs 2 and 3).
- Validator-05's voter-tip stand-in in run 1 (not needed before the kill); run 3 had no stale voter tip, so its stand-in variant was not needed.
- Why validators 06 and 07 fell up to 25 and 47 outputs behind in run 2's epoch 4.
- Why validator-10 fell behind and failed at run 2's epoch 3 to 4 boundary.
- Why validators 02 and 06 built few batches in run 3.
- The voters' deficit fields in run 3 (`xcheck_b8fields` not run).
- An interpretation of the floor/quorum basis split in run 3.
- Validator-02's certificate-failure log in run 1 (in the results, not read).
- Prometheus: not used as an input by any first look.
- The harness's certification count for run 3's load blast (no window, §6.5).

