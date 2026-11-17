# Review R1b: gateway-host half of tnd-l2-gateway `worker-gateway`

status: done (2026-11-17)

completed sections: image trust; unit and container; rollback; no-change detection; argument rendering and
validators; Caddy block and phases; --status and check_gateway; remove-node; the script (--json, exit codes,
consent, network, lock); bash 3.2 / lints; open questions.

Scope: `lib/gateway.sh`, `setup-gateway.sh`, `git diff origin/main..HEAD` of `install-caddy.sh`,
`remove-node.sh`, and `check_gateway` in `check-node.sh`, at branch HEAD 405af9e.

Counts: High 0, Medium 4, Low 13.

How I verified: a throwaway harness
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/R1b/h/harness.sh`.
It sources the real `lib/common.sh` and `lib/gateway.sh` with a `TN_ROOT_PREFIX` tree. `docker`, `systemctl`,
`curl` and `sleep` are PATH stubs, and the root primitives and the lock are stubbed. Each finding says whether
it was run in the harness ("harness") or traced line by line ("traced").

---

## Findings

### M1 (Medium): the trust rule's network is never checked against anything real; `--refresh` reads it from `gateway.meta`
- Where: `lib/gateway.sh:913-919` (`_gw_refresh_locked`: `_gw_load_meta`, then
  `gw_image_allowed "$GW_V_IMAGE" "$GW_V_NETWORK"`), `lib/gateway.sh:230-242` (network on a node-less host),
  `setup-gateway.sh:417-443`.
- Scenario (harness, scenario `trust-meta-network`): a standalone host with no node runs `--enable` on mainnet
  with `GW_MAINNET_IMAGE_PIN=<repo>@sha256:aaa…`, then `NETWORK=mainnet` in `gateway.meta` is changed to
  `devnet`. `--refresh --image <devnet repo>@sha256:bbb…` returns rc 0 with `applied=[refreshed]`, and the unit
  now runs `sha256:bbb…`, a digest this release does not pin, in front of a mainnet validator. The same thing
  happens with no file edit at all: on a node-less host `--enable --network devnet` is just the operator's word,
  so any digest in the public repository is accepted (`GW_DEVNET_IMAGE_REPOS` is the same `tn-public/worker-gateway`
  repository a mainnet pin would come from). On a node host, refresh never compares `gateway.meta` NETWORK with
  `.node-meta` NETWORK (`sg_resolve_network` computes the node's network and `gw_refresh` ignores it).
- Why it is wrong: contract 3.4 says testnet and mainnet run only the pinned digest. Here the pin is enforced
  only while a file the library does not verify says the right network, and that file decides which rule
  applies.
- Smallest fix: (a) in `_gw_refresh_locked`, when `node_meta_path` exists, refuse unless `GW_V_NETWORK` equals
  `.node-meta` NETWORK (and equals `GW_IN_NETWORK` whenever that is set); (b) for a standalone host, have
  `gw_validate_inputs` ask the upstream for `eth_chainId` (`http://<upstream>:<rpc port>`, which
  `--gateway-from` opens to this host) and refuse a chain id that does not match the claimed network. When the
  upstream does not answer, refuse unless the network is devnet. If the owner does not want (b), say in
  OPERATOR.md that on a gateway-only host `--network` is the trust root.

### M2 (Medium): after a release changes the pin, `--refresh` refuses, and `--status` and `check-node.sh` report the now-unpinned running image as healthy
- Where: `lib/gateway.sh:918-919` (refresh keeps the stored IMAGE and judges it by the new pin),
  `lib/gateway.sh:1083-1091` (`gw_status` checks only that the image is held, not that it is still allowed),
  `check-node.sh:2249`.
- Scenario (harness, scenario `pin-change`): mainnet, enabled with pin A. The scripts update installs a release
  that pins B (for example a gateway security fix). `setup-gateway.sh --refresh` with no `--image` gives rc 1:
  "image refused: mainnet runs only … (B)". `gw_status` gives rc 0, `issues=0`, "ready", image A. The F2 hint
  ("`--refresh` when lib/gateway.sh changed") therefore always fails on testnet and mainnet, and nothing tells
  the operator that the gateway runs an image this release no longer allows.
- Why it is wrong: the pin exists so that the gateway moves to the release's digest. The refresh path refuses to
  do that without an extra argument, and the status path hides the gap.
- Smallest fix: in `_gw_refresh_locked`, when `GW_IN_IMAGE` is empty and `GW_V_NETWORK` is testnet or mainnet,
  set `GW_V_IMAGE` to that network's pin. In `gw_status`, when meta was loaded, call
  `gw_image_allowed "$GW_V_IMAGE" "$GW_V_NETWORK"` and on rc 1 add an issue ("the running image is not the one
  this scripts release pins: run setup-gateway.sh --refresh").

### M3 (Medium): `remove-node.sh` removes a standalone gateway when the host also has an empty node directory, and skips the Caddy step (open point E4)
- Where: `remove-node.sh:925-935` (`rm_leftovers_present`: an existing `/var/lib/telcoin`, empty or not, counts
  as node leftovers), `remove-node.sh:1991-2014` (`json_remove` goes on when leftovers are present),
  `remove-node.sh:2067` and `remove-node.sh:1022-1035,1054` (`remove_gateway` / the `only_gw` test, which only
  forgives `/etc/telcoin` and `/var/backups/telcoin`).
- Scenario (traced): a gateway-only host (standalone, front caddy) also has an empty `/var/lib/telcoin`, for
  example created by a VM startup script or by an earlier partial node install. A UI or driver runs
  `remove-node.sh --json --remove validator service` and expects "no node installed". Instead the leftovers path
  runs `remove_gateway`: the unit is stopped, and the unit file, container and `/etc/telcoin/gateway` are
  removed. Without `gateway.meta`, `install-caddy.sh --phase gateway-disable` is still possible, but the
  `tn-gateway` Caddy site stays and serves 502 on the public hostname, with 80/443 left open. The only notice is
  a `warn` event. In the menu it is one "Remove these leftover files?" yes.
- Why it is wrong: contract 6 (D2) says that on a host with only a gateway the script points at
  `setup-gateway.sh --remove`. A production public endpoint is torn down by a node-leftover cleanup, and half of
  it (the Caddy site) is left behind.
- Smallest fix: `remove_gateway` removes only a gateway whose `gateway.meta` says `MODE=same-host` (remove-node
  runs as root and can read it). For a standalone gateway (or a missing or unreadable MODE with no node unit and
  no `.node-meta`) it calls `rm_gateway_pointer` and returns. In the `only_gw` test, also forgive an empty
  `/var/lib/telcoin` and `/var/log/telcoin`.

### M4 (Medium): `rpc-advertise` restarts a validator to advertise a URL it never checked
- Where: `install-caddy.sh:3197-3231` (`caddy_rpc_node_precheck` checks only the hostname syntax;
  `do_rpc_advertise` then goes straight to `caddy_node_info_advertise set` and the guarded restart).
- Scenario (traced): `install-caddy.sh --json --phase rpc-advertise --rpc-domain gw.exmaple.org` (a typo, or a
  gateway that is not up yet) on a committee validator. Its signed record now names a URL that does not answer.
  Non-committee nodes forward pooled submissions to the committee workers' `rpc.http` URLs (facts, node side), so
  their forwards to this worker fail until a second guarded restart, with an epoch wait, corrects the record.
  Nothing on the validator reports it.
- Why it is wrong: unlike `rpc-enable`, this phase does not serve the URL it advertises, so it has no evidence
  that the URL works. The cost of a mistake is a validator restart and a period of failed forwarding.
- Smallest fix: in `caddy_rpc_node_precheck` for `rpc-advertise`, require
  `curl -fsS --max-time 5 https://<domain>/health` to return 200 (the gateway block routes `GET /health` to the
  probe listener). Otherwise refuse with "start the gateway first (setup-gateway.sh --enable on its host)". If
  the owner wants an override, it needs an explicit flag.

### L1 (Low): no put-back on TERM, INT or HUP in the middle of a change
- Where: `setup-gateway.sh:170-180,362-374` (the EXIT traps only remove an in-flight temp file and release the
  lock); `lib/gateway.sh:710-777` (no trap).
- Scenario (traced): a TERM between the meta write (`lib/gateway.sh:750`) and the unit write (`:757`). On a
  first install this leaves a `gateway.meta` that describes no unit. Over an existing install it leaves a new
  meta next to the old running unit. The script exits 143 with `done ok:false`. This is not silent: `--status`
  reports "unit missing" or "unit differs", and a second `--enable` repairs it. This matches setup-alerts, as
  the contract asks.
- Fix (optional): have the EXIT trap call `_gw_putback` when `_GW_WROTE_META`, `_GW_WROTE_UNIT` or
  `_GW_DID_START` is set and the rc is not 0.

### L2 (Low): the value checks accept unusual inputs
- Where: `lib/gateway.sh:170-193`.
- Harness, scenario `validators`. `_gw_redirect_ok` accepts `http://x:99999`, `https://h:0/`, `http://-` and
  `http://...`; the gateway then exits 1 at start, and enable rolls back after 20 s with a generic "did not
  answer /health". `_gw_upstream_ok` accepts `169.254.169.254` (the cloud metadata server) and `100.64.0.1`.
  `_gw_domain_ok` accepts `1.2.3.4`. The redirect URL may be plain `http://` on mainnet, which sends query
  answers over the network unencrypted.
- Fix: range-check the redirect port (1-65535); require a label that contains a letter or digit; drop
  169.254/16 from the upstream set; consider requiring https for a non-private redirect host on mainnet.

### L3 (Low): `--redirect-queries` targets the gateway refuses at start are not refused up front
- Where: `lib/gateway.sh:314-316`. Facts: `--redirect-queries` "must not hit the gateway itself or a worker's
  RPC/readiness host:port" (exit 1).
- Scenario (traced): same-host, `--redirect-queries http://127.0.0.1:8545` (the node's own RPC, a natural
  choice) passes validation. The unit starts, the gateway exits 1, and after 20 s the enable is rolled back
  with "did not answer GET /health … see journalctl".
- Fix: in `gw_validate_inputs`, refuse a redirect whose host:port equals `UPSTREAM_HOST:RPC_PORT`,
  `UPSTREAM_HOST:HEALTH_PORT`, or 127.0.0.1 / 0.0.0.0 with the listen port.

### L4 (Low): a same-host gateway always uses 127.0.0.1 for the node, whatever address the node binds
- Where: `lib/gateway.sh:256-270`; `check-node.sh` `check_gateway` compares only the port.
- Scenario (traced): the node's launch file has `--healthcheck 10.0.0.5:43174`, or a specific
  `--http.addr`. Enable succeeds, because it waits for `/health` only. The gateway is never `/ready`, every
  submission gets 503, and check-node says the `--healthcheck` port matches.
- Fix: refuse same-host when the bind host from `tn_node_health_bind` is not 127.0.0.1 or 0.0.0.0, or use
  that host as the upstream host.

### L5 (Low): the script's image check accepts what the library refuses, and the message then says "tags are refused"
- Where: `setup-gateway.sh:104` (`SG_IMAGE_RE` allows `host:5000/repo@sha256:…`) against `lib/gateway.sh:364`
  (no `:` allowed).
- Fix: use the library's regex in the script, or reword the library message ("a registry port or a tag").

### L6 (Low): `rpc-unadvertise` and `rpc-advertise` ignore a public-RPC site on the host
- Where: `install-caddy.sh:3197-3245`.
- Scenario (traced): on a testnet node with an `rpc-enable` site, `rpc-unadvertise` clears node-info's
  `rpc.http` and unsets `PUBLIC_RPC_*`, with a guarded restart, while the `tn-rpc` site stays. `rpc-advertise`
  on the same host overwrites the advertisement and `PUBLIC_RPC_DOMAIN`, and after that `rpc-enable` refuses
  because of `RPC_ADVERTISED_VIA`.
- Fix: `rpc-advertise` refuses while a `tn-rpc` block is present ("run rpc-disable first"); `rpc-unadvertise`
  refuses unless `RPC_ADVERTISED_VIA=gateway` (or says that it is clearing an rpc-enable advertisement).

### L7 (Low): `remove_gateway` leaves the gateway advertisement and does not say so (open question D2)
- Where: `remove-node.sh:1529-1563`.
- Scenario (traced): a service-scope or data-scope removal on a same-host gateway keeps `.node-meta` with
  `RPC_ADVERTISED_VIA=gateway` and `PUBLIC_RPC_URL`. node-info.yaml in the datadir still advertises
  `https://<gw>/`. A reinstalled node publishes a dead URL, and `rpc-enable` stays refused.
- Fix: when `.node-meta` has `RPC_ADVERTISED_VIA=gateway`, print one line: "node-info.yaml still advertises
  <PUBLIC_RPC_URL>; once the node runs again use install-caddy.sh --phase rpc-unadvertise (or enable the
  gateway again)". Do not unset the keys alone: that would split the record from the meta.

### L8 (Low): an extra file in `/etc/telcoin/gateway` makes every `--remove` end rc 2
- Where: `lib/gateway.sh:977-991`.
- Scenario (traced): the operator leaves a note file in `/etc/telcoin/gateway`. `rmdir` fails, the run reports
  "partly removed; left /etc/telcoin/gateway, run --remove again", and every later run ends the same way
  (exit 3).
- Fix: name the files that block the `rmdir` in the message, or remove the directory's contents.

### L9 (Low): `gw_image_probe` has no time limit
- Where: `lib/gateway.sh:407-408`.
- Scenario: an image whose `--help` hangs (a trusted image, so unlikely) blocks the run while it holds the
  update lock, and with it every node operation on the host.
- Fix: wrap it in `timeout 60` where `timeout` exists, as `tn_docker_image_network_ok` does.

### L10 (Low): the Caddy no-op checks only the bytes of the block
- Where: `install-caddy.sh:3038-3070`; `lib/gateway.sh:1093-1102`.
- Scenario (traced): the block is current but Caddy is stopped or failed. `gateway-enable` returns ok,
  "nothing written, Caddy not reloaded". `gw_status` checks only that the block is present: not
  `block_stale` (a block written by an older release) and not that Caddy runs.
- Fix: the no-op path also requires `systemctl is-active caddy` (else reload or start); `gw_status` treats a
  stale stamp as an issue.

### L11 (Low): the public probe paths go to the listener with no connection cap and no rate limit
- Where: `install-caddy.sh:1335` ff. (`handle @probe` -> probe port). Facts: `--probe-addr` has "no conn cap,
  no rate limit".
- Probes are cheap (cached readiness), so this matters little, but `GET /ready/any` from the internet is
  unlimited. Proxying the probe paths to the main listener (probes are exempt from rate limits there but count
  toward the connection cap) would keep `--max-connections`. Owner's choice; contract 4 asks for the probe port.

### L12 (Low): `sg_end_changed` is not silent, and the baseline runs twice
- Where: `setup-gateway.sh:532-538` (`gw_status` with no FN prints every status line and issue after each
  change in plain mode; the comment says "silent"); `lib/gateway.sh:895,929,993` together with
  `setup-gateway.sh:521-527` (`tn_host_baseline_refresh` runs twice per change).
- Fix: pass a no-op say function; drop one of the two baseline calls.

### L13 (Low): with `--front none` the gateway has no CORS
- Facts: the gateway's CORS is off without `--cors-allowed-origins`, and `gw_render_args` never passes it. A
  front-none gateway therefore cannot be used directly by a wallet in a browser. If that is intended (front none
  sits behind an operator's own load balancer), say so in the usage text and OPERATOR.md.

---

## What I checked and found sound

- Image trust, harness: an upper-case repository, a tag before `@`, a 63-hex digest, and a repository that only
  starts with the allowed one (`…/worker-gateway-x`) are all refused. The devnet allow-list match is exact (a
  quoted `case` pattern, so no glob). Empty testnet and mainnet pins refuse with the contract message, and a set
  pin requires an exact match. Trust is judged before any `docker pull` and before the `--help` probe, both in
  enable (`gw_validate_inputs` runs before `gw_image_ensure` and `gw_image_probe`) and in refresh.
  `tn_docker_holds_digest` matches the full `repo@digest` in RepoDigests. The pins are plain assignments in
  the library, so the environment cannot override them.
- The unit: `--pull=never` is on the only start path (`ExecStart`). The container runs as uid 1101, read-only,
  with `--cap-drop ALL` and `no-new-privileges`. `docker stop -t 60` with `TimeoutStopSec=75` covers the 47 s
  drain. With `Restart=on-failure` and `RestartSec=5` the default start limit is never hit, so a crash loop
  retries forever, visible as not-active in status. With host networking the container can reach the node's
  RPC and health ports (by design) and the Node Manager on 127.0.0.1:8080, whose management API requires the
  per-install token in `/etc/telcoin-ui/token` (root:telcoin-ui 0640), which uid 1101 cannot read. Not
  verified: whether Caddy's admin endpoint is on a unix socket on every host. Every value that reaches
  `ExecStart` is restricted to characters that are not systemd specifiers (no `%`, `$`, quote, space or newline);
  values loaded from meta are checked again (`_gw_load_meta`), and IMAGE is checked by `gw_image_allowed` on
  refresh.
- Rollback: every exit after the first write goes through `_gw_fail` / `_gw_putback`, in this order: stop
  what this run started, disable what it enabled, restore or remove the unit and meta, remove the directories
  it made, `daemon-reload`, restart the previous gateway. A Caddy failure with rc 1 rolls the gateway back. rc 2
  (no done line) rolls back the gateway and reports the Caddy state as unknown. A failed put-back is rc 2, and
  the script exits 3. The library releases only a lock it took itself.
- No-change detection, harness (`noop`): a second identical enable makes no write and only the two
  `is-enabled` / `is-active` calls; empty `DOMAIN=` and `TRUSTED_PROXIES=` read back as empty. A hand-edited
  unit, a front change (the listen address changes) and a port change all differ from the installed state and
  restart the gateway. A domain-only change writes meta without a restart and runs the Caddy step.
- Caddy: all six writers pass the third block back (`do_enable`, `do_disable`, `do_rpc_enable`,
  `do_rpc_disable`, `do_gateway_enable`, `do_gateway_disable`). Every teardown decision counts all three blocks.
  `caddy_teardown` is the only place 80/443 are closed and is reached only from those three disables. A legacy
  pre-fence dashboard file is folded into a fenced block by `caddy_current_dashboard_block`. `rpc-disable`
  leaves node-info and the keys alone when `RPC_ADVERTISED_VIA=gateway`. `rpc-enable` refuses while a gateway
  block or `RPC_ADVERTISED_VIA=gateway` exists, and `gateway-enable` refuses while a `tn-rpc` block exists. The
  hostname-clash check covers all three sites. On a node host `gateway-enable` passes through
  `caddy_mainnet_gate`, so a staked mainnet validator cannot get a site; the library also refuses same-host on
  mainnet and standalone on a node host. Node detection is the same `node_meta_path` in both scripts.
  `rpc-advertise` and `rpc-unadvertise` use the existing advertise path with the update lock, the committee
  guard and the epoch wait. Handlers run in Caddyfile order (named matchers in order of appearance, the
  unmatched `handle` last). In that order HEAD and GET on the probe paths go to the probe listener; CONNECT,
  including HTTP/2 extended CONNECT, gets 405; a POST with a WebSocket upgrade gets 405; `/ready/` gets 405;
  `//ready` and `/HEALTH` reach the probe listener, which is harmless. An OPTIONS with no Origin gets 200 with
  CORS headers, as the `tn-rpc` block does. Caddy, as a trusted proxy, is exempt from the gateway's per-IP
  connection cap (facts), so funnelling all clients through 127.0.0.1 does not cap them at 32 connections.
- Nothing in these files stops, starts or restarts the node's unit, except `rpc-advertise` / `rpc-unadvertise`
  through `caddy_node_info_advertise`. The library and `remove_gateway` name only `telcoin-gateway.service` and
  the container `telcoin-gateway`, which the custom-install scan skips.
- The script: every `--json` path ends with exactly one done line (`sg_finish`, `json_on_exit`, or
  `gateway_require_lib`'s own line before any trap is set). The library never writes fd 3. The output of the
  `install-caddy.sh` child is captured. Exit codes map 0/1/3, 2 for library skew, and 143/130/129 for signals.
  Consent applies to `--enable` and `--remove`; `--json` never asks. The environment cannot reach `GW_IN_*` or
  `GW_CADDY_SCRIPT` (both reset after sourcing).
- `gw_status` without root reads the values from the unit file and says what it skipped. `installed` follows
  `gateway.meta`, so a half-removed tree reports either "unit missing" or "not installed" plus an issue for a
  leftover unit.
- Gates run: `bash -n` on the five files (rc 0); `shellcheck -x --severity=error` as CI runs it (rc 0);
  `shellcheck -x lib/gateway.sh setup-gateway.sh` at all severities (no output); `tools/check-bash32.sh` on the
  two new files (rc 0); `tools/check-network-hits.sh` (rc 0, "clean"). No bash-4-only construct found.
  `printf -v` with a computed name works on 3.1 and later.
- Not in scope, noted: `setup-gateway.sh` and `lib/gateway.sh` have no `.sha256` sidecar and are not in
  `update-scripts.sh` `SCRIPTS` yet (unit F2). Until F2 lands, an older `install-caddy.sh` on a host would
  drop the third block on any dashboard toggle.

## Rulings on the open questions (review-notes.md, "-> R1b")

1. D2, `.node-meta` keeps `RPC_ADVERTISED_VIA=gateway` after a service-scope or data-scope removal on a
   same-host gateway: **defect (Low), see L7.** Print the pointer; keep the keys, because they still match
   node-info.yaml.
2. A2, `--help --json` prints the usage and no done line; `--refresh` takes `--yes` and asks nothing; `--remove`
   asks only when something is installed: **acceptable as is.** `--help` is not an action, and refresh changes
   no exposure.
3. E4, a gateway-only host with an empty `/var/lib/telcoin` (or libexec dir) counts as node leftovers, and
   `--json --remove` removes the standalone gateway: **defect (Medium), see M3.** Remove only a `MODE=same-host`
   gateway; for anything else, point at `setup-gateway.sh --remove`.
4. E4, `scan_custom_installs` greps the real `/etc/systemd/system`: **acceptable as is** (a gap in what the
   tests can reach; the behaviour is right on a real host).
5. E1, the usage text contains a literal `{"event":"done",...}`: **acceptable**; an optional reword of
   `setup-gateway.sh:67` to `one done event last` costs nothing.
6. E1, the skew message names both libraries when only `lib/common.sh` is old: **acceptable as is** (the
   remedy, `update-scripts.sh`, is right).
