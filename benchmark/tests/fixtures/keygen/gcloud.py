#!/usr/bin/env python3
"""Fake gcloud for benchmark/tests/test_keygen.py (devnet-keygen.sh, fully offline).

Installed as <sandbox>/bin/gcloud. Every node lives in $KG_SB:
  state/<inst>.json  keyed (node-keys and .node-meta written), installed (a telcoin unit exists:
                     finalize ran), address (VALIDATOR_ADDRESS in .node-meta), info (node-info.yaml
                     is on disk and non-empty), data_dir, rpc_http / rpc_ws (what keygen wrote into
                     node-info.yaml), staged (the /tmp paths `sudo cp` copied node-info.yaml to).
                     No file = a fresh VM.
  faults/<inst>.json what this node does wrong (all optional):
                     "fail255": {"<kind>": N}  the next N calls of that kind exit 255, nothing done
                     "crash": {"<kind>": N}    the next N calls of that kind exit 1 with
                                               "gcloud crashed (ReadTimeout)" on stderr, nothing done
                     "keygen_drop": N          the next N keygen calls key the node, print nothing on
                                               stdout and exit 255 (the ssh dropped after the work)
                     "keygen_delay": S         every keygen call sleeps S seconds first
                     "keygen_wait_for": [[inst, kind], ...]  keygen waits (up to "keygen_wait_secs", 30)
                                               until calls of those kinds from those nodes were
                                               made: only possible when the nodes run at once
  calls.jsonl        one JSON object per call, written when it begins: seq, t (start, epoch secs),
                     argv, stdin, inst, kind, cmd (the ssh --command), injected ("255" | "crash" | "")
  env.jsonl          one JSON object per call: seq, environ (the environment this gcloud got)
  gates.jsonl        one JSON object per keygen_wait_for: inst, waited_for, satisfied, secs
  held/<inst>.pid    the pid of a keygen call while it waits (keygen_wait_for)
  lock, seq          flock + counter serialising the files above (KEYGEN_JOBS runs overlap)
Kinds: ext-ip / int-ip (`compute instances describe` for natIP / networkIP), keygen
(setup-node.sh --phase=keygen, the passphrase on stdin), meta (tn_node_meta_get's grep), info
(`sudo test -s <path> && echo __tn_info=1 || echo __tn_info=0`), stage (`sudo cp <info> /tmp/<node>.yaml && sudo chown ...`), scp (the
download; writes the node's node-info.yaml to the local path). Anything else: a message on stderr,
rc 1. v2's refusals are modelled with their real messages: a keyed node answers keygen with
"node-keys already exist at <dir>/node-keys -- refusing to overwrite in non-interactive mode", an
installed one with "A node is already installed (...)".
"""
import fcntl
import json
import os
import re
import shlex
import sys
import time

SB = os.environ["KG_SB"]
FRESH = {"keyed": False, "installed": False, "address": "", "info": False, "data_dir": "",
         "rpc_http": "", "rpc_ws": "", "staged": []}
UNIT = "/etc/systemd/system/telcoin.service"


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
    out = dict(default)
    try:
        with open(path(sub, inst + ".json")) as f:
            out.update(json.load(f))
    except (IOError, OSError, ValueError):
        pass
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
    with open(path(name), "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def flag(tokens, name):
    for k, tok in enumerate(tokens):
        if tok == name and k + 1 < len(tokens):
            return tokens[k + 1]
        if tok.startswith(name + "="):
            return tok[len(name) + 1:]
    return ""


def node_number(inst):
    m = re.search(r"(\d+)$", inst)
    return int(m.group(1)) if m else 0


def node_info(inst, st):
    """The node-info.yaml keygen writes (shape of v2's, values fake)."""
    n = node_number(inst)
    return "\n".join([
        "---",
        "name: node-fake-%d" % n,
        "bls_public_key: fakeBls%d" % n,
        "p2p_info:",
        "  primary:",
        "    network_address: /ip4/203.0.113.%d/udp/49590/quic-v1/p2p/fakePeer%d" % (10 + n, n),
        "    network_key: fakePrimaryKey%d" % n,
        "    rpc: ~",
        "  workers:",
        "    - network_address: /ip4/203.0.113.%d/udp/49594/quic-v1/p2p/fakeWorker%d" % (10 + n, n),
        "      network_key: fakeWorkerKey%d" % n,
        "      rpc:",
        '        http: "%s"' % st["rpc_http"],
        '        ws: "%s"' % st["rpc_ws"],
        'execution_address: "%s"' % st["address"].lower(),
        "proof_of_possession: fakePop%d" % n,
        "",
    ])


def classify(cmd):
    if "__tn_meta_rc" in cmd:
        return "meta"
    if cmd.startswith("sudo test -s "):
        return "info"
    if cmd.startswith("sudo cp "):
        return "stage"
    if "--phase=keygen" in cmd:
        return "keygen"
    return "unhandled"


def fail_keygen(msg):
    sys.stderr.write("ERROR: %s\n" % msg)
    print(json.dumps({"event": "error", "msg": msg}, separators=(",", ":")))
    print('{"event":"done","ok":false,"msg":%s}' % json.dumps(msg))
    return 1


def wait_for(inst, wanted, limit):
    """Block until calls.jsonl holds a call of each (inst, kind) in <wanted>, or <limit> seconds.
    held/<inst>.pid (this process's pid) exists while it waits."""
    t0 = time.time()
    os.makedirs(path("held"), exist_ok=True)
    with open(path("held", inst + ".pid.tmp"), "w") as f:
        f.write(str(os.getpid()))
    os.replace(path("held", inst + ".pid.tmp"), path("held", inst + ".pid"))
    seen = set()
    while True:
        try:
            with open(path("calls.jsonl")) as f:
                seen = {(r["inst"], r["kind"]) for r in (json.loads(line) for line in f if line.strip())}
        except (IOError, OSError, ValueError):
            pass
        ok = all(w in seen for w in wanted)
        if ok or time.time() - t0 >= limit:
            break
        time.sleep(0.05)
    with Locked():
        append("gates.jsonl", {"inst": inst, "waited_for": [list(w) for w in wanted], "satisfied": ok,
                               "secs": round(time.time() - t0, 3)})


def keygen(inst, cmd, data, faults):
    tokens = shlex.split(cmd)
    if tokens[:2] != ["sudo", "bash"] or not tokens[2].endswith("/setup-node.sh"):
        sys.stderr.write("fake gcloud: not a setup-node.sh call: %r\n" % cmd)
        return 1
    if faults.get("keygen_delay"):
        time.sleep(float(faults["keygen_delay"]))
    if faults.get("keygen_wait_for"):
        wait_for(inst, [tuple(w) for w in faults["keygen_wait_for"]], float(faults.get("keygen_wait_secs", 30)))
    st = load("state", inst, FRESH)
    ddir = flag(tokens, "--data-dir") or "/var/lib/telcoin"
    sys.stderr.write("[setup-node] keygen on %s (data dir %s)\n" % (inst, ddir))
    if st["installed"]:
        return fail_keygen("A node is already installed (%s exists), so --phase=keygen does not run. "
                           "Use edit-config.sh to change it, or remove-node.sh first." % UNIT)
    if st["keyed"]:
        return fail_keygen("node-keys already exist at %s/node-keys -- refusing to overwrite in "
                           "non-interactive mode" % st["data_dir"])
    if "--passphrase-stdin" not in tokens or not data.strip("\r\n"):
        return fail_keygen("--passphrase-stdin: no passphrase on stdin")
    st.update(keyed=True, info=True, address=flag(tokens, "--address"), data_dir=ddir,
              rpc_http=flag(tokens, "--rpc-http"), rpc_ws=flag(tokens, "--rpc-ws"))
    with Locked():
        save("state", inst, st)
    if faults.get("keygen_drop", 0) > 0:
        with Locked():
            f = load("faults", inst, {})
            f["keygen_drop"] = f.get("keygen_drop", 0) - 1
            save("faults", inst, f)
        sys.stderr.write("Connection to %s closed by remote host.\n" % inst)
        return 255
    info_path = ddir + "/node-info.yaml"
    for step in ("Running preflight checks and installing dependencies", "Applying node configuration",
                 "Creating system infrastructure", "Generating node keys"):
        print('{"event":"step","msg":%s}' % json.dumps(step))
    print('{"event":"done","ok":true,"phase":"keygen","node_type":"observer","node_info_path":%s,'
          '"keys_dir":%s,"node_info":%s,"msg":"keys generated -- BACK THEM UP before finalizing"}'
          % (json.dumps(info_path), json.dumps(ddir + "/node-keys"), json.dumps(node_info(inst, st))))
    return 0


def main():
    args = sys.argv[1:]
    data = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    record = {"argv": args, "stdin": data, "inst": "", "kind": "unhandled", "cmd": "", "injected": ""}
    fmt = flag(args, "--format")
    if args[:3] == ["compute", "instances", "describe"] and len(args) > 3:
        record.update(inst=args[3], kind="ext-ip" if "natIP" in fmt else "int-ip")
    elif args[:2] == ["compute", "scp"] and len(args) > 3 and ":" in args[2]:
        record.update(inst=args[2].split(":", 1)[0], kind="scp")
    elif args[:2] == ["compute", "ssh"] and len(args) > 2:
        cmd = flag(args, "--command")
        record.update(inst=args[2], kind=classify(cmd), cmd=cmd)
    inst, kind = record["inst"], record["kind"]

    with Locked():
        faults = load("faults", inst, {}) if inst else {}
        for mode, tag in (("fail255", "255"), ("crash", "crash")):
            if faults.get(mode, {}).get(kind, 0) > 0:
                faults[mode][kind] -= 1
                record["injected"] = tag
                save("faults", inst, faults)
                break
        record["seq"] = next_seq()
        record["t"] = time.time()
        append("calls.jsonl", record)
        append("env.jsonl", {"seq": record["seq"], "environ": dict(os.environ)})
    if record["injected"] == "255":
        sys.stderr.write("ssh: connect to host %s port 22: Connection timed out (fake 255)\n" % inst)
        return 255
    if record["injected"] == "crash":
        sys.stderr.write("ERROR: gcloud crashed (ReadTimeout): HTTPSConnectionPool(host='compute.googleapis.com', "
                         "port=443): Read timed out. (read timeout=300) (fake)\n")
        return 1
    if kind == "unhandled":
        sys.stderr.write("fake gcloud: unhandled call: %r\n" % (args,))
        return 1

    n = node_number(inst)
    if kind == "ext-ip":
        print("203.0.113.%d" % (10 + n))
        return 0
    if kind == "int-ip":
        print("198.51.100.%d" % (10 + n))
        return 0
    if kind == "keygen":
        return keygen(inst, record["cmd"], data, faults)

    st = load("state", inst, FRESH)
    info_src = (st["data_dir"] or "/var/lib/telcoin") + "/node-info.yaml"
    if kind == "meta":
        m = re.search(r"\^([A-Z][A-Z0-9_]*)=", record["cmd"])
        key = m.group(1) if m else ""
        if not st["keyed"]:
            print("__tn_meta_rc=2")
            return 0
        values = {"VALIDATOR_ADDRESS": st["address"], "DATA_DIR": st["data_dir"]}
        if key in values:
            print("%s=%s" % (key, values[key]))
            print("__tn_meta_rc=0")
        else:
            print("__tn_meta_rc=1")
        return 0
    if kind == "info":
        # `sudo test -s '<path>' && echo __tn_info=1 || echo __tn_info=0`
        target = shlex.split(record["cmd"])[3]
        print("__tn_info=%d" % (1 if (st["info"] and target == info_src) else 0))
        return 0
    if kind == "stage":
        m = re.match(r"sudo cp '([^']+)' '([^']+)' && sudo chown \$\(whoami\) '([^']+)'$", record["cmd"])
        if not m or m.group(2) != m.group(3):
            sys.stderr.write("fake gcloud: unexpected staging command: %r\n" % record["cmd"])
            return 1
        if not st["info"] or m.group(1) != info_src:
            sys.stderr.write("cp: cannot stat '%s': No such file or directory\n" % m.group(1))
            return 1
        with Locked():
            st = load("state", inst, FRESH)
            st["staged"] = sorted(set(st["staged"]) | {m.group(2)})
            save("state", inst, st)
        return 0
    if kind == "scp":
        remote, local = args[2].split(":", 1)[1], args[3]
        if remote not in st["staged"]:
            sys.stderr.write("scp: %s: No such file or directory\n" % remote)
            return 1
        with open(local, "w") as f:
            f.write(node_info(inst, st))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
