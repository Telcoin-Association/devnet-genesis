#!/usr/bin/env bash
#
# devnet-lib.sh — shared helpers for the devnet-*.sh per-node driver scripts.
#
# Source it (it sources config.sh for you). By default every node is reached over IAP —
# the always-on `wg-allow-iap-ssh` door (35.235.240.0/20 -> tcp:22) — which works
# post-lockdown and regardless of the wireguard overlay's state.
#
# Node model: tn-node-deployment v2 (mainnet-hardening). Every node is set up by ONE entry
# point, setup-node.sh (setup-validator.sh / setup-observer.sh survive only as deprecated
# shims that exec it; the role is decided on-chain). The service account (SERVICE_USER) is
# a system uid with no home directory and owns no scripts: the node scripts are a
# ROOT-owned checkout at TN_NODE_SCRIPTS_DIR (/opt/telcoin-node-scripts), detached at the
# pinned commit TN_NODE_SCRIPTS_REF, so on-node git and reads there are plain `sudo`.
# Node metadata is /etc/telcoin/.node-meta (root 0600; read it with tn_node_meta_get).
# Secrets reach the node on STDIN only (setup-node.sh --passphrase-stdin,
# setup-observability.sh --token-stdin, via tn_iap_ssh_cmd_stdin), never in a command
# string or the environment; tn_secret_set stores one in Secret Manager from stdin.
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

# _tn_require_cmd <caller> <remote-command-string> — refuse an EMPTY remote command:
# `gcloud compute ssh --command=""` (and `ssh host ""`) opens an interactive login shell
# instead, which is what `tn_iap_ssh n z "$(tn_cmd_refresh_scripts)"` would get if the
# builder failed. Message on stderr, rc 1.
_tn_require_cmd() {
    [ -n "${2:-}" ] && return 0
    echo "❌ $1: empty remote command refused (it would open an interactive login shell)" >&2
    return 1
}

# IAP transport faults are retried. TN_IAP_RETRIES (default 2) extra attempts when a
# gcloud call fails with ssh rc 255 (IAP refused the tunnel, or the session dropped) or
# crashes (rc 1 with "gcloud crashed" on stderr: a compute API ReadTimeout), with
# TN_IAP_RETRY_SECS (5) between attempts; 0 disables (the pre-2026-11-03 behaviour).
# Everything the drivers send is idempotent or self-guarding (v2 keygen and finalize
# refuse over an existing install; finalize's start-at probe records its first start;
# installs, reads and systemctl stop/start repeat harmlessly), so re-sending a command
# after a drop cannot do more than the first attempt did. stderr is buffered per attempt
# so the crash can be recognised, and replayed to the caller's stderr after each attempt.
# The caller's stdin, when forwarded, is buffered in a shell variable (never a file or
# argv) so every attempt receives the same bytes. bench 3, 2026-11-03: three faults in
# ~70 sessions, each ending a 10-minute step. Each failure is named by tn_iap_fault_kind:
# only `transport` is retried. An expired gcloud login (`reauth`) is never retried, since
# every later call fails the same way: it gets one ❌ line naming the fix, then the rc.
#
# tn_iap_fault_kind <rc> <stderr-file> — one word on stdout, always rc 0:
#   ok           rc 0
#   reauth       stderr matches TN_IAP_REAUTH_PAT (an ERE; default: the gcloud reauth and
#                token-refresh failures), whatever the rc. The default leaves out a bare
#                "gcloud auth login": a remote command's own stderr can print that hint, and
#                gcloud's real failure always carries one of the three phrases as well
#   transport    ssh rc 255 or "gcloud crashed" on stderr (the retry condition above)
#   iap-refused  an IAP tunnel refusal under another rc: [4003: 'failed to connect to
#                backend'], [4033: 'not authorized'], [4047: ...] (bench_iap_scp_down's matcher)
#   other        anything else: the remote command's own failure, a missing instance, ...
# Checked in that order, so an rc-255 refusal is `transport`. A missing or unreadable
# stderr file reads as empty, and a non-numeric rc as a plain failure.
tn_iap_fault_kind() {
    case "${1:-}" in 0) echo ok; return 0 ;; ''|*[!0-9]*) set -- 1 "${2:-}" ;; esac
    [ -r "${2:-}" ] || set -- "$1" /dev/null
    grep -Eq -- "${TN_IAP_REAUTH_PAT:-Reauthentication failed|There was a problem refreshing your current auth tokens|invalid_grant}" "$2" && { echo reauth; return 0; }
    { [ "$1" -eq 255 ] || grep -q 'gcloud crashed' "$2"; } && { echo transport; return 0; }
    grep -Eq '\[(4003|4033|4047): |failed to connect to backend' "$2" && { echo iap-refused; return 0; }
    echo other
}

_tn_iap_retry() {   # _tn_iap_retry <label> <stdin: 0|1> <gcloud args...>
    local label="$1" use_stdin="$2" rc attempt=0 errf data="" kind
    shift 2
    if [ "${use_stdin}" = 1 ]; then data="$(cat; printf x)"; data="${data%x}"; fi
    errf="$(mktemp)" || return 1
    while :; do
        if [ "${use_stdin}" = 1 ]; then
            printf '%s' "${data}" | gcloud "$@" 2>"${errf}"; rc=$?
        else
            gcloud "$@" 2>"${errf}" </dev/null; rc=$?
        fi
        cat "${errf}" >&2
        kind="$(tn_iap_fault_kind "${rc}" "${errf}")"
        if [ "${kind}" = reauth ]; then
            echo "❌ ${label}: gcloud needs re-authentication (run: gcloud auth login) — not retried" >&2
            break
        fi
        if [ "${rc}" -eq 0 ] || [ "${attempt}" -ge "${TN_IAP_RETRIES:-2}" ]; then break; fi
        if [ "${kind}" = transport ]; then
            attempt=$((attempt + 1))
            echo "⚠️  ${label}: transport fault (rc ${rc}) — retry ${attempt}/${TN_IAP_RETRIES:-2} in ${TN_IAP_RETRY_SECS:-5} s" >&2
            sleep "${TN_IAP_RETRY_SECS:-5}"
            continue
        fi
        break
    done
    rm -f "${errf}"
    return "${rc}"
}

# tn_iap_ssh <instance> <zone> <remote-command-string>
# Runs one command on the node over IAP. The command string is passed verbatim to
# the remote shell; callers that need sudo should include it in the string. An empty
# command string is refused (see _tn_require_cmd).
tn_iap_ssh() {
    local inst="$1" zone="$2" cmd="${3:-}"
    _tn_require_cmd tn_iap_ssh "${cmd}" || return 1
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        tn_ssh "${inst}" "${cmd}"
    else
        _tn_iap_retry "tn_iap_ssh ${inst}" 0 compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
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
        _tn_iap_retry "tn_iap_ssh_stdin ${inst}" 1 compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
            "${TN_SSH_FLAGS[@]}" --ssh-flag="-T" --command="sudo bash -s"
    fi
}

# tn_iap_ssh_cmd_stdin <instance> <zone> <remote-command-string> — run ONE command on the
# node with the CALLER'S stdin forwarded to it, for v2's secret-on-stdin flags
# (setup-node.sh --passphrase-stdin, setup-observability.sh --token-stdin). The caller
# pipes the secret in; it NEVER goes in the command string (that is remote argv: visible
# in ps, sudo's log and the ssh audit trail), NEVER in the environment, and is never
# echoed:
#   printf '%s\n' "${TN_BLS_PASSPHRASE}" | tn_iap_ssh_cmd_stdin "${inst}" "${zone}" \
#       "sudo bash '${TN_NODE_SCRIPTS_DIR}/setup-node.sh' --json ... --passphrase-stdin"
# Both v2 readers take one line, with or without the trailing newline, and drop one CR.
# Transport as tn_iap_ssh: gcloud hands its stdin to ssh (tn_iap_ssh_stdin relies on
# exactly that for `bash -s`), and the overlay's tn_ssh forwards stdin when given a
# command. Unlike tn_iap_ssh_stdin, the remote command is the caller's (no implied
# `sudo bash -s`). Empty command refused, as tn_iap_ssh.
tn_iap_ssh_cmd_stdin() {
    local inst="$1" zone="$2" cmd="${3:-}"
    _tn_require_cmd tn_iap_ssh_cmd_stdin "${cmd}" || return 1
    # -T: never allocate a remote pty for a call that carries a secret on stdin. ssh skips
    # the pty for a command anyway, but an operator ~/.ssh/config with `RequestTTY force`
    # would otherwise echo the piped bytes back into the captured stdout (R3 review).
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        tn_ssh "${inst}" "${cmd}"
    else
        _tn_iap_retry "tn_iap_ssh_cmd_stdin ${inst}" 1 compute ssh "${inst}" --zone="${zone}" --project="${PROJECT_ID}" \
            "${TN_SSH_FLAGS[@]}" --ssh-flag="-T" --command="${cmd}"
    fi
}

# tn_iap_scp <local-src> <instance> <zone> <remote-dest>
tn_iap_scp() {
    local src="$1" inst="$2" zone="$3" dest="$4"
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        # tn_scp rewrites the "NAME:path" token to tnadmin@<overlay-ip>:path; src stays local.
        tn_scp "${inst}" "${src}" "${inst}:${dest}"
    else
        _tn_iap_retry "tn_iap_scp ${inst}" 0 compute scp "${src}" "${inst}:${dest}" --zone="${zone}" --project="${PROJECT_ID}" \
            --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
    fi
}

# tn_node_ext_ip / tn_node_int_ip <instance> <zone> — the node's external (static,
# once pinned) and internal IPs, read from GCP (read-only describe). Through _tn_iap_retry
# (stdin closed): a `gcloud crashed (ReadTimeout)` on the describe is a transport fault that
# ended a whole finalize/keygen run under `set -e` in bench 3 (D4/D5).
tn_node_ext_ip() {
    _tn_iap_retry "tn_node_ext_ip $1" 0 compute instances describe "$1" --zone="$2" --project="${PROJECT_ID}" \
        --format='value(networkInterfaces[0].accessConfigs[0].natIP)'
}
tn_node_int_ip() {
    _tn_iap_retry "tn_node_int_ip $1" 0 compute instances describe "$1" --zone="$2" --project="${PROJECT_ID}" \
        --format='value(networkInterfaces[0].networkIP)'
}

# tn_region_from_zone <zone> -> region   (us-west2-a -> us-west2)
tn_region_from_zone() { printf '%s' "${1%-*}"; }

# tn_secret <secret-name> — fetch the latest Secret Manager version (e.g. the obs
# ingest token in OBS_SECRET_NAME). Read-only.
tn_secret() {
    gcloud secrets versions access latest --secret="$1" --project="${PROJECT_ID}"
}

# tn_secret_set <secret-name> — store STDIN as the newest version of a Secret Manager
# secret, creating the secret first (automatic replication) when it does not exist. The
# VALUE comes from stdin only (never argv or env) and is never echoed; gcloud reads it
# straight from the pipe (--data-file=-), so this helper never holds it in a variable:
#   printf '%s' "${value}" | tn_secret_set "${NAME}"
# The bytes are stored exactly as piped (printf '%s': no trailing newline, which is what
# tn_secret then reads back). Refuses a terminal on stdin (an interactively typed value
# would echo). describe/create read </dev/null, so no gcloud prompt can swallow the value
# meant for `versions add`. rc 1 on any failure.
tn_secret_set() {
    local name="${1:-}"
    if [ -z "${name}" ]; then
        echo "❌ tn_secret_set: secret name required (pipe the value on stdin)" >&2
        return 1
    fi
    if [ -t 0 ]; then
        echo "❌ tn_secret_set: stdin is a terminal; pipe the value in (printf '%s' \"\$v\" | tn_secret_set ${name})" >&2
        return 1
    fi
    if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1 </dev/null; then
        gcloud secrets create "${name}" --replication-policy=automatic \
            --project="${PROJECT_ID}" </dev/null || return 1
    fi
    gcloud secrets versions add "${name}" --data-file=- --project="${PROJECT_ID}" || return 1
}

# tn_require_bls_passphrase — resolve the BLS keystore passphrase WITHOUT ever
# committing it. Precedence: $TN_BLS_PASSPHRASE (already set) > $TN_BLS_PASSPHRASE_FILE >
# ${REPO_ROOT}/.secrets/bls-passphrase (gitignored). Leaves it as a plain SHELL variable:
# it is never exported, and an inherited export is removed, so no child process (gcloud,
# ssh, docker, cast, python3) sees it in its environment. Callers hand it to the node on
# stdin (printf | tn_iap_ssh_cmd_stdin) or to the genesis container's stdin. Never echo
# it. Returns 1 (caller should exit) if it cannot be resolved.
tn_require_bls_passphrase() {
    if [ -n "${TN_BLS_PASSPHRASE:-}" ]; then export -n TN_BLS_PASSPHRASE; return 0; fi
    local f="${TN_BLS_PASSPHRASE_FILE:-${DEVNET_LIB_DIR}/.secrets/bls-passphrase}"
    if [ -f "${f}" ]; then
        TN_BLS_PASSPHRASE="$(cat "${f}")"; export -n TN_BLS_PASSPHRASE
        [ -n "${TN_BLS_PASSPHRASE}" ] && return 0
    fi
    echo "❌ BLS passphrase not resolved. Put it in ${f} (gitignored, mode 0600) or point" >&2
    echo "   TN_BLS_PASSPHRASE_FILE at such a file. Do NOT export it from your shell: every" >&2
    echo "   driver and its gcloud/docker/cast children would inherit it. Never log it." >&2
    return 1
}

# tn_node_role <index> -> the entry's NODE_ROLES value, one of four roles:
#   validator  genesis committee member (runs a node)
#   observer   node 5: runs a node outside the genesis committee, staked after genesis
#   rpc        public RPC node: runs a node, never stakes, admission Open
#   gateway    runs no node and holds no keys, only the worker gateway of the node its
#              GATEWAY_FOR entry names
tn_node_role() { printf '%s' "${NODE_ROLES[$1]}"; }

# tn_data_dir_for_role <role> / tn_genesis_dir_for_role <role> / tn_service_for_role <role>
tn_data_dir_for_role() { printf '%s' "${VALIDATOR_DATA_DIR}"; }
tn_genesis_dir_for_role() { printf '%s' "${VALIDATOR_GENESIS_DIR}"; }
tn_service_for_role() { printf %s "telcoin"; }

# tn_setup_script_for_role <role> -> the on-node setup script path (in TN_NODE_SCRIPTS_DIR).
# v2 has one setup entry point for every role, setup-node.sh (setup-validator.sh and
# setup-observer.sh are deprecated shims that exec it). The role argument is accepted, so
# call sites stay unchanged, and ignored.
tn_setup_script_for_role() {
    printf '%s' "${TN_NODE_SCRIPTS_DIR}/setup-node.sh"
}

# --- Fleet topology (launch 2) ---------------------------------------------------------------
# An index is a position in config.sh's PARALLEL fleet arrays (INSTANCE_NAMES, NODE_ROLES, ZONES,
# NODE_NAMES, EXECUTION_ADDRESSES, STATIC_IP_NAMES, GATEWAY_MODES, GATEWAY_FOR); roles: see
# tn_node_role. These are pure lookups over the arrays (bash 3.2 safe): none of them calls gcloud
# except tn_internal_ip / tn_external_ip. A helper that prints a value prints one line.

# _tn_index_ok <i> — rc 0 when i is a plain decimal index (no sign, no leading zero) with a
# NODE_ROLES entry, else rc 1. No output. Guards every subscript below (bash evaluates a
# non-numeric subscript arithmetically: "x" would silently mean index 0).
_tn_index_ok() {
    case "${1:-}" in
        ''|*[!0-9]*|0?*) return 1 ;;
    esac
    [ -n "${NODE_ROLES[$1]+set}" ]
}

# _tn_index_of_node_name <name> — prints the index of the node-running entry (validator, observer,
# rpc) whose NODE_NAMES value is <name>; rc 1, no output, when there is none.
_tn_index_of_node_name() {
    local i
    [ -n "${1:-}" ] || return 1
    for i in "${!NODE_ROLES[@]}"; do
        if [ "${NODE_NAMES[$i]:-}" = "$1" ] && tn_is_node_index "${i}"; then
            printf '%s\n' "${i}"
            return 0
        fi
    done
    return 1
}

# _tn_gateway_entry_for <i> — prints the index of the first `gateway` entry whose GATEWAY_FOR
# names node i's NODE_NAMES value; rc 1, no output, when there is none.
_tn_gateway_entry_for() {
    local j name="${NODE_NAMES[$1]:-}"
    [ -n "${name}" ] || return 1
    for j in "${!NODE_ROLES[@]}"; do
        if [ "${NODE_ROLES[$j]}" = "gateway" ] && [ "${GATEWAY_FOR[$j]:-}" = "${name}" ]; then
            printf '%s\n' "${j}"
            return 0
        fi
    done
    return 1
}

# _tn_fleet_len <array name> <its length> <INSTANCE_NAMES length> — tn_fleet_check's length
# test: rc 0 when equal, else one line on stderr and rc 1.
_tn_fleet_len() {
    [ "$2" -eq "$3" ] && return 0
    echo "❌ tn_fleet_check: $1 has $2 entries, INSTANCE_NAMES has $3" >&2
    return 1
}

# tn_fleet_check — validate the fleet arrays; drivers call it first. No arguments, no stdout.
#   rc 0  consistent
#   rc 1  one line per problem on stderr: an array whose length differs from INSTANCE_NAMES
#         (NODE_ROLES, ZONES, NODE_NAMES, EXECUTION_ADDRESSES; STATIC_IP_NAMES when
#         USE_STATIC_IPS is on; GATEWAY_MODES and GATEWAY_FOR when TN_GATEWAY_ENABLE=1), a role
#         other than validator|observer|rpc|gateway, and, only when TN_GATEWAY_ENABLE=1: a mode
#         other than same-host|standalone|none, a mode other than `none` on an rpc or gateway
#         entry, a `standalone` node without exactly one `gateway` entry naming it in
#         GATEWAY_FOR, a `gateway` entry naming no node or a node whose mode is not standalone.
tn_fleet_check() {
    local rc=0 n i j k role mode target hits
    n="${#INSTANCE_NAMES[@]}"
    _tn_fleet_len NODE_ROLES "${#NODE_ROLES[@]}" "${n}" || rc=1
    _tn_fleet_len ZONES "${#ZONES[@]}" "${n}" || rc=1
    _tn_fleet_len NODE_NAMES "${#NODE_NAMES[@]}" "${n}" || rc=1
    _tn_fleet_len EXECUTION_ADDRESSES "${#EXECUTION_ADDRESSES[@]}" "${n}" || rc=1
    # Same truthiness test as common/create-instances.sh and common/reserve-static-ips.sh.
    case "$(printf '%s' "${USE_STATIC_IPS:-0}" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) _tn_fleet_len STATIC_IP_NAMES "${#STATIC_IP_NAMES[@]}" "${n}" || rc=1 ;;
    esac
    for i in "${!NODE_ROLES[@]}"; do
        role="${NODE_ROLES[$i]}"
        case "${role}" in
            validator|observer|rpc|gateway) ;;
            *) echo "❌ tn_fleet_check: index ${i} (${INSTANCE_NAMES[$i]:-?}): unknown role '${role}' (validator|observer|rpc|gateway)" >&2; rc=1 ;;
        esac
    done
    [ "${TN_GATEWAY_ENABLE:-0}" = "1" ] || return "${rc}"
    _tn_fleet_len GATEWAY_MODES "${#GATEWAY_MODES[@]}" "${n}" || rc=1
    _tn_fleet_len GATEWAY_FOR "${#GATEWAY_FOR[@]}" "${n}" || rc=1
    for i in "${!NODE_ROLES[@]}"; do
        role="${NODE_ROLES[$i]}"
        mode="${GATEWAY_MODES[$i]:-none}"
        case "${mode}" in
            same-host|standalone|none) ;;
            *) echo "❌ tn_fleet_check: index ${i} (${INSTANCE_NAMES[$i]:-?}): unknown gateway mode '${mode}' (same-host|standalone|none)" >&2; rc=1; continue ;;
        esac
        case "${role}" in
            rpc|gateway)
                if [ "${mode}" != "none" ]; then
                    echo "❌ tn_fleet_check: index ${i} (${INSTANCE_NAMES[$i]:-?}): role ${role} needs gateway mode none, not '${mode}'" >&2; rc=1
                fi ;;
            validator|observer)
                if [ "${mode}" = "standalone" ]; then
                    hits=0
                    for j in "${!NODE_ROLES[@]}"; do
                        if [ "${NODE_ROLES[$j]}" = "gateway" ] && [ "${GATEWAY_FOR[$j]:-}" = "${NODE_NAMES[$i]:-}" ]; then
                            hits=$((hits + 1))
                        fi
                    done
                    if [ "${hits}" -ne 1 ]; then
                        echo "❌ tn_fleet_check: index ${i} (${INSTANCE_NAMES[$i]:-?}): gateway mode standalone needs exactly one gateway entry with GATEWAY_FOR=${NODE_NAMES[$i]:-?}, found ${hits}" >&2; rc=1
                    fi
                fi ;;
        esac
        if [ "${role}" = "gateway" ]; then
            target="${GATEWAY_FOR[$i]:-}"
            if ! k="$(_tn_index_of_node_name "${target}")"; then
                echo "❌ tn_fleet_check: index ${i} (${INSTANCE_NAMES[$i]:-?}): gateway entry names no node (GATEWAY_FOR='${target}')" >&2; rc=1
            elif [ "${GATEWAY_MODES[$k]:-none}" != "standalone" ]; then
                echo "❌ tn_fleet_check: index ${i} (${INSTANCE_NAMES[$i]:-?}): gateway entry fronts ${target}, whose gateway mode is '${GATEWAY_MODES[$k]:-none}', not standalone" >&2; rc=1
            fi
        fi
    done
    return "${rc}"
}

# tn_indices_by_role <role>[,<role>...] — prints, one per line in array order, every index whose
# NODE_ROLES value is one of the comma-separated roles. rc 0 (also when nothing matches); rc 1
# with a message on stderr when no role is given.
tn_indices_by_role() {
    local want i
    if [ -z "${1:-}" ]; then
        echo "❌ tn_indices_by_role: a role list is required (e.g. validator,observer)" >&2
        return 1
    fi
    want=",$1,"
    for i in "${!NODE_ROLES[@]}"; do
        [ -n "${NODE_ROLES[$i]}" ] || continue
        case "${want}" in
            *",${NODE_ROLES[$i]},"*) printf '%s\n' "${i}" ;;
        esac
    done
    return 0
}

# tn_node_indices — prints, one per line, the indices of the hosts that run a node (roles
# validator, observer, rpc; never a gateway entry). rc 0.
tn_node_indices() { tn_indices_by_role validator,observer,rpc; }

# tn_is_node_index <i> — rc 0 when entry i runs a node (validator, observer, rpc), rc 1 otherwise
# (a gateway entry, an unknown role, no such index). No output.
tn_is_node_index() {
    _tn_index_ok "${1:-}" || return 1
    case "${NODE_ROLES[$1]}" in
        validator|observer|rpc) return 0 ;;
    esac
    return 1
}

# tn_internal_ip <i> / tn_external_ip <i> — entry i's internal / external IP read from GCP,
# through tn_node_int_ip / tn_node_ext_ip (read-only describe with their retry). Prints the IP;
# rc 1 with a message on stderr for a bad index, else the lookup's rc.
tn_internal_ip() {
    _tn_index_ok "${1:-}" || { echo "❌ tn_internal_ip: no fleet entry at index '${1:-}'" >&2; return 1; }
    tn_node_int_ip "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}"
}
tn_external_ip() {
    _tn_index_ok "${1:-}" || { echo "❌ tn_external_ip: no fleet entry at index '${1:-}'" >&2; return 1; }
    tn_node_ext_ip "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}"
}

# tn_gateway_mode <i> — prints entry i's worker-gateway mode: same-host, standalone or none.
# `none` when TN_GATEWAY_ENABLE is not 1, or the entry is missing or empty. rc 0. (Any other
# stored value is printed as is; tn_fleet_check rejects it.)
tn_gateway_mode() {
    if [ "${TN_GATEWAY_ENABLE:-0}" != "1" ] || ! _tn_index_ok "${1:-}"; then
        printf 'none\n'
        return 0
    fi
    printf '%s\n' "${GATEWAY_MODES[$1]:-none}"
}

# tn_gateway_host_index <i> — for node index i, prints the index of the host that runs its
# gateway: i itself for same-host, the `gateway` entry whose GATEWAY_FOR names node i for
# standalone. rc 1, no output, when node i has no gateway (mode none, gateways disabled, not a
# node index, or a standalone node with no gateway entry).
tn_gateway_host_index() {
    tn_is_node_index "${1:-}" || return 1
    case "$(tn_gateway_mode "$1")" in
        same-host) printf '%s\n' "$1" ;;
        standalone) _tn_gateway_entry_for "$1" ;;
        *) return 1 ;;
    esac
}

# tn_public_domain <i> — prints the public domain entry i serves: <NODE_NAME>.<BASE_DOMAIN> for a
# validator or observer, RPC_HOSTNAME for rpc, and for a gateway entry the domain of the node its
# GATEWAY_FOR names. rc 1 with a message on stderr when there is none (bad index, unknown role,
# a gateway entry naming no node).
tn_public_domain() {
    local k
    _tn_index_ok "${1:-}" || { echo "❌ tn_public_domain: no fleet entry at index '${1:-}'" >&2; return 1; }
    case "${NODE_ROLES[$1]}" in
        validator|observer) printf '%s.%s\n' "${NODE_NAMES[$1]}" "${BASE_DOMAIN}" ;;
        rpc) printf '%s\n' "${RPC_HOSTNAME}" ;;
        gateway)
            if ! k="$(_tn_index_of_node_name "${GATEWAY_FOR[$1]:-}")"; then
                echo "❌ tn_public_domain: gateway entry ${INSTANCE_NAMES[$1]:-$1} names no node (GATEWAY_FOR='${GATEWAY_FOR[$1]:-}')" >&2
                return 1
            fi
            tn_public_domain "${k}" ;;
        *) echo "❌ tn_public_domain: index $1 has unknown role '${NODE_ROLES[$1]}'" >&2; return 1 ;;
    esac
}

# tn_admin_domain <i> — prints admin.<NODE_NAME>.<BASE_DOMAIN> for a node host that runs Caddy:
# an rpc entry, or a validator/observer whose gateway mode is same-host. rc 1, no output,
# otherwise (standalone-fronted or mode-none node, gateway entry, bad index).
tn_admin_domain() {
    tn_is_node_index "${1:-}" || return 1
    if [ "${NODE_ROLES[$1]}" != "rpc" ] && [ "$(tn_gateway_mode "$1")" != "same-host" ]; then
        return 1
    fi
    printf 'admin.%s.%s\n' "${NODE_NAMES[$1]}" "${BASE_DOMAIN}"
}

# tn_admission_mode <i> — prints the node's admission mode for setup-node.sh --admission: closed
# for a validator or observer, open for rpc. rc 1 with a message on stderr for any other entry.
tn_admission_mode() {
    if tn_is_node_index "${1:-}"; then
        case "${NODE_ROLES[$1]}" in
            validator|observer) printf 'closed\n'; return 0 ;;
            rpc) printf 'open\n'; return 0 ;;
        esac
    fi
    echo "❌ tn_admission_mode: index '${1:-}' runs no node" >&2
    return 1
}

# tn_role_dir <i> — prints the genesis/ subdirectory that holds the node's node-info: validators
# for a validator, observers for an observer or rpc. rc 1 with a message on stderr for any other
# entry.
tn_role_dir() {
    if tn_is_node_index "${1:-}"; then
        case "${NODE_ROLES[$1]}" in
            validator) printf 'validators\n'; return 0 ;;
            observer|rpc) printf 'observers\n'; return 0 ;;
        esac
    fi
    echo "❌ tn_role_dir: index '${1:-}' runs no node" >&2
    return 1
}

# tn_node_meta_get <instance> <zone> <KEY> — print KEY's value from the node's
# /etc/telcoin/.node-meta, read with sudo over tn_iap_ssh. v2 writes that file root 0600
# as unquoted KEY=VALUE lines (lib/common.sh meta_set); the value is everything after the
# first '=', with any CR dropped, as v2's meta_get reads it. Keys setup-node.sh records
# include HOST_SERVICE_USER, HOST_SERVICE_GROUP, DATA_DIR, NETWORK, INSTALL_METHOD,
# DOCKER_IMAGE, DOCKER_IMAGE_DIGEST, RELEASE_TAG, RPC_PORT, WS_PORT, PASSPHRASE_METHOD,
# VALIDATOR_ADDRESS, LOG_TARGET, NODE_LOG_DIR (no NODE_TYPE: the role is on-chain).
#   rc 0  value printed (possibly empty, for a `KEY=` line)
#   rc 1  nothing printed: KEY is not in the file, or the node has no readable .node-meta
#   rc 2  nothing printed: the node did not answer, KEY is set more than once (no single
#         value, as meta_get), or KEY is not ^[A-Z][A-Z0-9_]*$
# The remote grep's rc travels back on a sentinel line, so an unreachable node is never
# mistaken for an absent key.
tn_node_meta_get() {
    local inst="$1" zone="$2" key="${3:-}" meta="/etc/telcoin/.node-meta"
    local remote out rc lines nl=$'\n'
    case "${key}" in
        ""|[!ABCDEFGHIJKLMNOPQRSTUVWXYZ]*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]*)
            echo "❌ tn_node_meta_get: bad key '${key}' (expected ^[A-Z][A-Z0-9_]*$)" >&2
            return 2 ;;
    esac
    # grep + `$?` run ON THE NODE (escaped); ${key}/${meta} expand locally. </dev/null:
    # a getter must not eat the caller's stdin (e.g. a `while read` loop over nodes).
    remote="sudo grep -E '^${key}=' '${meta}' 2>/dev/null; echo \"__tn_meta_rc=\$?\""
    if ! out="$(tn_iap_ssh "${inst}" "${zone}" "${remote}" </dev/null)"; then
        echo "❌ tn_node_meta_get: could not read ${key} from ${inst} (ssh failed)" >&2
        return 2
    fi
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    case "${out}" in
        *__tn_meta_rc=*) rc="${out##*__tn_meta_rc=}" ;;
        *) echo "❌ tn_node_meta_get: no answer from ${inst} reading ${key}" >&2; return 2 ;;
    esac
    case "${rc}" in
        0) ;;
        1) return 1 ;;
        *) echo "⚠️  tn_node_meta_get: no readable ${meta} on ${inst}" >&2; return 1 ;;
    esac
    lines="$(printf '%s\n' "${out}" | grep -E "^${key}=" || true)"
    case "${lines}" in
        "") echo "❌ tn_node_meta_get: ${inst} matched ${key} but sent no ${key}= line" >&2; return 2 ;;
        *"${nl}"*) echo "❌ tn_node_meta_get: ${key} is set more than once in ${inst}:${meta}; no single value" >&2; return 2 ;;
    esac
    printf '%s\n' "${lines#*=}"
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
# The tn_cmd_* builders expand TN_NODE_SCRIPTS_DIR / TN_NODE_SCRIPTS_REF / DOCKER_IMAGE
# (config.sh) LOCALLY and single-quote them into the remote command string.
# =============================================================================

# tn_cmd_refresh_scripts — remote command: move the node's tn-node-deployment checkout
# to the pinned commit TN_NODE_SCRIPTS_REF (config.sh), then PROVE the wrapper-aware
# update-node.sh is what landed (marker: TN_UPDATE_VERIFY_TIMEOUT) before any caller
# risks downtime with it.
#
# v2 model: the checkout at TN_NODE_SCRIPTS_DIR (/opt/telcoin-node-scripts) is ROOT-owned
# and detached at a full commit sha; the service account is a system uid that owns no
# scripts. So every step is plain `sudo` (root owns the repo: no dubious-ownership
# refusal, no `sudo -u`), and the fetch names the exact sha, never a moving branch: the
# fleet runs only the reviewed commit. No stash: nothing edits the root-owned scripts on
# the node, and if something ever does, `checkout --detach` refuses to overwrite a changed
# file and the refresh fails loudly instead of discarding it. `&&`-joined, so any failed
# step fails the whole command (non-zero over ssh).
#
# Prints nothing and returns 1 (message on stderr) unless TN_NODE_SCRIPTS_REF is a full
# 40-hex commit sha: empty means config.sh pinned nothing, a short sha cannot be fetched
# by name, and the value lands in a root command. Build the string first so that stops
# the caller (tn_iap_ssh also refuses the empty string an inline "$(...)" would pass):
#   cmd="$(tn_cmd_refresh_scripts)" || exit 1; tn_iap_ssh "${inst}" "${zone}" "${cmd}"
tn_cmd_refresh_scripts() {
    local ref="${TN_NODE_SCRIPTS_REF:-}" dir="${TN_NODE_SCRIPTS_DIR}"
    case "${ref}" in
        *[!0123456789abcdef]*) ref="" ;;
    esac
    if [ "${#ref}" -ne 40 ]; then
        echo "❌ tn_cmd_refresh_scripts: TN_NODE_SCRIPTS_REF='${TN_NODE_SCRIPTS_REF:-}' is not a full 40-hex commit sha (config.sh must pin the tn-node-deployment commit)" >&2
        return 1
    fi
    printf '%s' "sudo git -C '${dir}' fetch --depth=1 origin '${ref}' && sudo git -C '${dir}' checkout --detach FETCH_HEAD && sudo grep -q TN_UPDATE_VERIFY_TIMEOUT '${dir}/update-node.sh'"
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
