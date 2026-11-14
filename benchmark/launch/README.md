# Bench 6 launchers

A bench run is a chain of long driver calls against a GCP fleet: the deploy takes about 46 minutes, the teardown about 35, and run 1's arm walk about 7 hours.
Each call runs as a detached segment that survives the session that started it, with its own pid file and log.
`benchmark/launch/bench5/` holds the hand-written bench-5 launchers these replace (untracked originals, kept for reference).

| file | what it is |
|---|---|
| `launch.sh` | starts one segment of a run detached and returns at once; `status` lists the run's segments |
| `run-arms.sh` | the run-1 arm walk: what the `arms` segment runs |
| `bench6-run1.plan` | the default arm walk (plan W4), edited by hand at gate G2 |
| `bench6-run1.env` | run 1, the arms run |
| `bench6-run2.env` | run 2, the headline |
| `bench6-probe.env` | the one-VM GCE probe |
| `bench6-run1-lssd.env` | run 1b, the local-SSD deployment: run 1's env file plus four shape knobs |
| `bench6-run1-lssd.plan` | run 1b's walk: three of run 1's arms |

Tests: `benchmark/tests/test_launch.py` (fake drivers and shims in `benchmark/tests/fixtures/launch/`).

## Env files

An env file is the whole configuration of a run's segments.
`launch.sh` parses it and never sources it:

- one `KEY=value` per line; `#` comments and blank lines are ignored, and a directive has no trailing comment;
- keys start with `BENCH_`, `RUN_ARMS_`, `PARAMS_APPLY_` or `LAUNCH_`;
- a value is bare (no spaces, no quotes) or wholly inside `"..."` or `'...'`, and never holds `$`, a backquote or a backslash;
- a key appears once.

Before it exports the file, `launch.sh` drops every `BENCH_*`, `RUN_ARMS_*`, `PARAMS_APPLY_*` and `LAUNCH_*` variable of the shell that runs it, so nothing from an operator's shell reaches a driver.
That replaces the `unset` lines of the bench-5 launchers.

The files ship with placeholders in angle brackets: `<run-id>`, `<image-digest>`, `<node-sha>` and `<txgen-sha>`.
A launch refuses any value that still holds one.
The orchestrator fills them at the gate, then either commits the file (the harness sha in each log then names the exact configuration) or fills a copy outside `benchmark/`, for example `tasks/bench6/<run>.env`, and launches with the copy.
A filled file left uncommitted inside `benchmark/` makes the harness tree dirty, and `launch.sh` refuses to start.

Knobs the files set, and who reads them:

| knob | run 1 | run 2 | probe | read by |
|---|---|---|---|---|
| `BENCH_RUN_ID` | `<run-id>` | `<run-id>` | `<run-id>` | every driver |
| `BENCH_DOCKER_IMAGE` | `...adiri@sha256:<image-digest>` | same | | config.sh |
| `BENCH_DOCKER_IMAGE_EXPECT_DIGEST` | `sha256:<image-digest>` | same | | bench-lib.sh image gate |
| `BENCH_NODE_EXPECT_SHA` | `<node-sha>` | same | | bench-lib.sh image gate |
| `BENCH_NODE_EXPECT_FORKS` | `subsecond-from-genesis` | same | | bench-lib.sh image gate |
| `BENCH_TXGEN_SHA` | `<txgen-sha>` | same | | config.sh |
| `BENCH_NODE_BOOT_IMAGE` | bench 5's `ubuntu-2404-noble-amd64-v20261105` | same | same | config.sh |
| `BENCH_ARM_FILE` | (unset: A0 is the fleet as deployed) | `benchmark/arms/final.arm` | | config.sh, deploy step 7 |
| `BENCH_PERSIST_SAMPLER` | `1` | `1` | | config.sh |
| `BENCH_TAIL_SCAN_SECS` | `180` (run-arms gives it to M16 only) | `180` | | config.sh |
| `BENCH_LIGHT_START_DELAY_SECS` | `150` | `150` | | config.sh |
| `BENCH_LANDINGS_SAMPLE` | `100` | `100` | | config.sh |
| `BENCH_CHAOS` | `0` | `1` | | config.sh |
| `BENCH_LIGHT_LOAD` | `0` | `1` | | config.sh |
| `BENCH_DURATION_SECS` | | `2400` | | config.sh |
| `BENCH_LIGHT_SENDERS` | | `"8 600"` | | config.sh |
| `BENCH_LIGHT_WINDOWS` | | `"16 4"` | | config.sh |
| `BENCH_TEARDOWN_SKIP_ARCHIVE` | `1` | `1` | | benchmark-teardown.sh |
| `RUN_ARMS_MAX_QUEUED` | `1000` | | | run-arms.sh |
| `LAUNCH_PROBE_BIN` | | | `benchmark/work/probe-bin/mdbx-writeback-probe` | launch.sh |
| `LAUNCH_PROBE_ARMS` | | | (commented out: all arms; `core` is the short run) | launch.sh |

`bench6-run1-lssd.env` (run 1b) sets every run-1 knob to run 1's value and adds the four shape knobs and `RUN_ARMS_PLAN` listed under "Run 1b: the local-SSD deployment".
`test_launch.py` checks that every key an env file sets is read by `benchmark/config.sh` or a driver.

## launch.sh

```
benchmark/launch/launch.sh [--dry-run] <env-file> <segment> [segment args...]
benchmark/launch/launch.sh <env-file> status
```

| segment | driver call (from the repo root, R = the env file's run id) | gcloud token | last driver tag |
|---|---|---|---|
| `probe` | `benchmark/benchmark-probe.sh all --bin <LAUNCH_PROBE_BIN> [--arms <LAUNCH_PROBE_ARMS>]` | yes | `DOWN_OK` or `DOWN_INCOMPLETE` |
| `deploy12` | `benchmark/benchmark-deploy.sh --yes --with-contracts --to 12` | yes | `BENCH_DEPLOY_RESULT` |
| `arms` | `benchmark/launch/run-arms.sh` | yes | `ARMS_DONE`, or `ARMS_STOPPED` then `ARMS_RESUME` |
| `blast15` | `benchmark/benchmark-deploy.sh --yes --from 13 --to 15` | yes | `BENCH_DEPLOY_RESULT` |
| `step15` | `benchmark/benchmark-deploy.sh --yes --from 15 --to 15` | yes | `BENCH_DEPLOY_RESULT` |
| `teardown-dry` | `benchmark/benchmark-teardown.sh --run R` | yes | `TEARDOWN_DONE ... dry_run=1` |
| `teardown` | `benchmark/benchmark-teardown.sh --run R --yes` | yes | `TEARDOWN_DONE` |
| `archive` | `benchmark/tools/archive-run.sh --run R` | yes | `== archive-run run=R rc=` |
| `reindex` | `benchmark/benchmark-teardown.sh --run R --reindex` | no | |
| `bundle` | `python3 benchmark/report/make_bundle.py --run R` | no | |
| `arms-summary` | `python3 benchmark/tools/arms-summary.py --run-dir benchmark/results/R` | no | |

Segment args go to the end of the driver call: `launch.sh <env> bundle --compare r20261107-1504 --backfill <file>`, `launch.sh <env> arms --from-arm 3`.

It refuses (rc 1, nothing started, no file written):

- an env-file line that breaks the rules above, a placeholder, or a run id that is not `rYYYYMMDD-HHMM`;
- a dirty harness tree: `git status --porcelain -- benchmark/` not empty, leaving out only the untracked `benchmark/launch/bench5/`;
- a segment of the same run still running: a pid file in `tasks/bench6/<run>/` whose process is alive and is one of this run's wrappers (its command line holds `bench6-launch:<run>:`);
- a driver the segment would collide with: `pgrep -f` for the fleet drivers (`benchmark-{deploy,blast,teardown,probe}.sh`, `run-arms.sh`, `params-apply.sh`) before a fleet segment, for `archive-run.sh` or the teardown before `archive`, the teardown before `reindex`, and the tool itself before `bundle` and `arms-summary`; each pattern starts with a bracket class (`[b]enchmark-...`), so it never matches its own text. A test suite running these drivers on the same host counts too;
- for the segments marked "yes" above, a token that `gcloud auth print-access-token` cannot print within `LAUNCH_TOKEN_SECS` (30 s).

A live start runs `nohup setsid bash launch.sh __segment ...` from the repo root with stdin from `/dev/null`.
The detached shell writes its own pid to `tasks/bench6/<run>/<segment>-<UTC>.pid`, logs to the `.log` beside it, prints a header (the harness sha and the exported environment), runs the driver as its child, passes TERM on to it, and ends the log with `== <segment> rc=<n> <UTC>`: rc 0 on success, the driver's rc on failure, 143 after a TERM, 137 when the driver was killed.
The rc line claims an end, so it comes only once nothing of the segment's process group runs; a process that outlives its driver is named instead (Stop and resume, below).
A SIGKILL of the detached shell itself is the one case it cannot cover; `status` then reports the segment as `died (no rc line)`.
Logs and pid files are never overwritten: a second launch in the same second gets a `-2` suffix.

`launch.sh` prints `LAUNCHED segment=<seg> run=<run> pid=<pid> harness=<sha> log=<log>`, the line to wait for and the status command, then returns.
`--dry-run` makes every check except the token, prints the environment and the command, and starts nothing.
`status` prints one `SEGMENT <segment>-<UTC> pid=<pid> state=<state> last: <last log line>` per segment of the run, the state one of `running`, `stopping after <what> (pid <p>)` (a TERM was passed on and the segment is finishing <what>), `ended`, `left running (<pids>)` and `died (no rc line)`.

## run-arms.sh

```
benchmark/launch/run-arms.sh [--plan <file>] [--from-arm <k|name> [--from-step <n>]]
                             [--only-arm <k|name> [--from-step <n>]] [--dry-run]
```

Exit 0 is `ARMS_DONE` (or a dry run), 1 is `ARMS_STOPPED` with the fleet left as it is, 2 a refusal before anything ran (arguments, plan), and 128 plus the signal's number (143 for TERM) is any `ARMS_STOPPED` after a signal.
It needs `BENCH_RUN_ID`, which `launch.sh` exports.
Without `--plan` it walks `RUN_ARMS_PLAN`, and `bench6-run1.plan` when that knob is unset or empty, so an env file can pin its run's plan; `--plan` overrides the knob.

### The plan

One arm per line, in run order: the arm file (a name in `benchmark/arms/`, `.arm` optional, or a path from the repo root), then its steps.
Lines are numbered from 0 for `--from-arm` and `--only-arm`; an arm's name works as well when it is on one line only.

| step | what it is |
|---|---|
| `I` | 5 idle minutes (`RUN_ARMS_IDLE_SECS`), recorded as the mark `idle-<step>` with `params-apply.sh --mark` and `--end-mark` |
| `L` | the floor: 8 senders per blaster at window 16, 60 / 360 / 60 s, light start lead |
| `M4` | 600 x 4, 60 / 360 / 60 s, light start lead |
| `M16` | 600 x 16, 120 / 480 / 180 s, plus the tail scan of `BENCH_TAIL_SCAN_SECS` (180) |
| `M16s` | the short M16: 600 x 16, 120 / 300 / 180 s, no tail scan |

Every blast runs without chaos or lag injection: `benchmark-blast.sh fund --yes`, then `run --yes`, both under the next free `BENCH_RUN_INDEX` (one past every index in the manifest's `blast`, `fund`, `blasts[]` and `blast_runs[]`, the `blast-<i>-*` and `funder-<i>-*` archives, and every index this walk handed out).
`M16@epoch` (or `M16s@epoch`) times the run against the 1,200-s epoch: after the fund, run-arms reads the next boundary with `benchmark/recovery-schedule.py --rpc-url http://localhost:18545 --before-close 1 --downtime 2` (the run's RPC tunnel; `RUN_ARMS_RPC_URL`) and launches the run so that the boundary falls half-way into the mixed phase (`RUN_ARMS_EPOCH_OFFSET_SECS`, 240 s for M16).
The lead it allows is that offset plus the warmup (120), the generator's preamble (`BENCH_PREAMBLE_SECS`, 90) and the blast's start delay (`BENCH_START_DELAY_SECS`, 300, never below the blast's 240-s create floor).
The wait is at most one epoch; past `RUN_ARMS_EPOCH_WAIT_MAX_SECS` (1,500) the run stops.
The blast's own preflight takes some seconds after the launch, so the boundary lands a little before the middle.

The default walk (`bench6-run1.plan`):

| k | arm | steps |
|---|---|---|
| 0 | `a0-control` | I, L, M4, M16 |
| 1 | `p1-mdbx-advice` | M16 |
| 2 | `v-vote` | L, M16 |
| 3 | `v-vote-floor` | L, M16 |
| 4 | `pool-local` | M16@epoch |
| 5 | `pipe` | M4, M16 |
| 6 | `bound` | M4, M16 |
| 7 | `gr150` | I, L, M16s |
| 8 | `a0-prime` | M16 |

Sixteen blasts in all; `--dry-run` prints every command.
`v-vote` and `v-vote-floor` are the two forms of the vote fix (G1): the adaptive one (`quorum_exec_block_starved_rounds 4`) and the always-on one (`0`).
If the image lacks `pipelined_persist`, drop the `pipelined_persist` line from `pipe.arm`, `bound.arm` and `gr150.arm` (arms/README.md), or drop the `pipe` line here.
After a hand edit of the plan, update `DEFAULT_WALK` in `test_launch.py`: `test_the_default_plan` pins `bench6-run1.plan`, and `test_the_real_plan_walks_in_a_dry_run` walks it with `--dry-run`.
An edit that changes the steps or the order of `a0-control`, `p1-mdbx-advice` or `a0-prime` also fails `test_the_lssd_plan` until run 1b's plan follows it.
The tests that address arms by number walk a frozen copy of the eight-arm walk (`tests/fixtures/launch/walk-8.plan`), so an edit of the plan does not move them.

### One arm

Before the first arm, every arm file of the walk goes through `params-apply.sh --arm-file <file> --print-state`, which contacts no node; a refused file stops the walk before anything changes.
Then, per arm:

1. Step 0, the apply: `params-apply.sh --from-config --arm-file <file> --arm <name>`.
   The name is the file's `name` line, or `<name>-r2`, `-r3`, ... when the manifest's `param_arms[]` already records it (a re-applied arm; the arm tool refuses a recorded name).
   The control arm A0 on a fresh fleet changes nothing and restarts nothing: the arm tool records it with `no_restart`.
2. It waits until the `ready=` time of the `ARM_READY` line, which can lie up to 120 s ahead (at most `RUN_ARMS_READY_MAX_WAIT_SECS`, 600).
3. Each step in order, with the health check after each one (below).
4. The close: `params-apply.sh --from-config --close-arm <name>`.

Before a saturated blast (M4, M16, M16s), after its fund, every node's queued pool must be below `RUN_ARMS_MAX_QUEUED` (1,000; 0 turns the gate off).
It reads the pools the way `benchmark-blast.sh` records `pool_at_start`: one bounded query to the run's bench-obs Prometheus through its local forward (`max by (node) (reth_transaction_pool_queued_pool_transactions{network="bench"})`), every `RUN_ARMS_POOL_POLL_SECS` (30) for up to `RUN_ARMS_POOL_WAIT_SECS` (600).
Still high at the deadline stops the run.
Pools it cannot read, or fewer nodes than `results/<run>/nodes.txt` lists, are `unknown`: it keeps polling, and at the deadline goes on with a note, since the blast's own preflight opens the forward again or fails, and its `POOL_AT_START` line records the pools.

### Tags

```
ARMS_START plan=<file> run=<id> arms=<k..k> from_step=<n> <UTC>
ARMS_ARM k=<k> arm=<name> file=<file> steps=<steps>
ARMS_READY arm=<name> ready=<UTC> wait=<s>
ARMS_POOL arm=<name> step=<n> verdict=<ok|high|unknown|off> queued_max=<q> (<node>) read=<n>/<m> limit=<q> <UTC>
ARMS_EPOCH arm=<name> step=<n> boundary=<UTC> launch_at=<UTC> offset=<s> lead=<s>
ARMS_BLAST arm=<name> step=<n> kind=<type> index=<i> attempt=<a> fund_rc=<rc> run_rc=<rc|-> <UTC>
ARMS_RETRY arm=<name> step=<n> kind=<type> index=<i> reason=<...>
ARMS_HEALTH arm=<name> after=<step> verdict=<ok|stop|unknown|off> read=<n>/<m> disk_max=<pct> (<node>) fatal_db=<n> <UTC>
ARMS_STEP arm=<name> step=<n> kind=<apply|I|L|M4|M16|M16s|close> rc=<n> <UTC>
ARMS_DONE arms=<n> blasts=<n> <UTC>
ARMS_STOPPING arm=<name> step=<n> signal=<SIG> after=<what|none> pid=<pid|-> <UTC>
ARMS_STOPPED arm=<name> step=<n> reason=<reason> <UTC>
ARMS_RESUME <the command that resumes the walk>
```

Every driver's own output goes to the same log, each call after a `>>> <UTC> <command>` line.
A dry run prints `DRY RUN` lines and none of these tags.

### The walk's own log

From `ARMS_START` on, run-arms also appends everything it prints (its tags, each driver's output, its own errors) to `results/<run>/logs/run-arms-<segment>-<UTC>.log`, where `<segment>` is `LAUNCH_SEGMENT` (`arms` under `launch.sh`) and `hand` for a direct call; the second line of the walk names the file (`>>> run-arms: output copied to ...`).
The archive and the bundle read `results/`, never `tasks/`, so this copy is the one that travels with the run: kind and attempt per index, retry reasons, pool-gate readings, `ARMS_EPOCH`, the stop and its resume command.
The segment log in `tasks/bench6/<run>/` gets every line as before.
A refusal before the walk starts and a dry run write no copy.

The copy is made inside run-arms, not by a second handle in `launch.sh`:

- A walk started without `launch.sh` (the `ARMS_RESUME` line of a walk that was, the rehearsal test) gets its copy too.
- `launch.sh` is unchanged: its clean-tree check (`results/` is ignored), the pid written from inside the detached shell, `nohup setsid`, and its rc line. `launch.sh` runs eleven kinds of segment and knows nothing of a run's results layout.
- No tee sits between the wrapper and its child, so the wrapper still passes its signals to the walk itself.

Each stream goes through its own `tee -a` reading a FIFO, line by line as the walk prints, so a walk killed at any point (even with SIGKILL) leaves every line it printed.
The tees ignore HUP, INT, TERM and PIPE and end when every writer has closed, so the output of a driver that outlives a killed walk reaches both copies.
Before each exit of its own (`ARMS_DONE`, a stop, a refusal inside the walk) run-arms closes its ends and waits for both tees, so `== arms rc=` stays the last line of the segment log.

### Stops

The walk stops, leaves the fleet as it is, and ends with `ARMS_STOPPED` and `ARMS_RESUME` on:

| reason | when | resumes at |
|---|---|---|
| `node-failed-<node>` | a `PA_FAIL` or `PARAMS_FAIL` line in the apply: a node failed its restart or readback | the arm, re-applied |
| `guard-deferred-twice` | two `PA_GUARD_DEFER` lines in one apply (the arm tool itself fails a node at its second deferral) | the arm |
| `apply-rc<n>`, `no-arm-ready`, `bad-ready-<t>`, `ready-too-far` | the arm tool exited non-zero, printed no `ARM_READY`, or its ready time is too far ahead | the arm |
| `mark-rc<n>`, `end-mark-rc<n>`, `close-rc<n>` | the arm tool's record failed | the step (a close: the next arm, whose apply closes the open one) |
| `arm-file-refused-<name>` | `--print-state` refused an arm file of the walk | the same command, after the fix |
| `blast-abort-<reason>` | the blast aborted on fleet health (`manifest.abort.reason` disk-full, batch-cache-cliff, quorum-lost, node-stalled or obs-memory); never retried | the step |
| `blast-failed-twice` | a fund or run failed, then its one retry (same type, next index) failed too | the step |
| `pool-queued` | a node's queued pool stayed at or above the limit | the step |
| `epoch-unreadable`, `epoch-wait-too-long` | the boundary could not be read, or lies too far off | the step |
| `commit-stall` | the blast left a new `.commit_stalls[]` entry longer than `RUN_ARMS_STALL_SECS` (`BENCH_ABORT_STALL_SECS`, 120) | the next step |
| `disk-<node>-<pct>pct`, `fatal-db-<node>` | the health check after a step | the next step |
| `health-unparsed` | the health check's status exited 0 and printed `BENCH_STATUS` lines, but the check parsed none of them (a parser fault: the walk would go on blind) | the next step |
| `signal-TERM` (`-INT`, `-HUP`) | a signal, once the driver call it came during has returned (Stop and resume) | the step it cut short (during the apply or the ready wait: the arm), else the next one; with every step done, the next arm (or the close, after the last arm) |

A resume always re-applies its arm under a new recorded name (`--from-arm k`), so an arm with `host evict-mdbx` restarts every node again (about 10 minutes) and starts from an evicted cache.
The steps before `--from-step` stay recorded under the arm's first name; `arms-summary.py` places each blast by its time, so a resumed arm shows as two arms.

### Checks between steps, and what is left to the watch

After the apply and after every step, `benchmark-blast.sh status` (read-only serial-console reads, bounded by `RUN_ARMS_HEALTH_SECS`, 180; 0 turns it off) gives each node's newest `BENCH_STATUS` line.
A root disk above `RUN_ARMS_MAX_DISK_PCT` (`BENCH_ABORT_DISK_PCT`, 85) or `fatal_db` above 0 stops the walk.
A status it cannot read, or fewer nodes than `nodes.txt`, prints `verdict=unknown` and goes on.
A status that exits 0 and prints `BENCH_STATUS` lines of which the check parses none stops the walk (`health-unparsed`).
During a blast the blast driver's own watchers abort on the same signals and on a lost quorum.

The orchestrator watches what these checks cannot see:

- `fatal_db` in a `BENCH_STATUS` line counts only the two minutes before that line, and the check reads the newest line only: a FatalDBFailure earlier in a long step (a 10-minute apply, the 20-minute M16) is missed. Watch the blast logs for `batch-cache-cliff` and any node log line with `FatalDBFailure`.
- A commit stall between blasts: an idle chain makes no blocks, so blocks cannot show it, and rounds need the Prometheus forward. Watch `tn_primary_round` on bench-obs while no blast runs.
- The driver calls themselves have their own deadlines (the arm tool's per-node waits, the blast's done-wait), not one from run-arms.
- `MemAvailable` and `workingset_refault_file` late in the run (persist CSV), since run 1's late DB sizes exceed run 2's.
- The `bound` arm's entry rule (abort the arm when a validator enters it 30 or more rounds behind): nothing in the harness reads rounds-behind cheaply, so check it by hand after the apply, before its first blast.
- Plan W4's other judgement rules stay with the orchestrator: the vote arm is read before PIPE or BOUND run, and an optional arm (P2, P3, GR100, a split POOL and LOCAL) goes into the plan file at G2.

## The probe

1. Build the binary (`benchmark/tools/build-probe-bin.sh`, see the probe driver's runbook) and read its plan: `BENCH_RUN_ID=<run> benchmark/benchmark-probe.sh plan --bin benchmark/work/probe-bin/mdbx-writeback-probe`.
2. Fill `<run-id>` in `bench6-probe.env` (a fresh id, not a fleet run's) and commit it, or fill a copy.
3. `benchmark/launch/launch.sh benchmark/launch/bench6-probe.env probe`
4. Wait for `== probe rc=`; the line before it is `DOWN_OK` (the VM and its disk are gone) or `DOWN_INCOMPLETE` (run `benchmark-probe.sh down` again).
5. Read `results/<run>/probe/SUMMARY.txt` before gate G1.

The probe has two modes, chosen by `LAUNCH_PROBE_DISKS` in the env file (launch.sh passes it as `--disks`).
`LAUNCH_PROBE_ZONE` (passed as `--zone`) names the zone when the default (validator-01's) does not offer the shape: `us-west2` has no
C3 `-lssd` shape, `us-west1-a` has `c3-standard-8-lssd`.

| mode | knob | VM | records | run, start to `DOWN_OK` |
|---|---|---|---|---|
| hyperdisk (the default) | unset | the fleet's shape: `c3-highcpu-8`, the 100 GB `hyperdisk-balanced` boot disk at 20,000 IOPS and 800 MiB/s | one per arm, on the boot disk; all 20 arms | about 85 min: 5 to create and settle, 20 arms of 2.5-4 min plus about 40 s of sessions each, 2 to collect |
| both | `LAUNCH_PROBE_DISKS=both` with `LAUNCH_PROBE_ARMS=g1-node,g5,g8-nowritemap` | `c3-standard-8-lssd` (`--lssd-machine-type`): the same boot disk, plus its first local NVMe SSD made ext4 and mounted at `/mnt/bench-probe-nvme` with the options the image's fstab gives `/` | two per arm: `<arm>@hyperdisk`, then `<arm>@nvme` | about 60 min for the six arms: 37 of probe time, 8 of sessions, 5 to create, up to 2 for the mkfs, 2 to collect |

`both` with all 20 arms needs about 150 min, more than the 120-min run deadline: the driver skips the arms that could not end in time, so run it with the subset.
The subset answers whether the fix (whole-map `MADV_RANDOM`) helps or hurts on each device: `g1-node` is the node's own shape, `g5` is the prefault on/off square with and without the fix (`g5-7default`, `g5-7default-mrand`, `g5-7pfoff`, `g5-7pfoff-mrand`), and `g8-nowritemap` is the no-WRITEMAP write path.
Add `g6-peer,g6-peer-mrand` (about 15 min more) to see the fix against a foreign read-ahead opener as well.
`c3-standard-8-lssd` has twice the fleet's RAM (32 GB against 16), so compare `@hyperdisk` with `@nvme` inside one run, never a `both` run's numbers with a hyperdisk run's.
The local SSD goes with the instance: the run creates the same two resources in both modes, and `DOWN_OK` covers both.

`SUMMARY.txt` starts with `PROBE_RUN` (the mode, the shape, and which reader gave resident pages: `fincore`, or `census` when the image has no fincore).
Each `PROBE_ARM` line now ends with the device writes per measured output: `wr_ops/out` (write requests), `wr_kib_mean` and `wr_kib_p90` (bytes per request), `flushes/out`, `syncs/out` (MDBX's own msync and fsync calls), `commit_wr_ops/out`, `sync_ms`, `dev_ms/wr` and `dev_ms/flush` (the sampler's diskstats time per request), and the arm's totals.
The `BIND` line under it compares the commit's write rate with the device's provisioned caps (`commit_iops=<rate>/<cap> (<share>)`, the same for MiB/s) and names the larger share; on the local SSD, which has no provisioned cap, it reads `n/a (no provisioned cap)`.
An arm with fewer bytes that pays for them in requests shows a smaller `device/mdbx` and a larger `wr_ops/out` and `commit_iops` share.
With `both`, a `PAIR <arm> hyperdisk/nvme` line follows each arm's two records with their main numbers side by side.
A value the source does not record reads `n/a`, never 0.

## Run 1: the arms

| # | launch | wait for | read before the next segment |
|---|---|---|---|
| 1 | `launch.sh <run1.env> deploy12` | `== deploy12 rc=0`, `BENCH_DEPLOY_RESULT rc=0` | the deploy log's `HOST_PROBE_SUMMARY`, the image gate lines, `OBS_READY` |
| 2 | `launch.sh <run1.env> arms --dry-run` | `== arms rc=0` | the walk: arm names, indices, the 16 blasts |
| 3 | `launch.sh <run1.env> arms` | `== arms rc=` | `ARMS_DONE`; on `ARMS_STOPPED`, the reason and the arm tool's or blast's output above it, then gate G3 |
| 4 | `launch.sh <run1.env> step15` | `== step15 rc=0` | `BENCH_DEPLOY_RESULT rc=0`, `metrics.json` |
| 5 | `launch.sh <run1.env> teardown-dry` | `TEARDOWN_DONE ... dry_run=1` | the list of what it would delete: this run's resources only |
| 6 | `launch.sh <run1.env> teardown` | `TEARDOWN_DONE run=<run> deleted=<n> left=0` | `left=0`; the pulled logs |
| 7 | `launch.sh <run1.env> archive` | `== archive-run run=<run> rc=0` | the `ARCHIVE_REMOTE` line |
| 8 | `launch.sh <run1.env> reindex` | `== reindex rc=0` | `INDEX.md` |
| 9 | `launch.sh <run1.env> arms-summary` | `== arms-summary rc=0` | `results/<run>/analysis/arms.md` (the arms run stays private) |

The `arms` segment needs the deploy's RPC tunnel (localhost:18545, for `M16@epoch`) and bench-obs forward (localhost:19090, for the pool gate) still up; both outlive the deploy until the teardown stops them.

## Run 1b: the local-SSD deployment

Run 1b deploys run 1's fleet again with the data directory of six validators on a local NVMe SSD, and walks three of run 1's arms on it.
It is option (e) of the local-SSD design (`benchmark/private/bench6-prep/design/design-local-ssd-deployment.md`, not in git), the shape recommended for gate G2.
Every validator stays in run 1's zone, and the validators of both disk classes execute the same outputs under the same load at the same time.
It runs after run 1's teardown, because the instance names are fixed and only one bench fleet exists at a time.
It has its own run id and runs run 1's image, generator and boot image: fill `bench6-run1-lssd.env`'s placeholders with run 1's values and a fresh run id.

### The shape

Every node keeps run 1's zone and the fleet's 100 GB `hyperdisk-balanced` boot disk.

| nodes | indices | machine type | memory | data directory |
|---|---|---|---|---|
| validators 03, 04, 05, 06, 07, 10 | 2-6, 9 | `c3-standard-8-lssd` | 32 GiB | the first of its two local NVMe SSDs (`google-local-nvme-ssd-0`), mounted at the data directory |
| validators 01, 02 and observer 11 | 0, 1, 10 | `c3-standard-8` | 32 GiB | the boot disk |
| validators 08, 09 | 7, 8 | `c3-highcpu-8`, run 1's shape (the default `MACHINE_TYPE`) | 16 GiB | the boot disk |

Hong Kong and Seoul offer no `c3-standard-8`, so validators 08 and 09 keep run 1's shape.
The boot-disk class therefore holds two machine types, and the arm summary groups the validators by disk class and machine type, never by class alone.

| knob | run 1b | read by |
|---|---|---|
| `BENCH_NODE_MACHINE_TYPES` | `"0:c3-standard-8 1:c3-standard-8 2:c3-standard-8-lssd ... 6:c3-standard-8-lssd 9:c3-standard-8-lssd 10:c3-standard-8"` (the table above) | config.sh (`NODE_MACHINE_TYPES`) |
| `BENCH_NODE_DATADIR_LSSD` | `1` | config.sh (`NODE_DATADIR_LSSD`) |
| `BENCH_FLEET` | `c3-lssd6-hdb4` (config.sh requires it with `BENCH_NODE_DATADIR_LSSD=1`) | config.sh |
| `BENCH_ZONE_FALLBACKS` | the zones below | config.sh |
| `BENCH_MACHINE_TYPE` | unset: `c3-highcpu-8` | config.sh |
| `RUN_ARMS_PLAN` | `benchmark/launch/bench6-run1-lssd.plan` (the walk below; `--plan` overrides it) | run-arms.sh |

Each stockout fallback zone was read on 2026-11-12 to offer the node's own machine type.
Validator 03 (Sydney) falls back to `australia-southeast1-a`, then `-b`; 05 (Ashburn) to `us-east4-c`, then `-a`; 06 (Eemshaven) to `europe-west4-b`, then `-c`; 07 (Singapore) to `asia-southeast1-a`, then `-c`; 10 (Mumbai) to `asia-south1-b`, then `-a`.
Validators 08 and 09 keep run 1's defaults (`asia-east1-a`, `asia-northeast3-b`).
Validators 01, 02 and the observer have none.
Validator 04 (Tokyo) has none either: no other Tokyo zone offers `c3-standard-8-lssd`, so a stockout there stops the deploy at step 2.

### What the deploy does differently

This follows the design; no deploy has run these steps on a live fleet yet.

- Step 2 creates each machine type's nodes in a call of its own; the local-SSD nodes are created with `--maintenance-policy=TERMINATE`.
- Step 3, after the serial markers and before keygen (step 5) first writes into the data directory, mounts each local-SSD node's first SSD at the data directory, four nodes at a time (`BENCH_NODE_JOBS`).
  The file system is ext4, made with the probe's options (`mkfs.ext4 -q -F -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard`) and mounted with the boot disk's own fstab options for `/`, so the two disk classes differ in the device only.
  The fstab line carries `nofail`, a drop-in makes `telcoin.service` require the mount, and a marker on the boot disk (`/var/lib/bench-lssd/uuid`) records the file system's UUID.
  The harness never changes the owner of the data directory: keygen hands the empty mount point to the `telcoin` user.
- Each node prints one line, `LSSD_MOUNT <inst> dev=<dev> by_id=google-local-nvme-ssd-0 size_bytes=<n> uuid=<uuid> mount=<dir> mkfs=done|kept|resumed options=<opts> fstab_root_options=<opts> ra_kb=<n>`, or `LSSD_MOUNT <inst> failed <reason>`.
  The lines go to `logs/lssd-mount-<UTC>.log` and into the manifest's `instances[].data_disk` (`"class": "local-ssd"`; the other nodes get `"class": "boot"`).
  A failed or missing line stops the step and names the node, since a node whose data directory silently stayed on the boot disk would spoil the comparison.
- After the last node: `LSSD_MOUNT_SUMMARY nodes=6 done=6 kept=0 resumed=0 failed=[]`.
  A re-run of step 3 (`--from 3` or later) finds the mount and reports `mkfs=kept`.
  A first run cut after its mount (a dropped session) is finished by the next one and reports `mkfs=resumed`, but only when the file system holds nothing except an empty `lost+found`.
- A node whose marker exists but whose data directory is not that file system fails `lost`: its SSD was wiped (a stop, a suspend or a host error).
  Step 3 never formats it again, so the node never starts on an empty data directory; its keys and database are gone, and it is out for the run.
- Step 7's pre-start session first checks the mount on each local-SSD node and fails with `PRECFG_FAIL <inst> local SSD not mounted at <dir>` otherwise, before the fsync probe and the host probe run.
- The deploy's plan (no `--yes`) prints the step-3 lines, and `benchmark-deploy.sh --print-lssd-mount <instance>` prints one node's mount script without a call.

Never stop, suspend or reset a local-SSD node by hand: a stop or a suspend wipes its SSD, and with it the node's keys and database.
What a reset, or a host maintenance event under `TERMINATE`, does to the SSD is not verified.
The harness itself never stops or reboots a node VM; the arm tool restarts the container.

### Segments

The env file pins the walk (`RUN_ARMS_PLAN=benchmark/launch/bench6-run1-lssd.plan`), so an `arms` launch needs no `--plan`; a `--plan` on the command line overrides the env file.
The `ARMS_RESUME` line after a stop names the walked plan with `--plan`, so a resume walks the same plan whatever the env file holds.

| # | launch | wait for | read before the next segment |
|---|---|---|---|
| 1 | `launch.sh <run1b.env> deploy12` | `== deploy12 rc=0`, `BENCH_DEPLOY_RESULT rc=0` | `LSSD_MOUNT_SUMMARY nodes=6 done=6 kept=0 resumed=0 failed=[]` and the six `LSSD_MOUNT` lines; `instances[].data_disk` in the manifest; `HOST_PROBE_SUMMARY ... uniform=no` and `FSYNC_PROBE_SUMMARY ... slow=[...]` naming one disk class are expected warnings; the image gate lines, `OBS_READY` |
| 2 | `launch.sh <run1b.env> arms --dry-run` | `== arms rc=0` | the walk: `DRY RUN: run-arms walks benchmark/launch/bench6-run1-lssd.plan ...` and `DRY RUN END: 3 arm(s), 6 step(s), 5 blast(s)` |
| 3 | `launch.sh <run1b.env> arms` | `== arms rc=` | `ARMS_DONE arms=3 blasts=5`; on `ARMS_STOPPED`, as in run 1 |
| 4 | `launch.sh <run1b.env> step15` | `== step15 rc=0` | `BENCH_DEPLOY_RESULT rc=0`, `metrics.json` |
| 5 | `launch.sh <run1b.env> teardown-dry` | `TEARDOWN_DONE ... dry_run=1` | this run's resources only |
| 6 | `launch.sh <run1b.env> teardown` | `TEARDOWN_DONE run=<run> deleted=<n> left=0` | `left=0`; the pulled logs |
| 7 | `launch.sh <run1b.env> archive` | `== archive-run run=<run> rc=0` | the `ARCHIVE_REMOTE` line |
| 8 | `launch.sh <run1b.env> reindex` | `== reindex rc=0` | `INDEX.md` |
| 9 | `launch.sh <run1b.env> arms-summary` | `== arms-summary rc=0` | `results/<run>/analysis/arms.md` and its "By disk class" table |

Before the deploy, on top of the pre-launch checklist: run 1's teardown at `left=0`; the deploy's plan with this env's values (the per-node machine types, the step-3 lines, the `LOCAL_SSD_TOTAL_GB` quota line); `--print-lssd-mount` read for one node.

### The walk

| k | arm | steps |
|---|---|---|
| 0 | `a0-control` | I, L, M4, M16 |
| 1 | `p1-mdbx-advice` | M16 |
| 2 | `a0-prime` | M16 |

`a0-control` is the fleet as deployed, never restarted and with no eviction.
`p1-mdbx-advice` restarts every node with `mdbx_random_advice true` and `host evict-mdbx`; `a0-prime` restarts every node at the defaults with `host evict-mdbx`.
Each arm keeps its run-1 steps, in run 1's relative order, so each row pairs with run 1's row for the same arm, and `a0-prime` still brackets `p1-mdbx-advice` for the arm summary's drift correction (it takes the first and the last control arm of a blast type).
Five blasts and one idle window in all.

### Fleet time

From this README's figures: the deploy about 46 minutes and the teardown about 35; a light blast (L, M4) 12 minutes (the 150-s light start lead, the generator's 90-s preamble, 60 / 360 / 60 s); an M16 1,350 s; an apply with `host evict-mdbx` about 10 minutes; the idle step 5.
The "few minutes" after each blast (the fund, the results, the blaster deletes, the health check) is taken as 4.
The same figures, with half an epoch's wait for `M16@epoch`, give run 1's walk about 7.4 hours, close to the 7 hours at the top of this file.

| segment | minutes |
|---|---|
| deploy to step 12: 46, plus two waves of mkfs (six nodes, four at a time, up to 2 minutes each) | about 50 |
| `a0-control`: 5 + 12 + 12 + 22.5, plus 3 × 4 | about 63 |
| `p1-mdbx-advice`: 10 + 22.5 + 4 | about 37 |
| `a0-prime`: 10 + 22.5 + 4 | about 37 |
| step 15 (an estimate) | about 10 |
| teardown | about 35 |
| total: 50 + 63 + 37 + 37 + 10 + 35 = 232 | about 3 h 50 min |

### What the comparison can and cannot show

It can show how the two disk classes behave under the same load at the same time.
The cleanest pair is the six local-SSD validators against validators 01 and 02: the same family, vCPU count and memory, a different device.
The arm summary's "By disk class" table gives each (disk class, machine type) group's medians of the engine, amplification, refault and disk columns, and `p1-mdbx-advice` and `a0-prime` show each class's response to the advice and to the eviction.
On a local-SSD node the provisioned-cap shares and binds read `n/a`; its measured rates stay.

It cannot separate the disk from everything else that differs between the groups:

- The groups are small and sit in different regions: two validators (Los Angeles, London) in the 32-GiB boot-disk group, whose median is the mean of the two, two (Hong Kong, Seoul) in the 16-GiB group, and six elsewhere on local SSDs.
- Against run 1, nine of the eleven nodes have twice the memory and six a different disk, so a difference between paired rows mixes memory and disk, and the days differ.
  Only validators 08 and 09 have the same shape and disk in both runs.
- The fleet's throughput and latency are those of a mixed fleet; they do not say what ten validators on local SSDs would reach.

## Run 2: the headline

Before the deploy, `benchmark/arms/final.arm` must hold the configuration chosen at G3, committed.

| # | launch | wait for | read before the next segment |
|---|---|---|---|
| 1 | `launch.sh <run2.env> deploy12` | `== deploy12 rc=0`, `BENCH_DEPLOY_RESULT rc=0` | step 7's arm record (`param_arms[]`, `via: prestart`), step 9's switch readback, `HOST_PROBE_SUMMARY` |
| 2 | (the idle window is inherent: the fleet runs until the next launch) | | |
| 3 | `launch.sh <run2.env> blast15` | `== blast15 rc=0`, `BENCH_DEPLOY_RESULT rc=0` | `LIGHT_LOAD_DONE` twice, `BENCH_BLAST_DONE`, `LOG_RATE`, `late_secs` |
| 4 | `launch.sh <run2.env> teardown-dry` | `TEARDOWN_DONE ... dry_run=1` | this run's resources only |
| 5 | `launch.sh <run2.env> teardown` | `TEARDOWN_DONE ... left=0` | `left=0` |
| 6 | `launch.sh <run2.env> reindex` | `== reindex rc=0` | `INDEX.md` |
| 7 | `launch.sh <run2.env> archive` | `== archive-run run=<run> rc=0` | `ARCHIVE_REMOTE` |
| 8 | `launch.sh <run2.env> bundle --compare r20261107-1504 --backfill benchmark/report/backfill/<bench6>.json` | `== bundle rc=0` | the bundle's provenance and KPI lines |

## Bench 7

Two runs of the bench 7 build (upstream main with the tn-lmdb store and the bench 7 stack), each in the shape of bench 6's run `r20261113-1351`.
`bench7-always.env` applies `benchmark/arms/bench7-always.arm` (every switch on, the vote fix always on); `bench7-adaptive.env` applies `benchmark/arms/bench7-adaptive.arm` (the same with `quorum_exec_block_starved_rounds 4`).
The two files differ only in `BENCH_ARM_FILE` and their header comment.

Against the env that ran `r20261113-1351` (`tasks/bench6/r20261113-1351/bench6-run2.env`) they change three things:

- the image keys hold placeholders again: `<image-digest>` and `<node-sha>`, filled at the image cut (`tasks/bench7/orch-image-cut.sh` prints the digest), and `<run-id>`;
- `BENCH_ARM_FILE` names the bench 7 arm;
- they add `BENCH_NODE_ALLOW_FAUCET_ON_CHAIN=1` and `BENCH_NODE_RESERVE_PORTS=1`, and the fleet's shape written out: `BENCH_MACHINE_TYPE=c3-highcpu-8`, `BENCH_NODE_DISK_TYPE=hyperdisk-balanced`, `BENCH_NODE_DISK_SIZE=100`, `BENCH_NODE_DISK_IOPS=20000`, `BENCH_NODE_DISK_THROUGHPUT=800`.

Each added key is config.sh's default, so the fleet is the one `r20261113-1351` had; the zones are config.sh's fixed list.
They set no MDBX knob, as the run 2 env set none: the deploy refuses `BENCH_NODE_EVICT_MDBX` on a tn-lmdb image (`mdbx_knob_problems`), and config.sh refuses it beside an arm file.
No knob names the storage engine: the image gate reads it from the binary's `--version` and writes `storage_engine` into the manifest.

Per run, in this order:

| # | call | what it does | read before the next |
|---|---|---|---|
| 1 | `tasks/bench7/orch-run-chain.sh <env>` | the plan: `launch.sh --dry-run` of deploy12 and blast15, a new run id, a clean harness tree, no fleet driver running; starts nothing | the `CHAIN` plan lines, rc 0 |
| 2 | `setsid bash tasks/bench7/orch-run-chain.sh --live <env> > <log> 2>&1 < /dev/null &` | deploy12, the idle checks, then blast15 with `tasks/bench7/orch-fleet-health.sh <run> --watch ... --until-file <blast15 log>` beside it | `CHAIN done rc=0`, the watch's last `FLEET_HEALTH` lines |
| 3 | `tasks/bench7/orch-prom-export.py <out-dir> <start> <end> --manifest benchmark/results/<run>/manifest.json`, while the fleet is up | the must-have check, then the export | no `status=incomplete`, `EXPORT_DONE` |
| 4 | `launch.sh <env> teardown-dry`, `teardown`, `reindex`, `archive`, `bundle` | as in run 2 above | as in run 2 above |

At idle, before the blast (the chain checks the first two and stops at exit 11, leaving the fleet up, when one fails):

- seven `tn_node_switch{name}` series on each of the eleven nodes, with the arm's values: 1 for each bool, `quorum_exec_block_starved_rounds` 0 (always) or 4 (adaptive);
- `storage_engine` in the manifest is `tn-lmdb`;
- `halt=0` on every node (`tasks/bench7/orch-fleet-health.sh <run>`, one round, exit 0).

`halt=` is new on the samplers' `BENCH_STATUS` line (`... fatal_db=<n> halt=<n> block=<n> ...`).
It counts the lines of the node's unit log that carry one of the build's fail-stop phrases (the stored-record mismatch, the closing-block check, `epoch record conflict halt:`, the leftover-drain gap, `we have forked!`, a refused `vote_timeout`) since the log began, so a node that halted and restarted stays counted.
The blast's abort does not read it: a halted validator is a finding of the run, not a reason to stop the blast.
The watch prints `halt=<sum>` on its `FLEET_HEALTH` line, a `FLEET_HEALTH HALTED <node>=<n> ...` line, and ends with its alarm (exit 3) naming the nodes.

The export's check knows three kinds of must-have series: on every node; on every validator only (the proposer's order-hold series, which the observer never builds); and lazy ones, which exist on a node only after its first count (`status=lazy` lists the nodes without one and never refuses the export).

No pre-flight for the conflict halt: on a fresh genesis no node holds an epoch record from before the run, so there is no stored record a certified one could conflict with.

## Monitor

Poll each segment's log every 30 s with a deadline, never with a pattern that can match the poll's own command line:

```
deadline=$(( $(date +%s) + 4 * 3600 )); log=tasks/bench6/<run>/<segment>-<UTC>.log
until grep -qE '^== <segment> (rc=|LEFT_RUNNING )' "$log" || [ "$(date +%s)" -ge "$deadline" ]; do
  grep -E '^== .* (rc=|signal |LEFT_RUNNING )|❌|ABORT|BENCH_DEPLOY_RESULT|PARAMS_OK|PA_FAIL|ARM_READY|== arm|ARMS_(STEP|STOPPING|STOPPED|RESUME|DONE|HEALTH|POOL|RETRY)|LIGHT_LOAD_(START|DONE)|BENCH_BLAST_DONE|late_secs|LOG_RATE|(FSYNC|HOST)_PROBE_SUMMARY|PROBE_ARM_DONE|DOWN_(OK|INCOMPLETE)|TEARDOWN_DONE' "$log" | tail -n 5
  sleep 30
done
```

`launch.sh <env> status` shows every segment of the run and its last line.

## Pre-launch checklist

- `date -u`; a fresh token (`gcloud auth login` within an hour of a long segment; `launch.sh` refuses a token it cannot print).
- `bench_leftovers` empty, and the only bucket is the archive.
- Quotas, including hyperdisk IOPS and throughput.
- The boot image READY.
- The node image probed by digest (`benchmark-deploy.sh --probe-node-image <repo>@sha256:<d>`: the switch flags, the `node switches` line).
- The generator image built and probed.
- The harness gate (`benchmark/tests/gate.sh`) run alone, rc 0 on record.
- Dry runs: `--print-prestart` with `final.arm`, `params-apply.sh --dry-run` on every arm file, `launch.sh <env> arms --dry-run` (run 1, and run 1b, whose env file pins its plan), the probe's plan, and the teardown dry run.
- No heavy peer jobs on the host (`pgrep`); a test suite that runs the bench drivers also blocks a launch.
- The obs-devnet disk gate.
- Bench 5's results archived.
- Nobody edits a running driver or its libraries while a segment runs (lesson 2026-11-05).

## Stop and resume

- To stop a segment, send TERM to the pid in its pid file: `kill <pid>`.
  TERM is the only signal that reaches a segment: the detached shell starts as a background job under `nohup`, with INT and HUP ignored, and every driver inherits that.
  The shell logs `== <segment> signal TERM <UTC>: passed to pid <driver>; ...`, passes the TERM to its driver and waits for it; then `== <segment> driver pid=<p> exit=<n> after TERM <UTC>` and the rc line.
- Every segment but `arms`: the driver gets the TERM and runs its own exit cleanup (a blast stops or deletes its blasters, the probe deletes its VM), and the log ends with `== <segment> rc=143` (the driver's own code when it exits non-zero).
  `status` shows `state=stopping after the driver (pid <p>)` meanwhile.
- `arms`: the walk finishes the driver call that is running and starts nothing new (below); the log ends with `== arms rc=143` after the walk's last line.
- A process of the segment's group that outlives its driver (a background job the driver left) holds the rc line back for `LAUNCH_LEFT_WAIT_SECS` (60), listed under `== <segment> waiting up to 60 s for what is left of the segment:`.
  Still running then, it is listed again and the log ends with `== <segment> LEFT_RUNNING exit=<n> pids=<p,...> <UTC>` instead of an rc line (the shell exits 125); `status` shows `left running (<pids>)`.
  Treat it as a running driver: see what it is (`ps -o pid,args -p <pid>`) before launching anything.
  A helper meant to outlive its driver starts in a session of its own, as the ssh tunnels do (`nohup setsid`); the websocket tunnel (`BENCH_TUNNEL_MODE` other than `ssh`) does not, so a deploy that starts one ends with `LEFT_RUNNING`.

### A TERM to the arm walk

From `ARMS_START` on, the walk takes TERM (and INT or HUP in a walk started by hand) the same way.
A driver call that is running (an apply, a fund, a blast run, an idle mark, a close, a health check) is left alone and runs to its end.
The walk prints at once:

```
ARMS_STOPPING arm=<name> step=<n> signal=TERM after=<what> pid=<driver pid> <UTC>
  stopping after <what> (pid <p>): it runs to its end, nothing new starts (README.md, Stop and resume)
```

`<what>` is `apply-<arm>`, `blast-fund-<i>`, `blast-run-<i>`, `mark-idle-<n>`, `end-mark-idle-<n>`, `close-<arm>` or `health-<n>`, and `status` shows `state=stopping after <what> (pid <p>)`.
When the call returns, the walk prints its result as usual (`ARMS_BLAST`, `ARMS_STEP`) and stops with `ARMS_STOPPED ... reason=signal-TERM` and `ARMS_RESUME`: no retry, no health check, no close, so the arm stays open, as after `blast-failed-twice`.
A stop the call's result causes anyway (`node-failed-*` after an apply, `blast-abort-*`, `commit-stall`) keeps its own reason.
Every stop after a signal exits 143 (130 for INT, 129 for HUP).
A wait between calls (the ready time, the pool gate, the epoch boundary, the idle window) ends at once, with `after=none`; an idle window cut short still gets its `--end-mark` (a record, no node), and the resume measures it again.
A second TERM changes nothing: `  run-arms: TERM again: it changes nothing; still stopping after <what> (pid <p>)`.
Ctrl-C on a walk started by hand stops the walk the same way and does not end its driver: the drivers run as background jobs, which ignore INT (a program that sets its own INT handler, such as `gcloud compute ssh`, still gets it).

How long the wait can be is the rest of the call that is running:

| call | at most |
|---|---|
| blast run | what is left of its start delay (300 s), the generator's preamble (90), warmup, mixed phase, cooldown and tail scan (an M16 is 1,350 s in all), then the wait for its results, the copy and the blaster deletes (a few minutes) |
| blast fund | the funder VM's run, the copy and the VM's delete |
| apply | the rolling restart, one node at a time with each node's own waits (about 10 minutes with `host evict-mdbx`) |
| health check | `RUN_ARMS_HEALTH_SECS` (180 s) |
| a mark or a close | seconds (a record write, no node) |

To cut the wait:

- A blast run: `kill <pid>`, the pid of the `ARMS_STOPPING` line (the blast driver itself).
  Its exit trap stops the blasters (or deletes them before their start time), waits a bounded time (`BENCH_TRAP_WAIT_SECS`, 300 s, and more for a long blast) for their results, copies them and deletes the VMs; the walk then stops as above.
- A blast fund: the same `kill <pid>`, but `fund` has no exit cleanup of its own: its funder VM is left behind.
- Load VMs left behind (after a fund, a driver killed with SIGKILL, or a cleanup that names a VM it could not delete): `benchmark/benchmark-blast.sh status --run <run>` lists them and `benchmark/benchmark-blast.sh delete --yes --run <run>` deletes every blaster and funder VM of the benchmark (label-guarded).
- An apply: run-arms never signals it, and `params-apply.sh` has no TERM handling of its own (its EXIT trap only removes its work directory).
  A TERM to its pid ends it at once: a node whose transient restart unit has started finishes that restart on the node, the nodes after it keep the old arm, and the arm's record (open since its first restart) holds the nodes done so far.
  The walk stops (`apply-rc143`, or the failure the arm tool printed first); the resume re-applies the arm under a new name (`-r2`), which closes that record and restarts only the nodes not in the arm yet (every node again when the arm has host steps).
- The walk itself: a second TERM to the segment does nothing more.
  Killing run-arms with SIGKILL leaves its driver running without anyone watching it; `launch.sh` then names that driver in `LEFT_RUNNING` instead of writing an rc line.

### After a stop

- `ARMS_STOPPED` leaves the fleet as it is.
  Read the reason and the output above it, bring it to the user (gate G3), and resume with the printed `ARMS_RESUME` command; it goes through `launch.sh` when the walk was started by it.
- A segment that ended non-zero is relaunched with `launch.sh` after the cause is understood; the deploy and the teardown resume from their own records (`--from <step>`, a second teardown).
- A dead segment without its `== rc=` line (`status`: `died (no rc line)`) was killed with SIGKILL: look for its driver with `pgrep -f` before launching anything.
