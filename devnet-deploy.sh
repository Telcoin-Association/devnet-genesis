#!/usr/bin/env bash
#
# devnet-deploy.sh — the devnet deploy runbook (launch 2 topology: worker gateways, committee
# firewall, public RPC node) as a guided, resumable script. It SEQUENCES the provisioning
# sub-scripts (and pauses for the one manual step, DNS) so a fresh devnet is stood up end to
# end in the right order. The benchmark harness does not call it.
#
# It triggers MUTATING fleet/GCP operations through its sub-scripts, so it requires explicit
# confirmation: pass --yes, or type DEPLOY at the interactive prompt. Nothing runs until then.
#
# Steps (each is a named function; the runner executes them in order under set -e):
#    1. static IPs              ./common/reserve-static-ips.sh
#    2. VMs                     ./common/create-instances.sh
#    3. boot wait               serial-console completion marker on EVERY VM (gateway VM too)
#    4. DNS pause               prints the A records of the topology (and what to delete), waits
#                               for ENTER, then checks each record resolves to its address
#    5. keygen                  ./devnet-keygen.sh
#    6. genesis + manifest      ./devnet-genesis-build.sh ; ./devnet-release-sign.sh prepare
#    7. admission maps          ./devnet-network-config.sh --yes
#    8. VPC rules               ./setup-firewall.sh --yes
#    9. obs VM                  ./common/create-obs-instance.sh --wipe-data
#   10. finalize, stage only    ./devnet-finalize.sh --stage-only   (the signature gate fires here)
#   11. host ufw                ./devnet-firewall.sh --enable
#   12. observability, staged   ./devnet-observability.sh --staged
#   13. gateway installs        ./devnet-gateway.sh --yes
#   14. coordinated start       ./devnet-finalize.sh --start-all
#   15. rpc-6 public edge       ./devnet-gateway.sh --rpc-edge --yes
#   16. post-checks             ./devnet-postcheck.sh   (read-only; a failure stops the run)
#   17. dashboards              ./devnet-dashboards.sh   (opt out: TN_ADMIN_DASHBOARD=0)
#   18. contracts               ./devnet-contracts.sh --yes
#   19. txgen                   ./devnet-txgen.sh --yes
#   20. committee firewall      ./devnet-p2p-committee.sh --yes   (validators only, its default)
#
# --yes is passed to every sub-script that is a dry run without it: this runbook's own gate
# (--yes, or DEPLOY typed at the prompt) is the confirmation for them.
#
# Usage:
#   ./devnet-deploy.sh --yes                     # steps 1..20
#   ./devnet-deploy.sh --yes --from N [--to M]   # steps N..M (M defaults to 20)
#   ./devnet-deploy.sh --yes --only N            # step N alone (--to is refused with --only)
# Segments the launch runbook uses:
#   --to 3                VMs up and booted
#   (step 4, the DNS pause, needs a terminal: --only 4 prints the records and checks them)
#   --from 5 --to 10      keys, genesis, maps, VPC rules, obs VM, staging; stops at step 10
#                         with exit 3 until the release manifest is signed
#   --from 10 --to 19     staging (again, now signed) through the transaction generator
#   --only 20             committee firewall, once the chain runs
#
# Pre-gates (before the prompt, --yes or not; any failure exits 1 before step 1 runs):
#   1. tn_fleet_check (the fleet arrays of config.sh are consistent)
#   2. no PLACEHOLDER marker in config.sh outside a full-line comment, nor in the effective
#      DOCKER_IMAGE, GATEWAY_IMAGE or TN_NODE_SCRIPTS_REF
#   3. TN_NODE_SCRIPTS_REF is a full lowercase 40-hex commit sha
#   4. DOCKER_IMAGE and GATEWAY_IMAGE are <repo>@sha256:<64 hex>
#   5. run includes step 17 and TN_ADMIN_DASHBOARD=1: ./devnet-dashboards.sh --preflight
#      (the UI password secret exists; needs gcloud, so only then)
#   6. run includes step 18 / 19: the tn-contracts checkout exists (TN_CONTRACTS_DIR /
#      TXGEN_CONTRACTS_DIR, default ../tn-contracts-devnet-relaunch)
#
# Release signing (config.sh RELEASE_TAG; empty turns it off): step 6 ends with
# devnet-release-sign.sh prepare (releases/<tag>/{IMAGE_DIGEST,SHA256SUMS}). Step 10's
# devnet-finalize.sh --stage-only exits 3 (RELEASE_SIG_PENDING) before anything is staged
# until releases/<tag>/SHA256SUMS.asc exists: sign SHA256SUMS on the signing machine, place
# SHA256SUMS.asc beside it, and resume with --from 10.
#
# Step 9 wipes the observability VM's data: a run resumed with --from at or below 9 wipes it
# again (a warning line is printed before the prompt and before step 9).
#
# DNS check (step 4): after ENTER each record is looked up locally with `dig +short A` (macOS
# ships dig; Debian/Ubuntu: dnsutils). dig asks DNS itself (no /etc/hosts), as the certificate
# authority at step 13 will. A record must resolve to exactly its address;
# DEPLOY_DNS_CHECK_TRIES (6) tries, DEPLOY_DNS_CHECK_SLEEP (10 s) apart.
# DEPLOY_SKIP_DNS_CHECK=1 skips the check.
#
# Exit codes: the failing step's own code (set -e); 3 = release signature pending (step 10);
# 1 = argument error, a pre-gate, or an abort at a prompt. Between steps it prints
# `## step N done (<s> s)`; on a failure and at the end it prints how to resume (--from N).
#
# Log: every run tees its combined output (stdout and stderr, terminal unchanged) to
# logs/<UTC stamp>-deploy/deploy.log and prints that path first. No secret passes through
# this script's output: the sub-scripts read secrets from Secret Manager or stdin and never
# print them. Its only direct contact with the fleet is the GCP API (step 3's serial-console
# read, step 4's address lookups); every node operation happens inside the sub-scripts.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=devnet-lib.sh
source "${REPO_DIR}/devnet-lib.sh"

LAST_STEP=20
BOOTSTRAP_TIMEOUT_SECS=600   # per-VM first-boot wait (apt docker-ce + fetch scripts at tn-scripts-ref)
BOOTSTRAP_POLL_SECS=15
DNS_TTL=60
DNS_CHECK_TRIES="${DEPLOY_DNS_CHECK_TRIES:-6}"
DNS_CHECK_SLEEP="${DEPLOY_DNS_CHECK_SLEEP:-10}"
# The default tn-contracts checkout of devnet-contracts.sh (TN_CONTRACTS_DIR) and
# devnet-txgen.sh (TXGEN_CONTRACTS_DIR). Keep in sync with those two scripts.
CONTRACTS_DIR_DEFAULT="$(cd "${REPO_DIR}/.." && pwd)/tn-contracts-devnet-relaunch"

# --- args ----------------------------------------------------------------------
CONFIRM=0
FROM=1
FROM_SET=0
TO=""
ONLY=""
usage_error() { echo "❌ $1" >&2; exit 1; }
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --from) FROM="${2:?--from needs a step number}"; FROM_SET=1; shift ;;
        --from=*) FROM="${1#*=}"; FROM_SET=1 ;;
        --to) TO="${2:?--to needs a step number}"; shift ;;
        --to=*) TO="${1#*=}" ;;
        --only) ONLY="${2:?--only needs a step number}"; shift ;;
        --only=*) ONLY="${1#*=}" ;;
        *) usage_error "unknown argument '$1' (supported: --yes, --from <n>, --to <n>, --only <n>)" ;;
    esac
    shift
done

is_step() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le "${LAST_STEP}" ]; }
is_step "${FROM}" || usage_error "--from must be 1..${LAST_STEP}"
if [ -n "${TO}" ]; then
    is_step "${TO}" || usage_error "--to must be 1..${LAST_STEP}"
fi
if [ -n "${ONLY}" ]; then
    is_step "${ONLY}" || usage_error "--only must be 1..${LAST_STEP}"
    [ -z "${TO}" ] || usage_error "--to cannot be combined with --only (use --from N --to M for a range)"
    RUN_FROM="${ONLY}"; RUN_TO="${ONLY}"
else
    RUN_FROM="${FROM}"; RUN_TO="${TO:-${LAST_STEP}}"
    [ "${RUN_FROM}" -le "${RUN_TO}" ] || usage_error "--from ${RUN_FROM} is after --to ${RUN_TO}"
fi
in_range() { [ "$1" -ge "${RUN_FROM}" ] && [ "$1" -le "${RUN_TO}" ]; }

# The command line that resumes this run at step $1.
resume_cmd() {
    if [ -n "${ONLY}" ]; then
        printf './devnet-deploy.sh --yes --only %s\n' "$1"
    elif [ -n "${TO}" ]; then
        printf './devnet-deploy.sh --yes --from %s --to %s\n' "$1" "${RUN_TO}"
    else
        printf './devnet-deploy.sh --yes --from %s\n' "$1"
    fi
}

warn_obs_wipe() {
    if [ -z "${ONLY}" ] && [ "${FROM_SET}" -eq 1 ] && in_range 9; then
        echo "⚠️  --from ${RUN_FROM} includes step 9: common/create-obs-instance.sh --wipe-data wipes the observability VM's data again (use --from 10 to keep it)."
    fi
}

# --- run log -------------------------------------------------------------------
# stdout and stderr each pass through their own tee into one file, so the terminal shows
# exactly what it did before (stderr stays stderr) and the log holds both.
LOG_DIR="${REPO_DIR}/logs/$(date -u +%Y%m%d_%H%M%S)-deploy"
LOG_FILE="${LOG_DIR}/deploy.log"
mkdir -p "${LOG_DIR}"
exec > >(tee -a "${LOG_FILE}") 2> >(tee -a "${LOG_FILE}" >&2)
echo "log: ${LOG_FILE}"

CURRENT_STEP=""
on_exit() {
    local rc=$?
    if [ -n "${CURRENT_STEP}" ] && [ "${rc}" -ne 0 ]; then
        echo "" >&2
        echo "❌ step ${CURRENT_STEP} failed (exit ${rc}). Fix the cause, then resume with:" >&2
        echo "     $(resume_cmd "${CURRENT_STEP}")" >&2
        echo "   log: ${LOG_FILE}" >&2
    fi
}
trap on_exit EXIT

# --- per-step implementations --------------------------------------------------
step_1()  { echo ">>> Step 1: static IPs"; "${REPO_DIR}/common/reserve-static-ips.sh"; }
step_2()  { echo ">>> Step 2: VMs";        "${REPO_DIR}/common/create-instances.sh"; }

step_3()  {
    echo ">>> Step 3: boot wait (serial-console completion marker on every VM)"
    # Readiness is read from each VM's SERIAL CONSOLE via the GCP API (get-serial-port-output),
    # not probed over IAP SSH, so this step needs no SSH path. Every VM, the gateway VM
    # included, boots with the same startup script and prints the same marker: docker
    # installed and the node scripts fetched at `tn-scripts-ref` into /opt/telcoin-node-scripts.
    # The marker is emitted at first boot, so run this right after step 2 while it is still in
    # the (rolling) console buffer.
    local marker="devnet-startup.sh complete"
    local i inst zone waited ready out
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        echo "    polling ${inst} (${zone})..."
        waited=0; ready=0
        while [ "${waited}" -lt "${BOOTSTRAP_TIMEOUT_SECS}" ]; do
            # Capture-then-match (not `… | grep -q`): grep -q exits on the first hit and would
            # SIGPIPE the large serial stream, which pipefail turns into a false negative.
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
    echo "    all VMs READY (completion marker present on all ${#INSTANCE_NAMES[@]})"
}

# Step 4's record set, filled by dns_records: DNS_NAMES[k] must resolve to DNS_IPS[k], the
# static address of the host DNS_HOSTS[k] that serves the name. DNS_DELETE: stale names.
DNS_NAMES=(); DNS_HOSTS=(); DNS_IPS=(); DNS_DELETE=(); HOST_IPS=()
dns_add() { DNS_NAMES+=("$1"); DNS_HOSTS+=("$2"); }
dns_records() {
    local i h d k
    # Public names: a node behind a gateway is served by its gateway's host (node4 -> the
    # gateway VM); a node without one (the rpc node: RPC_HOSTNAME) by its own host.
    for i in $(tn_node_indices); do
        d="$(tn_public_domain "${i}")" || return 1
        h="$(tn_gateway_host_index "${i}")" || h="${i}"
        dns_add "${d}" "${h}"
    done
    # Admin names: on each node host that runs Caddy. A node without one had an admin record
    # in the previous topology, which nothing serves now.
    for i in $(tn_node_indices); do
        if d="$(tn_admin_domain "${i}")"; then
            dns_add "${d}" "${i}"
        else
            DNS_DELETE+=("admin.${NODE_NAMES[$i]}.${BASE_DOMAIN}")
        fi
    done
    for k in "${!DNS_NAMES[@]}"; do
        h="${DNS_HOSTS[$k]}"
        if [ -z "${HOST_IPS[$h]:-}" ]; then
            HOST_IPS[h]="$(tn_external_ip "${h}")" || return 1
            [ -n "${HOST_IPS[$h]}" ] || { echo "❌ ${INSTANCE_NAMES[$h]} has no external address (steps 1-2 done?)" >&2; return 1; }
        fi
        DNS_IPS[k]="${HOST_IPS[$h]}"
    done
}

# dns_lookup <name> — its IPv4 A addresses, sorted, space-separated (empty when none).
dns_lookup() {
    local out
    out="$(dig +short +time=3 +tries=1 A "$1" 2>/dev/null | grep -E '^[0-9]+(\.[0-9]+){3}$' | sort -u || true)"
    printf '%s' "${out}" | tr '\n' ' ' | sed 's/ *$//'
}

dns_verify() {
    local try=1 k got bad
    if ! command -v dig >/dev/null 2>&1; then
        echo "❌ dig is not installed (Debian/Ubuntu: dnsutils): install it, or re-run with DEPLOY_SKIP_DNS_CHECK=1." >&2
        return 1
    fi
    echo "    checking ${#DNS_NAMES[@]} records with dig (${DNS_CHECK_TRIES} tries, ${DNS_CHECK_SLEEP}s apart)"
    while :; do
        bad=()
        for k in "${!DNS_NAMES[@]}"; do
            got="$(dns_lookup "${DNS_NAMES[$k]}")"
            [ "${got}" = "${DNS_IPS[$k]}" ] || bad+=("${DNS_NAMES[$k]}: expected ${DNS_IPS[$k]}, resolves to ${got:-nothing}")
        done
        if [ "${#bad[@]}" -eq 0 ]; then
            echo "    ✓ every record resolves to its address"
            return 0
        fi
        [ "${try}" -lt "${DNS_CHECK_TRIES}" ] || break
        echo "    ${#bad[@]} record(s) not right yet (try ${try}/${DNS_CHECK_TRIES}); retrying in ${DNS_CHECK_SLEEP}s"
        sleep "${DNS_CHECK_SLEEP}"
        try=$((try + 1))
    done
    echo "❌ wrong DNS records (step 13's certificate issuance would fail on these):" >&2
    printf '     %s\n' "${bad[@]}" >&2
    echo "   A stale answer cached from an old TTL clears with time; or skip with DEPLOY_SKIP_DNS_CHECK=1." >&2
    return 1
}

step_4()  {
    echo ">>> Step 4: DNS pause (create the records of this topology, then press ENTER)"
    dns_records
    local k
    echo ""
    echo "  Create or change these A records (TTL ${DNS_TTL}), each to the static address of the host serving it:"
    for k in "${!DNS_NAMES[@]}"; do
        printf '    %-34s A  %-15s  TTL %s  (%s)\n' "${DNS_NAMES[$k]}" "${DNS_IPS[$k]}" "${DNS_TTL}" "${INSTANCE_NAMES[${DNS_HOSTS[$k]}]}"
    done
    if [ "${#DNS_DELETE[@]}" -gt 0 ]; then
        echo "  Delete these records (no host serves them in this topology):"
        for k in "${!DNS_DELETE[@]}"; do
            printf '    %-34s (that node has no admin domain now)\n' "${DNS_DELETE[$k]}"
        done
    fi
    echo ""
    pause_for_operator
    if [ "${DEPLOY_SKIP_DNS_CHECK:-0}" = "1" ]; then
        echo "    DNS check skipped (DEPLOY_SKIP_DNS_CHECK=1)"
        return 0
    fi
    dns_verify
}

step_5()  { echo ">>> Step 5: keygen"; "${REPO_DIR}/devnet-keygen.sh"; }
step_6()  {
    echo ">>> Step 6: genesis + manifest"
    "${REPO_DIR}/devnet-genesis-build.sh"
    # Release manifest over the configs just built (config.sh RELEASE_TAG; empty = off).
    # Step 10's finalize refuses to stage anything until SHA256SUMS.asc signs this manifest.
    [ -n "${RELEASE_TAG:-}" ] || return 0
    local rc=0
    "${REPO_DIR}/devnet-release-sign.sh" prepare || rc=$?
    if [ "${rc}" -ne 0 ]; then
        echo "❌ devnet-release-sign.sh prepare failed (rc ${rc})." >&2
        if [ "${rc}" -eq 1 ]; then
            echo "   releases/${RELEASE_TAG}/SHA256SUMS.asc signs different content (keygen or genesis re-ran):" >&2
            echo "   run ./devnet-release-sign.sh prepare --force, re-sign SHA256SUMS, then resume with --from 7." >&2
        fi
        return "${rc}"
    fi
}

step_7()  {
    echo ">>> Step 7: admission maps"
    # Renders each node's admission maps (bootstrap peers, trusted nodes) and installs them
    # on the host. They must be in place before step 10 stages and step 14 starts the nodes.
    "${REPO_DIR}/devnet-network-config.sh" --yes
}

# setup-firewall.sh is a dry run without --yes.
step_8()  { echo ">>> Step 8: VPC rules"; "${REPO_DIR}/setup-firewall.sh" --yes; }
step_9()  {
    echo ">>> Step 9: obs VM"
    warn_obs_wipe
    "${REPO_DIR}/common/create-obs-instance.sh" --wipe-data
}

step_10() {
    echo ">>> Step 10: finalize, stage only"
    # The release-signature gate fires here: --stage-only exits 3 (RELEASE_SIG_PENDING)
    # before anything is staged. Sign, then resume with --from 10.
    local rc=0
    "${REPO_DIR}/devnet-finalize.sh" --stage-only || rc=$?
    if [ "${rc}" -eq 3 ]; then
        echo "❌ RELEASE_SIG_PENDING: releases/${RELEASE_TAG:-<tag>}/SHA256SUMS is not signed (nothing was staged)." >&2
        echo "   Sign SHA256SUMS on the signing machine, place SHA256SUMS.asc beside it, then resume with --from 10." >&2
    fi
    return "${rc}"
}

step_11() {
    echo ">>> Step 11: host ufw"
    # Lockout-safe enable on every host (SSH re-verified per host; aborts the run on loss).
    # No separate port-mode call follows: the host script's --enable already opens the P2P
    # ports on node hosts (and --p2p-anywhere on the rpc node). Must precede step 12, whose
    # health port needs ufw active.
    "${REPO_DIR}/devnet-firewall.sh" --enable
}

step_12() {
    echo ">>> Step 12: observability, staged"
    # On stopped nodes: flags and agent installed, no node restart, no quorum sweep.
    "${REPO_DIR}/devnet-observability.sh" --staged
}

step_13() { echo ">>> Step 13: gateway installs"; "${REPO_DIR}/devnet-gateway.sh" --yes; }

step_14() {
    echo ">>> Step 14: coordinated start"
    "${REPO_DIR}/devnet-finalize.sh" --start-all
    echo "    note: node 5 connects to the RPC node about 45 s after both are up, and an idle chain shows no new block before the first epoch close."
}

# Restarts the rpc node once to put its public edge in front of it (after the start).
step_15() { echo ">>> Step 15: rpc-6 public edge"; "${REPO_DIR}/devnet-gateway.sh" --rpc-edge --yes; }

step_16() {
    # Step 15 restarted rpc-6, node 5's only peer, so the checks that need peers re-read for up to POSTCHECK_SETTLE_SECS (180).
    echo ">>> Step 16: post-checks"
    local rc=0
    "${REPO_DIR}/devnet-postcheck.sh" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        echo "❌ post-checks failed (rc ${rc}): the run stops here and the fleet stays up." >&2
        echo "   The checks are read-only: fix the cause, then re-run them with --only 16." >&2
    fi
    return "${rc}"
}

step_17() {
    echo ">>> Step 17: dashboards"
    # Default ON (config.sh TN_ADMIN_DASHBOARD=1); opt out only with TN_ADMIN_DASHBOARD=0.
    if [ "${TN_ADMIN_DASHBOARD:-1}" != "1" ]; then
        echo "    TN_ADMIN_DASHBOARD=0 (explicitly opted out) — skipping."
        return 0
    fi
    "${REPO_DIR}/devnet-dashboards.sh"
}

# 18 and 19: the chain wipe took every script-deployed contract with it; the generator
# reads them from the deployments book and fails on a missing key, so 18 precedes 19.
step_18() { echo ">>> Step 18: contracts";          "${REPO_DIR}/devnet-contracts.sh" --yes; }
step_19() { echo ">>> Step 19: txgen";              "${REPO_DIR}/devnet-txgen.sh" --yes; }
step_20() { echo ">>> Step 20: committee firewall"; "${REPO_DIR}/devnet-p2p-committee.sh" --yes; }

# pause_for_operator — block until ENTER. Without a TTY on stdin (piped, unattended) it
# fails loud instead of hanging.
pause_for_operator() {
    if [ ! -t 0 ]; then
        echo "❌ this is a MANUAL step but stdin is not a TTY — run it interactively, or use --from to resume past it after doing it by hand." >&2
        exit 1
    fi
    read -r -p "    Press ENTER when this manual step is complete (Ctrl-C to abort)... " _
}

# --- banner and pre-gates -------------------------------------------------------
gate_fail() { echo "❌ $1" >&2; exit 1; }
echo "=========================================="
echo "devnet deploy runbook"
echo "Project:  ${PROJECT_ID}"
echo "Domain:   ${BASE_DOMAIN}"
if [ -n "${ONLY}" ]; then
    echo "Scope:    ONLY step ${ONLY}"
else
    echo "Scope:    steps ${RUN_FROM}..${RUN_TO}"
fi
echo "This triggers MUTATING GCP/fleet operations via sub-scripts."
warn_obs_wipe
echo "=========================================="

# 1. Fleet arrays consistent (lengths, roles, gateway pairing); details on stderr.
tn_fleet_check || gate_fail "the fleet arrays in config.sh are inconsistent (see above)."

# 2. No PLACEHOLDER marker: in the config file (full-line comments skipped: they never reach
# the sourced config), nor in the three effective values that leave this machine, which an
# override from the environment or another config file could still hold.
config_file="${CONFIG_FILE:-${REPO_DIR}/config.sh}"
if placeholder_hits="$(grep -n 'PLACEHOLDER_' "${config_file}" | grep -v -E '^[0-9]+:[[:space:]]*#')"; then
    echo "❌ ${config_file} still contains PLACEHOLDER_ values. Fill them in, then re-run:" >&2
    printf '%s\n' "${placeholder_hits}" | sed 's/^/    /' >&2
    exit 1
fi
for v in DOCKER_IMAGE GATEWAY_IMAGE TN_NODE_SCRIPTS_REF; do
    case "${!v:-}" in
        *PLACEHOLDER_*) gate_fail "${v} still holds a PLACEHOLDER_ value ('${!v}')." ;;
    esac
done

# 3. TN_NODE_SCRIPTS_REF goes into every VM's instance metadata (`,tn-scripts-ref=<ref>`) and
# a root git command on the host: a full lowercase 40-hex sha only (a branch name could carry
# `,` or `=` into the metadata; the host refuses a short sha at first boot).
case "${TN_NODE_SCRIPTS_REF:-}" in
    *[!0-9a-f]*|'') gate_fail "TN_NODE_SCRIPTS_REF must be a full lowercase 40-hex commit sha (got '${TN_NODE_SCRIPTS_REF:-}')." ;;
esac
[ "${#TN_NODE_SCRIPTS_REF}" -eq 40 ] || gate_fail "TN_NODE_SCRIPTS_REF must be exactly 40 hex characters (got ${#TN_NODE_SCRIPTS_REF})."

# 4. Both images pinned by digest.
digest_re='^[^@[:space:]]+@sha256:[0-9a-f]{64}$'
for v in DOCKER_IMAGE GATEWAY_IMAGE; do
    [[ "${!v:-}" =~ ${digest_re} ]] || gate_fail "${v} must be <repo>@sha256:<64 hex> (got '${!v:-}')."
done

# 5. Step 17's UI password secret, checked now rather than 16 steps later (needs gcloud).
if in_range 17 && [ "${TN_ADMIN_DASHBOARD:-1}" = "1" ]; then
    "${REPO_DIR}/devnet-dashboards.sh" --preflight \
        || gate_fail "devnet-dashboards.sh --preflight failed: create the UI password secret (TN_ADMIN_PASSWORD_SECRET), or set TN_ADMIN_DASHBOARD=0."
fi

# 6. Steps 18 and 19 need the tn-contracts checkout.
if in_range 18; then
    d="${TN_CONTRACTS_DIR:-${CONTRACTS_DIR_DEFAULT}}"
    [ -d "${d}" ] || gate_fail "step 18 needs the tn-contracts checkout: ${d} does not exist (set TN_CONTRACTS_DIR)."
fi
if in_range 19; then
    d="${TXGEN_CONTRACTS_DIR:-${CONTRACTS_DIR_DEFAULT}}"
    [ -d "${d}" ] || gate_fail "step 19 needs the tn-contracts checkout: ${d} does not exist (set TXGEN_CONTRACTS_DIR)."
fi

if [ "${CONFIRM}" -ne 1 ]; then
    if [ ! -t 0 ]; then
        gate_fail "refusing to run unattended without --yes. Re-run with --yes."
    fi
    read -r -p "Type DEPLOY to continue: " ans
    [ "${ans}" = "DEPLOY" ] || { echo "Aborted."; exit 1; }
fi

# --- runner --------------------------------------------------------------------
run_step() {
    local n="$1" t0="${SECONDS}"
    CURRENT_STEP="${n}"
    echo ""
    echo "##########################################"
    "step_${n}"
    echo "## step ${n} done ($((SECONDS - t0)) s)"
    echo "##########################################"
    CURRENT_STEP=""
}

n="${RUN_FROM}"
while [ "${n}" -le "${RUN_TO}" ]; do
    run_step "${n}"
    n=$((n + 1))
done

echo ""
echo "=========================================="
if [ -n "${ONLY}" ]; then
    echo "Step ${ONLY} complete."
else
    echo "Steps ${RUN_FROM}..${RUN_TO} complete."
fi
if [ "${RUN_TO}" -lt "${LAST_STEP}" ]; then
    echo "Resume with: ./devnet-deploy.sh --yes --from $((RUN_TO + 1))"
else
    echo "All ${LAST_STEP} steps done; nothing left to resume."
fi
echo "Log: ${LOG_FILE}"
echo "=========================================="
