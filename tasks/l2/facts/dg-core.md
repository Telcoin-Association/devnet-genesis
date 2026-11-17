# F-DG1 fact sheet: devnet-genesis core drivers (main, read-only)
status: done
completed: 1, 2, 3, 4, 5, 6, 7
Paths relative to devnet-genesis/. `[I]` = inferred.

## 1. config.sh (348 lines)
- `REPO_ROOT` (config.sh:9). Image: `DOCKER_IMAGE_TAG="…/tn-public/adiri:v0.2.0-devnet"` (:41, informational); `DOCKER_IMAGE="us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:5257e768…4a610"`
  (:42; v2 setup-node.sh on devnet accepts only `<repo>@sha256:<64 hex>`, :33-36); deploy refuses while a PLACEHOLDER marker remains (:37-40).
- Release: `RELEASE_TAG="v0.2.0-devnet"` (:57; empty disables both hooks, :54), `RELEASE_KEYS_DIR="${REPO_ROOT}/tn-node-deployment/lib/release-keys"` (:58),
  `RELEASE_SIGNER_FPR` (:59, informational). Deploy step 6 `prepare`; finalize `verify`, `RELEASE_SIG_PENDING` exit 3 (:50-53).
- Fleet arrays, in order (all `export`ed; bash exports arrays as plain vars only [I]):
  - `INSTANCE_NAMES=("validator-1-devnet" "validator-2-devnet" "validator-3-devnet" "validator-4-devnet" "observer-5-devnet")` (:85)
  - `NODE_ROLES=("validator" "validator" "validator" "validator" "observer")` (:86) — "single source of truth every
    script branches on"; first four = genesis committee (:79-84). Note role string for node 5 is `observer`, not `rpc`.
  - `ZONES=("us-west2-a" "us-south1-a" "northamerica-northeast1-b" "europe-west4-a" "europe-west2-b")` (:87)
  - `NODE_NAMES=("node1" "node2" "node3" "node4" "node5")` (:89) → `node{N}.${BASE_DOMAIN}` (:88)
  - `EXECUTION_ADDRESSES=(0x3518…d024 0x7489…b5d3 0x0033…5ccb 0xefaa…7b17 0xd015…a7b8)` (:95); [4] = node 5 key, pk in `NODE5_VALIDATOR_PK_SECRET="devnet-node5-validator-pk"` (:96).
  - `STATIC_IP_NAMES=("validator-1-devnet-ip" … "validator-4-devnet-ip" "observer-5-devnet-ip")` (:102), "PARALLEL to INSTANCE_NAMES" (:97); `USE_STATIC_IPS=1` (:101).
  - Region comment only: 1 LA, 2 Dallas, 3 Montreal, 4 Netherlands, 5 London (:73-77). No REGIONS, EXTERNAL_IPS, INTERNAL_IPS arrays (:68-71).
  - Parallel (must stay equal length): INSTANCE_NAMES, NODE_ROLES, ZONES, NODE_NAMES, EXECUTION_ADDRESSES, STATIC_IP_NAMES
    (comment :97 states it only for STATIC_IP_NAMES; the rest [I] from same-index reads in the drivers, e.g. finalize:1135-1138).
- Project/GCP: `PROJECT_ID="tn-devnet"` (:103), `CLOUDSDK_CORE_PROJECT` (:107), `MACHINE_TYPE="e2-custom-4-8192"` (:108),
  `SERVICE_ACCOUNT="1095385745561-compute@developer.gserviceaccount.com"` (:112),
  `IMAGE=…/ubuntu-2404-lts-amd64` (:118), `STARTUP_SCRIPT_PATH="${REPO_ROOT}/devnet-startup.sh"` (:123).
  Network name: none exported; comment says classic VPC rules on the `default` network (:312-313).
- Ports: `DEFAULT_PRIMARY_UDP_PORT=49590` (:124), `DEFAULT_WORKER_UDP_PORT=49594` (:125),
  `DEFAULT_HEALTHCHECK_TCP_PORT=43174` (:126). No RPC/WS port variable in config.sh (8545/8546 appear only in a
  comment at devnet-finalize.sh:1257).
- Health/monitor: `HEALTHCHECK_MONITOR_SRC="104.155.184.201/32"` (:132), `GOOGLE_HC_RANGES="130.211.0.0/22,35.191.0.0/16,209.85.152.0/22,209.85.204.0/22"` (:138),
  `TN_KUMA_SRC="${HEALTHCHECK_MONITOR_SRC}"` (:329).
- DNS/TLS: `BASE_DOMAIN="devnet.telcoin.network"` (:142), `LETSENCRYPT_EMAIL` (:143), `CERT_DOMAINS=("${BASE_DOMAIN}")` (:146),
  `CONFIG_CADDY_SCRIPT="${REPO_ROOT}/common/config-caddy.sh"` (:150). Admin vhost `admin.<node>.${BASE_DOMAIN}` (:334).
- Genesis: `EPOCH_DURATION_SECS=3600` (:155), `CHAIN_ID=32285` (:157), `MIN_HEADER_DELAY_MS=350`, `MAX_HEADER_DELAY_MS=1000`,
  `MAX_BATCH_DELAY_MS=250` (:161-163), `WORKER_FEE_CONFIG="0:0:10000000"` (:169).
- Node model: `NODE_DEPLOY_MODE="tn-node-deployment"` (:179), `TN_INSTALL_METHOD="docker"` (:180), `SERVICE_USER="telcoin"` (:183),
  `TN_NODE_SCRIPTS_DIR="/opt/telcoin-node-scripts"` (:186, root-owned, detached at the ref),
  `TN_NODE_SCRIPTS_REF="d9446f720026fa5ce8b64fce9074e56b05b3f4eb"` (:188, must be full 40-hex, :39),
  `TN_NODE_DEPLOY_REPO="https://github.com/Telcoin-Association/tn-node-deployment.git"` (:191; devnet-startup.sh keeps
  its own copy of the URL, :189-190), `VALIDATOR_DATA_DIR`=`OBSERVER_DATA_DIR="/var/lib/telcoin"` (:192-193),
  `TN_CHAIN_SUBDIR="devnet"` (:194), `VALIDATOR_GENESIS_DIR`=`OBSERVER_GENESIS_DIR="/etc/telcoin/chain-configs/devnet"` (:197-198).
  Startup script checks out the ref from `tn-scripts-ref` metadata (:120-121).
- LB (global L7, `rpc.devnet.telcoin.network`): `LB_NAME_PREFIX="devnet-rpc"` (:202), `LB_HOSTNAME="rpc.devnet.telcoin.network"` (:203),
  `LB_HEALTH_CHECK_NAME="devnet-rpc-hc"` (:204), `LB_BACKEND_SERVICE="devnet-rpc-backend"` (:205), `LB_URL_MAP="devnet-rpc-urlmap"` (:206),
  `LB_SSL_CERT="devnet-rpc-cert"` (:207), `LB_HTTPS_PROXY="devnet-rpc-https-proxy"` (:208), `LB_FORWARDING_RULE="devnet-rpc-fr"` (:209),
  `LB_GLOBAL_IP_NAME="devnet-rpc-ip"` (:210), `LB_FIREWALL_RULE="devnet-lb-allow-health-check"` (:211). No instance-group,
  HTTP proxy or HTTP forwarding-rule variable in any in-scope file (grep); instance-group names are built elsewhere (not in scope).
- `RPC_URL="https://rpc.devnet.telcoin.network"` (:217), `SAFE_ADDR` (:219), `SAFE_EXTRA_OWNER` (:223), `STABLECOIN_MANAGER` (:227). `TN_USE_VPN=1` (:319), `WG_NODE_FIREWALL=0` (:325).
- Paths: `GENESISDIR="genesis/validators/"` (:231), `GENESIS_WORKSPACE="${REPO_ROOT}"` (:239, plain assignment so a profile can override), `GENESIS_DOCKER_USER`
  (:245-246), `GENESIS_FILE`, `PARAMETERS_FILE="${REPO_ROOT}/parameters.yaml"`, `COMMITTEE_FILE="./genesis/committee.yaml"` (:247-250).
- Obs: `OBS_INSTANCE_NAME="obs-devnet"` (:266), `OBS_HOSTNAME` (:270), `OBS_PUSH_URL`/`OBS_METRICS_PUSH_URL` (:285/:289), `TN_OBS_ENABLE_*` default 1 (:296-299).
  Admin UI: `TN_ADMIN_DASHBOARD` default 1, `TN_ADMIN_AUTH_USER`, `TN_ADMIN_HASH_SECRET` (:343-345); "one SHARED credential across all 5 nodes" (:337).
- No admission/allow-list/trusted-peer/bootstrap knob in config.sh (grep -i admission|trusted|bootstrap|allow: comments only).

## 2. devnet-lib.sh (448 lines)
Sources `${CONFIG_FILE:-${DEVNET_LIB_DIR}/config.sh}` (:28-30). `TN_SSH_TRANSPORT` default `iap`; `overlay` sources
`common/wgvpn/lib/wg-ssh-lib.sh` with `TN_USE_VPN` shim suppressed (:38-44). `TN_SSH_FLAGS=(--tunnel-through-iap
--ssh-flag="-o ConnectTimeout=20" --ssh-flag="-o StrictHostKeyChecking=accept-new")` (:48).
| function (line) | args | does |
|---|---|---|
| `_tn_require_cmd` (:54) | caller, cmd | rc 1 on empty remote command (would open login shell) |
| `tn_iap_fault_kind` (:87) | rc, stderr-file | prints `ok`/`reauth`/`transport`/`iap-refused`/`other` |
| `_tn_iap_retry` (:96) | label, stdin 0/1, gcloud args | retries only `transport` up to `TN_IAP_RETRIES` (2) every `TN_IAP_RETRY_SECS` (5); `reauth` never retried |
| `tn_iap_ssh` (:130) | inst, zone, cmd | `gcloud compute ssh … --command=cmd` (overlay: `tn_ssh`) |
| `tn_iap_ssh_stdin` (:143) | inst, zone | stdin script → `sudo bash -s` with `-T` |
| `tn_iap_ssh_cmd_stdin` (:167) | inst, zone, cmd | caller's stdin forwarded to cmd (secrets via `--passphrase-stdin`/`--token-stdin`) |
| `tn_iap_scp` (:182) | src, inst, zone, dest | `gcloud compute scp` over IAP (overlay: `tn_scp`) |
| `tn_node_ext_ip` (:197) / `tn_node_int_ip` (:201) | inst, zone | `instances describe` → `networkInterfaces[0].accessConfigs[0].natIP` / `.networkIP` |
| `tn_region_from_zone` (:207) | zone | strips last `-x` |
| `tn_secret` (:211) | name | `gcloud secrets versions access latest` |
| `tn_secret_set` (:224) | name; value on stdin | create (automatic replication) if absent, `versions add --data-file=-`; refuses a tty |
| `tn_require_bls_passphrase` (:248) | — | `$TN_BLS_PASSPHRASE` > `$TN_BLS_PASSPHRASE_FILE` > `.secrets/bls-passphrase`; `export -n` |
| `tn_node_role` (:262) | index | `${NODE_ROLES[$1]}`; comment says `validator|observer` (:261) |
| `tn_data_dir_for_role` / `tn_genesis_dir_for_role` / `tn_service_for_role` (:265-267) | role (ignored) | `VALIDATOR_DATA_DIR` / `VALIDATOR_GENESIS_DIR` / `telcoin` |
| `tn_setup_script_for_role` (:273) | role (ignored) | `${TN_NODE_SCRIPTS_DIR}/setup-node.sh` |
| `tn_node_meta_get` (:290) | inst, zone, KEY | reads `/etc/telcoin/.node-meta` via sudo grep; rc 0/1/2 (:284-287) |
| `wait_healthy` (:333) | inst, zone, svc | on-node `systemctl is-active` + `curl 127.0.0.1:${DEFAULT_HEALTHCHECK_TCP_PORT}`; `HEALTH_TIMEOUT_SECS` 120, `HEALTH_POLL_SECS` 5 |
| `tn_cmd_refresh_scripts` (:399) | — | builds `sudo git -C '<dir>' fetch --depth=1 origin '<ref>' && sudo git -C '<dir>' checkout --detach FETCH_HEAD && sudo grep -q TN_UPDATE_VERIFY_TIMEOUT '<dir>/update-node.sh'` (:408); rc 1 unless ref is 40 lowercase hex |
| `tn_cmd_update_check` / `_prepare` / `_apply <secs>` (:413/:420/:428) | | `update-node.sh --json --check` / `--prepare --ref '${DOCKER_IMAGE}'` / `sudo env TN_UPDATE_VERIFY_TIMEOUT=N … --apply --yes` |
| `tn_json_done_line`, `tn_json_check_line`, `tn_json_str`, `tn_json_true` (:439-448) | | jq-free parsers |
- No node-iteration helper and no hard-coded node count in devnet-lib.sh (grep). No retry helper other than `_tn_iap_retry`.
- Index-sensitive: only `tn_node_role` (:262). Role vocabulary documented as `validator|observer` (:261) [I: a new `rpc`/`gateway` role string is unknown to this comment, not to code].
- All per-role helpers ignore the role (:265-275), so a new role gets the same data dir/genesis dir/setup script [I].
- Secret-on-stdin model and on-node node-meta path are fixed (:15-18, :291).

## 3. benchmark/config.sh (870 lines; working tree has a local diff, 6+/3-, vs HEAD — values below are the working tree)
- Refuses interactive shells unless `BENCH_ALLOW_INTERACTIVE=1` (:41-47) and any caller not in the allowlist:
  `benchmark-deploy.sh|benchmark-firewall.sh|benchmark-blast.sh|benchmark-teardown.sh|benchmark-probe.sh|devnet-keygen.sh|devnet-genesis-build.sh|devnet-network-config.sh|devnet-finalize.sh|devnet-contracts.sh|create-instances.sh|genesis.sh|copy-committee.sh|params-apply.sh` (:48-57).
  devnet-deploy.sh is NOT on it. Selected via `CONFIG_FILE=benchmark/config.sh` (:15).
- Sources root config: `source "${BENCH_DIR}/../config.sh"` (:62), then overrides.
- Overrides: `RELEASE_TAG=""` (:67, gate OFF), `TN_PROFILE="benchmark"` (:69); fleet arrays rewritten as 11 entries
  (10 `validator` + `bench-observer-11` role `observer`): `INSTANCE_NAMES`, `NODE_ROLES`, `ZONES`, `NODE_NAMES` (`bench01`..`bench11`),
  `EXECUTION_ADDRESSES` (:98-103); `BENCH_ZONE_FALLBACKS` (:112); `USE_STATIC_IPS=0`, `STATIC_IP_NAMES=()` (:141-142);
  `CHAIN_ID=32286`, `EPOCH_DURATION_SECS=1200` (:146-147); `TN_USE_VPN=0`, `TN_SSH_TRANSPORT=iap` (:151-152);
  `WG_HUB_COORDS_FILE=/dev/null` (:156); `DOCKER_IMAGE="${BENCH_DOCKER_IMAGE:-${DOCKER_IMAGE}}"` (:161); `IMAGE` pinned
  `ubuntu-2404-noble-amd64-v20261105` (:167); `MACHINE_TYPE` default `c3-highcpu-8` (:171) and per-node `NODE_MACHINE_TYPES` (:192),
  `NODE_DISK_*` (:172-183), `NODE_DATADIR_LSSD` (:222); `INSTANCE_TAGS="bench-node"`, `INSTANCE_LABELS` (:251-252);
  `BASE_DOMAIN="bench.invalid"`, `CERT_DOMAINS` (:255-256); `HEALTHCHECK_MONITOR_SRC=""`, `TN_KUMA_SRC=""` (:257-258);
  `TN_OBS_ENABLE_*`, `TN_ADMIN_DASHBOARD` (:264-268); `GENESIS_WORKSPACE="${BENCH_DIR}"`, `GENESIS_FILE`, `COMMITTEE_FILE` (:305-307);
  `PARAMETERS_FILE` (:311); `TN_BLS_PASSPHRASE_FILE` (:360); `RPC_URL` (:365); `ZONES` replaced from `results/<run>/zones.env`
  `BENCH_ZONES_USED` with a length check against `INSTANCE_NAMES` (:554-561); `MACHINE_TYPE` + unsetting `INSTANCE_NAMES[i]` for
  `BENCH_CREATE_MACHINE_TYPE` (:865-868).
- Driver knobs (set only when unset): `FINALIZE_JOBS=4`, `KEYGEN_JOBS=4`, `NETCFG_JOBS=4`, `NETCFG_FAST=1`,
  `NETCFG_TRUST_OBSERVERS_EVERYWHERE=1`, `KEYGEN_REUSE_EXISTING=1`, `KEYGEN_RPC_ADVERTISE=internal-ip`, `KEYGEN_REPORT=1` (:585-592).
  `BENCH_ADMISSION_DENIED_MAX` = 0 when trust-everywhere, else empty (:597-601); gate is "deploy step 10" of the bench deploy (:593).
- Comment: deploy step 7 (bench) runs devnet-network-config.sh first so every bench node holds a "Closed-admission network-config" before any node starts (:35-37).
- Inherited unchanged from root (no assignment in the file, grep): `TN_NODE_SCRIPTS_REF`, `TN_NODE_SCRIPTS_DIR`, `TN_NODE_DEPLOY_REPO`,
  `PROJECT_ID`, `SERVICE_ACCOUNT`, `SERVICE_USER`, data/genesis dirs, `DEFAULT_*_PORT`s, all `LB_*`, `OBS_*`. `DOCKER_IMAGE` inherited
  unless `BENCH_DOCKER_IMAGE` is set (:159-161). No admission knob exists in root config.sh; the NETCFG_* knobs are consumed by the drivers.

## 4. devnet-deploy.sh (330 lines)
- Sources `devnet-lib.sh` (:59); `set -euo pipefail` (:56). `LAST_STEP=16` (:61); `BOOTSTRAP_TIMEOUT_SECS=600`, `BOOTSTRAP_POLL_SECS=15` (:62-63).
- Flags: `--yes` (`CONFIRM=1`), `--from <n>`/`--from=<n>`, `--only <n>`/`--only=<n>`; else `❌ unknown argument '…' (supported: --yes, --from <n>, --only <n>)` exit 1 (:69-79).
  `is_step` 1..`LAST_STEP` (:82-86). Each step is `step_N()`; runner `run_step` prints `## step N done` (:304-311), loops FROM..LAST_STEP (:313-321).
- Pre-gates (before the prompt, even with --yes): grep `PLACEHOLDER_` in `${CONFIG_FILE:-config.sh}` ignoring full-line comments → exit 1 (:276-281);
  `TN_NODE_SCRIPTS_REF` must be lowercase 40-hex → exit 1 (:286-292). Then `Type DEPLOY to continue: ` unless `--yes`; no tty + no --yes → exit 1 (:294-301).
- Step table (current; header :13-28, code :89-246):
  | # | title (echo text) | runs | prompts? |
  |---|---|---|---|
  | 1 | `reserve static IPs` | `common/reserve-static-ips.sh` (:89) | no |
  | 2 | `create instances` | `common/create-instances.sh` (:90) | no |
  | 3 | `wait for first-boot bootstrap on EVERY node (serial-console completion marker)` | loop over `INSTANCE_NAMES`, `gcloud compute instances get-serial-port-output`, marker `devnet-startup.sh complete` (:92-131) | no |
  | 4 | `MANUAL — create DNS A-records` | prints `NODE_NAMES[i].BASE_DOMAIN -> static IP of INSTANCE_NAMES[i]` for every index, `pause_for_operator` (:133-150) | yes (ENTER; no tty → exit 1, :250-256) |
  | 5 | `keygen` | `devnet-keygen.sh` (:152) | no |
  | 6 | `build genesis (+ release manifest)` | `devnet-genesis-build.sh`; if `RELEASE_TAG` set `devnet-release-sign.sh prepare` (rc 1 → hint `prepare --force`, resume `--from 7`) (:153-169) | no |
  | 7 | `per-node network-config (render + install BEFORE the first node start)` | `devnet-network-config.sh --yes` (:171-178) | no |
  | 8 | `finalize (stage + start)` | `devnet-finalize.sh` (:180) | no |
  | 9 | `obs VM (+ wipe data)` | `common/create-obs-instance.sh --wipe-data` (:181) | no |
  | 10 | `host firewall (UFW) — lockout-safe enable, then consensus rules` | `devnet-firewall.sh --enable` then `devnet-firewall.sh` (:183-200) | no |
  | 11 | `per-node observability` | `devnet-observability.sh` (:202-207) | no |
  | 12 | `GCP/VPC firewall rules` | `setup-firewall.sh` (:209) | no |
  | 13 | `DNS/Caddy reverse-proxy + load balancer` | `common/dns.sh`; `common/setup-load-balancer.sh` (:210-214) | no |
  | 14 | `admin dashboard (Node Manager UI) — install + expose read-only` | skip if `TN_ADMIN_DASHBOARD!=1`; `devnet-dashboards.sh`; `common/dns.sh` (:215-227) | no |
  | 15 | `app-contract stack (tn-contracts)` | `devnet-contracts.sh --yes` (:229-240) | no |
  | 16 | `transaction generator (txgen-devnet)` | `devnet-txgen.sh --yes` (:241-246) | no |
- Release-signature gate fires inside step 8 (finalize exits 3 `RELEASE_SIG_PENDING` before any node is touched; resume `--from 8`) (:38-42); prepare in step 6 (:156-160).
- Exit codes: failing step's rc via `set -e` (3 = signature pending) (:44-45); 1 for arg/gate/placeholder/abort.
- Logging: none of its own; stdout/stderr of sub-scripts pass through unfiltered (:45). No log file, no tee.
- Step 7 comment: renders "closed admission, committee_peers, and the trusted/bootstrap peers for node1/node5" (:173-174).
- Only direct node contact is step 3's serial-console read (:52-53). Steps 3 and 4 iterate `"${!INSTANCE_NAMES[@]}"` (:106, :146): a gateway VM must
  print the startup marker and gets a `node{N}` DNS line [I].

## 5. devnet-finalize.sh (1398 lines)
- CLI: `./devnet-finalize.sh [--stage-only | --start-all | --defer-start | --verify] [target ...]` (usage :224-235); at most one mode flag
  (:239-252); target = 0-based index, `INSTANCE_NAME` or `NODE_NAME` via `tn_select_indices` (:202-222); none = every index of `INSTANCE_NAMES`.
  Deploy step 8 calls it with NO mode (serial stage+finalize+start per node, devnet-deploy.sh:180). `--defer-start` already = stage all then one coordinated start (:97-98).
- Exit: 0 ok; 1 node/local failure (incl. failed signature verify); 2 bad target/option/knob, two modes, `FINALIZE_JOBS` reaching quorum; 3 `RELEASE_SIG_PENDING` (:144-153).
- Knobs: `FINALIZE_STABLE_SECS` 60, `FINALIZE_STABLE_POLL_SECS` 10, `FINALIZE_RO_RETRY_SECS` 5, `FINALIZE_START_LEAD_SECS` 60, `FINALIZE_START_LAUNCH_GAP_SECS` 1,
  `FINALIZE_START_TIMEOUT_SECS` 120, `FINALIZE_START_SPREAD_WARN_SECS` 10, `FINALIZE_JOBS` 1, `NETCFG_TRUST_OBSERVERS_EVERYWHERE` 0 (:160-197).
- Order of the run: parse/targets (:239-266) → quorum guard: counts `NODE_ROLES == "validator"`, `_q=2*_nval/3+1`, refuse `FINALIZE_JOBS>=_q` in stage-only/defer-start (:270-283)
  → local artifacts committee/genesis/`PARAMETERS_FILE` (:291-297) → `DOCKER_IMAGE` digest form check (:301-309) → release gate `devnet-release-sign.sh verify`
  (:311-343; rc 3 → exit 3 unless `TN_SKIP_RELEASE_SIG=1`, which only bypasses rc 3) → python3+PyYAML check (:352-356) → `NC_CTX` (:357-365) → phase A
  (`_run_nodes a _phase_a_node`, :1312) → coordinated start (:1315-1328) → phase B (`_run_nodes b _phase_b_node`, :1358) → summary (:1362-1398).
- Signature gate is LOCAL and runs before any gcloud/ssh (:102-111).
- tn-node-deployment on the host: finalize does NOT clone or fetch it. The readiness probe only checks `[ -f "$setup" ]` (`setup=1`) where setup =
  `${TN_NODE_SCRIPTS_DIR}/setup-node.sh` (:400, :1142, :1182 message `missing (fetch the node scripts)`). The checkout is made at first boot by devnet-startup.sh
  from instance metadata `tn-scripts-ref` (devnet-deploy.sh:98-100, :282-285; not in scope); re-pointing uses `tn_cmd_refresh_scripts` (devnet-lib.sh:408).
- Phase A per node `_phase_a_node <i>` (:1133-1311): reads `INSTANCE_NAMES[i]`, `ZONES[i]`, `NODE_NAMES[i]`, `EXECUTION_ADDRESSES[i]`, role via `tn_node_role` (:1135-1143).
  Step 0 address must be 0x+40 hex (:1149-1157). Step 1 readiness probe `_rs_ready` (:396-418): `setup=`, `keygen=` (`PASSPHRASE_METHOD=` in `.node-meta`),
  `installed=` (`/etc/systemd/system/telcoin.service`), logmarks, `jcursor=`, `nc=<DATA_DIR>/network-config`; gate needs setup=1, keygen=1, installed=0 and
  `_nc_verdict` ok (:1181-1191). Step 2 scp committee/genesis/parameters to `/tmp`, `sudo install -o root -g root -m 0644` into `VALIDATOR_GENESIS_DIR` (:1198-1217).
  Internal + external IP via `tn_node_int_ip`/`tn_node_ext_ip` (:1222-1234).
- Exact finalize invocation (:1237-1273): `sudo bash '<TN_NODE_SCRIPTS_DIR>/setup-node.sh'` + each arg single-quoted:
  `--json --phase=finalize --network devnet --install-method docker --docker-image "${DOCKER_IMAGE}" --genesis-dir "${gdir}" --data-dir "${ddir}"
  --service-user "${SERVICE_USER}" --address "${addr}" --advertised-name "${node}" --public-rpc-url "https://${node}.${BASE_DOMAIN}"
  --public-ws-url "wss://${node}.${BASE_DOMAIN}" --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
  --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1" --external-primary "/ip4/${extIP}/udp/…49590/quic-v1"
  --external-worker "/ip4/${extIP}/udp/…49594/quic-v1" --public-ip "${extIP}" --enable-healthcheck-monitor`. No `--admission`, `--trusted-nodes`,
  `--bootstrap-peers`, `--passphrase-stdin` (no secret, :113-115). Run with `tn_iap_ssh … </dev/null`; success = ssh rc 0 AND done event `"ok":true` (:1276-1283).
  Step 4 `wait_healthy` (:1287). In stage-only/defer-start: require active+NRestarts 0, `_defer_stop`, print `STAGED <inst> …` (:1293-1308).
- Start: no-mode = finalize itself starts+enables each node in target order (serial unless `FINALIZE_JOBS>1`, `_run_nodes` :1012-1018).
  `_start_all` (:871-1001): per-target `_rs_startcheck` (unit installed+enabled; active → `RUNNING`) (:877-900); `due=now+FINALIZE_START_LEAD_SECS` (:904);
  one background ssh per node `FINALIZE_START_LAUNCH_GAP_SECS` apart running `_rs_start_at` (sleep to due on node clock, `systemctl start`, record
  `/run/tn-start-at.<due>`) (:910-913, :582); late > spread-warn → not started (:962); then `wait_healthy` (:984); prints
  `COORDINATED_START due=… nodes=… started=… skipped_running=… spread_secs=… max_late_secs=…` (:993).
- Post-checks (phase B, `_phase_b_node` :1337-1357; header :27-53):
  A1 `assert_service` (:722): active for `FINALIZE_STABLE_SECS`, NRestarts=0, is-enabled=enabled.
  A2 `assert_meta` (:748): `.node-meta` `NETWORK=devnet`, `DOCKER_IMAGE_DIGEST` = `${DOCKER_IMAGE##*@}` (:750-763).
  A3 `assert_network_config` (:767): file still Closed admission via `_nc_verdict` (:682-710: exactly one `admission:` block with `mode: Closed`, one
  `committee_peers:`, no BOM, and `python3 devnet-network-config.py validate "${NC_CTX[@]}" --node <node>` passes).
  A4 `assert_logs` (:781): no `bad yaml data`, `committee_peers:`, `trusted_nodes[`, `bootstrap_peers[`, `panicked` in logs after the gate's mark; not empty.
  A5 `assert_runtime` (:810): ExecStart `/usr/local/libexec/telcoin/tn-start-docker` (:162), container `telcoin` runs `DOCKER_IMAGE`, ReadonlyRootfs, `--pull=never`, `--read-only`, no `TN_BLS_PASSPHRASE` in environ.
- Index/role assumptions: `NC_CTX` `--nodes` = `NODE_NAMES[i]=NODE_ROLES[i]` for EVERY index, `--hub` = first `validator` (:357-364); quorum count by
  role string `validator` (:274-275); every per-node step reads all parallel arrays at the same index (:1135-1138, :1339-1341). No literal `4`/`node5`
  in code (grep); public RPC/WS URLs assume a `node{N}` DNS name for every index (:1260-1261).

## 6. devnet-network-config.sh (839) + devnet-network-config.py (908)
- Shell CLI: no flag = render+validate locally, touch no node (exits 0 at :168); `--yes` install; `--verify` read-only re-read+validate (exclusive, exit 2) (:84-87);
  `-h|--help`; positional targets via its own copy of `tn_select_indices` (:108, :131); every node is always rendered (:62-63). Knobs `NETCFG_TRUST_OBSERVERS_EVERYWHERE`,
  `NETCFG_FAST`, `NETCFG_JOBS` (:42-56, :99-104). Context: `NODES_SPEC=<NODE_NAMES[i]>=<NODE_ROLES[i]>,…` over all indices, `HUB` = first `validator` (:145-151).
- Py CLI (:867-908): context flags `--committee` `--genesis-dir` `--nodes` (help "node1=validator,...,node5=observer", :875) `--hub` (help "(node1)", :876)
  `--trust-observers-everywhere`; subcommands `render --out-dir`, `validate --node N [--existing E] FILE…`, `merge --rendered R [--existing E] --out O` (:50-56). No PyYAML → exit 3.
- Inputs: `genesis/committee.yaml` (`authorities`, `bootstrap_servers`, `num_workers`) and `genesis/validators/<n>.yaml` | `genesis/observers/<n>.yaml` `p2p_info` (py:401-463).
  Output: `genesis/network-config/<nodeN>.yaml` (sh `OUT_DIR`, :71). Keys in order `admission, hostname, bootstrap_peers, trusted_nodes, committee_peers` (py:87).
- Composition (`Context.expected`, py:509-518): all nodes `admission {mode: Closed, snapshot_max_age_secs: 300}` and `committee_peers` = committee.yaml
  `bootstrap_servers` verbatim; observers get `bootstrap_peers {<hub BLS>: server_for(hub)}`; `trusted_nodes` from `trusted_peers_of` (py:497-507): default hub → all
  observers, observer → [hub], other validators → none; with `--trust-observers-everywhere` validators → all observers, observers → all validators.
  `trusted_entry` = `{primary, workers: {0..local_workers-1}}` (py:488-495).
- Role model in py: `--nodes` items must be `validator|observer` else `ConfigError` (py:429-430); sub dir `validators`/`observers` (py:431); a validator must be in the
  committee, an observer must not (py:446-450); committee size must equal validator count (py:457); `--hub` must be a validator (py:459-460).
- Multiaddrs: copied verbatim from committee.yaml `bootstrap_servers` or the node-info `p2p_info` (`server_for`, py:481-486); no `/ip4` or `/dns` literal in the py (grep).
  `check_p2p_node` requires a multiaddr whose `/p2p/<PeerId>` matches the PeerId derived from `network_key` (py:306-330, :34-35). Address family is whatever keygen
  wrote [I: devnet-keygen.sh not in scope]; finalize advertises `/ip4/<extIP>/udp/…/quic-v1` (finalize:1264-1265).
- "Strict validator" (py:33-39): exact key names/nesting, `Closed` exactly, list-vs-map worker shapes, one `committee_peers` entry per member, PeerId match, trailing
  newline, existing `hostname:` line kept verbatim, byte-for-byte emitter output outside it; refuses BOM, merge keys, anchors, aliases, tags.
- Install per node (:26-36, `nc_resolve` :198): user/group/dir from `.node-meta` `HOST_SERVICE_USER`/`HOST_SERVICE_GROUP`/`DATA_DIR` (fallback `SERVICE_USER`, role data dir);
  refuse unless `<datadir>/node-info.yaml` BLS = local `genesis/<role>/<nodeN>.yaml` (role dir chosen by `role = "observer"` → observers else validators, :500, :593);
  merge keeps only the existing `hostname:` line; upload to /tmp then `install -o <user> -g <group> -m 0640 … <datadir>/network-config` (:412, :528); re-read must be
  byte-identical, owner/mode right, validator passes. No restart: a running unit "reads … at its NEXT start (not restarted here)" (:539-541, :652). `--verify`: re-read +
  validate only, one session a node with `NETCFG_FAST=1` (:52-55, :488, :563, :583).
- Tests: `benchmark/tests/test_network_config.py` (563 lines; goldens under `benchmark/tests/fixtures/network-config/golden`, fleet fixture 3 validators + 2 observers
  `fixtures/network-config/config.sh:9-12`); also `test_finalize_modes.py`, `test_node_image.py`, `check_mutations.py` reference the scripts.

## 7. Assumptions the two appended VMs break (index 5 = `rpc-6-devnet` role `rpc`; index 6 = `gateway-4-devnet` role `gateway`, no node, no keys)
- config.sh:85-102 — six parallel arrays of 5; each needs entries 5 and 6. `EXECUTION_ADDRESSES[6]` has no meaning for a keyless gateway, yet finalize Step 0
  rejects anything not 0x+40 hex (finalize:1149-1157). `STATIC_IP_NAMES` entries needed if `USE_STATIC_IPS=1` [I].
- config.sh:79-86 — role vocabulary is `validator`/`observer` only; comments "first four are the genesis committee", "Node 5" (:79-84), "all 5 nodes" (:337), `EXECUTION_ADDRESSES[4]` (:38, :90).
- devnet-lib.sh:261 — `tn_node_role` documented `validator|observer`; role helpers ignore role, so a gateway would get `setup-node.sh` + `/var/lib/telcoin` (:265-275) [I].
- devnet-deploy.sh:106 — step 3 waits for `devnet-startup.sh complete` on EVERY index: a gateway VM not booted with devnet-startup.sh times out after 600 s [I].
- devnet-deploy.sh:146-148 — step 4 prints a `NODE_NAMES[i].BASE_DOMAIN` A-record for every index (gateway included) [I].
- devnet-deploy.sh:13-28, :61 — 16-step header and `LAST_STEP=16`; :174 comment "node1/node5"; :180 step 8 runs finalize with no mode (serial starts, not one coordinated start).
- devnet-finalize.sh:205 — no targets = every index: the gateway enters phase A and fails the gate (`keygen=0`, network-config `missing`) (:1182-1191) [I].
- devnet-finalize.sh:357-364 and devnet-network-config.sh:145-151 — `--nodes` built from every index with `NODE_ROLES[i]`; py rejects any role other than
  `validator|observer` (py:429-430), so `rpc` or `gateway` aborts the render and the finalize gate/A3. `HUB` = first `validator` (index 0).
- devnet-network-config.py:431, :446-450, :457 — node-info path `genesis/{validators,observers}/<n>.yaml` by role; observer must be outside the committee;
  committee size == validator count. An `rpc` node (outside committee, like observer) has no dir mapping; a gateway has no node-info at all [I].
- devnet-network-config.py:497-507, :513-514 — trust/bootstrap graph knows only hub↔observers (or validators↔observers with the flag); no rpc or gateway case.
- devnet-network-config.sh:500, :593 — role dir chosen by `role = "observer"` → `observers` else `validators`: an `rpc` role would look in `validators/` [I].
- devnet-network-config.sh:21-23, :62-63, py:875-876 — prose/help hard-code "node1" hub, "(node5)" observer, "all five are still rendered".
- devnet-finalize.sh:1237-1271 — finalize args have no `--admission`/`--trusted-nodes`/`--bootstrap-peers`; admission comes only from the pre-installed
  network-config, whose Closed shape the gate (:1185) and A3 (:767) require — a native `setup-node.sh --admission …` path must still satisfy `_nc_verdict` (:682-710) [I].
- devnet-finalize.sh:1260-1261 — `--public-rpc-url/--public-ws-url https|wss://<NODE_NAME>.<BASE_DOMAIN>` for every index; rpc-6's name must exist in DNS [I].
- devnet-finalize.sh:274-277 — quorum guard counts role `validator` only: unaffected by `rpc`/`gateway` [I].
- devnet-finalize.sh:120-121 — usage examples `observer-5-devnet`, `0 4`.
- benchmark/config.sh:98-103 — bench fleet is its own 11-entry set (index 10 = observer); it inherits nothing from the appended entries; zones.env length check (:559) is per-profile.
- Tests: benchmark/tests/fixtures/network-config/config.sh:9-12 (3 validators + 2 observers) and goldens assume the two-role model.
