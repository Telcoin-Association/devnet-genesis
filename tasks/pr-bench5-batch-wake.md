# Draft PR (telcoin-network) — topic `batch-wake` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Opened as #1820 (2026-11-10): head `feat/batch-wake` → base `staging/benchmark-obs-2026-11` (PR 9 of 10, stacked). Final body: tasks/pr-bodies/bench5-08-batch-wake.md.

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/batch-wake origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: batch-wake$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 716de9019
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: tasks/bench5-land-time-baseline.md (lever S1).
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/batch-wake --title "<title>" --body-file <this file's body>

## Title
feat(batch-builder): wake on transaction arrival

## Body (per-commit summary)
- 716de9019 `feat(batch-builder): wake on transaction arrival`
  An idle builder noticed a new transaction only on the 250 ms max_batch_delay tick or a canonical update, so
    below saturation the I-3 baseline's S1 tick part was up to 125 ms on average. The builder now listens to pool
    admissions (WorkerTxPool::admitted_transactions, made public); the first arrival at an idle builder arms a 40
    ms fill delay so a burst lands in one batch (wake=arrival). An arrival never starts a second build, never
    extends the delay, never shortens a refusal backoff, and after a failed or empty build arms nothing until the
    next tick or a mined batch, so retries keep the tick cadence. Expected: S1 tick part 25-50 ms below
    saturation, none at saturation. Worker invariants 1-5 (epoch, beneficiary, base fee, no blobs, bounds) are
    untouched.

## Why (measured motivation)
See the issue text tasks/bench5-land-time-baseline.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- S1 (pool wait) p50 26-31 ms at light load with 66-76 % of batches built on `wake=arrival`; the bench-4 model had ≈ 125 ms. Worth ≈ −0.07…−0.10 s of time to land at light load; no effect at saturation (the queue dominates). Small but confirmed.

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
