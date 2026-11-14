# Topic review 06: the own-chain order hold for #1807 (`digest_order_hold`)

Reviewed 2026-11-14 by unit R-06, read-only, no cargo.
Worktree `/home/drtnarg/coding/telcoin/tn-b7-gate` at a11f14b1b.
The change is the commit list 96d98a8a6 a1ee64826 8e0bc1aa0 b974ebb96 b892bd977 08e47ed93 5879d7ce6 b64320919 a06377d8f 9f61fdc6b cfc167924 1b5042e08 f9de4aa15 a11f14b1b, each read through its own diff.
Paths below are relative to `crates/` in that worktree unless named otherwise.

## Verdict: APPROVE WITH FOLLOW-UPS

With the switch off, the topic is main byte for byte in header contents and header timing.
With it on, it changes only which digests a node's own header carries, which no other validator checks, so a mixed fleet is one chain.
No reachable state holds a lane forever while this node's later headers still commit.
After verification there is no Critical, High or Medium finding.
Four Low findings are confirmed, and one lead (L-1) needs watching on the far validators.
The open design question (which digests trigger a header) has a recommendation in its own section below: reading B, narrowed to the previous header.
Nothing here blocks the benchmark image.
The trigger reading should be decided before the image is built if the run is meant to measure the hold as it would ship.

## Findings, most severe first

All four are Low and CONFIRMED by an independent verifier, which saw only the claim and the question.
The verifier's full text is at `/var/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/54d4e169-243d-47be-a98d-d2c129d3944a/scratchpad/R-06/verified-findings.md`.

### 1. Held digests count toward the header trigger, and the module doc says the hold never changes timing (Low, CONFIRMED)

- Location: `consensus/primary/src/proposer.rs:1704-1713`, `:1223-1225`; `consensus/primary/src/order_hold.rs:85-86`; `config/src/node.rs:454-456`; pinned by `proposer_tests.rs:4247`.
- Scenario: one worker, lane held behind own header R.
  `pending_digests_len()` sums every lane, held ones included, so a held backlog of 5 or more keeps `enough_digests` true.
  From the second header of a hold onward, the next header is built as soon as parents and `advance_round` allow, without the 1 s min delay, and it carries nothing from the held lane.
  At light load this builds headers earlier than main would.
  After release, a backlog still at or above the threshold builds R+1 before R's own certificate has had the min delay to arrive.
- The comment at `proposer.rs:1704-1707` and the switch doc disclose this.
  `order_hold.rs:85-86` ("It never changes when a header is built") is wrong for the feature as a whole.
- Fix: decide the trigger reading (question 9 below), then reword `order_hold.rs:85-86` and the design's "no timing change" sentence to match.
- Before the benchmark image: no. Before the upstream PR: yes, the decision and the doc.

### 2. Peers age out the stored bodies of held batches (Low, CONFIRMED, narrowed)

- Location: `consensus/worker/src/network/ledger.rs:42-71`, `:108-113`; `consensus/worker/src/network/handler.rs:72-76`, `:584-609`.
- Scenario: the #1794 ledger on every peer counts an author's stored, uncommitted batches against a bound of 500 (`handler.rs:85`).
  A held digest keeps its slot until it commits.
  When the key is at the bound, entries older than MAX_GC_DEPTH committed rounds are dropped and their bodies deleted, on the stated assumption that their certificate left the DAG.
  For a held digest that is false: it has no header yet.
- Narrowed by the verifier: voters do not refuse the later header, because `state_sync/header_validator.rs:125` checks the `Payload` table, which age-out does not clear.
  Execution re-fetches the body from the author, which keeps it (`worker.rs:429`).
  The cost is a re-fetch, plus wrong docs.
- Fix: correct the docs at `ledger.rs:53-55`, `:108-113` and `handler.rs:72-76`.
  Optionally carry the worker id in the ledger row so that age-out can treat digests still queued at their author differently.
- Before the benchmark image: no. Before the upstream PR: the docs.

Lead L-1 (PLAUSIBLE; the verifier read the code, no second check): when an author's key at a peer holds 500 uncommitted batches that are all younger than MAX_GC_DEPTH committed rounds, the peer refuses the author's reports (`ledger.rs:41-50`, `handler.rs:599-609`), and the author's quorum waiter counts that as a rejection (`quorum_waiter.rs:92-99`).
The seal then fails and the pool keeps the transactions, which the RPC feels.
The hold makes this reachable: while an author's own chain stays broken, a held lane drains at most one header's worth (`max_header_num_of_batches`) per own commit.
A worker that seals faster than that piles up young uncommitted batches.
That needs roughly 10 seals per committed round, sustained.
Whether a far validator reaches it on the fleet is unknown.
Watch `tn_worker.batch_reports_over_quota_total` with `tn_primary.digests_held` on the far validators in the switch-on run.
If the counter moves, decide a cap on how long a lane may stay held before the upstream PR.
This is one concrete consequence of accepted residual (c), not a new defect.

### 3. After a restart, a committed last header can be tracked again (Low, CONFIRMED, narrowed)

- Location: `consensus/primary/src/proposer.rs:406` (`committed_own_round: 0`), `:1507-1520`, `:1555-1569`, `:1755-1777`, `:997-1022`.
- Scenario: this node led the last saved commit L and crashed before proposing L+1.
  After the restart, `prime_consensus` sets the primary round from the last saved commit (`state-sync/src/lib.rs:86-117`), so the re-propose arm of `propose_next_header` cannot fire.
  The first max-delay tick can: `resendable_last_proposed` returns L.
  With `committed_own_round` back at 0, the guard at `:1507` does not stop it, so L enters `proposed_headers` again.
  With the switch on, L then holds its lanes in every header that does not cite it, until the next own commit.
  That commit re-queues L's already-committed digests, which are proposed a second time.
  Main does the same, and there they are counted as order-unknown, not as `stale_resend`.
- This is the restart variant of accepted residual (b), and it is not counted where (b) says it is.
  The switch adds latency on L's lanes only, never a stall.
- Fix: in `Proposer::new`, seed `committed_own_round` from the stored `LastProposed` when its round equals the restored committed round and this node led it.
  A sturdier variant compares the stored header's digest with the last executed leader's (`state-sync/src/lib.rs:93`).
- Before the benchmark image: no (only on a mid-run restart of a node that just led a commit). Before the upstream PR: worth a separate issue, since main has it too.

### 4. An own header that ends uncertified without a cancel report holds its lanes until the next own commit (Low, CONFIRMED, narrowed)

- Location: `consensus/primary/src/certifier.rs:422`, `:489-516` (no quorum after every vote request returned; error arm `:781-788`), `:618-622` (certificate-store read error), `:836-848` (full 64-slot report channel).
- Scenario: the certifier gives up on own header T without sending the uncertified report.
  T stays in `proposed_headers`, and with the switch on its lanes stay held until an own commit at or above T's round (`proposer.rs:997-1039`).
  On main T's digests wait just as long, while newer digests overtake them.
- Narrowed by the verifier: a fatal RPC error from one peer ends only that peer's request (`certifier.rs:453-464`, test at `certifier_tests.rs:2227`).
  The remaining paths need faults, or more than f permanent vote refusals.
- Fix (optional): report `CouldNotFormCertificate` when the report-on-cancel path is enabled.
- Before the benchmark image: no. Upstream: optional.

### Dismissed by verification

- The own commit notice is sent after `sequence().send().await` (`consensus/state.rs:790-814`), so execution back-pressure could lengthen holds: FALSE POSITIVE.
  `state.rs` is unchanged from main, the channel holds 10,000, and the 1,000-round run-ahead gate stops commits long before it could fill.
- `uncertified_report_dropped_total` files OverBudget and Broadcast under `unsubscribed` (`certifier.rs:838-846`): FALSE POSITIVE.
  Neither arm can run: the channel has no gap policy (`consensus_bus.rs:605-607`) and its sender is a tokio mpsc (`types/src/sync.rs:135-147`).
  The enqueue is the same as main's `try_send`.
- The own-certificate hook could reach a release build: FALSE POSITIVE.
  The gate is inside the hook (`types/src/test_hooks.rs:226-241`), the same pattern as main's other hooks.
  Images are built with `-p telcoin-network` (`etc/Dockerfile:51`, devnet-genesis `tn-node-deployment/lib/common.sh:7587`).
  Only `e2e-tests` enables `test-utils`.
- `tn_node.orphan_txs_total` does not sum to the processed transactions: FALSE POSITIVE.
  This is documented (`close_epoch.rs:126-127`, `:295-297`), and the processed set feeds only a log line.

### Info (observations, not verified)

- The guard at `proposer.rs:1507` is not in the model.
  It is covered by `test_order_hold_stale_resend_is_never_a_blocker`.
- A commit notice for the header still in flight logs "own committed header not found ... probably because of restarts" (`proposer.rs:974`) and leaves `forget` to the guard.
  The end state is right; the message is misleading.
- `OrderHoldHandles::new()` registers `tn_primary.headers_held_total` and `tn_primary.digests_held` with the switch off (`proposer.rs:410`, `metrics.rs:666-668`).
  A dashboard cannot tell "off" from "on, nothing held"; read the switch from `runtime_switches`.
- `tn_primary.digests_held` is zeroed only on the shutdown arm (`proposer.rs:1596-1599`).
  After an error exit it keeps its last value until the next proposer builds a header.
- The golden test (`proposer_tests.rs:3426-3492`) pins seven payloads through the cancel and commit re-queues, two workers, the cursor wrap and the cap.
  It does not pin parents, timing, the max-delay or restart re-send, or more than two workers.
  R-06 checked those by reading the code (2a).
- The per-lane sequence map is keyed by digest, so a digest reported twice can re-queue carrying the older copy's number (`proposer.rs:1838`, `:1843`).
  This affects the #1807 counters only.
- `plan` walks every tracked own header below the floor and its payload, O(tracked × 10) per header (`order_hold.rs:153-163`).
  The tracked count is bounded only by own commits, as `proposed_headers` already is on main.
- The doc of the orphan re-pool's nonce-too-low split (b892bd977, `close_epoch.rs` about `:299-315`) first says the counter cannot tell an executed nonce from a pool nonce that ran ahead, then reads `refused_nonce_too_low` as executed.
- Batches re-pooled by a node that left the committee are counted only on `orphan_batches_total{path=non_validator}` (`close_epoch.rs:479-480`), as on main.
- Under `before_store`, the hook's hold makes a formed certificate cancellable, by design: that produces the canceled kind.
  Its shutdown noticer in `after_store` is subscribed after the persist (`certifier.rs:746-750`), so a shutdown just before it may let the hold run its full length (test-utils builds only).

## Answers to 2a to 2g

### 2a. Switch off = main

Yes, byte for byte, in header contents (payload digests, their order and count, parents, system messages, other fields) and in timing.
`drain_digests_except(&BTreeSet::new())` yields the same lanes, `max_depth`, cursor and pops as main's drain (`proposer.rs:1244-1281` against main `:974-999`).
Parents are now taken before the drain (`:1404`), and neither the drain nor `pending_digests_len` reads them.
`pending_before` was already computed before the drain on main.
The new early return in `handle_proposal_result` (`:1507`) and both helpers (`forget_held`, `record_held_resent`) are gated on `order_hold.is_some()`.
`OwnChainOrder` is never built with the switch off, because `bool::then` is lazy (`:410`).
The run loop has no new trigger.
The switch is `serde(default)`, skipped when serialized at its default, and in the runtime switch list (`config/src/node.rs:465`, `:575`, `:781`).

Newly running with the switch off, all observability, none able to change behaviour:
- `lane_seqs`: one counter and one committed mark per worker, plus `out`, bounded by the tracked headers and the one in flight times `max_header_num_of_batches` (about 100 B an entry).
  It grows and shrinks with main's `proposed_headers`.
- `judge`, once per non-empty re-queue, O(size of `out`).
- Counters `tn_primary.requeued_out_of_order_total{cause}` and `tn_primary.requeued_order_unknown_total{reason}`, resolved once per epoch.
  `tn_primary.uncertified_report_dropped_total{reason}` and `tn_node.orphan_txs_total{result}` have fixed label sets.
  `OrderHoldHandles` registers its two series, which stay at 0.
- Log fields: `own_parent`, `held`, `held_lanes` and `blockers` on `header proposed`, once per header; `out_of_order` on `digests resent`, once per re-queue.
  A `proposer stopped` line is written once per epoch.
- The `order_hold` module is compiled into non-test builds (`lib.rs`).
  HD-2b's checkpoint reports clippy over all targets at exit 0 on its tree.

### 2b. Mixed fleet

One chain.
The switch changes only which digests go into this node's own header (`proposer.rs:1402-1427`); parents and execution inputs are unchanged.
The vote path checks `Header::validate` (`types/src/primary/header.rs:145-197`: epoch, parent count, batch count, timestamp, author, worker id range), the round, TooNew and execution checks, the parents' round, distinct authors and quorum stake (`consensus/primary/src/network/handler.rs:1697-1745`), and that each listed (digest, worker) exists (`state_sync/header_validator.rs:104-130`).
Certificate validation uses the payload only to start batch downloads (`state_sync/cert_validator.rs:154-165`).
No validator checks which digests a header leaves out, the order of digests across headers, or whether the author's previous certificate is among the parents.
Honest nodes with and without the switch accept each other's headers, votes and certificates.

### 2c. Liveness under the switch

Nothing is dropped.
A held digest stays in its lane in order and is carried once its lane is released.
A lane is released when its blocker leaves `proposed_headers`:
- by its own commit;
- by an own commit notice at or above its round (`proposer.rs:997-1039`); the notice is an awaited send, never dropped (`consensus/state.rs:809-814`);
- by a cancel report;
- or by the epoch's end, which sends everything to the orphan re-pool.
Empty headers never block (`order_hold.rs:159-162`), and empty own headers commit too, so their notices also release lanes.
"Every lane held forever" therefore needs this node's headers to stop committing for the rest of the epoch, and then main loses those digests to the same re-pool.
The bound on a held digest's wait is the earliest of the release events above: typically the next own commit.
When the own chain stays broken, a lane drains about one header's worth per own commit.
That is accepted residual (c), already stated in the switch doc at `config/src/node.rs:457-459`.
Findings 3 and 4 and lead L-1 are the edges.

### 2d. Byzantine or merely slow peers

See question 2 below.
In short: f Byzantine voters alone cannot make an honest proposer hold.
They need at least one slow honest voter, because with n = 10 and quorum 7 the six other honest votes still certify the header.
With that help, the cost per event moves from main's one round to one own commit latency, roughly 2 to 4 rounds (inference).
It cannot exceed what main already loses when every own header is cancelled.

### 2e. Restart and epoch boundary

All hold state is in memory in the per-epoch `Proposer` (`proposer.rs:388-410`): the order record, `proposed_headers`, the queues, `lane_seqs` and `committed_own_round`.
A restart loses all of it.
`LastProposed` survives and is written before the header reaches the certifier (`proposer.rs:610-632`), so the stored header was never cancelled before the crash.
Every sealed batch, whether queued, held or tracked, sits in `OurNodeBatchesCache` (`consensus/worker/src/worker.rs:361`) until a committed output removes it (`node/src/manager/node/run_epoch.rs:758`, `:1433-1446`).
`orphan_batches` re-pools that table at the start of every `run_epoch` (`run_epoch.rs:241-264`, `:412`), on main and with the switch on alike.
A restart re-send can execute a digest twice only through finding 3, which is main's behaviour.
With the switch on, nothing executes out of order there: the re-sent header records floor = its own round (`order_hold.rs:181-186`) while it is the only tracked header.
At an epoch boundary, held digests reach the re-pool exactly as main's queued digests do and are counted on `tn_node.orphan_txs_total{result}` on the validator path.
No record leaks into the next epoch: it is a field of the per-epoch proposer, and every read of `LastProposed` is filtered by epoch (`proposer.rs:350`, `:1359`, `:1568`).
A mid-epoch mode change rebuilds the primary and its proposer (`consensus/primary/src/primary.rs:109`, called from `run_epoch.rs:395` with a fresh bus from `:148`).

### 2f. Determinism

The plan is a function of the proposer's own state only.
`order_hold.rs` imports only `BTreeMap`/`BTreeSet` (`:92`).
`plan` reads the round, the single record, `parents.iter().any(..)` (order-insensitive) and a `BTreeMap` range (`:123-166`).
It has no clock, randomness, hashing order or I/O.
The payload order comes from a `BTreeMap` range rotated at the cursor, a `BTreeSet` filter and `VecDeque::pop_front` (`proposer.rs:1244-1281`).
That state depends on message arrival, which is expected: no other validator recomputes this node's payload.

### 2g. The scope file's questions

1. Can the hold stall a proposer?
   No permanent stall while later own headers commit (2c).
   A max-delay re-send cannot create a blocker: it re-sends only the newest header, and the guard at `proposer.rs:1507` keeps a header at or below `committed_own_round` out of the tracked set.
   A restart starts empty, and `record_resent` gives floor = the header's round.
   A round jump makes every older tracked header with digests a blocker until the next own commit, by design.
   Not every lane stays held indefinitely: empty headers commit, and their notices release lanes.
   The quota: a held digest's #1794 slot sits on each peer's ledger from the seal's quorum and is freed only at commit or age-out, so held digests keep their slots.
   Being put into a header frees nothing.
   The hold backs up into the RPC only through lead L-1.
2. Can a Byzantine minority make an honest proposer hold?
   Only together with a slow honest voter, and not beyond main's worst case.
   The levers (S1's analysis; magnitudes are inference):
   - Withhold votes so that T is cancelled.
     Main: T's digests ride N+1 and N carries newer ones out of order.
     Hold: N leaves T's lane queued and the lane waits about one header.
   - Time the deciding vote so that T certifies just after N's parents were taken.
     Main: no cost, since T commits on its own.
     Hold: T blocks its lane until T commits or an own commit at or above its round, about 2 to 4 rounds per event.
     Repeated every round, that is about one full header per 3 to 4 rounds.
   - Never cite the victim's certificate.
     Neither side pays: if N cites T, T is a proven ancestor, and six honest nodes cite T anyway.
   - Force a round jump.
     Main: old headers are re-queued at the next own commit.
     Hold: newer digests wait for that commit too.
     The jump needs honest progress ahead of the victim.
   Reading B of question 9 caps the second lever's effect at the min delay.
3. Header validity and determinism: confirmed (2b, 2f).
   The hold uses `BTreeMap`/`BTreeSet` only, and the switch is a local parameter.
4. Does the real drain equal the model's?
   Yes, line for line (`order_hold_model.rs:680-703` against `proposer.rs:1244-1281`): lane rotation without held lanes, `max_depth` over unheld lanes, slot order, cap, a cursor that does not move when nothing is served, FIFO.
   The re-queue paths match: the same cancel guard, oldest-first prepend, and `forget` beside every removal.
   The record is placed as in the model, at drain time (`proposer.rs:1408-1417`), which closes the HD-2c exclusion E5.
   The header enters the tracked set only at its result (`:1517`).
   That window is safe because no plan, drain or re-send runs while a header is pending (`:1682-1686`), a cancel for N needs a newer own header, and a failed proposal ends `run` through `?` (`:1665`).
   The guard at `:1507` closes exclusion E1 within one proposer instance; across a restart, finding 3 remains.
   Coverage: `test_order_hold_stale_resend_is_never_a_blocker`, `test_order_hold_max_delay_resend_keeps_the_record`, `test_order_hold_restart_reproposal_records_its_header`, `test_order_hold_survives_a_dropped_cancel_report`, `test_order_hold_releases_the_lane_when_the_notice_settles_the_blocker`, `test_order_hold_carries_unproven_through_the_chain_and_round_jumps`, `test_order_hold_holds_nothing_on_an_intact_own_chain`.
   The drain-to-result window is covered by argument only.
5. Switch off = main byte for byte: yes (2a).
6. Restart and epoch boundary: 2e.
   HD-3's counters see held digests at the boundary on the validator path; a node leaving the committee counts only batches.
7. The hook: compiled out unless tn-types has `test-utils`, and images are built with `-p telcoin-network`.
   With the variables unset, the environment is read once through a `OnceLock`, the hook returns `None`, and the certifier takes no await, log or new branch (`types/src/test_hooks.rs:226-241`, `:390`; `certifier.rs:141`, `:870`).
   When set, it only delays this node's own certificate.
   It signs, stores, sends or cancels nothing that the unhooked path would not; `before_store` makes the formed certificate cancellable, which is its purpose.
   The certifier's run loop never awaits it (the hold runs in the spawned proposal task, `certifier.rs:920-929`).
   A malformed value logs a warning and turns the hook off; nothing panics (`test_hooks.rs:378-430`).
8. Unbounded growth:
   - The order record is one `Option<ChainRecord>`.
   - `proposed_headers` is bounded as on main, slightly tighter with the guard.
   - `lane_seqs.out` and `proposed_first_received` are bounded by the tracked headers times the cap; held digests are not in them.
   - The queue is the only thing the hold grows.
     It has no cap on main either.
     With the hold it grows when the seal rate exceeds the cap times the share of headers that are not held.
     Entries are about 100 B, but the epoch close loads every uncommitted own batch body into one `Vec` (`close_epoch.rs:446-448`), and the peers' ledger interaction is lead L-1.
   - CPU: `plan` is O(tracked × 10) per header.
9. Which digests trigger a header: the next section.

## Question 9: which digests trigger a header

### What the code says

Known from code:
- The trigger is `enough_parents && (max_delay || (advance_round && (enough_digests || min_delay)))` (`proposer.rs:1711-1713`), the same formula as main's.
- `enough_digests` sums every lane (`:1223-1225`, `:1708`).
- The min-delay interval is reset at every proposal result (`:1497`) to 1 s, or to 0 when this node leads the next even round (`:702-711`).
  Its comment (`:697-701`) gives the reason for the odd-round delay: "so the certifier has time to certify the previous (possibly batch-bearing) even round header before it gets canceled".
- Parents of a higher round fire the min delay at once (`:905`, the Greater arm, a round jump).
- A late own certificate of the current round is added to `last_parents` by the Equal arm (`:927`).
- `plan` is pure and takes `&self` (`order_hold.rs:123-166`).
- With the switch on, a blocker stays until it leaves the tracked set (commit, notice, cancel).
  A missing own parent makes the floor the header's own round (`:142-149`).
- On the fleet each validator has one worker, so a held header is empty, and empty headers never block.
  A new blocker appears only at a digest-carrying header R whose successor is built before R's own certificate is among the parents.

### The three readings

| | (A) as built: every queued digest | (B) only digests outside held lanes | (C) what main would count |
|---|---|---|---|
| Far node, full load, during a hold | main's cadence, empty headers | min-delay cadence (1 s), empty headers; leader headers (min delay 0) and jumps fire at once | as A |
| Far node, full load, right after release | R+1 fires on parents, before R's certificate can arrive: a new blocker whenever it is late | R+1 waits until R's certificate joins the parents (the plan is recomputed on every loop), the min delay runs out, or a round jump fires it (then R blocks, as under A) | as A |
| Light load | a held backlog of 5 or more fires before main would; self-feeding after release if the backlog stays at or above the threshold | as main | about as main |
| Other validators | no change | this node's odd-round headers come up to 1 s later during a hold; leader headers are never delayed; the others reach quorum 7 of 10 without it | no change |
| Self-feeding (new blockers) | most | least | as A at full load |
| Byzantine minority | can turn a late certificate into a hold of one commit latency | its pull on the victim's cadence stops at the 1 s min delay, the idle-node rate on main | as A |
| "Header contents only, no timing change versus main" | false: earlier at light load | false: up to 1 s later, never for leader or jump headers | roughly true, but needs a shadow count of main's queue, which is undefined once re-queues diverge |

### Recommendation: B, narrowed to the previous header

With the switch on, leave held digests out of the trigger count only when the only blocker is the own header of the previous round, the one whose certificate can still arrive.
Otherwise count every queued digest, as built.

Why:
- Known from code: under B, a node whose only lane waits on its previous header uses main's own idle-node path, and that path's stated purpose is to give the certifier time to certify the previous header.
  B restores that purpose exactly when the hold is at stake.
  As built, the node skips it because of digests it cannot carry.
- Known from code: when the blocker is older than the previous round, it can leave only through a commit notice or a cancel, and neither depends on waiting.
  Plain B would slow the node to the 1 s cadence for nothing during a long hold, and delay the own commit that ends it.
  The narrowing keeps main's cadence there.
- Inference: B creates a blocker only when the own certificate takes longer than the next round's parents or the min delay.
  A creates one whenever the certificate is slower than the next round's parents.
  So B should cut how often a far validator's lane is held, which is the cost accepted residual (c) leaves unmeasured.
  How much depends on the far validators' certificate latency, which nothing logs today.
- Inference: C keeps A's self-feeding at full load, where the problem occurs, for more code.
- Cost: B breaks the design's "no timing change" statement in the other direction, by at most the min delay, and never for leader headers or round jumps.
  That statement must be reworded whichever reading is chosen, since A already breaks it.

Sketch, about 20 lines in `proposer.rs`, no patch here:
- Add `fn trigger_digests(&self) -> usize`, used at `:1708` in place of `pending_digests_len()`.
- With `order_hold` `None` or without enough parents, return `pending_digests_len()`.
- Otherwise plan for the round `propose_next_header` would use, `max(self.round + 1, primary_round() + 1)`, with `&self.last_parents`, `&self.proposed_headers` and `&self.authority_id`.
  That is the same input the drain will see, since the parents are taken right after.
- If `plan.blockers` is exactly `{round - 1}`, return the queued digests outside `plan.held_workers`; otherwise return `pending_digests_len()`.
- Add the count to the `header proposed` line (`pending_unheld`).
  Flip the assertion at `proposer_tests.rs:4247` and add a test that a backlog held behind the previous header does not build before the min delay or that header's certificate.
  Reword `order_hold.rs:85-86`, `proposer.rs:1704-1707` and `config/src/node.rs:454-456`.

What a fleet run must measure (switch off, A and, if built, B on the same fleet):
1. Blocker creation per validator: the share of digest-carrying headers whose next header has `own_parent=false` or a round gap.
2. Hold length: runs of `held > 0` / `blockers > 0` in rounds and in ms; the rate of `tn_primary.headers_held_total`; `tn_primary.digests_held` returning to 0.
3. Far-lane throughput: batches per header, digest wait p99, `requeued`, and `tn_primary.requeued_out_of_order_total`, which should stay near 0.
4. Cadence: header interval, the `reason` mix, round jumps, and the max-delay warnings per validator.
5. Effect on others: the far node's leader-round header time and the commit/skip rate of its leader rounds; overall landed tx/s and land latency p50/p99 per generator.
6. Lead L-1: `tn_worker.batch_reports_over_quota_total` on the far validators.
7. Not logged today: own-certificate latency relative to parent arrival.
   `own_parent` stands in for it.
   A Byzantine vote-withholding case needs an e2e test; a fleet run cannot show it.

If B is not built before the image, run A and read item 1.
The share of `own_parent=false` after a digest-carrying header on the far validators is what B would mostly remove.

## What was not examined

- Nothing was compiled or run.
  The gates are taken from the unit checkpoints: HD-2b reports check, fmt, clippy and nextest green on its tree, and HD-2c the model's long hunt green.
- The model test was compared on its drain, build and re-queue paths only.
  The bodies of properties P1 to P5, the GC residual classifier and the long hunt were not re-read.
  The test files were read only where a question needed them.
- `proposer_tests.rs` was read only for the golden test and the hold tests named above.
- The worker's #1794 ledger, quorum waiter and batch store were read only by the RF-5 verifier, for finding 2 and lead L-1.
- Security agents not started, with reasons:
  - cryptography: no signature or hash code changed;
  - contract safety: no Solidity;
  - dependency audit: no `Cargo.toml` changed;
  - STRIDE and DREAD: no new message, identity, key or privilege surface, and the one adversary lever was quantified in the consensus-safety pass;
  - the iterative logic audit: the rule's logic is covered by HD-2c's property model, plus the drain comparison and the consensus pass.
- Other topics' code in the worktree, except where this topic calls it or is called by it.
- The e2e design in the design's §4 and the benchmark arm (U5) are not in this commit list.
