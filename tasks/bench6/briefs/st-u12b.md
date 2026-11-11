# ST-U12b — e2e tests for pipelined persist, and a fleet-wide switch override for the e2e harness (test unit)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections;
the "Test units" section is yours). Load the `tn-write-e2e` skill and `tn-rust-skills`, then `tn-domain-execution`,
`tn-domain-storage`, `tn-domain-epoch`.
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u0c` — a finished unit's directory; the directory name is NOT your unit's — branch
`b6/u-st12b` at 27de9976e = the integration head 3ee6b629f (every other bench-6 fix) plus the eleven commits of pipelined
persist (core, wiring, the delay hook). `git diff 27de9976e` is your unit's diff. Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-u12b.md` (rewrite it after each deliverable).

## Why
`pipelined_persist: true` lets the engine build output N+1 on N's in-memory state while N's persist runs (two slots, a pinned
read snapshot per output, the closing output of an epoch as a barrier). It is the riskiest change of bench 6 and ships in the
bench image only if its go/no-go gates pass. The unit-level gates have passed (differential test, barrier test). Yours is
gate 4: real nodes. The property that matters: a pipelined node computes exactly the chain a sequential node computes, through
epoch boundaries, restarts and kills, and never shows consensus anything that is not durable.

## Read
1. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-5/design.md` §2 (the state machine), §4 (crash and
   failure matrix), §6.4 (your tests, by name).
2. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U12a" and "From U12b" (what was built,
   what "executed" means, the metric and log names in pipelined mode, the test delay hook).
3. The e2e harness: `crates/e2e-tests/src/lib.rs` (`NodeOverrides`, `FleetOverrides`, `merge_parameters_yaml`),
   `crates/e2e-tests/tests/it/common.rs` (start helpers with and without overrides, log helpers), `it/restarts.rs` (the slow
   executor test, `test_blocks_same`), `it/sigkill.rs`, `it/epochs.rs`, and the Makefile targets `test-restarts`, `test-epochs`,
   `test-sigkill` (their nextest filters and environment).
4. `crates/types/src/test_hooks.rs` (`execution_delay`: `TN_TEST_EXECUTION_DELAY_MS`), `crates/tn-reth/src/env/execution.rs`
   (`inject_persist_delay`, test-utils only), `crates/engine/src/persister.rs` (where the build task applies the delay hook).

## You own
`crates/e2e-tests/tests/it/persist_pipeline.rs` (a one-line stub with its `mod` line in `main.rs`); for deliverable 1 only,
`crates/e2e-tests/src/lib.rs` and `crates/e2e-tests/tests/it/common.rs`; for deliverable 2 only,
`crates/types/src/test_hooks.rs` and ONE call site in `crates/tn-reth/src/env/mod.rs`. Nothing else: no other `crates/**/src`,
no other test module (other test units are writing `exec_block.rs`, `epoch_drain.rs`, `sealed_txs.rs`, `admission.rs` on
other branches). A bug you find in the fix is a FINDING: keep the failing test, mark it `#[ignore = "<reason>"]` only if it
blocks the rest, report the minimal repro, do not weaken the assertion.

## Deliver, in this order (checkpoint and commit after each; one commit per deliverable)
1. **Fleet-wide parameters from the environment** (commit `test(e2e): …`, footer `Topic: bench6-switches`; it must touch only the
   two harness files so it can be picked onto a branch without pipelined persist). `TN_E2E_PARAMETERS`, a list of top-level
   `parameters.yaml` entries (choose a one-line format, e.g. `key: value; key: value`, and document it in the module docs), is
   merged into EVERY node's `parameters.yaml` by every start helper, including the ones that take no overrides, BEFORE a test's
   own `FleetOverrides` (the test's entries win). An unparsable value fails the test start with a message naming the variable.
   Each fleet start prints once what it applied. Unit tests for the parser and the merge order. Purpose: the orchestrator runs
   the repo's existing `restarts`, `epochs` and `sigkill` sets unchanged with `TN_E2E_PARAMETERS='pipelined_persist: true'` (and
   later with every bench-6 switch on); you do NOT run those sets (hours of lane time), you run ONE existing short test with
   the variable set and show the node's `node switches` line carrying `pipelined_persist=true`.
2. **A persist delay for e2e** (commit `test(types): …`, footer `Topic: pipelined-persist`): `TN_TEST_PERSIST_DELAY_MS` beside
   `TN_TEST_EXECUTION_DELAY_MS` in `test_hooks.rs` (same parsing, same `test-utils` gate, same docs standard, the parser's unit
   tests mirrored), applied once where the reth environment is created by calling the existing `inject_persist_delay`. On a
   local four-node network a persist takes milliseconds, so without it the pipeline never parks a built output behind a
   running persist and your tests would exercise only half the state machine. Absent without `test-utils`, as the other hook.
3. `persist_pipeline.rs::test_mixed_fleet_blocks_same` — THE go/no-go test: validators 1-2 with `pipelined_persist: true`, 3-4
   without; a persist delay of a few hundred ms on every node (so that on-nodes overlap build and persist); transactions
   flowing across two epoch boundaries; one on-node and one off-node restarted mid-run. Assert: `test_blocks_same`'s assertion
   over all four at the end; every node's finalized height advanced; each node's `node switches` line shows what it was given;
   no log line of any node carries `PipelineInvariant`, a fork or a state-root mismatch; on the on-nodes the pipeline really
   overlapped (find the evidence in the node's own log or metrics — e.g. `tn_engine_unpersisted_outputs` reaching 2, or
   `tn_engine_commit_interval_seconds` samples — and say what you used; a test in which the pipeline never overlapped proves
   nothing and must FAIL, not pass).
4. `persist_pipeline.rs::test_pipelined_epoch_close_under_load`: all four on, persist delay, load across an epoch boundary:
   the epoch records are equal on all nodes, the next epoch starts, blocks match, and state what
   `tn_engine_close_barrier_holds_total` read on each node (the design expects 0 because the forwarder sends nothing past a
   close; a non-zero value is not a failure but is reported).
5. `persist_pipeline.rs::test_sigkill_mid_pipeline_replays`: one on-node under load with a persist delay is SIGKILLed five
   times at varied points (derive the points from observed log lines — a kill while one output is committing and the next is
   built is the case to hit at least once; say how you know you hit it); after each restart it catches up; blocks match at the
   end; no node reports a consistency error on restart.
6. If budget remains: the slow-executor case with the switch on (`TN_TEST_EXECUTION_DELAY_MS` on one pipelined node; it must
   stay an active validator as `restarts.rs::test_slow_execution_stays_active` requires of a sequential one).

## How to run (fixed ports: ONE e2e job on the machine at a time)
Environment for every build and test call (the rules' node environment plus):
`export TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295`.
Build the node binary the tests start through the slot wrapper (again after deliverable 2, which changes the binary):
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo build --locked --profile e2e --bin telcoin-network --features tn-storage/test-utils --target-dir "$PWD/target"`,
then `export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"`. Check that the hooks are in that binary (the feature set above
is what the repo's own e2e build uses; if `tn-types/test-utils` is not on in it, say so before writing any test). Run each
test through the lane, never any other way:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh cargo nextest run --locked -p e2e-tests --test it --run-ignored all -E 'test(=<module>::<name>)'`.
Two other test units share the lane: waits of many minutes are normal, never a reason to bypass it. The machine is loaded,
so every wait in your tests is a deadline on an observed condition, never a fixed sleep; each test is run three times before
you call it stable.

## Gates
`cargo check --locked --all-targets -p e2e-tests -p tn-types -p tn-reth`, fmt, clippy for those packages, `cargo nextest run
--locked -p tn-types -p tn-reth -p tn-node -E 'package(tn-types)'` for the parser tests (through the slot wrapper); each new e2e
test three times through the lane.

## Hand-back
Per deliverable: what it starts and asserts with the numbers from three runs, runtime, the evidence that the pipeline
overlapped; every FINDING with its repro; flakiness and its cause; the exact command line for the orchestrator to run an
existing set with the switch on; what you did not reach; and your verdict on go/no-go gate 4 — "a pipelined node computes the
sequential chain through epochs, restarts and kills": PASS, FAIL, or NOT SHOWN.
