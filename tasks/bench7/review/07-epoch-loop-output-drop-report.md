# R-07 topic review: head 07, `fix/epoch-loop-output-drop` (unit XF-1)

Verdict: **APPROVE WITH FOLLOW-UPS.**
The fix closes the drop on every arm of the real `run_epoch` select, and nothing Low or above survived verification.
Eight Info items follow; none has to be fixed before the benchmark image, and three are worth doing before the upstream PR (findings 1, 2 and 3).

Scope: worktree `/home/drtnarg/coding/telcoin/tn-b7-xf1`, `git diff 14372820d..26c7ed72d` (4e149c9bf the reserve-first forward, 0151e03a8 the drain's continuity check, 26c7ed72d docs and a test).
Line numbers are the tip's unless marked "base".
Date: 2026-11-14.

## How this was reviewed

- Code review (tn-review): my own read of the diff, of the real `run_epoch` select and `finish_epoch`, of every producer into the consensus-output queue (`subscriber.rs:432`, `:915`, `:1438`) and of the engine's intake (`crates/engine/src/lib.rs:282-375`).
- Security evaluation (tn-security-eval): seven read-only agents (model opus), each limited to a named read list: consensus safety, state transitions, DoS, determinism, a Feynman and coupled-state logic audit (the nemesis slot), DREAD, STRIDE.
- Not started, because their question cannot apply: contract safety (no Solidity in the diff), dependency audit (no `Cargo.toml` or `Cargo.lock` change), crypto correctness (no signature, hash or key code changed).
- Verification (the skills' own step): one findings-verifier run (opus) over the three Low findings of the review and the evaluation together (V1 to V3), re-checked by an independent sub-agent that saw only the claims, key questions and files.
  V1 and V2 were confirmed and downgraded to Info; V3 was refuted as a design decision.
  Info items are not verified under the skills' tiering; I checked the ones I cite against the code (and, for findings 1 and 2, against tokio 1.53.1's source) myself.
- No cargo, no edits, no commits.
  The unit's gates (fmt, check, clippy, nextest -p tn-node 239 passed, new tests three times each) and its base reproduction (`[1, 3]` against `[1, 2, 3]`) are cited from `tasks/checkpoint-bench7-XF-1.md`, not re-run; my trace of the base code gives the same `[1, 3]`.

## Findings, most severe first

### 1. Info, CONFIRMED: a permit held across the wait for an output does not see an engine channel that closes meanwhile

- Location: `run_epoch.rs:783-794` (reserve, then `recv().await` while the permit is held), `:756-757` (`permit.send`, then `last_forwarded_consensus_number`), `:836-839` and `:492-502` (boundary output, then `close_epoch`); `crates/consensus/primary/src/consensus_bus.rs:1762-1776` (`wait_for_consensus_execution`, no timeout).
- Scenario: the forward holds a permit and waits for the next output; the engine task ends and drops its receiver; the next output arrives; `Permit::send` drops it without an error (tokio `bounded.rs:1690-1693`: the send "will succeed even if the receiver half has been closed") and `last_forwarded_consensus_number` advances.
  A non-boundary output fails one iteration later at `reserve()` (`:783`).
  A boundary output returns `Ok(target_hash)` and `close_epoch` waits for an execution that never comes.
  Base: `to_engine.send(output).await?` returned `Err` at once.
- Why Info: the receiver lives in the engine for its whole life (`crates/engine/src/lib.rs:93`, `:138`, `:145`); the engine is the critical task "consensus engine" (`crates/node/src/engine/inner.rs:67-92`) on the node task manager, whose `until_exit` notifies shutdown when any critical task ends (`crates/types/src/task_manager.rs:452-511`), so `run`'s outer select (`node.rs:1507-1518`) drops `run_epochs`.
  The wait is bounded, the counter is in memory only and the restart replay forwards from the executed tip; only the exit shape differs.
- Against the scope's residual "`Permit::send` cannot see a channel that closed while the permit was held, as on main": main had the same blindness only for the instant between its send's check and its write; here the permit is held for the whole idle wait between two outputs, so the window is that wait.
- Fix (before the upstream PR): reword `run_epoch.rs:733-735` and `close_epoch.rs:315-318` to "accepted into the engine channel"; optionally restore main's immediate error by checking `to_engine.is_closed()` after taking the output and before `forward_output`, returning the error main returned (the output is in the pack; the replay forwards it again).

### 2. Info, CONFIRMED (tokio source): the live forward's new `try_recv` can park a runtime worker thread

- Location: `run_epoch.rs:788`.
- Scenario: in tokio 1.53.1, `Receiver::try_recv` parks the OS thread when a concurrent send has claimed a slot but not yet written it (`TryPopResult::Busy`, `tokio-1.53.1/src/sync/mpsc/chan.rs:424-469`).
  Base used only `recv().await` on the live path, which returns `Pending` instead; the drain's `try_recv` runs after the subscriber is aborted, so it never meets a concurrent send.
  Now the live loop calls `try_recv` while the subscriber sends on another worker; if the OS deschedules the subscriber's thread mid-send, the epoch manager's worker thread is blocked for that time.
  The wait is normally a few instructions; the yield budget is still spent by `reserve()` (`batch_semaphore.rs:594-598`), so a run of ready outputs still yields.
- Fix (before the upstream PR, cheap): take the queued output with `consensus_output.recv().now_or_never()` (or `poll_recv` with a no-op context) instead of `try_recv`; both return without parking and keep the same stamp logic.

### 3. Info, CONFIRMED: the stale skip logs no digest, epoch or path, and has no counter

- Location: `close_epoch.rs:339-347` (new), `run_epoch.rs:802-810` (same text, already on base at `14372820d:run_epoch.rs:757-764`).
- Scenario: none on an honest path.
  A queued output at or below `last_forwarded_consensus_number` is identical to the one already forwarded: every queued output is saved first (`subscriber.rs:403-432`, `:874-915`, `:1426-1438`) and the pack refuses a number at or below its latest (`crates/storage/src/consensus.rs:1442-1447`).
  The gap is only that an operator cannot tell from the log which path skipped, or check the digest after a local bug.
- Fix (optional): add `digest = ?output.consensus_header_hash()` and a `path` field to both Stale arms, and a `tn_node.stale_outputs_skipped_total` counter with a static `path` label.

### 4. Info: the gap counter will rarely reach a scrape

- Location: `close_epoch.rs:349`.
- `metrics::counter!("tn_node.leftover_output_gaps_total")` is registered on first use and incremented just before the node stops, so a scrape will probably never see it; the error log line is the real signal.
  Its prefix is `tn_node` while the epoch manager's sibling counters use the `tn_epoch` scope (`crates/node/src/metrics.rs:19-77`), and the live loop's own gap (`run_epoch.rs:811-818`) counts nothing.
  Static name, no labels, nothing sensitive in the error text (two consensus numbers).
- Fix: none needed; if kept, say in the PR that the log line is the signal.

### 5. Info: batch eviction and quota release run one output later under backpressure

- Location: `run_epoch.rs:750-752`, now after `reserve().await` (base: before `send().await`).
- On base the forward took output N, evicted its batches from `NodeBatchesCache` and `OurNodeBatchesCache` and released its `ReportedBatchLedger` quota (`crates/consensus/worker/src/network/ledger.rs:154-160`), then waited for room.
  Now N stays in the queue, its batches cached and counted, until the engine frees a slot.
  Under backpressure that is one more output's worth on top of the backlog already queued; it runs on every node (no switch).
- Fix: none.

### 6. Info: the tests drive the real functions, not the real loop

- Location: `run_epoch.rs:3259-3427`, `close_epoch.rs:3390-3467`.
- The full-channel tests are a faithful worst case for the forward's cancel safety (details under question 7 below).
  `a_mode_change_while_the_forward_waits_for_output_loses_no_output` passes on base too (`recv` was already cancel safe) and would pass with a leaked permit; it guards the permit path, it does not reproduce the bug.
  The node-shutdown test's engine keeps consuming through the drain, which the real engine does not (it stops on node shutdown, `node.rs:930`).
  Not exercised: the `store_failed` arm, the phase-2 backfill after a cancelled forward, and a boundary output among the leftovers (`close_epoch(None)` and `write_epoch_record`, `run_epoch.rs:639-648`).
- Fix: none for the image; for the PR, say what the `for_output` test guards.

### 7. Info: the drain's queue phase still holds an output across an await

- Location: `close_epoch.rs:336-383` with `run_epoch.rs:720`.
- Phase 1 takes an output off the queue, then waits in `reserve().await`.
  Only `run`'s outer select can cancel that (node exit), the output is in the pack already, and the restart replay forwards it; so nothing is lost today.
  The safety rests on `finish_epoch` never being raced against anything inside the epoch loop.
- Fix: one sentence in the drain's doc stating that invariant, so a later change that puts the drain under a select reads it.

### 8. Info, REFUTED as a defect (design decision): the drain stops on a gap that the pack could fill

- Location: `close_epoch.rs:348-363`.
- No honest sequence puts a gap into the queue: the active subscriber awaits `handle_consensus_output` (save, publish, send) inside its select arm's body (`subscriber.rs:975-979`), so its shutdown arm (`:1020`) cannot cut it between save and send; the follower paths call `handle_sync_output` inline (`:513`, `:814`) and have no shutdown drain; only a task abort cancels between save and send, and that also ends `drain_pending_on_shutdown`.
  A saved-but-unqueued output can only be the tail, which phase 2 forwards.
  Backfilling a gap from the pack would hide the regression the stop is there to catch, and the live path already stops on the same rule.
- Fix: none.

## Answers to 2a-2g

### 2a. What changed for every node (no switch)

- The live forward (`run_epoch.rs:776-846`) reserves room, then takes an output (`try_recv`, else `recv().await`), then hands it over through the permit with no await (`forward_output`, `:739-758`).
  Same outputs, same order, same flags as base on every path that does not cancel; differences: no output is held across a cancellable await, eviction and quota release move after the wait for room (finding 5), the `forwarded_at` stamp is the start of the wait for room (observability only), the closed-channel case of finding 1, and the `try_recv` of finding 2.
- `process_output` (`:713-723`) is `reserve()` plus `forward_output`; the replay and the drain behave as with base's `send().await`.
- The drain's queue phase (`close_epoch.rs:336-365`) skips a stale output, which base forwarded again and the engine would have executed twice (its intake checks neither number nor parent, `crates/engine/src/lib.rs:325-350`), and returns an error on a gap, which base forwarded past; `finish_epoch` propagates it (`run_epoch.rs:640`).
- New observable lines: warn `skipping already-forwarded consensus output` (target `epoch-manager`, fields `number`, `last_forwarded`) in the drain; error `leftover consensus output does not follow the last output forwarded to the engine: stopping the node before the engine executes past the gap`; error text `leftover consensus output gap: expected {} but received {} - stopping the node; a restart replays the missing output from the consensus DB`; counter `tn_node.leftover_output_gaps_total`.
- Nothing consensus-visible changed.

### 2b. Mixed fleet

The change sits between a node's epoch manager and its own engine.
It changes no header, vote, certificate, batch, consensus output or pack that another validator checks, so fixed and unfixed nodes cannot reject each other or fork because of it.
The only cross-node effect is the bug itself: an unfixed node can still fork its own execution under the race; a fixed node cannot.

### 2c. Liveness

The fix removes a loss: an output taken off the queue now always reaches the engine channel or the node stops.
The new stop on a gap has no honest trigger (finding 8 and question 4).
The stale skip drops nothing the engine did not already receive, except in finding 1's dead-engine case, where the node is stopping anyway.
Every exit still pre-empts a full channel (question 3).

### 2d. Byzantine or slow peers

Before the fix, a transaction flood that made execution the bottleneck, plus a demotion or a closing record or an operator restart, could silently fork a lagging node's execution (DREAD 4.6, Medium).
After it, no window remains (DREAD 1.8).
A peer cannot put a gap or a stale number into the queue: it is node-local, and sync outputs pass the subscriber's own continuity check (`subscriber.rs:384-397`) and the pack's monotonic save before they are queued.
No new cost a peer can impose.

### 2e. Restart and epoch boundary

New in-memory state: only the permit, dropped with the forward future when the select resolves (before any arm handler and before `finish_epoch`).
`last_forwarded_consensus_number` is unchanged in kind: primed at startup from the pack's anchor (`node.rs:870-897`), moved only by `forward_output`, carried across epochs.
On the drain's gap stop, `finish_epoch` has sealed the certificate pack and persisted the consensus pack (`run_epoch.rs:623-629`) but not cleared tables or run `ensure_stores_durable` (`:654-661`); the restart replays from the executed tip with its contiguity check (`start_epoch.rs:143-199`) and needs no manual step.
Across an epoch boundary nothing changes: the boundary arm hands the closing output over before it returns, and `finish_epoch` clears the queue as on base (`run_epoch.rs:637`).

### 2f. Determinism

`Instant` feeds only the stamp, which is never serialized or hashed (`crates/types/src/primary/output.rs:97-121`, digest at `:143-145`; the engine reads it only for a metric, `crates/engine/src/lib.rs:454-455`).
No map iteration, no `SystemTime`, no randomness.
Which select arm wins no longer changes the sequence the engine executes; on base it could, and that was the bug.

### 2g. The topic's own questions

1. Every arm of the real select (`run_epoch.rs:484-563`, unbiased):
   `node_ended` (`:485`), `closed_by_record` (`:549`) and `until_task_ends` returning Ok on a demotion or rejoin (`:560`) can win while the forward pends at `reserve()` (`:783`) or `recv()` (`:790`); both are cancel safe, the forward holds at most a permit, released on drop, and the queued outputs go through the drain in order.
   `store_failed` (`:490`) and `until_task_ends` returning Err stop the node; the restart replays.
   The boundary arm (`:492`) is the forward itself; the closing output is flagged, stashed and handed over synchronously (`:831-839`).
   No other await sits between taking an output and the engine channel holding it on the live path (`:788-842`).
   The replay (`start_epoch.rs:175-188`) and both drain phases hold their output across `reserve().await`, but read it from the pack (replay, phase 2) or had it saved before it was queued (phase 1), and only the outer `run` select can cancel them (finding 7).
2. No reorder (one producer into `to_engine`, created once at `node.rs:902` and never cloned; one consumer of the FIFO queue), no double forward (the counter moves with each send, `:757`; stale is skipped on both paths; phase 2 starts at `last_forwarded + 1`, `close_epoch.rs:391-393`), no loss: an output that arrives while a permit is held stays queued if another arm wins (tokio removes it only on `Ready`), `try_recv` failing falls through to `recv`, and a disconnected queue ends the loop with base's error.
   Outputs left queued after a boundary are discarded as on base (`run_epoch.rs:637`, and `subscribe_fresh` on the next entry).
3. The held slot blocks nobody: the epoch manager is the channel's only sender, the engine reads regardless of permits (`crates/engine/src/lib.rs:326`, gated only by its own `MAX_QUEUED_OUTPUTS`), and the permit is gone before the close or the drain runs.
   With the channel full, every other arm still pre-empts, since the forward is pending.
   The only new unbounded wait is finding 1's, ended by the outer select.
4. The continuity stop has no honest trigger; four agents and the verifier traced restart, mode change, replay, followers, rejoin leftovers and the first output of an epoch to the same anchor.
   Startup primes the counter from the pack's anchor; a restart or new epoch replays up to the pack's latest before subscribing (`run_epoch.rs:241-269`); the active subscriber numbers from the same anchor and followers from the pack's latest (`subscriber.rs:384`, `:1472`); after a mode change the previous drain's phase 2 brought the counter to the pack's latest; all producers save then send, in order.
   The rule is the live path's (`run_epoch.rs:801-819`), so the drain stops only where the live forward would have stopped on its next output.
   One pre-existing case: a pack read failing in phase 2 (`close_epoch.rs:414-417`) leaves the counter short, and the next run stops on a gap, as base's live check already did.
   Skipping a stale output is always right: base's re-forward would execute it twice, and nothing relied on it.
   The one behaviour change, a stale boundary output ending the epoch as a mode change instead of a new epoch, is unreachable, because every forwarded boundary goes straight to a close.
5. A peer can cause neither a gap nor a wrong skip (2d).
   A slow peer or a flood can still fill the engine channel; that now costs only backpressure.
6. No record path changed: the hunks are the imports, the drain, `finish_epoch`'s call and doc, the forward functions, `OutputContinuity`'s visibility and tests; `close_epoch`, `write_epoch_record`, `recover_previous_epoch_record` and topic 03's closing-block check (in the base as 0f7917f29) are untouched, and the boundary stash sites are unchanged (`run_epoch.rs:836`, `close_epoch.rs:368`, `:398`).
   The stop's error text and counter carry static text and two numbers, no labels.
7. The tests run the real `wait_for_epoch_boundary` and the real drain in a `biased` select with the forward polled first; that makes the dangerous interleaving deterministic, and the real unbiased select reaches either it or a safer one, so as a test of the forward's cancel safety it is faithful.
   It skips what the real loop does between the select and the drain: `consensus_shutdown.notify()` (`run_epoch.rs:567`), the 200 ms grace (`:571`, `EPOCH_TASK_EXIT_GRACE` at `:55`) in which the subscriber's shutdown drain can queue more outputs (in order), the abort and 500 ms join whose timeout skips the drain (`:572-580`), and the seal and persist (`:623-629`).
   A test of the real loop needs `run_epoch`'s unbiased select, a queue from `subscribe_consensus_output`, a producer that saves then queues (with a shutdown drain blocked on a full queue, then aborted), an engine that can be held so `to_engine` stays full, the real `finish_epoch`, and many iterations or a seeded runtime; it should assert contiguous numbers ending at the pack's latest and at the counter, and a close when the boundary is among the leftovers.
   The slow-execution e2e test the code mentions (`run_epoch.rs:381-382`, bench F1-3) is the natural home.
   Nothing in the real loop invalidates the fix.

## Residuals from the scope

- The forward-wait stamp is an upper bound for an output that arrives during the wait for room: accepted, not re-reported.
- `Permit::send` cannot see a channel that closed while the permit was held: re-reported as finding 1, because the window is the whole wait between outputs rather than "as on main"; still Info, since the outer select bounds it.
- The engine docs that say "stamped just before its send" (`crates/engine/src/metrics.rs:81-83`, `lib.rs:450-452`): already a recorded follow-up, not re-reported.

## Not examined

- The engine beyond its intake and the lifetime of its receiver; state-sync verification beyond the subscriber's continuity check.
- No e2e and no test was run here (no cargo by rule).
- A node that already executed past a dropped output on an older image: nothing in this diff detects that; a fleet built fresh from this image does not carry such state.
