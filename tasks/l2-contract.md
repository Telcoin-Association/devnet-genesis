# Launch 2: frozen interface contract

status: FROZEN v1 (2026-11-17). Amendments are appended to §14 by the orchestrator only; a unit that needs a
change hands back a "contract change request" and stops that section.
Plan: `tasks/l2/plan-approved-2026-11-17.md`. Rules: `tasks/l2/agent-rules.md`. Units and file owners:
`tasks/l2/units.md`. Fact sheets with file:line evidence: `tasks/l2/facts/*.md` (named per section below).
Names: TND = `/home/drtnarg/coding/telcoin/tnd-l2-gateway` (tn-node-deployment, branch `worker-gateway`),
DG = `/home/drtnarg/coding/telcoin/dg-l2` (devnet-genesis, branch `l2/launch-2`), TN = telcoin-network 5533ff73a.

## 1. Ground facts everything rests on (read the sheet before relying on more than this)

Gateway binary (`facts/gateway-binary.md`, real `--help` in `facts/gateway-help.txt` once unit IMG saved it):
- Flags used by the installer, exact names: `--listen-addr`, `--probe-addr`, `--metrics`, `--upstream-rpc-url`,
  `--upstream-readiness-url`, `--worker-id`, `--redirect-queries`, `--trusted-proxies`. The readiness target is a
  full URL (`http://<host>:<health port>/health/workers`). Default `--listen-addr` is `0.0.0.0:8545` (collides
  with the node), so it is always given.
- It is an HTTP/1 POST proxy: no TLS, no WebSocket, no auth. `POST` to any path is JSON-RPC. `GET /health` (always
  200), `GET /ready` (200 when the worker is ready, else 503), `GET /ready/any` are served on the main listener
  and on `--probe-addr`. Any other non-POST gets 405.
- It starts and stays up with the node down and with the redirect URL unreachable (fails closed: worker calls get
  503 / `-32000`). It exits 1 at start on a flag-rule violation, a failed bind, or an https URL with no CA store.
- With `--redirect-queries` the gateway itself proxies every non-submission call to that URL (never a 3xx) and the
  `tn_,debug_,trace_,admin_` deny list is NOT applied: `tn_nodeMode` through a gateway is answered by the query
  node. Without the flag those prefixes get 403 / `-32011`.
- Limits per client IP: 100 req/s, 32 connections. `--trusted-proxies` (CIDR list) makes it read `X-Forwarded-For`
  from the right, skipping listed proxies.
- Stop needs up to 45 s drain + 2 s: `docker --stop-timeout 60`, `TimeoutStopSec` at least 75.
- Image: `USER 1101:1101`, `ENTRYPOINT ["worker-gateway"]`, no writable path, no capability.

Node (`facts/node-side.md`):
- A bare `--healthcheck <port>` binds `127.0.0.1:<port>`; all interfaces needs `0.0.0.0:<port>`. `GET
  /health/workers` always answers 200; the signal is `accepting_transactions` in the JSON body.
- Peers config is `<datadir>/network-config` (YAML): `admission: {mode: Open|Grace|Closed}`, `trusted_nodes`
  (map BLS key -> `{primary, workers: {<id>: …}}`), `committee_peers` (map BLS key -> `{primary, workers: […]}`).
  At epoch 0 a non-empty `committee_peers` must list every committee member or the node refuses to start.
- `tn_admissionSnapshot` (namespace `tn`, no params) has no "authoritative" flag: the rule is primary swarm
  `available: true`, `tracked_epoch` non-null, `admission.fallback` null (or `Unresolved`). Before the networks
  start it is a JSON-RPC error.
- A non-committee node pools a submission and forwards it per sealed batch to the `rpc.http` URL of committee
  worker records. The "public only" target check is literal (a DNS name always passes). Records advertise what
  `node-info.yaml` holds; `keytool set-rpc --http URL [--ws URL] | --clear` edits it; the record is signed at start.

tn-node-deployment (`facts/tnd-template.md`, `tnd-node.md`, `tnd-caddy.md`, `tnd-firewall.md`):
- `lib/alerts.sh` is sourced by the END of `lib/common.sh` in a guarded `if [[ -f … ]]; then source …; fi`.
- Lib skew is checked by function presence (`declare -F`), exit 2. `--json` = events on fd 3 (`exec 3>&1; exec
  1>&2`), exactly one `done` line. Library rc 0 ok / 1 refused or rolled back / 2 partial -> script exit 0/1/3.
- `setup-node.sh --json --phase finalize` always starts and enables the node (no `--no-start`). One map
  (`--bootstrap-peers <file>`) feeds both the node's `--bootstrap-peers` launch flag and `committee_peers`.
- `edit-config.sh --set` restarts the unit unconditionally, so today it starts a stopped node.
- `install-caddy.sh` regenerates the whole Caddyfile from two positional blocks; anything not passed is dropped.
- `firewall-setup.sh`: source lists persist in `.node-meta` and are re-applied by every `--enable` / `--reset`;
  unknown flags are silently ignored; `--p2p-committee on` refuses at once when the snapshot is not authoritative.

## 2. TND shared names: `lib/common.sh` (unit C1 is the only writer)

`COMMON_VERSION="2.2.0"`. Added, in one block near the other add-on constants (each line that names one network
carries a `# network-gated:` comment as the repo's lint wants):

| Name | Value / behaviour |
|---|---|
| `TN_GATEWAY_ETC_DIR` | `/etc/telcoin/gateway` |
| `TN_GATEWAY_META` | `/etc/telcoin/gateway/gateway.meta` |
| `TN_GATEWAY_UNIT` | `telcoin-gateway.service` |
| `TN_GATEWAY_CONTAINER` | `telcoin-gateway` |
| `TN_GATEWAY_LISTEN_PORT` / `TN_GATEWAY_PROBE_PORT` / `TN_GATEWAY_METRICS_PORT` | `8655` / `8656` / `9655` |
| `TN_CADDY_GW_BEGIN` / `TN_CADDY_GW_END` | `# >>> tn-gateway >>>` / `# <<< tn-gateway <<<` |
| `tn_gateway_meta_path` | prints `${TN_ROOT_PREFIX:-}${TN_GATEWAY_META}`; rc 0 |
| `tn_gateway_installed` | rc 0 when that path is a regular file, else 1; no output |
| `tn_gateway_meta_get KEY [DEFAULT]` | prints the value or DEFAULT, rc 0; key on two lines -> rc 2 and nothing printed (same contract as `addon_meta_get`, on `gateway.meta`) |
| `tn_gateway_from_list` | prints `.node-meta` `GATEWAY_ALLOW_FROM` (comma list) or nothing; rc 0; duplicate key rc 2; no node rc 1 |
| `tn_gateway_from_rules_ok LIST RPC_PORT HEALTH_PORT` | rc 0 when ufw is active and, for every source in LIST, `allow from <src> to any port <RPC_PORT> proto tcp` and the same for HEALTH_PORT exist; else rc 1 with `TN_GATEWAY_FROM_MISSING="<src> <port>"` (or `ufw-inactive`) |
| `tn_node_health_bind` | prints the node's `--healthcheck` launch value as `<host>:<port>` (`127.0.0.1:<port>` for a bare port); rc 1 when the flag is absent, rc 2 when no launch file is found |
| source block | at the end of the file, next to the alerts one: `if [[ -f "${__COMMON_DIR}/gateway.sh" ]]; then source …; fi` |

Meta keys. In `gateway.meta` (root:root 0600, `KEY=value`, written with `meta_set KEY VALUE "$(tn_gateway_meta_path)"`):
`GATEWAY_META_VERSION=1`, `NETWORK`, `MODE` (`same-host|standalone`), `FRONT` (`caddy|none`), `DOMAIN` (empty
with `none`), `IMAGE` (`<repo>@sha256:<64 hex>`), `UPSTREAM_HOST` (`127.0.0.1` or the validator's private IPv4),
`RPC_PORT`, `HEALTH_PORT`, `LISTEN_PORT`, `PROBE_PORT`, `METRICS_PORT`, `REDIRECT_QUERIES`, `TRUSTED_PROXIES`
(may be empty). In `.node-meta` (validator side): `GATEWAY_ALLOW_FROM` (C2), `GATEWAY_UPSTREAM` and
`GATEWAY_PREV_HEALTHCHECK` (C3), `RPC_ADVERTISED_VIA=gateway` (B).

## 3. TND gateway installer: `lib/gateway.sh` (A1) and `setup-gateway.sh` (A2)

### 3.1 CLI (A2), in the shape of `setup-alerts.sh`
```
setup-gateway.sh --enable  --mode same-host|standalone --image <repo>@sha256:<digest> --redirect-queries <url>
                           [--network <name>] [--domain <host>] [--front caddy|none]
                           [--upstream <private-ipv4>] [--rpc-port N] [--health-port N]
                           [--listen-port N] [--probe-port N] [--metrics-port N] [--trusted-proxies <cidrs>]
                           [--yes] [--json]
setup-gateway.sh --status  [--json]
setup-gateway.sh --refresh [--image <repo>@sha256:<digest>] [--yes] [--json]
setup-gateway.sh --remove  [--yes] [--json]
```
- Exactly one action; no action and no `--json` prints the usage (there is no menu). Unknown arguments are refused
  (as setup-alerts does), value flags take `--flag VALUE` and `--flag=VALUE`. Every refusal ends "Nothing was changed."
- Defaults: `--front caddy`; ports 8655 / 8656 / 9655; `--rpc-port`: same-host = the node's `--http.port` launch
  flag, else `.node-meta` `RPC_PORT`, else 8545; standalone = 8545. `--health-port`: same-host = the port of
  `tn_node_health_bind`; standalone = `${TN_KUMA_PORT}` (43174). `--trusted-proxies`: `127.0.0.1/32` with
  `--front caddy`, empty with `none`.
- `--network`: required on a host with no node; on a node host it defaults to `.node-meta` `NETWORK` and must
  equal it when given.
- `--yes`: plain mode prints what will be exposed and asks once; `--yes` or `--json` skips the question; no
  terminal and neither flag is a refusal. `--remove` asks the same way.
- Root is needed for every action but `--status`.
- Refusals for `--enable` (all before any change): `--mode same-host` with no node on the host or with the node's
  launch file lacking `--healthcheck` (name the remedy); `--mode same-host` on mainnet ("on mainnet the gateway
  runs on its own host"); `--mode standalone` on a host that runs a node, or without `--upstream`; `--upstream`
  not a strict private IPv4; `--front caddy` without `--domain`; `--domain` with `--front none`; a port that is
  invalid, repeated among the three, or equal to the node's RPC or health port on this host; `--redirect-queries`
  not `^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?$`; an image the trust rule refuses; docker missing
  or its daemon unreachable.
- Exit status: 0 done; 1 refused or rolled back, nothing changed; 2 the libraries are older than this script;
  3 a step failed after something changed (the message says what is left). Signals 143/130/129 as setup-alerts.

### 3.2 `--json` (A2)
Events `{"event":"step|log|warn|error","msg":…}` on fd 3, then one done line.
- Success: `{"event":"done","ok":true,"applied":[…],"network":<str|null>,<fields>,"msg":…}`. `applied` items:
  `gateway:enabled`, `gateway:refreshed`, `gateway:caddy` (the Caddy block was written), `gateway:removed`;
  `[]` when nothing had to change (msg says so).
- Failure: `{"event":"done","ok":false,"msg":…}`.
- Fields on every success line: `installed` (bool), `enabled` (bool), `active` (bool), `mode`, `front`, `domain`,
  `image`, `image_held` (bool), `listen`, `probe`, `metrics` (each `host:port`), `upstream_rpc`,
  `upstream_readiness`, `redirect_queries`, `health` (bool: `GET /health` on the probe listener answered 200),
  `ready` (bool: `/ready` 200), `ready_any` (bool), `caddy_block` (bool, `null` with front `none`), `issues` (number).
  Strings are `null` when not installed.
- `--status` always exits 0 once it could read the state; a caller judges `installed`, `active`, `issues`, `ready`.
  `--enable` does not wait for readiness (the node may be down): it waits up to 20 s for `health` only.

### 3.3 Library (A1): `GATEWAY_VERSION="2.2.0"` (plain assignment, first in the file), public `gw_*`, private `_gw_*`
Say convention as lib/alerts.sh: every public function takes an optional say function `FN` (called `FN KIND MSG`)
and never writes fd 3. Inputs are globals the script sets (empty = not given): `GW_IN_MODE GW_IN_NETWORK
GW_IN_IMAGE GW_IN_DOMAIN GW_IN_FRONT GW_IN_UPSTREAM GW_IN_RPC_PORT GW_IN_HEALTH_PORT GW_IN_REDIRECT
GW_IN_LISTEN_PORT GW_IN_PROBE_PORT GW_IN_METRICS_PORT GW_IN_TRUSTED_PROXIES`, plus `GW_CADDY_SCRIPT` (path of
`install-caddy.sh`, set by the script; empty skips the Caddy call with a warning).
Results: `GW_ERR` (one phrase), `GW_APPLIED` (space list of `enabled refreshed caddy removed`, empty = nothing
changed), `GW_ST_*` (one per status field of §3.2, upper-cased, e.g. `GW_ST_INSTALLED`, `GW_ST_READY_ANY`).

| Function | Contract |
|---|---|
| `gw_etc_dir`, `gw_meta_file`, `gw_unit_path` | print the `${TN_ROOT_PREFIX:-}`-prefixed path |
| `gw_validate_inputs [FN]` | resolves defaults into `GW_V_*` (same suffixes as `GW_IN_*`, plus `GW_V_UPSTREAM_HOST`); rc 0, or rc 1 with `GW_ERR` |
| `gw_image_allowed IMAGE NETWORK` | rc 0/1, no output; sets `GW_ERR` |
| `gw_image_ensure IMAGE [FN]` | `docker pull` when `tn_docker_holds_digest` says no, then checks again; rc 0, rc 1 unavailable |
| `gw_image_probe IMAGE [FN]` | runs the image's `--help` (`--network=none --read-only --cap-drop ALL --user 1101:1101 --pull=never`) and needs every flag of §1 in it; rc 0/1 |
| `gw_render_args` | prints ONE line from `GW_V_*`, in this order: `--listen-addr A --probe-addr 127.0.0.1:P --metrics 127.0.0.1:M --upstream-rpc-url http://H:R --upstream-readiness-url http://H:K/health/workers --worker-id 0 --redirect-queries Q` then `--trusted-proxies T` only when T is not empty. A = `127.0.0.1:L` with front `caddy`, `0.0.0.0:L` with `none` |
| `gw_unit_text` | prints the unit: `ExecStart=<abs docker> run --rm --name telcoin-gateway --network=host --user 1101:1101 --read-only --cap-drop ALL --security-opt no-new-privileges --pull=never --stop-timeout 60 <IMAGE> <args>`; `ExecStartPre=-<abs docker> rm -f telcoin-gateway`; `ExecStop=<abs docker> stop -t 60 telcoin-gateway`; `Restart=on-failure`; `RestartSec=5`; `TimeoutStopSec=75`; `After=`/`Wants=network-online.target`, `After=`/`Requires=docker.service`; `WantedBy=multi-user.target` |
| `gw_enable [FN]` | validate -> image allowed, ensured, probed -> if unit text and meta are what is installed, the image is held and the unit is enabled and active: nothing changes (`GW_APPLIED=""`, rc 0; the Caddy step still runs and is itself a no-op when the block is current) -> else back up the unit and meta (`tn_backup_file`), write meta and unit, `daemon-reload`, `enable`, `restart`, wait for `health` -> front `caddy`: run `GW_CADDY_SCRIPT --json --phase gateway-enable --gateway-domain D --gateway-port L --gateway-probe-port P`. rc 0; rc 1 refused or failed and put back (`tn_restore_backup`, or removed when there was none); rc 2 the put-back failed |
| `gw_refresh [FN]` | re-render from `gateway.meta` (a non-empty `GW_IN_IMAGE` replaces `IMAGE`), same no-op rule, restart the gateway unit only; rc 0/1/2 |
| `gw_remove [FN]` | front `caddy`: `GW_CADDY_SCRIPT --json --phase gateway-disable`; disable and stop the unit, remove the unit, the container and `/etc/telcoin/gateway`; the image stays (said in the message); rc 0/1/2 |
| `gw_status [FN]` | fills `GW_ST_*`; rc = number of issues, capped at 20; needs no root |

The library never stops, starts or restarts the node. It holds the update lock while it changes anything.

### 3.4 Image trust (A1)
- Tag references are always refused; only `<repo>@sha256:<64 lowercase hex>`.
- devnet: the repository must be in `GW_DEVNET_IMAGE_REPOS="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway"` (space-separated string).
- testnet and mainnet: only the digest pinned by this scripts release, `GW_TESTNET_IMAGE_PIN=""` and
  `GW_MAINNET_IMAGE_PIN=""` (full `<repo>@sha256:…` references in `lib/gateway.sh`, which the signed MANIFEST
  covers). Empty pin: `--enable` refuses with "this scripts release pins no worker-gateway image for <network>".
  With a pin, `--image` may be left out and must equal the pin when given.
- The `--help` probe of §3.3 runs on every network before anything is written.

## 4. TND `install-caddy.sh` (unit B)
- Third fenced block, markers `TN_CADDY_GW_BEGIN` / `TN_CADDY_GW_END`, first line inside `# tn-gateway block v1`.
  Site = the gateway hostname. Behaviour: `GET|HEAD` on `/health`, `/ready`, `/ready/any` -> `reverse_proxy
  127.0.0.1:<probe port>`; a WebSocket upgrade -> 405; any other non-`POST` except a CORS preflight -> 405 with
  `Allow: POST, OPTIONS`; preflight and CORS headers as the `tn-rpc` block does; `POST` -> `request_body max_size
  2MB`, `reverse_proxy 127.0.0.1:<listen port>` with `X-Forwarded-For` ending in the real client address.
- `caddy_write_managed` takes the gateway block as a third argument and every existing writer passes the block it
  found, so toggling the dashboard or the public RPC keeps it. "No block left" (teardown, closing 80/443) counts
  all three. The hostname clash check covers all three.
- New phases (JSON and human dispatch, usage text, both parse forms of every new value flag):
  `gateway-status` (one JSON object: `installed running enabled domain port probe_port block_stale`),
  `gateway-check-dns --gateway-domain <host>`,
  `gateway-enable --gateway-domain <host> [--gateway-port N] [--gateway-probe-port N]` (defaults 8655 / 8656),
  `gateway-disable`,
  `rpc-advertise --rpc-domain <host>` (writes `https://<host>/` and NO ws URL into node-info through the existing
  advertise path with its guarded restart, sets `.node-meta` `PUBLIC_RPC_DOMAIN`, `PUBLIC_RPC_URL`, unsets
  `PUBLIC_WS_URL`, sets `RPC_ADVERTISED_VIA=gateway`; touches no Caddy file),
  `rpc-unadvertise` (clears node-info's RPC entry, guarded restart, unsets those four keys).
- `rpc-disable` leaves node-info and the meta keys alone when `RPC_ADVERTISED_VIA=gateway`. `rpc-enable` refuses
  while a `tn-gateway` block is present or `RPC_ADVERTISED_VIA=gateway` is set; `gateway-enable` refuses while a
  `tn-rpc` block is present. Each refusal names the phase to run first.
- Gate for the gateway phases: a host with a node -> the existing `caddy_mainnet_gate`; a host with no node ->
  pass when `tn_gateway_installed`, else refuse ("run setup-gateway.sh first"). No other phase changes its gate.
- `gateway-enable` is a no-op (no reload) when the block on disk is already the one it would write.

## 5. TND validator side (units C2, C3)

`firewall-setup.sh --gateway-from <ipv4[,ipv4|cidr…]> | none` (C2):
- Goes with `--enable` or `--reset` (also `--json --enable`); alone, or with `--p2p-committee`, it is refused like
  the other source flags. Needs an installed node. Same source grammar as `--p2p-from`.
- Persisted as `.node-meta` `GATEWAY_ALLOW_FROM` (comma list); `none` unsets it and deletes the rules.
- Rules per source, on every network, applied after the health-port block: `ufw allow from <src> to any port
  <RPC port> proto tcp` and `… port <health port> proto tcp` (RPC port in the order `.node-meta` `RPC_PORT`, 8545;
  health port `${TN_KUMA_PORT}`). Re-applied from `.node-meta` by every `--enable` and `--reset`; rules of
  sources no longer listed are deleted on `--enable`.
- `--json --status` gains `"gateway_from":[…]`; the status screen and the expected-rules list gain the rows.
- `caddy_serves_public_edge` is also true for a Caddyfile holding `TN_CADDY_GW_BEGIN`.
- `--enable` on a host with no node but with a gateway (`tn_gateway_installed`) works: SSH rules, 80/443 when
  Caddy serves an edge, no P2P and no health rule. `NETWORK` then comes from `gateway.meta`.

`edit-config.sh --set gateway_upstream=<ipv4[,ipv4…]> | off` (C3):
- `<list>`: refused unless `tn_gateway_from_rules_ok` passes for the list (message names
  `firewall-setup.sh --enable --gateway-from`). Sets launch flags `--http.addr 0.0.0.0` and
  `--healthcheck 0.0.0.0:<health port>`; does NOT add the public-RPC limit flags or `--http.api`; records
  `GATEWAY_UPSTREAM=<list>` and, once, `GATEWAY_PREV_HEALTHCHECK=<previous value|none>`. Allowed on every network.
- `off`: `--http.addr 127.0.0.1`; `--healthcheck` back to `GATEWAY_PREV_HEALTHCHECK` (flag removed for `none`);
  both keys unset.
- A node whose unit was not active before the change is left stopped: files are edited, no restart, done line
  `ok:true` with a message that says it stays stopped. An active node gets the usual guarded restart. This guard
  is for this key only; other keys keep today's behaviour.
- Backup, rollback, `--json` and exit codes as the other setters.

## 6. TND `check-node.sh` (D1) and `remove-node.sh` (D2)
- D1, gateway section (when `tn_gateway_installed`): unit enabled and active; image held; the three listeners
  bound where `gateway.meta` says; `/health` 200; `/ready` state reported (not an issue when the node is down);
  Caddy block present when `FRONT=caddy`; same-host: the node has `--healthcheck`. On a host with a gateway and no
  node the script says so in one line, runs this section and skips the node sections without an error.
- D1, validator section (when `.node-meta` has `GATEWAY_ALLOW_FROM` or `GATEWAY_UPSTREAM`): the rules exist; the
  binds are `0.0.0.0` exactly when `GATEWAY_UPSTREAM` is set; a wildcard RPC bind without `GATEWAY_UPSTREAM` and
  without a public-RPC edge is an issue; the advertised RPC URL is https with no ws.
- D2: a `remove_gateway` step in the style of `remove_alerts` (fixed paths, no library call, before the node
  stops): unit, container, `/etc/telcoin/gateway`. On a host with only a gateway it points at
  `setup-gateway.sh --remove`.

## 7. TND tests and release files (E1-E5, F1, F2)
- Fixture tests under `tools/tests/` in the style of `alerts_test.sh` / `caddy_test.sh` (`TN_ROOT_PREFIX`,
  PATH stubs, `finish` last): expected argument line and unit text per mode; every refusal of §3.1 leaves the
  tree byte-identical; a second `--enable` with the same inputs writes nothing and restarts nothing; a failure
  after the first write restores the previous files; Caddy toggles keep the third block; `--gateway-from`
  survives `--reset`; `gateway_upstream` on a stopped unit never calls `systemctl start|restart`.
- `tools/tests/gateway_smoke.sh` (E5; not picked up by `run.sh`): real image, stub worker, health and redirect
  servers on loopback, the argument line from `gw_render_args`, no systemd.
- F1: OPERATOR.md, README.md, CHANGELOG.md (`## Unreleased`), AGENTS.md (a short gateway section).
  F2 (last): two rows in `update-scripts.sh` `SCRIPTS`, the `--refresh` hint when `lib/gateway.sh` changed, version
  bumps to 2.2.0, `*.sha256` sidecars by `tools/gen-checksums.sh`. MANIFEST, MANIFEST.asc, RELEASE and
  `install.sh` are not touched (the release ceremony is the maintainer's).

## 8. DG names: `config.sh`, `devnet-lib.sh`, `benchmark/config.sh` (unit G1)

Fleet arrays (parallel, length 7):
| i | `INSTANCE_NAMES` | `NODE_ROLES` | `ZONES` | `NODE_NAMES` | `STATIC_IP_NAMES` | `GATEWAY_MODES` | `GATEWAY_FOR` |
|---|---|---|---|---|---|---|---|
| 0-2 | validator-N-devnet | validator | (unchanged) | node1..3 | (unchanged) | same-host | "" |
| 3 | validator-4-devnet | validator | europe-west4-a | node4 | (unchanged) | standalone | "" |
| 4 | observer-5-devnet | observer | europe-west2-b | node5 | (unchanged) | same-host | "" |
| 5 | rpc-6-devnet | rpc | us-west2-b | node6 | rpc-6-devnet-ip | none | "" |
| 6 | gateway-4-devnet | gateway | europe-west4-a | gateway4 | gateway-4-devnet-ip | none | node4 |

`EXECUTION_ADDRESSES[5]` = a fixed devnet address for rpc-6 (it never stakes), `[6]` = the zero address (a
gateway has no keys; a placeholder keeps the shared instance-creation script's metadata well-formed).
Roles: `validator` (genesis committee), `observer` (node 5, stakes later), `rpc` (non-validator public RPC; keys
generated like an observer, node-info under `genesis/observers/`), `gateway` (no node, no keys).

New variables: `TN_GATEWAY_ENABLE=1`; `TN_ADMISSION_VIA="native"` (`devnet` = the old devnet-rendered
network-config path); `RPC_HOSTNAME="rpc.${BASE_DOMAIN}"`; `RPC_URL="https://${RPC_HOSTNAME}"`;
`NODE_RPC_PORT=8545`; `GATEWAY_LISTEN_PORT=8655`, `GATEWAY_PROBE_PORT=8656`, `GATEWAY_METRICS_PORT=9655`;
`GATEWAY_IMAGE_TAG="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway:v0.3.0-devnet"`;
`GATEWAY_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:<placeholder until P1>"`;
`GATEWAY_REDIRECT_URL="${RPC_URL}"`; `DOCKER_IMAGE_TAG="…/adiri:v0.3.0-devnet"`, `DOCKER_IMAGE` (placeholder until
P1); `RELEASE_TAG="v0.3.0-devnet"`; `TN_NODE_SCRIPTS_REF` (placeholder until the PR is pushed);
`ADMISSION_MAPS_DIR="genesis/admission-maps"` (local), `ADMISSION_HOST_DIR="/etc/telcoin/devnet-admission"`;
`VPC_TAG_P2P="devnet-p2p"`, `VPC_TAG_WEB="devnet-web"`, `VPC_TAG_GW_UPSTREAM="devnet-gw-upstream"`;
`P2P_COMMITTEE_WAIT_SECS=300`. The placeholders use the marker the deploy's existing gate already refuses.
Every `LB_*` variable is renamed `LEGACY_LB_*` (same values), read by the teardown only; `GOOGLE_HC_RANGES` and
`HEALTHCHECK_MONITOR_SRC` stay defined but no launch-2 driver opens a rule for them.

Helpers in `devnet-lib.sh` (index = position in the arrays):
| Helper | Behaviour |
|---|---|
| `tn_fleet_check` | rc 0, or one line per problem on stderr and rc 1: unequal array lengths, unknown role, a `standalone` node without exactly one `gateway` entry naming it in `GATEWAY_FOR`, a `gateway` entry naming no node, a mode other than `none` on `rpc`/`gateway`. With `TN_GATEWAY_ENABLE` not 1 the two gateway arrays are not checked |
| `tn_indices_by_role <role>[,<role>…]` | prints matching indices, one per line |
| `tn_node_indices` | indices with role `validator`, `observer` or `rpc` (hosts that run a node) |
| `tn_is_node_index <i>` | rc 0/1 |
| `tn_internal_ip <i>` / `tn_external_ip <i>` | by index, through `tn_node_int_ip` / `tn_node_ext_ip` |
| `tn_gateway_mode <i>` | prints `same-host`, `standalone` or `none` (`none` for a missing entry or `TN_GATEWAY_ENABLE` not 1) |
| `tn_gateway_host_index <i>` | for a node index: the index of the host running its gateway (itself for same-host, the `gateway` entry for standalone); rc 1 for `none` |
| `tn_public_domain <i>` | `validator`/`observer`: `<NODE_NAME>.<BASE_DOMAIN>`; `rpc`: `RPC_HOSTNAME`; `gateway`: the domain of the node it fronts |
| `tn_admin_domain <i>` | `admin.<NODE_NAME>.<BASE_DOMAIN>` for a node host that runs Caddy (same-host gateway nodes and `rpc`); rc 1 otherwise |
| `tn_admission_mode <i>` | `closed` for `validator`/`observer`, `open` for `rpc` |
| `tn_role_dir <i>` | `validators` for `validator`, `observers` for `observer` and `rpc` |

Bench rule (binding for G1 and checked in review): after G1, `CONFIG_FILE=benchmark/config.sh` yields the same
effective values as before for every variable a `benchmark/` script or a root driver reads on the bench path.
`benchmark/config.sh` gets ONE block right after it sources the root config: its own `TN_NODE_SCRIPTS_REF`
(d9446f720026fa5ce8b64fce9074e56b05b3f4eb), `DOCKER_IMAGE` / `DOCKER_IMAGE_TAG` defaults (the v0.2.0-devnet
values), `TN_ADMISSION_VIA=devnet`, `TN_GATEWAY_ENABLE=0`, empty `GATEWAY_MODES` / `GATEWAY_FOR`, and whatever
else the before/after dump shows moving. Proof = the two dumps (see `units.md`, G1).

Rule for every root driver the bench also calls (`devnet-lib.sh`, `devnet-keygen.sh`, `devnet-genesis-build.sh`,
`devnet-network-config.{sh,py}`, `devnet-finalize.sh`): with `TN_ADMISSION_VIA=devnet` and `TN_GATEWAY_ENABLE=0`
it runs the same remote commands with the same arguments as on `main` 884b760, and the bench's own tests
(`benchmark/tests/`) pass unmodified unless the unit's brief lists a test file.

## 9. DG admission, keygen, finalize (units G2, N1, N2, Z1)

Admission per node with `TN_ADMISSION_VIA=native` (to be confirmed by rehearsal RH0, see §14):
| Role | `--admission` | `--trusted-nodes` map | `--bootstrap-peers` map |
|---|---|---|---|
| validator | closed | rpc-6 | the four genesis validators |
| observer (node 5) | closed | rpc-6 | the four genesis validators |
| rpc | open | (not passed) | the four genesis validators |

- N1: `devnet-network-config.py … maps --out-dir <dir>` writes, per node name N in `--nodes` (roles `validator`,
  `observer`, `rpc`): `N.bootstrap-peers.yaml` (map BLS key -> `{primary: {network_address, network_key},
  workers: [{…}]}`, the committee's `bootstrap_servers` verbatim) and, except for `rpc`, `N.trusted-nodes.yaml`
  (map BLS key -> `{primary: {…}, workers: {0: {…}}}` for each `rpc` node). `/ip4` addresses only.
  `validate --native --node N FILE` parses a `network-config` written by `setup-node.sh` and compares mode,
  `trusted_nodes` and `committee_peers` with what `maps` gives (by content, not byte for byte). The existing
  `render` / `validate` / `merge` are unchanged.
- N2: native mode renders the maps locally; `--yes` installs them on each node host as
  `${ADMISSION_HOST_DIR}/bootstrap-peers.yaml` and `…/trusted-nodes.yaml` (root:root, dir 0755, files 0644) and
  reads them back; `--verify` checks the installed maps and, once the node is finalized, the native
  `network-config` with `validate --native`. Targets = node indices only.
- G2: keygen runs on node indices only. In `domain` mode with `TN_GATEWAY_ENABLE=1`: `--rpc-http
  https://<tn_public_domain>/` and no `--rpc-ws` for a node with a gateway; no RPC flag for `rpc` (its URL is
  set by the public edge in step 15). Node-info goes to `genesis/<tn_role_dir>/<NODE_NAME>.yaml`. The genesis
  build finds node 5 by role `observer`, not by index 4.
- Z1: finalize visits node indices only. Native mode adds `--admission <mode> --bootstrap-peers
  ${ADMISSION_HOST_DIR}/bootstrap-peers.yaml` and, when the map exists, `--trusted-nodes …/trusted-nodes.yaml`;
  the readiness gate needs the maps on the host instead of a pre-installed `network-config`; `--public-rpc-url
  https://<tn_public_domain>` and a `--public-ws-url` only for a node without a gateway; check A3 becomes
  `validate --native`; new check A6: `.node-meta` has `ADMISSION_MODE`, `BOOTSTRAP_PEERS_FILE` and (when passed)
  `TRUSTED_NODES_FILE`. The modes `--stage-only`, `--start-all`, `--defer-start`, `--verify` keep their meaning.

## 10. DG drivers (units GW, Z2, PC, FW, SU, TD, RS, SK, TX, OB)

Common to the three new drivers: `set -euo pipefail`, source `devnet-lib.sh`, `tn_fleet_check` first, targets by
index, instance name or node name, logs under `logs/<stamp>-<driver>/`, IAP ssh through the lib's wrappers with
one retry on rc 255 for read-only probes, exit 0 ok / 1 a host failed / 2 usage or config.

`devnet-gateway.sh [--yes] [--status] [--rpc-edge] [target …]` (GW). No flag = dry run that prints each command.
- `--yes`, per node with a gateway, in array order. same-host: on the node host
  `sudo bash <scripts>/setup-gateway.sh --enable --yes --json --mode same-host --network devnet --image
  "${GATEWAY_IMAGE}" --domain <tn_public_domain> --front caddy --redirect-queries "${GATEWAY_REDIRECT_URL}"`.
  standalone: on the validator `firewall-setup.sh --json --enable --gateway-from <gateway internal IP>` then
  `edit-config.sh --json --set gateway_upstream=<gateway internal IP>`; on the gateway host
  `setup-gateway.sh --enable --yes --json --mode standalone --network devnet --image … --domain
  <tn_public_domain> --front caddy --upstream <validator internal IP> --rpc-port "${NODE_RPC_PORT}"
  --health-port "${DEFAULT_HEALTHCHECK_TCP_PORT}" --redirect-queries …`. It asserts each done line `ok:true`,
  never readiness.
- `--rpc-edge --yes`: on each `rpc` host `install-caddy.sh --json --phase rpc-enable --rpc-domain
  "${RPC_HOSTNAME}" --yes` (run after the coordinated start; it restarts that node once).
- `--status`: `setup-gateway.sh --status --json` on every gateway host, one line each.

`devnet-postcheck.sh [target …]` (Z2), read-only, run after the start. Per gateway host: status `installed`,
`active`, `ready` true and `issues` 0; listeners on loopback (`ss -ltn`). Per node behind a gateway: RPC bound to
127.0.0.1 only (standalone node: 0.0.0.0, and the port answers from the gateway host and not from another
fleet VM); `tn_nodeMode` over `https://<domain>` is not this node's own answer (403, or the query node's);
a WebSocket upgrade to `wss://<domain>` fails; the certificate is valid; `curl 127.0.0.1:<metrics port>` on the
gateway host shows `tn_worker_gateway_upstream_ready`. Per `rpc` node: https and wss answer, admission Open.
Prints one `POSTCHECK <host> <check> ok|FAIL <detail>` line per check.

`devnet-p2p-committee.sh [--yes] [--status] [--off] [target …]` (PC). Default targets = role `validator`; node 5
only when named. Per host, one at a time: poll `tn_admissionSnapshot` on loopback until the rule of §1 holds (at
most `P2P_COMMITTEE_WAIT_SECS`, else exit 3 with nothing changed on that host); `firewall-setup.sh
--p2p-committee on` (retried while it answers "not authoritative"); `tn-p2p-allow-sync check` must exit 0; the
chain head must advance before the next host. A failure stops the sweep; later hosts are reported untouched.

FW: `setup-firewall.sh` sources the config by its own path (not the cwd), keeps tags per host (`devnet-p2p` on
node hosts, `devnet-web` on Caddy hosts, `devnet-gw-upstream` on a standalone-fronted validator; removes
`lb-health-check` everywhere and `http-server`/`https-server` from hosts without Caddy), and ensures the rules:
`devnet-allow-consensus` INGRESS udp:49590,49594 from 0.0.0.0/0 to `devnet-p2p`; `devnet-allow-web` INGRESS
tcp:80,443 from 0.0.0.0/0 to `devnet-web`; `devnet-allow-gateway-upstream` INGRESS tcp:8545,43174 from the
gateway's internal /32 to `devnet-gw-upstream`. It deletes `devnet-allow-consensus-egress`,
`devnet-deny-consensus-egress`, `devnet-allow-health-check`, `devnet-allow-healthcheck-from-kuma`. It fails
(exit 1) when a rule call fails. `devnet-firewall.sh --enable` runs `firewall-setup.sh --json --enable` on every
host (plus `--p2p-anywhere` on `rpc`), without `TN_LB_HC_RANGES`; its port mode visits node indices only.
SU: `devnet-startup.sh` also installs `nftables` and `ufw`.
TD: `devnet-teardown.sh` (dry run without `--yes`) additionally stops the txgen unit and deletes the LB stack by
its `LEGACY_LB_*` names in reverse creation order (forwarding rule, https proxy, certificate, URL map, backend
service, health check, instance groups `${LEGACY_LB_NAME_PREFIX}-ig-N`, the LB address, the LB firewall rule);
each absent piece is reported and skipped. Static node IPs stay.
RS: `devnet-release-sign.sh` adds `GATEWAY_IMAGE_DIGEST` (one line, the value of `GATEWAY_IMAGE`) to the signed
names when `GATEWAY_IMAGE` is set, and `verify` checks it against the config.
SK: `devnet-stake-node5.sh` finds node 5 by role, refuses an empty or non-numeric epoch at both guards, and
reads node 5's head and mode and the reference head over IAP on loopback.
TX: `devnet-txgen.sh` step 9 enables and restarts the unit and reads only journal lines of the new start.
OB: `devnet-observability.sh --staged` works on stopped nodes (flags and agent installed, no node restart, no
quorum sweep); `devnet-dashboards.sh` publishes `tn_admin_domain` through `install-caddy.sh --phase enable`.

## 11. DG deploy steps (unit DP) and the shim (unit SH)
`devnet-deploy.sh [--yes] [--from N] [--to N] [--only N]`, `LAST_STEP=20`:
| # | Step | Runs |
|---|---|---|
| 1 | static IPs | `common/reserve-static-ips.sh` |
| 2 | VMs | `common/create-instances.sh` |
| 3 | boot wait | serial-console marker on every index |
| 4 | DNS pause | prints the records of the new topology (`tn_public_domain`, `tn_admin_domain`, what to delete), waits for ENTER |
| 5 | keygen | `devnet-keygen.sh` |
| 6 | genesis + manifest | `devnet-genesis-build.sh`, `devnet-release-sign.sh prepare` |
| 7 | admission maps | `devnet-network-config.sh --yes` |
| 8 | VPC rules | `setup-firewall.sh` |
| 9 | obs VM | `common/create-obs-instance.sh --wipe-data` |
| 10 | finalize, stage only | `devnet-finalize.sh --stage-only` (the signature gate fires before anything is staged) |
| 11 | host ufw | `devnet-firewall.sh --enable` |
| 12 | observability, staged | `devnet-observability.sh --staged` |
| 13 | gateway installs | `devnet-gateway.sh --yes` |
| 14 | coordinated start | `devnet-finalize.sh --start-all` |
| 15 | rpc-6 public edge | `devnet-gateway.sh --rpc-edge --yes` |
| 16 | post-checks | `devnet-postcheck.sh` |
| 17 | dashboards | `devnet-dashboards.sh` |
| 18 | contracts | `devnet-contracts.sh --yes` |
| 19 | txgen | `devnet-txgen.sh --yes` |
| 20 | committee firewall | `devnet-p2p-committee.sh --yes` |
SH: `tasks/l2-shim/` in DG: fake `gcloud`, `ssh`, `scp` (and what else the drivers call outside the repo) on a
PATH directory, a state directory, a call log, and `run.sh [--from N] [--to N]` that runs `devnet-deploy.sh`
against them and fails on any call that reached a real binary.

## 12. What no unit may do
Edit `common/` or either `tn-node-deployment/` submodule; touch the main working tree outside new files under
`tasks/`; change a bench-path command; widen an interface of this file on its own.

## 13. Known gaps the units report, not fix
The native dashboard phase takes a password, not a stored hash (OB reports how the devnet's shared hash can be
used); `firewall-setup.sh` and `install-caddy.sh` ignore unknown flags; `--p2p-committee` has no `--json`;
Alloy takes one config file (no gateway scrape fragment).

## 14. Amendments
- A-1 (2026-11-17T19:55Z, to §3; from A2's hand-back, sent to A1 while it was writing). (a) Every boolean
  `GW_ST_*` is the literal `true` or `false`; `GW_ST_CADDY_BLOCK` is empty with front `none`; `GW_ST_ISSUES`
  holds the issue count; string fields are empty when no gateway is installed. (b) `gw_validate_inputs` also
  refuses a missing mode, a missing redirect URL, a missing image where the network has no pin, and bad syntax of
  the redirect URL, the upstream, the domain and the trusted-proxies list; the script checks only the action
  count, unknown arguments, missing values, flags outside their action, the vocabulary of `--mode` / `--front` /
  `--network`, port syntax and the image reference shape. (c) The script takes no lock and appends "Nothing was
  changed." to `GW_ERR` on rc 1; the library takes the update lock and must work on a host with no node.
- A-2 (2026-11-17T19:55Z, to §2; from C1's hand-back). `tn_gateway_from_rules_ok` reads `ufw status` itself
  (the repo's `ufw_has_allow` cannot match a source); an empty list is rc 0 when ufw is active; a CIDR source
  also matches by its network address; `TN_GATEWAY_FROM_MISSING` is a global, so the function is never called
  inside `$(…)`. `tn_node_health_bind` returns 2 for any launch-file problem. The constants sit in a brace
  group (indented), not at column 0.
- A-3 (2026-11-17T19:55Z, to §5; from C3's hand-back). `GATEWAY_PREV_HEALTHCHECK` holds the raw previous launch
  value (a bare port stays a bare port), so `off` restores the flag exactly; with the key missing, `off` leaves
  `--healthcheck` as it is and warns.
- A-4 (2026-11-17T19:55Z, to §8). The images are pushed: `DOCKER_IMAGE` =
  `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:0aec3e7cd1457488ed052a3cff8371a235f213f57e9fc727a3a62fb7abad11c1`,
  `GATEWAY_IMAGE` =
  `us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:8b887098f5cc5cb5ebc591bc82b1347513b23ae3ecca4f22787b2e4204f8c231`
  (the orchestrator replaces the two image placeholders after G1 hands back). `node-record-api` could not be
  built at 5533ff73a (challenge 28): no unit may depend on its image.
- A-5 (2026-11-17T20:00Z, to §9; from rehearsal RH0, `tasks/l2/rh0-report.md`). The admission table of §9 is
  CONFIRMED on the real image with network-config files written by tn-node-deployment's own renderer: a
  validator whose `committee_peers` lacks a member exits 1 at epoch 0 ("committee_peers: missing validator …");
  the open RPC node syncs and shows on the validators as `trusted`, `admitted: true`; node 5 (closed, trusted =
  the RPC node) syncs ONLY through the RPC node (the validators complete the handshake and drop it). Consequences:
  (a) N1: the maps are written with each BLS key as a plain `key:` line at column 0. PyYAML's `safe_dump` emits
  keys longer than 128 characters as `? key`, which the native renderer refuses. (b) Start order: the RPC node
  must be up for node 5 to sync; in the coordinated start they start together and node 5 connects after its
  trusted-dial backoff (45 s in the rehearsal), so any wait for node 5 allows for that. (c) While the RPC node
  is down, node 5's snapshot is Grace / Unresolved, so the committee firewall cannot be turned on there then.
  (d) An idle chain's head moves only at epoch closes: a check that needs "blocks advance" before the transaction
  generator runs must wait up to one epoch or use the consensus round, not the head. (e) A validator's snapshot
  was authoritative 3.7 s after a fresh start and 1.2 s after a restart. (f) The node image has no curl:
  in-container probes are not available; probe from the host.
- A-6 (2026-11-17T20:00Z, to §4; from B's hand-back). Only `gateway-enable` is gated; `gateway-status`,
  `gateway-check-dns` and `gateway-disable` are not (a site can always be taken down). `gateway-status`
  `installed` / `running` describe Caddy; `port` and `probe_port` are numbers or `null`. The block relies on
  `reverse_proxy`'s default `X-Forwarded-For` handling (Caddy 2.5 and later set it to the connecting peer and
  drop a client-sent value unless the peer is a trusted proxy, which the generated file never configures).
  The generated block was not validated by a Caddy binary by its author: unit E2 does that. (Done: Caddy 2.8.4
  and 2.11.9 both accept it; behaviour smoke 47/47 on each.)
- A-7 (2026-11-17T20:20Z, to §9-§11; details the DG units share).
  (a) Local admission maps: `${GENESIS_WORKSPACE:-${REPO_ROOT}}/${ADMISSION_MAPS_DIR}/<NODE_NAME>.bootstrap-peers.yaml`
  and `…/<NODE_NAME>.trusted-nodes.yaml` (no trusted file for `rpc`). On the host:
  `${ADMISSION_HOST_DIR}/bootstrap-peers.yaml` and `${ADMISSION_HOST_DIR}/trusted-nodes.yaml`. N2 installs
  them; Z1's gate needs them present with the same sha256 as the local files.
  (b) The `--nodes` context every caller builds for the Python renderer is `<NODE_NAME>=<role>` for the indices
  of `tn_node_indices`, in array order (gateway entries never appear). With `TN_ADMISSION_VIA=devnet` the roles
  are only `validator` and `observer`, as today.
  (c) Dashboards (contract §13 resolved for the devnet, no change to tn-node-deployment): `devnet-dashboards.sh`
  reads the UI password from the Secret Manager secret named by `TN_ADMIN_PASSWORD_SECRET` (default
  `devnet-admin-dashboard-password`; the value never touches argv, env or a log) and pipes it to
  `install-caddy.sh --json --phase enable --domain <tn_admin_domain> --username "${TN_ADMIN_AUTH_USER}"
  --password-stdin` on each host that has an admin domain. `devnet-dashboards.sh --preflight` (read-only: the
  secret exists and holds one line of 16 or more characters) exits 0 or 1; `devnet-deploy.sh` runs it among its
  pre-gates when `TN_ADMIN_DASHBOARD=1`, so a missing secret stops the deploy before step 1 and not at step 17.
  (d) `devnet-deploy.sh` pre-gates also run `tn_fleet_check`.
  (e) Every driver takes its node hosts from `tn_node_indices` and its gateway hosts from
  `tn_gateway_host_index`; none loops over `"${!INSTANCE_NAMES[@]}"` unless it means every VM (steps 1-4, the
  teardown, `devnet-firewall.sh --enable`).
  (f) Probes run on the HOST over IAP (`curl` exists on the VM, not in the node container).
- A-8 (2026-11-17T20:45Z, to §8's bench rule; from G1's hand-back). G1's bench proof holds for the bench's effective
  configuration (the dump differs only by new names that nothing under `benchmark/` reads, and the `LB_*` ->
  `LEGACY_LB_*` rename). But five bench TEST modules read the bench's scripts ref and image from the ROOT
  `config.sh` (`test_node_image.py` `scripts_ref()`, used by `test_host_probe.py`; and `test_node_deploy.py`,
  `test_node_shapes.py`, `test_local_ssd_deploy.py`, which build a base from `git show ae43747:benchmark/config.sh`
  plus the current root config): they fail once the root pins differ from the bench's. They cannot "pass
  unmodified". Resolution: a unit BT, after wave 2 and after `main` (8abb488 or later) is merged into
  `l2/launch-2`, makes those tests read the bench's own pins (`benchmark/config.sh`), changing nothing else in
  them. Units G2, N1, N2, Z1: a failure in one of those five modules is this known cause, not yours.
  G1 additions accepted: `tn_fleet_check` also refuses an unknown gateway mode and a gateway entry that fronts a
  node whose mode is not `standalone`; `tn_indices_by_role` with no argument is rc 1; indices are validated
  (`x`, `7`, `05` are rc 1). Note: with `TN_GATEWAY_ENABLE` not 1 no node has an admin domain.
  The image digests are pinned in `dg-l2/config.sh` (7e63e54); only `TN_NODE_SCRIPTS_REF` still holds a marker.
