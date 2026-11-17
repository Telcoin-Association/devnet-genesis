Validators are meant to keep their JSON-RPC private and take transactions through telcoin-network's `worker-gateway`, a small public JSON-RPC front that hands transaction submissions to one node's worker and proxies every other call to a query endpoint.
These scripts had no support for it: no installer, no service, no Caddy site, no firewall rule for a gateway host and no checks.
This branch adds `setup-gateway.sh` and the validator side it needs, for two layouts: the gateway next to the node, or on its own host in front of a validator's private address.
No released gateway image exists yet, so today it runs on devnets only; testnet and mainnet refuse it until a scripts release pins a digest.

## What is added

- `setup-gateway.sh` with `lib/gateway.sh`: `--enable`, `--status`, `--refresh` and `--remove`, each with `--json`, in the shape of `setup-alerts.sh` (exit 0 done, 1 refused or rolled back, 2 older libraries, 3 a step failed after something changed). It runs the image as `telcoin-gateway.service` under Docker (host network, uid 1101, read-only, no capability, `--pull=never`) and keeps its settings in `/etc/telcoin/gateway/gateway.meta`. It never stops, starts or restarts the node, never edits the node's launch file or `.node-meta`, and opens no firewall port itself (with `--front caddy`, the `install-caddy.sh --phase=gateway-enable` step it runs opens 80 and 443). An enable whose inputs equal what is installed changes nothing; a failure after the first write puts the previous service file and meta back. Unlike the other add-ons it runs on a host with no node. `--front caddy` (the default) serves `https://<domain>/` through this host's Caddy; `--front none` listens on `0.0.0.0:8655` (the default `--listen-port`) over plain HTTP and leaves the firewall to the operator. The probe (default 8656) and metrics (default 9655) listeners stay on `127.0.0.1`.
- `install-caddy.sh`: a third managed block, `tn-gateway`, and the phases `gateway-status`, `gateway-check-dns`, `gateway-enable` and `gateway-disable`. The block passes `POST` to the gateway with bodies capped at 2 MB, passes `GET` and `HEAD` on `/health`, `/ready` and `/ready/any` to the probe listener, answers a CORS preflight as the public-RPC site does, and answers a WebSocket upgrade or any other method with `405`. `gateway-enable` runs on a host with no node, changes nothing when the block on disk is current and Caddy runs, and starts a stopped Caddy. `rpc-advertise` and `rpc-unadvertise` put the gateway's `https://<host>/` (and no WebSocket URL) into the node's `node-info.yaml`, or clear it, with one guarded node restart and no Caddy change; `rpc-advertise` refuses unless `https://<host>/health` answers 200 from the node's host. A public-RPC site and a gateway site are never served from one host.
- `firewall-setup.sh --gateway-from <ipv4|cidr>[,...]|none`, with `--enable` or `--reset`: two ufw rules per source on every network, one to the RPC port and one to the health port, placed after the health-port block. The list is stored as `GATEWAY_ALLOW_FROM` in `.node-meta` and applied again by every `--enable` and `--reset`, like the SSH and P2P lists. While the node is bound for a gateway (`GATEWAY_UPSTREAM` set), `--gateway-from none`, a list that leaves out a bound host, and `--reset` are refused before any change. On a host with a gateway and no node, `--enable` applies the SSH rules and, with the Caddy site, 80 and 443, and keeps the SSH list in `gateway.meta`.
- `edit-config.sh --set gateway_upstream=<ipv4>[,...]|off`: for a validator whose gateway runs on another host, sets `--http.addr 0.0.0.0` and `--healthcheck 0.0.0.0:43174` and records the previous `--healthcheck`. It adds no public-RPC limit flag and no `--http.api`. It is refused unless ufw is active, holds both rules for every listed address, has a default incoming policy of deny or reject, and has no rule that lets any address in to either port. It is also refused when the RPC already listens on every interface, and while the node is starting, stopping or waiting for an automatic restart. A running node restarts after the quorum check and the epoch wait; a stopped node stays stopped. `off` sets `--http.addr` back to `127.0.0.1` and `--healthcheck` to its recorded value.
- `check-node.sh`: a gateway section (service, image held, the three listeners, `/health`, the Caddy block, and in same-host mode the node's health port; `/ready` is shown and not counted), and on a validator with `GATEWAY_*` keys an upstream section (the rules per host, the binds against `GATEWAY_UPSTREAM`, a firewall that admits more than the gateways, an advertised `https` URL without WebSocket). A host with only a gateway skips the node sections.
- `remove-node.sh`: removes a same-host gateway (service, container, `/etc/telcoin/gateway`) before it stops the node, as it does the private alerts. It keeps the image and the Caddy site, names the commands that remove them, and warns when `node-info.yaml` still advertises the gateway. It never removes a gateway that runs on its own host; on such a host it also leaves a node's leftover files and points at `setup-gateway.sh --remove`.
- `update-scripts.sh`: `setup-gateway.sh` and `lib/gateway.sh` join the updater's list. When an update changed either on a host that has the gateway's service, the updater prints the `setup-gateway.sh --refresh` command; it never runs it. An update leaves the installed service, `gateway.meta` and the running container as they were.
- Release: each script this branch touches moves its version constant to 2.2.0, and the checksum sidecars are refreshed, with new ones for `setup-gateway.sh` and `lib/gateway.sh` (`ui/requirements.txt.sha256`, stale since the click bump in #63, is refreshed too).
- Docs: OPERATOR.md section 4.15 (both layouts, the undo order, the advertisement, status fields, refresh, remove, limits, troubleshooting), the README script table and per-script changelog entries, one CHANGELOG entry, the `scripts-v2.2.0` release note (`CHANGELOG/scripts-v2.2.0.md`) and the AGENTS.md rules.

## The two shapes

Same host, behind this host's Caddy. Testnet or devnet only; the node's launch line needs `--healthcheck` (the testnet health add-on adds it, elsewhere it is added by hand):

```bash
sudo bash install-caddy.sh --phase=gateway-check-dns --gateway-domain gw.example.org
sudo bash setup-gateway.sh --enable --mode same-host --domain gw.example.org \
  --image us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:<digest> \
  --redirect-queries https://rpc.example.org/
sudo bash setup-gateway.sh --status
sudo bash install-caddy.sh --phase=rpc-advertise --rpc-domain gw.example.org   # once /health answers
```

Standalone, the only mainnet layout: a validator at `10.0.0.12` and a gateway host at `10.0.0.20` named `gw.example.org`, with a private network between them. The order matters, because the validator refuses to listen until its firewall admits the gateway host:

```bash
# on the validator
sudo bash firewall-setup.sh --enable --gateway-from 10.0.0.20
sudo bash edit-config.sh --set gateway_upstream=10.0.0.20
# on the gateway host (no node, Docker installed; --network is required here)
sudo bash setup-gateway.sh --enable --mode standalone --network devnet \
  --upstream 10.0.0.12 --domain gw.example.org \
  --image us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:<digest> \
  --redirect-queries https://rpc.example.org/
sudo bash firewall-setup.sh --enable --ssh-from 198.51.100.7/32
# on the validator, once https://gw.example.org/health answers from there
sudo bash install-caddy.sh --phase=rpc-advertise --rpc-domain gw.example.org
```

The undo, with `gateway_upstream=off` before the rules go (`--gateway-from none` is refused while the node is bound):

```bash
sudo bash setup-gateway.sh --remove                        # gateway host
sudo bash install-caddy.sh --phase=rpc-unadvertise         # validator, if advertised
sudo bash edit-config.sh --set gateway_upstream=off        # validator
sudo bash firewall-setup.sh --enable --gateway-from none   # validator
```

## Behaviour an existing operator should know about

On a host that never runs a gateway, this is what changes:

- `firewall-setup.sh --ssh-from` and `--p2p-from` get a fix. The cleanup of stale sources compared the new list with the stored one as text, while ufw stores `1.2.3.4/32` as `1.2.3.4` and a CIDR by its network address (`10.0.0.5/24` as `10.0.0.0/24`). The trigger is a stale entry that ufw stores as the same rule as a kept one, most simply a source re-entered in the other spelling, such as `--ssh-from 1.2.3.4` after `--ssh-from 1.2.3.4/32`: ufw skips the new allow as an existing rule, then the cleanup deletes the old spelling, which ufw resolves to that same rule. For the SSH list that is a lockout. On ufw 0.36.2 in an Ubuntu 24.04 container, a port-22 rule added as `1.2.3.4/32` was removed by a delete written `1.2.3.4`, and a rule added bare was removed by a delete written with `/32`. A list re-entered in the same spelling was never affected. One comparison in ufw's stored form now serves the SSH, P2P and gateway lists, the health-port keep check and the skip of the fixed SSH ranges.
- `install-caddy.sh`: every Caddyfile writer now rebuilds the file from three managed blocks, and the hostname clash check and the teardown count all three. `rpc-disable` behaves as before unless `.node-meta` says `RPC_ADVERTISED_VIA=gateway` (an advertisement made by `rpc-advertise`); then it removes only the public-RPC site and leaves `node-info.yaml` and the keys alone. `rpc-enable` refuses while a gateway site or a gateway advertisement exists.
- `firewall-setup.sh --json --status` gains a `gateway_from` field, and the status screen and the expected-rules list gain two rows per gateway source. A Caddyfile that holds the gateway site counts as a public edge, so 80 and 443 survive `--reset`. A fixture checks that the ufw calls of a host without `GATEWAY_ALLOW_FROM` equal a recorded baseline.
- `remove-node.sh`: its scan for other installs matched the gateway image's name and would have offered the gateway's service and container as a stray install; it now knows them.
- `edit-config.sh` only gains the new key. Other keys behave as before, including the restart that `--set` gives a node that was stopped (read from code).
- `lib/common.sh` sources `lib/gateway.sh` at its end when the file is present, the way it sources `lib/alerts.sh`.
- `update-scripts.sh` lists the two new files for every host, so it installs them where no gateway runs too (read from code); it prints the refresh command only on a host that has the gateway's service.

## Image trust

The gateway runs only from a digest, `<repository>@sha256:<64 lowercase hex>`; a tag is refused. On devnet the repository must be `us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway` (`GW_DEVNET_IMAGE_REPOS` in `lib/gateway.sh`). On testnet and mainnet only `GW_TESTNET_IMAGE_PIN` or `GW_MAINNET_IMAGE_PIN` is taken. Both are empty in this branch, so `--enable` there refuses with `this scripts release pins no worker-gateway image for <network>`. Before it writes anything, the enable pulls the digest when Docker lacks it and runs the image's `--help` under a time limit, refusing an image that lacks a flag the service passes; the service itself never pulls.

The network that picks the rule is checked. On a node host it must equal the node's network, and `--refresh` refuses a `gateway.meta` that names another. On a host with no node, the upstream's `eth_chainId` must belong to the network given; an upstream that does not answer within 3 seconds only warns, and `--status` checks again later. When a scripts release changes a pin, `--refresh` without `--image` moves the gateway to the new pin, and until then `--status` counts the old image as an issue.

No released worker-gateway image exists. Before this is usable on testnet or mainnet, telcoin-network has to build and publish one (no CI job builds it today, and its `--version` prints `tn-worker-gateway 0.1.0` with no commit), and a signed scripts release has to set the two pins.

## How it was tested

Fixture tests (no root, Docker or network needed). The whole suite ran on the branch head under bash 5.3.9 and again under bash 3.2.57 in a Linux container: 79 test files, 0 failed, under each. CI ran it on Linux bash 5 and on macOS bash 3.2 as well (see the end of this section). The six new files and the one this branch extends, with their checks per shell (no check failed in either run):

| File | Checks, bash 5.3.9 | Checks, bash 3.2.57 | Covers |
|---|---|---|---|
| `gateway_setup_test.sh` | 475 | 470, 3 skipped | `setup-gateway.sh` and `lib/gateway.sh`: arguments and service text per mode, each refusal leaving the tree unchanged, the image rule per network, the no-op enable, rollback, refresh, remove, `--json`, exit codes, consent |
| `caddy_gateway_test.sh` | 233 | 233 | the block text, every writer keeping it, teardown, the no-op, the refusals, `rpc-advertise` and `rpc-unadvertise`, `rpc-disable` leaving the advertisement |
| `gateway_validator_test.sh` | 214 | 214 | `--gateway-from` (parser, rule order, reset, `none`, mainnet, committee mode, gateway-only host), the source comparison, a host without the key |
| `gateway_check_remove_test.sh` | 115 | 111, 1 skipped | check-node's two sections and `remove_gateway` |
| `gateway_upstream_test.sh` | 109 | 109 | `gateway_upstream`: refusals, a running node, a stopped node that stays stopped, `off`, a failed restart rolled back |
| `gateway_remove_test.sh` | 23 | 23 | `remove-node.sh` on hosts with a gateway and a node's leftover files |
| `updater_manifest_test.sh` (extended) | 275 | 271, 2 skipped | the two new rows in the updater's list with their versions; the `--refresh` hint, printed (never run) only when a gateway file changed and the service exists |

The bash 3.2 container runs as root, and root reads a mode-0000 file, so the four cases that need a file the caller cannot read (`--status` without root, three times, and check-node with an unreadable `gateway.meta`) are skipped there, not run; the two skips in `updater_manifest_test.sh` are for gpg and git, which that container lacks. Under bash 5.3.9 none of the seven files skipped a case. `tools/tests/fwstub.sh` gains a mode that stores sources the way ufw does (`UFW_NORMALIZE=1`, off by default); against the `firewall-setup.sh` from before the fix, `gateway_validator_test.sh` failed 32 of its 214 checks. `addon_oldlib_test.sh` and `host_baseline_test.sh` were adjusted for the new script and phases. `tools/check-network-hits.sh` and the checksum check are clean.

Two smoke scripts need Docker, exit 77 without it, and are not picked up by `run.sh`:

- `tools/tests/gateway_smoke.sh <image>` runs the image with the argument line `gw_render_args` produces and the service's Docker options, against stub worker, health and query servers on loopback. Run on 6361c9c against the devnet image `us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:8b887098f5cc5cb5ebc591bc82b1347513b23ae3ecca4f22787b2e4204f8c231`, the one the rehearsal below also ran: 43 checks, 0 failed, 0 skipped. An earlier run, on an older tree, failed 2 checks from the stub's own delay and a test client that did not reopen closed connections; both were fixed in the stub and the client, not in the scripts. It covers readiness following the health answer (`/ready` answered 200 about 7 s after the stub began accepting), submissions to the worker and every other call to the query endpoint, `405` for `GET` and for a WebSocket upgrade, `413` above 1 MiB, the metrics, and a stop with exit status 0. In the burst, 600 calls in about 0.105 s carrying one forwarded client address got 210 answers of 200 and 390 of 429, within the 100/s, 200-token bucket's bound of 211; a second client address in the same second got 50 answers of 200 out of 50. The limit follows the forwarded client, not the proxy.
- `TN_SMOKE_CADDY_IMAGE=<image> bash tools/tests/caddy_gateway_smoke.sh` (default `caddy:2.8.4`; it takes no image argument) has a real Caddy validate the Caddyfile `caddy_write_managed` builds and serve the gateway block against stub listeners: 47 checks, 0 failed, 0 skipped, on `caddy:2.8.4` (v2.8.4) and again on `caddy:2` (v2.11.9). Caddy dropped a client-sent `X-Forwarded-For: 203.0.113.9`, and the upstream saw only the connecting address. A 3 MB POST got 413.

The two smoke tests and the lints ran on 6361c9c with no tracked file modified. The head, 79fb24e, differs from it by one test file (below), and the two suite runs were repeated on it with the same totals and the same counts in the table.

CI: on the first push (6361c9c) eleven of the twelve checks passed and the fixture tests on macOS bash 3.2 failed one check of `gateway_check_remove_test.sh`. The case calls `scan_custom_installs`, whose container listing runs docker under `timeout`, which macOS does not have; `remove_test.sh` already stubs `timeout` for that function, and the new case now does the same (the last commit, a test-only change). The failure reproduces on Linux with `timeout` hidden from `PATH`, on 6361c9c and not on the head. On 79fb24e all twelve checks pass, including the fixture tests on Linux bash 5 and on macOS bash 3.2.

ufw 0.36.2 in an Ubuntu 24.04 container settled how ufw stores and matches sources: `/32` is shown bare, a CIDR by its network address, a re-add in the other spelling is skipped as existing, and a delete in either spelling removes the rule. The new comparison follows those results.

A local rehearsal on Docker ran four validators and an RPC node, each validator with a gateway container in the standalone layout with `--front none`, started with the argument line this branch's `gw_validate_inputs` and `gw_render_args` produced and the service's Docker options (a bridge network in place of the host network). Its scope was narrow: plain HTTP to private addresses, no Caddy, TLS or ufw; the validators' launch lines carried the two binds `gateway_upstream` sets, written by hand rather than by `edit-config.sh`; and because the record URLs were private plain-http addresses, the RPC node ran with one setting changed (`allow_private_forward_targets: true`; the validators kept `false`). A transfer sent to the RPC node was forwarded to the URL in a validator's record, went through that validator's gateway to its worker, and was in block 2. 20 sequential transfers: 20 confirmed in about 1 s. 400 transfers posted with 8 threads: 400 confirmed in 4.65 s. The gateways turned ready about 11 s after they started. Two earlier local rehearsals covered the network's genesis and admission; of these scripts they called only the network-config renderer in `lib/common.sh`, which this branch does not change, not `setup-node.sh` and no gateway code.

Not run: `setup-gateway.sh` against a real Docker daemon and systemd (the smoke test and the rehearsal start containers with `docker run`); real ACME, so no certificate was issued and `rpc-advertise`'s HTTPS check never met a real name; the scripts driving a real host's ufw; a standalone gateway host in front of a mainnet-like validator end to end (two hosts, ufw, Caddy, the advertisement); INT or HUP in the middle of a change; the service side of `remove-node.sh`'s scan, which reads the real `/etc/systemd/system`.

## Review

Two independent reviews read the branch before the fix commits: one of the validator side (the `lib/common.sh` helpers, `--gateway-from`, `gateway_upstream`, check-node's upstream section) and one of the gateway host side (`lib/gateway.sh`, `setup-gateway.sh`, and the `install-caddy.sh`, `remove-node.sh` and check-node changes). Together they found 3 High, 8 Medium and 25 Low. Every High and Medium is fixed, with a fixture test:

- High: `--gateway-from none`, or a list without the bound host, succeeded while the node's RPC listened on every interface. Now refused.
- High: the source comparison described above.
- High: on a gateway-only host, the mainnet shape, a replaced SSH list left the old sources open. The list now lives in `gateway.meta`.
- Medium, validator side: the stopped-node guard took a crashed node waiting for its restart as stopped; `--reset` opened the wildcard RPC for the length of the re-apply; the bind guard checked that the gateways' rules exist, not that nobody else gets in; removing a monitor source deleted a health rule a gateway still needed.
- Medium, gateway side: the image rule's network was the operator's word; after a pin change `--refresh` refused while `--status` reported no issue; `remove-node.sh` removed a standalone gateway as node leftovers and left its Caddy site up; `rpc-advertise` restarted a validator to advertise a URL it never checked.

14 of the Lows are fixed; the 11 left open are in the next section.

## Limits and what a reviewer should look at

- No released image, and the testnet and mainnet pins are empty: with this branch alone a gateway runs only on a devnet.
- The installer renders no rate-limit flag, so the gateway's defaults apply: per client IP, 100 requests a second (burst 200) and 32 connections, and a batch of K calls costs K. An RPC node that forwards every user's transactions is one client to each gateway. In the rehearsal, a 400-transfer burst sent about 210 forwards to one gateway within a second and drew one `429`; the RPC node set that gateway aside for 30 s and re-sent 61 transfers elsewhere, and none was lost.
- After a `429` the gateway closes the keep-alive connection without `Connection: close` (seen with one client in the smoke test). Whether Caddy then answers an unrelated client with `502` is not verified.
- A restarting gateway answers `503` until its worker is ready (about 11 s in the rehearsal), and the RPC node sets it aside for 30 s.
- A same-host gateway whose `--redirect-queries` is on loopback logs a warning at every start, and a plain-http public redirect URL warns too (the gateway's own messages).
- `rpc-advertise` needs outbound HTTPS from the validator to the gateway's public name, and no flag skips the check.
- Same-host is refused on mainnet. Only on testnet does an add-on add `--healthcheck`; elsewhere a same-host gateway needs the flag added to the launch line by hand.
- Standalone binds the validator's RPC and health check to every interface, guarded by ufw, because the local readers expect loopback and a private-address bind is not offered (read from code). Resetting such a validator's firewall means turning the upstream off around the reset (OPERATOR.md 4.15 gives `gateway_upstream=off`, `--reset`, `--gateway-from <list>`, `gateway_upstream=<list>`), and each `gateway_upstream` change restarts a running node.
- Scripts older than this branch do not know the gateway: an older `remove-node.sh` leaves it running, and an older `firewall-setup.sh --reset` drops its rules while the bind stays on `0.0.0.0`. Update the scripts first.
- Open Lows: stale gateway rules are deleted on the current RPC port only, so after `RPC_PORT` changes the old-port rules stay until `--reset`; `--gateway-from` accepts IPv6, which `gateway_upstream` refuses and the rule check compares literally; on mainnet the Node Manager UI shows the health port as the monitor's, and closing it there leaves the gateway rules and the port open; rules are applied before the list is saved, as for SSH and P2P; a ufw rule without `proto`, or with `on <iface>`, is judged absent; `GATEWAY_PREV_HEALTHCHECK` is not validated by the setter (the launch-flag writer refuses a bad value); there is no put-back on TERM, INT or HUP in the middle of a change (`--status` reports it and a second `--enable` repairs it); a same-host gateway always reaches the node on `127.0.0.1`; the public probe paths have no connection cap or rate limit; `--front none` has no CORS.

Where a maintainer's eye helps most:

- `edit-config.sh` `set_gateway_upstream` and the two `lib/common.sh` helpers it relies on, `tn_gateway_from_rules_ok` and `tn_gateway_ports_private`: together they decide when a validator's RPC may listen on every interface.
- `firewall-setup.sh` `fw_src_canon`, `fw_src_in` and `fw_stale_sources`: this comparison now decides which SSH rules are deleted on every host. `fw_gw_upstream_guard` holds the refusals while a node is bound.
- `install-caddy.sh` `caddy_write_managed` and each of its callers: every writer must carry the third block, or a dashboard or RPC change drops the gateway's site.
- `lib/gateway.sh` `gw_image_allowed`, and the network and chain checks in `gw_validate_inputs`: the image trust rule.
- `remove-node.sh` `rm_leftovers_present`, `remove_leftovers` and `remove_gateway`: the path that keeps a standalone gateway, and the files next to it, in place.

## Follow-ups not in this branch

- telcoin-network: a CI build and release of the gateway image with the commit in `--version`; then a scripts release that pins its digests for testnet and mainnet.
- An installer option for the gateway's per-client rate limit, or the node's forwarder passing the client address with the RPC node listed as a trusted proxy.
- `setup-observability.sh --json` starts a node that was left stopped when it has to add a flag (read from code).
- Comments in `lib/common.sh` and `setup-observability.sh` say a bare `--healthcheck <port>` binds every interface; on telcoin-network main it binds loopback, and `--enable-health` still emits the bare port, so its monitor rule admits a monitor that reaches nothing.
- `firewall-setup.sh`, `install-caddy.sh` and `remove-node.sh` ignore an unknown flag and exit 0, so an older script given `--gateway-from` does nothing and says nothing (read from code).
