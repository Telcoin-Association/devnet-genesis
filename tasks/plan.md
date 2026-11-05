# Plan: bench 4 — main + PR 1783 (V1Lazy) + observability image, all harness defects, rerun, publish, report

Written 2026-11-04 (xerxes). Frozen contracts: `tasks/checkpoint-bench4-design.md`. Live-run checkpoint:
`tasks/checkpoint-bench4-live.md`. No Claude attribution on any commit or PR. Opus agents implement;
subagents never commit.

## Wave 0 — orchestrator setup
- [x] Apply the two project-context plans (devnet-genesis 59→62 lines; telcoin-network new, untracked)
- [x] Worktree `../telcoin-network-bench` on `bench/main-v1lazy-obs-2026-11` = origin/main a0d6e6e26 + PR 1783 ff (head e6d85bd68)
- [x] `tn-contracts` submodule initialised in the worktree (the first `cargo check` failed on the missing artifacts)
- [x] Toolchains: 1.94 (rust-toolchain.toml), nightly-2026-03-20 fmt/clippy present, nextest 0.9.143
- [x] Cold `cargo test --workspace --no-run` warm-up: 400 s, 6.1 GB target (`tasks/bench4-cargo-warmup.log`); 7 unit worktrees `../tn-bench-tn{8,1,2,4,3,6,7}` share that target dir
- [x] Probe gate dry run on the live digest: 12/12 strings, subsecond-from-genesis, 17 s (`tasks/bench4-probe-dryrun.log`)
- [x] `tasks/checkpoint-bench4-design.md` written (frozen contracts)

## Wave 1 — parallel implementation (checkpoints `tasks/checkpoint-bench4-<unit>.md`)
telcoin-network (worktree, branch `bench/main-v1lazy-obs-2026-11`):
- [x] U-TN8 network reqres class + durations
- [x] U-TN1 vote path timing (handler.rs, header_validator.rs, metrics.rs)
- [x] U-TN2 proposer stamps (certifier.rs, proposer.rs)
- [x] U-TN4 engine execute/persist/commit split
- [x] U-TN3 leader schedule logging
- [x] U-TN6 worker batch denials
- [x] U-TN7 epoch record signers
- [x] U-TN5 rejoin blockers + mode transitions (after U-TN1)
devnet-genesis:
- [x] U-H1 pull-lib.sh (new) + test_pull_logs
- [x] U-H2 bench-lib wiring + test_tunnel + certification/admission tests
- [x] U-H3 teardown gates
- [x] U-H4 deploy + config.sh
- [x] U-H5 blast chaos refresh + recovery-schedule refresh
- [x] U-H6 devnet-lib fault kinds + test_iap_retry
- [x] U-H7 finalize (commit 1 intIP, commit 2 FINALIZE_JOBS)
- [x] U-H8 keygen (--pull-only, reuse, report, jobs)
- [x] U-H9 network-config (trust flag, fast path, jobs)
- [x] U-H10 report + .gitignore + hygiene
- [x] U-H11 mutations + CI + README (28/28 anchors killed)
tn-transaction-generator:
- [x] U-H12 collector series + --end

## Wave 2 — freeze, verify, review, commit, build
- [x] Integration branch assembled: 8 commits e6d85bd68..1374afa17 (unit branches bench/u-tn*); hand-back log tasks/checkpoint-bench4-wave1.md
- [x] Harness suite: 673 tests, only the known slow-bundle env failure (tasks/bench4-integration-suite.log)
- [x] Workspace fmt/clippy clean, nextest 3884 passed/70 skipped on 1374afa17 (tasks/bench4-tn-workspace-verify.log)
- [x] Reviews: tn-review 0 BLOCKING (S1 buckets fixed in 496ebefb5); review-A 1 BLOCKING (finalize NC_CTX trust flag) fixed; review-B 1 BLOCKING (teardown ok=- gate) fixed; all SHOULDs fixed
- [x] Final harness suite 704 OK (tasks/bench4-final-suite.log); offline checks clean; dry-run plan DRY_RC=0 (tasks/bench4-dryrun-plan.log)
- [x] Commits: devnet-genesis 9 of 11 groups (5be1e62..e5b35ab); txgen 6f2aae6; telcoin-network 9 commits pushed (496ebefb5)
- [ ] Finalize commits 1+2 after the baseline-fixture fix; tasks commit
- [x] Image adiri:bench-main-v1lazy-obs-20261104 @sha256:f6922184… built, pushed, probed (12/12, subsecond-from-genesis)
- [x] V-off: cargo nextest workspace, fmt, clippy; bash -n + shellcheck; check-bash32; unittest; check_mutations; txgen tests
- [x] tn-review on the telcoin-network branch (diff vs origin/main minus PR 1783)
- [x] U-review on devnet-genesis (byte-identical knob-unset paths of the three root drivers)
- [x] Blocking fixes → V-off again
- [ ] Commits: telcoin-network 8 on the branch; devnet-genesis per unit group; txgen 1
- [x] Push `bench/main-v1lazy-obs-2026-11`; image build + push; digest; probe by digest
- [x] Dry-run deploy plan text (`--with-contracts`, no `--yes`), `--print-prestart`

## Wave 3 — live run (D5)
- [ ] preflight → deploy `--to 12` → idle ≥ 10 min → `--from 13 --to 15` → teardown → `--reindex`

## Wave 4 — analysis (A1, A2, A3, A4n, A4o, P-backfill, A5 report)
- [ ] `tasks/bench4-report-<run>.md` + `benchmark/private/followups.md ## <run>`

## Wave 5 — publish
- [ ] backfill json, make_bundle, tn-benchmarks build/scrub/tests, commit+push, HTTP 200
- [ ] devnet-genesis push main; txgen push main; draft PR on telcoin-network (or `tasks/pr-bench-observability.md`)
- [ ] memory `bench4-main-v1lazy-obs-run.md` + MEMORY.md; `tasks/todo.md` review section; `tasks/lessons.md`
