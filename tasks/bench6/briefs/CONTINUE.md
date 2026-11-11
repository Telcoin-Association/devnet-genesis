# Continuing a unit that another agent started

The first agent for your unit was cut off on 2026-11-11 (between about 01:45Z and 02:05Z) by an account rate limit, and it cannot be
resumed. You are the second agent for the same unit. Its brief is `tasks/bench6/briefs/<unit>.md` (lower-case unit id, under
`/home/drtnarg/coding/telcoin/devnet-genesis/`); wherever that brief says "You are unit X", that is you now, with the same ownership,
the same limits and the same hand-back.

## Read, in this order
1. The rules: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (the sections your brief names).
2. Your unit's brief.
3. Your unit's checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-<unit>.md` (the brief gives the exact
   name). It records what the first agent finished, what it decided and what remained.
4. What is actually on disk: `git status --short` and `git diff` for the files the brief lists as yours (node units: in your own
   worktree, plus `git log --oneline` against the base). The orchestrator's prompt tells you what it saw there.

## How to treat what you find
- The checkpoint can under-report. Uncommitted edits in your unit's files are the first agent's work in progress: read that diff
  critically before anything else. It may never have been compiled or tested. Keep what is right, fix what is wrong, finish what is
  missing. Do not start over and do not rewrite working code to your own taste.
- Do not trust a result you have not seen. "Tests passed" or "review approved" in the checkpoint counts only if a log file with an
  `EXIT=` line backs it AND the files have not changed since that log was written (compare modification times); otherwise re-run it.
- Every background job and every sub-agent the first agent started is gone (builds, test runs, reviewers, mutation runners).
  Start again whatever your brief still requires, the domain review included.
- Commits the first agent made (node units) stand. Check each compiles and carries its `Topic:` footer; do not amend them unless
  one is wrong, and then say so in the hand-back.
- Decisions recorded in the checkpoint's notes stand unless you find them wrong; if you overturn one, say why.

## What changed since the first agent stopped
- **Scratch**: write new scratch only under
  `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/32c51110-7507-4447-a3fb-2d90bd31a117/scratchpad/<unit>/`.
  The first agent's scratch (mutation runners, logs) may still exist under
  `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/5182cb11-39b0-49d7-92e2-41574ff8f3c2/scratchpad/<unit>/`: you may
  read and copy from it, write nothing there.
- **Build wrapper**: every compiling cargo call goes through
  `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo <args>`. Run it in the background with a log and wait
  for it; a wait of up to about 45 minutes is normal while the orchestrator holds a quiet window, and is never a reason to call
  cargo directly.
- **Quiet window**: while the file `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/QUIET` exists, an I/O probe is measuring
  this machine's disk. Until it is gone: no docker, no cargo outside the wrapper, no large copies or extractions onto the home disk.
  Reading, small edits, checkpoints and unit tests that use temp dirs under `/tmp` (a tmpfs) are fine.

## While you work
Rewrite the checkpoint after each section, and add the line `continued by a second agent on <date -u output>` under `notes:`.
Hand back as the rules describe: a summary, not file dumps.
