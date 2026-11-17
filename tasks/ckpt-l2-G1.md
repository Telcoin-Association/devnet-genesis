status: blocked: contract change request (bench tests pin bench ref/image to root config.sh), §8 implementation done
unit: G1
completed:
- step 1 (2026-11-17T19:40:51Z): before dump taken -> /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/G1/before.txt (242 lines, SOURCE_RC=0).
  Invocation adapted: $0=benchmark-deploy.sh (caller allowlist), BENCH_RUN_ID=r20991231-0000 (required; no results dir). Script: /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/G1/dump.sh

- step 2 (2026-11-17T19:46:09Z): config.sh edited (via /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/G1/edit_config.py); bash -n 0; markers on 3 lines (DOCKER_IMAGE, GATEWAY_IMAGE, TN_NODE_SCRIPTS_REF)
  LB_* readers (outside common/, tn-node-deployment/): devnet-teardown.sh:127 (script); docs: tasks/runbook-l1-2026-10-31.md:55, docs/mainnet-simulation-plan.md:130 (LB_BACKEND_ROLES, a doc example)

- step 3 (2026-11-17T19:47:46Z): devnet-lib.sh helpers added (block source /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/G1/lib_block.sh); helper check + negative checks pass
- step 4 (2026-11-17T19:47:46Z): benchmark/config.sh: one 11-line block after the root source (scripts ref, image pair, TN_ADMISSION_VIA=devnet, TN_GATEWAY_ENABLE=0, empty gateway arrays)
- step 5 (partial): after dump /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/G1/after.txt; diff /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/G1/bench-dump.diff = only new §8 vars + LB_->LEGACY_LB_ rename; next: grep proof, bench tests, gates
- step 5 (2026-11-17T19:52:11Z): grep proof: no benchmark/ file or bench-path root driver reads any new/renamed name (only the bench block itself). test_network_config.py 27 OK rc 0 (only *config* test file). Gates: bash -n 0 x3; shellcheck -x: config.sh 1 (SC2148, pre-existing) before=after, devnet-lib 0/0, bench 7/7 same kinds; portability rc 0 x3. Bench profile: tn_fleet_check rc 0 under set -u. Full bench suite running (extra), log scratch/G1/test-all.log
- step 6 (2026-11-17T19:52:11Z): create-instances 80-180 + reserve-static-ips read; findings drafted in hand-back

## bench before/after dump diff (verbatim, diff before after)
```
0a1,2
> declare -x ADMISSION_HOST_DIR="/etc/telcoin/devnet-admission"
> declare -x ADMISSION_MAPS_DIR="genesis/admission-maps"
133a136,143
> declare -ax GATEWAY_FOR=()
> declare -x GATEWAY_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:PLACEHOLDER_GATEWAY_IMAGE_DIGEST"
> declare -x GATEWAY_IMAGE_TAG="us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway:v0.3.0-devnet"
> declare -x GATEWAY_LISTEN_PORT="8655"
> declare -x GATEWAY_METRICS_PORT="9655"
> declare -ax GATEWAY_MODES=()
> declare -x GATEWAY_PROBE_PORT="8656"
> declare -x GATEWAY_REDIRECT_URL="https://rpc.devnet.telcoin.network"
150,159c160,169
< declare -x LB_BACKEND_SERVICE="devnet-rpc-backend"
< declare -x LB_FIREWALL_RULE="devnet-lb-allow-health-check"
< declare -x LB_FORWARDING_RULE="devnet-rpc-fr"
< declare -x LB_GLOBAL_IP_NAME="devnet-rpc-ip"
< declare -x LB_HEALTH_CHECK_NAME="devnet-rpc-hc"
< declare -x LB_HOSTNAME="rpc.devnet.telcoin.network"
< declare -x LB_HTTPS_PROXY="devnet-rpc-https-proxy"
< declare -x LB_NAME_PREFIX="devnet-rpc"
< declare -x LB_SSL_CERT="devnet-rpc-cert"
< declare -x LB_URL_MAP="devnet-rpc-urlmap"
---
> declare -x LEGACY_LB_BACKEND_SERVICE="devnet-rpc-backend"
> declare -x LEGACY_LB_FIREWALL_RULE="devnet-lb-allow-health-check"
> declare -x LEGACY_LB_FORWARDING_RULE="devnet-rpc-fr"
> declare -x LEGACY_LB_GLOBAL_IP_NAME="devnet-rpc-ip"
> declare -x LEGACY_LB_HEALTH_CHECK_NAME="devnet-rpc-hc"
> declare -x LEGACY_LB_HOSTNAME="rpc.devnet.telcoin.network"
> declare -x LEGACY_LB_HTTPS_PROXY="devnet-rpc-https-proxy"
> declare -x LEGACY_LB_NAME_PREFIX="devnet-rpc"
> declare -x LEGACY_LB_SSL_CERT="devnet-rpc-cert"
> declare -x LEGACY_LB_URL_MAP="devnet-rpc-urlmap"
178a189
> declare -x NODE_RPC_PORT="8545"
198a210
> declare -x P2P_COMMITTEE_WAIT_SECS="300"
207a220
> declare -x RPC_HOSTNAME="rpc.devnet.telcoin.network"
220a234
> declare -x TN_ADMISSION_VIA="devnet"
222a237
> declare -x TN_GATEWAY_ENABLE="0"
238a254,256
> declare -x VPC_TAG_GW_UPSTREAM="devnet-gw-upstream"
> declare -x VPC_TAG_P2P="devnet-p2p"
> declare -x VPC_TAG_WEB="devnet-web"
```

- full bench suite (2026-11-17T19:58:39Z): python3 -m unittest discover -s benchmark/tests -p 'test_*.py' from DG: see result line in hand-back
full suite: timed out at 580 s with E/F marks; comparing per module against a HEAD copy (scratch base/)

- step 5 result (2026-11-17T20:25:32Z): per-module bench suite, change tree vs HEAD copy (scratch base/, git archive HEAD + symlinked submodules), each module alone, 300 s cap:
  regressions (base pass -> new fail): test_host_probe (32 E), test_node_image (108 E; base hit the 300 s cap), test_node_deploy (13 F), test_local_ssd_deploy (23 F), test_node_shapes (5 F).
  One cause: tests take the bench's TN_NODE_SCRIPTS_REF / DOCKER_IMAGE from ROOT config.sh (test_node_image.py:502-504 regex; base sandboxes = git show ae43747:benchmark/config.sh + current root config.sh in test_node_deploy.py:34-36, test_node_shapes.py:27/105-137, test_local_ssd_deploy.py). Not fixable inside the 3 files without breaking §8 -> CCR.
  test_keygen SignalTests fails identically on HEAD (pre-existing). All other 38 modules pass in both.
