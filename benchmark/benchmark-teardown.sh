#!/usr/bin/env bash
#
# benchmark-teardown.sh — remove everything the benchmark created, and prove it.
#
# Candidates (each re-proven before anything is deleted):
#   instances   bench INSTANCE_NAMES ∪ every instance labelled benchmark=1
#   firewall    BENCH_FIREWALL_RULES (only if they target exactly bench-node + say benchmark=1)
#   buckets     every bucket labelled benchmark=1 or named tn-devnet-bench-* (copied into
#               results/<run>/bucket/ first; a non-empty bucket whose copy failed is LEFT)
#   disks       labelled benchmark=1 or named ^bench- (after the instances are gone)
#   IAM         the compute SA's secretAccessor binding on the two bench-txgen-* secrets
#   secrets     bench-txgen-* — KEPT unless --purge
#   contracts   the tn-contracts worktree benchmark/work/tn-contracts + bench/r* branches with
#               no commits of their own
#   tunnels     local `gcloud compute start-iap-tunnel ... 18545` processes
#   local       benchmark/genesis/ is moved into results/<run>/genesis/
#
# Instance rule: labels.benchmark == "1" AND (name ∈ bench INSTANCE_NAMES OR name ~
# ^bench-(blaster|funder)) AND name ∉ the devnet denylist (INSTANCE_NAMES of a clean
# ../config.sh + obs-devnet txgen-devnet devnet-indexer). ANY violation aborts the whole
# teardown before a single delete.
#
# Usage: benchmark/benchmark-teardown.sh [--yes] [--run ID] [--purge]
# Without --yes it lists the candidates + denylist, prints the delete argv and changes nothing.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

CONFIRM=0; PURGE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --purge) PURGE=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}" ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --run ID, --purge)" >&2; exit 1 ;;
    esac
    shift
done
if [ -z "${BENCH_RUN_ID:-}" ]; then
    _latest="$(ls -1d "${DIR}"/results/r* 2>/dev/null | tail -1 || true)"
    BENCH_RUN_ID="${_latest:+$(basename "${_latest}")}"
    BENCH_RUN_ID="${BENCH_RUN_ID:-rteardown}"
fi
export BENCH_RUN_ID
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"

echo "=========================================="
echo "benchmark teardown — project ${PROJECT_ID}, run ${BENCH_RUN_ID}$([ "${PURGE}" -eq 1 ] && echo ' (--purge)')"
[ "${CONFIRM}" -eq 1 ] && echo "Mode: APPLY (--yes)" || echo "Mode: DRY RUN — nothing will be changed"
echo "=========================================="

VIOLATIONS=()
violate() { VIOLATIONS+=("$*"); echo "    ✗ VIOLATION: $*" >&2; }

# --- denylist -------------------------------------------------------------------------
DENY=()
while IFS= read -r n; do [ -n "${n}" ] && DENY+=("${n}"); done < <(bench_devnet_denylist)
[ "${#DENY[@]}" -ge 3 ] || bench_die "devnet denylist came back short (${DENY[*]:-}) — refusing to tear down blind"
echo ">>> devnet denylist (never deleted): ${DENY[*]}"

# --- instances --------------------------------------------------------------------------
ALL_INST="$(gcloud compute instances list --project="${PROJECT_ID}" --format=json)"
CAND_INST=()   # "zone name"
while IFS= read -r row; do
    [ -n "${row}" ] || continue
    name="${row#* }"; zone="${row%% *}"
    labelled="$(printf '%s' "${ALL_INST}" | jq -r --arg n "${name}" '.[] | select(.name == $n) | .labels.benchmark // ""')"
    ok_name=0
    bench_in_list "${name}" "${INSTANCE_NAMES[@]}" && ok_name=1
    case "${name}" in bench-blaster-*|bench-funder*) ok_name=1 ;; esac
    if [ "${labelled}" != "1" ]; then violate "instance ${name} lacks labels.benchmark=1"; continue; fi
    if [ "${ok_name}" -ne 1 ]; then violate "instance ${name} is labelled benchmark=1 but is not a bench node/blaster/funder name"; continue; fi
    if bench_in_list "${name}" "${DENY[@]}"; then violate "instance ${name} is on the devnet denylist"; continue; fi
    if bench_is_protected "${name}"; then violate "instance ${name} matches ${BENCH_PROTECTED_RE}"; continue; fi
    CAND_INST+=("${zone} ${name}")
done < <(printf '%s' "${ALL_INST}" | jq -r --argjson names "$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R . | jq -s .)" \
    '.[] | select((.labels.benchmark // "") == "1" or ((.name) as $n | $names | index($n))) | (.zone|split("/")|last) + " " + .name')
echo ">>> instance candidates (${#CAND_INST[@]}):"
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do echo "    - ${c#* } (${c%% *})"; done
overlap=""
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do bench_in_list "${c#* }" "${DENY[@]}" && overlap="${overlap} ${c#* }"; done
[ -z "${overlap}" ] && echo "    ✓ no devnet instance is a candidate" || violate "devnet instance(s) among candidates:${overlap}"

# --- firewall rules ------------------------------------------------------------------------
CAND_FW=()
for r in "${BENCH_FIREWALL_RULES[@]}"; do
    j="$(gcloud compute firewall-rules describe "${r}" --project="${PROJECT_ID}" --format=json 2>/dev/null || true)"
    [ -n "${j}" ] || continue
    bench_is_protected "${r}" && { violate "rule ${r} matches ${BENCH_PROTECTED_RE}"; continue; }
    if ! printf '%s' "${j}" | jq -e '(.targetTags // []) == ["bench-node"] and ((.description // "") | contains("benchmark=1"))' >/dev/null; then
        violate "rule ${r} does not target exactly bench-node with benchmark=1 in its description"; continue
    fi
    CAND_FW+=("${r}")
done
echo ">>> firewall candidates (${#CAND_FW[@]}): ${CAND_FW[*]:-none}"
foreign="$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json | jq -r \
    --argjson ours "$(printf '%s\n' "${BENCH_FIREWALL_RULES[@]}" | jq -R . | jq -s .)" \
    '.[] | select((.targetTags // []) | index("bench-node")) | select(.name as $n | $ours | index($n) | not) | .name')"
[ -z "${foreign}" ] || bench_warn "non-bench rules target bench-node (left alone): ${foreign}"

# --- buckets ---------------------------------------------------------------------------------
CAND_BKT=()
while IFS= read -r b; do
    [ -n "${b}" ] || continue
    case "${b}" in tn-devnet-bench-*) CAND_BKT+=("${b}") ;; *) violate "bucket ${b} is labelled benchmark=1 but not named tn-devnet-bench-*" ;; esac
done < <(bench_bucket_names)   # label benchmark=1 OR name tn-devnet-bench-* (step 12 labels in a 2nd call)
echo ">>> bucket candidates (${#CAND_BKT[@]}): ${CAND_BKT[*]:-none}"

# --- disks (listed now for the plan; re-listed after the instances are gone) ----------------
list_disks() {
    gcloud compute disks list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r '.[] | select(((.labels.benchmark // "") == "1") or (.name | test("^bench-"))) | (.zone|split("/")|last) + " " + .name + " " + (((.users // []) | map(split("/")|last)) | join(","))'
}
CAND_DISK=()
while IFS= read -r row; do
    [ -n "${row}" ] || continue
    read -r dz dn du <<< "${row}"
    case "${dn}" in bench-*) ;; *) violate "disk ${dn} labelled benchmark=1 but not named bench-*"; continue ;; esac
    bench_in_list "${dn}" "${DENY[@]}" && { violate "disk ${dn} is on the denylist"; continue; }
    if [ -n "${du:-}" ]; then
        for u in ${du//,/ }; do
            found=0; for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do [ "${c#* }" = "${u}" ] && found=1; done
            [ "${found}" -eq 1 ] || violate "disk ${dn} is attached to non-candidate instance ${u}"
        done
    fi
    CAND_DISK+=("${dz} ${dn}")
done < <(list_disks)
echo ">>> disk candidates (${#CAND_DISK[@]}; boot disks auto-delete with their instance):"
for c in "${CAND_DISK[@]+"${CAND_DISK[@]}"}"; do echo "    - ${c#* } (${c%% *})"; done

# --- local / git / IAM ------------------------------------------------------------------------
TUNNEL_PIDS="$(pgrep -f "start-iap-tunnel.*${BENCH_TUNNEL_PORT}" 2>/dev/null | tr '\n' ' ' || true)"
echo ">>> IAP tunnel pids: ${TUNNEL_PIDS:-none}"
WT_PRESENT=0; [ -e "${BENCH_CONTRACTS_WORKTREE}" ] && WT_PRESENT=1
BENCH_BRANCHES=()
if [ -d "${BENCH_CONTRACTS_SRC_DIR}" ]; then
    while IFS= read -r br; do
        [ -n "${br}" ] || continue
        if git -C "${BENCH_CONTRACTS_SRC_DIR}" merge-base --is-ancestor "${br}" "${BENCH_CONTRACTS_BASE_BRANCH}" 2>/dev/null; then
            BENCH_BRANCHES+=("${br}")
        else
            bench_warn "branch ${br} has commits not on ${BENCH_CONTRACTS_BASE_BRANCH} — left alone"
        fi
    done < <(git -C "${BENCH_CONTRACTS_SRC_DIR}" for-each-ref --format='%(refname:short)' 'refs/heads/bench/r*' 2>/dev/null)
fi
echo ">>> contracts worktree: $([ "${WT_PRESENT}" -eq 1 ] && echo "${BENCH_CONTRACTS_WORKTREE}" || echo absent); branches: ${BENCH_BRANCHES[*]:-none}"
SECRETS=("${BENCH_TXGEN_MASTER_SECRET}" "${BENCH_TXGEN_SEED_SECRET}")
echo ">>> secrets: ${SECRETS[*]} — $([ "${PURGE}" -eq 1 ] && echo 'DELETE (--purge)' || echo 'kept; accessor binding for the compute SA removed')"
echo ">>> local: $([ -d "${BENCH_DIR}/genesis" ] && echo "move ${BENCH_DIR}/genesis -> ${BENCH_RESULTS_DIR}/genesis" || echo 'no benchmark/genesis to move')"

if [ "${#VIOLATIONS[@]}" -gt 0 ]; then
    echo "" >&2
    echo "❌ ${#VIOLATIONS[@]} guard violation(s) — NOTHING was deleted:" >&2
    for v in "${VIOLATIONS[@]}"; do echo "   - ${v}" >&2; done
    exit 1
fi

# ================================ delete ==================================================
echo ""
echo ">>> plan / execution"
if [ -n "${TUNNEL_PIDS}" ]; then
    # shellcheck disable=SC2086  # pid list
    bench_run kill ${TUNNEL_PIDS} || true
fi
[ "${BENCH_APPLY}" = "1" ] && rm -f "$(bench_tunnel_pidfile)"
[ "${BENCH_APPLY}" = "1" ] && bench_manifest_ts teardown_start
for z in $(for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do echo "${c%% *}"; done | sort -u); do
    names=(); for c in "${CAND_INST[@]}"; do [ "${c%% *}" = "${z}" ] && names+=("${c#* }"); done
    bench_run gcloud compute instances delete "${names[@]}" --zone="${z}" --project="${PROJECT_ID}" --quiet
done
for r in "${CAND_FW[@]+"${CAND_FW[@]}"}"; do
    bench_run gcloud compute firewall-rules delete "${r}" --project="${PROJECT_ID}" --quiet
done
# Orphan disks: re-list after the instances are gone (boot disks auto-delete with them).
if [ "${BENCH_APPLY}" = "1" ]; then
    while IFS= read -r row; do
        [ -n "${row}" ] || continue
        read -r dz dn du <<< "${row}"
        case "${dn}" in bench-*) ;; *) continue ;; esac
        [ -z "${du:-}" ] || { bench_warn "disk ${dn} still attached to ${du} — left"; continue; }
        bench_run gcloud compute disks delete "${dn}" --zone="${dz}" --project="${PROJECT_ID}" --quiet
    done < <(list_disks)
else
    echo "    (orphan disks are re-listed and deleted after the instances; boot disks go with them)"
fi
LEFT_BKT=()
for b in "${CAND_BKT[@]+"${CAND_BKT[@]}"}"; do
    first_obj="$(gcloud storage ls "gs://${b}/**" --project="${PROJECT_ID}" 2>/dev/null | head -1 || true)"
    if [ -z "${first_obj}" ]; then
        bench_run gcloud storage buckets delete "gs://${b}" --project="${PROJECT_ID}" --quiet
        continue
    fi
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/bucket/${b}"
    if bench_run gcloud storage cp -r "gs://${b}/*" "${BENCH_RESULTS_DIR}/bucket/${b}/"; then
        bench_run gcloud storage rm -r "gs://${b}" --project="${PROJECT_ID}"
    else
        # The bucket may hold the only copy of a run's results: never delete it unbacked.
        echo "❌ backup of non-empty gs://${b} failed — bucket LEFT in place: ${b}" >&2
        LEFT_BKT+=("${b}")
    fi
done
for s in "${SECRETS[@]}"; do
    if gcloud secrets get-iam-policy "${s}" --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -e --arg m "serviceAccount:${SERVICE_ACCOUNT}" '[.bindings[]? | .members[]] | index($m)' >/dev/null; then
        bench_run gcloud secrets remove-iam-policy-binding "${s}" --project="${PROJECT_ID}" \
            --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --format=none
    fi
    if [ "${PURGE}" -eq 1 ]; then
        lbl="$(gcloud secrets describe "${s}" --project="${PROJECT_ID}" --format='value(labels.benchmark)' 2>/dev/null || true)"
        case "${s}" in bench-txgen-*) ;; *) bench_die "refusing to purge non bench-txgen secret ${s}" ;; esac
        if [ "${lbl}" = "1" ]; then bench_run gcloud secrets delete "${s}" --project="${PROJECT_ID}" --quiet
        else bench_warn "secret ${s} absent or not labelled benchmark=1 — not purged"; fi
    fi
done
if [ "${WT_PRESENT}" -eq 1 ]; then
    bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree remove --force "${BENCH_CONTRACTS_WORKTREE}"
fi
bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree prune
for br in "${BENCH_BRANCHES[@]+"${BENCH_BRANCHES[@]}"}"; do
    bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" branch -D "${br}"
done
if [ -d "${BENCH_DIR}/genesis" ]; then
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}"
    if [ -e "${BENCH_RESULTS_DIR}/genesis" ]; then
        bench_run mv "${BENCH_DIR}/genesis" "${BENCH_RESULTS_DIR}/genesis.$(date -u +%Y%m%d%H%M%S)"
    else
        bench_run mv "${BENCH_DIR}/genesis" "${BENCH_RESULTS_DIR}/genesis"
    fi
fi

# ================================ left-nothing checks =====================================
echo ""
echo ">>> left-nothing checks$([ "${BENCH_APPLY}" = "1" ] || echo ' (current state — dry run deleted nothing)')"
lrc=0
chk() { # <label> <count> [detail]
    if [ "$2" = "0" ]; then echo "    ✓ $1: none"; else echo "    ✗ $1: $2 ${3:-}"; lrc=1; fi
}
now_inst="$(gcloud compute instances list --project="${PROJECT_ID}" --format=json)"
chk "instances labelled benchmark=1" "$(printf '%s' "${now_inst}" | jq '[.[] | select((.labels.benchmark // "") == "1")] | length')" \
    "$(printf '%s' "${now_inst}" | jq -r '[.[] | select((.labels.benchmark // "") == "1") | .name] | join(",")')"
chk "instances named bench-*" "$(printf '%s' "${now_inst}" | jq '[.[] | select(.name | test("^bench-"))] | length')"
chk "firewall rules ^bench- or targeting bench-node" "$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json \
    | jq '[.[] | select((.name | test("^bench-")) or ((.targetTags // []) | index("bench-node")))] | length')"
chk "buckets labelled benchmark=1 / named tn-devnet-bench-*" "$(bench_bucket_names | grep -c . || true)" "${LEFT_BKT[*]:+(backup failed, left: ${LEFT_BKT[*]})}"
chk "disks labelled benchmark=1 / named bench-*" "$(list_disks | grep -c . || true)"
chk "local IAP tunnels on :${BENCH_TUNNEL_PORT}" "$(pgrep -f "start-iap-tunnel.*${BENCH_TUNNEL_PORT}" 2>/dev/null | grep -c . || true)"
chk "contracts worktree" "$([ -e "${BENCH_CONTRACTS_WORKTREE}" ] && echo 1 || echo 0)" "${BENCH_CONTRACTS_WORKTREE}"
chk "bench/r* branches" "$(git -C "${BENCH_CONTRACTS_SRC_DIR}" for-each-ref --format=x 'refs/heads/bench/r*' 2>/dev/null | grep -c . || true)"
acc=0
for s in "${SECRETS[@]}"; do
    gcloud secrets get-iam-policy "${s}" --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -e --arg m "serviceAccount:${SERVICE_ACCOUNT}" '[.bindings[]? | .members[]] | index($m)' >/dev/null && acc=$((acc + 1))
done
chk "compute-SA bindings on bench secrets" "${acc}"
echo "    devnet instances (must all be present):"
for d in "${DENY[@]}"; do
    st="$(printf '%s' "${now_inst}" | jq -r --arg n "${d}" '.[] | select(.name == $n) | .status')"
    pre=""
    [ -f "${BENCH_RESULTS_DIR}/pre-instances.json" ] && pre="$(jq -r --arg n "${d}" '.[] | select(.name == $n) | .status' "${BENCH_RESULTS_DIR}/pre-instances.json")"
    if [ -n "${st}" ]; then echo "      ✓ ${d} ${st}${pre:+ (pre-run ${pre})}"; else echo "      ✗ ${d} MISSING"; lrc=1; fi
done
if [ -f "${BENCH_RESULTS_DIR}/pre-firewall.json" ]; then
    a="$(jq -S '.[] | select(.name == "devnet-allow-consensus")' "${BENCH_RESULTS_DIR}/pre-firewall.json")"
    b="$(gcloud compute firewall-rules describe devnet-allow-consensus --project="${PROJECT_ID}" --format=json 2>/dev/null | jq -S . || true)"
    if [ "${a}" = "${b}" ]; then echo "    ✓ devnet-allow-consensus identical to the run pre-snapshot"; else echo "    ✗ devnet-allow-consensus differs from the run pre-snapshot"; lrc=1; fi
fi
if [ "${BENCH_APPLY}" = "1" ]; then
    [ "${lrc}" -eq 0 ] && echo "✓ teardown left nothing behind." || { echo "❌ teardown left something behind (✗ above)." >&2; exit 1; }
else
    echo "DRY RUN — re-run with --yes to delete the candidates above."
fi
