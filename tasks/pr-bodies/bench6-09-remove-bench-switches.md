## Summary

This PR removes the six runtime switches the stack added, and the switch machinery of #1862, so that each fix behind a switch is the node's only behaviour.
The six switches are `vote_queue_fix` (#1864), `epoch_record_collect_past_uncertified` and `epoch_record_recertify` (#1866), `quorum_exec_block` and `quorum_exec_block_starved_rounds` (#1868), and `digest_order_hold` (#1869); the machinery is the `runtime_switches!` list, the `node switches` log line and the `tn_node_switch` gauge.
Of the two forms of the author's side of #1804 it keeps always-on and deletes the adaptive form, with its window, its reset streak and its two constants.
The review of the stack decided that a fix the benchmarks confirmed is the node's behaviour, and that a runtime switch is an instrument of a benchmark, not something to ship.
After this PR `Parameters` has the same fields and `Default` values as `main` at 0554efd4f, and a `parameters.yaml` that still names a removed key loads with the key ignored.

This PR targets #1862's branch (`feat/bench6-switches-obs`), which holds the collapsed stack: #1863 to #1869 were merged into it on 2026-11-16, so the Files tab shows this change alone and the Commits tab its 20 commits.
Two of those commits cancel out: `0a70b58f5` adds a mixed-binary vote test to `crates/e2e-tests/tests/it/upgrade.rs` and `e1a562cbb` reverts it, so the tree after the revert equals the tree before the test; the case it was written for is the first limit below.
Once this PR is merged, #1862 carries the stack without the switches; `main` is then merged into #1862's branch and `make attest` runs on the result.
Please merge with 'Create a merge commit', like the rest of the stack.
Code locations in this text are given at `e1a562cbb`; the six commits after it (comments, docs, test names and one added test) move some of them.

## Problem

Each of the six switches defaults to off, and with a switch off the node takes main's path for the fix behind it.
No chain preset sets any of them.
Without this PR the collapsed #1862 would bring to `main` six parameters nobody sets, two code paths for each fix (the fix and the path it replaces), and fixes that run on no node unless its operator turns them on.
Each off path also needs its own tests, and every later change to a fix would have to keep both paths working.

## Change

| Switch or part | Deleted | Stays |
|---|---|---|
| `vote_queue_fix` (#1864) | the switch; the wait for execution under the author lock; main's start-up check that `vote_timeout` stays below the 10 s request timeout (the check with the wait before the lock is stricter); 11 tests | the wait for the named execution block before the author lock (at most 1 s); the `SupersededRequest` refusal |
| `epoch_record_collect_past_uncertified` and `epoch_record_recertify` (#1866) | both switches; the collector's stop at an epoch the node holds only as its own uncertified record; the `Option` around the kept votes; the `parameters` argument of `sync_epoch_records_to_tip` and `spawn_epoch_record_collector`; 4 tests | the walk past that epoch; verified signatures kept across vote rounds; the re-vote of one older uncertified record of the node's own |
| `quorum_exec_block` and `quorum_exec_block_starved_rounds` (#1868) | both switches; the adaptive form (`ExecBlockPolicy` with its hooks, `QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`, `QUORUM_EXEC_BLOCK_RESET_STREAK`, the start-up warnings); the `ExecPolicy` type and the `exec_policy` log field; 8 unit tests, the off half of a ninth and 3 rows of the choice table; 3 e2e tests and two arms of a fourth | `choose_exec_block` under the quorum rule with the floor of 8 (`QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`); the 17 always-on rows of `test_quorum_exec_block_choice_table` |
| `digest_order_hold` (#1869) | the switch; the drain without the hold; `drain_digests_for_header` and `cites_own_parent`; 5 proposer tests and the e2e control | the hold at every drain; the code of `order_hold.rs` and its model |
| Switch machinery (#1862) | `runtime_switches!` and its list, `Parameters::switches()`, `Parameters::log_switches()`, `SwitchValue`, `Parameters::switch_at_default`; the `node switches` line; the `tn_node_switch` gauge; 8 config tests and 1 node test; the switch checks of the e2e harness | the rest of #1862's observability; #1863's e2e override scaffold; `unknown_keys_are_ignored` and `reserializing_keeps_the_existing_keys` |

For #1864, a voter always waits for the execution block a header names before it takes the author lock, at most `VOTE_EXECUTION_WAIT` (1 s), and always refuses a request that a newer request of the same author has superseded.
The wait under the author lock is gone.
Main's start-up check that `vote_timeout` stays below the 10 s request timeout goes with it: the check that `vote_timeout` plus the 1 s wait stays below 10 s is stricter, and it now applies to every node.

For #1866, the record collector always walks past an epoch the node holds only as its own uncertified record.
Vote rounds always keep verified signatures across rounds, and an epoch close re-votes one older uncertified record of the node's own.
`sync_epoch_records_to_tip` and `spawn_epoch_record_collector` lose their `parameters` argument, so their signatures are main's again.

For #1868, every header names the execution block `choose_exec_block` picks under the quorum rule with the floor of 8.
The adaptive form goes with its window-and-streak state, its hooks, its two constants and its start-up warnings; in its commit, unit tests included, that is 142 lines added and 1,332 deleted.
Against the base's always-on arm, the rule's inputs are built by the same expression, every parent filter stays in `quorum_rule_choice`, and no expected header bytes change in any kept test.

For #1869, the proposer holds `OwnChainOrder` as a plain field instead of an `Option`, and the branch that drained digests without the hold goes.
`drain_digests_for_header` and `cites_own_parent` were dead once that branch went: the first was `drain_digests_except` with an empty held set, the call the hold itself uses, and the second computed the value the hold's plan already gives.
`order_hold.rs` changes only in its docs, and the model with its 100,000-case hunt stays.

For #1862, the switch list, its accessors, the `node switches` line and the `tn_node_switch` gauge go; the epoch-entry gauge, the digest-receipt fix, the histogram buckets and the rest of that PR's observability stay.
The e2e harness no longer checks a node's `node switches` line: `STACK_SWITCHES_ON`, `STACK_SWITCHES_OFF`, `expected_switches` and `assert_switches` leave `fleet.rs`, and no e2e test is deleted with them.
Each call site that waited for that line is followed by a wait that tolerates a node that is not up yet (an RPC poll or a log wait with a timeout), so a node that never starts now fails at that later wait.
#1863's scaffold (`NodeOverrides`, `FleetOverrides`, `TN_E2E_PARAMETERS`) stays: tests in `digest_order_hold.rs`, `epoch_close_forms.rs`, `epoch_record_walk.rs` and `exec_block.rs` still pass test hook variables and cadence parameters (header and batch delays) through it.

## What a node does differently from main after this PR

Each item is against `main` at 0554efd4f, with where it is at this PR's head and the test that pins it.
This PR's diff touches no storage or execution crate and adds no message type, so no item changes the wire format, how a block is executed, or the format of what a node stores.
What changes is how a voter answers some requests, which block a header names, which digests a header carries, when a node re-votes an epoch record, a start condition, and what a node logs.

Votes (`crates/consensus/primary/src/network/handler.rs`; the superseded check at `:1382`, `check_header_lead` at `:1415`): what a voter answers differs from main in four points, and four of main's own tests now assert the new answers.
- Once a newer in-window request of an author has been seen, a request of that author for a strictly lower round of the same epoch gets the recoverable `SupersededRequest` on arrival, before the lock, where main answers `InvalidHeader(AlreadyVotedForLaterRound)` once it has decided the newer header, and decides the older one in full after a recoverable answer to the newer one (a timeout, `ExecutionBehind`, a deferral), which leaves no entry; a different header for the same round still gets `AlreadyVotedForLaterRound`.
- A repeat of an older header the voter already voted for then gets `SupersededRequest` instead of the cached vote.
- The old answers remain while no newer in-window request of that author is recorded: the record lives in memory and starts empty when the handler is built (a restart, a mode change), or the newer header was outside the vote window when it arrived.
- A header with a tier-three timestamp lead that names a block the voter has not executed gets the same `InvalidTimestamp`, but after up to 1 s instead of at once, because the wait before the lock runs before the drift check, which stays under the lock; a tier-three header that names a block the voter holds is refused at once, and a header that fails validation or is outside the vote window skips the wait.

The four tests are `test_vote_older_round_rejected`, `test_vote_cached_across_stale_headers`, `test_vote_cached_across_dropped_request` and `test_vote_tier_three_lead_waits_only_for_an_unexecuted_block` (main's `test_vote_tier_three_lead_is_rejected_before_execution_wait`, renamed here), in `crates/consensus/primary/src/tests/network_tests.rs`.
A request moves its author's mark when it arrives, not when a vote is cast: a newer request that is itself refused or dropped still makes every lower round of that author superseded, even if this voter never voted for the newer round.
A cached refusal is replayed under the lock, so a repeat of a refused header that names a block this voter has not executed waits up to 1 s for the cached answer; on main it came at once.
`SupersededRequest` is not a new wire type: it goes out as `PrimaryResponse::RecoverableError`, which main already has (0554efd4f), and a requester retries it up to 6 times at 250 ms, then with backoff until its next proposal cancels the request.
`AlreadyVotedForLaterRound` went out as `PrimaryResponse::Error`, which the certifier treats as fatal for that voter and header; neither carries a penalty, so an older request now costs retries where it cost one give-up, and they normally end at once because the author has moved on.

Start condition: `vote_timeout` strictly below 9 s is a start condition for every node.
`validate_vote_timeout` (`crates/config/src/consensus.rs:511`) requires `vote_timeout` plus `VOTE_EXECUTION_WAIT` (1 s) to stay below the 10 s request timeout, so 8.999 s passes and 9 s is refused; main requires only that `vote_timeout` stays below 10 s.
The check runs when the node enters a live epoch (`crates/node/src/manager/node/start_epoch.rs:480`), at start-up or after replaying closed epochs, which it replays without the check.
The other bounds stay: `vote_timeout` at least `max_header_delay` plus the drift wait, and above 1 s.
The code default and the mainnet preset are 5 s and the testnet preset keeps the default.
Pinned by `vote_timeout_plus_the_prelock_wait_stays_below_the_request_timeout` (`crates/config/src/consensus.rs:798`).

Epoch records: the record collector walks past an epoch the node holds only as its own uncertified record (`crates/state-sync/src/epoch.rs`), where main stops there (#1850); the e2e `test_uncertified_epoch_walked_past` covers it.
At start-up, a node whose latest record is certified and one of the 16 before it is not re-arms a vote round for an older uncertified record (`revote_uncertified_epoch_record_on_startup`, `crates/node/src/manager/epoch_votes.rs:786`; `MAX_RECERTIFY_LOOKBACK` at `:56`); on main it does not.
Rows `(false, true)` and `(true, false)` of `test_startup_rearm_recertifies_behind_a_certified_latest_record` (`epoch_votes.rs:3676`) pin the new outcome and the quiet case.
The collector and the pick run on every node; only a member of the picked record's committee casts the re-vote (`test_recertify_skips_a_record_outside_our_committee`, `epoch_votes.rs:3578`).
For operators: a re-certify pick that finds this node's record in conflict with the certified one stops the node, and a restart does not change the stored record, so a later pick stops it again until an operator acts (the stop at `epoch_votes.rs:138-143`, the start-up re-arm at `:786-806`, the pick at `:833-841`; `test_recertify_round_stops_on_a_conflicting_record` at `:4413`).
This now holds for every member, not only one that set `epoch_record_recertify`.

Execution block: every header names the highest execution block that holders of 2f+1 voting weight, among the proposer's own tip and its same-epoch parents, have reached: capped at the own tip, never older than 8 entries back in the recent-blocks ring (the floor), never older than the block the epoch opened on (`choose_exec_block`, `crates/consensus/primary/src/proposer.rs:2018`; `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES` at `:1871`).
On main every header names the proposer's own newest executed block.
Pinned by the 17 rows of `test_quorum_exec_block_choice_table` and by `test_quorum_exec_block_header_names_the_own_ring_block` (`crates/consensus/primary/src/tests/proposer_tests.rs:2304`).

Order hold: the next header carries no digest of a worker named in an older own header that its parents do not prove to be on its own chain, until that older header commits, is canceled or re-queued, or the epoch ends; main drains every worker's queue first in, first out, one digest per worker in turn up to `max_header_num_of_batches`, whatever its older own headers carry (0554efd4f `proposer.rs:965-997`).
At this head the hold is the field `order_hold` (`proposer.rs:216`) and every drain goes through `drain_digests_except` (`proposer.rs:1198`).
On an intact own chain nothing is held (`p5_an_intact_chain_costs_nothing`, `crates/consensus/primary/src/tests/order_hold_model.rs:1155`), and `test_canceled_header_digests_ride_the_next_header` (`proposer_tests.rs:1637`) pins the hold after a cancel.
The hold changes no rule of header validity, no message and nothing a voter checks; `own_parent` on `header proposed` always comes from the hold's plan.

No longer logged or exported (each came with the stack, except main's start-up error):
- the field `exec_policy` (values `off`, `always`, `tip`, `starved`) on `header proposed`; `exec_block`, `exec_tip` and `exec_basis` stay;
- the INFO line with target `node::switches` and message `node switches`, which carried one `<yaml key>=<value>` field per switch;
- the gauge `tn_node_switch` with its label `name`;
- the start-up warnings "quorum_exec_block_starved_rounds has no effect while quorum_exec_block is off" and "quorum_exec_block_starved_rounds is above its bound; the bound is used";
- main's start-up error "vote_timeout {:?} must stay below the libp2p request timeout {:?}, …", which goes with its check.

The re-queue reason `stale_resend` stays, with its metric label, and the label stays at 0 (`crates/consensus/primary/src/metrics.rs:598-617`, counted at `proposer.rs:1160-1162`): with the hold always on it can no longer be counted, as #1869's limits explain, and after a restart a re-proposed header that had already committed counts as `unknown_seq`.

A `parameters.yaml` that still names one of the six removed keys loads, and the key is ignored without a warning, as main ignores any unknown key: `Parameters` in `crates/config/src/node.rs` has no `deny_unknown_fields`, and `unknown_keys_are_ignored` (`node.rs:1274`) pins it.

## Testing

Deleted tests, by switch, with what they tested:
- `vote_queue_fix` (#1864), the off arm: the seven `quorum_exec_block_voter_*_switch_off` tests, which turned `vote_queue_fix` off (their on bodies stay, as `old_block_in_ring_is_voted_at_once` and six more), `vote_queue_fix_off_refuses_malformed_header_without_the_wait`, `vote_queue_fix_off_answers_repeat_of_voted_header_from_cache`, and `vote_queued_requests_of_one_author_wait_in_turn`, #1864's first test, which pinned main's wait in turn (what else it asserted is covered by `vote_queued_requests_wait_once`).
  The off arm of the start-up check: main's own `vote_timeout_must_stay_below_the_libp2p_request_timeout`, whose case moved into `vote_timeout_plus_the_prelock_wait_stays_below_the_request_timeout`.
- `epoch_record_collect_past_uncertified` and `epoch_record_recertify` (#1866), the off arm: `test_collect_epoch_records_stops_at_an_uncertified_epoch_with_the_walk_off` (state-sync), `test_uncertified_epoch_stops_the_collector_with_every_switch_off` (e2e) and `test_switch_off_revotes_only_the_previous_record` (node).
  Main's own `test_startup_revote_skips_certified_record` goes too: it asserted the start-up outcome this PR changes.
- `quorum_exec_block` and `quorum_exec_block_starved_rounds` (#1868), the adaptive arm: the eight unit tests of the window, the streak, the model and the warning (`test_quorum_exec_block_adaptive_policy_state_machine`, `test_quorum_exec_block_cancel_report_reaches_the_policy`, `test_quorum_exec_block_reset_needs_a_streak_of_certified_tip_headers`, `test_quorum_exec_block_policy_model_holds_the_target`, `test_quorum_exec_block_policy_model_after_the_regime_ends`, `test_quorum_exec_block_window_counts_headers_across_a_round_jump`, `test_quorum_exec_block_window_without_a_header_does_not_double`, `test_quorum_exec_block_starved_rounds_warning`), the e2e `test_held_member_two_closes_adaptive` and `test_missed_record_round_adaptive`, and the adaptive arm of `test_fast_executor_is_certified`.
  The off arm: the control arm of `test_fast_executor_is_certified`, and the off half of `test_quorum_exec_block_switch_off_keeps_header_bytes`, which is now `test_quorum_exec_block_header_names_the_own_ring_block`.
  The mixed switches: the e2e `test_mixed_switch_fleet_is_one_chain`.
- `digest_order_hold` (#1869), the off arm: `test_digest_order_bookkeeping_keeps_payloads_golden` (the drain without the hold); `test_stale_resend_requeue_is_not_out_of_order` and `test_stale_resend_releases_its_digest_numbers` (a path the hold's guard closes; the hold's version is `test_order_hold_stale_resend_is_never_a_blocker`); `test_canceled_requeue_behind_a_newer_digest_counts_out_of_order` and `test_committed_requeue_behind_a_committed_digest_counts_out_of_order` (the overtake of #1807, which the hold prevents; the hold's versions are `test_order_hold_keeps_a_canceled_headers_lane_in_order`, `test_order_hold_replays_the_model_counterexample` and `test_order_hold_warns_once_per_requeue_out_of_order`); and the e2e control `test_without_the_hold_the_far_validator_reorders`.
  The model's four tests that run the model without the hold stay (`hold_off_model_finds_the_overtake`, `hold_off_overtakes_often_enough`, `canceled_story_overtakes_only_without_the_hold`, `committed_story_overtakes_only_without_the_hold`): they flip the model's own flag and never read the node's configuration.
- The switch machinery (#1862): config `switches_list_every_switch_field`, `switch_values_render_as_their_yaml`, `switch_value_display_and_gauge`, `switch_value_kind_follows_the_field_type`, `absent_switch_keys_load_the_defaults`, `switch_at_default_is_not_written`, `chain_presets_leave_every_switch_at_its_default` and `node_switches_line_renders_yaml_tokens`, and node `test_node_switch_gauge_per_switch`.

Kept tests that changed:
- `test_vote_older_round_rejected`: a round-1 header after the round-2 request now gets `SupersededRequest`; a new first case keeps the old answer where it still applies, when the round-2 vote is held only on disk and no newer request has been seen.
- `test_vote_cached_across_stale_headers`: a different header for the older round now gets `SupersededRequest`, the same-round header still gets `AlreadyVotedForLaterRound`, and both refusals keep the cached vote.
- `test_vote_cached_across_dropped_request`: a repeat of the older, voted header after a dropped newer request is now refused as `SupersededRequest`, and the cached vote stays.
  The test was written for the property that a request dropped mid-evaluation puts the decision entry back (#1836); its newer request is now dropped during the wait before the lock, so it no longer exercises that property.
- `test_vote_tier_three_lead_is_rejected_before_execution_wait` is now `test_vote_tier_three_lead_waits_only_for_an_unexecuted_block`: a tier-three lead naming a block the voter lacks is refused after the 1 s wait, and a new case shows that a header naming a block the voter holds is still refused at once.
- `test_withhold_hook_silences_only_the_first_round_by_default` now expects {1, 2, 3, 4} where it expected {2, 3, 4}, and `test_withhold_hook_rounds_reach_the_failsafe` {1, 2, 4} where it expected {2, 4}: the closes of epochs 3 and 4 now also re-vote record 1.
- The e2e walk test in `epoch_record_walk.rs` keeps its assertions (epoch K stays uncertified, every collector walks past it).
  Now that re-certify rounds run, 64 withheld vote rounds keep K uncertified, and its check that no re-certify round is logged became: every validator logs re-certify rounds for K only, none certifies, and at least one round ends short.
- `test_fast_executor_is_certified` runs on the plain node and asserts absolute bounds under the rule: every node builds at least 20 headers in 90 s, every slow node and the fast node certify at least 0.93 of their own headers, at least 0.5 of the fast node's headers in the second half name `exec_basis=floor`, there is no canary and no fatal line, and all four nodes hold the same blocks.
  `test_held_member_two_closes` and `test_missed_record_round` run on the plain node with their assertions unchanged; the order-hold e2e tests are now `test_hold_keeps_every_transaction_before_store` and `test_hold_keeps_every_transaction_after_store`.
- `test_canceled_header_digests_ride_the_next_header` now pins the hold in full: the header built while round 1 is pending and not citing it is empty for that worker, and the header after the cancel report carries the canceled digests first, then the held one, then the newest.
  `test_lane_sequence_survives_requeues`, `test_proposer_stopped_reports_what_it_leaves` and `test_requeues_that_keep_lane_order_count_nothing` build each header on the previous own header, so nothing is held, and keep every assertion; two of them send a cancel report or a commit notice that a running node would not send for a header that another header cites as its own parent, and a comment in each says so.

One test is added, `test_startup_rearm_casts_no_own_vote_for_a_certified_latest_record` (node): with records 0 and 1 uncertified behind a certified record 2, the start-up re-arm arms record 2, and the node publishes re-votes for records 0 and 1 and no vote for record 2.
The mixed-binary vote test added on the way is reverted (see the Summary).
The six commits after `e1a562cbb` change no assertion of a kept test: they reword comments and docs that still spoke of a switch, drop section markers, rename the e2e scaffold's example keys from `example_switch` and `other_switch` to `example_parameter` and `other_parameter`, make the e2e header-window helper private to `exec_block.rs`, and add the test above.

Stack-wide gates for this PR run on its head, `refactor/remove-bench-switches` at `54aa60932` (20 commits on `500e21afa`), each once: no off arm is left to run them against.
- The checks made with each group of commits passed: `cargo check --locked --all-targets`, fmt, clippy with warnings denied and `cargo nextest run` for the crates the commits touch.
- Not finished when this text was last updated, and added here when they are: `cargo +nightly-2026-03-20 fmt --all -- --check`; `./etc/ci-lanes.sh clippy`; `cargo nextest run --locked --workspace`; every commit of this PR compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied); `make test-restarts`, `make test-epochs`, `make test-sigkill` and `make test-e2e-resync`; the e2e tests the stack adds (`exec_block`, `epoch_close_forms`, `epoch_record_walk`, `digest_order_hold`), three runs each; `make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time); the three `state_export_import` tests, which restore a node from an exported state; the order hold's model hunt, 100,000 cases.
- Until the e2e gates above have run, the e2e tests this PR changes have been compiled and not run.

## Limits and what a reviewer should look at

- The tests that showed "switch off equals main" are gone with the switches: after this PR the comparison with main is the rolling-upgrade test (`make test-upgrade`, previous binary `main`), not a per-switch off arm.
  That test covers old and new binaries making one chain through an in-place upgrade; it slows no node and reads no `exec_basis`, so it does not show a voter on main's binary voting for a header of this tree that names a block older than the proposer's own tip, and no test of that case is added (the deleted `test_mixed_switch_fleet_is_one_chain` showed it between nodes of one binary).
  What main's voter does with such a header is read from its code only (`crates/consensus/primary/src/network/handler.rs:1456-1507` at 0554efd4f): it waits up to 1 s (`VOTE_EXECUTION_WAIT`) for the block a header names; it refuses for good only when it holds a different block at that number or the number is below its restore floor; a block still above its tip when the wait ends gets the recoverable `ExecutionBehind`, so the proposer asks again; a block it holds passes the check, whether or not it is the proposer's tip.
- `vote_timeout` strictly below 9 s is a start condition for every node; the code default, the mainnet preset (both 5 s) and the testnet preset (the default) satisfy it, and a node configured at 9 s or more fails when it enters a live epoch.
- A voter restored from a snapshot refuses, for good and without a penalty, a header that names a block below its floor; under the quorum rule a header can name a block up to 8 ring entries behind the proposer's tip, older than the block main names.
- A tier-three timestamp lead on a header that names a block the voter has not executed is refused after a wait of up to 1 s, not at once; moving that check ahead of the wait would be a design change and is left open.
- No test aims at the hold's two known gaps on a running node: a garbage-collection cut below the leader (counted, not prevented; the model's `gc_cut_is_the_only_overtake` covers it) and the wait after a re-send after a restart (`test_hold_survives_a_kill_of_the_far_validator` restarts the hooked validator under load and asserts that no transaction is lost, not that wait).
- No test runs an uncertified epoch beside a node on a previous binary.
- The stack ran beside main at 33b727fce, the stack's base, not beside `v0.17.0-adiri`.
- Always-on is the only form left.
  Bench 7 ran one run of each form at 20,000 IOPS ([r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/) always-on, [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/) adaptive), and in that pair the adaptive form did not do better; bench 7 made no run at 50,000 IOPS, where bench 6 had the adaptive form ahead on certification.
  The depth of the floor of 8 is open in #1804.
- Each request's wait before the lock is capped at 1 s, but with the default serve budget nothing caps how many requests of one author wait at once: a serve class with capacity zero is unbounded, and zero is the default for every class (`crates/network-libp2p/src/serve_permits.rs:15-16`).
  Only the authenticated author can cause it, and on main N queued requests held their tasks for up to N × 1 s; counting waiters per author and answering `ExecutionBehind` past a small cap is a possible follow-up.
- The e2e tests this PR changed were compiled with their commits and are run by the stack-wide gates above, not before; the before-store order-hold test has not run under the always-on rule before them.
- The `stale_resend` classification and its metric label are dead code after this PR and are left in place: removing them is a change on a kept path, and a possible follow-up.

## Related

- Refs #1804: the voter's side (#1864) and the author's side in its always-on form (#1868) are now unconditional; the depth of the floor of 8 stays open there.
- Refs #1807: the own-chain order hold (#1869) is now unconditional; the issue's second defect, a resend that executes beside the original, is not touched.
- Refs #1850: the walk past an uncertified epoch and the re-certify round (#1866) are now unconditional; the question in the issue's comment, whether the stop on a conflicting certified record should need a super-quorum of the full committee, stays open there.
- Refs #1852: the stack's fix for it had no switch and is unchanged; re-certify rounds, which now run on every node, leave the signers gauge alone (`test_recertify_rounds_leave_the_signers_gauge_alone`).
- #1862: the switch list, the `node switches` line and the `tn_node_switch` gauge this PR removes; the rest of its observability stays.
- #1863: the e2e override scaffold, which stays.
- #1864: the voter's wait before the lock and the superseded refusal, now unconditional.
- #1865 and #1867: no switch; their changes were unconditional already.
- #1866: the record walk and the re-certify round, now unconditional.
- #1868: the quorum execution block, now unconditional and in its always-on form only.
- #1869: the own-chain order hold, now unconditional.
