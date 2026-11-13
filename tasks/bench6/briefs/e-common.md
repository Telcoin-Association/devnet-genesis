# Epoch-record investigation (E-1, E-2) — what each reads first

## The user's concern (2026-11-13, in their words)
"From the previous bench, I want to make sure epoch records are closing with a consensus of validators. I'm concerned that the decoupling execution state from consensus output and votes could end up with an issue at the epoch boundary with the certified records."

## What that refers to
The bench-6 node (worktree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, branch `bench/bench6-2026-11`, 2df831e3c; read-only: never edit, never build there) has a switch `quorum_exec_block` (the "vote fix").
With it off, a header names its proposer's own latest executed block and a voter whose execution has not reached that block waits or refuses.
With it on, a header names an older block that a quorum has executed (always, with `quorum_exec_block_starved_rounds=0`; only when the proposer is starved, with 4), so votes no longer depend on the voter having executed the proposer's tip: execution state is decoupled from the consensus output and from votes.
At an epoch boundary the validators close the epoch, write an epoch record that carries the epoch's final execution state, vote on it, and collect a certificate (`crates/node/src/manager/epoch_votes.rs`, `crates/node/src/manager/node/close_epoch.rs`, `crates/types/src/primary/epoch.rs`, `crates/storage/src/epoch_records.rs`).
A second switch, `epoch_record_state_check`, compares a stored record's final state with the node's own and stops the node on a difference; it went on together with the vote fix in every arm and run that had the fix.
The headline runs (run 2 and run 2b) run the always-on form with `vote_queue_fix`, `epoch_record_state_check` and `mdbx_random_advice`.

## What is already known (cite the unit, verify before you build on it)
- Run 1 (`r20261112-1520`, nine arms; the fix off in `a0-control`, `p1-mdbx-advice`, `a0-prime`; adaptive in `v-vote` and from `pool-local-r2` to `gr150`; always-on in `v-vote-floor-r2`): unit r1-A3 (`benchmark/private/bench6-r20261112-1520/A3/boundary.md`, `data/boundary.json`, `scripts/boundary.py`) read the epoch closes. At the loaded close of 20:00:32Z the record reached quorum with exactly 7 signers of 10 (validators 04, 05 and 02 missing); validator-02 was late at every loaded close and dropped out of the record; `epoch_record_state_check` never fired; no halt line in any log.
- Run 2 (`r20261113-1351`, always-on): six or seven epochs, one boundary (15:41:58Z) inside the five-minute outage of the killed validator-05, under full load.
- Run 2b (`r20261113-1630`) is still on the fleet while you work: do not wait for it and do not touch it.
- File layout, log layout (a trap: read it), exports: `tasks/bench6-run1-analysis-brief.md` §0 and `tasks/bench6-run2-analysis-brief.md` §0-§1.

## Rules
`tasks/bench6-agent-rules.md`, sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch (every agent)", "Investigations (`I-*`) and analysis units", "HAND BACK".
- Read-only on code and results; no git writes, no cargo, no gcloud, ssh or docker. Never open a node log with the Read tool: one `zcat | grep -F` pass per node into your scratch, at most four nodes at a time; reuse r1-A3's extracts under `benchmark/work/bench6-scratch/r1-A3/` when they hold the lines you need.
- Output: `benchmark/private/bench6-r20261113-1351/<unit>/findings.md` (the answer first; then the evidence, each statement with its file and line or the script and data file behind it; then what remains unknown; then options, not decisions) and `scripts/`.
- A mechanism is a path through the code that the runs' data agrees with at each step; say which of your statements are measured, which are read from code, and which are inferred.
- Prose: load the `human-writing` skill first; one sentence per line in Markdown. No IPs, instance ids or home paths in `findings.md`.
- Checkpoint `tasks/checkpoint-bench6-<unit>.md`, rewritten after each section with a `status:` header; on start read it and continue from the first unfinished section.
- If a Write of `findings.md` is refused, do not work around it: return its complete text in your final answer between the lines `===== BEGIN findings.md =====` and `===== END findings.md =====`.
- Budget: under 200k tokens; at about 160k finish the current section, checkpoint and hand back with the exact resume point.
- Final answer: at most 30 lines before any returned file text: status, the answer in five lines, the evidence that carries it, what is unknown, the options.
