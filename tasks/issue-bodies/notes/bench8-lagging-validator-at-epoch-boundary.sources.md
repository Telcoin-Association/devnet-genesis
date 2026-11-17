# Sources: bench8-lagging-validator-at-epoch-boundary (not for posting)

Logs: L10 = benchmark/results/r20261116-2332/logs/bench-validator-10-unit-stdout.log.gz, L07 = the same for validator-07. Extracts made for this text (zcat | grep -E '^ts=2026-11-17T01:(0[3-9]|1[0-2])' and '01:(2[3-9]|3[0-3])'): /home/drtnarg/.claude/jobs/e50668f4/tmp/w-i8/v10.txt, v07.txt. Build = git -C /home/drtnarg/coding/telcoin/tn-b8-bench show b1104905f:<path>; main = git -C /home/drtnarg/coding/telcoin/tn-b8-uc show f25a74eb7:<path>.

## Run and configuration
- run id, not published, one run: tasks/bench8/r20261116-2332/run-facts.md.
- ten validators + one observer, ten zones (asia-east2, asia-northeast1, asia-northeast3, asia-south1, asia-southeast1, australia-southeast1, europe-west2, europe-west4, us-east4, us-west2): benchmark/results/r20261116-2332/manifest.json, key instances[].zone (10 distinct).
- c3-highcpu-8, hyperdisk-balanced 20,000 IOPS: run-facts.md "Machine" line (manifest machine_type, node_disk).
- 600 senders x window 16, mixed 00:54:44-01:34:53: run-facts.md Blasts table, blast 2.
- arm bench8-control: quorum_exec_block=true, floor_outputs=8, vote_queue_fix=true: run-facts.md "Arm" line. run 1 r20261116-2011 differs only in floor (16): run-facts.md "By hand" first bullet; AF2 first-look line 1.
- build b1104905f = main 45dce8947 + #1862 stack + log fields: the brief w-i8.md section 1; log first line `telcoin-network 0.1.0 (b1104905f...) starting` (L10 line 1).
- 20-minute epochs: commit=1794877422 (L10 01:04:06.950) and commit=1794878622 (L07 01:24:06.733), difference 1200 s.

## What happens / Evidence (validator-10, L10 / v10.txt)
- `header proposed" round=3276 epoch=3` 01:03:43.239725: v10.txt grep -F 'header proposed" round=3276 '.
- others' `epoch boundary detected` epoch=3 01:03:43.075 to 01:03:43.169: benchmark/work/bench8-scratch/r2-AV10/r2/validator-0[1-9]-epoch.txt, first matching line per file, min and max (AV10 notes validator-05 was not tabulated; the range is over the files that matched).
- 62 `Failed to return pending certificate manager result` answers, 01:03:43.304 to 01:03:55.411: grep -F 'fatal request for requested vote' | grep -cF 'Failed to return pending' = 62; 186 lines with the string = 62 x 3 (fatal line + paired lines).
- nine voters: distinct authority= among those lines = 9.
- 154 `Invalid epoch. Peer proposed epoch 3, but expected 4`, last fatal line 01:04:06.694: fatal+Invalid epoch = 154; 216 fatal in all; last fatal 01:04:06.694875.
- 23 re-proposals 01:03:44.242 to 01:04:06.326: grep -cF 're-proposing last header after max delay interval expired for round 3276' = 23, first/last ts.
- own `epoch boundary detected epoch=3` 01:04:06.950877; 23.8 s = 06.950 - 43.169 (23.78) / - 43.075 (23.88).
- demotion line 01:04:09.428524 (rounded .429): `we are behind, go to catchup mode! epoch=4 exec_epoch=3 number=None exec_number=6065 ... committed_round=3274 round=41 ... gc_window=40 reason=epoch_behind newest_header_number=6080 backlog_outputs=15`, followed by `certificate indicates we are behind, go to catchup mode!` (cert path).
- `subscriber starting in mode node_mode=CvvActive` 01:12:44.092230: 8 min 35 s = 01:12:44.092 - 01:04:09.429 = 514.66 s.
- 541 s without a header: first `header proposed"` after 01:03:43.240 is round=1366 epoch=4 at 01:12:44.716249 (0 headers in between); also benchmark/work/bench8-scratch/r2-AV10/q4-gaps.txt line "r2 validator-10 ... 541.0s e3r3276 -> e4r1366".
- 147 `rejoin not ready`, 146 reason=round_gap (the other reason=stale_head at 01:11:16.627): grep -cF.
- gap 44 to 60 for six minutes, execution 66 to 96 rounds behind: every 20th round_gap line, newest_round-handled_round and newest_round-exec_round: 01:04:26 80 (exec n/a, first line); 01:05:30 58/96; 01:06:29 60/92; 01:07:36 52/88; 01:08:43 54/86; 01:09:47 54/84; 01:11:10 44/70; 01:12:22 34/66. "44 and 60 for six minutes" = 01:05:30 to 01:11:10 samples. Related bullet "44 to 80" = all samples but the last (34).
- `attempting to rejoin consensus ... round_gap=20 rejoin_window=20` 01:12:43.823634.
- 15,821 behind; one created at 01:12:44.715804 (after CvvActive 01:12:44.092): `vote path timing` lines with ts in [01:03:43.239, 01:12:44.716], outcome counts: behind 15821, rejected 560, superseded 12, error 3, too_new 2, missing_parents 1, created 1.
- quorum of 7 with one spare fewer: benchmark/private/bench8-r20261116-2332/AF2/first-look.md line 258 (figure-checked).
- 25 to 53 outputs behind the most advanced validator in e3: first-look.md line 254 (figure-checked).
- persist 377/414 ms per output (00:54, 00:56 buckets) vs 279/282 on validator-02: benchmark/work/bench8-scratch/r2-AV10/q1-engine.json keys "10" and "02", buckets "00:54"/"00:56": pe/n = 55745/148, 56746/137 vs 47190/169, 46585/165.
- 843 `Failed to track spawned task ... no available capacity`, 01:04:14.264 to 01:04:20.170: v10.txt grep -cF both strings = 843, first/last ts.

## Validator-07 (L07 / v07.txt)
- 54 internal-error answers, 01:23:43.499 to 01:23:55.710, its own B2938 e4 header: fatal+Failed to return pending = 54, first/last ts; round 2938 epoch 4 from q4-gaps.txt "e4r2938".
- demotion 01:24:13.004 `epoch=5 exec_epoch=4 number=None ... round=41 gc_window=40 reason=epoch_behind`; CvvActive 01:32:52.735; 8 min 40 s = 519.73 s.
- 550 s without a header: q4-gaps.txt "r2 validator-07 11-17T01:23:43 -> 01:32:53 550.0s e4r2938 -> e5r1130".
- 15,758 behind, 0 created, ts in [01:23:43.5, 01:32:53.9]: outcome counts behind 15758, rejected 670, superseded 18.
- "20 minutes later": the two commits differ by 1200 s.

## Run 1
- no validator >30 s without a header except start-up and the planned kill: q4-gaps.txt, r1 lines (start-up 20:28-20:35 for all, validator-05 22:26:11 -> 22:44:08).

## Code (main f25a74eb7 / build b1104905f)
- error.rs:332-333 PendingCertificateOneshot / same. error.rs:210 InvalidEpoch message / same. error/network.rs:18 "Error processing header vote request" / same.
- header_validator.rs:288-293 (fn 276) / same.
- cert_manager.rs:339-342 FilterUnkownDigests, :355-356 shutdown return / build 352-354, 368-369.
- certifier.rs:243-257 RPCError fatal / build 251-265.
- proposer.rs:1337 re-propose / build 1915.
- handler.rs:348-361 epoch_behind (header rule 348-352, cert rule 353-358), demotion 402-446 (message 442), cert path caller 629, outcome Behind arm 2348 / build 365-378, 422-466 (message 462), 649, 2603.
- types primary/mod.rs:87 rejoin_round_window / same. subscriber.rs:136 rejoin_ready, 554 attempting, 584 not ready / same.
- task_manager.rs:199-208 (match on try_send, error at 208) / build 199-201 (if let Err, error at 201).
- test_hooks.rs:117 TN_TEST_EXECUTION_DELAY_MS (main).

## Issues
- #1806: gh issue view 1806 (title "A loaded epoch close waits for the seventh-fastest validator's execution backlog; slower members miss the epoch record", open); round 39 / one round short: its local draft tasks/issue-bodies/bench5-loaded-epoch-boundary-drain.md lines 12-13; 4.05 s and 4 minutes: its bench-6 comment ("The `epoch_behind` demotion fired: ..."); tracker overflow = its proposal (D), draft line 160.
- #1857: gh issue view 1857 (open); 802 to 1,144 rounds: tasks/issue-bodies/bench6-rejoin-under-sustained-load.md Evidence.
- #1510: gh issue view 1510 (open), body "Problem".
- #1804: gh issue view 1804 (open); its fix is in the #1862 stack (brief).
- #1862, #1807: the brief.

## Added after the writer's hand-back (two figures it used and did not list)

- "70 ms": validator-10's round-3276 `header proposed` line at 01:03:43.239 minus the last peer's `epoch boundary detected` line at 01:03:43.169 (the peers' lines run from 01:03:43.075 to 01:03:43.169), each from that node's `logs/bench-validator-NN-unit-stdout.log.gz` of run r20261116-2332.
- "22 s": the 23 `re-proposing last header after max delay interval expired for round 3276` lines in validator-10's log, first at 01:03:44.242, last at 01:04:06.326 (22.1 s).

## After the figure-check (2026-11-17): the text now cites main at 5533ff73a

Upstream main moved while the draft was written: #1862 itself merged (squash 8c75f7582, 2026-11-17T01:19:02Z), and #1871, #1547, #1875, #1876 landed. Every code location was re-read on main at 5533ff73a:
`header_validator.rs:288-293` (send at 291, await at 293), `error.rs:332-333`, `cert_manager.rs:339-342` and `:355-356`, `certifier.rs:249-263` (the log line at 259), `proposer.rs:1685`, `network/handler.rs:362-366` (header rule), `:367-375` (certificate rule, `round > gc_depth.max(6)` at 375), `:419-463` (demotion, message at 459), `types/src/primary/mod.rs:87`, `executor/src/subscriber.rs:136`, `types/src/task_manager.rs:218-227` (error at 227), `types/src/test_hooks.rs:126`.
#1516 (closed) and #1547 (157d3207f): read from #1547's diff: it changes the gossip arms of `network/handler.rs` (`is_cvv()` → `is_active_cvv()`; no certificate written while inactive) and adds tests; it does not touch `identify_unknown_certificates` or the vote request path.
Validator-02's two lines (`Certifier received shutdown` 01:03:43.156, `Starting epoch` 01:03:48.265): from the figure-check's read of validator-02's unit log (its report, item W6).
The figure-check's report: `tasks/issue-bodies/notes/bench8-lagging-validator-at-epoch-boundary.figcheck.md` (82 figures: 75 matched, 5 wrong and corrected, 2 not traceable and removed; every code location held what the text says).
