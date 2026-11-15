# Sources: bench6-02-vote-queue.md on today's main (not posted)

Main = 33b727fcea4f6004d4b0cd2bd7923258e081e94f (`33b727fce`). Head `fix/1804-vote-queue` = local mark `b7/n2-02` = 17327280d54590d74581fc1abc40d03dd2961c3d, 10 commits on head 01 (`b7/n2-01` = 87be966514802e039b7f7ba87452bfc7e2e57f5d), read in `/home/drtnarg/coding/telcoin/tn-b7-p2`.
`git range-diff test/bench6-e2e-scaffold..fix/1804-vote-queue b7/n2-01..b7/n2-02`: all ten `=`.
Statements not listed here are unchanged from the earlier note `bench6-02-vote-queue.sources.md`. The code they rest on did not move: of the ten files head 02 edits, main changed only `crates/config/src/node.rs` (#1848: `Config` and bootstrap servers, not `Parameters`) and `crates/telcoin-network-cli/README.md` between 45dce8947 and 33b727fce; `git diff --stat 45dce8947 33b727fce -- crates/consensus crates/network-types` is empty; the shipped `chain-configs/*/parameters.yaml` are unchanged (mainnet `vote_timeout: 5s` at :6, testnet none); `LIBP2P_REQUEST_TIMEOUT` (10 s) is at `b7/n2-02:crates/config/src/consensus.rs:450`, a file main did not change.

## What changed and why

| text | source |
|---|---|
| "PR 3 of 6", merge order with `fix/epoch-loop-output-drop` last | `tasks/bench7/briefs/w-n.md` "What happened" |
| compare link `87be96651…17327280d` (full shas), 10 commits | `git rev-parse b7/n2-01 b7/n2-02`; `git log --oneline b7/n2-01..b7/n2-02` = 10 lines |
| ten ids in "Change", exact subjects | `git log --reverse --format='%h %s' b7/n2-01..b7/n2-02`, matched by subject; all ancestors of b7/n2-06 (idcheck.sh: 10 OK) |
| On main at 33b727fce: lock `handler.rs:1029-1033`, `vote_inner` under timeout `:1158-1162`, execution wait `:1462-1507`, pending-parent wait `:1845-1855` | `git show 33b727fce:crates/consensus/primary/src/network/handler.rs`: 1029 `if let Some(auth_lock) = self.auth_last_vote.get(...)`, 1032 `auth_lock.lock().await`; 1158-1162 `tokio::time::timeout(… vote_timeout, self.vote_inner(…))`; 1462 `timing.enter(VoteStage::ExecWait);` … 1507 `}`; 1845-1855 the pending-parent comment and `process_peer_certificate` loop (file unchanged since 45dce8947) |
| at 17327280d: `cargo check --locked --workspace --all-targets`, warnings denied, clean; nextest of tn-config, tn-types, tn-node, tn-primary, tn-network-libp2p: 1,825 passed, 9 skipped, "the tests above among them" | `tasks/bench7/gate-n1-02.log` lines 1-4; gate script (orchestrator scratch `orch/gate-n1-02.sh`) for the commands and `RUSTFLAGS="-D warnings …"`; nextest log `/home/drtnarg/coding/telcoin/tn-b7-pcc/target/tmp/n1-02-nextest.log`: one PASS line each for the seven named tests and for `vote_queue_fix_newer_request_waits_for_pending_parent_wait` (Limits); 17 PASS lines with `vote_queue_fix`; no FAIL line |
| earlier cut: check and nextest with `-p tn-primary -p tn-config -p tn-network-libp2p` passed, 1,303 passed, 4 skipped; fmt | `/home/drtnarg/coding/telcoin/tn-b7-stack/target/tmp/head02-6dae7520f.log` :1 (check command), :37 `CHECK EXIT=0`, :38 (nextest command), :1387 `1303 tests run: 1303 passed, 4 skipped`, :1388 `TEST EXIT=0`; fmt EXIT=0 `tasks/bench7-cherrypick-ledger.md:39` |
| "a form of this head's first nine commits whose tree differed from theirs only by doc comments in the e2e crate" | 6dae7520f = `docs(primary): say what a vote permit is held through with vote_queue_fix on`; `git diff --stat 6dae7520f fb7093744` = `crates/e2e-tests/src/lib.rs` +10, every added line a comment (fb7093744 = the old ninth commit on 45dce8947) |
| "no benchmark has run this head; a benchmark of the stack's earlier form on main at 45dce8947 runs it on, with the author-side switch, and has not finished" | brief item 6; `benchmark/arms/bench7-always.arm`: `param vote_queue_fix true`, `param quorum_exec_block true`; image from `bench/bench7-2026-11` = 91a15e223 on 45dce8947 (`tasks/plan.md:50`); no result stated |
| Related: `fix/epoch-loop-output-drop` added to "Next" | the six-PR merge order (brief); b7/n2-xf contains b7/n2-02 |
| Stack-wide gates line | brief item 5 |

## Dropped against the earlier text

- The old ids `fb7093744` and `48dae6a5f` in the gates sentence, and the stack-wide gate paragraph on `91a15e223` (brief item 5).
- "the next one runs it on": restated as above, since that benchmark is now running on the earlier form.

## Not verified at the new tip

- fmt and clippy at 17327280d: no log; fmt stated for the earlier cut only, clippy not stated (as before).
