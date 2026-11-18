# Launch 2 rehearsal: challenges report

Rows covered: 1-72 of `tasks/challenges-l2.md`.
Sources: that list, the text of tn-node-deployment PR #68 (branch `worker-gateway`, scripts 2.2.0, open, not merged) and the approved plan (`tasks/l2/plan-approved-2026-11-17.md`).
Rows 1-15 were seeded from the plan before the run; apart from row 10 they carry no run evidence, and the report says so where a consequence depends on it.

## 1. Summary

The devnet was redeployed in mainnet shape with tn-node-deployment: four genesis validators behind worker gateways (validator 4's on its own host), a committee P2P allowlist on the validators, a native public RPC node, and a fifth node that stakes after genesis.
72 challenges: 7 fixed in PR #68, 8 worked around or fixed on the devnet side, 57 open (13 of the open ones are devnet-genesis follow-ups and 1 is the operator host).
Counts follow each row's status column, corrected against PR #68's text for rows 1, 5, 6 and 24; a row whose upstream side is still open counts as open even where the devnet has a workaround (14, 15, 23, 49).
Before mainnet, the ones that matter most:
- Build and publish a worker-gateway image in telcoin-network CI and pin its digest in a signed scripts release; until then mainnet refuses the gateway (2, 29).
- Add the rotated release key (ed25519 95A38484…AE47) to tn-node-deployment's `lib/release-keys`; nodes refuse a release signed with it today (49).
- Find why the committee firewall makes a node outside the allowlists fall up to 476 blocks behind; every validator that joins after genesis meets it (67, 11, 33).
- Make `setup-observability.sh` write a health address a monitor can reach; a bare `--healthcheck` port now binds loopback (3, 38).
- Decide how the public RPC node's forwards fit the gateways' per-IP limit (100 rps, burst 200, 30 s demotion after a 429) (10, 42).
- Set an ACME email for Caddy, stop calling genesis validators observers, and keep `tn_*` off the public RPC node (54, 51, 12).

## 2. Before mainnet

Most serious first. "PR #68" is the open tn-node-deployment branch; anything it fixes reaches operators only once it is merged and shipped in a signed scripts release.

### 2.1 No gateway image to pin (rows 2, 29; also 1, 30)
- What happens: PR #68 runs the gateway only from a digest, and its testnet and mainnet pins (`GW_TESTNET_IMAGE_PIN`, `GW_MAINNET_IMAGE_PIN`) are empty, so `setup-gateway.sh --enable` there refuses with `this scripts release pins no worker-gateway image for <network>`. telcoin-network has no CI job or Makefile target that builds the image. The devnet's image was built outside CI for this rehearsal: its `--version` prints `tn-worker-gateway 0.1.0` with no commit, its Dockerfile takes no `GIT_SHA`, and its toolchain is pinned by channel. On tn-node-deployment `main` there is no gateway support at all until PR #68 merges (row 1).
- Who meets it: the launch team first; then every validator operator at install time, since the standalone gateway is the only mainnet layout.
- Proposed: a telcoin-network CI job that builds and publishes the gateway image with the commit in `--version` and a pinned toolchain; merge PR #68; a signed scripts release that sets both pins. A build that reports its features would also replace the string probe the devnet used to show the image has no faucet (row 30: every build lists `--allow-faucet-on-chain` in `--help`).

### 2.2 The rotated release key is not shipped (row 49)
- What happens: the release signer moved from RSA 4E36…7573 to ed25519 95A38484…AE47, published in tn-release-signing. `lib/release-keys` on `main` and on PR #68 holds only the RSA key, so a testnet or mainnet node refuses a release signed with the new key. The devnet's check read the same directory and refused too (rc 1, "not in the allow-list") until 0f26db7 pointed it at the tn-release-signing submodule; the release then verified (`VALIDSIG 95A38484…`).
- Who meets it: every operator who installs or updates the scripts, and the launch team signing the release.
- Proposed: add the ed25519 key to `lib/release-keys`; the owner is preparing that upstream PR (2026-11-18). The signing laptop no longer holds the RSA secret (`gpg: skipped "4E36…": No secret key`), so the release that adds the new key likely cannot be signed with a key existing installs trust; plan how hosts that already run the scripts get the new key.

### 2.3 The committee firewall degrades a joiner's sync (rows 67, 11, 33; also 8)
- What happens: node 5 synced only from the RPC node, which the firewall does not touch. Before validator 1's allowlist went on (02:05-02:27Z) its per-minute `catchup_distance` peaked at 2-3; at 02:28Z it reached 25, and after validators 2-4 (02:31Z on) it reached 14 to 48 consensus outputs, about 30 s of stall and up to 476 blocks behind validator 1, while the RPC node stayed within 6. Its dials to the validators hang and `Stream(NotConnected)` appears against all four. The next epoch showed the cause: from 03:28Z, the minute the validators' sets began to list node 5, its sync was steady again (94-99 catch-ups a minute, never more than 4 behind) at the same block rate, while their admission still refused it. So the dropped packets stall the sync; the refusal after a handshake does not. The code path is not read.
- Neither side explains it: a validator that refuses a non-admitted peer completes the QUIC handshake and drops it with no log line at `-vvv` (RH0: 9-27 handshakes per validator). The joiner's record now reaches the validators only through the hub; the plan says lookup backoff can delay its allowlist entry by up to 30 min (row 11 has no run evidence).
- Who meets it: every validator that joins mainnet after genesis, from its first start until the epoch after its `activate()`.
- Proposed: in telcoin-network, find where a dial that gets no answer holds the observer's sync up, keep sync from waiting on it, and log the refusal on the validator. Until then a joiner's operator should expect uneven sync (stalls of about 30 s) from its first start until the epoch after `activate()`; it clears by itself within five minutes of that epoch's start. In tn-node-deployment the admission renderer also cannot express "bootstrap from a hub, committee peers = genesis set" for a joiner (row 8).

### 2.4 Health checks bind loopback and monitors fail silently (rows 3, 38)
- What happens: on telcoin-network `main` a bare `--healthcheck <port>` binds 127.0.0.1. `setup-observability.sh --enable-health` still writes the bare port plus a ufw rule for the monitor's address, so the rule admits a monitor that can reach nothing, and the monitor or a load-balancer check sees a healthy node as down. Comments in `lib/common.sh` and `setup-observability.sh` still say the bare port binds every interface. Read from code; not run against a real monitor.
- Who meets it: testnet and devnet operators who turn on health monitoring with a main-based image. On mainnet the scripts refuse the health add-on (`require_testnet`, `lib/common.sh:9205-9212`) and `check-node.sh:2138-2151` fails a mainnet node that carries `--healthcheck`, so a mainnet validator has no health endpoint for a monitor at all; the gateway's public `/ready/any` is the path left (the owner's Kuma monitors move there, P4). The scripts' README on `main` (line 454) already says the bare port will bind loopback from the next release: known, documented, not fixed.
- Proposed: write an explicit address with the port that matches the ufw rule, and correct the comments. PR #68 writes `--healthcheck 0.0.0.0:43174` only for the standalone gateway case.

### 2.5 The public RPC node is one client to every gateway (rows 10, 42, 43, 44)
- What happens: each gateway allows one client IP 100 requests a second (burst 200) and 32 connections, and the RPC node's forwarder does not pass the original client, so every forwarded transaction counts against the RPC node's address. In RH5, 400 transfers sent about 210 forwards to one gateway within a second and drew one 429; the RPC node set that gateway aside for 30 s and re-sent 61 transfers, and 400/400 confirmed in 4.65 s. All transfers of one sender go to one validator's gateway first, so a busy sender concentrates there. A restarting gateway answers 503 for about 11 s and is set aside for 30 s too, so a rolling restart concentrates forwards on the others. The warning `demoting unreachable validator RPC endpoints from forward admission demoted=1 cooldown_secs=30` names no endpoint.
- Who meets it: the RPC operator and the launch team on launch day.
- Proposed: an installer option in `setup-gateway.sh` for the per-client limit, raised for the operator's own RPC node, or the forwarder passing the client address with the RPC node as a trusted proxy (PR #68's smoke test showed the limit already follows a forwarded client). Name the endpoint and validator in the warning.

### 2.6 The gateway breaks keep-alive after a 429 (row 35)
- What happens: after a 429 the gateway closes the connection without sending `Connection: close`, and the next request on it fails (BrokenPipe, reproduced with one client). Whether Caddy, which fronts every mainnet gateway, then answers an unrelated client with a 502 is not verified; the RH5 report notes a Caddy 502 would count as a failure and demote the gateway (not tested).
- Who meets it: users of the public RPC node, through the forwarder.
- Proposed: test with Caddy in front before mainnet; in the gateway, send `Connection: close` or keep the connection open.

### 2.7 Caddy's ACME account has no email (row 54)
- What happens: Caddy registers its Let's Encrypt account with `"email":""` (journal on validator-1-devnet, step 13), so a certificate that fails to renew warns nobody.
- Who meets it: every operator whose gateway host or RPC node runs Caddy.
- Proposed: a certificate-expiry check (in `check-node.sh` or the monitoring), since an email alone no longer brings a warning: Let's Encrypt ended its expiry emails in 2025 (from memory, not re-checked). An ACME email in Caddy's global options is still worth having as the account's contact.

### 2.8 Genesis validators are told they are observers (row 51)
- What happens: `setup-node.sh`'s closing JSON says `"node_type":"observer"` and "following consensus as a full node; staking to validate is optional" on every host, the four genesis validators included, right after its own on-chain check printed "Status: Active".
- Who meets it: every genesis validator operator at install time, and any tool that reads that JSON.
- Proposed: build the closing message from the on-chain status the script has just read, and add a status field beside `node_type`. The fixed `"node_type":"observer"` is deliberate (`setup-node.sh:222-226`: the Node Manager UI's slot), so the field stays; the sentence beside it is what misleads.

### 2.9 `tn_*` is public on the public RPC node (row 12)
- What happens: on a native public-RPC node the `tn_*` namespace, admission snapshot included, answers any caller. Seeded from the plan; the row has no run evidence.
- Who meets it: the RPC operator.
- Proposed: decide which `tn_*` methods are public and leave the rest out of what the node serves: in the API list tn-node-deployment renders for a `0.0.0.0` bind (row 20) if `--http.api` covers the namespace, otherwise in the node.

### 2.10 The committee allowlist is hard to drive and to read (rows 7, 23, 68, 72)
- What happens: `firewall-setup.sh --p2p-committee` is a manual step per host with no `--json`. Its `--wait 30` waits for the tool's lock, not for an authoritative snapshot, so a node that is not yet authoritative is refused at once and a driver must retry (the devnet driver does). The tool sits in `/usr/local/libexec/telcoin/`, off sudo's PATH: `sudo tn-p2p-allow-sync check` answers `command not found`; with the full path it gives `result=ok missing_total=0 mismatch_total=0`. Its status shows `keys=4` beside five addresses without saying the fifth is the trusted RPC node, and the drop counter (`accept=177128 drop=992` on validator-1, 16 min after `on`) does not say which sources were dropped, so a scanner cannot be told from a peer that should have been listed.
- Who meets it: every validator operator turning the allowlist on, and whoever debugs a joiner (2.3).
- Proposed: `--json`, a wait for an authoritative snapshot, the tool on PATH or its full path in OPERATOR.md, and a status that names each address's source and the dropped sources.

### 2.11 Scripts start a node that was left stopped (rows 15, 16, 37)
- What happens: finalize has no `--no-start` (the devnet stages by start-then-stop); `edit-config.sh --set` restarts the unit unconditionally (PR #68 guards only its new `gateway_upstream` key); `setup-observability.sh --json` forces "yes" to its restart question and runs `systemctl restart` whenever it adds a log or metrics flag. The devnet stops each node again after these steps.
- Who meets it: the launch team, if mainnet's genesis validators are staged stopped before a coordinated start as on the devnet; a node started early runs alone.
- Proposed: `--no-start` for finalize, and return before the restart when the unit is not active (row 37's smallest fix) in `setup-observability.sh` and `edit-config.sh`.

### 2.12 Admission settings have no version floor (rows 14, 57)
- What happens: `MIN_ADMISSION_VERSION` is set to `0.17.0` (`lib/common.sh:2769`) under a `TODO(node team): confirm` comment, and the check behind it returns "unknown" for an image pinned by digest. With a digest-pinned image `setup-node.sh` prints `[WARN] Could not tell whether the image … is release 0.17.0 or later … writing them anyway`. On devnet it writes them; what it does on mainnet was not run.
- Who meets it: every validator operator at install time, since mainnet images are pinned by digest.
- Proposed: set the floor, and record the image's version next to the pinned digest so the check can be made.

### 2.13 Open items in PR #68's own code (rows 45, 53, 4, 40)
- `rpc-advertise` checks `https://<gateway name>/health` from the validator before it edits the record, with no flag to skip it; a validator with no outbound HTTPS to that name cannot advertise its gateway (45). Mainnet validators sit in a closed network, so this likely applies to them.
- On a gateway-only host, `firewall-setup.sh --enable` reports "SSH + overlay + kuma pre-allowed" while the host gets the SSH rule only (53, message only; seen on gateway-4-devnet).
- Standalone binds the validator's RPC and health check to every interface, guarded only by ufw, because local readers hard-code loopback; a firewall reset needs `gateway_upstream=off` around it (4).
- The SSH lockout from source spellings (`1.2.3.4/32` stored as `1.2.3.4`) is fixed only in PR #68; on `main`, re-entering an SSH source in the other spelling deletes the rule (40).
- Proposed: settle 45 and 53 in PR #68's review before it merges; 4 needs a private-address bind the local readers understand.

### 2.14 Unknown flags are ignored with exit 0 (rows 17, 18)
- What happens: `firewall-setup.sh`, `install-caddy.sh` and `remove-node.sh` drop unknown flags silently, so an older script given a newer flag such as `--gateway-from` exits 0 having done nothing; `setup-node.sh` only warns. `firewall-setup.sh --status` without `--json` falls into the interactive menu, which would hang a non-interactive caller (inferred, not run).
- Who meets it: a validator operator whose installed scripts are older than the runbook they follow.
- Proposed: refuse unknown flags; make `--status` print and exit when stdin is not a terminal.

### 2.15 Monitoring gaps and noise (rows 13, 39, 52)
- No native scrape for gateway metrics, nftables counters or the allowlist's sync timer (13; from the plan, no run evidence).
- A healthy non-committee node logs the WARN `consensus output sync exchange failed; trying next peer` about once a second (about 200 in three minutes on the RPC node, 47 on the joiner), which hides real sync trouble (39).
- `setup-observability.sh` warns on every fresh launch, twice, that committee members are down, because it reads the public RPC URL before the chain has started (52).
- Who meets it: the RPC operator and joiners (39), the launch team at genesis (52), everyone who monitors a node (13).

### 2.16 One transient gcloud failure stops a devnet driver (row 47; also 59)
- What happens: one `describe` hung on a TLS handshake to compute.googleapis.com for 300 s (`ReadTimeoutError … read timeout=300`); the teardown refused on "state unknown" with nothing changed, and a second run passed. The drivers' reads have no retry.
- Who meets it: only the launch team, and only if it drives mainnet hosts with gcloud-based drivers like devnet-genesis's. A validator operator who runs tn-node-deployment on their own host does not go through these drivers. The same condition applies to the serial post-start checks (59: step 14 took 1014 s for six nodes).
- Proposed: retry reads in the drivers if they are reused for mainnet; otherwise a devnet follow-up.

## 3. By repository

Each row appears once, under the repository where its fix belongs; "also" names the other one. Mainnet column: yes / no / only for the devnet (or the condition under which it matters).

### 3.1 tn-node-deployment (36 rows)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 1 | No worker-gateway support: no installer, unit, Caddy block or checks | fixed in PR #68 | yes |
| 3 | `setup-observability.sh` emits a bare `--healthcheck` port, which binds loopback on main-based nodes; also telcoin-network | open | yes |
| 4 | A validator's RPC cannot bind only a private address (local readers hard-code loopback), so standalone uses a wildcard bind guarded by ufw | open (PR #68 checks ufw before the wildcard bind) | yes |
| 5 | No ufw rule for the RPC port, and `--reset` dropped hand-added rules | fixed in PR #68 (`--gateway-from`, re-applied by `--reset`) | yes |
| 6 | `install-caddy.sh` died on a node-less host and has no load-balancer backend mode | fixed in PR #68 for the gateway phases; LB mode open, not needed after decision 6 | no |
| 7 | `--p2p-committee` has no `--json`, no wait for an authoritative snapshot, one manual step per host | open | yes |
| 8 | The admission renderer cannot express "bootstrap from a hub, committee peers = genesis set" for a joiner | open | yes (post-genesis joiners) |
| 12 | `tn_*`, admission snapshot included, is public on a native public-RPC node; also telcoin-network | open (no run evidence) | yes |
| 13 | No native scrape for gateway metrics, nftables counters or the sync timer | open (no run evidence) | yes |
| 14 | `install.sh` / `update-scripts.sh` cannot install a PR head (the devnet fetches by sha, bypassing MANIFEST verification); `MIN_ADMISSION_VERSION` is a TODO | open (devnet fetches by sha) | yes for the floor; the PR-head install only for the devnet |
| 15 | Finalize has no `--no-start` | open (devnet starts then stops) | yes, for a staged start |
| 16 | `edit-config.sh --set` restarts a unit that was left stopped | open (PR #68 guards `gateway_upstream` only) | yes, for a staged start |
| 17 | `firewall-setup.sh`, `install-caddy.sh`, `remove-node.sh` ignore unknown flags and exit 0 | open | yes |
| 18 | `firewall-setup.sh --status` without `--json` opens the interactive menu (inferred, not run) | open | only for scripted callers |
| 19 | The dashboard phase hashes a 16+ character password locally; a fleet that stores only a bcrypt hash cannot reuse it | open (decision pending for `devnet-dashboards.sh`) | no |
| 20 | The RPC bind can be changed only in the interactive menu; its `0.0.0.0` case adds public-RPC limit flags and an `--http.api` list | open (PR #68 adds `gateway_upstream` for the gateway case) | no |
| 21 | Off testnet and devnet no script renders `--healthcheck`, which a same-host gateway needs | open (PR #68 refuses same-host on mainnet; standalone adds the flag) | no |
| 22 | The sidecar rule contradicts itself (`tools/gen-checksums.sh:11-13` against `AGENTS.md:335`) | open | no |
| 23 | `--p2p-committee on` waits 30 s for the tool's lock, not for an authoritative snapshot; also tn-p2p-allow-sync | open (devnet driver retries) | yes |
| 24 | `rpc-disable` cleared the advertised URL, Caddyfile writes kept two blocks, the last block closed 80/443 | fixed in PR #68 for the gateway block | no |
| 32 | The admission renderer refuses BLS keys written as YAML complex keys (PyYAML's output for keys over 128 characters) with a message that does not say why | worked around (devnet writes plain `key:` lines) | yes, for whoever generates the map |
| 37 | `setup-observability.sh --json` restarts a stopped node whenever it adds a flag | worked around (devnet stops it again) | yes, for a staged start |
| 38 | `--enable-health` writes a bare port and a ufw rule for a monitor that reaches nothing (the case of 3) | open | yes |
| 40 | `--ssh-from` / `--p2p-from` stale cleanup compares source spellings literally; for SSH a lockout | fixed in PR #68 | yes, until released |
| 41 | Plain `ufw status` and `systemctl is-active --quiet` say less than the scripts assumed | fixed in PR #68 where the gateway code used them | no |
| 42 | The installer renders no gateway rate-limit flag; also telcoin-network (forwarder, see 10) | open | yes |
| 45 | `rpc-advertise` needs outbound HTTPS from the validator to the gateway's public name; no skip flag | open (stated in PR #68) | yes |
| 46 | `ui/requirements.txt.sha256` stale on `main` since #63, so the CI checksums job fails | fixed in PR #68 | no |
| 49 | `lib/release-keys` ships only the rotated-out RSA key; also devnet-genesis | open (devnet worked around in 0f26db7; upstream PR in preparation) | yes |
| 51 | Finalize's closing JSON calls every host an observer, genesis validators included | open | yes |
| 52 | `setup-observability.sh` warns that committee members are down on every fresh launch, twice | open | yes (noise at genesis) |
| 53 | On a gateway-only host `--enable` claims "SSH + overlay + kuma pre-allowed" and applies SSH only | open (message only, PR #68's path) | yes (message) |
| 54 | Caddy's ACME account is registered with an empty email | open | yes |
| 57 | `setup-node.sh` cannot tell whether a digest-pinned image is 0.17.0 or later and writes the admission settings anyway on devnet | open | yes |
| 64 | `install-ui.sh` prints a curl connection error just before its own success line, on every host | open | no (cosmetic) |
| 68 | `tn-p2p-allow-sync` is installed off sudo's PATH (`/usr/local/libexec/telcoin/`); also devnet-genesis (runbook) | open (devnet runbook corrected) | yes |

### 3.2 telcoin-network: node, gateway, forwarder, images (16 rows)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 2 | No published gateway image or binary, CI never builds it, `--version` has no commit; also tn-node-deployment (the pins) | open | yes, blocks the gateway |
| 9 | The public-RPC guidance (`--forward-txs`, `--sanitize-txs`) bypasses node records; record forwarding leaves the gateway as the only pre-check; also tn-node-deployment (no script support) | open (no run evidence) | yes |
| 10 | One RPC node is one client IP to each gateway (100 rps, burst 200, 32 connections); a 429 demotes the gateway for 30 s | open (measured in RH5, no loss) | yes |
| 11 | A joiner's record lives only on the hub until a committee node fetches it; backoff can delay its allowlist entry up to 30 min | open (no run evidence) | yes |
| 28 | `bin/node-record-api` does not compile on its own at 5533ff73a (`SealedHeader: serde::Serialize is not satisfied`), so its image cannot be built | open | only if mainnet runs that service (not stated) |
| 29 | The gateway image carries no commit, pins its toolchain by channel, and no CI job or Makefile target builds it (extends 2) | open | yes |
| 30 | A "no faucet" check on `--help` fails on every build, which all list `--allow-faucet-on-chain` | worked around (binary string probe, count 0) | yes, for the launch team's image check |
| 31 | `git submodule update --init --recursive` clones about 40 nested Solidity repositories (about 35 min) | worked around (plain `--init`) | no |
| 33 | A validator that refuses a non-admitted peer logs nothing at `-vvv` | open | yes |
| 34 | The node image has no `curl` | worked around (probe from the host) | no |
| 35 | After a 429 the gateway closes keep-alive without `Connection: close`; a Caddy 502 to another client is not verified | open | yes |
| 36 | A same-host gateway with a loopback query endpoint warns at every start; a plain-http public redirect URL warns too | open (note) | no |
| 39 | A healthy non-committee node logs `consensus output sync exchange failed; trying next peer` about once a second | open (note) | yes |
| 43 | The RPC node's demotion warning names no endpoint and no validator | open | yes |
| 44 | A restarting gateway answers 503 for about 11 s and is demoted for 30 s | open (note) | yes |
| 67 | The validators' committee firewall degrades the sync of a node not yet in the eligible pool; also tn-node-deployment (`--p2p-committee`) | open (mechanism inferred from the log) | yes |

### 3.3 tn-p2p-allow-sync (1 row)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 72 | Status shows `keys=4` beside five addresses without naming the trusted RPC node, and the drop counter names no source; also tn-node-deployment | open | yes |

Also here: 23 (the tool's contract defines `--wait` as a lock wait, `docs/contract.md:287-288`) and 68 (its install path).

### 3.4 tn-transaction-generator (2 rows)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 62 | The transfer amount is in the `type` label, so every transaction is its own series (7,930 `txgen_` lines 25 min after start, unbounded) | open | no |
| 63 | The native faucet drip reverts in `eth_estimateGas` with `LowLevelCallFailure(bytes)` (0x37f33ed8) on an image without the `faucet` feature; the cause is not verified; also tn-contracts | open | no, unless the revert has a cause other than the missing feature |

### 3.5 tn-contracts (no row)

No row's fix belongs here. Also here: 63, whose revert is a tn-contracts error. Rows 25 and 48 are about the devnet's checkout of tn-contracts, not the contracts, and sit under devnet-genesis.

### 3.6 devnet-genesis: the devnet's own drivers (16 rows, local follow-ups)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 25 | `devnet-contracts.sh` and `devnet-txgen.sh` defaulted to a worktree that no longer existed | worked around via 48 (c00ebe5) | only for the devnet |
| 26 | `devnet-keygen.sh` loses its target check's failure; one unknown target keys nothing and exits 0 | open (unit G2; read from code, not run) | only for the devnet |
| 27 | `setup-firewall.sh` sources `./config.sh` from the cwd, runs without `set -e`, never deletes a rule it no longer writes | open (unit FW) | only for the devnet |
| 47 | One transient gcloud failure stops a driver; the drivers' reads have no retry | open (failed safe) | only if mainnet is driven by such drivers |
| 48 | The contracts checkout was a worktree a cron job removed; the pre-gate passed an empty directory; also operator host | worked around (c00ebe5: submodule; the gate checks the address book and `forge-std/src/Test.sol`) | only for the devnet |
| 50 | `config.sh` overwrites values given in the environment (`P2P_COMMITTEE_WAIT_SECS`, `RELEASE_KEYS_DIR`); a negative control passed for the wrong reason | open | only for the devnet |
| 56 | Three drivers stamp log directories in local time, `devnet-deploy.sh` in UTC | open | only for the devnet |
| 58 | `setup-firewall.sh --status` reads every VM first; before they exist it prints nothing and exits 1 | open | only for the devnet |
| 59 | The checks after the coordinated start run one host at a time; step 14 took 1014 s for six nodes | open (run them in parallel) | only if mainnet's start uses this driver |
| 60 | The post-check passes node 5 with `connected=0` (`connected` appears to count committee peers only, not verified) | open (check `net_peerCount` >= 1) | only for the devnet |
| 61 | `devnet-txgen.sh`'s metrics check runs before the first submit and is not a gate | open | only for the devnet |
| 65 | The contracts driver's "Next:" list misnumbers the txgen step and asks to commit an unchanged address book | open | only for the devnet |
| 66 | The staking driver's sync gate could not pass on a busy chain (two reads 3-5 s apart against a 5-block limit) | fixed in devnet-genesis (42f2850, test with 7 cases) | only for the devnet |
| 69 | `devnet-p2p-committee.sh --status` prints `check: no result line (exit 1)` per host while the allowlist is off | open | only for the devnet |
| 70 | The committee driver's settle check compares heads read one after another against 5 blocks; same cause as 66 | open | only for the devnet |
| 71 | `./devnet-deploy.sh --only 20` ends with "All 20 steps done" after one step | open | only for the devnet |

Also here: 49 (the devnet's release check, worked around in 0f26db7) and 68 (the runbook, corrected in its as-run lines).

### 3.7 Operator host (1 row)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 55 | Every IAP `gcloud compute ssh` prints a three-line NumPy warning that buries the scripts' `[WARN]` lines | open (install NumPy for gcloud's Python, or filter the line) | only for the devnet |

Also here: 48 (the cron job that removes worktrees).

## 4. Issue candidates

Upstream issues worth filing, grouped by problem. Nothing is posted; this table feeds local drafts only. devnet-genesis rows are local follow-ups and are left out, as are rows fixed in PR #68 with nothing left open.

| Slug | Repository | Title | Rows | Why an issue |
|---|---|---|---|---|
| publish-worker-gateway-image | telcoin-network | No CI job builds or publishes the worker-gateway image, and the binary's --version reports no commit. | 2, 29, 30 | Mainnet refuses the gateway until a published digest can be pinned; a build that reports its commit and features also replaces the faucet string probe. |
| joiner-sync-stalls-behind-allowlist | telcoin-network | A node not yet in the validators' P2P allowlists falls up to 476 blocks behind while its dials to them hang. | 67, 11 | Every validator that joins after genesis meets it until the epoch after its `activate()`; the mechanism is inferred and needs a code reading. |
| log-silent-peer-refusal | telcoin-network | A validator logs nothing when it drops a non-admitted peer, while healthy observers warn about sync once a second. | 33, 39 | A joiner that cannot sync gives no clue on either side, and the one sync WARN that does appear fires on healthy nodes. |
| forwarder-one-client-per-rpc-node | telcoin-network | An RPC node is one client IP to every gateway, so a busy sender draws 429s and 30 s demotions. | 10, 42, 43, 44 | RH5 drew a 429 and 61 re-sends at 400 transfers through one RPC node; the warning does not say which gateway was demoted. |
| gateway-keepalive-close-after-429 | telcoin-network | After a 429 the worker gateway closes the keep-alive connection without sending Connection: close. | 35 | Every mainnet gateway sits behind Caddy; whether this turns into 502s for other clients is not verified. |
| node-record-api-standalone-build | telcoin-network | bin/node-record-api does not build on its own: SealedHeader is not serde::Serialize without feature unification. | 28 | Its image cannot be built at 5533ff73a; the node build hides the missing bound. |
| public-rpc-forwarding-guidance | telcoin-network | Public-RPC docs advise --forward-txs, which skips node records; record forwarding has only the gateway as pre-check. | 9 | An RPC operator needs one supported mode and to know what is checked before a transaction reaches a worker; tn-node-deployment has no script support for either. |
| ship-rotated-release-key | tn-node-deployment | lib/release-keys ships only the rotated-out RSA key, so nodes refuse a release signed with the new ed25519 key. | 49 | Blocks every signed scripts release from now on; the owner is preparing the PR, so the issue tracks it and the key's rollout to existing installs. |
| healthcheck-bare-port-binds-loopback | tn-node-deployment | setup-observability.sh writes a bare --healthcheck port, which now binds loopback, so monitors reach nothing. | 3, 38 | Monitors and load-balancer checks fail silently on any main-based image, which mainnet runs. |
| caddy-acme-empty-email | tn-node-deployment | install-caddy.sh registers Caddy's ACME account with an empty email, so a failed renewal warns nobody. | 54 | Every Caddy host on mainnet (gateway hosts, the RPC node) depends on renewal. |
| finalize-reports-validators-as-observers | tn-node-deployment | setup-node.sh tells every host it is an observer, including genesis validators it has just read as Active. | 51 | Every genesis validator operator reads it at install time, and the JSON is machine-read. |
| public-rpc-serves-tn-namespace | tn-node-deployment | A native public-RPC node serves the tn_* namespace, admission snapshot included, to any caller. | 12 | Exposure decision for the RPC operator; also telcoin-network if `--http.api` cannot leave the namespace out. |
| p2p-committee-not-scriptable | tn-node-deployment | firewall-setup.sh --p2p-committee has no --json, waits on a lock, not a snapshot, and its tool is off sudo's PATH. | 7, 23, 68 | Every validator operator runs it by hand per host, and a driver has to retry a refusal the wait could have avoided. |
| scripts-start-stopped-node | tn-node-deployment | setup-node.sh, edit-config.sh --set and setup-observability.sh --json start a node that was deliberately left stopped. | 15, 16, 37 | A staged coordinated start needs nodes to stay stopped; the devnet stops them again after each step. |
| admission-version-floor-missing | tn-node-deployment | MIN_ADMISSION_VERSION is a TODO, so setup-node.sh writes admission settings it cannot check against a pinned image. | 14, 57 | Mainnet images are pinned by digest, so the check can never pass as it stands. |
| joiner-admission-renderer | tn-node-deployment | The admission renderer cannot express a joiner that bootstraps from a hub with the genesis set as committee peers. | 8 | A validator joining after genesis has no native way to write its admission settings. |
| admission-map-complex-keys | tn-node-deployment | The admission renderer refuses BLS keys written as YAML complex keys, and its error does not say why. | 32 | PyYAML's `safe_dump` writes keys over 128 characters that way, so a generated map fails with a misleading message. |
| unknown-flags-exit-zero | tn-node-deployment | firewall-setup.sh, install-caddy.sh and remove-node.sh ignore unknown flags and exit 0, so old scripts skip new flags. | 17, 18 | An operator on older scripts gets success and no change; `--status` without `--json` would also hang a scripted caller (inferred). |
| rpc-private-address-bind | tn-node-deployment | A validator's RPC cannot bind only its private address because the scripts' local readers hard-code 127.0.0.1. | 4 | The mainnet layout then rests on ufw alone, and a firewall reset needs the upstream turned off around it. |
| observability-scrape-gaps | tn-node-deployment | Observability scrapes neither the gateway's metrics nor the allowlist's nftables counters or sync timer. | 13 | The new mainnet components have no native monitoring. |
| fresh-install-false-alarms | tn-node-deployment | A fresh install warns that committee members are down before genesis and prints a curl error before the UI listens. | 52, 64 | On launch day these sit beside real warnings on every host. |
| checksum-sidecar-rule-conflict | tn-node-deployment | gen-checksums.sh and AGENTS.md disagree on when checksum sidecars change, and main's ui/requirements sidecar went stale. | 22, 46 | 46 is fixed in PR #68, but the conflicting rule that let CI fail on every pull request remains. |
| allowlist-status-hides-sources | tn-p2p-allow-sync | The allowlist status does not say where the trusted RPC node's entry comes from or which sources were dropped. | 72 | 992 drops in 16 min on validator-1 cannot be told apart from a peer missing from the list. |
| txgen-amount-in-metric-label | tn-transaction-generator | The generator puts the transfer amount in the type label, so every transaction creates a new metric series. | 62 | Unbounded growth in the generator and in Prometheus (7,930 lines after 25 min). |
| txgen-faucet-drip-reverts | tn-transaction-generator | On a chain built without the faucet feature, the generator's native faucet drip reverts in eth_estimateGas. | 63 | Every drip is a WARN and an `outcome="err"`; the cause is not verified, and the error is a tn-contracts one. |

Open rows not proposed as issues: 45 and 53 belong to PR #68's own code and go into its review; 19, 20 and 21 do not matter for mainnet (reasons in 3.1); 36 is a note.

## 5. Not carried further

- 1, 5, 40: fixed in PR #68; nothing is left beyond merging it and shipping a signed scripts release.
- 6: fixed in PR #68 for a node-less gateway host; the load-balancer backend mode is not needed since decision 6 removed the Google LB.
- 24: fixed in PR #68 for the gateway block; hosts without a gateway behave as before.
- 41: fixed in PR #68 where the gateway code used the two patterns; a review note with no failure seen.
- 46: fixed in PR #68; the rule that let it go stale is carried with 22.
- 25: duplicate of 48 and closed by c00ebe5, although its own status column still says open.
- 48: closed by c00ebe5 (tn-contracts as a submodule, a gate that checks real files).
- 66: fixed in devnet-genesis 42f2850, with a 7-case test of which 4 fail on the old file.
- 31: a build-host note; plain `--init` is enough for the image.
- 34: probing from the host works.
- 36: the gateway's own start-up warnings; same-host is refused on mainnet.
