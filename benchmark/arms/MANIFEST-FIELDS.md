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
| `mdbx_dat_folios` | {order: int} or null | the folio census of `mdbx.dat`: folios per folio order, keys are the order as a string; null before the node's first start, which is when deploy step 7 probes (the census resolves pages through the node process's page table, and no process maps the file yet) |
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

One entry per blast, written by `benchmark-blast.sh` (`blasts_append`, the only writer): each blast of a light-load sequence, and each `run` started by hand (H13), which is how run 1's sequencer starts every blast.
A hand run's entry has the same `started`, `ended` and `rc` as its `blast_runs[]` entry, and `index`, `senders`, `window`, `chaos` and `kind` from its `BENCH_RUN_INDEX`, `BENCH_SENDERS`, `BENCH_WINDOW`, `BENCH_CHAOS` and `BENCH_BLAST_KIND` (unset: `load`).
A `fund` writes no entry, and neither does the hand-run `run` of a light-load arm (`BENCH_LIGHT_LOAD=1`), whose sequence writes one per blast.
A blast that failed is recorded too, with its `rc`: a reader that measures blasts takes only `rc` 0.
An index can appear twice when a run that never sent is retried under its own index; the later entry is the retry.
Existing fields keep their names: `index`, `senders`, `window`, `chaos`, `started`, `ended`, `rc`.

| field | type | status | meaning |
|---|---|---|---|
| `kind` | `"light"` or `"load"` | new | the path that ran it: an entry of a light-load sequence (`BENCH_LIGHT_*` phases, chaos off) or the configured load profile |
| `arm` | string or null | new | the `param_arms[].name` in force when the blast started (the latest arm whose `begin` is at or before `started`); null when the manifest has no arm |
| `phases` | [{`name`, `start`, `end`}] | new | the blast's phases, real when `phases_planned` is present (below) |
| `phases_planned` | [{`name`, `start`, `end`}] | new | the plan, kept when `phases` was rewritten from the blasters |
| `pool_at_start` | {inst: {`pending`, `queued`}} | new | each node's transaction pool one second before the blast's `start_at`: reth's pending and queued sub-pool sizes (`reth_transaction_pool_pending_pool_transactions`, `reth_transaction_pool_queued_pool_transactions`) from bench-obs Prometheus, since the node serves no `txpool_status`; a node without a sample is null, and every node is null when the query failed. The blast tool records it as `blast.pool_at_start` for every blast and copies it into the entry |

`phases`, `phases_planned` and `pool_at_start` are copied from the live manifest when its `blast.run_index` is the entry's index, that is when the blast got as far as recording itself; a blast that stopped before has none of the three.

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
| `blast.kind`, `blast.senders`, `blast.window` | new (H13) | the blast's type: `BENCH_BLAST_KIND` (`"light"` or `"load"`, unset: `"load"`), senders per blaster and the generator window; after `tail_scan_secs`, so an archived `blast-<i>-<UTC>/manifest.json` alone says what the blast was |
| `blast.warmup_secs`, `blast.duration_secs`, `blast.cooldown_secs` | new (H13) | the planned phase lengths in seconds (`BENCH_WARMUP_SECS`, `BENCH_DURATION_SECS`, `BENCH_COOLDOWN_SECS`; the mixed phase is `duration_secs`) |
| `abort.reason` values `create_failed`, `late_create` | new | a blaster create that failed twice, or one that finished after `start_at` − 30 s |
| `abort.node`, `abort.detail`, `abort.unsent` | new | the blaster, the first `ERROR:` line, and true when no blaster sent |
| `blast_runs[]` | new | blasts run by hand (`fund` and `run`), recorded by the blast tool: `{action, index, started, ended, rc, log}` (below) |
| `node_boot_image` | new | `{"ref": IMAGE, "name": "<image>", "status": "READY", "deprecation_state": null or "<state>"}` from deploy step 0's `images describe` |
| `instances[].source_image` | new | the boot disk's source image as the disks list reports it (deploy step 2) |
| `archive.remote` | new | `{"uri": "<archive prefix of the run>", "verified_at": time, "files": int, "bytes": int}` from the archive verify |

The design named the remote archive record `manifest.archive_remote`.
It is `archive.remote` here because `report/scrub.py` already drops the whole `manifest.archive` object, which names the private bucket, so the record needs no new scrub rule.
The teardown's local gate assigns `.archive = {kind: "local", ...}` as a whole today; it must merge into the object instead, or a teardown re-run after the archive drops `archive.remote`.

## blast_runs[]

One entry per `benchmark-blast.sh fund` or `run` started by hand with `--yes` (not by the deploy, not a child of the light-load sequence), written as it exits.

| field | type | meaning |
|---|---|---|
| `action` | `"fund"` or `"run"` | what was run |
| `index` | int | its `BENCH_RUN_INDEX` (a string when that was not a number) |
| `started`, `ended` | time | when the invocation began and ended |
| `rc` | int | its exit status |
| `log` | string or null | its output copy, relative to `results/<run>/` (`logs/blast-<action>-<UTC>.log`); null without one |

When a later blast archives a run's outputs, its log moves into `blast-<index>-<UTC>/logs/` and the same manifest write sets `log` to that path (H13), so every `log` names a file that exists.
The manifest copy archived beside the moved files keeps the path the log had then.
A `fund` log never moves.

## The sequencer's log

`logs/run-arms-<segment>-<UTC>.log` under `results/<run>/` is not a manifest field: it is the copy `benchmark/launch/run-arms.sh` writes of everything it prints from `ARMS_START` on (H13), `<segment>` being `LAUNCH_SEGMENT` (`arms`) or `hand`.
Its tags are listed in `benchmark/launch/README.md`; one file per invocation, so a resumed walk has two.

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
| `tn_lmdb_dat_size_bytes`, `tn_lmdb_dat_allocated_bytes` | bench 7 (storage v2), appended after the freeze; every row: the size of `db/tn-lmdb.dat` and its allocated bytes (`st_blocks` × 512). On a tn-lmdb node the five `mdbx_dat_*` cells stay empty; on an MDBX node these eight do |
| `static_files_size_bytes`, `static_files_files_total` | bench 7, every row: the summed size and the count of the regular files under `static_files/` (reth's static files; on storage layout v2 the change sets and senders live there, not in the page file) |
| `tn_lmdb_used_bytes` | bench 7, every row: `sum(reth_db_table_size)` + `reth_db_freelist` × `reth_db_page_size` from the node's metrics, the pages reth's tables and the free list hold (the node exports no exact used-size gauge for tn-lmdb) |
| `tn_lmdb_dat_resident_pages`, `tn_lmdb_dat_vma_bytes`, `tn_lmdb_dat_rr_bytes` | bench 7, every 300 s, blank on the other rows: the fincore resident pages of `tn-lmdb.dat`, and the summed `Size` of the node's mappings of it in `/proc/<pid>/smaps` and the part whose `VmFlags` carry `rr`, as for `mdbx.dat` |

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

## Local-SSD deployment

With `BENCH_NODE_DATADIR_LSSD=1`, deploy step 3 puts the data directory of each node with a local SSD (a machine type ending in `-lssd`) on that node's first local NVMe SSD, before keygen writes into it.
The top-level `machine_type` and `node_disk` keep their meaning: the default machine type, and the boot disk the create asks for.
With `BENCH_NODE_MACHINE_TYPES` set, a node's own machine type is its `instances[].machine_type`.
No CSV column is new, and the host probe's frozen keys do not change: on a local-SSD node `datadir_mount_source` is the SSD's namespace and `disk` its name, and the persist CSV's `disk_*` columns count the SSD alone.
On a boot-disk node they still count the whole boot disk (the logs, docker and the OS as well as the databases), so its write counts are an upper bound on the database's own.

### instances[].data_disk

New, written by deploy step 2 (boot-disk nodes) and step 3 (local-SSD nodes), only with `BENCH_NODE_DATADIR_LSSD=1`.
A local-SSD node's object comes from its `LSSD_MOUNT` line (below), through `bench_lssd_mount_record`:

| field | type | meaning |
|---|---|---|
| `class` | `"local-ssd"` | the data directory is on the node's local SSD |
| `by_id` | string | `google-local-nvme-ssd-0`, the only device the mount script uses (`c3-standard-8-lssd` has a second one, `-1`, which nothing touches) |
| `device` | string | the NVMe namespace that id resolves to, a whole disk (for example `/dev/nvme1n1`) |
| `size_bytes` | int | the device's size from `lsblk -b` |
| `uuid` | string | the file system's UUID; the fstab line and the marker hold the same value |
| `fstype` | `"ext4"` | |
| `mount` | string | the data directory, `/var/lib/telcoin` |
| `mount_options` | string | the mount's options as `findmnt` reads them |
| `fstab_root_options` | string | the fstab options of `/`, which the mount uses, so the two disk classes differ in the device only |
| `mkfs` | `"done"`, `"kept"` or `"resumed"` | `done`: formatted by this step 3; `kept`: a file system an earlier step 3 finished, found mounted with the marker's UUID; `resumed`: a file system an earlier step 3 made and mounted but stopped before the marker, finished by this one without a new mkfs |
| `read_ahead_kb` | int | the device's `queue/read_ahead_kb` after the mount |
| `provisioned_iops`, `provisioned_throughput` | null | a local SSD has no provisioned figures |
| `ts` | time | when the deploy recorded the line |

A boot-disk node's object comes from the config: `{"class": "boot", "type": "<NODE_DISK_TYPE>", "size_gb": <int>, "provisioned_iops": <int or null>, "provisioned_throughput": <int or null>}`.

### zone_overrides[]

New, written by deploy step 2, only with `BENCH_NODE_ZONES` set: one entry `{"inst", "from", "to", "reason": "BENCH_NODE_ZONES", "ts"}` per node moved out of its configured zone.
Each also adds a note: `zone override: <inst> runs in <to>, not <from> (BENCH_NODE_ZONES); its latency is that zone's, a comparability caveat`.

### LSSD_MOUNT lines

Step 3 runs `bench_lssd_mount_script` on each local-SSD node in its own session, and the script prints one line:

```
LSSD_MOUNT <inst> dev=<device> by_id=google-local-nvme-ssd-0 size_bytes=<n> uuid=<uuid> mount=<datadir> mkfs=done|kept|resumed options=<mount options> fstab_root_options=<options of /> ra_kb=<read_ahead_kb>
LSSD_MOUNT <inst> failed <reason>
```

The fields of the first form come in this order and no other; `bench_lssd_mount_record` refuses a failed line, a missing line and any other shape.
The script decides by the marker `/var/lib/bench-lssd/uuid` (root, mode 0600, on the boot disk), which it writes last.
With no marker, it formats the device (`mkfs.ext4 -q -F -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard`, the probe driver's options), mounts it with the options of `/`, writes the fstab line `UUID=<uuid> <datadir> ext4 <options of />,nofail,x-systemd.device-timeout=30s 0 2` and the drop-in `/etc/systemd/system/telcoin.service.d/bench-lssd.conf` (`RequiresMountsFor=<datadir>`), and reloads systemd (`mkfs=done`).
A re-run rewrites that fstab line and that drop-in, so it leaves one of each.
It refuses a data directory that is not empty or not owned by root, and a device that is mounted anywhere else; it never unmounts anything and never changes an owner.
A file system that a stopped run made but never mounted is made again: nothing was ever written into it.
With no marker and the data directory already an ext4 mount of the device that holds an empty `lost+found` and nothing else, it skips the mkfs and the mount and finishes the rest (`mkfs=resumed`): that is what a first run leaves when its IAP session drops after the mount.
The same mount with anything more in it fails, since data without a marker is neither formatted again nor adopted, and so does a mount of another device.
With the marker present and the data directory mounted from the device with the marker's UUID, it writes nothing (`mkfs=kept`).
With the marker present and anything else, it prints `failed lost: …`: the VM was stopped or its host failed, and the SSD came back blank.
The script never formats that SSD again; the node's keys and database are gone, and the node is out for the run.

After every node, step 3 prints one line for the fleet:

```
LSSD_MOUNT_SUMMARY nodes=<n> done=<n> kept=<n> resumed=<n> failed=[<inst> ...]
```

### PRECFG_FAIL for the local SSD

Step 7 starts a local-SSD node's pre-start session with `bench_lssd_check_script`.
It prints nothing when `findmnt -no SOURCE --mountpoint <datadir>` is the device `google-local-nvme-ssd-0` resolves to; otherwise it prints

```
PRECFG_FAIL <inst> local SSD not mounted at <datadir>
```

and ends the session, so no `PRECFG_OK` follows and step 7 stops before any node starts.

The readers of the new keys pass them through: `tools/arms-summary.py` uses `data_disk`, `report/make_bundle.py`, `report/provenance.py` and `report/scrub.py` keep unknown keys, the collector ignores `data_disk`, and the teardown and `bench_leftovers` read names and labels only.

## What the report tools must learn

`report/make_bundle.py` refuses no unknown manifest key today: it checks unknown keys only in the backfill and in KPI entries.
`arm_rows` reads `name`, `begin`, `end`, `nodes` and `failed` and ignores every other arm field, and `_node_values` accepts the switch values as written (strings matching its `_PARAM_VALUE_RE`).
So the new keys pass through make_bundle unchanged; what the readers should learn is how to use them:

- `report/windows.py` `light_blasts` (and through it `floor_blast`, which make_bundle uses): select `kind == "light"` and `rc` 0 when `kind` is present.
  `report/kpis.py` `blast_from_dir` (for `--floor-blast-dir`) takes the last entry of the dir's index that ended `rc` 0 (no `rc` counts as 0), and `floor_from_dir`, which `kpis.py` and make_bundle's `prepare_floor` call, turns a dir whose every entry failed into a caveat instead of a floor.
- `report/provenance.py`: add the node's `node switches` startup line to `_CANDIDATE_MARKERS` and compare each start's switches with `param_arms[].switches` of the arm in force at that start (a `via: "prestart"` arm covers the first start).
  `expected_param_values` handles integers and durations only (`_as_int`, `dur_ms`), so the boolean switches need their own comparison.
- `tools/cert-rate.py`, `tools/stage-latency.py`, `tools/block-rate.py` and `tools/propose-latency.py` read an arm window as `begin`/`start` to `end`; they should start it at `ready` when present, and may add `marks[]` as sub-windows.
- `report/make_bundle.py` `consensus_block`: if deploy step 7 records the final arm (`via: "prestart"`), `arm_rows` puts it into the published run's `consensus.param_arms` rows; decide whether a headline run shows it.
- `report/scrub.py`: no new rule as long as the remote archive record stays under `archive`.

## Bench 7: the node build and the storage engine

Added 2026-11-14 for bench 7 (upstream `main` from 45dce8947: storage v2 with tn-lmdb, the faucet guard).
The same rules as above: additive, and a reader treats a missing field as "not recorded".
Other units' scripts read `storage_engine` and must tolerate its absence (a run probed before bench 7).

| name | status | meaning |
|---|---|---|
| `storage_engine` | new (bench 7) | `"tn-lmdb"` or `"mdbx"`, from the node image's own `--version` line `Reth Database: tn-lmdb` or `Reth Database: MDBX` (gate probe, `bench_node_probe_manifest`); `null` when the line is absent. Never read from the store. With `"tn-lmdb"`, deploy step 0 refuses `BENCH_NODE_EVICT_MDBX` (it targets `db/mdbx.dat`); `BENCH_NODE_DB_SYNC_MODE` stays valid (main maps `--db.sync-mode durable\|safe-no-sync` onto tn-lmdb) and `db_sync_mode` is recorded as before |
| `node_probe.build_features` | new (bench 7) | the `--version` line `Build Features: <list>` as printed (`"faucet"` for the bench image); `null` when absent |
| `node_probe.faucet_env` | new (bench 7) | the image's own `TN_ALLOW_FAUCET_ON_CHAIN` value (lower case), read only for a faucet build with the guard while `BENCH_NODE_ALLOW_FAUCET_ON_CHAIN=1`, which then requires a true value; `null` otherwise. Why the image must carry it: see "The faucet opt-in" below |
| `node_startup[inst].node_build` | new (bench 7) | the node's startup line `node build: faucet=<bool> adiri=<bool> chain_id=<n> genesis_hash=<0x..>` (target `cli`) as `{faucet, adiri, chain_id, genesis_hash}`, read by deploy step 9 from the coordinated start (the container's `StartedAt`; the unit file's block after its last `starting` line when the container log rotated); `null` when no parsable line was found. Recorded only when the probed image carries the line (`node_probe.strings["node build: faucet="]` > 0) |
| `node_build` | new (bench 7) | the one `node_startup[].node_build` every node recorded, after step 9; `null` (with a warning) when none did; step 9 stops when two nodes differ |
| `reserved_ports` | new (bench 7) | the node's listener ports deploy step 7 reserved on every node before the staging start (`BENCH_NODE_RESERVE_PORTS=1`), as numbers in the order primary UDP, worker UDP, healthcheck TCP (the root `config.sh`'s `DEFAULT_PRIMARY_UDP_PORT`, `DEFAULT_WORKER_UDP_PORT`, `DEFAULT_HEALTHCHECK_TCP_PORT`); absent at 0 |
| `node_startup[inst].reserve_ports` | new (bench 7) | that node's host step `reserve-ports`, as `bench_host_step_record` gives it: `{step: "reserve-ports", value: "<ports>", result: {ports_reserved_before, ports_reserved_after}}` (how many of the ports `net.ipv4.ip_local_reserved_ports` held before and after; step 7 stops unless after = all of them); absent at 0 |
| `node_startup[inst].ip_local_reserved_ports` | new (bench 7) | the kernel's reserved list as the pre-start config read it (`/proc/sys/net/ipv4/ip_local_reserved_ports`, its `reserved=` field on the PRECFG_OK line), right before the coordinated start; the pre-start config fails the node when a reserved port is missing from it; absent at 0 |

The PRECFG_OK line of the pre-start config gains ` faucet=allowed` when `BENCH_NODE_ALLOW_FAUCET_ON_CHAIN=1` (the bare `--allow-faucet-on-chain` is on the launch line and was read back).
With `BENCH_NODE_RESERVE_PORTS=1` it also gains ` reserved=<the kernel's list>`.
The reservation persists across a reboot of the VM: `/etc/sysctl.d/90-bench-reserved-ports.conf` holds the whole list (the kernel's entries plus the node's ports), and a second run of the step changes nothing.

### The faucet opt-in

The bench image is a `faucet` build, and a faucet build of main refuses every chain but adiri unless the operator opts in (#1716).
A bench node starts twice in deploy step 7, and each start gets the opt-in a different way:

1. The staging start (`devnet-finalize.sh --stage-only`) runs the launch line the v2 finalize writes, before the pre-start config exists, and its `docker run` passes the container none of the harness's variables.
   Only the image's own environment reaches it, so the bench image is the upstream image plus one layer, `ENV TN_ALLOW_FAUCET_ON_CHAIN=true`.
   The gate's image probe refuses a faucet build that has the guard (its binary names `TN_ALLOW_FAUCET_ON_CHAIN`) when the image's `Config.Env` does not set that variable to a true value (`1`, `true`, `yes`, `on`, `t`, `y`, any case), and names the fix; the value it read is `node_probe.faucet_env`.
2. The coordinated start runs the launch line after the pre-start config, which puts the bare `--allow-faucet-on-chain` on it (`tn_launch_flag_set`) and reads it back, so that start does not depend on the image's environment.

`BENCH_NODE_ALLOW_FAUCET_ON_CHAIN=0` turns off both checks and the flag: the pre-start script is then byte-identical to bench 6's.

## Bench 7: a run's switch list

Added 2026-11-14 for bench 7. The switch set of a manifest is that of its node build.
The bench 7 build has seven switches (`switches.tsv`); bench 6's twelve stay in `switches-bench6.tsv` (`README.md`, "Builds").

- `param_arms[].switches` holds every key of the list the arm tool read when the arm was applied: seven keys in a bench 7 run, twelve in a bench 6 run.
  A switch the build lacks is not in the state.
- `report/provenance.py` reads each run with the list of its own build: the list that shares the most keys with the run's `param_arms[].switches` states (or, when no arm recorded one, with its `node switches` lines), the live `switches.tsv` on a tie or when the run recorded none.
  Bench 6 manifests therefore keep reading as before, with no field added to them.

| name | status | meaning |
|---|---|---|
| `node_startup_check.switch_list` | new (bench 7) | the file name of the switch list the check read the run with (`"switches.tsv"` or `"switches-bench6.tsv"`); present whenever `node_startup_check.switches` is and the lists could be read |
| `node_startup_check.switches.extra` | new (bench 7) | `{key: starts}` for each key a `node switches` line carried that the run's list does not have, with the number of starts that carried it; a note, not a problem (the node may have gained a switch); absent when there is none |
