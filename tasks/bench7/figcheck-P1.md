# Figure-check FC-P1: the four bench 6 backfill pages

Checked 2026-11-14 (UTC) against the report `tasks/bench6-report-r20261113-1351.md` (R), the comparison `benchmark/private/bench6-r20261113-2118/A7/comparison.md` (C) and each run's `manifest.json` (M), for recovery and fleet only.
Pages: always-20k (r20261113-1351), always-50k (r20261113-1630), adaptive-20k (r20261113-2118), adaptive-50k (r20261114-0000).

## Verdict

FIX

Five errors, none of which changes a conclusion of any page; five statements not traceable to the allowed sources, one of them a present-tense claim about upstream main; nine weak or inconsistent spots.

## Errors

1. always-20k, `summary`, "Each validator ran at 0.998 of its 20,000 writes a second for the whole 40 minutes".
   Source: 19,967 [19,946-19,984] writes/s is the median of the nine validators other than validator-05 (R L27, L30, L311); validator-05 was killed and followed the chain for part of the blast.
   Replacement: "The validators other than validator-05 ran at 0.998 of their 20,000 writes a second (the median; 19,946 to 19,984) for the whole 40 minutes, so the rate is 20,000 divided by the writes per transaction, which rose as the database grew."
   Same error in always-20k `caveats[3]`, "Over blast 2 each validator ran 19,967 device writes a second (0.998 of 20,000)".
   Replacement: "Over blast 2 the median validator, validator-05 aside, ran 19,967 device writes a second (0.998 of 20,000; 19,946 to 19,984 across the nine), 5.0 KiB each, 3.74 writes per executed transaction, ..."
2. always-20k, `caveats[12]`, "across this program's first three runs it fired 11 times".
   Source: the 11 are over the arm-walk run r20261112-1520 and runs r20261113-1351 and r20261113-1630 (R L421: 9 on validators at 6 closes and 1 on the observer in the first two, 1 in r20261113-1630; R L640).
   The page's summary defines "this program" as the four runs, so "first three" reads as r20261113-1351, r20261113-1630 and r20261113-2118.
   Replacement: "across the arm-walk run (r20261112-1520), this run and r20261113-1630 it fired 11 times".
3. All four pages, shared `methodology[7]`, "and the bench-5 figures quoted on these pages were recomputed exactly from bench 5's own generator documents with the same code".
   Source: R L170 covers the KPI tables only (throughput, window, best 60 s, landed, blocks/s, land and seen, landed over accepted, RPC errors, the 600 x 4 and floor rows; R L175-205).
   Other bench-5 figures on the pages come from elsewhere: certification 0.0-16.3 % (R L25, bench-5 report finding 4), amplification 10-13x (R L26, "through run 1's model; bench 5 logged no page counts"), commit 178.0 µs (R L27, L30), refused votes 47,614 (R L359), stage figures 3.78 s, 16.9 s, 9.6 s (R L247-260), rejoin 28m05.8s (R L28).
   Replacement: "Headline figures keep bench 5's definitions and code; bench 5's throughput, latency and landing figures quoted on these pages were recomputed exactly from bench 5's own generator documents with the same code, while its certification, disk, stage and rejoin figures come from bench 5's report or from this program's reading of bench 5's logs and model."
4. adaptive-20k, `caveats[7]`, "With generator 05 left out the adaptive form had 3.54 times the resends, 4.03 times the skips and 59 times the unlanded."
   Source: only the resend ratio is with generator 05 left out (104,168 / 29,449, C L241); the skips are node-side Prometheus counts with no generator to leave out (52,588 / 13,036, C L243); 59 is all generators (10,767 / 183, C L249, L254; R L789).
   With generator 05 left out the unlanded are 9,290 against 0 (C L249), which the same caveat states, so no ratio exists.
   Replacement: "The adaptive form had 3.54 times the resends (generator 05 left out), 4.03 times the skips and 59 times the unlanded (all generators)."
5. adaptive-50k, `caveats[6]`, "With generator 05 left out the adaptive form had 1.96 times the resends, 1.91 times the skips and 1.4 times the unlanded."
   The values hold (1.96 = 251,929 / 128,835, C L241; 1.4 either way, C L249), but the skips (132,743 / 69,647, C L243) have no generator to leave out, and the sentence should match item 4's.
   Replacement: "The adaptive form had 1.96 times the resends (generator 05 left out), 1.91 times the skips and 1.4 times the unlanded."

## Not traceable

1. All four pages, last caveat: "A further run on the newer upstream main branch, with its new storage engine and with issue #1807 addressed, is planned".
   The allowed sources say nothing of upstream main or a further run (R §8.6 L850 asks only whether to repeat the 50,000 IOPS pair).
   The launch prompt's established facts are that main uses tn-lmdb (#1834) instead of these runs' MDBX and that a further run of both forms on that main is planned; neither says #1807 is addressed on main.
   If the #1807 change lives in the bench build rather than in upstream main, this is a wrong public statement about upstream.
   Safe replacement: "A further run of both forms on the newer upstream main branch, which uses a different execution storage engine (tn-lmdb) than these runs (MDBX), is planned; its result is not known."
   Add "with a change for issue #1807" only once the orchestrator confirms where that change is.
2. Shared `methodology[4]`, "c3-highcpu-8 (8 vCPU, 16 GiB)": R L89 gives 16 GiB only; 8 vCPU is implied by the public machine type name, not in the sources.
3. Shared `methodology[8]`, "with fixed-shape lines per vote, header, certificate, consensus output and engine stage": not in R L161, L164 or C L18 (the writer's cites); a general description, low risk.
4. always-20k, `caveats[5]`, "whose trigger bench 5's page left unidentified": bench 5's page is not an allowed source (R L40 says only "understood and gone").
   Replacement: drop the clause ("This program explains bench 5's extra disk bytes.").
5. adaptive-50k, `caveats[10]`, "A forecast made from r20261113-1630 before this run": C L340 and R L834 call it the first analysis pass's forecast from r20261113-1630; neither dates it before r20261114-0000 ran.
   Replacement: "A forecast from r20261113-1630's data, made in an earlier pass of the analysis, ..."

## Weak

1. always-20k `caveats[12]` and always-50k `caveats[11]`, "No test yet crosses an epoch close with the always-on form."
   R L419 speaks of the tests at build 2df831e3c; a present-tense claim about tests is not checkable for upstream main from the allowed sources.
   Replacement: "No test in this build (2df831e3c) crosses an epoch close with the always-on form."
2. always-50k `caveats[11]`, "The close inside the outage (18:22:19) is the thinnest of the program".
   R L407 wrote "of the program" before runs r20261113-2118 and r20261114-0000 existed (R L12), meaning the arm-walk run, r20261113-1351 and r20261113-1630; on this page "program" is the four runs, and the sources give no vote-gap figure for r20261113-2118's 7-signer close (C L116).
   Replacement: "is the thinnest close of the arm-walk run, r20261113-1351 and this run".
3. always-50k gives the same boundary two times: `methodology[11]` "18:22:20" (R L113; M chaos boundary_unix 1794594140) and `caveats[11]` "(18:22:19)" (R L404, C L307; M planned boundary 1794594139).
   Use one value on the page.
4. Cross-page: adaptive-20k `caveats[2]`, "they started their mixed phase 59 to 89 s late against 23 to 48 s", against always-20k `methodology[13]`, "no generator started more than 3 s late".
   They are different quantities (C L55 "start spread"; R L116, L292 largest `late_secs` 3 s), so a reader sees r20261113-1351's generators 3 s late on one page and 23 to 48 s on the other.
   Replacement on adaptive-20k: "In blasts 0 and 1 the generators' start spread was 59 to 89 s against 23 to 48 s in r20261113-1351, as generators 02 and 06 began their mixed phase late after losing setup transactions in the preamble; the cause was not traced."
5. Cross-page rounding of landed over accepted: r20261113-1351 reads 99.999 % on always-20k `caveats[7]` (R L185) and 99.9987 % on adaptive-20k `caveats[7]` (C L251); r20261113-1630 reads 99.923 % on always-50k `caveats[9]` and 99.9232 % on adaptive-50k `caveats[6]`.
   Use four decimals on all pages.
6. Commit cost per transaction from two measures: r20261113-1351 is 74.2 µs on always-20k `caveats[4]` (R L447, engine stages pooled) and 75 µs on always-50k `summary` and `caveats[3]` (R L27, L311, median of nine); on always-50k itself r20261113-1630 is 22 µs (`caveats[3]`) and 22.4 µs (`caveats[4]`).
   Name the measure where both appear, or use the engine's (74.2, 22.4) in always-50k's summary and `caveats[3]`.
7. All four pages, the #1807 caveat, "whether they change this cost was not measured": true of these four runs (R L852, C L358), but R L477 records that in the arm-walk run `sealed_tx_keep` with the three other pool switches left "no gap resends, nothing unlanded after the tail" (confounded: four switches and an epoch boundary in one step).
   Suggested: "... whether they change this cost was not measured in these runs (in the earlier arm-walk run, sealed_tx_keep with three other switches on left no gap resends, a reading confounded with the other switches and an epoch boundary)."
8. Present tense about the build's code: "Execute and persist run in series" (always-20k `caveats[4]`), "Executing and persisting a consensus output run in series" (always-50k `summary`), "a follower may promote only within 20 rounds ... and replays no faster than it executes" (always-20k `caveats[11]`).
   The sources describe build 2df831e3c (R L441 "at 2df831e3c"); upstream main has had a different execution store since.
   Suggested: past tense or "in this build".
9. No page names these runs' execution store, while the disk findings (prefault writes, the random-access hint, page-cache folios, amplification, commit cost) are specific to it and the last caveat contrasts "its new storage engine" with nothing on the page.
   Not a contradiction of the established fact; suggestion: name MDBX once in shared `methodology[3]` (for example "mdbx_random_advice (the MDBX database's random-access hint ...)").

## Rule breaches

None in the public keys: no unit names, no private paths, no host or person names, no "run 2 / 2b / 3 / 3b" nicknames, no tool or assistant attribution (scripted scan of every string outside `_comment`).
`_comment` carries the comparison's private path and unit name, which is allowed there; it has no attribution.

## Checked and right (the launch prompt's focus items)

- Throughput, seen p50/p95, floor, own-header certification per run and per validator: every value matches R §1, §3, §4.3, §8.3 and C §2.
- Senders' cost: every count sits with the right run (C L240-252); 29,546 resends on three generators belong to r20261113-1351, 133,975 on eight to r20261113-1630, 104,280 on eight to r20261113-2118, 255,453 on ten to r20261114-0000; the late-landing splits 30,497 + 9,766 and 120,778 + 9,776 add up (R L191).
- "+37.7 %" (always-50k summary): 7,329.0 / 5,322.1 = 1.3771, labelled derived.
- Definitions: always-on (shared `methodology[2]`) matches R L645 and C L260; adaptive matches R L646 ("own tip until an own header is cancelled, then the quorum rule inside a starved window"), with the 128-round bound from C L87 and R L849.
  The page follows the report, not the p1 brief's "uncertified for 4 rounds" wording, which is right.
- What binds: disk write count at 20,000 IOPS (R L35-38), the engine at 50,000 IOPS (C L215, L263); adaptive-20k gives both labels of C §8 item 6.
- Kill, restart and observer-restart times on all four pages equal M `chaos[0..2].ts`; the kill is `docker kill -s KILL`; machine c3-highcpu-8, Hyperdisk Balanced 100 GB at 800 MiB/s, IOPS 20,000 / 50,000 / 20,000 / 50,000; ten blasters on e2-standard-2, each in its target validator's zone; city names match `zones_used`; image digest 874537ff… and generator 62bbd5f in all four manifests.
- Rejoin times 21m40.7s, 21m30.2s, 22m39.8s, 30m00.0s and the cooldown or mixed-end to promotion times match R L429 and C L119-120, L228-229.
- The eight shared methodology items, the provenance caveat, the last caveat and the closing cross-run paragraph are word-for-word identical on all four pages (scripted); the cross-run paragraph is true of all four runs (R §8.1 items 1-5, C §9).
- Every compare_to statement matches the compared run's own page (apart from W4, W5 and W6 above).
- Nothing on any page says or implies the form of the vote fix is decided; each page says it is not.

## Note for the orchestrator (outside the allowed sources)

`recovery.rejoined_utc`, `catch_up_secs` and `failed_reports` are null and will be computed by the bundle from `tn_node_mode`; if that rejoin differs from the log's kill-to-active time in the caveats, the page will show two figures for one event.

## Counts

- Figures checked: about 1,350 numeric tokens (all four pages, shared text once, times and counts included) and about 70 relational statements.
- Wrong: 5 (in 7 places).
- Not traceable: 5.
- Weak: 9.
- Everything else matched its source.
