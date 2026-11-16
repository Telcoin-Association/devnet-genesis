# MR-1 — resolve the trial merge of the stack's top with today's `main` (local only)

Read `tasks/bench8-agent-rules.md` first (budget: 35 tool calls, about 120 printed lines per call; checkpoint `tasks/checkpoint-bench8-mr1.md`).
Skills: `tn-rust-skills`, `tn-domain-epoch`.

## State you start in

- Worktree `/home/drtnarg/coding/telcoin/tn-b7-pcc`, detached at 500e21afa (the top of the stack #1862-#1869), in the middle of `git merge --no-commit --no-ff 0554efd4f` (upstream `main`: #1859 c1b1eb9fe and #1861 0554efd4f on top of the stack's base 33b727fce).
- One file is unmerged: `crates/node/src/manager/epoch_votes.rs`, seven hunks. Everything else merged automatically.
- What each side did to that file, as far as the hunks show (verify with `git diff 33b727fce 0554efd4f -- <file>` and `git diff 33b727fce 500e21afa -- <file>`, in ranges):
  - `main` (#1861) renamed the failure channel `store_failed` → `round_failed` (a round now also reports a record that forked from the certified one, and the node exits non-zero), and imports `eyre::bail`.
  - the stack (#1866, the collector hardening) added the parameter `retained: Option<RetainedEpochVotes>` to `handle_new_vote` and its callers, imports `parking_lot::Mutex`, and documents the `epoch_record_recertify` switch on `spawn_epoch_vote_collector`.

## What to do

1. Resolve the seven hunks so that BOTH changes hold: `main`'s name `round_failed` and its fork-stop behaviour everywhere, the stack's `retained` argument and the re-certify logic everywhere. Both imports. The doc comment says both things.
2. The hunks are not the whole job. Code the stack added in regions that merged automatically may still say `store_failed`, and code `main` added may call a function whose signature the stack changed (in this file, in `crates/node/src/manager/node.rs`, `node/run_epoch.rs`, `crates/consensus/primary/src/network/mod.rs` and its tests). Find these with the compiler: `cargo check --locked --all-targets -p tn-node -p tn-primary` through the slot wrapper, warnings denied.
3. Read the two sides' logic where they meet, not only the names: does `main`'s fork stop and the stack's walk / re-certify / conflict evidence act on the same record twice, or in an order that changes what either does? Say what you found, with file:line. Do NOT redesign anything: if the two cannot both hold without a design choice, stop, leave the file as far as you got, and hand back the choice.
4. When it compiles: `git add crates/node/src/manager/epoch_votes.rs` (and any other file you had to touch, by path), then `git commit --no-edit -m "trial merge of the stack's top with main at 0554efd4f (local check only, never pushed)"`. This is a local merge commit on a detached HEAD. Never push it.
5. Run `cargo nextest run --locked --no-fail-fast -p tn-node -E 'test(epoch)'` through the slot wrapper (not e2e) and report the summary line. The orchestrator runs the wider check afterwards.
6. Write the resolution as notes to `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench8/merge-main-0554efd4f-notes.md`: per hunk, what each side had and what the result is; every extra edit outside the hunks with the compiler error that asked for it; the logic reading of point 3. The same resolution will be repeated later on a newer top, so write it so that someone else can redo it.

## Not yours

Any file outside the merge; any push; any design change; any e2e run.

## Hand back

The merge commit's sha, files touched beyond the conflicted one, the check's `EXIT=`, the nextest summary, the notes path, and the answer to point 3 in three sentences.
