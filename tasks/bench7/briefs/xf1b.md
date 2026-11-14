# XF-1b — review follow-ups for the epoch-loop output-drop fix

Unit: `XF-1b` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-XF-1b.md`. Budget: under 120k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-xf1b`, branch `b7/xf1b`, base = the integration head 5879d7ce6 (the fix's three commits are in it: `git log --oneline --grep='Topic: epoch-loop-output-drop' 45dce8947..HEAD`). Domains: `tn-domain-epoch`, `tn-domain-execution`. Topic slug: `epoch-loop-output-drop`.

## Background

The fix (brief `tasks/bench7/briefs/xf1.md`; the unit's notes `tasks/checkpoint-bench7-XF-1.md`): the epoch loop's forward to the engine reserves room in the engine channel BEFORE it takes an output off the queue, and hands it over with no await in between; the leftover drain's queue phase skips an output already forwarded and stops the node on a gap.
Its review and security evaluation (`tasks/bench7/review/07-epoch-loop-output-drop-report.md`: read findings 1 to 8 in full, with their evidence) approved it with follow-ups. Do findings 1, 2 and 3; record 5 in a doc comment; leave 4, 6, 7 and 8 as the report states them unless a one-line doc makes one of them clearer.

## What to change (files: `crates/node/src/manager/node/run_epoch.rs`, the forward and its tests; `crates/node/src/manager/node/close_epoch.rs`, the leftover drain's queue phase and its tests; nothing else)

1. **Finding 1: a closed engine channel while the permit is held.** The live forward holds its permit through the wait for the next output; if the engine's receiver is gone by the time the output arrives, `Permit::send` drops the output without an error and the forwarded counter still moves. Make the hand-over notice it: check `to_engine.is_closed()` at the hand-over (or the equivalent that this channel type offers on your base: read it) and take the path the old awaited send's error took (the function's existing "engine is gone" error), so the forwarded counter does not move for an output nobody received. Reword the two docs the report names (`run_epoch.rs` ≈ :733-735, `close_epoch.rs` ≈ :315-318) so they say what is true: main was blind only between its send's check and its write; here the window is the wait between two outputs, bounded because the engine is a critical task whose exit ends the node's outer select. A unit test: the receiver dropped while the forward waits for an output; the forward returns the error and the counter has not moved.
2. **Finding 2: `try_recv` on the live path can park a runtime worker thread** (the report cites tokio's channel code): use `recv().now_or_never()` (the `futures` crate's `FutureExt`; check it is already a dependency of the node crate: NO new dependency; if it is not available, say so and use the smallest equivalent with what the crate has, e.g. polling `recv()` once with a no-op waker through an existing utility). Behaviour must be identical for the three cases (an output ready, none ready, channel closed): pin them in a test if the existing tests do not.
3. **Finding 3: the stale-skip is hard to see.** The warn line for an output the drain skips as already forwarded gets the output's number, its digest and which phase skipped it (take the field names from the neighbouring lines: `number`, `digest`, … as the file writes them), and a counter in the file's inline `metrics::counter!` style: `tn_node.leftover_outputs_skipped_total` (no label). Doc: with the live forward's fix an honest run produces none; a count above zero says an output was queued twice.
4. **Finding 5 (doc only)**: say at the forward that batch eviction and the quota release for an output now happen when the NEXT output is taken (one output later under backpressure) and why that is harmless, if the report's evidence convinces you; if you find it is not harmless, stop and hand back.

## Gates and review

As the rules say: `cargo check --locked --all-targets -p tn-node`, the fmt check, clippy for the package, `cargo nextest run --locked -p tn-node --no-fail-fast` (whole package), each new test three times by name; all cargo through `tasks/bench6/cargo-slot.sh`; never wrap cargo in a short timeout; never end your turn while a gate runs.
The fix's own reproducing tests must still pass unchanged: `run_epoch::tests::a_mode_change_while_the_engine_is_full_loses_no_output` and its mirrors.
One `tn-domain-reviewer` (opus) on your diff, domains epoch and execution: can the closed-channel check turn a clean shutdown into an error line or a fatal stop it was not before (a node shutting down normally closes the engine: what does the loop do then, on main and now); is `now_or_never` on this channel type free of the parking the report describes.
Commits (one per finding, or one if they are inseparable): conventional subjects (`fix(node): …`), bodies in plain prose, then `Topic: epoch-loop-output-drop` as the last line; no issue number yet (the orchestrator adds it in the PR text); no attribution of any kind.

## Hand back

As the rules say, plus: per finding what changed with `path:line`; the new names verbatim (the counter, the log fields); the shutdown answer from the review; gates with exit codes.
