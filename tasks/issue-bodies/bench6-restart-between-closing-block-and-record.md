# A node stopped after executing epoch 0's closing block and before writing record 0 cannot restart from that datadir

## What happens

A node that stops inside epoch 0's close, after the closing block is executed and before record 0 is written, exits on every later start with:

```
Error: We have epoch 0 in our database if we are past epoch 0, on 1
```

The same stop at any later epoch's close is recovered: the restarted node rebuilds the missing record from its closing block and goes on.
Epoch 0 is the one epoch that path cannot reach, because a check earlier in startup stops the node first.

The window is short: main's boundary-window test says it "lasts about 200 ms per boundary" (`crates/e2e-tests/tests/it/restarts.rs:865-868`).
But every node of a new chain passes through it once.
A SIGTERM inside it leaves a datadir that cannot restart; by the code a crash or a power loss does too, once the executed closing block has reached disk.

## Evidence

We hit it while writing an end-to-end test for bench 6 (`epoch_close_forms.rs`, four validators, 120 s epochs, not upstream yet), on bench 6's node build (`bench/bench6-2026-11` at `2df831e3c`).
The test stops two of the four validators with the node's test hook `TN_TEST_EXIT_BEFORE_EPOCH_RECORD=<epoch>`, which is on main too (`crates/types/src/test_hooks.rs:185`).
The hook fires after `close_epoch` has executed the closing block and before `write_epoch_record`, and stops the node through the same graceful path a SIGTERM takes (`crates/node/src/manager/node/run_epoch.rs:510-519`).
We reproduced only this graceful stop, then restarted the two validators without the hook.
We have not run it on main; the check and its place before the record sync are the same there as in the build we ran, so it is reachable on main by code, and `test_restarts_cohort_exits_in_epoch_boundary_window` with the hook set to epoch 0 would confirm it.

- Stopped at epoch 0's close: 8 restarts (two test runs, two tests per run, two stopped validators per test), and all 8 exited at startup with the error above.
  For example, one of them logged on restart `read entered-epoch base fees from the closing block's on-chain record entered=1 closing_block=38` and exited 40 ms after it started.
- Stopped at epoch 1's close: 12 restarts (three runs), and all 12 logged `previous epoch record missing on restart (killed at its boundary); re-deriving it locally`, rejoined, and the tests passed.

By the code, nothing writes a record before the check, so every later start from that datadir fails the same way.
By the code, an operator can still recover such a node, though we did not try: `telcoin-network db reset-execution --force` makes the next start rebuild execution from genesis, where the committee is epoch 0's, so the check passes and the replay of epoch 0 writes record 0 at its close; moving the chain data aside and syncing the node as a new one also works.

## Where in the code

All references are on main at 45dce8947.

1. Startup reads the committee from the canonical tip (`crates/node/src/manager/node/start_epoch.rs:239`, called from `crates/node/src/manager/node.rs:998`).
   Once epoch 0's closing block has executed, that committee is epoch 1's.
2. The dummy epoch-0 record lives in memory only (`crates/storage/src/epoch_records.rs:2188-2195`).
   After a restart, `contains_epoch(0)` is false until a real record 0 is stored (`epoch_records.rs:2479-2487`).
3. `run()` then refuses to start (`node.rs:1320-1325`): with no record 0, it seeds the dummy only if the committee is epoch 0, and otherwise fails the `ensure!`.
   This runs before `sync_epoch_records_to_tip` (`node.rs:1334`), so a certified record 0 held by peers is never fetched either.
4. The recovery that handles every later epoch, `recover_previous_epoch_record` (`crates/node/src/manager/node/close_epoch.rs:559`), runs at epoch entry (`run_epoch.rs:238`), after that check.
   It already treats a dummy-only epoch 0 as missing (`close_epoch.rs:569-571`) and rebuilds the record through `write_epoch_record`, which builds epoch 0 with no previous record (`:495-499`).

The record cannot be written before the closing block executes, since its `final_state` is that block (`close_epoch.rs:527-529`).
`crates/e2e-tests/tests/it/eject.rs:526-532` and `:835-841` gate their kills on the target holding certified record 0, calling this "a pre-existing product issue".

## What a fix could look like

Let the existing re-derive path handle epoch 0:

- In `run()`, when record 0 is missing and the committee read from the tip is epoch 1, seed the dummy from the genesis committee instead of failing.
  `new()` already loads it (`node.rs:772`).
  Today the dummy is built from the current committee (`node.rs:1326`), which here would be epoch 1's.
- Keep the refusal when the committee is epoch 2 or later and record 0 is missing: that datadir really is incomplete.
- `recover_previous_epoch_record` then rebuilds record 0 at the entry into epoch 1, as it does for every other epoch.

## How to verify

- Run `test_restarts_cohort_exits_in_epoch_boundary_window` (`restarts.rs:899`) with the hook set to epoch 0 instead of `BOUNDARY_WINDOW_EPOCH` (6).
  On main every node should exit at startup with the error above.
  With the fix each node logs the re-derive line with `previous_epoch=0`, the cohort reaches epoch 2, and every node serves the same record 0 digest.
- Remove the two kill gates in `eject.rs` and run the two tests that hold them.

## Related

- #1015 (closed): the same startup failure, reached when epoch 0 was closed by a recovery arm that did not write the record.
  Its fix made every close arm write and persist the record, which leaves the window between executing the closing block and that write.
