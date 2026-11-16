#!/usr/bin/env python3
"""A stand-in for gcloud in the shim tests. Unarmed it prints REACHED and exits 9 (a dry path must never get
here). Armed by $FAKE_DIR/gcloud.json it answers the two calls the fleet-health watch makes:
  compute instances list ...                        -> "list" (a JSON array), or exit 1 when "list" is null
  compute instances get-serial-port-output <inst>   -> "serial"[<inst>], or exit 1
Bench 8, answered armed or not (read-only calls of the chain and the endpoint sampler):
  auth print-access-token  -> "fake-token", or as $FAKE_DIR/auth.json says: {"rc": <n>, "stderr": "<text>"}
  compute ssh <node> ...   -> with $FAKE_DIR/ssh.json {"<node>": "<metrics text>" | null, "sleep": <secs>}: the text
                              padded past the sampler's 1000-series floor, gzip -1 | base64 -w0 as the sampler's
                              remote command prints it; exit 255 for null or a node not listed; REACHED/9 unarmed
Every call's argv is appended to $FAKE_DIR/gcloud.calls (one JSON array per line), and a `ps` snapshot is
saved under $FAKE_DIR/ps/.
"""
import base64
import gzip
import json
import os
import subprocess
import sys
import time


def main():
    fake = os.environ["FAKE_DIR"]
    args = sys.argv[1:]
    with open(os.path.join(fake, "gcloud.calls"), "a") as f:
        f.write(json.dumps(args) + "\n")
    d = os.path.join(fake, "ps")
    os.makedirs(d, exist_ok=True)
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], stdout=subprocess.PIPE, universal_newlines=True).stdout
    with open(os.path.join(d, "gcloud-%d-%d.txt" % (os.getpid(), time.time_ns())), "w") as f:
        f.write(out)
    if args[:2] == ["auth", "print-access-token"]:
        apath = os.path.join(fake, "auth.json")
        acfg = {}
        if os.path.exists(apath):
            with open(apath) as f:
                acfg = json.load(f)
        if int(acfg.get("rc", 0)) != 0:
            sys.stderr.write(acfg.get("stderr", "ERROR: a fake token failure") + "\n")
            return int(acfg["rc"])
        print("fake-token")
        return 0
    spath = os.path.join(fake, "ssh.json")
    if args[:2] == ["compute", "ssh"] and len(args) > 2 and os.path.exists(spath):
        with open(spath) as f:
            scfg = json.load(f)
        time.sleep(float(scfg.get("sleep", 0)))
        text = scfg.get(args[2])
        if text is None:
            sys.stderr.write("ssh: connect to host %s: a fake failure\n" % args[2])
            return 255
        text += "".join('fake_pad_series{i="%d"} 0\n' % i for i in range(1100))
        sys.stdout.write(base64.b64encode(gzip.compress(text.encode(), 1)).decode())
        return 0
    path = os.path.join(fake, "gcloud.json")
    if not os.path.exists(path):
        print("REACHED")
        return 9
    with open(path) as f:
        cfg = json.load(f)
    if args[:3] == ["compute", "instances", "list"]:
        if cfg.get("list") is None:
            print("ERROR: (gcloud.compute.instances.list) a fake failure", file=sys.stderr)
            return 1
        print(json.dumps(cfg["list"]))
        return 0
    if args[:3] == ["compute", "instances", "get-serial-port-output"] and len(args) > 3:
        text = (cfg.get("serial") or {}).get(args[3])
        if text is None:
            return 1
        sys.stdout.write(text)
        return 0
    print("REACHED")
    return 9


if __name__ == "__main__":
    sys.exit(main())
