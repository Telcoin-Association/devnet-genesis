## Summary

The batch builder wakes on transaction arrival. The first arrival at an idle builder arms a 40-ms fill delay, so a new
transaction no longer waits for the 250-ms `max_batch_delay` tick.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

An idle builder noticed a new transaction only on the 250-ms `max_batch_delay` tick or on a canonical update. Below
saturation the tick part of stage S1 (pool wait) in the bench-4 time-to-land baseline (r20261105-0803) was therefore up
to 125 ms on average.

## Fix

- {{SHA:716de9019}} `feat(batch-builder): wake on transaction arrival`: the builder listens to pool admissions
  (`WorkerTxPool::admitted_transactions`, made public). The first arrival at an idle builder arms a 40-ms fill delay so a
  burst lands in one batch (`wake=arrival`). An arrival never starts a second build, never extends the delay and never
  shortens a refusal backoff, and after a failed or empty build it arms nothing until the next tick or a mined batch, so
  retries keep the tick cadence. Expected: an S1 tick part of 25-50 ms below saturation and none at saturation. Worker
  invariants 1-5 (epoch, beneficiary, base fee, no blobs, bounds) are untouched.

## Testing

{{TESTING:08}}

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- S1 (pool wait) p50 was 26-31 ms at light load, with 66-76 % of batches built on `wake=arrival`; the bench-4 model had
  about 125 ms. That is worth about −0.07 to −0.10 s of time to land at light load and nothing at saturation, where the
  engine queue dominates. Small, but confirmed.
