# I-6c — bench-5 page, third correction (the trigger sentence), re-bundle, site gates

You are unit **I-6c** of the bench-6 program.
Read `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` first (sections: "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Investigations", "HAND BACK").
Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-I-6c.md` (on start, read your own checkpoint and continue from the first unfinished section; rewrite it after EACH section with a `status:` header and the list of completed sections).
Output directory: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-6c/`.
Scratch: `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/I-6c/`; logs and anything large under `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/work/bench6-scratch/I-6c/`.
Load the `human-writing` skill before you edit prose.
Budget: under 150k tokens. Final answer: at most 35 lines.

You are the ONLY writer of these two files and you write nothing else in the repo:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench5-report-r20261107-1504.md` and
`/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/report/backfill/2026-11-07-main-fixes.json`.
You do not commit and you do not push, in any repo. The orchestrator reads your diff, commits and publishes.

## Why
The published page of run r20261107-1504 (bench 5) is built from the backfill JSON.
Two earlier passes (I-6, I-6b) corrected it; their result sits uncommitted in `/home/drtnarg/coding/telcoin/tn-benchmarks` (`runs/r20261107-1504/{report.html,run.json}`).
One statement in it is now known to be wrong, and the user has authorised this one fix and the publication.
The statement: the "likely trigger" of the extra device bytes is that each node's database was created during staging and reopened for the run (about 60 %).
Two cloud probes and a local probe contradict it: a re-open alone does not produce the extra bytes.

## Sections (checkpoint after each)

### 1. Verify the numbers, then write the replacement text
Sources (read these, nothing further):
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`: the two sections whose headings start "THE GCE PROBE ON THE FLEET'S SHAPE" and "THE TWO-DEVICE PROBE" (`grep -n PROBE`, read those ranges only), and the local probe section if the first one cites it.
- `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/probe/SUMMARY-r20261111-2310.txt` and `SUMMARY-r20261112-0024.txt`.
- `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-1r/verdict.md` (the local probe: the re-open arm at 1.000×).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-brief.md` §6 items 5 and 12.

What the new text must say (check every figure in the files above before you use it; if a figure does not check, use the one the file gives and say so in the hand-back):
- The trigger is not identified.
- Reopening a database that was created during staging was the first suspect. Tested alone it did not reproduce the extra bytes: 1.00× on the test machine and on a cloud VM of the validators' machine type and disk.
- In those tests the extra bytes appeared only in three cases: when the file's pages had been read into the page cache before they were changed (11.9×, in writes of about 256 KiB; this run's writes were 222 to 228 KB — decimal; the first version of this brief said KiB, corrected 2026-11-12), when the database library's pre-write of new pages was off (9.7×), or when another process had opened the database (1.8×).
- What did one of these on the run's nodes is not known.

Voice: the page is written for a reader who does not know the code. Follow the surrounding sentences: "the database library", "large multi-page blocks", "random-access hint", no function names, no internal unit names (no "I-1", "probe arm g5"), no "folio", no "MADV_RANDOM", no "libmdbx". Short declarative sentences, no em dashes, the page's own number style ("4.3 times", "about").
Write the old and new passages side by side into `…/I-6c/corrections-3.md` with the source file and line of each figure.

### 2. Edit the backfill JSON (schema unchanged: same keys, 16 methodology, 20 caveats; valid JSON)
- `summary`: replace the one sentence that starts "The likely trigger, found later, is how the nodes were started: …" with one or two sentences in the summary's voice (not identified; reopening alone did not reproduce it in later tests). Keep it short: the detail belongs in the caveat.
- `caveats[2]`: replace the passage from "The likely trigger, found later from the code and the run records (about 60 % …" through "… How the large blocks then form there is not yet separated." with the new text of section 1. Leave every other sentence of the caveat as it is, including the memory-pressure sentences that follow.
- `_comment`: append one sentence dated 2026-11-12 naming this change, in the style of the two "Corrected …" sentences already there.
- Change nothing else in the file. If you find another sentence in `summary` or `caveats` that the probes contradict, do NOT change it: list it in the hand-back with the evidence.
- Keep a pre-edit copy in your scratch directory and show `diff` of the pretty-printed before and after in `corrections-3.md`.

### 3. Edit the report (`tasks/bench5-report-r20261107-1504.md`)
The same statement appears there (`grep -n -i 'likely trigger\|about 60 %\|re-opened\|ranked first'`; about lines 31, 494-520 and the corrections lists at the end).
Minimal edits in the report's own style and wrapping; do not undo the earlier passes; do not rewrite sections.
Where the report states the re-open trigger as likely (about 60 %), say it was tested and did not reproduce (with the figures of section 1) and that the trigger is open.
Append a new dated list "## Corrections (2026-11-12)" at the end (read `date -u`), one entry per changed statement: old → new, why, source.

### 4. Re-bundle
Exactly as the second pass did. Its record: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-I-6.md` (the commands), `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-I-6b.md` and `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-6b/corrections-2.md` line 75.
In short: a `git worktree` of devnet-genesis pinned (detached) at **149f941**, with ONLY the backfill JSON replaced by your edited copy and `benchmark/results` symlinked to the main checkout's (read-only use); tools from a `git archive` of `/home/drtnarg/coding/telcoin/tn-transaction-generator` at `6dad96f`; then
`make_bundle.py --run r20261107-1504 --compare r20261105-0803 --floor-blast-dir blast-0-20261107T163112Z --backfill benchmark/report/backfill/2026-11-07-main-fixes.json --txgen-bench <archive>/bench --analysis-sha 6dad96f`
(add `--force` if its scratch directory from an earlier pass still exists). It took 719 s last time; run it in the background with a log that ends in `EXIT=<rc>` and wait for it.
The harness has changed since 149f941 and the page's numbers must not: that is why the worktree is pinned.
- BEFORE the bundle: copy the present (uncommitted) `runs/r20261107-1504/run.json` and `report.html` from `/home/drtnarg/coding/telcoin/tn-benchmarks` into your output directory as `before-run.json` and `before-report.html`.
- BEFORE the bundle: wait while `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/QUIET` exists (poll every 60 s; give up after 90 minutes and hand back with this section pending).
- `touch` a marker first and verify afterwards that nothing under the main checkout's `benchmark/results/` is newer than it.
- Remove the pinned worktree with `git worktree remove` (no `--force`) when done.

### 5. Gates and the proof that only the text changed
In `/home/drtnarg/coding/telcoin/tn-benchmarks` (each with a log ending in `EXIT=`): `build.py --check`, `build.py --check runs/r20261107-1504`, `scrub.py`, `scrub.py runs/r20261107-1504`, `python3 -m unittest discover -s tests`.
Then compare the new `run.json` with `before-run.json` as parsed JSON: the ONLY differences allowed are the `summary` string and `caveats[2]` (and a build timestamp if the file carries one). Print every differing key path. Compare `report.html` the same way (timestamp only, unless the summary is rendered into it).
If any number or any other key differs, do not try to repair it: stop, restore nothing, and hand back with the list.
Report `git -C /home/drtnarg/coding/telcoin/tn-benchmarks status --short` and `diff --stat`. `.claude/` there is untracked and stays out of everything.

## Hand back
Status and checkpoint path; the old and new text of the two backfill passages verbatim; the figures you could not verify; the differing key paths from section 5; every gate with its `EXIT=`; the tn-benchmarks status; other sentences you believe the probes contradict (not changed).
