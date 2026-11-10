## Summary

When a newer own header cancels a header's votes, the proposer moves that header's batch digests to the front of its
queue at once, instead of waiting for a later own commit to re-queue them. The cancelled header is not signed or sent
again.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

A header whose votes a newer own header cancelled can never be certified, yet its batch digests waited for a later own
commit to re-queue them, a fallback of 20-45 s. Bench 4 (r20261105-0803) put Seoul at 31.5 % uncertified own headers
under load, and far validators left 70 % of their idle certificates uncommitted.

## Fix

- {{SHA:3304d94ce}} `feat(primary): re-queue digests of cancelled headers`: the certifier reports such a header on a
  bounded `uncertified_own_headers` queue (`try_send`; a full queue drops the report) where `new_proposal` ends its
  proposal. It never reports after no certificate formed, nor a header with a stored certificate. The proposer moves the
  header's digests to the front of the queue. The header is not signed or sent again, and only a header below the
  proposer's round moves. `digests resent` gains `cause=`, and `tn_primary_digests_requeued_total{cause}` counts digests.

## Testing

{{TESTING:09}}

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- `digests resent … cause=canceled`: a cancelled header's digests landed in the proposer's next header in 2,811 of 2,813
  cases, 113-118 ms after the cancel instead of the 20-45-s fallback.
- It does not move the median. Uncertified headers under load were a starvation problem (the F3-6 refusal), not a cancel
  problem, and on a starved node the next header is refused for the same reason: v04 re-queued 8,162 digests, v08 7,479
  and v10 3,543, to no effect ({{ISSUE:execution-behind-vote-starvation}}).
- Keep it: it is correct and cheap, and it will matter once certification is healthy. Like the commit-path re-queue, it
  can carry a sender's earlier batch in a later header than the batch after it, so the later nonces execute first and are
  skipped. {{ISSUE:sealed-tx-invisible-drops-and-duplicates}} covers that effect and proposes no change to the re-queue.

Refs {{ISSUE:execution-behind-vote-starvation}}
