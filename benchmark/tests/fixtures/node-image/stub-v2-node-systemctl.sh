#!/usr/bin/env bash
# systemctl on a sandbox v2 node (v2-node-run.sh): unit telcoin is $STUB_STATE/unit (active,
# inactive, failed, ...) with NRestarts $STUB_STATE/nrestarts (default 0); every other unit is
# active, and start / stop / enable / daemon-reload succeed. `is-active` prints the state and
# exits 3 unless active, as systemd does.
printf 'systemctl %s\n' "$*" >> "${STUB_LOG:?}"
unit() { cat "${STUB_STATE:?}/unit" 2>/dev/null || echo active; }
case "$*" in
    "is-active telcoin") s="$(unit)"; echo "${s}"; [ "${s}" = active ] || exit 3 ;;
    "is-active --quiet telcoin") [ "$(unit)" = active ] || exit 3 ;;
    "show -p NRestarts --value telcoin") cat "${STUB_STATE}/nrestarts" 2>/dev/null || echo 0 ;;
    "is-active --quiet "*|"daemon-reload"|"enable --now "*|"start "*|"stop "*) exit 0 ;;
    *) echo "stub systemctl: unexpected: $*" >&2; exit 1 ;;
esac
