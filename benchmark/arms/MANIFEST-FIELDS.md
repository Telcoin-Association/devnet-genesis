# Manifest fields and file formats for bench 6

These names were frozen on 2026-11-10, before the bench-6 harness work split into parallel units.
Units write and read them exactly as spelled here and never rename them.
Every field that existed before bench 6 keeps its name and meaning; every new field is additive, so a bench-5 manifest still reads.
Times are UTC strings `YYYY-MM-DDTHH:MM:SSZ` (whole seconds) unless a row says otherwise.
"new" marks a bench-6 field; a reader treats a missing new field as "not recorded", never as an error.

## param_arms[]

One entry per application of an arm, appended by `tools/params-apply.sh` (rolling restart) or by deploy step 7 (`BENCH_ARM_FILE`, before the first start).
The list keeps its bench-4 name so `tools/cert-rate.py --windows`, `report/provenance.py` (`expected_param_values`) and `report/make_bundle.py` (`arm_rows`) keep working.

| field | type | status | meaning |
|---|---|---|---|
| `name` | string | existing | the arm's name, `[a-z0-9][a-z0-9-]{0,39}`, unique within the manifest; by default the arm file's `name` line |
| `begin` | time | existing | the first node's restart into this arm (for `via: "prestart"`, the coordinated start) |
| `end` | time or null | existing | null while the arm is open; set to the next arm's `begin` or by `--close-arm` |
| `nodes` | {inst: {key: value}} | existing | per restarted node, the keys the tool wrote into its `parameters.yaml` in this arm, values as strings (`"true"`, `"3"`, `"150ms"`) |
| `no_restart` | true | existing | present when no node needed a change |
| `failed` | instance name | existing | the node that did not come back; the arm stopped there |
| `via` | `"params-apply"` or `"prestart"` | new | who applied the arm; absent means `"params-apply"` |
| `file` | string or null | new | the arm file, repo-relative (`benchmark/arms/p2.arm`); null for an arm given with `--set` only |
| `sha256` | string | new | lower-case hex SHA-256 of the arm file's bytes as applied |
| `switches` | {key: value} | new | the full switch state the arm puts every node in: one entry per row of `switches.tsv`, defaults included, values as strings in the tsv's spelling |
| `host` | [host step] | new | one entry per host step the arm ran, in run order (below) |
| `ready` | time | new | the last node's consensus progress after its restart, plus 120 s; absent until known |
| `restart_secs` | {inst: number} | new | seconds from stop to consensus progress, one decimal |
| `guard` | {inst: {`samples`: int, `refused`: int}} | new | the committee-guard samples taken before that node's restart and how many refused |
| `marks` | [{`label`, `begin`, `end`}] | new | sub-windows set with `--mark <label>` (for example the idle window); `label` follows the arm-name rule |

There is no `started` field on an arm: its start is `begin`, the bench-4 name.

Readers use `switches` for an arm's state and `nodes` only for what was written where: a switch that goes back to its default may be written with its default value or removed from `parameters.yaml`, and both mean the default.
An arm's measurement window is `ready` to `end` when `ready` is present, otherwise `begin` to `end`.

A host step entry is `{"step": "<step>", "value": <string or null>, "nodes": {"<inst>": <result>}}`.
`step` is `read-ahead-kb` (with `value` the KiB as a string, e.g. `"16"`) or `evict-mdbx` (`value` null).
The per-node result is the same object wherever a host step is recorded:

| step | result |
|---|---|
| `evict-mdbx` | `{"resident_pages_before": int, "resident_pages_after": int}` |
| `read-ahead-kb` | `{"read_ahead_kb_before": int, "read_ahead_kb_after": int}` |
| either, on failure | `{"failed": "<reason>"}` (the arm stops at that node, and the entry's `failed` names it) |

Example:

```json
{"name": "p2", "begin": "2026-11-12T03:10:05Z", "end": null, "via": "params-apply",
 "file": "benchmark/arms/p2.arm", "sha256": "<64 hex>",
 "switches": {"quorum_exec_block": "false", "quorum_exec_block_starved_rounds": "0", "vote_queue_fix": "false",
              "mdbx_random_advice": "true",
              "sealed_tx_keep": "false", "digest_dedupe": "false", "recovery_threads": "0",
              "epoch_close_task_drain": "false", "epoch_record_state_check": "false", "parent_grace": "0ms",
              "rpc_admission_backlog_outputs": "0", "pipelined_persist": "false"},
 "nodes": {"bench-observer-11": {"mdbx_random_advice": "true"}},
 "host": [{"step": "read-ahead-kb", "value": "16",
           "nodes": {"bench-observer-11": {"read_ahead_kb_before": 128, "read_ahead_kb_after": 16}}},
          {"step": "evict-mdbx", "value": null,
           "nodes": {"bench-observer-11": {"resident_pages_before": 812345, "resident_pages_after": 0}}}],
 "ready": "2026-11-12T03:19:41Z", "restart_secs": {"bench-observer-11": 41.5},
 "guard": {"bench-observer-11": {"samples": 1, "refused": 0}}, "marks": []}
```

## node_startup[inst]

Existing fields (`log_filter`, `log_max_files`, `logrotate_size`, `params_bak`, `db_sync_mode`, `fsync_probe` and the deploy step 9 readbacks) keep their names.
Records merge into the instance's object (`node_startup_merge`), so adding a key leaves the others in place.

| field | type | status | meaning |
|---|---|---|---|
| `host` | object | new | the pre-start host probe of deploy step 7, taken before the node's first start |
| `host_steps` | [{`step`, `value`, `result`}] | new | the host steps deploy step 7 ran before the first start (from `BENCH_NODE_EVICT_MDBX`, `BENCH_NODE_READ_AHEAD_KB` or `BENCH_ARM_FILE`), with `result` the per-node object of the table above |

`host` holds these fields; any one the probe could not read is null:

| field | type | source |
|---|---|---|
| `kernel` | string | `uname -r` |
| `cmdline` | string | `/proc/cmdline` |
| `os_release` | string | `PRETTY_NAME` from `/etc/os-release` |
| `image_serial` | string | `serial` from `/etc/cloud/build.info` (for example `20261105`) |
| `mem_total_kb` | int | `MemTotal` from `/proc/meminfo` |
| `nproc` | int | `nproc` |
| `datadir` | string | the node's data directory on the host |
| `datadir_mount_source` | string | `findmnt -no SOURCE --target <datadir>` |
| `datadir_fstype` | string | `findmnt -no FSTYPE --target <datadir>` |
| `datadir_mount_options` | string | `findmnt -no OPTIONS --target <datadir>` |
| `disk` | string | the whole disk under the data directory (`lsblk -no PKNAME`) |
| `read_ahead_kb` | int | `/sys/block/<disk>/queue/read_ahead_kb` |
| `max_sectors_kb` | int | `/sys/block/<disk>/queue/max_sectors_kb` |
| `max_hw_sectors_kb` | int | `/sys/block/<disk>/queue/max_hw_sectors_kb` |
| `scheduler` | string | the active entry (the bracketed one) of `/sys/block/<disk>/queue/scheduler` |
| `nr_requests` | int | `/sys/block/<disk>/queue/nr_requests` |
| `thp_enabled` | string | the active entry of `/sys/kernel/mm/transparent_hugepage/enabled` |
| `thp_defrag` | string | the active entry of `/sys/kernel/mm/transparent_hugepage/defrag` |
| `thp_shmem_enabled` | string | the active entry of `/sys/kernel/mm/transparent_hugepage/shmem_enabled` |
| `khugepaged_defrag` | string | `/sys/kernel/mm/transparent_hugepage/khugepaged/defrag` |
| `vm_dirty_ratio` | int | `vm.dirty_ratio` |
| `vm_dirty_background_ratio` | int | `vm.dirty_background_ratio` |
| `vm_dirty_bytes` | int | `vm.dirty_bytes` |
| `vm_dirty_background_bytes` | int | `vm.dirty_background_bytes` |
| `vm_dirty_expire_centisecs` | int | `vm.dirty_expire_centisecs` |
| `vm_dirty_writeback_centisecs` | int | `vm.dirty_writeback_centisecs` |
| `vm_swappiness` | int | `vm.swappiness` |
| `vm_vfs_cache_pressure` | int | `vm.vfs_cache_pressure` |
| `container_memory_limit_bytes` | int | the node container's `--memory` limit (`HostConfig.Memory`); 0 means none |
| `mdbx_dat_size_bytes` | int or null | size of `<datadir>/db/mdbx.dat`; null when the file does not exist yet |
| `mdbx_dat_resident_pages` | int or null | fincore resident pages of `mdbx.dat` |
| `mdbx_dat_folios` | {order: int} or null | the folio census of `mdbx.dat`: folios per folio order, keys are the order as a string |
| `lru_gen_enabled` | string | `/sys/kernel/mm/lru_gen/enabled` (for example `0x0007`); null when the kernel has no multi-generational LRU. With it on, the `active` page flag is mostly unset, which changes how the folio census's `active_folios` reads |

A probe that failed as a whole records `{"probe_failed": true, "reason": "<text>"}` instead, as `fsync_probe` does.

### HOST_PROBE line

The pre-start session prints one line per node:

```
HOST_PROBE <inst> <json>
HOST_PROBE <inst> probe_failed <reason>
```

`<json>` is the `host` object above as compact JSON on one line.
The recorder takes the last line that starts with `HOST_PROBE <inst> `; no line, or one it cannot parse, records `probe_failed` with the reason.

### HOST_PROBE_SUMMARY line

After the pre-start step the deploy prints one line for the fleet:

```
[⚠ ]HOST_PROBE_SUMMARY kernel=<v> image=<serial> ra_kb=<n> uniform=yes|no differ=[<inst> ...] probe_failed=[<inst> ...]
```

Each value is the most common one among the nodes that probed (a tie goes to the first node in fleet order), or `-` when no node probed.
The uniformity fields are `kernel`, `image_serial`, `datadir_fstype`, `datadir_mount_options`, `read_ahead_kb`, `max_sectors_kb`, `scheduler`, `nr_requests`, `thp_enabled`, `thp_defrag`, `thp_shmem_enabled`, `khugepaged_defrag`, the eight `vm_*` fields, `nproc`, `container_memory_limit_bytes` and `lru_gen_enabled`.
`differ` lists, in fleet order, the nodes whose value of any uniformity field is not the most common one.
`uniform=yes` when at least one node probed and `differ` is empty.
The line starts with `⚠ ` when `uniform=no` or `probe_failed` lists a node.
A host difference is a finding for the analysis, so the summary never stops the deploy.

## blasts[]

One entry per blast of a sequence (`benchmark-blast.sh`).
Existing fields keep their names: `index`, `senders`, `window`, `chaos`, `started`, `ended`, `rc`.

| field | type | status | meaning |
|---|---|---|---|
| `kind` | `"light"` or `"load"` | new | the path that ran it: an entry of a light-load sequence (`BENCH_LIGHT_*` phases, chaos off) or the configured load profile |
| `arm` | string or null | new | the `param_arms[].name` in force when the blast started (the latest arm whose `begin` is at or before `started`); null when the manifest has no arm |
| `phases` | [{`name`, `start`, `end`}] | new | the blast's phases, real when `phases_planned` is present (below) |
| `phases_planned` | [{`name`, `start`, `end`}] | new | the plan, kept when `phases` was rewritten from the blasters |

`windows.light_blasts` selects `kind == "light"` with `rc` 0 when `kind` is present, and falls back to the bench-5 rule (chaos off, not the top blast) for entries without it.
An idle window has no blasters and is not a blast: it is a `param_arms[].marks` entry.

## phases and phases_planned

The top-level `phases` keeps its shape: `[{"name": "preamble"|"warmup"|"mixed"|"cooldown", "start": time, "end": time}]` for the latest blast.
Once every blaster's marker is in, the blast tool rewrites `phases` from the blasters' own `run.phases` (the earliest start and the latest end of each phase; start rounded down and end rounded up to the second) and keeps the plan as the top-level `phases_planned` (new).
`phases_planned` is present exactly when `phases` holds real times; without it, `phases` is the plan, as in every bench-5 manifest.
The blaster tail scan is not a phase: `phases` never extends past the cooldown.

## blasters[]

Existing fields keep their names: `name`, `zone`, `machine_type`, `instance_id`, `target`, `node_url`, `sender_start`, `senders`, `result`, `rc`.

| field | type | status | meaning |
|---|---|---|---|
| `created_at` | time | new | when the blaster's create succeeded (recorded at once, before the run) |
| `create_secs` | number | new | seconds the successful create took |
| `attempts` | int | new | create attempts, the successful one included |
| `late_secs` | number | new | the blaster's preamble start (its own `run.phases`) minus the blast's `start_at`, in seconds, one decimal; the tool prints a ⚠ above 5 |

## Other new names

| name | status | meaning |
|---|---|---|
| `blast.tail_scan_secs` | new | the `--tail-scan-secs` the blasters ran with (`BENCH_TAIL_SCAN_SECS`); 0 when off |
| `abort.reason` values `create_failed`, `late_create` | new | a blaster create that failed twice, or one that finished after `start_at` − 30 s |
| `abort.node`, `abort.detail`, `abort.unsent` | new | the blaster, the first `ERROR:` line, and true when no blaster sent |
| `blast_runs[]` | new | blasts run by hand (`fund` and `run`), recorded by the blast tool; its writer documents the entry |
| `node_boot_image` | new | `{"ref": IMAGE, "name": "<image>", "status": "READY", "deprecation_state": null or "<state>"}` from deploy step 0's `images describe` |
| `instances[].source_image` | new | the boot disk's source image as the disks list reports it (deploy step 2) |
| `archive.remote` | new | `{"uri": "<archive prefix of the run>", "verified_at": time, "files": int, "bytes": int}` from the archive verify |

The design named the remote archive record `manifest.archive_remote`.
It is `archive.remote` here because `report/scrub.py` already drops the whole `manifest.archive` object, which names the private bucket, so the record needs no new scrub rule.
The teardown's local gate assigns `.archive = {kind: "local", ...}` as a whole today; it must merge into the object instead, or a teardown re-run after the archive drops `archive.remote`.

## The blaster's run.tail_scan

`run.tail_scan` is part of the blaster document (`blasters/<name>.json`, schema `tn-blast/v2`), not of the manifest.
Its fields are `secs`, `end_reason`, `landed_late`, `by_type` and `unlanded_after`; landings rows gain `late`, and `totals.unlanded_own_at_cooldown_end` stays so the numbers compare with bench 5.
The generator's `bench/schema/README.md` is authoritative for their types.

## Persist files

The persist sampler (`BENCH_PERSIST_SAMPLER=1`) writes two files per node, and collect copies them to `results/<run>/persist/`.
They live outside `sampler/` on purpose: `report/kpis.py` and `report/make_bundle.py` glob `sampler/*.csv`, so a persist CSV there would read as another node.
Both files are CSV with a header line; every value is numeric, and an empty field means unavailable.

### persist/&lt;inst&gt;.csv

Header: `benchmark/tools/persist-csv-header.txt` (one line), one row every 30 s.
Counters (`_total`) are cumulative as the kernel reports them; `pid` changes at every node restart, and the counters of `proc_*` restart with it.

| columns | source |
|---|---|
| `ts_unix`, `pid` | the sample time; the in-container `telcoin node` process as the host sees it |
| `disk_*` | `/proc/diskstats` for the data disk: read and write I/Os, bytes (sectors × 512) and ticks, flush I/Os and ticks, I/Os in flight, I/O ticks |
| `vm_*` | `/proc/vmstat`: `nr_dirty`, `nr_writeback`, `nr_dirtied`, `nr_written`, `workingset_refault_file`, `pgmajfault`, `thp_file_alloc`, `thp_file_fallback` |
| `mem_*` | `/proc/meminfo`: `MemAvailable`, `Cached`, `Dirty`, `Writeback` (kB) |
| `memcg_*` | the node container's cgroup: `memory.current`, and `file`, `file_dirty`, `file_writeback`, `workingset_refault_file` from `memory.stat` |
| `proc_*` | `/proc/<pid>/io`: `rchar`, `wchar`, `syscr`, `syscw`, `read_bytes`, `write_bytes`, `cancelled_write_bytes` |
| `mdbx_dat_size_bytes`, `mdbx_dat_resident_pages` | every 300 s, blank on the other rows: the size of `mdbx.dat` and its fincore resident pages |
| `mdbx_dat_vma_bytes`, `mdbx_dat_rr_bytes` | every 300 s, blank on the other rows: the summed `Size` of the node's `mdbx.dat` mappings in `/proc/<pid>/smaps`, and the part whose `VmFlags` carry `rr` |
| `mdbx_dat_resident_past_used_pages` | every 300 s, blank on the other rows and whenever the used size cannot be read: resident pages of `mdbx.dat` past the database's used size, which the sampler reads from the node's `tn_reth_mdbx_used_bytes` gauge (last column, added after the first freeze) |

No MDBX reader runs beside the node: page operations come from the node's own `persisted output` line and metrics, not from `mdbx_stat`.

### persist/&lt;inst&gt;.folios.txt

Header: `benchmark/tools/folio-census-header.txt` (one line).
Every 900 s the folio census writes one row per folio order it found in `mdbx.dat`; a census that finds no resident page writes one row with the order columns empty, so every census leaves at least one row.
The census never faults a page in.
The name ends in `.txt` so that `persist/*.csv` matches only the 30-s files.

| column | meaning |
|---|---|
| `ts_unix` | when the census started; shared by every row of one census |
| `census_secs` | how long the census took |
| `mdbx_dat_size_bytes`, `mdbx_dat_resident_pages` | the file's size and resident pages at the census |
| `unresolved_pages` | resident pages whose page flags could not be read |
| `folio_order` | the folio order of this row (0 = a single 4 KiB page) |
| `folios` | resident folios of that order |
| `dirty_folios`, `writeback_folios`, `active_folios` | the ones of them flagged dirty, under writeback, or on the active LRU |

## What the report tools must learn

`report/make_bundle.py` refuses no unknown manifest key today: it checks unknown keys only in the backfill and in KPI entries.
`arm_rows` reads `name`, `begin`, `end`, `nodes` and `failed` and ignores every other arm field, and `_node_values` accepts the switch values as written (strings matching its `_PARAM_VALUE_RE`).
So the new keys pass through make_bundle unchanged; what the readers should learn is how to use them:

- `report/windows.py` `light_blasts` (and through it `floor_blast`, which make_bundle uses): select `kind == "light"` and `rc` 0 when `kind` is present.
  `report/kpis.py` `blast_from_dir` reads `blasts[]` by index and needs no change.
- `report/provenance.py`: add the node's `node switches` startup line to `_CANDIDATE_MARKERS` and compare each start's switches with `param_arms[].switches` of the arm in force at that start (a `via: "prestart"` arm covers the first start).
  `expected_param_values` handles integers and durations only (`_as_int`, `dur_ms`), so the boolean switches need their own comparison.
- `tools/cert-rate.py`, `tools/stage-latency.py`, `tools/block-rate.py` and `tools/propose-latency.py` read an arm window as `begin`/`start` to `end`; they should start it at `ready` when present, and may add `marks[]` as sub-windows.
- `report/make_bundle.py` `consensus_block`: if deploy step 7 records the final arm (`via: "prestart"`), `arm_rows` puts it into the published run's `consensus.param_arms` rows; decide whether a headline run shows it.
- `report/scrub.py`: no new rule as long as the remote archive record stays under `archive`.
