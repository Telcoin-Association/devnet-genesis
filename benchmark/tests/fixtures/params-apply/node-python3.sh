#!/usr/bin/env bash
# python3 on a fake node (tests/test_params_apply.py). `python3 - <mode> ...` is bench-lib.sh's host
# program (the host probe, or a host step) on stdin: logged as `python3 <mode> <args>` in the node's
# calls.log and answered from the node's state files, so nothing reads or writes the real /sys.
# Anything else (the node's docker stub is a python script) runs the real one, $PA_REAL_PYTHON3.
#   <node>/read-ahead-kb   the data disk's read_ahead_kb (absent: 128); the step writes it
#   <node>/resident-pages  mdbx.dat's resident pages before an eviction (absent: 812345)
#   <node>/probe-fails, <node>/read-ahead-fails, <node>/evict-fails: that call fails, with the
#                          file's text as the reason
[ "${1:-}" = - ] || exec "${PA_REAL_PYTHON3:?}" "$@"
shift
prog="$(cat)"
d="${STUB_NODE_DIR:?}"
printf 'python3 %s\n' "$*" >> "${d}/calls.log"
case "${prog}" in *"def read_ahead(d, kb):"*) ;; *) echo "fake python3: stdin is not the host program" >&2; exit 2 ;; esac
ra="$(cat "${d}/read-ahead-kb" 2>/dev/null || echo 128)"
case "$1" in
    probe)
        if [ -f "${d}/probe-fails" ]; then echo "HOST_PROBE $2 probe_failed $(cat "${d}/probe-fails")"; exit 0; fi
        printf 'HOST_PROBE %s {"datadir":"%s","disk":"sda","read_ahead_kb":%s}\n' "$2" "$3" "${ra}" ;;
    read-ahead-kb)
        if [ -f "${d}/read-ahead-fails" ]; then echo "failed $(cat "${d}/read-ahead-fails")"; exit 0; fi
        echo "$3" > "${d}/read-ahead-kb"
        echo "ok ${ra} $3" ;;
    evict-mdbx)
        if [ -f "${d}/evict-fails" ]; then echo "failed $(cat "${d}/evict-fails")"; exit 0; fi
        echo "ok $(cat "${d}/resident-pages" 2>/dev/null || echo 812345) 0" ;;
    *) echo "failed unknown mode '$1'" ;;
esac
