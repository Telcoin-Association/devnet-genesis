# Figure-check: bench6-epoch-loop-output-drop.md (not for posting)

Checked 2026-11-14 against: upstream main 45dce89474e1efc7f90c6fbd1e51332cc237ab9b (read with `git show 45dce8947:<path>`), fix commits 4e149c9bf, 0151e03a8, 26c7ed72d, the XF-1 checkpoint, the four runs' logs and manifests, and GitHub read-only.

## Verdict

FIX

## Errors

1. Section "What happens", line 18, the phrase "The only continuity check is the live path's (`run_epoch.rs:756`)".
   The text says the live path's check is the only continuity check.
   The source has two more at 45dce8947: the restart replay requires each output to follow the executed one by number and parent hash (`crates/node/src/manager/node/start_epoch.rs:166-174`, "restart replay is not contiguous"), and the subscriber's sync path refuses a gap before it saves (`crates/consensus/executor/src/subscriber.rs:384-397`, `SyncContinuity::Gap`).
   Neither catches this case (the replay is skipped on `ModeChange`, `run_epoch.rs:85-88`, and starts after the executed tip; the subscriber check sits before the queue), so the argument stands, but a reader who opens `start_epoch.rs` sees the "only" is wrong.
   Replacement for the whole line 18: "The live path's continuity check (`run_epoch.rs:756`) assumes, in its comment, that the queue "never drops an output" (`:750-755`): the queue does not, the cancelled send does."

## Code references (each opened at 45dce8947, range plus ten lines either side)

All match; none is off by any line.
- `run_epoch.rs:749` `while let Some(mut output) = consensus_output.recv().await`: matches.
- `:730` `to_engine.send(output).await?;` inside `process_output` (713-734): matches.
- `node.rs:91` `const TO_ENGINE_CAPACITY: usize = 64;`: matches (channel built at :898).
- `crates/engine/src/lib.rs:61` `MAX_QUEUED_OUTPUTS: usize = 8`: matches; `:326` intake arm gated on `self.queued.len() < MAX_QUEUED_OUTPUTS`: matches.
- "about 72 outputs behind": 64 + 8 = 72, plus one executing; the node.rs doc (:86-87) says "roughly `TO_ENGINE_CAPACITY + MAX_QUEUED_OUTPUTS`". Matches with "about".
- `run_epoch.rs:484` `tokio::select! {` with no `biased`: matches.
- `:560` `until_task_ends(consensus_shutdown_clone)` then `epoch_tasks_ended` (Ok logs the mode-change line at :1215): matches.
- `handler.rs:455` `self.consensus_config.shutdown().notify()` after the demotion (:444): matches; `subscriber.rs:791` `self.config.shutdown().notify()` in `promote`: matches; `consensus_shutdown` is `primary.shutdown_signal()` = `consensus_config.shutdown()` (`crates/node/src/primary.rs:156-157`), so both reach `:560`.
- `:549` `record = closed_by_record`, fed by `certified_record_closes_running_epoch` (CvvActive and `record.epoch > running_epoch`, :1264-1270): matches "a certified record of a later epoch".
- `:485` `node_ended`: matches.
- `:490` `err = store_failed => return Err(err)`, so no drain: matches "stops the node instead".
- `subscriber.rs:874-875` `save_consensus(...)`, `:915` `consensus_output().send(output).await`: matches (the sync path does the same at :403 and :432).
- `run_epoch.rs:732` sets `last_forwarded_consensus_number` after the send: matches.
- `run_epoch.rs:637-638` drain call in `finish_epoch`, reached when `epoch_boundary_reached` is false: matches.
- `close_epoch.rs:319-338` Phase 1, `try_recv` then `process_output`, no continuity check: matches; `process_output` moves `last_forwarded_consensus_number` (run_epoch.rs:732).
- `close_epoch.rs:345-348` `latest_db`, `last_sent`, `if latest_db > last_sent`, `for number in (last_sent + 1)..=latest_db`: matches.
- `run_epoch.rs:756` `check_output_continuity` on the live path: matches; `:750-755` comment, "The `consensus_output` queue never drops an output" at :753-754: matches.
- `lib.rs:326-341` arrival and `enqueue`, no number or parent check: matches; `:169` `let parent = self.parent_header.clone();`: matches; `payload_builder.rs:86-88` `BuildArguments { reth_env, output, parent_header }`, `canonical_header = parent_header`: matches. The only use of `output.parent_hash()` in the engine is a span field (`payload_builder.rs:113`).
- `run_epoch.rs:649` `RunEpochMode::ModeChange`: matches; `:85-88` `replay_consensus` is false for `ModeChange`: matches.
- `payload_builder.rs:98` `rewards_counter().inc_leader_count(...)`; `RewardsCounter` counts leaders "during an epoch for reward distribution" (`crates/types/src/gas_accumulator.rs:131-143`): matches.
- `close_epoch.rs:424-435` stored-record lookup and `check_stored_record` call: matches; `:712-749` `check_stored_record`, counter at :734, error text at :743-744 ("stored epoch record final_state does not match this node's closing block: ... stopping the node"), `Err` at :746: matches.
- `tn_epoch_final_state_mismatches_total`: scope `tn_epoch` (`crates/node/src/metrics.rs:14`), field :24, rendered so in `crates/tn-reth/README.md:976`: matches.
- If none is stored, `build_epoch_record` (:505), `save_record` (:514), `epoch_record_watch().send_replace` (:519): matches "builds, saves and publishes".
- `crates/telcoin-network-cli/README.md:487-489` `telcoin-network db reset-execution --force`: matches.
- `crates/tn-reth/README.md:968-977`: re-executes its own consensus output, checks each epoch against the record it holds, "certified, or its own from before the reset", stops on a mismatch: matches; a certified record cannot replace a different stored one (`crates/storage/src/epoch_records.rs:641-649`, `ConflictingRecord`).
- `run_epoch.rs:550-556` the closed-epoch warning: matches.
- `tn_engine_channel_depth`: scope `tn_engine` (`crates/engine/src/metrics.rs:18`), gauge :87, refreshed at each execution completion (`lib.rs:372-374`), so it can read 64: matches.
- "X is never forwarded": the drain skips it (above), `ModeChange` does not replay, and a later replay starts at the executed tip (`start_epoch.rs:135-151`), which is past X: supported.

## Test and fix

- Test `a_mode_change_while_the_engine_is_full_loses_no_output` (added in 4e149c9bf; at 26c7ed72d `run_epoch.rs:3339`): outputs 1 to 3 saved to the pack, 1 forwarded into `mpsc::channel(1)`, 2 and 3 queued; `tokio::select! { biased; wait_for_epoch_boundary ...; exit }`, the exit being `until_task_ends` on a notified shutdown then `epoch_tasks_ended` Ok; then the real `send_leftover_consensus_output_to_engine`; asserts `[1, 2, 3]`. Matches the text.
- `[1, 3]` on main's code: XF-1 checkpoint, A2 ("engine received [1, 3], expected [1, 2, 3]", EXIT=100). The run was on 14372820d; `git diff 45dce8947 14372820d` touches run_epoch.rs only from line 933 and close_epoch.rs only in imports and from line 398, engine lib.rs and node.rs:91 not at all, so the tested code is main's. Matches.
- Passes with the fix: XF-1 checkpoint final gates on 26c7ed72d (new tests x3 EXIT=0, nextest -p tn-node 239 passed). Matches.
- Part 1 (4e149c9bf): `to_engine.reserve().await?`, then `try_recv` or `recv().await`, then `forward_output(permit, ...)`, which sends through the permit and does not await. Matches.
- Part 2 (0151e03a8): Phase 1 applies `check_output_continuity`; `Stale` is skipped with a warning; `Gap` runs `metrics::counter!("tn_node.leftover_output_gaps_total")`, logs an error and returns `Err`, which `finish_epoch` propagates (`?` at run_epoch.rs:639 at 0151e03a8, :640 at 26c7ed72d). Matches.
- Metric name: dotted `counter!` names are rendered with an underscore: `tn_epoch.runs_total` (`crates/node/src/metrics.rs:38`) is documented as `tn_epoch_runs_total` (`docs/src/getting-started/observability-listeners.md:117`), and `tn_epoch.final_state_mismatches_total` (metrics.rs:89) as `tn_epoch_final_state_mismatches_total` (tn-reth README:976). So `tn_node_leftover_output_gaps_total` matches.
- "with no switch": neither fix diff adds a parameter or switch. Matches.
- "the restart replays the missing output from the pack": replay starts after the executed tip (start_epoch.rs:135-151), which is X-1 when the drain stops at the gap. Matches.

## Run claims

- r20261113-1630, validator-05's `*-unit-stdout.log.gz`: `epoch task manager exited - likely syncing with committee` 4 times, at 18:02:42.806, 18:02:45.805, 18:02:46.503 and 18:42:49.996 UTC; every other node of the run 0. Matches "one validator", "four times", "three at 18:02", "once at 18:42".
- "demoted an epoch behind": `we are behind, go to catchup mode!` at 18:02:42.684 and 18:02:45.848, `epoch=4 exec_epoch=3 reason=epoch_behind`. Matches.
- "twice rejoining": `attempting to rejoin consensus` at 18:02:45.805 and 18:02:46.503; the 18:42:49.996 exit follows a third. Matches.
- "under load": manifest `phases` mixed 17:55:32Z to 18:36:19Z. Matches.
- "after the run killed and restarted it": manifest `chaos` `docker kill -s KILL telcoin` at 18:21:20Z and `systemctl start telcoin` at 18:26:20Z, both on that validator. Matches.
- "at most 21 outputs behind": demotion `backlog_outputs=0` (18:02:42) and `=21` (18:02:45); rejoins 6217-6196 = 21, 6217-6197 = 20, 9270-9260 = 10. Matches; "not full" is the inference 21 < 64, and the text says the gauge was not read.
- Zero counts: `consensus output gap` 0 in every `logs/*.log.gz` of r20261113-1351, r20261113-1630, r20261113-2118, r20261114-0000. Matches.
- Final-state mismatch: the four runs ran image `node_git_sha` 2df831e3c, not main; its line is `stored epoch record's final state is not this node's closing block; halting` (`close_epoch.rs:572` at 2df831e3c), behind the switch `epoch_record_state_check`, which was true on 11 of 11 nodes in each run's arm (the `false` starts in `node_startup_check` are the pre-arm starts). Re-grepped every `logs/*.log.gz` of the four runs for `final state is not this node's closing block`, `diverged from the record`, `final_state does not match` and `leftover consensus output`: 0 in each run. Matches.
- The image has the same drop path (2df831e3c `run_epoch.rs:796` `to_engine.send(output).await?`, :820 `recv().await`, close_epoch.rs Phase 1 with no check), so "show the trigger" holds for it.
- The four run-page URLs have the form already posted in #1851. Matches.

## GitHub

- #1575 (merged 2026-10-07, closes #1562), "Notes for review": "Pre-existing and left alone: if `wait_for_epoch_boundary` is cancelled while `to_engine.send` holds an output, Phase 1 of the leftover drain forwards the following outputs with no continuity check and Phase 2 never backfills the dropped one. ... Separate issue to follow." Matches.
- #1618 (open), "Subscriber drops unsaved outputs at teardown when the consensus_output queue is full": stops forwarding at the first failure because a skip "would instead let Phase 1 forward k+1 and move `last_forwarded_consensus_number` past k". Matches "the subscriber side, keeps the queue gap-free because Phase 1 has no continuity check".
- #1562 (closed 2026-10-07, completed by #1575): "`consensus_output` broadcast is still lossy for the CVV path and a slow engine". Matches.
- Search `output drop epoch loop in:title,body` (state all, 20) and `wait_for_epoch_boundary cancelled in:body`: no issue reports this case.

## Not traceable

- "Found while reviewing a change to the epoch-close path" (line 36): the review is not among the allowed sources. #1575's notes for review (2026-10-07) already named the case; the sentence is consistent with either review, and the Related list says so.

## Weak

- Line 32 "it costs that node, alone, its execution state": supported for execution state (the forward, the drain and the engine are per node); the text's own line 27 leaves the node's votes in that window unknown, so "alone" should not be read past execution state. Optional: "it costs that node its execution state; other nodes' execution is not affected."
- Line 30 "rebuilds execution from the node's own consensus database" cites `crates/telcoin-network-cli/README.md:487-489`, which says "rebuilds it from genesis"; the own-packs wording is at :492-493 and tn-reth README:968-969 (cited later in the sentence). Optional: cite `:487-493`.
- Line 30 "by the code a divergent record the node saved would stop the rebuild" cites a README (tn-reth README:968-977); the code basis is `epoch_records.rs:641-649` plus `check_stored_record`. Optional: "by the README".
- "stops the node" (line 25) and "never forwarded" (line 17) are supported (above).

## Rule breaches

None: no em or en dash, no unit names, no private paths, no host or person names ("one validator"), no tool attribution; "bench 6's four runs" stands beside its four run ids.

## Note on the writer's source note (not the text)

The source note's zero-count grep used main's line `final_state does not match`, which the bench 6 image does not log; the image's line is quoted above. The note should name both.

## Counts

Figures and statements checked: 66. Matched: 64. Wrong: 1 (error 1). Untraceable: 1.
