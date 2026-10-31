#!/usr/bin/env bash
#
# devnet-basefee-check.sh — READ-ONLY check that each epoch boundary moved worker 0's
# EIP-1559 base fee exactly as the protocol says it should.
#
# The genesis carries `--worker-fee-config ${WORKER_FEE_CONFIG}` (config.sh; 0:0:10000000 =
# worker 0, EIP-1559, target 10,000,000 gas per EPOCH). At every epoch close the closing block's
# fourth system call writes worker 0's next-epoch fee into WorkerConfigs.data
# (0xFee0FEe0fee0fEE0FEe0fee0FEE0fEe0feE0FEe0), and the next epoch runs on that fee. For each
# boundary N -> N+1 this script recomputes the fee from chain data and compares:
#
#   fee(N+1) == step(fee(N), gas_used(N), target)       (telcoin-network gas_accumulator.rs)
#   gas_used(N) >= target                               (the permanent txgen is loading the chain)
#
#   fee(N)      WorkerConfigs.data at the block before epoch N (max 7; epoch 0 = 7), checked
#               against every header's baseFeePerGas in epoch N
#   gas_used(N) the sum of header gasUsed over epoch N, closing block included (batched
#               eth_getBlockByNumber, 500 per request)
#   target      WorkerConfigs.getWorkerConfig(0).value at epoch N's last block, checked against
#               WORKER_FEE_CONFIG unless --expect-target any
#   fee(N+1)    WorkerConfigs.data at epoch N's last block, checked against epoch N+1's first
#               header and the word at N+1's first block
#
# step(): fee +/- fee * |gas - target| / (target * 8), gas clamped to 2 * target (so +/-12.5 %
# per epoch at most), a rise of at least 1 wei, floored at 7 wei. The exact integer
# transcription, its sources and the self-tests are in devnet-basefee-check.py.
#
# Epoch ranges come from tn_getEpochInfo(N).blockHeight (the registry's first block of N; the
# previous epoch's closing block is blockHeight - 1). Outside the registry's ring buffer
# [current-3, current+2] the start block is bisected on the header nonce (epoch << 32 | round)
# and cross-checked with getCurrentEpochInfo() pinned at the block before it.
#
# Inert target: a worker-0 target of u64::MAX (the genesis default without
# --worker-fee-config) reads any real load as ~0 %, so the fee can only fall to the 7 wei
# floor. Such a boundary prints SKIP (the step is still computed and noted) and does not fail
# the run.
#
# Usage:
#   ./devnet-basefee-check.sh --last 2               # the last two closed boundaries
#   ./devnet-basefee-check.sh --epoch 12             # boundary 12 -> 13
#   ./devnet-basefee-check.sh --watch [--count 1]    # wait for the next close(s), check each
#   ./devnet-basefee-check.sh --self-test            # unit tests of the fee step (offline)
# Options:
#   --rpc URL               JSON-RPC endpoint with the tn namespace (default RPC_URL, config.sh)
#   --expect-target GAS|any required worker-0 target (default: WORKER_FEE_CONFIG's value)
#   --formula-only          do not FAIL a boundary just because gas_used < target
#   --interval SECS         --watch poll period (default 30)
#   --count M               --watch: stop after M boundaries (default: run until Ctrl-C)
#   --bisect                find epoch ranges by bisection even inside the registry window
#
# Output: one line per boundary (boundary, blocks, gas_used, target, fee_N, fee_N1_expected,
# fee_N1_actual, PASS|FAIL|SKIP, notes), then a summary. Exit 0 = no FAIL, 1 = a FAIL,
# 2 = usage / RPC error. Needs curl, jq, cast (foundry) and python3 (stdlib only); no gcloud.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/devnet-lib.sh"

usage() { sed -n '3,53p' "$0" | sed 's/^# \{0,1\}//'; }

RPC="${RPC_URL:-}"
EXPECT=""
MODE=""
PY_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --epoch|--last)
            [ $# -ge 2 ] || { echo "❌ $1 needs a value" >&2; exit 2; }
            case "$2" in ''|*[!0-9]*) echo "❌ $1 needs a non-negative integer, got '$2'" >&2; exit 2 ;; esac
            [ -z "${MODE}" ] || { echo "❌ pick one of --epoch / --last / --watch / --self-test" >&2; exit 2; }
            MODE="$1"; PY_ARGS+=("$1" "$2"); shift 2 ;;
        --watch|--self-test)
            [ -z "${MODE}" ] || { echo "❌ pick one of --epoch / --last / --watch / --self-test" >&2; exit 2; }
            MODE="$1"; PY_ARGS+=("$1"); shift ;;
        --interval|--count)
            [ $# -ge 2 ] || { echo "❌ $1 needs a value" >&2; exit 2; }
            case "$2" in ''|*[!0-9]*) echo "❌ $1 needs a non-negative integer, got '$2'" >&2; exit 2 ;; esac
            PY_ARGS+=("$1" "$2"); shift 2 ;;
        --rpc)
            [ $# -ge 2 ] || { echo "❌ --rpc needs a URL" >&2; exit 2; }
            RPC="$2"; shift 2 ;;
        --expect-target)
            [ $# -ge 2 ] || { echo "❌ --expect-target needs GAS or 'any'" >&2; exit 2; }
            case "$2" in any) ;; ''|*[!0-9]*) echo "❌ --expect-target needs GAS or 'any', got '$2'" >&2; exit 2 ;; esac
            EXPECT="$2"; shift 2 ;;
        --formula-only|--bisect) PY_ARGS+=("$1"); shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "❌ unknown argument '$1' (see --help)" >&2; exit 2 ;;
    esac
done
[ -n "${MODE}" ] || { usage >&2; exit 2; }

for tool in python3 cast curl jq; do
    command -v "${tool}" >/dev/null 2>&1 || { echo "❌ ${tool} not found in PATH" >&2; exit 2; }
done
PY="${SCRIPT_DIR}/devnet-basefee-check.py"
if [ "${MODE}" = "--self-test" ]; then
    exec python3 "${PY}" --self-test
fi

# Expected target: worker 0's VALUE from WORKER_FEE_CONFIG (WORKER_ID:STRATEGY:VALUE, strategy
# 0 = EIP-1559). Anything else (unset, another worker, a static fee) means no expectation.
if [ -z "${EXPECT}" ]; then
    EXPECT=any
    if [ -n "${WORKER_FEE_CONFIG:-}" ]; then
        IFS=: read -r wfc_worker wfc_strategy wfc_value <<EOF
${WORKER_FEE_CONFIG}
EOF
        if [ "${wfc_worker}" = 0 ] && [ "${wfc_strategy}" = 0 ]; then
            case "${wfc_value}" in ''|*[!0-9]*) ;; *) EXPECT="${wfc_value}" ;; esac
        fi
    fi
fi

[ -n "${RPC}" ] || { echo "❌ no RPC endpoint: set RPC_URL in config.sh or pass --rpc" >&2; exit 2; }

# Preflight: the endpoint must serve the tn namespace (validators may not expose it).
epoch_now="$(curl -sS -m 20 -H 'content-type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tn_getCurrentEpochInfo","params":[]}' "${RPC}" \
    | jq -er '.result.epochId' 2>/dev/null)" || {
    echo "❌ ${RPC} did not answer tn_getCurrentEpochInfo (unreachable, or the tn namespace is not exposed)" >&2
    exit 2
}
echo "devnet-basefee-check: ${RPC} at epoch ${epoch_now}; expected worker-0 target: ${EXPECT}" >&2

exec python3 "${PY}" --rpc "${RPC}" --expect-target "${EXPECT}" ${PY_ARGS[@]+"${PY_ARGS[@]}"}
