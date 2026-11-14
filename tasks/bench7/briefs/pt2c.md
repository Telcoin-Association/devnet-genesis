# PT-2C — review follow-ups for the voter's queue fix (`vote_queue_fix`)

Unit: `PT-2C` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-2C.md`. Budget: under 150k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt2c`, branch `b7/pt2c`, base = the integration head 5879d7ce6 (the topic's commits are in it: `git log --oneline --grep='Topic: vote-queue' 45dce8947..HEAD`; check the footer's exact slug in the log and use the same). Domains: `tn-domain-consensus`, `tn-domain-networking`. `Refs #1804`.

## Background

The fix (brief `tasks/bench7/briefs/pt2b.md`; the unit's notes `tasks/checkpoint-bench7-PT-2B.md`): with `vote_queue_fix` on, a voter waits for execution BEFORE it takes the per-author lock, and refuses a request the same author has superseded with a newer header (`SupersededRequest`). Switch off: main's behaviour exactly.
Its review (`tasks/bench7/review/02-vote-queue-report.md`: read the findings and the answer to the topic's question 4 in full) approved it with follow-ups. Recorded limits from the unit itself: L1 (the pre-lock wait runs before the header's cheap checks, so a Byzantine committee member can make a voter hold up to 800 concurrent one-second waits: 8 connections x 100 streams) and L2 (worst case per request = 1 s + lock wait + `vote_timeout`).

## What to change

1. **L1: cheap checks before the wait (switch-on path only).** Move the header's stateless validation (`header.validate` and the round-0 check, as the report names them: find them in `RequestHandler::vote` on your base) ahead of the pre-lock wait, so a request that would be refused anyway never waits. Constraints: with the switch OFF the order of checks, the errors and the timing line are byte-for-byte main's (the existing switch-off tests and the golden timing tests must pass unchanged); with the switch ON no request gets a vote it would not get today, and no honest request gets a different ERROR than today unless two refusals applied at once: list every such pair (which error wins before and after). If the checks need the committee or state that is only read under the lock, move only what is stateless and say what stays.
2. **L2: validate the timing combination.** Where the node validates its epoch timing parameters (the unit's notes name `validate_epoch_timing`), require `vote_timeout + 1 s` (the pre-lock wait's bound: take the constant from the code, do not write the number twice) to stay under the request deadline it must fit in (the notes say 10 s: find the real bound and name it) when `vote_queue_fix` is on; refuse to start with a clear error otherwise, in the file's existing style. The 5 s default passes. A unit test for the refusal and for the default.
3. **Comments** (the report's Info 1 and the unit's own note): `crates/consensus/primary/src/network/mod.rs` ≈ :3781 and `crates/network-libp2p/…/serve_permits.rs` ≈ :28-30 (find the file: `grep -rn "vote permit\|vote_permit" crates/ --include=*.rs | head`) describe what a vote permit is held through; with the switch on it is also held through the pre-lock wait. Say what is true for both settings. The corrected sentence for `network/mod.rs` is in `tasks/checkpoint-bench7-PT-2B.md`'s hand-back notes: use it.
4. **Info 2**: `crates/consensus/primary/src/metrics.rs` ≈ :406-410: `record_outcome` indexes with `.get()` and would drop an out-of-range outcome silently; index the way `record_stage` and `record_timeout` do.
5. **Info 3**: the doc comment at `handler.rs` ≈ :1366-1367 that breaks mid-sentence.
NOT yours: the harness's reading of the timing line (a harness unit does it).

## Files you own

`crates/consensus/primary/src/network/handler.rs` (the vote path only), `crates/consensus/primary/src/network/mod.rs` (that comment only), the `serve_permits.rs` comment, `crates/consensus/primary/src/metrics.rs` (`record_outcome` only: another unit is adding proposer metrics to this file on another branch: touch nothing else), the file with `validate_epoch_timing` (that function and its tests only), and tests in `crates/consensus/primary/src/tests/network_tests.rs`: **another unit is appending a block at the END of that file right now**, so put your new tests IMMEDIATELY AFTER the voter queue fix's own marker line (the start of its section, found with `grep -n "^// ---- bench7" crates/consensus/primary/src/tests/network_tests.rs`), not at the end of the file, as one self-contained block under `// ---- bench7 vote-queue: review follow-ups ----`.

## Gates and review

As the rules say: check, the fmt check, clippy, whole-package nextest for the primary package and for each other package you touched (mind the config-package quirk in the rules), each new or timing-sensitive test three times by name, and the voter queue fix's timing set (the unit's notes name it: 16 tests) three times. All cargo through `tasks/bench6/cargo-slot.sh`; never wrap cargo in a short timeout; never end your turn while a gate runs.
One `tn-domain-reviewer` (opus) on your diff, domain consensus: with the switch on, can the reordering refuse an honest request that was voted before, or vote one that was refused; is the switch-off path untouched; does the new start-up refusal fire for any configuration the repository ships (testnet and mainnet parameter files, the e2e tests' short timings: `grep -rn "vote_timeout" crates/ etc/ chain-configs/ 2>/dev/null | head -20`).
Commits: one per item (items 3 to 5 may share one `docs`/`refactor` commit), conventional subjects, bodies in plain prose, `Refs #1804`, then the topic footer as the last line; no attribution of any kind.

## Hand back

As the rules say, plus: item 1's list of error pairs (before / after); the bound item 2 enforces with `path:line` and what the shipped configurations give; the two corrected comments verbatim; gates with exit codes; the reviewer's answers.
