# PT-3v — the voter's answers to an old execution block, pinned on main's reworked vote handler

Unit: `PT-3v` (node test unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-3v.md`. Budget: under 150k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt3v`, branch `b7/pt3v`, base = the integration head 5879d7ce6 (upstream main 45dce8947 + 57 commits: the vote fix, the voter's queue fix and the collector hardening are in it). Domains: `tn-domain-consensus`, `tn-domain-execution`. Topic slug: `quorum-exec-block`. `Refs #1804`.
Test code only: you change no production line. If a case cannot be expressed without a production change, stop and hand back with what is missing.

## Why

With `quorum_exec_block` on, a proposer names an execution block up to eight outputs behind its own tip (never before the epoch's opening block: the D75 clamp) instead of the tip. The fix changes what the AUTHOR names; it relies on the voter's rule being unchanged.
Bench 6 pinned the voter's side with tests (bench-6 tree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only, commit 14b55b04c, 169 lines appended to `crates/consensus/primary/src/tests/network_tests.rs`):
1. a header naming an old block the voter executed is voted for at once, also once that block has left the recent-blocks ring and only the canonical database confirms it;
2. an old number with another hash is refused with `UnknownExecutionResult`, never as `ExecutionBehind`;
both with `vote_queue_fix` off and on.
Since then upstream reworked `RequestHandler::vote` and the per-author lock (#1822, #1839, #1842, #1844, #1846), and this stack's voter queue fix (`vote_queue_fix`: the wait for execution moved BEFORE the per-author lock; a superseded request is refused with `SupersededRequest`) sits on top. The bench-6 tests do not apply as text: re-express them against the handler as it is on your base.

## Read first

- `git -C /home/drtnarg/coding/telcoin/telcoin-network-b6 show 14b55b04c` (the two cases and how bench 6 built them).
- On your base: `crates/consensus/primary/src/network/handler.rs` (the vote path: where the header's named execution block is checked, the ring lookup, the canonical-database fallback, the wait for execution, the per-author lock, the error each branch returns), `crates/consensus/primary/src/recent_blocks.rs` (the ring; `newest_before_epoch`), `crates/consensus/primary/src/error/network.rs`.
- The end of `crates/consensus/primary/src/tests/network_tests.rs`: the voter queue fix's tests (the last ≈ 1,240 lines, under its marker) show how a test on this base builds a handler, a header with a chosen execution block, sets the switch, and feeds the execution bus. Reuse its helpers; do not copy them.
- `tasks/checkpoint-bench7-PT-3a.md` (what a header carries for the named block; how a test builds a header under each form) and `tasks/checkpoint-bench7-PT-2B.md` (the voter path's stages and outcomes on this base).

## What to write

Append at the END of `crates/consensus/primary/src/tests/network_tests.rs`, after everything there, under the marker line `// ---- bench7 quorum-exec-block: the voter's answers to an old execution block ----`. Your block must be self-contained (its own closing lines; nothing shared with the block above).
Cases, each run with `vote_queue_fix` off and on (one parameterised helper, two `#[tokio::test]`s per case, or a loop inside one test: follow the file's way):
1. **Old block, executed, still in the ring**: the header names a block N−8 (the voter's tip is N): the vote is given without waiting (assert no wait: the stage / outcome the handler records, or the elapsed time against the handler's execution wait, whichever the file's existing tests use).
2. **Old block, executed, out of the ring**: the ring no longer holds the block; only the canonical database confirms number and hash: the vote is given. Establish from the code what the ring's capacity is and how a test evicts an entry; if the handler on this base has no database fallback, say so in the hand-back with `path:line` and pin what it does instead (that would change what the vote fix can assume: it is the most important thing you can report).
3. **Old number, other hash**: refused with `UnknownExecutionResult` (or this base's name for it), never `ExecutionBehind`, and not after a wait.
4. **A block of the previous epoch** (the clamp's other side): a header whose named block is the previous epoch's closing block, and one that names a block BEFORE it: pin what the voter answers today (vote, refuse, wait) for each. Do not judge it; state it. A proposer with the clamp never names a block before the opening block; this case records what a voter does with a header from a proposer that did.
5. **Newer than the voter's tip** (control, if the file does not already pin it on this base): the voter waits for execution and votes when the block arrives, or answers `ExecutionBehind` (the outcome name on this base) on timeout. Skip it if an existing test covers exactly this; name that test in the hand-back.
No paused-clock trick the file does not already use; no sleeps longer than the file's own.

## Gates and review

As the rules say: `cargo check --locked --all-targets -p tn-primary`, the fmt check, clippy for the package, `cargo nextest run --locked -p tn-primary --no-fail-fast` (whole package), each new test three times by name (`--stress-count 3`). All cargo through `tasks/bench6/cargo-slot.sh`; a wait of 30 minutes for a slot is normal on this host, never wrap cargo in a short timeout, and never end your turn while a gate runs.
One `tn-domain-reviewer` (opus) on your diff, domain consensus: does each test pin the handler's real branch (not a branch of the test's own fixture); would each test fail if the voter's rule were loosened (accepting an unknown hash) or tightened (refusing an executed old block).
Mutation check by hand, reported verbatim (revert each after): (a) make the handler answer `ExecutionBehind` for an old number with another hash; (b) remove the database fallback (or the ring lookup's equivalent on this base): name the test of yours each one fails.
One commit: `test(primary): pin the voter's answers to an old execution block`, body in plain prose, `Refs #1804`, then `Topic: quorum-exec-block` as the last line; no attribution of any kind.

## Hand back

As the rules say, plus: the voter's rule on this base in five lines with `path:line` (ring, fallback, wait, errors); for each case what the voter does with the switch off and on; case 4's answers; the two mutations and the test each fails; anything in the reworked handler that changes what the vote fix can assume about voters (for the review of the vote fix and for the bench 7 form comparison).
