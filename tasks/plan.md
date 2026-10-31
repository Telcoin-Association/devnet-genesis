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
- [~] config.sh: TN_NODE_SCRIPTS_REF pinned to 090d9e19…80bc; DIGEST + NODE5 address still placeholders (need gcloud auth)
- [x] gitlinks: common → 0af7698 (branch devnet/genesis-knobs), tn-node-deployment → 090d9e1 (detached) — staged at commit time
- [x] G1 common 0af7698: gated `--user $GENESIS_DOCKER_USER -e HOME=/tmp` (26/26 identical unset); FULL genesis build rehearsed on xerxes with v0.2.0-devnet: rc 0, WorkerConfigs(0) = 0x989680, owners 8, outputs drtnarg-owned; without the knob rc 1 (reproduces the HIGH)
- [x] DOC README.md + INSTRUCTIONS.md rewritten for the v2 model (IAP default, 16 steps, knobs, closed admission, day-two tools, not-yet-v2 list)
- [x] R6 C1-C6/C8 PASS; HIGH: genesis build docker runs as uid 1101 → cannot write the workspace on xerxes → G1 (gated --user knob in common/genesis.sh + GENESIS_DOCKER_USER in config.sh + full build rehearsal); lows fixed by the orchestrator (runbook ×4, config/deploy comments, step numbers, startup keeps checkout on reboot, node-5 funding check); C7 README/INSTRUCTIONS drift → DOC agent
- [ ] commit per track (DG), no attribution

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
