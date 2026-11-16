# The ninth PR (`refactor/remove-bench-switches`): facts for its text, collected as the units report

Private. The orchestrator's file; the PR text's writer reads it, the figure-checker checks the text against the code, not against this file.
Sources: the units' hand-backs (kept in `tasks/checkpoint-bench8-R*.md`), the reviews under `tasks/bench8/review/`, the gate logs under `tn-b8-uc/target/tmp/`.
Branch: `refactor/remove-bench-switches` in `/home/drtnarg/coding/telcoin/tn-b8-uc`, base 500e21afa (#1869's head).

## What the PR is

The stack #1862-#1869 shipped six fixes behind runtime switches that default to off.
The owner's review decided that a fix the benchmarks confirmed is the node's behaviour: the six switches go, with the switch list, the `node switches` line and the gauge; of the two forms of the #1804 fix only always-on ships.
What the removal loses: the "switch off equals main" tests and the mixed-switch fleet test. The mixed fleet is covered by `make test-upgrade` with `main` as the previous binary.

## For operators

- A `parameters.yaml` that still names a removed key is read and the key ignored: `Parameters` has no `deny_unknown_fields` (`crates/config/src/node.rs:273`; loader `serde_yaml::from_str`, `crates/config/src/traits.rs:47`, `:69`); the test `unknown_keys_are_ignored` (`crates/config/src/node.rs:1765` at a5be61615) pins it.
- `vote_timeout` must now be strictly below 9 s for a node to start (it was "below 10 s" unless the switch was on): `validate_vote_timeout` in `crates/config/src/consensus.rs` requires `vote_timeout + VOTE_EXECUTION_WAIT (1 s) < LIBP2P_REQUEST_TIMEOUT (10 s)`, on entering any epoch the node can vote in. 8.999 s passes, 9 s is refused. Also still required: `vote_timeout >= max_header_delay + the drift wait`, and `vote_timeout > 1 s`. The code default is 5 s; the mainnet preset sets 5 s; the testnet preset leaves the default.
- Removed start-up error text: "vote_timeout {:?} must stay below the libp2p request timeout {:?}, which otherwise cancels a slow vote before vote_timeout fires; lower vote_timeout" (the check can no longer fire). The live check's text lost only its words about the switch.

## R1 — the epoch-record switches (a5be61615, b67c0acdd; reviews: approve, Lows only)

- `epoch_record_collect_past_uncertified` gone: the record collector always walks past an epoch this node holds only as its own uncertified record. `sync_epoch_records_to_tip` and `spawn_epoch_record_collector` lost their `parameters` argument (the signatures equal `main` 0554efd4f's again).
- `epoch_record_recertify` gone: vote rounds always keep verified signatures across rounds, and a close re-votes one older uncertified record of this node's own. The `Option` around `RetainedEpochVotes` went.
- **What changes for a node beyond a default:** at start-up, a node whose latest record is certified and an older one is not now re-arms a vote round for the older one (the base's doc called that shape deliberately not healed). `main`'s own test `test_startup_revote_skips_certified_record` asserted the old outcome and is deleted; rows `(false, true)` and `(true, false)` of `test_startup_rearm_recertifies_behind_a_certified_latest_record` assert the new outcome and the quiet case.
- Operator note that went with the removed field's doc and must be said somewhere: a re-certify pick that finds this node's record in conflict with the certified one stops the node, and a later pick stops it again until an operator acts.
- Deleted tests: `test_collect_epoch_records_stops_at_an_uncertified_epoch_with_the_walk_off` (state-sync), `test_uncertified_epoch_stops_the_collector_with_every_switch_off` (e2e), `test_switch_off_revotes_only_the_previous_record`, `test_startup_revote_skips_certified_record` (node).
- Kept tests with changed expectations: `test_withhold_hook_silences_only_the_first_round_by_default` ({2,3,4} → {1,2,3,4}) and `test_withhold_hook_rounds_reach_the_failsafe` ({2,4} → {1,2,4}): the closes of 3 and 4 now also re-vote record 1 (3 % 2 = 1, 4 % 3 = 1).
- The e2e walk test keeps its assertions (epoch K stays uncertified, every collector walks past it); its plumbing changed: 64 withheld vote rounds keep K uncertified now that re-certify rounds run, and "no re-certify log" became: every validator logs re-certify rounds for K only, none certifies, at least one round ends short.
- No log line, field or metric changed in R1.
- Not tested (review Low): that a certified latest record re-armed at start-up gets no vote of this node's own (one guard, `cert_by_digest(...).is_none()`).

## R2 — `vote_queue_fix` (d2b80ced5, adecca691, 6a7c3d7c5; review: approve, Lows only)

- Gone: the switch; the wait for execution UNDER the author lock. A voter always waits for the execution block a header names BEFORE the author lock, at most `VOTE_EXECUTION_WAIT` (1 s), and always refuses a request that a newer request of the same author has superseded.
- **What a voter answers differently from `main`** (four of `main`'s own tests pinned the old answers and now assert the kept ones):
  1. Once a newer in-window request of an author has been seen, a request of that author for a strictly lower round of the same epoch gets the recoverable `SupersededRequest` instead of `InvalidHeader(AlreadyVotedForLaterRound)`. The check runs on arrival, before the lock. A different header for the SAME round still gets `AlreadyVotedForLaterRound`.
  2. A repeat of an older header the voter already voted for then gets `SupersededRequest` instead of the cached vote.
  3. The old answers are still reachable while no newer in-window request of that author has been recorded: the record is in memory and starts empty when the handler is built (a restart, a mode change), or the newer header was outside the vote window on arrival.
  4. A header with a tier-three timestamp lead that names an execution block the voter has NOT executed is refused with the same `InvalidTimestamp`, but after up to 1 s instead of at once: the pre-lock wait runs before the drift check, which stays under the lock. A tier-three header that names a block the voter holds is refused at once; a header that fails validation or is outside the vote window skips the wait.
- **On the wire and on the requester:** `SupersededRequest` is not a new wire type: it goes out as `PrimaryResponse::RecoverableError(String)`, which `main` 0554efd4f has. A requester retries a recoverable error up to 6 times at 250 ms, then with backoff until its next proposal cancels the request; `AlreadyVotedForLaterRound` went out as `PrimaryResponse::Error`, which the certifier treats as fatal for that voter and header (no retry). Neither carries a penalty. So an older request now costs retries where it cost one give-up; they normally end at once because the author has moved on.
- A coverage gap the writer names: `test_vote_cached_across_dropped_request` was written for the property that a request dropped mid-evaluation puts the decision entry back (#1836); its newer request is now dropped during the pre-lock wait, so that property is no longer exercised by it.
- If the owner wants the tier-three refusal at once again: call `check_header_lead` in `vote_request` before the pre-lock wait for in-window headers and keep the check under the lock too; a tier-three refusal would then not be written to the author's vote state, so a repeat would be judged again each time, and after the clock catches up the header would be voted (the doc says "reject for good"). Not done: a design change.
- **Three more points a reviewer must be told** (from the independent review of R2; all Low, none worse than `main`):
  - A request moves its author's mark when it ARRIVES, not when a vote is cast: a newer request that is itself refused or dropped still makes every lower round of that author `SupersededRequest`, even if this voter never voted for the newer round. The mark lives in memory only.
  - A cached refusal is replayed under the lock, so a repeat of a refused header that names a block this voter has not executed waits up to 1 s before it gets the cached answer; on `main` it came at once.
  - Each request's wait before the lock is capped at 1 s, but nothing caps how many requests one author has waiting at once: the vote request class is unbounded by default (`crates/network-libp2p/src/serve_permits.rs:15-17`; its per-peer limit of 2 applies only when a capacity is configured) and the primary request protocol sets no stream cap. Only the authenticated author can cause it, and on `main` queued requests held their tasks for up to N × 1 s. A possible follow-up: count waiters per author and answer `ExecutionBehind` at once past a small cap.
- `vote_queued_requests_of_one_author_wait_in_turn` was not an upstream test (#1864 added it to reproduce #1804); what else it asserted is covered by `vote_queued_requests_wait_once`.
- Deleted tests: the seven `quorum_exec_block_voter_*_switch_off` (they turned off `vote_queue_fix`; their on bodies live on as `old_block_in_ring_is_voted_at_once` and six more), `vote_queue_fix_off_refuses_malformed_header_without_the_wait`, `vote_queue_fix_off_answers_repeat_of_voted_header_from_cache`, `vote_queued_requests_of_one_author_wait_in_turn`, and `vote_timeout_must_stay_below_the_libp2p_request_timeout` (its case moved into `vote_timeout_plus_the_prelock_wait_stays_below_the_request_timeout`).
- No log line, field or metric changed in R2.

## R3 — always-on is the only form (a242a3b4a node code; de075ab78 e2e; review of the first: approve, Lows only; of the second: running)

- Gone: `quorum_exec_block`, `quorum_exec_block_starved_rounds`; the adaptive form (the `ExecBlockPolicy` window-and-streak state with its hooks, `QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`, `QUORUM_EXEC_BLOCK_RESET_STREAK`, the start-up warning); the `ExecPolicy` type. Every header's execution block is chosen by `choose_exec_block` under the quorum rule with the floor of 8 (`QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`). +142 / −1,332 in the node code.
- **Why the adaptive form is deleted:** the owner chose always-on as the only form that ships. Bench 7 ran one run of each form at 20,000 IOPS; the adaptive form did not do better, and it carries a window, a streak and two constants that no run tuned.
- The independent review checked the node commit against the base's always-on arm point by point: the inputs are built by the same expression; every parent filter lives in `quorum_rule_choice`, untouched; the removed guard operand was always false under always-on; the removed hooks returned at once under always-on; no expected header bytes changed in any kept test.
- Removed log output, verbatim: the field `exec_policy` on `header proposed` (values `off`, `always`, `tip`, `starved`; `exec_block`, `exec_tip`, `exec_basis` stay); the start-up warnings "quorum_exec_block_starved_rounds has no effect while quorum_exec_block is off" and "quorum_exec_block_starved_rounds is above its bound; the bound is used". No metric label carried the policy.
- Deleted unit tests: the eight tests of the adaptive window, streak, model and warning (`test_quorum_exec_block_adaptive_policy_state_machine`, `…_cancel_report_reaches_the_policy`, `…_reset_needs_a_streak_of_certified_tip_headers`, `…_policy_model_holds_the_target`, `…_policy_model_after_the_regime_ends`, `…_window_counts_headers_across_a_round_jump`, `…_window_without_a_header_does_not_double`, `…_starved_rounds_warning`). `test_quorum_exec_block_switch_off_keeps_header_bytes` is now `test_quorum_exec_block_header_names_the_own_ring_block` (its off half is gone). The choice table keeps all 20 always-on rows.
- e2e: deleted `test_mixed_switch_fleet_is_one_chain`, the control and adaptive arms of `test_fast_executor_is_certified`, `test_held_member_two_closes_adaptive`, `test_missed_record_round_adaptive`. Kept, on the plain node: `test_fast_executor_is_certified` (every node at least 20 headers in 90 s; every slow node and the fast node certify at least 0.93 of their own headers; at least 0.5 of the fast node's headers in the second half name `exec_basis=floor`; no canary, no fatal line, the same blocks on all four nodes), `test_held_member_two_closes`, `test_missed_record_round` (assertions unchanged), and the order-hold tests renamed after the hook stage (`…_before_store`, `…_after_store`).
- **What the removal loses** (to state in the limits):
  1. The control arm of the fast-executor test: that WITHOUT the rule the fast node certifies at most 0.85 of its headers and every slow voter refuses some requests as execution behind. Only the rule's absolute share is asserted now.
  2. The mixed fleet: one chain while two nodes ran the fixes and two did not, across epochs and a restart; every node serving the same certified record per closed epoch; no record conflict; and a certified header of a fixed node naming an older block, which needs a vote from a node without the fixes. Its stated replacement is `make test-upgrade` with `main` as the previous binary; whether that test makes any node execute late (so that an upgraded proposer names a block below its tip while old binaries vote) is being checked by the review of de075ab78.
- Not yet run: the kept e2e tests on the plain node (the before-store order-hold test has never run under the always-on rule).

## R4, R5 — to be added as they report

## Gates on the top — to be added

## Limits the plan already names

- `vote_timeout` under 9 s is now a start condition.
- A voter restored from a snapshot refuses a named block below its floor.
- The hold's two untested gaps: a garbage-collection cut below the leader; a re-send after a restart.
- No test runs an uncertified epoch beside a previous binary.
- The stack was run beside `main`, not beside `v0.17.0-adiri`.
