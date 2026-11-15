# FC-P7: figure-check of bench 7's two backfill files

FIX

No figure is wrong; eight `weak` items (one shared by both files) need a wording change before publishing; none changes a conclusion.
Every replacement below is plain text with no double quote or backslash, so it is valid inside a JSON string as written (the apostrophes and "²" need no escaping).

## Counts

| file | shown fields | numeric tokens / ids checked | wrong | untraceable | weak | match |
|---|---|---|---|---|---|---|
| `2026-11-15-bench7-always-20k.json` (A, r20261115-1131) | title, summary, evidence 0, methodology 0-12, caveats 0-16, fleet, recovery, upstream | 515 / 33 | 0 | 0 | 3 (A-W1, A-W2, S-W1) | all other statements |
| `2026-11-15-bench7-adaptive-20k.json` (B, r20261115-1653) | title, summary, evidence 0, methodology 0-12, caveats 0-15, fleet, recovery, upstream | 627 / 45 | 0 | 0 | 5 (B-W1 to B-W4, S-W1) | all other statements |

## Structure

Both files parse with `json.load`.
Each has exactly the key set of its model (`2026-11-13-bench6-always-20k.json`, `2026-11-13-bench6-adaptive-20k.json`), nested keys included: no extra key, no missing key.
`compare_to` and `date`: A `r20261113-1351`, `2026-11-15`; B `r20261115-1131`, `2026-11-15`; both as gate.md's table says.
`status` is `complete` in both, as in the models; `upstream.evidence_detail` is a one-item list, as in the model.
`upstream.sha` `91a15e22376fa1277c107824e738dce689792c56` = `git -C tn-b7-p2 rev-parse 91a15e223`; 45dce8947 is its ancestor with 114 commits between them (`rev-list --count`), as the texts say.
`upstream.branch` `bench/bench7-2026-11`: exists as `refs/heads/bench/bench7-2026-11` at 91a15e223 in tn-b7-p2; there is no remote-tracking ref for it there, so that it is pushed (gate.md calls it public) is not checkable from the allowed sources: confirm it is on GitHub before the page links it.
`fleet` (both): label and load match both manifests (`fleet` c3-hdb, `machine_type` c3-highcpu-8, `node_disk` hyperdisk-balanced 20,000 IOPS / 800 MiB/s / 100 GB, `zones_used` validator-05 us-east4-b; ten `blasters` e2-standard-2, blaster NN targets validator NN).
`recovery`: A killed 2026-11-15T13:41:35Z, restarted 13:46:35Z; B 18:44:01Z, 18:49:01Z; node bench-validator-05; all equal to `manifest.chaos[0].ts` / `chaos[1].ts`; the three null fields are the writer's choice, explained in `_comment`.

## Wrong

None.

## Weak

S-W1 (both files, `upstream.evidence_detail` item 0).
Text: "The arm of both bench 7 runs set seven node switches: quorum_exec_block (the vote fix, whose form the setting quorum_exec_block_starved_rounds picks), vote_queue_fix (...), digest_order_hold (...) and the three epoch-record switches ...".
Problem: the sentence promises seven switches and names six; the seventh, quorum_exec_block_starved_rounds, appears only as "the setting" (report l.90 counts it among the seven).
Replace `quorum_exec_block (the vote fix, whose form the setting quorum_exec_block_starved_rounds picks)` with `quorum_exec_block (the vote fix) and quorum_exec_block_starved_rounds (which picks its form)`.

A-W1 (A, `caveats` item 0).
Text: "... device writes from 0.998 to 0.859 of the 20,000 cap and engine busy from 994.3 to 978.1 ms a second."
Source: report l.32 gives 994.3 (bench 6, r20261113-1351) and 978.1 (r20261115-1131), log timeline, with no spread and no verdict; run 7a's own 300-s buckets of engine busy run 967.2-999.2 ms (`comparison.json` Q1.32 spread, Prometheus), which holds bench 6's value.
Problem: "from ... to" reads as a fall; the rule is that a difference inside run 7a's own spread is not told apart, and the report does not call it one (it says only that both sit near full busy, l.488-491).
Replace `and engine busy from 994.3 to 978.1 ms a second` with `and engine busy was 994.3 and 978.1 ms a second, near full busy in both`.

A-W2 (A, `caveats` item 4).
Text: "(14.71 block-bearing outputs, 13.16 s at validator-01's output rate, against the measured 7.57 and 6.77 s)".
Source: report l.460: "against the measured 7.57 and 4.83 outputs, 6.77 and 4.45 s" (run 7a: 7.57 outputs, 6.77 s; `comparison.json` Q4.21 7.573, Q4.22 6.774).
Problem: 7.57 is outputs, not seconds; as written it reads as two times.
Replace `against the measured 7.57 and 6.77 s` with `against the measured 7.57 outputs and 6.77 s`.

B-W1 (B, `summary`, last sentence).
Text: "... with the storage engine, the vote handler, the order hold, the epoch-record switches and the run's shape changing together, so neither is put down to one change".
Source: report l.44 and l.462 list "the adaptive rule change (7b/run 3 only)" among the changes the certification fall is not separable between (`vs-bench6.json` `q3_certification_rounds.attribution`); B's own `caveats` item 5 lists it.
Problem: against r20261113-2118 the adaptive rule itself changed (the window is counted in headers built on this build, in rounds on bench 6's); leaving it out implies the form was the same on both benches.
Replace `with the storage engine, the vote handler, the order hold, the epoch-record switches and the run's shape changing together` with `with the storage engine, the vote handler, the order hold, the epoch-record switches, the change to the adaptive rule and the run's shape changing together`.

B-W2 (B, `caveats` item 7).
Text: "... against 104,168 gap resends, 9,290 unlanded and 52,588 skips in r20261113-2118; the plan's fleet checks ...".
Source: report l.30 and l.383: bench 6's resends and skips are counted from its warm-up start to its cool-down end (`vs-bench6.json` `q3_hold.pairs.7b_vs_b6run3` row 0 definition); A's `caveats` item 6 says so for r20261113-1351.
Problem: the bench 6 cells count a different window from "In blast 2", unstated on this page only.
Replace `and 52,588 skips in r20261113-2118;` with `and 52,588 skips in r20261113-2118 (its resends and skips from its warm-up start to its cool-down end);`.

B-W3 (B, `caveats` item 9).
Text: "The longest held run was 113 headers and 55.3 s (validator-06, after validator-05's start), against 21 headers and 9.1 s there."
Source: report l.417-418 and l.426: run 7a's 21 headers lie before the kill and its 9.1 s after validator-05's start, "so they are not one run" (`comparison.json` Q3.39 21 / Q3.40 9.083; Q3.30, run 7a's after-start window, is 15 headers); A's `caveats` item 9 says "two different runs".
Problem: "21 headers and 9.1 s" presents run 7a's two maxima as one held run.
Replace `against 21 headers and 9.1 s there.` with `against 21 headers (before the kill) and 9.1 s (after validator-05's start) there, two different runs.`.

B-W4 (B, `methodology` item 10).
Text: "A node-side figure on this page that reads one of them covers fewer nodes or stops early."
Source: the page's node-side figures read four series (`benchmark/report/kpis.py`: tn_primary_commit_latency_seconds, tn_engine_execution_duration_seconds, tn_node_mode, tn_batch_builder_seal_failures_total; no other tn_ or reth_ name occurs in kpis.py or make_bundle.py); run 7b's engine analysis, the file the report cites at l.175 (`benchmark/private/bench7-r20261115-1653/A5/engine.md` l.43, l.70, l.75), lists tn_engine_execution_duration_seconds among validator-01's series missing for the whole run ("absent v01; late or gapped obs11").
Problem: the sources settle the condition for one of the page's figures; gate.md asks the page to say where its Prometheus figures cover fewer validators.
Replace `A node-side figure on this page that reads one of them covers fewer nodes or stops early.` with `Validator-01's missing series include tn_engine_execution_duration_seconds, which this page's execution-duration figure reads, so that figure covers the other validators; any other node-side figure that reads a series named here covers fewer nodes or stops early.`.
Whether the three other page series are whole on validator-05 before 18:40:00 is not settled by the sources read (its three missing series are not named in the report or the CORRECTION line); the replacement does not claim it.

## Not traceable

None in the texts.
Not checkable from the allowed sources: that `bench/bench7-2026-11` is pushed (see Structure).

## Checked against the report line, file behind it not re-opened

Within the 35-call budget these figures were matched to the report line only; the report itself was figure-checked against these files earlier: tn-lmdb course and fit (21.49-42.07 µs, 10,470-8,393 tx/s, 1.12-2.74 GiB, 14.3 µs/GiB r² 0.966; B 20.32-42.34, 10,497-8,164, 1.11-2.72, 14.9 r² 0.968; 7a/7b A5 course); the floor-16 arithmetic (14.71 outputs, 13.16 s; 7a A3 perheader §8); validator-05's first own certificate 1.65 / 59.6 s (A4 recovery own_after: a list of log lines, not a number); validator-04's 516 spawn-capacity errors (7b A4 census leads); the epoch-record signer rows (7 / 8.86 s, 7 / 16.0 s, 7 / 11.84 s, 7 / 11.93 s and bench 6's; V q3_epoch_records rows); the far validators' certified-not-committed shares (V q3_far_validators); blast 1 far landed rates 161.8 / 172.0 / 1,198.8 and 169.6 / 157.0 / 1,186.6 (A7 far_generators); refused-behind and superseded per minute (V q3_vote_path; refused-behind re-derived from q3_certification_rounds counts: 474 / 817 s = 34.8, 734 / 1,121 s = 39.3, 15 / 1,393 s = 0.6, superseded bench 6 run 2 85 / 1,477 s = 3.5).
Re-derived from the files and matching: every `comparison.json` row the texts use (Q1.01-Q1.15, Q1.24, Q1.36-Q1.41, Q2.01-Q2.17, Q3.36-Q3.62, Q4.12-Q4.30, Q3F.01, .06-.08, .10, .16-.18, .20); `vs-bench6.json` q2_rows a/b .01, .04, .05, .09, .27-.29, q3_certification_rounds both pairs, q3_hold both pairs (981 = 981 with 05 apart in run 7a; 1,127 all / 988 with 05 apart in run 7b), q3_storage engine and disk; A4 recovery replay 95.418 / 68.207 s, rejoin attempts 1, left none, export mark 11.487 s; closing-block observer counts 17 / 13; census 19,307 / 438; A3 q4u 10.31 / 61.25 / 99.53 and 12.55 / 66.7 / 99.06; both manifests.

## Statements from outside the report

The vote fix's definition (A and B `methodology` item 3; B `summary`): same meaning as bench 6's published pages (`methodology` item 1 of both bench 6 files: "a proposer names in each header a block that a quorum of validators should already have executed; a voter signs only after it finds the named block in its own chain"; "never more than 8 outputs behind it (the floor)"; "until one of the author's headers is cancelled uncertified"); the change from bench 6's "up to 128 rounds" to "up to 128 headers" is the report's own (l.351) and is said: match.
#1807's mechanism (A and B `methodology` item 4): bench 6's `caveats` item 6 wording, shortened, same meaning: match.
"Saw its receipt", "the voter's lock wait", "8 x 16", "before an epoch boundary", generator 05 "cut off for the outage and for as long as its validator follows the chain": bench 6's `methodology` items 2, 4, 5, 6 wording: match.
"Headers built under the hold": gate.md's wording for the report's "headers held" (l.415, `comparison.json` Q3.36): match.
A `methodology` item 10, the four page series are not among validator-09's missing series: kpis.py's four names against run-facts 7a l.58's full list (up, scrape_*, tn_engine_root_seconds, tn_executor_output_transactions, tn_primary_vote_stage_seconds, tn_primary_uncertified_report_dropped_total, tn_reth_persist_save_blocks_seconds, tn_storage_tndb_write_stall_seconds, tn_worker_batch_report_seconds, tn_worker_batch_size_bytes, three reth_storage_providers_database_*, two reth_trie_*): none of the four is in it; "ten more series" after the five named is right (5 + 3 + 2): match.
B `methodology` item 10's conditional: see B-W4.
Aside for the orchestrator: report l.176 and run-facts 7b l.78 say validator-01's four missing series include "the consensus store's write-stall series", while 7b's engine.md l.70 names the four as persist duration, execution duration, tn_engine_root_seconds and tn_reth_block_state_root_seconds; the page names only persist duration, so it is unaffected, but the report and its source disagree on that list.
Full node commit sha: match (see Structure).

## Rule breaches

None in any shown field of either file: no unit name, no private path, no host or person name, no "7a" / "7b" / "run 2" / "run 3", no attribution of a tool or assistant ("agent" occurs only as "the metrics agent"), and the lost first attempt's run id appears nowhere in either file, `_comment` included.
Each page says one run per form ("each form ran once"), the kill by design (A `summary` "validator-05 killed by design inside the window", B `summary` "killed by design inside the load blast"), no significance test, the spread rule, the not-separable list, "consistent with the hold doing its job and does not prove it" (never that the hold removed #1807's losses), and no single word for what binds (engine and disk both below their limits, engine nearer).
Replayed and inferred figures are marked (B `caveats` item 3 "replayed, not logged"; early-trigger candidates "inferred"; the far validators' last step "inferred").
`_comment` (stripped before publishing, so not a breach) holds: the bundle command with the private env path `tasks/bench7/<run>/bench7-always.env` / `bench7-adaptive.env`, the source paths `tasks/bench7-report-r20261115-1131.md` and `tasks/bench7/report/p7.sources.md`, the manifest provenance of `recovery` and `fleet`, the reason the three recovery fields are null, and "Written 2026-11-15".

## Cross-page figures

| quantity | A | B | |
|---|---|---|---|
| blast 2 chain tx/s, 7a / 7b | 9,288.6 (summary), 9,289 against 9,337 (C5) | 9,337.2 against 9,288.6 (summary, C0) | same |
| seen p50, 7a / 7b | 9.40 | 8.62 against 9.40 | same |
| fleet certification blast 2, spread | 95.59 against 95.00; 93.37-97.29 | 95.00 against 95.59; 93.37-97.29 | same |
| lowest validator, spread | 83.6 against 76.4; 55.2-89.3 | 76.4 against 83.6; 55.2-89.3 | same |
| committed rounds per second, spread | 2.32 against 2.22; 1.99-2.73 | 2.22 against 2.32; 1.99-2.73 | same |
| seen p95; blast 0 rate | 17.33 against 24.18; 698.3 against 680.0 | 24.18 against 17.33; 680.0 against 698.3 | same |
| per-validator rows outside the spread | 28 lower, 13 higher in the adaptive run | 28 lower here, 13 higher | same |
| headers held; longest run | 1,866; 21 headers / 9.1 s | 3,259 against 1,866; 21 / 9.1 there | same values (B-W3 for the pairing) |
| windows before the kill | 817 s and 1,121 s | 1,121 s and 817 s | same |
| idle, kill epoch | 15.7 min, epoch 5; epoch 4 in r20261115-1653 | 5.7 against 15.7 min; epoch 4 here, 5 there | same |
| first own certificate after promotion | 1.65 s (59.6 s in the adaptive run) | 59.6 s against 1.65 s | same |
| kill offset | 817.1 s | 1,121.2 s against 817.1 s | same |
| distance to the named block | 7.57 outputs, 6.77 s | 7.57 to 4.83 outputs, 6.77 to 4.45 s | same |
| far generators blast 0, run 7a | 8.8 and 5.5 tx/s | r20261115-1131: 8.8 and 5.5 | same |
| closes; closing-block `ok` | 8; 179 | 7 (6 inside the export); 135; "r20261115-1131's 8 of 8" | same |
| fsync probe median | 1,044 µs | 1,074 µs | each its own run (report l.104) |
| build, image digest, generator commit, switches | identical evidence and methodology items 0-4 | identical | same |

No figure the two pages share differs.
