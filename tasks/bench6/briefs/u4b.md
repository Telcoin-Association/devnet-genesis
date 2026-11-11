# U4b — engine contention bench (node unit, wave 1; after U4a)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u7` — a finished unit's directory, reused for its warm engine build; the directory name
is NOT your unit's — branch `b6/u-u4b`, cut from the integration branch with the recovery pool in (aa71a50f8).
Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u4b.md`.
Skills: `tn-rust-skills`, `tn-domain-execution`. Topic slug: `recovery-pool`. Refs #1805.

## Why
In bench 5 (r20261107-1504) an output's `finish` lap cost 22.1 µs/tx when another output's signer-recovery job overlapped it and
7.8 µs/tx when none did (validator-09, window 4; 16.3 against 6.7 at window 16), with the state root and the EVM unchanged: both
`finish` and recovery use rayon's global pool. Unit U4a put recovery on a dedicated pool behind `recovery_threads`. This bench
measures, off the fleet, whether that removes the slowdown, and two things bench 5 could not separate: how much the cached reads
(E5) save, and how large the state root's share of execute is.

## Read
1. Node design, the paragraph "Parallel state root (design and Criterion only)" at the end of §B and topic 6:
   `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md` (it names the three
   groups and the pass criteria; where it says Criterion, read "a plain timed binary": see below).
2. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/briefs/u0c-api.md` (the bench target exists as a stub) and unit U4a's
   checkpoint `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u4a.md` (the pool's API:
   `tn_engine::run_on_recovery_pool(threads, closure)`; the pool is process-wide and its size is fixed by the first non-zero
   call, so one dedicated size per PROCESS; the list of rayon users on the execute path: two sites in `finish`, none in root).
3. The repo's one existing bench, your model for structure and style: `crates/tn-reth/benches/output_overlay.rs` and how
   `crates/tn-reth/Cargo.toml` declares it (`harness = false`, a hand-written `main`, `#![allow(unused_crate_dependencies)]`).
4. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-3/verdict.md` §2 and §3 (what the run could and could
   not say; your numbers go into its pending section).
5. Code: `crates/engine/src/{lib.rs,recovery.rs,payload_builder.rs}`, `crates/engine/tests/it/main.rs` (how tests build a reth env and
   a multi-block consensus output and execute it: reuse those helpers, do not invent a second fixture path),
   `crates/tn-reth/src/env/execution.rs` (the laps: recover, evm, root, finish; the cached-reads scope).

## You own
`crates/engine/benches/engine_contention.rs` (replace the stub). Nothing else. **Criterion is not a dependency of this workspace and
is not to be added** (nor any other bench framework): write a plain `harness = false` binary that times with `Instant`, repeats
each case enough times to report a median and a spread, and prints one machine-readable line per case. If a helper you need is
private to the engine or to tn-reth, do not widen an API for a bench: use what `test-utils` already exposes, and if that is not
enough, stop and say exactly which item is missing.

## Deliver
A bench binary with three groups, selectable by argument or environment (so one process runs one pool mode):
1. `finish_under_recovery/{global,dedicated}/{0,1,2}`: the `finish` lap per transaction of one output (aim for the design's shape:
   about 6,000 transactions in about 20 blocks, on a warmed temporary environment) while 0, 1 or 2 signer-recovery jobs of
   same-sized outputs run concurrently, on the global pool and on a dedicated pool of 3 threads. Because the dedicated pool is
   process-wide, the `global` and `dedicated` modes run in separate processes: say how to invoke each.
2. `cached_reads/{scoped,fresh}`: the same output executed with the output-scoped read cache and with a fresh cache per block
   (the E5 A/B), reporting execute µs/tx and the EVM lap. Only if the code offers both paths without an API change; otherwise
   report what would be needed and skip the group.
3. `root_share/{0,1,2}`: the state-root lap as a share of execute, with 0, 1, 2 concurrent recovery jobs (the root is
   single-threaded: the expectation is "unchanged", and the group documents it).
Output: one line per case, `BENCH <group>/<case> n=<runs> median_us_tx=<x> p10=<x> p90=<x> [lap fields…]`, plus a header with the
machine, the thread counts and the output shape. A `--quick` mode (a few hundred transactions, three runs) for a smoke run.
Pass criteria to print at the end (computed, not asserted): `finish` per tx at N = 1 and N = 2 within 15 % of N = 0 on the
dedicated pool; the global pool shows the slowdown (bench 5 saw roughly +8 to +15 µs/tx).

## Runs
The full bench is a heavy job that needs a CPU-quiet machine, and other units are compiling here: build it
(`cargo-slot.sh cargo bench --locked -p tn-engine --bench engine_contention --no-run`), run ONLY `--quick` in both pool modes to
prove it works, and hand back a runbook: the exact commands for the full run in each mode, the expected duration, what "quiet"
it needs (CPU only, or disk too). The orchestrator runs it and reads the numbers.

## Gates and hand-back
`cargo check --locked --all-targets -p tn-engine`, fmt, clippy for the engine package (the bench target included); domain review
(domains: execution) on the bench's method — ask the reviewer specifically whether each case measures what it claims (is the
concurrent recovery really overlapping the `finish` lap; is the warm-up enough; is anything timed that should not be). Commit:
one commit, `Topic: recovery-pool`, `Refs #1805`. Hand-back: how each group is built, the `--quick` output of both modes
verbatim, the runbook, what you could not measure and why.
