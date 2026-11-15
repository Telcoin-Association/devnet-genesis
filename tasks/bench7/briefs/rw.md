# RW — the bench 7 report (writers) and its figure-check

Units `RW-A` (§2, §3), `RW-B` (§5, §7), `RW-C` (§4.1-4.4), `RW-D` (§4.5-4.8, §6), then `RW-S` (§1, after the others), then `RW-FC` (the figure-check). Writers: opus, load the `human-writing` skill first. Your launch prompt says which you are.
The report: `tasks/bench7-report-r20261115-1131.md`, assembled by the orchestrator from one file per section, `tasks/bench7/report/s<N>.md` (N = 1…7; §4 is `s4a.md` for 4.1-4.4 and `s4b.md` for 4.5-4.8). You write ONLY your sections' files and one sources note per file, `tasks/bench7/report/s<N>.sources.md`.
Read-only on code and results; no cloud, no cargo, no git writes, no sub-agents. Checkpoint `tasks/checkpoint-bench7-<unit>.md` (a `status:` header, finished sections, the exact resume point), rewritten after each subsection; on start read it and continue.
HARD BUDGET RULE (the repository owner's): at most 35 tool calls and at most about 120 printed lines per tool call. Read figures with small scripts that print only the rows or keys you need; never dump a JSON file, a unit's markdown or the bench 6 report. At the limit: finish the subsection you are in, checkpoint, hand back `partial`.

## What the report is

The record of bench 7 for the repository owner and, in parts, for the node's maintainers: two fleet runs at 20,000 IOPS on one build, run 7a `r20261115-1131` (always-on vote form) and run 7b `r20261115-1653` (adaptive), with the order hold, the epoch-record switches and the closing-block check on, compared with each other and with bench 6's runs 2 and 3. The form of bench 6's report (`tasks/bench6-report-r20261113-1351.md`: read its headings and ONE subsection of your own kind for tone and density, by line range) is the model; bench 7's is shorter: about 450 lines in all.

| § | title | unit | about |
|---|---|---|---|
| 1 | Summary | RW-S | 45 lines: what ran; the answer on the form (the recommendation's two sentences, named as a recommendation); what #1807 looks like with the hold on; one headline table (run 7a, run 7b, bench 6 run 2, run 3); what is new; what did not happen; what is open |
| 2 | Run facts and provenance | RW-A | build and image, harness, fleet, the two runs' timelines, the lost first attempt at run 7b, what differs between the two runs' shapes and against bench 6's, the partial Prometheus series and what stands in, what was archived and what is private |
| 3 | KPIs | RW-A | per blast, both runs; blast 2 in five-minute buckets; per generator through the kill; time to land stage by stage; the plan's fleet checks with each run's result |
| 4.1 | The form: what the two runs tell apart and what they do not | RW-C | the form comparison and the recommendation |
| 4.2 | #1807 with the order hold on | RW-C | the senders' cost; lost own headers that no resend followed; what is and is not separable from the other changes; the hold's cost per form |
| 4.3 | Certification fell while throughput rose | RW-C | against bench 6; under-held headers, the floor arithmetic, refused-behind and superseded answers; not separable |
| 4.4 | What binds at 20,000 IOPS now | RW-C | the engine at its limit, persist's share, the device below its write cap, the course through the blast |
| 4.5 | The far validators' batches | RW-D | certified, not committed; four runs side by side; the hold ruled out; the cause open |
| 4.6 | Epoch records and the closing-block check | RW-D | closes, signers, seconds to quorum, the checks' counts, what never fired |
| 4.7 | Recovery after the kill | RW-D | both runs, with the four figures side by side, not one number against bench 6 |
| 4.8 | Census | RW-D | fail-stops (none), new error templates |
| 5 | Friction and harness | RW-B | what cost fleet time (the expired cloud login, the idle check's stop), the metrics agent's defect and the endpoint sampler, analysis-side findings about the tools, what to fix before the next run |
| 6 | Open questions and what a next run could test | RW-D | each with the measurement that would answer it |
| 7 | Appendix | RW-B | evidence index (one line per finding: files and keys), definitions that differ between units or benches, contradictions between units (from the form comparison's §6, none resolved), corrections made during the program |

## Sources (JSON first; markdown only for definitions and wording)

- Decisions and facts every writer reads in full: `tasks/bench7/analysis-decisions.md`; both runs' `tasks/bench7/<run>/run-facts.md`.
- The form comparison: `benchmark/private/bench7-r20261115-1653/A9/comparison.json` (rows by id: `Q1.NN`, `Q2.NN`, `Q3.NN`, `Q3F.NN`, `Q4.NN`, `Q5.NN`, `Q6.NN`; each row: label, both runs' value with file and key, the difference, run 7a's own spread, a verdict, a note), `comparison.md`, `recommendation.md`; checkpoint `tasks/checkpoint-bench7-A9.md`.
- The bench 6 comparison: `benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json` (keys `q1_same_shape`, `q2_rows`, `q2_senders`, `q3_storage`, `q3_hold`, `q3_vote_path`, `q3_epoch_records`, `q3_certification_rounds`, `q3_far_validators`, `q4_same_definitions`, `q5_no_counterpart`, `q6_form_gap`, `q7_statements`), `vs-bench6.md`, `far-validators.md`; checkpoints `tasks/checkpoint-bench7-A10.md`, `-A10-far.md`.
- The sixteen per-run analyses: `benchmark/private/bench7-<run>/A<N>/` (JSON and rendered markdown) with checkpoints `tasks/checkpoint-bench7-<7a|7b>-A<N>.md` (each lists its files and keys) and findings copies `…-findings.md`. N: 1 KPIs and stages, 2 certification and votes, 3 per header, 4 epoch closes, recovery and census, 5 engine, 6 disk, 7 losses and the hold, 8 rounds.
- The orchestrator's log for §2 and §5 only: `tasks/checkpoint-bench7-orch.md`, entries dated 2026-11-15 (grep by time; it is long: read by line range), and `tasks/lessons.md` (the 2026-11-15 entry).

## Rules for every sentence

1. One run per cell. Every table's caption says "one run each". A difference inside run 7a's own spread is "not told apart from noise"; no row inside the spread is counted for a form. No significance, no "wins", "better" or "outperforms" on such a row.
2. Nothing is attributed to one change unless a counter isolates it; otherwise "not separable", with the changes that moved together (the storage engine and storage v2; the order hold; the upstream vote-handler rework; the run shape: the kill came earlier into the load than in bench 6, and bench 6 started blast 2 with transactions still queued).
3. Never: tn-lmdb is faster "as a store"; the hold "removed" #1807's losses; a run is "disk-bound" or "engine-bound" in one word (give the engine's busy time and persist's share beside the device's write count against its cap and the device time per write).
4. Every figure is one a unit's file holds. In the text, each figure or table carries a short cite the appendix resolves: `[C Q1.04]` a row of the form comparison; `[V q2_rows a.03]` a row or key of the bench 6 comparison; `[7a A2 key]`, `[7b A6 key]` a per-run analysis file and key; `[RF 7b]` a run-facts line. The sources note lists, per figure in order of appearance: the figure, the file, the key or row id. A figure you cannot find in a file is left out and listed in your hand-back.
5. What is measured, read in code, replayed or inferred is marked where it is not measured: the adaptive window's sizes are replayed from the logs (99.875 % match); the early-trigger candidates are inferred; the far validators' last step (near headers not naming the late certificate) is inferred: which parents a header names is not logged.
6. Definitions that differ are said beside the figure: the two kinds of lost own header and their two counts; "landed" (block time) against "seen" (the scanner's time); the two runs' "before the kill" windows have different lengths (817 s and 1,121 s); blast 1 has no all-generators window in run 7a; run 7b's last close lies outside its export.
7. Unit names (A1 … A10) do not appear in prose: "the certification analysis", "the loss analysis", "the form comparison", "the bench 6 comparison". Private paths appear only in the appendix and in cites.
8. Sentences: `human-writing`. One sentence per line in the source. No filler, no summary sentence that repeats a table.

## Hand back

Per section file: path, line count; the five statements you consider most load-bearing with their cites; figures you wanted and could not find; anything in another section's scope that your sources contradict.

## RW-FC, the figure-check (after assembly)

Read `tasks/bench7/briefs/figcheck.md` for the method. Input: the assembled report and the `s<N>.sources.md` notes. For every figure in the report: find it in the cited file and key (a script per source file that prints the cited keys); verdict per figure `match`, `wrong` (with the file's value), `untraceable`, or `weak` (the sentence says more than the figure supports: rule 1, 2, 3 or 5 above). Output `tasks/bench7/report/figcheck.md`: counts, then every `wrong`, `untraceable` and `weak` item with its line, the report's text, the file's value and a replacement sentence. Split by section over several agents if the budget requires; each takes the sections its prompt names.
