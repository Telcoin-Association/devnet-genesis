# Figure-check FC-3: s4b.md (§4.5-4.8) and s6.md (§6)

## Counts

| subsection | figures checked | match | wrong | untraceable | weak |
|---|---:|---:|---:|---:|---:|
| §4.5 far validators' batches (s4b.md 1-44) | 97 | 94 | 1 | 0 | 2 |
| §4.6 epoch records, closing-block check (s4b.md 46-71) | 49 | 46 | 0 | 0 | 3 |
| §4.7 recovery after the kill (s4b.md 73-93) | 48 | 47 | 0 | 0 | 1 |
| §4.8 census (s4b.md 95-101) | 15 | 12 | 2 | 0 | 1 |
| §6 open questions (s6.md 1-37) | 30 | 24 | 1 | 0 | 5 |
| total | 239 | 223 | 4 | 0 | 12 |

Every line of both files was checked; no line is left unchecked.

## Wrong

1. s4b.md:7. Text: "seen p50 16.6-18.2 s against 4.10-5.08 s".
   File: run 7b validator-02 in blast 1 = 16650 ms exactly (C `q3_far_validators.rows` Q3F.12 `b7b.02`; V `far_generators_b6.answer_by_blast.1.far_seen_p50_s.7b.02` = 16.65); half-up gives 16.7, and analysis-decisions.md line 33 reads "16.7-18.2 s".
   Replacement: "seen p50 16.7-18.2 s against 4.10-5.08 s".
   The table at s4b.md:16 uses the same half-even rounding twice (run 7a validator-06 landed 5.475 printed "5.47"; bench 6 run 3 near median 88.85 printed "(88.8)"; half-up: 5.48 and 88.9): one convention for the whole report is the orchestrator's call.
2. s4b.md:98. Text: "The bare words "panic", "halt", "fork" and "fatal" do occur, inside digests and in info templates such as `node switches`, not as failures".
   File: "fatal" never occurs inside a digest; it occurs only as text, in the error template `fatal request for requested vote` (33 lines in run 7a, 152 in run 7b) and in run 7b once in the warn template `skipping protocol penalty for committee peer (field penalty=Fatal)`; "fork" occurs inside digests and in the fork-schedule banner (24); "halt" in `node switches` (24) and inside digests; "panic" inside digests only (both runs' `census.json` `words.<node>.<word>.where` / `in_text_templates`; `fail_stops.fatal_in_text` = 33 / 153).
   Replacement: "The bare words "panic", "halt" and "fork" occur inside digests, in the `node switches` info line and in the fork-schedule banner; "fatal" occurs only in the error template `fatal request for requested vote` (33 lines in run 7a, 152 in run 7b) and once in run 7b in a warn line naming `penalty=Fatal`; none of these is a fail-stop phrase of the census [7a A4 census words] [7b A4 census words]."
3. s4b.md:100. Text: "...; and in run 7b the spawn-capacity errors of §4.7 [7a A4 census flagged] [7b A4 census flagged, leads.spawn_capacity]" (listed among "the error templates new against bench 6").
   File: the spawn-capacity family is not new: bench 6's run 2, the census's reference, logged 1,421 such lines (7b `census.json` `leads.spawn_capacity.bench6_run2_census`, e.g. `VoteRequest` 394), and run 7a's validator-05 logged 1,347 (`leads.spawn_capacity.run7a_census`, 7 task names); run 7a's `flagged` holds none of them; in run 7b `flagged` (`new_vs_run2` = true) holds only three task names: `next-batch` 20 lines, `ProcessGossip-tn-epoch-vote` 2, `sync-batches` 2.
   Replacement: "...; and in run 7b three task names of the spawn-capacity error (`next-batch` 20 lines, `ProcessGossip-tn-epoch-vote` 2, `sync-batches` 2); the spawn-capacity error itself is not new: bench 6's run 2 logged 1,421 such lines and run 7a's validator-05 1,347 [7a A4 census flagged] [7b A4 census flagged, leads.spawn_capacity.bench6_run2_census, leads.spawn_capacity.run7a_census]."
4. s6.md:26. Text: "[V q7_statements 4.6 line 60]".
   File: the statement "At 50,000 IOPS the engine's sequential cycle sets the ceiling." is `q7_statements.statements` entry with `section` "1.", `line` 60 (V); no entry has section 4.6. The figures (978.1 / 978.4 ms/s; 0.8591 / 0.8628 of the cap) match. s6.sources.md line 17 carries the same wrong section.
   Replacement: "[V q7_statements 1. line 60]".

## Untraceable

None.

## Weak

1. s4b.md:36. Text: "The code is the same on both builds: `crates/consensus/primary/src/proposer.rs:942` at 2df831e3c and `:999` at 91a15e223 (the `take_while`), ...".
   File: the cited lines hold what the text says (proposer.rs:942 at 2df831e3c and :999 at 91a15e223 are the same `take_while(|(header_round, _)| **header_round <= max_committed_round)`; state.rs:809-812 is `if has_headers { committed_own_headers().send((leader_commit_round, own_rounds_committed)) }` on both, lines 760-830 identical), but the function is not the same: at 91a15e223 the same walk adds `stale_resend` bookkeeping (proposer.rs:1001-1003), V `q3_far_validators.code_reading` row 3 (`same`: false).
   Replacement: "The trigger and the walk are the same on both builds: ..." (rest unchanged).
2. s4b.md:41. Text: "while each miss costs the same re-queue delay in rounds".
   File: V `q3_far_validators.reading` (B1, what moved little): "the re-queue's delay in rounds (41-58 in bench 6 against 50-61 in bench 7, overlapping; in seconds 14.3-20.3 against 21.1-21.4 in run 7b, at bench 6's top end and just above it)"; `differences` B1 `requeue_s_p50` `differs`: true.
   Replacement: "while the re-queue's delay in rounds overlaps (41-58 rounds in bench 6, 50-61 in bench 7) [V q3_far_validators B1.requeue_rounds_p50, reading]."
3. s4b.md:49. Text: "...with a conflict-halt switch (`epoch_record_conflict_halt`, on in both arms [RF 7a] [RF 7b]) that the later form drops."
   File: "on in both arms" matches run-facts.md line 9 of both runs; "the later form drops" has no cite; it is in tasks/pr-bodies/bench6-04-collector-hardening.md line 41 ("Dropped from this change's earlier form: the switch `epoch_record_conflict_halt` with its threshold ...") and tasks/plan.md line 89 (the stack on main "without `epoch_record_conflict_halt`"; line 92: the harness drops it with the next image).
   Replacement: "...with a conflict-halt switch (`epoch_record_conflict_halt`, on in both arms [RF 7a] [RF 7b]) that the later form drops [PR 04 body line 41; plan line 89]." (the appendix resolves the two cites to tasks/pr-bodies/bench6-04-collector-hardening.md and tasks/plan.md).
4. s4b.md:54. Text: "Signers on the quorum lines and seconds to the first quorum, one close per cell, one run each".
   File: the idle row is a min-max over several closes (V `q3_epoch_records.pairs.*.rows[6]`, "idle closes: seconds to the first quorum, min-max").
   Replacement: "Signers on the quorum lines and seconds to the first quorum, one run each; one close per cell except the idle row, which gives the range over the run's idle closes [V q3_epoch_records pairs]:"
5. s4b.md:58. Text: run 7b cell "1.39-1.94".
   File: the 1.39 is epoch 6's close (7b `closes.json` `closes[6].first_quorum_s` = 1.39, `window` "idle (no blast running); after the export's last sample", 8 publishing nodes); inside the export run 7b's idle closes read 1.67-1.94; rule 6 asks the outside-the-export close to be named beside the figure.
   Replacement cell: "1.39-1.94 (1.39: epoch 6, after the export, eight nodes' logs)".
6. s4b.md:93. Text: "validator-05 has the same template after its start (993 lines in run 7b) [7b A4 census leads.spawn_capacity.by_node.v05]".
   File: run 7a's validator-05 has it too, 1,347 lines over 7 task names (7b `census.json` `leads.spawn_capacity.run7a_census`, sum of `total`; all `by_node` v05); analysis-decisions.md line 26: "validator-05 has the same template in both runs".
   Replacement: "validator-05 has the same template after its start in both runs (1,347 lines in run 7a, 993 in run 7b) [7b A4 census leads.spawn_capacity.by_node.v05, leads.spawn_capacity.run7a_census]."
7. s4b.md:100. Text: "The error templates new against bench 6: ...".
   File: both runs' `census.json` `reference` is one bench 6 run, r20261113-1351 (bench 6's run 2, `benchmark/private/bench6-r20261113-1351/A3b/census.json`), also for run 7b, whose bench 6 counterpart elsewhere in the report is run 3; the flag is `new_vs_run2`.
   Replacement: "The error templates new against bench 6's run 2 (the census's one reference, for both runs): ..."
8. s6.md:21. Text: "Both moved together in both bench 7 runs, so the fall in certification and the hold's cost are not separable between them (§4.2, §4.3)."
   File: s4a.md:142 and V name more than the two: the certification share is not separable between the "vote-handler rework (refusal rule and timing), the execution lag at the voters (rate x1.75, larger outputs, the storage engine's persist time), the hold ...".
   Replacement: "Both moved together in both bench 7 runs, with the voters' execution lag on the new storage engine, so the fall in certification and the hold's cost are not separable between them (§4.2, §4.3)."
9. s6.md:24. Text: "The review proposed a field for the un-held count on the header line; with it, a run would count them."
   File: holds, but uncited: tasks/bench7/review/06-digest-order-hold-report.md line 318 ("Add the count to the `header proposed` line (`pending_unheld`)."); both runs' `A7/losses.json` `early_trigger.read.field_for_reading_B`: "pending_unheld (not on the line); here pending_before - held stands in for it".
   Replacement: "The review proposed a field for the un-held count on the `header proposed` line (`pending_unheld`) [review 06 line 318] [7a A7 early_trigger]; with it, a run would count them."
10. s6.md:28. Text: "A run at 50,000 IOPS on this build answers both."
   File: V `q7_statements` (section 4.3, line 386, "every faster configuration ... widens that spread"): `verdict` "cannot test" because "no per-engine execution spread across the benches in these keys"; every node ran tn-lmdb (both `census.json` `arm_store.store_by_node_arms`), so a 50,000 IOPS run on this build alone gives no engines' spread.
   Replacement: "A run at 50,000 IOPS on this build answers the first; the second also needs the engines measured side by side on the same configurations."
11. s6.md:36. Text: "The conflict evidence, the re-certify round and the walk past an uncertified epoch were on in both runs and never fired (§4.6)."
   File: the arm's switches are `epoch_record_conflict_halt`, `epoch_record_recertify`, `epoch_record_collect_past_uncertified` (run-facts.md line 9, both runs); the conflict evidence line has no switch (tasks/pr-bodies/bench6-04-collector-hardening.md line 4).
   Replacement: "The conflict halt (`epoch_record_conflict_halt`), the re-certify round (`epoch_record_recertify`) and the walk past an uncertified epoch (`epoch_record_collect_past_uncertified`) were on in both runs and never fired (§4.6)."
12. s6.md:37. Text: "The e2e tests cover them; the fleet did not, ...".
   File: tasks/pr-bodies/bench6-04-collector-hardening.md lines 63-64: the e2e file `epoch_record_walk.rs` covers the walk and the re-certify round with withheld votes, and "no node logs or counts a conflict"; line 41: the later form drops the conflict-halt switch.
   Replacement: "The e2e tests cover the walk and the re-certify round with withheld votes and no conflict; none drives a conflicting record, and the later form drops the conflict-halt switch; a fleet run that injects a conflicting record or withholds a record's certificate would exercise these paths under load."
