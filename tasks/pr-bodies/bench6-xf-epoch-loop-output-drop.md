## Summary

The epoch loop now reserves room in the engine channel before it takes a consensus output, so an exit that pre-empts the forward while the engine lags no longer drops the output.
The leftover drain's queue phase skips an output already forwarded and stops the node on a gap, before the engine executes past it.
No switch: it fixes a loss on main.

Into `staging/benchmark-bench6-2026-11`, after the stack's first five pull requests (merge order: 00, 01, 02, 03, 04, then this).
Stacked on `fix/epoch-record-collector-hardening`: this head contains its commits, so the Files tab shows them until that PR merges; this change alone is https://github.com/Telcoin-Association/telcoin-network/compare/ca258b37ce6e4d03308008bd39216cfbe7cb1990...38a8012f5977e397e75e83d10a54c445a763f4e6 (9 commits).
Its node change needs nothing from the stack below: everything its first eight commits call is on main at 45dce8947, and their diff applies there with fuzz (checked, not built); the ninth adds the stop to `crates/e2e-tests/tests/it/fleet.rs`, which `fix/epoch-record-collector-hardening` creates.
Please merge with 'Create a merge commit'.

## Problem

#1860 traces the drop on main at 45dce8947: output X, taken off the queue (`crates/node/src/manager/node/run_epoch.rs:749`), is lost when another `select!` arm wins while its send to a full engine channel waits (`:730`), and the drain forwards X+1 unchecked (`close_epoch.rs:320`).
Measured: on main's code the issue's reproducing test delivers `[1, 3]` to the engine, not `[1, 2, 3]`.
Inferred from code: the engine then executes X+1 on X-1's state.
The trigger, a validator changing mode under load, occurred in [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/); the symptom was not seen in bench 6's runs, and how often a full channel meets such an exit is not known.

This PR does both parts of the issue's fix and leaves the engine and the `ModeChange` re-entry as they are.

## Change

- `fb9204bfc` `fix(node): take room in the engine channel before taking a consensus output`: `process_output` splits into `reserve().await` and `forward_output`, which sends through the permit without awaiting; the live forward reserves, takes, then hands over.
  Same outputs, order and flags; the `forwarded_at` stamp (observability only) starts at the wait for room.
- `befa26c27` `fix(node): stop the node on a gap in the leftover drain's queued outputs`: the queue phase applies the live forward's `check_output_continuity`.
- `98b3087b5` `test(node): cover a forward cancelled while it waits for an output`: the second cancel point; main's `recv` was already cancel safe there, so it would pass on main too and guards the held permit.
- `d7babdcb3` `fix(node): take a queued output with one poll instead of try_recv`: tokio 1.53's `try_recv` can park the OS thread on a send in progress; one poll of `recv` cannot.
- `9e1456086` `fix(node): fail the live forward when the engine is gone at the hand-over`: a held permit's send drops the output silently if the engine has gone, so the forward checks `to_engine.is_closed()` first.
- `0f3b0018a` `test(node): capture log lines in the epoch-close tests`: test-only; its own commit because a later head of the stack uses it too.
- `7b1a0bf01` `fix(node): name and count the outputs the leftover drain skips`: the fields and counter below.
- `a80927410` `docs(node): say when the forward evicts and why the drain stays unraced`: the drain must never run under a `select!`.
- `38a8012f5` `test(e2e): count the leftover drain's gap stop as a fatal line`: test-only; the stack's e2e tests fail on a node that logs the stop.

## What changes for every node

- The next output's batch eviction and quota release run after the wait for room.
- The drain skips a stale output (main forwarded it again, to execute twice) and stops on a gap (main forwarded past it).
- New counters `tn_node_leftover_output_gaps_total` and `tn_node_leftover_outputs_skipped_total`; the live `skipping already-forwarded consensus output` warning gains `digest` and `path` (`live`), and the drain's new one carries them (`leftover_queue`).
- No new reads; nothing consensus-visible.

Mixed fleet: the change is local to a node's epoch manager and its own engine, so fixed and unfixed nodes run one chain.

## What a reviewer will ask first

Can the new stop fire on an honest path?
Traced in the code, no path reaches it (restarts, mode changes, replay, followers, rejoins, an epoch's first output): every producer saves an output before queuing it, in order, the counter is primed from the pack's anchor, and the live forward now hands over every output it takes.
Main's live forward already stops on the same rule; as on main, a failed pack read in the drain leaves the counter short and stops the next run on a gap.

And a clean shutdown?
The engine stops on the same notification, so if its channel closes first the node can log `failed to reach epoch boundary` or `error sending leftover consensus output to engine` as it exits, as main can; nothing is lost.

What does an operator see if the stop fires?
Logged at error, target `epoch-manager`, fields `number` and `last_forwarded`: `leftover consensus output does not follow the last output forwarded to the engine: stopping the node before the engine executes past the gap`.
The node exits with `leftover consensus output gap: expected <n> but received <m> - stopping the node; a restart replays the missing output from the consensus DB`.
The counter rarely reaches a scrape; the log line is the signal.
Restart and keep the datadir: the startup replay (`replay_missed_consensus`) forwards from the executed tip, reading each output from the consensus pack (persisted before the drain).
The stop means a regression: report it with the log.

## Testing

- `run_epoch::tests::a_mode_change_while_the_engine_is_full_loses_no_output`, #1860's reproduction, fails on main's code and passes here.
  Mirrors: `the_node_ending_while_the_engine_is_full_loses_no_output`, `a_closing_record_while_the_engine_is_full_loses_no_output`, `a_mode_change_while_the_forward_waits_for_output_loses_no_output`.
- The forward's intake: `the_forward_takes_an_output_queued_during_its_wait_for_room`, `the_forward_stamps_a_late_output_on_arrival`, `the_forward_drains_a_closed_queue_then_ends`, `the_forward_fails_on_an_engine_gone_while_it_waits`.
- The drain: `the_leftover_drain_stops_on_a_gap_before_the_engine_gets_past_it` (nothing reaches the engine), `the_leftover_drain_skips_an_output_already_forwarded`, `the_leftover_drain_logs_and_counts_an_output_it_skips`.
- On a2c4dfae9 (an earlier cut of the first eight commits, on `bench/bench7-2026-11`: the same node code, without the stack's e2e test files, which these gates do not build): `cargo check --locked --all-targets -p tn-node` exit 0; `cargo nextest run --locked --no-fail-fast -p tn-node` 276 passed, 1 skipped, these 11 among them; `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-node -- -D warnings` exit 0.
- Not run: no e2e test drives the race through the real loop, and no fleet has run this head yet.

Stack-wide gates: run on the top of the stack before these PRs were opened; results in the stack's last PR.

## Limits and what a reviewer should look at

- The tests drive the real forward and drain under a `biased` copy of the loop's `select!`, not `run_epoch` itself; a test of the real loop would close that.
- Untested: the `store_failed` arm, the pack phase after a cancelled forward, a boundary output among the leftovers.
- Left as on main: the shutdown lines above, and the drain stashing a boundary header before its send.
- `crates/engine/src/metrics.rs:81` still says the forward stamp is taken just before the send.
- Not detected: a node that already executed past a dropped output on an older binary.
- Nothing found before opening this PR is left unfixed.

## Related

- Fixes #1860: both parts of its proposed fix are here, and its reproducing test passes.
- #1575, whose notes for review named this case.
- #1618, the subscriber side of the same teardown, is not changed here.
- Next: `fix/1804-quorum-exec-block` and `fix/1807-digest-order-hold` build on this head.
