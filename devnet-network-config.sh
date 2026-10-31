#!/usr/bin/env bash
#
# devnet-network-config.sh — OPERATOR driver: render each node's <datadir>/network-config
# (closed connection admission, the committee launch inventory, and the trusted/bootstrap
# peers between the hub validator and the observers), validate it, and with --yes install
# it on the fleet. Deploy step 7: after keygen + genesis build, BEFORE finalize starts any
# node.
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
# nothing.
#
# Usage:
#   ./devnet-network-config.sh                  # render + validate locally; touches no node
#   ./devnet-network-config.sh --yes            # ... then install on every node
#   ./devnet-network-config.sh --yes node5      # ... install on a subset (index, INSTANCE_NAME
#                                               #     or NODE_NAME); all five are still rendered
#   ./devnet-network-config.sh --verify         # read-only: re-read + validate installed files
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

# Same selector as devnet-finalize.sh: no args → all nodes; args may be an index (0-based),
# an INSTANCE_NAME, or a NODE_NAME. A node named twice is visited once.
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
for i in "${!NODE_NAMES[@]}"; do
    NODES_SPEC="${NODES_SPEC:+${NODES_SPEC},}${NODE_NAMES[$i]}=${NODE_ROLES[$i]}"
    if [ -z "${HUB}" ] && [ "${NODE_ROLES[$i]}" = "validator" ]; then HUB="${NODE_NAMES[$i]}"; fi
done
CTX=(--committee "${COMMITTEE_LOCAL}" --genesis-dir "${GENESIS_LOCAL_DIR}" --nodes "${NODES_SPEC}" --hub "${HUB}")

echo ">>> rendering + validating network-config for ${NODES_SPEC} (hub ${HUB})"
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

# --- per-node helpers ---------------------------------------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tn-network-config.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

# nc_meta <inst> <zone> <KEY> — .node-meta value; rc 0 value printed, 1 absent, 2 error.
# Uses devnet-lib.sh's tn_node_meta_get when it is there, else the same read inline.
nc_meta() {
    local inst="$1" zone="$2" key="$3" out rc
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

# nc_check_installed <inst> <zone> <node> <local-copy> [<existing>] — re-read the installed
# file into <local-copy>, check owner/group/mode, and run the validator on it.
nc_check_installed() {
    local inst="$1" zone="$2" node="$3" copy="$4" existing="${5:-}" nc="${NC_DIR}/network-config" perm rc
    rc=0; nc_fetch "${inst}" "${zone}" "${nc}" "${copy}" || rc=$?
    if [ "${rc}" -ne 0 ]; then echo "    ❌ could not re-read ${nc} (rc ${rc})"; return 1; fi
    # Owner must be the service account and nobody but the owner may write: the install
    # sets 0640, but the UI's set-hostname rewrites the file with tee+mv under the caller's
    # umask (R2 review, I3), so an exact -perm 0640 would fail a node that is fine.
    perm="$(tn_iap_ssh "${inst}" "${zone}" \
        "sudo find '${nc}' -maxdepth 0 -user '${NC_USER}' -group '${NC_GROUP}' ! -perm /022" | tr -d '\r')" || perm=""
    if [ "${perm}" != "${nc}" ]; then
        echo "    ❌ ${nc} is not owned by ${NC_USER}:${NC_GROUP} with no group/world write bit"
        return 1
    fi
    if [ -n "${existing}" ]; then
        python3 "${PY}" validate "${CTX[@]}" --node "${node}" --existing "${existing}" "${copy}" || return 1
    else
        python3 "${PY}" validate "${CTX[@]}" --node "${node}" "${copy}" || return 1
    fi
}

# nc_node_bls <inst> <zone> — the bls_public_key in the node's own <datadir>/node-info.yaml.
nc_node_bls() {
    tn_iap_ssh "$1" "$2" "sudo grep -m1 -E '^bls_public_key:' '${NC_DIR}/node-info.yaml'" \
        | tr -d '\r' | sed -e 's/^bls_public_key:[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/'
}

# --- fleet loop ---------------------------------------------------------------------------
INDICES=()
while IFS= read -r _idx; do INDICES+=("$_idx"); done <<< "${SELECTION}"
echo ""
echo ">>> ${MODE} targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"

done_nodes=()
failed=()

for i in "${INDICES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    rendered="${OUT_DIR}/${node}.yaml"
    echo ""
    echo ">>> [${node}] ${MODE} network-config on ${inst} (${zone}) role=${role}"

    if ! nc_resolve "${inst}" "${zone}" "${role}"; then
        echo "❌ [${node}] could not resolve the service account / datadir from .node-meta"
        failed+=("${node}"); continue
    fi
    nc="${NC_DIR}/network-config"
    echo "    datadir ${NC_DIR}, owner ${NC_USER}:${NC_GROUP}"

    if [ "${MODE}" = "verify" ]; then
        if nc_check_installed "${inst}" "${zone}" "${node}" "${WORK}/${node}.installed"; then
            done_nodes+=("${node}")
        else
            echo "❌ [${node}] installed ${nc} failed verification"
            failed+=("${node}")
        fi
        continue
    fi

    # Right file for the right node: the datadir's node-info.yaml must carry this node's key.
    want_bls="$(sed -n -e 's/^bls_public_key:[[:space:]]*//p' \
        "${GENESIS_LOCAL_DIR}/$([ "${role}" = "observer" ] && echo observers || echo validators)/${node}.yaml" | head -1)"
    have_bls="$(nc_node_bls "${inst}" "${zone}" || true)"
    if [ -z "${want_bls}" ] || [ "${have_bls}" != "${want_bls}" ]; then
        echo "❌ [${node}] ${NC_DIR}/node-info.yaml BLS key '${have_bls:0:16}…' is not the local ${node}'s '${want_bls:0:16}…' (keygen not run, or wrong node)"
        failed+=("${node}"); continue
    fi

    existing="${WORK}/${node}.existing"
    rc=0; nc_fetch "${inst}" "${zone}" "${nc}" "${existing}" || rc=$?
    case "${rc}" in
        0) echo "    existing ${nc}: $(wc -c < "${existing}" | tr -d ' ') bytes (keeping only its hostname line)" ;;
        1) echo "    no existing ${nc}" ;;
        *) echo "❌ [${node}] could not read the existing ${nc}"; failed+=("${node}"); continue ;;
    esac

    merged="${WORK}/${node}.merged"
    if ! python3 "${PY}" merge --rendered "${rendered}" --existing "${existing}" --out "${merged}" \
        || ! python3 "${PY}" validate "${CTX[@]}" --node "${node}" --existing "${existing}" "${merged}"; then
        echo "❌ [${node}] merged file failed; nothing uploaded"
        failed+=("${node}"); continue
    fi

    tmp="/tmp/tn-network-config.${node}.$$"
    if ! tn_iap_scp "${merged}" "${inst}" "${zone}" "${tmp}"; then
        echo "❌ [${node}] upload to ${tmp} failed"
        failed+=("${node}"); continue
    fi
    if ! tn_iap_ssh "${inst}" "${zone}" \
        "rc=0; sudo install -o '${NC_USER}' -g '${NC_GROUP}' -m 0640 -- '${tmp}' '${nc}' || rc=\$?; rm -f -- '${tmp}'; exit \$rc"; then
        echo "❌ [${node}] sudo install into ${nc} failed"
        failed+=("${node}"); continue
    fi

    installed="${WORK}/${node}.installed"
    if ! nc_check_installed "${inst}" "${zone}" "${node}" "${installed}" "${existing}" \
        || ! cmp -s "${merged}" "${installed}"; then
        echo "❌ [${node}] re-read of ${nc} does not match what was uploaded, or fails validation"
        failed+=("${node}"); continue
    fi
    state="$(tn_iap_ssh "${inst}" "${zone}" "systemctl is-active '$(tn_service_for_role "${role}")' 2>/dev/null || true" | tr -d '[:space:]' || true)"
    if [ "${state}" = "active" ]; then
        echo "    ⚠️  $(tn_service_for_role "${role}") is already running: it reads ${nc} at its NEXT start (not restarted here)"
    fi
    echo "    ✓ installed + re-read + validated ${nc}"
    done_nodes+=("${node}")
done

echo ""
echo "========================================="
echo "network-config ${MODE} summary"
echo "========================================="
echo "ok (${#done_nodes[@]}):"
for n in "${done_nodes[@]+"${done_nodes[@]}"}"; do echo "  - ${n}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    exit 1
fi
echo "all targeted nodes: ${MODE} ok."
