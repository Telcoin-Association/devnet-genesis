# Figure-check FC-R8b: bench 8 report §4 to §8

FIX
No error changes a conclusion; three figures or definitions are wrong and eight statements are weaker or looser than their sources.

## Counts

About 190 figures and statements checked in s4.md to s8.md, plus the five answer figures of s1.md.
Matched: about 176.
Wrong: 3 (E1 to E3).
Weak: 8 (W1 to W8).
Not traceable: 1 (the idle span in §6.1, inside W7).
Not checked within the budget: §8.1's row counts for the figure-checks (AE5's "about 215 checked" matched), §8.3's AF3 error 1 and 2 and AF1 E2 wording, §6.5's validator-09 authority and run 3's 99.94 %, §7.1's "20 to 31", the 7a figures §4.1 and §4.8 take from s3.md (the other checker's sections).

## Errors

E1. s4.md §4.6 line 200: "1,530 quorums for 1,531 headers on validator-02".
Source: far.md line 96 and the far figure-check line 150 give `quorum reached` / `header proposed` as 1,531 / 1,530 for 02 (1,524 / 1,531 for 06 is right).
Old: `(run 1 light blast 1: 1,530 quorums for 1,531 headers on validator-02, 1,524 for 1,531 on 06)`
New: `(run 1 light blast 1: 1,531 quorum lines for 1,530 headers on validator-02, a window edge, and 1,524 for 1,531 on 06)`

E2. s4.md §4.8 line 223: "(7a: busy 980 to 1,009 ms per s)".
Source: no-run-findings.md line 18 gives 980-1,009 for both bench 7 runs; line 72 splits it: 7a 991-1,007, 7b 980-1,009.
Old: `(7a: busy 980 to 1,009 ms per s)`
New: `(7a and 7b: busy 980 to 1,009 ms per s from the load blast's first minute)`

E3. s8.md §8.2: "k ≥ 4: the share of rounds in which four or more headers were under-held."
§4.1 (and AF2 §2, its figure-check lines 24-28) use k per header: the number of other voters more than 8 outputs behind the lead at the proposal, stale voters left out; §8.2 defines only the first looks' "rounds with k ≥ 4" row, which §4 never uses.
Old: `k ≥ 4: the share of rounds in which four or more headers were under-held.`
New (two lines): `k (per header, §4.1): the number of other voters whose latest header tip was more than 8 outputs behind the lead when the header was proposed, leaving out voters whose latest header line was more than 5 s old; k ≥ 4 means four or more such voters.` / `The first looks' "rounds with k ≥ 4" row is a different count: the share of rounds in which four or more headers were under-held.`

## Weak

W1. s4.md §4.5 line 148: "25 to 53 outputs behind the lead in e3".
AF2 per-minute rows (lines 82-91): validator-10 at 9 in the 00:54:44 minute, 25 to 53 from 00:55:44 to 01:02:44; AF2 line 254's "25 to 53" is the issue figure-check's untraced N1.
Old: `By A-F2's minute medians it ran 25 to 53 outputs behind the lead in e3;`
New: `By A-F2's minute medians it ran 9 outputs behind the lead in the first minute of W-prekill and 25 to 53 from 00:55:44 to 01:02:44;`

W2. s4.md §4.6 line 189: the two-window ranges are right and labelled, but the all-six ranges the far figure-check gives (far figcheck lines 48-50, far.md line 86) are missing.
Old: `76 to 88 % of far certificates were named by no near round r+1 header, and fewer than 1 % by 4 or more of the nine others (0.00 to 0.65 %).`
New (two lines): the old sentence, then `Over all six far windows of the far analysis the two shares read 94.4 to 98.0 % and 72.3 to 88.0 %, and in run 2's and run 3's light blast 1 the share named by 4 or more others is 1.03 to 3.00 % [the far analysis's figure-check].`

W3 and W4. s4.md §4.8 line 229: "tied to validator-06 and runs of losses" is not what no-run-findings.md says (line 113: 100 of 7a's 102 lost not-under-held headers are 02's and 06's; N3, line 20: the order hold did not amplify the loss); and "it is the bare-quorum path" for all 496 is split only in AE5's windows (§4.2 marks the run-wide link inferred).
Old: `- The not-under-held remainder was small in 7a (0.49 of 6.00 points) and tied to validator-06 and runs of losses; in run 1 it was 496 of 1,208 lost headers, and it is the bare-quorum path of §4.2, which the no-run analyses did not name.`
New: `- The not-under-held remainder was small in 7a (0.49 of 6.00 points), and 100 of 7a's 102 lost not-under-held headers in N2's count were the far validators' (02 and 06); in run 1 it was 496 of 1,208 lost headers, and in the windows taken apart in §4.2 it is the bare-quorum path, which the no-run analyses did not name.`

W5. s4.md §4.5 keeps the internal error and the demotion in separate paragraphs and says "Twice in run 2, never in runs 1 and 3", but it never says the demotion is mostly evidence for #1806, and §4.8 line 231 calls the whole episode new.
Old: `The demotion and the nine minutes [measured].`
New: `The demotion and the nine minutes [measured]; unlike the internal error, which is new, this part is mostly evidence for the upstream issue #1806 (which predicted a catch-up that could not finish under load; this one finished).`
Old: `- The lagging validator at an epoch close (§4.5) is new; nothing before the runs predicted it.`
New: `- The internal vote error at an epoch close (§4.5) is new, and nothing before the runs predicted it; the demotion that followed is mostly evidence for the upstream issue #1806.`

W6. s5.md §5.2 line 21 claims the suggestion would have worked on the 193 headers; no source measures that.
Old: `this would have left a spare vote, so one late vote would no longer end the round one short.`
New: `this aims at a spare vote, so that one late vote need not end the round one short; whether those headers would then have been certified is not measured.`

W7. s6.md §6.1 line 17: "idled from about 16:10 to about 18:50, 2 h 40 min, until a new login at 18:39" mixes two end points, and 18:50 and "2 h 40 min" are in neither the run facts (lines 71-84), the log nor the lessons' last two entries (not traceable there).
Old: `idled from about 16:10 to about 18:50, 2 h 40 min, until a new login at 18:39.`
New: `idled from about 16:10 to the teardown at about 18:50, 2 h 40 min; the new login came at 18:39.` (and give the source of 18:50 in s6.sources.md)

W8. s8.md §8.1 says "One line per finding of §4", but 4.8 has no line and 4.6 has no file or key.
Old: `| 4.6 | the far validators | see §4.6's sources | | |`
New: ``| 4.6 | the far validators | `P/bench8-far/far.md` Q1 to Q5 | `P/bench8-far/figcheck.md` (ranges per window corrected; the code reading checked at b1104905f and 5533ff73a) | `P/bench8-far/q2-*.json` (for example `q2-r20261117-1401-B1.json` `origins.02.named_near_dist`), `q3.json` |``
Old: `| 4.7 | what did not happen | see §4.7's sources | | |`
New: the old row, then ``| 4.8 | against what was concluded before the runs | `tasks/bench8/no-run-findings.md` §1, §2, §4 and §5 | | |``

## What was checked and held

§4.1: every figure of the author-distance table, the k table, the stale-as-behind recount, the per-minute counts, the definitional paragraph and the outcome figures match AF2 and its figure-check; the required caution and outcome are there.
§4.2: 824 / 412, the round-end lines, 182 / 230 / 0, the voter answers, "bare quorum of seven" on 193, a spare vote on 37, 223 of 230, 0.6 to 21.2 ms, 354 / 400 / 407, the corrected 62 and 81 = 38 + 43 + 0, 343 / 462 of 705, and run 2's lost_class all match AE5, its figure-check and AF1.
§4.3: one run per floor is said; the plan's rows are quoted exactly (plan lines 109-115); 97.618 / 3.43, 99.895 / 0.03, 95.504 / 7.67, 0.3 points, 93.94 to 99.99, 12 to 18 % and 81.7 %, the boundary collapse and regrowth match.
§4.4: busy shares, the 0 / 1 / 2 histogram, 27 of 28, 53 and 47, 1,633 s, 5,072 outputs and 17,788,630 transactions on all ten, 107.5 / 95.4, 114.3 / 103.0, 27 of 31, 4 of 55,256, 28.7 / 24.2, 173 / 140, 219.5 / 415.4, 5,356.8 / 5,181.6 match; the link is called a timing fit.
§4.5: every time and count matches the issue draft and its figure-check (the 48 to 66 "from 01:05 to 01:09" is more exact than the draft's 01:10); twice in run 2 and in neither other run is said; 07's 39 to 47 matches AF2's rows.
§4.6: 95 to 200 / 573 to 1,223 tx/s, 0.39 to 0.68 / 2.44 to 4.80, 96 to 98 %, 76 to 88 %, 0.00 to 0.65 %, the 0-of-N pairs, 17 to 30 %, 286 to 297 / 134 to 182 / 262 to 284 ms, the `bad` and score lines match; the drop is "read from code".
§4.8: apart from W3, W4 and W5, each "borne out" or "changed" verdict matches no-run-findings.md (§1 lines 17-20, §2 line 28, §4 line 113, §5 line 122).
Code at 5533ff73a (five spots): `process_parents` proposer.rs:812 with the `Less` arm at :882 logging only "ignoring older parents"; `behind_consensus` handler.rs:304 with the header rule comparing output numbers and the certificate rule `round > gc_depth.max(6)` when `exec_epoch + 1 == epoch`; `identify_unknown_certificates` header_validator.rs:276 mapping the dropped reply to `PendingCertificateOneshot` at :293; certifier.rs:259 "fatal request for requested vote"; `InvalidEpoch` exists. All hold what §4 and §5 say.
§5: every item is a suggestion, none is called tried or measured, each names its finding, 5.1 says a deeper floor is not a fix, and 5.6 says nothing is posted during the freeze; only W6 overstates.
§6: the login times (13:59, 14:01, 15:31:19, 15:35:58), the failed kill at 15:51:36 and its 13 later actions (rc 1), 45 rounds, 22 instances, 16:30:32, 18:39 and 18:44, rc 128 and commit 1db706d (config.sh, README.md, test_node_image.py), the gate's 1,640 tests, one launch-caused failure, 555 mutation cases, 2,909 s, `SigIgn` 0x6 and the 30-test re-run in 30.9 s, the sampler's 97 rounds and 2,520 files, and the lesson's rules match the run facts, the log and the lessons file.
§7: each question names its measurement; none contradicts §4 (2 to 8 % matches no-run line 94; 1,200 in flight at 11 s gives about 109 tx/s; 98.51 % and 93.997 % match AF3 and AF1).
§1: 1,251 of 1,258, 99.40 / 82.26 %, 193 of 230 and 37, 0.959 to 0.984 with 53, 0.555 to 0.589 with 2, and 31 residual losses match §4.

## Rule breaches

None found: no host name, cloud project id or IP address in s4 to s8, and the only "agent" is the metrics agent on the nodes.
