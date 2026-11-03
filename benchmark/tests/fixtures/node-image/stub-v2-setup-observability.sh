#!/usr/bin/env bash
# setup-observability.sh on a sandbox v2 node (test_node_image.py ObsScriptTests), at
# <node>/opt/telcoin-node-scripts/setup-observability.sh. Records what it was given:
#   $STUB_STATE/obs-argv   one argument per line
#   $STUB_STATE/obs-stdin  its stdin, byte for byte
#   $STUB_STATE/obs-env    its environment (env)
# then answers like the real one in --json mode: the JSON events on stdout ($STUB_OBS_EVENTS, a
# fixtures/node-image/obs-events-*.jsonl file), the print_* lines on stderr, coloured: the
# no-restart phrase unless STUB_OBS_PHRASE=0, then $STUB_OBS_ERR_LINES numbered [ERROR] lines, then
# (STUB_OBS_LEAK=1) one line that holds the token it read. Exit status $STUB_OBS_RC (default 0).
st="${STUB_STATE:?}"
printf '%s\n' "$@" > "${st}/obs-argv"
cat > "${st}/obs-stdin"
env > "${st}/obs-env"
printf 'setup-observability.sh %s\n' "$*" >> "${STUB_LOG:?}"
printf '  \033[0;34m[INFO]\033[0m Enabling metrics shipping\n' >&2
if [ "${STUB_OBS_PHRASE:-1}" = 1 ]; then
    printf '  \033[0;32m[OK]\033[0m  Node already serves a metrics endpoint (--metrics).\n' >&2
else
    printf '  \033[0;32m[OK]\033[0m  Added --metrics 127.0.0.1:9101 to the node command\n' >&2
fi
i=1
while [ "${i}" -le "${STUB_OBS_ERR_LINES:-0}" ]; do
    printf '  \033[0;31m[ERROR]\033[0m alloy check %d failed\n' "${i}" >&2
    i=$((i + 1))
done
[ "${STUB_OBS_LEAK:-0}" != 1 ] || printf 'curl -H "Authorization: Bearer %s" refused\n' "$(head -1 "${st}/obs-stdin")" >&2
cat "${STUB_OBS_EVENTS:?}"
exit "${STUB_OBS_RC:-0}"
