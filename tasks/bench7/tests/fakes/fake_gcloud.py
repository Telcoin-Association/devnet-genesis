#!/usr/bin/env python3
"""A stand-in for gcloud in the shim tests. Unarmed it prints REACHED and exits 9 (a dry path must never get
here). Armed by $FAKE_DIR/gcloud.json it answers the two calls the fleet-health watch makes:
  compute instances list ...                        -> "list" (a JSON array), or exit 1 when "list" is null
  compute instances get-serial-port-output <inst>   -> "serial"[<inst>], or exit 1
Every call's argv is appended to $FAKE_DIR/gcloud.calls (one JSON array per line), and a `ps` snapshot is
saved under $FAKE_DIR/ps/.
"""
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
