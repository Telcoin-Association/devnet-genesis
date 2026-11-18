# A node not yet in the validators' P2P allowlists falls up to 476 blocks behind while its dials to them hang.

A node that is not yet admitted by the validators syncs from the public RPC node alone, yet once the validators' P2P allowlist firewall is on it stalls for up to 48 consensus outputs while its dials to them hang.
Every validator that joins after genesis is in this state from its first start until the epoch after its `activate()`. The mechanism is inferred from the log, not read from code.

## What happens

The setting is a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), on 2026-11-18 from 02:05 to 02:38 UTC.
Node 5 (`observer-5-devnet`) was not yet staked, so it was not in any validator's allowlist. Its only sync peer was the RPC node, which the firewall does not touch.

- Before the firewall (02:05-02:27 UTC): node 5 fetched every consensus output from the RPC node as it was announced, about 97 catch-ups a minute, never more than 3 outputs behind. Every few minutes it completed a handshake with each validator and published its record to it.
- 02:28 UTC, validator 1's allowlist on: the per-minute maximum of `catchup_distance` rose to 25.
- From 02:31 UTC, validators 2-4 on: per-minute maxima of 14, 17, 21, 40, 37, 38, 36 and 48 outputs, stalls of about 30 s. Its dials to the validators hang, and `Stream(NotConnected)` appears against all four, up to 39 times a minute.
- Probed every 10 s from 02:35:15 to 02:37:05 UTC with host timestamps, node 5 was behind validator 1 by 262, 51, 208, 366, 476, 0, -1, 0, 2, 4 and 17 blocks. The RPC node stayed within 6.
- One stall on node 5, at 02:35:15 UTC:
  ```
  02:35:15.242 WARN primary::network consensus output sync exchange failed; trying next peer peer=24JYGVN9…   (4 times in 0.4 ms, same peer)
  02:35:15.382 WARN tn::observer failed to fetch/verify consensus output from peer, will retry e="no peer served the consensus output over the sync protocol"
  02:35:17.427 INFO tn::observer catching up consensus blocks last_consensus_height=6997 max_consensus_height=7006 catchup_distance=9
  02:35:17.430 INFO tn::observer catching up consensus blocks last_consensus_height=7006 max_consensus_height=7023 catchup_distance=17
  02:35:17.619 INFO tn::network peer metrics heartbeat connected_count=1 connected_or_dialing=4 banned_count=0
  ```
- Two things changed together: the block rate rose from about 2.5 to 7 blocks/s while the firewall went on. The cause is not separated.
- Node 5 also logged `peer denied consensus output sync request: Unavailable` from the RPC node, 30 to 60 a minute since 02:12 UTC, before any firewall (2,752 by 02:38 UTC).
- With the firewall on, node 5's record reaches the validators only through the bootstrap hub until a validator fetches it there. The deployment plan says lookup backoff can delay a joiner's allowlist entry by up to 30 minutes. No run measured this and the code was not read for it.

## Evidence

- Per-minute `catchup_distance` maxima, the catch-up rate and the handshakes before the firewall: node 5's `/var/log/telcoin/telcoin.log`, as summarised in devnet-genesis `tasks/challenges-l2.md` row 67. The log itself was not re-read for this draft.
- Block lags: `tasks/l2/w3/s1/lagprobe2-0.txt` (validator 1), `lagprobe2-4.txt` (node 5) and `lagprobe2-5.txt` (RPC node), one block number with its host timestamp every 10 s. Node 5 was read about 1.9 s after validator 1; the raw pairs give 230, 22, 179, 335, 458, 0, -1, 0, 2, 1, 15, 17 blocks, and the figures above are those pairs taken to the same instant.
- Log excerpt and heartbeat: `tasks/l2/w3/s1/node5-view-0235Z.txt`, a log tail taken on node 5 at 02:35:16 UTC.
- `Stream(NotConnected)` counts, the `Unavailable` count, and the rate change: the orchestrator log `tasks/ckpt-l2-orch.md`, entry 02:38Z.
- Where the lines are logged, at 5533ff73a: `crates/consensus/primary/src/network/mod.rs:2388` (`exchange failed; trying next peer`), `:2279` (`no peer served`), `:2771` (`peer denied`), and `crates/state-sync/src/lib.rs:575` (`catching up consensus blocks`). This locates the messages, not the cause.

## What is not known

- Whether the observer's sync waits on dials to the validators that the firewall drops. Inferred from the log; the dial and sync path was not read.
- How much of the stall the rate change alone explains.
- Why the RPC node answers `Unavailable` 30 to 60 times a minute on a healthy chain.
- The 30-minute figure: from the deployment plan, not measured, not read in code.
- How node 5 syncs once it is in the validators' allowlists. This draft is to get that evidence when node 5 is admitted.

## What could be done (suggestions, none tried)

- Read the observer's dial and sync path to confirm the mechanism.
- Keep a sync request from waiting on a dial that never completes, for example by trying only connected peers first, or a short dial timeout for sync.
- Log the refusal on the validator side, so the joiner's operator and the validator's operator can see why they are not connected.

## Related

- {{log-silent-peer-refusal}}: neither side logs the refusal, and the one sync WARN that appears also fires on healthy nodes.
- {{joiner-admission-renderer}} (tn-node-deployment): the scripts cannot write admission settings for a joiner that bootstraps from a hub with the genesis set as committee peers.
