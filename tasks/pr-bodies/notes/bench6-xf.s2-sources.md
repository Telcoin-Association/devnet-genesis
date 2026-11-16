# Sources: PR text xf (#1867, `fix/epoch-loop-output-drop`), second pass (not posted)

Text: `tasks/pr-bodies/bench6-xf-epoch-loop-output-drop.md`, 1,585 words by `wc -w`.
Lint: `bash tasks/bench7/orch-gh-post.sh lint` on a copy with `{{pr-09}}` replaced by a number: LINT-OK; on the file itself the only hit is the unresolved `{{pr-09}}` token.
Untouched: the stack-position lines, the merge-method line, the block from `Stack-wide gates` to `## Limits` (L68-78; its L73-74 are two of the three lines that mention switches).

## The switch mentions, checked against the stack as it merges

- L5 "No switch: it fixes a loss on main." Kept as it is. This PR adds no switch, and the removal PR changes none of its files: `git diff --stat 500e21afa..refactor/remove-bench-switches -- crates/node/src/manager/node/run_epoch.rs crates/node/src/manager/node/close_epoch.rs crates/engine/src/metrics.rs` is empty (repo `/home/drtnarg/coding/telcoin/tn-b8-uc`), and neither node file contains the word `switch` at 500e21afa. pr9-facts names nothing of this PR's change.
- L73, L74: inside the script-owned gates block; left alone.

## Changed sentences (old -> new, sources)

1. L91: "- Fixes #1860: both parts of its proposed fix are here, and its reproducing test passes." -> "- Refs #1860: both parts of its proposed fix are here, and its reproducing test passes (closed from #1862's body, the only PR of the stack that merges into main)." Source: brief point 4.
2. L94: "- Next: `fix/1804-quorum-exec-block` and `fix/1807-digest-order-hold` build on this head." -> "- Next: `fix/1804-quorum-exec-block` (#1868) and `fix/1807-digest-order-hold` (#1869) build on this head, and {{pr-09}}, which removes the stack's switches, comes last." Source: the brief's stack list (#1868 `fix/1804-quorum-exec-block`, #1869 `fix/1807-digest-order-hold`); the ninth PR sits on #1869 (brief, "What happened"). Not asked for this file by the prompt; made so the stack's "Next" lines agree with #1866's.

Changed sentences: 2. Heading changes: none (the body has no "switch off" section). `{{pr-09}}` placed: 1 (L94).

## Left for the orchestrator

- L66 "Not run: no e2e test drives the race through the real loop, and no fleet has run this head yet." The stale-phrase check did not list it; bench 7 ran the stack's earlier cut on 45dce8947 (L65 says that cut has "the same seven node commits"). Not changed. A form that states no result: "…, and no fleet has run this head; bench 7 ran the stack's earlier cut on main at 45dce8947 (r20261115-1131, r20261115-1653), and #1868 and #1869 report its results."
