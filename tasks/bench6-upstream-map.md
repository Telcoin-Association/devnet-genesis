# Bench 6 — upstream map (kept current by the orchestrator; re-checked before W8)

State 2026-11-10T23:20Z (`gh pr list`, `git ls-remote`): main 9aa1d6139. Staging `staging/benchmark-obs-2026-11` 514bf6687
(ten bench-5 PRs #1811-#1814, #1816-#1821 MERGED into it) → PR #1826 into main (REVIEW_REQUIRED, mergeable, attested).
Review follow-ups `fix/benchmark-obs-review-followups` 165e3fe01 → PR #1827 into main (REVIEW_REQUIRED, mergeable, attested);
after #1826 squash-merges, #1827 needs main merged in and a new attest (the user's). Bench-6 base = 165e3fe01.
Other open: #1808 (#1790 fix, APPROVED, unattested) + #1825 follow-up on `staging/review-followups-2026-11`; #1759 tn-lmdb
(sstanfield); `staging/mavenrain-2026-11-09` 8b6ff805b with #1810, #1815, #1822, #1823 (+ #1779 landed there, not on main);
#1531, #1547 (inactive CVV); #1154, #1376 (edit `txn_pool.rs` / `batch.rs`).

| our item | topic | upstream | relation | consequence |
|---|---|---|---|---|
| #1804 design D + V | quorum-exec-block, voter-lock | #1782 (voter wait); PRs #1822, #1823, #1531, #1547, #1779 edit `handler.rs` | near-duplicate on the voter side; file conflicts | cite #1782; re-check the conflict surface before W8 |
| #1802 MDBX advice | mdbx-advice | PR #1759 tn-lmdb; vendor DECISIONS D10 assigns MDBX changes to that work | overlaps, may supersede | bench image: our choice (Rust-side, no vendored edit); upstream PR only after sstanfield agrees (G4); cross-link #1802 ↔ #1759 |
| #1803 parent grace | parent-grace | #1781 variant 2 (same proposal); #1779 (verify-before-forward certificate gossip, on `staging/mavenrain-2026-11-09`, not on main) | duplicate proposal; confound | grace arms measured inside one image; #1779 is NOT in the base (165e3fe01 descends from main only) |
| #1805 recovery pool | recovery-pool | #376 (closed), #1795 / PR #1810 | overlaps | cite |
| pipelined persist | pipelined-persist | PR #1759 (edits `execution.rs`, own persist bench and histograms), #1618, #1575 | conflicts | keep the topic self-contained; expect a rebase |
| in-flight bound | inflight-bound | PR #1815 (500-batch per-reporter quota), #1575, #1553 | interacts | #1815 is NOT in the base; watch `batch_reports_over_quota_total` only if it lands |
| #1806 epoch drain | tracker-drain | #1212, #1213, #1793 (merged, in the base), #1618 | overlaps | cite; boundary baseline differs from bench 5 (record it in run 1's control arm) |
| #1807 sealed tx | sealed-keep, digest-dedupe | #1329 (closed), #415, #1259, #1616; PRs #1154, #1376 | partial overlap; file conflicts | cite #1329 as the pattern |
| F3 #1801 | (bench 5) | PR #1531 (#1517), PR #1547 (#1516), #1513 closed via #1550 | overlaps | #1801 should say it is what remains after #1550 |
| #1790 | (base) | PR #1808 (approved, unattested) + #1825; adiri builds only | open, NOT in the base | the bench image is a `faucet` build: verify with the image probe and the local 4-node smoke; include #1808 if it has landed by the image cut |

Convention for W8: `staging/benchmark-bench6-2026-11` off main once #1826 and #1827 are in main (from the bench-5 staging tip
otherwise); stacked topic PRs merged with merge commits; assignee grantkee; reviewers MavenRain + sstanfield (Huwonk via CODEOWNERS).
