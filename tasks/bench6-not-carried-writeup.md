# Bench 6: three measured changes that do not carry to main

Bench 6's node build (`bench/bench6-2026-11` at `2df831e3c`) put twelve changes behind switches, off by default, on a base older than #1834.
Main at 45dce8947 has since replaced the execution storage engine (#1834: tn-lmdb by default, storage layout v2, an execution cache, parallel storage roots).
Three of the changes do not carry to that main and are not sent as pull requests; this note keeps what they measured.

The runs are [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) (20,000 provisioned IOPS), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) (50,000), their twins under the adaptive vote fix [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) and [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/), and the arm walk r20261112-1520 (nine switch sets by rolling restart, no run page).
Each configuration ran once.

## The MDBX random-access advice (`mdbx_random_advice`, #1802)

The switch advised the whole MDBX mapping `MADV_RANDOM`; libmdbx advises only the part in use when the environment opens.

In the arm walk every node's first process that executed blocks skipped libmdbx's prefault writes, and new pages landed in large page-cache folios that were written back whole; a restart ended that state.
The observer, the one node the first arm did not restart, wrote 6.5 to 10.9 times its page bytes, near bench 5's 10 to 13 times ([r20261107-1504](https://benchmark.telcoin.network/runs/r20261107-1504/), through a model, since bench 5 logged no page counts).
With the advice on from the coordinated start, the first process that executed blocks (each node had first run once, alone, during staging, with every switch at its default and no output executed), every node of r20261113-1351 and r20261113-1630 wrote single pages throughout: 1.156 to 1.193 device bytes per page byte on the validators at full load, 1.06 on the observer.
What starts the state is a correlation, and whether bench 5's nodes took load in their first process was not checked.

It does not carry: main runs its execution database on MDBX only under the off-by-default `mdbx` feature (`crates/tn-reth/Cargo.toml:157-161`), and the default engine already advises every mapping `MADV_RANDOM` on Linux (`crates/tn-lmdb/src/env.rs:309-317`, default at `:397`), a default the node keeps (`crates/tn-lmdb-reth/src/env.rs:311-325`).

What survives: the advice fixed the bytes, and on this disk class the write count binds.
Over the load blast of r20261113-1351 the device ran 19,967 writes per second against 20,000 provisioned IOPS, 3.74 writes per executed transaction, so the executed rate was the limit over writes per transaction.
tn-lmdb's writes per transaction on such a disk are not measured yet; the next benchmark, on main, is to measure them at 20,000 IOPS.

## The stored-record state check (`epoch_record_state_check`, 42b2a6f39)

A member that reaches an epoch close late finds the record the faster members certified already stored and reuses it, so on the bench-6 base nothing compared its execution with the record.
The switch made the node compare the stored record's `final_state` with its own closing block and stop on a mismatch, before publishing the record.
It ran on late validators in r20261113-1351 and r20261113-1630 and passed; no bench-6 close had a mismatch for it to catch.

#1834 made the same comparison unconditional.
On main at 45dce8947, `check_stored_record` (`crates/node/src/manager/node/close_epoch.rs:712-749`) runs on the stored-record path (`:432`), counts a mismatch in `tn_epoch.final_state_mismatches_total` and stops the node.
It also runs at every epoch entry (`:590`).

A narrower gap remains.
When a node builds its own record, nothing checks, before it saves and votes for it, that the block it commits as `final_state` (sampled at `:411`) is the block in which the epoch-closing calls ran; the entry check compares it only after the vote.
That gap is filed separately as {{epoch-record-closing-block-check}}.

## Pipelined persist (`pipelined_persist`, #1800, closed)

The switch let the engine commit output N while it built N+1.
N+1's state roots read one read-only transaction pinned before N's persist, with N's blocks layered on it, whatever N's commit did meanwhile.
After a failure every block not yet durable was rolled back and the node stopped.

It passed its gates, among them a 400-case differential against the sequential engine, a mixed fleet that stayed one chain and kills mid-pipeline that replayed cleanly.

In the arm walk, at 20,000 IOPS, the cycle was 1.010 times the longer stage at 600 × 16 (600 senders per generator, each keeping 16 transactions in flight), but the persist carried the whole device write time: 7.04 writes per transaction at 20,000 IOPS is 352 µs per transaction, against 354.9 measured.
Where write IOPS set the rate, overlap could not add throughput; that arm was the walk's slowest at 600 × 16, through outputs half the size of the arm before.
A build beside a commit cost 3 to 14 µs per transaction more, an upper estimate, and the switch never ran at 50,000 IOPS.

It does not carry because #1834's parallel storage roots and output overlay assume that no persist overlaps the next build, and its execution cache's failure rule assumes the next build has not started.
`crates/tn-reth/src/env/output_overlay/parallel.rs:63-82` says so and names "a pipelined persist" as what would break it (`:74`); each storage-root task opens its own read-only transaction, so one pinned transaction no longer covers a root.
The overlay is anchored at the database tip (`crates/tn-reth/src/env/output_overlay.rs:73-75`), and a failed persist clears the execution cache on the premise that the blocks are rebuilt or the node stops (`crates/tn-reth/src/env/execution.rs:555-559`).

What survives: with the disk off its limit the engine's sequential cycle set the ceiling, and the persist was a third of it; that is filed as {{execute-and-persist-in-series}}.
The reference implementation stays public on `bench/bench6-2026-11` at `2df831e3c`.
