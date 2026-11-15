## 4. Findings, ranked by what they change

Each finding opens with what it changes.

### 4.1 The form: what the two runs tell apart and what they do not

What it changes: the default form of the vote fix; the repository owner decides, and the form comparison recommends.

The rows the recommendation rests on, one run each.
Run 7a's spread is the range over its own buckets of the same window: 300-s buckets of blast 2, the two buckets that end before its kill for the per-validator rows, 60-s blocks for blast 0.

| Row | Run 7a | Run 7b | Run 7a's spread | Verdict | Cite |
|---|---|---|---|---|---|
| Blast 2 chain tx/s, headline window | 9,289 | 9,337 | 8,344.6-10,544.9 | not told apart from noise | [C Q1.01] |
| Own-header certification, fleet, blast 2 (%) | 95.59 | 95.00 | 93.37-97.29 | not told apart from noise | [C Q1.09] |
| Lowest validator, blast 2 (%) | 83.6 | 76.4 | 55.2-89.3 | not told apart from noise | [C Q1.10] |
| Committed rounds per second, blast 2 (chain) | 2.32 | 2.22 | 1.99-2.73 | not told apart from noise | [C Q1.24] |
| Seen p95, blast 2 (s) | 17.33 | 24.18 | 14.27-18.78 | outside 7a's spread | [C Q1.06] |
| Blast 0 chain tx/s, all-generators window (315 / 358 s) | 698.3 | 680.0 | 688.2-722.8 | outside 7a's spread | [C Q1.04] |
| Before the kill: validator-01 (%) | 100.0 | 89.2 | 99.9-100.0 | outside 7a's spread | [C Q1.11] |
| Before the kill: validator-04 (%) | 94.1 | 99.4 | 90.3-95.4 | outside 7a's spread | [C Q1.12] |
| Before the kill: validator-05 (%) | 100.0 | 90.8 | 99.9-100.1 | outside 7a's spread | [C Q1.13] |
| Before the kill: validator-06 (%) | 62.7 | 79.0 | 55.2-69.5 | outside 7a's spread | [C Q1.14] |
| Before the kill: validator-08 (%) | 86.4 | 99.2 | 77.5-88.4 | outside 7a's spread | [C Q1.15] |

The two "before the kill" windows differ in length: 817 s in run 7a and 1,121 s in run 7b [C q3_hold.windows].
The seen p95 values come from the combined landing documents and their spread from 1-in-100 sampled landings [C Q1.06].
The land tail has no spread to judge against: p95 7.76 / 8.77 s, p99 17.40 / 22.06 s [C Q1.07] [C Q1.08].

Under load most of the headers the adaptive form built over blast 2 lay inside its starved window: 61.5 % of run 7b's headers over blast 2, 59.7 % of those before the kill [C Q4.26] [C Q4.12].
Those shares are measured from the logged policy; on this build the window counts headers built, not rounds [read; a-common §3].
Replayed from the logs, with the replay matching the logged policy on 99.875 % of headers, 56.3 % of the windows before the kill and 89.1 % of those after validator-05's start opened at the 128-header cap [C Q4.29] [C Q4.30].
A return to the own tip lost 1.66 own-tip headers on average, and 64.0 % of returns lost their first header [C Q4.27] [C Q4.28].
What the window bought is a fresher named block: 38.51 % of run 7b's headers named the author's tip against 0.26 % in run 7a, and 54.0 % named the floor against 77.0 % [C Q4.17] [C Q4.15].
The fleet mean distance from the tip to the named block fell from 7.57 to 4.83 block-bearing outputs (run 7a's spread over its nine proposers 6.96-7.95; the fleet median was 8 in both runs) and from 6.77 to 4.45 s at validator-01's output rate [C Q4.21] [C Q4.22].
A lower bound on the named block's age fell from 7.36 to 4.43 s [C Q4.23].
The certified share of tip-basis headers is not told apart from noise: 96.4 % against 98.1 % [C Q4.20].

The per-validator rows move in both directions.
Of the 41 per-bucket rows that lie outside the validator's own run 7a range, 28 are lower in run 7b and 13 higher; the five farthest outside that range, measured against its width, are all validator-01 or validator-05 lower, by 10.6 to 12.0 points [C Q5.34] [C Q5.40] [C Q5.30] [C Q5.11] [C Q5.50], while the largest differences in points are validator-08's rises, up to 22.2 points (77.5 to 99.7 % in bucket 01) [C Q5.47] [C q5_per_validator.outside_7a_bucket_range].
The lagging validators differ: under 98 % over blast 2 were validators 04, 06, 08 and 10 in run 7a and 01, 02, 05, 06 and 10 in run 7b, only 06 and 10 in both [C q5_per_validator.lagging_sets].
The validator slowest to execute was the same in 0 of 8 buckets, the lowest certifier in 5 of 8 [C q5_per_validator.same_slowest_buckets] [C q5_per_validator.same_lowest_cert_buckets].
As in bench 6, the pair does not separate the form from which validators lagged.

The form comparison's recommendation to the repository owner, in its own words [C recommendation]:

> The two runs support keeping the always-on form as the default at 20,000 IOPS: on blast 2's throughput, fleet certification and round rate the forms are not told apart from run 7a's own spread, and the rows outside that spread show the adaptive form naming a fresher block, whose value bench 7 did not measure, with a higher seen p95 and a lower blast-0 rate; it also held more headers and adds code the always-on form does not carry.
> The support is weak: one run of each form on the same build and the same disk, with per-validator rows that move in both directions.

The same page adds that run 7a's spread is variation inside one run, not run-to-run variance, and that no row carries a significance test [C recommendation].
What would change the recommendation, from its own list:

- A second run of each form: rows inside run 7a's spread could flip, and the two rows against the adaptive run, seen p95 and blast 0's rate, could fall inside a second run's spread [C Q1.06] [C Q1.04].
- A run at 50,000 IOPS, where bench 6 found the adaptive form ahead on certification and behind on the senders' cost; bench 7 made no run there [C recommendation].
- A measured cost for the named block's age: if the age costs something, the fresher block is a reason to make the adaptive form the default.
- A run at a floor of 16 outputs, which the per-header arithmetic says leaves no under-held header in either run (§4.3) [7a A3 perheader §8] [7b A3 perheader §8].
- The code: the adaptive form adds the starved window, its 128-header cap and the return to the own tip, which the page counts as a cost with no row behind it.

### 4.2 #1807 with the order hold on

What it changes: whether the order hold goes upstream as it is.

The senders' cost in blast 2 as each generator saw it (bench 6's gap-resend cells: its warm-up start to its cool-down end), one run each; generator 05's validator was the one killed [V q2_senders.window].

| Blast 2 | Run 7a | Bench 6 run 2 | Run 7b | Bench 6 run 3 | Cite |
|---|---|---|---|---|---|
| Gap resends, generators other than 05 | 0 | 29,449 | 0 | 104,168 | [V q2_senders a, b] [C Q2.01] |
| Unlanded after the 180-s tail scan, all / other than 05 | 32 / 0 | 183 / 0 | 2,137 / 0 | 10,767 / 9,290 | [V q2_senders a, b] [C Q2.08] [C Q2.09] |
| Landings seen 300 s or more after submission, all generators | 9,780 | 40,263 | 7,724 | 111,508 | [V q2_senders a, b] [C Q2.11] |

In blast 2, outside generator 05 neither bench 7 run gap-resent or left a transaction unlanded, and no landing was seen 300 s or more after submission [C Q2.01] [C Q2.08] [C Q2.10].
Lost own headers carrying batches still occur in both runs, on all nine validators other than 05, and in both kinds [V q2_senders a, b].
Not certified: 981 / 1,127 headers by the loss analysis's definition, which accepts an own quorum for the same round at any later time, and 1,002 / 1,168 by the certification analysis's, which needs the quorum before the node's next header [7a A7 lost_kinds.by_window.B2.fleet] [7b A7 lost_kinds.by_window.B2.fleet].
Certified but never committed (no validator other than 05 logged the certificate's commit in the whole run): 293 / 356 [7a A7 lost_kinds.by_window.B2.fleet] [7b A7 lost_kinds.by_window.B2.fleet].
Run 7b's counts include validator-05's own headers; without them they are 988 not certified (the loss analysis's definition) and 338 certified but never committed [V q3_hold b].
No gap resend followed any of them, where in bench 6 every gap-resend second of generators 01-04 and 06-10 fell 280-345 s after a lost own header of the generator's own validator: 31 of 31 seconds in run 2, 124 of 124 in run 3 [V q3_hold a, b].

One counter isolates the hold: its out-of-order re-queue counter read 0 in both runs, in the log, the warnings and the export [C Q3.49] [C Q3.50].
It has no bench 6 twin, and it says that no re-queue went out of order on bench 7, not how many would have without the hold [V q3_hold.attribution].
The fall of gap resends, unlanded transactions and `nonce_too_high` skips between the benches is not separable; in the bench 6 comparison's words it moved with "the hold (#1807), the storage engine and the vote path (they moved the rate and the round time, and so how long a lost header's batches wait), the kill earlier into the load in bench 7, bench 6 starting blast 2 with transactions still queued, and sealed_tx_keep / digest_dedupe gone (off on bench 6)" [V q3_hold.attribution].

Run 7a has one exception, in blast 1: one gap episode of 4 transactions on generator 06, whose preamble wait ran its full length, and 4 landings seen 300 s or more after submission [C Q2.14] [C Q2.15] [C Q2.17] [C recommendation].
Its one resend second fell 280-345 s after a lost own header of validator-06, bench 6's pattern [V q3_hold a].
Run 7a's nodes also counted 22 `nonce_too_high` skips (the export's counter), 2 per node on 11 nodes, all in blast 1; run 7b's counted none [C Q2.06] [V q2_senders a, b].
Run 7a's fleet checks print the gap resends as "not 0: 4" and the `nonce_too_high` skips as "not 0: 22" against the plan's "near 0"; run 7b's print both as met [C q3_hold.fleet_checks].

Generator 05 paid in both runs: 9,812 / 8,129 gap resends and 32 / 2,137 transactions unlanded after the tail scan [C Q2.02] [C Q2.09].
The loss analyses found the unlanded to be transactions accepted in the last seconds before the kill and batched by the restarted validator after the tail scan [V q2_senders a, b].
Its 9,780 / 7,724 sightings 300 s or more after submission are late sightings of blocks made before the kill, not late landings: a landing's time is its block's timestamp, a sighting's is when the generator's scanner saw it [C Q2.11] [V q2_senders a, b].

The hold's cost per form, one run each; no row has a spread.

| Blast 2 | Run 7a | Run 7b | Cite |
|---|---|---|---|
| Headers held | 1,866 | 3,259 | [C Q3.36] |
| Held headers that carried a batch | 0 | 0 | [C Q3.37] |
| Longest held run, headers (window) | 21 (before the kill) | 113 (after validator-05's start) | [C Q3.39] |
| Longest held run, s (window) | 9.1 (after validator-05's start) | 55.3 (after validator-05's start) | [C Q3.40] |
| Blocker created, % of headers, fleet | 2.46 | 3.13 | [C Q3.41] |
| Blocker created, % of headers, validator-06 | 6.9 | 15.6 | [C Q3.43] |
| Certified share of held headers (%) | 49.8 | 60.5 | [C Q3.61] |
| Certified share of headers not held (%) | 97.3 | 97.4 | [C Q3.62] |
| Early-trigger candidates (inferred) | 152 | 183 | [C Q3.58] |
| Over-quota reports | 0 | 0 | [C Q3.53] |

Each longest run is validator-06's maximum in a named window; run 7a's two lie in different windows, so they are not one run [C q3_hold.reading].
The windows differ in length: before the kill 817 s and 1,121 s, after validator-05's start 1,308 s and 990 s [C q3_hold.windows].
Held headers certified less often than the rest in both runs; that is an association, and no counter says the hold caused it.
The early-trigger candidates are inferred, not measured: held headers whose digest trigger may have counted held digests, out of 1,110 / 2,056 held headers built on the digest trigger [C Q3.58].
The fleet ran a digest threshold of 5 batches and a minimum header delay of 350 ms, where the hold's review assumed a minimum delay of 1 s [7a A7 early_trigger.fleet_parameters] [7b A7 early_trigger.read].

The plan's fleet check "`headers_held > 0` where headers were lost" fails once in each run, printed as each run has it [C q3_hold.fleet_checks]:

- Run 7a: of 32 (window, validator) cells with blockers created, one shows no increase: validator-06 during validator-05's outage, 1 blocker created, 0 held headers [C q3_hold.fleet_checks].
- Run 7b: validator-05 in blast 0, 18 blockers created and no increase of `tn_primary_headers_held_total`; of its 26 headers with blockers, none had a pending queue, a batch or a held digest, so nothing was queued to hold [C q3_hold.fleet_checks].

### 4.3 Certification fell while throughput rose

What it changes: what the next fix is aimed at.

Against bench 6, one run each, in blast 2's mixed phase before the kill (the throughput row: bench 5's headline window, blast 2's all-generators window with the kill inside); the four before-the-kill windows are 817, 1,477, 1,121 and 1,393 s long [V q3_certification_rounds a, b] [V q2_rows a.01, b.01].

| Before the kill | Run 7a | Bench 6 run 2 | Run 7b | Bench 6 run 3 | Cite |
|---|---|---|---|---|---|
| Blast 2 chain tx/s, headline window | 9,289 | 5,322 | 9,337 | 5,395 | [V q2_rows a.01, b.01] |
| Fleet certification (%; bench 7: the certification analysis's count, bench 6: its rounds analysis's, same window) | 94.0 | 99.94 | 94.95 | 99.56 | [V q3_certification_rounds a, b] |
| Validators other than 05 under 98 % | 4 | 0 | 4 | 0 | [V q3_certification_rounds a, b] |
| Refused-behind answers per minute | 34.8 | 0 | 39.3 | 0.6 | [V q3_vote_path a, b] |
| Superseded answers per minute | 1,199 | 3.5 | 2,089 | 136 | [V q3_vote_path a, b] |
| Rounds with four or more under-held parents (%) | 11.13 | 0.02 | 10.34 | 2.98 | [V q3_certification_rounds a, b] |
| Committed rounds per second, validator-01's own count | 2.54 | 2.81 | 2.46 | 2.78 | [V q2_rows a.18, b.18] |
| Execution lag in rounds, median over validators | 16.96 | 35.65 | 21.36 | 34.0 | [V q3_certification_rounds a, b] |

Throughput rose 74.5 % and 73.1 % while certification fell and the execution lag counted in rounds fell with it [V q2_rows a.01, b.01].
In blast 2 as a whole 5,432 of run 7a's headers (10.31 %) and 6,378 of run 7b's (12.55 %) were under-held: at the proposal at most five other voters held the block they named, validator-05 counting as a voter without it after its start [7a A3 q4u B2.fleet] [7b A3 q4u B2.fleet].
Under-held headers certified 61.25 % and 66.70 % of the time, the rest 99.53 % and 99.06 % [7a A3 q4u B2.fleet] [7b A3 q4u B2.fleet].
By basis, run 7a certified 94.3 % of its floor-basis headers, 99.9 % of its quorum-basis and 96.4 % of its tip-basis headers; run 7b 92.1 %, 99.9 % and 98.1 % [7a A3 q2 B2.fleet] [7b A3 q2 B2.fleet].
The per-header analyses' floor arithmetic holds the measured tips, rounds and cancels fixed and moves only the floor: at a floor of 16 outputs no header in either run would have been under-held (0.00 %) [7a A3 perheader §8] [7b A3 perheader §8].
That is arithmetic on these runs, not a result, and the plan kept the floor at 8.
It would name an older block, whose cost bench 7 did not measure: the mean distance would be 14.71 and 13.81 block-bearing outputs, 13.16 and 12.72 s at validator-01's output rate, against the measured 7.57 and 4.83 outputs, 6.77 and 4.45 s [7a A3 perheader §8] [7b A3 perheader §8].
No counter isolates one change: refused-behind answers and the under-held split divide the lost certification by mechanism, not by the change that moved it [V q3_certification_rounds.attribution].
In the bench 6 comparison's words the certification share is not separable between the "vote-handler rework (refusal rule and timing), the execution lag at the voters (rate x1.75, larger outputs, the storage engine's persist time), the hold (re-times digests and so headers), the adaptive rule change (7b/run 3 only), the shape (kill earlier, bench 6's queued pools)" [V q3_certification_rounds.attribution].

### 4.4 What binds at 20,000 IOPS now

What it changes: where throughput work goes.

The engine and the device in blast 2's mixed phase, one run each [V q3_storage.runs.<run>.engine_b2, .disk.b2].

| Blast 2 | Run 7a | Bench 6 run 2 | Run 7b | Bench 6 run 3 |
|---|---|---|---|---|
| Executed tx/s per node | 9,293 | 5,314 | 9,376 | 5,399 |
| Rate the task's cost allows at full busy, tx/s | 9,500 | 5,343 | 9,582 | 5,420 |
| Engine busy, ms per s (log timeline) | 978.1 | 994.3 | 978.4 | 996.1 |
| Task, µs per transaction | 105.26 | 187.15 | 104.36 | 184.51 |
| Execute, µs per transaction | 54.29 | 90.21 | 54.03 | 89.98 |
| Persist, µs per transaction | 49.42 | 95.25 | 48.78 | 92.85 |
| Commit (part of persist), µs per transaction | 31.93 | 74.17 | 31.36 | 72.01 |
| Persist's share of the task | 0.47 | 0.51 | 0.47 | 0.50 |
| Transactions per output | 8,294 | 3,854 | 8,638 | 4,072 |
| Commit, ms per output | 265.5 | 287.7 | 270.9 | 293.4 |
| Persist, ms per output | 410.9 | 369.5 | 421.4 | 378.3 |
| Device writes per s, share of the 20,000 cap | 0.859 | 0.998 | 0.863 | 0.999 |
| Device writes per transaction | 1.85 | 3.74 | 1.85 | 3.71 |
| Device time per write, ms | 8.50 | 6.88 | 8.67 | 6.77 |
| Bytes written per transaction | 26,132 | 19,288 | 25,498 | 19,119 |

In both runs the engine was busy about 978 ms of every second by the log timeline (982 / 980 ms by Prometheus, median validator) and executed 9,293 / 9,376 tx/s per node (log, mean per node), against the 9,327 / 9,392 tx/s its task cost allows at the Prometheus busy time and 9,500 / 9,582 tx/s at full busy [7a A5 window.2.bound_check] [7b A5 window.2.bound_check] [V q3_storage.runs.<run>.engine_b2].
The cycle is sequential: no execution task started before the previous one ended (0 of 24,447 task starts in run 7a and 0 of 23,554 in run 7b, blast 2), and the task is execute plus persist plus announce plus 2.7 / 2.61 ms on average, so the task's time per transaction sets that rate; persist is 47 % of it [7a A5 engine.md T16] [7a A5 window.2.log_fleet.seq] [7b A5 engine.md T13] [7b A5 window.2.log_fleet.seq] [V q3_storage.runs.<run>.engine_b2].
The device ran at 0.859 / 0.863 of its write cap at 8.50 / 8.67 ms per write, each write carrying 2.74 / 2.68 times bench 6's bytes [V q3_storage.runs.<run>.disk.b2] [V q3_storage.attribution].
Both readings sit below their limits, the engine nearer to its own.
Through blast 2 the store grew and commit per transaction rose with it: from 21.49 to 42.07 µs in run 7a and from 20.32 to 42.34 µs in run 7b between the first and last 300-s bucket, while tn-lmdb's used size went from 1.12 to 2.74 GiB and from 1.11 to 2.72 GiB [7a A5 course.buckets] [7b A5 course.buckets].
Over the same buckets the executed rate fell from 10,470 to 8,393 and from 10,497 to 8,164 tx/s [7a A5 course.buckets] [7b A5 course.buckets].
A least-squares fit over the eight buckets gives 14.3 / 14.9 µs of commit per transaction per GiB used (r² 0.966 / 0.968) and -1,420 / -1,486 tx/s per GiB (r² 0.969 / 0.972); it is a fit, not a mechanism [7a A5 course.fit_*] [7b A5 course.fit_*].
Bench 6 sat at the write cap: its measured rate was 0.997 and 1.000 of the identity rate, cap over writes per transaction, within 0.3 % [V q3_storage.runs.b6r2.identity] [V q3_storage.runs.b6r3.identity].
Per transaction, commit fell to 0.43 / 0.44 of bench 6's and persist to 0.52 / 0.53; per output, commit fell only to 0.92 and save_blocks rose 1.79 / 1.78 times, while transactions per output rose 2.15 / 2.12 times [V q3_storage.attribution].
Device writes per transaction fell to 0.49 / 0.50 of bench 6's while writes per output moved -4.0 % / +2.9 % before the kill; with writes per output barely moving and transactions per output doubled (above), the halving is arithmetic, and nothing isolates which change made the outputs larger [V q3_storage.attribution].
tn-lmdb and storage v2 came in one change (#1834) and are not separable from each other; the device counts take every writer on the boot disk, so the store, the vote-path rework, the hold and the load left after the kill could all move them [V q3_storage.attribution] [7a A6 q10_whole_disk.statement].
