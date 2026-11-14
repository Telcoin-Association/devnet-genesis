# U-P — the text of one pull request of the bench-6 stack

Unit: `U-P<NN>` (writer, opus; load the `human-writing` skill first). Rules: `tasks/bench7-agent-rules.md` ("What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Delta reads, writers …", "HAND BACK") and `tasks/bench7/briefs/u-common.md` (the rules for every public text: read it whole; a PR text is posted under the repository owner's name, unedited). Checkpoint: `tasks/checkpoint-bench7-U-P<NN>.md`. Budget: under 120k tokens.
You write ONE file per pull request: `tasks/pr-bodies/bench6-<NN>-<slug>.md`, and its sources note `tasks/pr-bodies/notes/bench6-<NN>-<slug>.sources.md` (not posted). You never run a `gh` write, never push, never edit a repository.

## The stack

Upstream repository `Telcoin-Association/telcoin-network`; base branch `staging/benchmark-bench6-2026-11`, created at upstream `main` 45dce89474e1efc7f90c6fbd1e51332cc237ab9b. The stack is one branch per topic, each head = the previous head plus its topic's commits; every PR targets the staging branch, so until the previous PR merges a PR's Files tab shows the stack below it too.

| NN | head branch | what | state |
|---|---|---|---|
| 00 | `feat/bench6-switches-obs` | the runtime-switch machinery, the `node switches` line, observability | PR now |
| 01 | `test/bench6-e2e-scaffold` | per-node parameters and environment in the e2e harness | PR now |
| 02 | `fix/1804-vote-queue` | `vote_queue_fix` (voter side of #1804) | PR now |
| 03 | `fix/epoch-record-closing-block-check` | the closing-block check (no switch) | PR now |
| 04 | `fix/epoch-record-collector-hardening` | the record collector's walk, conflict halt, re-certify | PR now |
| — | `fix/epoch-loop-output-drop` | #1860 | separate PR, later |
| 05 | `fix/1804-quorum-exec-block` | the vote fix, both forms | after the next benchmark decides the form |
| 06 | `fix/1807-digest-order-hold` | the order hold | after the next benchmark confirms it |

Your launch prompt gives your NN, the head's commit, the previous head's commit, the worktree to read the commits from (read-only), and the list of your topic's commits (`git -C <worktree> log --reverse --format='%h %s' <prev>..<head>`).

## Sources (your launch prompt names the ones for your topic)

- The commits themselves (`git -C <worktree> show <sha>`: read every one; the PR text describes what the code does, not what a note says it does).
- The topic's review scope and report (`tasks/bench7/review/<NN>-*.scope.md`, `…-report.md`): the reviewers' answers on "switch off = main" and "a mixed fleet is one chain", the residuals, what was fixed afterwards.
- The units' notes (`tasks/checkpoint-bench7-<UNIT>.md`): gates with exit codes, the names, the limits each unit recorded.
- The stack's assembly record `tasks/bench7-cherrypick-ledger.md` (the per-head gates on the assembled stack).
- The benchmark evidence: the public run pages and the issues (u-common.md lists them); the private analysis only through what u-common.md allows.
- The names: `tasks/bench7-contract.md` (every log line, metric and switch of the stack, from the code).
- The model: bench 5's PR texts `tasks/pr-bodies/bench5-0*.md` (structure, register, length). Their `{{…}}` placeholders are NOT available to you: the only placeholder you may use is `{{<issue-slug>}}` for an issue created by this program (slugs: `tasks/issue-bodies/TITLES-bench6.md`); refer to another PR of the stack by its head branch name, never by a number.

## The text (GitHub markdown, one sentence per line, 500 to 1,100 words)

1. `## Summary`: what the PR changes for a node operator and for a reviewer, in three to six lines; the switch and its default, or "no switch" and why.
   Then one paragraph, exactly this shape with your values: "PR <k> of 5 into `staging/benchmark-bench6-2026-11` (merge order: 00, 01, 02, 03, 04). Stacked on `<previous head branch>`: this head contains its commits, so the Files tab shows them until that PR merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/<prev sha>...<head sha> (<n> commits). Please merge with 'Create a merge commit' so the next PR's diff collapses." (PR 00 says "The first of the stack: its base is `main` at 45dce8947.")
2. `## Problem`: what the benchmark or the code shows on main, with the run id linked and the issue referenced; what is measured, what is inferred from code, what is not known, in those words.
3. `## Change`: one bullet per commit, in order: the short sha in backticks, the subject, then what it does and what it deliberately keeps (invariants). A reader must be able to review commit by commit.
4. `## With the switch off` (or `## What changes for every node` when there is no switch): exactly what newly runs with every switch at its default (log lines, fields, metrics, reads), from the review's answer 2a, checked against the code; and the mixed-fleet statement (2b).
5. `## Testing`: the unit tests by name where they pin the claim; the gates that ran on this head, with counts, from the ledger and the unit notes (commands in backticks, results as "N passed"); the e2e tests where they exist; what was NOT run and why. Leave no blank to fill: write what the record shows today, and end the section with one line starting `Stack-wide gates:` followed by the sentence "run on the top of the stack before these PRs were opened; results in the stack's last PR." (the orchestrator replaces that sentence with the results before posting).
6. `## Limits and what a reviewer should look at`: the residuals the review recorded and the unit's own stated limits, each in one or two lines, with what would close it; anything the review asked to fix before merge that is NOT fixed (there should be none: say so if so).
7. `## Related`: the issues this PR addresses or informs (`Refs #…`, never `Fixes` unless the PR closes the issue completely: say which), the next PRs of the stack that build on it.
PR 00 only: a section `## What bench 6 measured that is not in this stack`, the content of `tasks/bench6-not-carried-writeup.md` condensed to at most 200 words with its two issue references.
Never in the text: unit names, private paths, host names, the cloud project, any mention of an assistant or a tool that wrote or reviewed anything ("an internal review", "we"), a figure without its run id.

## Hand back

The file path, the word count, the title you propose for the PR (at most 72 characters, conventional-commit form as bench 5's), every figure with its source in the sources note, anything you could not trace and left out, and anything in the commits that the notes or the review describe differently (the code wins: say what you wrote).
