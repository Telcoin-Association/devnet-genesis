#!/usr/bin/env bash
# logrotate on a sandbox v2 node (v2-node-run.sh): `logrotate -d <file>` (debug: parse, rotate nothing)
# succeeds when <file> has a `{ ... }` block with at least one directive and logs `logrotate -d <file>`;
# a missing file or no block fails like logrotate's parser. Anything else fails loudly.
printf 'logrotate %s\n' "$*" >> "${STUB_LOG:?}"
[ "$#" -eq 2 ] && [ "$1" = "-d" ] || { echo "stub logrotate: unexpected: $*" >&2; exit 1; }
[ -f "$2" ] || { echo "error: stat of $2 failed: No such file or directory" >&2; exit 1; }
awk '/\{[[:space:]]*$/ { o = 1; next } o && /^[[:space:]]*}[[:space:]]*$/ { if (d) ok = 1; o = 0; next } o && NF { d = 1 }
     END { exit ok ? 0 : 1 }' "$2" || { echo "error: $2: no complete { } block" >&2; exit 1; }
