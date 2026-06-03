#!/bin/bash
#
# Provision the Global External Application Load Balancer that fronts the
# adiri validators at https://rpc.telcoin.network/.
#
# Each gcloud call is wrapped `describe || create` so the script is idempotent
# and safe to re-run after a partial failure. Order follows the dependency
# graph: firewall → instance groups → health check → backend service →
# url-map → ssl-cert → https-proxy → static IP → forwarding rule.
#
# DNS is intentionally NOT mutated here — the script prints the A record the
# operator must set. The Google-managed cert provisions only after the A
# record resolves to the LB IP (typically 5–60 minutes).
#

set -u

source ./config.sh

# Google's LB / health-check probe source ranges. Stable, documented at
# https://cloud.google.com/load-balancing/docs/health-check-concepts#ip-ranges
GOOGLE_LB_PROBE_RANGES="130.211.0.0/22,35.191.0.0/16"

echo "=========================================="
echo "Provisioning ${LB_HOSTNAME} → ${#INSTANCE_NAMES[@]} validators"
echo "Project: ${PROJECT_ID}"
echo "=========================================="

#
# 1. Firewall rule — allow LB probes + backend traffic to the lb-health-check tag
#
echo ""
echo ">>> Step 1: firewall rule ${LB_FIREWALL_RULE}"
if gcloud compute firewall-rules describe "${LB_FIREWALL_RULE}" \
        --project="${PROJECT_ID}" --quiet >/dev/null 2>&1; then
    echo "    exists — skipping"
else
    gcloud compute firewall-rules create "${LB_FIREWALL_RULE}" \
        --project="${PROJECT_ID}" \
        --direction=INGRESS \
        --network=default \
        --action=ALLOW \
        --rules="tcp:80,tcp:443,tcp:${DEFAULT_HEALTHCHECK_TCP_PORT}" \
        --source-ranges="${GOOGLE_LB_PROBE_RANGES}" \
        --target-tags=lb-health-check
fi

#
# 2. Unmanaged zonal instance groups — one per validator, each with a single member
#
echo ""
echo ">>> Step 2: instance groups (one per zone)"
for i in "${!INSTANCE_NAMES[@]}"; do
    instance="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    ig="${LB_NAME_PREFIX}-ig-$((i+1))"

    echo "    [${i}] ${ig} in ${zone} → ${instance}"

    if gcloud compute instance-groups unmanaged describe "${ig}" \
            --project="${PROJECT_ID}" --zone="${zone}" --quiet >/dev/null 2>&1; then
        echo "        group exists — skipping create"
    else
        gcloud compute instance-groups unmanaged create "${ig}" \
            --project="${PROJECT_ID}" --zone="${zone}"
    fi

    # add-instances is idempotent only by error message — the API rejects an
    # already-member instance with a non-zero exit. Detect membership first.
    if gcloud compute instance-groups unmanaged list-instances "${ig}" \
            --project="${PROJECT_ID}" --zone="${zone}" \
            --format="value(instance.basename())" 2>/dev/null | grep -qx "${instance}"; then
        echo "        ${instance} already a member"
    else
        gcloud compute instance-groups unmanaged add-instances "${ig}" \
            --project="${PROJECT_ID}" --zone="${zone}" \
            --instances="${instance}"
    fi

    gcloud compute instance-groups unmanaged set-named-ports "${ig}" \
        --project="${PROJECT_ID}" --zone="${zone}" \
        --named-ports="http:80"
done

#
# 3. Health check — TCP probe on the existing :43174 endpoint
#
echo ""
echo ">>> Step 3: health check ${LB_HEALTH_CHECK_NAME}"
if gcloud compute health-checks describe "${LB_HEALTH_CHECK_NAME}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping"
else
    gcloud compute health-checks create tcp "${LB_HEALTH_CHECK_NAME}" \
        --project="${PROJECT_ID}" \
        --global \
        --port="${DEFAULT_HEALTHCHECK_TCP_PORT}" \
        --check-interval=10s \
        --timeout=5s \
        --healthy-threshold=2 \
        --unhealthy-threshold=3
fi

#
# 4. Backend service — global, EXTERNAL_MANAGED so localityLbPolicy is honored
#
echo ""
echo ">>> Step 4: backend service ${LB_BACKEND_SERVICE}"
if gcloud compute backend-services describe "${LB_BACKEND_SERVICE}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping create"
else
    gcloud compute backend-services create "${LB_BACKEND_SERVICE}" \
        --project="${PROJECT_ID}" \
        --global \
        --protocol=HTTP \
        --port-name=http \
        --health-checks="${LB_HEALTH_CHECK_NAME}" \
        --load-balancing-scheme=EXTERNAL_MANAGED \
        --locality-lb-policy=ROUND_ROBIN \
        --timeout=30s
fi

# Attach each instance group as a backend. add-backend is not idempotent —
# detect existing membership and skip.
existing_backends=$(gcloud compute backend-services describe "${LB_BACKEND_SERVICE}" \
    --project="${PROJECT_ID}" --global \
    --format="value(backends.group)" 2>/dev/null || echo "")

for i in "${!INSTANCE_NAMES[@]}"; do
    zone="${ZONES[$i]}"
    ig="${LB_NAME_PREFIX}-ig-$((i+1))"
    ig_url_suffix="zones/${zone}/instanceGroups/${ig}"

    if echo "${existing_backends}" | grep -q "${ig_url_suffix}"; then
        echo "    backend ${ig} already attached"
        continue
    fi

    echo "    attaching ${ig}"
    gcloud compute backend-services add-backend "${LB_BACKEND_SERVICE}" \
        --project="${PROJECT_ID}" \
        --global \
        --instance-group="${ig}" \
        --instance-group-zone="${zone}" \
        --balancing-mode=UTILIZATION \
        --max-utilization=0.8 \
        --capacity-scaler=1.0
done

#
# 5. URL map → SSL cert → target HTTPS proxy
#
echo ""
echo ">>> Step 5: url-map ${LB_URL_MAP}"
if gcloud compute url-maps describe "${LB_URL_MAP}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping"
else
    gcloud compute url-maps create "${LB_URL_MAP}" \
        --project="${PROJECT_ID}" \
        --global \
        --default-service="${LB_BACKEND_SERVICE}"
fi

echo ""
echo ">>> Step 6: managed SSL cert ${LB_SSL_CERT} for ${LB_HOSTNAME}"
if gcloud compute ssl-certificates describe "${LB_SSL_CERT}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping"
else
    gcloud compute ssl-certificates create "${LB_SSL_CERT}" \
        --project="${PROJECT_ID}" \
        --global \
        --domains="${LB_HOSTNAME}"
fi

echo ""
echo ">>> Step 7: target HTTPS proxy ${LB_HTTPS_PROXY}"
if gcloud compute target-https-proxies describe "${LB_HTTPS_PROXY}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping"
else
    gcloud compute target-https-proxies create "${LB_HTTPS_PROXY}" \
        --project="${PROJECT_ID}" \
        --global \
        --url-map="${LB_URL_MAP}" \
        --ssl-certificates="${LB_SSL_CERT}"
fi

#
# 6. Static global anycast IP + forwarding rule
#
echo ""
echo ">>> Step 8: global static IP ${LB_GLOBAL_IP_NAME}"
if gcloud compute addresses describe "${LB_GLOBAL_IP_NAME}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping create"
else
    gcloud compute addresses create "${LB_GLOBAL_IP_NAME}" \
        --project="${PROJECT_ID}" \
        --global
fi

LB_IP=$(gcloud compute addresses describe "${LB_GLOBAL_IP_NAME}" \
    --project="${PROJECT_ID}" --global \
    --format="value(address)")

if [ -z "${LB_IP}" ]; then
    echo "ERROR: failed to read LB IP after create" >&2
    exit 1
fi

echo ""
echo ">>> Step 9: forwarding rule ${LB_FORWARDING_RULE} → ${LB_IP}:443"
if gcloud compute forwarding-rules describe "${LB_FORWARDING_RULE}" \
        --project="${PROJECT_ID}" --global --quiet >/dev/null 2>&1; then
    echo "    exists — skipping"
else
    gcloud compute forwarding-rules create "${LB_FORWARDING_RULE}" \
        --project="${PROJECT_ID}" \
        --global \
        --address="${LB_IP}" \
        --target-https-proxy="${LB_HTTPS_PROXY}" \
        --ports=443 \
        --load-balancing-scheme=EXTERNAL_MANAGED
fi

echo ""
echo "=========================================="
echo "Load balancer provisioned."
echo "=========================================="
echo ""
echo "  Set DNS A record:  ${LB_HOSTNAME}  →  ${LB_IP}"
echo ""
echo "Once DNS resolves, the Google-managed cert auto-provisions (5–60 min)."
echo "Monitor with:"
echo ""
echo "  gcloud compute ssl-certificates describe ${LB_SSL_CERT} \\"
echo "      --global --format='value(managed.status,managed.domainStatus)'"
echo ""
echo "Backend health:"
echo ""
echo "  gcloud compute backend-services get-health ${LB_BACKEND_SERVICE} --global"
echo ""
