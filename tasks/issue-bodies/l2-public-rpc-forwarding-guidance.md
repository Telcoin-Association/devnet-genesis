# Public-RPC docs centre on --forward-txs, which skips the node-record path that worker gateways rely on.

A public RPC node can hand transactions to validators in two ways, and the operator guide is built around `--forward-txs`, which bypasses the node-record path that a layout with worker gateways relies on.
An RPC operator has to pick one mode without a statement of which is supported for mainnet, or of what is checked before a transaction reaches a validator's worker on the record path.

## What happens

- `docs/src/getting-started/public-rpc-nodes.md` describes both modes. With `--forward-txs` the node relays each `eth_sendRawTransaction` to a dedicated validator from local configuration and returns that validator's answer. Without it, the node pools the transaction and forwards it later, in the background, to the validator that owns the sender, at the RPC endpoint in that validator's node record.
- `crates/tn-reth/README.md` says that with `--forward-txs` the local pool is never touched, "so the node-record path above never sees the transaction", and that without `--sanitize-txs` the only local check is the `--rpc.txfeecap` guard, which at the default cap of 0 decodes nothing.
- A devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis) used the record path: each validator advertises its worker gateway's URL in its node record, and the RPC node forwards there.
- On that path, the run's notes take the gateway as the only check between the RPC node and a validator's worker. That is taken from the notes, not verified in code: the RPC node's own pool admission was not read.
- The deployment scripts (tn-node-deployment) render neither `--forward-txs` nor `--sanitize-txs`, so the guide's mode has no script support there (from the run's notes, not re-checked).

## Evidence

- Read from the documentation and the code at 5533ff73a; no run compared the two modes.
- The record path working end to end through a gateway: devnet-genesis `tasks/l2/rh5-report.md` (local rehearsal, 2026-11-17 21:05-21:14 UTC: one transfer through the RPC node, its own pool, the gateway URL in validator 1's record, validator 1's worker, a block).

## Where in the code

At 5533ff73a:

- `docs/src/getting-started/public-rpc-nodes.md:5-10`: the two modes, as above.
- `crates/tn-reth/README.md:505-507`: `--forward-txs` installs `EthSubmitForwarded` (`src/rpc_tx_forward.rs`) on every transport that serves `eth`; the local pool is not touched.
- `crates/tn-reth/README.md:519`: the precheck without and with `--sanitize-txs`.
- `crates/telcoin-network-cli/README.md:562-563`: the two flags in the node's flag table.

## What is not known

- Which mode is meant for mainnet public RPC nodes.
- What the RPC node's pool checks before a transaction enters the record path, and so whether the gateway is in fact the only check before a worker.
- How the two modes differ under load; the record path's behaviour under load is in {{forwarder-one-client-per-rpc-node}}.

## What could be done (suggestions, none tried)

- State in `public-rpc-nodes.md` which mode is supported for mainnet, and when to use the other.
- For the record path, list what is checked where: on the RPC node, at the gateway, and at the worker.

## Related

- {{forwarder-one-client-per-rpc-node}} and {{forwarder-rejected-warning-for-included-txs}}: the record path's forwarder under load.
- {{publish-worker-gateway-image}}: the gateway that the record path forwards to.
