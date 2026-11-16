# Bench 8: review of the main chain's last five commits (RVB-main-2)

Worktree `/home/drtnarg/coding/telcoin/tn-b8-bench`, branch `bench/bench8-2026-11`, base 91a15e223, range tip fdb9d22a9. Commits reviewed: 3dfd7e0b0, 453123d5e, e8eb8e199, b3067a77e, fdb9d22a9. File:line references are at fdb9d22a9 unless a commit is named. I did not write these commits and ran no cargo command.

## Verdict

**Approve with follow-ups.** Critical 0, High 0, Medium 0, Low 7. With every parameter at its default, these five commits change only logging. No decision, send, stored value, returned error, or sub-dag order differs from the base. The follow-ups are corrections to node-fields.md and two missing value tests. No code change is needed before the bench.

## Per commit

### 3dfd7e0b0: vote arrivals, errors and tally (certifier.rs, aggregators/votes.rs)

1. **Behaviour.** No change.
   - `request_vote` gets `voter.clone()` (certifier.rs:583-584), whose id is `vote_round.voter(name.clone())` (:574): the same value the base passed as `name.clone()` (base :560-561). There is no other production call site.
   - The return type `DagResult<Vote>` is unchanged. The retry loop gains two synchronous `voter.answer(..)` calls (:247, :267) and nothing else: `missing_parents = None`, the ceiling log, the sleep schedule and the cancel arm's `Canceled` are untouched.
   - In the spawned task, `match &result` (:593-600) only records; the task still sends `(name, target, result)` unchanged. `retry_answer_kind` and `final_answer_kind` (:1054-1084) take references and only match.
2. **Values.** As described.
   - Time zero: `vote_round.start()` (:400) runs right before the spawn loop (:401-404), with no await between. The own vote is appended at :392-393, before `start`, so it counts in `votes_at_end`.
   - A re-issued request (:483-486) gets a handle on the same `VoteRound`, so it is timed from the same instant.
   - `elapsed_ms` is read under the lock, so list order and ms values agree. `record_*` checks `ended`, so answers after the round's end are not listed. The quorum path calls `set_tally` before `finish` (votes.rs:67, :78).
   - Each list holds one entry per voter, so it is bounded by the committee size, in insertion order (a Vec, no hashing).
3. **Cost.**
   - The `parking_lot` guard never crosses an `.await`: every `VoteRound` method is synchronous and drops its guard.
   - A request task holds the lock for a scan of at most 9 entries plus one push, under 1 µs. That is the most it can delay the certifier loop (`set_tally` per vote).
   - `finish` renders both lists under the lock: up to 18 base58 encodes, each a String (L1).
4. **Tests.** votes.rs tests pin the rendering, the order, `ended` and the bound. certifier_tests pin arrival order, one `refused` entry, and `votes_at_end` = 3 and 1. The ms values are pinned only by their order. No test pins the codes `deferred`, `timeout`, `network`, `parents_unavailable` or `other` (L3).
5. **Rules.** No unwrap or expect outside tests. New items have `///` docs. No new dependency (`parking_lot` is already used; Cargo files unchanged). The message ends with `Topic: bench8-obs` and has no attribution.

### 453123d5e: `invalid_vote` in `vote_errors`

1. **Behaviour.** No change. The only statement added in the `append` Err branch is `vote_round.answer(&name, "invalid_vote")` (certifier.rs:461), plus comments. The `error!` call, the metric and the `None` are untouched.
2. **Values.** Correct. `name` is the peer that was asked, from the channel tuple: the key the request task used for the arrival, so the voter shows in both lists as documented.
3. **Cost.** One lock, only on an invalid vote. 4. **Tests.** None for this entry (L3). 5. **Rules.** Ok.

### e8eb8e199: `certificate accepted` (aggregators/certificates.rs, state_sync/cert_manager.rs)

1. **Behaviour.** No change. Base `append` (base :75-102) and tip `append` (:135-166) have the same duplicate check, push and weight add, quorum test `weight >= quorum_threshold()`, "do not reset the weight", and `certificates.drain(..)`.
   - So the quorum send carries every certificate collected so far, and each later certificate goes alone, exactly as at the base.
   - A duplicate author still returns before any send (:48-50). `append_certificate` sends `appended.parents` exactly where the base sent `quorum` (:68-70).
2. **Values.** Correct.
   - `round_certs` is `authorities_seen.len()`, a set the base already kept, so no certificate stays alive longer. The only new state is `first_sent: Option<Instant>` per round.
   - `parents_sent` and `late_ms` are read before this certificate's push. `quorum_reached` is `sends && !parents_sent`; `parents_resent` is `sends && parents_sent` (:62-63).
   - `source` is built once per batch from `config.authority_id()` (cert_manager.rs:240; an `Option` clone). `Recovered` is used at start-up (:303).
   - `late_ms`'s zero is set before the send's await (:161) (L2).
3. **Cost.** One INFO line per certificate per node, formatted before the parents send (L2). No added clone of a certificate.
4. **Tests.** Ten certificates in a fixed order; every field's value is pinned per line, and the quorum is at index 6. 5. **Rules.** Ok.

### b3067a77e: `order hold released` (proposer.rs)

1. **Behaviour.** No change.
   - `held_blockers` is read only in `release_held` (:1243-1246), `log_held_at_stop` (:1253-1260) and the log itself. No decision reads it.
   - It is written at :1444-1449, only for a round that `proposed_headers.get(round)` holds, so its keys stay a subset of `proposed_headers`. That code is reached only through `drain_held`, the order-hold path.
   - `proposed_headers` loses entries at exactly three sites: :1056 (commit, Some arm), :1129 (re-queue on commit) and :1216 (cancel). Each is followed by `forget_held` and `release_held`. :1089 only iterates.
   - The proposer is consumed per epoch (`spawn(mut self)` :1676, `run` :1770), so nothing leaks across epochs. An error exit drops the map without a line, as documented.
2. **Values.** As described. `waited_ms` is wall clock minus `created_at_ms`. At stop, ascending round order stands for the order of leaving, so the newest blocker counts the shared lanes. The `requeue_on_commit` line also comes after the re-queue (L5).
3. **Cost.** `digests` does not walk the digest queue.
   - `freed_digests` sums `VecDeque::len()` (O(1)) per lane, skipping lanes another blocker holds: about lanes × tracked blockers steps (1 × ≤3 here) per released header. The queue's length (even tens of thousands) does not matter.
   - The insert walks a blocker's payload once (`or_insert_with`), on the first plan that names it.
4. **Tests.** Field names and order are pinned; (round, lanes, digests, cause) are pinned for `cancel`, `commit`, `requeue_on_commit` and `epoch_end`, plus two `epoch_end` lines at a stop. With the switch off, nothing is logged and the map stays empty. `freed_digests` and `waited_ms` are unit-tested. Only `waited_ms` in the line is bounded rather than pinned (`< 60 000`).
5. **Rules.** Ok.

### fdb9d22a9: `subdag parent skipped` (consensus/utils.rs)

1. **Behaviour.** No change. `state: &ConsensusState` is immutable, so `last_committed` cannot change during the walk. `skip` is computed exactly as at the base (:66-70). `skipped.note` runs only inside `if skip` and touches only `skipped`. `buffer`, `already_ordered`, `ordered` and the later sort are untouched. The map is read only by `log`, which runs before the sort and returns nothing.
2. **Values.** Correct.
   - `note` re-reads the same `state.last_committed` and counts only `round < last`. A certificate skipped because it was already ordered was pushed with `round > last`, so it is never counted; a frontier skip (`round == last`) is not counted either.
   - `skipped` counts the map's distinct `(round, origin)` keys; `edges` counts every edge that hit such a skip. `skips` is ordered by the BTreeMap key `(Round, AuthorityIdentifier)`, which is deterministic (L7).
   - Bound: entries need a parent round `> gc_round`. The walk stops expanding at `x.round() == gc_round + 1` (:51-54), and the dag holds one certificate per (round, origin), so the map has at most gc_depth × committee size entries.
3. **Cost.** One extra `HashMap::get` per skipped edge (mostly already-ordered hits: about 150-200 per sub-dag of 2 rounds × 10), one BTreeMap insert per strictly-below edge. Once per committed leader, for microseconds.
4. **Tests.** Field names are pinned, and `leader_round`=3, `skipped`=3, `edges`=5 and the exact `skips` text. The test also checks the skipped origins are absent from the output and nothing is logged before a commit.
5. **Rules.** Ok. The `expect` calls are in the test module.

## F: added INFO volume per node at bench load

Assumptions: ids are base58 of 32 bytes (44 characters, committee.rs:787-790); a line prefix is about 55 bytes; about 24 certificates per second; 2.5 own headers per second.

| line | lines/s | bytes per line (added) | bytes/s |
|---|---|---|---|
| `certificate accepted` (new) | ~24 | ~250 | ~6.0 kB |
| `quorum reached` / `header uncertified` (grown) | 2.5 | +~355 typical (6-7 arrivals), +~1.1 kB worst (9 arrivals and 9 error entries) | ~0.9 kB, ≤ 2.7 kB |
| `order hold released` (new, hold on) | ≤ 2.5 | ~150 | ≤ 0.4 kB |
| `subdag parent skipped` (new, rare) | ≤ 1.25 | ≤ ~650 | ~0, ≤ 0.8 kB |

Total: about 29-31 new or grown lines per second per node, about 7.5 kB/s typical and at most about 10.5 kB/s (27-38 MB/h). This is under 1 % of the 2026-11-05 DEBUG incident (about 1.1 MB/s). It is buffered writes with no fsync: a handful of writeback IOPS against a disk bound at 4.5k-20k. CPU is a few µs per line.

It does not disturb what bench 8 measures. The only part on a latency path is L1 and L2: tens of µs per header against vote rounds of hundreds of ms.

## Findings

Critical, High, Medium: none.

- **L1 (cost, 3dfd7e0b0).** `VoteRound::finish` renders both lists under the mutex, even when INFO is off. It runs inside `VotesAggregator::append` (votes.rs:78) before the certificate is returned, adding about 10-40 µs to each header's quorum-to-certificate path. Fix: copy the Vecs out under the lock and render outside it, or render only when `enabled!(Level::INFO)`.
- **L2 (cost and doc, e8eb8e199).** `certificate accepted` is formatted before `parents().send(..).await` (certificates.rs:53-69), a few µs per certificate. `first_sent` is set before that await (:161), so back-pressure on the parents channel would show in later `late_ms`. Fix: log after the send, or document the zero as "when the quorum certificate was appended".
- **L3 (tests).** No value test for `retry_answer_kind` / `final_answer_kind` (certifier.rs:1054-1084: `deferred`, `timeout`, `network`, `parents_unavailable`, `other`), and none for 453123d5e's `invalid_vote` entry (:461). Fix: one table test per helper.
- **L4 (doc).** In `vote_errors`, `kind` is the latest non-vote answer's code and `count` counts answers of every kind (votes.rs `record_error`). node-fields.md does not say which.
- **L5 (doc).** `order hold released` `digests`: on `requeue_on_commit` the line also comes after the re-queue (`prepend_requeued` proposer.rs:1119-1124, release :1128-1131), not only on a cancel.
- **L6 (doc).** node-fields.md's "read at this tip" proposer citations are at e8eb8e199. At fdb9d22a9, b3067a77e has moved them: :1430 → :1554, :932-941 → :998-1007, :1365 → :1479 (by hunk arithmetic, +114).
- **L7 (doc).** `skips` is ordered by `AuthorityIdentifier`'s `Ord` on the raw bytes, not by the base58 text. A script that re-sorts by the printed id can get a different order.

No finding: the ids are the full base58 form (`AuthorityIdentifier` has only that Display); the kind codes match node-fields.md; `source` cannot tell a broadcast from a fetch, as stated.

## Corrections to node-fields.md

1. Vote round, `vote_errors` row. Old: "one entry per voter that answered with something other than a vote". New: "one entry per voter that answered with something other than a vote; `kind` is the code of its latest such answer, `count` counts all of them whatever their code".
2. `certificate accepted`, `late_ms` row. Old: "0, or milliseconds since that first send (monotonic clock)". New: "0, or milliseconds since the quorum certificate was appended, just before the first send was awaited (monotonic clock)".
3. The same section. Old: "(`proposer.rs:1430`) … (`:1365`) … (`:932-941`, …)". New: "(`proposer.rs:1554` at fdb9d22a9; :1430 at e8eb8e199) … (`:1479`) … (`:998-1007`, …)".
4. `order hold released`, `digests` row. Old: "on a cancel the line comes after the re-queue, so the cancelled header's own digests are counted". New: "on a cancel or a requeue_on_commit the line comes after the re-queue, so the header's own re-queued digests are counted".
5. `subdag parent skipped`. Old: "the lowest ten by (round, origin)". New: "the lowest ten by (round, origin), origin ordered by its raw id bytes (not by the base58 text)".
