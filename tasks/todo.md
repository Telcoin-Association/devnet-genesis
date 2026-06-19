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
