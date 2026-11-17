#!/usr/bin/env bash
#
# setup-firewall.sh — the devnet's VPC firewall on the project's `default` network
# (deploy step 8; safe to re-run at any time, also on a running chain).
#
# Every fleet VM is created with the tags validator,http-server,https-server,lb-health-check
# (common/create-instances.sh). This script gives each VM purpose tags and keeps three rules
# (network default, priority 1000):
#
#   devnet-allow-consensus         INGRESS ALLOW udp:49590,udp:49594 from 0.0.0.0/0       -> devnet-p2p
#   devnet-allow-web               INGRESS ALLOW tcp:80,tcp:443      from 0.0.0.0/0       -> devnet-web
#   devnet-allow-gateway-upstream  INGRESS ALLOW tcp:8545,tcp:43174  from each gateway's  -> devnet-gw-upstream
#                                  internal /32 that fronts a standalone node (absent when no node is standalone)
#
# Tags per VM (add-tags / remove-tags; only what differs is changed; `validator` is left alone):
#   devnet-p2p          every node host (roles validator, observer, rpc)
#   devnet-web          every host that runs Caddy: a node with a same-host gateway, the rpc node,
#                       a gateway host (with TN_GATEWAY_ENABLE not 1: every node host, the model
#                       before launch 2)
#   devnet-gw-upstream  a node whose gateway is standalone
#   lb-health-check     removed from every fleet VM (the load balancer is gone)
#   http-server, https-server  removed from a VM that does not run Caddy (they feed Google's
#                       stock default-allow-http/https rules, if the project has them)
#
# Deleted when present: devnet-deny-consensus-egress, devnet-allow-consensus-egress,
# devnet-allow-health-check, devnet-allow-healthcheck-from-kuma and ${LEGACY_LB_FIREWALL_RULE}.
# Consensus UDP is open to any source at this layer; the host firewall narrows it
# (devnet-firewall.sh, devnet-p2p-committee.sh). No node IP appears in any rule any more, so a
# VM stop/start no longer makes a rule stale; the gateway's internal IP is stable while its VM exists.
#
# Order of changes, so a re-run on a running chain never drops traffic that was allowed a moment
# before: (A) add tags, (B) create or update the three allow rules (an update can move a rule's
# target tag, so the tag must already be on the VMs), (C) remove tags, (D) delete rules. In (D) the
# egress DENY backstop goes before the egress ALLOW: deleting the ALLOW first would leave the DENY
# (udp 49590/49594 to 0.0.0.0/0) blocking consensus egress to the fleet itself until the next call.
#
# Never edits or deletes a rule whose name does not start with `devnet-`; Google's stock
# default-allow-* rules are only reported.
#
# Usage:
#   ./setup-firewall.sh            dry run: reads the current state, prints every change it would make
#   ./setup-firewall.sh --yes      applies those changes
#   ./setup-firewall.sh --status   prints the devnet- rules and each fleet VM's tags
# Before launch 2 this script applied with no flag; devnet-deploy.sh step 8 calls it with --yes.
#
# Needs the VMs (deploy step 2 before step 8): tags live on them and the gateway's internal IP
# is read from its VM. Configuration: devnet-lib.sh sources ${CONFIG_FILE:-<this dir>/config.sh}.
# Exit: 0 ok · 1 a gcloud call failed or a VM is missing (the message names the rule or VM) ·
#       2 usage or configuration.

set -euo pipefail

fw_usage() {
    echo "usage: $0 [--yes | --status]"
    echo "  (no flag)  dry run: print every change against the current state"
    echo "  --yes      apply the changes (deploy step 8)"
    echo "  --status   print the devnet- rules and each fleet VM's tags"
}

FW_APPLY=0
FW_STATUS=0
for a in "$@"; do
    case "$a" in
        --yes) FW_APPLY=1 ;;
        --status) FW_STATUS=1 ;;
        -h|--help) fw_usage; exit 0 ;;
        *) echo "❌ unknown argument '$a'" >&2; fw_usage >&2; exit 2 ;;
    esac
done
if [ "${FW_APPLY}" -eq 1 ] && [ "${FW_STATUS}" -eq 1 ]; then
    echo "❌ --yes and --status do not go together" >&2
    exit 2
fi

# shellcheck source=devnet-lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

for v in PROJECT_ID VPC_TAG_P2P VPC_TAG_WEB VPC_TAG_GW_UPSTREAM NODE_RPC_PORT \
         DEFAULT_PRIMARY_UDP_PORT DEFAULT_WORKER_UDP_PORT DEFAULT_HEALTHCHECK_TCP_PORT LEGACY_LB_FIREWALL_RULE; do
    [ -n "${!v:-}" ] || { echo "❌ ${v} is not set in the configuration" >&2; exit 2; }
done
if ! tn_fleet_check; then
    echo "❌ the fleet arrays are inconsistent (lines above); nothing was read or changed" >&2
    exit 2
fi

R_CONSENSUS="devnet-allow-consensus"
R_WEB="devnet-allow-web"
R_GWUP="devnet-allow-gateway-upstream"
# Deletion order matters (header, step D): the egress DENY before the egress ALLOW.
OBSOLETE_RULES=(devnet-deny-consensus-egress devnet-allow-consensus-egress devnet-allow-health-check
                devnet-allow-healthcheck-from-kuma "${LEGACY_LB_FIREWALL_RULE}")
MANAGED_TAGS=("${VPC_TAG_P2P}" "${VPC_TAG_WEB}" "${VPC_TAG_GW_UPSTREAM}")

_fw_ours() {
    case "$1" in devnet-*) return 0 ;; esac
    echo "❌ refusing to touch firewall rule '$1': only rules named devnet-* belong to this script" >&2
    exit 2
}
for r in "${R_CONSENSUS}" "${R_WEB}" "${R_GWUP}" "${OBSOLETE_RULES[@]}"; do _fw_ours "${r}"; done

# --- gcloud: every call carries --project; a failed call exits 1 naming the rule or VM ----------
FW_OUT=""
FW_CHANGES=0
_fw_read() {   # _fw_read <what> <gcloud args…>  -> FW_OUT
    local what="$1"; shift
    if ! FW_OUT="$(gcloud "$@" --project "${PROJECT_ID}")"; then
        echo "❌ ${what}: gcloud $1 $2 $3 failed" >&2
        exit 1
    fi
}
_fw_change() {   # _fw_change <rule or VM> <gcloud args…>  (dry run: print only)
    local what="$1"; shift
    FW_CHANGES=$((FW_CHANGES + 1))
    if [ "${FW_APPLY}" -ne 1 ]; then
        printf '    would run: gcloud'; printf ' %q' "$@" --project "${PROJECT_ID}"; printf '\n'
        return 0
    fi
    printf '    + gcloud'; printf ' %q' "$@" --project "${PROJECT_ID}"; printf '\n'
    if ! gcloud "$@" --project "${PROJECT_ID}"; then
        echo "❌ ${what}: gcloud $1 $2 $3 failed; changes before this one are in place, re-run after fixing" >&2
        exit 1
    fi
}

# --- canonical forms, so "udp:1,2" == "udp:1,udp:2" and list order does not matter -------------
_fw_norm_list() { printf '%s\n' "${1:-}" | tr ';' ',' | tr ',' '\n' | sed '/^$/d' | LC_ALL=C sort -u | paste -sd, - ; }
_fw_norm_rules() {
    printf '%s\n' "${1:-}" | tr ';' ',' | tr ',' '\n' \
        | awk -F: 'NF == 0 { next } /^[0-9]/ { print p ":" $0; next } { p = $1; print }' \
        | LC_ALL=C sort -u | paste -sd, -
}
_fw_has() { case ",$1," in *",$2,"*) return 0 ;; esac; return 1; }   # _fw_has <list> <item>

# --- current state: VM tags + internal IPs, rules named devnet-* or default-allow-* -------------
V_TAGS=(); V_IP=()
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
    if ! line="$(gcloud compute instances describe "${inst}" --zone "${zone}" \
            --format='value[separator="|"](tags.items.list(),networkInterfaces[0].networkIP)' \
            --project "${PROJECT_ID}")" || [ "${line#*|}" = "${line}" ]; then
        echo "❌ VM ${inst} (${zone}) could not be read: does it exist? Deploy step 2 creates the VMs; step 8 needs them." >&2
        exit 1
    fi
    V_TAGS[i]="$(_fw_norm_list "${line%%|*}")"
    V_IP[i]="${line#*|}"
done

R_NAME=(); R_NET=(); R_DIR=(); R_PRI=(); R_DIS=(); R_ALLOW=(); R_DENY=(); R_SRC=(); R_DST=(); R_STAG=(); R_TTAG=()
_fw_read_rules() {
    local n net dir pri dis al de src dst stag ttag k=0
    _fw_read "listing the firewall rules" compute firewall-rules list \
        --filter="name~'^(devnet-|default-allow-)'" \
        --format='value[separator="|"](name,network.basename(),direction,priority,disabled,allowed[].map().firewall_rule().list(),denied[].map().firewall_rule().list(),sourceRanges.list(),destinationRanges.list(),sourceTags.list(),targetTags.list())'
    R_NAME=(); R_NET=(); R_DIR=(); R_PRI=(); R_DIS=(); R_ALLOW=(); R_DENY=(); R_SRC=(); R_DST=(); R_STAG=(); R_TTAG=()
    while IFS='|' read -r n net dir pri dis al de src dst stag ttag; do
        [ -n "${n}" ] || continue
        R_NAME[k]="${n}"; R_NET[k]="${net}"; R_DIR[k]="${dir}"; R_PRI[k]="${pri}"; R_DIS[k]="${dis}"
        R_ALLOW[k]="${al}"; R_DENY[k]="${de}"; R_SRC[k]="${src}"; R_DST[k]="${dst}"; R_STAG[k]="${stag}"; R_TTAG[k]="${ttag}"
        k=$((k + 1))
    done <<< "${FW_OUT}"
}
FW_IDX=""
_fw_rule_idx() {   # _fw_rule_idx <name> -> FW_IDX, rc 1 when absent
    local k
    for k in ${R_NAME[@]+"${!R_NAME[@]}"}; do
        [ "${R_NAME[$k]}" = "$1" ] && { FW_IDX="$k"; return 0; }
    done
    return 1
}
_fw_read_rules

# --- desired state ------------------------------------------------------------------------------
_fw_runs_caddy() {   # _fw_runs_caddy <i>
    case "${NODE_ROLES[$1]}" in gateway|rpc) return 0 ;; esac
    tn_is_node_index "$1" || return 1
    [ "${TN_GATEWAY_ENABLE:-0}" = "1" ] || return 0
    [ "$(tn_gateway_mode "$1")" = "same-host" ]
}
W_ADD=(); W_DEL=(); W_FINAL=(); GW_SRCS=""
for i in "${!INSTANCE_NAMES[@]}"; do
    want=""
    if tn_is_node_index "${i}"; then
        want="${VPC_TAG_P2P}"
        if [ "$(tn_gateway_mode "${i}")" = "standalone" ]; then
            want="${want},${VPC_TAG_GW_UPSTREAM}"
            j="$(tn_gateway_host_index "${i}")" || { echo "❌ ${INSTANCE_NAMES[$i]} is standalone but has no gateway entry" >&2; exit 2; }
            [ -n "${V_IP[$j]}" ] || { echo "❌ VM ${INSTANCE_NAMES[$j]} has no internal IP" >&2; exit 1; }
            GW_SRCS="${GW_SRCS},${V_IP[$j]}/32"
        fi
    fi
    _fw_runs_caddy "${i}" && want="${want},${VPC_TAG_WEB}"
    add=""; del=""
    for t in ${want//,/ }; do _fw_has "${V_TAGS[$i]}" "${t}" || add="${add},${t}"; done
    for t in "${MANAGED_TAGS[@]}" lb-health-check http-server https-server; do
        _fw_has "${V_TAGS[$i]}" "${t}" || continue
        _fw_has "${want}" "${t}" && continue
        case "${t}" in http-server|https-server) _fw_runs_caddy "${i}" && continue ;; esac
        del="${del},${t}"
    done
    W_ADD[i]="${add#,}"; W_DEL[i]="${del#,}"
    final=""
    for t in ${V_TAGS[$i]//,/ } ${add//,/ }; do _fw_has "${del}" "${t}" || final="${final},${t}"; done
    W_FINAL[i]="$(_fw_norm_list "${final}")"
done
GW_SRCS="${GW_SRCS#,}"

# --- printing -----------------------------------------------------------------------------------
_fw_print_rules() {   # _fw_print_rules <label>
    local k found=0
    echo "devnet- rules $1 (name, network, direction, priority, allow, deny, sources, destinations -> target tags):"
    for k in ${R_NAME[@]+"${!R_NAME[@]}"}; do
        case "${R_NAME[$k]}" in devnet-*) ;; *) continue ;; esac
        found=1
        printf '  %-36s %s %s %s allow=%s deny=%s src=%s dst=%s -> %s%s\n' "${R_NAME[$k]}" "${R_NET[$k]}" \
            "${R_DIR[$k]}" "${R_PRI[$k]}" "${R_ALLOW[$k]:--}" "${R_DENY[$k]:--}" "${R_SRC[$k]:--}" \
            "${R_DST[$k]:--}" "${R_TTAG[$k]:-(all VMs)}" "$([ "${R_DIS[$k]}" = True ] && echo ' DISABLED')"
    done
    [ "${found}" -eq 1 ] || echo "  (none)"
}
_fw_tags() { if [ "$1" = final ]; then printf '%s' "${W_FINAL[$2]}"; else printf '%s' "${V_TAGS[$2]}"; fi; }
_fw_print_stock() {   # _fw_print_stock <current|final> <label>
    local k i t on found=0 tags
    echo "Google's stock default-allow-* rules (information only, never changed here; VM tags $2):"
    for k in ${R_NAME[@]+"${!R_NAME[@]}"}; do
        case "${R_NAME[$k]}" in default-allow-*) ;; *) continue ;; esac
        found=1
        on=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            tags="$(_fw_tags "$1" "${i}")"
            if [ -z "${R_TTAG[$k]}" ]; then on="${on} ${INSTANCE_NAMES[$i]}"; continue; fi
            for t in ${R_TTAG[$k]//,/ }; do
                _fw_has "${tags}" "${t}" && { on="${on} ${INSTANCE_NAMES[$i]}"; break; }
            done
        done
        printf '  %-24s %s %s allow=%s from %s, target tags %s%s\n    opens it on:%s\n' "${R_NAME[$k]}" \
            "${R_DIR[$k]}" "${R_NET[$k]}" "${R_ALLOW[$k]:--}" "${R_SRC[$k]:--}" "${R_TTAG[$k]:-(none: every VM)}" \
            "$([ "${R_DIS[$k]}" = True ] && echo ' DISABLED')" "${on:- no fleet VM}"
    done
    [ "${found}" -eq 1 ] || echo "  (none present: default-allow-http, default-allow-https, default-allow-internal all absent)"
}
_fw_print_vms() {   # _fw_print_vms <current|final> <label>
    local i tags
    echo "Fleet VM tags $2:"
    for i in "${!INSTANCE_NAMES[@]}"; do
        tags="$(_fw_tags "$1" "${i}")"
        printf '  %-20s %-9s %-15s %s\n' "${INSTANCE_NAMES[$i]}" "${NODE_ROLES[$i]}" "${V_IP[$i]:--}" "${tags:-(no tags)}"
    done
}

echo "=========================================="
echo "devnet VPC firewall (network default) — project ${PROJECT_ID}"
if [ "${FW_STATUS}" -eq 1 ]; then echo "Mode: --status (read-only)"
elif [ "${FW_APPLY}" -eq 1 ]; then echo "Mode: --yes (apply)"
else echo "Mode: DRY RUN (nothing is changed; --yes applies)"; fi
echo "=========================================="

if [ "${FW_STATUS}" -eq 1 ]; then
    _fw_print_rules "(current)"; echo ""
    _fw_print_vms current "(current)"; echo ""
    _fw_print_stock current "(current)"
    exit 0
fi

# _fw_ensure <name> <rules> <source ranges> <target tag> <description>: INGRESS ALLOW, network
# default, priority 1000. `firewall-rules update` changes rules, source ranges, target tags,
# priority and the disabled bit in place; it cannot change network, direction or action, and
# this script never sets source tags or destination ranges: any of those differing = delete + create.
_fw_ensure() {
    local name="$1" rules src tag="$4" desc="$5" i upd=()
    rules="$(_fw_norm_rules "$2")"; src="$(_fw_norm_list "$3")"   # canonical forms, for comparing
    _fw_ours "${name}"
    local create=(compute firewall-rules create "${name}" --network default --direction INGRESS --action ALLOW
                  --rules "$2" --source-ranges "$3" --target-tags "${tag}" --priority 1000
                  --description "${desc}")
    if ! _fw_rule_idx "${name}"; then
        echo "  ${name}: create (INGRESS allow $2 from $3 -> ${tag})"
        _fw_change "rule ${name}" "${create[@]}"
        return 0
    fi
    i="${FW_IDX}"
    if [ "${R_NET[$i]}" != default ] || [ "${R_DIR[$i]}" != INGRESS ] || [ -n "${R_DENY[$i]}" ] \
       || [ -n "${R_STAG[$i]}" ] || [ -n "${R_DST[$i]}" ]; then
        echo "  ${name}: delete and re-create (now ${R_DIR[$i]} on ${R_NET[$i]}, deny=${R_DENY[$i]:--}, source tags=${R_STAG[$i]:--}, dst=${R_DST[$i]:--}: update cannot change these)"
        _fw_change "rule ${name}" compute firewall-rules delete "${name}" --quiet
        _fw_change "rule ${name}" "${create[@]}"
        return 0
    fi
    [ "$(_fw_norm_rules "${R_ALLOW[$i]}")" = "${rules}" ] || upd+=(--rules "$2")
    [ "$(_fw_norm_list "${R_SRC[$i]}")" = "${src}" ] || upd+=(--source-ranges "$3")
    [ "$(_fw_norm_list "${R_TTAG[$i]}")" = "${tag}" ] || upd+=(--target-tags "${tag}")
    [ "${R_PRI[$i]}" = 1000 ] || upd+=(--priority 1000)
    [ "${R_DIS[$i]}" != True ] || upd+=(--no-disabled)
    if [ "${#upd[@]}" -eq 0 ]; then
        echo "  ${name}: no change"
        return 0
    fi
    echo "  ${name}: update in place (${upd[*]})"
    _fw_change "rule ${name}" compute firewall-rules update "${name}" "${upd[@]}" --description "${desc}"
}
_fw_delete() {   # _fw_delete <name>
    _fw_ours "$1"
    if ! _fw_rule_idx "$1"; then
        echo "  $1: absent, skipped"
        return 0
    fi
    echo "  $1: delete"
    _fw_change "rule $1" compute firewall-rules delete "$1" --quiet
}

echo ""
echo ">>> A. add tags"
for i in "${!INSTANCE_NAMES[@]}"; do
    if [ -z "${W_ADD[$i]}" ]; then echo "  ${INSTANCE_NAMES[$i]}: nothing to add"; continue; fi
    echo "  ${INSTANCE_NAMES[$i]}: add ${W_ADD[$i]}"
    _fw_change "VM ${INSTANCE_NAMES[$i]}" compute instances add-tags "${INSTANCE_NAMES[$i]}" --zone "${ZONES[$i]}" --tags "${W_ADD[$i]}"
done

echo ""
echo ">>> B. allow rules"
_fw_ensure "${R_CONSENSUS}" "udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" "0.0.0.0/0" "${VPC_TAG_P2P}" \
    "devnet consensus P2P from any source; the host firewall narrows it (setup-firewall.sh)"
_fw_ensure "${R_WEB}" "tcp:80,tcp:443" "0.0.0.0/0" "${VPC_TAG_WEB}" \
    "devnet web on Caddy hosts: ACME http-01 and TLS RPC (setup-firewall.sh)"
if [ -n "${GW_SRCS}" ]; then
    _fw_ensure "${R_GWUP}" "tcp:${NODE_RPC_PORT},tcp:${DEFAULT_HEALTHCHECK_TCP_PORT}" "${GW_SRCS}" "${VPC_TAG_GW_UPSTREAM}" \
        "devnet standalone gateway to its node: RPC and health port (setup-firewall.sh)"
else
    echo "  ${R_GWUP}: no standalone node, not wanted (deleted in D if present)"
fi

echo ""
echo ">>> C. remove tags"
for i in "${!INSTANCE_NAMES[@]}"; do
    if [ -z "${W_DEL[$i]}" ]; then echo "  ${INSTANCE_NAMES[$i]}: nothing to remove"; continue; fi
    echo "  ${INSTANCE_NAMES[$i]}: remove ${W_DEL[$i]}"
    _fw_change "VM ${INSTANCE_NAMES[$i]}" compute instances remove-tags "${INSTANCE_NAMES[$i]}" --zone "${ZONES[$i]}" --tags "${W_DEL[$i]}"
done

echo ""
echo ">>> D. delete obsolete rules"
for r in "${OBSOLETE_RULES[@]}"; do _fw_delete "${r}"; done
[ -n "${GW_SRCS}" ] || _fw_delete "${R_GWUP}"

echo ""
echo ">>> listing"
[ "${FW_APPLY}" -eq 1 ] && [ "${FW_CHANGES}" -gt 0 ] && _fw_read_rules
if [ "${FW_APPLY}" -eq 1 ]; then
    _fw_print_rules "(read back after this run)"; echo ""
    _fw_print_vms final "(after this run)"; echo ""
    _fw_print_stock final "(after this run)"
else
    _fw_print_rules "(current; the dry run changed nothing)"; echo ""
    _fw_print_vms final "(after --yes)"; echo ""
    _fw_print_stock final "(after --yes)"
fi

echo ""
echo "=========================================="
if [ "${FW_CHANGES}" -eq 0 ]; then
    echo "No change: the VPC firewall already matches."
elif [ "${FW_APPLY}" -eq 1 ]; then
    echo "${FW_CHANGES} change(s) applied."
else
    echo "DRY RUN: ${FW_CHANGES} change(s) planned, nothing changed. Run with --yes to apply."
fi
echo "=========================================="
