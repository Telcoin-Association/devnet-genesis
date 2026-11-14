# Sources: bench6-epoch-loop-output-drop.md (not for posting)

Slug `epoch-loop-output-drop`. Written 2026-11-14 (UTC). Title 108 characters. Body 799 words by `tail -n +2 | wc -w` (819 with the H1).

## Code claims, each read with `git -C /home/drtnarg/coding/telcoin/telcoin-network-b7 show 45dce8947:<path>`

- `run_epoch.rs:749` `while let Some(mut output) = consensus_output.recv().await` (crates/node/src/manager/node/run_epoch.rs).
- `:730` `to_engine.send(output).await?;` inside `process_output` (713-734); `:732` sets `last_forwarded_consensus_number` after it; called from `:793` and `:797`.
- `node.rs:91` `const TO_ENGINE_CAPACITY: usize = 64;` (doc 85-90: in-flight capped at roughly `TO_ENGINE_CAPACITY + MAX_QUEUED_OUTPUTS`); channel built at `:898`.
- `crates/engine/src/lib.rs:61` `MAX_QUEUED_OUTPUTS = 8`; `:326` intake arm gated on `self.queued.len() < MAX_QUEUED_OUTPUTS`; `:326-341` arrival and `enqueue`, no number or parent check; `enqueue` 247-254; `:169` `let parent = self.parent_header.clone();`.
- `crates/engine/src/payload_builder.rs:86-88` `BuildArguments { reth_env, output, parent_header }`, `canonical_header = parent_header`; `:98` `inc_leader_count`; leader counts are per-epoch reward counts (`crates/types/src/gas_accumulator.rs:136-144`, `get_address_counts` 170-).
- `run_epoch.rs:484` `tokio::select! {` without `biased` (unbiased); arms: `node_ended` 485, `store_failed` 490 (`return Err(err)`, so `finish_epoch` and the drain do not run), boundary 492, `closed_by_record` 549 (warn text 550-556), `until_task_ends` 560 -> `epoch_tasks_ended` 1209-1226 (Ok logs "epoch task manager exited - likely syncing with committee" at 1215).
- `crates/types/src/task_manager.rs:396` `until_task_ends` resolves once shutdown is notified.
- Demotion: `crates/consensus/primary/src/network/handler.rs:290` `behind_consensus`, `:444` CvvInactive, `:455` `self.consensus_config.shutdown().notify()`.
- Rejoin: `crates/consensus/executor/src/subscriber.rs:784-792` `promote`, notify at `:791`.
- `closed_by_record`: `certified_record_closed_epoch` 1287-1310; `certified_record_closes_running_epoch` 1264-1270 (CvvActive and record.epoch > running).
- Subscriber saves before it queues: `subscriber.rs:868` `handle_consensus_output`, `save_consensus` at 874-875, `consensus_output().send(output).await` at 915 (active path, cited). The catch-up/follow path does the same: `save_consensus` at 403, send at 432 (not cited, same claim).
- Final re-check (S3, 2026-11-14 19:03 UTC): every `path:line` in the posted text printed from 45dce8947 and matched; body 799 words (`tail -n +2 | wc -w`), 819 with the H1; title 108 characters; no em dash; hygiene grep clean.
- `finish_epoch` 610; drain call 637-638; `ModeChange` 649.
- `crates/node/src/manager/node/close_epoch.rs:314` drain; Phase 1 319-338 (try_recv, `process_output`, no continuity check); Phase 2 340-375 (`latest_db` 345, `last_sent` 346, `if` 347, loop 348).
- `run_epoch.rs:756` `check_output_continuity` on the live path; comment 750-755 ("The `consensus_output` queue never drops an output" at 753-754); `check_output_continuity` 1096, doc 1093-1095 says live path only.
- `run_epoch.rs:85-88` `replay_consensus` false for ModeChange (used at 241).
- `close_epoch.rs:424-435` stored-record lookup and `check_stored_record` call; `check_stored_record` 712-749 (counter 734, error text 743-744, `Err(mismatch.into())` 746). Metric `tn_epoch` scope (`crates/node/src/metrics.rs:14`, field `:24`), exported as `tn_epoch_final_state_mismatches_total` (`crates/tn-reth/README.md:976`).
- `crates/telcoin-network-cli/README.md:487-489` `db reset-execution --force`; command `crates/telcoin-network-cli/src/db.rs:122`.
- `crates/tn-reth/README.md:968-977`: the rebuild re-executes the node's own consensus output and checks each epoch against the record it holds, "certified, or its own from before the reset"; on a mismatch it stops.
- `crates/storage/src/epoch_records.rs:641-650`: `save_record` and the certified save refuse a different record for an already-stored epoch (`ConflictingRecord`), so a certified record cannot replace a divergent own one. (Basis for "a divergent record the node saved would stop the rebuild"; inferred from docs and code, not run.)
- `crates/engine/src/metrics.rs:18` scope `tn_engine`, `:85-87` `channel_depth` gauge -> `tn_engine_channel_depth`.
- The code used by the test is unchanged between 45dce8947 and the tree it ran on (14372820d): `git diff 45dce8947 14372820d` has no hunk in run_epoch.rs before line 933 or in close_epoch.rs between 30 and 398, so `wait_for_epoch_boundary`, `process_output`, the `select!`, `finish_epoch` and the drain are main's.

## Not traced (said so in the text)

- The catch-up path from the ModeChange re-entry to the next close; whether the record is stored at that close; what the node votes on meanwhile.
- reset-execution not tried on this case.

## Test

- Name: `manager::node::run_epoch::tests::a_mode_change_while_the_engine_is_full_loses_no_output`, on branch `b7/xf1` (`/home/drtnarg/coding/telcoin/tn-b7-xf1`, run_epoch.rs:3339-3351; helper `exit_while_the_forward_waits` 3280-3333: one-slot channel, outputs 1-3 saved to the pack, `biased` select with the forward first).
- Failure on the base code: `benchmark/work/bench7-scratch/XF-1/phaseA-base-fail.log` lines 21-24 (`left: [1, 3]`, `right: [1, 2, 3]`), line 59 `EXIT=100`.
- Pass with the fix: `tasks/checkpoint-bench7-XF-1.md` line 15 (nextest -p tn-node EXIT=0, 239 passed, 1 skipped; new tests x3, 6/6).
- Fix commits: 4e149c9bf (reserve before recv), 0151e03a8 (Phase 1 continuity: Stale skip, Gap -> `metrics::counter!("tn_node.leftover_output_gaps_total")`, error "leftover consensus output does not follow the last output forwarded to the engine: stopping the node before the engine executes past the gap"), 26c7ed72d (the wait-for-output test). Exported name `tn_node_leftover_output_gaps_total` by the same dot-to-underscore export as the `tn_epoch` counter.

## Benchmark figures

Run r20261113-1630, `benchmark/results/r20261113-1630/`:

- "four times": `zcat logs/bench-validator-05-unit-stdout.log.gz | grep -c "epoch task manager exited - likely syncing with committee"` = 4 (lines 2241179 at 18:02:42.806, 2241809 at 18:02:45.805, 2241941 at 18:02:46.503, 3215781 at 18:42:49.996). Every other node of the run: 0.
- "demoted an epoch behind": lines 2241144 (18:02:42.684) and 2241811 (18:02:45.848) "we are behind, go to catchup mode!" `epoch=4 exec_epoch=3 ... reason=epoch_behind`.
- "twice rejoining": "attempting to rejoin consensus" at 18:02:45.805 and 18:02:46.503; at 18:42:49.996 the fourth.
- "under load": manifest.json `phases` mixed 17:55:32Z-18:36:19Z.
- "killed and restarted": manifest.json `chaos[0]` `docker kill -s KILL telcoin` at 18:21:20Z on bench-validator-05; restart at planned_unix 1794594380 = 18:26:20Z (chaos-remote.log lines 7-9, state `active`).
- "at most 21 outputs behind": demotion lines `backlog_outputs=0` (18:02:42) and `backlog_outputs=21` (18:02:45); rejoin lines `newest_number - exec_number` = 6217-6196 = 21 (18:02:45), 6217-6197 = 20 (18:02:46), 9270-9260 = 10 (18:42:49). Inference: outputs between the engine and the subscriber cannot exceed newest - executed, so fewer than 64 in `to_engine`. Gauge not read.
- "No node in bench 6's four runs logged a final-state mismatch or a consensus output gap": `grep -c -e "final_state does not match" -e "consensus output gap"` over every `logs/*unit-stdout.log.gz`, `*unit-stderr.log.gz`, `*-telcoin-pre-*.log.gz`, `*-telcoin-cert-fail-*.log.gz` of r20261113-1351, r20261113-1630, r20261113-2118, r20261114-0000: 0 in each run.
- Not cited: the mode-change line also appears in r20261113-1351 (validator-05, 1), r20261113-2118 (validator-05, 1), r20261114-0000 (validator-02, 2; validator-05, 1).

## Issues read (gh, read-only)

- #1575 (merged PR, grantkee, 2026-10-07): "Notes for review" bullet "Pre-existing and left alone: if `wait_for_epoch_boundary` is cancelled while `to_engine.send` holds an output, Phase 1 of the leftover drain forwards the following outputs with no continuity check and Phase 2 never backfills the dropped one. ... Separate issue to follow."
- #1618 (open): subscriber drops unsaved outputs at teardown when the queue is full; keeps `send().await` / stops at first failure because "a try_send that skipped k and sent k+1 would ... let Phase 1 forward k+1 and move last_forwarded_consensus_number past k".
- #1562 (closed 2026-10-07 by #1575): broadcast `consensus_output` lossy; lag tripped `consensus output gap`.
- `gh search issues` for this case: none.

## How it was found

`tasks/bench7/review/03-closing-block-check-report.md` finding 1 (High, not in that diff); reproduced by unit XF-1 (`tasks/checkpoint-bench7-XF-1.md`).
Public text says only "found while reviewing a change to the epoch-close path".

## Added after the figure-check

The four bench 6 runs ran image 2df831e3c, whose mismatch line is "stored epoch record's final state is not this node's closing block; halting" (main's line differs). The zero counts in the text were re-derived with the image's line, main's line and `consensus output gap` over every `logs/*.log.gz` of the four runs: 0 each (figure-check file beside this note).
