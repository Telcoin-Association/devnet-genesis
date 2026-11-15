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
| Blast 0 chain tx/s | 698.3 | 680.0 | 688.2-722.8 | outside 7a's spread | [C Q1.04] |
| Before the kill: validator-01 (%) | 100.0 | 89.2 | 99.9-100.0 | outside 7a's spread | [C Q1.11] |
| Before the kill: validator-04 (%) | 94.1 | 99.4 | 90.3-95.4 | outside 7a's spread | [C Q1.12] |
| Before the kill: validator-05 (%) | 100.0 | 90.8 | 99.9-100.1 | outside 7a's spread | [C Q1.13] |
| Before the kill: validator-06 (%) | 62.7 | 79.0 | 55.2-69.5 | outside 7a's spread | [C Q1.14] |
| Before the kill: validator-08 (%) | 86.4 | 99.2 | 77.5-88.4 | outside 7a's spread | [C Q1.15] |

The two "before the kill" windows differ in length: 817 s in run 7a and 1,121 s in run 7b [C q3_hold.windows].
The seen p95 values come from the combined landing documents and their spread from 1-in-100 sampled landings [C Q1.06].
The land tail has no spread to judge against: p95 7.76 / 8.77 s, p99 17.40 / 22.06 s [C Q1.07] [C Q1.08].

Under load the adaptive form spent most of blast 2 in its starved window: 61.5 % of the headers run 7b built over blast 2 lay inside one, 59.7 % before the kill [C Q4.26] [C Q4.12].
Those shares are measured from the logged policy; on this build the window counts headers built, not rounds.
Replayed from the logs, with the replay matching the logged policy on 99.875 % of headers, 56.3 % of the windows before the kill and 89.1 % of those after validator-05's start opened at the 128-header cap [C Q4.29] [C Q4.30].
A return to the own tip lost 1.66 own-tip headers on average, and 64.0 % of returns lost their first header [C Q4.27] [C Q4.28].
What the window bought is a fresher named block: 38.51 % of run 7b's headers named the author's tip against 0.26 % in run 7a, and 54.0 % named the floor against 77.0 % [C Q4.17] [C Q4.15].
The distance from the tip to the named block fell from 7.57 to 4.83 block-bearing outputs (run 7a's spread over its nine proposers 6.96-7.95) and from 6.77 to 4.45 s at validator-01's output rate [C Q4.21] [C Q4.22].
A lower bound on the named block's age fell from 7.36 to 4.43 s [C Q4.23].
The certified share of tip-basis headers is not told apart from noise: 96.4 % against 98.1 % [C Q4.20].

The per-validator rows move in both directions.
Of the 41 per-bucket rows that lie outside the validator's own run 7a range, 28 are lower in run 7b and 13 higher, the largest all on validator-01 or validator-05 lower [C q5_per_validator.outside_7a_bucket_range] [C recommendation].
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
- A run at a floor of 16 outputs, which the per-header arithmetic says leaves no under-held header in either run (§4.3).
- The code: the adaptive form adds the starved window, its 128-header cap and the return to the own tip, which the page counts as a cost with no row behind it.

### 4.2 #1807 with the order hold on

What it changes: whether the order hold goes upstream as it is.

The senders' cost in blast 2, one run each; generator 05's validator was the one killed.

| Blast 2 | Run 7a | Bench 6 run 2 | Run 7b | Bench 6 run 3 | Cite |
|---|---|---|---|---|---|
| Gap resends, generators other than 05 | 0 | 29,449 | 0 | 104,168 | [V q2_senders a, b] [C Q2.01] |
| Unlanded after the 180-s tail scan, all / other than 05 | 32 / 0 | 183 / 0 | 2,137 / 0 | 10,767 / 9,290 | [V q2_senders a, b] [C Q2.08] [C Q2.09] |
| Landings seen 300 s or more after submission, all generators | 9,780 | 40,263 | 7,724 | 111,508 | [V q2_senders a, b] [C Q2.11] |

Outside generator 05 neither bench 7 run gap-resent, left a transaction unlanded or saw a landing 300 s late [C Q2.01] [C Q2.08] [C Q2.10].
Lost own headers carrying batches still occur in both runs, on all nine validators other than 05, and in both kinds [V q2_senders a, b].
Not certified: 981 / 1,127 headers by the loss analysis's definition, which accepts an own quorum for the same round at any later time, and 1,002 / 1,168 by the certification analysis's, which needs the quorum before the node's next header [7a A7 lost_kinds.by_window.B2.fleet] [7b A7 lost_kinds.by_window.B2.fleet].
Certified but never committed: 293 / 356 [7a A7 lost_kinds.by_window.B2.fleet] [7b A7 lost_kinds.by_window.B2.fleet].
Run 7b's counts include validator-05's own headers; without them they are 988 and 338 [V q3_hold b].
No gap resend followed any of them, where in bench 6 every gap-resend second of generators 01-04 and 06-10 fell 280-345 s after a lost own header of the generator's own validator: 31 of 31 seconds in run 2, 124 of 124 in run 3 [V q3_hold a, b].

One counter isolates the hold: its out-of-order re-queue counter read 0 in both runs, in the log, the warnings and the export [C Q3.49] [C Q3.50].
It has no bench 6 twin, and it says that no re-queue went out of order on bench 7, not how many would have without the hold [V q3_hold.attribution].
The fall of gap resends, unlanded transactions and `nonce_too_high` skips between the benches is not separable; in the bench 6 comparison's words it moved with "the hold (#1807), the storage engine and the vote path (they moved the rate and the round time, and so how long a lost header's batches wait), the kill earlier into the load in bench 7, bench 6 starting blast 2 with transactions still queued, and sealed_tx_keep / digest_dedupe gone (off on bench 6)" [V q3_hold.attribution].

Run 7a has one exception, in blast 1: one gap episode of 4 transactions on generator 06, whose preamble wait ran its full length, and 4 landings seen 300 s or more after submission [C Q2.14] [C Q2.15] [C Q2.17] [C recommendation].
Its one resend second fell 280-345 s after a lost own header of validator-06, bench 6's pattern [V q3_hold a].
Run 7a also logged 22 `nonce_too_high` skips, 2 per node on 11 nodes, all in blast 1; run 7b logged none [C Q2.06] [V q2_senders a, b].
Run 7a's fleet checks print both as not met [C q3_hold.fleet_checks].

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

- Run 7a: of 32 (window, validator) cells with blockers created, one shows no increase: validator-06 during validator-05's outage, 1 blocker created, 0 held headers.
- Run 7b: validator-05 in blast 0, 18 blockers created and no increase of `tn_primary_headers_held_total`; of its 26 headers with blockers, none had a pending queue, a batch or a held digest, so nothing was queued to hold.
