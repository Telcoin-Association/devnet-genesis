#!/usr/bin/env bash
# systemctl on a fake node (tests/test_params_apply.py): start (or restart) marks state/restarted;
# every unit is active. A file stop-fails or start-fails in the node makes that verb fail.
printf 'systemctl %s\n' "$*" >> "${STUB_NODE_DIR:?}/calls.log"
case "$*" in
    "stop telcoin") [ ! -f "${STUB_NODE_DIR}/stop-fails" ] || exit 1 ;;
    "restart telcoin"|"start telcoin")
        [ ! -f "${STUB_NODE_DIR}/start-fails" ] || exit 1
        : > "${STUB_NODE_DIR}/state/restarted" ;;
esac
exit 0
