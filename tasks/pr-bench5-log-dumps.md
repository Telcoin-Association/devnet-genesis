# Draft PR (telcoin-network) — topic `log-dumps` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/log-dumps origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: log-dumps$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): a962b9876
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: Refs the bench-5 issue text tasks/issues/bench5-f2-execution-ceiling.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/log-dumps --title "<title>" --body-file <this file's body>

## Title
perf(engine): demote the engine debug dumps to trace

## Body (per-commit summary)
- a962b9876 `perf(engine): demote output, block and per-tx debug dumps to trace`
  Bench 4 ran the nodes at engine=debug and each unit log grew at 1.16 GB/min. Most of it was formatted on the
    executing thread inside execute_ms: `executing output` dumped the whole ConsensusOutput with its raw
    transaction bytes (~18.7 MB per line), `block executed` the whole ExecutedBlock (~716 kB per line), and three
    per-transaction EVM lines (~450 B each with the span fields) ran inside the transaction loop, an estimated
    15-50 us of the 165 us/tx execute cost. The struct dumps move to trace under `engine::dump`, the per-
    transaction lines to trace under `engine::evm`, and a shape-only `executing output` debug line keeps
    consensus_number, batches and txs. `output execution task finished`, `output executed` and `persisted output`
    are unchanged.

## Why (measured motivation)
See the issue text tasks/issues/bench5-f2-execution-ceiling.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- Unit-log rate on validator-01 under load: 5.05 MB/min at the headline blast (A4n), 10.8 MB/min at the 600 × 4 point (harness LOG_RATE) — bench 4 wrote 1,163 MB/min with the dumps at debug.
- The dumps' share of execution time (`other_ms`) is 0.2-0.3 µs/tx; execute fell from 165 to 87 µs/tx together with the signer-reuse and cached-reads changes.
- Eleven node logs now total 1.87 GB compressed for the whole run (bench 4: ≈ 49 GB per validator uncompressed); the teardown's log pull took 6 min instead of hours.

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
