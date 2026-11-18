# PR #68's gateway_upstream binds a validator's RPC and health check to 0.0.0.0, guarded only by ufw

`edit-config.sh --set gateway_upstream=<list>` opens a validator's RPC and health check to its worker gateways by binding them to every interface, with ufw as the only guard; there is no way to bind the private address alone.
Every validator that runs a worker gateway on another host meets it; the row gives the reason as the scripts' local readers, which reach the RPC at 127.0.0.1.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis. Each validator's gateway runs on its own host and needs the validator's RPC and health port.

PR #68 gives that one form: `--http.addr 0.0.0.0` and `--healthcheck 0.0.0.0:<health port>`. The setter refuses unless ufw is active, lets each gateway address in to both ports and keeps every other address out. Two consequences follow:

- The RPC's exposure rests on ufw alone. If ufw is turned off or its rules are reset, the RPC listens on every interface with nothing in front of it.
- A firewall reset therefore needs `gateway_upstream=off` before it and the setting again after it (from the run's report, not re-read here).

A bind on the private address only (`--http.addr <private IP>`) would remove the first point, but the scripts' local readers, which reach the RPC at `127.0.0.1`, would then fail; that is why the PR uses a wildcard (as the row states it; the readers were counted, not each read).

## Evidence

- Read from code at PR #68's head (below); row 4 of the run's challenge list (2026-11-17, open, no log attached). The row does not say which gateway mode each validator used; validator-1's gateway ran in same-host mode, where this bind is not used.
- Loopback readers: `git grep -cE '127\.0\.0\.1:(\$\{?RPC_PORT|8545|\$\{?HEALTH)'` finds 5 lines in `setup-node.sh`, 3 in `migrate-node-naming.sh` and 1 in `install-caddy.sh` at both refs, besides tests; the helper `tn_local_rpc_url` is named by the setter's comment. Which of these break on a private-only bind was not checked.

## Where in the code

`origin/main` 2813343 (scripts 2.1.0) has no `gateway_upstream`: `setup-node.sh:2774` and `:2783` launch the node with `--http.addr 127.0.0.1 --ws.addr 127.0.0.1`. The problem is in PR #68's new code only.

At PR #68's head 79fb24e (scripts 2.2.0):

- `edit-config.sh:2815-2833`: the comment of `set_gateway_upstream` (2834): `--http.addr 0.0.0.0` and `--healthcheck 0.0.0.0:<health port>`, `TN_RPC_ADDR` in `node.env`, `GATEWAY_UPSTREAM` in `.node-meta`; refused unless ufw is active and admits exactly the listed addresses to both ports (`tn_gateway_from_rules_ok`, `tn_gateway_ports_private`); `off` puts `--http.addr 127.0.0.1` back.
- `edit-config.sh:123` and `:140-141`: the help for the same setting.
- `edit-config.sh:2857`: `off` sets `--http.addr 127.0.0.1`.

## What is not known

- Which local readers fail on a private-only bind, and whether `tn_local_rpc_url` is the only place to change.
- Whether the node's health listener can take a private address (`--healthcheck <ip>:<port>`) the way `--http.addr` can.

## What could be done (suggestions, none tried)

- Accept `gateway_upstream=<list>` with a bind address (the host's private address), and route the local readers through one helper that reads the bind from the launch line, falling back to 127.0.0.1.
- Until then, say in OPERATOR.md that a firewall reset on a gateway-upstream validator needs `gateway_upstream=off` around it.

## Related

- PR #68 (open): this is its code; to settle in its review or right after.
- {{unknown-flags-exit-zero}}: the same scripts' firewall handling.
