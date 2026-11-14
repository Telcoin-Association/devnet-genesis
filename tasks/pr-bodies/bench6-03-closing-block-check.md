## Summary

Before a node saves, votes on or publishes an epoch record, it now checks that the record's `final_state` is the block where the epoch-closing calls ran: the closing consensus header's digest as `parent_beacon_block_root`, the record's epoch in the nonce, the 32-byte closing seed in `extra_data`.
It runs wherever a record is built or reused and at every epoch entry; a failing block stops the node.
No switch: this extends main's unconditional stored-record guard (#1834), and a genuine close passes by construction, so blocks, records and votes do not change.
New: an `epoch record published` info line and two counters.

PR 4 of 5 into `staging/benchmark-bench6-2026-11` (merge order: 00, 01, 02, 03, 04).
Stacked on `fix/1804-vote-queue`: this head contains its commits, so the Files tab shows them until that PR merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/6ad315794b8f641f7ce0f2e2b8b24d7322cee6ab...6d8fe775bffa22c36508eb6e62ca034e69492faa (3 commits).
Please merge with 'Create a merge commit' so the next PR's diff collapses.

## Problem

On main at 45dce8947 the #1834 guard stops the node when a stored record's `final_state` differs from its closing block (`crates/node/src/manager/node/close_epoch.rs:1274`), on the stored close path (`:432`) and at every entry (`:590`).
The build path takes the ring tip's number and hash (`:411`), then saves (`:514`) and publishes (`:519`) the record unchecked.
No path compares the block's markers; `final_state` is logged nowhere.
Inferred from code: if a change moved the ring tip off the closing block, every node would save and vote the same wrong record, stopping only at the next entry.

Measured on bench 6's branch (same `final_state` construction): at all 37 closes of [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and r20261112-1520 (no public page), the block that ran the closing calls was the closing output's last block on every node, with one record hash per epoch.
`final_state` itself was not measured: no line carried it.
This is a missing assertion, not an observed fault (#1851).

## Change

- `56841024a` `fix(node): require an epoch record's final_state to be the block where the epoch-closing calls ran`: `closing_block_check` compares, in order, (a) `parent_beacon_block_root` with `final_consensus.hash`, (b) the nonce's epoch, (c) a 32-byte `extra_data`, equal to the shuffle seed when the node holds the boundary header the record commits; the engine's own marking rules.
  Build path: checked before any committee read and `save_record`.
  Stored path: after main's `final_state` compare, which still fails first.
  Entry: against the registry pin, length only.
  An `adiri` build skips (c) for epochs up to 160 (`ADIRI_DUP_BATCH_EPOCH`), where the engine tolerates closing outputs whose last block carries no marker.
  Kept: record contents byte-identical to main, the restored-floor skip, main's guard tests (their fixtures now carry the markers).
- `a9d7c0026` `feat(node): count the close-time base-fee identity check`: `adjust_base_fees` already stops the node when canonical tip + 1 is not the entered epoch's `blockHeight`; now passes count too.
- `6d8fe775b` `fix(node): name what the closing-block halt prevents per path, the re-derive path and an empty ring`: the refusal's `reason` follows the path, a re-derive refusal reports `path=rederived`, an empty ring `check=no_block` (was `beacon_root`); no decision changes.

## What changes for every node

- Per close, one check at the close and one at the next entry, counted in `tn_epoch_epoch_record_closing_block_check_total{result}` (`ok`, `no_block`, `beacon_root`, `nonce_epoch`, `extra_data_length`, `extra_data_seed`); no new read.
- Per record it publishes as its own, the info line `epoch record published` (`epoch`, `final_state_number`, `final_state_hash`, `final_consensus_number`, `final_consensus_hash`, `digest`, `branch` = `built`, `stored_matched` or `stored_restored`).
- Per live close, `tn_epoch_epoch_close_identity_check_total{result}` (`ok`, `mismatch`).

On a failure the node logs at error (target `epoch-manager`) `epoch record final_state is not the block where the epoch-closing calls ran, stopping the node`, with `epoch`, `path` (`built`, `rederived`, `stored`, `entry`), `check`, `reason`, the block, its markers and `final_consensus`, and exits; the error ends `(do NOT delete chain-data: keep the datadir)`.
A restart stops again at the next entry.
One node alone: keep the datadir and, once the cause is known, recover as for main's `final_state` mismatch stop (the execution rebuild in `crates/tn-reth/README.md`).
Every node at one close with one `check`: the engine and the check disagree, and a build without this change runs on the same chain.

Mixed fleet: records, votes, certificates and blocks are byte-identical to main's, so old and new binaries run one chain.

## Testing

- Genuine closes pass: `a_closing_block_the_engine_builds_passes_the_check` (an earlier block of the same output fails), `a_genuine_close_saves_the_same_record_and_logs_it_published`, `epoch_entry_accepts_a_genuine_record_against_the_registry_pin`, `the_restored_floor_skips_the_closing_markers_too`, `the_closing_marker_is_skipped_only_for_adiri_early_epochs`.
- Refusals: `closing_block_check_names_the_comparison_that_fails`, `a_closing_block_without_its_markers_stops_the_build_before_the_save`, `a_stored_record_without_the_closing_markers_stops_the_close`, `epoch_entry_stops_on_a_closing_block_without_the_records_markers`, `an_empty_ring_stops_the_build_as_no_block`, `a_rederived_record_is_refused_as_rederived`, `the_refusal_names_its_path_and_what_the_stop_prevents`.
- This head's first cut (without the previous head's doc commit): `cargo check --locked --all-targets -p tn-node` exit 0; `cargo nextest run --locked --no-fail-fast -p tn-node` 232 passed, 1 skipped.
- Main plus these commits: `cargo clippy --locked --all-targets -p tn-node -- -D warnings` clean, also with `--features adiri`, where the 37 tests of the check, the guard and the counters passed.
- e2e, on an earlier integration build with this PR's first two commits and every switch off: `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12 passed, no halt line.
- Not run: no fleet has run the check (the next benchmark runs it on eleven nodes), and no e2e test makes it fire.

Stack-wide gates: run on the top of the stack before these PRs were opened; results in the stack's last PR.

## Limits and what a reviewer should look at

- False positives, traced in the code with none failing: a restart mid-close, records from peers, a snapshot restore, epoch 0's placeholder, empty and multi-batch closing outputs, leftover outputs, governance changes; the rule matches every engine branch that writes a marker.
  The engine test builds blocks with `TNPayload::new`, not `execute_consensus_output`: empty closing outputs and adiri's tolerance are covered by reading only, until an engine-level test.
- The marker rules live in the engine and in this check, adiri's bound in two crates: changing one side alone stops every node at the same close; a shared predicate would close the adiri half.
- Long-lived networks: a record stored before this check is checked only when read again, and a bad one would stop every node resyncing through it.
  Before adiri runs this build: one full resync with it, or a walk of its stored records through the check.
  Main already stops on a wrong `final_state`; the new exposure is a wrong `final_consensus` or nonce epoch beside a right one.
- Nothing found before opening this PR is left unfixed.

## Related

- Refs #1851: this implements its fix sketch; not `Fixes`: its e2e verification, the markers checked on chain, is planned for the epoch-close tests of `fix/epoch-record-collector-hardening`.
- #1860: main's epoch loop can drop an output under lag; found while checking this path, not caught by this check, fixed separately in `fix/epoch-loop-output-drop`.
- Next: `fix/epoch-record-collector-hardening` builds on this head.
