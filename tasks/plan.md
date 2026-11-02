# Plan: launch 1 — execute the reset (2026-10-31)

Source: the approved "Devnet launch 1 (execute the reset now) + launch 2 design" plan. Supersedes
the 2026-10-30 plan below (its code is complete and committed; nothing had touched GCP).
No Claude attribution on any commit/PR. Live state at start: 5 VMs RUNNING, 5 static IPs IN_USE,
head block 0x12f9e8, chain 0x7e1d; gcloud authenticated as the operator.

## Wave 0
- [x] project-context refresh (devnet-genesis, tn-cli-dev) spawned; gcloud token OK; live state recorded

## Wave 1 (parallel, opus; config.sh single writer = U4b)
- [x] U1 image pushed 10:21Z (cache hit, 11 s); index digest sha256:5257e768e657586a19e31308906bfacac0df95e5ca3da29a68f818f159d4a610 (gcloud + imagetools agree); 4 probes green by digest; log logs/push-v0.2.0-devnet-20261031T1021Z.log
- [x] U2 devnet-validator-key.sh (<nodeN> [--apply] [--rotate]; key only on a pipe to tn_secret_set; read-back via import-key; atomic config/accounts edits; 1,000,100 TEL = 0xd3c787962b1b04100000, NOT the brief's 0xd3c21b… which is 1,000,000) + docs/validator-key-provisioning.md + Further-reading links; stub matrix a-h green, 0 key hits
- [x] U3a-code tn-cli-dev: re-pin to 3f9b0709c FAILS upstream (tn-kad-client → tn-network-libp2p needs TN's [patch.crates-io] libp2p-quic/quinn-proto/libp2p-connection-limits; fix = 3 patch entries, proven in scratch, NOT applied → launch-2 decision); stays on c07d6d6a (risk: `tn node record` rejects >1 multiaddr, moot while nodes are Closed); FALLBACK_HANDLER → 0xfd0732Dc…Ec99; build OK, 193 tests pass (anvil e2e ran), ~/.cargo/bin/tn installed; R2 to fix safe-spec.example.toml:23-24 + cli.rs:418 wording
- [x] U3a-docs tn-cli-dev: 32285 in devnet docs (2017 kept for Adiri-only deploy doc), --trezor no longer forced (signer passthrough; R2 checks hot-key fallback), TARGET 10000000, devnet RPC default, README `tn` + compressed BLS + on-chain owners, v2 rewrites of new-validator/observer-to-validator, toml example faucet placeholder
- [x] U4a devnet-release-sign.sh prepare/verify (490 lines, +x); verdict stricter than the node (any NO_PUBKEY/ERRSIG/BADSIG fails); 30-row matrix green incl. real shipped keyring → rc 1 for an unlisted key; `releases/` stays committable (c3)
- [x] U4b config.sh RELEASE_TAG/KEYS_DIR/SIGNER_FPR; deploy step_6 → prepare; finalize gate rc0/3/1 + bypass only for rc 3; stub matrix green; HEAD-identical when RELEASE_TAG empty. Orchestrator pinned DOCKER_IMAGE digest (1 PLACEHOLDER left: node5 address)
- [x] U4c docs/release-signing-ceremony.md (3 paths, re-sign rule, evidence, troubleshooting); PR ref fixed to #52
- [x] U6 docs/mainnet-simulation-plan.md (452 lines; 8 design findings flagged [I]: forward target, default-allow-internal tcp:443, nc -u probe ambiguity, staged-joiner persistence, L2-C/L2-D overlap, port 80 for http-01, node 5 Closed pre-join)
- [x] U7 tasks/runbook-l1-2026-10-31.md (536 lines). ADOPTED D1b: `./devnet-deploy.sh --yes --only 12 </dev/null` right after D1 so the VPC /32 consensus rules learn node 2's Dallas IP before step 8 (otherwise nodes 1,3,4 = exact quorum through steps 8-11)

## Wave 2 (serialized)
- [x] R1: safe to run for real; A1 MAJOR fixed (set -x in CONFIG_FILE leaked the cast JSON → re-checked before cast), BENCH MAJOR fixed by orchestrator (benchmark/config.sh RELEASE_TAG=""), B1/B2 verdict tightened (NEWSIG reset, gpgv rc), docs aligned; 9 MINORs listed in tasks/checkpoint-l1-R1.md
- [x] R2 tn-cli-dev reviewed: F1 HIGH fixed (tn falls back to PRIVATE_KEY env/.env → new-validator.sh now requires exactly one of --ledger/--trezor/--hot-key), node-info-vs-Safe guard, Adiri HAS the handler (docs corrected), N+3 wording unified, leftovers fixed; 193 tests pass; commit 8462884 pushed (76a9cfd..8462884)
- [x] digest pinned; `./devnet-validator-key.sh node5 --apply` real: 0xd0154a8091de71cc81b3c6f95b73d0aa129da7b8, secret devnet-node5-validator-pk v1 (read back OK), 0 placeholders; gate check exits "refusing to run unattended" with no side effects; c1 = b1b49be
- [x] teardown --yes 10:58Z: 5 VMs + boot disks deleted, 5 addresses RESERVED (unchanged), obs/txgen/LB/disks intact (log logs/teardown-20261031T1058Z.log)
- [x] zone move: ZONES[1]=us-south1-a (+README/INSTRUCTIONS/issue.md), Sydney validator-2-devnet-ip deleted, devnet-rpc-ig-2 removed from devnet-rpc-backend and deleted → c2

## Wave 3 (deploy in three segments)
- [x] D1 steps 1-3 done 11:04-11:07Z (5 VMs RUNNING, startup markers in ~100 s); node 2 = 34.174.181.214 (us-south1); D1b step 12 done 11:09Z (consensus rules new=1 old=0, 10 /32s). DNS pause: operator sets node2 + admin.node2 → 34.174.181.214
- [x] D2 --from 5 done 11:12-11:22Z: keygen ok ×5, genesis built (Safe threshold 1, owners 7→8 with 0xAee… first, knob checks pass), prepare wrote releases/v0.2.0-devnet/{IMAGE_DIGEST,SHA256SUMS}, network-config installed ×5, step 8 stopped RELEASE_SIG_PENDING rc 3 (no node touched); node-info addresses match config ×5. PAUSE: operator signs on the laptop + DNS
- [x] operator pause done 2026-11-02: DNS node2/admin.node2 → 34.174.181.214 (authoritative + local agree); SHA256SUMS.asc verified rc 0 (VALIDSIG 4E36D35A4AB61B589861D01AC7173F2377CA7573, signed 2026-11-02 15:27Z); c3 committed before D3
- [x] D3 step 8 done 15:32-15:44Z: VALIDSIG gate passed, 5/5 nodes finalized + started (health :43174 answers); node4 post-check A3 hit a transient IAP ssh rc 255 (A1/A2/A4/A5 passed, A3 re-verified read-only with `devnet-network-config.sh --verify node4` → ok) so the run exited 1 before step 9
- [x] D3b steps 9-10 done 15:48-15:50Z (obs stack redeployed + Loki/Prometheus wiped; ufw 5/5); step 11 REFUSED by the quorum guard: validator-4 is CvvInactive
- [ ] FINDING (launch-1 F1): validators 1-3 reached quorum at 15:33:56Z (epoch 0 closed instantly: genesis timestamp was 2 days old) and ran ahead; validator-4's unit started 15:34:33Z, 36 s later, when epoch 1 was already >50 rounds in. Node 4 is stuck at round 0/1 (peers' certs "TooNew", its vote requests rejected "too new for max round 50"), restarts its epoch tasks every 69 s (the "Could not get the epoch record" line is normal startup noise, node 1 logged it too; the decisive line is "batch builder not started: node is in committee but not an active CVV; accepted transactions stay pooled until a later epoch"), follows the chain only via state-sync ("catching up consensus blocks") (consensus tip 2007 vs 2000), mode CvvInactive. Expected to rejoin at the epoch-1 close ≈16:34Z (all restart at round 1). Mainnet-relevant: a genesis validator starting >50 rounds (~20-40 s at this cadence) after its peers cannot join the running epoch.
- [x] D3c: step 12 done 15:58Z (10 /32s); step 13 done 16:13Z on attempt 4 (dns.sh Phase 4 loses a ~1 s race vs first-time Let's Encrypt issuance and stops at that node: nodes 1, 3, 4 each lost once; all 5 certs + WSS + admin 401 green); step 14 done 16:17Z
- [x] 16:37Z probe: validator-4 CvvActive after the epoch-1 close (all 4 CvvActive, node 5 Observer, all at 0x6c0 and rising) — finding F1 confirmed: a stranded genesis validator rejoins at the next epoch boundary
- [x] D3d `--only 11` 16:39-16:41Z: validator-1 flags already on the unit (restart refused at 15:50, process still without them), validator-2 enabled + restarted OK (back at round 1734 of epoch 2 within 3 min, so a mid-epoch restart does NOT strand a node), validator-3 restart REFUSED by the guard (counted validator-2, still catching up ~25 s after its restart, as down) → sweep stopped before 4 and 5. Finding F2: devnet-observability.sh's "after" check accepts CvvActive at 0 s, but a restarted member is absent from commits for ~30-60 s, so the next node's guard refuses.
- [x] recovery 16:43-16:49Z: validator-4 obs enable (guard refused its restart again) → validator-3 restart 16:46Z → validator-1 restart 16:47Z → observer-5 obs enable + restart; validator-4 restarted 16:59Z by hand (9 flag args live); every restart back in commits within ~60 s (all 4 origins), all CvvActive
- [x] step 15 done 16:49-17:0xZ: contracts deployed, address book verified (StablecoinManager 0xf09a4e51…, WTEL 0x…37E1, V2 router 0xe10cd8ed…, V3 SwapRouter02 0x7e905feb…); no faucet contract in the book (U3c settles)
- [x] step 16 first attempt failed on a local prerequisite: sops/age not on xerxes (user installed sops 3.9.4 + age 1.2.1)
- [x] step 16 second attempt failed: tn-transaction-generator/secrets/master.key missing on xerxes (only on the Mac + sops on the VM); recovered from the VM with the Secret Manager age identity, address = genesis-funded 0x46c26b4f…, seed 24 words
- [x] S1 preflight found a bug: `revert_selector` only matched `custom error 0x…`; cast 1.8 prints the resolved name + `data: "0x…"` → fixed (both formats, rc 0 when absent), helper unit-tested, gates green
- [x] step 16 done 17:38Z (binary built on the VM, secrets verified as the txgen user, unit active, Alloy wired); txgen submitting since 17:40Z (native transfers, stablecoin transfers/approves, Uniswap V2/V3 swaps, WTEL wrap/unwrap)
- [x] S1: dry run clean (lag 0); `--yes --watch-epochs 3` 17:21Z: minted via the Safe, staked 1,000,000 TEL, activate() in epoch 2 → PendingActivation (activationEpoch 3) → ✓ Active in epoch 3; committee(3) and (4) = genesis four, committee(5) includes node 5 (0xd0154a…); watch continues (log logs/stake-node5-20261102T1721Z.log)
- [x] U3b tn-cli-dev genesis fixtures = DG 6807ece (7 files), e2e_safe fixed (governance Safe proxy now delegates to SafeL2 0x29fcb43b… in the new genesis; test asserts slot 0), 193 tests pass, commit a9a9e10 pushed
- [x] U3c: devnet faucet = StablecoinManager proxy 0xf09a4e512cf87ecac839d732681959cefd83ecb9 (inherits TNFaucet; impl 0x1dbff831…; 23 eXYZ + native enabled, cooldown 86400 s; dripTo simulates OK); 0xb781… is the live ADIRI faucet so the default became per-network; native TEL drip reverts until the Safe calls grantMintRole(0xf09a…) on 0x…07e1 (calldata 0xc2e3273d…f09a…); `tn status` 5 nodes epoch 2 height 4864, `tn fees` 10000000/8, `tn safe` 1-of-8 0xAee… first, `tn node record` refused; tn-cli-dev 6962def pushed

## Wave 4
- [x] S1 stake node 5 (see above)
- [x] V1 tasks/verification-l1-2026-10-31.md: 12/12 pass at 17:58Z (new: V1-a Alloy overwrites the `network` label; V1-b old txgen hit the new chain from 16:13Z and its txgen_* metrics stopped 17:39Z; V1-c Loki job label; V1-e committee(5) seats node 5 in place of node 4)
- [ ] V2 node 5 CvvActive from epoch 5 (19:33:56Z) + membership over ≥3 epochs + basefee --last 4
- [x] close-out: todo.md review section, lessons (3 entries), plan ticks, memory; c4 pushed (V2 appends later)

## Launch 2 (mainnet simulation)

Design: docs/mainnet-simulation-plan.md. Starts only after launch 1 (the 2026-10-31 reset) is live and reviewed; it is a second teardown + deploy.

- [ ] G0: launch 1 live and reviewed, node 2 in us-south1; record baseline (base fee per epoch, RPC submit-to-inclusion latency).
- [ ] L2-A config model: append sentry-{1..5}-devnet at indices 5..9 of INSTANCE_NAMES/NODE_ROLES/ZONES/NODE_NAMES/STATIC_IP_NAMES; add SENTRY_OF, NODE_ROLES "sentry", LB backend roles, per-node INSTANCE_TAGS.
- [ ] L2-A common PR: common/create-instances.sh honors per-node INSTANCE_TAGS; reserve 5 sentry static IPs in each validator's region.
- [ ] L2-B network-config renderer roles validator|sentry|joiner per the admission matrix (trusted_nodes, bootstrap_peers, committee_peers = 4 genesis validators everywhere).
- [ ] Confirm at telcoin-network 3f9b0709c which validator a sentry forwards transactions to; set the validator tcp:443 sources (own sentry vs all sentries) before L2-C.
- [ ] L2-C setup-firewall.sh: per-validator udp:49590,49594 ingress (tag validator-<i>), 1050 deny from 10.128.0.0/9, devnet-sentry-allow-consensus from 0.0.0.0/0, egress allow to validators+sentries, 443 to own sentry, web + LB health check retargeted to sentries.
- [ ] L2-C devnet-firewall.sh: --enable --p2p-from <per-node list> on validators, --p2p-anywhere on sentries; drop the `--port … on` pass; assert sources via --json --status.
- [ ] L2-D --stage-joiner node5 (VPC + ufw on validators 1-4 and node 5, staged state recorded in config.sh) and the join runbook (mint, stake, sync, activate, N..N+3 checks).
- [ ] L2-E tn-node-deployment PR 13 devnet release channel (--release-tag <x>-devnet, GPG-signed SHA256SUMS/IMAGE_DIGEST, chain-config pins from signed sums); fallback = launch 1 laptop-signed release.
- [ ] L2-F dns.sh/obs/dashboards for 10 nodes; manual A records for sentry1..5; LB backends = sentries only; decide admin.nodeN access behind the 443 restriction.
- [ ] L2-G gate G2: rendered admission shapes for all 10 nodes match the admission matrix.
- [ ] L2-G gate G3: firewall dry-run output (VPC + ufw) matches the firewall matrix; lockout-safe one-node-at-a-time order; lockdown-firewall-gcp.sh never called.
- [ ] L2-G gate G4: secrets (5 sentry BLS keys + passphrases, no persisted network keys, PR 13 key dir public-only).
- [ ] Second teardown + deploy (10 node VMs + obs + txgen).
- [ ] Verify: validators admission_mode=2, sentries Open, node 5 Closed pre-join; txgen `nc -u` + deny-rule log hit on a validator's 49590, accepted on a sentry; `tn node record` via a sentry works.
- [ ] Verify: a tx sent to rpc.devnet lands via the sentry forward path (record hash, block, sentry, receiving validator, latency).
- [ ] Join rehearsal: node 5 CvvActive at N+3; record draws missed, admission_fallback excursion per validator, committee rotation including node 5, base fee stepping vs G0.
- [ ] Record results and lessons in the tasks/todo.md review section.

---

# Plan: devnet full reset on tn-node-deployment v2 + new image (2026-10-30)

Source plan: the approved "Devnet full reset on tn-node-deployment v2 (PR 11 + stacked PR 12),
new image (main + PR 1715)" plan (see transcript). No Claude attribution on any commit/PR.

## State deltas found at start (vs the plan text)
- tn-node-deployment: local `mainnet-hardening` tip 8175a88 is ONE unpushed commit ahead of
  origin (326a89d). PR 12 branch `devnet-docker-images` created from 8175a88; P0b pushes
  8175a88 to origin/mainnet-hardening first so the PR 12 diff is only PR 12.
- common: origin/main moved dee644f → 4a2925c (WG_NODE_SUDOERS guard in wg-node-bootstrap.sh
  only, default 1 = unchanged behaviour). Phase 2 branches from 4a2925c; byte-identical gate
  against 4a2925c (genesis.sh/create-instances.sh unchanged between the two).
- telcoin-network: PR 1715 head 3f9b0709 fast-forwards from origin/main 8aedf72e (confirmed).
- gcloud auth EXPIRED → P1 builds with `--load` now (default builder holds the 17 GB cache),
  registry push + digest resolution happen after the operator's `gcloud auth login`.
- Only the `default` (docker driver) buildx builder exists; do not create tn-builder (cold cache).

## Wave 1 (parallel, opus)
- [x] P0a ND code: devnet repos + `-devnet` grammar (final=1), --release-tag refused on devnet, _tn_guard_network in update-node/edit-config AND tn_docker_image_allowed fallback, no registry walk on devnet, UI parity; versions 2.0.1; only the 5 expected vector flips fail
- [x] P0c ND docs done (CHANGELOG, followup.md closed, README x2, OPERATOR, tasks/pr12-body.md); P0b must fill script versions + gate results + fix the detect_network wording for edit-config
- [x] P1 TN `devnet/v0.2.0-devnet` = 3f9b0709c (ff from main), pushed; amd64 image built --load in 8 min (image ID 0a3dfb28…), probes green; registry push + digest pending gcloud auth; `Build Features` is empty for faucet builds (probe by precompile strings); Reference block in tasks/checkpoint-reset-P1.md
- [x] P2 common `devnet/genesis-knobs` pushed @ ebffdcb (gate 10/10 identical when unset); PR NOT opened: gh PAT lacks repo access on deploy-networks-common → OPERATOR opens https://github.com/Telcoin-Association/deploy-networks-common/pull/new/devnet/genesis-knobs with tasks/pr-common-genesis-knobs.md
- [x] A1 config.sh: digest DOCKER_IMAGE + DOCKER_IMAGE_TAG, /opt scripts dir + REF + repo, root parameters.yaml, 4 genesis knobs, SAFE_EXTRA_OWNER, node5 placeholder + secret name; follow-ups: devnet-update*.sh TARGET_TAG parse, benchmark/config.sh inherits
- [x] A2 devnet-startup.sh: 5 steps, no useradd, fetch by `tn-scripts-ref` into /opt (full 40-hex sha or branch name only; short sha refused), die() before the marker, no install.sh; rehearsal a-g green
- [x] A3 devnet-lib.sh: setup-node.sh path, tn_iap_ssh_cmd_stdin, tn_secret_set (stdin), tn_node_meta_get, refresh by full-sha ref, empty-command guard; stub evidence green
- [x] B2 devnet-genesis-build.sh: step-0 banner asserts knobs; step-4 parameters.yaml checks (humantime+secs/nanos); step 6 devnet-genesis-safe-owner.py (idempotent, anvil: getOwners 7→8, 0xAee… first); follow-ups: benchmark profile inherits knobs+extra owner; __pycache__ at root to clean
- [x] B3 devnet-network-config.sh + .py (render/validate/merge; --yes install, --verify; PeerId derived in stdlib; PyYAML for parsing). Corrections: bootstrap_peers is a MAP keyed by BLS; hostname appended in FINALIZE (step 7 before 8 is right); rendered files in genesis/network-config/ (re-render after new keygen)
- [x] C1 devnet-deploy.sh order — 16 steps, network-config = 7, firewall 10 before obs 11, --yes to 15/16, PLACEHOLDER gate; stale step refs in contracts/txgen/teardown comments fixed by the orchestrator
- [x] C3 devnet-dashboards.sh: node runs its own ui/install-ui.sh (first install / --update), no tarball/chown, enable + :8080 probe; stub runs green
- [x] D2 devnet-basefee-check.sh + .py: formula transcribed from gas_accumulator.rs:557-568 + alloy-eips, fee(N) from WorkerConfigs.data (empty-close copies parent fee), epoch range via tn_getEpochInfo or nonce bisection; live --last 2 / --epoch 1020 / --watch verified; live finding: target already 1e6, txgen idle since ~1238764

## Wave 2
- [x] P0b PR 12 = tn-node-deployment PR #52 (base mainnet-hardening @ 8175a88 pushed; head 090d9e19735572ea2ea0086a00c8a9eba00580bc; 4 commits); gates: 59 files/3687 checks 0 failed, pytest 258, helper 494, bash 3.2 run, sidecars x5; gap noted: _tn_release_fetch/tn_source_checkout_tag pass -devnet tags (unreachable) → R4 decides
- [x] B1 devnet-keygen.sh: setup-node.sh --json --phase=keygen … --passphrase-stdin via tn_iap_ssh_cmd_stdin; export -n passphrase; per-run log; real parser accepts argv; 0 passphrase hits outside stdin
- [x] B4 devnet-finalize.sh: setup-node.sh --json --phase=finalize (no passphrase), root 0644 staging, readiness gate, 5 post-checks (stable 60 s + enabled + NRestarts 0; .node-meta NETWORK/digest; network-config Closed+committee_peers; log patterns; tn-start-docker + --pull=never --read-only + environ), selector exits 2; orchestrator added --external-*/--public-ip; follow-up: reset-network.sh/devnet-update.sh re-run finalize (v2 refuses)
- [x] C2 devnet-observability.sh: --json --enable-* --token-stdin via tn_iap_ssh_cmd_stdin, sudo env TN_SKIP_EPOCH_WAIT=1 (operator may set 0), sequential with before/after probes (telcoin + telcoin-alloy active, tn_nodeMode back to CvvActive ≤300 s), refused-restart detection stops the sweep; 0 token hits outside stdin
- [x] D1 devnet-stake-node5.sh + .py: preflight (chain id, owner, PoP simulated vs the live blsVerify precompile), Safe-exec mint (pre-approved sig), stake, sync gate, activate, watch; keys via pty keystore import (0 argv/env hits in 560 samples); anvil T1 green with a stubbed B151; seating = activationEpoch+2 (N+3)

## Wave 3 (reviews + rehearsal)
- [x] T1 anvil rehearsal done inside B2 (owners) and D1 (mint/stake/activate via the Safe)
- [x] R1 no blocking defects (anvil: patch bytes == addOwnerWithThreshold); LOW blank-line-in-map fixed (now refused), ADDR_RE \\Z, cast timeout 60 s; infos: bench profile inherits the extra owner, step 5 hard-codes SAFE_ADDR
- [x] F2 devnet-finalize.sh: gate + A3 fetch the file base64 and run raw checks + the validator (m02/m14 + 16 mutants refused); A4 scans only post-gate bytes (cksum-guarded) + journal after cursor; 59 scenarios green; I3 closed by the orchestrator (verify accepts any mode without g/o write)
- [x] F1 network-config.py: syntax + canonical checks (BOM/merge/anchor/tag refused; 16/16 mutants refused), atomic multi-node render, accurate merge message; rendered files byte-identical
- [x] R2 no High/Medium (serde_yaml-0.8 mirror parses all five; container uid reads 0640 via owner bit; 18 finalize flags accepted); lows L1 (BOM/merge-key pass-through), L2 (unanchored Closed grep), L3 (old log lines) + I1/I2/I3 → fix agents F1/F2
- [x] R3 keygen/obs/lib/stake-pty clean (strace + /proc sampler); FIXED: stake HUP/PIPE traps, genesis-build export -n, lib never exports + message, -T on stdin ssh; FOLLOW-UP (pre-existing): devnet-contracts.sh + tn-contracts scripts put the admin key on cast argv and in .env
- [ ] R4 PR 12 review (testnet/mainnet unchanged) → head sha = TN_NODE_SCRIPTS_REF
- [x] R5 PASS independently (32/32 cases; set -e/-u postures; odd values); low finding closed in devnet-deploy.sh gate: TN_NODE_SCRIPTS_REF must be a 40-hex sha

## Wave 4 (orchestrator)
- [~] config.sh: TN_NODE_SCRIPTS_REF pinned to d9446f72…f4eb; DIGEST + NODE5 address still placeholders (need gcloud auth)
- [x] gitlinks: common → 0af7698 (branch devnet/genesis-knobs), tn-node-deployment → 090d9e1 (detached) — staged at commit time
- [x] G1 common 0af7698: gated `--user $GENESIS_DOCKER_USER -e HOME=/tmp` (26/26 identical unset); FULL genesis build rehearsed on xerxes with v0.2.0-devnet: rc 0, WorkerConfigs(0) = 0x989680, owners 8, outputs drtnarg-owned; without the knob rc 1 (reproduces the HIGH)
- [x] DOC README.md + INSTRUCTIONS.md rewritten for the v2 model (IAP default, 16 steps, knobs, closed admission, day-two tools, not-yet-v2 list)
- [x] R6 C1-C6/C8 PASS; HIGH: genesis build docker runs as uid 1101 → cannot write the workspace on xerxes → G1 (gated --user knob in common/genesis.sh + GENESIS_DOCKER_USER in config.sh + full build rehearsal); lows fixed by the orchestrator (runbook ×4, config/deploy comments, step numbers, startup keeps checkout on reboot, node-5 funding check); C7 README/INSTRUCTIONS drift → DOC agent
- [x] committed per track on main (8aa445b..d895f50, 11 commits, no attribution; NOT pushed); genesis/network-config/ left untracked until step 7 re-renders

## Phase 4 (operator-present) — see the plan; blocked on `gcloud auth login`
- [ ] 0 gcloud auth login / project / configure-docker; Secret Manager check
- [ ] 1 push image (`--push`, cache hit) → digest → config.sh pin; probe by digest
- [x] 2 tn-contracts bundle fetched (prereq d95fea88 from origin) + worktree ../tn-contracts-devnet-relaunch @ 2005b45 (done early; local-only)
- [ ] 3 node 5 key → Secret Manager + config.sh + testnet_accounts.yaml
- [ ] 4 DESTRUCTIVE devnet-teardown.sh --yes
- [ ] 5 devnet-deploy.sh --yes
- [ ] 6 devnet-stake-node5.sh --yes; watch two boundaries
- [ ] 7 todo.md review, lessons, memory, commits

## Phase 5 verification — see the plan's list (numbers, not adjectives)
