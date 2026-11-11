# U4b engine_contention: full-run runbook

The binary is a plain `harness = false` bench in `crates/engine/benches/engine_contention.rs` (branch b6/u-u4b).
Run each pool mode in its own process: the dedicated recovery pool is process-wide and sized once.

## Quiet

- CPU-quiet: required. No cargo builds, e2e or other benches on the host while it runs. The global-pool cases saturate every core the process can see, and the single-threaded root and evm laps move with SMT and frequency contention.
- Disk: not on the timed path. Each output is persisted after its window, and the temp DB is small (estimate under 1 GB for the full run), so ordinary disk activity is fine. Avoid memory pressure that could evict the DB's pages (the root lap reads MDBX through the page cache).

## Commands

From the worktree (build once through the slot wrapper; running the binary is not a compile, so it needs no slot):

```bash
cd /home/drtnarg/coding/telcoin/tn-b6-u7
export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates"
mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"
/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh \
  cargo bench --locked -p tn-engine --bench engine_contention --no-run 2>&1 | grep Executable
BIN=target/release/deps/engine_contention-ddde923d95939745   # the path the line above prints
OUT=/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/work/bench6-scratch/u4b
mkdir -p "$OUT"

# fleet shape (validators are c3-highcpu-8: 4 cores x 2 threads); on xerxes cpu i and i+8 are siblings
taskset -c 0-3,8-11 "$BIN" --pool global    > "$OUT/engine-contention-global-c8.txt"
taskset -c 0-3,8-11 "$BIN" --pool dedicated > "$OUT/engine-contention-dedicated-c8.txt"

# optional: the whole host (16 threads) for comparison
"$BIN" --pool global    > "$OUT/engine-contention-global-c16.txt"
"$BIN" --pool dedicated > "$OUT/engine-contention-dedicated-c16.txt"
```

The rayon global pool sizes itself from the process affinity, so `taskset` alone gives an 8-thread global pool; the header line prints `cpus=` and `rayon_global_threads=` to confirm it.
Progress lines go to stderr; stdout holds only the `#` header, `BENCH` and `CRITERION` lines.

## Shape and duration

Full defaults: 6,000 transfers in 20 blocks per output, 2 warm-up rounds discarded, 20 measured rounds.
Per process: 2 seed outputs + 22 rounds x 5 contention cases + 22 rounds x 4 read-cache arms = 200 outputs (1.2 M transactions).
Estimate 5-10 min per process on a quiet host (the global loop cases are the slow ones), about 20-40 min for all four runs.
This is an estimate from the `--quick` runs (about 15 k transactions in 1-2 s); no full-shape run was made.
Override with `--runs`, `--warmup`, `--txs`, `--blocks`, `--reuse`, or narrow with `--groups finish_under_recovery,root_share,cached_reads`.

## Reading the numbers

- `finish_under_recovery/<pool>/{0,1,2}`: jobs recover back to back for the whole build (the saturation bound).
  `{1,2}_once`: one recovery per job from the start of the build, as the engine's job per queued output; `job_overlap` is the share of the build one job was busy.
- Pass (dedicated process): `CRITERION finish_under_recovery pool=dedicated ... result=pass` for cases 1 and 2 (and the `_once` cases).
- Slowdown (global process): `slowdown=yes` on the loop cases; compare `delta_us_tx` with bench 5's +8..+15 only on the `_once` lines (`in_bench5_range`), and set `job_overlap` against bench 5's overlap quartiles (verdict §3a: 0-0.11 -> 14.4, 0.11-0.21 -> 21.4, 0.21-0.96 -> 28.4 us/tx against 7.8 clean).
- `root_share`: `oversubscribed=yes` (global loop cases) means the build thread shares the cores with a saturated pool, so a root rise there is time-slicing, not rayon inside the root.
- `cached_reads`: `scoped`/`fresh` give each transaction its own sender (only the recipient and system contracts recur); `*_reuse4` has every sender send in 4 blocks of each output. The saving is the median of per-round paired fresh-minus-scoped differences.
- Results go into `benchmark/private/bench6-prep/I-3/verdict.md` §3b (pending section) and §2.
