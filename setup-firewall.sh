#!/bin/bash
#
# Reconcile the three validator-scoped rules in the global network firewall
# policy "telcon-network-default" with the current node IP set defined in
# config.sh, and re-enable them.
#
# Rules touched:
#   1111 (INGRESS) — RPC + consensus to validator IPs
#   1112 (EGRESS)  — consensus from validator IPs
#   1114 (INGRESS) — Google LB health-check probes to :43174
#
# Each call uses `rules update`, which replaces the IP / layer-4 sets
# in-place and preserves description / audit history. Re-running is safe.
# Disabling is a one-liner per rule and is intentionally not scripted.
#

set -u

source ./config.sh

# Existing typo "telcon-network-default" preserved — that's the live policy name.
POLICY="telcon-network-default"

# Documented Google health-check / LB probe ranges (rule 1114 source set).
# https://cloud.google.com/load-balancing/docs/health-check-concepts#ip-ranges
GOOGLE_HC_RANGES="130.211.0.0/22,35.191.0.0/16,209.85.152.0/22,209.85.204.0/22"

# Build the canonical validator IP CSV: every external + internal address
# from config.sh, each as a /32. Observer IPs are deliberately not included.
NODE_IPS_CSV=""
for ip in "${EXTERNAL_IPS[@]}" "${INTERNAL_IPS[@]}"; do
    NODE_IPS_CSV+="${ip}/32,"
done
NODE_IPS_CSV="${NODE_IPS_CSV%,}"

echo "=========================================="
echo "Reconciling firewall policy ${POLICY}"
echo "Project: ${PROJECT_ID}"
echo "Validator IPs (${#EXTERNAL_IPS[@]} external + ${#INTERNAL_IPS[@]} internal):"
echo "  ${NODE_IPS_CSV}"
echo "=========================================="

#
# 1. Rule 1111 — INGRESS: allow public + peer traffic to validator IPs
#
echo ""
echo ">>> Step 1: rule 1111 (INGRESS to validators on tcp:443,8545 + udp consensus)"
gcloud compute network-firewall-policies rules update 1111 \
    --firewall-policy="${POLICY}" \
    --global-firewall-policy \
    --project="${PROJECT_ID}" \
    --action=allow \
    --direction=INGRESS \
    --src-ip-ranges=0.0.0.0/0 \
    --dest-ip-ranges="${NODE_IPS_CSV}" \
    --layer4-configs="tcp:443,tcp:8545,udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" \
    --no-disabled

#
# 2. Rule 1112 — EGRESS: allow consensus UDP from validator IPs
#
echo ""
echo ">>> Step 2: rule 1112 (EGRESS from validators on udp consensus)"
gcloud compute network-firewall-policies rules update 1112 \
    --firewall-policy="${POLICY}" \
    --global-firewall-policy \
    --project="${PROJECT_ID}" \
    --action=allow \
    --direction=EGRESS \
    --src-ip-ranges="${NODE_IPS_CSV}" \
    --dest-ip-ranges=0.0.0.0/0 \
    --layer4-configs="udp:${DEFAULT_PRIMARY_UDP_PORT},udp:${DEFAULT_WORKER_UDP_PORT}" \
    --no-disabled

#
# 3. Rule 1114 — INGRESS: allow Google LB health-check probes to :43174
#
echo ""
echo ">>> Step 3: rule 1114 (INGRESS Google probes on tcp:${DEFAULT_HEALTHCHECK_TCP_PORT})"
gcloud compute network-firewall-policies rules update 1114 \
    --firewall-policy="${POLICY}" \
    --global-firewall-policy \
    --project="${PROJECT_ID}" \
    --action=allow \
    --direction=INGRESS \
    --src-ip-ranges="${GOOGLE_HC_RANGES}" \
    --layer4-configs="tcp:${DEFAULT_HEALTHCHECK_TCP_PORT}" \
    --no-disabled

#
# 4. Print effective state of the three rules so the operator can eyeball-verify
#
echo ""
echo ">>> Step 4: post-reconcile state (priorities 1111 / 1112 / 1114)"
echo ""
gcloud compute network-firewall-policies describe "${POLICY}" \
    --global \
    --project="${PROJECT_ID}" \
    --format="yaml(rules)" \
    | awk '/priority: 11(11|12|14)$/,/ruleTupleCount/'

echo ""
echo "=========================================="
echo "Firewall reconcile complete."
echo "=========================================="
echo ""
echo "To re-disable a rule ad hoc:"
echo ""
echo "  gcloud compute network-firewall-policies rules update <pri> \\"
echo "      --firewall-policy=${POLICY} --global-firewall-policy \\"
echo "      --project=${PROJECT_ID} --disabled"
echo ""
