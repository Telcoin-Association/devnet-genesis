# U9b — parent grace: review fixes (node unit)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u9` — a finished unit's directory (warm build of the primary); the directory name is
NOT your unit's — branch `b6/u-u9b` at the integration head given in your prompt. Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u9b.md` (rewrite it after each section).
Skills: `tn-rust-skills`, `tn-domain-consensus`. Topic slug: `parent-grace`. Refs #1803.

## Why
Upstream issue #1803 (bench 5, run r20261107-1504): the two far validators' certificates arrive after the near validators have
a quorum of parents and have already proposed, so far certificates are left out of headers, the far validators drift behind
and jump rounds. The fix (switch `parent_grace`, a duration; default `0s` = off; the benchmark uses `150ms` and `100ms`): a
proposer that is ready waits a bounded grace for the certificates of authors its LAST own header carried.

A code review plus security evaluation of the topic (verified findings; report
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/parent-grace-report.md`) returned CHANGES REQUIRED. No safety
problem: a mixed fleet cannot fork and no validator rejects another's header. But the grace does not do its job for long:

- **M1 (must fix).** The grace waits only for authors whose certificate the last own header carried. A far validator whose
  certificate misses ONE header (one expiry, a skipped round, a restart, an epoch start) is no longer in the basis; its late
  certificate takes the proposer's `Ordering::Less` arm, which only counts it; and from then on the node is ready before that
  author's certificate arrives in every round, so it never waits for it again. Each near node drops the far validator on its
  own first excursion, and the drift of bench 5 returns.
- **M2 (fix with it).** A round jump during a grace ends the grace as `preempted` and the held header for that round is never
  built. If this node LEADS that round, no leader certificate exists for it: every proposer waits out `max_header_delay` and
  that leader is never committed. Decision taken by the orchestrator (recorded for the user's gate as reversible): do not arm
  a grace when this node leads the next round — the proposer already gives a leader a zero minimum delay for the same reason,
  and the far certificates still ride the non-leaders' headers.

## Read
1. The report, sections M1, M2, M3, L1-L5 and the answers 2c-2e and 2g (they cite every line; the report's line numbers are of
   the integration head).
2. `crates/consensus/primary/src/proposer.rs`: the grace types and functions (`GraceInFlight`, the basis, `on_proposed`,
   `missing`, `hold`, `end_if_round_moved`), the three `Ordering` arms where parents arrive, `calc_min_delay`,
   `update_leader`, `calc_max_delay`; the section `bench6 parent-grace` of
   `crates/consensus/primary/src/tests/proposer_tests.rs`.
3. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`, row `parent-grace` (the log and metric names: frozen
   unless you add a field), and `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, section "From U9" (D37, D38).
4. The issue body `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/bench5-far-validator-certificate-inclusion.md`
   (option A: "wait for authors live in round r−1, meaning it holds their round-(r−1) certificate").

## Deliver
1. **M1 — re-entry.** A certificate of the previous round that arrives after this node's header for the current round went out
   puts its author (back) in the basis for the next grace, including while a header is pending (the report's suggested shape:
   in the `Less` arm when `round + 1 == self.round`; stash while a proposal is in flight and merge in `on_proposed`). Decide
   from the code whether the basis should be "authors of certificates held for round r−1" outright (the issue's wording)
   rather than "authors the last header carried, plus late arrivals": say which you built and why. Bound the basis by the
   committee. Tests: the re-entry sequence (round r expires without F; F's late certificate arrives; the next header waits for
   F and carries it); several rounds in a row with a far author that is always later than quorum but inside G (it stays in);
   an author that stops sending (crashed) costs one grace and is then dropped; the node's own certificate does not make the
   node wait for itself.
2. **M2 — no grace for the next round's leader.** When this node leads the round it is about to propose in (the condition the
   proposer already uses for its zero minimum delay), no grace is armed. Tests: the leader proposes at once with the switch
   on; a non-leader in the same state arms; the round-jump sequence of the report no longer loses the leader's header.
   Document on the switch and in the module docs that leaders do not wait, and why.
3. **L1** (readiness can drop while a grace is armed, so a hold can exceed G): fix if it is a few lines, else document the
   bound (`max_header_delay`). **L2** (`parent_grace` above `max_header_delay` is capped silently): log one warn at start
   that names both values; do not reject the file. **L4**: the debug lines `parent grace armed` and `parent grace ended` gain
   the authors waited for (short ids, bounded by the committee size) so that an analysis can name the late author; add the
   field at the END of each line and report its exact name.
4. **Docs, no code.** The switch's and the module's docs must say what the grace costs under load (M3: with the header ready
   on the quorum message the grace arms on almost every round and costs up to G per round — the issue's "about 0 under load"
   is wrong) and what one author can do (L3: an author that lands just inside G costs about G every round with outcome
   `complete`).
5. Switch off (`0s`): no behaviour change — the header bytes and timing decisions are those of the current head; say how you
   checked.
6. Domain review (domain: consensus): ask it to attack re-entry for a way a faulty author can pin every honest proposer at
   +G per round forever (it can: state the bound and whether a cap on consecutive graces for one author is warranted — do
   not build one without evidence), and for any way the new basis makes a node wait for an author that has left the
   committee or the epoch.

## You own
`crates/consensus/primary/src/proposer.rs` (the parent-grace code and the arms where parents arrive), `crates/config/src/node.rs`
(the `parent_grace` doc only), the `bench6 parent-grace` section of `crates/consensus/primary/src/tests/proposer_tests.rs`.
ANOTHER unit is changing `ExecBlockPolicy` (the `quorum_exec_block` types near the end of `proposer.rs`) and the
`bench6 quorum-exec-block` test section on another branch right now: do not touch, move or reformat those regions, and add
your tests INSIDE your own section, not at the end of the file, so the two branches merge cleanly.

## Gates
The rules' node environment; through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh`:
`cargo check --locked --all-targets -p tn-primary -p tn-config -p tn-types -p tn-node`, fmt, clippy for those packages,
`cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-config -p tn-types -p tn-node -E 'package(tn-primary) | package(tn-config)'`,
each new test with timing in it three times by name. Commits: `fix(primary): …` per finding (M1, M2 separately), footers
`Refs #1803` and `Topic: parent-grace`. No attribution lines. You do not run e2e tests.

## Hand-back
Per finding: the rule as built in two lines, the tests, what changed in log lines or metrics (verbatim), the review's verdict;
the cost bounds as now documented; what you did not fix and why; and what the benchmark's grace arm must read to judge cost
and benefit (metric and field names).
