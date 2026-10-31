# Runbook: devnet full reset on tn-node-deployment v2 + v0.2.0-devnet (2026-10-30)

Operator-present steps. Everything before step 0 is done in the working tree (commits per
track are the orchestrator's last action; see tasks/plan.md). Nothing below has been run.
Steps marked DESTRUCTIVE delete the fleet.

## 0. Session prerequisites (xerxes)
```
gcloud auth login
gcloud config set project tn-devnet
gcloud auth configure-docker us-docker.pkg.dev
gcloud auth print-access-token > /dev/null          # start the reauth window fresh (lesson 2026-10-07)
for s in obs-ingest-token devnet-contracts-admin-pk devnet-admin-dashboard-hash; do
  gcloud secrets describe "$s" --project=tn-devnet --format='value(name)'; done
```
Open the two PRs the token could not: tn-node-deployment PR #52 is open; deploy-networks-common
needs a manual PR for branch `devnet/genesis-knobs` (ebffdcb):
https://github.com/Telcoin-Association/deploy-networks-common/pull/new/devnet/genesis-knobs
with the text in tasks/pr-common-genesis-knobs.md. Merging either PR is NOT required for the
reset (the fleet pins commit shas); after merge, move `TN_NODE_SCRIPTS_REF` and the `common`
gitlink to the merge commits.

## 1. Push the image and pin the digest
The image is built and loaded locally (image ID 0a3dfb28…, branch devnet/v0.2.0-devnet @
3f9b0709c, pushed to GitHub). The registry push is a cache hit:
```
cd /home/drtnarg/coding/telcoin/telcoin-network && git rev-parse HEAD   # 3f9b0709cd52bfbd384221be5c4932566c9be45e
docker buildx build -f etc/Dockerfile --build-arg CARGO_FEATURES=faucet \
  --build-arg GIT_SHA=$(git rev-parse HEAD) --platform linux/amd64 \
  -t us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.2.0-devnet --push .
docker buildx imagetools inspect us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.2.0-devnet | head -3
```
Take the `Digest: sha256:<64hex>` line (the manifest digest the registry reports) and put it in
config.sh `DOCKER_IMAGE` in place of `PLACEHOLDER_DIGEST`. Probe BY DIGEST before anything else:
```
IMG="us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:<digest>"
docker run --rm "$IMG" telcoin --version          # Commit SHA: 3f9b0709cd52…; "Build Features:" is EMPTY for faucet builds (expected)
docker run --rm "$IMG" telcoin genesis --help | grep -E 'worker-fee-config|max-batch-delay-ms'
docker run --rm "$IMG" telcoin node --help | grep -E 'bootstrap-peers-file|credential'
docker run --rm --entrypoint sh "$IMG" -c "grep -c 'grantMintRole: expected 32 bytes' /usr/local/bin/telcoin"   # faucet compiled in: prints 1
```

## 2. tn-contracts worktree — DONE
`/home/drtnarg/coding/telcoin/tn-contracts-devnet-relaunch` @ 2005b45 (branch deploy/devnet-relaunch),
the default `TN_CONTRACTS_DIR` of devnet-contracts.sh.

## 3. Node 5 execution key (never logged, never on argv)
```
cd /home/drtnarg/coding/telcoin/devnet-genesis && source ./devnet-lib.sh
out="$(cast wallet new --json)"                      # keep this variable in the shell only
addr="$(printf '%s' "$out" | jq -r '.data[0].address')"        # cast 1.8: {data:[{address,private_key,public_key}],…}
printf '%s' "$out" | jq -r '.data[0].private_key' | tn_secret_set "$NODE5_VALIDATOR_PK_SECRET"
unset out
echo "$addr"
```
Then: config.sh `EXECUTION_ADDRESSES[4]` ← `$addr` (lowercase, replacing `PLACEHOLDER_NODE5_ADDRESS`);
testnet_accounts.yaml: add `$addr` with 1,000,100 TEL (same format as the other entries; the
stake is 1,000,000 TEL + gas). Confirm `grep -c PLACEHOLDER_ config.sh` = 0.

## 4. DESTRUCTIVE — teardown the old fleet
```
./devnet-teardown.sh            # dry run: read what it will delete
./devnet-teardown.sh --yes      # 5 VMs; static IPs, obs disk, LB, DNS, VPC rules, txgen-devnet, WG hub survive
```

## 5. Deploy (steps 1..16; ~60-90 min; step 4 pauses for DNS only if IPs changed — they are static)
```
./devnet-deploy.sh --yes 2>&1 | tee logs/deploy-$(date -u +%Y%m%dT%H%MZ).log
```
Order: reserve IPs → create VMs (metadata tn-scripts-ref = PR #52 head) → serial-console wait →
DNS pause (step 4 ALWAYS pauses for ENTER; the static IPs are unchanged, so just confirm) → keygen (passphrase on stdin) → genesis build (knobs + Safe owner patch; verifies
parameters.yaml) → network-config (Closed admission; re-renders genesis/network-config/) →
finalize (5 post-checks per node) → obs VM --wipe-data → host firewall → observability
(sequential, waits for CvvActive) → VPC rules → dns/LB → dashboards → contracts --yes → txgen --yes.
Resume after a failed step with `--from N`. devnet-deploy.sh has no per-node selector: if keygen
or finalize fails on ONE node, fix it and run that driver directly for that node
(`./devnet-keygen.sh node3`, `./devnet-finalize.sh node3`), then continue with `--from 6` /
`--from 9` (keygen refuses already-keyed nodes and finalize's gate refuses nodes that already
have a unit, so a whole-fleet `--only` re-run exits 1).

## 6. Stake node 5 (after it syncs; ~1 h to Active, 2-3 more epochs to see rotation)
```
./devnet-stake-node5.sh                 # dry run: preflight + every call it would make
./devnet-stake-node5.sh --yes           # mint via Safe → stake → sync gate → activate → watch
./devnet-stake-node5.sh --yes --from-step 6 --watch-epochs 3   # later: just the committee watch (--yes: a dry run exits before the watch)
```
Node 5 is first eligible for the committee of activationEpoch+2 (N+3 from the activate tx).

## 7. Verification (Phase 5 of the plan; numbers, not adjectives)
- Fleet: `./devnet-finalize.sh --verify`-style checks are built into finalize; re-run
  `./devnet-network-config.sh --verify` any time.
- Base fee: `./devnet-basefee-check.sh --last 2` after two boundaries (expect 7→8 wei at 0→1,
  then +12.5 %/epoch while txgen gas ≥ 20M/epoch; `--watch --count 1` to catch the next close).
- Closed admission: Prometheus on obs, `tn_network_admission_mode{network=~"primary|worker"}`
  = 2 on nodes 1-4 and `admission_fallback` = 0 once records resolve; around node 5's
  activation boundary nodes 2-4 show fallback = 4 until node 5's record arrives via node 1.
- Governance: `cast call 0x…07a0 "getOwners()(address[])" --rpc-url $RPC_URL` = 8, 0xAee… first;
  `getThreshold()` = 1; `cast call 0xFee0…FEe0 "getWorkerConfig(uint16)(uint8,uint64,uint184)" 0`
  = (0, 10000000, <fee>).
- Logs/metrics: Loki `count_over_time({chain="devnet", node=~"node.*"}[5m]) > 0` for all five;
  LB backends HEALTHY; `admin.nodeN` 401 without / 200 with basic auth; `eth_chainId` = 0x7e1d.
- Firewall: `./devnet-firewall.sh` (re-applies and asserts the rules via the node's --json
  --status) and `sudo ufw status` over IAP on all five; IAP SSH still works.
