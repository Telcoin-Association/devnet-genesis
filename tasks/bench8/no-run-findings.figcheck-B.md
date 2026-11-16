# Figure-check B of `tasks/bench8/no-run-findings.md`, sections 4-7 (lines 87-164)

Checker N-FC-B, 2026-11-16, read-only. Sources: `benchmark/private/bench8-prep/` N0-N5 findings and JSON files, the plan's Step 5 (`/home/drtnarg/.claude/plans/glistening-dancing-boole.md` lines 89-120), `tasks/bench8/briefs/n-sum.md` point 6 and `b8-1.md` to `b8-7.md` (with `b8-1b.md`, `b8-2b.md`).
Paths below are relative to `benchmark/private/bench8-prep/` unless they say otherwise.

## Verdict

FIX: three figures in section 4 are wrong or mislabelled, one "covered by" cell in section 6 misdescribes its brief, two "by" cells miss N3, and five section-6 rows plus two sentences went stale when briefs b8-2b, b8-6 and b8-7 were extended at 10:40, three minutes after the summary (10:37); no conclusion changes.

## Errors

1. Section 4, "N1 and N4", the trap sentence.
Text: "N1 has 7a's validator 10 lacking on 43-45 % of its headers in minutes 0-5 while N4 has 7a's under-held share at 0.00 % in minute 1".
Source: `N1/n1-figures.json .lacking.7a-prekill.minutes[0]` is the minute N4 calls minute 1 (13:27:58Z, 1,712 headers, under_held 0), and there 10's share is 33.1 %; 43-45 % holds for minutes 1-5 (45.2, 45.0, 43.1, 44.8, 42.7). N1 counts minutes from 0, N4 from 1 (`N4/findings.md` §1: minute 1 = 1,712 headers). N1's findings line ("minutes 0-5 (lacking on 43-45 %)") carries the same slip; the JSON is the source. The share's denominator is the headers 10 voted on, not 10's own headers.
Replacement: "N1 has 7a's validator 10 lacking on 43-45 % of its headers in minutes 0-5 while N4 has 7a's under-held share at 0.00 % in minute 1" → "N1 has 7a's validator 10 lacking on 33.1 % of the headers it voted on in N1's minute 0 (43-45 % in minutes 1-5) while N4 has 7a's under-held share at 0.00 % in that same minute, N4's minute 1 (N1 counts minutes from 0, N4 from 1)".
The conclusion of the sentence (one lacking voter does not make a header under-held) stands.

2. Section 4, "N1 and N4", the 7b sequence.
Text: "(7b: 04 leads minutes 0-2, 02 and 09 from minute 3, 04 again in minutes 15-18;".
Source: `N1/n1-figures.json .lacking.7b-prekill.minutes[3]`: 04 58.9 %, 02 36.2 %, 09 29.0 % (04 still leads); minute 4: 02 57.3, 04 55.1, 09 43.6; from minute 5 to 14 02 and 09 are the top two; minutes 15-18 04 leads (85.9-100 %). N1's findings ("02 and 09 take over from minute 3") have the same slip.
Replacement: "(7b: 04 leads minutes 0-2, 02 and 09 from minute 3, 04 again in minutes 15-18;" → "(7b: 04 leads minutes 0-3, 02 from minute 4, 02 and 09 the top two in minutes 5-14, 04 again in minutes 15-18;".

3. Section 4, "N1 and N4", the cost-stage sentence.
Text: "N1 finds 7a's four laggers lowest on commit µs/tx and on flushes per output and reads that as possibly a consequence of running behind, N4 finds them 2-8 % higher on execute µs/tx".
Source: `N1/findings.md` §4: the four laggers are the four lowest on commit µs/tx, but on flushes per output it is "the three deepest laggers" (7a 10, 05, 07), and the "may be a consequence of running behind" reading is attached to the flushes bullet only. `N4/findings.md` "Definitions": N4's laggards are N0's sets (7a 05, 07, 10; 7b 09, 02, 04), three not four, and the 2-8 % is minute 2 to the kill over both runs (`N4/n4-figures.json .7a.laggard_minus_other_execute_us_60s`, minutes 2-13: 0.91-3.78 µs/tx).
Replacement: "N1 finds 7a's four laggers lowest on commit µs/tx and on flushes per output and reads that as possibly a consequence of running behind, N4 finds them 2-8 % higher on execute µs/tx" → "N1 finds 7a's four laggers lowest on commit µs/tx and the three deepest (10, 05, 07) lowest on flushes per output, and reads the flushes as possibly a consequence of running behind; N4 finds its laggards (7a 05, 07, 10; 7b 09, 02, 04) 2-8 % higher on execute µs/tx from minute 2 to the kill".

4. Section 6, row "queue depth on `output executed`".
Text: "`outputs_behind`, if it counts outputs waiting (not stated in the sources)".
Source: `tasks/bench8/briefs/b8-6.md` line 13 states what it counts: "how many consensus outputs are queued behind this one when it finishes, log it; if it does not, say so and skip it". The open point is whether the engine knows the number, not what the field counts.
Replacement: "`outputs_behind`, if it counts outputs waiting (not stated in the sources)" → "`outputs_behind` (b8-6: the consensus outputs queued behind this one when it finishes; logged only if the engine knows the number)".

5. Section 6, two "by" cells miss N3.
N3's "What the saved data cannot tell" asks for "on the certifier, the time the quorum was reached against the arrival of the author's next header" (the sixth vote's time) and says "Clocks: node clocks; offsets not measured".
Replacement: "| each vote's arrival at its author, or the time of the sixth vote | N2 |" → "| each vote's arrival at its author, or the time of the sixth vote | N2, N3 |".
Replacement: "| per-node clock offsets (chrony tracking samples) | N0, N1, N2, N4, N5 |" → "| per-node clock offsets (chrony tracking samples) | N0, N1, N2, N3, N4, N5 |".
Every other ask in the six units' "cannot tell" sections has a row (checked one by one; the code reads sit in section 7).

6. Sections 5, 6 and 7, stale against briefs written after the summary (not a writing error: the summary is 10:37, `b8-2b.md`, `b8-6.md` and `b8-7.md` are 10:40, b8-6's two fields marked "Added 2026-11-16 from the no-run analyses").
The five "NOT covered: node" rows are now briefed, all but the digest:
- "| on a `superseded` answer, the round and digest of the superseding header | N3 | – | node |" → "| on a `superseded` answer, the round and digest of the superseding header | N3 | `superseded_by_round`, `superseded_after_ms` on `vote path timing` (b8-2b) | the digest |"
- "| a line when the order hold releases a lane (`round`, `lanes`, `waited_ms`, cause cancel or commit) | N3 | – | node |" → "| a line when the order hold releases a lane (`round`, `lanes`, `waited_ms`, cause cancel or commit) | N3 | `order hold released` (b8-7) | – |"
- "| a line when the sub-dag ordering skips a parent (`origin`, `round`, `last_committed[origin]`) | N5 | – | node |" → "| a line when the sub-dag ordering skips a parent (`origin`, `round`, `last_committed[origin]`) | N5 | `subdag parent skipped` (b8-7) | – |"
- "| CPU time beside wall time on `output executed` | N4 | – | node |" → "| CPU time beside wall time on `output executed` | N4 | `cpu_ms` (b8-6) | – |"
- "| persist's lock or queue wait on `persisted output` (`commit_ms` is not it) | N4 | – | node |" → "| persist's lock or queue wait on `persisted output` (`commit_ms` is not it) | N4 | `commit_wait_ms` (b8-6) | – |"
- "The next node unit's input: the superseding header's round and digest on `superseded`, the order-hold release line, the sub-dag skip line, CPU time beside wall time and persist's wait on the engine lines." → "The node rows are now briefed: b8-2b (the superseding header's round, not its digest), b8-6's added `cpu_ms` and `commit_wait_ms`, and b8-7 (the order-hold release and sub-dag skip lines)."
- Section 5, last row: "no change; also read the skip path, which needs a line the build does not add (section 6)" → "no change; also read the skip path from b8-7's `subdag parent skipped` line (section 6)".
- Section 7, first item: "CPU and steal time would narrow it (N1, N4)." → "CPU time (b8-6's `cpu_ms`, now planned) and steal time would narrow it (N1, N4)."
The "N2's keep-open change (a node change the bench 8 build does not carry)" claim still holds: no brief b8-1 to b8-7 (nor b8-1b) carries it.

## Not traceable

None beyond weak item 5 (a judgment attributed to N0 row 4 that N0 does not make).

## Weak

1. Section 4, "N3 and N2": "N3's only excess is 06's headers at exactly six holders (O÷E 1.19 / 1.53)".
The O÷E is the six-holder bin over all authors (`N3/figures.json s2c_per_bin.<w>.6` O_over_E 1.185 / 1.529); N3 attributes the excess to 06 through its share of the losses (69 of 69, 121 of 127).
Replacement: "N3's only excess is 06's headers at exactly six holders (O÷E 1.19 / 1.53)" → "N3's only excess is at exactly six holders (O÷E 1.19 / 1.53, all authors), and it is 06's: 69 of 69 (7a) and 121 of 127 (7b) of those held headers' losses".

2. Section 4, "N3 and N2": "and nothing in the voters' answers separates held from not held there [measured; mechanism not known]".
N3 (`N3/findings.md` §2, `s2d_votes`): "Nothing here separates the groups beyond the vote count itself" (created votes per header 6.20 vs 6.61 in 7a, 6.57 vs 6.67 in 7b).
Replacement: → "and nothing in the voters' answers separates held from not held there beyond the vote count itself (created votes per header 6.20 against 6.61 in 7a, 6.57 against 6.67 in 7b) [measured; mechanism not known]".

3. Section 4, "N3 and N2": "so N2's association is the loss run".
N2's lost not-under-held headers sit mostly at six holders (7a: 69 of N2's 70 held ones; 7b: 127 of 148), and that is exactly where N3's stratified comparison still shows an excess (1.19 / 1.53), not 0.94-0.99.
Replacement: "so N2's association is the loss run" → "so N2's association is mostly the loss run (at six holders, where most of these headers sit, N3 still finds 1.19 / 1.53)".

4. Section 4, "N5 and N2": the quote "separate from the certification loss" is not N5's wording; N5 ("What this decides", bullet 2) says "a commit problem, not a certification one".
Replacement: "N5's \"separate from the certification loss\" holds for the first only" → "N5's \"a commit problem, not a certification one\" holds for the first only".

5. Section 5, yardstick row: "too wide to judge one run (N0 row 4)".
N0 row 4 says only that the yardstick is 300-s buckets of the whole blast, fleet-pooled, and that only buckets 00-01 end before the kill; it makes no judgment on 60-s shares. The 60-s span itself (88.99-99.88 %) is right (`N4/s1-7a-B2.json .b60`, minutes 1-13).
Replacement: "too wide to judge one run (N0 row 4)" → "too wide to judge one run [inferred; N0 row 4 says only that the yardstick is 300-s buckets of the whole blast]".

6. Section 5, run 1 row: "F does not touch the not-under-held loss".
N1 ("What this decides", bullet 1): "what it does to the 102 (7a) and 271 (7b) lost headers that were not under-held is not addressed by it"; no unit measured that F leaves them alone.
Replacement: "F does not touch the not-under-held loss, 0.49 (7a) / 0.98 (7b) points (N0 row 2)" → "N1's floor argument does not address the not-under-held loss, 0.49 (7a) / 0.98 (7b) points (N0 row 2)".

7. Section 5, run 2 row: the plan's first R branch is missing.
Plan line 115: "under-held under 1 % and at least 99.0 % → the cause is the spread of execution tips at full load; stop"; the summary states only the "at least 5 %" branch. Every other plan row (F floor 16; at least 99.0 % with under-held under 1 % → R; at most 97.3 % → H then a voter-wait parameter; between → C; R at about 5,300 tx/s, void outside 4,500-6,500, `BENCH_SENDERS=300`, `BENCH_WINDOW=3`; run 1's light blasts and `parents`) matches the plan.
Replacement: "| run 2, R at about 5,300 tx/s (void outside 4,500-6,500), `BENCH_SENDERS=300`, `BENCH_WINDOW=3` |" → "| run 2, R at about 5,300 tx/s (void outside 4,500-6,500), `BENCH_SENDERS=300`, `BENCH_WINDOW=3`; under-held under 1 % and at least 99.0 % → stop, under-held at least 5 % → H |".

8. Section 5, run C row: "it is also the only planned run that would give a second always-on pre-kill figure".
Plan line 108: every run is the control shape (bench 7's always-on run with the kill) with one change, so F, R and H also give always-on pre-kill figures; C is the only one of the unchanged configuration.
Replacement: → "it is also the only planned run that would give a second pre-kill figure of the unchanged always-on configuration".

9. Section 5, "at most 97.3 %" row: "N2 names the lever: keep an under-held header open at its author past its next header" carries no mark; N2 ("What this decides", bullet 3) marks it [inferred].
Replacement: "N2 names the lever: keep" → "N2 names the lever [inferred]: keep".

## Rule breaches

None: the text is private, so unit names and paths are allowed; no host, person or attribution.

## Checked and right (with the JSON opened)

Section 4: N1 longest runs 10-19 minutes (`.lacking.<w>.minutes_in_set`); catch-up 3-8 outputs p50 2.56 / 3.23 s (`.catch_s_by_deficit`); 06's certified share 62.7 % (`.voter_context.7a.per_validator.06."a2.cert_pct"`); N4 `most_behind3` {10, 05, 07} / {06, 01, 09} / {02, 03, 07} for 7a's buckets 0, 3 (first after the kill) and 7; N2 slack 0 of 992 / 792 (`s2b.<w>.windows.B2-prekill.by_slack`), superseded prelock p10 593 / 693, p50 1,000 (`s12…answer_waits_by_outcome.superseded`), far at ≤ 100 ms 84.43 / 65.88 % against near 100 / 99.52 %, lost not-under-held 102 / 271 with 06 at 96 / 194 and `held_gt0` 70 / 148 against 83 / 602 certified, ratios 13.9-202 ("14-200"); N3 O÷E 0.938 / 0.985, lost after lost 920 / 1,246 and 765 / 1,399 (73.84 / 54.68 %), next header held 390 / 599 and 528 / 1,018 against not held 530 / 647 and 237 / 381, excess 10.8 / 43.9 = 0.052 / 0.159 points; holder-bin-only 1.82 / 2.66 re-derived from N3's table cells (E 256.5 / 258.7; no JSON key holds it); N5 far 4,145 / 3,366 and 5,514 / 4,924, uncommitted 770 / 3,366 = 22.88 % and 128 / 4,924 = 2.60 %, light-blast far certified 99.58-99.66 %.
Section 5: lag6 never above 16 (N0 row 6); holders 0 / 26.5 / 70.97 % (`s12.7a…by_holders_at_proposal`); 100 − 0.98 = 99.02; 7b first 817 s 94.24 / 12.32 % against 94.92 / 11.01 % (N4 §1); 300-s pre-kill buckets 93.93 / 93.37 (A2, via N0) and 7b's 94.46 / 94.63 / 94.39 (`N4 .7b.b300`), so none reached 97.3 %; 1 s / 5,300 = 189 µs, 1 s / 9,400 = 106 µs; light blast 1 9,432 / 9,435 tx/s, busy 852-894 ms per s (10.6-14.8 % headroom); 342 / 346 s (N0 row 3a); laggers 21-30 rounds behind (N1 §4: 21.4-30.1); "the harness has no pacing option" (plan 5c).
Section 7: every figure matches N3 or N4 findings; `far_b7.py` exists under `bench7-r20261115-1653/A2/scripts/`.
Marks: the [measured] / [inferred] marks of sections 4-5 match the units' except weak item 9.

## Counts

Checked: 102 figures (section 4: 46, section 5: 45, section 7: 11) and 16 field rows (section 6).
Matched: 99 of 102 figures; 9 of 16 field rows as written.
Wrong: 3 figures (errors 1-3); 1 field description (error 4); 2 "by" cells (error 5); 5 field rows and 2 sentences stale since 10:40 (error 6).
Untraceable: 0 figures; 1 attributed judgment (weak 5).
Plan rows: 6 checked, 5 stated as the plan has them, 1 omitted (weak 7).
Weak: 9.
