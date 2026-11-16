# A-E5 — bench 8 run 1: what happened in epoch 5 (22:07:21 to 22:27:31Z), validator-02 first

Read `tasks/bench8-agent-rules.md` (the budget; "Analysis units"), `tasks/bench7/briefs/a-common.md` §2 to §9 (where a run is, how the logs are laid out), `tasks/bench8/r20261116-2011/run-facts.md`, then the first look `benchmark/private/bench8-r20261116-2011/AF1/first-look.md` (whole: its tables, its section 6) and `tasks/bench8/node-fields.md` (the log lines and fields this node build added, verbatim). Budget 35 tool calls, about 120 printed lines per call. Read-only on results and earlier analyses; no cloud, no cargo, no `gh`.
Scratch (yours, gitignored): `benchmark/work/bench8-scratch/r1-AE5/` with `scripts/`. The first look's extracts are reusable and read-only for you: `benchmark/work/bench8-scratch/r1-AF1/` (`ev/vNN.pkl` = each validator's `header proposed`, `quorum reached` and `vote path timing` lines; `blockmap.pkl`; `perheader-Wprekill.pkl`; `authority.json`; the scripts that made them in `scripts/`). Checkpoint `tasks/checkpoint-bench8-A-E5.md`, rewritten after each step; on start read it and continue.

## What is known (first look, one run)

Run 1 is bench 7's always-on run with the floor at 16 outputs instead of 8. In the load blast (mixed phase 21:54:55 to 22:35:11Z; validator-05 killed at 22:26:12Z):
- 21:54:55 to 22:09:55 (epoch 4 until 22:07:21, then the first 2.5 min of epoch 5): fleet certification 99.83 to 99.99 % per 300-s bucket, under-held headers 0.03 %.
- 22:09:55 to 22:24:55 (inside epoch 5): 93.94 %, 95.13 %, 96.70 %. Validator-02 certified 412 of 824 own headers in 22:09:55-22:14:55, then 575 of 781, then 680 of 745; validators 04, 10, 07 and 05 lost headers too; 01, 03, 06, 08, 09 lost none. Under-held headers (named block held by at most 5 other voters at the proposal) explain 712 of the 1,208 headers lost before the kill; 496 were not under-held, and 462 of validator-02's lost headers were held by at least 6 others when they were cancelled.
- After epoch 6 began (22:27:31Z, validator-05 dead or catching up): 98.98 %, then 99.93 %.
- Epoch 4 began under light load (the load blast's mixed phase started 7 min 43 s into it); epoch 5 was the first epoch that began under the full load.

## Questions, in this order (stop when the budget is two-thirds used and write up what you have)

1. **The onset.** To the second (and the round), when does validator-02's first run of lost headers begin, and what happened on validator-02 and in the fleet in the 60 s before: the epoch boundary (the epoch-close lines, the epoch record vote lines, `leader schedule updated`), validator-02's own execution (`engine` lines with `cpu_ms`, `store_bytes`, `outputs_behind`; `output execution task finished`), its commit lag, any restart, any error or warn line that is not routine. Same for validators 04 and 10 (shorter).
2. **Why validator-02's headers were lost.** For its lost headers in 22:09:55-22:14:55: what did the voters answer (`vote path timing` outcomes per voter: created, superseded, rejected, behind; `superseded_by_round`, `superseded_after_ms`; `exec_deficit_outputs`, `exec_deficit_open`, `exec_tip_arrival`, `exec_tip_answer`), how many answers arrived before validator-02 proposed its next header (the vote round end lines: `vote_arrivals`, `vote_errors`, `votes_at_end`, `stake_at_end`), how long its rounds were against the fleet's. Split the lost headers into: under-held; cut off by its own next header while enough voters held the block; refused for another reason (name it). Give counts.
3. **Who was behind.** Per 60 s from 22:05 to 22:27: each validator's execution tip against the fleet's leading tip, in block-bearing outputs (the blockmap), from its own `header proposed` `exec_tip`; mark which validators are more than 8 and more than 16 behind, and for how long. Is validator-02 the one behind (its voters cannot vote for others), or the one ahead (its headers name blocks others lack), or neither?
4. **The floor's reach.** In the lossy buckets, the share of validator-02's (and 04's, 10's) headers that named the floor (16 back), and whether a quorum held even the floor block.
5. **Epoch 4 against epoch 5.** The same per-60-s spread (question 3) for 21:55 to 22:07: was the spread already growing before the boundary, or did it jump at it?
6. `benchmark/results/r20261116-2011/logs/bench-validator-02-telcoin-cert-fail-20261116T230648Z.log.gz` exists (the harness saved it because validator-02 fell below 90 %): say what it holds and use it if it answers 1 or 2 faster.

Say for every statement whether it is measured (file, key or line) or inferred. A timing fit is not a mechanism. One run.

## Hand back

The report as plain text between the lines `BEGIN-AE5-REPORT` and `END-AE5-REPORT` in your final answer, then: the onset time, the three counts of question 2, one sentence on question 3, what is unfinished, the scratch directory.
