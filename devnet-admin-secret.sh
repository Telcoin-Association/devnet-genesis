#!/bin/bash
#
# devnet-admin-secret.sh — ONE-TIME setup of the shared admin-dashboard basic_auth
# credential. Generates a random password, bcrypt-hashes it, and stores the HASH in
# GCP Secret Manager (the name in config.sh: TN_ADMIN_HASH_SECRET). The rollout
# scripts (common/dns.sh) fetch that hash automatically on every run — so after this
# runs once, no env vars are ever needed again.
#
# Idempotent: if the secret already exists it does nothing (so re-running is safe and
# never rotates the password by surprise). Use --rotate to set a NEW password.
#
# The plaintext password is printed ONCE here — store it in your password manager and
# share it with the team out of band. It is NOT recoverable from the stored hash.
#
# Usage:
#   ./devnet-admin-secret.sh            # create if absent (no-op if it exists)
#   ./devnet-admin-secret.sh --rotate   # add a new version with a fresh password

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "${REPO_DIR}/config.sh"

ROTATE=0
[ "${1:-}" = "--rotate" ] && ROTATE=1

SECRET="${TN_ADMIN_HASH_SECRET}"
USER_NAME="${TN_ADMIN_AUTH_USER}"

echo "=========================================="
echo "Admin dashboard credential — Secret Manager"
echo "Project: ${PROJECT_ID}   Secret: ${SECRET}   Username: ${USER_NAME}"
echo "=========================================="

exists=0
if gcloud secrets describe "${SECRET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    exists=1
fi

if [ "${exists}" -eq 1 ] && [ "${ROTATE}" -eq 0 ]; then
    echo "✅ Secret '${SECRET}' already exists — nothing to do."
    echo "   The dashboards fetch it automatically; no env vars needed."
    echo "   To set a NEW password: ./devnet-admin-secret.sh --rotate"
    exit 0
fi

# Need a local bcrypt hasher. Caddy is preferred (it's what serves basic_auth).
if ! command -v caddy >/dev/null 2>&1; then
    echo "❌ 'caddy' not found locally — needed to bcrypt-hash the password." >&2
    echo "   Install it (e.g. 'brew install caddy'), or run 'caddy hash-password' on any node and" >&2
    echo "   store the result yourself with: gcloud secrets create ${SECRET} --data-file=- --project=${PROJECT_ID}" >&2
    exit 1
fi

# Generate + hash. caddy v2: --plaintext is the non-interactive flag.
PW="$(openssl rand -base64 24)"
HASH="$(caddy hash-password --plaintext "${PW}")"
if [ -z "${HASH}" ]; then
    echo "❌ caddy hash-password produced an empty hash — aborting (no secret written)." >&2
    exit 1
fi

if [ "${exists}" -eq 1 ]; then
    printf '%s' "${HASH}" | gcloud secrets versions add "${SECRET}" --data-file=- --project="${PROJECT_ID}" >/dev/null
    echo "🔁 Rotated: added a new version of '${SECRET}'."
else
    printf '%s' "${HASH}" | gcloud secrets create "${SECRET}" --data-file=- --project="${PROJECT_ID}" >/dev/null
    echo "🆕 Created secret '${SECRET}'."
fi

echo ""
echo "=================================================================="
echo " STORE THIS NOW (printed only once; not recoverable from the hash):"
echo ""
echo "     URL:      https://admin.node1.${BASE_DOMAIN}/   (node1..node5)"
echo "     username: ${USER_NAME}"
echo "     password: ${PW}"
echo ""
echo " The bcrypt hash is in Secret Manager; the rollout scripts fetch it"
echo " automatically. Next: ./devnet-dashboards.sh && ./common/dns.sh"
echo "=================================================================="