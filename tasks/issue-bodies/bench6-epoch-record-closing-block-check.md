# An epoch record is saved and voted with no check that its final_state is the block that ran the closing calls

## What happens

An epoch record's `final_state` is meant to be the block where the epoch-closing calls ran (`applyIncentives`, `applySlashes`, `concludeEpoch`).
On main at 45dce8947 that holds by construction, and the benchmark found no close where it did not: this is a missing assertion, not an observed fault.

Since #1834, main stops the node when a stored record's `final_state` differs from its closing block, on the stored close path and at every epoch entry that finds the previous record stored; a closing block at or below a snapshot-restored datadir's floor is not compared.
Still missing:

- The build path checks nothing: `write_epoch_record` takes the ring tip's number and hash, saves the record and hands it to the vote collector.
- No path compares the closing block's markers with the record: `parent_beacon_block_root` against `final_consensus`, the nonce's epoch, and the 32-byte `extra_data` against the output's seed. Only the restart re-derive path reads the first two.
- `final_state` is logged nowhere when a record is built or reused.
- No test asserts the property.

If a later change moved the ring tip off the closing block, every node would save the same wrong record, start voting on it, and stop only at the next entry (inferred from code); a build-path check stops it before the save.

## Evidence

We checked every close of three bench-6 runs on ten validators and one observer: [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) (20,000 IOPS), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) (50,000 IOPS) and an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public page).
The build was `bench/bench6-2026-11` at `2df831e3c`, not main; it builds `final_state` the same way, and its stored-record check was a switch.

For each node and close, the block that logged `closing epoch emitted registry event` for `NewEpoch`, logged while that block runs `concludeEpoch`, was the closing output's last block, the ring entry `write_epoch_record` reads, the next epoch's `blockHeight - 1` and state pin, and the same number and hash on every node.
That held at all 37 closes on every node that closed them: 25 closes and 271 node-closes in r20261112-1520, 6 and 66 in each of the others, validator-05's replay after its restart included.
Every vote, quorum line and fetched record carried one record hash per epoch, and no node logged a final-state halt, an identity error or a re-derive line.
The two adaptive-form runs, [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) and [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/), showed one record hash and one closing block on all eleven nodes at every close.

Not measured: `final_state` itself, which no log line, metric or export carries.
That it is this block is inferred from the code and the single record hash per epoch, whose digest covers `final_state`.

## Where in the code

All on main at 45dce8947.

- `crates/node/src/manager/node/close_epoch.rs:411` samples `latest_execution_block_num_hash()`; with no stored record the committees are read at that block (`:476-490`), the record is built (`:505-512`), saved (`:514`), persisted (`:518`) and published (`:519`), where a member signs its vote (`crates/node/src/manager/epoch_votes.rs:503-525`). Nothing in between looks at the header.
- The guard, `check_stored_record` (`close_epoch.rs:712-749`, comparing in `check_stored_final_state`, `:1265-1284`), compares number and hash only (`:1274`), skips a closing block at or below the datadir's restored-state floor (`:1271`), and on a mismatch counts `tn_epoch.final_state_mismatches_total`, logs an error and stops the node (`:733-746`). It runs on the stored close path (`:430-433`) and at entry (`:590-596`, from `run_epoch.rs:238`, against the `blockHeight - 1` header read at `run_epoch.rs:152`).
- The markers: beacon root and nonce on every block of an output (`crates/tn-reth/src/payload.rs:168-170`, `:140`), the seed on the closing output's last block (`payload.rs:129-134`), stored as `extra_data` (`crates/tn-reth/src/evm/block.rs:2118`). Among the record paths only `boundary_consensus_digest` (`close_epoch.rs:1294-1316`) reads any, on the re-derive path.
- Tests: the guard's unit tests (`close_epoch.rs:2111-2278`) use a header with no markers (`header_of`, `:2045`). The e2e `assert_epoch_records_verify` (`crates/e2e-tests/tests/it/common.rs:1600-1639`) checks that each node holds the block at `final_state`; any block all nodes agree on passes.

## What a fix could look like

One pure function: is this sealed header the closing block of epoch N for this record?
(a) `parent_beacon_block_root == final_consensus.hash`; (b) the nonce's epoch is N; (c) `extra_data` is 32 bytes, equal to the seed when it is at hand.
Run it on the build path, on the ring's sealed header (`crates/consensus/primary/src/recent_blocks.rs:78`), before the committee reads and `save_record`, stopping the node as the guard does; on the stored path after the `final_state` comparison; at entry on `epoch_start_header`, already in hand; and add (c) on the re-derive path.
Skip (c) under `adiri` for epochs at or below `ADIRI_DUP_BATCH_EPOCH` (160, `crates/types/src/forks.rs:71`).
No switch: it extends an unconditional guard, and a genuine close passes every comparison, so blocks and records do not change.
Add an info line per record built or reused (epoch, `final_state`, `final_consensus`, digest, path) and a counter by result.

A fix along these lines is in preparation and will be proposed as a PR against the staging branch.

## How to verify

- Unit: a genuine closing-header helper for the guard tests, existing assertions kept; each of (a), (b), (c) failing alone stops the build path with nothing saved or published; an earlier block of the closing output as ring tip; a matching `final_state` with a wrong marker on the stored and entry paths.
- e2e: `assert_epoch_records_verify` also checks the block's 32-byte `extraData`, `parentBeaconBlockRoot == final_consensus.hash` and `getEpochInfo(N+1).blockHeight == final_state.number + 1`.

## Related

- {{epoch-record-collector-gaps}}: a record the network leaves uncertified, or certifies differently from a node's own.
- #1806: late members of a loaded close find the record certified and take the stored path, which compares `final_state` but no marker.
