# FC-S1: figure-check of #1862's body (second pass) and the proposed squash message

Files: `tasks/pr-bodies/bench6-00-switches-obs.md` (32 changed or new sentences), `tasks/pr-bodies/bench6-squash-1862.md` (all lines).
Read against: the removal branch at 57a55b221, #1862's head b29d59bef, base 33b727fce, upstream main 0554efd4f (all in tn-b8-uc); issues #1851, #1852, #1860, #1804, #1807, #1850 (body and comments, 2026-11-16); the other seven bodies.

VERDICT: FIX (one error, five weak items; every closing keyword stays as written).

## Closing keywords

- Fixes #1851: KEEP. Every ask of the issue is at 57a55b221.
  - Pure check (a) beacon root, (b) nonce epoch, (c) 32-byte extra_data / seed: `closing_block_check` (#1865), on the build path before the committee read and `save_record`, on the stored paths, at entry ((c) by length only; the issue asks the seed "when it is at hand") and on the re-derive path.
  - adiri skip: `the_closing_marker_is_skipped_only_for_adiri_early_epochs` (crates/node/src/manager/node/close_epoch.rs:3225).
  - Info line per record and a counter by result: `epoch record published` and the check counter by `result` (named in crates/e2e-tests/tests/it/epoch_close_forms.rs:88-117, read there by `assert_close_checks`).
  - Unit asks: `a_closing_block_without_its_markers_stops_the_build_before_the_save` (close_epoch.rs:3346) fails each of (a), (b), (c) alone on the build path, the earlier block of the closing output included, and asserts nothing saved or published; stored and entry paths with a matching final_state and a wrong marker: `a_stored_record_without_the_closing_markers_stops_the_close` (:3503), `epoch_entry_stops_on_a_closing_block_without_the_records_markers` (:3584); genuine-header helper: `a_closing_block_the_engine_builds_passes_the_check` (:3259) and main's guard tests rebuilt with markers.
  - e2e ask (32-byte extraData, parentBeaconBlockRoot == final_consensus, getEpochInfo(N+1).blockHeight == final_state.number + 1): `check_record_on_chain` (epoch_close_forms.rs:1101-1137) with `closing_block_from_chain` (:1177-1185, closing block = `getEpochInfo(E + 1).blockHeight - 1`, final_state compared at :1105), reached through `check_closed_epoch` (:776, :810) from both kept tests: `test_held_member_two_closes` (:254, records 0 and 1 at :377-378) and `test_missed_record_round` (:261, every closed epoch at :557). The file was added inside #1868's range (38f00e88e), so "the epoch-close tests #1868 adds" is right.
  - Nuance, not an error: the checks sit in `check_record_on_chain`, used by these two tests, not in `assert_epoch_records_verify` as the issue words it.
  - Not run on the removal branch: the line says the verification "is in" those tests; it states presence, not a pass, and implies none. The only pass on record is the unchanged stack-wide gate line (13 e2e tests at 500e21afa, three runs each). Since the closing keyword rests on these two tests, they should pass on the removal head before #1862 merges.
- Fixes #1852: KEEP. Ask: check `cert_by_digest` before the error, info and count if held, error otherwise; open question on the signer gauge; a unit test beside `test_failed_round_sets_signer_gauge`.
  At 57a55b221: crates/node/src/manager/epoch_votes.rs:321 (`cert_by_digest`), :335 (info line), :337 (gauge reports the held certificate's signers), :347 (error kept otherwise); tests `test_failed_round_with_a_held_cert_logs_info_and_counts` (:3075) and `test_failed_round_signer_gauge_follows_a_held_cert` (:3141), beside `test_failed_round_sets_signer_gauge` (:2780).
  The merge of 0554efd4f conflicts in this file (#1861); the body's unchanged gate line says the trial merge keeps both sides.
- Fixes #1860: KEEP. Ask: (1) reserve before taking an output; (2) Phase 1 of the drain applies `check_output_continuity`, skips a forwarded output, counts the gap, logs and stops; verify: the reproducing test passes.
  At 57a55b221: `to_engine.reserve().await` (crates/node/src/manager/node/run_epoch.rs:720, :799); drain continuity (close_epoch.rs:550) and `tn_node.leftover_output_gaps_total` (:565); `a_mode_change_while_the_engine_is_full_loses_no_output` (run_epoch.rs:3372). The issue's fleet bullet describes what to watch, not a required run.
  "its reproducing test passes" is #1867's own result; not re-run here (no cargo).
- Refs #1804: KEEP `Refs`; clause true but incomplete (Weak 2).
- Refs #1807: KEEP. The clause is the comment of 2026-11-14's "Still open" list, both points, in its words. The body's proposals (A)/(B) and their test plan were superseded by the same comment ("neither is on main or being ported"); nothing else the issue asks is missing.
- Refs #1850: KEEP `Refs`; clause true but narrower than #1866's own reason (Weak 3).
- Refs #1806, #1819, #1782: KEEP (consistent with #1864's Related and with d2b80ced5 "a voter always waits for execution before the vote lock"). Refs #1794: KEEP; wording, Weak 4.

## Errors

1. Body l.33, Change lead: "{{pr-09}} removes what they add, with their tests."
   Source: `8bbc4a009` adds `reserializing_keeps_the_existing_keys`, `unknown_keys_are_ignored` and their helper `parse_with` (`git log -S` on 33b727fce..b29d59bef); all three are at 57a55b221 (crates/config/src/node.rs, the only diff of that file against 0554efd4f besides one doc line). The body itself says so at l.79-80 and l.112-113 ("the other four stay"; "now pinned by `unknown_keys_are_ignored`").
   Replace: `{{pr-09}} removes what they add, with their tests.` → `{{pr-09}} removes what they add, with their tests, except two tests of \`8bbc4a009\` that pin main's parsing and stay: \`reserializing_keeps_the_existing_keys\` and \`unknown_keys_are_ignored\`.`

## Weak

1. Body l.75: "For a fleet of old and new binaries the evidence is the rolling-upgrade test ..., which ran on the full stack with every switch off and with the six on (below); {{pr-09}} removes the off arms."
   The "six on" set of that gate had `quorum_exec_block_starved_rounds: 4`, the adaptive form, which {{pr-09}} deletes; the always-on form it keeps did not run in the upgrade test. #1868's body (l.123, l.125) says the test slows no node, so an upgraded proposer names its own tip almost always and nothing asserts that a voter on main voted for a header naming an older block; "Whether a test of that point is added ...: see {{pr-09}}".
   Replace: `which ran on the full stack with every switch off and with the six on (below); {{pr-09}} removes the off arms.` → `which ran on the full stack with every switch off and with the six on (below), the author's rule there in its adaptive form, which {{pr-09}} deletes; #1868's limits say what that test does not cover, and whether a test of it is added: see {{pr-09}}.`
2. Refs #1804 (body l.126, squash l.35): "left open: the depth of the floor of 8, ..." is what the comment of 2026-11-14 leaves open once the form is settled ("Open: the form and the floor's depth"), but the same comment also says: "New since #1842: `vote_inner` also waits under the lock ... for an attached parent parked as pending ...; bench 6's fix does not move that wait." #1864's body (l.84) says it stays under the lock; 57a55b221 pins it (`vote_newer_request_waits_for_pending_parent_wait`, crates/consensus/primary/src/tests/network_tests.rs:6631). The test plan's ten-validator e2e variant (conditional on a validator-count fixture) is not at 57a55b221 either.
   Replace in both files: `left open: the depth of the floor of 8, which the executors' spread outgrew at 50,000 IOPS in bench 6.` → `left open: the depth of the floor of 8, which the executors' spread outgrew at 50,000 IOPS in bench 6, and the wait for a pending parent that #1842 put under the vote lock, which #1864 does not move.`
3. Refs #1850 (body l.128, squash l.37): the super-quorum question is genuinely open (comment of 2026-11-15, unanswered; #1866 l.101 "The stop's signer bar is main's"), but #1866's own reason for `Refs` (l.112) is different: "a node without the record still needs re-certification, and this text reports no fleet run of either change"; the issue's verification asks for a benchmark run (the gauge at the last closed epoch within about 10 s of the first quorum). The two bodies should give the same reason.
   Replace in both files: `left open: the question in its comment, whether that stop should need a super-quorum of the full committee.` → `left open: the question in its comment, whether that stop should need a super-quorum of the full committee; a node without its own record of the epoch still needs re-certification, and no fleet run of either change is reported (#1866).`
4. Refs #1794 (body l.132, squash l.41): "a held digest keeps its slot in that bound until it commits" is copied from #1869's Related; here "that bound" follows the #1782 line and reads as the execution wait. Name the bound (not checked against #1794's text: no read of #1794 in budget).
   Replace in both files: `Refs #1794: a held digest keeps its slot in that bound until it commits (#1869).` → `Refs #1794: a held digest keeps its slot in #1794's bound until it commits (#1869).`
5. Squash message.
   - Title "fix: vote stalls, digest order and epoch records; node metrics": 62 characters, 70 with " (#1862)": within 72. Form: the last 15 subjects on 0554efd4f use a scoped prefix (`fix(primary):`, `fix(deps):`, `feat(config):`) or, for multi-area PRs, a plain title (#1861, #1859, #1855, #1849, #1834); an unscoped `fix:` appears in none. Optional: `Vote stalls, digest order, epoch records: fixes and node metrics` (64, 72 with suffix).
   - l.38-39 "(this PR)" is ambiguous in a message that names every PR: `(this PR).` → `(#1862).` (two occurrences: replace each with its own line as old string: `Refs #1806: the epoch-entry gauge measures how late a member enters an epoch (this PR).` and `Refs #1819: its digest-wait histogram now counts across re-queues (this PR).`).
   - Omissions against the bodies' Summaries (optional): #1866 also adds "an evidence line and a counter in front of main's stop on a conflicting certified record"; #1868's bounds also include "never older than the block the epoch opened on".

## Checked and matched (selected)

- Summary l.3-7: three measurements stay (`tn_primary_epoch_entry_rounds_behind`, first-receipt digest wait with `oldest_requeue_wait_ms`, `SUB_MS_SECONDS_BUCKETS` in crates/tn-metrics/src/recorder.rs); `git grep -i 'node switches\|tn_node_switch\|runtime_switches\|SwitchValue\|switch_at_default\|NON_SWITCH_KEYS\|log_switches' 57a55b221 -- crates` finds only two unrelated doc comments ("before the node switches to it", storage/consensus.rs:1222, telcoin-network-cli/src/db.rs:1944). Besides the measurements, #1862's diff leaves only the two config tests of Error 1; node/src/metrics.rs and manager/node.rs carry none of #1862's lines at 57a55b221.
- Change l.33-34 (C): the four commits are exactly the switch machinery (8bbc4a009 list and `SwitchValue`, d1cd20992 `switch_at_default`, 8093e1030 line and gauge, 676692c6c NON_SWITCH_KEYS doc); none of their identifiers is at 57a55b221. The other eight stay: every function and test they add is at 57a55b221, and the removal (500e21afa..57a55b221) deletes none of their lines (its one hunk beside `proposed_first_received` drops #1869's `order_hold.is_some()` condition; one #1862 test-fixture line was rewritten by #1869 before the removal).
- Limits l.114 (D): `git diff 0554efd4f 57a55b221 -- crates/config/src/node.rs` changes one doc line of `vote_timeout` and adds the two tests; fields, serde attributes and `Default` equal main's.
- l.66, l.80, l.109, l.111, l.113: match 57a55b221 (tests and machinery absent, `unknown_keys_are_ignored` present, no `deny_unknown_fields`).
- l.17-18: matches #1868 l.28 (runs, 45dce8947, forms); #1869's own bench 7 sentence not re-opened.
- l.133: six switches = `vote_queue_fix` (#1864), `epoch_record_collect_past_uncertified`, `epoch_record_recertify` (#1866), `quorum_exec_block`, `quorum_exec_block_starved_rounds` (#1868), `digest_order_hold` (#1869), per the list at 500e21afa.
- Squash l.11-12: "A node needs `vote_timeout` below 9 s to start" holds at 57a55b221 (adecca691 drops only the looser 10 s check; crates/config/src/consensus.rs:553 keeps the 9 s one). l.24's three `header proposed` fields match 57a55b221 (`exec_policy` is gone). l.29-30 match the removal log and D.
- "50,000 IOPS" (body l.126, squash l.35): #1804's comment of 2026-11-14, "At 50,000 IOPS the spread outgrew the floor", same meaning (bench 6, not a bench 7 result). #1868's body uses 50,000 IOPS only for the two forms differing (l.26, l.118), no conflict.

## Not traceable

- "its reproducing test passes" (#1860) and the #1851 unit tests at 57a55b221: present by name; no test run here (no cargo).

## Rule breaches

None: no unit name, private path, host, person, project id, IP, assistant or tool mention, attribution or bold in running text; one sentence per line.
Lint (on copies with `{{pr-09}}` → #1871): body LINT-OK (resolved `{{epoch-record-closing-block-check}}` → #1851, `{{execute-and-persist-in-series}}` → #1853); squash LINT-OK.

## Counts

Statements checked: 32 in the body, 24 in the squash message (56). Matched: 49. Wrong: 1 (Error 1). Weak: 5 items (8 strings across both files). Untraceable: 1. Closing keywords: 3 Fixes kept, 7 Refs kept.
