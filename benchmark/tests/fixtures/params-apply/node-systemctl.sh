#!/usr/bin/env bash
# systemctl on a fake node (tests/test_params_apply.py): restart marks state/restarted; every unit is active.
printf 'systemctl %s\n' "$*" >> "${STUB_NODE_DIR:?}/calls.log"
case "$*" in "restart telcoin") : > "${STUB_NODE_DIR}/state/restarted" ;; esac
exit 0
