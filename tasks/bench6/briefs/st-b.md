# ST-B — e2e tests for sealed-keep and the RPC admission bound (test unit: ST-U6 + ST-U11)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections;
the "Test units" section is yours). Load the `tn-write-e2e` skill and `tn-rust-skills`, then `tn-domain-worker` and `tn-domain-execution`.
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u2` — a finished unit's directory; the directory name is NOT your unit's — branch
`b6/u-st-b` at the integration head given in your prompt: every bench-6 fix except pipelined persist is in. Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-b.md`.

## Why
Two of the bench-6 switches change what a CLIENT sees, and neither has run on real nodes yet.
- `sealed_tx_keep` (upstream issue #1807): a validator keeps the transactions of a batch it sealed in its pool, marked, until
  the batch executes, instead of pruning them at the quorum ack. In bench 5 (run r20261107-1504) the pruned-but-unexecuted
  window made clients resend after 300 s; 60.5 % of the resends were accepted as NEW and about 47 % of those executed twice.
  The builder-level tests pass; the switch only acts through a node wiring commit that landed last (the builder is told whether
  its worker seals through a quorum), so the first thing to show is that a live validator really marks.
- `rpc_admission_backlog_outputs: 2`: an active validator refuses `eth_sendRawTransaction` with JSON-RPC −32003 "txpool is full"
  while its engine is two or more consensus outputs behind what the node forwarded to it, and admits again at a backlog of 0.

## Read
1. The e2e harness: `crates/e2e-tests/src/lib.rs` (`NodeOverrides`, `FleetOverrides`, `merge_parameters_yaml`: per-node
   `parameters.yaml` entries and per-node environment variables), `crates/e2e-tests/tests/it/common.rs` (the `*_with_overrides`
   start helpers; the log helpers `node_log_lines`, `wait_for_node_log_line`, `log_field`), the slow-execution test in
   `crates/e2e-tests/tests/it/restarts.rs` (`TN_TEST_EXECUTION_DELAY_MS` on one node: your way to put one engine behind), the
   existing "every node has the same blocks" assertion (`test_blocks_same`), and `it/forward_txs.rs` (an observer forwarding).
   Another test unit is writing `it/exec_block.rs` and `it/epoch_drain.rs` on another branch right now: you will not see them;
   do not create those files.
2. What the fixes log and count: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`, section "Node log lines
   and metrics", rows `sealed-keep (pool side)`, `sealed-keep (builder side)`, `inflight-bound`, and the `node switches` line.
3. The cases: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-2/sealed-keep-test-cases.md` (S1, S6, S7, S9
   are the ones left for e2e) and the "From U6b" and "From U11" sections of
   `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md` (what is NOT fixed, and what "pending" means with the
   switch on).

## You own
`crates/e2e-tests/tests/it/sealed_txs.rs` and `crates/e2e-tests/tests/it/admission.rs` (both exist as one-line stubs with their
`mod` lines in `main.rs`). Nothing else. A bug you find in a fix is a FINDING: keep the failing test, mark it
`#[ignore = "<one-line reason>"]` only if it would block the rest, and report the minimal repro. Do not weaken an assertion to
make a test pass, and do not edit `crates/**/src`.

## Deliver, in this order of priority (hand back after each group if the budget runs short)
1. `sealed_txs.rs::test_validators_keep_and_mark_sealed_transactions`: four validators, `sealed_tx_keep: true` on all, a load of
   several senders with consecutive nonces through at least one epoch boundary. Assert: every validator's
   `batch builder started` line shows `keeps_sealed=true`; marks really exist under load (the gauge `tn_reth_sealed_txs_marked`
   read above zero at least once on a validator — say how you read it — and the cleared-by-execution counter rises); EVERY
   submitted transaction lands EXACTLY once without any client resend (count by hash in the blocks, and the senders' final
   nonces); no marks are left once the load has drained (the gauge returns to 0); all four hold the same blocks.
   Control with the switch off on all: the start line shows `keeps_sealed=false`, the gauge stays 0, the same exactly-once and
   same-blocks assertions hold (the bench-5 symptom needs a resending client, which this test does not have).
2. `sealed_txs.rs::test_mixed_sealed_keep_and_admission_fleet_is_one_chain`: two validators with `sealed_tx_keep: true` and
   `rpc_admission_backlog_outputs: 2`, two with neither, load submitted to all four, across an epoch boundary and one restart of
   a switched-on node: each node's `node switches` line shows what it was given, exactly-once landing, same blocks. (The
   benchmark flips switches by rolling restart, so the fleet is mixed for minutes at every arm change.)
3. `admission.rs::test_backlog_bound_refuses_then_readmits`: `rpc_admission_backlog_outputs: 2` on all four, ONE validator
   executing each output late. Under load: a submission to the slow validator is refused with code −32003 and message
   "txpool is full" while it is behind, its counter `tn_reth_rpc_admission_refused_total` rises, the other three admit; a
   refused transaction is in no pool and never lands unless resubmitted; once the load stops and the slow engine has caught
   up, the same submission is admitted and lands. Control with the bound at 0: the slow validator admits throughout and no
   such counter series exists. State the delay and load at which the gate closes reliably on a loaded machine.
4. `admission.rs::test_observer_forward_survives_closed_gates`: an observer forwarding to validators whose gates are closed
   (all four slow enough, or the bound at 1): the transaction is not lost — it lands once after the gates reopen — and the
   observer itself never answers −32003.
5. `sealed_txs.rs::test_restart_with_sealed_uncommitted_batches` (S9): a validator killed with marked, uncommitted
   transactions, restarted; the client resends the same bytes. The marks live in memory, so I-2's expectation ("already
   known" after the restart) may NOT hold: establish what happens, assert the invariant that must hold either way (each
   transaction executes exactly once; none is lost), and report the resend's answer as a finding if it is accepted as new.
6. If budget remains: S6 (a seal that fails to report at the epoch boundary: every transaction of that batch executes
   exactly once in the new epoch without a resend, in BOTH switch states — if the switch-off control fails this, that pins
   bench 5's boundary loss: say so, it is the most important finding you can make), then S7 (a real queued-limit eviction of
   a marked transaction).

## How to run (fixed ports: ONE e2e job on the machine at a time)
Environment for every build and test call (the rules' node environment plus):
`export TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295`.
Build the node binary the tests start, once, through the slot wrapper:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo build --locked --profile e2e --bin telcoin-network --features tn-storage/test-utils --target-dir "$PWD/target"`,
then `export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"`. Run each test through the lane, never any other way:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh cargo nextest run --locked -p e2e-tests --test it --run-ignored all -E 'test(=<module>::<name>)'`.
The lane takes a machine-wide lock and another test unit is using it too: waits of many minutes are normal, never a reason to
bypass it. The machine is loaded by other units' builds, so every wait in your tests is a deadline on an observed condition (a
log line, a block height, a counter), never a fixed sleep, and each test is run three times before you call it stable.

## Gates
`cargo check --locked --all-targets -p e2e-tests`, fmt, clippy for the package (through the slot wrapper); each new test three
times through the lane. Commits: one per module, `test(e2e): …`, footers `Refs #1807` + `Topic: sealed-keep` (sealed_txs.rs)
and `Topic: inflight-bound` (admission.rs).

## Hand-back
For each test: what it starts, what it asserts with the numbers you saw in three runs, its runtime; every FINDING against a
fix with its repro; flakiness you saw and its cause; what you did not get to; and your verdict for the image gate — "validators
mark and every transaction lands exactly once", "a fleet mixed on these two switches is one chain", "the bound refuses and
readmits as specified", "a forwarded transaction survives closed gates": YES, NO, or NOT SHOWN.
