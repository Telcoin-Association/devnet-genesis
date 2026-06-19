#!/bin/bash
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
#
# Note on --bls-passphrase-source stdin: the adiri direct-exec path (mirrored
# here) does NOT pipe a passphrase into the committee assembly — assembling the
# committee from public node-info does not need the keystore secret. If a future
# image build prompts on stdin, the operator can pipe it manually
# (printf '%s' "$TN_BLS_PASSPHRASE" | ...); this script authors the plain call to
# match adiri exactly.
#
# Idempotent: safe to re-run (it overwrites genesis/committee.yaml + genesis.yaml).

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# ----------------------------------------------------------------------------
# Step 0: work from the repo root so the docker `-v ./:/code` mount == repo root
# (matches common/genesis.sh).
# ----------------------------------------------------------------------------
echo ">>> step 0: cd ${REPO_ROOT}"
cd "${REPO_ROOT}"

VALIDATORS_DIR="${REPO_ROOT}/genesis/validators"

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
echo ">>> step 2: ensuring accounts file at ${REPO_ROOT}/testnet_accounts.yaml"
ACCOUNTS_AT_ROOT="${REPO_ROOT}/testnet_accounts.yaml"
ACCOUNTS_IN_COMMON="${REPO_ROOT}/common/testnet_accounts.yaml"
if [ -f "${ACCOUNTS_AT_ROOT}" ]; then
    echo ">>> accounts file already present at repo root"
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
echo ">>> step 3: building committee + genesis via tn_genesis_build_committee"
# genesis.sh has NO `set -e`/`-u`/`pipefail`, and tn_genesis_build_committee handles the
# docker exit code itself (exits non-zero on failure). Relax our strict options around
# the source + call so the build runs in the SAME environment as adiri's direct
# ./genesis.sh exec (byte-identical; no spurious unset-var or exit-code aborts). Step 4
# below re-verifies the artifacts as the safety net.
set +e +u +o pipefail
# shellcheck source=/dev/null
GENESIS_LIB_ONLY=1 source ./common/genesis.sh
tn_genesis_build_committee
set -euo pipefail

# ----------------------------------------------------------------------------
# Step 4: verify the two output artifacts exist and report their paths.
# ----------------------------------------------------------------------------
echo ">>> step 4: verifying outputs"
COMMITTEE_OUT="${REPO_ROOT}/genesis/committee.yaml"
GENESIS_OUT="${REPO_ROOT}/genesis/genesis.yaml"
missing=0
for f in "${COMMITTEE_OUT}" "${GENESIS_OUT}"; do
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

echo ""
echo "========================================="
echo "genesis build complete"
echo "========================================="
echo "  committee: ${COMMITTEE_OUT}"
echo "  genesis:   ${GENESIS_OUT}"
echo "Next: ./devnet-finalize.sh to stage + finalize on every node."
