#!/usr/bin/env bash
# devnet-finalize.sh stand-in, copied over the repo-root script in a test tree (test_node_image.py
# Step7Tests): logs its argv and CONFIG_FILE to $STUB_LOG, then prints $STUB_STAGE_OUT for
# --stage-only (exit $STUB_STAGE_RC) or $STUB_START_OUT for --start-all (exit $STUB_START_RC).
printf 'devnet-finalize.sh %s CONFIG_FILE=%s\n' "$*" "${CONFIG_FILE:-}" >> "${STUB_LOG:?}"
case "$*" in
    --stage-only) printf '%s\n' "${STUB_STAGE_OUT:-}"; exit "${STUB_STAGE_RC:-0}" ;;
    --start-all) printf '%s\n' "${STUB_START_OUT:-}"; exit "${STUB_START_RC:-0}" ;;
    *) echo "stub devnet-finalize.sh: unexpected: $*" >&2; exit 2 ;;
esac
