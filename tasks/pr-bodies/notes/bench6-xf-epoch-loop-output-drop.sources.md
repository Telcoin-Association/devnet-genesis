# Sources: PR text `bench6-xf-epoch-loop-output-drop.md` (head `fix/epoch-loop-output-drop`, a2c4dfae9)

Not for posting.
Repo reads with `git -C /home/drtnarg/coding/telcoin/telcoin-network`; head files exported to the unit's scratch (`run_epoch.rs`, `close_epoch.rs`, `start_epoch.rs`, `node.rs` at a2c4dfae9).

## Stack paragraph

- prev d7daa9aa1 (`fix/epoch-record-collector-hardening`), head a2c4dfae9, 8 commits: `git log --reverse --format='%h %s' d7daa9aa1..a2c4dfae9`; full shas d7daa9aa1d… and a2c4dfae93d387154e8873ef6005b371a4fe5635 (from `git show`); prev full sha from `git rev-parse d7daa9aa1` (in the text).
- Dependency sentence: every symbol and fixture the eight commits use exists on main 45dce8947: `git grep -c` for `manager_with_engine_and_floor`, `fn manager_with_engine`, `certified_record_closed_epoch`, `fn epoch_tasks_ended`, `EPOCH_TASK_MANAGER`, `fn check_output_continuity`, `metrics_util` (all > 0 at 45dce8947).
  `LineCapture` is added by 95705aab3 (ledger `tasks/bench7-cherrypick-ledger.md` line 82: it was defined by head 06's orphan counters on the integration branch; the head did not compile alone, CHECK EXIT=101 at 835dfe4e7; fix = own commit here).
  Textual check: `git diff d7daa9aa1 a2c4dfae9` applied to main's two files with `patch -p1 --dry-run -F3`: every hunk applies; fuzz at close_epoch.rs hunk 1 (import block: head 03 added `metrics::EpochMetrics` to the `use crate::{…}` line) and the test-module ends (close_epoch.rs hunk 6, run_epoch.rs hunk 10). `git apply --check` (no fuzz) fails on those. Not built on main alone.

## Problem

- main lines: `git show 45dce8947:crates/node/src/manager/node/run_epoch.rs` :749 `while let Some(mut output) = consensus_output.recv().await`, :730 `to_engine.send(output).await?`; close_epoch.rs :320 `while let Ok(output) = consensus_output.try_recv()` (Phase 1, no continuity check). Same lines as the issue cites.
- "[1, 3] instead of [1, 2, 3]": `tasks/checkpoint-bench7-XF-1.md` A2 (EXIT=100 on base 14372820d, whose code in question equals main's: A1 "lines unchanged from 45dce8947"); issue #1860 Evidence section says the same.
- Trigger in r20261113-1630: issue #1860 Evidence (one validator logged the mode-change line four times); XF-1 notes. Not repeated as a figure in the PR text.
- "no node in bench 6's four runs logged a final-state mismatch or a consensus output gap": issue #1860 Evidence; referred to, not repeated.
- Engine checks neither number nor parent; ModeChange re-entry does not replay: issue #1860 "What happens" (main `crates/engine/src/lib.rs:326-341`, run_epoch.rs:85-88); the eight commits do not touch `crates/engine` (diffstat: only close_epoch.rs and run_epoch.rs).
- Already-diverged node not detected: review report "Not examined", last bullet.

## Change (per commit, from `git show`)

- 1c2af644f: `process_output` = `reserve().await` + `forward_output(permit, output, forwarded_at)`; live loop reserve → take → `forward_output`; three tests (mode change, node shutdown, closing record).
- 19239c515: Phase 1 `check_output_continuity`; Stale → warn + continue; Gap → counter `tn_node.leftover_output_gaps_total`, error line, `return Err(eyre!(…))`; return type `eyre::Result<Option<ConsensusHeaderDigest>>`; engine-gone still `Ok(None)`; `finish_epoch` uses `?`; doc of `check_output_continuity` (replay unchecked, phase 2 from last_forwarded + 1). Tests `the_leftover_drain_stops_on_a_gap_before_the_engine_gets_past_it`, `the_leftover_drain_skips_an_output_already_forwarded`.
- e247d3130: test `a_mode_change_while_the_forward_waits_for_output_loses_no_output`; review report finding 6: passes on base too, guards the permit path.
- a876f66e6: `recv().now_or_never().flatten()`; commit body: tokio 1.53 `try_recv` parks the OS thread on a claimed-but-unwritten slot; review finding 2 (tokio-1.53.1 chan.rs:424-469). Tests `the_forward_takes_an_output_queued_during_its_wait_for_room`, `the_forward_stamps_a_late_output_on_arrival`, `the_forward_drains_a_closed_queue_then_ends`.
- caba85bf3: `if to_engine.is_closed() { return Err(mpsc::error::SendError(()).into()); }` (head run_epoch.rs:823); review finding 1; test `the_forward_fails_on_an_engine_gone_while_it_waits`.
- 95705aab3: `LineCapture` + `FieldCapture`, test-only, close_epoch.rs tests; ledger line 82 for the reason (later head 06 uses it).
- ab980e106: fields `digest = ?output.consensus_header_hash()`, `path = "leftover_queue"` (close_epoch.rs:360) / `path="live"` (run_epoch.rs:839); counter `tn_node.leftover_outputs_skipped_total` (close_epoch.rs:354), drain only; review finding 3. Test `the_leftover_drain_logs_and_counts_an_output_it_skips`.
- a2c4dfae9: docs only; review findings 5 and 7.

## What changes for every node

- Review report 2a (lines 96-103) and 2b (105-109), checked against the head code above.
- Names: `tasks/bench7-contract.md` sections 2.5 (lines 87-92), 3.5 (167-171), fatal list (line 200). Prometheus forms `tn_node_leftover_output_gaps_total`, `tn_node_leftover_outputs_skipped_total` (contract 3.5).
- Error line verbatim: head close_epoch.rs:371-372; returned error: :375-377.

## What a reviewer will ask first

- Honest path: review report finding 8 (lines 86-92) and 2g question 4 (lines 151-156); what it rests on: counter primed from the pack's anchor (node.rs:889-897 at head), producers save then send in order, sync outputs pass the subscriber's continuity check (review 2d), live forward cancel safe; pre-existing phase-2 read failure case (2g q4, line 154).
- Clean shutdown: `tasks/checkpoint-bench7-orch.md` line 538-539 (XF-1b record: "a clean shutdown can reach the error line in one narrow race that main already has (could be silenced with a biased select or by treating SendError during shutdown as a normal exit)"); XF-1b checkpoint "nit 1 (shutdown race, as on base)"; brief `tasks/bench7/briefs/xf1b.md` line 22 (the question). Code: engine started with `self.node_shutdown.subscribe()` (head node.rs:928-930); forward Err logged `failed to reach epoch boundary` (run_epoch.rs:494); drain engine-gone logged `error sending leftover consensus output to engine` (close_epoch.rs:394, :424); main: `to_engine.send(output).await?` (45dce8947 run_epoch.rs:730) fails on a closed channel the same way.
- Operator: restart replay at head start_epoch.rs:130-199: from `last_executed_consensus_block` (:136), `get_missing_consensus` (:143), contiguity `ensure!` (:170), `get_consensus_output_current`, `process_output`; pack persisted before the drain (`finish_epoch`, run_epoch.rs:627); review 2e (line 129): "needs no manual step". Gap counter rarely scraped: review finding 4.

## Testing

- Head gate log `/home/drtnarg/coding/telcoin/tn-b7-gate/target/tmp/headXF-a2c4dfae9.log`: line 2 `cargo check --locked --all-targets -p tn-node`, line 7 `CHECK EXIT=0`; line 8 `cargo nextest run --locked --no-fail-fast -p tn-node`, line 294 `276 tests run: 276 passed, 1 skipped`, line 295 `TEST EXIT=0`; line 296 `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-node -- -D warnings`, line 1027 `CLIPPY EXIT=0`. Also orch checkpoint line 720.
- The 11 topic tests PASS in that log (grep of the names).
- "each new test three times": XF-1 checkpoint (new tests x3 EXIT=0 each) and XF-1b checkpoint S6 (new tests x3 EXIT=0 each), on the unit branches.
- Not run: e2e of the race (review finding 6, 2g q7); fleet: none ran this head before the text was written (bench 7 fleet runs not launched; MEMORY / orch checkpoint) — time-sensitive.

## Limits

- Review findings 4, 6, 7; 2g q7 (what a real-loop test needs); XF-1b's two open items (orch checkpoint lines 538-539); engine doc `crates/engine/src/metrics.rs:81-82` at a2c4dfae9 ("stamped just before its send"), XF-1 notes follow-up.

## Related

- #1575: `gh pr view 1575` "fix(primary): backpressure consensus_output with a bounded que channel", MERGED; issue #1860 Related says its notes for review named this case.
- #1618: `gh issue view 1618`, OPEN, "Subscriber drops unsaved outputs at teardown when the consensus_output queue is full".
- Fixes #1860: both items of the issue's "What a fix could look like" are in 1c2af644f and 19239c515; its "How to verify" test passes (gate log); the fleet signals it names are the lines and counter added.
