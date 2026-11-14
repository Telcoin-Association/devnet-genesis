# Review R-04: head 04, epoch-record collector hardening (E2, E3, E4)

Date: 2026-11-14.
Scope: telcoin-network-b7, the commit list 5145c7d83, 8fc1ffebb, 90a47028f (E2), 2fa2b55a8, 645a50111, e4f1157ce (E4), 425d6a89d, a9be68ff1 (E3), on main 45dce8947.
Code review (tn-review) and security evaluation (tn-security-eval) were both run, and every non-Info finding was checked by an independent verification pass (findings-verifier, opus sub-agents).
The worktree head moved from 5e2197ce7 to 5879d7ce6 during the review (other topics: the withhold-vote test hook a04c15e68 and dc711b289, the order-hold commits).
All line numbers below are at 5e2197ce7 (`git show 5e2197ce7:<path>`).
Paths: `SS` = crates/state-sync/src/epoch.rs, `EV` = crates/node/src/manager/epoch_votes.rs, `ER` = crates/storage/src/epoch_records.rs, `TE` = crates/types/src/primary/epoch.rs, `CFG` = crates/config/src/node.rs.

## Verdict: APPROVE WITH FOLLOW-UPS

No Critical or High finding.
With all three switches off the code behaves as main does, apart from E2's log lines, metrics and two read-only store reads.
No switch changes a message, a vote, a record digest or a certificate rule, so a mixed fleet cannot fork or reject each other's messages.
The walk accepts nothing main would refuse; retained votes cannot build a certificate that a single round with the same votes could not.
The two Medium findings matter for mainnet and the upstream PR, not for a ten-node benchmark run.
Recommended before the benchmark image: V12 (log what a halt needs for diagnosis) and V10 (gauge caveat or fix), plus the V5 pre-flight before anyone flips `epoch_record_conflict_halt`.

## Findings

### V4. Medium (mainnet) / Low (bench), CONFIRMED: the conflict halt's threshold is below a super-quorum of K-1's committee, and its message overclaims

- Location: SS:183-217 (message SS:199-213), SS:546-569, SS:607-626; TE:107-110, TE:150-162; ER:401-417, ER:1210-1229.
- Validation accepts a record whose committee is any `committee_compatible` subset of K-1's `next_committee` (at least four members and at least two thirds), and checks the certificate against that subset's super-quorum.
- So for an anchor of 10 members, 5 signers (committee of 7, super-quorum 5) can certify a K' that validates: more than f = 3, fewer than 2f+1 = 7. Signers need not be staked any more (former members, long-range keys).
- Sequence: 5 key-holders of K-1's `next_committee` sign K' that names the real K-1 as parent; a switch-on node holding its own K uncertified (the vote window right after a close, or K left uncertified network-wide) asks for K, validates K', `save` returns `ConflictingRecord`, the collector or the startup sync returns an error, and the node stops on every restart.
- Not a new class of weakness: main's vote-round recovery ladder already fail-stops on the same evidence under the same rule (main EV:274-289) for N, N-1 and the latest record re-armed at startup. The switch extends it to the collector, the gap retry and the startup sync, for any epoch the node holds uncertified.
- Within the BFT assumption (at most f faulty) it cannot be triggered against a correct node.
- The message "this node has forked" is stronger than the evidence: under the shrunk-committee rule the certificate proves only that at least 5 of 10 members signed another record, which also fits more than a third of the committee being faulty.
- Fix: halt only when the signers reach the full super-quorum of K-1's `next_committee` (log and count otherwise), and say in the message that the stored record differs from one certified by S of the M members of the committee K-1 names, with both digests.
- When: before the upstream PR.

### V2. Medium, CONFIRMED (worst case overstated by the first claim): the gap retry holds the record collector loop

- Location: SS:607-655, SS:711-752; crates/consensus/primary/src/network/mod.rs:2784-2795; crates/network-libp2p/src/consensus.rs:781-785.
- `retry_gaps` awaits `request_epoch_cert` for up to 16 gaps in sequence, each call sends three requests (no early exit on an "unavailable" answer), each bounded by the request-response default timeout of 10 s (about 20 s with substream negotiation).
- Sequence: the walk opens 16 gaps; a pass ends definitive; `retry_gaps` runs; chosen peers accept and do not answer; the next pass (with the certified-record republish that heals a pinned last-published watch, issues #1771 and #1796), the gauge update and the shutdown select at SS:745-751 wait until it finishes. Ceiling about 480 s; with one silent peer among nine, about 50 s.
- Only with `epoch_record_collect_past_uncertified` on (the gap set stays empty otherwise). Shutdown does not hang the process: the task manager waits 2 s.
- The doc at SS:687-690 says "one request per open gap"; it is three.
- Fix: run `retry_gaps` under a deadline and a `select!` on `node_shutdown`, stop at the deadline; or one request per gap per retry.
- When: before the upstream PR; in the benchmark, watch the republish latency.

### V3. Low (was Medium), CONFIRMED: switch-on re-votes can make a switch-off node evict its current round

- Location: EV:444-540 (eviction EV:520-537), EV:136-145, EV:278-285; crates/consensus/primary/src/network/handler.rs:883-919.
- A switch-off node starts a round for a verified vote of any epoch it holds uncertified (main), and evicts with `pop_front` (main); ended rounds stay queued until a send to them fails.
- Sequence: in a mixed fleet, switch-on peers holding different uncertified sets pick different old epochs (EV:766-779); five rounds for distinct epochs start on a switch-off node within the 1-3 s that N's round collects; N's round is evicted, ends as `channel_closed` with no recovery and no alarm; its votes are not re-delivered this epoch.
- It heals: the failsafe re-signs N at the next close (EV:621-640, logged at error), the record collector fetches N's certificate from peers, switch-on nodes never evict N.
- Fix: in the switch-off path, do not evict a newer round for a vote of a lower epoch than every queued one.
- When: before the upstream PR.

### V1. Low, CONFIRMED (by design, under-documented): `epoch_record_recertify` stops a node on an old divergent record whatever `epoch_record_conflict_halt` says, and a restart repeats it

- Location: EV:358-373, EV:643-655, EV:721-744, EV:766-779, EV:792-819; CFG:356-396.
- Sequence: a node in K's committee holds its own K (K in N-16..N-2) that differs from the network's certified K while its K-1 matches; the close picks K; its own re-vote starts a round that falls short; the recovery ladder validates the network's K and calls `node_shutdown.notify()` (EV:373), which does not read `epoch_record_conflict_halt`; after a restart the re-arm and the pick (latest epoch modulo the candidate count) choose the same K and it stops again.
- A peer's vote for the network's digest is rejected by the handler (digest check), so only the node's own vote starts that round; a Byzantine minority cannot trigger it on a correct node.
- On ten validators at most three nodes can hold a divergent K while K is certified; stopping all three leaves no fault margin.
- Fix: document in both switch docs that this stop ignores `epoch_record_conflict_halt` and repeats on restart (the `conflict_halt` doc at CFG:393-394 says the conflict is only logged with it off, which is wrong when `recertify` is on), or gate the ladder's stop for re-certify rounds on `conflict_halt`.
- When: before the upstream PR.

### V5. Low (operational), CONFIRMED (by design): turning the halt on stops any node that already holds a conflicting record

- Location: crates/node/src/manager/node.rs:1340-1346, SS:399, SS:469, SS:567.
- A node whose stored K conflicts with a certified K' fails the startup sync (or, if the 5 s pass cap or the 30 s deadline hides it, exits later from the collector) once the switch is on, and does so on every restart.
- Fix: none in code. Pre-flight before the flip: on the switches-off image read `tn_state_sync.epoch_record_conflicts_total` (always counted) on every node; grep main's logs for `ConflictingRecord {` (target `epoch-manager`, "failed to save epoch record/cert for epoch") and for "we have forked!"; flip one node at a time.
- When: before the benchmark flips the switch (runbook, not code).

### V7. Low, CONFIRMED: a walk that does not land is repeated on every wake-up

- Location: SS:482-513, SS:153-159.
- Sequence: the node holds K uncertified (or a run of up to 16); peers do not hold the next record yet; each pass walks, gets "unavailable", returns the cursor before the walk; the next wake-up (5 s timer or any `send_replace` on `requested_missing_epoch`) does it again.
- Cost: at the tip during a vote round, 6 requests per wake-up instead of 3; worst case 17 calls (51 requests).
- The doc at CFG:381 says the skipped epoch is asked for "on every later pass"; gaps are retried at most once per 5 s.
- Fix: remember the last walk's end and its time, and re-walk at most once per retry interval.
- When: before the upstream PR.

### V8. Low, CONFIRMED (impact overstated): a refusal after a walk skips the end-of-pass persist

- Location: SS:482-494 versus SS:515-520.
- With a steady parent mismatch after a walk, every pass returns at SS:493 and the collector never persists what it stored earlier in the pass.
- Epoch close (close_epoch.rs:827), vote rounds and a clean close persist the store, so an OS crash is needed to lose anything, and the lost records are downloaded again.
- Fix: replace the early returns with a break that reaches the persist.
- When: before the upstream PR.

### V9. Low, CONFIRMED: a failed read drops a gap

- Location: SS:613-645; ER:2371-2378.
- `retry_gaps` treats anything but `Some((_, None))` as closed; `record_by_epoch` maps a read error to `None`; the cursor is past the epoch, so it is not asked for again until a restart.
- Fix: close a gap only on `Some((_, Some(_)))`.
- When: before the upstream PR.

### V10. Low, CONFIRMED (metrics only): re-certify accounting keyed on a mark misattributes rounds

- Location: EV:208-231, EV:296-322, EV:413-433, EV:792-819, EV:893-921.
- Rounds for epochs at or below N-2 that this node did not mark (a skipped pick whose committee peers re-vote, a peer's different pick, a second concurrent round, a pruned mark) write `tn_node.epoch_record_signers`; a mark whose round never starts relabels a later round; re-certify rounds add to `tn_node.epoch_record_missing_signers_total` with no label to tell them from current rounds.
- Effect on a benchmark: the signers gauge can show an old record's round instead of the latest close, and missing-signer counts include old-committee misses.
- Fix: write the gauge only for rounds of epoch N or N-1 (the collector's latest), and add a `round` label to the missing-signers counter.
- When: the gauge before the benchmark image (or a dashboard caveat); the label before the upstream PR.

### V11. Low, CONFIRMED: a kept quorum is not aggregated until another vote arrives

- Location: EV:121-134, EV:413-433.
- Votes reaching a round during its peer recovery are drained into the kept signatures (EV:419-426) but no aggregate is tried, and kept signatures seed only a new round; two concurrent rounds for one epoch can both end short while the kept union holds a quorum.
- The certificate then waits for a later vote for that epoch (failsafe, a later pick) and is never built if the epoch leaves the 16-epoch window first.
- The comment at EV:827 ("kept only once a round counted it") contradicts the drain.
- Fix: after the drain, aggregate and verify if the kept signatures reach quorum.
- When: neither (liveness only); fold into the upstream PR if convenient.

### V12. Low, CONFIRMED: the halt and the refusal lines omit what an operator needs

- Location: SS:196-213, SS:579-594, SS:482-494.
- The halt logs both digests and the serving peer (a relay, not a signer) but not the offered certificate's signer set or the offered record, and the pair is not stored; the "got an invalid epoch record" line omits the peer that is in hand at SS:553.
- Fix: log `signed_authorities` (as authority ids) and the offered record on the halt and on the non-halt conflict; add `%peer` to the invalid-record line.
- When: before the benchmark image (diagnosis of any halt in the run).

### V6. Refuted as a defect

The walk stores K+1 certified while K is uncertified; main produces the same shape (a node's own round certifies K+1 after K's failed, ER:2525-2533) and no reader assumes the certified epochs have no holes.
The startup sync measures the certified prefix and can end early after such a hole; the background collector continues, so this is harmless.

### Info (not verified; observations)

- The re-certify pick depends on each node's own uncertified set, so nodes can pick different records at one close (liveness only; kept signatures soften it).
- A stored certificate's signer set depends on timing and on which peer answered; the first save wins; nothing hashes a certificate (main).
- When an aggregate or verify fails, `forget_record` drops every kept signature of the record, good ones included; no peer can force this (votes pass group and key checks at the handler); no unit test exercises it.
- Kept signatures are not re-verified at seeding; they are bound by the record digest, which covers the committee and its order (TE:43-47).
- The vote's epoch is not signed, only the digest, which commits to the epoch (main).
- The receive side has no lookback: a member of any old committee can make a node verify one vote per (author, epoch) per epoch run and run one round per epoch it holds uncertified (main, unchanged by the switch).
- With the switch on, the lowest epoch is evicted, so a lower-epoch newcomer evicts this node's re-certify round; the newest record's round and N-1's are never evicted, which is better than main.
- Former members' re-votes may be filtered by the gossip layer's publisher rules (not read); that limits re-certification of records whose committee rotated out.
- After a restart `latest` is 0 and the kept-signature window is open until the first prune; still bounded at 17 records.
- Permanently uncertified epochs hold their gap slots for good; after 16 the walk stops at the next one, as main does at the first.
- A walk followed by an unanswered request makes the pass non-definitive where main's is definitive; the startup sync waits its 2 s unanswered budget.

## Answers to 2a-2g

### 2a. Switch off = before

With all three switches off, every E3 and E4 path is main's behaviour; three agents and the verifier checked line by line.
Lines that run with the switches off and did not run on main:
- E3: construction of `Collection` and the `walked` vector (SS:289, SS:443, SS:708-710), `land` on an empty vector (SS:450, SS:473), the early `return false` in `may_walk_past` (SS:153-155, no store read), the `walked.is_empty()` branch that returns main's `{epoch - 1, true}` (SS:483-484), the `gaps.is_empty()` check (SS:731-732), and `tn_state_sync.epoch_record_conflicts_total` incremented on a `ConflictingRecord` before main's `stop_on_local_failure` (SS:196-197).
- E4: local `certified` writes (EV:120, 245, 293, 382), `None` checks on `retained` (EV:121, 164, 257, 267, 413, 643), `recertify_round = false` taking main's metric calls (EV:213, 227, 308, 319), the `else if` reaching main's `pop_front` (EV:534), and the short-circuit `recertify &&` at EV:735 (no store read).
- The `Parameters` argument reaching the collector is copied into two bools (SS:102-108); the retained-votes `Option` is `None`.
- E2 (no switch): the `peer` and `signers` fields on both `retrieved cert` lines (SS:571-576, EV:375-380); `request_epoch_cert` returns the responder's key, used for logs only (mod.rs:2788-2790); the gauge `tn_state_sync.epoch_records_certified_through`, set from one read-only `first_missing_historical_cert(Epoch::MAX)` per collector wake-up and once before the startup sync (SS:285, SS:740, SS:764-775; the same call main's startup progress closure makes, O(1) from the watermark); in a vote round that ends without quorum, one `cert_by_digest` read (EV:291), the counter `tn_node.epoch_record_round_ended_certified_total`, an info line instead of the error when the certificate is held, the signers gauge set from the held certificate, and the missing-certificate alarm skipped then (EV:286-322, EV:405). The recovery ladder still runs in that case, as on main.
- Metric registrations: three new state-sync counters and the gauge (crates/state-sync/src/metrics.rs), registered whatever the switches.
- Out of scope but present at the new head 5879d7ce6: the withhold-vote test hook reads the environment at the three places this node signs its own vote (EV:629, 662, 820 at that head), with the switches off too. The owning topic's review should check it.

### 2b. Mixed fleet

No switch changes a message, a wire format, a record digest, a vote or how a certificate is checked: the re-vote is the same deterministic BLS vote through `publish_epoch_vote`, and `validate_downloaded_record` is unchanged.
Switch-on and switch-off validators cannot disagree on anything another validator checks (headers, votes, certificates, batches), so they cannot fork or reject each other.
They can disagree on which records they hold certified (local coverage: the walk stores K+1 past an own uncertified K; switch-off nodes stop at K), which is not consensus-visible.
They can differ in who stops: only switch-on nodes halt on a conflict (V4, V5) or on an old divergent record (V1), and only nodes that genuinely hold a record differing from a validated certificate are exposed.
An epoch close stalls only if more than f validators stop that way.
Switch-on peers' re-votes make switch-off nodes run rounds for older epochs, and in a narrow case evict their current round (V3); this heals at the next close and has no fleet-wide effect.
Rounds that a switch-off node joins add no vote of its own for old epochs, so re-certification needs a super-quorum of switch-on members of that committee.

### 2c. Liveness under the switches

Nothing that used to make progress is dropped.
- The record collector can be held by the gap retry for up to minutes when peers are silent (V2), delaying the certified-record republish and the gauge.
- A walk that does not land multiplies requests per wake-up (V7).
- A failed read drops a gap until a restart (V9).
- A quorum held in kept signatures waits for another vote (V11).
- Permanently uncertified epochs hold their gap slots for good (Info).
- The walk makes a node with an uncertified own K receive `set_certified_record_epoch_if_newer(K+1)`, so a validator still running K+1 after the network closed it leaves to catch up, as main already does for a node whose K is certified.
- An epoch close can only be stopped by halts on more than f validators (V1, V4, V5).

### 2d. Byzantine or slow peers

- A slow or silent peer can hold the collector loop for up to 3 x 10-20 s per gap per retry, at most 16 gaps (V2).
- A peer answering "I do not hold K" falsely only opens a gap that is retried; K+1 must still validate against the node's own K.
- A peer serving an invalid record ends the pass, as on main.
- A conflicting record that validates needs at least 5 of 10 key-holders of K-1's `next_committee` (more than f), current or former (V4); that is outside the BFT assumption, and main's ladder already stops on the same evidence for recent epochs.
- A member of any old committee can cost a node one BLS verify per (author, epoch) per epoch run and one round (about 65 s plus five peer requests) per epoch the node holds uncertified, on main and with the switch on; the switch-on eviction protects the newest round, and a lower-epoch vote can evict the node's re-certify round (Info).
- Memory: gap set at most 16 epochs; kept signatures at most 17 records times the committee size (about 34 KB for ten validators); re-certify marks at most 15.

### 2e. Restart and epoch boundary

- Gap set (E3): in memory, one per collector process; it survives epoch closes; empty after a restart, when the collector starts from epoch 0 and re-walks (the walk counter then counts the same epoch again, known). Startup passes keep their own gaps for one pass only.
- Kept signatures, `latest`, re-certify marks and the vote queue (E4): in memory; all lost on restart; `latest` is 0 until the first record arrives, so the window is open until then (bounded). Across a close they persist and are pruned to the new window before that close's rounds start.
- The conflict halt (V4, V5) and the re-certify fork stop (V1) repeat on every restart.
- Turning a switch on or off needs a restart (switches are read once at start).

### 2f. Determinism

Nothing feeds a consensus-visible value from hash-map iteration order, wall-clock time, thread timing or randomness.
The certificate built from kept and fresh signatures depends only on the signer set (BLS aggregation is a sum, `signed_authorities` is a bitmap); the signer set depends on timing, as on main, and certificates are not hashed into anything.
`pick_recertify_record` is deterministic for a given store.
Timing in the walk and the gap retry changes when and how far records are stored, never which record.
`HashMap`/`HashSet` uses in `manage_epoch_votes` are lookups; the lists that reach logs and metrics follow the committee order; the new containers are `BTreeMap`/`BTreeSet`.

### 2g. The scope's questions

1. The walk accepts nothing main would refuse and skips no epoch it should hold.
K+1 is accepted only by the unchanged `validate_downloaded_record` anchored on `record_by_epoch(K)` (ER:1216-1228), and `may_walk_past` requires the node's own stored, uncertified K that is not the epoch-0 dummy (SS:147-165); a node without K never walks.
Production writers of an uncertified record are the own close (close_epoch.rs:823), the record half of a `save` whose certificate write failed after validation (ER:2306-2312), and the CLI snapshot import, which verifies every record against its certificate.
The stated exception is as strong an anchor as a certified record: it passed the same super-quorum validation against K-1, and the failed certificate write stopped the node at the time.
A walked epoch becomes a gap retried every 5 s; if this node's K differs from the network's, K+1 is refused on its parent and the walk stops where main stops.

2. The halt is reached only through `Collection::refused`, called after `Valid` at SS:560-567, from the collector pass, the gap retry and the startup sync, when `save` returns `ConflictingRecord` (ER:2213-2223), which needs the node's own K stored uncertified.
The certificate it needs is a super-quorum of the record's own committee, which may be a two-thirds subset of K-1's `next_committee`: 5 of 10, not 7 (V4).
To halt every switch-on node: all of them must hold a K that conflicts with a validated K'; that needs either a non-determinism that puts every switch-on node on the uncertified side, or at least 5 colluding key-holders of K-1's `next_committee` (current or former) against nodes that hold K uncertified (K left uncertified network-wide, or the vote window right after a close).
Recovery short of a resync: turn the switch off and restart; the node starts, logs and counts the conflict, its collector stays at K-1, and it keeps running on its own record (main's behaviour); nothing in the store can replace a record.
The message should say that the stored record differs from one certified by S of M members of the committee K-1 names, not that the node has forked (V4).

3. Retained votes cannot produce a certificate no single honest round could.
They are keyed by (epoch, digest) of the node's own record (EV:939), and the digest covers the committee and its order (TE:43-47), so an index maps to the same key in every round; the round loop and the drain both require the vote's digest to equal the record's (EV:156, EV:420); seeding removes the key from `committee_keys` before inserting the index, so no signer counts twice (EV:126, EV:160); only the node's own vote and handler-verified votes enter the channel (EV:546, handler.rs:907-919).
`verify_with_cert` gates every save (EV:236).
A failed aggregate or verify drops the record's kept signatures (EV:256-259, EV:267-269), so later rounds start empty and are not blocked; no peer can cause that failure.

4. No new message type and no wire change: the re-vote is `record.sign_vote` sent through the existing `publish_epoch_vote` (EV:816-818); the commits touch the config, `epoch_votes.rs` and the node call sites only.
A member of any old committee (current or former, the handler checks the record's committee) can cost one BLS verify per (author, epoch) per epoch run and one round per epoch the receiver holds uncertified, with the switch on or off.
The 16-epoch lookback is enforced only on the sending side (the pick, EV:766-779, and the startup check, EV:748-756) and on how long signatures are kept (EV:860-864); the receiving side has none, as on main.

5. Yes, it is a new trigger for main's existing stop, not a new kind of stop (V1).
Main stops through the recovery ladder for N, N-1 and the re-armed latest record; with the switch on it also stops for N-16..N-2, regardless of `epoch_record_conflict_halt`, and again after every restart.
Only a node in K's committee whose own K diverges while its K-1 matches can be stopped this way (the handler rejects peers' votes for another digest, so only its own vote starts the round); a Byzantine minority cannot trigger it on a correct node.

6. Mixed fleet: see 2b. Nodes cannot disagree on anything other nodes check, and cannot split on which records are certified in the sense of validity: every certificate is checked the same way. Coverage differs, and only switch-on nodes halt. An epoch close stalls only if more than f validators halt.

7. All switches off = main apart from E2: see 2a. Beyond E2's log fields, metrics and the two read-only store reads, the only extra effect is the conflicts counter, which increments on a refused conflicting save with the halt off.

8. Restart and epoch boundary: see 2e.

## What I did not examine

- No build, test or e2e run (cargo was out of bounds); conclusions rest on reading the code and the unit gates the units recorded.
- Tests in the eight commits were read only to check claims; their adequacy was not reviewed. Untested paths the agents noted: an unanswered request after a walk, multi-gap landing, the persist skip, a gap dropped by a failed read, `forget_record`.
- The gossip layer's publisher filter for epoch votes from former committee members (crates/network-libp2p).
- Whether a fresh node or observer's consensus catch-up can execute through an uncertified epoch (design §E "not covered"); the walk never helps such a node, by design.
- The withhold-vote test hook (a04c15e68, dc711b289) and the order-hold commits that landed on the worktree during the review.
- The unit checkpoints (`tasks/checkpoint-bench7-E2.md`, `-E3.md`, `-E4.md`) carry no "trust assumptions and bounds" section, though the scope says each ends with one; the bounds above come from the code.
- Doc errors found along the way, for the upstream PR: CFG:381 ("asks again on every later pass": at most once per 5 s), SS:687-690 ("one request per open gap": three), EV:827 (the drain keeps uncounted votes), CFG:393-394 (V1).
