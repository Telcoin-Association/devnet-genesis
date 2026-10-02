# Benchmark profile

A throwaway Telcoin Network fleet for load testing, built in the `tn-devnet` project next to
the live devnet and removed afterwards. Ten validators and one observer run chain **32286**
(devnet is 32285) with 20-minute epochs. One COS blaster VM per validator drives
`tn-transaction-generator blast` at it, while a sampler on every node and obs-devnet's
Prometheus record what the nodes do.

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
  `forge` for `--with-contracts`.
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

## Runbook

Pick a run id and use it for every command: `BENCH_RUN_ID=r$(date -u +%Y%m%d-%H%M)`.

```bash
# 0. Read the plan. This makes no GCP calls.
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --with-contracts

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

# 2. Tear down. Read the dry run, then apply.
benchmark/benchmark-teardown.sh --run r20260923-0100
benchmark/benchmark-teardown.sh --run r20260923-0100 --yes           # --purge also deletes the bench secrets
```

Every script is a dry run unless you pass `--yes`, and prints each gcloud argv before it
runs it.

### What the deploy does

| Step | What happens |
|---|---|
| 0 | Preflight checks: auth, tools, accounts file, empty `genesis/`, no foreign rule selecting `bench-node`, obs-devnet `/mnt/obs-data` below 70 %, CPU quota. Writes the pre-snapshots and `manifest.json`. |
| 1 | Asserts the `:blast-v2-<sha>` tag, builds it with Cloud Build if missing, and probes `blast --help` for the CLI contract flags (when docker is available). |
| 2 | Runs `common/create-instances.sh` on the bench profile, then asserts `tags == [bench-node]` and `labels.benchmark == 1` on every node, labels the boot disks and records `manifest.instances[]`. |
| 3 | Waits for the `devnet-startup.sh complete` serial marker on each node. |
| 4 | `benchmark-firewall.sh apply`: `bench-allow-consensus` (udp 49590/49594 from the nodes' own /32s) and `bench-allow-iap-rpc` (tcp 8545 from IAP). |
| 5–7 | The devnet drivers, on the bench profile: keygen, genesis build (in `benchmark/`) and finalize. |
| 8 | Metrics-only observability in one IAP session per node. `setup-observability.sh` would label the node `network="devnet"` (it derives the label from the node's network), so it is pointed at a black-hole metrics URL. In the same session Alloy is stopped, its WAL wiped, the env set to `TN_CHAIN=bench`, `TN_NODE=<instance>` and the real obs-devnet URL, and Alloy started again. No devnet-labelled sample leaves a bench node. |
| 9 | One IAP session per node, run serially. It rebinds reth `--http.addr` to 0.0.0.0, checks the bench Alloy labels, restarts the node, waits until the internal IP answers `eth_chainId == 0x7e1e` and consensus is progressing (the block height rose, or the node's `docker logs` show `subdag committed`/`quorum reached` since the restart; connection refusals while the node restarts are retried until the deadline), then installs `bench-node-sampler.service`. Serial order keeps at most one node down at a time. |
| 10 | Health gate: `wait_healthy` on every node; an IAP tunnel to `bench-validator-01:8545` on `localhost:18545` shows chain id 32286; Prometheus reports `count(count by (node)(tn_engine_canonical_height{network="bench"})) == 11`, `min by (node)(tn_primary_round{network="bench"})` rising on all 11 nodes across samples 30 s apart, and no bench node series with `network="devnet"`. |
| 11 | With `--with-contracts` only: a worktree of `tn-contracts-devnet-relaunch` on `bench/<run>`, `deployments-devnet.json` copied over `deployments-testnet.json` (chain 32286 reads the testnet book), then `devnet-contracts.sh --yes` through the tunnel. The result is saved as `results/<run>/deployments-bench.json`. |
| 12 | Grants the compute service account `secretAccessor` on the two bench secrets and creates `gs://tn-devnet-bench-<run>` with the benchmark labels. |
| 13 | Fund: the `bench-funder` VM runs `blast --prepare` for all 10 × `BENCH_SENDERS` senders, then is deleted. |
| 14 | Blast: `bench-blaster-01..10` start together five minutes after creation, each against its own validator's internal IP. The chaos schedule and abort watchers run alongside. |
| 15 | Collect: sampler CSVs over IAP, blaster results from the bucket, then `tn-transaction-generator/bench/collect-gcp-metrics.py`. |
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

`manifest.chaos_schedule` records the measured epoch, anchor block/hash, and planned times.
`manifest.chaos_boundary` records the actual block that opened the next epoch.
`chaos-remote.log` records the remote host's action begin/end times, including failed actions.
These observed times establish how close the kill really landed to the boundary.

Enable `--log.stdout.filter 'info,state-sync=debug,consensus-chain=debug,tn::observer=debug'`
in the deployed node command before a recovery investigation. The sampler appends decimal
block height to each CSV row and inventories epoch-pack sizes and modification times every
minute. `collect` pulls both files. Teardown pulls them again with the service journal into
`logs/<node>-recovery-<instance-id>.*.tgz` before deleting anything. Missing sampler files
on an older deployment are allowed; a failed transfer or invalid archive stops teardown.
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

Each action goes into `manifest.chaos[]` with its timestamp and exit code. Set
`BENCH_CHAOS=0` to skip the schedule, or move it with `BENCH_CHAOS_{KILL,BACK,OBS}_AT_SECS`.

## Abort rules

The run watchers poll every `BENCH_POLL_SECS` (240 s minimum; sustained IAP polling gets
throttled, see `tasks/lessons.md`). They read each node's `BENCH_STATUS` serial line, which
`node-sampler.sh` writes every two minutes, and obs-devnet memory from Cloud Monitoring, so
the loop itself makes no SSH calls. The first rule to trip sets `manifest.abort`, stops every
blaster (`docker stop txgen`) and allows 10 minutes for the results to upload.

| Reason | Trigger |
|---|---|
| `disk-full` | a bench node's root disk is above 85 % |
| `obs-memory` | obs-devnet memory is above 85 % |
| `batch-cache-cliff` | `FatalDBFailure` shows up in a node's `docker logs telcoin`. This is the batch-cache defect, **not** a hardware limit, and the report must say so. |
| `quorum-lost` | two consecutive polls in which no node's `max by (node)(tn_primary_round{network="bench"})` advanced. A failed Prometheus query counts as unknown, never as stalled. |
| `node-stalled` | one validator's epoch/round stays unchanged for two consecutive polls while peers advance. Planned outages and pauses are exempt. Observers and missing metrics are not counted; an unknown poll resets the comparison. The victim's log is saved before aborting. |

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
  `tn-transaction-generator/bench/schema/manifest.example.json`)
- `pre-instances.json`, `pre-firewall.json`: project state before the run; teardown compares against them
- `blasters/<name>.json` (`tn-blast/v2`), plus each blaster's docker log and generator log
- `funder/prepare.json`, `sampler/<node>.csv`, `deployments-bench.json`, `metrics.json`
- `genesis/`: moved here from `benchmark/genesis/` at teardown, so the next run starts clean

## Teardown guarantees

`benchmark-teardown.sh` collects its candidates first: bench instances, bench firewall rules,
buckets labelled `benchmark=1` or named `tn-devnet-bench-*` (copied into
`results/<run>/bucket/` first; a non-empty bucket whose copy fails is left in place), orphaned bench
disks, the compute SA's bindings on the bench secrets, the contracts worktree, `bench/r*`
branches with no commits of their own, and local IAP tunnels. It deletes nothing if any
single guard fails. It keeps the `bench-txgen-*` secrets unless you pass `--purge`. At the
end it prints the "left nothing" checks, which confirm that no labelled or `bench-*`
resource remains, that every devnet instance is still present, and that
`devnet-allow-consensus` matches the pre-run snapshot.
