# A far validator's certified headers often go uncommitted, so its batches wait up to about 50-60 rounds to be re-proposed

## What happens

On a ten-validator committee, two validators whose certificates usually form among the last of the ten (validators 02 and 06 of the bench fleet, "far" below; "near" is the other eight) get their batch-carrying headers certified, yet many of those certificates are never committed.
A batch in such a header comes back to the proposer's queue only through the commit-path re-queue, which fires when a later own header is committed, and is then proposed again.
In bench 7 a commit-path re-queue came a median 50-61 rounds after the oldest own header it returned (about 21 s in the run that records seconds).

What it costs: in bench 7, under light load, a far validator's batch took 12.9 to 61.4 s at the median from its first own proposal to execution (61.4 s is a median of 5 batches), against 0.93 to 1.37 s on the near validators.
Transactions sent to a far validator land after tens of seconds: in bench 7's second light blast the generators sending to 02 and 06 saw a median of 16.7-18.2 s, against 2.11-2.12 s for the near median.
The generators keep a fixed number of transactions in flight (16 per sender), so their rate is expected to follow the latency (inferred, not measured separately): in bench 7's first light blast the far generators landed 2 to 10 % of the near median's rate.

## Evidence

Four runs, one per configuration, ten validators and one observer at 20,000 IOPS: bench 6's [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) and [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) (branch `bench/bench6-2026-11`, 2df831e3c), bench 7's [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/) and [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/) (branch `bench/bench7-2026-11`, 91a15e223, on main at 45dce8947).
Validators 02 / 06 with the near median in parentheses, over each light blast's mixed phase; "-" is not in the run's data.

| quantity | blast | r20261113-1351 | r20261113-2118 | r20261115-1131 | r20261115-1653 |
|---|---|---|---|---|---|
| certified, never committed, share of batch-carrying headers | 0 | 0.38 / 0.36 (0.00) | 0.70 / 0.71 (0.00) | 0.47 / 0.55 (-) | 0.75 / 0.76 (0.00) |
| | 1 | 0.29 / 0.35 (0.00) | 0.14 / 0.16 (0.00) | 0.51 / 0.60 (0.02) | 0.46 / 0.50 (0.00) |
| proposals per batch, p50 | 0 | 2 / 2 (1) | 3 / 3 (1) | 2 / 2 (1) | 3 / 4 (1) |
| | 1 | 1 / 1 (1) | 1 / 1 (1) | 2 / 2 (1) | 2 / 2 (1) |
| first own proposal to execution, p50 s | 0 | 12.5 / 15.0 (0.93) | 40.1 / 40.1 (0.93) | 16.1 / 20.3 (0.93) | 44.9 / 61.4 (0.93) |
| | 1 | 2.90 / 3.24 (2.70) | 2.74 / 2.76 (1.91) | 15.8 / 15.2 (1.35) | 12.9 / 14.7 (1.37) |
| share of committed certificates, % | 0 | 2.74 / 2.68 (11.9) | 1.17 / 1.19 (12.2) | 2.09 / 1.89 (12.0) | 1.12 / 0.92 (12.3) |
| | 1 | 4.67 / 3.96 (11.6) | 6.49 / 5.72 (11.0) | 2.36 / 2.12 (12.0) | 3.50 / 3.28 (11.7) |

In r20261115-1653's first light blast the medians of first own proposal to execution for 02 and 06 (44.9 / 61.4 s) rest on 7 and 5 batches.
In bench 7 every batch-carrying header of 02 and 06 in the light blasts was certified.
Counted from the oldest own header each re-queue returned, the re-queue came a median 41-60 rounds later in bench 6 and 50-61 in bench 7; in seconds, 14.3-21.1 s in bench 6 and 21.0-21.4 s in r20261115-1653.
The near validators' median count of commit-path re-queues is 0 in every cell.
The re-queue fires on an own commit: on bench 6, 127 of 127 commit-path re-queues of 02 and 06 in the light blasts came within 50 ms of that node's own `certificate committed` line.
In the second light blast a far certificate that was never committed formed 9th or 10th of ten at the median in r20261115-1653 and in both bench 6 runs; in r20261115-1653, 7 or 8 of the nine others had proposed the next round by then.

The digest order hold for #1807, in the bench 7 build, is not involved: bench 6 had no hold and shows the same in its first light blast, and in bench 7 the hold held none of 02's or 06's headers in the light blasts.

## Where in the code

On main at 33b727fce, and the same in both bench builds:

- `crates/consensus/primary/src/consensus/state.rs:765-771` collects, over the committed sub-dags, the rounds of this node's own headers; `:809-814` sends them on `committed_own_headers` whenever the sub-dags hold any header.
- `crates/consensus/primary/src/proposer.rs:1238-1240` hands that notice to `process_committed_headers` (`:823`), which takes the highest own round in it, 0 when it holds none (`:825-832`).
- `:846-854` walks `proposed_headers` in round order with `.take_while(|(header_round, _)| **header_round <= max_committed_round)`; `:857-862` puts the digests of every header it passed back at the front of the queue (`prepend_requeued`, `RequeueCause::Committed`), logged as `digests resent` (`:940-947`).

So a certified own header that is never committed holds its batches until a later own header is committed.
The doc comment (`:815-822`) calls such headers "skipped with no hope of being committed"; the walk learns that only from a later own commit, and a far validator's certificates are committed less often than a near validator's (the committed share above) and with long gaps (in bench 6's light blasts the 95th-percentile gap between two own commits of 02 or 06 was 16-58 rounds).

## What is not known

Why the far certificates are not committed is inferred: the near validators' next-round headers do not name a late far certificate as a parent, so no leader's sub-dag reaches it before the re-queue.
Which parents a header names is not logged, nor when a certificate reaches a peer; the rank and lateness above use each author's own `quorum reached` time and the others' `header proposed` times.

In the second light blast bench 7 committed a smaller share of the far certificates than bench 6 (2.12-3.50 % against 3.96-6.49 %) while the re-queue's delay in rounds overlaps.
Between bench 6 and bench 7 the storage engine, the upstream vote-handler rework, the order hold and the run's shape changed together; the round rate of 02 and 06 barely moved (2.83-2.84 own headers per second against 2.80-2.81), and no counter separates the candidates.
The far validators had no leader slot in that blast in bench 7, against 0.48-1.72 % in bench 6: a lead, not a finding.

## What could be done (suggestions, none tried)

- Re-queue a certified own header's batches once its certificate can no longer be committed, or after a bounded number of rounds, rather than at the next own commit; this has to handle the old header being committed after all.
- Let a proposer wait briefly for a late certificate of the previous round before it builds its header.
- Look at how the leader schedule treats validators that are always late.

## How to tell more, and how to verify

A field on `header proposed` listing the parents the header names, or a counter of own certificates that no next-round header names, would turn the inferred step into a measurement.
A fix shows in a light blast as one proposal per batch at the median on 02 and 06, and a first-proposal-to-execution time close to the near validators'.
