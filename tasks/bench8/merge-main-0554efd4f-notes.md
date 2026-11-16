# Trial merge: stack top 500e21afa + upstream `main` 0554efd4f (local only, never pushed)

Written 2026-11-16 (MR-1). Worktree `/home/drtnarg/coding/telcoin/tn-b7-pcc`, detached.

- Merge commit: **b23472a43fa29786a25b897c36c44009f586e752** (parents 500e21afa = #1869 top, 0554efd4f = `main` with #1859 c1b1eb9fe and #1861 0554efd4f). Subject: `trial merge of the stack's top with main at 0554efd4f (local check only, never pushed)`.
- Only file changed by the resolution: `crates/node/src/manager/epoch_votes.rs` (+65/-48 against the stack top). Everything else merged automatically and needed no edit.
- `git rerere` is on in this repo: it recorded the seven hunks' resolution at the first commit (9f326a59b, later amended). The edits outside the hunks below are not in rerere and must be redone by hand.
- Gates (env from the bench 7 node-unit rules, all through `tasks/bench6/cargo-slot.sh`):
  - `cargo check --locked --all-targets -p tn-node -p tn-primary`: EXIT=0 (`target/tmp/mr1-check-4.log`, on the final commit).
  - `cargo +$(cat rust-nightly) fmt --all -- --check`: EXIT=0 (`target/tmp/mr1-fmt-2.log`).
  - `cargo nextest run --locked --no-fail-fast -p tn-node -E 'test(epoch)'`: `186 tests run: 186 passed, 98 skipped`, EXIT=0 (`target/tmp/mr1-nextest-2.log`). Before the test edit E4: 185 passed, 1 failed (`target/tmp/mr1-nextest.log`).
  - Log paths are under the worktree.
- Helper scripts used (scratch, may not survive): `/home/drtnarg/.claude/jobs/e50668f4/tmp/mr1/{resolve,fork_forget,doc_fix,test_fix}.py`, each `python3 -I <script> crates/node/src/manager/epoch_votes.rs`, in that order. Every step is described below, so they are not needed.

## The seven hunks (line numbers: conflicted file before resolution)

What the two sides did to this file: `main` (#1861) renamed the failure channel `store_failed` to `round_failed` (a round now also reports a fork, `bail!`, and the node exits non-zero) and imports `eyre::bail`. The stack (#1866) added `retained: Option<RetainedEpochVotes>` to `handle_new_vote` and its callers, imports `parking_lot::Mutex`, and documents the `epoch_record_recertify` switch on `spawn_epoch_vote_collector`.

| # | Where | Stack (HEAD) | `main` | Result |
|---|---|---|---|---|
| H1 | imports, l.10 | `use eyre::WrapErr as _;` + `use parking_lot::Mutex;` | `use eyre::{bail, WrapErr as _};` | `use eyre::{bail, WrapErr as _};` then `use parking_lot::Mutex;` |
| H2 | `handle_new_vote` params, l.551 | `store_failed: &Sender<TaskError>,` + `retained: Option<RetainedEpochVotes>,` | `round_failed: &Sender<TaskError>,` | `round_failed: &Sender<TaskError>,` + `retained: Option<RetainedEpochVotes>,` |
| H3 | doc of `spawn_epoch_vote_collector`, l.659 | old store-failure paragraph + `///` + the `recertify` switch paragraph | new paragraph (store failure **or fork**, exits non-zero) | `main`'s paragraph, `///`, then the stack's `recertify` paragraph unchanged |
| H4 | collector's call of `handle_new_vote`, l.709 | `…, &store_failed_tx,` + `retained.clone()).await;` | `…, &round_failed_tx).await;` | `…, &round_failed_tx,` + `retained.clone()).await;` |
| H5-H7 | three test calls of `handle_new_vote`, l.2299, 2372, 2398 | `&store_failed,` + `None,` | `&round_failed,` | `&round_failed,` + `None,` |

Rule used for H2 and H4-H7: take the stack's lines and rename `store_failed` to `round_failed`. On a newer top where the switch paragraph of H3 has been rewritten (switch removal), keep `main`'s paragraph first and the stack's then-current paragraph after it.

## Edits outside the hunks (same file)

- **E1, rename in auto-merged stack code.** A test the stack added (it builds `let (store_failed, _store_failed_rx) = mpsc::channel(1)` and passes `&store_failed` to `handle_new_vote`, about l.3823 and 3841 before resolution) still used the old name. Not a compiler error (local binding); renamed to `round_failed` so the file has one name. `grep -n store_failed` on the file must be empty afterwards.
  - Not renamed: `crates/node/src/manager/node/run_epoch.rs:461,476,492` (`let store_failed = store_failure(&self.consensus_db)`). That is the consensus-DB failure arm of the epoch loop, identical on 33b727fce, 0554efd4f and 500e21afa; it is not the vote collector's channel.
- **E2, fork branch of `manage_epoch_votes`.** Compiler, after the hunks: `error: value assigned to 'conflict' is never read --> crates/node/src/manager/epoch_votes.rs:403:37` (`-D unused-assignments` via `-D warnings`; log `target/tmp/mr1-check-1.log`). Cause: the auto-merge put the stack's `conflict = true;` right before `main`'s `bail!`, so the stack's post-loop `} else if conflict { retained.forget_record(epoch_rec.epoch, epoch_hash); }` can no longer run. Edit, keeping both behaviours:
  1. replace `conflict = true;` (same position, just before the `error!` "…we have forked!") with
     `if let Some(retained) = &retained { /* a record known to differ from the network's certified one is never built from kept votes, in this round or a later one */ retained.forget_record(epoch_rec.epoch, epoch_hash); }` (the comment is the stack's, moved);
  2. delete the post-loop `} else if conflict { … forget_record … }` branch (four lines), keeping `if certified { … } else { … }`;
  3. delete `let mut conflict = false;`.
  Result: final file l.403-409 (forget) before l.416 (`bail!`).
- **E3, doc of `manage_epoch_votes`.** The stack's paragraph (auto-merged) said a fork round "logs the fork and calls `node_shutdown`". Now: "logs the fork, forgets the signatures kept for its own record and ends with the fork as its error, whatever the record's epoch: a round for an older record (a re-certify round) stops the node as the previous record's round does." Not compiler-asked: the old text was false after the merge.
- **E4, the stack's test of a fork in a re-certify round.** nextest: `FAIL manager::epoch_votes::epoch_vote_collector_tests::test_recertify_round_stops_on_a_conflicting_record`, panic at the helper `conflicting_record_round`'s `.expect("no local store failure")` with `epoch 1: the network certified epoch record … where this node computed …; this node has forked`. The stack's helper expected `Ok(())` and `stopped = noticer.noticed()`. Changed to `main`'s form, as `main` did for its own `test_fork_digest_mismatch_fails_the_round`:
  - `let fork = manage_epoch_votes(…).await.expect_err("a conflicting record must end the round with the fork");`
  - `assert!(!noticer.noticed(), "the round leaves the stop to its error, which the collector returns");`
  - `let stopped = fork.to_string().contains("this node has forked");` and `ConflictingRound { kind, stopped, adopted, lines }`;
  - the `stopped` field doc and the test's doc say "ends with the fork as its error (which the collector returns to stop the node)" instead of "calls the node's shutdown".
  The four cases, `assert!(round.stopped)`, `!round.adopted` and the ERROR "we have forked!" line assertion are unchanged.

`crates/node/src/manager/node.rs`, `node/run_epoch.rs`, `crates/consensus/primary/src/network/mod.rs` and its tests: the compiler asked for nothing there.

## Where the two sides' logic meets (final file, `crates/node/src/manager/epoch_votes.rs`)

- `main`'s fork stop: in the peer-recovery branch of `manage_epoch_votes` (l.149), a validated downloaded record whose digest differs from ours makes the round `bail!` (l.416). `handle_new_vote`'s round task sends the error on `round_failed` (l.606), the critical collector returns it (l.683), the node exits non-zero.
- The stack's conflict evidence acted on the same record, `(epoch_rec.epoch, epoch_hash)`: it called `node_shutdown.notify()`, fell through to the post-loop block and dropped the record's kept signatures there. With `main`'s early return that drop is unreachable. After E2 each change acts once on the record, in this order: forget (l.405), then stop (l.416). Against the stack, the forget now comes before the stop instead of after `notify()`. A round the collector starts for the same record before it handles the error cannot start from the forked record's kept signatures.
- Re-certify and the walk: `recertify_older_record` (l.884) picks one older uncertified record of `N-16 ..= N-2` round-robin and votes for it. Its round is an ordinary `manage_epoch_votes` round of kind `Recertify`, and the fork check applies to every round whatever its epoch. The stack widens which records can reach the fork stop; `main` changes how the stop happens. They compose: a forked re-certify round now stops the node non-zero. `retained.prune` (l.737) and the `retained` argument of `handle_new_vote` are not on the fork path. Nothing acts twice.
- What `bail!` skips that the stack's post-loop did on a fork:
  - `retained.take_recertify(epoch)` and `tn_node.epoch_record_recertify_rounds_total{result="short"}` (l.509-511) for a forked re-certify round. The mark stays in memory and the process exits, so only that one counter sample is lost. The doc at l.879 ("the round it joins or starts reports its outcome in …") is not true for a forked round.
  - Left as is: counting it before the `bail!` would be a design choice for the orchestrator.
  - The kept-quorum aggregation (post-loop `else`) never ran on a conflict on either side. The missing-certificate alarm does not fire either way.
- `RetainedEpochVotes` is in memory (a `parking_lot::Mutex`, node lifetime), so the forget matters only between the `bail!` and the process exit.
- Not covered by a test: no test asserts that the fork drops the kept signatures. The stack had none either; the conflict tests run with `retained` in `conflicting_record_round` but check stop, adoption and the log line only.

## To redo on a newer top

1. `git merge --no-commit --no-ff <main>`; rerere may replay H1-H7. Check them against the table anyway.
2. `grep -n store_failed crates/node/src/manager/epoch_votes.rs`: rename every hit (E1).
3. `grep -n 'conflict' crates/node/src/manager/epoch_votes.rs`: if `conflict = true;` still sits before `bail!`, do E2. Then fix the `manage_epoch_votes` doc (E3).
4. `cargo check --locked --all-targets -p tn-node -p tn-primary` with `-D warnings`, then nextest `-p tn-node -E 'test(epoch)'`. If `test_recertify_round_stops_on_a_conflicting_record` still expects `Ok` plus `node_shutdown`, do E4.
5. If the newer top removed the `epoch_record_recertify` switch, `retained` may no longer be an `Option`. Do the E2 forget unconditionally on the retained store in that case, still before the `bail!`.
