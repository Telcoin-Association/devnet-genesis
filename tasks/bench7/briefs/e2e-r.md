# E2E-R — restructure the stack's e2e test files so every pull request carries its own tests

Unit: `E2E-R` (e2e unit, opus; load `tn-rust-skills` and `tn-write-e2e`). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", the e2e lane rule, plus the common sections). Checkpoint: `tasks/checkpoint-bench7-E2E-R.md`. Budget: under 220k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-p2`, branch `b7/p2`, at d7daa9aa1 (clean). Test files only: **no line outside `crates/e2e-tests/tests/it/` may differ from the stack's top when you are done.**

## The problem

The stack is one branch per topic, each head = the previous head + its topic's commits (the table below). Four e2e test files were written by four units, each on the integration branch where everything already existed. Three of them import their fleet helpers (the four-validator fleet, the load generator, the switch-line and fatal-line checks, the epoch-record readers) from `tests/it/exec_block.rs`, which belongs to head 05. So:
- `epoch_record_walk.rs` (the tests of head 04's collector hardening: #1850) cannot sit in head 04: today it is in head 05, and head 04's pull request would carry no e2e test of its own;
- the shared helpers live in a file named after the vote fix.

| head | branch | tip today | what |
|---|---|---|---|
| 04 | `fix/epoch-record-collector-hardening` | d7daa9aa1 | node code of the collector hardening (three record switches); NO e2e file today |
| xf | `fix/epoch-loop-output-drop` | a2c4dfae9 | 8 commits on 04 |
| 05 | `fix/1804-quorum-exec-block` | 54cd8e1e5 | 16 node commits (a2c4dfae9..0d5ff6f50), then 11 e2e commits: `exec_block.rs` (1), `epoch_close_forms.rs` and its changes to `exec_block.rs` (8), `epoch_record_walk.rs` and a visibility change (2) |
| 06 | `fix/1807-digest-order-hold` | 91a15e223 | 16 node commits (54cd8e1e5..74c9970c2), then 3 e2e commits: the switch in the shared lists, a visibility change, `digest_order_hold.rs` |
All in the repository of your worktree (`git log --reverse --format='%h %s' <a>..<b>`). The four files' final content is at 91a15e223 (`git show 91a15e223:crates/e2e-tests/tests/it/<file>`).

## What to build (a new series of commits on your branch; nothing is pushed, nobody else works on these files)

Target layout:
- **head 04** = d7daa9aa1 + (a) `test(e2e): fleet helpers for the stack's e2e tests`: a new module `tests/it/fleet.rs` (+ its `mod` line) holding everything in `exec_block.rs` at 91a15e223 that is not specific to the vote fix's two tests: the fleet type and its methods, the load generator, the log readers, `assert_switches` / `expected_switches`, the switch lists, the fatal-line lists and checks, `node_epoch`, `wait_for_epoch_on_all`, `assert_epoch_records`, the constants they need. The switch lists hold exactly the switches that EXIST at this head (`crates/config/src/node.rs` at d7daa9aa1: `epoch_record_recertify`, `epoch_record_collect_past_uncertified`, `epoch_record_conflict_halt`, `vote_queue_fix`, in the macro's order); the fatal list holds the lines that exist at this head (main's stored-record mismatch, the closing-block halt, the conflict halt by its stable phrase). + (b) `test(e2e): an epoch the network never certifies, walked past and re-certified`: `epoch_record_walk.rs` (final content, importing from `fleet`; rename the test `…_on_main` to say what it runs: the stack's binary with every switch off) + its `mod` line.
- **xf head** = head 04 + the 8 commits `d7daa9aa1..a2c4dfae9` cherry-picked unchanged (they touch no e2e file: they must apply cleanly) + ONE new commit `test(e2e): count the leftover drain's gap stop as a fatal line` (the line this head adds, appended to `fleet.rs`'s fatal list).
- **head 05** = xf head + the 16 node commits `a2c4dfae9..0d5ff6f50` cherry-picked unchanged + `test(e2e): fast executor certification and a mixed-switch fleet`: `exec_block.rs` reduced to the vote fix's two tests and what only they use, importing from `fleet`; the two vote-fix switches join the shared lists in the macro's order (they come FIRST in `runtime_switches!`: check) + `test(e2e): two epoch closes under each vote-fix form with members held behind`: `epoch_close_forms.rs` (final content, importing from `fleet` and from `exec_block` only what is the vote fix's) as ONE commit whose body says in three lines what the tests check.
- **head 06** = head 05 + the 16 node commits `54cd8e1e5..74c9970c2` cherry-picked unchanged + `test(e2e): the own-chain hold keeps every accepted transaction while a validator's chain breaks`: `digest_order_hold.rs` (final content, imports adjusted) with `digest_order_hold` added to the shared lists.
Name the four head commits with branches in your worktree's repository: `b7/p2-04`, `b7/p2-xf`, `b7/p2-05`, `b7/p2-06` (`git branch <name> <sha>`; do not touch any other branch).
Rules for the content:
- **No assertion changes, no timing changes, no test added or removed.** This is a move: the same tests, the same helper bodies, new homes. Where a helper's body must differ per head (a list's entries), that is the only difference. Every existing test name stays except the one rename above.
- Cherry-pick with `git -c rerere.enabled=false cherry-pick <sha>`; a node commit that does not apply cleanly means you built on the wrong commit: stop and look, do not resolve.
- Commit messages: plain prose bodies; footers: head 04's two commits `Refs #1850` then `Topic: epoch-record-collector-hardening`; the xf line commit `Refs #1860` then `Topic: epoch-loop-output-drop`; head 05's two `Refs #1804` (the second also `Refs #1850, #1851`) then `Topic: quorum-exec-block`; head 06's `Refs #1807` then `Topic: digest-order-hold`. No attribution of any kind (no Co-Authored-By line, no "generated with" line).

## Checks (each must hold; report each with its command and output)

1. `git diff --stat 91a15e223 b7/p2-06 -- . ':!crates/e2e-tests/tests/it'` is EMPTY.
2. At EACH of the four heads: `cargo check --locked --all-targets -p e2e-tests`, `cargo +$(cat rust-nightly) fmt --all -- --check`, `cargo +$(cat rust-nightly) clippy --locked --all-targets -p e2e-tests -- -D warnings` (all cargo through `tasks/bench6/cargo-slot.sh` with the rules' environment). A head whose tests reference a switch, a line or a helper that does not exist yet at that head fails this or fails at run time: check the lists against `runtime_switches!` at each head by reading it.
3. The tests are the same: for each of the four files, `diff` between the set of `fn test_…` / `#[test]` names at 91a15e223 and at `b7/p2-06` shows only the one rename; and a reviewer's read (below) of the moved bodies.
4. ONE lane run at `b7/p2-06` of all thirteen tests (`-E 'test(/^(exec_block|epoch_close_forms|epoch_record_walk|digest_order_hold)::/)'`, each once, through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh`), and ONE lane run at `b7/p2-04` of `epoch_record_walk`'s three tests (the head whose pull request they now belong to: they must pass there, with the four-key list). **The lane is busy for several hours today with the orchestrator's gate chain (`pgrep -af orch-top-e2e`): your lane jobs queue behind it; every other cargo call also waits while a lane job runs (a wait of an hour or more is normal). Do all the file work and queue the checks; never wrap them in a timeout; never end your turn while a job of yours runs or waits; never kill a process you did not start.**
5. One `tn-domain-reviewer` (opus) on `git diff 91a15e223 b7/p2-06 -- crates/e2e-tests/tests/it` : is any test's behaviour changed (an assertion, a wait, a list a test iterates); can a test at head 04 pass with a switch silently missing from the list; is anything left in `exec_block.rs` that the other files need.

## Hand back

As the rules say, plus: the four head ids; per head the commits you added (id, subject); what `fleet.rs` holds and what stayed in `exec_block.rs`; the lists' contents at each head; checks 1 to 5 with outputs; the lane runs' results and wall-clock; anything that could not be moved without a behaviour change (and what you did instead).
