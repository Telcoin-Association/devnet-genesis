# L1a — `benchmark/config.sh`: per-node machine types, zone overrides, the local-SSD data-directory knob

You are unit **L1a** of the bench-6 program. Read `tasks/bench6/briefs/l-common.md` first (it names the rules, the design, the orchestrator's decisions and the facts), then the design's Summary, §1 "The VM and its disk" and "What the manifest records about the shape", §2 (the knob table), §2.1 and §2.10. Nothing else of the design.
Checkpoint: `tasks/checkpoint-bench6-L1a.md`.

## You own (and write nothing else)
`benchmark/config.sh` and the new `benchmark/tests/test_node_shapes.py`.

## Sections (checkpoint after each)
1. **Read** `config.sh` in ranges: the fleet block (`:80-170`), `zones.env` (`:450-470`), the array-length checks (`:505-515`), the 0/1 loop and the shape refusals (`:610-645`), the last block. Note every place that counts or indexes `INSTANCE_NAMES`.
2. **`BENCH_NODE_MACHINE_TYPES`** → `NODE_MACHINE_TYPES[]` (design §2.1, first bullet), with every refusal the design lists, and the e2/n1 × hyperdisk refusal per distinct type.
3. **`BENCH_NODE_ZONES`** → rewrites `ZONES[index]` before the `zones.env` block (third bullet).
4. **`BENCH_NODE_DATADIR_LSSD`** → `NODE_DATADIR_LSSD[]` (second bullet): `0|1`; with `1` at least one node's type ends in `-lssd` and the caller must have set `BENCH_FLEET`; a `-lssd` node with the knob at 0 is allowed.
5. **`BENCH_CREATE_MACHINE_TYPE`** (fourth bullet): the internal narrowing for one `common/create-instances.sh` call. Under decision 1 of l-common it is used for the non-`-lssd` groups only, but the knob itself does not know that: it narrows to whatever type it is given.
6. **Tests** in `test_node_shapes.py` (model: how `benchmark/tests/test_launch.py` and `test_gate.py` source `config.sh` in a sandbox; `python3 -m unittest discover -s benchmark/tests -p test_node_shapes.py` must work):
   - every knob unset: `declare -p` of every variable equals the base config's (`git show ae43747:benchmark/config.sh` into the sandbox) except the two new arrays, which are `MACHINE_TYPE` × 11 and `0` × 11;
   - each refusal, one by one, with its message;
   - option (e)'s values (l-common, last fact) give the expected arrays, and `ZONES` is untouched;
   - a mixed C3/C4 value with one `BENCH_NODE_ZONES` move;
   - `BENCH_CREATE_MACHINE_TYPE`: the sparse `INSTANCE_NAMES`, each surviving index keeping its zone, role, name and address; then the REAL `common/create-instances.sh` run in the sandbox with `CONFIG_FILE` at the changed config and a recording `gcloud` shim (answers "not found" to `instances describe`, records `instances create`, prints `REACHED` and exits 9 on anything else that creates or deletes): one create per surviving node, with that node's own zone, `--machine-type` and description; and with every knob unset the recorded argv equals the base config's.
   - `zones.env` still wins over `BENCH_NODE_ZONES` (a stockout move after an override keeps both).
7. **Gates**, each with a log ending `EXIT=<rc>`: `bash -n` and `shellcheck -S warning benchmark/config.sh`; py_compile and the 3.9 grammar check of your test; `test_node_shapes`; then the modules that source `config.sh`: `test_launch test_gate test_repo_hygiene test_network_config test_node_image test_finalize_modes test_keygen test_obs test_probe test_params_apply test_teardown_local_gate` (one `discover -p` each; report counts). Bash 3.2 portability applies (`/bin/bash` first on PATH once, as the bench-5 rules say).
8. **Mutation anchors**: at least five, applied by hand and reverted, reported verbatim with the failing test (for example: an index past the last node accepted; a duplicate index accepted; the `unset` of the other types' entries dropped; `BENCH_NODE_DATADIR_LSSD=1` accepted without `BENCH_FLEET`; `BENCH_NODE_ZONES` applied after the `zones.env` block).

Final answer: at most 35 lines.
