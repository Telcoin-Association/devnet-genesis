## Summary

Recovers transaction signers in a blocking job that starts when an output is queued, so the execution task builds from
recovered transactions instead of recovering them inside every block build. Blocks are unchanged.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

Bench 4 (r20261105-0803) executed at 163-170 µs/tx with signer recovery inside every block build on the execution thread
(an estimated 3-17 µs/tx of wall time) while 2.8-5.2 outputs waited in the engine queue. {{ISSUE:f2-execution-ceiling}}
(item 4) has the bench-4 evidence.

## Fix

- {{SHA:9039198de}} `perf(engine): recover signers when an output is queued, off the execution thread`: a blocking job
  started when an output is queued runs `RethEnv::recover_output_signers` (one `Vec` per batch in `flatten_batches`
  order, the same drop-and-count semantics, `tx_len` logged instead of the bytes). The execution task builds from its
  result through `build_block_from_recovered_payload`, which the bytes path wraps. A job without a result falls back to
  inline recovery and counts `tn_engine_recovery_fallback_total`, never an error. `output executed` reports
  `recover_wait_ms` in place of `recover_ms`, and the job logs `signers recovered`.

## Testing

{{TESTING:03}}

Differential tests build the same output from bytes and from pre-recovered transactions and pin identical blocks.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- `recover_wait_ms` is 0.0-0.6 µs/tx at saturation: the recovery job (13-21 µs/tx of CPU) runs off the execute thread and
  finishes before the output is dequeued. Fallbacks: 0.
- At light load it is 12 µs/tx, as expected: an empty queue leaves nothing to recover ahead.
- Execute fell from 165 to 87 µs/tx across the log-dumps, signer-reuse and cached-reads changes together. One run cannot
  separate their shares (the summed expectation was 23-79 µs/tx; the measured drop is 78).
- Side effect: the job runs on the global rayon pool, which the block build's `finish` also uses. On a node whose
  execution lags, jobs land on top of an execute and `finish` rises from 10-12 to 17-19 µs/tx, which keeps the node
  behind. {{ISSUE:execution-lag-feedback}} traces this and proposes a dedicated recovery pool.

Refs {{ISSUE:f2-execution-ceiling}}
Refs {{ISSUE:execution-lag-feedback}}
