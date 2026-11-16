# Figure-check A of `tasks/bench8/no-run-findings.md`, lines 1-86 (head, sections 1-3)

Checker N-FC-A, 2026-11-16, read-only. Sources: `benchmark/private/bench8-prep/N0/plan-figures.md`, `N1..N5/findings.md` and their JSON files (keys opened with small scripts under the scratch directory; no unit script was re-run, because no JSON key disagreed with its findings file).
Sections 4-7 belong to checker B and were not checked.

## Verdict

FIX: six errors and two weak items, none of which changes a conclusion of the text.

## Errors

1. Section 2, row "light blast 1", phrase "99.85 % is the share of 7b's light-blast headers that were not under-held".
   The text says 99.85 % of the headers were not under-held; N0 row 3c says 99.85 is the certified share of the headers that were NOT under-held (7,440 of 7,451; 3,269 of 10,720 were under-held, so 69.51 % were not).
   Replacement: `99.85 % is the share of 7b's light-blast headers that were not under-held` → `99.85 % is the certified share of 7b's light-blast headers that were not under-held`.

2. Section 3, N3, bullet "Validator-06 at six holders".
   The text gives 127 lost against 83.1 expected (+43.9) as validator-06's; `N3/figures.json s2c_per_bin.7b-prekill."6"` has O 127, E 83.1 for the held six-holder headers of all authors (404 headers), of which validator-06 has 302 headers and 121 losses (`held_by_author_n_lost."6"` = [302, 121]; validator-10 adds 6, validator-02 1). In 7a all 69 losses are validator-06's (124 of 142 headers), so the 7a half holds. N3's own Answer carries the same label ("validator-06's headers at exactly six holders (7b: 127 lost against 83.1 expected)"); its §2 has the split.
   Replacement: `- Validator-06 at six holders: +10.8 headers over expectation in 7a (0.05 points), 127 lost against 83.1 expected in 7b (+43.9, 0.16 points);` → `- Held headers at exactly six holders, nearly all validator-06's (124 of 142 in 7a with all 69 losses, 302 of 404 in 7b with 121 of the losses): +10.8 headers over expectation in 7a (0.05 points), 127 lost against 83.1 expected in 7b (+43.9, 0.16 points);`

3. Section 3, N4, bullet "Light blast 1, 60-120 s", its source bracket.
   The light-blast figures (9,432 / 9,435 tx/s, busy 852-894 / 859-894 ms per s, queue 9.5-15.0 / 11.7-35.9 ms) are cited to `.7a_B1_vs_B2`, `.7b_B1_vs_B2`; those keys hold light blast 1's first minute (`B1_first60`, 0-60 s: 8,907.3 / 9,233.4 tx/s, busy 744.9-774.2 / 758.2-792.8). The 60-120 s figures are in `N4/s5-spread.json ."7a-B1".minute2` and `."7b-B1".minute2` (the same data as `n4-figures.json .cost_spread_backlog`), and the load-blast queues in `s5-spread.json ."<7a|7b>-B2".first."60"`. Every value matches there.
   Replacement: `` [measured; unit validator and bin; `N4/n4-figures.json .7a_B1_vs_B2`, `.7b_B1_vs_B2`]`` → `` [measured; unit validator and bin; light blast `N4/s5-spread.json ."7a-B1".minute2`, `."7b-B1".minute2`; load blast `N4/n4-figures.json .7a_B1_vs_B2.B2_first60`, `.7b_B1_vs_B2.B2_first60`, queues `N4/s5-spread.json ."<7a|7b>-B2".first."60"`]``

4. Head, line 10, phrase "Validator-05 is alive in every window".
   N4's whole-load-blast figures in section 3 (the 35-minute course, "each 300-s bucket", "all 16 300-s buckets", "7a's whole load blast (13:27:58-14:08:23Z, 2,425 s)") span validator-05's kill at 817.1 s (7a) and 1,121.2 s (7b); N4 "Definitions" drops it from both groups in and after the kill bin and says post-kill under-held is not comparable with pre-kill. 7b's whole blast is 18:25:20-19:05:31Z (2,411 s, N4 "Definitions").
   Replacement: `Validator-05 is alive in every window;` → `Validator-05 is alive in every window except N4's whole-load-blast series (7a 13:27:58-14:08:23Z, 2,425 s; 7b 18:25:20-19:05:31Z, 2,411 s), which span its kill (N4 drops it from both groups from the kill bin on);`

5. Section 3, N4, second sentence, phrase "by 1-4 µs/tx from minute 2 on".
   N4 §2-3: "From minute 2 to the kill the gap is 0.91-3.78 µs/tx (7a) and 0.91-4.22 (7b)" (N0's laggard sets against the others). After the kill the same series (`n4-figures.json .<7a|7b>.laggard_minus_other_execute_us_60s`) runs -1.95 to 2.16 (7a) and -0.58 to 3.63 (7b), and the post-kill 300-s buckets give 0.2-0.9 µs/tx. N4's Answer has the same "from minute 2 on".
   Replacement: `by 1-4 µs/tx from minute 2 on, a gap that does not grow` → `by 1-4 µs/tx from minute 2 to the kill (N0's laggard sets against the others), a gap that does not grow`

6. Section 3, N4, first sentence, phrase "then moves between 5 and 26 % per minute without a trend for 35 minutes".
   The spread-type share (`n4-figures.json .<7a|7b>.lag6_gt8_60s_series_pct`) is below 5 % in 7a minutes 14-17 (2.14, 0.63, 0.00, 3.51; the kill), 36-37 (0.00, 2.59) and 41, and in 7b minutes 3, 13 (1.90), 18-23 (1.50 to 0.00; the kill), 31 and 41; the maximum is 25.80 / 25.64. N4 §1 calls these resets; N4's Answer gives 5-26 % without them.
   Replacement: `and then moves between 5 and 26 % per minute without a trend for 35 minutes` → `and then moves between 5 and 26 % per minute without a trend for 35 minutes, apart from minutes at 0-4 % around the kill and when the input dipped (7a minutes 14-17 and 36-37, 7b minutes 18-23; N4 §1 "Resets")`

## Not traceable

- No figure. The plan path on line 5 and the plan's wording quoted in section 2's first column were not opened (the plan is not among the allowed sources); every quoted plan figure matches N0's quotation of it.
- Carried from N0 without opening N0's own sources (A2, A3, A4): 95.59 / 95.00 % (row 4), 13:41:35.100Z and 18:44:01.162Z (row 5), p90 9 / 8 (row 6). They match N0.

## Weak

1. Section 1, second sentence: "against 852-894 ms per s and no queue in light blast 1".
   N4's Answer says "a queue of 10-36 ms in light blast 1", and the text's own N4 bullet gives 9.5-15.0 / 11.7-35.9 ms (N4 §5 also says "no queue", so the unit is inconsistent).
   Replacement: `and no queue in light blast 1` → `and a queue of only 10-36 ms in light blast 1`

2. Section 3, N5, second sentence, marked [measured]: "stayed uncommitted because a later own certificate committed first".
   N5 §3c measures only the order ("a later certificate of the same author was committed before the naming header was", `skip_rule_consistent` 8 of 8) and marks the causal reading [inferred], via the skip rule read from code.
   Replacement: `stayed uncommitted because a later own certificate committed first` → `stayed uncommitted after a later own certificate had committed first (the skip rule as the cause is [inferred])`

## Rule breaches

None. The text is private, so unit names and paths are allowed.

## Marks

Every [measured] / [inferred] mark in lines 1-86 matches its unit's mark, except Weak 2.

## Notes (no change needed)

- Section 2 row 6 says "tip-named headers" where N0 row 6 says "tip-basis headers"; N4 §5 also uses "tip-named". Same meaning as far as the sources show; the orchestrator may align the two terms.
- N3's "121 of 127" (findings §2) against `held_by_author_n_lost`, whose losses sum to 128 for the six-holder bin of 7b: O = 127 leaves out held headers without a comparator. The replacement in Error 2 says "121 of the losses" to stay true either way.
- "Section 2 row 5: N1-N4 now do [compute 7b's first 817 s]": confirmed in all four units (N1 `.lacking.7b-first817`, N2 "7b first 817 s" rows, N3 `7b-first817`, N4 "7b first 817 s" totals).
- Rounding: N4's 7b light-blast 9,434.5 tx/s and 858.5 ms per s appear as 9,435 and 859 (half up); N4 stats300 -0.305 appears as -0.31.

## JSON keys opened

- N1 `n1-figures.json`: `.lacking.<7a|7b>-prekill.voters.<v>` (share, `def_p50`, `catch_s_p50`), `.lacking.<w>.def_le2_and_next_line`, `.quorum_deficit.<w>.quorum_deficit`, `.prelock.<w>.groups["under-held, lacking 3-8"]`.
- N2 `n2-figures.json`: `s12.<t>.windows.B2-prekill.curve.log`, `s2b.<t>.windows.B2-prekill.by_slack`, `s34.<t>.groups.lost_under.answers_nonholder` (shares recomputed: 86.0 / 3.7 %, 79.7 / 4.4 %), `s34.<t>.groups.lost_not_under` against `cert_not_under`.
- N3 `figures.json`: `s0_counts.*.xtab_n_lost` (held > 0: 790, 1,651, 1,266), `s2b_since_loss.*.OE_held_vs_not_author_x_since_x_holders`, `s2c_per_bin.*."6"|"<=5"`, `s5_derived.*`.
- N4 `n4-figures.json`: `.7a_B1_vs_B2`, `.7b_B1_vs_B2`, `.<7a|7b>.b300[*].spearman_execute_vs_gt8` (0.762-0.946), `.<t>.lag6_gt8_60s_series_pct`, `.<t>.laggard_minus_other_execute_us_60s`, `.<t>.stats_join`, `.b6_1351`; `s3-7a-B2.json .stats60/.stats300` (-0.279 / -0.305); `s5-spread.json` (task 3.2-8.2 %, queue 90.7-463.3 % in bench 7; task 0.3-1.6 % in 1351).
- N5 `n5-figures.json`: `derived.totals_six_windows` (10,524; 83,830; 75,460 before the quorum = 90.0 %), `derived.<run>/<win>` (far certified 99.58-99.66 % in the light blasts; control > 150 ms 1.80-11.02 %), `<run>.windows.<win>.far`, `.far_cnc` (latest 0.126 s), `7b.windows.B2-prekill.all_authors_anomaly`.

## Counts

About 290 figures and stated relations checked (a range counts once): 282 matched, 6 wrong (four mislabelled counts or windows, one wrong key, one wrong statement), 2 weak, 0 untraceable figures.
