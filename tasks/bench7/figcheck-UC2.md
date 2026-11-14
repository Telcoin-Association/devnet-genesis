# Figure-check FC-UC2: tasks/issue-comments/bench6-1804.md (comment on #1804)

Checked 2026-11-14 against: the report `tasks/bench6-report-r20261113-1351.md` (§4.3 lines 353-386, §8 lines 645-863), `benchmark/private/bench6-r20261113-2118/A7/comparison.md` (C3), `benchmark/private/bench6-r20261113-1351/A7/comparison.md` (C2), `benchmark/private/bench6-r20261113-1351/I-10/findings.md`, `benchmark/private/bench6-r20261113-2118/I-10/findings.md` and `findings-r20261114-0000.md`, `benchmark/private/bench6-r20261113-2118/A2/certification.md` and `vs-always-on.md`, `benchmark/private/bench6-r20261113-1351/A2/certification.md`, `benchmark/private/bench6-r20261112-1520/A7/verdicts.md`, `tasks/bench5-report-r20261107-1504.md`, issues #1804 and #1782 as they stand (both OPEN, no comments), and the code at 45dce8947 (read with `git show 45dce8947:<path>`), 2df831e3c and 4d6ab6191.
Line numbers in the report are the file as it is now (§8 starts at :645, not :642 as the writer's notes say).

## Verdict

FIX

No error changes a conclusion; five statements need new text before posting (one definition overstated, one test located on `main` that is not on `main`, one window label, one total that disagrees with the issue it is posted on, one causal attribution stronger than the four runs).

## Errors

1. Line 6, the always-on definition: "as parents name earlier picks of that rule, every header names its author's executed tip minus 8 outputs, the floor."
   The source does not say every header.
   Report :364 (§4.3): "names its author's own tip minus 8 executed outputs on 97-99 % of headers".
   `bench6-r20261113-2118/I-10/findings.md`:15 and :60: in r20261113-1351 "0.2 % and 7.59 outputs (about 5.5 s) always-on, where 9 of 10 authors named exactly tip minus 8"; mean 7.59, p50 8, p95 8.
   `bench6-r20261113-2118/I-10/findings-r20261114-0000.md`:43: in r20261113-1630 before the kill the basis was own tip 9.0 %, quorum 4.9 %, floor 86.1 %; `bench6-r20261113-1351/I-10/findings.md`:47: validator-05 named its own tip on 3,570 of 4,034 headers.
   The report's own §8 intro (:648) uses "every header", which is where the comment's wording comes from; §4.3 and the per-header data say otherwise, and the comment itself gives 5.5 s (7.59 outputs) two paragraphs later.
   Replace with: "Always-on: (D)'s rule on every header; as parents name earlier picks of that rule, an author ahead of the quorum settles on its executed tip minus 8 outputs, the floor (in r20261113-1351 nine of ten authors named exactly that; 7.59 outputs behind the tip on the mean)."

2. Line 38: "The unit test `vote_queued_requests_of_one_author_wait_in_turn`, on `main` as it is, answers …"
   The test is not on `main`: `git grep vote_queued_requests_of_one_author_wait_in_turn 45dce8947` finds nothing; it exists only in commit 4d6ab6191 (parent 45dce8947, test-only, +85 lines in `crates/consensus/primary/src/tests/network_tests.rs`, test at :5539).
   A maintainer reading "on `main`" will look for it there.
   What the test asserts matches the rest of the sentence (six requests per author, k-th answer at k × `VOTE_EXECUTION_WAIT`, all `ExecutionBehind`, the sixth after `vote_timeout`; it calls `handler.vote` directly, no requests cancelled, no network layer).
   Replace with: "A unit test run against `main` as it is, `vote_queued_requests_of_one_author_wait_in_turn` (it comes with the voter-side PR), answers six queued requests of one author one second apart, the sixth after the 5 s vote timeout."

3. Line 16, window label: "0 and 15 over the 20,000 IOPS mixed phases."
   The 0 and 15 are Prometheus counts over blast 2's mixed phase only (report :714; C3:66); r20261113-1351 had 9 in blast 1's mixed phase (same rows), so "the mixed phases" read as all of them is wrong for that run.
   Replace "0 and 15 over the 20,000 IOPS mixed phases" with "0 and 15 over the 600 × 16 blast's mixed phase in r20261113-1351 and r20261113-2118".

4. Line 16, "refused-behind votes: 47,614 over that run".
   47,614 is the sum of the bench-5 report's run totals (`tasks/bench5-report-r20261107-1504.md`:599: 14,785 + 11,953 + 5,744 + 3,167 + 2,725 + 2,558 + 2,557 + 2,220 + 1,317 + 588 = 47,614; C2:31 "the sum is my arithmetic"; report :359).
   The issue this comment is posted on lists other counters for the same run (#1804 body, "Counters over the run": 14,802, 11,969, 5,747, 3,171, 2,728, 2,559, 2,558, 2,222, 1,317, 588), which add to 47,661.
   A reader who adds the issue's list gets a different total.
   Replace "47,614 over that run" with "more than 47,600 over that run" (true for both sources), or with "47,661 over that run (the counters above)".

5. Lines 33-34, attribution of the lock figure to the switch (a strength error, not a wrong number).
   The figures are right: `lock_ms` p95 is 0 on every voter in every window of all four runs (`bench6-r20261113-1351/A2/certification.md`:147 for r20261113-1351 and r20261113-1630; `bench6-r20261113-2118/A2/certification.md`:16 and the per-window tables at :66 and :308, all 0, log-side so validator-07's missing Prometheus series does not matter); bench 5's validator-01 waited 7.3-8.5 s (#1804 body; bench-5 report :584).
   But the sentence pair "`vote_queue_fix`, on in all four runs, does … / `lock_ms` p95 was 0 …; bench 5's validator-01 waited 7.3-8.5 s" credits the switch with the drop from bench 5, and the four runs cannot show that: the author-side rule was also on in all four (report :145, :672), and it alone removes most execution waits, so the four runs show the level, not the switch's effect.
   What does tie the 0 to the switch, inside the four runs: the slow voters still waited the full second, before the lock (`prelock_wait_ms` p95 1,001 ms in r20261113-1630 and r20261114-0000; C3:160; `bench6-r20261113-2118/A2/vs-always-on.md`:128).
   The arm walk r20261112-1520 (3,597-7,892 ms off, 0 on, 1,558-3,993 ms off again; `bench6-r20261112-1520/A7/verdicts.md`:418, report :384) is not a single-switch toggle either: the switch came on in arm `v-vote` together with `quorum_exec_block` and `epoch_record_state_check` (verdicts.md:128) and went off in `a0-prime` with every switch (verdicts.md:370, :387; report :357).
   Minimal fix, after line 34, add: "The author-side rule was on in all four runs too, so they show the level, not what the switch alone did; the slow voters still waited the full second, now before the lock (`prelock_wait_ms` p95 1,001 ms in r20261113-1630 and r20261114-0000)."
   Optional, if length allows: "In an arm walk (r20261112-1520: nine node configurations applied one after another by rolling restart; it has no public page) `lock_ms` p95 went from 3,597-7,892 ms to 0 in every window when the switch came on and back to 1,558-3,993 ms when it went off, each time together with the author-side rule."
   (The sibling comments on #1803 and #1805 describe that run with the same parenthesis.)

## Not traceable

None.
Every figure was found in the named sources; the plan sentences (lines 42-43) trace to the brief, as the brief intends.

## Weak (matched, but stronger or vaguer than the source)

- Line 11, table caption "Own headers certified over proposed, mixed phase": every cell is blast 2's mixed phase with validator-05's outage inside (report :655, :710-711, :732-733); three blasts had mixed phases.
  Suggested: "Own headers certified over proposed, the 600 × 16 blast's mixed phase (validator-05's outage included):".
- Line 7, "(`quorum_exec_block_starved_rounds` 4)": the 4 is never explained, and "starved window" is undefined.
  The bench-6 switch doc (`telcoin-network-b6` 2df831e3c `crates/config/src/node.rs`:329-337) and `bench6-r20261113-1351/I-10/findings.md`:140: the quorum rule applies for K rounds after an own header is cancelled uncertified, doubling while that keeps happening, up to 128 rounds.
  Suggested: "the author's own tip until an own header is cancelled uncertified, then the quorum rule for a window of 4 rounds that doubles while headers keep being cancelled (up to 128)".
- Line 27, "(D) with a floor of 8 holds while the disk binds" is the report's word (§8.5 :829) for both forms, but against the issue's own bar ("at least 98 % on every validator in every loaded window") the adaptive run at 20,000 IOPS dipped in blast 2's first 120 s to 96.3 % on validator-02, six validators under 99 %, while the always-on run stayed at 99.7 % or more (report :713; C3:65).
  The comment omits it; a maintainer checking the bar will find it on the run page.
  Suggested addition to line 20: "; in the blast's first 120 s it certified 97.98 % against 100.0 % (lowest 96.3 %, validator-02)".
- Line 19, "the lead almost never reached the floor": "the lead" is undefined here (C3:320: the author's tip minus the 7th highest tip at the proposal).
  Suggested: "an author's lead over the seventh-ranked member almost never reached the floor (0.01-0.02 % of headers)".
- Line 20, "about 0.9 s old against 5.5 s": a mean before the kill (report :802, 1.21 against 7.59 outputs behind the author's tip); say "on the mean".
- Line 22, "validator-06 ran about 18 outputs ahead of validator-01, so four or five voters lacked the block": one pair does not give "four or five"; the source (report :365; `bench6-r20261113-1351/I-10/findings.md`:12) lists 18 ahead of 01, about 45 ahead of 05 and 7-9 ahead of 04 and 02, and marks rounds-to-outputs as inferred at two rounds per output.
  Suggested: "validator-06 ran about 18 outputs ahead of validator-01, 45 ahead of validator-05 and 7-9 ahead of validator-04 and -02 (outputs inferred from rounds), so four or five of the nine other voters lacked the block a fast author named."
- Line 25, floor arithmetic: values right (`findings-r20261114-0000.md`:116-123: floor 16 fleet 100.0 % on r20261114-0000's tips, 97.0 % on r20261113-1630's; floor 32 100.0 % and 99.9 %), labelled as arithmetic, before the kill, not a run, and as fleet, not every validator.
  Two limits are missing: the baseline is the pre-kill window, where the same method gives 87.0 % and 93.2 % for the floor of 8, not the table's 88.26 % and 94.82 % (B2 mixed); and at floor 16 validator-10 stays at 80.5 % and validator-06 at 90.4 % on r20261113-1630's tips (report :376; `findings-r20261114-0000.md`:121).
  The source also says a different floor would move the tips and rounds the arithmetic holds fixed (report :814; C3:357).
  Suggested: "… a floor of 16 outputs gives fleet certification of 97.0 % (r20261113-1630, validator-10 still 80.5 %) and 100.0 % (r20261114-0000), 32 gives 99.9 % and 100.0 %, against 87.0 % and 93.2 % for the floor of 8 in the same window: arithmetic, not a run, for a block 16 or 32 outputs old, and a different floor would move the tips and rounds it holds fixed."
- Line 28, "resent 3.5 and 1.9 times": correct as all-generators ratios (C3:240: 104,280 / 29,546 = 3.53; 255,453 / 133,975 = 1.91; C3:31 words it the same way).
  It is not the generator-05-left-out ratio (C3:241, :254, report :792: 3.54 and 1.96, which would round to 3.5 and 2.0), and the comment correctly does not say "generator 05 left out"; keep it that way or change 1.9 to 2.0 if that phrase is ever added.
  The writer's notes cite :254 (3.54 / 1.96) for 1.9; the number traces to :240, not :254.
- Line 34, "bench 5's validator-01 waited 7.3-8.5 s for the lock": a traced set (validator-01's refusals of validator-04's rounds 1065-1078 at 17:45, #1804 body), set against a p95 over windows.
  Suggested: "bench 5's validator-01 waited 7.3-8.5 s for the lock on validator-04's requests at 17:45".
- Line 17, "No node logged a fork, halt or unexpected execution result": true for all four runs (report :770); add "in the four runs" since the sentence follows a bench-5 sentence.
- Length: 631 words by `wc -w` (table markup and URLs included) against the brief's 600; the fixes above add words, so something should go (the optional arm-walk sentence first).

## Code claims at 45dce8947 (all hold except the test's location)

- `crates/consensus/primary/src/proposer.rs:385`: `consensus_bus.app().latest_execution_block_num_hash()` passed to `Header::new` (:379-388). Holds.
- `crates/consensus/primary/src/network/handler.rs:1029-1033`: `vote_request` (fn at :985) takes `auth_lock.lock().await`; the guard lives to :1202. Holds.
- `:1158-1180`: `vote_inner` under `timeout(vote_timeout)` while the guard is held. Holds.
- `:1462-1507`: `timeout(VOTE_EXECUTION_WAIT, wait_for_execution(..))`, `ExecutionBehind` on expiry; `VOTE_EXECUTION_WAIT` = 1 s at `crates/config/src/consensus.rs:459`. Holds.
- `:1138-1147`, `:1189-1195`: the only refusal of an older round (`AlreadyVotedForLaterRound`) is under the lock, and a recoverable outcome restores the previous entry, so a newer request refused as behind does not make older queued ones refusable. Before the lock (:992-1025) there are only the peer check and the inactive-node refusal. "Nothing answers a superseded request before it gets the lock" holds.
- `:1845-1855` (`Ok(()) | Err(CertManagerError::Pending(_)) => {}`) and `:1552` (`notify_read_parent_certificates`), inside the `vote_timeout` of :1158: the wait for an attached pending parent runs under the lock. `git log -S` puts the `Pending` arm in b1baed048 (#1842). Holds.
- Vote timeout 5 s: `crates/config/src/node.rs:343-345`. Holds.
- #1822, #1839, #1842, #1844, #1846 are on `main` (ed8ae4b00, 36a7bf599, b1baed048, 1475bb098, b0188d69f). Holds.
- `vote_queue_fix` does what line 33 says: `telcoin-network-b6` 2df831e3c `crates/config/src/node.rs`:341-350. Holds.

## The open question: does a requester's cancel reach the voter on `main`?

No.
On `main` at 45dce8947 the voter's vote future is dropped only when the network layer reports an inbound failure for that request (the 10 s request timeout or a closed connection), on a duplicate request id, or at shutdown; a requester that cancels sends nothing.
- Requester side: `request_vote` (`crates/consensus/primary/src/network/mod.rs:2030-2052`) calls `send_request` (`crates/network-libp2p/src/types.rs:1050-1058`), which queues `NetworkCommand::SendRequest` and returns a oneshot receiver; the certifier's cancel drops the future and that receiver, and nothing more.
  The swarm keeps the request in `outbound_requests` (`crates/network-libp2p/src/consensus.rs:600`, `:1323-1332`) until a response, an outbound failure or a disconnect (`:2848-2867`); libp2p-request-response 0.30.0 has no way to cancel an outbound request, and its inbound worker only ends on the response, the substream timeout, or a stream error (`libp2p-request-response-0.30.0/src/handler.rs:125-170`, `:414-416`).
- Voter side: each forwarded request carries a `cancel` receiver (`consensus.rs:2230-2238`); its sender fires only in `close_inbound` (`:2436-2440`), called on a duplicate request id (`:2253-2259`), on `InboundFailure` for a tracked request (`Timeout`, `ConnectionClosed`, `Io`, `UnsupportedProtocols`, `ResponseOmission`; `:2357-2409`) and after `ResponseSent` (`:2412-2419`).
  The vote task selects the vote against that receiver (`crates/consensus/primary/src/network/mod.rs:3792-3812`).
  The transport timeout is `request_response::Config::default()` (`consensus.rs:784`), 10 s, documented on `main` as `LIBP2P_REQUEST_TIMEOUT` (`crates/config/src/consensus.rs:441-449`: "a voter still evaluating a header when it fires has its vote cancelled").
- So #1842's commit message ("a request the network layer dropped mid-await (its requester cancelled it)") and the code comment it added at `handler.rs:1149-1153` ("the network layer drops this future when the requester cancels the request") describe a path the network layer on `main` does not have; the future is dropped mid-await only through the timeout or a connection close. #1842's change is still correct for those paths.
- What it means for the queue: per author, every request that reached the voter in the last 10 s and is not answered stays queued on the lock, including requests for headers the author has already cancelled. A voter behind on execution serves them one per second, and a request that would wait past 10 s from arrival is dropped by the transport, so the lock wait runs up to about 9-10 s; bench 5 measured up to 9.4 s (#1804 body), the same bound the issue inferred at 067639def.
- For the comment: it claims nothing about cancellation, and the unit test's six never-cancelled requests show no more than the test does; the text needs no change on this point.
  If the orchestrator wants the finding in the comment, a sentence that stays inside what was read: "Read from code, a requester's cancel does not reach the voter on `main`: a queued request stays on the lock until it is answered or the transport's 10 s timeout drops it (`crates/network-libp2p/src/consensus.rs:2357-2409`, `crates/consensus/primary/src/network/mod.rs:3792-3812`), although #1842's commit message and the comment at `handler.rs:1149-1153` say the network layer drops it."

## The comment against the issues

- #1804 (OPEN, no comments): no contradiction except error 4 (the refused-behind total). The comment's (D)/(V) labels, the floor of 8 (the issue's N = 8) and the 7.3-8.5 s figure are the issue's own.
- #1782 (OPEN, no comments): the comment does not mention it and says nothing that contradicts it.

## No promise, no advocacy

The comment promises no result: lines 42-43 state the next steps (the voter-side port now, the author-side PR after a run of both forms at 20,000 IOPS on current `main`) without an expected outcome.
It does not advocate a form: line 28 leaves the form and the floor's depth open, and the costs of each form are both given (the adaptive form's lower certification at 20,000 IOPS in the table, its fresher block, its round-rate cost and the senders' cost at 50,000 IOPS).

## Rule breaches

None.
No unit names, private paths, host or person names, run nicknames, or tool or assistant attribution; every run id is linked to its page at first mention.

## Counts

Figures and statements checked: 54.
Matched: 49 (of which 9 listed under Weak).
Wrong: 5 (errors 1-5; error 5 is a strength error, its numbers are right).
Untraceable: 0.
