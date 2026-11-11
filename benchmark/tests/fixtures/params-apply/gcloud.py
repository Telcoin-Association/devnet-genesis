#!/usr/bin/env python3
"""Fake gcloud for tests/test_params_apply.py.

`gcloud compute ssh <node> ... --command=...` runs the stdin script with bash on a fake node: the
directory $PA_NODES/<node>, with /usr/local/libexec/telcoin/, /etc/telcoin/, /opt/telcoin/ and
/var/lib/bench-logs moved into it and the node stubs ($PA_NODE_BIN: docker, systemctl, systemd-run,
curl, date, sleep) first on PATH. A file
<node>/iap-refuse-once makes the first call fail the way IAP refuses a tunnel (4033). Every call
appends {"argv", "stdin", "node", "start", "end", "rc"} as one JSON line to $PA_SHIM_LOG.
Any other gcloud command fails (params-apply.sh needs none).
"""
import fcntl
import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]
data = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
start = time.time()
node, out, err, rc = None, "", "", 0
if args[:2] == ["compute", "ssh"] and len(args) > 2:
    node = args[2]
    nd = os.path.join(os.environ["PA_NODES"], node)
    refuse = os.path.join(nd, "iap-refuse-once")
    if not os.path.isdir(nd):
        err, rc = "ERROR: (gcloud.compute.ssh) instance %s not found\n" % node, 1
    elif os.path.exists(refuse):
        os.unlink(refuse)
        err, rc = "ERROR: (gcloud.compute.start-iap-tunnel) Error while connecting [4033: 'not authorized'].\n", 255
    else:
        script = data
        for root in ("/usr/local/libexec/telcoin/", "/etc/telcoin/", "/opt/telcoin/", "/var/lib/bench-logs"):
            script = script.replace(root, nd + root)
        env = dict(os.environ)
        env["PATH"] = os.environ["PA_NODE_BIN"] + os.pathsep + env.get("PATH", "")
        env["STUB_NODE_DIR"] = nd
        env["TMPDIR"] = os.path.join(nd, "tmp")
        p = subprocess.run(["bash", "-s"], input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, universal_newlines=True, timeout=120)
        out, err, rc = p.stdout, p.stderr, p.returncode
else:
    err, rc = "fake gcloud: unexpected command %r\n" % (args,), 3
sys.stdout.write(out)
sys.stderr.write(err)
with open(os.environ["PA_SHIM_LOG"], "a") as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.write(json.dumps({"argv": args, "stdin": data, "node": node, "start": start, "end": time.time(),
                         "rc": rc}) + "\n")
sys.exit(rc)
