# Topic review: recovery-pool (#1805, switch `recovery_threads`)

Date: 2026-11-11
Code: `/home/drtnarg/coding/telcoin/telcoin-network-b6`, branch `bench/bench6-2026-11`, head `d91d65d3e` (read-only; no cargo run)
Diff: `git show --format= 11a1cae01 bd4bfe888 5da405afa aa71a50f8 d0824a0a4`
Mode: code review only (scope file). Security evaluation skipped; nothing found in the review calls for it (the change moves signer
recovery between rayon thread pools; it touches no wire message, no consensus-visible value and no new untrusted input).

## Verdict: APPROVE WITH FOLLOW-UPS

Nothing Critical, High or Medium. No node code has to change before the benchmark image. One harness check is recommended before
the run (F2). Two small cleanups belong to the upstream PR (F1, F3). With the switch at 0 the code takes the previous path
(the `pool=global` log field and the switch gauge are the only additions), and a mixed fleet cannot fork or stall from this
switch, because recovered signers never leave the node and are identical on either pool.

Method note: the `tn-review` skill's Phase 3 hands findings to a `findings-verifier` agent. No agent-spawning tool was
available in this run, so each finding was re-checked by reading the cited lines directly and trying to disprove it. One
candidate was dropped that way (see 2c). Status CONFIRMED means re-read and the scenario holds as written; PLAUSIBLE means the
mechanism holds but its size depends on the host.

## Findings (most severe first)

### F1. `proptest` is added as a dev-dependency and nothing uses it — Low, CONFIRMED
- Where: `crates/engine/Cargo.toml:40`; `Cargo.lock` (tn-engine deps, +`"proptest"`), commit `5da405afa`.
- Scenario: the commit message says "its tests need a property-test crate", but no file under `crates/engine/` mentions
  `proptest` (grep at head; `git log -S proptest -- crates/engine/src crates/engine/tests` is empty). The crate's
  `#![allow(unused_crate_dependencies)]` (`crates/engine/src/lib.rs:21`, older than this topic) and the it-binary's
  (`crates/engine/tests/it/main.rs:5`) hide the lint, so nothing flags it. An upstream reviewer sees an unexplained new
  edge in the lockfile.
- Fix: drop the `proptest` line from `[dev-dependencies]` and its Cargo.lock entry, or add the property test it was meant for
  (signers from the dedicated pool equal the global pool's for random outputs).
- When: before the upstream PR. It does not affect the node binary or the image.

### F2. The harness cannot tell a POOL arm whose pool failed to build from one that ran on it — Low, CONFIRMED
- Where: `crates/engine/src/recovery.rs:220-251` (failed build → `None`, one warn, global pool for the process lifetime);
  `crates/config/src/node.rs:737` (the switch gauge renders the configured value); harness
  `benchmark/tools/arms-summary.py` (no recovery-pool check), `benchmark/tools/stage-latency.py` (reads `recover_ms` but not `pool`).
- Scenario: a node starts with `recovery_threads: 3`; its first non-empty output's job calls `build_recovery_pool`, which fails
  (thread spawn refused); `pool_or_warn` logs `signer recovery pool failed to build - recovering on the global pool` once and
  stores `None`; from then on every `signers recovered` line says `pool=global`, while `node switches` and
  `tn_node_switch{name="recovery_threads"}` still say 3. The arm summary counts that node as POOL and the comparison is diluted.
  The fallback itself is a known residual; what isn't listed is that the arm would be misclassified. For 3 threads a failed
  build is unlikely, so the risk is to the analysis, not the run.
- Fix (harness, no image change): do for this switch what `arms-summary.py:1009-1031` already does for `mdbx_random_advice`. Mark a
  node's POOL arm in force only if the arm window has no `signer recovery pool failed to build` warning and its `signers recovered`
  lines say `pool=dedicated`.
- When: before the benchmark run (harness side).

### F3. Two doc comments outside the topic's files still say recovery runs on the global pool — Info, CONFIRMED
- Where: `crates/engine/src/payload_builder.rs:70-72` ("jobs start together and share the global rayon pool");
  `crates/tn-reth/src/env/execution.rs:216-218` ("recovered in parallel on the global rayon pool").
- Both are true only at `recovery_threads: 0`. U4a's checkpoint flagged them as open for the orchestrator; they are still open at head.
- Fix: one clause each ("... on the global rayon pool, or on the dedicated pool when `recovery_threads` is above zero").
- When: before the upstream PR.

### F4. Bench: on the dedicated pool, the saturation cases' pass band also measures CPU share — Info, PLAUSIBLE
- Where: `crates/engine/benches/engine_contention.rs:110` (`PASS_BAND` 0.15), `:974-985` (dedicated CRITERION), `:915-925`
  (`oversubscribed` printed only on `root_share` lines).
- Scenario: in `--pool dedicated` cases `1` and `2` (loop), three `tn-recover` threads stay busy for the whole build while the
  build's `finish` runs its parallel parts on the global pool (as many threads as cores). The two pools no longer share rayon
  threads but do share cores, so `finish` can rise past 15 % from the scheduler's share alone and print `result=fail` while the
  isolation works. The metrics doc says the same (`crates/engine/src/metrics.rs:68`: "still share CPU cores").
  The `_once` cases, which match the engine's one job per queued output, are not affected in the same way.
- Fix: none required. Optionally print `oversubscribed` on the `finish_under_recovery` lines as well, and read the dedicated
  loop-case result against the header's `cpus` and `rayon_global_threads`.
- When: neither; it only affects how the full run is read (that run is still owed, D36).

Counts: Critical 0, High 0, Medium 0, Low 2, Info 2.

## Bench binary (`engine_contention.rs`): does it time what it says?
Yes. The timed window is the block loop only (`:526-566`), with the output's own recovery before it (`:478-481`) and persist after
it (`:502-504`). The `finish` lap comes from tn-reth's own `BlockBuildTimings` (`crates/tn-reth/src/env/execution.rs:354-389`):
`builder.finish` less the root lap, plus the `rayon::join` sorts at `:374`, which are exactly the two global-pool sites U4a
identified. The root lap is single-threaded on the bench thread. Jobs are plain threads calling `run_on_recovery_pool`
(`:682-697`), started behind a barrier before the window and stopped after it (`:483-485`). Before measuring, the bench checks
that recovery really runs on the pool it reports (`:173-181`, an `ensure!` on the thread name). Case order rotates per round
against drift (`:774`), and every executed transaction is counted (`:489-496`). Caveats: F4, and `execute_us_tx` includes the
in-memory chain updates but not the engine's per-block telemetry, as the module doc says (`:9-13`).

## Answers to 2a-2g

**2a. Switch off = before.** Yes. At `recovery_threads: 0` (default `crates/config/src/node.rs:392-393`, `:569`), the node hands
0 to the engine (`crates/node/src/engine/inner.rs:572`; a field store), the engine passes 0 into every job
(`crates/engine/src/lib.rs:325-330`), and the job (`recovery.rs:61-62` → `:255-265`), the fallback (`:89`) and the no-job path
(`:153-155`, called from `payload_builder.rs:273`) all reach `recover_signers_on(.., 0)` → `install(0, ..)` (`:178`, `:207-211`)
→ `recovery_pool(0)` returns `None` at `:221-223` before touching `RECOVERY_POOL`, so `op()` runs on the calling thread exactly
as `RethEnv::recover_output_signers(output)` did before. No pool is built and no thread is created. Lines that run with the
switch off and did not run before: (1) the `pool=global` field on `signers recovered` (`recovery.rs:187`), log only;
(2) the `recovery_threads` entry in `switches()` (`node.rs:737`), which feeds the `node switches` line and the
`tn_node_switch{name="recovery_threads"}` gauge (= 0), observability only; (3) the `threads: u16` field carried in
`RecoveryHandle` (`recovery.rs:42`) and in `ExecutorEngine` (`lib.rs:121`), plus the `match`/tuple in `install`. rayon becomes a direct
dependency of tn-engine at the version tn-reth already links (1.11.0; Cargo.lock adds only names). None of these can change
behaviour.

**2b. Mixed fleet.** No fork, rejection or stall. Recovered signers stay inside the node: they feed only the local block build
(`payload_builder.rs:271-286`). The pool decides which threads compute them, not what is computed. Both collects keep input
order whatever the pool: an indexed `par_iter().enumerate().map().collect()` (`execution.rs:229-238`) and
`par_iter().filter_map().collect()` (`execution.rs:898-912`). Headers, votes, certificates and batches are untouched. The only
cross-node effect is how fast this node executes, the same kind of variation load already causes.

**2c. Liveness.** Nothing new is dropped or left without bound. Each job runs to completion: an `install` from outside the
pool injects the job and blocks on a `LockLatch` (rayon-core 1.13.0 `registry.rs:520-538`), and every injected job is eventually
popped (`find_work`: local, then steal, then injector, `registry.rs:833-842`). The pool is built inside the blocking job
(`recovery.rs:61-64` → `:224`), never on the engine's async loop. Concurrent first callers wait on the `OnceLock` until the
build ends, a bounded one-time wait. No deadlock: the work inside the pool never waits on the engine or on another pool,
and nested `par_iter` on one pool (even with one thread) runs inline. The fallback still recovers inline, now on the same pool,
behind at most the jobs already queued there. Dropped candidate: "the first output after a burst waits longer on 3 threads".
Under rayon's order each of the 3 workers takes a different output's top-level job, so output 1 gets about one thread's worth
of recovery, as it did when 8 jobs shared an N-thread global pool. Its wait is about the same, and later outputs are ready
long before execution reaches them (bench 5: recovery 13-21 µs/tx against an engine task of 250-289 µs/tx). Leftover jobs
after an epoch close are the known residual.

**2d. Byzantine or slow peers.** Nothing new. A faulty proposer can still certify batches whose bytes are expensive or
impossible to recover. The cost is the same work as before, now limited to `recovery_threads` rayon threads, which keeps it
off the build's rayon threads (an improvement). Its wall time on 3 threads can be up to about N/3 times longer than on an
N-thread pool, which is bounded by batch size and the transaction count per output, and stays well under that output's own
execution time.

**2e. Restart and epoch boundary.** The only new state is the process-wide `static RECOVERY_POOL: OnceLock<Option<ThreadPool>>`
(`recovery.rs:202`). It survives epoch changes (one engine per process, `manager/node.rs:915-923`), is never dropped (its
threads idle on rayon's sleep), and disappears at restart, to be rebuilt on the first output with batches. Its size is fixed by the
first non-zero request (`:217-219`, test `:648`). A failed build's `None` sticks for the rest of the process, with no retry
(`:199-202`, documented; see F2). Per-output `RecoveryHandle`s keep their old lifecycle: dropped at shutdown or epoch close, the job
runs to completion and its send fails silently (`:262-264`). Nothing is persisted.

**2f. Determinism.** Nothing consensus-visible depends on the pool. The same function runs with the same order-preserving collects
(2b). Wall-clock time appears only in `recover_ms` and the histogram. Thread timing affects only the order of the per-transaction
`failed to recover signer` error lines and when the signers are ready. Pinned by `test_queued_recovery_on_dedicated_pool_matches_inline_recovery`
(`crates/engine/tests/it/main.rs:5053`; block-for-block equality including state and receipts roots) and
`test_dedicated_pool_job_matches_global_recovery` (`recovery.rs:554`).

**2g.1 Pool lifetime, bounds, build failure, panics.** Lifetime: process static, built lazily (2e). Bounds: `u16`, so 1..=65535;
rayon-core 1.13.0 caps a pool at `THREADS_MAX` = 65535 on 64-bit (`sleep/counters.rs:57,77`; `registry.rs:246`), so no value
is silently cut. A huge value either builds that many idle threads or fails a spawn (`registry.rs:313-314`). In the latter
case the `Terminator` guard (`registry.rs:230-236`, `:283`) shuts down the threads already started, and the node warns and
uses the global pool (the "no cap" residual is known and not worse than stated). Build failure: one warning, global pool for
the process lifetime, never a panic (`recovery.rs:237-251`, test `:659`). Panics: rayon catches a panic on the pool worker and
resumes it on the thread that called `install` (`thread_pool/mod.rs:117`; `registry.rs:538` `into_result`). The job thread
unwinds as before, the handle's sender drops, `wait` warns and recovers inline (`recovery.rs:79-89`). A deterministic panic
then resumes on the execution thread, the pending task's sender drops and `run` returns the error (`lib.rs:449`), the same
chain as on the global pool. The worker thread survives. Rayon's abort-on-panic handler applies only to `spawn`ed jobs, which
this code does not use.

**2g.2 Ordering and completeness vs the global pool.** Identical: same function, same ordered collects, the same transactions
dropped from the same bytes. The engine still checks the length before the first block (`payload_builder.rs:276-281`). Tests: 2f.

## Not examined
- The security evaluation (`tn-security-eval`), skipped per the scope file; the review gave no reason to run it.
- Other topics' code, beyond the run loop, `configure_engine` and the tn-reth recovery and `finish` paths this topic calls.
- Any build or test execution (read-only brief). Gate results are taken from U4a/U4b's checkpoints as reported, not re-run.
- The full `engine_contention` run (owed, D36) and its numbers; tokio blocking-pool sizing; rayon internals beyond the
  functions cited.
