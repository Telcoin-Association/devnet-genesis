# N units — common brief (bench 8's no-run analyses of bench 7's and bench 6's saved data)

Read `tasks/bench8-agent-rules.md` first (budget: 35 tool calls, about 120 printed lines per call; checkpoints; scratch), then this file, then your own brief `tasks/bench8/briefs/n<k>.md`.
You are read-only on every result and on every earlier analysis. You write only: your output directory `benchmark/private/bench8-prep/N<k>/` (`findings.md`, one JSON file with every figure you state, `scripts/` with every script that made a figure), your checkpoint `tasks/checkpoint-bench8-N<k>.md`, and a copy of your findings at `tasks/checkpoint-bench8-N<k>-findings.md` (write it too: a Write under `benchmark/private/` has been refused to agents before). Big intermediate data goes to `benchmark/work/bench8-scratch/N<k>/`.

## The open question all five units serve

Bench 7 (2026-11-15, ten validators and one observer, 20,000 IOPS): the share of headers that were certified, in the load blast before the kill of validator-05, was 94.0 % in run 7a (r20261115-1131, the always-on form) and 94.95 % in run 7b (r20261115-1653, the adaptive form). Bench 6 had 99.94 % (r20261113-1351, always-on) and 99.56 % (r20261113-2118, adaptive) in its window before the kill.
Most of the loss sits in "under-held" headers: headers naming an execution block that fewer than a quorum of voters held when they were asked to vote.
Not known: why the validators' execution tips spread so far apart under the load blast that a block eight outputs back is not held by a quorum.
Inferred only, because header parents are not logged: that a far validator's certificate is lost at the last step because near validators' next-round headers do not name it as a parent.
Bench 8 will change one thing per run. Your unit says, from the data that already exists, which change is worth a run. A unit that ends "cannot tell from the saved data, and here is the field that would tell" is a full result.

## Where the data is (start from the data map, do not rediscover it)

- The data map of unit N0: `benchmark/private/bench8-prep/N0/data-map.md` (copy: `tasks/checkpoint-bench8-N0-findings.md`). It lists every pickle and JSON file, its schema, the windows with their UTC bounds, the definitions (under-held, holder, distance, block-bearing output), the scripts of the bench 7 analyses you can import or copy, and which figures of the plan it confirmed. READ IT FIRST. If it does not exist yet, stop and say so.
- Bench 7's per-header analysis (run 7a, then the same for 7b): `benchmark/private/bench7-r20261115-1131/A3/perheader.md`, its JSON files beside it, its scripts under `A3/scripts/`, the per-header pickles `benchmark/work/bench7-scratch/7a-A3/perheader-<window>.pkl` (7b: `7b-A3`), the event extracts `benchmark/work/bench7-scratch/7a-A2/ev/vNN.pkl` (7b: `7b-A2`).
- Bench 7's report: `tasks/bench7-report-r20261115-1131.md` (§4 findings; §7 evidence index). The form comparison: `benchmark/private/bench7-r20261115-1653/A9/comparison.md`. The bench 6 comparison and the far validators: `…/A10/vs-bench6.md`, `…/A10/far-validators.md`.
- Raw results (large; `grep`/`zcat` a narrow pattern into your scratch, never print them): `benchmark/results/<run>/`.
- Python: `python3` on the host; the pickles need only the standard library unless the data map says otherwise. One script per question, saved under your `scripts/`, output to a file, then read the part you need.

## Rules for the findings

- Every figure names its run id, its window (with UTC bounds at first mention), its counting unit (headers, voters, block-bearing outputs, seconds) and the file and key it came from.
- Mark each statement [measured] or [inferred]. A timing fit is not a mechanism. One run per form: say so wherever a conclusion rests on it.
- Validator-05 is killed in the load blast: say for every load-blast figure whether it is in it.
- State the answer to your question first, in three sentences at most, then the tables, then "what this decides for bench 8" (which run it argues for or against), then "what the saved data cannot tell" with the log field that would.
- No unit names of other programs in prose beyond file paths. This is a private file, so paths are fine.
- `findings.md`: 150 lines at most.

## Hand back (your final answer; a summary, not a file dump)

Status and checkpoint; the answer in three sentences; the five figures that carry it, each with its source; what it decides for bench 8; what cannot be told; files written.

## Corrections from the data map (N0, 2026-11-16) that every unit must use

- Windows differ between the runs: run 7a's kill is 817.1 s into the load blast (13:41:35.1Z), run 7b's is 1,121.2 s in (18:44:01.2Z). "Before the kill" is therefore 817 s in 7a and 1,121 s in 7b. Where you compare the runs, also compute 7b's FIRST 817 s (18:25:20-18:38:57Z); no earlier analysis did. Light blast 1 is 954 s in 7a and 374 s in 7b.
- Certified share before the kill, one analysis for all four runs (the certification analysis): 99.96 % (r20261113-1351), 99.56 % (r20261113-2118), 94.00 % (7a: 19,513 of 20,758), 94.95 % (7b: 26,179 of 27,571). The per-header analysis counts 1,400 lost in 7b (94.92 %).
- Under-held, summed over authors, before the kill: 7a 2,508 of 20,758 headers (1,364 certified, 1,144 lost; the other 18,250 headers lost 102); 7b 3,036 of 27,571 (1,907 certified, 1,129 lost; the other 24,535 lost 271).
- Under-held as the scripts compute it: at most 5 OTHER voters held the named block when the header was proposed (`q4_underheld.py` line 26), i.e. at most 6 holders of 10 with the author.
- The spread, re-derived by N0 (`N0/scripts/a6_tip_spread.py`): the proposer's tip minus the 6th-highest other voter's tip, in block-bearing outputs, is above 8 on 12.08 % of 7a's headers before the kill (exactly the under-held ones) and 8.78 % of 7b's, and never above 16 in either run. The lagging voters named there: 7a 05, 07, 10; 7b 09, 02, 04.
- Bench 6's r20261113-2118 has no per-header pickle (its extracts and blockmap exist; `perheader.py` can build one into your scratch). Bench 6's extracts have no `held` / `own_parent` fields. No per-60-s series is saved: build what you need from the per-header pickles.
