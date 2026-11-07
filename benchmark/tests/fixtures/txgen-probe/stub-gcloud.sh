#!/usr/bin/env bash
# Fake gcloud for test_txgen_probe.py: the registry login's token, and nothing else.
printf '%s\n' "gcloud $*" >> "${STUB_LOG:?}"
if [ "$*" = "auth print-access-token" ]; then echo fake-access-token; exit 0; fi
echo "stub gcloud: unexpected call: $*" >&2
exit 97
