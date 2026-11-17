# RH3: local rehearsal of the launch-2 genesis and admission scripts

Run 2026-11-17 20:46-20:53 UTC on local docker. Scripts under test: `dg-l2` at `46db2fc` (branch `l2/launch-2`), run
unedited. Image `us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:0aec3e7c…` (local, `--pull never` on every
harness `docker run`). Scratch dir (kept; containers and network removed):
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/RH3/` (`$S`).

## What must change before the real deploy
- **Nothing** in `devnet-genesis-build.sh`, `devnet-release-sign.sh`, `devnet-network-config.{sh,py}`: every step below
  passed on the files the drivers produced. The Safe post-processing (steps 5-6) still matches the new genesis: the Safe at
  `0x…07a0` is a SafeProxy over the canonical SafeL2 v1.4.1 singleton, and a proxy keeps the singleton's storage layout
  (owners slot 2, count slot 3, threshold slot 4) in its own alloc entry. The live chain answered threshold 1, eight owners.
- For the orchestrator, not a script change: the brief says to delete the passphrase file and also that a later unit reuses
  these keys. The BLS keys under `$S/data/nodeN/node-keys/` are encrypted with that deleted passphrase, so they cannot be
  started again. A later unit that needs running nodes re-runs `$S/bin/setup.sh` after `rm -rf $S/data $S/ws/genesis`
  (new keys, about 10 s) and the genesis build (about 1 s). The public files (node-info, committee, genesis, maps) still work
  as fixtures.

## Harness
- `CONFIG_FILE=$S/config-rh3.sh` sources `dg-l2/config.sh`, then sets `REPO_ROOT=GENESIS_WORKSPACE=$S/ws`
  (+ `GENESIS_FILE`, `PARAMETERS_FILE`), `RELEASES_DIR=$S/releases`, `BASE_DOMAIN=l2rh3.invalid` (+ `CERT_DOMAINS`,
  `RPC_HOSTNAME`, `RPC_URL`, `GATEWAY_REDIRECT_URL`), `EPOCH_DURATION_SECS=120`, `TN_NODE_SCRIPTS_REF=` 40 hex,
  `TN_BLS_PASSPHRASE_FILE=$S/secret/pass` (mode 600, 32 random bytes; stdin only, never argv/env).
- Why `REPO_ROOT` too: `common/genesis.sh` cd's to `REPO_ROOT` when sourced and makes `./logs/genesis-deployment/<ts>/` there,
  and the release manifest resolves `./genesis/committee.yaml` against it. So `$S/ws` is a shadow root with symlinks to
  the two paths read through `REPO_ROOT` (`common/`, `devnet-genesis-safe-owner.py`) and a copy of `testnet_accounts.yaml`.
  This also runs the devnet branch of the build (`GENESIS_WS == REPO_ROOT`). `RELEASE_KEYS_DIR` keeps config's dg-l2 path
  (read only by a signed `verify`, never reached here).
- Worktree check: `git -C dg-l2 status --porcelain` (and `--ignored`) captured before and compared after each script run.
- Containers as RH0 (`$S/bin/start.sh`, `rpc.sh`, `status.sh`, `snap.py`, `render.sh` copied from RH0, names `l2rh3-`),
  network `l2rh3-net` 172.30.103.0/24, nodeN = .1N. Same deviations as RH0: bridge + fixed IP, invoking uid, passphrase
  redirected to stdin inside the container.

## Step 1: KEYS. Verdict: done
`$S/bin/setup.sh`: `telcoin keytool generate validator --datadir … --address ${EXECUTION_ADDRESSES[i]}
--external-primary-addr /ip4/<ip>/udp/9000/quic-v1 --external-worker-addrs /ip4/<ip>/udp/9001/quic-v1
[--rpc-http https://nodeN.l2rh3.invalid/] --bls-passphrase-source stdin`. `generate validator` for all six roles, as
`setup-node.sh:2300` does (RH0 used `generate observer` for the RPC node). Placement via devnet-lib's `tn_role_dir`:
`ws/genesis/validators/node1-4.yaml`, `ws/genesis/observers/node5.yaml node6.yaml`. node-info: node1-5 `workers[0].rpc:
{http: "https://nodeN.l2rh3.invalid/", ws: ~}`, node6 `rpc: ~`. node6's `execution_address` is `0x…07a0` (= the Safe;
that is what `EXECUTION_ADDRESSES[5]` holds).

## Step 2: GENESIS. Verdict: finishes, rc 0, both Safe overrides applied and correct
Output (`$S/logs/genesis-build.log`): step 0 `node 5 0xd0154a80… is funded`; step 1 `expected validators: 4 | found
node-info files: 4` (seven-entry fleet, count by role); step 2 `accounts file already present at repo root`; step 3 ok;
step 4 `max_header_delay 1s, min_header_delay 350ms, max_batch_delay 250ms, basefee_address 0x…07a0,
allow_private_forward_targets false` all ✓. Steps 5 and 6, verbatim:
```
>>> step 5: devnet override — set Safe 0x00000000000000000000000000000000000007a0 threshold to 1 signer
    ✓ governance Safe threshold set to 1 signer (slot 0x..04 = ...0001)
>>> step 6: devnet override — add 0xAee2797478Cb5EfaF1869A2e33e369421EBf520f as an owner of Safe 0x…07a0
    owners[SENTINEL] (0xe90b7bce…c2e0): 0x2358cf87… -> 0xaee27974…
    inserted owners[0xaee27974…] (0xf6042463…ef22) = 0x2358cf87… (line 46)
    ownerCount (slot 0x..03): 7 -> 8
    owner list (8): 0xaee2… -> 0x2358… -> 0x389c… -> 0xde53… -> 0xf5b3… -> 0xdce4… -> 0xa21b… -> 0x5b9e…
```
Docker argv (logged by a `docker` shell function around the same `tn_genesis_build_committee`, `$S/bin/rawbuild.sh`):
`run -i --platform linux/amd64 -v ./:/code --workdir /code --user 1000:1000 -e HOME=/tmp <image> /usr/local/bin/telcoin
genesis --datadir ./ --chain-id 32285 --bls-passphrase-source stdin --accounts /code/testnet_accounts.yaml
--epoch-duration-in-secs 120 --min-header-delay-ms 350 --max-header-delay-ms 1000 --max-batch-delay-ms 250
--worker-fee-config 0:0:10000000`.
Before/after: the unpatched genesis was rebuilt in `$S/ws-raw` by `rawbuild.sh` (same lib and function, steps 5-6 not run).
It equals the shipped file except `timestamp` and the four Safe lines, and committee.yaml / parameters.yaml are identical.
The Safe's alloc entry (`$S/bin/safe.py`): fields `nonce, balance, code, storage`; code 171 bytes starting
`608060405273ff…600054167fa619486e` (SafeProxy, `masterCopy()`); slot 0 = `0x29fcb43b46531bca003ddc8fcb67ffe91900c762`
(SafeL2 v1.4.1, its own alloc entry with 24,421 bytes of code).
| storage key | raw | patched |
|---|---|---|
| slot 0x..00 (singleton) | 0x29fcb43b…c762 | same |
| slot 0x..03 (ownerCount) | 0x7 | **0x8** |
| slot 0x..04 (threshold) | 0x3 | **0x1** |
| owners[SENTINEL] `0xe90b7b…c2e0` | 0x2358cf87… | **0xaee27974…** |
| owners[0xaee2…] `0xf60424…ef22` | absent | **0x2358cf87…** (new) |
| 6 other owners[…] links, owners[last]=0x1, modules[SENTINEL]=0x1 | unchanged | unchanged |
| fallback handler slot `0x6c9a6c…18d5` | 0xfd0732dc…ec99 (CompatibilityFallbackHandler 1.4.1) | unchanged |
The list walk before writing found 7 owners = slot 3; after, 8 = slot 3. Worktree unchanged (porcelain and `--ignored`).

## Step 3: RELEASE MANIFEST. Verdict: as specified
`devnet-release-sign.sh prepare` rc 0 wrote `$S/releases/v0.3.0-devnet/{IMAGE_DIGEST, GATEWAY_IMAGE_DIGEST, SHA256SUMS}`;
`IMAGE_DIGEST` = config's `DOCKER_IMAGE`, `GATEWAY_IMAGE_DIGEST` = config's `GATEWAY_IMAGE`; `SHA256SUMS` lists IMAGE_DIGEST,
GATEWAY_IMAGE_DIGEST, genesis.yaml (b854fdc2…), committee.yaml (019cbc0b…), parameters.yaml (ef669af2…), and each hash
matches `sha256sum` of the file. `verify` rc **3**, first line `RELEASE_SIG_PENDING`, then the signing instructions
(printed, no ssh run). No signature created.

## Step 4: ADMISSION MAPS. Verdict: as specified
- `devnet-network-config.sh` (no flag) rc 0: `wrote 11 file(s) under $S/ws/genesis/admission-maps`; node1-5 `--admission
  closed maps: bootstrap-peers.yaml trusted-nodes.yaml`, node6 `--admission open maps: bootstrap-peers.yaml`. Every map:
  top-level lines = plain `<base58>:` lines (4 per bootstrap map, 1 per trusted map), zero `?` lines. Trusted map = node6.
- network-config via TND's `tn_network_config_render <datadir> <tn_admission_mode> <N.trusted-nodes.yaml|none>
  <N.bootstrap-peers.yaml>` (the arguments `setup-node.sh` `setup_admission_config` derives): rc 0 for all six; node1-5
  `admission Closed, trusted_nodes 1, committee_peers 4`; node6 `admission Open, committee_peers 4`, no trusted_nodes.
- `python3 devnet-network-config.py validate --native --committee <ws>/genesis/committee.yaml --genesis-dir <ws>/genesis
  --nodes node1=validator,…,node5=observer,node6=rpc --hub node1 --node N <file>` (finalize's `NC_CTX`): six
  `ok … is nodeN's native network-config` lines, rc 0 each.
- Negative: node1's file without node2's `committee_peers` entry: `FAIL … committee_peers: missing node2 zhXDb6uYzYHz...`, rc 1.

## Step 5: START. Verdict: all checks met within three minutes
Started node1-4 at 20:49:07-08, node6 at 20:49:18, node5 at 20:49:28 (`$S/bin/startall.sh`; `--bootstrap-peers` = text of
`nodeN.bootstrap-peers.yaml`; genesis, committee, parameters copied into each datadir).
- 20:49:54: node1-4 `CvvActive`, node6 and node5 `Observer`, head 1 everywhere (epoch 0 closed at once: genesis time was
  20:46).
- Snapshots at 20:50:02: node1 `Closed/Closed fallback=None 4/3/3`, entry `node6: slots=trusted admitted=True
  source=record`, node5 absent; node6 `Open/Open fallback=None 4/3/4`, node1-4 admitted; node5 `Closed/Closed fallback=None
  4/3/0` (no committee connection), node6 trusted, admitted.
- node5 through node6: its epoch-0 cert `retrieved … from a peer peer=yGjNGLx7…` (node6's BLS key) 1.5 s after start;
  `/health/network` at 20:52: primary and worker `established_peers: 1` (it showed 4 on the primary at 20:50; those were
  passing handshakes, as RH0 saw).
- Epoch boundary: epoch 1 closed at 20:51:11.5; block 2 hash `0x8570da57…` executed on node1 (11.53), node6 (11.53),
  node5 (11.84). At 20:52:10 head 2 on all six, modes unchanged; node1's snapshot then `tracked_epoch=2 Closed/Closed`.
- Live Safe through node6 (`eth_call` over the node's loopback via `docker exec`, so launch args stay unchanged; calldata from
  `cast sig`, decoded with `cast abi-decode`): `getThreshold()` = **1** (config: 1); `getOwners()` = 8, **0xAee27974…
  (`SAFE_EXTRA_OWNER`) first**, then the seven genesis owners; `VERSION()` = "1.4.1".

## Step 6: A4 log patterns. Verdict: all 0
At 20:52:20 (`docker logs`, 1,905-5,959 lines a node), node1..node6: `bad yaml data` 0, `committee_peers:` 0,
`committee_peers: missing validator` 0 (native mode's extra pattern), `trusted_nodes[` 0, `bootstrap_peers[` 0,
`panicked` 0. Logs kept in `$S/logs/nodeN.log`.

## Step 7: CLEAN-UP. Verdict: done
`docker rm -f l2rh3-node1..6`, `docker network rm l2rh3-net`; then `docker ps -a --filter name=l2rh3-` → `[]`,
`docker network ls --filter name=l2rh3-` → `[]`. `$S/secret/pass` removed (0 files left).
git: start `?? .claude/`, `?? tasks/l2-shim/`. At 20:47 UTC, while step 3 ran, three files changed:
` M benchmark/tests/test_node_{deploy,image,shapes}.py` (mtimes 20:47:13-35). They are the A-8 "unit BT" files, and no script
I ran references `benchmark/tests`. I rebaselined then. From the rebaseline to the end, porcelain and `--ignored` are unchanged.
End state: the three ` M benchmark/tests/…`, `?? .claude/`, `?? tasks/l2-shim/`.

## Observations (not blockers)
- `genesis.yaml` is mode 0600 locally after step 5 (`mktemp` + `mv`); harmless: finalize installs it `root 0644`
  (`devnet-finalize.sh:1359`).
- The RPC node logs about 200 `consensus output sync exchange failed; trying next peer` warnings in 3 min (node5: 47) on a
  healthy chain. An operator reading node6's log would see them.
- Validators log 2 `failed to request epoch pack for epoch 0 … no peer served` errors at start (all four), node4 one
  `failed to get vote for header`; benign here.

## Not verified
- `--network=host`, the image user, systemd credentials, the real `setup-node.sh` install path (the harness calls the TND
  renderer directly, as RH0). Node 5 after staking. Multi-worker nodes.
