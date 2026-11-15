# SR-N34: heads 03 and 04 reshaped onto upstream main 33b727fce

Read-only review, 2026-11-15 13:22 UTC.
Repository `/home/drtnarg/coding/telcoin/tn-b7-p2`, git object reads only.
N = `33b727fcea4f6004d4b0cd2bd7923258e081e94f`; `b7/n1-02` = 17327280d; `b7/n1-03` = c2f266b9c (head 03, 3 commits); `b7/n1-04` = 14fde16f4 (head 04, 26 commits).
Every `path:line` is at `b7/n1-04` unless it says otherwise.
Method: the interdiff against the reviewed form (`git range-diff ad83a72f3..cd52dcd81 b7/n1-02..b7/n1-03`, the BF-04a tables of old and new commits), then the production code of `crates/state-sync/src/epoch.rs` diffed against N, then what N's new stop and the stack do together.
No cargo run.

## Verdict: APPROVE WITH FIXES

Nothing at Critical, High or Medium.
The fixes are doc and test-text wording (one Low, the rest Info); the code is right as it stands.
With head 04 on N a peer cannot stop an honest node in any way N alone does not allow at the same signer bar, the evidence read cannot lose a conflict (only delay it on the startup path, as N's own save await can), and every switch off leaves sends, votes, signatures, stores and execution as on N.

## Findings

### 1. Low: two docs say the conflicting record carries a super-quorum certificate of the anchor committee

- Location: `crates/state-sync/src/epoch.rs:210-214` (doc of `Collection::refused`: "with a super-quorum certificate of the committee that record hands over to"), `crates/state-sync/src/metrics.rs:56-57` (doc of `epoch_record_conflicts_total`: "with a super-quorum certificate").
- What the code accepts: `validate_record_against_anchor` (`crates/storage/src/epoch_records.rs:401-417`) requires the record's own committee to be `committee_compatible` with the previous record's `next_committee` (`crates/types/src/primary/epoch.rs:145-175`: a subset of at least four and at least two thirds), and `verify_with_cert` (`crates/types/src/primary/epoch.rs:60-90`) counts signers against that own committee's `super_quorum`.
- Scenario: an anchor of 10 and an offered committee of 7 give a valid certificate with 5 signers, which is not a super-quorum of the committee the previous record hands over to (7 of 10).
  The next sentence of the `refused` doc ("the certificate takes more than `f` members") and the evidence line ("certified by {signers} of the {committee} members") are right; only the quoted phrases overclaim, which is the old V4 wording point in a new place.
- Fix: say "with a certificate signed by a super-quorum of the record's own committee, a subset of at least two thirds of the committee the record before it hands over to" in both docs.

### 2. Info: the operator README describes the stop line but not the evidence line in front of it

- Location: `crates/tn-reth/README.md:1284-1292` (N's text, #1849).
- The README tells an operator that a conflict logs `a certified epoch record from peers conflicts with this node's own record` and counts `tn_epoch_final_state_mismatches_total`.
  Head 04 adds the `epoch record conflict:` line with the signers, the serving peer and the offered record, and `tn_state_sync_epoch_record_conflicts_total`, which the README does not name (BF-04a part 1 noted that no README mentions the collector).
- Fix: one sentence after the stop line in that paragraph naming the evidence line and its fields, or leave it to the PR text.

### 3. Info (upstream text, outside the stack): the storage README still says a conflicting record from a peer is only logged

- Location: `crates/storage/README.md:427-429`, unchanged by the stack (`git diff N b7/n1-04 -- crates/storage/README.md` is empty).
- Since #1849 the collector stops on a conflicting certified record (`crates/state-sync/src/epoch.rs:530-546`).
- Fix: upstream; worth a line in the #1850 follow-up rather than a stack commit.

### 4. Info: the e2e switch check's error text names a constant this head does not have

- Location: `crates/e2e-tests/tests/it/fleet.rs:312-315`: "add them to STACK_SWITCHES_ON and STACK_SWITCHES_OFF"; only `STACK_SWITCHES_OFF` exists at `b7/n1-04` (`fleet.rs:77`).
- Fix: name `STACK_SWITCHES_OFF` only, or add the other constant in the head that introduces it.

### 5. Info: FATAL_LOGS covers head 04's and head 03's stops but not two of N's

- Location: `crates/e2e-tests/tests/it/fleet.rs:67-68`, `crates/e2e-tests/tests/it/epoch_record_walk.rs:501-504`.
- Covered: the replay guard (`HALT_LOG`), the evidence line (`CONFLICT_LOG`), N's collector stop (`CONFLICT_STOP_LOG`), the closing-block check (`CLOSING_BLOCK_HALT_LOG`), and the vote round's `we have forked!` (checked on its own).
  Not covered: the close-time identity halt and a close-time `save_record` refusal of a rebuilt record 0.
- A running node that stops on either fails the test anyway: validators through `settle`/`assert_blocks_same`, observers through `get_block_number`, every live process through `scrape_metric_value`, which errors after 30 s on an absent series (`common.rs:2292-2311`).
  The own-record observer's run 0, which the test kills itself, is checked by its log lines alone, so a stop there on an unlisted line would pass; the window is between its `epoch record published epoch=1` line and the kill.
- Fix: none needed for this head; add the identity-halt text when a later head's tests can reach it.

### 6. Info (reviewed form, not the interdiff): the vote-queue eviction rule is unconditional

- Location: `crates/node/src/manager/epoch_votes.rs:607-621` (commit ba73ee5f9, picked from 29c36a4ec as the old V3 fix).
- With every switch off, a sixth round now drops ended rounds and then evicts the lowest epoch's round where N pops the front entry.
  It changes which rounds of this node finish and so which certificates this node stores itself; it changes no block, state root, vote, signature or consensus-pack byte.
- Fix: none; the PR text should say it is the one switch-off difference from main in head 04.

### 7. Info: re-closing epoch 0 over this node's own record 0 counts the closing-block check twice

- Location: `crates/node/src/manager/node/close_epoch.rs:460-471` (record-0 arm) and `:505-512` (build path); documented in `crates/node/src/metrics.rs` (`record_closing_block_check`) and pinned by `a_reclose_over_own_record0_counts_the_closing_block_check_twice`.
- The arm's check is redundant with the build path's whenever the boundary header commits the stored record (same block, same `final_consensus`, same seed), and otherwise the build path's beacon-root check or `save_record`'s `ConflictingRecord` stops the node anyway; the arm changes only the refusal's `path=stored` and its reason text.
- Fix: none.

## Answers

### Q1. Remote triggers of a stop

No.
Head 04 no longer decides anything: `Collection::refused` (`epoch.rs:232-267`) logs and counts, then calls N's `stop_on_local_failure` (`:530-546`) for every error; every `ConflictingRecord` stops, as on N, and nothing else does.
The records that reach `refused` are those whose `save` failed after `validate_downloaded_record` returned `Valid` (`epoch.rs:726-736`); storage is untouched by the stack.
Validation (`crates/storage/src/epoch_records.rs:1210-1229`, `:401-417`) requires the record's epoch to be the requested slot, its parent to be the digest of this node's stored record of the epoch before (or default for epoch 0), its committee to be `committee_compatible` with that stored record's `next_committee` (the stored or genesis committee for epoch 0), and a certificate over the intent-wrapped digest signed by a super-quorum of the record's own committee.
That is at least 5 of an anchor of 10 and more than `f` for every committee size (per-step bound, `crates/types/src/primary/epoch.rs:109-128`), so one faulty node, `f` faulty members or a non-member relay cannot produce one; a relay only forwards.
The walk (`may_walk_past`, `epoch.rs:164-190`) widens which epochs are asked: N's pass stops at the first uncertified epoch K, the walk goes on to K+1 onward, up to 16 open gaps, and the gap retry asks K again each interval.
It does not lower the bar: the walked anchor is this node's own record of K, which a peer cannot choose; a node without its own record never walks; and a conflict there needs this node to hold its own, different record of K+1.
N already asks for the first uncertified epoch however old, against the committee its predecessor names, so the long-range exposure to old keys is the same class one epoch later.
The startup sync builds a new `Collection` per pass and walks each pass; same bar.
Head 03 adds no peer trigger in the interdiff: the record-0 arm checks this node's own uncertified record against its own closing block.

### Q2. The evidence read before the stop

It cannot fail: `ConflictEvidence::read` (`epoch.rs:285-310`) uses `record_by_epoch` and `get_committee_keys`, which return `None` on a dead actor (`crates/storage/src/epoch_records.rs:707-726`); the evidence is then empty and the count, the line (committee 0) and the stop follow.
It hangs only where N already hangs: the reads go to the same single epoch-store actor thread that answered `validate_downloaded_record` and `save` a moment earlier, so a stuck actor stalls N's collector at those awaits too.
It can be cancelled only in the startup sync (the 5 s pass cap and the 30 s deadline in `drive_epoch_record_sync`, `:458-462` and `:504-512`, and shutdown).
A cancelled attempt has counted and logged nothing, because the count, the line and `stop_on_local_failure` run in the poll that completes the read, with no await between them (`:243-266`).
The record collector meets the same conflict again: its pass is not raced against anything (`:926-934`), and the gap retry's deadline wraps only `request_epoch_cert` (`:810-815`), not `store_epoch_record`.
So a conflict is delayed (until the collector's next pass reaches the epoch), not lost, as long as a peer still serves the record; N has the same window at its own `save` await.
`tn_epoch.final_state_mismatches_total` is incremented once per completed attempt inside `stop_on_local_failure`, together with `tn_state_sync.epoch_record_conflicts_total`; never for a cancelled attempt; once with an empty evidence read; never on a hang.
`test_a_conflict_cancelled_at_its_evidence_read_is_counted_once` pins the order.

### Q3. The re-certify rounds

A re-certify round stops the node only through N's recovery ladder (`epoch_votes.rs:367-439`): a record fetched from a peer that `validate_downloaded_record` accepts and whose digest differs from this node's.
That is the same evidence N's collector stops on when it reaches the epoch; the round only reaches older epochs (N-16 to N-2) the collector would not ask while an earlier epoch is uncertified, which is the walk's widening again, at the same bar, and only with `epoch_record_recertify` on.
Kept votes cannot cause a stop; they can only end a round with a certificate.
Kept signatures are keyed by `(epoch, digest)` and the committee index in that record (`RetainedVotes.votes`, `:1061-1069`); a round keeps a vote only when its epoch and digest are the round's (`:212-237`, drain `:456-463`); the vote signs the intent-wrapped digest, and the digest commits to the epoch and the committee in order (`EpochRecord::digest`, `sign_vote`).
A signature cannot move to another epoch or record, and `certify_record` (`:88-128`) verifies the aggregate before it saves, dropping the record's kept signatures if it fails.
A re-derived record is the deterministic close-time record, so it changes nothing here.
A committee that changed since the epoch does not enter: the round uses the record's own committee, and the recovery anchors on the stored record of the epoch before.
With the switch off, `retained` is `None` and the rounds are N's but for the eviction rule (finding 6) and the `cert_by_digest` read on a short round (reviewed form).

### Q4. Head 03 at N

No false refusal found.
Restart in the close of epoch 0: a kill before record 0 is written leaves the dummy, so the entry re-derives through the build path; a kill after it is written but before the closing block persists replays the close, and the record-0 arm compares a deterministic re-execution of the same block; a restart in epoch 1 with record 0 stored runs the entry check with no seed.
None of these differ from the reviewed form except the record-0 arm, which cannot refuse where the build path would pass (finding 7).
Snapshot-restored datadir: below the floor nothing is compared (`check_stored_final_state`, `close_epoch.rs:1382-1384`, then `stored_restored`); at the floor N now compares the block, and head 03 checks its markers too.
That header is the exporter's full header, whose hash `import_chain_scaffold` binds to the certified record's `final_state` (`crates/tn-reth/src/snapshot.rs:650`), so its beacon root, nonce and `extra_data` are the original engine's and pass; above the floor the node executed the block itself.
adiri early epochs: `closing_marker_checked` (`:1534-1544`) skips the `extra_data` compare at or below 160 on every path, the record-0 arm included; the beacon root and nonce are compared only after `final_state` matched, so they are the historical block's own fields.
The seed rule is the same on both stored calls: `self.closing_seed_for(&epoch_rec)` at `:465` (record-0 arm) and `:481` (reuse); the entry passes `None` (`:670`) and the build the boundary header's randomness (`:509`).

### Q5. Remnants of the dropped switch

`git grep` at `b7/n1-04` over `crates` for `conflict_halt`, `below_halt_threshold`, `conflict halt:`, `keeps its own record`, `round_conflicts_total`, `halt_threshold`, `conflicts_below` and `in a re-certify round` finds nothing; the commit bodies of `b7/n1-02..b7/n1-04` name no halt or threshold of head 04.
The config docs (`crates/config/src/node.rs:399-405`, `:426-438`), `manage_epoch_votes` (`epoch_votes.rs:139-144`), `refused` and the collection docs say a conflict stops the node, with the walk on or off, in the collector, the gap retry, the startup sync and the vote rounds.
Misstatements left: finding 1 (two docs, Low) and finding 3 (N's storage README, outside the stack).

### Q6. Determinism with no conflict and every switch off

Nothing in the interdiff changes what a node sends, votes on, signs, stores or executes.
Head 04: the evidence read and both counters run only on a `ConflictingRecord`; with the walk off `may_walk_past` returns at once and the pass returns on a refusal before the persist, as on N; the startup sync's progress read is N's `first_missing_historical_cert(Epoch::MAX)` plus a gauge; `request_epoch_cert` returns the peer for logs only.
Head 03: the record-0 arm is a read-only check plus a counter; the reuse and entry seeds are N's head-03 rule refactored into `closing_seed_for`.
Outside the interdiff, the reviewed form's eviction rule (finding 6) is the one switch-off behaviour change, and it touches no block, state root or pack.

### Q7. The e2e commit

The switches cannot be silently off: `assert_switches` (`fleet.rs:283-320`) reads every node's `node switches` line, which the node logs from the same `Parameters` the collector and the vote collector read, and fails on a wrong value or an unlisted switch.
The walk and re-certify arms also need the behaviour: walk lines with `epoch=1 gaps=1`, the observer fetching records 2 and 3 and publishing past the gap, the re-certify line and a `certified` re-certify count; the gap arm needs the opposite.
A node that stopped fails the test (finding 5): validators through `settle` and `assert_blocks_same`, the restarted and fresh observers through `get_block_number`, every live process through the scrapes of the conflict and mismatch counters.
The fatal lines are complete for head 04's stops (the evidence line, N's stop line, the vote round's `we have forked!`) and head 03's (closing-block check, replay guard); two of N's other stops are caught only by liveness.

### Q8. The old reports' findings at `b7/n1-04`

Report 03:
- 1 High (leftover drain forwards X+1 after a dropped send): still applies; `run_epoch.rs:718-732` unchanged in kind; not head 03's, it is head xf's (#1860).
- 2 Low (refusal reason per path): fixed, `RecordCheckPath::halt_reason` (`close_epoch.rs:1426-1433`).
- 3 Info (re-derive logged as built): fixed, `RecordCheckPath::Rederived`.
- 4 Info (empty ring reported as beacon_root): fixed, `ClosingBlockCheck::NoBlock`.
- 5 Info (engine-equivalence test bypasses the payload builder): still applies.
- 6 Info (stale adiri Cargo.toml comment): fixed, `crates/node/Cargo.toml:46-50`.
- 7 Info (floor branch compares nothing): fixed by N (#1849) for the floor block, which head 03 now checks too; below the floor nothing is compared, by design.
- 8 Info (seed implied by beacon root): still applies, a design note.

Report 04:
- V4 Medium (threshold below a super-quorum, overclaiming message): moot; switch and threshold dropped, N's stop decides, the evidence line states S of M signers; the 5-of-10 property is N's rule (raised on #1850); a wording residue is finding 1.
- V2 Medium (gap retry holds the loop): fixed, `GAP_RETRY_DEADLINE` and a shutdown select (`epoch.rs:786-859`), fair restart point (`retry_from`).
- V3 Low (eviction of a switch-off node's current round): fixed, unconditionally (finding 6).
- V1 Low (recertify stops whatever the halt switch says): moot; the docs now say the round stops the node and repeats after a restart (`crates/config/src/node.rs:399-405`).
- V5 Low (turning the halt on stops a node holding a conflict): moot.
- V7 Low (unlanded walk repeated every wake-up): fixed in the collector (`unlanded_walk`); the startup sync walks each pass, as documented.
- V8 Low (refusal after a walk skips the persist): fixed (`epoch.rs:628-643`); a conflict or a failed save still ends the pass before the persist, as on N.
- V9 Low (failed read drops a gap): fixed (`epoch.rs:806-808`).
- V10 Low (re-certify accounting): fixed for the signers gauge (`round_kind` keyed on the epoch) and the missed-votes label; the outcome counter still credits the next round of a marked epoch, as documented in `recertify_older_record`.
- V11 Low (kept quorum not aggregated): fixed (`epoch_votes.rs:464-502`).
- V12 Low (lines lack operator evidence): fixed (signer ids, offered record fields, peer on the invalid-record line).
- V6: refuted then, still not a defect.
- Info items: the vote round's stop is still uncounted in `final_state_mismatches_total` (N's design), and with the re-certify round's own conflict counter gone, a re-certify stop leaves only its `we have forked!` line.
