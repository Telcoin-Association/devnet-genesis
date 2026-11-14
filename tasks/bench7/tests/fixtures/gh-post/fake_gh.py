#!/usr/bin/env python3
"""A fake gh for the orch-gh-post.sh shim tests.

Every call appends its argv (JSON, one line) to $FAKE_GH_LOG.
Unarmed ($FAKE_GH_MODE unset) it prints REACHED and exits 9, so a dry run that reaches gh fails loudly.
Armed:
  ok          list calls print $FAKE_GH_LIST; create and comment calls print a URL
              (https://github.com/x/y/issues/<n>, .../pull/<n>, .../issues/<issue>#issuecomment-4242),
              <n> = $FAKE_GH_NUMBER or 123
  fail        every call fails (stderr "HTTP 422: fake failure", exit 1)
  fail-create list calls behave as ok, the create or comment fails
  no-url      list calls behave as ok, the create or comment exits 0 without a URL
A --body-file argument is copied to $FAKE_GH_BODY_COPY when that is set (the script removes its temp
file on exit, so the copy is the only way to see what would have been posted).
"""
import json
import os
import shutil
import sys


def main():
    argv = sys.argv[1:]
    log = os.environ.get("FAKE_GH_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\n")
    mode = os.environ.get("FAKE_GH_MODE", "")
    if not mode:
        print("REACHED")
        return 9
    verb = argv[:2]
    if verb in (["issue", "list"], ["pr", "list"]):
        if mode == "fail":
            sys.stderr.write("HTTP 422: fake failure\n")
            return 1
        sys.stdout.write(os.environ.get("FAKE_GH_LIST", ""))
        return 0
    copy = os.environ.get("FAKE_GH_BODY_COPY")
    if copy and "--body-file" in argv:
        i = argv.index("--body-file")
        if i + 1 < len(argv):
            shutil.copyfile(argv[i + 1], copy)
    if mode in ("fail", "fail-create"):
        sys.stderr.write("HTTP 422: fake failure\n")
        return 1
    if mode == "no-url":
        print("created")
        return 0
    n = os.environ.get("FAKE_GH_NUMBER", "123")
    if verb == ["issue", "create"]:
        print("https://github.com/x/y/issues/" + n)
    elif verb == ["pr", "create"]:
        print("https://github.com/x/y/pull/" + n)
    elif verb == ["issue", "comment"] and len(argv) > 2:
        print("https://github.com/x/y/issues/%s#issuecomment-4242" % argv[2])
    else:
        print("REACHED")
        return 9
    return 0


if __name__ == "__main__":
    sys.exit(main())
