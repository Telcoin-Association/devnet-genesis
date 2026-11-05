#!/usr/bin/env python3
"""Offline stand-in for `gcloud compute ssh` (test_pull_logs.py).

Every call appends {"argv", "stdin", "session", "outcome"} to $FAKE_ROOT/calls.jsonl. The session
is the first line of the script on stdin when the remote command is `sudo bash -s` (the pull's
"# bench-pull: span" / "# bench-pull: rotated"); any other stdin script is refused. A call with
another remote command is session "cmd".

A session runs for real on this machine, as the node would run it: the stdin script under
`bash -s`, a command under `bash -c` (a leading "sudo " dropped). The node's files are the paths
the script names; the tests point BENCH_NODE_UNIT_LOGS at a directory of their own.

FAKE_OUTCOMES=<outcome>[,<outcome>...] scripts the calls in order (the last one repeats; default ok):
  ok          the session's own stdout, stderr and rc
  partial255  the first half of the session's stdout, a dropped connection on stderr, rc 255
  partial0    the first half of the session's stdout, rc 0 (a cut stream that reports success)
  refused     no output, IAP's 4033 refusal on stderr, rc 255
  reauth      no output, gcloud's re-authentication failure on stderr, rc 1
  other       no output, a failing remote command on stderr, rc 1
  empty       no output, rc 0
FAKE_SPAN_FILE=<path>: a span session prints this file instead of running its script.
"""
import json
import os
import subprocess
import sys

ROOT = os.environ["FAKE_ROOT"]
HEADER = "# bench-pull: "

STDERR = {
    "partial255": "Connection to compute.googleapis.com closed by remote host.\n",
    "refused": "ERROR: (gcloud.compute.start-iap-tunnel) Error while connecting [4033: 'not authorized'].\n",
    "reauth": ("ERROR: (gcloud.compute.ssh) There was a problem refreshing your current auth tokens: "
               "Reauthentication failed. cannot prompt during non-interactive execution.\n"
               "Please run:\n\n  $ gcloud auth login\n\nto obtain new credentials.\n"),
    "other": "bash: line 1: /var/log/telcoin/telcoin.log: Permission denied\n",
}
RC = {"partial255": 255, "refused": 255, "reauth": 1, "other": 1}


def die(msg, code=1):
    sys.stderr.write("fake gcloud: " + msg + "\n")
    sys.exit(code)


def next_outcome():
    p = os.path.join(ROOT, "calls-made")
    n = int(open(p).read()) if os.path.exists(p) else 0
    with open(p, "w") as fh:
        fh.write(str(n + 1))
    outcomes = (os.environ.get("FAKE_OUTCOMES") or "ok").split(",")
    return outcomes[min(n, len(outcomes) - 1)]


def main():
    argv = sys.argv[1:]
    stdin = b"" if sys.stdin.isatty() else sys.stdin.buffer.read()
    pos = [a for a in argv if not a.startswith("-")]
    if pos[:2] != ["compute", "ssh"]:
        die("unexpected: " + " ".join(argv))
    cmd = [a for a in argv if a.startswith("--command=")]
    if len(cmd) != 1:
        die("one --command= expected")
    cmd = cmd[0][len("--command="):]
    if cmd == "sudo bash -s":
        first = stdin.decode("utf-8", "replace").split("\n", 1)[0]
        if not first.startswith(HEADER):
            die("unexpected stdin session %r" % first)
        session, run = first, ["bash", "-s"]
    else:
        session, run = "cmd", ["bash", "-c", cmd[len("sudo "):] if cmd.startswith("sudo ") else cmd]
    outcome = next_outcome()
    with open(os.path.join(ROOT, "calls.jsonl"), "a") as fh:
        fh.write(json.dumps({"argv": argv, "stdin": stdin.decode("utf-8", "replace"),
                             "session": session, "outcome": outcome}) + "\n")
    if outcome in ("refused", "reauth", "other"):
        sys.stderr.write(STDERR[outcome])
        sys.exit(RC[outcome])
    if outcome == "empty":
        sys.exit(0)
    if outcome not in ("ok", "partial255", "partial0"):
        die("unknown outcome %r" % outcome)
    span_file = os.environ.get("FAKE_SPAN_FILE")
    if session == HEADER + "span" and span_file:
        out, err, rc = open(span_file, "rb").read(), b"", 0
    else:
        p = subprocess.run(run, input=stdin if run[1] == "-s" else None,
                           stdin=None if run[1] == "-s" else subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err, rc = p.stdout, p.stderr, p.returncode
    if outcome == "ok":
        sys.stdout.buffer.write(out)
        sys.stderr.buffer.write(err)
        sys.exit(rc)
    sys.stdout.buffer.write(out[:len(out) // 2])
    if outcome == "partial255":
        sys.stderr.write(STDERR[outcome])
        sys.exit(RC[outcome])
    sys.exit(0)


if __name__ == "__main__":
    main()
