# Review scope — sealed-keep

Upstream issue: #1807. Switch: `sealed_tx_keep` (bool; default false).
Where: the checked-out branch `bench/bench6-2026-11`, head ae62cc47a. Size: 9 commits, +3749 lines (tests included).

## Commits (the diff under review, in branch order)
- `1169532a8` feat(config): add the sealed_tx_keep switch
- `a00fae8bb` feat(batch-builder): hand the sealed_tx_keep switch to the batch builder and the pool side
- `7cfe52acd` fix(batch-builder): start the batch builder on its reth env's sealed_tx_keep
- `edc616c0d` feat(reth): keep sealed transactions pooled and marked until their batch executes
- `c08d78c33` feat(batch-builder): keep sealed transactions pooled until their batch executes
- `3bbcbe226` fix(node): clear sealed marks of orphaned batches on every worker pool
- `3ee6b629f` feat(node): tell the batch builder whether its worker seals through a quorum
- `fe86f1658` test(e2e): sealed-keep on a live fleet, a mixed fleet and a restart with marks
- `ae62cc47a` test(e2e): report an S9 kill that leaves nothing to resend instead of failing

## Files touched
- `crates/batch-builder/src/batch.rs`
- `crates/batch-builder/src/lib.rs`
- `crates/batch-builder/src/metrics.rs`
- `crates/batch-builder/src/test_utils.rs`
- `crates/config/src/node.rs`
- `crates/e2e-tests/tests/it/sealed_txs.rs`
- `crates/node/src/engine/inner.rs`
- `crates/node/src/engine/mod.rs`
- `crates/node/src/manager/node.rs`
- `crates/node/src/manager/node/close_epoch.rs`
- `crates/node/src/manager/node/run_epoch.rs`
- `crates/tn-reth/src/env/mod.rs`
- `crates/tn-reth/src/lib.rs`
- `crates/tn-reth/src/sealed_txs.rs`
- `crates/tn-reth/src/txn_pool.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table row and the rows `sealed-keep (pool side)` and `sealed-keep (builder side)` under "Node log lines and metrics".
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U6a", "From U6b" (as built; the node wiring commit; residuals D51: fee-bump replacement, uncertified header holding marks, non-validator orphan branch, marks in memory) and D12-D14.
- The issue body `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/bench5-sealed-tx-invisible-drops-and-duplicates.md`, the cases `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-2/sealed-keep-test-cases.md`, the node design `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md` §B topic 4 (with its "Design correction to the issue").
- Unit checkpoints `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u6a.md`, `…-u6b.md`, and the e2e result if it exists when you start: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-b.md`.

## Questions specific to this topic (2g)
1. Exactly-once: find any sequence in which a marked transaction executes twice, or never (stuck marked forever, so that selection skips it and no path clears the mark). Walk: quorum ack then the batch never certifies; the header is cancelled and its digests re-queued; the batch is orphaned at an epoch close; the node restarts; the mark task fails; the transaction is evicted from the pool while marked; a replacement by fee bump.
2. The ticket taken before sealing exists to close a race between a late mark and an early execution of the same batch. Is the race closed for every ordering of ack, canonical update and mark? What if two batches hold the same transaction?
3. Pool accounting with the switch on: marked transactions stay in the pending pool. Can they exhaust per-sender or global pool limits, so that a sender is refused new transactions (or other senders' are evicted) because of transactions that are already sealed? Can a client exploit that to pin pool space?
4. The nonce view: with the switch off the builder advances the pool's nonce optimistically at the ack; with it on nothing is advanced until execution. What does `eth_getTransactionCount(pending)` answer in between, and can a correct client be led to reuse a nonce?
5. The orphan pass clears marks on every pool before recovery runs. If recovery then fails partway, are the unmarked transactions safe to be selected again?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/sealed-keep-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-sealed-keep.md`
