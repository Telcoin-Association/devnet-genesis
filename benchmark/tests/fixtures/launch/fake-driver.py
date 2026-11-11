#!/usr/bin/env python3
"""A stand-in for every bench driver that test_launch.py reaches (launch.sh segments, run-arms.sh calls).

Usage: fake-driver.py <driver name> [driver args...]. It appends one JSON line per call to FAKE_LOG
(name, argv, the BENCH_/RUN_ARMS_/PARAMS_APPLY_/LAUNCH_ environment, pid, parent pid, session id),
prints REACHED, then answers from FAKE_SCENARIO: {"<key>": [response, ...]}, the n-th call of a key
taking the n-th response (the default response once the list is used up). Keys: pa:arm-file,
pa:mark, pa:end-mark, pa:close-arm, pa:print-state, blast:fund, blast:run, blast:status, and the
driver name for the rest. A response: rc, out (lines; {arm} and {ready} are filled in), ready_in
(seconds from now for {ready}), sleep (seconds before the exit), status ({node: [root_pct, fatal_db]}),
manifest (top-level keys a run sets), stall (an entry a run appends to commit_stalls), delta (the
schedule's boundary_unix is --earliest-kill + 1 + delta). Blast fund and run keep the run's
manifest.json the way the real driver does for a hand run (fund.run_index, blast.run_index, abort,
blast_runs[]).
"""
import datetime
import json
import os
import sys
import time

PREFIXES = ("BENCH_", "RUN_ARMS_", "PARAMS_APPLY_", "LAUNCH_")


def iso(t):
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key_of(name, argv):
    if name == "params-apply.sh":
        for a in ("--print-state", "--mark", "--end-mark", "--close-arm", "--arm-file"):
            if a in argv:
                return "pa:" + a[2:]
        return "pa:other"
    if name == "benchmark-blast.sh":
        return "blast:" + (argv[0] if argv else "")
    return name


def arg_after(argv, flag, default=""):
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default


def response(key):
    scen = {}
    path = os.environ.get("FAKE_SCENARIO", "")
    if path and os.path.exists(path):
        with open(path) as f:
            scen = json.load(f)
    state = os.path.join(os.environ["FAKE_STATE"], key.replace(":", "_"))
    n = 0
    if os.path.exists(state):
        with open(state) as f:
            n = int(f.read() or 0)
    with open(state, "w") as f:
        f.write(str(n + 1))
    lst = scen.get(key) or []
    return dict(lst[n]) if n < len(lst) else {}


def manifest_path(argv):
    run = arg_after(argv, "--run", os.environ.get("BENCH_RUN_ID", "r-none"))
    return os.path.join("benchmark", "results", run, "manifest.json")


def manifest_edit(argv, fn):
    p = manifest_path(argv)
    m = {}
    if os.path.exists(p):
        with open(p) as f:
            m = json.load(f)
    fn(m)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(m, f)


def nodes(argv):
    p = os.path.join(os.path.dirname(manifest_path(argv)), "nodes.txt")
    if not os.path.exists(p):
        return ["bench-validator-01"]
    with open(p) as f:
        return [l.split()[0] for l in f if l.strip() and not l.lstrip().startswith("#")]


def main():
    name, argv = sys.argv[1], sys.argv[2:]
    key = key_of(name, argv)
    rec = {"t": time.time(), "name": name, "key": key, "argv": argv,
           "env": dict((k, v) for k, v in os.environ.items() if k.startswith(PREFIXES)),
           "pid": os.getpid(), "ppid": os.getppid(), "sid": os.getsid(0)}
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    print("REACHED %s %s" % (name, " ".join(argv)))
    sys.stdout.flush()
    r = response(key)
    rc = int(r.get("rc", 0))
    out = r.get("out")
    idx = os.environ.get("BENCH_RUN_INDEX", "")
    if key == "pa:arm-file" and out is None:
        out = ["ARM_READY {arm} ready={ready} restarted=11 nodes=11"]
    elif key == "pa:print-state" and out is None:
        out = ["ARM_NAME fake"]
    elif key == "blast:status" and out is None:
        st = r.get("status", {})
        out = ["    %s: BENCH_STATUS host=%s ts=%d root_used_pct=%s fatal_db=%s block=100 rss_total_kb=1"
               % (n, n, int(time.time()), st.get(n, [40, 0])[0], st.get(n, [40, 0])[1]) for n in nodes(argv)]
    elif key == "recovery-schedule.py" and out is None:
        b = int(arg_after(argv, "--earliest-kill", "0")) + 1 + int(r.get("delta", 0))
        out = [json.dumps({"epoch": 7, "duration_secs": 1200, "boundary_unix": b})]
    if key == "blast:fund":
        manifest_edit(argv, lambda m: (m.__setitem__("fund", {"run_index": int(idx)}),
                                       m.setdefault("blast_runs", []).append({"action": "fund", "index": int(idx), "rc": rc})))
    elif key == "blast:run":
        def run_edit(m):
            m["abort"] = None
            m["blast"] = {"run_index": int(idx)}
            m.update(r.get("manifest", {}))
            if "stall" in r:
                m.setdefault("commit_stalls", []).append(r["stall"])
            m.setdefault("blast_runs", []).append({"action": "run", "index": int(idx), "rc": rc})
        manifest_edit(argv, run_edit)
    ready = iso(time.time() + float(r.get("ready_in", 0)))
    for line in out or []:
        print(line.replace("{arm}", arg_after(argv, "--arm", "?")).replace("{ready}", ready))
    sys.stdout.flush()
    end = time.time() + float(r.get("sleep", 0))
    while time.time() < end:
        time.sleep(0.05)
    sys.exit(rc)


if __name__ == "__main__":
    main()
