#!/usr/bin/env bash
#
# devnet-teardown.sh — DESTROY the devnet node VMs (and their boot disks) and the legacy
# RPC load balancer, so the fleet can be rebuilt from scratch on a brand-new genesis.
#
# This is the counterpart to devnet-wipe.sh. Where wipe removes only chain data and
# deliberately PRESERVES keys, teardown removes the machines themselves — which is the
# only way to get fresh BLS/network/execution keys:
#
#   * common/create-instances.sh SKIPS instances that already exist, so a redeploy
#     against the live fleet would silently reuse the old VMs.
#   * setup-node.sh refuses keygen when ${DATA_DIR}/node-keys is present, and
#     devnet-keygen.sh always passes --json (non-interactive), so the run would then
#     abort at deploy step 5 with:
#         node-keys already exist at /var/lib/telcoin/node-keys -- refusing to overwrite
#
# Deleting the instance with --delete-disks=all takes the keys with it. Each node has
# exactly ONE disk (the 100GB pd-ssd boot disk created inline by create-instances.sh);
# there are no separate node data disks to enumerate.
#
# A full run (no instance names) does, in this order:
#   1. txgen: STOPS the transaction generator's unit (tn-transaction-generator.service) on
#      txgen-devnet over IAP ssh, so it does not hammer a dead endpoint. The VM stays and the
#      unit stays enabled (deploy step 19 restarts it). A VM that is absent or not running, or
#      a unit that is not installed, is reported and skipped.
#   2. VMs: deletes every INSTANCE_NAMES entry + its boot disk, in parallel (an entry that
#      does not exist is reported ALREADY ABSENT), then checks each one is gone.
#   3. load balancer: deletes the legacy Global External Application LB that fronted
#      rpc.devnet (the LEGACY_LB_* names in config.sh; made by common/setup-load-balancer.sh),
#      in reverse creation order: forwarding rule (HTTPS, :443), target HTTPS proxy, managed SSL
#      certificate, URL map, backend service, TCP health check, the unmanaged instance groups
#      <prefix>-ig-* (found by listing, in whatever zone each sits), the global address, the
#      LB firewall rule. setup-load-balancer.sh creates no HTTP (:80) proxy or forwarding rule.
#      Each piece is described first; an absent one prints "absent, skipped". A failed delete is
#      reported and the run goes on; a piece still referenced by a failed one is not attempted.
#   4. lists what remains: the reserved -devnet-ip addresses and any LB piece still there.
# Launch 2 serves rpc.devnet from the rpc node instead of the LB.
#
# OPERATOR: this script never touches DNS. Once the LB is gone, the rpc.devnet A record
# points at a released address: re-point it to the rpc node's static IP yourself.
#
# PRESERVED — this script does NOT touch any of these:
#   * the reserved static external IPs (STATIC_IP_NAMES, e.g. validator-1-devnet-ip).
#     They drop to RESERVED and are re-attached by name on recreate, so DNS A-records for
#     node{1..5}/admin.node*/obs. stay correct and deploy step 4 is a no-op.
#   * GCP Secret Manager secrets (obs-ingest-token, obs-grafana-admin,
#     devnet-admin-dashboard-hash)
#   * obs-devnet + its obs-devnet-data persistent disk (redeployed by deploy step 9)
#   * DNS records; VPC firewall rules other than the LB's own rule
#   * the WireGuard hub in tn-devops-sandbox
#   * devnet-indexer (terminated, out of scope) and the txgen-devnet VM itself
#
# Reaches GCP through the control plane only, except the one IAP ssh to txgen-devnet. It
# never SSHes to a node — the node is about to stop existing.
#
# DESTRUCTIVE AND IRREVERSIBLE: refuses to run unless --yes is passed OR FORCE=true is
# in the env. With neither, it prints exactly what WOULD be deleted and what is
# preserved, then exits 0.
#
# Usage:
#   ./devnet-teardown.sh                          # DRY RUN: print the plan, delete nothing
#   ./devnet-teardown.sh --yes                    # stop txgen, delete every node VM + boot disk, delete the LB
#   ./devnet-teardown.sh --yes --keep-lb          # the same, but leave the LB alone
#   ./devnet-teardown.sh --yes validator-3-devnet # stop txgen, delete one (or more) VM by name; LB untouched
#   ./devnet-teardown.sh --yes --lb-only          # the LB only (re-run after a partial LB failure)
#   FORCE=true ./devnet-teardown.sh               # same as --yes
#
# Exit: 0 done (or dry run); 1 bad flag/name, gcloud auth failed, or something could not be
# stopped/deleted (the run ends with a list of what is left).

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# txgen-devnet: the same names and defaults as devnet-txgen.sh's tunables.
TXGEN_INSTANCE="${TXGEN_INSTANCE:-txgen-devnet}"
TXGEN_ZONE="${TXGEN_ZONE:-us-west2-a}"
TXGEN_UNIT="tn-transaction-generator.service"

# --- args: flags (anywhere) + optional instance-name subset --------------------
CONFIRM=0
LB_ONLY=0
KEEP_LB=0
SELECTED=()
for arg in "$@"; do
    case "${arg}" in
        --yes)     CONFIRM=1 ;;
        --lb-only) LB_ONLY=1 ;;
        --keep-lb) KEEP_LB=1 ;;
        -*) echo "❌ unknown flag '${arg}' (supported: --yes, --lb-only, --keep-lb)" >&2; exit 1 ;;
        *)  SELECTED+=("${arg}") ;;
    esac
done
[ "${FORCE:-}" = "true" ] && CONFIRM=1
if [ "${LB_ONLY}" -eq 1 ] && [ "${KEEP_LB}" -eq 1 ]; then
    echo "❌ --lb-only and --keep-lb exclude each other" >&2; exit 1
fi
if [ "${LB_ONLY}" -eq 1 ] && [ "${#SELECTED[@]}" -gt 0 ]; then
    echo "❌ --lb-only takes no instance names" >&2; exit 1
fi

# Validate any requested names against INSTANCE_NAMES — never delete something this
# config does not own.
if [ "${#SELECTED[@]}" -gt 0 ]; then
    for want in "${SELECTED[@]}"; do
        found=0
        for have in "${INSTANCE_NAMES[@]}"; do
            [ "${want}" = "${have}" ] && { found=1; break; }
        done
        [ "${found}" -eq 1 ] || { echo "❌ unknown instance '${want}' (not in INSTANCE_NAMES)" >&2; exit 1; }
    done
fi
tn_teardown_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local inst="$1" s
    for s in "${SELECTED[@]}"; do [ "${s}" = "${inst}" ] && return 0; done
    return 1
}

# What this run covers: txgen + VMs unless --lb-only; the LB on a full run or --lb-only.
DO_VMS=1
if [ "${LB_ONLY}" -eq 1 ]; then DO_VMS=0; fi
DO_LB=0
if [ "${LB_ONLY}" -eq 1 ]; then
    DO_LB=1
elif [ "${#SELECTED[@]}" -eq 0 ] && [ "${KEEP_LB}" -eq 0 ]; then
    DO_LB=1
fi

# The rpc node's static IP: where rpc.devnet must point once the LB is gone.
RPC_IP_NAME="the rpc node's static IP"
for i in "${!NODE_ROLES[@]}"; do
    if [ "${NODE_ROLES[$i]}" = rpc ]; then RPC_IP_NAME="${STATIC_IP_NAMES[$i]}"; break; fi
done

# --- the legacy LB --------------------------------------------------------------
# Pieces in delete order (reverse of common/setup-load-balancer.sh's creation order).
# LB_BLOCKERS[i] = the key of the piece that references piece i: while that one is still
# there, deleting piece i cannot succeed, so it is not attempted. The instance groups (ig)
# are zonal and found by listing; every other piece has one fixed name.
LB_KEYS=(fr proxy cert urlmap backend hc ig ip fw)
LB_LABELS=("forwarding rule" "target HTTPS proxy" "SSL certificate" "URL map" "backend service"
           "health check (TCP)" "instance groups" "global address" "firewall rule")
LB_KINDS=(forwarding-rules target-https-proxies ssl-certificates url-maps backend-services
          health-checks instance-groups addresses firewall-rules)
LB_NAMES=("${LEGACY_LB_FORWARDING_RULE}" "${LEGACY_LB_HTTPS_PROXY}" "${LEGACY_LB_SSL_CERT}"
          "${LEGACY_LB_URL_MAP}" "${LEGACY_LB_BACKEND_SERVICE}" "${LEGACY_LB_HEALTH_CHECK_NAME}"
          "${LEGACY_LB_NAME_PREFIX}-ig-*" "${LEGACY_LB_GLOBAL_IP_NAME}" "${LEGACY_LB_FIREWALL_RULE}")
LB_GLOBAL=(1 1 1 1 1 1 0 1 0)
LB_BLOCKERS=("" fr proxy proxy urlmap backend backend fr "")

# _lb_gcloud <i> <verb> [args…] — gcloud compute <kind> <verb> <name>, with --global if global.
_lb_gcloud() {
    local i="$1" verb="$2"
    shift 2
    if [ "${LB_GLOBAL[$i]}" = 1 ]; then
        gcloud compute "${LB_KINDS[$i]}" "${verb}" "${LB_NAMES[$i]}" --global --project="${PROJECT_ID}" "$@"
    else
        gcloud compute "${LB_KINDS[$i]}" "${verb}" "${LB_NAMES[$i]}" --project="${PROJECT_ID}" "$@"
    fi
}
_lb_exists() { _lb_gcloud "$1" describe --format='value(name)' >/dev/null 2>&1; }
_lb_label_of() {
    local i
    for i in "${!LB_KEYS[@]}"; do
        if [ "${LB_KEYS[$i]}" = "$1" ]; then printf '%s %s' "${LB_LABELS[$i]}" "${LB_NAMES[$i]}"; return 0; fi
    done
}

# _lb_list_igs — fills IG_NAMES/IG_ZONES with every unmanaged group named <prefix>-ig-*.
# Listed, not derived from the arrays: the groups were made one per entry of the OLD fleet in
# that entry's zone, and node 2 has since moved region. rc 1 if the listing fails.
_lb_list_igs() {
    local out n z errf
    IG_NAMES=(); IG_ZONES=()
    errf="$(mktemp)" || return 1
    if ! out="$(gcloud compute instance-groups unmanaged list --project="${PROJECT_ID}" \
            --filter="name~'^${LEGACY_LB_NAME_PREFIX}-ig-'" --format='value(name,zone.basename())' 2>"${errf}")"; then
        tail -3 "${errf}" | sed 's/^/      /' >&2
        rm -f "${errf}"
        return 1
    fi
    rm -f "${errf}"
    while read -r n z; do
        [ -n "${n}" ] || continue
        IG_NAMES+=("${n}"); IG_ZONES+=("${z}")
    done <<< "${out}"
}

# _lb_snapshot — LB_PRESENT[i] = 1 / 0 / ? (? = the instance-group listing failed).
_lb_snapshot() {
    local i
    LB_PRESENT=()
    for i in "${!LB_KEYS[@]}"; do
        if [ "${LB_KEYS[$i]}" = ig ]; then
            if ! _lb_list_igs; then LB_PRESENT[i]="?"
            elif [ "${#IG_NAMES[@]}" -gt 0 ]; then LB_PRESENT[i]=1
            else LB_PRESENT[i]=0; fi
        elif _lb_exists "${i}"; then LB_PRESENT[i]=1
        else LB_PRESENT[i]=0; fi
    done
}

# _lb_print <word for a present piece> <word for an absent piece> — one line per piece.
_lb_print() {
    local i j n=0 scope
    for i in "${!LB_KEYS[@]}"; do
        n=$((n + 1))
        scope=global; [ "${LB_GLOBAL[$i]}" = 1 ] || scope=network
        if [ "${LB_KEYS[$i]}" = ig ]; then
            if [ "${LB_PRESENT[$i]}" = "?" ]; then
                printf '    %d. %-20s %-34s ❌ listing FAILED (state unknown)\n' "${n}" "${LB_LABELS[$i]}" "${LB_NAMES[$i]}"
            elif [ "${LB_PRESENT[$i]}" = 0 ]; then
                printf '    %d. %-20s %-34s %s\n' "${n}" "${LB_LABELS[$i]}" "${LB_NAMES[$i]}" "$2"
            else
                for j in "${!IG_NAMES[@]}"; do
                    printf '    %d. %-20s %-34s %s\n' "${n}" "instance group" "${IG_NAMES[$j]} (${IG_ZONES[$j]})" "$1"
                done
            fi
        elif [ "${LB_PRESENT[$i]}" = 1 ]; then
            printf '    %d. %-20s %-34s %s\n' "${n}" "${LB_LABELS[$i]}" "${LB_NAMES[$i]} (${scope})" "$1"
        else
            printf '    %d. %-20s %-34s %s\n' "${n}" "${LB_LABELS[$i]}" "${LB_NAMES[$i]} (${scope})" "$2"
        fi
    done
}

LEFT=()           # what this run leaves behind (printed before exit 1)
LB_LEFT=" "       # keys of LB pieces still standing after their step
_lb_left_has() { case "${LB_LEFT}" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
_lb_mark_left() { LB_LEFT="${LB_LEFT}$1 "; LEFT+=("$2"); }

# _lb_delete_all — describe, then delete, each piece in order. Never aborts on a failure.
_lb_delete_all() {
    local i j n=0 key label name blk log
    for i in "${!LB_KEYS[@]}"; do
        n=$((n + 1)); key="${LB_KEYS[$i]}"; label="${LB_LABELS[$i]}"; name="${LB_NAMES[$i]}"; blk="${LB_BLOCKERS[$i]}"
        if [ "${key}" = ig ]; then
            if ! _lb_list_igs; then
                echo "  ${n}. ${label} ${name}: ❌ listing FAILED — not deleted"
                _lb_mark_left ig "${label} ${name}: listing failed, state unknown"
                continue
            fi
            if [ "${#IG_NAMES[@]}" -eq 0 ]; then echo "  ${n}. ${label} ${name}: absent, skipped"; continue; fi
            for j in "${!IG_NAMES[@]}"; do
                if [ -n "${blk}" ] && _lb_left_has "${blk}"; then
                    echo "  ${n}. instance group ${IG_NAMES[$j]} (${IG_ZONES[$j]}): NOT attempted — the $(_lb_label_of "${blk}") still references it"
                    _lb_mark_left ig "instance group ${IG_NAMES[$j]} (${IG_ZONES[$j]}): not attempted, the $(_lb_label_of "${blk}") is still there"
                    continue
                fi
                log="${LOGS_DIR}/lb_${IG_NAMES[$j]}.log"
                if gcloud compute instance-groups unmanaged delete "${IG_NAMES[$j]}" --zone="${IG_ZONES[$j]}" \
                       --project="${PROJECT_ID}" --quiet >"${log}" 2>&1; then
                    echo "  ${n}. ✓ instance group ${IG_NAMES[$j]} (${IG_ZONES[$j]}) deleted"
                else
                    echo "  ${n}. ❌ instance group ${IG_NAMES[$j]} (${IG_ZONES[$j]}): delete FAILED — see ${log}"
                    tail -3 "${log}" | sed 's/^/        /'
                    _lb_mark_left ig "instance group ${IG_NAMES[$j]} (${IG_ZONES[$j]}): delete failed"
                fi
            done
            continue
        fi
        if ! _lb_exists "${i}"; then echo "  ${n}. ${label} ${name}: absent, skipped"; continue; fi
        if [ -n "${blk}" ] && _lb_left_has "${blk}"; then
            echo "  ${n}. ${label} ${name}: NOT attempted — the $(_lb_label_of "${blk}") still references it, so its delete would fail too"
            _lb_mark_left "${key}" "${label} ${name}: not attempted, the $(_lb_label_of "${blk}") is still there"
            continue
        fi
        log="${LOGS_DIR}/lb_${key}.log"
        if _lb_gcloud "${i}" delete --quiet >"${log}" 2>&1; then
            echo "  ${n}. ✓ ${label} ${name} deleted"
        else
            echo "  ${n}. ❌ ${label} ${name}: delete FAILED — see ${log}"
            tail -3 "${log}" | sed 's/^/        /'
            _lb_mark_left "${key}" "${label} ${name}: delete failed"
        fi
    done
}

echo "=========================================="
echo "devnet fleet TEARDOWN — destroys node VMs + boot disks and the legacy RPC load balancer"
echo "Project:   ${PROJECT_ID}"
echo "Method:    gcloud compute instances delete --delete-disks=all; LB pieces by name (describe, then delete)"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:    ${SELECTED[*]}"
if [ "${CONFIRM}" -eq 1 ]; then
    echo "Mode:      APPLY (--yes/FORCE) — THIS IS IRREVERSIBLE"
else
    echo "Mode:      DRY RUN (no --yes) — nothing will be deleted"
fi
echo "=========================================="

# --- the plan ------------------------------------------------------------------
# Resolve current state first so the dry run reflects reality (an already-deleted
# instance is reported as such rather than silently "planned").
echo ""
echo "DELETE plan:"
echo "  txgen (unit stopped before any VM is deleted; the VM and the unit's enablement stay):"
if [ "${DO_VMS}" -eq 1 ]; then
    txgen_status="$(gcloud compute instances describe "${TXGEN_INSTANCE}" --project="${PROJECT_ID}" \
        --zone="${TXGEN_ZONE}" --format='value(status)' 2>/dev/null)" || txgen_status=""
    case "${txgen_status}" in
        "")      printf '    - %-20s %-26s absent, skipped\n' "${TXGEN_INSTANCE}" "(${TXGEN_ZONE})" ;;
        RUNNING) printf '    - %-20s %-26s RUNNING: sudo systemctl stop %s\n' "${TXGEN_INSTANCE}" "(${TXGEN_ZONE})" "${TXGEN_UNIT}" ;;
        *)       printf '    - %-20s %-26s %s (not running), skipped\n' "${TXGEN_INSTANCE}" "(${TXGEN_ZONE})" "${txgen_status}" ;;
    esac
else
    echo "    (not touched: --lb-only)"
fi

echo "  node VMs + boot disks:"
targets=()
target_zones=()
if [ "${DO_VMS}" -eq 1 ]; then
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        zone="${ZONES[$i]}"
        role="$(tn_node_role "${i}")"

        tn_teardown_selected "${inst}" || continue

        if gcloud compute instances describe "${inst}" \
            --project="${PROJECT_ID}" --zone="${zone}" --format='value(name)' >/dev/null 2>&1; then
            printf '    - %-20s %-26s role=%-9s + its boot disk\n' "${inst}" "(${zone})" "${role}"
            targets+=("${inst}")
            target_zones+=("${zone}")
        else
            printf '    - %-20s %-26s ALREADY ABSENT — nothing to do\n' "${inst}" "(${zone})"
        fi
    done
    if [ "${#targets[@]}" -eq 0 ]; then
        echo "    (no live instances match — nothing to delete)"
    fi
else
    echo "    (not touched: --lb-only)"
fi

echo "  load balancer (legacy front of ${LEGACY_LB_HOSTNAME}; delete order):"
lb_todo=0
if [ "${DO_LB}" -eq 1 ]; then
    _lb_snapshot
    _lb_print "exists -> delete" "absent, skipped"
    for i in "${!LB_KEYS[@]}"; do
        if [ "${LB_PRESENT[$i]}" != 0 ]; then lb_todo=1; fi
    done
elif [ "${KEEP_LB}" -eq 1 ]; then
    echo "    (KEPT: --keep-lb)"
else
    echo "    (not touched: an instance subset was given; use --lb-only to delete it alone)"
fi

cat <<EOF

PRESERVE (explicitly NOT touched by this script):
  - reserved static external IPs: ${STATIC_IP_NAMES[*]}
      -> they return to RESERVED and are re-attached by name on recreate, so DNS stays valid
  - GCP secrets: ${OBS_SECRET_NAME}, obs-grafana-admin, ${TN_ADMIN_HASH_SECRET}
  - obs VM + data disk: ${OBS_INSTANCE_NAME}, ${OBS_DATA_DISK_NAME}
  - DNS records, VPC firewall rules (other than ${LEGACY_LB_FIREWALL_RULE}), the WireGuard hub
  - devnet-indexer (out of scope), the ${TXGEN_INSTANCE} VM (only its unit is stopped)

AFTER teardown the node keys are GONE. That is the point: deploy step 5 (devnet-keygen.sh)
mints brand-new BLS/network/execution keys, and step 6 seals them into a new genesis.
EOF
if [ "${DO_LB}" -eq 1 ]; then
    echo "OPERATOR: DNS is not touched. Once the LB is gone, re-point ${LEGACY_LB_HOSTNAME} (A record)"
    echo "to ${RPC_IP_NAME} (the rpc node); until then it resolves to a released address."
fi

if [ "${CONFIRM}" -ne 1 ]; then
    echo ""
    echo "DRY RUN only — re-run with --yes (or FORCE=true) to actually delete."
    # Dry run is not an error: exit 0 so callers can preview without tripping set -e.
    exit 0
fi

if [ "${#targets[@]}" -eq 0 ] && [ "${lb_todo}" -eq 0 ]; then
    echo ""
    echo "Nothing to delete — exiting cleanly."
    exit 0
fi

# --- apply ---------------------------------------------------------------------
# Warm gcloud's token cache serially first. Parallel gcloud invocations race on
# one-time SQLite schema migrations after an SDK update; one serial call completes
# the migration before the background jobs start (same guard create-instances.sh uses).
gcloud auth print-access-token >/dev/null || {
    echo "❌ gcloud auth failed — run 'gcloud auth login' and retry" >&2; exit 1; }

LOGS_DIR="${REPO_ROOT}/logs/instance-teardown/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${LOGS_DIR}"
rc=0

# --- 1. txgen: stop the unit before any VM is deleted ---------------------------
if [ "${DO_VMS}" -eq 1 ]; then
    echo ""
    echo ">>> txgen: stop ${TXGEN_UNIT} on ${TXGEN_INSTANCE} (stays enabled; deploy step 19 restarts it)"
    txgen_status="$(gcloud compute instances describe "${TXGEN_INSTANCE}" --project="${PROJECT_ID}" \
        --zone="${TXGEN_ZONE}" --format='value(status)' 2>/dev/null)" || txgen_status=""
    case "${txgen_status}" in
        "") echo "  ${TXGEN_INSTANCE} absent — skipped" ;;
        RUNNING)
            txlog="${LOGS_DIR}/txgen_stop.log"
            if txout="$(tn_iap_ssh "${TXGEN_INSTANCE}" "${TXGEN_ZONE}" \
                    "if systemctl cat ${TXGEN_UNIT} >/dev/null 2>&1; then sudo systemctl stop ${TXGEN_UNIT} && echo TD_TXGEN=stopped; else echo TD_TXGEN=no-unit; fi" \
                    2>"${txlog}")"; then
                case "${txout}" in
                    *TD_TXGEN=stopped*) echo "  ✓ ${TXGEN_UNIT} stopped (still enabled)" ;;
                    *TD_TXGEN=no-unit*) echo "  ${TXGEN_UNIT} not installed on ${TXGEN_INSTANCE} — skipped" ;;
                    *) echo "  ❌ no answer from the stop command — see ${txlog}"; rc=1
                       LEFT+=("txgen: ${TXGEN_UNIT} on ${TXGEN_INSTANCE} may still run (stop not confirmed)") ;;
                esac
            else
                echo "  ❌ could not stop ${TXGEN_UNIT} (ssh rc $?) — see ${txlog}; the teardown goes on"
                tail -3 "${txlog}" | sed 's/^/      /'
                rc=1
                LEFT+=("txgen: ${TXGEN_UNIT} on ${TXGEN_INSTANCE} may still run (stop failed)")
            fi ;;
        *) echo "  ${TXGEN_INSTANCE} is ${txgen_status} (not running) — nothing to stop, skipped" ;;
    esac
fi

# --- 2. VMs: parallel delete ----------------------------------------------------
if [ "${#targets[@]}" -gt 0 ]; then
    echo ""
    echo "Deleting ${#targets[@]} instance(s) in parallel. Logs: ${LOGS_DIR}"
    echo ""

    pids=()
    launched_names=()
    launched_logs=()

    for i in "${!targets[@]}"; do
        inst="${targets[$i]}"
        zone="${target_zones[$i]}"
        log="${LOGS_DIR}/${inst}_delete.log"

        (
            # `if gcloud ...` rather than `gcloud ...; rc=$?`: this subshell inherits set -e,
            # under which a bare failing command would exit before the status could be read
            # and the FAILED marker would never reach the log.
            echo "=== deleting ${inst} (${zone}) at $(date) ==="
            if gcloud compute instances delete "${inst}" \
                   --zone="${zone}" \
                   --project="${PROJECT_ID}" \
                   --delete-disks=all \
                   --quiet 2>&1; then
                echo "=== ${inst} deleted at $(date) ==="
                exit 0
            else
                rc=$?
                echo "=== FAILED to delete ${inst} (rc=${rc}) at $(date) ==="
                exit "${rc}"
            fi
        ) > "${log}" 2>&1 &

        pids+=($!)
        launched_names+=("${inst}")
        launched_logs+=("${log}")
        echo "  started delete of ${inst} (PID: $!, log: ${log})"
    done

    echo ""
    echo "All delete jobs launched. Waiting for completion..."
    echo ""

    for i in "${!pids[@]}"; do
        # `if wait` — a bare failing `wait` would end the script here under set -e.
        if wait "${pids[$i]}"; then
            echo "  ✓ deleted ${launched_names[$i]}"
        else
            echo "❌ failed to delete ${launched_names[$i]} — see ${launched_logs[$i]}" >&2
            echo "   last 10 lines:"
            tail -10 "${launched_logs[$i]}" | sed 's/^/   /'
            rc=1
        fi
    done

    # Assert what the operator actually cares about rather than trusting the delete's own
    # success line: the instances are gone.
    echo ""
    echo ">>> post-teardown verification"
    for i in "${!targets[@]}"; do
        inst="${targets[$i]}"; zone="${target_zones[$i]}"
        if gcloud compute instances describe "${inst}" \
            --project="${PROJECT_ID}" --zone="${zone}" --format='value(name)' >/dev/null 2>&1; then
            echo "  ❌ ${inst} STILL EXISTS" >&2
            rc=1
            LEFT+=("VM ${inst} (${zone}) still exists")
        else
            echo "  ✓ ${inst} gone"
        fi
    done
elif [ "${DO_VMS}" -eq 1 ]; then
    echo ""
    echo ">>> VMs: none live in scope — nothing to delete"
fi

# --- 3. the legacy LB -----------------------------------------------------------
if [ "${DO_LB}" -eq 1 ]; then
    echo ""
    echo ">>> load balancer: delete in order (logs: ${LOGS_DIR}/lb_*.log)"
    _lb_delete_all
fi

# --- 4. what remains ------------------------------------------------------------
# The static IPs must survive as RESERVED with unchanged addresses (that is what keeps
# DNS correct and deploy step 4 a no-op).
echo ""
echo "  reserved static IPs (expect STATUS=RESERVED, addresses unchanged):"
gcloud compute addresses list --project="${PROJECT_ID}" \
    --filter="name~'-devnet-ip$'" \
    --format='table(name, region, address, status)' | sed 's/^/    /' \
    || echo "    ❌ listing the addresses failed"
if [ "${DO_LB}" -eq 1 ]; then
    echo ""
    echo "  load balancer pieces now:"
    _lb_snapshot
    _lb_print "STILL EXISTS" "gone"
    for i in "${!LB_KEYS[@]}"; do
        if [ "${LB_PRESENT[$i]}" != 0 ]; then rc=1; fi
    done
fi

echo ""
if [ "${LB_LEFT}" != " " ]; then rc=1; fi
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "teardown complete. Next: ./devnet-deploy.sh --yes"
    echo "=========================================="
else
    echo "=========================================="
    echo "teardown finished WITH ERRORS — see ❌ lines above." >&2
    if [ "${#LEFT[@]}" -gt 0 ]; then
        echo "LEFT by this run:"
        for l in "${LEFT[@]}"; do echo "  - ${l}"; done
    fi
    if [ "${DO_LB}" -eq 1 ] && [ "${LB_LEFT}" != " " ]; then
        echo "A piece still referenced by a failed one cannot go before it does. Fix the cause, then:"
        echo "  ./devnet-teardown.sh --yes --lb-only"
    fi
    echo "=========================================="
fi
if [ "${DO_LB}" -eq 1 ]; then
    echo "DNS: re-point ${LEGACY_LB_HOSTNAME} to ${RPC_IP_NAME} (this script does not touch DNS)."
fi
exit "${rc}"
