# Sources: tasks/bench6-not-carried-writeup.md (not for posting)

Written 2026-11-14 by U-I3W. Figure or claim -> file and line. "M" = telcoin-network 45dce8947 (worktree telcoin-network-b7, HEAD verified = 45dce89474e1efc7f90c6fbd1e51332cc237ab9b). "B6" = bench/bench6-2026-11 at 2df831e3c (worktree telcoin-network-b6).

## Intro
- twelve switches, off by default, base 165e3fe01 (older than #1834): tasks/bench6-report-r20261113-1351.md:79-81; DR rules (165e3fe01 not an ancestor of M): tasks/bench7-agent-rules.md:22.
- #1834 contents: tasks/bench7/briefs/u-i3w.md:8; tasks/bench7/briefs/u-common.md:10.
- runs and disks: report §2 "The three runs" (:94-103), fleet :89; adaptive twins report §8.2 (:666-671). Run 1 has no page: tn-benchmarks/runs/ lists no r20261112-1520 (checked 2026-11-14); the backfill files call it "an earlier arm-walk run of the same build (r20261112-1520)" (benchmark/report/backfill/2026-11-13-bench6-always-20k.json).
- "Each configuration ran once": report §8.1 item 6 (:662), §8.3 (:695).

## MDBX advice
- libmdbx advises only the part in use at open: issue #1802 body, Mechanism ("`MADV_RANDOM` only over the part that was in use when the environment was opened", `dxb_set_readahead`).
- first-process state, prefaults skipped, large folios written whole, restart ends it: report §4.2 :333-339; §1 item 2 :40-44; source run 1 I-9/findings.md.
- observer 6.5-10.9x: report :42, :337.
- bench 5 10-13x through run 1's model, no page counts: report §1 table :26; :346.
- single pages throughout, 1.156-1.193 validators, 1.06 observer: report §4.2 :343-346; §1 table :26 (1.186-1.193 run 2, 1.156-1.170 run 2b, observer 1.064/1.062).
- correlation / bench-5 first process not checked: report :339, :350.
- M: `mdbx` feature off by default: crates/tn-reth/Cargo.toml:157-161 ("Off by default"); bin/telcoin-network/Cargo.toml:30.
- M: readahead default false on Linux -> MADV_RANDOM: crates/tn-lmdb/src/env.rs:309-317 (doc), :397 (default); node takes engine default: crates/tn-lmdb-reth/src/env.rs:311-325 (`..EnvOptions::default()`, doc "its access advice among them"). README same mechanism: crates/tn-lmdb/README.md:2472-2490.
- 19,967 writes/s, 0.998 of 20,000, 3.74 writes/tx, 5.0 KiB: report §4.1 :311; §1 table :27.
- "executed rate = limit over writes per tx": report §1 item 1 :36; §4.1 :327.
- next benchmark on main at 20,000 IOPS: tasks/bench7/briefs/u-i3w.md:17 ("bench 7 will produce it at 20,000 IOPS").

## Stored-record check
- what B6 42b2a6f39 did: `git -C telcoin-network-b6 show 42b2a6f39` message ("returns without building or signing its own ... compares the stored record's final_state with the node's closing block and returns an error ... before publishing the record").
- ran on late validators and passed, never a mismatch: report §4.4 :391-393. Runs 3/3b closes all on one record hash: report §8.3 :716, :741.
- M: check_stored_record close_epoch.rs:712-749; stored path call :432; entry call :590 (in recover_previous_epoch_record, :575-596); metric `tn_epoch.final_state_mismatches_total` (crates/node/src/metrics.rs:24, :89 test name); counter :734, error line :735-745. Corroborated by benchmark/private/bench7-prep/DR-E/findings.md:7, :23-36, :66.
- gap: build path samples `latest_execution_block_num_hash()` at close_epoch.rs:411 and compares nothing before save_record :514 / publish :519; entry check is after the vote: DR-E/findings.md:9, :33, :42.

## Pipelined persist
- design (pin before N's persist, N's deltas layered): B6 crates/tn-reth/src/env/output_overlay.rs:21-30; at most two outputs: B6 crates/engine/src/lib.rs:65-68; failure rule: B6 crates/engine/src/persister.rs (module doc "Failure: ... rolled back to the durable tip in one call"; struct doc "After an error the pipeline is spent ... stops the node").
- gates: tasks/archive/plan-bench6-2026-11-10.md:63 (ST-U12a: 400-case hunts of the differential and the fault property, no finding), :64 (ST-U12b: mixed pipelined/sequential fleet one chain 3 of 3, five SIGKILLs mid-pipeline replay 3 of 3), :66 (gate 5: interval over the longer phase 0.991 / 1.030 execute-bound, 1.004 / 1.003 persist-bound; overlapped 35/35 x4).
- cycle bench raw: benchmark/work/bench6-scratch/st-u12c/cycle-{pinned,unpinned,pinned-persist-bound,unpinned-persist-bound}.txt line 5 (`interval_over_max_phase=0.991/1.030/1.004/1.003`). Runbook: tasks/bench6/quiet-host-runbook.md:12-29.
- arm walk cycle 1.010 at M16: benchmark/private/bench6-r20261112-1520/A4e/pipelined.md:46.
- commit slot 97.6 %: pipelined.md:29; 7.04 writes/tx / 20,000 = 352 us/tx vs 354.9: benchmark/private/bench6-r20261112-1520/A7/verdicts.md:278.
- slowest M16, outputs half the size: benchmark/private/bench6-r20261112-1520/A7/final-arm-options.md:71.
- build beside a commit 3-14 us/tx, upper estimate: pipelined.md:70, :74.
- never at 50,000: report §4.6 :462.
- M: parallel.rs:63-82 (":74 What would break it: persisting an output while the next one builds (a pipelined persist)"), :18-19 (each task opens its own read-only transaction, "a database transaction is not shared across threads"); output_overlay.rs:73-75 (anchor = database tip, persistence strictly sequential), also :196-198; execution.rs:555-559 (failed persist clears the execution cache, "the blocks are rebuilt or the node stops").
- persist a third of the cycle at 50,000: report §1 item 6 :60-62; §4.6 :447 (44.5 of 133.9 us/tx).
- #1800 closed 2026-11-12 (gh issue view 1800: closedAt 2026-11-12T19:13:16Z; comment "Fixed on main by a3df64830 (#1827 ...)").

## Left out
- the 27-35 % sequential counterfactual (pipelined.md:99-102): not a controlled comparison.
- speedups 1.10-1.35 from the cycle bench: not here (word budget).

## Revision 2 (2026-11-14, figure-check tasks/bench7/figcheck-UI3W.md applied)
Changed sentences and their sources:
- MDBX, "The switch advised the whole MDBX mapping `MADV_RANDOM`; ..." ("from the first start" moved to the sentence on runs 2/2b): orchestrator's item 4 (staging fact from the runs' own logs: each node ran once alone during staging, 17-90 s, every switch at default, no peer, no output executed; arm switches on from the coordinated start).
- MDBX, "every node's first process that executed blocks skipped ..." (was "first process after genesis"): orchestrator's item 4 (the arm walk's control had the same staging process before its first loaded process); the state itself unchanged: report :333-339.
- MDBX, "The observer, the one node the first arm did not restart, ...": figcheck Weak, write-up line 15 (report :335-337: restarted at the next arm, then 1.06x).
- MDBX, "With the advice on from the coordinated start, the first process that executed blocks (each node had first run once, alone, during staging, with every switch at its default and no output executed), ...": orchestrator's item 4.
- MDBX, "main runs its execution database on MDBX only under ...": figcheck Weak, line 19 (crates/tn-reth/Cargo.toml:159-160: the default build reads an MDBX database to migrate it).
- MDBX, "3.74 writes per executed transaction" (dropped "of 5.0 KiB"): cut for length; figure unchanged (report :311).
- MDBX, "the next benchmark, on main, is to measure them at 20,000 IOPS": figcheck Weak, line 23 (a plan).
- Stored record, "It also runs at every epoch entry (`:590`)." (dropped "so main covers more than the bench-6 change did"): cut for length.
- Pipelined, "After a failure every block not yet durable was rolled back ..." (dropped "At most two outputs were in flight"): cut for length.
- Pipelined, gates sentence shortened ("among them a 400-case differential against the sequential engine, a mixed fleet that stayed one chain and kills mid-pipeline that replayed cleanly"): cut for length; source unchanged (tasks/archive/plan-bench6-2026-11-10.md:63-64).
- Pipelined, quiet-host interval sentence (0.991-1.030) removed: cut for length (a secondary gate result).
- Pipelined, "at 600 × 16 (600 senders per generator, each keeping 16 transactions in flight), but the persist carried the whole device write time": figcheck error 4 definition (report :171; A7/verdicts.md:305) and Weak line 48 (354.9 us/tx is the whole persist: A4e/execute.md:34, verdicts.md:278).
- Pipelined, "It does not carry because #1834's parallel storage roots and output overlay assume that no persist overlaps the next build, and its execution cache's failure rule assumes the next build has not started.": figcheck error 1 replacement, verbatim (parallel.rs:62-81, :74; output_overlay.rs:73-75; exec_cache.rs:30, :38-50; execution.rs:556-557).
- Pipelined, "each storage-root task opens its own read-only transaction, so one pinned transaction no longer covers a root" (dropped the clause on threads): cut for length.
