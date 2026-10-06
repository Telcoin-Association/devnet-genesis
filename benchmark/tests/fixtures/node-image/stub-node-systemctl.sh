#!/usr/bin/env bash
# systemctl on the node: every unit restarts, is active and enables fine.
printf 'systemctl %s\n' "$*" >> "${STUB_LOG:?}"
exit 0
