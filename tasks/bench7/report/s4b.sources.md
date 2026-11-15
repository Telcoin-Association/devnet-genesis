# Sources for s4b.md (§4.5-4.8), in order of appearance

Files: C = `benchmark/private/bench7-r20261115-1653/A9/comparison.json` (Q1 rows in `q1_table`, Q3F rows in `q3_far_validators.rows`); V = `benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json` (rendered for §4.5 in `A10/far-validators.md`, from `A10/far-validators.json`); 7a A4 / 7b A4 = `benchmark/private/bench7-r20261115-1131/A4/` / `benchmark/private/bench7-r20261115-1653/A4/` (`closes.json`, `recovery.json`, `census.json`); RF 7a / RF 7b = `tasks/bench7/r20261115-1131/run-facts.md` / `tasks/bench7/r20261115-1653/run-facts.md`, line 9 (the arm).
In V `q3_far_validators.summary_rows`, a row is addressed `<window>.<metric>`; each holds `b6r2`, `b6r3`, `b7a`, `b7b` with `02`, `06`, `near_median`.

## 4.5

| figure | file | key or row |
|---|---|---|
| far rate 2-10 % of near median (B0), 13-14 % (B1) | V | `far_generators_b6.answer_by_blast.<0,1>.far_share_of_other8_rate` (7a, 7b: 0.099/0.062, 0.025/0.020; 0.135/0.143, 0.143/0.132) |
| bench 6 shortfall in blast 0 (blast 0, one run per cell) | V | `far_generators_b6.answer_by_blast.0.bench6_both_far_short_in_both_runs` = true |
| B1 seen p50 16.7-18.2 s (run 7b validator-02 16,650 ms, half up; analysis-decisions.md line 33) vs 4.10-5.08 s; near 2.11-2.12 vs 2.67-3.38 s | V | `q3_far_validators` B1.seen_p50_s (also C Q3F.12) |
| not certified 0 (bench 7, both blasts) | V | B0.bh_not_certified, B1.bh_not_certified |
| 46-76 % never committed | V | B0.bh_cnc_share, B1.bh_cnc_share (bench 7 cells) |
| re-queue 50-61 rounds, 21.0-21.4 s | C | Q3F.07, Q3F.08, Q3F.17, Q3F.18 |
| batch 12.9-61.4 s vs near 0.93-1.37 s | C | Q3F.06, Q3F.16 (ms; first own proposal to execution, both runs) |
| near re-queue count 0 | V | B0.requeue_events_committed, B1.requeue_events_committed (near_median) |
| table, landed rate (half up at the printed digit: run 7a validator-06 5.475 -> 5.48; bench 6 run 3 near median 88.85 -> 88.9) | V / C | B0.landed_tps, B1.landed_tps / Q3F.01, Q3F.11 |
| table, certified-not-committed share | V | B0.bh_cnc_share, B1.bh_cnc_share |
| table, proposals per batch p50 | V / C | B0.ppb_p50, B1.ppb_p50 / Q3F.05, Q3F.15 |
| table, first own proposal to execution | V (bench 6) / C (bench 7) | B0/B1.first_to_exec_p50_s / Q3F.06, Q3F.16 |
| table, re-queue rounds and seconds | V / C | B0/B1.requeue_rounds_p50, requeue_s_p50 / Q3F.07, Q3F.08, Q3F.17, Q3F.18 |
| table, committed share | V / C | B0/B1.committed_share_pct / Q3F.09, Q3F.19 |
| table, leader-slot share | V | B0/B1.leader_share_pct |
| rank 9th-10th; 7-8 of 9 (run 7b), 8 of 9 (run 7a) | V | B1.cert_rank_nc_p50, B1.late_nc_p50 |
| code lines proposer.rs:942 / :999, state.rs:809-812 | V | `q3_far_validators.code_reading` (rows 1, 2); the function differs at 91a15e223 (`stale_resend` bookkeeping, proposer.rs:1001-1003): row 3, `same` false, so the text says the trigger and the walk are the same |
| 127 of 127 within 50 ms | V | `q3_far_validators.reading` (the "[measured] trigger on bench 6" item); also `far-validators.json` `requeue_trigger_b6` |
| held 0 on 02/06 | C | Q3F.10, Q3F.20 (from both runs' `A7/losses.json` `far_generators.by_window.<B0,B1>.<02,06>` held_gt0) |
| committed share 2.12-3.50 % vs 3.96-6.49 % | V | B1.committed_share_pct |
| re-queue's delay in rounds overlaps: 41-58 (bench 6) vs 50-61 (bench 7) | V | B1.requeue_rounds_p50; `q3_far_validators.reading` (B1, what moved little) |
| round rate 2.83-2.84 vs 2.80-2.81 | V | B1.headers_per_s |
| leader slots 0 vs 0.48-1.72 % | V | B1.leader_share_pct; the lead: `q3_far_validators.differences` (leader_share_pct row) |

## 4.6

| figure | file | key or row |
|---|---|---|
| switch `epoch_record_conflict_halt`=true | RF 7a, RF 7b | line 9 |
| the later form drops the switch (cites "PR 04 body line 41", "plan line 89") | tasks/pr-bodies/bench6-04-collector-hardening.md; tasks/plan.md | line 41; line 89 (line 92: the harness drops it with the next image) |
| 8 closes on one hash and block by all 11 (7a); 6 (7b) | C | Q1.36 |
| run 7b epoch 6 at 19:25:01Z, 8 nodes; logs of 01, 02, 04 | 7b A4 | `closes.json` `closes[6].close_utc`, `.published_nodes`, `.window`; `last_closed_epoch_in_export` = 5; `closes.md` branch table |
| idle 1.91-2.36 / 1.50-1.99 / 1.29-2.71 / 1.39-1.94 s, a min-max over the run's idle closes; 1.39 is epoch 6, after the export, 8 publishing nodes | V; 7b A4 | `q3_epoch_records.pairs.<7a_vs_b6run2,7b_vs_b6run3>.rows[6]`; `closes.json` `closes[6].first_quorum_s`, `.window` |
| kill close 9/14.75, 7/8.86, 8/13.85, 7/11.84 | V | same, rows[1], rows[3] |
| other mixed close 7/16.44, 7/16.0, 7/14.85, 7/11.93 | V | same, rows[4], rows[5] |
| idle closes 10 signers | 7a A4, 7b A4 | `closes.json` `closes[*].signers_quorum_lines_min_med_max` |
| not separable | V | `q3_epoch_records.attribution.not_separable` |
| validator-05 `stored_matched` | 7a A4, 7b A4 | `closes.json` `closes[5,6].branches` (7a), `closes[4,5].branches` (7b) |
| validators 04 (4, 5), 03 (5); not restarted | 7b A4 | `recovery.json` `stored_matched_v03_v04`, `subscriber_mode_lines_v03_v04`, `exec_lag_max_rounds_at_close` |
| closing-block check 16/18/17, 179; 12/14/13, 135 | 7a A4, 7b A4, V | `closes.json` `closing_block_check.<node>.ok`; V `q3_epoch_records.pairs.*.rows[9]` |
| identity 8 / 6 ok, 0 mismatch | 7a A4, 7b A4 | `closes.json` `close_identity_check.<node>` |
| certified-through 7 / 5 on 11 nodes | V | `q3_epoch_records.pairs.*.rows[10]`; `closes.json` `certified_through_at_end` |
| conflict, halt, walk, invalid, re-certify all 0 | 7a A4, 7b A4 | `closes.json` `collector.<node>.lines`, `.counters`; `vote_rounds.<node>.recertify_round_lines`, `recertify_rounds_counter` |
| error line 3 -> 0; info twin 3 -> 2, 3 -> 1 | V | `q3_epoch_records.pairs.*.rows[7]`, `rows[8]`; `attribution.isolated_by_a_counter`; `closes.json` `vote_rounds_note` |

## 4.7

| figure | file | key or row |
|---|---|---|
| closing epoch 5 / 4 | C | Q1.37 |
| offset 1,477 / 1,393 / 817.1 / 1,121.2 s | V / C | `q2_rows.pairs.*.shape.kill_into_b2_mixed_s` / Q1.38 |
| load left 950 / 1,017 / 1,607.9 / 1,289.8 s | V / C | `q2_rows.pairs.*.shape.load_left_after_kill_s` / Q1.39 |
| kill to `CvvActive` 1,300.7 / 1,359.8 / 2,068.6 / 1,712.4 s | V / C | `q2_rows` Q2.a.27, Q2.b.27 / Q1.40 |
| cool-down end to promotion 301.9 / 302.8 / 450.7 / 400.5 s | V / C | Q2.a.28, Q2.b.28 / Q1.41 |
| observer distance 1: 23.3 / 360.4 / 3.7 / 4.5 s | V | Q2.a.29, Q2.b.29 |
| export mark 11.5 s after the log line | 7b A4 | `recovery.json` `rejoin_mark.export_mark_minus_log_s` (11.487) |
| replay 95.4 / 68.2 s; one attempt; no demotion | 7a A4, 7b A4 | `recovery.json` `replay_of_epoch5_s`, `replay_of_epoch4_s`, `rejoin_attempts`, `demotion_lines` |
| not ready 406 / 363; 180 / 199 `round_gap`; 126 / 125 `epoch_closed` | 7a A4, 7b A4 | `recovery.json` `rejoin_not_ready_total`, `rejoin_not_ready_by_phase` |
| no other validator left `CvvActive` | 7a A4, 7b A4 | `recovery.json` `left_cvv_active_outside_v05` (and `_logs` in 7b) = [] |
| observer all at distance 1: 41.1 / 29.9 s | 7a A4, 7b A4 | `recovery.json` `observer_restart.all_distance1_after_restart_end_s` |
| first header +0.42 / +0.77 s; first own certificate committed +1.65 / +59.57 s | 7a A4, 7b A4 | `recovery.json` `own_after` |
| validator-04 516 errors 18:45:24.787-18:45:29.399; validator-05 993 (run 7b), 1,347 over 7 task names (run 7a) | 7b A4 | `census.json` `leads.spawn_capacity.by_node.v04`, `.v05`; `leads.spawn_capacity.run7a_census` (sum of `total`) |

## 4.8

| figure | file | key or row |
|---|---|---|
| every fail-stop phrase 0 | 7a A4, 7b A4 | `census.json` `fail_stops` (the 17 phrase keys), `arms_agreement.fail_stop_nodes` = {} |
| "panic", "halt", "fork" inside digests, `node switches`, the fork-schedule banner; "fatal" only in `fatal request for requested vote` (33 / 152 lines) and once in run 7b's `penalty=Fatal` warn line | 7a A4, 7b A4 | `census.json` `words.<node>.<word>.where`, `in_text_templates`; `fail_stops.fatal_in_text` (33 / 153) |
| test-hook lines 0 | 7a A4, 7b A4 | `census.json` `arms_agreement.test_hook_lines` |
| "new against bench 6's run 2": the census's one reference, r20261113-1351, for both runs | 7a A4, 7b A4 | `census.json` `reference` (benchmark/private/bench6-r20261113-1351/A3b/census.json); flag `new_vs_run2` |
| too new 19,307 / 438 on v05, warn twin | 7a A4, 7b A4 | `census.json` `flagged` (templates `processed certificate that is too new`, `process_gossip | Certificate(…TooNew…)`) |
| AntiQuorum 3 (03, 06, 08) / 4 (03, 07, 08, 10) | 7a A4, 7b A4 | `census.json` `flagged` (`error while sealing batch | AntiQuorum`) |
| channel closed 1 on the observer | 7a A4, 7b A4 | `census.json` `flagged` (`ConsensusOutput channel closed. Shutting down...`) |
| run 7b's new spawn-capacity task names: `next-batch` 20, `ProcessGossip-tn-epoch-vote` 2, `sync-batches` 2; bench 6 run 2 1,421 lines; run 7a validator-05 1,347 | 7b A4 | `census.json` `flagged` (`new_vs_run2` true); `leads.spawn_capacity.bench6_run2_census`, `.run7a_census` |
| gauges at the arm; tn-lmdb on every node | 7a A4, 7b A4 | `census.json` `arm_store.gauges_at_arm`, `arm_store.store_by_node_arms` |
