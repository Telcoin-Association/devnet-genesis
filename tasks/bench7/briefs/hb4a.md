# HB-4a — the orchestrator's run scripts for bench 7: one chained launch, a watch that ends, an export that checks first

Unit: `HB-4a` (harness unit, opus). Rules: `tasks/bench7-agent-rules.md` ("Harness units" and the common sections). Checkpoint: `tasks/checkpoint-bench7-HB-4a.md`. Budget: under 200k tokens.
You write ONLY under `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench7/` (the scripts and tests below). You do not edit anything under `benchmark/` (four bundles are about to be launched from it and a launch refuses a dirty `benchmark/` tree), nothing under `tasks/bench6/`, and you do not commit.
Nothing you run may reach the cloud: no real `gcloud`, no real `launch.sh` segment. Every test uses shims on `PATH` and a sandbox copy of what it needs.

## Why (three defects that cost or endangered a fleet run in bench 6; `tasks/bench6-handoff-2.md` §4.6 and §6.4)

1. **A fleet idled between deploy and blast.** Each segment was launched by hand from the session; run 3b's fleet idled 46 minutes when the session hit its limit after `deploy12`. A deploy must only be launched together with what follows it.
2. **The fleet-health watch never ended and then watched the wrong fleet.** `tasks/bench6/orch-fleet-health.sh --watch … --until-file` only ends on a line `== arms rc=`; runs 2 to 3b ran `blast15`, so the watch ran on, and since it finds instances by NAME (`bench-validator-NN`) it reported the next run's fleet under the old run id.
3. **A metric export was incomplete.** Run 3's export lacked one validator's `tn_primary_vote_stage_seconds` series; nobody checked before the teardown.

## What to build (all new files under `tasks/bench7/`; bench 6's scripts stay as they are)

### 1. `tasks/bench7/orch-run-chain.sh` — deploy12 → idle checks → blast15 without a gap

`tasks/bench7/orch-run-chain.sh [--live] <env-file>` (default is a DRY plan: it prints every step it would take and starts nothing; `--live` is required to start anything).
Started detached by the orchestrator (`setsid bash … > log 2>&1 < /dev/null &`), it must survive the session ending.
Steps, each logged as one `CHAIN <step> …` line with a UTC time:
1. Preconditions (both modes): the env file parses the way `benchmark/launch/launch.sh` expects (read its header comment and its `status` segment; do not re-implement its parser: call `launch.sh --dry-run <env> deploy12` and `… blast15` and require rc 0 from both), the run id is new (`benchmark/results/<run>/` absent or empty of a manifest), `git status --porcelain -- benchmark/` clean apart from `benchmark/launch/bench5/`, no driver running.
2. `launch.sh <env> deploy12`; wait for `^== deploy12 rc=` in the log the launcher names, with a deadline (`CHAIN_DEPLOY_DEADLINE_SECS`, default 5400). Not rc 0, or `BENCH_DEPLOY_RESULT rc=0 last_step=12` missing from the log: stop, `CHAIN stop reason=deploy …`, exit 10. Nothing is torn down by this script, ever.
3. The idle checks against the bench Prometheus forward (`http://localhost:19090`, up after `deploy12`), each with a bounded `curl --max-time 20`, retried for up to `CHAIN_IDLE_WAIT_SECS` (default 300) because gauges need a scrape or two:
   - every node of the manifest is scraped: `count(up{network="bench"} == 1)` covers the 11 nodes (read how `tasks/bench6/orch-prom-read.py` and handoff §4.4 select the bench nodes; use the same label logic);
   - the modes: 10 `cvv_active`, 1 `observer` (`tn_node_mode`);
   - **the switches the run asked for are what the nodes report**: expected values from `benchmark/results/<run>/manifest.json` (`.param_arms[0].switches`, name → value as strings; a bool `true` is gauge 1), compared per node with `tn_node_switch{name=…}`; every expected switch on all 11 nodes with the expected value, and no node reporting a switch on that the manifest does not list. No switch name is hard-coded in the script. How the gauge exposes an integer switch (bench 6: `quorum_exec_block_starved_rounds`) — read `tasks/bench6/orch-prom-read.py` and the bench-6 node commit 9c91263e7 (`git -C /home/drtnarg/coding/telcoin/telcoin-network-b6 show 9c91263e7 -- crates/node/src/metrics.rs`) and handle both;
   - the storage engine the manifest names (a key another unit adds; read it if present, print `engine=<value or unknown>`, never fail on its absence);
   - `HOST_PROBE_SUMMARY … uniform=yes` present in the deploy log (a note if absent, not a stop).
   A failed check: `CHAIN stop reason=idle-check <which> …`, exit 11, the fleet is left up and the line says so in capitals (`FLEET IS UP AND IDLE: decide teardown or blast by hand`).
4. All checks pass: `launch.sh <env> blast15` AT ONCE (the same second the checks pass), then start the watch of item 2 below beside it, wait for `^== blast15 rc=` (`CHAIN_BLAST_DEADLINE_SECS`, default 9000), report `BENCH_DEPLOY_RESULT rc=0 last_step=15` present or not, and end with `CHAIN done rc=<n>`. It does NOT tear down, export or archive: those stay separate, deliberate calls.
- Trap to respect: the launcher refuses when a driver's file name appears in a running command line (`pgrep -f`); your script's own command line and its children's must not contain `benchmark-deploy.sh`, `benchmark-blast.sh`, `params-apply.sh`, `make_bundle.py` and the like. A test proves the chain script's `ps` line would not match any pattern in `launch.sh`'s `PAT=` list.
- Dry and live never share a code path: the `launch.sh` calls sit behind an explicit `[ "${LIVE}" = "1" ] || return` guard on the line before them.

### 2. `tasks/bench7/orch-fleet-health.sh` — a copy of bench 6's watch with the two defects fixed

- `--until-file` ends the watch on ANY `^== <segment> (rc=|LEFT_RUNNING )` line, and `--max-secs <n>` (default 3 h) ends it regardless.
- Instances are taken from the run's own manifest AND checked to belong to the run before any read: `gcloud compute instances describe … --format='value(labels)'` (or one `instances list --filter` call per watch round) must show the run's label (read `benchmark/benchmark-deploy.sh` or `benchmark/config.sh` for the label key the deploy sets, e.g. `grep -n 'labels' benchmark/*.sh | head`); an instance of the same name with another run's label is reported as `foreign` and not read; when no instance of the run is left, the watch ends with `FLEET_HEALTH run=<run> gone`.
- Keep the output line formats of the original.

### 3. `tasks/bench7/orch-prom-export.py` — the export with a completeness check first

A copy of `tasks/bench6/orch-prom-export.py` that, before exporting, runs `count by (node) (<metric>)` (or the repo's node label) for a short list of must-have series (`tn_primary_vote_stage_seconds_count`, `tn_node_switch`, the persist/commit histograms the bench-6 units read; take the list from what `benchmark/private/bench6-r20261113-1351/*/scripts/*.py` actually query — grep for metric names, keep the twenty most used; metric names that no longer exist on the new node build are reported, not fatal), prints one `EXPORT_CHECK metric=<m> nodes=<n>/<expected> missing=<list>` line each, and exits 3 before exporting when a must-have series that exists on some node is missing on another, unless `--allow-missing` is given. After the export it prints `EXPORT_DONE metrics=<n> series=<n> nodes=<n>`.

### 4. Tests: `tasks/bench7/tests/test_orch_scripts.py` (python 3.9 grammar, `unittest`)

Sandbox: a temp dir with a fake `launch.sh` (records its argv, writes a log with the rc line the test asks for), a fake `curl` answering Prometheus queries from fixture JSON, a fake `gcloud` (prints `REACHED` and exits 9 unless the test arms it with fixture output), a fixture manifest. The scripts take their roots from environment variables with the real paths as defaults (`CHAIN_ROOT`, `CHAIN_PROM_URL`, …) so the tests never touch the real tree.
Cases at least: the dry plan starts nothing (zero launcher and gcloud hits); a deploy rc ≠ 0 stops before any check; a missing switch on one node stops with exit 11 and never launches the blast; an unexpected switch on stops; all checks green launches `blast15` exactly once and the watch beside it; the deadline paths; the watch ends on `== blast15 rc=0`, on `--max-secs`, and reports a same-name instance with another run's label as foreign without reading it; the export refuses an incomplete must-have series and passes with `--allow-missing`.
Mutation anchors (apply by hand, report verbatim): invert the `--live` guard; drop the per-node comparison of one switch; match only `== arms` in the watch; skip the label check; skip the export's refusal. Each must fail a named test.

## Gates

`bash -n` and `shellcheck -S warning` on the two shell scripts; `python3 -m py_compile` and the 3.9 grammar check the harness uses (`grep -rn "feature_version\|ast.parse" benchmark/tests/test_repo_hygiene.py | head` shows it) on the python files; `python3 -m unittest tasks/bench7/tests/test_orch_scripts.py -v` (run it from the repo root; make the module importable without a package `__init__` if that is simpler).
Hygiene as the harness rules say (no literal IPv4 but 127.0.0.1, the project name only where bench 6's originals already pass it as `--project tn-devnet` in an orchestrator script — keep it in one variable at the top).

## Hand back

As the rules say, plus: each script's usage line; every `CHAIN …`, `FLEET_HEALTH …`, `EXPORT_…` line format verbatim; the must-have metric list; the mutation anchors with the test each one fails; what the orchestrator must still check by hand before a live chain (anything the script cannot know).
