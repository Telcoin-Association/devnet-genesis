#!/usr/bin/env bash
#
# devnet-deploy.sh — the one-time Ubuntu-migration runbook, expressed as a guided,
# resumable script. It SEQUENCES the real provisioning sub-scripts (and pauses for
# the handful of operator-manual steps) so a fresh devnet can be stood up end to
# end in the right order.
#
# This triggers MUTATING fleet/GCP operations through its sub-scripts, so it
# requires explicit confirmation: pass --yes, or type DEPLOY at the interactive
# prompt. Nothing runs until you confirm.
#
# Steps (each is a named function; the runner executes them in order under set -e):
#    1. reserve static IPs            ./common/reserve-static-ips.sh
#    2. create instances              ./common/create-instances.sh
#    3. wait for first-boot bootstrap on EVERY node (serial-console completion marker)
#    4. MANUAL: create DNS A-records node{N}.${BASE_DOMAIN} -> each static IP   [pause]
#    5. keygen                        ./devnet-keygen.sh
#    6. build genesis                 ./devnet-genesis-build.sh
#    7. finalize (stage + start)      ./devnet-finalize.sh
#    8. obs VM                        ./common/create-obs-instance.sh --wipe-data
#    9. per-node observability        ./devnet-observability.sh
#   10. host firewall (UFW)          ./devnet-firewall.sh --enable ; ./devnet-firewall.sh
#   11. GCP/VPC firewall rules        ./setup-firewall.sh
#   12. DNS/Caddy + load balancer     ./common/dns.sh ; ./common/setup-load-balancer.sh
#   13. admin dashboards (default ON)  ./devnet-dashboards.sh ; ./common/dns.sh   (opt out: TN_ADMIN_DASHBOARD=0)
#   14. app-contract stack           ./devnet-contracts.sh    (tn-contracts: infra + LPs + faucet role)
#   15. transaction generator        ./devnet-txgen.sh        (txgen-devnet VM + permanent systemd service)
#
# Resume / piecemeal:
#   ./devnet-deploy.sh --yes              # full run, steps 1..15 (step 13 skips only if TN_ADMIN_DASHBOARD=0)
#   ./devnet-deploy.sh --yes --from 5     # resume at step 5 to the end
#   ./devnet-deploy.sh --yes --only 9     # run ONLY step 9
#
# This script authors the sequence; it reaches nodes only via the lib's IAP
# helpers (step 3's readiness poll). It does NOT run anything until confirmed.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

LAST_STEP=15
BOOTSTRAP_TIMEOUT_SECS=600   # per-node first-boot wait (apt docker-ce + clone scripts)
BOOTSTRAP_POLL_SECS=15

# --- args ----------------------------------------------------------------------
CONFIRM=0
FROM=1
ONLY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --from) FROM="${2:?--from needs a step number}"; shift ;;
        --from=*) FROM="${1#*=}" ;;
        --only) ONLY="${2:?--only needs a step number}"; shift ;;
        --only=*) ONLY="${1#*=}" ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --from <n>, --only <n>)" >&2; exit 1 ;;
    esac
    shift
done

# Validate numeric ranges.
is_step() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le "${LAST_STEP}" ]; }
is_step "${FROM}" || { echo "❌ --from must be 1..${LAST_STEP}" >&2; exit 1; }
if [ -n "${ONLY}" ]; then
    is_step "${ONLY}" || { echo "❌ --only must be 1..${LAST_STEP}" >&2; exit 1; }
fi

# --- per-step implementations --------------------------------------------------
step_1()  { echo ">>> Step 1: reserve static IPs";        "${REPO_DIR}/common/reserve-static-ips.sh"; }
step_2()  { echo ">>> Step 2: create instances";          "${REPO_DIR}/common/create-instances.sh"; }

step_3()  {
    echo ">>> Step 3: wait for first-boot bootstrap on EVERY node (serial-console completion marker)"
    # Readiness is verified by reading each node's SERIAL CONSOLE via the GCP API
    # (get-serial-port-output) for devnet-startup.sh's completion marker — NOT by probing
    # over IAP SSH. The serial read travels the GCP REST API and needs no SSH/IAP path to
    # the node, so Step 3 stays reliable even when the operator's local IAP tunnel is down.
    # NOTE: this confirms the startup-script FINISHED (docker installed + node scripts
    # cloned). The later per-node steps (keygen/finalize/observability/firewall) still run
    # commands ON the node over IAP SSH and need that path working. The marker is emitted at
    # first boot, so run Step 3 right after Step 2 while it is fresh in the (rolling) buffer.
    local marker="devnet-startup.sh complete"
    local i inst zone waited ready out
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        echo "    polling ${inst} (${zone})..."
        waited=0; ready=0
        while [ "${waited}" -lt "${BOOTSTRAP_TIMEOUT_SECS}" ]; do
            # Capture-then-match (not `… | grep -q`): grep -q exits on first hit and would
            # SIGPIPE the large serial stream, which `set -o pipefail` turns into a false
            # negative. A bash glob over the captured text has no such pipe hazard.
            out="$(gcloud compute instances get-serial-port-output "${inst}" \
                     --zone="${zone}" --project="${PROJECT_ID}" 2>/dev/null || true)"
            if [[ "${out}" == *"${marker}"* ]]; then
                echo "      ✓ ${inst} READY (after ${waited}s)"
                ready=1; break
            fi
            sleep "${BOOTSTRAP_POLL_SECS}"
            waited=$((waited + BOOTSTRAP_POLL_SECS))
            echo "      …${inst} not ready yet (${waited}s/${BOOTSTRAP_TIMEOUT_SECS}s)"
        done
        if [ "${ready}" -ne 1 ]; then
            echo "❌ ${inst} did not finish first-boot bootstrap within ${BOOTSTRAP_TIMEOUT_SECS}s." >&2
            echo "   Inspect serial console: gcloud compute instances get-serial-port-output ${inst} --zone=${zone} --project=${PROJECT_ID}" >&2
            return 1
        fi
    done
    echo "    all nodes READY (serial-console completion marker present on all)"
}

step_4()  {
    cat <<EOF
>>> Step 4: MANUAL — create DNS A-records

  For each node, point node{N}.${BASE_DOMAIN} at that instance's RESERVED static IP.
  The static IPs were printed by Step 1 (common/reserve-static-ips.sh); re-list with:

    gcloud compute addresses list --project=${PROJECT_ID} \\
      --filter="name~'-devnet-ip\$'" --format='table(name, region, address)'

  Map:
EOF
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        printf '    %-8s -> static IP of %s\n' "${NODE_NAMES[$i]}.${BASE_DOMAIN}" "${INSTANCE_NAMES[$i]}"
    done
    pause_for_operator
}

step_5()  { echo ">>> Step 5: keygen";                    "${REPO_DIR}/devnet-keygen.sh"; }
step_6()  { echo ">>> Step 6: build genesis";             "${REPO_DIR}/devnet-genesis-build.sh"; }
step_7()  { echo ">>> Step 7: finalize (stage + start)";  "${REPO_DIR}/devnet-finalize.sh"; }
step_8()  { echo ">>> Step 8: obs VM (+ wipe data)";      "${REPO_DIR}/common/create-obs-instance.sh" --wipe-data; }
step_9()  { echo ">>> Step 9: per-node observability";    "${REPO_DIR}/devnet-observability.sh"; }

step_10() {
    echo ">>> Step 10: host firewall (UFW) — lockout-safe enable, then consensus rules"
    # No longer a manual step. devnet-firewall.sh --enable delegates to the node's
    # firewall-setup.sh --json --enable, which allows SSH, the 10.100.0.0/16 overlay, the
    # Kuma monitor and the Google LB health-check ranges BEFORE `ufw --force enable`, then
    # re-verifies SSH per node and ABORTS the whole run on loss (no further nodes touched).
    #
    # FALLBACK (only if --enable itself is broken): enable UFW by hand, SSH allowed FIRST,
    # once per node from an IAP/console session, then re-run this step with --only 10:
    #     sudo ufw allow 22/tcp && sudo ufw --force enable
    "${REPO_DIR}/devnet-firewall.sh" --enable   # per-node enable + SSH re-verify + abort on loss
    echo "    applying host consensus rules via devnet-firewall.sh"
    "${REPO_DIR}/devnet-firewall.sh"            # consensus ingress, asserted via --json --status
}

step_11() { echo ">>> Step 11: GCP/VPC firewall rules";   "${REPO_DIR}/setup-firewall.sh"; }
step_12() {
    echo ">>> Step 12: DNS/Caddy reverse-proxy + load balancer"
    "${REPO_DIR}/common/dns.sh"
    "${REPO_DIR}/common/setup-load-balancer.sh"
}
step_13() {
    echo ">>> Step 13: admin dashboard (Node Manager UI) — install + expose read-only"
    # Mandatory by default (config.sh TN_ADMIN_DASHBOARD=1). Opt out only with TN_ADMIN_DASHBOARD=0.
    if [ "${TN_ADMIN_DASHBOARD:-1}" != "1" ]; then
        echo "    TN_ADMIN_DASHBOARD=0 (explicitly opted out) — skipping."
        return 0
    fi
    # No secret handling here: common/dns.sh fetches the basic_auth hash from Secret Manager
    # itself (one-time setup: ./devnet-admin-secret.sh). Install the UI backend FIRST, then
    # re-apply Caddy so the admin vhost points at a service that already answers on :8080.
    "${REPO_DIR}/devnet-dashboards.sh"   # (1) install/refresh the UI fleet-wide (backend live FIRST)
    "${REPO_DIR}/common/dns.sh"          # (2) re-apply Caddy; dns.sh auto-fetches the hash + emits the vhost
}

step_14() {
    echo ">>> Step 14: app-contract stack (tn-contracts)"
    # The chain wipe takes every script-deployed contract with it (WTEL, the eXYZ
    # stablecoins, StablecoinManager, the Uniswap factories/routers/pools). Only
    # ConsensusRegistry/Issuance/StakeManager are genesis-assigned. The transaction
    # generator reads all of them from deployments-devnet.json and fails hard on a
    # missing mandatory key, so this must land before Step 15.
    "${REPO_DIR}/devnet-contracts.sh"
}
step_15() {
    echo ">>> Step 15: transaction generator (txgen-devnet)"
    # Permanent, continuous transaction source so the chain never sits idle.
    "${REPO_DIR}/devnet-txgen.sh"
}

# pause_for_operator — block until ENTER (skipped only if stdin isn't a TTY, e.g.
# piped, so an unattended run of a manual step fails loud rather than hanging).
pause_for_operator() {
    if [ ! -t 0 ]; then
        echo "❌ this is a MANUAL step but stdin is not a TTY — run it interactively, or use --from to resume past it after doing it by hand." >&2
        exit 1
    fi
    read -r -p "    Press ENTER when this manual step is complete (Ctrl-C to abort)... " _
}

# --- confirmation gate ---------------------------------------------------------
echo "=========================================="
echo "devnet ONE-TIME deploy runbook"
echo "Project:  ${PROJECT_ID}"
echo "Domain:   ${BASE_DOMAIN}"
if [ -n "${ONLY}" ]; then
    echo "Scope:    ONLY step ${ONLY}"
else
    echo "Scope:    steps ${FROM}..${LAST_STEP}"
fi
echo "This triggers MUTATING GCP/fleet operations via sub-scripts."
echo "=========================================="

if [ "${CONFIRM}" -ne 1 ]; then
    if [ ! -t 0 ]; then
        echo "❌ refusing to run unattended without --yes. Re-run with --yes." >&2
        exit 1
    fi
    read -r -p "Type DEPLOY to continue: " ans
    [ "${ans}" = "DEPLOY" ] || { echo "Aborted."; exit 1; }
fi

# --- runner --------------------------------------------------------------------
run_step() {
    local n="$1"
    echo ""
    echo "##########################################"
    "step_${n}"
    echo "## step ${n} done"
    echo "##########################################"
}

if [ -n "${ONLY}" ]; then
    run_step "${ONLY}"
else
    n="${FROM}"
    while [ "${n}" -le "${LAST_STEP}" ]; do
        run_step "${n}"
        n=$((n + 1))
    done
fi

echo ""
echo "=========================================="
if [ -n "${ONLY}" ]; then
    echo "Step ${ONLY} complete."
else
    echo "Deploy runbook complete (steps ${FROM}..${LAST_STEP})."
fi
echo "=========================================="
