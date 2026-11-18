# The RPC node warns that a forwarded transaction was rejected (nonce too low) when it is already included.

The forwarder logs `the forwarded transaction was rejected; no validator accepted it` and counts a drop for transactions the chain already holds, so the warning and the `rejected` drop counter overstate loss.
RPC operators who read the log or alert on the counter meet it. Why the already-included transactions were sent again is not verified.

## What happens

On a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), with a transaction generator sending steady load through the public RPC node on 2026-11-18:

- The RPC node logged the warning several times a second, twelve lines from 03:01:10 to 03:01:13 UTC, each with a `reason` of `nonce too low`.
- The transactions named were already included: the sender's next nonce was past them.
- `tn_reth_forwarded_txns_dropped_total{reason="rejected"}` went from 930 to 959 in 68 s, while `tn_reth_forwarded_txns_queued_total` rose from 12,369 to 12,864 (+495) and `tn_reth_forwarded_txns_requeued_total` from 727 to 770 (+43).
  In that window, 29 rejections against 495 queued is about 6 %. Over the chain's first 75 minutes the counter reached 959 against 12,864 queued, about 7.5 %.
- A drop counter at this level reads as steady loss, and the warning says no validator accepted the transaction, while the chain holds it.

## Evidence

- Metrics: devnet-genesis `tasks/l2/w3/v/r7-t0-rpc6.txt` and `r7-t1-rpc6.txt`, two scrapes of the RPC node (`rpc-6-devnet`) 68 s apart.
- Log lines and the inclusion check: the RPC node's log from 03:01:10 to 03:01:13 UTC, from the run's notes (`tasks/challenges-l2.md` row 76). The log is not in the repository and was not re-read for this draft.
- Seen in one window of one run.

## Where in the code

At 5533ff73a, read from code, not run:

- `crates/tn-reth/src/forward.rs:808-818`: on `ForwardOutcome::Rejected(reason)` the forwarder removes the transaction from its pending forwards, adds one to `rejected`, and logs the warning with the target's `reason` as its only field.
- `:802-806`, just before: a deferred outcome keeps the transaction pending and defers it for a later attempt, which is where a second delivery of the same transaction could start (inferred, not traced).
- Where `rejected` feeds `tn_reth_forwarded_txns_dropped_total{reason="rejected"}` was not read.

## What is not known

- Whether the forwarder re-sends a transaction after a slow or failed answer from a target that had in fact accepted it, or the generator sends the same transaction twice. Not verified.
- Whether every `rejected` count in the window was a `nonce too low` for an included transaction, or some were real rejections.

## What could be done (suggestions, none tried)

- Before counting a rejection as a drop, check whether the transaction's hash is already in the local chain, or whether its nonce is below the sender's on-chain nonce, and count that case apart (for example `reason="already_included"`).
- Log the transaction hash and the target's index with the warning, so an operator can check inclusion.

## Related

- {{forwarder-one-client-per-rpc-node}}: the same forwarder's demotions and requeues under load.
- {{public-rpc-forwarding-guidance}}: the forwarding mode this is part of.
