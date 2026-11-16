status: done (SP-1, read-only inventory, 2026-11-16)
sections: summary, 00, 01, 02, 03, 04, xf, 05, 06, step-3 checks, judgment calls

# bench6 restack: stale-sentence check

Scope: the eight rendered bodies in tasks/pr-bodies/rendered/bench6-{00,01,02,03,04,xf,05,06}.md, against the FACTS of the brief. Switch statements were not read for staleness (a later pass owns them).
Cross-check done read-only: `gh pr list` shows #1862 base=main and #1863-#1869 each based on the head branch of the PR before it, with the branch names of the mapping. Same as FACTS.

## Summary

Hard staleness or contradiction with the FACTS: none in any of the eight files.
Step-1 grep: 0 hits for staging, of 6, of six, not sent yet, until that PR merges, this head contains, merge order, compare/, two later, six heads, six pull, five pull. The 17 hits it did return (the "PR N of 8" lines, ordinals such as "seventh commit", "sixth of six queued requests", and "a later head") are all fine.
Step 2: every sentence on stacking, targets, PR count, PR numbers and branch names agrees with the FACTS. Commit counts agree: 12, 8, 10, 3, 27, 8, 18, 17 (sum 103; 05:79 says 86 = the first seven).
Step 3: every file has exactly one "## Limits and what a reviewer should look at" and exactly one "The stack will be collapsed into #1862" sentence.

Judgment calls (not breaks of a FACT; the caller decides): J1 merge rationale (00,01,02,03,04,05), J2 benchmark-status sentences (02,03,04), J3 incomplete "Next:" lists (02,03,04), J4 a 24+2 versus 27 count (04).

## Step-3 table

| file | "## Limits ..." line (count) | "The stack will be collapsed into #1862" line (count) |
|---|---|---|
| 00 | 95 (1) | 8 (1) |
| 01 | 83 (1) | 9 (1) |
| 02 | 72 (1) | 9 (1) |
| 03 | 71 (1) | 10 (1) |
| 04 | 78 (1) | 8 (1) |
| xf | 79 (1) | 8 (1) |
| 05 | 98 (1) | 10 (1) |
| 06 | 105 (1) | 9 (1) |

## bench6-00 (PR 1 of 8, #1862, feat/bench6-switches-obs)

| line | sentence (cut to 200) | verdict | fact |
|---|---|---|---|
| 7 | PR 1 of 8 in the stack #1862 to #1869; this PR targets `main` (its base is main at 33b727fce), and each later PR targets the branch of the one before it, so every Files tab shows one change alone (12 c | fine | matches targets, base, 12 commits |
| 8 | The stack will be collapsed into #1862 (each PR merged into the branch below it); `main` is then merged into that branch and `make attest` runs on the result. | fine | the collapse plan |
| 9 | Please merge with 'Create a merge commit' so the next PR's diff collapses. | judgment J1 | rationale fits a bottom-up merge, not the collapse plan |
| 72 | On main at 33b727fce, at `17327280d` (the tip of `fix/1804-vote-queue`, #1864, which contains this head's twelve commits): | fine | #1864 = fix/1804-vote-queue; 12 commits |
| 84 | Stack-wide gates ran before these PRs were opened, on the top of the full stack: `fix/1807-digest-order-hold` at `500e21afa`, 103 commits on main at 33b727fce, carries the code of all eight pull req | fine | top and base and 103 agree; past tense, top commit 2026-11-15 13:32Z, PRs opened 19:02Z and 22:32Z |
| 98 | The first switch comes with `fix/1804-vote-queue`. | fine | branch is #1864 |
| 110 | Stacked on this: #1863 (`test/bench6-e2e-scaffold`), #1864 (`fix/1804-vote-queue`, ...), #1865 ... #1869 (`fix/1807-digest-order-hold`). | fine | all seven numbers and branches match the mapping |
| 114 | ...three of its switches do not carry to main and are not sent as pull requests. | fine | bench 6 extras, not stack members |

## bench6-01 (PR 2 of 8, #1863, test/bench6-e2e-scaffold)

| line | sentence | verdict | fact |
|---|---|---|---|
| 8 | PR 2 of 8 in the stack #1862 to #1869; #1862 targets `main`, this PR targets #1862's branch (`feat/bench6-switches-obs`), so the Files tab shows this change alone (8 commits). | fine | matches |
| 10 | Please merge with 'Create a merge commit' so the next PR's diff collapses. | judgment J1 | as 00:9 |
| 58 | ...at `17327280d` (the tip of `fix/1804-vote-queue`, #1864, which contains this head's eight commits)... | fine | mapping, 8 commits |
| 61, 66 | On the stack's earlier cut on main at 45dce8947 ... / ...before they were stacked | fine | dated history, not a claim about now |
| 86 | ...(from `feat/bench6-switches-obs`) ... it is not in this PR. | fine | branch is #1862 |
| 97 | Stacked on this: #1864 ... #1865 ... #1866 ... #1867 ... #1868 ... #1869 | fine | matches mapping |

## bench6-02 (PR 3 of 8, #1864, fix/1804-vote-queue)

| line | sentence | verdict | fact |
|---|---|---|---|
| 8 | PR 3 of 8 ...; this PR targets #1863's branch (`test/bench6-e2e-scaffold`) ... (10 commits). | fine | matches |
| 10 | Please merge with 'Create a merge commit' so the next PR's diff collapses. | judgment J1 | as 00:9 |
| 16 | ...the sixth of six queued requests is answered after the 5 s vote timeout. | fine | vote queue, not the stack |
| 53 | On main at 33b727fce, at this head's tip `17327280d`: | fine | tip of #1864 |
| 59 | Not run: no e2e test covers the switch, and no benchmark has run this head; a benchmark of the stack's earlier form on main at 45dce8947 runs it on, with the author-side switch, and has not finished. | judgment J2 | 05:23 and 06:67 report bench 7 as run on the earlier cut at 45dce8947, with published run links |
| 86 | Refs #1804: the voter's side only; the author's side is `fix/1804-quorum-exec-block`, which builds on this head. | fine | #1868 is above #1864 |
| 89 | Next: `fix/epoch-record-closing-block-check`, `fix/epoch-record-collector-hardening` and `fix/epoch-loop-output-drop` build on this head. | fine, incomplete J3 | true, but omits #1868 and #1869 (the stack is linear) |

## bench6-03 (PR 4 of 8, #1865, fix/epoch-record-closing-block-check)

| line | sentence | verdict | fact |
|---|---|---|---|
| 9 | PR 4 of 8 ...; this PR targets #1864's branch (`fix/1804-vote-queue`) ... (3 commits); the stack's base is main at 33b727fce. | fine | matches |
| 11 | Please merge with 'Create a merge commit' so the next PR's diff collapses. | judgment J1 | as 00:9 |
| 58 | - Not run: no fleet has run this head (a benchmark of the stack's earlier cut on main at 45dce8947, which carries the check, is under way), and no e2e test makes the check fire. | judgment J2 | as 02:59 |
| 85 | ...is in the epoch-close tests (`epoch_close_forms.rs`) of `fix/1804-quorum-exec-block`, a later head of the stack: ... | fine | #1868 is above #1865; only the word "head" is old |
| 87 | Next: `fix/epoch-record-collector-hardening` builds on this head. | fine, incomplete J3 | true; the direct next only |

## bench6-04 (PR 5 of 8, #1866, fix/epoch-record-collector-hardening)

| line | sentence | verdict | fact |
|---|---|---|---|
| 7 | PR 5 of 8 ...; this PR targets #1865's branch (`fix/epoch-record-closing-block-check`) ... (27 commits); the stack's base is main at 33b727fce. | fine | matches |
| 9 | Please merge with 'Create a merge commit' so the next PR's diff collapses. | judgment J1 | as 00:9 |
| 62 | Each of the 24 commits up to `8c76745f2` passed `cargo check --locked --all-targets -p tn-config -p state-sync -p tn-node -p tn-primary -p e2e-tests` with warnings denied; the two after it passed `ca | judgment J4 | 24 + the two after = 26 unless 8c76745f2 is a 25th; PR has 27; not verifiable here (local branches are not the restacked ones) |
| 65 | Not run on a fleet; a benchmark of this stack's earlier cut on main at 45dce8947 is running, and this text reports none of its results. | judgment J2 | as 02:59 |
| 89 | ...an e2e error message names `STACK_SWITCHES_ON`, which a later head adds. | fine | the constant arrives in #1868's commits |
| 95 | Next: `fix/epoch-loop-output-drop` and `fix/1804-quorum-exec-block` build on this head. | fine, incomplete J3 | omits #1869 |

## bench6-xf (PR 6 of 8, #1867, fix/epoch-loop-output-drop)

| line | sentence | verdict | fact |
|---|---|---|---|
| 7 | PR 6 of 8 ...; this PR targets #1866's branch (`fix/epoch-record-collector-hardening`) ... (8 commits). | fine | matches |
| 9 | Its node change needs nothing from the stack below: everything its first seven commits call is on main at 33b727fce ... the eighth adds the stop to `crates/e2e-tests/tests/it/fleet.rs`, which `fix/epoch- | fine | independence claim; not about targets |
| 10 | Please merge with 'Create a merge commit'. | fine | no rationale to go stale |
| 29 | ...which a later head of the stack uses too. | fine | later PRs exist; only the word "head" is old |
| 93 | Next: `fix/1804-quorum-exec-block` and `fix/1807-digest-order-hold` build on this head. | fine | complete |

## bench6-05 (PR 7 of 8, #1868, fix/1804-quorum-exec-block)

| line | sentence | verdict | fact |
|---|---|---|---|
| 9 | PR 7 of 8 ...; this PR targets #1867's branch (`fix/epoch-loop-output-drop`) ... (18 commits). | fine | matches |
| 11 | Please merge with 'Create a merge commit' so the next PR's diff collapses. | judgment J1 | as 00:9 |
| 23 | Bench 7 ran this head's node logic, on an earlier cut of the stack on main at 45dce8947 (branch `bench/bench7-2026-11`) ... | fine | dated history; also the contradiction partner of J2 |
| 78, 79 | at this head's tip `38f00e88e` / Every one of the 86 commits from main to the tip, this topic's 18 among them | fine | 12+8+10+3+27+8+18 = 86 |
| 115 | Refs #1804: the author's side; the voter's side is `fix/1804-vote-queue` (#1864). | fine | mapping |
| 116 | Next: `fix/1807-digest-order-hold`, the order hold for #1807, builds on this head. | fine | #1869 |

## bench6-06 (PR 8 of 8, #1869, fix/1807-digest-order-hold)

| line | sentence | verdict | fact |
|---|---|---|---|
| 8 | PR 8 of 8 ...; this PR targets #1868's branch (`fix/1804-quorum-exec-block`) ... (17 commits). | fine | matches |
| 10 | Please merge with 'Create a merge commit', like the rest of the stack. | fine | no stale rationale |
| 62, 63 | On main at 33b727fce, at this head's tip `500e21afa`: / Each of the 17 commits | fine | top and 17 commits agree |
| 67 | Bench 7 ran this head's node logic, on an earlier cut of the stack on main at 45dce8947, with the switch on: [r20261115-1131]... | fine | dated history |
| 123 | Stacked on #1868 (`fix/1804-quorum-exec-block`); the last PR of the stack. | fine | matches |

## Judgment calls

J1. "Please merge with 'Create a merge commit' so the next PR's diff collapses." (00:9, 01:10, 02:10, 03:11, 04:9, 05:11). The rationale belongs to the old model, where later PRs sat on a shared base and their diffs shrank when a lower PR landed. Now every PR targets the branch below it and its Files tab already shows its own change alone, and the plan is a collapse into #1862, not bottom-up merges to main. The request is not false, but its reason no longer matches the plan. xf:10 and 06:10 do not carry the reason. Suggested fix: keep the request, drop "so the next PR's diff collapses", or replace it with the reason that fits the collapse.

J2. Benchmark-status sentences (02:59, 03:58, 04:65) say a benchmark of the earlier cut at 45dce8947 is running or under way or has not finished. 05:23 and 06:67 in the same set report bench 7 as run on that cut (r20261115-1131, r20261115-1653, links). The bodies contradict each other; outside the FACTS list, so not counted as hard. Also 00:14, "the vote fix and the order hold wait for the next benchmark", is a benchmark-status clause tied to defaults (switch scope, not reported).

J3. "Next:" lists are uneven in a linear stack: 02:89 names three of five PRs above it; 03:87 only the next; 04:95 two of three; xf:93 and 05:116 are complete. Not wrong, incomplete.

J4. 04:62: "24 commits up to 8c76745f2 ... the two after it" gives 26 if "up to" includes 8c76745f2; the PR has 27. Reads right if the e2e commit 8c76745f2 is counted apart (24 + 1 + 2). Unverified: the local telcoin-network branches are not the restacked ones.
