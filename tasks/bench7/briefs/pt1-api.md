# PT-1 e2e scaffold: the surface later e2e units use

Branch `b7/pt1` (on M 45dce8947), topic `bench6-e2e-scaffold`.
Library items live in `crates/e2e-tests/src/lib.rs` (`use e2e_tests::{...}`); start helpers and log helpers live in `tests/it/common.rs` (`use crate::common::{...}`).

## Library (`e2e_tests`)
- `NodeOverrides { pub parameters: Vec<(String, String)>, pub env: Vec<(String, String)> }`, `Default`, `Clone`, `Eq`: one node's extra `parameters.yaml` entries (key, raw one-line YAML) and process environment.
  - `.parameter(key, value) -> Self`, `.env(name, value) -> Self`, `.is_empty() -> bool`; a later entry for the same key or name wins.
  - `.apply_parameters(&self, node_dir: &Path) -> eyre::Result<()>`: writes `parameters.yaml` = the harness's file plus these entries, keeps the harness's file as `parameters.yaml.harness-base`, stages in `parameters.yaml.merging` and checks it with the node's own `Parameters` loader before the move; no entries restores the harness's file (or touches nothing).
  - `.layered_over(&self, fleet_wide: &[(String, String)]) -> NodeOverrides`: fleet-wide entries first, the node's own last (the node's value wins).
  - `.apply_with_e2e_parameters(&self, node_dir: &Path) -> eyre::Result<()>`: `apply_parameters` with `TN_E2E_PARAMETERS` layered underneath; every start helper calls this.
- `FleetOverrides` (`Default`, `Clone`, `Eq`), keyed by datadir name (`"validator-1"` … for `instance` helpers, the names in the `validators` slice for `start_nodes*`):
  - `.parameter(nodes: impl IntoIterator<Item = impl Into<String>>, key, value) -> Self`, `.env(nodes, name, value) -> Self`, `.set_node(node: impl Into<String>, NodeOverrides) -> Self`, `.node(&self, node: &str) -> &NodeOverrides` (empty when unset).
- `merge_parameters_yaml(base: &str, overrides: &[(String, String)]) -> eyre::Result<String>`: pure text merge; key = `[A-Za-z0-9_]+` at column 0, value = one non-empty line; replaces an existing top-level entry (block value included) and appends `key: value`; idempotent.
- `E2E_PARAMETERS_VAR: &str = "TN_E2E_PARAMETERS"`; `e2e_parameters() -> eyre::Result<&'static [(String, String)]>` (read once per process, printed once); `parse_e2e_parameters(raw: &str) -> eyre::Result<Vec<(String, String)>>`.

## `TN_E2E_PARAMETERS` grammar
- `TN_E2E_PARAMETERS='key: value; key: value'`: entries split on `;`, each split at its first `:`, key and value trimmed, empty entries skipped, unset or blank = no entries.
- A value cannot hold `;`; it may hold `:` and spaces (`nested: {x: 1}`).
- Merged into every node a start helper starts (validators, restarts, observers, `spawn_local_testnet`), before the test's own `FleetOverrides`.
- A malformed or non-unicode value, or a merged file the node's loader refuses, fails the start with an error naming the variable.
- Restarting a node through a helper that takes no fleet drops its own entries and variables (the fleet-wide ones stay); restart a node whose overrides matter with the same fleet.
- Not covered: nodes a test spawns with its own `bin.command()` (`epochs.rs` `test_epoch_observer_forwards_to_second_worker`) and the `db` subcommands.

## Start helpers (`tests/it/common.rs`, `pub(crate)`)
- `start_validator_with_overrides(instance, bin, base_dir, rpc_port, test, run, extra_args: &[&str], fleet: &FleetOverrides) -> eyre::Result<Child>`.
- `start_nodes_with_overrides(temp_path, validators: &[(&str, Address)], test, run, fleet: &FleetOverrides) -> eyre::Result<(Vec<Child>, Vec<NodeEndpoints>)>`.
- M's `start_validator`, `start_validator_with_args`, `start_validator_with_env`, `start_observer*`, `start_named_observer`, `start_nodes` keep their signatures; with no fleet entries and the variable unset they start nodes exactly as on M.

## Log helpers (moved from `restarts.rs` to `common.rs`, `pub(crate)`)
- `node_log_lines(test, instance, run) -> eyre::Result<Vec<String>>`, `plain_log_lines(path: &Path) -> eyre::Result<Vec<String>>` (ANSI stripped, lossy).
- `log_line_matches(line, text, fields: &[String]) -> bool` (`name=value` whole tokens), `log_field(line, name) -> Option<u64>`.
- `async wait_for_node_log_line(test, instance, run, text, fields: &[String], timeout: Duration) -> eyre::Result<()>`.

A key the node does not know is ignored by the node, so assert the setting in the node itself (a log line or metric), not in the merged file.
