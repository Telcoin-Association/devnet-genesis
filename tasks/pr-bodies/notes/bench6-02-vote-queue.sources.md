# Sources: tasks/pr-bodies/bench6-02-vote-queue.md (PR 02, `fix/1804-vote-queue`, head 6ad315794, prev 9ef55c989)

Not posted. Figure or claim → where it comes from. Code read with `git -C /home/drtnarg/coding/telcoin/telcoin-network show <sha>`; main = 45dce8947.

## Summary
- default `false`, field `Parameters::vote_queue_fix`: ce212d230 (crates/config/src/node.rs, `Default for Parameters`, `runtime_switches!`).
- wait up to 1 s before the lock, check under it without a wait: 6e14debce handler.rs hunks at `vote_request` (`timeout(VOTE_EXECUTION_WAIT, wait_for_execution)` before `auth_last_vote.get`) and `vote_inner` (`check_execution_block` when the switch is on). `VOTE_EXECUTION_WAIT` = 1 s: main crates/config/src/consensus.rs:459.
- `SupersededRequest` recoverable, no penalty: 6e14debce error/network.rs (`From<&PrimaryNetworkError> for Option<Penalty>` → None; `is_author_content_fault` false), message.rs (`RecoverableError`); test `superseded_request_is_recoverable_and_not_penalized`.
- `vote_timeout` below 9 s with the switch on: 031a89d56 (`validate_vote_timeout`, `vote_timeout + VOTE_EXECUTION_WAIT < LIBP2P_REQUEST_TIMEOUT`); LIBP2P_REQUEST_TIMEOUT = 10 s at main crates/config/src/consensus.rs:449; doc 6ad315794.
- counts by outcome on every node: 32994d7fe (`record_outcome` called unconditionally in the timing finish path).
- compare link: `git rev-parse 9ef55c989 6ad315794` = 9ef55c989dc46d7b10961538781e9e55a81df0a3, 6ad315794b8f641f7ce0f2e2b8b24d7322cee6ab; 10 commits = `git log --reverse 9ef55c989..6ad315794`.

## Problem
- main handler.rs (`git show 45dce8947:crates/consensus/primary/src/network/handler.rs`): lock taken :1029-1033 (`auth_lock.lock().await` :1032); `timeout(vote_timeout, vote_inner)` :1158-1162; execution wait :1462-1507; pending attached parent accepted :1845-1855 (wait itself at :1552). Same lines in the bench-6 comment on #1804 and tasks/checkpoint-bench7-PT-2.md.
- the requester's cancel does not reach the voter: 9dbb01f9b (message + test `vote_request_cancelled_by_requester_still_runs_on_the_voter`); main certifier.rs:834 `self.new_proposal.notify()`; PT-2 checkpoint notes (network-libp2p consensus.rs close_inbound).
- sixth of six queued requests after the 5 s vote timeout: 87e53f510 test `vote_queued_requests_of_one_author_wait_in_turn` (asserts `last > vote_timeout`, `Parameters::default().vote_timeout` = 5 s).
- bench 5, r20261107-1504, validator-01 waited 7.3 to 8.5 s for the lock on validator-04's requests: #1804 bench-6 comment ("Voter side", "bench 5's validator-01 waited 7.3-8.5 s for the lock on validator-04's requests at 17:45"); #1804 body, Evidence ("waiting 7.3 to 8.5 s for the lock").
- bench 6 ran an earlier version on an older base in all four runs: #1804 bench-6 comment ("`vote_queue_fix` (on in all four runs)"); bench 6 node build = `bench/bench6-2026-11` at 2df831e3c (u-common.md); review scope 02 ("Bench 6 ran with this fix on in all four headline runs on an older base ... a re-application on new code").
- `lock_ms` p95 0 on every voter in every window of the four runs: #1804 bench-6 comment, "Voter side" paragraph 2.
- author-side rule on in all four runs; "they show the level, not what the switch alone did": #1804 bench-6 comment, "Voter side" paragraph 3.
- the wait moves from `lock_ms` to `prelock_wait_ms`: 6e14debce (`timing.enter(VoteStage::PreLockWait)` before `lock_wait`); review 02 finding 1.
- `prelock_wait_ms` p95 1,001 ms in r20261113-1630 and r20261114-0000: #1804 bench-6 comment; for r20261113-1630 also benchmark/private/bench6-r20261113-1351/A2/certification.md:131 ("1001 (05)").
- 93,730 `superseded` answers against 265 refused-behind votes, 600 × 16 blast mixed phase, r20261113-1630: benchmark/private/bench6-r20261113-1351/A2/certification.md:131 (table "window (r20261113-1630)", row "b2 mixed": refused behind 265, superseded answers (log) 93730); column definitions :144; report tasks/bench6-report-r20261113-1351.md:361.
- "a voter without the block still does not vote": report tasks/bench6-report-r20261113-1351.md:366 (mechanism step 3, "read and measured"); A2/certification.md:12.

## Change
- per commit: the commit itself (message and diff).
- mark in memory, empty each epoch: review 02 answer 2e (handler built per epoch, start_epoch.rs:1141 → network/mod.rs:3682).
- refused at three points; under the lock after the cached vote and the recast: 6e14debce (`refuse_superseded_request` calls) and review 02 Q3.
- the repeat of an older voted header refused, nothing signed either way: 6e14debce tests `vote_queue_fix_refuses_repeat_of_voted_header_after_newer_request` / `vote_queue_fix_off_answers_repeat_of_voted_header_from_cache` (`repeats_of_voted_headers`).
- 9106fb991: handler.rs `if in_window && header.validate(...).is_ok()`; commit message ("not refused ahead of the lock, because the entry it leaves refuses a later header of the same round").
- 031a89d56: default and both presets (mainnet, adiri) pass: test `default_and_shipped_timing_pass_with_vote_queue_fix`.

## With the switch off
- review 02 answer 2a (empty map; `record_outcome`; `prelock_wait_ms=0`; stage loop over eight stages with PreLockWait None; registration of the `prelock_wait` histogram, its timeout label and ten outcome counters; three bool reads; `.ok()` restructure). Checked against the head: the three reads are in `vote_request` (pre-lock block), under the lock, and in `vote_inner`; the fourth read is `validate_vote_timeout` (031a89d56), run when the node sets up consensus for an epoch it can vote in.
- `vote_queue_fix=false` on the `node switches` line: ce212d230 `runtime_switches!` entry; tasks/bench7-contract.md:36.
- mixed fleet: review 02 answer 2b. Correction made from the code (see hand-back): with the switch off, a lower-round request after a newer one is decided as main decides it (`AlreadyVotedForLaterRound` if the newer header was voted; evaluated normally if the newer one ended recoverably, because the entry is restored), not only "`AlreadyVotedForLaterRound` or the cached vote".

## Testing
- test names: 6e14debce, 9106fb991, 031a89d56 (`git show <sha> | grep '^+async fn\|^+fn'`).
- gates on 6dae7520f: /home/drtnarg/coding/telcoin/tn-b7-stack/target/tmp/head02-6dae7520f.log:1 (check command), :37 `CHECK EXIT=0`, :38 (nextest command), :1387 `1303 tests run: 1303 passed, 4 skipped`, :1388 `TEST EXIT=0`; fmt EXIT=0: tasks/bench7-cherrypick-ledger.md:39.
- re-cut differs by doc comments and README text only (2 files, +12/-4): tasks/bench7-cherrypick-ledger.md:47, :51; `git diff --shortstat 6dae7520f 6ad315794` = 2 files changed, 12 insertions(+), 4 deletions(-).
- dropped from the text for length: the timing set ran three times in a row (16 tests x3 on PT-2B's branch, 20/20 x3 on PT-2C's: tasks/checkpoint-bench7-PT-2B.md, -PT-2C.md).
- the next benchmark runs it on with the author-side switch: benchmark/arms/bench7-always.arm:9 and bench7-adaptive.arm:9 (`param vote_queue_fix true`).

## Limits
- pending-parent wait: 6e14debce test `vote_queue_fix_newer_request_waits_for_pending_parent_wait`; ce212d230 field doc; PT-2 notes (#1842).
- worst case 1 s + lock wait + `vote_timeout`: L2 in tasks/checkpoint-bench7-PT-2B.md notes; review 02 2c; 031a89d56 message ("the time a request waits for the author lock ... is not counted").
- 800 = 8 connections × 100 streams; unbounded vote serve class by default: review 02 answer 2d and Q4 (network-libp2p/src/consensus.rs:244; libp2p-request-response default 100).
- a header failing only a check under the lock still waits: 9106fb991 code comment ("every other check of `vote_inner` (the attached parents, the drift tier, the seed signature) stays under the lock").
- mark before header checks; malformed header below it gets `SupersededRequest`, not its penalty: 591c892b5 doc on `refuse_superseded_request`; review 02 Q2.
- `LastProposed`: I5 (tasks/checkpoint-bench7-PT-2B.md notes; review 02 Q1).
- compare `total_ms`, not `lock_ms`: review 02 finding 1.
- nothing open before merge: review 02 findings 2 to 4 fixed in 6dae7520f; L1 fixed in 9106fb991; L2 bound added in 031a89d56, docs in 6ad315794; finding 1 is the benchmark harness, not this PR.

## Left out
- bench 6 run 1 (r20261112-1520) arm comparison "`lock_ms` p95 3,597-7,892 ms → 0 with it on, back with it off" (report :384): no public run page, and `lock_ms` with the switch on no longer holds the execution wait, so the drop is partly the field move.
- validator-02 round 1073 `lock_ms=291 exec_wait_ms=1001` (bench 5): traceable (#1804 body, Evidence), cut for length.
- the ordering note (one author's requests take the lock in the order their waits end; review 02 2f): cut for length; at most one vote per author and round still holds.
