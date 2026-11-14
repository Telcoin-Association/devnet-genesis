# Figure-check FC-UI3W: the not-carried write-up and two new issue bodies

Checked 2026-11-14 against the report, the run-1, run-2 and run-3 analysis files, the bench-6 plan archive, the quiet-host scratch outputs, the review and followups files, and the code: main at 45dce8947 (telcoin-network-b7, HEAD verified) and the bench-6 build at 2df831e3c (telcoin-network-b6).
Every `path:line` the three texts cite on main was opened at 45dce8947.

## Verdict

Write-up `tasks/bench6-not-carried-writeup.md`: FIX.
Issue `tasks/issue-bodies/bench6-execute-and-persist-in-series.md`: FIX.
Issue `tasks/issue-bodies/bench6-inflight-bound-measurements.md`: FIX.
No error changes a conclusion: every "does not carry" argument stands on the parts of the code that do say it, and every table figure matches its source.

## Errors

1. Write-up, "Pipelined persist", line 52, "#1834's parallel storage roots, output overlay and execution cache assume that no persist overlaps the next build".
   The roots and the overlay say so (`crates/tn-reth/src/env/output_overlay/parallel.rs:62-81`, `:74`; `crates/tn-reth/src/env/output_overlay.rs:73-75`).
   The execution cache does not: its invariant is keyed by block hash "not by the persisted tip" (`crates/tn-reth/src/env/exec_cache.rs:30`), and its "What would break it" list (`:38-50`) names no overlapping persist.
   Only its failed-persist rule presumes the next build has not started (`crates/tn-reth/src/env/execution.rs:556-557`, "so start the next build empty").
   Replacement: "It does not carry because #1834's parallel storage roots and output overlay assume that no persist overlaps the next build, and its execution cache's failure rule assumes the next build has not started."
2. Execute-and-persist issue, "Problem", line 11, "on storage v2, whose roots, overlay and cache assume it does not."
   Same over-reach as error 1, same sources.
   Replacement: "on storage v2, whose parallel roots and output overlay assume it does not, and whose execution cache is cleared on a failed persist on the premise that the next build has not started."
3. In-flight bound issue, "Evidence", line 42, "how the bound shapes outputs was not measured."
   The source the paragraph itself rests on says the cycle is a mechanism: "That part is a mechanism (the gate rule in code, the output-by-output sequence in the data); the timing of each opening against the generators' retries is not joined, because the node logs no gate transition" (`benchmark/private/bench6-r20261112-1520/I-8/findings.md:147`), and the report adopts that explanation (`tasks/bench6-report-r20261113-1351.md:493`).
   The "not measured by any unit" wording is the earlier arm verdict (`benchmark/private/bench6-r20261112-1520/A7/verdicts.md:327`), which that later unit answered.
   Replacement: "That is an unplanned group commit, not the bound's purpose; the cycle is read from the gate rule in the code and from the outputs in sequence, but the timing of each opening against the senders' retries was not joined, since the node logs no gate transition."
4. In-flight bound issue, "Evidence", table header "| 600 × 16 senders |" (and line 16 "closed-loop generators with 6,000 senders").
   600 × 16 is 600 senders per generator × a window of 16 transactions in flight per sender, ten generators, 6,000 senders (`tasks/bench6-report-r20261113-1351.md:171`; `benchmark/private/bench6-r20261112-1520/A7/verdicts.md:305`); the header reads as 9,600 senders.
   Replacement for line 16: "Arm walk r20261112-1520 (one fleet stepped through nine switch sets by rolling restart; no run page): ten validators, 20,000 provisioned IOPS, ten closed-loop generators of 600 senders each; a blast is named by senders per generator × the window each sender keeps in flight (600 × 16, 600 × 4)."
   Replacement for the header cell: "| 600 × 16 |".

## Not traceable

None.
Every figure in the three texts was found in an allowed source, with the same run, window and unit.

## Weak

Write-up:
- Line 15, "The observer, the one node not restarted": only the first arm's apply left it running; it was restarted at the next arm and then wrote 1.06 times (report :335-337).
  Suggested: "The observer, the one node the first arm did not restart, wrote 6.5 to 10.9 times its page bytes".
- Line 23, "the next benchmark, on main, measures them at 20,000 IOPS": a plan stated as a fact.
  Suggested: "the next benchmark, on main, is to measure them at 20,000 IOPS."
- Line 31, "#1834 made the same comparison unconditional": true as "no switch", but the guard compares nothing when the closing block is at or below the datadir's restored-state floor (`crates/node/src/manager/node/close_epoch.rs:721-731`, `:1271`).
  Acceptable as written; if words allow, "with no switch".
- Line 48, "the commit carried the whole device write time ... against 354.9 measured": 354.9 µs/tx is the whole pipelined persist, save_blocks plus commit (A4e `execute.md:34`, verdicts.md:278); A4p measured 345, of which the commit 298.6 (A4p `persist.md:123`).
  Suggested: "the persist carried the whole device write time".
- Line 46, "On a quiet host the interval per output was 0.991 to 1.030 times the longer of execute and persist": two of the four runs (1.004, 1.003) were persist-bound only through a forced 182 ms sleep in every persist (`benchmark/work/bench6-scratch/st-u12c/cycle-*-persist-bound.txt` line 5).
  Acceptable as a gate result.
- Line 19, "main runs MDBX only under the off-by-default `mdbx` feature": the default build still opens an MDBX database to migrate it (`crates/tn-reth/Cargo.toml:159-160`).
  Suggested: "main runs its execution database on MDBX only under ...".
- Lines 48-49, "at 600 × 16" is used without saying what it is; see error 4.
- Word count is about 895 against the 900 ceiling: the replacements above should be net-neutral.

Execute-and-persist issue:
- Line 37, the quiet-host figure, see the section below: publishable only with what it measures.
  Suggested: "On a quiet host with a lab database, whose build cost about 30 µs/tx, the build took 6 to 8 µs/tx longer pipelined than in sequence (1.22 to 1.26 times), and with execute the longer phase the overlap gained 10 to 11 % (one run on each of two CPU shapes, the two engines run one after the other)."
- Line 36, "In the arm walk r20261112-1520 (20,000 IOPS, no run page)": "arm walk" is not explained in this issue.
  Suggested: "In the arm walk r20261112-1520 (one fleet stepped through nine switch sets by rolling restart, 20,000 IOPS, no run page)".
- Line 36, "its cycle was 1.010 to 1.072 times the longer stage": the range spans the three arms that ran the pipeline (medians 1.010-1.017 in its own arm, 1.060-1.072 in the two later ones, `benchmark/private/bench6-r20261112-1520/A4e/pipelined.md:43-49`); the write-up gives 1.010 for its own arm at 600 × 16.
  Both are true; the issue may add "(1.010 in its own arm at 600 × 16)".
- Line 36, "throughput did not rise": the source says the pipelined arm regressed, 2,562 landed tx/s against 3,186 in the arm before, through outputs 46 % smaller (verdicts.md:277, :288).
  Not wrong, softer than the source.
- Lines 19-27, the table's first header cell "per executed transaction, µs" also heads rows that are not µs per transaction (transactions per output, tx/s, ms/s, share of the limit).
  Suggested: header cell "over the 40-minute blast, nine validators", and row labels "execute, µs/tx", "persist (save_blocks + commit), µs/tx", "task, with announce, µs/tx".
- Line 10, "the next benchmark runs main at 20,000 IOPS, and this issue will be updated with its split": at 20,000 IOPS the disk bound bench 6 (0.998 of the limit), so that split alone does not settle "What to discuss" item 1, which is about 50,000 IOPS.
  Suggested to add: "a run at 50,000 IOPS is what item 1 needs."
- Line 7, "the fleet ran at its costliest engine's sequential capacity": shown for r20261113-1630 (`benchmark/private/bench6-r20261113-1351/A4e/engine.md:14`); in r20261114-0000 the engines waited for input part of the time (queue at the cap in 17 % of samples, `benchmark/private/bench6-r20261113-2118/A4e/engine.md:285`).
  The bullet at line 29 anchors it to r20261113-1630; acceptable.

In-flight bound issue:
- Line 5, "a validator's RPC admits a raw transaction however far its execution is behind": a validator in `CvvInactive` mode refuses with −32603 "validator is inactive; retry another endpoint" (`crates/tn-reth/src/rpc_fee_cap.rs:57-78`).
  Suggested: "On main at 45dce8947 an active validator's RPC admits a raw transaction however far its execution is behind."
- Line 7, "pushes back into consensus, never to the RPC": main's doc says the backpressure goes "into the `to_engine` channel (and ultimately the EpochManager forwarder)" (`crates/engine/src/lib.rs:57-59`; `crates/node/src/manager/node.rs:89-90`).
  Suggested: "and pushes back to the epoch manager's forwarder, never to the RPC."
- The control arm: `pipe` is the right control by the walk's own reading rule (each arm read only against the arm before it, report :466; switches differ only by the bound, report :137-138), and the text names the colder cache and the larger database.
  But `pipe` was the slowest 600 × 16 of the walk (`benchmark/private/bench6-r20261112-1520/A7/final-arm-options.md:71`), 2,562 landed tx/s against 3,186 in the arm before and 6,165 in the opening control (`A1/bound-fields.md:15`), so "+60 %" starts from a low base.
  Suggested to add after line 18: "`pipe` was the walk's slowest 600 × 16, its outputs small through page cost, so the gain is measured from a low base."
- Line 36, "It also refused in the warm-up (467,765 calls) and during one generator's account setup": the warm-up figure is the 600 × 16 blast, the account-setup refusals the 600 × 4 one (`A1/bound-fields.md:17`, `:41`).
  Acceptable.
- Title, "so under load transactions queue behind the engine, not at the sender": the queueing is measured on bench 6's build (channel and engine queue wait 34,624 ms p50) and inferred for main from the same queue structure (`crates/engine/src/lib.rs:61`, `crates/node/src/manager/node.rs:91`); the body says so at line 8.
  Acceptable.

## Settled points the prompt named

The three "does not carry" arguments, on main at 45dce8947:
- MDBX advice: true. `mdbx = []` is off by default with the comment at `crates/tn-reth/Cargo.toml:157-161`; `readahead` doc at `crates/tn-lmdb/src/env.rs:309-317` ("With `false` every mapping of the file is advised `MADV_RANDOM`"), default `!cfg!(target_os = "linux")` at `:397`; the node's options take `..EnvOptions::default()` at `crates/tn-lmdb-reth/src/env.rs:311-325`, opened at `:542`; the advice itself is applied in `crates/tn-lmdb/src/file.rs:856`.
- Stored-record check: true. `check_stored_record` is `close_epoch.rs:712-749`, came in with #1834 (af0f1ccae, `git log -S`), has no switch, counts `tn_epoch.final_state_mismatches_total` (`crates/node/src/metrics.rs:14`, `:24`) at `:734` and returns the error that stops the node; it runs on the stored-record path at `:432` and at every epoch entry at `:590` (called from `run_epoch.rs:238`); the build path samples the closing block at `:411` and saves at `:514` with no comparison.
- Pipelined persist: true for the roots and the overlay (`parallel.rs:62-81`, the "pipelined persist" line at `:74`, own transaction per task at `:18-19`; `output_overlay.rs:73-75`); over-stated for the execution cache (errors 1 and 2).

The quiet-host figure "the build ran 1.22-1.26× as long pipelined":
- Found: `execute_stretch=1.257` in `benchmark/work/bench6-scratch/st-u12c/cycle-pinned.txt` and `1.219` in `cycle-unpinned.txt` (line 5 of each), the two execute-bound runs without a forced persist delay, as the runbook says to read it (`tasks/bench6/quiet-host-runbook.md:28-29`); the 10-11 % is `speedup=1.100` and `1.108` in the same lines.
- What it measures: the median build lap of a pipelined engine over the median build lap of a sequential engine, whole milliseconds, in one release test (`crates/engine/tests/it/persist_pipeline.rs:1630-1665`, `:2120-2145` at 2df831e3c); the two engines ran one after the other on separate databases from one genesis, the pipelined one first; 35 measured outputs of 10 blocks and 2,200 transactions each; "pinned" in the file names means CPU pinning to 8 hardware threads (`taskset`), not the pinned reader, and the unpinned run had 16.
- In µs/tx the stretch is 18 ms and 14-15 ms per 2,200-transaction output, about 8 and 6.5 µs/tx, inside the arm walk's 3-14 µs/tx; the ratio is large because the lab build costs about 29-32 µs/tx (64-70 ms per output), against 87-131 µs/tx on the fleet.
- What it does not separate: the seeded overlay read, CPU beside the concurrent commit, and run order; one invocation per CPU shape.
- Sound to publish only with that context; as written, a 22-26 % build slowdown next to the fleet's 3-14 µs/tx reads as a production cost it is not (suggested wording under Weak).

The execute/persist split table: every cell matches.
- r20261113-1351: blast 2, 15:16:49-15:56:49Z, nine validators pooled (validator-05 apart): 90.2; 95.2 (20.9 + 74.2); 187.2; 3,854 transactions per output over all outputs (3,879 non-empty); 5,314 tx/s per node; 994 ms/s busy from the log (`benchmark/private/bench6-r20261113-1351/A4e/engine.md:63`); device 0.998 (report :27, :311).
- r20261113-1630: blast 2, 17:56:19-18:36:19Z, same pooling: 87.7; 44.5 (21.9 + 22.4); 133.9; 5,781 (5,790 non-empty); 7,287; 975 (engine.md:66); device 0.497 (report :27, :313).
- r20261114-0000: blast 2, 02:13-02:53Z, same pooling: 89.6; 42.5 (20.9 + 21.5); 133.8; 6,234 (6,313 non-empty); 7,210; 965 (`benchmark/private/bench6-r20261113-2118/A4e/engine.md:287`, `:329`); device 0.480 (report :740).
- Unit: µs per executed transaction of the non-empty outputs in the window (engine.md "Per-transaction figures").
- MDBX and layout v1 stated plainly at lines 9-10; bench 6 pins layout v1 (`crates/tn-reth/src/env/mod.rs:792-809` at 2df831e3c) and runs MDBX; the re-measure on main is stated without a promised result.
- Main's engine at the cited lines: `run` at `crates/engine/src/lib.rs:279`, spawn only when `pending_task.is_none()` at `:304-311`, `MAX_QUEUED_OUTPUTS = 8` at `:61`; persist in line at `crates/engine/src/payload_builder.rs:392-413` (`persist_output_with_retry` at `:401`), announce and finalize `:414-422`, `output executed` with `execute_ms`, `persist_ms`, `announce_ms` at `:427-445`.

The in-flight bound issue:
- `bound` against `pipe` at 600 × 16 (blast 12 against blast 10): 4,093 against 2,562 landed tx/s; 42.3 % of 3,373,473 mixed-phase send calls refused; 2,336 given up; all from `benchmark/private/bench6-r20261112-1520/A1/bound-fields.md:15`, `:17`; at 600 × 4 (blast 11 against 9): 2,590 against 2,127, 57.6 % of 2,297,032, 10,110 given up (`:14`, `:16`).
- Every other row matches: seen 36.66/63.90 against 10.19/25.09 s; window share 98.6 % against 27.5 %; lag 81-84 against 20-24 rounds; channel and queue wait 34,624 against 4,268 ms; pool wait 129 against 1,900 ms and accept p95 37 against 3,198 ms (verdicts.md:284, :319, :321); busy 957 against 995 ms/s and queue at cap 59 % against 97 % (`:320`); faults 171 against 27 per second and the database 6.07 against 4.96 GiB, +22 % (`:303-304`); in flight 44.5 % against 102.0 % (bound-fields.md:15, :17); 1,423,641 retries; 467,765 warm-up refusals.
- The control is right by the walk's rule (see Weak); one run.
- "An unplanned group commit": the source's own words ("the gate acts as an unplanned group commit", I-8 `findings.md:17`; report :493), and "accounts for the whole gain" is verdicts.md:326 (19,275 ÷ 4.71 = 4,092 against 4,093 measured); the strength matches. The 57 % is I-8's fleet-median figure (`:144`); A4e's pooled count is 3,640 of 6,479, 56 %.
- Review findings on main: M1 holds (`crates/tn-reth/src/forward.rs:1112-1126` the held-rejection rule, `:155-162` −32003 transient, `:808-811` removal with no requeue; `crates/tn-reth/src/worker.rs:168-172` answers −32000 "worker is inactive", which is not in `NODE_LOCAL_MESSAGES` at `forward.rs:205-218`); L1 holds (`forward.rs:939-959`, only `added` is counted; `forward_pending.rs:298-313` removes the entry uncounted); L3 holds (`crates/tn-reth/src/rpc_tx_forward/client.rs:4-5`, `:218-229`); L4 is a property of any fee-blind gate, as the text says.
- "Unchanged on main" is exact: `forward.rs`, `forward_pending.rs`, `worker.rs` and `rpc_tx_forward/client.rs` are byte-identical between 2df831e3c and 45dce8947 (`git diff --stat` empty).
- Nothing on main bounds admission by backlog: the guard at `crates/tn-reth/src/rpc_fee_cap.rs:216-225`; the only −32003 producers in `crates/` are tests and the forwarder's classification.

Titles:
- Execute-and-persist: 110 characters, ASCII; "execute and persist run in series" is true at 45dce8947 (above); the consequence is inferred and conditional on the engine binding, which the body attributes to bench 6's build.
- In-flight bound: 114 characters, ASCII; "RPC admission ignores the execution backlog" is true at 45dce8947; the queueing consequence is bench 6's measurement (see Weak).

The arm walk r20261112-1520 (no public page):
- Write-up: understandable ("the arm walk r20261112-1520 (nine switch sets by rolling restart, no run page)").
- Execute-and-persist issue: not explained ("(20,000 IOPS, no run page)"); replacement under Weak.
- In-flight bound issue: only partly ("Arm walk r20261112-1520 (no run page)", with "the arm before it" left to context); replacement in error 4.

Placeholders:
- Write-up: `{{epoch-record-closing-block-check}}` (line 37), `{{execute-and-persist-in-series}}` (line 56).
- Execute-and-persist issue: none.
- In-flight bound issue: `{{execute-and-persist-in-series}}` (line 58).

Cross-text: the same quantities read the same everywhere (persist a third of the cycle; 3-14 µs/tx, an upper estimate; never at 50,000 IOPS; 1.010 at 600 × 16 inside the issue's 1.010-1.072); errors 1 and 2 are one over-reach in two places and must be fixed together.

## Rule breaches

None: no unit names, no private paths, no host or person names, no run nicknames, no tool or assistant attribution (scanned all three texts).
Word counts without table pipes: write-up about 893, execute-and-persist 885, in-flight bound 877, each inside its range.

## Counts

Write-up: 67 figures and claims checked, 66 matched, 1 wrong, 0 untraceable.
Execute-and-persist issue: 66 checked, 65 matched, 1 wrong, 0 untraceable.
In-flight bound issue: 62 checked, 60 matched, 2 wrong (one a mislabel), 0 untraceable.
