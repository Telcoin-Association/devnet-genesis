# HD-2c — the model test of the own-chain hold: one author, random certification, cancels and commits

Unit: `HD-2c` (test unit, opus). Rules: `tasks/bench7-agent-rules.md` ("Node units" and "Test units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-2c.md`. Budget: under 150k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-hd2c`, branch `b7/hd2c`, base = `b7/hd2a`'s tip c5f60105f (upstream main 45dce8947 + the pure module `crates/consensus/primary/src/order_hold.rs`). Domains: `tn-domain-consensus`. Topic slug: `digest-order-hold`. `Refs #1807`.
Skill first: `tn-write-proptest` (after `tn-rust-skills` and `tn-domain-consensus`).

## Why

Issue #1807: a re-queued batch digest of a worker executes after a newer digest of the same worker, so a sender's later transactions run first and fail on their nonces.
The fix is a rule in the proposer (`OwnChainOrder`, already written and unit-tested: read `tasks/bench7/briefs/hd2-api.md` for its surface and wiring notes, `tasks/bench7/briefs/hd2.md` for the rule and invariants, the design `benchmark/private/bench7-prep/design/design-1807-own-chain-hold.md` §1, §3, §4 "Property test", §7, and the delta read `benchmark/private/bench7-prep/DR-1807/findings.md` verdicts 1, 3, 6 for how main's proposer, ordering and execution really behave).
The unit tests check the rule's arithmetic. Nobody has yet checked the RULE against the system it lives in: a model of one author's proposer under random certification, cancels and commits. That is this unit. If the model finds a schedule in which the rule still lets an older digest of a lane execute after a newer one (other than the documented GC-cut residual), that is a hole in the design: STOP and hand the minimal counterexample back; the plan sends a design change back to the user.

## What to build

A proptest suite (proptest is already a dev-dependency of the primary crate) in a NEW file, `crates/consensus/primary/src/tests/order_hold_model.rs`, declared from the end of `order_hold.rs` (`#[cfg(test)] #[path = "tests/order_hold_model.rs"] mod model;` or the form the crate's other test files use: look at how `proposer.rs` declares `proposer_tests`). You own that new file and that one line; nothing else. Do NOT touch `proposer.rs`, `metrics.rs`, `proposer_tests.rs`, `lib.rs`, `crates/config`.

The model (integers only; it drives the REAL `OwnChainOrder` through its two traits with integer types, and models everything else):
- **State of one author**: per-worker queues of digests with a per-(author, worker) sequence number; the tracked own headers (round → payload = the digests it drained, in drain order); which own headers are certified; the own-chain links (does header n carry the own certificate of n−1 as a parent); the committed set; the executed log (digest, worker, seq) in execution order.
- **Steps, chosen at random by the strategy** (weights are parameters; include degenerate mixes: no cancels, all cancels, own parent always missing, bursts):
  1. a worker reports a new digest (appended to the BACK of its queue with the next seq);
  2. the author proposes the next header at round n: own parent present or absent (absent models the own certificate missing the parent set: late, or the previous header was canceled); with the hold ON it calls `plan`, drains only lanes not held (up to the header's batch cap, as main's drain does: read `proposer.rs` on main for the cap and the drain order), `record`s; with the hold OFF it drains as main does;
  3. the newer header replaces an uncertified older one: the older is **canceled** → its digests go back to the FRONT of each worker's queue, oldest first (main's canceled path), and the header is forgotten;
  4. a **commit** of an own header at round c: main's ordering commits it together with its own-chain ancestors that are certified and above the GC cut, in round order, and an older own header that is NOT an ancestor of a committed one is committed only if it is itself picked later, before the newer one, or never (DR-1807 verdict 3: model exactly that: "ordered before the newer one or never"); every tracked own header at or below c that did not commit is re-queued by the **committed-kind** path: digests to the FRONT, oldest first; committed headers' digests are appended to the executed log in payload order;
  5. a max-delay **re-send** of the current header and a **restart re-propose** (`record_resent`), as the API note describes;
  6. the epoch ends: everything still queued or tracked is "pending at the end" (the orphan re-pool takes it; not an ordering violation).
- **Properties with the hold ON**, checked after every step and at the end:
  - P1: for each worker, the seq numbers in the executed log strictly increase (the #1807 invariant, per (author, worker) lane);
  - P2: no digest is executed twice;
  - P3: every digest ever reported is exactly one of executed, queued, tracked in a proposed header, or pending at the end (nothing is lost by the bookkeeping);
  - P4 (liveness, bounded): after any state, if the author then runs K rounds with its own parent present and every header certified and committed, every lane is drained again (no lane is held forever once the chain is intact); pick K from the model and state it;
  - P5: with the own chain intact from the start, the hold never holds anything (its cost is zero on a healthy chain): the ON and OFF models produce identical headers.
- **The sanity check that the model can see the defect**: with the hold OFF, the same strategy must FIND a P1 violation (a test that asserts the search finds one within a fixed number of cases with a fixed seed, and prints the shrunk schedule in the failure message of a deliberately inverted assertion or collects it with `TestRunner` and asserts `is_err()`); the shrunk counterexample should be the issue's own story (older header canceled or committed late after a newer header drained the lane). If the OFF model finds nothing, the model is too weak: fix the model, not the test.
- The GC-cut residual: model the GC depth as a parameter; with a depth so large it never cuts, P1 holds strictly; with a small depth, state exactly which schedules violate P1 (an own-chain ancestor more than the depth below the leader overtaken) and assert that EVERY P1 violation found is of that form (a classifier in the test), so a second kind of violation cannot hide behind the residual.
- Cases: the default run must finish in well under a minute in the package's nextest run (set the case count accordingly, e.g. 256); an `#[ignore]`d long hunt (e.g. 100,000 cases, a different seed per run via an environment variable, the seed printed) for the orchestrator's gate; `proptest.toml` at the repo root shows the repo's conventions: follow them, add no regression file to git unless a real counterexample is found (then commit it and STOP as above).

## Gates

`cargo check --locked --all-targets -p tn-primary`, fmt check, clippy for the package, `cargo nextest run --locked -p tn-primary` (whole package), the new tests by name twice, and ONE run of the long hunt with at least 20,000 cases (through the slot wrapper; the host is heavily loaded: let it take what it takes, do not lower the cases to make it fast), its seed and result reported.
One `tn-domain-reviewer` (opus) on your diff, domain consensus, asked one thing: is the MODEL faithful to main where it matters (the two re-queue paths to the front oldest first; the drain order and cap; "ordered before the newer one or never"; execution in payload order; what a commit takes with it), with `path:line` on main for each; a model that is kinder than main proves nothing.

## Hand back

As the rules say, plus: the model's steps and what each mirrors on main (`path:line`); the five properties as coded; the OFF model's shrunk counterexample, written out as a schedule; the long hunt's cases, seed and result; the reviewer's answer on fidelity; and, in the FIRST line, either "no schedule breaks the rule" or the counterexample.
