# Sources: PR 03 `fix/epoch-record-closing-block-check` (not posted)

Text: `tasks/pr-bodies/bench6-03-closing-block-check.md`.
Repository read-only at `/home/drtnarg/coding/telcoin/telcoin-network`; head 6d8fe775b, previous head 6ad315794 (full shas `git rev-parse`: 6d8fe775bffa22c36508eb6e62ca034e69492faa, 6ad315794b8f641f7ce0f2e2b8b24d7322cee6ab).

## Summary and Change

| claim | source |
|---|---|
| 3 commits 56841024a, a9d7c0026, 6d8fe775b, subjects verbatim | `git log --reverse --format='%h %s' 6ad315794..6d8fe775b` |
| (a) beacon root == `final_consensus.hash`, (b) nonce epoch, (c) 32-byte `extra_data`, == seed when given; order of comparisons | close_epoch.rs at 6d8fe775b `closing_block_check` :1478 (body in `git diff 6ad315794 6d8fe775b`, diff lines 345-368) |
| seed on build path always (boundary header's `sub_dag.randomness()`); stored path only when the node's boundary header is the record's `final_consensus`; entry `None` | close_epoch.rs:499 (`require_closing_block(..., Some(last_consensus_header.sub_dag.randomness()), build_path, false)`), stored branch seed filter (diff lines 78-85), entry call :665 with `None` and comment "the closing seed would need a consensus-store read here" |
| build path checked before committee read and `save_record` | diff lines 105-122 (take + check moved above the committee reads); review 03 Q3 order |
| stored path compares after main's `final_state` compare | `check_stored_record` :786, `require_closing_block` called inside `Ok(StoredFinalState::Matches)` (:800); comment "compared after `final_state`, so a record naming another block is reported as a `FinalStateMismatch` first" |
| adiri skip of (c) for epoch <= 160 | `closing_marker_checked` :1511 (`epoch > tn_types::forks::ADIRI_DUP_BATCH_EPOCH`), doc comment (diff lines 370-380); `ADIRI_DUP_BATCH_EPOCH` = 160 (`crates/types/src/forks.rs:71` per DR-E findings, README text "epochs up to 160") |
| "the engine tolerates closing outputs whose last block carries no marker" | `closing_marker_checked` doc: outputs holding more batch digests than batches, close flag lands on no block, last block carries no marker; review 03 Q2 adiri bullet |
| "the engine's own marking rules" | review 03 Q2 (payload_builder.rs, evm/block.rs:2114/:2118/:2150, payload.rs:128-140) |
| record contents byte-identical to main | review 03 §2a last bullet |
| restored-floor skip kept | `check_stored_record` doc "A closing block at or below it is compared in neither way"; test `the_restored_floor_skips_the_closing_markers_too`; review 03 Info 7 |
| main's guard tests re-fixtured with markers | diff hunks at old :2115, :2199, :2227, :2280 (`execute_to` → `execute_closing` / `closing_header`) |
| identity check: halt unchanged, pass counted, failed epoch-info read not counted | run_epoch.rs:936-937 at head (`identity_holds`, `record_close_identity_check`); metrics.rs:77 doc; commit a9d7c0026 body |
| third commit: per-path `reason`, `path=rederived`, `check=no_block` (was `beacon_root`), no decision change | `git show 6d8fe775b`: `halt_reason` (Built/Rederived vs Stored/Entry), `write_epoch_record_on(..., Rederived)` :744, `NoBlock` via `block.map_or`; empty ring before = default header failing (a): review 03 Info 4 |

## Problem (main at 45dce8947)

| claim | source |
|---|---|
| guard compares `final_state` number and hash `:1274`; stored path `:432`; entry `:590`; ring sample `:411`; save `:514`; publish `:519` | `git show 45dce8947:crates/node/src/manager/node/close_epoch.rs` lines checked by awk in this unit; DR-E findings §1 |
| no marker compare on any path; `final_state` logged nowhere | DR-E findings §1, §3; issue #1851 body |
| inferred: a moved ring tip → every node saves/votes the same wrong record, stops at next entry | issue #1851 "What happens" last paragraph (inferred from code) |
| 37 closes, runs r20261113-1351, r20261113-1630, r20261112-1520 (no public page), closing block = closing output's last block on every node, one record hash per epoch | issue #1851 "Evidence" (public); its sources note `tasks/issue-bodies/notes/bench6-epoch-record-closing-block-check.sources.md:22` (E3 "The answer" :14, §3 table :74-78) |
| bench 6's branch builds `final_state` the same way | issue #1851 Evidence ("it builds `final_state` the same way") |
| `final_state` not measured | issue #1851 Evidence "Not measured" |

## What changes for every node

| claim | source |
|---|---|
| counter `tn_epoch_epoch_record_closing_block_check_total{result}` and its six values | metrics.rs:67 (`record_closing_block_check`), `ClosingBlockCheck::as_str`; contract §3.3 (Prometheus name) |
| one check at the close, one at the next entry; no new read | review 03 §2a (build/stored at close, entry every entry; header from the ring and the entry pin main reads at run_epoch.rs:152) |
| info line `epoch record published`, fields, branch values; re-derive logs `built` | close_epoch.rs:1617-1627 `log_published_record`; calls :484 (stored_matched/stored_restored) and :586 (`built`, the only call in `write_epoch_record_on`, which serves Built and Rederived) |
| identity counter per live close, `ok`/`mismatch` | metrics.rs:77; run_epoch.rs:937; DR-E findings §3 ("runs on the live close only") |
| halt line verbatim, level error, target `epoch-manager`, fields | close_epoch.rs:1546-1563 at head (`error!` with the continuation string at :1561); contract §2.3 |
| error text ends `(do NOT delete chain-data: keep the datadir)` | `impl Display for ClosingBlockMismatch` :1592 |
| restart stops again at the next entry | review 03 §2c |
| one node alone → recover as for main's final-state stop (execution rebuild in tn-reth README) | inferred: main's `FinalStateMismatch` text "keep the datadir to find the first block that differs" (45dce8947 close_epoch.rs:1225-1236); README rebuild section (head `crates/tn-reth/README.md` ~:958-990) documents the rebuild and both checks |
| every node at one close → engine and check disagree; a build without the change runs the same chain | review 03 Q2 (fleet-wide halt question) and §2b (nothing other nodes see changes) — inference |
| mixed fleet byte-identical | review 03 §2b |

## Testing

| claim | source |
|---|---|
| test names | `git diff 6ad315794 6d8fe775b` (close_epoch.rs tests at diff lines 730-1407; run_epoch.rs `epoch_entry_accepts_a_genuine_record_against_the_registry_pin`); "an earlier block of the same output fails": doc of `a_closing_block_the_engine_builds_passes_the_check` |
| first cut 8f7e4357a: check exit 0; nextest -p tn-node 232 passed, 1 skipped | `tn-b7-stack/target/tmp/head03-8f7e4357a.log` lines 1, 19, 20, 40, 274-275; ledger row 03 and re-cut section (re-cut differs by `crates/config/src/node.rs` doc comments and CLI README only, from 1290500de under it) |
| main + these commits (unit branch b7/e1 tip 0ec490341, base 45dce8947): clippy -p tn-node and --features adiri EXIT=0; adiri nextest 37 passed | `checkpoint-bench7-E1.md` gates; `tn-b7-e1/target/tmp/e1-clippy-7.log`, `e1-clippy-adiri-5.log`, `e1-nextest-adiri-5.log` (filter closing/replay_guard/epoch_entry/restored_floor/published/identity/refusal/no_block/rederived: 37 run, 37 passed, 193 skipped) |
| e2e on integration head 14372820d (M + PT-0 + PT-1 + E2 + E1's first two commits), every switch off: restarts 11/11, epochs 11/11, sigkill 12/12, 0 halt-message lines | `checkpoint-bench7-orch.md:200`, `:229`, `:234-235`; review 03 "How this was reviewed" |
| next benchmark on eleven nodes | launch prompt; bench 6 fleet shape ten validators + one observer (issue #1851 Evidence) |

## Limits

| claim | source |
|---|---|
| false-positive cases traced, none failing; rule matches every engine branch | review 03 Q1, Q2 |
| engine test uses `TNPayload::new`, not `execute_consensus_output`; empty output and adiri tolerance by reading | review 03 Info 5 |
| marker rules in two places; adiri bound in two crates | scope I5, I6; review 03 "Residuals"; orch log :205-207 |
| long-lived networks: old records checked only when read again; full resync or walk before adiri | launch prompt; orch log :205-206 (L4) |
| new exposure narrowed to `final_consensus` / nonce epoch | review 03 "Residuals" L4 paragraph |
| nothing left unfixed | review 03 findings 2, 3, 4, 6 fixed in 6d8fe775b (`checkpoint-bench7-E1.md` third completed line); Info 5, 7, 8 optional / scope |

## Related

| claim | source |
|---|---|
| #1851 fix sketch implemented; e2e half not in this PR | issue #1851 "What a fix could look like" / "How to verify" vs the diff (no e2e file changed: `git diff --stat 6ad315794 6d8fe775b`) |
| e2e marker check planned in head 04's epoch-close tests | `tasks/bench7/briefs/ecf.md:10,25`; `checkpoint-bench7-ECF.md` (status in-progress); ledger row 04 "waits for DS-1, ECF, E5b" |
| #1860 = epoch-loop-output-drop, own PR `fix/epoch-loop-output-drop` | launch prompt; review 03 finding 1 ("This topic's new check does not catch it") |
