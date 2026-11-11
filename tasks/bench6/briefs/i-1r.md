# I-1r — read the local probe, find what still separates the node from it, and arm the GCE probe accordingly

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (sections "What nobody but the orchestrator does",
"Checkpoint, budget, scratch", "Investigations", "HAND BACK"). Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-I-1r.md` (on start, read it and continue from the first unfinished
section). Output directory: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-1r/`.
Skills: `tn-domain-storage`, `tn-domain-execution`.

## Where things stand
Bench 5 (run r20261107-1504) lost 24.7 % throughput because the MDBX commit wrote 4.3× the device bytes of the pages it dirtied:
under WRITEMAP a page cache made of large folios is written back a whole folio at a time. Unit I-1 ranked the cause
(`benchmark/private/bench6-prep/I-1/verdict.md`, read it first, then `probe-arms.md` and `u3-notes.md` beside it): every node ran its
load in a RE-OPENED database whose open-time `MADV_RANDOM` covered only the genesis pages, and large folios were built in the rest by
one of two routes — R1, mmap read-around at the growth frontier; R2, libmdbx's multi-page prefault `pwritev`. The node fix being
built (unit U3) applies `MADV_RANDOM` to the whole map. I-1 named its own falsifier (verdict.md, "What would falsify"): the probe's
arm 7 under reth's defaults staying at ≈ 1.00× while its prefault-off positive control rises.

The local probe has now run on a quiet machine (xerxes, Linux 7.0.0-38-generic, ext4 on LVM, 61 GB RAM), eleven arms:
results in `/home/drtnarg/coding/telcoin/mdbx-writeback-probe/results/i1-20261111T154355Z/` (`summary-i1.csv`, `summary.csv`,
`run-i1.log`, `status.txt`, one CSV per arm). What the orchestrator read off the log (verify every number yourself):

| arm | what it is | device ÷ MDBX-dirtied (median) | notes |
|---|---|---|---|
| 7-default | re-opened DB, growth inside the unadvised range, reth defaults (prefault on) | 1.000 | 95 pages grown and 95 prefault calls per output; 0 pages resident past used |
| 7-ovf | + 5 % of tx upsert 6,000-byte values (two-page allocations) | 1.008 | 97 pages and 97 prefault calls per output |
| 7-pfoff | prefault OFF (positive control) | **8.686** | 0 prefault calls; 33-63 pages resident past used |
| 7-pfoff-mrand | prefault off + whole-map `MADV_RANDOM` | 1.000 | 0 pages past used |
| 7-ovf-mrand | 7-ovf + whole-map `MADV_RANDOM` | 1.008 | |
| 7-ovf-pfoff-mrand | both | 1.000 | |
| 7-noreopen-pfoff | no re-open, prefault off (negative control) | 1.000 | |
| 8-readused-nopressure | 1 GB DB whose used range was read through the page cache, no pressure | 5.37 (wide band) | |
| 8-readused, 8-readused-random, 8-cold-normal | reclaim pressure variants | see the files | were still running when this brief was written |

So: (1) the whole-map advice closes the read-around route completely (8.69 → 1.000); (2) with prefault ON — which is what the node
runs — the re-open condition alone does NOT reproduce the amplification on this kernel: I-1's falsifier fired for R1 under
defaults; (3) R2 was barely exercised (two-page runs only, and the calls-per-page ratio stayed 1.00). What gives a real node its
large folios is therefore open again, and the one-VM GCE probe and run 1's control arm must be armed to find it.

## Questions (one section each; checkpoint after each; every claim cites file:line or a result file and column)
1. **Read the eleven arms properly.** The table above with p10/p90, commit time, write sizes, the residency and prefault columns, and
   the arm-8 family (does reclaim pressure break up a resident large-folio cache: yes/no, how fast, how far). Note anything that
   makes an arm unclean (swap was 8 GB in use when it started; the wide band on arm 8; a `grown` figure that is clearly an
   arithmetic overflow in one summary line).
2. **What differs between the node and arm 7-default?** Work through, in code (`/home/drtnarg/coding/telcoin/telcoin-network-b6`,
   read-only; libmdbx under `vendor/reth/crates/storage/libmdbx-rs/mdbx-sys/libmdbx/mdbx.c`) and in bench-5 data
   (`benchmark/results/r20261107-1504/sampler/*.csv`, the manifest, `benchmark/private/bench5-r20261107-1504/I-B2/*.md`,
   `benchmark/private/bench6-prep/I-3/verdict.md`), each candidate, and rank them with what evidence exists and what would test it:
   - **Is prefault really on for the node's allocations?** I-1 says the per-allocation switch-off applies to a database under 1,234
     pages or to pages below an enabled read-ahead edge (`mdbx.c:22486-22500`). Find every way that edge can become enabled for a
     running node: the node's own open flags on the first (creating) and the second open; any OTHER process that opens the same
     environment without `NORDAHEAD` while the node runs or between the two starts (the node design found that a plain `mdbx_stat`
     does exactly this through the shared lock file) — list every `telcoin` subcommand or tool the deploy, the finalize stage
     (`/home/drtnarg/coding/telcoin/devnet-genesis/tn-node-deployment/` and `devnet-finalize.sh`, read-only: I-1 did not read
     them), the image entrypoint, the samplers or the health checks run against the datadir, and what each opens.
     If prefault is effectively off on the node, arm 7-pfoff IS the node's case and the picture closes: say so plainly.
   - **Multi-page allocations of real size (R2).** Which allocations in the real node span many pages: overflow values (which
     tables, how large), and above all the GC/freelist records — bench 5's freelist reached 58-59 k entries in 5-minute means
     (15-s peaks 78-81 k), which is a record of hundreds of kilobytes rewritten at every commit, prefaulted in `pwritev` runs of up
     to 64 pages. Does that fit the commit-cost drift I-3 measured (+0.031 s per output per minute of load in both windows, with
     the freelist growing)? What does libmdbx do with a GC record larger than one page (split into chunks? `mdbx.c` gc_update)?
   - **The size of the outputs and of the database** (the probe used 2,000-tx outputs on a 0.2 GB database; the node 6-7 k tx on
     gigabytes), the number of tables and their fan-out, read faults on pages written long ago.
   - **Kernel and filesystem**: what differs between `7.0.0-38-generic` on ext4/LVM/NVMe and the GCE image's `7.0.0-1017-gcp` on its
     data disk (filesystem and mount options are in bench 5's deploy scripts; large-folio support for buffered writes; read-ahead
     defaults of the block device). Only what can be established without the VM; the rest goes to the GCE probe.
   - Anything else your reading turns up.
3. **Extend the probe so the GCE run can separate what is left.** You are the only writer of the probe crate
   `/home/drtnarg/coding/telcoin/mdbx-writeback-probe` (I-1 added arms 7 and 8 and the flags listed in `probe-arms.md`). Add what
   question 2 calls for — at least: an arm (or flags) that produces multi-page allocations of realistic size (large overflow values
   up to 64 pages; a large freelist built by a long-held reader and then released, so that GC records span many pages) under
   prefault on, with and without the whole-map advice; and a way to emulate "another process enabled the read-ahead edge" if
   question 2 finds a real path for it. Record per output what proves the route: pages per prefault call, the largest `pwritev`
   run, the freelist length, the GC record size. Build through the slot wrapper
   (`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo build --release …`) and SMOKE each new arm for a few
   seconds only: the machine is no longer quiet (other units are compiling), so local numbers from now on are smoke, not
   measurement. Keep every existing flag and CSV column; append new columns at the end.
4. **The GCE arm list, revised.** Rewrite §4 of `benchmark/private/bench6-prep/I-1/probe-arms.md` IN A NEW FILE,
   `…/I-1r/gce-arms.md` (do not edit I-1's files): the arms G0… in run order with the exact probe command line for each, what each
   proves, the expected result under each surviving hypothesis, and the total time (aim for at most 60 minutes on one VM; say what
   to cut first). It must still contain: a baseline that mimics the node as closely as the probe can; the read-all and
   `read_ahead_kb` 16 arms; whole-map `MADV_RANDOM` with and without read-all; the growth arm with its prefault-off positive
   control; no-WRITEMAP; the sampler-safety arm (five folio censuses as root against a live arm leave residency unchanged) — plus
   the new arms. The probe driver (`benchmark/benchmark-probe.sh`, another unit's, being finished now) takes its arms from a
   table: write the list so that it can be pasted into that table (name, needs-own-scope flag, arguments).
5. **What run 1's control arm must record** to settle it on the real node if the VM does not: the fields already planned are the
   node's per-persist page-operation deltas (`page_newly`, `page_cow`, `page_spill`, `page_unspill`, `page_prefault`, `page_wops`,
   `page_msync`), `mdbx_used_bytes`, `mdbx_advised_bytes`, the persist sampler's residency and `rr` columns, resident pages past the
   used size, and the folio census by order. Say which of the surviving hypotheses each field decides, and name anything missing
   (for example the freelist length per persist, or the count of multi-page prefault calls) precisely enough for the node unit U3
   to add it — the orchestrator passes it on.

## Read list (explore no further; hand back instead)
The files named above; `benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md` §B topic 3 (the `mdbx_stat` finding);
the probe crate's `README.md`, `src/`, `run-full.sh`; `benchmark/private/bench6-prep/I-1/run-i1.sh`; in the worktree
`vendor/reth/crates/storage/db/src/implementation/mdbx/mod.rs`, `vendor/reth/crates/storage/libmdbx-rs/src/environment.rs`, the
parts of `mdbx.c` the questions name (grep, read in ranges: the file is very large), `crates/tn-reth/src/env/mod.rs`,
`crates/telcoin-network-cli/src/{node.rs,db.rs}`; the deploy side: `benchmark/bench-lib.sh` (`bench_prestart_script` and the
finalize calls), `benchmark/benchmark-deploy.sh` steps 5-9, `benchmark/node-sampler.sh`, `devnet-finalize.sh` and the scripts under
`tn-node-deployment/` that it runs on a node (read-only; never edit `tn-node-deployment/` or `common/`).

## Deliverables
`…/I-1r/verdict.md` (questions 1, 2, 5), `…/I-1r/gce-arms.md` (question 4), the probe crate changes with a short
`…/I-1r/probe-changes.md` (flags, columns, smoke results). Final answer: at most 40 lines — the eleven-arm table, the ranked list
of what still separates the node from the probe with your confidence in each, the revised GCE arms in one line each, what U3 must
add to its log line, and the points for the user's G1 gate.
