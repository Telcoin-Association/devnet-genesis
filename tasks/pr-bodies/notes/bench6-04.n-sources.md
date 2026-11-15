# Sources: PR text 04 `fix/epoch-record-collector-hardening` on today's main (not posted)

Text: `tasks/pr-bodies/bench6-04-collector-hardening.md`, 1,847 words by `wc -w` (earlier form 1,611; cap about 1,930), `bash tasks/bench7/orch-gh-post.sh lint` LINT-OK.
Repository read-only: `/home/drtnarg/coding/telcoin/tn-b7-p2` (git object reads only).
Main N = 33b727fcea4f6004d4b0cd2bd7923258e081e94f. Head 03 = c2f266b9c458cad9f238a5ff1100f280e38da9f8 (`b7/n2-03`). This head = ff877fb0ef97dcba56a76bb7df3b957a9bc9592e (`b7/n2-04`).
`git rev-list --count c2f266b9c..ff877fb0e` = 27; `git rev-list --count 33b727fce..ff877fb0e` = 60.
Every short id in the text (27) is in `c2f266b9c..ff877fb0e` and an ancestor of `b7/n2-06` (`git merge-base --is-ancestor`, checked one by one); every commit of the range is named in the text.
Tip copies used for line numbers (scratch): `ev_tip.rs` = `ff877fb0e:crates/node/src/manager/epoch_votes.rs`, `epoch_tip.rs` = `ff877fb0e:crates/state-sync/src/epoch.rs`, `walk_tip.rs` = `ff877fb0e:crates/e2e-tests/tests/it/epoch_record_walk.rs`.
Reader's notes used and checked (not cited in the text): `tasks/pr-bodies/notes/bench6-04.n-delta.md`, `tasks/checkpoint-bench7-BF-04a.md` (parts 1-4), `tasks/checkpoint-bench7-BF-04b.md`, `tasks/bench7/review/n34-reshaped-heads-report.md` (verdict, findings 1-7).

## Commit ids (old -> new, for the earlier text's ids)

| old (45dce8947 series) | new | subject at new |
|---|---|---|
| a0f066bf3 | bb5f2533e | feat(primary): name the peer that served an epoch certificate |
| 804612e01 | 9a401b658 | feat(state-sync): gauge how far every epoch record is certified |
| 06bd23236 | 053713719 | fix(node): no quorum error when the epoch record is already certified |
| e02241b99 | 047910bcf | feat(config): add the epoch_record_recertify switch |
| ca3fc40fd | 9e97158b9 | feat(node): re-certify older uncertified epoch records |
| 548e606fc | f2f3de1bd | fix(node): keep re-certify rounds off the epoch record signers gauge |
| 445c8ac78 | df0075d98 | feat(config): a switch for the epoch record collector's walk |
| 44c5b88ea | b8142b234 | feat(state-sync): walk past an own uncertified epoch record, count a conflicting one |
| 729c30a1b | 8b3109ddb | test(node): add a hook that withholds a node's own epoch vote |
| da7c8f465 | 64a6de4b5 | docs(node): say what the withhold hook leaves in place |
| 19aa21b01 (+0671e626d folded) | 4c63328ca | fix(state-sync): log who certified a conflicting epoch record |
| 3515fdd76 | dropped | (the threshold) |
| 90546d0d8 | 0a7c8f21c | fix(state-sync): bound the epoch record gap retry by a deadline and shutdown |
| 4d54cb784 | 352a78b9e | fix(state-sync): keep an epoch record gap open when its read fails |
| c7a366bdc | 5b9c4f210 | fix(state-sync): persist what a walking pass stored when a record is refused |
| 7efa02c9a | 7d2639473 | fix(state-sync): retry an epoch record walk that did not land once per interval |
| 3be004668 | 3805eab5b | docs(config): describe the epoch record walk's retries and what a conflict does |
| 42a33a914 | 8038aa198 | fix(state-sync): lead the next gap retry with the gap its deadline cut short |
| def55a937 | 4d3c7e7fb | docs(config): say where the epoch record walk is held back and how to read the conflict counters |
| e2e8760c8 | 3143a099d | fix(node): keep older records' vote rounds off the epoch record signers gauge |
| a804ce9c4 | 818d61e47 | test(node): pin that a re-certify round stops the node on a conflicting record |
| e7f559696 | 80e1672a8 | fix(node): aggregate kept epoch votes once they reach a quorum |
| 29c36a4ec | ba73ee5f9 | fix(node): never evict the latest close's epoch vote rounds |
| 0fa7baa68 | 1dfa680a0 | docs(node): say what a re-certify round does on a conflicting record |
| 29929278a | 8c76745f2 | fix(node): no missing-certificate alarm when kept votes certify the record |
| (new) | d6992db59 | fix(state-sync): count an epoch record conflict once, after its evidence is read |
| (new) | b7f008dc9 | docs(state-sync): say which committee certifies a conflicting epoch record |
| c319adfac | dropped | (the halt's doc) |
| ca258b37c | ff877fb0e | test(e2e): an epoch the network never certifies, walked past and re-certified |

Source: `git log --reverse --format='%h %s' c2f266b9c..ff877fb0e` and `45dce8947..fix/epoch-record-collector-hardening`; BF-04a tables.

## Summary and stack paragraph

| claim | source |
|---|---|
| two switches, default false, `node switches` entries | `ff877fb0e:crates/config/src/node.rs:408` (`epoch_record_recertify`), `:439` (`epoch_record_collect_past_uncertified`), `:565-566` (Default), `:767-768` (`runtime_switches!`) |
| serving peer, gauge, held-cert info line, evidence line + counter: no switch | see Change rows below (no switch read on those paths) |
| eviction is the one switch-off behaviour change | review n34 finding 6; `ev_tip.rs:526-531` (doc), `:606-620` (code, no switch read); main `33b727fce:crates/node/src/manager/epoch_votes.rs:403-404` (`pop_front` at `len() >= 5`) |
| PR 5 of 6, merge order (wording as texts 00-02: "then `fix/epoch-loop-output-drop`"), base staging branch | `tasks/bench7/briefs/w-n.md` table and "Merge order" line |
| compare link and 27 commits | full shas above; `git rev-list --count` |

## Problem (main at 33b727fce)

| claim | source |
|---|---|
| pass ends at first record it cannot store | `33b727fce:crates/state-sync/src/epoch.rs:372-374` (`if result_epoch != epoch { break; }`) |
| peers serve a record only with its certificate | `33b727fce:crates/consensus/primary/src/network/handler.rs:1909-1919` (`get_epoch_by_number`, `cert.map(...)`, `UnavailableEpoch`) |
| failsafe re-votes only the previous record, once | `33b727fce:crates/node/src/manager/epoch_votes.rs:483-502` |
| handler.rs and epoch_votes.rs unchanged 45dce8947 -> 33b727fce | `git diff --stat 45dce8947 33b727fce -- <both>` empty |
| 37 closes, all with at least 7 of 10 (bench 6, unchanged) | earlier sources note `bench6-04-collector-hardening.sources.md` row "37 closes" (`tasks/bench6-report-r20261113-1351.md:391`) |
| since #1849 a conflicting certified record stops the node in the collector, counted in `tn_epoch.final_state_mismatches_total` | `33b727fce:crates/state-sync/src/epoch.rs:213-215` (const), `:228-245` (`stop_on_local_failure`: counter, error line, `Err`); #1849 = d4d53c115 (`git log 45dce8947..33b727fce`; `git show d4d53c115 -- crates/state-sync/src/epoch.rs`); #1850 comment of 2026-11-15 says the same |
| vote round's recovery stops on a conflict | `33b727fce:crates/node/src/manager/epoch_votes.rs:279-289` |
| collector's line names epoch and both digests, not signers/peer | `33b727fce:crates/state-sync/src/epoch.rs:231-237` (fields `epoch`, `e`); `e` Display `33b727fce:crates/storage/src/epoch_records.rs:2759-2762` ("epoch {epoch} already holds record {stored}; refusing the different record {offered}") |
| quorum error without store check | `33b727fce:crates/node/src/manager/epoch_votes.rs:231-237` |
| 11 times, each with the cert already stored | issue #1852 body "Evidence" (unchanged; no comments on #1852 at 2026-11-15) |

## Change (at ff877fb0e)

| claim | source |
|---|---|
| `request_epoch_cert` returns the peer; `peer`, `signers` on both `retrieved cert` lines | `ff877fb0e:crates/consensus/primary/src/network/mod.rs:2774-2778` (returns `(EpochRecord, EpochCertificate, BlsPublicKey)`); `epoch_tip.rs:742-747`; `ev_tip.rs:413-418` |
| gauge semantics, -1, set at startup and after each pass | `ff877fb0e:crates/state-sync/src/metrics.rs:40-44`; `epoch_tip.rs:401`, `:417` (startup), `:956` (collector) |
| held-cert round: info line, counter, signers gauge from cert, no alarm, recovery unchanged | `ev_tip.rs:322-348` (counter `:331`, line `:342`, gauge `:345-347`), recovery follows `:362` on, alarm gate `:440-443` |
| kept votes per (epoch, digest), seed the next round | `ev_tip.rs:131-137` (doc), `:912-934` (`RetainedEpochVotes` doc) |
| close N and startup re-arm re-vote one older record, N-16..=N-2, round-robin, members only | `ev_tip.rs:846-868` (`pick_recertify_record`, `epoch % count`), `:878-920` (`recertify_older_record`, member check `:886-890`), `:806-830` (startup re-arm with `recertify`); `MAX_RECERTIFY_LOOKBACK = 16` `:56` |
| older rounds leave the signers gauge alone; `round=recertify` label | `ev_tip.rs:1083-1102` (`RoundKind`), `:1182-1200` (label); gauge only `if kind == RoundKind::Current` `:345`, `:357`, `:497` |
| kept quorum aggregated, never for a conflicting record | `ev_tip.rs:446-503` (`forget_record` on `conflict` `:449-452`, `take_quorum` `:468`); alarm after kept quorum `:510-517` |
| re-certify round conflict: main's `we have forked!` + shutdown | `ev_tip.rs:400-411` (`conflict = true`, line, `node_shutdown.notify()`), doc `:139-144`; test `ev_tip.rs:4488-4500` (cases: recertify+marked, recertify unmarked, previous record's round, switch off) |
| walk: own uncertified record only, not epoch-0 dummy; next validates against it; gap at most 16 | `epoch_tip.rs:146-190` (`may_walk_past`; own uncertified record, not the dummy, `:187`), `:62` (`MAX_UNCERTIFIED_GAPS = 16`); config doc `ff877fb0e:crates/config/src/node.rs:410-424` |
| retries 5 s / shutdown, cut gap leads, failed read keeps gap, refusal after walk persists, unlanded walk once per 5 s | `epoch_tip.rs:73` (`GAP_RETRY_DEADLINE`), `:127-132` (`retry_from`), `:133-136` + `:174-179` (`unlanded_walk`), `:632-647` (refused after walk breaks to the persist), `:790-860` (`retry_gaps`); config doc `node.rs:415-424`; commit subjects |
| walk does not change a conflict, but reaches epochs a walk-off node never asks for | config doc `ff877fb0e:crates/config/src/node.rs:426-428`; `epoch_tip.rs:658-661` (walk continues past a "not held") |
| conflict: main's stop unchanged, in collector, gap retry, startup sync, walk on or off | `epoch_tip.rs:534-551` vs `33b727fce:crates/state-sync/src/epoch.rs:228-246` (byte-identical, `diff`); `refused` called from `store_epoch_record` `epoch_tip.rs:738`, reached from `collect_epoch_records` `:618` and `retry_gaps` `:827`; startup sync uses `collect_epoch_records` `:404-415`; no switch read in `refused` `:236-271` |
| evidence read, then counter, then the error line (target, text, 11 fields), then main's stop, no await between | `epoch_tip.rs:236-271` (read `:247`, counter `:248`, `error!` `:251-268`, `stop_on_local_failure` `:270`); `ConflictEvidence::read` `:289-311` |
| a startup pass cut short during the read counts nothing | `epoch_tip.rs:226-229` (doc); test `test_a_conflict_cancelled_at_its_evidence_read_is_counted_once` `:2437`; commit d6992db59 body |
| every restart stops the same way | `epoch_tip.rs:233-234` (doc "repeats on every restart, since the startup sync meets the same conflict"); config doc `node.rs:429-432`; main's doc `33b727fce:crates/state-sync/src/epoch.rs:226` |
| dropped from the earlier form | BF-04a tables (3515fdd76 and c319adfac dropped; a804ce9c4 re-made as a test; "No longer exist" list: `epoch_record_conflict_halt`, `..._below_halt_threshold_total`, `tn_node.epoch_record_round_conflicts_total`, `own epoch record differs ...` line); grep gate `git grep 'conflict_halt\|below_halt_threshold\|conflict halt:\|keeps its own record' ff877fb0e -- crates` empty (BF-04a part 2); threshold `2n/3 + 1` from the earlier text line 35 |
| eviction: drop ended, then lowest epoch's; newest two never | `ev_tip.rs:606-620`, doc `:526-531`; test `test_older_rounds_do_not_evict_the_latest_close` `ev_tip.rs:4655-4660` |
| hook grammar, default 1, first n rounds, off without `test-utils` | `ff877fb0e:crates/types/src/test_hooks.rs:186-212` |
| release image builds `-p telcoin-network`; a workspace-root build has `test-utils` | `33b727fce:etc/Dockerfile:51`; `33b727fce:crates/e2e-tests/Cargo.toml:21` (normal dependency `tn-types` with `test-utils`); hook doc `test_hooks.rs:206-208` |
| e2e files | `git diff --stat b7f008dc9 ff877fb0e`: `epoch_record_walk.rs`, `fleet.rs`, `main.rs` (`mod epoch_record_walk;` `:10`, `mod fleet;` `:14`) |

## With every switch off

| claim | source |
|---|---|
| certified-prefix read per collector pass | `epoch_tip.rs:956` (`certified_prefix_end` after each pass), `:980` |
| `cert_by_digest` read per short round | `ev_tip.rs:327` |
| copy of each downloaded record and certificate for its save | `epoch_tip.rs:736-737` (`save(epoch_rec.clone(), cert.clone())`); main `33b727fce:crates/state-sync/src/epoch.rs:308` (`save(epoch_rec, cert)`); BF-04a review Info I3 |
| per conflict a read of the previous record and the evidence line | `epoch_tip.rs:289-311`, `:251-268` |
| three state-sync counters + gauge | `ff877fb0e:crates/state-sync/src/metrics.rs:44`, `:50`, `:55`, `:66` (`git diff 33b727fce ff877fb0e -- crates/state-sync/src/metrics.rs`) |
| one `tn_node` counter with switches off; recertify counter and retained gauge only with the switch | `ev_tip.rs:331` (touched by 0 on every short round); `:506`, `:888` and `:1077-1080` behind `retained` / `recertify_older_record` (switch on only: `spawn_epoch_vote_collector` `retained = recertify.then(...)`, `ev_tip.rs:666`) |
| `round` label on missed signers | `ev_tip.rs:1182-1200` |
| main evicts the oldest-queued entry, live or ended | `33b727fce:crates/node/src/manager/epoch_votes.rs:403-404` |
| eviction touches no block, state root, vote, signature or pack byte | review n34 finding 6 |
| a node with the walk on can reach a conflict; any node that meets one stops | config doc `node.rs:426-432`; stop rows above |

## Testing

| figure / claim | source |
|---|---|
| unit test names exist at the tip | `ev_tip.rs:3133`, `:4549`, `:4660`, `:4495`; `epoch_tip.rs:1888`, `:1962`, `:2498`, `:2311`, `:2360`, `:2260`, `:2437` |
| nextest 6 packages 1,952 passed, 9 skipped at 8c76745f2 | `/home/drtnarg/coding/telcoin/tn-b7-n04/target/tmp/bf04a2-nextest-tip-r2.log:1975-1976`; command `scratchpad/BF-04a-2/gates.sh:29` |
| clippy clean at 8c76745f2 (tn-config, state-sync, tn-node, tn-primary, nightly, `-D warnings`) | `bf04a2-clippy-tip-r2.log:18` EXIT=0; `gates.sh:32` |
| state-sync + tn-config 228 passed at d6992db59; clippy clean | `bf04a3-nextest.log:240-241`; `bf04a3-clippy.log:1,8` |
| state-sync 78 passed at b7f008dc9; doc comments only | `bf04a4-nextest.log:90-91`; BF-04a part 4 ("doc comments only") |
| fmt clean | `bf04a3-fmt.log`, `bf04a4-fmt.log` EXIT=0 (`fmt --all -- --check`) |
| per-commit check: 24 commits up to 8c76745f2, five packages, `-D warnings` | `bf04a-per-commit-summary.log` (01-10, ids identical to the final series), `bf04a-per-commit-summary-2.log` (11-18), `bf04a2-per-commit-summary-r1.log` (21, 3143a099d), `bf04a2-per-commit-summary-r2.log` (22-26); all EXIT=0; command and RUSTFLAGS `scratchpad/BF-04a-2/gates.sh:9,20`, `BF-04a-1/gates.sh:7,18` |
| the two after it: `cargo check` on the packages they touch | `bf04a3-check.log` (`-p tn-config -p state-sync -p tn-node -p e2e-tests`, EXIT=0; d6992db59 touches config + state-sync); `bf04a4-check.log` (`-p state-sync`, EXIT=0; b7f008dc9 touches state-sync only). RUSTFLAGS for these two not visible in the logs: the text does not claim warnings denied for them |
| e2e run tree = this head without d6992db59, b7f008dc9 | d1da5db0b^ = 8c76745f2; `cmp <(git diff d1da5db0b ff877fb0e) <(git diff 8c76745f2 b7f008dc9)` identical |
| e2e crate check, fmt, clippy clean | `/home/drtnarg/coding/telcoin/tn-b7-n04b/target/tmp/bf04b-{check,fmt,clippy}.log` EXIT=0 |
| 3 of 3 (866 s) | `/home/drtnarg/coding/telcoin/tn-b7-n04b/target/tmp/bf04b-walk.log:1,612-617,659` (head=d1da5db0b; Summary 865.974 s, 3 passed; EXIT=0) |
| two of four withhold epoch 1's record, first two rounds | `walk_tip.rs:1-15`, `:37` (K = 1), `:45-58` (WITHHOLDING, ROUNDS = 2) |
| no node logs or counts a conflict | `walk_tip.rs:499-510` (`assert_no_fatal_log` + `ROUND_FORK_LOG`, both counters 0); `ff877fb0e:crates/e2e-tests/tests/it/fleet.rs:51`, `:55`, `:67-68` (`FATAL_LOGS` = replay guard, `epoch record conflict:`, main's stop line, closing-block halt) |
| what each test asserts; epoch 3's close certifies epoch 1 | `walk_tip.rs:176-228` |
| no fleet ran this head; a benchmark of the earlier form is running, no result stated | brief w-n.md item 6 |

## Limits

| claim | source |
|---|---|
| walk never helps a node without its own record; fresh observer stops (tested) | `epoch_tip.rs:160-163` (doc), `:187`; `walk_tip.rs:194-202` |
| not examined; bounds 16 / 17 records / no receive-side lookback | earlier sources note, Limits rows (unchanged code: `MAX_RETAINED_RECORDS = MAX_RECERTIFY_LOOKBACK + 1` `ev_tip.rs:59`) |
| validation's bar: own committee's super-quorum; subset of >= 4 and >= 2/3; 10/7/5; more than f | `33b727fce:crates/storage/src/epoch_records.rs:401-417`; `33b727fce:crates/types/src/primary/epoch.rs:96-111` (super_quorum, its doc: e = 10, n = 7, quorum 5, more than f of the expected set), `:145-175` (`committee_compatible`); doc at tip `epoch_tip.rs:211-218`; #1850 comment of 2026-11-15 (the question) |
| a node holding a conflicting record stops on main when its collector asks | main rows above; `33b727fce:crates/state-sync/src/epoch.rs:217-227` (doc) |
| failed read: committee=0, no signer ids, still stops | `epoch_tip.rs:295-304` (`unwrap_or_default()`), `:313` (`committee: anchor.len()`), `:270` |
| stop skips the persist, as main's | `epoch_tip.rs:738` (`?`) before `:673-677`; main `33b727fce:crates/state-sync/src/epoch.rs:309` before `:376-381` |
| committee read after the failed save | `epoch_tip.rs:737-738` then `:247` |
| vote round's stop has no peer/signers and is not counted in mismatches | `ev_tip.rs:403-411` (no fields, no counter); main increments the counter only at `33b727fce:crates/node/src/manager/node/close_epoch.rs:740` and `crates/state-sync/src/epoch.rs:230` (`git grep final_state_mismatches 33b727fce -- crates/`); BF-04a review Info I1 |
| pick logged before marked | `ev_tip.rs:893-900` (`info!`) then `:901` (`mark_recertify`) |
| storage README "only logged" | `33b727fce:crates/storage/README.md:427-429`; unchanged by the stack (review n34 finding 3) |
| tn-reth README names main's line and counter only | `33b727fce:crates/tn-reth/README.md:1270-1278` (at the tip the paragraph is shifted by lower heads: `ff877fb0e:crates/tn-reth/README.md:1289`); review n34 finding 2 |
| five commits corrected by later ones, not squashed | BF-04a review F6 (df0075d98/3805eab5b, 0a7c8f21c/8038aa198, 8b3109ddb/64a6de4b5, f2f3de1bd/3143a099d, 9e97158b9/ba73ee5f9) |
| e2e message names `STACK_SWITCHES_ON`, added by a later head | `ff877fb0e:crates/e2e-tests/tests/it/fleet.rs:312-315`; `b7/n2-05:crates/e2e-tests/tests/it/fleet.rs:91` (`const STACK_SWITCHES_ON`); review n34 finding 4 |

## Related

| claim | source |
|---|---|
| #1850's sketch: walk, re-certify behind switches; gauge and serving peer always on; G2 on main since #1849 | `gh issue view 1850` body "What a fix could look like"; comment of 2026-11-15T11:31Z ("#1849 fixed G2 ...; G1 is unchanged") |
| #1852's sketch and open question; gauge from held cert | `gh issue view 1852` body; `ev_tip.rs:345-347` |
| next heads build on this one | `b7/n2-xf` (f5f7589f5) and `b7/n2-05` (38f00e88e) both contain ff877fb0e (brief table) |

## Left out or changed (not in the posted text)

- The earlier text's test counts (1,340 passed on an unpublished cut), its e2e run (714.5 s) and the stack-wide gates at `91a15e223`: all on the earlier cut on main at 45dce8947; replaced by this head's logs or by the gates line.
- The later head's kept-vote certificate figure (7.7-8.5 s): measured on that change's own branch before the stack moved; dropped.
- "the next benchmark runs all three switches": untrue now (two switches) and the running benchmark is of the earlier form; replaced by the brief's sentence, no result stated.
- Review n34 finding 5 (the e2e fatal-line list omits two of main's own stops; a node stopping on either still fails the tests' liveness checks) and BF-04a review Info I2 (053713719's body says "otherwise nothing changes" and omits the `cert_by_digest` read): not stated; the earlier text's "nothing found before opening this PR is left unfixed" was dropped instead, since it would now be untrue.
- Why #1849 made its change: not stated (brief).
- Whether `-D warnings` was set for the checks of d6992db59 and b7f008dc9: not visible in their logs, so not claimed.
