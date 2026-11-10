## Summary

Splits the engine's per-output `execute_ms` into recover, evm, root and finish laps, times the hop from the subscriber to
the engine together with the channel depth, and logs a queued line plus consensus ids on executed blocks so every block
joins back to its output and batch. Timing and log fields only.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

Bench 4 (r20261105-0803) executed at 215 µs/tx, 165 of it in `execute_ms`. One number per output is too coarse to say
whether bench 6 should parallelise the state root.

Bench 4's `queue_wait` saw only the engine's own 8-slot queue. The 64-slot `to_engine` channel in front of it, where
outputs back up once execution falls behind, had no measurement.

The bench-5 land-path breakdown joins its stages on the consensus number and the batch digest, but the engine's side of
that join was incomplete: an output reaching the engine queue was not logged, and `next block executed` named only the
block hash and number. Its enclosing span carried `consensus_number`, but the offline join parses the explicit field.

{{ISSUE:f2-execution-ceiling}} (items 2 and 3) has the bench-4 evidence.

## Fix

- {{SHA:3dc26fa59}} `feat(engine): split execute_ms into recover/evm/root/finish per output`:
  `build_block_from_batch_payload_timed` returns the laps (the old call wraps it) and times the root inside the overlay
  root provider, as reth runs it in `finish`. `output executed` appends `txs`, the laps, `other_ms` and the slowest
  block's root and evm laps. `tn_engine_{recover,evm,root,finish}_seconds` are the only execute-only series
  (`execution_duration` times the whole task), and `tn_engine_executed_transactions_total` gives a per-transaction rate.
- {{SHA:fac145464}} `feat(engine): time the subscriber-to-engine hop and export channel depth`: `ConsensusOutput` gains a
  transient `forwarded_at` stamp (like `close_epoch`: never serialized, hashed or executed), set in `process_output` just
  before the one send to the engine. The engine records `tn_engine_forward_wait_seconds` when it takes an output off the
  channel, appends `forward_wait_ms` to `output execution task finished`, and samples the depth left behind into
  `tn_engine_channel_depth` on every arrival and completion. A field instead of an `(Instant, ConsensusOutput)` tuple
  leaves the 11 forwarding signatures and 22 test call sites untouched.
- {{SHA:decc4cbc4}} `feat(engine): queued line and consensus ids on executed blocks`: the engine logs `output queued` at
  debug with the consensus number and the queue depth after the push, and `next block executed` appends
  `consensus_number`, `batch_index` and `batch_digest`, so the queue and execute stages of every block join back to their
  output and batch. One line per output or block, never per transaction.

## Testing

{{TESTING:02}}

A test shows the timed wrapper is transparent and the build deterministic. Parity with the old loop rests on passing the
same `Recovered<T>` by value (no clone) and on the reth-oracle root test, run through the timed root provider. An engine
test captures the new lines and pins the field order of the engine's timing lines.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- The split is the F2 measurement. At saturation execute = 87.4 µs/tx = recover_wait 0.0 + evm 26.5 + root 49.2 + finish
  11.4 + other 0.2, and persist = 199.2 = save_blocks 21.1 + commit 178.0 (median of ten validators). 1 / (87.4 + 199.2)
  µs = 3,465 tx/s, within 0.5 % of the measured 3,449 tx/s.
- `root_ms` is 56 % of execute: the parallel state root is the next execute item (worth at most 49 µs/tx).
- `forward_wait_ms` and `tn_engine_channel_depth` showed that the suspected 64-slot backlog does not exist: channel depth
  stays at 2 or less and consensus commits at the execution rate (0.573 vs 0.559 outputs/s). The engine queue (cap 8)
  sits at its cap only on the three slowest executors.
- The same lines exposed the run's main surprise: the MDBX commit takes 1.03-1.06 s per output on every node (bench 4:
  0.30-0.34 s) with identical logical writes ({{ISSUE:persist-fsync-amplification}}).

Refs {{ISSUE:f2-execution-ceiling}}
Refs {{ISSUE:persist-fsync-amplification}}
