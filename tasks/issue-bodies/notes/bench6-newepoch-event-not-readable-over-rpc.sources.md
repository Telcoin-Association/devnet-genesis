# Sources: bench6-newepoch-event-not-readable-over-rpc

Not for posting. Every claim of the body and where it comes from.

## Measurement (bench 6 e2e, read-only worktree /home/drtnarg/coding/telcoin/tn-b6-u2)

- Test module `crates/e2e-tests/tests/it/epoch_close_forms.rs` (branch `b6/st-epoch-close-forms`, tip 8c1c27764, not pushed); node code = `bench/bench6-2026-11` at 2df831e3c.
- Query: `registry_logs_in_block` lines 998-1004: `eth_getLogs` with `{"address": CONSENSUS_REGISTRY_ADDRESS, "fromBlock": N, "toBlock": N}`; reported on node 0 (doc lines 737-738), not asserted (module doc lines 23-25).
- "30 closing blocks, every answer 0": `tn-b6-u2/target/tmp/st-e-run{3,4,5}.log`, lines matching `closing block <N> <hash> (<k> registry logs by eth_getLogs)`: 10 per run, all `(0 registry logs by eth_getLogs)` (grep -c). Runs 3-5 are the valid runs at 8c1c27764 (`tasks/checkpoint-bench6-ST-E.md` lines 12-14; `tasks/bench6-handoff-2.md` line 152).
- "located each closing block by the four reads, agreed every time": test asserts `final_state` == block where `getCurrentEpoch` turns (lines 807-821), nonce epoch (853, 910), extraData and `parentBeaconBlockRoot` (doc 807-810), `getEpochInfo(E+1).blockHeight - 1` (checkpoint line 22); all four tests passed in runs 3, 4, 5 (checkpoint lines 12-14; handoff line 151). The record is read by `tn_epochRecord` (`crates/e2e-tests/tests/it/common.rs:1567` on M).

## Code on main 45dce8947 (/home/drtnarg/coding/telcoin/telcoin-network-b7)

- No receipt for system calls, by design: `crates/tn-reth/src/evm/block.rs:421-426` ("No receipt is built for a system call, matching Ethereum: the logs it emits reach neither the receipts root, the header `logs_bloom`, nor `eth_getLogs`, and they must not, since adding them would change `receipts_root` and be a hard fork"); `transact_and_commit_system_call` `:427-487` (logs only to `surface_system_call_logs` `:448`); receipts only for transactions `:2033`; root/bloom from receipts `:2057-2061`, `:2105`.
- Between 2df831e3c and M, `block.rs` changed only the receipts-root/bloom computation (same result; refactor + test), not the system-call path (`git diff 2df831e3c 45dce8947 -- crates/tn-reth/src/evm/block.rs`).
- Node-side log: `crates/tn-reth/src/system_calls.rs:415-422` (`info!(target: "engine", event = name, detail = ?event, "{description} emitted registry event")`); module doc `:17-19`; events list doc `:405-407` ("`NewEpoch`, `ValidatorActivated`, `ValidatorExited`, `ValidatorSlashed`, ...").
- Event declaration/emit: `tn-contracts/src/interfaces/IConsensusRegistry.sol:123` (`event NewEpoch(EpochInfo epoch);`), `tn-contracts/src/consensus/ConsensusRegistry.sol:127-129` (emit in `concludeEpoch`, `blockHeight = block.number + 1`); `concludeEpoch` is `onlySystemCall` (:101). Submodule at 10cc12b.
- Other events also emitted outside system calls (hence "when the closing calls emit them" and "the copies emitted in a closing block"): `ValidatorActivated` in the constructor/genesis seeding (`ConsensusRegistry.sol:1654`) and `_activate` (:1180, from `_updateValidatorQueue` :1300); `ValidatorExited` in `_exit` (:1199) from the queue (:1317) and from `_consensusBurn` (:1393); `ValidatorSlashed` in `applySlashes` (:223).
- Docs: `docs/src/epoch-boundaries.md:101` ("System calls are invisible to users. ... Their effects are visible only through state changes (updated balances, committee rotations) and the block header metadata (`extra_data` and `withdrawals` fields)."); `docs/src/rpc-methods/eth/eth_getlogs.md` has no mention of system calls (grep "system call|receipt|NewEpoch|registry|event": only the generic topics line 31).
- extraData: set from `close_epoch` at `crates/tn-reth/src/evm/block.rs:2118`; read/checked `crates/tn-reth/src/evm/config.rs:209-222` (0 or 32 bytes; "empty for a normal block"); payload sets `close_epoch` only for the last batch of the closing output (`crates/tn-reth/src/payload.rs:128-131`).
- Nonce: `crates/types/src/primary/header.rs:255-257` (`((epoch as u64) << 32) | round`); output nonce = leader's (`crates/types/src/primary/output.rs:217-218`); payload uses it (`crates/tn-reth/src/payload.rs:140`).
- `tn_getEpochInfo` ring buffer: `crates/execution/tn-rpc/src/rpc_ext.rs:210-211`; `tn` namespace not public on validators: `rpc_ext.rs:174-180`; `tn_epochRecord` `:186-191`.
- `EpochRecord` fields: `crates/types/src/primary/epoch.rs:22-38` (`committee`, `next_committee`, `parent_hash`, `final_state: BlockNumHash`, `final_consensus`).

## Filing note

By design on main; what is left is documentation (two pages, one NatSpec line). Filed as a short docs issue per the brief. The orchestrator may decide `epoch-boundaries.md:101` already covers enough and not file it.

## Revision after the figure-check (tasks/bench7/figcheck-UI2.md §3), 2026-11-14

Changed sentences and their sources (no new figure):
- Title/H1 "… and the docs do not say how to follow epochs instead" → "The registry's NewEpoch event never reaches eth_getLogs, and the docs do not say so" (83 chars): figcheck error 1 (line 96); `docs/src/epoch-boundaries.md:116-119` already names `extra_data` as the close marker ("The `extra_data` value serves as a public indicator that the epoch closed at this block.").
- New first-paragraph sentence: "This is by design; the ask is two sentences in the docs and a NatSpec line." (coordinator instruction; by design per `crates/tn-reth/src/evm/block.rs:421-426`).
- "The same holds for the other registry events when the closing calls emit them (`ValidatorActivated`, `ValidatorExited`, `ValidatorSlashed`)." → "(among them `ValidatorActivated`, `ValidatorExited`, `ValidatorSlashed`, `ValidatorStakeVersionUpgraded`, `RefundQueued` and `NextCommitteeSizeUpdated`)" (figcheck weak 1, lines 103-104; `RefundQueued` `ConsensusRegistry.sol:287`, `ValidatorStakeVersionUpgraded` `:297` in `_processStakeVersionQueue` called from `concludeEpoch`; `NextCommitteeSizeUpdated` `:1348` in `_updateValidatorQueue`, called from `concludeEpoch` at `:122`). `NextCommitteeSizeUpdated` added because the coordinator listed it; the figcheck verified it.
- "This is by design, and main says so in code: …" → "Main says so in code: …" (the by-design statement moved to the first paragraph).
- Docs sentence → figcheck replacement verbatim (line 98): "`docs/src/epoch-boundaries.md:101` says … and `:116-119` names `extra_data` as the public marker of an epoch close; but neither it nor `docs/src/rpc-methods/eth/eth_getlogs.md` says that the registry's events are never served, and neither names the other reads below."
- `getEpochInfo` bullet → figcheck replacement verbatim (line 106), split into two lines: "read once epoch E + 1 has begun (before that it reads 0)" (`ConsensusRegistry.sol:421`, "Block height is unknowable ahead of time and remains 0"); "The contract keeps only the epochs from three before the current one to two after it, and older requests revert, at the head by `eth_call` and by `tn_getEpochInfo` alike" (`ConsensusRegistry.sol:412-413`: `epoch > current + 2 || (current >= 3 && epoch < current - 3)` reverts; `rpc_ext.rs:210-211`).
- Fix bullet: "and a note on `ValidatorActivated`, `ValidatorExited` and `ValidatorSlashed` that the copies emitted in a closing block are not served either." → "and a note on the other events the closing calls emit." (figcheck weak 1, line 104).
Word count after revision: see hand-back (`wc -w`).
