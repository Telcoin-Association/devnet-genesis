# U0c — plumbing (node unit, wave 0b)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u0c` (branch `b6/u-u0c`, cut from the integration branch AFTER unit U0a's switch commits:
`crates/config/src/node.rs` now has the twelve switch fields and `Parameters::switches()`, `crates/types/src/execution_backlog.rs`
has `ExecutionBacklog`; read both first). Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u0c.md`.
Skills: `tn-rust-skills`, `tn-domain-epoch`, `tn-domain-execution`, `tn-domain-worker`.

## Why
Eight fixes land behind switches in `parameters.yaml`. Ten later units each implement one fix in files they own. You are the only
unit that touches the constructors and wiring between crates, so that no later unit has to edit a file outside its own row. You
also make the switch state visible: one log line and one gauge per switch, which the benchmark harness reads back after every
restart to prove a node really runs the arm it was given.

## You own (nothing else)
`crates/node/src/manager/node.rs`, `crates/node/src/metrics.rs` (the node metrics file; find its real path), `crates/node/src/engine/inner.rs`,
the constructor/setter plumbing ONLY in `crates/engine/src/lib.rs` and `crates/batch-builder/src/lib.rs`, `crates/engine/Cargo.toml`,
a new stub `crates/engine/src/persister.rs` with its module line, one constructor in `crates/tn-reth/src/env/execution.rs`, and the
minimal signature change in `crates/tn-reth/src/env/mod.rs` that hands the reth-side switches to `RethEnv` (keep it to the
constructor path; unit U3 owns the rest of that file right after you). `crates/consensus/primary/src/consensus_bus.rs` is edited by nobody.

## Deliver (one commit per item, each compiling alone; footer `Topic:` as given)
1. **The switch line and gauge** (`Topic: bench6-switches`). At node start, AFTER `parameters.yaml` is loaded, log exactly once:
   message `node switches`, level info, `target: "node::switches"`, one field per switch named exactly as its YAML key, in the order
   of `Parameters::switches()`, values as YAML scalars (`true`/`false`, integers, durations like `150ms` and `0ms`). And export the
   gauge `tn_node_switch{name="<yaml key>"}` with the value from the enumeration's numeric form (bool 0/1, counts as is, durations in
   milliseconds — say which in the doc). The harness parses `key=value` tokens after the message text, so the rendering through the
   node's log formatter must produce `quorum_exec_block=false` style tokens: check how the node's tracing output renders fields
   (file logs and stdout) and add a test that captures the line and asserts the exact token list.
2. **Every switch readable where its unit needs it**, with one small test per component proving the value set in `Parameters`
   arrives there. First check which components already see `Parameters` (the proposer, the vote handler and the worker read it
   through the consensus/worker config; the node manager has `tn_config.parameters`): for those add nothing. Wire the rest:
   | switch | consumer (unit) | must be readable in |
   |---|---|---|
   | `mdbx_random_advice` | U3 | the reth environment right after `new_database` (`crates/tn-reth/src/env/mod.rs`) |
   | `recovery_threads` | U4a | `ExecutorEngine` (`crates/engine/src/lib.rs`), for `crates/engine/src/recovery.rs` |
   | `sealed_tx_keep` | U6a, U6b | the transaction pool side in tn-reth, and `BatchBuilder` (`crates/batch-builder/src/lib.rs`) |
   | `rpc_admission_backlog_outputs` + an `ExecutionBacklog` handle | U11 | the RPC submission guard (`crates/tn-reth/src/rpc_fee_cap.rs` is installed from `env/rpc.rs`: make the value and the handle available on `RethEnv` so U11 only edits its own two files and `run_epoch.rs`) |
   | `pipelined_persist` | U12a, U12b | `ExecutorEngine` |
   | `epoch_close_task_drain`, `epoch_record_state_check` | U5 | `run_epoch.rs` / `close_epoch.rs` (verify they can read `parameters`; add nothing if so) |
   Use builder-style setters or one small config struct per crate (follow the crate's existing style; no new dependencies between
   crates beyond what exists). Stored values must not trip `dead_code` under `-D warnings` and you may not add lint suppressions:
   give each a documented getter that your test uses. Commits: one per topic slug (`mdbx-advice`, `recovery-pool`, `sealed-keep`,
   `inflight-bound`, `pipelined-persist`), so each topic's cherry-pick index contains its own plumbing.
3. **The backlog write** (`Topic: inflight-bound`): in the engine, beside the existing queued-outputs gauge update(s) in
   `crates/engine/src/lib.rs`, record the queued count and the last finished output into the `ExecutionBacklog` handle (U0a's API).
   One `ExecutionBacklog` per node, created in the node manager and shared with the engine and the reth environment. With the
   admission switch at 0 nothing reads it.
4. **Engine crate scaffolding** (`Topic: pipelined-persist` for the persister stub; `Topic: recovery-pool` for the bench scaffolding):
   `crates/engine/Cargo.toml` gains what later units need and may not add themselves — `rayon` (dependency, for U4a's dedicated
   pool), `criterion` and `proptest` (dev-dependencies), and a `[[bench]] name = "engine_contention"`, `harness = false` entry with a
   minimal `crates/engine/benches/engine_contention.rs` that compiles (unit U4b fills it). Use the workspace's versions (check the
   root `Cargo.toml` `[workspace.dependencies]`; if one is not there, stop and report rather than adding a workspace dependency).
   Stub `crates/engine/src/persister.rs` with a module doc only and `pub mod persister;` in `lib.rs` (it must be `pub`: an
   integration test in `crates/engine/tests/` will name types from it).
5. **`OutputBuildScope::seeded`** (`Topic: pipelined-persist`): in `crates/tn-reth/src/env/execution.rs`, a ~15-line constructor
   that builds an `OutputBuildScope` from an existing overlay and tip, exactly as specified in
   `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-5/open-questions.md` item O1 and
   `…/I-5/design.md` §5.1-§5.2 (read those two parts; the type has private fields and the unit that needs to seed it does not own
   this file). Add the unit test the design names for it, or a round-trip test if it names none.

## What U0a landed (use it as is; do not edit its files)
- `tn_config::Parameters::switches(&self) -> Vec<(&'static str, SwitchValue)>` in the contract's order; `SwitchValue::{Bool, Count, Duration}`,
  `Display` = the YAML form (`true`, `3`, `150ms`; a zero duration prints `0s`), `SwitchValue::gauge() -> f64` (bool 0/1, count as is,
  duration in milliseconds). Log each field with `value.to_string()` and set the gauge from `gauge()`.
- A switch at its default is not written to `parameters.yaml` (`skip_serializing_if`), so a node's file usually lacks the keys; the
  log line still lists every switch with its effective value.
- `tn_types::ExecutionBacklog` (`record_forwarded`, `record_executed`, `record_queued`, `outputs_behind`, …) and `AdmissionGate`
  (`new(backlog, limit)`, `admits()`, `open_after`). The engine calls `record_executed` for EVERY finished output, empty ones
  included, and `record_queued` beside the queued-outputs gauge. `record_forwarded` is another unit's (U11, in `run_epoch.rs`).
- Known build quirk: `cargo nextest run -p tn-config` alone does not compile (`tn-network-types` needs a serde feature that only
  appears with tn-reth in the graph; pre-existing). Keep `-p tn-node` in the graph and filter with `-E 'package(<crate>)'`.

## Constraints
With every switch at its default the node behaves exactly as the base: you add a log line, gauges, setters and stubs, no behaviour.
`Cargo.lock` changes only by what the new engine dependencies need (use `--locked` everywhere else; say exactly what changed).

## Gates
As in the rules for the packages you touched (tn-node, tn-engine, tn-batch-builder, tn-reth: take the real names from each
Cargo.toml) plus `cargo check --locked --workspace --all-targets` ONCE at the end (the wiring crosses crates), and
`cargo bench -p <engine> --bench engine_contention --no-run` to prove the bench target builds. Domain review (domains: epoch,
execution, worker). Hand-back: the exact rendered `node switches` line from your test, the gauge name and value encoding, every
setter/getter you added with its signature (the other units' briefs quote them), the `Cargo.lock` delta, `git log --oneline`.
