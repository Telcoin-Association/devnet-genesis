# U6a — sealed-keep, the store and the pool side (node unit, wave 1)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u2` — a finished unit's directory, reused for its warm build cache; the directory name is NOT your unit's — (branch `b6/u-u6a`, cut from the integration branch with U0a's switches and U0c's
plumbing in). Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u6a.md`.
Skills: `tn-rust-skills`, `tn-domain-worker`, `tn-domain-execution`. Topic slug: `sealed-keep`. Refs #1807.

## Why
When a worker seals a transaction into a batch and the batch reaches quorum, the transaction is removed from the pool and the
pool's nonce is advanced optimistically. From then until the batch executes, the node has no record of it: RPC lookups miss, the
pending nonce does not count it, and if the batch is lost or delayed the sender sees a nonce gap. In bench 5 (r20261107-1504) the
load generator repaired such gaps after 300 s: 235,073 resend calls, of which 60.5 % were accepted as NEW because the node had no
record of the original; about 47 % of those executed twice (37,683 `nonce too low` skips); 1.81 % of all landings took ≥ 256 s.
The fix keeps a sealed transaction in the pool, marked, until its batch executes.

## Read (in this order)
1. Node design §B topic 4, including the "Design correction to the issue": `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md`.
2. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-2/sealed-keep-test-cases.md` (take every case a pool
   unit test can express; the batch-builder cases are the next unit's, the e2e cases a later unit's) and `…/I-2/verdict.md` "Q2", "Q3".
3. Code: `crates/tn-reth/src/txn_pool.rs` (`PeerBatchTxs` near :1037 is the model; `process_canon_state_update` near :865;
   `add_recovered_transaction_external`; the pending-nonce and lookup paths near :764), `crates/tn-reth/src/lib.rs`, where a block's
   `ommers_hash` carries its batch digest (`evm/config.rs` near :249, read-only), and how U0c made `sealed_tx_keep` readable on the
   pool side (its getter).

## You own
New `crates/tn-reth/src/sealed_txs.rs` (+ its `mod` line in `crates/tn-reth/src/lib.rs`), `crates/tn-reth/src/txn_pool.rs`, and their
unit tests. NOT the batch builder (`crates/batch-builder/**` is the next unit, U6b: it calls your marking API on a quorum ack and
skips marked transactions when it selects) and not `close_epoch.rs`.

## Deliver (behind `sealed_tx_keep`, default false = today's behaviour unchanged)
1. `SealedTxs`: a store of (batch digest → transaction hashes) and (hash → digest), modelled on `PeerBatchTxs` but with NO time-based
   expiry (a mark lives until its batch executes or the transaction is re-pooled). Bounded: say what bounds it (it can only hold
   transactions that are in the pool) and what happens to marks whose transaction the pool evicts (the mark is dropped with it:
   reth's own eviction can still drop a marked transaction, which falls back to today's behaviour — accepted for this round, but
   count it: a counter for marks dropped by eviction).
2. The API the batch-builder unit needs (document it; it is the interface between your unit and U6b): mark a sealed batch's
   hashes under its digest; ask whether a hash is marked; iterate/skip support for selection if the pool does the selection.
3. Clearing, as the design correction says: in `process_canon_state_update`, each executed block's `ommers_hash` is its batch
   digest — after the update removes mined transactions, unmark whatever is still pooled for those digests and drop the marks of
   every mined hash. NOT at forward time (the issue's original wording would re-seal transactions that are about to execute).
4. `add_recovered_transaction_external` (used when an epoch boundary re-pools an orphaned batch's transactions) clears an existing
   mark, so the transaction becomes buildable again.
5. Visibility: a marked transaction is found by hash through the pool/RPC path, submitting the same bytes again answers
   `AlreadyImported` ("already known"), and the pending nonce counts it — these are the three properties that make the generator's
   300-s repair unnecessary. With the switch on, the optimistic nonce advance that today stands in for the removed transaction
   must not be double-counted on the pool side: state what U6b must stop sending.
6. Metrics (names in your hand-back): marked now (gauge), marks cleared by execution, by re-pool, dropped by eviction (counters).

## Tests
Pool unit tests from the I-2 cases: a sealed transaction stays visible by hash; the same bytes return `AlreadyImported`; the pending
nonce counts it; execution of its batch (canon update with that `ommers_hash`) clears the mark and removes it; a canon update for
another digest leaves it; re-pooling clears the mark; an evicted marked transaction drops its mark and moves the counter; descendants
(higher nonces of the same sender) stay pending and selectable; switch off → every existing pool test unchanged.

## Gates and hand-back
As in the rules for the tn-reth package; domain review (domains: worker, execution). Hand-back: the `SealedTxs` API verbatim (U6b's
brief quotes it), what U6b must change in the builder (mark instead of `update_canonical_state`, no optimistic nonce advance, skip
without `mark_invalid`), the metric names, and any I-2 case you could not express at this level.
