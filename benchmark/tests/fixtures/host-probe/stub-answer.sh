#!/usr/bin/env bash
# A host tool on a fake node root (test_host_probe.py), installed as findmnt, lsblk and fincore: logs
# `<name> <args>` to $STUB_LOG, then answers call number <n> of <name> with the text of
# $STUB_STATE/<name>.<n> when that file exists, else with $STUB_STATE/<name>; with neither it exits 1,
# as a tool that failed or is missing. Exit status otherwise: $STUB_STATE/<name>.rc, default 0.
n="$(basename "$0")"
printf '%s %s\n' "${n}" "$*" >> "${STUB_LOG:?}"
c=$(( $(cat "${STUB_STATE:?}/${n}.calls" 2>/dev/null || echo 0) + 1 ))
echo "${c}" > "${STUB_STATE}/${n}.calls"
if [ -f "${STUB_STATE}/${n}.${c}" ]; then
    cat "${STUB_STATE}/${n}.${c}"
elif [ -f "${STUB_STATE}/${n}" ]; then
    cat "${STUB_STATE}/${n}"
else
    exit 1
fi
exit "$(cat "${STUB_STATE}/${n}.rc" 2>/dev/null || echo 0)"
