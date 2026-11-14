# Plan: close out bench 6 (publish, summary, upstream), then bench 7 (both vote forms at 20,000 IOPS on the latest main, #1807 addressed)

Written 2026-11-14 (xerxes). The approved plan text is `/home/drtnarg/.claude/plans/here-is-a-summary-lively-dolphin.md` (the orchestrator's brief; this file is its tick list).
Previous tick list archived at `tasks/archive/plan-bench6-2026-11-10.md`.
Agent rules: `tasks/bench7-agent-rules.md`. Briefs: `tasks/bench7/briefs/`. Unit list: `tasks/bench7-task-list.md`. Orchestrator log: `tasks/checkpoint-bench7-orch.md` (newest at the bottom).
Design reports (made on the bench-6 tree): `benchmark/private/bench7-prep/design/`; the delta reads on M: `benchmark/private/bench7-prep/DR-1807/`, `…/DR-E/`.

Standing rules: no Claude/Anthropic attribution anywhere; opus agents implement and analyse, sonnet for inventories, no fable subagents; subagents never push, never `gh … create/edit/comment`, never touch GCP, never build an image; one writer per file; `tn-node-deployment/` and `common/` are not edited; `--project tn-devnet` on every ad-hoc gcloud read; one e2e job per machine at a time through `tasks/bench6/e2e-lane2.sh` (lane 1 holds another session's parked queue, pids 84216 and 4066496: not ours to stop); cargo through `tasks/bench6/cargo-slot.sh`; a deploy is launched only when the session can also launch its blast.

User decisions (2026-11-14): publish the four runs first and write a maintainers' summary; one staging branch off `main`; PRs now for what bench 6 confirmed, the #1807 PR and the vote-form PR after bench 7; #1807 = an own-chain hold in the proposer (`digest_order_hold`); the `final_state` check and the collector hardening built, tested and ON in both bench 7 runs; bench 7 = always-on and adaptive at 20,000 IOPS, run 2's shape, floor 8.
Authorized by the plan's approval: pushing devnet-genesis `main`; committing and pushing tn-benchmarks; pushing the staging branch, topic heads and `bench/bench7-2026-11`; creating the listed issues, comments and PRs 00-04; building and pushing the bench 7 image.
Added by the user 2026-11-14 ≈ 17:50Z (verbatim: "if verified, file the epoch loop forward bug as an upstream issue and put the fix into bench 7"): the High bug the closing-block check's security evaluation found in main itself (a cancelled send in the epoch loop drops a consensus output; the leftover drain forwards the next one) is verified by unit XF-1 with a reproducing test; if REAL: an upstream issue (writer + figure-check, then posted) and the fix as its own head `fix/epoch-loop-output-drop` in the bench 7 image. Its PR is not on the list of PRs authorized now: ask when the PRs are created.
NOT authorized, asked when reached: any fleet launch; publishing bench 7; PRs 05 and 06; deleting anything old; a change of design if the hold or a hardening unit fails its tests or reviews.

## Facts at the start (2026-11-14T15:04Z)
- **M = 45dce89474e1efc7f90c6fbd1e51332cc237ab9b** (`origin/main`, fetched 15:05Z; 23 commits past the merge-base 9aa1d6139 with the bench-6 tree). `staging/benchmark-bench6-2026-11` created at M and pushed 15:1xZ.
- Integration worktree `/home/drtnarg/coding/telcoin/telcoin-network-b7` on `bench/bench7-2026-11` at M (not pushed yet).
- No bench instance in the cloud, no driver, no cargo job at the start; 415 GB free; devnet-genesis `main` 184 commits ahead of origin; tn-benchmarks clean at fc078de.
- The five planning reports of the plan session were saved from its transcript to `benchmark/private/bench7-prep/design/`.

## W0 — preflight (orchestrator)
- [x] old tick list archived; this one, `tasks/bench7-agent-rules.md`, `tasks/checkpoint-bench7-orch.md`, `tasks/bench7/mk-worktree.sh`
- [x] fetch, pin M, staging branch pushed, integration worktree
- [x] memory pointer updated
- [x] project-context (sonnet) for telcoin-network at M → `telcoin-network-b7/.claude/project-context.md` (54.7 KB)
- [x] task-decomposer over the unit list → `tasks/bench7-task-list.md` (with the orchestrator's rulings)
- [x] DR-1807 (delta read: the hold's design on M) → `benchmark/private/bench7-prep/DR-1807/findings.md`: the rule stands; 12 changes to the design
- [x] DR-E (delta read: the epoch-record designs on M) → `benchmark/private/bench7-prep/DR-E/findings.md`: M already halts on a stored mismatch, so E1 has no switch

## Track P — publish the four runs and the summary
- [x] P1 four backfill files (opus writer) · figure-check (opus): 5 errors and 14 weak or untraceable items fixed; then "from the coordinated start"
- [x] P2 (17:06:41Z, after the provenance reader fix 02275df: staging starts before the arm's begin) commit the backfills; bundles in order: `r20261113-1351` (--compare r20261107-1504), `r20261113-1630` (--compare r20261113-1351), `r20261113-2118` (--compare r20261113-1351), `r20261114-0000` (--compare r20261113-1630)
- [x] P3 (115 tests, check ok, scrub 0/0 ×4, 61 files) site gates: unittest, `build.py --check`, `scrub.py runs/<id>` ×4, `build.py --out dist`, the four pages and landing cards read
- [x] P4 push devnet-genesis `main` (9fae083); commit and push tn-benchmarks (fc62df1); the four pages live (HTTP 200, 17:10Z)
- [x] P5 `tasks/bench6-maintainer-summary.md` (opus writer) · figure-check · printed in the chat

## Track N — node work on the staging stack (base M)
Stack: 00 `feat/bench6-switches-obs` · 01 `test/bench6-e2e-scaffold` · 02 `fix/1804-vote-queue` · 03 `fix/epoch-record-closing-block-check` · 04 `fix/epoch-record-collector-hardening` · 05 `fix/1804-quorum-exec-block` · 06 `fix/1807-digest-order-hold`; `bench/bench7-2026-11` = the top.
- [x] PT-0 switches + obs: b7/pt0 d8273bbe3 (9 commits) = head 00
- [x] PT-1 e2e scaffold (`NodeOverrides`, `FleetOverrides`, `TN_E2E_PARAMETERS`): b7/pt1 653e6ab51 (5 commits); head 01 = eca202a19
- [ ] PT-2 voter-lock: phase A verdict on M = **PORT** (done) · phase B the port (running, tn-b7-pt2b)
- [ ] PT-3 quorum-exec-block (both forms) + ST-A's tests + follow-ups: D75 clamp to the epoch's opening block, the starved-rounds validation, a superseded-refusal counter
- [ ] `epoch_close_forms.rs` (branch `b6/st-epoch-close-forms`) ported and extended (with E5)
- [ ] XF-1 main's epoch-loop output drop: verify + reproduce (running) · fix (cancel-safe forward; continuity check) · issue · head `fix/epoch-loop-output-drop` in the image (user, 2026-11-14)
- [ ] HD-1 #1807 observability (no switch) · HD-2 the hold (`digest_order_hold`, `order_hold.rs`, unit tests, property test) · HD-3 orphan re-pool counters (after E1) · HD-4 e2e (`TN_TEST_OWN_CERT_DELAY_MS`, four validators, both forms, a kill arm, the switch-off control)
- [ ] E1 `final_state` check (DONE, b7/e1 d3028fad7, no switch) · E2 observability (DONE, b7/e2 304858e08) · E3 collector walk + conflict halt (running) · E4 re-certify (running) · E5 e2e (`TN_TEST_WITHHOLD_EPOCH_VOTE`, `test_uncertified_epoch_walked_past`, the four `epoch_close_forms` tests extended)
- [ ] file order kept: E1 → HD-3 on `close_epoch.rs`; E2 → E3 on `state-sync/src/epoch.rs`; E2 → E4 on `epoch_votes.rs`; PT-0 → PT-3 → HD-1 → HD-2 on `proposer.rs`
- [ ] per-topic reviews: `tn-review-agent` each; `tn-security-eval` for the hold, E1, E3, E4, the ported quorum-exec-block; no open Critical or High
- [ ] top-head gates: per-commit strict check, fmt, `./etc/ci-lanes.sh clippy`, `cargo nextest run --workspace`, the repo's e2e sets (restarts, epochs, sigkill) all-off and bench-7-set-on, a mixed-switch fleet, each new e2e test ×3 through the lane, the property test's long hunt
- [ ] image: `orch-image-cut.sh <worktree> <commit> bench7-<date>` (faucet, tn-lmdb), digest recorded, `--probe-node-image` by digest, local image trial with the harness's start line

## Track U — issues and PRs (texts by opus agents; created by the orchestrator, dry run first)
- [ ] PR texts 00-04 (`tasks/pr-bodies/bench6-NN-*.md`) · PRs created (assignee grantkee, reviewers MavenRain, sstanfield)
- [x] new issues created 2026-11-14 (#1850 collector gaps, #1851 closing-block check, #1852 false quorum error, #1853 execute and persist in series, #1854 admission and the backlog, #1856 restart gap, #1857 rejoin under load, #1858 NewEpoch docs) (`tasks/issue-bodies/bench6-*.md`): closing-block check gap; collector gaps G1, G2; rejoin under sustained load + the follower's dead RPC; the false quorum error; stop between epoch 0's closing block and record 0; `NewEpoch` unreadable over RPC; in-flight bound measurements; execute and persist in series at 50,000 IOPS
- [x] comments with bench-6 data posted 2026-11-14: #1802, #1803, #1804, #1805, #1806, #1807, #1774
- [x] write-up of what does not carry (MDBX advice, the old stored-record check, pipelined persist): `tasks/bench6-not-carried-writeup.md` (goes into the PR stack's text)

## Track H — harness for bench 7 (starts when the four bundles are launched: a bundle refuses a dirty `benchmark/`)
- [ ] HB-1 faucet build of M starts (`TN_ALLOW_FAUCET_ON_CHAIN`, BLS passphrase source, `node build:` line, image contract, no MDBX flags, engine in the manifest)
- [ ] HB-2 switch list, `benchmark/arms/bench7-always.arm`, `bench7-adaptive.arm`, provenance
- [ ] HB-3 storage measures on tn-lmdb (sampler, folio census, readers)
- [ ] HB-4 run-costing defects: listener ports, the chained launcher, the fleet-health watch, the metric export check
- [ ] HB-5 `benchmark/launch/bench7.env`, README, the #1807 and hold readers
- [ ] full harness gate alone on the host; `params-apply.sh --print-state` ×2; the deploy's dry plan; the teardown's dry mode (0 candidates)

## Bench 7 — the two runs (orchestrator only; the user's go + a fresh `gcloud auth login` first)
- [ ] run 7a (always-on, starved rounds 0): deploy12 → idle checks → blast15 → prelim read + metric export → teardown-dry → teardown → reindex → archive
- [ ] run 7b (adaptive, starved rounds 4): the same, the same day
- [ ] analysis per run, the 7a-7b comparison, the comparison with runs 2 and 3, `tasks/bench7-report-<run>.md` (two writers + a figure-check)
- [ ] **form gate**: the result and a recommendation to the user → PR 05 with the chosen default, PR 06, the bench 7 pages, the last issue comments

## Wrap-up
- [ ] ledger verdicts, `tasks/todo.md` review section, lessons, memory, the launch README, push devnet-genesis
