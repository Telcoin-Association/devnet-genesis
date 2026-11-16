# RV-5: review of R5 (the switch machinery goes)

Commits in `/home/drtnarg/coding/telcoin/tn-b8-uc`, branch `refactor/remove-bench-switches`, base `726a25f1b`:

- `1d41981dd` test(e2e): stop checking the node switches line
- `e8dfcce10` refactor(node): drop the node switches log line and gauge
- `57a55b221` refactor(config): remove the runtime switch list

9 files, +38 / −748. Line numbers below are at the tip `57a55b221` unless marked otherwise.

## Verdict

**Approve with follow-ups.** Critical 0, High 0, Medium 0, Low 2. Both Lows are wording or reporting fixes. Neither blocks the merge.

## The four questions of the rules file

1. **Is any of the machinery left?** No. The required grep (`node switches|tn_node_switch|runtime_switches|SwitchValue|STACK_SWITCHES|assert_switches|expected_switches|log_switches` over `crates docs`) returns two hits, both unrelated prose about epoch directories: `crates/storage/src/consensus.rs:1222` and `crates/telcoin-network-cli/src/db.rs:1944` ("…before the node switches to it"). An extra grep for `switch_at_default|record_node_switches|NODE_SWITCH|stack_overrides|runtime switch` returns nothing. The six switch names over `crates docs etc chain-configs` return only `crates/e2e-tests/tests/it/main.rs:9 mod digest_order_hold;`, which is the module's file name.
2. **Did a statement on a kept path change?** No.
   - Config: the diff only deletes code, apart from two doc comments it rewrites (`:1239-1240`, `:1272`).
   - Node: 4 lines go from `Node::new` (`manager/node.rs`, base `:774-777`): a comment, `let parameters = &builder.tn_config.parameters;`, `parameters.log_switches();` and `crate::metrics::record_node_switches(&parameters.switches());`. The only other `parameters` read in that function is `builder.tn_config.parameters.gc_depth`, which goes through `builder` and not the removed binding (e8dfcce10 ~`:813`).
   - e2e: `Form::overrides` now folds only `PRODUCTION_CADENCE` (`digest_order_hold.rs:247-249`), and `stack_overrides()` becomes `FleetOverrides::default()` (`epoch_close_forms.rs:289`, `:440`). Both are equivalent to the old code because `STACK_SWITCHES_ON` was `[(&str, &str); 0] = []` at the base, so no fleet gets different parameters.
3. **Was a test of kept behaviour deleted or weakened?** No; see B. Config tests went from 37 at the base to 29 at the tip (upstream main has 27). Exactly the 8 named switch tests went.
4. **Does any comment, doc or log text still speak of the switch?** Only the e2e scaffold docs in `crates/e2e-tests/src/lib.rs` (L1). Test data keys (`no_such_switch`, `example_switch`, `unknown_switch`) are not prose and are fine.

## A. `crates/config/src/node.rs` (57a55b221, +3 / −480): only machinery went. PASS

The deleted lines are:
- the marker comments in `struct Parameters` and in `Default for Parameters`;
- `Parameters::switch_at_default`, the `runtime_switches!` macro (which generated `switches()` and `log_switches()`) and its empty invocation;
- `SwitchValue` with `gauge()`, `Display` and the `From` impls for bool, u16, u32, u64, usize and Duration;
- in tests: `NON_SWITCH_KEYS`, `yaml_scalar`, `every_switch_flipped`, the `FieldNames` deserializer, the `LineCapture` subscriber, the 8 tests, and the switch loop in `reserializing_keeps_the_existing_keys`.

No field, default, validation or serde attribute is among the deleted lines, and neither is any non-switch test. `Duration` is still used by 7 fields.

Field comparison, `pub <name>:` inside `struct Parameters`:
- **Fields:** upstream main `0554efd4f`, base and tip each have the same 14 fields. Main has none the tip lacks, and the tip has none main lacks.
- **Defaults:** before `mod test`, the tip's `node.rs` differs from main only in the `vote_timeout` doc comment (tip `:310-312`, from another PR in the stack). `impl Default for Parameters` and every `default_*` function are identical to main.

## B. Deleted config tests: nothing that matters is left untested. PASS

- `absent_switch_keys_load_the_defaults` (base) compared only `parse_with("").switches()` with `Parameters::default().switches()`. With the list empty, that compared two empty vectors and tested nothing. It never checked a non-switch field. The fields at the tip are exactly main's, so no "newer key" is left whose absence needs a test. Absent keys still parse:
  - `reserializing_keeps_the_existing_keys` (`:1245`) parses a bench-5 file holding 9 of the 14 keys;
  - `absent_vote_timeout_key_defaults_to_five_seconds` (`:967`) pins one default.
  - No test compares `parse_with("")` with `Parameters::default()` across all fields, but none did on main either, and the deleted test did not.
- `chain_presets_leave_every_switch_at_its_default` parsed `MAINNET_PARAMETERS` and `TESTNET_PARAMETERS`. Both still parse in two tests:
  - `shipped_chain_presets_pin_their_basefee_address` (`:1011`, "mainnet parameters parse" / "adiri parameters parse", plus `validate_operational_floors`);
  - `reserializing_keeps_the_existing_keys` (`:1245`, which loops over bench5, MAINNET and TESTNET).
- `reserializing_keeps_the_existing_keys` still asserts three things for each of the three files: every input key is in the output with the same value (strings compared case-insensitively), the output parses, and the reparsed `Parameters` equals the parsed one. Only the "no switch key added" loop went, and with no switch fields it had nothing to check.
- `unknown_keys_are_ignored` (`:1274`) asserts `parse_with("no_such_switch: true\nanother_unknown: 3ms") == parse_with("")`. A file that names an unknown key, a removed one included, loads and equals the same file without it. That is exactly the property the PR text relies on. The test does not use one of the six real names. Using one would bring a removed name back into the F2 grep, so the current form is the better choice.

## C. `crates/node/src/metrics.rs` (−60 / +1) and `manager/node.rs` (−4): PASS

- **What went:** `use tn_config::SwitchValue`, `NODE_SWITCH_GAUGE = "tn_node_switch"` with its doc, `record_node_switches` with its doc, `test_node_switch_gauge_per_switch` with its marker comment, and the "and runtime switches" tail of the module doc.
- **Imports:** `DebuggingRecorder` and `DebugValue` are still used by the tests that remain (`:85`, `:89`, `:117-141`).
- **Metrics at base and tip:** the same 8 remain, `tn_epoch.{current, boundary_timestamp_seconds, replayed_outputs_total, final_state_mismatches_total, runs_total, provider_fault_retries_total, epoch_record_closing_block_check_total, epoch_close_identity_check_total}`. Only `tn_node_switch{name}` is gone.
- **`manager/node.rs`:** `parameters` had no other use in `Node::new`; see question 2.

## D. e2e: no start-up wait lost at any of the nine call sites. PASS (one Low)

The writer said the harness creates each run's log file before the process starts. That is true: `setup_log_dir` calls `File::create(test_dir/node{i}-run{r}.log)` (`crates/e2e-tests/src/lib.rs:~1050`). At every site, the next thing the test does tolerates a node that is not up yet:

| Call site | What follows the removed call |
|---|---|
| `digest_order_hold.rs` `drive` (`:270`) | `network_advancing(&fleet.urls)` already ran before it (RPC poll on all 4); then clients and load |
| `digest_order_hold.rs` `kill_and_restart` (`:416-422`) | `get_block_number(&url)` reads FUNDER (1), not HOOKED (0), so it is not the restarted node; then `wait_until_blocking(180 s, get_block_number(HOOKED).is_ok_and(..))` |
| `epoch_close_forms.rs` `check_held_member` run 0 (`:313`) | `network_advancing` came before; then `epoch_snapshot(&urls[0])` |
| `epoch_close_forms.rs` HELD_MEMBER restart (`:362-368`) | `get_block_number(&urls[0])` reads node 0 (HELD_MEMBER = 3); then `wait_until_blocking(CATCH_UP_TIMEOUT, get_block_number(urls[3]).is_ok_and(..))` |
| `epoch_close_forms.rs` `check_missed_round` run 0 (`:465`) | `network_advancing`, then `Load::start(..).wait_started()` |
| `epoch_close_forms.rs` ROUND_HELD restarts (`:512-515`) | a 1 s poll loop with `node_epoch(url).ok()` and `certified_record(..).is_ok()`, which tolerates a node that is down (see L2) |
| `epoch_record_walk.rs` validators and OWN_OBSERVER run 0 (`:291-302`) | `network_advancing`, `load.wait_started()`, then `wait_for_log_line(OWN_OBSERVER, 0, PUBLISHED_LOG, 6 epochs + 60 s)` |
| `epoch_record_walk.rs` OWN_OBSERVER run 1 and FRESH_OBSERVER run 0 (`:368-372`) | Walk arm: `fetch_record(own_url, e, left)` (a verified fetch with a time limit), `wait_for_log_line(.., left)`, `assert_serves_record_before_gap(fresh, window_end)`. Only after that, and after `sleep_until(window_end)`, does `assert_holds_none` run, so both observers have already proved they serve RPC and that check cannot pass vacuously. Recertify arm: `fetch_record(url, epoch, left)` for both. |
| `exec_block.rs` `measure_fast_executor` (`:150`) | `network_advancing`, then `Load::start(..).wait_started()` |

No site has a one-shot read that could now fail or pass vacuously: no metrics scrape, no `assert_no_log`, no immediate log read. `FATAL_LOGS` and the canary checks run at the end of each run.

## E. The #1863 scaffold

It is still used with non-empty overrides:
- `digest_order_hold.rs:238-249`: hook env `HOOK_MS_ENV`, `HOOK_STAGE_ENV` and `HOOK_EVERY_ENV` on HOOKED, `EXECUTION_DELAY_ENV` on SLOWED, and the `PRODUCTION_CADENCE` parameters on all validators. It is used by 3 tests.
- `epoch_close_forms.rs:290` (`EXECUTION_DELAY_ENV` on the held member) and `:444-445` (`EXECUTION_DELAY_ENV` and `EXIT_BEFORE_EPOCH_RECORD_ENV` on ROUND_HELD).
- `epoch_record_walk.rs:154`: `WITHHOLD_EPOCH_ENV` and more.
- `exec_block.rs:84-91`: env plus the `PRODUCTION_CADENCE` parameters.
- `common.rs:541-542`, `:580`, `:780` and `:1282`: helpers that set `TN_BLS_PASSPHRASE` and other env.

No test under `tests/it` sets `TN_E2E_PARAMETERS`. It appears only in `lib.rs`: its docs, `E2E_PARAMETERS_VAR` (`:844`) and the unit tests.

The `lib.rs` docs still describe the scaffold in terms of a switch (L1).

## F. Residual greps: PASS

Results as in question 1. `git grep -i switch` over the touched files finds only the test data key at `config/src/node.rs:1275` and unrelated prose (`epochs.rs:108` "as epochs switch", `state_export_import.rs:824` "Switching").

## G. Commit order: PASS (by reading)

- **After `1d41981dd`:** outside the config crate, only `crates/node/src/manager/node.rs:776-777` uses the machinery (`log_switches`, `record_node_switches`, `.switches()`). `e8dfcce10` removes those calls, and the config machinery still exists at `1d41981dd`. Nothing in e2e uses it.
- **After `e8dfcce10`:** nothing outside `crates/config/src/node.rs` names `SwitchValue`, `.switches()`, `log_switches`, `switch_at_default`, `record_node_switches` or `NODE_SWITCH_GAUGE`. `tn_config`'s `lib.rs` names none of them either; the export is a glob.

Each commit therefore compiles alone as far as references go. I ran no cargo command.

## Commit messages

All three end with `Topic: remove-bench-switches`. None has a bench figure, a private label or an attribution line.

## Findings

### Low

- **L1. The scaffold docs still speak of a node switch** (`crates/e2e-tests/src/lib.rs`). A closing unit should reword these to "a parameter" or "a setting":
  - `:9`: "existing test set with a node switch on without editing a test:"
  - `:12`: the example `TN_E2E_PARAMETERS='example_switch: true; other_switch: 4'`
  - `:442`: "can name a switch whether or not the node under test reads it."
  - `:610`: "// validators 1 and 2 (instances 0 and 1) run with the switch, 3 and 4 without it", with `"example_switch"` at `:613`
  - `:1284`: unit-test doc "switch and a typed override, and the node's loader reads the typed value back."
  - The `example_switch`, `other_switch` and `unknown_switch` keys in the unit tests (`:1227-1541`) are test data and can stay.
- **L2. The missed-round release timer now starts before the restarted nodes are up** (`crates/e2e-tests/tests/it/epoch_close_forms.rs:512-519`).
  - `released_at` and the `ROUND_SECOND_CLOSE_TIMEOUT` deadline used to start after both restarted nodes had logged their start-up line. They now start right after the two spawns.
  - So "epoch N closed X s after the release" in the summary (`:578-582`) and `after_release` in the failure message (`:1031`) now include process start-up time, a few seconds. The deadline is tighter by the same amount.
  - Neither figure has a threshold, and `ROUND_SECOND_CLOSE_TIMEOUT` is 4 epochs, so a flake is unlikely.
  - Fix: either accept it and say in the summary that the time counts from the restart, or wait for each restarted node's RPC (`get_block_number` poll) before taking `released_at`.

### Informational (not counted)

- `unknown_keys_are_ignored` uses `no_such_switch` as test data. It is harmless, and better than a real removed name (see B).
- No config test checks that the serde defaults equal `Parameters::default()` for every field. Upstream main has no such test either, and the deleted test never did it. A possible later test: `assert_eq!(parse_with(""), Parameters { basefee_address: GOVERNANCE_SAFE_ADDRESS, ..Parameters::default() })`.
