#!/usr/bin/env bash
#
# devnet-stake-node5.sh — make node 5 the fifth validator after a genesis reset.
#
# Genesis seats nodes 1-4 with nextCommitteeSize 4. Node 5 is a unified node outside the
# genesis committee that syncs as an observer. This script mints its ConsensusNFT, stakes it
# and activates it, so five eligible validators rotate through the four seats. Node 5 is found
# by role: the first `observer` entry of NODE_ROLES (config.sh); the reference validator of
# step 4 is the first `validator` entry. No `observer` entry: exit 2.
#
#   1. preflight     read-only checks; refuses on any mismatch (below)
#   2. mint          Safe.execTransaction(registry, 0, mint(node5), CALL, 0,0,0, 0x0, 0x0, sig)
#                    from the contracts admin, a Safe owner. Threshold 1, so one pre-approved
#                    signature suffices: r = admin address (left-padded), s = 0, v = 1. That is
#                    the common/Makefile `submit` / `mint-submit` shape; the Safe's own nonce()
#                    is consumed (no nonce argument), and getTransactionHash is logged.
#   3. stake         calldata = `telcoin keytool export-staking-args --calldata` run on node 5's
#                    node-info.yaml (the image's own encoder, so the ABI always matches the
#                    image's genesis registry); value = stakeConfig(getCurrentStakeVersion())
#                    .stakeAmount; sent from node 5's key after an eth_call simulation passes.
#   4. sync gate     node 5's eth_blockNumber within SYNC_MAX_LAG (5) blocks of the reference
#                    validator's and node 5's tn_nodeMode == "Observer", polled until
#                    SYNC_TIMEOUT_SECS; each node read on its own loopback over IAP (STEP 4 below).
#   5. activate      ConsensusRegistry.activate() from node 5's key -> PendingActivation.
#   6. watch         getValidator(node5) -> Active at the next epoch boundary, then committee
#                    membership for --watch-epochs K epochs, stating whether it changed. Two
#                    lines per epoch from activationEpoch: node 5's status, its tn_nodeMode,
#                    whether it is in that epoch's committee, and what to check on the
#                    validators (allowlist entry, admission window one epoch later, first seat).
#
# Seating arithmetic (tn-contracts ConsensusRegistry, the copy pinned by the image): activate()
# in epoch N sets activationEpoch = N+1. At the close of N, concludeEpoch flips it to Active and
# stores the committee the protocol drew for epoch N+3 (newEpoch + 2, _updateEpochInfo). The
# N+1 and N+2 committees were fixed before activation, so N+3 is the first epoch node 5 can sit
# in. Five eligible for four seats means any single draw can leave it out.
#
# WHERE EACH READ GOES (launch 2). Every chain read and every send (steps 1-3, 5, 6) uses --rpc,
# by default RPC_URL from config.sh: the public RPC node (https://rpc.<BASE_DOMAIN>). A
# transaction submitted there is forwarded by the RPC node to the committee's gateways.
# tn_getNextCommitteeSize (preflight) is a tn_* call to the same URL: the RPC node answers it
# natively, and a failure is tolerated (shown as n/a). Step 4 is different, see its note.
#
# STEP 4 READS THE NODES THEMSELVES. https://nodeN.<BASE_DOMAIN> is now a worker gateway that sends
# every read and every tn_* call to the RPC node, so a head or tn_nodeMode read through it is
# answered by the RPC node, not by node N, and the gate would not be measuring node 5. By default
# step 4 runs each probe on the node's own host: `curl http://127.0.0.1:${NODE_RPC_PORT}` (config.sh,
# 8545) through the lib's tn_iap_ssh, one ssh round trip per probe, an ssh rc 255 retried once:
# node 5's head and tn_nodeMode on node 5's instance, the reference head on the first validator's.
# The same IAP read gives node 5's tn_nodeMode in step 6. --node5-rpc / --ref-rpc URL switch that
# read back to the URL (a fleet without gateways).
#
# Preflight refuses unless: chain id == CHAIN_ID; the registry has code and owner() == SAFE_ADDR;
# the Safe threshold is 1 and isOwner(SAFE_EXTRA_OWNER); the registry is not paused; node 5's
# address is set (no placeholder) and equals the execution_address in its node-info file;
# node 5 is not retired or past PendingActivation in a way this script cannot continue; node 5
# holds stake + gas and the admin holds gas; each secret's key belongs to the expected address;
# the stake simulation shows the PoP and value accepted (before the mint it may revert ONLY with
# InvalidTokenId, the missing NFT, which is checked after the PoP and the value).
#
# KEY HANDLING. Keys are never on argv, in the environment, or printed:
#   tn_secret <name> | python3 devnet-stake-node5.py import-key --dir <0700 tmp> --name <n> --expect <addr>
# The key goes from Secret Manager straight into the helper's stdin (not even a shell
# variable). The helper types it into `cast wallet import -i` on a private pty, under a random
# password kept in a 0600 file in the same 0700 mktemp dir, and checks the keystore's address.
# cast then signs with `--keystore <dir>/<n> --password-file <dir>/<n>.pw`; the dir is removed on
# exit (trap). Why not the alternatives: `--private-key` puts the key on argv (ps, /proc); this
# cast (foundry 1.8.x) documents the `env://VAR` signer form only for --tempo.sponsor-signer, not
# for --private-key/--from; and `cast wallet import` reads a key only from argv or /dev/tty.
# The script refuses to run under `set -x`.
#
# Usage:
#   ./devnet-stake-node5.sh                    # DRY RUN: preflight + every call it would make
#   ./devnet-stake-node5.sh --yes              # do it
#   ./devnet-stake-node5.sh --yes --from-step 5   # resume (step 1 always runs; every step
#                                              # also skips itself when the chain shows it done)
#   ./devnet-stake-node5.sh --yes --node5-rpc http://<node5>:8545 --ref-rpc http://<node1>:8545
#                                              # a fleet without gateways: step 4 reads these URLs
# Options:
#   --rpc URL            chain RPC for reads and sends (default RPC_URL from config.sh, the
#                        public RPC node; it forwards a submitted transaction to the committee)
#   --from-step N        skip steps 2..N-1
#   --watch-epochs K     epochs of committee membership to log in step 6 (default 3; 0 = none)
#   --node-info PATH     node 5's node-info (default genesis/<tn_role_dir>/<NODE_NAME>.yaml of the
#                        observer entry, i.e. genesis/observers/node5.yaml)
#   --node5-rpc URL      read node 5's head and tn_nodeMode (steps 4, 6) from URL instead of over
#                        IAP (default: over IAP, 127.0.0.1:${NODE_RPC_PORT} on node 5's host)
#   --ref-rpc URL        read the reference head (step 4) from URL instead of over IAP (default:
#                        over IAP on the first validator's host)
#   --node5-via-iap      accepted for old command lines: IAP is the default (it still wins over
#                        --node5-rpc)
#   --poll SECS          poll interval (default 30)
# Env: ADMIN_PK_SECRET (default devnet-contracts-admin-pk), KEYTOOL_IMAGE (default DOCKER_IMAGE),
#      SYNC_TIMEOUT_SECS (1800), SYNC_MAX_LAG (5), EPOCH_TIMEOUT_SECS (2 x EPOCH_DURATION_SECS + 600).
#
# REHEARSAL HOOK (tests only): TN_STAKE_NODE5_TEST_HOOKS=<file> is sourced after every function
# below is defined, so a rehearsal can replace tn_secret (stub keys), node5_mode (anvil has no
# tn_nodeMode), host_rpc / node5_head / ref_head (no IAP) or any other function. A banner is
# printed when it is set. CONFIG_FILE (honoured by devnet-lib.sh) points the run at a rehearsal
# config. Never set either on a live run.

set -euo pipefail
case "$-" in
    *x*) echo "❌ refusing to run under 'set -x' (xtrace would log the signing commands)" >&2; exit 1 ;;
esac

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${REPO_DIR}/devnet-lib.sh"
HELPER="${REPO_DIR}/devnet-stake-node5.py"

# --- constants ------------------------------------------------------------------
# Genesis-assigned ConsensusRegistry: telcoin-network crates/tn-reth/src/system_calls.rs
# (CONSENSUS_REGISTRY_ADDRESS) and common/Makefile's activate / is-validator targets.
REGISTRY="0x07E17e17E17e17E17e17E17E17E17e17e17E17e1"
BLS_PRECOMPILE="0x000000000000000000000000000000000000B151"   # native blsVerify used by stake()
ZERO_ADDR="0x0000000000000000000000000000000000000000"
STATUS_NAMES=(Undefined Staked PendingActivation Active PendingExit Exited Any)
VINFO_T="(address,uint32,uint32,uint8,bool,uint8,uint8)"         # IConsensusRegistry.ValidatorInfo
EXEC_SIG="execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)(bool)"
TXHASH_SIG="getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)"

# --- args -----------------------------------------------------------------------
CONFIRM=0
RPC="${RPC_URL}"
FROM_STEP=1
WATCH_EPOCHS=3
NODE5_INFO=""                     # default set after the role lookup below
NODE5_RPC=""                      # empty: step 4 reads node 5 over IAP (the default)
REF_RPC=""                        # empty: step 4 reads the reference validator over IAP
NODE5_VIA_IAP=0
POLL=30
usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]:-$0}" | sed '$d' | sed 's/^# \{0,1\}//'; }
need_val() { [ "$#" -ge 2 ] && [ -n "$2" ] || { echo "❌ $1 needs a value" >&2; exit 1; }; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --rpc) need_val "$@"; RPC="$2"; shift ;;
        --from-step) need_val "$@"; FROM_STEP="$2"; shift ;;
        --watch-epochs) need_val "$@"; WATCH_EPOCHS="$2"; shift ;;
        --node-info) need_val "$@"; NODE5_INFO="$2"; shift ;;
        --node5-rpc) need_val "$@"; NODE5_RPC="$2"; shift ;;
        --ref-rpc) need_val "$@"; REF_RPC="$2"; shift ;;
        --node5-via-iap) NODE5_VIA_IAP=1 ;;
        --poll) need_val "$@"; POLL="$2"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "❌ unknown argument '$1' (see --help)" >&2; exit 1 ;;
    esac
    shift
done
for _n in FROM_STEP WATCH_EPOCHS POLL; do
    case "${!_n}" in ''|*[!0-9]*) echo "❌ ${_n} must be a non-negative integer (got '${!_n}')" >&2; exit 1 ;; esac
done
[ "${FROM_STEP}" -ge 1 ] && [ "${FROM_STEP}" -le 6 ] || { echo "❌ --from-step must be 1..6" >&2; exit 1; }
[ "${POLL}" -ge 1 ] || POLL=1
# --node5-via-iap is the default now; kept for old command lines, and as before it wins over --node5-rpc
if [ "${NODE5_VIA_IAP}" -eq 1 ]; then NODE5_RPC=""; fi

# Node 5 and the reference validator by role (config.sh NODE_ROLES), not by array index:
# node 5 = the first `observer` entry, the reference = the first `validator` entry.
NODE5_IDX="$(tn_indices_by_role observer)" || exit 2
NODE5_IDX="${NODE5_IDX%%$'\n'*}"
REF_IDX="$(tn_indices_by_role validator)" || exit 2
REF_IDX="${REF_IDX%%$'\n'*}"
[ -n "${NODE5_IDX}" ] || { echo "❌ no 'observer' entry in NODE_ROLES (config.sh): no node 5 to stake" >&2; exit 2; }
[ -n "${REF_IDX}" ] || { echo "❌ no 'validator' entry in NODE_ROLES (config.sh): no reference validator for step 4" >&2; exit 2; }
[ -n "${NODE5_INFO}" ] || NODE5_INFO="${REPO_DIR}/genesis/$(tn_role_dir "${NODE5_IDX}")/${NODE_NAMES[$NODE5_IDX]}.yaml"

ADMIN_PK_SECRET="${ADMIN_PK_SECRET:-devnet-contracts-admin-pk}"
ADMIN_ADDR="${SAFE_EXTRA_OWNER}"
NODE5_ADDR="${EXECUTION_ADDRESSES[$NODE5_IDX]}"
NODE5_INSTANCE="${INSTANCE_NAMES[$NODE5_IDX]}"
REF_NAME="${NODE_NAMES[$REF_IDX]}"
KEYTOOL_IMAGE="${KEYTOOL_IMAGE:-${DOCKER_IMAGE}}"
SYNC_TIMEOUT_SECS="${SYNC_TIMEOUT_SECS:-1800}"
SYNC_MAX_LAG="${SYNC_MAX_LAG:-5}"
EPOCH_TIMEOUT_SECS="${EPOCH_TIMEOUT_SECS:-$((2 * EPOCH_DURATION_SECS + 600))}"

# --- helpers --------------------------------------------------------------------
die() { echo "❌ $*" >&2; exit 1; }
lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
is_addr() { case "$1" in 0x*) [ "${#1}" -eq 42 ] && [ -z "$(printf '%s' "${1#0x}" | tr -d '0-9a-fA-F')" ] ;; *) return 1 ;; esac; }
first() { printf '%s' "${1%% *}"; }                 # "1000 [1e3]" -> "1000"
big() { python3 "${HELPER}" int "$@"; }             # big-integer add|mul|ge|eq
tel() { cast from-wei "$1"; }
plan() { echo "    → $*"; }
rd() { cast call "$@" --rpc-url "${RPC}"; }          # read against the chain RPC
step_header() { echo ""; echo ">>> step $1: $2"; }
skip_step() { [ "$1" -lt "${FROM_STEP}" ] && { echo "    skipped (--from-step ${FROM_STEP})"; return 0; }; return 1; }

# word <hex> <n>: the n-th 32-byte word of an ABI-encoded static return, as an integer (small words only)
word() { local h="${1#0x}"; printf '%d' "$((16#${h:$((64 * $2)):64}))"; }

# read_validator: V_MINTED V_RETIRED V_STATUS V_ACT_EPOCH for node 5. getValidator reverts
# (InvalidTokenId) for an address that was never minted, so balanceOf/isRetired go first.
read_validator() {
    local raw
    V_MINTED="$(first "$(rd "${REGISTRY}" "balanceOf(address)(uint256)" "${NODE5_ADDR}")")"
    V_RETIRED="$(rd "${REGISTRY}" "isRetired(address)(bool)" "${NODE5_ADDR}")"
    V_STATUS=0; V_ACT_EPOCH=0
    [ "${V_MINTED}" = "0" ] && return 0
    raw="$(rd "${REGISTRY}" "getValidator(address)" "${NODE5_ADDR}")"
    V_ACT_EPOCH="$(word "${raw}" 1)"
    V_STATUS="$(word "${raw}" 3)"
}
status_name() { printf '%s' "${STATUS_NAMES[$1]:-?$1}"; }
show_validator() {
    if [ "${V_MINTED}" = "0" ]; then echo "    node 5 ${NODE5_ADDR}: no ConsensusNFT (not minted), retired=${V_RETIRED}"; return; fi
    echo "    node 5 getValidator: $(rd "${REGISTRY}" "getValidator(address)(${VINFO_T})" "${NODE5_ADDR}")"
    echo "      = status $(status_name "${V_STATUS}") (${V_STATUS}), activationEpoch ${V_ACT_EPOCH}"
}
# current_epoch: the registry's current epoch as a decimal, or rc 1 with a message. A failed,
# empty or non-numeric read is retried (3 tries, 5 s apart). Every epoch read goes through here:
# `first "$(rd …)"` alone loses rd's failure and can print "" with rc 0.
current_epoch() {
    local out="" try=1
    while :; do
        if out="$(rd "${REGISTRY}" "getCurrentEpoch()(uint32)")"; then
            out="$(first "${out}")"
            case "${out}" in ''|*[!0-9]*) ;; *) printf '%s\n' "${out}"; return 0 ;; esac
        fi
        [ "${try}" -lt 3 ] || break
        try=$((try + 1)); sleep 5
    done
    echo "❌ getCurrentEpoch() at ${RPC}: no decimal epoch after ${try} tries (last answer '${out}')" >&2
    return 1
}
# wait_for_epoch <n>: return once the current epoch is >= n, leaving it in EPOCH_SEEN. An
# unreadable epoch keeps waiting, it never ends the wait (that would read a committee that is
# not final yet); 10 unreadable polls in a row, or EPOCH_TIMEOUT_SECS, stop the run.
wait_for_epoch() {
    local start=${SECONDS} fails=0
    while :; do
        if EPOCH_SEEN="$(current_epoch)"; then
            fails=0
            [ "${EPOCH_SEEN}" -lt "$1" ] || return 0
        else
            fails=$((fails + 1))
            [ "${fails}" -lt 10 ] || die "the current epoch was unreadable ${fails} polls in a row while waiting for epoch $1"
            echo "      (current epoch unreadable, ${fails}/10 in a row; still waiting for epoch $1)"
        fi
        [ $((SECONDS - start)) -lt "${EPOCH_TIMEOUT_SECS}" ] || die "epoch $1 did not begin within ${EPOCH_TIMEOUT_SECS}s"
        sleep "${POLL}"
    done
}
# committee <epoch>: sorted lower-case member addresses, space separated; rc 1 if the read fails
committee() {
    local out
    out="$(rd "${REGISTRY}" "getCommitteeValidators(uint32)(${VINFO_T}[])" "$1")" || return 1
    printf '%s\n' "${out}" | grep -oE '0x[0-9a-fA-F]{40}' | tr '[:upper:]' '[:lower:]' | sort | tr '\n' ' ' | sed 's/ $//'
}
has_node5() { case " $1 " in *" $(lc "${NODE5_ADDR}") "*) return 0 ;; *) return 1 ;; esac; }

# revert selectors (cast sig "<error>") for the errors the stake path can raise
error_name() {
    case "$1" in
        0xed15e6cf) echo "InvalidTokenId(uint256): no ConsensusNFT" ;;
        0x37f33ed8) echo "LowLevelCallFailure(bytes): the BLS precompile at ${BLS_PRECOMPILE} failed or is absent" ;;
        0xa865bb35) echo "InvalidProofOfPossession((bytes)): the PoP in node-info.yaml does not verify for ${NODE5_ADDR}" ;;
        0x88b4590c) echo "InvalidStakeAmount(uint256)" ;;
        0x674469f2) echo "InvalidBLSPubkey()" ;;
        0x8d12779f) echo "DuplicateBLSPubkey(): this BLS key is already registered" ;;
        0x61f51356) echo "RequiresConsensusNFT()" ;;
        0x774f7f12) echo "InvalidStatus(uint8)" ;;
        0x9fb08779) echo "AlreadyDefined(address)" ;;
        0xd93c0665) echo "EnforcedPause(): the registry is paused" ;;
        *) echo "unrecognised revert $1" ;;
    esac
}
# cast prints an unresolved selector as `custom error 0x…`; once it has resolved the name
# (cast 1.8 caches lookups in ~/.foundry/cache/signatures) only the raw `data: "0x…"` field
# still carries it. Match both; print nothing (rc 0) when neither is present, so a caller
# under `set -e` can test the result instead of dying.
revert_selector() {
    printf '%s' "$1" | grep -oiE '(custom error |data: "?)0x[0-9a-f]{8}' | head -1 \
        | grep -oiE '0x[0-9a-f]{8}$' | tr '[:upper:]' '[:lower:]' || true
}

# send <signer admin|node5> <label> <cast send args...>: signs with that keystore, prints one
# receipt line, fails on a reverted tx. Only file paths reach argv.
send() {
    local signer="$1" label="$2" out
    shift 2
    if ! out="$(cast send "$@" --rpc-url "${RPC}" --keystore "${KS_DIR}/${signer}" \
            --password-file "${KS_DIR}/${signer}.pw" --json </dev/null)"; then
        die "${label}: cast send failed (see the error above)"
    fi
    printf '%s' "${out}" | python3 "${HELPER}" receipt | sed 's/^/    ✓ '"${label}"': /' \
        || die "${label}: transaction reverted"
}

# load_key <name> <secret> <address>: Secret Manager -> 0700 keystore, address checked
load_key() {
    local got
    if ! got="$(tn_secret "$2" | python3 "${HELPER}" import-key --dir "${KS_DIR}" --name "$1" --expect "$3")"; then
        die "could not load the key in Secret Manager ${2} as ${3} (reason above; the key is never printed)"
    fi
    echo "    ✓ Secret Manager ${2} → keystore for ${got} (matches)"
}

# Node probes (step 4, and tn_nodeMode in step 6). https://nodeN.<domain> is a worker gateway
# that answers reads from the RPC node, so each node is asked on its own loopback over IAP,
# unless --node5-rpc / --ref-rpc gave a URL. The rehearsal hook may replace any of these.
# host_rpc <index> <method>: one JSON-RPC call (no params) to http://127.0.0.1:NODE_RPC_PORT on
# that host: one ssh round trip through the lib's tn_iap_ssh, an ssh rc 255 retried once.
host_rpc() {
    local inst="${INSTANCE_NAMES[$1]}" zone="${ZONES[$1]}" body cmd out rc=0
    body="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$2\",\"params\":[]}"
    cmd="curl -fsS --max-time 10 -H 'content-type: application/json' --data '${body}' http://127.0.0.1:${NODE_RPC_PORT:-8545}"
    out="$(tn_iap_ssh "${inst}" "${zone}" "${cmd}" </dev/null)" || rc=$?
    if [ "${rc}" -eq 255 ]; then
        echo "⚠️  ${inst}: ssh rc 255 reading $2; retrying once" >&2
        rc=0; out="$(tn_iap_ssh "${inst}" "${zone}" "${cmd}" </dev/null)" || rc=$?
    fi
    [ "${rc}" -eq 0 ] || return "${rc}"
    printf '%s\n' "${out}" | python3 "${HELPER}" rpc-result
}
node5_head() {
    local h
    if [ -n "${NODE5_RPC}" ]; then cast block-number --rpc-url "${NODE5_RPC}"
    else h="$(host_rpc "${NODE5_IDX}" eth_blockNumber)" && cast to-dec "${h}"; fi
}
node5_mode() {
    if [ -n "${NODE5_RPC}" ]; then cast rpc tn_nodeMode --rpc-url "${NODE5_RPC}" | tr -d '"'
    else host_rpc "${NODE5_IDX}" tn_nodeMode; fi
}
ref_head() {
    local h
    if [ -n "${REF_RPC}" ]; then cast block-number --rpc-url "${REF_RPC}"
    else h="$(host_rpc "${REF_IDX}" eth_blockNumber)" && cast to-dec "${h}"; fi
}
# sync_probe: prints one status line; rc 0 iff in sync (lag <= SYNC_MAX_LAG and mode Observer)
sync_probe() {
    local h5 h1 mode lag
    h5="$(node5_head 2>/dev/null)" || h5=""
    h1="$(ref_head 2>/dev/null)" || h1=""
    mode="$(node5_mode 2>/dev/null)" || mode=""
    case "${h5}${h1}" in ''|*[!0-9]*) echo "      node 5 head '${h5:-?}', ${REF_NAME} head '${h1:-?}', mode '${mode:-?}' (unreachable?)"; return 1 ;; esac
    lag=$((h1 - h5)); [ "${lag}" -lt 0 ] && lag=$((-lag))
    echo "      node 5 head ${h5}, ${REF_NAME} head ${h1} (lag ${lag}), tn_nodeMode '${mode:-?}'"
    [ "${lag}" -le "${SYNC_MAX_LAG}" ] && [ "${mode}" = "Observer" ]
}
# epoch_line <epoch> <committee> <membership note> <what to check>: step 6's two lines per epoch.
# The status is the last getValidator read (no extra chain call); tn_nodeMode is node 5's own
# answer now (over IAP unless --node5-rpc).
epoch_line() {
    local mode
    mode="$(node5_mode 2>/dev/null)" || mode=""
    echo "    epoch $1: node 5 status at activation $(status_name "${V_STATUS}"), tn_nodeMode now '${mode:-?}'; committee($1): $2 — $3"
    echo "      from the start of epoch $1, check on the validators: $4"
}

if [ -n "${TN_STAKE_NODE5_TEST_HOOKS:-}" ]; then
    echo "⚠️  TEST HOOKS ACTIVE: sourcing ${TN_STAKE_NODE5_TEST_HOOKS} (rehearsal only; never on a live run)"
    # shellcheck source=/dev/null
    source "${TN_STAKE_NODE5_TEST_HOOKS}"
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tn-stake-node5.XXXXXX")"
trap 'rm -rf "${WORK_DIR}"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# A terminal hang-up or a dead pipe (run piped into tee) must also reach the EXIT trap:
# bash skips it when an untrapped signal kills the shell, which would leave the keystores
# beside their password files in WORK_DIR (R3 review finding).
trap 'exit 129' HUP
trap 'exit 141' PIPE
chmod 700 "${WORK_DIR}"
KS_DIR="${WORK_DIR}/ks"
mkdir -m 700 "${KS_DIR}"

echo "=========================================="
echo "devnet: mint + stake + activate node 5"
echo "RPC:         ${RPC}"
echo "Registry:    ${REGISTRY}"
echo "Safe:        ${SAFE_ADDR} (admin owner ${ADMIN_ADDR}, key: Secret Manager ${ADMIN_PK_SECRET})"
echo "Node 5:      ${NODE5_ADDR} (key: Secret Manager ${NODE5_VALIDATOR_PK_SECRET})"
echo "Node info:   ${NODE5_INFO}"
echo "Keytool:     ${KEYTOOL_IMAGE}"
[ "${CONFIRM}" -eq 1 ] && echo "Mode:        APPLY (--yes), from step ${FROM_STEP}" \
    || echo "Mode:        DRY RUN (no --yes): reads only, every send is printed, nothing is sent"
echo "=========================================="

# ================================================================================
step_header 1 "preflight"
for bin in cast python3 docker; do
    command -v "${bin}" >/dev/null 2>&1 || die "'${bin}' not on PATH"
done
is_addr "${NODE5_ADDR}" || die "EXECUTION_ADDRESSES[${NODE5_IDX}] is '${NODE5_ADDR}', not an address: fill config.sh with node 5's address first"
is_addr "${ADMIN_ADDR}" || die "SAFE_EXTRA_OWNER '${ADMIN_ADDR}' is not an address"
case "${KEYTOOL_IMAGE}" in *PLACEHOLDER*) die "KEYTOOL_IMAGE/DOCKER_IMAGE still holds a placeholder: '${KEYTOOL_IMAGE}'" ;; esac
[ -f "${NODE5_INFO}" ] || die "node-info not found: ${NODE5_INFO}"

rpc_chain="$(cast chain-id --rpc-url "${RPC}")" || die "RPC ${RPC} unreachable"
[ "${rpc_chain}" = "${CHAIN_ID}" ] || die "chain id ${rpc_chain} at ${RPC}, expected ${CHAIN_ID}"
echo "    ✓ chain id ${rpc_chain}"
[ "$(cast code "${REGISTRY}" --rpc-url "${RPC}" | wc -c)" -gt 10 ] || die "no code at the registry ${REGISTRY}"
reg_owner="$(rd "${REGISTRY}" "owner()(address)")"
[ "$(lc "${reg_owner}")" = "$(lc "${SAFE_ADDR}")" ] || die "registry owner() is ${reg_owner}, not the Safe ${SAFE_ADDR}"
echo "    ✓ registry owner() = Safe ${reg_owner}"
[ "$(rd "${REGISTRY}" "paused()(bool)")" = "false" ] || die "the registry is paused (stake/activate would revert)"

info_addr="$(sed -n 's/^execution_address:[[:space:]]*"\{0,1\}\(0x[0-9a-fA-F]\{40\}\)"\{0,1\}[[:space:]]*$/\1/p' "${NODE5_INFO}")"
[ -n "${info_addr}" ] || die "no execution_address in ${NODE5_INFO}"
[ "$(lc "${info_addr}")" = "$(lc "${NODE5_ADDR}")" ] || die "address mismatch: EXECUTION_ADDRESSES[${NODE5_IDX}] = ${NODE5_ADDR} but ${NODE5_INFO} execution_address = ${info_addr}"
echo "    ✓ node 5 address ${NODE5_ADDR} == EXECUTION_ADDRESSES[${NODE5_IDX}] == node-info execution_address"

next_size="$(first "$(rd "${REGISTRY}" "getNextCommitteeSize()(uint16)")")"
# a tn_* call to the chain RPC (the RPC node answers it natively); tolerated if absent
tn_next="$(cast rpc tn_getNextCommitteeSize --rpc-url "${RPC}" 2>/dev/null)" || tn_next="n/a (no tn_ namespace at this RPC)"
eligible="$(first "$(rd "${REGISTRY}" "getEligibleValidatorCount()(uint256)")")"
EPOCH_NOW="$(current_epoch)" || die "cannot read the current epoch (see above)"
echo "    nextCommitteeSize ${next_size} (tn_getNextCommitteeSize: ${tn_next}); eligible validators ${eligible}; current epoch ${EPOCH_NOW}"
cm="$(committee "${EPOCH_NOW}")" || die "getCommitteeValidators(${EPOCH_NOW}) failed"
echo "    committee(${EPOCH_NOW}): ${cm}"

read_validator
show_validator
[ "${V_RETIRED}" = "true" ] && die "node 5 ${NODE5_ADDR} is retired: that address can never rejoin"
if [ "${V_STATUS}" -ge 4 ]; then
    die "node 5 is $(status_name "${V_STATUS}"): exiting or exited, this script does not handle that"
fi

threshold="$(first "$(cast call "${SAFE_ADDR}" "getThreshold()(uint256)" --rpc-url "${RPC}")")"
is_owner="$(cast call "${SAFE_ADDR}" "isOwner(address)(bool)" "${ADMIN_ADDR}" --rpc-url "${RPC}")"
safe_nonce="$(first "$(cast call "${SAFE_ADDR}" "nonce()(uint256)" --rpc-url "${RPC}")")"
owners="$(cast call "${SAFE_ADDR}" "getOwners()(address[])" --rpc-url "${RPC}")"
echo "    Safe owners (${threshold}-of-$(printf '%s' "${owners}" | grep -oE '0x[0-9a-fA-F]{40}' | wc -l | tr -d ' ')): ${owners}"
echo "    Safe nonce ${safe_nonce}"
[ "${V_MINTED}" != "0" ] || {
    [ "${is_owner}" = "true" ] || die "admin ${ADMIN_ADDR} is not an owner of the Safe ${SAFE_ADDR}"
    [ "${threshold}" = "1" ] || die "Safe threshold is ${threshold}; one pre-approved signature needs threshold 1"
    echo "    ✓ admin ${ADMIN_ADDR} isOwner, threshold 1"
}

stake_version="$(first "$(rd "${REGISTRY}" "getCurrentStakeVersion()(uint8)")")"
STAKE_WEI="$(cast to-dec "0x$(rd "${REGISTRY}" "stakeConfig(uint8)" "${stake_version}" | cut -c3-66)")"
gas_price="$(cast gas-price --rpc-url "${RPC}")"
echo "    stake version ${stake_version}: stakeAmount ${STAKE_WEI} wei ($(tel "${STAKE_WEI}") TEL); gas price ${gas_price} wei"

node5_bal="$(cast balance "${NODE5_ADDR}" --rpc-url "${RPC}")"
node5_need="$(big mul "${gas_price}" 3000000)"                       # stake + activate, generous
[ "${V_STATUS}" -ge 1 ] || node5_need="$(big add "${node5_need}" "${STAKE_WEI}")"
big ge "${node5_bal}" "${node5_need}" \
    || die "node 5 holds $(tel "${node5_bal}") TEL, needs $(tel "${node5_need}") TEL (stake + gas)"
echo "    ✓ node 5 balance $(tel "${node5_bal}") TEL >= $(tel "${node5_need}") TEL needed"
if [ "${V_MINTED}" = "0" ]; then
    admin_bal="$(cast balance "${ADMIN_ADDR}" --rpc-url "${RPC}")"
    big ge "${admin_bal}" "$(big mul "${gas_price}" 500000)" || die "admin ${ADMIN_ADDR} holds $(tel "${admin_bal}") TEL, not enough gas for the mint"
    echo "    ✓ admin balance $(tel "${admin_bal}") TEL"
fi

NEED_ADMIN=0; NEED_NODE5=0
[ "${V_MINTED}" = "0" ] && [ "${FROM_STEP}" -le 2 ] && NEED_ADMIN=1
[ "${V_STATUS}" -lt 2 ] && NEED_NODE5=1
[ "${NEED_ADMIN}" -eq 1 ] && load_key admin "${ADMIN_PK_SECRET}" "${ADMIN_ADDR}"
[ "${NEED_NODE5}" -eq 1 ] && load_key node5 "${NODE5_VALIDATOR_PK_SECRET}" "${NODE5_ADDR}"

STAKE_CALLDATA=""
if [ "${V_STATUS}" -lt 1 ]; then
    mkdir -m 755 "${WORK_DIR}/ni"                         # the container runs as a non-root uid
    cp "${NODE5_INFO}" "${WORK_DIR}/ni/node-info.yaml"     # node-info.yaml is public material
    chmod 644 "${WORK_DIR}/ni/node-info.yaml"
    ka_out="$(docker run --rm --entrypoint telcoin -v "${WORK_DIR}/ni:/ni:ro" "${KEYTOOL_IMAGE}" \
        keytool export-staking-args --node-info /ni/node-info.yaml --calldata \
        --bls-passphrase-source no-passphrase --log.stdout.filter off --color never </dev/null)" \
        || die "keytool export-staking-args failed"
    STAKE_CALLDATA="$(printf '%s\n' "${ka_out}" | grep -E '^0x[0-9a-fA-F]{8,}$' | tail -1)"
    [ -n "${STAKE_CALLDATA}" ] || die "keytool export-staking-args printed no calldata"
    sel="$(lc "${STAKE_CALLDATA:0:10}")"
    case "$(cast code "${REGISTRY}" --rpc-url "${RPC}" | tr '[:upper:]' '[:lower:]')" in
        *"63${sel#0x}"*) ;;
        *) die "the registry has no function ${sel} (keytool's stake selector): image and genesis disagree" ;;
    esac
    echo "    ✓ stake calldata from keytool: ${sel}…, $(( (${#STAKE_CALLDATA} - 2) / 2 )) bytes; selector present in the registry"
    if sim="$(rd "${REGISTRY}" "${STAKE_CALLDATA}" --from "${NODE5_ADDR}" --value "${STAKE_WEI}" 2>&1)"; then
        echo "    ✓ stake simulation (eth_call from node 5, value ${STAKE_WEI}) succeeds"
    else
        rsel="$(revert_selector "${sim}")"
        if [ "${rsel}" = "0xed15e6cf" ] && [ "${V_MINTED}" = "0" ]; then
            echo "    ✓ stake simulation: PoP and value accepted; reverts only with $(error_name "${rsel}") (minted in step 2)"
        else
            echo "${sim}" | tail -3 >&2
            die "stake simulation reverts: $(error_name "${rsel:-none}")"
        fi
    fi
fi
echo "    ✓ preflight passed"

# ================================================================================
step_header 2 "mint node 5's ConsensusNFT through the Safe"
if ! skip_step 2; then
    if [ "${V_MINTED}" != "0" ]; then
        echo "    already minted: skipping"
    else
        mint_data="$(cast calldata "mint(address)" "${NODE5_ADDR}")"
        # pre-approved signature: r = owner address left-padded to 32 bytes, s = 0, v = 1
        admin_hex="$(lc "${ADMIN_ADDR#0x}")"
        sigs="0x000000000000000000000000${admin_hex}$(printf '%064d' 0)01"
        safe_tx_hash="$(cast call "${SAFE_ADDR}" "${TXHASH_SIG}" "${REGISTRY}" 0 "${mint_data}" 0 0 0 0 \
            "${ZERO_ADDR}" "${ZERO_ADDR}" "${safe_nonce}" --rpc-url "${RPC}")"
        echo "    Safe nonce ${safe_nonce}; safeTxHash ${safe_tx_hash}"
        plan "cast send ${SAFE_ADDR} '${EXEC_SIG}' ${REGISTRY} 0 ${mint_data} 0 0 0 0 ${ZERO_ADDR} ${ZERO_ADDR} ${sigs}  (from admin ${ADMIN_ADDR})"
        if [ "${CONFIRM}" -eq 1 ]; then
            send admin "Safe.execTransaction(mint)" "${SAFE_ADDR}" "${EXEC_SIG}" "${REGISTRY}" 0 "${mint_data}" \
                0 0 0 0 "${ZERO_ADDR}" "${ZERO_ADDR}" "${sigs}"
            read_validator
            [ "${V_MINTED}" = "1" ] || die "execTransaction succeeded but balanceOf(node5) is ${V_MINTED}"
            show_validator
            echo "    Safe nonce now $(first "$(cast call "${SAFE_ADDR}" "nonce()(uint256)" --rpc-url "${RPC}")")"
        fi
    fi
fi

# ================================================================================
step_header 3 "stake ${STAKE_WEI} wei from node 5"
if ! skip_step 3; then
    if [ "${V_STATUS}" -ge 1 ]; then
        echo "    already $(status_name "${V_STATUS}"): skipping"
    else
        plan "cast send ${REGISTRY} <keytool calldata ${STAKE_CALLDATA:0:10}…> --value ${STAKE_WEI}  (from node 5 ${NODE5_ADDR})"
        if [ "${CONFIRM}" -eq 1 ]; then
            [ "${V_MINTED}" = "1" ] || die "node 5 has no ConsensusNFT: run step 2 first"
            if ! sim="$(rd "${REGISTRY}" "${STAKE_CALLDATA}" --from "${NODE5_ADDR}" --value "${STAKE_WEI}" 2>&1)"; then
                echo "${sim}" | tail -3 >&2
                die "stake simulation reverts: $(error_name "$(revert_selector "${sim}")")"
            fi
            send node5 "stake" "${REGISTRY}" "${STAKE_CALLDATA}" --value "${STAKE_WEI}"
            read_validator
            [ "${V_STATUS}" -eq 1 ] || die "after stake node 5 is $(status_name "${V_STATUS}"), expected Staked"
            show_validator
        fi
    fi
fi

# ================================================================================
step_header 4 "wait for node 5 to be in sync (lag <= ${SYNC_MAX_LAG}, tn_nodeMode Observer)"
if ! skip_step 4; then
    echo "    node 5: ${NODE5_RPC:-${NODE5_INSTANCE} over IAP, 127.0.0.1:${NODE_RPC_PORT:-8545}}"
    echo "    reference ${REF_NAME}: ${REF_RPC:-${INSTANCE_NAMES[$REF_IDX]} over IAP, 127.0.0.1:${NODE_RPC_PORT:-8545}}"
    if [ "${V_STATUS}" -ge 2 ]; then
        echo "    already $(status_name "${V_STATUS}"): skipping"
    elif [ "${CONFIRM}" -eq 0 ]; then
        sync_probe || echo "    (not in sync now; --yes waits up to ${SYNC_TIMEOUT_SECS}s)"
    else
        start=${SECONDS}
        until sync_probe; do
            [ $((SECONDS - start)) -lt "${SYNC_TIMEOUT_SECS}" ] || die "node 5 not in sync after ${SYNC_TIMEOUT_SECS}s"
            sleep "${POLL}"
        done
        echo "    ✓ node 5 in sync"
    fi
fi

# ================================================================================
step_header 5 "activate() from node 5"
if ! skip_step 5; then
    if [ "${V_STATUS}" -ge 2 ]; then
        echo "    already $(status_name "${V_STATUS}"): skipping"
    else
        plan "cast send ${REGISTRY} 'activate()'  (from node 5 ${NODE5_ADDR})"
        if [ "${CONFIRM}" -eq 1 ]; then
            [ "${V_STATUS}" -eq 1 ] || die "node 5 is $(status_name "${V_STATUS}"), activate() needs Staked"
            send node5 "activate" "${REGISTRY}" "activate()"
            read_validator
            [ "${V_STATUS}" -eq 2 ] || die "after activate node 5 is $(status_name "${V_STATUS}"), expected PendingActivation"
            show_validator
        fi
    fi
fi

# ================================================================================
step_header 6 "watch activation and committee membership"
if [ "${CONFIRM}" -eq 0 ]; then
    plan "poll getValidator(node5) every ${POLL}s until Active (up to ${EPOCH_TIMEOUT_SECS}s), then log committee(e) for ${WATCH_EPOCHS} epoch(s) from activationEpoch+2; per epoch from activationEpoch: status, tn_nodeMode, membership, what to check on the validators"
    echo ""
    echo "DRY RUN complete: nothing was sent. Re-run with --yes to apply."
    exit 0
fi
read_validator
[ "${V_STATUS}" -ge 2 ] || die "node 5 is $(status_name "${V_STATUS}"); nothing to watch until it is activated"
start=${SECONDS}
while [ "${V_STATUS}" -eq 2 ]; do
    [ $((SECONDS - start)) -lt "${EPOCH_TIMEOUT_SECS}" ] || die "still PendingActivation after ${EPOCH_TIMEOUT_SECS}s"
    ep="$(current_epoch 2>/dev/null)" || ep="unreadable"
    echo "      epoch ${ep}: PendingActivation (activationEpoch ${V_ACT_EPOCH}); next poll in ${POLL}s"
    sleep "${POLL}"
    read_validator
done
[ "${V_STATUS}" -eq 3 ] || die "node 5 went from PendingActivation to $(status_name "${V_STATUS}")"
ep="$(current_epoch 2>/dev/null)" || ep="unreadable"
echo "    ✓ node 5 Active in epoch ${ep} (activationEpoch ${V_ACT_EPOCH})"

first_seat=$((V_ACT_EPOCH + 2))      # activate() in N: activationEpoch N+1, first drawable committee N+3
for e in $((V_ACT_EPOCH)) $((V_ACT_EPOCH + 1)); do
    c="$(committee "${e}")" || die "getCommitteeValidators(${e}) failed"
    if has_node5 "${c}"; then m="node 5 IN"; else m="node 5 out (drawn before activation)"; fi
    if [ "${e}" -eq "${V_ACT_EPOCH}" ]; then chk="node 5's allowlist entry (the first epoch start after activate())"
    else chk="node 5's admission window (one epoch after the allowlist entry)"; fi
    epoch_line "${e}" "${c}" "${m}" "${chk}"
done
prev="$(committee $((first_seat - 1)))" || die "getCommitteeValidators($((first_seat - 1))) failed"
seated=""; changes=0; e=${first_seat}
while [ "${e}" -lt $((first_seat + WATCH_EPOCHS)) ]; do
    # committee(e) is final once epoch e-2 has begun: the close of e-3 stored it (newEpoch + 2)
    wait_for_epoch $((e - 2))
    c="$(committee "${e}")" || die "getCommitteeValidators(${e}) failed"
    if has_node5 "${c}"; then m="node 5 IN"; seated="${seated} ${e}"; else m="node 5 out"; fi
    if [ "${c}" = "${prev}" ]; then d="unchanged vs $((e - 1))"; else d="CHANGED vs $((e - 1))"; changes=$((changes + 1)); fi
    if [ "${e}" -eq "${first_seat}" ]; then chk="the first possible seat"; else chk="a later seat"; fi
    if has_node5 "${c}"; then chk="${chk}: node 5 drawn, it joins the committee"
    else chk="${chk}: node 5 not drawn, it stays outside the committee"; fi
    epoch_line "${e}" "${c}" "${m}; ${d}" "${chk}"
    prev="${c}"; e=$((e + 1))
done
echo ""
if [ "${WATCH_EPOCHS}" -gt 0 ]; then
    echo "Summary: node 5 Active; seated in epoch(s):${seated:- none} of ${first_seat}..$((first_seat + WATCH_EPOCHS - 1));"
    echo "         committee membership changed ${changes} time(s) across the watched epochs."
    [ -n "${seated}" ] || echo "⚠️  node 5 drew no seat in the watched window (possible with 5 eligible for 4 seats); watch more epochs."
else
    echo "Summary: node 5 Active (no epochs watched)."
fi
