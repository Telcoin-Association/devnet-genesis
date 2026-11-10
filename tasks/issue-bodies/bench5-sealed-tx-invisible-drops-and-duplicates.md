## Problem

The batch builder removes a transaction from the pool as soon as its batch reaches the worker quorum. From then until the
batch executes, the node has no record of the transaction that the pool or the RPC can see: `eth_getTransactionByHash`
returns null, `eth_getTransactionCount(pending)` ignores it, and `eth_sendRawTransaction` of the same bytes is accepted as a
new transaction. Execution skips an invalid transaction and never hands it back to the pool. Two user-visible defects follow.

1. **Accepted transactions vanish for five minutes.** When one node's later batch for a sender executes before its earlier
   batch, the later nonces are skipped (`nonce N too high`). They had already left the pool, and the sender's next
   transactions wait in the pool's queued sub-pool behind the hole. Nothing repairs the gap until the client sends the same
   bytes again. The load generator does that after 300 s without progress, so 1.85 % of the sampled landings under load took
   300 s or more, none took 250-300 s, and land p99 was 402.6 s (bench 4: 31.4 s). A wallet that does not resend never
   sees its transaction land and gets no error.
2. **A resend executes beside the original.** When a batch stays sealed but uncommitted for longer than the client waits,
   the client resends, the pool accepts the same transaction again, and both copies are committed. The second copy is skipped
   (`nonce N too low`). If the resent set is identical, the rebuilt batch is byte-identical, has the same digest, and is
   committed and executed again. Nothing between seal and execution deduplicates by transaction hash or by batch digest.

The trigger that made the sealed batches long-lived in this run was the F3-6 vote starvation of three validators
({{ISSUE:execution-behind-vote-starvation}}), but the first defect does not need it: it comes from the commit rule
skipping an author's header, which happens at every load level.

## Evidence

Run r20261107-1504, the 600 × 16 load blast (mixed phase 17:40:02-18:20:02, validator-05 killed at 17:54:44). Times are
UTC. Execution is deterministic, so one node's log (validator-02) shows every skip on the fleet; the skip lines are
`skipping invalid transaction` at `crates/tn-reth/src/env/execution.rs:318`.

The five-minute cliff (1-in-100 sampled landings, 82,830 mixed rows):
- 1,530 transactions were seen 300 s or more after submission and none in 250-300 s: 104-287 on eight generators (London
  287, Netherlands 251, Mumbai 193, Seoul 184, Hong Kong 175, Tokyo 170, Singapore 143, Ashburn 104), Sydney 22, LA 1. Every
  generator logged its gap repair, `pinned node lost the head-of-line tx; resending in-flight txs` (lines plus suppressed:
  14,046 over the ten), for example `blaster-04:17:43:40.918` `sender=13 chain=52 next_nonce=68 resend=16`.
- 748 of the 1,530 (48.9 %) were skipped before they landed: 736 `nonce too high`, 12 `too low`. A control set of 3,295
  transactions seen in 5-20 s matched no skip line (bench-5 triage; report finding 9). First case: `validator-02:17:40:31.237` output 11578 `nonce 298
  too high, expected 283`.
- Of the other 782: 570 landed at seen p50 313 s, 96 % of them inside 300-330 s, the shape of a transaction submitted at
  the moment its sender stalled and resent 300 s later (the skipped ones land at p50 331 s, p90 380 s, because they waited
  before the skip). 109 are the starved validators' transactions (generators 04/08/10 inside their certification gaps, p50
  607 s) and 103 are generator 05's after its validator was killed (p50 382 s).
- `nonce too high` skips on validator-02 grouped by consensus output and expected nonce: 416 sender episodes before the
  kill and 7,948 after it, 86,823 skipped transactions. Each skipped run starts above a hole of 6.7-7.0 nonces on average.
  Those holes are filled when the earlier batch lands, and the generator then submits that many new transactions, which
  queue behind the skipped ones. Skipped plus queued is about 145,000 transactions, 1.8 % of the ≈ 8.3 M the load phase
  landed, against 1.85 % of the sample at 300 s or more. The predicted skipped share of that set is 59.8 %, against
  56.8 % observed among the 1,318 slow landings that are neither starved nor on the killed node.
- The out-of-order batches come from every author (by the batch that carries the skips: before the kill v07 32, v10 31,
  v06 21, v02 20; after it v09 115, v08 95, v06 92, v02 91). The 600 × 4 blast, with no starvation and no kill, has 1,097
  episodes and 8,987 `too high` skips on validator-02 between 16:48 and 17:09. Its 324-s window ends before any 300-s resend,
  so the sample cannot show those transactions.

The duplicates:
- All 37,683 `nonce too low` lines on validator-02 fall in outputs 12084-12088 and 12091 (17:55:01-17:55:20), the first
  outputs after the starved validators certified again. Every one is in a batch authored by those three: validator-04
  14,989 in 61 batches, validator-08 18,652 in 25, validator-10 4,042 in 18, all first sealed between 17:43:29 and 17:55:07.
  Their batches had cycled uncertified for 560-640 s (bench-5 report, finding 4), longer than the generator's 300 s.
- Five batch digests were executed more than once (nine extra blocks). Validator-04 sealed four of them three times each,
  300 s apart: `0x6024039a…` at `validator-04:17:43:41.391`, 17:48:41.52 and 17:53:41.65, each time `batch built …
  num_txs=16 reason=drained pool_age_p50_ms=300187`, 470 ms after `blaster-04:17:43:40.918` resent sender 13's 16
  transactions; `0xc3454353…` 40-90 ms after each of blaster-04's resends for sender 428 (17:43:49.269, 17:48:49.354,
  17:53:49.470). It proposed them in several headers (`0xf2a3ab87…` in rounds 1713 and 1717, `0xbdecfd16…` in 1707 and
  1716) and all copies executed in outputs 12084-12088.
- The fifth shows the two defects are one. Validator-01 sealed `0x9c01a8c5…` at 17:48:09.8. In output 11880
  (`validator-02:17:48:20.835`) all nine `too high` skips of that output are in this batch. The generator resent the same
  bytes, validator-01 sealed the byte-identical batch again at 17:53:08.9, and its copy in output 12033 executed with no
  skip. The duplicate digest was the copy that landed the transactions.
- The batch line also shows the pool's view on a starved node: validator-04's 17:43:41 build had `pending_before=16
  queued_before=9235`. Reading (not checked per sender): once a canonical update resets a sender's pool nonce below its
  sealed, unexecuted nonces, its later transactions queue behind them.

## Mechanism

Line numbers are at `bench/main-fixes-2026-11` 067639def; reth at v1.11.3.

1. **Sealing removes the transaction from the pool.** The builder seals, waits for the quorum ack, and on success prunes
   the batch's transactions and advances the senders' pool nonces (`crates/batch-builder/src/lib.rs:366-369`, applied at
   `:643` through `crates/tn-reth/src/txn_pool.rs:764`; the optimistic nonce at `crates/batch-builder/src/batch.rs:279`).
   Only a failed seal leaves them (`lib.rs:395-406`). Afterwards the transaction exists only inside the batch: the worker's
   `OurNodeBatchesCache` row (`crates/consensus/worker/src/worker.rs:361`, evicted when the output is forwarded to execution,
   `crates/node/src/manager/node/run_epoch.rs:1262-1276`) and the digest in the proposer's queue.
2. **The RPC cannot see it.** `transaction_by_hash` reads the RPC cache, the database and then the pool
   (reth `crates/rpc/rpc-eth-api/src/helpers/transaction.rs:668-672`), so a sealed transaction is null. The pool's only
   duplicate check is `contains(hash)` (`crates/transaction-pool/src/pool/txpool.rs:750`) and validation reads canonical
   state, where the nonce is still unused, so a resend is accepted as new instead of `already known`. The pending nonce comes
   from the pool's highest consecutive transaction (`crates/rpc/rpc-eth-api/src/helpers/state.rs:358-362`), so a wallet that
   signs from `pending` while its earlier transactions are sealed reuses their nonces. The generator's gap rule asks exactly
   this question (`tn-transaction-generator/src/blast/sender.rs:470-530`: no progress for 300 s and
   `eth_getTransactionByHash` null on the pinned node) and cannot tell a sealed transaction from a lost one; it resends to
   the same node, and it treats `already known` as accepted (`sender.rs:123`).
3. **A skipped transaction never returns.** Execution skips an invalid transaction per transaction (`execution.rs:309-321`)
   and nothing feeds it back. When the earlier batch lands, the canonical update sets the pool's nonce for that sender to the
   executed one, and every later transaction of the sender, already queued or submitted afterwards, waits behind the hole in
   the queued sub-pool. The hole closes only when the client resends.
4. **One node's batches can execute out of order.** A generator sender is pinned to one node, so all its batches come from
   one worker, sealed in nonce order and queued FIFO (`crates/consensus/primary/src/proposer.rs:127-133`, `:1201`). They
   execute in commit order, and an author's headers do not commit in round order:
   - Bullshark skips any certificate whose round is at or below the last committed round of its author
     (`crates/consensus/primary/src/consensus/utils.rs:61-65`). A header whose certificate the leader's sub-DAG did not reach,
     while the author's next header was reached, is never committed. Its digests return only through the commit-path re-queue
     (`proposer.rs:803-863`, `Repropose … in undelivered headers`, `cause=committed`), into a header later than the one
     already committed.
   - The cancelled-header re-queue (L7, `feat(primary): re-queue digests of cancelled headers`) moves a cancelled header's digests to the front of the queue (`proposer.rs:873-892`, `:900-926`), but
     the header after the cancelled one is already proposed with newer digests, so they ride the header after that (bench-5 certification analysis: the
     resent set lands in header R+1).

   Within a sub-DAG certificates execute in round order (`utils.rs:107`), so in both cases the earlier batch executes after
   the later one and the later nonces are skipped. The pinned-sender layout makes this visible; any client that sends
   consecutive nonces to one node faster than it seals hits it.
5. **Nothing deduplicates between seal and execution.** The batch carries no time or parent field and its digest excludes
   `received_at` (`crates/types/src/worker/sealed_batch.rs:137-138`; built at `batch.rs:264`), so the same transactions
   drained alone give the same digest, which `OurNodeBatchesCache` overwrites without noticing (`worker.rs:361`). The
   proposer appends every reported digest without checking its queue, its proposed headers or this epoch's commits
   (`proposer.rs:1201`). The subscriber deduplicates digests only within one output and re-adds a repeated one
   (`crates/consensus/executor/src/subscriber.rs:1036-1044`, `:1080-1103`); across outputs nothing checks. The peer-batch
   window of #1329 (`crates/tn-reth/src/peer_batch.rs`, 10-s TTL) covers only transactions seen in a peer's batch, not this
   node's own sealed ones. Execution skips each copy (`execution.rs:309-321`), so consensus stays safe; the cost is the
   wasted block space and a resend that cannot be told from a duplicate.
6. **Restart and epoch boundary.** A killed node loses its pool and its in-memory proposer queue (`proposer.rs:1196`);
   its sealed batches survive in `OurNodeBatchesCache` and are re-pooled at restart (generator 05's 103). The epoch
   boundary is not a path: `orphan_batches` re-pools the uncommitted own batches (`crates/node/src/manager/node/close_epoch.rs:236-245`;
   validator-02 re-pooled 6 batches / 1,852 transactions at 17:56:05 and 5 / 1,486 at 18:15:54), and no duplicate fell at a
   boundary in this run.

## Proposal

The defect is that the node forgets a sealed transaction before it executes. Fix that in the pool; the other rules are
safety nets or belong to other issues.

**(A) Keep a sealed transaction in the pool until it executes. Recommended.** On a successful seal, mark the batch's
transactions as sealed instead of pruning them, and drop the optimistic nonce advance. The builder skips sealed transactions
without `mark_invalid`, so their descendants stay buildable, as `is_peer_deferred` already does for peer batches. The
canonical update removes them when they execute. When `evict_committed_batches` reports a digest as forwarded to execution,
clear its marks: a transaction still in the pool after its batch executed was skipped and becomes buildable again. The
orphan path at the epoch boundary then has nothing to re-pool.
- Symptom 1: a skipped transaction is re-sealed one batch later, and the queued successors behind it are released, so a
  300-s stall becomes one extra commit cycle (seconds).
- Symptom 2: `eth_getTransactionByHash` answers pending for a sealed transaction, `eth_sendRawTransaction` of the same bytes
  returns `already known` from the pool's own check, and `pending` counts it. The generator needs no change: it does not
  resend a transaction the node knows, and it treats `already known` as accepted.
- The fix belongs in the node, not the RPC layer or the generator. A separate RPC-side index of sealed hashes would fix
  visibility and leave the skipped transactions lost. A generator that never resends hides the duplicates and leaves the
  five-minute loss, which real wallets also hit.
- Cost and care: sealed transactions count against the pool's limits, about one window per sender (≤ 9,600 per node at
  this load). Eviction under pool pressure must not drop a sealed transaction, which is consensus-bound already. Not
  consensus-observable: batch contents and execution are unchanged; only what the pool offers to the next build changes.

**(B) Deduplicate where it is cheap.** With (A) the builder never sees a resend of a sealed transaction, so no
transaction-level index is needed. Add at the worker: before sealing, if the digest is already in `OurNodeBatchesCache`,
do not report it again. Add at the proposer: drop a reported digest that is already pending or in `proposed_headers`.
Do not drop digests already committed in this epoch, and do not deduplicate at the subscriber or the engine: the
`0x9c01a8c5…` case shows a re-committed digest can be the copy that lands the transactions, and a digest refused after its
transactions left the pool loses them. Execution-level deduplication would also change block contents and need a fork gate.

**(C) A TTL that returns uncertified digests to the pool. Rejected.** With (A) the transactions never left the pool, so
there is nothing to return. Dropping a digest that a live header may still carry risks committing the transactions twice,
and a TTL shorter than starvation only adds re-seal churn. A per-node count of digests re-queued more than N times is
enough to make starvation visible.

**(D) The starvation (F3-6) is a separate fix** ({{ISSUE:execution-behind-vote-starvation}}). It explains the 10-minute
sealed batches, the 37,683 `too low` skips, all five duplicate digests and the 109 starved landings (≈ 7 % of the tail).
It does not explain the 1,318 out-of-order cases (86 % of the tail), which come from the commit rule skipping an author's
header (mechanism 4): they occur on every author, in the 600 × 4 blast with no starvation, and at light load, where London
and the Netherlands commit 13-18 % of their certificates. With F3-6 fixed and without (A), expect the 300-s cliff on most
generators and duplicates whenever a client retries faster than a batch commits (London/NL at light load: first proposal
to commit p50 13.9-27 s).

Out-of-order execution itself is not worth preventing at the source. The builder could hold a sender's next nonces while an
earlier one sits in an uncommitted own batch, but that limits a sender to one batch per commit cycle. With (A) an
out-of-order pair costs one re-seal.

## Test plan

- Batch builder unit: seal a batch, assert its transactions stay in the pool, are not offered to the next build, and their
  descendants are; clear the marks for the digest, and a transaction still in the pool is built again; a canonical update
  that mines it removes it.
- Pool and RPC unit: with a transaction sealed, `get(hash)` is some, `add_transaction` of the same bytes returns
  `AlreadyImported`, and the pending nonce counts it.
- Worker: sealing a batch whose digest is already in `OurNodeBatchesCache` reports nothing new. Proposer: a digest reported
  twice, or reported while in `proposed_headers`, lands in one header.
- Engine (no change, pin behaviour): two batches of one sender committed in reverse nonce order skip the later nonces with
  `nonce too high` and leave state as if they were absent; the same batch in two outputs executes twice with every
  transaction of the second copy skipped.
- e2e: under load, force one validator's header to be cancelled or skipped by the commit rule (or starve it with a fault
  injected into its votes). Assert its transactions answer `eth_getTransactionByHash` while sealed, a resend returns
  `already known`, every transaction lands exactly once, and no block carries a `nonce too low` skip.
- e2e out-of-order: two batches of one sender with the earlier digest re-queued behind the later header. Assert the
  skipped nonces land within a few commit cycles without any resend.

## The bench-6 fields that prove it

- Sampled landings at 300 s or more: 0 on every generator (bench 5: 1,530 of 82,830, 1.85 %). Land p99 back near bench 4's
  31 s, net of any starvation.
- Generator gap repairs (`resending in-flight txs`, lines plus suppressed): ≈ 0 (bench 5: 14,046).
- `tn_reth_invalid_txs_skipped_total{reason="nonce_too_low"}` ≈ 0 under load (bench 5: 37,683 per node).
  `{reason="nonce_too_high"}` may stay non-zero (out-of-order pairs still happen) but every skipped transaction lands within
  seconds.
- Duplicate digests executed (same `batch_digest` in two `next block executed` lines): 0 (bench 5: 5, nine extra blocks).
  Digests sealed twice on one node (`batch sealed`): 0 (bench 5: 5).
- `queued_before` on `batch built` lines stays small on every node (bench 5: 9,235 on validator-04 at 17:43:41).
- Data to add so bench 6 can classify every slow landing instead of 1-in-100 by time: the sender address in the landings
  export and in the `skipping invalid transaction` line. Then each slow landing is a skipped one, a queued successor (same
  sender, `too high` skip at a lower nonce in the previous 300 s), a sealed-but-uncommitted one (hash in a batch sealed
  more than 300 s earlier) or lost on restart. Also run the 600 × 4 blast long enough to show its 300-s tail (bench 5 had
  1,097 out-of-order episodes it could not see).

## Related

- {{ISSUE:execution-behind-vote-starvation}} (F3-6): the trigger for the long-lived sealed batches; fixing it removes
  the duplicates seen here but not the out-of-order losses.
- #1329: the peer-batch deferral window. (A) applies the same idea to this node's own sealed transactions, without the TTL.
- #1236 / #1304: the pool's lag resync. With (A) the pool's nonce view no longer jumps between the builder's optimistic
  nonce and the canonical one.
- Lever 10 in the bench-5 report, finding 5 ("nonce-gap parking fix"): (A) is that fix.
- L7 (the cancelled-header re-queue) and the commit-path orphan re-queue: correct for liveness, and the source of the out-of-order pairs;
  no change proposed.
