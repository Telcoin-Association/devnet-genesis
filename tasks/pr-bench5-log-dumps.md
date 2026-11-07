# Draft PR (telcoin-network) — topic `log-dumps` — not yet opened; evidence section to be filled from the bench-5 analysis (Wave D)

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

## Evidence (bench 5, run <R>)
(to be filled in Wave E from benchmark/private/bench5-<run>/{A1,A3,A4n,A6}: the fields named in tasks/checkpoint-bench5-design.md for this topic, with file cites; verdict confirmed / inconclusive / regressed)

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
