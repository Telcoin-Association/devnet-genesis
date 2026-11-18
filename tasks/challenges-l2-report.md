# Launch 2 rehearsal: challenges report

Rows covered: 1-84 of `tasks/challenges-l2.md`.
Sources: that list, the text of tn-node-deployment PR #68 (branch `worker-gateway`, scripts 2.2.0, open, not merged), the approved plan (`tasks/l2/plan-approved-2026-11-17.md`), the verification table (`tasks/verification-l2-2026-11-17.md`) and the index of issue drafts (`tasks/issue-bodies/TITLES-l2.md`).
Rows 1-15 were seeded from the plan before the run; apart from row 10 they carry no run evidence, and the report says so where a consequence depends on it. Rows 73-84 come from the verification run (runbook section 10, the restart check included) and from the generator's journal read during it (81).

## 1. Summary

The devnet was redeployed in mainnet shape with tn-node-deployment: four genesis validators behind worker gateways (validator 4's on its own host), a committee P2P allowlist on the validators, a native public RPC node, and a fifth node that stakes after genesis.
84 challenges: 7 fixed in PR #68, 10 worked around or fixed on the devnet side, 67 open (14 of the open ones are devnet-genesis follow-ups and 1 is the operator host).
Counted from each row's status column as it stands now (the list now carries PR #68's fixes for rows 1, 5, 6 and 24 itself). A row whose upstream side is still open counts as open even where the devnet has a workaround or its own fix (14, 15, 23, 49, 80); "fixed in the record" (78, 84, runbook corrections) counts as fixed on the devnet side. Section 3 holds one status cell per row, and these counts are those cells.
Before mainnet, the ones that matter most:
- Build and publish a worker-gateway image in telcoin-network CI and pin its digest in a signed scripts release; until then mainnet refuses the gateway (2, 29).
- Add the rotated release key (ed25519 95A38484…AE47) to tn-node-deployment's `lib/release-keys`; nodes refuse a release signed with it today (49).
- Find where the node's sync waits on dials that the committee firewall drops; a node outside the allowlists fell up to 476 blocks behind, and every validator that joins after genesis meets it (67, 11, 33).
- Make `setup-observability.sh` write a health address a monitor can reach; a bare `--healthcheck` port now binds loopback (3, 38).
- Decide how the public RPC node's forwards fit the gateways' per-IP limit (100 rps, burst 200, 30 s demotion after a 429) (10, 42).
- Fix the gateway's close after a 429: with Caddy in front, a throttled client gets a 502 for about 6 % of its requests (75, 35).
- Give operators a sign that a restarted validator votes again, since "CvvActive" comes first, and a check of the other members before a manual restart (82, 83).
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
- What happens: node 5 synced only from the RPC node, which the firewall does not touch. Before validator 1's allowlist went on (02:05-02:27Z) its per-minute `catchup_distance` peaked at 2-3; at 02:28Z it reached 25, and after validators 2-4 (02:31Z on) it reached 14 to 48 consensus outputs, about 30 s of stall and up to 476 blocks behind validator 1, while the RPC node stayed within 6. Its dials to the validators hang and `Stream(NotConnected)` appears against all four. The next epoch showed the cause: from 03:28Z, the minute the validators' sets began to list node 5, its sync was steady again (94-99 catch-ups a minute, never more than 4 behind) in minutes that ran at 8 to 10 blocks a second, while their admission still refused it. So the dropped packets stall the sync; the refusal after a handshake does not. The code path is not read.
- Neither side explains it: a validator that refuses a non-admitted peer completes the QUIC handshake and drops it with no log line at `-vvv` (RH0: 9-27 handshakes per validator). The joiner's record now reaches the validators only through the hub; the plan says lookup backoff can delay its allowlist entry by up to 30 min (row 11 has no run evidence).
- Who meets it: every validator that joins mainnet after genesis, from its first start until the epoch after its `activate()`.
- Proposed: in telcoin-network, find where a dial that gets no answer holds the observer's sync up, keep sync from waiting on it, and log the refusal on the validator. Until then a joiner's operator should expect uneven sync (stalls of about 30 s) from its first start until the epoch after `activate()`; it clears by itself within five minutes of that epoch's start. In tn-node-deployment the admission renderer also cannot express "bootstrap from a hub, committee peers = genesis set" for a joiner (row 8).

### 2.4 Health checks bind loopback and monitors fail silently (rows 3, 38)
- What happens: on telcoin-network `main` a bare `--healthcheck <port>` binds 127.0.0.1. `setup-observability.sh --enable-health` still writes the bare port plus a ufw rule for the monitor's address, so the rule admits a monitor that can reach nothing, and the monitor or a load-balancer check sees a healthy node as down. Comments in `lib/common.sh` and `setup-observability.sh` still say the bare port binds every interface. Read from code; not run against a real monitor.
- Who meets it: testnet and devnet operators who turn on health monitoring with a main-based image. On mainnet the scripts refuse the health add-on (`require_testnet`, `lib/common.sh:9205-9212`) and `check-node.sh:2138-2151` fails a mainnet node that carries `--healthcheck`, so a mainnet validator has no health endpoint for a monitor at all; the gateway's public `/ready/any` is the path left (the owner's Kuma monitors move there, P4). The scripts' README on `main` (line 454) already says the bare port will bind loopback from the next release: known, documented, not fixed.
- Proposed: write an explicit address with the port that matches the ufw rule, and correct the comments. PR #68 writes `--healthcheck 0.0.0.0:43174` only for the standalone gateway case.

### 2.5 The public RPC node is one client to every gateway (rows 10, 42, 43, 44, 76, 77)
- What happens: each gateway allows one client IP 100 requests a second (burst 200) and 32 connections, and the RPC node's forwarder does not pass the original client, so every forwarded transaction counts against the RPC node's address. In RH5, 400 transfers sent about 210 forwards to one gateway within a second and drew one 429; the RPC node set that gateway aside for 30 s and re-sent 61 transfers, and 400/400 confirmed in 4.65 s. All transfers of one sender go to one validator's gateway first, so a busy sender concentrates there. A restarting gateway answers 503 for about 11 s and is set aside for 30 s too, so a rolling restart concentrates forwards on the others. The warning `demoting unreachable validator RPC endpoints from forward admission demoted=1 cooldown_secs=30` names no endpoint.
- The verification confirmed the limit per real client address: one client got its burst of 200, then about 100 a second, while a second client was not throttled (verification row 8). In the restart check a gateway gave 503 for 5 s and 200 again after about 6 s (verification row 11).
- The forwarder's drop count overstates loss (76): the RPC node logs `the forwarded transaction was rejected; no validator accepted it` with `nonce too low` several times a second and counts each in `tn_reth_forwarded_txns_dropped_total{reason="rejected"}` (959 against 12,864 queued in the first 75 min, 7.5 %), but the transactions named were already included. Whether the forwarder re-sends after a slow answer or the generator sends twice is not verified.
- The RPC node is the gateways' only read target (77): each gateway's query route carries 165-202 timeouts and 1-8 `upstream_unreachable` from before the verification window and none since. The likely time is step 15, when the RPC node restarted (not verified); who sent those reads is not known.
- Who meets it: the RPC operator and the launch team on launch day; anyone who alarms on the forwarder's `rejected` count (76).
- Proposed: an installer option in `setup-gateway.sh` for the per-client limit, raised for the operator's own RPC node, or the forwarder passing the client address with the RPC node as a trusted proxy (PR #68's smoke test showed the limit already follows a forwarded client). Name the endpoint and validator in the warning. Tell a forwarder re-send from a client double-send, then keep transactions already included out of the warning and the `rejected` count (76). 77 is a note: while one RPC node is the only read target, its restart leaves redirected reads nowhere to go.

### 2.6 The gateway breaks keep-alive after a 429 (rows 35, 75)
- What happens: after a 429 the gateway closes the connection without sending `Connection: close`, and the next request on it fails (BrokenPipe, reproduced with one client). With Caddy in front this is now seen (75): one client with 24 kept-alive connections sent 6,000 requests to node1 in 11.28 s and got 200 x 1,283, 429 x 4,360 and 502 x 357, about 6 %. Caddy's journal on validator-1-devnet holds 357 `server closed idle connection`: Caddy sent the next request on a connection the gateway had closed. Caddy's connections to the gateway are shared by all clients, so another client's request can draw the 502 (inferred; not seen for another client: 6 requests of a second client and 4 forwards of the RPC node in the window). A 502 to the RPC node's forwarder would set that validator's gateway aside for 30 s (not tested).
- Who meets it: any client that exceeds a gateway's limit; through Caddy's shared connections possibly other clients and the public RPC node's forwarder (inferred).
- Proposed: in the gateway, send `Connection: close` or keep the connection open. In tn-node-deployment's Caddy block, retries or no keep-alive to the gateway would hide it.

### 2.7 Restarting a validator (rows 82, 83)
- What happens: `tn_nodeMode` answers "CvvActive" about 3 s after a validator starts, before it has signed anything (82; on validator-2-devnet the log's `subscriber starting in mode node_mode=CvvActive` came at 04:09:22.8Z, 4.5 s after the unit became active). Whether it votes again shows only in its log (its own origin in `certificate committed` lines) or in the other validators' view, so an operator or a script that waits for "CvvActive" after a restart moves on too early; launch 1 saw a restarted member absent from commits for 30-60 s. A plain `systemctl restart telcoin` on a committee member checks nothing about the other members, and with four validators one restart leaves exactly quorum. The scripts' own restarts go through a guard, which reads `tn_nodeMode`; an operator's manual restart, or one by a package upgrade, has none (83).
- The restart itself went well (verification row 11). With the other three checked "CvvActive" first, validator 2 restarted at 04:09:15Z in about 7 s, its RPC answered "CvvActive" by 04:09:36Z (about 21 s), and 657 of its own certificates were committed by 04:13:00Z (597-708 for the other three origins), so no gap in its proposing shows; the second of its first new vote was not measured. Its allowlist was intact: the stateless md5 of `inet tn_p2p_allow` was the same at 04:11Z and 04:15Z, `check` rc 0, sync timer active. The public head never stopped (slowest stretch 1 block in 11 s), and the RPC node set no gateway aside. It rejoined within the epoch instead of sitting it out as a late genesis start does.
- Who meets it: every validator operator who restarts a node (an update, a config change), and the scripts' restart guards.
- Proposed: in telcoin-network, a mode or check that says the node is voting again, and restart guards that wait for it; in tn-node-deployment, a restart wrapper that checks the other members first, and OPERATOR.md wording that a plain restart does not.

### 2.8 Caddy's ACME account has no email (row 54)
- What happens: Caddy registers its Let's Encrypt account with `"email":""` (journal on validator-1-devnet, step 13), so a certificate that fails to renew warns nobody.
- Who meets it: every operator whose gateway host or RPC node runs Caddy.
- Proposed: a certificate-expiry check (in `check-node.sh` or the monitoring), since an email alone no longer brings a warning: Let's Encrypt ended its expiry emails in 2025 (from memory, not re-checked). An ACME email in Caddy's global options is still worth having as the account's contact.

### 2.9 Genesis validators are told they are observers (row 51)
- What happens: `setup-node.sh`'s closing JSON says `"node_type":"observer"` and "following consensus as a full node; staking to validate is optional" on every host, the four genesis validators included, right after its own on-chain check printed "Status: Active".
- Who meets it: every genesis validator operator at install time, and any tool that reads that JSON.
- Proposed: build the closing message from the on-chain status the script has just read, and add a status field beside `node_type`. The fixed `"node_type":"observer"` is deliberate (`setup-node.sh:222-226`: the Node Manager UI's slot), so the field stays; the sentence beside it is what misleads.

### 2.10 `tn_*` is public on the public RPC node (row 12)
- What happens: on a native public-RPC node the `tn_*` namespace, admission snapshot included, answers any caller. Seeded from the plan; the row has no run evidence.
- Who meets it: the RPC operator.
- Proposed: decide which `tn_*` methods are public and leave the rest out of what the node serves: in the API list tn-node-deployment renders for a `0.0.0.0` bind (row 20). The scripts put `tn` in `--http.api` on purpose (`setup-node.sh:2518-2521`), so this is a decision for the maintainers, not an oversight; the draft is held as a question.

### 2.11 The RPC node refuses batches over 100 calls (row 80)
- What happens: the launch 2 RPC node refuses a JSON-RPC batch of more than 100 calls (`-32010 The batch request was too large`, `Exceeded max limit of 100`); launch 1's endpoint took 500. The devnet's `devnet-basefee-check.py` sent 500 headers per batch and failed with rc 2; with batches of 100, `--last 2` passed in 16 s.
- Who meets it: any tool that batches against a public RPC node of this release: explorers, indexers.
- Proposed: document the limit for RPC users. Whether it is a setting the RPC operator can change is not checked.

### 2.12 The committee allowlist is hard to drive and to read (rows 7, 23, 68, 72, 73, 74, 79)
- What happens: `firewall-setup.sh --p2p-committee` is a manual step per host with no `--json`. Its `--wait 30` waits for the tool's lock, not for an authoritative snapshot, so a node that is not yet authoritative is refused at once and a driver must retry (the devnet driver does). The tool sits in `/usr/local/libexec/telcoin/`, off sudo's PATH: `sudo tn-p2p-allow-sync check` answers `command not found`; with the full path it gives `result=ok missing_total=0 mismatch_total=0`. Its status shows `keys=4` beside five addresses without saying the fifth is the trusted RPC node, and the drop counter (`accept=177128 drop=992` on validator-1, 16 min after `on`) does not say which sources were dropped, so a scanner cannot be told from a peer that should have been listed.
- `check` exits 3 on a validator for up to five minutes after every epoch start, until its own timer runs, because its set is from the epoch before (79). In epoch 3, from 03:24:45Z, it exited 3 on all four at 03:25:15Z, on validators 1 and 4 still at 03:27:15Z, and 0 on all four at 03:29:15Z; node 5 was in the snapshots within 30 s and in the sets 2.5 to 4.5 min later (verification row 3). In that window a node that became eligible at the boundary is still dropped by that validator, and a monitor that alarms on a non-zero `check` fires at every epoch change. The seat is covered (the entry comes two epochs before it), so this is about the monitor and the wording, not about joining.
- `check-node.sh` prints `Bootstrap peers:  $(cat /etc/telcoin/bootstrap-peers.yaml)`, the launch flag's text, not the peers (73). It prints nothing about the allowlist when it is on and healthy, so its report cannot show an operator, or a reviewer of that report, that the allowlist is on (74: no line on validator-4-devnet, where it is on with `check=ok`).
- Who meets it: every validator operator turning the allowlist on or reading `check-node.sh`, any monitor that alarms on `check` (79), and whoever debugs a joiner (2.3).
- Proposed: `--json`, a wait for an authoritative snapshot, the tool on PATH or its full path in OPERATOR.md, and a status that names each address's source and the dropped sources. In `check-node.sh`, the peers instead of the flag's text and one OK line with the set's size and the last sync (73, 74). A sync run at the epoch change, or a monitor rule and wording that allow the five-minute window (79).

### 2.13 Scripts start a node that was left stopped (rows 15, 16, 37)
- What happens: finalize has no `--no-start` (the devnet stages by start-then-stop); `edit-config.sh --set` restarts the unit unconditionally (PR #68 guards only its new `gateway_upstream` key); `setup-observability.sh --json` forces "yes" to its restart question and runs `systemctl restart` whenever it adds a log or metrics flag. The devnet stops each node again after these steps.
- Who meets it: the launch team, if mainnet's genesis validators are staged stopped before a coordinated start as on the devnet; a node started early runs alone.
- Proposed: `--no-start` for finalize, and return before the restart when the unit is not active (row 37's smallest fix) in `setup-observability.sh` and `edit-config.sh`.

### 2.14 Admission settings have no version floor (rows 14, 57)
- What happens: `MIN_ADMISSION_VERSION` is set to `0.17.0` (`lib/common.sh:2769`) under a `TODO(node team): confirm` comment, and the check behind it returns "unknown" for an image pinned by digest. With a digest-pinned image `setup-node.sh` prints `[WARN] Could not tell whether the image … is release 0.17.0 or later … writing them anyway`. On devnet it writes them; what it does on mainnet was not run.
- Who meets it: every validator operator at install time, since mainnet images are pinned by digest.
- Proposed: set the floor, and record the image's version next to the pinned digest so the check can be made.

### 2.15 Open items in PR #68's own code (rows 45, 53, 4, 40)
- `rpc-advertise` checks `https://<gateway name>/health` from the validator before it edits the record, with no flag to skip it; a validator with no outbound HTTPS to that name cannot advertise its gateway (45). Mainnet validators sit in a closed network, so this likely applies to them.
- On a gateway-only host, `firewall-setup.sh --enable` reports "SSH + overlay + kuma pre-allowed" while the host gets the SSH rule only (53, message only; seen on gateway-4-devnet).
- Standalone binds the validator's RPC and health check to every interface, guarded only by ufw, because local readers hard-code loopback; a firewall reset needs `gateway_upstream=off` around it (4).
- The SSH lockout from source spellings (`1.2.3.4/32` stored as `1.2.3.4`) is fixed only in PR #68; on `main`, re-entering an SSH source in the other spelling deletes the rule (40).
- Proposed: settle 45 and 53 in PR #68's review before it merges; 4 needs a private-address bind the local readers understand.

### 2.16 Unknown flags are ignored with exit 0 (rows 17, 18)
- What happens: `firewall-setup.sh`, `install-caddy.sh` and `remove-node.sh` drop unknown flags silently, so an older script given a newer flag such as `--gateway-from` exits 0 having done nothing; `setup-node.sh` only warns. `firewall-setup.sh --status` without `--json` falls into the interactive menu, which would hang a non-interactive caller (inferred, not run).
- Who meets it: a validator operator whose installed scripts are older than the runbook they follow.
- Proposed: refuse unknown flags; make `--status` print and exit when stdin is not a terminal.

### 2.17 Monitoring gaps and noise (rows 13, 39, 52)
- No native scrape for gateway metrics, nftables counters or the allowlist's sync timer (13; from the plan, no run evidence).
- A healthy non-committee node logs the WARN `consensus output sync exchange failed; trying next peer` about once a second (about 200 in three minutes on the RPC node, 47 on the joiner), which hides real sync trouble (39).
- `setup-observability.sh` warns on every fresh launch, twice, that committee members are down, because it reads the public RPC URL before the chain has started (52).
- Who meets it: the RPC operator and joiners (39), the launch team at genesis (52), everyone who monitors a node (13).

### 2.18 One transient gcloud failure stops a devnet driver (row 47; also 59)
- What happens: one `describe` hung on a TLS handshake to compute.googleapis.com for 300 s (`ReadTimeoutError … read timeout=300`); the teardown refused on "state unknown" with nothing changed, and a second run passed. The drivers' reads have no retry.
- Who meets it: only the launch team, and only if it drives mainnet hosts with gcloud-based drivers like devnet-genesis's. A validator operator who runs tn-node-deployment on their own host does not go through these drivers. The same condition applies to the serial post-start checks (59: step 14 took 1014 s for six nodes).
- Proposed: retry reads in the drivers if they are reused for mainnet; otherwise a devnet follow-up.

## 3. By repository

Each row appears once, under the repository where its fix belongs; "also" names the other one. Mainnet column: yes / no / only for the devnet (or the condition under which it matters).

### 3.1 tn-node-deployment (39 rows)

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
| 73 | `check-node.sh` prints `Bootstrap peers:  $(cat /etc/telcoin/bootstrap-peers.yaml)`, the launch flag's text, not the peers | open | yes |
| 74 | `check-node.sh` says nothing about the committee allowlist when it is on and healthy, so its report cannot show that it is on | open (one OK line with the set's size and the last sync) | yes |
| 83 | A plain `systemctl restart telcoin` on a committee member checks nothing about the other members; with four validators it leaves exactly quorum | open (note) | yes |

Also here: 75 (the Caddy block could hide the 502s), 79 (the 5-min sync timer), 82 (the restart guards that read `tn_nodeMode`).

### 3.2 telcoin-network: node, gateway, forwarder, images (21 rows)

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
| 35 | After a 429 the gateway closes keep-alive without `Connection: close`; with Caddy in front this is row 75 | open | yes |
| 36 | A same-host gateway with a loopback query endpoint warns at every start; a plain-http public redirect URL warns too | open (note) | no |
| 39 | A healthy non-committee node logs `consensus output sync exchange failed; trying next peer` about once a second | open (note) | yes |
| 43 | The RPC node's demotion warning names no endpoint and no validator | open | yes |
| 44 | A restarting gateway answers 503 for about 11 s and is demoted for 30 s | open (note) | yes |
| 67 | The validators' committee firewall degrades the sync of a node not yet in the eligible pool; also tn-node-deployment (`--p2p-committee`) | open (cause shown by the run: the stalls ended when the validators' sets listed node 5; the code path is not read) | yes |
| 75 | Behind Caddy a client over a gateway's limit gets a 502 for about 6 % of its requests (357 of 6,000) instead of a 429 (35 with Caddy in front); a 502 to another client is inferred, not seen; also tn-node-deployment (Caddy block) | open | yes |
| 76 | The RPC node warns `rejected … nonce too low` and counts `dropped{reason="rejected"}` (959 against 12,864 queued, 7.5 %) for transactions already included; re-send or double-send not verified | open | yes |
| 77 | Each gateway's query route shows 165-202 timeouts and 1-8 `upstream_unreachable` from before the verification window, none since; likely the RPC node's restart at step 15 (not verified) | open (note) | yes, while one RPC node is the only read target |
| 80 | The RPC node refuses a JSON-RPC batch of more than 100 calls (launch 1's took 500); whether the limit is a setting is not checked; also devnet-genesis (`devnet-basefee-check.py`) | open for the note; the devnet script is fixed (batches of 100) | yes (explorers, indexers) |
| 82 | `tn_nodeMode` answers "CvvActive" about 3 s after a start, before the node has signed anything; also tn-node-deployment (restart guards that read it) | open | yes |

### 3.3 tn-p2p-allow-sync (2 rows)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 72 | Status shows `keys=4` beside five addresses without naming the trusted RPC node, and the drop counter names no source; also tn-node-deployment | open | yes |
| 79 | For up to five minutes after every epoch start `check` exits 3 on a validator until its own timer runs, so a monitor that alarms on it fires at every epoch change; also tn-node-deployment (the 5-min timer) | open (note) | yes (monitoring) |

Also here: 23 (the tool's contract defines `--wait` as a lock wait, `docs/contract.md:287-288`) and 68 (its install path).

### 3.4 tn-transaction-generator (2 rows)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 62 | The transfer amount is in the `type` label, so every transaction is its own series (7,930 `txgen_` lines 25 min after start, unbounded) | open | no |
| 63 | The native faucet drip reverts in `eth_estimateGas` with `LowLevelCallFailure(bytes)` (0x37f33ed8) on an image without the `faucet` feature; the cause is not verified; also tn-contracts | open | no, unless the revert has a cause other than the missing feature |

Also here: 81 (the generator's Uniswap operations, which revert on the pools the devnet leaves empty).

### 3.5 tn-contracts (no row)

No row's fix belongs here. Also here: 63, whose revert is a tn-contracts error. Rows 25 and 48 are about the devnet's checkout of tn-contracts, not the contracts, and sit under devnet-genesis.

### 3.6 devnet-genesis: the devnet's own drivers (19 rows, local follow-ups)

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
| 61 | `devnet-txgen.sh`'s metrics check runs before the first submit and is not a gate | open (re-read for up to a minute, then fail) | only for the devnet |
| 65 | The contracts driver's "Next:" list misnumbers the txgen step and asks to commit an unchanged address book | open | only for the devnet |
| 66 | The staking driver's sync gate could not pass on a busy chain (two reads 3-5 s apart against a 5-block limit) | fixed in devnet-genesis (42f2850, test with 7 cases) | only for the devnet |
| 69 | `devnet-p2p-committee.sh --status` prints `check: no result line (exit 1)` per host while the allowlist is off | open (say "off: no check to run") | only for the devnet |
| 70 | The committee driver's settle check compares heads read one after another against 5 blocks; same cause as 66 | open (compare each host with a reference read just before it, as in the staking fix) | only for the devnet |
| 71 | `./devnet-deploy.sh --only 20` ends with "All 20 steps done" after one step | open | only for the devnet |
| 78 | The runbook's check of the firewall counters sent three UDP packets, which the counters' own movement (about 160 accepts and 1 drop a second) hides | fixed in the record (500 packets from an unlisted host, 3,000 from a listed one, counters every 2 s: drops +501, accepts +3,341) | only for the devnet runbook (a mainnet check needs the same method) |
| 81 | The generator's Uniswap operations revert in `eth_estimateGas` several times a minute (9 warnings among 178 submits in three minutes): the contracts step leaves two of the three pools empty (its gate asks for one); also tn-transaction-generator | open (devnet only) | only for the devnet |
| 84 | "Compare the allowlist table before and after" (runbook rows 11 and 12) proves nothing, since the listing carries packet counters; `nft -s list table inet tn_p2p_allow` is stateless | fixed in the record (stateless md5 from 04:11Z on) | only for the devnet runbook (a mainnet check needs the same method) |

Also here: 49 (the devnet's release check, worked around in 0f26db7), 68 (the runbook, corrected in its as-run lines) and 80 (`devnet-basefee-check.py`, fixed: batches of 100).

### 3.7 Operator host (1 row)

| # | Statement | Status | Mainnet |
|---|---|---|---|
| 55 | Every IAP `gcloud compute ssh` prints a three-line NumPy warning that buries the scripts' `[WARN]` lines | open (install NumPy for gcloud's Python, or filter the line) | only for the devnet |

Also here: 48 (the cron job that removes worktrees).

## 4. Issue candidates

26 local drafts were written from this section's earlier version, and `tasks/issue-bodies/TITLES-l2.md` is now the authority for what was drafted: it holds each title. Bodies are `tasks/issue-bodies/l2-<slug>.md`, each with a sources table in `tasks/issue-bodies/notes/l2-<slug>.sources.md`. Nothing is posted: the owner decides, draft by draft, whether one is filed, and each draft needs a figure-check against its sources table first.

| Slug | Repository | Rows | Advice |
|---|---|---|---|
| publish-worker-gateway-image | telcoin-network | 2, 29, 30 | file |
| joiner-sync-stalls-behind-allowlist | telcoin-network | 67, 11 | file after the re-read once node 5 is in the allowlists (evidence to add) |
| log-silent-peer-refusal | telcoin-network | 33, 39 | file |
| forwarder-one-client-per-rpc-node | telcoin-network | 10, 42, 43, 44 | file |
| gateway-keepalive-close-after-429 | telcoin-network | 35, 75 | file |
| node-record-api-standalone-build | telcoin-network | 28 | file |
| public-rpc-forwarding-guidance | telcoin-network | 9 | hold: a question about which mode is meant for mainnet; no run evidence, the pool's checks not read |
| forwarder-rejected-warning-for-included-txs | telcoin-network | 76 | file; stronger once a forwarder re-send is told apart from a generator double-send |
| healthcheck-bare-port-binds-loopback | tn-node-deployment | 3, 38 | file, to track the fix; testnet and devnet only (mainnet refuses the add-on) |
| caddy-acme-empty-email | tn-node-deployment | 54 | file, centred on the missing certificate-expiry check (the expiry-email point is from memory: check it first) |
| finalize-reports-validators-as-observers | tn-node-deployment | 51 | file |
| public-rpc-serves-tn-namespace | tn-node-deployment | 12, 20 | hold: `tn` is in `--http.api` on purpose; a question for the maintainers |
| p2p-committee-not-scriptable | tn-node-deployment | 7, 23, 68 | file |
| scripts-start-stopped-node | tn-node-deployment | 15, 16, 37 | file |
| admission-version-floor-missing | tn-node-deployment | 14, 57 | file |
| joiner-admission-renderer | tn-node-deployment | 8 | file |
| admission-map-complex-keys | tn-node-deployment | 32 | file |
| unknown-flags-exit-zero | tn-node-deployment | 17, 18 | file |
| rpc-private-address-bind | tn-node-deployment | 4 | not an issue: code that exists only in PR #68; raise it in that PR's review |
| observability-scrape-gaps | tn-node-deployment | 13 | file; no run evidence (from the plan) |
| fresh-install-false-alarms | tn-node-deployment | 52, 64 | file |
| checksum-sidecar-rule-conflict | tn-node-deployment | 22, 46 | file |
| check-node-allowlist-and-bootstrap-lines | tn-node-deployment | 73, 74 | file |
| allowlist-status-hides-sources | tn-p2p-allow-sync | 72 | file; the raw status says "5 IPv4 … (4 keys, 4 floor)", so the fifth address is not accounted for |
| txgen-amount-in-metric-label | tn-transaction-generator | 62 | file |
| txgen-faucet-drip-reverts | tn-transaction-generator | 63 | file; cause not verified |

Not drafted, as the index says:
- ship-rotated-release-key (tn-node-deployment, row 49): the owner is preparing that pull request.
- Rows 45 and 53 (PR #68's own code): for that pull request's review, with `rpc-private-address-bind`.
- devnet-genesis rows (26, 27, 47, 50, 56, 58-61, 65, 66, 69-71, 78): local follow-ups, listed in section 3.

The index does not name rows 77 or 79-84. Of these, 80 and 82 are open upstream points that no draft covers yet; 77, 79 and 83 are notes; 81 is devnet-only and 84 is fixed in the record. Other open rows without a draft: 19 and 21 do not matter for mainnet (reasons in 3.1), 36 is a note, and 55 belongs to the operator host.

## 5. Not carried further

- 1, 5, 40: fixed in PR #68; nothing is left beyond merging it and shipping a signed scripts release.
- 6: fixed in PR #68 for a node-less gateway host; the load-balancer backend mode is not needed since decision 6 removed the Google LB.
- 24: fixed in PR #68 for the gateway block; hosts without a gateway behave as before.
- 41: fixed in PR #68 where the gateway code used the two patterns; a review note with no failure seen.
- 46: fixed in PR #68; the rule that let it go stale is carried with 22.
- 25: duplicate of 48 and closed by c00ebe5.
- 48: closed by c00ebe5 (tn-contracts as a submodule, a gate that checks real files).
- 66: fixed in devnet-genesis 42f2850, with a 7-case test of which 4 fail on the old file.
- 78, 84: runbook corrections, fixed in the record (500 and 3,000 packets with the counters read every 2 s for 78; a stateless `nft -s` listing for 84). A mainnet run of the same checks needs the same method.
- 31: a build-host note; plain `--init` is enough for the image.
- 34: probing from the host works.
- 36: the gateway's own start-up warnings; same-host is refused on mainnet.
