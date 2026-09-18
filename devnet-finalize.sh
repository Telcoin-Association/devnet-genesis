#!/usr/bin/env bash
#
# devnet-finalize.sh — OPERATOR driver: stage the assembled genesis on every node
# (or a targeted subset) and run the tn-node-deployment FINALIZE phase, which
# writes the systemd unit and starts the node.
#
# Per node:
#   1. scp committee.yaml + genesis.yaml + parameters.yaml to /tmp, then
#      sudo mv them into the role's genesis dir (root-owned).
#   2. run setup-validator.sh / setup-observer.sh --phase=finalize ... which
#      installs the systemd unit (telcoin) and starts the node.
#
# SECURITY: same as devnet-keygen.sh — the BLS passphrase is resolved once via
# tn_require_bls_passphrase and passed as sudo TN_BLS_PASSPHRASE='...'; it is
# NEVER echoed (command built in a var, redacted form logged, no `set -x`).
#
# Usage:
#   ./devnet-finalize.sh                  # all nodes
#   ./devnet-finalize.sh node1 node3      # subset by NODE_NAME
#   ./devnet-finalize.sh observer-5-devnet  # subset by INSTANCE_NAME
#   ./devnet-finalize.sh 0 4              # subset by index

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# Same selector as devnet-keygen.sh: no args → all nodes; args may be an index,
# an INSTANCE_NAME, or a NODE_NAME.
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

# Local genesis artifacts produced by devnet-genesis-build.sh.
COMMITTEE_LOCAL="${REPO_ROOT}/genesis/committee.yaml"
GENESIS_LOCAL="${REPO_ROOT}/genesis/genesis.yaml"

echo ">>> verifying local genesis artifacts"
for f in "${COMMITTEE_LOCAL}" "${GENESIS_LOCAL}" "${PARAMETERS_FILE}"; do
    if [ ! -f "${f}" ]; then
        echo "❌ missing ${f}. Run ./devnet-genesis-build.sh first." >&2
        exit 1
    fi
done

echo ">>> resolving BLS passphrase (never logged)"
if ! tn_require_bls_passphrase; then
    exit 1
fi

# macOS /bin/bash is 3.2 and lacks `mapfile`; this read-loop is the portable equivalent.
INDICES=()
while IFS= read -r _idx; do INDICES+=("$_idx"); done < <(tn_select_indices "$@")
echo ">>> finalize targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"

finalized=()
failed=()

for i in "${INDICES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    gdir="$(tn_genesis_dir_for_role "${role}")"
    ddir="$(tn_data_dir_for_role "${role}")"
    setup="$(tn_setup_script_for_role "${role}")"
    service="$(tn_service_for_role "${role}")"

    echo ""
    echo ">>> [${node}] finalize on ${inst} (${zone}) role=${role} service=${service}"

    # --- Step 1: stage genesis files ----------------------------------------
    echo ">>> [${node}] staging committee/genesis/parameters to ${gdir}"
    stage_ok=1
    tn_iap_scp "${COMMITTEE_LOCAL}" "${inst}" "${zone}" "/tmp/committee.yaml" || stage_ok=0
    tn_iap_scp "${GENESIS_LOCAL}"   "${inst}" "${zone}" "/tmp/genesis.yaml"   || stage_ok=0
    tn_iap_scp "${PARAMETERS_FILE}" "${inst}" "${zone}" "/tmp/parameters.yaml" || stage_ok=0
    if [ "${stage_ok}" -ne 1 ]; then
        echo "❌ [${node}] failed to scp one or more genesis files"
        failed+=("${node}")
        continue
    fi

    if ! tn_iap_ssh "${inst}" "${zone}" \
        "sudo mkdir -p '${gdir}' && sudo mv /tmp/committee.yaml /tmp/genesis.yaml /tmp/parameters.yaml '${gdir}/' && sudo chown -R root:root '${gdir}'"; then
        echo "❌ [${node}] failed to install genesis files into ${gdir}"
        failed+=("${node}")
        continue
    fi
    echo ">>> [${node}] genesis staged in ${gdir}"

    # The node binds its P2P listeners to the INTERNAL IP (mirrors devnet-keygen.sh's
    # --listener-*). Without these, setup --phase=finalize writes EMPTY
    # PRIMARY/WORKER_LISTENER_MULTIADDR and the node builds a bare /p2p/<peerid> multiaddr
    # -> "Multiaddr is not supported" at epoch start (start_epoch.rs).
    intIP="$(tn_node_int_ip "${inst}" "${zone}")"
    if [ -z "${intIP}" ]; then
        echo "❌ [${node}] could not resolve internal IP for listener multiaddrs"
        failed+=("${node}")
        continue
    fi

    # --- Step 2: finalize (writes systemd unit + starts the node) -----------
    finalize_args=(
        --json
        --phase=finalize
        --network devnet
        --install-method docker
        --docker-image "${DOCKER_IMAGE}"
        --genesis-dir "${gdir}"
        --data-dir "${ddir}"
        --service-user "${SERVICE_USER}"
        # Pass the execution address so setup-node.sh's post-start
        # check_validator_onchain_status actually probes the ConsensusRegistry instead of
        # bailing with "Invalid validator address -- skipping on-chain check". Empty, that
        # probe returns 1, and under setup-node.sh's `set -e` it aborted finalize BEFORE
        # `systemctl enable` -- every node came up active but disabled for boot
        # (devnet genesis reset 2026-09-17). tn-node-deployment now guards the call with
        # `|| true` as well; this makes the check meaningful rather than merely harmless.
        --address "${EXECUTION_ADDRESSES[$i]}"
        # The node's own public, operator-facing endpoints, served by its Caddy edge:
        #   https://node{N}.<domain>  -> reth RPC  :${RPC_PORT} (8545)
        #   wss://node{N}.<domain>    -> reth WS   :${WS_PORT}  (8546)
        # config-caddy.sh already routes both (the @websocket matcher forwards the Upgrade
        # to WS_PORT before the catch-all RPC handler). Recording them in .node-meta means a
        # node knows its OWN reachable addresses -- the UI, operators and tooling no longer
        # have to reconstruct them from a hostname convention. Applies to the observer too,
        # which serves RPC exactly like a validator.
        --public-rpc-url "https://${NODE_NAMES[$i]}.${BASE_DOMAIN}"
        --public-ws-url "wss://${NODE_NAMES[$i]}.${BASE_DOMAIN}"
        --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        # Bake `--healthcheck 43174` into the launch command so the node opens the health
        # listener that Uptime Kuma + the GCP LB probe. Honored by both setup-{validator,observer}.sh
        # (devnet evaluates the opt-in via tn_node_launch_flags' is_testnet_like gate).
        --enable-healthcheck-monitor
    )

    # Passphrase interpolated here — NEVER echo this var; log the redacted twin.
    # `sudo env VAR=...` (see devnet-keygen.sh): guarantees TN_BLS_PASSPHRASE reaches the
    # child regardless of sudoers env_reset/setenv policy; it has no CLI-flag fallback.
    remote_cmd="sudo env TN_BLS_PASSPHRASE='${TN_BLS_PASSPHRASE}' ${setup} ${finalize_args[*]}"
    redacted_cmd="sudo env TN_BLS_PASSPHRASE='***REDACTED***' ${setup} ${finalize_args[*]}"
    echo ">>> [${node}] running: ${redacted_cmd}"

    if tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}"; then
        echo ">>> [${node}] finalize JSON above; service ${service} should be active"
        finalized+=("${node} (${service})")
    else
        echo "❌ [${node}] finalize command failed"
        failed+=("${node}")
    fi
done

echo ""
echo "========================================="
echo "finalize summary"
echo "========================================="
echo "finalized (${#finalized[@]}):"
for n in "${finalized[@]}"; do echo "  - ${n}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    exit 1
fi
echo "all targeted nodes finalized and started."
