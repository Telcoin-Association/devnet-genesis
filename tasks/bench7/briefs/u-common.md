# Track U — common rules for the writers of issue bodies, issue comments and PR texts

Read after `tasks/bench7-agent-rules.md` (the sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Delta reads, writers …", "HAND BACK") and before your own brief.
You write text files. The orchestrator creates the issues, comments and PRs from them, so **what you write is posted publicly under the repository owner's name, unedited**. You never run a `gh` write.

## Where the facts are

- The public record: the four run pages (`https://benchmark.telcoin.network/runs/r20261113-1351/` always-on at 20,000 IOPS, `…/r20261113-1630/` always-on at 50,000, `…/r20261113-2118/` adaptive at 20,000, `…/r20261114-0000/` adaptive at 50,000; they go live during this program) and bench 5's page `…/r20261107-1504/`. Link a run id to its page at first mention.
- The private record you may read and must not cite by path or unit name: the report `tasks/bench6-report-r20261113-1351.md` (its §7 "Evidence index" maps every topic to the analysis files under `benchmark/private/bench6-r20261113-1351/` and `benchmark/private/bench6-r20261112-1520/`; the adaptive runs are under `benchmark/private/bench6-r20261113-2118/` and `…-r20261114-0000/`), `tasks/bench6-upstream-followups.md` (what each topic's review left open), the topic reviews `tasks/bench6/review/<topic>-report.md`.
- The code: bench 6's node build is the pushed branch `bench/bench6-2026-11` at `2df831e3c` (worktree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only). Upstream `main` today is **45dce8947** (worktree `/home/drtnarg/coding/telcoin/telcoin-network-b7`, read-only): storage v2 with tn-lmdb by default (#1834), the vote-handler rework (#1822, #1839, #1842, #1844, #1846), #1841, #1827.
- The issues as they stand: `gh issue view <n> --repo Telcoin-Association/telcoin-network --comments` (read the body and every comment before you write, so nothing is repeated and nothing contradicts an earlier post without saying so). The bench-5 bodies that opened #1799 to #1807 are `tasks/issue-bodies/bench5-*.md`: the model for structure, register and length.

## Rules for every text

- Load the `human-writing` skill first. Plain language, short sentences, no filler, no emphasis by bold in running text. A maintainer who knows the code but did not follow the benchmark must be able to act on it.
- **Check the claim against `main` (45dce8947) before you write it as present tense.** For every defect or gap: find the code on M, cite `path:line` at M, and say "on main at 45dce8947". If M already fixed or changed it, say so and what is left; if nothing is left, the text is not filed: tell the orchestrator. Code that only exists on the bench-6 branch is named as such.
- Every figure exactly as its source has it, with its run id and what it counts. Keep a sources note beside each text, not for posting: `tasks/issue-bodies/notes/<slug>.sources.md` (or `tasks/issue-comments/notes/…`, `tasks/pr-bodies/notes/…`): figure → file and line (private paths are fine there).
- Never in the posted text: unit names (A2, I-10, E-3, U6a, ST-B …), private paths (`benchmark/private/…`, `tasks/…`), a host name, a person's name other than a GitHub handle the issue already uses, the cloud project id, an IP address, "run 2 / 2b / 3 / 3b" without the run id, any mention of an assistant, an agent or a tool that wrote or analysed anything. "We measured", "the benchmark shows".
- Say what was measured, what is inferred from code, and what is not known, in those words. A timing correlation is not a mechanism. One run per configuration: say so where a conclusion rests on one run.
- A new issue: H1 = the title (a sentence stating the defect and its consequence, at most 120 characters; if the best title is longer, give a ≤ 120 form in your hand-back), then sections in the bench-5 bodies' order (what happens, evidence, where in the code, what a fix could look like, how to verify). 400 to 900 words. Reference other issues as `#<n>`; a reference to an issue not yet created is written `{{slug}}` (the orchestrator substitutes the number at creation) and listed in your hand-back.
- A comment on an existing issue: starts with one sentence saying what it adds ("Bench 6 data for this issue: …"), then the data, then what it changes about the issue (confirmed, narrowed, moot on main, a fix measured), then what is still open. 150 to 500 words. No greeting, no sign-off.
- One file per text; you own exactly the files your brief lists. Markdown as GitHub renders it; one sentence per line.

## Hand back

Per text: path, word count, the title (issues) or the first sentence (comments), `{{slug}}` references, the M check's result in one line (`still on main: path:line` / `changed on main: …` / `do not file: …`), figures you left out because you could not trace them.
