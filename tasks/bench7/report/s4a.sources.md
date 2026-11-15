# Sources for s4a.md (§4.1-4.4), figures in order of appearance

Files behind the cite prefixes:
- C: benchmark/private/bench7-r20261115-1653/A9/comparison.json (row id; cells `a7a.value`, `b7b.value`, `spread.min`/`spread.max`, `verdict`); "C recommendation": benchmark/private/bench7-r20261115-1653/A9/recommendation.md
- V: benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json; pair a = `pairs.7a_vs_b6run2`, pair b = `pairs.7b_vs_b6run3`; "q2_rows a.NN" = row id Q2.a.NN
- 7a / 7b A<N>: benchmark/private/bench7-r20261115-1131/A<N>/ and benchmark/private/bench7-r20261115-1653/A<N>/ (A3: `q4u-<run>-B2.json`, `q2-<run>-B2.json`, `perheader.md`; A5: `engine.json` under `.run.<run>`; A6: `disk.json`; A7: `losses.json`)

## 4.1

| figure | file | key or row |
|---|---|---|
| 9,289 / 9,337; spread 8,344.6-10,544.9; not told apart | C | Q1.01 |
| 95.59 / 95.00; 93.37-97.29 | C | Q1.09 |
| 83.6 / 76.4; 55.2-89.3 | C | Q1.10 |
| 2.32 / 2.22; 1.99-2.73 | C | Q1.24 |
| 17.33 / 24.18; 14.27-18.78; outside | C | Q1.06 |
| 698.3 / 680.0; 688.2-722.8; outside; all-generators window 315 / 358 s | C | Q1.04 (label; note) |
| 100.0 / 89.2; 99.9-100.0 | C | Q1.11 |
| 94.1 / 99.4; 90.3-95.4 | C | Q1.12 |
| 100.0 / 90.8; 99.9-100.1 | C | Q1.13 |
| 62.7 / 79.0; 55.2-69.5 | C | Q1.14 |
| 86.4 / 99.2; 77.5-88.4 | C | Q1.15 |
| spread definitions (300-s buckets; the two before the kill; 60-s blocks) | tasks/checkpoint-bench7-A9.md notes; C | Q1.04 (spread.src) |
| 817 s / 1,121 s | C | q3_hold.windows["B2-prekill"] |
| combined documents; 1-in-100 sampled landings | C recommendation | "What it rests on", bullet 2 (Q1.06) |
| 7.76 / 8.77 s; 17.40 / 22.06 s | C | Q1.07; Q1.08 |
| 61.5 %; 59.7 % (run 7b): a share of the headers built inside a starved window, not a share of time | C | Q4.26; Q4.12 (label: "share of headers inside a starved window (logged exec_policy, counted in headers built)") |
| the window counts headers built, not rounds (read; cite [read; a-common §3]) | tasks/bench7/briefs/a-common.md | §3, line 47 |
| 99.875 %; 56.3 %; 89.1 % | C | Q4.29; Q4.30 (note: replayed; `.fleet.replay_agreement_pct`) |
| 1.66; 64.0 % | C | Q4.27; Q4.28 |
| 38.51 / 0.26 %; 54.0 / 77.0 % | C | Q4.17; Q4.15 |
| fleet mean 7.57 / 4.83; spread 6.96-7.95 (nine proposers); fleet median 8 / 8; 6.77 / 4.45 s | C | Q4.21 (label "fleet mean"; note "fleet p50 7a 8, 7b 8"); Q4.22 |
| 7.36 / 4.43 s | C | Q4.23 |
| 96.4 / 98.1 % | C | Q4.20 |
| 41 rows | C | q5_per_validator.outside_7a_bucket_range (41 ids) |
| 28 lower, 13 higher | C | q5_per_validator.outside_7a_bucket_range (recounted from the rows' `diff`) |
| five farthest outside the range by its width: validator-01 or 05 lower, 10.6-12.0 points | C | Q5.34, Q5.40, Q5.30, Q5.11, Q5.50 (`rel_to_spread` 60.0-53.0) |
| largest in points: validator-08, up to +22.2 (77.5 to 99.7 %, bucket 01) | C | Q5.47 (also Q5.75 +19.8, Q5.102 +17.3) |
| 04, 06, 08, 10 / 01, 02, 05, 06, 10; both 06, 10 | C | q5_per_validator.lagging_sets["certified under 98 %, blast 2 mixed"] |
| 0 of 8; 5 of 8 | C | q5_per_validator.same_slowest_buckets; .same_lowest_cert_buckets |
| the two quoted sentences | C recommendation | "## Recommendation" |
| variation inside one run; no significance test | C recommendation | "What the pair cannot tell", bullet 3 |
| second run; 50,000 IOPS; age; floor; code | C recommendation | "What would change it", bullets 1-5 |
| floor 16 (bullet 4) | 7a / 7b A3 perheader.md | §8 rows "B2 \| floor 16" (see 4.3) |

## 4.2

| figure | file | key or row |
|---|---|---|
| window: blast 2 as each generator saw it; bench 6's gap-resend cells (L rows) its warm-up start to its cool-down end | V | q2_senders.window |
| 0 / 29,449 / 0 / 104,168 | V; C | q2_senders.pairs.<a\|b>.rows["gap resends, 05 apart"]; Q2.01 |
| 32 / 0; 183 / 0; 2,137 / 0; 10,767 / 9,290 | V; C | q2_senders rows["unlanded after the 180-s tail scan, all / 05 apart"]; Q2.08, Q2.09 |
| 9,780 / 40,263 / 7,724 / 111,508 | V; C | q2_senders rows["landings seen 300 s or more after submission (all generators)"]; Q2.11 |
| blast 2, outside 05: no gap resend, none unlanded, no landing seen 300 s or more after submission | C | Q2.01; Q2.08; Q2.10 (label "landings seen 300 s or more after submission, generators other than 05") |
| nine validators other than 05 | V | q2_senders rows["validators with a lost own header"].bench7.05_apart |
| 981 / 1,127; 1,002 / 1,168 | 7a / 7b A7 losses.json | lost_kinds.by_window.B2.fleet.loss_not_certified_with_batches; .a2_not_certified_with_batches |
| the two definitions | 7a / 7b A7 losses.json | lost_kinds.how_they_differ[1] |
| 293 / 356; never committed = no `certificate committed` for (origin, epoch, round) on any validator except 05, whole run | 7a / 7b A7 losses.json | lost_kinds.by_window.B2.fleet.loss_certified_not_committed_with_batches; lost_kinds.definitions.loss_certified_not_committed_mechanism (filled from `lost_with_batches`, A7/scripts/lost_kinds.py line 33) |
| 988 not certified (the loss analysis's definition) / 338 certified, never committed | V | q3_hold.pairs.b.rows["lost own headers"].bench7.<not_certified\|certified_not_committed>.05_apart |
| 280-345 s; 31 of 31; 124 of 124 | V | q3_hold.pairs.<a\|b>.rows["lost-header-to-resend timing…"].bench6.value; what_the_loss_analyses_show |
| out-of-order 0 (log, warnings, export) | C; V | Q3.49, Q3.50; q3_hold.pairs rows["the hold's own counters…"] |
| no bench 6 twin | V | q3_hold.attribution.isolated_by_a_counter |
| quoted not-separable list | V | q3_hold.attribution.not_separable |
| 4 transactions; one episode; 4 seen late | C | Q2.14; Q2.15; Q2.17 |
| generator 06, preamble wait ran full | C recommendation | "What it rests on", senders' cost bullet |
| one resend second, lost header 280-345 s before | V | q3_hold.pairs.a.rows[timing].bench7.by_blast["1"] |
| 22 (the export's counter `tn_reth_invalid_txs_skipped_total{reason="nonce_too_high"}`); 2 per node on 11 nodes; blast 1; run 7b 0 | C; V | q3_hold.fleet_checks n=2 a7a.value; Q2.06; q2_senders.pairs.<a\|b>.rows["nonce_too_high skips"].bench7[0].value |
| run 7a "not 0: 4" (gap resends), "not 0: 22" (`nonce_too_high`), the plan's "near 0"; run 7b "met" | C | q3_hold.fleet_checks n=3, n=2 (a7a.verdict, b7b.verdict) |
| 9,812 / 8,129; 32 / 2,137 | C | Q2.02; Q2.09 |
| what the unlanded and late sightings are | V | q2_senders.pairs.<a\|b>.what_the_loss_analysis_found.unlanded, .seen_300s |
| landed vs seen | tasks/bench7/analysis-decisions.md | line 17 |
| 1,866 / 3,259; 0 / 0 | C | Q3.36; Q3.37 |
| 21 (before the kill); 113 (after 05's start) | C | Q3.39; q3_hold.reading[0] |
| 9.1 s; 55.3 s (both after 05's start) | C | Q3.40; q3_hold.reading[0] |
| 2.46 / 3.13; 6.9 / 15.6 | C | Q3.41; Q3.43 |
| 49.8 / 60.5; 97.3 / 97.4 | C | Q3.61; Q3.62 |
| 152 / 183 (inferred) | C | Q3.58 |
| 0 / 0 over-quota | C | Q3.53 |
| 817 / 1,121 s; 1,308 / 990 s | C | q3_hold.windows["B2-prekill"], ["B2-poststart"] |
| 1,110 / 2,056 | C | Q3.58 note |
| 5 batches; 350 ms | 7a / 7b A7 losses.json | early_trigger.fleet_parameters |
| review's 1 s | 7a / 7b A7 losses.json | early_trigger.read.review_value_note |
| 32 cells; validator-06 outage 1 blocker, 0 held | C | q3_hold.fleet_checks[n=5].a7a.value |
| validator-05 blast 0: 18 blockers; 26 headers, pending 0, batches 0, held 0 | C | q3_hold.fleet_checks[n=5].b7b.value |

## 4.3

| figure | file | key or row |
|---|---|---|
| 817, 1,477, 1,121, 1,393 s | V | q3_certification_rounds.pairs.<a\|b>.secs_prekill |
| throughput row's window: bench 5's headline window, blast 2's all-generators window, kill inside (7a 2,375 s, 7b 2,389 s) | V; C | q2_rows Q2.a.01 / Q2.b.01 key .runs[0].blasts[2].bench5_defs.kpis.avg_chain_tps_all_generators; Q1.01 note |
| 9,289 / 5,322 / 9,337 / 5,395; +74.5 % / +73.1 % | V | q2_rows Q2.a.01, Q2.b.01 (diff_rel) |
| 94.0 / 99.94 / 94.95 / 99.56; bench 7 cells the certification analysis's count, bench 6 cells its rounds analysis's | V | q3_certification_rounds rows["certified pre-kill, rounds unit (%)"] (values; .definition) |
| 4 / 0 / 4 / 0 | V | q3_certification_rounds rows["validators other than 05 under 98 % certified pre-kill"] |
| 34.8 / 0 / 39.3 / 0.6 | V | q3_vote_path.pairs.<a\|b>.compare["blast 2 mixed before kill"].refused_behind_prom_per_min |
| 1,199 / 3.5 / 2,089 / 136 | V | same, .voter_superseded_per_min |
| 11.13 / 0.02 / 10.34 / 2.98 | V | q3_certification_rounds rows["rounds with k >= 4 under-held parents, share (%)"] |
| 2.54 / 2.81 / 2.46 / 2.78 | V | q2_rows Q2.a.18, Q2.b.18 |
| 16.96 / 35.65 / 21.36 / 34.0 | V | q3_certification_rounds rows["A2 fleet exec_lag_rounds_mean_median"] |
| 5,432 / 6,378; 10.31 / 12.55 %; 61.25 / 66.70 %; 99.53 / 99.06 % | 7a / 7b A3 q4u-<run>-B2.json | .fleet.under_held, .under_held_pct, .under_held_certified_pct, .others_certified_pct |
| at most five other voters; validator-05 counted without the block after its start | 7a / 7b A3 q4u-<run>-B2.json; tasks/bench7/analysis-decisions.md | .definition; line 10 |
| 94.3 / 99.9 / 96.4; 92.1 / 99.9 / 98.1 | 7a / 7b A3 q2-<run>-B2.json | .fleet.basis_certified_pct |
| floor 16: 0.00 %; 14.71 / 13.81 outputs; 13.16 / 12.72 s | 7a / 7b A3 perheader.md | §8 row "B2 \| floor 16" (7a line 280, 7b line 467) |
| measured 7.57 / 4.83 outputs; 6.77 / 4.45 s | 7a / 7b A3 perheader.md | §8 row "B2 \| measured" (7a line 278, 7b line 465) |
| the older block's cost not measured | s4a §4.1 line 55; C recommendation | line 30 |
| floor kept at 8 | C recommendation | "What would change it", bullet 4 |
| no counter isolates; mechanism split | V | q3_certification_rounds.attribution.isolated_by_a_counter |
| quoted not-separable list | V | q3_certification_rounds.attribution.not_separable["certification share"] |

## 4.4

| figure | file | key or row |
|---|---|---|
| table, engine rows (executed tx/s, rate at full busy, busy ms/s, task, execute, persist, commit µs/tx, persist share, tx per output, commit and persist ms per output) | V (bench 7 cells name 7a / 7b A5 engine.json `.run.<run>.window.2.log_fleet.<key>` or `.bound_check.<key>`) | q3_storage.runs.<b6r2\|7a\|b6r3\|7b>.engine_b2.<executed_tx_per_s_node_mean, rate_at_full_busy, timeline_busy_ms_per_s_mean, task_us_per_tx, execute_us_per_tx, persist_us_per_tx, commit_us_per_tx, persist_share_of_task, txs_per_output_all, commit_ms_per_output, persist_ms_per_output> |
| table, device rows (share of cap, writes per tx, ms per write, bytes per tx) | V | q3_storage.runs.<run>.disk.b2.<wr_of_limit, wr_per_tx, wr_lat_ms, wr_bytes_per_tx> |
| 978 ms/s (log timeline); 982 / 980 ms (Prometheus, median validator); 9,293 / 9,376 (log, mean per node); 9,327 / 9,392 at the Prometheus busy time; 9,500 / 9,582 at full busy | 7a / 7b A5 engine.json; V | .run.<run>.window.2.bound_check (busy_ms_per_s_prom_median 981.8 / 980.1, executed_tx_per_s_node_mean, rate_at_measured_busy 9,327.4 / 9,391.5, rate_at_full_busy); V q3_storage.runs.<run>.engine_b2.timeline_busy_ms_per_s_mean (978.1 / 978.4) |
| sequential cycle: 0 of 24,447 / 0 of 23,554 task starts before the previous task's end; task minus (execute + persist + announce) 2.7 / 2.61 ms mean | 7a / 7b A5 engine.md; engine.json | 7a line 113 (T16), 7b line 14 (T13); .run.<run>.window["2"].log_fleet.seq |
| 47 % | V | q3_storage.runs.<7a\|7b>.engine_b2.persist_share_of_task (0.4695 / 0.4674) |
| 0.859 / 0.863; 8.50 / 8.67 ms | V | q3_storage.runs.<7a\|7b>.disk.b2.wr_of_limit, .wr_lat_ms |
| 2.74 / 2.68 times bench 6's write size | V | q3_storage.attribution.not_separable |
| 21.49 → 42.07 µs; 20.32 → 42.34 µs | 7a / 7b A5 engine.json | .run.<run>.course.buckets[0], [7].commit_us_per_tx |
| 1.12 → 2.74 GiB; 1.11 → 2.72 GiB | 7a / 7b A5 engine.json | .run.<run>.course.buckets[0].tn_lmdb_used_gib_end_median, [7].tn_lmdb_used_gib_end_median |
| 10,470 → 8,393; 10,497 → 8,164 tx/s | 7a / 7b A5 engine.json | .run.<run>.course.buckets[0], [7].executed_tx_per_s_log |
| 14.3 / 14.9 µs per GiB (r² 0.966 / 0.968); -1,420 / -1,486 tx/s per GiB (r² 0.969 / 0.972); "a fit, not a mechanism" | 7a / 7b A5 engine.json | .run.<run>.course.fit_commit_us_per_tx_vs_used_gib, .fit_executed_tx_per_s_vs_used_gib, .fit_note |
| 0.997 / 1.000 of the identity rate; within 0.3 % | V | q3_storage.runs.<b6r2\|b6r3>.identity.b2.measured_over_limit_rate (0.9974 / 0.9996) |
| 0.43 / 0.44; 0.52 / 0.53; 0.92; 1.79 / 1.78; 2.15 / 2.12 | V | q3_storage.attribution.isolated_by_a_counter |
| 0.49 / 0.50; -4.0 % / +2.9 %; the halving as arithmetic (writes per output barely moving, transactions per output 2.15 / 2.12 times, row above); nothing isolates which change made the outputs larger | V | q3_storage.attribution.not_separable; .isolated_by_a_counter |
| #1834, one change | V | q3_storage.attribution.isolated_by_a_counter |
| every writer on the boot disk | 7a A6 disk.json; V | q10_whole_disk.statement; q3_storage.attribution.not_separable |
