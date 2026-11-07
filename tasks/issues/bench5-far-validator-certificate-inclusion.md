# At light load the two European validators drift a little further behind the round every round, so most of their certificates are never committed and their users wait about 20 s per transaction

## Problem

At light load London (validator-02) and the Netherlands (validator-06) certify about 99.5 % of their own headers, but only 13-18 %
of those certificates are ever committed. The rest are orphaned: no header of the next round lists them as a parent, so no
leader's causal history reaches them. A batch in an orphaned header waits for the proposer's `Repropose N batches in undelivered
headers` re-queue, which happens about every 20 s and at the same millisecond on both nodes. Their generators land in
synchronized bursts with a p50 of 14-19 s, while the other eight land in 1.3-2.0 s.

The re-queue runs on no timer. The far pair drifts. Every non-leader proposes exactly `min_header_delay` after its own previous
header. The leader of the next even round proposes without waiting. The eight nearer validators each lead about one round in 16,
so the network averages 345.7 ms per round. London and the Netherlands never lead, because the reputation table has swapped them
out of every leader slot. They run at 353 ms per round and lose 7.4 ms per round. Their certificate already reaches the
Asia-Pacific majority after it has proposed, and only Ashburn (sometimes LA) picks it up while the lag is still under about 40 ms. After about
six rounds even Ashburn misses it. After about 60 rounds the lag reaches a full round. A quorum of the next round then arrives
before their own timer fires, so they skip a round and propose at once. For a few rounds they are back in phase and their
certificates are referenced and committed. That first own commit is what re-queues the digests stranded since the previous
jump. The cycle then starts over.

Under load the round is set by parent arrival (443 ms at 600 × 4, 746 ms at saturation), not by the timer. Nothing drifts, the
far certificates arrive inside the round, and 76-99.7 % of them commit.

## Evidence

Run r20261107-1504: ten validators in ten regions, one per region, `min_header_delay` 350 ms, `max_header_delay` 1,000 ms,
`gc_depth` 50, quorum 7. Times are UTC. Window light8 = 16:18:24-16:24:24 (8 senders per generator), light16 = 16:38:21-16:44:21,
load600x4 = 16:58:16-17:04:16 (A4n windows). Sources: A2/certification.md, A6/stages.md §3 and §6, A4n/leader-serve.json, and a
pass over the unit stdout logs of all ten validators for the three windows (`header proposed`, `quorum reached`, `received
parents`, `digests resent`, `Repropose`, `certificate committed`, `scheduled leader`, `Bad node`).

User-visible cost (A6 §3a, A2):
- light8 / light16 chain seen p50 per generator: London 14.49 / 18.72 s, Netherlands 14.48 / 18.73 s, the other eight 1.26-2.02 s.
  Stage S5 (first header to the quorum of the header that finally carried the batch) is 12.6 / 13.0 s (light8) and 16.8 / 17.2 s
  (light16) for v02 / v06 and 132-224 ms everywhere else. Little's-law ratio 1.00-1.04, so the latency is real. Their senders are
  window-blocked behind it and land 8-9 tx/s against 59-93 for the others.
- Own certificates committed: idle 25.6 / 25.0 %, light8 18.1 / 17.7 %, light16 13.3 / 15.3 %, load600x4 78.1 / 75.7 %, load_all10
  99.7 / 99.2 % (v02 / v06). Every other node is at 100 %, except Mumbai at 86-89 % at light load.
- Leader share: v02 and v06 led 0 rounds in light8, light16 and load600x4, and 198 / 193 of 12,834 committed leader rounds over the
  whole run. The fair share is about 1,283. They were also the lowest two in bench 4.

The drift, light8 (per-node pace from consecutive own `header proposed` lines; network pace = the 7th proposer of each round):

| node | own leader rounds | mean ms per round | into own leader round, p50 ms | skipped rounds | cert formed p50 ms | lag to the 7th proposer p10 / p50 / p90 ms |
|---|---:|---:|---:|---:|---:|---|
| v01, v03, v04, v05, v07, v08, v09 | 64-75 each | 345.6-345.7 | 224-233 | 0 | 132-194 | −133 … +52 |
| v10 Mumbai | 40 | 347.2 | 227 | 4 | 224 | −67 / −6 / +103 |
| v02 London | 0 | 353.1 | – | 19 | 267 | −4 / +134 / +280 |
| v06 Netherlands | 0 | 353.2 | – | 19 | 271 | 0 / +138 / +282 |
| network (7th proposer) | | 345.7 | | | | |

- Every interval that is not into the node's own leader round is 352 ms p50 on every node. The zero-delay leader round saves
  6.4-6.9 ms per round on average for each near node and nothing for the far pair. Example: Tokyo led round 142 and proposed it
  227 ms after round 141 (`v04:16:16:33.109` round 141, `v04:16:16:33.336` round 142). London proposed 140, 141, 142 and 143
  352-353 ms apart (`v02:16:16:32.737`, `33.089`, `33.442`, `33.795`), even though its round-140 quorum was complete 282 ms after
  its own proposal (`v02:16:16:33.019 received parents … parent_round=140 num_parents=7`).
- The far pair skip the same rounds: 466, 526, 586, 646, 689/690, 746, 786, 846 … (light8), 60 rounds apart while the drift is
  steady. A jump: `v02:16:18:25.264 header proposed round=465 … num_parents=10`, then
  `v02:16:18:25.565 received parents this_round=465 parent_round=466 num_parents=7`, then `v02:16:18:25.565 header proposed
  round=467 … num_parents=7` 0.4 ms later. On the Netherlands it is `v06:16:18:25.567` / `v06:16:18:25.569`.
- Committed London rounds come in contiguous runs that start right after each jump: 467-472, 527-530, 587-592, 647-652,
  691-712, 747-752, 787-790, 847-852, 899-912 … (light8, `certificate committed origin=FKvY…`). The Netherlands' runs are the
  same rounds within one. Those runs cover 17.8 / 17.4 % of the window's rounds, which is A2's 18.1 / 17.7 %.
- The first own commit after a jump re-queues everything stranded since the previous one. `v02:16:18:27.306 digests resent
  count=1 from_round=433 round=471 cause=committed` comes 1.7 s after the jump at 466, with the matching `Repropose 1 batches in
  undelivered headers [433, 434, …]`. The Netherlands logs it at `v06:16:18:27.312`. A2's pair (`v02:16:18:09.329` /
  `v06:16:18:09.339`, `from_round=373 round=419`) is the previous cycle.
- Ashburn carries them. In rounds inside a London run, Ashburn's next-round header holds 8 or more parents 84 % of the time,
  against 16 % outside the runs (LA: 42 % against 10 %). At the last round of almost every run, Ashburn is among the near nodes
  with an extra parent. Ashburn is 44 ms one-way from London; Tokyo, Seoul and Sydney are 117-151 ms away.
- Mumbai shows that the leader slots drive the drift. It skipped rounds only while the reputation table had it in the bad set
  (`Bad node on round 1030: 4zoS… -> 10`, `… round 1150 … -> 7`), and those skips came at 1095, 1155, 1215 and 1275, also 60 rounds
  apart. With its leader slots it keeps pace.
- Each epoch start is a natural experiment. The scores reset, every validator leads, and London's certificates commit without
  a gap: rounds 41-81 of epoch 3 (the extract starts at 41; the Netherlands misses 51 and 71 only), and rounds 2-71 of
  epoch 4. The first schedule change marks them bad (`v02:16:16:09.110 Bad
  node on round 70: FKvY… -> 5`, `Br3W… -> 7`; epoch 4 `v02:16:36:03 Bad node on round 54`). 11-17 rounds later the runs
  begin: epoch 4 shows 107-131, 167-176, 227-232, 281-292, 347-372, the same 60-round cycle.
- load600x4: network 443.3 ms per round, London 444.8 (1.5 ms per round of drift), 2 skips, lag p50 +13 ms. The headers are still
  labelled `min_delay`, but the interval p50 of 423-436 ms shows that parent arrival sets the round, not the timer.

## Mechanism

Line numbers are at 067639def (`bench/main-fixes-2026-11`).

1. **A certificate can only be a parent in the very next round, and only if it arrives before that proposal.** The aggregator
   sends the first 2f+1 certificates of a round, then each later one on its own (`crates/consensus/primary/src/aggregators/
   certificates.rs:24-44`, `:75-102`). The proposer appends a late one only while it is still at that round (`Ordering::Equal`,
   `proposer.rs:761-783`) and drops it once it has moved on (`Ordering::Less`, `:751-760`). Voters reject any parent that is not
   from `round - 1` (`network/handler.rs:1228`), so a round-r certificate that misses every round-(r+1) proposal stays orphaned.
   `order_dag` only follows parents one round down (`consensus/utils.rs:51-56`) and stops at `gc_depth` (`:38`, `:47`).
2. **Arrival.** London's own quorum takes 267 ms (its 6th-nearest voter is Hong Kong at 197 ms RTT, plus vote-path time) against
   132-194 ms for the near nodes. Delivery to Tokyo, Seoul, Hong Kong and Sydney takes another 99-151 ms one-way. Even when London
   proposes in the same instant as the 7th near proposer, its certificate reaches Asia 370-420 ms later, after their next header
   at about 345 ms. Only Ashburn (+44 ms, about 311 ms) and LA (+69 ms) are inside the window, and only while London's lag stays
   small.
3. **Drift.** `should_create_header` (`proposer.rs:1262-1264`) needs the parents, `advance_round` and `min_delay_timed_out`.
   The min-delay interval is re-armed from the node's own proposal (`handle_proposal_result`, `:1100`) with `calc_min_delay`,
   which is zero only when the node leads the next even round (`:559-569`). A node that never leads always waits the full
   350 ms + about 2 ms from its own last header, even when its parents have been in for 70 ms. The near nodes lose about 120 ms
   once in about 16 rounds. The network therefore runs at 345.7 ms per round while the far pair runs at 353.1, so the far pair's
   lag grows 7.4 ms per round and nothing pulls it back.
4. **Reset by jumping, which strands what came before.** When the round-(r+1) quorum reaches a proposer still waiting at round r,
   the `Ordering::Greater` branch (`proposer.rs:718-750`) adopts those parents and resets the min delay at once. The proposer
   skips round r+1 and proposes r+2 immediately (the cert validator's empty-parents hint at `state_sync/cert_validator.rs:158` does
   the same at two rounds ahead). The post-jump header cannot reference the node's own pre-jump certificate, so the own strand is
   cut, and every certificate since the last commit is orphaned for good.
5. **The re-queue waits for proof that the old headers are dead.** `process_committed_headers` (`proposer.rs:803-858`) re-queues
   own headers only up to the highest own round in the current commit (`:807`, `:829`). It receives every commit, but the list is
   empty while no own certificate commits. The rule is exact: once an own round-m certificate commits, `order_dag` never orders an
   older own certificate (`utils.rs:61-65`), so re-queued digests can never commit twice. It is also why the re-queue lands at
   the first in-phase commit after a jump and not before.
6. **Same round, same millisecond.** Both nodes drift identically (no leader slots, 353 ms each, quorum 267 / 271 ms). They are
   12.6 ms apart and equidistant from Asia, so the same quorum makes both jump within 4 ms. The same Ashburn and LA certificates
   carry both post-jump certificates into the same leader's history, and both run `process_committed_headers` when they commit
   that leader.
7. **The reputation table closes the loop.** A validator's score is the number of its committed round-(leader+1) certificates
   that vote for the previous leader (`consensus/bullshark.rs:89-96`). An orphaned certificate scores nothing. The swap table marks
   a validator bad below `highest - 2σ`, up to 33 % of the committee (`leader_schedule.rs:73-103`;
   `DEFAULT_BAD_NODES_STAKE_THRESHOLD` = 33 at `crates/types/src/primary/mod.rs:39`). The schedule changes every 60 sub-dags
   (`crates/node/src/primary.rs:33`), and `leader_with_swap` (`leader_schedule.rs:308-330`) gives a bad validator's slots to good
   nodes. A swapped-out validator loses the zero-delay round (item 3), and the fleet stops waiting for its leader certificate
   (`update_leader`, `proposer.rs:575-584`). That wait used to re-phase it every 20 rounds. So the swap turns a marginal arrival
   into an 82 % orphan rate, and the orphan rate keeps the score at 0 until the epoch ends.
8. **Why load fixes it.** When a round is longer than parent arrival, every proposer, the far pair included, proposes when its
   parents and the leader check are complete. The timer has already expired and does not bind. Phase is set again every round,
   there is no drift, and the far certificates (267 + 44-151 ms) arrive inside a 443-746-ms round.

A round-level model of these rules on the 2026-11-07 UDP matrix (one-way = RTT/2, measured quorum times, 3 seeds × 1,200
rounds) reproduces the pace (345.1 ms) and a jump about every 50-60 rounds. It puts London's committed share at 13-45 % depending on the
delivery overhead assumed (0-40 ms), against 18 % measured. Use it for ranking, not for absolute numbers. Its results are under
each option below.

## Proposal

Options, then one recommendation for bench 6.

**(A) Parent grace on every proposer (upstream #1781, variant 2).** Once a proposer has 2f+1 parents and would propose, it
waits up to G ms for the round-r certificates of validators that were live in round r−1, meaning it holds their round-(r−1)
certificate, and proposes the moment the last one arrives or G expires. It applies to leaders too. This removes the cause: the
network can no longer run ahead of a live validator's certificate, so the drift stops and the far certificates become parents.
Model: v02 / v06 committed 100 % for every G from 100 to 210 ms. The round goes from 345 to 364-404 ms (+5 to +16 %), because
the far certificate now sets the network's phase. That is about +0.07 to +0.19 s on the fleet's light-load seen p50 (S4, S6a and
part of S6b are round-sized). Under load the rounds are already longer than the far arrival, so the wait almost never runs and
the cost is about 0. Choose G from the matrix as a delivery bound, not a vote bound: the largest one-way delay in the fleet is
London-Sydney at 151 ms (301.6 / 2). G = 150 never cuts off a far certificate that formed on time. The 6th-nearest 210 ms is a
vote RTT, already inside the 267-ms quorum time, and the full slowest RTT of 300 ms only adds failure-mode cost. Failure modes:
a crashed validator costs one round of G, because next round it is no longer live. A Byzantine validator that releases its
certificate just inside G slows every round by up to G (+43 % at 350 ms). That is bounded, and the bound is the reason to keep G
small. The change is node-local policy: no wire or validation change, mixed versions interoperate, and the 2f+1 rule and the
leader check stay as they are. It is consensus-observable (headers carry more parents, rounds are longer, and outputs and the
leader schedule change), so it needs its own design row rather than riding under bench 5's §F1/§F3 contract. Cherry-pickable.

**(B) Weak links / late-parent inclusion.** A header may also reference certificates from rounds below r−1 that are not yet in
its causal history, as DAG-Rider's weak edges do, so an orphan is pulled in by the next round. This costs no round time, but it is
a protocol change. The parent-round rule at `handler.rs:1228`, `order_dag`'s one-round-down traversal (`utils.rs:51-56`), the
fetcher and missing-parent checks, the gc bound and the commit sequence all change. It must be fork-gated at an epoch boundary,
and every node must run it. The Sui Narwhal lineage dropped weak links and relies on re-proposing undelivered batches, which is
TN's item 5. Bench 7+ at the earliest.

**(C) Re-queue at the first commit that skips the own certificate (A6 lever 3a).** It gains about nothing. A6's −10 to −14 s
assumed each re-proposal had an independent 18 % chance. The measured commits come in contiguous runs right after each jump, so
a digest re-queued while the node lags rides in another header that is orphaned with near certainty. It gets through in the same
in-phase window as today, which saves at most the 2-4 rounds between the jump and the first own commit (about 1 s). It also
breaks the exactness of item 5. An own certificate skipped by one commit can still commit later through the node's own strand
(its next header references it) within `gc_depth`, so an early re-queue can commit a batch twice. Not recommended.

**(D) `min_header_delay` tuned to the slowest RTT.** It does not remove the drift: the timer still binds at idle, and the zero-delay
leader round saves about 220 ms per leader round at 450, so the far pair loses about 14 ms per round instead of 7. The slack is
larger, so the in-phase share rises, but it does not reach 90 %. Model at 450: 65-83 % committed, 24-30 skipped rounds per 1,000,
round +26 %. At 250 the result is unstable (23-99 % depending on the overhead), consistent with A6's warning that 250 must follow
the fix. No 250 / 350 / 450 arm exists in this (V1Lazy) regime. The stage-1 sweep (r20261006-2058, 50-500 ms) ran before lazy
negotiation halved quorum time; its idle round was 527-550 ms in every arm, and the timer never bound there. Keep 450 as the
bench-6 control arm, not as the fix.

**(E) Leader-election fairness is a symptom, and also the amplifier.** The low share is a consequence: a score only counts
committed certificates, and theirs are orphaned. But the swap is what keeps them orphaned (item 7). At each epoch start, before
the first swap, their certificates commit without a gap. In the model, the same 350-ms fleet without the swap commits 97-100 %
of theirs at an unchanged pace. It is still the wrong place to fix it. The leader schedule must be computed identically by every
node, so any change to scores or swaps is a fork-gated protocol change. The swap also exists to keep genuinely slow or faulty
leaders out of the slots. Once (A) makes their certificates includable, their scores recover and the swap stops on its own.
Revisit only if their leader share stays below about 5 % with (A) in place.

**Recommendation for bench 6: (A) with G = 150 ms, as a node-local proposer policy.** Shape: in `Proposer::run`, when
`should_create_header` becomes true for a new header (not the max-delay path), arm a grace deadline of now + G if any authority
with a round-(r−1) certificate in hand has no round-r certificate in `last_parents`. Keep extending `last_parents` from the
`Ordering::Equal` path as today, and propose when the set is complete or the deadline fires. The max-delay path stays
unconditional, so liveness is unchanged. Two observability items should travel with it: a histogram
`tn_primary_parent_grace_wait_seconds` and a counter `tn_primary_parent_grace_total{outcome="complete|expired"}`, and a counter
of certificates dropped in the `Ordering::Less` branch by origin (`tn_primary_late_parents_total`). The counter is the direct
measure #1781 asks for, and it is cheap enough to cherry-pick before the policy itself. Cherry-pickable: the grace, the metrics
and the late-parent counter. Protocol-level: (B) and any change to reputation or swaps (E). (C) is cherry-pickable but not
worth it. (D) is a parameter.

## Test plan

- Proposer unit tests (`crates/consensus/primary/src/tests/proposer_tests.rs`, paused clock, next to
  `test_proposal_waits_milliseconds_for_future_parents`):
  - Quorum of 7 at round r plus min delay elapsed, with an 8th authority live in r−1 whose round-r certificate arrives 100 ms
    later: the header is proposed 100 ms later with 8 parents. Without the grace it would have 7.
  - The 8th certificate never arrives: the header is proposed at exactly +G with 7 parents, and the expired counter rises.
  - An authority with no round-(r−1) certificate is not waited for: the header goes out with no delay.
  - The max-delay path ignores the grace, and the next-round leader's zero min delay still applies, with the grace on top.
  - Regression for the drift: a scripted 10-node schedule in which one authority never leads and its certificate arrives
    `min_header_delay − 20 ms` after each round's quorum. Without the grace its certificates stop being parents within 10 rounds
    and it skips a round within about 60. With it, it is a parent of every round and never skips.
- Bullshark/DAG test (`consensus/tests/bullshark_tests.rs` style): build a DAG in which one authority's round-r certificates are
  parents of round r+1 only under the grace, and assert that every one of its certificates is in a committed sub-DAG and that
  `process_committed_headers` re-queues nothing.
- e2e with injected asymmetry: a test-only delay (behind `test-utils`) on certificate delivery from one node of a 4-node
  committee (quorum 3) equal to 1.2 × its round time. Without the grace, its certificates are mostly not committed and its
  header rounds have gaps. With G it commits at least 95 % and has no gaps, and rounds per second fall by at most 15 %. No such
  hook exists today (no netem or delay utility in `crates/e2e-tests`). The bench fleet is the real asymmetry test.
- Bench 6 arms: the default with G = 150, a G = 100 arm, and the 450-ms `min_header_delay` control, each idle plus light8 plus
  a short loaded window.

## The fields that prove it (bench 6, light load)

- Per-node committed own certificates (`certificate committed origin=` ÷ own `quorum reached`, A2's method) at 90 % or more for
  v02 and v06 in idle, light8 and light16. Today: 25 / 18 / 13 %.
- London and Netherlands generators: chain seen p50 2 s or less (today 14.5-18.7 s) and S5 p50 under 400 ms (today 12.6-17.2 s).
- No skipped header rounds on v02 or v06 (today 19 each in light8), and `digests resent cause=committed` about 0 on them.
- Near nodes' `header proposed num_parents` mean at 9.5 or more (today 7.2-7.5); `tn_primary_late_parents_total` for v02 and v06
  origins about 0.
- Leader share of v02 and v06 within 5 points of 10 %, with no `Bad node … FKvY…` / `Br3W…` lines after the first schedule.
- Cost bound: network round (7th proposer) at light load 400 ms or less (today 345.7); fleet light seen p50 within +0.2 s of
  bench 5's 1.50 s; grace `expired` under 1 % of headers with all ten alive; loaded rounds and throughput unchanged within noise.

## Related

- #1781 (open): the proposer advances on 2f+1 parents. It names both variants. This run shows that variant 1 (wait for the
  proposer's own certificate) cannot help, because London already includes its own certificate (quorum 267 ms < 352). Variant 2
  is option (A). The drift and the reputation loop are new here.
- Bench 4 F4 / bench 3 F7: the round-floor proposal (`min_header_delay` 400-450). Option (D) explains why a floor alone does
  not reach 90 %: the zero-delay leader round keeps the drift.
- A6 levers 3 and 6: lever 3a (re-queue at the first skip) is re-rated to about 0 here. Lever 6 (`min_header_delay` 250) still
  has to follow the fix.
- A2 §"London and Netherlands at light load", A6 §6: the measurements this issue explains.
- Leader reputation and swap (`bullshark.rs:63-120`, `leader_schedule.rs:60-140`): any change there is protocol-level (E).
