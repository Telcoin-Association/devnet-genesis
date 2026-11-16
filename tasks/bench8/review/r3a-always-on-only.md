# Review RV-3a: always-on is the only form (R3 part A)

Commit `a242a3b4a` in `tn-b8-uc` (base `6a7c3d7c5`), "refactor(primary): every header names an execution block a quorum holds": +142 / -1,332 over `crates/config/src/node.rs`, `crates/consensus/primary/src/proposer.rs`, `tests/proposer_tests.rs`, `tests/network_tests.rs`. All line numbers below are at `a242a3b4a` unless marked "base".

## Verdict: approve with follow-ups

Every header at the tip gets exactly what the base gave under `quorum_exec_block: true`, `quorum_exec_block_starved_rounds: 0`. No statement on a kept path changed. The three findings are Low: two test docs still say "both forms", and one local variable is still named after the policy. Counts: Critical 0, High 0, Medium 0, Low 3.

## The four questions

1. **Is anything of the adaptive arm left?** Nothing in code. `git grep` at the tip finds no `ExecPolicy`, `ExecBlockPolicy`, `exec_block_policy`, `applies_quorum_rule`, `QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`, `QUORUM_EXEC_BLOCK_RESET_STREAK`, `starved` or `exec_policy` in `crates/consensus/primary` or `crates/config`. In `node.rs`, the switch lists at :511-513 and :710-713 now hold only `digest_order_hold`. The only `quorum_exec_block` names left in the primary crate are the floor constant and test names of kept tests (proposer_tests.rs:2036, 2197, 2289, 2322, 2379, 2454, 2526). The e2e modules still set both keys and read `exec_policy` (exec_block.rs:71-74, :396; fleet.rs:103-112; epoch_close_forms.rs:313; digest_order_hold.rs:234). They are part B's job, being done now, and they are not findings here. What remains in wording: L1-L3.
2. **Did any statement on a kept path change?** No.
   - A. Base `ExecBlockInputs::new(Always, …)` took the `applies_quorum_rule()` branch: `parents.iter().map(|parent| ParentExecBlock::new(parent, committee)).collect()`. The tip (proposer.rs:1992) runs the same expression with no `if`. `author`, `own_power`, `epoch` and `quorum_threshold` are unchanged. The filters (epoch, `round > 0`, `>= lowest_usable`, own author, one count per author) live in `quorum_rule_choice` (:2080), which the diff does not touch. The genesis seed at :350 is also untouched. The call site at :1404 passes the same `&self.committee, &authority_id, &parents`.
   - B. The guard `!inputs.policy.applies_quorum_rule() || ring.is_empty()` became `ring.is_empty()` (:2066). Under Always the first operand is `false`, so the condition is the same. That `if` held nothing else. The Off branch removed from `choose()` (:2008) was unreachable under Always.
   - C. At the base, both `on_cancelled` and `on_certified` returned at once when `!adaptive()` (`base_window == 0`). `for_round` returned `Always` without touching state. None of the three logged, counted a metric or wrote state that the kept path reads. The own-parent `.find` was a pure read. `process_uncertified_header` (:1049) is otherwise unchanged.
   - D. The base `exec_off` (Off) read `consensus_bus.app().latest_execution_block_num_hash()`, which is `tx_recent_blocks.borrow().latest_execution_block_num_hash()` (consensus_bus.rs:1354). That is the same ring `choose_exec_block` reads. `exec_no_parents` (proposer_tests.rs:1950) gives `values = [(tip, own_power)]`. The quorum value is then `None`, or equal to the tip and removed by the `< tip` cap, so the result is the own tip, and an empty ring gives the same default. `test_multi_worker_proposed_header_payload` and `propose_round_two` changed only the helper call, with no expected value touched. In a real node's first round, the genesis parents (round 0) are skipped under both commits, so the result is the same block.
   - E. The `header proposed` line (proposer.rs:500-519) loses only `exec_policy`. `exec_block`, `exec_tip` and `exec_basis` keep their names, order and expressions. At the base, `ExecPolicy::as_str` had one consumer, the log field (base proposer.rs:541), and no metric label. Removed field, verbatim: `exec_policy = exec_inputs.policy.as_str()` (values `off`, `always`, `tip`, `starved`). The start-up `warn!` is removed with its two texts, "quorum_exec_block_starved_rounds has no effect while quorum_exec_block is off" and "quorum_exec_block_starved_rounds is above its bound; the bound is used".
3. **Was a test of the kept behaviour deleted or weakened?** No.
   - The eight deleted tests (`…adaptive_policy_state_machine`, `…cancel_report_reaches_the_policy`, `…reset_needs_a_streak_of_certified_tip_headers`, `…policy_model_holds_the_target`, `…policy_model_after_the_regime_ends`, `…window_counts_headers_across_a_round_jump`, `…window_without_a_header_does_not_double`, `…starved_rounds_warning`) test only the window, the streak, the model or the warning. Their one Always case ("the switch off and the `always` policy ignore the reports") was a property of the policy object. With no state left, it now holds by construction.
   - `…header_names_the_own_ring_block` (:2289): the kept half is unchanged except that `exec_policy == "always"` is dropped. It still checks own entry 112, the own ring's hash rather than 0xee, and `exec_block` 112, `exec_tip` 133, `exec_basis` quorum, now under `Parameters::default()`. The deleted `Header::new` byte rebuild belonged to the off half.
   - `…choice_table` (:2036): all 20 Always rows are kept with the same parents, block, tip and basis. Of the dropped rows, "starved" equals the kept row "ahead by six outputs" (`table_parents(1, 9, 139)` gives 139 Quorum), and Tip and Off are arms that no longer exist.
   - `…self_feeding_fleet` (:2197): the always half is intact (lag `min(r - 1, 8)`, Floor after round 9, lag exactly 8 from round 9). The whole-fleet half was adaptive only. It asserted that with all ten nodes in a Starved window over rounds 6-9 the lag climbs (`round - 5`, Starved, Quorum) and drops back to (0, Tip, Tip). The climb is the ratchet the always half asserts from round 1. The windowed half's lag of 1 next to fresh tips is the rule on parents one output behind, which the table covers ("ahead by one output", "three parents at the tip …").
   - `…faulty_high_parents…` (:2379): the `[Off, Tip]` loop asserted `choose == own_tip` for the gone arms. The kept contrast never used it: `votes(tip, honest) == 1` and the sweep's `votes(choice) >= votes(tip)` read `tip` directly, and both stay.
   - `…bound_holds…` and `…never_names…`: the `[Always, Starved]` loops collapsed to one pass with the same assertions.
   - `test_header_proposed_reports_own_parent_and_hold_fields` (:2988): the tail is 4 names instead of 5. Only `exec_policy` left the assertion.
4. **Does any comment, doc or log text still speak of the switch?** Not in `proposer.rs`. The words "switch" at :1147 and :1664 belong to `digest_order_hold` (R4). The remaining hits are in tests: L1 and L2 ("both forms") and L3 (`always`).

## Findings

### Low

- **L1** `crates/consensus/primary/src/tests/proposer_tests.rs:2315`: "The bound names the opening block instead, under both forms that apply the rule;". The loop over the two forms is gone. Change to "The bound names the opening block instead; a debug build stops …".
- **L2** `proposer_tests.rs:2444`: "The quorum rule in an epoch's first rounds, under both forms that apply it: the ring holds". Change to "The quorum rule in an epoch's first rounds: the ring holds".
- **L3** `proposer_tests.rs:2199-2208`: the local `let always = self_feeding_fleet(20);` and the messages `"always: round {round}, node {node}"` and `"always: round {round} sits on the floor"` still carry the old policy's name. Rename the local to `fleet` and drop the `always: ` prefix.

## Notes (not findings of this commit)

- At `a242a3b4a`, e2e `exec_block.rs` still asserts on `exec_policy=` values (:233, :260-272, :396), and every module still writes the two removed keys. The commit compiles (R3 gate `check -p e2e-tests` EXIT=0), but those runtime assertions fail until part B lands. Ship both commits together.
- `benchmark/tools/arms-summary.py:225,933` reads `exec_policy` with `f.get`, so it does not crash. A node built from `main` reports no value there, which is expected because the harness targets `bench/bench8-2026-11`.
- Older review and section labels in test comments (`I-4 item 1` :2190, `I-4 item 9` :2284, `Review item I1` :2310, `// ---- bench6 quorum-exec-block ----` :1946, `// ---- bench7 … ----` :2308) predate this commit and were not added by it. They are a candidate for a stack-wide sweep before `main`.

## Checked and fine

- `crates/config/src/node.rs`: both fields with their docs, both defaults and both `runtime_switches!` entries are removed. Nothing else changed, and no mention is left.
- `crates/consensus/primary/src/proposer.rs`: the field, the `new` doc and warning, the cancel and certified hooks, the two constants, `ExecPolicy`, `ExecBlockPolicy` and the log field are removed. The kept path is identical under `-w`. The docs of `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`, `ExecBasis::Tip` and `choose_exec_block` are in present tense.
- `crates/consensus/primary/src/tests/proposer_tests.rs`: 8 adaptive tests deleted. `exec_off` became `exec_no_parents` with the same block. Kept assertions are unchanged apart from the policy plumbing.
- `crates/consensus/primary/src/tests/network_tests.rs`: two doc comments (:7047, :7204) now say "the quorum rule" where they named the switch. Nothing else changed.
- Commit message: says what goes and what stays, `Refs #1804`, `Topic: remove-bench-switches` last, with no figure, no private label and no attribution.
