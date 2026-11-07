# Bench 5 cherry-pick ledger — bench/main-fixes-2026-11 (telcoin-network)

Base: origin/main 4bf4604d2 (2026-11-06). Then the nine observability commits (cherry-picked -x from bench/main-v1lazy-obs-2026-11;
their PR text: tasks/pr-bench-observability.md), then the topic commits below. Every topic commit carries a `Topic: <slug>` footer, so
`git log --grep='^Topic: <slug>$' origin/main..bench/main-fixes-2026-11` is the index.

Recipe per topic: `git -C $TN fetch origin main && git switch -c fix/<slug> origin/main && git cherry-pick -x $(git log --reverse
--format=%h --grep='^Topic: <slug>$' origin/main..bench/main-fixes-2026-11)`. PR text: tasks/pr-bench5-<slug>.md (Wave E).

Verdicts (Wave D): confirmed = the bench-5 field in tasks/checkpoint-bench5-design.md moved as predicted; inconclusive = the field
could not be read or did not move; regressed = a KPI or a safety field got worse. Fill in from the A-unit outputs only, with cites.

## Observability (cherry-picked, not topic commits)
| sha | title | crates |
|---|---|---|
| 77539d77d | feat(network): label outbound request durations by service class and log request resolution | tn-network-libp2p |
| e938be258 | feat(primary): time the voter's vote path by stage and count vote outcomes | tn-primary |
| 49643180d | feat(primary): stamp proposer vote round trips, persist barrier and proposal lock | tn-primary |
| 4ab917aae | feat(engine): split execute, persist and commit timings and count engine busy time | tn-engine, tn-reth |
| 180a2d8c1 | feat(subscriber): log rejoin blockers and count node mode transitions with reasons | tn-executor, tn-primary, tn-node |
| c6e8df6dd | feat(primary): log the scheduled leader of every round and count leader outcomes | tn-primary |
| 2d47fe191 | feat(worker): count batch-serve denials and denied batch requests | tn-worker |
| f7936def8 | feat(epoch-manager): log missing epoch record signers and signer counts | tn-node |
| 3a721a1b6 | fix(observability): sub-millisecond stage buckets, quieter batch-sync lines and review follow-ups | several |

## Topic commits
| sha | topic | row | crates | upstream issue | PR title | depends on | bench-5 verdict | cherry-pick recipe |
|---|---|---|---|---|---|---|---|---|
| E1 a962b9876 (unit 69c9eba0d) | log-dumps | E1 | tn-engine, tn-reth | tasks/issues/bench5-f2-execution-ceiling.md | perf(engine): demote output, block and per-tx debug dumps to trace | — | — | recipe(log-dumps) |
| E2 3dc26fa59 (unit 988ca198e), E3 fac145464 (unit fa9a4ff55), L5 decc4cbc4 (unit 5105eda5a) | exec-split | E2, E3, L5 | tn-engine, tn-reth, tn-node | tasks/issues/bench5-f2-execution-ceiling.md | feat(engine): execute split, subscriber-to-engine hop timing, queued line | log-dumps | — | recipe(exec-split) |
| E4 9039198de (unit 928c12300) | signer-reuse | E4 | tn-engine, tn-reth | tasks/issues/bench5-f2-execution-ceiling.md | perf(engine): recover signers off the execution thread | exec-split | — | recipe(signer-reuse) |
| E5 420f8aef7 (unit 61234d989) | cached-reads | E5 | tn-reth | tasks/issues/bench5-f2-execution-ceiling.md | perf(tn-reth): one read cache per consensus output | signer-reuse | — | recipe(cached-reads) |
| F1-1 557c9b737 (unit f5324e6db), F1-2 a3a00525e (unit 3e4f0dd54), F1-3 d33ecb797 (unit de49fbb90), SEC1 9bad6966d (unit f53249c80; execution block by number+hash, three-way check, guard boundary), F1-3 sizing 6f9703662 (unit 317444cb9) | f1-commit-lag | F1-1, F1-2, F1-3 | tn-types, tn-primary, tn-executor, tn-engine, e2e-tests | #1781 #1782 + tasks/issues/bench5-f1-commit-lag-demotion.md | fix(primary): commit without waiting for execution | — | — | recipe(f1-commit-lag) |
| F3-0 746ac3272 (unit 5d7cbdc03), F3-2 0c41872ba (unit 48b969dd8), F3-5 bf34ec488 (unit 69f3891dc), F3-6 cae41a400 (unit 86a650d91), F3-3 f2f9437f7 (unit f61792797), F3-4 73d3163db (unit 324d3e5ad), F3-7 ae68877dc (unit 2e4e55dbf), SEC2 9840759a2 (unit 6eb90481d; stalled-head rejoin, failed-only cap, frontier fetch + gap re-request), halted-committee e2e 74a4e984e (unit 98c3b82c3) | f3-rejoin | F3-0, F3-2, F3-3, F3-4, F3-5, F3-6, F3-7 (F3-1a/1b DROPPED 2026-11-06 by I-4: conflict with #1516/PR 1547 and do not fix the observed failure) | tn-types, tn-storage, tn-config, tn-primary, tn-executor, tn-state-sync, e2e-tests | #1518 (F3-0) #1513 (F3-2) #1517 (F3-5; superseded by PR 1531 if it lands first) #1782 (F3-6) + tasks/issues/bench5-f3-rejoin-loop.md | fix: one rejoin per episode — keep the rounds a rejoiner rebuilds from, propose at the head, grace, attempt cap, refuse votes while inactive, bound the voter's exec wait | f1-commit-lag (F3-3 bus state) | — | recipe(f3-rejoin) |
| L1 dac760298 (unit ae8f0a130), L2 d660e8e7f (unit 5f6baf9a7), L4 44a87b0ef (unit 994755c1c), L3 c7764fac4 (unit dc09d7985) | land-path-obs | L1, L2, L3, L4 | tn-batch-builder, tn-worker, tn-primary, tn-executor, tn-state-sync, tn-storage | tasks/bench5-land-time-baseline.md | feat: time-to-land stage instrumentation | f1-commit-lag (L3 site) | — | recipe(land-path-obs) |
| L6 716de9019 (unit 2561e98ff) | batch-wake | L6 | tn-batch-builder | tasks/bench5-land-time-baseline.md | feat(batch-builder): wake on transaction arrival | land-path-obs | — | recipe(batch-wake) |
| L7 3304d94ce (unit 4364ec892) | cert-requeue | L7 | tn-primary | tasks/bench5-land-time-baseline.md | feat(primary): re-queue digests of cancelled headers | land-path-obs | — | recipe(cert-requeue) |
