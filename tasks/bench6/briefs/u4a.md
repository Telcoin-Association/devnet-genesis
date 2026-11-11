# U4a — recovery-pool (node unit, wave 1)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u4a` (branch `b6/u-u4a`, cut from the integration branch with U0a's switches and U0c's
plumbing in). Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u4a.md`.
Skills: `tn-rust-skills`, `tn-domain-execution`. Topic slug: `recovery-pool`. Refs #1805.

## Why
The engine recovers the signers of the NEXT output on a blocking job while it executes the current one; both use rayon's global
pool. In bench 5 (r20261107-1504), on validator-09, an output's `finish` lap cost 22.1 µs/tx when another output's recovery job
overlapped it against 7.8 µs/tx when none did (16.3 against 6.7 at window 16), with root and evm unchanged and a dose-response in
the overlapped share: execution lag feeds itself, because a lagging node always has a queued output whose recovery competes with
`finish`. A small dedicated pool for signer recovery removes the competition.

## Read
1. Node design §B topic 6: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md`.
2. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-3/verdict.md` §3 (the overlap measurement).
3. Code: `crates/engine/src/recovery.rs` (the job closure near :40-60 and the inline fallback near :115), where `recover_output_signers`
   / `recover_signers` use `par_iter` in `crates/tn-reth/src/env/execution.rs` (near :206-228; read-only), `crates/engine/src/lib.rs`
   (U0c added the `recovery_threads` setter/getter: read it), `crates/engine/src/metrics.rs`, the existing differential and
   recovery-fallback tests in `crates/engine/` (find them: they pin that reused signers give identical blocks).

## You own
`crates/engine/src/recovery.rs`, the recovery call sites in `crates/engine/src/lib.rs` (not its constructor plumbing, which is in),
`crates/engine/src/metrics.rs`, and their unit tests. Not `execution.rs`, not `payload_builder.rs`, not the bench file (`benches/
engine_contention.rs` is the next unit's; expose what it needs).

## Deliver (behind `recovery_threads`; 0 = today's global pool, byte-identical behaviour; N > 0 = a dedicated pool of N threads)
A process-wide `OnceLock<rayon::ThreadPool>` with threads named `tn-recover-{i}`, built on first use with the configured size; the
recovery job closure and the inline fallback run the signer recovery inside `pool.install(…)` so the `par_iter` inside uses that
pool; with 0 nothing is installed. A pool that fails to build falls back to the global pool with one warn line (never panics).
`signers recovered` gains `pool=dedicated|global`. Expose a small `pub` function the benchmark unit can call to run a recovery
closure on the dedicated pool of a given size (documented as bench/test support), so the bench exercises the real path.
Blocks must be byte-identical with the pool on or off: recovery only decides who computes the signers.

## Tests
The existing differential test (reused signers vs fresh) and the recovery-fallback tests run with `recovery_threads = 3` and give
identical results; the threads carry the `tn-recover-` name; `recovery_threads = 0` installs nothing; the `pool=` field appears with
the right value; building the pool twice returns the first.

## Gates and hand-back
As in the rules for the engine package (and `cargo check -p tn-node`); domain review (domains: execution). Hand-back: the pool's
API verbatim (the bench unit quotes it), the log field, tests, and whether anything else in the engine uses rayon's global pool on
the execute path (list the sites: the benchmark will ask whether root/finish want their own pool too).
