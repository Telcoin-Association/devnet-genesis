# U6b — sealed-keep, the batch builder side (node unit, wave 2; after U6a)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u2` — a finished unit's directory, reused for its warm build of tn-reth; the directory
name is NOT your unit's — branch `b6/u-u6b`, cut from the integration branch at edc616c0d (the switches, the plumbing and unit
U6a's store and pool side are in). Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u6b.md`.
Skills: `tn-rust-skills`, `tn-domain-worker`, `tn-domain-execution`. Topic slug: `sealed-keep`. Refs #1807.

## Why
When a worker seals a transaction into a batch and the batch reaches quorum, the batch builder removes it from the pool and
advances the pool's nonce optimistically. Until the batch executes the node has no record of the transaction. In bench 5
(r20261107-1504) the load generator repaired such gaps after 300 s with 235,073 resend calls, 60.5 % of which were accepted as
NEW because the node had no record of the original, and about 47 % of those executed twice; 1.81 % of all landings took ≥ 256 s.
Unit U6a built the store that keeps a sealed transaction in the pool, marked, until its batch executes. You make the batch
builder use it.

## Read (in this order)
1. Unit U6a's checkpoint `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u6a.md` and its API as landed, in the
   code: `crates/tn-reth/src/sealed_txs.rs` (module docs first) and the sealed-keep parts of `crates/tn-reth/src/txn_pool.rs`
   (`WorkerTxPool::seal_ticket() -> SealTicket`, `mark_sealed(ticket, digest, hashes).await -> Result<usize, JoinError>`,
   `sealed_txs() -> &SealedTxs`, the `TxPool` trait's `is_sealed(&TxHash) -> bool` with a default of false,
   `SealedTxs::clear_orphaned(&digest) -> usize`). The seven numbered changes U6a asks of the builder are the core of your unit:
   they are in section "What U6b must change in the builder" of the note `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/briefs/u6a-api.md`.
2. Node design §B topic 4 with its "Design correction to the issue":
   `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md`.
3. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-2/sealed-keep-test-cases.md`: the cases U6a could not
   express at pool level and handed to you — S1 end to end (a skipped transaction is re-sealed and executes exactly once), S2 and
   S3 (builder behaviour).
4. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/briefs/u0c-api.md` (`BatchBuilder::sealed_tx_keep()`).
5. Code: `crates/batch-builder/src/lib.rs` (the spawned build task near :353-393, the seal-result handling near :654-680, the
   `mined_transactions.is_empty()` defer branch), `crates/batch-builder/src/batch.rs` (selection near :197-204, the optimistic
   `changed_accounts` near :277-310, `TestPool`), `crates/batch-builder/src/metrics.rs`, how the worker says it seals by quorum
   (`Worker::seals_via_quorum()`), and `orphan_batches` / `repool_batch_txns` in `crates/node/src/manager/close_epoch.rs` (near :132-170).

## You own
`crates/batch-builder/src/lib.rs`, `crates/batch-builder/src/batch.rs`, `crates/batch-builder/src/metrics.rs` and their tests; and
ONE small change in `crates/node/src/manager/close_epoch.rs`: inside `orphan_batches` only (another unit is editing the
`final_state` site further down the same file: do not touch anything else there).

## Deliver (behind `sealed_tx_keep`, default false = today's path, byte-identical batches)
The seven changes of U6a's note, in short: take the seal ticket inside the build task after the batch is built and before it is
sent to the worker; on a quorum `Ok` ack mark the batch's hashes under its digest (before the next selection can run) instead of
pruning them, and decide and document what a `JoinError` from the mark does (fall back to today's prune path is the conservative
choice); with the switch on send no mined hashes and no optimistic `changed_accounts` to the pool after a seal; a switch-on
`Mined` outcome still notes the recovery and continues at once; in selection the `is_sealed` skip comes first, before the
peer-deferred check, and is kept out of the `unpackable` and `peer_deferred` counts and out of `sender_nonces`; never mark on a
refused, empty, failed or failed-to-report outcome; mark only when the worker seals by quorum (an observer keeps today's path).
Plus the close-epoch call: for every orphaned batch digest, on every pool, `pool.sealed_txs().clear_orphaned(&digest)`, whichever
branch of `orphan_batches` runs (today only the committee-member branch re-pools, so a node that leaves the committee would keep
marks under orphaned digests for good).
Metrics: a counter for selection skips of sealed transactions (`tn_batch_builder_sealed_txs_skipped_total`, or the crate's
naming if its scope differs: say the exact name), nothing per transaction in a log.

## Tests
Builder tests with the crate's test pool (make `TestPool` forward `is_sealed` where the tests rely on it) and, where the case
needs real pool behaviour, the real pool as U6a's tests build it: sealed transactions stay pooled and are skipped in the next
selection without being marked invalid; the sender's later nonces stay buildable; S1 — a batch executes without one of its
transactions, the mark clears, the transaction is re-sealed and lands exactly once; S2/S3 as the cases describe them; a failed
report marks nothing and the retry re-seals; an observer prunes as today; a mark's `JoinError` takes the documented path; the
orphan clear at an epoch close on both branches; switch off → the existing builder tests pass unchanged and a batch's contents
are exactly today's.

## Gates and hand-back
As in the rules for the batch-builder and node packages (keep `-p tn-node` in the graph, filter with `-E 'package(…)'`), plus
`cargo check --locked --all-targets -p tn-worker` if you touch anything the worker calls; domain review (domains: worker,
execution). Hand-back: each of the seven changes as built (file:line), the `JoinError` policy, the metric name, the tests with
their I-2 case ids, what the sealed-tx e2e test must still show (the cases only a running fleet can), deviations.
