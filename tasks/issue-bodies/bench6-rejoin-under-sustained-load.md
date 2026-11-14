# A validator restarted under sustained load stayed inactive until the load ended: it replays at about the network's rate

## What happens

A validator killed under load and started again 300 s later stayed `CvvInactive` until its replay passed the end of the load.
In bench 6 that took 16m40.8s and 16m30.1s from its start in the two headline runs, and 17m39.6s and 25m00.1s in the two runs with the adaptive vote form.
The promotion itself worked: one per restart, held, first certified header within a second.

While it followed:

- the committee ran at least one validator short from the kill to the promotion, 21m30.2s to 30m00.0s;
- it signed neither of the two epoch records closed after the kill: the first closed while it was down, the second while it was still replaying;
- its RPC refused every transaction submission with error code -32603 and the message `validator is inactive; retry another endpoint`;
- it answered reads from its own executed head, 402 to 605 outputs behind the network's in per-minute samples.

## Evidence

Ten validators in ten regions; ten closed-loop generators, each pinned to its own validator.
Validator-05 was killed with SIGKILL during the main load blast and started 300 s later.
The node build is `bench/bench6-2026-11` at `2df831e3c`, with bench 6's vote changes switched on.
They are not on main and let the network run at its validators' execution rate.
We have not measured main under this load, so whether a restarted validator gains on main's network is not known.

| run | vote form, disk IOPS | start to `CvvActive` | outputs behind: open-epoch entry, end of load | follower / network outputs per s under load | generator 05 landed nothing, kill to end of load |
|---|---|---|---|---|---|
| [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) | always-on, 20,000 | 16m40.8s | 452, 513 | 1.332 / 1.409 | 949 s |
| [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) | always-on, 50,000 | 16m30.1s | 470, 515 | 1.180 / 1.243 | 899 s |
| [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) | adaptive, 20,000 | 17m39.6s | 438, 402 | 1.305 / 1.288 | 1,008 s |
| [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/) | adaptive, 50,000 | 25m00.1s | 429, 466 | 1.063 / 1.091 | 1,374 s |

- Each start replayed the epoch that closed during the outage, then followed the open epoch with every check failing on `reason=round_gap`: 802 to 1,144 rounds against a window of 20.
- Execution was the bound: in the three runs where we read it, the follower's `tn_engine_queued_outputs` was 8 in nearly every minute.
- In r20261113-2118 the follower gained about 4.5 outputs a minute: roughly 90 more minutes of load to reach the window (inferred from that slope).
- Promotion came 5m01.9s to 5m54s after the load's cooldown ended.
- In the headline runs generator 05 sent about 580 to 593 transactions a second after the restart, and every one was refused, from about 10 s after the start until the load ended.
  The refusal says to try another endpoint; our generator is pinned to one node and does not.

## Where in the code

On main at 45dce8947; the rejoin rule is unchanged from the bench-6 build.

- `rejoin_ready` (`crates/consensus/executor/src/subscriber.rs:136-149`) promotes when the handled output trails the newest known header by at most `rejoin_round_window(gc_depth)` rounds, (50 - 10) / 2 = 20 at the default `gc_depth` (`crates/types/src/primary/mod.rs:52`, `:87-89`).
- State sync hands a follower an output only after local execution reached the block that output's leader names (`crates/state-sync/src/lib.rs:616-624`), so a follower replays at its own execution rate.
- The window was sized for a node under load that is "always a few outputs behind" (`subscriber.rs:130-132`).
  A restarted validator comes back hundreds behind, and at the network's execution limit it replays at about the network's rate.
- `test_restarts_lagged_under_load` (`crates/e2e-tests/tests/it/restarts.rs:1873-1888`) requires a rejoin "before the load stops" under one account sending from one thread (`spawn_load`, `:1846`), far below that limit.
- While `CvvInactive`, `node_mode_accepts_submissions` (`crates/tn-reth/src/rpc_fee_cap.rs:57-62`) refuses every submission, by design since #1514; reads are not gated.

## What a fix could look like

The rejoin code does what it says; the replay sets the time.
Options, none on main:

- Catch up from a state snapshot of the committee's executed head and replay only a short tail.
- Let the follower's handled round run ahead of its execution, up to the bound an active validator already gets (`MAX_COMMIT_RUN_AHEAD_ROUNDS` = 1,000, `crates/types/src/primary/mod.rs:217`), so the rejoin rule sees the head.
  The gaps above sit near that bound, state sync's fork check would trail with execution, and the node would still sign no record until its execution reaches the close.
- Keep the network's production below its execution limit by a margin, so a follower gains, at a cost in throughput.

Separately: should a following validator forward submissions to active members, as an observer does, instead of refusing them?

## How to verify

- A run like bench 6's: kill a validator under a load that holds the committee at its execution limit, restart it 300 s later, and measure start to `CvvActive` while the load continues and whether it signs the next record.
- An e2e version (not built): every validator under the same `TN_TEST_EXECUTION_DELAY_MS` (`crates/types/src/test_hooks.rs:117`) so execution paces the network, and one validator restarted a few hundred outputs behind under load.

## Related

- #1513 (closed): its fix replaced the exact-head rule with the 20-round window: enough for a node a few outputs behind, not hundreds.
- #1801 (closed, fixed by #1818): a promotion that failed and looped.
  Bench 6 ran with that fix, and every promotion after a restart held at once; this issue is the wait before it.
