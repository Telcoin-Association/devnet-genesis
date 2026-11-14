# Benchmark profile

A throwaway Telcoin Network fleet for load testing, built in the `tn-devnet` project next to
the live devnet and removed afterwards. Ten validators and one observer run chain **32286**
(devnet is 32285) with 20-minute epochs. Each node is a `c3-highcpu-8` with a 100 GB
`hyperdisk-balanced` boot disk unless you pick another shape (see [Fleet shape](#fleet-shape)).
One COS blaster VM per validator drives `tn-transaction-generator blast` at it, while a sampler
on every node and the run's own Prometheus (on `bench-obs`, a VM the run creates and deletes)
record what the nodes do.

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
- `obs-devnet`, devnet's obs VM. The bench neither reads nor writes it: no metrics, no logs,
  no secret, no disk check. It never runs `create-obs-instance.sh` (and so never `--wipe-data`)
  or `devnet-observability.sh`. The run's metrics go to a VM of its own, `bench-obs`, which
  deploy step 2 creates and the teardown deletes (see [The obs VM](#the-obs-vm-bench-obs)). The
  nodes ship it **metrics only**, labelled `network="bench"`, and no logs at all.
- The devnet tn-contracts checkout. Contracts deploy from a disposable worktree on a
  `bench/<run>` branch, which is never committed to.

`benchmark/config.sh` only loads for an allowlist of callers: the `benchmark-*.sh` scripts
and the shared drivers they run (`devnet-keygen.sh`, `devnet-genesis-build.sh`,
`devnet-network-config.sh`, `devnet-finalize.sh`, `devnet-contracts.sh`,
`common/create-instances.sh`). `devnet-network-config.sh` is there for step 7: it reads the fleet
from the profile and installs a Closed-admission `network-config` on every bench node before any
node starts, rendering the files under `benchmark/genesis/network-config/`. Every other script
started with `CONFIG_FILE=benchmark/config.sh` exits before doing anything, including the
devnet-only drivers, the wgvpn tools, and scripts added later. `devnet-observability.sh` is
deliberately not on the list (see step 8). The profile also refuses to be sourced in an
interactive shell, because its exports would leak into a later devnet command.

## Before the first run

- `gcloud auth login` as an account with Compute, Secret Manager, Storage and IAM rights in
  `tn-devnet`. You also need `cast`, `jq`, `python3` with PyYAML (`python3-yaml`; step 7's
  drivers parse YAML with it), `docker` and `git` locally, plus `forge` for `--with-contracts`.
  `TN_NODE_SCRIPTS_REF` (from `../config.sh`) must be a full 40-hex sha; step 0 and the gate for
  step 7 refuse anything else. Docker must be running: the gate examines the node image
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
- The `common` submodule is checked out. `bench-obs` boots from its
  `observability/obs-vm/startup-obs.sh` and its Grafana serves the dashboards under
  `observability/obs-vm/grafana/dashboards`; step 2 stops when the startup script is missing.
- Nothing on obs-devnet: no Grafana secret, no ingest token, no free disk. `bench-obs` takes no
  ingest auth (step 8's token is a throwaway from `openssl rand -hex 16`), and step 0 no longer
  looks at obs-devnet's `/mnt/obs-data`. Step 0's quota check counts `bench-obs` in its own
  region (`BENCH_OBS_ZONE`'s): the vCPUs of `BENCH_OBS_MACHINE_TYPE` (4 of `CPUS` for
  `e2-standard-4`), one `IN_USE_ADDRESSES` and `SSD_TOTAL_GB` for its 20 GB boot disk plus its
  `BENCH_OBS_DISK_GB` data disk (70 GB by default). A region holding `bench-obs` and no node is
  checked for those alone.
- A `--yes` run checks all of this before its first step: the image, `cloudbuild.yaml`,
  `config.bench.toml` and `results/<run>/deployments-bench.json` (unless step 11 will make it).
  When a selected step deploys the node image, it also probes that image and pins the run to
  its digest (see [Node image](#node-image)).

These knobs change how the harness works. Most leave what it measures alone; the light-load arm
(`BENCH_LIGHT_*`), `BENCH_WINDOW` and `BENCH_NODE_DB_SYNC_MODE` change it, and at their defaults the
blast and the node command are bench 4's. `config.sh` sets each one only
when it is unset, so a value exported before the run wins. The root drivers keep their devnet
behaviour (the driver default) unless the bench profile or the operator sets the knob.

| Variable | Bench value | Driver default | What it does |
|---|---|---|---|
| `BENCH_LOGROTATE_SIZE` | `20G` | | Step 7 replaces v2's `/etc/logrotate.d/telcoin` with the bench's own: v2's template without `maxsize`, rotating the unit logs once they pass this size. `<n>K`, `<n>M` or `<n>G`; empty leaves v2's file (100 MB, `maxsize 1G`) alone. See [Node log filter](#node-log-filter). |
| `BENCH_NODE_DB_SYNC_MODE` | empty | | Step 7's pre-start config puts `--db.sync-mode <value>` on every node's command (through `tn_launch_flag_set`, read back like the other launch flags) and adds `dbsync=<value>` to the `PRECFG_OK` line. `durable` or `safe-no-sync`; empty (the default) adds no flag, so the node runs the image's default (durable) and the pre-start script is bench 4's byte for byte. `safe-no-sync` skips the MDBX fsync on commit: never for a published run (kept for a bench-6 arm). The value goes into `manifest.node_startup[<inst>].db_sync_mode` (`durable` when unset); `report/make_bundle.py` refuses a run with any `safe-no-sync` node unless given `--allow-safe-no-sync`, and then caveats the bundle. |
| `BENCH_NODE_JOBS` | `4` | | Per-node sessions of steps 7 (pre-start config) and 9 (verify) run this many at a time. Each node's output is printed whole, in fleet order; a node that fails does not stop the others, and the step stops once they have all ended, naming the failed nodes. `1` runs the nodes one after the other and stops at the first failure. |
| `FINALIZE_JOBS` | `4` | `1` | `devnet-finalize.sh` works on this many nodes at once, its output printed in target order. With `--stage-only` or `--defer-start` it refuses a value that reaches a quorum of the validators (exit 2), since that many units run together before their stops. |
| `KEYGEN_JOBS` | `4` | `1` | `devnet-keygen.sh` keys this many nodes at once, each node's output printed whole, in index order. |
| `NETCFG_JOBS` | `4` | `1` | `devnet-network-config.sh` works on this many nodes at once, each node's output printed whole, in fleet order. |
| `NETCFG_FAST` | `1` | `0` | network-config takes at most two IAP sessions a node: one reads everything, the merge and validation run locally, and a node whose file is already right is left alone (`unchanged (not written)`); otherwise one more session installs the file and reads it back. |
| `NETCFG_TRUST_OBSERVERS_EVERYWHERE` | `1` | `0` | Every validator trusts every observer and every observer every validator (`devnet-network-config.py --trust-observers-everywhere`, render and validate). Bootstrap peers stay the hub's. `devnet-finalize.sh` reads it too: its gate and A3 check validate each node's network-config in the same context, so the two drivers must see the same value. |
| `KEYGEN_REUSE_EXISTING` | `1` | `0` | A node that refuses keygen because it is keyed already, or whose keygen sent no done line (a dropped session), is checked again: when its `.node-meta` records its own `VALIDATOR_ADDRESS` and its `node-info.yaml` is not empty, that file is downloaded (`already keyed … reusing`). Keyed for another address, it fails. So a re-run of step 5 after a partial keygen goes on. |
| `KEYGEN_RPC_ADVERTISE` | `internal-ip` | `domain` | `node-info.yaml` advertises `http://<internal IP>:8545/` and `ws://<internal IP>:8546/`, the node's own listeners, instead of the unresolvable `<node>.bench.invalid`. |
| `KEYGEN_REPORT` | `1` | `0` | Keygen prints `KEYGEN_DONE <inst> rc= secs= reused= rpc_http= rpc_ws=` per node; step 5 records them (see [What the deploy does](#what-the-deploy-does)). |
| `BENCH_LIGHT_LOAD` | `0` | | `1` makes steps 13 and 14 (`benchmark-blast.sh fund` and `run`) run the light-load arm: one light blast per `BENCH_LIGHT_SENDERS` entry, then the configured profile, on the one fleet. See [Light-load arm](#light-load-arm-steps-13-14). `0` is the single blast of bench 4. |
| `BENCH_LIGHT_LOAD_AFTER` | `0` | | `1` adds one more light blast after the configured profile, with the first entry's senders and window. Leave it at `0` unless the committee is whole after the chaos. |
| `BENCH_LIGHT_SENDERS` | `8 16 600` | | Senders per blaster of each light blast, one blast per entry, in order: positive integers separated by single spaces. |
| `BENCH_LIGHT_WINDOWS` | `16 16 4` | | The `--window` of each light blast, paired with `BENCH_LIGHT_SENDERS` by position; `config.sh` refuses a list of another length. Empty gives every light blast `BENCH_WINDOW`. |
| `BENCH_LIGHT_WARMUP_SECS`, `BENCH_LIGHT_DURATION_SECS`, `BENCH_LIGHT_COOLDOWN_SECS` | `60`, `360`, `60` | | Each light blast's warm-up, mixed phase and cool-down, in seconds. |
| `BENCH_WINDOW` | `16` | | The generator's `--window`, the transactions each sender keeps in flight, for the configured profile (and for every light blast when `BENCH_LIGHT_WINDOWS` is empty). A blaster gets a `WINDOW` metadata key only when it is not 16, so a default blast's create argv is bench 4's; the funder never gets one. |
| `BENCH_LANDINGS_SAMPLE` | `0` | | `N` > 0 adds `--landings-out /out/landings-<label>.ndjson.gz --landings-sample N` to every blaster's generator (through a `LANDINGS_SAMPLE` metadata key, blasters only): one own landing in N, exported as gzipped NDJSON, which comes back as `blasters/landings-<blaster>.ndjson.gz`. The `blast --help` probe (deploy step 1, and the blast driver's) then requires both flags too, so an image without them stops the run before any VM. `0` adds nothing. |
| `BENCH_LOG_RATE_WARN_MB_MIN` | `30` | | The light-load arm's `LOG_RATE` lines (one per blast) end in a `⚠` above this many MB (10^6 bytes) per minute of one node's unit log. Never fatal. |
| `BENCH_LOG_TRANSFER` | `iap` | | How the teardown moves the node logs: `iap` (bench 4's pull, one IAP ssh stream per file) or `bucket` (each node gzips and uploads its own logs to the run bucket, then one local `gcloud storage cp -r`). See [Log transfer through the run bucket](#log-transfer-through-the-run-bucket): `bucket` needs node service accounts with a GCS write scope, which `common/create-instances.sh` does not give them yet. |
| `BENCH_PULL_JOBS` | `4` | | Nodes at a time in the bucket transfer's upload sessions and landing checks. Read by `pull-lib.sh` only; `config.sh` does not set it. |
| `BENCH_TEARDOWN_RECERTIFY` | `0` | | `1` makes a teardown re-run run the certification pass and its snapshots again although `manifest.certification` exists; with `0` a re-run skips them. See [Certification outcome](#certification-outcome). |
| `BENCH_SKIP_GCLOUD_ARGV_CHECK` | `0` | | `1` skips the dry-run teardown's gcloud argv check. Read by the teardown only; `config.sh` does not set it. See [Teardown guarantees](#teardown-guarantees). |

The knobs of the other parts sit with them: zone fallbacks under [Fleet shape](#fleet-shape),
`BENCH_COLLECT_WAIT_REJOIN` under step 15, `BENCH_CHAOS_REFRESH_SCHEDULE` under
[Chaos schedule](#chaos-schedule-step-14), the RPC tunnel's under [The RPC tunnel](#the-rpc-tunnel),
`BENCH_ADMISSION_DENIED_MAX` under step 10 and the teardown's under
[Teardown guarantees](#teardown-guarantees).

## Fleet shape

Ten validators, one per region, and an observer. Six of the ten are in Asia-Pacific. The order
is `ZONES` in `config.sh`:

| Index | Instance | Zone | Region | Role | Why this slot |
|---|---|---|---|---|---|
| 0 | `bench-validator-01` | `us-west2-a` | Los Angeles | validator | `ZONES[0]` also hosts the funder, and step 10's IAP tunnel lands here |
| 1 | `bench-validator-02` | `europe-west2-b` | London | validator | |
| 2 | `bench-validator-03` | `australia-southeast1-c` | Sydney | validator | `BENCH_LAG_IDX` default: the node lag injection pauses |
| 3 | `bench-validator-04` | `asia-northeast1-b` | Tokyo | validator | stockout fallback `asia-northeast1-c` |
| 4 | `bench-validator-05` | `us-east4-b` | Ashburn | validator | `CHAOS_KILL_IDX`: the node the chaos schedule kills. Moved from Montréal, where no c3 zone had `c3-highcpu-8` left; stockout fallbacks `us-east4-c`, `us-east4-a` |
| 5 | `bench-validator-06` | `europe-west4-a` | Netherlands | validator | |
| 6 | `bench-validator-07` | `asia-southeast1-b` | Singapore | validator | stands in for Jakarta: no asia-southeast2 zone offers `c3-highcpu-8` |
| 7 | `bench-validator-08` | `asia-east2-a` | Hong Kong | validator | stockout fallback `asia-east1-a` (Taiwan, another region) |
| 8 | `bench-validator-09` | `asia-northeast3-a` | Seoul | validator | stockout fallback `asia-northeast3-b` |
| 9 | `bench-validator-10` | `asia-south1-c` | Mumbai | validator | zone c is the only Mumbai zone with `c3-highcpu-8` |
| 10 | `bench-observer-11` | `us-west2-a` | Los Angeles | observer | beside validator-01; restarted by the chaos schedule |

Each validator's blaster runs in that validator's zone; the light-load arm runs several blasts on
the same fleet, one after another (see [Light-load arm](#light-load-arm-steps-13-14)). Moving a node
means editing `ZONES` only;
step 0 then checks the new zone before anything is created (see the runbook).

A zone can run out of `c3-highcpu-8` between step 0 and step 2. `BENCH_ZONE_FALLBACKS` names
where a node may go instead: space-separated `<index>:<zone>[,<zone>…]` items, the index being the
node's position in `INSTANCE_NAMES`. The default holds the fallbacks in the last column above,
`3:asia-northeast1-c 4:us-east4-c,us-east4-a 7:asia-east1-a 8:asia-northeast3-b`; an empty value
turns fallbacks off, and a stockout then stops the run. When `common/create-instances.sh` fails in
step 2, every node it names must have failed on a stockout (any other failure stops the step).
Each of them moves to its next fallback zone, and step 2 writes `results/<run>/zones.env`, one
line `BENCH_ZONES_USED=<zone of node 0> … <zone of node 10>`, then runs the create again. The
create skips the nodes that exist, and step 2 gives up after 3 rounds. `config.sh` reads
`zones.env` (it never sources it) and replaces `ZONES` with it, so every later script of the run,
the teardown included, addresses a moved node in its new zone; a `zones.env` whose zone count
differs from `INSTANCE_NAMES` stops every script that loads the profile. Each move goes into
`manifest.zone_fallbacks[]` (`{inst, from, to, reason: "stockout", ts}`) with a note, because the
node's latency is now its new zone's and the latency matrices lack that zone.
`manifest.zones_used` maps every node to the zone it was created in. Step 0 checks that every
fallback zone offers the machine type (a warning, not a stop), but it checks quota only in the
fleet's own regions, so `asia-east1` for validator-08 is not checked.

The default shape is `c3-hdb`: every node is a `c3-highcpu-8` with a 100 GB
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
| `BENCH_BLASTER_MACHINE_TYPES` | `e2-standard-2 n2-standard-2 n2d-standard-2` | Blaster types, tried in order. A create that fails on a zone stockout is retried at once on the next type; the type used is `manifest.blasters[].machine_type`. `BENCH_BLASTER_MACHINE_TYPE=<type>` pins one type with no fallback. |

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

### The obs VM (`bench-obs`)

The run's metrics live on a VM of their own, which goes with the fleet. Deploy step 2 creates it
(`bench_obs_create` in `benchmark/obs-lib.sh`), step 8 brings it up, and the teardown pulls a
Prometheus snapshot from it before deleting it.

- `bench-obs` in `us-west2-a`, an `e2-standard-4` running debian-12 on a 20 GB `pd-balanced` boot
  disk, plus a `pd-ssd` data disk `bench-obs-data` of 50 GB with device name `obs-data`, which the
  startup script formats and mounts at `/mnt/obs-data`. Both disks auto-delete with the VM.
- Tag `bench-obs` only (not `bench-node`, so no bench firewall rule selects it), and the run's
  labels plus `tn-role=obs` (`benchmark=1,network=bench,bench-run=<run>,tn-role=obs`) on the VM
  and on both disks. It gets the nodes' service account and scopes and an ephemeral external IP.
- The startup script is `common/observability/obs-vm/startup-obs.sh` (Docker, the Ops Agent, the
  data disk). Step 8 then copies the bundle in `benchmark/obs/` to `/opt/obs` with the dashboards
  from `common/observability/obs-vm/grafana/dashboards`, and starts it with `docker compose`:
  Prometheus `v3.1.0` (remote-write receiver, admin API on, retention `BENCH_PROM_RETENTION`) on
  port 9090 of the VM's internal IP and of loopback, and Grafana `11.4.0` on loopback port 3000
  with anonymous Viewer access and one Prometheus datasource (uid `prometheus`). `/opt/obs/.env`
  holds the bind IP, the retention and a random Grafana admin password; it is written once, mode
  600.
- Metrics only. No Loki, no DNS name, no Caddy or TLS, no static IP, no Secret Manager secret and
  no firewall rule. The nodes push to its VPC internal IP over `default-allow-internal`, and the
  operator reaches it only through two IAP ssh forwards on localhost (see
  [The RPC tunnel](#the-rpc-tunnel)).
- A `bench-obs` that already exists is kept only when it is this run's: exactly the tag
  `bench-obs`, `benchmark=1` and this run's `bench-run`. Any other stops step 2, so the bench
  never adopts a VM it did not create.

`manifest.obs` records `instance`, `zone`, `machine_type`, `disk_gb`, `created_at`, `internal_ip`
and `instance_id` (step 2), `ready_at`, `prom_local_port`, `grafana_local_port` and
`ship_logs: false` (step 8), and `prom_snapshot` (the teardown). The report's scrubber drops
`internal_ip`, `instance_id` and every `grafana_url`.

| Variable | Default | What it does |
|---|---|---|
| `BENCH_OBS_INSTANCE` | `bench-obs` | The VM's name. It must start with `bench-`, which keeps it among the teardown's candidates; the data disk is `<name>-data`. |
| `BENCH_OBS_ZONE` | `us-west2-a` | Its zone. Step 0 checks the machine type there and counts the VM's quota in its region. |
| `BENCH_OBS_MACHINE_TYPE` | `e2-standard-4` | |
| `BENCH_OBS_DISK_GB` | `50` | The `pd-ssd` data disk, in GB. |
| `BENCH_OBS_BOOT_TIMEOUT_SECS` | `600` | How long step 8 waits for the startup script's `[obs-startup] … done` on the serial console. |
| `BENCH_OBS_PROM_LOCAL_PORT` | `19090` | Local end of the Prometheus forward. |
| `BENCH_OBS_GRAFANA_LOCAL_PORT` | `13000` | Local end of the Grafana forward. |
| `BENCH_PROM_URL` | `http://127.0.0.1:19090/api/v1` | What every Prometheus read of the run queries, built from the local port. |
| `BENCH_GRAFANA_URL` | `http://127.0.0.1:13000` | Grafana through its forward; recorded as `manifest.prometheus.grafana_url`. |
| `BENCH_PROM_AUTH` | `0` | `0`: queries go straight to Prometheus on the forward, with no credentials. `1`: the path from before `bench-obs`, through the Grafana datasource proxy at `BENCH_GRAFANA_URL` with the admin password from Secret Manager (`OBS_GRAFANA_SECRET_NAME`) on curl's stdin. |
| `BENCH_PROM_RETENTION` | `7d` | Prometheus's retention on the VM: a number and one of `s m h d w y`. |
| `BENCH_OBS_DISK_MAX_PCT` | `70` | `bench_obs_require` warns when the data disk is at least this full. It never stops a run. |
| `BENCH_OBS_PULL_PROM` | `1` | `0`: the teardown pulls no Prometheus snapshot. |
| `BENCH_OBS_INTERNAL_IP` | unset | Read from `manifest.obs.internal_ip`. Set it only to override, such as for `--print-obs-script`; without either, dry runs and print modes show the placeholder host `bench-obs-internal-ip.invalid`. |

`BENCH_OBS_BUNDLE_DIR`, `BENCH_OBS_DASHBOARDS_DIR` and `BENCH_OBS_STARTUP_SCRIPT` point at the
bundle, the dashboards and the startup script above.

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

### Per-node values

`BENCH_NODE_PARAM_OVERRIDES` gives single nodes their own values on top of the file:
space-separated `<index>:<key>=<value>[,<key>=<value>...]` items, the index into `INSTANCE_NAMES`,
for example `"2:min_header_delay=50ms,max_header_delay=250ms 7:max_batch_delay=100ms"`. Durations
are `<int>ms` or `<int>s`. The keys are the node's `Parameters` (listed in `BENCH_NODE_PARAM_KEYS`);
`gc_depth` and `basefee_address` are refused because they must be the same on every node. config.sh
refuses a malformed item at load, and the gate refuses a node the node itself would refuse at
startup: `min_header_delay` above `max_header_delay`, a threshold outside
`1..max_header_num_of_batches`, or a `vote_timeout` (5 s when unset) below `max_header_delay` +
250 ms or at 10 s or more. The plan prints every node's resulting values.

Step 7's pre-start config writes a node's overrides into `<datadir>/parameters.yaml` while the
node is stopped, before the coordinated start. The datadir is `DATA_DIR` in the node's
`/etc/telcoin/.node-meta`, read once on the node; nothing parses it out of the start script (v2
finalize copies `parameters.yaml` from the genesis dir into `DATA_DIR`, so edits there stay). Each
line is rewritten in place, or appended, and marked `# bench-override`; a re-run rewrites the same
lines, and the script fails when the number of marked lines differs from the node's overrides.
Step 9 reads the file back from the same path. The gate records the overrides as
`manifest.consensus_parameters.overrides` (`{"<instance>": {"<key>": "<value>"}}`) when step 7
runs; a later range with a different `BENCH_NODE_PARAM_OVERRIDES` gets a warning, and step 9 then
checks the nodes against the new value. The fork-schedule check uses the smallest
`max_header_delay` of any node.

### Node log filter

`BENCH_NODE_LOG_FILTER` (default
`info,primary=debug,engine=debug,subscriber=debug,worker::network=debug,network::reqres=debug,primary::cert_validator=info,primary::cert_manager=info,primary::cert_fetcher=info`)
goes onto each node's command line at step 7 (pre-start config, with v2's `tn_launch_flag_set` on
`/usr/local/libexec/telcoin/tn-start-docker`) as `--log.stdout.filter` and `--log.file.filter`,
with `--log.file.max-files ${BENCH_NODE_LOG_MAX_FILES}` (default 20). What each target gives (the
timing lines named here are the bench 4 build's; an older image logs only some of them):

- `primary=debug`, with `primary::cert_validator`, `primary::cert_manager` and
  `primary::cert_fetcher` held at `info` to drop the per-certificate dumps: the whole primary.
  The proposer (`primary::proposer`: the parents and delays of each header, `header stored and
  sent` with its persist and send times), the certifier (`primary::certifier`: each vote request
  and response per peer with `round`, `attempt` and `elapsed_ms`, `vote requests issued` and
  `proposal lock acquired`), the voter (`Processing vote request from peer`, `Created vote`, and
  on `primary::network` one `vote path timing` line per request with each stage's milliseconds,
  `vote timeout fired` and `vote refused: header too new`) and the leader schedule
  (`primary::bullshark`: `scheduled leader`).
- `engine=debug`: each consensus output's execution and persistence (`output executed`,
  `persisted output`, `output execution task finished`).
- `subscriber=debug`: the consensus subscriber, including why a node that fell behind cannot
  rejoin yet (`rejoin not ready … reason=`).
- `worker::network=debug`: the worker's batch serving, including `batch-serve pool is full`
  denials.
- `network::reqres=debug`: every request-response exchange (`inbound request`, `response sent`,
  `response received`, `outbound request failed`) with its class and time.

Bench 3's default named `primary::certifier` and `primary::proposer`, which `primary=debug`
covers, and `tn_primary::network::handler=debug` for the voter's missing-parent lines. In the
bench 4 build every debug line of that handler carries the `primary::network` target, so
`primary=debug` selects them and the module-path directive would select nothing; it is gone.

The heavy diagnostic targets are opt-in: `network=debug` (the `request received` line, which
timestamps a vote request's arrival at the voter and carries the full header),
`multistream_select=debug`, `libp2p_swarm::connection::pool=debug` and `peer-manager=debug` (the
per-substream protocol negotiation and connection lifecycle, which stage 1 needed once to prove
the negotiation fix) and `network-kad=info`. They were the default in r20261007-0316, which logged
about 1 MB per node per round: ~3 GB/h raw per node idle, ~22 GB/h under load, and ~80 GB pulled
at teardown. `network=debug` is the bulk. Re-filtering bench-validator-01's log offline, the
default of that time without the heavy set kept about 31 % of the bytes of the first 24 minutes
after the stage-2 restart and 1.2 % of a 98-second slice under load, where `network` debug lines
were 97 % of the bytes. For a diagnostic run, append the heavy set to the default:

```
BENCH_NODE_LOG_FILTER="info,primary=debug,engine=debug,subscriber=debug,worker::network=debug,network::reqres=debug,primary::cert_validator=info,primary::cert_manager=info,primary::cert_fetcher=info,multistream_select=debug,libp2p_swarm::connection::pool=debug,peer-manager=debug,network=debug,network-kad=info"
```

Every container line lands on the node twice: in the docker json-file log and in the unit's
append file `/var/log/telcoin/telcoin.log` (the teardown pulls both, as `<node>-telcoin.log.gz`
and `<node>-unit-stdout.log.gz`). On v2 nodes the start script caps the json-file log at
50 MB × 3 (`--log-opt max-size=50m --log-opt max-file=3`), so `docker logs` holds only the newest
~150 MB. The unit file is the record: it spans every container run since finalize (v2 finalize
empties it before the node's first start), so it holds the stage-only run and then the
coordinated one. It is rotated, though: v2's `/etc/logrotate.d/telcoin` cuts it once it passes
100 MB and keeps five generations (`telcoin.log.1`, then `.2.gz` to `.5.gz`), which split bench 3's
evidence across files. So step 7 writes the bench's own rotation config, the same template
without `maxsize` and rotating at `BENCH_LOGROTATE_SIZE` (default `20G`), and the teardown pulls
every generation (see [Pull markers and re-runs](#pull-markers-and-re-runs)). Step 9 reads the
boot lines 30-55 min after the start, by which time a busy filter may have rotated them out of
`docker logs`. It then reads them from the unit file (the `StandardOutput=append:` path of the
unit, else `<NODE_LOG_DIR>/telcoin.log`), or from its `.1` or `.2.gz` generation when the live
file has no `starting` line, taking every field from the last `starting` block, which is this
container's run. The file log under
`<datadir>/.cache/reth/logs/telcoin-network-logs/` is a third copy, but it rotates at 200 MB per
file. `BENCH_NODE_LOG_FILTER=` (empty) leaves the command line as it is.
`manifest.node_startup[<instance>]` records `log_filter` and `log_max_files`.

### What step 9 reports

Step 9 restarts nothing. Each node's `POSTCFG_OK` line ends with the boot lines, then the
readback, then `back=-` (no restart, so no downtime to report):

```
POSTCFG_OK <inst> ... sha=<git> mhd=<ms> nhd=<ms> mbd=<ms> vt=<ms|?> forks=<label>
    max=<ms> min=<ms> batch=<ms> thr=<n> vote=<ms|-> filter=<filter|-> maxfiles=<n|-> back=-
```

The boot lines come from `docker logs --since` the container's `StartedAt`, or from the unit file
when they have rotated out of the capped json-file log (see Node log filter). `max`, `min`,
`batch`, `thr` and `vote` are read from `<DATA_DIR from .node-meta>/parameters.yaml` (`-` when
the file lacks the key); `filter` and `maxfiles` from the running container's command line
(`docker inspect telcoin`), which must also carry `--http.addr 0.0.0.0`, `--ws.addr 0.0.0.0` and
`--metrics 127.0.0.1:<METRICS_PORT>`. Both the boot lines and the file must show that node's
values (its override, else the manifest's), and the filter must be `BENCH_NODE_LOG_FILTER`, or
step 9 stops at that node. The unit must report `NRestarts=0`. They go into
`manifest.node_startup[<instance>]` as `params` and `log_*`.

Changing parameters on a live fleet between sweep arms is `tools/params-apply.sh`'s job (one node
restarted at a time, each arm recorded as `manifest.param_arms`; see `tools/README.md`, section
"params-apply"). Run its `--stage-test` on one node before the first arm of a fleet.

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

# Resume after a failure, or re-run one step. Step 7 can be re-run as a whole (--from 7): staged
# and running nodes are skipped (see "Step 7: one coordinated start").
benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 9
benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --only 15

# Record a deviation in manifest.notes while the run is in flight (a hand fix, a re-run; no GCP call):
benchmark/benchmark-deploy.sh --run r20260923-0100 --note "v05 restarted by hand at 00:12Z"

# Read a remote script before it runs (prints and exits; no GCP call):
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --print-prestart bench-validator-01    # step 7
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --print-obs-script bench-observer-11   # step 8, token shown as PLACEHOLDER-TOKEN
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --print-obs-bringup                    # step 8, the bench-obs bring-up
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --print-postconfig bench-validator-01  # step 9

# Stop after a step (a sweep deploys the fleet with --to 12, then blasts per arm with --from 13 --to 15
# under a new BENCH_RUN_INDEX each time):
BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --yes --with-contracts --to 12
BENCH_RUN_INDEX=1 benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 13 --to 15

# The light-load arm: light blasts, then the configured profile, on the same fleet (steps 13-14):
BENCH_LIGHT_LOAD=1 BENCH_LANDINGS_SAMPLE=100 benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 13 --to 15

# The blast phases on their own (steps 13-15 call exactly these):
benchmark/benchmark-blast.sh fund    --run r20260923-0100 --yes
benchmark/benchmark-blast.sh run     --run r20260923-0100 --yes      # --keep leaves the blasters up
benchmark/benchmark-blast.sh collect --run r20260923-0100 --yes
benchmark/benchmark-blast.sh status  --run r20260923-0100

# 2. Tear down. Read the dry run, then apply. Before the first delete it checks that
#    results/r20260923-0100/ (the only copy of the run) holds every node's logs and the manifest.
benchmark/benchmark-teardown.sh --run r20260923-0100
benchmark/benchmark-teardown.sh --run r20260923-0100 --yes           # --purge also deletes the bench secrets

# Only if a node's logs cannot be saved and the fleet must go anyway (recorded in manifest.notes):
BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 benchmark/benchmark-teardown.sh --run r20260923-0100 --yes
```

Every script is a dry run unless you pass `--yes`, and prints each gcloud argv before it
runs it.

The harness never deletes a node log. Each run's logs and results stay in `results/<run>/`,
the only copy: no bucket keeps another. The directory is gitignored and on one disk, so back it
up outside the repo once the teardown has finished.

### What the deploy does

| Step | What happens |
|---|---|
| gate | `--yes` only, before any step. Checks what the selected steps need: the `:blast-v2-<sha>` image, `cloudbuild.yaml`, `config.bench.toml` and `deployments-bench.json`. When step 0, 5, 6 or 7 is selected and the run has no pinned image yet, it probes the node image and pins it (see [Node image](#node-image)). It then creates `manifest.json`, or keeps it on a resume, and records the probe (`node_*`) and `consensus_parameters`. |
| 0 | Preflight checks: auth, tools, accounts file, empty `genesis/`, no foreign rule selecting `bench-node`; obs-devnet is not read. Then the fleet's footprint: the node machine type in every fleet zone, the first blaster type in every validator zone and `BENCH_OBS_MACHINE_TYPE` in `BENCH_OBS_ZONE` (one `machine-types describe` per zone and type), a hyperdisk type offered in every fleet zone, and quota headroom per region against what that region's nodes and blasters need, plus `bench-obs` in its own region (its vCPUs, one address, its boot and data disks against `SSD_TOTAL_GB`). Node vCPUs count against their family's quota metric (`C3_CPUS` for c3) and the blasters' e2 vCPUs against `CPUS`; addresses against `IN_USE_ADDRESSES`; blaster boot disks against `SSD_TOTAL_GB`; hyperdisk-balanced against the `HDB-TOTAL-{GB,IOPS,THROUGHPUT}` quotas, read from the Cloud Quotas API (`gcloud beta quotas info describe`) because `regions describe` does not list them. Each check lists every failing zone or region in one error. A quota it cannot read is a warning, not a failure. Writes the pre-snapshots. |
| 1 | Asserts the `:blast-v2-<sha>` tag, builds it with Cloud Build if missing, and probes `blast --help` for the CLI contract flags (when docker is available). |
| 2 | Runs `common/create-instances.sh` on the bench profile, its output copied to `logs/create-instances-<UTC>.log` (one per round). A node whose zone is out of the machine type moves to its next `BENCH_ZONE_FALLBACKS` zone and the create runs again, at most 3 rounds; any other create failure stops the step (see [Fleet shape](#fleet-shape)). Then it asserts `tags == [bench-node]` and `labels.benchmark == 1` on every node, labels the boot disks and records `manifest.instances[]` and `manifest.zones_used`. Then `bench_obs_create` makes the run's `bench-obs` VM (see [The obs VM](#the-obs-vm-bench-obs)), or keeps it when this run already has one; a `bench-obs` of another run stops the step. It labels both disks, records `manifest.obs` and prints `OBS_CREATE inst=<i> zone=<z> ip=<ip> id=<id> existing=<0|1>`. |
| 3 | Waits for the `devnet-startup.sh complete` serial marker on each node. |
| 4 | `benchmark-firewall.sh apply`: `bench-allow-consensus` (udp 49590/49594 from the nodes' own /32s) and `bench-allow-iap-rpc` (tcp 8545 from IAP). |
| 5–6 | The devnet drivers, on the bench profile: keygen and genesis build (in `benchmark/`). Keygen's output is copied to `logs/keygen-<UTC>.log`. Its `KEYGEN_DONE` lines go into `manifest.keygen_timing` (`{<inst>: {secs, reused}}`) and, from the nodes whose keygen succeeded, `manifest.node_info_rpc` (`{<inst>: {http, ws}}`, the RPC URLs `node-info.yaml` advertises). With the bench knobs keygen runs 4 nodes at a time, reuses a node already keyed for its address and advertises each node's internal-IP RPC (see [Before the first run](#before-the-first-run)). |
| 7 | One coordinated start, in four parts (see [Step 7](#step-7-one-coordinated-start)): `network-config` (`devnet-network-config.sh --yes`, Closed admission on every node), `stage-only` (`devnet-finalize.sh --stage-only`: stage, v2 finalize, stop; the unit stays enabled), `pre-start config` (one IAP session per node, `BENCH_NODE_JOBS` at a time: first the datadir fsync probe `bench_fsync_probe_script`, then `bench_prestart_script`, both on stdin; `PRECFG_OK <inst>` required, the probe never) and `start-all` (`devnet-finalize.sh --start-all`: every unit started at one due time on the nodes' clocks). The `COORDINATED_START` line goes into `manifest.coordinated_start`; a spread above 10 s stops the run. |
| 8 | First `bench_obs_ensure` brings `bench-obs` up. It creates the VM if it is missing (a `--from 8` after it was lost), waits for the startup script's `[obs-startup] … done` on the serial console (`OBS_BOOT`), copies the bundle and starts Prometheus and Grafana in one root IAP session whose last line must be `OBS_STACK_OK` (`--print-obs-bringup` prints that script), opens the two local forwards (see [The RPC tunnel](#the-rpc-tunnel)), records `manifest.obs.ready_at` and prints `OBS_READY inst=<i> ip=<ip> secs=<n>`. Each part keeps what is already in place. Then metrics-only observability in one IAP session per node, with no node restart. First every validator must be `CvvActive` (`bench_fleet_ready 0`). `bench-obs` takes no ingest auth, but `setup-observability.sh` requires a token, so the step makes a throwaway one (`openssl rand -hex 16`). It travels on the session's stdin only: the script reads it into a plain variable and pipes it to `setup-observability.sh --json --enable-metrics --token-stdin`. That script would label the node `network="devnet"` (it derives the label from the node's network), so it is pointed at a black-hole URL (`127.0.0.1:9`) for both its metrics and its log push. The session requires the `done` event with `"ok":true`, the phrase `Node already serves a metrics endpoint (--metrics).` (step 7 put `--metrics` on the node command, so nothing changes) and the container's `StartedAt` unchanged with `NRestarts=0`; anything else is `OBSCFG_FAIL <inst> contract drift`, with no restart fallback. In the same session `bench-obs` must answer `curl http://<bench-obs internal IP>:9090/-/ready` from the node, or the session ends with `OBSCFG_FAIL <inst> bench-obs unreachable` and Alloy stays on the black hole. Then Alloy is stopped, its WAL wiped, the env set to `TN_CHAIN=bench`, `TN_NODE=<instance>` and `OBS_METRICS_PUSH_URL=http://<bench-obs internal IP>:9090/api/v1/write`, and Alloy started again. No devnet-labelled sample leaves a bench node, and obs-devnet is never written to. The last line is `OBSCFG_OK <inst> restarted=none <done event>`. |
| 9 | One IAP session per node, `BENCH_NODE_JOBS` (4) at a time, verify only: no restart and no edit of the start script. It reads the running container's arguments (`docker inspect telcoin`: `--http.addr 0.0.0.0`, `--ws.addr 0.0.0.0`, `--metrics 127.0.0.1:<port>`, and the log filters and max-files when `BENCH_NODE_LOG_FILTER` is set), the node's `parameters.yaml` (path from `.node-meta` `DATA_DIR`) and the bench Alloy labels, requires `NRestarts=0`, waits until the internal IP answers `eth_chainId == 0x7e1e` and consensus is progressing (the block height rose, or the node's `docker logs` show `subdag committed`/`quorum reached` in the last 45 s, never before the coordinated start), reads the node's boot lines from `docker logs --since` the container's start, then installs `bench-node-sampler.service`. The boot lines give the git sha, the max and min header delay, the max batch delay, the vote timeout (later builds only) and the fork schedule. They go onto the `POSTCFG_OK` line as `sha= mhd= nhd= mbd= vt= forks=` and into `manifest.node_startup[<inst>]`. All but the vote timeout must match `node_git_sha`, `consensus_parameters` and `node_fork_schedule`; a mismatch fails that node and stops step 9 once the nodes running with it have ended (with `BENCH_NODE_JOBS=1`, at the first mismatch). A build that does not log the three delay lines waits out the 300-second deadline (`POSTCFG_WAIT_SECS` in the remote script) and then fails. |
| 10 | Health gate: `wait_healthy` on every node; an IAP tunnel to `bench-validator-01:8545` on `localhost:18545` shows chain id 32286; `bench_obs_require` finds `bench-obs` (gone: the run stops with "resume with --from 8", which recreates it and re-points every node's Alloy), its forwards up and its Prometheus answering, and warns when its data disk is `BENCH_OBS_DISK_MAX_PCT` % full or more; its Prometheus reports `count(count by (node)(tn_engine_canonical_height{network="bench"})) == 11`, `min by (node)(tn_primary_round{network="bench"})` rising on all 11 nodes across samples 30 s apart, and no bench node series with `network="devnet"`. Right after the chain id check, `recovery-schedule.py` reads the ConsensusRegistry through the tunnel, and its epoch duration must equal `EPOCH_DURATION_SECS`. The reading goes into `manifest.registry_probe`. Last, `bench_admission_gate` reads each node's own `/metrics` over IAP (loopback only): admission mode Closed on the primary and worker networks and fallback 0 on every node, recorded as `manifest.admission` and `manifest.fleet_modes`; it lists every node that is not Closed and stops the run. When `BENCH_ADMISSION_DENIED_MAX` is a whole number (the bench profile sets `0` when `NETCFG_TRUST_OBSERVERS_EVERYWHERE=1`, since every node then trusts every other; unset or empty: no check), every node whose closed-admission denials in or out exceed it gets an `ADM_WARN <inst> denied_in=<n> denied_out=<n> max=<max>` line, and `manifest.admission_denied_check` records `{max, over: [<inst>…], ts}`. That check only warns: a node redialling a peer that does not trust it is counted there, not refused. |
| 11 | With `--with-contracts` only: a worktree of `tn-contracts-devnet-relaunch` on `bench/<run>`, `deployments-devnet.json` copied over `deployments-testnet.json` (chain 32286 reads the testnet book), then `devnet-contracts.sh --yes` through the tunnel. The result is saved as `results/<run>/deployments-bench.json`. |
| 12 | Grants the compute service account `secretAccessor` on the two bench secrets and creates `gs://tn-devnet-bench-<run>` with the benchmark labels. |
| 13 | Fund. First `bench_obs_require` (as in step 10), then every validator must be `CvvActive` (`bench_fleet_ready`, `manifest.fleet_ready`): one pass over the validators, and when one is not active, a wait until the next epoch boundary plus `BENCH_FLEET_READY_SETTLE_SECS`, capped at `BENCH_FLEET_READY_MAX_WAIT_SECS`, then a second pass. Then the `bench-funder` VM runs `blast --prepare` for all 10 × `BENCH_SENDERS` senders and is deleted. A prepare that timed out with senders still unfunded exits 0, so the driver reads `still_short=<n>` from the generator log in `funder/`: above 0 it prints a ⚠, records `manifest.fund.still_short`, and runs the prepare once more on a new funder, which tops up only the senders still short. That count goes in `manifest.fund.still_short_after_retry`, and above 0 the fund fails with `fund-short-<n>`. With `BENCH_LIGHT_LOAD=1` it funds every blast of the light-load arm, the configured profile last (see [Light-load arm](#light-load-arm-steps-13-14)). |
| 14 | Blast: `bench-blaster-01..10` start together five minutes after creation, each against its own validator's internal IP. The chaos schedule and abort watchers run alongside. With `BENCH_LIGHT_LOAD=1` the light blasts run first, each a blast of its own with chaos off, and the configured profile after them. |
| 15 | Collect: sampler CSVs over IAP, blaster results from the bucket, `bench_obs_require` (as in step 10), then `tn-transaction-generator/bench/collect-gcp-metrics.py`, which with `BENCH_PROM_AUTH=0` gets `--prom-url ${BENCH_PROM_URL} --prom-no-auth` and reads `bench-obs`'s Prometheus straight through its forward. An IAP copy that IAP refuses (error 4003, 4033 or 4047) is retried up to `BENCH_IAP_RETRIES` attempts (default 3), 10 s and then 20 s apart, and lands under a `.part` name until it is complete. Then `analysis/block-rate.md` (and `analysis/cert-rate.md` once node logs are on disk), `INDEX.md` and `CHECKSUMS.sha256` are written into `results/<run>/`; a failure there is only a warning. The collector's own window, taken from the manifest's timestamps and phases, ends at the latest of `timestamps.blast_end`, `timestamps.collect_start` and the phases' ends; in bench 3 that was before the chaos target rejoined. So with `BENCH_COLLECT_WAIT_REJOIN=1` (default) and a chaos kill that landed (a kill in `manifest.chaos[]` with rc 0), step 15 first waits until every validator is `CvvActive` again (`bench_fleet_ready`) and each killed node still reads `CvvActive` `BENCH_NODE_BACK_SECS` later: bench 3's target was promoted and demoted again 11 times, so one reading is not a rejoin, and a target that falls back starts the wait over. The whole wait is capped at `BENCH_FLEET_READY_MAX_WAIT_SECS` (still not ready is a warning), and then step 15 passes the collector `--start <manifest window start> --end <then>`. `manifest.prom_window` records `{start, end, end_reason, waited_secs, confirm_secs}`, `end_reason` being `fleet_ready`, `max_wait`, `no_chaos` or `knob_off`; in the last two nothing is passed and the collector keeps the manifest's window. |
| 16 | With `--with-teardown` only: `benchmark-teardown.sh --yes`. |

A resume finds `bench-obs` where the run left it. `--from 2` or earlier creates it, or keeps this
run's; `--from 8` brings it up again, recreating a lost one and re-pointing every node's Alloy at
it; from step 10 on, the steps that read Prometheus (10, 13, 15) require it and stop when it is
gone.

The last line an applied deploy (`--yes`) prints is its outcome, on its own stdout once the log
has drained:
`BENCH_DEPLOY_RESULT rc=<n> last_step=<step|gate|-> first_error=<text|-> log=<deploy log>`.
`first_error` is the first `❌` line of this invocation's log, at most 300 characters. The same
outcome goes into `results/<run>/last-deploy.status` (key=value lines `rc`, `last_step`,
`first_error`, `started`, `ended`, `scope`, `log`, replaced atomically) and into
`manifest.deploy_result`, and is appended to `manifest.deploy_runs[]` (the log path relative to
the run directory, `null` for an unknown field). A supervisor, or a later session, can read how
the last invocation ended without parsing its log. The status file is written from the first
moment of an applied deploy, `rc=-` (running) with `last_step=starting` and this invocation's
`started`, and rewritten with each step's number, so a watcher never mistakes the previous
invocation's outcome for this one's (it trusts only a `started` at or after its own launch). An
exit before the deploy log starts (an argument, a pinned image, `config.sh` or `bench-lib.sh`
refusing) rewrites it with that exit's rc, and a `kill -9` leaves `rc=-` with the step it was in.
A gate that stops a new run before the manifest exists writes the status file only, and a dry run
prints no result line. Each invocation's log
(`logs/deploy-<UTC>.log`) prefixes every line with its `HH:MM:SSZ` time; the terminal copy has no
prefix. `--run <id> --note "<text>"` appends `<text> (operator note, <UTC>)` to `manifest.notes`
and exits without running a step or contacting GCP.

### Step 7: one coordinated start

A committee member that starts more than `gc_depth` (50) rounds after the others reach quorum
sits out the whole epoch (`too new for max round 50`, lessons 2026-11-02), and after the start no
node may restart. So no node runs until every node is configured, and then all start together:

1. `network-config`: `devnet-network-config.sh --yes` renders each node's `network-config`
   (admission Closed, the committee peers, the hub/observer trusted and bootstrap peers) under
   `benchmark/genesis/network-config/` and installs it. It restarts nothing. With the bench knobs
   every validator trusts every observer and each observer every validator, a node takes at most
   two IAP sessions, and four nodes go at a time (see [Before the first run](#before-the-first-run)).
2. `stage-only`: `devnet-finalize.sh --stage-only` stages genesis, committee and
   `PARAMETERS_FILE`, runs the v2 finalize (which starts the node once, alone), then stops the
   unit and leaves it enabled. Nodes go `FINALIZE_JOBS` (4) at a time, and the driver refuses a
   value that reaches a quorum of the validators, so the units that run together before their
   stops can never form one. Its output is also copied to
   `results/<run>/logs/finalize-stage-<UTC>.log`.
3. `pre-start config`: one IAP session per node, up to `BENCH_NODE_JOBS` (4) at a time, the
   script on stdin (`bench_prestart_script`; print it with `--print-prestart <instance>`), after
   the disk probe in the same session (below). With the
   unit stopped it checks the node's `tn-node-deployment` checkout against `TN_NODE_SCRIPTS_REF`,
   sets `--http.addr 0.0.0.0`, `--ws.addr 0.0.0.0`, `--metrics 127.0.0.1:<METRICS_PORT>` and the
   log filter on `/usr/local/libexec/telcoin/tn-start-docker` with v2's `tn_launch_flag_set`, keeps
   the staged `parameters.yaml` as `parameters.yaml.bak` (`cp -p`, unless a `.bak` is there
   already; a file that holds `# bench-override` lines and has no `.bak` fails, as it is not the
   original), and writes the node's parameter overrides. When `BENCH_LOGROTATE_SIZE` is set it
   also replaces `/etc/logrotate.d/telcoin` with the bench's rotation config (v2's template
   without `maxsize`, rotating at that size, written with v2's `tn_write_root_file`), which
   `logrotate -d` must parse. With `BENCH_NODE_DB_SYNC_MODE` set it also puts
   `--db.sync-mode <value>` on the command. Its last line, `PRECFG_OK <inst> datadir=…
   http=0.0.0.0 ws=0.0.0.0 metrics=127.0.0.1:<port> … unit=inactive logrotate=<size|->
   paramsbak=<written|kept>`, followed by `dbsync=<value>` when that knob is set, is required; `logrotate` and `paramsbak` go into `manifest.node_startup[<inst>]` as
   `logrotate_size` and `params_bak`, and `dbsync` as `db_sync_mode` (`durable` when the line has no
   `dbsync=`: the knob is unset and the node runs its default). With more than one node at a time a failed node does not
   stop the others, and the step stops once they have all ended, naming the failed nodes.
4. `start-all`: `devnet-finalize.sh --start-all` starts every unit at one due time (now + 60 s by
   default, on each node's own clock), waits for them, and runs its post-checks. Its output is
   copied to `results/<run>/logs/finalize-start-<UTC>.log`. The `COORDINATED_START due=…
   nodes=… started=… skipped_running=… spread_secs=… max_late_secs=…` line goes into
   `manifest.coordinated_start`. A spread above 10 s stops the run: read the `START_AT` lines in
   that log and do not restart anything inside the epoch.

**Disk probe.** Each pre-start session first times 200 × (write 4 KB + `fsync`) on a temp file in
the node's datadir (`.node-meta` `DATA_DIR`, the host directory the container mounts at
`/home/nonroot`), with python3 from the node image (stdlib only), while the unit is still stopped,
and prints `FSYNC_PROBE <inst> p50_us=<n> p95_us=<n>` (nearest-rank percentiles, integer
microseconds) or `FSYNC_PROBE <inst> probe_failed <reason>`. The deploy records it as
`manifest.node_startup[<inst>].fsync_probe` = `{p50_us, p95_us}` or `{probe_failed: true, reason}`.
Once every node is configured (before start-all) it prints one line,
`FSYNC_PROBE_SUMMARY median_us=<n|-> slow=[<inst> …] probe_failed=[<inst> …]`: the median p50 of
the nodes that measured (`-` when none did), the nodes more than 20 % above it, and the nodes whose
probe failed or printed no `FSYNC_PROBE` line (their record is `{probe_failed: true, reason}`); the
line starts with `⚠` when either list is not empty. Nothing about the probe stops the step: a slow disk is a finding for the
analysis (a node whose persist is slower than the fleet's), not a fault.

Re-running step 7 (`--from 7`) converges. `network-config` is idempotent. `stage-only` skips a
node whose unit is staged (`PRESTAGED`) or running (`RUNNING`). Pre-start accepts flags that
already hold their value, and is not repeated on a node that has run since the coordinated start
(it was configured before that start; if its start script lacks `--metrics`, step 8 refuses it).
`start-all` skips running nodes. The first start stays `manifest.coordinated_start`; every later
start-all appends `{line, ts}` to `manifest.coordinated_start_reruns`, and one that started nodes
warns: they joined after the fleet and sit out the epoch they started in.

A unit that is running before any coordinated start stops step 7. That happens when a stage-only
fails after v2 finalize started the unit (a health timeout, `NRestarts` above 0, a failed stop).
The node ran alone, so no quorum formed and stopping it is safe. On each named node run
`sudo systemctl stop telcoin; sudo systemctl reset-failed telcoin`, then re-run with `--from 7`.
Left running, it would skip its pre-start config, and step 8 would refuse it after the start, when
no restart is allowed.

`devnet-finalize.sh` cannot finalize a node twice, so a post-check that failed on a transient
ssh drop is re-checked, read-only, by hand (phase B only, A1-A5):

```bash
CONFIG_FILE=benchmark/config.sh BENCH_RUN_ID=r20260923-0100 \
  BENCH_DOCKER_IMAGE=<manifest node_image_pinned> ./devnet-finalize.sh --verify [node]
```

`BENCH_DOCKER_IMAGE` must be the pinned `<repo>@sha256:` ref, because the checks compare the
running image's digest with it.

Fleet readiness. Step 8 requires every validator to report `tn_nodeMode` `CvvActive` in one pass
(`bench_fleet_ready 0`); a validator that is not active stops it, and the fix is to wait for the
next epoch boundary and resume with `--from 8`. Step 13 waits for the same condition, up to
`BENCH_FLEET_READY_MAX_WAIT_SECS` (default `EPOCH_DURATION_SECS` + 300): when a validator is not
active it sleeps until the next epoch boundary plus `BENCH_FLEET_READY_SETTLE_SECS` (default 90),
then polls each node again for up to `BENCH_NODE_BACK_SECS` (default 180). It never polls in a
tight loop (IAP throttles). Both record `manifest.fleet_ready`.

Every bench script that sources tn-node-deployment's library on a node first sets
`DEVNET_RPC_URL` to `BENCH_GUARD_PUBLIC_RPC` (`http://127.0.0.1:9`, refused): the library's
restart guard falls back to that URL, which otherwise is the live devnet's public RPC.

### Progress means consensus rounds, not blocks

An idle TN chain sits at **block 0**. The engine skips empty consensus outputs that do not close
an epoch (`skipping execution for empty non-epoch-closing output`), so `eth_blockNumber` only
moves once there are transactions, which means after the funder runs. Consensus runs anyway:
`tn_primary_round` rises about once a second and the node logs `quorum reached` / `subdag
committed`. Steps 9 and 10 and the `quorum-lost` watcher therefore judge liveness by
consensus rounds. `block=` in the sampler's `BENCH_STATUS` line is informational only.

### The RPC tunnel

Steps 10 to 15 and the chaos schedule reach `bench-validator-01:8545` through a local tunnel on
`localhost:18545` (`bench_tunnel_up`). By default (`BENCH_TUNNEL_MODE=ssh`) one IAP ssh session
carries a port-forward that every RPC request shares, run by a supervisor in its own session
that appends to `results/<run>/tunnel.log`:

- every start logs `tunnel: start <ISO> mode=ssh target=<inst>:8545 local=<port> pid=<ssh pid>`
  and every exit `tunnel: exit <ISO> rc=<n> up=<s>s fails=<n>/<max>`;
- a session that stayed up at least `BENCH_TUNNEL_MIN_UP_SECS` (20) was a drop, and the count of
  consecutive failures starts again; a shorter one counts as a failure;
- after `BENCH_TUNNEL_MAX_FAILS` (5) consecutive failures the supervisor gives up with
  `tunnel: giving up after <n> consecutive failures at <ISO>` (exit 1);
- after every exit it asks GCP for the instance, and `not found` (the teardown deleted it) ends
  it (exit 0, `tunnel: <inst> is gone …; not restarting`); otherwise it restarts 3 s later.

Any other mode runs one `gcloud compute start-iap-tunnel`, a websocket per connection (about one
connection in 50 was lost on 2026-11-03), and logs the same `tunnel: start` line. The plan line
names the command of the mode in use. `bench_tunnel_up` then waits up to 45 s for `cast chain-id`
through the tunnel. The teardown stops the supervisor with the tunnel. Read `tunnel.log` first
when an RPC call failed mid-run.

`bench-obs` gets two more forwards of the same kind, always in ssh mode and each under its own
supervisor (`bench_obs_tunnel_up`, from step 8 on; steps 10, 13 and 15, the blast's `run` and
the teardown open them again when they are down):

| Local end | Target | Pid file | Probe |
|---|---|---|---|
| `127.0.0.1:19090` (`BENCH_OBS_PROM_LOCAL_PORT`) | `bench-obs:9090`, Prometheus | `results/<run>/tunnel-obs-prom.pid` | `curl -sf ${BENCH_PROM_URL}/query?query=up` |
| `127.0.0.1:13000` (`BENCH_OBS_GRAFANA_LOCAL_PORT`) | `bench-obs:3000`, Grafana | `results/<run>/tunnel-obs-grafana.pid` | `curl -sf ${BENCH_GRAFANA_URL}/api/health` |

Their starts and exits go to the same `tunnel.log`
(`tunnel: start <ISO> mode=ssh target=bench-obs:9090 local=19090 pid=<ssh pid>`, and
`target=bench-obs:3000 local=13000` for Grafana). Every Prometheus read of the run goes through
the first (`BENCH_PROM_URL`, no credentials while `BENCH_PROM_AUTH=0`). Grafana answers at
`http://127.0.0.1:13000` with anonymous Viewer access and the dashboards from `common`; its
admin password is only in `/opt/obs/.env` on the VM. `bench_tunnel_down` and the teardown stop
every `tunnel*.pid` supervisor.

### IAP sessions and retries

devnet-lib's IAP wrappers (`tn_iap_ssh`, `tn_iap_ssh_stdin`, the copies and the IP lookups),
which the drivers and the harness open their sessions with, go through `_tn_iap_retry`. It names
each failure with `tn_iap_fault_kind <rc> <stderr file>`, checked in this order:

| Kind | When | Retried |
|---|---|---|
| `ok` | rc 0 | |
| `reauth` | stderr matches `TN_IAP_REAUTH_PAT`, whatever the rc (an extended regex; default `Reauthentication failed\|There was a problem refreshing your current auth tokens\|invalid_grant`) | never: every later call would fail the same way. One `❌ <label>: gcloud needs re-authentication (run: gcloud auth login) — not retried` line, then the call's rc |
| `transport` | ssh rc 255 (IAP refused the tunnel, or the session dropped) or `gcloud crashed` on stderr | `TN_IAP_RETRIES` (default 2) more attempts, `TN_IAP_RETRY_SECS` (5) apart; `0` turns the retry off |
| `iap-refused` | an IAP refusal under another rc: `[4003:`, `[4033:`, `[4047:` or `failed to connect to backend` | not by devnet-lib; the collect copies and the log pulls retry it themselves |
| `other` | anything else: the remote command's own failure, a missing instance | no |

The IP lookups (`tn_node_ext_ip`, `tn_node_int_ip`) are retried on transport faults too. The log
pulls turn devnet-lib's retry off for each attempt and retry on their own, because
a retried stream would land the retry's bytes after the cut attempt's (see
[Pull markers and re-runs](#pull-markers-and-re-runs)); a `reauth` there stops every pull that
has not started. The chaos sessions are never retried (see below).

### Light-load arm (steps 13-14)

With `BENCH_LIGHT_LOAD=1`, steps 13 and 14 (`benchmark-blast.sh fund` and `run`) drive a sequence
of blasts on the one fleet: a light blast per entry of `BENCH_LIGHT_SENDERS`, each at the
`BENCH_LIGHT_WINDOWS` entry in the same position (`BENCH_WINDOW` when that list is empty), with
`BENCH_LIGHT_WARMUP_SECS`, `BENCH_LIGHT_DURATION_SECS` and `BENCH_LIGHT_COOLDOWN_SECS` (60/360/60 s)
and chaos and lag injection off; then the configured profile (`BENCH_SENDERS` at `BENCH_WINDOW`, its
phases, `BENCH_CHAOS` as set); then, with `BENCH_LIGHT_LOAD_AFTER=1`, one more light blast with the
first entry's senders and window. The defaults give four blasts:

| Index | Senders × window per blaster | In flight (10 blasters) | Chaos | Reads |
|---|---|---|---|---|
| 0 | 8 × 16 | 1,280 | off | the floor: time to land at light load (the report's floor KPIs) |
| 1 | 16 × 16 | 2,560 | off | the floor at twice that load |
| 2 | 600 × 4 | 24,000 | off | the reduced in-flight point: bench 4's senders at a quarter of the window |
| 3 | 600 × 16 | 96,000 | as set | the configured profile: bench 4's load |

Each blast is a plain single-blast invocation of the script under its own `BENCH_RUN_INDEX`,
counting up from `BENCH_RUN_INDEX` (default 0: indices 0 to 3, or 4 with the blast after the load),
so the second-blast support funds, bucket-prefixes and archives it. `fund` funds every index, the
configured profile's last (so `funder/` ends with its output). Each light blast lands in
`results/<run>/blast-<index>-<UTC>/` with its own copy of the manifest. The configured profile's
outputs stay where a single blast puts them (`blasters/`, then step 15's collect and
`metrics.json`): after a light blast that follows the load, the script archives that blast and moves
the configured profile's files and manifest back from its `blast-<index>-<UTC>/`.

`run` prints `LIGHT_LOAD_START i=<index> senders=<n> window=<w>` before and
`LIGHT_LOAD_DONE i=<index> rc=<rc>` after each light blast (a dry run prints
`>>> light-load arm (plan): light blast, index <i>, <n> senders per blaster at window <w>` instead,
so a log watcher never takes a plan for a run), appends
`{index, senders, window, chaos, started, ended, rc}` to `manifest.blasts[]` after every blast, and
stops at the first blast that ends with rc != 0, printing the commands that finish the sequence by
hand (the failed blast funded and run under a fresh index, the later ones under their funded
indices; when a light blast is among them, a reminder that a hand-run blast is not in `blasts[]`, so
the floor KPIs need its `blast-<index>-<UTC>/` as `--floor-blast-dir`). It refuses `--keep`, and before funding or running anything it refuses when an earlier
blast on the fleet used one of its indices, naming the next free base. The sequence's own output
is `logs/blast-light-<action>-<UTC>.log`. A light blast takes about 15-20 minutes (the 300 s
`BENCH_START_DELAY_SECS` boot wait included), each extra fund a few minutes.

Every blast of the sequence also measures one node's log volume, the configured profile's under load
included (the light blasts under-read the loaded rate several times over). Once its blasters send (the
start plus `BENCH_PREAMBLE_SECS`), it takes two samples 60 s apart, one IAP session each, of the size
of `bench-validator-01`'s unit log `/var/log/telcoin/telcoin.log` and its rotated siblings, and
prints `LOG_RATE <node> blast=<index> mb_per_min=<n.n>` (MB = 10^6 bytes), followed by
`⚠ above BENCH_LOG_RATE_WARN_MB_MIN=<t>` when the rate is above `BENCH_LOG_RATE_WARN_MB_MIN`
(default 30): a log filter that writes that much would flood the teardown's pull. It is never fatal:
a failed sample, or a rotation between the samples, prints `mb_per_min=?`. Each measurement appends
`{blast, inst, mb_per_min, warn}` to the list `manifest.log_rate`, in run order (an archived blast's
manifest copy holds the entries up to its own). The measurement runs before the blast's watch loop,
so its first abort poll comes about `BENCH_PREAMBLE_SECS` + 60 s after the start; the chaos kill is
later than that.

`BENCH_LANDINGS_SAMPLE=N` (N > 0) adds `--landings-out /out/landings-<label>.ndjson.gz
--landings-sample N` to every blaster's generator, in each blast of the sequence or in a single
blast. The export comes back with the rest of `/out` as `blasters/landings-<blaster>.ndjson.gz`
(under `blast-<index>-<UTC>/blasters/` for an archived blast). `tools/stage-latency.py` reads the
archived light blasts as windows of their own (see [Outputs](#outputs-resultsrun-gitignored)).

### Chaos schedule (step 14)

Offline checks: `python3 -m unittest discover -s benchmark/tests -v` and
`python3 benchmark/tests/check_mutations.py`. CI also checks Bash syntax, ShellCheck, bash 3.2
constructs (`tn-node-deployment/tools/check-bash32.sh`, when the submodule is checked out) and
`tasks/check-bash-portability.sh`.

By default (`BENCH_CHAOS_TIMING=epoch`), the operator opens the existing RPC tunnel and reads
the registry at a pinned execution block. The preceding closing block's timestamp anchors
the schedule. After at least `BENCH_CHAOS_MIN_LOAD_SECS=600` seconds of planned mixed load,
the drill kills validator-05 `BENCH_CHAOS_BEFORE_CLOSE_SECS=59` seconds before an eligible
epoch boundary. It restarts after `BENCH_CHAOS_DOWNTIME_SECS=300` seconds from the kill and
restarts the observer `BENCH_CHAOS_OBS_AFTER_BACK_SECS=300` seconds later. An unavailable
epoch read stops the run before load VMs are created. A restart scheduled after the workload
also stops the run, so extend `BENCH_DURATION_SECS` for long outages.

That first plan projects the closing epoch at whole epoch durations from the epoch it measured.
A loaded boundary waits for execution (12-26 s without a block in bench 3), so each epoch in
between can open late, and the kill would land that much more than 59 s before the real close.
With `BENCH_CHAOS_REFRESH_SCHEDULE=1` (default) every poll before the kill runs
`chaos_schedule_refresh`. Once the closing epoch has opened (it never opens before its projected
start, so nothing is asked earlier), and while the kill is still more than
`BENCH_CHAOS_GUARD_SECS + BENCH_CHAOS_STAGE_SECS` away, it reads that epoch's start from the
registry (`recovery-schedule.py --epoch <closing> --before-close <s> --downtime <s>`) and plans
the kill, the restart and the observer restart again from it, once. The read must not eat into the
kill's margin, so it uses only a tunnel that is already up: a poll that finds the tunnel down skips
the refresh (`the RPC tunnel is not up — not refreshed at this poll`), and the registry read runs
under an alarm of `BENCH_CHAOS_REFRESH_TIMEOUT_SECS` (default 20, at most
`BENCH_CHAOS_STAGE_SECS`; the blast checks both when it starts). Either miss leaves the plan as it
is, and the next poll tries again. `manifest.chaos_schedule_refresh`
records `{planned_kill_unix, kill_unix, drift_secs, closing_epoch, epoch_start_unix, ts}`;
`manifest.chaos_schedule` keeps the first plan. An epoch not opened yet is asked again at the next
poll. `BENCH_CHAOS_REFRESH_SCHEDULE=0` keeps the first plan.

Use `BENCH_CHAOS_BEFORE_CLOSE_SECS=600 BENCH_CHAOS_DOWNTIME_SECS=900` for a mid-epoch
kill that still crosses the boundary. The offset must fit the measured epoch duration and
the downtime must exceed the offset. The drill keeps its existing owed-restart cleanup.

Each action is staged so it lands on time. `BENCH_CHAOS_STAGE_SECS=30` seconds before it is
due, the run opens one IAP session and sends a short script on stdin (`sudo bash -s`). The
script starts saving the container log in the background (`BENCH_CHAOS_SAVE_STARTED <file>`),
waits on the node's own clock for the due time, prints `BENCH_CHAOS_BEGIN`, runs the action and
prints `BENCH_CHAOS_END`. The action never waits for the save: the script checks the clock every
0.2 s, so the action begins at most about 0.2 s after its due time however long the save takes.
After `END` the session waits up to `BENCH_CHAOS_SAVE_WAIT_SECS=60` seconds for the save and
prints its outcome:

- `BENCH_CHAOS_SAVED <file> at_action=finished|running`: the copy is on the node. `finished`
  means it was complete when the action began, `running` that it completed afterwards. Either
  way it holds the container's output up to about the moment the save began: `docker logs`
  reads the log up to the size it had then, and Docker does not cut that read short when it
  removes the killed `--rm` container (checked on Docker 29.8 with the json-file driver: a
  542 MB read started 0.5 s before a SIGKILL completed in full).
- `BENCH_CHAOS_SAVE_RUNNING <file> at_action=running`: still writing when the wait ran out. It
  completes on the node by itself, and the file appears under its name only once complete. The
  run adds a `log-save-unconfirmed` note to the manifest.
- `BENCH_CHAOS_SAVE_FAILED <name> at_action=… <error>`: no copy. The run adds a
  `log-save-failed` note.

The saved copy is a convenience. The unit's append file (`<node>-unit-stdout.log.gz` at
teardown) holds every container's output across restarts, including the seconds between the
save and the action. r20261007-0316 saved before waiting: the 17 GB save took about 70 s and
the kill began 41.8 s late, 18 s before the epoch boundary instead of 59 s.
`BENCH_CHAOS_STAGE_SECS + BENCH_CHAOS_SAVE_WAIT_SECS` must stay below the outage
(`BENCH_CHAOS_DOWNTIME_SECS`, or `BENCH_CHAOS_BACK_AT_SECS - BENCH_CHAOS_KILL_AT_SECS` in mixed
mode), so the kill's session ends before the restart's opens; `benchmark-blast.sh` refuses to
start otherwise.

In epoch mode the restart is due `BENCH_CHAOS_DOWNTIME_SECS` after the kill's node-side begin,
and the observer restart `BENCH_CHAOS_OBS_AFTER_BACK_SECS` after the restart's. No poll starts
within `BENCH_CHAOS_GUARD_SECS=90` seconds of a due action; it runs right after the action
instead. If the session fails before `BEGIN`, the action falls back to a direct `--command` at
its due time and is recorded with `staged: false`. The fallback does not save the log first,
since that would delay the action. Neither session is retried by devnet-lib
(`TN_IAP_RETRIES=0`): a session that dropped after its action ran would run the action again,
late. The fallback is the staged session's retry, and an owed restart is tried again at a later
poll. Before staging, r20261006-0053 killed 17 s late (a long poll,
the log save and the IAP setup all ran first), and both restarts inherited it.

Run `benchmark/benchmark-blast.sh chaos-stage-test --instance <node> --yes` once against a
live fleet before a blast. It sends the same script with the harmless action `true`, due
`BENCH_CHAOS_STAGE_SECS` ahead, saves that node's container log alongside as
`telcoin-stage-test-<UTC>.log.gz`, and prints `BEGIN`, `END`, how late the action began and the
save's outcome. It fails when the markers do not come back. Without `--yes` it only checks that
the script parses.

`manifest.chaos_schedule` records the measured epoch, anchor block/hash and planned times; the
kill's `chaos[]` entry repeats them as `planned` (`closing_epoch`, `boundary_unix`,
`restart_unix`), the refreshed plan when `chaos_schedule_refresh` moved the kill. Whether the outage crossed the boundary is measured, not assumed. After the
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
`node-sampler.sh` writes every two minutes, and `bench-obs` memory from Cloud Monitoring, so
the loop itself makes no SSH calls. Before any blaster exists, `run --yes` requires `bench-obs`
(`bench_obs_require`: the VM exists and its Prometheus answers on the forward), since the round,
health and commit checks read it. The first rule to trip sets `manifest.abort`, stops every
blaster (`docker stop txgen`) and allows 10 minutes for the results to upload. A poll that
would start within `BENCH_CHAOS_GUARD_SECS` of a chaos action waits until the action has run.

The status line is `BENCH_STATUS host=<h> ts=<unix> root_used_pct=<n> fatal_db=<n> halt=<n>
block=<n> rss_total_kb=<n>`. `fatal_db` counts the node's fatal database lines (`FatalDBFailure`,
or tn-lmdb's latched store) since the previous status line. `halt` counts the node's fail-stop
lines (seven phrases of `tasks/bench7-contract.md` section 4, listed in `node-sampler.sh`; the
re-certify conflict only with `stop=true`) in its unit log since that log began, so a node that
halted and restarted stays counted. The watchers here do not read `halt`: a halted validator is a finding of the run, not a
reason to abort. `tasks/bench7/orch-fleet-health.sh` reads it.

| Reason | Trigger |
|---|---|
| `disk-full` | a bench node's root disk is above 85 % |
| `obs-memory` | `bench-obs` (`BENCH_OBS_INSTANCE`) memory is above `BENCH_ABORT_OBS_MEM_PCT` (85 %) |
| `batch-cache-cliff` | `FatalDBFailure` shows up in a node's `docker logs telcoin`. This is the batch-cache defect, **not** a hardware limit, and the report must say so. |
| `quorum-lost` | two consecutive polls in which no node's `max by (node)(tn_primary_round{network="bench"})` advanced. A failed Prometheus query counts as unknown, never as stalled. |
| `node-stalled` | one validator's epoch/round stays unchanged for two consecutive polls while peers advance. Planned outages and pauses are exempt. Observers and missing metrics are not counted; an unknown poll resets the comparison. The victim's log is saved before aborting. |

Commit stalls are noted, never aborted on. `quorum-lost` needs two whole polls without a
round, so a stall shorter than that goes unseen (r20261006-0053: 301 s at block 15513). Each
poll therefore reads every `BENCH_STATUS` sample since the previous poll. A stall needs both
signals: the fleet's highest block has not moved for `BENCH_STALL_NOTE_SECS=60` seconds, and
the fleet's highest consensus round rose by at most `BENCH_STALL_NOTE_MAX_ROUNDS=4` over the
last `BENCH_STALL_NOTE_SECS` of that stretch. The round comes from Prometheus, read with
`offset` at those times. The last stretch is used, not the whole one, because in the 6 Oct
stall blocks stopped about 28 s before rounds did. A stall prints one `⚠ commits flat` line.
When the block moves again, even after cooldown, `manifest.commit_stalls[]` gets `{start, end,
secs, block, round_start, round_end, source: "watch"}` and a note. The bounds are sample times,
and the rounds (epoch × 10^8 + round) are read at those times. A stall still flat when the
watch ends gets `open: true`. Blocks flat while rounds keep rising is an idle chain, not a
stall: empty consensus outputs are not executed, so blocks stop once the generators do
(r20261006-0458 finished about 37 s before the planned mixed end). That prints one `idle:` line
and records nothing. Only a stretch that starts in the planned mixed phase counts: in cooldown
the generator only drains.

`collect` runs `stall-scan.py` over the sampler CSVs (fleet maximum per 30 s, same window)
into `manifest.commit_stalls_sampled`, and notes any sampler file it could not copy. The sampler
records blocks but no consensus round, so this scan cannot tell a stall from an idle chain. Its
entries carry `source: "sampler-blocks-only"`. Read one as a stall only when
`manifest.commit_stalls` (the watch, which checks rounds) has a matching entry.

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

`results/<run>/` is the only copy of a run. No bucket keeps another: the persistent archive
`gs://tn-devnet-benchmark-archive` is retired, and the run bucket is deleted at teardown once it
is copied into `bucket/`. The directory is gitignored and on one disk, so back it up outside the
repo once the teardown has finished.

- `manifest.json`: `tn-bench-manifest/v1` (see
  `tn-transaction-generator/bench/schema/manifest.example.json`), plus the provenance fields
  below
- `pre-instances.json`, `pre-firewall.json`: project state before the run; teardown compares against them
- `blasters/<name>.json` (`tn-blast/v2`), plus each blaster's docker log and generator log and,
  with `BENCH_LANDINGS_SAMPLE` set, its landings export `landings-<blaster>.ndjson.gz` (gzipped
  NDJSON, one row per sampled own landing: `hash`, `type`, `node`, `sender`, `nonce`, `submit_ms`,
  `accept_ms`, `block`, `seen_ms`, `phase`; private, never a bundle file)
- `blast-<index>-<UTC>/`: an earlier blast on this fleet (a second blast under a new
  `BENCH_RUN_INDEX`, or each light blast of the light-load arm): its `blasters/`,
  `meta/bench-blaster-*`, `logs/create-bench-blaster-*.log`, `logs/blast-run-*.log`,
  `logs/blast-collect-*.log`, `metrics.json` if it had one, and a copy of `manifest.json` as it was
  when the next blast started
- `funder/prepare.json`, `sampler/<node>.csv`, `deployments-bench.json`, `metrics.json`
- `logs/`: every node's logs, their pull markers and the recovery evidence, saved by the
  teardown. Per node: `<node>-telcoin.log.gz` (the container running at the pull),
  `<node>-unit-stdout.log.gz` (the unit's append file `/var/log/telcoin/telcoin.log`: the output
  of every container run since setup, or since its last rotation, so it also covers the seconds
  between a pre-kill log save and the kill), `<node>-unit-stdout.rotated-<N>.log.gz` and
  `<node>-unit-stderr.rotated-<N>.log.gz` (the unit logs' earlier generations, `telcoin.log.1`
  gzipped on the node and `.<N>.gz` as they were; when the name is taken by a file the node's
  marker does not vouch for, the copy lands as `<node>-unit-<stream>-<UTC>.rotated-<N>.log.gz`),
  `<node>.logspan` (the `LOGSPAN` lines: every unit log generation on the node at the pull, its
  bytes and its first and last line's time; see Pull markers and re-runs), the container logs
  saved on the node before a restart or kill (`<node>-telcoin-pre-kill-…`; runs before the
  coordinated start also have `-pre-step9-<UTC>`, saved before step 9's restart) and
  `<node>-recovery-<id>.*.tgz`. Step 2's creates are copied to `create-instances-<UTC>.log` (one
  per round), step 5's keygen to `keygen-<UTC>.log`, and step 7's two finalize runs to
  `finalize-stage-<UTC>.log` and `finalize-start-<UTC>.log`.
  A validator below the certification threshold also has `<node>-telcoin-cert-fail-<UTC>.log.gz`
  (see Certification outcome). Beside them, each script invocation's output (`deploy-*.log`, `blast-<action>-*.log`, and a
  light-load sequence's own `blast-light-<action>-*.log`) and the
  load VM creates of the current blast index (`create-<vm>.log`); an earlier index's creates are
  in `blast-<index>-<UTC>/logs/`.
- `logs/bench-obs-prometheus-<UTC>.tar.gz`: the teardown's snapshot of `bench-obs`'s Prometheus
  TSDB (admin API), every series of the run, pulled before the VM is deleted
  (`manifest.obs.prom_snapshot`). To read it, untar it and start a Prometheus with
  `--storage.tsdb.path` on the extracted directory.
- `tunnel.log` and `tunnel*.pid`: the local forwards' supervisor log and pid files, among them
  `tunnel-obs-prom.pid` and `tunnel-obs-grafana.pid` for `bench-obs` (see The RPC tunnel). The
  teardown removes the pid files once it has stopped the forwards.
- `last-deploy.status`: how the last applied deploy invocation ended, or how far a running one
  has got (`rc`, `last_step`,
  `first_error`, `started`, `ended`, `scope`, `log`; see What the deploy does)
- `zones.env`: only after a stockout moved a node, `BENCH_ZONES_USED=<zone of each node>`, which
  replaces `ZONES` for every script of the run (see Fleet shape)
- `bucket/<name>/`: the run bucket, copied here by the teardown before it deletes the bucket
- `genesis/`: moved here from `benchmark/genesis/` at teardown, so the next run starts clean
- `analysis/cert-rate.md`: per validator and phase, the certification rate, re-proposals, failed
  vote requests and the node's share of committed certificates and leaders
  (`tools/cert-rate.py`). It needs the node logs, so it appears at the end of the teardown.
- `analysis/block-rate.md`: per phase, committed rounds/s, blocks/s and tx/s from the blasters'
  block lists, and per node rounds/s, blocks/s and commit latency (`tools/block-rate.py`).
  `tools/ANALYSIS.md` describes both tools and how to run them on devnet or testnet logs.
- `analysis/certification.json`: `tools/cert-rate.py --format json` over the validator logs, the
  numbers behind `manifest.certification` (see Certification outcome)
- `INDEX.md`: one row per file group (what it is, which step or script wrote it, how many files);
  a file the harness does not know gets a row of its own.
- `CHECKSUMS.sha256`: the SHA-256 of every other file. Check a copy with
  `cd results/<run> && shasum -a 256 -c CHECKSUMS.sha256` (`sha256sum -c` on Linux).

Two readings of a finished run are taken by hand; no step writes them:

- `tools/stage-latency.py --run-dir results/<run> --out-json <file> --out-md <file>` joins each
  node's log with its generator's block table and splits the time to land into stages, S0 (RPC
  accept) to S13 (visibility at the scanner): per window, each stage's count, p50 and p95, and the
  headline sums `ts`, `commit` and `seen`. Without `--windows` the windows are each archived light
  blast's mixed phase (named from `manifest.blasts[]`, `light8`, `light16`, …), the load, and `all`.
  The light windows (and only those) drop the blocks within 30 s of an epoch boundary by default
  (`--boundary-secs` sets the width; `--keep-boundaries` keeps them; `--exclude-boundaries GLOB`
  applies the cut to the windows matching GLOB instead).
  `--out-blocks <file>` adds one JSON line per joined block. It is stdlib only and reads gzipped
  logs; its docstring lists the stage sources and joins.
- `python3 benchmark/report/kpis.py --run-dir benchmark/results/<run> --table` prints the KPIs the
  report would publish, the floor KPIs from the 8-sender light blast among them, as a markdown table.
  Its inputs are not scrubbed, so the output is private (see `report/README.md`).

`analysis/`, `INDEX.md` and `CHECKSUMS.sha256` are written after `collect` and at deploy step 15
(non-fatal, so an interrupted run still has them), by the teardown's local gate, and once more
after the teardown's deletes. `benchmark-teardown.sh --run <run> --reindex` writes the last two
again, locally, after files are added (see Teardown guarantees).

`manifest.archive` records the local gate: `kind` (`local`), `path` (the absolute results
directory), `verified_at`, `files` and `bytes` (what `CHECKSUMS.sha256` covers, the manifest
at its final size included), `final_index_at` and, after a `--reindex`, `reindexed_at`. Under
the override it holds `skipped_gate: true` instead of `verified_at`. Runs before the gate carry
the retired archive's `uri` and `status` here instead. The publishing scrub drops `manifest.archive`, together with
`project` and `notes`.

The provenance fields record which bytes the run measured:

| Field | Written by | Holds |
|---|---|---|
| `harness` | manifest creation | `sha` of this checkout, `dirty` (tracked files differ from HEAD; untracked files do not count) and the `submodules` HEADs of `common` and `tn-node-deployment` |
| `node_image_ref`, `node_image_digest`, `node_image_pinned` | gate | the ref probed, its digest, and the `<repo>@sha256:` ref the fleet runs |
| `node_version`, `node_git_sha`, `node_fork_schedule` | gate | the version and git sha from `telcoin -V` and `--version`, and the fork-schedule label from the contract strings |
| `node_probe` | gate | `at`, `flags_ok` and `strings`, the count of each contract string in the binary |
| `consensus_parameters` | gate | `file`, `sha256`, `max_header_delay_ms`, `min_header_delay_ms`, `max_batch_delay_ms` |
| `coordinated_start` | step 7 | the first start: `due` (unix), `nodes`, `started`, `skipped_running`, `spread_secs`, `max_late_secs` from the `COORDINATED_START` line, and `ts` |
| `coordinated_start_reruns[]` | step 7 re-runs | `{line, ts}`: each later `COORDINATED_START` line, verbatim, and when it was recorded (never replaces `coordinated_start`) |
| `fleet_ready` | steps 8 and 13 | `label`, `ts`, `ok`, `waited_secs`, `passes` and each node's `modes` (`tn_nodeMode`) |
| `obs` | steps 2 and 8, teardown | the run's `bench-obs` VM: `instance`, `zone`, `machine_type`, `disk_gb`, `created_at`, `internal_ip`, `instance_id` (step 2); `ready_at`, `prom_local_port`, `grafana_local_port`, `ship_logs` (`false`; step 8); `prom_snapshot` `{name, file, bytes, at}` (teardown). The publishing scrub drops `internal_ip` and `instance_id`. |
| `prometheus` | manifest creation | `grafana_url` (`BENCH_GRAFANA_URL`, the local forward; dropped by the publishing scrub), `datasource_uid`, `network_label` |
| `zones_used`, `zone_fallbacks[]` | step 2 | the zone each node was created in, and each stockout move: `{inst, from, to, reason: "stockout", ts}` |
| `keygen_timing`, `node_info_rpc` | step 5 | per node, from its `KEYGEN_DONE` line: `{secs, reused}`, and the `{http, ws}` RPC URLs its `node-info.yaml` advertises (successful keygens only) |
| `node_startup[<inst>]` | steps 7 and 9 | `logrotate_size` (`"20G"` or null), `params_bak` (`written`, `kept` or null) and `db_sync_mode` (`durable` or `safe-no-sync`; `durable` when `BENCH_NODE_DB_SYNC_MODE` is unset) from the `PRECFG_OK` line; `fsync_probe` from the disk probe (`{p50_us, p95_us}`, or `{probe_failed: true, reason}`); `sha`, `mhd`, `nhd`, `mbd`, `vt` and `forks` from the node's boot lines |
| `blasts[]` | step 14, light-load arm | one entry per blast of the sequence: `{index, senders, window, chaos, started, ended, rc}`. `started` is stamped before the blast's VMs are created, so it precedes the blast's phases by the create, the start delay and the preamble; the phases are in the blast's own blaster files |
| `log_rate` | step 14, light-load arm | one node's unit-log growth, one entry per blast in run order: `[{blast, inst, mb_per_min, warn}]` |
| `registry_probe` | step 10 | the `recovery-schedule.py` reading: current epoch, its opening block and duration, and the drill it would schedule from that moment |
| `admission[]`, `fleet_modes` | step 10 | per node the admission modes of the primary and worker networks, fallback, denied in/out and `tn_nodeMode`; `fleet_modes` maps each node to its mode |
| `admission_denied_check` | step 10 | with `BENCH_ADMISSION_DENIED_MAX` set: `{max, over: [<inst>…], ts}` |
| `chaos_schedule_refresh` | step 14 | the kill re-planned once the closing epoch opened: `{planned_kill_unix, kill_unix, drift_secs, closing_epoch, epoch_start_unix, ts}` |
| `prom_window` | step 15 | the Prometheus window the collector got: `{start, end, end_reason, waited_secs, confirm_secs}` |
| `deploy_result`, `deploy_runs[]` | every applied deploy | `{rc, last_step, first_error, started, ended, scope, log}` of the last invocation, and of every one |
| `log_coverage[]` | teardown | per node `{inst, generations, first_ts, last_ts, due, blast_end, ok, checked_at}` from its `LOGCOV` line |
| `timestamps.teardown_start`, `timestamps.teardown_done`, `teardown_reruns[]`, `teardown_pending[]` | teardown | the first teardown's start (just before its first delete) and the end of the first teardown whose deletes all finished; each later teardown of the run as `{start, done}`; instances still deleting at the wait cap as `{inst, zone, status, at}` (dropped once none is left) |
| `node_startup_check` | teardown | the saved logs checked against `node_git_sha` (informational) |

### Certification outcome

A validator whose own headers are not certified is a result of the run, recorded with its logs.
The usual case is a far-away validator in fast rounds. After every `collect` and at teardown,
`bench_certification_record` runs `tools/cert-rate.py --windows manifest.json --format json` over
`logs/`. `collect` does not pull node logs, so in practice the teardown records it, after the log
and evidence pulls and before the local gate. It reads only the files that match
`BENCH_CERT_LOG_GLOB` (`--node-glob`, default `bench-validator-*-unit-stdout*.log.gz`): the
validators' unit append files and their rotated generations hold the whole run once, where the
container logs, saved logs and snapshots repeat parts of it. cert-rate.py matches certificates to
subdags within one file, so a rotation that cuts a subdag loses that subdag's certificates, one
subdag per rotation. It writes `analysis/certification.json` and three manifest fields:

| Field | Holds |
|---|---|
| `certification` | `{<validator>: {<window>: {proposed, certified, rate_pct, own_cert_share_pct, own_leader_share_pct, not_committed_pct}}}` for every validator and every window cert-rate.py reports (`arm <name>`, `phase <name>`, `run`). The observer never proposes and is left out. |
| `certification_meta` | `fail_below_pct`, `min_proposed`, `windows` (in order), `source`, `recorded_at` |
| `cert_failures` | one entry per validator that certified fewer than `BENCH_CERT_FAIL_PCT` % (default 90) of its own headers in a window where it proposed at least 50: `inst`, `window` (the worst one), `rate_pct`, `proposed`, `certified`, `windows` (every failing one) and `logs` |

`bench_cert_failures_snapshot` then saves each failing validator's container log on the node as
`telcoin-cert-fail-<UTC>.log.gz`, pulls it into `logs/<node>-telcoin-cert-fail-<UTC>.log.gz`, and
lists it in `cert_failures[].logs` with the node's `-telcoin.log.gz` and `-unit-stdout.log.gz`.
The local gate requires every listed file, so a snapshot saved on the node but not pulled stops the
teardown before any delete. A validator whose instance is already gone gets the logs on disk listed
and a `manifest.notes` entry. On a teardown re-run that certifies again, a snapshot of the same
instance (same id) that a pull marker already vouches for is listed again, not taken again.

`analysis/cert-rate.md` and `analysis/block-rate.md`, which the teardown writes after its deletes,
read every pulled log once more. `BENCH_TEARDOWN_SKIP_ANALYSIS=1` skips that pass and prints the
two commands to run by hand later. It does not skip the certification record above, which a
first teardown always runs.

A teardown re-run whose manifest already holds `certification` skips the certification pass and its
cert-fail snapshots, with one line:
`certification: already recorded at <recorded_at> — skipped (BENCH_TEARDOWN_RECERTIFY=1 re-runs it)`.
Bench 4's re-run read every validator log again for about 70 minutes and took three snapshots again.
`BENCH_TEARDOWN_RECERTIFY=1` (default 0) runs the pass and the snapshots as before. When a log that
`manifest.cert_failures` lists is missing (the first teardown's snapshot pull failed), the snapshot
step still runs, with a ⚠ line naming the logs, so the local gate can pass on the re-run;
cert-rate.py does not.

Running it again (every `collect`, and a teardown that certifies) replaces `certification` and
merges `cert_failures` by validator. A validator
judged again keeps its listed logs that are still on disk. One that passes now loses its entry,
with a note, and its files stay. A validator with fewer than 50 proposals in every window is not
judged. Neither step stops a collect or a teardown: a failure is a warning, and the local gate
decides. The teardown prints the outcome in its last lines.

`report/make_bundle.py` publishes it. The built report gets a "Certification by node" section
after "Consensus health": one row per validator with its region, its rate in every window, and its
own-leader and not-committed shares over the run, next to the fair share (100 / validators). When
`cert_failures` is not empty, run.json gets a caveat naming the validators, the threshold and the
windows. The site's run.json schema has no field for the table. An archived report is copied byte
for byte, so it gets the caveat only.

## Teardown guarantees

`benchmark-teardown.sh` collects its candidates first: bench instances (`bench-obs` among them),
bench firewall rules, buckets labelled `benchmark=1` or named `tn-devnet-bench-*` (copied into
`results/<run>/bucket/` first; a non-empty bucket whose copy fails is left in place), orphaned bench
disks, the compute SA's bindings on the bench secrets, the contracts worktree, `bench/r*`
branches with no commits of their own, and local IAP tunnels. It deletes nothing if any single
guard fails. It keeps the `bench-txgen-*` secrets unless you pass `--purge`. At the end it
prints the "left nothing" checks, which confirm that no labelled or `bench-*` resource remains,
that every devnet instance is still present, and that `devnet-allow-consensus` matches the
pre-run snapshot. It also prints the file count and size of `results/<run>/`, which it keeps.

First, before it lists anything (a dry run too), it checks the gcloud credentials:
`gcloud auth print-access-token` must answer within 60 s. Otherwise it prints `gcloud has no
usable credentials … NOTHING was pulled or deleted` with the `gcloud auth login` command and the
re-run line, and exits 1. A long pull that outlives an expired session cannot finish, and a
half-pulled fleet is the worst place to find out. A `BENCH_TEARDOWN_*` knob with a value it does
not take stops the teardown before anything too.

Nothing is deleted until five gates pass, in this order:

1. **Logs.** Every live node's logs are pulled to `results/<run>/logs/` (`BENCH_TEARDOWN_SKIP_LOGS=1` overrides).
   A node whose pull marker still holds is not pulled again (see "Pull markers and re-runs" below).
   Before the pull starts, the filesystem under `results/<run>/logs/` must have
   `BENCH_TEARDOWN_MIN_FREE_GB` GB free (default 20, `0` skips the check). Below that, or when
   `df` cannot be read, the teardown prints the free space, says `NOTHING was deleted` and exits 1
   with nothing pulled. When a session finds that gcloud needs re-authentication (a `reauth`
   fault, see [IAP sessions and retries](#iap-sessions-and-retries)), no further pull starts and
   the teardown exits 1: `gcloud needs re-authentication (the session expired during the log pull)
   — NOTHING was deleted`, with the login hint. It checks for that again after the certification
   snapshots.
2. **Recovery evidence.** Each node's service journal and sampler files are pulled.
3. **Certification.** `tools/cert-rate.py` runs over the pulled logs and records every validator's
   per-window certification in `manifest.certification`; a validator that certified fewer than
   `BENCH_CERT_FAIL_PCT` % (default 90) of at least 50 proposed headers in a window is listed in
   `manifest.cert_failures[]`, its container log is saved on the node as a `cert-fail` snapshot and
   pulled, and every one of its logs is named in `cert_failures[].logs[]` (see "Certification
   outcome"). This step warns rather than blocks; the local gate enforces the files it listed. A
   re-run whose manifest already holds `certification` skips it unless `BENCH_TEARDOWN_RECERTIFY=1`.
4. **Coverage.** Every node's pulled unit logs must span the run. `bench_log_coverage_check`
   reads the node's `logs/<node>.logspan` and prints one line,
   `LOGCOV <inst> gens=<n> first=<ISO> last=<ISO> due=<ISO> end=<ISO> ok=<0|1|->`, recorded in
   `manifest.log_coverage[]`. The earliest line of all the node's generations must be at or
   before `coordinated_start.due` and the latest at or after `timestamps.blast_end`. A node with
   `ok=0` (its logs start late or end early), or with no `LOGCOV` line, stops the teardown:
   `NOTHING was deleted`, exit 1. `ok=-` means the coverage is unknown. When the run's window is
   known (a coordinated start and a blast end), the instance still exists and
   `BENCH_TEARDOWN_SKIP_LOGS` is not `1`, it counts as not covered (`no recorded span … counted as
   not covered`, `ok: false` in the manifest): a live node's pull always records a span, so a
   missing one is a broken pull. Otherwise (no window, a node already gone, or
   `BENCH_TEARDOWN_SKIP_LOGS=1`) it is a note, not a failure. Coverage is judged from the span the
   node reported for its own files at the pull, not from how far the local copies reach; a
   generation the span lists that did not land fails the pull itself (no marker, so the log gate
   stops the teardown). `BENCH_TEARDOWN_SKIP_COVERAGE=1` warns, adds a `manifest.notes` entry and
   deletes anyway.
5. **Local gate.** `results/<run>/` is the only copy of the run, so for every node in
   `INSTANCE_NAMES` it must hold a non-empty `logs/<node>-telcoin.log.gz`,
   `logs/<node>-unit-stdout.log.gz` and `logs/<node>-recovery-*.tgz`, plus a `manifest.json`
   that parses and every log listed in `manifest.cert_failures[].logs[]` (relative to
   `results/<run>/` unless absolute). A node whose instance is already gone needs these from an
   earlier pull. If anything is missing, the teardown names every missing file, prints
   `NOTHING was deleted` and exits 1. Otherwise it writes `INDEX.md` and `CHECKSUMS.sha256` and
   sets `manifest.archive` (see Outputs). `BENCH_TEARDOWN_SKIP_LOCAL_GATE=1` deletes even with
   files missing: it warns, sets `manifest.archive.skipped_gate` and adds a `manifest.notes`
   entry. `BENCH_TEARDOWN_SKIP_LOGS=1` does not relax this gate; a node it abandoned needs this
   override too.

`bench-obs` holds the run's metrics, so the teardown reads it before anything is deleted and
deletes it with the fleet:

- **Forwards.** When the VM exists and is a candidate (labelled `benchmark=1`, in
  `BENCH_OBS_ZONE`), its two local forwards come up first (`bench_obs_urls`,
  `bench_obs_tunnel_up`), so the health table and the snapshot read its Prometheus. With no
  `bench-obs` the teardown warns and pulls no snapshot. One that is listed but that `instances
  describe` does not answer for stops a `--yes` teardown with nothing pulled or deleted. One
  without `benchmark=1` is not this run's: it is neither read nor deleted.
- **Snapshot.** After the certification snapshots, and so before the coverage and local gates,
  `bench_obs_prom_snapshot_pull` asks Prometheus for a TSDB snapshot (admin API) and streams it
  into `logs/bench-obs-prometheus-<UTC>.tar.gz`. It prints
  `OBS_SNAPSHOT inst=<i> name=<snapshot> bytes=<n> file=<path>` and records
  `manifest.obs.prom_snapshot`, and the local gate indexes and checksums the file. The pull only
  warns: a failed one leaves no snapshot and the teardown goes on. `BENCH_OBS_PULL_PROM=0` skips
  it. Neither gate requires it.
- **Delete.** After the local gate and every Prometheus read, `bench-obs` gets a `GATE_IDS` row
  and the same id re-check and background delete as every other instance. Its boot and data disks
  auto-delete with it; one left behind is an orphan disk labelled `bench-run=<run>`, which the
  orphan-disk step deletes. The left-nothing checks count `bench-obs`, the disks labelled
  `bench-run=<run>` whatever their name, and the local forwards on 18545, 19090 and 13000.
- **obs-devnet** stays on the denylist, and the left-nothing checks confirm it is still present
  with the other devnet instances.

The dry run lists `bench-obs` with the other instances, prints the two forwards' plan lines and
the snapshot's argv, and deletes nothing.

A dry run ends with a gcloud argv check. Every gcloud command the teardown can issue
(`td_gcloud_argv` in `benchmark-teardown.sh`: its own calls and those of the helpers it calls) and
every flag it gives them are looked up in the installed SDK's help, one `gcloud <command> --help`
per command, all at once (about 8 s; local, no project, no network). It prints
`GCLOUD_ARGV_OK <n> commands, <m> flags`, or one `❌ GCLOUD_ARGV gcloud <command> rejects --<flag>`
per flag the SDK does not know (and `❌ GCLOUD_ARGV gcloud <command>: not a command of this SDK`
per missing command) and exits 1 without `TEARDOWN_DONE`. Bench 4's third teardown attempt died at
its first delete on `--async`, a flag only the test fake accepted. `BENCH_SKIP_GCLOUD_ARGV_CHECK=1`
skips the check with a note, as does a machine without gcloud on PATH; a `--yes` run never runs
it. A new gcloud flag in the teardown or its helpers goes on its `td_gcloud_argv` line too:
test_teardown_local_gate fails otherwise. The node-side `gcloud storage cp` of the bucket transfer
runs on the node's own SDK, which the check does not see.

Each instance is deleted with `--quiet` in the background (gcloud has no `--async` for instance deletes) right after its id is re-checked. One loop then
describes every instance still deleting, every 10 s, until each is gone or
`BENCH_TEARDOWN_DELETE_WAIT_SECS` (default 600; `0` is a single pass) have passed; an instance
still there is reported, listed in `manifest.teardown_pending[]` (`{inst, zone, status, at}`)
and counted by the left-nothing checks. `manifest.timestamps.teardown_start` is the first
teardown's, written once just before its first delete. `timestamps.teardown_done` is written
once, by the first teardown that ends with nothing pending: a teardown that leaves instances
still deleting records them in `teardown_pending[]` and no done time, and a later run that finds
nothing left to wait for writes the done time and drops the list. A later teardown of the same
run never moves `teardown_start`; it appends `{start, done}` to `manifest.teardown_reruns[]`. The last line
of a teardown that reaches its end is
`TEARDOWN_DONE run=<id> deleted=<instances confirmed gone> left=<items the left-nothing checks still see> at=<UTC>`,
with ` dry_run=1` appended in a dry run.

The dry run runs the gate's checks against what `results/<run>/` holds at that moment (it pulls
nothing) and says which files it would write. After the deletes and the provenance check below,
the teardown writes `analysis/` (the node logs are on disk by then), then `INDEX.md` and
`CHECKSUMS.sha256` again over the final tree, which now holds the run bucket's copy and
`genesis/`, and records `manifest.archive.final_index_at`. That last step only warns when it
fails.

Analysis written into `results/<run>/` after the teardown (a sweep's summary, per-arm tables) is
in neither file until the tree is indexed again:

```bash
benchmark/benchmark-teardown.sh --run <run> --reindex
```

It rewrites `INDEX.md` and `CHECKSUMS.sha256` over the tree as it is, updates
`manifest.archive.files` and `.bytes` (and sets `.reindexed_at`) when the manifest holds a local
archive record, prints the file count and bytes, and exits. It makes no gcloud call, runs no
gate, deletes nothing and refuses without `--run`. In `INDEX.md`, a top-level analysis file the
harness does not write gets its own row, and each subdirectory of `analysis/` gets one row.

Before the final index, once teardown has saved the node logs and finished the deletes, it runs
an informational provenance check:

```bash
python3 benchmark/report/provenance.py --run-dir benchmark/results/<run> --update-manifest
```

It finds each node's start line in the saved logs, compares the build with
`manifest.node_git_sha` and writes the result to `manifest.node_startup_check`. A mismatch adds
a warning and a `manifest.notes` entry, and finding no start lines is a warning. With
`BENCH_TEARDOWN_SKIP_LOGS=1` it reads whatever logs were saved. It never blocks the teardown.

### Pull markers and re-runs

A node's pull goes in this order: the span of its unit logs, its current container's log, the
logs saved on the node, the unit's append files, then their rotated generations. Every one of
these transfers is `bench_pull_stream`'s (`pull-lib.sh`). Each attempt writes a fresh temp file
with devnet-lib's own retry off, and the bytes are checked whole (`gzip -t`, or `tar -tf` and the
archive's end blocks) before they are renamed into place. A session that drops, an IAP refusal,
or one that exits 0 with bytes that do not check (a cut stream) is tried again, up to
`BENCH_IAP_RETRIES` attempts (default 3), 10 s and then 20 s apart. A `reauth` fault touches a
stop file, and no pull starts after it. Before, devnet-lib's retry sent every attempt's stdout to
the same file, so a retried pull could hold a cut stream followed by the whole one.

The span comes first, read on the node before anything is copied: one line per unit log and
generation (`telcoin.log`, `telcoin.log.1`, `telcoin.log.<N>.gz`, and the same for
`telcoin-error.log`),
`LOGSPAN <inst> stream=<stdout|stderr> gen=<N> file=<node path> bytes=<n|-> first=<ISO|-> last=<ISO|->`,
saved as `logs/<node>.logspan`. `first` is the first timestamped line among a file's first 20,
`last` the last among its last 20 (read for generations 0 and 1 only); a missing live file shows
`gen=0 … bytes=- first=- last=-`. The coverage gate reads it (see Teardown guarantees). The
rotated generations land as `<node>-unit-<stream>.rotated-<N>.log.gz`: `.1` gzipped on the node,
`.<N>.gz` as they are. When a pull's copy would take a name that already holds a file, and no
marker of this instance vouches for that file, the copy lands beside it under a stamped name
(`<node>-unit-<stream>-<UTC>.rotated-<N>.log.gz`, or `-<UTC>` before `.log.gz` for the other
logs). A stamped copy byte-identical to the file it stands beside is dropped, and that file counts
as this pull's: gzip on the node stores nothing that changes between two pulls of an unchanged
file (no time, or the file's own mtime), so they are the same bytes.

Each node that passes the log pull gets `logs/<node>.pulled`. The marker names the instance id
and the pull time and lists every log file it vouches for with its byte size. A re-run skips a
node only when one of its markers is in the current format and complete, names the node and
the id of the instance that holds the name now, lists files that are all still in `logs/` at
exactly the recorded sizes, and is fresh: pulled at most 15 minutes ago. An older marker is
rejected ("pulled …, more than 15 min ago; the node has logged since"). The node is pulled
again, and its new copies land beside the old ones under stamped names.

A marker this teardown pulled itself is exempt from that age rule however long the pull took: a
marker of this run whose pull time is at or after the moment the teardown started counts as the
teardown's own, and only the age rule is lifted for it (a missing or resized file, another instance
id or a pull time in the future still refuse it). Bench 4's teardown pulled for 4h19m and then
refused the eight markers it had written more than 15 minutes earlier, deleting nothing. Every
marker line ends in how its age was judged: `[fresh:this-invocation]`, `[fresh]` (an earlier
teardown's, within 15 minutes), `[trusted]` (older, accepted by `BENCH_TEARDOWN_TRUST_MARKERS=1`) or
`[stale]` (older, refused). After a pull the teardown prints the marker lines of every node it
pulled under `markers after the pull`.

The pull copies each node's whole container log as it is at that moment. A fleet left up after
the run keeps logging, so a later pull can be far larger than the run's own logs. The
certification step (gate 3) pulls one more whole-log snapshot of each failing validator, on every
teardown that certifies (the first, and a re-run with `BENCH_TEARDOWN_RECERTIFY=1`), after the
free-space check. Check `df -h benchmark/results` before a
teardown, and before every re-run.

`BENCH_TEARDOWN_TRUST_MARKERS=1` (default `0`) lifts the age rule and nothing else. Use it to
re-run a teardown that was interrupted after some nodes were saved, for example by an expired
gcloud session, when those logs are the ones you want and the lines the nodes logged since
(an idling fleet) are not. Every other check still applies; a vouched file that is missing or
has a different size means the marker is not accepted, and the verdict names the file. A node
accepted this way is not pulled again at all, and its verdict line ends
`(BENCH_TEARDOWN_TRUST_MARKERS=1) [trusted]`. Once the log gate passes, the manifest gets one note naming
each such node and its marker's pull time:
`teardown: saved logs accepted from markers older than the freshness window (BENCH_TEARDOWN_TRUST_MARKERS=1): bench-validator-01@2026-10-07T03:12:40Z …`.
Nodes without an intact marker are pulled as usual.

```bash
df -h benchmark/results
BENCH_TEARDOWN_TRUST_MARKERS=1 benchmark/benchmark-teardown.sh --run <run>         # dry run: read the marker lines
BENCH_TEARDOWN_TRUST_MARKERS=1 benchmark/benchmark-teardown.sh --run <run> --yes
```

### Log transfer through the run bucket

With `BENCH_LOG_TRANSFER=bucket` the teardown takes the same logs another way. Each node gets one
IAP session in which its own gcloud streams every log the IAP pull would take (the current
container's log, the saved logs, the unit files and their rotated generations, gzipped on the node
exactly as the IAP pull gzips them) to `gs://<run bucket>/logs/<node>/<local file name>`, counting
the bytes it sends (`PULLED <name> bytes=<n>`); the same session prints the node's `LOGSPAN` lines
first. `BENCH_PULL_JOBS` (default 4) nodes go at a time. After every node, one
`gcloud storage cp -r gs://<run bucket>/logs/*` copies everything into a work directory beside the
logs; each file is checked (the node's byte count, `gzip -t`) and renamed to the name the IAP pull
gives it, and each node gets the same marker the IAP pull writes, so the local gate, the
certification pass and the index see no difference. The objects are then removed from the bucket
(otherwise the bucket backup at the delete step would copy them again). The teardown prints
`LOG_TRANSFER mode=bucket nodes=<n>` before and `LOG_TRANSFER_DONE mode=bucket bytes=<n> secs=<n>`
after. gcloud needing re-authentication during the sessions or the download stops the teardown the
same way it stops an IAP pull. Bench 4's IAP pull took 4h19m at about 2 MB/s per session; the
bucket transfer's time is the nodes' uploads (inside GCP) plus one download bounded by this
machine's link.

Before any session it checks that the run bucket exists and that every node's service account has a
GCS write scope (`cloud-platform` or `devstorage.read_write`); if not, a dry run says so on a `✗`
line and a `--yes` run stops with nothing sent. Bench nodes created by `common/create-instances.sh`
have `devstorage.read_only`, so the bucket transfer needs a scope change there first; until then the
preflight refuses it on this fleet and `iap` (the default) is the transfer to use.

## Publishing

`benchmark/report/make_bundle.py` turns one run's results into a scrubbed bundle for the public
benchmark site. It reads `results/<run>/` without changing it and works in
`work/report/<run>/`. It checks the node logs against `manifest.node_git_sha` and refuses a
mismatch unless you pass `--allow-provenance-mismatch`, and a run with any `safe-no-sync` node
(`manifest.node_startup[<inst>].db_sync_mode`) unless you pass `--allow-safe-no-sync`. It exits 1 when the finished bundle
fails its own leak scan or the site's check. [`report/README.md`](report/README.md) covers
the pipeline, the flags and the backfill format.

Findings from a run that still need work, and that the public bundle must not carry, go in
`benchmark/private/followups.md`. `private/`, `work/`, `results/` and `genesis/` under
`benchmark/` are gitignored and never committed.
