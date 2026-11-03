#!/usr/bin/env bash
#
# devnet-genesis-build.sh — OPERATOR driver (LOCAL only, no ssh): assemble the
# committee + genesis from the per-validator node-info collected by
# devnet-keygen.sh.
#
# It reuses the EXACT build path adiri uses: common/genesis.sh's
# tn_genesis_build_committee, which runs
#   docker run --platform linux/amd64 -v ./:/code --workdir /code <img> \
#     telcoin genesis --datadir ./ --chainid <CHAIN_ID> \
#       --bls-passphrase-source stdin \
#       --accounts /code/testnet_accounts.yaml \
#       --epoch-duration-in-secs <EPOCH_DURATION_SECS> ...
# Because the mount is `-v ./:/code` and genesis.sh cd's to ${REPO_ROOT} first,
# /code == repo root: the committee is built from EVERY file in
# genesis/validators/, and the accounts file MUST live at
# ${REPO_ROOT}/testnet_accounts.yaml (so the container sees /code/testnet_accounts.yaml).
# Outputs land at genesis/committee.yaml and genesis/genesis.yaml.
# After the build it checks the consensus knobs in the parameters file (step 4)
# and applies two devnet-only overrides to the governance Safe in genesis.yaml:
# threshold 1 (step 5) and SAFE_EXTRA_OWNER as an extra owner (step 6, through
# devnet-genesis-safe-owner.py; needs python3 + foundry's cast).
#
# Note on --bls-passphrase-source stdin: images up to v0.12.1 accepted the flag and
# never read stdin, so the committee assembly ran without a passphrase. The
# v0.1.0-devnet image made it a HARD requirement and aborts with "Error passphrase is
# required" on empty stdin. That anticipated "future image build" is now the present
# one, so we resolve the passphrase up front (tn_require_bls_passphrase, which reads
# the gitignored .secrets/bls-passphrase) and common/genesis.sh pipes it into
# `docker run -i`. Piping zero bytes is still valid for the older images.
#
# Idempotent: safe to re-run (it overwrites genesis/committee.yaml + genesis.yaml).

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# ----------------------------------------------------------------------------
# Step 0: banner — print the config.sh inputs that shape this genesis and fail
# loud if any is unset or empty. CHAIN_ID, EPOCH_DURATION_SECS and the four
# timing/fee knobs (common/genesis.sh passes them to `telcoin genesis`) change the
# genesis hash, and an empty knob would silently fall back to the binary default.
# SAFE_ADDR + SAFE_EXTRA_OWNER drive step 6 and the basefee check in step 4;
# PARAMETERS_FILE is what devnet-finalize.sh ships. Step 6 also needs python3 and
# foundry's cast, so they are checked here, before the build instead of after it.
# ----------------------------------------------------------------------------
echo ">>> step 0: genesis inputs"
inputs_missing=0
for v in CHAIN_ID EPOCH_DURATION_SECS MIN_HEADER_DELAY_MS MAX_HEADER_DELAY_MS \
         MAX_BATCH_DELAY_MS WORKER_FEE_CONFIG SAFE_ADDR SAFE_EXTRA_OWNER PARAMETERS_FILE; do
    if [ -n "${!v:-}" ]; then
        printf '    %-20s %s\n' "${v}" "${!v}"
    else
        printf '    %-20s ✗ UNSET OR EMPTY\n' "${v}" >&2
        inputs_missing=1
    fi
done
for c in python3 cast; do
    command -v "${c}" >/dev/null 2>&1 || { echo "    ✗ ${c} not on PATH (step 6 needs it)" >&2; inputs_missing=1; }
done
if [ "${inputs_missing}" -ne 0 ]; then
    echo "❌ genesis inputs incomplete (see above). Set them in config.sh and retry." >&2
    exit 1
fi

# Then work from the genesis workspace so the docker `-v ./:/code` mount == the
# workspace. config.sh sets GENESIS_WORKSPACE=REPO_ROOT for devnet (matches
# common/genesis.sh); a profile such as benchmark/ points it at its own tree.
GENESIS_WS="${GENESIS_WORKSPACE:-${REPO_ROOT}}"
# Node 5 joins the committee after genesis by staking 1,000,000 TEL from its own address,
# so that address must be funded at genesis: testnet_accounts.yaml keys are checksummed
# (mixed case) while config.sh stores lower case, hence the case-insensitive grep.
# The benchmark profile (TN_PROFILE=benchmark, benchmark/config.sh) has no post-genesis
# staking node: its ten validators are all in the genesis committee and index 4 is one of
# them, so the check below does not apply there (2026-11-03, bench 3).
if [ "${TN_PROFILE:-}" = "benchmark" ]; then
    echo "    benchmark profile: no post-genesis staking node, the node-5 funding check does not apply"
else
    node5_addr="${EXECUTION_ADDRESSES[4]:-}"
    if [ -z "${node5_addr}" ] || ! grep -qi "^\"${node5_addr}\":" "${GENESIS_WS}/testnet_accounts.yaml" 2>/dev/null; then
        echo "❌ node 5 address '${node5_addr}' (EXECUTION_ADDRESSES[4]) is not a funded key in ${GENESIS_WS}/testnet_accounts.yaml; add it with 1,000,100 TEL before the build (runbook §3)" >&2
        exit 1
    fi
    echo "    node 5 ${node5_addr} is funded in testnet_accounts.yaml"
fi
echo ">>> step 0: cd ${GENESIS_WS}"
cd "${GENESIS_WS}"

VALIDATORS_DIR="${GENESIS_WS}/genesis/validators"

# ----------------------------------------------------------------------------
# Step 1: count expected validators (NODE_ROLES == validator) and verify there
# is one node-info yaml per validator in genesis/validators/. Fail loud if not —
# the committee hash depends on the full set.
# ----------------------------------------------------------------------------
echo ">>> step 1: verifying per-validator node-info in ${VALIDATORS_DIR}"
expected_validators=0
for r in "${NODE_ROLES[@]}"; do
    [ "${r}" = "validator" ] && expected_validators=$((expected_validators + 1))
done

if [ ! -d "${VALIDATORS_DIR}" ]; then
    echo "❌ ${VALIDATORS_DIR} does not exist. Run ./devnet-keygen.sh first." >&2
    exit 1
fi

shopt -s nullglob
validator_files=("${VALIDATORS_DIR}"/*.yaml)
shopt -u nullglob
found_validators="${#validator_files[@]}"

echo ">>> expected validators: ${expected_validators} | found node-info files: ${found_validators}"
for f in "${validator_files[@]}"; do echo "    - ${f}"; done

if [ "${found_validators}" -ne "${expected_validators}" ]; then
    echo "❌ validator node-info count mismatch (have ${found_validators}, need ${expected_validators})." >&2
    echo "   Each validator must have a genesis/validators/<nodeN>.yaml. Run ./devnet-keygen.sh" >&2
    echo "   for the missing validators before building the committee." >&2
    exit 1
fi

# ----------------------------------------------------------------------------
# Step 2: ensure the accounts file is where the docker build reads it. The build
# reads /code/testnet_accounts.yaml and /code == repo root, so the file must be
# at ${REPO_ROOT}/testnet_accounts.yaml. The canonical copy ships in common/.
# ----------------------------------------------------------------------------
echo ">>> step 2: ensuring accounts file at ${GENESIS_WS}/testnet_accounts.yaml"
ACCOUNTS_AT_ROOT="${GENESIS_WS}/testnet_accounts.yaml"
ACCOUNTS_IN_COMMON="${REPO_ROOT}/common/testnet_accounts.yaml"
if [ -f "${ACCOUNTS_AT_ROOT}" ]; then
    if [ "${GENESIS_WS}" = "${REPO_ROOT}" ]; then
        echo ">>> accounts file already present at repo root"
    else
        echo ">>> accounts file present in workspace ${GENESIS_WS}"
    fi
elif [ "${GENESIS_WS}" != "${REPO_ROOT}" ]; then
    # A non-default workspace must ship its OWN accounts file. Falling back to common/
    # (or the devnet root copy) would silently fund the wrong addresses in its genesis.
    echo "❌ no testnet_accounts.yaml in the genesis workspace ${GENESIS_WS}." >&2
    echo "   A non-default GENESIS_WORKSPACE never falls back to common/ — provide it and retry." >&2
    exit 1
elif [ -f "${ACCOUNTS_IN_COMMON}" ]; then
    echo ">>> copying ${ACCOUNTS_IN_COMMON} -> ${ACCOUNTS_AT_ROOT}"
    cp "${ACCOUNTS_IN_COMMON}" "${ACCOUNTS_AT_ROOT}"
else
    echo "❌ no testnet_accounts.yaml at repo root or in common/. The build reads" >&2
    echo "   /code/testnet_accounts.yaml (== ${ACCOUNTS_AT_ROOT}). Provide it and retry." >&2
    exit 1
fi

# ----------------------------------------------------------------------------
# Step 3: source common/genesis.sh in library mode (defines the build functions
# without running any of its phases) and run the committee build.
# ----------------------------------------------------------------------------
# Resolve the BLS passphrase BEFORE the build. genesis.sh pipes $TN_BLS_PASSPHRASE into
# the container's stdin; without this call the var is unset here and v0.1.0-devnet aborts.
# tn_require_bls_passphrase exports it from .secrets/bls-passphrase and never echoes it.
tn_require_bls_passphrase || exit 1
# A shell variable from here on, never an environment variable: genesis.sh is sourced
# into THIS shell and its `printf '%s' "$TN_BLS_PASSPHRASE" | docker run -i …` expands
# the value here, so no child (docker, python3, cast, awk) needs it in its environ.
export -n TN_BLS_PASSPHRASE
echo ">>> BLS passphrase resolved (value redacted)"

echo ">>> step 3: building committee + genesis via tn_genesis_build_committee"
# genesis.sh has NO `set -e`/`-u`/`pipefail`, and tn_genesis_build_committee handles the
# docker exit code itself (exits non-zero on failure). Relax our strict options around
# the source + call so the build runs in the SAME environment as adiri's direct
# ./genesis.sh exec (byte-identical; no spurious unset-var or exit-code aborts). Step 4
# below re-verifies the artifacts as the safety net.
set +e +u +o pipefail
# shellcheck source=/dev/null
GENESIS_LIB_ONLY=1 source "${REPO_ROOT}/common/genesis.sh"
# genesis.sh cd's to REPO_ROOT when sourced and makes its (relative) log dir there.
# Re-enter the workspace so the docker `-v ./:/code` mount and the relative
# committee log path both land in it (a no-op for devnet, where the two are the same).
cd "${GENESIS_WS}"
mkdir -p "${OUTPUT_PATH}"
tn_genesis_build_committee
set -euo pipefail

# ----------------------------------------------------------------------------
# Step 4: verify the output artifacts exist and report their paths, then check
# that the parameters file carries the consensus knobs. The expected values ARE
# the config.sh variables (the same ones common/genesis.sh passed to the build),
# so the check cannot drift from the build.
#
# Which parameters file: devnet ships the parameters.yaml that
# `telcoin genesis --datadir ./` just wrote at the workspace root
# (PARAMETERS_FILE == ${REPO_ROOT}/parameters.yaml), so PARAMETERS_FILE itself is
# checked; a stale path there fails here instead of shipping old delays. A
# profile workspace (benchmark/) ships its own hand-kept PARAMETERS_FILE, which
# its config.sh validates; there the file the build wrote in the workspace is
# checked, which still proves the build honoured the knobs.
# ----------------------------------------------------------------------------

# param_get FILE KEY — print the value of top-level KEY in a parameters.yaml with
# double quotes stripped. A nested map (`KEY:` then indented `secs:` / `nanos:`
# lines) comes back on one line ("secs: 1 nanos: 0"). Prints nothing when absent.
param_get() {
    awk -v key="$2" '
        { sub(/\r$/, "") }
        inmap && /^[ ]/ { l = $0; sub(/^[ ]+/, "", l); val = (val == "" ? l : val " " l); next }
        inmap { exit }
        index($0, key ":") == 1 {
            found = 1
            v = substr($0, length(key) + 2)
            sub(/^[ ]+/, "", v); sub(/[ ]+$/, "", v); gsub(/"/, "", v)
            if (v == "") { inmap = 1; next }
            val = v; exit
        }
        END { if (found) print val }
    ' "$1"
}

# duration_ms VALUE — a duration as param_get prints it, in whole milliseconds.
# Reads both serde forms the binary writes: humantime ("1s", "350ms", "1s 500ms")
# and the {secs, nanos} map ("secs: 1 nanos: 0"). Prints "?" for anything else and
# "<n>ns" for a duration that is not a whole number of milliseconds.
duration_ms() {
    awk -v s="$1" 'BEGIN {
        n = split(s, t, /[ :]+/); ns = 0
        if (n == 0) { print "?"; exit }
        if (n == 4 && t[1] == "secs" && t[3] == "nanos") {
            ns = t[2] * 1e9 + t[4]
        } else {
            for (i = 1; i <= n; i++) {
                if (!match(t[i], /^[0-9]+/)) { print "?"; exit }
                u = substr(t[i], RLENGTH + 1); m = 0
                if (u == "ns") m = 1; else if (u == "us") m = 1e3; else if (u == "ms") m = 1e6
                else if (u == "s") m = 1e9; else if (u == "m") m = 60e9; else if (u == "h") m = 3600e9
                if (m == 0) { print "?"; exit }
                ns += substr(t[i], 1, RLENGTH) * m
            }
        }
        if (ns % 1e6 == 0) printf "%d\n", ns / 1e6; else printf "%dns\n", ns
    }'
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

echo ">>> step 4: verifying outputs"
COMMITTEE_OUT="${GENESIS_WS}/genesis/committee.yaml"
GENESIS_OUT="${GENESIS_WS}/genesis/genesis.yaml"
if [ "${GENESIS_WS}" = "${REPO_ROOT}" ]; then
    PARAMS_CHECK="${PARAMETERS_FILE}"
else
    PARAMS_CHECK="${GENESIS_WS}/parameters.yaml"
fi
outputs=("${COMMITTEE_OUT}" "${GENESIS_OUT}" "${PARAMS_CHECK}")
[ "${PARAMETERS_FILE}" = "${PARAMS_CHECK}" ] || outputs+=("${PARAMETERS_FILE}")
missing=0
for f in "${outputs[@]}"; do
    if [ -f "${f}" ]; then
        echo "    ✓ ${f}"
    else
        echo "    ✗ MISSING: ${f}" >&2
        missing=1
    fi
done
if [ "${missing}" -ne 0 ]; then
    echo "❌ genesis build did not produce the expected artifacts." >&2
    exit 1
fi

echo ">>> step 4: consensus knobs in ${PARAMS_CHECK}"
params_bad=0
for spec in "max_header_delay=${MAX_HEADER_DELAY_MS}" \
            "min_header_delay=${MIN_HEADER_DELAY_MS}" \
            "max_batch_delay=${MAX_BATCH_DELAY_MS}"; do
    key="${spec%%=*}"; want="${spec#*=}"
    raw="$(param_get "${PARAMS_CHECK}" "${key}")"
    got="$(duration_ms "${raw}")"
    if [ -n "${raw}" ] && [ "${got}" = "${want}" ]; then
        echo "    ✓ ${key}: ${raw}  (${got} ms)"
    else
        echo "    ✗ ${key}: ${raw:-<missing>}  (${got} ms; config.sh wants ${want} ms)" >&2
        params_bad=1
    fi
done
raw="$(param_get "${PARAMS_CHECK}" basefee_address)"
if [ -n "${raw}" ] && [ "$(lower "${raw}")" = "$(lower "${SAFE_ADDR}")" ]; then
    echo "    ✓ basefee_address: ${raw}"
else
    echo "    ✗ basefee_address: ${raw:-<missing>}  (config.sh SAFE_ADDR is ${SAFE_ADDR})" >&2
    params_bad=1
fi
raw="$(param_get "${PARAMS_CHECK}" allow_private_forward_targets)"
if [ "${raw}" = "false" ]; then
    echo "    ✓ allow_private_forward_targets: ${raw}"
else
    echo "    ✗ allow_private_forward_targets: ${raw:-<missing>}  (want false)" >&2
    params_bad=1
fi
if [ "${params_bad}" -ne 0 ]; then
    echo "❌ ${PARAMS_CHECK} does not carry the config.sh consensus knobs (see above)." >&2
    exit 1
fi

# ----------------------------------------------------------------------------
# Step 5: devnet-only override — governance Safe single-signer threshold.
# genesis.yaml is regenerated from scratch on every build by the pinned image
# (telcoin genesis ...), so this MUST be re-applied post-build — a hand-edit to
# the committed file would just be overwritten. Rewrites ONLY storage slot
# 0x..04 (the Safe threshold) of the Safe at SAFE_ADDR, scoped to that account's
# alloc block so no other contract's slot 0x..04 is touched. Fails loud if the
# slot is gone (e.g. a future genesis-format change) instead of silently
# shipping the image's default threshold. Idempotent: re-runs are no-ops.
# devnet-finalize.sh ships GENESIS_OUT unchanged, so this patched file is what
# reaches every node.
# ----------------------------------------------------------------------------
SAFE_ADDR='0x00000000000000000000000000000000000007a0'
THR_SLOT='0x0000000000000000000000000000000000000000000000000000000000000004'
THR_VAL='0x0000000000000000000000000000000000000000000000000000000000000001'   # 1 signer

echo ">>> step 5: devnet override — set Safe ${SAFE_ADDR} threshold to 1 signer"
tmp="$(mktemp)"
SAFE_ADDR="${SAFE_ADDR}" SLOT="${THR_SLOT}" VAL="${THR_VAL}" awk '
  $0 ~ ("^  \"" ENVIRON["SAFE_ADDR"] "\":")    { in_safe=1; print; next }    # enter Safe alloc block
  in_safe && /^  "0x[0-9a-fA-F]+":[ ]*$/       { in_safe=0 }                 # next alloc entry: leave block
  in_safe && $0 ~ ("\"" ENVIRON["SLOT"] "\":") { sub(/"0x[0-9a-fA-F]+"[ ]*$/, "\"" ENVIRON["VAL"] "\""); done=1 }
  { print }
  END { if (!done) exit 3 }
' "${GENESIS_OUT}" > "${tmp}" \
  || { echo "❌ Safe override: threshold slot ${THR_SLOT} not found in ${GENESIS_OUT}" >&2; rm -f "${tmp}"; exit 1; }
mv "${tmp}" "${GENESIS_OUT}"
echo "    ✓ governance Safe threshold set to 1 signer (slot 0x..04 = ...0001)"

# ----------------------------------------------------------------------------
# Step 6: devnet-only override — add SAFE_EXTRA_OWNER as an owner of the same
# Safe. Post-build for the same reason as step 5. devnet-genesis-safe-owner.py
# rewrites ONLY the storage map of the Safe's alloc block, as raw text (every
# other byte is kept): owners[SENTINEL] := extra, a new owners[extra] := old head
# line, ownerCount (slot 0x..03) += 1. That is the storage effect of the Safe's
# addOwnerWithThreshold minus the threshold write, which step 5 owns. It walks
# the owner list before writing and fails loud on a missing slot or a broken or
# inconsistent list. Idempotent: a re-run prints "already applied" and leaves the
# file byte-identical. The owners mapping keys are keccak256, so it shells out to
# cast (checked in step 0).
# ----------------------------------------------------------------------------
echo ">>> step 6: devnet override — add ${SAFE_EXTRA_OWNER} as an owner of Safe ${SAFE_ADDR}"
python3 "${REPO_ROOT}/devnet-genesis-safe-owner.py" "${GENESIS_OUT}" "${SAFE_EXTRA_OWNER}" --safe "${SAFE_ADDR}" \
  || { echo "❌ Safe owner override failed; ${GENESIS_OUT} is not shippable as is." >&2; exit 1; }
echo "    ✓ governance Safe owners include ${SAFE_EXTRA_OWNER} (threshold stays 1)"

echo ""
echo "========================================="
echo "genesis build complete"
echo "========================================="
echo "  committee:  ${COMMITTEE_OUT}"
echo "  genesis:    ${GENESIS_OUT}"
echo "  parameters: ${PARAMETERS_FILE}"
echo "Next: ./devnet-finalize.sh to stage + finalize on every node."
