# Review RVB-main-1: bench 8 main chain, commits 1-3 (77d7909c1, 19074c301, 1f87d7860)

Worktree `tn-b8-bench`, branch `bench/bench8-2026-11`, base 91a15e223. Line numbers are at 1f87d7860 unless marked `@base`. Read-only review; no cargo run.

## Verdict: approve with follow-ups

0 Critical, 0 High, 0 Medium, 7 Low. At floor 8 the named block and every other header byte are what 91a15e223 produced. At 16 the named block is always an entry of the proposer's own ring, at or above the epoch's opening block and below or at the own tip. No voter code reads the floor.

## Per commit

**77d7909c1 test(primary): golden table** (proposer_tests.rs, +86, test only)
1. Behaviour: none (test only). 2. Logged values: n/a. 3. Cost: n/a.
4. Tests: 20 rows on 4 rings pin (block, tip, basis) and the own-ring hash of the named block. Rows reach: rule off (Off, Tip outside a window), in step, cap above the tip, short power, empty ring, quorum (exact entry and between entries), floor at 9/12/16/17 entries back and the oldest entry, Starved, short ring (quorum, floor = oldest), opening block named, parents below the opening dropped. Rows missing (L4): the walk's other parent filters (another epoch, round 0, own certificate, repeated author). Unreachable, so no row is possible: the `nth_newest` `None` arm of `quorum_rule_choice`, the `newest_at_or_below` `None` arm, and the `bound_to_opening` raise.
5. Rules: subject/body fine, no attribution, `Topic: bench8-obs` last.

**19074c301 feat(primary): floor parameter** (config/node.rs, proposer.rs, tests)
1. Behaviour at 8: none. `floor_entries` = `usize::try_from(8)` (proposer.rs:379-380) replaces the constant at the one read (proposer.rs:2508). A compile-time assert keeps default == `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES` (proposer.rs:2026-2029). The new refusal cannot newly fire at 8, because `gc_depth > GC_ACTIVITY_BUFFER` (10) is checked first (node.rs ~703-708, types/primary/mod.rs:64). The diff to the golden table is only the `floor_entries` plumbing. All 20 expected triples are unchanged through 1f87d7860.
2. n/a (the `node switches` value is the parameter itself: `SwitchValue::Count`, rendered `{count}`).
3. Cost: one `usize` per proposer and per header input. Nothing else.
4. Tests: `parameters_bound_quorum_exec_block_floor_to_the_ring` pins default 8, the listed value "8", 1 and gc_depth accepted, 0 and gc_depth+1 refused, and the message. `test_quorum_exec_block_floor_parameter_sixteen` pins the 8 changed rows and their values at 16 (`differing == changed.len()`).
5. Rules: no unwrap/expect, docs present, no new dependency. `Refs #1804`, Topic last.

**1f87d7860 feat(primary): four fields on `header proposed`**
1. Behaviour at default: none. `Header::new` is called with the same arguments (proposer.rs ~513-522). The moved floor read is proven harmless under A below. The `parents` Vec is built inside the tracing macro's enabled branch, after the header exists.
2. Values: `exec_quorum` = `quorum_value.unwrap_or_default()` (proposer.rs:2531). That is after the parent filters (other epoch, round 0, below the opening block, own, repeat: :2516-2523) and before the cap (:2532), the floor (:2537) and `bound_to_opening` (:2492). See L1. `exec_floor` = `nth_newest(floor_entries).number` (:2508): on every header under the rule, 0 only when the rule did not run or the ring is empty. `parents`: one per parent cert, no dedup, `sort_unstable` on derived `Ord` of `Arc<[u8;32]>` (byte order, committee.rs:724-725), rendered full bs58 (committee.rs:789). `pending_unheld` = `pending_before.saturating_sub(held)` (:293-295). This is exact: `pending_before` (:1431), plan, `order.record` and `drain_held` (:1432-1453) run synchronously on `&mut self` with no `.await` and no second drain. A held lane is filtered out of the drain whole (:1278), so `held` (:1317-1321) counts only digests that were in `pending_before`.
3. Cost: per header, one `Vec<&AuthorityIdentifier>` of 10 or fewer, a sort, and one bs58 `String` per author in Display. That costs about 10 small allocations, only while INFO `consensus::metrics` is enabled. The floor read is now done on every header under the rule: one O(1) `VecDeque::get` under the same synchronous ring borrow (:2403). No lock, no await, no clone. Bytes: `parents=` is about 10 x 44 + 9 + 2 = about 450 B. The four fields add about 510 B per line. At about 2.5 headers/s/node that is about 1.3 KB/s/node (about 4.6 MB/h).
4. Tests: the golden table pins `(exec_quorum, exec_floor)` per row at 8 and 16. `test_header_proposed_reports_bench8_fields` pins `pending_before/held/pending_unheld` with the hold on and off ((2,1,1),(3,0,3) / (2,0,2)), `parents` (value and order), `num_parents` equality and the field order. Gap (L3): on the rendered line, `exec_quorum`/`exec_floor` are pinned only at 0, because the fixture's policy is off.
5. Rules: fine. One Low: the test prints the unit label `B8-1b` (L6).

## A. At the default (8)

- Golden table: covers every basis and every reachable branch except the parent filters (L4). The table was committed alone on the unchanged code (77d7909c1 adds only test lines; every helper it calls exists at 91a15e223). I did not re-run it.
- `bound_to_opening` raise (proposer.rs:2556-2563, assert :2493). In `quorum_rule_choice`, every counted value is >= `lowest_usable` = opening (:2515-2520), and the own tip is >= opening. So the quorum value v >= opening. The named block is either `newest_at_or_below(v)` (>= opening on a ring whose numbers do not fall, since the opening entry is a candidate) or the floor entry, which is named only when v < floor.number, so floor.number > v >= opening. The floor depth never enters this inequality chain. So the raise is no more reachable at 16 than at 8. It can fire only on a ring whose numbers fall in push order, and `push_latest` (recent_blocks.rs) appends only the canonical tip of each output.
- Moved floor read (1f87d7860: :2508, before the walk; @base it came after the walk, base :2436). `nth_newest` returns `None` only when `len()==0` (`checked_sub(1)?`, recent_blocks.rs:99-102). `choose_exec_block` returns before `quorum_rule_choice` on an empty ring (:2484). So inside the rule the read is always `Some`, and it is the same pure function of the same borrowed ring and the same `floor_entries`. The walk does not read it. Base and tip return identical choices. Even on the never-taken `None` arm, both name `own_tip`.

## B. At 16

(i) 50 entries, quorum value 12 back: floor = entry 16 back. v >= floor gives `newest_at_or_below(v)`, the 12-back entry, basis `quorum`. At 8 this was the 8-back entry, basis `floor`.
(ii) Value 20 back: v < floor gives the entry 16 back, basis `floor`.
(iii) 10 entries: `nth_newest(16)` = index 0, the oldest entry (9 back). The ring is built once per process (node.rs:800) and is not cleared at an epoch change, so a short ring happens only after a node (re)start.
(iv) First rounds of a new epoch: in round 1 the parents are the epoch's genesis certificates (round 0, filtered), so only the own power counts: short of quorum, so the own tip, at any floor. Later rounds: the floor entry may lie below the opening block for the first 16 block-bearing outputs of the epoch (8 at default). It is never named (argument above), but it is logged (L2).
In all four cases the named block is an own ring entry: `newest_at_or_below`, `nth_newest` or the tip. It is >= the opening block, and <= the own tip by the cap (:2532).
Voter side: no code outside `proposer.rs` reads `exec_block_floor`, `floor_entries` or the constant, except tests and the e2e doc constant (L7). The own node's voter checks its own header like any other (`check_execution_block`, recent_blocks.rs:135-143). A voter whose ring lacks the block (one restored from a snapshot or restarted recently, holding fewer entries) misses in the ring and goes to `ExecutionCheck::from_canonical`. It answers `Match` if the block is persisted with that hash, `Unconfirmed` if not yet persisted (asked again, not refused), `Fork` on a different hash, and `BelowFloor` only below its restore floor. Exports are taken at epoch closing blocks, and the named block is >= the header epoch's opening block, so an honest proposer at 16 never draws `BelowFloor`. A deeper floor only sends more such voters to the canonical read.

## C. Plumbing

- `usize::try_from(u64).unwrap_or(usize::MAX)` (proposer.rs:379-380) is exact on 64-bit.
- `validate_operational_floors` (config/node.rs, ensure ~748-754) is called from `ConsensusConfig::new` (consensus.rs:101) and `new_for_epoch` (consensus.rs:194). The only non-test production caller is `configure_consensus` (start_epoch.rs:452), which runs for every epoch with `self.builder.tn_config.clone()`. `ConsensusConfig::new` has no caller in the tree. The ring is built once with `builder.tn_config.parameters.gc_depth` (node.rs:800), the same value. So the refusal happens when the first epoch's config is built, not at process start, which has the same effect.
- Floor = gc_depth on a full ring: `nth_newest(50)` = index `49.saturating_sub(50)=0`, the oldest entry, 49 back. It is never `None` and never the tip. So a floor of gc_depth behaves as gc_depth-1 (L5).

## D. Switch listing and YAML

- `quorum_exec_block_floor_outputs` is appended after `digest_order_hold`, before the end marker (config/node.rs:843). `switches()` and `log_switches` are generated in listing order, so earlier entries keep their order and rendering. The new value renders as `SwitchValue::Count` (`impl From<u64>` existed before, node.rs:904). The gauge gains one label value.
- `skip_serializing_if = "Parameters::floor_outputs_at_default"` with serde default 8: a written `parameters.yaml` is byte-identical at 8, and a file without the key reads 8.

## E. Fields: see 1f87d7860 item 2. All four claims hold, with the L1 caveat on `exec_quorum`.

## Findings

Critical: none. High: none. Medium: none.

Low
- L1 `exec_quorum` docs (ExecRuleTrace, proposer.rs ~2425-2428; node-fields.md) say it is taken before "the opening-block bound". In fact parents below the opening block, of another epoch, of round 0, the own certificate and a repeated author are dropped before the walk (:2516-2523). Golden row "opening: parents below it are not counted" logs `exec_quorum=0` with 9 parents present. Fix: say "after the parent filters, before the cap, the floor and the final opening bound".
- L2 `exec_floor` can lie below the epoch's opening block, and then it is never the named block. Example: ring 3 at 16 gives 151 < opening 187 (golden `floor_sixteen[3]`). This happens for the first `floor` block-bearing outputs of each epoch. Fix: a node-fields note, so analysis does not read `exec_block - exec_floor` as the floor's effect there.
- L3 No test pins a non-zero `exec_quorum`/`exec_floor` on the rendered line. A swap at proposer.rs:567-568 would pass every test. Fix: one proposer-level case with policy `Always` that asserts both fields.
- L4 The golden table has no row for the walk's other-epoch, round-0, own-certificate and repeated-author filters. The code is unchanged, so this is coverage only.
- L5 A floor of exactly `gc_depth` names the oldest entry, `gc_depth-1` back (recent_blocks.rs:99-102). Harmless. Fix: doc it, or bound `1..gc_depth`.
- L6 `println!("B8-1b sample line: …")` in `test_header_proposed_reports_bench8_fields` puts a private unit label in test output. Fix: drop the print.
- L7 `crates/e2e-tests/tests/it/epoch_close_forms.rs:62-64` hard-codes `FLOOR_OUTPUTS = 8`. Correct at the defaults e2e runs with. Stale if anyone reads it for run F.

## Corrections to tasks/bench8/node-fields.md

- "Start-up refusal (`Parameters::validate_operational_floors`)" → "Refused when each epoch's consensus config is built (`configure_consensus`, start_epoch.rs:452 → `ConsensusConfig::new_for_epoch`), so a bad value stops the node at its first epoch start".
- "At 8 the header payloads equal 91a15e223's (golden table of 20 rows on 4 rings; …)" → "At 8 the named execution block equals 91a15e223's on all 20 golden rows (4 rings), and every other header byte is built by unchanged code; at 16 exactly 8 rows differ".
- `exec_quorum`: "BEFORE the cap at the own tip, the floor and the opening-block bound" → "after the parent filters (another epoch, round 0, below the epoch's opening block, the own certificate, a repeated author) and BEFORE the cap at the own tip, the floor and the final opening-block bound".
- `exec_floor`: add "may lie below the epoch's opening block (and below `exec_block`) during an epoch's first `quorum_exec_block_floor_outputs` block-bearing outputs; a floor entry below the opening block is never named".
- Sample tail: add "(authorities abbreviated here; the node logs the full bs58, about 44 characters)".
- Parameter: add "a floor equal to `gc_depth` names the oldest entry of a full ring, `gc_depth`-1 back".

## What run F (floor 16) will and will not exercise

It will change only headers under the rule (`exec_policy` always/starved window) whose quorum value lies 9 to 16 ring entries below the own tip. Those now name the quorum value (basis `quorum`) instead of the 8-back floor. Headers deeper than 16 back name the 16-back entry instead of the 8-back one. `exec_quorum`/`exec_floor` make each case visible on every such header. Voters that are in step answer from their 50-entry rings, so the measured effect is the voters that held the older block but not the 8-back one.

It will not exercise: the `bound_to_opening` raise (unreachable at any floor); headers with the rule off or the tip policy outside a window; round 1 of an epoch (own tip by short power); any voter-side change (none exists); `BelowFloor` (not reachable from an honest proposer). The short-ring path runs only on a node that restarts during the run. A floor entry below the opening block appears in `exec_floor` early in each epoch but is never named.
