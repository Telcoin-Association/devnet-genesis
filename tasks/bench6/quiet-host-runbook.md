# Quiet-host jobs (orchestrator only) — run when no agent is compiling or running tests

Check first: `pgrep -af 'cargo|rustc|nextest' | grep -v sccache | head` prints nothing and `uptime` shows a load average under 1.
Hold the window for other sessions with `touch tasks/bench6/QUIET` (the slot wrapper waits while it exists) and remove it after.
None of these may run while an e2e test, a harness gate or another job of this list runs. Order: 1, 2, 3 (3 is the longest).

## 1. Engine contention bench (U4b; I-3 verdict §3b; about 20-40 min for four processes)
Full instructions: `tasks/bench6/u4b-engine-contention-runbook.md`. Binary: `/home/drtnarg/coding/telcoin/tn-b6-u7/target/release/deps/engine_contention-ddde923d95939745`
(built at e3f6c4ba3; if it is gone: `cargo bench --locked -p tn-engine --bench engine_contention --no-run` through the slot wrapper in that worktree).
Canonical shape: `taskset -c 0-3,8-11` (the fleet's 4 cores × 2 threads). Output → `benchmark/work/bench6-scratch/u4b/`.

## 2. Pipelined-persist cycle bench (ST-U12c; go/no-go gate 5; about 1 min per invocation)
Binary: `/home/drtnarg/coding/telcoin/tn-b6-u0a/target/release/deps/it-15c921466125b44f` (built at c6e207b15; rebuild outside the window with
`cargo test --locked --release -p tn-engine --test it --no-run` through the slot wrapper, env `CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates"`).
```
cd /home/drtnarg/coding/telcoin/tn-b6-u0a/crates/engine
BIN=../../target/release/deps/it-15c921466125b44f
T="--ignored --exact persist_pipeline::bench_pipeline_cycle_vs_max_phase --nocapture --test-threads 1"
OUT=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/work/bench6-scratch/st-u12c; mkdir -p "$OUT"
export TMPDIR=/home/drtnarg/coding/telcoin/tn-b6-u0a/target/tmp
taskset -c 0-3,8-11 $BIN $T > "$OUT/cycle-pinned.txt" 2>&1        # execute-bound on a lab database
$BIN $T > "$OUT/cycle-unpinned.txt" 2>&1
# persist-bound, bench 5's ratio: D = 2.44 × execute_ms − persist_ms from the unforced pinned run
PIPELINE_CYCLE_PERSIST_DELAY_MS=<D> taskset -c 0-3,8-11 $BIN $T > "$OUT/cycle-pinned-persist-bound.txt" 2>&1
PIPELINE_CYCLE_PERSIST_DELAY_MS=<D> $BIN $T > "$OUT/cycle-unpinned-persist-bound.txt" 2>&1
grep -ho 'BENCH pipeline_cycle.*\|NOTE pipeline_cycle.*\|# pipeline_cycle.*' "$OUT"/cycle-*.txt
```
Gate 5 = `pass=true` (interval ≤ 1.1 × max(execute, persist)) in all four AND `overlapped` > 0. Read `persist_stretch` and `execute_stretch` from the
UNFORCED runs (the forced delay is a sleep and dilutes the ratio). A lab database cannot show whole-folio writeback: the devnet's `persisted output` fields do.

## 3. Full harness gate (H8; about 30-45 min)
`cd /home/drtnarg/coding/telcoin/devnet-genesis && bash benchmark/tests/gate.sh --jobs 4` — it refuses a loaded host by itself. Last line:
`GATE unittest=<rc> isolated=<…> mutations=<rc> load=<quiet|loaded> secs=<n>`. 333 mutation cases as of 4356229 (more after H14a-c).

## 4. Per-commit strict check of the node branch (W3; hours)
Every commit of `165e3fe01..<integration head>` compiles alone (`cargo check --locked --all-targets --workspace`), in a spare worktree, through
the slot wrapper. Not time-critical for the image (it is built from the head); required before the upstream stack (W8).
