#!/usr/bin/env python3
"""A stand-in for benchmark/launch/launch.sh in the shim tests of tasks/bench7/orch-run-chain.sh.

Called as `bash <sandbox>/launch.sh [--dry-run] <env-file> <segment>` (a bash wrapper execs this file).
Reads $FAKE_DIR/launch.json, appends "DRY <seg>" or "LIVE <seg>" to $FAKE_DIR/launch.calls, and saves a
`ps` snapshot under $FAKE_DIR/ps/ (the test checks every command line of the chain's process tree
against launch.sh's pgrep patterns).

launch.json: {"run": <run id>, "dry_rc": {<seg>: rc}, "segments": {<seg>: {"refuse": bool,
  "body": [lines], "end": "rc=<n>" | "LEFT_RUNNING exit=0 pids=1" | null, "alive": bool,
  "manifest": {...} | null}}}
A live call writes <CHAIN_ROOT>/tasks/bench6/<run>/<seg>-fake.log (start line, body, end line when given),
writes the manifest when given, and prints the LAUNCHED line. "alive" leaves a process whose command line
carries the log's marker (its pid goes to $FAKE_DIR/alive.pids so the test can stop it).
"""
import json
import os
import subprocess
import sys
import time


def snapshot(fake):
    d = os.path.join(fake, "ps")
    os.makedirs(d, exist_ok=True)
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], stdout=subprocess.PIPE, universal_newlines=True).stdout
    with open(os.path.join(d, "launch-%d-%d.txt" % (os.getpid(), time.time_ns())), "w") as f:
        f.write(out)


def main():
    fake = os.environ["FAKE_DIR"]
    root = os.environ["CHAIN_ROOT"]
    args = sys.argv[1:]
    dry = bool(args) and args[0] == "--dry-run"
    if dry:
        args = args[1:]
    seg = args[1]
    with open(os.path.join(fake, "launch.json")) as f:
        cfg = json.load(f)
    run = cfg["run"]
    with open(os.path.join(fake, "launch.calls"), "a") as f:
        f.write("%s %s\n" % ("DRY" if dry else "LIVE", seg))
    snapshot(fake)
    if dry:
        print("DRY RUN: nothing is started; token: not checked in a dry run")
        print("  cd %s" % root)
        print("  env BENCH_RUN_ID=%s" % run)
        print("  command: benchmark/fake-driver %s" % seg)
        return int(cfg.get("dry_rc", {}).get(seg, 0))
    s = cfg["segments"][seg]
    if s.get("refuse"):
        print("launch: refused: a fake refusal for %s" % seg, file=sys.stderr)
        return 1
    if s.get("manifest") is not None:
        mdir = os.path.join(root, "benchmark", "results", run)
        os.makedirs(mdir, exist_ok=True)
        with open(os.path.join(mdir, "manifest.json"), "w") as f:
            json.dump(s["manifest"], f)
    marker = "bench6-launch:%s:%s" % (run, seg)
    if s.get("alive"):
        p = subprocess.Popen(["bash", "-c", 'exec -a "$0" sleep 60', "bash launch.sh __segment " + marker],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        pid = p.pid
        with open(os.path.join(fake, "alive.pids"), "a") as f:
            f.write("%d\n" % pid)
    else:
        p = subprocess.Popen(["true"])
        p.wait()
        pid = p.pid
    rel = "tasks/bench6/%s/%s-fake.log" % (run, seg)
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(path, "w") as f:
        f.write("== %s start %s %s pid=%d harness=fake\n" % (seg, now, marker, pid))
        for line in s.get("body", []):
            f.write(line + "\n")
        if s.get("end"):
            f.write("== %s %s %s\n" % (seg, s["end"], now))
    print("LAUNCHED segment=%s run=%s pid=%d harness=fake log=%s" % (seg, run, pid, rel))
    print("  wait for: ^== %s rc=  in %s" % (seg, rel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
