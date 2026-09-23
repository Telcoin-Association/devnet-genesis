#!/usr/bin/env bash
#
# benchmark-deploy.sh — stand up the throwaway benchmark fleet (10 validators + 1 observer,
# chain 32286, 20-min epochs) in tn-devnet, blast it from per-zone COS VMs, collect the
# evidence, and optionally tear it all down. The live devnet is never touched: no devnet
# instance, tag, rule, DNS name, LB or obs setting is created, modified or deleted.
#
# Dry run by default: without --yes it prints this run's full step plan (with the concrete
# commands) after local-only checks, and exits 0 without a single GCP call. With --yes it
# executes the steps; every gcloud mutation prints its argv first.
#
#    -  gate (--yes)     before ANY step: the pinned :blast-v2-<sha> image, cloudbuild.yaml,
#                        config.bench.toml and deployments-bench.json that the selected steps need
#    0  preflight        auth + tools + no leftover bench-*/benchmark=1 resources + accounts file +
#                        empty benchmark/genesis + firewall/tag hygiene + obs-devnet disk < 70% +
#                        quota; pre-snapshots; manifest.json
#    1  image            :blast-v2-<sha> exists, else Cloud Build builds it (synchronous);
#                        `IMAGE blast --help` must carry every contract flag (when docker exists)
#    2  instances        common/create-instances.sh on the bench profile; assert tag bench-node +
#                        label benchmark=1 on every node; label boot disks; manifest.instances[]
#    3  bootstrap        serial-console marker "devnet-startup.sh complete" on every node
#    4  firewall         benchmark-firewall.sh apply --yes
#    5  keygen           ../devnet-keygen.sh           (bench profile via CONFIG_FILE)
#    6  genesis          ../devnet-genesis-build.sh    (workspace benchmark/, chain 32286)
#    7  finalize         ../devnet-finalize.sh
#    8  observability    per node, ONE IAP session: setup-observability.sh --enable-metrics aimed at
#                        a black-hole URL, then (same session) stop Alloy, wipe its WAL, set
#                        TN_CHAIN=bench TN_NODE=<instance> + the real obs-devnet URL, start Alloy —
#                        no sample labelled network="devnet" ever leaves a bench node. Never
#                        create-obs-instance.sh, never devnet-observability.sh.
#    9  post-config      per node, ONE IAP session each, serially: reth --http.addr 0.0.0.0,
#                        assert the bench Alloy labels, restart (<=1 down at a time), wait for
#                        eth_chainId on the internal IP + consensus progressing (blocks rose, or
#                        subdag committed/quorum reached in its log — an idle chain stays at
#                        block 0), install node-sampler
#   10  health gate      wait_healthy x11, IAP tunnel -> cast chain-id == 32286, Prometheus
#                        min by (node)(tn_primary_round{network="bench"}) rising on all 11,
#                        Prometheus: count(count by (node)(tn_engine_canonical_height{network="bench"})) == 11
#                        and no bench node has any series labelled network="devnet"
#   11  contracts        (--with-contracts) tn-contracts worktree bench/<run> -> devnet-contracts.sh
#   12  IAM + bucket     secretAccessor on the bench secrets for the compute SA; gs://<bucket>
#   13  fund             benchmark-blast.sh fund --yes
#   14  blast            benchmark-blast.sh run --yes
#   15  collect          benchmark-blast.sh collect --yes + tn-transaction-generator/bench/collect-gcp-metrics.py
#   16  teardown         (--with-teardown) benchmark-teardown.sh --yes
#
# Usage:
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh                 # plan only
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --yes --with-contracts
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 9          # resume
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --only 15         # one step

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

LAST_STEP=16
CONFIRM=0; FROM=0; ONLY=""; WITH_CONTRACTS=0; WITH_TEARDOWN=0; PRINT_POSTCONFIG=""; PRINT_OBS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --from) FROM="${2:?--from needs a step number}"; shift ;;
        --from=*) FROM="${1#*=}" ;;
        --only) ONLY="${2:?--only needs a step number}"; shift ;;
        --only=*) ONLY="${1#*=}" ;;
        --with-contracts) WITH_CONTRACTS=1 ;;
        --with-teardown) WITH_TEARDOWN=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}" ;;
        --print-postconfig) PRINT_POSTCONFIG="${2:?--print-postconfig needs an instance}"; shift ;;  # review aid: print step 9's remote script
        --print-obs-script) PRINT_OBS="${2:?--print-obs-script needs an instance}"; shift ;;       # review aid: step 8's script, placeholder token
        -h|--help) sed -n '2,39p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --from N, --only N, --with-contracts, --with-teardown, --run ID)" >&2; exit 1 ;;
    esac
    shift
done
is_step() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 0 ] && [ "$1" -le "${LAST_STEP}" ]; }
is_step "${FROM}" || { echo "❌ --from must be 0..${LAST_STEP}" >&2; exit 1; }
[ -z "${ONLY}" ] || is_step "${ONLY}" || { echo "❌ --only must be 0..${LAST_STEP}" >&2; exit 1; }
export BENCH_RUN_ID="${BENCH_RUN_ID:-}"
# A resumed run keeps the image step 1 verified (the generator checkout may have moved on).
if [ -z "${BENCH_TXGEN_SHA:-}" ] && [ -n "${BENCH_RUN_ID}" ] && [ -f "${DIR}/results/${BENCH_RUN_ID}/manifest.json" ]; then
    BENCH_TXGEN_SHA="$(jq -r '.txgen_git_sha // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    export BENCH_TXGEN_SHA
fi
# shellcheck disable=SC2034  # read by bench-lib.sh (bench_run, manifest writers)
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"   # exports CONFIG_FILE=benchmark/config.sh for every sub-script

BOOTSTRAP_TIMEOUT_SECS=600
BOOTSTRAP_POLL_SECS=15
CHAIN_ID_HEX="$(printf '0x%x' "${CHAIN_ID}")"
PROM_COUNT_QUERY="count(count by (node) (tn_engine_canonical_height{network=\"${BENCH_PROM_NETWORK_LABEL}\"}))"
PROM_LEAK_QUERY='count(count by (node) (tn_engine_canonical_height{network="devnet", node=~"bench.*"}))'
PROM_LEAK_ANY_QUERY='count(count by (node) ({network="devnet", node=~"bench.*"}))'
COLLECT_METRICS_PY="${BENCH_TXGEN_BENCH_DIR}/collect-gcp-metrics.py"
DEVNET_TXGEN_MASTER="0x46c26b4fafffaab86437b11f5cdbd1b9f7ddc844"

# ================================ steps ==============================================
step_0() {
    echo ">>> Step 0: preflight"
    bench_require_tools gcloud cast jq python3 curl docker git openssl || bench_die "missing tools"
    [ "${WITH_CONTRACTS}" -eq 0 ] || bench_require_tools forge || bench_die "forge needed for --with-contracts"
    local acct; acct="$(gcloud config get-value account 2>/dev/null || true)"
    gcloud auth print-access-token >/dev/null || bench_die "gcloud auth failed — gcloud auth login"
    echo "    ✓ gcloud auth (${acct:-unknown account})"
    local left; left="$(bench_leftovers)"
    if [ -n "${left}" ]; then
        printf '%s\n' "${left}" | sed 's/^/    ✗ exists: /' >&2
        bench_die "benchmark resources from an earlier run still exist — tear them down first:
     benchmark/benchmark-teardown.sh            # dry run, then add --yes
   (or resume the run that owns them with --from N instead of starting at step 0)"
    fi
    echo "    ✓ no bench-* / benchmark=1 instance, disk, firewall rule or bucket exists"
    local accounts="${GENESIS_WORKSPACE}/testnet_accounts.yaml"
    grep -qi "${BENCH_TXGEN_MASTER_ADDRESS}" "${accounts}" || bench_die "${accounts} does not fund the bench txgen master ${BENCH_TXGEN_MASTER_ADDRESS}"
    ! grep -qi "${DEVNET_TXGEN_MASTER}" "${accounts}" || bench_die "${accounts} still funds the DEVNET txgen master"
    echo "    ✓ ${accounts} funds ${BENCH_TXGEN_MASTER_ADDRESS}"
    if [ -d "${BENCH_DIR}/genesis" ] && [ -n "$(ls -A "${BENCH_DIR}/genesis" 2>/dev/null)" ]; then
        bench_die "${BENCH_DIR}/genesis is not empty (a previous run's keys?) — benchmark-teardown.sh moves it into results/<run>/"
    fi
    echo "    ✓ benchmark/genesis empty"
    if [ ! -s "${TN_BLS_PASSPHRASE_FILE}" ]; then
        echo "    creating bench BLS passphrase ${TN_BLS_PASSPHRASE_FILE} (gitignored, mode 600, never printed)"
        ( umask 077; mkdir -p "$(dirname "${TN_BLS_PASSPHRASE_FILE}")"; openssl rand -hex 24 | tr -d '\n' > "${TN_BLS_PASSPHRASE_FILE}" )
    fi
    echo "    ✓ bench BLS passphrase present"
    local foreign
    foreign="$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json | jq -r \
        --argjson ours "$(printf '%s\n' "${BENCH_FIREWALL_RULES[@]}" | jq -R . | jq -s .)" \
        '.[] | select((.targetTags // []) | index("bench-node")) | select(.name as $n | $ours | index($n) | not) | .name')"
    [ -z "${foreign}" ] || bench_die "non-bench firewall rules target bench-node: ${foreign}"
    echo "    ✓ no non-bench firewall rule targets bench-node"
    local obs_pct
    obs_pct="$(tn_iap_ssh "${OBS_INSTANCE_NAME}" "${OBS_ZONE}" "df --output=pcent /mnt/obs-data | tail -1" 2>/dev/null | tr -dc '0-9' || true)"
    [ -n "${obs_pct}" ] || bench_die "could not read obs-devnet /mnt/obs-data usage over IAP"
    [ "${obs_pct}" -lt 70 ] || bench_die "obs-devnet data disk is ${obs_pct}% (>= 70%) — bench metrics would push it over"
    echo "    ✓ obs-devnet /mnt/obs-data ${obs_pct}%"
    local region need have
    for region in $(for z in "${ZONES[@]}"; do tn_region_from_zone "${z}"; echo; done | sort -u); do
        need=0
        for i in "${!ZONES[@]}"; do
            [ "$(tn_region_from_zone "${ZONES[$i]}")" = "${region}" ] || continue
            need=$(( need + $(bench_machine_shape "${MACHINE_TYPE}" "${ZONES[$i]}" | awk '{print $1}') ))
            [ "${NODE_ROLES[$i]}" = "validator" ] && need=$(( need + 2 ))   # its blaster (e2-standard-2)
        done
        have="$(gcloud compute regions describe "${region}" --project="${PROJECT_ID}" --format=json \
            | jq -r '.quotas[] | select(.metric == "CPUS") | (.limit - .usage) | floor')"
        [ "${have}" -ge "${need}" ] || bench_die "${region}: CPUS headroom ${have} < ${need}"
        echo "    ✓ ${region}: CPUS headroom ${have} >= ${need}"
    done
    mkdir -p "${BENCH_RESULTS_DIR}"
    [ -f "${BENCH_RESULTS_DIR}/pre-instances.json" ] \
        || gcloud compute instances list --project="${PROJECT_ID}" --format=json > "${BENCH_RESULTS_DIR}/pre-instances.json"
    [ -f "${BENCH_RESULTS_DIR}/pre-firewall.json" ] \
        || gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json > "${BENCH_RESULTS_DIR}/pre-firewall.json"
    echo "    ✓ pre-snapshots in ${BENCH_RESULTS_DIR}/pre-{instances,firewall}.json"
    bench_manifest_init
}

step_1() {
    bench_require_txgen_image
    local digest tag="${BENCH_TXGEN_IMAGE##*:}" sha
    sha="${tag#blast-v2-}"
    echo ">>> Step 1: txgen image ${BENCH_TXGEN_IMAGE}"
    digest="$(bench_txgen_image_digest)"
    if [ -z "${digest}" ]; then
        # Build only what the tag claims: HEAD of a clean generator checkout.
        [ -z "${BENCH_TXGEN_IMAGE_ERROR}" ] || bench_die "cannot build: ${BENCH_TXGEN_IMAGE_ERROR}"
        [ "$(git -C "${BENCH_TXGEN_REPO}" rev-parse --short=7 HEAD)" = "${sha}" ] \
            || bench_die "tag ${tag} is not HEAD of ${BENCH_TXGEN_REPO} — check out ${sha} or unset BENCH_TXGEN_SHA/BENCH_TXGEN_IMAGE"
        [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] || bench_die "missing ${BENCH_TXGEN_CLOUDBUILD}"
        echo "    not in the registry — building it with Cloud Build (synchronous)"
        bench_run gcloud builds submit --project="${PROJECT_ID}" --config="${BENCH_TXGEN_CLOUDBUILD}" \
            --substitutions="_IMAGE=${BENCH_TXGEN_IMAGE%:*},_TAG=${tag},_GIT_SHA=${sha}" "${BENCH_TXGEN_REPO}"
        digest="$(bench_txgen_image_digest)"
        [ -n "${digest}" ] || bench_die "Cloud Build finished but ${BENCH_TXGEN_IMAGE} is still not in the registry"
    fi
    echo "    ✓ ${BENCH_TXGEN_IMAGE} = ${digest}"
    bench_txgen_cli_probe
    bench_manifest_jq --arg i "${BENCH_TXGEN_IMAGE}" --arg d "${digest}" --arg s "${sha}" \
        '.txgen_image = $i | .txgen_image_digest = $d | .txgen_git_sha = $s'
}

step_2() {
    echo ">>> Step 2: create the bench instances (common/create-instances.sh, bench profile)"
    echo "    + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/common/create-instances.sh"
    "${REPO_ROOT}/common/create-instances.sh"
    echo "    asserting tags == [bench-node] and labels.benchmark == 1 on every node"
    local i inst zone j bad=0
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        j="$(bench_instance_json "${inst}" "${zone}")"
        if [ -z "${j}" ] || ! printf '%s' "${j}" | jq -e '(.tags.items // []) == ["bench-node"] and .labels.benchmark == "1"' >/dev/null; then
            echo "    ✗ ${inst}: $(printf '%s' "${j}" | jq -c '{tags: .tags.items, labels}' 2>/dev/null || echo missing)" >&2; bad=1
        fi
    done
    if [ "${bad}" -ne 0 ]; then
        echo "❌ a bench instance is missing its bench-node tag / benchmark=1 label. Nothing else will run." >&2
        echo "   Inspect, then clean up with: benchmark/benchmark-teardown.sh --run ${BENCH_RUN_ID} (dry run first)" >&2
        exit 1
    fi
    echo "    ✓ all ${#INSTANCE_NAMES[@]} tagged bench-node + labelled benchmark=1"
    local insts="[]" disk djson shape
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        j="$(bench_instance_json "${inst}" "${zone}")"
        disk="$(printf '%s' "${j}" | jq -r '.disks[] | select(.boot) | .source | split("/") | last')"
        bench_run gcloud compute disks add-labels "${disk}" --zone="${zone}" --project="${PROJECT_ID}" \
            --labels="${BENCH_LABELS},tn-role=${NODE_ROLES[$i]}" --format=none
        djson="$(gcloud compute disks describe "${disk}" --zone="${zone}" --project="${PROJECT_ID}" --format=json)"
        shape="$(bench_machine_shape "$(printf '%s' "${j}" | jq -r '.machineType | split("/") | last')" "${zone}")"
        insts="$(printf '%s' "${insts}" | jq --argjson j "${j}" --argjson d "${djson}" --arg role "${NODE_ROLES[$i]}" \
            --arg zone "${zone}" --arg v "${shape% *}" --arg m "${shape#* }" '
            . + [{name: $j.name, role: $role, zone: $zone, instance_id: $j.id,
                  machine_type: ($j.machineType | split("/") | last), vcpus: ($v|tonumber), memory_mb: ($m|tonumber),
                  internal_ip: $j.networkInterfaces[0].networkIP,
                  external_ip: ($j.networkInterfaces[0].accessConfigs[0].natIP // null),
                  boot_disk: {name: $d.name, size_gb: ($d.sizeGb|tonumber), type: ($d.type | split("/") | last)}}]')"
    done
    bench_manifest_jq --argjson a "${insts}" '.instances = $a'
    echo "    ✓ manifest.instances[] recorded (${#INSTANCE_NAMES[@]})"
}

step_3() {
    echo ">>> Step 3: wait for first-boot bootstrap (serial marker 'devnet-startup.sh complete')"
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        bench_serial_wait "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "devnet-startup.sh complete" \
            "${BOOTSTRAP_TIMEOUT_SECS}" "${BOOTSTRAP_POLL_SECS}" \
            || bench_die "${INSTANCE_NAMES[$i]} did not finish bootstrap; serial: gcloud compute instances get-serial-port-output ${INSTANCE_NAMES[$i]} --zone=${ZONES[$i]}"
    done
}

step_4()  { echo ">>> Step 4: bench firewall rules"; "${DIR}/benchmark-firewall.sh" apply --yes --run "${BENCH_RUN_ID}"; }
step_5()  { echo ">>> Step 5: keygen";               "${REPO_ROOT}/devnet-keygen.sh"; }
step_6()  { echo ">>> Step 6: genesis (chain ${CHAIN_ID}, workspace ${GENESIS_WORKSPACE})"; "${REPO_ROOT}/devnet-genesis-build.sh"; }
step_7()  { echo ">>> Step 7: finalize (stage + start)"; "${REPO_ROOT}/devnet-finalize.sh"; }

# obs_script <instance> <region> <token> — step 8's remote script for one node (piped to
# `sudo bash -s`, so the ingest token never appears on a gcloud command line).
#
# setup-observability.sh derives TN_CHAIN from the node's NETWORK=devnet (DEVNET_CHAIN_NAME is
# readonly in tn-node-deployment), so left alone the node would remote-write
# network="devnet" chain="devnet" samples into obs-devnet. To make that impossible rather than
# brief, setup-observability.sh is pointed at a black-hole metrics URL (127.0.0.1:9, refused);
# then, in the same session and before anything can reach obs-devnet, Alloy is stopped, its WAL
# (which holds the devnet-labelled samples) is wiped, the env gets TN_CHAIN/TN_NODE/the real URL,
# and Alloy starts again. The first sample obs-devnet ever sees from a bench node is network=bench.
obs_script() {
    local inst="$1" region="$2" token="$3" hold="http://127.0.0.1:9/bench-hold"
    cat <<EOS
set -euo pipefail
fail() { echo "OBSCFG_FAIL \$*"; exit 1; }
TOKEN=$(printf '%q' "${token}")
if ! OBS_PUSH_URL='${OBS_PUSH_URL}' OBS_METRICS_PUSH_URL='${hold}' \\
    '${TN_NODE_SCRIPTS_DIR}/setup-observability.sh' --json --enable-metrics --region '${region}' \\
    --token "\${TOKEN}" --push-url '${OBS_PUSH_URL}' --metrics-push-url '${hold}' > /tmp/bench-obs.json 2>/tmp/bench-obs.err; then
    tail -5 /tmp/bench-obs.err; fail "setup-observability.sh failed"
fi
unset TOKEN
systemctl stop telcoin-alloy.service
rm -rf /var/lib/telcoin-alloy/* 2>/dev/null || true
E=/etc/telcoin/alloy/telcoin-alloy.env
[ -f "\$E" ] || fail "no \$E"
sed -i -e 's/^TN_CHAIN=.*/TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}/' -e 's/^TN_NODE=.*/TN_NODE=${inst}/' \\
    -e 's#^OBS_METRICS_PUSH_URL=.*#OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}#' "\$E"
grep -qx 'TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}' "\$E" && grep -qx 'TN_NODE=${inst}' "\$E" \\
    && grep -qx 'OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}' "\$E" || fail "alloy env not rewritten"
systemctl start telcoin-alloy.service
systemctl is-active --quiet telcoin-alloy.service || fail "telcoin-alloy not active"
echo "OBSCFG_OK ${inst} \$(tail -1 /tmp/bench-obs.json 2>/dev/null)"
EOS
}

step_8() {
    echo ">>> Step 8: per-node observability, metrics only -> ${OBS_METRICS_PUSH_URL}, labelled network=${BENCH_PROM_NETWORK_LABEL} before the first push"
    # Never common/create-obs-instance.sh (and never --wipe-data): obs-devnet is devnet's.
    # Not devnet-observability.sh either: it cannot relabel inside the setup session (see obs_script).
    local token i inst out
    token="$(tn_secret "${OBS_SECRET_NAME}")" || true
    [ -n "${token}" ] || bench_die "obs ingest token (${OBS_SECRET_NAME}) is empty"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: setup-observability.sh --enable-metrics (token redacted) + same-session relabel"
        out="$(obs_script "${inst}" "$(tn_region_from_zone "${ZONES[$i]}")" "${token}" | tn_iap_ssh_stdin "${inst}" "${ZONES[$i]}" 2>&1 || true)"
        printf '%s\n' "${out}" | grep -E 'OBSCFG_(OK|FAIL)' | cut -c1-200 | sed 's/^/      /' || true
        [[ "${out}" == *"OBSCFG_OK ${inst}"* ]] || bench_die "observability failed on ${inst}"
    done
    unset token
}

# postconfig_script <instance> — step 9's remote script for one node (piped to `sudo bash -s`).
# Everything that can fail transiently (the RPC while the node restarts) is polled with a
# deadline and never trips set -e/pipefail; only the final assertions can fail the session.
postconfig_script() {
    local inst="$1" b64
    b64="$(base64 < "${DIR}/node-sampler.sh" | tr -d '\n')"
    cat <<EOS
set -euo pipefail
fail() { echo "POSTCFG_FAIL \$*"; exit 1; }
W=/opt/telcoin/start-telcoin.sh
[ -f "\$W" ] || fail "no \$W (docker start wrapper)"
# 1. reth RPC on all interfaces (blasters reach it on the internal IP; no public rule admits 8545)
sed -i 's/--http\.addr 127\.0\.0\.1/--http.addr 0.0.0.0/' "\$W"
grep -q -- '--http.addr 0.0.0.0' "\$W" || fail "http.addr not rewritten"
# 2. alloy labels were set in step 8's session; assert they are still bench labels
E=/etc/telcoin/alloy/telcoin-alloy.env
grep -qx 'TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}' "\$E" && grep -qx 'TN_NODE=${inst}' "\$E" || fail "alloy env lacks bench labels (re-run step 8)"
# 3. restart the node; wait until it serves chain ${CHAIN_ID} on the INTERNAL IP and consensus is
#    progressing. An idle TN chain stays at block 0 (the engine skips empty non-epoch-closing
#    consensus outputs), so progress = eth_blockNumber increased OR this node's own log shows
#    consensus commits since the restart. Polled to the deadline so the node can rejoin.
systemctl restart telcoin
restart_ts=\$(date +%s)
IP=\$(curl -sf -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip || true)
[ -n "\$IP" ] || fail "no internal IP from the metadata server"
# ECONNREFUSED right after the restart is expected: curl's failure is swallowed, empty = retry.
rpc() { { curl -s --max-time 3 -H 'content-type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"\$1\",\"params\":[]}" "http://\${IP}:8545" || true; } | sed -n 's/.*"result":"\([^"]*\)".*/\1/p' || true; }
# consensus lines in the node's docker log since the restart (never older than 45 s)
commits() {
    local now since
    now=\$(date +%s); since=\$(( now - 45 )); [ "\$since" -ge "\$restart_ts" ] || since="\$restart_ts"
    { docker logs telcoin --since "\$since" 2>&1 || true; } | grep -c -E 'subdag committed|quorum reached' || true
}
cid=""; b0=""; b=""; how=""; n=0
deadline=\$(( \$(date +%s) + \${POSTCFG_WAIT_SECS:-300} ))
while [ "\$(date +%s)" -lt "\$deadline" ]; do
    if systemctl is-active --quiet telcoin; then
        cid="\$(rpc eth_chainId)"
        if [ "\$cid" = "${CHAIN_ID_HEX}" ]; then
            b="\$(rpc eth_blockNumber)"
            if [ -n "\$b" ]; then
                if [ -z "\$b0" ]; then b0="\$b"; elif [ "\$((b))" -gt "\$((b0))" ]; then how="blocks \$((b0))->\$((b))"; break; fi
            fi
            n="\$(commits)"
            if [ "\${n:-0}" -ge 1 ]; then how="consensus log (\${n} subdag committed/quorum reached lines since restart)"; break; fi
        fi
    fi
    sleep 5
done
[ "\$cid" = "${CHAIN_ID_HEX}" ] || fail "eth_chainId on \${IP}:8545 = '\$cid', expected ${CHAIN_ID_HEX}"
[ -n "\$how" ] || fail "consensus not progressing: block \${b0:-none} -> \${b:-none} and no 'subdag committed|quorum reached' in docker logs since the restart"
# 4. node sampler (systemd, root)
echo '${b64}' | base64 -d > /usr/local/bin/bench-node-sampler.sh
chmod 0755 /usr/local/bin/bench-node-sampler.sh
cat > /etc/systemd/system/bench-node-sampler.service <<'UNIT'
[Unit]
Description=benchmark node sampler (CSV every 30 s -> /var/lib/bench-sampler)
After=docker.service telcoin.service
[Service]
Type=simple
ExecStart=/usr/local/bin/bench-node-sampler.sh
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now bench-node-sampler.service
systemctl is-active --quiet bench-node-sampler.service || fail "sampler not active"
echo "POSTCFG_OK ${inst} chain=\$cid block=\${b:-?} ip=\${IP} progress=\${how}"
EOS
}

step_9() {
    echo ">>> Step 9: post-config, one IAP session per node, serially (<= 1 node down at a time)"
    local i inst out
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: http.addr 0.0.0.0, assert alloy labels, restart, chain-id ${CHAIN_ID_HEX} on internal IP, sampler"
        out="$(postconfig_script "${inst}" | tn_iap_ssh_stdin "${inst}" "${ZONES[$i]}" 2>&1 || true)"
        printf '%s\n' "${out}" | grep -E 'POSTCFG_(OK|FAIL)' | sed 's/^/      /' || true
        [[ "${out}" == *"POSTCFG_OK ${inst}"* ]] || bench_die "post-config failed on ${inst} — stopping before any other node restarts"
    done
}

step_10() {
    echo ">>> Step 10: health gate"
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        HEALTH_POLL_SECS=15 HEALTH_TIMEOUT_SECS=180 wait_healthy "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$(tn_service_for_role "${NODE_ROLES[$i]}")" \
            || bench_die "${INSTANCE_NAMES[$i]} not healthy"
    done
    bench_tunnel_up || bench_die "IAP tunnel failed"
    local cid
    cid="$(cast chain-id --rpc-url "${RPC_URL}")"
    [ "${cid}" = "${CHAIN_ID}" ] || bench_die "tunnel RPC reports chain ${cid}, expected ${CHAIN_ID}"
    echo "    ✓ chain id ${cid} via ${RPC_URL} (block $(cast block-number --rpc-url "${RPC_URL}" 2>/dev/null || echo '?'); an idle TN chain stays at 0 until the funder runs)"
    # Progress = consensus rounds, not blocks: every node's min(tn_primary_round) must rise above
    # its first sample. Re-sampled every 30 s (up to 4x) to absorb scrape + remote-write lag.
    local r0 r1="" adv="[]" tries=0 missing=" (no Prometheus sample)" inst
    r0="$(bench_prom_rounds min)"
    [ -n "${r0}" ] || bench_die "Prometheus tn_primary_round query failed"
    while [ "${tries}" -lt 4 ]; do
        sleep 30; tries=$((tries + 1))
        r1="$(bench_prom_rounds min)"
        [ -n "${r1}" ] || continue
        adv="$(bench_rounds_advanced "${r0}" "${r1}")"
        missing=""
        for inst in "${INSTANCE_NAMES[@]}"; do
            printf '%s' "${adv}" | jq -e --arg n "${inst}" 'index($n) != null' >/dev/null || missing="${missing} ${inst}"
        done
        [ -n "${missing}" ] || break
        echo "      …consensus round not yet advanced on:${missing} ($((tries * 30))s)"
    done
    [ -z "${missing}" ] || bench_die "consensus round did not advance on:${missing} (first ${r0}, last ${r1:-none})"
    echo "    ✓ consensus progressing: tn_primary_round advanced on all ${#INSTANCE_NAMES[@]} nodes ($(printf '%s' "${r1}" | jq -r '[.[]] | "rounds " + (min|tostring) + ".." + (max|tostring)'))"
    local n="" waited=0
    while [ "${waited}" -le 300 ]; do
        n="$(bench_prom_scalar "${PROM_COUNT_QUERY}")"
        [ "${n}" = "${#INSTANCE_NAMES[@]}" ] && break
        echo "      …Prometheus sees ${n:-0}/${#INSTANCE_NAMES[@]} bench nodes (${waited}s)"
        sleep 30; waited=$((waited + 30))
    done
    [ "${n}" = "${#INSTANCE_NAMES[@]}" ] || bench_die "Prometheus sees ${n:-0} bench nodes, expected ${#INSTANCE_NAMES[@]} (${PROM_COUNT_QUERY})"
    echo "    ✓ Prometheus: ${n} bench nodes reporting"
    # No bench series may ever carry devnet's labels (step 8 relabels before the first push).
    local q raw leak
    for q in "${PROM_LEAK_QUERY}" "${PROM_LEAK_ANY_QUERY}"; do
        raw="$(bench_prom_query "${q}" || true)"
        printf '%s' "${raw}" | jq -e '.status == "success"' >/dev/null 2>&1 || bench_die "Prometheus query failed: ${q}"
        leak="$(printf '%s' "${raw}" | jq -r '.data.result[0].value[1] // "0"')"
        [ "${leak}" = "0" ] || bench_die "${leak} bench node(s) have series labelled network=\"devnet\" in obs-devnet (${q})"
    done
    echo "    ✓ Prometheus: no network=\"devnet\" series from bench nodes"
    bench_manifest_ts nodes_healthy
}

step_11() {
    echo ">>> Step 11: app contracts on chain ${CHAIN_ID}"
    local out="${BENCH_RESULTS_DIR}/deployments-bench.json"
    if [ "${WITH_CONTRACTS}" -ne 1 ]; then
        echo "    skipped (no --with-contracts). Steps 13/14 need ${out}."
        [ -f "${out}" ] || bench_warn "${out} does not exist yet"
        return 0
    fi
    local wt="${BENCH_CONTRACTS_WORKTREE}" br="${BENCH_CONTRACTS_BRANCH}"
    [ -d "${BENCH_CONTRACTS_SRC_DIR}" ] || bench_die "${BENCH_CONTRACTS_SRC_DIR} missing (devnet-contracts.sh's checkout)"
    if [ ! -d "${wt}" ]; then
        mkdir -p "$(dirname "${wt}")"
        bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree add "${wt}" -b "${br}" "${BENCH_CONTRACTS_BASE_BRANCH}"
    fi
    [ "$(git -C "${wt}" rev-parse --abbrev-ref HEAD)" = "${br}" ] || bench_die "${wt} is not on ${br}"
    bench_run git -C "${wt}" submodule update --init --recursive
    # Chain 32286 routes tn-contracts to deployments-testnet.json (DeploymentsResolver.sol);
    # seed it with the devnet address book so the same CREATE2 addresses are expected.
    bench_run cp "${wt}/deployments/deployments-devnet.json" "${wt}/deployments/deployments-testnet.json"
    bench_tunnel_up || bench_die "IAP tunnel failed"
    echo "    + TN_CONTRACTS_DIR=${wt} TN_CONTRACTS_BRANCH=${br} DEPLOYMENTS_JSON=deployments/deployments-testnet.json DEVNET_RPC=${RPC_URL} EXPECTED_CHAIN_ID=${CHAIN_ID} devnet-contracts.sh --yes"
    TN_CONTRACTS_DIR="${wt}" TN_CONTRACTS_BRANCH="${br}" DEPLOYMENTS_JSON="deployments/deployments-testnet.json" \
        DEVNET_RPC="${RPC_URL}" EXPECTED_CHAIN_ID="${CHAIN_ID}" "${REPO_ROOT}/devnet-contracts.sh" --yes
    cp "${wt}/deployments/deployments-testnet.json" "${out}"
    echo "    ✓ ${out} (the worktree is never committed; teardown removes it + ${br})"
    bench_manifest_ts contracts_done
}

step_12() {
    echo ">>> Step 12: secret access for ${SERVICE_ACCOUNT} + results bucket gs://${BENCH_BUCKET}"
    local s
    for s in "${BENCH_TXGEN_MASTER_SECRET}" "${BENCH_TXGEN_SEED_SECRET}"; do
        case "${s}" in bench-txgen-*) ;; *) bench_die "unexpected secret ${s}" ;; esac
        bench_run gcloud secrets add-iam-policy-binding "${s}" --project="${PROJECT_ID}" \
            --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --format=none
    done
    if gcloud storage buckets describe "gs://${BENCH_BUCKET}" --format='value(name)' >/dev/null 2>&1; then
        echo "    bucket exists"
    else
        bench_run gcloud storage buckets create "gs://${BENCH_BUCKET}" --project="${PROJECT_ID}" \
            --location="${BENCH_BUCKET_LOCATION}" --uniform-bucket-level-access
    fi
    bench_run gcloud storage buckets update "gs://${BENCH_BUCKET}" --update-labels="${BENCH_LABELS}"
}

step_13() { echo ">>> Step 13: fund senders"; "${DIR}/benchmark-blast.sh" fund --yes --run "${BENCH_RUN_ID}"; }
step_14() { echo ">>> Step 14: blast";        "${DIR}/benchmark-blast.sh" run --yes --run "${BENCH_RUN_ID}"; }

step_15() {
    echo ">>> Step 15: collect"
    "${DIR}/benchmark-blast.sh" collect --yes --run "${BENCH_RUN_ID}"
    if [ -f "${COLLECT_METRICS_PY}" ]; then
        echo "    + python3 ${COLLECT_METRICS_PY} --manifest ${BENCH_RESULTS_DIR}/manifest.json --out ${BENCH_RESULTS_DIR}/metrics.json"
        python3 "${COLLECT_METRICS_PY}" --manifest "$(bench_manifest)" --out "${BENCH_RESULTS_DIR}/metrics.json"
    else
        bench_warn "${COLLECT_METRICS_PY} not found — metrics.json not produced (re-run --only 15 once it exists)"
        bench_manifest_note "collect: ${COLLECT_METRICS_PY} missing at $(bench_now_iso)"
    fi
}

step_16() {
    echo ">>> Step 16: teardown"
    if [ "${WITH_TEARDOWN}" -ne 1 ]; then
        echo "    skipped (no --with-teardown). Later: benchmark/benchmark-teardown.sh --run ${BENCH_RUN_ID} --yes"
        return 0
    fi
    bench_tunnel_down
    "${DIR}/benchmark-teardown.sh" --yes --run "${BENCH_RUN_ID}"
}

# ================================ dry-run plan ==========================================
print_plan() {
    local i
    cat <<EOP
PLAN for run ${BENCH_RUN_ID} (nothing below has been executed):

  fleet    ${#INSTANCE_NAMES[@]} x ${MACHINE_TYPE}, ${NODE_DISK_SIZE} GB ${NODE_DISK_TYPE}, tag ${INSTANCE_TAGS}, labels ${INSTANCE_LABELS}
  chain    ${CHAIN_ID} (${CHAIN_ID_HEX}), epoch ${EPOCH_DURATION_SECS}s, image ${DOCKER_IMAGE}
  genesis  workspace ${GENESIS_WORKSPACE}, accounts ${GENESIS_WORKSPACE}/testnet_accounts.yaml
  metrics  -> ${OBS_METRICS_PUSH_URL} as network="${BENCH_PROM_NETWORK_LABEL}" (obs-devnet, metrics only)
  load     ${BENCH_TXGEN_IMAGE}, ${BENCH_BLASTER_MACHINE_TYPE} COS blasters x ${BENCH_SENDERS} senders, bucket gs://${BENCH_BUCKET}
  results  ${BENCH_RESULTS_DIR}
EOP
    for i in "${!INSTANCE_NAMES[@]}"; do
        printf '    %-20s %-10s %-26s %s %s\n' "${INSTANCE_NAMES[$i]}" "${NODE_ROLES[$i]}" "${ZONES[$i]}" "${NODE_NAMES[$i]}" "${EXECUTION_ADDRESSES[$i]}"
    done
    cat <<EOP

   -  gate           (--yes, before any step) pinned image, ${BENCH_TXGEN_CLOUDBUILD}, ${BENCH_TXGEN_CONFIG}, deployments-bench.json
   0  preflight      tools, auth, NO leftover bench-*/benchmark=1 instance|disk|rule|bucket, accounts, empty genesis/,
                     bench-node tag hygiene, obs-devnet df over IAP (< 70%), CPU quota,
                     pre-snapshots -> ${BENCH_RESULTS_DIR}/pre-{instances,firewall}.json, manifest.json
   1  image          ${BENCH_TXGEN_IMAGE:-<unresolved: ${BENCH_TXGEN_IMAGE_ERROR}>}
                     if absent: gcloud builds submit --config=${BENCH_TXGEN_CLOUDBUILD} --substitutions=_IMAGE=${BENCH_TXGEN_IMAGE_REPO},_TAG=${BENCH_TXGEN_TAG:-blast-v2-<sha>},_GIT_SHA=${BENCH_TXGEN_SHA:-<sha>} ${BENCH_TXGEN_REPO}
                     then docker run --rm --platform linux/amd64 <image> blast --help must list: ${BENCH_TXGEN_CONTRACT_FLAGS}
   2  instances      CONFIG_FILE=benchmark/config.sh ${REPO_ROOT}/common/create-instances.sh
                     assert tags==[bench-node] + labels.benchmark=1; gcloud compute disks add-labels <boot> --labels=${BENCH_LABELS},tn-role=<role>
   3  bootstrap      serial marker 'devnet-startup.sh complete' (${BOOTSTRAP_TIMEOUT_SECS}s/node)
   4  firewall       benchmark/benchmark-firewall.sh apply --yes   (${BENCH_FIREWALL_RULES[*]} -> tag bench-node)
   5  keygen         ${REPO_ROOT}/devnet-keygen.sh           -> ${GENESIS_WORKSPACE}/genesis/{validators,observers}/
   6  genesis        ${REPO_ROOT}/devnet-genesis-build.sh    -> ${GENESIS_FILE}
   7  finalize       ${REPO_ROOT}/devnet-finalize.sh
   8  observability  per node, one IAP session: setup-observability.sh --enable-metrics -> black hole 127.0.0.1:9,
                     stop alloy, wipe /var/lib/telcoin-alloy, TN_CHAIN=${BENCH_PROM_NETWORK_LABEL} TN_NODE=<instance> OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}, start alloy
   9  post-config    per node, one IAP session, serial: /opt/telcoin/start-telcoin.sh --http.addr 0.0.0.0; assert
                     bench alloy labels; restart telcoin; eth_chainId == ${CHAIN_ID_HEX} on the internal IP + consensus progressing
                     (blocks rose OR docker logs 'subdag committed|quorum reached' since restart); bench-node-sampler.service
  10  health gate    wait_healthy x${#INSTANCE_NAMES[@]}; gcloud compute start-iap-tunnel ${INSTANCE_NAMES[0]} 8545 --local-host-port=localhost:${BENCH_TUNNEL_PORT};
                     cast chain-id == ${CHAIN_ID}; Prometheus ${PROM_COUNT_QUERY} == ${#INSTANCE_NAMES[@]};
                     min by (node)(tn_primary_round{network="${BENCH_PROM_NETWORK_LABEL}"}) rises on every node (samples 30 s apart);
                     ${PROM_LEAK_QUERY} == 0 (and the same over every metric)
  11  contracts      $([ "${WITH_CONTRACTS}" -eq 1 ] && echo "git worktree add ${BENCH_CONTRACTS_WORKTREE} -b ${BENCH_CONTRACTS_BRANCH} ${BENCH_CONTRACTS_BASE_BRANCH}" || echo "SKIPPED (pass --with-contracts)")
                     $([ "${WITH_CONTRACTS}" -eq 1 ] && echo "devnet-contracts.sh --yes (DEPLOYMENTS_JSON=deployments/deployments-testnet.json EXPECTED_CHAIN_ID=${CHAIN_ID}) -> ${BENCH_RESULTS_DIR}/deployments-bench.json")
  12  IAM + bucket   gcloud secrets add-iam-policy-binding ${BENCH_TXGEN_MASTER_SECRET}|${BENCH_TXGEN_SEED_SECRET} --member=serviceAccount:${SERVICE_ACCOUNT} --role=roles/secretmanager.secretAccessor
                     gcloud storage buckets create gs://${BENCH_BUCKET} --location=${BENCH_BUCKET_LOCATION}; update --update-labels=${BENCH_LABELS}
  13  fund           benchmark/benchmark-blast.sh fund --yes   (bench-funder, --prepare $(( 10 * BENCH_SENDERS )) senders from $(( BENCH_RUN_INDEX * 100000 )))
  14  blast          benchmark/benchmark-blast.sh run --yes    (bench-blaster-01..10, start now+${BENCH_START_DELAY_SECS}s, ${BENCH_DURATION_SECS}s mixed, chaos on v05 + observer)
  15  collect        benchmark/benchmark-blast.sh collect --yes; python3 ${COLLECT_METRICS_PY} --manifest ${BENCH_RESULTS_DIR}/manifest.json --out ${BENCH_RESULTS_DIR}/metrics.json
  16  teardown       $([ "${WITH_TEARDOWN}" -eq 1 ] && echo "benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" || echo "SKIPPED (pass --with-teardown; or run benchmark-teardown.sh later)")

Scope: $([ -n "${ONLY}" ] && echo "ONLY step ${ONLY}" || echo "steps ${FROM}..${LAST_STEP}")
EOP
    echo "Local checks (no GCP calls):"
    local ok=1
    bench_require_tools gcloud cast jq python3 curl docker git || ok=0
    if grep -qi "${BENCH_TXGEN_MASTER_ADDRESS}" "${GENESIS_WORKSPACE}/testnet_accounts.yaml" 2>/dev/null; then
        echo "    ✓ accounts file funds the bench txgen master"; else echo "    ✗ accounts file lacks ${BENCH_TXGEN_MASTER_ADDRESS}"; ok=0; fi
    if [ -d "${BENCH_DIR}/genesis" ] && [ -n "$(ls -A "${BENCH_DIR}/genesis" 2>/dev/null)" ]; then
        echo "    ✗ ${BENCH_DIR}/genesis is not empty"; ok=0; else echo "    ✓ benchmark/genesis empty"; fi
    if ( bench_require_txgen_image ) 2>/dev/null; then echo "    ✓ image pinned: ${BENCH_TXGEN_IMAGE}"
    else echo "    ✗ image: ${BENCH_TXGEN_IMAGE_ERROR:-tag of '${BENCH_TXGEN_IMAGE}' is not blast-v2-<sha>}"; ok=0; fi
    [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] && echo "    ✓ ${BENCH_TXGEN_CLOUDBUILD}" || { echo "    ✗ ${BENCH_TXGEN_CLOUDBUILD} missing (step 1)"; ok=0; }
    [ -f "${BENCH_TXGEN_CONFIG}" ] && echo "    ✓ ${BENCH_TXGEN_CONFIG}" || echo "    · ${BENCH_TXGEN_CONFIG} not present yet (needed by steps 13-14)"
    [ -f "${COLLECT_METRICS_PY}" ] && echo "    ✓ ${COLLECT_METRICS_PY}" || echo "    · ${COLLECT_METRICS_PY} not present yet (needed by step 15)"
    [ "${ok}" -eq 1 ] || echo "    (fix the ✗ items before --yes)"
    echo ""
    echo "DRY RUN — re-run with --yes to execute."
}

# ================================ runner ================================================
if [ -n "${PRINT_POSTCONFIG}" ]; then
    bench_index_of "${PRINT_POSTCONFIG}" >/dev/null || bench_die "${PRINT_POSTCONFIG} is not a bench instance"
    postconfig_script "${PRINT_POSTCONFIG}"
    exit 0
fi
if [ -n "${PRINT_OBS}" ]; then
    _i="$(bench_index_of "${PRINT_OBS}")" || bench_die "${PRINT_OBS} is not a bench instance"
    obs_script "${PRINT_OBS}" "$(tn_region_from_zone "${ZONES[$_i]}")" "PLACEHOLDER-TOKEN"
    exit 0
fi
echo "=========================================="
echo "benchmark deploy — run ${BENCH_RUN_ID}, project ${PROJECT_ID}, chain ${CHAIN_ID}"
echo "=========================================="
if [ "${CONFIRM}" -ne 1 ]; then
    print_plan
    exit 0
fi

# --- fail-fast gate for --yes runs (M1): everything a LATER step needs is checked now, so a
# run cannot die at step 13 an hour after the fleet came up.
in_range() { if [ -n "${ONLY}" ]; then [ "${ONLY}" -eq "$1" ]; else [ "${FROM}" -le "$1" ]; fi; }
gate() {
    echo ">>> gate: prerequisites of the selected steps"
    local deps="${BENCH_DEPLOYMENTS_JSON:-${BENCH_RESULTS_DIR}/deployments-bench.json}" bad=0
    if in_range 1 || in_range 13 || in_range 14; then
        ( bench_require_txgen_image ) || bad=1
        [ -n "${BENCH_TXGEN_IMAGE}" ] && echo "    image ${BENCH_TXGEN_IMAGE}"
    fi
    if in_range 1; then
        [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] && echo "    ✓ ${BENCH_TXGEN_CLOUDBUILD}" || { echo "    ✗ missing ${BENCH_TXGEN_CLOUDBUILD}" >&2; bad=1; }
    fi
    if in_range 13 || in_range 14; then
        [ -f "${BENCH_TXGEN_CONFIG}" ] && echo "    ✓ ${BENCH_TXGEN_CONFIG}" || { echo "    ✗ missing ${BENCH_TXGEN_CONFIG}" >&2; bad=1; }
        if [ "${WITH_CONTRACTS}" -eq 1 ] && in_range 11; then
            echo "    · ${deps} will be produced by step 11"
        elif [ -f "${deps}" ]; then
            echo "    ✓ ${deps}"
        else
            echo "    ✗ missing ${deps} and step 11 will not produce it (pass --with-contracts with a range that includes 11)" >&2; bad=1
        fi
    fi
    [ "${bad}" -eq 0 ] || bench_die "prerequisites missing — nothing was started"
}
gate
bench_manifest_init >/dev/null 2>&1 || true
run_step() {
    local n="$1"
    echo ""
    echo "##########################################"
    "step_${n}"
    bench_manifest_ts "step_${n}_done"
    echo "## step ${n} done"
}
if [ -n "${ONLY}" ]; then
    run_step "${ONLY}"
else
    n="${FROM}"
    while [ "${n}" -le "${LAST_STEP}" ]; do run_step "${n}"; n=$((n + 1)); done
fi
echo ""
echo "=========================================="
echo "benchmark deploy: $([ -n "${ONLY}" ] && echo "step ${ONLY}" || echo "steps ${FROM}..${LAST_STEP}") complete — ${BENCH_RESULTS_DIR}"
echo "=========================================="
