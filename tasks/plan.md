# Plan: bench 5 → upstream — nine issues, ten stacked PRs into `staging/benchmark-obs-2026-11`, the persist root cause

Written 2026-11-09 (xerxes). The approved plan text is the orchestrator's brief (this file is its checklist). Previous plan archived at
`tasks/archive/plan-bench5-2026-11-06.md`. Rules: no Claude/Anthropic attribution on any commit, PR or issue text; opus agents implement;
subagents never push, never `gh … create`, never touch GCP; one writer per file; `tn-node-deployment/` and `common/` are not edited;
`--project tn-devnet` on every ad-hoc gcloud read; one e2e/nextest job per machine at a time. The orchestrator opens the issues and PRs.

User decisions (2026-11-09): base branch `staging/benchmark-obs-2026-11` (pinned at c65abdf79, D2); stop after PRs + issues + investigation.

Preflight facts (2026-11-09T21:31-21:40Z): origin/main moved to c2fffa5f2 = c65abdf79 + #1768 "Vendor and pare down the Reth code" (836 files,
+310k; touches our `tn-reth/src/env/mod.rs`, `tn-reth/src/error.rs`, `e2e-tests/tests/it/restarts.rs`) — staging stays pinned at c65abdf79
per D2; the user's pre-attest merge of main will meet it (report the `git merge-tree` conflict count in W5). #1793 still open. #1790 open
(#1644's replay parent check halts a fresh adiri node). gcloud auth is VALID (grant@telcoin.org; default project telcoin-network ≠ tn-devnet).
Snapshots: `benchmark/results/r20261105-0803/logs/bench-obs-prometheus-20261105T161318Z.tar.gz`,
`benchmark/results/r20261107-1504/logs/bench-obs-prometheus-20261107T185712Z.tar.gz`; recovery tarballs per node in each run's `logs/`.
Worktree `/home/drtnarg/coding/telcoin/telcoin-network-pr5` @ 3a721a1b6 (detached, rerere on); dedicated target dir
`/home/drtnarg/coding/telcoin/telcoin-network-pr5-target` seeded by `cp -a` from the bench target (marker `.seeded`).
Previous session's scratch (5.4 GB, `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/8fd11b65-538a-4941-99e8-e68b9023491c`)
could not be deleted by the orchestrator (safety classifier) — operator item.

## W0 — preflight (orchestrator)
- [x] fetch origin main; `merge-base --is-ancestor 4bf4604d2 c65abdf79` OK; pin c65abdf79 recorded
- [x] worktree + rerere; dedicated target dir seeding (background)
- [x] `gh api repos/$R/assignees/grantkee` → 204; ls-remote: none of staging/benchmark-obs-2026-11, feat/bench-observability, fix/*-<slug>, feat/<slug> exist
- [x] labels verified: bug enhancement consensus spike tech debt P0 P1 P2 upstream security ci (+documentation, duplicate, …)
- [x] project-context ×2 regenerated (2026-11-09 ≈ 21:58Z; devnet-genesis 25.4 KB, telcoin-network 37.1 KB) (sonnet agents; drafts in ~/.claude/plans/i-want-to-run-groovy-grove-agent-{a5cf86070e393dff8,afca48f1971ed4419}.md)
- [x] checkpoints: tasks/checkpoint-bench5-prs.md (U-STACK), tasks/checkpoint-bench5-texts.md (U-TEXT), tasks/checkpoint-bench5-persist-{a,c,d}.md (agents), tasks/checkpoint-bench5-persist.md (orchestrator)

## W1 — build and verify the stack (U-STACK, opus)
- [x] P1 split on 4bf4604d2 (U-STACK-a, done ≈ 22:15Z; 13 carry rows cleared; DEVIATION accepted by the orchestrator: the test-only `primary/src/tests/log_capture.rs` helper + its 3-line mod declaration were copied forward from land-path-obs cafca0d95 into f1 SEC1 9bad6966d so its test compiles; 07 then adds it as an identical add — noted in the f1 PR body via {{CARRY_NOTE}}): pr5/00-obs = 3a721a1b6 → pr5/01-log-dumps → 02-exec-split → 03-signer-reuse → 04-cached-reads → 05-f1-commit-lag → 06-f3-rejoin → 07-land-path-obs → 08-batch-wake → 09-cert-requeue (cherry-pick -x per `Topic:`; carry rows for SEC1 9bad6966d + guard 8651e5abd)
- [x] Gate: `git diff --stat bench5-p1/09-cert-requeue 067639def` empty (re-verified by the orchestrator 22:19Z); tags bench5-p1/NN-slug set
- [x] P2 rebase done: heads 243efea78 1b0717358 359ffa8bf 8af014cd2 8c5400c33 a8d601923 529926ad0 43310a70b 69abacd5e e9a31b4ad (tasks/bench5-heads.json); one conflict (obs 2d47fe191 in worker/network/mod.rs vs GHSA 677bb6055; range-diff 37/38 identical); cross-check merge ≡ pr5/09 (0 hunks); SIGKILL_SET_REQUIRED: no; strict `cargo check --workspace --all-targets --all-features` green at all ten heads; 38 commits, 0 attribution hits, 38 -x lines (orchestrator re-verified); sha map tasks/bench5-sha-map.json; P3 note: #1788 `publish_certified_consensus_num_hash` can move `last_published_consensus_num_hash` backward — exercised by the restarts e2e set
- [ ] P3: per-commit strict `cargo check --workspace --all-targets` (38/38); per head fmt + clippy + `nextest --locked --workspace`; top head `make public-tests` + test_slow_execution_stays_active + test_observer_late_join_catchup + test_observer_reconnect_after_pause (+ `make test-sigkill` if P2 found replay overlap); `git status --porcelain` empty after each run — LAUNCHED 2026-11-10T00:25Z (U-STACK-b, gated behind the probe window; S0: liveness mutation anchors 1×5 at every head, heads == heads.json, 38 commits)

## W2 — texts (U-TEXT, opus; writes only tasks/issue-bodies/, tasks/pr-bodies/, its checkpoint)
- [x] 9 issue bodies with `{{ISSUE:<slug>}}` cross-refs; lint clean (2026-11-09 ≈ 21:59Z; 5 titles shortened to ≤ 120 chars, verbatim H1s in tasks/issue-bodies/TITLES.md; no forward references)
- [x] 10 PR bodies with `{{ISSUE:*}}`, `{{PR:prev}}`, `{{ORDER}}`, `{{SHA:<bench sha>}}`, `{{TESTING:NN}}` placeholders; lint clean
- [x] tasks/bench5-labels.json (tables A and B) written by U-TEXT (verified: labels per table A/B; `{peer}` note confirmed against worker metrics.rs:292-299) for the orchestrator's gh calls

## W3 — GitHub (orchestrator only; after W1 P3 green + W2 lint clean)
- [x] attribution gate over commit messages and bodies = 0 (23:48Z: commits c65abdf79..pr5/09 grep = 0; issue+PR bodies grep = 0)
- [x] 9 issues created 2026-11-10T00:28Z — #1799 f1, #1800 f2, #1801 f3, #1802 persist, #1803 far-validator, #1804 starvation, #1805 lag-feedback, #1806 epoch-drain, #1807 sealed-tx (assignee grantkee, labels per table A, no leftovers); NOTE: opened by a dry-run bug in w3/create_issues.sh (lesson recorded), before PASS 2 — #1802 body must be replaced by `gh issue edit 1802 --body-file` once PASS 2 lands; map tasks/bench5-issue-map.json
- [ ] staging pushed: c65abdf79 → refs/heads/staging/benchmark-obs-2026-11
- [ ] ten heads pushed `--atomic` under table-B names; remote shas verified
- [ ] 10 PRs opened 00→09 (ready, assignee grantkee, labels); `{{ORDER}}`/`{{PR:prev}}` filled by `gh pr edit`; `gh pr list --base` = 10; pr.yaml visible
- [x] `git merge-tree` dry-run of origin/main (c2fffa5f2) into pr5/09 (22:19Z): ONE content conflict, crates/tn-reth/src/error.rs

## W4 — persist root cause (parallel)
- [x] I-a gcloud reads (orchestrator; 21:58Z: bench 3+4 same image v20261024 + kernel 7.0.0-1014-gcp, bench 5 v20261105 + 7.0.0-1017-gcp; kernel from Ops Agent syslog, serial console not in Logging): ubuntu-2404-lts-amd64 image publish dates vs deploys 11-03 19:23Z / 11-05 08:05Z / 11-07 15:06Z; serial-console "Linux version" per bench instance; Monitoring disk write_bytes/ops per instance per blast window (3 runs) → benchmark/private/bench5-r20261107-1504/I-B2/gcp.md
- [x] I-b Prometheus replay + sampler CSVs (U-PERSIST-a, ≈ 22:03Z) → I-B2/series.md (commit s ≈ 1.0 ms/MB device bytes, r 0.99; bench 3 = bench 5 signature at matched tx/output; bench 4 diverged in minute 5 when re-reads (page-cache pressure) began; write size 230 → 30 KB; bench 5 nodes also dropped late in the run)
- [x] I-c libmdbx writeback probe on xerxes (U-PERSIST-c): crate /home/drtnarg/coding/telcoin/mdbx-writeback-probe built + smoke DONE ≈ 22:10Z (I-B2/probe-smoke.md: large-folio cache → 3.5× device bytes, ~107 KB ops, 2× commit time; order-0 cache → 1.00×; no-WRITEMAP pwrite path → 1.00× at the device; libmdbx already sets MADV_NOHUGEPAGE; MADV_RANDOM covers only the first VMA); full run GO given 22:12Z (+ arm 6 cgroup MemoryMax=2G) → I-B2/probe.md — FULL RUN DONE 22:43Z (9 arms) + 7 re-run/extra arms 23:58-00:16Z (orchestrator, quiet machine after the peer session's `make attest` ended 23:55Z): 6 GB WRITEMAP read-all 1.70× and 3.76× median (WIDE), 2 GB 14.5×, memcg/cold/no-WRITEMAP 1.00×; probe.md fold-in by U-PERSIST-c2 (launched 00:25Z) — probe.md FINAL (265 lines, U-PERSIST-c2 done 00:40Z; 6 GB read-all 1.70×/3.76× median, scatter-dependent 1.05-17.4×; 2 GB 14.5×; order-0 arms 1.00×; "prefault off" refuted)
- [x] I-d synthesis (U-PERSIST-d, launched ≈ 22:05Z; PASS 1 on gcp.md + series.md, PASS 2 after the probe): I-B2/verdict.md; persist issue text updated; report finding 3 + §6 arms amended; tndb answer recorded; orchestrator posts `gh issue comment` — PASS 2 sent 00:44Z (re-rank proposals, §5 actuals, title decision, report (b1)-(b3); then `gh issue edit 1802`) — PASS 2 DONE 01:00Z (verdict ≈ 85 % whole-folio dirtying, 60 % pressure took bench 4 out; "prefault off" refuted; ranking a-e); #1802 title+body replaced 01:03Z (title 107 chars); report §6 stale prefault sentence fixed by the orchestrator; tn-lmdb write path checked (MAP_SHARED + msync/fdatasync, MADV_RANDOM whole reserve → same exposure, (a) built in)

## W5 — wrap-up (orchestrator)
- [ ] ledger + pr texts get "Opened as #n"; todo.md review section; lessons; memory bench5-main-fixes-run.md updated
- [ ] commit + push devnet-genesis main (no attribution; checkpoints gitignored)
- [ ] final message: PR links in merge order + recipe; issue links; persist verdict; tndb answer; report §6 pointer; submodule answer; bench-6 arms; cautions
