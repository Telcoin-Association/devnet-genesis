## Summary

Lets an e2e test give chosen nodes their own `parameters.yaml` entries and environment (`NodeOverrides`, `FleetOverrides`), and lets a test lane set fleet-wide entries through `TN_E2E_PARAMETERS`, so a switch can be tested on part of a fleet or across an existing test set without editing the tests.
The node log helpers of `restarts.rs` move to `common.rs`.
Test code only: no node crate changes, and there is no switch.
A test that passes no override, with the variable unset, starts its nodes as on main.

PR 2 of 5 into `staging/benchmark-bench6-2026-11` (merge order: 00, 01, 02, 03, 04).
Stacked on `feat/bench6-switches-obs`: this head contains its commits, so the Files tab shows them until that PR merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/81a06c4e1...48dae6a5f (8 commits).
Please merge with 'Create a merge commit' so the next PR's diff collapses.

## Problem

Bench 6 put each fix behind a switch whose default is main's behaviour, so its e2e tests need fleets where some nodes run a switch and others do not, and the existing restart, epoch and sigkill sets have to pass with each switch on.
On main at 45dce8947 every node of an e2e fleet gets the same `parameters.yaml`, copied from the shared genesis directory (`crates/e2e-tests/src/lib.rs:356`, `:388`).
Only `start_validator_with_env` (`crates/e2e-tests/tests/it/common.rs:527`) takes extra environment, for one validator; `start_nodes` and the observer helpers take none.
The helpers that read and wait for node log lines are private to `restarts.rs` (`crates/e2e-tests/tests/it/restarts.rs:1368-1388`, `:2074`).

## Change

- `29cfa7895` test(e2e): start chosen nodes with their own parameters and environment.
  `NodeOverrides` holds one node's extra `parameters.yaml` entries (key and one line of raw YAML) and environment variables; `FleetOverrides` assigns them across a fleet.
  The entries are merged into the node's file before it starts and checked with the node's `Parameters` loader.
  The existing helpers keep their signatures and delegate to the new `start_validator_with_overrides` and `start_nodes_with_overrides` with empty overrides.
- `fca359747` test(e2e): move the node log helpers from restarts to common.
  `node_log_lines`, `plain_log_lines`, `log_line_matches`, `wait_for_node_log_line` and `log_field` (with its test) move as they are, now `pub(crate)`.
- `af8a065e7` test(e2e): key fleet overrides by datadir and rebuild parameters per start.
  Overrides keyed by position gave the wrong node's overrides to a restart of a subset; they are now keyed by datadir name (`validator-1`, …).
  The first start with entries keeps the harness's file as `parameters.yaml.harness-base`, and every start rebuilds `parameters.yaml` from it plus that start's entries, staged in `parameters.yaml.merging` and moved into place by `rename`.
- `72424b8c8` test(e2e): fleet-wide parameters.yaml entries from TN_E2E_PARAMETERS.
  `TN_E2E_PARAMETERS='key: value; key: value'` is merged into every node a start helper starts, restarts and observers included, under the test's own overrides, so a test that sets the same key keeps its value.
  A malformed list or a value the loader refuses fails the start with an error naming the variable.
- `fcdba0f3b` test(e2e): close the gaps review found in the parameters override scaffold.
  The docs now name `gc_depth` beside `basefee_address` as a key that forks a fleet when only some nodes carry it, and say that a restart through a helper without overrides drops a node's entries and variables.
  A non-unicode `TN_E2E_PARAMETERS` now fails the start instead of being read lossily.
- `e9ecfe49d` test(e2e): apply every node's overrides before start_nodes_with_overrides spawns any.
  `FleetOverrides::apply_with_e2e_parameters` applies every node first, so a node that cannot take its overrides fails the call before any node is spawned and none is left running.
- `6ea3dec7b` test(e2e): say when a start drops parameters.yaml entries of the previous start.
  The start is unchanged, but it prints one line on stderr and through `warn!`: `e2e: <datadir> starts without the parameters.yaml entries [...] of its previous start: …`.
  A test that never gives a node overrides never sees it.
- `48dae6a5f` docs(e2e): say what TN_E2E_PARAMETERS is checked with and which nodes it reaches.
  Doc comments only: the merge is checked with the `Parameters` of the tree under test, not by the binary that will read the file, and the entries also reach the `TN_BIN_PATH_PREV` nodes that `upgrade.rs`, `reth_db_migration.rs` and `resync.rs` start.

## What changes for every node

Nothing in the node binary or any node crate.
For e2e tests that pass no override, with `TN_E2E_PARAMETERS` unset, the `parameters.yaml` bytes, the arguments and the environment are main's; the one new step is an `exists()` check for `parameters.yaml.harness-base` per start.
The variable is read once per test process and prints nothing when it holds no entries.
The moved log helpers are byte-identical apart from `pub(crate)` and the imports, and no Makefile, nextest or workflow filter selected the moved test, `test_log_field_reads_whole_fields`, by its old `restarts::` path.

Mixed fleet: not applicable to the node, since no message, header, vote, certificate or batch is touched.
The scaffold builds mixed fleets on purpose, and its docs warn that a key that changes what the chain computes, given to only some nodes, forks the test fleet.

## Testing

Among the e2e library's 16 unit tests, `merge_later_entry_wins_and_is_idempotent`, `apply_parameters_reaches_the_node_loader`, `apply_parameters_starts_each_run_from_the_harness_file`, `fleet_apply_fails_on_the_node_that_cannot_take_its_overrides` and `dropped_entries_notice_names_the_datadir_and_the_dropped_keys` pin the claims above.

On `6ea3dec7b`, the head before its last commit (which changes doc comments only):
- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.
- `cargo check --locked --all-targets -p e2e-tests -p tn-config -p tn-node`: passed.
- `cargo nextest run --locked --no-fail-fast -p e2e-tests --lib -p tn-config`: 160 passed.

The same commits on main, before they were stacked: clippy over `e2e-tests` (all targets) clean, the 16 library tests and the doctest passed.
On the first five commits, `restarts::test_restarts_observer` and `common::test_log_field_reads_whole_fields` passed as e2e tests with the variable unset.

Not run: the rest of the e2e suite, and any lane with `TN_E2E_PARAMETERS` set.
No test in this PR calls `start_validator_with_overrides` or `start_nodes_with_overrides`; the first callers in the stack are the e2e tests of `fix/epoch-record-collector-hardening` (`epoch_record_walk.rs`), which start their fleets through the shared helpers that head adds.

Stack-wide gates ran before these PRs were opened, on the full stack: `bench/bench7-2026-11` at `91a15e223` carries the code of these five heads, of the epoch-loop fix (#1860) and of two later heads not sent yet (`fix/1804-quorum-exec-block`, `fix/1807-digest-order-hold`).
- `./etc/ci-lanes.sh clippy`: passed.
- `cargo nextest run --locked --workspace`: 5,531 of 5,532 passed.
  The one failure, `tests::differential::random_scripts_match_mdbx_multi_leaf` in `tn-lmdb-reth`, is a randomized test of a crate this stack does not touch; it passed ten of ten re-runs.
- Those two ran three commits below `91a15e223`, on a tree that differs only in e2e test files; the e2e crate's check and clippy passed at `91a15e223`.
- `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12, once with every switch off and once with the full stack's seven switches on.
- The 13 e2e tests the full stack adds, three runs each: all passed.

The PR heads differ from `91a15e223` in commit messages and in how the e2e test files are split.
Outside `crates/e2e-tests/tests/it` the top head's tree is identical to it; on the final split the 13 tests passed once, and `cargo +nightly-2026-03-20 fmt --all -- --check` is clean.

## Limits and what a reviewer should look at

- A mistyped key passes silently: the node ignores unknown keys.
  A helper that waits for the key in the `node switches` line (from `feat/bench6-switches-obs`) would catch it for switch keys; it is not in this PR.
- A restart through a plain helper rebuilds the node's file without its own entries.
  The new line says so, but every existing restart test uses the plain helpers, so a test copied from one loses its switch at the restart.
- `TN_E2E_PARAMETERS` does not reach `test_epoch_observer_forwards_to_second_worker` (`epochs.rs`), which spawns its own nodes, nor the `db load-state` runs of `state_export_import.rs`, which use no `Parameters` field on main.
- A lane with the variable set also merges it into the `TN_BIN_PATH_PREV` nodes of `upgrade.rs`, `reth_db_migration.rs` and `resync.rs`.
  When that binary was built at another commit, as `upgrade.rs` requires, it ignores keys it does not know, so the test runs as a mixed fleet; the crate docs say so (`48dae6a5f`).
- `parameters.yaml.harness-base` is written with a plain `fs::copy`; a cut-short copy fails that start, and no later start reads it.

## Related

No issue: test scaffolding for the stack.
Stacked on this: `fix/1804-vote-queue`, `fix/epoch-record-closing-block-check` and `fix/epoch-record-collector-hardening`, and later `fix/1804-quorum-exec-block`, whose e2e test runs a mixed-switch fleet with `FleetOverrides`.
