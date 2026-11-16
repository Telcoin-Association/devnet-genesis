## Summary

Before a node saves, votes on or publishes an epoch record, it now checks that the record's `final_state` is the block where the epoch-closing calls ran: the closing consensus header's digest as `parent_beacon_block_root`, the record's epoch in the nonce, a 32-byte `extra_data`, equal to the closing seed where the node holds the boundary header.
It runs wherever a record is built (at a close, or when a restart re-derives a missing one) and on the three paths where main compares a stored record with its closing block: a record the close reuses, this node's own uncertified record 0 before the close builds it again, and the previous record at every epoch entry.
A failing block stops the node.
No switch: this extends main's unconditional stored-record guard (#1834, #1849), and a genuine close passes by construction, so blocks, records and votes do not change.
New: an `epoch record published` info line and two counters.

PR 4 of 9 in the stack #1862 to {{pr-09}}; it was merged into #1864's branch (`fix/1804-vote-queue`) on 2026-11-16, when the stack was collapsed into #1862, and its Files tab shows this change alone (3 commits); the stack's base is main at 33b727fce.
#1862 now holds the stack's eight changes and targets `main`; {{pr-09}} targets #1862's branch and removes the switches; once it is merged, `main` is merged into that branch and `make attest` runs on the result.

## Problem

On main at 33b727fce the #1834 guard stops the node when a stored record's `final_state` differs from its closing block (`crates/node/src/manager/node/close_epoch.rs:1274`): on the stored close path (`:438`), on this node's own uncertified record 0 before the close builds it again (`:431`, added by #1849) and at every entry (`:596`); a closing block below a snapshot-restored datadir's floor is not compared (`:1280`).
The build path takes the ring tip's number and hash (`:411`), then saves (`:520`) and publishes (`:525`) the record unchecked.
Among the record paths, only the restart re-derive path reads any of the block's markers, the beacon root and the nonce's epoch, to find the boundary header (`:1303-1325`); no path compares them with a record, and `final_state` is logged nowhere when a record is built or reused.
Inferred from code: if a change moved the ring tip off the closing block, every node would save and vote the same wrong record, stopping only at the next entry.

Measured on bench 6's branch (same `final_state` construction): at all 37 closes of [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and r20261112-1520 (no public page), the block that ran the closing calls was the closing output's last block on every node, with one record hash per epoch.
`final_state` itself was not measured: no line carried it.
This is a missing assertion, not an observed fault (#1851).

## Change

- `7e67af7d7` `fix(node): require an epoch record's final_state to be the block where the epoch-closing calls ran`: `closing_block_check` compares, in order, (a) `parent_beacon_block_root` with `final_consensus.hash`, (b) the nonce's epoch, (c) a 32-byte `extra_data`, equal to the shuffle seed when the node holds the boundary header the record commits; the engine's own marking rules.
  Build path: checked before any committee read and `save_record`.
  Stored paths, a reused record and this node's own uncertified record 0: after main's `final_state` compare, which still fails first; both take the seed by the same rule (`closing_seed_for`).
  Entry: against the registry pin, after main's `final_state` compare; (c) by length only, since the seed would need a consensus-store read.
  An `adiri` build skips (c) for epochs up to 160 (`ADIRI_DUP_BATCH_EPOCH`), where the engine tolerates closing outputs whose last block carries no marker.
  Kept: record contents byte-identical to main, and main's floor rule: below the restored floor neither compare runs, at the floor block both do.
  Main's guard tests that reach the new check now build their closing blocks with the markers; `replay_guard_stops_on_an_uncertified_epoch0_record_that_does_not_match` is unchanged.
- `128f4a5d4` `feat(node): count the close-time base-fee identity check`: `adjust_base_fees` already stops the node when canonical tip + 1 is not the entered epoch's `blockHeight`; now passes count too.
- `c2f266b9c` `fix(node): name what the closing-block halt prevents per path, the re-derive path and an empty ring`: the refusal's `reason` follows the path (this node's own record 0 refuses as `path=stored`, with the stored path's reason), a re-derive refusal reports `path=rederived`, an empty ring `check=no_block` (was `beacon_root`); no decision changes.

## What changes for every node

- Per close, one check at the close and one at each entry into the next epoch, counted in `tn_epoch_epoch_record_closing_block_check_total{result}` (`ok`, `no_block`, `beacon_root`, `nonce_epoch`, `extra_data_length`, `extra_data_seed`); no new read.
  A close that finds this node's own uncertified record 0 checks twice, as the stored record and as the record built again, and counts both: the counter counts checks, not closes.
- Per record it publishes as its own, the info line `epoch record published` (`epoch`, `final_state_number`, `final_state_hash`, `final_consensus_number`, `final_consensus_hash`, `digest`, `branch`).
  `branch` is `built` (a re-derived record included), `stored_matched` (a stored record whose block was compared, the restored floor block included) or `stored_restored` (a closing block below the restored floor, not compared).
- Per live close whose epoch-info read succeeds, `tn_epoch_epoch_close_identity_check_total{result}` (`ok`, `mismatch`).

On a failure the node logs at error (target `epoch-manager`) `epoch record final_state is not the block where the epoch-closing calls ran, stopping the node`, with `epoch`, `path` (`built`, `rederived`, `stored`, `entry`), `check`, `reason`, the block, its markers and `final_consensus`, and stops; the error ends `(do NOT delete chain-data: keep the datadir)`.
A restart stops again at the next entry.
One node alone: keep the datadir and, once the cause is known, recover as for main's `final_state` mismatch stop (the execution rebuild in `crates/tn-reth/README.md`).
Every node at one close with one `check`: the engine and the check disagree, and a build without this change runs on the same chain.

Mixed fleet: records, votes, certificates and blocks are byte-identical to main's, so old and new binaries run one chain.

## Testing

- Genuine closes pass: `a_closing_block_the_engine_builds_passes_the_check` (an earlier block of the same output fails in the default build), `a_genuine_close_saves_the_same_record_and_logs_it_published`, `epoch_entry_accepts_a_genuine_record_against_the_registry_pin`, `a_reclose_over_own_record0_counts_the_closing_block_check_twice` (two `ok` for the one close), `the_closing_marker_is_skipped_only_for_adiri_early_epochs`.
- The restored floor: `the_restored_floor_skips_the_closing_markers_too` reuses a block without markers below the floor (`stored_restored`) and passes it at the entry, and refuses the same block at the floor, at the close and at the entry.
- Refusals: `closing_block_check_names_the_comparison_that_fails`, `a_closing_block_without_its_markers_stops_the_build_before_the_save`, `a_stored_record_without_the_closing_markers_stops_the_close`, `own_uncertified_record0_without_the_closing_markers_stops_the_close_before_the_rebuild` (`path=stored` with `beacon_root`, then `extra_data_seed`), `epoch_entry_stops_on_a_closing_block_without_the_records_markers`, `an_empty_ring_stops_the_build_as_no_block`, `a_rederived_record_is_refused_as_rederived`, `the_refusal_names_its_path_and_what_the_stop_prevents`.
- At `c2f266b9c`: `cargo check --locked --all-targets -p tn-node` exit 0 (also at `128f4a5d4`); `cargo nextest run --locked --no-fail-fast -p tn-node` 236 passed, 1 skipped; `cargo +nightly-2026-03-20 fmt --all -- --check` clean.
- `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-node -- -D warnings` clean at `c2f266b9c`, also with `--features adiri`, where the 51 tests of the `close_epoch` and `metrics` modules, the entry test and the identity counter test passed.
- Not run: no fleet has run this head, and no e2e test makes the check fire.
  Bench 7 ran the stack's earlier cut on main at 45dce8947, which carries the check, on 2026-11-15: [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/) and [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/), ten validators at 20,000 IOPS, one run each; #1868 and #1869 report its results.

Stack-wide gates ran before these PRs were opened, on the top of the full stack: `fix/1807-digest-order-hold` at `500e21afa`, 103 commits on main at 33b727fce, carries the code of all eight pull requests (#1862 to #1869).
- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.
- `./etc/ci-lanes.sh clippy`: passed.
- `cargo nextest run --locked --workspace`: 5,624 passed, 149 skipped.
- Every one of the 103 commits compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied).
- `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12 and `make test-e2e-resync` 1/1, once with every switch off and once with the full stack's six switches on.
- `make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time): passed with every switch off and with the six on.
- The 13 e2e tests the full stack adds, three runs each: all passed.
- The three `state_export_import` tests, which restore a node from an exported state: passed.
- Against a later main, c1b1eb9fe (#1859): the top merges without conflict, and the merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-storage` (1,764 passed, 21 skipped).
- Against the main of 2026-11-16, 0554efd4f (#1861): one file conflicts, `crates/node/src/manager/epoch_votes.rs`. #1861 renamed the collector's failure channel and ends a vote round on a forked record with an error; #1866 added the kept signatures to the same functions. In a local trial merge both changes are kept, the drop of a forked record's kept signatures moves in front of #1861's early return, and one test of #1866 expects the fork as an error. The merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-types -p tn-reth -p telcoin-network-cli` (2,175 passed, 17 skipped). The merge itself is made after the stack is collapsed.
- The stack's top is now {{pr-09}}, which removes the switches; the gates of that head are listed in its text.

## Limits and what a reviewer should look at

- False positives, traced in the code with none failing: a restart mid-close, this node's own uncertified record 0, records from peers, the floor block of a snapshot restore, epoch 0's placeholder, empty and multi-batch closing outputs, leftover outputs, governance changes; the rule matches every engine branch that writes a marker.
  The engine test builds blocks with `TNPayload::new`, not `execute_consensus_output`: empty closing outputs and adiri's tolerance are covered by reading only, until an engine-level test.
- The floor block of a snapshot restore is the header the restore imported, whose hash it ties to the certified record's `final_state`, so it carries the source chain's markers; this is traced, not run.
  The three e2e tests that restore a datadir (`test_state_export_import_bootstrap`, `test_state_export_import_idle_epoch`, `test_state_export_import_recovers_recorded_fee` in `state_export_import.rs`) have not run on this head; the stack-wide gates above say whether they ran on the top of the stack.
- The marker rules live in the engine and in this check, adiri's bound in two crates: changing one side alone stops every node at the same close; a shared predicate would close the adiri half.
- Long-lived networks: a record stored before this check is checked only when read again, and a bad one would stop every node resyncing through it.
  Before adiri runs this build: one full resync with it, or a walk of its stored records through the check.
  Main already stops on a wrong `final_state`; the new exposure is a wrong `final_consensus` or nonce epoch beside a right one.
- Nothing found before opening this PR is left unfixed.

## Related

- Refs #1851: this implements its fix sketch; not `Fixes`: its e2e verification, the markers checked on chain, is in the epoch-close tests (`epoch_close_forms.rs`) of `fix/1804-quorum-exec-block`, a later head of the stack: every published record is compared there with the block in which the registry's epoch turned.
- #1860: main's epoch loop can drop an output under lag; found while checking this path, not caught by this check, fixed separately in `fix/epoch-loop-output-drop`.
- Next: #1866 (`fix/epoch-record-collector-hardening`), #1867 (`fix/epoch-loop-output-drop`), #1868 (`fix/1804-quorum-exec-block`) and #1869 (`fix/1807-digest-order-hold`) build on this head, and last {{pr-09}}, which removes the stack's switches.
