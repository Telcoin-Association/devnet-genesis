#!/usr/bin/env bash
#
# devnet-keygen.sh — OPERATOR driver: run tn-node-deployment keygen on every node
# (or a targeted subset) over IAP SSH, then pull each node's node-info.yaml back
# into the local genesis/ tree so devnet-genesis-build.sh can assemble the
# committee.
#
# Per node it runs (as root, on the node):
#   setup-validator.sh --phase=keygen ...   (validators)
#   setup-observer.sh  --phase=keygen ...   (observer)
# capturing the JSON the keygen emits, then copies <DATA_DIR>/node-info.yaml down
# to genesis/validators/<nodeN>.yaml (validators) or genesis/observers/<nodeN>.yaml.
#
# SECURITY: the BLS keystore passphrase is resolved ONCE up front via
# tn_require_bls_passphrase and passed to the remote command as
#   sudo TN_BLS_PASSPHRASE='...' <setup> ...
# (sudo keeps the explicit VAR=val on its argv for the root child). It is NEVER
# echoed: the command is built in a variable, `set -x` is never enabled, and the
# logged form is redacted.
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

# macOS /bin/bash is 3.2 and lacks `mapfile`; this read-loop is the portable equivalent.
INDICES=()
while IFS= read -r _idx; do INDICES+=("$_idx"); done < <(tn_select_indices "$@")
echo ">>> keygen targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"

# Local collection dirs for the pulled node-info files.
VALIDATORS_LOCAL="${REPO_ROOT}/genesis/validators"
OBSERVERS_LOCAL="${REPO_ROOT}/genesis/observers"
mkdir -p "${VALIDATORS_LOCAL}" "${OBSERVERS_LOCAL}"

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

    # Build the keygen args common to both roles. Multiaddrs use the fixed
    # devnet consensus ports (49590 primary / 49594 worker).
    keygen_args=(
        --json
        --phase=keygen
        --network devnet
        --install-method docker
        --address "${addr}"
        --external-primary "/ip4/${extIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --external-worker "/ip4/${extIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --public-ip "${extIP}"
        --docker-image "${DOCKER_IMAGE}"
        --data-dir "${ddir}"
        --service-user "${SERVICE_USER}"
        --advertised-name "${node}"
    )

    # The remote command. The passphrase is interpolated here — DO NOT echo this
    # variable. A redacted twin is what we log.
    # `sudo env VAR=...` (NOT bare `sudo VAR=...`): env sets the var explicitly for the
    # child, bypassing sudoers env_reset/setenv policy. Bare `sudo VAR=val` is not
    # guaranteed to forward the var, and TN_BLS_PASSPHRASE has no CLI-flag fallback — a
    # dropped passphrase would silently generate the BLS key under the wrong secret.
    remote_cmd="sudo env TN_BLS_PASSPHRASE='${TN_BLS_PASSPHRASE}' ${setup} ${keygen_args[*]}"
    redacted_cmd="sudo env TN_BLS_PASSPHRASE='***REDACTED***' ${setup} ${keygen_args[*]}"
    echo ">>> [${node}] running: ${redacted_cmd}"

    if tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}"; then
        echo ">>> [${node}] keygen JSON above (emitted on node stdout)"
    else
        echo "❌ [${node}] keygen command failed"
        failed+=("${node}")
        continue
    fi

    # Pull node-info.yaml. It is root-owned under the data dir, so copy it to
    # /tmp and chown to the SSH user before scp-ing it down.
    tmp_remote="/tmp/${node}.yaml"
    echo ">>> [${node}] staging node-info.yaml for download"
    if ! tn_iap_ssh "${inst}" "${zone}" \
        "sudo cp '${ddir}/node-info.yaml' '${tmp_remote}' && sudo chown \$(whoami) '${tmp_remote}'"; then
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
    exit 1
fi
echo "all targeted nodes keyed and collected. Next: ./devnet-genesis-build.sh"
