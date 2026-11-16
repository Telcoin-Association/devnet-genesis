# Sources: bench6-01-e2e-scaffold.md (#1863), second pass: the switches go in {{pr-09}} (not posted)

Facts file: `tasks/bench8/pr9-facts.md`, sections "R5" (the scaffold stays and what goes through it) and "R3" (the e2e tests deleted).
Code read: `/home/drtnarg/coding/telcoin/tn-b8-uc`, the removal branch `refactor/remove-bench-switches` at 57a55b221 (last of its 12 commits), and 500e21afa (#1869's head, the branch's base).
Untouched: the stack-position lines, the merge-method sentence, the `Stack-wide gates` block (its two lines that mention switches stay as the script wrote them), and :5 "Test code only: no node crate changes, and there is no switch" (true of this diff and of the stack as it merges).
No figure, run id or commit id was added.

## Changed sentences

1. Summary :3, end of the sentence.
   Old: "…, so a switch can be tested on part of a fleet or across an existing test set without editing the tests."
   New: "…, so part of a fleet can run with its own parameters or test hooks, and an existing test set with a parameter set from outside, without editing the tests."
   Source: pr9-facts R5, "#1863's e2e scaffold (`NodeOverrides`, `FleetOverrides`, `TN_E2E_PARAMETERS`) stays and is still used … test hook variables … header cadence parameters … a whole test set can still be run with a parameter set from outside".
2. Summary, new :7.
   New: "The stack added the scaffold to test its switches on part of a fleet; {{pr-09}}, the last PR of the stack, removes the switches and keeps the scaffold."
   Source: the old :3 and :14 (the scaffold's purpose); brief "What happened" (the ninth PR removes the six switches); pr9-facts R5 (the scaffold stays).
3. Summary, new :8.
   New: "After it, the stack's later e2e tests pass test hook variables and header cadence parameters through `NodeOverrides` and `FleetOverrides`; no test sets `TN_E2E_PARAMETERS`, but a lane can still run a whole test set with a parameter set from outside."
   Source: pr9-facts R5 (same bullet as 1). Checked at 57a55b221: `grep -nE 'NodeOverrides::|FleetOverrides::|_with_overrides\(' crates/e2e-tests/tests/it/*.rs` outside `common.rs` hits `epoch_record_walk.rs:154,274`, `digest_order_hold.rs:238`, `epoch_close_forms.rs:289,440,663` (289 and 440 are `FleetOverrides::default()`, empty), `exec_block.rs:84` and the helper `fleet.rs:192`.
   Deliberately no count: R5 says "five tests pass non-empty overrides"; the orchestrator's prompt said "five test files"; the grep shows four test files plus the helper module `fleet.rs`. Not reconciled, so the text names none.
4. Problem :16 (was :14), tense only.
   Old: "Bench 6 put each fix behind a switch whose default is main's behaviour, so its e2e tests need fleets where some nodes run a switch and others do not, and the existing restart, epoch and sigkill sets have to pass with each switch on."
   New: the same sentence in the past tense ("was", "needed", "ran", "did not", "had to pass").
5. Problem, new :17.
   New: "The stack's later e2e tests also give chosen nodes test hook variables (an execution delay, an own-certificate delay, withheld epoch votes, an exit before the epoch record), and that need stays after {{pr-09}} removes the switches."
   Source: pr9-facts R5, the list in parentheses is R5's "test hook variables: execution delay, own-certificate delay, withheld epoch votes, exit before the epoch record". Per-node use seen at 57a55b221: `epoch_record_walk.rs:154` `FleetOverrides::default().env(withholding.clone(), WITHHOLD_EPOCH_ENV, …)`, `exec_block.rs:84` `FleetOverrides::default().env(`.
6. Limits :90 (was :87), second line of the first bullet.
   Old: "A helper that waits for the key in the `node switches` line (from `feat/bench6-switches-obs`) would catch it for switch keys; it is not in this PR."
   New: "Later in the stack, `assert_switches` in `fleet.rs` checks a node's `node switches` line (from `feat/bench6-switches-obs`) against the switch entries the test gave it; {{pr-09}} removes that check with the line and the switches."
   Source: `git grep` at 500e21afa, `crates/e2e-tests/tests/it/fleet.rs:4` ("[`assert_switches`] checks the `node switches` …"), `:122` ("What the `node switches` line of a node given the switch entries `given` must show"), `:341` `const SWITCHES_LOG: &str = "node switches";`, `:349` `pub(crate) fn assert_switches(`; `fleet.rs` was added by ff877fb0e ("test(e2e): an epoch the network never certifies, walked past and re-certified"), above this PR. Removal: pr9-facts R5 ("`STACK_SWITCHES_ON`, `STACK_SWITCHES_OFF`, `expected_switches`, `assert_switches` and their helpers are gone from `fleet.rs`"; the `node switches` line is removed).
7. Limits :92 (was :89), end of the sentence.
   Old: "…, so a test copied from one loses its switch at the restart."
   New: "…, so a test copied from one loses its entries and variables at the restart."
   Source: the body's own :37 ("a restart through a helper without overrides drops a node's entries and variables").
8. Related :101 (was :98).
   Old: "…, #1868 (`fix/1804-quorum-exec-block`), whose e2e test runs a mixed-switch fleet with `FleetOverrides`, and #1869 (`fix/1807-digest-order-hold`)."
   New: "…, #1868 (`fix/1804-quorum-exec-block`), whose mixed-switch fleet test (`test_mixed_switch_fleet_is_one_chain`, built with `FleetOverrides`) {{pr-09}} deletes, #1869 (`fix/1807-digest-order-hold`), and last {{pr-09}}, which removes the stack's switches and keeps this scaffold."
   Source: pr9-facts R3 ("e2e: deleted `test_mixed_switch_fleet_is_one_chain`"); the old sentence (it uses `FleetOverrides`); pr9-facts R5 (scaffold kept).

`{{pr-09}}` placed: 5 (Summary 1, Problem 1, Limits 1, Related 2).
