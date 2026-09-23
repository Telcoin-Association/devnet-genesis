#!/usr/bin/env bash
#
# benchmark-firewall.sh — the bench fleet's two VPC rules, and nothing else.
#
#   bench-allow-consensus  INGRESS udp:49590,49594 from the bench nodes' current external +
#                          internal /32s (or 0.0.0.0/0 with --world)
#   bench-allow-iap-rpc    INGRESS tcp:8545 from IAP (35.235.240.0/20), for the operator's
#                          `gcloud compute start-iap-tunnel` to reth RPC
#
# Both target ONLY the tag bench-node (no devnet instance carries it) and are described
# "benchmark=1 run=<id>" so teardown can prove ownership. Blaster -> node :8545 traffic is
# internal and already covered by default-allow-internal (10.128.0.0/9), so it needs no rule.
#
# Hard guards: rule names must be ^bench- and never match ^devnet-|^default-|^obs-|^wg-|^allow-;
# an existing rule of the same name is only touched if it already targets exactly bench-node
# and carries benchmark=1; after apply, devnet-allow-consensus is diffed against its state
# before the call (and against results/<run>/pre-firewall.json when present) and the script
# aborts loudly if it changed.
#
# Usage:
#   benchmark/benchmark-firewall.sh status
#   benchmark/benchmark-firewall.sh apply  [--yes] [--world] [--run ID]
#   benchmark/benchmark-firewall.sh delete [--yes] [--run ID]
# Without --yes, apply/delete print the gcloud argv they would run and change nothing.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

ACTION=""; CONFIRM=0; WORLD=0
while [ $# -gt 0 ]; do
    case "$1" in
        apply|delete|status) ACTION="$1" ;;
        --yes) CONFIRM=1 ;;
        --world) WORLD=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}" ;;
        -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1' (usage: {apply|delete|status} [--yes] [--world] [--run ID])" >&2; exit 1 ;;
    esac
    shift
done
[ -n "${ACTION}" ] || { echo "❌ missing action: apply | delete | status" >&2; exit 1; }
if [ -z "${BENCH_RUN_ID:-}" ]; then
    _latest="$(ls -1d "${DIR}"/results/r* 2>/dev/null | tail -1 || true)"
    BENCH_RUN_ID="${_latest:+$(basename "${_latest}")}"
    [ -n "${BENCH_RUN_ID}" ] || { [ "${ACTION}" = "status" ] && BENCH_RUN_ID="rstatus"; }
fi
export BENCH_RUN_ID
# shellcheck disable=SC2034  # read by bench-lib.sh (bench_run)
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"

RULE_CONSENSUS="${BENCH_FIREWALL_RULES[0]}"
RULE_IAP_RPC="${BENCH_FIREWALL_RULES[1]}"
IAP_RANGE="35.235.240.0/20"
TARGET_TAG="bench-node"
DESC="benchmark=1 run=${BENCH_RUN_ID}"
DEVNET_RULE="devnet-allow-consensus"

for r in "${BENCH_FIREWALL_RULES[@]}"; do bench_assert_bench_name "firewall rule" "${r}"; done
[ "${INSTANCE_TAGS}" = "${TARGET_TAG}" ] || bench_die "INSTANCE_TAGS=${INSTANCE_TAGS}, expected ${TARGET_TAG}"

rule_json() { gcloud compute firewall-rules describe "$1" --project="${PROJECT_ID}" --format=json 2>/dev/null || true; }

# assert_ours <name> <json> — an existing rule may only be touched if it is ours.
assert_ours() {
    local name="$1" json="$2" tags desc
    tags="$(printf '%s' "${json}" | jq -r '(.targetTags // []) | join(",")')"
    desc="$(printf '%s' "${json}" | jq -r '.description // ""')"
    [ "${tags}" = "${TARGET_TAG}" ] || bench_die "existing rule ${name} targets '${tags}', not exactly ${TARGET_TAG} — not ours, refusing."
    case "${desc}" in *benchmark=1*) ;; *) bench_die "existing rule ${name} has no benchmark=1 in its description ('${desc}') — not ours, refusing." ;; esac
}

# foreign_bench_node_rules — rules that select bench-node but are not ours (should be none).
foreign_bench_node_rules() {
    gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r --arg t "${TARGET_TAG}" --arg a "${RULE_CONSENSUS}" --arg b "${RULE_IAP_RPC}" \
            '.[] | select((.targetTags // []) | index($t)) | select(.name != $a and .name != $b) | .name'
}

devnet_rule_canon() { rule_json "${DEVNET_RULE}" | jq -S '.' 2>/dev/null || true; }

check_devnet_rule_against_snapshot() {
    local now="$1" snap="${BENCH_RESULTS_DIR}/pre-firewall.json" pre
    [ -f "${snap}" ] || return 0
    pre="$(jq -S --arg n "${DEVNET_RULE}" '.[] | select(.name == $n)' "${snap}")"
    if [ -n "${pre}" ] && [ "${pre}" != "${now}" ]; then
        echo "❌❌ ${DEVNET_RULE} differs from the run's pre-snapshot (${snap}):" >&2
        diff <(printf '%s\n' "${pre}") <(printf '%s\n' "${now}") >&2 || true
        return 1
    fi
    echo "    ✓ ${DEVNET_RULE} identical to the run pre-snapshot"
}

do_status() {
    echo ">>> bench firewall status (project ${PROJECT_ID}, run ${BENCH_RUN_ID})"
    gcloud compute firewall-rules list --project="${PROJECT_ID}" \
        --filter="name~'^bench-' OR targetTags:${TARGET_TAG}" \
        --format='table(name,direction,sourceRanges.list():label=SRC,allowed[].map().firewall_rule().list():label=ALLOW,targetTags.list():label=TARGET,description)'
    local foreign; foreign="$(foreign_bench_node_rules)"
    if [ -n "${foreign}" ]; then echo "    ⚠ non-bench rules select ${TARGET_TAG}: ${foreign}"; else echo "    ✓ no non-bench rule selects ${TARGET_TAG}"; fi
    local dj; dj="$(devnet_rule_canon)"
    if [ -n "${dj}" ]; then
        echo "    ${DEVNET_RULE}: $(printf '%s' "${dj}" | jq -r '(.sourceRanges|length|tostring) + " source ranges, targets " + ((.targetTags//[])|join(","))')"
        check_devnet_rule_against_snapshot "${dj}" || true
    fi
}

consensus_sources() {
    local i ext int out=()
    if [ "${WORLD}" -eq 1 ]; then printf '0.0.0.0/0'; return 0; fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        ext="$(tn_node_ext_ip "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" 2>/dev/null || true)"
        int="$(tn_node_int_ip "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" 2>/dev/null || true)"
        if [ -z "${ext}" ] || [ -z "${int}" ]; then
            echo "❌ ${INSTANCE_NAMES[$i]} has no external/internal IP yet (ext='${ext}' int='${int}') — create the fleet first, or use --world." >&2
            return 1
        fi
        out+=("${ext}/32" "${int}/32")
    done
    local IFS=,; printf '%s' "${out[*]}"
}

upsert_rule() { # <name> <rules> <sources>
    local name="$1" rules="$2" src="$3" json
    json="$(rule_json "${name}")"
    if [ -n "${json}" ]; then
        assert_ours "${name}" "${json}"
        echo ">>> ${name}: exists (ours) — updating"
        bench_run gcloud compute firewall-rules update "${name}" --project="${PROJECT_ID}" \
            --rules="${rules}" --source-ranges="${src}" --target-tags="${TARGET_TAG}" --description="${DESC}"
    else
        echo ">>> ${name}: creating"
        bench_run gcloud compute firewall-rules create "${name}" --project="${PROJECT_ID}" \
            --network=default --direction=INGRESS --action=ALLOW --priority=1000 \
            --rules="${rules}" --source-ranges="${src}" --target-tags="${TARGET_TAG}" --description="${DESC}"
    fi
}

do_apply() {
    [ -n "${BENCH_RUN_ID:-}" ] || bench_die "no run id (pass --run or BENCH_RUN_ID)"
    local before after foreign src
    foreign="$(foreign_bench_node_rules)"
    [ -z "${foreign}" ] || bench_die "non-bench rules already select ${TARGET_TAG}: ${foreign} — investigate before applying."
    before="$(devnet_rule_canon)"
    [ -n "${before}" ] || bench_warn "${DEVNET_RULE} not found — nothing to protect-diff against"
    src="$(consensus_sources)"
    echo ">>> consensus sources: ${src}"
    upsert_rule "${RULE_CONSENSUS}" "udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" "${src}"
    upsert_rule "${RULE_IAP_RPC}" "tcp:8545" "${IAP_RANGE}"
    after="$(devnet_rule_canon)"
    if [ "${before}" != "${after}" ]; then
        echo "❌❌ ${DEVNET_RULE} CHANGED during this apply — the bench must never touch it:" >&2
        diff <(printf '%s\n' "${before}") <(printf '%s\n' "${after}") >&2 || true
        exit 1
    fi
    echo "    ✓ ${DEVNET_RULE} unchanged by this apply"
    [ -z "${after}" ] || check_devnet_rule_against_snapshot "${after}" || exit 1
}

do_delete() {
    local r json
    for r in "${BENCH_FIREWALL_RULES[@]}"; do
        json="$(rule_json "${r}")"
        if [ -z "${json}" ]; then echo ">>> ${r}: absent"; continue; fi
        assert_ours "${r}" "${json}"
        echo ">>> ${r}: deleting"
        bench_run gcloud compute firewall-rules delete "${r}" --project="${PROJECT_ID}" --quiet
    done
}

case "${ACTION}" in
    status) do_status ;;
    apply)  do_apply ;;
    delete) do_delete ;;
esac
[ "${ACTION}" = "status" ] || [ "${CONFIRM}" -eq 1 ] || echo "DRY RUN — re-run with --yes to apply."
