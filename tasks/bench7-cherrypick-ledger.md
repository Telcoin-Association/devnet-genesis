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
| 02 | `fix/1804-vote-queue` | `vote_queue_fix` (footer slug `voter-lock`) | af19b5354 (phase A's test), **b543f3a0d from the unit branch** (integration's d8fa97940 conflicts in `node.rs`), 932211375, 0db541464, af7159c58, 5e2197ce7, then the follow-ups f6b7b6666, d64f8b02a, 7c09db756 | **done: 6dae7520f** (M+28; fmt 0; topic files identical to integration's; check EXIT=0; 1,303 tests of primary, config, network-libp2p passed, TEST EXIT=0; branch moved) |
| 03 | `fix/epoch-record-closing-block-check` | closing-block check, no switch | 0f7917f29, 14372820d (from integration, clean), **0ec490341 from the unit branch** (integration's d5944d1be conflicts in `close_epoch.rs`: the orphan counters' tests surround it there); NOT b10180cfc | **done: 8f7e4357a** (M+31; fmt 0; `close_epoch.rs` and `run_epoch.rs` identical to the unit branch's; check EXIT=0; 232 node tests passed, TEST EXIT=0; branch moved) |
| 04 | `fix/epoch-record-collector-hardening` | observability, walk, conflict halt, re-certify, hook, follow-ups, e2e | E2: 5145c7d83, 8fc1ffebb, 90a47028f; E4: 2fa2b55a8 (node.rs keep-both, record switch BEFORE `vote_queue_fix` as on integration), 645a50111, e4f1157ce; E3: 425d6a89d (node.rs keep-both, same order), a9be68ff1; hook: **9117dd345, 47edb0eda from the unit branch** (integration's carry the other hook's join); E3-FU x10 (f18f2e1c8 … f3a789520) and E4-FU x6 (a98afe33a … b3446667f) from integration, clean; then DS-1's sentences of this topic, ECF, E5b | **node part assembled: e5121e7e1** (M+57; fmt 0; every topic file identical to integration's; `test_hooks.rs` differs by the other hook's 295/2 and `node.rs` by the later switches' 54/0, as expected; gate running); waits for DS-1, ECF, E5b |
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
- 04 (node part): e5121e7e1, M+57. fmt EXIT=0. Gate: `tn-b7-stack/target/tmp/head04node-e5121e7e1.log`.

## Re-cut of 2026-11-14 22:3xZ: the doc sweep's commits go into their own topics

The doc sweep (DS-1, on a11f14b1b) produced one docs commit per topic. Nothing is pushed, so the stack was re-cut on a NEW branch `b7/stack2` (the first cut stays on `b7/stack` for reference):
- 02 = 6dae7520f + 1290500de (voter-lock docs: the 9 s `vote_timeout` ceiling) = **6ad315794** (M+29).
- 03 = 02 + the same three commits as before (`git cherry-pick 6dae7520f..8f7e4357a`, clean) = **6d8fe775b** (M+32).
- 04 node part = 03 + the same 26 commits (`8f7e4357a..e5121e7e1`, clean: the resolutions made in the first cut are in those commits) + edbb971c0 (collector docs) = **b30607017** (M+59).
- a4358cc4e (quorum-exec-block docs) waits for head 05.
Checks: fmt EXIT=0 on b30607017; `git diff --shortstat` between each first-cut head and its re-cut twin = 2 files, +12/-4 (02 and 03) and +25/-13 (04 node part): `crates/config/src/node.rs` doc comments and the CLI README only. The first cut's gates (02: 1,303 tests; 03: 232; 04 node part: 1,340) ran on trees that differ from the re-cut ones by doc comments and README text only; the top-head gates run everything again.
Local branches `fix/1804-vote-queue` → 6ad315794 and `fix/epoch-record-closing-block-check` → 6d8fe775b.

## Third cut, 2026-11-14 ~23:00Z: one docs commit on head 01 (branch `b7/stack3`)

The e2e scaffold's review had asked for one doc sentence that was never written; the unit PT-1d wrote it (326230222 on the integration branch). Nothing is pushed, so:
- 01 = 9ef55c989 + that commit = **bf9853709** (M+20; its first seven commits keep their ids).
- 02 = 01 + `9ef55c989..6ad315794` (10, clean) = **6e771ac39** (M+30).
- 03 = 02 + `6ad315794..6d8fe775b` (3, clean) = **1e38f1882** (M+33).
- 04 node part = 03 + `6d8fe775b..b30607017` (27, clean) = **d7daa9aa1** (M+60).
Checks: fmt EXIT=0 on d7daa9aa1; `git diff --shortstat b30607017 d7daa9aa1` = 1 file, +10 (doc comments in `crates/e2e-tests/src/lib.rs`). Local branches moved: `test/bench6-e2e-scaffold` → bf9853709, `fix/1804-vote-queue` → 6e771ac39, `fix/epoch-record-closing-block-check` → 1e38f1882.
The PR texts 01, 02 and 03 were remapped to these ids (map: scratchpad/orch/sha-remap-3.tsv). Heads 00 to 03 are final unless a late review note lands.

## Fourth cut, 2026-11-15 ~00:3xZ: the whole stack's node code, in topic order (branch `b7/stack7`)

Order (phase 1: test files sit where they compile): 00 → 01 → 02 → 03 → 04 → epoch-loop → 05 → 06.

| head | tip | M+ | how |
|---|---|---|---|
| 00 `feat/bench6-switches-obs` | 8a42fec57 | 12 | unchanged |
| 01 `test/bench6-e2e-scaffold` | bf9853709 | 20 | unchanged (third cut) |
| 02 `fix/1804-vote-queue` | 6e771ac39 | 30 | unchanged |
| 03 `fix/epoch-record-closing-block-check` | 1e38f1882 | 33 | unchanged |
| 04 `fix/epoch-record-collector-hardening` | d7daa9aa1 | 60 | node part only (its e2e file comes in phase 2) |
| `fix/epoch-loop-output-drop` | **a2c4dfae9** | 68 | the fix's three commits from the unit branch (one join in `close_epoch.rs`: the closing-block check's follow-up tests, then the fix's tests, each block whole), **one new commit 95705aab3** (`test(node): capture log lines in the epoch-close tests`), then the four follow-ups |
| 05 `fix/1804-quorum-exec-block` | **a4adf3a15** | 93 | the switch fields (clean, in the integration order), the vote fix and its follow-ups (unit-branch commits where the integration ones carry later context), the voter-side tests, the docs commit, `exec_block.rs`, the eight `epoch_close_forms.rs` commits; all clean. The uncertified-epoch e2e file is added here when its unit lands |
| 06 `fix/1807-digest-order-hold` (node part) | **5142a9434** | 109 | the own-certificate hook (four regions of `test_hooks.rs` joined, the hook's blocks before the withhold hook's: the integration layout), the drop counter, the orphan counters (two regions of `close_epoch.rs` joined around the helper), the rule, the model, the observability, the wiring, the docs. Its e2e file is added when its unit lands |

**The check that ties the two branches:** `git rev-parse 5142a9434^{tree}` = `git rev-parse fa41707a3^{tree}` (the integration tip) = 99c25e43e3bc…: the stack's top and the integration branch are the SAME TREE, byte for byte. Everything verified on the integration tree holds for the stack's top.

Two things this cut found:
1. **A head that did not compile on its own.** The epoch-loop follow-up's test reads a log line with a helper (`LineCapture`) that the orphan counters' commit (head 06) defines; on the integration branch the orphan counters came first. First gate of the epoch-loop head (835dfe4e7): `CHECK EXIT=101` (`use of undeclared type LineCapture`). Fix: the helper (50 lines, verbatim) gets its own commit in the epoch-loop head, placed where the integration layout has it; the orphan counters' first commit is then picked without its copy (its diff is 397/34 on the stack, 447/34 at its source: the 50 helper lines). No other commit's content changed.
2. **A recorded resolution replayed.** `git rerere` is on in this repository: a retry of a pick I had resolved in the wrong block order replayed that resolution without showing a conflict. From there on every pick runs with `-c rerere.enabled=false`.

And one mistake of mine: in one step the join script stopped on an unexpected second conflict region and my command chain (`;`) went on to commit the unresolved file. Nothing was pushed; the bad tip is on the dead local branch `b7/stack6`; the work continued from the last good commit on `b7/stack7`. Rule: the join, the format check and the commit are chained with `&&`, and the commit step first checks that no conflict marker is left.

Dead local branches from the cuts (not deleted: deleting anything old needs the user's word): `b7/stack`, `b7/stack2`, `b7/stack3`, `b7/stack4`, `b7/stack5`, `b7/stack6`.

Per-head gates of this cut: epoch-loop head a2c4dfae9 (check, node tests, clippy) and head 05 a4adf3a15 (check incl. the e2e crate, primary/config/node tests) run in `tn-b7-gate`; results in the orchestrator log.

## Fifth cut, 2026-11-15 ~00:25Z: the uncertified-epoch e2e file joins head 05 (branch `b7/stack8`)

- 05 = a4adf3a15 + c441d56f0 (visibility in `exec_block.rs`) + e4aa204d3 (`epoch_record_walk.rs`; `tests/it/main.rs` keep-both: `epoch_close_forms`, then `epoch_record_walk`) = **54cd8e1e5** (M+95).
- 06 node part = 05 + `a4adf3a15..5142a9434` (16, clean, picks with rerere off) = **74c9970c2** (M+111).
- Tree check: `74c9970c2^{tree}` = the integration tip `a0d04ab79^{tree}` = 570a1b6ef7e7…: identical.
- Heads 00 to 04 and the epoch-loop head are unchanged from the fourth cut.
Gates: epoch-loop head a2c4dfae9: check EXIT=0, 276 node tests passed, TEST EXIT=0 (clippy running); head 05 54cd8e1e5 queued behind it in `tn-b7-gate`.

## The stack is complete, 2026-11-15 00:35Z (branch `b7/stack8`)

Head 06 = 74c9970c2 + the hold's three e2e commits (7d59027f3 the switch in the shared lists, 0d3d259d0 visibility, 6aafe58af `digest_order_hold.rs`; all clean) = **91a15e223** (M+114).

| head | branch | tip | M+ |
|---|---|---|---|
| 00 | `feat/bench6-switches-obs` | 8a42fec57 | 12 |
| 01 | `test/bench6-e2e-scaffold` | bf9853709 | 20 |
| 02 | `fix/1804-vote-queue` | 6e771ac39 | 30 |
| 03 | `fix/epoch-record-closing-block-check` | 1e38f1882 | 33 |
| 04 | `fix/epoch-record-collector-hardening` | d7daa9aa1 | 60 |
| — | `fix/epoch-loop-output-drop` | a2c4dfae9 | 68 |
| 05 | `fix/1804-quorum-exec-block` | 54cd8e1e5 | 95 |
| 06 | `fix/1807-digest-order-hold` = the image source | **91a15e223** | 114 |

Tree check: `91a15e223^{tree}` = the integration tip `6646be1c0^{tree}` = 8a23d42636de…: identical. No commit carries attribution (`git log --format=%B 45dce8947..91a15e223 | grep -ci 'co-authored\|claude\|anthropic'` = 0).
Phase 2 (before PR 04 is opened; not needed for the image): the fleet helpers out of `exec_block.rs` into a test module introduced in head 04, `epoch_record_walk.rs` into head 04; node code outside `crates/e2e-tests` byte-identical to 91a15e223.

## The PR heads, final (2026-11-15 06:1xZ; branch `b7/p4` in `tn-b7-p2`)

The image was cut from the fifth cut's top, **91a15e223** (`bench/bench7-2026-11`, pushed; every gate ran on it). The pull requests' heads are a later series with the SAME node code:
1. **Test files restructured** (unit E2E-R, branches `b7/p2-*`): the fleet helpers that three e2e files imported from `exec_block.rs` (head 05) moved into `tests/it/fleet.rs`, introduced in head 04, so head 04 carries its own e2e tests (`epoch_record_walk.rs`); `exec_block.rs` keeps the vote fix's two tests; the switch and fatal-line lists grow head by head. `git diff --stat 91a15e223 <top> -- . ':!crates/e2e-tests/tests/it'` is empty. Checked per head: compile, format, clippy of the e2e crate; all 13 tests once at the top (13 passed); the walk's three tests at head 04 (3 passed, with head 04's four-switch line).
2. **One squash** (`b7/p3`): the commit that added `fleet.rs` alone did not compile under `-D warnings` (dead code until its first user), so it is one commit with `epoch_record_walk.rs`.
3. **Commit messages corrected** (`b7/p4`; trees unchanged): seven bodies stated as fact things the posted issues say were never observed or counted differently (five said bench 6 left an epoch uncertified on every node: issue #1850 says no run reached that state; one gave eleven false quorum errors to one run: issue #1852 has eleven over three runs; one said "a fifth round" where the code evicts when a round is queued while five are queued), and fourteen carried labels of a private review ("review finding V4", "Review 05, finding V1"): removed. 21 of the 72 commits after head 03 were amended (message only).

| head | branch | tip | M+ |
|---|---|---|---|
| 00 | `feat/bench6-switches-obs` | 8a42fec57 | 12 |
| 01 | `test/bench6-e2e-scaffold` | bf9853709 | 20 |
| 02 | `fix/1804-vote-queue` | 6e771ac39 | 30 |
| 03 | `fix/epoch-record-closing-block-check` | 1e38f1882 | 33 |
| 04 | `fix/epoch-record-collector-hardening` | **065ee9e5a** | 61 |
| — | `fix/epoch-loop-output-drop` | **be483a955** | 70 |
| 05 | `fix/1804-quorum-exec-block` | **d155f04df** | 88 |
| 06 | `fix/1807-digest-order-hold` | **b93a8e682** | 105 |

Each of the four new heads has the same tree as its `b7/p3-*` and `b7/p2-*` twin (checked by tree id while picking). No commit carries attribution; all 105 are authored by the repository owner's identity.
NOT corrected: the same inexact bodies are in `bench/bench7-2026-11` (pushed before the PR 04 writer found them); that branch is the image's record and is not rewritten (no force-push). Heads 00 to 03 were not re-read for the same kind of claim in commit bodies (their PR texts were figure-checked; the bodies were not).
Still owed before the heads are pushed: the per-commit compile check on `45dce8947..b93a8e682`.
