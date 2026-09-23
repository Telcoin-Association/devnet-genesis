#!/usr/bin/env bash
#
# devnet-contracts.sh — deploy runbook Step 14: redeploy the APP-CONTRACT stack onto a
# freshly-genesised devnet.
#
# A genesis reset takes every script-deployed contract with it. Only ConsensusRegistry,
# Issuance and StakeManager are genesis-assigned; WTEL, the 23 eXYZ stablecoins,
# StablecoinManager, GitAttestationRegistry and all the Uniswap factories/routers/pools
# are CREATE2-deployed by tn-contracts and die with the chain. tn-transaction-generator
# reads every one of them out of deployments-devnet.json at startup and refuses to run if
# a mandatory key is missing (src/deployments.rs:31-71), so Step 14 must land before
# Step 15.
#
# This is a THIN WRAPPER, not a reimplementation. The real work is done by tn-contracts'
# own scripts, which are already idempotent and chain-id aware:
#
#   script/bash/deploy-testnet-infra.sh   stablecoins -> StablecoinManager ->
#                                         GitAttestationRegistry -> WTEL -> Uniswap V2/V3/V4
#                                         -> role grants. Each step is skipped when the
#                                         address recorded in the json already has on-chain
#                                         code (its has_code() gate), so re-runs are safe.
#   script/testnet/SeedTestnetLPs.s.sol   seeds the Uniswap pools so the swap tx types have
#                                         liquidity to trade against.
#
# What this wrapper adds on top of them — all of it load-bearing:
#
#   1. Secret handling. ADMIN_PK comes from GCP Secret Manager (${ADMIN_PK_SECRET}), not a
#      hand-maintained .env, and is never echoed (redacted logging, as devnet-keygen.sh does).
#   2. A materialized .env in the contracts checkout. BOTH tn-contracts bash scripts do a
#      bare `source .env`, so an exported ADMIN_PK/TN_RPC_URL cannot survive the call —
#      seed-testnet-lps.sh:19 in particular has no pre-capture and WILL clobber an exported
#      TN_RPC_URL, which on a stale .env means seeding liquidity on the WRONG NETWORK.
#      Writing .env (mode 600) is the only reliable way to aim those scripts at devnet.
#   3. Hard preconditions: chain id is really 32285, the deploy key really is the json's
#      .admin (TestnetGrantRole.s.sol:88 asserts hasRole(DEFAULT_ADMIN_ROLE, .admin) and
#      SeedTestnetLPs.s.sol:115 acts AS .admin — both revert on a mismatch), and .admin is
#      actually funded on the new chain.
#   4. The WTEL genesis fix. On a chain genesised from the current precompile-config, WTEL
#      already exists at the vanity address 0x...37E1, but the json still carries the old
#      pre-genesis CREATE2 value. Left alone, the deploy would mint a SECOND WTEL at the
#      stale address and wire every Uniswap router to the wrong one. tn-contracts'
#      script/README.md:109 calls this out: "At the next reset, also set WTEL to its genesis
#      vanity address".
#   5. Post-hoc verification. The Uniswap V3/V4 steps SKIP WITHOUT FAILING when their
#      vendored bytecode literals are unpopulated, so a partial stack otherwise exits 0.
#      We re-read every mandatory address and assert eth_getCode != 0x ourselves.
#
# NOT done here: a "grant the txgen master the StablecoinManager FAUCET role" step. There is
# no FAUCET role in tn-contracts (the role set is MAINTAINER/PAUSER/SWAPPER on
# StablecoinManager and MINTER/BURNER/SUPPORT on Stablecoin), and the faucet entrypoints
# dripTo()/drip() are PERMISSIONLESS (TNFaucet.sol:115). The generator's drip path
# (src/funding.rs:139-152) calls dripTo directly, so it needs no role at all — flipping
# enable_stablecoin_funding to true is free whenever it is wanted.
#
# Touches only the app-contract layer: no VM, no firewall, no DNS, no consensus.
#
# Usage:
#   ./devnet-contracts.sh              # DRY RUN: preflight + plan, deploys nothing
#   ./devnet-contracts.sh --yes        # run the deploy + LP seed
#   ./devnet-contracts.sh --yes --skip-lps    # deploy only, no LP seeding

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

# --- tunables ------------------------------------------------------------------
# The tn-contracts checkout to deploy FROM. Defaults to the deploy/devnet-relaunch
# worktree, which is the tree tn-transaction-generator pins its vendor/ submodule to.
# HEAD of tn-contracts carries different CREATE2 salts and therefore a COMPLETELY
# different address book — the two are not interchangeable, so the branch is asserted.
#
# Every tunable below defaults to the devnet value. The benchmark profile
# (benchmark/benchmark-deploy.sh step 11) overrides them to deploy the same stack onto
# its own throwaway chain from a disposable worktree; see the chain-routing guard below.
DEVNET_CONTRACTS_DIR_DEFAULT="$(cd "${REPO_DIR}/.." && pwd)/tn-contracts-devnet-relaunch"
TN_CONTRACTS_DIR="${TN_CONTRACTS_DIR:-${DEVNET_CONTRACTS_DIR_DEFAULT}}"
TN_CONTRACTS_BRANCH="${TN_CONTRACTS_BRANCH:-deploy/devnet-relaunch}"
ADMIN_PK_SECRET="${ADMIN_PK_SECRET:-devnet-contracts-admin-pk}"
DEVNET_RPC="${DEVNET_RPC:-${RPC_URL}}"                  # config.sh: https://rpc.devnet.telcoin.network
WTEL_GENESIS_ADDR="0x00000000000000000000000000000000000037E1"
DEPLOYMENTS_JSON="${DEPLOYMENTS_JSON:-deployments/deployments-devnet.json}"  # relative to TN_CONTRACTS_DIR
EXPECTED_CHAIN_ID="${EXPECTED_CHAIN_ID:-${CHAIN_ID}}"   # config.sh: 32285
DEVNET_CHAIN_ID=32285

# Chain-routing guard. tn-contracts picks its address book by chain id
# (deployments/DeploymentsResolver.sol, script/bash/deploy-testnet-infra.sh): 32285 reads
# deployments-devnet.json, every other chain reads deployments-testnet.json. A mismatched
# DEPLOYMENTS_JSON would verify one file while forge writes the other. A non-devnet chain
# must also never deploy from the devnet worktree, whose testnet json it would overwrite.
if [ "${EXPECTED_CHAIN_ID}" = "${DEVNET_CHAIN_ID}" ]; then
    expected_json="deployments/deployments-devnet.json"
else
    expected_json="deployments/deployments-testnet.json"
    # Compare physical paths: a trailing slash, a symlink or a ../ spelling of the devnet
    # worktree must not slip past a string compare.
    _canon() { (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; }
    if [ "$(_canon "${TN_CONTRACTS_DIR}")" = "$(_canon "${DEVNET_CONTRACTS_DIR_DEFAULT}")" ]; then
        echo "❌ EXPECTED_CHAIN_ID=${EXPECTED_CHAIN_ID} is not devnet, but TN_CONTRACTS_DIR is the devnet" >&2
        echo "   worktree (${TN_CONTRACTS_DIR}). Deploy a non-devnet chain from its own worktree." >&2
        exit 1
    fi
fi
if [ "${DEPLOYMENTS_JSON}" != "${expected_json}" ]; then
    echo "❌ DEPLOYMENTS_JSON=${DEPLOYMENTS_JSON} but chain ${EXPECTED_CHAIN_ID} routes to ${expected_json}." >&2
    exit 1
fi

# --- args ----------------------------------------------------------------------
CONFIRM=0
SKIP_LPS=0
for arg in "$@"; do
    case "${arg}" in
        --yes) CONFIRM=1 ;;
        --skip-lps) SKIP_LPS=1 ;;
        *) echo "❌ unknown argument '${arg}' (supported: --yes, --skip-lps)" >&2; exit 1 ;;
    esac
done
[ "${FORCE:-}" = "true" ] && CONFIRM=1

echo "=========================================="
echo "devnet app-contract stack (Step 14)"
echo "Contracts:  ${TN_CONTRACTS_DIR} (branch ${TN_CONTRACTS_BRANCH})"
echo "RPC:        ${DEVNET_RPC}"
echo "Chain id:   ${EXPECTED_CHAIN_ID} (expected)"
echo "Admin key:  Secret Manager ${ADMIN_PK_SECRET} (project ${PROJECT_ID}) — never printed"
[ "${SKIP_LPS}" -eq 1 ] && echo "LP seeding: SKIPPED (--skip-lps)"
[ "${CONFIRM}" -eq 1 ] && echo "Mode:       APPLY (--yes)" || echo "Mode:       DRY RUN (no --yes) — preflight only"
echo "=========================================="

# --- preflight: tooling ---------------------------------------------------------
echo ""
echo ">>> preflight: tooling"
for bin in forge cast jq curl; do
    command -v "${bin}" >/dev/null 2>&1 || { echo "❌ '${bin}' not on PATH" >&2; exit 1; }
    echo "    ✓ ${bin} $(command -v "${bin}")"
done

# --- preflight: the contracts checkout -----------------------------------------
echo ""
echo ">>> preflight: contracts checkout"
[ -d "${TN_CONTRACTS_DIR}" ] || { echo "❌ ${TN_CONTRACTS_DIR} does not exist" >&2; exit 1; }
[ -f "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}" ] \
    || { echo "❌ ${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON} missing" >&2; exit 1; }
cur_branch="$(git -C "${TN_CONTRACTS_DIR}" rev-parse --abbrev-ref HEAD)"
if [ "${cur_branch}" != "${TN_CONTRACTS_BRANCH}" ]; then
    echo "❌ ${TN_CONTRACTS_DIR} is on '${cur_branch}', expected '${TN_CONTRACTS_BRANCH}'." >&2
    echo "   The address book and the CREATE2 salts must come from the SAME tree — a" >&2
    echo "   different branch deploys to entirely different addresses." >&2
    exit 1
fi
echo "    ✓ ${cur_branch} @ $(git -C "${TN_CONTRACTS_DIR}" rev-parse --short HEAD)"
[ -d "${TN_CONTRACTS_DIR}/lib/forge-std" ] \
    || { echo "❌ forge libs not initialized — run: git -C '${TN_CONTRACTS_DIR}' submodule update --init --recursive" >&2; exit 1; }
echo "    ✓ forge libs present"

# --- preflight: the chain is the one we think it is ----------------------------
echo ""
echo ">>> preflight: chain identity"
observed_chain="$(cast chain-id --rpc-url "${DEVNET_RPC}")"
if [ "${observed_chain}" != "${EXPECTED_CHAIN_ID}" ]; then
    echo "❌ ${DEVNET_RPC} reports chain id ${observed_chain}, expected ${EXPECTED_CHAIN_ID}." >&2
    echo "   Refusing to deploy — deploy-testnet-infra.sh routes by chain id and a" >&2
    echo "   mismatch would write to the WRONG address book." >&2
    exit 1
fi
echo "    ✓ chain id ${observed_chain}"

# --- admin key (from Secret Manager; never echoed) ------------------------------
echo ""
echo ">>> resolving admin private key from Secret Manager (${ADMIN_PK_SECRET})"
if ! admin_pk="$(tn_secret "${ADMIN_PK_SECRET}" 2>/dev/null)" || [ -z "${admin_pk}" ]; then
    cat >&2 <<EOF
❌ secret '${ADMIN_PK_SECRET}' is missing or empty in project ${PROJECT_ID}.

   Create it once (the value is the 0x-prefixed private key of the contracts admin):

     printf '%s' '0x<ADMIN_PRIVATE_KEY>' | gcloud secrets create ${ADMIN_PK_SECRET} \\
       --project=${PROJECT_ID} --replication-policy=automatic --data-file=-

   Rotate later with: gcloud secrets versions add ${ADMIN_PK_SECRET} --data-file=-
EOF
    exit 1
fi
admin_pk="$(printf '%s' "${admin_pk}" | tr -d '[:space:]')"
admin_addr="$(cast wallet address --private-key "${admin_pk}")"
echo "    ✓ key retrieved (redacted) -> deployer address ${admin_addr}"

# --- the deployer MUST be the json's .admin ------------------------------------
# TestnetGrantRole.s.sol:88 asserts hasRole(DEFAULT_ADMIN_ROLE, deployments.admin) on every
# stablecoin, and SeedTestnetLPs.s.sol:115 takes admin = deployments.admin as the drip
# recipient / LP provider. DEFAULT_ADMIN_ROLE lands on the DEPLOYER (Stablecoin.sol:54
# _grantRole(DEFAULT_ADMIN_ROLE, _msgSender())), so if .admin is anyone else the grant step
# reverts and the LP seed acts for an address it cannot sign for.
json_admin="$(jq -r '.admin' "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}")"
echo ""
echo ">>> preflight: deployer identity vs ${DEPLOYMENTS_JSON} .admin"
if [ "$(printf '%s' "${json_admin}" | tr 'A-Z' 'a-z')" != "$(printf '%s' "${admin_addr}" | tr 'A-Z' 'a-z')" ]; then
    echo "❌ .admin is ${json_admin} but the deploy key is ${admin_addr}." >&2
    echo "   TestnetGrantRole.s.sol:88 would revert. Set .admin to the deploy key, or" >&2
    echo "   put the matching key in Secret Manager." >&2
    exit 1
fi
echo "    ✓ .admin == deployer (${admin_addr})"

# --- the deployer must be funded on the NEW chain ------------------------------
echo ""
echo ">>> preflight: deployer balance on the new chain"
admin_bal="$(cast balance "${admin_addr}" --rpc-url "${DEVNET_RPC}")"
if [ "${admin_bal}" = "0" ]; then
    echo "❌ ${admin_addr} has zero balance on ${DEVNET_RPC}." >&2
    echo "   It must be allocated in testnet_accounts.yaml BEFORE genesis is sealed" >&2
    echo "   (deploy Step 6) — there is no faucet path for it here." >&2
    exit 1
fi
echo "    ✓ balance ${admin_bal} wei ($(cast from-wei "${admin_bal}") TEL)"

# --- WTEL: point the json at the GENESIS WTEL, not a stale CREATE2 address ------
echo ""
echo ">>> preflight: WTEL"
json_wtel="$(jq -r '.WTEL' "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}")"
genesis_wtel_code="$(cast code "${WTEL_GENESIS_ADDR}" --rpc-url "${DEVNET_RPC}")"
wtel_patch_needed=0
if [ "${genesis_wtel_code}" != "0x" ] && [ -n "${genesis_wtel_code}" ]; then
    echo "    genesis WTEL present at ${WTEL_GENESIS_ADDR} (code ${#genesis_wtel_code} chars)"
    if [ "$(printf '%s' "${json_wtel}" | tr 'A-Z' 'a-z')" != "$(printf '%s' "${WTEL_GENESIS_ADDR}" | tr 'A-Z' 'a-z')" ]; then
        echo "    ⚠ json .WTEL is ${json_wtel} — a stale pre-genesis CREATE2 address."
        echo "      Left as-is, Step 4 of deploy-testnet-infra.sh would deploy a SECOND WTEL"
        echo "      there and wire every Uniswap router to it instead of the genesis one."
        echo "      -> will patch .WTEL to ${WTEL_GENESIS_ADDR}"
        wtel_patch_needed=1
    else
        echo "    ✓ json .WTEL already points at the genesis address"
    fi
else
    echo "    genesis WTEL address has NO code — this chain does not predeploy WTEL."
    echo "    ✓ leaving .WTEL as ${json_wtel} (deploy-testnet-infra.sh will CREATE2 it)"
fi

# --- the mandatory address-book keys the generator demands ----------------------
# src/deployments.rs:31-109 — a missing/codeless key here is what makes Step 15 refuse
# to start, so this same list is what we verify after the deploy.
MANDATORY_JQ=(
    '.ConsensusRegistry' '.Issuance' '.StakeManager'
    '.StablecoinManager' '.WTEL'
    '.uniswapV2.UniswapV2Factory' '.uniswapV2.UniswapV2Router02'
    '.uniswapV3.UniswapV3Factory' '.uniswapV3.SwapRouter02'
    '.uniswapV4.V4SwapHelper' '.uniswapV4.V4Quoter'
    '.eXYZs.eUSD' '.eXYZs.eEUR'
)

if [ "${CONFIRM}" -ne 1 ]; then
    cat <<EOF

PLAN (nothing has been changed):
  1. write ${TN_CONTRACTS_DIR}/.env   (mode 600: ADMIN_PK from Secret Manager + TN_RPC_URL=${DEVNET_RPC})
$([ "${wtel_patch_needed}" -eq 1 ] && echo "  2. patch ${DEPLOYMENTS_JSON} .WTEL -> ${WTEL_GENESIS_ADDR}" || echo "  2. (no WTEL patch needed)")
  3. ./script/bash/deploy-testnet-infra.sh      (8 idempotent steps; skips whatever already has code)
  4. verify eth_getCode != 0x for every mandatory key
$([ "${SKIP_LPS}" -eq 1 ] && echo "  5. (LP seeding skipped)" || echo "  5. seed Uniswap LPs (SeedTestnetLPs.s.sol) + verify a pool has reserves")

DRY RUN only — re-run with --yes to apply.
EOF
    exit 0
fi

# ================================ APPLY =========================================

# --- 1. materialize .env --------------------------------------------------------
# Both tn-contracts bash scripts do a bare `source .env`, so exported vars cannot survive
# into them. seed-testnet-lps.sh:19 has no pre-capture at all and would otherwise inherit
# whatever TN_RPC_URL the old .env carried (historically https://adiri.tel — i.e. it would
# seed liquidity on TESTNET). Writing the file is the only reliable aim.
echo ""
echo ">>> writing ${TN_CONTRACTS_DIR}/.env (mode 600; ADMIN_PK redacted in all logs)"
env_file="${TN_CONTRACTS_DIR}/.env"
if [ -f "${env_file}" ]; then
    cp -p "${env_file}" "${env_file}.bak.$(date +%Y%m%d_%H%M%S)"
    echo "    (existing .env backed up)"
fi
umask 077
cat > "${env_file}" <<EOF
# Written by devnet-genesis/devnet-contracts.sh — do not commit (gitignored).
# ADMIN_PK is mirrored from GCP Secret Manager '${ADMIN_PK_SECRET}' in project ${PROJECT_ID}.
TN_RPC_URL=${DEVNET_RPC}
ADMIN_PK=${admin_pk}
ADMIN_ADDRESS=${admin_addr}
EOF
chmod 600 "${env_file}"
echo "    ✓ .env written (TN_RPC_URL=${DEVNET_RPC}, ADMIN_PK=***REDACTED***)"

# --- 2. WTEL patch --------------------------------------------------------------
if [ "${wtel_patch_needed}" -eq 1 ]; then
    echo ""
    echo ">>> patching ${DEPLOYMENTS_JSON} .WTEL -> ${WTEL_GENESIS_ADDR}"
    tmp="$(mktemp)"
    jq --arg w "${WTEL_GENESIS_ADDR}" '.WTEL = $w' \
        "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}" > "${tmp}"
    mv "${tmp}" "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}"
    echo "    ✓ .WTEL = $(jq -r '.WTEL' "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}")"
fi

# --- 3. deploy the stack --------------------------------------------------------
echo ""
echo ">>> running deploy-testnet-infra.sh (cwd must be the repo root — it sources ./.env)"
echo "    + TN_RPC_URL=${DEVNET_RPC} ./script/bash/deploy-testnet-infra.sh"
( cd "${TN_CONTRACTS_DIR}" && TN_RPC_URL="${DEVNET_RPC}" ./script/bash/deploy-testnet-infra.sh ) \
    || { echo "❌ deploy-testnet-infra.sh failed — see the forge output above." >&2; exit 1; }
echo "    ✓ deploy-testnet-infra.sh returned 0"

# --- 4. verify every mandatory key has code -------------------------------------
# NOT optional: the V3/V4 steps print "bytecode unpopulated, deferring" and exit 0 when
# their vendored hex literals are empty, so a partial stack would pass silently here.
echo ""
echo ">>> verifying the address book against the chain (eth_getCode != 0x)"
vrc=0
for jqpath in "${MANDATORY_JQ[@]}"; do
    addr="$(jq -r "${jqpath}" "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}")"
    if [ -z "${addr}" ] || [ "${addr}" = "null" ] \
       || [ "${addr}" = "0x0000000000000000000000000000000000000000" ]; then
        printf '    ❌ %-34s UNSET in the json (%s)\n' "${jqpath}" "${addr}" >&2
        vrc=1; continue
    fi
    code="$(cast code "${addr}" --rpc-url "${DEVNET_RPC}" 2>/dev/null || echo "0x")"
    if [ "${code}" = "0x" ] || [ -z "${code}" ]; then
        printf '    ❌ %-34s %s  NO CODE ON CHAIN\n' "${jqpath}" "${addr}" >&2
        vrc=1
    else
        printf '    ✓ %-34s %s  (%s bytes)\n' "${jqpath}" "${addr}" "$(( (${#code} - 2) / 2 ))"
    fi
done
if [ "${vrc}" -ne 0 ]; then
    echo "" >&2
    echo "❌ the app-contract stack is INCOMPLETE. tn-transaction-generator will refuse to" >&2
    echo "   start against this address book (src/deployments.rs mandatory keys)." >&2
    echo "   If Uniswap V3/V4 are the gap, their vendored bytecode literals are empty —" >&2
    echo "   refresh with script/bash/fetch-uniswap-v{3,4}-bytecode.sh and re-run." >&2
    exit 1
fi

# --- 5. seed the Uniswap pools --------------------------------------------------
if [ "${SKIP_LPS}" -eq 1 ]; then
    echo ""
    echo ">>> LP seeding skipped (--skip-lps). Swap tx types will have no liquidity."
else
    echo ""
    echo ">>> seeding Uniswap LPs (SeedTestnetLPs.s.sol)"
    echo "    .env now pins TN_RPC_URL=${DEVNET_RPC}, so the script's bare 'source .env'"
    echo "    can no longer redirect this at another network."
    ( cd "${TN_CONTRACTS_DIR}" && bash ./script/bash/seed-testnet-lps.sh ) \
        || { echo "❌ seed-testnet-lps.sh failed — see the forge output above." >&2; exit 1; }

    echo ""
    echo ">>> verifying at least one Uniswap V2 pool holds reserves"
    seeded=0
    for pool_key in wTEL_eUSD_Pool eUSD_eEUR_Pool wTEL_eEUR_Pool; do
        paddr="$(jq -r ".uniswapV2.${pool_key} // empty" "${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}")"
        [ -n "${paddr}" ] || continue
        res="$(cast call "${paddr}" 'getReserves()(uint112,uint112,uint32)' \
                 --rpc-url "${DEVNET_RPC}" 2>/dev/null || true)"
        r0="$(printf '%s' "${res}" | awk 'NR==1{print $1}')"
        if [ -n "${r0}" ] && [ "${r0}" != "0" ]; then
            echo "    ✓ ${pool_key} (${paddr}) reserve0=${r0}"
            seeded=1
        else
            echo "    · ${pool_key} (${paddr}) empty"
        fi
    done
    if [ "${seeded}" -ne 1 ]; then
        echo "❌ no sampled V2 pool has reserves — LP seeding did not land." >&2
        echo "   The swap tx types would fire against empty pools." >&2
        exit 1
    fi
fi

# --- done -----------------------------------------------------------------------
if [ "${EXPECTED_CHAIN_ID}" != "${DEVNET_CHAIN_ID}" ]; then
    # Non-devnet (benchmark) chains deploy from a throwaway worktree: nothing to commit.
    echo ""
    echo "app-contract stack deployed and verified on chain ${EXPECTED_CHAIN_ID}."
    echo "  address book: ${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON} (do NOT commit it)"
    echo "  deployer:     ${admin_addr}"
    exit 0
fi
cat <<EOF

==========================================
app-contract stack deployed and verified.
==========================================
  address book: ${TN_CONTRACTS_DIR}/${DEPLOYMENTS_JSON}
  deployer:     ${admin_addr}

Next:
  1. commit the regenerated address book on ${TN_CONTRACTS_BRANCH}:
       git -C '${TN_CONTRACTS_DIR}' add ${DEPLOYMENTS_JSON} && git -C '${TN_CONTRACTS_DIR}' commit
  2. point tn-transaction-generator's vendor/tn-contracts submodule at that commit
  3. ./devnet-txgen.sh --yes    (Step 15)
EOF
