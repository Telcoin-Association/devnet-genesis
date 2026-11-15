# Figure-check FC-2: s4a.md §4.1-4.4

Verdict: FIX (4 wrong, 12 weak, 0 untraceable; no error changes a conclusion).

## Counts

| subsection | figures checked | match | wrong | untraceable | weak |
|---|---:|---:|---:|---:|---:|
| 4.1 (lines 7-57) | 105 | 101 | 0 | 0 | 4 |
| 4.2 (lines 61-115) | 107 | 101 | 1 | 0 | 5 |
| 4.3 (lines 119-142) | 68 | 64 | 3 | 0 | 1 |
| 4.4 (lines 146-178) | 113 | 111 | 0 | 0 | 2 |
| total | 393 | 377 | 4 | 0 | 12 |

## Wrong

W1. Line 85, §4.2.
Text: "Run 7a's fleet checks print both as not met [C q3_hold.fleet_checks]."
File: A9/comparison.json `q3_hold.fleet_checks` n=2 a7a.verdict "not 0: 22" and n=3 a7a.verdict "not 0: 4" (the plan's wording "near 0"); run 7b's n=2 and n=3 verdicts "met". Run 7a's third failing check (n=5, "not met: 1 (listed)") is the one lines 112-114 give.
Replacement: "Run 7a's fleet checks print the gap resends as "not 0: 4" and the `nonce_too_high` skips as "not 0: 22" against the plan's "near 0"; run 7b's print both as met [C q3_hold.fleet_checks]."

W2. Line 121, §4.3.
Text: "(the headline row: the whole mixed phase)".
File: A10/vs-bench6.json `q2_rows` Q2.a.01 / Q2.b.01 bench6 and bench7 key `.runs[0].blasts[2].bench5_defs.kpis.avg_chain_tps_all_generators` (bench 5's headline window, the all-generators window); A9 Q1.01 note: all-generators windows 7a 2,375 s, 7b 2,389 s, against blast 2's mixed phase of 2,425 / 2,411 s (`q3_hold.windows["B2"]`).
Replacement: "Against bench 6, one run each, in blast 2's mixed phase before the kill (the throughput row: bench 5's headline window, blast 2's all-generators window with the kill inside); the four before-the-kill windows are 817, 1,477, 1,121 and 1,393 s long [V q3_certification_rounds a, b] [V q2_rows a.01, b.01]."

W3. Line 126, §4.3, table row label.
Text: "Fleet certification, the rounds analysis's count (%)".
File: A10/vs-bench6.json `q3_certification_rounds.pairs.<a|b>.rows["certified pre-kill, rounds unit (%)"].definition` = "different units' figures for the same window (bench 7's from A2)": the bench 7 cells (94.0 / 94.95) are the certification analysis's count, the bench 6 cells (99.94 / 99.56) its rounds analysis's. Values match.
Replacement row: `| Fleet certification (%; bench 7: the certification analysis's count, bench 6: its rounds analysis's, same window) | 94.0 | 99.94 | 94.95 | 99.56 | [V q3_certification_rounds a, b] |`

W4. Line 135, §4.3, the under-held definition.
Text: "at the proposal at most five voters held the block they named".
File: bench7-r20261115-1131/A3/q4u-r20261115-1131-B2.json and bench7-r20261115-1653/A3/q4u-r20261115-1653-B2.json `definition` = "under-held = named block held by <= 5 other voters at the proposal"; analysis-decisions.md line 10 ("at most five other voters"). Figures 5,432 / 10.31 %, 6,378 / 12.55 % match.
Replacement: "In blast 2 as a whole 5,432 of run 7a's headers (10.31 %) and 6,378 of run 7b's (12.55 %) were under-held: at the proposal at most five other voters held the block they named, validator-05 counting as a voter without it after its start [7a A3 q4u B2.fleet] [7b A3 q4u B2.fleet]."

## Untraceable

None.

## Weak

K1. Line 19, §4.1, table row, window not named.
Text: "| Blast 0 chain tx/s | 698.3 | 680.0 | 688.2-722.8 | outside 7a's spread | [C Q1.04] |".
File: A9 Q1.04 label "B0 (8 x 16) chain tx/s, all-generators window"; note "all-generators windows: 7a 315 s, 7b 358 s" (blast 0 itself: 405 / 362 s, `q3_hold.windows["B0"]`). Values match.
Replacement row: `| Blast 0 chain tx/s, all-generators window (315 / 358 s) | 698.3 | 680.0 | 688.2-722.8 | outside 7a's spread | [C Q1.04] |`

K2. Line 30, §4.1, a share of headers read as a share of time.
Text: "Under load the adaptive form spent most of blast 2 in its starved window: 61.5 % of the headers run 7b built over blast 2 lay inside one, 59.7 % before the kill [C Q4.26] [C Q4.12]."
File: A9 Q4.26 61.52 / Q4.12 59.66, labels "share of headers inside a starved window (logged exec_policy, counted in headers built)"; no time share is measured.
Replacement: "Under load most of the headers the adaptive form built over blast 2 lay inside its starved window: 61.5 % of run 7b's headers over blast 2, 59.7 % of those before the kill [C Q4.26] [C Q4.12]."

K3. Line 35, §4.1, a mean given without saying so; the median did not move.
Text: "The distance from the tip to the named block fell from 7.57 to 4.83 block-bearing outputs (run 7a's spread over its nine proposers 6.96-7.95) …".
File: A9 Q4.21 label "fleet mean", 7.573 / 4.832, spread 6.963-7.945; note "fleet p50 7a 8, 7b 8". Q4.22 6.774 / 4.449 match.
Replacement: "The fleet mean distance from the tip to the named block fell from 7.57 to 4.83 block-bearing outputs (run 7a's spread over its nine proposers 6.96-7.95; the fleet median was 8 in both runs) and from 6.77 to 4.45 s at validator-01's output rate [C Q4.21] [C Q4.22]."

K4. Line 40, §4.1, "the largest" ranked by an unstated measure.
Text: "… 28 are lower in run 7b and 13 higher, the largest all on validator-01 or validator-05 lower".
File: A9 `q5_per_validator.outside_7a_bucket_range` (41 ids; recounted from the rows' `diff`: 28 lower, 13 higher, match). The five rows the recommendation names (Q5.34, Q5.40, Q5.30, Q5.11, Q5.50: -12.0 to -10.6 points) are the largest by `rel_to_spread` (60.0 to 53.0). By difference in points the largest are validator-08's rises: Q5.47 77.5 to 99.7 % (+22.2), Q5.75 +19.8, Q5.102 +17.3.
Replacement: "Of the 41 per-bucket rows that lie outside the validator's own run 7a range, 28 are lower in run 7b and 13 higher; the five farthest outside that range, measured against its width, are all validator-01 or validator-05 lower, by 10.6 to 12.0 points [C Q5.34] [C Q5.40] [C Q5.30] [C Q5.11] [C Q5.50], while the largest differences in points are validator-08's rises, up to 22.2 points (77.5 to 99.7 % in bucket 01) [C Q5.47] [C q5_per_validator.outside_7a_bucket_range]."

K5. Line 63, §4.2, table caption, window not named.
Text: "The senders' cost in blast 2, one run each; generator 05's validator was the one killed."
File: A10/vs-bench6.json `q2_senders.window` = "blast 2 as each generator saw it (A1 per-generator rows) on both benches; bench 6's L rows: warm-up start to cool-down end" (the bench 6 gap-resend cells 29,449 / 104,168 are L rows). All sixteen cells match.
Replacement: "The senders' cost in blast 2 as each generator saw it (bench 6's gap-resend cells: its warm-up start to its cool-down end), one run each; generator 05's validator was the one killed [V q2_senders.window]."

K6. Line 71, §4.2, blast not named (run 7a had 4 gap resends and 4 late landings outside generator 05 in blast 1).
Text: "Outside generator 05 neither bench 7 run gap-resent, left a transaction unlanded or saw a landing 300 s late [C Q2.01] [C Q2.08] [C Q2.10]."
File: A9 Q2.01, Q2.08, Q2.10 are blast-2 rows (0 / 0 each); Q2.14 blast 1 4 / 0, Q2.17 4 / 0.
Replacement: "In blast 2, outside generator 05 neither bench 7 run gap-resent, left a transaction unlanded or saw a landing 300 s late [C Q2.01] [C Q2.08] [C Q2.10]."

K7. Line 74, §4.2, the commit-path kind's definition not said (rule 6).
Text: "Certified but never committed: 293 / 356 …".
File: both runs' A7/losses.json `lost_kinds.by_window.B2.fleet.loss_certified_not_committed_with_batches` 293 / 356 (match). The key is filled from the mechanism test's `lost_with_batches` (`A7/scripts/lost_kinds.py` line 33; the run 7b copy changes only the input file), whose committed set is `lost_kinds.definitions.loss_certified_not_committed_mechanism`: "no `certificate committed` for (origin, epoch, round) on any validator except 05, whole run", not validator-01's set (the far-generator tables' definition). "Never committed" fits that set.
Replacement: "Certified but never committed (no validator other than 05 logged the certificate's commit in the whole run): 293 / 356 [7a A7 lost_kinds.by_window.B2.fleet] [7b A7 lost_kinds.by_window.B2.fleet]."

K8. Line 75, §4.2, which of line 73's two not-certified counts the 988 is.
Text: "Run 7b's counts include validator-05's own headers; without them they are 988 and 338 [V q3_hold b]."
File: A10/vs-bench6.json `q3_hold.pairs.7b_vs_b6run3` / `q2_senders` row "lost own headers" bench7 `not_certified.05_apart` 988 (all 1,127, the loss analysis's count), `certified_not_committed.05_apart` 338 (all 356); no count without validator-05 is given for the certification analysis's 1,168.
Replacement: "Run 7b's counts include validator-05's own headers; without them they are 988 not certified (the loss analysis's definition) and 338 certified but never committed [V q3_hold b]."

K9. Line 84, §4.2, "logged" for a counter.
Text: "Run 7a also logged 22 `nonce_too_high` skips, 2 per node on 11 nodes, all in blast 1; run 7b logged none".
File: A9 Q2.06 22 / 0.0, and `q3_hold.fleet_checks` n=2 a7a.value: "22 over the export window: 2 per node on 11 of 11 nodes; blast 0 0, blast 1 22, blast 2 0 (`tn_reth_invalid_txs_skipped_total{reason="nonce_too_high"}`, increase)". Values match; the source is the export's counter, not a log.
Replacement: "Run 7a's nodes also counted 22 `nonce_too_high` skips (the export's counter), 2 per node on 11 nodes, all in blast 1; run 7b's counted none [C Q2.06] [V q2_senders a, b]."

K10. Line 140, §4.3, the floor's cost stated as known.
Text: "Its cost is the named block's age: the mean distance would be 14.71 and 13.81 block-bearing outputs, 13.16 and 12.72 s …".
File: bench7-r20261115-1131/A3/perheader.md line 280 and bench7-r20261115-1653/A3/perheader.md line 467 ("B2 | floor 16": 14.71 / 13.16 s; 13.81 / 12.72 s; held by <= 5 0.00 %), lines 278 / 465 (measured 7.57 / 6.77 s; 4.83 / 4.45 s): all match. The section gives distances; the cost of the age is unmeasured (§4.1 line 55; recommendation.md line 30).
Replacement: "It would name an older block, whose cost bench 7 did not measure: the mean distance would be 14.71 and 13.81 block-bearing outputs, 13.16 and 12.72 s at validator-01's output rate, against the measured 7.57 and 4.83 outputs, 6.77 and 4.45 s [7a A3 perheader §8] [7b A3 perheader §8]."

K11. Line 168, §4.4, two busy readings mixed under one cite.
Text: "In both runs the engine was busy about 978 ms of every second and executed 9,293 / 9,376 tx/s per node, against the 9,500 / 9,582 tx/s its task cost allows at full busy [7a A5 window.2.bound_check] [7b A5 window.2.bound_check]."
File: `bound_check` has the same five keys in both runs' A5/engine.json `.run.<run>.window["2"]`: busy_ms_per_s_prom_median 981.8 / 980.1, task_us_per_tx_log_fleet 105.26 / 104.36, rate_at_measured_busy 9,327.4 / 9,391.5, rate_at_full_busy 9,500.3 / 9,582.2, executed_tx_per_s_node_mean 9,293.4 / 9,376.3 (log, mean per node; the same value as `log_fleet.executed_tx_per_s_node_mean`). The text's four rates match and use the same keys in both runs. The 978 is not in `bound_check`: it is the log timeline's busy time (V `q3_storage.runs.<run>.engine_b2.timeline_busy_ms_per_s_mean` 978.1 / 978.4). The engine analyses' own pairs: run 7a "9,327 tx/s, against 9,308 tx/s executed (Prometheus, median validator) and 9,293 tx/s (log, mean per node)" (7a A5/engine.md line 128, table line 136; 9,308 is in no `bound_check` key); run 7b "executed 9,376 tx/s per node (log; Prometheus median 9,351) … allowed 9,392" (7b A5/engine.md lines 12, 270). So 9,308 / 9,327 is Prometheus-executed against the rate at the measured busy time; 9,376 / 9,392 is log-executed against the same rate; the report's 9,293 / 9,376 against 9,500 / 9,582 is log-executed against full busy in both runs.
Replacement: "In both runs the engine was busy about 978 ms of every second by the log timeline (982 / 980 ms by Prometheus, median validator) and executed 9,293 / 9,376 tx/s per node (log, mean per node), against the 9,327 / 9,392 tx/s its task cost allows at the Prometheus busy time and 9,500 / 9,582 tx/s at full busy [7a A5 window.2.bound_check] [7b A5 window.2.bound_check] [V q3_storage.runs.<run>.engine_b2]."

K12. Line 169, §4.4, a bench 6 reading in the code cited where bench 7 measured it (rule 5).
Text: "The cycle executes and then persists in turn, as bench 6's report read in the code (its §4.6), so the task's time per transaction sets that rate; persist is 47 % of it [V q3_storage.runs.<run>.engine_b2]."
File: run 7a A5/engine.md line 113 (T16): "of the pooled validators' 24,447 task starts in blast 2, 0 began before the previous task's end"; `.run.r20261115-1131.window["2"].log_fleet.seq`: task minus (execute + persist + announce) 2.7 ms mean, p95 5.0, task / (execute + persist + announce) 1.0031 over 24,393 outputs. Run 7b A5/engine.md line 14 and its sequence table: "0 of 23,554 task starts in blast 2", `.run.r20261115-1653.window["2"].log_fleet.seq` 2.61 ms mean, p95 5.0, ratio 1.0029. Persist share 0.4695 / 0.4674 (match).
Replacement: "The cycle is sequential: no execution task started before the previous one ended (0 of 24,447 task starts in run 7a and 0 of 23,554 in run 7b, blast 2), and the task is execute plus persist plus announce plus 2.7 / 2.61 ms on average, so the task's time per transaction sets that rate; persist is 47 % of it [7a A5 engine.md T16] [7a A5 window.2.log_fleet.seq] [7b A5 engine.md T13] [7b A5 window.2.log_fleet.seq] [V q3_storage.runs.<run>.engine_b2]."
