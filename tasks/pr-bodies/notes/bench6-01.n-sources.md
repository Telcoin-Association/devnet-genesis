# Sources: bench6-01-e2e-scaffold.md on today's main (not posted)

Main = 33b727fcea4f6004d4b0cd2bd7923258e081e94f (`33b727fce`). Head `test/bench6-e2e-scaffold` = local mark `b7/n2-01` = 87be966514802e039b7f7ba87452bfc7e2e57f5d, 8 commits on head 00 (`b7/n2-00` = b29d59bef7b46220aad81ddaeb48101f197a14b4), read in `/home/drtnarg/coding/telcoin/tn-b7-p2`.
`git range-diff feat/bench6-switches-obs..test/bench6-e2e-scaffold b7/n2-00..b7/n2-01`: all eight `=` (identical patches).
Statements not listed here are unchanged from the earlier note `bench6-01-e2e-scaffold.sources.md`; the code they rest on did not move: head 01 edits `crates/e2e-tests/src/lib.rs`, `tests/it/common.rs`, `tests/it/restarts.rs` (`git diff --stat b7/n2-00 b7/n2-01`), and main changed none of them between 45dce8947 and 33b727fce (`git diff --stat 45dce8947 33b727fce -- crates/e2e-tests/` lists only README.md, resync.rs, upgrade.rs).

## What changed and why

| text | source |
|---|---|
| "PR 2 of 6", merge order with `fix/epoch-loop-output-drop` last | `tasks/bench7/briefs/w-n.md` "What happened" |
| compare link `b29d59bef…87be96651` (full shas), 8 commits | `git rev-parse b7/n2-00 b7/n2-01`; `git log --oneline b7/n2-00..b7/n2-01` = 8 lines |
| eight ids in "Change" and `87be96651` in Limits, exact subjects | `git log --reverse --format='%h %s' b7/n2-00..b7/n2-01`, matched by subject to the old series; all ancestors of b7/n2-06 (idcheck.sh: OK) |
| On main at 33b727fce every node gets the same `parameters.yaml`, `lib.rs:356`, `:388` | `git show 33b727fce:crates/e2e-tests/src/lib.rs` 356 and 388: `std::fs::copy(shared_genesis_dir.join("parameters.yaml"), dir.join("parameters.yaml"))?;` |
| `start_validator_with_env` at `common.rs:527` | `git show 33b727fce:crates/e2e-tests/tests/it/common.rs` 527 `pub(crate) fn start_validator_with_env(` |
| `restarts.rs:1368-1388`, `:2074` | at 33b727fce 1368 `fn node_log_lines(`, 1388 `async fn wait_for_node_log_line(`, 2074 `fn log_field(` |
| the `TN_BIN_PATH_PREV` nodes of `upgrade.rs`, `reth_db_migration.rs`, `resync.rs` (Limits; main changed upgrade.rs and resync.rs) | at 33b727fce each calls `e2e_tests::get_previous_telcoin_network_binary()` (upgrade.rs:920, reth_db_migration.rs:86, resync.rs:798) and starts nodes through `start_validator` / `start_named_observer` (at b7/n2-01: upgrade.rs:246, :264, :420; resync.rs:387, :443, :596; reth_db_migration.rs:267, :298), which head 01 routes through the override path |
| "as `upgrade.rs` requires" (built at another commit) | at 33b727fce `upgrade.rs` `Binaries::new` (from line 175): `ensure!(prev_sha != current_sha, "TN_BIN_PATH and TN_BIN_PATH_PREV both report commit …")` |
| `db load-state` uses no `Parameters` field on main | `git grep -n "Parameters\|parameters()\|\.parameters" 33b727fce -- crates/telcoin-network-cli/src/db.rs crates/telcoin-network-cli/src/db/`: no hit (#1849 changed db.rs and added db/load_state_marker.rs) |
| at 17327280d: `cargo check --locked --workspace --all-targets`, warnings denied, builds the e2e crate: clean | `tasks/bench7/gate-n1-02.log` line 2 (`rc=0`); gate script `RUSTFLAGS="-D warnings -D unused_extern_crates"`; the check log `/home/drtnarg/coding/telcoin/tn-b7-pcc/target/tmp/n1-02-check.log:43` `Checking e2e-tests v0.1.0`, `:45` Finished; `e2e-tests` is a workspace member (`Cargo.toml` members, line 26 of the block) |
| "The e2e library's unit tests were not run on today's main" | the gate's nextest packages are tn-config, tn-types, tn-node, tn-primary, tn-network-libp2p (gate script), no `-p e2e-tests` |
| earlier cut, head's seventh commit: fmt clean, check passed, 160 passed | `tn-b7-stack/target/tmp/head01-9ef55c989.log` (`CHECK EXIT=0`, `160 tests run: 160 passed, 0 skipped`, `TEST EXIT=0`); fmt EXIT=0 recorded in `tasks/bench7-cherrypick-ledger.md:38`; 9ef55c989 = `test(e2e): say when a start drops parameters.yaml entries of the previous start`, 7 commits over 8a42fec57 |
| 16 library tests (count re-checked at the new head), doctest, clippy, on main at 45dce8947 before stacking | `git show b7/n2-01:crates/e2e-tests/src/lib.rs` 16 `#[test]`; `tn-b7-pt1/target/tmp/r2-clippy.log` EXIT=0, `r2-libtests.log` `16 tests run: 16 passed`, `r2-doctests.log` `1 passed` |
| first five commits: the two e2e tests passed, variable unset | `tn-b7-pt1/target/tmp/e2e-observer.log` (`2 tests run: 2 passed`, EXIT=0; both PASS lines) |
| first callers: `epoch_record_walk.rs` of head 04, through the helpers that head adds | `git grep -l "FleetOverrides\|start_validator_with_overrides\|start_nodes_with_overrides"`: only common.rs at b7/n2-01, -02, -03; at b7/n2-04 also epoch_record_walk.rs and fleet.rs; fleet.rs added by ff877fb0e (`git log --diff-filter=A b7/n2-03..b7/n2-04`) |
| Related: `fix/epoch-loop-output-drop` added to the heads stacked on this; `fix/1804-quorum-exec-block` uses `FleetOverrides` | the six-PR merge order (brief); `b7/n2-05:crates/e2e-tests/tests/it/exec_block.rs:18`, `:203`, `:588` |
| Stack-wide gates line | brief item 5 |

## Dropped against the earlier text

- The old ids `6ea3dec7b` (now "the head's seventh commit", on the earlier cut) and `48dae6a5f`, and the stack-wide gate paragraph on `91a15e223` (brief item 5).

## Not verified at the new tip

- fmt, clippy, the 16 library tests, the doctest and the two e2e tests on today's main: no log; stated for the earlier cut only.
