# U1b — the adaptive execution-block policy must hold its target when the tip certifies only part of the time (node unit)

Rules first: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (all but the harness and investigation sections).
Worktree: `/home/drtnarg/coding/telcoin/tn-b6-u0b` — a finished unit's directory (its e2e-profile build is warm); the directory name
is NOT your unit's — branch `b6/u-u1b` at the integration head given in your prompt. Checkpoint:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u1b.md` (rewrite it after each section).
Skills: `tn-rust-skills`, `tn-domain-consensus`. Topic slug: `quorum-exec-block`. Refs #1804.

## Why
Upstream issue #1804 (bench 5, run r20261107-1504): a validator whose execution is ahead of a quorum names its own newest
executed block in its headers; voters that have not executed that block refuse to vote, and the fast validator's headers are
cancelled uncertified. The fix (switch `quorum_exec_block`) makes the proposer name the block a quorum of its parents has
named. Applied to every header (`quorum_exec_block_starved_rounds: 0`, "always") the fleet settles 8 outputs behind its tips.
The ADAPTIVE form (`quorum_exec_block_starved_rounds: 4`) keeps the own tip by default and uses the quorum rule for a window
of rounds after an own header is cancelled, doubling the window up to 128 on repeated cancels. Its promise, written on
`QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`: a proposer that stays ahead loses about 2 of every 130 headers (the bench-6 target is
≥ 98 % of own headers certified).

The first e2e test of the fix (`crates/e2e-tests/tests/it/exec_block.rs::test_fast_executor_is_certified`, three runs) shows the
promise does not hold: fast node certified 0.53-0.71 with the switches off, **0.81-0.82 adaptive**, 0.99-1.00 always. The
cause, from the round-by-round log: in that regime the tip certifies PART of the time (outputs commit every second round, so
the fast header proposed right after a commit names a block the slow voters reach in time). A single certified tip header
resets the next window to the configured 4 (`ExecBlockPolicy::on_certified`), so the node returns to its tip every 4-16
rounds instead of every 128 and loses a header or two each time. Headers built under the quorum rule certified every time.

## Read
1. `crates/consensus/primary/src/proposer.rs`: `QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`, `ExecPolicy`, `ExecBlockPolicy`
   (`for_round`, `on_cancelled`, `on_certified`) and where the proposer calls them; the policy's unit tests and the
   self-feeding model test in `crates/consensus/primary/src/tests/proposer_tests.rs` (section `bench6 quorum-exec-block`).
2. `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`: "D1" (the two forms and why), "From U1" (D29: the
   reset rule as built and the reason a header certified INSIDE a window must not reset; D30), and the ST-A section (the
   numbers above). `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-a.md` for the calibration detail.
3. `crates/e2e-tests/tests/it/exec_block.rs` (the three arms and what each asserts).

## Analysis to start from (verify it; do not take it on trust)
Let p be the chance that a header naming the own tip certifies, and f the share of rounds the policy spends on the tip. A
tip header that fails is lost; a header under the quorum rule is not. So the share lost is about f × (1 − p): never worse than
with the switch off (f = 1), and ≤ 2 % needs f ≤ 0.02 ÷ (1 − p). While the regime lasts the policy therefore has to stay in
long windows; one certified tip header says almost nothing about p (at p = 0.6 it happens 60 % of the time). The windows
should shrink only on evidence that the tip certifies reliably — a RUN of consecutive certified tip headers — and a return to
the tip that keeps certifying already stays on the tip without any reset (a window only opens on a cancel), so a slow reset
costs nothing when the regime has really ended; it only makes the next isolated cancel open a longer window.

## Deliver
1. A model of the policy as a pure function of a sequence of tip outcomes (the state machine has no I/O): simulate the share
   lost and the share of rounds on the tip for p ∈ {0, 0.3, 0.5 alternating (success, failure, success, …: the e2e regime),
   0.6, 0.9, 0.99, 1} over a few thousand rounds, for the rule as built and for each candidate. Candidates at least:
   (a) reset to the configured window only after S consecutive certified tip headers (try S = 8, 16, 32); (b) halve the
   next window after every S consecutive certified tip headers; (c) anything better you find. Also model a regime that ENDS
   (p = 0.5 for 500 rounds, then 1): how many rounds until the policy is back on the tip, and what the next isolated cancel
   then costs. Put the table in the checkpoint. Keep the model as a unit test (seeded, no wall clock) that pins the chosen
   rule's numbers with margins.
2. The smallest change to `ExecBlockPolicy` that meets: share lost ≤ 2 % for every modelled p ≤ 0.9 with the configured
   window 4; lag 0 and no window when every tip header certifies; back on the tip within one maximum window after a regime
   ends; never worse than the switch off; no new switch, no new config field, no change with `quorum_exec_block` off or with
   the window at 0 ("always"); the header bytes with the switch off stay identical. State what the rule cannot do (the
   bound f ≤ 0.02 ÷ (1 − p) for p close to 1) in the constant's doc, which today promises more than the code delivers.
3. Unit tests for the new rule beside the existing ones (keep every existing test; one whose expectation the new rule
   changes is updated with the reason in the commit body), including: a single certified tip header after a doubled window
   does not reset it; the run needed does; a cancel inside the run restarts it; a header certified inside a window still
   does not count (D29's reason stands).
4. The e2e adaptive arm, three runs through the lane after rebuilding the node binary: report the fast node's certified
   share per run next to ST-A's 0.812 / 0.806 / 0.816, and raise the arm's assertion to what the three runs support with
   margin for a loaded machine (the target is 0.98; say plainly if the local fleet does not reach it and why). You may edit
   `exec_block.rs` for that arm's thresholds and its summary line only.
5. A domain review (domain: consensus): ask it to attack the new rule for a state that never returns to the tip, one that
   flaps every round, and any way a peer's behaviour (withholding votes for tip headers only) could pin an honest node in
   long windows — and what that costs the node (staleness of its named block, not safety: say why).

## You own
`crates/consensus/primary/src/proposer.rs` (the policy types and their call sites only), the `bench6 quorum-exec-block` section
of `crates/consensus/primary/src/tests/proposer_tests.rs`, and the adaptive arm's thresholds in
`crates/e2e-tests/tests/it/exec_block.rs`. Nothing else. Another reviewer is reading `proposer.rs` on the integration branch
for a different topic: you work only in your worktree.

## How to run
Unit level: the rules' node environment; `cargo nextest run --locked -p tn-primary -p tn-node -E 'package(tn-primary)'`, clippy and
fmt for the package, through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh`. E2e: environment
`TN_SEED_SIGNATURE_FORK_EPOCH=4294967295 TN_MULTI_WORKERS_FORK_EPOCH=4294967295 TN_PREVRANDAO_FORK_EPOCH=4294967295 TN_LEADER_SEEDED_ORDERING_FORK_EPOCH=0 TN_SUBSECOND_TIMESTAMP_FORK_EPOCH=0 TN_GOVERNANCE_SAFE_FORK_EPOCH=4294967295`,
rebuild the binary with `cargo build --locked --profile e2e --bin telcoin-network --features tn-storage/test-utils --target-dir "$PWD/target"`
(slot wrapper), `export TN_BIN_PATH="$PWD/target/e2e/telcoin-network"`, and run ONLY through the lane:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh cargo nextest run --locked -p e2e-tests --test it --run-ignored all -E 'test(=exec_block::test_fast_executor_is_certified)'`
(about 5 minutes per run; other test units share the lane).

## Commits
`fix(primary): …` for the rule (body: the regime, the numbers before and after from the model), `test(e2e): …` for the
thresholds; footers `Refs #1804` and `Topic: quorum-exec-block`. No attribution lines.

## Hand-back
The model table (rule as built vs chosen rule), the rule in three lines, the e2e shares for three runs, the tests, the
gates, the review's verdict, what the adaptive form still cannot do, and your recommendation between "always" and the
adaptive form for the benchmark's vote-fix arm, with the cost of each.
