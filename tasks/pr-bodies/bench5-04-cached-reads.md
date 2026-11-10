## Summary

Keeps one read cache across the blocks of a consensus output, advanced from each block's bundle, so accounts and slots
that several batches touch are read once per output instead of once per block. Blocks, roots, receipts and bundles are
unchanged. This is the last of the four engine PRs for F2 (log dumps, execute split, signer reuse, cached reads), so it
closes that issue; the persist regression bench 5 found is tracked separately.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

Bench 4 (r20261105-0803) spent an estimated 5-12 µs/tx of execute time on overlay and MDBX reads, and every block of an
output started from an empty `CachedReads`, so senders and contracts shared by its batches were read again per block.
{{ISSUE:f2-execution-ceiling}} (item 5) has the bench-4 evidence and the case against sharing one revm `State` across
blocks.

## Fix

- {{SHA:420f8aef7}} `perf(tn-reth): keep one read cache across the blocks of a consensus output`: `OutputBuildScope` now
  carries the output's trie overlay and one read cache, advanced after each successful build from the block's bundle.
  Destroyed or info-less accounts are evicted, others take their code-less info and written slots, created accounts drop
  their other slots, and code and block hashes stay. The engine threads one scope per output; the bytes path uses a fresh
  cache.

## Testing

{{TESTING:04}}

Differential tests and two proptests pin identical blocks, roots, receipts and bundles.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- Inconclusive by construction: this change shipped with the log-dumps and signer-reuse changes. The combined execute
  drop (165 → 87 µs/tx, −78) sits at the top of the summed expectation (23-79), so the cache most likely contributed, but
  no field isolates it.
- No consensus-observable effect: blocks, roots and gas were byte-identical across the fleet (no fork, no `BogusSubdag`,
  0 DB errors, 0 panics in 11 node logs).
- A single-change arm (cache on and off on the same image) is how bench 6 can size it.
- The engine's ceiling did not rise: execute halved, but persist went from about 50 to 199 µs/tx through the MDBX commit
  fsync, with identical logical writes ({{ISSUE:persist-fsync-amplification}}).

Closes {{ISSUE:f2-execution-ceiling}}
Refs {{ISSUE:persist-fsync-amplification}}
