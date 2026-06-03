#!/bin/bash
#
# Repairs SSL/Apache on every validator after the first-boot certbot failure.
#
# Failure mode:
#   - first-boot certbot ran before DNS A records existed → no cert acquired
#   - config-apache.sh still a2ensite'd 000-default-le-ssl, which is a stub
#     with `SSLEngine on` and no SSLCertificateFile directives
#   - apache now refuses to start
#   - subsequent certbot runs fail because http-01 needs apache up on :80
#
# Per node, in parallel:
#   Phase 1: capture diagnostics (apache status, error log, certs, sites)
#   Phase 2: reset apache to HTTP-only baseline:
#              - a2dissite 000-default-le-ssl
#              - rm /etc/apache2/sites-available/000-default-le-ssl.conf
#              - a2ensite 000-default
#              - systemctl restart apache2  (must come up; abort node if not)
#   Phase 3: scp + run the canonical config-apache.sh, which now succeeds
#            because apache is up for the http-01 challenge
#   Phase 4: verify — apache active + certbot certificates listing
#
# config-apache.sh is unchanged and remains idempotent.
#

set -u

source ./config.sh

if [ ! -f "${CONFIG_APACHE_SCRIPT}" ]; then
    echo "Error: ${CONFIG_APACHE_SCRIPT} not found" >&2
    exit 1
fi

timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="./logs/dns/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

REMOTE_CONFIG_APACHE="/tmp/config-apache.sh"

# Single-quoted: neither this shell nor gcloud expand anything; the remote
# bash sees the literal text. Don't introduce $vars or `cmds` here.
RESET_SCRIPT='set +e

echo "--- apache status (before) ---"
sudo systemctl status apache2 --no-pager 2>&1 | head -20

echo ""
echo "--- apache error log (last 30 lines) ---"
sudo tail -30 /var/log/apache2/error.log 2>&1 || echo "(no error log)"

echo ""
echo "--- existing letsencrypt certs ---"
sudo ls -la /etc/letsencrypt/live/ 2>&1 || echo "(no /etc/letsencrypt/live)"

echo ""
echo "--- enabled apache sites ---"
sudo ls -la /etc/apache2/sites-enabled/ 2>&1

echo ""
echo "--- disabling broken SSL site + removing stub ---"
sudo a2dissite 000-default-le-ssl 2>&1 || true
sudo rm -f /etc/apache2/sites-available/000-default-le-ssl.conf
sudo a2ensite 000-default 2>&1 || true

echo ""
echo "--- restarting apache (HTTP-only) ---"
sudo systemctl restart apache2
if sudo systemctl is-active --quiet apache2; then
    echo "apache: active on :80 — ready for certbot http-01"
    exit 0
fi

echo "FATAL: apache still will not start after reset"
sudo journalctl -xeu apache2.service --no-pager 2>&1 | tail -60
exit 1'

VERIFY_SCRIPT='echo "--- apache status (after) ---"
sudo systemctl is-active apache2 && echo "apache: active" || echo "apache: NOT active"

echo ""
echo "--- listening ports (80, 443) ---"
sudo ss -tlnp 2>&1 | grep -E ":(80|443) " || echo "(no listeners on 80/443)"

echo ""
echo "--- certbot certificates ---"
sudo certbot certificates 2>&1 | head -60'

run_node() {
    local instance="$1"
    local zone="$2"
    local log="$3"

    {
        echo "=========================================================================="
        echo "= $(date) :: ${instance} (${zone})"
        echo "=========================================================================="

        echo ""
        echo ">>> Phase 1+2: diagnostics + reset apache to HTTP-only baseline"
        gcloud compute ssh "${instance}" --zone="${zone}" \
            --command="${RESET_SCRIPT}" 2>&1
        local rc=$?
        if [ ${rc} -ne 0 ]; then
            echo ""
            echo "=== RESET FAILED on ${instance} (rc=${rc}) — aborting node ==="
            return ${rc}
        fi

        echo ""
        echo ">>> Phase 3a: scp ${CONFIG_APACHE_SCRIPT} → ${instance}:${REMOTE_CONFIG_APACHE}"
        gcloud compute scp "${CONFIG_APACHE_SCRIPT}" \
            "${instance}:${REMOTE_CONFIG_APACHE}" \
            --zone="${zone}" 2>&1
        rc=$?
        if [ ${rc} -ne 0 ]; then
            echo ""
            echo "=== SCP FAILED on ${instance} (rc=${rc}) — aborting node ==="
            return ${rc}
        fi

        echo ""
        echo ">>> Phase 3b: run config-apache.sh"
        gcloud compute ssh "${instance}" --zone="${zone}" \
            --command="sudo bash ${REMOTE_CONFIG_APACHE}" 2>&1
        local config_rc=$?

        echo ""
        echo ">>> Phase 4: verify"
        gcloud compute ssh "${instance}" --zone="${zone}" \
            --command="${VERIFY_SCRIPT}" 2>&1
        local verify_rc=$?

        echo ""
        if [ ${config_rc} -eq 0 ] && [ ${verify_rc} -eq 0 ]; then
            echo "=== ${instance} OK at $(date) ==="
            return 0
        fi
        echo "=== ${instance} FAILED at $(date) (config_rc=${config_rc}, verify_rc=${verify_rc}) ==="
        return 1
    } >> "${log}" 2>&1
}

pids=()
logs=()
for i in "${!INSTANCE_NAMES[@]}"; do
    instance="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    log="${OUTPUT_PATH}/${instance}.log"
    logs+=("${log}")

    echo "Starting on ${instance} (${zone}) → ${log}"
    run_node "${instance}" "${zone}" "${log}" &
    pids+=($!)
done

echo ""
echo "All ${#pids[@]} jobs launched. Waiting..."
echo ""

failed=()
for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
        echo "✅ ${INSTANCE_NAMES[$i]}"
    else
        echo "❌ ${INSTANCE_NAMES[$i]} — see ${logs[$i]}"
        echo "   Last 25 lines:"
        tail -25 "${logs[$i]}" | sed 's/^/   /'
        failed+=("${INSTANCE_NAMES[$i]}")
    fi
done

echo ""
echo "========================================="
echo "DNS / SSL reconfig summary"
echo "========================================="
echo "Total:      ${#INSTANCE_NAMES[@]}"
echo "Successful: $((${#INSTANCE_NAMES[@]} - ${#failed[@]}))"
echo "Failed:     ${#failed[@]}"
if [ ${#failed[@]} -gt 0 ]; then
    echo ""
    echo "Failed instances:"
    for f in "${failed[@]}"; do
        echo "  - ${f}"
    done
fi
echo ""
echo "Logs: ${OUTPUT_PATH}"
echo "========================================="

if [ ${#failed[@]} -gt 0 ]; then
    exit 1
fi

echo ""
echo "🎉 SSL/Apache reconfigured on all instances."
