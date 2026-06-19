#!/bin/bash
#
# devnet-lib.sh — shared helpers for the devnet-*.sh per-node driver scripts.
#
# Source it (it sources config.sh for you). Every node is reached over IAP — the
# always-on `wg-allow-iap-ssh` door (35.235.240.0/20 -> tcp:22) — which works
# post-lockdown and regardless of the wireguard overlay's state. Do NOT source
# common/wgvpn/lib/wg-ssh-lib.sh from these drivers: its TN_USE_VPN=1 shim ignores
# --tunnel-through-iap and forces the (possibly-down) overlay (see tasks/lessons.md).

# Resolve + source config.sh relative to this file (overridable via CONFIG_FILE).
DEVNET_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${CONFIG_FILE:-${DEVNET_LIB_DIR}/config.sh}"

# Standard SSH flags: IAP tunnel, fail fast, accept new host keys (the fleet is
# re-created, so a pinned known_hosts entry would otherwise block reconnects).
TN_SSH_FLAGS=(--tunnel-through-iap --ssh-flag="-o ConnectTimeout=20" --ssh-flag="-o StrictHostKeyChecking=accept-new")

# tn_iap_ssh <instance> <zone> <remote-command-string>
# Runs one command on the node over IAP. The command string is passed verbatim to
# the remote shell; callers that need sudo should include it in the string.
tn_iap_ssh() {
    local inst="$1" zone="$2" cmd="$3"
    gcloud compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
        "${TN_SSH_FLAGS[@]}" --command="${cmd}"
}

# tn_iap_ssh_stdin <instance> <zone>  — pipe a script on stdin to `bash -s` on the
# node (for multi-line remote scripts). Usage: tn_iap_ssh_stdin n z <<'EOF' ... EOF
tn_iap_ssh_stdin() {
    local inst="$1" zone="$2"
    gcloud compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
        "${TN_SSH_FLAGS[@]}" --command="sudo bash -s"
}

# tn_iap_scp <local-src> <instance> <zone> <remote-dest>
tn_iap_scp() {
    local src="$1" inst="$2" zone="$3" dest="$4"
    gcloud compute scp "${src}" "${inst}:${dest}" --zone="${zone}" --project="${PROJECT_ID}" \
        --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
}

# tn_node_ext_ip / tn_node_int_ip <instance> <zone> — the node's external (static,
# once pinned) and internal IPs, read from GCP (read-only describe).
tn_node_ext_ip() {
    gcloud compute instances describe "$1" --zone="$2" --project="${PROJECT_ID}" \
        --format='value(networkInterfaces[0].accessConfigs[0].natIP)'
}
tn_node_int_ip() {
    gcloud compute instances describe "$1" --zone="$2" --project="${PROJECT_ID}" \
        --format='value(networkInterfaces[0].networkIP)'
}

# tn_region_from_zone <zone> -> region   (us-west2-a -> us-west2)
tn_region_from_zone() { printf '%s' "${1%-*}"; }

# tn_secret <secret-name> — fetch the latest Secret Manager version (e.g. the obs
# ingest token in OBS_SECRET_NAME). Read-only.
tn_secret() {
    gcloud secrets versions access latest --secret="$1" --project="${PROJECT_ID}"
}

# tn_require_bls_passphrase — resolve the BLS keystore passphrase WITHOUT ever
# committing it. Precedence: $TN_BLS_PASSPHRASE (env) > $TN_BLS_PASSPHRASE_FILE >
# ${REPO_ROOT}/.secrets/bls-passphrase (gitignored). Exports TN_BLS_PASSPHRASE.
# Never echo it. Returns 1 (caller should exit) if it cannot be resolved.
tn_require_bls_passphrase() {
    if [ -n "${TN_BLS_PASSPHRASE:-}" ]; then export TN_BLS_PASSPHRASE; return 0; fi
    local f="${TN_BLS_PASSPHRASE_FILE:-${DEVNET_LIB_DIR}/.secrets/bls-passphrase}"
    if [ -f "${f}" ]; then
        TN_BLS_PASSPHRASE="$(cat "${f}")"; export TN_BLS_PASSPHRASE
        [ -n "${TN_BLS_PASSPHRASE}" ] && return 0
    fi
    echo "❌ BLS passphrase not resolved. Set: export TN_BLS_PASSPHRASE=... (or put it in" >&2
    echo "   ${f}, which is gitignored). It is NEVER committed and must stay out of logs." >&2
    return 1
}

# tn_node_role <index> -> validator|observer
tn_node_role() { printf '%s' "${NODE_ROLES[$1]}"; }

# tn_data_dir_for_role <role> / tn_genesis_dir_for_role <role> / tn_service_for_role <role>
tn_data_dir_for_role() { [ "$1" = "observer" ] && printf '%s' "${OBSERVER_DATA_DIR}" || printf '%s' "${VALIDATOR_DATA_DIR}"; }
tn_genesis_dir_for_role() { [ "$1" = "observer" ] && printf '%s' "${OBSERVER_GENESIS_DIR}" || printf '%s' "${VALIDATOR_GENESIS_DIR}"; }
tn_service_for_role() { [ "$1" = "observer" ] && printf '%s' "telcoin-observer" || printf '%s' "telcoin-validator"; }

# tn_setup_script_for_role <role> -> the on-node setup script path (in TN_NODE_SCRIPTS_DIR)
tn_setup_script_for_role() {
    [ "$1" = "observer" ] && printf '%s' "${TN_NODE_SCRIPTS_DIR}/setup-observer.sh" \
                          || printf '%s' "${TN_NODE_SCRIPTS_DIR}/setup-validator.sh"
}
