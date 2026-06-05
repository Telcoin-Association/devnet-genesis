#!/bin/bash
#
# Tear down the Global External Application Load Balancer for
# rpc.devnet.telcoin.network in reverse dependency order. Each delete is best-effort
# — "not found" is treated as success so the script is safe to re-run.
#
# Order (reverse of setup):
#   forwarding-rule → https-proxy → ssl-cert → url-map → backend-service →
#   health-check → instance-groups → static IP → firewall rule
#

set -u

source ./config.sh

echo "=========================================="
echo "Tearing down ${LB_HOSTNAME} load balancer"
echo "Project: ${PROJECT_ID}"
echo "=========================================="

# Helper: delete-or-ignore. Always exits 0 so `set -u` semantics don't bite us
# when an earlier teardown removed a downstream resource.
delete_global() {
    local kind="$1"
    local name="$2"
    echo ">>> deleting global ${kind} ${name}"
    gcloud compute "${kind}" delete "${name}" \
        --project="${PROJECT_ID}" --global --quiet 2>&1 \
        | grep -v -E "was not found|already in use" || true
}

delete_zonal_ig() {
    local name="$1"
    local zone="$2"
    echo ">>> deleting instance-group ${name} in ${zone}"
    gcloud compute instance-groups unmanaged delete "${name}" \
        --project="${PROJECT_ID}" --zone="${zone}" --quiet 2>&1 \
        | grep -v -E "was not found|already in use" || true
}

#
# 1. Forwarding rule
#
echo ""
gcloud compute forwarding-rules delete "${LB_FORWARDING_RULE}" \
    --project="${PROJECT_ID}" --global --quiet 2>&1 \
    | grep -v "was not found" || true

#
# 2. Target HTTPS proxy
#
echo ""
gcloud compute target-https-proxies delete "${LB_HTTPS_PROXY}" \
    --project="${PROJECT_ID}" --global --quiet 2>&1 \
    | grep -v "was not found" || true

#
# 3. SSL certificate
#
echo ""
delete_global "ssl-certificates" "${LB_SSL_CERT}"

#
# 4. URL map
#
echo ""
delete_global "url-maps" "${LB_URL_MAP}"

#
# 5. Backend service
#
echo ""
delete_global "backend-services" "${LB_BACKEND_SERVICE}"

#
# 6. Health check
#
echo ""
delete_global "health-checks" "${LB_HEALTH_CHECK_NAME}"

#
# 7. Instance groups (one per zone)
#
echo ""
for i in "${!INSTANCE_NAMES[@]}"; do
    ig="${LB_NAME_PREFIX}-ig-$((i+1))"
    delete_zonal_ig "${ig}" "${ZONES[$i]}"
done

#
# 8. Static global IP
#
echo ""
echo ">>> deleting global address ${LB_GLOBAL_IP_NAME}"
gcloud compute addresses delete "${LB_GLOBAL_IP_NAME}" \
    --project="${PROJECT_ID}" --global --quiet 2>&1 \
    | grep -v "was not found" || true

#
# 9. Firewall rule
#
echo ""
echo ">>> deleting firewall rule ${LB_FIREWALL_RULE}"
gcloud compute firewall-rules delete "${LB_FIREWALL_RULE}" \
    --project="${PROJECT_ID}" --quiet 2>&1 \
    | grep -v "was not found" || true

echo ""
echo "=========================================="
echo "Teardown complete."
echo "=========================================="
