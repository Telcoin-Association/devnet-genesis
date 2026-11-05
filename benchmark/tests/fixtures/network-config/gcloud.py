#!/usr/bin/env python3
"""Fake gcloud for benchmark/tests/test_network_config.py (devnet-network-config.sh, fully offline).

Installed as <sandbox>/bin/gcloud. Every node lives under $NETCFG_SB:
  nodes/<inst>/etc/telcoin/.node-meta   the node's metadata (written by the test)
  nodes/<inst>/data/                    its DATA_DIR (the test writes DATA_DIR=<this path> into
                                        .node-meta): node-info.yaml, network-config
  nodes/<inst>/tmp/                     the node's /tmp/tn-network-config* paths, moved here
  nodes/<inst>/unit                     what `systemctl is-active` answers (absent: inactive)
  <file>.owner                          beside any node file: "user:group:mode" (octal), the
                                        owner and mode the fake's install/find model; a file
                                        without one is owned by root:root 0644
  faults/<inst>.json                    {"fail255": {"<kind>": N}} the next N sessions of that
                                        kind exit 255 before anything runs on the node;
                                        {"drop_after_run": {"<kind>": N}} the next N run on the
                                        node, then the session exits 255 with no output;
                                        {"partial255": {"<kind>": N}} the next N run on the
                                        node, print the first part of their output (cut in the
                                        middle of the NC_B64= line when there is one, else half
                                        way) and exit 255, as a session dropped mid-answer;
                                        {"hold": {"<kind>": N}} the next N write their pid to
                                        held/<inst>.<pid> and wait (120 s) before running; on
                                        SIGTERM a held session waits 0.5 s, writes
                                        held/<inst>.<pid>.term ("work=1" when a
                                        tn-network-config.* dir is still in $TMPDIR, else
                                        "work=0") and exits 143
  calls.jsonl                           one JSON object per session: seq, inst, kind, rc, fault,
                                        header (a stdin session's first line), cmd
  lock, seq                             flock + counter serialising calls.jsonl
  nodebin/                              links named sudo, install, find, systemctl to this file,
                                        first on the PATH of every remote command

A session's remote command (--command, or the stdin script of `sudo bash -s`) runs under bash for
real, with /etc/telcoin/ and /tmp/tn-network-config moved into the node's directory. The stubs:
sudo runs its arguments; install -o U -g G -m M -- SRC DST copies and records DST.owner; find
answers only the driver's ownership test (PATH -maxdepth 0 -user U -group G ! -perm /022) from the
.owner record and runs the real find otherwise; systemctl answers is-active from nodes/<inst>/unit.

Kinds: meta (tn_node_meta_get), bls (node-info grep), state (test -f/-e), cat, scp, install,
perm (the ownership find), unit (systemctl is-active), and the stdin sessions by their first-line
header: `# netcfg: read` -> read, `# netcfg: write` -> write. Anything else: rc 1 with a message.
"""
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time

ME = os.path.realpath(__file__)
SB = os.environ.get("NETCFG_SB", "")


def _node_root(inst):
    return os.path.join(SB, "nodes", inst)


def _log(rec):
    with open(os.path.join(SB, "lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        seq_file = os.path.join(SB, "seq")
        seq = int(open(seq_file).read() or "0") + 1 if os.path.exists(seq_file) else 1
        with open(seq_file, "w") as fh:
            fh.write(str(seq))
        rec["seq"] = seq
        with open(os.path.join(SB, "calls.jsonl"), "a") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        fcntl.flock(lock, fcntl.LOCK_UN)


def _take_fault(inst, group, kind):
    """True (and one fewer left) when faults/<inst>.json has a pending <group> fault for <kind>."""
    path = os.path.join(SB, "faults", inst + ".json")
    with open(os.path.join(SB, "lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not os.path.exists(path):
                return False
            with open(path) as fh:
                faults = json.load(fh)
            left = faults.get(group, {}).get(kind, 0)
            if left <= 0:
                return False
            faults[group][kind] = left - 1
            with open(path, "w") as fh:
                json.dump(faults, fh)
            return True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _relocate(text, root):
    return (text.replace("/etc/telcoin/", root + "/etc/telcoin/")
            .replace("/tmp/tn-network-config", root + "/tmp/tn-network-config"))


def classify(cmd, header):
    if header is not None:
        return {"# netcfg: read": "read", "# netcfg: write": "write"}.get(header, "")
    for needle, kind in (("__tn_meta_rc", "meta"), ("^bls_public_key:", "bls"), ("then echo present", "state"),
                         ("sudo cat --", "cat"), ("sudo install -o", "install"), ("sudo find", "perm"),
                         ("systemctl is-active", "unit")):
        if needle in cmd:
            return kind
    return ""


def _opt(args, name):
    for a in args:
        if a.startswith(name + "="):
            return a[len(name) + 1:]
    return None


def gcloud(argv):
    if argv[:2] == ["compute", "scp"]:
        src, target = argv[2], argv[3]
        inst, _, dest = target.partition(":")
        kind, header, cmd, data = "scp", None, "", b""
    elif argv[:2] == ["compute", "ssh"]:
        inst = argv[2]
        cmd = _opt(argv[3:], "--command") or ""
        data = sys.stdin.buffer.read() if cmd == "sudo bash -s" else b""
        header = data.decode("utf-8", "replace").split("\n", 1)[0] if cmd == "sudo bash -s" else None
        kind = classify(cmd, header)
    else:
        sys.stderr.write("fake gcloud: unexpected call %r\n" % (argv,))
        return 1
    root = _node_root(inst)
    rec = {"inst": inst, "kind": kind, "header": header, "cmd": cmd, "fault": ""}
    if not kind or not os.path.isdir(root):
        sys.stderr.write("fake gcloud: unknown session or node (%s, %r)\n" % (inst, header or cmd[:80]))
        rec["rc"] = 1
        _log(rec)
        return 1
    if _take_fault(inst, "fail255", kind):
        sys.stderr.write("Connection closed by 203.0.113.9 port 22\n")
        rec.update(rc=255, fault="fail255")
        _log(rec)
        return 255
    if _take_fault(inst, "hold", kind):
        _hold(inst)
    partial = _take_fault(inst, "partial255", kind)
    if kind == "scp":
        dst = _relocate(dest, root)
        shutil.copyfile(src, dst)
        rc = 0
        out = b""
    else:
        env = dict(os.environ)
        env["PATH"] = os.path.join(SB, "nodebin") + os.pathsep + env.get("PATH", "")
        env["NETCFG_NODE_ROOT"] = root
        script = _relocate(data.decode("utf-8"), root).encode("utf-8") if header is not None else b""
        proc = subprocess.run(["bash", "-c", _relocate(cmd, root)], input=script, cwd=root, env=env,
                              stdout=subprocess.PIPE)
        rc, out = proc.returncode, proc.stdout
    if partial:
        at = out.find(b"NC_B64=")
        cut = at + (out.find(b"\n", at) - at) // 2 if at >= 0 else len(out) // 2
        sys.stdout.buffer.write(out[:cut])
        sys.stdout.flush()
        sys.stderr.write("Connection to 203.0.113.9 closed by remote host.\n")
        rec.update(rc=255, fault="partial255")
        _log(rec)
        return 255
    if _take_fault(inst, "drop_after_run", kind):
        sys.stderr.write("Connection to 203.0.113.9 closed by remote host.\n")
        rec.update(rc=255, fault="drop_after_run")
        _log(rec)
        return 255
    sys.stdout.buffer.write(out)
    sys.stdout.flush()
    rec["rc"] = rc
    _log(rec)
    return rc


def _hold(inst):
    held = os.path.join(SB, "held")
    os.makedirs(held, exist_ok=True)
    mark = os.path.join(held, "%s.%d" % (inst, os.getpid()))

    def on_term(signum, frame):
        time.sleep(0.5)
        tmp = os.environ.get("TMPDIR", "")
        work = any(n.startswith("tn-network-config.") for n in (os.listdir(tmp) if os.path.isdir(tmp) else []))
        with open(mark + ".term", "w") as fh:
            fh.write("work=%d\n" % work)
        os._exit(143)

    signal.signal(signal.SIGTERM, on_term)
    with open(mark, "w") as fh:
        fh.write("%d\n" % os.getpid())
    time.sleep(120)


# --- the node's own commands (nodebin links) ---------------------------------------------------

def _owner(path):
    try:
        with open(path + ".owner") as fh:
            return fh.read().strip()
    except OSError:
        return "root:root:644"


def stub_install(args):
    owner = group = mode = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "-g", "-m"):
            val = args[i + 1]
            if a == "-o":
                owner = val
            elif a == "-g":
                group = val
            else:
                mode = val
            i += 2
            continue
        if a != "--":
            rest.append(a)
        i += 1
    if len(rest) != 2 or not (owner and group and mode):
        sys.stderr.write("install stub: unsupported arguments %r\n" % (args,))
        return 1
    src, dst = rest
    if not os.path.isdir(os.path.dirname(dst)):
        sys.stderr.write("install: cannot create regular file '%s': No such file or directory\n" % dst)
        return 1
    shutil.copyfile(src, dst)
    with open(dst + ".owner", "w") as fh:
        fh.write("%s:%s:%s\n" % (owner, group, mode.lstrip("0") or "0"))
    return 0


def stub_find(args):
    if len(args) == 10 and args[1:3] == ["-maxdepth", "0"] and args[3] == "-user" and args[5] == "-group" \
            and args[7:] == ["!", "-perm", "/022"]:
        path, user, group = args[0], args[4], args[6]
        if not os.path.exists(path):
            sys.stderr.write("find: '%s': No such file or directory\n" % path)
            return 1
        o_user, o_group, o_mode = _owner(path).split(":")
        if o_user == user and o_group == group and not int(o_mode, 8) & 0o022:
            print(path)
        return 0
    path_env = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                               if os.path.realpath(p) != os.path.realpath(os.path.join(SB, "nodebin")))
    real = shutil.which("find", path=path_env)
    os.execv(real, [real] + args)
    return 1


def stub_systemctl(args):
    if len(args) == 2 and args[0] == "is-active":
        try:
            with open(os.path.join(os.environ["NETCFG_NODE_ROOT"], "unit")) as fh:
                state = fh.read().strip()
        except OSError:
            state = "inactive"
        print(state)
        return 0 if state == "active" else 3
    sys.stderr.write("systemctl stub: unsupported %r\n" % (args,))
    return 1


def main():
    name = os.path.basename(sys.argv[0])
    args = sys.argv[1:]
    if name == "sudo":
        os.execvp(args[0], args)
    if name == "install":
        return stub_install(args)
    if name == "find":
        return stub_find(args)
    if name == "systemctl":
        return stub_systemctl(args)
    return gcloud(args)


if __name__ == "__main__":
    sys.exit(main())
