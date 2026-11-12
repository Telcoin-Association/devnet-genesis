# I-3b — the engine contention bench's results into the I-3 verdict (§3b), and the recovery-pool topic's verdict line

You are unit **I-3b** of the bench-6 program: a small read-only analysis unit.
Read `tasks/bench6-agent-rules.md` first (sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Investigations", "HAND BACK").
Checkpoint: `tasks/checkpoint-bench6-I-3b.md` (on start read it and continue from the first unfinished section; rewrite after each section).
Scratch: `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/I-3b/`.
Budget: under 90k tokens. Final answer: at most 25 lines. No cargo, no gcloud, no commit. A harness gate is running on this machine: start no test and no build.

## You own (and write nothing else)
`benchmark/private/bench6-prep/I-3/verdict.md` — ONLY its section "### 3b. Criterion …" (a pending stub today) and one reconciling paragraph at the end of §3 — and the new `benchmark/private/bench6-prep/I-3/contention-u4b.md` (the full table).

## Inputs (read these, nothing further)
- The four result files of the full run on a quiet host, 2026-11-12T08:10-08:20Z: `benchmark/work/bench6-scratch/u4b/engine-contention-{global,dedicated}-{c8,c16}.txt` (stdout: `#` header, `BENCH` and `CRITERION` lines), their `.meta` (load before and after) and `.err` (progress).
  `c8` = `taskset -c 0-3,8-11`, the fleet's 4 cores × 2 threads, the canonical shape; `c16` = the whole host, for comparison.
- How to read them: `tasks/bench6/u4b-engine-contention-runbook.md`, section "Reading the numbers".
- What they answer: `benchmark/private/bench6-prep/I-3/verdict.md` §3 and §3a (the run's per-output evidence on validator 09: `finish` 22.1 against 7.8 µs/tx with and without an overlapping recovery job at 600 × 4, 16.3 against 6.7 at 600 × 16; the overlap quartiles), and §2 (E5's share: the read-cache A/B).

## Sections
1. **The table** (`contention-u4b.md`): per pool and CPU shape, every case's `finish` median with p10 and p90, evm, root, execute, the job's overlap, and each `CRITERION` verdict, with the file each number comes from. Note any run whose `.meta` shows load from something else (the bench's own global-pool cases load the host; the header's `cpus=` and `rayon_global_threads=` say what the process saw).
2. **§3b of the verdict**, in the verdict's own style and wrapping, at most 25 lines: what the bench shows for the question "does a queued recovery job slow `finish`, and does a dedicated pool remove it" — the size on the global pool for the `_once` cases against bench 5's +8 to +15 µs/tx, the dedicated pool's result for the same cases, the saturation (loop) cases as a bound and why their size is not a fleet number, the root share with the `oversubscribed` flag, and the read-cache A/B (`cached_reads`: the saving with its sign, for §2). Say what a lab database and 6,000 transfers per output cannot show.
3. **The reconciling paragraph** at the end of §3: does the bench agree with §3a's per-output evidence from the run, in direction and in size; what run 1's `pool-local` arm must show on the fleet for the recovery-pool switch to count as confirmed (name the node's own field the arm summary reads: `pool=dedicated`).

## Hand back
Status; the three or four numbers that carry the result; whether the dedicated pool passes its own criterion in both shapes; anything in the files that looks wrong (a NaN that should be a number, a verdict line that contradicts its BENCH lines).
