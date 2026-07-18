#!/usr/bin/env bash
#
# devnet-lib.sh — shared helpers for the devnet-*.sh per-node driver scripts.
#
# Source it (it sources config.sh for you). By default every node is reached over IAP —
# the always-on `wg-allow-iap-ssh` door (35.235.240.0/20 -> tcp:22) — which works
# post-lockdown and regardless of the wireguard overlay's state.
#
# Break-glass: set TN_SSH_TRANSPORT=overlay to route the per-node ssh/scp helpers over the
# WireGuard overlay instead — for when the IAP transport itself is broken locally (e.g.
# gcloud's bundled lightweight websocket client dropping the tunnel). The overlay path reuses
# tn_ssh/tn_scp from common/wgvpn/lib/wg-ssh-lib.sh, sourced with its TN_USE_VPN=1 gcloud shim
# SUPPRESSED (that shim hijacks every `gcloud compute ssh/scp` and ignores --tunnel-through-iap;
# see tasks/lessons.md). Default (iap) leaves every call site byte-identical.

# Resolve + source config.sh relative to this file (overridable via CONFIG_FILE).
DEVNET_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${CONFIG_FILE:-${DEVNET_LIB_DIR}/config.sh}"

# Transport selector for the per-node helpers below. Default 'iap'; 'overlay' reroutes
# tn_iap_ssh/_stdin/_scp (and devnet-keygen.sh's tn_iap_scp_down) over the WireGuard
# overlay. When overlay, source wg-ssh-lib.sh for tn_ssh/tn_scp/tn_overlay_ip — but with
# its TN_USE_VPN=1 gcloud shim suppressed (save/clear/restore), so the global
# `gcloud compute ssh|scp` shim is NOT installed (it would hijack the REST-only gcloud
# describe/serial calls and ignore --tunnel-through-iap; see tasks/lessons.md).
export TN_SSH_TRANSPORT="${TN_SSH_TRANSPORT:-iap}"
if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
    _tn_save_vpn="${TN_USE_VPN:-}"; TN_USE_VPN=0
    # shellcheck source=/dev/null
    source "${DEVNET_LIB_DIR}/common/wgvpn/lib/wg-ssh-lib.sh"
    TN_USE_VPN="${_tn_save_vpn}"; unset _tn_save_vpn
fi

# Standard SSH flags: IAP tunnel, fail fast, accept new host keys (the fleet is
# re-created, so a pinned known_hosts entry would otherwise block reconnects).
TN_SSH_FLAGS=(--tunnel-through-iap --ssh-flag="-o ConnectTimeout=20" --ssh-flag="-o StrictHostKeyChecking=accept-new")

# tn_iap_ssh <instance> <zone> <remote-command-string>
# Runs one command on the node over IAP. The command string is passed verbatim to
# the remote shell; callers that need sudo should include it in the string.
tn_iap_ssh() {
    local inst="$1" zone="$2" cmd="$3"
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        tn_ssh "${inst}" "${cmd}"
    else
        gcloud compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
            "${TN_SSH_FLAGS[@]}" --command="${cmd}"
    fi
}

# tn_iap_ssh_stdin <instance> <zone>  — pipe a script on stdin to `bash -s` on the
# node (for multi-line remote scripts). Usage: tn_iap_ssh_stdin n z <<'EOF' ... EOF
tn_iap_ssh_stdin() {
    local inst="$1" zone="$2"
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        # tn_ssh forwards stdin when a command is given, so the `... <<EOF` piping pattern works.
        tn_ssh "${inst}" "sudo bash -s"
    else
        gcloud compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
            "${TN_SSH_FLAGS[@]}" --command="sudo bash -s"
    fi
}

# tn_iap_scp <local-src> <instance> <zone> <remote-dest>
tn_iap_scp() {
    local src="$1" inst="$2" zone="$3" dest="$4"
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        # tn_scp rewrites the "NAME:path" token to tnadmin@<overlay-ip>:path; src stays local.
        tn_scp "${inst}" "${src}" "${inst}:${dest}"
    else
        gcloud compute scp "${src}" "${inst}:${dest}" --zone="${zone}" --project="${PROJECT_ID}" \
            --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
    fi
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
tn_data_dir_for_role() { printf '%s' "${VALIDATOR_DATA_DIR}"; }
tn_genesis_dir_for_role() { printf '%s' "${VALIDATOR_GENESIS_DIR}"; }
tn_service_for_role() { printf %s "telcoin"; }

# tn_setup_script_for_role <role> -> the on-node setup script path (in TN_NODE_SCRIPTS_DIR)
tn_setup_script_for_role() {
    [ "$1" = "observer" ] && printf '%s' "${TN_NODE_SCRIPTS_DIR}/setup-observer.sh" \
                          || printf '%s' "${TN_NODE_SCRIPTS_DIR}/setup-validator.sh"
}

# wait_healthy <instance> <zone> <service> — gate a node HEALTHY only when, ON THE NODE,
# the systemd unit is active AND the healthcheck TCP endpoint responds. One SSH round-trip
# per poll, up to HEALTH_TIMEOUT_SECS (default 120) every HEALTH_POLL_SECS (default 5).
#
# Loopback probe (curl 127.0.0.1:${DEFAULT_HEALTHCHECK_TCP_PORT}, matching the UI helper):
# the firewall only admits the Kuma VM / Google HC ranges, so an operator-side EXTERNAL probe
# would be (correctly) blocked — external reachability is confirmed separately via Uptime Kuma
# and `gcloud compute backend-services get-health`. The probe distinguishes "unit not active"
# from "active but port not bound" (the latter is exactly the no-listener bug this gate guards
# against). Returns 1 on timeout. Stricter replacement for the old is-active-only wait.
wait_healthy() {
    local inst="$1" zone="$2" svc="$3"
    local timeout="${HEALTH_TIMEOUT_SECS:-120}" poll="${HEALTH_POLL_SECS:-5}"
    local port="${DEFAULT_HEALTHCHECK_TCP_PORT:-43174}"
    local waited=0 result
    # systemctl + curl run ON THE NODE: escape $ so the command substitution happens remotely;
    # ${svc}/${port} expand locally. The remote always exits 0 (a final echo), so SSH success
    # reflects transport, not node health — which we read from the echoed token instead.
    local remote
    remote="st=\$(systemctl is-active '${svc}' 2>/dev/null); \
if [ \"\$st\" != active ]; then echo \"INACTIVE:\$st\"; \
elif curl -fsS --max-time 3 \"http://127.0.0.1:${port}\" >/dev/null 2>&1; then echo HEALTHY; \
else echo NOLISTEN; fi"
    while [ "${waited}" -lt "${timeout}" ]; do
        result="$(tn_iap_ssh "${inst}" "${zone}" "${remote}" 2>/dev/null || true)"
        result="$(printf '%s' "${result}" | tr -d '[:space:]')"
        case "${result}" in
            *HEALTHY)
                echo "      ✓ ${svc} on ${inst} active AND :${port} responds (after ${waited}s)"
                return 0 ;;
            *INACTIVE:*)
                echo "      …${svc} on ${inst} not active yet (state='${result##*INACTIVE:}', ${waited}s/${timeout}s)" ;;
            *NOLISTEN)
                echo "      …${svc} on ${inst} active but :${port} not responding yet (${waited}s/${timeout}s)" ;;
            *)
                echo "      …${svc} on ${inst} health unknown ('${result:-no-output}', ${waited}s/${timeout}s)" ;;
        esac
        sleep "${poll}"
        waited=$((waited + poll))
    done
    echo "      ❌ ${svc} on ${inst} did not reach HEALTHY (active + :${port} responding) within ${timeout}s" >&2
    return 1
}

# =============================================================================
# Image-only update helpers (devnet-update.sh image mode + devnet-update-all.sh)
#
# The fleet updates docker images through the SAME on-node tooling individual
# operators use: tn-node-deployment/update-node.sh's --json contract. That
# script's json_setup_fds sends newline-delimited JSON to stdout and every
# human-readable line to stderr — so callers must capture STDOUT ONLY for
# parsing and log stderr to the per-run file.
#
# The tn_cmd_* builders expand TN_NODE_SCRIPTS_DIR / DOCKER_IMAGE / SERVICE_USER
# (config.sh) LOCALLY and single-quote them into the remote command string.
# =============================================================================

# tn_cmd_refresh_scripts — remote command: fast-forward the node's
# tn-node-deployment clone to GitHub main, then PROVE the wrapper-aware
# update-node.sh actually landed (marker: TN_UPDATE_VERIFY_TIMEOUT) before any
# caller risks downtime with it. git runs as the clone's owner (SERVICE_USER)
# so root's git doesn't refuse with dubious-ownership; the stash is a safety
# valve for stray on-node edits (never expected — nodes track main; see
# tasks/lessons.md), deliberately `;`-joined so refresh proceeds regardless.
# EVERY command in the chain must be privileged: the SSH login user cannot read
# under /home/telcoin (0750 home dir), so an unprivileged marker grep fails
# with EACCES even after a successful pull (the 2026-07-18 phase-0 false abort).
tn_cmd_refresh_scripts() {
    printf '%s' "sudo -u ${SERVICE_USER} git -C '${TN_NODE_SCRIPTS_DIR}' stash --include-untracked; sudo -u ${SERVICE_USER} git -C '${TN_NODE_SCRIPTS_DIR}' pull --ff-only origin main && sudo -u ${SERVICE_USER} grep -q TN_UPDATE_VERIFY_TIMEOUT '${TN_NODE_SCRIPTS_DIR}/update-node.sh'"
}

# tn_cmd_update_check — remote command: report install method + current/latest
# image tag as one JSON line (keyed by "install_method"). Read-only.
tn_cmd_update_check() {
    printf '%s' "sudo bash '${TN_NODE_SCRIPTS_DIR}/update-node.sh' --json --check"
}

# tn_cmd_update_prepare — remote command: docker-pull DOCKER_IMAGE on the node
# (ZERO downtime; service untouched). Passes the FULL image ref — used verbatim
# by update-node.sh's json_prepare_docker.
tn_cmd_update_prepare() {
    printf '%s' "sudo bash '${TN_NODE_SCRIPTS_DIR}/update-node.sh' --json --prepare --ref '${DOCKER_IMAGE}'"
}

# tn_cmd_update_apply <verify-secs> — remote command: stop → swap image in the
# launch wrapper/unit → restart → on-node health verify within <verify-secs>
# (auto-rollback to the old image if it times out). `sudo env` (the
# devnet-finalize.sh pattern) guarantees the var crosses sudoers env_reset.
tn_cmd_update_apply() {
    printf '%s' "sudo env TN_UPDATE_VERIFY_TIMEOUT=${1} bash '${TN_NODE_SCRIPTS_DIR}/update-node.sh' --json --apply --yes"
}

# --- jq-free parsers for update-node.sh's --json stdout ------------------------
# One self-contained JSON object per line; every value we need is a flat string
# or bare true/false, so grep/sed/case are enough — no jq dependency on the Mac
# driver, and the sed stays BSD-safe. Each helper tolerates "no match" (echoes
# nothing / returns 1) so callers can branch under set -euo pipefail.

# tn_json_done_line <stream> — the LAST terminal {"event":"done",...} line ("" if none).
tn_json_done_line() { printf '%s\n' "$1" | grep '"event":"done"' | tail -1 || true; }

# tn_json_check_line <stream> — the --check result line ("" if none).
tn_json_check_line() { printf '%s\n' "$1" | grep '"install_method"' | tail -1 || true; }

# tn_json_str <line> <key> — the string value of "key":"value" ("" if absent).
tn_json_str() { printf '%s' "$1" | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p"; }

# tn_json_true <line> <key> — 0 iff the line contains "key":true.
tn_json_true() { case "$1" in *"\"$2\":true"*) return 0 ;; *) return 1 ;; esac; }
