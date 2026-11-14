# PT-2 — the voter's queue fix (`vote_queue_fix`, issue #1804): does M still have the wait? Then port or drop

Unit: `PT-2` (node port unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-2.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt2`, branch `b7/pt2`, base **M = 45dce8947**. Domains: `tn-domain-consensus`, `tn-domain-networking`. Plan rows: Track N's stack table row 02, "Port units", and the risk "`vote_queue_fix` may be superseded upstream".

## Background

Bench 5 and bench 6 measured that a validator's vote on a peer's header waited in the vote handler behind an earlier request of the same author (the per-author lock; the `lock_ms` field of the vote line, `tn_primary_vote_stage_seconds`), so a fast author's next header overtook the vote and the author's own header went uncertified (issue #1804, with #1782).
Bench 6 fixed the wait behind the switch `vote_queue_fix` (unit U2; brief `tasks/bench6/briefs/u2.md`; commits on the bench-6 tree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only: the field 82ed5801a, the fix 2b9a69925, the review fix 12bb5bb45 — find it with `git -C … log --oneline --grep='Topic: voter-lock' 165e3fe01..2df831e3c`; tests in `crates/consensus/primary/src/tests/network_tests.rs`). All four headline runs of bench 6 ran with it on.
Since then upstream reworked `RequestHandler::vote` and the per-author lock: #1822 (ed8ae4b00), #1839 (36a7bf599), #1842 (b1baed048), #1844 (1475bb098), #1846 (b0188d69f). Those PRs fix #1836 and #1797; none of them names #1804 or #1782, which are open. The handler changed by about 510 lines and `network_tests.rs` by about 734 against the old base.

## Phase A (now): establish what M does. Do NOT port yet.

1. Read U2's brief and its two fix commits: state in five lines what the wait was (which lock, held across what, by whom, what the later request waited for) and what the fix did (what a superseded or queued request gets instead).
2. Read M's `RequestHandler::vote` and the lock (`crates/consensus/primary/src/network/handler.rs` and what it calls; `git -C /home/drtnarg/coding/telcoin/tn-b7-pt2 log --oneline 165e3fe01..45dce8947 -- crates/consensus/primary/src/network/`). Answer with `file:line`:
   - Does a vote request for author A at round r+1 still wait behind an in-flight request for A at round r (or for the same round) on M? For how long at most (what bounds the hold: a parent fetch, an execution wait, a store write)?
   - Do M's reworks shorten that hold, remove it, or leave it? Does anything on M already answer a superseded request early?
   - Are the `lock_ms` field and the `tn_primary_vote_stage_seconds` stages still measured on M (they came with the observability stack, #1827 squash)?
3. Evidence by test, not only by reading: bench 6's tests for this fix include one that shows the wait with the switch off. Port that one test (test code only, in your worktree, at the end of `network_tests.rs` under `// ---- bench7 voter-lock ----`) so it measures the wait on M's handler as it is, and run it three times through the slot wrapper. If it cannot be expressed against M's handler without the fix's own types, write the smallest test that can (two requests of one author, the first held at a controllable point, assert whether the second returns before the first is released) and say what it measures.
4. Verdict, one of:
   - **DROP**: M no longer has the wait (the test shows the second request is answered without waiting, and the code says why). Deliverable: a paragraph for issue #1804 with the evidence (`file:line`, the test's output), and the test kept as a regression test only if it is cheap and stable (one commit, `Topic: voter-lock`).
   - **PORT**: the wait is still there (or there in part). Deliverable of phase A: the list of what must be re-applied against M's handler (which parts of 2b9a69925 and 12bb5bb45 still make sense, which collide with M's rework and how), an estimate (straight port / real rewrite), and the equivocation and cached-vote invariants M's rework introduced that the fix must not break (#1839 and #1844 keep a cast vote cached; #1842 cancels vote requests).
   - **REDESIGN NEEDED**: the fix as written cannot be laid on M's handler without changing M's new invariants. Stop; the plan says a port that turns into a redesign goes back to the user.
5. Commit only test code in phase A (if the verdict keeps it), then update the checkpoint and hand back. Phase B (the port itself, with the switch field on PT-0's machinery) starts only on the orchestrator's word, in a fresh worktree on the integration head, and only if the verdict is PORT.

## Gates in phase A

`cargo check --locked --all-targets -p <the primary package>`, the one test three times by name, fmt check. No clippy or whole-package run needed until phase B.

## Hand back

Status; the verdict in the first line; the five-line statement of the old wait and fix; the M answers with `file:line`; the test's name, what it measures and its three results; for PORT the re-apply list and estimate; for DROP the paragraph for #1804; token use.
