# Publishing pipeline

The scripts in this directory turn one benchmark run in `benchmark/results/<run>/` into a
bundle for the public site repository, `Telcoin-Association/tn-benchmarks`. A bundle is the
directory `runs/<run>/` in that repository:

| File | Contents |
|---|---|
| `run.json` | The run in the `tn-bench-site-run/v1` schema. The schema is `RUN_SCHEMA` in the site's `scrub.py`. |
| `report.html` | The full report from `build-report.py`, or an archived report copied byte for byte. |
| `series/tps-1s.json` | Chain TPS per second over the merged mixed window, at most 2000 rows. |

How a run is deployed, blasted and collected is in [`../README.md`](../README.md). This file
starts where that one ends, with a finished `results/<run>/` directory.

## Prerequisites

- Python 3.9 or later, standard library only. On macOS, `/usr/bin/python3` is 3.9 and is the
  easy way to check that nothing newer slipped in.
- A tn-transaction-generator checkout at `../tn-transaction-generator`, next to this
  repository, or set `BENCH_TXGEN_REPO`. The pipeline runs `aggregate.py`, `derive-sizing.py`
  and `build-report.py` from its `bench/` directory. Its `bench/reference-chains.json` is not
  used (see the report step).
  `--txgen-bench DIR` names a `bench/` directory directly.
- A tn-benchmarks checkout at `../tn-benchmarks`, or set `BENCH_SITE_REPO`. Its `origin` must end in
  `Telcoin-Association/tn-benchmarks` or `Telcoin-Association/tn-benchmarks.git` (any host form,
  owner and repo case-insensitive). `make_bundle.py` refuses to write into a checkout with
  any other origin. The site's `build.py` and `scrub.py` run as the final gate.

## Modules

The directory is not a package. Each module is a script with the standard library only, and
`make_bundle.py` imports the others by path.

| Module | What it does |
|---|---|
| `make_bundle.py` | The entry point. Runs the pipeline below and writes the bundle. |
| `provenance.py` | Reads the node logs saved with the run and checks which build ran. |
| `windows.py` | Works out the measurement windows, the 5-minute blocks and the 1-second series. |
| `kpis.py` | Computes the 13 KPIs and the recovery record. |
| `scrub.py` | The first leak gate. Scrubs the report inputs and scans the finished bundle. |

### provenance.py

Every node logs `telcoin-network <version> (<40-hex sha>) starting` when it starts. While it
loads its configuration it logs `Max header delay set to ... ms`, `Min header delay set to ...
ms` and `Max batch delay set to ... ms`. Builds that have one also log a fork-schedule line.
The module reads logfmt, JSON and plain lines, and strips ANSI colour codes.

It labels the fork schedule with the same labels as the node image probe: `adiri-schedule`,
`subsecond-from-genesis`, `pre-subsecond`, or none. The unit stdout files repeat the
container logs, so repeated starts (same instance, timestamp, version and sha) count once.
Files in `logs/` that are not node logs (`deploy-*`, `blast-*`, `create-*`) are skipped.

```
python3 benchmark/report/provenance.py --run-dir DIR [--expect-sha SHA] [--update-manifest] [--json]
```

Exit 0 when the check passes, 1 when it fails, 2 when no start line was found.
`--update-manifest` writes the result to `DIR/manifest.json` as `node_startup_check` and keeps
every other key, the key order and the file mode. Teardown runs it this way.

The 29 September baseline build does not log its vote timeout. When a build does (`Vote
timeout set to ... ms`), the value is used. A run's `consensus` block is published only when
the logs or the backfill supply `vote_timeout_ms`.

### windows.py

Each blaster records its own `mixed` phase. Blasters start at different times, so a blast has
two windows:

- **Merged mixed**: earliest mixed start to latest mixed end. This is `landed.window_secs` in
  `combined.json`, and the module checks that the two agree.
- **All generators**: latest mixed start to earliest mixed end, the stretch when every blaster
  was in its mixed phase. It is null, with a caveat, when the mixed phases do not overlap.

`kpis.py` also uses **run**, the whole blast. Windows are half-open `[start, end)` in whole
unix seconds. Seconds missing from the per-second chain series count as zero. GCP,
Prometheus and sampler points use inclusive bounds, as `derive-sizing.py` does.

```
python3 benchmark/report/windows.py <blasters-dir> <combined.json> [--blocks]
```

It prints the windows as JSON, plus 5-minute blocks with `--blocks`. Exit 1 when it finds a
problem, 2 on bad input.

### kpis.py

Healthy validators are the manifest's validators minus the chaos targets. A chaos target is an
instance the harness took down and held down (`docker kill`, `systemctl stop`, `lag-pause`). A
plain `systemctl restart` is not a target. "Busiest" is the healthy validator with the highest
p95 of that measure. Every percentile is nearest-rank, the same function `derive-sizing.py`
uses. Values are rounded half-up to a fixed number of decimals per KPI.

| KPI id | Window | Source | Published as |
|---|---|---|---|
| `avg_chain_tps_all_generators` | all generators | `combined.series.per_second[chain_tx]` | mean tx/s; the headline |
| `best_60s_chain_tps_all_generators` | all generators | `combined.series.per_second[chain_tx]` | best 60 consecutive seconds, tx/s |
| `landed_total` | run | `combined.totals.landed_chain` | tx |
| `blocks_per_sec` | merged mixed | `combined.blocks.rows[timestamp]` | blocks in the window / its length |
| `time_to_land_p50_s` | run | `combined.latency.ts_ms.p50` | s |
| `time_to_land_p95_s` | run | `combined.latency.ts_ms.p95` | s |
| `commit_latency_p95_s` | merged mixed | `metrics.prometheus.series.tn_primary_commit_latency_seconds`, p95 per healthy validator | s, range over validators |
| `execution_time_per_output_s` | merged mixed | `metrics.prometheus.series.tn_engine_execution_duration_seconds`, median of the mean per healthy validator | s, range over validators |
| `disk_write_p95_mibps_busiest` | merged mixed | `metrics.gcp[<busiest>].disk_write_bytes_per_sec` p95 | MiB/s |
| `disk_write_iops_p95_busiest` | merged mixed | `metrics.gcp[<busiest>].disk_write_ops_per_sec` p95 | IOPS |
| `cpu_p95_pct_busiest` | merged mixed | `metrics.gcp[<busiest>].cpu_utilization` p95 | % |
| `rss_p95_gib_busiest` | merged mixed | `metrics.gcp[<busiest>].telcoin_rss_bytes` p95 | GiB |
| `psi_io_max_pct` | merged mixed | `sampler[healthy validators].psi_io_some_avg10` max | %, range over validators |

A KPI whose inputs are missing is left out and a caveat says why.

Recovery covers one chaos target. Killed and restarted come from `manifest.chaos`. Demoted and
rejoined come from `tn_node_mode{mode="cvv_inactive"}`, at 15-second resolution: the rejoin is
the first active sample after the node's LAST inactive sample, so it must stay active to the end
of the metrics window (a promotion followed by another inactive sample is a transient, counted in
a caveat, not a rejoin); when the last sample is still inactive, rejoined and `catch_up_secs` are
null and the backfill supplies them from the node log. `catch_up_secs` is demoted to rejoined.
`failed_reports` is the collector's window count of
`tn_batch_builder_seal_failures_total{reason="failed_to_report"}` for the target (the counter's
rise over the window). Runs without those series get killed and restarted times only.

### scrub.py

```
python3 benchmark/report/scrub.py inputs <scratch_dir> <scrubbed_dir>
python3 benchmark/report/scrub.py scan <dir> [--manifest raw-manifest.json]
```

`inputs` writes scrubbed copies of `manifest.json`, `metrics.json`, `combined.json` and
`sizing.json`, and copies `sampler/*.csv` after checking that each is an identifier header
plus numeric rows. `build-report.py` only ever sees the scrubbed copies.

Keys dropped wherever they occur: `internal_ip`, `external_ip`, `instance_id`, `node_url`,
`grafana_url`, `bucket`, `bucket_name`, `bucket_prefix`.

Keys dropped per file:

| File | Dropped |
|---|---|
| `manifest.json` | `project`; `notes`; on each `instances[]` and `blasters[]` entry, every key ending in `ip`, `ips`, `id` or `ids`; `blasters[].node_url`; `prometheus.url` and any `prometheus.*_url`; any key containing `bucket` under `fund` and `blast` |
| `metrics.json` | `project`; the same host keys on `instances[]`; `prometheus.url` and any `prometheus.*_url` |
| `combined.json` | nothing dropped; `nodes[].url` becomes `http://<instance-name>:<port>` |
| `sizing.json` | nothing dropped; string rewrites only |

String rewrites, in every file:

- A dotted quad from the manifest's IP map becomes the instance name. Any other dotted quad,
  except `0.0.0.0` and `127.0.0.1`, becomes `redacted-ip`. This is wider than RFC 1918 on
  purpose, because the site gate rejects every dotted quad.
- An image path in the private registry loses its `<host>pkg.dev/<project>/<repo>/` prefix,
  so `txgen_image` keeps its name and tag.
- A host path under `/Users`, `/home`, `/private`, `/var/folders`, `/root` or `/tmp` becomes its
  basename. Container paths such as `/var/lib/bench` are kept.

`scan` checks a finished bundle. A finding names the file, line and rule, never the matched
text, so a CI log does not repeat the leak. The denylist:

| Rule | Matches |
|---|---|
| `private-ip`, `ipv4` | any dotted quad except `0.0.0.0` and `127.0.0.1` |
| `internal-name` | the GCP project id, `gs://`, the observability hostname prefix, the load-generator secret prefix, and the key names `internal_ip`, `external_ip`, `instance_id`, `node_url` (exact literals live in scrub.py) |
| `local-path` | `/Users/`, `/home/`, `/private/tmp/`, `/private/var/`, `/var/folders/`, `C:\Users` |
| `artifact-runtime` | markers left by a hosted page runtime |
| `private-key` | `-----BEGIN` |
| `secret-assignment` | `passphrase`, `mnemonic` or `private_key` followed by `:` or `=` |
| `email` | an e-mail address |
| `gcp-internal-dns` | `*.c.<project>.internal`, `metadata.google.internal` |
| `token` | GitHub, AWS and Google token shapes |
| `hex64` | `0x` plus 64 hex digits |
| `manifest-ip`, `manifest-instance-id`, `manifest-name` | built from the raw manifest: its IPs, instance ids, project, bucket names and Grafana host |
| `symlink`, `unexpected-file` | a symlink, or a file that is not `.json`, `.csv` or `.html` text |

This list is a first pass. The rule table that decides what is published lives in the site
repository's `scrub.py`, and its `build.py --check` is the final gate. If the two disagree, the
site wins. Fix this side to match, not the other way round.

## The pipeline

`make_bundle.py` prints one log line per step, numbered in execution order (`0 setup` to
`10 gates`).

1. **Setup** (`0 setup`). The out directory's last component must be the run id. If it lies in
   a git checkout, that checkout's origin must be tn-benchmarks. A foreign file in the out
   directory is refused before any work. The backfill is loaded and checked. With `--compare`,
   an existing scratch of the compare run built from another blast is refused here too.
2. **Scratch** (`1 scratch`). An allowlisted copy of `results/<run>/` goes to
   `benchmark/work/report/<run>/`: `manifest.json`, `metrics.json`, `blasters/*.json` and
   `sampler/*.csv`, plus an empty `reference-chains.json` (`[]`). With `--blast-index N` the
   manifest, metrics and blasters come from `blast-N-*/`. Nothing else is copied: no node logs
   (25-80 GB for a run with a debug log filter), no `genesis/`, `bucket/`, `meta/`, `funder/` or
   `evidence/`. The scratch directory holds the tools' inputs and outputs only. An existing
   scratch directory is refused unless you pass `--force`.
3. **Provenance** (`2 provenance`). The node logs in `results/<run>/logs/` are read in place
   (never copied) and checked against the expected sha:
   `manifest.node_git_sha`, else the backfill's `upstream.sha`. A mismatch stops the run here,
   before the slow steps, unless you pass `--allow-provenance-mismatch`. That publishes with
   evidence `inferred` and a caveat. A run with no node logs takes its evidence from the
   backfill, `inferred` or `not-recorded`.
4. **Tools** (`3 tools`). `aggregate.py` writes `combined.json` and `derive-sizing.py` writes
   `sizing.json`, both run in the scratch directory with relative paths.
5. **Scrub** (`4 scrub`). `scrub.scrub_inputs()` writes `scratch/scrubbed/`.
6. **Report** (`5 report`). `build-report.py` runs inside `scrubbed/` with relative paths only,
   including `--reference reference-chains.json`. Its default `--reference` is an absolute
   path, which would end up in the report footer. That file holds `[]`, so the report shows the
   "Reference chains" heading with a one-line "Not collected: reference chains." note and no
   table. The tool's own table puts this run's busiest single second beside other chains'
   sustained figures, which misleads on a page that can be shared on its own. The site's "Other
   networks" section carries cited figures with their method instead. With `--compare R2`, R2's scratch and
   scrubbed inputs are built or reused under `benchmark/work/report/R2/` and passed as
   `../../R2/scrubbed`. They come from R2's top-level results, or from `blast-M-*/` with
   `--compare-blast-index M`. With `--archived-report` the archived file is used instead and
   `build-report.py` does not run.
7. **Windows** (`6 windows`). Merged and all-generators windows, the 5-minute blocks for
   `run.json` and the 1-second series.
8. **KPIs** (`7 kpis`). `kpis.compute()` plus the backfill's `kpis_published`, and recovery.
9. **Assemble** (`8 assemble`). `run.json` with every `RUN_SCHEMA` key and nothing else.
10. **Write** (`9 write`). `run.json`, `report.html` and `series/` go to a staging directory
    next to the out directory, `<parent>/.<run>.tmp-<pid>/<run>/` (inside the site that is
    `runs/.<run>.tmp-<pid>/<run>/`), on the same filesystem.
11. **Gates** (`10 gates`). On the staged bundle: the harness `scrub.scan_dir()` must be clean,
    then the site check runs: `build.py --check <staged path>` when the out directory is in the
    site repository and `build.py` exists, else the site's `scrub.py <staged path>`.
12. **Install** (`11 install`). The previous bundle, if any, is moved aside and the staged one
    moved into place; the site check then runs once more on the out directory, and if it fails
    the previous bundle is restored. A failure in steps 10-12 exits 1 and leaves the out
    directory as it was (the previous bundle, or nothing); the error says which. The staging
    directory is always removed.

Exit status: 0 ok, 1 refused or a gate failed, 2 usage error.

The scratch directory is kept after a run, so a later `--compare` can reuse it. `--force`
deletes and rebuilds it, and only after the sources are known to be usable. Each scratch
directory holds a `.source.json` marker: `{run, blast_index, source, built_at}`.

## Usage

A new run, compared against the 29 September run:

```
python3 benchmark/report/make_bundle.py --run <run> --compare r20260929-1647 \
    --compare-blast-index 0 [--backfill benchmark/report/backfill/<file>.json]
```

`--compare-blast-index 0` compares against the published blast 0. Without it the compare reads
the 29 September run's top-level results, which are its blast 1 (the lag-pause test).

The 29 September run. Its first blast is published from the run's results, with the archived
report as `report.html`:

```
python3 benchmark/report/make_bundle.py --run r20260929-1647 --blast-index 0 \
    --compare r20260923-0515 \
    --archived-report benchmark/work/report/archived/r20260929-1647.html \
    --backfill benchmark/report/backfill/2026-09-29-hyperdisk.json
```

A page with no raw results, where `run.json` comes from the backfill alone. `--no-results`
needs both `--archived-report` and `--backfill`:

```
python3 benchmark/report/make_bundle.py --run r20260828-devnet --no-results \
    --archived-report benchmark/work/report/archived/2026-08-devnet-native.html \
    --backfill benchmark/report/backfill/2026-08-28-devnet.json
```

Other flags: `--out DIR` writes somewhere other than the site checkout, and the last path
component must still be the run id. `--analysis-sha SHA` sets `generator.analysis_sha`
(default: the backfill, else the tools' git HEAD).

After a bundle passes, review the diff in the site checkout, then commit it there. The site's
GitHub Action builds and deploys the pages.

## Backfill JSON

A backfill is a single JSON object written by hand. It fills in what a run did not record.
Every key is optional unless marked. Keys starting with `_` are comments and are ignored. Any
other unknown key is an error. A draft marker such as `<<RESULT>>` anywhere in a value, or in the
assembled `run.json`, refuses the build with a message naming the field.

| Key | Contents | Where the backfill wins |
|---|---|---|
| `title`, `summary` | text | Default is generated. Required with `--no-results`. |
| `status` | `complete`, `aborted` or `superseded` | Wins, except that `aborted` from `manifest.abort` wins over it. |
| `date` | `YYYY-MM-DD` | Wins over the deploy date. Required with `--no-results`. |
| `started_utc`, `ended_utc` | `YYYY-MM-DDTHH:MM:SSZ` | Used with `--no-results` only. |
| `compare_to` | run id | Used when `--compare` is not given. |
| `upstream` | `sha` (7 to 40 hex), `branch`, `evidence` (`inferred` or `not-recorded`), `evidence_detail` [text] | `branch` wins (default null). `evidence` is used when the run has no node logs. `evidence_detail` is appended. A full sha is published as `sha`, a short one only as `short`. |
| `node_image` | `ref`, `digest` (`sha256:<64 hex>`), `version`, `fork_schedule` | Fills nulls. |
| `generator` | `sha`, `image_digest`, `analysis_sha` | Fills nulls. `--analysis-sha` wins over it. |
| `harness` | `sha`, `submodules` {name: sha or null} | Used when the manifest has none. |
| `fleet` | `label`, `validators`, `observers`, `machine_type`, `vcpus`, `memory_gb`, `disk` {`type`, `size_gb`, `iops`, `throughput_mibps`}, `regions` [text], `load` {`blasters`, `machine_type`, `senders_each`, `placement`} | Every key given wins. `disk` and `load` merge key by key. |
| `chain` | `chain_id`, `network`, `epoch_secs` | Fills nulls. |
| `consensus` | `max_header_delay_ms`, `min_header_delay_ms`, `max_batch_delay_ms`, `vote_timeout_ms`, `file`, `confirmed_by` | Numbers fill values the run did not record; a conflicting number is an error. The `file` and `confirmed_by` labels win. Without `vote_timeout_ms`, `run.json` carries `consensus: null`. |
| `workload` | `warmup_secs`, `mixed_secs`, `cooldown_secs`, `tx_types` [text] | Fills nulls. |
| `methodology`, `caveats` | [text] | Backfill caveats come first, computed caveats follow. |
| `kpis_published` | [{`id`, `label`, `short_label`, `value` or `range` [lo, hi], `unit`, `window` or null, `source`, `method` or null, `provenance: "published"`}] | Appended to the computed KPIs. Ids must not collide with computed ones. |
| `recovery` | `node`, `killed_utc`, `restarted_utc`, `rejoined_utc`, `catch_up_secs`, `failed_reports` | Fills null fields, and a caveat says so. |
| `report` | `archived_from`, `modifications` [text] | Used with `--archived-report`. `archived_from` defaults to the archived file's name. |

With `--no-results` the backfill must also carry `fleet` (`label`, `validators`, `observers`,
`machine_type`, `disk` {`type`, `size_gb`}, `regions`) and `chain` (`chain_id`, `network`).
`consensus` and `workload` are published only when the backfill gives every key, else null.

The backfills for the first three published runs are in `backfill/`:
`2026-08-28-devnet.json`, `2026-09-23-sizing.json` and `2026-09-29-hyperdisk.json`.

## What is never committed

`benchmark/results/`, `benchmark/work/`, `benchmark/private/` and `benchmark/genesis/` are
gitignored. Nothing in them is committed, and `make_bundle.py` copies only the allowlist above
out of `results/`. Scratch directories built before 7 October 2026 also hold a `logs/` copy;
nothing reads it, and deleting it (or the whole scratch, which `--force` rebuilds) is safe.

Findings from a run that still need work, and that must not be published, go in
`benchmark/private/followups.md`. Give each run one `## <run>` section with four parts:
findings, harness defects, data gaps and upstream questions. That file is never published and
never read by the pipeline.

### Fixture names that git ignores

Some ignore patterns match a name at any depth, so a test fixture with that name is silently
left out of a commit:

| Name | Ignored by |
|---|---|
| `telcoin-network.yaml`, `*.key`, `.env`, `.env.makefile` (files), `.secrets/`, `__pycache__/` (directories) | the root `.gitignore` |
| `results/`, `work/`, `genesis/`, `private/`, `.secrets/` (directories), `parameters.yaml` | `benchmark/.gitignore` |

`logs`, `archive` and `telcoin` are anchored: the root `.gitignore` ignores only `/logs/`,
`/archive/` and the `/telcoin` binary at the top of the repository, and `benchmark/.gitignore`
ignores only `benchmark/logs/`. A fixture directory called `logs/` or a fixture file called
`telcoin` is tracked, and so is `tasks/archive/`. A node log fixture such as
`bench-validator-01-telcoin.log.gz` is fine anywhere except under a directory called `results/`,
`work/`, `genesis/` or `private/`. Run `git check-ignore -v --no-index <path>` on a new fixture
before you commit.

## Tests

From the repository root:

```
python3 -m unittest discover -s benchmark/tests -v
python3 benchmark/tests/check_mutations.py
```

The report tests (`test_report_kpis.py`, `test_report_windows.py`) run against the synthetic
run in `benchmark/tests/fixtures/report/synthetic-run/`, with hand-computed expectations in
their docstrings. `check_mutations.py` breaks known lines in temporary copies of the source and
checks that the named test fails at its assertion.

## Known limits

- `build-report.py` writes a `Generated HH:MM` footer. Two builds of the same run in different
  minutes give different `report.html` bytes, so `report.sha256` in `run.json` changes too.
  Nothing else differs. The fix belongs in `build-report.py`.
- A bundle covers one blast. The 29 September run published blast 0 (`--blast-index 0`). Its
  blast 1, the lag-pause of validator 03, is not published.
- `--compare R2` reads R2's top-level results unless you pass `--compare-blast-index M`. For
  `r20260929-1647` the top level is blast 1, so a compare against the published blast 0 needs
  `--compare-blast-index 0`. An existing R2 scratch is reused only when its `.source.json`
  names the same blast. One built from another blast, or with no marker, is refused at setup,
  before any work, with a message naming both blasts. `--force` rebuilds it from the blast you
  asked for. Scratch dirs keyed by run id hold one blast at a time, so comparing against two
  blasts of one run in turn rebuilds the scratch each time.
- Node image tags are mutable. A run is pinned to an image digest only from the node image probe
  onwards. An older run that deployed a tag has a null `node_image.digest` unless a backfill
  supplies it.
- The baseline build does not log its vote timeout, so `consensus` is null unless the logs or
  a backfill give `vote_timeout_ms`. The blaster machine type is not recorded either. Without a
  backfill, `fleet.load.machine_type` reads `not recorded`.
