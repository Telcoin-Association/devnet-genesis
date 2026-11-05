#!/usr/bin/env bash
# devnet-keygen.sh stand-in, copied over the repo-root script in a test tree (test_node_image.py
# KeygenTests): logs its argv, CONFIG_FILE and the bench knobs it inherits to $STUB_LOG, prints
# $STUB_KEYGEN_OUT (KEYGEN_DONE lines and such), exits $STUB_KEYGEN_RC.
printf 'devnet-keygen.sh %s CONFIG_FILE=%s KEYGEN_JOBS=%s KEYGEN_REUSE_EXISTING=%s KEYGEN_RPC_ADVERTISE=%s KEYGEN_REPORT=%s\n' \
    "$*" "${CONFIG_FILE:-}" "${KEYGEN_JOBS:-}" "${KEYGEN_REUSE_EXISTING:-}" "${KEYGEN_RPC_ADVERTISE:-}" "${KEYGEN_REPORT:-}" >> "${STUB_LOG:?}"
printf '%s\n' "${STUB_KEYGEN_OUT:-}"
exit "${STUB_KEYGEN_RC:-0}"
