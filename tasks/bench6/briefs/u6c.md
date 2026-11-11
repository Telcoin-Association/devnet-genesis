# U6c — sealed-keep: review fixes (node unit)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u2` — a finished unit's directory (warm build of tn-reth, the batch builder and the
node); the directory name is NOT your unit's — branch `b6/u-u6c` at the integration head given in your prompt. Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u6c.md` (rewrite it after each section).
Skills: `tn-rust-skills`, `tn-domain-worker`, `tn-domain-execution`. Topic slug: `sealed-keep`. Refs #1807.

## Why
Upstream issue #1807: a worker pruned a batch's transactions from its pool at the quorum ack, so a transaction whose batch
then executed late or out of order sat in no pool and could only land by a client resend (bench 5: 235,073 resend calls,
many executed twice). The fix (switch `sealed_tx_keep`, default false) keeps an acked batch's transactions pooled and
MARKED until the batch executes; selection skips a marked transaction. On a local fleet the switch-off control loses whole
windows in half the runs and the switch-on runs lose nothing.

A code review plus security evaluation (verified findings; report
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/sealed-keep-report.md`) approved the topic with follow-ups. Three of
them are worth fixing before a ten-validator fleet run, because each can make the switch-on arm of the benchmark show a
symptom that looks like the bug it removes:

- **M2 — the pool's global cap.** With the switch on, the in-flight (sealed, unexecuted) transactions stay in reth's pending
  sub-pool, whose default cap is 10,000 transactions and 20 MB. The benchmark's main load keeps about 9,600 transactions in
  flight per validator: with the switch off most of those are OUT of the pool, with it on they are IN it, at 96 % of the
  cap. Above the cap reth silently drops accepted tail nonces and their descendants — #1807's symptom by another path, on
  the switch-on arm only.
- **M1 — a re-pack of transactions that have just executed.** The builder walks a snapshot of the pending pool but reads the
  marks live. A canonical update that prunes and unmarks during the walk lets the builder pack this node's own
  just-executed transactions again; they are then skipped at execution as `nonce too low` — the very count the switch-on
  arm is expected to hold near zero.
- **L1 — a mark that lands after the next epoch's orphan pass is never cleared** (timing only): those transactions are then
  skipped by selection forever.

## Read
1. The report: sections M1, M2, L1 (each cites the lines and suggests a fix), L2-L4 and the answers 2c and 2e.
2. `crates/tn-reth/src/sealed_txs.rs` (module docs), the sealed-keep parts of `crates/tn-reth/src/txn_pool.rs` (how the pool is
   configured: where reth's `PoolConfig` limits are read; `mark_sealed`, the ticket, the canonical-update path that clears
   marks), `crates/batch-builder/src/batch.rs` (the selection walk and its `is_sealed` check) and `lib.rs` (`keeps_sealed`),
   `crates/node/src/manager/node/close_epoch.rs` (the orphan pass's `clear_orphaned`), `crates/tn-reth/src/cli.rs` (where TN
   seeds `max_account_slots`).
3. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U6a", "From U6b", "From ST-B".

## Deliver (one commit per finding; each compiles alone)
1. **M2.** With `sealed_tx_keep` ON, the worker pool's pending sub-pool limits are raised so that the kept in-flight
   transactions do not eat the cap that today bounds only unsealed ones: decide the rule (a fixed multiple of reth's default,
   or the default plus an allowance for in-flight transactions) and state it in the switch's doc; with the switch OFF the
   pool's limits are exactly today's (assert it in a test — the limits read from the built pool, both states). Say what
   memory the higher cap can hold at most. Do not add a config field or a switch. Also say in the hand-back which pool
   metrics (reth's own names, as exported) show a crossing of the cap and an eviction, so that the benchmark's snapshot can
   collect them.
2. **M1.** Close the walk race the way the report suggests (a mark-then-presence check gated on `keeps_sealed`, so that
   switch-off stays byte-identical) or better. A test that fails on the current code: a canonical update prunes and
   unmarks between the snapshot and the mark read, and the builder does not pack the executed transaction.
3. **L1.** A mark that would land after its batch's digest was cleared as orphaned is refused or cleared (about five
   lines per the report). A test for the late-mark-after-orphan-pass order.
4. Switch off: every path is today's. Say how you checked (the existing suites, and by reading each new line's gate).
5. Domain review (domains: worker, execution): ask it to attack the new presence check for a path on which a transaction
   that must be sealed again (its batch was skipped) is now never selected, and the raised limits for a way a client can
   pin memory it could not before.

## You own
`crates/tn-reth/src/txn_pool.rs`, `crates/tn-reth/src/sealed_txs.rs`, `crates/batch-builder/src/batch.rs`, `crates/batch-builder/src/lib.rs`,
`crates/batch-builder/src/test_utils.rs`, the sealed-keep part of `crates/node/src/manager/node/close_epoch.rs`, the
`sealed_tx_keep` doc in `crates/config/src/node.rs`, their inline tests. Nothing else; you do not edit e2e tests and you do
not run them (say which of `crates/e2e-tests/tests/it/sealed_txs.rs`'s tests the orchestrator should re-run).

## Gates
The rules' node environment; through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh`:
`cargo check --locked --all-targets -p tn-reth -p tn-batch-builder -p tn-node -p tn-config`, fmt, clippy for those packages,
`cargo nextest run --locked --no-fail-fast -p tn-reth -p tn-batch-builder -p tn-config -p tn-types -p tn-node -E 'package(tn-reth) | package(tn-batch-builder) | package(tn-node) | package(tn-config)'`,
each new test with timing in it three times by name. Commits `fix(...)`, footers `Refs #1807` and `Topic: sealed-keep`, no
attribution lines. Run the format check and stop on its failure before you commit.

## Hand-back
Per finding: the rule as built in two lines, the test and that it fails without the fix, what changed for the switch-off
path (nothing, with the evidence); the pool limits before and after, with the memory bound; the pool metrics to collect;
the review's verdict; what you did not fix (L2-L4) and why.
