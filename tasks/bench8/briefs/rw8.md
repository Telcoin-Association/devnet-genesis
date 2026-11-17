# RW8 — the bench 8 report (two writers, then a figure-check)

Units `RW8-A` (§2, §3, §6, §8), `RW8-B` (§4, §5, §7, then §1 last). Writers: opus; load the `human-writing` skill first. Your launch prompt says which you are.
The report: `tasks/bench8-report.md`, assembled by the orchestrator from one file per section, `tasks/bench8/report/s<N>.md` (N = 1…8). You write ONLY your sections' files and one sources note per file, `tasks/bench8/report/s<N>.sources.md` (each figure: the JSON file and key, or the analysis file and line, it came from).
Read-only on code and results; no cloud, no cargo, no git writes, no `gh` write, no sub-agents. Checkpoint `tasks/checkpoint-bench8-<unit>.md` (a `status:` header, finished sections, the resume point), rewritten after each section; on start read it and continue.
Budget: at most 35 tool calls and about 120 printed lines per call. Read figures with small scripts that print only the keys you need; never dump a JSON file or a whole analysis. At the limit: finish the section you are in, checkpoint, hand back `partial`.

## What the report is

The private record of bench 8 for the repository owner (it is NOT a public text: private paths, run ids and unit names of the analyses may be cited as sources; still no host names, no cloud project id, no IP addresses, no mention of an assistant, an agent or a tool, and plain language, one sentence per line, no bold in running text).
Bench 8 asked one question: why header certification before the kill fell to about 94 % in bench 7's always-on run (7a, `r20261115-1131`). It ran three fleet runs on one node build (`bench/bench8-2026-11` at b1104905f: bench 7's image commit plus one bench-only parameter, `quorum_exec_block_floor_outputs`, and log fields), ten validators and one observer, the same machines, disks and generator as bench 7:

| run | id | arm | single change | 
|---|---|---|---|
| 1 (F) | `r20261116-2011` | `bench8-floor16` | the header may name an execution block up to 16 outputs behind its proposer's tip (bench 7: 8) |
| 2 (C) | `r20261116-2332` | `bench8-control` | none: bench 7's always-on arm, floor 8, on bench 8's build |
| 3 (R) | `r20261117-1401` | `bench8-control` | the load blast at about 5,300 tx/s (300 senders × window 4) instead of about 9,200 (600 × 16) |

The plan's rule, its rows and its yardstick: `tasks/plan.md` (Step 5) and `/home/drtnarg/.claude/plans/glistening-dancing-boole.md` (Step 5d): quote the rows exactly where you cite them.

## Sources (all figure-checked unless a line says otherwise; take figures from the JSON beside each analysis first, the markdown for definitions and wording)

- Run facts: `tasks/bench8/<run>/run-facts.md` for the three runs (each with a "By hand" section).
- Run 1: first look `benchmark/private/bench8-r20261116-2011/AF1/first-look.md` (+ `figcheck.md`, JSON beside it); the lossy stretch `…/AE5/epoch5.md` (+ `figcheck.md`).
- Run 2: first look `benchmark/private/bench8-r20261116-2332/AF2/first-look.md` (+ `figcheck.md`, JSON); validator-10's silence `…/AV10/validator-10.md` (NOT figure-checked as a whole; the figures the issue draft took from it were checked: `tasks/issue-bodies/notes/bench8-lagging-validator-at-epoch-boundary.figcheck.md`; prefer those).
- Run 3: first look `benchmark/private/bench8-r20261117-1401/AF3/first-look.md` (+ `figcheck.md`, JSON).
- The far validators (RW8-B only; your prompt says whether it is ready and checked): `benchmark/private/bench8-far/far.md`.
- Bench 7's run 7a for comparison: `benchmark/private/bench7-r20261115-1131/A2/numbers.json`, `A3/q2-…`, `A3/q4u-…`; the bench 7 report `tasks/bench7-report-r20261115-1131.md` (§1 and §4.3 only).
- Before the runs: `tasks/bench8/no-run-findings.md` (what the five no-run analyses of bench 7's data concluded).
- The node build's additions: `tasks/bench8/node-fields.md`.
- The orchestrator's log, for what happened around the runs: `tasks/checkpoint-bench8-orch.md` (grep for the run id or a keyword; do not read it whole). Lessons: the last two entries of `tasks/lessons.md`.
- The local issue draft that came out of run 2: `tasks/issue-bodies/bench8-lagging-validator-at-epoch-boundary.md` (not posted; the owner reviews it).

## Sections

| § | title | unit | about |
|---|---|---|---|
| 1 | Summary | RW8-B, last | at most 45 lines: the question; the three runs in one table (rate, certified % and under-held % in the window before the kill, for run 3 the whole mixed phase and its first 1,679 s; 7a beside them); the answer in four or five sentences, each marked measured or inferred; what is new; what is not known; what is for the owner to decide |
| 2 | Run facts and provenance | RW8-A | the build and image; the three runs' timelines (deploy, blasts with their real phases, the kill or its absence, teardown, archive); what differs between the runs' shapes apart from the planned change (blast 1's length against bench 7; where the load blast sits in the epochs; the kill at 1,877 s, 1,679 s and never; run 3's window offset of 85 s and its uneven ingress); what Prometheus lacks per run and what stands in; what is archived and what is private |
| 3 | The numbers | RW8-A | one table per question, runs side by side: the plan's two numbers per window; the 300-s buckets with their epochs; the per-epoch segments; per author (lost headers) per run; the distance named and the share at the floor; the achieved rate; the engines' busy share; the harness's own whole-phase count as a cross-check. No interpretation here beyond what a row is |
| 4 | Findings, ranked by what they change | RW8-B | 4.1 who loses headers and when (the validators at the execution lead; the step between three and four voters behind; what is definitional and what is observed, as run 2's figure-check words it); 4.2 the second path in run 1 is the same root (the bare quorum of seven, the superseded answers, the round's end at the author's next header); 4.3 what the floor does and does not do (16 against 8, first load epoch against the second; one run per floor); 4.4 the root: executors at about 97 % busy drift tens of outputs apart, at about 57 % none falls behind (run 3; what is measured and what is a timing fit); 4.5 the lagging validator at an epoch close (the internal error; the demotion and the nine minutes; twice in run 2, never in runs 1 and 3; how it feeds 4.1); 4.6 the far validators (from `far.md`, if ready; else say it is pending); 4.7 what did not happen (fail-stops, restarts, anything the logs would show) only if a source states it |
| 5 | What this means for the node | RW8-B | suggestions, none tried, each tied to a finding and marked as a suggestion: the floor's depth is not a fix by itself; a named block with margin above the bare quorum; execution capacity or back-pressure as the root; the vote answer for a closed epoch; the rejoin rule under load. What is the owner's decision and what could go upstream (nothing is posted during the freeze) |
| 6 | Friction and harness | RW8-A | what cost fleet time or data: the cloud login that died 1.5 h into run 3 (no kill, 2 h 40 min of idle fleet), the contracts path that went away (teardown rc 128, fixed in commit 1db706d), the metrics agent's lost batches and what the endpoint sampler saved, the harness gate's launch-caused failure and its fix, `analysis/certification.json` gaps (no authority for some validators; no window for run 3's load blast), the manifest's phases for run 3; what to fix before the next run |
| 7 | Open questions and what a next run could test | RW8-B | each with the measurement that would answer it: why some executors run slower at saturation (persist time; which validators and whether it moves with the epoch); whether a floor at the ring's depth plus a margin removes the loss at full load; the cost of the rejoin window; why run 2's validator-10's persist time rose; the far validators' ingress at reduced load |
| 8 | Appendix | RW8-A | an evidence index (one line per finding of §4: the analysis file, its figure-check and the JSON keys); the definitions used (certified, lost, under-held, the distance behind the lead, busy share, the windows); the corrections the figure-checks made that changed a statement made to the owner; what was not computed |

## Rules

Every figure names its run, its window and its counting unit, and is in a source you list. One run per configuration: say so wherever runs are compared; no significance claim. Mark measured, read from code, inferred, and "a timing fit". Where two sources disagree, say so and cite both; do not pick silently. Where a source was not figure-checked, say so beside the figure.

## Hand back

Per section file: its path, its word count, the sources note's path, anything you could not source, anything two sources disagree on.
