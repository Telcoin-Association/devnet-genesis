# Investigations after run 1 (I-7, I-8, I-9) — what each reads first

Run 1 of bench 6 (r20261112-1520, an arms run on ten validators and an observer) is analysed; the fleet is deleted; everything is local.
Rules: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md`, sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch (every agent)", "Investigations (`I-*`) and analysis units", "HAND BACK".
Then, in `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-r20261112-1520/` (below `P/`): `cross-unit-notes.md` in full (what the eight analysis units established), and the candidate your brief names in `A7/candidates.md` (its evidence and what is missing).
The run's facts and file layout: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-run1-analysis-brief.md` §0 and §1 (note the log-layout trap in §0).

- The node code of the run is the worktree `/home/drtnarg/coding/telcoin/telcoin-network-b6` (branch `bench/bench6-2026-11`, 2df831e3c; read-only: never edit, never build there). The twelve switches and each topic's design: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md` (grep your switch names; read only those parts). Load the `tn-rust-skills` skill and the `tn-domain-*` skill your brief names before reading node code.
- You change no code and run no cargo. You read code, the units' outputs and extracts, and the run's logs through scripts.
- Never open a node log with the Read tool. The prefiltered whole-run logs are `benchmark/work/prefilter/r20261112-1520/logs/<node>-unit-stdout.log.gz` (about 100 MB each); the full ones `benchmark/results/r20261112-1520/logs/<node>-unit-stdout.log.gz` (about 4 GB plain each). One `zcat | grep -F` pass per node into your scratch, at most four nodes at a time; reuse another unit's extract when it has what you need (each unit's hand-back names its extract directory under `benchmark/work/bench6-scratch/`).
- Output directory: `P/<unit>/` with `findings.md` (the answer first, then the evidence, each statement with its file and line or the script and data file behind it; then what remains unknown; then what you would change or measure next, as options, not as a decision) and `scripts/`.
- A mechanism is a path through the code that the run's data agrees with at each step; a correlation between two series is not one. Say which of your statements are which.
- Prose: load the `human-writing` skill first; one sentence per line in Markdown. No IPs, instance ids or home paths in `findings.md`.
- Checkpoint `tasks/checkpoint-bench6-<unit>.md`, rewritten after each section with a `status:` header; on start read it and continue from the first unfinished section. If a Write is refused, do not work around it: return the text in your final answer.
- Budget: under 200k tokens; at about 160k finish the current section, checkpoint and hand back with the exact resume point.
- Final answer: at most 30 lines: status, the answer in five lines, the evidence that carries it, what is unknown, the options.
