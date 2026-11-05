#!/usr/bin/env bash
# python3 for benchmark/tests/test_finalize_modes.py, first on PATH in each sandbox (bin/python3).
# devnet-finalize.sh calls python3 for two things: `python3 -c 'import yaml'` (answered yes, so
# the test does not depend on PyYAML) and `devnet-network-config.py validate ... --node <n> <file>`
# on each node's network-config bytes. validate passes when the script is there and the file is
# not empty (with FIN_REAL_VALIDATE=1 the real devnet-network-config.py decides); its arguments are
# appended, tab-separated, one call per line, to $FIN_SB/validate.log.
# The raw-shape half of the script's _nc_verdict (admission / mode: Closed / committee_peers)
# runs for real on fixtures/finalize/network-config.yaml. Anything else (the fake gcloud's own
# interpreter) runs $FIN_REAL_PYTHON.
case "${1:-}" in
    -c)
        if [ "${2:-}" = "import yaml" ]; then exit 0; fi ;;
    */devnet-network-config.py)
        if [ "${2:-}" = "validate" ]; then
            line="$(printf '%s\t' "$@")"   # one write per call: parallel nodes append too
            printf '%s\n' "${line}" >> "${FIN_SB:?}/validate.log"
            # FIN_REAL_VALIDATE=1: the real validator judges the file (logged all the same).
            if [ "${FIN_REAL_VALIDATE:-0}" = 1 ]; then exec "${FIN_REAL_PYTHON:?}" "$@"; fi
            last=""
            for a in "$@"; do last="${a}"; done
            if [ -f "$1" ] && [ -s "${last}" ]; then exit 0; fi
            echo "FAIL fake validate: no ${1##*/} or an empty network-config" >&2
            exit 1
        fi ;;
esac
exec "${FIN_REAL_PYTHON:?}" "$@"
