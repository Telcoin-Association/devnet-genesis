# ST-U12a — the differential and fault tests of pipelined persist (test unit)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections;
the "Test units" section is yours). Load the `tn-write-proptest` skill and `tn-rust-skills`, then `tn-domain-execution` and
`tn-domain-storage`.
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u0a` — a finished unit's directory with a warm engine build; the directory name is NOT
your unit's — branch `b6/u-st12a`, cut from unit U12a's tip fd81652d2 (the pipelined-persist core).
Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-u12a.md`. Topic slug: `pipelined-persist`.

## Why
Pipelined persist lets output N+1 execute on N's in-memory state while N's persist runs, turning the engine's cycle from
execute + persist into max(execute, persist). It is the one large change of bench 6 and it ships in the image ONLY if its
go/no-go tests pass. You write the first two of them: the differential test (pipelined against sequential must give identical
chains and identical database contents) and the persist-fault tests. Your verdict decides whether the feature makes the image.

## Read
1. The design, `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-5/design.md`: §2 (state machine), §3
   (invariants I1-I9, each with the test that pins it), §4 (crash and failure matrix), §6.3 (YOUR tests, by name, with set-up
   and assertion), §6.5 (the go/no-go list).
2. What the core landed and where it deviates from the design: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/briefs/u12a-api.md`.
3. Code: `crates/engine/src/persister.rs` (the `PersistPipeline` API and its own tests: reuse their helpers where they are
   reachable from an integration test; if a helper you need is private, say so rather than widening an API),
   `crates/engine/src/payload_builder.rs` (`build_output` / `commit_output`, the sequential path),
   `crates/engine/tests/it/main.rs` (how the existing differential test builds environments and outputs; the engine crate's
   `proptest` dev-dependency exists), `crates/tn-reth/src/env/execution.rs` (`inject_persist_provider_faults`,
   `inject_late_persist_provider_faults`), `crates/tn-reth/src/env/output_overlay.rs` (`trie_tables_digest`).

## You own
New `crates/engine/tests/it/persist_pipeline.rs` and the one `mod persist_pipeline;` line in `crates/engine/tests/it/main.rs`
(if that file is a single test file without `mod` lines, add the line where the crate's convention puts it and nothing else).
You do not edit `crates/engine/src/**` or `crates/tn-reth/src/**`: a bug you find there is a FINDING — write the failing test,
mark it `#[ignore = "<one-line reason>"]` only if it would block the rest of your file, and report it with the minimal repro.

## Scope note
The engine wiring (the unit that makes the node's engine loop use the pipeline behind the `pipelined_persist` switch) does not
exist yet. Drive the pipeline through its public API (`PersistPipeline::new`, `start_inline`, `next_event`, the test-only
`hold_commits` gate) against the sequential path, as §6.3 describes. Tests that need the engine loop itself or an injected
persist delay (the design names `test_finalize_during_next_build_keeps_unpersisted_blocks` and the epoch-close barrier test) are
the wiring unit's and the e2e unit's: list them in your hand-back as "not expressible at this level", do not fake them.

## Deliver
1. `prop_pipelined_matches_sequential`: for generated sequences of consensus outputs (include the shapes the design lists:
   empty outputs, outputs that close an epoch, a contract wipe and re-create in one output, a `BLOCKHASH` read of a block of the
   previous output, outputs of very different sizes so that commits land at different points of the next build), one environment
   executes sequentially and one through the pipeline with overlapping commits (use the commit gate to force each interleaving
   the state machine allows: commit before the next build starts, during it, after it); assert identical block hashes, state
   roots, receipts roots, gas used, the set of blocks announced, and identical trie tables (`trie_tables_digest`) after every
   output and at the end. Keep the case count and sizes such that the test runs in about a minute; say what the generator covers
   and what it cannot reach.
2. The persist-fault tests of §6.3 with the two existing injection hooks: a fault in N's persist while N+1 is building or built;
   a late fault; assert the documented outcome (first error wins; every unpersisted block is rolled back to the durable tip; the
   database equals a sequential node that stopped at the same output; nothing is announced past the durable tip; the pipeline
   refuses further starts).
3. Any §6.3 test not covered by 1 and 2 that is expressible through the public API.
4. A short mutation check by hand (in a scratch copy of the worktree's source, restored afterwards, never committed): two or
   three deliberate breaks of the core (for example: the next build does not see the previous output's state; a commit is
   announced before it is durable; rollback keeps one block) each make at least one of your tests fail. Report which.

## Gates
`tasks/bench6/cargo-slot.sh cargo nextest run --locked -p tn-engine -p tn-node -E 'package(tn-engine)'` (the engine crate's tests are
unit and integration tests, not e2e: no lane needed), each new test by name three times, fmt, clippy for the engine package with
`--all-targets`. Commit: one or two commits, `test(engine): …`, footer `Topic: pipelined-persist`.

## Hand-back
The tests by name with what each proves and its runtime; the generator's coverage; the interleavings forced; every FINDING
against the core with its repro; the mutation check; what is not expressible at this level; and your verdict on go/no-go gates
1 (differential) and 2 (persist faults): PASS, FAIL (with the finding), or NOT YET (what is missing).
