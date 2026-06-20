# TODO — Devnet: restore SSH (grant2), deploy obs, secure BLS, bring RPC online — 2026-06-19

Closing the 4 loose ends after `devnet-deploy.sh` stopped before step 9. Execute in order; gate after each.
Reach nodes over the WireGuard overlay (`utun6`=10.100.9.6=hannibal/grant2); GCP REST/API works fine.

## Phase 1 — Restore SSH for grant2 (metadata break-glass)  [LOW RISK] ✅ DONE
- [x] Pre-flight: VPN up (hub+node1 ping ok); local tnvpn key pubkey == plan's grant2 key; all 5 nodes' `ssh-keys` metadata ABSENT (safe to set, no clobber); OS Login off (project+instance); baseline node1 probe = `Permission denied (publickey)` (node doesn't trust grant2; hub does).
- [x] 1. Injected `tnadmin:<grant2-pubkey>` into all 5 nodes' instance `ssh-keys` metadata (Updated x5).
- [x] 2. Cleared stale `known_hosts` for 10.100.2.1–.5.
- [x] 3. Verified all 5 return hostname over `tn_ssh` (5/5, attempt 1).
- [x] 4. Persisted into `.tnvpn` via `sync_keys_to_registry_nodes` — 6 key lines installed on all 5.
- [x] 5. Removed metadata break-glass (canary node1 first, verified .tnvpn path holds, then 2-5); trust now `.tnvpn`-only.
- [x] GATE PASSED: 5/5 hostname over tn_ssh AFTER metadata removal; `authorized_keys.tnvpn`=6 lines incl. tnvpn-grant@hannibal on all 5; sshd AuthorizedKeysFile honors `.ssh/authorized_keys.tnvpn`.

## Phase 2 — Step 9 per-node observability  [LOW RISK] ✅ LOGS DONE / metrics blocked server-side
- [x] Canaried node1 -> discovered Alloy was crash-looping fleet-wide (driver reported "running" falsely).
- [x] Root-caused + fixed TWO tn-node-deployment bugs (branch fix/obs-alloy-docker-storage-and-chain-label, commit d16bb34):
      (A) Alloy docker storage dir mounted under image's 473:473-owned /var/lib/alloy; --cap-drop=ALL strips
          CAP_DAC_OVERRIDE so container-root can't traverse it -> "mkdir /var/lib/alloy/data: permission denied".
          Fix: mount + --storage.path at ${OBS_DATA_DIR} (/var/lib/telcoin-alloy, parent /var/lib traversable),
          matching the native unit; all hardening flags kept. (B) TN_CHAIN hardcoded "adiri" -> map from NETWORK
          (testnet stays adiri byte-identical; devnet->devnet).
- [x] Pushed fixed lib/observability.sh to all 5 nodes (sha c4b2d66, verified); re-ran obs node-by-node
      (1 validator restart each, quorum 3/4 held; each rejoined consensus before next).
- [x] GATE (logs): all 5 Alloy active + shipping; Loki {job="telcoin-node"} shows all 5 with chain=devnet
      (28 streams/10m, zero adiri leakage). ✅
- [x] FOLLOW-UP #1 CODE DONE (live redeploy pending tunnel): metrics 401 root cause was NOT a missing Caddy
      route — the committed Caddyfile already has the token-gated /api/v1/write block. The LIVE Caddy was
      serving a STALE config: `docker compose up -d` doesn't recreate a container when only a bind-mounted
      file's CONTENTS change, so redeploys kept an old Caddyfile lacking the route -> Grafana catch-all ->
      "Invalid API key". FIX (common 8ef0e9d): bringup-remote.sh now reloads each config-bearing service
      after `up -d` (caddy reload / SIGHUP prometheus / restart loki). Also parameterized prometheus
      `monitor:` per-network (OBS_MONITOR=obs-devnet). LIVE: re-run create-obs-instance.sh -> verify
      /api/v1/write 204 + tn_info series.
- [x] FOLLOW-UP #2 CODE DONE (live redeploy pending): reth's ~1.1MB lines exceed Loki's per-line cap. The key
      is `max_line_size` (NOT `max_entry_size`); default 262144=256KB. FIX (common 8ef0e9d): loki-config.yaml
      max_line_size=2097152 (2MiB), lossless (no truncate). Documented in obs README for self-hosters.
      LIVE: redeploy obs -> force a >256KB line ingests (no 400).

## Phase 3 — BLS Docker LoadCredential fix upstream + re-finalize  ✅ DONE
- [x] tn-node-deployment branch `fix/tn-node-deployment-docker-fixes` (3 commits, LOCAL — operator pushes/PRs):
      d16bb34 (obs alloy storage+chain, Phase 2), a09fd68 (BLS Docker LoadCredential in setup-validator.sh +
      setup-observer.sh — wrapper reads $CREDENTIALS_DIRECTORY, `-e TN_BLS_PASSPHRASE` name-only, README updated),
      0154f38 (tn_node_launch_target → docker wrapper, so obs flag injection still works post-wrapper).
- [x] Render-validated the loadcredential wrapper+unit locally before any deploy (bash -n + 5 assertions PASS).
- [x] DISCOVERED + handled: (a) `--json --phase=finalize` can't emit obs reth flags (ENABLE_* are interactive-
      testnet-only) → re-finalize alone drops obs; (b) the wrapper moves `docker run` out of the unit, breaking
      obs_ensure_reth_flags injection → fixed via tn_node_launch_target. Method (user-chosen): finalize (writes
      LoadCredential unit; `start` is a no-op while running) THEN obs re-run (injects obs flags into the wrapper +
      ONE real `systemctl restart` that activates everything).
- [x] Rolled node-by-node over overlay (canary node1 → 2 → 3 → 4 → observer-5). Each: push setup script +
      lib/common.sh (sha-verified) → finalize → obs → verified consensus rejoin BEFORE next. genesis re-stage
      verified byte-identical (no-op). Passphrase read from each node's own file, never echoed.
- [x] GATE PASSED: all 5 units `LoadCredential=bls-passphrase:…`, ZERO embedded passphrase (was `=tornado`);
      chain advancing (epoch 7, all 5 in lockstep, restarts=0/oom=false per node); all 5 still ship to Loki
      (chain=devnet); obs flags present in every wrapper. A healthy rejoined node PROVES LoadCredential
      delivers the passphrase (else BLS decrypt fails). Branch is local — operator pushes + opens PR.

## Phase 4 — Public RPC edge (steps 10–12)  [RISKIEST: SSH-lockout + IAP dep — confirm first]
CODE DONE this session (2026-06-20); LIVE rollout is tunnel-gated (operator brings up WG, then driveable
over TN_SSH_TRANSPORT=overlay):
- [x] Step 10 CODE: firewall-setup.sh `--json --enable` (lockout-safe, tn-node-deployment bc44be9) +
      devnet-firewall.sh `--enable` mode (one node at a time, SSH re-verify, ABORT on loss). LIVE: run
      `./devnet-firewall.sh --enable` over overlay (observer canary first), `tn_ssh <n> true` after each.
- [x] Step 11 CODE: setup-firewall.sh drops public tcp:8545 from devnet-allow-web (reth binds loopback,
      Caddy fronts RPC). LIVE: re-run setup-firewall.sh to reconcile IPs + confirm 80/443.
- [x] Step 12 CODE: dns.sh overlay branch (common 9a0053c) + config-caddy.sh per-node port resolution
      (common f905061, observer wss -> :8554). LIVE: dns.sh over overlay (re)applies Caddy + verifies
      eth_blockNumber + WSS-101; setup-load-balancer.sh builds LB; create node{1..5} + rpc A-records.
- [ ] GATE (live): https://node{N} + https://rpc serve eth_blockNumber; wss://node{N} 101; rpc -> LB IP;
      consensus advancing + restarts=0 fleet-wide after each step.

## Review — Phase 2 follow-ups + Phase 4 code (2026-06-20)

ALL CODE for the remaining Phase 2 follow-ups + Phase 4 landed + statically/render-verified; committed on
`main` in all 3 repos (NOT pushed, no co-author). LIVE rollout is tunnel-gated (client IAP broken on this
Mac; operator brings up WG, then drive it over TN_SSH_TRANSPORT=overlay).

Commits:
- tn-node-deployment (main): fast-forwarded the 3 docker-fix commits (d16bb34/a09fd68/0154f38) onto main,
  then 7bd1351 (reth --ws + --http.addr/--ws.addr 127.0.0.1 in all 4 launch heredocs; WS_PORT derived +
  persisted to .node-meta), bc44be9 (firewall-setup.sh lockout-safe --json --enable).
- common (main): 8ef0e9d (Loki max_line_size 2MiB + bringup reloads config-bearing services + per-network
  prometheus monitor), f905061 (config-caddy.sh resolves RPC/WS ports from .node-meta), 9a0053c (dns.sh
  TN_SSH_TRANSPORT=overlay branch).
- devnet-genesis (main): submodule bumps (common 9a0053c, tn-node-deployment bc44be9) + config.sh
  OBS_MONITOR=obs-devnet + setup-firewall.sh (drop public tcp:8545) + devnet-firewall.sh --enable + tasks/*.

Plan corrections caught by verifying against source (not trusting the plan):
1. reth WS port = 8546 + instance*2-2 (observer 8554), NOT 8546+(instance-1) (=8550) — reth
   rpc_server.rs adjust_instance_ports.
2. Loki key is `max_line_size`, not `max_entry_size`.
3. metrics 401 = stale LIVE Caddyfile (bind-mount + `compose up -d` doesn't recreate), not a missing route.
4. reth already binds RPC/WS to loopback by default -> public 8545 was dead weight (safe drop); --ws was OFF.

Render/static verification (all PASS): 4-variant heredoc render (BLS LoadCredential intact, --ws/loopback,
.node-meta 8545/8546 + 8541/8554); config-caddy port-resolution precedence; dns.sh both transports;
firewall --json --enable lockout order (SSH+overlay+kuma before enable); devnet-firewall --enable
abort-on-SSH-loss. bash -n on every edited script; Loki + Prometheus YAML valid.

Docker+native parity: every tn-node-deployment change touched all four launch heredocs (docker+native ×
TPM+LoadCredential) and render-verified for both install methods; .node-meta write + port derivation are
install-method agnostic.

REMAINING (live, tunnel-gated — see Phase 2/4 LIVE notes above): operator `wg-quick up tn-wg0`; then
Phase 2 (redeploy obs; verify 204 + tn_info + big-line ingest); Phase 4 over overlay (--ws restart
node-by-node + ss -tlnp; UFW enable; VPC reconcile; Caddy/LB/DNS), each gated on consensus rejoin + restarts=0.

---

# TODO — Devnet deploy unblock: route per-node steps over the WireGuard overlay — 2026-06-19

IAP SSH is broken **client-side** (gcloud's new lightweight websocket drops instantly on this
macOS box; no env/property/flag override). Bypass it by reaching nodes over the existing
WireGuard overlay. Nodes were recreated 2026-06-19 → new WG pubkeys, so re-enroll them with the
hub first. Hub = `tnadmin@10.100.0.1` (project `tn-devops-sandbox`, instance `wg-hub`).

Division of labor:
- **Autonomous (no tunnel / no sudo):** Phase C code, Phase B serial reads + registry edits.
- **Operator (local sudo):** Phase A — bring the operator's WG tunnel up.
- **After tunnel up (driveable; ssh/scp + REST only, no local sudo):** Phase B hub redeploy +
  verify, Phase D drivers, Phase E verify/commit.

## Phase C — overlay transport toggle (code; safe, default=iap, behavior unchanged unless overlay) ✅ DONE
- [x] `devnet-lib.sh`: `TN_SSH_TRANSPORT` toggle (default `iap`); when `overlay`, source
      `wg-ssh-lib.sh` with the gcloud shim suppressed (`TN_USE_VPN=0` around the source);
      overlay branch in `tn_iap_ssh`, `tn_iap_ssh_stdin`, `tn_iap_scp`. Header comment updated.
- [x] `devnet-keygen.sh`: overlay branch in local `tn_iap_scp_down`.
- [x] Syntax-test both transports — PASS: iap leaves gcloud a file + tn_ssh undefined; overlay
      defines tn_ssh/tn_scp/tn_overlay_ip, keeps gcloud a FILE (shim suppressed), restores
      TN_USE_VPN=1, resolves 10.100.2.1/.4/.5 correctly.

## Phase B — re-enroll the 5 recreated nodes (serial → registry → hub)
- [x] Read `WG_NODE_PUBKEY=` from each node's serial console (REST) — all 5 captured (2 boots each,
      1 distinct value), validated 32-byte:
      v1 `lm4QOBnt…7Q0=` · v2 `fnt9MJi3…GEE=` · v3 `btL8ZlSC…O3Y=` · v4 `slFDkkkq…bE8=` · obs5 `H2Lgx2ed…9mI=`.
- [x] `common/wgvpn/peers/registry.csv`: replaced 5 pubkeys, bumped date 2026-06-19, renamed node-5
      `validator-5-devnet` → `observer-5-devnet`. Overlay IPs unchanged. Pre-flight: 17 valid peers render.
- [x] Wrote break-glass `tasks/hub-redeploy-overlay.sh` (hub_redeploy is IAP-hardcoded; this runs the
      same bringup-hub.sh over the overlay to `tnadmin@10.100.0.1`). Syntax + hub-constant resolution OK.
- [x] Ran `./tasks/hub-redeploy-overlay.sh` — 17 peers rendered, `wg syncconf` (no drop), operator
      peer kept handshake. All 5 devnet nodes handshaked the hub within ~18s (verified hub-side:
      endpoints + fresh handshakes + bidirectional transfer).
- [x] **(gate)** all 5 reachable via `tn_ssh` — BUT first had to clear stale `~/.ssh/known_hosts`
      entries for 10.100.2.1–.5 (recreated nodes → new SSH host keys; `accept-new` rejects a CHANGED
      key by design). `ssh-keygen -R` each, then 5/5 returned hostname. Lesson for Phase E.

## Phase A — operator brings the tunnel up (LOCAL SUDO — operator runs; runtime already installed)
- [ ] `sudo install -m 600 ~/.config/tnvpn/tn-wg0.conf /etc/wireguard/tn-wg0.conf`
- [ ] `sudo wg-quick up tn-wg0`
- [ ] verify: `sudo wg show` (handshake w/ hub `hqIDsk…`, nonzero rx/tx), `ping -c3 10.100.0.1`

## Phase B.5 — hub split-brain recovery (operator ran add-peer.sh + hub redeploy on 2nd machine `hannibal`)
- [x] That redeploy re-rendered wg0.conf from the OTHER machine's stale registry → reverted my devnet
      key fix → all 5 nodes unreachable again. Other machine had added `grant2` maintainer (10.100.9.6).
- [x] Read the hub's leftover `/tmp/wgvpn/peers/registry.csv` + grant2.pub; merged = my devnet fix +
      grant2 row + grant2.pub. Diff vs hub = ONLY the 5 devnet rows. Operator re-ran redeploy → nodes back.
- [ ] FOLLOW-UP: commit merged registry + grant2.pub in `common` so both machines converge via git;
      operator must NOT run hub ops from `hannibal` until then (re-clobber risk).

## Phase D — run gated steps over the overlay (`export TN_SSH_TRANSPORT=overlay`; run drivers via bash 5.x)
- NOTE: drivers have `#!/bin/bash` but use mapfile (bash4+); macOS /bin/bash is 3.2 → run as `bash driver.sh`.
- [x] **Step 5 keygen** — all 5 keyed + node-info collected. REQUIRED a tn-node-deployment fix: the
      keygen `docker run` in setup-validator.sh:742 / setup-observer.sh:785 lacked `--user` (ran as image
      nonroot 1101; DATA_DIR owned by host telcoin 1002 → "Permission denied"). Added
      `--user ${docker_uid}:${docker_gid}` + `-e HOME=/home/nonroot` (numeric --user has no passwd entry
      → $HOME=/ → reth log dir unwritable). Pushed patched scripts to all 5 nodes (sha-verified).
- [x] **Step 6 genesis-build** (local) — needed (a) local Docker Desktop running, (b) a `common`
      submodule fix: `common/genesis.sh:164` passed `--chainid` but v0.11.0 binary wants `--chain-id`
      (value 32285 unchanged → hash-safe; adiri leaves CHAIN_ID empty so unaffected). committee+genesis built.
- [x] **Step 7 finalize** — all 5 nodes' services started. Needed TWO fixes:
      (a) tn-node-deployment runtime `ExecStart` had the SAME `--user`/HOME bug as keygen → added
      `-e HOME=/home/nonroot` to setup-validator.sh:925 + setup-observer.sh ExecStart (re-pushed to nodes);
      (b) `devnet-finalize.sh` didn't pass `--listener-primary/--listener-worker` → node built a bare
      `/p2p/<id>` multiaddr ("Multiaddr is not supported") → added them from intIP (in-scope driver fix).
      Validators' finalize reports rc=1 (premature health check pre-quorum) but services run; observer ok:true.
- [x] **GCP consensus firewall** — `devnet-allow-consensus`(+egress) had STALE node IPs (recreated nodes
      → new static IPs). Ran sanctioned `setup-firewall.sh` (REST) → reconciled to current internal+external
      /32s. **Result: 4 validators reached quorum, consensus advancing (round ~190, voting_power 3/3);
      observer executing consensus output.** ✅ DEVNET IS LIVE.
- [ ] Step 8 obs VM (local/REST — obs-devnet already RUNNING).
- [ ] **Step 9 observability** (`./devnet-observability.sh`, overlay) — needs OBS_INGEST_TOKEN
      (Secret Manager `obs-ingest-token` in tn-devnet — fetchable via gcloud REST). NOT yet run.
- [ ] **Step 10 firewall** (CAUTION: host UFW currently INACTIVE; this activates it. Confirm ruleset
      keeps :22 from 10.100.0.0/16; apply per-node; re-test `tn_ssh <node> true` after each). NOT yet run.

## Cross-repo changes to COMMIT (3 repos) + node-side drift to reconcile
- `devnet-genesis`: devnet-lib.sh + devnet-keygen.sh (TN_SSH_TRANSPORT toggle), devnet-finalize.sh
  (listener fix), tasks/hub-redeploy-overlay.sh (new break-glass), tasks/todo.md.
- `common`: peers/registry.csv (5 devnet keys + observer-5 rename + grant2 merge) + peers/ssh/grant2.pub;
  genesis.sh (--chain-id). NOTE: hannibal divergence — commit so both machines converge via git.
- `tn-node-deployment`: setup-validator.sh + setup-observer.sh (keygen+runtime --user/HOME fixes).
  Also pushed directly to the 5 nodes (sha-verified) — node copies match local until next boot re-clone.

## Phase E — verify, clean up, commit
- [ ] End-to-end: nodes healthy (`tn_ssh <node> 'docker ps'`), consensus advancing, RPC up.
- [ ] Commit registry fix in the `common` submodule (real correctness fix).
- [ ] Optionally commit the `TN_SSH_TRANSPORT` toggle + tasks/lessons.md note.

## Review (this task)
(filled in as phases complete)

---

# TODO — Devnet migration to `tn-node-deployment` (v0.11.0-devnet, Ubuntu) — 2026-06-19

Three repos, clear ownership (all siblings under `/Users/grant/coding/telcoin/`):
- `tn-node-deployment` — Association per-node tooling. Remote `…/tn-node-deployment.git`, branch `main`, clean. (Workstream A.)
- `common` submodule = repo `deploy-networks-common-` (trailing dash; remote of devnet's submodule). Shared/parameterized. (Workstream B.) Checked out @48cbfdb; adiri also pins 48cbfdb.
- `devnet-genesis` (this repo) — fleet/GCP orchestration + new per-node driver scripts. (Workstream C.)
- `adiri-genesis` — frozen testnet; absorbs 6 moved scripts (B1 Commit B). Pins common@48cbfdb; do NOT bump its pointer.

SCOPE (this session): author + commit scripts/config on branches. No mutating gcloud, no live deploy, no PR merges (operator does those). The end-to-end runbook is operator-run. [confirm via questions]

## Workstream A — tn-node-deployment ✅ DONE — commits 72b3923 (PR1), 5cbed98 (PR2), f50d08b (PR3) on `main`; bash -n clean, additive-only, effective-URL reaches config.alloy, all lib fns verified.
### PR1 — devnet network profile + genesis injection
- [ ] A1 `lib/common.sh`: add `DEVNET_CHAIN_ID="32285"`, `DEVNET_CHAIN_NAME="devnet"` (+ RPC/EXPLORER empty defaults) near consts (lines 12–21).
- [ ] A2 `setup-validator.sh` + `setup-observer.sh`: add `devnet)` arm to `json_set_network()` before `*)` reject (val 1208–1215 / obs 1290–1297).
- [ ] A3 both: `step_write_config()` — change `chain_subdir` to handle `devnet` (val 797–845 / obs 832–890).
- [ ] A4 both: `step_write_config()` `search_paths` — prepend `${TN_GENESIS_DIR:+"$TN_GENESIS_DIR"}`; add `--genesis-dir <path>` flag to `main()` parser (sets `TN_GENESIS_DIR`).
- [ ] A5 `lib/common.sh`: add `is_testnet_like()` (testnet OR devnet); make `require_testnet` accept testnet-like (used by setup-observability.sh). Leave soft `is_testnet` prompts testnet-only.
- [ ] A6 `lib/testnet-addons.env` + `lib/observability.sh`: add overridable `OBS_PUSH_URL_DEVNET`/`OBS_METRICS_PUSH_URL_DEVNET` (default empty, fail-closed); select when `NETWORK=devnet`. Adiri `_TESTNET` defaults untouched.
### PR2 — scriptable `setup-observability.sh`
- [ ] A7 add `--json` non-interactive block (interactive menu stays default): `--enable-logs/--enable-metrics/--enable-health`, `--disable-*`, `--region`, `--token`/`TN_OBS_TOKEN`, `--push-url`/`--metrics-push-url` (or `OBS_PUSH_URL`/`OBS_METRICS_PUSH_URL` env). Add json_event/json_done helpers (copy per-script pattern).
### PR3 — `install.sh --yes`
- [ ] A8 honor `--yes/-y/--force` + `TN_ASSUME_YES` to skip overwrite prompt (lines 64–80). Default unchanged.
### PR4 — DEFERRED (firewall-setup.sh --json already supports 49590/49594/udp + 43174/tcp, SSH-safe).
- [ ] A-verify: interactive testnet flow byte-identical (pick network 1); devnet keygen emits node-info.yaml; finalize loads custom `--genesis-dir` (chainid 32285); obs --json brings up telcoin-alloy; install.sh --yes non-interactive.

## Workstream B — common/ ✅ DONE — commits: 4189fb7 (B1 move), 089e2d3 (B2 genesis lib), 0220774 (B3 obs-wipe), b8d89d5 (B4 wgvpn), 42c58aa (B5 static-IP) on common `main`; adiri 1ac4bdb (Commit B). NOTE: B4 plan-deviation — `WG_NODE_ENFORCE` already exists (gates activation, default 0); devnet must set the NEW `WG_NODE_FIREWALL=0` (not WG_NODE_ENFORCE) — adjust C2.
- [ ] B1 move 6 adiri-only scripts → adiri root (start-validator-node.sh, start-observer-node.sh, update.sh, update-staggered.sh, startup.sh, config-apache.sh). Commit B in adiri (copy + repoint config.sh L58/124/127/129 to `${REPO_ROOT}/…` + README note); Commit A in common (`git rm` the 6 + README). Verify shared orchestrators only reference start scripts via config.sh env vars.
- [ ] B2 `common/genesis.sh` sourceable: extract `tn_genesis_pull_validator_info` / `tn_genesis_build_committee` / `tn_genesis_distribute_and_start`; direct exec runs all three (adiri byte-identical); add `GENESIS_LIB_ONLY=1` early-return guard.
- [ ] B3 add `common/observability/wipe-obs-data.sh` (params OBS_INSTANCE_NAME/OBS_ZONE/PROJECT_ID): ssh → `docker compose down` → wipe loki/prometheus dirs → `up -d`; `--yes`/`FORCE=true` guard; print OBS_HOSTNAME. Add `--wipe-data` to `create-obs-instance.sh`.
- [ ] B4 `common/wgvpn/node/wg-node-bootstrap.sh`: `WG_NODE_ENFORCE` (default 1=adiri enforcing; 0=overlay-only, no policy-drop nftables → UFW authoritative).
- [ ] B5 `common/create-instances.sh`: static external IPs via `--address`, gated by `USE_STATIC_IPS` + `STATIC_IP_NAMES[]`; add `reserve-static-ips.sh` (idempotent `gcloud compute addresses create`). Reuse any existing adiri static path.

## Workstream C — devnet-genesis ✅ DONE (except C1, deferred) — commits 32247bd (C2 config), de3076c (lib+gitignore), 612ae13 (9 drivers), 5662c18 (C4 reset-network), 76179c6 (Commit C common bump). C1 (submodule add) deferred until Workstream A is merged upstream so the pin references a real commit.

## Workstream C — devnet-genesis root (new scripts + config)
- [ ] C1 add `tn-node-deployment` submodule (pin to commit containing Workstream A) — AFTER A merges.
- [ ] C2 `config.sh` additions: NODE_DEPLOY_MODE, TN_* dirs, genesis dirs, Ubuntu IMAGE/OBS_IMAGE, STARTUP_SCRIPT_PATH→devnet-startup.sh, USE_STATIC_IPS + STATIC_IP_NAMES, WG_NODE_ENFORCE=0, TN_KUMA_SRC, TN_OBS_ENABLE_* (default-on), OBS_METRICS_PUSH_URL fix.
- [ ] C3 new root scripts: devnet-startup.sh, devnet-keygen.sh, devnet-genesis-build.sh, devnet-finalize.sh, devnet-observability.sh, devnet-firewall.sh, devnet-update.sh, devnet-wipe.sh, devnet-deploy.sh.
- [ ] C4 repoint `reset-network.sh` → devnet-wipe.sh + devnet-finalize.sh.
- [ ] C5 BLS passphrase via `TN_BLS_PASSPHRASE` env (untracked/Secret Manager), persisted to `/etc/telcoin/<type>/bls-passphrase` 600; never committed/echoed.

## Cross-cutting
- [ ] Firewall: single port manifest (config.sh ⇄ testnet-addons.env); GCP source-of-truth + UFW safety-net; nftables overlay-only (WG_NODE_ENFORCE=0).
- [ ] Verification: genesis-hash equivalence before/after B2 refactor (adiri inputs); shellcheck new scripts; adiri config.sh paths still resolve after Commit B.

## Decisions / open
- [ ] Branch/commit structure across the 3 upstream repos (see questions).
- [ ] BLS passphrase source path / Secret Manager secret name.

---
---

## Review — what landed + what the operator must do next

ALL CODE AUTHORED + COMMITTED (no pushes, no PR merges, no mutating gcloud — per session scope).

Commits by repo:
- tn-node-deployment `main`: 72b3923 (PR1 devnet profile+genesis injection), 5cbed98 (PR2 setup-observability --json), f50d08b (PR3 install.sh --yes). Additive-only; interactive testnet UX byte-identical; effective-URL reaches config.alloy; all lib fns verified.
- deploy-networks-common- `main`: 4189fb7 (B1 move 6 scripts out), 089e2d3 (B2 genesis sourceable, 17 ins/0 del = behavior-identical), 0220774 (B3 obs-wipe), b8d89d5 (B4 WG_NODE_FIREWALL), 42c58aa (B5 static IPs).
- adiri-genesis `main`: 1ac4bdb (B1 Commit B: absorb 6 scripts + repoint config.sh). Its `common` pointer deliberately NOT bumped (still @48cbfdb, which still carries the scripts) — adiri unaffected.
- devnet-genesis `main`: 32247bd, de3076c, 612ae13, 5662c18, 76179c6 (see headers above).

Key plan deviations (justified, evidence-backed):
1. WG_NODE_FIREWALL (new) instead of reusing WG_NODE_ENFORCE — the latter already exists (gates *activation*, default 0) and adiri's lockdown depends on it; reusing it as the plan said would break adiri's lockdown. Devnet sets WG_NODE_FIREWALL=0.
2. OBS_IMAGE stays Debian (NOT Ubuntu) — obs-vm/startup-obs.sh hardcodes the Debian docker apt repo; Ubuntu would fail docker-ce install. Only the validator IMAGE moved to Ubuntu.
3. keygen/finalize use `sudo env TN_BLS_PASSPHRASE=...` (not bare `sudo VAR=`) — env-only secret, no flag fallback; bare form isn't guaranteed past sudoers env_reset.
4. devnet-genesis-build relaxes set -e/-u/pipefail around the genesis build to match adiri's (unset-state) env exactly.

Verified statically: node-info.yaml schema IDENTICAL between keygen output and the genesis build input (same NodeInfo struct) — only a filename rename. All scripts bash -n + shellcheck clean.

OPERATOR HANDOFF (cannot be done autonomously):
- [ ] Push tn-node-deployment + open PR1/PR2/PR3; merge to main. Confirm repo is PUBLIC (devnet-startup.sh https-clones it) or bake a deploy key.
- [ ] C1: after A merges, `git submodule add` tn-node-deployment pinned to the merged commit.
- [ ] Push common (deploy-networks-common-), adiri-genesis, devnet-genesis commits.
- [ ] Provide BLS passphrase: `export TN_BLS_PASSPHRASE=...` or put it in `.secrets/bls-passphrase` (gitignored).
- [ ] Ensure Secret Manager `obs-ingest-token` exists in tn-devnet (devnet-observability.sh fetches it).
- [ ] Run the one-time migration: `./devnet-deploy.sh --yes` (reserves IPs, recreates VMs on Ubuntu, keygen→build→finalize→obs→firewall→LB). DESTRUCTIVE VM recreate.
- [ ] Scratch-VM verify the upstream A changes (keygen emits node-info; finalize loads --genesis-dir chainid 32285; obs --json brings up telcoin-alloy; install.sh --yes) and genesis-hash equivalence for adiri before adiri bumps its common pointer.

---
---

# ARCHIVE — prior completed runbooks (kept for reference)

# TODO — Recover obs-devnet observer (https://obs.devnet.telcoin.network/) — 2026-06-18

Stack: Loki + Grafana + Caddy on VM `obs-devnet`, zone `us-west2-a`, project `tn-devnet`, reserved IP 34.20.241.60.
Symptom: endpoint times out (packets dropped). Every node ships reth logs to `/loki/api/v1/push` → obs down = no central logs.

## Root cause (CONFIRMED — guest OS network stack dead; GCP edge healthy)
- client `curl https://obs.devnet.telcoin.network/` → `(28) Connection timed out after 15002ms` (drop, not refuse).
- IAP SSH → `Connection timed out during banner exchange` (tunnel reaches :22, sshd can't handshake → guest wedged).
- serial console: `23:40 ens4: Could not set DHCPv4 address: Connection timed out` → `23:45 ens4: Failed`;
  `169.254.169.254:80 i/o timeout` (metadata dead, still failing 2026-06-18T11:36); martian source 172.18.0.4;
  dockerd/containerd "Waiting for containerd to be ready" churn. Onset ~2026-06-16 23:40 UTC.
- Diagnosis: guest lost DHCP lease + metadata connectivity + Docker-bridge/iptables corruption. NOT a Caddy/app
  or firewall bug. GCP control plane still reports RUNNING; inbound packets reach edge, find no guest net → dropped.

## Fix: reboot (idempotent startup-obs.sh remounts /mnt/obs-data; services restart: unless-stopped; reserved IP
## persists so DNS+cert stay valid; fresh boot forces clean DHCP + rebuilds Docker iptables).

## Execution
- [x] Step 1 — read-only triage + forensics: SSH banner-timeout (confirms diagnosis); serial console captured;
      forensic boot-disk snapshot `obs-devnet-netfail-20260618` = READY (30 GB).
- [x] Step 2 — graceful stop (exit 0, no reset needed) → start (exit 0); RUNNING; IP unchanged
      34.20.241.60 ext / 10.168.0.3 int (reserved IP persisted → DNS + rendered .env stay valid).
- [x] Step 3 — verify recovery: network FIXED (clean DHCP, metadata reachable, no martians; Caddy UP).
      BUT endpoint = 502: **/mnt/obs-data (obs-devnet-data, 100GB pd-ssd) is 100% FULL** → loki + grafana
      crash-loop (loki: "no space left on device"; grafana: "database or disk is full"). 2nd root cause,
      independent of the network wedge, NOT fixable by reboot. loki/chunks=97G. Retention IS set
      (336h/14d, compactor retention_enabled) but disk fills in ~8d (~12GB/day) → fills before 14d
      retention deletes anything; compactor can't run on a full disk (deadlock). ⇒ need to free space.
      DECISION (user-approved): expand to 200 GB, keep 14d retention (preserve data, match validators).
      DONE: gcloud disks resize obs-devnet-data 100->200 GB (READY) + on-box `resize2fs /dev/sdb` (whole-disk,
      no growpart) → /mnt/obs-data now 197G, 99G free, 50% used. `docker compose restart loki grafana` →
      caddy/grafana/loki all Up; grafana healthy (dashboards provisioned); loki up (ring warming, transient
      "empty ring" 500s on first pushes — nodes already pushing again from node IPs). E2E verified below.
- [x] Step 4 — bring-up path used: `docker compose restart loki grafana` after the resize; stack
      auto-restarts via restart:unless-stopped. All 3 containers Up; loki ingester auto-joined ring at
      19:17:12 (~33s), /ready=ready, "empty ring" cleared.
- [~] Step 5 — root-cause + prevention (see Review). FOLLOW-UPS: (a) add obs to uptime-kuma; (b) investigate
      validator-3-devnet log gap; (c) watch disk plateau (~14d × ~12GB/day ≈ ≤170GB on the 200GB disk).

## Verification (from this laptop unless noted)
- [x] 1. TCP/HTTP reachable: GET / -> HTTP/2 302 -> /login (was: connection timeout). NOT a timeout.
- [x] 2. Grafana served: 302 -> /login; container healthy (dashboards provisioned; no "disk full").
- [x] 3. Loki route + token gate: GET /loki/api/v1/push (no token) -> 401 (Caddy bearer gate).
- [x] 4. Cert valid: Let's Encrypt issuer, CN=obs.devnet.telcoin.network, Jun 10 -> Sep 8 2026 (reused
        existing cert from /mnt/obs-data/caddy/data; no new ACME challenge).
- [x] 5. Guest healthy: post-19:07 serial console has NO martian / metadata-timeout / DHCP-failed lines.
- [~] 6. Logs flowing: loki /ready=ready; fresh ingest last 2m — val-1 18650, val-2 18730, val-4 10781,
        obs-5 8439 lines. ⚠️ validator-3-devnet SILENT ~30m (node-side, NOT obs) — FLAGGED for follow-up.

## Review
obs.devnet.telcoin.network RESTORED. TWO independent root causes (the plan anticipated only the 1st):
  (1) Guest network-stack wedge (DHCP lease lost + metadata 169.254.169.254 i/o timeout + Docker-bridge
      martian-source corruption) since 2026-06-16 23:40 → inbound packets dropped → client TIMEOUT.
      Fixed by graceful stop/start: clean DHCP, metadata reachable, Docker iptables rebuilt, Caddy up;
      reserved IP 34.20.241.60 preserved so DNS + LE cert stayed valid.
  (2) /mnt/obs-data 100% full (loki/chunks = 97G of node logs) → loki ("no space left on device") + grafana
      ("database or disk is full") crash-loop → 502. Reboot CANNOT fix this. Fixed by online-expanding
      obs-devnet-data 100->200GB (pd-ssd) + `resize2fs /dev/sdb` → 197G / 50% used, all data preserved.
Loki retention (336h/14d, compactor retention_enabled) WAS set, but the disk filled in ~8d (< 14d) so
retention never triggered, and the compactor can't run on a full disk (deadlock). With 200GB, usage will
plateau ≤~170GB once data ages past 14d and the compactor (starts ~10m post-boot) begins deleting — OK
headroom; monitor. Forensic boot-disk snapshot obs-devnet-netfail-20260618 retained for offline analysis
of the network wedge trigger (likely the recent caddy-migration / wg work disturbing Docker iptables).

---

# TODO — Devnet disk: diagnosis + recovery (corrected from original plan)

Nodes (`config.sh`): validator-1..4-devnet + observer-5-devnet (node1–node5), project `tn-devnet`.
Reach: `--tunnel-through-iap` (public :22 removed at 2026-06-15 lockdown; `wg-allow-iap-ssh` is the open door;
VPN `tn-wg0` down + no passwordless sudo). Do NOT source `wg-ssh-lib.sh`. Always `--project=tn-devnet`.

## CORRECTED DIAGNOSIS (Phase 1 overturned the plan's hypotheses)
- **Active outage**: chain HALTED at block 265 (0x109), epoch 235, since ~13:12 UTC (~2h). Both up nodes frozen at 265.
- **3 of 4 validators CRASHED** on `No space left on device (os error 28)`:
  - val-4 died first (~10:12), then val-2 + val-3 within 3s of each other (~13:12) → quorum (3/4) lost.
  - val-1 still up but **isolated** (1/4, DialFailure to peers) and itself at **100% disk (165M free)** — about to crash too.
  - observer-5 up, 68% disk, just following (not in quorum).
- **Root cause = legitimate chain data, NOT logs/images.** `consensus-db/epochs` = **88–89 GB/validator** (~94% of disk).
  - Logs bounded everywhere (OBS token SET on all 5; LogConfig max-size:100m/max-file:5; biggest json-log 87M).
  - Images ~1 GB total, ~0 reclaimable. kad = 56K. → Phase 2 cleanup reclaims ~nothing → **SKIPPED**.
- ⚠️ Recurrence risk: epochs/ grows unbounded on 1h-epoch devnet; 200 GB buys time but will refill. Durable fix =
  epoch retention/pruning in telcoin-network (code change, out of scope here). FLAG to team.

## Decision (user-approved): Expand all 5 → 200 GB online + restart the 3 crashed validators + verify.

## Execution
- [x] Phase 0 — IAP reach confirmed (val-1 probe)
- [x] Phase 1 — assess all 5 (read-only) → diagnosis above
- [x] ~~Phase 2 cleanup~~ — SKIPPED (logs/images/kad reclaim ~nothing; OBS token already seeded fleet-wide)
- [x] Phase 3 + recovery (online resize 100→200 GB; growpart + resize2fs; restart crashed):
  - [x] 1. val-1 — resized 200 GB → 197G/50%. (NO restart; protected last validator.)
  - [x] 2. val-4 — resized 200 GB → 197G/50%; telcoin restarted (Exit 0).
  - [x] 3. val-2 — resized 200 GB → 197G/51%; telcoin restarted (Exit 0).
  - [x] 4. val-3 — resized 200 GB → 197G/51%; telcoin restarted (Exit 0).
  - [x] 5. node5 — resized 200 GB → 197G/34%. (NO restart.)
  - NOTE: this Debian image had NO partition tools (no growpart/parted/sfdisk); installed
    cloud-guest-utils via apt (egress to deb.debian.org works). resize2fs/partx/e2fsck were present.

## Verification
- [x] All 5 `df -h /` = 197G total; `disks list` sizeGb=200. Used: validators ~51%, observer 34%.
- [x] Logging still bounded (LogConfig max-size:100m/max-file:5 on all 5; alloy running).
- [x] Quorum restored: val-1/2/3 + observer-5 HEALTHY at epoch 236, consensus advancing (quorum reached
      every round, rounds/consensus_number climbing). Chain is LIVE at 3/4 + observer.
  - EVM block flat at 266 = NORMAL: outputs are empty (batches=0, no txs) + non-epoch-closing → execution
    skipped. Block advances on next tx or epoch close.
- [ ] ⚠️ val-4 NOT fully recovered: stuck at epoch 233 (3 behind), rejecting epoch-236 certs
      (`InvalidEpoch {theirs:236, ours:233}`), can't retrieve newer epoch records. A clean restart did
      NOT fix it → consensus-layer epoch-catchup wedge, separate from the disk crash. DECISION PENDING.

## Review
**Disk emergency RESOLVED.** Root cause was NOT the plan's hypotheses (logs/images bounded fleet-wide).
It was legitimate `consensus-db/epochs` growth (~89 GB/validator) filling the 100 GB disks → all 4
validators hit `No space left on device` and crashed (val-4 ~10:12, val-2/3 ~13:12 UTC), halting the
chain at block 265 (~2h). Fixed by expanding every boot disk 100→200 GB online (no resync) and
restarting the crashed validators → 3/4 validators + observer healthy and live at epoch 236.

OPEN: val-4 epoch-catchup wedge (awaiting user decision: escalate/preserve vs resync).

⚠️ RECURRENCE (~2 weeks): epochs/ grew ~6.8 GB/day (89 GB in 13 days since 2026-06-05 provisioning).
200 GB has ~100 GB headroom → refills ~early July unless epoch retention/pruning is addressed in
telcoin-network. Also: parameterize create-instances.sh:119 disk size via config.sh for re-provisions.

Reusable ops scripts created in tasks/ (IAP-based): run-on-all.sh, resize-disk.sh, recover-down-node.sh,
verify-all.sh, check-progress.sh, diag-epoch.sh, assess.sh, diagnose-health.sh.
