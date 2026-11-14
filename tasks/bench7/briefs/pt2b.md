# PT-2B — port the voter's queue fix (`vote_queue_fix`, issue #1804) onto M's reworked vote handler

Unit: `PT-2B` (node port unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-2B.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt2b`, branch `b7/pt2b`, base = the integration head with PT-0's switch machinery in it; the orchestrator creates it and cherry-picks phase A's test commit (4d6ab6191, `vote_queued_requests_of_one_author_wait_in_turn`) onto it first. Domains: `tn-domain-consensus`, `tn-domain-networking`. Topic slug: `voter-lock`. Stack head: `fix/1804-vote-queue` (PR 02). `Refs #1804`.
Read first: `tasks/bench7/briefs/pt0-api.md` (how to add a switch field), then **phase A's findings in full**: `tasks/checkpoint-bench7-PT-2.md` (what the wait is on M with `file:line`, what applies straight, what collides, the invariants). This brief only adds the decisions.

## Verdict of phase A (binding)

PORT. On M a vote request still waits behind an earlier request of the same author on that author's lock, for up to `vote_timeout` per request ahead, and a queued request's own lock wait is not bounded; upstream's rework (#1822, #1839, #1842, #1844, #1846) did not shorten the hold. The fix is a straight port of bench-6 commit 2b9a69925 (and the field 82ed5801a, redone on PT-0's machinery), with hand resolution in `vote_request`.

## Decisions (the orchestrator's; build exactly these)

1. **Collision (a): the superseded refusal against M's cached vote and stored-vote recast.** With the switch on, a request for a strictly lower round than the author's newest in-window request is refused as `SupersededRequest` BEFORE the lock, which on M is ahead of #1844's cached-vote hit and #1839's stored-vote recast (both now under the lock). So a repeat of an older header this node already voted for, arriving after a newer request of the same author, gets `SupersededRequest` instead of its vote. **Accept this and pin it in a test**: the author abandons header r when it proposes r+1 (the certifier cancels r's requests), so the vote has no reader; nothing is signed, the cached vote is untouched, #1836's bound (at most one signature per voted header) and #1844's rule (only a vote for a newer header replaces the cached one) hold. Do NOT add a lock-free copy of the cached digest. The test asserts all of that: the refusal, no new signature, the cached entry unchanged, and that a repeat of the NEWEST voted header is still answered from the cache.
2. **Collision (b)**: the third check (after the lock is taken) goes after the cached-vote hit and the recast, and before `previous_vote`.
3. **Collision (c)**: correct the doc of `vote_queue_fix_keeps_equivocation_refusals` (the recast is under the lock on M).
4. **Collision (d)** (`network/mod.rs` ≈ :3773-3781, the comment on vote permits): not your file; another unit is editing `network/mod.rs`. Put the corrected sentence in your hand-back; the orchestrator applies it at integration.
5. **The scope gap phase A found is NOT closed here**: #1842 added a wait for a pending attached parent under the lock (≈ :1552, up to `vote_timeout`); after the port a newer request still waits behind an in-flight older one for whatever it spends there. Covering it would mean cutting short an in-flight request, which is beyond the bench-6 design. State it in the switch's doc and in the commit body; add one test that MEASURES it with the switch on (an in-flight request parked on a pending parent; the newer request's answer time), so the number exists for the issue.
6. **The superseded-refusal counter** (the bench-6 review's follow-up, `tasks/bench6/review/vote-starvation-report.md` ≈ :148-154): the outcome exists only on the debug line `vote path timing` (`outcome=superseded`). Add `tn_primary.vote_outcomes_total{outcome}` fed from the handler's outcome type's `as_str` (every outcome, not only `superseded`; static label values), no switch, counted with the switch off too (where `superseded` simply never occurs). If M already counts vote outcomes somewhere, extend that instead and say where.

## Files you own

`crates/consensus/primary/src/network/handler.rs`, `crates/consensus/primary/src/error/network.rs`, `crates/consensus/primary/src/network/message.rs` (only if the recoverable arm needs the new variant), `crates/consensus/primary/src/metrics.rs` (**your additions only**: `VoteStage::PreLockWait` and its label, the outcome counter; a serial chain of other units edits this file's proposer metrics: keep your hunks local), `crates/consensus/primary/src/tests/network_tests.rs` (at the END, under the `// ---- bench7 voter-lock ----` marker phase A opened; another unit appends its own block after yours later), `crates/config/src/node.rs` (your field only).
Not yours: `consensus_bus.rs` (nobody's; phase A found no edit is needed), `network/mod.rs`, `proposer.rs`, `certifier.rs`.

## Names (frozen by bench 6; the harness and the analysis scripts parse them — `tasks/bench6-contract.md`, the voter-lock row)

Switch `vote_queue_fix`; error `SupersededRequest`; stage label `prelock_wait` (`VoteStage::PreLockWait`, the FIRST stage: the other stages' indexes shift by one) in `tn_primary.vote_stage_seconds{stage}` and `tn_primary.vote_timeouts_total{stage}`; outcome `superseded`; field `prelock_wait_ms` on the `vote path timing` line right after `outcome`, 0 with the switch off. Verify each against the contract file and report any difference.

## Tests

The seven bench-6 tests of the fix plus the error-mapping and outcome unit tests, re-expressed on M's types; phase A's test kept as the switch-off regression test; the tests of decisions 1 and 5; M's own vote tests (the equivocation, cached-vote, recast, cancelled-request and pending-parent tests of #1822/#1839/#1842/#1844/#1846) pass unchanged with the switch off AND with it on (run the handler's test module twice if the tests can take the switch as a parameter; otherwise add switch-on twins of the invariants named in phase A's "Invariants the port must keep").
Whole-package nextest for the primary and the config packages; clippy; fmt; each timing test three times by name (the host is heavily loaded: tests use the paused clock wherever phase A's did).

## Gates and review

As the rules say; one `tn-domain-reviewer` (opus) on your diff, domains consensus and networking, asked: with the switch on, can an honest author be denied a vote it still needs (liveness); can a Byzantine author use the high-water mark to make this node refuse another author's or its own later requests; does anything in the port weaken #1836/#1839/#1844 (one signature per header, the cached vote) or #1842 (cancelled requests leave the entry as found).

## Hand back

As the rules say, plus: the port's commits with the bench-6 sha each came from; decision 1's test names and what they assert; decision 5's measured wait; the outcome counter's label values verbatim; the corrected sentence for `network/mod.rs`; anything in M's handler that makes bench 7's voter path differ from bench 6's (for the run facts).
