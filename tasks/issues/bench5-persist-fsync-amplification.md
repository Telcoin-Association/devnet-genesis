# The MDBX commit writes about 4× the device bytes per transaction that bench 4 wrote, below the engine

## Problem

In bench 5 (run r20261107-1504, build 067639def) the durable persist became the throughput limit. The MDBX commit
(`msync` of the WRITEMAP map) takes 1.03-1.06 s per consensus output on every validator, against 0.30-0.34 s in bench 4
(r20261105-0803, build 496ebefb5). Persist went from about 50 to 199 µs per transaction while execute fell from 165 to
87, so the engine's cost per transaction rose 34 % and the chain ceiling fell from 4,578 to 3,449 tx/s.

The logical writes did not change. Every reth table grows by the same bytes per transaction in both runs, and both runs
touch 0.44 accounts and 0.62 storage slots per transaction. The device bytes did change: about 155 KB per transaction
against 36 KB, written in 227 KB operations against 32 KB. The persist code is byte-for-byte the same in the two
images, and so are reth (v1.11.3) and libmdbx (0.13.7). Something under MDBX turns the same page updates into about four
times the device writes, and bench 4 is the run that escaped it: bench 3 (r20261103-1922, different code) shows bench 5's
signature.

Two premises in the A4n verdict need correcting before anyone tests this:

- The validators do not boot debian-12. They boot `family/ubuntu-2404-lts-amd64` (devnet `config.sh:118`, passed as
  `image=` by `common/create-instances.sh:180`; `benchmark/config.sh` does not override it). debian-12 is the bench-obs
  image (`config.sh:281`). The family resolves at create time, so each run booted whatever Ubuntu image and kernel was
  current that day. None of the three runs recorded the image, the kernel, THP, the `vm.dirty_*` settings or the mount
  options.
- The bytes cannot all be MDBX page copies (see "Upper bound" below). The verdict's "MDBX dirtying about 4× more pages"
  candidate does not fit the table sizes.

## Evidence

Load windows: bench 5 load_pre_kill 17:41:32-17:54:44 UTC (ten validators, 6,006-6,042 tx per output); bench 4 load
09:11:59-09:33:50 UTC (8-12.5 k tx per output). v01 unless noted; the other validators agree within a few per cent.
Sources: `benchmark/private/bench5-r20261107-1504/A4n/` (f2-verdict.md §0 and §4, bottlenecks.md B1/B8, f2.json,
resources.json), `benchmark/private/bench4-r20261105-0803/A4n/bottlenecks.md`, both runs' `metrics.json` (Prometheus
replay) and the per-node sampler CSVs in the recovery tarballs.

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

The commit time is the per-output byte volume divided by a nearly constant device rate in both runs (≈ 0.9-1.0 GB/s;
per-minute peaks 868-880 MB/s against the volume's provisioned 800 MiB/s). Two independent meters agree inside each run,
so this is not a measurement artefact.

**Same logical writes.** `reth_db_table_size` growth per transaction over the two load windows (bench 4 / bench 5):
TransactionHashNumbers 73.3 / 73.3 B, TransactionSenders 37.6 / 37.6, AccountChangeSets 33.4 / 33.0,
StorageChangeSets 47.0 / 46.5, StoragesHistory 7.4 / 9.8, AccountsHistory 3.8 / 3.7, HashedAccounts 2.9 / 2.9,
HashedStorages 2.6 / 3.6, PlainAccountState 2.4 / 2.3, PlainStorageState 2.5 / 3.7. Blocks per transaction are close
too (A1: 266 vs 289 tx per block).

**Upper bound on what MDBX can write.** MDBX copies a page at most once per write transaction; later changes to a page
already dirty in the transaction are made in place. So one commit cannot dirty more pages than the tables it touches
hold. At 17:54:44 on v01 the mutable tables are small: PlainAccountState 13.2 MB, HashedAccounts 16.1, PlainStorageState
42.2, HashedStorages 42.5 (state 114 MB), AccountsHistory 25.4 and StoragesHistory 90.7 (116 MB). TransactionHashNumbers
is 573 MB, but an output inserts 6 k random keys, so at most ≈ 6 k leaves plus ≈ 1.4 k branch pages (≈ 30 MB). The
append-only tables (TransactionSenders, the two changeset tables) add under 1 MB per output. The trie tables are not in
the collector; at roughly one branch node per 15 hashed entries they are estimated at under 20 MB. Copying every page of
every one of these tables in every commit would write ≈ 285 MB. Bench 5 wrote ≈ 931 MB per output. At least 70 % of the
bytes therefore come from below MDBX's page copies, whatever pages the workload touches. Bench 4 sits near its own bound
(≈ 240 MB at 09:33:50, measured 315-357 MB of which ≈ 20-25 MB/s is not MDBX), which suggests it was not entirely free
of the effect either.

**When the high-byte mode appears.**

- Bench 5 was in it from its first light blast: v01:16:18:06 wrote 39 MB/s against 8.6 MB/s idle, at about 600 tx/s
  on near-empty tables. The load's warm-up was at 526 MB/s by v01:17:38:36 and 609 MB/s at 17:39:06.
- Bench 4 was not, from its first minute: v01:09:09:02 78 MB/s and v01:09:10:32 185 MB/s (debug log included) at the
  warm-up's ≈ 8 k tx/s submitted (≈ 19-33 KB per transaction).
- Trajectories: bench 3 rose 80 → 170 KB/tx over its blast with zero page-cache re-reads (v01 `io_read_bytes` max
  0.1 MB). Bench 4 fell 52 → 37 KB/tx while its process re-read 1.3 GB from disk (v01 cumulative `io_read_bytes`
  20 MB at 09:14:02, 312 MB at 09:24:03, 1.26 GB at 09:54:03). Bench 5 re-read 4.8 MB in total.
- Bench 4 is the only run whose page cache churned. Its 1.16 GB/min engine debug log (≈ 49 GB of unit log per
  validator) took the root volume from 7 % to 65 % (09:04 → 09:54).

**Ruled-out code paths.** `git diff 496ebefb5 067639def -- crates/engine crates/tn-reth crates/storage`:

- `persist_executed_output` is identical (bench 4 `crates/tn-reth/src/env/execution.rs:326-365`, bench 5 `:431-470`).
  It opens one `provider_rw`, makes one `save_blocks(blocks, SaveBlocksMode::Full)` call with every block of the output,
  writes the finalized and safe markers in the same transaction, and commits once (`:465`). 4ab917aae and the E-units add
  timers and metrics only (`markers_ms` 0).
- E5 (420f8aef7) changes reads only. `advance_cached_reads` (`execution.rs:873-898`) updates the in-memory read cache
  from the block's bundle. The bundle that is written is still the block's `db.take_bundle()` (`execution.rs:346-349`),
  and the differential tests pin equal bundles and roots.
- Grouping cannot change the copied-page set. reth `save_blocks` (`crates/storage/provider/src/providers/database/provider.rs:600-688`
  in the reth checkout) writes the output's transaction hashes as one sorted batch, `write_state` per block, the merged
  hashed state and trie updates once per output, and history indices once, all in one MDBX transaction.
- crates/storage: visibility, tests and `ROUNDS_TO_KEEP` moved to tn-types. 746ac3272 raises certificate retention from
  64 to 128 rounds in the consensus DB (a few MB of live data, not MDBX). 0bd522ca7 times the existing pack persist.
- `Cargo.lock`, reth-db 1.11.3 and libmdbx 0.13.7 are unchanged. Neither run passed `--db.sync-mode`.

## Mechanism candidates, ranked

How MDBX is opened and committed. reth opens the RW environment with WRITEMAP (`crates/storage/db/src/implementation/mdbx/mod.rs:381-386`),
`no_rdahead` and `coalesce` (`:441-448`), `rp_augment_limit` 256 k (`:477`), the OS page size of 4 KB (`:139`), a 4 GiB
growth step (`:137`) and `SyncMode::Durable` (`:145`). TN calls it through `init_db(db_path, …database_args())`
(`crates/tn-reth/src/env/mod.rs:294`). libmdbx on Linux is built with `MDBX_AVOID_MSYNC=0` (`mdbx.c:1737-1742`), so it
keeps no dirty list and the kernel tracks dirty pages. A durable commit is `msync(MS_SYNC)` over
`[0, first_unallocated)` (`mdbx.c:20770-20776`, `osal_msync` at `:29325`). Spilling in WRITEMAP mode is
`msync(MS_ASYNC)`, which does nothing on Linux (`:33209`). The device writes whatever the kernel holds dirty for
`mdbx.dat` at that moment, in whatever unit the page cache dirties.

| # | candidate | plausibility | cheapest test |
|---|---|---|---|
| H1 | whole-folio writeback: 4 KB WRITEMAP stores dirty multi-page page-cache folios | high | one VM, fio mmap (minutes) |
| H2 | the unpinned Ubuntu image/kernel differed between bench 4 and bench 5 | medium | desk check (free) |
| H3 | bench 4's debug log kept the MDBX file's cache in single-page folios (modifier of H1) | medium as a modifier, nil alone | synthetic-writer arm |
| H4 | MDBX copies more pages (which keys, E5 ordering, per-block grouping) | ruled out as the main cause | in-engine page-op counter |
| H5 | another writer in the process (static files, consensus pack, tndb) | low | in-engine counter + diskstats |
| H6 | THP `enabled=always` making 2 MB file folios | low | probe field |
| H7 | measurement artefact | ruled out | n/a |

**H1. Whole-folio writeback.** A store through a shared file mapping marks the whole folio dirty: an mmap write fault
cannot tell which bytes changed, so every block of the folio becomes dirty. `msync` then writes the whole folio. If
`mdbx.dat`'s page cache holds multi-page folios, each 4 KB page MDBX copies into costs a folio of device writes. ext4
regular-file large folios are in mainline from 6.16. The Ubuntu 24.04 GCP kernels of late 2026 are HWE kernels
newer than that, but this is not verified for these runs: the kernel was never recorded. Two paths in libmdbx can put
multi-page folios into `mdbx.dat`'s cache on such a kernel:

- `prefault_write` is on by default for WRITEMAP (`mdbx.c:11425-11428`). When an allocation's pages are not resident,
  libmdbx pre-writes a pattern with `pwrite` for a single page, or with `pwritev` for a multi-page run (`:22356-22395`).
  A multi-page buffered write gets large folios. Every commit allocates such a run for its GC record: 50-225 k retired
  page numbers × 4 B is 0.2-0.9 MB, usually at the never-touched tail. The pages come back to the free pool later and
  are reused as ordinary 4 KB B-tree pages, still inside the large folio.
- libmdbx applies `MADV_RANDOM` only up to the used size at open (`dxb_set_readahead`, `:20055-20066`, called at open
  with the open-time used size at `:20618`). It extends the range only on a geometry change (`:19937-19943`). The 4 GiB
  file never resizes during a run (`db_bytes` 4,295,995,405 throughout both runs). After the deploy restart nearly the
  whole map is outside the random range, and read faults there read ahead into large folios. Holes read ahead without
  device reads, which fits bench 5's zero `io_read_bytes`.

What H1 explains: bytes above the copy bound; fewer, larger device operations (227 KB, 0.4× the ops/s); `/proc/<pid>/io`
agreeing with the device (write_bytes is charged per dirtied folio, `folio_nr_pages × 4 KB`); fleet uniformity; no code
change. With no reclaim, the large-folio share of the hot pages only grows, which fits bench 3 rising from 80 to 170 KB/tx
and bench 5 high after an hour of light blasts. Under reclaim it shrinks: evicted pages come back as single pages through
the one-page prefault `pwrite`, which fits bench 4 falling from 52 to 37 KB/tx while it re-read 1.3 GB.

Against H1: bench 4 was already low in its warm-up, before any re-reads. That fits only if bench 4's large-folio
population was still small when its load began (it went straight from idle to 8 k tx/s, while bench 5 had an hour of
light blasts first) or if bench 4 booted a different kernel (H2). The creation paths above are read from the code, not
observed.

**H2. Image or kernel drift.** The family is resolved per run. The runs were created on 11-03, 11-05 08:04Z and
11-07 15:06Z. For bench 3 to match bench 5 while bench 4 differs, the kernel would have to go A-B-A within four days,
which needs a withdrawn image. Alternatively, a single change between 11-05 and 11-07 would mean bench 3's similar
signature has its own cause (different code, contract-call workload). The guest kernel also sets the block-queue limits
(`max_sectors_kb`, merging) that decide the 32 vs 227 KB operation size, so the operation size is weaker cross-run evidence
than the bytes. The desk check settles H2 for free: list the `ubuntu-2404-lts-amd64` images with creation and deprecation
times, identify the family head at each run's create-instances timestamp, and read their `linux-gcp` version from the
image manifests.

**H3. Bench 4's debug log, as a modifier of H1.** The log cannot shrink MDBX's bytes directly:

- `msync` and `fsync` flush only `mdbx.dat`'s own dirty folios.
- An ext4 `data=ordered` journal commit forced by MDBX's sync must first write the log's newly allocated blocks, which
  makes bench 4's sync slower, not smaller.
- Early background writeback (`vm.dirty_background_ratio`) can only add rewrites.

Its only route is H1's folio population. Forty-nine GB of log through a 16 GB page cache evicts MDBX's folios, which are
clean between commits, and the copy destinations come back as single pages. Memory churn can also make high-order folio
allocations fail; they are allocated no-retry and fall back to order 0. Bench 4 is the only run with re-reads, which
supports the eviction route. Its low warm-up does not; see the objection under H1. Logged per node, bench 3 wrote ≈ 1 GB,
bench 4 ≈ 49 GB and bench 5 0.17 GB, which lines up with high, low and high bytes but proves nothing alone.

**H4. MDBX copying more pages.** The upper bound rules it out as the main cause. Senders 400000+ (bench 5) and 0-5999
(bench 4) are random addresses and random hashed keys in both runs. Six thousand against 8-12.5 k transactions per output
changes how far branch-page copies are amortized by tens of per cent, not four times. E5 and the per-block grouping cannot
change the copied set (see "Ruled-out code paths"). The freelist is the same in both runs (bench 4 20 k → 55 k pages,
bench 5 21 k → 59 k), and the file never grows past its first 4 GiB step in either.

**H5. Another writer in the process.** No write path changed between the images:

- Static files grow 0.86 MB/s, `commit_sf` takes 9-38 ms and `save_blocks_sf` 20-30 ms.
- The consensus `epochs` store grows 0.34 MB/s.
- Idle writes are equal in both runs (8.3-8.7 MB/s).
- The time sits inside MDBX's sync phase: `transaction_commit_sync` equals the whole commit.

A writer whose volume quadrupled with unchanged code would also have to land inside MDBX's `msync` window to stretch it.

**H6. THP.** libmdbx never issues `MADV_HUGEPAGE` (none in `mdbx.c`), and the 2 MB file-folio path for mmap faults
needs it. Ubuntu's default `enabled` is `madvise`. Large folios below 2 MB from buffered writes and readahead do not
depend on the THP knob. Record the setting, but do not expect it to discriminate.

**H7. Measurement.** Ruled out. GCP device bytes and `/proc/<pid>/io` agree inside each run (bench 5: 524 vs 526 MB/s;
bench 4: 201 vs 164 MB/s, the gap being the log written outside the telcoin process). The same disk spec and sampler code
ran in both. The commit duration tracks bytes at the device rate in both runs.

**Most likely cause: H1.** The kernel writes back whole multi-page folios for MDBX's 4 KB WRITEMAP page copies. Why bench 4
escaped is open between H2 (another kernel) and H3 (page-cache churn from its log).

## Proposal

1. Desk check (free, before anything else). Identify the Ubuntu image and `linux-gcp` version each of the three runs
   booted. If bench 4 and bench 5 differ, pin the image for bench 6 and say which one was used.
2. One-VM test (the single cheapest decisive test, about 30 minutes, no chain). Boot one c3-highcpu-8 from the current
   family with the same 100 GB hyperdisk-balanced at 20 k IOPS and 800 MiB/s. Record `uname -r`. Lay out a 4 GiB file
   with large buffered writes, then run
   `fio --ioengine=mmap --rw=randwrite --bs=4k --size=4g --fsync=2000 --fadvise_hint=0 --time_based --runtime=180`
   (the mmap engine flushes with `msync`). Compare fio's written bytes with the device's (sectors written in
   `/proc/diskstats`, `iostat -x` `wareq-sz`). Repeat after `echo 1 > /proc/sys/vm/drop_caches` with `fadvise_hint=1`.
   - A ratio near 1 both times means H1 is dead; go to item 3.
   - A ratio well above 1 that falls to about 1 after the drop confirms H1 and the folio dependence. Repeat on the image
     bench 4 booted (from item 1) to settle H2.
3. Bench-6 observability (small, off the hot path):
   - In `persist_executed_output`, read `Environment::info()?.page_ops()` before `save_blocks` and after `commit`
     (reth-libmdbx `environment.rs:410-425`: `newly`, `cow`, `split`, `merge`, `prefault`, `mincore`, `msync`;
     `MDBX_ENABLE_PGOP_STAT=1` is compiled in, `mdbx.c:1680`). Read `/proc/self/io` `write_bytes` at the same two points,
     and add `mdbx_newly`, `mdbx_cow`, `mdbx_prefault` and `proc_write_bytes` to the `persisted output` line.
   - Add AccountsTrie and StoragesTrie to the collector's `reth_db_table_size` series.
   - Extend the H2 pre-start probe with: `uname -r`; the boot image from instance metadata;
     `/sys/kernel/mm/transparent_hugepage/{enabled,defrag}`; `vm.dirty_ratio`, `dirty_background_ratio`,
     `dirty_expire_centisecs` and `dirty_writeback_centisecs`; `findmnt -no FSTYPE,OPTIONS` for the datadir;
     `/sys/block/<dev>/queue/{max_sectors_kb,read_ahead_kb,scheduler}`.
   - Add to the sampler: `/proc/diskstats` write ios and sectors (gives `wareq-sz`), and `/proc/vmstat` `nr_dirty`,
     `nr_writeback`, `workingset_refault_file` and `thp_file_alloc`.
4. Bench-6 arms of about 20 minutes each, after the main load:
   - (a) control on the bench-6 image;
   - (b) the bench-4 image 496ebefb5 with the engine dumps filtered out (`engine=info`), which isolates code from log;
   - (c) the bench-6 image with a synthetic 20-25 MB/s sequential writer on the datadir volume, which tests H3;
   - (d) the bench-6 image with the page cache dropped just before the blast; under H1 bytes per transaction start low
     and climb;
   - (e) last, `--db.sync-mode safe-no-sync` as a diagnostic only. It bounds what the sync costs (≈ 172 of 199 µs/tx).
     It also changes write coalescing, so it does not measure amplification. A crash can roll MDBX back to its last
     steady commit, which the restart path must then replay from the consensus DB. Never outside a bench.
5. Fix directions if H1 is confirmed, each to be measured on the one-VM rig before a run:
   - Keep `mdbx.dat`'s cache in single-page folios: disable libmdbx `prefault_write` (`MDBX_opt_prefault_write_enable`
     = 0) and `madvise(MADV_RANDOM)` the whole map, not only the open-time used range.
   - Or open the environment without WRITEMAP, so MDBX writes its dirty pages with `pwrite`. ext4 tracks dirty state per
     block for `write(2)`. reth hardcodes `write_map()` for RW (`mdbx/mod.rs:385`), so this needs a reth option.
   - Pipelined persist (A6 lever 2) hides the sync whichever cause wins: about 5.0 k tx/s at today's commit.
   - Restoring bench 4's per-transaction commit (≈ 35 µs/tx) alone gives about 6.9 k tx/s (A4n §5).

## Test plan

- Item 2 is the test for H1 and H2. Record it in `benchmark/private/` with the image name, the kernel, fio's job file and
  output, and the `/proc/diskstats` deltas before and after.
- Item 3 code: a tn-reth unit test that a persisted non-empty output reports non-zero `mdbx_cow` and `proc_write_bytes`
  and that an empty output reports zero `mdbx_cow`; extend `test_metrics_register_and_update` if the fields become
  metrics. fmt and clippy.
- Item 5 code, whichever direction is taken: the existing persist and restart e2e tests, plus a one-VM A/B of the reth
  bench (`save_blocks` and `commit` of a 6 k-transaction output on a warmed 4 GiB environment) comparing device bytes per
  commit and commit latency.

## What the next benchmark run reads

- Per output, `amplification = proc_write_bytes / ((Δnewly + Δcow) × 4096)`.
  - About 1 means MDBX's own copies are the bytes. H4 is back, and the per-table page counts say which table.
  - About 4 (bench 5) means H1. Compare it with `wareq-sz` and with the arm outcomes.
- The probe fields: the kernel and image on every node, identical across the fleet, and the same in every arm.
- Bytes per transaction and its 5-minute trajectory against `workingset_refault_file` and `io_read_bytes`. Under H1 it
  climbs while nothing is evicted and falls when the cache churns.
- Arm outcomes:
  - (b) high on today's kernel means not the code; H2 if item 1 found a different kernel for bench 4.
  - (c) falling over time means H3 is real as a modifier.
  - (d) starting low means H1's folio population.
  - (e) gives the sync's share of the 199 µs/tx persist.
- The commit µs/tx (`persisted output` `commit_ms / txs`) against bench 5's 178 and bench 4's 28-45. That number is what
  moves the ceiling.
