# Review scope — recovery-pool

Upstream issue: #1805. Switch: `recovery_threads` (count; default 0 = the global rayon pool as before; 3 in the benchmark).
Where: the checked-out branch `bench/bench6-2026-11`, head d91d65d3e. Size: 5 commits, +1642 lines (tests included). This group gets the code review only: skip the security evaluation unless the review turns up something that calls for it.

## Commits (the diff under review, in branch order)
- `11a1cae01` feat(config): add the recovery_threads switch
- `bd4bfe888` feat(engine): hand the recovery_threads switch to the executor engine
- `5da405afa` build(engine): add rayon, proptest and an engine_contention bench target
- `aa71a50f8` feat(engine): recover signers on a dedicated rayon pool behind recovery_threads
- `d0824a0a4` test(engine): bench finish, read cache and root share under recovery contention

## Files touched
- `Cargo.lock`
- `crates/config/src/node.rs`
- `crates/engine/Cargo.toml`
- `crates/engine/benches/engine_contention.rs`
- `crates/engine/src/lib.rs`
- `crates/engine/src/metrics.rs`
- `crates/engine/src/recovery.rs`
- `crates/engine/tests/it/main.rs`
- `crates/node/src/engine/inner.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table row and the `recovery-pool` rows.
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From I-3" and "From U4a" / "From U4b" (D36: no Criterion; the contention bench is a plain binary whose full run is still owed).
- Unit checkpoints `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u4a.md`, `…-u4b.md`.

## Questions specific to this topic (2g)
1. A dedicated rayon pool is created per engine: lifetime, thread count bounds (a huge value in the file), what happens if the pool cannot be built, and whether a panic in a recovery job can take the engine down differently than before.
2. Signer recovery results feed execution: any ordering or completeness difference between the dedicated pool and the global one?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/recovery-pool-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-recovery-pool.md`
