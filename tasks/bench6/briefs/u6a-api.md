# What unit U6a (sealed-keep, pool side) landed — the contract for the batch builder (U6b) and the e2e test (ST-U6)

Integrated as edc616c0d (unit commit da24d6780). The code's module docs (`crates/tn-reth/src/sealed_txs.rs`) are authoritative; this is
U6a's hand-back.

## API
On `tn_reth::WorkerTxPool`:
- `pub fn seal_ticket(&self) -> SealTicket`
- `pub async fn mark_sealed(&self, ticket: SealTicket, digest: BlockHash, hashes: Vec<TxHash>) -> Result<usize, JoinError>` — runs on
  `spawn_blocking`; marks only the hashes the pool still holds and returns how many were newly marked; marks NOTHING if `digest`
  executed after `ticket` was taken, or if a canonical-state broadcast lag happened after it.
- `pub fn sealed_txs(&self) -> &SealedTxs`
- on the `TxPool` trait: `fn is_sealed(&self, _hash: &TxHash) -> bool { false }` (a default, so other implementations such as
  batch.rs's `TestPool` keep compiling; `WorkerTxPool` overrides it; a test pool must forward it if its tests rely on the skip).
`tn_reth::sealed_txs::SealedTxs` (cheap-clone shared handle): `new()`, `ticket() -> SealTicket`, `is_marked(&TxHash) -> bool`,
`digest_of(&TxHash) -> Option<BlockHash>`, `len()`, `is_empty()`, `clear_orphaned(&BlockHash) -> usize`. `SealTicket(u64)` is opaque
and `Copy`. Consts `SEALED_TXS_EXECUTED_MEMORY = 4_096`, `SEALED_TXS_SWEEP_INTERVAL = 1 s`.

## Why there is a ticket
The worker acks a batch only after it reports the digest, so under load the batch can EXECUTE before the builder handles the ack;
a mark made then would leave a skipped transaction marked for good. The ticket is taken when the batch is built; `mark_sealed`
refuses if the digest executed since.

## When marks clear
- Execution (`process_canon_state_update`, after the pool update): each block's `ommers_hash` is its batch digest; every mark under
  that digest clears (what the block skipped becomes buildable again) and every mined hash loses its mark.
- Re-pool: `add_recovered_transaction_external` clears the hash's mark first (covers `close_epoch` `repool_batch_txns`, the
  forwarder's requeue and retry). A client resend goes through reth's RPC handle and never clears a mark.
- Eviction: the maintenance loop sweeps at most once a second and drops marks whose transaction left the pool.
- Lag: a canonical-state broadcast lag drops every mark and raises a floor, so a ticket taken before the lag is refused.

## What U6b must change in the builder
1. Take `let ticket = pool.seal_ticket();` inside the spawned task, after `spawn_batch_build(..).await` returns and before
   `to_worker.send` (lib.rs ~353-393). Not at ack time, and not before selection.
2. On a quorum `Ok` ack, call `pool.mark_sealed(ticket, batch.digest(), mined_transactions).await` before the next selection can
   run (in the task before `result.send`, or in the run loop before `continue`). Pick a policy for a `JoinError`: fall back to the
   prune path, or treat it as fatal.
3. With the switch on, stop calling `update_canonical_state` after a seal: send no mined hashes and no `changed_accounts` (the
   optimistic nonce max+1 and the debited balance, batch.rs ~277-310). reth discards pooled transactions below an advanced nonce
   (`txpool.rs:1542`), which would undo the feature. Computing `changed_accounts` and `get_account_balances` can be skipped too.
4. The `mined_transactions.is_empty()` defer branch (lib.rs ~676): a switch-on `Mined` outcome must still call `note_recovery()`
   and `continue` right away.
5. In `batch.rs` selection (~197-204), put the `is_sealed` arm first, before `is_peer_deferred`, so `peer_deferred` cannot drop the
   descendants; keep the skip out of the `unpackable` and `peer_deferred` counts and out of `sender_nonces`.
6. Never mark on Refused, Empty, Failed or `FailedToReport`.
7. Mark only when the worker seals by quorum (`Worker::seals_via_quorum()`). On an observer the batch is re-packed under other
   digests, so its marks would clear only by mined hash or requeue; keep today's prune path there.

## Cross-unit need (given to U6b)
`close_epoch.rs` `orphan_batches` re-pools only on the committee-member branch. A node that leaves the committee takes the
`disburse_txns` branch, so its marks under orphaned digests would never clear: call `pool.sealed_txs().clear_orphaned(&digest)` for
every orphan digest on every pool, whichever branch runs.

## Metrics and log lines (Prometheus renders `.` as `_`)
Gauge `tn_reth.sealed_txs_marked`; counters `tn_reth.sealed_txs_cleared_executed_total`, `tn_reth.sealed_txs_cleared_repooled_total`
(also counts `clear_orphaned`), `tn_reth.sealed_txs_dropped_evicted_total`, `tn_reth.sealed_txs_cleared_lag_total`,
`tn_reth.sealed_txs_late_marks_refused_total` (counts transactions). Warnings (target `txpool`):
`sealed transaction marks dropped after canonical state broadcast lag` (field `marks`),
`sealed transaction mark sweep failed; retrying after the next interval` (field `error`).

## Residuals U6a accepted (for the reviewers and the run's analysis)
- A retired worker's `migrate_transactions_to` hands over transactions without their marks (in practice none remain then).
- Sealed transactions hold pool capacity until execution, including the 256 per-sender slots: a generator window above 256 would
  hit slot refusals (the bench uses windows 16 and 4).
- reth's own eviction can still drop a marked transaction: the mark is dropped with it and counted (today's behaviour for that one).

## Left for the e2e test (ST-U6): the I-2 cases only a running fleet can show
S1 end to end, S6 (the epoch-boundary loss path) and S9 (restart); S7 (a real queued-limit eviction) was only simulated at pool level.
