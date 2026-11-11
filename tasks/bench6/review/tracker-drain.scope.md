# Review scope — tracker-drain

Upstream issue: #1806. Switch: `epoch_close_task_drain` (bool), `epoch_record_state_check` (bool); both default false.
Where: the checked-out branch `bench/bench6-2026-11`, head d91d65d3e. Size: 9 commits, +1322 lines (tests included). This group gets the code review only: skip the security evaluation unless the review turns up something that calls for it.

## Commits (the diff under review, in branch order)
- `901505021` feat(config): add the epoch_close_task_drain and epoch_record_state_check switches
- `43158b0d0` docs(config): state the tracker-drain switches' scope precisely
- `16695b20a` feat(primary): gauge how far behind a node enters an epoch
- `2783dfa79` feat(types): track and reap tasks while a future runs
- `bc20ddf27` fix(node): keep the epoch task tracker draining during the epoch close
- `b77ccbb29` feat(node): epoch close gauges and a skipped record vote counter
- `42b2a6f39` fix(node): halt when a stored epoch record names another final state
- `2c9b43209` docs(config): describe the stored-record check as built
- `4e9c19782` test(e2e): a loaded epoch close with a slow member

## Files touched
- `crates/config/src/node.rs`
- `crates/consensus/primary/src/metrics.rs`
- `crates/consensus/primary/src/network/handler.rs`
- `crates/consensus/primary/src/tests/network_tests.rs`
- `crates/e2e-tests/tests/it/epoch_drain.rs`
- `crates/node/src/manager/node/close_epoch.rs`
- `crates/node/src/manager/node/run_epoch.rs`
- `crates/node/src/metrics.rs`
- `crates/types/src/task_manager.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the two switch table rows and the `tracker-drain` rows.
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From I-6" / "From I-6b" and "From U5" (D42: the halt does not survive a restart; D43: the 200-ms grace does not read the channel; D44 done).
- The issue body `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/bench5-loaded-epoch-boundary-drain.md`; unit checkpoint `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u5.md`.

## Questions specific to this topic (2g)
1. `track_while(fut)` drains the task-tracking channel while the close runs and must never cancel or drop the close future: verify for every exit (a critical task ending, failing, panicking; shutdown).
2. The state check HALTS a validator. Can a correct node be made to halt by anything other than a real divergence (a record stored for a different epoch, the empty-ring case, a peer's record arriving before this node's closing block is executed)?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/tracker-drain-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-tracker-drain.md`
