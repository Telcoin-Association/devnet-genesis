# Topic review: tracker-drain (#1806)

**Verdict: APPROVE WITH FOLLOW-UPS.** No Critical, High or Medium findings, and nothing has to change before the benchmark image. Two Low findings and four Info findings, all CONFIRMED.

- Code: `/home/drtnarg/coding/telcoin/telcoin-network-b6`, branch `bench/bench6-2026-11`, head `d91d65d3e`. The diff is `git show --format=` of these commits, in order: 901505021, 43158b0d0, 16695b20a, 2783dfa79, bc20ddf27, b77ccbb29, 42b2a6f39, 2c9b43209, 4e9c19782.
- Switches: `epoch_close_task_drain` and `epoch_record_state_check`, both default false.
- What was read: every hunk in context at head, plus the callers and callees this topic depends on. That covers all four `write_epoch_record` call sites, `close_epoch`, `wait_for_epoch_boundary`, `replay_missed_consensus`, `send_leftover_consensus_output_to_engine` and `recover_previous_epoch_record`. It also covers `RecentBlocks`, `wait_for_consensus_execution`, `try_restore_state`, the vote collector, epoch-record sync, `validate_downloaded_record`, the gossip-certificate path and the outer `run` select.
- Method: the `tn-review` skill was invoked on this diff. Two parts of the skill could not run as written. Its intermediate report goes in the repository root, which is read-only here. Its `findings-verifier` agent could not be launched, because this session has no agent tool. Instead, each finding was checked a second time by reading the cited lines again against the claim alone. All six held, so all are CONFIRMED.
- The security evaluation was not run. The scope asks for the code review only, and nothing on the halt path calls for one: a halt needs a record certified by a super-quorum (see 2g-2).

| # | Title | Severity | Status | Before |
|---|---|---|---|---|
| F1 | The e2e test never shows the final-state check ran | Low | CONFIRMED | upstream PR |
| F2 | The drain arm logs a critical task's failure during the close at WARN, not ERROR | Low | CONFIRMED | upstream PR |
| F3 | Log levels in `join_tasks_within` change with the switches off, for every TaskManager | Info | CONFIRMED | — |
| F4 | The vote-skip counter cannot account for every missing signer | Info | CONFIRMED | reading run-1 data |
| F5 | The `epoch_record_state_check` doc leaves out the empty-ring skip | Info | CONFIRMED | upstream PR |
| F6 | The close gauges and the drained line exist only on the live boundary arm | Info | CONFIRMED | — |

## Findings

### F1. The e2e test never shows the final-state check ran (Low, CONFIRMED)
- **Where:** `crates/e2e-tests/tests/it/epoch_drain.rs:119-185`. The no-halt assertion is at `:170`.
- **Scenario:**
  1. The drain arm asserts that no node logs `stored epoch record's final state is not this node's closing block`.
  2. That assertion passes whether or not the slow member (validator 4) took the stored-record branch (`close_epoch.rs:427-435`).
  3. If the slow member found no record stored at its close, it built its own. Then `check_stored_record_final_state` never ran, and the assertion proves nothing.
  4. Nothing in the test tells the two cases apart. With the roughly 95-s detection lag ST-A measured, the slow member almost certainly found the certified record, but the test does not pin it.
- **Fix:** in the drain arm, make three checks:
  - scrape `tn_node_epoch_record_vote_skipped_total{reason="certified_before_close"}` on `SLOW_MEMBER` and require at least 1, or require that it logs no `publishing epoch record vote for epoch 0`;
  - require `tn_node_epoch_record_state_check_skipped_total` = 0;
  - keep the no-halt assertion.
- **When:** before the upstream PR. Not needed for the image.

### F2. The drain arm logs a critical task's failure during the close at WARN, not ERROR (Low, CONFIRMED)
- **Where:** `crates/types/src/task_manager.rs:488-493` (`track_while`), compared with `:630-637` (`join_tasks_within`).
- **Scenario:**
  1. A critical epoch task fails or panics while `close_epoch` waits for execution. An example is `primary network events` (`crates/consensus/primary/src/network/mod.rs:2465-2478`).
  2. With the switch off, nothing polls `tasks` until `wait_for_exit` (`run_epoch.rs:624`). Its join logs `… shutdown with error …` at ERROR.
  3. With the switch on, `track_while` reaps the same event and logs `… returned error … while tracking` at WARN.
- **What changes:** behaviour is the same in both arms. Neither stops the node, because the `until_task_ends` arm was dropped when the boundary arm won. WARN also matches `until_exit_internal`'s existing "while shutting down" branch (`task_manager.rs:552-557`). What changes is visibility: a panic inside the close window is less visible in the drain arm only, so the two arms' error censuses differ. No bench reader counts either line; checked in `benchmark/tools/arms-summary.py` and `benchmark/tests/test_pull_logs.py`.
- **Fix:** in `track_while`, log at ERROR an `Err` whose join error `is_panic()`. Leave the other errors at WARN.
- **When:** before the upstream PR.

### F3. Log levels in `join_tasks_within` change with the switches off, for every TaskManager (Info, CONFIRMED)
- **Where:** `crates/types/src/task_manager.rs:590-640`, commit 2783dfa79. The commit is not behind a switch.
- **What changed:** for non-critical tasks, the `shutdown successfully` and `was cancelled` lines moved from info to debug. This runs with both switches off, on the node, engine, worker and epoch managers.
- **Effect:** log-only. No bench reader counts these lines. The readers count `Failed to track spawned task` (`benchmark/tools/arms-summary.py:121`) and `epoch close drained` (`benchmark/tests/test_pull_logs.py:1399`).
- Listed so that the claim "switch off = before" is exact. No action.

### F4. The vote-skip counter cannot account for every missing signer (Info, CONFIRMED)
- **Where:** the counter is set at `close_epoch.rs:423`, `:432` and `:516` through `EpochRecordVoteSkip::for_record`. The collector it mirrors decides at `crates/node/src/manager/epoch_votes.rs:505-507`.
- **Case (a), a late vote:** a member that builds its own record is counted as "will vote". If its vote reaches peers after their collectors already aggregated (they stop about 1 s after quorum), it is a missing signer with no skip counted. A late vote is not a skip.
- **Case (b), a certificate in between:** the counter reads certification at the close. The collector reads `cert_by_digest` again later, when it handles the watch. If a certificate is saved in between (for example by epoch-record sync, `crates/state-sync/src/epoch.rs:279`), the collector skips a vote that the counter did not count.
- **Consequence:** the issue's bench-6 field ("`epoch_record_vote_skipped_total` explains every missing signer") cannot hold from this counter alone. Read missing signers as skipped plus late. A late signer shows up as a node whose drain ended after the seventh member's.
- **Fix:** state this in the field definition. Optionally, for upstream, count in the collector where it skips rather than at the close.

### F5. The `epoch_record_state_check` doc leaves out the empty-ring skip (Info, CONFIRMED)
- **Where:** `crates/config/src/node.rs:406-414`. The skip itself is in `close_epoch.rs:544-560`.
- **History:** commit 43158b0d0 removed the sentence about the skip, and commit 2c9b43209 did not put it back.
- **Fix:** add one sentence: "With no executed block (an empty recent-blocks ring) the check is skipped, logged at warn and counted in `tn_node_epoch_record_state_check_skipped_total`."
- **When:** before the upstream PR.

### F6. The close gauges and the drained line exist only on the live boundary arm (Info, CONFIRMED)
- **Where:** the gauges and the `epoch close drained` line are set only at `run_epoch.rs:500-537`.
- **Closes not measured:**
  - the replay-and-close path (`run_epoch.rs:244-254`): a member restarted mid-drain whose replay crosses the boundary;
  - the leftover-drain path (`run_epoch.rs:701-711`): a demoted member whose leftover drain reaches the boundary.
- On those closes the gauges keep the previous close's values, or are absent after a restart.
- The contract documents this ("per live boundary close"). When reading run-1 data: if a node has no drained line at a close, it closed through one of those paths; the close itself was not missed.
- `track_while` is not needed on those paths. No epoch network task runs during the replay close, and the leftover drain runs after the abort.
- No action. For upstream, those paths could log a one-line close.

### Known residuals, checked and not re-reported
- **D42** (the halt does not survive a restart). Not worse than stated. After the halt, the restarted node runs `run_epoch(N+1)`. There `recover_previous_epoch_record` finds record N present (`close_epoch.rs:633-657`), clears the stale epoch tables and enters N+1 on its own state. That is the same shape as the existing `exit_after_epoch_record` recovery. A divergence then surfaces at the next vote's fork check, as on bench 5.
- **D43** (the 200-ms grace does not read the channel). Not worse than stated:
  - `update_tasks` at `run_epoch.rs:619` empties the channel before the grace, so the bound really is 1,000 spawns within 200 ms;
  - `wait_for_task_shutdown` (`:633-637`) runs only after `abort_all_tasks` has stopped the loops that spawn tasks;
  - the last sweep (`:638-644`) aborts whatever they queued before they stopped.

## Answers to the brief's questions

**2a. Does switch off mean before?** The behaviour is unchanged, but the code is not byte-for-byte the same. These lines run with both switches off and did not run before. All are metrics, logs or config reads, and none can change a decision:
- `crates/consensus/primary/src/network/handler.rs:183` resets the entry gauge when a handler is built.
  - `:286` and `:397-403` take a `parking_lot` lock and set the gauge. This happens only for a verified certificate of epoch `exec_epoch+1`, and the lock is never held across an await. `behind_consensus` returns the same result as before.
  - The gauge is also registered as a new `PrimaryMetrics` field.
- `run_epoch.rs:500-509` sets the detection gauges. `TimestampMs::elapsed` saturates (`crates/types/src/primary/mod.rs:282-284`), and so does the backlog subtraction.
- `run_epoch.rs:525-537` sets the drain gauge and logs `epoch close drained` at info.
- `run_epoch.rs:517-586`: the close, the record and the export moved into one async block, awaited at `:585`. The order, the `?` exits and the test-hook stops are the same as before.
- `run_epoch.rs:511` and `:617` read the switch from config.
- `close_epoch.rs:422` and `:431` call the check, which returns `Ok` at once when the switch is off (`:539-541`).
- `close_epoch.rs:423`, `:432` and `:516` increment the vote-skip counter.
- `task_manager.rs:590-640`: the log levels from F3.

**2b. Mixed fleet.** Neither switch changes any message or shared state that another validator checks: no header, vote, certificate, batch, epoch record or epoch vote.
- `epoch_close_task_drain` changes only which of this node's own tasks are tracked and aborted. The closing epoch's per-message tasks end at the abort sweep instead of at the manager's drop when `run_epoch` returns. Both end them at an await, a few hundred ms apart. The vote collector runs on the node's task manager (`node.rs:1253-1260`) and is not affected.
- `epoch_record_state_check` can only halt this node. It reads a stored record and never writes one.
- So a mixed fleet cannot fork, and honest validators cannot start rejecting each other.
- One interaction to know about: the check turns a divergence from any other cause (for example another topic's switch) into a halt on every member whose closing block differs from the certified record's. Four halted members out of ten stall the fleet until they restart, and per D42 they then carry on. ST-A's mixed fleet had matching final blocks in 3 of 3 runs.

**2c. Liveness under the switches.**
- `track_while` adds no wait. With `biased`, the close future is polled first on every wake-up (`task_manager.rs:468-469`). A task that never ends never blocks the reaping.
- What runs after the select is synchronous (`update_tasks`) or an abort call.
- The 200-ms grace was already always spent in full, because `primary network events` does not watch the consensus shutdown (`crates/consensus/primary/src/network/mod.rs:2465-2478`). The close takes no longer.
- Nothing that used to make progress is now dropped. Tasks that the sweep now aborts used to end a few hundred ms later, at the manager's drop, through the local shutdown (`task_manager.rs:143-147`, `:190-197`).
- No transaction, batch digest, header, vote or epoch close is newly dropped. The halt stops a node only when its closing block differs from the stored record's (2g-2).

**2d. Byzantine or merely slow peers.**
- One faulty validator cannot trigger the halt. A record of epoch N gets into storage in only two ways:
  - downloaded, with a certificate checked against record N−1's `next_committee` (`crates/storage/src/epoch_records.rs:1210-1229`, through `crates/state-sync/src/epoch.rs:271-279`);
  - as this node's own record, certified by its own collector (`epoch_votes.rs:60`).
  A halt therefore needs at least 2f+1 signers on a different `final_state`.
- A flood of requests during the close costs no more than before. Per-message tasks are now tracked and reaped, so the tracked set is bounded by the tasks running at once. Before, up to 1,000 handles sat in the queue, plus untracked tasks.
- The entry gauge reads only certificates already verified against the committee (`handler.rs:497-503`), so a peer cannot inflate it.

**2e. Restart and epoch boundary.**
- The tracked task set lives for one `run_epoch` and is dropped on return (local shutdown).
- The highest round seen lives in each `RequestHandler`. The gauge resets to 0 on each build: at a new epoch and at a mode-change re-entry.
- The node's close gauges keep their last value for the life of the process and are set only on the live arm (F6).
- The halt does not persist across a restart (D42).
- Across the boundary, the check reads the recent-blocks ring. The ring lives for the whole process, `reset_for_epoch` does not clear it (`consensus_bus.rs:1294-1301`), and `try_restore_state` fills it at startup (`node.rs:1838-1866`).

**2f. Determinism.** Nothing this topic adds feeds consensus-visible data. Wall-clock time appears only in gauges and log fields. The halt is a local comparison of a stored record with the local ring and does not depend on iteration order or thread timing.

**2g-1. Can `track_while` cancel or drop the close future?** No, on every exit:
- The loop exits only at `task_manager.rs:469` (`break output`), when the future completes.
- The intake arm (`:471-478`) and the reaping arm (`:479-496`) contain no break, return or `?`.
- A task's panic is caught by its `JoinHandle` and arrives as an `Err` (`TaskHandle::poll`, `:103-124`).
- A closed channel or an empty task set disables that arm for one pass of the select, without spinning. The future's arm uses the irrefutable `output` pattern, so it is never disabled.
- How each case is handled:
  - a critical task ending Ok is logged at info and reaped;
  - a critical task ending with an error or a panic is logged at warn and reaped;
  - a non-critical panic is reaped without a log line;
  - there is no shutdown arm.
- The `?` at `run_epoch.rs:583` applies only to the finished output.
- The only remaining way to drop the close future is to drop `run_epochs`. That happens in `run`'s select (`node.rs:1476-1487`) on node shutdown, SIGTERM or a node-level critical task ending. It is the same with the switch off, and the test hooks at `run_epoch.rs:546-575` rely on it.
- `track_while_never_cancels_the_future` (`task_manager.rs:1156`) covers a critical task ending Ok, ending with an error and panicking, plus a non-critical panic. The U5 mutant check shows the test fails when a critical Ok stops the draining.

**2g-2. Can a correct node be made to halt by anything but a real divergence?** None found. The check compares against the newest block in the ring (`close_epoch.rs:543-546`). All four callers reach it with that block equal to this node's closing block:
- **Live close** (`run_epoch.rs:560`):
  - the closing output is the last one forwarded (`:862-865`), and `close_epoch` waits for it (`:911`);
  - the engine always builds a block for a closing output (`crates/engine/src/payload_builder.rs:162`, `:183-187`);
  - the ring stores the block and its consensus hash in one push (`crates/consensus/primary/src/recent_blocks.rs:41-60`).
- **Replay-and-close** (`:252`): the replay stops at the closing output (`start_epoch.rs:182`).
- **Leftover drain** (`:709`): it returns at the boundary output (`close_epoch.rs:344-346`, `:374-376`).
- **Recovery at startup** (`close_epoch.rs:707`):
  - it runs only when the record was absent at `:633`, so the stored-record branch is hit only if a certified record lands during that startup window;
  - the ring is checked equal to the last executed output block (`:669-678`). In the only state this path exists for (a node killed at the boundary), that block is the closing block.
  - The one theoretical false halt is record N−1 missing while epoch-N blocks are already executed. `open_epoch_pack`'s invariant rules that state out (`run_epoch.rs:736-743`), and in it the existing code would build a wrong record anyway.

The scope's three cases:
- **A record stored for a different epoch:** records are fetched and validated by epoch number, and the comparison is against this close's block.
- **An empty ring:** cannot occur after the wait, because the push that ends the wait carries a block. If it did occur, the check is skipped: a warning is logged, the counter increments and the node does not halt.
- **A peer's record arriving before this node's closing block is executed:** this cannot cause a halt, because the comparison runs only after `close_epoch`'s wait.

The epoch-0 dummy record is never compared, because `:418` requires a certificate (test `epoch_zero_dummy_record_is_not_compared`, `close_epoch.rs:2095`). Nothing here calls for a security evaluation.

**The e2e test**, read as evidence: it shows the loaded close completes with both switches on and with every switch off, the drained line appears, nothing logs a tracking failure and nothing halts. As the test itself states, it does not show the overflow fixed at four nodes. F1 is the gap it leaves.

## Not examined
- No test or build was run (no cargo).
- The e2e helpers (`Fleet`, `assert_epoch_records_verify`, `scrape_metric_value`) were read only where they are called.
- The ordering of ring pushes under `pipelined_persist` is taken from that topic's review.
- Blocking tasks that may run on the epoch spawner were not listed.
- The outer `run` path was read only around `node.rs:1476-1487`.
