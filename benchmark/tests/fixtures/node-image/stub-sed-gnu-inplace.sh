#!/usr/bin/env bash
# Installed only where the host sed is BSD sed (macOS): the remote script targets the nodes'
# GNU sed, whose `sed -i <script> <file>` BSD sed would read as a backup suffix.
if [ "${1:-}" = "-i" ]; then shift; exec /usr/bin/sed -i '' "$@"; fi
exec /usr/bin/sed "$@"
