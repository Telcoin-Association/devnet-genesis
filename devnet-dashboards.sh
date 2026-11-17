#!/bin/bash
#
# devnet-dashboards.sh — install / refresh the Telcoin Node Manager UI (the Flask "admin
# dashboard", systemd unit telcoin-ui, bound to 127.0.0.1:8080) on the node hosts, and
# publish it at its admin domain through tn-node-deployment's own dashboard block
# (install-caddy.sh --phase enable). Deploy step 17. Opt out: TN_ADMIN_DASHBOARD=0.
#
# Hosts (devnet-lib.sh): the node hosts (tn_node_indices); the gateway entry runs no node
# and no UI and is skipped. A host PUBLISHES when tn_admin_domain names a domain for it
# (admin.<node>.<BASE_DOMAIN>: a node with a same-host gateway, and the rpc node, i.e. the
# hosts that run Caddy). A validator fronted by a standalone gateway has no public HTTP:
# its UI is installed and published nowhere (reach it over the ssh tunnel,
# tn-node-deployment/open-ui.sh).
#
# Per host, over the lib's transport helpers (IAP, or the overlay with TN_SSH_TRANSPORT):
#   1. The UI, from the node's OWN ui/install-ui.sh in the root-owned checkout at
#      ${TN_NODE_SCRIPTS_DIR} (nothing is shipped from here; install-ui.sh refuses a tree an
#      administrator did not lay down). --update when telcoin-ui.service exists, then enable
#      it (--update leaves enable-on-boot alone); else a first install (</dev/null: no tty,
#      so it starts and enables the unit). Then assert enabled, GET / on 127.0.0.1:8080
#      answers 200, active: install-ui.sh exits 0 even when the start fails.
#   2. Publish (admin-domain hosts only, and only when 1 passed):
#      a. read install-caddy.sh --json --phase gateway-status and --phase rpc-status;
#      b. sudo bash install-caddy.sh --json --phase enable --domain <admin domain>
#         --username "${TN_ADMIN_AUTH_USER}" --password-stdin, the password on STDIN; the
#         done line decides (ok:true for this domain);
#      c. read both status phases again: `enabled` and `domain` of the gateway block and of
#         the public-RPC block must be unchanged (the phase rewrites the whole Caddyfile);
#      d. from THIS machine, https://<admin domain>/ must answer 401 without credentials (a
#         502 means Caddy cannot reach the UI; a name that does not resolve means its DNS
#         record is missing). The password is never sent from here. --no-public-check skips
#         d (a rehearsal before DNS exists).
#   The public site carries X-TN-Dashboard-Public, so the UI serves it READ-ONLY: writes and
#   non-allow-listed GETs answer 403 by design. Full controls: the ssh tunnel.
#
# The password: the Secret Manager secret TN_ADMIN_PASSWORD_SECRET (default
# devnet-admin-dashboard-password), read ONCE through tn_secret, one line of at least 16
# characters, piped to each host through tn_iap_ssh_cmd_stdin: never on argv (here or on the
# host), never in the environment, never echoed or logged. The host hashes it itself. The
# bcrypt hash devnet-admin-secret.sh stores (TN_ADMIN_HASH_SECRET) cannot serve: the native
# phase takes the password, and a hash does not turn back into one.
# Create the secret once (the value reaches neither shell history nor any argv):
#   openssl rand -base64 24 | tr -d '\n' | gcloud secrets create devnet-admin-dashboard-password --data-file=- --project=<PROJECT_ID>
# or keep the team's current password (the one devnet-admin-secret.sh printed): paste it at the
# silent prompt of
#   read -rs PW && printf '%s' "$PW" | gcloud secrets create devnet-admin-dashboard-password --data-file=- --project=<PROJECT_ID>; unset PW
# Share it: gcloud secrets versions access latest --secret=devnet-admin-dashboard-password --project=<PROJECT_ID>
#
# Usage:
#   ./devnet-dashboards.sh [--no-public-check] [target ...]   # all node hosts, or some
#                                                             # (index, instance name or node name)
#   ./devnet-dashboards.sh --preflight                        # read-only: the secret is usable
# Exit: 0 ok, 1 a host failed (or the preflight did), 2 usage or config.

set -euo pipefail
case "$-" in
    *x*) echo "❌ refusing to run under 'set -x' (xtrace would log the dashboard password)" >&2; exit 1 ;;
esac

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${REPO_DIR}/devnet-lib.sh"

: "${TN_ADMIN_PASSWORD_SECRET:=devnet-admin-dashboard-password}"
UI_INSTALLER="${TN_NODE_SCRIPTS_DIR}/ui/install-ui.sh"   # on the node, in its root-owned checkout
CADDY_SCRIPT="${TN_NODE_SCRIPTS_DIR}/install-caddy.sh"   # the same checkout
DASH_PW_MIN=16          # install-caddy.sh CADDY_PASSWORD_MIN
DASH_PUBLIC_TRIES=6     # the public 401 check: attempts, DASH_PUBLIC_SLEEP seconds apart
DASH_PUBLIC_SLEEP=10    # (Caddy obtains the certificate when the site is first configured)

usage() { sed -n '/^# Usage:/,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//'; }
die_usage() { echo "❌ $*" >&2; usage >&2; exit 2; }

PREFLIGHT=0
PUBLIC_CHECK=1
TARGETS=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --preflight)       PREFLIGHT=1 ;;
        --no-public-check) PUBLIC_CHECK=0 ;;
        -h|--help)         usage; exit 0 ;;
        -*)                die_usage "unknown flag '$1'" ;;
        *)                 TARGETS+=("$1") ;;
    esac
    shift
done
[ "${PREFLIGHT}" -eq 0 ] || [ "${#TARGETS[@]}" -eq 0 ] || die_usage "--preflight takes no targets"

if [ "${TN_ADMIN_DASHBOARD:-1}" != "1" ]; then
    echo "TN_ADMIN_DASHBOARD=${TN_ADMIN_DASHBOARD}: admin dashboards opted out, nothing to do."
    exit 0
fi
tn_fleet_check || { echo "❌ the fleet arrays in config.sh are inconsistent (lines above)" >&2; exit 2; }
case "${TN_ADMIN_AUTH_USER}" in
    ''|?|*[!A-Za-z0-9._-]*|?????????????????????????????????*)
        echo "❌ TN_ADMIN_AUTH_USER='${TN_ADMIN_AUTH_USER}': 2-32 of A-Z a-z 0-9 . _ - (install-caddy.sh's rule)" >&2; exit 2 ;;
esac

dash_secret_help() {
    echo "   Create it once (the value reaches neither shell history nor any argv):" >&2
    printf '%s\n' "     openssl rand -base64 24 | tr -d '\\n' | gcloud secrets create ${TN_ADMIN_PASSWORD_SECRET} --data-file=- --project=${PROJECT_ID}" >&2
    echo "   or keep the team's current password, pasted at a silent prompt:" >&2
    echo "     read -rs PW && printf '%s' \"\$PW\" | gcloud secrets create ${TN_ADMIN_PASSWORD_SECRET} --data-file=- --project=${PROJECT_ID}; unset PW" >&2
    echo "   (the secret exists already: 'gcloud secrets versions add' with the same arguments)" >&2
}

# dash_read_password — read the secret ONCE into DASH_PW (never printed, never exported).
# Only its line count and length are judged. rc 1 with the reason and the fix.
DASH_PW=""
dash_read_password() {
    local v=""
    if ! v="$(tn_secret "${TN_ADMIN_PASSWORD_SECRET}" 2>/dev/null)" || [ -z "${v}" ]; then
        echo "❌ cannot read Secret Manager secret ${TN_ADMIN_PASSWORD_SECRET} in ${PROJECT_ID} (missing, no version, empty or no access)." >&2
        dash_secret_help; return 1
    fi
    case "${v}" in
        *$'\n'*) echo "❌ secret ${TN_ADMIN_PASSWORD_SECRET} spans several lines; install-caddy.sh --password-stdin reads one." >&2
                 dash_secret_help; return 1 ;;
    esac
    if [ "${#v}" -lt "${DASH_PW_MIN}" ]; then
        echo "❌ secret ${TN_ADMIN_PASSWORD_SECRET} is shorter than ${DASH_PW_MIN} characters (install-caddy.sh refuses it)." >&2
        dash_secret_help; return 1
    fi
    DASH_PW="${v}"
}

if [ "${PREFLIGHT}" -eq 1 ]; then
    dash_read_password || exit 1
    DASH_PW=""
    echo "✅ ${TN_ADMIN_PASSWORD_SECRET}: one line, at least ${DASH_PW_MIN} characters (value not shown)."
    exit 0
fi

# --- targets: index, instance name or node name ------------------------------------
dash_resolve() {
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        if [ "$1" = "${i}" ] || [ "$1" = "${INSTANCE_NAMES[$i]}" ] || [ "$1" = "${NODE_NAMES[$i]}" ]; then
            printf '%s\n' "${i}"; return 0
        fi
    done
    return 1
}
SEL=()
if [ "${#TARGETS[@]}" -gt 0 ]; then
    for t in "${TARGETS[@]}"; do
        idx="$(dash_resolve "${t}")" || die_usage "unknown target '${t}' (not an index, instance name or node name)"
        SEL+=("${idx}")
    done
fi
dash_selected() {
    [ "${#SEL[@]}" -eq 0 ] && return 0
    local s
    for s in "${SEL[@]}"; do [ "${s}" = "$1" ] && return 0; done
    return 1
}

HOSTS=()
publish_any=0
for i in $(tn_node_indices); do
    dash_selected "${i}" || continue
    HOSTS+=("${i}")
    if dom="$(tn_admin_domain "${i}")"; then
        publish_any=1
        case "${dom}" in *[!A-Za-z0-9.-]*) echo "❌ admin domain '${dom}' of ${INSTANCE_NAMES[$i]} is not a hostname" >&2; exit 2 ;; esac
    fi
done
for i in $(tn_indices_by_role gateway); do
    if dash_selected "${i}"; then echo "↪ ${INSTANCE_NAMES[$i]}: a gateway host runs no node and no UI, skipped."; fi
done
[ "${#HOSTS[@]}" -gt 0 ] || { echo "no node host among the targets, nothing to do."; exit 0; }

RUN_LOG_DIR="${DEVNET_LIB_DIR}/logs/$(date +%Y%m%d_%H%M%S)-dashboards"
echo "=========================================="
echo "devnet admin dashboards (Node Manager UI): install, then publish"
echo "Project:   ${PROJECT_ID}   Transport: ${TN_SSH_TRANSPORT}"
echo "Installer: ${UI_INSTALLER}; publish: ${CADDY_SCRIPT} --phase enable (user ${TN_ADMIN_AUTH_USER})"
echo "Password:  Secret Manager ${TN_ADMIN_PASSWORD_SECRET} (stdin only, never shown)"
echo "Public:    $([ "${PUBLIC_CHECK}" -eq 1 ] && echo "https://<admin domain>/ must answer 401" || echo "check skipped (--no-public-check)")"
echo "Logs:      ${RUN_LOG_DIR}"
echo "=========================================="
mkdir -p "${RUN_LOG_DIR}"

if [ "${publish_any}" -eq 1 ]; then
    dash_read_password || { echo "nothing was touched." >&2; exit 1; }
fi

# The UI round trip (one root session; UI_MODE names the path, UI_REFRESH_OK = success).
remote_cmd="set -e; \
sudo test -f '${UI_INSTALLER}' || { echo 'UI_ERR: ${UI_INSTALLER} not found (no tn-node-deployment checkout at ${TN_NODE_SCRIPTS_DIR}?)' >&2; exit 1; }; \
if systemctl list-unit-files --no-legend telcoin-ui.service 2>/dev/null | grep -q '^telcoin-ui\.service'; then \
echo UI_MODE=update; sudo bash '${UI_INSTALLER}' --update </dev/null; sudo systemctl enable --quiet telcoin-ui; \
else \
echo UI_MODE=install; sudo bash '${UI_INSTALLER}' </dev/null; \
fi; \
systemctl is-enabled --quiet telcoin-ui || { echo 'UI_ERR: telcoin-ui is not enabled on boot' >&2; exit 1; }; \
curl -fsS --max-time 3 --retry 10 --retry-delay 2 --retry-connrefused -o /dev/null http://127.0.0.1:8080/ || { echo 'UI_ERR: no HTTP 200 from GET 127.0.0.1:8080/' >&2; exit 1; }; \
systemctl is-active --quiet telcoin-ui || { echo 'UI_ERR: telcoin-ui is not active (another process on :8080?)' >&2; exit 1; }; \
echo UI_REFRESH_OK"

# The two status phases in one read-only round trip, one "__tn_dash <phase> <json>" line each.
DASH_STATE_CMD="for p in gateway-status rpc-status; do l=\"\$(sudo bash '${CADDY_SCRIPT}' --json --phase \"\$p\" </dev/null 2>/dev/null | tail -n 1)\"; echo \"__tn_dash \$p \$l\"; done"

# dash_caddy_state <inst> <zone> <log> — prints "gateway enabled=<b> domain=<d>; rpc
# enabled=<b> domain=<d>"; rc 1 when a phase gave no status object.
dash_caddy_state() {
    local out p line en summary=""
    out="$(tn_iap_ssh "$1" "$2" "${DASH_STATE_CMD}" </dev/null 2>>"$3")" || true
    printf '%s\n' "--- caddy status" "${out}" >>"$3"
    for p in gateway-status rpc-status; do
        line="$(printf '%s\n' "${out}" | tr -d '\r' | sed -n "s/^__tn_dash ${p} //p" | tail -n 1)"
        case "${line}" in
            *'"enabled":'*) ;;
            *) echo "    ❌ install-caddy.sh --phase ${p} gave no status on $1 (see $3)" >&2; return 1 ;;
        esac
        en=false
        tn_json_true "${line}" enabled && en=true
        summary+="${p%-status} enabled=${en} domain=$(tn_json_str "${line}" domain); "
    done
    printf '%s\n' "${summary%; }"
}

# dash_public_check <domain> — from this machine, without credentials: rc 0 on 401.
dash_public_check() {
    local d="$1" n=0 code crc
    while :; do
        n=$((n + 1))
        crc=0
        code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "https://${d}/" 2>/dev/null)" || crc=$?
        if [ "${crc}" -eq 6 ]; then
            echo "    ❌ ${d} does not resolve: its DNS A record is missing (the host's static IP; devnet-deploy.sh step 4 lists the records)." >&2
            return 1
        fi
        if [ "${crc}" -eq 0 ] && [ "${code}" = 401 ]; then
            echo "    public: https://${d}/ answers 401 without credentials"
            return 0
        fi
        if [ "${n}" -ge "${DASH_PUBLIC_TRIES}" ]; then
            if [ "${code}" = 502 ]; then
                echo "    ❌ https://${d}/ answers 502: Caddy cannot reach the UI on 127.0.0.1:8080." >&2
            else
                echo "    ❌ https://${d}/ did not answer 401 after ${n} tries (last: HTTP ${code:-none}, curl rc ${crc})." >&2
            fi
            return 1
        fi
        sleep "${DASH_PUBLIC_SLEEP}"
    done
}

rc=0
published=()
ui_only=()
failed=()
for i in "${HOSTS[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    hlog="${RUN_LOG_DIR}/${inst}.log"
    dom="$(tn_admin_domain "${i}")" || dom=""

    echo ""
    echo ">>> ${inst} (${zone}): install-ui.sh$([ -n "${dom}" ] && printf ', then publish %s' "${dom}")"
    if out="$(tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}" </dev/null 2>&1)"; then ssh_rc=0; else ssh_rc=$?; fi
    printf '%s\n' "${out}" | sed 's/^/    /'
    mode="$(printf '%s\n' "${out}" | sed -n 's/^UI_MODE=//p' | tail -n 1)"
    if [ "${ssh_rc}" -ne 0 ] || ! printf '%s' "${out}" | grep -q 'UI_REFRESH_OK'; then
        echo "    ❌ ${inst}: UI rollout failed (path: ${mode:-none}; rc ${ssh_rc}), nothing published (UI_ERR / [ERROR] lines above)" >&2
        failed+=("${inst}"); rc=1; continue
    fi
    echo "    ✅ telcoin-ui ${mode:-?}: enabled, answering on 127.0.0.1:8080"

    if [ -z "${dom}" ]; then
        echo "    ↪ no admin domain (no Caddy here: the node is fronted by a standalone gateway): NOT published; use the ssh tunnel (open-ui.sh)."
        ui_only+=("${inst}"); continue
    fi

    before="$(dash_caddy_state "${inst}" "${zone}" "${hlog}")" || { failed+=("${inst}"); rc=1; continue; }
    echo "    before: ${before}"
    enable_cmd="sudo bash '${CADDY_SCRIPT}' --json --phase enable --domain '${dom}' --username '${TN_ADMIN_AUTH_USER}' --password-stdin"
    echo "    + ${enable_cmd}   [password on stdin]"
    ssh_rc=0
    out="$(printf '%s\n' "${DASH_PW}" | tn_iap_ssh_cmd_stdin "${inst}" "${zone}" "${enable_cmd}" 2>>"${hlog}")" || ssh_rc=$?
    { echo "--- install-caddy.sh --phase enable stdout (rc=${ssh_rc})"; printf '%s\n' "${out}"; } >>"${hlog}"
    events="$(printf '%s\n' "${out}" | grep -E '"event":"(warn|error)"' || true)"
    if [ -n "${events}" ]; then
        while IFS= read -r ev; do echo "      [$(tn_json_str "${ev}" event)] $(tn_json_str "${ev}" msg)"; done <<< "${events}"
    fi
    done_line="$(tn_json_done_line "${out}")"
    enabled_ok=0
    if [ -z "${done_line}" ]; then
        echo "    ❌ no done line from install-caddy.sh on ${inst} (ssh rc=${ssh_rc}; see ${hlog})" >&2
    elif ! tn_json_true "${done_line}" ok; then
        echo "    ❌ install-caddy.sh --phase enable failed on ${inst}: $(tn_json_str "${done_line}" msg)" >&2
    elif [ "${ssh_rc}" -ne 0 ]; then
        echo "    ❌ install-caddy.sh said ok on ${inst} but exited rc=${ssh_rc} (see ${hlog})" >&2
    elif [ "$(tn_json_str "${done_line}" domain)" != "${dom}" ]; then
        echo "    ❌ install-caddy.sh enabled '$(tn_json_str "${done_line}" domain)' on ${inst}, not ${dom}" >&2
    else
        enabled_ok=1
    fi
    [ "${enabled_ok}" -eq 1 ] || { failed+=("${inst}"); rc=1; continue; }
    echo "    done: ok, dashboard site ${dom}"

    after="$(dash_caddy_state "${inst}" "${zone}" "${hlog}")" || { failed+=("${inst}"); rc=1; continue; }
    if [ "${after}" != "${before}" ]; then
        echo "    ❌ the gateway / public-RPC blocks changed on ${inst}: after: ${after}" >&2
        failed+=("${inst}"); rc=1; continue
    fi
    echo "    after:  unchanged"

    if [ "${PUBLIC_CHECK}" -eq 1 ] && ! dash_public_check "${dom}"; then
        failed+=("${inst}"); rc=1; continue
    fi
    published+=("${inst}")
done
DASH_PW=""

echo ""
echo "=========================================="
[ "${#published[@]}" -gt 0 ] && echo "published: ${published[*]}"
[ "${#ui_only[@]}" -gt 0 ]   && echo "UI only:   ${ui_only[*]} (no public HTTP; ssh tunnel)"
[ "${#failed[@]}" -gt 0 ]    && echo "FAILED:    ${failed[*]}"
echo "per-host logs: ${RUN_LOG_DIR}"
if [ "${rc}" -eq 0 ]; then
    echo "admin dashboards done. Public sites are read-only (403 on writes is expected); log in as ${TN_ADMIN_AUTH_USER}."
else
    echo "admin dashboards finished WITH ERRORS — see the ❌ lines above." >&2
fi
echo "=========================================="
exit "${rc}"
