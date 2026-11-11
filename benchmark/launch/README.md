# Bench 6 launchers

A bench run is a chain of long driver calls against a GCP fleet: the deploy takes about 46 minutes, the teardown about 35, and run 1's arm walk about 6 hours.
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
| 3 | `pool-local` | M16@epoch |
| 4 | `pipe` | M4, M16 |
| 5 | `bound` | M4, M16 |
| 6 | `gr150` | I, L, M16s |
| 7 | `a0-prime` | M16 |

Fourteen blasts in all; `--dry-run` prints every command.
If the image lacks `pipelined_persist`, drop the `pipelined_persist` line from `pipe.arm`, `bound.arm` and `gr150.arm` (arms/README.md), or drop the `pipe` line here.

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
| `signal-TERM` (`-INT`, `-HUP`) | a signal, once the driver call it came during has returned (Stop and resume) | the step it cut short (during the apply or the ready wait: the arm), else the next one; with every step done, the next arm (or the close, after the last arm) |

A resume always re-applies its arm under a new recorded name (`--from-arm k`), so an arm with `host evict-mdbx` restarts every node again (about 10 minutes) and starts from an evicted cache.
The steps before `--from-step` stay recorded under the arm's first name; `arms-summary.py` places each blast by its time, so a resumed arm shows as two arms.

### Checks between steps, and what is left to the watch

After the apply and after every step, `benchmark-blast.sh status` (read-only serial-console reads, bounded by `RUN_ARMS_HEALTH_SECS`, 180; 0 turns it off) gives each node's newest `BENCH_STATUS` line.
A root disk above `RUN_ARMS_MAX_DISK_PCT` (`BENCH_ABORT_DISK_PCT`, 85) or `fatal_db` above 0 stops the walk.
A status it cannot read, or fewer nodes than `nodes.txt`, prints `verdict=unknown` and goes on.
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

## Run 1: the arms

| # | launch | wait for | read before the next segment |
|---|---|---|---|
| 1 | `launch.sh <run1.env> deploy12` | `== deploy12 rc=0`, `BENCH_DEPLOY_RESULT rc=0` | the deploy log's `HOST_PROBE_SUMMARY`, the image gate lines, `OBS_READY` |
| 2 | `launch.sh <run1.env> arms --dry-run` | `== arms rc=0` | the walk: arm names, indices, the 14 blasts |
| 3 | `launch.sh <run1.env> arms` | `== arms rc=` | `ARMS_DONE`; on `ARMS_STOPPED`, the reason and the arm tool's or blast's output above it, then gate G3 |
| 4 | `launch.sh <run1.env> step15` | `== step15 rc=0` | `BENCH_DEPLOY_RESULT rc=0`, `metrics.json` |
| 5 | `launch.sh <run1.env> teardown-dry` | `TEARDOWN_DONE ... dry_run=1` | the list of what it would delete: this run's resources only |
| 6 | `launch.sh <run1.env> teardown` | `TEARDOWN_DONE run=<run> deleted=<n> left=0` | `left=0`; the pulled logs |
| 7 | `launch.sh <run1.env> archive` | `== archive-run run=<run> rc=0` | the `ARCHIVE_REMOTE` line |
| 8 | `launch.sh <run1.env> reindex` | `== reindex rc=0` | `INDEX.md` |
| 9 | `launch.sh <run1.env> arms-summary` | `== arms-summary rc=0` | `results/<run>/analysis/arms.md` (the arms run stays private) |

The `arms` segment needs the deploy's RPC tunnel (localhost:18545, for `M16@epoch`) and bench-obs forward (localhost:19090, for the pool gate) still up; both outlive the deploy until the teardown stops them.

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
- Dry runs: `--print-prestart` with `final.arm`, `params-apply.sh --dry-run` on every arm file, `launch.sh <env> arms --dry-run` (run 1), the probe's plan, and the teardown dry run.
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
