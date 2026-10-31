#!/usr/bin/env bash
#
# devnet-keygen.sh — OPERATOR driver: run tn-node-deployment v2 keygen on every node
# (or a targeted subset) over IAP SSH, then pull each node's node-info.yaml back
# into the local genesis/ tree so devnet-genesis-build.sh can assemble the
# committee.
#
# Per node it runs (as root, on the node), the same for every role (v2 has one entry
# point, setup-node.sh; the role is decided on-chain):
#   sudo bash '${TN_NODE_SCRIPTS_DIR}/setup-node.sh' --json --phase=keygen ... --passphrase-stdin
# v2 keygen creates the service account itself (SERVICE_USER: a system uid with no home
# and no login shell), lays out the data dir and generates the keys. Its --json contract
# puts one JSON event per line on STDOUT and every human-readable line on stderr: stdout
# is captured and judged by its {"event":"done",...} line, stderr goes to the per-run log
# logs/<ts>-keygen/<instance>.log. Then <DATA_DIR>/node-info.yaml (the done line's
# node_info_path) is copied down to genesis/validators/<nodeN>.yaml (validators) or
# genesis/observers/<nodeN>.yaml (node 5). That split follows NODE_ROLES, not the done
# line (v2 reports node_type "observer" for every node): `telcoin genesis` builds the
# committee from every file in genesis/validators/.
#
# Keygen leaves <DATA_DIR>/network-config alone. v2 writes its `hostname:` line only in
# the finalize phase (step_write_config -> write_advertised_name), and does not record
# --advertised-name in .node-meta, so the flag below is accepted and unused at keygen;
# the hostname line appears only if finalize passes it too. devnet-network-config.sh
# installs the file between keygen and finalize, and finalize's edit merges into it.
#
# SECURITY: the BLS keystore passphrase is resolved ONCE up front via
# tn_require_bls_passphrase (TN_BLS_PASSPHRASE > TN_BLS_PASSPHRASE_FILE >
# .secrets/bls-passphrase) and reaches the node on STDIN only: printf (a bash builtin,
# so it is never a process argv) pipes "<passphrase>\n" into tn_iap_ssh_cmd_stdin, and
# setup-node.sh --passphrase-stdin reads that one line. It is never in the remote
# command (remote argv: visible in ps, sudo's log and the ssh audit trail), never in the
# environment handed to gcloud/ssh (unexported below; setup-node.sh also refuses
# TN_BLS_PASSPHRASE and --passphrase-stdin together), never echoed and never in the run
# log. `set -x` is never enabled.
#
# Usage:
#   ./devnet-keygen.sh                  # all nodes
#   ./devnet-keygen.sh node1 node3      # subset by NODE_NAME
#   ./devnet-keygen.sh validator-1-devnet  # subset by INSTANCE_NAME
#   ./devnet-keygen.sh 0 4              # subset by index

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# ----------------------------------------------------------------------------
# Resolve the set of node indices to act on. With no args → every node. With
# args, each may be an index, an INSTANCE_NAME, or a NODE_NAME.
# ----------------------------------------------------------------------------
tn_select_indices() {
    local out=() arg i matched
    if [ "$#" -eq 0 ]; then
        for i in "${!INSTANCE_NAMES[@]}"; do out+=("$i"); done
        printf '%s\n' "${out[@]}"; return 0
    fi
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                out+=("$i"); matched=1; break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME, or NODE_NAME)" >&2
            return 1
        fi
    done
    printf '%s\n' "${out[@]}"
}

# gcloud compute scp in the DOWN direction (remote -> local). tn_iap_scp only
# does local -> remote, so the down-copy is spelled out here.
tn_iap_scp_down() {
    local inst="$1" zone="$2" remote_src="$3" local_dest="$4"
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        # remote -> local: tn_scp rewrites the "NAME:path" src to tnadmin@<overlay-ip>:path.
        tn_scp "${inst}" "${inst}:${remote_src}" "${local_dest}"
    else
        gcloud compute scp "${inst}:${remote_src}" "${local_dest}" \
            --zone="${zone}" --project="${PROJECT_ID}" \
            --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
    fi
}

echo ">>> resolving BLS passphrase (never logged)"
if ! tn_require_bls_passphrase; then
    exit 1
fi
# A shell variable from here on, not an environment variable: tn_require_bls_passphrase
# exports it, and every gcloud/ssh child would inherit it. It travels on stdin only.
export -n TN_BLS_PASSPHRASE

# macOS /bin/bash is 3.2 and lacks `mapfile`; this read-loop is the portable equivalent.
INDICES=()
while IFS= read -r _idx; do INDICES+=("$_idx"); done < <(tn_select_indices "$@")
echo ">>> keygen targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"

# Local collection dirs for the pulled node-info files. GENESIS_WORKSPACE (config.sh)
# is REPO_ROOT for devnet; a profile such as benchmark/ points it at its own tree.
VALIDATORS_LOCAL="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis/validators"
OBSERVERS_LOCAL="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis/observers"
mkdir -p "${VALIDATORS_LOCAL}" "${OBSERVERS_LOCAL}"

# Per-run log: each node's setup-node.sh stderr (its human-readable progress) and the
# JSON events it sent. The passphrase never reaches it (it only rides the ssh stdin).
RUN_LOG_DIR="${REPO_ROOT}/logs/$(date +%Y%m%d_%H%M%S)-keygen"
mkdir -p "${RUN_LOG_DIR}"
echo ">>> per-node logs: ${RUN_LOG_DIR}"

collected=()
failed=()

for i in "${INDICES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    setup="$(tn_setup_script_for_role "${role}")"
    ddir="$(tn_data_dir_for_role "${role}")"
    addr="${EXECUTION_ADDRESSES[$i]}"

    echo ""
    echo ">>> [${node}] keygen on ${inst} (${zone}) role=${role}"

    echo ">>> [${node}] resolving external + internal IP"
    extIP="$(tn_node_ext_ip "${inst}" "${zone}")"
    intIP="$(tn_node_int_ip "${inst}" "${zone}")"
    if [ -z "${extIP}" ] || [ -z "${intIP}" ]; then
        echo "❌ [${node}] could not resolve IPs (ext='${extIP}' int='${intIP}') — skipping"
        failed+=("${node}")
        continue
    fi
    echo ">>> [${node}] extIP=${extIP} intIP=${intIP} addr=${addr}"

    # The keygen args, the same for every role. Multiaddrs use the fixed devnet
    # consensus ports (49590 primary / 49594 worker). --data-dir and --service-user
    # restate v2's defaults (/var/lib/telcoin, telcoin) so config.sh stays the one place
    # that names them; keygen records both in .node-meta for finalize.
    keygen_args=(
        --json
        --phase=keygen
        --network devnet
        --install-method docker
        --docker-image "${DOCKER_IMAGE}"
        # The passphrase arrives on stdin (see SECURITY above); this flag carries no secret.
        --passphrase-stdin
        --address "${addr}"
        --external-primary "/ip4/${extIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --external-worker "/ip4/${extIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --public-ip "${extIP}"
        --data-dir "${ddir}"
        --service-user "${SERVICE_USER}"
        # Accepted but unused at keygen in v2 (see the header): finalize writes the name.
        --advertised-name "${node}"
        # Advertise this node's PUBLIC JSON-RPC endpoints in node-info.yaml. telcoin-network
        # attaches RpcInfo to the WORKER entry only (primary stays null) and publishes it
        # through the kademlia node record, so wallets/dapps can discover where to submit
        # transactions. devnet-genesis-build.sh then carries it from node-info into
        # genesis/committee.yaml, which is what makes it SURVIVE a full redeploy -- the
        # genesis/ files are regenerated every run, so hand-editing them would not.
        # Trailing slash matches how Url serializes (https://host -> https://host/).
        # Both go through Caddy on :443, not reth's loopback 8545/8546.
        --rpc-http "https://${node}.${BASE_DOMAIN}/"
        --rpc-ws "wss://${node}.${BASE_DOMAIN}/"
    )

    # The remote command holds no secret, so it is echoed as is. Every value above comes
    # from config.sh or GCP and has no shell metacharacters: the plain join is the
    # remote argv word for word.
    remote_cmd="sudo bash '${setup}' ${keygen_args[*]}"
    nlog="${RUN_LOG_DIR}/${inst}.log"
    echo ">>> [${node}] running: ${remote_cmd}"
    echo ">>> [${node}] passphrase on stdin; setup-node.sh stderr -> ${nlog}"

    # STDOUT only is captured (the JSON events); stderr is appended to the run log. The
    # exit status is kept, not acted on at once, so the done line can say what failed.
    keygen_rc=0
    keygen_out="$(printf '%s\n' "${TN_BLS_PASSPHRASE}" \
        | tn_iap_ssh_cmd_stdin "${inst}" "${zone}" "${remote_cmd}" 2>>"${nlog}")" || keygen_rc=$?
    [ -n "${keygen_out}" ] && printf '%s\n' "${keygen_out}" >>"${nlog}"
    done_line="$(tn_json_done_line "${keygen_out}")"
    if [ -z "${done_line}" ]; then
        echo "❌ [${node}] keygen sent no done event (rc=${keygen_rc}; ssh failed or dropped?) — see ${nlog}:"
        tail -n 5 "${nlog}" | sed 's/^/      /'
        failed+=("${node}")
        continue
    fi
    if [ "${keygen_rc}" -ne 0 ] || ! tn_json_true "${done_line}" ok; then
        echo "❌ [${node}] keygen failed (rc=${keygen_rc}): $(tn_json_str "${done_line}" msg) — see ${nlog}"
        failed+=("${node}")
        continue
    fi
    echo ">>> [${node}] keygen ok: $(tn_json_str "${done_line}" msg)"

    # node-info.yaml is at <DATA_DIR>/node-info.yaml. The done line names the file keygen
    # wrote; any other path means the node's data dir is not config.sh's, so stop here
    # rather than download a file from somewhere else.
    info_src="${ddir}/node-info.yaml"
    info_path="$(tn_json_str "${done_line}" node_info_path)"
    if [ -n "${info_path}" ] && [ "${info_path}" != "${info_src}" ]; then
        echo "❌ [${node}] keygen wrote ${info_path}, not ${info_src} — not downloading"
        failed+=("${node}")
        continue
    fi

    # Pull node-info.yaml. It is not readable by the SSH user under the data dir, so
    # copy it to /tmp and chown to the SSH user before scp-ing it down.
    tmp_remote="/tmp/${node}.yaml"
    echo ">>> [${node}] staging node-info.yaml for download"
    if ! tn_iap_ssh "${inst}" "${zone}" \
        "sudo cp '${info_src}' '${tmp_remote}' && sudo chown \$(whoami) '${tmp_remote}'"; then
        echo "❌ [${node}] failed to stage node-info.yaml"
        failed+=("${node}")
        continue
    fi

    if [ "${role}" = "observer" ]; then
        local_dest="${OBSERVERS_LOCAL}/${node}.yaml"
    else
        local_dest="${VALIDATORS_LOCAL}/${node}.yaml"
    fi

    echo ">>> [${node}] downloading ${tmp_remote} -> ${local_dest}"
    if tn_iap_scp_down "${inst}" "${zone}" "${tmp_remote}" "${local_dest}"; then
        echo ">>> [${node}] collected node-info -> ${local_dest}"
        collected+=("${local_dest}")
    else
        echo "❌ [${node}] failed to download node-info.yaml"
        failed+=("${node}")
    fi
done

echo ""
echo "========================================="
echo "keygen summary"
echo "========================================="
echo "collected node-info files (${#collected[@]}):"
for f in "${collected[@]}"; do echo "  - ${f}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed nodes (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    echo "per-node logs: ${RUN_LOG_DIR}"
    exit 1
fi
echo "per-node logs: ${RUN_LOG_DIR}"
echo "all targeted nodes keyed and collected. Next: ./devnet-genesis-build.sh"
