# Figure-check FC-1: §2 (s2.md) and §3 (s3.md)

FIX: two wrong items and nine weak ones. None of them changes a conclusion or a verdict of the form comparison.

## Counts

| section | figures checked | match | wrong | untraceable | weak |
|---|---|---|---|---|---|
| §2 `tasks/bench7/report/s2.md` (lines 1-118) | 288 | 282 | 1 | 0 | 5 |
| §3 `tasks/bench7/report/s3.md` (lines 1-118) | 344 | 339 | 1 | 0 | 4 |

How the figures were counted: each number, time, id, digest, commit, name and quoted line counts once, and each one inside a table cell counts separately (zone names and series names too).
The known points are settled as follows. Run 7b's idle is 5.7 min in all three places, the same as V `q1_same_shape.facts.7b.idle_deploy_to_blast_min`; C `Q1.37`'s note still says 5.6, but the text does not use it.
Run 7b's partial series follow the CORRECTION line of RF 7b.
The fleet-check rows match each run's `fleet_checks[0..10]`: three not met in run 7a, one in run 7b.
Bench 6's kill offsets (1,477 and 1,393 s) and its pools at the start of blast 2 (b6r2: v04 36, v06 682; b6r3: v06 831, v07 575, v08 681, v09 266, v10 147) match `q1_same_shape.facts`.
The image digest, node commit 91a15e22376f…, version, `faucet`, `tn-lmdb`, generator digest and commit, and both arms' sha256 and switches match both manifests.
For the 300-s spread, see W-3-8.

## Wrong

W-2-1. s2.md:43, run 7b's archive cell.
Text: "`ARCHIVE_VERIFY ok=1 files=626 problems=0`, 19:39:59".
File: RF 7b ("Archive:" line) quotes it as `ARCHIVE_VERIFY ok=1 run=r20261115-1653 files=626 bytes=2632212196 objects=626 problems=0`. The values are right, but the code-quoted line drops three of its fields, so it is not verbatim.
Replacement cell: "`ARCHIVE_VERIFY ok=1 run=r20261115-1653 files=626 bytes=2632212196 objects=626 problems=0`, 19:39:59".

W-3-1. s3.md:19.
Text: "Blast 1 has no all-generators window in run 7a (§2), and the KPI file computes no average, best 60 s or block rate on one for it".
File: 7a A1 `.runs[0].blasts[1].bench5_defs.caveats` names only "average and best-60-s chain throughput not computed". The same block holds `.bench5_defs.kpis.blocks_per_sec` = 13.986 for run 7a's blast 1. That rate is not over an all-generators window (the window is null), while run 7b's 35.832 is over its 346 s.
Replacement: "Blast 1 has no all-generators window in run 7a (§2), and the KPI file computes no average or best 60 s for it [7a A1 .runs[0].blasts[1].bench5_defs.caveats]; the file's blast-1 block rate, 14.0 blocks/s, is not taken over such a window and is left out of the table [7a A1 .runs[0].blasts[1].bench5_defs.kpis.blocks_per_sec]."

## Untraceable

None.

## Weak

K-2-1. s2.md:10.
Text: "The closing-block check has no switch; it ran in both runs [orch l.99]."
File: orch l.99 holds only "(The closing-block check has no switch.)". That the check ran in both runs comes from 7a A7 `fleet_checks[5].value` ("results other than `ok`: none; `mismatch`: none; 11 nodes") and 7b A7 `fleet_checks[5].value` ("other results none; mismatch none on 11 nodes").
Replacement: "The closing-block check has no switch [orch l.99]; it ran in both runs, with no result other than `ok` on 11 nodes [7a A7 fleet_checks[5]] [7b A7 fleet_checks[5]]."

K-2-2. s2.md:11.
Text: "A later form of the stack drops `epoch_record_conflict_halt` and its threshold (head 04 rebuilt without them, `b7/n04`) [orch l.964] [orch l.1004]".
File: orch l.964 is a plan ("NEXT: BF-04 (head 04 on N without epoch_record_conflict_halt and its threshold …)"), and l.1004 is a launch ("BF-04a-1 LAUNCHED … head 04's commits 1-20 on N without the conflict halt"). Neither supports the present-tense "drops". The completed work is at orch l.1039: "BF-04a-2 DONE, ACCEPTED … head 04's node part on N = b7/n04 at 8c76745f2".
Replacement: "A later form of the stack, branch `b7/n04` (head 04 rebuilt, at 8c76745f2), drops `epoch_record_conflict_halt` and its threshold [orch l.964] [orch l.1039]; bench 7 ran with the switch on."

K-2-3. s2.md:71.
Text: "The two runs' "before the kill" windows therefore have different lengths, 817 s and 1,121 s [C Q1.38]."
File: the figures match (C `Q1.38` a7a 817.1, b7b 1121.2). The "therefore" is the problem: it follows a sentence about bench 7 against bench 6, but the two bench 7 lengths differ because of the idle (line 69; C `Q1.38` note "the schedule, not the form").
Replacement: "Because the idle differed, the two bench 7 runs' "before the kill" windows have different lengths, 817 s and 1,121 s [C Q1.38]."

K-2-4. s2.md:93.
Text: "the orchestrator's first note named two, and the engine and disk analyses corrected it [RF 7b] [7b A6 export_coverage]".
Rule breach: "the orchestrator" names an assistant role, and the brief allows no attribution of a tool or assistant.
Cite: 7b A6 `export_coverage` holds only four series. From it: validator-01 has write-stall and persist duration absent; validator-05 has save-blocks only from 18:40:00Z; validator-08 has write-stall only to 18:29:45Z; the observer has write-stall, persist duration, save and commit only to 18:58:45Z. All of these match lines 94-97. The counts "four series" (validator-01) and "three series" (validator-05), and validator-08's other series, come from A5 `engine.md` T17 through RF 7b's CORRECTION, not from A6.
Replacement: "Prometheus is partial on three validators and the observer; the run's first notes named two, and the engine and disk analyses corrected them [RF 7b] [7b A5 engine.md T17] [7b A6 export_coverage]:"

K-2-5. s2.md:12, 18, 22, 59, 77.
Text: "bench 6's run 2", "bench 6's run 2", "its runs 2 and 3", the table header "bench 6 run 2 | bench 6 run 3", and "in run 2 and on five in run 3".
Rule breach: a run nickname with no run id nearby. File: V `q1_same_shape.pairs[0].bench6` = r20261113-1351 (run 2) and `pairs[1].bench6` = r20261113-2118 (run 3).
Replacement, line 59: "| | run 7a | run 7b | bench 6 run 2 (r20261113-1351) | bench 6 run 3 (r20261113-2118) |".
Replacement, line 12: "Generator image `sha256:7cefcc50…5a59`, commit 62bbd5f, the commit bench 6's run 2 (r20261113-1351) used [RF 7a] [V q1_same_shape pairs.always.equal]."
Lines 18, 22 and 77 can stay as they are once line 12 has the id.

K-3-1. s3.md:21.
Text: "That difference lies inside run 7a's 60-s blocks with nine or more generators, 9,397.6 to 9,513.9 tx/s: not told apart from noise [C Q1.03]."
File: C `Q1.03` takes its spread from `.runs[0].blasts[1].buckets_60s[*].chain_tps (secs == 60, generators_active >= 9)`, which is a chain rate (every landing, generator 06's included). The two values it is set against are the nine generators' landed rate (`.q4.rows["B1 without generator 06 (600 x 4, nine generators)"].landed_tps`, 9,399.4 and 9,412.2; diff 12.8). The text does not say the two definitions differ.
Replacement: "That difference, 12.8 tx/s, lies inside the spread of run 7a's 60-s blocks of chain tx/s with nine or more generators mixed, 9,397.6 to 9,513.9 tx/s (a chain rate, not the nine generators' landed rate): not told apart from noise [C Q1.03]."

K-3-2. s3.md:24.
Text: "seen p95, 24.18 s against 17.33 s, lies outside run 7a's 300-s spread of 14.3 to 18.8 s [C Q1.06]".
File: C `Q1.06` note says "the spread is from the sampled landings, the values from the combined documents". The text says this only at line 45, not beside the figure (rule 6).
Replacement: "Seen p50 differs by 0.78 s, not told apart from noise [C Q1.05]; seen p95, 24.18 s against 17.33 s from the combined documents, lies outside run 7a's 300-s spread of 14.3 to 18.8 s from the 1-in-100 sample [C Q1.06]."

K-3-3. s3.md:44, also behind line 23.
Text: "The form comparison's yardstick is run 7a's eight full blocks: chain 8,344.6 to 10,544.9 tx/s [C Q1.01]".
File: C `Q1.01` spread is min 8,344.6, max 10,544.9, n 8, from `.runs[0].blasts[2].buckets[*].chain_tps (secs == 300)`. That is blocks 1-8, and block 1 is included even though it holds 9.6 generators on average (`buckets[0].generators_active`).
The KPI analysis's 8,344.6 / 9,221.9 / 10,465.1 is min / median / max over blocks 2-8, the seven with all ten generators (`generators_active` 10.0): 10,465.1 is block 2, 9,221.9 is block 5, and 8,344.6 is block 7.
Both are chain tx/s by block time over 300-s blocks of the merged mixed window. Neither is over the all-generators window (2,375 s) of the 9,288.6 they are compared with. Blast 0's spread (C `Q1.04`) keeps only blocks with all ten generators, so the two rows filter differently.
No verdict changes. The 48.6 tx/s lies inside either spread. Over blocks 2-8, seen p50 runs 8.31-10.90 s and seen p95 14.68-18.78 s, so 0.78 s stays inside and 24.18 s stays outside.
Replacement: "The form comparison's yardstick is run 7a's eight full 300-s blocks, the first (9.6 generators on average) included: chain 8,344.6 to 10,544.9 tx/s [C Q1.01], seen p50 8.28 to 10.90 s [C Q1.05], seen p95 14.27 to 18.78 s [C Q1.06]; over the seven blocks with all ten generators the chain rate runs 8,344.6 to 10,465.1 tx/s, median 9,221.9 [7a A1 .runs[0].blasts[2].buckets[1..7].chain_tps], and no verdict changes."

K-3-4. s3.md:112, the check column.
Text: "switch gauges on 11 nodes (at idle)", printed for both runs.
File: 7a A7 `fleet_checks[7].wording` is "switch gauges on 11 nodes (at idle)", but 7b A7 `fleet_checks[7].wording` is "switch gauges on 11 nodes". The values and verdicts match.
Replacement cell: "switch gauges on 11 nodes (run 7a's wording adds "(at idle)")".
