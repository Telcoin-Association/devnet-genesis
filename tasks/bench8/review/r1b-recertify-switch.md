# Review RV-1b: removal of `epoch_record_recertify` (a5be61615..b67c0acdd)

Reviewer: RV-1b, 2026-11-16. Commit read with `git diff -w` and `git show b67c0acdd:<path>`, never the working tree. Seven files, +312 / -394. No cargo run by me. The writer's gate logs in `tn-b8-uc/target/tmp/` say `EXIT=0` for check, fmt, clippy and nextest (735 passed, 5 skipped). Clippy ran before the last edit, which only changed literals in two tests.

**Verdict: approve with follow-ups.** Critical 0, High 0, Medium 0, Low 6.

## The four questions

1. **Is any of the off arm left? No.** `git grep -n -w epoch_record_recertify b67c0acdd -- crates docs` finds nothing. Neither `epoch_votes.rs` nor `epoch_record_walk.rs` mentions a switch any more. `recertify: bool` is gone from `spawn_epoch_vote_collector` (tip :645-651) and from `revote_uncertified_epoch_record_on_startup` (:786-789). The config field, its default and its `runtime_switches!` entry are gone (config/node.rs base :418-442, :596, :800). Both readers are gone from node.rs (base :1329, :1339). Both `STACK_SWITCHES_*` lists drop from 5 entries to 4 (fleet.rs:102, :111).
2. **Did a statement on a kept path change? No.** Every hunk is a wrapper, the switch read, or a doc:
   - `retained.round_kind(epoch_rec.epoch)` (tip :183) is exactly the `Some` arm of the old `retained.as_ref().map_or(RoundKind::Current, |r| r.round_kind(epoch_rec.epoch))`.
   - The six `if let Some(retained) = &retained` wrappers go and nothing else changes (base :186, :229, :304, :446, :729, and test :4454). Their bodies are unchanged under `-w`.
   - rustfmt joined `if (index as usize) < epoch_rec.committee.len() && kept_signers.insert(index)` (tip :466). The operands and the short-circuit order are the same.
   - `RetainedEpochVotes::default()` (tip :651) is the value `recertify.then(RetainedEpochVotes::default)` produced with the switch on.
   - The pick call now takes `&retained` (tip :713-722). The base on-arm passed the same reference.
   - The startup gate `else if holds_uncertified_before(db, record.epoch)` (tip :799) is the base `recertify && …` with `recertify = true`.
   - The new "Scope" doc (tip :773-781) matches what the base on-arm doc said: the "N certified, N-1 uncertified" shape is healed by writing the certified latest record to the watch.
3. **Was a test of the kept behaviour deleted or weakened? No.** Details under "Tests" below.
4. **Does any doc, comment or log text still speak of the switch?** None names it. Two private labels remain (L1, L2). One operator note was lost with the field doc (L4).

Log lines and metrics are unchanged. The names checked at tip: `epoch record re-certify round` (:876), `re-arming epoch vote rounds to re-certify older epoch records` (:803), `re-arming epoch vote round for stored-but-uncertified epoch record` (:795), `epoch record certified from kept votes`, `tn_node.epoch_record_recertify_rounds_total{result}`, `tn_node.epoch_record_retained_votes`, `tn_node.epoch_record_signers`, `tn_node.epoch_record_missing_signers_total{round}`. No metric or log call is in the `-w` diff.

## Tests

**Deleted**
- `test_switch_off_revotes_only_the_previous_record` (base :3735). The brief names it, and it only tested the off arm.
- `test_startup_revote_skips_certified_record` (base :1271-1294). This one was upstream main's. It stored record 0 uncertified behind a certified record 1, called the startup function with `false`, and asserted that the watch stays empty.
  - That outcome is now reversed on purpose: the shape now re-arms. The tip asserts the new outcome in row `(false, true)` of `test_startup_rearm_recertifies_behind_a_certified_latest_record` (tip :3676-3702).
  - Its title claim, "a certified latest record stays quiet", is still true when nothing older is uncertified. Row `(true, false)` asserts that (all of records 0-2 certified, watch `None`).
  - The deleted test never asserted that a certified record gets no vote: it only checked that nothing was armed. That property has moved to the collector's guard at tip :727, which has no test (L3).

**Edited, with the arithmetic checked against the pick rule**
- The rule: `pick_recertify_record` takes the uncertified records in `N-16 ..= N-2`, in epoch order, and picks `N % count`. `closes_with_the_hook` stores records 0..=4 uncertified, sets the hook on epoch 3, and closes 3 and then 4.
  - Close 3: the failsafe votes 2; the pick is 3 % |{0,1}| = 1, so record 1; the own vote for 3 is hook round 1.
  - Close 4: the failsafe for 3 is hook round 2; the pick is 4 % |{0,1,2}| = 1, so record 1 again; then the own vote for 4.
  - With n=1 that gives {1,2,3,4}; with n=2, {1,2,4}. The tip's expectations (:3947, :3956) match.
- At base, `closes_with_the_hook` passed `false` (the hunk at base ~:3992), so both tests ran with the switch off. The old sets {2,3,4} and {2,4} were the off-arm values.
- The assertions are as strong as before: an exact set and exact hook lines. They now also cover the picks.

**Nine `None` fixtures now pass `RetainedEpochVotes::default()`** (tip :2136, :2214, :2283, :2305, :2581, :2671, :2860, :3047, :3386)
- These behave as before. On a fresh value `latest` is 0, so `round_kind` returns `Current` (tip :998-1004), the same as the old `None`. The kept set starts empty.

**Removed rows, all off-arm only**
- The startup re-arm test's `(false, false, false)` row.
- The two `queue_after_a_new_round(false, _)` asserts. They expected the same values as the `true` rows, which are kept: `[10,6,7,8,1]` and `[10,4,7,8,1]`.
- The `(false, 3, false, Current)` row of `test_recertify_round_stops_on_a_conflicting_record`.
- The `false` pass of `test_older_rounds_do_not_evict_the_latest_close`. The single remaining pass keeps every assertion; only the panic text changed.

**Eleven call sites that passed `false` now run the always-on path, with unchanged expectations** apart from the two hook tests above. Ten are `spawn_epoch_vote_collector` calls in tests; one is the startup function.

## e2e `epoch_record_walk.rs`

**The walk is tested at least as strongly as before.**
- These assertions are unchanged under `-w`: the given-up line on every validator, no node holding K certified, certified-through equal to K-1, `assert_epoch_records(K+1..=K+2)`, and the walk counts per process.
- The Walk arm now withholds 64 rounds (`WALK_WITHHOLD_ROUNDS`, :59-64).
  - K = 1, and K is the only candidate, so each validator signs about 2 + 1-3 rounds per close. 64 leaves wide room.
  - The added `started < 64` check (:447-454) shows that the hook never ran out.
- The new positive assertions replace `assert_no_log(RECERTIFY_LOG)`, which was a property of the off arm:
  - every validator logs a pick, and every pick is for K;
  - `certified` is 0;
  - `short` reaches at least 1 (:605-635).

**Flakiness, reasoned from the code:**
- **The one-shot pick-line read.** It runs in `check_after_load`. That is after `wait_for_epoch_on_all(K+3)` (:325-326) and after the observer windows. The pick line is logged before the hook check (epoch_votes.rs:876 before :881), so the withholding validators log it too. The match is on whole tokens (common.rs:654-656), so `epoch=1` does not match `epoch=10`.
- **The `short` poll.** `labelled_counter` scrapes the metrics live (:799-800), and `poll` retries every 500 ms. A round evicted from the queue also counts as `short` (epoch_votes.rs:853-854).
- **Remaining risk** is in L5 and L6.

## Findings

**Low**
- **L1:** private label at `epoch_votes.rs:3239` (tip): `/// P2's same-digest branch: …`. Write "The same-digest branch of the peer recovery: …".
- **L2:** private label at `epoch_votes.rs:4572` (tip): `/// V3: while the rounds of the latest close collect, …`. Drop "V3: ". The base had 3 labels; the commit removed the V3 in the eviction test doc.
- **L3:** no test shows that a certified latest record re-armed at startup gets no vote of this node's own.
  - The only guard is the collector's `cert_by_digest(epoch_hash).await.is_none()` check at tip :727. It already existed at base, but this path now runs on every restart that holds an uncertified record within the 16-epoch lookback.
  - If it regressed, the result would be gossip noise only: the handler drops votes for certified records (:557).
  - Suggestion: in the `(false, true)` row, feed the armed watch to `spawn_epoch_vote_collector` and assert that the published epochs are {1} (failsafe + pick, no 2).
- **L4:** the field doc removed from `config/node.rs` (base :432-440) carried the only operator note that a conflicting older record "stops the node again until an operator acts", because a restart does not change the stored record.
  - At tip, `test_recertify_round_stops_on_a_conflicting_record` (:4407-4411) documents the stop, but not the repeat.
  - Carry the note into the doc of `recertify_older_record` (tip :846-854) or into the PR text.
- **L5:** the Walk arm's "every pick is for K" check (:609-619) needs no other record at or below N-2 to be uncertified on any validator at any close until the end of the run.
  - The Recertify arm makes the same assumption (:552-558), but only around close K+2, because K certifies there. Here the window is every close of the run.
  - In a healthy 4-validator fleet it should hold. If it flakes, relax it to "at least one pick for K".
- **L6:** comment lines left short after the switch words were cut; re-wrap them:
  - `epoch_votes.rs:1164` ("before it, `recertify` for an older")
  - `epoch_votes.rs:4573` ("older records start five more rounds; the")
  - `epoch_close_forms.rs:209` ("of a re-certify pick: at the close")
  - `epoch_record_walk.rs:184` ("The close of `K + 2` re-votes the")

  A related harness-wide risk: the hook-rounds check (:437-462) now reads a log that is still growing, because picks continue at every close. A torn last line would break the consecutive-round comparison. This is unlikely, since tracing writes whole lines.

## Commit message
- No bench figure, no private label and no attribution.
- `Refs #1850`, with `Topic: remove-bench-switches` last.
- It says what goes and what stays, and gives the walk test's plumbing change in one sentence. It does not say that the Walk arm's "no re-certify log" check became positive assertions. That is acceptable.

## Checked and fine
- config/node.rs: the field, its default and its `runtime_switches!` entry only.
- node.rs: the two argument lines only.
- test_hooks.rs:254: the doc now describes the behaviour.
- fleet.rs: entries and lengths, 5 to 4.
- epoch_close_forms.rs: docs at :206, :209 and :1061 only.
- epoch_votes.rs: plumbing, docs and off-arm tests only; `round_kind` is identical.
- epoch_record_walk.rs: plumbing, plus the walk assertions the ruling asked for.
