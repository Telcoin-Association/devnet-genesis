# Review: parent-grace (bench 6, issue #1803)

Commits: `5c1c28720` feat(config): add the parent_grace switch; `80584c6f6` feat(primary): wait a bounded parent grace for
last round's authors. Branch `bench/bench6-2026-11`. The scope was written at `dc7855cc6`; the branch has since moved to
`31ef1149c`, but `proposer.rs`, `metrics.rs` and `proposer_tests.rs` are unchanged since `dc7855cc6`. Line numbers are
`crates/consensus/primary/src/proposer.rs` at `31ef1149c` unless another file is named. In `crates/config/src/node.rs` the
switch now sits at 424 (field), 558 (default) and 726 (`switches()`).

How this was produced:
- The repository's code review (`tn-review`) and security evaluation (`tn-security-eval`) ran on the two commits.
- For the security evaluation, these evaluators ran: consensus safety, state transitions (scoped to the proposer's
  in-memory state), DoS, determinism, nemesis, DREAD and STRIDE. Contract safety, dependency audit and crypto correctness
  were not started: the diff has no Solidity, no `Cargo.toml`/`Cargo.lock` change and no cryptographic code.
- Both skills' verification steps ran inline and read the claims before the code. So the merge step added one blind
  verifier per Medium finding. Each blind verifier got only a neutral question and the code, never the claim.
- I checked the key mechanisms against the code myself as well: the run loop, `process_parents`, `ParentGrace`, the
  voter checks, the `tokio::select!` macro, and the two tests the findings cite.

## Verdict: CHANGES REQUIRED

There is no Critical or High finding. The grace is consensus-safe: no fork, no rejection between honest validators, no
change to anything other validators recompute.

One Medium finding (M1) should be fixed before the benchmark image. As built, an honest far validator falls out of a
node's grace the first time its certificate misses that node's grace window, and it stays out. That is the bench-5 drift
regime, the one the grace exists to remove, so the run would test a weaker grace than the one the issue designs. The fix
is small.

A second Medium (M3) needs a decision before the image but no code: the grace also arms on almost every loaded round, so
the "loaded cost ≈ 0" claim and the pass criterion built on it are wrong. The third Medium (M2) and the Lows can wait for
the upstream PR.

Counts: 0 Critical, 0 High, 3 Medium, 5 Low, 7 Info.

## Findings

### M1. Medium, CONFIRMED. An author that misses one header drops out of the grace and does not come back
Fix before the benchmark image.

Where:
- `proposer.rs:854`: the `Less` arm only counts the certificate.
- `proposer.rs:2257-2272` (`on_proposed`) and `proposer.rs:2287-2294` (`missing`).
- `proposer.rs:2105`: the rule as documented.
- Test `test_parent_grace_ignores_authors_absent_from_last_header`, `proposer_tests.rs:2844`.

What the code does:
- The grace waits only for the authors whose certificates the node's last own header actually carried.
- A round-(r−1) certificate that arrives after the round-r header went out takes the `Ordering::Less` arm, which only
  increments `tn_primary_late_parents_total`.
- The issue's option A specifies a different rule: wait for authors "live in round r−1, meaning it holds their
  round-(r−1) certificate" (issue body line 138).

Sequence:
1. Node X waits for far validator F's round-r certificate. F's certificate arrives after G: one quorum excursion, a skipped
   round, a restart or an epoch start is enough. The grace expires, or ends `preempted`.
2. X's round-(r+1) header goes out without F, so F is not in X's basis for round r+1.
3. F's round-r certificate arrives at X after that header went out. It takes the `Less` arm and is only counted.
4. In every later round, X is ready as soon as its quorum arrives. F's certificate arrives after that, because F is the
   late author. X never arms for F again.
5. F gets back in only if its certificate happens to beat one of X's proposals unaided, for example while X is held by a
   grace for another author.
6. Each near node drops F on its own first excursion. Once fewer than a quorum still wait for F, the network runs ahead of
   F again, and F drifts and jumps as in bench 5.
- No multi-round test and no re-entry test exist.

Suggested fix:
- In the `Less` arm, when `round + 1 == self.round` and the basis (or the in-flight header) is of `self.round`, add the
  late certificates' origins to the basis.
- While a header is pending, stash them in `GraceInFlight` and merge them in `on_proposed`.
- Add a re-entry test: round r expires without F; F's late certificate arrives; the round-(r+1) header waits for F and
  carries it.
- Trade-off to state in the PR: a live author that is always later than G then costs G every round, which is the bound
  the issue already states. A crashed author still costs G once, because no late certificate of its arrives.
- With the fix, a node's own certificate can only re-enter its basis through a race: the certifier cancels the previous
  own header once the next one is sent. No new self-delay follows.

### M2. Medium, CONFIRMED mechanism, PLAUSIBLE trigger. A round jump during a grace strands the held header; if the node leads that round, the round's leader is lost
Fix before the upstream PR. It is cheap to fold into the M1 change. Covers the code review's PG-3.

Where:
- `proposer.rs:812-844`: the `Greater` arm.
- `proposer.rs:1505`, `2159-2164`: `end_if_round_moved`.
- `proposer.rs:1168`: the next header is built at r+2.
- Leader timing: `proposer.rs:640-650` (`calc_min_delay`), `656-664` (`update_leader`), `618-629` (`calc_max_delay`).
- Test `proposer_tests.rs:3049-3067`.

Sequence:
1. Node L leads round r+1. With its zero min delay it is ready on the round-r quorum and arms a grace for a missing
   basis author.
2. Before the deadline, a quorum of round-(r+1) certificates from nodes that did not wait reaches L.
3. The `Greater` arm moves L to round r+1 and `end_if_round_moved` ends the grace as `preempted`. L proposes round r+2
   at once.
4. L's round-(r+1) header is never built; the max-delay re-send cannot build it either (1360).
5. At round r+1, every proposer, L included, finds no leader certificate in `update_leader`. All of them wait out the
   max delay (1 s on the fleet, `parameters.yaml`), and that leader is never committed.
6. For a non-leader the same sequence skips its own r+1 header. Its round-r certificate loses the reference from its own
   strand.
- With G = 0 a ready header goes out in the same pass. A similar skip already exists through the accepted
  `handle_proposal_result` quirk (1297). The grace adds a new and more frequent window of up to G.

Trigger:
- It needs basis asymmetry. If the round-(r+1) certificates referenced the certificate L is waiting for, L would fetch
  that certificate first and the grace would end `complete`.
- M1 produces exactly that asymmetry.
- It also needs the round-(r+1) quorum to reach L within G of its readiness. The devnet margin is about 117 ms at
  G = 150 in steady state. On a single-region committee, where certificates form in tens of milliseconds, the margin is
  gone whenever the asymmetry exists.

Suggested fix: do not arm the grace when this node leads the next round (`calc_min_delay().is_zero()`); the far
certificates still ride the non-leader headers. Alternatively, propose the held header before taking a newer round. The
issue says the grace "applies to leaders too", so this needs a human decision. Also document that G must stay below
next-round certificate formation.

Bench guard until fixed: watch for `parent grace ended outcome=preempted` on rounds the node leads, and for max-delay
warnings.

### M3. Medium, CONFIRMED mechanism, PLAUSIBLE size. Under load the grace arms on almost every round
Decide before the benchmark image. No code change is needed if the cost is accepted. The code review's verifier rated
this Low because it follows the arming rule as designed; I raised it because the topic's cost claim and its bench pass
criterion depend on it.

Where:
- `proposer.rs:1484-1486`, `1514`: `hold` is reached from either readiness branch, the digest threshold or the min delay.
- `proposer.rs:2169-2211`, `2257-2272`.
- `aggregators/certificates.rs:83-98`: the first stake quorum is sent as one message, later certificates one by one.
- Issue body lines 142-144.

Sequence:
1. Under load the header is ready the moment the quorum message arrives. Either the digest threshold is met (5 on the
   fleet) or the min delay has already elapsed.
2. Every basis author outside that message is missing by construction, so the grace arms.
3. A grace that ends `complete` leaves every live author in the basis, so the next round arms the same way.
4. The leader of the next even round has a zero min delay, so it arms the same way. Its wait sits on everyone's critical
   path through `update_leader`.

Cost per round: the gap from the quorum to the last basis certificate, at most G. The issue's "under load ... the wait
almost never runs and the cost is about 0" does not follow from the code. The pass criterion "loaded rounds and
throughput unchanged within noise" can fail for this reason alone. M3 also makes armed leader graces frequent, which
raises M2's exposure.

Suggested fix:
- Correct the cost claim in the issue and the PR text.
- Make the loaded arm's analysis read `tn_primary_parent_grace_wait_seconds`, `tn_primary_parent_grace_total` and
  `grace_ms`.
- Whether to arm only on timer-paced rounds is a design decision. Not arming when `enough_digests` holds would let drift
  return under load.

### L1. Low, CONFIRMED (re-derived blind). Readiness can drop while a grace is armed, so the hold can exceed G
Before the upstream PR.

Where: `proposer.rs:882`, `711-716`, `2144-2153`; `consensus/leader_schedule.rs:289-294`.

Sequence:
1. `ready()` reruns on every parents message, including the `Less` arm, and reads the live leader swap table.
2. Bullshark replaces that table about once per schedule window.
3. If the swap lands within G, `should_create_header` turns false and `hold` is no longer reached.
4. The deadline fires and `expire()` leaves the grace with no timer.
5. The header waits for readiness to return or for the max-delay tick, and the outcome is recorded as `preempted` with a
   wait longer than G.

The max delay still bounds it. Fix: latch readiness once a grace arms, or end the grace with its own outcome when
readiness drops.

### L2. Low, CONFIRMED. `parent_grace` is never validated and is capped silently
Before the upstream PR.

Where: `node.rs:424`, `580`, `632` (no check); `proposer.rs:2134` (the silent cap); `node.rs:726`.

What happens:
- Any G is accepted and silently capped at `max_header_delay`.
- `switches()` and the `node switches` line report the configured value, not the effective one.
- For a node that leads the next round, the effective cap is `max_header_delay / 2`, because its max-delay tick is halved.

Fix: reject G ≥ `max_header_delay / 2` in `validate_operational_floors`, and log the effective value.

### L3. Low (documentation), CONFIRMED. D38 understates what one author can do
Before the upstream PR.

Where: `tasks/bench6-g1-notes.md:334-336`; `proposer.rs:2176-2177`, `2257-2272`.

- An author whose certificate arrives just inside G ends the grace `complete`. Its certificate rides the header, so the
  author stays in the basis.
- One author alone can therefore cost about G every round, under the healthy-looking `complete` outcome.
- "Every other round" holds only for an author past G.
- The issue body already says this; D38, which is meant for the PR text, does not.

Fix: reword D38 and the PR text.

### L4. Low, CONFIRMED. The grace log lines cannot name the author that delays the network
Before the upstream PR. Cheap and worth adding with the M1 fix, so that the M1 and M3 behaviour can be attributed in the
run.

Where: `proposer.rs:2195-2202` and `2222-2228`, where `missing` is a count, at debug level.

- A delayer inside G shows outcome `complete` and a normal committed share, so the certification analysis that D37
  relies on cannot see it.
- This gap is separate from D37's late-parent counter.

Fix: log the authors waited for on `parent grace armed`, and the authors still missing on `parent grace ended`.
Consider info level for `expired`.

### L5. Low, PLAUSIBLE (not blind-checked). Two far validators can wait on each other
Before the upstream PR; the M1 fix covers most of it.

Where: `proposer.rs:2169-2211`, together with M1.

1. Each far validator has the other in its basis, and the far-to-far link is the longest, so each one's own grace makes
   its next certificate later.
2. After a round in which the near nodes did not wait, that certificate can land after G at all near nodes at once.
3. With M1, the far validators then leave every basis together.

Measure it with the L4 logging.

### Info
- **I1.** `reason` is computed after the grace (`proposer.rs:1534`). A header held past the digest threshold is labelled
  `parents_and_threshold`. After a `preempted` grace the header line shows `grace_ms=0`, and the wait reaches only the
  histogram.
- **I2.** The run-loop `select!` (`proposer.rs:1398-1451`) is unbiased and now has 9 branches instead of 8 (tokio
  `macros/select.rs:625-684, 808`). With the switch off the new branch is always pending, which only shifts which of
  several ready events is polled first (see 2a).
- **I3.** A fresh `sleep_until` is built on every loop pass while a grace is armed (`proposer.rs:1376-1383`, `1448`).
  Negligible.
- **I4.** A grace still armed at shutdown or at the epoch end records no outcome (`proposer.rs:1399-1401`). Outcome
  totals can be lower than the number of `parent grace armed` lines.
- **I5.** PLAUSIBLE. A parent that arrived just before the proposal can cost a voter a `MissingParents` round trip
  (`network/handler.rs:1367-1402`). Read it from the vote-stage `Parents` timing.
- **I6.** Test gaps:
  - No re-entry test (M1) and no leader-case jump test (M2).
  - The jump test at `proposer_tests.rs:3049-3067` does not assert that no round-3 header exists, and its round-3
    certificates have empty parents.
  - All nine tests run a single round on four nodes. The issue's drift regression test is not there.
- **I7.** Not re-derived. One node's interval between headers can reach about 2G (the leader waited, then its own grace
  ran), while the average stays at most G per round.

## Answers to the brief's questions

### 2a. Switch off = before
Yes for behaviour. With `parent_grace: 0s`, header bytes, timing, parents, digests and the execution block are the same
as before. These lines run and did not run before:

Metrics and log fields only:
- `node.rs:424`, `558`, `726`: the field and its zero default. `switches()` adds `parent_grace=0s` to the `node switches`
  line and to the `tn_node_switch` gauge.
- `metrics.rs:161`: the `parent_grace_wait_seconds` histogram, registered by the `Metrics` derive.
- `proposer.rs:308-312` → `2132-2141`: `ParentGrace::new` registers five counters at zero (`parent_grace_total{outcome}`
  ×3, `late_parents_total{origin}` ×2).
- `proposer.rs:854` → `2275-2282`: `tn_primary_late_parents_total` is incremented on every `Less` parents message.
- `proposer.rs:1233` → `479`: `grace_ms=0` on `header proposed`.

No-ops:
- `on_propose` returns at once (2237), so `on_proposed` returns at once too (2258).
- `end_if_round_moved` (1505) does nothing.
- On the max-delay path, `end(Preempted)` returns zero with no metric (2216-2218).
- `hold` returns `Propose(0)` on its first line (2170-2171), so the `continue` at 1515 is unreachable.

One non-metric difference, the new `select!` branch at 1448:
- It is `std::future::pending()`, so no timer is created.
- The `select!` is not `biased`, so it now draws a random start over 9 branches instead of 8. A start on the
  always-pending branch wraps to `rx_shutdown`, which shifts the poll-order distribution (branch 0 first with probability
  2/9).
- That changes only which of several simultaneously ready events runs first, which was already random, and never a
  decision.

### 2b. Mixed fleet
No fork, no rejection between honest validators, no stall. The switch is node-local:
- It is a `serde(default)` field, never hashed or sent. It is read only to build `ParentGrace` and for `switches()`.

It changes only the node's own headers, in ways voters already accept:
- **Later `created_at`.** The proposer clamps it after every parent (`proposer.rs:385-428`), and voters require exactly
  that (`handler.rs:1418-1439`). There is deliberately no lower bound (`handler.rs:1423-1425`), and the lead check only
  refuses headers from the future.
- **More parents.** They are of the same round with unique authors, at most n. They pass `TooManyParents`
  (`header.rs:154-157`, `handler.rs:1240-1244`) and the epoch, round − 1, duplicate and quorum checks
  (`handler.rs:1409-1454`).
- **More digests.** Still capped (`header.rs:166-171`).
- **The execution block.** It is chosen from more parents, so the quorum value can only rise, still capped at the own tip
  (`proposer.rs:1917-1950`), and voters check it as before.

Unchanged: votes, certificates, batches, the certifier and the vote handler. Commit support, reputation and the leader
swap are computed from the certified DAG, so they change identically on every validator.

Effects that are performance only:
- Certificates from nodes with the grace on arrive later at nodes with it off.
- The on/off mix creates the basis asymmetry M2 needs. On the devnet that stays inside the about 117 ms margin at G = 150.

### 2c. Liveness under the switch
Every armed grace ends in a proposal or in a jump:
- `complete` (2176);
- `expired`: the deadline branch (1448-1450), then the next `hold` (2179);
- `preempted` by the max-delay tick (1511);
- `preempted` by a round jump, including the empty-parents jump (1505, 2159-2164).

`should_create_header` stays true while a grace is armed:
- `ready()` only gains as parents are added.
- `enough_parents` falls only on a round change, which ends the grace.
- The digest count and `min_delay_timed_out` only grow until a proposal.
- The exception is L1.

Nothing is dropped:
- Digests stay in the lanes and the re-queue paths are untouched.
- The max-delay re-send cannot run beside a grace, because it needs `!should_create_header`.
- The proposer has no vote path.
- The certifier cancels the previous own header later than before, which helps that header.
- The epoch close does not depend on the grace.

What can now fail to make progress:
- M2: the node's own round-(r+1) header is never built. Its digests ride round r+2. If the node leads r+1, the committee
  waits out the max delay (1 s) and that leader is never committed.
- L1: a hold beyond G, bounded by the max delay.
- M1 is not a liveness loss but a loss of the grace's benefit.

### 2d. Byzantine or slow peers
New capability: any validator in a node's basis, not only a leader, can delay that node's header by up to G per round by
choosing when it publishes its certificate. Before this change, a non-leader cost nothing (2f+1 proposals ignore it);
only a Byzantine leader could cost up to `max_header_delay` on its own rounds.

How it plays out:
- **Just inside G:** every round, about G each time, outcome `complete`, author not identifiable (L3, L4). That is up to
  +43 % round time at G = 150 against a 350 ms round.
- **Just past G:** G once, then the author is dropped (M1). Alternating gives every other round.
- **After the M1 fix:** an author that is always past G costs G every round, as the issue states.
- **f colluders:** they face the same single deadline per round, so they cost no more than one author.

Bound: at most G per node per round. There is one grace per parents round (2187, 2210), a fixed deadline (2207) and
max-delay preemption (1511). Exceptions: M2 (a lost leader round costs `max_header_delay`) and L1 (rare).

A crashed validator costs G once, because it is not in the basis the next round.

### 2e. Restart and epoch boundary
All grace state is in memory (`proposer.rs:192`); nothing is persisted, and a held header is not built, so `LastProposed`
is never involved.

Restart:
- `new()` starts with no basis (2132-2141), so the first header after a restart never arms.
- The restart re-propose branch (1191-1225) keeps only the authors the stored header carries (2261-2266), or none.
- The max-delay re-send (1543-1563) keeps the current basis (2257-2260).

Epoch change:
- The proposer is built per epoch (`primary.rs:109-115`), so the grace starts empty.
- Certificates of another epoch are filtered before they reach the parents (785-807).
- A grace armed at the boundary is dropped without an outcome (I4).

### 2f. Determinism
Nothing new reaches consensus-visible data through iteration order, wall-clock time or thread timing:
- The grace state is `BTreeSet`s plus tokio's monotonic `Instant`, and none of it enters a header. `grace_ms` is a log
  field.
- The grace changes when a header is proposed and which certificates it carries. Both were already local timing, and
  both are certified before anyone builds on them.
- Commit support, reputation, the leader swap and ordering read only the certified DAG.
- The `select!` randomness (I2) is local.

### 2g. The scope's questions
**1. Bounds.** All confirmed in code:
- Cap: `grace.min(max_header_delay)` at 2134. A node that leads the next round has a halved max-delay tick (618-629),
  which ends its grace first (1511).
- Deadline: arm time + G (2207).
- No grace for the first two headers of an epoch: `on_propose` drops round-0 parents (2242), so the round-1 header leaves
  no basis (2267-2268) and the round-2 header cannot arm. Round 3 is the first that can.
- No grace after a jump (2288), after a restart or after a promotion.
- Early ends: `complete` (2176; it wins over `expired` in the same pass) and `preempted` (1511-1512, 2159-2164).
- Re-arming for the same round is blocked by `last_armed_round` (2187, 2210).
- No path waits past the max-delay tick. Only L1 waits past G.

**2. Which parents.** Waiting only adds same-round certificates with unique authors, and voters accept that (2b). A voter
that lacks such a parent fetches it: a delay (I5), not a rejection. Bullshark's commit needs f+1 support from next-round
certificates, so extra parents only add support. Reputation and the leader swap are pure functions of the certified DAG,
so they change identically everywhere. That change is the design's intent: the far validators' certificates commit and
their scores recover.

**3. Other topics in `proposer.rs`.** The grace holds no execution reference and no digest beyond what those topics
assume.
- `quorum_exec_block`:
  - The inputs are built after the grace (1247-1252), and the ring is read just before `Header::new` (431). The block a
    held header names is chosen when it is finally proposed, not when the grace armed.
  - Extra parents only raise the quorum value, which stays capped at the own tip.
  - Waiting for the own certificate fires `on_certified` more often and leaves fewer certifier cancels, so the adaptive
    policy opens fewer starvation windows. Those windows are counted in rounds; the slow self-certification shows up as
    waits of up to G instead.
- `digest_dedupe`: during a grace the digests stay in the lanes and in the `pending` index. `in_flight` fills only at the
  drain, after the grace (1103-1105), and clears at 1307-1309. Nothing in it depends on time.
- Digest-wait accounting: the grace is included in `oldest_digest_wait_ms` (447-463), and `grace_ms` on the same line
  separates it out. Digests are held for at most G, longer only under L1.
- The `reason` label is computed after the grace (I1).

**4. D38.**
- The bound "at most G per node per round, never above `max_header_delay`" is right, except for M2 and L1.
- "One author every other round" is right only for an author past G. Just inside G, one author alone costs about G every
  round (L3); two alternating authors also reach every round, but one is enough.
- After the M1 fix, a past-G author also costs G every round.
- A cheap per-author cap does not work. A streak rule cannot tell a griefer from the honest far validator: both end
  `complete` with a wait equal to their lag. f colluders can also rotate around any per-author limit.
- Levers that do work:
  - Keep G at or below the largest one-way delay and below next-round certificate formation, which also closes M2.
  - Name the waited-for authors (L4).
  - Optionally, a node-wide budget, for example a burst of G refilled by about 60-75 ms per round. That would cap a
    sustained griefer near +20 % without touching a far validator whose mean wait is below the refill.

**5. The own certificate in `missing`.** A node whose own headers fail to certify does not delay itself every round:
- The node is in its own basis only if its last header carried its own certificate (2257-2272). One failure costs at
  most G, the next header lacks the own certificate, and the round after does not wait for it.
- A node whose headers never certify is never in its own basis.
- It waits for itself every round only when its own certificate forms late but inside G each time. That is the intended
  far-validator case, and it also gives the own header up to G more to certify before the certifier cancels it.
- The M1 fix does not change this, because an own certificate cannot normally arrive after the next own header.

## Not examined
- Nothing was compiled or run. Tests were read, not executed, because cargo was off-limits.
- Fleet-level dynamics were not modelled: the size of M1's drop rate, M3's loaded cost and M2's margin rest on the issue's
  numbers and the fleet `parameters.yaml`.
- The certificate fetch path (`state_sync`, the certificate validator) behind M2's trigger condition.
- Bullshark and `order_dag`, beyond commit support and reputation.
- Gossip delivery timing and the histogram bucket configuration.
- Other topics' commits, except where they meet this topic in `proposer.rs`.
- The later e2e commits on the branch (`8bd68e514` runs a mixed-switch fleet with `parent_grace: 150ms`; also
  `4e9c19782` and `31ef1149c`).
- L5 and I7 were not blind-checked.
