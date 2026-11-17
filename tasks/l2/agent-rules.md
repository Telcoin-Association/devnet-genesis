# Launch 2 — rules for every agent (read first, they bind you)

Program: devnet launch 2 (worker gateways, committee firewall, public RPC node). Orchestrator log:
`tasks/ckpt-l2-orch.md`. Frozen interface contract (once written): `tasks/l2-contract.md`.
All paths below are absolute under `/home/drtnarg/coding/telcoin/`.

| Name | Path | What it is |
|---|---|---|
| DG | `dg-l2/` | devnet-genesis worktree, branch `l2/launch-2` (base `main` 884b760): ALL launch-2 code and doc edits happen here |
| REC | `devnet-genesis/tasks/` | launch-2 records only: checkpoints, fact sheets (`tasks/l2/facts/`), briefs, the contract. New files only |
| TND | `tnd-l2-gateway/` | tn-node-deployment worktree, branch `worker-gateway`, base `origin/main` 2813343 |
| TN | `tn-l2-img/` | telcoin-network worktree, detached at `origin/main` 5533ff73a (READ-ONLY for everyone but unit IMG) |
| PAS | `tn-p2p-allow-sync/` | the allow-sync tool's repo (read-only) |

**A benchmark program (bench 8) is live in `devnet-genesis/` (the main working tree) in another session.** It
runs gates and fleet drivers from that tree and edits `benchmark/` there. So: in `devnet-genesis/` you may
only create NEW files under `tasks/` named in your brief. Never edit, move or delete any other file there
(not `config.sh`, not a `devnet-*.sh`, not anything under `benchmark/`, not `tasks/plan.md`,
`tasks/lessons.md`, `tasks/todo.md`), never run a driver or a `benchmark/` gate from that tree, never kill a
process you did not start. Code goes to `dg-l2/`.

Never read or edit `dg-l2/tn-node-deployment/` or `devnet-genesis/tn-node-deployment/` (old submodule pin
d9446f7), any `common/` (a submodule: read its usage headers only if your brief says so),
`tn-node-deployment/` (the user's own checkout) or `telcoin-network/` (the user's own checkout).

## Scope
1. One deliverable. Your brief lists the paths you may READ and the paths you may WRITE. Do not read
   past the read list to "understand more"; if you need a fact that is not there, write the question
   in your hand-back. Do not write any file that is not on your write list (one owner per file).
2. Large files (over 400 lines) are read by line range only: `grep -n` first, then the range.
3. Budget: at most 45 tool calls and about 120 printed lines per call (pipe long output through
   `head`/`tail`/`grep`; write long output to a file under your scratch dir and read the part you
   need). You must stay well under 200k tokens. When you reach the cap: finish only the section you
   are in, rewrite the checkpoint, hand back what you have. A fresh agent resumes from it.
4. If the contract and the code disagree, or the contract cannot be implemented as written, stop
   that section and hand back a "contract change request" (what, why, the smallest change). Do not
   improvise a different interface: other units build against the same contract in parallel.

## Checkpoint (so a rate limit loses nothing)
- Your checkpoint is `devnet-genesis/tasks/ckpt-l2-<unit>.md` (named in your brief). On start, read
  your own checkpoint and continue from the first unfinished section.
- It starts with a `status:` line (`in-progress` | `blocked: <why>` | `done`) and a list of completed
  sections. Rewrite it after EACH section, not once at the end. Times come from `date -u` in the same
  command that writes the entry.
- If a Write is refused, do not work around it: return the complete text in your final answer.

## Hard rules
- No `git commit`, `git push`, `git stash`, `git reset`, `git rebase`, `git checkout <other branch>`,
  `git add`. The orchestrator makes every commit. No `gh` writes.
- No `gcloud`, no ssh to any host, no docker push, unless your brief says you are a fleet or image unit.
- No attribution of any kind (no "Co-Authored-By", no "Generated with") in any file, message or text.
- Secrets never on argv, in env, in logs or in your hand-back. `TN_SKIP_RELEASE_SIG` is the user's only.
- Never end your turn while a job of yours runs or waits; wait for it and read its exit line. A check
  is reported as passed only after you read its exit code in the same step.
- Shell lines that must all succeed are one `&&` chain, never `;`. Quote heredoc delimiters (`<<'EOF'`).
- Scratch files go under `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/<unit>/`,
  never in a repo.
- Bash style: the scripts run on bash 3.2 too (macOS operators). No associative arrays, no `mapfile`,
  no `${var,,}`, no `&>>`, no `declare -n`. TND has `tools/check-bash32.sh`; DG has
  `tasks/check-bash-portability.sh`.

## Gates on every script you edit (run them, read the exit code)
- `bash -n <file>`
- `shellcheck <file>` with the repo's own configuration (TND: as its CI calls it; DG: plain `shellcheck -x`)
- the repo's portability check named above
- your unit's tests, if it has any

## Hand-back (your final message, at most 60 lines, no file dumps)
1. `status:` done | partial (which sections) | blocked
2. Files written, with line counts (`wc -l`) and for edited files `git diff --stat -- <path>`
3. Gates: each command and its exit code
4. Deviations from the contract and contract change requests
5. Friction with tn-node-deployment or telcoin-network that an operator would also hit (one line
   each, with file:line): these feed `tasks/challenges-l2.md`
6. Open questions and anything you could not verify (say "not verified", never guess)
