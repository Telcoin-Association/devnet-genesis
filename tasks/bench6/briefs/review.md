# Topic review — code review and security evaluation of ONE bench-6 topic (review unit)

You review one topic of the bench-6 node branch of telcoin-network (Narwhal/Bullshark consensus with a reth execution layer)
before it goes into a benchmark image for a ten-validator fleet and, if the benchmark confirms it, upstream as a pull request.
Your prompt names a scope file under `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/`: read it first. It lists
the topic's commits, files, switch, upstream issue, where the topic's claims and known residuals are written down, the
questions specific to it, your report path and your checkpoint path.

## The change under review
- Code: `/home/drtnarg/coding/telcoin/telcoin-network-b6`, branch `bench/bench6-2026-11`. READ-ONLY for you: no edits, no
  commits, no branch or stash operations, no `cargo` of any kind (the machine's build slots belong to test units that are
  running now; reason from the code and the existing tests). `git show`, `git log`, `git diff`, grep and file reads are fine.
- The "pull request" is exactly the scope file's commits, in order: `git show --format= <commit> …` is its diff, the branch
  head is its final state. The commits are interleaved with other topics' commits on the branch, so there is no base branch
  to diff against: wherever a skill or sub-agent would compute `main...HEAD`, give it the commit list instead. Other topics'
  code is out of scope except where this topic's code calls it or is called by it.
- Every bench-6 fix sits behind a switch in the node's `parameters.yaml` whose default keeps the previous behaviour.

## What to do
1. Run the repository's code review (the `tn-review` skill) and its security evaluation (the `tn-security-eval` skill) on that
   diff, and have the findings verified independently (the skills' own verification step) so that what you report has been
   checked against the code, not only suspected.
2. Beyond what the skills ask, answer these for the topic, each with file:line evidence:
   a. **Switch off = before.** With the switch at its default, is every code path byte-for-byte the previous behaviour? Name
      any line that runs with the switch off and did not run before (metrics registration and log fields are acceptable if
      they cannot change behaviour; say which you saw).
   b. **Mixed fleet.** The benchmark flips switches by rolling restart, so for minutes some validators have the switch on and
      others off. Can that fork the chain, make honest validators reject each other's headers, votes, certificates or
      batches, or stall the fleet? State which messages or state the switch can change that another validator checks.
   c. **Liveness under the switch.** Can the new code drop, delay without bound, or never retry something that used to make
      progress (a transaction, a batch digest, a header, a vote, an epoch close)? Give the sequence if so.
   d. **Byzantine or merely slow peers.** What can one faulty or slow validator (or client, where relevant) now cause that it
      could not before? Bound the cost.
   e. **Restart and epoch boundary.** State held in memory by the new code: what happens to it across a restart and across
      an epoch change?
   f. **Determinism.** Anything the new code feeds into consensus-visible data that depends on iteration order, wall-clock
      time or thread timing.
   g. The scope file's own questions.
3. Do not re-report a residual that the scope file's notes already list as known and accepted, unless you can show it is
   worse than stated — then say exactly how.

## Economy
The diff is small (the scope file gives its size). Tell every sub-agent which files and commits it may read and that it
returns findings, not file dumps. Do not let a sub-agent wander the repository; a sub-agent whose question does not apply to
this diff (for example contract safety for a Rust-only change, or dependency audit when no `Cargo.toml` changed) is told so
and returns at once, or is not started.

## Rules
No attribution to any AI tool or vendor in anything you write. Nothing is pushed, posted or sent anywhere. Write only your
report file and your checkpoint file (rewrite the checkpoint after each phase: scope read, review done, security evaluation
done, verification done, report written; on start, read it and continue from the first unfinished phase).

## Report (the file named in the scope) and hand-back
Report: verdict (APPROVE / APPROVE WITH FOLLOW-UPS / CHANGES REQUIRED), then findings ranked most severe first, each with
severity (Critical/High/Medium/Low/Info), CONFIRMED or PLAUSIBLE, file:line, the failure scenario as a concrete sequence, the
suggested fix, and whether it must be fixed before the benchmark image (it can hurt a ten-node devnet run) or before the
upstream PR (it matters for mainnet); then the answers to 2a-2g; then what you did not examine.
Hand-back (at most 40 lines): the verdict, every High or Critical finding in two lines each, the Medium findings in one line
each, counts of the rest, the answers to 2a and 2b in one line each, and the report path.
