# Sources: tasks/issue-bodies/bench6-execute-and-persist-in-series.md (not for posting)

Slug: execute-and-persist-in-series. Written 2026-11-14 by U-I3W. "M" = 45dce8947 (telcoin-network-b7). Paths without a run are under benchmark/private/.
Abbreviations: E2 = bench6-r20261113-1351/A4e/engine.md (runs 2 and 2b); E3 = bench6-r20261113-2118/A4e/engine.md (runs 3 and 3b); P1 = bench6-r20261112-1520/A4e/pipelined.md; R = tasks/bench6-report-r20261113-1351.md.

## Problem
- "fleet ran at its costliest engine's sequential capacity; persist a third of busy time": R §1 item 6 :60-62; E2 :14-18, :197-199 (execute 639 / persist 336 of 975 busy ms/s; v01 persist 33 %).
- MDBX + layout v1 on bench 6; storage v2 on M: R §2 :79; #1834 (brief u-i3w.md:8).
- next benchmark on main at 20,000 IOPS: brief u-i3w.md:17.

## Evidence
- runs, disks, forms: R §2 :89, :96-103; §8.2 :666-671. Ten validators: R :16.
- 40-minute load blast, nine validators pooled (v05 apart): E2 :36, :41; E3 :287.
- no task before the previous ended: E2 :49-53 (29,774 run 2, 27,219 run 2b); E3 :321 (24,975 run 3b).
- table, r20261113-1351: E2 :63 (execute 90.2, persist 95.2, save 20.9, commit 74.2, announce 0.71, task 187.2, 5,314 tx/s, tx/output all 3,854, busy 994); device 0.998: R §1 table :27 / §4.1 :311.
- table, r20261113-1630: E2 :66 (87.7; 44.5; 21.9; 22.4; 0.75; 133.9; 7,287; 5,781; 975); device 0.497: R :27, :313.
- table, r20261114-0000: E3 :329 (89.6; 42.5; 20.9; 21.5; 0.77; 133.8; 7,210; 6,234 all; busy 965 log); device 0.480: R §8.3 :740.
- validator-01 136.9 us/tx, 997 ms/s, backlog 14-18, capacity 7,287 = fleet rate: E2 :16; R §4.6 :450. Cheapest idled 50 ms/s: E2 :17. Input holder not measured: E2 :20, :290; R :459.
- persist ~260 ms/output run 2b (commit 130, save 130): E2 :284 (cross-check of the preliminary read). 268 ms run 3b (commit 136, save_blocks 132): E3 :288.
- save_blocks 20.9 (20k) vs 21.9 (50k): E2 :221.
- arithmetic 7,469 at full busy, 7,287 measured, 11,397 persist free: E2 :24, :216-218; R §4.6 :456.
- pipelined persist on bench/bench6-2026-11 2df831e3c: R §4.7 :482; B6 crates/engine/src/lib.rs:65-68, :81-83.
- arm walk cycle 1.010-1.072 x longer stage: P1 :43-49 (medians 1.017, 1.010, 1.060, 1.072, 1.071 over blasts 9-14).
- disk bound, no throughput gain: bench6-r20261112-1520/A7/final-arm-options.md:71; A7/verdicts.md:291.
- build beside commit 3-14 us/tx, upper estimate: P1 :70, :74.
- quiet host, lab DB: benchmark/work/bench6-scratch/st-u12c/cycle-pinned.txt and cycle-unpinned.txt line 5: execute_stretch 1.257 / 1.219, speedup 1.100 / 1.108 (execute-bound, unforced). Runbook tasks/bench6/quiet-host-runbook.md:28-29 (read stretch from unforced runs). Gate record tasks/archive/plan-bench6-2026-11-10.md:66.
- never ran at 50,000: R §4.6 :462; §6 item 4 :573-575.

## Where in the code (M, read 2026-11-14)
- crates/engine/src/lib.rs:279 `run`; :304-311 spawn only when `pending_task.is_none()` ("the previous consensus output finishes executing before inserting the next task"); :61 MAX_QUEUED_OUTPUTS = 8.
- crates/engine/src/payload_builder.rs:392-412 persist in line with rollback on failure; :401 persist_output_with_retry; :415-421 announce + finalize_block; :427-445 `output executed` with execute_ms, persist_ms, announce_ms.
- crates/tn-reth/src/env/output_overlay/parallel.rs:18-19 (each task opens its own read-only transaction), :63-82 ("Why the tasks' transactions see the walk's state"), :74 ("What would break it: persisting an output while the next one builds (a pipelined persist)"); metrics names `tn_reth.parallel_state_root_task_failures_total` (tip_moved) :79-80, `tn_reth.parallel_state_root_mismatches_total` :90 (module doc).
- crates/tn-reth/src/env/output_overlay.rs:73-75 (anchor = database tip; "TN persistence is strictly sequential").
- crates/tn-reth/src/env/execution.rs:555-559 (failed persist -> clear_execution_cache; "the blocks are rebuilt or the node stops").
- crates/tn-lmdb/README.md:1602-1603 ("A long-lived reader only holds back page reuse, so the file grows instead").
- MDBX pinned reader page cost no effect above about 7 %: bench6-r20261112-1520/A7/verdicts.md:281.
- #1804 spread: R §4.6 :462 ("it lowers each engine's cost, which may widen or narrow the spread that broke certification"); §4.3 :368-369.

## Title
- 110 characters. "in series" is read from M's code (inferred, not measured on M). The "third" is in the body, attributed to bench 6's build.

## Left out
- 27-35 % sequential counterfactual (P1 :99-102): uncontrolled; left out for length.
- persist-bound cycle bench speedups 1.287 / 1.345: forced 182 ms sleep in each persist, not a disk measurement.

## Revision 2 (2026-11-14, figure-check tasks/bench7/figcheck-UI3W.md applied)
Changed sentences and their sources:
- Problem, "... the next benchmark is to run main at 20,000 IOPS, and this issue will be updated with its split, though a run at 50,000 IOPS is what item 1 below needs.": figcheck Weak, line 10 (at 20,000 IOPS the disk bound bench 6, 0.998 of the limit; item 1 is about 50,000); "runs" -> "is to run" (a plan, as figcheck Weak for the write-up's line 23).
- Problem, "... whose parallel roots and output overlay assume it does not, and whose execution cache is cleared on a failed persist on the premise that the next build has not started.": figcheck error 2 replacement, verbatim (parallel.rs:62-81, :74; output_overlay.rs:73-75; exec_cache.rs:30, :38-50; execution.rs:556-557).
- Evidence, "One run per configuration." (dropped "Figures cover the 40-minute load blast, nine validators pooled;", now in the table header): figcheck Weak, table header.
- Evidence, "In every run no task began before the previous one ended.": wording only (sources unchanged: E2 :49-53; E3 :321).
- Table header cell "over the 40-minute blast, nine validators"; row labels "execute, µs/tx", "persist (save_blocks + commit), µs/tx", "task, with announce, µs/tx": figcheck Weak, lines 19-27. Cells unchanged.
- Evidence, validator-01 bullet: dropped "the cheapest engine idled 50 ms/s" (cut for length; E2 :17 unchanged).
- Evidence, "In the arm walk r20261112-1520 (one fleet stepped through nine switch sets by rolling restart, 20,000 IOPS, no run page) ... but the disk bound, and the pipeline's own arm regressed in throughput, through outputs half the size of the arm before; ...": figcheck Weak, line 36 (arm-walk wording; "regressed" per A7/verdicts.md:277, :288-292; half-size outputs per A7/final-arm-options.md:71).
- Evidence, quiet host: "On a quiet host with a lab database, whose build cost about 30 µs/tx, the build took 6 to 8 µs/tx longer pipelined than in sequence (1.22 to 1.26 times), and with execute the longer phase the overlap gained 10 to 11 % (one run on each of two CPU shapes, the two engines run one after the other).": figcheck Weak, line 37, verbatim (figcheck "Settled points": execute_stretch 1.257 / 1.219 and speedup 1.100 / 1.108 in st-u12c/cycle-pinned.txt and cycle-unpinned.txt line 5; build 64-70 ms per 2,200-tx output = about 29-32 us/tx; stretch 18 and 14-15 ms per output = about 8 and 6.5 us/tx; B6 crates/engine/tests/it/persist_pipeline.rs:1630-1665, :2120-2145).
- Evidence, "It never ran at 50,000 IOPS." (dropped "and it does not carry to main"): cut for length; the Problem's last sentence and "Where in the code" carry the reason.
- Where in the code, engine bullet: dropped "up to 8 outputs wait behind it (`MAX_QUEUED_OUTPUTS`, `:61`)" (cut for length).
- Where in the code, "The parallel roots and the output overlay rely on that order." (was "Storage v2 relies on that order."): figcheck error 2.
- Where in the code, "The execution cache's failure rule assumes the next build has not started: a failed persist clears the cache, "so start the next build empty" (`crates/tn-reth/src/env/execution.rs:555-559`).": figcheck error 1/2 (execution.rs:556-557 is the quoted comment, inside the cited 555-559).
