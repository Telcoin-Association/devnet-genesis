# The registry's NewEpoch event never reaches eth_getLogs, and the docs do not say so

## What happens

`IConsensusRegistry` declares `event NewEpoch(EpochInfo epoch)` (`tn-contracts/src/interfaces/IConsensusRegistry.sol:123`), and `concludeEpoch` emits it in every epoch-closing block (`tn-contracts/src/consensus/ConsensusRegistry.sol:127-129`).
It cannot be read over RPC: `eth_getLogs` for the registry's address over the closing block returns an empty list, and no receipt carries the log, so a tool or an indexer that follows epochs by event sees nothing.
The same holds for the other registry events when the closing calls emit them (among them `ValidatorActivated`, `ValidatorExited`, `ValidatorSlashed`, `ValidatorStakeVersionUpgraded`, `RefundQueued` and `NextCommitteeSizeUpdated`).
This is by design; the ask is two sentences in the docs and a NatSpec line.

Main says so in code: the epoch-closing calls run as system calls, which build no receipt, "matching Ethereum".
Their logs reach neither the receipts root, the header `logs_bloom` nor `eth_getLogs`, and adding them "would change `receipts_root` and be a hard fork" (`crates/tn-reth/src/evm/block.rs:421-426` on main at 45dce8947).
The node writes each event to its own log instead (`log_registry_event`, `crates/tn-reth/src/system_calls.rs:415-422`: `event=NewEpoch`, target `engine`).

What is missing is the user-facing side.
`docs/src/epoch-boundaries.md:101` says system calls are "invisible to users" and that their effects show only in state and in header fields, and `:116-119` names `extra_data` as the public marker of an epoch close; but neither it nor `docs/src/rpc-methods/eth/eth_getlogs.md` says that the registry's events are never served, and neither names the other reads below.

## Evidence

An end-to-end test written for bench 6 (`epoch_close_forms.rs`, four validators, not upstream yet; node build `bench/bench6-2026-11` at `2df831e3c`) asked node 0, by `eth_getLogs` with the registry's address and the closing block as `fromBlock` and `toBlock`, for the registry's logs in every closing block.
Over three runs, 30 closing blocks in all, every answer was 0 logs.
The same test located each closing block on every node by the four reads below, and they agreed every time.

## What a reader can use instead

All of these work on main today:

- The closing block is the only block whose header `extraData` is 32 bytes (the epoch seed); it is empty on every other block (`crates/tn-reth/src/evm/block.rs:2118`, checked on read at `crates/tn-reth/src/evm/config.rs:209-222`).
- A block's epoch is the upper 32 bits of its header `nonce`, which is `(epoch << 32) | round` of the output's leader (`crates/types/src/primary/header.rs:255-257`).
- `getEpochInfo(E + 1).blockHeight` from the registry, read once epoch E + 1 has begun (before that it reads 0), is the first block of epoch E + 1, so the closing block of E is `blockHeight - 1`, and `getCurrentEpoch()` by `eth_call` reads E at the block before it and E + 1 at it.
  The contract keeps only the epochs from three before the current one to two after it, and older requests revert, at the head by `eth_call` and by `tn_getEpochInfo` alike (`crates/execution/tn-rpc/src/rpc_ext.rs:210-211`).
- `tn_epochRecord(E)` returns the certified epoch record with its certificate: committee, next committee and `final_state`, the closing block's number and hash (`crates/types/src/primary/epoch.rs:22-38`).
  This works for any past epoch the node holds; validators should not expose the `tn` namespace publicly (`rpc_ext.rs:174-180`), so serve it from a non-validating node.

## What a fix could look like

Documentation, no code change:

- in `eth_getlogs.md` and `epoch-boundaries.md`, say that events emitted by the epoch-closing system calls are not returned by `eth_getLogs`, receipts or log subscriptions, and list the four reads above;
- a NatSpec line on `NewEpoch` in `IConsensusRegistry.sol` (the `tn-contracts` submodule) saying the same, since that is where an integrator first meets the event, and a note on the other events the closing calls emit.

## How to verify

Read the two pages and follow the recipe against a node: for two consecutive epochs, find the closing block by `extraData` length, check its `nonce` epoch, `getCurrentEpoch` before and at it, and `tn_epochRecord(E).final_state`, and confirm all four agree.
