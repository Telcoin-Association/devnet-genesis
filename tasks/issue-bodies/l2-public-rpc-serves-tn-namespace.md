# The public-RPC launch flags put `tn` in `--http.api`, so a public RPC node serves `tn_admissionSnapshot` to any caller

The flags the scripts write for a node that serves public RPC list `--http.api eth,net,web3,tn`, so every `tn_*` method answers any caller, the admission snapshot included.
The operator of a public RPC node meets it, and so do the validators whose P2P addresses that node tracks. This is an exposure decision as much as a defect: the list names `tn` on purpose.

## What happens

Read from code; no run evidence, and the snapshot was not called on the devnet's RPC node.

- `setup-node.sh` writes, for a public RPC node, `--rpc.max-blocks-per-filter 10000 --rpc.max-logs-per-response 10000 --rpc.max-subscriptions-per-connection 100 --rpc.max-request-size 2 --http.api eth,net,web3,tn`. Its comment: "HTTP limited to eth, net, web3 and tn".
- `edit-config.sh` writes the same list when the operator sets the RPC bind to `0.0.0.0` from the interactive menu.
- The Caddy site `install-caddy.sh` writes for the public RPC endpoint has no method filter, so through the edge every method the node serves is public.
- On telcoin-network, `tn` holds `info`, `nodeMode`, `admissionSnapshot`, `latestConsensusHeader`, `genesis`, `epochRecord`, `getCurrentEpoch`, `getValidators` and others.
  `tn_admissionSnapshot` returns "for each swarm, its connection admission status and every BLS key it tracks, with the key's slots, addresses and whether its PeerId is in the swarm's authorized set."
- On a network in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), the RPC node's configuration lists the four validators as committee peers with their external addresses.
  Inferred, not verified: its snapshot would hand those P2P addresses to any caller, while the validators' firewalls admit only the committee and the RPC node.
- The node's doc says "Listing a key grants it nothing"; the question is the addresses and the admission state, not the keys.

## Evidence

- Challenge rows 12 and 20 of the devnet run of 2026-11-17/18; row 12 was seeded from the plan and has no run evidence.
- The RPC node's `committee_peers` (four entries) and `mode Open`: devnet-genesis `tasks/l2/w3/d3a/as-run.md:9`.
- The node's RPC defaults: devnet-genesis `tasks/l2/facts/node-side.md:31-33`, read from telcoin-network code by an earlier unit; not re-read here.

## Where in the code

- tn-node-deployment `origin/main` (2813343): `setup-node.sh:2518-2521`, `public_rpc_limit_flags` and its comment (not re-checked at PR #68's head).
- `edit-config.sh:2760` (main), `:2791` (PR #68's head, 79fb24e): the list in the `0.0.0.0` branch of the RPC bind setter (row 20 cites `:2702-2775`; `edit_rpc` starts at `:2704`).
- `install-caddy.sh` at main: `git grep -i -E "jsonrpc|request_body|method"` finds no method filter.
- telcoin-network `5533ff73a`: `crates/execution/tn-rpc/src/rpc_ext.rs:128` (`namespace = "tn"`), `:141-150` (`admissionSnapshot` and its doc), the ext merged at `crates/node/src/engine/inner.rs:177`.
- Per the facts file: the default namespaces are `eth, net, web3, rpc, tn`, and an explicit list must include `tn` to keep `tn_*` (`crates/tn-reth/src/cli.rs:207-208`, `rpc_server_args.rs:106-112`).

## What is not known

- Which `tn_*` methods are meant for the public: `getValidators` and the epoch methods look public by nature, `admissionSnapshot` and `nodeMode` less so.
- What a snapshot from an RPC node in `Open` mode holds in practice.
- The scripts write no `--ws.api`, so the WebSocket listener would serve the default set, `tn` included, whatever `--http.api` says (inferred from the defaults above).
- Whether host tooling on a public RPC node needs `tn_admissionSnapshot` over the same listener.

## What could be done (suggestions, none tried)

- Decide which `tn_*` methods a public RPC node serves and document it in OPERATOR.md.
- If some must stay private: `--http.api` cannot drop part of a namespace, so either the node splits `tn` (a telcoin-network change), or the Caddy RPC site rejects those method names, or the node serves them on a second, loopback-only listener.
- Set `--ws.api` beside `--http.api` so both listeners serve the same list.

## Related

- PR #68 adds a separate `gateway_upstream` key that sets `--http.addr 0.0.0.0` without the public list (row 20).
- {{p2p-committee-not-scriptable}}: the committee allowlist that the snapshot's addresses sit behind.
