#!/usr/bin/env python3
"""Offline stand-in for gcloud (test_tunnel.py): the calls the RPC tunnel makes.

State lives under $FAKE_ROOT:
  ssh-plan     one outcome per `compute ssh` call, in order (one per line); the last line repeats:
                 fail      exit 255 at once (IAP refused, host unreachable)
                 up:<s>    hold the forward for <s> seconds, then exit 255 (a drop)
                 gone      mark the instance deleted (the file `gone`), then exit 255
  gone         when it exists, `compute instances describe` fails as gcloud does for a deleted
               instance ("... was not found", rc 1); otherwise it prints $FAKE_INSTANCE_ID (default
               4242) for --format=value(id), else RUNNING
  ssh-count    how many `compute ssh` calls were made so far
Every call appends {"argv": [...]} to $FAKE_ROOT/calls.jsonl. `compute ssh` and `compute start-iap-tunnel`
(the long-lived tunnel processes) also append {"argv": [...], "open": [...]} to $FAKE_ROOT/fds.jsonl:
which of the descriptors 5 and 6 they inherited open. `compute start-iap-tunnel` holds its
port for $FAKE_WS_SECS (default 60) seconds. Anything else fails, so a test notices a call shape it
does not model.
"""
import json
import os
import sys
import time

root = os.environ["FAKE_ROOT"]
argv = sys.argv[1:]
with open(os.path.join(root, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": argv}) + "\n")


def path(name):
    return os.path.join(root, name)


if argv[:2] in (["compute", "ssh"], ["compute", "start-iap-tunnel"]):
    inherited = []
    for fd in (5, 6):
        try:
            os.fstat(fd)
            inherited.append(fd)
        except OSError:
            pass
    with open(path("fds.jsonl"), "a") as f:
        f.write(json.dumps({"argv": argv, "open": inherited}) + "\n")


if argv[:2] == ["compute", "ssh"]:
    n = int(open(path("ssh-count")).read()) if os.path.exists(path("ssh-count")) else 0
    with open(path("ssh-count"), "w") as f:
        f.write(str(n + 1))
    plan = [line.strip() for line in open(path("ssh-plan")) if line.strip()] if os.path.exists(path("ssh-plan")) else ["fail"]
    step = plan[min(n, len(plan) - 1)]
    if step == "gone":
        open(path("gone"), "w").close()
    elif step.startswith("up:"):
        time.sleep(float(step[3:]))
    print("ssh: connect to host %s port 22: Connection closed (fake, plan step %r)" % (argv[2], step), file=sys.stderr)
    sys.exit(255)

if argv[:3] == ["compute", "instances", "describe"]:
    if os.path.exists(path("gone")):
        print("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
              " - The resource 'projects/p/zones/z/instances/%s' was not found" % argv[3], file=sys.stderr)
        sys.exit(1)
    print(os.environ.get("FAKE_INSTANCE_ID", "4242") if "--format=value(id)" in argv else "RUNNING")
    sys.exit(0)

if argv[:2] == ["compute", "start-iap-tunnel"]:
    print("Listening on port [%s]." % argv[-1], flush=True)
    time.sleep(float(os.environ.get("FAKE_WS_SECS", "60")))
    sys.exit(0)

print("fake gcloud: unexpected call: %s" % " ".join(argv), file=sys.stderr)
sys.exit(2)
