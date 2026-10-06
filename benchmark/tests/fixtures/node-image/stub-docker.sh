#!/usr/bin/env bash
# Offline stand-in for the operator's docker (test_node_image.py). Logs every call to
# $STUB_LOG. The "image" is the directory $STUB_IMAGE_DIR: `run --entrypoint
# /usr/local/bin/telcoin <img> <args>` prints its out-*/help-* file for <args>, and
# `cp <cid>:/usr/local/bin/telcoin <dest>` copies its node-bin file. No local images exist.
printf 'docker %s\n' "$*" >> "${STUB_LOG:?}"
if [ "${1:-}" = "--config" ]; then shift 2; fi
case "${1:-}" in
    info) [ "${STUB_DOCKER_DOWN:-0}" = 1 ] && exit 1; exit 0 ;;
    login) cat > /dev/null; exit 0 ;;
    pull) exit 0 ;;
    image) exit 1 ;;
    run)
        shift; ep=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --rm|--pull=never) shift ;;
                --platform) shift 2 ;;
                --entrypoint) ep="$2"; shift 2 ;;
                *) break ;;
            esac
        done
        if [ "${ep}" != /usr/local/bin/telcoin ]; then
            echo "stub docker: run without --entrypoint /usr/local/bin/telcoin" >&2; exit 125
        fi
        shift   # the image ref
        d="${STUB_IMAGE_DIR:?}"
        case "$*" in
            -V) cat "${d}/out-short-version.txt" ;;
            --version) cat "${d}/out-long-version.txt" ;;
            "node --help") cat "${d}/help-node.txt" ;;
            "genesis --help") cat "${d}/help-genesis.txt" ;;
            "keytool generate validator --help") cat "${d}/help-keytool.txt" ;;
            *) echo "error: unrecognized arguments '$*'" >&2; exit 2 ;;
        esac ;;
    create) echo stubcid0001 ;;
    cp)
        shift; [ "${1:-}" != -L ] || shift
        [ "${1:-}" = stubcid0001:/usr/local/bin/telcoin ] || { echo "stub docker: cp of '${1:-}'" >&2; exit 1; }
        cp "${STUB_IMAGE_DIR:?}/node-bin" "$2" ;;
    rm) exit 0 ;;
    *) echo "stub docker: unexpected: $*" >&2; exit 2 ;;
esac
