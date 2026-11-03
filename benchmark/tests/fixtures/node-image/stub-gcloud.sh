#!/usr/bin/env bash
# Offline stand-in for gcloud (test_node_image.py). Logs every call to $STUB_LOG.
#   artifacts docker images describe  -> $STUB_DIGEST (fails when unset)
#   auth print-access-token           -> a dummy token
# Anything else fails loudly (the deploy steps that ssh to nodes use stub-gcloud-v2-node.sh).
printf 'gcloud %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    "artifacts docker images describe "*) [ -n "${STUB_DIGEST:-}" ] || exit 1; echo "${STUB_DIGEST}" ;;
    "auth print-access-token"*) echo stub-token-not-a-secret ;;
    *) echo "stub gcloud: unexpected: $*" >&2; exit 1 ;;
esac
