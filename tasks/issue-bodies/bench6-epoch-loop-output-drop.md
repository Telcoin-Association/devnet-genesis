# A lagging validator can drop a consensus output when its epoch loop is pre-empted, then execute past the gap

## What happens

On main at 45dce8947; `run_epoch.rs` and `close_epoch.rs` are in `crates/node/src/manager/node/`.

`wait_for_epoch_boundary` takes output X off the consensus-output queue (`run_epoch.rs:749`), then `process_output` awaits `to_engine.send` (`:730`).
`to_engine` holds 64 outputs (`crates/node/src/manager/node.rs:91`) and the engine queues 8 more (`crates/engine/src/lib.rs:61`, `:326`), so the send waits on a validator about 72 outputs behind in execution.

The forward is one arm of the `tokio::select!` at `run_epoch.rs:484`; three others can win meanwhile: the epoch's tasks ending Ok (`:560`) after a demotion or a rejoin notifies the epoch's shutdown (`crates/consensus/primary/src/network/handler.rs:455`, `crates/consensus/executor/src/subscriber.rs:791`); `closed_by_record` (`:549`), a certified record of a later epoch; and `node_ended` (`:485`), the node's shutdown.
`store_failed` (`:490`) stops the node instead.
Dropping the forward drops the pending send and X; X survives only in the consensus pack, saved before it was queued (`subscriber.rs:874-875`, `:915`).
`last_forwarded_consensus_number` still names X-1, since it is set after the send (`run_epoch.rs:732`).

`finish_epoch` then runs the leftover drain (`run_epoch.rs:637-638`).
Phase 1 forwards what is still queued, X+1 first, with no continuity check, and moves `last_forwarded_consensus_number` past X (`close_epoch.rs:319-338`).
Phase 2 reloads from the pack only numbers above it (`close_epoch.rs:345-348`), so X is never forwarded.
The only continuity check is the live path's (`run_epoch.rs:756`), whose comment assumes the queue "never drops an output" (`:750-755`): the queue does not, the cancelled send does.
The engine checks neither the output's number nor its consensus parent (`lib.rs:326-341`, `:169`; `crates/engine/src/payload_builder.rs:86-88`), so X+1 executes on X-1's state, and the `ModeChange` re-entry (`run_epoch.rs:649`) does not replay (`:85-88`).

## What it costs

From X+1 on, the node's blocks differ from the network's, without X's transactions or leader count for the epoch's rewards (`payload_builder.rs:98`).

By the code, the next epoch close stops the node if a record of that epoch is stored: `check_stored_record` logs `stored epoch record final_state does not match this node's closing block`, counts `tn_epoch_final_state_mismatches_total` and stops it (`close_epoch.rs:424-435`, `:712-749`).
If none is stored, the node builds, saves and publishes its own record, which no other validator signs.
We traced the drop, the drain, the engine and the re-entry, not the catch-up up to that close, so which branch a lagging node takes, and its votes meanwhile, are not known.

By then the divergent blocks are on disk.
The code's recovery path, `telcoin-network db reset-execution --force` (`crates/telcoin-network-cli/README.md:487-489`), rebuilds execution from the node's own consensus database, X included; we have not tried it here, and by the code a divergent record the node saved would stop the rebuild (`crates/tn-reth/README.md:968-977`).

It needs a lagging node and a pre-empted send; it costs that node, alone, its execution state.

## Evidence

Found while reviewing a change to the epoch-close path, then reproduced by `run_epoch::tests::a_mode_change_while_the_engine_is_full_loses_no_output`.
With outputs 1 to 3 in a pack, 1 filling a one-slot engine channel and 2 and 3 queued, it runs the real `wait_for_epoch_boundary` against `until_task_ends` (epoch shutdown notified), then the real leftover drain.
Its `select!` copies `run_epoch`'s shape but is not `run_epoch`: `biased`, forward first, so the exit wins while the send waits.
On main's code the engine channel receives `[1, 3]`, not `[1, 2, 3]`; with the fix below it passes.

Our benchmark runs show the trigger, not the symptom.
In [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) one validator logged `epoch task manager exited - likely syncing with committee` four times: three at 18:02 UTC under load, demoted an epoch behind and twice rejoining, and once at 18:42 UTC, rejoining after the run killed and restarted it.
Each time its lines put it at most 21 outputs behind, so the engine channel was not full; we did not read the depth gauge.
No node in bench 6's four runs ([r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), r20261113-1630, [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/), [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/)) logged a final-state mismatch or a `consensus output gap`.

## What a fix could look like

A fix is prepared on a branch, with no switch. It has two parts:

1. Reserve room in the engine channel before taking an output (`to_engine.reserve().await`, `recv()`, then `permit.send(output)`), so no await separates the two.
2. Phase 1 of the drain applies `check_output_continuity`: it skips an output already forwarded, and on a gap counts `tn_node_leftover_output_gaps_total`, logs an error and stops the node; the restart replays the missing output from the pack.

## How to verify

- The test above fails on main and passes with both changes.
- On a fleet, the trigger is the mode-change line, the closed-epoch warning (`run_epoch.rs:550-556`) or a shutdown, while `tn_engine_channel_depth` is 64.
  On main a hit surfaces at that node's close as the mismatch line and counter, if the record is stored.
  With the fix, the drain's gap error and counter flag a regression.

## Related

- #1575's notes for review named this case and promised a separate issue; this is it.
- #1618, the subscriber side, keeps the queue gap-free because Phase 1 has no continuity check; this hole is made after the queue.
- #1562 (closed by #1575): the earlier lossy broadcast.
