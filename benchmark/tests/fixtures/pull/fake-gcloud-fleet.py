#!/usr/bin/env python3
"""Offline gcloud for the fleet tests of test_pull_logs.py: a few nodes, the run bucket and the
operator's machine, for the whole node-log pull (bench_pull_node_logs over IAP and
bench_pull_node_logs_bucket through the run bucket).

State under $FAKE_ROOT:
  instances.json            [{"name", "zone", "id", "creationTimestamp", "serviceAccounts"}, ...]
  gcs/<bucket>/<object>     the bucket's objects; the bucket exists when its directory does
  nodes/<inst>/             the node: every "/var/" a session names means nodes/<inst>/var/, and
                            nodes/<inst>/container.log is its telcoin container's log (stub-docker.sh)

A call made on the operator's side appends {"argv", "stdin", "session"} to calls.jsonl (session: the
first line of a `sudo bash -s` script, "cmd" for another remote command, "" for a non-ssh call). A
call made inside a node session (the node's own gcloud: FAKE_NODE is set) appends {"node", "argv"}
to node-calls.jsonl instead.

A session runs for real on this machine, as the node would run it, with FAKE_NODE=<inst> and the
test's bin directory (this gcloud, stub sudo and docker) first on PATH: the stdin script under
`bash -s`, another command under `bash -c` (a leading "sudo " dropped). The stdout of a text
session (`# bench-pull: span` or `# bench-pull: bucket`) names the node paths, not the sandbox's.

Knobs (environment):
  FAKE_SSH_FAIL=<inst>[,...]    every session to that node fails as a dropped IAP session (rc 255)
  FAKE_REAUTH=ssh|download|rm   that operator-side call fails as an expired gcloud session does
  FAKE_UPLOAD_FAIL=<text>       a node-side `storage cp -` whose object name contains <text> fails
                                (rc 1, after reading its stdin)
  FAKE_DOWNLOAD=fail|skip:<text>  the operator's `storage cp -r` fails (rc 1) after copying the
                                objects; skip:<text> leaves out the objects whose name contains <text>
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.environ["FAKE_ROOT"]
GCS = os.path.join(ROOT, "gcs")
SCHEME = "gs" + "://"
HEADER = "# bench-pull: "
REAUTH = ("ERROR: (gcloud.%s) There was a problem refreshing your current auth tokens: "
          "Reauthentication failed. cannot prompt during non-interactive execution.\n")


def die(msg, code=1):
    sys.stderr.write(msg + "\n")
    sys.exit(code)


def log(name, entry):
    fd = os.open(os.path.join(ROOT, name), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(entry) + "\n").encode())
    finally:
        os.close(fd)


def split_url(url):
    bucket, _, name = url[len(SCHEME):].partition("/")
    return bucket, name


def objects(bucket, prefix):
    base = os.path.join(GCS, bucket)
    out = {}
    for d, _, files in os.walk(base):
        for f in files:
            p = os.path.join(d, f)
            name = os.path.relpath(p, base).replace(os.sep, "/")
            if name.startswith(prefix):
                out[name] = p
    return out


def flag(argv, name):
    for a in argv:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def instances():
    p = os.path.join(ROOT, "instances.json")
    return json.load(open(p)) if os.path.exists(p) else []


def ssh(argv, pos, stdin):
    inst = pos[2]
    cmd = flag(argv, "--command")
    if cmd is None:
        die("fake gcloud: one --command= expected")
    text = stdin.decode("utf-8", "replace")
    session = text.split("\n", 1)[0] if cmd == "sudo bash -s" else "cmd"
    if cmd == "sudo bash -s" and not session.startswith(HEADER):
        die("fake gcloud: unexpected stdin session %r" % session)
    log("calls.jsonl", {"argv": argv, "stdin": text, "session": session})
    if os.environ.get("FAKE_REAUTH") == "ssh":
        sys.stderr.write(REAUTH % "compute.ssh")
        sys.exit(1)
    if inst in (os.environ.get("FAKE_SSH_FAIL") or "").split(","):
        sys.stderr.write("Connection to compute.googleapis.com closed by remote host.\n")
        sys.exit(255)
    node = os.path.join(ROOT, "nodes", inst)
    if not os.path.isdir(node):
        die("ERROR: (gcloud.compute.ssh) Could not fetch resource: instance %s not found" % inst)
    env = dict(os.environ, FAKE_NODE=inst)
    if cmd == "sudo bash -s":
        run, data = ["bash", "-s"], stdin.replace(b"/var/", (node + "/var/").encode())
    else:
        body = cmd[len("sudo "):] if cmd.startswith("sudo ") else cmd
        run, data = ["bash", "-c", body.replace("/var/", node + "/var/")], None
    p = subprocess.run(run, input=data, stdin=None if data is not None else subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out = p.stdout
    if session in (HEADER + "span", HEADER + "bucket"):
        out = out.replace((node + "/var/").encode(), b"/var/")
    sys.stdout.buffer.write(out)
    sys.stderr.buffer.write(p.stderr)
    sys.exit(p.returncode)


def storage_node(argv, pos, stdin):
    """The node's own gcloud: `storage cp - gs://<bucket>/<object>` only."""
    log("node-calls.jsonl", {"node": os.environ["FAKE_NODE"], "argv": argv})
    if pos[1:3] != ["cp", "-"] or len(pos) != 4 or not pos[3].startswith(SCHEME):
        die("fake gcloud (node): unexpected " + " ".join(argv))
    bucket, name = split_url(pos[3])
    if not os.path.isdir(os.path.join(GCS, bucket)):
        die("ERROR: (gcloud.storage.cp) %s%s not found: 404." % (SCHEME, bucket))
    fail = os.environ.get("FAKE_UPLOAD_FAIL")
    if fail and fail in name:
        die("ERROR: (gcloud.storage.cp) HTTPError 503: upload of %s failed" % name)
    dst = os.path.join(GCS, bucket, name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(stdin)


def storage(argv, pos):
    log("calls.jsonl", {"argv": argv, "stdin": "", "session": ""})
    verb = pos[1]
    if verb == "buckets" and pos[2:3] == ["list"]:
        names = sorted(os.listdir(GCS)) if os.path.isdir(GCS) else []
        print(json.dumps([{"name": b, "labels": {}} for b in names]))
    elif verb == "cp" and "-r" in argv and len(pos) == 4 and pos[2].startswith(SCHEME):
        # cp -r gs://<bucket>/<prefix>/* <dir>/ : each object under <prefix>/ to <dir>/<rest of its name>
        if os.environ.get("FAKE_REAUTH") == "download":
            sys.stderr.write(REAUTH % "storage.cp")
            sys.exit(1)
        bucket, name = split_url(pos[2])
        if not name.endswith("/*"):
            die("fake gcloud: cp -r expects <prefix>/*, got " + pos[2])
        prefix = name[:-1]
        found = objects(bucket, prefix)
        if not found:
            die("ERROR: (gcloud.storage.cp) The following URLs matched no objects or files: " + pos[2])
        mode = os.environ.get("FAKE_DOWNLOAD", "")
        for n, p in sorted(found.items()):
            if mode.startswith("skip:") and mode[5:] in n:
                continue
            out = os.path.join(pos[3], n[len(prefix):])
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copyfile(p, out)
        if mode == "fail":
            die("ERROR: (gcloud.storage.cp) HTTPError 500: download interrupted")
    elif verb == "rm" and len(pos) == 3 and pos[2].startswith(SCHEME) and pos[2].endswith("/**"):
        if os.environ.get("FAKE_REAUTH") == "rm":
            sys.stderr.write(REAUTH % "storage.rm")
            sys.exit(1)
        bucket, name = split_url(pos[2])
        found = objects(bucket, name[:-2])
        if not found:
            die("ERROR: (gcloud.storage.rm) One or more URLs matched no objects.")
        for p in found.values():
            os.remove(p)
    else:
        die("fake gcloud: unexpected " + " ".join(argv))


def main():
    argv = sys.argv[1:]
    stdin = b"" if sys.stdin.isatty() else sys.stdin.buffer.read()
    pos = [a for a in argv if not a.startswith("-") or a == "-"]
    if os.environ.get("FAKE_NODE"):
        if pos[:1] != ["storage"]:
            die("fake gcloud (node): unexpected " + " ".join(argv))
        storage_node(argv, pos, stdin)
    elif pos[:2] == ["compute", "ssh"]:
        ssh(argv, pos, stdin)
    elif pos[:3] == ["compute", "instances", "describe"]:
        log("calls.jsonl", {"argv": argv, "stdin": "", "session": ""})
        for i in instances():
            if i["name"] == pos[3]:
                print(json.dumps(i))
                return
        die("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n - The resource "
            "'projects/x/zones/%s/instances/%s' was not found" % (flag(argv, "--zone"), pos[3]))
    elif pos[:1] == ["storage"]:
        storage(argv, pos)
    else:
        die("fake gcloud: unexpected " + " ".join(argv))


if __name__ == "__main__":
    main()
