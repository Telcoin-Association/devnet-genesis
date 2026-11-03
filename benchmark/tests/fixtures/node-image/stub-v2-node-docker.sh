#!/usr/bin/env bash
# docker on a sandbox v2 node (v2-node-run.sh), the running telcoin container:
#   inspect -f '{{.State.StartedAt}}' telcoin      $STUB_STATE/started; from read number
#                                                  $STUB_STATE/started-flip + 1 on, a later time
#                                                  (the container was restarted in between)
#   inspect -f '{{.Path}} {{join .Args " "}}' telcoin  $STUB_STATE/cmdline
#   logs telcoin --since <t>                       $STUB_STATE/boot.log (a `logs` call without
#                                                  --since fails: the bench reads since a start)
# Nothing else is expected on the node.
printf 'docker %s\n' "$*" >> "${STUB_LOG:?}"
st="${STUB_STATE:?}"
case "$*" in
    "inspect -f {{.State.StartedAt}} telcoin")
        n=$(( $(cat "${st}/started-reads" 2>/dev/null || echo 0) + 1 )); echo "${n}" > "${st}/started-reads"
        if [ -f "${st}/started-flip" ] && [ "${n}" -gt "$(cat "${st}/started-flip")" ]; then
            echo "2026-01-01T00:09:00.000000000Z"
        else
            cat "${st}/started"
        fi ;;
    'inspect -f {{.Path}} {{join .Args " "}} telcoin') cat "${st}/cmdline" ;;
    "logs telcoin --since "?*) cat "${st}/boot.log" ;;
    *) echo "stub docker: unexpected: $*" >&2; exit 2 ;;
esac
