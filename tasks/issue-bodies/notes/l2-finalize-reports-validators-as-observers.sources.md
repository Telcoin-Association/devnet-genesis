# Sources: l2-finalize-reports-validators-as-observers

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). DG = devnet-genesis.

| Item in the draft | Source | Status |
|---|---|---|
| Claim: `"node_type":"observer"` and the full-node message on every host, right after `Status: Active` | `tasks/challenges-l2.md` row 51; report section 2.8 | checked against log and code below |
| `>>> Checking validator on-chain status...` | DG `tasks/l2/w3/d3a/s10-canary-node1.log:81` (grep) | checked |
| `[OK]  Status: Active (participating in consensus)` | same log `:86` | checked |
| `json: {"event":"done","ok":true,"phase":"finalize","node_type":"observer","service":"telcoin","rpc_port":"8545",...` | same log `:100` (`cut -c1-330`) | checked (read up to `host_baseline`) |
| Message text `"${SERVICE_NAME} finalized and started -- following consensus as a full node; staking to validate is optional (see docs)"` | `git -C TND show M:setup-node.sh \| sed -n '3575,3582p'`; P line 3581 by `git grep` | checked at M; line and `node_type` at P by grep, message tail at P not re-read |
| Six hosts, "(5 of 5, validators included)" | DG `tasks/l2/w3/d3a/as-run.md:9` and `:7` (canary on validator-1) | checked |
| `Status: Active` on other validators | DG `tasks/l2/w3/d3a/s10-only10.log:100`, `:190` (grep) | checked |
| Times 00:42-00:56 UTC on 2026-11-18 | as-run `:7` (00:42Z-00:47Z), `:9` (00:45Z-00:56Z, deploy log `20261118_004541`) | checked |
| `setup-node.sh:3392` keygen event | `git grep -n node_type` at M and P | checked (both refs) |
| `setup-node.sh:3231` "Your node is set up and will follow consensus as a full node." | `git grep -n -i "full node" origin/main -- '*.sh'` | checked at M only |
| `setup-node.sh:222-226` comment, quote | `git show M:setup-node.sh \| sed -n '222,232p'`; P line 225 by grep | checked at M; line 225 at P |
| `lib/common.sh:5529`, `:5631`, `:5663`; labels grepped by `check-node.sh`/`update-node.sh` | `git show M:lib/common.sh \| sed -n '5524,5532p;5626,5636p'`; grep at M and P for 5631, 5663 | checked (both refs for 5631/5663; 5529 at M) |
| `ui/server.py:3205` `/api/status/<node_type>` | `git grep -n node_type P -- ui/` | checked at P only |
| Row 51 cites `setup-node.sh` (finalize) | line 3581 | checked, matches |
