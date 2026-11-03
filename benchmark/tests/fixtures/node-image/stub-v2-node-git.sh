#!/usr/bin/env bash
# git on a sandbox v2 node: `git -C <dir> rev-parse HEAD` answers $STUB_STATE/git-head (the
# scripts' checkout); nothing else is expected.
printf 'git %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    "-C "?*" rev-parse HEAD") cat "${STUB_STATE:?}/git-head" ;;
    *) echo "stub git: unexpected: $*" >&2; exit 1 ;;
esac
