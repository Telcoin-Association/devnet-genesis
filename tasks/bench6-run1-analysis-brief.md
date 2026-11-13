# Bench 6 — run 1 analysis brief (run r20261112-1520, the arms run)

Written by the orchestrator, its only writer, on 2026-11-12 after the walk.
Read `tasks/bench6-agent-rules.md` first (sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Investigations and analysis units", "HAND BACK"), then this file, then your own unit below.
The fleet is deleted: every input is local and nothing is fetched.

## 0. Paths

- Results: `benchmark/results/r20261112-1520/` (read-only; an archive upload may be reading it).
  - `manifest.json`: `param_arms[]` (each arm's name, begin, ready, end, switches, host steps, restart seconds), `blasts[]` (index, arm, kind, senders, window, real phases), `blast_runs[]`, `log_rate[]`, `commit_stalls[]`.
  - `blast-<i>-<UTC>/blasters/bench-blaster-NN.json` and the generator logs of blast `i` (the folder's time is when it was archived, not when the blast ran).
  - `logs/`: node logs, pulled at the teardown (layout below); `persist/<node>.csv` and `<node>.folios.txt` (header: `benchmark/tools/persist-csv-header.txt`); `metrics.json` (Cloud Monitoring); `analysis/` (the harness's own `cert-rate.md`, `block-rate.md`, `certification.json`, and `arms.md` once the arm summary has run).
  - `blasters/` and `funder/` at the top level belong to blast 15 (the last blast is not moved into a `blast-15-*` folder).
  - `logs/run-arms-arms-*.log`: the walk's own record (kind and attempt per index, the two stops and their resume lines).
- Node log layout in `logs/` (a trap: read this before you grep):
  - `bench-validator-NN-unit-stdout.log.gz` is the WHOLE node log of the run (15:21:56Z to 23:35:31Z, about 4 GB plain, 540 MB gzipped, one line per event: `ts=… level=… target=… message="…" key=value …`). Use it for anything inside a blast.
  - `bench-validator-NN-telcoin-pre-arm-<arm>-<UTC>.log.gz` is only the last 12-18 minutes BEFORE the apply of `<arm>` (so it shows the arm before it), and `…-telcoin.log.gz` the last 12 minutes before the teardown. They do not cover the blasts.
  - `…-telcoin-cert-fail-<UTC>.log.gz`, `…-recovery-*.tgz`, `.logspan`, `.pulled`: the teardown's own snapshots and records.
- Prefiltered node logs: `benchmark/work/prefilter/r20261112-1520/logs/` with the same file names; `…-unit-stdout.log.gz` there is about 100 MB per validator and keeps only the lines the harness readers match (`vote path timing`, `certificate committed`, `next block executed`, `header proposed`, `quorum reached`, `output queued`, `output executed`, `persisted output`, `output saved`, `subdag committed`, `batch built / sealed / reported`, `signers recovered`, `consensus output ready`, `parent grace armed / ended`, `header uncertified`, `scheduled leader`). Start there; go to the full log only for lines it lacks (warn and error templates, `node switches`, `vote refused`).
- One pass over a full log costs about half a minute of CPU per node: extract once into your scratch with one `zcat | grep -F -e … -e …`, at most four nodes at a time, then work on the extract.
- Node metrics exported from the run's Prometheus before the teardown: `benchmark/private/bench6-r20261112-1520/prom-export/<metric>.json.gz` (the body of `query_range`, step 15 s, 15:40Z to the export time; `INDEX.tsv` lists series and points per metric).
  Labels: `node` (bench-validator-01 … -10, bench-observer-11), `region`; a counter resets at every node restart (one per arm), so take rates inside one arm only.
- Orchestrator's preliminary reads (not results): `tasks/bench6/r20261112-1520/prelim-prom-read.txt`, and the run log `tasks/checkpoint-bench6-run1.md` (gitignored, read-only).
- Templates: the bench-5 units' scripts and outputs under `benchmark/private/bench5-r20261107-1504/{A1,A2,A3,A4n,A4o,A6}/`, the bench-5 brief `tasks/bench5-analysis-brief.md`, the bench-5 report `tasks/bench5-report-r20261107-1504.md`.
- Design: `benchmark/private/bench6-prep/design/design-harness--arms-and-runs.md` §4 (run-1 schedule, "What each arm must record", "Drift control") and §5 (run 2's acceptance); `…/design-node-fixes-for-bench-6.md` §A (the twelve switches) and your topic's part of §B.
- Tools: `benchmark/tools/{arms-summary,cert-rate,block-rate,stage-latency,folio-census}.py`; the generator's `bench/kpis.py` and `bench/aggregate.py` in `/home/drtnarg/coding/telcoin/tn-transaction-generator`.
- Your output directory: `benchmark/private/bench6-r20261112-1520/<unit>/`. Your checkpoint: `tasks/checkpoint-bench6-r1-<unit>.md`.
- Scratch: `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/r1-<unit>/` (nothing over 200 MB); bigger extracts under `benchmark/work/bench6-scratch/r1-<unit>/`.
- Node logs are several GB each. Never read one with the Read tool: write a script, `grep` or `zcat | grep` into your scratch, and read the extract.

## 1. Run facts (cite, do not re-derive)

- Node image `adiri@sha256:874537ff…852745` built from `bench/bench6-2026-11` = 2df831e3c (base 165e3fe01 + 98 commits), sub-second timestamps from genesis; generator 62bbd5f.
- Fleet: ten validators and one observer, `c3-highcpu-8` (16 GiB RAM), one 100 GB Hyperdisk Balanced per node (20,000 IOPS, 800 MiB/s) holding the root and the data directory; bench 5's ten zones; epoch 1,200 s.
- Deploy 15:09:21Z to 15:59:55Z, 10 of 10 CvvActive, HOST_PROBE uniform (`read_ahead_kb` 128), fsync probe median 1,041 µs.
- The walk: 16:01:16Z to 22:53:12Z in four segments, nine arms, sixteen blasts (indices 0-15), every fund and run rc 0, no blast retried, `commit_stalls` empty, vote timeouts 0.
- Two stops, both in an apply, both resumed within a minute with the walk's own resume line (the arm was re-applied to all eleven nodes under a new recorded name):
  - 18:30:12Z, arm 3: an IAP ssh fault (exit 255) before validator-07 was touched. For about four minutes the observer and validators 01-06 ran `v-vote-floor` and 07-10 still `v-vote`. Recorded arms `v-vote-floor` (failed, no blast) and `v-vote-floor-r2`.
  - 19:17:45Z, arm 4: validator-08's eviction left 8 of 565,013 pages resident and the strict check failed the apply. The observer and validators 01-08 ran `pool-local`, 09-10 still `v-vote-floor`, for about one minute. Recorded arms `pool-local` (failed, no blast) and `pool-local-r2`.
- Step 15 (collect) 22:54:37Z to 22:59:53Z rc 0; teardown 23:35:15Z to 23:59:30Z rc 0, `deleted=12 left=0`; the results directory holds 2,896 files, 8.5 GB.
- The teardown's certification check names three validators below 90 % own-header certification: validator-08 27.1 % and validator-09 53.0 % in blast 15's mixed phase, validator-10 47.5 % in blast 8's warmup, with further windows listed in `manifest.cert_failures[]` (blast 2 and 3 warmups, blast 7 and 8 warmups, blast 8 mixed, blast 9 warmup, all of blast 15).
- The walk's own health check after each step read no node (`verdict=unknown read=0/11`, a parser defect); a separate reader showed 11 of 11 nodes, root disk at most 31 %, `fatal_db` 0 throughout.

Arms in run order (switches are cumulative; `on` lists what differs from the control):

| k | recorded arm | on (beside the arm before it) | host step | blasts (index kind) |
|---|---|---|---|---|
| 0 | `a0-control` | nothing (fresh fleet, restarted once by the apply, never evicted) | none | 0 L, 1 M4, 2 M16 |
| 1 | `p1-mdbx-advice` | `mdbx_random_advice` | evict | 3 M16 |
| 2 | `v-vote` | `quorum_exec_block` with `quorum_exec_block_starved_rounds=4`, `vote_queue_fix`, `epoch_record_state_check` | evict | 4 L, 5 M16 |
| 3 | `v-vote-floor-r2` | as `v-vote` with `quorum_exec_block_starved_rounds=0` (always on) | evict | 6 L, 7 M16 |
| 4 | `pool-local-r2` | back to starved rounds 4; `sealed_tx_keep`, `digest_dedupe`, `recovery_threads=3`, `epoch_close_task_drain` | evict | 8 M16@epoch |
| 5 | `pipe` | `pipelined_persist` | evict | 9 M4, 10 M16 |
| 6 | `bound` | `rpc_admission_backlog_outputs=3` | evict | 11 M4, 12 M16 |
| 7 | `gr150` | `parent_grace=150ms` | evict | idle mark, 13 L, 14 M16s |
| 8 | `a0-prime` | nothing: every switch back at its default | evict | 15 M16 |

Blast types: L = 8 senders per blaster at window 16; M4 = 600 × 4; M16 = 600 × 16 with 120 / 480 / 180 s and a 180 s tail scan; M16s = 120 / 300 / 180 s without the tail scan.
The real phase times are in `manifest.blasts[].phases`; use the mixed phase, and say which part of it you used.

## 2. What is already known, and what confounds the arms

These are the orchestrator's preliminary reads (Prometheus and one validator's persist CSV).
Verify them; do not cite them as results.

- **Throughput fell through the run, and the closing control ran at half the opening one**: M16 medians 5,809 tx/s (`a0-control`) and 2,911 tx/s (`a0-prime`), engine busy near 1,000 ms/s in every M16.
- **Cold cache.** Every arm from `p1` on starts from an evicted page cache (`host evict-mdbx`, by design), and after it the node reads the database back from the Hyperdisk one 4 KiB page per major fault.
  On validator-03, disk reads and major faults per second in the mixed phase: `a0-control` M16 0 and 8; `p1` 24; `v-vote` M16 23; floor M16 80; `pool-local-r2` 184; `pipe` M4 532 and M16 20; `bound` M4 808 and M16 339; `gr150` L 555 and M16s 376; `a0-prime` 801.
  The database grew from 1.7 GiB used (end of index 2) to 7.0 GiB (end of index 15); the resident part after `a0-prime`'s M16 was 3.4 GiB.
  So `a0-prime` against `a0-control` mixes the database's age with the cold cache, and the first blast after an apply is colder than the second.
- **The design's drift rule applies**: commit time per transaction moved far more than 15 % between the two controls, so only adjacent arms are compared, and even adjacent arms differ in fault rate.
  Report the fault rate and the read latency beside every per-arm figure that depends on the engine or the persist.
- **No whole-block writes anywhere**: writes of about 5 KB each and `thp_file_alloc` 0 on validator-03 in every blast, the opening control included. Bench 5's write amplification did not occur on this deployment.
- **Output size moved**: transactions per output 4,779 (control M16), 3,512 (`p1`), 3,259 (`v-vote`), 2,781 (floor), 4,530 (`pool-local-r2`), 2,297 (`pipe`), 3,033 (`bound`), 3,735 (`gr150`), 3,695 (`a0-prime`).
  A per-output time is not comparable across arms without it.
- **`pipe` M16 is the slowest M16 although it ran warm** (27 faults/s): persist cycle 0.83 s, commit 0.72 s, against 0.36 s commit in the arm before it.
- **Refused-behind votes** over the mixed phase, summed over validators: control 1,181, `p1` 300, `v-vote` 113, floor 0, `pool-local-r2` 1,724 (an epoch boundary lies in it), `pipe` 0, `bound` 0, `gr150` 0, `a0-prime` 3,679.
- A calibration arm (the control switches again without the eviction) was prepared and not run; there is no warm control at the final database size.

## 3. Reading rules (the user's, from the handoff and the design)

- Judge the storage arms on commit time and throughput, with write count, sync count and write size beside any byte ratio.
- Read `p1` against the controls with the cache state named; label an arm by what the node measured (`tn_reth_mdbx_random_advice_bytes`, `keeps_sealed=true`, `pool=dedicated`, the `node switches` line of each start), not by the arm file.
- The admission-bound arm: landed tx/s and refusals and drops, together.
- The grace arm: far-validator certification against round time.
- An arm that shows the final-state halt line is a failed arm: say so first.
- Every number cites its file and the line, query or script that produced it. Say plainly what could not be measured. A timing fit is not a mechanism.
- No recommendation for run 2 without the measured basis next to it.

## 4. Units

Wave 1 runs in parallel; each unit writes only under its own output directory.

### r1-A1 — generator KPIs per blast
Inputs: `blast-<i>-*/blasters/*.json` and the generator logs, `manifest.blasts[]`; templates bench-5 `A1/`.
For each of the sixteen blasts: landed tx/s over the mixed phase, sent and landed counts, `seen` and `land` p50 / p95 / p99, errors by code, resends by cause, nonce skips, duplicates, landings at or past 300 s, still unlanded after the tail scan (M16 only), any generator silent for more than 30 s, per-sender time blocked at the window.
The floor KPIs for the four L blasts; the M4 blasts as the Little's-law point.
For `bound` and `gr150`: what the generators saw of the admission bound (refusal codes, retries, time blocked) beside landed tx/s.
Outputs: `kpis.json`, `kpis.md` (one row per blast, arm named), `pool-fields.md` (the POOL fields), `bound-fields.md`.

### r1-A2 — certification and the vote path
Inputs: node logs (prefiltered first), `analysis/` cert-rate output, prom-export `tn_primary_*`; template bench-5 `A2/`.
Per blast window and per validator: own-header certification share, `outcome=behind` per header, votes refused (inactive, execution behind), vote timeouts, `lock_ms` p95, exec lag in rounds, headers proposed per second by reason, parents per header, leader share, the grace's `expired` count.
The two vote forms side by side (adaptive, always-on) at L and at M16, with the control and `a0-prime` as the brackets.
`gr150`: validators 02 and 06 (the far ones in bench 5; confirm from this run which are far) committed share at idle and at L, against round time.
Outputs: `numbers.json`, `certification.md`, `vote-forms.md`, `grace.md`.

### r1-A3 — restarts, the loaded boundary, and the log census
Inputs: node logs, `param_arms[]` (restart seconds, guard), the walk's record; template bench-5 `A3/`.
The eleven applies: per node restart gap, time to CvvActive, mode transitions, rejoin episodes, anything refused by the guard; the two mixed-fleet intervals at the stops (did the chain or the votes show them).
The epoch boundary inside `pool-local-r2`'s M16 (index 8): boundary wait, task-tracker errors, `epoch record quorum` lines, S10 and S11 on the slow nodes; the other boundaries of the run as the comparison.
Warn and error template census per arm (new templates against bench 5's census), any `FatalDBFailure`, any final-state halt line, any `unexpected execution result`.
Outputs: `restarts.md`, `boundary.md`, `census.json`, `census.md`.

### r1-A4e — execution
Inputs: node logs (`output executed` lines), prom-export `tn_engine_*`, `tn_executor_*`, `tn_node_*`; template bench-5 `A4n/`.
Per blast and per validator, in matched transactions-per-output bins: recover / evm / root / finish / other in µs per transaction, queue and forward wait, engine busy, channel depth, backlog outputs.
`pool-local-r2`: the recovery pool (`pool=dedicated`), sealed-transaction keeps, digest dedupe counts, skipped and repacked transactions.
`pipe`, `bound`, `gr150`: the engine task against max(execute, persist), `persist_wait`, unpersisted outputs, where the engine's second goes when the persist overlaps the next output.
State what bounds the engine in each M16 (execute, persist, waiting on the persist, input).
Outputs: `execute.json`, `execute.md`, `pipelined.md`.

### r1-A4p — persist, disk and cache
Inputs: `persist/<node>.csv` and `.folios.txt` for all eleven nodes, node logs (`persisted output` lines), prom-export `tn_reth_*`, `tn_engine_persist_*`, `reth_db_*`, `param_arms[].host` (resident pages before and after each eviction); template bench-5 `A4n/` and `I-B2/`.
Per blast and per node: save_blocks, markers and commit time per output and per transaction; pages newly allocated and copied; device bytes, write count, mean write size, sync count; amplification as device bytes over (newly + cow) × 4096 with the counts beside it; disk reads, major faults, read latency (read ticks over read count); MemAvailable, Cached, the resident part of `mdbx.dat` against its used size; the advised range against the used size; `thp_file_alloc` and the folio census.
Then the question the controls leave open: how much of the fall from `a0-control` to `a0-prime` is the cold cache and how much the database's size.
Charge each blast its faults (faults per second × measured read latency = time blocked) and show what is left; say how far the data supports that split and where it does not.
Did `p1` change anything measurable on this deployment (no amplification existed to remove), and what does the advice cost when the cache is cold (no read-ahead)?
Outputs: `persist.json`, `persist.md`, `cache.md`, `drift.md`.

### r1-A6 — land-path stages
Inputs: node logs, the generator's landings samples; `benchmark/tools/stage-latency.py`; template bench-5 `A6/`.
Per blast window: stage p50 and p95 (S0-S13) and the three sums (`ts`, `commit`, `seen`) with the sanity check; one node first, then all ten.
Which stage moved in each arm against the arm before it (the vote forms at L, `pipe` and `bound` at M4 and M16, `gr150` at L).
Outputs: `stages-<index>.json`, `stages.md`.

### r1-A4o — operations
Inputs: `tasks/bench6/r20261112-1520/*.log`, `tasks/checkpoint-bench6-run1.md`, `logs/deploy-*.log`, `logs/run-arms-*.log`, the teardown log; template bench-5 `A4o/`.
Timeline against the plan (deploy, each arm, the stops, collect, teardown); faults (IAP, eviction residue, the blind health check); harness defects with the file and line; what run 2 needs fixed before it starts, in order.
Outputs: `timeline.md`, `faults.md`, `defects.md`, `recommendations.md`.

### r1-A7 — arm verdicts (wave 2, after every wave-1 unit)
Inputs: the wave-1 outputs only.
One table: per arm, each field the design's §4 table names for it, the measured value, the comparison arm, the cache state of both, and a verdict (confirmed, regressed, inconclusive with the reason).
Then the options for run 2's `final.arm`, each with what run 1 does and does not support, and the list of candidate systemic findings with their evidence (the pipelined commit, the cold cache after an eviction, output size against the vote fix, anything new).
Outputs: `verdicts.md`, `final-arm-options.md`, `candidates.md`.

## 5. Hand back

Status and checkpoint path; the output files; the five numbers that matter most with their cites; what you could not measure; what you would ask the orchestrator to decide.
A summary, never file contents.
