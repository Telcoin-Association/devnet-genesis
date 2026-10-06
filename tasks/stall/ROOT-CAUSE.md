status: done (orchestrator synthesis, 2026-10-06)

# r20261006-0053 stall — root cause

Sources: tasks/stall/L1-failing.md (v03/v04/v10 logs), L3-survivors.md (v01/02/06-09, v05, observer),
L2-code.md (telcoin-network @ 964087e02), T1-preamble.md (generators).

## Mechanism
1. The proposer re-sends its byte-identical last header every max_header_delay (500 ms; 250 ms when the
   node is the next leader, proposer.rs calc_max_delay) while it waits for 7 parent certificates
   ("re-proposing last header after max delay interval expired"). Digests never change (L1 §4).
2. Certifier::run calls new_proposal.notify() for EVERY header and spawns a new spawn_header_proposal;
   propose_header builds a fresh VotesAggregator each time (certifier.rs ~303, ~570). So each re-propose
   cancels every in-flight request_vote (DagError::Canceled, logged "failed to get vote … Canceled") and
   throws away all votes already received. `Canceled` lines land within 10 ms of the re-propose tick
   (v03 192/195, v04 232/241, v10 388/388 — L1 §3). The error is a symptom, not a cause.
3. A validator that cannot collect 6 remote votes inside one window can never certify. v03/v04
   (australia-southeast1, 10.152.0.x) certified 0/1564 and 0/1542 proposals in the first two 10-min
   buckets of the run, ~1/3 later when rounds slowed under load (L1 verdict 2). Observed one-way
   request→recast delays from v03: v04 0-49 ms, v01 200-249 ms, v10 400-449 ms (L1 verdict 4).
   The committee therefore ran on 8 certifying validators from launch, with zero failures to spare
   once one more was lost.
4. Kill v05 (02:09:55) → 7 certifying validators = exactly the quorum. At round 1787 v10 (next leader of
   1788, 250 ms window) also failed to certify; v03/v04 as usual. Only 6 round-1787 certificates existed
   (v01, v02, v06, v07, v08, v09); the certificate aggregator hands parents to the proposer only at 7
   (aggregators/certificates.rs:92), so nobody could propose 1788. The 30 s "triggering certificate
   fetching" found nothing (no 7th certificate existed anywhere). 301 s with zero commits.
5. v05 restarted 02:15:00, recovered its pack WAL, fetched 154 certificates, proposed round 1787 with 9
   parents at 02:15:16.3 (a NEW digest, so voters voted at once) → 7th certificate → round 1788 → commit
   02:15:17.4 → the 02:10:37 epoch boundary detected 60 ms later (by design: boundary = first commit
   whose timestamp >= boundary; L2 §6).

All six survivors recast votes for the three stuck digests on every request (595/595/1188 — L3 §2,
L1 §5), so the votes were sent; the proposer never kept them long enough.

## Ruled out
- Epoch-close window: nothing in primary references the boundary (L2 §6); the stall began 22 s before it.
- Same-round equivocation / "already voted": re-proposals are identical; no refusal text in any log.
- Dead-peer request delaying quorum: propose_header stops at 7 votes and never waits for v05 (L2 §4).
- Vote timeout: never fired (only the startup "Vote timeout set to 5000 ms").
- The 7 merged branches: certifier.rs, handler.rs, aggregators unchanged since d89566e1d (L2 §7).

## Fix
certifier.rs: an identical re-proposal of the in-flight header must not cancel/restart vote collection
(keep the aggregator and the retrying request_vote tasks). Different digest → unchanged behaviour.
Branch fix/certifier-keep-inflight-on-repropose off main; merged into devnet-bench-10-5-2026 for the re-run.

## Why 29 Sep did not stall
3 s max header delay: every validator could certify inside one window, so 9 live validators meant 9
certifying ones; losing v05 left 8 ≥ 7.

## Secondary findings (not fixed here)
- Transactions accepted into the pool are dropped when their batch never commits (T1): 8/10 generators
  hit the 600 s preamble limit; chronic "pinned node lost the head-of-line tx" on every blaster.
- v03/v04 include transactions very slowly (submit→land p50 77-90 s vs 2.5-3.6 s) — same latency-bound
  certification problem seen from the generator side.
