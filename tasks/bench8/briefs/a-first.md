# A-F1 — bench 8 run 1 (floor 16): the first look that decides run 2

Read `tasks/bench8-agent-rules.md` (the budget; "Analysis units"), then `tasks/bench7/briefs/a-common.md` §2 to §9 (where a run is, how the node logs are laid out and filtered, the windows, the scratch rules; its §0 and §1 are bench 7's: your prompt gives this run's facts), then this brief. Budget 35 tool calls, about 120 printed lines per call. No cloud, no cargo, no `gh`. Read-only on `benchmark/results/` and on every earlier analysis.
Checkpoint `tasks/checkpoint-bench8-A-F1.md`, rewritten after each step (status, what is computed with its file, what is left). On start read it and continue.

## The question

Bench 7's always-on run (7a, `r20261115-1131`) lost about six points of header certification before the kill, and headers that named an execution block fewer than a quorum of voters held explain most of it. Bench 8 run 1 is the same run with ONE change: `quorum_exec_block_floor_outputs` 16 instead of 8 (the header may name a block up to 16 entries back in the ring instead of 8). The plan's rule for what runs next:

| run 1's result, in the window before the kill | next |
|---|---|
| fleet certification at least 99.0 % AND under-held headers under 1 % | the loss acts only through under-held headers: run R (reduced load) |
| fleet certification at most 97.3 % | another path: run H (no hold) |
| between | run C (a repeat of the control) first |

You produce the two numbers of that rule for run 1, by the SAME method that produced them for run 7a, the same numbers for 7a beside them, and the decision row they select. Nothing else.

## Method (the same as 7a's, so the numbers compare)

- 7a's analysis: `benchmark/private/bench7-r20261115-1131/A2/` (the certification analysis: `scripts/parse_b7.py`, `blockmap_b7.py`, `join_b7.py`, `analyze_b7.py`; its numbers `numbers.json`, text `certification.md`) and `…/A3/` (per header: `scripts/perheader.py`, `q1_join.py`, `q4_underheld.py`, `exec_tips.py`; text `perheader.md`; results `q4u-r20261115-1131-B2-prekill.json` and the `q1-*`, `q2-*` files). Read `perheader.md` §1 and §4 and the docstrings of those scripts first: the definitions are there. Under-held = a header whose named block was held by at most 5 of the other voters at the proposal (voter ring tips); round = (epoch, round) with at least 7 headers.
- Copy the scripts you need into `benchmark/work/bench8-scratch/r1-AF1/scripts/` and change only what the run id, the paths and the windows require. A change to a definition is not allowed; if a script cannot run on this run's logs without one, stop and say exactly which line and why (the node's log lines gained fields in bench 8: `tasks/bench8/node-fields.md` lists them verbatim; an existing field keeps its name and place).
- Extracts and pickles go to `benchmark/work/bench8-scratch/r1-AF1/` (gitignored). Long jobs run in the foreground with their output in a log file there; print the tail.
- Windows, from this run's manifest (`benchmark/results/<run>/manifest.json`: `blasts[].phases`, `chaos`; your prompt gives them): **W-817** = the load blast's mixed phase, first 817 s (7a's window before its kill was exactly 817 s: 13:27:58-13:41:35Z); **W-prekill** = the mixed phase's start to this run's kill (at least 817 s by the launch file); **300-s buckets** over the load blast's whole mixed phase (the yardstick: 7a's buckets ran from 93.37 % to 97.29 %).
- Cross-check with what the bench 8 node logs itself, as a second, independent count (do not replace the method with it): on `header proposed`, `exec_quorum` and `exec_floor`; on `vote path timing`, `exec_deficit_outputs` and `exec_deficit_open` (see `tasks/bench8/node-fields.md`): the share of headers for which at least one voter reported a deficit, and the share of vote answers with a deficit, in W-817.

## Output

1. One table, run 1 beside 7a, for W-817 (and run 1's W-prekill in a second column if it differs): headers; certified %; under-held headers and %; certified % of under-held; certified % of the others; per author: headers, certified %, lost.
2. The 300-s buckets of fleet certification over the mixed phase, run 1 beside 7a's, with validator-05 in or out stated per bucket.
3. The distance named (exec_tip minus exec_block, in block-bearing outputs): mean, p50, p95 and the share of headers at the floor, run 1 beside 7a: did the deeper floor get used.
4. The cross-check's two shares.
5. The decision row the two numbers select, in one sentence, and how far each number is from the row's bounds. One run per configuration: say so; no significance claim.
6. What you could not measure, and anything in the logs that would make the comparison unfair (a node missing, a phase cut short, the kill at a different point, a log gap).

Every figure names its window, its counting unit and the JSON file and key it came from. Scripts stay in `…/r1-AF1/scripts/`.

## Hand back

The report as plain text between a line `BEGIN-AF1-REPORT` and a line `END-AF1-REPORT` in your final answer (the orchestrator saves it; your Write under `benchmark/private/` would be refused), then five lines: the two numbers, the decision row, the scratch directory, what is unfinished.
