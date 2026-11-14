# HB-2 — the switch list of the bench 7 build, the two arm files, and what the harness checks against them

Unit: `HB-2` (harness unit, opus). Rules: `tasks/bench7-agent-rules.md` ("Harness units" and the common sections). Checkpoint: `tasks/checkpoint-bench7-HB-2.md`. Budget: under 180k tokens.
You do not commit. **Do not edit anything under `benchmark/` until your launch prompt says the tree is free.** `benchmark/config.sh` has a writer before you (HB-1: the faucet allowance, the manifest keys, the reserved ports); your launch prompt says whether it has landed. You touch `config.sh` only at the switch-key list (≈ lines 325-330).

## Why

Bench 6's node printed twelve switches on its `node switches` line; the harness knows them from `benchmark/arms/switches.tsv` (name, kind, default, `optional`), `BENCH_NODE_SWITCH_KEYS` in `benchmark/config.sh`, and checks them in three places: the deploy's readback after the first start with the arm (`bench_switch_readback`, `benchmark/bench-lib.sh` ≈ :3541), the arm tool (`benchmark/tools/params-apply.sh`), and the report's provenance pass (`benchmark/report/provenance.py`: every start's `node switches` line against the arm in force; a line that lacks a non-optional key is a problem).
The bench 7 node is upstream main plus a ported stack. Its `node switches` line is generated from a list (a macro in `crates/config/src/node.rs`) and prints **exactly the switches that exist on that build**, each by its YAML key; a key the build lacks is simply absent (bench 6 printed `unlisted`). The gauge is `tn_node_switch{name="<key>"}`: 0/1 for a bool, the count as is, a duration in milliseconds.
The seven switches of the bench 7 build (final; every one defaults off / 0):

| YAML key | kind | topic |
|---|---|---|
| `quorum_exec_block` | bool | the author-side vote fix |
| `quorum_exec_block_starved_rounds` | integer (rounds; 0 = always-on, N > 0 = adaptive) | the same |
| `vote_queue_fix` | bool | the voter-side lock fix |
| `digest_order_hold` | bool | the #1807 own-chain hold |
| `epoch_record_collect_past_uncertified` | bool | the record collector's walk |
| `epoch_record_conflict_halt` | bool | the collector's fail-stop on a conflicting certified record |
| `epoch_record_recertify` | bool | re-vote of an older own uncertified record |

Gone from the build (bench 6 only): `mdbx_random_advice`, `sealed_tx_keep`, `digest_dedupe`, `recovery_threads`, `epoch_close_task_drain`, `epoch_record_state_check`, `parent_grace`, `rpc_admission_backlog_outputs`, `pipelined_persist`. A `parameters.yaml` that names one of them on the new build is an unknown key (main ignores unknown keys without a warning: a silent no-op, which is exactly what an arm must never be).
The closing-block check of bench 7 has NO switch (it extends main's unconditional guard).
Inventory of every reader of these names: `benchmark/private/bench7-prep/obs-inventory.md` (Table B row "node switches shape" and the switch rows of Table A).

## What to change

1. **`benchmark/arms/switches.tsv` and `BENCH_NODE_SWITCH_KEYS`**: the seven keys above, in that order, all required (not optional). Bench 6's nine other rows are REMOVED from the live list, but bench-6 results must stay readable: the provenance pass and the arm summary run on old manifests too (four bench-6 bundles were just built with the twelve-key list). So the readers take the switch set from the RUN where it records one (the manifest's `param_arms[].switches` keys, and the keys the run's own `node switches` lines carry) and fall back to the file; or the file gains a column / a second file for the bench-6 set keyed by the node build. Choose the smaller change that keeps every existing bench-6 test green without editing its expectations, and say which. A test builds the provenance check for a bench-6-shaped run (twelve keys, `unlisted` never appears) and for a bench-7-shaped run (seven keys) from the same tree.
2. **Arm files** (format: `benchmark/arms/README.md`; model: `benchmark/arms/final.arm`):
   - `benchmark/arms/bench7-always.arm`: name `bench7-always`; `quorum_exec_block true`, `quorum_exec_block_starved_rounds 0`, `vote_queue_fix true`, `digest_order_hold true`, `epoch_record_collect_past_uncertified true`, `epoch_record_conflict_halt true`, `epoch_record_recertify true`; no host step.
   - `benchmark/arms/bench7-adaptive.arm`: name `bench7-adaptive`; identical except `quorum_exec_block_starved_rounds 4`.
   - Bench 6's arm files stay in the tree (they document what ran) but must be REFUSED for a bench-7 build with a clear line, never applied as a silent no-op: where the arm tool or the deploy validates an arm file's keys against the switch list, a key not in the live list is an error naming the key and the file. `benchmark/tests/test_params_apply.py` and the arm-file tests that walk every `*.arm` in the directory must still pass: mark the bench-6 arm files' build generation in a way the tests and the tool both read (a header line in the arm file such as `build bench6`, a subdirectory `arms/bench6/`, or the second switch file of item 1), and say which.
3. **The readback and the provenance pass**: with the seven-key list, a `node switches` line that carries all seven is complete; a line with an extra key the list does not know is reported (a note, not a failure: the node may gain switches); a line missing a listed key is a failure, as today. `params-apply.sh --arm-file benchmark/arms/bench7-always.arm --print-state` and the same for the adaptive file must print the state and exit 0; the deploy's `--print-prestart` for each arm writes the seven keys (`NOV=7` in bench 6's terms: check what that counter is and report the line).
4. **`benchmark/arms/MANIFEST-FIELDS.md`**: the switch set of a manifest is that of its build; document it. (HB-1 adds `node_build` and `storage_engine` to the same file before you: add your part below it.)

## Files you own

`benchmark/arms/switches.tsv` (and a second switch file if you add one), `benchmark/arms/bench7-always.arm`, `benchmark/arms/bench7-adaptive.arm`, the bench-6 arm files only for the generation marker of item 2, `benchmark/arms/README.md`, `benchmark/arms/MANIFEST-FIELDS.md` (your section), `benchmark/config.sh` (the switch-key list only), `benchmark/bench-lib.sh` (`bench_switch_readback` and what it calls, nothing else: HB-1 edited other parts of this file), `benchmark/tools/params-apply.sh`, `benchmark/report/provenance.py` (the switch-row source only: a unit fixed its arm-begin logic today, commit 02275df: read that commit first and keep its tests green), `benchmark/tests/test_params_apply.py`, `benchmark/tests/test_report_provenance.py`, `benchmark/tests/test_node_image.py` (only where it pins `BENCH_NODE_SWITCH_KEYS` equal to `switches.tsv`), `benchmark/tests/test_launch.py` and `test_run1_rehearsal.py` only where they pin the twelve-key list, and your cases in `benchmark/tests/check_mutations.py`.
Not yours: `benchmark/launch/*` (the env file for bench 7 is another unit's), `benchmark/tools/arms-summary.py` and `log-shapes.txt` (HB-3's), `benchmark/report/make_bundle.py`.

## Tests and gates

Your modules green; every existing bench-6 test green with its expectations untouched (list any you had to change and why); `bash -n`, `shellcheck -S warning`, py_compile, the 3.9 grammar check; `python3 -m unittest discover -s benchmark/tests 2>&1 | tail -5` once at the end (it takes 25 to 45 minutes on this host: start it when your own modules are green and do other checks meanwhile).
Mutation anchors by hand, reported verbatim: accept an arm key that is not in the live list; make a missing listed key on the `node switches` line pass; let the bench-7 list leak into a bench-6 run's provenance check.

## Hand back

As the rules say, plus: how a run's switch set is chosen (the rule in five lines); the two arm files verbatim; the refusal line for a bench-6 arm on the bench-7 list; the `--print-state` output of both arms; every test you changed and why; the mutation anchors with the test each fails.
