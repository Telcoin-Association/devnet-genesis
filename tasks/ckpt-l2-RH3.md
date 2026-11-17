status: done
updated: 2026-11-17T20:53Z

# RH3 checkpoint (local rehearsal of the launch-2 genesis + admission scripts)
Scratch S=/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/RH3 (kept after the run).
- CONFIG_FILE wrapper: $S/config-rh3.sh (sources dg-l2/config.sh; REPO_ROOT=GENESIS_WORKSPACE=$S/ws, RELEASES_DIR=$S/releases,
  BASE_DOMAIN=l2rh3.invalid + RPC_HOSTNAME/RPC_URL/GATEWAY_REDIRECT_URL/CERT_DOMAINS, EPOCH_DURATION_SECS=120,
  TN_NODE_SCRIPTS_REF=40 hex, TN_BLS_PASSPHRASE_FILE=$S/secret/pass).
- $S/ws: shadow repo root (symlinks common -> dg-l2/common, devnet-genesis-safe-owner.py -> dg-l2; copy of testnet_accounts.yaml),
  genesis/validators/node1-4.yaml, genesis/observers/node5.yaml node6.yaml.
- $S/data/nodeN: datadirs with node-keys (keytool generate validator for all six, as setup-node.sh:2300).
- $S/bin: setup.sh (step 1, idempotent), render.sh (TND renderer), start.sh NAME IP MAP, rpc.sh, status.sh, snap.py.
- network l2rh3-net 172.30.103.0/24, nodeN = .1N (node1 .11 ... node6 .16).
- git baseline of dg-l2: $S/git/before.txt (+ before-ignored.txt).
Run a driver: CONFIG_FILE=$S/config-rh3.sh bash /home/drtnarg/coding/telcoin/dg-l2/<script>

## Completed sections
- step 1 KEYS: done (six keys, node-info placed; rpc http on node1-5, none on node6)
- step 2 GENESIS: done. devnet-genesis-build.sh rc=0, steps 5+6 applied (log $S/logs/genesis-build.log). Safe 0x..07a0 = SafeProxy
  (171 B, slot0 = SafeL2 v1.4.1 singleton 0x29fcb43b…c762); raw (ws-raw/, rebuilt by $S/bin/rawbuild.sh, identical but timestamp)
  slot3 7->8, slot4 3->1, owners[SENTINEL] 0x2358…->0xaee2…, new owners[0xaee2…]=0x2358…; walk 8 owners. $S/bin/safe.py prints it.
- step 3 RELEASE: done. prepare rc=0 (IMAGE_DIGEST, GATEWAY_IMAGE_DIGEST + 3 configs in SHA256SUMS, hashes re-checked), verify rc=3 RELEASE_SIG_PENDING.
  NB: dg-l2 git status moved during my run by ANOTHER unit (BT: 3 benchmark/tests/*.py, mtime 20:47 UTC); rebaselined to $S/git/before-2*.txt.
- step 4 MAPS: done ($S/bin/step4.sh). 11 maps, plain keys; six network-config via TND renderer; validate --native 6x ok; negative rc=1 "missing node2".
- step 5 START: done ($S/bin/startall.sh 20:49:07-20:49:28 UTC). 4x CvvActive, node5/node6 Observer, head 2 on all six at 20:52:10;
  epoch 1 closed 20:51:11.5 (block 2 hash 0x8570da57… on node1/node6/node5); node5's epoch-0 cert came from node6; snapshots as briefed;
  live Safe via node6 eth_call: threshold 1, 8 owners (0xAee2… first), VERSION 1.4.1.
- step 6 A4 PATTERNS: done, all 0 on six containers at 20:52:20 (container logs saved to $S/logs/nodeN.log at cleanup).
- step 7 CLEAN-UP: done. containers + l2rh3-net removed (empty listings), passphrase file deleted, git unchanged since rebaseline.
- report: tasks/l2/rh3-report.md written.
NB for a later unit: the keys in $S/data are encrypted with the deleted passphrase. To run nodes again:
  rm -rf $S/data $S/ws/genesis; bash $S/bin/setup.sh; CONFIG_FILE=$S/config-rh3.sh bash dg-l2/devnet-genesis-build.sh.
