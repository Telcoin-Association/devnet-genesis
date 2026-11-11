# What unit U12a (pipelined persist, core) landed — for the wiring unit (U12b) and the test units

NOT yet on the integration branch (pipelined persist is integrated last so it can be left out): the three commits are on branch
`b6/u-u12a` (tip fd81652d2, base 7cfe52acd) in `/home/drtnarg/coding/telcoin/tn-b6-u0a`; they merge cleanly with the integration
head as of 2026-11-11. Design: `benchmark/private/bench6-prep/I-5/design.md` (§5.4 is the interface; the deviations below win).

## Commits
- e74947cca `feat(tn-reth): pin one read snapshot per output for the layered state root`
- 938493304 `refactor(engine): split output execution into build and commit halves`
- fd81652d2 `feat(engine): pipelined persist core behind PersistPipeline`
Files: `crates/engine/src/persister.rs`, `crates/engine/src/payload_builder.rs`, `crates/engine/src/error.rs`,
`crates/tn-reth/src/env/output_overlay.rs`. `crates/engine/src/lib.rs` is untouched: nothing reads `pipelined_persist` yet.

## Public API (matches §5.4 except where noted)
- `RethEnv::pin_output_overlay(&self) -> TnRethResult<OutputTrieOverlay>` (the pinned block comes from the `Finish` stage
  checkpoint, read inside the pinned transaction); `OutputTrieOverlay::anchor_block(&self) -> Option<BlockNumHash>`;
  `RethEnv::trie_tables_digest(&self) -> TnRethResult<B256>` under `cfg(any(test, feature = "test-utils"))`.
- `PersistPipeline::new(reth_env, parent_header, task_spawner, gas_accumulator, repack_monitor, engine_update_tx)`;
  `can_start`, `start_inline(output)`, `is_idle`, `in_memory_tip`, `durable_tip`, `unpersisted_outputs`, `barrier`;
  `async next_event(&mut self) -> EngineResult<PipelineEvent>`; `hold_commits(&mut self) -> CommitGate` (test-utils only;
  `release_one()`, `release_all()`; dropping the gate releases everything). `BuildReport`, `CommitReport` as designed.
- `TnEngineError::PipelineInvariant(&'static str)` ("pipelined persist ordering check failed: {0}").

## Deviations the wiring unit must know
1. `start` takes an `Option`: `pub(crate) fn start(&mut self, output, signers: Option<RecoveryHandle>)`; call
   `start(output, Some(signers))`. `start_inline` is `start(output, None)`.
2. Two event variants are boxed: `PipelineEvent::Built(Box<BuildReport>)`, `Committed(Box<CommitReport>)`;
   `PersistStarted { consensus_number, waited }` is unchanged.
3. `start` returns `Err` only when `can_start()` is false or the output's number is not greater than the last one started (nothing
   is started or changed). A failed seed check fails the PIPELINE instead: `next_event` returns that error once both slots have
   settled (an error straight from `start` would let the engine stop while a commit is in flight).
4. Consensus order is checked: an output whose number is not greater than the last started is refused, fail closed.
5. A commit task that ends without sending a result: `lookup_head()` decides whether its output counts as committed or as a
   persist failure (rolled back).
6. `output executed` gains `persist_wait_ms`, `seed_ms` and `pipelined=true` ONLY on the pipelined commit's line (a line without
   `pipelined` is sequential): the existing test `test_engine_lines_carry_consensus_ids` (`crates/engine/tests/it/main.rs`) pins
   the sequential field list.

## Log lines (target `engine`)
`pipelined persist failed - rolling back unpersisted outputs` (error; `consensus_number`, `rolled_back_outputs`,
`rolled_back_blocks`, `durable_number`); `pinning the output overlay failed - next output waits for the commit` (warn;
`consensus_number`, `err`); `error building consensus output` (error); `pipelined persist: a later error while settling a failure`
(warn). No new metrics (the wiring unit's).

## What U12a names as the riskiest remaining gaps
- Shutdown and drain: the engine loop must return only when the queue is empty AND `is_idle()` holds; `next_event` may only be
  polled behind `!is_idle()`; blocking tasks cannot be cancelled, so a dropped engine future leaves a commit running.
- A commit landing between two blocks of N+1 (invariant I9): nothing forces that interleaving deterministically yet; it needs an
  injected persist delay (the wiring unit's hook) and the test `test_finalize_during_next_build_keeps_unpersisted_blocks`.
- The pinned read transaction falls under libmdbx's 5-minute read-transaction timeout: a build or persist longer than that would
  stop the node (unreachable at bench timings; state it in the PR).
- `OutputBuildScope::seeded`'s docs (`crates/tn-reth/src/env/execution.rs`) still describe commits landing mid-output; with
  pinning that caveat no longer applies: the wiring unit updates them when it edits that file.

## Tests that exist (all pass at fd81652d2)
3 in `output_overlay.rs` (`mod pinned_tests`, incl. `test_pinned_anchor_root_ignores_later_commit`); 6 slot-table tests and 8
database-backed tests in `persister.rs` (incl. `test_pipeline_two_outputs_overlap_and_commit_in_order`,
`test_seeded_build_matches_unseeded_build`). `cargo nextest run -p tn-engine -p tn-reth`: 544/544.
