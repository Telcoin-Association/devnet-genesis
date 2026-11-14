# U-I4 — a new issue: a lagging validator drops a consensus output when its epoch loop is pre-empted

Unit: `U-I4` (writer, opus). Rules: `tasks/bench7-agent-rules.md`, then `tasks/bench7/briefs/u-common.md` (binding). Checkpoint: `tasks/checkpoint-bench7-U-I4.md`. Budget: under 150k tokens.
You own `tasks/issue-bodies/bench6-epoch-loop-output-drop.md` (slug `epoch-loop-output-drop`) and its note `tasks/issue-bodies/notes/bench6-epoch-loop-output-drop.sources.md`. No commits.

## The finding (verified by a unit that reproduced it with a test on main's own code)

Everything is in `tasks/checkpoint-bench7-XF-1.md` (the trace with line numbers on main 45dce8947, the reproducing test and its failure, reachability, the fix, the unit's own 250-word draft statement at its end) and in the High finding of `tasks/bench7/review/03-closing-block-check-report.md` (how it was found).
The code: upstream main at 45dce8947 in `/home/drtnarg/coding/telcoin/telcoin-network-b7` (`git show 45dce8947:<path>` for main's own lines: the worktree's head has other topics' commits on top); the fix on the local, unpushed branch `b7/xf1` in `/home/drtnarg/coding/telcoin/tn-b7-xf1` (commits 4e149c9bf, 0151e03a8, 26c7ed72d).

## What the issue must say (500 to 800 words; the bench-5 bodies' section order)

- **What happens**, as a maintainer can check in the code: where the output is taken (`run_epoch.rs`), the awaited send on the bounded engine channel, the `select!` arms that can win while the send waits (name each and what triggers it), that the output is held nowhere else and the last-forwarded number is not advanced; then the leftover drain's first phase forwarding the next output with no continuity check, its second phase reloading from the pack only past the new last-forwarded number, and the engine checking neither the output number nor the consensus parent. Every `path:line` verified by you at 45dce8947.
- **What it costs**: the node executes past a gap; what stops it later and where (the stored-record guard at its next close: say which parts of this the verifying unit traced and which it did not, in those words); divergent blocks are on disk by then; recovery (`telcoin-network db reset-execution --force` exists on main: say it is the code's recovery path and that it was not tried).
- **Evidence**: the reproducing test by name and what it drives (the real forward and the real leftover drain on a manager with an engine and a pack; the `select!` is a copy of `run_epoch`'s shape, not `run_epoch` itself: say so), its result on main (`[1, 3]` instead of `[1, 2, 3]`), and that the same test passes with the fix. The benchmark side, stated exactly: the trigger shape occurs in our runs (a validator killed and restarted under load is demoted and rejoins while lagging; in `r20261113-1630` the restarted validator logged the mode-change line four times), and NO run showed the symptom (no final-state mismatch on any node): this was found by reading and reproduced by test, not observed on the fleet. Do not suggest otherwise.
- **Fix**: what the two changes do (room in the engine channel is taken before an output is taken, so no await separates the two; the leftover drain refuses a gap and stops the node before the engine passes it, and skips an output already forwarded), that a fix is prepared and will be proposed as a PR; no switch.
- **How to verify**: the test; what a fleet would log (the trigger lines, the later mismatch line and counter on main; with the fix, the drain's gap error and counter if a regression ever reintroduced a gap).
- Related issues as the checkpoint names them (#1618, #1562, #1575): read each with `gh issue view` before you cite it and say in one clause how it relates.
- Severity wording: plain. It is a correctness bug that needs a lagging node and a pre-empted loop; it costs that node its execution state. Do not call it a consensus-safety break: the node diverges alone and is stopped; say what happens to its votes and records between the gap and the stop only as far as the code shows it (a record no one else signs).

Title: a sentence of at most 120 characters stating the defect and its consequence.
Hand back as `u-common.md` says.
