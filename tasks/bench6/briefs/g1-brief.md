# G1-BRIEF — condense the gate notes into the decision list the user answers (analysis unit; writes one file)

You write `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-brief.md` and nothing else. No code, no git, no cloud.
Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-g1-brief.md` (a `status:` line and the list of
finished sections, rewritten after each section; on start read it and continue).

## What this is for
Bench 6 is a program that builds twelve switchable fixes into the telcoin-network node, measures them on a ten-validator
GCE fleet in two runs (run 1: arms, one switch group at a time; run 2: the headline), publishes the result and upstreams
what the run confirms. The orchestrator stops at four gates and asks the user. **G1** is the first: it comes after the
investigations, the node and harness units, the reviews and the one-VM GCE probe, and before the image is built. Everything
the orchestrator learned on the way is in one long notes file, in the order it was learned, with decisions numbered D1…D84.
The user will not read 1,000 lines. They need one page per topic at most: what was found, what must be decided, what the
orchestrator recommends and why, and what happens by default if they say nothing.

## Read
1. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md` — all of it (it is the source of truth; later
   sections supersede earlier ones where they say so: follow those supersessions, e.g. D38 → the parent-grace review
   section, D61 → the U1b section, D9 → the U12b section).
2. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/plan.md` — the gates' definitions (G1's own line lists what it must
   cover) and the run-1 and run-2 lines.
3. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-upstream-followups.md` — what is deferred to the upstream PRs (so
   that you do NOT list those as gate decisions).
4. `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/launch/bench6-run1.plan` and `benchmark/arms/README.md` (the arms as
   they stand), and the last 60 lines of `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-orch.md` (the
   image-cut checklist and what is still running).
Read nothing else; if something you need is not in these files, write "not in the notes" rather than guessing.

## Write (`tasks/bench6-g1-brief.md`)
1. **State in ten lines**: what is built and integrated, what is held (pipelined persist and its go/no-go gates, with the
   status of each), what has been verified and how (reviews, e2e, workspace gates), what is still running or owed before
   the image (name each).
2. **Decisions the user must make at G1** — only those the notes mark as the user's, or where the orchestrator's choice
   changes what the fleet runs or costs. For each: a short title, the D-number(s), the finding in two or three sentences
   with its numbers, the options, the orchestrator's recommendation exactly as the notes record it (if the notes record
   none, write "no recommendation recorded"), and the default if unanswered. Group them:
   A. what the fleet runs (the arms of run 1, the vote-fix form, the parent grace values, the admission bound, the disk
      comparison and the provisioned-IOPS question, pipelined persist in or out);
   B. the persist root cause (what the probe settled, what run 1 must show, the options that are not switchable);
   C. the image and the boot image pin;
   D. bench 5's corrected report and its republication; pruning local results;
   E. anything else the notes mark for the gate.
3. **Decided by the orchestrator, reversible** — one line each with its D-number: what was chosen and what it would take to
   undo. (For example D62, D72, D78.)
4. **Information, no decision** — one line each for the findings a reader of the report will ask about (what was
   reproduced locally, what the reviews approved, known residuals accepted for the benchmark).
5. **A table of every D-number** (D1…D84, and any you find beyond): one line each — title in five words, class (user /
   orchestrator / info / superseded by Dn / deferred upstream), where it appears in the notes (section name). A number you
   cannot find is listed as "not found".

## Rules
- Do not change a recommendation, add one, or soften a finding. Numbers are copied from the notes, with their units.
- Where two sections disagree and the later does not say it supersedes, show both and flag it.
- Plain prose, short lines, tables where they help; at most about 220 lines for sections 1-4 (the table in 5 is extra).
- No attribution to any AI tool or vendor.

## Hand-back
The path, the count of user decisions, any contradiction you flagged, any D-number you could not classify.
