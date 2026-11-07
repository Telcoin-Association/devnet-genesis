# Plan: bench 5 — fix the commit-lag demotion and the rejoin loop, lift the execution ceiling, measure time-to-land end to end

Written 2026-11-06 (xerxes). Frozen contracts: `tasks/checkpoint-bench5-design.md`. Rules: `tasks/bench5-agent-rules.md`. Ledger:
`tasks/bench5-cherrypick-ledger.md`. Live-run checkpoint: `tasks/checkpoint-bench5-live.md`. No Claude attribution on any commit,
PR or issue text. Opus agents implement; subagents never push and never touch the fleet. Supersedes the bench-4 plan (all ticked;
report `tasks/bench4-report-r20261105-0803.md`).

## Wave 0 — orchestrator setup
- [x] Worktree `../telcoin-network-bench5` on `bench/main-fixes-2026-11` = origin/main 4bf4604d2 (main moved overnight: GHSA-8fj9 sync-peer fix on top of 7527b15c0; base amended)
- [x] tn-contracts submodule initialised (`--reference` to the bench-4 worktree's module)
- [x] Nine observability commits cherry-picked `-x` cleanly (77539d77d..3a721a1b6)
- [x] Verify: fmt clean; nextest libp2p+primary 916 passed; the three PR-1783 tests pass; workspace clippy clean (`tasks/bench5-wave0-verify.log`)
- [x] `tasks/checkpoint-bench5-design.md`, `tasks/bench5-agent-rules.md`, `tasks/bench5-cherrypick-ledger.md`, this checklist
- [x] `benchmark/config.sh` knob block (orchestrator-owned; lines 335-356 + validation 593-620; sourced through a driver-named wrapper, 6 bad values refused)
- [x] Wave-1a unit worktrees `../tn-bench5-{f1,f3a1,f3a2,e1,l1}` on the shared target dir
- [x] Two Prometheus snapshot copies extracted for I-2p / I-3 (scratchpad prom-I2p, prom-I3)

## Wave I — investigation (5 opus agents, read-only; checkpoints `tasks/checkpoint-bench5-I*.md`)
- [x] I-1 F1 commit-lag demotion → `tasks/issues/bench5-f1-commit-lag-demotion.md` + §F1 amendments
- [x] I-2c F2 code → `tasks/issues/bench5-f2-execution-ceiling.md` + §F2 amendments
- [x] I-2p F2 Prometheus replay → `benchmark/private/bench5-prep/F2/`
- [x] I-3 LAND → `tasks/bench5-land-time-baseline.md` + §LAND amendments
- [x] I-4 F3 rejoin loop → `tasks/issues/bench5-f3-rejoin-loop.md` + §F3 amendments
- [x] Contracts amended and frozen in `tasks/checkpoint-bench5-design.md` (§F2 I-2c+I-2p, §F1 I-1, §F3 I-4 — F3-1a/1b dropped, F3-0 added; §LAND I-3 — 4-index arm, nonce-gap finding)

## Wave 1a — parallel implementation (one worktree each; tn-review per unit; cherry-pick F1 → F3a1 → F3a2 → E1 → L1)
telcoin-network:
- [x] U-F1 F1-1 — f5324e6db (review 0 BLOCKING, S1/S2 + 5 NIT applied; 703 tests); integrated as 557c9b737
- [x] U-F3a1 F3-0 certificate retention — 5d7cbdc03 on bench5/u-f3a1 (ROUNDS_TO_KEEP 128, floor check; 1235+372 tests)
- [x] U-F3a2 F3-2 — 48b969dd8 (review 0 BLOCKING, S1/S2 + 5 NIT applied; 421 tests); integrated
- [x] U-E1 E1+E2+E3+L5 — 69c9eba0d 988ca198e fa9a4ff55 5105eda5a (review 0 BLOCKING; S1-S3+N4 applied; 519 tests; per-commit strict check); integrated a962b9876..decc4cbc4
- [x] U-L1 L1+L2+L6 — ae8f0a130 5f6baf9a7 2561e98ff (review 0 BLOCKING; fixes applied; 132 tests); integrated dac760298 d660e8e7f 716de9019 (recorder.rs add/add resolved)
tn-transaction-generator:
- [x] U-T (T1, T2, T3) — COMMITTED in tn-transaction-generator: 0ca0c49 4fd1fb0 6dad96f (review 0 BLOCKING; S1/N1/N2 + digests_requeued series folded in; 201 Rust tests, bench 124 OK) → BENCH_TXGEN_SHA=6dad96f (blaster image built by deploy step 1 via Cloud Build once gcloud is re-authed)
devnet-genesis:
- [x] U-H1 light-load arm (4 indices, per-index window) + BENCH_WINDOW + LOG_RATE + landings flags — 24 tests, 6 anchors; uncommitted
- [x] U-H2 deploy fsync probe + sync-mode knob — 131 tests in test_node_image, 3 anchors; uncommitted
- [ ] U-H3a teardown D34 exemption + B9 skip-certification + A10
- [x] U-H3b bucket log transfer — 42 tests, 3 anchors, iap default byte-identical; CANNOT RUN on this fleet (nodes have devstorage.read_only scope; needs common/create-instances.sh change = follow-up) → bench 5 pulls over iap
- [x] U-H4a stage-latency.py — 12 tests, 3 anchors; bench-4 preamble blocks reproduce I-3 trace; uncommitted
- [x] U-H4b kpis/windows/make_bundle + scrub + tn-benchmarks (56+41 tests, 9 anchors; bench-4 KPIs byte-identical; seen p50 12.92); uncommitted in both repos

## Wave 1b — after 1a integrates (integration 73d3163db = F3-0, F3-2, F1-1, E1-E3, L5, L1, L2, L6, L4, L3, E4, L7, F3-5, F3-6, F1-2, F3-3, F3-4 — verified through tasks/bench5-integration-verify-{1..8}.log, all green; E5 and the e2e commits still to land)
- [x] U-F3b1 F1-2+F3-3+F3-4 — 3e4f0dd54 f61792797 324d3e5ad (review 0 BLOCKING; S1-S5 + nits applied; 714 tests); integrated a3a00525e f2f9437f7 73d3163db (two nested-test-module conflicts rebuilt by hand)
- [x] U-F3b2 F3-5+F3-6 — 69f3891dc 86a650d91 (review 0 BLOCKING; S1-S3 + N1-N5 applied; 503 tests); integrated bf34ec488 cae41a400 (metrics/network_tests add/add resolved)
- [x] U-L2a L3 — dc09d7985 (392 tests); integrated c7764fac4; Wave-2 land-path review covers L3+L4
- [x] U-E2a E4 — 928c12300 (review 0 BLOCKING; S1/S2 + nits applied; 509 tests); integrated 9039198de
- [x] U-H5 README (+191), check_mutations 63/63 killed, hygiene 13 tests, CI, test_txgen_probe (4) — suite 951 OK; probe pipefail bug fixed by the orchestrator; uncommitted

## Wave 1c — after 1b
- [x] U-L2b L4 — 994755c1c (907 tests; observability-only); integrated 44a87b0ef; Wave-2 land-path review covers L3+L4
- [x] U-L3 L7 — 4364ec892 (review 0 BLOCKING; S1 + N1-N3 applied; 398 tests); integrated 3304d94ce
- [x] U-E2b E5 — 61234d989 (review 0 BLOCKING; S1-S3 hardening + N1-N3 applied; 516 tests; 32-case proptests reach evict/clear; no path difference); integrated 420f8aef7 (clean)
- [x] U-X F1-3+F3-7 e2e — de49fbb90 2e4e55dbf (slow-execution node active with exec lag 246 vs window 15; one rejoin, 146 own certs after promotion, 0 fetch failures, also at gc_depth 50); integrated d33ecb797 ae68877dc (clean)

## Wave 2 — verify, review, build, probe, dry runs (serial)
- [x] Per-commit strict compile check: 22/22 topic commits OK with `-D warnings -D unused_extern_crates` (tasks/bench5-per-commit-check.log)
- [x] Workspace fmt / clippy / `nextest --locked --workspace` green on 9840759a2 (4007 passed incl. SEC1+SEC2, strict check clean — tasks/bench5-tn-workspace-verify.log; earlier 3980 on 420f8aef7); `make public-tests` GREEN on 420f8aef7: workspace 3980 passed, epoch e2e set 11/11, restarts e2e set 10/10 (tasks/bench5-public-tests.log, 26 min); `test_slow_execution_stays_active` to run explicitly in the final pass (not matched by the restarts filter)
- [ ] tn-review per topic group: F1 ✓, F3-2 ✓, engine ✓, L1/L2/L6 ✓, F3-5/6 ✓, L3+L4 ✓ (fixes squashed), E4 ✓ (amending), L7 ✓ (amending) — all 0 BLOCKING; F3b1 review after its throttle amend; tn-security-eval on the consensus set DONE: CONCERNS — no divergence path; 2 CRITICAL liveness (SEC-1 hash-only ring match exposed by F1-1; SEC-2 no rejoin re-check on a stalled head), 2 HIGH, 2 MEDIUM → U-SEC1 amended f53249c80 (792 tests; e2e lagged-restart passes) INTEGRATED as 9bad6966d; U-Xfix 317444cb9 (delay 500 ms, run-ahead counter asserted 0, 3/3 passes) integrated 6f9703662; U-SEC2 c781243a7 reviewed 1 BLOCKING (stall must be OBSERVED: ≥ 20 s since loop entry, head unchanged, gossip frontier ≤ replayed; stalled promotions exempt from the cap; e2e for a halted committee) — amended as eb670e95e (743 tests); second review: 1 NEW BLOCKING (frontier condition refuses a halt caused by the node's own demotion: queue the held consensus number at loop entry) → U-SEC2b amended as e7bd531a5 (793 tests: tracker fetches the held frontier at start, per-check gap re-request, walk-cap hold); third tn-review APPROVE 0 BLOCKING 0 SHOULD 6 NIT → final 6eb90481d INTEGRATED as 9840759a2; U-SEC2e2 halted-committee e2e 98c3b82c3 PASSED 5/5 (halt 21 s, resume → first commit 42-53 s, walk-cap hold observed firing in the diagnostic run) — INTEGRATED as 74a4e984e (the complete branch head); e2e pass on 9840759a2: lagged-restart + slow-execution PASS (tasks/bench5-e2e-security-pass.log); final `make public-tests` on 74a4e984e FAILED (2026-11-07 03:32Z): `restarts::test_restartstt` fails deterministically (2/2) — a restarted validator never rejoins: the SEC1-tightened `restored_dag_gap` window check trips on every promotion after a follower catch-up (no certificates stored for the rounds caught up via the pack), two failed promotions exhaust the rejoin cap, and the inactive follower then stops replaying (replayed_number frozen). Evidence tasks/bench5-restartstt-fail-{test-output.txt,node2-run2.log}. The log also holds a second, duplicated run (an earlier launch had started after all; lesson 2026-11-07) whose extra failures (lagged_delayed, halt e2e) are port/log collisions. U-FIXRESTART DONE (worktree ../tn-bench5-fixrestart, bench5/u-fixrestart): b9eee3a2a `fix(primary): judge a restored dag by the certificates ordering can reach` (Topic f1-commit-lag; replaces SEC1's window check with "a reachable restored certificate with a missing parent"; SEC-3 shapes still demote) + 685af13b6 `fix(executor): re-request the outputs behind a frontier when the replay stalls` (Topic f3-rejoin; the stalled-head timer also re-requests when the replay is frozen). 703 unit tests green; e2e restartstt 3/3 + lagged_under_load, slow_execution, halt, lagged_delayed, delayed all PASS (tasks/checkpoint-bench5-u-fixrestart.md). Review APPROVED (0 BLOCKING, S1 + nits folded in by U-FIXRESTART-S1: same-range re-send with 5→60 s backoff while the replay floor is stuck; tasks/checkpoint-bench5-review-FIXRESTART.md, tasks/checkpoint-bench5-u-fixrestart-s1.md). INTEGRATED 2026-11-07 ~05:05Z as 8651e5abd (guard) + 685b8505b (replay) = new head; trees identical to the unit head. Gate 2 running detached (scratchpad bench5-gate2.sh, pid tasks/bench5-gate2.pid): per-commit strict check 420f8aef7..HEAD → tasks/bench5-per-commit-check-2.log, then fmt/clippy/`make public-tests` → tasks/bench5-public-tests-2.log. GATE 2 GREEN 05:22Z (fmt 0, clippy 0, per-commit 6/6, workspace 4014, epoch 11/11, restarts 11/11) → PUSHED 685b8505b 05:25Z; BENCH_NODE_EXPECT_SHA updated. Open: the halt e2e flaked once in its first phase (node 3 caught up through buffered gossip before any certificate fell outside its window) — test-robustness unit U-HALTFIX to follow. The branch is NOT pushed beyond 420f8aef7; U-SEC2e wrote the halted-committee e2e (+334, uncommitted patch in scratch USEC2e/) — 2 of 3 passed, the failure exposed SEC-2 dead zone #2 (state-sync skips fetches at 6 active) → folded into U-SEC2b; the test is committed after the amended SEC2 lands; U-SEC1 amending (S1/S2/S4 + nits, running the two e2e tests); then cherry-pick, re-verify, re-push; harness U-review ✓ 0 BLOCKING (byte-identity 12/12, 15/15, 13/13 KPIs; 3 SHOULD → U-Hfix running); txgen review ✓ 0 BLOCKING (fixes folded in)
- [ ] BLOCKING fixes → checks again (the security findings SEC-1/2/3/5/6/8/10/11 are being fixed as two commits; SEC-7 accepted as designed — see design §SEC)
- [x] Pushed `bench/main-fixes-2026-11` @ 420f8aef7 (31 commits: 9 obs + 22 topic) over ssh
- [ ] (needs operator `gcloud auth login` first — token expired 2026-11-06) image `adiri:bench-main-fixes-<yyyymmdd>` built + pushed; digest recorded; probe 12/12 (`tasks/bench5-probe-bench-image.log`)
- [ ] Harness: full unittest, check_mutations (all anchors killed), bash -n, shellcheck, check-bash32, py3.9 grammar; txgen tests + blaster image
- [ ] Dry runs: deploy (`--print-prestart` with/without sync-mode), blast (light-load lines), teardown on r20261105-0803 (read-only gcloud)
- [x] Commits: devnet-genesis 85fb888..fe35deb (7 groups: blast, deploy, teardown/pull, tools, report, docs/CI/anchors, tasks); txgen 0ca0c49 4fd1fb0 6dad96f; tn-benchmarks schema/window words committed; nothing pushed

## Wave 3 — live run (orchestrator only, detached segments; `tasks/checkpoint-bench5-live.md`)
- [ ] Pre-run gates (obs-devnet < 60 %, devnet healthy on info filter, quota, leftovers, gcloud token); RTT re-probe incl. us-east4
- [ ] deploy `--yes --with-contracts --to 12` (FSYNC_PROBE per node, OBS_READY, OBSCFG_OK ×11, PRECFG_OK ×11, rc 0)
- [ ] idle ≥ 10 min
- [ ] blast `--yes --from 13 --to 15` with BENCH_LIGHT_LOAD=1 (LIGHT_LOAD_START/DONE, BENCH_BLAST_DONE ×10, chaos lines, 0 aborts)
- [ ] teardown `--run $R --yes` (health table, pull ≤ projection, prometheus snapshot, TEARDOWN_DONE left=0, obs-devnet untouched); `--reindex`

## Wave D — analysis (`benchmark/private/bench5-<run>/<unit>/`)
- [ ] D1: A1, A2, A3 (F1/F3 verdicts), A4n (F2), A4o, A6 (land path) in parallel
- [ ] D2: P backfill, A5 report `tasks/bench5-report-<run>.md`
- [ ] D3: triage of other systemic findings → one investigation agent per confirmed candidate → `tasks/issues/bench5-<slug>.md`

## Wave E — publish
- [ ] Backfill JSON; `make_bundle.py --run <R> --compare r20261105-0803` (detached); site gates; `git add runs/<R>`; push; HTTP 200
- [ ] Pushes: devnet-genesis main, txgen main, telcoin-network branch
- [ ] Ledger verdicts; `tasks/pr-bench5-<slug>.md` per topic; observability PR text refreshed
- [ ] Memory `bench5-main-fixes-run.md` + index; `tasks/lessons.md`; `tasks/todo.md` review section
