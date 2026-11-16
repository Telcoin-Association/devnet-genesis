# RV-1a: review of the walk switch's removal (R1, first commit)

Commit: `tn-b8-uc` 500e21afa..a5be61615, `refactor(state-sync): the record collector always walks past its own uncertified epoch`. Seven files, +107 / -306. Read with `git diff -w`, file by file; `may_walk_past` compared body against body. Line numbers below are at a5be61615 unless marked "base". No cargo command was run; the writer's gate logs were read (see the end).

## Verdict

**Approve with follow-ups.** Nothing of the off arm is left in code, no statement on a kept path changed, and no test of the kept behaviour was deleted or weakened. Two Low items, both cosmetic: one e2e comment still says "with the walk on", and a few doc lines were left short after their switch clause was cut.

Counts: Critical 0, High 0, Medium 0, Low 2.

## The four questions

1. **Is anything of the off arm left?** No. `git grep -n -w` at a5be61615 over the whole tree for `epoch_record_collect_past_uncertified`, `EpochRecordCollectSwitches`, `past_uncertified`, `walk_off`, `Arm::Gap`, `uncertified_epoch_gap` and the two deleted test names returns nothing. All of these are gone: the struct and its `From<&Parameters>` (base epoch.rs:102-115), the `switches` field and the `Collection::new` argument (epoch.rs:121-126), the gate at the top of `may_walk_past` (base :170-172), the test helpers `WALK` and `walk_off()` (base :1803, :1816), `Arm::Gap` with its arms (e2e epoch_record_walk.rs, base :120-146, :384, :410-423, :532, :559, :645), and the field, default and `runtime_switches!` entry in config/src/node.rs (base :442-473, :628, :833).
2. **Did any statement on a kept path change?** No.
   - `may_walk_past` (epoch.rs:145-168): the only difference from base is the deleted `if !self.switches.past_uncertified { return false; }`. The unlanded-walk hold, the `MAX_UNCERTIFIED_GAPS` bound and the own-uncertified-record check (`Some((_, None)) => epoch > 0 || !epochs.contains_dummy_epoch0()`) are byte for byte as before. The parent check and the conflict stop in `collect_epoch_records` (:607-622) and `Collection::refused` are untouched; the only change near them is the comment at :616-617.
   - The other non-test hunks are plumbing: the `use tn_config::Parameters` import, the struct, the field and constructor, `sync_epoch_records_to_tip` (:347-361) and `spawn_epoch_record_collector` (:845-860), their `_with` twins (lost `switches`), the two `Collection::new(metrics)` calls (:~385, :890), and doc text. The public signatures now match main 0554efd4f (epoch.rs:94-99 and :405-411 there): the same five or four arguments, in the same order and with the same types. manager/node.rs (base :1383, :1403) only drops the `&self.builder.tn_config.parameters` argument.
   - Logs and metrics: the diff adds or removes no `info!`/`warn!`/`increment` line. The literal counts are equal at base and tip across `crates/state-sync/src` and `crates/node/src`: `epoch record collector walking past an uncertified epoch` 2/2 (fields `epoch`, `gaps = self.gaps.len()`, :176-180), `epoch record conflict:` 4/4, `epoch_record_gap_walks_total` 4/4, `epoch_record_walk_parent_mismatches_total` 4/4, `epoch_record_conflicts_total` 6/6, `final_state_mismatches_total` 11/11.
3. **Was a test of the kept behaviour deleted or weakened?** No.
   - Deleted `test_collect_epoch_records_stops_at_an_uncertified_epoch_with_the_walk_off` (base :1938-1956) tested only the off arm: stop at 0 on two passes, no gap, epoch 2 not stored. Every one of those assertions holds only with the walk off. The kept stops are still covered: no own record by `test_collect_epoch_records_does_not_walk_past_a_missing_record`, the gap bound by `…_bounds_the_open_gaps`, a parent mismatch by `…_stops_at_a_parent_mismatch_after_a_walk`, and a walk that did not land by `test_a_walk_that_does_not_land_waits_a_retry_interval`.
   - Deleted e2e `test_uncertified_epoch_stops_the_collector_with_every_switch_off` (base :176-195, with the `Arm::Gap` branches) tested only the off arm: observers stop at K, no node walks, the gauge reads `K - 1`. What still applies with the walk is still asserted in the `Walk` arm: the fresh observer holds none of `K..=K+2` (:397), the fresh observer and the own-record observer's first run log no walk (:491), and K is given up with no quorum (:516-527).
   - `…_counts_and_stops_on_a_conflicting_certified_record` (:2105): the off/on loop became the on case. `counters()` returns the increments since the previous snapshot (the base loop asserted `Some(&1)` on both iterations, which only passes with per-snapshot increments), so `Some(&1)` at :2128 is the same assertion for the case that stays. The gap-retry and collector halves are unchanged.
   - `test_startup_sync_walks_past_its_own_uncertified_epoch_and_stops_on_a_conflict` (:2166, renamed): `stored3.is_some() == walk` became `assert!(stored3.is_some())`, and the "diverged" check is unchanged. Each base iteration built a fresh chain, so dropping the `false` iteration changes nothing for the `true` one.
   - `test_every_conflict_reaches_the_final_state_mismatch_stop` (:2195): `Some(&2)` became `Some(&1)` for both counters. There is one snapshot after the loop, and the loop went from two runs of (one conflict + one `CertificateMismatch`) to one run, so the new value says the same thing: the conflict is counted once in each counter and the mismatch in neither. `refused()` never read the switch.
   - The conflict stop was never tested only in the deleted off case. It is still tested with the walk in the three tests above and in `…_stops_on_a_record_conflicting_with_our_own`, `test_conflict_and_invalid_record_lines_carry_the_evidence` and `test_a_conflict_cancelled_at_its_evidence_read_is_counted_once`. The e2e diff does not touch conflict coverage.
   - Fixtures that were `walk_off()` or `::default()` are now walking collections. Their meaning does not change: the walk is entered only on a definitive `Fetched::Missing` for an epoch this node holds as its own uncertified record (:633). The conflict, invalid-certificate and failed-store tests reach `Refused` or an error before that point. `test_record_collector_sets_certified_through` (own records 1 and 2 uncertified) can now walk, but it asserts only the gauge, which the walk does not move past the gap.
4. **Does any comment, doc or log text still speak of the switch?** One comment does (L1 below). Everything else was rewritten into present-tense behaviour: metrics.rs:48, the `Collection.gaps` doc, the `collect_epoch_records` doc (:539-549), close_forms `WALK_LOG` (:218-219), the walk e2e module doc and the `Arm` docs. The `Arm` and module docs still mention "record switch(es)" for `epoch_record_recertify`, which is correct at this commit because R1's second commit removes it.

## Findings

### Critical / High / Medium

None.

### Low

- **L1. A switch phrase is left in an e2e comment.** `crates/e2e-tests/tests/it/epoch_record_walk.rs:471`: `// the walks: with the walk on, each validator walks past K once (it holds its own record`. Change it to `// the walks: each validator walks past K once (…`. The second R1 commit is editing this file now and can fold the fix in.
- **L2. Doc lines were left short where a switch clause was cut.** The text is correct; it just needs rewrapping to the 100-column comment width. `epoch.rs:132` (`/// Only while fewer than [`MAX_UNCERTIFIED_GAPS`] gaps would`), `:539` (`/// A pass told by a peer that it`), and the test docs at `:1816`, `:1869`, `:1905`, `:2101`, `:2508`. rustfmt does not join short comment lines, so the fmt gate passed.

## Other checks

- The commit message claims that "a `parameters.yaml` that still names the key loads and ignores it". That is correct: `Parameters` derives `Deserialize` without `deny_unknown_fields` (config/src/node.rs:273-274), and `unknown_keys_are_ignored` (node.rs:1765) pins that behaviour. An operator's old `parameters.yaml` keeps working.
- The removed field doc in config/src/node.rs held the conflict-stop operator text. Its substance (the `epoch record conflict:` line, both counters, and the node stopping right after the count) is still in the `epoch_record_conflicts_total` doc at metrics.rs:57-64. The field's own description of the walk's bounds now lives only in the epoch.rs docs (`MAX_UNCERTIFIED_GAPS`, `retry_gaps`). That is enough for code; the PR body should repeat the bounds for operators.
- Commit message: conventional subject, prose body of 8 lines, `Refs #1850`, `Topic: remove-bench-switches` last, no figure, no private label, no attribution.
- Writer's gates, read but not re-run: `tn-b8-uc/target/tmp/r1-c1-{check,fmt2,clippy,nextest}.log` all show `EXIT=0`, and nextest ran `-p tn-config -p state-sync -p tn-node` with 508 passed and 1 skipped. That includes the three edited tests by name. The e2e tests were compiled, not run (the orchestrator runs them).
- state-sync `Cargo.toml` still depends on `tn-config`. That is right: main has it too, and `ConsensusConfig` and `NetworkConfig` still use it.

## Checked and fine, by file

- `crates/state-sync/src/epoch.rs`: plumbing and docs only on kept paths; `may_walk_past` differs from base by the gate alone; tests as in Q3.
- `crates/config/src/node.rs`: the field, its doc, the default and the `runtime_switches!` entry went, and nothing else; `NON_SWITCH_KEYS` and the machinery stay for R5.
- `crates/node/src/manager/node.rs`: two argument removals.
- `crates/state-sync/src/metrics.rs`: one doc sentence dropped; the metric name is unchanged.
- `crates/e2e-tests/tests/it/epoch_record_walk.rs`: `Arm::Gap`, its test and its branches went; the `Walk` and `Recertify` assertions are unchanged apart from L1.
- `crates/e2e-tests/tests/it/fleet.rs`: one entry left each of `STACK_SWITCHES_ON` and `STACK_SWITCHES_OFF`, the lengths went from 6 to 5, and the order still follows `runtime_switches!`.
- `crates/e2e-tests/tests/it/epoch_close_forms.rs`: the `WALK_LOG` doc only; base :1062 names only `epoch_record_recertify`, which is not this commit's.
