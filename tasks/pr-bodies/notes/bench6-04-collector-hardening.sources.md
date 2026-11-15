# Sources: PR 04 `fix/epoch-record-collector-hardening` (not posted)

Text: `tasks/pr-bodies/bench6-04-collector-hardening.md`.
Repository read-only at `/home/drtnarg/coding/telcoin/telcoin-network`; head 07cdc51e5 (07cdc51e5b28bd8b582afc65ce06904ee2492df7), previous head 1e38f1882 (1e38f1882fdb7d96c85db6294b4080ad9d14302e); `git log --reverse 1e38f1882..07cdc51e5` = 28 commits.
Final text: 1,300 words by `wc -w`, all 28 short ids present, `orch-gh-post.sh lint` LINT-OK.
Head code read from `git show 07cdc51e5:<path>` (copies in the unit's scratch: `epoch_head.rs` = crates/state-sync/src/epoch.rs, `ev_head.rs` = crates/node/src/manager/epoch_votes.rs).

## Summary and Change

| claim | source |
|---|---|
| three switches, default false | `07cdc51e5:crates/config/src/node.rs:359,377,407` (fields), `:533-535` (Default), `:736-738` (runtime_switches! order, before vote_queue_fix) |
| request_epoch_cert returns the responder's BLS key; `peer`, `signers` on both `retrieved cert` lines | commit 2945ab3f9 message; contract §2.4 rows 1-2 |
| gauge `tn_state_sync.epoch_records_certified_through`, -1 while epoch 0 has none | commit 291cdfcc3 message; contract §3.4 row 1 |
| held-cert info line text, counter, gauge from held cert, alarm skipped, recovery still runs | `ev_head.rs:317-358` (line :335, counter :324, gauge :338-340), alarm gate `:457-461`, recovery after both branches `:359` on; review report 2a (E2 bullet) |
| round-robin pick among N-16..=N-2, `epoch % count` | `ev_head.rs:866-889`; `MAX_RECERTIFY_LOOKBACK = 16` `:56` |
| a node outside the record's committee signs nothing (counts `skipped`) | `ev_head.rs:906-911` |
| startup re-arm behind a certified latest record | `ev_head.rs:836-852` |
| round classed at start by epoch vs newest record (`epoch + 2 <= latest` = re-certify) | `ev_head.rs:1099-1113`; commit 7c3bac9f0 |
| kept quorum aggregated (V11) | commit 62c0beea8; contract §2.4 `epoch record certified from kept votes` |
| alarm waits; conflict drops kept signatures | commit 02e891783; `ev_head.rs:463-469`, `:527-528` |
| re-certify stop needs halt on + full-committee super-quorum; line and counter | commit 922822cfa; `ev_head.rs:395-416`; contract §2.4 and §4 rows |
| newest and previous record keep main's stop | `ev_head.rs:417-425` (else branch = main's "we have forked!" + notify); config doc `node.rs:354-355` |
| walk: own uncertified, not epoch-0 dummy; next validates against own record; gap at most 16 | `epoch_head.rs:153-195` (`may_walk_past`), `MAX_UNCERTIFIED_GAPS = 16` `:62`; commit d675e2e91 |
| gap retry: 5 s deadline, shutdown, one request of up to three peers per gap | `GAP_RETRY_DEADLINE` `epoch_head.rs:73`; config doc `node.rs:366-371`; commits 54bd8ccbd, 7f7c8e91d |
| failed read keeps a gap (V9), refusal after a walk persists (V8), unlanded walk once per interval, collector only (V7) | commits 6fae23519, c9c7efb2e, be79002ef; config doc `node.rs:371-374`; `epoch_head.rs:180-186`, `:675` |
| halt threshold `committee * 2 / 3 + 1` of the anchor (full previous next_committee); 7 of 10, 3 of 4; 5 of 10 validates but does not halt | `epoch_head.rs:343-349`; `:305-341` (anchor read); config doc `node.rs:383-389`; commit e552ed3be |
| halt line verbatim, 13 fields, error returned, below-threshold counter | `epoch_head.rs:243-305` (text `:262-275`, fields `:276-291`, counters `:252`, `:258-260`); contract §2.4, §3.4, §4 |
| halt ends the collector / fails startup, repeats on restart | config doc `node.rs:389-391`; `epoch_head.rs` doc `:229-233` |
| recovery: switch off and restart; node logs, counts, keeps its own record | review report 2g answer 2 ("Recovery short of a resync: turn the switch off and restart; ... keeps running on its own record (main's behaviour)"); `epoch_head.rs:270-274` (`this node keeps its own record`), `:302-304` (non-halt path = `stop_on_local_failure`) |
| pre-flight | config doc `07cdc51e5:crates/config/src/node.rs:400-404` (both counters, difference = would stop, grep `epoch record conflict:` and the re-certify line, one node at a time) |
| eviction: main pops the front at `len() >= 5`; head drops ended entries then evicts the lowest epoch at `len() >= 5` | main `45dce8947:crates/node/src/manager/epoch_votes.rs:403-406`; head `ev_head.rs:543-548` (doc), `:627-638` |
| hook grammar, default 1, read once, constant off without tn-types test-utils | commit 03780ee80 (`crates/types/src/test_hooks.rs` `#[cfg(feature = "test-utils")]` / `not(...)` arms); contract §5 rows 8-9 and the protection paragraph; E5a note |
| release build does not enable test-utils | `07cdc51e5:etc/Dockerfile:51` (`cargo build -p telcoin-network --bin telcoin-network --release --locked`, features only from CARGO_FEATURES) |
| fleet.rs: fleet, load, switch check, fatal lines, readers | commit 07cdc51e5 message; E2E-R note |

## Problem

| figure / claim | source |
|---|---|
| collector ends the pass at the first epoch it cannot store | `45dce8947:crates/state-sync/src/epoch.rs:343-345`; issue #1850 "Where in the code" |
| peers serve a record only with its certificate | `45dce8947:crates/consensus/primary/src/network/handler.rs:1909-1919` (checked) |
| failsafe re-votes only the previous record | `45dce8947:crates/node/src/manager/epoch_votes.rs:483-502` (checked) |
| conflicting save refused and logged | `45dce8947:crates/state-sync/src/epoch.rs:279-280` (checked) |
| vote round's recovery fork stop | `45dce8947:crates/node/src/manager/epoch_votes.rs:279-289` (checked) |
| quorum error with no store check | `45dce8947:crates/node/src/manager/epoch_votes.rs:231-237` (checked) |
| "no metric reports which certificates a node holds" | issue #1850 body, "Evidence", last line |
| 37 closes, all with at least 7 of 10 | `tasks/bench6-report-r20261113-1351.md:391` (31 closes of runs 1 and 2 + 6 of run 2b); PR 03 text uses the same 37 |
| r20261113-1630's 18:22:19 close with exactly 7 votes | issue #1850 body, "Evidence" ("The closest call") |
| 11 quorum errors, each after the collector had stored the certificate | issue #1852 body, "Evidence"; report `:54` |

## Testing

| figure | source |
|---|---|
| unit test names | `07cdc51e5:crates/state-sync/src/epoch.rs` and `crates/node/src/manager/epoch_votes.rs` (grep `fn test_`) |
| 6 and 7 signers of 10 in the threshold test | commit 7f7c8e91d message |
| gate on e5121e7e1: check EXIT=0, 1,340 passed, 7 skipped, the five packages | `/home/drtnarg/coding/telcoin/tn-b7-stack/target/tmp/head04node-e5121e7e1.log:1,24,26,1395-1396`; orch checkpoint 22:27Z entry |
| e5121e7e1 vs head: doc comments (config node.rs, e2e lib.rs), CLI README, e2e test files | `git diff --stat e5121e7e1 07cdc51e5` (6 files; node.rs and lib.rs hunks are `///`/`//!` lines only); ledger line 51 |
| e2e crate check/fmt/clippy clean on this tree | E2E-R note "check 2" (`e2er-{check,fmt,clippy}-04.log` EXIT=0); tree of c32a58efc = tree of 07cdc51e5 (`f6721a7f7…`, `git rev-parse`) |
| walk tests 3 passed, 714.5 s, four-switch line | `/home/drtnarg/coding/telcoin/tn-b7-p2/target/tmp/e2er-lane-04.log:28-32`; E2E-R note "check 4" |
| what each e2e test asserts; K = 1; ROUNDS = 2; about four minutes each | `07cdc51e5:crates/e2e-tests/tests/it/epoch_record_walk.rs:1-15, 35-58, 190-240`; commit 07cdc51e5 message; lane log per-test 225-262 s |
| later head: kept-vote certificate 7.7-8.5 s after release | ECF note, notes line "C finding"; `206a1a594:crates/e2e-tests/tests/it/epoch_close_forms.rs:1066-1080` (recertify on) |
| next benchmark: all three switches on, ten validators and an observer | launch prompt (the plan); orch 05:53Z local image trial shows the seven-switch line |

## Limits

| claim | source |
|---|---|
| walk never helps a node without the record; fresh observer still stops (asserted) | `epoch_head.rs:163-169`; walk test doc `epoch_record_walk.rs:221-226` |
| consensus catch-up through an uncertified epoch not examined | review report "What I did not examine" bullet 4; issue #1850 "Undetermined" |
| gossip filter for former members' votes not read | review report Info bullet 8 and "What I did not examine" bullet 3 |
| bounds: 16 gaps, 17 records ~34 KB for ten validators | review report 2d last bullet; `ev_head.rs:59` |
| receive side has no lookback; one BLS verify per (author, epoch) per epoch run, one round per uncertified epoch | review report 2g answer 4, Info bullet 6 |
| permanently uncertified epochs hold gap slots; in-memory state lost on restart | review report Info bullet 10, 2e |
| V5: turning the halt on stops a node already holding a conflict | review report V5 |
| F2 failed anchor read counted below threshold (fails open; pre-flight undercounts) | E3-FU review file Q1 and Findings line; orch 20:28Z "NOT FIXED" |
| F6 halt `?` skips end-of-pass persist | E3-FU review file Findings line |
| F3 anchor re-read after save, epoch-0 dummy replacement only | E3-FU review file Q1 ("TOCTOU") |
| Byzantine answers | review report 2g answers 1-5, 2d |
| e2e production note: log before mark | E5b review Q4 (L2, `epoch_votes.rs 874-923 vs 521` at its base); `ev_head.rs:913-923` (info! then `mark_recertify`) |
| every before-PR finding fixed (V1, V2, V3, V4, V7, V8, V9, V10, V11, V12) | commits 922822cfa, 54bd8ccbd, ab5ce554c, e552ed3be, be79002ef, c9c7efb2e, 6fae23519, 7c3bac9f0, 62c0beea8, 3e03978c5; V5 = pre-flight doc |

## Related

| claim | source |
|---|---|
| #1850 fix sketch points and "How to verify" (benchmark: gauge within ~10 s) | `gh issue view 1850` body, "What a fix could look like", "How to verify"; no comments |
| #1852 fix sketch points | `gh issue view 1852` body; no comments |

## Left out (untraceable or contradicted)

- E4-FU reviewer's Info notes I1-I4: recorded only in that unit's hand-back, not on disk.
- Commit messages c53f3acfb, f44c117ec, 7bf1fc406, d675e2e91 say bench 6 (r20261113-1351) left an epoch uncertified on every node; 03780ee80 says bench 6 got there by stopping two validators. Issue #1850 and the report (every close certified with at least 7 of 10) say the path was never reached. The text follows the issue.
- Commit a8b70d847 says r20261113-1351 had eleven such errors; issue #1852 says 11 across three runs (3 in r20261113-1351). The text follows the issue.
- Commit ab5ce554c says the eviction differs "only when a fifth round would be queued beside four others"; the code (both sides) evicts at `len() >= 5`, i.e. when a round is queued while five are queued. The text follows the code.
- The E5b run-1 timelines (scratch) were on pre-review code; no timing from them is used.
- Gathered but cut for length (not in the posted text): r20261113-1630's 18:22:19 close with exactly 7 votes, the 34 KB bound, "about four minutes each", the 13 other unit-test names.
- "eleven nodes" for the next benchmark = ten validators and one observer (launch prompt; bench 6 fleet shape in issue #1850 "Evidence").
