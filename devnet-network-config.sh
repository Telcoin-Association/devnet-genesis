#!/usr/bin/env bash
#
# devnet-network-config.sh — OPERATOR driver for connection admission. Deploy step 7: after
# keygen + genesis build, BEFORE finalize starts any node. Two modes, chosen by the config's
# TN_ADMISSION_VIA (config.sh: native; benchmark/config.sh: devnet; unset: devnet):
#
#   native  the devnet deploy (devnet-deploy.sh with config.sh). Renders each node's admission
#           MAPS and with --yes installs them on its host. It never writes <datadir>/network-config:
#           tn-node-deployment's setup-node.sh writes that file at finalize (devnet-finalize.sh
#           passes --admission <mode> --bootstrap-peers <map> [--trusted-nodes <map>]).
#   devnet  the benchmark harness (CONFIG_FILE=benchmark/config.sh). Renders the whole
#           <datadir>/network-config here and with --yes installs it ("devnet mode" below).
#
# Targets, and the renderer's --nodes context, are the node hosts only (tn_node_indices: roles
# validator, observer, rpc, in config order); a gateway entry runs no node and is refused as a
# target (exit 2).
#
# --- native mode ---------------------------------------------------------------------------
# What each node gets (devnet-network-config.py `maps`):
#   role       --admission  bootstrap-peers.yaml      trusted-nodes.yaml
#   validator  closed       the genesis committee     the rpc node(s)
#   observer   closed       the genesis committee     the rpc node(s)
#   rpc        open         the genesis committee     (none)
# Local render: ${GENESIS_WORKSPACE:-REPO_ROOT}/${ADMISSION_MAPS_DIR}/<NODE_NAME>.bootstrap-peers.yaml
# and <NODE_NAME>.trusted-nodes.yaml (both kinds are cleared there first, so what exists is this
# render's); per node it prints the files and the admission mode the node will get.
# Install, per node host (--yes): upload the maps to /tmp, then, as root,
#   install -d ${ADMISSION_HOST_DIR} (root:root 0755)
#   install -o root -g root -m 0644 <tmp> ${ADMISSION_HOST_DIR}/bootstrap-peers.yaml
#   the same for trusted-nodes.yaml, or remove a stale one when the node gets none;
# then read both back: sha256 equal to the local file, root:root 0644. Nothing is restarted and
# <datadir>/network-config is left as it is: a finalized node takes new maps only when finalize
# writes its network-config again.
# --verify (read-only), per node host: the installed maps equal the local ones (sha256, owner,
# mode); when <datadir>/network-config exists (the node is finalized) it is fetched and checked
# with `devnet-network-config.py validate --native --node <NODE_NAME>`; before finalize the node
# is reported "not finalized yet", which is not a failure.
# Sessions: --yes one upload a map and one session a node, --verify one session a node; a
# session that hits a transport fault (ssh rc 255 after devnet-lib's own retries) is run once
# more at the end, read-only.
#
# --- devnet mode ---------------------------------------------------------------------------
# Render each node's <datadir>/network-config (closed connection admission, the committee
# launch inventory, and the trusted/bootstrap peers between the hub validator and the
# observers), validate it, and with --yes install it on the fleet.
#
# Why before the first start: the node reads network-config once, at startup. When the
# file is missing it writes NetworkConfig::default() there (admission Open) and runs with
# that (telcoin-network crates/config/src/traits.rs:56-86, crates/node/src/manager/node.rs:1014).
# v2 finalize (setup-node.sh step_write_config -> write_advertised_name) runs just before
# it starts the node, and puts `hostname: "<name>"` into this file: it rewrites an existing
# ^hostname: line, else APPENDS one with `>>`. So we install first, and our file ends with
# a newline for that append.
#
# What each node gets (shapes pinned at telcoin-network 3f9b0709c; see devnet-network-config.py):
#   all nodes    admission {mode: Closed, snapshot_max_age_secs: 300}
#                committee_peers = genesis/committee.yaml bootstrap_servers, verbatim
#   hub          trusted_nodes {<observer BLS>: {primary, workers: {0: ...}}}
#     (the first validator in config.sh, node1)
#   observers    bootstrap_peers {<hub BLS>: <hub's committee entry>}
#     (node5)    trusted_nodes  {<hub BLS>: {primary, workers: {0: ...}}}
# The node ignores unknown top-level keys, so a misspelt key would silently leave it Open:
# every file is checked by the python validator before upload AND after it is re-read.
#
# Rendered files: genesis/network-config/<nodeN>.yaml (reviewable, committed like
# genesis/committee.yaml). Rendering reads genesis/committee.yaml plus
# genesis/validators/<nodeN>.yaml and genesis/observers/<nodeN>.yaml from devnet-keygen.sh.
#
# Install, per node (--yes):
#   1. service user/group + datadir from /etc/telcoin/.node-meta (HOST_SERVICE_USER,
#      HOST_SERVICE_GROUP, DATA_DIR; config.sh's SERVICE_USER / datadir when absent).
#   2. refuse unless <datadir>/node-info.yaml carries the BLS key of the local
#      genesis/<role>/<nodeN>.yaml (right file, right node).
#   3. fetch the existing <datadir>/network-config (sudo cat), when there is one.
#   4. merge locally: our keys + the existing `hostname:` line verbatim; every other key of
#      the existing file is dropped (it is the node's default dump or our previous install).
#   5. validate the merged file, upload it to /tmp, then
#      sudo install -o <user> -g <group> -m 0640 <tmp> <datadir>/network-config
#   6. re-read the installed file: byte-identical to the merged one, owner/group/mode as
#      installed, and the validator passes again.
# A node that is already running reads the file at its next start; this script restarts
# nothing. When the ownership check of step 6 cannot reach the node (a transport fault, not
# a wrong owner), the node is checked once more at the end, after the others.
#
# Knobs (environment; unset keeps everything above as it is):
#   NETCFG_TRUST_OBSERVERS_EVERYWHERE=1  render and validate with --trust-observers-everywhere:
#                                        every validator trusts every observer and each
#                                        observer every validator (bootstrap stays the hub)
#   NETCFG_FAST=1   one `# netcfg: read` session per node returns steps 1-3 plus the file's
#                   owner/mode and the unit state; merge + validate locally; a node whose file
#                   already is the merged one (and owned right) is left alone ("unchanged"),
#                   else one `# netcfg: write` session installs it (content on stdin) and
#                   re-reads it for step 6: at most 2 sessions a node (--verify: 1)
#   NETCFG_JOBS=N   N nodes at a time (default 1, in order); each node's output is printed
#                   whole, in fleet order; INT, TERM or HUP stops the running jobs first
# In native mode only NETCFG_JOBS applies: NETCFG_FAST changes nothing there (native already
# uses one session a node) and NETCFG_TRUST_OBSERVERS_EVERYWHERE=1 is refused (exit 2).
#
# Usage:
#   ./devnet-network-config.sh                  # render + validate locally; touches no node
#   ./devnet-network-config.sh --yes            # ... then install on every node
#   ./devnet-network-config.sh --yes node5      # ... install on a subset (index, INSTANCE_NAME
#                                               #     or NODE_NAME); every node is still rendered
#   ./devnet-network-config.sh --verify         # read-only: re-read + validate installed files
# Exit: 0 ok; 1 a render, a node or a check failed; 2 bad flag, knob, config value or target.
#
# Needs python3 with PyYAML (parsing only): sudo apt-get install python3-yaml.

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

PY="${DEVNET_LIB_DIR}/devnet-network-config.py"
GENESIS_LOCAL_DIR="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis"
COMMITTEE_LOCAL="${GENESIS_LOCAL_DIR}/committee.yaml"
OUT_DIR="${GENESIS_LOCAL_DIR}/network-config"

usage() { sed -n '2,/^set -euo pipefail/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }

MODE="local"
SELECTORS=()
for a in "$@"; do
    case "$a" in
        --yes)     [ "${MODE}" = "local" ] || { echo "❌ --yes and --verify are exclusive" >&2; exit 2; }; MODE="install" ;;
        --verify)  [ "${MODE}" = "local" ] || { echo "❌ --yes and --verify are exclusive" >&2; exit 2; }; MODE="verify" ;;
        -h|--help) usage; exit 0 ;;
        -*)        echo "❌ unknown flag: $a (see --help)" >&2; exit 2 ;;
        *)         SELECTORS+=("$a") ;;
    esac
done
if [ "${MODE}" = "local" ] && [ "${#SELECTORS[@]}" -gt 0 ]; then
    echo "❌ node selectors only apply with --yes or --verify (rendering always covers the whole fleet)" >&2
    exit 2
fi
NETCFG_TRUST_OBSERVERS_EVERYWHERE="${NETCFG_TRUST_OBSERVERS_EVERYWHERE:-0}"
NETCFG_FAST="${NETCFG_FAST:-0}"
NETCFG_JOBS="${NETCFG_JOBS:-1}"
for _knob in NETCFG_TRUST_OBSERVERS_EVERYWHERE NETCFG_FAST; do
    case "${!_knob}" in 0|1) ;; *) echo "❌ ${_knob} must be 0 or 1 (got '${!_knob}')" >&2; exit 2 ;; esac
done
case "${NETCFG_JOBS}" in
    ""|*[!0-9]*) echo "❌ NETCFG_JOBS must be a positive integer (got '${NETCFG_JOBS}')" >&2; exit 2 ;;
esac
if [ "${NETCFG_JOBS}" -lt 1 ]; then echo "❌ NETCFG_JOBS must be at least 1" >&2; exit 2; fi

TN_ADMISSION_VIA="${TN_ADMISSION_VIA:-devnet}"
case "${TN_ADMISSION_VIA}" in
    native|devnet) ;;
    *) echo "❌ TN_ADMISSION_VIA must be native or devnet (got '${TN_ADMISSION_VIA}')" >&2; exit 2 ;;
esac
NC_WHAT="network-config"
if [ "${TN_ADMISSION_VIA}" = native ]; then
    NC_WHAT="admission maps"
    if [ "${NETCFG_TRUST_OBSERVERS_EVERYWHERE}" = 1 ]; then
        echo "❌ NETCFG_TRUST_OBSERVERS_EVERYWHERE applies to TN_ADMISSION_VIA=devnet only" >&2
        exit 2
    fi
    case "${ADMISSION_HOST_DIR:-}" in
        /?*) ;;
        *) echo "❌ ADMISSION_HOST_DIR must be an absolute path (got '${ADMISSION_HOST_DIR:-}')" >&2; exit 2 ;;
    esac
    case "${ADMISSION_HOST_DIR}" in
        *[!A-Za-z0-9._/-]*) echo "❌ ADMISSION_HOST_DIR '${ADMISSION_HOST_DIR}' has unexpected characters" >&2; exit 2 ;;
    esac
    if [ -z "${ADMISSION_MAPS_DIR:-}" ]; then echo "❌ ADMISSION_MAPS_DIR is not set (see config.sh)" >&2; exit 2; fi
    ADMISSION_HOST_DIR="${ADMISSION_HOST_DIR%/}"
    MAPS_DIR="${GENESIS_WORKSPACE:-${REPO_ROOT}}/${ADMISSION_MAPS_DIR}"
fi

# The node hosts (tn_node_indices: validator, observer, rpc), in config order.
NODE_IDX=()
while IFS= read -r _idx; do [ -z "${_idx}" ] || NODE_IDX+=("${_idx}"); done <<< "$(tn_node_indices)"
if [ "${#NODE_IDX[@]}" -eq 0 ]; then echo "❌ the config names no node host (roles validator, observer, rpc)" >&2; exit 2; fi

# Same selector as devnet-finalize.sh: no args → all node hosts; args may be an index (0-based),
# an INSTANCE_NAME, or a NODE_NAME. A node named twice is visited once; an entry that runs no
# node (a gateway) is refused.
tn_select_indices() {
    local out=() arg i matched
    if [ "$#" -eq 0 ]; then
        printf '%s\n' "${NODE_IDX[@]}"; return 0
    fi
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                if ! tn_is_node_index "${i}"; then
                    echo "❌ target ${arg} is ${INSTANCE_NAMES[$i]} (role ${NODE_ROLES[$i]:-none}): it runs no node" >&2
                    return 1
                fi
                case " ${out[*]+"${out[*]}"} " in *" ${i} "*) ;; *) out+=("$i") ;; esac
                matched=1; break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME, or NODE_NAME)" >&2
            return 1
        fi
    done
    printf '%s\n' "${out[@]}"
}

# Resolve the targets now: an unknown one stops the run before anything is rendered.
if ! SELECTION="$(tn_select_indices "${SELECTORS[@]+"${SELECTORS[@]}"}")"; then exit 2; fi

# --- python + PyYAML --------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 not found; it renders and validates the files." >&2
    exit 1
fi
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
    echo "❌ python3 has no PyYAML (used to PARSE committee.yaml and the files under check)." >&2
    echo "   Install it: sudo apt-get install python3-yaml   (or: python3 -m pip install --user pyyaml)" >&2
    exit 1
fi

# --- the fleet as the renderer sees it: name=role in config.sh order; hub = first validator ---
NODES_SPEC=""
HUB=""
for i in "${NODE_IDX[@]}"; do
    NODES_SPEC="${NODES_SPEC:+${NODES_SPEC},}${NODE_NAMES[$i]}=${NODE_ROLES[$i]}"
    if [ -z "${HUB}" ] && [ "${NODE_ROLES[$i]}" = "validator" ]; then HUB="${NODE_NAMES[$i]}"; fi
done
CTX=(--committee "${COMMITTEE_LOCAL}" --genesis-dir "${GENESIS_LOCAL_DIR}" --nodes "${NODES_SPEC}" --hub "${HUB}")
TRUST_NOTE=""
if [ "${NETCFG_TRUST_OBSERVERS_EVERYWHERE}" = 1 ]; then
    CTX+=(--trust-observers-everywhere)
    TRUST_NOTE="; observers trusted by every validator"
fi

if [ "${TN_ADMISSION_VIA}" = native ]; then
    # native: the maps each node's finalize hands to setup-node.sh (see the header).
    echo ">>> rendering admission maps for ${NODES_SPEC} into ${MAPS_DIR}"
    mkdir -p "${MAPS_DIR}"
    rm -f "${MAPS_DIR}"/*.bootstrap-peers.yaml "${MAPS_DIR}"/*.trusted-nodes.yaml
    if ! python3 "${PY}" maps "${CTX[@]}" --out-dir "${MAPS_DIR}"; then
        echo "❌ rendering the admission maps failed; nothing was installed." >&2
        exit 1
    fi
    _render_ok=1
    for i in "${NODE_IDX[@]}"; do
        _files=""
        for _kind in bootstrap-peers trusted-nodes; do
            if [ -f "${MAPS_DIR}/${NODE_NAMES[$i]}.${_kind}.yaml" ]; then _files="${_files} ${_kind}.yaml"; fi
        done
        printf '    %-10s %-9s --admission %-6s maps:%s\n' "${NODE_NAMES[$i]}" "${NODE_ROLES[$i]}" \
            "$(tn_admission_mode "${i}")" "${_files:- (none)}"
        if [ ! -f "${MAPS_DIR}/${NODE_NAMES[$i]}.bootstrap-peers.yaml" ]; then
            echo "❌ [${NODE_NAMES[$i]}] no ${NODE_NAMES[$i]}.bootstrap-peers.yaml was rendered" >&2
            _render_ok=0
        fi
        if [ "${NODE_ROLES[$i]}" = rpc ] && [ -f "${MAPS_DIR}/${NODE_NAMES[$i]}.trusted-nodes.yaml" ]; then
            echo "❌ [${NODE_NAMES[$i]}] an rpc node gets no trusted-nodes map, but one was rendered" >&2
            _render_ok=0
        fi
    done
    if [ "${_render_ok}" != 1 ]; then echo "❌ the rendered maps are incomplete; nothing was installed." >&2; exit 1; fi
    if [ "${MODE}" = "local" ]; then
        echo ""
        echo "rendered under ${MAPS_DIR}; no node was touched."
        echo "review the files, then install with: $0 --yes"
        exit 0
    fi
else
    echo ">>> rendering + validating network-config for ${NODES_SPEC} (hub ${HUB}${TRUST_NOTE})"
    if ! python3 "${PY}" render "${CTX[@]}" --out-dir "${OUT_DIR}"; then
        echo "❌ render/validate failed; nothing was installed." >&2
        exit 1
    fi

    if [ "${MODE}" = "local" ]; then
        echo ""
        echo "rendered + validated under ${OUT_DIR}; no node was touched."
        echo "review the files, then install with: $0 --yes"
        exit 0
    fi
fi

# --- per-node helpers ---------------------------------------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tn-network-config.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

# nc_meta <inst> <zone> <KEY> — .node-meta value; rc 0 value printed, 1 absent, 2 error.
# Uses devnet-lib.sh's tn_node_meta_get when it is there, else the same read inline. Under
# NETCFG_FAST the node's read session already brought the lines back (NC_READ_OUT).
nc_meta() {
    local inst="$1" zone="$2" key="$3" out rc
    if [ -n "${NC_READ_OUT:-}" ]; then
        nc_meta_from_read "${inst}" "${key}"
        return
    fi
    if declare -F tn_node_meta_get >/dev/null 2>&1; then
        rc=0; tn_node_meta_get "${inst}" "${zone}" "${key}" || rc=$?
        return "${rc}"
    fi
    out="$(tn_iap_ssh "${inst}" "${zone}" \
        "sudo grep -E '^${key}=' /etc/telcoin/.node-meta 2>/dev/null; echo \"__tn_meta_rc=\$?\"")" || return 2
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    case "${out}" in *__tn_meta_rc=0*) ;; *__tn_meta_rc=*) return 1 ;; *) return 2 ;; esac
    out="$(printf '%s\n' "${out}" | grep -E "^${key}=" || true)"
    [ "$(printf '%s\n' "${out}" | grep -c .)" -eq 1 ] || return 2
    printf '%s\n' "${out#*=}"
}

# nc_resolve <inst> <zone> <role> — sets NC_USER, NC_GROUP, NC_DIR; rc 1 when unusable.
nc_resolve() {
    local inst="$1" zone="$2" role="$3" rc
    rc=0; NC_USER="$(nc_meta "${inst}" "${zone}" HOST_SERVICE_USER)" || rc=$?
    [ "${rc}" -le 1 ] || return 1
    if [ -z "${NC_USER}" ]; then
        NC_USER="${SERVICE_USER}"
        echo "    ⚠️  no HOST_SERVICE_USER in .node-meta; using config.sh SERVICE_USER=${NC_USER}"
    fi
    rc=0; NC_GROUP="$(nc_meta "${inst}" "${zone}" HOST_SERVICE_GROUP)" || rc=$?
    [ "${rc}" -le 1 ] || return 1
    if [ -z "${NC_GROUP}" ]; then NC_GROUP="${NC_USER}"; fi
    rc=0; NC_DIR="$(nc_meta "${inst}" "${zone}" DATA_DIR)" || rc=$?
    [ "${rc}" -le 1 ] || return 1
    if [ -z "${NC_DIR}" ]; then
        NC_DIR="$(tn_data_dir_for_role "${role}")"
        echo "    ⚠️  no DATA_DIR in .node-meta; using config.sh's ${NC_DIR}"
    fi
    # These go into remote command strings: accept only plain names and paths (as v2 does).
    case "${NC_USER}${NC_GROUP}" in *[!a-z0-9_-]*) echo "    ❌ unusable service account '${NC_USER}:${NC_GROUP}'"; return 1 ;; esac
    case "${NC_DIR}" in /*) ;; *) echo "    ❌ DATA_DIR '${NC_DIR}' is not absolute"; return 1 ;; esac
    case "${NC_DIR}" in *[!A-Za-z0-9._/-]*) echo "    ❌ DATA_DIR '${NC_DIR}' has unexpected characters"; return 1 ;; esac
    NC_DIR="${NC_DIR%/}"
    return 0
}

# nc_fetch <inst> <zone> <remote-path> <local-file> — copy a root/service-owned file down
# byte for byte (stdout straight to the file, so a missing trailing newline survives).
# rc 0 fetched, 1 absent, 2 error.
nc_fetch() {
    local inst="$1" zone="$2" path="$3" dest="$4" state
    state="$(tn_iap_ssh "${inst}" "${zone}" \
        "if sudo test -f '${path}'; then echo present; elif sudo test -e '${path}'; then echo other; else echo absent; fi")" || return 2
    state="$(printf '%s' "${state}" | tr -d '[:space:]')"
    case "${state}" in
        present) tn_iap_ssh "${inst}" "${zone}" "sudo cat -- '${path}'" > "${dest}" || return 2 ;;
        absent)  : > "${dest}"; return 1 ;;
        *)       echo "    ❌ ${path} exists but is not a regular file (${state:-no answer})"; return 2 ;;
    esac
}

# nc_owner_check <inst> <zone> <path> — owner must be the service account (NC_USER:NC_GROUP)
# and nobody but the owner may write: the install sets 0640, but the UI's set-hostname
# rewrites the file with tee+mv under the caller's umask (R2 review, I3), so an exact
# -perm 0640 would fail a node that is fine. rc 0 ok, 1 not so (said), 3 the session itself
# failed (said): that is no answer about the owner, so it is never reported as a wrong one.
nc_owner_check() {
    local inst="$1" zone="$2" nc="$3" perm rc=0
    perm="$(tn_iap_ssh "${inst}" "${zone}" \
        "sudo find '${nc}' -maxdepth 0 -user '${NC_USER}' -group '${NC_GROUP}' ! -perm /022" | tr -d '\r')" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        echo "    ⚠️  could not check ${nc} (transport rc ${rc})"
        return 3
    fi
    if [ "${perm}" != "${nc}" ]; then
        echo "    ❌ ${nc} is not owned by ${NC_USER}:${NC_GROUP} with no group/world write bit"
        return 1
    fi
}

# nc_check_installed <inst> <zone> <node> <local-copy> [<existing>] — re-read the installed
# file into <local-copy>, check owner/group/mode, and run the validator on it. rc 0 ok,
# 1 failed, 3 everything passed but the ownership check could not reach the node (the caller
# checks that once more at the end).
nc_check_installed() {
    local inst="$1" zone="$2" node="$3" copy="$4" existing="${5:-}" nc="${NC_DIR}/network-config" rc owner=0
    rc=0; nc_fetch "${inst}" "${zone}" "${nc}" "${copy}" || rc=$?
    if [ "${rc}" -ne 0 ]; then echo "    ❌ could not re-read ${nc} (rc ${rc})"; return 1; fi
    nc_owner_check "${inst}" "${zone}" "${nc}" || owner=$?
    if [ "${owner}" -eq 1 ]; then return 1; fi
    if [ -n "${existing}" ]; then
        python3 "${PY}" validate "${CTX[@]}" --node "${node}" --existing "${existing}" "${copy}" || return 1
    else
        python3 "${PY}" validate "${CTX[@]}" --node "${node}" "${copy}" || return 1
    fi
    return "${owner}"
}

# nc_bls_value — stdin: node-info's `bls_public_key:` line; stdout: the key alone.
nc_bls_value() {
    tr -d '\r' | sed -e 's/^bls_public_key:[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/'
}

# nc_node_bls <inst> <zone> — the bls_public_key in the node's own <datadir>/node-info.yaml.
nc_node_bls() {
    tn_iap_ssh "$1" "$2" "sudo grep -m1 -E '^bls_public_key:' '${NC_DIR}/node-info.yaml'" | nc_bls_value
}

# --- NETCFG_FAST: one read session, at most one write session -------------------------------
# Both remote scripts run as root (`sudo bash -s`, the script on stdin; its first line names
# the session), print KEY=value lines between NC_BEGIN=1 (after an empty line) and NC_END=1,
# the last line once they ran to the end. devnet-lib's IAP retry streams every attempt's
# stdout into the same capture, so only the lines after the LAST NC_BEGIN=1 are read
# (nc_last_attempt; the empty line ends a cut-off line of an earlier attempt), and an answer
# without NC_END there is a failed session, not a fact about the node.
NL=$'\n'

# nc_field <KEY> <session-output> — the first KEY= line's value (reads all of its input).
nc_field() {
    printf '%s\n' "$2" | awk -v k="$1=" 'index($0, k) == 1 && !seen { print substr($0, length(k) + 1); seen = 1 }'
}
# nc_last_attempt — stdin: a session's whole stdout (each attempt the IAP retry made, in
# order); stdout: the lines after the last NC_BEGIN=1, CRs dropped; nothing without one.
nc_last_attempt() {
    tr -d '\r' | awk '$0 == "NC_BEGIN=1" { seen = 1; n = 0; next } { line[++n] = $0 }
        END { if (seen) for (i = 1; i <= n; i++) print line[i] }'
}
# nc_has_line <line> <session-output> / nc_has_key <KEY> <session-output>
nc_has_line() { case "${NL}${2}${NL}" in *"${NL}${1}${NL}"*) return 0 ;; esac; return 1; }
nc_has_key() { case "${NL}${2}" in *"${NL}${1}="*) return 0 ;; esac; return 1; }

# nc_b64_decode / nc_b64_encode — stdin to stdout through python3 (already required here; the
# base64 tool's decode flag differs between GNU and macOS). The decoder accepts base64 only.
nc_b64_decode() {
    python3 -c 'import base64, binascii, sys
try:
    data = base64.b64decode(sys.stdin.read().strip(), validate=True)
except (binascii.Error, ValueError):
    sys.exit("network-config: the session sent something that is not base64")
sys.stdout.buffer.write(data)'
}
nc_b64_encode() {
    python3 -c 'import base64, sys; sys.stdout.write(base64.encodebytes(sys.stdin.buffer.read()).decode("ascii"))'
}

# nc_meta_from_read <inst> <KEY> — nc_meta's answer from NC_READ_OUT, by tn_node_meta_get's
# rules: rc 0 value printed, 1 absent (or no readable .node-meta), 2 set more than once.
nc_meta_from_read() {
    local inst="$1" key="$2" lines
    if ! nc_has_line "NC_META_FILE=1" "${NC_READ_OUT}"; then
        echo "⚠️  no readable /etc/telcoin/.node-meta on ${inst}" >&2
        return 1
    fi
    lines="$(printf '%s\n' "${NC_READ_OUT}" | grep -E "^NC_META_${key}=" || true)"
    case "${lines}" in
        "") return 1 ;;
        *"${NL}"*) echo "❌ ${key} is set more than once in ${inst}:/etc/telcoin/.node-meta; no single value" >&2; return 2 ;;
    esac
    printf '%s\n' "${lines#NC_META_"${key}"=}"
}

# nc_remote_reread — the tail of both remote scripts: the state of "$nc", its bytes (base64,
# one line), and whether "$user:$group" owns it with no group/world write bit (nc_owner_check).
nc_remote_reread() {
    cat <<'EOF'
if [ -f "$nc" ]; then
    echo NC_STATE=present
    if b64="$(base64 < "$nc" | tr -d '\n')"; then echo "NC_B64=$b64"; fi
    if [ -n "$(find "$nc" -maxdepth 0 -user "$user" -group "$group" ! -perm /022 2>/dev/null)" ]; then
        echo NC_PERM=ok
    else
        echo NC_PERM=bad
    fi
elif [ -e "$nc" ]; then
    echo NC_STATE=other
else
    echo NC_STATE=absent
fi
EOF
}

# nc_read_script <role> — `# netcfg: read`: .node-meta's three keys, the owner and datadir
# they resolve to (nc_resolve's fallbacks), node-info's BLS line, the network-config re-read
# and the unit's state. Reads only.
nc_read_script() {
    echo "# netcfg: read"
    printf 'def_user=%q\ndef_dir=%q\nunit=%q\n' "${SERVICE_USER}" "$(tn_data_dir_for_role "$1")" "$(tn_service_for_role "$1")"
    cat <<'EOF'
set -u -o pipefail
printf '\nNC_BEGIN=1\n'
meta=/etc/telcoin/.node-meta
mval() { grep -m1 -E "^$1=" "$meta" 2>/dev/null | tr -d '\r' | cut -d= -f2-; }
if [ -r "$meta" ]; then
    echo NC_META_FILE=1
    grep -E '^(HOST_SERVICE_USER|HOST_SERVICE_GROUP|DATA_DIR)=' "$meta" | tr -d '\r' | sed 's/^/NC_META_/'
else
    echo NC_META_FILE=0
fi
user="$(mval HOST_SERVICE_USER)"; [ -n "$user" ] || user="$def_user"
group="$(mval HOST_SERVICE_GROUP)"; [ -n "$group" ] || group="$user"
dir="$(mval DATA_DIR)"; [ -n "$dir" ] || dir="$def_dir"
dir="${dir%/}"
echo "NC_DIR=$dir"
echo "NC_OWNER=$user:$group"
case "$dir" in /*) ;; *) dir="" ;; esac
case "$dir" in *[!A-Za-z0-9._/-]*) dir="" ;; esac
if [ -n "$dir" ]; then
    echo "NC_BLS=$(grep -m1 -E '^bls_public_key:' "$dir/node-info.yaml" 2>/dev/null)"
    nc="$dir/network-config"
EOF
    nc_remote_reread
    cat <<'EOF'
fi
echo "NC_UNIT=$(systemctl is-active "$unit" 2>/dev/null)"
echo NC_END=1
EOF
}

# nc_write_script <remote-path> <local-file> — `# netcfg: write`: <local-file> (base64 inside
# the script, so on stdin) installed over <remote-path> as NC_USER:NC_GROUP 0640, then re-read.
nc_write_script() {
    echo "# netcfg: write"
    printf 'nc=%q\nuser=%q\ngroup=%q\n' "$1" "${NC_USER}" "${NC_GROUP}"
    cat <<'EOF'
set -u -o pipefail
printf '\nNC_BEGIN=1\n'
rc=0
tmp="$(mktemp /tmp/tn-network-config.XXXXXX)" || rc=$?
if [ "$rc" -eq 0 ]; then
    base64 -d > "$tmp" <<'NC_FILE_B64' || rc=$?
EOF
    nc_b64_encode < "$2"
    cat <<'EOF'
NC_FILE_B64
fi
if [ "$rc" -eq 0 ]; then install -o "$user" -g "$group" -m 0640 -- "$tmp" "$nc" || rc=$?; fi
if [ -n "${tmp:-}" ]; then rm -f -- "$tmp"; fi
echo "NC_INSTALL_RC=$rc"
EOF
    nc_remote_reread
    echo "echo NC_END=1"
}

# nc_read_session <inst> <zone> <role> — the read script's answer (its last attempt's lines,
# nc_last_attempt); rc the session's.
nc_read_session() {
    local out
    out="$(nc_read_script "$3" | tn_iap_ssh_stdin "$1" "$2")" || return $?
    printf '%s\n' "${out}" | nc_last_attempt
}

# nc_fast_check <node> <session-output> <local-copy> [<existing> <merged>] — step 6 on the file
# a session re-read: present, owned right, valid (hostname kept from <existing>), and, given
# <merged>, byte-identical to it.
nc_fast_check() {
    local node="$1" out="$2" copy="$3" existing="${4:-}" merged="${5:-}" nc="${NC_DIR}/network-config"
    if [ "$(nc_field NC_STATE "${out}")" != present ] || ! nc_has_key NC_B64 "${out}" \
        || ! nc_field NC_B64 "${out}" | nc_b64_decode > "${copy}"; then
        echo "    ❌ could not re-read ${nc} (state: $(nc_field NC_STATE "${out}"))"
        return 1
    fi
    if [ "$(nc_field NC_PERM "${out}")" != ok ]; then
        echo "    ❌ ${nc} is not owned by ${NC_USER}:${NC_GROUP} with no group/world write bit"
        return 1
    fi
    if [ -n "${existing}" ]; then
        python3 "${PY}" validate "${CTX[@]}" --node "${node}" --existing "${existing}" "${copy}" || return 1
    else
        python3 "${PY}" validate "${CTX[@]}" --node "${node}" "${copy}" || return 1
    fi
    if [ -n "${merged}" ] && ! cmp -s "${merged}" "${copy}"; then
        echo "    ❌ ${nc} as re-read is not the file that was sent"
        return 1
    fi
}

# --- one node -----------------------------------------------------------------------------
# nc_node <index> installs or verifies one node. It and the bodies below always return 0, so a
# plain call keeps `set -e` in force inside them exactly as in the loop they replaced; the
# outcome is NC_RESULT: ok, failed, or recheck (a transport fault hid the final check, which
# runs once more at the end; ${WORK}/<node>.recheck says what to check).
nc_node() {
    NC_RESULT=failed
    NC_READ_OUT=""
    if [ "${TN_ADMISSION_VIA}" = native ]; then
        nm_node "$1"
    elif [ "${NETCFG_FAST}" = 1 ]; then nc_node_fast "$1"; else nc_node_legacy "$1"; fi
}

# --- native mode: one node ------------------------------------------------------------------
# nm_sha256 <file> — the file's sha256, hex (python3: sha256sum is not on every operator's Mac).
nm_sha256() {
    python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
}

# nm_session_script <install 0|1> <bootstrap-tmp> <trusted-tmp> <send-network-config 0|1> <role>
# — `# admission: install|read`, run as root (`sudo bash -s`). With install 1 it installs the
# uploaded map(s) into ADMISSION_HOST_DIR (an empty <trusted-tmp> removes a stale
# trusted-nodes.yaml) and removes the uploads; then it reports, between NC_BEGIN=1 and NC_END=1,
# the directory's and each map's owner/mode and sha256, the datadir (.node-meta DATA_DIR, else
# config.sh's) and whether <datadir>/network-config exists (its bytes in base64 when asked).
nm_session_script() {
    echo "# admission: $([ "$1" = 1 ] && echo install || echo read)"
    printf 'd=%q\ndo_install=%q\nbp_tmp=%q\ntr_tmp=%q\nwant_nc=%q\ndef_dir=%q\n' \
        "${ADMISSION_HOST_DIR}" "$1" "$2" "$3" "$4" "$(tn_data_dir_for_role "$5")"
    cat <<'EOF'
set -u -o pipefail
printf '\nNC_BEGIN=1\n'
if [ "$do_install" = 1 ]; then
    rc=0
    install -d -m 0755 -- "$d" || rc=$?
    if [ "$rc" -eq 0 ]; then chown root:root -- "$d" || rc=$?; fi
    if [ "$rc" -eq 0 ]; then chmod 0755 -- "$d" || rc=$?; fi
    if [ "$rc" -eq 0 ]; then install -o root -g root -m 0644 -- "$bp_tmp" "$d/bootstrap-peers.yaml" || rc=$?; fi
    if [ "$rc" -eq 0 ] && [ -n "$tr_tmp" ]; then
        install -o root -g root -m 0644 -- "$tr_tmp" "$d/trusted-nodes.yaml" || rc=$?
    elif [ "$rc" -eq 0 ] && { [ -e "$d/trusted-nodes.yaml" ] || [ -L "$d/trusted-nodes.yaml" ]; }; then
        if rm -f -- "$d/trusted-nodes.yaml"; then echo NM_TR_REMOVED=1; else rc=$?; fi
    fi
    rm -f -- "$bp_tmp"
    if [ -n "$tr_tmp" ]; then rm -f -- "$tr_tmp"; fi
    echo "NM_INSTALL_RC=$rc"
fi
nm_state() {
    if [ -L "$2" ]; then
        echo "$1_STATE=other"
    elif [ -f "$2" ]; then
        echo "$1_STATE=present"
        echo "$1_SHA=$(sha256sum < "$2" | cut -d' ' -f1)"
        echo "$1_PERM=$(stat -c '%U:%G %a' -- "$2")"
    elif [ -e "$2" ]; then
        echo "$1_STATE=other"
    else
        echo "$1_STATE=absent"
    fi
}
if [ -d "$d" ] && [ ! -L "$d" ]; then echo "NM_DIR_PERM=$(stat -c '%U:%G %a' -- "$d")"; else echo NM_DIR_PERM=absent; fi
nm_state NM_BP "$d/bootstrap-peers.yaml"
nm_state NM_TR "$d/trusted-nodes.yaml"
dir="$(grep -m1 -E '^DATA_DIR=' /etc/telcoin/.node-meta 2>/dev/null | tr -d '\r' | cut -d= -f2-)"
[ -n "$dir" ] || dir="$def_dir"
dir="${dir%/}"
echo "NM_DATA_DIR=$dir"
case "$dir" in /*) ;; *) dir="" ;; esac
case "$dir" in *[!A-Za-z0-9._/-]*) dir="" ;; esac
nc="$dir/network-config"
if [ -z "$dir" ]; then
    echo NM_NC_STATE=unknown
elif [ -f "$nc" ]; then
    echo NM_NC_STATE=present
    if [ "$want_nc" = 1 ] && b64="$(base64 < "$nc" | tr -d '\n')"; then echo "NM_NC_B64=$b64"; fi
elif [ -e "$nc" ]; then
    echo NM_NC_STATE=other
else
    echo NM_NC_STATE=absent
fi
echo NC_END=1
EOF
}

# nm_check_file <session-output> <KEY> <local-map> <name> — the host's copy is a regular file,
# root:root 0644, with the local map's sha256. rc 0 ok, 1 not (said).
nm_check_file() {
    local out="$1" key="$2" map="$3" name="$4" want got perm state
    want="$(nm_sha256 "${map}")"
    state="$(nc_field "${key}_STATE" "${out}")"
    if [ "${state}" != present ]; then
        echo "    ❌ ${ADMISSION_HOST_DIR}/${name} is ${state:-unknown} on the host"
        return 1
    fi
    got="$(nc_field "${key}_SHA" "${out}")"
    perm="$(nc_field "${key}_PERM" "${out}")"
    if [ "${got}" != "${want}" ]; then
        echo "    ❌ ${ADMISSION_HOST_DIR}/${name}: sha256 ${got:0:12}… on the host, ${want:0:12}… here"
        return 1
    fi
    if [ "${perm}" != "root:root 644" ]; then
        echo "    ❌ ${ADMISSION_HOST_DIR}/${name} is ${perm:-unknown}, not root:root 644"
        return 1
    fi
    echo "    ✓ ${ADMISSION_HOST_DIR}/${name} = local ${map##*/} (sha256 ${want:0:12}…, root:root 644)"
}

# nm_check <index> <session-output> — the maps a session read back against the local ones and,
# with --verify, the node's network-config once it exists. Sets NC_RESULT; returns 0.
nm_check() {
    local i="$1" out="$2" node inst map_dir tr irc dperm ok=1 st dir copy
    node="${NODE_NAMES[$i]}"
    inst="${INSTANCE_NAMES[$i]}"
    tr="${MAPS_DIR}/${node}.trusted-nodes.yaml"
    if nc_has_key NM_INSTALL_RC "${out}"; then
        irc="$(nc_field NM_INSTALL_RC "${out}")"
        if [ "${irc}" != 0 ]; then
            echo "❌ [${node}] installing the maps on ${inst} failed (rc ${irc})"
            return 0
        fi
        if nc_has_line NM_TR_REMOVED=1 "${out}"; then echo "    removed a stale ${ADMISSION_HOST_DIR}/trusted-nodes.yaml"; fi
    fi
    map_dir="${ADMISSION_HOST_DIR}"
    dperm="$(nc_field NM_DIR_PERM "${out}")"
    if [ "${dperm}" != "root:root 755" ]; then
        echo "    ❌ ${map_dir} is ${dperm:-unknown}, not a root:root 0755 directory"
        ok=0
    fi
    nm_check_file "${out}" NM_BP "${MAPS_DIR}/${node}.bootstrap-peers.yaml" bootstrap-peers.yaml || ok=0
    if [ -f "${tr}" ]; then
        nm_check_file "${out}" NM_TR "${tr}" trusted-nodes.yaml || ok=0
    elif [ "$(nc_field NM_TR_STATE "${out}")" != absent ]; then
        echo "    ❌ ${map_dir}/trusted-nodes.yaml is on the host, but ${node} gets no trusted-nodes map"
        ok=0
    else
        echo "    ✓ no ${map_dir}/trusted-nodes.yaml (${node} gets none)"
    fi
    if [ "${ok}" != 1 ]; then
        echo "❌ [${node}] the admission maps on ${inst} failed the ${MODE} check"
        return 0
    fi

    st="$(nc_field NM_NC_STATE "${out}")"
    dir="$(nc_field NM_DATA_DIR "${out}")"
    if [ "${MODE}" = install ]; then
        if [ "${st}" = present ]; then
            echo "    note: ${dir}/network-config exists (finalized): left as it is; finalize writes it from the maps"
        fi
        NC_RESULT=ok
        return 0
    fi
    case "${st}" in
        absent)
            echo "    ${dir}/network-config: not finalized yet (nothing to validate)"
            NC_RESULT=ok ;;
        present)
            copy="${WORK}/${node}.network-config"
            if ! nc_has_key NM_NC_B64 "${out}" || ! nc_field NM_NC_B64 "${out}" | nc_b64_decode > "${copy}"; then
                echo "❌ [${node}] could not re-read ${dir}/network-config"
            elif python3 "${PY}" validate "${CTX[@]}" --native --node "${node}" "${copy}"; then
                echo "    ✓ ${dir}/network-config passes validate --native"
                NC_RESULT=ok
            else
                echo "❌ [${node}] ${dir}/network-config failed validate --native"
            fi ;;
        *)
            echo "❌ [${node}] ${dir:-<datadir>}/network-config is not a regular file (state ${st:-no answer})" ;;
    esac
}

# nm_session <index> <install 0|1> [<bootstrap-tmp> <trusted-tmp>] — run nm_session_script on the
# node's host; NM_OUT = the last attempt's lines (nc_last_attempt); rc the session's, or 1
# when the answer has no NC_END=1.
nm_session() {
    local i="$1" want_nc=0 rc=0
    [ "${MODE}" = verify ] && want_nc=1
    NM_OUT="$(nm_session_script "$2" "${3:-}" "${4:-}" "${want_nc}" "$(tn_node_role "${i}")" \
        | tn_iap_ssh_stdin "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}")" || rc=$?
    NM_OUT="$(printf '%s\n' "${NM_OUT}" | nc_last_attempt)"
    if [ "${rc}" -eq 0 ] && ! nc_has_line NC_END=1 "${NM_OUT}"; then rc=1; fi
    return "${rc}"
}

# nm_node <index> — native --yes / --verify for one node host. Returns 0 (see nc_node).
nm_node() {
    local i="$1" inst zone node role tr bp_tmp="" tr_tmp="" install=0 rc
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    tr="${MAPS_DIR}/${node}.trusted-nodes.yaml"
    echo ""
    echo ">>> [${node}] ${MODE} admission maps on ${inst} (${zone}) role=${role} admission=$(tn_admission_mode "$i")"
    if [ "${MODE}" = install ]; then
        install=1
        bp_tmp="/tmp/tn-admission.${node}.$$.bootstrap-peers.yaml"
        if ! tn_iap_scp "${MAPS_DIR}/${node}.bootstrap-peers.yaml" "${inst}" "${zone}" "${bp_tmp}"; then
            echo "❌ [${node}] could not upload ${node}.bootstrap-peers.yaml to ${inst}; nothing was installed"
            return 0
        fi
        if [ -f "${tr}" ]; then
            tr_tmp="/tmp/tn-admission.${node}.$$.trusted-nodes.yaml"
            if ! tn_iap_scp "${tr}" "${inst}" "${zone}" "${tr_tmp}"; then
                echo "❌ [${node}] could not upload ${node}.trusted-nodes.yaml to ${inst}; nothing was installed"
                return 0
            fi
        fi
    fi
    rc=0; nm_session "${i}" "${install}" "${bp_tmp}" "${tr_tmp}" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        echo "    ⚠️  could not read ${inst}'s admission maps back (transport rc ${rc})"
        nc_recheck_later "${node}" native "${ADMISSION_HOST_DIR}"
        return 0
    fi
    nm_check "${i}" "${NM_OUT}"
}

# nm_recheck <index> — the end-of-run re-check: one read-only session, the same checks.
nm_recheck() {
    local i="$1" rc=0
    echo ""
    echo ">>> [${NODE_NAMES[$i]}] re-check on ${INSTANCE_NAMES[$i]} (${ZONES[$i]})"
    nm_session "${i}" 0 || rc=$?
    if [ "${rc}" -ne 0 ]; then
        echo "    ⚠️  could not read ${INSTANCE_NAMES[$i]}'s admission maps (transport rc ${rc})"
        echo "❌ [${NODE_NAMES[$i]}] admission maps failed their re-check"
        return 0
    fi
    nm_check "${i}" "${NM_OUT}"
}

# nc_recheck_later <node> owner|fast <remote-path> — queue the end-of-run check.
nc_recheck_later() {
    printf '%s %s %s %s\n' "$2" "$3" "${NC_USER:--}" "${NC_GROUP:--}" > "${WORK}/$1.recheck"
    echo "    ${3}: checked once more at the end"
    NC_RESULT=recheck
}

nc_node_legacy() {
    local i="$1" inst zone node role rendered nc want_bls have_bls existing merged tmp installed state rc
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    rendered="${OUT_DIR}/${node}.yaml"
    echo ""
    echo ">>> [${node}] ${MODE} network-config on ${inst} (${zone}) role=${role}"

    if ! nc_resolve "${inst}" "${zone}" "${role}"; then
        echo "❌ [${node}] could not resolve the service account / datadir from .node-meta"
        return 0
    fi
    nc="${NC_DIR}/network-config"
    echo "    datadir ${NC_DIR}, owner ${NC_USER}:${NC_GROUP}"

    if [ "${MODE}" = "verify" ]; then
        rc=0; nc_check_installed "${inst}" "${zone}" "${node}" "${WORK}/${node}.installed" || rc=$?
        case "${rc}" in
            0) NC_RESULT=ok ;;
            3) nc_recheck_later "${node}" owner "${nc}" ;;
            *) echo "❌ [${node}] installed ${nc} failed verification" ;;
        esac
        return 0
    fi

    # Right file for the right node: the datadir's node-info.yaml must carry this node's key.
    want_bls="$(sed -n -e 's/^bls_public_key:[[:space:]]*//p' \
        "${GENESIS_LOCAL_DIR}/$([ "${role}" = "observer" ] && echo observers || echo validators)/${node}.yaml" | head -1)"
    have_bls="$(nc_node_bls "${inst}" "${zone}" || true)"
    if [ -z "${want_bls}" ] || [ "${have_bls}" != "${want_bls}" ]; then
        echo "❌ [${node}] ${NC_DIR}/node-info.yaml BLS key '${have_bls:0:16}…' is not the local ${node}'s '${want_bls:0:16}…' (keygen not run, or wrong node)"
        return 0
    fi

    existing="${WORK}/${node}.existing"
    rc=0; nc_fetch "${inst}" "${zone}" "${nc}" "${existing}" || rc=$?
    case "${rc}" in
        0) echo "    existing ${nc}: $(wc -c < "${existing}" | tr -d ' ') bytes (keeping only its hostname line)" ;;
        1) echo "    no existing ${nc}" ;;
        *) echo "❌ [${node}] could not read the existing ${nc}"; return 0 ;;
    esac

    merged="${WORK}/${node}.merged"
    if ! python3 "${PY}" merge --rendered "${rendered}" --existing "${existing}" --out "${merged}" \
        || ! python3 "${PY}" validate "${CTX[@]}" --node "${node}" --existing "${existing}" "${merged}"; then
        echo "❌ [${node}] merged file failed; nothing uploaded"
        return 0
    fi

    tmp="/tmp/tn-network-config.${node}.$$"
    if ! tn_iap_scp "${merged}" "${inst}" "${zone}" "${tmp}"; then
        echo "❌ [${node}] upload to ${tmp} failed"
        return 0
    fi
    if ! tn_iap_ssh "${inst}" "${zone}" \
        "rc=0; sudo install -o '${NC_USER}' -g '${NC_GROUP}' -m 0640 -- '${tmp}' '${nc}' || rc=\$?; rm -f -- '${tmp}'; exit \$rc"; then
        echo "❌ [${node}] sudo install into ${nc} failed"
        return 0
    fi

    installed="${WORK}/${node}.installed"
    rc=0; nc_check_installed "${inst}" "${zone}" "${node}" "${installed}" "${existing}" || rc=$?
    if { [ "${rc}" -ne 0 ] && [ "${rc}" -ne 3 ]; } || ! cmp -s "${merged}" "${installed}"; then
        echo "❌ [${node}] re-read of ${nc} does not match what was uploaded, or fails validation"
        return 0
    fi
    state="$(tn_iap_ssh "${inst}" "${zone}" "systemctl is-active '$(tn_service_for_role "${role}")' 2>/dev/null || true" | tr -d '[:space:]' || true)"
    if [ "${state}" = "active" ]; then
        echo "    ⚠️  $(tn_service_for_role "${role}") is already running: it reads ${nc} at its NEXT start (not restarted here)"
    fi
    if [ "${rc}" -eq 3 ]; then
        nc_recheck_later "${node}" owner "${nc}"
        return 0
    fi
    echo "    ✓ installed + re-read + validated ${nc}"
    NC_RESULT=ok
}

nc_node_fast() {
    local i="$1" inst zone node role rendered nc want_bls have_bls existing merged installed out wout rc
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    rendered="${OUT_DIR}/${node}.yaml"
    echo ""
    echo ">>> [${node}] ${MODE} network-config on ${inst} (${zone}) role=${role}"

    rc=0; out="$(nc_read_session "${inst}" "${zone}" "${role}")" || rc=$?
    if [ "${rc}" -ne 0 ] || ! nc_has_line NC_END=1 "${out}"; then
        if [ "${MODE}" = "verify" ]; then
            echo "    ⚠️  could not check ${inst}'s network-config (transport rc ${rc})"
            nc_recheck_later "${node}" fast -
        else
            echo "❌ [${node}] could not read ${inst} (transport rc ${rc}); nothing was changed"
        fi
        return 0
    fi
    NC_READ_OUT="${out}"
    if ! nc_resolve "${inst}" "${zone}" "${role}"; then
        echo "❌ [${node}] could not resolve the service account / datadir from .node-meta"
        return 0
    fi
    nc="${NC_DIR}/network-config"
    if [ "$(nc_field NC_DIR "${out}")" != "${NC_DIR}" ] || [ "$(nc_field NC_OWNER "${out}")" != "${NC_USER}:${NC_GROUP}" ]; then
        echo "❌ [${node}] the read session resolved $(nc_field NC_OWNER "${out}") in '$(nc_field NC_DIR "${out}")', not ${NC_USER}:${NC_GROUP} in ${NC_DIR}"
        return 0
    fi
    echo "    datadir ${NC_DIR}, owner ${NC_USER}:${NC_GROUP}"

    if [ "${MODE}" = "verify" ]; then
        if nc_fast_check "${node}" "${out}" "${WORK}/${node}.installed"; then
            NC_RESULT=ok
        else
            echo "❌ [${node}] installed ${nc} failed verification"
        fi
        return 0
    fi

    want_bls="$(sed -n -e 's/^bls_public_key:[[:space:]]*//p' \
        "${GENESIS_LOCAL_DIR}/$([ "${role}" = "observer" ] && echo observers || echo validators)/${node}.yaml" | head -1)"
    have_bls="$(nc_field NC_BLS "${out}" | nc_bls_value || true)"
    if [ -z "${want_bls}" ] || [ "${have_bls}" != "${want_bls}" ]; then
        echo "❌ [${node}] ${NC_DIR}/node-info.yaml BLS key '${have_bls:0:16}…' is not the local ${node}'s '${want_bls:0:16}…' (keygen not run, or wrong node)"
        return 0
    fi

    existing="${WORK}/${node}.existing"
    case "$(nc_field NC_STATE "${out}")" in
        present)
            if ! nc_has_key NC_B64 "${out}" || ! nc_field NC_B64 "${out}" | nc_b64_decode > "${existing}"; then
                echo "❌ [${node}] could not read the existing ${nc}"
                return 0
            fi
            echo "    existing ${nc}: $(wc -c < "${existing}" | tr -d ' ') bytes (keeping only its hostname line)" ;;
        absent)
            : > "${existing}"
            echo "    no existing ${nc}" ;;
        *)
            echo "    ❌ ${nc} exists but is not a regular file ($(nc_field NC_STATE "${out}"))"
            echo "❌ [${node}] could not read the existing ${nc}"
            return 0 ;;
    esac

    merged="${WORK}/${node}.merged"
    if ! python3 "${PY}" merge --rendered "${rendered}" --existing "${existing}" --out "${merged}" \
        || ! python3 "${PY}" validate "${CTX[@]}" --node "${node}" --existing "${existing}" "${merged}"; then
        echo "❌ [${node}] merged file failed; nothing uploaded"
        return 0
    fi

    # The node already holds exactly the merged file (validated above, hostname included): one
    # session was enough, unless its owner or mode is wrong, which the install puts right.
    if cmp -s "${merged}" "${existing}"; then
        if [ "$(nc_field NC_PERM "${out}")" = ok ]; then
            echo "    ✓ unchanged (not written)"
            NC_RESULT=ok
            return 0
        fi
        echo "    ⚠️  ${nc} holds the merged file but is not owned by ${NC_USER}:${NC_GROUP} with no group/world write bit: installing it again"
    fi

    rc=0; wout="$(nc_write_script "${nc}" "${merged}" | tn_iap_ssh_stdin "${inst}" "${zone}")" || rc=$?
    wout="$(printf '%s\n' "${wout}" | nc_last_attempt)"
    if [ "${rc}" -ne 0 ] || ! nc_has_line NC_END=1 "${wout}"; then
        echo "    ⚠️  could not check ${nc} (transport rc ${rc})"
        nc_recheck_later "${node}" fast "${nc}"
        return 0
    fi
    if [ "$(nc_field NC_INSTALL_RC "${wout}")" != 0 ]; then
        echo "❌ [${node}] sudo install into ${nc} failed (rc $(nc_field NC_INSTALL_RC "${wout}"))"
        return 0
    fi
    installed="${WORK}/${node}.installed"
    if ! nc_fast_check "${node}" "${wout}" "${installed}" "${existing}" "${merged}"; then
        echo "❌ [${node}] re-read of ${nc} does not match what was uploaded, or fails validation"
        return 0
    fi
    if [ "$(nc_field NC_UNIT "${out}")" = "active" ]; then
        echo "    ⚠️  $(tn_service_for_role "${role}") is already running: it reads ${nc} at its NEXT start (not restarted here)"
    fi
    echo "    ✓ installed + re-read + validated ${nc}"
    NC_RESULT=ok
}

# nc_recheck <index> — the one end-of-run check of a node whose check hit a transport fault:
# the ownership test again (owner), or a fresh read session checked as the write session's
# re-read would have been (fast). It installs nothing: a node that fails it is re-run by hand.
nc_recheck() {
    local i="$1" inst zone node role kind nc out rc existing="" merged=""
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    NC_RESULT=failed
    NC_READ_OUT=""
    if [ "${TN_ADMISSION_VIA}" = native ]; then nm_recheck "${i}"; return 0; fi
    read -r kind nc NC_USER NC_GROUP < "${WORK}/${node}.recheck"
    echo ""
    echo ">>> [${node}] re-check on ${inst} (${zone})"
    if [ "${kind}" = owner ]; then
        if nc_owner_check "${inst}" "${zone}" "${nc}"; then
            echo "    ✓ ${nc} is owned by ${NC_USER}:${NC_GROUP}"
            NC_RESULT=ok
        else
            echo "❌ [${node}] ${nc} failed its re-check"
        fi
        return 0
    fi
    rc=0; out="$(nc_read_session "${inst}" "${zone}" "${role}")" || rc=$?
    if [ "${rc}" -ne 0 ] || ! nc_has_line NC_END=1 "${out}"; then
        echo "    ⚠️  could not check ${inst}'s network-config (transport rc ${rc})"
        echo "❌ [${node}] network-config failed its re-check"
        return 0
    fi
    NC_READ_OUT="${out}"
    if ! nc_resolve "${inst}" "${zone}" "${role}"; then
        echo "❌ [${node}] could not resolve the service account / datadir from .node-meta"
        return 0
    fi
    if [ "${MODE}" = "install" ]; then
        existing="${WORK}/${node}.existing"
        merged="${WORK}/${node}.merged"
    fi
    if nc_fast_check "${node}" "${out}" "${WORK}/${node}.installed" "${existing}" "${merged}"; then
        echo "    ✓ re-read + validated ${NC_DIR}/network-config"
        NC_RESULT=ok
    else
        echo "❌ [${node}] ${NC_DIR}/network-config failed its re-check"
    fi
}

# --- fleet loop ---------------------------------------------------------------------------
INDICES=()
while IFS= read -r _idx; do INDICES+=("$_idx"); done <<< "${SELECTION}"
RUN_NOTE=""
if [ "${NETCFG_FAST}" = 1 ] && [ "${TN_ADMISSION_VIA}" = devnet ]; then
    RUN_NOTE=" (NETCFG_FAST: read once, write only a changed file)"
fi
if [ "${NETCFG_JOBS}" -gt 1 ]; then RUN_NOTE="${RUN_NOTE} (${NETCFG_JOBS} at a time)"; fi
echo ""
echo ">>> ${MODE} targets: ${#INDICES[@]} node(s) — ${INDICES[*]}${RUN_NOTE}"

done_nodes=()
failed=()
rechecks=()

# nc_tally <index> — file the node under ok / failed / re-check by NC_RESULT.
nc_tally() {
    case "${NC_RESULT}" in
        ok)      done_nodes+=("${NODE_NAMES[$1]}") ;;
        recheck) rechecks+=("$1") ;;
        *)       failed+=("${NODE_NAMES[$1]}") ;;
    esac
}

# nc_collect <pid> <index> — wait for one node's job, print its output whole, tally it.
nc_collect() {
    local rc=0
    wait "$1" || rc=$?
    cat "${WORK}/job.$2.out"
    NC_RESULT="$(cat "${WORK}/job.$2.result" 2>/dev/null || true)"
    if [ -z "${NC_RESULT}" ]; then
        echo "❌ [${NODE_NAMES[$2]}] its job ended without a result (rc ${rc})"
        NC_RESULT=failed
    fi
    nc_tally "$2"
}

# nc_run_parallel <jobs> <index>... — nc_node for each index in a background subshell, at most
# <jobs> at once. A job's stdout and stderr go to ${WORK}/job.<index>.out and its NC_RESULT to
# job.<index>.result; outputs print whole and in the order given (the oldest job is collected
# before the next one starts). A background job ignores the terminal's INT, so INT, TERM or
# HUP stops the jobs still running (nc_stop_jobs) before the EXIT trap removes ${WORK}.
NC_JOB_PIDS=()
NC_JOB_HEAD=0
nc_run_parallel() {
    local jobs="$1" i
    local -a order
    shift
    NC_JOB_PIDS=()
    NC_JOB_HEAD=0
    trap 'nc_stop_jobs; exit 130' INT
    trap 'nc_stop_jobs; exit 143' TERM
    trap 'nc_stop_jobs; exit 129' HUP
    for i in "$@"; do
        ( nc_node "${i}"; printf '%s\n' "${NC_RESULT}" > "${WORK}/job.${i}.result" ) > "${WORK}/job.${i}.out" 2>&1 &
        NC_JOB_PIDS+=("$!")
        order+=("${i}")
        if [ "$(( ${#NC_JOB_PIDS[@]} - NC_JOB_HEAD ))" -ge "${jobs}" ]; then
            nc_collect "${NC_JOB_PIDS[$NC_JOB_HEAD]}" "${order[$NC_JOB_HEAD]}"
            NC_JOB_HEAD=$((NC_JOB_HEAD + 1))
        fi
    done
    while [ "${NC_JOB_HEAD}" -lt "${#NC_JOB_PIDS[@]}" ]; do
        nc_collect "${NC_JOB_PIDS[$NC_JOB_HEAD]}" "${order[$NC_JOB_HEAD]}"
        NC_JOB_HEAD=$((NC_JOB_HEAD + 1))
    done
    trap - INT TERM HUP
    NC_JOB_PIDS=()
}

# nc_kill_tree <pid> — SIGTERM <pid> and every local process below it (the job's subshells,
# gcloud, ssh), each pid added to NC_KILLED. A remote command that already runs is not
# stopped by this (no pty, no SIGHUP); every session here is a read, or an install that a
# re-run repeats harmlessly.
nc_kill_tree() {
    local kids c
    kids="$(ps -A -o pid= -o ppid= 2>/dev/null | awk -v p="$1" '$2 == p { print $1 }')" || kids=""
    kill "$1" 2>/dev/null || true
    NC_KILLED="${NC_KILLED} $1"
    for c in ${kids}; do nc_kill_tree "${c}"; done
}

# nc_stop_jobs — stop every job not yet collected and wait, up to 10 s, until none of the
# processes it signalled is left (zombies count as gone), so that ${WORK} is removed only after.
nc_stop_jobs() {
    local k p alive tries=0
    NC_KILLED=""
    k="${NC_JOB_HEAD}"
    while [ "${k}" -lt "${#NC_JOB_PIDS[@]}" ]; do
        nc_kill_tree "${NC_JOB_PIDS[$k]}"
        k=$((k + 1))
    done
    k="${NC_JOB_HEAD}"
    while [ "${k}" -lt "${#NC_JOB_PIDS[@]}" ]; do
        wait "${NC_JOB_PIDS[$k]}" 2>/dev/null || true
        k=$((k + 1))
    done
    while [ "${tries}" -lt 100 ]; do
        alive=""
        for p in ${NC_KILLED}; do
            case "$(ps -o stat= -p "${p}" 2>/dev/null || true)" in ""|Z*) ;; *) alive=1 ;; esac
        done
        [ -n "${alive}" ] || break
        sleep 0.1
        tries=$((tries + 1))
    done
}

if [ "${NETCFG_JOBS}" -gt 1 ]; then
    nc_run_parallel "${NETCFG_JOBS}" "${INDICES[@]}"
else
    for i in "${INDICES[@]}"; do
        nc_node "${i}"
        nc_tally "${i}"
    done
fi

if [ "${#rechecks[@]}" -gt 0 ]; then
    echo ""
    echo ">>> re-check: ${#rechecks[@]} node(s) whose final check hit a transport fault — ${rechecks[*]}"
    for i in "${rechecks[@]}"; do
        nc_recheck "${i}"
        nc_tally "${i}"
    done
fi

echo ""
echo "========================================="
echo "${NC_WHAT} ${MODE} summary"
echo "========================================="
echo "ok (${#done_nodes[@]}):"
for n in "${done_nodes[@]+"${done_nodes[@]}"}"; do echo "  - ${n}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    exit 1
fi
echo "all targeted nodes: ${MODE} ok."
