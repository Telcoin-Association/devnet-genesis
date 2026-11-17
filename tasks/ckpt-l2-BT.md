status: done
unit: BT
worktree: /home/drtnarg/coding/telcoin/dg-l2 (l2/launch-2 @ 46db2fc, main 8abb488 merged); scratch /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/BT/
completed:
- step 0 (2026-11-17T20:43:06Z): read agent-rules, contract s8 + A-8, ckpt-l2-G1, G1 permod.sh. Note: dg-l2 has an uncommitted devnet-observability.sh edit (not BT's; untouched).
next: step 1 reproduce the five modules
- step 1 (2026-11-17T20:47:02Z): reproduced in dg-l2 (runner scratch/BT/permod.sh, logs scratch/BT/repro.d/):
  test_node_shapes 17 tests FAILED (failures=5) first: test_node_shapes.py:290 test_create_argv_equals_the_base (argv differs)
  test_node_deploy 17 FAILED (failures=13) first: test_node_deploy.py:307 test_dry_plan_equals_the_base (got image sha256:5257e7.. = bench pin, want base sha256:0aec3e7.. = root's new image)
  test_local_ssd_deploy 20 FAILED (failures=23) first: test_local_ssd_deploy.py:162 (same image diff; uses tnd.Sandbox's base tree)
  test_host_probe 39 FAILED (errors=32) all: test_node_image.py:504 scripts_ref AttributeError (root ref is the PLACEHOLDER marker)
  test_node_image 194 FAILED (errors=108) all: test_node_image.py:504 scripts_ref AttributeError
  facts: root config.sh identical at ae43747 and main; base bench config's next line after the root source line = main's ('# The release-signing gate').
  choice: scripts_ref = last 40-hex TN_NODE_SCRIPTS_REF export in root+bench text (source order); base sandboxes: insert the lines today's benchmark/config.sh has right after its root source line and the base has not (empty on main) -> helper with_bench_pins in test_node_deploy.py, reused by test_node_shapes; test_local_ssd_deploy inherits it via tnd.Sandbox (no edit).
next: step 2 edit
- step 2 (2026-11-17T20:52:48Z): edited dg-l2 benchmark/tests/test_node_image.py (scripts_ref: last TN_NODE_SCRIPTS_REF export across root+bench config, must be 40-hex), test_node_deploy.py (with_bench_pins helper + make_tree base uses it for benchmark/config.sh), test_node_shapes.py (import test_node_deploy as tnd; base copy through tnd.with_bench_pins). test_local_ssd_deploy.py: no edit (uses tnd.Sandbox). py_compile rc 0 x3.
  scratch copies: scratch/BT/s2 (clone --shared of l2/launch-2 + my 3 test files, root ref = dummy 0123..4567, submodules copied w/o .git), scratch/BT/main (clone --shared -b main = 8abb488, same submodule treatment). dg-l2 tn-node-deployment is unpopulated (as in the copies).
  state 1 (placeholder) partial: node_deploy OK 17, local_ssd_deploy OK 20, host_probe OK 39, node_shapes 4 failures = test_declare_p_equals_the_base on BENCH_CONTRACTS_SRC_DIR (tn-contracts vs tn-contracts-devnet-relaunch; from main's bench contracts default, not a pin) -> check on main. node_image running.
next: finish state 1, state 2 in scratch/BT/s2, then whole suite main vs branch
- step 3 (2026-11-17T20:58:51Z): five modules, both root states (logs scratch/BT/fixed-s1.d, fixed-s2.d):
  state 1 (PLACEHOLDER, dg-l2): node_shapes 17 FAILED(failures=4: test_declare_p_equals_the_base x4 variants, BENCH_CONTRACTS_SRC_DIR) | node_deploy 17 OK | local_ssd_deploy 20 OK | host_probe 39 OK | node_image 194 OK (skipped=12)
  state 2 (dummy 40-hex, scratch/BT/s2): identical results.
  main (scratch/BT/main, 8abb488, unmodified tests): node_shapes 17 FAILED(failures=4) same 4 tests, same BENCH_CONTRACTS_SRC_DIR diff -> fails on main as well (main's bench contracts default vs base ae43747), not BT's.
next: step 4 whole suite: scratch/BT/main -> scratch/BT/suite-main.txt, then dg-l2 -> scratch/BT/suite-branch.txt (one background job, sequential)
- step 4 started (2026-11-17T21:03:02Z): whole suite running in background (one job: scratch/BT/main then dg-l2), log scratch/BT/suites.log ends with SUITES_DONE; per-module lines in scratch/BT/suite-main.txt and scratch/BT/suite-branch.txt (each ends ALLDONE), logs in suite-*.d/. Branch HEAD at start: 16d6593 (+ BT's 3 test edits).
  main-correctness check: with main's files, scripts_ref() = root's d9446f7 and with_bench_pins(base) == base (identity) -> the edits change nothing on main as it is today.
  diff: git diff --stat -- benchmark/ = 3 files, 20+/4- (test_node_deploy 13, test_node_image 7, test_node_shapes 4); test_local_ssd_deploy.py unchanged.
  resume: if SUITES_DONE is in suites.log, build the table from the two txt files; else wait for it (never start a second copy). Calls used ~53/60.
- step 4 done (2026-11-17T21:45:44Z): whole-suite table (module tests main/branch, results):
  admission_gate           24/24   main=OK             branch=OK
  archive                  18/18   main=OK             branch=OK
  arms_summary             35/35   main=OK             branch=OK
  blast_argv               85/85   main=OK             branch=OK
  block_rate                7/7    main=OK             branch=OK
  cadence_model             6/6    main=OK             branch=OK
  cert_rate                14/14   main=OK             branch=OK
  certification            24/24   main=OK             branch=OK
  collect_retry             6/6    main=OK             branch=OK
  finalize_modes           51/51   main=OK             branch=OK
  fund_short                7/7    main=OK             branch=OK
  gate                     20/20   main=OK             branch=OK
  host_probe               39/39   main=OK             branch=OK
  iap_retry                22/22   main=OK             branch=OK
  keygen                   30/30   main=OK             branch=OK
  latency_matrix           28/28   main=OK             branch=OK
  launch                   84/84   main=OK             branch=OK
  local_ssd                34/34   main=OK             branch=OK
  local_ssd_deploy         20/20   main=OK             branch=OK
  log_filter               44/44   main=OK(s=16)       branch=OK(s=16)
  network_config           27/40   main=OK             branch=OK
  node_deploy              17/17   main=OK             branch=OK
  node_image              194/194  main=OK(s=12)       branch=OK(s=12)
  node_shapes              17/17   main=FAIL(f=4)      branch=FAIL(f=4)
      branch first: FAIL: test_declare_p_equals_the_base (test_node_shapes.KnobUnsetTests.test_declare_p_equals_the_base) (variant='unset')
      main first:   FAIL: test_declare_p_equals_the_base (test_node_shapes.KnobUnsetTests.test_declare_p_equals_the_base) (variant='unset')
  obs                      45/45   main=OK             branch=OK
  params_apply             95/95   main=OK(s=2)        branch=OK(s=2)
  persist_sampler          59/59   main=OK(s=3)        branch=OK(s=3)
  probe                    34/34   main=OK             branch=OK
  propose_latency           6/6    main=OK             branch=OK
  pull_logs                61/61   main=OK(s=1)        branch=OK(s=1)
  recovery                 39/39   main=OK             branch=OK
  repo_hygiene             13/13   main=OK             branch=OK
  report_bundle            94/94   main=OK(s=8)        branch=OK(s=1)  <-- DIFFERS
  report_kpis              60/60   main=OK(s=3)        branch=OK(s=3)
  report_provenance        52/52   main=OK             branch=OK
  report_scrub             41/41   main=OK             branch=OK
  report_windows           26/26   main=OK             branch=OK
  run1_rehearsal           12/12   main=OK             branch=OK
  stage_latency            19/19   main=OK             branch=OK
  stall_scan                5/5    main=OK             branch=OK
  teardown_local_gate      91/91   main=OK             branch=OK
  tunnel                   25/25   main=OK             branch=OK
  txgen_probe               4/4    main=OK             branch=OK
  v2_launch_edit            6/6    main=OK(s=6)        branch=OK(s=6)
  2026-11-17T20:58:54Z
  branch HEAD before: 06a6ed8 shim: emulators for deploy steps 9-14
  branch HEAD after: cbfc73d shim: emulators for deploy steps 15-20; the full twenty-step rehearsal runs clean
  2026-11-17T21:45:34Z
