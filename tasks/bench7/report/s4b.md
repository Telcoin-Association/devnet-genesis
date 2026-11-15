### 4.5 The far validators' batches

What it changes: a defect report for the node's maintainers that is not about the order hold.
Validators 02 and 06 are the far validators; "near" is the other eight.
In the light blasts of both bench 7 runs the far validators' generators land a small fraction of what the near generators land: 2 to 10 % of the near median in blast 0, 13 to 14 % in blast 1 [V far_generators_b6 answer_by_blast].
Bench 6's runs 2 and 3 show the same shortfall in blast 0, so in blast 0, one run per cell, it is not new with this build [V far_generators_b6 answer_by_blast].
In blast 1 bench 7's far generators are slower than bench 6's while the near ones are faster: seen p50 16.7-18.2 s against 4.10-5.08 s, and 2.11-2.12 s against 2.67-3.38 s for the near median [V q3_far_validators B1.seen_p50_s].
Every batch-carrying header of 02 and 06 was certified in both light blasts of both bench 7 runs, and 46 to 76 % of them were never committed [V q3_far_validators B0.bh_not_certified, B1.bh_not_certified, B0.bh_cnc_share, B1.bh_cnc_share].
Their digests go back into the proposer's queue on the commit path (`digests resent cause=committed`) a median 50 to 61 rounds after the header that carried them, 21.0 to 21.4 s in run 7b, the one bench 7 run whose file has the delay in seconds [C Q3F.07, Q3F.08, Q3F.17, Q3F.18].
A far batch takes 12.9 to 61.4 s at the median from its first own proposal to execution, against 0.93 to 1.37 s on the near validators [C Q3F.06, Q3F.16].

Validators 02 / 06, with the near median in parentheses, one run each; light blasts' mixed phases. Latency starts at the batch's first own proposal on all four runs. "-": not in the run's file. The near validators' median count of commit-path re-queues is 0 in every cell [V q3_far_validators B0.requeue_events_committed, B1.requeue_events_committed], so the re-queue rows give no near median.

| blast | quantity | bench 6 run 2 | bench 6 run 3 | run 7a | run 7b | cite |
|---|---|---|---|---|---|---|
| 0 | landed rate, tx/s | 10.1 / 10.5 (88.8) | 2.91 / 2.54 (88.9) | 8.76 / 5.48 (88.9) | 2.18 / 1.79 (88.3) | [V q3_far_validators B0.landed_tps; C Q3F.01] |
| 0 | certified, not committed, share of batch-carrying headers | 0.38 / 0.36 (0.00) | 0.70 / 0.71 (0.00) | 0.47 / 0.55 (-) | 0.75 / 0.76 (0.00) | [V q3_far_validators B0.bh_cnc_share] |
| 0 | proposals per batch, p50 | 2 / 2 (1) | 3 / 3 (1) | 2 / 2 (1) | 3 / 4 (1) | [V q3_far_validators B0.ppb_p50; C Q3F.05] |
| 0 | first own proposal to execution, p50 s | 12.5 / 15.0 (0.93) | 40.1 / 40.1 (0.93) | 16.1 / 20.3 (0.93) | 44.9 / 61.4 (0.93) | [V q3_far_validators B0.first_to_exec_p50_s; C Q3F.06] |
| 0 | re-queue's delay, p50 rounds | 48 / 48 | 60 / 60 | 50 / 52 | 60 / 60 | [V q3_far_validators B0.requeue_rounds_p50; C Q3F.07] |
| 0 | re-queue's delay, p50 s | 16.8 / 16.8 | 21.1 / 21.1 | - | 21.0 / 21.0 | [V q3_far_validators B0.requeue_s_p50; C Q3F.08] |
| 0 | committed share, % | 2.74 / 2.68 (11.9) | 1.17 / 1.19 (12.2) | 2.09 / 1.89 (12.0) | 1.12 / 0.92 (12.3) | [V q3_far_validators B0.committed_share_pct; C Q3F.09] |
| 0 | leader-slot share, % | 0.00 / 0.00 (13.0) | 0.00 / 0.00 (12.7) | 0.00 / 0.00 (12.5) | 0.00 / 0.00 (12.6) | [V q3_far_validators B0.leader_share_pct] |
| 1 | landed rate, tx/s | 283 / 202 (750) | 300 / 129 (776) | 162 / 172 (1,199) | 170 / 157 (1,187) | [V q3_far_validators B1.landed_tps; C Q3F.11] |
| 1 | certified, not committed, share of batch-carrying headers | 0.29 / 0.35 (0.00) | 0.14 / 0.16 (0.00) | 0.51 / 0.60 (0.02) | 0.46 / 0.50 (0.00) | [V q3_far_validators B1.bh_cnc_share] |
| 1 | proposals per batch, p50 | 1 / 1 (1) | 1 / 1 (1) | 2 / 2 (1) | 2 / 2 (1) | [V q3_far_validators B1.ppb_p50; C Q3F.15] |
| 1 | first own proposal to execution, p50 s | 2.90 / 3.24 (2.70) | 2.74 / 2.76 (1.91) | 15.8 / 15.2 (1.35) | 12.9 / 14.7 (1.37) | [V q3_far_validators B1.first_to_exec_p50_s; C Q3F.16] |
| 1 | re-queue's delay, p50 rounds | 48 / 48 | 58 / 41 | 58 / 50 | 60 / 61 | [V q3_far_validators B1.requeue_rounds_p50; C Q3F.17] |
| 1 | re-queue's delay, p50 s | 16.8 / 16.9 | 20.3 / 14.3 | - | 21.1 / 21.4 | [V q3_far_validators B1.requeue_s_p50; C Q3F.18] |
| 1 | committed share, % | 4.67 / 3.96 (11.6) | 6.49 / 5.72 (11.0) | 2.36 / 2.12 (12.0) | 3.50 / 3.28 (11.7) | [V q3_far_validators B1.committed_share_pct; C Q3F.19] |
| 1 | leader-slot share, % | 1.72 / 1.55 (12.2) | 0.48 / 0.48 (12.4) | 0.00 / 0.00 (12.8) | 0.00 / 0.00 (12.9) | [V q3_far_validators B1.leader_share_pct] |

The evidence chain, each step marked:

- [measured] In blast 1 a far certificate that is not committed forms 9th or 10th of ten at the median in run 7b and in both bench 6 runs, and 7 or 8 of the nine others have already proposed the next round in run 7b [V q3_far_validators B1.cert_rank_nc_p50, B1.late_nc_p50]. Run 7a has no rank and counts the others' next-round headers before its own quorum line, its own definition: 8 of 9 [V q3_far_validators B1.late_nc_p50].
- [read] The commit-path re-queue fires on an own commit notice and re-queues every tracked own header at or below the highest own round committed in it; the notice is sent whenever a committed sub-dag holds any header, and a notice that carries no own round re-queues nothing, so the effect is a re-queue only on an own commit (`crates/consensus/primary/src/consensus/state.rs:766`, `:809-814` and `crates/consensus/primary/src/proposer.rs:825-832`, `:849` at main 33b727fce; the state lines are identical on both builds). The trigger and the walk are the same on both builds: `crates/consensus/primary/src/proposer.rs:942` at 2df831e3c and `:999` at 91a15e223 (the `take_while`), `crates/consensus/primary/src/consensus/state.rs:809-812` on both [V q3_far_validators code_reading]. On bench 6, 127 of 127 commit-path re-queues of 02 and 06 in the light blasts came within 50 ms of the node's own `certificate committed` line [measured; V q3_far_validators reading].
- [measured] The order hold held no header of 02 or 06 in the light blasts of either bench 7 run [C Q3F.10, Q3F.20], and bench 6, which had no hold, shows the same pattern in blast 0 [V q3_far_validators B0.bh_cnc_share]. What bench 7 added on the commit path is bookkeeping that neither gates nor delays the re-queue [read; V q3_far_validators code_reading].
- [inferred] The near validators' next-round headers do not name the late far certificate as a parent, so no leader's sub-dag reaches it until the re-queue. Which parents a header names is not logged on either build.

What is open.
In blast 1 bench 7 commits a smaller share of the far validators' certificates than bench 6 (2.12-3.50 % against 3.96-6.49 %) [V q3_far_validators B1.committed_share_pct], while the re-queue's delay in rounds overlaps (41-58 rounds in bench 6, 50-61 in bench 7) [V q3_far_validators B1.requeue_rounds_p50, reading].
No counter isolates what moved that share.
The candidates are the upstream vote-handler rework (when far votes and certificates form), the near validators' speed on the new storage engine (the eight propose the next round sooner) and the round rate, which barely moved: 2.83-2.84 own headers per second against 2.80-2.81 [V q3_far_validators B1.headers_per_s]; none is concluded.
The far validators had no leader slot in blast 1 of either bench 7 run, against 0.48-1.72 % in bench 6 [V q3_far_validators B1.leader_share_pct]; the schedule's reputation counts votes that the vote-handler rework and the near round rate move, which is a lead, not a finding [V q3_far_validators differences].

### 4.6 Epoch records and the closing-block check

What it changes: confidence in the two epoch-record pull requests' code under load.
The bench image carried an earlier form of that code, with a conflict-halt switch (`epoch_record_conflict_halt`, on in both arms [RF 7a] [RF 7b]) that the later form drops [PR 04 body line 41; plan line 89].
Run 7a closed 8 epochs, every one on one record hash and one closing block and published by all eleven nodes [C Q1.36].
Run 7b closed 7 epochs, all on one record hash and one closing block, but only 6 lie inside the export and were published by all eleven [C Q1.36]: the last close (epoch 6, 19:25:01Z) falls after the export's last sample and after the logs of validators 01, 02 and 04 were pulled, so 8 nodes show it [7b A4 closes[6].published_nodes].
Run 7b's 6 of 7 is therefore not like for like with run 7a's 8 of 8.

Signers on the quorum lines and seconds to the first quorum, one run each; one close per cell except the idle row, which gives the range over the run's idle closes [V q3_epoch_records pairs]:

| close | bench 6 run 2 | run 7a | bench 6 run 3 | run 7b |
|---|---|---|---|---|
| idle closes, seconds to the first quorum | 1.91-2.36 | 1.50-1.99 | 1.29-2.71 | 1.39-1.94 (1.39: epoch 6, after the export, eight nodes' logs) |
| the kill's close (validator-05 down): signers min / seconds | 9 / 14.75 | 7 / 8.86 | 8 / 13.85 | 7 / 11.84 |
| the other close in blast 2's mixed phase: signers min / seconds | 7 / 16.44 | 7 / 16.0 | 7 / 14.85 | 7 / 11.93 |

Every idle close had all ten validators signing [7a A4 closes[*].signers_quorum_lines_min_med_max] [7b A4 closes[*].signers_quorum_lines_min_med_max].
The loaded closes' signers and seconds are not separable between the voters' execution lag, the vote-path rework, the hold, the record switches and the run shape [V q3_epoch_records attribution.not_separable].
Validator-05 published the records of the two closes after its kill from the collector (`stored_matched`) in both runs [7a A4 closes[5].branches] [7b A4 closes[4].branches].
In run 7b validators 04 (epochs 4 and 5) and 03 (epoch 5) did the same [7b A4 recovery stored_matched_v03_v04]; neither restarted: their subscriber-mode lines read `CvvActive` at every epoch start, and both lagged in execution at those closes [7b A4 recovery subscriber_mode_lines_v03_v04, exec_lag_max_rounds_at_close].
The closing-block check counted only `ok`: 16 per validator, 18 on validator-05 and 17 on the observer in run 7a (179 fleet-wide), 12, 14 and 13 in run 7b (135); its failure labels have no series on any node, and an absent label is 0 [7a A4 closing_block_check] [7b A4 closing_block_check] [V q3_epoch_records pairs row 9].
The close identity check read `ok` 8 times on every node in run 7a and 6 times in run 7b, with no `mismatch` [7a A4 close_identity_check] [7b A4 close_identity_check].
At the end of each export the certified-through gauge equalled the last close inside it on all eleven nodes: 7 in run 7a, 5 in run 7b [V q3_epoch_records pairs row 10].
What never fired, on any node in either run: a conflict line, a conflict halt, a walk past an uncertified epoch, an invalid record, a re-certify round, and their counters [7a A4 collector, vote_rounds] [7b A4 collector, vote_rounds].
The switches were on and nothing triggered them, so the runs do not exercise those paths.
The `failed to reach quorum on epoch close` error line fell from 3 in each bench 6 run to 0 in both bench 7 runs because this build logs it only when no certificate is held; its info twin, a vote round that ended without a local quorum while the record was already certified, counted 2 in run 7a and 1 in run 7b against 3 [V q3_epoch_records pairs rows 7, 8; attribution.isolated_by_a_counter].

### 4.7 Recovery after the kill

Validator-05 was killed in blast 2's mixed phase in both runs, at the close of epoch 5 in run 7a and of epoch 4 in run 7b [C Q1.37].
One run each; "load left" runs from the kill to the end of blast 2's mixed phase; kill to `CvvActive` is the node's own log line:

| | bench 6 run 2 | bench 6 run 3 | run 7a | run 7b | cite |
|---|---|---|---|---|---|
| the kill's offset into blast 2's mixed phase, s | 1,477 | 1,393 | 817.1 | 1,121.2 | [V q2_rows shape; C Q1.38] |
| load left after the kill, s | 950 | 1,017 | 1,607.9 | 1,289.8 | [V q2_rows shape; C Q1.39] |
| kill to `CvvActive`, s | 1,300.7 | 1,359.8 | 2,068.6 | 1,712.4 | [V q2_rows a.27, b.27; C Q1.40] |
| end of the cool-down to the promotion, s | 301.9 | 302.8 | 450.7 | 400.5 | [V q2_rows a.28, b.28; C Q1.41] |
| observer: first line at distance 1 after its restart, s | 23.3 | 360.4 | 3.7 | 4.5 | [V q2_rows a.29, b.29] |

The kill came earlier into the load in bench 7 and left more load after it, so kill to `CvvActive` is not one number to compare with bench 6's.
In run 7b the export's mark of the promotion falls 11.5 s after the log line [7b A4 recovery rejoin_mark.export_mark_minus_log_s].
Between its start and its promotion validator-05 replayed the kill's epoch (95.4 s in run 7a, 68.2 s in run 7b) and made one rejoin attempt with no demotion line [7a A4 recovery replay_of_epoch5_s, rejoin_attempts, demotion_lines] [7b A4 recovery replay_of_epoch4_s, rejoin_attempts, demotion_lines].
Its rejoin check answered not ready 406 and 363 times; the largest groups were `round_gap` before the fleet's next close (180 and 199) and `epoch_closed` while it still executed an epoch the fleet had closed (126 and 125) [7a A4 recovery rejoin_not_ready_total, rejoin_not_ready_by_phase] [7b A4 recovery rejoin_not_ready_total, rejoin_not_ready_by_phase].
No other validator left `CvvActive` in either run [7a A4 recovery left_cvv_active_outside_v05] [7b A4 recovery left_cvv_active_outside_v05, left_cvv_active_outside_v05_logs].
The observer had all its lines at distance 1 within 41.1 s and 29.9 s of its restart [7a A4 recovery observer_restart] [7b A4 recovery observer_restart].
Measured and not explained: after its promotion validator-05 proposed its first header within a second in both runs, but its first own certificate committed after 1.65 s in run 7a and 59.6 s in run 7b [7a A4 recovery own_after] [7b A4 recovery own_after].
Also not explained: in run 7b validator-04 logged 516 `Failed to track spawned task … no available capacity` errors in under 5 s at 18:45:24, as epoch 5 began [7b A4 census leads.spawn_capacity.by_node.v04]; validator-05 has the same template after its start in both runs (1,347 lines in run 7a, 993 in run 7b) [7b A4 census leads.spawn_capacity.by_node.v05, leads.spawn_capacity.run7a_census].

### 4.8 Census

Every fail-stop phrase the census counts (a stored final state that does not match, a refused closing block, a conflict halt, a fork, a fatal database failure, an output gap and the rest) is zero on every node in both runs [7a A4 census fail_stops, arms_agreement.fail_stop_nodes] [7b A4 census fail_stops, arms_agreement.fail_stop_nodes].
The bare words "panic", "halt" and "fork" occur inside digests, in the `node switches` info line and in the fork-schedule banner; "fatal" occurs only in the error template `fatal request for requested vote` (33 lines in run 7a, 152 in run 7b) and once in run 7b in a warn line naming `penalty=Fatal`; none of these is a fail-stop phrase of the census [7a A4 census words] [7b A4 census words].
No test-hook line appears on any node [7a A4 census arms_agreement.test_hook_lines] [7b A4 census arms_agreement.test_hook_lines].
The error templates new against bench 6's run 2 (the census's one reference, for both runs): `processed certificate that is too new` on validator-05 only, after its start (19,307 lines in run 7a, 438 in run 7b, each with a warn twin of the same count); `error while sealing batch | AntiQuorum` (3 lines on validators 03, 06 and 08 in run 7a; 4 on 03, 07, 08 and 10 in run 7b); `ConsensusOutput channel closed` once on the observer in each run; and in run 7b three task names of the spawn-capacity error (`next-batch` 20 lines, `ProcessGossip-tn-epoch-vote` 2, `sync-batches` 2); the spawn-capacity error itself is not new: bench 6's run 2 logged 1,421 such lines and run 7a's validator-05 1,347 [7a A4 census flagged] [7b A4 census flagged, leads.spawn_capacity.bench6_run2_census, leads.spawn_capacity.run7a_census].
The switch gauges read the arm's values on every validator in both runs, and every node ran the tn-lmdb storage engine [7a A4 census arm_store.gauges_at_arm, store_by_node_arms] [7b A4 census arm_store.gauges_at_arm, store_by_node_arms].
