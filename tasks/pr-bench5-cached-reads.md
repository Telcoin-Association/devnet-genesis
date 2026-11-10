# Draft PR (telcoin-network) — topic `cached-reads` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Opened as #1816 (2026-11-10): head `fix/1800-cached-reads` → base `staging/benchmark-obs-2026-11` (PR 5 of 10, stacked). Final body: tasks/pr-bodies/bench5-04-cached-reads.md.

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/cached-reads origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: cached-reads$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 420f8aef7
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: tasks/issues/bench5-f2-execution-ceiling.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/cached-reads --title "<title>" --body-file <this file's body>

## Title
perf(tn-reth): keep one read cache across the blocks of a consensus output

## Body (per-commit summary)
- 420f8aef7 `perf(tn-reth): keep one read cache across the blocks of a consensus output`
  Bench 4 spent an estimated 5-12 us/tx of execute time on overlay and MDBX reads, and every block of an output
    started from an empty CachedReads, so senders and contracts shared by its batches were read again per block.
    OutputBuildScope now carries the output's trie overlay and one read cache, advanced after each successful
    build from the block's bundle: destroyed or info-less accounts are evicted, others take their code-less info
    and written slots, created accounts drop their other slots, code and block hashes stay. The engine threads one
    scope per output, the bytes path a fresh cache; differential tests and two proptests pin identical blocks,
    roots, receipts and bundles.

## Why (measured motivation)
See the issue text tasks/issues/bench5-f2-execution-ceiling.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- Inconclusive by construction: E5 shipped with E1 and E4; the combined execute drop (165 → 87 µs/tx, −78) sits at the top of the summed expectation (23-79), so E5 most likely contributed, but no field isolates it.
- No consensus-observable effect: blocks, roots and gas were byte-identical across the fleet (no fork, no `BogusSubdag`, 0 DB errors, 0 panics in 11 node logs).
- A single-change arm (E5 on/off on the same image) is the bench-6 way to size it.

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
