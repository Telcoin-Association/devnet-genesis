#!/usr/bin/env bash
# One-time: remove the basic_auth frontdoor from node5's admin dashboard vhost so it is
# publicly viewable (still READ-ONLY — the X-TN-Dashboard-Public guard is untouched).
# Surgical in-place edit of node5's live /etc/caddy/Caddyfile; backup + validate + rollback.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source ./devnet-lib.sh            # sources config.sh

i=4                               # node5 lives at index [4]
inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"; name="${NODE_NAMES[$i]}"
[ "${name}" = "node5" ] || { echo "guard: index $i is '${name}', not node5 — aborting." >&2; exit 1; }
admin_fqdn="admin.${name}.${BASE_DOMAIN}"
echo ">>> Removing admin frontdoor on ${name} (${inst} / ${zone}): ${admin_fqdn}"

# Inject the FQDN as a %q-quoted assignment line, then a fully-literal remote script.
{
  printf 'ADMIN_FQDN=%q\n' "${admin_fqdn}"
  cat <<'REMOTE'
set -euo pipefail
CF=/etc/caddy/Caddyfile
TS=$(date +%Y%m%d-%H%M%S)
echo "[node5] target vhost: ${ADMIN_FQDN}"

if ! grep -q 'basic_auth' "$CF"; then
  echo "[node5] no basic_auth block present — frontdoor already removed; nothing to do."; exit 0
fi

before=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
  --resolve "${ADMIN_FQDN}:443:127.0.0.1" "https://${ADMIN_FQDN}/" || echo ERR)
echo "[node5] admin HTTP BEFORE: ${before} (expect 401 = frontdoor up)"

cp -a "$CF" "${CF}.bak.${TS}"; echo "[node5] backup: ${CF}.bak.${TS}"

# Delete every basic_auth { ... } block (brace-balanced). basic_auth occurs ONLY in the
# admin vhost, so this strips the frontdoor and nothing else. caddy validate is the safety net.
awk '
  skip==0 && $0 ~ /(^|[[:space:]])basic_auth([[:space:]]|\{|$)/ { skip=1; depth=0 }
  skip==1 { o=gsub(/\{/,"{"); c=gsub(/\}/,"}"); depth+=o-c; if (depth<=0) skip=0; next }
  { print }
' "${CF}.bak.${TS}" > "$CF"

caddy fmt --overwrite "$CF"
if ! caddy validate --adapter caddyfile --config "$CF"; then
  echo "[node5] ERROR: invalid Caddyfile — restoring backup, NOT reloading." >&2
  cp -a "${CF}.bak.${TS}" "$CF"; exit 1
fi
if ! grep -q 'X-TN-Dashboard-Public' "$CF"; then
  echo "[node5] ERROR: read-only header missing after edit — restoring backup." >&2
  cp -a "${CF}.bak.${TS}" "$CF"; exit 1
fi

systemctl reload caddy || { echo "[node5] reload failed — restoring + reload." >&2; \
  cp -a "${CF}.bak.${TS}" "$CF"; systemctl reload caddy; exit 1; }

sleep 2
after=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
  --resolve "${ADMIN_FQDN}:443:127.0.0.1" "https://${ADMIN_FQDN}/" || echo ERR)
echo "[node5] admin HTTP AFTER: ${after} (expect NOT 401)"
if [ "${after}" = "401" ]; then
  echo "[node5] ERROR: still 401 — restoring backup." >&2
  cp -a "${CF}.bak.${TS}" "$CF"; systemctl reload caddy; exit 1
fi
echo "[node5] ✅ frontdoor removed — dashboard publicly viewable (read-only). Backup: ${CF}.bak.${TS}"
REMOTE
} | tn_iap_ssh_stdin "${inst}" "${zone}"
