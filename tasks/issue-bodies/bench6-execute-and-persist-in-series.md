# Execute and persist run in series, so off the disk's write limit the persist is part of the throughput ceiling

## Problem

The engine builds every block of a consensus output, persists them, and only then starts the next output.
While the disk binds, the commit carries its write limit either way; once it stops binding, the persist adds to every output's time.
In bench 6, at 50,000 provisioned IOPS, the fleet ran at its costliest engine's sequential capacity, and the persist was a third of each engine's busy time.

These figures are from bench 6's build: MDBX, storage layout v1.
Main's storage v2 (#1834) changes both halves, so the split must be re-measured on main; the next benchmark is to run main at 20,000 IOPS, and this issue will be updated with its split, though a run at 50,000 IOPS is what item 1 below needs.
The ask is a design discussion: whether and how a persist can overlap the next build on storage v2, whose parallel roots and output overlay assume it does not, and whose execution cache is cleared on a failed persist on the premise that the next build has not started.

## Evidence

[r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/) ran ten validators on Hyperdisk Balanced at 50,000 provisioned IOPS, under the two forms of the vote fix; [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) is the same build and load at 20,000 IOPS.
One run per configuration.
In every run no task began before the previous one ended.

| over the 40-minute blast, nine validators | r20261113-1351 (20,000 IOPS) | r20261113-1630 (50,000) | r20261114-0000 (50,000) |
|---|---:|---:|---:|
| execute, µs/tx | 90.2 | 87.7 | 89.6 |
| persist (save_blocks + commit), µs/tx | 95.2 (20.9 + 74.2) | 44.5 (21.9 + 22.4) | 42.5 (20.9 + 21.5) |
| task, with announce, µs/tx | 187.2 | 133.9 | 133.8 |
| transactions per output | 3,854 | 5,781 | 6,234 |
| executed tx/s per node | 5,314 | 7,287 | 7,210 |
| engine busy, ms/s | 994 | 975 | 965 |
| device writes, share of the limit | 0.998 | 0.497 | 0.480 |

- In r20261113-1630 validator-01, the costliest engine at 136.9 µs/tx, was busy 997 ms/s with a flat backlog of 14 to 18 outputs, and its capacity, 7,287 tx/s, was the fleet's executed rate.
  What held the input at validator-01's capacity was not measured.
- The persist took about 260 ms per output in r20261113-1630 and 268 ms in r20261114-0000.
  Half of it is save_blocks, which did not shrink with the faster disk (20.9 µs/tx at 20,000 IOPS, 21.9 at 50,000).
- Arithmetic, not runs: r20261113-1630's costs give 7,469 tx/s at full busy, against 7,287 measured, and 11,397 with the persist free.

Bench 6 also built a pipelined persist that commits output N while N+1 builds (`pipelined_persist` on `bench/bench6-2026-11` at `2df831e3c`).
In the arm walk r20261112-1520 (one fleet stepped through nine switch sets by rolling restart, 20,000 IOPS, no run page) its cycle was 1.010 to 1.072 times the longer stage, but the disk bound, and the pipeline's own arm regressed in throughput, through outputs half the size of the arm before; a build beside a commit cost 3 to 14 µs/tx more, an upper estimate.
On a quiet host with a lab database, whose build cost about 30 µs/tx, the build took 6 to 8 µs/tx longer pipelined than in sequence (1.22 to 1.26 times), and with execute the longer phase the overlap gained 10 to 11 % (one run on each of two CPU shapes, the two engines run one after the other).
It never ran at 50,000 IOPS.

## Where in the code (main at 45dce8947)

- `ExecutorEngine::run` (`crates/engine/src/lib.rs:279`) spawns an output's task only when none is pending (`:304-311`).
- The task builds every block, then persists in line (`crates/engine/src/payload_builder.rs:392-412`, `persist_output_with_retry` at `:401`), then announces and finalizes (`:415-421`).
  `output executed` (`:427-445`) logs `execute_ms`, `persist_ms` and `announce_ms`, so main's split reads from the same fields.
- The parallel roots and the output overlay rely on that order.
  Each parallel storage-root task reads through its own read-only transaction, and `crates/tn-reth/src/env/output_overlay/parallel.rs:63-82` names "a pipelined persist" as what would break it (`:74`).
  The output overlay is anchored at the database tip (`crates/tn-reth/src/env/output_overlay.rs:73-75`).
- The execution cache's failure rule assumes the next build has not started: a failed persist clears the cache, "so start the next build empty" (`crates/tn-reth/src/env/execution.rs:555-559`).

## What to discuss

1. Re-measure first: if on main the persist is a small share of the task at 50,000 IOPS, overlap buys little and this can close.
2. One snapshot for every reader of a build.
   Bench 6 pinned one read-only transaction before N's persist and layered N's blocks on it.
   Main's roots read on several threads, each through its own transaction, so all of them would need that snapshot; whether tn-lmdb can open several transactions at one snapshot is open.
3. Failure: a persist of N that fails after N+1 started must roll back both and stop the node, and the cache N+1 checked out, anchored on N's blocks, must go with them.
4. The pinned reader's cost: on tn-lmdb a reader held across a commit holds back page reuse (`crates/tn-lmdb/README.md:1602-1603`); on MDBX the arm walk saw no page cost above about 7 %.
5. Overlap lowers each engine's cost, which may widen or narrow the execution spread across validators that cost own-header certification at 50,000 IOPS (#1804); bench 6 did not measure it.

## How to verify

- On main, a loaded blast at 20,000 and at 50,000 IOPS, reading `output executed`, `tn_engine_busy_milliseconds_total` and the device's writes against its limit.
  The issue stands if the engine is busy near 1,000 ms/s with the device under its limit and the persist a material share of the task.
- For a design: blocks, receipts and roots byte-identical to the sequential engine in a differential test; `tn_reth.parallel_state_root_task_failures_total` and `tn_reth.parallel_state_root_mismatches_total` at 0; a kill between a build and the previous commit replays to the same chain; the interval per output within 1.1 times the longer of execute and persist.
