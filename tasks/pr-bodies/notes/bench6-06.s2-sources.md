# Second-pass sources: tasks/pr-bodies/bench6-06-digest-order-hold.md (#1869; not for posting)

Pass: bench 8, the switches go in the ninth PR (`{{pr-09}}`, literal token, replaced by the orchestrator).
Sources: B = `tasks/bench8/briefs/w-s.md`; F = `tasks/bench8/pr9-facts.md` (R4 l.63-73, R3 e2e line l.57, "What the PR is" l.7-11, "Limits the plan already names" l.92-97); the body itself (line numbers below are the body BEFORE this pass unless "now"); first-pass note `notes/bench6-06.sources.md` for code lines it already maps.
No new figure, run id or commit id was added. F's figure for the deleted control (288 of 14,102 transactions lost) was deliberately not added.

## Summary (old l.3; new l.8)
1. l.3 old: "Adds the runtime switch `digest_order_hold` (default `false`, the base's drain) for #1807."
   new: "Adds the own-chain order hold for #1807 behind the runtime switch `digest_order_hold` (default `false`; in this PR's diff the default keeps the base's drain)."
   Source: B point 1; facts unchanged from the old sentence.
2. new (now l.8): "{{pr-09}}, the last PR of the stack, removes the switch and makes the hold the node's behaviour; once the stack is collapsed into #1862 there is no switch."
   Source: B point 1; F R4 "Gone: `digest_order_hold`; `order_hold: Option<OwnChainOrder>` is the value"; #1862 as collapse target: body l.9.

## Section "With the switch off" -> "The switch, and where it goes" (old l.45-51, now l.47-57)
3. Heading old "## With the switch off" -> new "## The switch, and where it goes". Source: B point 1.
4. l.47 old "The proposer never consults the hold ..." -> new "In this PR's diff, with the switch off, the proposer never consults the hold ..."; l.48 old "New with it off: ..." -> new "New with it off, in this diff: ...". Code locations unchanged (`order_hold.rs:46-47`, `proposer.rs:409`, `:1237-1239`). Source: B point 1.
5. new: "{{pr-09}}, the last PR of the stack, removes the switch and the drain without the hold, so once the stack is collapsed into #1862 there is no switch and no off state."
   Source: F R4 "Gone: ... the branch that drained digests without the hold".
6. new: "A reviewer should read the hold as unconditional: after {{pr-09}} every proposer applies the rule above at every drain, and the limits say what that changes against main."
   Source: F R4 ("`order_hold: Option<OwnChainOrder>` is the value"; the no-hold branch is gone; `own_parent` always from the hold's plan). B point 1 (what a reviewer should check).
7. l.51 old "A mixed fleet is one chain: ..." -> new "In this PR's diff a mixed fleet is one chain: ...". Source: B point 1.
8. new: "After {{pr-09}} the same holds for main beside the stack during a rolling upgrade, and `make test-upgrade` with main as the previous binary passed on the stack's top with the six switches on (see the gates below)."
   Source: the body's own reasoning in l.51 (no other validator checks which digests a node puts in its own header; so also true of a main validator); body gates block l.99 ("passed with every switch off and with the six on", on the stack top 500e21afa per l.93); F "What the PR is" (mixed fleet covered by `make test-upgrade` with main as the previous binary). B point 2.

## Testing (new sentences after old l.60, now l.67-68)
9. new: "{{pr-09}} deletes the proposer tests that drive the drain without the hold (`test_digest_order_bookkeeping_keeps_payloads_golden` and the two `…_counts_out_of_order` tests) and the control; `test_order_hold_keeps_a_canceled_headers_lane_in_order` and `test_order_hold_replays_the_model_counterexample` stay, and so do the model's tests with the hold off, which flip the model's own flag and never read the node's configuration."
   Source: F R4 "Deleted tests" (`test_digest_order_bookkeeping_keeps_payloads_golden`; `test_canceled_requeue_behind_a_newer_digest_counts_out_of_order`, `test_committed_requeue_behind_a_committed_digest_counts_out_of_order`, both named in body l.56; their hold versions `test_order_hold_keeps_a_canceled_headers_lane_in_order`, `test_order_hold_replays_the_model_counterexample`, both in body l.56; e2e `test_without_the_hold_the_far_validator_reorders`); F R4 "Kept: the model's four tests that run the MODEL without the hold ... flip the model's own flag and never read the node's configuration".
10. new: "The two e2e tests named after a vote form are renamed after the hook stage they use."
   Source: F R3 e2e l.57 ("the order-hold tests renamed after the hook stage (`…_before_store`, `…_after_store`)"); the vote-form names `test_hold_keeps_every_transaction_adaptive` / `_always`: body l.59; hook stages before/after store: body l.21.

## Limits (new bullets after old l.116, now l.125-130)
11. new: "No test aims at the hold's two known gaps on a running node: a garbage-collection cut below the leader (counted, not prevented; the model's `gc_cut_is_the_only_overtake` covers it) and a re-send after a restart (the item above)."
   Source: F "Limits the plan already names" ("The hold's two untested gaps: a garbage-collection cut below the leader; a re-send after a restart"). "counted, not prevented": body l.43 (`order_hold.rs:78-81`). Model test: body l.55. The restart re-send: body l.116 (`order_hold.rs:105-115`). Wording "on a running node" because the body itself names a model test for the GC cut and says the model covers re-sends and restarts (body l.27), so "untested" can only mean no node-level test.
12. new: "After {{pr-09}} every proposer applies the hold: while an own header is neither committed nor given up, the next header carries no digest of the worker lanes that header holds; on main those digests drain first in, first out into the next header."
   Source: F R4 "What a proposer does differently from `main`" (verbatim); main's drain: body l.14 (`proposer.rs:974` on main at 33b727fce).
13. new: "{{pr-09}} deletes the e2e control, `test_without_the_hold_the_far_validator_reorders`; after it the defect is shown by the model's tests that run without the hold, not by a node."
   Source: F R4 "What the removal loses" and "Kept" (the model's four hold-off tests).
14. new: "With the hold on, which after {{pr-09}} is always, the re-queue reason `stale_resend` can no longer be counted: a header enters the tracked set only behind a guard that returns early for a round at or below the last committed own round, and that round only rises in the call that removes every tracked header at or below it."
    "After a restart, a re-proposed header that had already committed counts as `unknown_seq`."
    "The reason and its metric label stay, and their docs say the reason stays 0; see {{pr-09}}."
   Source: F R4 "A leftover a reviewer should know" (all three facts).

## Related (old l.122, l.124; now l.136, l.138)
15. old "- Refs #1807: the switch defaults off, so this does not close it."
    new "- Refs #1807: once {{pr-09}} lands the hold is the node's behaviour; the closing keyword for #1807, if any, is in #1862's body, the only PR of the stack that merges into `main`."
    Source: B point 4; prompt (no `Fixes` here).
16. old "- Stacked on #1868 (`fix/1804-quorum-exec-block`); the last PR of the stack."
    new "- Stacked on #1868 (`fix/1804-quorum-exec-block`). Next: {{pr-09}}, which removes the stack's switches, is the PR on top of this one and the last of the stack."
    Source: B "What happened" (ninth PR on top of #1869).

## Not changed
- Stack-position lines (l.8-9 old, "PR 8 of 8 ..."), merge-method sentence (l.10), the `Stack-wide gates` block (l.93-104 old): untouched (B point 5). Note: "PR 8 of 8" stays as written by rule, while the new text calls {{pr-09}} the last PR of the stack.
- Stale-phrase check (`under way|has not finished|is running|not sent yet`): no hit before or after.
- Problem l.17 ("the model test and the e2e control below reproduce the reordering with the switch off") left as a description of this PR's diff; item 13 says the control goes.
