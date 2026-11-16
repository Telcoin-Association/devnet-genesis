# bench6-00 (#1862 body), second pass: sources

Private. Body: `tasks/pr-bodies/bench6-00-switches-obs.md`. Squash proposal: `tasks/pr-bodies/bench6-squash-1862.md`.
Removal branch read: `refactor/remove-bench-switches` at 57a55b221 in `/home/drtnarg/coding/telcoin/tn-b8-uc`.
Facts file: `tasks/bench8/pr9-facts.md` (cited below as pr9-facts, by section).
Untouched: the two stack-position lines, the merge-method sentence, the block from `Stack-wide gates` to `## Limits` (checked identical to HEAD with `diff`), the two `{{slug}}` placeholders.

## Changed sentences, old -> new, and where each fact comes from

1. Summary l.3. Old: "Adds the list the later PRs of this stack put their runtime switches into, a `node switches` log line and `tn_node_switch` gauge that show them, and three measurements the benchmark reads."
   New: same content, measurements first, "with a `node switches` log line and a `tn_node_switch` gauge that show them." No new fact.
2. Summary, new: "{{pr-09}}, the last PR of the stack, removes the switch list, the line and the gauge again, together with the six switches the later PRs add, and makes each change behind those switches the node's behaviour."
   Source: brief "What happened"; pr9-facts "What the PR is", "R5" (gone from #1862: `runtime_switches!` and its list, `Parameters::switches()`, `log_switches()`, `SwitchValue`, `switch_at_default`, the start-up line, the gauge).
3. Summary, new: "So once the stack is collapsed into #1862, `main` receives the three measurements and the stack's fixes, and none of the switch machinery."
   Source: pr9-facts R5 "Kept from #1862: the epoch-entry gauge, the digest-receipt fix, the histogram buckets".
4. Summary l.4. Old: "A switch is a top-level ..." -> New: "In this PR's diff a switch is a top-level ..." (scope only).
5. Summary l.5. Old: "No switch is defined here, and nothing a node sends, accepts, decides or stores changes." -> New: "This PR alone defines no switch and changes nothing a node sends, accepts, decides or stores; the collapsed #1862 carries the later PRs' behaviour changes to `main`." Source: body l.8 (collapse sentence).
6-9. Problem l.13. Old: "This stack carries what carries to main: each behaviour change behind a switch whose default is main's behaviour, except the closing-block check, the epoch-loop fix and one eviction rule of the collector hardening, which have none; the vote fix and the order hold wait for the next benchmark."
   New (four lines): "This stack carries what carries to main." / "In the PRs' own diffs each behaviour change sits behind a switch ..., which have none." / "Bench 7 ran the node logic of the author-side vote fix (#1868) and the order hold (#1869) on the stack's earlier cut on main at 45dce8947, once per form of the vote fix: always-on in r20261115-1131, adaptive in r20261115-1653; #1868 and #1869 report the results." / "{{pr-09}} then removes the six switches, so each fix is the node's behaviour, and of the two forms of #1868's fix it keeps only always-on."
   Sources: brief point 6 (run ids, 45dce8947, "#1868 and #1869 report its results"); `bench6-05-quorum-exec-block.md:23` ("Bench 7 ran this head's node logic, on an earlier cut of the stack on main at 45dce8947 ..., once per form ...: the always-on form in r20261115-1131, the adaptive form in r20261115-1653"); `bench6-06-digest-order-hold.md:67`; pr9-facts R3 (always-on the only form). "the vote fix ... wait for the next benchmark" is replaced because bench 7 ran; no bench 7 result is stated. No bench 7 mention in the #1864-#1867 bodies (grep), so the sentence names only #1868 and #1869.
10. Change, new lead: "Four of the twelve commits build the switch list, the `node switches` line and the `tn_node_switch` gauge (`8bbc4a009`, `d1cd20992`, `8093e1030`, `676692c6c`); {{pr-09}} removes what they add, with their tests."
   Sources: the body's own commit list (l.28-34, l.49-50); pr9-facts R5 (removed items and deleted config tests incl. `switches_list_every_switch_field`, `switch_at_default_is_not_written`, `node_switches_line_renders_yaml_tokens`; node `test_node_switch_gauge_per_switch`); `git grep -c -e NON_SWITCH_KEYS -e runtime_switches refactor/remove-bench-switches -- crates/` returns no match.
11. Change, new: "The other eight, the observability, stay." Source: pr9-facts R5 "Kept from #1862"; commits 341747929, 42655214d, dffa19ccd, 59d5db11a, 26319d169, 4917efaae, 3fbfa7428, b29d59bef are all gauge/bucket/digest-receipt commits per the body's list.
12. What changes for every node, l.58. Old: "At start: the bare `node switches` line; `tn_node_switch` has no series yet." -> New: "At start, in this PR's diff: the bare `node switches` line, and `tn_node_switch` has no series yet; after {{pr-09}} neither exists." Source: pr9-facts R5 (removed log output and metric, verbatim).
13. Same section, new: "The collapsed stack does change what a node sends and decides, and no switch turns that off after {{pr-09}}: a reviewer checks the later PRs' changes as unconditional." Source: brief point 1.
14. Same section, new: "For a fleet of old and new binaries the evidence is the rolling-upgrade test with main as the previous binary, which ran on the full stack with every switch off and with the six on (below); {{pr-09}} removes the off arms."
   Sources: the body's script-owned gates line "`make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time): passed with every switch off and with the six on."; pr9-facts "What the PR is" ("The mixed fleet is covered by `make test-upgrade` with `main` as the previous binary").
15. Testing, new: "{{pr-09}} deletes `switch_at_default_is_not_written` and `node_switches_line_renders_yaml_tokens` with the code they pin; the other four stay."
   Source: `git grep -l "fn <name>" refactor/remove-bench-switches -- crates/`: present `reserializing_keeps_the_existing_keys` (crates/config/src/node.rs), `test_engine_stage_histograms_render_sub_ms_buckets` (crates/tn-metrics/src/recorder.rs), `epoch_entry_gauge_records_rounds_behind` (crates/consensus/primary/src/tests/network_tests.rs), `test_requeued_digest_reports_its_wait_from_first_receipt` (crates/consensus/primary/src/tests/proposer_tests.rs); absent the two named.
16. Limits. Old: "No switch yet: the line is bare." / "The first switch comes with `fix/1804-vote-queue`." -> New: "In this PR's diff no switch is defined, so the line is bare; the first switch comes with `fix/1804-vote-queue`."
17. Limits, new: "{{pr-09}} removes the list, the line and the gauge with the six switches, so the collapsed #1862 brings none of them to `main`." Source: pr9-facts R5.
18. Limits, new: "This holds only inside the stack: {{pr-09}} deletes the test with the list." Source: pr9-facts R5 deleted tests (`switches_list_every_switch_field`).
19. Limits, new: "After {{pr-09}} this covers the six removed keys: a `parameters.yaml` that still names one loads, and the key is ignored." Source: pr9-facts "For operators" (`Parameters` has no `deny_unknown_fields`, `crates/config/src/node.rs:273`; loader `crates/config/src/traits.rs:47`, `:69`; test `unknown_keys_are_ignored` at node.rs:1765 at a5be61615; present on 57a55b221 per git grep).
20. Limits, new: "After {{pr-09}}, `Parameters` has the same fields and `Default` values as `main` at 0554efd4f, so the collapsed stack adds no parameter." Source: pr9-facts R5 ("the same 14 fields, the same `Default` values and `default_*` functions" against upstream main 0554efd4f).
21. Related, new: "Only this PR of the stack merges into `main`, so this list closes the stack's issues." Source: brief point 4.
22-31. The closing list (below, per issue).
32. Related, "Stacked on this" line. Old listed each PR with its switch count ("`vote_queue_fix`", "no switch", "two switches"); new drops those and adds "and {{pr-09}} (`refactor/remove-bench-switches`), which removes the six switches of #1864, #1866, #1868 and #1869 and the switch list this PR adds." Sources: brief (branch names, which PRs carry switches); pr9-facts header (branch name).

`{{pr-09}}` placed: 15 times in the body (Summary 1, Problem 1, Change 1, What changes 3, Testing 1, Limits 4, Related 4 (three Refs lines and the stacked line)). The squash proposal carries it 5 times.

## The closing list: what decided each line

Each issue read with `gh issue view <n> --repo Telcoin-Association/telcoin-network`, body and comments, on 2026-11-16.

- Fixes #1851 (#1865, verification in #1868).
  Issue "What a fix could look like": "(a) `parent_beacon_block_root == final_consensus.hash`; (b) the nonce's epoch is N; (c) `extra_data` is 32 bytes, equal to the seed when it is at hand." and "Add an info line per record built or reused ... and a counter by result."
  Issue "How to verify": "e2e: `assert_epoch_records_verify` also checks the block's 32-byte `extraData`, `parentBeaconBlockRoot == final_consensus.hash` and `getEpochInfo(N+1).blockHeight == final_state.number + 1`."
  #1865's Related gave as its only reason for `Refs`: "its e2e verification, the markers checked on chain, is in the epoch-close tests (`epoch_close_forms.rs`) of `fix/1804-quorum-exec-block`, a later head of the stack". In the collapsed #1862 that test is in the same merge. On 57a55b221 `crates/e2e-tests/tests/it/epoch_close_forms.rs` checks `getEpochInfo(E + 1).blockHeight` (doc :15), `parentBeaconBlockRoot` (:828-841) and the closing block's 32-byte `extraData` (:1098-1127), in the kept tests `test_held_member_two_closes` (:254) and `test_missed_record_round` (:261).
  Caveat: pr9-facts R3 "Not yet run: the kept e2e tests on the plain node". The checks live in `epoch_close_forms.rs`, not inside `assert_epoch_records_verify` as the issue words it.
- Fixes #1852 (#1866).
  Issue: "Before the error, check `cert_by_digest(epoch_hash)` ... If the certificate is held, log at info and count it; otherwise keep the error exactly as it is." / "Whether the signer gauge at `:238` should also skip such a round is open" / verify: "A unit test beside `test_failed_round_sets_signer_gauge`".
  #1866's Related: "Fixes #1852: every point of its sketch, including its open question: the gauge reports the held certificate's signers." #1866 Summary: the info line is outside any switch.
- Fixes #1860 (#1867).
  Issue: "It has two parts: 1. Reserve room in the engine channel before taking an output ... 2. Phase 1 of the drain applies `check_output_continuity` ..." / verify: "The test above fails on main and passes with both changes." (the fleet bullet describes what to watch, not a required run).
  #1867's Related: "both parts of its proposed fix are here, and its reproducing test passes." No switch, so the removal does not touch it.
- Refs #1804 (#1864, #1868).
  Comment of 2026-11-14: "So (D) with a floor of 8 holds in either form while the disk binds, in neither once the spread exceeds it." / "At 50,000 IOPS the spread outgrew the floor" / "Open: the form and the floor's depth". {{pr-09}} settles the form (always-on, pr9-facts R3), not the depth; #1868's body (l.104) still reads a floor of 16 from arithmetic on bench 7.
  Also not done: the test plan's "ten-validator variant, three fast and seven delayed"; the control arm "Run once on the parent commit and record that the fast validator certifies under 10 % there" (#1868's control arm is deleted by {{pr-09}}, pr9-facts R3); the comment's "New since #1842: `vote_inner` also waits under the lock ... for an attached parent parked as pending; bench 6's fix does not move that wait."
  Figures in the line: "floor of 8" (comment; `QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`, pr9-facts R3), "50,000 IOPS" and "bench 6" (comment, runs r20261113-1630 and r20261114-0000).
- Refs #1807 (#1869).
  Title: "A sealed transaction leaves the pool and the RPC, so a skipped one waits 5 minutes for a resend and a resend runs twice". Comment of 2026-11-14, "Still open": "The second defect, a resend that executes beside the original because a sealed transaction is invisible to the pool and the RPC: the hold does not touch it." and "173 re-queued batches in r20261113-1630 and 12 in r20261114-0000 never executed; why is unknown."
  Also (pr9-facts R4 and "Limits the plan already names"): the e2e control that showed the loss without the hold is gone; the hold's two untested gaps (a garbage-collection cut below the leader, a re-send after a restart). Not in the line, which names what the issue itself leaves open.
- Refs #1850 (#1866; G2 by #1849 on main).
  Comment of 2026-11-15: "#1849 fixed G2, and G1 is unchanged." / "Should the stop require a super-quorum of the full committee, 7 of the 10 members the previous record names?" / "Still open: G1."
  #1866's Limits (l.84) leaves that question open ("The stop's signer bar is main's"). G1's sketch (walk, re-certify, gauge, serving peer) is in #1866 and unconditional after {{pr-09}} (pr9-facts R1).
- Refs #1806 (this PR): unchanged reason, "(this PR)" added. Title: "A loaded epoch close waits for the seventh-fastest validator's execution backlog; slower members miss the epoch record".
- Refs #1819 (this PR): unchanged reason, "(this PR)" added. #1819 is a merged PR (time-to-land instrumentation), not an issue.
- Refs #1782 (#1864): reason from #1864's Related ("the bounded execution wait this moves") and pr9-facts R2 (the wait runs before the author lock). Kept `Refs` as the prompt directs.
- Refs #1794 (#1869): reason copied from #1869's Related ("a held digest keeps its slot in that bound until it commits").

## Squash proposal

Title, 70 characters with GitHub's " (#1862)": "fix: vote stalls, digest order and epoch records; node metrics (#1862)". Style from `git log --format=%s -12 0554efd4f` in tn-b8-uc (`fix(deps): ...`, `feat(config): ...`, free titles with "(#N)").
Two lines per PR taken from each body's Summary (bench6-01 .. bench6-06, bench6-xf), and #1862's Change list; the 1 s and 9 s bounds from #1864's Summary; the 8-entry floor from #1868's Summary; no benchmark figure except the closing list's "50,000 IOPS" (bench 6, from #1804's comment).
