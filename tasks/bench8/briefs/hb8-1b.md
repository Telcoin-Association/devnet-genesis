# HB8-1b — finish HB8-1: retire bench 7's switch list, the READMEs, and three open checks

Common brief: `tasks/bench8/briefs/hb8-common.md`. The unit you continue: `tasks/bench8/briefs/hb8-1.md` and its checkpoint `tasks/checkpoint-bench8-HB8-1.md` (read both; trust the checkpoint's map). Your checkpoint: `tasks/checkpoint-bench8-HB8-1b.md`.

HB8-1 left in the working tree, uncommitted (do not revert any of it): three new arms, four new launch files, `benchmark/arms/switches.tsv` (+ the row `quorum_exec_block_floor_outputs int 8 8,16`, and `digest_order_hold`'s arm values `true,false`), new tests in `benchmark/tests/test_launch.py` and `test_params_apply.py`. It set `BENCH_CHAOS_MIN_LOAD_SECS=817` in the four launch files instead of adding a knob (the existing knob already holds the kill back; accepted).

## 1. The blocker: 14 existing tests pin bench 7's seven-row list

The orchestrator's ruling: bench 7's list is retired the way bench 6's was (`benchmark/arms/switches-bench6.tsv` is the model: read how it is named, loaded and tested). So:
- New file `benchmark/arms/switches-bench7.tsv` = `switches.tsv` as it is in git HEAD (`git show HEAD:benchmark/arms/switches.tsv`), byte for byte.
- `benchmark/arms/bench7-always.arm` and `bench7-adaptive.arm` name their list the way bench 6's arms do (the `build` directive or whatever the model uses); their `param` lines do not change.
- The tests that pin bench 7's list (`test_params_apply.py`: `Bench7ListTests` and the three others HB8-1 names; `test_node_image.py::test_switch_keys_are_the_rows_of_switches_tsv`; `test_report_provenance.py::Bench7SwitchListTests`) point at the retired list. You may change these tests ONLY to repoint them; no assertion gets weaker. Where a test pins "the live list", add its bench 8 twin (eight rows, the count with default 8, `digest_order_hold` with `true,false`).
- `benchmark/config.sh` `BENCH_NODE_SWITCH_KEYS`: add the one token for the new count if the live list needs it there (read what consumes it first); a run with the knob set as bench 7 had it must behave as before (test).
- `benchmark/report/…/provenance.py` `run_switch_rows()` picks, per run, the list that shares the most keys with the run. A bench 7 run's `node switches` line has seven keys, all of them also in the eight-row list: prove with a test which list a bench 7 run gets (it must be the seven-row one, so the missing count is not read as a defect) and which a bench 8 run gets; fix the tie-break if it is wrong.
- Then the three modules must be green: `test_params_apply`, `test_node_image`, `test_report_provenance`, plus `test_launch`, `test_arms_summary`.

## 2. The READMEs (HB8-1's section 5)

`benchmark/launch/README.md`, section "Bench 8": the four launch files and what each changes against `bench7-always.env`; the read window (the load blast before the kill; with `BENCH_CHAOS_MIN_LOAD_SECS=817` the kill falls between 817 s and 2,016 s into the mixed phase, so the window is at least 817 s and its length is named with every figure); the void rule of the reduced run (4,500-6,500 tx/s in the load blast). `benchmark/arms/README.md`: the three arms and the retired list.

## 3. Three open checks (findings; code only if a check fails)

- The reduced run's expected rate: derive it from saved figures, not from the brief. Bench 7's second light blast ran 600 senders × window 4 per generator and its rate is in the run's results (`benchmark/results/r20261115-1131/analysis/` or the report's KPI table: `grep -n 'light' tasks/bench7-report-r20261115-1131.md | head`); the reduced load blast is 300 × 3. State what rate that predicts, with the source, and whether 4,500-6,500 is the right void band for it.
- The latest-kill case: with the kill at up to 2,016 s, the observer step (restart + 300 s) lands near 2,616 s, after the 2,580-s workload. Read what the blast driver does when a chaos step's time is past the workload's end (skips it, runs it late, fails the run?) and say so with file:line. If it fails the run, say what bound on the kill avoids it; do not change the driver.
- `bash -n` and `shellcheck -S warning` on every shell file touched by HB8-1 or you; the 3.9 grammar check on the Python files.

## Yours

`benchmark/arms/switches-bench7.tsv` (new), `benchmark/arms/bench7-always.arm`, `bench7-adaptive.arm` (the list directive only), `benchmark/arms/README.md`, `benchmark/launch/README.md` ("Bench 8"), `benchmark/config.sh` (the one token), the provenance reader's list choice if the tie-break needs it, and the five test modules named above. HB8-1's new files are yours to correct if a test shows a defect. Nothing under `tasks/bench8/` except your checkpoint (another unit works there).

Hand back as the common brief says, plus: the list a bench 7 run and a bench 8 run each get, the predicted rate of the reduced run with its source, and the driver's behaviour in the latest-kill case.
