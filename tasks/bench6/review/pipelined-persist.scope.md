# Review scope — pipelined-persist

Upstream issue: #1800 (execution ceiling). Switch: `pipelined_persist` (bool; default false).
Where: branch `b6/pipe-stack-2` (the integration branch plus the held pipelined-persist commits), checked out READ-ONLY for you at `/home/drtnarg/coding/telcoin/tn-b6-u0c` (use that directory instead of the brief's; builds and tests of another job run there, sources do not change), head 86956df51. Size: 18 commits, +7127 lines (tests included).

## Commits (the diff under review, in branch order)
- `5472d5ee1` feat(tn-reth): pin one read snapshot per output for the layered state root
- `ceab12841` refactor(engine): split output execution into build and commit halves
- `cbe6e1af0` feat(engine): pipelined persist core behind PersistPipeline
- `81e5f7144` feat(engine): pipelined persist metrics
- `70c553f44` test(tn-reth): persist delay hook for engine pipeline tests
- `9b3a4cbfc` feat(engine): run the pipelined persist behind pipelined_persist
- `ff5cd2185` docs(tn-reth): atomicity contract with a pipelined engine
- `a3d266304` docs(engine): queued recovery jobs share the recovery pool when one is set
- `3e314c545` fix(engine): pipelined loop fails closed with nothing to wait on
- `466d6174c` docs(engine): pipelined persist series export zero on a sequential node
- `7276103fd` test(engine): apply the execution delay hook in the pipelined build task
- `181320d5f` test(engine): differential and persist-fault tests of the pipelined persist
- `9bcbf8bc4` test(engine): cycle bench of the pipelined persist (go/no-go gate 5)
- `71ae39958` test(types): TN_TEST_PERSIST_DELAY_MS holds every persist for e2e tests
- `c76114d64` test(e2e): pipelined and sequential validators build the same chain
- `c6240f467` test(e2e): pipelined validators close an epoch under load
- `f61988587` test(e2e): SIGKILL a pipelined validator mid-pipeline and replay
- `86956df51` test(reth): read the persist delay hook where the persist runs

## Files touched
- `crates/e2e-tests/tests/it/persist_pipeline.rs`
- `crates/engine/src/error.rs`
- `crates/engine/src/lib.rs`
- `crates/engine/src/metrics.rs`
- `crates/engine/src/payload_builder.rs`
- `crates/engine/src/persister.rs`
- `crates/engine/tests/it/main.rs`
- `crates/engine/tests/it/persist_pipeline.rs`
- `crates/tn-reth/src/env/execution.rs`
- `crates/tn-reth/src/env/mod.rs`
- `crates/tn-reth/src/env/output_overlay.rs`
- `crates/types/src/test_hooks.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- The design `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-5/design.md` (§2 state machine, §3 invariants with their enforcing sites, §4 crash and failure matrix, §6.5 go/no-go).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U12a", "From U12b", "From ST-U12a" (as built; D45, D52-D56) and the API note `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/briefs/u12a-api.md`.
- Unit checkpoints `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u12a.md`, `…-u12b.md`, `…-st-u12a.md`, `…-st-u12c.md`, and the e2e results: `…-st-u12b.md` and section "From ST-U12b" of the gate notes (mixed fleet, epoch close and five SIGKILLs mid-pipeline all passed 3 of 3).

## Questions specific to this topic (2g)
1. Invariant I3 (one pinned read snapshot per output for every state root of N+1): find any read during N+1's build that could see N's commit half-applied or a later snapshot.
2. Durability before visibility: is anything that consensus, a peer or the epoch record can see (engine updates, `recent_blocks`, canonical head, the execution backlog) ever ahead of what is durable? RPC `latest` is known to be (D53).
3. Crash matrix: a SIGKILL at every point between build start of N+1 and commit end of N. Does restart always find a consistent database and replay to the same chain? What about a persist error that is NOT a crash (the pipeline refuses and drains)?
4. Epoch close: the closing output is a barrier in the engine and the forwarder sends nothing past a close. Can the next epoch's first output ever build on a closing block that is not durable, or with base fees or gas accounting from the wrong epoch?
5. Two threads touch reth's in-memory chain (the build task and the commit task). Find a data race or an ordering in which the commit removes blocks the build still needs.

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/pipelined-persist-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-pipelined-persist.md`
