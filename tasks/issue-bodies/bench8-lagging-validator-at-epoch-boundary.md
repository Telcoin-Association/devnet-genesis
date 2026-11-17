# A validator late to a loaded epoch close gets internal-error vote answers, then sits out about nine minutes in catch-up

Part 1 is new: a voter that has closed an epoch answers a vote request for a header of that epoch with an internal error, and the proposer treats it as fatal.
Part 2 is the `epoch_behind` demotion at a loaded close that #1806 predicted; it could go to #1806 as a comment, leaving part 1 as a short issue.

## What happens

In run r20261116-2332, validator-10, never restarted, was behind in execution when the other validators closed epoch 3 under load.
It proposed one more header of epoch 3, 71 ms after the last of them logged `epoch boundary detected`.
Every voter answered `Error processing header vote request: Failed to return pending certificate manager result.`, then, once in epoch 4, `Invalid epoch. Peer proposed epoch 3, but expected 4`.
It logged the boundary 23.8 s after the others, was demoted to `CvvInactive` with `reason=epoch_behind`, and was out 8 min 35 s: 541 s without a header, and no vote signed until its promotion.
Validator-07 did the same at the next close.

## Evidence

One run of one configuration, not published: ten validators in ten regions, c3-highcpu-8, Hyperdisk Balanced at 20,000 IOPS, 20-minute epochs.
Load: 600 senders, window 16, mixed phase 00:54:44 to 01:34:53 UTC on 2026-11-17.
The node was a benchmark build at b1104905f: main at 45dce8947 plus what #1862 has since merged (the fixes for #1804 and #1807 and the epoch-record work), from before its runtime switches were removed, with every switch on and `quorum_exec_block` at a floor of 8 outputs, plus log fields.

- Its execution lag built up from 00:54 to 00:58: persist took 377 and 414 ms per output against 279 and 282 ms on validator-02.
- Its round-3276 header went out at 01:03:43.240; the others logged the boundary from 01:03:43.075 to 01:03:43.169.
  Its log has 62 internal-error answers from all nine voters until 01:03:55.411 and 154 epoch answers until 01:04:06.695, each logged as `fatal request for requested vote`, and 23 re-proposals in 22 s.
- At 01:04:09.429: `message="we are behind, go to catchup mode!" epoch=4 exec_epoch=3 number=None … round=41 … gc_window=40 reason=epoch_behind`.
- From 01:05 to 01:10 its `rejoin not ready … reason=round_gap` lines had the handled round 48 to 66 behind the newest.
  At 01:12:43.824 it came back through the 20-round window (`attempting to rejoin consensus … round_gap=20 rejoin_window=20`) and was `CvvActive` at 01:12:44.092.
- From 01:03:43.240 to its next header at 01:12:44.716 it answered 15,821 vote requests `behind`.
  The quorum of 7 had one spare voter fewer for nine minutes.
- Validator-07 at the next close, 20 minutes later, with validator-05 killed by plan: 54 internal-error answers from eight voters about its round-2938 header of epoch 4, demotion at `round=41`, 8 min 40 s inactive, 550 s without a header, 15,758 `behind` answers and none signed.
- In run r20261116-2011 (same build, floor 16) no validator went more than 30 s without a header, apart from start-up and a planned kill.

## Where in the code

On main at 5533ff73a, which holds #1862; every location is also on the benchmark build.

Part 1:

- The vote path's `identify_unknown_certificates` sends `CertificateManagerCommand::FilterUnkownDigests` and awaits a oneshot reply; a dropped reply becomes `HeaderError::PendingCertificateOneshot` (`crates/consensus/primary/src/state_sync/header_validator.rs:288-293`, `crates/types/src/error.rs:332-333`).
- The certificate manager answers that command (`crates/consensus/primary/src/state_sync/cert_manager.rs:339-342`) only until its loop returns on shutdown (`:355-356`).
- The certifier treats any `RPCError` answer as fatal for that voter and header (`crates/consensus/primary/src/certifier.rs:249-263`); the proposer re-proposes after its max delay (`crates/consensus/primary/src/proposer.rs:1685`).
- Inferred from the times: each voter's epoch-3 certificate manager had stopped at its close while its vote handler still took epoch-3 requests.
  Validator-02, a voter, logged `Certifier received shutdown` at 01:03:43.156 and `Starting epoch` at 01:03:48.265; the error is the dropped-reply variant, not a send error.
- These answers come before the gap between two epochs, not in it: with no event loop the gap policy drops every inbound request and the requester retries (`crates/consensus/primary/src/network/gap_policy.rs:91-94`, `:108-115`), so an answered request reached an event loop that was still serving after its certificate manager had stopped (inferred from that code and the times).

Part 2:

- `number=None` is the certificate rule of `behind_consensus`: a node executing the previous epoch passes only while the new epoch's round is at most `gc_depth.max(6)`, 40 here (`crates/consensus/primary/src/network/handler.rs:367-375`, demotion at `:419-463`).
  The header rule beside it compares output numbers (`:362-366`).
- Rejoin needs the handled round within `rejoin_round_window`, 20 rounds, of the newest (`crates/types/src/primary/mod.rs:87`, `crates/consensus/executor/src/subscriber.rs:136`).

## What is not known

- Why validator-10's persist time rose from 00:54 to 00:58.
- Where the command or its reply is dropped.
- Whether main without the stack falls this far behind at a loaded close (not run under this load).

## What could be done (suggestions, none tried)

- Part 1: check the header's epoch against a closed epoch before the certificate-manager round trip, or map the dropped reply in `identify_unknown_certificates`, and answer with the existing `InvalidEpoch`.
- Part 2: the certificate rule could measure lateness in outputs, as the header rule does, rather than in the new epoch's rounds.

## How to tell more, and how to verify

- An e2e test (not built): slow one validator with `TN_TEST_EXECUTION_DELAY_MS` (`crates/types/src/test_hooks.rs:126`) so it reaches a close seconds late; its last header should draw an epoch answer, not a fatal vote error.

## Related

- #1806: in bench 5 a slow member entered a new epoch at round 39, one round short of this demotion; bench 6 saw demotions of 4.05 s and 4 minutes.
  This run adds the demotion itself, a catch-up that finished under load (#1806 expected one that cannot), and a repeat.
  Validator-10's 843 `Failed to track spawned task … no available capacity` lines are #1806's task-tracker overflow (`crates/types/src/task_manager.rs:218-227`).
- #1857: the same 20-round rule, for a restart hundreds of rounds behind; here at most 80 rounds, closed under load.
- #1792, fixed by #1793: a restarted validator whose start-up record sync ended one epoch short.
  A validator exactly one epoch behind is demoted by the same certificate rule once the next epoch passes about forty rounds (the doc of `certified_record_closes_running_epoch`, `crates/node/src/manager/node/run_epoch.rs:1396-1408`); part 2 measures what that rule and the rejoin window cost under load.
  Validator-10 held no certified record of epoch 3 until 01:03:57.471 while the other nine were closing: the state the review of #1793 describes, a lagging peer that answers "not held" while the others drop the request; no node was syncing at that moment, so that case did not occur in this run.
- #1516, fixed on main by #1547: the same condition on the gossip path (a certificate handed to a certificate manager that is not running); #1547 leaves the vote path as it is.
