#!/usr/bin/env bash
# Fake docker for test_txgen_probe.py: logs each call as "docker <argv>" (words joined by single
# spaces) to STUB_LOG, answers `info`, swallows a `login`'s password on stdin, and for
# `run ... blast --help` prints the file STUB_HELP names (the image's canned help text).
printf '%s\n' "docker $*" >> "${STUB_LOG:?}"
args=("$@")
while [ "${#args[@]}" -gt 0 ] && [ "${args[0]}" = "--config" ]; do args=("${args[@]:2}"); done
case "${args[0]:-}" in
    info) exit 0 ;;
    login) cat >/dev/null; exit 0 ;;
    run)
        case " ${args[*]} " in
            *" blast --help "*) cat -- "${STUB_HELP:?}"; exit 0 ;;
        esac ;;
esac
echo "stub docker: unexpected call: $*" >&2
exit 97
