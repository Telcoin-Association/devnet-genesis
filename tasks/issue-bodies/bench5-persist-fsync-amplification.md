## Problem

In bench 5 (run r20261107-1504, build 067639def) the durable persist became the throughput limit. The MDBX commit
(`msync` of the WRITEMAP map) takes 1.03-1.06 s per consensus output on every validator, against 0.30-0.34 s in bench 4
(r20261105-0803, build 496ebefb5). Persist went from about 50 to 199 µs per transaction while execute fell from 165 to
87, so the engine's cost per transaction rose 34 % and the chain ceiling fell from 4,578 to 3,449 tx/s.

The logical writes did not change. Every reth table grows by the same bytes per transaction in both runs, and both runs
touch 0.44 accounts and 0.62 storage slots per transaction. The device bytes did change: about 155 KB per transaction
against 36 KB, written in 227 KB operations against 32 KB. The persist code is byte-for-byte the same in the two
images, and so are reth (v1.11.3) and libmdbx (0.13.7). Something under MDBX turns the same page updates into three to
four times the device writes. Bench 3 (r20261103-1922, different code) wrote like bench 5. Bench 4 is the run that
escaped, and it escaped in the fifth minute of its blast, when its process started re-reading evicted pages.

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
per-window engine and resource summaries, the image and kernel reads, and the persist series replay (cited as series §n);
the bench-4 bottleneck notes (r20261105-0803), both runs' `metrics.json` (Prometheus replay) and the per-node sampler
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

## Mechanism: ranked verdict

How MDBX is opened and committed. reth opens the RW environment with WRITEMAP (`crates/storage/db/src/implementation/mdbx/mod.rs:381-386`),
`no_rdahead` and `coalesce` (`:441-448`), `rp_augment_limit` 256 k (`:477`), the OS page size of 4 KB (`:139`), a 4 GiB
growth step (`:137`) and `SyncMode::Durable` (`:145`). TN calls it through `init_db(db_path, …database_args())`
(`crates/tn-reth/src/env/mod.rs:294`). libmdbx on Linux is built with `MDBX_AVOID_MSYNC=0` (`mdbx.c:1737-1742`), so it
keeps no dirty list and the kernel tracks dirty pages. A durable commit is `msync(MS_SYNC)` over
`[0, first_unallocated)` (`mdbx.c:20770-20776`, `osal_msync` at `:29325`). Spilling in WRITEMAP mode is
`msync(MS_ASYNC)`, which does nothing on Linux (`:33209`). The device writes whatever the kernel holds dirty for
`mdbx.dat` at that moment, in whatever unit the page cache dirties.

What the kernel does with it (Linux v7.0 source; ext4 has had large folios for regular files since 6.16):

- An mmap write fault on ext4 marks the whole folio dirty. `ext4_page_mkwrite` sets `len = folio_size(folio)`, clamped to
  the end of file, and calls `block_commit_write(folio, 0, len)` (`fs/ext4/inode.c`). Writeback writes every dirty block,
  so the whole folio reaches the device. `write(2)` marks only the blocks it writes.
- Faults allocate single-page folios. `filemap_fault` creates the folio with `FGP_CREAT|FGP_FOR_MMAP` and no order, mmap
  read-around starts at `ra->order = 0`, and only async readahead raises the order (`mm/filemap.c`, `mm/readahead.c`).
  Only `VM_HUGEPAGE` forces 2 MB folios on a fault, and libmdbx never sets it.
- Buffered writes get folios as large as the write: `write_begin_get_folio` passes `fgf_set_order(len)`
  (`include/linux/pagemap.h`). The ext4 cap with 4 KB blocks is order 9, 2 MiB (`EXT4_MAX_PAGECACHE_ORDER`).
- Large page-cache allocations are opportunistic. Above order 0 they use `__GFP_NORETRY | __GFP_NOWARN` and fall back one
  order at a time when memory is short (`__filemap_get_folio_mpol`, `mm/filemap.c`).
- No mount option or sysfs knob turns large folios off for ext4. `data=journal` and the per-inode journal-data flag pin the
  order to the minimum, at the cost of journalling every data block (`fs/ext4/super.c` `ext4_set_max_mapping_order`,
  `fs/ext4/inode.c` `ext4_set_inode_mapping_order`).

| # | candidate | verdict | deciding evidence |
|---|---|---|---|
| H1 | whole-folio writeback: MDBX's 4 KB WRITEMAP stores dirty large page-cache folios and `msync` writes them whole; memory pressure breaks the large folios up | most likely (probe pending) | bytes 2.9-3.9× the copy bound; `write_bytes` equals the device; bench 3 and 4 identical until bench 4's re-reads; the matched contrasts inside bench 4 and bench 5 |
| H3 | bench 4's debug log | the pressure that switched H1 off in bench 4; refuted as a direct cause | the collapse follows the re-reads, not the log rate; bench 5 dropped late with no log |
| H2 | the unpinned image or kernel | refuted for bench 3 vs bench 4 | same image and kernel, opposite modes |
| H4 | MDBX copies more pages | refuted as the cause | copy bound; equal per-table growth; same code |
| H5 | another writer in the process | ruled out | below |
| H6 | THP | not expected (probe pending) | only `VM_HUGEPAGE` changes the fault order |
| H7 | measurement artefact | ruled out | below |
| H8 | writeback before the commit | secondary, bench 4 only | 9-14 % of bench 4's process bytes left before the commit |

**H1. Whole-folio writeback, switched off by memory pressure.** If `mdbx.dat`'s page cache holds multi-page folios, each
4 KB page MDBX copies into one costs the folio in device writes.

Where the large folios come from. On v7.0 the fault paths cannot make them (above). The buffered writes to `mdbx.dat` are
libmdbx's prefault writes. `prefault_write` is on by default for WRITEMAP (`mdbx.c:11425-11428`) and stays on because reth
turns readahead off (`mdbx.c:22486-22500`). When an allocation's pages are not resident, libmdbx writes a pattern through
the file handle before touching them: `pwrite` for a single page, `pwritev` over the whole run for a multi-page allocation
(`mdbx.c:22356-22395`). A multi-page run, such as a large value or the commit's GC record, therefore lands in one or more
large folios. Once the run is freed, its pages return to the free pool and are reused as ordinary 4 KB B-tree pages, still
inside those folios. Every later copy into such a page writes the whole folio. Read faults outside libmdbx's open-time
`MADV_RANDOM` range (`dxb_set_readahead`, `:20055-20066`, called at open with the open-time used size at `:20618`) start
at order 0 on v7.0, so that path only matters for async readahead on sequential runs. The creation path is read from the code; no run recorded folio sizes (probe pending).

What switches it off. Nothing on a quiet node splits a page-cache folio, so without pressure the large-folio share only
grows. Pressure breaks it two ways:

- Eviction. A page MDBX reuses after its folio was evicted is non-resident, so libmdbx prefaults it with a one-page
  `pwrite`: an order-0 folio, no read. A page MDBX reads after eviction comes back through the fault path at order 0;
  that is the re-read bench 4 shows.
- Allocation fallback. With free memory at the watermarks, the opportunistic large allocations for new prefault runs fail
  and fall back to small orders without any read. This is the only route in hand for bench 5's late drop.

What H1 explains: bytes above the copy bound; fewer, larger device operations; `write_bytes` agreeing with the device;
fleet uniformity; no code change; bench 3's climb and bench 5's high start (no pressure); bench 4's exit in the minute its
re-reads began, node by node; the matched contrasts in which the nodes still at large operations wrote 1.3-1.6× the bytes
(bench 4) or about 1.2× (bench 5) and committed slower. Not shown yet: folio sizes and memory state, which no run recorded,
and why bench 4's process bytes are 1.4-1.5× its own bound in the low state (some large folios survived, operations 17-74 KB
rather than 4-8 KB, or the bound misses about 100 MB per output).

**H3. Bench 4's debug log, as the pressure.** The log cannot shrink MDBX's bytes directly. `msync` and `fsync` flush only
`mdbx.dat`'s own dirty folios; an ext4 `data=ordered` journal commit forced by MDBX's sync could only make bench 4's sync
slower; and the timing does not fit a direct effect. The log ran at ≈ 36 MB/s in minutes 3-4 at 229-231 KB operations, the
collapse came in minute 5 with the re-reads, the commit stayed flat while the disk filled, and bench 5 dropped late with no
log at all. Its route is memory: about 1 GB/min of log through a 16 GB page cache. Re-reads began at 09:11-09:12 on every
validator. The root volume grew 9-10 GB in 09:08-09:13 while at most 6 GB of log reached the device, which suggests
several GB sat dirty in the cache then (ext4 counts delayed allocations as used; memory was not recorded, so this is an
inference). The two nodes with the least log output, v08 (28 MB/s) and the observer (26 MB/s, against 33-37 MB/s),
collapsed last.

**H2. Image or kernel drift.** Refuted for bench 3 against bench 4: same image, same kernel, opposite modes. Bench 5's
newer kernel (1017) is not needed either: bench 5 matches bench 3 in operation size (222-231 KB) and in KB/tx at 6-12 k
tx per output (108-164 against 102-144, series §7). A kernel of 6.16 or later is a precondition of H1, and all three
runs met it. Pin the image anyway, so that the kernel cannot change between runs unrecorded.

**H4. MDBX copying more pages.** The upper bound rules it out as the cause. The bound could only be wrong three ways and
none gives 3×: pages outside the table footprints (GC and meta pages, a few MB); a page written twice in one commit
because the flusher wrote it mid-transaction (bench 5 wrote 0-4 % of its bytes before the commit, series §3); or a
stale footprint (it refreshes every ≈ 2 min, so 5-minute buckets are fine). Senders 400000+ (bench 5) and 0-5999
(bench 4) are random addresses and random hashed keys in both runs. Six thousand against 8-12.5 k transactions per output
changes how far branch-page copies are amortized by tens of per cent, not three times. The freelist is the same in both
runs (bench 4 20 k → 55 k pages, bench 5 21 k → 59 k), and the file never grows past its first 4 GiB step in either.

**H5. Another writer in the process.** No write path changed between the images:

- Static files grow 0.86 MB/s, `commit_sf` takes 9-38 ms and `save_blocks_sf` 20-30 ms.
- The consensus `epochs` store grows 0.34 MB/s.
- Idle writes are equal in both runs (8.3-8.7 MB/s).
- The time sits inside MDBX's sync phase: `transaction_commit_sync` equals the whole commit.

**H6. THP.** libmdbx never issues `MADV_HUGEPAGE` (none in `mdbx.c`). On v7.0 the 2 MB path for a file fault needs
`VM_HUGEPAGE`; THP `enabled=always` does not change file faults (`do_sync_mmap_readahead`, `mm/filemap.c`). Record the
setting; `MADV_NOHUGEPAGE` should change nothing (probe pending).

**H7. Measurement.** Ruled out. GCP device bytes and `/proc/<pid>/io` agree inside each run (bench 5: 524 vs 526 MB/s;
bench 4: 201 vs 164 MB/s, the gap being the log written outside the telcoin process). The same disk spec and sampler code
ran in both. The commit duration tracks bytes at the device rate in both runs.

**H8. Writeback before the commit.** Bench 4 wrote 9-14 % of its process bytes before the commit started; bench 5 0-4 %
(lower bound: device bytes minus commit seconds × 0.88 GB/s, series §3). It is most likely background writeback pushed by
the log's dirty pages. It hides bytes from the commit rather than removing them, about a tenth of bench 4's commit.

**Most likely cause: H1.** The kernel writes back whole multi-page folios for MDBX's 4 KB WRITEMAP page copies, and memory
pressure is what took bench 4 out of it.

## Proposal

1. Done: the desk check. Bench 3 and bench 4 booted the same image and kernel ("Image and kernel"). Pin the image for
   bench 6 and record it.
2. The libmdbx probe on a 7.0 kernel (one machine, no chain; probe pending). Open an MDBX environment the way reth does
   (WRITEMAP, durable, 4 KB pages, `no_rdahead`), run a random-update workload with commits of a few hundred MB, and
   compare device bytes and write sizes (`/proc/diskstats`) with the pages MDBX copied. Arms and what each outcome means:

   | arm | H1 predicts | otherwise |
   |---|---|---|
   | baseline | device ÷ copied ≈ 3-4×, operations ≥ 150 KB | ≈ 1× with small operations, once the prefault counter shows multi-page runs ran: H1 is dead and the copy bound must be wrong |
   | cgroup `MemoryMax` well below the map size | ≈ 1×, small operations, re-reads | still 3-4×: pressure is not the switch |
   | a sequential appender filling the cache | falls to ≈ 1× once the cache is full, not before | a drop before the cache fills: a direct I/O effect of the log (H3) |
   | no WRITEMAP | device ≈ 1× even with large folios; `write_bytes` may exceed the device | device 3-4×: dropping WRITEMAP is not a fix |
   | prefault writes off | ≈ 1× from a cold cache | still high: the folios come from readahead; try `MADV_RANDOM` |
   | `MADV_RANDOM` on the whole map | no change if prefault makes the folios | a drop: readahead makes them |
   | `MADV_NOHUGEPAGE` | no change | a drop: THP policy matters (H6) |

3. Fixes, ranked. Ceilings use the 1.0 ms/MB law and the split in the bench-5 report's finding 3 (task 288.6 µs/tx, execute 87.4, save_blocks
   21.1). Bench 4's commit (≈ 25-38 µs/tx) gives about 6.9 k tx/s; bytes at the copy bound (≈ 47-70 µs/tx) about
   5.6-6.4 k.

   | rank | change | ceiling | time to land | risk |
   |---|---|---|---|---|
   | 1 | Turn prefault writes off: after `init_db`, `mdbx_env_set_option(env, MDBX_opt_prefault_write_enable, 0)` through reth-libmdbx `Environment::with_raw_env_ptr` (public, `environment.rs:145`; `DatabaseEnv` derefs to `Environment`, `mdbx/mod.rs:633`). TN only, no reth fork (probe pending) | 5.6-6.9 k tx/s | about a day plus the persist and restart e2e tests | low: a documented runtime option; a reused page that is not resident costs one 4 KB read, about zero without pressure |
   | 2 | Also apply `MADV_RANDOM` to the whole map. libmdbx covers only the open-time used size and has no API for the map address, so either find the mapping in `/proc/self/maps` or patch `dxb_set_readahead` to cover the map limit | adds only if readahead makes folios (probe pending) | 1-2 days | low to medium |
   | 3 | Open the RW environment without WRITEMAP. reth hardcodes `write_map()` (`mdbx/mod.rs:385`) | 5.6-6.9 k tx/s whatever the folio size, if the no-WRITEMAP arm escapes (probe pending) | a reth change and review, weeks | medium: a different durable path, shadow pages cost RAM and copies |
   | 4 | Bound the node container's memory (`docker run --memory` or `memory.high`), as bench 4 did by accident | up to bench 4's level, but only once the cache reaches the bound | minutes | high outside a bench: OOM kill at `memory.max`, throttling at `memory.high`, re-reads; resets with the cache. Diagnostic only |
   | 5 | Pipelined persist (lever 2 in the bench-5 report, finding 5) | ≈ 5.0 k tx/s at today's commit (×1.42) | weeks | medium |
   | 6 | More provisioned disk throughput (the commit runs at the 800 MiB/s cap) | in proportion, up to the machine type's limit (not checked) | config | cost; hides the bytes |

   `--db.sync-mode safe-no-sync` is dropped from bench 6: the 1.0 ms/MB law already says what the sync costs. No kernel or
   mount knob is usable (see Mechanism); a kernel older than 6.16 or `data=journal` would be test arms, not fixes.
4. Bench-6 observability (small, off the hot path):
   - In `persist_executed_output`, read `Environment::info()?.page_ops()` before `save_blocks` and after `commit`
     (reth-libmdbx `environment.rs:410-425`: `newly`, `cow`, `split`, `merge`, `prefault`, `mincore`, `msync`;
     `MDBX_ENABLE_PGOP_STAT=1` is compiled in, `mdbx.c:1680`). Read `/proc/self/io` `write_bytes` at the same two points,
     and add `mdbx_newly`, `mdbx_cow`, `mdbx_prefault` and `proc_write_bytes` to the `persisted output` line.
   - Pre-start probe: `uname -r`; the boot image from instance metadata; `/sys/kernel/mm/transparent_hugepage/{enabled,defrag}`;
     `vm.dirty_ratio`, `dirty_background_ratio`, `dirty_expire_centisecs` and `dirty_writeback_centisecs`;
     `findmnt -no FSTYPE,OPTIONS` for the datadir; `/sys/block/<dev>/queue/{max_sectors_kb,read_ahead_kb,scheduler}`.
   - Sampler, every 30 s: `/proc/diskstats` write ios and sectors (gives `wareq-sz`); `/proc/vmstat` `nr_dirty`,
     `nr_writeback`, `nr_file_pages`, `workingset_refault_file`, `pgsteal_file`, `nr_file_hugepages`, `thp_file_alloc`;
     `/proc/meminfo` `MemAvailable`, `Cached`, `Dirty`; the container's cgroup `memory.stat` (`file`, `file_dirty`,
     `file_writeback`, `anon`) and `memory.events`.
   - Every 5 minutes, the folio census of `mdbx.dat`: `page-types -f` (the kernel's `tools/mm`) or a small `/proc/kpageflags`
     reader that counts pages by folio order. The THP counters in `/proc/vmstat` count only 2 MB folios and v7.0 has no
     per-order counter for page-cache folios, so the census is the only direct measurement.
5. Bench-6 arms of about 20 minutes each on fresh VMs, after the main load:
   - (b1) the bench-6 build as is, image pinned: does bytes per output follow the large-folio share of `mdbx.dat`, and does
     the share fall when `MemAvailable` reaches the floor?
   - (b2) (b1) plus the fix the probe selects (prefault writes off, and `MADV_RANDOM` on the whole map if that arm moved):
     does the commit fall to bench 4's 25-38 µs/tx with a small-folio census and no re-reads?
   - (b3) (b1) with the node container's memory bounded (the value from the probe; record `memory.events`): does pressure
     alone reproduce bench 4 on today's build?

## Test plan

- Item 2 is the test for H1. Record it with the bench-6 analysis, with the machine, the kernel, the mount options, the probe
  program and its arms, the `/proc/diskstats` deltas and the page-op counts per arm.
- Item 4 code: a tn-reth unit test that a persisted non-empty output reports non-zero `mdbx_cow` and `proc_write_bytes`
  and that an empty output reports zero `mdbx_cow`; extend `test_metrics_register_and_update` if the fields become
  metrics. fmt and clippy.
- Item 3 code, whichever lever is taken: the existing persist and restart e2e tests, plus a one-VM A/B of the reth bench
  (`save_blocks` and `commit` of a 6 k-transaction output on a warmed 4 GiB environment) comparing device bytes per commit,
  commit latency and the folio census.

## What the next benchmark run reads

- Per output, `amplification = proc_write_bytes / ((Δnewly + Δcow) × 4096)`.
  - About 1 means MDBX's own copies are the bytes. H4 is back, and the per-table page counts say which table.
  - About 3-4 (bench 5) means H1. The folio census should show the large-folio share behind it.
- The probe fields: the same kernel and image on every node and in every arm.
- Bytes per transaction and its 5-minute trajectory against the folio census, `MemAvailable`, `workingset_refault_file`
  and `io_read_bytes`. Under H1 it climbs while nothing is evicted and falls when free memory runs out, with or without
  re-reads.
- Arm outcomes:
  - (b1) bytes per output tracking the large-folio share confirms H1 on the fleet.
  - (b2) a commit near 25-38 µs/tx is the fix; still near 178 means the probe's lever does not carry to the fleet.
  - (b3) falling bytes once the container reaches its bound confirms the pressure switch.
- The commit µs/tx (`persisted output` `commit_ms / txs`) against bench 5's 178 and bench 4's 28-45. That number is what
  moves the ceiling.
