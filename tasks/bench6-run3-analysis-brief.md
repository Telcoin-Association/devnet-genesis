# Bench 6 — run 3 and run 3b analysis brief (the adaptive vote form against the always-on form)

Written by the orchestrator of runs 3 and 3b, its only writer, on 2026-11-13.
Read `tasks/bench6-agent-rules.md` first (sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Investigations and analysis units", "HAND BACK"), then this file, then your own unit in §4.
Where this file and the rules file differ (the scratch path, the budget), this file wins.
The fleets are deleted when you work: every input is local and nothing is fetched.

## 0. The question, the four runs and their paths

The user's question (2026-11-13): "I'm not sure about the always-on form vs the adaptive - I want to run another bench with the adaptive form to fully compare these two".
The two forms of the vote fix (`quorum_exec_block`), node code `telcoin-network-b6` at 2df831e3c, `crates/consensus/primary/src/proposer.rs`:
- always-on (`quorum_exec_block_starved_rounds 0`): every header names the quorum value, in practice its author's own tip minus 8 executed outputs (the floor);
- adaptive (`quorum_exec_block_starved_rounds 4`): a header names its author's own tip until an own header is cancelled, then the quorum rule for a window of rounds that doubles up to 128.

| | always-on | adaptive (the new runs) |
|---|---|---|
| 20,000 IOPS (bench 5's disk) | run 2 `r20261113-1351` | run 3 `r20261113-2118` |
| 50,000 IOPS | run 2b `r20261113-1630` | run 3b `<filled in when it has run>` |

Everything else is identical between a run and its twin: image `adiri@sha256:874537ff…` (2df831e3c), generator 62bbd5f, bench 5's ten zones, `c3-highcpu-8`, epoch 1,200 s, the same three blasts and chaos plan, `vote_queue_fix`, `epoch_record_state_check` and `mdbx_random_advice` on.
The only difference is the arm file: `benchmark/arms/final.arm` (runs 2, 2b) against `tasks/bench6/arms/final-adaptive.arm` (runs 3, 3b).

For a run `<R>`:
- Results: `benchmark/results/<R>/` (read-only; layout as in `tasks/bench6-run2-analysis-brief.md` §0, including the node-log trap it points to).
- Prefiltered logs: `benchmark/work/prefilter/<R>/logs/`.
- Node metrics exported before the teardown: `benchmark/private/bench6-<R>/prom-export/` (`INDEX.tsv`; step 15 s; counters reset at a node's restart).
- The always-on twins' analysis, which is your model and your comparison column: `benchmark/private/bench6-r20261113-1351/<unit>/` (both run 2 and run 2b are in that one directory), its scripts under `<unit>/scripts/` (A1: the `.py` files beside its outputs), each unit's hand-back in `tasks/checkpoint-bench6-r2-<unit>.md`, and `benchmark/private/bench6-r20261113-1351/cross-unit-notes.md` (read it in full first: 44 lines).
- Your output directory: `benchmark/private/bench6-r20261113-2118/<unit>/` (one directory per unit for run 3 and run 3b; name every table's run). Copy the twin unit's scripts into your own `scripts/` and change the copies; never edit a file under `bench6-r20261113-1351/`.
- Your checkpoint: `tasks/checkpoint-bench6-r3-<unit>.md`.
- Scratch: `/var/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/b809dfe1-0989-4cf2-83c7-25d4b75a1901/scratchpad/r3-<unit>/` (nothing over 200 MB); bigger extracts under `benchmark/work/bench6-scratch/r3-<unit>/<R>/`. The twin units' extracts under `benchmark/work/bench6-scratch/r2-<unit>/` may be read, never written.
- Never open a node log with the Read tool: one `zcat | grep -F` pass per node into your scratch, at most four nodes at a time.
- Budget: under 200k tokens. At about 160k finish the current section, checkpoint, and hand back with the exact resume point.
- Another session is working in this repository on other bench-6 units (E-3, E-4, ST-E). Do not touch `tasks/checkpoint-bench6-orch.md`, their checkpoints or their output directories.

## 1. Run facts (cite, do not re-derive)

Run 3, `r20261113-2118` (the orchestrator fills this section before a unit starts; if a line is missing, take it from `benchmark/results/r20261113-2118/manifest.json` and say so):
- A first deployment (`r20261113-2044`) stopped in step 7, before the coordinated start and before the arm was applied (validator-08's first start: "Address already in use" on its worker listener, udp 49594); it was torn down and is not part of the run.
- Deploy 21:18:25Z to 22:02:14Z; `final-adaptive` applied at step 7 through the pre-start config (`param_arms[0]`, sha256 77a3dfaa…), ready 21:38:28Z: `quorum_exec_block` on with `quorum_exec_block_starved_rounds` 4 (the adaptive form), `vote_queue_fix`, `epoch_record_state_check`, `mdbx_random_advice` on; every other switch at its default; no host step. Coordinated start 11 of 11, spread 0 s. Ten validators CvvActive. Read on the bench Prometheus in the idle window: starved rounds = 4 on all eleven nodes.
- Node disks: Hyperdisk Balanced 100 GB, 20,000 provisioned IOPS, 800 MiB/s (`manifest.node_disk`).
- Fsync probe median 1,043 µs; validators 04 and 07 flagged slow (run 2: 04 and 05).
- Blasts: 0 light 8 × 16 (mixed 22:12:55-22:19:56Z); 1 light 600 × 4 (mixed 22:25:37-22:33:06Z); 2 load 600 × 16 with the chaos plan (mixed 22:45:46-23:25:56Z, 2,400 s planned). Take every other phase time from `manifest.blasts[].phases` and the `blast-<n>-*/manifest.json` copies.
- Chaos in blast 2: epoch 4 opened 22:49:58Z; validator-05 killed 23:08:59Z, started 23:13:59Z; the outage crossed an epoch boundary (epoch 5 opened 23:09:58Z); observer restarted 23:18:59Z. Every validator was CvvActive again before the collect (waited 0 s).
- All ten generators `BENCH_BLAST_DONE rc=0` in each blast (blast 2 at 23:30:09Z); blast segment rc 0 at 23:39:27Z. Log rate of validator-01 in blast 2: 14.8 MB per minute.
- Teardown rc 0 at 23:52:55Z, `TEARDOWN_DONE deleted=12 left=0`, the devnet untouched; reindex: 648 files, 2.48 GB. The teardown's certification check: no validator below 90 % of its own headers in any window it was judged in (the lowest per validator: 02 96.6 %, 07 and 10 96.8 %, 06, 08 and 09 97.1 %, all in blast 2's warmup; 01 98.0 % in blast 2's preamble; 03, 04, 05 at least 99.5 %).
- The teardown's warning "node startup provenance mismatch" is the known one of runs 2 and 2b: each node's first start, alone, during staging (21:30-21:36Z), ran before the arm was applied and shows the switches off; the coordinated start at 21:38Z and every later start carry the arm. Not a finding; do not count the staging starts as run starts.
- Orchestrator's preliminary read (Prometheus, verify; `tasks/bench6/r20261113-2118/prelim-prom-read.txt`): blast 2 executed 4,634 / 5,374 / 5,380 tx/s (min / median / max over validators; the minimum is the killed one), 4,044 transactions per output, persist 0.380 s per output (commit 0.290, save 0.084), refused-behind votes 10 over the fleet (5 on one validator), vote timeouts 0; blast 1 5,506 tx/s with 4 refused-behind votes (run 2: 6,224 tx/s); blast 0 643 tx/s (run 2: 700).
- During the second light blast every node's prefault writes ran at 1.18-1.20 times its newly allocated pages over five minutes (run 2: 1.16-1.19), so the write-pattern advice held.

Run 3b: RUN3B_FACTS_PENDING

The twins' facts: `tasks/bench6-run2-analysis-brief.md` §1.

## 2. What the comparison must answer

Per disk, always-on against adaptive, the same rows in the same definitions as the twin unit used:
1. Throughput by bench 5's definition and its five-minute buckets; seen p50, p95 and mean; the floor latency.
2. Own-header certification per validator per window; refused-behind votes; `superseded` answers; `lock_ms`; execution lag per node; round time.
3. Per header: which basis named the block (own tip, quorum value, floor), how many voters held it by the author's next header, and for the adaptive form how often and how long each proposer sat inside its starved window. This is the heart of the comparison.
4. The engine's split per transaction, device writes against the provisioned limit, and what binds.
5. Epoch closes and the kill of validator-05: signers per close, one hash and one closing block, the recovery time.

What the earlier runs lead one to expect, to be TESTED, not assumed:
- at 20,000 IOPS both forms hold (run 1's arms: adaptive 98.5 % with 126 refusals at full load; always-on 99.9 % with 0);
- at 50,000 IOPS the adaptive form names the own tip until starved and then behaves like the floor-8 rule inside its window, so it may lose as much as the always-on form or more (`benchmark/private/bench6-r20261113-1351/I-10/findings.md` §4, the "own tip" row: 2.7 % for validator-06).
If a result contradicts an expectation, say so in the first line of your hand-back.

## 3. Reading rules

The rules of runs 1 and 2 hold (`tasks/bench6-run1-analysis-brief.md` §3, `tasks/bench6-run2-analysis-brief.md` §3): a figure names its window and its denominator; one node is not the fleet (write "validator-NN"); a fit is not a mechanism; write count, sync count, write size and commit time beside any byte ratio; say plainly what could not be measured.
Every figure of blast 2 says whether its window includes the outage of validator-05 and whether validator-05 is in the median.
A comparison cell is only filled when both runs' figures come from the same script and the same window definition; rerun the twin's figure with your copy of the script if you changed anything that could move it, and say whether it reproduced.
Two runs are one sample each: give the difference, and beside it the spread the twin shows between its own windows or nodes, so that a reader can tell a difference from noise.

## 4. Units

Each unit works on ONE run per pass: the run its launch prompt names.
A second pass (a fresh agent, the same unit, the other run) reads the first pass's checkpoint, reuses its scripts and adds the run to the same output files.

- **r3-A1** generator KPIs. Model: `bench6-r20261113-1351/A1/` (`blast_kpis.py`, `render_md.py`, `kpis.md`). Per blast: landed tx/s by bench 5's definition, the five-minute buckets of blast 2, seen and land p50 / p95 / mean, the floor KPIs, the figure without generator 05, `late_secs`, `still_short`, landings at or past 300 s, unlanded. Outputs `kpis.json`, `kpis.md`, and `vs-always-on.md` (the run beside its twin, row by row).
- **r3-A2** certification and votes. Model: `bench6-r20261113-1351/A2/` (scripts `*_r2.py`, `certification.md`, `numbers.json`). FIRST produce the event extracts (`parse`, `blockmap`) into `benchmark/work/bench6-scratch/r3-A2/<R>/` and record that in your checkpoint as section `S2 extracts DONE` with the path: unit r3-I10 waits for them. Then per window and validator: own-header certification, refused-behind votes, `superseded` answers by voter, `lock_ms`, `prelock_wait_ms`, execution lag, round time, the first two minutes of each blast, the windows around the kill and the rejoin. Outputs `numbers.json`, `certification.md`, and `vs-always-on.md`.
- **r3-I10** per-header basis (the heart). Model: `bench6-r20261113-1351/I-10/` (`findings.md`, `scripts/perheader.py`, `q2.py`, `q2d.py`, `q4.py`; they take a run and a window). Skills first: `tn-rust-skills`, `tn-domain-consensus`. Read the adaptive form's code path (`proposer.rs`, grep `starved`, `choose_exec_block`, `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`; and what the `header proposed` line logs about the basis and the window) while r3-A2's extracts are being made; wait for them with a background until-loop on r3-A2's checkpoint (deadline 45 minutes; if they are not there, hand back). Then, on blast 2's mixed phase before the kill (and, if the budget allows, after validator-05's start): per author, the share of headers named by own tip, quorum value and floor; the own tip minus the named block in outputs; how many of the nine other voters held the named block by the author's next header; certification by holder count; how often each proposer entered its starved window, how long it stayed, what share of its headers were proposed inside it, and what certification was inside against outside; which voters did not vote on lost headers and why. Run the same scripts on the always-on twin for the same window where I-10 did not already (run 2's pre-kill window exists as `q2-r20261113-1351-prekill.json`). Then the arithmetic of I-10 §4 on this run's data: what the always-on form with floor 8, 16 and 32 would have named and certified here. Output `findings.md` (the answer first, in five lines; each statement marked measured, read from code or inferred) and `scripts/`. Write the full findings text ALSO to `tasks/checkpoint-bench6-r3-I10-findings-<R>.md` as you go; if the Write of `findings.md` is refused, do not work around it: the orchestrator copies it from there.
- **r3-A3a** closes and the kill. Model: `bench6-r20261113-1351/A3a/` (`closes.md`, `recovery.md`, `scripts/`) and `bench6-r20261113-1351/E-1/scripts/` (the epoch-record readers; they take a run's extracts). Every epoch close of the run: commit gap, signers, one record hash and one closing block on all eleven nodes, which path gave each node its certificate (own vote round, collector, startup sync; unit E-4's method is in `bench6-r20261113-1351/E-4/`, read its findings' method section only), the state check's lines. The kill: validator-05 from kill to CvvActive, the rejoin episodes, the records it missed signing and whether it holds them. The observer's restart. Also the fatal census in one pass per node (halt, fork, `unexpected execution result received`, fatal database text, panic): counts per node, zero stated as zero. Outputs `closes.md`, `recovery.md`, and `vs-always-on.md`.
- **r3-A4e** the engine. Model: `bench6-r20261113-1351/A4e/` (`engine.md`, `engine.json`, `scripts/`). Per blast and, for blast 2, per five-minute bucket and per validator: the split per transaction (recover, evm, root, finish, save, commit, wait), busy, queue, transactions per output, each engine's executed rate against its input and its backlog; the execution spread across validators over time (the quantity the vote forms react to); what binds the run. Outputs `engine.md`, `engine.json`, and `vs-always-on.md`.
- **r3-A4p** the disk, narrow. Model: `bench6-r20261113-1351/A4p/` (`disk.md`, `scripts/wiops_minutes.py`, `prom_windows.py`, `disk_tables.py`, `prefault_by_process.py`, `folios.py`); no model check and no extrapolation. Per blast and per minute of blast 2: device writes per second against the provisioned limit, writes per transaction, write size, sync count, amplification (device bytes over page bytes), prefault against growth per process, the largest folio order, database size at the end. Outputs `disk.md`, `disk.json`, and `vs-always-on.md`.

Wave 2, after both runs' passes:
- **r3-A7** the comparison: per disk, always-on against adaptive, the rows of §2, from the unit outputs only; then the draft of the report's addendum (a new section for `tasks/bench6-report-r20261113-1351.md`; the orchestrator inserts it). Outputs `comparison.md`, `addendum-draft.md`.

## 5. Hand back

At most 30 lines: status and checkpoint path; the output files; the five numbers that matter most for the comparison, each beside its always-on twin, with cites; whether the twin's figures reproduced with your script copies; what you could not measure; what you would ask the orchestrator to decide.
A summary, never file contents.
