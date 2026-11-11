#!/usr/bin/env bash
# systemd-run on a fake node (tests/test_params_apply.py): logs the call, then runs the command
# after `--` at once, in the foreground, so the unit's stop, host steps and start are done when it
# returns (the real one returns once the unit started). Its status is systemd-run's own: 0, unless
# the node has a file systemd-run-fails.
printf 'systemd-run %s\n' "$*" >> "${STUB_NODE_DIR:?}/calls.log"
[ ! -f "${STUB_NODE_DIR}/systemd-run-fails" ] || { echo "Failed to start transient service unit" >&2; exit 1; }
while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ $# -gt 1 ] || { echo "fake systemd-run: no command after --" >&2; exit 2; }
shift
"$@" || true
exit 0
