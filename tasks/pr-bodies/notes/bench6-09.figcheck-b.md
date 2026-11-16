# FC-9b — figure-check of bench6-09-remove-bench-switches.md, lines 104 to the end

Verdict: FIX (one error, a pointer in the wrong direction; four weak items; nothing that changes a conclusion).

Sources read: the removal branch tip e1a562cbb (tree = 57a55b221), the old top 500e21afa (tree = 105e584ac), main 0554efd4f, the stack's base 33b727fce, #1864's first commit 84c517cf1, the bodies of #1862, #1864, #1866, #1868, #1869, the issues #1804, #1807, #1850, #1852.
Code was read with `git show <commit>:<path>` and `git grep <commit>` only.

## Errors

1. Limits, the bullet on the e2e tests (line 152 or so): "are run by the gates below, not before".
   The gates block (the `Stack-wide gates` marker) sits at the end of `## Testing` (line 134), above `## Limits` (line 136); nothing follows the Limits but `## Related`.
   Replacement: `are run by the gates below, not before` → `are run by the stack-wide gates above, not before`

## Weak

1. Testing, the `vote_queue_fix` start-up item: `vote_timeout_must_stay_below_the_libp2p_request_timeout` is main's own test (present at 0554efd4f `crates/config/src/consensus.rs`; at 500e21afa it ran with `vote_queue_fix` at its default `false`, `node.rs:629`, so "the off arm" is right).
   The text says "Main's own" for `test_startup_revote_skips_certified_record` but not here, and #1864's body promises only that this PR "changes four of main's own tests".
   Replacement: ``The off arm of the start-up check: `vote_timeout_must_stay_below_the_libp2p_request_timeout` `` → ``The off arm of the start-up check: main's own `vote_timeout_must_stay_below_the_libp2p_request_timeout` `` (rest of the sentence unchanged; its case, 2 × the request timeout refused, is in the new test at e1a562cbb `consensus.rs:798-826`).
2. Limits, the serve-permit bullet: "nothing caps how many requests of one author wait at once" holds only for the default budget.
   `serve_permits.rs:22-25` and `:30-32` at e1a562cbb: an enforcing class holds one peer to `MAX_PERMITS_PER_PEER` (= 2, `:66`), and "the per-peer share bounds how many of one peer's vote tasks wait at once".
   Replacement: `but nothing caps how many requests of one author wait at once` → `but with the default serve budget nothing caps how many requests of one author wait at once`
   (Optionally append to that sentence, after `(`crates/network-libp2p/src/serve_permits.rs:15-16`)`: `; a configured vote class holds one peer to two (`MAX_PERMITS_PER_PEER`)`.)
3. Limits: "The stack ran beside main" — the gates ran `make test-upgrade` with main at 33b727fce as the previous binary (#1862's gates block, line 100), while bullet 1 of the same list cites main at 0554efd4f.
   The voter code is the same at both (`git diff --stat 33b727fce 0554efd4f` of `network/handler.rs`, `consensus_bus.rs`, `config/src/consensus.rs` is empty), so this is a precision fix only.
   Replacement: ``- The stack ran beside main, not beside `v0.17.0-adiri`.`` → ``- The stack ran beside main at 33b727fce, the stack's base, not beside `v0.17.0-adiri`.``
4. Limits bullet 1: "a block above its tip gets the recoverable `ExecutionBehind`" — only when the block is still unexecuted at the end of the 1 s wait (`handler.rs:1463-1506` at 0554efd4f: `timeout(VOTE_EXECUTION_WAIT, wait_for_execution)`, `Err(_)` → `ExecutionBehind`).
   Replacement: ``a block above its tip gets the recoverable `ExecutionBehind` `` → ``a block still above its tip when the wait ends gets the recoverable `ExecutionBehind` ``

Optional (not an error): `Refs #1850` names nothing left open, while the #1804 and #1807 clauses do and #1862's `Refs #1850` names "the question in its comment, whether that stop should need a super-quorum of the full committee".
If wanted: ``- Refs #1850: the walk past an uncertified epoch and the re-certify round (#1866) are now unconditional.`` → ``- Refs #1850: the walk past an uncertified epoch and the re-certify round (#1866) are now unconditional; the question in the issue's comment, whether that stop should need a super-quorum of the full committee, stays open there.``

## Verified (high points)

- A, deleted tests: every name the text lists as deleted exists at 500e21afa and is gone at e1a562cbb (54 names grepped); the counts hold: seven `quorum_exec_block_voter_*_switch_off`, "six more" helper bodies (`old_block_out_of_ring_is_voted_from_the_database`, `old_number_with_another_hash_is_refused_as_a_fork`, `previous_epoch_blocks_in_ring_are_voted_at_once`, `previous_epoch_blocks_out_of_ring_are_answered_at_once`, `block_above_the_tip_is_waited_for`, `author_stepping_back_is_voted_at_once`), eight adaptive unit tests, the model's four tests (kept at the tip), eight config tests plus `test_node_switch_gauge_per_switch`.
  `vote_queued_requests_of_one_author_wait_in_turn` is added by 84c517cf1, #1864's first commit.
  The deleted list is complete: every test fn removed by the diff and absent at the tip is either listed or renamed.
- A, "No test is added": `+fn test_` 7, `-fn test_` 30; every added fn is a rename or a helper made a test: the `vote_queue_fix_` prefix dropped (14 tests), the seven `(on: bool)` helpers now plain tests, `vote_queue_fix_keeps_vote_timeout_plus_the_prelock_wait_below_the_request_timeout` → `vote_timeout_plus_the_prelock_wait_stays_below_the_request_timeout`, `default_and_shipped_timing_pass_with_vote_queue_fix` → `default_and_shipped_timing_pass`, `test_held_member_two_closes_always`/`test_missed_record_round_always` → plain names, `test_hold_keeps_every_transaction_adaptive`/`_always` → `_before_store`/`_after_store`, `test_startup_sync_walks_under_the_switch_and_stops_on_a_conflict` → `test_startup_sync_walks_past_its_own_uncertified_epoch_and_stops_on_a_conflict`, the tier-three test and the header-bytes test as the text says.
  The mixed-binary test is 0a70b58f5, reverted by e1a562cbb.
- A, kept tests: `test_vote_older_round_rejected` (new first case `AlreadyVotedForLaterRound` from a stored vote, then `SupersededRequest {round: 1, newest_round: 2}`; old expected `AlreadyVotedForLaterRound`), `test_vote_cached_across_stale_headers`, `test_vote_cached_across_dropped_request` (old doc: "a request ... dropped while it was evaluated"), tier-three (old: one unexecuted case, `waited == 0`; new: `expected = if executed {0} else {VOTE_EXECUTION_WAIT}`), withhold {1, 2, 3, 4} / {1, 2, 4} (old {2, 3, 4} / {2, 4}), the walk e2e (`WALK_WITHHOLD_ROUNDS = 64`, re-certify lines for K only on every validator, `certified == 0`, a polled `short >= 1` on some validator), `test_fast_executor_is_certified` (`MIN_WINDOW_HEADERS = 20`, `MEASURE_WINDOW = 90 s`, `MIN_CERTIFIED_SHARE = 0.93` for slow and fast, `MIN_FLOOR_SHARE = 0.5` of the fast node's second half, canary, fatal lines, `assert_blocks_same`), the proposer tests (`[d1, d2, d3, d4]`; the "forced" comments are in `test_lane_sequence_survives_requeues` and `test_requeues_that_keep_lane_order_count_nothing`).
  No sentence says or implies that a gate or an e2e test passed.
- B1: `upgrade.rs` at e1a562cbb has no `exec_basis`, no slowed node; main's voter at 0554efd4f `handler.rs:1456-1507` and `consensus_bus.rs` `wait_for_execution`: 1 s wait (`VOTE_EXECUTION_WAIT`, `config/src/consensus.rs:459`); `Fork` only when the ring or the canonical database holds a different block at the number; `BelowFloor` → `BelowRestoreFloor`; timeout → `ExecutionBehind`, recoverable without penalty (`error/network.rs:281`); a block held in the ring or the database is `Match`, tip or not. The text says it is read from code; it does not say how an upgrade is rolled out.
- B2: `LIBP2P_REQUEST_TIMEOUT` 10 s minus the 1 s wait, the bound itself refused (strictly below 9 s); default 5 s (`node.rs:398`, `default_vote_timeout_is_five_seconds`), mainnet `vote_timeout: 5s`, testnet sets none; checked at `start_epoch.rs:480` on `EpochPosition::Live`.
- B3: `BelowRestoreFloor` at e1a562cbb `handler.rs:1614`, no penalty (`error/network.rs:314`), `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES = 8` (`proposer.rs:1871`).
- B5: wording matches #1869's Limits line 12 word for word. B6: `v0.17.0-adiri` is a tag; #1862's gates line 100. B7: same run ids and wording as #1868's lines 11, 26, 28, 97; no new figure.
- B8: authentication before the wait (`PeerNotAuthor`, handler at e1a562cbb), `serve_permits.rs:15-16`; the `stale_resend` bullet agrees with #1869's line 15 and 130.
- C: no `Fixes`/`Closes`/`Resolves` in the file; each `Refs` matches its issue (#1804's floor depth, #1807's defect 2, #1850's walk and re-certify, #1852's gauge) and #1862's Related.
- D: every pointer to this PR in the other bodies has a landing place: #1868:125 "No test of that point is added" → Limits bullet 1; #1869:130 `stale_resend` → the last Limits bullet and line 100; #1864:94 "changes four of main's own tests" → the four voter tests under "Kept tests that changed"; #1866:93 the start-up re-arm → "Main's own `test_startup_revote_skips_certified_record` goes too"; #1862:113 → line 102.

## Not traceable

- "on main queued requests held their tasks for up to N × 1 s" (serve-permit bullet): not re-derived within the budget.
- "No test runs an uncertified epoch beside a node on a previous binary": the only test that takes the previous binary is `upgrade.rs`, and it was not read in full for vote withholding.

## Rule breaches

None: no unit name, no private path, no host, no attribution; one sentence per line; the lint returns LINT-OK on a copy.

## Observation outside this text

At e1a562cbb the doc of `test_vote_tier_three_lead_waits_only_for_an_unexecuted_block` (`network_tests.rs`, just above line 3177) still opens "A tier-three header is rejected before the voter waits for its execution block.", which its own next paragraph and body contradict; a code-doc fix for the closing commits.

## Counts

Claims and figures checked: 112. Matched: 105. Wrong: 1. Weak: 4 (plus one optional). Untraceable: 2.
