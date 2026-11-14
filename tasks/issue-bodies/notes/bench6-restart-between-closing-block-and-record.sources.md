# Sources: bench6-restart-between-closing-block-and-record

Not for posting. Every figure and claim of the body, and where it comes from.

## Reproduction (bench 6 e2e, read-only worktree /home/drtnarg/coding/telcoin/tn-b6-u2)

- Test module: `crates/e2e-tests/tests/it/epoch_close_forms.rs` on branch `b6/st-epoch-close-forms` (tip 8c1c27764, base 2df831e3c, not pushed). Node code unchanged from `bench/bench6-2026-11` at 2df831e3c.
- Four validators, 120 s epochs, nodes 2 and 3 held + `TN_TEST_EXIT_BEFORE_EPOCH_RECORD`: `tasks/checkpoint-bench6-ST-E.md` lines 24-25.
- Runs 1 (sha 5faa128d3) and 2 (sha 00d592308) used epoch 0 for the hook: checkpoint lines 8-10; handoff `tasks/bench6-handoff-2.md` line 152.
- "8 restarts, all 8 exited": counted per file, `tn-b6-u2/target/tmp/st-e-run{1,2}-logs/missed_record_round_{adaptive,always}/node{2,3}-run0.log` (hook line `test hook: exiting before the epoch record is written epoch=0`, 1 each) and `node{2,3}-run1.log` (error `We have epoch 0 in our database if we are past epoch 0, on 1`, 1 each). 2 runs x 2 tests x 2 nodes = 8, 8/8 hook + error.
- stderr: `node2-run1.stderr.log` prints `Error: We have epoch 0 in our database if we are past epoch 0, on 1` / `Location: crates/node/src/manager/node.rs:1294:13` (bench-6 line; on M 1320-1325).
- Example node: `st-e-run1-logs/missed_record_round_adaptive/node2-run0.log` line 596 (hook, epoch=0, 21:22:22.197371Z); `node2-run1.log`: start 21:23:27.255956Z, `Engine stated from block 38/0x1293…` 21:23:27.278985Z, `read entered-epoch base fees from the closing block's on-chain record entered=1 closing_block=38 …` 21:23:27.281992Z, `Error running node: …` 21:23:27.296373Z → 40.4 ms after start.
- "12 restarts, all 12 re-derived": runs 3, 4, 5 (sha 8c1c27764), same file pattern; `node{2,3}-run0.log` hook `epoch=1` (1 each), `node{2,3}-run1.log` `re-deriving it locally` (1 each): 3 x 2 x 2 = 12/12. All four tests PASS in runs 3-5: checkpoint lines 12-14.

## Code on main 45dce8947 (/home/drtnarg/coding/telcoin/telcoin-network-b7)

- Guard: `crates/node/src/manager/node.rs:1320-1325` (`if !contains_epoch(0)` → `eyre::ensure!(committee.epoch() == 0, "We have epoch 0 in our database if we are past epoch 0, on {}")`); dummy built from current committee at `:1326-1331`.
- Startup committee from canonical tip: `node.rs:998-999` calls `get_committee_with_epoch_start_info`, `crates/node/src/manager/node/start_epoch.rs:230`, tip sampled at `:239`.
- `sync_epoch_records_to_tip` after the guard: `node.rs:1334`.
- Nothing writes a record before the guard: `run()` 868-1320 has only reads of `epochs()` (`seed_node_mode_on_startup` :1015, `revote_uncertified_epoch_record_on_startup` :1293); `try_restore_state` :1860-1934 touches no record (awk over the ranges).
- Dummy in memory only: `crates/storage/src/epoch_records.rs:2188-2195` (`self.dummy_epoch0 = Some(record)`); `contains_epoch` `:2479-2487` (epoch 0 with empty index → `dummy_epoch0.is_some()`).
- Hook on M: `crates/types/src/test_hooks.rs:185` (static), `:42` (fn); fired at `crates/node/src/manager/node/run_epoch.rs:510-519` after `close_epoch` (:496-502) and before `write_epoch_record` (:523); comment ":516-517 stop where a SIGTERM inside this window stops".
- Recovery: `close_epoch.rs:559` `recover_previous_epoch_record`; `:565-567` returns for current_epoch 0; `:569-571` dummy-only epoch 0 falls through to re-derive; `:628-643` tip == closing block check; `:662-672` re-derive log + `write_epoch_record`; called from `run_epoch.rs:238`.
- `write_epoch_record` epoch-0 branch: `close_epoch.rs:424-429` (epoch 0 reuses only a certified record), `:495-499` (`prev_record = None` for epoch 0); persist right after save `:514-518`.
- "record cannot be written before the closing block executes": `close_epoch.rs:527-529`.
- "fatal for epoch 0" comments: `close_epoch.rs:384-385`, `:515-517`.
- Window width: `crates/e2e-tests/tests/it/restarts.rs:865-868` ("It lasts about 200 ms per boundary"), `:884` ("A SIGTERM lands in a 200 ms window only by luck").
- Boundary-window test: `restarts.rs:899` `test_restarts_cohort_exits_in_epoch_boundary_window`, `BOUNDARY_WINDOW_EPOCH = 6` at `:745`; re-derive log constant `:785`.
- eject workarounds: `crates/e2e-tests/tests/it/eject.rs:526-532` (in `test_validator_ejected_from_current_committee_mid_epoch`, fn at :450) and `:835-841` (in `test_committee_member_restarted_mid_epoch_after_ejection`, fn at :793); text "pre-existing product issue".
- Genesis committee: `node.rs:772-780` (`committee_zero`), passed to `ConsensusChain::new` at `:784`.

## Related issues

- #1015 (closed 2026-07-27): "Recovery-arm epoch closes never write the epoch record; an epoch 0 closed this way bricks the node on its next restart" (`gh issue view 1015`). Fixed by PR #1021 "fix(epoch): write and persist the epoch record on all three epoch-close arms" (merged; `gh search prs`).
- No open issue found for the error string (`gh search issues "We have epoch 0 in our database"` → []).

## Reachable on main

Yes, by code. Nothing in #1808 or #1834 moved the guard or the re-derive call; the guard still runs in `run()` before `run_epochs`. One confirming run: `test_restarts_cohort_exits_in_epoch_boundary_window` with the hook epoch 0 (expect every node to exit with the error).

## Revision after the figure-check (tasks/bench7/figcheck-UI2.md §1), 2026-11-14

Changed sentences and their sources (no new figure):
- Title/H1 → "… cannot restart from that datadir" (115 chars): figcheck error 1 (line 23). Reason: `telcoin-network db reset-execution --force` exists on main (`crates/telcoin-network-cli/README.md:487`, the `db reset-execution` paragraph).
- "a SIGTERM, a crash or a power loss inside it leaves a datadir that cannot start" → "A SIGTERM inside it leaves a datadir that cannot restart; by the code a crash or a power loss does too, once the executed closing block has reached disk." (figcheck weak 1, line 31; the hook path is graceful, `run_epoch.rs:510-519`; crash case is an inference from code, not reproduced).
- New: "We reproduced only this graceful stop, then restarted the two validators without the hook." (coordinator instruction; the hook is the only stop the test used: `tasks/checkpoint-bench6-ST-E.md` line 25).
- New: "We have not run it on main; the check and its place before the record sync are the same there as in the build we ran, so it is reachable on main by code, and `test_restarts_cohort_exits_in_epoch_boundary_window` with the hook set to epoch 0 would confirm it." (figcheck weak 2, line 33, and verdict lines 10-16; bench-6 guard `node.rs:1293-1298` at 2df831e3c identical to main's `:1320-1325`).
- "One of them logged `test hook…epoch=0`; on restart it logged …" → "For example, one of them logged on restart `read entered-epoch base fees … entered=1 closing_block=38` and exited 40 ms after it started." (figcheck weak 3; hook line dropped for length, same log as before).
- "We did not try to recover the failed datadirs; by the code, nothing writes a record before the check, so every later start fails the same way." → "By the code, nothing writes a record before the check, so every later start from that datadir fails the same way." (the "not tried" moved into the next sentence).
- New: "By the code, an operator can still recover such a node, though we did not try: `telcoin-network db reset-execution --force` makes the next start rebuild execution from genesis, where the committee is epoch 0's, so the check passes and the replay of epoch 0 writes record 0 at its close; moving the chain data aside and syncing the node as a new one also works." (figcheck line 24, verbatim; README `db reset-execution` paragraph; `close_epoch.rs:418-432` builds over a dummy).
- Item 4: dropped "checks that the canonical tip is the closing block (`:628-643`)," and "For epoch 0 it never gets the chance." (length).
- Dropped "The comments at `close_epoch.rs:384-385` and `:515-518` already call a lost record 0 fatal," (length); the eject sentence kept.
- Fix section: "`new()` already loads it (`node.rs:772`) and hands it to `ConsensusChain::new`." → "`new()` already loads it (`node.rs:772`)."; dropped the "To check while doing it" paragraph and the unit-test bullet (length).
- How to verify: "run `test_validator_ejected_from_current_committee_mid_epoch` and `test_committee_member_restarted_mid_epoch_after_ejection`" → "run the two tests that hold them" (same two tests, `eject.rs:450`, `:793`).
Word count after revision: 887 (`wc -w`).
