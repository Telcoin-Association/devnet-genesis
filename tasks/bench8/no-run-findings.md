# Bench 8: what the saved data say before any run, and what that changes in Step 5

Private, written 2026-11-16 from six read-only analyses, for the owner and for the units that build and analyse bench 8.
Sources, all under `benchmark/private/bench8-prep/`: `N0/plan-figures.md` (the check of the plan's own figures) and `N1/findings.md` to `N5/findings.md`; every figure names the file and key it came from there, and other paths are under `benchmark/private/` unless they say otherwise.
Measured against the plan `/home/drtnarg/.claude/plans/glistening-dancing-boole.md`, "Context" (the paragraph "Open from bench 7") and "Step 5".
Runs: 7a = r20261115-1131 (always-on), 7b = r20261115-1653 (adaptive), bench 6's 1351 = r20261113-1351 (always-on) and 2118 = r20261113-2118 (adaptive); one run per form in each bench.
Windows, UTC, 2026-11-15 unless named: 7a's load blast before the kill 13:27:58-13:41:35Z (817 s); 7b's 18:25:20-18:44:01Z (1,121 s), and its first 817 s 18:25:20-18:38:57Z.
Light blast 1: 7a 13:03:11-13:19:05Z (954 s), 7b 18:09:19-18:15:33Z (374 s); light blast 0 (N5 only): 7a 12:50:21-12:57:06Z, 7b 17:56:45-18:02:47Z.
Bench 6 before the kill, 2026-11-13: 1351 15:16:22-15:40:59Z (1,477 s), 2118 22:45:46-23:08:59Z (1,393 s).
Validator-05 is alive in every window; every time is a node's own log clock, and offsets between nodes were not measured.
Under-held: a header whose named execution block at most 5 other voters held at the proposal (by their logged tip), so at most 6 of 10 with the author, below the quorum of 7 (N0 row 7).
Lag6: the proposer's tip minus the 6th-highest other voter's tip, in block-bearing outputs, per header (N0 row 6); far = validators 02 and 06, near = the other eight.

## 1. In five sentences

[measured] Before the kill most lost headers were under-held (5.51 of 7a's 6.00 lost points, 4.10 of 7b's 5.08; N0 row 2), and the voters that lacked the block were the same three to five validators for minutes at a time, 3-5 block-bearing outputs behind at p50 (N1).
[measured] Those validators had the highest execute cost per transaction while every executor was saturated (busy 980-1,009 ms per s from the load blast's first minute, against 852-894 ms per s and no queue in light blast 1 at about 9,430 tx/s), and the set changed over the blast (N4).
[measured] A lagging voter held its answer up to about 1,000 ms and mostly answered `superseded`, but the header was dead before that: none was certified when the voter completing the quorum needed at least the author's interval to its next header, 0 of 992 (7a) and 0 of 792 (7b) (N1, N2).
[measured] The own-chain order hold did not amplify the loss (N3), and the far validators' uncommitted certificates are a commit problem apart from the certification loss (N5).
The data do not say why those validators' execution falls behind (cause or effect of the higher cost), when each vote reached its author, what `superseded` and the 1,000 ms cap mean in code, or how far node clocks differ, and every conclusion rests on one run per form.

## 2. The plan's figures, corrected (N0)

| the plan said | the data say | source |
|---|---|---|
| certification before the kill fell "from 99.94 / 99.56 % to 94.0 / 94.95 %" | bench 6's two figures come from the rounds analysis, bench 7's from the certification analysis; the certification analysis alone gives 99.96 / 99.56 / 94.00 / 94.95, and the per-header analysis 93.997 % (7a, 1,246 lost; certification analysis 1,245) and 94.922 % (7b, 1,400 lost; 1,392) | N0 rows 1a-1d and "1 note": `bench6-r20261113-2118/R/rounds.json .pairs["20,000 IOPS"].certified_pct_prekill`, `bench7-<run>/A2/numbers.json .tables["blast 2 mixed before kill"].fleet`, `bench7-<run>/A3/q4u-<run>-B2-prekill.json` |
| under-held headers explain "4.1 of run 7b's 5.05" lost points | 4.10 holds, but against the per-header analysis's own 5.08 (1,400 lost = 4.10 under-held + 0.98 rest); 5.05 is the certification analysis's loss; the under-held share of the loss is 81 % in 7b against 92 % in 7a (6.00 = 5.51 + 0.49) | N0 row 2: `A3/q4u-<run>-B2-prekill.json .authors[*]` |
| light blast 1 "99.92 / 99.85 % certified" | 7a's 99.92 holds (99.91 in the certification analysis); 7b's fleet figure is 99.90 % (per-header, 11 lost of 10,720) or 99.93 % (10,713 of 10,720); 99.85 % is the share of 7b's light-blast headers that were not under-held; 3,269 of 10,720 (30.49 %) were under-held and all certified | N0 rows 3b, 3c: `bench7-r20261115-1653/A3/perheader.md` line 206 and §2 B1 "all"; `A2/numbers.json .tables["blast 1 mixed"]` |
| yardstick "run 7a's spread of fleet certification, 93.37-97.29 %" | 300-s buckets of 7a's whole load blast (n = 8, fleet-pooled), not 60 s and not per validator; it is the spread of the whole-blast row (95.59 / 95.00 %); only buckets 00-01 end before the kill (93.93, 93.37 %), buckets 02-07 hold or follow it | N0 row 4: `bench7-r20261115-1131/A2/numbers.json .tables["blast 2 bucket 00".."07"].fleet.cert_pct` |
| "Read: the window before the kill and the load blast's first 817 s" | 817 s is 7a's pre-kill window only (kill 13:41:35.100Z, 817.1 s in); 7b's kill came 1,121.2 s in (18:44:01.162Z); no earlier analysis computed 7b's first 817 s, and N1-N4 now do | N0 row 5: `bench7-<run>/A4/recovery.json .kill` `kill_into_b2_mixed_s` |
| "execution tips spread more than 8 outputs apart under the load blast" | not a stored figure; as lag6 > 8: 2,508 of 20,758 headers in 7a (12.08 %, exactly the under-held count) and 2,420 of 27,571 in 7b (8.78 %; 7b's 3,036 under-held also count tip-named headers); p90 9 / 8, never above 16; it is three or four voters lagging the proposer by 9-16 outputs, not a fleet-wide spread, and they differ between the runs; a voter's tip can read up to one header interval low | N0 row 6: `N0/scripts/a6_tip_spread.py` on `benchmark/work/bench7-scratch/<run>-A3/perheader-B2-prekill.pkl` |

The four pre-kill windows have four lengths (1,477, 1,393, 817 and 1,121 s): compare shares, not counts (N0 row "1 windows").

## 3. N1 to N5

### N1: who lacked the block
Question: per under-held header, which voters lacked the named block, by how many outputs and for how long, and how does bench 6 compare?
[measured] In both bench 7 runs the same three to five voters lacked the block for 10-19 minutes at a stretch, 3-5 outputs behind at p50, and they are the validators with the highest execution lag in rounds; the set differs between 7a and 7b (only 07 in both) and in 7a never includes the far validator 06.
[measured] The quorum's deficit decides the header, and a voter 3-8 outputs behind holds its answer about 1,000 ms and answers `superseded`; only 13-18 % of the lacking pairs are an artefact of the logged tip, against 69 % in bench 6's 2118, where the lag was 1 output and harmless.
- 7a, 2,508 under-held of 20,758: 05 and 07 lack on 100.0 %, 10 on 95.1 %, deficit p50 4 / 3 / 4 outputs, catch-up p50 2.63 / 1.83 / 2.53 s; 7b, 3,036 of 27,571: 09 98.3 %, 02 97.5 %, deficit p50 4 / 5, catch-up p50 2.86 / 3.99 s [measured; unit headers; `N1/n1-figures.json .lacking.<7a|7b>-prekill.voters`].
- Certified share by the quorum's deficit: 1 output 81.03 % (7a) / 80.72 % (7b), 2 outputs 28.78 / 32.80 %, 3-4 outputs 11.24 / 11.43 % [measured; unit headers; `.quorum_deficit.<w>.quorum_deficit`].
- Voters 3-8 outputs behind: `prelock_wait_ms` p50 1,000 ms, `superseded` on 93.1 % (7a) / 93.7 % (7b) of answers [measured; unit first joined answer per voter per header; `.prelock.<w>.groups`]; the fields' meaning in code is [inferred].
- Lacking pairs at most 2 outputs behind and caught up by the voter's next line: 13.3 % (7a), 18.4 % (7b), 69.1 % (2118) [measured; unit (header, lacking voter) pairs; `.lacking.<w>.def_le2_and_next_line`].
One run per form: whether the form or chance chose which validators lag cannot be told.

### N2: the certified share of under-held headers against the lagging voters' wait
Question: does the certified share of under-held headers fall with the wait of the voter that completes the quorum, on one curve in the light and the load blast?
[measured] Before the kill both runs follow one curve, and its cut-off is the author's next header (author interval p50 0.37-0.43 s), not the voter's 1-s wait: no under-held header was certified when the deciding voter needed at least that interval.
[measured] The light blast cannot test the curve (7a's had no under-held header of 27,448; 7b's 3,269 all had a deciding wait of at most 100 ms and all were certified), and on lost under-held headers the lagging voters answer `superseded`, rarely `behind`.
- Certified share by deciding (7th-holder) wait: 0-100 ms 97.6 % (7a) / 94.8 % (7b), 500-1,000 ms 34.5 / 41.4 %, over 1,000 ms 4.6 / 4.3 % [measured; unit under-held headers; `N2/n2-figures.json F.s12.<7a|7b>.windows.B2-prekill.curve.log`].
- Slack (author's interval to its next header minus the deciding wait) at or below 0: 0 of 992 (7a) and 0 of 792 (7b) certified; above 250 ms 97.7 / 94.8 % [measured; `F.s2b.<tag>.windows.B2-prekill.by_slack`].
- Non-holders' answers on lost under-held headers: `superseded` 86.0 % (7a) / 79.7 % (7b), `behind` 3.7 / 4.4 % [measured; unit voter answers; `F.s34.<tag>.groups.lost_under.answers_nonholder`].
- Lost though not under-held: 102 of 18,250 (7a) and 271 of 24,535 (7b), each with at least 6 other voters answering `created`; `held` > 0 on 68.6 / 54.6 % of them against 0.46 / 2.48 % of the certified [measured; `F.s34.<tag>.groups.lost_not_under`].
Comparisons between 7a and 7b rest on one run each.

### N3: does the order hold turn one lost header into a run of losses?
Question: per author, does the first loss come before the first held header, and are held headers lost more than not-held ones at equal holder counts?
[measured] The hold follows the loss: 75.8 % (7a) and 61.7 % (7b) of held headers are the author's first header after a loss, and held headers are lost at 0.94-0.99 times the rate of not-held headers of the same author, distance from the last loss and holder count.
[measured] Bench 7's loss runs are long and 1351's short, but 1351 had only 11 headers with six or fewer holders, so that comparison measures the execution spread, not the hold [attribution inferred]; the one possible cost is validator-06's headers at exactly six holders, at most 0.05 (7a) to 0.16 (7b) points.
- Held headers (`held` > 0): 790 of 20,758 (7a), 1,651 of 27,571 (7b), 1,266 of 20,281 (7b's first 817 s) [measured; unit headers; `N3/figures.json s0_counts`].
- Observed against expected losses of held headers, by author × own headers since the last loss × holder bin: 466 / 496.5 = 0.94 (7a), 684 / 694.4 = 0.99 (7b), 575 / 591.8 = 0.97 (7b's first 817 s) [measured; `N3/figures.json` §2 keys `s2_holders`, `s2b_since_loss`, `s2c_per_bin`].
- Lost after a lost own header 73.84 % (7a), 54.68 % (7b), 4.35 % (1 of 23, 1351); the header after a loss was lost 65.1 % when held against 81.9 % when not (7a), 51.9 against 62.2 % (7b) [measured; `s3_runs`, `s5_derived`].
- Validator-06 at six holders: +10.8 headers over expectation in 7a (0.05 points), 127 lost against 83.1 expected in 7b (+43.9, 0.16 points); every held header carried no batch (790 of 790, 1,651 of 1,651) [measured; §2 keys and `s4_shape`].
Every conclusion rests on one run per form.

### N4: the course over the load blast
Question: does the under-held share track the lagging validators' commit cost as the store grows, and what does bench 6's engine course look like at the same point?
[measured] Every executor is saturated from the load blast's first minute; the spread-type under-held share is 0.00 % in that minute, reaches its working level within 2-4 minutes and then moves between 5 and 26 % per minute without a trend for 35 minutes while the store triples and the commit cost per transaction doubles.
[measured] In each 300-s bucket the validators that are behind are those with the highest execute cost per transaction, by 1-4 µs/tx from minute 2 on, a gap that does not grow, and the set changes over the blast; [inferred] this points at the load against execution capacity, the store acting, if at all, by lowering capacity.
- Light blast 1, 60-120 s: 9,432 (7a) / 9,435 (7b) tx/s, busy 852-894 / 859-894 ms per s, queue wait 9.5-15.0 / 11.7-35.9 ms, lag6 > 8 on 0.00 %; load blast minute 1: 11,638 / 12,043 tx/s, busy 991-1,007 / 980-1,009, queue 1,625-6,261 / 3,425-5,231 ms [measured; unit validator and bin; `N4/n4-figures.json .7a_B1_vs_B2`, `.7b_B1_vs_B2`].
- Spearman between each validator's execute µs/tx and its share of headers more than 8 outputs behind the proposer: 0.76-0.95 in all 16 300-s buckets of both runs [measured; `.7a.b300`, `.7b.b300` `spearman_execute_vs_gt8`].
- 7a's whole load blast (13:27:58-14:08:23Z, 2,425 s): commit 21 → 42 µs/tx, task 95 → 118 µs/tx, others' tx/s 10,478 → 8,192; under-held against the laggards' commit cost -0.28 per 60 s, -0.31 per 300 s [measured; `.7a.b300`, `N4/s3-7a-B2.json .stats60/.stats300`].
- 1351 was saturated too (busy 986-1,001 ms per s per 300 s) at 5,365-6,097 tx/s, yet its under-held share stayed at 0.01 % with task costs within 0.3-1.6 % of each other, against 3-8 % and queue waits 91-463 % apart in bench 7 [measured; `.b6_1351`, `N4/s5-spread.json`].
Every conclusion rests on one run per form.

### N5: the far validators' last step
Question: after a far certificate of round r that was certified and never committed, did a committed near header of round r+1 name every certificate of round r (which would make #1870's inferred step false)?
[measured] None did: of 10,524 such far certificates in six windows, no committed near r+1 header named all of round r, and the 83,830 committed near r+1 headers after them were created before the far certificate formed at its author (90.0 %) or at most 126 ms after.
[measured] In the light blasts far certificates are certified 99.6 % of the time and 70-91 % are never committed, a commit symptom; a second, smaller path exists in 7b's load blast, where 5 far certificates named by the other far validator's committed header stayed uncommitted because a later own certificate committed first.
- Certified and never committed, share of far certificates: 7a light blast 1 80.79 %, 7b 70.01 %; load blast before the kill 22.88 % (7a), 2.60 % (7b); near under 1 % everywhere [measured; unit certificates (author, epoch, round); `N5/n5-figures.json J:<run>.windows.<win>.far`, `J:derived.<run>/<win>`].
- Totals over six windows: 10,524 certificates, 83,830 committed near r+1 headers, 0 contradictions [measured; `J:derived.totals_six_windows`].
- Committed near r+1 headers created more than 150 ms after the far quorum: 0 of 83,830 after an uncommitted far certificate, 1.8-11.0 % after a committed one [measured; `committed_near_r1_created_gt_150ms_after_qr`]; that a certificate reaches a near node about 0.15 s after it forms is [inferred].
- Skip path: 8 certified, uncommitted certificates in 7b's load blast followed by a committed r+1 header naming all of round r, a later own certificate committed first in 8 of 8 [measured; `J:7b.windows.B2-prekill.all_authors_anomaly`]; that `order_dag_inner` skips them is read from code at 91a15e223 (`crates/consensus/primary/src/consensus/utils.rs:58-65`).
One run per form; the light-blast pattern is the same in both forms.

## 4. Where the five agree and where they pull apart

N1 and N4, the same voters or a changing set.
N1 measured 3-5 voters lacking the block for 10-19 minutes before the kill, the set moving "on a scale of several minutes, never minute to minute" (7b: 04 leads minutes 0-2, 02 and 09 from minute 3, 04 again in minutes 15-18; `N1 .lacking.<w>.minutes`).
N4 measured that the validators behind are the costliest by execute µs/tx in each 300-s bucket, and that the set changes over the whole blast, most clearly across the kill (7a most behind {10, 05, 07} in the first bucket, {06, 01, 09} in the first after the kill, {02, 03, 07} in the last; `N4 most_behind3`, `costliest3_execute`).
Both can be true: lasting minutes and not fixed for the run are one picture at two time scales, and N4's most-behind three in 7a's first bucket, {10, 05, 07}, are N1's three.
They part on cost stage: N1 finds 7a's four laggers lowest on commit µs/tx and on flushes per output and reads that as possibly a consequence of running behind, N4 finds them 2-8 % higher on execute µs/tx; neither can tell cause from effect.
A trap for readers: N1 has 7a's validator 10 lacking on 43-45 % of its headers in minutes 0-5 while N4 has 7a's under-held share at 0.00 % in minute 1; one lacking voter does not make a header under-held, so the two figures do not conflict [inferred from the definitions].

N2 and N1, what ends a lagging voter's answer.
N1 measured that a voter 3-8 outputs behind holds its answer about 1,000 ms (`prelock_wait_ms` p50 1,000) and needs p50 2.6-3.2 s to catch up, so it answers `superseded`.
N2 measured that the header is dead before that: with the author's next header at p50 0.37-0.43 s, no under-held header whose deciding voter needed the author's interval or more was certified (0 of 992 / 792), and `superseded` answers carry prelock p10 593 / 693 ms, p50 1,000 ms.
Both are true: the 1,000 ms hold exists but does not bind; the author's next header comes first and decides.
They agree that a longer voter wait would not help (N1: eleven or more header intervals needed; N2: a vote after the author's next header is superseded whatever the wait), and N2 adds that a shorter one would cost no measured certificate [inferred].
Neither read the vote handler: that `prelock_wait_ms` is the execution wait and what `superseded` means are [inferred] in both.

N3 and N2, `held` > 0 on the lost headers that were not under-held.
N2 measured, unstratified, `held` > 0 on 68.6 % (7a) / 54.6 % (7b) of the lost not-under-held headers against 0.46 / 2.48 % of the certified ones, with `own_parent` false and the `parents_and_threshold` reason, 14-200 times their rate among certified headers.
N3 measured the same kind of excess when stratifying by holder bin only (O÷E 1.82 in 7a, 2.66 in 7b), and showed it goes once headers are compared at equal author, distance from the last loss and holder count (0.94-0.99), because held headers are mostly the author's first header after a loss.
They do not contradict: `held` > 0 marks a header built right after its author lost one, and losses come in runs (lost after lost 73.84 / 54.68 %), so N2's association is the loss run; N3's direct check agrees (after a loss, held lost 65.1 / 51.9 %, not held 81.9 / 62.2 %).
They meet at validator-06: 96 of 7a's 102 and 194 of 7b's 271 lost not-under-held headers are 06's (N2), and N3's only excess is 06's headers at exactly six holders (O÷E 1.19 / 1.53).
N3 bounds that excess at 0.05 / 0.16 points against a not-under-held loss of 0.49 / 0.98 points (N0 row 2), so the hold could explain at most part of that remainder, and nothing in the voters' answers separates held from not held there [measured; mechanism not known].

N5 and N2, the far validators.
N5 measured a commit symptom: far certificates certified 99.6 % in the light blasts and 70-91 % never committed, against 22.88 % (7a) / 2.60 % (7b) uncommitted in the load blast before the kill; it concludes that this does not explain 94.0 / 94.95 %.
N2 measured a certification symptom on the same authors in the load blast: at a deciding wait of at most 100 ms, far authors' under-held headers were certified 84.4 % (7a) / 65.9 % (7b) against 100 / 99.5 % for near ones, and 100 of 7a's 102 lost not-under-held headers are 02's and 06's.
N5's own counts show it too: 4,145 far headers and 3,366 certified (7a), 5,514 and 4,924 (7b) before the kill (`J:<run>.windows.B2-prekill.far`), and N1 gives 06's certified share in 7a as 62.7 % (`.voter_context.7a.per_validator.*.a2.cert_pct`).
Both are true: the far validators have two symptoms, uncommitted certificates in the light blasts (a commit problem, N5) and lost certificates under load (part of the certification loss, N2), and N5's "separate from the certification loss" holds for the first only.
N2 reads the second as travel to and from 02 and 06 acting besides execution [inferred]; 06 never lacks the block as a voter in 7a (N1).

## 5. What this changes in Step 5 (for the owner to accept or not)

| the plan | what the findings say | proposed change |
|---|---|---|
| run 1, F: floor 16; at least 99.0 % with under-held under 1 % → R | lag6 never exceeded 16 before the kill in either run, so floor 16 would have put every pre-kill header within a quorum's reach [inferred, N1 from N0 row 6]; certified share rises with holders, 0 / 26.5 / 71.0 % at 3 / 4 / 5 holders in 7a [measured association, N2 `by_holders_at_proposal`]; F does not touch the not-under-held loss, 0.49 (7a) / 0.98 (7b) points (N0 row 2) | F stands as run 1; read its not-under-held loss apart, since a 7b-sized remainder alone would leave 99.02 % (100 - 0.98), at the 99.0 % bar |
| read "the window before the kill and the load blast's first 817 s" | 817 s is 7a's pre-kill window, 7b's is 1,121 s (N0 row 5); 7b's first 817 s gives the same picture as its full window in N1, N2, N3 (0.97) and N4 (94.24 % certified, 12.32 % under-held, against 94.92 / 11.01 %); the share settles within 2-4 minutes and has no trend (N4) | read the whole pre-kill window, its length named; use the first 817 s only beside 7a; compare shares, not counts |
| yardstick for "between": 93.37-97.29 %, branch bounds 97.3 and 99.0 % | 300-s buckets of 7a's whole blast; before the kill only 93.93 and 93.37 %; pre-kill shares 94.00 (7a) / 94.95 % (7b) in the certification analysis; per 60 s 7a's minutes 1-13 span 88.99-99.88 % (`N4/s1-7a-B2.json .b60`), too wide to judge one run (N0 row 4) | take the bench 7 reference from the pre-kill window (94.00 / 94.95 %) and restate the lower bound on that unit; no bench 7 pre-kill window share or pre-kill 300-s bucket reached 97.3 % |
| at most 97.3 %: run H (no hold), then a voter-wait parameter | H: held headers are not lost more at equal author, distance and holders (0.94-0.99), a hold cost at most 0.05-0.16 points (N3), against moving H ahead of R; voter wait: 0 of 992 / 792 certified once the deciding wait reached the author's interval, answers `superseded` with `behind` 4 % (N2), laggers need p50 2.6-3.2 s (N1); N2 names the lever: keep an under-held header open at its author past its next header (lost headers' deciding wait p50 1.17 / 0.89 s) | drop the voter-wait parameter; the next run in this branch is one of: N2's keep-open change (a node change the bench 8 build does not carry), H only to read 06's six-holder figure (7b 59.0 % held against 75.1 % not held, N3), or a run chosen from the new engine fields on why 3-5 nodes run 21-30 rounds behind (N1); the owner chooses |
| run 2, R at about 5,300 tx/s (void outside 4,500-6,500), `BENCH_SENDERS=300`, `BENCH_WINDOW=3` | would show whether the build makes the spread far below saturation, the plan's "at least 5 %" branch [inferred]; would not show the store's effect on capacity: saturating at 5,300 tx/s needs task cost above about 189 µs/tx (1 s / 5,300), and 7a's rose to 118 over 2,425 s (N4 arithmetic applied) [inferred]; bench 6's 1351, on a different store engine, was saturated at 5,365-6,097 tx/s (N4) | keep as one option |
| R at about 9,400 tx/s instead (N4) | light blast 1 at 9,432 / 9,435 tx/s already had 10-15 % headroom, no queue, lag6 > 8 on 0.00 % (N4); would also test the store: saturation once task cost passes about 106 µs/tx, which 7a reached about 1,200 s into its blast; a spread that appears only once busy nears 1,000 ms per s says the store acts through capacity [inferred, N4]; would not give a clean "no spread" if saturation comes mid-run, and light blast 1 held about 9,400 tx/s for only 342-346 s (N0 row 3a) | lay out both for the owner; at 9,400 the void band and the launch file's senders and window change (the harness has no pacing option) |
| run C (control repeat) first when F lands between | which validators lag (N1), 7b's twice-7a not-under-held loss (N2) and the far uncommitted share 22.88 / 2.60 % (N5) all rest on one run per form; the always-on pre-kill share has one value (94.00 %) | C keeps its branch; it is also the only planned run that would give a second always-on pre-kill figure, the run-to-run spread no yardstick has now |
| run 1's light blasts settle the far step through `parents` | no committed near r+1 header named all of round r after 10,524 uncommitted far certificates; the step stays [inferred] until `parents` or a certificate-arrival line names them; a second, skip-rule path exists (N5) | no change; also read the skip path, which needs a line the build does not add (section 6) |

## 6. Fields the units asked for, against the bench 8 build

| field asked for | by | covered by | NOT covered |
|---|---|---|---|
| per-output execute and commit time, per node, per minute | N1, N4 | `execute_ms`, `commit_ms`, `store_bytes` on the engine's output lines | N1 says no such series is saved; N4 built one from saved per-output extracts (`benchmark/work/bench7-scratch/<run>-A5/x/`) |
| queue depth on `output executed` (outputs waiting to execute) | N1 | `outputs_behind`, if it counts outputs waiting (not stated in the sources) | possibly |
| the voter's tip at a request's arrival and at its answer | N1, N2, N3, N4 | `exec_tip_arrival`, `exec_tip_answer`, `exec_deficit_outputs` and histogram on `vote path timing` | – |
| each vote's arrival at its author, or the time of the sixth vote | N2 | `vote_arrivals`, `vote_errors`, `votes_at_end` on the author's round-end line | – |
| `parents` on `header proposed` | N5 | `parents` | – |
| a far certificate's arrival at each near node | N5 | `certificate accepted` (`round`, `origin`, `round_certs`, `parents_sent`, `late_ms`) | – |
| on a `superseded` answer, the round and digest of the superseding header | N3 | – | node |
| a line when the order hold releases a lane (`round`, `lanes`, `waited_ms`, cause cancel or commit) | N3 | – | node |
| a line when the sub-dag ordering skips a parent (`origin`, `round`, `last_committed[origin]`) | N5 | – | node |
| CPU time beside wall time on `output executed` | N4 | – | node |
| persist's lock or queue wait on `persisted output` (`commit_ms` is not it) | N4 | – | node |
| per-node clock offsets (chrony tracking samples) | N0, N1, N2, N4, N5 | – | harness |
| host steal time per minute | N4 | – | harness |
| the generators' per-minute submit counts | N4 | – | harness |
| worker count per node in the run's record | N3 | – | harness |
| `output execution task finished` extracted for every validator (saved only for 05) | N2 | – | analysis extraction step |

The next node unit's input: the superseding header's round and digest on `superseded`, the order-hold release line, the sub-dag skip line, CPU time beside wall time and persist's wait on the engine lines.
The next harness unit's input: per-node clock offsets, host steal time per minute, the generators' per-minute submit counts and each node's worker count.

## 7. Open questions no saved data and no planned field answer

Why the lagging validators' execution falls behind, and whether their 2-8 % higher execute cost is cause or effect (host contention, cache state, their own proposer work); CPU and steal time would narrow it (N1, N4).
Why bench 6's per-validator task costs stayed within 0.3-1.6 % of each other while execute costs differed by 5-9 % (N4).
Why every validator's execute cost jumps between the load blast's minute 1 and minute 2 (7a 49.2 → 58.6 µs/tx) while transactions per output fall (8,767 → 7,106) (N4).
What makes the loss runs: a loss raises the next header's loss from about 21 % to 68-76 % at five or fewer holders, and the hold is not it (N3).
Why 7b loses twice 7a's share of not-under-held headers (1.10 against 0.56 %), with only associations (the starved policy, author 10) and one run per form (N2).
What caused 7a's one-minute dip at 2,040-2,100 s into its load blast (others' executed tx/s 7,460) (N4).
Whether the form or chance sets which validators lag: that needs more runs, not a field (N1).
Whether the hold has a small cost: per-header comparison rules out a large effect only; a run with the hold off tells (N3).
Two are code reads, not data: what `superseded` means and what caps `prelock_wait_ms` near 1,000 ms (the vote handler at 91a15e223; N1, N2), and the far validators' selection rule (`bench7-r20261115-1653/A2/scripts/far_b7.py`, unread; N0).
