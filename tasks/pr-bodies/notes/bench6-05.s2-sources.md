# Second-pass sources: tasks/pr-bodies/bench6-05-quorum-exec-block.md (#1868; not for posting)

Pass: bench 8, the switches go in the ninth PR (`{{pr-09}}`, literal token, replaced by the orchestrator).
Sources: B = `tasks/bench8/briefs/w-s.md`; F = `tasks/bench8/pr9-facts.md` (R3 l.50-61, R2 l.47, "What the PR is" l.7-11); the body itself (line numbers below are the body BEFORE this pass unless "now"); first-pass note `notes/bench6-05.sources.md` for code lines it already maps.
No new figure, run id or commit id was added; the figures repeated (0.85, 128, 64, 8, 20,000 IOPS) are the body's own or F's.

## Summary (old l.3, l.5; new block now l.9-12)
1. l.3 old: "Adds two runtime switches for the author's side of #1804: ... off like every switch of the stack; at the defaults every header names the proposer's own newest executed block, as on main."
   new: "Adds the author's side of #1804 behind two runtime switches, ...; in this PR's diff, at the defaults, every header names the proposer's own newest executed block, as on main."
   Source: B point 1 (wording "in this PR's diff"); facts unchanged from the old sentence.
2. l.5 old: "... the one the repository owner chose as the default after bench 6 and bench 7, so turning the fix on is `quorum_exec_block: true` and nothing else."
   new: "... the one the repository owner chose, after bench 6 and bench 7, as the only form that ships."
   Source: F "What the PR is" ("of the two forms of the #1804 fix only always-on ships"); F R3 "Why".
3. new: "{{pr-09}}, the last PR of the stack, removes both switches and makes the always-on form the node's behaviour; once the stack is collapsed into #1862 there is no switch."
   Source: B point 1 and "What happened"; F R3 "Gone: `quorum_exec_block`, `quorum_exec_block_starved_rounds`"; #1862 as collapse target: body l.10.
4. new: "{{pr-09}} also deletes the adaptive form: its window, its reset streak, its two constants (the 128-header cap and the 64-header streak) and their tests."
   Source: F R3 "Gone: ... the `ExecBlockPolicy` window-and-streak state ..., `QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`, `QUORUM_EXEC_BLOCK_RESET_STREAK`"; F R3 "Deleted unit tests" (eight tests). Values 128 and 64: body l.6 ("doubling up to 128", "after 64 certified tip headers in a row"), l.46 (`5de0491a1`: 64 in a row), l.48 (`2720304e9`: above 128 lowered to 128); code lines in `notes/bench6-05.sources.md`.
5. new: "The adaptive form is deleted because the repository owner chose always-on as the only form that ships, and because of bench 7: it ran one run of each form at 20,000 IOPS, and in that pair the adaptive form did not do better (in the table below three rows are not told apart, and on the two rows outside the always-on run's spread the adaptive run is behind)."
   Source: F R3 "Why the adaptive form is deleted" (owner's choice; one run of each form at 20,000 IOPS; did not do better). Runs and IOPS: body l.23 (r20261115-1131 always-on, r20261115-1653 adaptive, 20,000 IOPS). "three rows not told apart": body table l.28-30 (chain tx/s, own-header certification, committed rounds per second, verdict "not told apart"). "two rows outside ... adaptive run is behind": body table l.31 (seen p95 s: 17.33 always-on vs 24.18 adaptive, a longer p95 is worse) and l.32 (first light blast chain tx/s: 698.3 vs 680.0, lower is worse), both verdict "outside". No figure added to the text.
6. new: "The adaptive form also carries a window, a streak and two constants that no run tuned."
   Source: F R3 "Why" (verbatim reason), prompt.

## Change (new line after the commit list, now l.67)
7. new: "{{pr-09}} removes what these commits add for the adaptive form (the window, its reset streak, its cap and the warnings about `quorum_exec_block_starved_rounds`) and keeps the rule with its floor of 8."
   Source: F R3 "Gone" (window-and-streak state, the two constants, the start-up warning(s)); F R3 "Removed log output" (the two start-up warnings about `quorum_exec_block_starved_rounds`); F R3 "Every header's execution block is chosen by `choose_exec_block` under the quorum rule with the floor of 8 (`QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`)".

## Section "With the switch off" -> "The switches, and where they go" (old l.62-70, now l.69-81)
8. Heading old "## With the switch off" -> new "## The switches, and where they go". Source: B point 1.
9. l.64 old "Every header names ..." -> new "In this PR's diff, with the switch off, every header names ..."; l.65 old "New with it off: ..." -> new "New with it off, in this diff: ...". Code locations unchanged (`proposer.rs:1908`, `:305-318`, `:478-481`). Source: B point 1.
10. new: "{{pr-09}}, the last PR of the stack, removes both switches and the adaptive form, so once the stack is collapsed into #1862 there is no switch and no off state." Source: as 3 and 4.
11. new: "A reviewer should read the rule as unconditional: after {{pr-09}} every header of every node names the block `choose_exec_block` picks under the quorum rule with the floor of 8." Source: F R3 (`choose_exec_block`, floor of 8); `choose_exec_block` also named in body l.45.
12. l.68 old "A mixed fleet is one chain: ..." -> new "In this PR's diff a mixed fleet is one chain: ...". Source: B point 1.
13. l.70 old "`test_mixed_switch_fleet_is_one_chain` runs a fleet with the switches mixed." -> new "...; {{pr-09}} deletes it with the switches." Source: F R3 e2e "deleted `test_mixed_switch_fleet_is_one_chain`".
14. new: "After {{pr-09}} the mixed fleet that matters is main beside the stack during a rolling upgrade: `make test-upgrade` with main as the previous binary passed on the stack's top with the six switches on (see the gates below), and the limits say what that test does not cover."
   Source: body gates block l.93 ("`make test-upgrade` with main at 33b727fce as the previous binary ...: passed with every switch off and with the six on", on the stack top 500e21afa per l.87); F "What the PR is" (mixed fleet covered by `make test-upgrade` with main as the previous binary). B point 2.

## Testing (new sentence after old l.76, now l.88)
15. new: "{{pr-09}} deletes the adaptive form's tests above (the window, streak and model unit tests, `test_held_member_two_closes_adaptive` and `test_missed_record_round_adaptive`), the control and adaptive arms of `test_fast_executor_is_certified`, `test_mixed_switch_fleet_is_one_chain` and, with `vote_queue_fix`, the seven voter tests that turn that switch off; the always-on tests and the other seven voter tests stay, some under new names."
   Source: F R3 "Deleted unit tests" (incl. `..._window_counts_headers_across_a_round_jump`, `..._reset_needs_a_streak_of_certified_tip_headers`, `..._policy_model_holds_the_target`, all three named in body l.74); F R3 e2e (deleted mixed fleet, control and adaptive arms, `test_held_member_two_closes_adaptive`, `test_missed_record_round_adaptive`; kept `test_held_member_two_closes`, `test_missed_record_round`; `test_quorum_exec_block_switch_off_keeps_header_bytes` renamed `..._header_names_the_own_ring_block`); F R2 l.47 (the seven `quorum_exec_block_voter_*_switch_off` deleted, their on bodies live on as `old_block_in_ring_is_voted_at_once` and six more).

## Limits (old l.105, l.107; new bullets now l.118-126)
16. l.105 old "... up to eight block-producing outputs later than with the switch off (`proposer.rs:1530-1545`)." -> new "... later than when it names its own tip, as main does (`proposer.rs:1530-1545`)." Source: body l.15 (on main the proposer names its own newest executed block, `proposer.rs:379-385` at 33b727fce); code location unchanged.
17. l.107 kept; new continuation: "After {{pr-09}} always-on is the only form, on every node, and that code is gone." Source: F R3 "Gone"; B point 3.
18. new: "{{pr-09}} deletes the control arm of `test_fast_executor_is_certified`, which showed that without the rule the fast node certifies at most 0.85 of its headers and every slow voter refuses some requests as execution behind; after it only the rule's absolute share is asserted."
   Source: F R3 "What the removal loses" 1 (verbatim facts; 0.85 also body l.18, l.76).
19. new: "{{pr-09}} deletes `test_mixed_switch_fleet_is_one_chain`: one chain while two nodes ran the fixes and two did not, across epochs and a restart, every node serving the same certified record per closed epoch, no record conflict, and a certified header of a fixed node naming an older block, which needs a vote from a node without the fixes."
    "`make test-upgrade` with main as the previous binary covers old and new binaries making one chain through a rolling upgrade, but not that last point: it slows no node and reads no `exec_basis`, all four validators execute at the same speed, so an upgraded proposer names its own tip almost always, and nothing asserts that a voter running main ever voted for a header naming an older block."
    "The voter-side unit tests that stay exercise this tree's voter, not main's."
    "Whether a test of that point is added to the rolling-upgrade test: see {{pr-09}}."
   Source: F R3 "What the removal loses" 2 (all facts, incl. `upgrade.rs` slows no node, reads no `exec_basis`, four validators same speed; kept voter-side unit tests exercise this tree's voter; a phase may be added to `upgrade.rs`). Not promised: worded "see {{pr-09}}" per the prompt.
20. new: "{{pr-09}} removes the field `exec_policy` (values `off`, `always`, `tip`, `starved`) from `header proposed`; `exec_block`, `exec_tip` and `exec_basis` stay." Source: F R3 "Removed log output, verbatim".

## Related (old l.116-117, now l.135-136)
21. old "- Refs #1804: the author's side; the voter's side is `fix/1804-vote-queue` (#1864). The switch defaults off, so this does not close the issue."
    new "- Refs #1804: the author's side; the voter's side is `fix/1804-vote-queue` (#1864). The closing keyword for #1804, if any, is in #1862's body, the only PR of the stack that merges into `main`."
    Source: B point 4; prompt (stays `Refs`).
22. old "- Next: `fix/1807-digest-order-hold`, the order hold for #1807, builds on this head."
    new "- Next: `fix/1807-digest-order-hold` (#1869), the order hold for #1807, builds on this head; {{pr-09}}, which removes the stack's switches, is the PR on top of #1869."
    Source: B "What happened" (stack list: #1869 `fix/1807-digest-order-hold`; ninth PR on top of #1869).

## Not changed
- Stack-position lines (l.9-10), merge-method sentence (l.11), the `Stack-wide gates` block (l.87-97): untouched (B point 5).
- Stale-phrase check (`under way|has not finished|is running|not sent yet`): no hit before or after.
- Problem l.18 ("with every switch off the fast node must certify at most 0.85 ...") left as a description of this PR's test; item 18 says the arm goes.
