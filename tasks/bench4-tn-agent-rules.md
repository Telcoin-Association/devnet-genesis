# Bench 4 — rules for every telcoin-network observability agent (U-TN1…U-TN8)

Your worktree: /home/drtnarg/coding/telcoin/tn-bench-<unit> (e.g. tn-bench-tn1) on branch `bench/u-<unit>`, at
e6d85bd68 = origin/main a0d6e6e26 + PR 1783 (V1Lazy, 4 commits). Work ONLY there. Never touch
/home/drtnarg/coding/telcoin/telcoin-network (the devnet checkout) or any other tn-bench-* worktree.

READ FIRST, in this order:
1. Invoke the Skill tool with `tn-rust-skills` (the repo's Rust conventions: docs on every item, no unwrap,
   no locks across .await, no HashMap iteration in consensus paths, metrics patterns, tracing targets).
   Load the matching `tn-domain-*` skill for your crate (consensus → tn-domain-consensus, network-libp2p →
   tn-domain-networking, engine/tn-reth → tn-domain-execution, worker → tn-domain-worker, node/epoch →
   tn-domain-epoch, executor/subscriber → tn-domain-consensus + tn-domain-epoch).
2. /home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench4-design.md — section D2: the
   Conventions paragraph, YOUR unit's row, the "Analysis contract" (the exact message text and field names
   the analysis tools will parse — they are the contract, do not rename them), the log-filter string (your
   targets must be selected by it), and the "Prometheus series" list (your metric names must match).
3. /home/drtnarg/coding/telcoin/telcoin-network/.claude/project-context.md (untracked; architecture map).
4. The files in your row, in ranges (`grep -n` first; line numbers in the design are approximate — re-verify).
5. Pattern references: `crates/engine/src/metrics.rs:52-100` (DebuggingRecorder test pattern); an existing
   `#[derive(Metrics)] #[metrics(scope = "tn_x")]` struct in your crate; an existing `debug!(target: "…", …)`
   call in your crate for the field style.

HARD RULES
- Observability ONLY: no behaviour change, no signature change on public APIs, no new dependencies, no
  changes to consensus timing, admission, retries or error handling. If a measurement would require a
  behaviour change, leave it out and say so in the hand-back.
- `///` docs on every new item; `pub(crate)` unless needed elsewhere; no `unwrap()`/`expect()` outside tests
  (`u64::try_from(..).unwrap_or(u64::MAX)`, `as_millis()` → `u64::try_from(d.as_millis()).unwrap_or(u64::MAX)`);
  never hold a lock across `.await`; no HashMap iteration on a consensus path (use the committee order /
  Vec); `Instant` stamps only (no SystemTime on consensus paths).
- Every new log line: explicit `target:` as the design says, a fixed `key = value` field shape (numbers,
  static labels, bs58 ids via `%id` or `.to_string()` as the surrounding code does; `?err` last), message
  text EXACTLY as in the analysis contract. Levels: debug for per-request lines, info for state
  transitions, warn only where the design says warn.
- Metrics: fields on the crate's `Metrics` struct or `metrics::counter!/histogram!/gauge!` with the exact
  names in the design; label values are static strs or small enums (never unbounded strings except where
  the design names a peer/leader/signer label — those are bs58 ids, bounded by committee size). Histograms
  named `*_seconds` only. Pre-resolve handles (`counter!(…)` returned handle stored on the struct) where a
  call runs > 5/s; a `metrics::counter!()` call inside a hot loop is NOT acceptable.
- Tests: inline `#[cfg(test)] mod tests` in the touched file(s) using
  `metrics_util::debugging::DebuggingRecorder` (snapshot and assert the series/labels you added) and a
  `tracing_test`-style or `tracing::subscriber::with_default` capture for one log line per new message where
  the crate already has such a pattern; keep tests fast (no network, no node start). PR 1783's three tests
  must stay green if you touch network-libp2p: `lazy_negotiation_sync_stream_to_wrong_role_fails_at_open`,
  `test_peer_without_gossipsub_is_banned_under_lazy_negotiation`,
  `test_record_retrieval_lazy_rejection_takes_legacy_fallback`.
- Build: prefix EVERY cargo command with `CARGO_TARGET_DIR=/home/drtnarg/coding/telcoin/telcoin-network-bench/target`
  (a shared, pre-warmed target dir; a build may print "Blocking waiting for file lock" while another unit
  builds — wait, do not kill it; use a 600000 ms timeout or run_in_background for builds). Commands:
  `CARGO_TARGET_DIR=… cargo nextest run -p <crate>` for each touched crate (and `-p tn-primary` if you touch
  anything primary depends on), `CARGO_TARGET_DIR=… cargo +nightly-2026-03-20 fmt --check` (fix with `fmt`),
  `CARGO_TARGET_DIR=… cargo +nightly-2026-03-20 clippy -p <crate> --all-targets --all-features -- -D warnings`
  (if the repo's Makefile defines a clippy target, match its flags). Do not run the whole workspace suite;
  the orchestrator does.
- NEVER run `git add`, `git commit`, `git push`, `git stash`, `git checkout -- <file>`, `git reset`. The
  orchestrator commits with the title in your row. Use `git diff`/`git status` freely.
- Checkpoint: /home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench4-<unit>.md (e.g.
  checkpoint-bench4-U-TN1.md). On start read it and resume from the first unfinished section. Rewrite it
  after EACH section with a `status:` header (in-progress|done|blocked) and the completed-section list. If
  Write is refused, return the text in the final answer.
- Budget: well under 250k tokens; read in ranges; `handler.rs`, `subscriber.rs`, `consensus.rs` are large.
  If you trend past, checkpoint and hand back with the exact resume point.
- Absolute paths and `git -C` everywhere.

HAND BACK (summary, no file dumps): files changed with +/- lines (`git -C <worktree> diff --stat`); the
exact log messages and metric names you emitted (so the orchestrator can diff them against the contract);
the test names added and the nextest/fmt/clippy results (counts, not logs); any contract deviation with the
reason; anything you could not measure without a behaviour change; the proposed commit title (from your
row) and a 3-6 line commit body in plain prose (no attribution lines).
