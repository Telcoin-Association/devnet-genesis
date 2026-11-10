## Summary

Moves the engine's struct dumps and per-transaction EVM lines from debug to trace. An `engine=debug` filter keeps the
three engine timing lines and no longer formats whole outputs and blocks on the execution thread.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

Bench 4 (r20261105-0803) ran the nodes at `engine=debug`, and each unit log grew at 1.16 GB/min. Most of it was
formatted on the executing thread inside `execute_ms`: `executing output` dumped the whole `ConsensusOutput` with its raw
transaction bytes (about 18.7 MB per line), `block executed` the whole `ExecutedBlock` (about 716 kB per line), and three
per-transaction EVM lines (about 450 B each with the span fields) ran inside the transaction loop, an estimated 15-50 µs
of the 165 µs/tx execute cost. {{ISSUE:f2-execution-ceiling}} (item 1) has the bench-4 evidence with log cites.

## Fix

- {{SHA:a962b9876}} `perf(engine): demote output, block and per-tx debug dumps to trace`: the struct dumps move to trace
  under `engine::dump`, the per-transaction lines to trace under `engine::evm`, and a shape-only `executing output` debug
  line keeps `consensus_number`, `batches` and `txs`. `output execution task finished`, `output executed` and `persisted
  output` are unchanged.

## Testing

{{TESTING:01}}

Log levels only, so no new tests.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- Unit-log rate on validator-01 under load: 5.05 MB/min at the headline blast and 10.8 MB/min at the 600 × 4 point (the
  harness's `LOG_RATE`). Bench 4 wrote 1,163 MB/min with the dumps at debug.
- The dumps' share of execution time (`other_ms`) is 0.2-0.3 µs/tx. Execute fell from 165 to 87 µs/tx together with the
  signer-reuse and cached-reads changes later in this stack.
- The eleven node logs total 1.87 GB compressed for the whole run (bench 4: about 49 GB per validator uncompressed), and
  the teardown's log pull took 6 min instead of hours.

Refs {{ISSUE:f2-execution-ceiling}}
