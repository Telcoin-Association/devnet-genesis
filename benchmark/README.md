# Benchmark profile

A throwaway Telcoin Network fleet for load testing, built in the `tn-devnet` project next to
the live devnet and removed afterwards. Ten validators and one observer run chain **32286**
(devnet is 32285) with 20-minute epochs. Each node is a `c3-highcpu-8` with a 100 GB
`hyperdisk-balanced` boot disk unless you pick another shape (see [Fleet shape](#fleet-shape)).
One COS blaster VM per validator drives `tn-transaction-generator blast` at it, while a sampler
on every node and obs-devnet's Prometheus record what the nodes do.

Everything here is additive. The devnet scripts behave exactly as before unless a benchmark
script points them at `benchmark/config.sh` through `CONFIG_FILE`.

## What it never touches

- The devnet instances `validator-{1..4}-devnet`, `observer-5-devnet`, `obs-devnet`,
  `txgen-devnet` and `devnet-indexer`. Teardown rebuilds this denylist from a clean
  `../config.sh` on every run and aborts if any candidate is on it.
- Devnet firewall rules. Bench nodes carry only the tag `bench-node`, which no devnet rule
  selects, and none of devnet's tags (`validator`, `http-server`, `https-server`,
  `lb-health-check`), so no devnet rule, LB backend or health check selects them.
  `benchmark-firewall.sh` refuses any name matching `^devnet-|^default-|^obs-|^wg-|^allow-`,
  and after every apply it diffs `devnet-allow-consensus` against its earlier state.
- DNS, certificates, Caddy, the RPC load balancer, dashboards, Uptime Kuma and the WireGuard
  overlay. `BASE_DOMAIN` is `bench.invalid` and the nodes never join the overlay.
- The obs VM itself. The bench ships **metrics only** to obs-devnet, labelled
  `network="bench"`. It never runs `create-obs-instance.sh` (and so never `--wipe-data`),
  and it ships no logs into devnet's Loki.
- The devnet tn-contracts checkout. Contracts deploy from a disposable worktree on a
  `bench/<run>` branch, which is never committed to.

`benchmark/config.sh` only loads for an allowlist of callers: the `benchmark-*.sh` scripts
and the shared drivers they run (`devnet-keygen.sh`, `devnet-genesis-build.sh`,
`devnet-finalize.sh`, `devnet-contracts.sh`, `common/create-instances.sh`). Every other script
started with `CONFIG_FILE=benchmark/config.sh` exits before doing anything, including the
devnet-only drivers, the wgvpn tools, and scripts added later. `devnet-observability.sh` is
deliberately not on the list (see step 8). The profile also refuses to be sourced in an
interactive shell, because its exports would leak into a later devnet command.

## Before the first run

- `gcloud auth login` as an account with Compute, Secret Manager, Storage and IAM rights in
  `tn-devnet`. You also need `cast`, `jq`, `python3`, `docker` and `git` locally, plus
  `forge` for `--with-contracts`. Docker must be running: the gate examines the node image
  with it, and that check has no skip switch.
- The secrets `bench-txgen-master-key` (bare `0x<64 hex>`) and `bench-txgen-children-seed`
  (12 BIP-39 words) exist in Secret Manager. They never go into instance metadata or onto
  the operator's disk: each blaster reads them over the Secret Manager REST API with its own
  service-account token.
- `testnet_accounts.yaml` in this directory is devnet's accounts file with the txgen master
  swapped for the bench master `0xb1F7…3C8E`. The contracts admin `0xAee2…520f` stays funded.
- `tn-transaction-generator/config.bench.toml` and `cloudbuild.yaml` exist. The load image is
  pinned to a generator commit, `…/tn-transaction-generator:blast-v2-<sha7>`, where the SHA is
  `BENCH_TXGEN_SHA` or the HEAD of a clean generator checkout. A dirty tree is refused. The
  old `:blast` tag predates the blast-v2 CLI and is never used. Step 1 builds the image with
  Cloud Build if the tag is missing, then runs `blast --help` from it and checks every flag
  the blasters use. The manifest records the image, so a resumed run keeps using it.
- A `--yes` run checks all of this before its first step: the image, `cloudbuild.yaml`,
  `config.bench.toml` and `results/<run>/deployments-bench.json` (unless step 11 will make it).
  When a selected step deploys the node image, it also probes that image and pins the run to
  its digest (see [Node image](#node-image)).

## Fleet shape

The default fleet is `c3-hdb`: every node is a `c3-highcpu-8` with a 100 GB
`hyperdisk-balanced` boot disk provisioned at 20000 IOPS and 800 MiB/s. These variables change
the shape:

| Variable | Default | Notes |
|---|---|---|
| `BENCH_MACHINE_TYPE` | `c3-highcpu-8` | e2 and n1 types cannot attach hyperdisk, so config.sh refuses them with a hyperdisk disk type. Pair them with `pd-ssd`. |
| `BENCH_NODE_DISK_TYPE` | `hyperdisk-balanced` | For a hyperdisk type, step 0 checks that every fleet zone offers it. |
| `BENCH_NODE_DISK_SIZE` | `100` | GB. |
| `BENCH_NODE_DISK_IOPS` | `20000` on `hyperdisk-balanced`, else empty | Hyperdisk only. Set it empty (`BENCH_NODE_DISK_IOPS=`) to give the disk its type's default. |
| `BENCH_NODE_DISK_THROUGHPUT` | `800` on `hyperdisk-balanced`, else empty | MiB/s. Same rules as the IOPS. |
| `BENCH_FLEET` | from the shape | The fleet label in the manifest and the report. |

Only `hyperdisk-balanced` gets the 20000/800 defaults. Other hyperdisk types provision only IOPS
or only throughput, so set the knob they take yourself. Either knob on a non-hyperdisk disk is
refused.

Unless `BENCH_FLEET` overrides it, the label follows the shape:

| Machine type and disk | Label |
|---|---|
| `e2-custom-4-8192` + `pd-ssd` | `A`, the e2 baseline |
| `c3-highcpu-8` + `pd-ssd` | `B` |
| any type + `hyperdisk-balanced` | `<family>-hdb`, such as `c3-hdb` |
| anything else | the machine type |

So `BENCH_MACHINE_TYPE=e2-custom-4-8192 BENCH_NODE_DISK_TYPE=pd-ssd` reproduces fleet A.

## Consensus timing

The bench runs shorter consensus delays than devnet. They live in the committed
`benchmark/consensus-parameters.yaml`:

| Key | Bench | Devnet (`common/parameters.yaml`) |
|---|---|---|
| `max_header_delay` | 500ms | 3s |
| `min_header_delay` | 250ms | 1s |
| `max_batch_delay` | 250ms | 1s |

Every other key is the same as in `common/parameters.yaml`. The node reads `parameters.yaml`
from its datadir, and `devnet-finalize.sh` (step 7) stages this file there.

`BENCH_PARAMETERS_FILE` points the run at another file, which must exist and be readable.
config.sh refuses `benchmark/parameters.yaml` under any spelling of its path, because
`telcoin genesis` writes a file with that name into the workspace at step 6. That generated
file is gitignored.

The gate records the file in `manifest.consensus_parameters`: its name, SHA-256 and the three
delays in milliseconds. A resume that does not re-run step 7 keeps the recorded values, and
warns if the file has changed since. Step 9 checks every node's boot lines against them.

## Node image

The bench never runs a node image it has not examined. `BENCH_DOCKER_IMAGE` names the image, as
a tag or `<repo>@sha256:<digest>`. Without it the bench uses the live devnet's image. When a
selected step creates or starts nodes from the image (0, 5, 6 or 7), the `--yes` gate runs
`bench_node_image_probe` on it before any step runs, so on a fresh run nothing exists in GCP
yet. Any failure stops the run. The probe:

1. Resolves the tag to its registry digest and pins the run to `<repo>@sha256:<digest>`, since
   tags are mutable. Every later step and sub-script runs the pinned ref.
2. Pulls the pinned ref and runs `telcoin -V`, which must name a git sha. An image that says
   `unknown` was built without git metadata, so the run stops. When `--version` names a
   commit, it must be the same one.
3. Checks that `telcoin node --help`, `telcoin genesis --help` and
   `telcoin keytool generate validator --help` list every flag the deploy passes.
4. Copies the binary out of the image and counts each string of
   `benchmark/node-image-contract.txt` in it.

The contract file has three directives:

| Directive | Meaning |
|---|---|
| `require <string>` | The binary must contain it, or the image is refused. |
| `require-if-subsecond <string>` | All of them present means a build with sub-second timestamps from genesis. |
| `forbid-if-subsecond <string>` | Present means the adiri fork schedule. An image that also has every sub-second marker is refused. |

From these the probe labels the fork schedule `subsecond-from-genesis`, `adiri-schedule` or
`pre-subsecond` (neither marker).

Every `require` line is calibrated against the known-good baseline image: a line stays only if
the baseline passes it. A `require` the baseline cannot pass is a broken check, not a finding.
Fix or drop the line, never the baseline (see the 2026-07-22 lesson on version-string gates in
`tasks/lessons.md`). This is why the Prometheus metric names are not in the file. The node
builds them at run time, so they never appear as literal strings in the binary. Step 10 checks
them live instead.

Optional expectations make the probe stricter:

| Variable | The run stops unless |
|---|---|
| `BENCH_DOCKER_IMAGE_EXPECT_DIGEST=sha256:<64 hex>` | the tag resolves to this digest |
| `BENCH_NODE_EXPECT_SHA=<7-40 hex>` | the binary's git sha starts with it |
| `BENCH_NODE_EXPECT_FORKS=<label>` | the fork schedule is this label |

`benchmark/benchmark-deploy.sh --probe-node-image [REF]` runs the probe on its own, locally,
and writes nothing: no run directory, no manifest. `REF` defaults to the configured image. If the
pull fails, the probe falls back to a local image of that name. With `--yes` it refuses a local
image whose repo digest is not the registry's, as the gate does. The probe needs a running
docker and takes about 20 to 40 seconds on an Apple Silicon Mac, which runs the amd64 image
under emulation.

A resumed run (`--run`) reuses `manifest.node_image_pinned` and does not probe again. If
`BENCH_DOCKER_IMAGE` names an image other than the pinned ref or the ref it was probed from,
the deploy exits 1. Unset it, or start a new run.

## Runbook

Pick a run id and use it for every command: `BENCH_RUN_ID=r$(date -u +%Y%m%d-%H%M)`.

```bash
# 0. Read the plan. This makes no GCP calls.
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --with-contracts

# Optional: probe the node image alone (local docker, writes nothing).
benchmark/benchmark-deploy.sh --probe-node-image

# 1. Deploy, fund, blast, collect (steps 0-15). Add --with-teardown to finish with step 16.
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --yes --with-contracts

# Resume after a failure, or re-run one step:
benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 9
benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --only 15

# The blast phases on their own (steps 13-15 call exactly these):
benchmark/benchmark-blast.sh fund    --run r20260923-0100 --yes
benchmark/benchmark-blast.sh run     --run r20260923-0100 --yes      # --keep leaves the blasters up
benchmark/benchmark-blast.sh collect --run r20260923-0100 --yes
benchmark/benchmark-blast.sh status  --run r20260923-0100

# 2. Tear down. Read the dry run, then apply. Before the first delete it copies the run to
#    gs://tn-devnet-benchmark-archive/runs/r20260923-0100/ and verifies the copy.
benchmark/benchmark-teardown.sh --run r20260923-0100
benchmark/benchmark-teardown.sh --run r20260923-0100 --yes           # --purge also deletes the bench secrets

# Only if the archive cannot be written and the fleet must go anyway (recorded in manifest.notes):
BENCH_TEARDOWN_SKIP_ARCHIVE=1 benchmark/benchmark-teardown.sh --run r20260923-0100 --yes
```

Every script is a dry run unless you pass `--yes`, and prints each gcloud argv before it
runs it.

The harness never deletes a node log. Each run's logs and results stay in `results/<run>/` and
in the archive bucket `gs://tn-devnet-benchmark-archive` (`BENCH_ARCHIVE_BUCKET`), which no
script deletes from. Clean the archive by hand, and only after the run's results are qualified.

### What the deploy does

| Step | What happens |
|---|---|
| gate | `--yes` only, before any step. Checks what the selected steps need: the `:blast-v2-<sha>` image, `cloudbuild.yaml`, `config.bench.toml` and `deployments-bench.json`. When step 0, 5, 6 or 7 is selected and the run has no pinned image yet, it probes the node image and pins it (see [Node image](#node-image)). It then creates `manifest.json`, or keeps it on a resume, and records the probe (`node_*`) and `consensus_parameters`. |
| 0 | Preflight checks: auth, tools, accounts file, empty `genesis/`, no foreign rule selecting `bench-node`, obs-devnet `/mnt/obs-data` below 70 %, vCPU quota per region, and a hyperdisk type offered in every fleet zone. Node vCPUs count against their family's quota metric (`C3_CPUS` for c3) and the blasters' e2 vCPUs against `CPUS`. A metric the region does not list is a warning, not a failure. Writes the pre-snapshots. |
| 1 | Asserts the `:blast-v2-<sha>` tag, builds it with Cloud Build if missing, and probes `blast --help` for the CLI contract flags (when docker is available). |
| 2 | Runs `common/create-instances.sh` on the bench profile, then asserts `tags == [bench-node]` and `labels.benchmark == 1` on every node, labels the boot disks and records `manifest.instances[]`. |
| 3 | Waits for the `devnet-startup.sh complete` serial marker on each node. |
| 4 | `benchmark-firewall.sh apply`: `bench-allow-consensus` (udp 49590/49594 from the nodes' own /32s) and `bench-allow-iap-rpc` (tcp 8545 from IAP). |
| 5–7 | The devnet drivers, on the bench profile: keygen, genesis build (in `benchmark/`) and finalize. |
| 8 | Metrics-only observability in one IAP session per node. `setup-observability.sh` would label the node `network="devnet"` (it derives the label from the node's network), so it is pointed at a black-hole metrics URL. In the same session Alloy is stopped, its WAL wiped, the env set to `TN_CHAIN=bench`, `TN_NODE=<instance>` and the real obs-devnet URL, and Alloy started again. No devnet-labelled sample leaves a bench node. |
| 9 | One IAP session per node, run serially. It rebinds reth `--http.addr` to 0.0.0.0, checks the bench Alloy labels, restarts the node, waits until the internal IP answers `eth_chainId == 0x7e1e` and consensus is progressing (the block height rose, or the node's `docker logs` show `subdag committed`/`quorum reached` since the restart; connection refusals while the node restarts are retried until the deadline), reads the node's boot lines, then installs `bench-node-sampler.service`. Serial order keeps at most one node down at a time. The boot lines give the git sha, the max and min header delay, the max batch delay, the vote timeout (later builds only) and the fork schedule. They go onto the `POSTCFG_OK` line as `sha= mhd= nhd= mbd= vt= forks=` and into `manifest.node_startup[<inst>]`. All but the vote timeout must match `node_git_sha`, `consensus_parameters` and `node_fork_schedule`. `bench-validator-01` goes first, and the first mismatch stops the run before any other node restarts. A build that does not log the three delay lines waits out the 300-second deadline (`POSTCFG_WAIT_SECS` in the remote script) and then fails. |
| 10 | Health gate: `wait_healthy` on every node; an IAP tunnel to `bench-validator-01:8545` on `localhost:18545` shows chain id 32286; Prometheus reports `count(count by (node)(tn_engine_canonical_height{network="bench"})) == 11`, `min by (node)(tn_primary_round{network="bench"})` rising on all 11 nodes across samples 30 s apart, and no bench node series with `network="devnet"`. Right after the chain id check, `recovery-schedule.py` reads the ConsensusRegistry through the tunnel, and its epoch duration must equal `EPOCH_DURATION_SECS`. The reading goes into `manifest.registry_probe`. |
| 11 | With `--with-contracts` only: a worktree of `tn-contracts-devnet-relaunch` on `bench/<run>`, `deployments-devnet.json` copied over `deployments-testnet.json` (chain 32286 reads the testnet book), then `devnet-contracts.sh --yes` through the tunnel. The result is saved as `results/<run>/deployments-bench.json`. |
| 12 | Grants the compute service account `secretAccessor` on the two bench secrets and creates `gs://tn-devnet-bench-<run>` with the benchmark labels. Then checks that the archive bucket `gs://tn-devnet-benchmark-archive` exists, or creates it (uniform bucket-level access, public access prevention, labels `purpose=bench-archive,retain=true`). If the bucket can be neither read nor created, the step stops, because the teardown would refuse to delete anything later. |
| 13 | Fund: the `bench-funder` VM runs `blast --prepare` for all 10 × `BENCH_SENDERS` senders, then is deleted. |
| 14 | Blast: `bench-blaster-01..10` start together five minutes after creation, each against its own validator's internal IP. The chaos schedule and abort watchers run alongside. |
| 15 | Collect: sampler CSVs over IAP, blaster results from the bucket, then `tn-transaction-generator/bench/collect-gcp-metrics.py`. An IAP copy that IAP refuses (error 4003, 4033 or 4047) is retried up to `BENCH_IAP_RETRIES` attempts (default 3), 10 s and then 20 s apart, and lands under a `.part` name until it is complete. With `BENCH_COLLECT_ARCHIVE=1` (the default), the step then copies `results/<run>/` and the run bucket to the archive and records `manifest.archive.collect_sync_at`. A failure there is only a warning, because the teardown's archive gate makes the copy that counts. |
| 16 | With `--with-teardown` only: `benchmark-teardown.sh --yes`. |

### Progress means consensus rounds, not blocks

An idle TN chain sits at **block 0**. The engine skips empty consensus outputs that do not close
an epoch (`skipping execution for empty non-epoch-closing output`), so `eth_blockNumber` only
moves once there are transactions, which means after the funder runs. Consensus runs anyway:
`tn_primary_round` rises about once a second and the node logs `quorum reached` / `subdag
committed`. Steps 9 and 10 and the `quorum-lost` watcher therefore judge liveness by
consensus rounds. `block=` in the sampler's `BENCH_STATUS` line is informational only.

### Chaos schedule (step 14)

Offline checks: `python3 -m unittest discover -s benchmark/tests -v` and
`python3 benchmark/tests/check_mutations.py`. CI also checks Bash syntax and ShellCheck.

By default (`BENCH_CHAOS_TIMING=epoch`), the operator opens the existing RPC tunnel and reads
the registry at a pinned execution block. The preceding closing block's timestamp anchors
the schedule. After at least `BENCH_CHAOS_MIN_LOAD_SECS=600` seconds of planned mixed load,
the drill kills validator-05 `BENCH_CHAOS_BEFORE_CLOSE_SECS=59` seconds before an eligible
epoch boundary. It restarts after `BENCH_CHAOS_DOWNTIME_SECS=300` seconds from the kill and
restarts the observer `BENCH_CHAOS_OBS_AFTER_BACK_SECS=300` seconds later. An unavailable
epoch read stops the run before load VMs are created. A restart scheduled after the workload
also stops the run, so extend `BENCH_DURATION_SECS` for long outages.

Use `BENCH_CHAOS_BEFORE_CLOSE_SECS=600 BENCH_CHAOS_DOWNTIME_SECS=900` for a mid-epoch
kill that still crosses the boundary. The offset must fit the measured epoch duration and
the downtime must exceed the offset. The drill keeps its existing owed-restart cleanup.

Each action is staged so it lands on time. `BENCH_CHAOS_STAGE_SECS=30` seconds before it is
due, the run opens one IAP session and sends a short script on stdin (`sudo bash -s`). The
script saves the container log, waits on the node's own clock for the due time, prints
`BENCH_CHAOS_BEGIN`, runs the action and prints `BENCH_CHAOS_END`. In epoch mode the restart is
due `BENCH_CHAOS_DOWNTIME_SECS` after the kill's node-side begin, and the observer restart
`BENCH_CHAOS_OBS_AFTER_BACK_SECS` after the restart's. No poll starts within
`BENCH_CHAOS_GUARD_SECS=90` seconds of a due action; it runs right after the action instead.
If the session fails before `BEGIN`, the action falls back to a direct `--command` at its due
time and is recorded with `staged: false`. Before staging, r20261006-0053 killed 17 s late
(a long poll, the log save and the IAP setup all ran first), and both restarts inherited it.

Run `benchmark/benchmark-blast.sh chaos-stage-test --instance <node> --yes` once against a
live fleet before a blast. It sends the same script with the harmless action `true`, due
`BENCH_CHAOS_STAGE_SECS` ahead, saves that node's container log as
`telcoin-stage-test-<UTC>.log.gz`, and prints `BEGIN`, `END` and how late the action began.
It fails when the markers do not come back. Without `--yes` it only checks that the script
parses.

`manifest.chaos_schedule` records the measured epoch, anchor block/hash and planned times; the
kill's `chaos[]` entry repeats them as `planned` (`closing_epoch`, `boundary_unix`,
`restart_unix`). Whether the outage crossed the boundary is measured, not assumed. After the
restart, each poll asks the registry for the block that opened the next epoch until it has
opened. `manifest.chaos_boundary` then records that block, and the kill's entry gets
`boundary_unix` and `crossed_boundary`: true when kill begin < boundary < restart begin, on
the node's clock. A `chaos-boundary` note gives the verdict and the times. If the epoch has not
opened by the end of the watch, `crossed_boundary` is null and the note says so. A registry
entry at block height 0 counts as not opened, because the registry records the next epoch
before it starts. Mixed timing records no boundary fields. `chaos-remote.log` keeps the raw
output of every session, failed ones included.

Enable `--log.stdout.filter 'info,state-sync=debug,consensus-chain=debug,tn::observer=debug'`
in the deployed node command before a recovery investigation. The sampler appends decimal
block height to each CSV row and inventories epoch-pack sizes and modification times every
minute. `collect` pulls both files. Teardown pulls them again with the service journal into
`logs/<node>-recovery-<instance-id>.*.tgz` before deleting anything. Missing sampler files
on an older deployment are allowed; a failed transfer or invalid archive stops teardown.
Retries reuse a readable archive only for the same VM instance ID.
The existing explicit `BENCH_TEARDOWN_SKIP_LOGS=1` override also covers this evidence.

For the legacy `BENCH_CHAOS_TIMING=mixed` mode, the mixed phase starts at
`BENCH_START_AT + preamble + warmup`. From that point:

- **+15 min**: `docker kill -s KILL telcoin` on `bench-validator-05`, followed immediately by
  `systemctl stop telcoin`. The unit has `Restart=on-failure`, so without the stop it would
  come back after 10 s instead of staying down. `bench-blaster-05` targets only this node,
  so its sends fail for the whole outage by design (the generator resends on connection
  errors). The kill's `chaos.note` says so and `manifest.notes` gets a `blaster-05-outage`
  entry, so the report does not count this as a blaster fault.
- **+20 min**: `systemctl start telcoin` on `bench-validator-05`. `docker start` cannot work
  here because the unit runs `docker run --rm`. This restart happens even if the run has
  already aborted.
- **+25 min**: `systemctl restart telcoin` on `bench-observer-11`.

Each action goes into `manifest.chaos[]`. `ts` is its node-side begin. `begin_unix` and
`end_unix` (node clock, ms), `planned_unix`, `late_secs` (begin minus planned) and `staged` sit
beside `rc`, the action's own exit code from `BENCH_CHAOS_END` (the ssh exit code when that line
never came back). Set `BENCH_CHAOS=0` to skip the schedule, or move it with
`BENCH_CHAOS_{KILL,BACK,OBS}_AT_SECS`.

## Abort rules

The run watchers poll every `BENCH_POLL_SECS` (240 s minimum; sustained IAP polling gets
throttled, see `tasks/lessons.md`). They read each node's `BENCH_STATUS` serial line, which
`node-sampler.sh` writes every two minutes, and obs-devnet memory from Cloud Monitoring, so
the loop itself makes no SSH calls. The first rule to trip sets `manifest.abort`, stops every
blaster (`docker stop txgen`) and allows 10 minutes for the results to upload. A poll that
would start within `BENCH_CHAOS_GUARD_SECS` of a chaos action waits until the action has run.

| Reason | Trigger |
|---|---|
| `disk-full` | a bench node's root disk is above 85 % |
| `obs-memory` | obs-devnet memory is above 85 % |
| `batch-cache-cliff` | `FatalDBFailure` shows up in a node's `docker logs telcoin`. This is the batch-cache defect, **not** a hardware limit, and the report must say so. |
| `quorum-lost` | two consecutive polls in which no node's `max by (node)(tn_primary_round{network="bench"})` advanced. A failed Prometheus query counts as unknown, never as stalled. |
| `node-stalled` | one validator's epoch/round stays unchanged for two consecutive polls while peers advance. Planned outages and pauses are exempt. Observers and missing metrics are not counted; an unknown poll resets the comparison. The victim's log is saved before aborting. |

Commit stalls are noted, never aborted on. Consensus rounds can keep advancing while blocks
stop (r20261006-0053: 301 s at block 15513), so `quorum-lost` does not catch one. Each poll
reads every `BENCH_STATUS` sample since the previous poll. When the fleet's highest block has
not moved for `BENCH_STALL_NOTE_SECS=60` seconds, the run prints one `⚠ commits flat` line.
When the block moves again, `manifest.commit_stalls[]` gets `{start, end, secs, block,
round_start, round_end, source: "watch"}` and a note; rounds use the watcher's
epoch × 10^8 + round form, and the bounds are sample times. Only a stretch that starts in the
planned mixed phase counts: in cooldown the generator only drains, so blocks stop by design.
`collect` runs `stall-scan.py` over the sampler CSVs (fleet maximum per 30 s, same window)
into `manifest.commit_stalls_sampled`, and notes any sampler file it could not copy.

A blaster is deleted only when its serial marker says `rc=0 reason=ok`, which means its
results are in the bucket. A failed upload reports `rc=75 reason=upload-failed`. Any other
outcome makes the script fetch `/var/lib/bench/out` over IAP first. It deletes the VM only if
that fetch worked, and otherwise keeps it and says so. The funder is handled the same way.

If `run` exits early (an error, Ctrl-C or TERM), its exit trap first restarts
`bench-validator-05` if its restart was still owed and records `manifest.abort =
interrupted`. It then deletes the blasters if they had not started yet, or else stops them,
waits for their markers and settles them as above (`--keep` leaves them running). If the
operator machine dies, the blasters finish on their own and upload to the bucket. Run
`benchmark-blast.sh collect` and `benchmark-blast.sh delete` afterwards.

## Outputs (`results/<run>/`, gitignored)

- `manifest.json`: `tn-bench-manifest/v1` (see
  `tn-transaction-generator/bench/schema/manifest.example.json`), plus the provenance fields
  below
- `pre-instances.json`, `pre-firewall.json`: project state before the run; teardown compares against them
- `blasters/<name>.json` (`tn-blast/v2`), plus each blaster's docker log and generator log
- `funder/prepare.json`, `sampler/<node>.csv`, `deployments-bench.json`, `metrics.json`
- `logs/`: every node's logs, their pull markers and the recovery evidence, saved by the teardown
- `bucket/<name>/`: the run bucket, copied here by the teardown before it deletes the bucket
- `genesis/`: moved here from `benchmark/genesis/` at teardown, so the next run starts clean

The teardown also copies the whole directory to the archive, apart from `genesis*/` (validator
keystores), `tunnel.pid` and dot-files:

```
gs://tn-devnet-benchmark-archive/runs/<run>/results/        results/<run>/
gs://tn-devnet-benchmark-archive/runs/<run>/bucket/<name>/  each run bucket, copied before its delete
```

`manifest.archive` records the copy: `uri` (`BENCH_ARCHIVE_PREFIX`), `status` (`pending`, then
`verified-before-delete`, or `unverified` under the override), `verified_at`, `final_sync_at`
and `collect_sync_at`. The publishing scrub drops it, together with `project` and `notes`.

The provenance fields record which bytes the run measured:

| Field | Written by | Holds |
|---|---|---|
| `harness` | manifest creation | `sha` of this checkout, `dirty` (tracked files differ from HEAD; untracked files do not count) and the `submodules` HEADs of `common` and `tn-node-deployment` |
| `node_image_ref`, `node_image_digest`, `node_image_pinned` | gate | the ref probed, its digest, and the `<repo>@sha256:` ref the fleet runs |
| `node_version`, `node_git_sha`, `node_fork_schedule` | gate | the version and git sha from `telcoin -V` and `--version`, and the fork-schedule label from the contract strings |
| `node_probe` | gate | `at`, `flags_ok` and `strings`, the count of each contract string in the binary |
| `consensus_parameters` | gate | `file`, `sha256`, `max_header_delay_ms`, `min_header_delay_ms`, `max_batch_delay_ms` |
| `node_startup[<inst>]` | step 9 | `sha`, `mhd`, `nhd`, `mbd`, `vt` and `forks` from the node's boot lines |
| `registry_probe` | step 10 | the `recovery-schedule.py` reading: current epoch, its opening block and duration, and the drill it would schedule from that moment |
| `node_startup_check` | teardown | the saved logs checked against `node_git_sha` (informational) |

## Teardown guarantees

`benchmark-teardown.sh` collects its candidates first: bench instances, bench firewall rules,
buckets labelled `benchmark=1` or named `tn-devnet-bench-*` (copied into
`results/<run>/bucket/` first; a non-empty bucket whose copy fails is left in place), orphaned bench
disks, the compute SA's bindings on the bench secrets, the contracts worktree, `bench/r*`
branches with no commits of their own, and local IAP tunnels. The archive bucket is never a
candidate: `config.sh` refuses an archive name that matches `tn-devnet-bench-*` or labels
that carry `benchmark=` or `bench-run=`, and the bucket listing skips the archive by name. It
deletes nothing if any single guard fails. It keeps the `bench-txgen-*` secrets unless you
pass `--purge`. At the end it prints the "left nothing" checks, which confirm that no labelled
or `bench-*` resource remains, that every devnet instance is still present, and that
`devnet-allow-consensus` matches the pre-run snapshot. It also prints how many objects the
run has in the archive; the archive is kept.

Nothing is deleted until three gates pass, in this order:

1. **Logs.** Every live node's logs are pulled to `results/<run>/logs/` (`BENCH_TEARDOWN_SKIP_LOGS=1` overrides).
2. **Recovery evidence.** Each node's service journal and sampler files are pulled.
3. **Archive.** The teardown makes sure the archive bucket exists, sets `manifest.archive.status`
   to `pending`, copies `results/<run>/` and every candidate bucket to
   `BENCH_ARCHIVE_PREFIX`, and then lists the archive once. Every `logs/*.log.gz`, pull
   marker, `logs/*-recovery-*.tgz` and `manifest.json` must be there at its local size.
   The status then becomes `verified-before-delete` and `manifest.json` is uploaded again. If
   any of this fails, the teardown prints `archive … failed — NOTHING was deleted` and exits 1;
   re-run it once the bucket is reachable. `BENCH_TEARDOWN_SKIP_ARCHIVE=1` still tries the
   copy, but deletes even if it fails, sets the status to `unverified` and adds a
   `manifest.notes` entry.

Every copy has an alarm (`BENCH_ARCHIVE_TIMEOUT_SECS`, default 1800 s) and a closed stdin. A
copy only adds or replaces objects, so a later sync never removes what an earlier one saved.
After the deletes and the provenance check below, `results/<run>/` is synced once more, which
picks up the run bucket's local copy and the final manifest, and the time goes into
`manifest.archive.final_sync_at`. That last sync only warns when it fails. The dry run prints
the archive prefix, whether the bucket exists or would be created, and every copy command.

Before the final sync, once teardown has saved the node logs and finished the deletes, it runs
an informational provenance check:

```bash
python3 benchmark/report/provenance.py --run-dir benchmark/results/<run> --update-manifest
```

It finds each node's start line in the saved logs, compares the build with
`manifest.node_git_sha` and writes the result to `manifest.node_startup_check`. A mismatch adds
a warning and a `manifest.notes` entry, and finding no start lines is a warning. With
`BENCH_TEARDOWN_SKIP_LOGS=1` it reads whatever logs were saved. It never blocks the teardown.

## Publishing

`benchmark/report/make_bundle.py` turns one run's results into a scrubbed bundle for the public
benchmark site. It reads `results/<run>/` without changing it and works in
`work/report/<run>/`. It checks the node logs against `manifest.node_git_sha` and refuses a
mismatch unless you pass `--allow-provenance-mismatch`. It exits 1 when the finished bundle
fails its own leak scan or the site's check. [`report/README.md`](report/README.md) covers
the pipeline, the flags and the backfill format.

Findings from a run that still need work, and that the public bundle must not carry, go in
`benchmark/private/followups.md`. `private/`, `work/`, `results/` and `genesis/` under
`benchmark/` are gitignored and never committed.
