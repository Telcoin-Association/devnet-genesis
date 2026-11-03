#!/usr/bin/env bash
# stat on a sandbox v2 node: `stat -c '%U:%G %a' <file>` answers $STUB_STATE/stat, default
# "root:root 755" (the sandbox files belong to the test user, a node's to root).
printf 'stat %s\n' "$*" >> "${STUB_LOG:?}"
[ "${1:-}" = -c ] && [ "${2:-}" = '%U:%G %a' ] && [ -e "${3:-}" ] || { echo "stub stat: unexpected: $*" >&2; exit 1; }
cat "${STUB_STATE:?}/stat" 2>/dev/null || echo "root:root 755"
