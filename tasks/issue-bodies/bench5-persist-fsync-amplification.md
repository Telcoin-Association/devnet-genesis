## Problem

In bench 5 (run r20261107-1504, build 067639def) the durable persist became the throughput limit. The MDBX commit
(`msync` of the WRITEMAP map) takes 1.03-1.06 s per consensus output on every validator, against 0.30-0.34 s in bench 4
(r20261105-0803, build 496ebefb5). Persist went from about 50 to 199 µs per transaction while execute fell from 165 to
87, so the engine's cost per transaction rose 34 % and the chain ceiling fell from 4,578 to 3,449 tx/s.

The logical writes did not change. Every reth table grows by the same bytes per transaction in both runs, and both runs
touch 0.44 accounts and 0.62 storage slots per transaction. The device bytes did change: about 155 KB per transaction
against 36 KB, written in 227 KB operations against 32 KB. The persist code is byte-for-byte the same in the two
images, and so are reth (v1.11.3) and libmdbx (0.13.7). The extra writes happen below MDBX, in the page cache: when
`mdbx.dat`'s cache holds large folios, every 4 KB page MDBX writes through the map dirties the whole folio and the commit's
`msync` writes it. A probe of the same libmdbx on a 7.0 kernel reproduces this at 1.7-14.5× and writes exactly 1.00× when the
cache holds single-page folios. Bench 3 (r20261103-1922, different code) wrote like bench 5. Bench 4 is the run that
escaped, in the fifth minute of its blast, when its process started re-reading evicted pages. What gave the bench nodes
large folios in the first place was not recorded.

Two premises in the bench-5 F2 verdict (report finding 3) needed correcting:

- The validators do not boot debian-12. They boot `family/ubuntu-2404-lts-amd64` (the default image of the devnet
  deployment scripts; the benchmark configuration does not override it). debian-12 is the bench-obs image. The family resolves at create time. The image and kernel of each run were recovered afterwards
  from the instances' syslog (see "Image and kernel"). No run recorded THP, the `vm.dirty_*` settings, the mount options
  or memory use.
- The bytes cannot all be MDBX page copies (see "Upper bound" below).

## Evidence

Load windows: bench 5 load_pre_kill 17:41:32-17:54:44 UTC (ten validators, 6,006-6,042 tx per output); bench 4 load
09:11:59-09:33:50 UTC (8-12.5 k tx per output). v01 unless noted; the other validators agree within a few per cent.
Sources: the private bench-5 analysis (run r20261107-1504): the F2 verdict §0 and §4, bottleneck notes B1 and B8, the
per-window engine and resource summaries, the image and kernel reads, the persist series replay (cited as series §n), and a
probe of the same libmdbx on a 7.0 kernel (cited as probe F n); the bench-4 bottleneck notes (r20261105-0803), both runs' `metrics.json` (Prometheus replay) and the per-node sampler
CSVs in the recovery tarballs. The bench-5 report summarizes the F2 verdict in finding 3:
https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

**Commit time and bytes.**

| | bench 4 | bench 5 |
|---|---|---|
| MDBX commit per output (`save_blocks_commit_mdbx`, healthy validators) | 0.30-0.34 s | 1.031-1.062 s |
| commit = `transaction_commit_sync` (libmdbx sync phase) | yes | yes, to 0.1 % |
| persist µs/tx (save_blocks + commit) | ≈ 50 (≈ 15 + 28-45) | 199.2 (21.1 + 178.0) |
| telcoin process writes (`/proc/<pid>/io` write_bytes) | 144-180 MB/s | 522-547 MB/s |
| device writes (GCP) v01 | 201 MB/s | 524 MB/s |
| bytes per output | ≈ 315-357 MB | ≈ 931 MB |
| bytes per transaction | ≈ 36 KB (52 → 37 over the blast) | ≈ 155 KB |
| write ops/s, size per op | 5,484-6,825, ≈ 32 KB | 2,301-2,413, ≈ 227 KB |
| PSI io some / CPU | 5.5-7.1 % / 31-35 % | 26.5-27.2 % / 17-19 % |

The commit time is the per-output byte volume at a fixed device rate. Over 5-minute validator buckets of load and post-kill,
the commit takes 1.0 ms per device MB per output: bench 4 slope 1.000 ms/MB (r 0.93, n 68), bench 5 0.963 ms/MB
(r 0.97, n 74), pooled r 0.99 (n 142). It does not follow table growth (r −0.02 bench 4, 0.39 bench 5, −0.61 pooled) or
transactions per output (−0.06, 0.47, −0.55) (series §3). Per-minute device peaks are 876-880 MB/s in all three runs,
against the volume's provisioned 800 MiB/s. Two independent meters agree inside each run, so this is not a measurement
artefact.

**Image and kernel** (the private bench-5 analysis, run r20261107-1504: first syslog line of every instance):

| run | created (UTC) | image | kernel | write mode |
|---|---|---|---|---|
| bench 3 r20261103-1922 | 11-03 19:24 | ubuntu-2404-noble-amd64-v20261024 | 7.0.0-1014-gcp | high (≈ 231 KB ops) |
| bench 4 r20261105-0803 | 11-05 08:05 | ubuntu-2404-noble-amd64-v20261024 | 7.0.0-1014-gcp | low after minute 5 |
| bench 5 r20261107-1504 | 11-07 15:06 | ubuntu-2404-noble-amd64-v20261105 | 7.0.0-1017-gcp | high |

All 11 instances of each run agree. Bench 3 and bench 4 ran the same image and kernel and wrote in opposite modes.

**Same logical writes.** `reth_db_table_size` growth per transaction over the two load windows (bench 4 / bench 5):
TransactionHashNumbers 73.3 / 73.3 B, TransactionSenders 37.6 / 37.6, AccountChangeSets 33.4 / 33.0,
StorageChangeSets 47.0 / 46.5, StoragesHistory 7.4 / 9.8, AccountsHistory 3.8 / 3.7, HashedAccounts 2.9 / 2.9,
HashedStorages 2.6 / 3.6, PlainAccountState 2.4 / 2.3, PlainStorageState 2.5 / 3.7; all tables 218 / 221 B/tx (series
§3). Blocks per transaction are close too (bench-5 KPI analysis: 266 vs 289 tx per block).

**Matched transactions per output** (5-minute validator buckets of load and post-kill, series §2):

| tx per output | bench 3 MB/output (op KB) | bench 4 MB/output (op KB) | bench 5 MB/output (op KB) | bench 3 ÷ 4 | bench 5 ÷ 4 |
|---|---|---|---|---|---|
| 6-8 k | 1,111 (222) | 380 (74) | 1,182 (223) | 2.9 | 3.1 |
| 8-10 k | 899 (231) | 416 (32) | 1,291 (124) | 2.2 | 3.1 |
| 10-12 k | 1,192 (229) | 420 (22) | 1,125 (87) | 2.8 | 2.7 |

Bench 3's transactions per output (load-window median 8.0 k) are bench 4's (10.2 k), not bench 5's (6.7 k), so the gap
is not an output-size effect.

**Upper bound on what MDBX can write.** MDBX copies a page at most once per write transaction; later changes to a page
already dirty in the transaction are made in place. So one commit cannot dirty more pages than the tables it touches
hold. At 17:54:44 on v01 the mutable tables are small: PlainAccountState 13.2 MB, HashedAccounts 16.1, PlainStorageState
42.2, HashedStorages 42.5 (state 114 MB), AccountsHistory 25.4 and StoragesHistory 90.7 (116 MB), AccountsTrie 2.9 and
StoragesTrie 15.3 (the trie tables are in the collector: `reth_db_table_size{table="AccountsTrie"}`). TransactionHashNumbers is 573 MB, but an output inserts 6 k random keys, so at
most ≈ 6 k leaves plus 23 % branch pages. The append-only tables (TransactionSenders, the two changeset tables) add under
1 MB per output. Copying every page of every one of these tables in every commit would write ≈ 278 MB per output (bench 4
at 09:33:50: ≈ 234 MB). Bench 5 wrote 808-1,079 MB per output in its load buckets. At least 66-74 % of the bytes therefore
come from below MDBX's page copies, whatever pages the workload touches. `reth_db_table_size` is the page footprint
(`reth_db_table_pages` × 4096, checked on six tables), so the bound counts pages, not logical bytes (series §3).
Bench 4's process wrote 335-355 MB per output, 1.4-1.5× its own bound, so it was not entirely free of the effect either.

**Where the extra bytes are charged.** Over the whole run, the telcoin process's `write_bytes` matches the device to
0.2-0.4 % in bench 3 (1.002) and bench 5 (1.003-1.004); bench 4's 1.23-1.24 is the log, written outside the process
(series §1). The kernel adds to `write_bytes` when a folio turns dirty, by the whole folio
(`folio_account_dirtied`: `task_io_account_write(nr * PAGE_SIZE)` with `nr = folio_nr_pages(folio)`,
`mm/page-writeback.c`, Linux v7.0). The extra bytes therefore exist at the moment the telcoin process dirties its pages.
The block layer and the device add nothing.

**When the high-byte mode appears and ends.**

- Bench 3 and bench 4 start the same way. v01, minutes after blast start (series §4):

  | minute | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 10 | 14 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | bench 3 KB/tx | 4.0 | 13.0 | 37.0 | 51.7 | 71.0 | 77.9 | 70.5 | 74.7 | 86.5 | 93.9 |
  | bench 3 op KB | 178 | 221 | 230 | 234 | 235 | 230 | 232 | 235 | 235 | 235 |
  | bench 4 KB/tx | 4.1 | 16.3 | 31.3 | 48.7 | 47.9 | 58.3 | 42.4 | 65.3 | 58.3 | 39.9 |
  | bench 4 op KB | 163 | 218 | 229 | 231 | 133 | 77 | 62 | 52 | 37 | 28 |
  | bench 4 re-read MB | 0 | 0 | 0 | 5.4 | 1.8 | 12.9 | 32.8 | 23.1 | 24.3 | 27.9 |
  | bench 4 commit s | 0.03 | 0.11 | 0.23 | 0.33 | 0.35 | 0.37 | 0.39 | 0.31 | 0.38 | 0.34 |

  Both runs were low in the warm-up (pre phase 14.4 and 15.6 KB/tx, series §1): bench 4's low warm-up is bench 3's
  warm-up, not a different mode.
- Bench 4 leaves the mode node by node, in the order its re-reads begin. Re-reads start at 09:11-09:12 on every validator.
  Operations fall below 150 KB at 09:12-09:13 on eight validators, at 09:15 on v07, at 09:18 on the observer and at 09:22
  on v08, not at a common disk fill (15.8-26.7 %). The log rate did not change at the collapse: v01's writes outside the
  process were already ≈ 36 MB/s in minutes 3-4, at 229-231 KB operations (series §4, §6).
- At the same transactions per output inside bench 4 (09:13-09:21, 7.5-7.9 k), the nodes that had not yet collapsed
  wrote more and committed slower (series §6):

  | nodes | MB/output | KB/tx | op KB | commit s/output | re-read MB |
  |---|---|---|---|---|---|
  | eight early-collapse validators | 363-405 | 47-53 | 38-49 | 0.33-0.35 | 160-230 |
  | v08 | 567 | 76.0 | 187 | 0.56 | 30.8 |
  | observer | 542 | 70.7 | 165 | 0.53 | 4.8 |

- Bench 4's commit stayed at 0.31-0.36 s per output while the root volume filled from 20 to 64 % (r −0.08, series §6).
- Bench 5 drops late without re-reads. From 18:01-18:12, 8 of 11 nodes go from ≈ 220 KB to 39-90 KB operations by
  18:21, with at most 5.5 MB re-read per node and no log flood. At 18:14-18:21 (10.8-11.5 k tx per output,
  series §6):

  | nodes | op KB | MB/output | KB/tx | commit s/output |
  |---|---|---|---|---|
  | v04, v06, v10 (did not drop) | 190-216 | 1,516-1,579 | 134.9-137.9 | 1.50-1.55 |
  | v01, v02, v03, v07, v09 | 89-116 | 1,228-1,362 | 110-120 | 1.29-1.38 |
  | v08 | 62 | 1,076 | 93.6 | 1.11 |

- Bench 3 never re-read (v01 `io_read_bytes` max 0.1 MB), kept 215-237 KB operations to its end and climbed from 71-96
  to 102-192 KB/tx. Bench 5 started its main load at 222 KB operations after an hour of light blasts (series §4, §5).
- Logged per node, bench 3 wrote ≈ 1 GB, bench 4 ≈ 49 GB (≈ 1 GB/min through a 16 GB page cache) and bench 5 0.17 GB.

**Ruled-out code paths.** `git diff 496ebefb5 067639def -- crates/engine crates/tn-reth crates/storage`:

- `persist_executed_output` is identical (bench 4 `crates/tn-reth/src/env/execution.rs:326-365`, bench 5 `:431-470`).
  It opens one `provider_rw`, makes one `save_blocks(blocks, SaveBlocksMode::Full)` call with every block of the output,
  writes the finalized and safe markers in the same transaction, and commits once (`:465`). 4ab917aae and the engine commits of
  {{ISSUE:f2-execution-ceiling}} (E1-E5) add timers and metrics only (`markers_ms` 0).
- E5 (420f8aef7) changes reads only. `advance_cached_reads` (`execution.rs:873-898`) updates the in-memory read cache
  from the block's bundle. The bundle that is written is still the block's `db.take_bundle()` (`execution.rs:346-349`),
  and the differential tests pin equal bundles and roots.
- Grouping cannot change the copied-page set. reth `save_blocks` (`crates/storage/provider/src/providers/database/provider.rs:600-688`
  in the reth checkout) writes the output's transaction hashes as one sorted batch, `write_state` per block, the merged
  hashed state and trie updates once per output, and history indices once, all in one MDBX transaction.
- crates/storage: visibility, tests and `ROUNDS_TO_KEEP` moved to tn-types. 746ac3272 raises certificate retention from
  64 to 128 rounds in the consensus DB (a few MB of live data, not MDBX). 0bd522ca7 times the existing pack persist.
- `Cargo.lock`, reth-db 1.11.3 and libmdbx 0.13.7 are unchanged. Neither run passed `--db.sync-mode`.

## Mechanism

How MDBX is opened and committed. reth opens the RW environment with WRITEMAP (`crates/storage/db/src/implementation/mdbx/mod.rs:381-386`),
`no_rdahead` and `coalesce` (`:441-448`), `rp_augment_limit` 256 k (`:477`), the OS page size of 4 KB (`:139`), a 4 GiB
growth step (`:137`) and `SyncMode::Durable` (`:145`). TN calls it through `init_db(db_path, …database_args())`
(`crates/tn-reth/src/env/mod.rs:294`). libmdbx on Linux is built with `MDBX_AVOID_MSYNC=0` (`mdbx.c:1737-1742`), so it
keeps no dirty list and the kernel tracks dirty pages. A durable commit is `msync(MS_SYNC)` over
`[0, first_unallocated)` (`mdbx.c:20770-20776`, `osal_msync` at `:29325`). libmdbx advises the whole map `MADV_NOHUGEPAGE`,
and `MADV_RANDOM` only over the part that was in use when the environment was opened (`dxb_set_readahead`, `:20055-20151`,
called at open with the used size at `:20618` and again only on a geometry change, `:19943`). The 4 GiB file never resized
in these runs, so that range never moved.

What the kernel does with a store through the map (Linux v7.0 source; ext4 has had large folios for regular files since
6.16):

- The first store into a clean folio takes a write fault, and ext4 marks every block of the folio dirty:
  `ext4_page_mkwrite` sets `len = folio_size(folio)`, clamped to the end of file, and calls `block_commit_write(folio, 0, len)`
  (`fs/ext4/inode.c`). `msync` then writes the whole folio. `write(2)` marks only the blocks it writes.
- The kernel charges the dirtying process the whole folio (`folio_account_dirtied`, `mm/page-writeback.c`), which is why
  `write_bytes` equals the device bytes when whole folios are dirtied.

Where large folios come from:

- Not from libmdbx's normal operation. Faults inside the `MADV_RANDOM` range get single-page folios, and libmdbx writes each
  non-resident page it allocates with a 4 KB `pwrite` before touching it (`prefault_write`, on by default for WRITEMAP,
  `mdbx.c:11425-11428`, `:22356-22395`), which also gives a single-page folio. A cold start that refilled the cache this way
  wrote 1.00× (probe F1).
- A buffered read of `mdbx.dat` builds large folios through readahead, up to the readahead window (128 KB on the probe
  machine, `read_ahead_kb` 128).
- Faults past the open-time `MADV_RANDOM` edge go through normal mmap readahead, which raises the folio order over a region
  that is touched in order. Prefault normally gets there first. With prefault off, the probe's small database went from 1.0×
  to 1.8× in five outputs as it grew past the edge (probe F4). On a node whose database grows from genesis, nearly all of it
  lies past the edge, so a page that is evicted and then read again also comes back through this path.
- From the kernel source, not tested: a buffered write of the file, such as a datadir copy or extract, gets folios as large
  as the write (`write_begin_get_folio` passes `fgf_set_order(len)`, `include/linux/pagemap.h`).
- No ext4 mount option or sysfs knob disables large folios. `data=journal` and the per-inode journal-data flag pin the order
  to the minimum, at the cost of journalling every data block (`fs/ext4/super.c` `ext4_set_max_mapping_order`,
  `fs/ext4/inode.c` `ext4_set_inode_mapping_order`).

| # | candidate | verdict | deciding evidence |
|---|---|---|---|
| H1 | whole-folio dirtying: MDBX's 4 KB WRITEMAP stores dirty whole large page-cache folios and `msync` writes them | the cause; reproduced on a 7.0 kernel; what put large folios into the bench nodes' cache is not recorded | probe 1.7-14.5× with large folios, 1.00× without; bytes 2.9-3.9× the copy bound with `write_bytes` equal to the device |
| H3 | bench 4's debug log | not a direct cause; the memory pressure it created fits bench 4's escape but is untested on a resident large-folio cache | appender arm 1.00×; the collapse follows the re-reads, not the log rate |
| H2 | the unpinned image or kernel | refuted for bench 3 vs bench 4; the kernel, filesystem and disk settings still decide how large the folios get | same image and kernel, opposite modes |
| H4 | MDBX copies more pages | refuted | copy bound; equal per-table growth; identical page-op counts across the probe's arms |
| H5 | another writer in the process | ruled out | below |
| H6 | THP | not involved | `thp_file_alloc` 0 in every probe arm; libmdbx already sets `MADV_NOHUGEPAGE` |
| H7 | measurement artefact | ruled out | below |
| H8 | writeback before the commit | secondary, bench 4 only | 9-14 % of bench 4's process bytes left before the commit |

**H1. Whole-folio dirtying under WRITEMAP.** The probe opened libmdbx 0.13.7 exactly as reth does, on a byte-identical 6 GB
database, and ran a bench-5-shaped output (2,640 account and 3,720 slot updates, 6,000 random hash inserts) per durable
commit (probe "Environment"):

| cache state | device ÷ MDBX-dirtied, per-commit median [p10-p90] | total bytes | commit median (p90) |
|---|---|---|---|
| order-0 (libmdbx's own faults and prefaults), any arm | 1.00 [1.00-1.00] | 1.00× | 61.7 ms (76.9) |
| large folios from a buffered read, 6 GB, run r2 | 1.70 [1.05-6.76] | 3.30× | 117.6 ms (365.0) |
| the same, run r3 | 3.76 [1.05-17.71] | 8.10× | 202.8 ms (936.9) |
| the same, 2 GB database | 14.54 [1.04-18.05] | 12.3× | 615.2 ms (739.5) |

In every case the process dirtied exactly what the device received, so the extra bytes are whole folios dirtied by the write
faults, not something added at writeback (probe F2, F8). The factor depends on how scattered the dirtied pages are: 1.05×
while MDBX's free-page reuse hands out contiguous runs, 6.4× and 17.4× once it recycles scattered pages (probe F2). It also
varied between two runs that dirtied byte-identical pages (1.70× against 3.76×), because the folio sizes the read left
behind differed. Bench 5's 4.3× sits inside this band, and its data carry the same signature: bytes 2.9-3.9× a bound that
copies every page, with `write_bytes` equal to the device.

Operation size alone does not show folio size: at order 0 the probe writes 88 KB operations on contiguous runs and 4.4 KB on
scattered pages for the same bytes (probe F5). Bench 5's 227 KB operations support H1 only together with its bytes. They
also imply a larger `max_sectors_kb` on the GCE disk than the probe machine's 128 KB, and possibly a larger readahead window,
so the folios there may be larger than the probe's.

What no run recorded: the folio sizes and MDBX's own dirtied pages on the bench nodes, and what filled their cache with large
folios. The candidates are a buffered read or write of `mdbx.dat` by something other than the node (a copy, an extract, a
checksum, a backup or a sampler) and faults past the `MADV_RANDOM` edge on a database that grew from genesis.

**H3. Bench 4's debug log.** Not a direct cause. `msync` and `fsync` flush only `mdbx.dat`'s own folios, and a 19 MB/s
appender on the same filesystem left the probe's commit at 1.00× and 60.3 ms (probe F7). In bench 4 the collapse came in
minute 5 with the re-reads, after the log had already run at ≈ 36 MB/s for two minutes at 229-231 KB operations; the commit
stayed flat while the disk filled; and bench 5 dropped late with no log at all. The route that fits is memory: about
1 GB/min of log through a 16 GB page cache. Re-reads began at 09:11-09:12 on every validator, and the root volume grew 9-10
GB in 09:08-09:13 while at most 6 GB of log reached the device, which suggests several GB sat dirty in the cache (ext4
counts delayed allocations as used). The two nodes with the least log output, v08 (28 MB/s) and the observer (26 MB/s,
against 33-37 MB/s), collapsed last. The probe shows that pressure refills the cache through 4 KB faults and prefaults at
1.00× (probe F6). It could not show pressure breaking up a cache that already holds large folios: under a 2 GB memory limit
the read-built cache was gone before the first output (probe arm 6b). So this route is consistent with the data but not
demonstrated.

**H2. Image or kernel drift.** Refuted for bench 3 against bench 4: same image, same kernel, opposite modes. Bench 5's newer
kernel (1017) is not needed either: bench 5 matches bench 3 in operation size and KB/tx (series §7). The kernel, the
filesystem and the disk's `read_ahead_kb` and `max_sectors_kb` still decide whether the file gets large folios and how large,
and none of them was recorded. Pin the image and record them.

**H4. MDBX copying more pages.** The upper bound rules it out. The bound could only be wrong three ways and none gives 3×:
pages outside the table footprints (GC and meta pages, a few MB); a page written twice in one commit because the flusher
wrote it mid-transaction (bench 5 wrote 0-4 % of its bytes before the commit, series §3); or a stale footprint (it refreshes
every ≈ 2 min, so 5-minute buckets are fine). The freelist is the same in both runs (bench 4 20 k → 55 k pages, bench 5
21 k → 59 k), and the file never grows past its first 4 GiB step in either. In the probe, MDBX's own page counts were
identical in every arm while the device bytes ranged from 1.00× to 14.5× of them.

**H5. Another writer in the process.** No write path changed between the images:

- Static files grow 0.86 MB/s, `commit_sf` takes 9-38 ms and `save_blocks_sf` 20-30 ms.
- The consensus `epochs` store grows 0.34 MB/s.
- Idle writes are equal in both runs (8.3-8.7 MB/s).
- The time sits inside MDBX's sync phase: `transaction_commit_sync` equals the whole commit.

**H6. THP.** Not involved. `thp_file_alloc` stayed 0 in every probe arm, and libmdbx already advises the map
`MADV_NOHUGEPAGE`. The large folios here are below 2 MB and do not depend on the THP setting.

**H7. Measurement.** Ruled out. GCP device bytes and `/proc/<pid>/io` agree inside each run (bench 5: 524 vs 526 MB/s;
bench 4: 201 vs 164 MB/s, the gap being the log written outside the telcoin process). The same disk spec and sampler code
ran in both. The commit duration tracks bytes at the device rate in both runs.

**H8. Writeback before the commit.** Bench 4 wrote 9-14 % of its process bytes before the commit started; bench 5 0-4 %
(lower bound: device bytes minus commit seconds × 0.88 GB/s, series §3). It hides bytes from the commit rather than removing
them, about a tenth of bench 4's commit.

**Cause: H1.** The commit writes whole large page-cache folios for MDBX's 4 KB WRITEMAP page writes. Bench 4 most likely lost
its large folios to memory pressure. What gave the bench nodes large folios in the first place is the open question.

## Proposal

1. Done: the image and kernel per run ("Image and kernel"), and a probe of the same libmdbx on a 7.0 kernel (above).
2. Fixes, ranked. Ceilings use the 1.0 ms/MB law and the split in the bench-5 report's finding 3 (task 288.6 µs/tx, execute
   87.4, save_blocks 21.1, commit 178). Without the amplification the commit returns to bench 4's ≈ 25-38 µs/tx (about
   6.9 k tx/s), or at worst to the copy bound's ≈ 47-70 µs/tx (5.6-6.4 k). Fixes (a)-(c) deliver that only if they close
   the route the bench nodes actually took, which item 3 measures.

   | rank | fix | expected gain | cost | risk | probe evidence |
   |---|---|---|---|---|---|
   | (a) | Apply `MADV_RANDOM` over the whole map after `init_db`, and again after any geometry change: TN finds the mapping of `mdbx.dat` in `/proc/self/maps`, or libmdbx's `dxb_set_readahead` is patched to cover the map limit | closes the growth and evicted-page refault routes; 5.6-6.9 k tx/s if that was the trigger | 1-2 days | low | whole-map arm 1.00×, no measurable cost; cannot split folios a buffered read already made |
   | (b) | Keep buffered readers and writers off `mdbx.dat` of a running or about-to-start node, and evict it with `posix_fadvise(POSIX_FADV_DONTNEED)` before the node starts (harness and operator rule) | closes the read- and copy-built route; same ceiling if that was the trigger | no code; slower puts while a large existing database warms up | low; does not stop a reader that runs later | cold start 1.00× |
   | (c) | Lower `read_ahead_kb` on the data disk | caps the size of read-built folios, so the factor | a udev rule | low to medium: slower sequential reads of other files on that disk | untested; folios were capped at the 128 KB readahead window on the probe machine |
   | (d) | Open the RW environment without WRITEMAP (reth hardcodes `write_map()`, `mdbx/mod.rs:385`) | immune at the device whatever the cache holds | a reth change and review, weeks | medium: commit latency +83 % on a normal cache (112.9 against 61.7 ms), a different durable path | 1.00× device with 3.76× dirtied |
   | (e) | A memory limit on the node container | removes large folios by refilling the cache with single pages | minutes | high: at 2 GB, 1.3-1.4 s of puts per output, beyond the ≈ 1 output/s cadence; a limit just above the working set is untested. Diagnostic only | memory-limit arms 1.00× |
   | then | Pipelined persist (lever 2 in the bench-5 report, finding 5) | ≈ 5.0 k tx/s at today's commit (×1.42) | weeks | medium | — |
   | then | More provisioned disk throughput (the commit runs at the 800 MiB/s cap) | in proportion, up to the machine type's limit (not checked) | config | cost; hides the bytes | — |

   Do not turn libmdbx's prefault writes off (`MDBX_opt_prefault_write_enable`): prefault is what keeps newly allocated
   pages in single-page folios, and turning it off produced 1.5-1.8×, growing, once the database passed the `MADV_RANDOM`
   edge (probe F4). `--db.sync-mode safe-no-sync` stays out of the bench: the 1.0 ms/MB law already says what the sync costs.
3. Bench-6 records, on every node in every arm:
   - Pre-start: `uname -r`; the boot image; `findmnt -no FSTYPE,OPTIONS` for the datadir;
     `/sys/block/<dev>/queue/{read_ahead_kb,max_sectors_kb}`; THP `enabled` and `defrag`; `vm.dirty_*`; RAM; `fincore` of
     `mdbx.dat` just before the node starts (resident pages then mean something read or wrote it with buffered I/O); every
     harness step that touches the datadir.
   - The decisive measurement, every 5 minutes during load: `mdbx_stat -e` against the live environment (built from the same
     libmdbx 0.13.7; it reads the page-op counters from the lock file, since reth exports none) and the device bytes from
     `/proc/diskstats`. Amplification = Δdevice ÷ (Δ(newly + cow) × 4096): about 1 in bench-4-like and about 4 in
     bench-5-like conditions.
   - Also every 5 minutes: `fincore mdbx.dat`; the `MADV_RANDOM` range of the mapping (`/proc/<pid>/smaps` VmFlags `rr`)
     against the used size; a folio census (`page-types -f` from the kernel's `tools/mm`, or a `/proc/kpageflags` reader;
     v7.0 has no per-order page-cache counters).
   - Every 30 s: `/proc/<pid>/io`; `/proc/vmstat` `nr_dirty`, `nr_writeback`, `workingset_refault_file`, `pgmajfault`,
     `thp_file_alloc`; `/proc/meminfo` `MemAvailable` and `Cached`; the container's `memory.stat` `file` and `file_dirty`.
   - In `persist_executed_output`, optionally, the same page-op counters from `Environment::info()?.page_ops()` before
     `save_blocks` and after the commit, with `/proc/self/io` `write_bytes`, on the `persisted output` line.
4. Bench-6 arms of about 20 minutes each on fresh VMs. The main arm, without any persist change, is the control: with the
   records above it shows whether the GCE nodes amplify and what filled their cache.
   - (b1) the main build plus fix (a), with the harness rule (b): does the amplification fall to about 1 and the commit to
     bench 4's 25-38 µs/tx? Cost: 1-2 days of code and a harness step; low risk.
   - (b2) the main build with `read_ahead_kb` lowered on the data disk (16 KB, say) and no code change: does capping
     read-built folios alone bring the factor down? Cost: a sysfs setting; may slow other reads.
   - (b3) a no-WRITEMAP build, only if (b1) and (b2) leave the factor above about 1.2: does the pwrite path hold 1× on GCE, and
     at what commit latency? Cost: a reth patch; +83 % commit latency on the probe machine.

## Test plan

- Fix (a): a tn-reth test that, after the environment opens, every part of the `mdbx.dat` mapping carries `rr` in
  `/proc/self/smaps`, and again after a forced geometry change. The existing persist and restart e2e tests. A one-VM A/B with
  the probe (or the reth bench: `save_blocks` and `commit` of a 6 k-transaction output on a warmed environment) after a
  buffered read of the file, comparing device bytes per commit and commit latency with and without the fix.
- Rule (b): the pre-start probe fails the node start if `fincore` reports resident pages of `mdbx.dat` after the eviction.
- Records: run the `mdbx_stat -e` sampler against a running node and check that it opens the environment read-only and that
  Δ(newly + cow) moves with the outputs.
- If the persist line gets the page-op fields: a tn-reth unit test that a non-empty output reports non-zero `mdbx_cow` and
  an empty one zero; fmt and clippy.

## What the next benchmark run reads

- Per node, the amplification from `mdbx_stat -e` against the device:
  - About 1 in the main arm: the nodes had no large folios this time. Then `fincore` at start and the harness steps say what
    differed from bench 5.
  - About 3-4 or more: H1 is active on GCE. `fincore` at start, the `rr` range against the used size and the folio census
    say which route filled the cache.
- The kernel, mount options, `read_ahead_kb` and `max_sectors_kb`, the same on every node and in every arm.
- (b1) against the main arm: the amplification and the commit µs/tx. (b2): whether the readahead cap alone moves it. (b3) only
  if run.
- The commit µs/tx (`persisted output` `commit_ms / txs`) against bench 5's 178 and bench 4's 28-45. That number is what
  moves the ceiling.
