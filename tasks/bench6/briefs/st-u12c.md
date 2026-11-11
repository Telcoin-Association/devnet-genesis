# ST-U12c — the pipelined-persist cycle bench (test unit; go/no-go gate 5)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections;
the "Test units" section is yours). Skills: `tn-rust-skills`, `tn-domain-execution`, `tn-domain-storage`.
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u0a` — a finished unit's directory; the directory name is NOT your unit's — branch
`b6/u-st12c` at the commit given in your prompt (the integration head, the pipelined-persist core and wiring, and the
differential and fault tests in `crates/engine/tests/it/persist_pipeline.rs`). Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-u12c.md`.

## Why
Pipelined persist (switch `pipelined_persist`) lets the engine build output N+1 while N's persist runs, so that the cycle per
output is max(execute, persist) instead of their sum (bench 5: execute 479 ms + persist 1,167 ms per output; the expected gain
is ×1.41). It ships in the bench-6 image only if every go/no-go gate passes. Gates 1-3 passed. Gate 5 is a measurement nobody
has written yet: the pipeline's cycle must be at most 1.1 × max(execute, persist). If the overlap makes persist stretch (a
build reading the same memory map, a pinned reader deferring page reuse by one commit) the gain shrinks, and this is the only
place that shows it before a fleet does.

## Read
1. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-5/design.md`: §2 (the state machine), §6.3's last
   bullet (`bench_pipeline_cycle_vs_max_phase`: the shape and the assertion), §6.5 item 5, §7.1 item 3.
2. `crates/engine/tests/it/persist_pipeline.rs` (the helpers you reuse: the two-node fixture, the output generator, how the
   pipeline is driven and how the sequential oracle runs), `crates/engine/src/persister.rs` (the events and the `CommitReport`
   laps), `crates/engine/benches/engine_contention.rs` (how a timed binary in this repo prints its header and result lines,
   computes nearest-rank percentiles and keeps its DB under `TMPDIR`).
3. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U12a" and "From U12b".

## You own
`crates/engine/tests/it/persist_pipeline.rs`: ADD to it, change nothing that exists (the existing tests are the go/no-go
evidence for gates 1 and 2). Nothing else; no `crates/**/src`.

## Deliver
`bench_pipeline_cycle_vs_max_phase`, `#[ignore = "heavy: release profile, CPU-quiet and disk-quiet host"]`, as the design
describes it: 40 outputs of 10 blocks with 200 transfers each to fresh accounts plus storage writes, run through
`PersistPipeline` (commits never held: the pipeline runs free) and then through the sequential path on a second node from the
same genesis. Over outputs 6-40:
- from the pipeline's own reports, the median commit interval and the median of max(execute, persist) per output; assert
  interval ≤ 1.1 × that median;
- the sequential cycle (median execute + persist per output) and the speedup = sequential cycle ÷ pipelined interval;
- whether persist STRETCHED: the median persist lap pipelined ÷ sequential, and the same for the execute lap (this ratio is
  the number the gate exists for: print it even though only the 1.1 × bound is asserted);
- one result line with all of it, and a header line with host, cpu count, profile, shape.
The shape must be overridable from the environment (outputs, blocks, transactions per block) so a smoke run takes seconds; an
optional per-persist delay through the existing test-utils hook lets a persist-bound regime be forced on a lab database whose
real persist is far shorter than its execute — print which regime each run was in (execute-bound or persist-bound), because
the 1.1 × bound means something different in each, and a run that never had the pipeline overlap must say so plainly.
Both final chains must be equal (reuse the file's own comparison), so that the bench cannot time a wrong chain.

## Limits
You do NOT run the full shape: it needs the host quiet, and the orchestrator runs it. Smoke it at a tiny shape in the test
profile and once in the release profile (through the slot wrapper; say how long the release build took), with and without the
forced persist delay. Numbers from smoke runs are not results: say so beside them.

## Gates
`cargo check --locked --all-targets -p tn-engine`, fmt, clippy for the package, `cargo nextest run --locked -p tn-engine
-p tn-node -E 'package(tn-engine)'` (the existing 60+ tests still pass; the new one is ignored there). One commit,
`test(engine): …`, footer `Topic: pipelined-persist`.

## Hand-back
The bench as built (what it times, from which report fields), the smoke output verbatim, the exact command lines for the full
run (release profile, pinned to the fleet's 4 cores × 2 threads with `taskset -c 0-3,8-11` and unpinned), the expected
duration, what quiet it needs (CPU, disk, memory), and what the numbers can and cannot say about a real node.
