# Figure-check of the bench 6 maintainers' summary

Text: `tasks/bench6-maintainer-summary.md` (93 lines, 1,499 words by `wc -w`).
Checked 2026-11-14 15:29 UTC against the allowed sources only.
R = `tasks/bench6-report-r20261113-1351.md`; C = `benchmark/private/bench6-r20261113-2118/A7/comparison.md`; P = the bench 7 plan (`here-is-a-summary-lively-dolphin.md`); F = `benchmark/private/bench7-prep/design/issue-1807-findings-from-bench-6.md`.
Fact 1 and fact 2 are the two facts from the launch prompt (proposer.rs on main equals 165e3fe01; main's unconditional stored-record guard, #1834).

## Verdict

FIX

Every number in the text matches its source line; no figure is wrong.
The errors are labels, scope and definitions: one statement about bench 7 contradicts fact 2, and the headline table's definition lines and two confirmed findings are wider than their sources.
None changes a conclusion.

## Errors

1. §5 "Why bench 7 is a new number", the phrase "and the epoch-record closing-block check and collector hardening switched on".
   The text says both are switched on, which gives the closing-block check a switch.
   Fact 2: on main the closing-block check extends the unconditional stored-record guard of #1834 and has no switch (P:25 records that guard; P:96 "extend upstream's guard where it is unconditional"; P:129 names switches only for the collector, "the closing-block check and the three collector switches on").
   Replacement: "with #1807 addressed by an own-chain hold in the proposer (switch `digest_order_hold`), the collector hardening switched on, and the epoch-record closing-block check, which extends `main`'s own unconditional stored-record guard (#1834) and has no switch."

2. §2, the definition line "Certification is the share of own headers certified over the load blast's mixed phase."
   The bench-5 cell in that column ("0.0 % (validator-08) before the kill") is over a different window: bench 5 up to the kill (R:25, R:359), the four bench-6 rows over blast 2's whole mixed phase with the outage in it (R:707-708, R:729-730; C:20).
   The cell says "before the kill", but the definition line says nothing of the exception, so a reader comparing 0.0 % with 44.5 % compares a pre-kill window with one that holds the outage.
   Replacement: "Certification is the share of own headers certified over the load blast's mixed phase, the outage included (bench 5: before the kill, the only window the sources give for it)."

3. §2, the column "landed over accepted" has no definition line, although the brief asks for one line per column (p5.md:13).
   Source: C:251 "Landed over accepted" (whole blast as each generator saw it, C:236); R:185 calls it "landed own over accepted", and R:170 says bench 5's figure was recomputed from bench 5's raw generator documents with the code that computed the bench-6 figures.
   Comparability of the bench-5 cell: R:188 says bench 5 recorded neither gap resends nor unlanded transactions after the tail, so the sources do not say whether bench 5's 99.629 % rests on the same 180-s tail scan as the other four cells.
   Replacement (new line under the table): "Landed over accepted is the share of the transactions the RPC accepted that landed on chain, over the whole load blast; bench 5's figure was recomputed from its raw generator records with the same code, but its generator recorded no gap resends and no tail scan."

4. §2, the bench-5 row's throughput, 3,448.7, sits in the table as a like-for-like reference with no caveat.
   The figure and its definition are right (R:21, R:175), but the report attaches two caveats that the table drops: the outage weighs more on bench 5's figure, because generator 05 is silent for 65 % of bench 5's window against 40 % (r20261113-1351) and 38 % (r20261113-1630) (R:192); and "5,322 against bench 5's 3,449" compares a run bound by write count with one bound by bytes (R:327).
   Replacement (add to the throughput definition line): "Generator 05 was silent for 65 % of bench 5's window against 40 % and 38 % in r20261113-1351 and r20261113-1630, and bench 5 was bound by the disk's bytes where bench 6 at 20,000 IOPS was bound by its write count."

5. §3 "What is confirmed", the phrase "the disk gave every engine the same cost, 187.0-187.3 µs/tx".
   The sentence is about "the 20,000-IOPS rows" (both forms), but 187.0-187.3 µs/tx is r20261113-1351's alone (R:369 "In run 2 the disk gave every engine the same cost"); r20261113-2118's task cost was 184.5 µs/tx pooled over nine validators (R:714), and no allowed source gives its per-engine range.
   R:832 extends the conclusion ("its pass holds only while the disk binds") to the adaptive form, not the figure.
   Replacement: "and only then: in r20261113-1351 the disk gave every engine the same cost, 187.0-187.3 µs/tx, and the adaptive run's cost was within the same spread."

6. §3 "What is confirmed", the phrase "With `mdbx_random_advice` on from the first start every node wrote 1.06-1.19 times its page bytes".
   §1 has just said the advice was on in all four runs, so "every node" reads as all four; 1.06-1.19 is measured on runs r20261113-1351 and r20261113-1630 only (R:43 "every node of runs 2 and 2b"; R:26).
   For the adaptive runs the sources give the write pattern (prefault over growth, largest folio order 3, `thp_file_alloc` 0), not a ratio (C:264).
   Replacement: "With `mdbx_random_advice` on from the first start every node of r20261113-1351 and r20261113-1630 wrote 1.06-1.19 times its page bytes, and the adaptive runs showed the same write pattern, against 10-13 times (modelled) for bench 5, whose own first process was not checked."

## Not traceable

- §1 "on top of the benchmark-observability stack": not in R, C, P or F; R:79 gives "base 165e3fe01 plus 98 commits". The writer's notes say it comes from the brief.
- §2 bench-5 cell "no fleet figure": true of the allowed sources (R:25 gives only lowest validators); whether bench 5 has a fleet figure elsewhere was not checked.
- §2 bench-5 "landed over accepted" basis: see error 3; the sources do not say whether it uses the 180-s tail scan.
- §4 "#1807" paragraph, "the comment at lines 996-999 defers the case to #1807": correct for 2df831e3c (F:13, C:262); whether that comment exists on `main` is not in the allowed sources.
- §7 links: the five URLs are the brief's (p5.md:18); whether the four bench-6 pages are live is an orchestrator step (P:67), not checkable here.

## Weak

- §2, throughput definition "over the load blast's window in which all ten generators sent, the outage included": C:265 has "the window in which all ten generators sent", but R:21 has "the all-generators window, outage and generator 05 included", and generator 05 sent nothing for the last 949 s of r20261113-1351's window (R:238) and for 40 % of it (R:192). Suggested: "over bench 5's all-generators window of the load blast, the outage and generator 05's silence included".
- §2, the senders'-cost columns carry no window, while the certification line says "mixed phase"; the source counts them over blast 2 from warm-up start to cool-down end, or the whole blast as each generator saw it (C:236). Suggested: add "over the whole load blast" to the gap-resend and unlanded line.
- §1 "a 40-minute load blast": blast 2 is 120 / 2,400 / 180 s (R:111), so its mixed phase is 40 minutes and the blast 45. Suggested: "a load blast with a 40-minute mixed phase".
- §3 "compare the 20,000-IOPS rows with bench 5's 0.0-16.3 % on its three fastest validators": R:359 says "before the kill"; the 20,000-IOPS rows are over the whole mixed phase. Suggested: add "before the kill".
- §3 "fell from 6,092 tx/s in its first five minutes to 4,719 in its last full five as writes per transaction rose": R:38 ties the rise in writes per transaction to the executed rate's 15 % fall from minutes 1-4 to 35-39; 6,092 and 4,719 are chain-rate buckets (R:216, R:223), and in the last one generator 05 was silent (R:227 argues the fall is not the outage). This follows R:31 and R:38 as the report juxtaposes them; acceptable, but "15 % from minutes 1-4 to 35-39" is the figure the mechanism is stated for.
- §4 "At 50,000 IOPS the adaptive form certified more": the comparison lists the noise as an unsettled contradiction between units (C §8 item 5): the 6.4-point gap of bucket means is inside run r20261113-1630's own 10.6-point bucket range by one unit and outside its two windows (87.0 and 87.3 %) by another (C:29, C:351, R:783). Suggested: "certified more (94.82 against 88.26 %), a gap inside the always-on run's own five-minute range by one measure and outside it by another".
- §4 "The comparison is distorted": the brief's word (p5.md:15); the sources say "not separated" (C:30, C:353) and "cannot be told" (C:360). Suggested: "The comparison does not separate the form from the fleet".
- §4 "the fleet of r20261114-0000 idled 46 minutes before its load": the idle was between deploy and the first blast, a light one (C:12, R:684). Suggested: "before its first blast".
- §4 floor arithmetic, "a floor of 32 outputs gives 100.0 % on the adaptive run's tips and 99.9 % on the always-on run's (16 gives 100.0 and 97.0 %)": the sources give these for the pre-kill window (C:344, C:357, R:809), and neither says whether they are fleet shares or the lowest validator. On r20261113-1630's tips the per-validator table gives 80.5 % (validator-10) at floor 16 and 99.7 % at floor 32 (R:376-377), so the unlabelled 97.0 % and 99.9 % must not be read as "every validator". Suggested: add "before the kill" and name the measure once the orchestrator confirms it from the unit file.
- §4 "The margin was at its minimum once": the source's "once" covers the arm walk, r20261113-1351 and r20261113-1630 (R:51-52, R:571); for the adaptive runs the sources give only "at least 7 signers" (C:266). Suggested: "once in the arm walk, r20261113-1351 and r20261113-1630".
- §4 "#1807" line numbers: pinned to 2df831e3c, so the text does not contradict fact 1, but the brief asks for a mechanism "a maintainer can check against the code" (p5.md:15), and on `main` proposer.rs is the bench-6 base's, so these lines will not match there. Suggested: add "(on `main`, whose proposer.rs is unchanged from bench 6's base 165e3fe01, the same code sits at other lines)".

## Rule breaches

- None found: no unit names, private paths, host names, person names, run nicknames or tool attribution (regex scan for `A<n>`, `I-<n>`, `E-<n>`, `r3-`, `G3`, "run 2/2b/3/3b", `vNN`, home paths, `tasks/`, `private`, attribution words: no hits).
- No statement contradicts C §8 ("Contradictions between units"); the 50,000-IOPS noise dispute (item 5) and the "what binds at 20,000 IOPS" label (item 6) are used on one side without the other, listed under Weak where it matters.
- Brief compliance (not a figure error): 1,499 words by `wc -w` against the brief's 600-1,000 plus one table (p5.md:9), which the writer acknowledges; §3 leaves out R §1 finding 8 ("The floor did not move", 1.50 s seen p50 by stage, R:67), which the brief's item 3 ("whatever else the report's §4 ranks as confirmed") would include.

## Counts

- Figures and statements checked: about 160 (table 42 cells and run ids, definitions 4, §1 20, §3 18, §4 42, §5 16, §6 15, links 5).
- Matched their source value: all.
- Wrong (label, scope or definition; listed under Errors): 6.
- Untraceable to the allowed sources: 5.
- Weak: 11.
