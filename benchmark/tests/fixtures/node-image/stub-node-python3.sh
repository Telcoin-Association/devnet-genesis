#!/usr/bin/env bash
# python3 on a sandbox v2 node (test_node_image.py): logs `python3 <args>` to $STUB_LOG, then
#   no $STUB_STATE/fsync-probe  -> the real python3 (the next one on PATH after the node's bin/), stdin kept:
#                                  the fsync probe runs for real on the sandbox datadir
#   $STUB_STATE/fsync-probe     -> the program on stdin is read and dropped, that file's text is the output and
#                                  $STUB_STATE/fsync-probe-rc (default 0) the exit status (canned probe results)
printf 'python3 %s\n' "$*" >> "${STUB_LOG:?}"
f="${STUB_STATE:?}/fsync-probe"
if [ -f "${f}" ]; then
    cat > /dev/null
    cat "${f}"
    exit "$(cat "${STUB_STATE}/fsync-probe-rc" 2>/dev/null || echo 0)"
fi
PATH="${PATH#*:}" exec python3 "$@"
