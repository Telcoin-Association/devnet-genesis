# Figure-check FC-I8: tasks/issue-bodies/bench8-lagging-validator-at-epoch-boundary.md

Verdict: FIX.
Five factual errors and six weak points; none changes a conclusion of the text.
The draft is 1,115 words with the title (1,094 without); the 30 edits in section 7 bring it to 898 (877 without the title), lint clean.

## Counts

Figures checked 82, matched 75, wrong 5, not traceable from the allowed sources 2.

## Errors

1. What happens, "For 541 s it proposed no header and signed no vote." The 541 s (01:03:43.239 to 01:12:44.716) hold one `created` vote, at 01:12:44.716, 0.62 s after the promotion (01:12:44.092). Replacement: "For 541 s it proposed no header, and it signed no vote until its promotion." (merged into edit C4).
2. Evidence, "For six minutes the handled round trailed the newest by 44 to 60 rounds, and execution by 66 to 96." Those are every 20th line. Over all 146 `round_gap` lines the gap ran 30 to 80; per minute 01:05 54-66, 01:06 52-60, 01:07 48-56, 01:08 50-56, 01:09 50-56, 01:10 34-46; execution 80 to 98 from 01:05 to 01:09. Replacement: "From 01:05 to 01:10 the handled round trailed the newest by 48 to 66 rounds, and execution by 80 to 98." (edit C11 is a shorter form).
3. Related #1857, "here the gap was 44 to 80 rounds": all lines 30 to 80. Replacement: "here the gap was at most 80 rounds" (edit C27).
4. Related #1510, "here nothing was killed and it rejoined.": this run killed validator-05 by plan at 01:22:43 UTC across the epoch-4 close (run-facts line 24). Replacement: "here validator-10 was not killed and it rejoined." (edit C28 deletes the line).
5. Evidence, "plus the open stack of #1862": #1862 merged into main on 2026-11-17 at 01:19:02 UTC (merge 8c75f7582); #1863 to #1869 show MERGED into their stacked base branches; none of the switch names occurs in the ten cited files on current main 5533ff73a. Replacement (edit C7): "plus the stack of #1862 (the fixes for #1804 and #1807 and the epoch-record work; #1862 itself merged since) with all its switches on, `quorum_exec_block` at a floor of 8 outputs, plus log fields." The owner should settle the stack's state in that one line.

## Weak

W1. The switch list "(`quorum_exec_block` with a floor of 8 outputs, `vote_queue_fix`)" reads as complete; the arm also set `digest_order_hold`, `epoch_record_collect_past_uncertified`, `epoch_record_conflict_halt`, `epoch_record_recertify` true (run-facts line 9). Edit C7 says "all its switches on".
W2. Validator-07's repeat omits that validator-05 was down by plan at that close: its 54 answers came from eight voters. Edit C14 adds it.
W3. Main has moved: f25a74eb7 (2026-11-16 19:18 UTC) is 5 commits behind upstream main 5533ff73a, which adds #1862 and #1547 "fix(primary): skip cert-manager path on inactive CVV (#1516)" (network/handler.rs only). The part-1 lines are unchanged there; the others moved (section 2). "Every location is also on the build, at other line numbers" is not exact: error.rs:332 and primary/mod.rs:87 are the same lines on the build (edit C16). Whether #1547 changes a voter's answer was not checked (it gates an inactive node; the voters were active).
W4. Timestamps mix truncation and rounding: .239 (log .239725), .950 (.950877), .694 (.694875) truncated; .429 (.428524), .169 (.168898), .824 (.823634) rounded; "70 ms" is 70.8 ms. Optional, word-neutral: "header went out at 01:03:43.239" → "header went out at 01:03:43.240"; "From 01:03:43.239 to its next header" → "From 01:03:43.240 to its next header"; "until 01:04:06.694" → "until 01:04:06.695"; "70 ms after the last" → "71 ms after the last".
W5. "#1806 predicted" is fair, but #1806 predicted a catch-up "it cannot finish under load"; this one finished under load (rejoin 01:12:43, mixed phase to 01:34:53). Edit C25 says so.
W6. Optional strengthening of the inference (part 1, last code bullet), measured on a voter: validator-02 logged `Certifier received shutdown` at 01:03:43.156 (its boundary), `process_gossip e=Certificate(CertificateManagerOneshot)` at 01:03:43.170 and 01:03:43.199, and `Starting epoch` at 01:03:48.265. From code: the answer is `PendingCertificateOneshot`, not `TNSend` (error.rs:330, :373), so the channel accepted the command and its reply sender was dropped unanswered; the manager answers every command it receives (cert_manager.rs:339-342), so the command was dropped unreceived. Adds about 25 words if used.

## Not traceable

N1. "In epoch 3 validator-10 ran 25 to 53 outputs behind the most advanced validator.": its only source is the private first-look; the logs show `backlog_outputs=15 exec_lag_rounds=30` at the demotion. Edit C8 deletes it.
N2. "the fixes for … #1807": #1804's are in the stack (#1864 fix/1804-vote-queue, #1868 fix/1804-quorum-exec-block, both on in the arm); #1807's was not checked (brief only).

## 1. Times and counts (raw logs of r20261116-2332; matched unless listed above)

Peers' `epoch boundary detected epoch=3`: 01:03:43.075 (validator-07) to 01:03:43.169 (validator-06), all nine including validator-05.
Validator-10's round-3276 header 01:03:43.239725, 70.8 ms after the last peer.
216 `fatal request for requested vote` = 62 `Failed to return pending certificate manager result.` (01:03:43.304 to 01:03:55.411, nine distinct voters) + 154 `Invalid epoch. Peer proposed epoch 3, but expected 4` (01:03:47.620 to 01:04:06.695).
For each of the nine voters every internal-error answer precedes its first epoch answer, which comes 1.0 s later.
23 re-proposals of round 3276, 01:03:44.242 to 01:04:06.327 (22.1 s).
Own boundary 01:04:06.951: 23.78 s after the last peer.
Demotion 01:04:09.4285 with `number=None … round=41 … gc_window=40 reason=epoch_behind`, followed by `certificate indicates we are behind, go to catchup mode!`: the certificate rule, as the text says.
`node_mode=CvvInactive` 01:04:20.242, `node_mode=CvvActive` 01:12:44.092; demotion to promotion 514.7 s = 8 min 35 s (the mode is set at the demotion, handler.rs:444).
No header between 01:03:43.240 and 01:12:44.716 (round 1366 of epoch 4): 541.5 s.
147 `rejoin not ready`, 146 `round_gap`, one `stale_head`; `attempting to rejoin consensus … round_gap=20 rejoin_window=20` at 01:12:43.824.
Vote outcomes 01:03:43.239 to 01:12:44.716: behind 15,821, rejected 560, superseded 12, error 3, too_new 2, missing_parents 1, created 1 (after the promotion).
843 `Failed to track spawned task … no available capacity`, 01:04:14.264 to 01:04:20.170.
Endpoint samples: `tn_node_mode_transitions_total{to="cvv_inactive",reason="epoch_behind"} 1` from 01:04, `{to="cvv_active",reason="rejoin"} 1` at 01:14.
Validator-07: header B2938 e4 at 01:23:43.455; 54 internal-error answers 01:23:43.499 to 01:23:55.710 from eight voters; 131 epoch answers; demotion 01:24:13.004 `round=41 gc_window=40`; CvvActive 01:32:52.736 (519.7 s = 8 min 40 s); next header 01:32:53.235 (549.8 s); behind 15,758, no `created`; the two closes' commits differ by 1,200 s.
Persist (q1-engine.json): 55,745/148 = 377, 56,746/137 = 414 against 47,190/169 = 279, 46,585/165 = 282 ms per output.
Configuration: c3-highcpu-8, hyperdisk-balanced 20,000 IOPS, 11 instances in 10 zones of 10 regions, 600 × 16, mixed 00:54:44 to 01:34:53, floor 8 (manifest; run-facts lines 6, 9, 18).

## 2. Code locations (f25a74eb7: all OK; current main 5533ff73a in brackets)

error.rs:332-333 `PendingCertificateOneshot` and its message: OK [same].
header_validator.rs:288-293 send `FilterUnkownDigests`, await the oneshot, map to `PendingCertificateOneshot` (fn at 276; called from the vote path via header_validator.rs:270): OK [same].
cert_manager.rs:339-342 answers the command, :355-356 returns on shutdown: OK [same]; the loop can also return on a fatal GC error (:350).
certifier.rs:243-257 `RPCError` logged `fatal request for requested vote` and returned as an error: OK [249-263].
proposer.rs:1337 the re-propose warning: OK [1685].
handler.rs:348-352 header rule, :353-358 certificate rule `round > gc_depth.max(6)`, fn `behind_consensus` at 290, demotion :402-446 (log 442, mode switch 444-445): OK [362-366, 367-375, 419-463]; the local `gc_depth` holds `gc_activity_window(gc_depth)` (handler.rs:340), 40 here.
primary/mod.rs:87 `rejoin_round_window` (20 at gc_depth 50): OK [same].
subscriber.rs:136 `rejoin_ready`: OK [same].
task_manager.rs:199-208 `try_send`, error at 208: OK [218-227].
test_hooks.rs:117 the doc line naming `TN_TEST_EXECUTION_DELAY_MS`: OK [126].
Build b1104905f spot checks: certifier.rs:261, error.rs:332, proposer.rs:1915, handler.rs:378, mod.rs:87, task_manager.rs:201.

## 3. Causal sentences

Measured (two log lines in sequence): the internal-error then epoch answers per voter; fatal for that voter (`fatal request for requested vote`); the demotion by the certificate rule; the stay until the 20-round window (146 `round_gap` lines, then `attempting to rejoin … round_gap=20`, then CvvActive 0.27 s later, and the `reason="rejoin"` counter).
Read from code and marked as such: the oneshot mapping, the manager's shutdown return, the certifier's fatal arm, the re-propose, the two rules and the window.
Inferred and marked "Inferred from the times": the voter's certificate manager had stopped at its close; no voter line says the manager stopped, but W6 gives a voter line consistent with it.
What the fleet lost: only "The quorum of 7 had one spare voter fewer for those nine minutes", arithmetic (10 validators, quorum 7), true for 01:03 to 01:12 (no other validator was down); no certification loss is claimed.
"The lag built up from 00:54 to 00:58, when its persist time was …" is a timing correlation; the text lists the cause as not known.

## 4. Related issues

#1806, body: "And validator-01 entered epoch 8 when the network was at round 39 of it: one round more and the `epoch_behind` rule would have demoted it into a catch-up it cannot finish under load." The text's round 39 / one round short is right; its bench-6 comment reports validator-05 twice (4.05 s in all) and validator-02 for 4 minutes: right. "Part 2 is mostly evidence for #1806" is fair, with W5's correction. The tracker overflow is #1806's ("logged about 1,460 `tn::tasks` errors (`… no available capacity …`)").
#1857: "every check failing on `reason=round_gap`: 802 to 1,144 rounds against a window of 20": the text's account is right; error 3.
#1510: title and Problem match the text's account; error 4.
#1804: its fixes (#1864, #1868) were on in the arm: right.

## 5. Strength and scope

"One run of one configuration", "not published", "with its switches on", "never restarted / never killed" (validator-10: no kill or restart in run-facts): present and true.
Run 1 (r20261116-2011), raw logs of validators 01-10: no gap over 30 s between own headers after start-up (20:37) except validator-05 22:26:11 to 22:44:08, the planned kill of 22:26:12Z (its run-facts line 24): the sentence stands.

## 6. Rules of a public text

Lint: LINT-OK.
No private path, unit name, host, person, project id, IP, tool mention or attribution; one sentence per line.
Log excerpts: the demotion quote drops `message="…"` (edit C10 restores it); `Invalid epoch. Peer proposed epoch 3, but expected 4` is a substring of the logged text, which ends `expected 4)` (the format string's stray parenthesis, error.rs:210).

## 7. Edits that fix the errors and cut to 898 words

Strings are Python reprs (\n = line break); apply in order; each old string occurs exactly once in the original file.
Result: 898 words with the title, 877 without; lint clean; the edited copy is /home/drtnarg/.claude/jobs/e50668f4/tmp/fc-i8/after3.md.
Nothing the owner needs is lost: what goes is the region names, the observer, the duplicate re-proposal sentence, the untraced "25 to 53", "not at an epoch record", one "not known" duplicate and one speculative item, the second part-1 suggestion, #1806's "levers" line, the fleet-verification bullet, and the #1510 and #1804 lines.

C1 (-9 words)
- old: 'Two things happened at one event, kept apart below.\n'
- new: (deleted)
C2 (-1 words)
- old: 'In benchmark run r20261116-2332,'
- new: 'In run r20261116-2332,'
C3 (-11 words)
- old: 'It re-proposed the header about once a second for 22 s.\n'
- new: (deleted)
C4 (-2 words)
- old: 'It logged the boundary itself 23.8 s after the others, was demoted to `CvvInactive` with `reason=epoch_behind`, and stayed in catch-up for 8 min 35 s.\nFor 541 s it proposed no header and signed no vote.'
- new: 'It logged the boundary 23.8 s after the others, was demoted to `CvvInactive` with `reason=epoch_behind`, and was out 8 min 35 s: 541 s without a header, and no vote signed until its promotion.'
C5 (-11 words)
- old: 'ten validators in ten regions (Asia, Australia, Europe, the US) and one observer, on c3-highcpu-8 with Hyperdisk Balanced at 20,000 IOPS, with 20-minute epochs.'
- new: 'ten validators in ten regions, c3-highcpu-8, Hyperdisk Balanced at 20,000 IOPS, 20-minute epochs.'
C6 (-8 words)
- old: 'The load had 600 senders with a window of 16; its mixed phase ran from 00:54:44 to 01:34:53 UTC on 2026-11-17.'
- new: 'Load: 600 senders, window 16, mixed phase 00:54:44 to 01:34:53 UTC on 2026-11-17.'
C7 (+3 words)
- old: 'plus the open stack of #1862 (the fixes for #1804 and #1807 and the epoch-record work) with its switches on (`quorum_exec_block` with a floor of 8 outputs, `vote_queue_fix`), plus log fields.'
- new: 'plus the stack of #1862 (the fixes for #1804 and #1807 and the epoch-record work; #1862 itself merged since) with all its switches on, `quorum_exec_block` at a floor of 8 outputs, plus log fields.'
C8 (-19 words)
- old: '- In epoch 3 validator-10 ran 25 to 53 outputs behind the most advanced validator.\n  The lag built up from 00:54 to 00:58, when its persist time was 377 and 414 ms per output against 279 and 282 ms on validator-02 (two 2-minute buckets).'
- new: "- Validator-10's execution lag built up from 00:54 to 00:58: persist took 377 and 414 ms per output against 279 and 282 ms on validator-02."
C9 (+3 words)
- old: 'and 23 re-proposals.'
- new: 'and 23 re-proposals in 22 s.'
C10 (-6 words)
- old: '- It logged the boundary at 01:04:06.950.\n  At 01:04:09.429: `we are behind, go to catchup mode! epoch=4'
- new: '- At 01:04:09.429: `message="we are behind, go to catchup mode!" epoch=4'
C11 (-9 words)
- old: '- Catch-up logged 147 `rejoin not ready` lines, 146 with `reason=round_gap`.\n  For six minutes the handled round trailed the newest by 44 to 60 rounds, and execution by 66 to 96.'
- new: '- From 01:05 to 01:10 its `rejoin not ready … reason=round_gap` lines had the handled round 48 to 66 behind the newest.'
C12 (-6 words)
- old: 'it came back through the 20-round window, not at an epoch record (`attempting to rejoin consensus … round_gap=20 rejoin_window=20`), and it was `CvvActive`'
- new: 'it came back through the 20-round window (`attempting to rejoin consensus … round_gap=20 rejoin_window=20`) and was `CvvActive`'
C13 (-9 words)
- old: '15,821 vote requests `behind`; the one vote it signed came after the promotion.'
- new: '15,821 vote requests `behind`.'
C14 (+8 words)
- old: '- Validator-07 at the next close, 20 minutes later: 54 internal-error answers about'
- new: '- Validator-07 at the next close, 20 minutes later, with validator-05 killed by plan: 54 internal-error answers from eight voters about'
C15 (-6 words)
- old: '- In the other bench 8 run of the same build (r20261116-2011, floor 16) no validator'
- new: '- In run r20261116-2011 (same build, floor 16) no validator'
C16 (-7 words)
- old: 'On main at f25a74eb7.\nEvery location is also on the build, at other line numbers; none exists only in the stack.'
- new: 'On main at f25a74eb7, before #1862 merged; every location is also on the build.'
C17 (-16 words)
- old: '- Whether a shorter way back exists for a node 24 s late at a close.\n'
- new: (deleted)
C18 (-3 words)
- old: 'at a loaded close: we have not run main under this load.'
- new: 'at a loaded close (not run under this load).'
C19 (-10 words)
- old: "- It is one run, with the stack's switches on.\n"
- new: (deleted)
C20 (-12 words)
- old: 'or map a closed channel in `identify_unknown_certificates`, and answer with the existing `InvalidEpoch`.\n  The proposer could stop re-proposing once a quorum says the epoch ended.'
- new: 'or map the dropped reply in `identify_unknown_certificates`, and answer with the existing `InvalidEpoch`.'
C21 (-11 words)
- old: "- Part 2: #1806's levers shorten how late the slowest member reaches a close.\n  The certificate rule could measure"
- new: '- Part 2: the certificate rule could measure'
C22 (-2 words)
- old: 'one validator slowed with `TN_TEST_EXECUTION_DELAY_MS` (`crates/types/src/test_hooks.rs:117`) so it reaches a close a few seconds late; its last header should draw an epoch answer and no fatal vote error.'
- new: 'slow one validator with `TN_TEST_EXECUTION_DELAY_MS` (`crates/types/src/test_hooks.rs:117`) so it reaches a close seconds late; its last header should draw an epoch answer, not a fatal vote error.'
C23 (-19 words)
- old: '- On a fleet: per close, count the error string and `tn_node_mode_transitions_total{reason="epoch_behind"}`, and time each demotion to its `reason="rejoin"`.\n'
- new: (deleted)
C24 (-1 words)
- old: 'entered the new epoch at round 39, one round short of this demotion; its bench-6 comment reports demotions'
- new: 'entered a new epoch at round 39, one round short of this demotion; bench 6 saw demotions'
C25 (+0 words)
- old: 'This run adds a validator never killed, inactive for 8 min 35 s, and a repeat at the next close.'
- new: 'This run adds the demotion itself, a catch-up that finished under load (#1806 expected one that cannot), and a repeat.'
C26 dropped: a path counts as one word, so shortening it saves nothing; keep the full path.
C27 (-5 words)
- old: '- #1857: the same 20-round rule, for a validator restarted hundreds of rounds behind; here the gap was 44 to 80 rounds and closed under load.'
- new: '- #1857: the same 20-round rule, for a restart hundreds of rounds behind; here at most 80 rounds, closed under load.'
C28 (-21 words)
- old: '- #1510: a validator killed across a close stayed frozen in the finished epoch; here nothing was killed and it rejoined.\n'
- new: (deleted)
C29 (-26 words)
- old: '- #1804: its fix was on in this run; whether it changes how far behind a slow member gets at a close we did not measure.\n'
- new: (deleted)
C30 (-1 words)
- old: 'The quorum of 7 had one spare voter fewer for those nine minutes.'
- new: 'The quorum of 7 had one spare voter fewer for nine minutes.'
