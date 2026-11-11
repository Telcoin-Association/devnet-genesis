# ST-A — e2e tests for the proposer/voter fix and the epoch-close drain, and the mixed-switch fleet (test unit: ST-U1 + ST-U5)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections;
the "Test units" section is yours). Load the `tn-write-e2e` skill and `tn-rust-skills`, then `tn-domain-consensus` and `tn-domain-epoch`.
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u0b` — a finished unit's directory (its e2e build profile is warm); the directory name is
NOT your unit's — branch `b6/u-st-a` at c8e5ae7be, the integration head: every bench-6 fix except the batch-builder side of
sealed-keep, the admission bound and pipelined persist is in. Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-a.md`.

## Why
Bench 6 puts eight node fixes behind switches in one image. Unit tests cover each fix in isolation; nothing has yet started real
nodes with a switch on. Before a fleet is paid for, a local four-node network must show (1) that the proposer and voter fixes
for upstream issue #1804 do what the issue promises, (2) that the epoch-close drain for #1806 does, and (3) that a fleet in
which only some nodes have the switches on stays ONE chain — the benchmark flips switches by rolling restart, so the fleet is
mixed for minutes at every arm change.

## Read
1. The e2e harness as it is now: `crates/e2e-tests/src/lib.rs` (the docs of `NodeOverrides`, `FleetOverrides`,
   `merge_parameters_yaml`: per-node `parameters.yaml` entries and per-node environment variables), `crates/e2e-tests/tests/it/common.rs`
   (the `*_with_overrides` start helpers; the log helpers `node_log_lines`, `wait_for_node_log_line`, `log_field`), the existing
   slow-execution test in `crates/e2e-tests/tests/it/restarts.rs` (it arms `TN_TEST_EXECUTION_DELAY_MS` on one node: your pattern),
   and `test_blocks_same` (find it: the existing "every node has the same blocks" assertion).
2. What the fixes log, so that a test can assert on a node's own report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`,
   section "Node log lines and metrics" (the `node switches` line a node prints at start; `header proposed` with `exec_block`,
   `exec_tip`, `exec_basis`, `exec_policy`; `vote path timing` with `outcome` and `prelock_wait_ms`; `epoch close drained`;
   `Failed to track spawned task`; the halt line of the final-state check).
3. The issues' own e2e cases: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/bench5-execution-behind-vote-starvation.md`
   and `…/bench5-loaded-epoch-boundary-drain.md` (grep "e2e"), and the two notes that correct them:
   `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-4/unit-specs.md` (§U1, §U5) and the U1 and U5 sections of
   `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md` (the proposer rule has two policies:
   `quorum_exec_block_starved_rounds: 0` = the rule on every header, which settles 8 outputs behind the tip; `4` = own tip by
   default, the rule for 4 rounds after an own header was cancelled uncertified).

## You own
`crates/e2e-tests/tests/it/exec_block.rs` and `crates/e2e-tests/tests/it/epoch_drain.rs` (both exist as one-line stubs with their `mod`
lines in `main.rs`). Nothing else. A bug you find in a fix is a FINDING: keep the failing test, mark it
`#[ignore = "<one-line reason>"]` only if it would block the rest, and report the minimal repro. Do not weaken an assertion to
make a test pass, and do not edit `crates/**/src`.

## Deliver
1. `exec_block.rs::test_fast_executor_is_certified`: four validators, three of them executing each output late
   (`TN_TEST_EXECUTION_DELAY_MS` on three nodes), under a transaction load that produces outputs. Control run with the switches
   off: show bench 5's signature on the fast node (its headers refused as "execution behind", a low share certified) — if the
   control does NOT reproduce it at this scale, say so and find the delay and load at which it does, because without a failing
   control the test proves nothing. Then with `quorum_exec_block: true` + `quorum_exec_block_starved_rounds: 4` +
   `vote_queue_fix: true` on all four: the fast node's own headers certify (state the share and the threshold you assert, with
   margin for a loaded machine), `exec_policy` shows `tip` and `starved` as expected, and all four nodes hold the same blocks.
   A second variant with `quorum_exec_block_starved_rounds: 0`: certified, and `exec_basis` settles on `floor`.
2. `exec_block.rs::test_mixed_switch_fleet_is_one_chain`: two validators with every bench-6 switch that is in this tree on
   (`quorum_exec_block` with starved rounds 4, `vote_queue_fix`, `mdbx_random_advice`, `digest_dedupe`, `recovery_threads: 3`,
   `epoch_close_task_drain`, `epoch_record_state_check`, `parent_grace: 150ms`; NOT `sealed_tx_keep`, `rpc_admission_backlog_outputs`
   or `pipelined_persist`, whose code is not complete in this tree) and two with none, under load, across at least one epoch
   boundary and one restart of a switched-on node: every node's `node switches` line shows what it was given, the chain
   advances, and all four hold the same blocks (`test_blocks_same`'s assertion).
3. `epoch_drain.rs::test_loaded_close_with_a_slow_member`: an epoch close under load with one slow member. With
   `epoch_close_task_drain: true` and `epoch_record_state_check: true` on all nodes: the epoch closes on every node, each logs
   `epoch close drained`, no node logs `Failed to track spawned task`, no node halts on the final-state check, the next epoch
   starts and the blocks match. Control with the switches off: the close still completes (today's behaviour); if the
   tracking-channel overflow can be provoked at this scale, assert it in the control, and if it cannot (the channel holds 1,000
   and bench 5 needed a loaded ten-node fleet), say so plainly — then the test pins "no regression and the drain line appears",
   not "the overflow is fixed", and your hand-back says that.

## How to run (fixed ports: ONE e2e job on the machine at a time)
Environment for every build and test call (the rules' node environment plus):
`export TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295`.
Build the node binary the tests start, through the slot wrapper:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo build --locked --profile e2e --bin telcoin-network --features tn-storage/test-utils --target-dir "$PWD/target"`,
then `export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"` (rebuild it whenever you pull nothing — you do not change node code —
so once is enough). Run each test through the lane, never any other way:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh cargo nextest run --locked -p e2e-tests --test it --run-ignored all -E 'test(=<module>::<name>)'`.
The lane takes a machine-wide lock and waits for other e2e jobs (another test unit may be using it): a wait is normal. The
machine is loaded by other units' builds, so every wait in your tests is a deadline on an observed condition (a log line, a
block height), never a fixed sleep, and each test is run three times before you call it stable.

## Gates
`cargo check --locked --all-targets -p e2e-tests`, fmt, clippy for the package (through the slot wrapper); each new test three
times through the lane. Commits: one per module, `test(e2e): …`, footers `Topic: quorum-exec-block` (exec_block.rs; Refs #1804)
and `Topic: tracker-drain` (epoch_drain.rs; Refs #1806).

## Hand-back
For each test: what it starts, what it asserts with the numbers you saw in three runs, its runtime, and whether the CONTROL
reproduces the bench-5 signature at this scale; every FINDING against a fix with its repro; flakiness you saw and its cause;
and your verdict for the image gate — "the proposer/voter fix works on a local fleet", "a mixed-switch fleet is one chain", "the
drain works": YES, NO, or NOT SHOWN AT THIS SCALE.
