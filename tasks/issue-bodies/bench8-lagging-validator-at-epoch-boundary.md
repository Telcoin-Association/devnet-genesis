# A validator late to a loaded epoch close gets internal-error vote answers, then sits out about nine minutes in catch-up

Two things happened at one event, kept apart below.
Part 1 is new: a voter that has closed an epoch answers a vote request for a header of that epoch with an internal error, and the proposer treats it as fatal.
Part 2 is the `epoch_behind` demotion at a loaded close that #1806 predicted; it could go to #1806 as a comment, leaving part 1 as a short issue.

## What happens

In benchmark run r20261116-2332, validator-10, never restarted, was behind in execution when the other validators closed epoch 3 under load.
It proposed one more header of epoch 3, 70 ms after the last of them logged `epoch boundary detected`.
Every voter answered `Error processing header vote request: Failed to return pending certificate manager result.`, then, once in epoch 4, `Invalid epoch. Peer proposed epoch 3, but expected 4`.
It re-proposed the header about once a second for 22 s.
It logged the boundary itself 23.8 s after the others, was demoted to `CvvInactive` with `reason=epoch_behind`, and stayed in catch-up for 8 min 35 s.
For 541 s it proposed no header and signed no vote.
Validator-07 did the same at the next close.

## Evidence

One run of one configuration, not published: ten validators in ten regions (Asia, Australia, Europe, the US) and one observer, on c3-highcpu-8 with Hyperdisk Balanced at 20,000 IOPS, with 20-minute epochs.
The load had 600 senders with a window of 16; its mixed phase ran from 00:54:44 to 01:34:53 UTC on 2026-11-17.
The node was main at 45dce8947 plus the open stack of #1862 (the fixes for #1804 and #1807 and the epoch-record work) with its switches on (`quorum_exec_block` with a floor of 8 outputs, `vote_queue_fix`), plus log fields.

- In epoch 3 validator-10 ran 25 to 53 outputs behind the most advanced validator.
  The lag built up from 00:54 to 00:58, when its persist time was 377 and 414 ms per output against 279 and 282 ms on validator-02 (two 2-minute buckets).
- Its round-3276 header went out at 01:03:43.239; the others logged the boundary from 01:03:43.075 to 01:03:43.169.
  Its log has 62 internal-error answers from all nine voters until 01:03:55.411 and 154 epoch answers until 01:04:06.694, each logged as `fatal request for requested vote`, and 23 re-proposals.
- It logged the boundary at 01:04:06.950.
  At 01:04:09.429: `we are behind, go to catchup mode! epoch=4 exec_epoch=3 number=None … round=41 … gc_window=40 reason=epoch_behind`.
- Catch-up logged 147 `rejoin not ready` lines, 146 with `reason=round_gap`.
  For six minutes the handled round trailed the newest by 44 to 60 rounds, and execution by 66 to 96.
  At 01:12:43.824 it came back through the 20-round window, not at an epoch record (`attempting to rejoin consensus … round_gap=20 rejoin_window=20`), and it was `CvvActive` at 01:12:44.092.
- From 01:03:43.239 to its next header at 01:12:44.716 it answered 15,821 vote requests `behind`; the one vote it signed came after the promotion.
  The quorum of 7 had one spare voter fewer for those nine minutes.
- Validator-07 at the next close, 20 minutes later: 54 internal-error answers about its round-2938 header of epoch 4, demotion at `round=41`, 8 min 40 s inactive, 550 s without a header, 15,758 `behind` answers and none signed.
- In the other bench 8 run of the same build (r20261116-2011, floor 16) no validator went more than 30 s without a header, apart from start-up and a planned kill.

## Where in the code

On main at f25a74eb7.
Every location is also on the build, at other line numbers; none exists only in the stack.

Part 1:

- The vote path's `identify_unknown_certificates` sends `CertificateManagerCommand::FilterUnkownDigests` and awaits a oneshot reply; a dropped reply becomes `HeaderError::PendingCertificateOneshot` (`crates/consensus/primary/src/state_sync/header_validator.rs:288-293`, `crates/types/src/error.rs:332-333`).
- The certificate manager answers that command (`crates/consensus/primary/src/state_sync/cert_manager.rs:339-342`) only until its loop returns on shutdown (`:355-356`).
- The certifier treats any `RPCError` answer as fatal for that voter and header (`crates/consensus/primary/src/certifier.rs:243-257`); the proposer re-proposes after its max delay (`crates/consensus/primary/src/proposer.rs:1337`).
- Inferred from the times: each voter's epoch-3 certificate manager had stopped at its close while its vote handler still took epoch-3 requests.

Part 2:

- `number=None` is the certificate rule of `behind_consensus`: a node executing the previous epoch passes only while the new epoch's round is at most `gc_depth.max(6)`, 40 here (`crates/consensus/primary/src/network/handler.rs:353-358`, demotion at `:402-446`).
  The header rule beside it compares output numbers (`:348-352`).
- Rejoin needs the handled round within `rejoin_round_window`, 20 rounds, of the newest (`crates/types/src/primary/mod.rs:87`, `crates/consensus/executor/src/subscriber.rs:136`).

## What is not known

- Why validator-10's persist time rose from 00:54 to 00:58.
- Where the command or its reply is dropped.
- Whether a shorter way back exists for a node 24 s late at a close.
- Whether main without the stack falls this far behind at a loaded close: we have not run main under this load.
- It is one run, with the stack's switches on.

## What could be done (suggestions, none tried)

- Part 1: check the header's epoch against a closed epoch before the certificate-manager round trip, or map a closed channel in `identify_unknown_certificates`, and answer with the existing `InvalidEpoch`.
  The proposer could stop re-proposing once a quorum says the epoch ended.
- Part 2: #1806's levers shorten how late the slowest member reaches a close.
  The certificate rule could measure lateness in outputs, as the header rule does, rather than in the new epoch's rounds.

## How to tell more, and how to verify

- An e2e test (not built): one validator slowed with `TN_TEST_EXECUTION_DELAY_MS` (`crates/types/src/test_hooks.rs:117`) so it reaches a close a few seconds late; its last header should draw an epoch answer and no fatal vote error.
- On a fleet: per close, count the error string and `tn_node_mode_transitions_total{reason="epoch_behind"}`, and time each demotion to its `reason="rejoin"`.

## Related

- #1806: in bench 5 a slow member entered the new epoch at round 39, one round short of this demotion; its bench-6 comment reports demotions of 4.05 s and 4 minutes.
  This run adds a validator never killed, inactive for 8 min 35 s, and a repeat at the next close.
  Validator-10's 843 `Failed to track spawned task … no available capacity` lines (01:04:14.264 to 01:04:20.170) are #1806's task-tracker overflow (`crates/types/src/task_manager.rs:199-208`).
- #1857: the same 20-round rule, for a validator restarted hundreds of rounds behind; here the gap was 44 to 80 rounds and closed under load.
- #1510: a validator killed across a close stayed frozen in the finished epoch; here nothing was killed and it rejoined.
- #1804: its fix was on in this run; whether it changes how far behind a slow member gets at a close we did not measure.
