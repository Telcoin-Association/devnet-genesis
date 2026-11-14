# U-C2 — the interim comment on #1804 (execution-behind vote starvation)

Unit: `U-C2` (writer, opus). Rules: `tasks/bench7-agent-rules.md`, then `tasks/bench7/briefs/u-common.md` (binding). Checkpoint: `tasks/checkpoint-bench7-U-C2.md`. Budget: under 150k tokens.
You own `tasks/issue-comments/bench6-1804.md` and its note `tasks/issue-comments/notes/bench6-1804.sources.md`. No commits.

Read the issue and all its comments first (`gh issue view 1804 --repo Telcoin-Association/telcoin-network --comments`; its body is `tasks/issue-bodies/bench5-execution-behind-vote-starvation.md`), and #1782 (same read) since the two are linked.

## What the comment carries (400 to 600 words; this one may run to 600 because it reports two fixes and an open choice)

1. **The author-side fix, in both forms, measured in four runs.** A header names an execution block; bench 6 changed what the author names behind two switches: always the quorum-backed block with a floor 8 outputs behind the author's own tip ("always-on"), or the own tip until the author's headers went uncertified for 4 rounds and then the quorum-backed block ("adaptive"). Use the report's exact wording of both definitions (`tasks/bench6-report-r20261113-1351.md` §8 intro ≈ lines 642-660 and §4.3), not this brief's.
   - At 20,000 provisioned IOPS (the disk binds): own-header certification per run, fleet and lowest validator, for `r20261113-1351` (always-on) and `r20261113-2118` (adaptive), against bench 5 `r20261107-1504` where the fastest executors lost every certificate.
   - At 50,000 IOPS (the disk no longer binds): certification broke on some validators in both forms (`r20261113-1630`, `r20261114-0000`): the figures, and why (execution spread exceeds the 8-output floor; the replay arithmetic for floors 16 and 32 with its limits: it is arithmetic on measured data, before the kill, not a run).
   - What is not decided: which form, and the floor's depth. One run per form and disk; the comparison does not separate the form from which validators lagged; the senders' cost (#1807) rides on it. A further run of both forms at 20,000 IOPS is planned on a build of the current `main` (different storage engine); the form is proposed as a PR after it. Source for all of this: the report §4.3 and §8, and `benchmark/private/bench6-r20261113-2118/A7/comparison.md` §1, §2, §8, §9.
2. **The voter-side fix (the per-author lock wait), and that `main` still has the wait.** Bench 6 moved the bounded execution wait out of the author's vote lock and refuses a request the author has already superseded (switch `vote_queue_fix`; on in all four runs). What it measured: the lock-wait figures bench 6 reports with it on against bench 5 (report §4.3; the certification file the evidence index names).
   On `main` at 45dce8947 the wait is still there after the vote-handler rework (#1822, #1839, #1842, #1844, #1846): state it from `tasks/checkpoint-bench7-PT-2.md` (the unit that established it; private, do not cite): the per-author lock is held for the whole vote evaluation including the 1 s execution wait; a unit test on `main` as it is shows six queued requests of one author answered one second apart, the sixth after the 5 s vote timeout (give the test's name; it will be in the PR). Verify every `path:line` yourself in `/home/drtnarg/coding/telcoin/telcoin-network-b7`.
   One new observation for the maintainers: #1842's wait for a pending attached parent now also runs under that lock (up to the vote timeout); the bench-6 fix does not cover it.
3. **What comes next**: the voter-side fix is being ported to `main` and proposed as a PR against a staging branch now (it is independent of the form); the author-side PR follows the next run. Do not promise results.

Keep it a data comment: no advocacy for a form.
Hand back as `u-common.md` says.
