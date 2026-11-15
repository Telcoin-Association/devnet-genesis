# Figure-check FC-NRM: texts 00, 01, 02 and the epoch-loop text on today's main (33b727fce)

Checked 2026-11-15 (Sun Nov 15 14:15 UTC) by a read-only checker against the code in `/home/drtnarg/coding/telcoin/tn-b7-p2` (git reads only) and the gate logs named in the launch prompt.
Scope: the lines changed by `git diff 7a814eb 06cb3f5`, plus every commit id, compare link, `path:line` and "on main" sentence in each text.
The line `Stack-wide gates: to be filled in when the gates on the top of the stack have finished.` is a placeholder and was not checked.

## Verdicts

- `bench6-00-switches-obs.md`: PASS
- `bench6-01-e2e-scaffold.md`: PASS
- `bench6-02-vote-queue.md`: PASS
- `bench6-xf-epoch-loop-output-drop.md`: PASS (one weak statement below, optional to change)

## Errors

None.

## Not traceable

None.

## Weak

1. `bench6-xf-epoch-loop-output-drop.md`, stack paragraph, line 9: "everything its first seven commits call is on main at 33b727fce, and their diff applies there with fuzz (checked, not built)".
   What the code shows: `git diff b7/n2-04 ca4f68b0f` (the seven node commits) applied to main's `close_epoch.rs` and `run_epoch.rs` exported to scratch applies only with `patch -p1 -F3`.
   With patch's default fuzz of 2, close_epoch.rs hunk 1 (the import block) fails, because its trailing context is head 03's three-line `use crate::{… metrics::EpochMetrics …}` block and main has a one-line `use crate::{engine::ExecutionNode, manager::EpochManager, primary::PrimaryNode};` (main close_epoch.rs:18).
   A three-way merge, as a cherry-pick would do (`git merge-file` on the same files), conflicts in three places: the import block and the test-module ends of both files.
   All three are context only (the added lines need nothing from the stack, and every symbol the commits call is at 33b727fce: `check_output_continuity`, `OutputContinuity`, `retry_provider_faults`, `manager_with_engine_and_floor`, `certified_record_closed_epoch`, `epoch_tasks_ended`, `EPOCH_TASK_MANAGER`, the `metrics` and `metrics-util` dependencies), so the claim "needs nothing from the stack below" holds.
   The same wording was accepted on the earlier cut; it is listed here because a reviewer who tries `git cherry-pick` gets conflicts.
   Optional replacement: "Its node change needs nothing from the stack below: everything its first seven commits call is on main at 33b727fce, and their diff applies there with fuzz in the import block and the test-module ends (checked with `patch -F3`, not built); the eighth adds the stop to `crates/e2e-tests/tests/it/fleet.rs`, which `fix/epoch-record-collector-hardening` creates."

## Rule breaches

None in the four texts: no private path, no unit name, no host or person name, no run nickname, no attribution of any tool or assistant.
Every commit id resolves; each is either in the series (`33b727fce..b7/n2-xf`) or one of the allowed outside ids (2df831e3c, 45dce8947, 33b727fce).

## Cross-text check (with the first 12 lines and the Related sections of texts 03 and 04)

- PR numbers: 00 = 1, 01 = 2, 02 = 3, 03 = 4, 04 = 5, epoch-loop = 6, all "of 6": consistent.
- Merge order: "00, 01, 02, 03, 04, then `fix/epoch-loop-output-drop`" in 00, 01, 02, 03 and 04; "00, 01, 02, 03, 04, then this" in the epoch-loop text: consistent.
- Compare links chain without gap: N..b29d59bef (12), b29d59bef..87be96651 (8), 87be96651..17327280d (10), 17327280d..c2f266b9c (3), c2f266b9c..ff877fb0e (27), ff877fb0e..f5f7589f5 (8); every count matches `git rev-list --count`, and the six heads form one linear chain on 33b727fce.
- Switches (`runtime_switches!` in crates/config/src/node.rs): 00 and 01 an empty list; 02 `vote_queue_fix`; 03 unchanged from 02; 04 adds `epoch_record_recertify` and `epoch_record_collect_past_uncertified`; the epoch-loop head unchanged from 04.
  Text 00 ("two switches" for 04, "no switch" for 03 and the epoch-loop head, `vote_queue_fix` for 02, "The first switch comes with `fix/1804-vote-queue`"), text 01 ("there is no switch"), text 02 and text 04 ("behind two switches") agree with the code and with each other.
- The one unconditional rule of head 04: text 00 calls it "one eviction rule of the collector hardening"; text 04 says "a full vote queue never evicts the rounds of the newest record or the one before it"; the code at b7/n2-04 `crates/node/src/manager/epoch_votes.rs:610-621` reads no switch (`vote_queues.retain(...)`, then at 5 entries removes the lowest epoch's entry; main at 33b727fce:403-405 pops the front): consistent.
- Stacked-on and Next lines agree: 01 on 00, 02 on 01, 03 on 02, 04 on 03, epoch-loop on 04; 02's Next lists 03, 04 and the epoch-loop head; 04's Next lists the epoch-loop head and `fix/1804-quorum-exec-block`; the epoch-loop text's Next lists `fix/1804-quorum-exec-block` and `fix/1807-digest-order-hold`.

## Note for the publisher (not a text error)

The local branch `staging/benchmark-bench6-2026-11` in the telcoin-network repository still points at 45dce8947.
Text 03 says that branch "is main at 33b727fce", and text 00's compare link starts at 33b727fce; if the branch is not moved to 33b727fce before PR 00 is opened, PR 00's diff would also show main's commits from 45dce8947 to 33b727fce.

## What was checked, per text

### bench6-00-switches-obs.md (PASS)

- "PR 1 of 6" and the merge order; base 33b727fce; compare link full shas (33b727fcea4f…, b29d59bef7b4…) and "12 commits": match.
- The twelve ids in "Change", in order, with exact subjects: match `git log --reverse 33b727fce..b7/n2-00`; `git range-diff` against the old series: commits 2-12 `=`, commit 1 differs only in the context of its test-module hunk, as line 76 says.
- Line 14 (which changes have no switch): matches the switch lists above and head 04's unconditional eviction.
- `crates/config/src/node.rs:273-274` at 33b727fce: the `#[derive(...)]` and `pub struct Parameters {`, no `deny_unknown_fields` in the file: match.
- `recorder.rs:18-19` (`SECONDS_BUCKETS`, first bound 0.005) and `:170` (the `_seconds` suffix matcher): match; the four engine stage histograms are not among main's five sub-ms `Full` overrides (recorder.rs:171-190).
- `proposer.rs:842` and `:1384-1385`, `handler.rs:353-358`: match; the three measurements are absent at 33b727fce (`epoch_entry_rounds_behind`, `first_received`, `oldest_requeue_wait_ms`, `tn_node_switch` all 0 hits).
- "only comments added" to `Parameters` and `Default`: `git diff 33b727fce b7/n2-00 -- crates/config/src/node.rs` struct and `Default` hunks add marker comments only.
- Gate at 17327280d (= `b7/n2-02`, the tip of `fix/1804-vote-queue`, contains b7/n2-00): `gate-n1-02.log` `check --workspace --all-targets rc=0`, gate script `RUSTFLAGS="-D warnings -D unused_extern_crates"`; nextest command as in the text (n1-02-nextest.log line 1), `1825 tests run: 1825 passed, 9 skipped`; the pinned tests and `unknown_keys_are_ignored`, `switches_list_every_switch_field` all PASS there (`test_engine_stage_histograms_render_sub_ms_buckets` is in tn-metrics, outside that gate; the text claims no run of it on today's main).
- Earlier-cut results (fmt, clippy, cargo test three times, 1,207 passed) carry the label "On the stack's earlier cut on main at 45dce8947" and are not presented as today's.
- `crates/tn-lmdb/src/env.rs:309-317` (the `readahead` doc and field; line 397 `readahead: !cfg!(target_os = "linux")`), `mdbx` off by default (crates/tn-reth/Cargo.toml:148 `default = []`), `close_epoch.rs:718-755` (`check_stored_record`), `parallel.rs:70-90` (lines 70, 80, 90 as the text uses them): match at 33b727fce.
- Not run on a fleet: stated.

### bench6-01-e2e-scaffold.md (PASS)

- "PR 2 of 6", merge order, stacked on `feat/bench6-switches-obs`, compare link full shas (b29d59bef7b4…, 87be96651480…) and "8 commits": match.
- The eight ids with exact subjects, and `87be96651` in Limits (doc comments only, 10 lines in lib.rs): match; range-diff against the old series all `=`.
- `crates/e2e-tests/src/lib.rs:356`, `:388` (the two `parameters.yaml` copies), `tests/it/common.rs:527` (`start_validator_with_env`), `tests/it/restarts.rs:1368-1388` (`node_log_lines` … `wait_for_node_log_line`) and `:2074` (`log_field`): match at 33b727fce.
- "main has not changed the three files they edit since": `git diff --stat 45dce8947 33b727fce` over lib.rs, common.rs, restarts.rs is empty.
- Gate at 17327280d: check rc=0 with warnings denied; `n1-02-check.log:43` `Checking e2e-tests`; e2e-tests is a workspace member; "unit tests were not run on today's main": the gate's nextest has no `-p e2e-tests`.
- Earlier-cut results carry "On the stack's earlier cut on main at 45dce8947" or "on main at 45dce8947, before they were stacked".
- `db load-state` uses no `Parameters` field on main: no hit in crates/telcoin-network-cli/src/db.rs or db/ at 33b727fce.
- First callers of the override helpers: only lib.rs and common.rs at heads 01-03, `epoch_record_walk.rs` and `fleet.rs` at head 04; `FleetOverrides` in `exec_block.rs` at the top of the series: match.

### bench6-02-vote-queue.md (PASS)

- "PR 3 of 6", merge order, stacked on `test/bench6-e2e-scaffold`, compare link full shas (87be96651480…, 17327280d545…) and "10 commits": match.
- The ten ids with exact subjects: match; range-diff all `=`.
- `handler.rs:1029-1033`, `:1158-1162`, `:1462-1507`, `:1845-1855` at 33b727fce: match (the file is unchanged between 45dce8947 and 33b727fce).
- Gate at this head's tip 17327280d: check clean, nextest 1,825 passed, 9 skipped; every test named in Testing (switch-off twin = `vote_queue_fix_off_answers_repeat_of_voted_header_from_cache`) and in Limits (`vote_queue_fix_newer_request_waits_for_pending_parent_wait`) has a PASS line.
- The earlier-cut result (1,303 passed, 4 skipped) carries the label.
- Benchmark sentence: "no benchmark has run this head"; the earlier form's benchmark is described as running with no result.
- The "as on main" / "on main they wait on the lock" sentences rest on code unchanged since the earlier check (handler.rs identical; `git diff 45dce8947 33b727fce -- crates/config/src/network.rs` touches no per-peer, stream or vote line).

### bench6-xf-epoch-loop-output-drop.md (PASS, one weak)

- "PR 6 of 6", merge order, stacked on `fix/epoch-record-collector-hardening`, compare link full shas (ff877fb0ef97…, f5f7589f52ff…) and "8 commits": match.
- The eight ids with exact subjects: match; range-diff commits 1-7 `=`, commit 8 `!` (fleet.rs).
- "first seven commits … the eighth adds the stop to fleet.rs, which `fix/epoch-record-collector-hardening` creates": the seven touch only close_epoch.rs and run_epoch.rs; f5f7589f5 touches only fleet.rs; fleet.rs is absent at 33b727fce and added by ff877fb0e in head 04.
- "applies there with fuzz": see Weak 1.
- `run_epoch.rs:749` (`while let Some(mut output) = consensus_output.recv().await`), `:730` (`to_engine.send(output).await?`), `close_epoch.rs:320` (`while let Ok(output) = consensus_output.try_recv()` in the drain at 314): match at 33b727fce.
- "33b727fce changes neither run_epoch.rs nor the drain": run_epoch.rs diff empty; close_epoch.rs hunks of 45dce8947..33b727fce start at line 415, after the drain (314-378 at 45dce8947).
- Main's live forward stops on the same rule: 33b727fce run_epoch.rs:756 `check_output_continuity`.
- `crates/engine/src/metrics.rs:81` at the head still says "stamped just before its send"; crates/engine unchanged between 33b727fce and the head.
- Gate: `gate-n1-xf.log` start 15f60ff82, check rc=0 (warnings denied by the script), nextest command as in the text, `2048 tests run: 2048 passed, 10 skipped`, no FAIL line, one PASS line for each of the 11 named tests.
- "this head's tree but for comment lines in two crates/state-sync files": `git diff --stat 15f60ff82 f5f7589f5` = state-sync epoch.rs (12) and metrics.rs (18), every changed line a comment; 15f60ff82 is on 33b727fce; the commit is b7f008dc9 (docs-only, in head 04, not in head 03), committed 13:26:13Z, after the gate's 13:10:39Z-13:13:11Z.
- Earlier-cut clippy carries "On the stack's earlier cut on main at 45dce8947"; "no fleet has run this head yet": stated.

## Counts

- 00: 40 checked, 40 matched, 0 wrong, 0 untraceable.
- 01: 30 checked, 30 matched, 0 wrong, 0 untraceable.
- 02: 33 checked, 33 matched, 0 wrong, 0 untraceable.
- epoch-loop: 36 checked, 36 matched (1 weak), 0 wrong, 0 untraceable.
- Cross-text facts: 6 checked, 6 consistent.
- Total: 145 checked, 145 matched (1 weak), 0 wrong, 0 untraceable.
