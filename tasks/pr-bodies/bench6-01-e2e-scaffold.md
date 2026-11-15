## Summary

Lets an e2e test give chosen nodes their own `parameters.yaml` entries and environment (`NodeOverrides`, `FleetOverrides`), and lets a test lane set fleet-wide entries through `TN_E2E_PARAMETERS`, so a switch can be tested on part of a fleet or across an existing test set without editing the tests.
The node log helpers of `restarts.rs` move to `common.rs`.
Test code only: no node crate changes, and there is no switch.
A test that passes no override, with the variable unset, starts its nodes as on main.

PR 2 of 6 into `staging/benchmark-bench6-2026-11` (merge order: 00, 01, 02, 03, 04, then `fix/epoch-loop-output-drop`).
Stacked on `feat/bench6-switches-obs`: this head contains its commits, so the Files tab shows them until that PR merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/b29d59bef7b46220aad81ddaeb48101f197a14b4...87be966514802e039b7f7ba87452bfc7e2e57f5d (8 commits).
Please merge with 'Create a merge commit' so the next PR's diff collapses.

## Problem

Bench 6 put each fix behind a switch whose default is main's behaviour, so its e2e tests need fleets where some nodes run a switch and others do not, and the existing restart, epoch and sigkill sets have to pass with each switch on.
On main at 33b727fce every node of an e2e fleet gets the same `parameters.yaml`, copied from the shared genesis directory (`crates/e2e-tests/src/lib.rs:356`, `:388`).
Only `start_validator_with_env` (`crates/e2e-tests/tests/it/common.rs:527`) takes extra environment, for one validator; `start_nodes` and the observer helpers take none.
The helpers that read and wait for node log lines are private to `restarts.rs` (`crates/e2e-tests/tests/it/restarts.rs:1368-1388`, `:2074`).

## Change

- `651a377a4` test(e2e): start chosen nodes with their own parameters and environment.
  `NodeOverrides` holds one node's extra `parameters.yaml` entries (key and one line of raw YAML) and environment variables; `FleetOverrides` assigns them across a fleet.
  The entries are merged into the node's file before it starts and checked with the node's `Parameters` loader.
  The existing helpers keep their signatures and delegate to the new `start_validator_with_overrides` and `start_nodes_with_overrides` with empty overrides.
- `eea10a5cc` test(e2e): move the node log helpers from restarts to common.
  `node_log_lines`, `plain_log_lines`, `log_line_matches`, `wait_for_node_log_line` and `log_field` (with its test) move as they are, now `pub(crate)`.
- `9dde3a026` test(e2e): key fleet overrides by datadir and rebuild parameters per start.
  Overrides keyed by position gave the wrong node's overrides to a restart of a subset; they are now keyed by datadir name (`validator-1`, …).
  The first start with entries keeps the harness's file as `parameters.yaml.harness-base`, and every start rebuilds `parameters.yaml` from it plus that start's entries, staged in `parameters.yaml.merging` and moved into place by `rename`.
- `f5095a920` test(e2e): fleet-wide parameters.yaml entries from TN_E2E_PARAMETERS.
  `TN_E2E_PARAMETERS='key: value; key: value'` is merged into every node a start helper starts, restarts and observers included, under the test's own overrides, so a test that sets the same key keeps its value.
  A malformed list or a value the loader refuses fails the start with an error naming the variable.
- `e64d31c74` test(e2e): close the gaps review found in the parameters override scaffold.
  The docs now name `gc_depth` beside `basefee_address` as a key that forks a fleet when only some nodes carry it, and say that a restart through a helper without overrides drops a node's entries and variables.
  A non-unicode `TN_E2E_PARAMETERS` now fails the start instead of being read lossily.
- `f4556ea25` test(e2e): apply every node's overrides before start_nodes_with_overrides spawns any.
  `FleetOverrides::apply_with_e2e_parameters` applies every node first, so a node that cannot take its overrides fails the call before any node is spawned and none is left running.
- `0b5248068` test(e2e): say when a start drops parameters.yaml entries of the previous start.
  The start is unchanged, but it prints one line on stderr and through `warn!`: `e2e: <datadir> starts without the parameters.yaml entries [...] of its previous start: …`.
  A test that never gives a node overrides never sees it.
- `87be96651` docs(e2e): say what TN_E2E_PARAMETERS is checked with and which nodes it reaches.
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

On main at 33b727fce, at `17327280d` (the tip of `fix/1804-vote-queue`, PR 3 of 6, which contains this head's eight commits): `cargo check --locked --workspace --all-targets`, warnings denied, which builds the e2e crate and its tests: clean.
The e2e library's unit tests were not run on today's main.

On the stack's earlier cut on main at 45dce8947 (the same eight commits before the move; main has not changed the three files they edit since), at the head's seventh commit (the eighth changes doc comments only):
- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.
- `cargo check --locked --all-targets -p e2e-tests -p tn-config -p tn-node`: passed.
- `cargo nextest run --locked --no-fail-fast -p e2e-tests --lib -p tn-config`: 160 passed.

The same commits on main at 45dce8947, before they were stacked: clippy over `e2e-tests` (all targets) clean, the 16 library tests and the doctest passed.
On the first five commits, `restarts::test_restarts_observer` and `common::test_log_field_reads_whole_fields` passed as e2e tests with the variable unset.

Not run: the rest of the e2e suite, and any lane with `TN_E2E_PARAMETERS` set.
No test in this PR calls `start_validator_with_overrides` or `start_nodes_with_overrides`; the first callers in the stack are the e2e tests of `fix/epoch-record-collector-hardening` (`epoch_record_walk.rs`), which start their fleets through the shared helpers that head adds.

Stack-wide gates: to be filled in when the gates on the top of the stack have finished.

## Limits and what a reviewer should look at

- A mistyped key passes silently: the node ignores unknown keys.
  A helper that waits for the key in the `node switches` line (from `feat/bench6-switches-obs`) would catch it for switch keys; it is not in this PR.
- A restart through a plain helper rebuilds the node's file without its own entries.
  The new line says so, but every existing restart test uses the plain helpers, so a test copied from one loses its switch at the restart.
- `TN_E2E_PARAMETERS` does not reach `test_epoch_observer_forwards_to_second_worker` (`epochs.rs`), which spawns its own nodes, nor the `db load-state` runs of `state_export_import.rs`, which use no `Parameters` field on main.
- A lane with the variable set also merges it into the `TN_BIN_PATH_PREV` nodes of `upgrade.rs`, `reth_db_migration.rs` and `resync.rs`.
  When that binary was built at another commit, as `upgrade.rs` requires, it ignores keys it does not know, so the test runs as a mixed fleet; the crate docs say so (`87be96651`).
- `parameters.yaml.harness-base` is written with a plain `fs::copy`; a cut-short copy fails that start, and no later start reads it.

## Related

No issue: test scaffolding for the stack.
Stacked on this: `fix/1804-vote-queue`, `fix/epoch-record-closing-block-check`, `fix/epoch-record-collector-hardening` and `fix/epoch-loop-output-drop`, and later `fix/1804-quorum-exec-block`, whose e2e test runs a mixed-switch fleet with `FleetOverrides`.
