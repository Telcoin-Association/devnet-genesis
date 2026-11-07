# Bench 5 — rules for every implementation agent (telcoin-network units, txgen units, harness units)

Written 2026-11-06 (xerxes). Contracts: tasks/checkpoint-bench5-design.md (the orchestrator is its only writer).
Plan checklist: tasks/plan.md. Ledger: tasks/bench5-cherrypick-ledger.md.

## Repos and worktrees
- telcoin-network integration worktree: /home/drtnarg/coding/telcoin/telcoin-network-bench5, branch `bench/main-fixes-2026-11`
  = origin/main 4bf4604d2 (2026-11-06, "Merge commit from fork" = GHSA-8fj9 sync-peer fix, on top of PR 1783 7527b15c0)
  + the nine observability commits cherry-picked (77539d77d..3a721a1b6). Agents NEVER edit it; the orchestrator integrates.
- One unit = one worktree /home/drtnarg/coding/telcoin/tn-bench5-<unit> on branch `bench5/u-<unit>` (created by the
  orchestrator from the integration head of the unit's wave). Work ONLY there. Never touch
  /home/drtnarg/coding/telcoin/telcoin-network (the devnet checkout), telcoin-network-bench (bench 4) or another unit's worktree.
- devnet-genesis: /home/drtnarg/coding/telcoin/devnet-genesis (harness, `benchmark/`), tn-transaction-generator:
  /home/drtnarg/coding/telcoin/tn-transaction-generator, tn-benchmarks: /home/drtnarg/coding/telcoin/tn-benchmarks.
- The fleet does not exist. No gcloud against a real project, no ssh, no docker against a remote host. Offline only.

## READ FIRST (telcoin-network units), in this order
1. Skill tool: `tn-rust-skills`; then the `tn-domain-*` skills your unit row names.
2. tasks/checkpoint-bench5-design.md: the Conventions paragraph, YOUR unit's row(s) (the exact sites, fields, metric
   names, log message texts and test names — they are the contract the analysis tools parse; do not rename them), and the
   "shared files / insertion points" section.
3. /home/drtnarg/coding/telcoin/telcoin-network/.claude/project-context.md (architecture map; untracked, read-only).
4. The files in your row, in ranges. Line numbers in the design were verified at 496ebefb5 on 2026-11-05 and the base has
   moved (GHSA-8fj9 touched primary/src/network/{mod,sync_codec}.rs and tests/network_tests.rs): `grep -n` first, always.

## HARD RULES (telcoin-network)
- Scope: exactly your unit's rows. **No consensus-observable change outside §F1/§F3**: block contents, state roots,
  timestamps, gas, receipts and the consensus pack must stay byte-identical for every engine/tn-reth/worker/batch-builder
  change; the differential tests named in your row pin it. If a measurement or an optimisation would need a behaviour
  change outside your contract, leave it out and say so in the hand-back.
- `///` docs on every new item; `pub(crate)` unless needed elsewhere; no `unwrap()`/`expect()` outside tests
  (`u64::try_from(d.as_millis()).unwrap_or(u64::MAX)`); never hold a lock across `.await`; no HashMap/HashSet iteration on a
  consensus path; `Instant` stamps only on consensus paths; no new dependencies; no CHANGELOG edits (generated).
- Log lines: explicit `target:` as the design says, fixed `key = value` field shape (numbers, static labels, bs58 ids via
  `%id`; `?err` last), message text EXACTLY as the contract; one line per batch/header/certificate/output, never per tx.
  Levels: debug for per-request lines, info for state transitions and the `consensus::metrics` stage lines, warn only where
  the design says warn; whole-struct `?dump` fields only at trace under `engine::dump`/`engine::evm`.
- Metrics: fields on the crate's `#[derive(Metrics)] #[metrics(scope = "tn_x")]` struct or `metrics::counter!/histogram!/
  gauge!` with the exact names in the design; histograms end in `_seconds`; label values are static strs or small enums
  (bs58 ids only where the design names a peer/leader label); pre-resolve handles where a call runs > 5/s; nothing inside a
  per-tx loop. The sub-ms bucket hunk in `crates/tn-metrics/src/recorder.rs` stays as it is.
- Tests travel with their change: inline `#[cfg(test)] mod tests` (DebuggingRecorder for metrics, `tracing::subscriber::
  with_default` capture for one log line per new message where the crate already does that), the differential/proptest/
  e2e tests your row names. Keep unit tests fast (no network, no node start) unless your row is an e2e row.
- Build: prefix EVERY cargo command with `CARGO_TARGET_DIR=/home/drtnarg/coding/telcoin/telcoin-network-bench/target`
  (shared, warm). "Blocking waiting for file lock" = another unit is building: wait, never kill it; use a 600000 ms timeout
  or run_in_background. Per touched crate: `cargo nextest run -p <crate>` (+ `-p tn-primary` if primary depends on your
  change), `cargo +nightly-2026-03-20 fmt --all -- --check` (fix with `fmt`), `cargo +nightly-2026-03-20 clippy -p <crate>
  --all-targets --all-features -- -D warnings`, and `RUSTFLAGS="-D warnings -D unused_extern_crates" cargo check -p <crate>
  --all-targets`. Never the whole workspace suite; the orchestrator runs it.
- COMMITS: you DO commit in your own worktree (the ledger needs one commit per topic row), with exactly the title in your
  row, a 3-8 line prose body with the measured motivation, `Refs #<n>` when your row names an upstream issue, and the
  footer line `Topic: <slug>` (your row's slug) as the LAST line. No Co-Authored-By, no "Generated with", no AI attribution
  of any kind, ever. Never `git push`, `git rebase`, `git reset --hard`, `git stash`, `git checkout -- <file>`; never touch
  another branch. Every commit must compile alone (`cargo check -p <crate> --all-targets` at each commit when a unit has
  several commits).
- Checkpoint: /home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench5-<unit>.md. On start read it and resume
  from the first unfinished section. Rewrite it after EACH section with a `status:` header (in-progress|done|blocked) and
  the completed-section list (commit shas once they exist). If Write is refused, return the text in the final answer.
- Budget: well under 250k tokens; read in ranges (`handler.rs`, `subscriber.rs`, `proposer.rs`, `state.rs`, `lib.rs` in
  engine are large; `grep -n` first). If you trend past, checkpoint and hand back with the exact resume point.
- Scratch files only under the session scratchpad in a subdirectory named after your unit (the scratchpad is shared).
- Absolute paths and `git -C <dir>` everywhere; parallel tool calls share the shell cwd.

## Shared files in one wave — named insertion points (so cherry-picks collide only in trivially mergeable places)
- `crates/consensus/executor/src/subscriber.rs`: Wave 1a — U-F1 owns `fetch_batches`, `run` and the output path; U-F3a1 owns
  `rejoin_ready`, `RejoinBlocker` and the promotion site. New tests go at the END of the existing `#[cfg(test)] mod tests`
  block inside a nested `mod <unit_slug> { use super::*; … }` (`mod f1_commit_lag`, `mod f3_rejoin`).
- `crates/consensus/primary/src/metrics.rs` and `crates/consensus/executor/src/metrics.rs`: new fields go at the END of the
  relevant metrics struct, preceded by `// bench5 <topic-slug>`; mirror/registration tests extended in place (one assert per
  new series, appended at the end of the existing test).
- `crates/consensus/primary/src/tests/network_tests.rs`: new tests appended at the END of the file under a
  `// ---- bench5 <topic-slug> ----` comment; the paused-clock test near `:2033` is edited in place by U-F3b2 only.
- `crates/consensus/primary/src/network/handler.rs`: Wave 1a — U-F3a1 owns the gossip-certificate path (`:341-355`) only.
  Wave 1b — U-F3b1 owns `behind_consensus`; U-F3b2 owns `vote()` and the vote-path errors.
- `crates/consensus/primary/src/consensus/state.rs`: Wave 1a — U-F1 owns `:583-700` (the commit path). Wave 1b — U-L2a adds
  the `subdag sequenced` line at the F1-changed site and the `certificate committed` fields at `:228-245`.
- `crates/engine/src/lib.rs`, `payload_builder.rs`, `metrics.rs`: Wave 1a — U-E1 only (E1, E2, E3, L5). Later waves: U-E2a (E4),
  U-E2b (E5) in sequence.
- `crates/tn-reth/src/env/execution.rs`: U-E1 (E2 laps, per-tx clone) in 1a; U-E2a (E4) and U-E2b (E5) later, in sequence.
- `crates/node/src/manager/{node,run_epoch,start_epoch}.rs`: U-E1 (E3 channel type) in 1a; U-F3b1 (`start_epoch.rs` sticky
  boundary) in 1b.
- Harness: `benchmark/config.sh` knob block is written by the ORCHESTRATOR only (already present: BENCH_LIGHT_LOAD*,
  BENCH_WINDOW, BENCH_NODE_DB_SYNC_MODE, BENCH_LOG_RATE_WARN_MB_MIN, BENCH_LOG_TRANSFER, BENCH_TEARDOWN_RECERTIFY); units
  READ them. `benchmark-blast.sh` + `blaster-startup.sh` + the step-13 LOG_RATE check: U-H1 only. `benchmark-deploy.sh` +
  `bench-lib.sh` (`bench_prestart_script`): U-H2 only. `benchmark-teardown.sh` + `pull-lib.sh`: U-H3a (D34, B9, A10) first,
  U-H3b (bucket transfer) on top of U-H3a's diff. `benchmark/report/*.py`: U-H4b only; `benchmark/tools/stage-latency.py`:
  U-H4a only. README, `check_mutations.py`, `test_repo_hygiene.py`, CI workflow: U-H5 only, last.

## Harness and txgen units (devnet-genesis, tn-transaction-generator)
Everything in tasks/bench4-agent-rules.md and tasks/bench4-obs-agent-rules.md applies (sole writer of your row's files;
knob-unset paths byte-identical with a test; bash 3.2 portable; python 3.9 grammar; `set -e` + command substitution
`x="$(fn)" || x=""`; secrets on stdin only; hygiene: no literal IPv4 except 0.0.0.0/127.0.0.1 and the documentation nets,
never the GCP project name as a literal, no absolute home paths; `bash -n` + `shellcheck -S warning` + py_compile + the 3.9
grammar check; your test module green and the whole suite tail; mutation anchors applied by hand and reported verbatim),
with these differences for bench 5:
- Harness/txgen agents DO NOT commit (the orchestrator commits per unit group); telcoin-network agents DO (see above).
- Your contract is tasks/checkpoint-bench5-design.md §D-IV (harness) or §LAND "Generator" (txgen T1-T3).
- txgen: `cargo test` in /home/drtnarg/coding/telcoin/tn-transaction-generator (its own target dir), `cargo fmt --check`,
  `cargo clippy --all-targets -- -D warnings`; the blaster schema id stays `tn-blast/v2`; new columns are additive and
  column-named; document them in `bench/schema/README.md`.

## HAND BACK (a summary, never file dumps)
Files changed with +/- lines (`git -C <worktree> diff --stat` or the commit stats); the commit sha(s) + title(s) (TN units);
the exact log messages and metric names emitted (so the orchestrator can diff them against the contract); test names added
and the nextest/fmt/clippy/unittest results (counts, not logs); mutation-anchor lines verbatim (harness); contract deviations
with the reason; cross-unit needs; anything left undone with the exact resume point.
