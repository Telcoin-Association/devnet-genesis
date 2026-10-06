#!/usr/bin/env bash
# docker on the node, for step 9's remote script: `docker logs telcoin ...` prints the boot log
# fixture $STUB_BOOT_LOG; every other docker call succeeds silently.
printf 'docker %s\n' "$*" >> "${STUB_LOG:?}"
case "${1:-}" in logs) cat "${STUB_BOOT_LOG:?}" ;; *) exit 0 ;; esac
