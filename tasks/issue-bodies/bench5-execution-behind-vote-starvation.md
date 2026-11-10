## Problem

A voter signs a header only after its own execution has reached the block the header names (`latest_execution_block`), and
a proposer names its own newest executed block. Since `fix(primary): bound the voter's wait for execution` (F3-6, Refs
#1782) the voter waits at most 1 s for that block and then refuses with the recoverable `ExecutionBehind`. Since F1-1 consensus
no longer waits for execution, so under load the validators' executed heights spread out. The validators that executed
fastest proposed headers naming blocks the other seven had not executed yet, and those seven refused them. At n = 10 the
seven slower validators are a quorum on their own, so every round advanced on their certificates and the fast validators'
headers were cancelled before they collected seven votes.

In the 2026-11-07 run Tokyo, Hong Kong and Mumbai certified 0.2 %, 0.0 % and 16.2 % of their own headers for 8 to 14 minutes
of load. Their users' transactions waited in the pool with no RPC error, and their workers almost stopped sealing batches.

The 1-s bound is not the cause. A header lives one round, about 1 s under load, and the slower quorum reached the named
block 3 to 4 s after the header was proposed. With bench 4's 5-s wait the vote would have arrived after the header had been
cancelled. Any validator whose execution runs more than about a round ahead of 2f others is starved for as long as the other
2f+1 can certify without it, and up to f validators can be starved at once.

## Evidence

Run r20261107-1504: ten validators in ten regions, 600 senders per generator, window 16. Times are UTC on 2026-11-07. The
window load_all10 is 17:41:32-17:54:44, the loaded phase before a validator was killed. Numbers are from the run's analysis
(certification and vote path, stage latency, recovery, execution cost), summarized in the bench-5 report, finding 4
(https://benchmark.telcoin.network/runs/r20261107-1504/report.html); the traced lines are from the validators' unit logs.

Certification in load_all10:
- validator-04 (Tokyo) certified 2 of 918 own header rounds, validator-08 (Hong Kong) 0 of 918, validator-10 (Mumbai) 149 of
  918. The other seven certified 914 to 918.
- no own certificate on validator-04 for 787 s (17:41:50.404 to 17:54:57.757), on validator-08 for 817 s and on
  validator-10 for 487 s. Their generators landed nothing for 802, 853 and 491 s before the kill and resumed 7 to 13 s
  after it.
- the three were the fastest executors. Average execution lag was 6.4, 6.5 and 9.1 rounds against 12.6 to 13.5 for
  validator-02, -06, -07 and -09 and 22 to 31 for validator-01, -03 and -05. Their per-transaction execute cost was 84 to 86
  µs against 87 to 97 µs on the others, so a 2 to 4 % difference was enough.

Who refused (voter-side `vote path timing`, load_all10). For validator-04's 918 header rounds only validator-08 (861 votes)
and validator-10 (542) voted reliably. validator-02, -06, -07 and -09 voted 74 to 104 times and refused 676 to 683 times
each, validator-03 voted 32 times and refused 615 times, and validator-01 and -05 never voted (537 and 554 refusals). Every
refusal was `outcome=behind` with `exec_wait_ms` 1000 or 1001. validator-08's and validator-10's rows look the same.

One header, traced:
- `validator-04:17:44:59.115` executes the output of leader round 1066; its last block is 21772.
- `validator-04:17:44:59.950` proposes round 1073 naming block 21772 (re-sent unchanged at 17:45:00.978).
  `validator-04:17:45:01.349` proposes round 1074, which cancels round 1073.
- `validator-02:17:45:00.160` has executed block 21719, two outputs behind. `validator-02:17:45:01.357`: `vote path timing
  … round=1073 epoch=7 outcome=behind lock_ms=291 exec_wait_ms=1001 total_ms=1293`. validator-04 logs the same refusal from
  another voter at 21719 at `validator-04:17:45:01.228`: `Execution is behind the header: header block 21772, local block
  21719`.
- `validator-02:17:45:03.813` executes block 21772: 3.86 s after the proposal, 2.46 s after the header was cancelled, and
  4.70 s after validator-04 executed the same output.
- rounds 1070 and 1072 the same way: validator-02 reached the named blocks (21719, 21741) 3.57 s and 3.03 s after
  validator-04 proposed them.

The gap in numbers: 21772 - 21719 = 53 blocks = two outputs (21719 to 21741 to 21772). At saturation an output carried
about 25 blocks (validator-02 executed 1,768 blocks in 72 outputs between 17:44 and 17:46; fleet-wide 12.96 blocks/s at
0.57 outputs/s is 22.6), so 53 blocks is 3.5 s of execution at 0.57 outputs/s; validator-02 took 3.65 s (17:45:00.160 to
17:45:03.813). Over load_all10 the refusals that reached the three fast proposers' certifiers named gaps of p50 49, 38 and 35
blocks and p95 230 to 241. Per minute, validator-04 led validator-02 and -09, two of the four middle-tier voters the quorum needed, by 2 to 12
rounds, that is 1 to 6 outputs.

Retries happened and could not help:
- the requester retries every refusal (below). Most attempts died with their cancelled header before the answer was
  logged: validator-04 logged 77 refusals while its voters logged 4,835.
- `validator-02:17:44:58.349` to `17:45:07.474`: validator-02 refused validator-04's rounds 1070 to 1079 exactly one per
  second, each after waiting 0 to 646 ms for validator-04's vote lock and 1,000 ms for execution.
- `validator-01:17:45:00.700` to `17:45:13.727`: validator-01 refused rounds 1065 to 1078 one per second, each after
  waiting 7.3 to 8.5 s for the lock. Through 17:45 its average lock wait was 7.3 to 8.2 s for seven of the nine other
  authors (maximum 9.4 s), so it was answering requests for headers cancelled 8 s earlier.

At the kill (17:54:44) nine validators were left, so at most two certificates per round could be missing. The slow tier was
refusing nearly everything (validator-01 and -03: 14,082 refusals after the restart), so rounds waited for a fast
validator's certificate. The three certified again 7 to 13 s after the kill, before the epoch boundary, and then took turns:
validator-04 had 3 and 1 own certificates in the minutes from 18:02 and 18:03, validator-08 none for 226 s (18:05:42 to
18:09:28).

Counters over the run: `tn_primary_votes_refused_execution_behind_total` validator-01 14,802, -03 11,969, -05 5,747, -06
3,171, -09 2,728, -07 2,559, -02 2,558, -10 2,222, -04 1,317, -08 588, and 0 at idle and light load.
`tn_primary_vote_timeouts_total` was 0 for every stage on every node, so the bound did what it was for on the requester side.

Bench 4 (2026-11-05) did not show this: before F1-1 the commit path waited for the leader's execution, which kept every
validator's execution within about a round of consensus, and validator-04, -08 and -10 certified 99.7, 96.0 and 87.0 % under
load. F1-1 removed that wait on purpose; in this run execution lag ranged from 2 to 62 rounds.

## Mechanism

Line numbers are at the bench integration head 067639def.

1. **The proposer names its newest executed block.** `crates/consensus/primary/src/proposer.rs:379` passes
   `latest_execution_block_num_hash()` to `Header::new`. The field is in the header's wire bytes and the digest hashes them
   (`crates/types/src/primary/header.rs:320`, `:623-630`), so it is certified content.
2. **The voter signs only after that block is canonical locally, and waits at most 1 s.** `vote_inner`
   (`crates/consensus/primary/src/network/handler.rs:1124-1169`) runs `timeout(VOTE_EXECUTION_WAIT,
   wait_for_execution(header_block))`, with `VOTE_EXECUTION_WAIT` = 1 s (`crates/config/src/consensus.rs:459`).
   `wait_for_execution` (`crates/consensus/primary/src/consensus_bus.rs:1344`) waits while the local tip is below the named
   number (`crates/consensus/primary/src/recent_blocks.rs:98-106`). On expiry the voter answers `ExecutionBehind`,
   recoverable and without a penalty (`network/message.rs:275`, `error/network.rs:269`).
3. **A header lives one round.** The certifier cancels the outstanding vote requests whenever the proposer hands it a
   different header (`crates/consensus/primary/src/certifier.rs:818-819`). The proposer moves on at the min-delay tick once
   it holds 2f+1 parents (90-97 % of the seven slower validators' loaded proposals), on average every 0.86 s in load_all10 (918 rounds in 792 s).
4. **Retries cannot outrun the round.** `request_vote` resends a recoverable refusal after 250 ms up to six times
   (`crates/consensus/primary/src/network/mod.rs:933-948`), and the certifier retries again with 0, 0.1, 0.5, 1, 2, 5 and
   10 s back-off until the header is cancelled (`certifier.rs:147-297`). Each retry costs at least another second at the
   voter. A header that names a block two outputs ahead of the 2f-th fastest other voter needs 3 to 4 s and gets about 1 s.
5. **The round does not need the fast validators.** At n = 10, f = 3 a certificate needs 7 votes including the author's,
   and a round needs 7 certificates. The seven slower validators name blocks everyone has executed, so they certify each
   other and the round advances; the fast validators' headers are cancelled every round. Their digests, re-queued at the cancel by L7 (`feat(primary): re-queue digests of cancelled headers`), go
   into the next header, which is refused for the same reason, and their workers stop sealing because nothing they seal is
   certified.
6. **The per-author vote lock turns refusals into a queue.** `vote_request` takes the author's lock
   (`handler.rs:810`) before `vote_inner` and holds it across the execution wait. A refusal restores the previous entry
   (`:920`), so it does not short-circuit later requests. A requester that gives up on a request does not cancel the voter's
   task: the task ends with its answer or when the transport reports an inbound timeout or a closed connection
   (`network/mod.rs:2164-2187`, `crates/network-libp2p/src/consensus.rs:2252-2262`; the transport timeout is 10 s,
   `crates/config/src/consensus.rs:449`). Each author's requests are therefore served one per second, in arrival order,
   including requests for headers cancelled seconds earlier. Requests that would wait past 10 s are dropped by the transport
   (inferred: there is no log line for inbound timeouts; validator-01's lock waits stop below 9.4 s). The queue does not cause
   the starvation, but it makes every refusal cost the voter a second per author and delays a voter's first useful vote
   after it catches up.
7. **F1-1 removed the pacing that hid this.** With the commit waiting for execution, no validator could execute far
   ahead of the others. Without it, a 2 to 4 % difference in execution cost became a 2 to 12 round lead within minutes.

## Proposal

Make honest proposers name a block that a quorum has already executed (design D below), and stop the voter from serving a
queue of stale requests (V). Keep F3-6: with D only the at most f slowest voters refuse, and the bound keeps them from
holding requests (#1782).

## Bench-6 proposal

The invariant every candidate is judged by is the vote-time fork canary: an honest voter signs a header only if the
header's execution block (number and hash) is on its own canonical chain. The canary detects a validator whose execution
has diverged; it does not prevent divergence, because every node computes execution locally from the ordered outputs and the
header's block is not an input to execution. Since F1-1 a second check depends on it. The subscriber waits for each
committed leader's execution block and treats a mismatch as its own fork: it logs "leader's execution block is not on the
local chain; execution has forked, going inactive", goes inactive and shuts down (`crates/consensus/executor/src/
subscriber.rs:938-960`, `:1163-1210`). That conclusion is sound only because a certificate's 2f+1 votes include at least
f+1 honest voters who matched the block against their own chains.

Costs below are for n = 10, f = 3: a certificate is the author plus 6 votes, and a round is 7 certificates.

### (A) Drop F3-6 and wait up to `vote_timeout` (5 s) again

- Invariant: kept.
- Effect: does not fix the starvation. The header lives about 1 s; validator-02 reached round 1073's block 3.86 s after it
  was proposed, so its vote would have arrived 2.46 s after the cancel. Bench 4 certified the fast validators only because
  the pre-F1 commit wait kept the execution spread under a round.
- Cost: #1782 returns (each attempt held up to 5 s at a lagging voter, about 36 s of requester time per header across the
  seven attempts), and each request holds the author's lock until the voter catches up instead of for 1 s. On a slow voter
  every request would wait out the 10-s transport timeout.
- Verdict: reject.

### (B) Keep the bound and retry the refusal within the round

- This is already the behaviour: the requester retries in two layers (mechanism 4). The 537 to 683 refusals per voter are
  counts over validator-04's 918 header rounds, so at most one per round, paced at one per second by the voter's lock. They
  are not per header.
- Effect: none. The retries fail for the same reason as (A): the quorum reaches the block after the header is gone. A
  variant that keeps collecting votes after the proposer has moved on produces round-r certificates that the round-(r+1)
  headers, already proposed, do not reference, so they are orphaned like the London and Netherlands certificates at light
  load. It also conflicts with L7, which has already re-queued the cancelled header's digests.
- Verdict: reject.

### (C) Vote for a header whose block is ahead of local execution by at most K, keep the check for blocks at or below it

- Invariant: broken for every "ahead" header. The voter signs a number and hash it has never seen.
- What a Byzantine or diverged proposer gains: it names a number a little above the honest tip with an invented hash.
  Honest laggards within K sign; f Byzantine votes plus f+1 honest laggards make 2f+1. If that certificate becomes a leader,
  every honest subscriber waits for that number (`next_wait_floor`, `subscriber.rs:1303`) and then either finds a different
  hash and shuts down as forked, or waits forever because the outputs before it never produce that number. One Byzantine
  leader halts the chain. A validator whose execution diverged by accident does the same: today the voters refuse its headers
  and only it stops; under (C) its certified leaders stop everyone. The later canonical check, when the voter executes the
  block, is that same fail-stop check and fires only after the certificate is committed. Equivocation is unaffected (the
  per-author lock and the vote store still reject a second header for the same round).
- K from the data: the voters the quorum needed were the mid tier, which the fast three led by 1 to 6 outputs per minute in
  load_all10 (25 to 150 blocks at about 25 blocks per output). K = 2 outputs covers the median header; K = 6 outputs covers
  every minute. In blocks the same K is meaningless across loads (1 to 2 blocks per output at light load, 22 to 46 at
  saturation), so it would have to count outputs.
- Verdict: unsafe, and a protocol change (a voting rule every node must apply, behind a fork gate). Reject.

### (D) Name an execution block a quorum already holds (recommended)

- Rule. When it builds the header for round r, the proposer takes its own executed tip and the execution block named by
  each parent certificate from another author, and names the (2f+1)-th highest of those numbers. The result is never above
  its own tip and never more than N outputs below it (N = 8 entries of its recent-blocks ring). It resolves the number to its
  own number and hash from the ring: parents name the last block of an output, the ring holds the last block of each output,
  so the lookup is exact. With fewer than 2f+1 usable values (round 1 with genesis parents, parents from another epoch) it
  names its own tip, as today.
- Why it works. Each parent's author had executed the block it named when it proposed round r-1. At least 2f+1 committee
  members, counting the proposer, therefore hold the named block, so at least 2f other voters can vote at once without
  waiting. Only the at most f slowest refuse, and the round does not need them.
- Invariant: kept in full. The voter path does not change; every honest voter still checks the named block before signing,
  and the subscriber's conclusion still holds. A Byzantine proposer gains nothing new: the voting rule already accepts any
  block at or below the voter's tip that is on its chain (`check_execution_block`, `consensus_bus.rs:1321`, via the ring or
  the canonical database), and (D) only changes which valid block honest proposers choose. Parent values are certified, so
  they are real blocks. f Byzantine parents naming low blocks fall below the (2f+1)-th rank and cannot move it. f Byzantine
  parents claiming high blocks can push it up until only f+1 honest members hold it; that proposer is then refused by slower
  honest voters, as every fast proposer is today, and never worse off than today.
- Cost: the canary checks an older block. The age is the proposer's lead over the (2f+1)-th member: zero when the fleet is
  in step (idle and light load, every validator within an output), 1 to 6 outputs (2 to 12 rounds, about 4 to 11 s) for
  the three fast validators in this run, never more than N. A diverged validator is detected that much later, by voters and
  by the other nodes' subscribers. Until then its headers name blocks from before its divergence, which is what any header
  naming an older block does today and does not touch consensus. Side effects: the subscriber's execution floor
  (`next_wait_floor`) is lower by at most N outputs, so at most N more outputs are assembled ahead (about 1 to 1.25 MB each);
  the observer's execution wait in state-sync (`crates/state-sync/src/lib.rs:588`) throttles by up to N outputs less, and
  its bounded output queue remains the real bound. Requester retries fall from up to seven refusing voters per header to at
  most f. Round pacing is unchanged with ten alive. After a kill that leaves one validator out and two far behind (seven healthy
  validators, exactly a quorum), every proposer can still certify, because the 7th-ranked block is held by all seven
  healthy validators, instead of the fast validators taking turns.
- Consensus-observable: the header bytes, and so the certified content and the consensus output, change; no validity rule
  does. A mixed fleet works: voters without the change check the older block like any other, and proposers without it keep
  naming their tip (and stay starvable). No fork gate, rolling deploy. Cherry-pickable for bench 6: about 40 lines around
  `proposer.rs:373-382`, a ring lookup helper in `recent_blocks.rs`, tests.
- Optional, observability only: the proposer can compare each parent's named block at or below its own tip with its own
  chain and count a mismatch, which detects divergence on every certificate whatever block the headers name.
- Smaller fallback: always name the ring entry N outputs back. Fewer lines, but the canary is N outputs stale even when the
  fleet is in step. The ranked rule is preferred.

### (E) A lagging voter votes anyway if it already voted for this proposer's previous header's block

- Invariant: broken. That the proposer's block at round r-1 was on the voter's chain says nothing about its block at round
  r; the proposer's chain can diverge right after it. This is (C) without a bound, available to any proposer that behaved
  for one round.
- Effect in this run: almost none. validator-01 and -05 never voted for validator-04, and the mid tier voted for it 74 to
  104 times out of 918, rarely in consecutive rounds, so the rule would seldom have applied.
- Verdict: reject.

### (V) Companion: stop the per-author vote queue

- Wait for execution, bounded as now, before taking the author's lock; the wait only reads the recent-blocks watch and the
  canonical database. Check again under the lock, which returns at once when the block is executed. Requests from one
  author then wait side by side, so a refusal costs at most 1 s per request instead of 1 s times the queue length.
- Refuse at once, as recoverable, a request whose round is below the highest round this voter has already received from
  that author in the same epoch: the author has moved on and cancelled it.
- Invariant: unchanged. The equivocation check, the vote store and the signature still happen under the lock.
- Cost: more tasks waiting at once per author, bounded by the vote serve budget and its per-peer permit cap.
- Not consensus-observable; about 40 to 60 lines and a paused-clock test.

### Recommendation

Ship (D) for bench 6 with (V) as a second small commit, and keep F3-6. (D) is the only candidate that removes the cause,
a proposer asking for a check the quorum cannot make yet, and it keeps the canary whole. (A) and (B) do not change the
outcome, and (C) and (E) give a single Byzantine or diverged leader a way to halt every honest node through the subscriber's
fork check. (D) and (V) are small proposer-side and voter-local fixes that need no fork gate; (C) and (E) would be protocol
changes. The open protocol question from the F1 design (vote without the execution check and detect forks through a separate
execution attestation) stays a later design item; with (D) it is no longer needed for liveness.

## Test plan

Unit:
- Proposer: a table test of the block-choice function. Ten values give the 7th highest; an own tip below that gives the own
  tip; fewer than 2f+1 usable values (genesis or other-epoch parents) give the own tip; the floor applies when the 7th-ranked
  value is more than N ring entries back; the resolved hash is the proposer's own even when a parent names a different hash
  at that number (and the mismatch is counted); f low outliers do not move the choice.
- Ring helper: the newest entry at or below a number and the n-th newest entry, on an empty ring, below the oldest entry and
  on an exact hit.
- Voter (the existing handler test fixture): a header naming a block three outputs below the voter's tip is voted with no
  execution wait; one below the ring is matched through the canonical database; a different hash at an older number is still
  refused as `UnknownExecutionResult`, so the canary still fires for old blocks.
- (V), paused clock: five queued requests from one author whose block is ahead are all answered within about 1 s, not 5 s; a
  request for an older round than one already received from that author is refused at once; the equivocation tests pass
  unchanged.
- Primary integration with a ten-authority committee fixture: three authorities' executed tips two outputs ahead of the other
  seven. Each fast authority's header built with the new rule gets at least six votes without an execution wait; with the
  current rule it gets two.

End to end:
- `test_fast_executor_is_certified`, next to `test_slow_execution_stays_active` (`crates/e2e-tests/tests/it/restarts.rs:2120`).
  The local testnet has four validators (`crates/e2e-tests/src/lib.rs:270-275`). Set `TN_TEST_EXECUTION_DELAY_MS`
  (`crates/types/src/test_hooks.rs:129`) on three of them so that 2f+1 = 3 slow validators can certify without the fast one,
  the same shape as this run at f = 1. Under the existing load for 60 s, every validator's own header rounds with `quorum
  reached` must be at least 95 % of its `header proposed` rounds, and at most one voter may refuse each of the fast
  validator's headers. Run once on the parent commit and record that the fast validator certifies under 10 % there.
- A ten-validator variant, three fast and seven delayed (this run at f = 3), once `config_local_testnet` takes a validator
  count: the same assertions, then kill one delayed validator during the load and require at least 90 % certification on
  every remaining validator.
- The existing slow-execution and restart tests stay green, since (D) changes the proposer path.

## The bench-6 fields that prove it

- Own-header certification of at least 98 % on every validator in every loaded window (this run, load_all10: 0.2 %, 0.0 %
  and 16.2 % on the three fast validators).
- No generator lands nothing for more than 30 s while its validator is active (this run: 802, 853 and 491 s).
- `vote path timing` lines with `outcome=behind`: at most f refusing voters per header, each with an executed tip below the
  named block; created votes' `exec_wait_ms` p95 under 50 ms on every voter.
- `tn_primary_votes_refused_execution_behind_total` on the middle-tier voters down at least tenfold (this run, load_all10:
  1,844 to 1,982 each).
- New fields on the `header proposed` line: `exec_block`, `exec_tip` and `exec_basis` (`quorum`, `tip` or `floor`).
  `exec_tip - exec_block` is 0 at idle and light load and at most N outputs at saturation; `floor` is rare.
- With (V): `vote path timing` `lock_ms` p95 under 1.1 s on every voter (this run: about 8 s on the slowest voter for seven of
  the nine other authors).
- The canary is still live: `unexpected execution result received` stays 0 (0 in this run) and the unit tests above pass.

## Related

- #1782: a lagging voter holds vote requests on its execution wait. F3-6 bounded the wait; this issue shows that the bound
  is not what limits liveness once execution can spread. (D) keeps #1782 fixed.
- #1781: the proposer advances on 2f+1 parents. Same family: a validator whose certificates the round does not need is left
  behind. (D) does not change it.
- F1-1 (the subscriber's fork check): the reason (C) and (E) are unsafe.
- The F1 design's open question (vote without the execution wait, fork check at commit): a later protocol item.
- {{ISSUE:f3-rejoin-loop}}, rule 6: the F3-6 commit this issue revisits.
