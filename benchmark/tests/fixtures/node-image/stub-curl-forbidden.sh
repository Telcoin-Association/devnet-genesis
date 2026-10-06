#!/usr/bin/env bash
# curl must not be reached by these tests (no registry HEAD, no network): log and fail.
printf 'curl %s\n' "$*" >> "${STUB_LOG:?}"
echo "stub curl: network access attempted: $*" >&2
exit 97
