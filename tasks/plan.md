# Plan: bench 6 — recover the execution ceiling, fix every bench-5 concern, rerun, publish, upstream what the run confirms

Written 2026-11-10 (xerxes). The approved plan text is `/home/drtnarg/.claude/plans/i-want-to-run-groovy-grove.md` (the orchestrator's
brief; this file is its tick list). Previous plan archived at `tasks/archive/plan-bench5-upstream-2026-11-09.md`.
Agent rules: `tasks/bench6-agent-rules.md`. Design reports: `benchmark/private/bench6-prep/design/`. Ledger:
`tasks/bench6-cherrypick-ledger.md`. Names contract: `tasks/bench6-contract.md`. Upstream map: `tasks/bench6-upstream-map.md`.
Standing rules: no Claude/Anthropic attribution anywhere; opus agents implement and analyse, sonnet for inventories; subagents never
push, never `gh … create/edit/comment`, never touch GCP; one writer per file; `tn-node-deployment/` and `common/` are not edited;
`--project tn-devnet` on every ad-hoc gcloud read; one e2e job per machine at a time; cargo through the host-wide slot wrapper.

User decisions (2026-11-10): U1 image base = the landed staging tree + review follow-ups; U2 everything, switchable (defaults =
bench-5 behaviour; pipelined persist only if its go/no-go tests pass by the image cut); U3 two deployments (run 1 arms, run 2
headline; one-VM GCE probe before run 1); U4 generator: measurements only. Issues and PRs only after the benchmark confirms a fix.
Gates: G1 (after W1 + the GCE probe), G2 (before run 1), G3 (after run 1's analysis), G4 (after run 2's analysis).

## Facts at the start (2026-11-10T23:19Z) — what changed since the plan was written (21:00Z)
- The tn-workspace session finished and PUSHED both tips: staging `staging/benchmark-obs-2026-11` = 514bf6687 (ten PRs merged into it,
  main 9aa1d6139 merged, the event-gap fix; attested; PR #1826 into main open) and `fix/benchmark-obs-review-followups` = 165e3fe01
  (48 commits on the staging tip; attested; PR #1827 into main open). main is an ancestor of both.
- **Base pin for bench 6 = 165e3fe01** (replaces the plan's local pin `bo-asm` 807ee9ed4; the design reports' line numbers are from
  807ee9ed4, so every unit greps first). The "rebase onto pushed tips" step of W3 is now only "re-check that the base has not moved".
- No cargo job and no attest was running at 23:19Z (load 0.8). Disk: 259 GB free on `/`; `/tmp` 17/31 GB; swap full.
- Old target dirs (nothing deleted without the user's word): telcoin-network-pr5-target 37 GB, telcoin-network-bench/target 24 GB,
  telcoin-network-bench5/target 20 GB (ours, 81 GB); tn-workspace targets ≈ 300 GB (the other session's). sccache 10/10 GiB.
- Deviation recorded: node units run as general-purpose opus agents that load `tn-rust-skills` + the domain skills, write their row's
  unit tests, run the package-scoped gates themselves and spawn a `tn-domain-reviewer` on their diff (the `tn-rust-engineer` agent
  definition cannot run cargo, write tests or spawn its own reviewer; lesson 2026-11-05). `tn-review-agent` / `tn-security-eval`
  per topic stay as planned in W3.

## W0 — preflight (orchestrator)
- [x] bench-5 launchers copied out of the old session scratch → `benchmark/launch/bench5/` (5 launchers + 2 gate scripts, cmp-identical) — 23:20Z
- [x] old plan archived; this tick list written
- [x] planning reports saved to `benchmark/private/bench6-prep/design/` (node design, harness design, explorers A-C, decomposer check)
- [x] `tasks/bench6-agent-rules.md`; helpers `tasks/bench6/{mk-worktree.sh,e2e-lane.sh,w0-archive.sh,w0-archive-verify.py}`
- [x] integration worktree `/home/drtnarg/coding/telcoin/telcoin-network-b6` @ 165e3fe01 on `bench/bench6-2026-11` (rerere on, tn-contracts by reference)
- [ ] archive r20261103-1922, r20261107-1504, r20261105-0803 → `gs://tn-devnet-benchmark-archive/runs/<run>/results/` (detached, pid
      `tasks/bench6/w0-archive.pid`, log `tasks/bench6/w0-archive-20261110T232332Z.log`; exclude rule re-proven by dry run: a `^`-leading
      `--exclude` is silently ignored by gcloud and would have uploaded `genesis/`); verify report `tasks/bench6/w0-archive-verify.md`
- [x] project-context ×3 (sonnet): devnet-genesis 38 KB, telcoin-network 52 KB (describes the b6 tree at 165e3fe01; lives in the main checkout's `.claude/`), tn-benchmarks 23 KB
- [x] task-decomposer: the task tool was not available to it, so the list and its dependency corrections are `tasks/bench6-task-list.md` (85 tasks; U1, U2, U7 need only U0a; GCE probe waits on I-1; H11 after H10; site pushes wait for their gates)
- [x] ledger, contract and upstream-map files seeded (`tasks/bench6-{cherrypick-ledger,contract,upstream-map}.md`); orchestrator resume state `tasks/checkpoint-bench6-orch.md`

## W1 — investigations (opus; outputs `benchmark/private/bench6-prep/<unit>/`) — all six launched 2026-11-10 ≈ 23:35Z
- [x] I-1 persist trigger — DONE: the load ran in a re-opened DB whose advice covered only the genesis pages (stage-only start + start-all); `MADV_RANDOM` closes read-around but not the prefault `pwritev` route; eviction is ineffective; bench-4 commit = 38 µs/tx; local probe arms 7/8 built
- [ ] I-1r local probe run (`run-i1.sh`, ≈ 40 min quiet window `tasks/bench6/QUIET`; builds wait behind `tasks/bench6/cargo-slot.sh`)
- [x] I-2 generator and sealed tx — DONE: no window generator-bound; resends reconcile (60.5 % accepted as new); 3,804 queued-pool evictions from stale entries; ≥ 95 % of the unlanded lost; the cliff exists since bench 3; boundary loss path uncovered (S6 → ST-U6)
- [ ] I-3 ceiling recut — sections 1, 2, 3a, 4, 5, 6 DONE (commit cost drifts +0.031 s/output per minute of load in both windows; overlap slows `finish` 2-3×; v09's lost leader rounds = the #934 durability barrier); 3b pending U4b's Criterion results; ten report corrections saved for the I-6b pass
- [x] I-4 design answers — DONE: design D as written always settles on the floor (8 outputs stale); a twelfth switch `quorum_exec_block_starved_rounds` makes both variants buildable; U2 also owns `network/message.rs` + `error/network.rs`; G1 items in `tasks/bench6-g1-notes.md`
- [x] I-5 pipelined persist design — DONE (`I-5/design.md`): go for implementation; three ownership gaps settled (U0c adds `OutputBuildScope::seeded` + `pub mod persister;`; U12a owns `engine/src/error.rs`; ST-U12a owns the `mod` line in `engine/tests/it/main.rs`)
- [x] I-6 bench-5 report repair — DONE: 12 defects corrected (16-entry corrections list), backfill caveats updated, local re-bundle + site gates green (115 tests, scrub 0/0); nothing committed
- [x] I-6b second pass — DONE: 28 statements corrected from I-1, I-2, I-3, I-4 ("## Corrections (2026-11-11)", 22 entries), backfill summary + caveats 2, 5, 7, re-bundle 719 s, site gates green (115 tests, scrub 0/0); report + backfill + tn-benchmarks run files uncommitted until the user's G1 review

## W2a — node topics (base 165e3fe01; switches default to bench-5 behaviour)
- [ ] wave 0: **U0a DONE** (14 commits, tip da9dc0ff3, integrated 3696d49f3..5b9f13b25; twelve switches + `ExecutionBacklog`; a switch at its default is not written to `parameters.yaml`) · U0b e2e scaffold (4 commits; its e2e check waits behind a foreign attest); U8 DONE f3d34932e, integrated (ledger row 1)
- [ ] wave 0b: U0c plumbing — launched 2026-11-11 ≈ 01:22Z from 5b9f13b25 (brief `tasks/bench6/briefs/u0c.md`)
- [ ] wave 1: U1, U2, U7 launched ≈ 01:22Z from 5b9f13b25 (they need only U0a) — U1 quorum-exec-block · U2 voter-lock · U3 mdbx-advice · U4a recovery-pool · U4b contention bench · U5 tracker-drain ·
      U6a sealed-keep store · U7 digest-dedupe (worker) · U8 bench6-obs · U12a pipelined-persist core (after I-5)
- [ ] wave 2: U9 parent-grace · U11 inflight-bound · U12b pipelined wiring · U6b sealed-keep batch marks · U1v voter cases · ST-U12a
- [ ] wave 3: U10 digest-dedupe (proposer) · ST-U1 · ST-U5 · ST-U6 · ST-U11 · ST-U12b
- [ ] integration by cherry-pick: U0a-c, U8, U5, U4, U3, U2, U1 (+U1v), U7, U6a-b, U9, U10, U11, U12 last
- [ ] pipelined persist go/no-go recorded

## W2b — harness and generator units
- [x] H0 knobs and frozen names — DONE (config.sh +85/−5, `arms/switches.tsv` 12 keys, arm-file format, persist CSV + folio headers, `MANIFEST-FIELDS.md`; 9 new tests, 11/11 mutation anchors killed); H9a DONE (per-second send series, window waits, resends by cause; 211 tests; send path byte-identical to a golden recorded before the change; uncommitted in the generator repo); H9b DONE (tail scan, gap resends by answer, stalled columns, unlanded export, tail histogram, `aggregate.py`; 229 tests; golden untouched); generator commit d3be21a on its local main (ahead 1, not pushed); H9c launched 2026-11-11 ≈ 01:20Z (tail landings must not change any pre-existing field)
- [ ] H1a → H1b · H2 → H3 · H4 · H5a → H5b · H6a · H7a ∥ H7b · H10 · H11 — **H1a DONE** (38aa93a) · **H2 DONE** (451d090) · **H6a DONE** (a99566b: prefilter pass ≈ 1 min for 64 logs, readers 600 s → 55 s; archive-run + archive-verify) · H5a running · H1b and H10 launched ≈ 01:27Z · **H4 DONE** (persist sampler + folio census, 36 tests; follow-up running: one more CSV column) · **H7a DONE** (switch provenance, kind-based windows, 5 modules green, bench-5 bundle reproduces) · **H7b DONE** (arms-summary.py + arm windows; bench-5 self-check reproduces the recut), committed
- [ ] H6b (README) and H8 (gate) last, no cargo job running

## W3 — verify, image, GCE probe
- [ ] one-VM GCE probe (announced; H0, H2, H4, H10 in) → I-1 verdict
- [ ] **G1** (investigations, probe, design defaults, persist arms P2/P3, boot image pin, corrected bench-5 report, prune question)
- [ ] node branch gates: per-commit strict check, fmt, clippy ×2, nextest --workspace, public-tests, restarts/epochs/sigkill e2e,
      mixed-switch 2-on/2-off fleet, tn-review per topic, tn-security-eval for U1, U2, U3, U6, U7/U10, U9, U11, U12, final_state check
- [ ] base re-check (origin tips unchanged or rebase explained hunk by hunk)
- [ ] image built and pushed, digest recorded, `--probe-node-image` by digest; generator image, `BENCH_TXGEN_SHA` pinned
- [ ] harness gate alone on the host; dry runs (prestart per knob, params-apply per arm file, probe, teardown)
- [ ] **G2**

## W4 — run 1: arms (orchestrator only; `tasks/checkpoint-bench6-run1.md`)
- [ ] deploy → A0 → P1 → V → POOL+LOCAL → PIPE → BOUND → GR150 → A0′ → collect → teardown → archive
- [ ] W5 analysis units A1-A7, A4o, D1 → **G3**

## W6 — run 2: headline (`tasks/checkpoint-bench6-run2.md`)
- [ ] deploy → idle → blasts → teardown → reindex → archive → bundle
- [ ] W7 analysis, report `tasks/bench6-report-<run>.md`, publish to tn-benchmarks → **G4**

## W8 — upstream (after G4)
- [ ] stack on `staging/benchmark-bench6-2026-11`, verify per head, texts, issues and PRs (assignee grantkee, reviewers MavenRain + sstanfield), MDBX coordination

## W9 — wrap-up
- [ ] ledger verdicts, todo.md review section, lessons, memory, README archive-bucket fix, archive of both bench-6 runs, commit + push devnet-genesis
