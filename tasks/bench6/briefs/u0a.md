# U0a node switches — original brief (as sent to the first agent; recovered from the session transcript 2026-11-11)

You are node unit **U0a (switches)** of the bench-6 program. Read /home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md first, all of it except the harness and investigation sections, and follow it exactly. Worktree (yours alone): /home/drtnarg/coding/telcoin/tn-b6-u0a (branch b6/u-u0a at 165e3fe01). Checkpoint: /home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u0a.md (on start, read it and continue from the first unfinished section). Domains: `tn-domain-epoch` (node configuration); load `tn-rust-skills` first.

## Why
Bench 6 ships eight node fixes in one image, each behind a runtime switch that defaults to bench-5 behaviour, flipped per benchmark arm by rewriting `parameters.yaml` and restarting. You add the switches; other units read them. Design: /home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md §A (read it) and the switch table in the plan (/home/drtnarg/.claude/plans/i-want-to-run-groovy-grove.md, section "W2a — node topics", the "Switches" table and the U0a row).

## You own
`crates/config/src/node.rs` (the `Parameters` struct and its tests), one new file `crates/types/src/execution_backlog.rs` plus its `mod`/`pub use` lines in `crates/types/src/lib.rs`. Nothing else. (`crates/node/**`, `crates/engine/**` and the e2e crate belong to units U0c and U0b.)

## Deliver (one commit per switch group, each compiling alone, footer `Topic: <slug>` as given)
Flat top-level `Parameters` fields, each `#[serde(default)]` (or the struct's existing default mechanism — follow how the neighbouring fields do it, including duration parsing), each with a `///` doc that says what it switches, that the default is the previous behaviour, and the upstream issue:
| field | type, default | Topic slug | Refs |
|---|---|---|---|
| `quorum_exec_block` | bool, false | `quorum-exec-block` | #1804 |
| `vote_queue_fix` | bool, false | `voter-lock` | #1804 |
| `mdbx_random_advice` | bool, false | `mdbx-advice` | #1802 |
| `sealed_tx_keep` | bool, false | `sealed-keep` | #1807 |
| `digest_dedupe` | bool, false | `digest-dedupe` | #1807 |
| `recovery_threads` | u16, 0 (0 = the global pool) | `recovery-pool` | #1805 |
| `epoch_close_task_drain` and `epoch_record_state_check` | bool, false (one commit) | `tracker-drain` | #1806 |
| `parent_grace` | duration, 0 ms | `parent-grace` | #1803 |
| `rpc_admission_backlog_outputs` | usize, 0 (off) | `inflight-bound` | — |
| `pipelined_persist` | bool, false | `pipelined-persist` | — |
Plus, in a first commit with `Topic: bench6-switches`: a small public way to enumerate the switches for logging — e.g. `Parameters::switches(&self) -> [(&'static str, String); N]` (name = the YAML key, value rendered as it would be written in YAML) — which unit U0c will use to log one `node switches` line and export a `tn_node_switch{name}` gauge; keep it in sync with the fields by a test that fails when a switch field is added without being listed. Keep getters consistent with the existing style (if the struct exposes fields directly, do the same).

**`tn_types::ExecutionBacklog`** (commit with `Topic: inflight-bound`): a cheap, cloneable handle around atomics, no locks, for the admission bound. Writers: the node records the number of the last consensus output forwarded to the engine (unit U11, in `run_epoch.rs`); the engine records how many outputs are queued or in flight and the last output it finished (unit U0c, beside the existing queued-outputs gauge in `engine/src/lib.rs`). Reader: the RPC submission guard (unit U11) asks "how many outputs is execution behind" and applies hysteresis (close at ≥ K, reopen below K−1). Give it a minimal, documented API that covers those three callers (e.g. `record_forwarded(u64)`, `record_queued(usize)`, `record_executed(u64)`, `outputs_behind() -> u64`, and an `AdmissionGate`-style helper with the hysteresis as a pure, unit-tested function), `Default`, `Debug`, `Clone`. It must not depend on any crate `tn-types` does not already depend on.

**Per-node execution delay for e2e tests**: a later e2e test (`test_fast_executor_is_certified`) must delay execution on 3 of 4 nodes. First find how the existing hook works (`TN_TEST_EXECUTION_DELAY_MS` in `crates/types/src/test_hooks.rs` and its use near `crates/e2e-tests/tests/it/restarts.rs`, grep for it). If the hook can already be set per node through a per-node environment in the e2e harness, add nothing and say so in the hand-back (unit U0b owns the harness side). Only if it cannot, add the smallest test-only knob in `Parameters` (feature-gated like the existing test hooks, absent from a release build) and describe exactly how U0b and the engine side must use it.

## Tests (in the crates you own)
Round-trip: a `parameters.yaml` without any of the new keys deserializes to the defaults and re-serializes without changing the meaning of the existing keys; each new key parses with its arm value from the table in the plan (`true`, `3`, `150ms`/`100ms`, `2`); an unknown key is still ignored (pin today's behaviour); the embedded presets for `--chain adiri/mainnet` are unchanged; the switch enumeration covers every new field; `ExecutionBacklog` arithmetic (saturating, never panics, concurrent writers in a threaded test) and the hysteresis table.

Gates: as in the rules for `-p tn-config -p tn-types` (check the real package names in each Cargo.toml) plus `cargo check --locked --all-targets -p tn-node` to prove nothing downstream broke. Then the domain review, then the hand-back: include the exact YAML key names and value syntax (the harness arm tool writes them), the public API of `ExecutionBacklog` and of the switch enumeration verbatim, and your answer on the per-node execution delay.
