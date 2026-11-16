# Plan: bench 7 follow-up — fixes become the behaviour, the stack goes to main, bench 8 finds the certification cause

Written 2026-11-16 (xerxes). The approved plan text is `/home/drtnarg/.claude/plans/glistening-dancing-boole.md` (the orchestrator's brief; this file is its tick list).
Previous tick list archived at `tasks/archive/plan-bench7-2026-11-14.md`.
Agent rules: `tasks/bench8-agent-rules.md` (on top of `tasks/bench7-agent-rules.md`). Briefs: `tasks/bench8/briefs/` and `tasks/bench7/briefs/`. Orchestrator log: `tasks/checkpoint-bench8-orch.md` (newest at the bottom).

Standing rules: no attribution anywhere; opus agents implement and analyse, sonnet for inventories, no fable agents; each agent at most 35 tool calls and about 120 printed lines per call, with a checkpoint file; the orchestrator alone pushes, runs `gh` writes, builds images and drives the fleet; no rebase, force, stash or reset; `tn-node-deployment/` and `common/` never edited; telcoin-network pushes over `git@github.com:Telcoin-Association/telcoin-network.git`.

User decisions (review of #1862-#1869, 2026-11-16): the six runtime switches go; always-on is the only upstream form of the #1804 fix; the removal is a ninth PR on top of #1869; the stack collapses into #1862, `main` is merged in, `make attest` runs on the result; both defect reports are posted; everything local of the program is pushed.

Approval covers: the records; committing and pushing devnet-genesis `main`; editing the eight PR bodies (twice); posting the two defect reports; pushing `refactor/remove-bench-switches` and opening the ninth PR; pushing `bench/bench8-2026-11`; building and pushing the bench 8 image.
Asked when reached: every fleet launch; publishing bench 8; the merge of `main` into #1862's branch after the collapse; merging or closing any PR; `make attest`; deleting anything; bumping a submodule pin; pushing or opening a PR in a repo that is not this program's; a design change if a removal unit fails tests or review.

## Facts at the start (2026-11-16T15:57Z)
- `main` = 0554efd4f (#1859, #1861). Stack, bottom to top: #1862 `feat/bench6-switches-obs` b29d59bef (base `main`) · #1863 `test/bench6-e2e-scaffold` 87be96651 · #1864 `fix/1804-vote-queue` 17327280d · #1865 `fix/epoch-record-closing-block-check` c2f266b9c · #1866 `fix/epoch-record-collector-hardening` ff877fb0e · #1867 `fix/epoch-loop-output-drop` f5f7589f5 · #1868 `fix/1804-quorum-exec-block` 38f00e88e · #1869 `fix/1807-digest-order-hold` 500e21afa. All MERGEABLE.
- `bench/bench7-2026-11` = 91a15e223 (bench 7's image commit, old base 45dce8947, seven switches).
- No bench instance, no driver, no cargo job; 194 GB free.

## Step 0 — records
- [x] memory `pr-body-limits-section.md`, `fixes-ship-unconditional.md`, index, `bench6-program.md`
- [x] `tasks/lessons.md` (the correction), this tick list, `tasks/checkpoint-bench8-orch.md`, `tasks/bench8-agent-rules.md`

## Step 1 — in parallel
- [x] 1a PR bodies for the new stacking: eight files edited, gates block re-run, stale-phrase check (sonnet), eight `gh pr edit --body-file`, live sha256 = file, `tasks/bench7/gh-posted.tsv`
- [x] 1b defect report to telcoin-network (`bench7-far-validator-batches-not-committed`): #1870
- [x] 1b defect report to tn-node-deployment (`bench7-metrics-agent-network-relabel`), after `observability/config.alloy:126-129` is confirmed unchanged on its `main`: they HAD moved (the draft cited the pinned copy); corrected, checked, posted as tn-node-deployment #66
- [x] 1c trial merge of the top with `main` 0554efd4f in `tn-b7-pcc` (conflicts, compile, scoped tests) → one conflicting file (`epoch_votes.rs`), resolved locally as b23472a43 with one logic fix; check rc 0, 2,175 tests pass; in the gates block; notes `tasks/bench8/merge-main-0554efd4f-notes.md`
- [x] 1d no-run analyses N1-N5 started (Step 5a)
- [x] 1e repo sweep: small records committed, the three devnet-launch lessons copied into `tasks/lessons.md`, devnet-genesis `main` pushed; inventory re-run

## Step 2 — the ninth PR `refactor/remove-bench-switches` (worktree `tn-b8-uc`, from 500e21afa)
- [x] R1 records (walk, kept votes: switches and off-arm tests removed): a5be61615, b67c0acdd · both commits reviewed and approved (Lows only: `tasks/bench8/review/followups.md`)
- [x] R2 `vote_queue_fix` (off branch, wrappers, 7 `_off` twins; `vote_timeout` < 9 s always enforced): d2b80ced5, adecca691, 6a7c3d7c5 · reviewed and approved (Lows only). Four of `main`'s vote tests now assert the kept answers: see `tasks/bench8/pr9-facts.md`
- [x] R3 always-on only (`quorum_exec_block`, `quorum_exec_block_starved_rounds`, window and streak state, adaptive tests, off/adaptive e2e arms, mixed-switch fleet): a242a3b4a, de075ab78 · reviewed and approved (one Medium, text: `make test-upgrade` does not show an old voter voting for a header that names an older block)
- [ ] R4 the hold (`Option` around `OwnChainOrder`, off drain branch, golden off test, no-hold control) · review
- [ ] R5 machinery (`runtime_switches!`, `switches()`, `log_switches()`, `SwitchValue`, the `node switches` line, `tn_node_switch`, `assert_switches`, `STACK_SWITCHES_ON/OFF`) · review
- [ ] gates on the new top: fmt; `./etc/ci-lanes.sh clippy`; `cargo nextest run --locked --workspace`; every new commit compiles alone; `make test-restarts`, `test-epochs`, `test-sigkill`, `test-e2e-resync`; the stack's own e2e tests ×3; `make test-upgrade` (previous = `main`); the three `state_export_import` tests; the hold's property hunt, 100,000 cases
- [ ] `git grep` finds none of the six names in `crates/`; `vote_timeout` under 9 s in the shipped presets and the devnet's configs
- [ ] PR text (opus, `human-writing`, limits section) · figure-check · branch pushed · ninth PR opened on `fix/1807-digest-order-hold`

## Step 3 — PR bodies, second pass
- [ ] #1862, #1864, #1866, #1868, #1869: switch statements rewritten; #1868 says the adaptive form is deleted and why
- [ ] closing keywords moved to #1862 (`Fixes` only where every point of the issue is met, else `Refs`)
- [ ] every body has "Limits and what a reviewer should look at"
- [ ] proposed squash title and message for #1862
- [ ] stale-phrase check, figure-check of every changed sentence, posted, live sha256 = file

## Step 4 — collapse, `main`, attest
- [ ] pre-flight on the trial merge of the new top with `main`: CI lanes, ignored `tn-lmdb` tests, ignored e2e suite, `make test-e2e-reth-migration`, `make test-e2e-resync`; conflict resolutions kept as notes
- [ ] (user) the collapse: #1869 down to #1862
- [ ] (on the user's word) merge `origin/main` into `feat/bench6-switches-obs`, pre-flight on that commit, push
- [ ] (user) `make attest`

## Step 5 — bench 8
- [x] (N0-N5, the summary and its figure-check done 2026-11-16) 5a N1 voters lacking the block per under-held header · N2 certified share against the laggards' wait · N3 held against not-held · N4 60-s course · N5 near headers after an uncommitted far certificate → `benchmark/private/bench8-prep/N1..N5/`, `tasks/bench8/no-run-findings.md`, figure-checked
- [ ] 5b `bench/bench8-2026-11` from 91a15e223 (confirmed against run 7a's manifest): `quorum_exec_block_floor_outputs` (default 8), the log fields, gates (unit tests, golden payloads at floor 8, nextest for the touched crates, the restart e2e set), image built and pushed
- [ ] 5c harness: arms `bench8-floor16`, `bench8-control`, `bench8-nohold`, `arms/switches.tsv` rows, the reduced-load launch file, credentials check, the idle check's `up` rule, the endpoint sampler as a segment, the first-and-last-sample export check; harness tests pass
- [ ] 5d run 1 (F, floor 16) — the user's go + a fresh `gcloud auth login`
- [ ] 5d run 2 (R or H or C by run 1's result) — the user's go + a fresh login
- [ ] 5e analysis, report, pages (publishing asked)

## Verification
- [ ] bodies: live sha256 = rendered file for all nine; no stale phrase; figure-check notes under `tasks/pr-bodies/notes/`
- [ ] removal: gate logs under `tasks/bench8/`; review verdicts; none of the six names left in `crates/`
- [ ] collapse: the pre-flight's log on the exact merged commit before the attest
- [ ] bench 8 build: golden test at floor 8; at idle on the fleet the new fields on 11 nodes and the floor read back from each
- [ ] defect reports: two issue URLs in `tasks/bench7/gh-posted.tsv`
- [ ] repo sweep: devnet-genesis `main` = `origin/main`; untracked = logs, pid files, the bundle, `.claude/`; no program repo ahead of its remote
