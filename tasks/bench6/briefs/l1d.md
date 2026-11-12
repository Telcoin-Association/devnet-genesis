# L1d — `benchmark/benchmark-deploy.sh`: a fleet with more than one machine type (step 0, step 2, the plan)

You are unit **L1d** of the bench-6 program. Read `tasks/bench6/briefs/l-common.md` first (rules, design, the orchestrator's decisions, facts), then the design's Summary, §1 "The VM and its disk", "What the manifest records about the shape" and "Restarts, stops and re-creates", §2.2, §2.3 ("Step 0 and the plan", "Step 2"; NOT step 3, step 7 or the dry path's local-SSD lines: those are L1c's), §2.9 and §2.10. Nothing else of the design.
Checkpoint: `tasks/checkpoint-bench6-L1d.md`.

## You own (and write nothing else)
`benchmark/benchmark-deploy.sh` and the new `benchmark/tests/test_node_deploy.py`.
`benchmark/config.sh` (L1a, done: it gives you `NODE_MACHINE_TYPES[]`, `NODE_DATADIR_LSSD[]`, `BENCH_CREATE_MACHINE_TYPE`, `BENCH_NODE_ZONES`) and `benchmark/bench-lib.sh` (L1b, done) are read-only for you. If you need a change there, stop that item and describe the hunk in your hand-back.

## Sections (checkpoint after each)
1. **Read**, in ranges (grep first; never the whole file): step 0's `machine_type_check`, `zone_fallback_check`, `region_needs`, `quota_check`, `machine_vcpus` and the `fleet` line; step 2's create call, `create_failed_names`, `create_fail_log`, the stockout rounds, `zone_fallback_record`, `zones.env`, and where `instances[]` is written into the manifest; `print_plan`'s lines for steps 0 and 2; `common/create-instances.sh:150-190` (read-only: the argv you must mirror); `benchmark/benchmark-probe.sh:490-505` (the live-proven create of a `-lssd` VM).
2. **Helpers**: `node_machine_type <index>`, `machine_groups` (distinct types in index order), `type_zones <type>`; `machine_vcpus` strips a trailing `-lssd`.
3. **Step 0 and the plan**: the type check once per group over that group's zones; each fallback zone checked against the moved node's own type; `region_needs` one line per node; for each node with `NODE_DATADIR_LSSD=1` the `LOCAL_SSD_TOTAL_GB` line as §2.3 gives it; a C4 node's CPU quota "not checked" with the reason (l-common's quota fact; use what L1b's hand-back says about `bench_cpu_quota_metric`, quoted in the orchestrator's prompt); the `fleet` line for several groups. One group (every knob unset, or one type for all): today's calls and today's text, byte for byte.
4. **Step 2, the create** (l-common decision 1, design §2.2 path B):
   - one group and it is not `-lssd`: today's single `create-instances.sh` call, with no extra variable in its environment;
   - otherwise one `create-instances.sh` call per non-`-lssd` group with `BENCH_CREATE_MACHINE_TYPE=<type>`, and `bench_create_node <index>` for each `-lssd` node: the argv of `create-instances.sh:166-185` for that node with `--machine-type=<its type>` and `--maintenance-policy=TERMINATE`, printed through `bench_run` before it runs, behind the live guard, failing with the same `Failed to create instance <name> - See <file> for details` line so that the stockout rounds, `create_failed_names` and `create_fail_log` stay shared;
   - `zone_fallback_record` names the node's own type; with `BENCH_NODE_ZONES` set, `zone_overrides[]` and its note are recorded once (§2.8).
   The dry path shares no code with the live create: the live `gcloud` sits behind an explicit guard on the line before it.
5. **Tests** in `test_node_deploy.py` (model: how `test_launch.py`, `test_gate.py` and `test_node_shapes.py` run drivers in a sandbox with shims):
   - every knob unset: the dry plan (`BENCH_RUN_ID=<fixed> benchmark-deploy.sh`), `--print-prestart <inst>` for every instance, and the recorded `gcloud` argv of step 2 are identical to the base's (`git show ae43747:` for `benchmark-deploy.sh`, `config.sh`, `bench-lib.sh` into a second sandbox);
   - option (e)'s three types: two `create-instances.sh` calls (c3-standard-8: indices 0, 1, 10; c3-highcpu-8: 7, 8) and six `bench_create_node` creates, each node with its own zone, type and description; together exactly eleven creates, none twice;
   - the argv-parity test: for one `-lssd` node, the argv `bench_create_node` records equals the argv the REAL `create-instances.sh` would record for that node (run it with `BENCH_CREATE_MACHINE_TYPE` set to the `-lssd` type in a sandbox) except `--maintenance-policy`; so a later change in `common/` that the bench copy misses fails;
   - a stockout of one `-lssd` node moves it to its fallback zone and re-creates only it; a fallback zone that lacks the node's type is reported by step 0;
   - the per-node quota lines for a mixed C3/C4 fleet and the C4 "not checked" text; `LOCAL_SSD_TOTAL_GB` for the local-SSD nodes;
   - `zone_overrides[]` in the manifest with `BENCH_NODE_ZONES`;
   - every shim prints `REACHED` and exits 9 on a create or delete; every dry run asserts zero `REACHED`.
6. **Gates**, each with a log ending `EXIT=<rc>`: `bash -n`, `shellcheck -S warning benchmark/benchmark-deploy.sh`; py_compile and the 3.9 grammar check; `test_node_deploy`, `test_node_shapes`, then the modules that run the deploy driver: `test_launch test_gate test_run1_rehearsal test_host_probe test_obs test_finalize_modes test_keygen test_network_config test_node_image test_admission_gate test_iap_retry test_tunnel test_repo_hygiene` (one `discover -s benchmark/tests -p <module>.py` each; report counts). Bash 3.2 portability applies.
7. **Mutation anchors**: at least six, by hand, reverted, verbatim with the failing test (for example: `machine_vcpus` without the strip; `region_needs` back to nodes × `MACHINE_TYPE`; `zone_fallback_check` against `MACHINE_TYPE`; `bench_create_node` with `MIGRATE`; an `-lssd` node also sent through `create-instances.sh`; the live guard before the create removed).

Final answer: at most 40 lines.
