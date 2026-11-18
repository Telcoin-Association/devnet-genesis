# The scripts write a bare `--healthcheck` port, which telcoin-network main binds to loopback, so monitors reach nothing

On telcoin-network `main` a bare `--healthcheck <port>` binds 127.0.0.1; the scripts still write the bare port and a ufw rule for the monitor.
Testnet and devnet operators with the health monitor on meet it as soon as their node runs a release built from that `main`; the on-host probe still passes.

## What happens

- `setup-observability.sh --enable-health`, and `setup-node.sh` when `ENABLE_HEALTHCHECK_MONITOR=true`, put `--healthcheck 43174` on the node command and add a ufw rule that admits the Association monitor's address to 43174/tcp.
- On telcoin-network `main` that bare port binds `127.0.0.1:43174`. Only an address form such as `0.0.0.0:43174` listens on every interface.
- The ufw rule then admits the monitor to a port that answers nothing from outside, and the monitor sees a healthy node as down.
- The probes the scripts and the Node Manager UI run on the host reach the loopback bind, so nothing on the host reports the failure.
- The comments and two warnings still assume the old bind: "--healthcheck binds ${TN_KUMA_PORT} on all interfaces", and with ufw inactive "health port 43174 is reachable from the INTERNET", which is no longer true on such a release.

The scripts' own README already describes the change ("From the next release a bare `--healthcheck <port>` binds `127.0.0.1` only. The scripts pass the bare port …"), so this is known and documented, not fixed.

## Evidence

- Read from code, not run against a real monitor, during a devnet run in mainnet shape on 2026-11-17 (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis).
- The node side: the module doc of `crates/node/src/health.rs` and the flag table in `crates/telcoin-network-cli/README.md:356` at telcoin-network `5533ff73a`, the commit of the devnet's node image.
- The address form is not accepted by `v0.16.0-adiri` (README of PR #68's head, line 455), so one string cannot serve every image.

## Where in the code

tn-node-deployment `origin/main` (2813343) and PR #68's head (79fb24e); the same lines at both unless two are given.

- `setup-observability.sh:78-90`: `health_flag_add` injects `--healthcheck ${TN_KUMA_PORT}`.
- `lib/common.sh:9693-9694` (main), `:9727-9728` (PR): the node-launch flag tail adds the same bare port when the monitor is enabled.
- `lib/testnet-addons.env:40` (main): `TN_KUMA_PORT="43174"`.
- Comments that say the bare port binds every interface: `setup-observability.sh:147` and `:356-357`, `lib/common.sh:11160-11161` (main), `:11194-11195` (PR). The warnings beside them are `setup-observability.sh:359-363`.
- telcoin-network `5533ff73a`, `crates/node/src/health.rs:21-23`: "`--healthcheck 8080` binds `127.0.0.1:8080` … `--healthcheck 0.0.0.0:8080` is the only way to listen on every interface (issue #1689)".

Mainnet is not reached through this add-on: `require_testnet` refuses it off testnet and devnet (`lib/common.sh:9205-9212`, main), and `check-node.sh:2138-2151` fails a mainnet node whose command carries `--healthcheck`.
The one outside reader on mainnet found here is the worker gateway's readiness poll of `/health/workers`, which PR #68 handles (below).

## What is not known

- Which telcoin-network release first ships the loopback bind, and when testnet moves to it.
- Whether any testnet monitor already points at a node on such an image (not checked).
- Whether a load balancer anywhere reads this port; the challenge row names load-balancer checks, and none was found in the scripts read here.

## What could be done (suggestions, none tried)

- Write `--healthcheck 0.0.0.0:<port>`, kept behind the existing source rule, when the image accepts the address form, and the bare port only for an image that does not. This needs the image's version, the same gap as {{admission-version-floor-missing}}.
- Correct the comments and the "reachable from the INTERNET" warnings for a loopback bind.
- Have the status view say that the on-host probe cannot show whether the monitor can reach the port.

## Related

- PR #68 writes `--healthcheck 0.0.0.0:43174` only when `gateway_upstream` is set (the standalone worker gateway case, `edit-config.sh:2817` at its head); the add-on keeps the bare port.
- telcoin-network issue #1689: the change to a loopback default.
- {{admission-version-floor-missing}}: the scripts cannot read the version of a digest-pinned image.
