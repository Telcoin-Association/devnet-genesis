# Sources: bench6-09-remove-bench-switches.md (not for posting)

Worktree `/home/drtnarg/coding/telcoin/tn-b8-uc`, branch `refactor/remove-bench-switches`, tip counted e1a562cbb (no closing commit had landed at the time of writing: `git log --oneline 500e21afa..HEAD | wc -l` = 14, checked three times).
F = `tasks/bench8/pr9-facts.md` (line). B0x = `tasks/pr-bodies/bench6-0x-*.md` (line). "HEAD:" = at e1a562cbb. Brief = `tasks/bench8/briefs/w-9.md`.

## Summary
- six switches and their PRs: F:9-10, F:21-22 (#1866), F:33 (#1864), F:52 (#1868), F:65 (#1869); B00:4 (machinery).
- `runtime_switches!`, `node switches`, `tn_node_switch`: F:77-78.
- always-on kept, adaptive (window, streak, two constants) deleted: F:52, B05:10.
- owner's decision: F:10, brief :19 (worded without a name).
- `Parameters` = main 0554efd4f fields and Default values: F:83; B00:114.
- removed key loads, ignored: F:15; B00:113.
- position line: #1862 branch `feat/bench6-switches-obs`, #1863-#1869 merged 2026-11-16: brief :8-10. 14 commits: `git log --oneline 500e21afa..HEAD | wc -l` at e1a562cbb.
- `0a70b58f5` adds, `e1a562cbb` reverts, tree equal: brief :12, F:88; `git log` subjects ("test(e2e): old-binary voters vote for a header that names an older block", "Revert ...").
- `make attest`, merge sentence: brief :10; B06:11-12.

## Problem
- "No chain preset sets any of them": the deleted test `chain_presets_leave_every_switch_at_its_default` (F:80).
- default off; with a switch off main's path: B02:44 ("with the switch off, every vote decision is main's"), B05:3, B06:3, B04:4.

## Change (table and paragraphs)
- #1864 row: F:33, F:17 (start-up check removed), main's check `vote_timeout < LIBP2P_REQUEST_TIMEOUT` at 0554efd4f `crates/config/src/consensus.rs:543-547`; commit adecca691 "drop the vote timeout check the pre-lock bound covers". 11 tests = 7 `quorum_exec_block_voter_*_switch_off` + 2 `vote_queue_fix_off_*` + `vote_queued_requests_of_one_author_wait_in_turn` + `vote_timeout_must_stay_below_the_libp2p_request_timeout` (F:47).
- #1866 row: F:21-22; 4 tests F:25.
- #1868 row: F:52, F:55 (exec_policy, warnings), F:56 (8 unit tests, switch_off_keeps_header_bytes off half), F:57 (3 e2e + 2 arms). 20 always-on rows: F:56; test name `test_quorum_exec_block_choice_table` from `git show 500e21afa:crates/consensus/primary/src/tests/proposer_tests.rs`.
- #1869 row: F:65; 5 proposer tests + e2e control F:67.
- machinery row: F:77, F:79-81; kept `unknown_keys_are_ignored`, `reserializing_keeps_the_existing_keys` F:80, B00:33.
- `VOTE_EXECUTION_WAIT` 1 s: HEAD:crates/config/src/consensus.rs:460.
- `sync_epoch_records_to_tip`, `spawn_epoch_record_collector` signatures = main: F:21.
- +142 / -1,332 node code: F:52 ("142 lines added and 1,332 deleted").
- same expression, filters in `quorum_rule_choice`, no expected header bytes changed: F:54.
- `drain_digests_for_header` = `drain_digests_except` with empty set; `cites_own_parent` same value: F:65, F:70.
- `order_hold.rs` docs only: `git diff 500e21afa HEAD -- crates/consensus/primary/src/order_hold.rs` (only `//!` lines changed in the hunk read); 100,000-case hunt: F:65.
- epoch-entry gauge, digest-receipt fix, histogram buckets kept: F:79.
- `STACK_SWITCHES_ON/OFF`, `expected_switches`, `assert_switches`, no e2e test deleted, later wait: F:81.
- scaffold, four files, hook variables, cadence parameters: F:82; B01:17.

## What a node does differently
- no storage/execution crate, no message type: `git diff --stat 500e21afa HEAD` (24 files: config, consensus/primary, e2e-tests, network-libp2p/serve_permits.rs (docs), node, state-sync, cli README, types/test_hooks.rs); F:39 (SupersededRequest not a new wire type).
- superseded check HEAD:crates/consensus/primary/src/network/handler.rs:1382; `check_header_lead` :1415.
- four points: copied from B02:95-98 (figure-checked body); F:35-38.
- four tests named: commit body of 6a7c3d7c5 (`git log -1 --format=%b 6a7c3d7c5`).
- mark moves on arrival; cached refusal replayed under the lock: F:43-44.
- RecoverableError, 6 retries at 250 ms, Error fatal, no penalty: B02:99-100; F:39. `message.rs:296` at HEAD maps SupersededRequest.
- `validate_vote_timeout` HEAD:crates/config/src/consensus.rs:511 (bounds at :522-545); called by `validate_epoch_timing` :470-476; live-epoch call HEAD:crates/node/src/manager/node/start_epoch.rs:480. 8.999 s / 9 s, presets 5 s, testnet default: F:16, B02:101-102. main's "below 10 s": 0554efd4f consensus.rs:543. Test `vote_timeout_plus_the_prelock_wait_stays_below_the_request_timeout` HEAD consensus.rs:798. `LIBP2P_REQUEST_TIMEOUT` 10 s HEAD consensus.rs:450.
- walk: F:21; main stops there: #1850 title ("An epoch the network never certifies stops every record collector there"); `test_uncertified_epoch_walked_past` HEAD:crates/e2e-tests/tests/it/epoch_record_walk.rs:179.
- start-up re-arm: F:23; `revote_uncertified_epoch_record_on_startup` HEAD:crates/node/src/manager/epoch_votes.rs:786 (log at :803); `MAX_RECERTIFY_LOOKBACK` = 16 at :56; `test_startup_rearm_recertifies_behind_a_certified_latest_record` :3676, rows from F:23; main's test `test_startup_revote_skips_certified_record` at 0554efd4f epoch_votes.rs:691.
- committee member only: F:23, B04:59; `test_recertify_skips_a_record_outside_our_committee` HEAD epoch_votes.rs:3578.
- conflict stop: B04:95-96 wording; doc HEAD epoch_votes.rs:138-143; `test_recertify_round_stops_on_a_conflicting_record` :4413.
- exec block rule wording: B05:4; `choose_exec_block` HEAD proposer.rs:2018; `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES` = 8 at :1871; main names own newest executed block: B05:3; `test_quorum_exec_block_header_names_the_own_ring_block` HEAD proposer_tests.rs:2304.
- hold rule: B06:126 wording (corrected form, F:66); main's drain 0554efd4f proposer.rs:965-997 (F:66; doc at :965-972 read); `order_hold: OwnChainOrder` HEAD proposer.rs:216; `drain_digests_except` :1198; `p5_an_intact_chain_costs_nothing` HEAD order_hold_model.rs:1155; `test_canceled_header_digests_ride_the_next_header` HEAD proposer_tests.rs:1637; validity/messages/votes unchanged: B06:5; own_parent: F:65.
- no longer logged: F:55 (exec_policy, warnings verbatim), F:78 (`node::switches`, `tn_node_switch` label `name`); main's error text: F:17 and 0554efd4f consensus.rs:544.
- `stale_resend`: F:71, B06:128-130; HEAD metrics.rs:598-617; HEAD proposer.rs:1160-1162.
- parameters.yaml: F:15; no `deny_unknown_fields` in crates/config/src/node.rs (git grep at HEAD finds it only in network.rs, trusted.rs, network_budget.rs, source_admission.rs); `unknown_keys_are_ignored` HEAD node.rs:1274.

## Testing
- deleted lists: F:47 (#1864; `old_block_in_ring_is_voted_at_once` HEAD network_tests.rs:7058; `vote_queued_requests_wait_once` :5806; F:46), F:25 (#1866), F:56-57 (#1868; full names from `git show 500e21afa:.../proposer_tests.rs`), F:67-68 (#1869), F:80 (#1862).
- four vote tests changed: commit body 6a7c3d7c5. `test_vote_cached_across_dropped_request` gap and #1836: F:40; HEAD network_tests.rs:1922.
- withhold hook sets: F:26; HEAD epoch_votes.rs:3945, :3954.
- walk test: F:27.
- fast executor bounds (20 headers, 90 s, 0.93, 0.5, exec_basis=floor, four nodes): F:57.
- order-hold e2e names: `git show HEAD:crates/e2e-tests/tests/it/digest_order_hold.rs` (test_hold_keeps_every_transaction_before_store / _after_store).
- reworked proposer tests: F:66, F:72.
- no test added: commit list; 0a70b58f5 reverted by e1a562cbb.

## Limits
- bullet 1: brief :40, F:60, F:92; B05:122-125 wording. main's voter read at 0554efd4f: handler.rs:1456-1507 (wait `tokio::time::timeout(VOTE_EXECUTION_WAIT, wait_for_execution)`; Fork -> `UnknownExecutionResult`; BelowFloor -> `BelowRestoreFloor`; timeout -> `ExecutionBehind`); `VOTE_EXECUTION_WAIT` 0554efd4f consensus.rs:459; `wait_for_execution` 0554efd4f consensus_bus.rs:1728-1757 (Match -> Ok for a held block at that number); ExecutionBehind -> RecoverableError 0554efd4f network/message.rs:292-293.
- bullet 2: F:16, B02:101-102.
- bullet 3: F:102; 0554efd4f handler.rs:1480-1495 (final refusal without a penalty, doc comment); 8 ring entries: B05:4.
- bullet 4: F:38, F:41.
- bullet 5: B06:125 wording (`gc_cut_is_the_only_overtake`, `test_hold_survives_a_kill_of_the_far_validator`); F:103.
- bullet 6: F:104, B04:97.
- bullet 7: F:105, B02:51.
- bullet 8: B05:11 (one run each at 20,000 IOPS, "did not do better", no run at 50,000 IOPS, bench 6 adaptive ahead on certification); run ids/links: brief :29, B05 (r20261115-1131 always-on, r20261115-1653 adaptive); floor of 8 open in #1804: B00:126.
- bullet 9: F:45; HEAD:crates/network-libp2p/src/serve_permits.rs:15-16 ("A class capacity of zero means unbounded ... Zero is the default for every class"). The per-peer limit of 2 (F:45) not stated: not verified.
- bullet 10: brief :48, F:61.
- bullet 11: F:71, brief :49.

## Related
- issue titles: `gh issue view` 1804, 1807, 1850, 1852 (all OPEN).
- #1807 second defect: B00:127.
- #1852: B00:124 (fixed by the stack; gauge reports signers, #1866); `test_recertify_rounds_leave_the_signers_gauge_alone` at 500e21afa epoch_votes.rs:3823 (HEAD :3750).
- #1865, #1867 had no switch: the six switches belong to #1864, #1866, #1868, #1869 (F:9-10, B00:4).
