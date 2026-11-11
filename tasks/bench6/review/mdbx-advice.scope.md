# Review scope — mdbx-advice

Upstream issue: #1802 (and #1800). Switch: `mdbx_random_advice` (bool; default false).
Where: the checked-out branch `bench/bench6-2026-11`, head dc7855cc6. Size: 4 commits, +1398 lines (tests included).

## Commits (the diff under review, in branch order)
- `de08ef7f1` feat(config): add the mdbx_random_advice switch
- `f22362090` feat(reth): hand the mdbx_random_advice switch to RethEnv
- `dddccd4a6` feat(reth): whole-map MADV_RANDOM for mdbx.dat and per-persist storage counters
- `dc7855cc6` test(reth): open the re-open tests' datadir on one fixed genesis time

## Files touched
- `Cargo.lock`
- `crates/config/src/node.rs`
- `crates/node/src/manager/node.rs`
- `crates/tn-reth/Cargo.toml`
- `crates/tn-reth/src/env/execution.rs`
- `crates/tn-reth/src/env/mdbx_advice.rs`
- `crates/tn-reth/src/env/mod.rs`
- `crates/tn-reth/src/metrics.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table row and the three `mdbx-advice` rows under "Node log lines and metrics" (the fields added to `persisted output`, the gauges, the page-operation counter, which fields are left off).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, section "From U3" (as built; D17: a prefault-off switch is NOT built) and the I-1 / I-1r sections (what the local probe showed and did not show).
- The issue body `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/bench5-persist-fsync-amplification.md` and the investigation verdicts `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-1/verdict.md`, `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-1r/verdict.md`.
- Unit checkpoint `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u3.md`.

## Questions specific to this topic (2g)
1. The one `unsafe` block (the `madvise` call in `crates/tn-reth/src/env/mdbx_advice.rs`): is the address range always a live mapping of this process for the whole call, including while libmdbx remaps or grows the map on another thread? What does the code do if the mapping set changes between reading `/proc/self/maps` and the call?
2. The file identity is taken from the maps line that holds the address of a record read in a short read transaction. Can that pick a mapping of a DIFFERENT file (another MDBX environment in the process, a static file, a second env of the same path)? What if the process has several environments?
3. Failure handling: every `/proc` read and the advice itself can fail (permissions, a container without `/proc`, a non-Linux build). Confirm that no failure can fail the database open, block a persist, or panic; and that the non-Linux build compiles the feature out.
4. The per-persist counters run on the persist path of every node, switch on or off (about 115 µs measured). Is anything in that path able to block (a read transaction that waits, a `/proc` read on a process with thousands of threads) or to fail the persist?
5. The standing operational rule of this program is that nothing but the node opens a live node's database. Does this change itself open a second handle or transaction that could alter libmdbx's read-ahead or prefault state?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/mdbx-advice-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-mdbx-advice.md`
