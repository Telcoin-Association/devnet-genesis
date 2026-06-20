#!/bin/bash
#
# Lock down the devnet with tag-based VPC firewall rules on the project's
# `default` network (target tag `validator`, which every instance carries):
#
#   devnet-allow-consensus         INGRESS ALLOW udp:49590,49594  from node IPs only     pri 1000
#   devnet-allow-consensus-egress  EGRESS  ALLOW udp:49590,49594  to node IPs only       pri 1000
#   devnet-deny-consensus-egress   EGRESS  DENY  udp:49590,49594  to 0.0.0.0/0           pri 1100
#   devnet-allow-web               INGRESS ALLOW tcp:80,443       from 0.0.0.0/0         pri 1000
#   devnet-allow-health-check      INGRESS ALLOW tcp:43174        from Google HC ranges  pri 1000
#
# Posture:
#   - Consensus UDP (primary 49590 + worker 49594) is locked to the 5 nodes'
#     own internal + external IPs, ingress AND egress. Nodes dial each other's
#     external multiaddrs (startup.sh bakes /ip4/${EXTERNAL_IP}/udp/... into
#     node-info) and GCP's one-to-one NAT preserves the sender's external IP,
#     so external /32s carry the real traffic; internal /32s are included
#     because listeners bind them (harmless and future-proof).
#   - The DENY backstop exists because the VPC's implied egress rule is
#     allow-all: without it, the egress ALLOW above would be meaningless.
#     ALLOW (1000) beats DENY (1100) beats the implied allow (65535).
#     Only udp:49590/49594 egress is denied — DNS, NTP, apt, etc. untouched.
#   - 8545 is NOT public: reth binds RPC/WS to loopback and Caddy fronts them on
#     443 (TLS), so the node serves RPC only via the Caddy edge -- never a raw
#     public :8545. 80 is required for certbot http-01 (Let's Encrypt probe IPs
#     are unpublished) and is the LB backend named port; 443 is the Caddy TLS RPC.
#   - Ingress needs no deny backstop: the VPC's implied ingress rule is
#     already deny-all.
#
# *** IMPORTANT: node IPs are EPHEMERAL. ***
# This script queries the live IPs at run time. Any instance stop/start
# changes its external IP and silently invalidates the consensus rules,
# cutting that node out of p2p (this is exactly what happened to node3).
# RE-RUN THIS SCRIPT AFTER ANY INSTANCE STOP/START.
#
# Each rule is reconciled idempotently (describe → create-or-update), so
# re-running is safe. Note: `firewall-rules update` cannot change an existing
# rule's direction/action — those are fixed per rule name; only rules, ranges,
# priority, and tags are reconciled.
#

set -u

source ./config.sh

# Documented Google health-check / LB probe source ranges.
# https://cloud.google.com/load-balancing/docs/health-check-concepts#ip-ranges
GOOGLE_HC_RANGES="130.211.0.0/22,35.191.0.0/16,209.85.152.0/22,209.85.204.0/22"

echo "=========================================="
echo "Reconciling devnet firewall rules (network=default, tag=validator)"
echo "Project: ${PROJECT_ID}"
echo "Instances covered: ${#INSTANCE_NAMES[@]} (validators + observer)"
echo "=========================================="

#
# 0. Gather the live node IPs (internal + external) for the consensus rules.
#
# Fail hard if any instance is missing either IP — reconciling with a partial
# set would cut a live node out of consensus.
#
echo ""
echo ">>> Step 0: querying live node IPs (ephemeral — see header)"
echo ""
NODE_IPS_CSV=""
for i in "${!INSTANCE_NAMES[@]}"; do
    # csv format preserves empty fields, so a missing IP is detectable.
    line=$(gcloud compute instances describe "${INSTANCE_NAMES[$i]}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONES[$i]}" \
        --format='csv[no-heading](networkInterfaces[0].networkIP, networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null)
    internal_ip="${line%%,*}"
    external_ip="${line#*,}"

    if [ -z "${internal_ip}" ] || [ -z "${external_ip}" ] || [ "${internal_ip}" = "${line}" ]; then
        echo "ERROR: ${INSTANCE_NAMES[$i]} (${ZONES[$i]}) is missing an internal or external IP."
        echo "       Got: internal='${internal_ip}' external='${external_ip}'"
        echo "       Is the instance running? Refusing to reconcile with a partial IP set."
        exit 1
    fi

    printf '  %-20s internal=%-15s external=%s\n' "${INSTANCE_NAMES[$i]}" "${internal_ip}" "${external_ip}"
    NODE_IPS_CSV+="${internal_ip}/32,${external_ip}/32,"
done
NODE_IPS_CSV="${NODE_IPS_CSV%,}"
echo ""
echo "Consensus allow set (${#INSTANCE_NAMES[@]} nodes × internal+external):"
echo "  ${NODE_IPS_CSV}"

# ensure_fw_rule NAME DIRECTION ACTION PRIORITY RULES RANGES DESCRIPTION
# Creates the rule on `default` targeting tag `validator`, or reconciles
# rules/ranges/priority/tags in place if it already exists. RANGES is
# --source-ranges for INGRESS, --destination-ranges for EGRESS.
ensure_fw_rule() {
    local name="$1"
    local direction="$2"
    local action="$3"
    local priority="$4"
    local rules="$5"
    local ranges="$6"
    local desc="$7"

    local range_flag="--source-ranges"
    if [ "${direction}" = "EGRESS" ]; then
        range_flag="--destination-ranges"
    fi

    if gcloud compute firewall-rules describe "${name}" \
            --project="${PROJECT_ID}" --quiet >/dev/null 2>&1; then
        echo "    ${name} exists — reconciling rules/ranges/priority/tags"
        gcloud compute firewall-rules update "${name}" \
            --project="${PROJECT_ID}" \
            --rules="${rules}" \
            "${range_flag}=${ranges}" \
            --priority="${priority}" \
            --target-tags=validator
    else
        echo "    ${name} — creating"
        gcloud compute firewall-rules create "${name}" \
            --project="${PROJECT_ID}" \
            --network=default \
            --direction="${direction}" \
            --action="${action}" \
            --rules="${rules}" \
            "${range_flag}=${ranges}" \
            --priority="${priority}" \
            --target-tags=validator \
            --description="${desc}"
    fi
}

#
# 1. Consensus p2p ingress (primary + worker QUIC) — node IPs only
#
echo ""
echo ">>> Step 1: devnet-allow-consensus (INGRESS udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT} from node IPs)"
ensure_fw_rule "devnet-allow-consensus" \
    "INGRESS" "ALLOW" "1000" \
    "udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" \
    "${NODE_IPS_CSV}" \
    "devnet consensus p2p ingress from node IPs only (re-run setup-firewall.sh after IP changes)"

#
# 2. Consensus p2p egress — node IPs only (beats the deny backstop below)
#
echo ""
echo ">>> Step 2: devnet-allow-consensus-egress (EGRESS udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT} to node IPs)"
ensure_fw_rule "devnet-allow-consensus-egress" \
    "EGRESS" "ALLOW" "1000" \
    "udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" \
    "${NODE_IPS_CSV}" \
    "devnet consensus p2p egress to node IPs only (re-run setup-firewall.sh after IP changes)"

#
# 3. Consensus egress deny backstop — overrides the VPC implied allow-all egress
#
echo ""
echo ">>> Step 3: devnet-deny-consensus-egress (EGRESS DENY udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT} to 0.0.0.0/0)"
ensure_fw_rule "devnet-deny-consensus-egress" \
    "EGRESS" "DENY" "1100" \
    "udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" \
    "0.0.0.0/0" \
    "devnet consensus egress deny backstop (implied egress is allow-all)"

#
# 4. Web: certbot HTTP-01 (80) + Caddy TLS RPC/WSS (443) — public ingress
#
echo ""
echo ">>> Step 4: devnet-allow-web (INGRESS tcp:80,tcp:443 from 0.0.0.0/0)"
ensure_fw_rule "devnet-allow-web" \
    "INGRESS" "ALLOW" "1000" \
    "tcp:80,tcp:443" \
    "0.0.0.0/0" \
    "devnet web: certbot http-01 + Caddy TLS RPC/WSS (reth binds loopback)"

#
# 5. Per-node health-check probes from Google ranges
#
echo ""
echo ">>> Step 5: devnet-allow-health-check (INGRESS tcp:${DEFAULT_HEALTHCHECK_TCP_PORT} from Google ranges)"
ensure_fw_rule "devnet-allow-health-check" \
    "INGRESS" "ALLOW" "1000" \
    "tcp:${DEFAULT_HEALTHCHECK_TCP_PORT}" \
    "${GOOGLE_HC_RANGES}" \
    "devnet node health-check probes from Google HC ranges"

#
# 6. Print effective state so the operator can eyeball-verify
#
echo ""
echo ">>> Step 6: effective devnet firewall rules"
echo ""
gcloud compute firewall-rules list \
    --project="${PROJECT_ID}" \
    --filter="name~'^devnet-(allow|deny)-'" \
    --format="table(name, direction, priority, allowed[].map().firewall_rule().list(), denied[].map().firewall_rule().list(), sourceRanges.list(), destinationRanges.list(), targetTags.list())"

echo ""
echo "=========================================="
echo "Firewall reconcile complete."
echo "=========================================="
echo ""
echo "REMINDER: node IPs are ephemeral — re-run this script after any"
echo "instance stop/start, or the consensus rules go stale."
echo ""
echo "To delete a rule ad hoc:"
echo ""
echo "  gcloud compute firewall-rules delete <name> --project=${PROJECT_ID}"
echo ""
