# Topic review R-02: head 02 `fix/1804-vote-queue` (switch `vote_queue_fix`)

Date: 2026-11-14 (UTC).
Worktree `/home/drtnarg/coding/telcoin/tn-b7-pt2b`, branch `b7/pt2b`, range `90a47028f..291b9f6c4` (7 commits; config/node.rs +17, error/network.rs +58/-1, metrics.rs +88/-10, network/handler.rs +202/-20, network/message.rs +5, tests/network_tests.rs +1240).
Code review only (`tn-review`); the security evaluation of the vote fix runs on head 05.
Findings were verified by an independent findings-verifier pass that saw the claims and the code, not this reviewer's reasoning.
Line numbers are at the tip 291b9f6c4 unless a file outside the worktree is named.

## Verdict: APPROVE WITH FOLLOW-UPS

No defect in the node code.
With the switch off the vote path decides exactly as at the base; with it on, the only refusals it adds are for vote requests the author has already abandoned, and nothing another validator checks changes.
The follow-ups are one benchmark-harness gap (Low) and two documentation or metrics nits (Info).
Nothing here blocks the benchmark image.

## Findings

### 1. Low, CONFIRMED: the harness vote gate reads `lock_ms` only, and with the switch on the execution wait moves to `prelock_wait_ms`

Location: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/tools/arms-summary.py:172`, `:270`, `:789-791`, `:1323` (working tree, uncommitted edits of other units); node side `handler.rs:990`, `:1046-1073`, `:1078`.

arms-summary.py parses only `outcome` and `lock_ms` from the `vote path timing` line, and its vote gate is `vote_lock_p95_ms < 1100` over `lock_ms` alone.
With `vote_queue_fix` on, each request's bounded execution wait runs before the lock timer starts (`handler.rs:1078` starts `lock_wait` after the pre-lock block at `:1046-1073`) and is logged as `prelock_wait_ms`.
Sequence: with the switch off, the third of three queued requests of one author logs `lock_ms` of about 2,000 (the two earlier requests' execution waits under the lock) and `exec_wait_ms` of up to 1,000; with it on, the same request logs `prelock_wait_ms` of up to 1,000 and a `lock_ms` that holds none of those waits, so the gate compares a figure that contains other requests' execution waits with one that cannot.
Part of B's drop is real (the waits now overlap) and part is the wait moving to another field; the gate cannot tell them apart.
The refusal counters also count only `behind` (arms-summary.py ≈`:1327`, `:1543`), so the new `superseded` outcome is not counted anywhere.
Fix: parse `prelock_wait_ms` and `total_ms`, add a gate on the vote-path `total_ms` p95 next to the `lock_ms` one, and count `superseded` beside `behind`.
When: before the bench 7 arm comparison is analysed or published (harness, not the image; it cannot hurt a run).

### 2. Info, CONFIRMED: the vote serve-permit docs describe only the author-lock wait

Location: `crates/network-libp2p/src/serve_permits.rs:28-30` (outside the diff), alongside the known stale comment at `network/mod.rs:3781-3784`.

The vote task takes its serve permit before it is spawned and holds it across `RequestHandler::vote` (`network/mod.rs:3785-3797`), so with the switch on the permit is also held through the pre-lock wait (`handler.rs:1046-1073`).
The module doc still says the permit covers "a wait on the author's vote lock" and that the per-peer share "bounds that wait to one task per peer"; with `MAX_PERMITS_PER_PEER = 2` (`serve_permits.rs:64`) both of a peer's permits can sit in the pre-lock wait at once.
Fix: correct this doc in the same integration commit that corrects the `network/mod.rs` comment.
When: before the upstream PR.

### 3. Info, CONFIRMED (latent): `record_outcome` silently skips an outcome outside the counter array

Location: `crates/consensus/primary/src/metrics.rs:406-410`; check at `handler.rs:2560-2567`.

`record_outcome` uses `self.outcomes.get(outcome.index())` and does nothing on `None`, while `record_stage` and `record_timeout` index directly (`metrics.rs:397`, `:402`).
The compile-time check walks only positions below `VoteOutcome::COUNT`, so a future variant given index 10 without growing `COUNT` and `ALL` builds, passes the metrics test (which walks `ALL`), and is never counted.
`VoteStage`'s check documents this limit (`metrics.rs:308-310`); the `VoteOutcome` copy does not, and its silent `get` hides the miss where `VoteStage` would panic in a test.
Nothing is dropped today: all ten variants sit at their positions.
Fix: index directly, `self.outcomes[outcome.index()].increment(1)`, as the sibling methods do, and copy the caveat comment.
When: before the upstream PR (optional).

### 4. Info (nit): a broken line wrap in a doc comment

`handler.rs:1366-1367` breaks "The caller has checked that the peer / is the header's author" across two lines mid-sentence; rewrap before the upstream PR.

## Answers to 2a to 2g

### 2a. Switch off = before

Every vote decision is the base's.
Lines that now run with the switch off:
- `handler.rs:270`: an empty `newest_vote_requests` map, once per handler.
- `handler.rs:970`: `record_outcome`, the new `tn_primary.vote_outcomes_total{outcome}` counter.
- `handler.rs:990`: `prelock_wait_ms=0` on the `vote path timing` line.
- `handler.rs:979-983`: the stage loop runs over eight stages; `PreLockWait` is `None`, so nothing is recorded for it.
- `metrics.rs:358-366`: registration of the `prelock_wait` stage histogram, its timeout-counter label and ten outcome counters, at handler construction.
- `handler.rs:1046`, `:1131`, `:1581`: three reads of a `bool` through `&Parameters` (`config/src/consensus.rs:368` returns a reference).
- `handler.rs:1593-1600`: the switch-off execution wait now ends in `.ok()`; the arms at `:1601-1638` map one to one onto the base's (`Ok(Ok)`→`Some(Ok)`, `Ok(Err(x))`→`Some(Err(x))`, `Err(Elapsed)`→`None`), same results and same metric.

`SupersededRequest` is built only at `handler.rs:1381`, which is reached only through the three switch-gated calls (`:1056`, `:1071`, `:1136`), so its new arms in `message.rs:296`, `error/network.rs:157`, `:243` and `handler.rs:2521` cannot run with the switch off.
All of the above is metrics, a log field or an identical restructure; the recorded I4 covers the log field and the new series.

### 2b. Mixed fleet

The switch changes one thing another validator sees: the voter's answer to a vote request.
A switch-on voter may answer `SupersededRequest`, which leaves the node as `PrimaryResponse::RecoverableError(PrimaryRPCError(String))` (`message.rs:296-298`), a variant every node already handles: the requester retries it five times 250 ms apart and then reports it retryable to the certifier's backoff (`network/mod.rs:2041-2063`).
Votes it does sign are the same deterministic signatures over the same header; header, certificate and batch validation are untouched, and nothing outside the voter reads the switch (grep: `handler.rs:1046`, `:1131`, `:1581` only).
So a mixed fleet cannot fork or reject each other's messages.
The only difference in answers: for a lower-round request after a newer one from the same author, a switch-on voter says "superseded" where a switch-off voter would say `AlreadyVotedForLaterRound` (fatal to the requester) or hand back a cached vote; in both cases the author has already cancelled that header (`certifier.rs:833-834`), so no certificate depends on it and the fleet cannot stall on it.

### 2c. Liveness under the switch

Nothing that made progress before is dropped or delayed without bound.
- A superseded refusal hits only a request of the same epoch and a strictly lower round than the author's newest in-window request (`handler.rs:1375-1396`); retries of the same header and the resend with missing parents keep the round and pass.
  An honest author never needs such a request answered (see question 1).
- Under the lock, execution is checked without a wait (`handler.rs:1581-1592`); the request has already waited up to 1 s before the lock, and a block still not executed gets the recoverable `ExecutionBehind` it would get on main after its 1 s wait.
- A header out of the window on arrival that the committed round brings inside while it queues skips the wait and may get `ExecutionBehind` sooner (documented at `handler.rs:1047-1054`; recoverable, retried after 250 ms).
- Worst case per request is 1 s + lock wait + `vote_timeout` (the recorded L2); on main the lock wait itself held every earlier request's execution wait, so the bound is not worse.

### 2d. Byzantine or slow peers

A faulty author can raise only its own mark (the peer-is-author check at `handler.rs:1018-1024` runs first, and the map is keyed by `header.author()`), only up to `committed_round + gc_depth` (`:1344-1353`), and with any header, even a malformed one, because the mark is recorded before `vote_inner`'s checks.
The harm is to its own lower-round requests, the same as not proposing.
It cannot make this node refuse this node's own headers: the self-vote is made in the certifier and never passes through this handler.
The map holds at most one entry per committee member.

Resource cost: the bounded execution wait now runs side by side instead of one request at a time.
One peer can have at most 8 connections (`network-libp2p/src/consensus.rs:244`) × 100 inbound streams each (libp2p-request-response 0.30 default, used at `consensus.rs:784`) = 800 requests in flight; the vote serve class is unbounded unless `serve_budget.vote` is set (`network/mod.rs:3781-3782`), and then caps a peer at 2.
Each wait is a parked future on the `recent_blocks` watch, woken once per executed output for a ring comparison (`recent_blocks.rs:98-106`); the canonical database is read only on a ring miss at or below the tip, which returns Match, Fork or BelowFloor at once, and the retry loop (`consensus_bus.rs:1728-1760`) needs a database read failure that no peer can cause.
On main the same 800 requests sat parked on the author lock instead; the expensive work (header checks, seed signature verify, parent reads, signing) stays serialised under the lock.
A malformed header now pays the wait before its check, so its penalty lands up to 1 s later (the recorded L1); a tier-2 future-dated header, whose repeats `handler.rs:1531-1537` calls cheap, now costs a parked wait of up to 1 s per repeat, the same class as L1.
A slow voter is what the fix is for: queued requests' waits overlap instead of adding up.

### 2e. Restart and epoch boundary

The only new state is `newest_vote_requests`, in memory in `RequestHandler`.
The handler is built per epoch (`node/src/manager/node/start_epoch.rs:1141` → `network/mod.rs:3682`), so the map starts empty at each epoch, and a restart empties it too; an empty map refuses nothing, which is main's behaviour until the author's next request.
Within an epoch it survives mode changes, which is harmless: it refuses only strictly lower rounds of its own epoch.
Pre-lock waits are plain futures and die with the task; nothing is persisted.

### 2f. Determinism

Nothing the new code produces is consensus-visible.
The mark decides only whether this node answers with a vote; votes are deterministic signatures, and any 2f+1 of them make a valid certificate.
The map is never iterated (`get` and `insert` only, `handler.rs:1376-1396`).
One timing change: with the switch on, one author's requests take the lock in the order their pre-lock waits end, not in arrival order (the tokio mutex is FIFO).
Between two equivocating headers of one round, which one this voter signs was already arrival-order dependent, and at most one vote per author and round still holds.

## 2g. The topic's own questions

### Q1. Can an honest author be denied a vote it still needs?

No, apart from the recorded I5.
The accepted case: a repeat of an older voted header after a newer request is refused at `handler.rs:1056`, before the cached-vote answer (`:1086`) and the stored-vote recast (`:1094`); nothing is signed and `cast` is untouched (the test `repeats_of_voted_headers` asserts two votes created, cached and stored vote unchanged, for both settings).
The author has abandoned that header on every certifier path:
- A header with a new digest notifies `new_proposal` (`certifier.rs:833-834`), which ends every outstanding vote request (`request_vote`'s select, `:291-292`) and the proposal itself (`propose_header`, `:474-477`).
- An identical re-proposal keeps vote collection (`:822-830`) and has the same round, so it passes the mark.
- On an author restart the proposer recovers round P from `LastProposed`, which is made durable before the header reaches the certifier (`proposer.rs:531-560`), seeds P−1 and re-sends the byte-identical round-P header (doc at `:231-245`): an equal round passes.
  It never starts below `primary_round` (`:291-292`).
- I5: if the `LastProposed` read fails, the proposer starts at `primary_round` and may propose below the mark; those requests are refused as superseded (recoverable, retried) until its rounds pass the mark, at most the distance from the committed round to the old P.
  Main refuses the same requests at every voter that voted for P (`AlreadyVotedForLaterRound`); the switch adds refusals only at voters that received P's request without voting.
  Not worse than recorded.

### Q2. The per-author high-water mark

Raised only by the author's own requests (peer-is-author check first), only for headers of this epoch in rounds 1 to `committed_round + gc_depth` (`handler.rs:1344-1353`), and only upward (`:1388-1393`); its size is one entry per committee member.
It is recorded before the header checks, so an author's malformed in-window header raises its own mark; that harms only that author.
An epoch change resets it (new handler per epoch); a mode change within an epoch keeps it, harmlessly.
A Byzantine author cannot use it against another author's requests (the key is the authenticated author) or make this node refuse its own headers (the self-vote never comes through this handler).

### Q3. Main's invariants from #1836, #1839, #1844 and #1842

None is weakened.
The new code never writes `cast` or the author's entry.
The arrival refusal returns before the lock; the refusal under the lock (`handler.rs:1131-1137`) sits after the cached-vote answer and the recast, and before `previous_vote` and `take()` (`:1139-1141`), so a request that gets past the arrival check is still answered from `cast`, and a refused one leaves the entry as found.
The recast under the lock with its persist barrier (`:1094-1130`, `recast_stored_vote` at `:1271-1300`) is unchanged; the arrival refusal can only pre-empt it, and then nothing is signed.
`SupersededRequest` is never produced inside `vote_inner`, so it is never cached (`:1243-1256`).
A request dropped during the pre-lock wait never held the lock; the only state it leaves is the mark it raised on arrival, which is its author's own newest request.

### Q4. How many pre-lock waits one peer can hold, and L1

Up to 800 at once (8 connections × 100 streams), each for at most 1 s, while the vote serve class is unbounded (the default); 2 per peer under an enforcing `serve_budget.vote`.
Each is cheap (2d), and on main the same requests sat parked on the lock instead.
L1 is not worth fixing before the benchmark image: ten honest validators send no malformed headers, and the wait ends as soon as the header's block executes.
Before the upstream PR it is worth moving the cheap stateless checks (`header.validate(committee)` and the round-0 check, `handler.rs:1493-1498`) ahead of the wait, so a malformed header is refused and penalised at once; the seed signature verify should stay under the lock.
`serve_permits.rs:28-30` has the same stale wording as the known `network/mod.rs` comment (finding 2).

### Q5. Switch off byte for byte

Yes, see 2a.
Besides the empty stage label, `prelock_wait_ms=0` and the outcome counter, the other new lines that run are the empty map at construction, three `bool` reads, the eight-stage loop and the `.ok()` restructure of the execution wait, which decides identically.

### Q6. The new counter and stage

Label values are static string literals (`handler.rs:2544-2556`, `metrics.rs:276-286`) and complete: `ALL` has `COUNT` entries by its array type, the const checks pin each position (`handler.rs:2560-2567`, `metrics.rs:311-316`), and the `index()` matches are exhaustive; the one gap is finding 3.
No reader indexes stages by position: in the node every reader goes through `index()` or the label (`metrics.rs:358-366`, `:397`, `:402`; `handler.rs:979`, `:2423`, `:2430`), and the metrics test's label list was updated with `prelock_wait` first (`metrics.rs:913-924`).
The harness reads the `vote path timing` line by field name (`arms-summary.py:172`, `:791`) and Prometheus series by label.

## What was not examined

- The security evaluation (runs on head 05).
- The 1,240 added test lines, apart from `repeats_of_voted_headers` and its two wrappers and the doc comments of the stale-round and window tests; no test or `cargo` command was run.
- The base's other topics (the 17 commits under 90a47028f), except where this topic calls them.
- network-libp2p internals beyond the stream and connection caps; the libp2p default of 100 streams was read from the vendored crate source.
- Whether the bench 7 fleet sets `serve_budget.vote`.
