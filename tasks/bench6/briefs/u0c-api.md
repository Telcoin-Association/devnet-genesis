# What unit U0c (plumbing) landed — the names later node units use

Integrated on `bench/bench6-2026-11` as 12 commits ending at 7cfe52acd (2026-11-11). Read the code for the docs; these are the
signatures from U0c's hand-back. With every switch at its default nothing here changes behaviour.

## The switch line and gauge (harness contract; do not change)
- `EpochManager::new` logs once, after `parameters.yaml` is loaded: message `node switches`, level info, `target: "node::switches"`,
  one field per switch in the order of `Parameters::switches()`. Rendered with defaults:
  `node switches quorum_exec_block=false quorum_exec_block_starved_rounds=0 vote_queue_fix=false mdbx_random_advice=false sealed_tx_keep=false digest_dedupe=false recovery_threads=0 epoch_close_task_drain=false epoch_record_state_check=false parent_grace=0s rpc_admission_backlog_outputs=0 pipelined_persist=false`
- Gauge `tn_node_switch{name="<yaml key>"}` = `SwitchValue::gauge()` (bool 0/1, counts as is, durations in milliseconds).

## tn-reth (`crates/tn-reth/src/env/mod.rs`)
- `pub struct RethSwitches { pub mdbx_random_advice: bool, pub sealed_tx_keep: bool, pub rpc_admission_backlog_outputs: usize, pub execution_backlog: tn_types::ExecutionBacklog }` (`Clone, Debug, Default`).
- `RethEnv::new_with_switches(reth_config, task_manager, database, basefee_address, gas_accumulator, switches: RethSwitches) -> eyre::Result<Self>`;
  `RethEnv::new` delegates to it with the defaults. Today it only STORES the switches: the unit that owns a switch acts on it.
- Getters on `RethEnv`: `mdbx_random_advice() -> bool`, `sealed_tx_keep() -> bool`, `rpc_admission_backlog_outputs() -> usize`,
  `execution_backlog() -> &ExecutionBacklog`.
- `crates/tn-reth/src/env/execution.rs`: `pub fn OutputBuildScope::seeded(overlay: OutputTrieOverlay, tip: B256) -> Self` (its docs
  state what the caller vouches for).

## tn-engine (`ExecutorEngine`, `crates/engine/src/lib.rs`)
- `with_recovery_threads(self, threads: u16) -> Self`, `recovery_threads(&self) -> u16`.
- `with_execution_backlog(self, backlog: ExecutionBacklog) -> Self`, `execution_backlog(&self) -> &ExecutionBacklog`; `new()` starts
  on `reth_env.execution_backlog().clone()`. The engine already calls `record_queued(queued + executing)` beside both
  `queued_outputs.set` calls and `record_executed(consensus_number)` for every finished output, empty ones included.
- `with_pipelined_persist(self, pipelined: bool) -> Self`, `pipelined_persist(&self) -> bool`.
- `pub mod persister;` — an empty module with docs only (`crates/engine/src/persister.rs`).
- `crates/engine/Cargo.toml`: `rayon` (dependency), `proptest` (dev-dependency), `[[bench]] name = "engine_contention"`,
  `harness = false`, with a stub `crates/engine/benches/engine_contention.rs`. **Criterion is not a dependency of this workspace and
  is not to be added**: the repo's one existing bench (`crates/tn-reth/benches/output_overlay.rs`) is a plain `harness = false`
  binary with a hand-written `main`; follow it.

## tn-batch-builder (`BatchBuilder`, `crates/batch-builder/src/lib.rs`)
- `with_sealed_tx_keep(self, keep: bool) -> Self`, `sealed_tx_keep(&self) -> bool`; `new()` starts from `reth_env.sealed_tx_keep()`.

## tn-node
- `EpochManager` has the field `execution_backlog: ExecutionBacklog` (created once in `new()`, shared with the reth env and the
  engine). The unit that forwards outputs records `self.execution_backlog.record_forwarded(n)` in `run_epoch.rs` after the send
  to the engine has succeeded.
- `run_epoch.rs` and `close_epoch.rs` are `impl EpochManager` blocks and read `self.builder.tn_config.parameters` directly
  (`epoch_close_task_drain`, `epoch_record_state_check`): no plumbing was needed.
- `crates/node/src/engine/inner.rs`: `configure_engine(ExecutorEngine, &Parameters, &ExecutionBacklog)` and
  `configure_batch_builder(BatchBuilder, &Parameters)` apply the setters in `start_engine` / `start_batch_builder`.
- The proposer, the vote handler and the worker read `Parameters` through their config (`parameters()`).

## Known rough edges (not yours to fix unless your brief says so)
- A duration of one second or more with a millisecond remainder renders with a space (`1s 500ms`), which would break `key=value`
  parsing of the switch line; the bench only uses `150ms` and `100ms`.
- Until each fix lands, the switch line and gauges report switches that do nothing yet.
