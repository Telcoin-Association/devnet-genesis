### 4.5 The far validators' batches

What it changes: a defect report for the node's maintainers that is not about the order hold.
Validators 02 and 06 are the far validators; "near" is the other eight.
In the light blasts of both bench 7 runs the far validators' generators land a small fraction of what the near generators land: 2 to 10 % of the near median in blast 0, 13 to 14 % in blast 1 [V far_generators_b6 answer_by_blast].
Bench 6's runs 2 and 3 show the same shortfall in blast 0, so it is not new with this build [V far_generators_b6 answer_by_blast].
In blast 1 bench 7's far generators are slower than bench 6's while the near ones are faster: seen p50 16.6-18.2 s against 4.10-5.08 s, and 2.11-2.12 s against 2.67-3.38 s for the near median [V q3_far_validators B1.seen_p50_s].
Every batch-carrying header of 02 and 06 was certified in both light blasts of both bench 7 runs, and 46 to 76 % of them were never committed [V q3_far_validators B0.bh_not_certified, B1.bh_not_certified, B0.bh_cnc_share, B1.bh_cnc_share].
Their digests go back into the proposer's queue on the commit path (`digests resent cause=committed`) a median 50 to 61 rounds after the header that carried them, 21.0 to 21.4 s in run 7b, the one bench 7 run whose file has the delay in seconds [C Q3F.07, Q3F.08, Q3F.17, Q3F.18].
A far batch takes 12.9 to 61.4 s at the median from its first own proposal to execution, against 0.93 to 1.37 s on the near validators [C Q3F.06, Q3F.16].

Validators 02 / 06, with the near median in parentheses, one run each; light blasts' mixed phases. Latency starts at the batch's first own proposal on all four runs. "-": not in the run's file. The near validators' median count of commit-path re-queues is 0 in every cell [V q3_far_validators B0.requeue_events_committed, B1.requeue_events_committed], so the re-queue rows give no near median.

| blast | quantity | bench 6 run 2 | bench 6 run 3 | run 7a | run 7b | cite |
|---|---|---|---|---|---|---|
| 0 | landed rate, tx/s | 10.1 / 10.5 (88.8) | 2.91 / 2.54 (88.8) | 8.76 / 5.47 (88.9) | 2.18 / 1.79 (88.3) | [V q3_far_validators B0.landed_tps; C Q3F.01] |
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
- [read] The commit-path re-queue fires on an own commit notice and re-queues every tracked own header at or below the highest own round committed in it; the notice is sent only when a committed sub-dag holds an own header. The code is the same on both builds: `crates/consensus/primary/src/proposer.rs:942` at 2df831e3c and `:999` at 91a15e223 (the `take_while`), `crates/consensus/primary/src/consensus/state.rs:809-812` on both [V q3_far_validators code_reading]. On bench 6, 127 of 127 commit-path re-queues of 02 and 06 in the light blasts came within 50 ms of the node's own `certificate committed` line [measured; V q3_far_validators reading].
- [measured] The order hold held no header of 02 or 06 in the light blasts of either bench 7 run [C Q3F.10, Q3F.20], and bench 6, which had no hold, shows the same pattern in blast 0 [V q3_far_validators B0.bh_cnc_share]. What bench 7 added on the commit path is bookkeeping that neither gates nor delays the re-queue [read; V q3_far_validators code_reading].
- [inferred] The near validators' next-round headers do not name the late far certificate as a parent, so no leader's sub-dag reaches it until the re-queue. Which parents a header names is not logged on either build.

What is open.
In blast 1 bench 7 commits a smaller share of the far validators' certificates than bench 6 (2.12-3.50 % against 3.96-6.49 %) while each miss costs the same re-queue delay in rounds [V q3_far_validators B1.committed_share_pct, B1.requeue_rounds_p50].
No counter isolates what moved that share.
The candidates are the upstream vote-handler rework (when far votes and certificates form), the near validators' speed on the new storage engine (the eight propose the next round sooner) and the round rate, which barely moved: 2.83-2.84 own headers per second against 2.80-2.81 [V q3_far_validators B1.headers_per_s]; none is concluded.
The far validators had no leader slot in blast 1 of either bench 7 run, against 0.48-1.72 % in bench 6 [V q3_far_validators B1.leader_share_pct]; the schedule's reputation counts votes that the vote-handler rework and the near round rate move, which is a lead, not a finding [V q3_far_validators differences].
