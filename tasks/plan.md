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
- [x] PT-2 voter-lock (`vote_queue_fix`): ported (PT-2B), reviewed (R-02), follow-ups in (PT-2C); stack head 02 = 6dae7520f, gated (1,303 tests)
- [x] PT-3 quorum-exec-block (both forms): PT-3a, PT-3v (voter-side tests), PT-3b (e2e: control 0.59-0.66, adaptive 0.92-0.94, always 0.99-1.00 on tn-lmdb), PT-3c (review follow-ups: the adaptive window counts HEADERS BUILT, explicit opening-block bound); reviewed (R-05); head 05 = b608a9eb8 (M + 88); its e2e tests x3 passed at the top-head gate
- [x] `epoch_close_forms.rs` ported and extended (unit ECF): in head 05, on the shared `tests/it/fleet.rs` helpers that enter at head 04
- [x] XF-1 main's epoch-loop output drop: verified REAL, fixed, reviewed (R-07), follow-ups in (XF-1b), **issue #1860 posted**; head `fix/epoch-loop-output-drop` = 38a8012f5 (M + 70), in the image. Its PR needs the user's word (Track U)
- [x] #1807 hold: HD-1 observability, HD-2a rule, HD-2c model (100,000 schedules, no order break with the hold on), HD-2b wiring + `digest_order_hold`, HD-3, HD-4a hook, HD-4b e2e (hold on: 0 lost / duplicated / out of order in three runs; control: 288 of 14,102 lost), R-06 approve; head 06 = fac7a05fb (M + 105). OPEN FOR THE USER before PR 06: held digests count toward the early-header trigger (bench 7 runs as built and measures the `own_parent=false` share)
- [x] epoch records: E1 (head 03 = cd52dcd81), E2, E3, E4, E5a hook, the review's follow-ups E3-FU and E4-FU, E5b e2e (`epoch_record_walk.rs`); reviewed (R-03, R-04); head 04 = ca258b37c (M + 61)
- [x] file order kept: E1 → HD-3 on `close_epoch.rs`; E2 → E3 on `state-sync/src/epoch.rs`; E2 → E4 on `epoch_votes.rs`; PT-0 → PT-3 → HD-1 → HD-2 on `proposer.rs`
- [x] per-topic reviews: 00, 01, 03 approved; 02, 04, 05, 06 (the hold), 07 (epoch loop) approved with follow-ups, all applied. No Critical or High anywhere
- [x] top-head gates on 91a15e223 (2026-11-15): fmt; `./etc/ci-lanes.sh clippy` EXIT=0; `cargo nextest run --workspace` 5,531/5,532 (one flaky test of main's storage crate, 10/10 on re-run); the repo's e2e sets off and on (11/11, 11/11, 12/12 each); a mixed-switch fleet and each new e2e test x3 (13 tests, 3/3 iterations); the model's 100,000-case hunt. the per-commit strict check: PASSED on the sixth cut 45dce8947..e83313305 (104 of 104 commits compile alone, 2026-11-15 07:14Z; the fifth cut failed on one test-helper commit, folded into its first user)
- [x] image (2026-11-15 05:48Z): `us-docker.pkg.dev/telcoin-network/tn-public/adiri:bench7-20261115`, digest sha256:15acdccafff786c2aa60ac69cddc3b09069648d5cf22ae1727c060fafa68822c, from `bench/bench7-2026-11` = 91a15e223 (pushed); probe by digest rc 0; local trial with the image's own binary passed (two repo e2e tests, the seven switches on)

## Track U — issues and PRs (texts by opus agents; created by the orchestrator, dry run first)
- [x] PR texts 00-04 and the epoch-loop text (`tasks/pr-bodies/bench6-NN-*.md`): figure-checked twice, ids = the final heads (branch `b7/p5`: 00 81a06c4e1, 01 48dae6a5f, 02 ad83a72f3, 03 cd52dcd81, 04 ca258b37c), gate results in, lint OK, dry-run posts OK
- [x] the eight topic heads pushed · PRs 00-04 created (assignee grantkee, reviewers MavenRain, sstanfield): DONE 2026-11-15 19:02Z on main 33b727fce: staging fast-forwarded 45dce8947 → 33b727fce; heads b29d59bef, 87be96651, 17327280d, c2f266b9c, ff877fb0e, f5f7589f5 (epoch-loop), 38f00e88e (05, no PR), 500e21afa (06, no PR); PRs #1862 (00), #1863 (01), #1864 (02), #1865 (03), #1866 (04)
- [x] the epoch-loop PR (`fix/epoch-loop-output-drop`, Fixes #1860): the user's word given 2026-11-15 ("Epoch-loop PR into staging"); #1867 opened 19:03Z, PR 6 of 6
- [x] new issues created 2026-11-14 (#1860 main's epoch-loop output drop; #1850 collector gaps, #1851 closing-block check, #1852 false quorum error, #1853 execute and persist in series, #1854 admission and the backlog, #1856 restart gap, #1857 rejoin under load, #1858 NewEpoch docs) (`tasks/issue-bodies/bench6-*.md`): closing-block check gap; collector gaps G1, G2; rejoin under sustained load + the follower's dead RPC; the false quorum error; stop between epoch 0's closing block and record 0; `NewEpoch` unreadable over RPC; in-flight bound measurements; execute and persist in series at 50,000 IOPS
- [x] comments with bench-6 data posted 2026-11-14: #1802, #1803, #1804, #1805, #1806, #1807, #1774
- [x] write-up of what does not carry (MDBX advice, the old stored-record check, pipelined persist): `tasks/bench6-not-carried-writeup.md` (goes into the PR stack's text)

## Track H — harness for bench 7 (starts when the four bundles are launched: a bundle refuses a dirty `benchmark/`)
- [x] (d2ab915) HB-1 faucet build of M starts (`TN_ALLOW_FAUCET_ON_CHAIN`, BLS passphrase source, `node build:` line, image contract, no MDBX flags, engine in the manifest)
- [x] (dfbebec; whole suite running on it) HB-2 switch list, `benchmark/arms/bench7-always.arm`, `bench7-adaptive.arm`, provenance
- [x] (d2ab915) HB-3 storage measures on tn-lmdb (sampler, folio census, readers)
- [x] (scripts committed; ports reserved by HB-1b) HB-4 run-costing defects: listener ports, the chained launcher, the fleet-health watch, the metric export check
- [x] (80deb36, 0adb69e; whole suite running on 0adb69e) HB-5: HB-5a (launch files `bench7-always.env` / `bench7-adaptive.env`, 32 kept log shapes, `halt=` in the sampler + the fleet watch's alarm, the export's 38 must-haves) and HB-5b (the arms summary's bench 7 blocks, the seventh fail-stop, `--halt-baseline`)
- [x] full harness gate alone on the host: PASSED 2026-11-15 06:38Z (unit suite 1,626 OK, mutation checker 0 failures, 2,710 s); `params-apply.sh --print-state` ×2 rc 0 (seven switches each; starved rounds 0 / 4); the deploy's and the blast's dry plans and the chained launcher's plan mode rc 0 for both forms; the teardown's dry mode: 0 candidates, left=0

## Bench 7 — the two runs (orchestrator only; the user's go + a fresh `gcloud auth login` first)
- [x] run 7a = **r20261115-1131** DONE 2026-11-15 (deploy 11:31-12:24Z, blast 12:40-14:22Z by hand after the idle check stopped on one node's missing `up`, export 14:27Z with validator-09's Prometheus set partial, teardown 14:42Z deleted=12 left=0, archive 14:49Z problems=0) (always-on, starved rounds 0): deploy12 → idle checks → blast15 → prelim read + metric export → teardown-dry → teardown → reindex → archive
- [x] run 7b (adaptive, starved rounds 4): FIRST ATTEMPT r20261115-1450 LOST (the cloud login expired 16 min into the blast, 16:24Z; fleet torn down 16:53Z deleted=22 left=0; not a bench 7 run). RE-RUN = **r20261115-1653** (chain `tasks/bench7/r20261115-1653/chain-20261115T165325Z.log`; deploy rc 0 17:40:48Z; blast launched by hand 17:46:24Z; per-minute endpoint samples of all 11 nodes); blast rc 0 19:19:08Z; export 397 metrics / 22,759 series; teardown deleted=12 left=0 19:34:12Z; archive ok files=626 problems=0 19:39:59Z
- [x] analysis per run, the 7a-7b comparison, the comparison with runs 2 and 3, the report: DONE 2026-11-15 ~22:00Z. Sixteen per-run analyses under benchmark/private/bench7-<run>/A1…A8/; the form comparison benchmark/private/bench7-r20261115-1653/A9/comparison.md + recommendation.md; the bench 6 comparison …/A10/vs-bench6.md + far-validators.md; the report `tasks/bench7-report-r20261115-1131.md` (827 lines, sections under tasks/bench7/report/, figure-checked: about 1,750 figures, every wrong / weak item applied; figcheck-1…4.md)
- [ ] **form gate**: the result and a recommendation to the user → PR 05 with the chosen default, PR 06, the bench 7 pages, the last issue comments — REACHED 2026-11-15: the recommendation (keep always-on as the default at 20,000 IOPS; weak support) is with the user; PR 05, PR 06 and the bench 7 pages wait for their word

## Wrap-up
- [ ] ledger verdicts, `tasks/todo.md` review section, lessons, memory, the launch README, push devnet-genesis

## Re-plan 2026-11-15: upstream main moved to 33b727fce (M + 3) after every gate — APPROVED by the user 2026-11-15 ~11:13Z (R1-R4, R6 into staging; R5 follows from R2)

Facts (the note `tasks/bench7/main-delta-33b727fce.md`; the orchestrator log has the short form):
- `main` gained #1848 (bundled bootstrap servers), #1849 (storage v2 follow-ups, by a reviewer of this stack) and #1855 (each transaction stored once, new datadirs). The staging branch and the stack are on M = 45dce8947.
- #1849 stops a node on a certified record that conflicts with its own, unconditionally: the second gap of #1850 is fixed on main, and head 04's `epoch_record_conflict_halt` has no effect once main is merged in. #1849 also narrows the restored-floor rule of the guard head 03 extends and adds a record-0 call that head 03's changed signature breaks (a merge of main into head 03 or above does not compile as it is).
- PR text 04 is false of today's main in three places; PR text 03 in two. PRs 00-02 are untouched in substance (head 00: one mechanical hunk in `crates/config/src/node.rs`).
- #1850's first gap, #1851, #1852 and #1860 are still present on today's main.
- The harness starts an image of the stack on today's main as it is (three log-shape gaps to close). What #1855 changes for the measurement: device bytes (about 171 kB/s less per 1,000 tx/s), not the write count or the syncs (inferred from the code; within 0.2 % of 20,000 IOPS per 1,000 tx/s).
- Nothing is pushed or posted that would have to be taken back: no topic head is on the remote, no PR is open. The sixth cut of the series passed the per-commit check (see the ledger).

The items (approved as recommended):
- [ ] R1 (APPROVED; the user logged in; RUN 7a LAUNCHED 11:31:32Z as r20261115-1131, always-on) bench 7 runs NOW on the image as built (M + stack): both runs share one base, which is what the form comparison needs; the report states the base and what today's main differs in. Needs the go and a fresh `gcloud auth login`.
- [x] R2 DONE: the stack is on main 33b727fce (b7/n2, 103 commits, top 500e21afa), without `epoch_record_conflict_halt`; every gate passed on the top (cargo gates 14:30Z; the e2e lane block 18:40Z; the upgrade set off/on 18:59Z; a trial merge with the later main c1b1eb9fe (#1859) compiles and passes 1,764 tests)
- [x] R3 DONE 2026-11-15 19:02Z: PRs 00-04 opened on main 33b727fce (#1862-#1866), texts figure-checked, gate results filled in. Main had moved once more by then (c1b1eb9fe, #1859, unrelated; clean merge checked): the stack stayed on 33b727fce, told to the user at 16:20Z and 16:55Z.
- [x] R4 (POSTED 2026-11-15 11:31Z after its figure-check and the user's "post": https://github.com/Telcoin-Association/telcoin-network/issues/1850#issuecomment-6893661988) a follow-up comment on #1850: its second gap is fixed by #1849, the first is open, and the question whether a stop should need a super-quorum of the anchor committee; written and figure-checked first.
- [ ] R5 the harness drops `epoch_record_conflict_halt` with the next image, not before bench 7 has run (the bench 7 arms and image name it).
- [x] R6 DONE: the epoch-loop PR is #1867 (Fixes #1860), PR 6 of 6 into staging.

