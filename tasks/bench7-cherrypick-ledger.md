# Bench 7 — the stack's assembly ledger

How the ordered stack on `staging/benchmark-bench6-2026-11` (base M = 45dce8947) is built from the unit branches, and what the integration branch is for.
Kept by the orchestrator; a row is ticked when its head is assembled, formatted, compiled and its tests have an exit line that was read.

## Two branches, two jobs

- **Integration** (`b7/int` in `/home/drtnarg/coding/telcoin/tn-b7-int`, fast-forwarded into `bench/bench7-2026-11` in `telcoin-network-b7`): unit branches cherry-picked in the order they FINISHED. It is where units get their bases and where cross-unit conflicts were first resolved. Its history is not the stack's.
- **Stack** (`b7/stack` in `/home/drtnarg/coding/telcoin/tn-b7-stack`): the same commits in TOPIC order, one head per topic, each head = the previous head + its topic's commits. This is what is pushed as the topic heads, what the PRs show, and (its top) what the bench 7 image is built from. When it is complete, `bench/bench7-2026-11` is moved to its top and pushed.
- **The check that ties them**: at the end, `git diff <stack top> <integration head>` may show only the order of entries in keep-both regions (switch fields in `crates/config/src/node.rs`, appended test blocks, `mod` lines); anything else is an assembly error.

## Rules of assembly

1. Source commits are the integration branch's (already resolved against each other), picked in the order below; a unit branch's own commit is used only where the integration commit carries another topic's lines.
2. After EVERY conflict: resolve from whole blocks, then `cargo +$(cat rust-nightly) fmt --all -- --check` before the next pick; compare `git diff --numstat` with the source commit's own.
3. Integration-only repairs are NOT picked: b10180cfc (re-closes a test that my join of two appended blocks had left open: in topic order the blocks never meet that way); the pt2b unit's 40436d016 (same kind) was never on the integration branch.
4. Each head: fmt check, `cargo check --locked --all-targets` for the packages its topic touches, their nextest; exit lines read; then the head's branch is moved and the row ticked.
5. Commit messages are not edited (no attribution exists in any: checked per head with `git log --format=%B <prev>..<head> | grep -ci 'co-authored\|claude\|anthropic'` = 0). Footers `Topic:` are missing on some early commits (rows marked ∅): the PR text lists commits by sha, so nothing is rewritten for that.

## Heads (integration commit numbers are positions in `git log --reverse 45dce8947..5879d7ce6`)

| # | head branch | topic | commits (integration position → unit) | state |
|---|---|---|---|---|
| 00 | `feat/bench6-switches-obs` | switches, observability | 1-9, 20, 21, 22 = `b7/pt0` (12 commits) | **done: 8a42fec57** (= the unit branch; R-00 approved) |
| 01 | `test/bench6-e2e-scaffold` | e2e scaffold | 10-14, 26, 27 = `b7/pt1` (7 commits, picked from the unit branch, no conflict) | **done: 9ef55c989** (fmt 0; e2e crate equal to the integration head's; check EXIT=0; 160 tests of the scaffold and config packages passed, EXIT=0; branch moved) |
| 02 | `fix/1804-vote-queue` | `vote_queue_fix` (footer slug `voter-lock`) | af19b5354 (phase A's test), **b543f3a0d from the unit branch** (integration's d8fa97940 conflicts in `node.rs`), 932211375, 0db541464, af7159c58, 5e2197ce7, then the follow-ups f6b7b6666, d64f8b02a, 7c09db756 | **assembled: 6dae7520f** (M+28; fmt 0; topic files identical to integration's; check + tests running) |
| 03 | `fix/epoch-record-closing-block-check` | closing-block check, no switch | 0f7917f29, 14372820d (from integration, clean), **0ec490341 from the unit branch** (integration's d5944d1be conflicts in `close_epoch.rs`: the orphan counters' tests surround it there); NOT b10180cfc | **assembled: 8f7e4357a** (M+31; fmt 0; `close_epoch.rs` and `run_epoch.rs` identical to the unit branch's; gates queued behind head 02's) |
| 04 | `fix/epoch-record-collector-hardening` | observability, walk, conflict halt, re-certify, hook, e2e | 15-17 (E2), 23-25 (E4), 43-44 (E3), 54-55 (E5a) + R-04's follow-ups + ECF + E5b | waits for R-04, ECF, E5b |
| — | `fix/epoch-loop-output-drop` | main's output drop (no switch) | 45-47 + XF-1b's follow-ups (running) | after 04; its PR needs the user's word |
| 05 | `fix/1804-quorum-exec-block` | both vote forms | 34-41 (PT-3a) + PT-3v + PT-3b + R-05's follow-ups | PR after bench 7 |
| 06 | `fix/1807-digest-order-hold` | the hold | 28-29 (hook, drop counter), 30-32 (orphan counters), 56-57 (rule, model) + HD-1 + HD-2b + HD-4b | PR after bench 7 |

Order of topics that share a file (must hold in the stack as it held between the units): `close_epoch.rs` 03 → epoch-loop → 06 (orphan counters); `state-sync/src/epoch.rs` and `epoch_votes.rs` inside 04 (E2 → E3, E2 → E4 → E5a); `proposer.rs` 00 → 05 → 06; `test_hooks.rs` 04 (withhold) → 06 (own-cert delay): the reverse of the integration order, so that file's join is redone; `network_tests.rs` 02 → 05; `crates/config/src/node.rs` switch fields: 02 (1), 04 (3), 05 (2), 06 (1), in that order in the list; `tests/it/main.rs`: one `mod` line each from 04 (two), 05 (one), 06 (one).

## Per-head record

- 00: 8a42fec57, M+12. Gates: the unit's (PT-0) and R-00.
- 01: 9ef55c989, M+19. fmt EXIT=0; `cargo check --locked --all-targets -p e2e-tests -p tn-config -p tn-node` EXIT=0; nextest `-p e2e-tests --lib -p tn-config` 160 passed, EXIT=0 (`tn-b7-stack/target/tmp/head01-9ef55c989.log`).
- 02: 6dae7520f, M+28. fmt EXIT=0. Gates: `tn-b7-stack/target/tmp/head02-6dae7520f.log`.
- 03: 8f7e4357a, M+31. fmt EXIT=0. Gates: `tn-b7-stack/target/tmp/head03-8f7e4357a.log`.
- Rule added: the stack worktree is not moved while a gate runs in it unless the new commits touch none of the packages under test (head 03 was assembled while head 02's gate ran: it touches only `crates/node` and a README, and head 02's gate covers primary, config and network-libp2p).
