# Bench 6 — rules for every agent (node units, test units, harness units, generator units, investigations, analysis)

Written 2026-11-10 (xerxes) by the orchestrator, its only writer. Read this file first, then your own brief.
The approved plan is `/home/drtnarg/.claude/plans/i-want-to-run-groovy-grove.md` (read ONLY the rows your brief names).
Tick list: `tasks/plan.md`. Ledger: `tasks/bench6-cherrypick-ledger.md`. Names contract: `tasks/bench6-contract.md`.

## What nobody but the orchestrator does
- No `git push`, no `gh … create/edit/comment/merge/close` (gh reads are fine), no `gcloud`/ssh/docker against anything remote,
  no fleet action, no image build or push. The fleet does not exist while you work: offline only.
- No Claude/Anthropic/AI/agent/tool attribution anywhere: commit messages, code comments, docs, PR or issue drafts. No `Co-Authored-By`.
- One writer per file: touch only the files your brief lists. `tn-node-deployment/` and `common/` are never edited.
  If your change needs a file you do not own, stop that item and say so in the hand-back.
- Never delete anything outside your own scratch directory. Never `git stash`, `git reset --hard`, `git rebase`, `git checkout -- <file>`,
  force operations or branch deletion. Never `rm -rf` with a variable in the path.
- Absolute paths and `git -C <dir>` everywhere; parallel tool calls share the shell cwd.
- **Nothing but the node itself ever opens a live node's MDBX database**: no `mdbx_stat` or other MDBX tool, no second environment
  handle, no `telcoin db …` against a running node's datadir, in code, in harness scripts, in probes or by hand. Any open without
  `NORDAHEAD` flips a bit in the shared lock file that switches the node's prefault writes off for every allocation, which
  produces the write amplification this round is measuring (local probe: 1.00× → 8.7×).

## Repos and worktrees
- devnet-genesis (harness `benchmark/`, `tasks/`): `/home/drtnarg/coding/telcoin/devnet-genesis`.
- telcoin-network integration worktree: `/home/drtnarg/coding/telcoin/telcoin-network-b6`, branch `bench/bench6-2026-11`,
  base **165e3fe01** = `origin/fix/benchmark-obs-review-followups` (PR #1827) on top of the attested staging tip 514bf6687
  (PR #1826: the ten bench-5 PRs + main 9aa1d6139 + the event-gap fix). Agents NEVER edit it; the orchestrator integrates by cherry-pick.
- One node unit = one worktree `/home/drtnarg/coding/telcoin/tn-b6-<unit>` on branch `b6/u-<unit>`, created by the orchestrator.
  Work ONLY there. Never touch `/home/drtnarg/coding/telcoin/telcoin-network` (devnet checkout), `telcoin-network-bench*`,
  `telcoin-network-pr5`, anything under `/home/drtnarg/coding/telcoin/tn-workspace/` (another session's worktrees) or another unit's worktree.
- Generator: `/home/drtnarg/coding/telcoin/tn-transaction-generator`. Site: `/home/drtnarg/coding/telcoin/tn-benchmarks`.
- Design reports (the contract, with the plan's W2a/W2b tables on top where they differ):
  `benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md` (node: §A switches, §B per topic),
  `benchmark/private/bench6-prep/design/design-harness--arms-and-runs.md` (harness, arms, runs, generator),
  `…/bench-5-findings-and-artifacts-inventory.md`, `…/bench-harness--image--publishing-readiness.md`,
  `…/upstream-issues-prs-comparison.md`. Their line numbers were taken at 807ee9ed4; the base is now 165e3fe01: `grep -n` first, always.

## Checkpoint, budget, scratch (every agent)
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-<unit>.md`. On start, read your own checkpoint and
  continue from the first unfinished section. Rewrite it after EACH section (not once at the end) in this shape:
  `status: in-progress | done | blocked`, `updated: <date -u output>`, `completed:` (section — commit sha or "no commit" — one line),
  `remaining:`, `notes:`. If a Write is refused, do not work around it: return the complete text in your final answer.
- Budget: well under 250k tokens. Read large files in ranges after `grep -n`. If you trend past ~180k, finish the current section,
  update the checkpoint and hand back with the exact resume point. Do not explore past your read list; hand back instead.
- Scratch: only `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/32c51110-7507-4447-a3fb-2d90bd31a117/scratchpad/<unit>/`
  (the scratchpad is shared; `/tmp` is a quota-limited tmpfs: nothing over ~200 MB there). Bigger data (snapshot copies, extracts)
  goes under `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/work/bench6-scratch/<unit>/` (gitignored).
- **The session changed again on 2026-11-12: write new scratch ONLY under
  `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/<unit>/`.**
  The `32c51110-…` path above and the older `5182cb11-…` path may be read if they exist; write nothing new there.
- The session changed on 2026-11-11: the scratch path above is the NEW one. Scratch you wrote before that under the old session's
  path (`…/5182cb11-39b0-49d7-92e2-41574ff8f3c2/scratchpad/<unit>/`) may still be read if it exists, but write nothing new there.
- Read `date -u` before writing a time anywhere. Every poll loop has a deadline and a pattern that cannot match itself.
- Prose you write (commit bodies, docs, reports, issue/PR drafts): load the `human-writing` skill first. Markdown: one sentence
  per line in new files; keep an existing file's own wrapping.

## Node units (telcoin-network; `U*` units)
READ FIRST, in this order:
1. Skill tool: `tn-rust-skills`, then the `tn-domain-*` skills your brief names.
2. Your row of the plan's W2a table, the switch table, and your topic's section in the node design report (§B).
3. `/home/drtnarg/coding/telcoin/telcoin-network/.claude/project-context.md` (architecture map, read-only).
4. The files in your row, in ranges.

HARD RULES:
- **Every behaviour change sits behind its switch** (a flat top-level `Parameters` field, `serde(default)`, default = bench-5 behaviour;
  U0a owns `crates/config/src/node.rs`, U0c hands each switch to its component). With every switch at its default the tree must behave as
  the base: block contents, state roots, receipts, gas, timestamps and the consensus pack byte-identical. New log fields and metrics need
  no switch. `crates/consensus/primary/src/consensus_bus.rs` is edited by nobody.
- Code quality: `///` docs on every new item; `pub(crate)` unless needed elsewhere; no `unwrap()`/`expect()` outside tests; never hold a
  lock across `.await`; no HashMap/HashSet iteration on a consensus path; no new dependencies unless your row names them; no CHANGELOG
  edits; document every `unsafe` block; no Clippy suppressions.
- Log lines: explicit `target:`, fixed `key = value` fields, one line per batch/header/certificate/output (never per tx), message text
  exactly as the design says. Metrics: fields on the crate's `#[derive(Metrics)]` struct or `metrics::…!` with the design's exact names;
  histograms end in `_seconds`; static label values. Report every new log message, field and metric name verbatim in your hand-back:
  the harness and the analysis tools parse them.
- Tests travel with the change: the unit tests named in your row (inline `#[cfg(test)]` or the crate's `tests/` as the row says).
  You do NOT write e2e modules (`crates/e2e-tests/tests/it/*.rs`) or proptest suites unless your unit is an `ST-*` unit.
  New tests in a shared test file go at the END, under `// ---- bench6 <topic-slug> ----`.
- Build and test (you run these yourself; the orchestrator re-runs the workspace gates on the integration branch):
  - every compiling cargo call goes through the host-wide slot wrapper:
    `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo <args>`
    (three slots on the host; it blocks until one is free, and also while the orchestrator holds a quiet window for an I/O probe —
    a wait of up to ~45 min there is normal: do not work around it, do not call cargo directly; never kill someone else's build;
    never start a second copy of a running build).
  - environment: `export CARGO_INCREMENTAL=0 RUSTFLAGS="-D warnings -D unused_extern_crates" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 RUST_BACKTRACE=1`
    and `mkdir -p "$PWD/target/tmp" && export TMPDIR="$PWD/target/tmp"`. Your worktree's own `target/` is the target dir (never a shared one).
  - package-scoped only: `cargo check --locked --all-targets -p <crate>…`; `cargo +$(cat rust-nightly) fmt --all -- --check`
    (the pinned nightly; revert any file the formatter touched that you did not edit);
    `cargo +$(cat rust-nightly) clippy --locked --all-targets --all-features -p <crate>… -- -D warnings`;
    `cargo nextest run --locked -p <crate>…` for every package you touched (whole package, not a name filter), plus each new test by
    name three times if it has timing in it. Never the whole workspace, never `-p e2e-tests`, never `make attest`.
  - known build quirk (pre-existing): `cargo nextest run -p tn-config` or `-p tn-types` ALONE fails to compile `tn-network-types`
    (a serde feature that only appears with tn-reth in the graph). Keep a node-side crate in the graph and filter instead:
    `cargo nextest run --locked -p tn-config -p tn-types -p tn-node -E 'package(tn-config) | package(tn-types)'`.
  - capture the real exit code: `<cmd> > "$LOG" 2>&1; echo "EXIT=$?" >> "$LOG"`, then read the tail. Logs under `<worktree>/target/tmp/`.
  - a test that fails in a package you did not change: run it alone twice, check `git diff 165e3fe01 -- <file>`, report it as
    pre-existing or flaky with the evidence; do not edit unrelated tests.
- Domain review before you commit the final state: spawn one `tn-domain-reviewer` agent (model opus) on your diff with your `domains:`
  list; fix what it finds or record why not. If you cannot spawn agents, say so in the hand-back and the orchestrator runs it.
- COMMITS: you DO commit in your own worktree, staged by path (`git add <paths>`, never `-A`): one commit per logical change, conventional
  subject in the repo's style (`fix(primary): …`, `feat(engine): …`), a 3-8 line prose body with the measured motivation
  (bench 5, run r20261107-1504) and `Refs #<issue>` when your row names one, and the footer `Topic: <slug>` as the LAST line (the slug in
  your brief; it is the cherry-pick index). Every commit compiles alone. Never commit the `tn-contracts` pointer, `tasks/`, `.env`, `target/`.

## Test units (`ST-*`)
- Clock trap: `tn_types::test_genesis()` stamps the current second into the genesis. A test that opens one datadir twice, or
  compares two chains, builds the genesis ONCE and shares it, or uses `tn_types::test_genesis_at(<fixed>)`. A test that passes
  only when no second ticks between two calls is a bug, not a flake.
- `tn-write-e2e` / `tn-write-proptest` skill first. You own exactly the `it/*.rs` module or proptest file in your row.
- e2e runs use fixed ports: **one e2e job on the machine at a time**. Run every `-p e2e-tests` command through
  `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.sh <cmd…>` (it takes the machine-wide lock, waits for a foreign
  attest to end, then runs your command through a build slot). Never run an e2e test any other way.

## Harness and generator units (`H*`; devnet-genesis `benchmark/`, tn-transaction-generator)
- READ FIRST: `tasks/bench4-agent-rules.md`, `tasks/bench4-obs-agent-rules.md` and the "Harness and txgen units" section of
  `tasks/bench5-agent-rules.md` (all of it applies: knob-unset paths byte-identical with a test; bash 3.2 portable; python 3.9 grammar;
  `set -e` + command substitution `x="$(fn)" || x=""`; secrets on stdin only; hygiene: no literal IPv4 except 0.0.0.0/127.0.0.1 and the
  documentation nets, never the GCP project name as a literal, no absolute home paths; `bash -n` + `shellcheck -S warning` + py_compile +
  the 3.9 grammar check; your test module green and the whole suite tail; mutation anchors applied by hand and reported verbatim).
  Then your row of the plan's W2b table and your section of the harness design report.
- A dry run never shares a code path with the live call: the live side-effect sits behind an explicit `[ "$DRY" = "0" ] || return`
  guard on the line before it and the dry branch ends in `return`/`continue`; every script that can create or delete something remote
  gets a shim test (a fake binary on PATH that prints `REACHED` and exits 9; assert zero hits in the dry run).
- A gcloud list-flag value must never start with `^` (it is read as a delimiter spec and the rest is silently ignored).
- Harness agents DO NOT commit (the orchestrator commits per unit group). Generator units (H9): do not commit either; cargo through the
  slot wrapper (`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo <args>`), the repo's own target dir, `cargo test`, `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`.
- The whole-suite gate (`benchmark/tests/gate.sh`, ~25 min) runs only when the orchestrator says so (it must be alone on the host).
  Run your own test module(s) and `python3 -m unittest` for the modules that import what you changed.
- Field and knob names frozen by H0 (`BENCH_*` knobs, `arms/switches.tsv`, the persist CSV header, `manifest.param_arms[]` fields) are
  read, never renamed. Report every new manifest key, CSV column, log tag and knob verbatim in your hand-back.

## Investigations (`I-*`) and analysis units (`A*`, `D1`)
- Read-only on code and on results. Write only under your output directory (`benchmark/private/bench6-prep/<unit>/` for I-units,
  `benchmark/private/bench6-<run>/<unit>/` for analysis units) and your checkpoint. Results live in `benchmark/results/<run>/`
  (r20261107-1504 = bench 5, r20261105-0803 = bench 4, r20261103-1922 = bench 3); copy nothing bigger than you need.
- An archive upload reads `benchmark/results/` in the background until it finishes: do not move, rename or rewrite anything there.
- Every number cites the file (and line or query) it came from. Say plainly what you could not measure. A timing fit is not a mechanism.
- Heavy jobs (Criterion, an I/O probe, a Prometheus replay container) need a go from the orchestrator: write the runbook
  (`run.sh` + what it needs: disk-quiet, CPU-quiet, duration) and hand back; do not start them yourself unless your brief says so.

## HAND BACK (your final answer: a summary, never file dumps)
1. Status (done / partial with the exact resume point / blocked on what), checkpoint path.
2. Node units: branch, base sha, tip sha, `git log --oneline 165e3fe01..HEAD`; files changed with +/- counts; the switch(es) read and where.
   Harness units: files changed with +/- counts (`git -C … diff --stat`).
3. Every new log message / field / metric / manifest key / knob / CSV column, verbatim.
4. Gates: each command, its `EXIT=`, pass/fail counts, the log path. Mutation anchors verbatim (harness).
5. Deviations from the design with the reason; cross-unit needs; decisions you want the orchestrator or the user to make.
