# Figure-check FC-S3: #1866 (`bench6-04-collector-hardening.md`) and #1867 (`bench6-xf-epoch-loop-output-drop.md`), second pass

Verdict: FIX (one wrong label in #1866, two weak statements in #1866, one incomplete sentence in #1867; no conclusion changes).

Scope: every changed or added sentence of `git diff HEAD` (#1866: 26 sentences and one heading; #1867: 2), plus #1867 L66, which its writer raised.
Repos: `/home/drtnarg/coding/telcoin/tn-b8-uc` (#1866 head ff877fb0e, #1867 head f5f7589f5, stack top 500e21afa, removal tip 57a55b221, main 0554efd4f and 33b727fce, bench 7 image 91a15e223).
Lint (`orch-gh-post.sh lint` on copies with `{{pr-09}}` -> `#1871`, under `/home/drtnarg/.claude/jobs/e50668f4/tmp/FC-S3/`): LINT-OK on both.

## Errors

1. #1866 L59, "What a reviewer should check instead: after {{pr-09}} the walk, the kept votes and the re-certify pick are unconditional (the pick, as before, only on a member)."
   The pick is not member-only: at 57a55b221 the collector is spawned on every node (`crates/node/src/manager/node.rs:1318`, before `if is_committee_member`) and calls `recertify_older_record` for every record on the watch (`crates/node/src/manager/epoch_votes.rs:716`); `pick_recertify_record` says "Committee membership is not a filter here" (`:826-829`); a node outside the picked record's committee picks, counts `skipped` and returns without a vote (`:860-870`, doc "a pick this node may not sign counts as `skipped`").
   What is member-only is the re-vote (as L29 says, "(members only)"). The same holds at ff877fb0e (`epoch_votes.rs:878-890`).
   Replacement (#1866): `(the pick, as before, only on a member)` -> `(the re-vote, as before, only from a member of the picked record's committee)`

## Weak

1. #1866 L93, "At start-up, a node whose latest record is certified and an older one is not re-arms a vote round for the older one: in this PR's diff only with re-certify on, after {{pr-09}} unconditionally."
   Both halves hold (ff877fb0e `epoch_votes.rs:821` `else if recertify && holds_uncertified_before(…)`; 57a55b221 `:799-806` `else if holds_uncertified_before(…)`), but "an older one" is unbounded: `holds_uncertified_before` looks only at the 16 epochs before the latest (`MAX_RECERTIFY_LOOKBACK = 16`, `:56`, `:812-820`), and the collector then re-votes N-1 by the failsafe or one record of N-16..N-2 by the round-robin pick, not necessarily "the older one".
   Replacement (#1866): `a node whose latest record is certified and an older one is not re-arms a vote round for the older one` -> `a node whose latest record is certified and one of the 16 before it is not re-arms a vote round for an older uncertified record`
2. #1866 L77 with L112: L77 names bench 7's two runs without saying that both of this PR's switches were on in them; L112 then gives as a "Not `Fixes`" reason "this text reports no fleet run of either change".
   Bench 7's report (`tasks/bench7-report-r20261115-1131.md:90`, `:731`) sets `epoch_record_collect_past_uncertified` and `epoch_record_recertify` true in both runs (r20261115-1131 and r20261115-1653), so the clause is true only of what the text chooses to say.
   The result (the walk and re-certify never fired, `:568`) is stated in neither #1868's nor #1869's body, so it must stay out; the configuration is a setup fact, stated the same way by #1864's body ("with this switch on", `bench6-02-vote-queue.md:68`) and #1869's ("with the switch on", `bench6-06-digest-order-hold.md:75`).
   Replacements (#1866):
   `Bench 7 ran the stack's earlier cut on main at 45dce8947, once per form of #1868's fix:` -> `Bench 7 ran the stack's earlier cut on main at 45dce8947 with both of this PR's switches on, once per form of #1868's fix:`
   `and this text reports no fleet run of either change.` -> `and this text reports no fleet result of either change.`

## Incomplete (the writer's question, item G)

#1867 L66, "- Not run: no e2e test drives the race through the real loop, and no fleet has run this head yet."
Not false: this head (f5f7589f5, on 33b727fce) has not run on a fleet.
Incomplete: bench 7's image 91a15e223 carries all seven node commits of this head (`git log --oneline 45dce8947..91a15e223`: `1c2af644f`, `19239c515`, `e247d3130`, `a876f66e6`, `caba85bf3`, `ab980e106`, `a2c4dfae9`; not the e2e commit), and the fix has no switch, so bench 7 ran it; L65 already says that cut has "the same seven node commits", and #1865's and #1866's bodies now name bench 7.
Recommended replacement (#1867), states no result and matches #1865's wording (`bench6-03-closing-block-check.md:59`):
`and no fleet has run this head yet.` -> `and no fleet has run this head.` followed by a new continuation line `  Bench 7 ran the stack's earlier cut on main at 45dce8947, which carries the same seven node commits, on 2026-11-15: [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/) and [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/), ten validators at 20,000 IOPS, one run each; #1868 and #1869 report its results, and this text reports none of them.`

## Checked and right (#1866)

- L3-L4, L50-L51: two switches, both default off at ff877fb0e (`crates/config/src/node.rs:565-566`); removed by `a5be61615` (walk) and `b67c0acdd` (re-certify); no runtime switch list left at 57a55b221 (`57a55b221` "remove the runtime switch list"; no `runtime_switches` in `crates/`).
- L52: no `deny_unknown_fields` on `Parameters` (only `crates/config/src/network.rs:127`, `:152`, `network/trusted.rs:13`); `unknown_keys_are_ignored` (57a55b221 `crates/config/src/node.rs:1274`) parses a parameters file with two unknown keys through `serde_yaml` to the same `Parameters` as without (it names generic keys, not these two; serde ignores any unknown key the same way).
- L6, L54: the eviction is the one change with every switch off in this diff (the start-up re-arm and the pick sit behind `recertify` at ff877fb0e `:666`, `:729`, `:821`; the walk behind `past_uncertified`, `state-sync/src/epoch.rs:113`).
- L56: `node switches` line removed by `e8dfcce10`; no `node switches` anywhere at 57a55b221.
- L59 (but for Error 1): walk unconditional at 57a55b221 (no `past_uncertified` in `crates/`); kept votes unconditional (`epoch_votes.rs` `let retained = RetainedEpochVotes::default();` in `spawn_epoch_vote_collector`); pick unconditional (`:716`).
- L61: the two e2e tests exist at 57a55b221 (`epoch_record_walk.rs:179`, `:197`); the gates block (L84-L85, unchanged) says the make targets and `make test-upgrade` with main at 33b727fce as previous binary ran with the six switches on.
- L63-L65: same claims as the old sentences; main's failsafe re-votes only N-1, as a switch-off node does.
- L72 (item C): 27 commits in `c2f266b9c..ff877fb0e`; `8c76745f2` is the 24th oldest; `d6992db59` and `b7f008dc9` are the 25th and 26th; `ff877fb0e` (the 27th) is the e2e commit. The new wording claims what the old one did ("24 up to and including" = "the 24 commits up to"; "the next two" = "the two after it"), names the two commits and adds that the 27th is the e2e commit, for which it claims no check; the gate results themselves were not re-run.
- L75 (item D): `test_uncertified_epoch_stops_the_collector_with_every_switch_off` at ff877fb0e `epoch_record_walk.rs:190`, gone at 57a55b221 (removal commits touching the file: `a5be61615`, `b67c0acdd`, `1d41981dd`); the other two stay.
- L76-L77 (item E, but for Weak 2): this head has not run on a fleet; run ids, date-free wording, 45dce8947, "once per form of #1868's fix", always-on and adaptive match #1862's (`bench6-00` L17), #1865's (`bench6-03` L59) and #1868's (`bench6-05` L28) bodies; no result stated. No other sentence of the body becomes false: L16 "No run reached this state" stays true for bench 7 too (bench 7 report `:568`: no walk past an uncertified epoch, no re-certify round, on any node in either run).
- L93-L94 (item B1): main's test `test_startup_revote_skips_certified_record` exists on 0554efd4f (`epoch_votes.rs:691`) and 33b727fce (`:684`), and at ff877fb0e and 500e21afa (`:1274`, with `false`); deleted by `b67c0acdd`, absent at 57a55b221. It stores epoch 0 uncertified and epoch 1 certified and asserts the watch stays empty: exactly the shape the sentence names.
- L95 (item B2): at 57a55b221 a short round's recovery that downloads a valid record with another digest logs `… we have forked!` at error and calls `node_shutdown.notify()` (`epoch_votes.rs:393-405`), whatever the record's epoch (doc `:139-143`; test `test_recertify_round_stops_on_a_conflicting_record`, `:4413`); the round returns `Ok` (`:145-146`) and the collector returns `Ok(())` on the shutdown (`:661`), so the node stops. Nothing is saved on the conflict (only in-memory kept votes are dropped, `:441-444`), so the record stays stored uncertified; on restart `revote_uncertified_epoch_record_on_startup` writes the latest record to the watch (`:786-806`), the collector runs the pick (`:716`), and `pick_recertify_record` is deterministic (`epoch % count`, `:835-840`), so the same record is picked at the same latest epoch, and later closes reach it round-robin: "a later pick stops it again" follows. After the merge with 0554efd4f the round ends with an error instead (body L89, #1861): still a stop.
- L96: at ff877fb0e the pick runs only with `recertify` (`:729`); at 57a55b221 for every node, re-vote for members.
- L97 (item B3): no e2e test at 57a55b221 other than `epoch_record_walk.rs` uses the withhold hook; `upgrade.rs` has no uncertified epoch. The possible follow-up test in `upgrade.rs` (older-block headers) would not make it false.
- L107: `STACK_SWITCHES_ON` is in `fleet.rs` and three more e2e files at 500e21afa, nowhere at 57a55b221.
- L111-L112 (item F, but for Weak 2): #1850's sketch is the walk, re-certify, G2 (fixed by #1849, per its comment) and the always-on gauge and peer; it says "A node without K cannot check K's `next_committee`, so letting it cross needs a protocol decision" and "Only this [re-certify] reaches a fresh node": the first reason names something the issue leaves open. Its "How to verify" asks for a benchmark run (every node's gauge at the last closed epoch within about 10 s of the first quorum): the second reason is true in that sense. #1862's body (L128) names a different open point, the comment's super-quorum question; #1866's clause does not contradict it.
- L113: #1852 asks for the store check, info line and count, and leaves the signer gauge open; `053713719` does all three and sets the gauge from the held certificate (body L26), still at 57a55b221 (`epoch_votes.rs:335`); test `test_failed_round_with_a_held_cert_logs_info_and_counts` at 57a55b221. #1862's body carries `Fixes #1852` (L124), and #1862 is the only PR targeting `main` (body L7): the parenthesis is true.
- L114 (item H): #1867, #1868, #1869 in order, `{{pr-09}}` last.
- Heading "The switches, and where they go": matches the section.

## Checked and right (#1867)

- L91 (item G): #1862's body has `Fixes #1860: both parts of its proposed fix, and its reproducing test passes (#1867)` (L125); #1860 asks for two parts (reserve before taking the output; Phase 1 continuity check with count, error and stop), both in this head; the parenthesis is true.
- L94 (item H): `fix/1804-quorum-exec-block` is #1868 and `fix/1807-digest-order-hold` #1869 (stack list), `{{pr-09}}` last; complete.

## Notes (no change asked)

- The two "Next:" lines use different forms (numbers only in #1866; branches with numbers in #1867); same facts.
- #1866's unchanged Testing list (L70) names `test_startup_sync_walks_under_the_switch_and_stops_on_a_conflict`, true of this diff; `a5be61615` renames it to `test_startup_sync_walks_past_its_own_uncertified_epoch_and_stops_on_a_conflict`.

## Not traceable

None. The gate results in L72 were not re-run (older results; only the wording was compared, as asked).

## Rule breaches

None in the changed lines: no unit name, private path, host, person, project id, IP address, tool or assistant mention, bold, or second sentence on a line.

## Counts

Statements checked: 30 (#1866: 26 sentences and the heading; #1867: 2 and L66).
Matched: 26. Wrong: 1 (#1866 L59). Weak: 2 (#1866 L93; #1866 L77 with L112). Incomplete: 1 (#1867 L66). Untraceable: 0.
