# Review RV-4: the order hold always on (unit R4 + R4b)

Commits in `tn-b8-uc`: base de075ab78, dd21a50ef `refactor(primary): the own-chain order hold is always on`, 726a25f1b `test(primary): build the proposer tests on the order hold`. Line numbers are at 726a25f1b unless marked otherwise. No cargo run (reviewer contract).

## Verdict

**Approve with follow-ups.** Critical 0, High 0, Medium 1, Low 6. No statement on the hold's path changed. The five deleted tests drove the no-hold path. The one real leftover is the `stale_resend` accounting, which can no longer fire (M1).

## The four questions

1. **Is anything of the off arm left?** `git grep -w digest_order_hold 726a25f1b -- crates docs` returns only `e2e-tests/tests/it/main.rs:9 mod digest_order_hold;`, which is the file name and is allowed. One piece is left that only the off arm could reach: the `stale_resend` classification and its counter label (M1).
2. **Did a statement on a kept path change?** No. `git diff -w` of `proposer.rs` shows only the `Option` going, the wrappers going and doc text:
   - Plan, record and drain keep the same calls in the same order (:1343-1349).
   - The I2 warning (:1143), the commit-notice guard (:1419) and `digests_held.set(0.0)` at stop (:1510) are now unconditional. That is what the base's on arm did.
   - `drain_held` (:1243) is unchanged. The log fields and metrics are unchanged.
3. **Was a test of the kept behaviour deleted or weakened?** No:
   - All five deleted tests asserted no-hold payloads or no-hold re-queues. What they also pinned is now covered by kept tests, apart from M1 and L6.
   - The four reworked tests keep every assertion. The cancel test now asserts the hold's behaviour in full.
4. **Does any doc still speak of the switch?** `git grep -i switch` over `order_hold.rs`, `proposer.rs` and `metrics.rs` finds nothing. Some "with the hold on" and "the base" wording is left (L1-L3).

## Medium

**M1. The `stale_resend` accounting cannot fire under the always-on hold.**
- Why it cannot fire:
  - The only insert into `proposed_headers` is `proposer.rs:1430`, and it sits behind the guard at :1419 (`if header.round() <= self.committed_own_round { …; return Ok(()); }`).
  - `committed_own_round` only rises (:994), inside the same `process_committed_headers` call that takes every tracked header at or below the committed round out.
  - So a tracked header always has a round above `committed_own_round`. That makes `resent` false at :973 and at :1050, and `stale_resend` is always 0.
  - After a restart `committed_own_round` is 0. A re-proposed header that had already committed is then filed as `unknown_seq`, not as `stale_resend`.
- Where the dead parts are:
  - the classification: :963-975, :1049-1051, :1114-1121, :1159-1162;
  - the label: `metrics.rs:598-617`, `RequeueOrderUnknown::StaleResend`;
  - two docs that describe a state that can no longer happen: :204-207 ("a header tracked there afterwards was put back by a re-send … counted as `stale_resend`") and the tail of the guard comment at :1416.
- Test coverage: the two deleted tests (`test_stale_resend_requeue_is_not_out_of_order`, `test_stale_resend_releases_its_digest_numbers`) were the only ones that made `reason="stale_resend"` non-zero. Every kept `order_totals` assertion has 0 at index 3.
- Fix, as a follow-up and not in this unit, because it changes a published label set:
  - either remove the classification and the label in their own `refactor(primary)` commit, and say so in the PR;
  - or keep the label for dashboards and rewrite :204-207 to say it stays 0 because of the guard.

## Low

- **L1.** `proposer.rs:1409`: "with the order hold on, a header at or below …". Drop "with the order hold on".
- **L2.** `e2e-tests/tests/it/digest_order_hold.rs`: :120-121 "with the hold on.", :152 "With the hold on, every transaction …", and the failure text at :1272 "… out of order with the hold on". The hold has no off state now. Drop "with the hold on".
- **L3.** `order_hold.rs`: :46 (I3 "drains as the base does"), :94-98, :108 and :114 use "the base". No base drain exists in the tree any more. Suggested rewording:
  - I3: "a plan that holds no lane drains every lane: the held-lane filter takes no slot and does not move the cursor".
  - Elsewhere: "a proposer without the hold".
- **L4.** `proposer_tests.rs:3061` "the order this script drained without the hold" and :3111 "drains exactly as without the hold". The list is now derived by hand: I re-derived rows 1-4 and they match. The claim that it equals a no-hold drain is no longer checked by anything. Say "the lane rotation's order with nothing held". The wording at :2981 and :3402 describes the defect and is fine.
- **L5.** `test_lane_sequence_survives_requeues` (:2662-2718):
  - The test doc does not say that the cancel input is forced. Only the comment inside does.
  - That comment says "a commit of round 3 orders round 2 with it". This holds at commit round 5, but the same shape (a cited own parent dies behind its child's commit) can happen past the GC depth. `test_order_hold_warns_once_per_requeue_out_of_order` (:3438, commit at 60) shows it. So only the cancel part is unreachable.
- **L6.** The deleted `test_canceled_requeue_behind_a_newer_digest_counts_out_of_order` pinned that a newer digest counts while its header is still in flight, before it is tracked (`lane_seqs.drained` at drain time). No kept out-of-order test re-queues while the newer header is in flight: both build and track it first. Under the hold this needs a fault, or the GC residual with an in-flight header. Add a test only if the counter rule is touched again.
- **L7.** `digest_order_hold.rs`, `Form::hook` doc: the reflow left the line "`after_store`, so the hold runs on" short. Cosmetic.

## A-G as briefed

- **A. `proposer.rs`.** Only the wrapper, the `Option` and doc text changed (see question 2). The deleted `match plan { None => … }` arm was the switch-off arm and nothing else.
  - At the base, with the switch on, `own_parent` already came from `HoldPlan::own_parent` through `drain_held`. Nothing changed there.
  - `cites_own_parent` (base) and `plan`'s `own_parent` (`order_hold.rs:158-164`) are the same computation:
    - both look up `round.checked_sub(1)` in `proposed_headers`;
    - both check whether any parent has `origin()/author()` equal to this node and `header().digest()` equal to the tracked header's `digest()` (impls at `order_hold.rs:262-293`).
  - The edge cases give the same result. Round 0 and round 1 (genesis parents, nothing tracked below) give false in both. A parent set without the own certificate gives false in both. No log field value changes.
- **B. The drain.** At the base, `drain_digests_for_header` was literally `self.drain_digests_except(&BTreeSet::new())`. With an empty set the filter keeps every lane, so the drain is the same, byte for byte. The I3 doc is accurate apart from L3.
- **C. The deleted tests.**
  - The golden test is off-arm: row 2 `[4, 5]` was drained while round 1 was pending.
  - The canceled-cause counter becomes non-zero in `test_lane_sequence_survives_requeues` :2718 `[3,0,1,0]`.
  - The committed-cause counter and its warning: `test_order_hold_warns_once_per_requeue_out_of_order` :3449-3460.
  - The release of digest numbers through the guard: `test_order_hold_stale_resend_is_never_a_blocker` :3387-3388. The code is at :1419-1424.
  - The gaps are M1 and L6.
- **D. The four reworked tests (726a25f1b).**
  - The cancel test (fn ≈:1658, asserts ≈:1665 and ≈:1676-1680) matches the code step by step:
    - Round 2 has no own parent: the fixture certificates are not this node's header. Its floor is therefore 2, round 1 is a blocker and worker 0 is held, so the payload is empty.
    - The cancel prepends d1 and d2 ahead of the held d3, and d4 arrives after them.
    - For round 3 the only tracked older header is the empty round 2, which is not a blocker, so the payload is `[d1, d2, d3, d4]`.
    - `digests resent` count 2, cause `canceled`, and the totals `[2, 0]` are unchanged. This is the order the module doc promises at :67-69.
  - The other three tests keep every assertion. Only `propose_and_track` became `build_on(hold_parents(..))`, plus one `last_parents` in the stopped test. My view is in the three sentences below.
- **E. The intact-chain test.** It is drained under default parameters, and each round queues exactly 3 digests, so the header cap does not bind. Rotation starts at `next_lane` 0.
  - Round 1: queues w0 `[2,3]` and w1 `[101]`. The lanes are `[0,1]`, so the drain order is w0, w1, w0: `[(2,0),(101,1),(3,0)]`. The cursor moves to 1.
  - Round 2: queues w0 `[4,5]` and w2 `[102]`. From the cursor the lanes are `[1,2,0]`, and w1 is empty, so the drain is `[(102,2),(4,0),(5,0)]`. The cursor moves to 1.
  - Round 3: w0 gets `[6,7]`, and 3%3=0 adds `[103]` to w0 as well. Only w0 has digests, so the drain is `[(6,0),(7,0),(103,0)]`.
  - Round 4 checks out too: `[(104,1),(8,0),(9,0)]`.
  - All four match the list in the test.
- **F. The e2e tests.** At the base `Form::hold()` was `self != Control`, so all three kept forms already had `HEADERS_HELD` required, and `kill_and_restart` read run 0 with `true`.
  - They already used `wait_for_landing` and the on branch of `check_form`.
  - Every assertion of the three kept tests survives. Making the requirement unconditional adds nothing new.
  - The `fleet.rs` lists are now empty `[_; 0]`. That machinery belongs to R5.
- **G. Docs.** There is no "switch" in the three files. The leftover wording is L1-L4. The text at `proposer_tests.rs:2981` and :3402 reads as a description of the defect, not as an off arm.

## Three sentences on D (for the owner)

The cancel test now pins exactly what the proposer does, in the order the hold's doc promises: the header built while round 1 is pending carries nothing of worker 0, and the header after the report carries `[d1, d2, d3, d4]`. The other two tests still test something real, because the lane numbers, the prepend order and the out-of-order counter are bookkeeping driven only by the reports they receive, and I2 keeps that counter as the production net for faults and the GC cut. But the cancel of a header that the next header cites (`test_lane_sequence_survives_requeues`, and the second report in `test_requeues_that_keep_lane_order_count_nothing`) is a report the certifier never sends, so the canceled count of 3 is the counter rule on an unreachable input; the writer said so inside the tests, which is the honest form, and I would add one line to the test doc (L5) rather than delete it, since it is now the only test that makes the `canceled` cause non-zero.

## Checked and fine

- `config/src/node.rs`: the field, doc, default and `runtime_switches!` entry are gone, and nothing else changed.
- `metrics.rs`: doc only.
- `order_hold_model.rs`: one doc line, which now names `drain_digests_except`. I did not re-read the model's hold-off tests.
- `order_hold.rs`: doc only, :43-47 and :91-98.
- `proposer.rs`: see A.
- `proposer_tests.rs`: `hold_fixture()` lost its argument. The `for on in [false, true]` loops became single runs on the on arm, and those runs keep their asserts.
- `digest_order_hold.rs` and `fleet.rs`: see F. The doc dropped the "16 and 15" figures, which is fine.
- Commit messages: no unsourced figure, no private label, no attribution, `Refs #1807`, and `Topic: remove-bench-switches` as the last line.
