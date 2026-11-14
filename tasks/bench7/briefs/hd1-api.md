# HD-1 API: the proposer's order bookkeeping (#1807), for HD-2

Written by HD-1. Branch `b7/hd1` on base b10180cfc, tip 603f8b2f1 (5 commits). Files: `crates/consensus/primary/src/proposer.rs`, two handles structs in `metrics.rs`.
Nothing here is read when a header's contents are chosen; `test_digest_order_bookkeeping_keeps_payloads_golden` (green on the base first) pins the payloads.

## Shapes

- `ProposerDigest` gains `seq: Option<u64>`: the digest's place in its worker's lane, counted per worker from 0 over the proposer's life (one epoch). `None` = unknown.
- `Proposer::queue_reported(digest)` is the run loop's push of a worker report: it numbers the digest (`lane_seqs.assign(worker)`) and pushes it to the back of its lane. Tests queue through it too.
- `Proposer::lane_seqs: LaneSequences { next, out, committed }`: `next` per worker; `out: BTreeMap<BlockHash, (WorkerId, Option<u64>)>`; `committed: BTreeMap<WorkerId, u64>` (highest committed seq per lane).
- `Proposer::committed_own_round: Round`: the highest own round any commit notice named.

## Where drained digests are kept

In `lane_seqs.out`, beside `proposed_headers`, with the same lifecycle as `proposed_first_received`.
An entry is written in `drain_digests_for_header`, so the header in flight counts before `handle_proposal_result` tracks it.
It leaves when its digest returns (`push_payload` calls `lane_seqs.returned`) or commits (`process_committed_headers` calls `lane_seqs.committed`).
`push_payload` takes a fifth argument, `seq: impl FnMut(&BlockHash) -> Option<u64>`, which fills the rebuilt digest's `seq`.

## How a header is forgotten

There is no separate forget call. A round leaves `proposed_headers` only in `process_committed_headers` (the committed rounds, then the dead rounds it re-queues) and in `process_uncertified_header`; the `out` entries leave at the same places.
HD-2's `OwnChainOrder::forget(round)` goes beside each `proposed_headers.remove`.

## The out-of-order rule (`LaneSequences::judge`, called from `prepend_requeued`)

A re-queued digest (lane w, seq s) counts once per re-queue iff a digest of w with a higher seq is out of the queue and does not return in the same call: it is in `out` (in flight or tracked) or under `committed[w]`. `None` seqs count as unknown, never as out of order.

## Stale re-sends (HD-2a wiring note 8)

A tracked header at a round `<= committed_own_round`, read before the current notice raises it, was put back by a re-send after an own commit had settled its round.
Both re-queue paths take its digests' `out` entries (as `proposed_first_received` loses their stamps) but give them no seq, and count them as `tn_primary.requeued_order_unknown_total{reason="stale_resend"}`, never as out of order.

## `header proposed` fields

`ProposalTrigger.hold: HoldReport { own_parent, held, held_lanes, blockers }`, built in `propose_next_header` before the drain.
HD-1 sets `own_parent` from `Proposer::cites_own_parent(round, &self.last_parents)` (the same reading as `HoldPlan::own_parent`) and leaves the counts 0.
HD-2 fills them from the plan: `held` = digests left queued in held lanes, `held_lanes = plan.held_workers.len()`, `blockers = plan.blockers.len()`; it can replace `cites_own_parent` with `plan.own_parent`.
