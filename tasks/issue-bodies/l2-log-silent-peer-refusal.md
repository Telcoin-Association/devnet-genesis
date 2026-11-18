# A validator logs nothing when it drops a non-admitted peer, while healthy observers warn about sync once a second.

Two separable logging problems that together leave a joiner's sync trouble unexplained: a validator under closed admission refuses a peer it does not admit without a log line, and a healthy non-committee node logs a sync WARN about once a second.
Operators of validators, of the public RPC node and of nodes joining after genesis meet both; either part could be filed alone.

## What happens

Part 1, the silent refusal:

- In a local rehearsal of the admission layout (four validators under closed admission, a public RPC node, and a joiner that the validators do not admit), the RPC node was left stopped, so the joiner had no peer that would keep it.
- For the 100 s watched, the joiner stayed at head 0 while validator 1 was at 1, with `connected_count=0` in its heartbeat. Its log shows `"new connection established"` 9 to 27 times to each validator's primary and worker address: the QUIC handshake completes and the validator drops the connection again.
- The validators ran at `-vvv`. Their logs have no line naming the joiner's peer id, so a validator's operator cannot see why the joiner is not connected.

Part 2, the noisy WARN:

- On a healthy chain, the public RPC node logged about 200 `consensus output sync exchange failed; trying next peer` warnings in 3 minutes, and the joiner 47.
- On a live devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), the joiner logged the WARN 4 times in 0.4 ms against the same peer at 02:35:15 UTC on 2026-11-18, then caught up 26 outputs 2 s later.
- These lines sit beside the ones that matter when sync does fail, such as the stall in {{joiner-sync-stalls-behind-allowlist}}.

## Evidence

- Part 1: devnet-genesis `tasks/l2/rh0-report.md`, run 2 of the local docker rehearsal, 2026-11-17 19:50-19:54 UTC, image built from 5533ff73a. The handshake counts and the absence of a log line come from that report; the container logs were not re-read for this draft.
- Part 2: `tasks/l2/rh3-report.md` (a later local rehearsal of the same layout, 2026-11-17, container logs), and `tasks/l2/w3/s1/node5-view-0235Z.txt` (a log tail on the joiner of the live devnet).

## Where in the code

At 5533ff73a, read from code, not run:

- `crates/network-libp2p/src/peers/behavior.rs:162-186`: the inbound handler, after the self and ban checks, calls `check_admission(Some(&peer), ConnectionDirection::Inbound)?` at `:180`.
- `crates/network-libp2p/src/peers/manager.rs:572-588`: under closed admission, a peer outside the authorized set is counted with `record_closed_admission_denied(direction)` and denied with `PeerAdmissionDenied::ClosedAdmission`. Nothing is logged.
- `crates/network-libp2p/src/consensus.rs:1463-1481`: the swarm's `IncomingConnectionError` with `ListenError::Denied` is counted by `record_inbound_rejection`; a rate-limited WARN is logged only for connection-limit refusals, not for admission.
- `crates/consensus/primary/src/network/mod.rs:2378-2389`: on `ConsensusOutputAttempt::Failed(e)` the node marks the peer with `mark_sync_failed(peer, epoch)` and logs the WARN at once, before it tries the next peer, whether or not a later peer serves the output.

## What is not known

- Which error the healthy nodes' WARNs carry; the `e` field was not re-read.
- Whether the refusal counter is exported where an operator would look, and whether it can be told apart per peer. It counts by direction only.
- Whether the outbound side, a validator dialling a non-admitted peer, is logged. Not checked.

## What could be done (suggestions, none tried)

- Part 1: log an admission refusal with the peer id and direction, rate-limited per peer like the connection-limit warning, at a level shown at `-vvv`.
- Part 2: log a failed exchange at debug while other peers remain, and keep a WARN for the case where no peer served the output, which `tn::observer` already logs as `no peer served the consensus output over the sync protocol`.

## Related

- {{joiner-sync-stalls-behind-allowlist}}: the stall these logs fail to explain.
- tn-node-deployment `firewall-setup.sh --p2p-committee`: a host firewall in front of the same refusal. With it on, a validator never sees the joiner's handshake, so even a refusal log would stay empty for that peer (inferred).
