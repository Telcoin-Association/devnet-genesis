# PT-1 — port the e2e scaffold to M

Unit: `PT-1` (node port unit, test code only, opus). Rules: `tasks/bench7-agent-rules.md` ("Node units" and "Test units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-1.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt1`, branch `b7/pt1`, base = the integration head after PT-0 (the orchestrator creates it; `git -C <worktree> log --oneline 45dce8947..HEAD` shows PT-0's commits). Domains: `tn-domain-epoch`. Plan rows: Track N's stack table row 01.

## What this unit delivers

The second head of the staging stack, `test/bench6-e2e-scaffold` (PR 01): the test harness pieces every later e2e test of this stack needs, and nothing of an unported topic.

Source commits on the bench-6 tree (`/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only), in port order:

| # | bench-6 commit | what | files |
|---|---|---|---|
| 1-4 | 38b65ff7b, 4c7e5f032, d1b6b0ac3, b09d65945 | `NodeOverrides` / `FleetOverrides`: per-node and fleet-wide `parameters.yaml` entries and environment for the nodes a test starts | `crates/e2e-tests/src/lib.rs`, `crates/e2e-tests/tests/it/common.rs`, `tests/it/restarts.rs` (see each `git show --stat`) |
| 5 | d91d65d3e | `TN_E2E_PARAMETERS`: entries merged into every node's `parameters.yaml` (how the repo's own e2e sets run with switches on) | `crates/e2e-tests/src/lib.rs`, `tests/it/common.rs` |

M changed `tests/it/restarts.rs` (≈250 lines) and `tests/it/common.rs` (≈101 lines) and added modules (`resync.rs`, `reth_db_migration.rs`, `state_export_import.rs`, the `epochs/` and `sigkill/` directories): start with `git diff 165e3fe01 45dce8947 --stat -- crates/e2e-tests` and read how M's tests start nodes today.
Re-apply the scaffold's intent against M's code: M's own start helpers keep their signatures and behaviour (a test that passes no override starts its nodes exactly as on M, byte-identical `parameters.yaml`); the overrides are an addition.
Anything in those five commits that only served an unported topic (the admission bound, sealed-keep, pipelined persist, tracker drain, MDBX advice, recovery pool) is left out; say what you left out.
Do NOT port `tests/it/{admission,epoch_drain,persist_pipeline,sealed_txs,exec_block}.rs` or add `mod` lines for them: `exec_block.rs` and `epoch_close_forms.rs` belong to a later unit.

M's faucet guard (#1716) and storage v2 (#1834) may change what a test node needs at start (environment, flags, the first-start cost of creating `db/tn-lmdb.dat`): the scaffold must not hide or override those.

Commit footer: `Topic: bench6-e2e-scaffold` on every commit.

## Tests and gates

- `cargo check --locked --all-targets -p e2e-tests` (the package's real name from its `Cargo.toml`), fmt check, clippy for the package, the scaffold's own unit tests (`cargo nextest run --locked -p <package> --lib` or however they are reached without starting nodes; bench 6 had eleven).
- One existing e2e test of M, unchanged, through the lane to show the scaffold breaks nothing: pick the cheapest restart test (`cargo nextest list -p <package>` to see the names; M's Makefile has the lane commands), run it once: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh cargo nextest run --locked -p <package> --test it --run-ignored all -E 'test(<name>)'`.
- One tiny new e2e test only if bench 6's scaffold had one that proves an override reaches a node (a node started with a `parameters.yaml` entry logs it in its `node switches` line; PT-0's machinery has no switch yet, so use a plain existing `Parameters` field such as a header delay, and assert on the written file). If bench 6 proved it by unit test, keep the unit test and add no e2e test.
- `tn-domain-reviewer` (opus) on your diff, domains epoch.

## Hand back

As the rules say, plus: the new shas with the bench-6 sha each came from; what was left out and why; the public surface a later e2e unit uses (type names, constructor and method signatures, the environment variable's grammar) in under 40 lines, written also to `tasks/bench7/briefs/pt1-api.md` (you own that one file in devnet-genesis).
