#!/usr/bin/env python3
"""Fake gcloud for benchmark/tests/test_finalize_modes.py (devnet-finalize.sh, fully offline).

Installed as <sandbox>/bin/gcloud. Every node lives in $FIN_SB:
  state/<inst>.json    the node's telcoin unit: installed (bool), active (active | inactive |
                       failed), enabled ("enabled", "disabled", or "" when no unit), nrestarts,
                       container (a running container named telcoin), image, hostname (the
                       network-config `hostname:` line finalize adds). No file = a fresh node:
                       node scripts fetched, keygen done, no unit.
  faults/<inst>.json   what this node does wrong (all optional):
                       "fail255": {"<kind>": N}     the next N calls of that kind exit 255, no output
                       "describe_fails": {"internal"|"external": N}  the next N describes of
                                                    that IP exit 1 with an API error on stderr
                                                    (not a transport fault: never retried)
                       "finalize_fails": true       setup-node.sh's done event says ok:false (rc 1)
                       "nrestarts_after_finalize": N  the unit finalize starts reports NRestarts=N
                       "stop_leaves_failed": true   `systemctl stop` leaves ActiveState=failed (the
                                                    docker client exits 143); only a `systemctl
                                                    reset-failed` in the same probe clears it
                       "container_survives_stop": true
                       start-at only (a fail255 on start-at is a refused connect: nothing runs):
                       "drop_after_send": N         the next N start-at calls run the probe on the
                                                    node, detached, and the ssh returns 255 at once
                       "drop_after_due": N          the next N start-at calls reach nothing and
                                                    return 255 at due + 0.5 s
                       "hang_start_at": S           sleep S s before reaching the node
                       "arrive_late": S             reach the node at due + S s
                       "clock_step": S              the node clock jumps S s forward after the
                                                    probe's first `date +%s` (its late check)
  calls.jsonl          one JSON object per call, written when the call begins: seq, t, argv,
                       stdin, inst, kind, cmd (the ssh --command), pargs (a probe's arguments),
                       key (a .node-meta read), injected255, drop (connect | drop_after_send |
                       drop_after_due | api-rc1 | "")
  node.jsonl           one JSON object (seq, t, inst, argv) per `systemctl` the start-at text runs
  transitions.jsonl    one JSON object per change of a unit's state: seq, t, inst, kind, before,
                       after (each {"active", "enabled", "installed"})
  signals.jsonl        one JSON object (t, inst, kind, signal) per start-at probe killed by a
                       signal (devnet-finalize.sh's deadline), written as the probe dies
  lock, seq            flock + counter serialising the files above (start-at calls overlap)
  run/<inst>/          the node's /run (the start-at text's /run/ paths are moved here)
  nodebin/<inst>/      the node's own commands, first on its PATH: systemctl (and date, with a
                       clock_step), links to this file, which acts as them by its argv[0]
Kinds: describe, scp, stage (`sudo install -d ...`), finalize (setup-node.sh --phase=finalize),
health (wait_healthy's is-active + curl), meta (tn_node_meta_get), and each probe by its
`# tn-probe: <name>` first line: ready, unit, stop, start-check, start-at, service,
network-config, logs, runtime. Every probe is answered from the model above, except start-at:
devnet-finalize.sh's own start-at text runs under bash, its /run/ relocated and its
`systemctl start` the stub's (which starts the unit in state/). Anything else: a message on
stderr, rc 1. $FIN_FIX/network-config.yaml is the network-config every node holds (finalize
appends hostname).
"""
import base64
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time

SB = os.environ["FIN_SB"]
FIX = os.environ["FIN_FIX"]
SHOW = "systemctl show -p ActiveState,SubState,UnitFileState,NRestarts,Result"
PATTERNS = ("bad yaml data", "committee_peers:", "trusted_nodes[", "bootstrap_peers[", "panicked")


class Locked(object):
    def __enter__(self):
        self.f = open(os.path.join(SB, "lock"), "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def path(*parts):
    return os.path.join(SB, *parts)


def load(sub, inst, default):
    try:
        with open(path(sub, inst + ".json")) as f:
            value = json.load(f)
    except (IOError, OSError, ValueError):
        return dict(default)
    out = dict(default)
    out.update(value)
    return out


def save(sub, inst, value):
    os.makedirs(path(sub), exist_ok=True)
    tmp = path(sub, inst + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump(value, f, sort_keys=True)
    os.replace(tmp, path(sub, inst + ".json"))


def next_seq():
    try:
        with open(path("seq")) as f:
            n = int(f.read().strip() or "0")
    except (IOError, OSError, ValueError):
        n = 0
    with open(path("seq"), "w") as f:
        f.write(str(n + 1))
    return n + 1


def append(name, record):
    record["seq"] = next_seq()
    record["t"] = time.time()
    with open(path(name), "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


FRESH = {"installed": False, "active": "inactive", "enabled": "", "nrestarts": 0,
         "container": False, "image": "", "hostname": ""}


def unit_view(st):
    return {"active": st["active"], "enabled": st["enabled"], "installed": st["installed"]}


def change(inst, kind, fn):
    """Apply fn(state) to the node under the lock; log a transition when the unit changed."""
    with Locked():
        st = load("state", inst, FRESH)
        before = unit_view(st)
        fn(st)
        save("state", inst, st)
        if unit_view(st) != before:
            append("transitions.jsonl", {"inst": inst, "kind": kind, "before": before,
                                         "after": unit_view(st)})
        return st


def unit_lines(st):
    if not st["installed"]:
        return ["ActiveState=inactive", "SubState=dead", "UnitFileState=", "NRestarts=0",
                "Result=success"]
    sub = {"active": "running", "failed": "failed"}.get(st["active"], "dead")
    result = "exit-code" if st["active"] == "failed" else "success"
    return ["ActiveState=" + st["active"], "SubState=" + sub, "UnitFileState=" + st["enabled"],
            "NRestarts=%d" % st["nrestarts"], "Result=" + result]


def nc_lines(st):
    with open(os.path.join(FIX, "network-config.yaml"), "rb") as f:
        data = f.read()
    if st["hostname"]:
        data += ('hostname: "%s"\n' % st["hostname"]).encode()
    return ["nc_present=1", "nc_b64=" + base64.b64encode(data).decode()]


def flag(tokens, name):
    """The value after <name> in a setup-node.sh argument list ("" when absent)."""
    for k, tok in enumerate(tokens[:-1]):
        if tok == name:
            return tokens[k + 1]
    return ""


def classify(cmd):
    """(kind, probe script, probe args, .node-meta key) of one ssh --command string."""
    m = re.search(r"# tn-probe: ([a-z-]+)", cmd)
    if m:
        tokens = shlex.split(cmd)
        if tokens[:3] != ["sudo", "bash", "-c"] or len(tokens) < 5 or tokens[4] != "_":
            return "malformed-probe", "", [], ""
        return m.group(1), tokens[3], tokens[5:], ""
    if "__tn_meta_rc" in cmd:
        k = re.search(r"grep -E '\^([A-Z][A-Z0-9_]*)='", cmd)
        return "meta", "", [], k.group(1) if k else ""
    if "--phase=finalize" in cmd:
        return "finalize", "", shlex.split(cmd), ""
    if cmd.startswith("sudo install -d "):
        return "stage", "", [], ""
    if "systemctl is-active" in cmd and "curl" in cmd:
        return "health", "", [], ""
    return "unhandled", "", [], ""


def node_command(name, args):
    """systemctl / date on the fake node $FIN_NODE_INST, for the real start-at text."""
    inst = os.environ["FIN_NODE_INST"]
    if name == "systemctl":
        with Locked():
            append("node.jsonl", {"inst": inst, "argv": [name] + args})
        if len(args) == 2 and args[0] == "start":
            if not load("state", inst, FRESH)["installed"]:
                sys.stderr.write("Failed to start %s.service: Unit %s.service not found.\n" % (args[1], args[1]))
                return 5

            def start(s):
                s.update(active="active", container=True)
            change(inst, "start-at", start)
            return 0
        sys.stderr.write("fake systemctl: unhandled %r\n" % (args,))
        return 1
    if args != ["+%s"]:
        sys.stderr.write("fake date: unhandled %r\n" % (args,))
        return 1
    counter = path("run", inst, ".date-calls")
    with Locked():
        try:
            with open(counter) as f:
                n = int(f.read().strip() or "0") + 1
        except (IOError, OSError, ValueError):
            n = 1
        with open(counter, "w") as f:
            f.write(str(n))
    step = int(load("faults", inst, {}).get("clock_step", 0)) if n > 1 else 0
    print(int(time.time()) + step)
    return 0


def link(target):
    try:
        os.symlink(os.path.abspath(sys.argv[0]), target)
    except FileExistsError:
        pass


def start_at(inst, script, pargs, faults, drop):
    """Run devnet-finalize.sh's start-at text on the fake node; rc as ssh would give it."""
    due = int(pargs[1])

    def killed(signum, frame):
        # No lock here: the signal may land while this process holds it.
        with open(path("signals.jsonl"), "a") as f:
            f.write(json.dumps({"t": time.time(), "inst": inst, "kind": "start-at",
                                "signal": signum}) + "\n")
        os._exit(128 + signum)
    signal.signal(signal.SIGTERM, killed)
    if faults.get("hang_start_at"):
        time.sleep(float(faults["hang_start_at"]))
    if drop == "drop_after_due":
        while time.time() < due + 0.5:
            time.sleep(0.05)
        sys.stderr.write("ssh: connection to %s timed out (fake 255 after due)\n" % inst)
        return 255
    if faults.get("arrive_late"):
        while time.time() < due + float(faults["arrive_late"]):
            time.sleep(0.02)
    rundir, nodebin = path("run", inst), path("nodebin", inst)
    os.makedirs(rundir, exist_ok=True)
    os.makedirs(nodebin, exist_ok=True)
    link(os.path.join(nodebin, "systemctl"))
    if faults.get("clock_step"):
        link(os.path.join(nodebin, "date"))
    if "/run/" not in script:
        sys.stderr.write("fake gcloud: the start-at text no longer uses /run/\n")
        return 1
    argv = ["bash", "-c", script.replace("/run/", rundir + "/"), "_"] + pargs
    env = dict(os.environ, PATH=nodebin + os.pathsep + os.environ["PATH"], FIN_NODE_INST=inst)
    if drop == "drop_after_send":
        subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        sys.stderr.write("ssh: connection to %s closed after the command was sent (fake 255)\n" % inst)
        return 255
    p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       universal_newlines=True)
    sys.stdout.write(p.stdout)
    return p.returncode


def main():
    name = os.path.basename(sys.argv[0])
    if name in ("systemctl", "date"):
        return node_command(name, sys.argv[1:])
    args = sys.argv[1:]
    data = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    record = {"argv": args, "stdin": data, "inst": "", "kind": "unhandled", "cmd": "",
              "pargs": [], "key": "", "injected255": False, "drop": ""}
    script = ""
    if args[:3] == ["compute", "instances", "describe"] and len(args) > 3:
        record.update(inst=args[3], kind="describe")
    elif args[:2] == ["compute", "scp"] and len(args) > 3 and ":" in args[3]:
        inst, dest = args[3].split(":", 1)
        record.update(inst=inst, kind="scp", pargs=[args[2], dest])
    elif args[:2] == ["compute", "ssh"] and len(args) > 2:
        cmd = ""
        for a in args:
            if a.startswith("--command="):
                cmd = a[len("--command="):]
        kind, script, pargs, key = classify(cmd)
        record.update(inst=args[2], kind=kind, cmd=cmd, pargs=pargs, key=key)
    inst, kind = record["inst"], record["kind"]

    with Locked():
        faults = load("faults", inst, {}) if inst else {}
        which = ("external" if "natIP" in " ".join(args) else "internal") if kind == "describe" else ""
        if faults.get("describe_fails", {}).get(which, 0) > 0:
            faults["describe_fails"][which] -= 1
            record["drop"] = "api-rc1"
        elif faults.get("fail255", {}).get(kind, 0) > 0:
            faults["fail255"][kind] -= 1
            record["drop"] = "connect"
        elif kind == "start-at":
            for mode in ("drop_after_send", "drop_after_due"):
                if faults.get(mode, 0) > 0:
                    faults[mode] -= 1
                    record["drop"] = mode
                    break
        if record["drop"]:
            save("faults", inst, faults)
            record["injected255"] = record["drop"] != "api-rc1"
        append("calls.jsonl", record)
    if record["drop"] == "api-rc1":
        sys.stderr.write("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
                         " - fake API fault for %s\n" % inst)
        return 1
    if record["drop"] == "connect":
        sys.stderr.write("ssh: connection to %s closed by remote host (fake 255)\n" % inst)
        return 255
    if kind in ("unhandled", "malformed-probe"):
        sys.stderr.write("fake gcloud: unhandled call: %r\n" % (args,))
        return 1

    if kind == "start-at":
        sys.stdout.flush()
        return start_at(inst, script, record["pargs"], faults, record["drop"])
    st = load("state", inst, FRESH)
    out = []
    if kind == "describe":
        out.append("203.0.113.7" if "natIP" in " ".join(args) else "192.0.2.7")
    elif kind in ("scp", "stage"):
        pass
    elif kind == "finalize":
        tokens = record["pargs"]
        if faults.get("finalize_fails"):
            print('{"event":"error","message":"fake finalize failure"}')
            print('{"event":"done","ok":false}')
            return 1

        def finalize(s):
            s.update(installed=True, active="active", enabled="enabled",
                     nrestarts=int(faults.get("nrestarts_after_finalize", 0)),
                     container=True, image=flag(tokens, "--docker-image"),
                     hostname=flag(tokens, "--advertised-name"))
        change(inst, kind, finalize)
        out += ['{"event":"step","step":"finalize","ok":true}', '{"event":"done","ok":true}']
    elif kind == "health":
        out.append("HEALTHY" if st["active"] == "active" else "INACTIVE:" + st["active"])
    elif kind == "meta":
        values = {"NETWORK": "devnet", "DATA_DIR": "/var/lib/telcoin"}
        if "@" in st["image"]:
            values["DOCKER_IMAGE_DIGEST"] = st["image"].split("@", 1)[1]
        key = record["key"]
        if key in values:
            out += ["%s=%s" % (key, values[key]), "__tn_meta_rc=0"]
        else:
            out.append("__tn_meta_rc=1")
    else:
        pargs = record["pargs"]
        if kind == "ready":
            svc, logdir = pargs[1], pargs[3]
            out += ["setup=1", "keygen=1", "installed=%d" % int(st["installed"]),
                    "logmark=0:-:%s/%s.log" % (logdir, svc),
                    "logmark=0:-:%s/%s-error.log" % (logdir, svc),
                    "jcursor=s=ready-" + inst, "nc=/var/lib/telcoin/network-config"]
            if SHOW in script:
                out += unit_lines(st)
            out += nc_lines(st)
        elif kind == "unit":
            out += unit_lines(st)
        elif kind == "stop":
            def stop(s):
                if "systemctl stop" in script and s["active"] == "active":
                    s["active"] = "failed" if faults.get("stop_leaves_failed") else "inactive"
                    s["container"] = bool(faults.get("container_survives_stop"))
                if "systemctl reset-failed" in script and s["active"] == "failed":
                    s["active"] = "inactive"
            st = change(inst, kind, stop)
            out += ["stop_rc=0", "reset_rc=0"] + unit_lines(st)
            out.append("container=" + ("true" if st["container"] else "false"))
        elif kind == "start-check":
            svc, logdir = pargs[0], pargs[1]
            out += unit_lines(st)
            out += ["logmark=100:42:%s/%s.log" % (logdir, svc),
                    "logmark=0:-:%s/%s-error.log" % (logdir, svc),
                    "jcursor=s=startcheck-" + inst]
        elif kind == "service":
            active = st["active"] if st["installed"] else "inactive"
            out += ["active=" + active, "enabled=" + (st["enabled"] or "not-found"),
                    "nrestarts=%d" % st["nrestarts"]]
        elif kind == "network-config":
            out += nc_lines(st)
        elif kind == "logs":
            svc, cursor = pargs[0], pargs[3]
            out += ["files= /var/log/telcoin/%s.log(skip=0,new-since-gate)" % svc, "journal=12",
                    "journal_from=" + ("after-gate-cursor" if cursor else "this-boot"),
                    "journal_rc=0", "lines=40"]
            out += ["hit=0|%s|" % p for p in PATTERNS]
        elif kind == "runtime":
            running = st["container"] and st["active"] == "active"
            out += ["execstart=/usr/local/libexec/telcoin/tn-start-docker", "mainpid=4242",
                    "launch_cmd=/usr/bin/docker run -i --rm --pull=nev", "launch_pull=1",
                    "launch_ro=1",
                    "container=%s true %d %s" % ("true" if running else "false",
                                                 4343 if running else 0, st["image"]),
                    "env_pids= 4343", "env_hits=0"]
        out.append("__tn_probe_done")
    for line in out:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
