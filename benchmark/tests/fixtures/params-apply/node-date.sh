#!/usr/bin/env bash
# date on a fake node (tests/test_params_apply.py): `date +%s` is a clock that advances one second
# per call (state/clock), so a wait loop ends after a bounded number of polls; any other use is real.
if [ "$*" = "+%s" ]; then
    f="${STUB_NODE_DIR:?}/state/clock"; n=1700000000; [ ! -f "${f}" ] || n="$(cat "${f}")"
    n=$((n + 1)); echo "${n}" > "${f}"; echo "${n}"
else
    exec /bin/date "$@"
fi
