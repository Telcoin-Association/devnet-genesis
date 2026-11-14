# XF-1 — verify a reported output drop in main's epoch loop, reproduce it by test, then fix it (two phases)

Unit: `XF-1` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-XF-1.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-xf1`, branch `b7/xf1`, base = the integration head 14372820d (upstream main 45dce8947 + 19 commits, none of which changes the code in question except that the closing-block check unit edited other functions of the same two files). Domains: `tn-domain-epoch`, `tn-domain-execution`, `tn-domain-consensus`. Topic slug: `epoch-loop-output-drop`.

## The report (from the security evaluation of another change; CONFIRMED by its verifier, on upstream main 45dce8947 unchanged)

Full text: `tasks/bench7/review/03-closing-block-check-report.md` (the High finding and its evidence). In short:
- The epoch loop in `crates/node/src/manager/node/run_epoch.rs` forwards consensus outputs to the engine inside a `tokio::select!` (≈ :484); the forward is an awaited send on a bounded channel (≈ :730-732, `to_engine`).
- If `to_engine` is full (a node lagging in execution) and another arm of the `select!` fires while that send is pending (`closed_by_record`, or the node is demoted), the send future is dropped and **output X is lost**: it was already taken off its source and is held nowhere else.
- The leftover drain at the close (`crates/node/src/manager/node/close_epoch.rs` ≈ :320-340, "Phase 1") then forwards X+1 and later outputs with no continuity check, so the node executes X+1 on top of X−1: its execution diverges from consensus.
- Expected outcome on main: the node stops at its next epoch close on #1834's stored-record guard, with divergent blocks already persisted, so recovery needs a manual execution reset.
- The benchmark has produced this trigger shape before (a validator lagging in execution, demoted by commit lag, rejoining under load).

## Phase A — verify and reproduce (do this first; commit only test code; hand back if the verdict is not REAL)

1. Trace it yourself on your base, independently of the report: where an output is taken from its source in the loop; every `.await` between that point and the engine having it; which `select!` arms can pre-empt that await and under what conditions each fires (`closed_by_record`, demotion / mode change, shutdown, anything else); whether the output survives anywhere (a local variable re-used on the next iteration, a pending buffer, the consensus store from which the leftover drain re-reads it). Then the leftover drain: what it forwards, from where, starting at which output, and whether anything would notice a gap (the engine's own check of an output's number or parent? `grep -rn "consensus_number\|sub_dag_index\|expected.*output" crates/engine/src crates/node/src/engine | head -30`).
2. Say exactly what a dropped X does downstream: does the engine refuse X+1 (a number or parent check), execute it (divergence), or does a restart replay X from the consensus store and heal it?
3. Reproduce it with the smallest test that exercises the REAL code (not a model): the node crate's tests show how the epoch manager's pieces are driven in isolation (`crates/node/src/manager/node/run_epoch.rs` and `close_epoch.rs` test modules; the closing-block check unit added helpers that execute a closing output: read its tests at the end of `close_epoch.rs`). A full `to_engine` channel, an output in flight, the other arm firing; assert what the engine receives. If the loop cannot be driven in a unit test, drive the smallest extractable piece and say what the test proves and what it does not.
4. Verdict, in the first line of your hand-back:
   - **REAL**: a test on main's code shows an output lost and a later one forwarded (name the test; it fails on main and will pass with the fix).
   - **REAL, NARROWER**: the drop exists but something downstream catches it before execution diverges (say what and where).
   - **NOT REAL**: the output is not lost (say what holds it), with the test that shows it delivered.
   For REAL or NARROWER also state reachability under a benchmark: which bench conditions make `to_engine` full and one of the pre-empting arms fire (the engine's queue cap, a validator demoted while lagging, an epoch closing by record while a node is behind), and how the fleet would show it (which log lines and counters; grep bench 6's node logs ONLY if a line name makes a cheap check possible: `benchmark/results/r20261113-1630/logs/*-unit-stdout.log.gz` hold a run in which validators were demoted while lagging).

## Phase B — the fix (only if the verdict is REAL or REAL, NARROWER; same worktree; go straight on, do not wait)

Two separate commits, so each can be judged on its own:
1. **The forward is cancel-safe** (the root cause): no output is taken off its source until the engine channel has room for it (`reserve()` a permit, then take and send without an await in between), or the taken output is kept in the loop's state and sent first on the next iteration. Choose the form that changes the least and keeps the loop's other arms responsive (the reason the `select!` exists: a close or a demotion must still pre-empt a full channel). The Phase A test passes; add the mirror test for each pre-empting arm.
2. **A continuity check in the leftover drain**: the drain refuses to forward an output that does not directly follow the last one forwarded to the engine in this epoch, with an `error!` naming both numbers and a counter, and returns an error that stops the node the same way the file's other fatal mismatches do, BEFORE the gap is executed and persisted. With commit 1 in place it can never fire on an honest path: say so in its doc and test that; it exists so that a future regression stops a node cleanly instead of forking its execution.
No switch: this is a correctness fix (a switch whose "off" reproduces a dropped output has no use). No new dependency. Files you own: `crates/node/src/manager/node/run_epoch.rs` (the forward and its tests only), `crates/node/src/manager/node/close_epoch.rs` (the leftover drain's Phase 1 and its tests only; two other units edit other functions of this file: the record paths and the orphan re-pool), inline `metrics::counter!` in the `tn_node.*` style for the counter (do not edit `crates/node/src/metrics.rs`).

## Gates and review

As the rules say (check, fmt, clippy, whole-package nextest for the node package; each new test three times by name; the host is heavily loaded and an e2e gate may hold a quiet window: a cargo wait of 30 minutes is normal, never wrap cargo in a short timeout).
One `tn-domain-reviewer` (opus) on your diff, domains epoch and execution: can the fix reorder, duplicate or delay an output; can it deadlock the loop against the engine (the engine waiting on the loop for something while the loop waits for a permit); does every pre-empting arm still pre-empt.

## Hand back

The verdict line; the trace with `path:line`; the reproducing test's name and what it shows on main; reachability under a benchmark; for Phase B the two commits (shas, subjects), what each changes in five lines, gates with exit codes, the reviewer's answers; a draft, in plain language and at most 250 words, of how you would state the bug to the repository's maintainers (what happens, when, where in the code, what it costs a node) — a writer will turn it into an issue.
