# Figure-check FC-9a: bench6-09-remove-bench-switches.md, lines 1-103

Verdict: FIX (3 errors, none changes a conclusion; 5 weak; 3 not traceable within budget; lint clean; no rule breach).

Sources read: the removal branch at e1a562cbb (tree = 57a55b221), the base 500e21afa (tree = 105e584ac), upstream main 0554efd4f, the PR heads b29d59bef to 500e21afa, and the bodies bench6-00, -04, -05, -06.
Every old string below occurs exactly once in the whole file (grep -c -F = 1).

## Errors

1. Line 27 (Change table, #1868 row, "Stays"): the text says "the 20 always-on rows of `test_quorum_exec_block_choice_table`".
   At e1a562cbb the `cases` vec of that test (proposer_tests.rs:2060-2132) has 17 rows, plus a short-ring and an empty-ring check after the loop.
   At 500e21afa the vec had 20 rows: 17 `ExecPolicy::Always`, 1 `Off`, 1 `Starved`, 1 `Tip`; the 17 always-on rows are the ones kept.
   Replacement: `the 20 always-on rows of \`test_quorum_exec_block_choice_table\`` → `the 17 always-on rows of \`test_quorum_exec_block_choice_table\``
2. Line 86 (Execution block): "Pinned by the 20 rows of `test_quorum_exec_block_choice_table`": same source, 17 rows at this head.
   Replacement: `Pinned by the 20 rows of \`test_quorum_exec_block_choice_table\`` → `Pinned by the 17 rows of \`test_quorum_exec_block_choice_table\``
3. Line 40 (For #1868): "in the node code that is 142 lines added and 1,332 deleted".
   The figures are the whole numstat of a242a3b4a, unit tests included: node.rs 0/38, proposer.rs 22/345, network_tests.rs 4/4, proposer_tests.rs 116/945 (142/1,332).
   The non-test node code is 22 added and 383 deleted; a right number under a wrong label.
   Replacement: `in the node code that is 142 lines added and 1,332 deleted` → `in its commit, unit tests included, that is 142 lines added and 1,332 deleted`

## Weak

1. Line 64: "four of main's own tests" are then named with `test_vote_tier_three_lead_waits_only_for_an_unexecuted_block`, a name main does not have: on main (and at 500e21afa) it is `test_vote_tier_three_lead_is_rejected_before_execution_wait`, renamed in 6a7c3d7c5. A reviewer searching main finds three of the four.
   Replacement: `` `test_vote_tier_three_lead_waits_only_for_an_unexecuted_block`, in `` → `` `test_vote_tier_three_lead_waits_only_for_an_unexecuted_block` (main's `test_vote_tier_three_lead_is_rejected_before_execution_wait`, renamed here), in ``
2. Line 27, #1868 "Deleted": the 3 non-always rows of the choice table (Off, Starved, Tip at 500e21afa) also go and are not named.
   Replacement: `8 unit tests and the off half of a ninth` → `8 unit tests, the off half of a ninth and 3 rows of the choice table`
3. Line 91 (Order hold): "Header validity, the messages and what peers vote for do not change" is true of the hold, but read alone it contradicts the Votes section (a voter after this PR refuses, as `SupersededRequest`, an older-round request main's voter would decide in full after a recoverable answer to the newer one).
   Replacement: `Header validity, the messages and what peers vote for do not change` → `The hold changes no rule of header validity, no message and nothing a voter checks`
4. Line 67: the response is `PrimaryResponse::RecoverableError(PrimaryRPCError(..))` (message.rs:296-298 at e1a562cbb), not `(String)`.
   Replacement: `` `PrimaryResponse::RecoverableError(String)` `` → `` `PrimaryResponse::RecoverableError` ``
5. Line 9: the Files tab shows files; the 14 commits are on the Commits tab.
   Replacement: `so the Files tab shows this change alone (14 commits)` → `so the Files tab shows this change alone and the Commits tab its 14 commits`

## Not traceable (within budget)

1. Line 100: "after a restart a re-proposed header that had already committed counts as `unknown_seq`": not in #1869's body (bench6-06 has no `unknown_seq`), so "as #1869's limits explain" covers only the first clause; not checked against the proposer's restart path.
2. Line 81: "a restart does not change the stored record, so a later pick stops it again" is not in epoch_votes.rs:138-143 (those lines state the stop on a conflicting record, for any epoch); the restart half was not located.
3. Line 50: that the e2e tests in `digest_order_hold.rs`, `epoch_close_forms.rs`, `epoch_record_walk.rs`, `exec_block.rs` still pass hook variables and cadence parameters through the scaffold: not opened.

## Verified (selection)

- 14 commits in 500e21afa..e1a562cbb; `git diff --stat 57a55b221 e1a562cbb` empty; 0a70b58f5 touches only `upgrade.rs`; trees of 105e584ac and 500e21afa equal.
- Each switch's PR, by field presence at each head: `vote_queue_fix` first at 17327280d (#1864), both `epoch_record_*` at ff877fb0e (#1866, absent at #1865's c2f266b9c), both `quorum_exec_block*` at 38f00e88e (#1868), `digest_order_hold` at 500e21afa (#1869), `runtime_switches!` at b29d59bef (#1862), `NodeOverrides`/`TN_E2E_PARAMETERS` at 87be96651 (#1863).
- `Parameters` vs main: `git diff 0554efd4f e1a562cbb -- crates/config/src/node.rs` changes only the `vote_timeout` doc and adds the two tests; no `deny_unknown_fields` in node.rs (only on network-config structs); `unknown_keys_are_ignored` at node.rs:1274.
- Deleted-test counts by `#[test]`/`#[tokio::test]` count and names per commit: vote_queue_fix 10 (network_tests 144→134) + 1 (adecca691) = 11; #1866 4; #1868 8 + off half of `..._switch_off_keeps_header_bytes`, e2e net 3 + two arms in exec_block.rs; #1869 5 proposer tests + `test_without_the_hold_the_far_validator_reorders`; machinery 8 config + 1 node; 1d41981dd deletes no e2e test.
- Votes: pre-lock `refuse_superseded_request` (handler.rs:1061, body :1376-1396, `SupersededRequest` :1382), mark recorded only when in window, strict `round <` of the same epoch; same-round other digest still `AlreadyVotedForLaterRound` (:1194-1199); tier-three check under the lock (:1539) after the pre-lock wait, main checks it before its under-lock wait (main :1422 vs :1465); main has no `SupersededRequest`; retry 6 × 250 ms (network/mod.rs:2041-2055), then the certifier's backoff until cancel; `PrimaryResponse::Error` → `RPCError` fatal.
- Start condition: consensus.rs:511 `vote_timeout + VOTE_EXECUTION_WAIT < LIBP2P_REQUEST_TIMEOUT` (10 s), lower bounds kept; main's check `vote_timeout < 10 s` and its message; start_epoch.rs:480 live only; default 5 s, mainnet 5 s, testnet unset; test at :798.
- Epoch records: `MAX_RECERTIFY_LOOKBACK = 16` (:56), function at :786, main re-arms only an uncertified latest record; test rows `(false, true)`, `(true, false)` at :3676; :3578, :4413; signatures of `sync_epoch_records_to_tip` and `spawn_epoch_record_collector` equal main's.
- Proposer: :216, :1198, :1871 (= 8), :2018, :1160-1162; main's drain at 0554efd4f :965-997 round-robin with `take(max_header_num_of_batches)`; order_hold.rs diff is comments only; model test :1155 and 100,000 cases.
- Removed outputs at 500e21afa, none left at e1a562cbb: `exec_policy` values off/always/tip/starved (proposer.rs:2028-2031), `node::switches`/`node switches`, `tn_node_switch` with label `name`, both warnings verbatim.
- Cross-body: switch-to-PR attributions agree with bench6-00 (:33), bench6-04 (#1850, :3), bench6-06 (:128, `stale_resend` no longer counted).

## Rule breaches

None in lines 1-103 (no unit name, private path, host, IP, bold, tool mention). Lint: `LINT-OK` on a copy (no token to replace).

## Counts

Figures and claims checked: 96; matched: 90; wrong: 3; not traceable: 3; weak (among the matched): 5.
