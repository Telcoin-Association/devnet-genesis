# Review scope — sealed-keep-delta (the fixes made after the sealed-keep review)

Upstream issue: #1807. Switch: `sealed_tx_keep` (bool; default false).
Where: the checked-out branch `bench/bench6-2026-11`, head 80a0c76c0. Size: 6 commits, about +550 lines (tests included).
This is a DELTA review: the topic itself was reviewed (report `sealed-keep-report.md` beside this file: APPROVE WITH
FOLLOW-UPS); these six commits are the fixes for its findings M1, M2 and L1 and have not been reviewed by anyone but the unit
that wrote them (whose own domain review found two further problems, fixed in the fourth and fifth commit).

## Commits (the diff under review, in branch order)
- `891e2b962` fix(reth): double the pending sub-pool limits of a pool that keeps sealed transactions
- `d2c695797` fix(batch-builder): skip a candidate that left the pool after the selection's snapshot
- `cc022b4d0` fix(reth): refuse a sealed mark that lands after its digest was orphaned
- `8b23bb608` fix(batch-builder): hold back a sender's later nonces when a replacement took the candidate's nonce
- `c8659e2fa` fix(reth): fence late sealed marks at the orphan pass with the ticket floor
- `80a0c76c0` fix(reth): build the worker pool with the env's sealed_tx_keep

## Files touched
- `crates/tn-reth/src/txn_pool.rs`, `crates/tn-reth/src/sealed_txs.rs`, `crates/tn-reth/src/env/mod.rs`
- `crates/batch-builder/src/batch.rs`, `crates/batch-builder/src/lib.rs`, `crates/batch-builder/src/test_utils.rs`
- `crates/config/src/node.rs` (doc), `crates/node/src/manager/node/close_epoch.rs` (comment)

## Where the claims are written (read these before the code)
- `sealed-keep-report.md` in this directory: findings M1, M2, L1 (what each fix is supposed to close).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U6c" (the rules as built) and
  "sealed-keep (#1807)" (D74).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u6c.md` (the unit's own account, its domain review's
  two findings and what it left open: L2-L4).

## Questions specific to this delta (2g)
1. The presence check (`TxPool::holds`, `holds_nonce`, the "replaced since snapshot" hold-back): find a sequence in which a
   transaction that MUST be packed again (its batch was skipped or orphaned, so it is unmarked and still valid) is skipped
   by every later selection, or in which a sender is held back build after build. The mark is read before presence and
   maintenance prunes before it unmarks: is every interleaving of the selection walk with a canonical update, an eviction
   and a fee-bump replacement covered?
2. The ticket floor raised by the orphan pass: can a legitimate mark of the NEW epoch's builders be refused (a builder that
   took its ticket before the pass and sealed after it; a same-epoch re-entry; two worker pools)? What does a refused mark
   cost, and is it bounded?
3. The doubled pending limits: with the switch OFF are the limits bit-for-bit the configured ones on every construction
   path (`new`, `build`, the test seam, the env)? With it on, is there any path that builds a worker pool WITHOUT the raised
   limits (the wiring commit exists because there was one)? What can a client pin now that it could not before, in bytes?
4. Do these fixes change anything a second validator observes (a mixed fleet), or anything with the switch off?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/sealed-keep-delta-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-sealed-keep-delta.md`
