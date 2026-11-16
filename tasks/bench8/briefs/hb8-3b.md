# HB8-3b — finish HB8-3a, the reduced run's setting, and three defects in a plan test

Common brief: `tasks/bench8/briefs/hb8-common.md`. The unit you continue: `tasks/bench8/briefs/hb8-3a.md` and its checkpoint `tasks/checkpoint-bench8-HB8-3a.md` (its findings for items 1, 2 and 5 are there in full with file:line; trust them). Your checkpoint: `tasks/checkpoint-bench8-HB8-3b.md`. The harness tree is committed and clean.

## A. The reduced run's setting (from HB8-3a's item 1; the orchestrator's ruling)

The plan wants run R's load blast at about 5,300 tx/s (void outside 4,500-6,500) and wrote `BENCH_SENDERS=300`, `BENCH_WINDOW=3`. From bench 7's three blasts (in flight = senders × window × ten generators; rate ≈ in flight ÷ mean seen latency: blast 0 at 1,280 in flight 698 / 680 tx/s, light blast 1 at 24,000 in flight 9,399 / 9,576 tx/s, the load blast at 96,000 in flight 9,289 / 9,337 tx/s; `tasks/bench7-report-r20261115-1131.md:206-217`), 300 × 3 predicts about 4,070 tx/s (4,170-4,400 with the method's bias): below the void line. 300 × 4 predicts about 5,180 (5,300-5,600 with the bias).
- `benchmark/launch/bench8-reduced.env`: `BENCH_WINDOW=4` (keep `BENCH_SENDERS=300`); the header says in three lines why (the rate target is the plan's; the setting follows the prediction; one run per setting and a two-point interpolation, so the void band is the check).
- `benchmark/launch/README.md`, section "Bench 8": the reduced run's row and one paragraph with the prediction and its source; also what HB8-3a found about the latest kill: with `BENCH_CHAOS_MIN_LOAD_SECS=817` the kill falls 817-2,016 s into the mixed phase; the restart is always inside the workload (the driver checks it, `benchmark-blast.sh:1986-1994`); in the latest case the observer step runs about 36 s after the workload ends, is not a failure, and bench 8 does not read it; a run that needs every step inside sets `BENCH_DURATION_SECS=2520`. No launch file changes for that.
- The test in `benchmark/tests/test_launch.py` that pins the reduced file's senders and window (HB8-1's `Bench8EnvTests`) follows.

## B. HB8-3a's items 3, 4 and 6 (not started; its brief has them word for word)

3. The readback, the provenance reader and the chain's idle check read the `node switches` line by key: one test each with the node's real order (the count LAST).
4. `benchmark/arms/MANIFEST-FIELDS.md` near `:400`, `:409`; the mutation checker's anchors (`benchmark/tests/check_mutations.py` near `:540`, `:559`).
6. Callers of `tasks/bench8/orch-prom-export.py` that treat only rc 0 as success.

## C. Three defects in `tasks/bench8/tests/test_orch_bench8.py::TestChainPlanBench8` (HB8-3a item 5, shown on its scratch copy `/home/drtnarg/.claude/jobs/e50668f4/tmp/HB8-3a/t/test_orch_bench8_fix.py`)

(a) The placeholder fill only fills values that START with `<`; the launch files carry `…adiri@sha256:<image-digest>` and `sha256:<image-digest>`: fill by placeholder name, keeping the prefix. (b) The fill is written after the sandbox's commit, so the launcher refuses a dirty tree: commit after the fill. (c) The step-3 assertion expects the line to END with `quorum_exec_block_floor_outputs`, but every `CHAIN` line ends with a UTC stamp: match `quorum_exec_block_floor_outputs \S+$`.
Also: the plan tests skip when ANY process on the host has a harness driver's name anywhere in its command line (an agent's grep, an editor). In the two bench 8 test modules (`tasks/bench8/tests/test_orch_bench8.py`, `tasks/bench8/tests/test_orch_scripts.py`; NOT bench 7's) make the skip condition "a driver is executing": the script's name is the program or the script a shell runs (the first two words of the process's arguments), as `tasks/bench6/e2e-lane2.sh` does in its `foreign()` function. `launch.sh`'s own guard is not touched.
Then `python3 -m unittest tasks.bench8.tests.test_orch_bench8 tasks.bench8.tests.test_orch_scripts` must run the plan tests (not skip them) and pass.

## Yours

`benchmark/launch/bench8-reduced.env`, `benchmark/launch/README.md` ("Bench 8"), `benchmark/tests/test_launch.py`, `benchmark/arms/MANIFEST-FIELDS.md`, `benchmark/tests/check_mutations.py` (anchors only), `benchmark/tests/test_params_apply.py` and `test_report_provenance.py` (add tests only), `tasks/bench8/tests/test_orch_bench8.py`, `tasks/bench8/tests/test_orch_scripts.py`, and for item 6 the callers under `tasks/bench8/`.

Order: A, C, then B's items 3, 6, 4. Hand back as the common brief says.
