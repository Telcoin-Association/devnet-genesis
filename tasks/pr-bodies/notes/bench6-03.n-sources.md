# Sources: PR 03 `fix/epoch-record-closing-block-check` on today's main (not posted)

Text: `tasks/pr-bodies/bench6-03-closing-block-check.md` (rewritten 2026-11-15 for the stack on 33b727fce).
Repository read-only: `/home/drtnarg/coding/telcoin/tn-b7-p2`.
Main N = 33b727fcea4f6004d4b0cd2bd7923258e081e94f; head below (02, `b7/n2-02`) = 17327280d54590d74581fc1abc40d03dd2961c3d; this head (`b7/n2-03`) = c2f266b9c458cad9f238a5ff1100f280e38da9f8.
Line numbers: `git show <rev>:<path>`, read in this unit. "head" = c2f266b9c; "N" = 33b727fce.
Earlier reader's notes used and re-verified: `tasks/pr-bodies/notes/bench6-03.n-delta.md`, `tasks/checkpoint-bench7-BF-03.md`, `tasks/checkpoint-bench7-BF-03-review.md`, `tasks/bench7/review/n34-reshaped-heads-report.md` (Q4, Q8, finding 7).

## Base and stack paragraph

| claim | source |
|---|---|
| PR 4 of 6, merge order 00, 01, 02, 03, 04, epoch-loop; staging = main at 33b727fce | `tasks/bench7/briefs/w-n.md` "What happened" (staging fast-forwarded to 33b727fce before the PRs open) |
| stacked on `fix/1804-vote-queue` | brief table (PR 02 head = `b7/n2-02`); `git rev-parse b7/n2-02` = 17327280d… |
| compare link 17327280d…c2f266b9c…, 3 commits | `git rev-list --count b7/n2-02..b7/n2-03` = 3; full shas by `git rev-parse` |
| commit ids and subjects | `git log --reverse --format='%h %s' b7/n2-02..b7/n2-03`; each `git merge-base --is-ancestor <id> b7/n2-06` holds (checked for every hex id in the text, 33b727fce and 45dce8947 included) |

## Summary

| claim | source |
|---|---|
| (a) beacon root == `final_consensus.hash`, (b) nonce epoch, (c) 32-byte `extra_data`, seed when held | head close_epoch.rs:1502-1525 (`closing_block_check`) |
| runs where a record is built: close and re-derive | head :505-512 (`require_closing_block` on the build path, `build_path` = Built or Rederived), :750 (`write_epoch_record_on(previous_epoch, engine, RecordCheckPath::Rederived)`) |
| three stored-record paths: reuse, own uncertified record 0, entry | head :476-485 (reuse), :460-469 (record-0 arm), :664-673 (entry); the marker check sits in `check_stored_record`'s `Matches` arm :804-815; same three paths on N: :438, :431, :596 |
| failing block stops the node | head :1588-1595 (`Err(ClosingBlockMismatch)` propagated with `?` at every call) |
| no switch; extends #1834 guard and #1849's record-0 arm | no `crates/config` change (`git diff --stat 17327280d c2f266b9c`: Cargo.toml, close_epoch.rs, run_epoch.rs, metrics.rs, tn-reth README); `git diff 45dce8947 33b727fce -- close_epoch.rs` adds the record-0 arm (+:430-433) in d4d53c115 (#1849) |
| blocks, records, votes unchanged | build inputs: N :411 `latest_execution_block_num_hash()` = `executed_blocks.back()…num_hash()` (N `crates/consensus/primary/src/recent_blocks.rs:73-75`); head :433-440 `latest_execution_block()` (same deque back, `recent_blocks.rs:78-80`) then `num_hash()`; `final_consensus` = `ConsensusNumHash::new(number, digest())` on both (N :509/:517, head :503-504); no engine or block-building file in the diff stat |
| new info line and two counters | head :1643-1655; head metrics.rs:70-72, :80-84 |

## Problem (main at 33b727fce)

| claim | source |
|---|---|
| guard compares `final_state` (number and hash) | N close_epoch.rs:1274-1293 (`check_stored_final_state`, compare :1283) |
| stored close path `:438`; own uncertified record 0 `:431` (#1849); entry `:596` | N :436-441, :430-433, :596-602; #1849 = d4d53c115 (`git log 45dce8947..33b727fce -- close_epoch.rs`) |
| below the floor not compared `:1280` (`<`) | N :1280 `restored_floor.filter(\|floor\| local.number < *floor)`; was `<=` at 45dce8947 :1271 |
| ring `:411`, save `:520`, publish `:525` | N :411, :520, :525 (persist :524 between) |
| only the re-derive path reads beacon root and nonce epoch, to find the boundary header | N :650 calls `boundary_consensus_digest` :1303-1325 (beacon root :1307, nonce epoch :1316-1317); issue #1851 body "Only the restart re-derive path reads the first two" |
| `final_state` logged nowhere when built or reused | N: the only non-test log of a record's `final_state` is the mismatch `error!` :741-751 (scan of close_epoch.rs, epoch_votes.rs, state-sync epoch.rs, run_epoch.rs, start_epoch.rs above `mod tests`); issue #1851 body |
| inference: moved ring tip → same wrong record saved and voted, stop at next entry | issue #1851 "What happens" (inferred from code); N entry compare :596 against the `blockHeight - 1` pin (N run_epoch.rs:152, :238; tn-reth env/epoch.rs:360-363) |
| 37 closes; r20261113-1351, r20261113-1630, r20261112-1520 (no public page); closing block = closing output's last block on every node; one record hash per epoch | issue #1851 "Evidence" (public body, read 2026-11-15): "all 37 closes", 25 + 6 + 6, "one record hash per epoch"; head commit 7e67af7d7 body |
| bench 6 builds `final_state` the same way | issue #1851 Evidence; N :411 unchanged from 45dce8947 :411 |
| `final_state` not measured | issue #1851 "Not measured" |

## Change

| claim | source |
|---|---|
| commit 1 order (a), (b), (c); seed when the node holds the boundary header the record commits | head :1502-1525; `closing_seed_for` :850-857 |
| "the engine's own marking rules" | head doc :1487-1501; old review 03 Q2 (payload.rs, evm/block.rs) via the earlier sources note; #1851 "Where in the code" (payload.rs:129-134, :140, :168-170; evm/block.rs:2118) |
| build path checked before committee read and `save_record` | head :500-512 before :553-567 (committee reads) and :587 (save) |
| stored paths after main's compare, `FinalStateMismatch` first; both take the seed by `closing_seed_for` | head :803-815 (comment :805-806); :465 and :481 both `self.closing_seed_for(&epoch_rec)` |
| entry against the registry pin, (c) by length only | head :664-673 (`None` seed, comment "the closing seed would need a consensus-store read here") |
| adiri skips (c) for epoch <= 160 | head :1534-1544; N `crates/types/src/forks.rs:71` (`ADIRI_DUP_BATCH_EPOCH: Epoch = 160`); engine tolerance head `crates/engine/src/payload_builder.rs:150-168` |
| record contents byte-identical | see Summary "blocks, records, votes unchanged" |
| floor rule kept: below neither compare, at the floor both | head :1382 (`<`), :817-826 (Restored arm: no marker check), :804-815 (Matches arm: marker check); doc :790-792 |
| main's guard tests that reach the check now carry markers; `replay_guard_stops_on_an_uncertified_epoch0_record_that_does_not_match` unchanged | `git diff 17327280d c2f266b9c -- close_epoch.rs` hunks at old :2125, :2209, :2273, :2316, :2331 (`execute_to` → `execute_closing` / `closing_header`); no hunk in that test (head :2630) |
| commit 2: `adjust_base_fees` stops on tip + 1 != `blockHeight`; passes counted | N run_epoch.rs:935-951 (error return); head :936-938 (`identity_holds`, `record_close_identity_check`) |
| commit 3: `reason` per path; record 0 refuses `path=stored` with the stored reason; re-derive `path=rederived`; empty ring `no_block` (was `beacon_root`); no decision change | head :1397-1434 (`RecordCheckPath`, `halt_reason`), :466 (record-0 arm passes `Stored`), :1560-1562 (`NoBlock`); at 7e67af7d7 `require_closing_block` takes `&SealedHeader` (no `NoBlock`, a default header fails (a)) and has no `reason` field (7e67af7d7 close_epoch.rs:1511-1550); commit c2f266b9c body |

## What changes for every node

| claim | source |
|---|---|
| counter name and six values | head metrics.rs:70-72 (`tn_epoch.epoch_record_closing_block_check_total`, Prometheus `_` form as in head tn-reth README:1263-1265); head :1456-1468 (`as_str`) |
| one at the close, one at each entry into the next epoch | head :505/:807 (close), :666 (entry); N doc :557-564 ("the check also runs on a mid-epoch restart and a mode-change re-entry") |
| no new read | ring header from the same `recent_blocks` watch (head :433-436); entry pin already held (N run_epoch.rs:152) |
| own record 0: checks twice and counts both | head :460-471 then falls through to :505-512; test `a_reclose_over_own_record0_counts_the_closing_block_check_twice` (head :3533-3567, asserts `{"ok": 2}`); head metrics.rs doc ("so that close counts twice"); review n34 finding 7 (fix: none) |
| info line, fields, branch values and meanings; re-derive logs `built` | head :1638-1655; :486-490 (`stored_matched` / `stored_restored` by `StoredFinalState`); :592 (`built`, the only call in `write_epoch_record_on`, which serves Built and Rederived) |
| identity counter per live close | head metrics.rs:80-84; N run_epoch.rs:842-844 (`if live_boundary`) |
| halt line verbatim, level, target, fields | head :1570-1587 |
| error text ends `(do NOT delete chain-data: keep the datadir)` | head :1620-1632 |
| restart stops again at the next entry | built/re-derived: record unsaved → the entry re-derives through the same check (head :750, :505-512); stored/entry: the entry check (head :666-673); review 03 §2c (earlier sources note) |
| recover as for main's final-state stop; execution rebuild in `crates/tn-reth/README.md` | N README:1209-1260 ("Rebuilding in the new layout", `db reset-execution`, each epoch compared against its record); N FinalStateMismatch text close_epoch.rs:1237-1241 |
| every node at one close: engine and check disagree; a build without the change runs on | inference (old review 03 Q2 and §2b, via the earlier sources note) |
| mixed fleet byte-identical | see Summary row; no change outside the node's close/entry checks, counters and logs |

## Testing

| claim | source |
|---|---|
| test names and what each asserts | head close_epoch.rs: :2884, :2966, :3000 (doc :2995-2998: an earlier batch's block has no marker), :3087, :3186, :3244, :3325, :3379 (doc :3374-3377; floor 21 → `stored_restored`, floor 20 → `(Stored, BeaconRoot)` and `(Entry, BeaconRoot)`), :3467 (asserts `path: Stored, check: BeaconRoot`, then `ExtraDataSeed`), :3533, :3642, :3682, :3718; run_epoch.rs:3127 |
| check exit 0 at 128f4a5d4 and c2f266b9c | `/home/drtnarg/coding/telcoin/tn-b7-n03/target/tmp/bf03-check-c2.log` (header HEAD=128f4a5d4, EXIT=0), `bf03-check-c3.log` (HEAD=c2f266b9c, EXIT=0). Commit 1's log `bf03-check-c1-a.log` shows HEAD=a22415d89, whose tree differs from 7e67af7d7 (`git diff --stat a22415d89 7e67af7d7`: 2 files, +204/-35); the checkpoint says the working tree matched the amend, which a log cannot show, so commit 1 is not claimed |
| nextest -p tn-node 236 passed, 1 skipped | `bf03-nextest.log` header HEAD=c2f266b9c, :247 "236 tests run: 236 passed, 1 skipped", :248 EXIT=0 |
| fmt clean | `bf03-fmt-check.log` (HEAD=c2f266b9c, `cargo +nightly-2026-03-20 fmt --all -- --check`, EXIT=0) |
| clippy clean, with and without adiri | `bf03-clippy.log` (HEAD=c2f266b9c, `-p tn-node -- -D warnings`, EXIT=0); `bf03-clippy-adiri.log` (`--features adiri`, EXIT=0) |
| adiri run: 51 passed (`close_epoch` and `metrics` modules, entry test, identity counter test) | `bf03-nextest-adiri.log` header filter `test(close_epoch::) \| test(epoch_entry_accepts_a_genuine_record) \| test(the_close_time_identity_check_is_counted) \| test(metrics::)`, :80 "51 tests run: 51 passed, 184 skipped", :81 EXIT=0 |
| no fleet ran this head; a benchmark of the earlier cut on 45dce8947 is under way and carries the check | brief item 6; `git log --grep` on 91a15e223 finds the check's commit (0238163c2); 45dce8947 is an ancestor of 91a15e223 |
| no e2e test makes the check fire | no e2e file in this head's diff; at `b7/n2-06` the halt line appears only in `crates/e2e-tests/tests/it/fleet.rs:86-88` (a fatal-line list) and the counter name in `epoch_close_forms.rs:118` |
| dropped: the old e2e line (integration build on 45dce8947) and the old stack-wide gates | brief items 4-5; delta note (L53, L56-66) |

## Limits

| claim | source |
|---|---|
| false-positive cases traced, none failing (list) | old review 03 Q1-Q2 (earlier sources note); review n34 Q4 (restart in the close of epoch 0, own record 0, floor block, adiri early epochs: "No false refusal found") |
| own record 0 cannot refuse where the build would pass | review n34 finding 7 |
| engine test uses `TNPayload::new`; empty output and adiri tolerance by reading | head :3021 (`TNPayload::new`); review n34 Q8 "5 Info … still applies" |
| floor block = imported header, hash tied to the certified record's `final_state` | N `crates/node/src/manager/export_exec.rs:268-281` (full headers exported), N `crates/telcoin-network-cli/src/db.rs:1581-1583` (re-sealed), :1323-1338 (pack bound to the certified record), N `crates/tn-reth/src/snapshot.rs:650-657` (tip hash must equal `final_state.hash`), :806-813 (inserted as is) |
| three restore e2e tests, names and file | head `crates/e2e-tests/tests/it/state_export_import.rs:155`, `:464`, `:854` (all `#[ignore]`, run as a separate step); not run on this head (no log); the gates line decides |
| marker rules in two places; adiri bound in two crates | head payload_builder.rs:157 and close_epoch.rs:1534-1537 |
| long-lived networks: old records checked only when read again; resync or walk before adiri; new exposure = `final_consensus` or nonce epoch beside a right `final_state` | code: the check runs only on the reuse, record-0, entry and build paths (above); no walk of stored records exists; earlier sources note (review 03 residuals) |
| nothing found is left unfixed | BF-03 review: APPROVED, Q4 Low items all at commits 1-2 and fixed at the tip (head metrics.rs doc now names the re-derive path); review n34 Q8: report-03 items 2, 3, 4, 6, 7 fixed, 5 (engine test) named in the limits, 8 a design note, 1 is #1860 |

## Related

| claim | source |
|---|---|
| #1851 open, fix sketch implemented, e2e half not here | `gh issue view 1851` (OPEN, no comments; "What a fix could look like", "How to verify"); no e2e file in `git diff --stat 17327280d c2f266b9c` |
| `epoch_close_forms.rs` in `fix/1804-quorum-exec-block` compares every published record with the block where the registry's epoch turned | `b7/n2-05` (38f00e88e) `crates/e2e-tests/tests/it/epoch_close_forms.rs`, added by 38f00e88e: :1191-1232 (final_state vs the turning block, 32-byte `extraData`, beacon root == `final_consensus`), :1269-1278 |
| #1860 open; main's loop can drop an output | `gh issue view 1860` (OPEN); `git diff --stat 45dce8947 33b727fce -- crates/node/src/manager/node/run_epoch.rs` is empty, N run_epoch.rs:730 (send) and :749 (take); review n34 Q8 item 1 |
| next head `fix/epoch-record-collector-hardening` | brief table (PR 04 = `b7/n2-04`, ff877fb0e) |
