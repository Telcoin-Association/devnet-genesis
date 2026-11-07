# Draft PR (telcoin-network) — topic `cached-reads` — not yet opened; evidence section to be filled from the bench-5 analysis (Wave D)

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

## Evidence (bench 5, run <R>)
(to be filled in Wave E from benchmark/private/bench5-<run>/{A1,A3,A4n,A6}: the fields named in tasks/checkpoint-bench5-design.md for this topic, with file cites; verdict confirmed / inconclusive / regressed)

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
