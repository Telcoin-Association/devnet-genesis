#!/usr/bin/env python3
"""Offline stand-in for gcloud (test_teardown_local_gate.py, test_collect_retry.py).

State lives under $FAKE_ROOT:
  gcs/<bucket>/<object name>   objects; a bucket exists when its directory does
  labels/<bucket>.json         bucket labels
  instances.json               the project's instances (compute instances list/describe/delete)
  deleting.json                {"<zone>/<name>": describes left} for instances deleted with --async
  disks.json                   the project's disks (compute disks list/delete; absent = no disk)
  scp-attempts                 compute scp attempts so far
  logspan/<instance>           LOGSPAN lines the `# bench-pull: span` session prints (else a default)
  rotated/<instance>/<file>    the files the `# bench-pull: rotated` session tars (else a default)
  nodes/<instance>/            a sandbox node: its pull sessions really run there (see below)

Every call appends {"argv": [...], "stdin": "<what it read on stdin>"} to $FAKE_ROOT/calls.jsonl,
so a test can check the order of calls and that a call's stdin was closed (empty).

Knobs (environment):
  FAKE_FAIL=<word>[,<word>...]  fail any call whose argv, joined by spaces, contains a word
  FAKE_DESCRIBE_ERR=<text>      `storage buckets describe` fails with <text> on stderr
  FAKE_TRUNCATE=<suffix>        rsync/cp write an object whose name ends with <suffix> one byte short
  FAKE_SCP=<outcome>[,...]      compute scp outcome per attempt: ok | 4003 | 4033 | 4047 | fail
                                (the last one repeats); a failing attempt leaves a partial file
  FAKE_AUTH=fail                `auth print-access-token` fails as an expired session does
  FAKE_REAUTH_SSH=1             every `compute ssh` fails as an expired session does (rc 1)
  FAKE_SSH_FAIL=<text>          a `compute ssh` whose command or stdin script header contains <text>
                                fails as a dropped IAP session does (rc 255)
  FAKE_DESCRIBE_TRANSIENT=<name> `instances describe <name>` fails as an API error does (rc 1, no
                                "not found"), as fixtures/obs/fake-gcloud.py's describe-transient
  FAKE_DELETE_POLLS=<n>|never   an `instances delete --async` leaves the instance STOPPING for <n>
                                describes (default 1), then describe says not found; never = stays

Remote sessions on stdin are told apart by the script's first line: `# bench-pull: span` prints
LOGSPAN lines, `# bench-pull: rotated` writes a tar of gzip files; any other `sudo bash -s`
script gets the recovery-evidence tar (a gzipped tar holding telcoin.journal).
bench-obs's Prometheus snapshot pull (--command="sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots
<name> | gzip -1") gets a gzipped tar of <name>/; a port-forward session (--ssh-flag=-N, the tunnel
supervisor's) is not modelled offline and fails at once as a refused forward does (rc 255).

For an instance with a sandbox nodes/<instance>/, the `# bench-pull:` scripts and every --command
other than `sudo bash -s` run there for real (bash -c <command>, the script on stdin): every
"/var/" in the command and the script means <node>/var/, <node>/bin (the test's sudo and docker
stubs) is first on PATH, and the span's LOGSPAN lines name the node paths, not the sandbox's.
The recovery-evidence script keeps its canned answer.

Storage semantics follow gcloud where the harness depends on them: rsync's --exclude is a
Python regex matched with re.match against the path relative to the source; rsync only adds
or replaces objects; `ls` of a URL that matches nothing fails after listing the rest.
"""
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = os.environ["FAKE_ROOT"]
GCS = os.path.join(ROOT, "gcs")
LABELS = os.path.join(ROOT, "labels")
SCHEME = "gs" + "://"


def log(argv, stdin):
    # One write per call: a tunnel supervisor in the background may log while the teardown does.
    fd = os.open(os.path.join(ROOT, "calls.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps({"argv": argv, "stdin": stdin}) + "\n").encode())
    finally:
        os.close(fd)


def die(msg, code=1):
    sys.stderr.write(msg + "\n")
    sys.exit(code)


def split_url(url):
    rest = url[len(SCHEME):]
    bucket, _, name = rest.partition("/")
    return bucket, name


def objects(bucket, prefix=""):
    """{name: path} of the objects in <bucket> whose name starts with <prefix>."""
    base = os.path.join(GCS, bucket)
    out = {}
    for d, _, files in os.walk(base):
        for f in files:
            p = os.path.join(d, f)
            name = os.path.relpath(p, base).replace(os.sep, "/")
            if name.startswith(prefix):
                out[name] = p
    return out


def put(bucket, name, src):
    if not os.path.isdir(os.path.join(GCS, bucket)):
        die("ERROR: %s%s not found: 404." % (SCHEME, bucket))
    dst = os.path.join(GCS, bucket, name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fh:
        data = fh.read()
    suffix = os.environ.get("FAKE_TRUNCATE", "")
    if suffix and name.endswith(suffix) and data:
        data = data[:-1]
    with open(dst, "wb") as fh:
        fh.write(data)


def flag(args, name):
    for a in args:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def storage(args, pos):
    verb = pos[1]
    if verb == "buckets":
        sub, url = pos[2], (pos[3] if len(pos) > 3 else "")
        bucket = split_url(url)[0] if url else ""
        if sub == "describe":
            if os.environ.get("FAKE_DESCRIBE_ERR"):
                die(os.environ["FAKE_DESCRIBE_ERR"])
            if not os.path.isdir(os.path.join(GCS, bucket)):
                die("ERROR: (gcloud.storage.buckets.describe) %s%s not found: 404." % (SCHEME, bucket))
            print(bucket)
        elif sub == "create":
            if os.path.isdir(os.path.join(GCS, bucket)):
                die("ERROR: (gcloud.storage.buckets.create) HTTPError 409: already exists")
            os.makedirs(os.path.join(GCS, bucket))
        elif sub == "update":
            labels = dict(kv.split("=", 1) for kv in (flag(args, "--update-labels") or "").split(",") if kv)
            os.makedirs(LABELS, exist_ok=True)
            with open(os.path.join(LABELS, bucket + ".json"), "w") as fh:
                json.dump(labels, fh)
        elif sub == "list":
            out = []
            for b in sorted(os.listdir(GCS)) if os.path.isdir(GCS) else []:
                lp = os.path.join(LABELS, b + ".json")
                labels = json.load(open(lp)) if os.path.exists(lp) else {}
                out.append({"name": b, "labels": labels})
            print(json.dumps(out))
        elif sub == "delete":
            if objects(bucket):
                die("ERROR: bucket %s is not empty" % bucket)
            shutil.rmtree(os.path.join(GCS, bucket))
        else:
            die("fake gcloud: unexpected storage buckets %s" % sub)
    elif verb == "rsync":
        if "--delete-unmatched-destination-objects" in args:
            die("fake gcloud: rsync would delete archived objects", 99)
        src, dst = pos[2], pos[3]
        exclude = flag(args, "--exclude")
        recursive = "-r" in args or "-R" in args or "--recursive" in args
        if src.startswith(SCHEME):
            sb, sp = split_url(src)
            sp = sp.rstrip("/")
            items = {(n[len(sp) + 1:] if sp else n): p for n, p in objects(sb, sp + "/" if sp else "").items()}
        else:
            if not os.path.isdir(src):
                die("ERROR: %s does not exist" % src)
            items = {}
            for d, _, files in os.walk(src):
                for f in files:
                    p = os.path.join(d, f)
                    items[os.path.relpath(p, src).replace(os.sep, "/")] = p
        db, dp = split_url(dst)
        dp = dp.rstrip("/")
        for rel, p in sorted(items.items()):
            if not recursive and "/" in rel:
                continue
            if exclude and re.match(exclude, rel):
                continue
            put(db, (dp + "/" if dp else "") + rel, p)
    elif verb == "cp":
        src, dst = pos[2], pos[3]
        if src.startswith(SCHEME):   # cp -r <bucket url>/* <dir>/
            sb, sp = split_url(src)
            sp = sp.rstrip("*").rstrip("/")
            found = objects(sb, sp + "/" if sp else "")
            if not found:
                die("ERROR: (gcloud.storage.cp) The following URLs matched no objects or files: " + src)
            for n, p in found.items():
                rel = n[len(sp) + 1:] if sp else n
                out = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copyfile(p, out)
        else:
            db, dn = split_url(dst)
            put(db, dn, src)
    elif verb == "rm":
        bucket = split_url(pos[2])[0]
        shutil.rmtree(os.path.join(GCS, bucket), ignore_errors=True)
        lp = os.path.join(LABELS, bucket + ".json")
        if os.path.exists(lp):
            os.remove(lp)
    elif verb == "ls":
        long_form = "-l" in args
        missing, total, nbytes = False, 0, 0
        for url in pos[2:]:
            b, name = split_url(url)
            if name.endswith("**"):
                found = objects(b, name[:-2])
            else:
                found = {n: p for n, p in objects(b, name).items() if n == name}
            if not found:
                missing = True
            for n, p in sorted(found.items()):
                size = os.path.getsize(p)
                total += 1
                nbytes += size
                if long_form:
                    print("%10d  2026-10-06T00:00:00Z  %s%s/%s" % (size, SCHEME, b, n))
                else:
                    print("%s%s/%s" % (SCHEME, b, n))
        if long_form and total:
            print("TOTAL: %d objects, %d bytes" % (total, nbytes))
        if missing:
            die("ERROR: (gcloud.storage.ls) One or more URLs matched no objects.")
    else:
        die("fake gcloud: unexpected storage %s" % verb)


def instances_state():
    p = os.path.join(ROOT, "instances.json")
    return json.load(open(p)) if os.path.exists(p) else []


def save_json(name, data):
    with open(os.path.join(ROOT, name), "w") as fh:
        json.dump(data, fh)


def deleting_state():
    p = os.path.join(ROOT, "deleting.json")
    return json.load(open(p)) if os.path.exists(p) else {}


REAUTH_ERR = ("ERROR: (gcloud.auth.print-access-token) There was a problem refreshing your current auth tokens: "
              "Reauthentication failed. cannot prompt during non-interactive execution.\n"
              "Please run:\n\n  $ gcloud auth login\n\nto obtain new credentials.")


def compute(args, pos, stdin):
    what, verb = pos[1], pos[2]
    if what == "instances":
        state = instances_state()
        if verb == "list":
            print(json.dumps(state))
            return
        name, zone = pos[3], flag(args, "--zone")
        if verb == "describe" and name == os.environ.get("FAKE_DESCRIBE_TRANSIENT"):
            die("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
                " - Internal error. Please try again or contact Google Support. (fake)")
        match = [i for i in state if i["name"] == name and i["zone"].split("/")[-1] == zone]
        if not match:
            die("ERROR: (gcloud.compute.instances.%s) Could not fetch resource:\n"
                " - The resource 'projects/p/zones/%s/instances/%s' was not found" % (verb, zone, name))
        key = zone + "/" + name
        deleting = deleting_state()
        if verb == "describe":
            if key in deleting:
                left = deleting[key]
                if left != "never" and left <= 0:
                    del deleting[key]
                    save_json("deleting.json", deleting)
                    save_json("instances.json", [i for i in state if i is not match[0]])
                    die("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
                        " - The resource 'projects/p/zones/%s/instances/%s' was not found" % (zone, name))
                if left != "never":
                    deleting[key] = left - 1
                    save_json("deleting.json", deleting)
            print(json.dumps(match[0]))
        elif verb == "delete":
            if "--async" in args:
                polls = os.environ.get("FAKE_DELETE_POLLS") or "1"
                deleting[key] = polls if polls == "never" else int(polls)
                save_json("deleting.json", deleting)
                match[0]["status"] = "STOPPING"
                save_json("instances.json", state)
                sys.stderr.write("Delete in progress for [%s].\n" % name)
            else:
                save_json("instances.json", [i for i in state if i is not match[0]])
        else:
            die("fake gcloud: unexpected compute instances %s" % verb)
    elif what == "disks":
        p = os.path.join(ROOT, "disks.json")
        disks = json.load(open(p)) if os.path.exists(p) else []
        if verb == "list":
            print(json.dumps(disks))
            return
        name, zone = pos[3], flag(args, "--zone")
        match = [d for d in disks if d["name"] == name and d["zone"].split("/")[-1] == zone]
        if verb != "delete" or not match:
            die("ERROR: (gcloud.compute.disks.%s) The resource 'projects/p/zones/%s/disks/%s' was not found"
                % (verb, zone, name))
        save_json("disks.json", [d for d in disks if d is not match[0]])
    elif what == "firewall-rules":
        if verb == "list":
            print("[]")
        else:
            die("ERROR: not found")
    elif what == "ssh":
        if os.environ.get("FAKE_REAUTH_SSH") == "1":
            die(REAUTH_ERR.replace("auth.print-access-token", "compute.ssh"))
        header = stdin.split("\n", 1)[0].strip()
        cmd = flag(args, "--command") or ""
        broken = os.environ.get("FAKE_SSH_FAIL")
        if broken and (broken in header or broken in cmd):
            die("Connection closed by remote host\nERROR: (gcloud.compute.ssh) [/usr/bin/ssh] exited with "
                "return code [255].", 255)
        if "--ssh-flag=-N" in args:
            die("channel 2: open failed: connect failed: Connection refused\n"
                "ERROR: (gcloud.compute.ssh) [/usr/bin/ssh] exited with return code [255].", 255)
        if cmd.startswith(PROM_SNAPSHOTS):
            prom_snapshot_session(cmd)
            return
        node = os.path.join(ROOT, "nodes", pos[2])
        if os.path.isdir(node) and (header.startswith("# bench-pull:") or cmd != "sudo bash -s"):
            on_node(node, cmd, stdin, header == "# bench-pull: span")
            return
        if header == "# bench-pull: span":
            span_session(pos[2])
            return
        if header == "# bench-pull: rotated":
            rotated_session(pos[2])
            return
        if flag(args, "--command") != "sudo bash -s":
            die("fake gcloud: unexpected ssh command %r" % flag(args, "--command"))
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"journal of " + verb.encode() + b"\n"
            info = tarfile.TarInfo("./telcoin.journal")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        sys.stdout.buffer.write(buf.getvalue())
    elif what == "scp":
        src, dst = pos[2], pos[3]
        p = os.path.join(ROOT, "scp-attempts")
        n = int(open(p).read()) if os.path.exists(p) else 0
        with open(p, "w") as fh:
            fh.write(str(n + 1))
        outcomes = (os.environ.get("FAKE_SCP") or "ok").split(",")
        outcome = outcomes[min(n, len(outcomes) - 1)]
        if outcome == "ok":
            with open(dst, "w") as fh:
                fh.write("copied from %s\n" % src)
            return
        with open(dst, "w") as fh:
            fh.write("partial")
        if outcome == "fail":
            die("ERROR: (gcloud.compute.scp) [/usr/bin/scp] exited with return code [1].")
        die("ERROR: (gcloud.compute.start-iap-tunnel) Error while connecting [%s: 'not authorized']." % outcome)
    else:
        die("fake gcloud: unexpected compute %s" % what)


PROM_SNAPSHOTS = "sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots "


def prom_snapshot_session(cmd):
    """bench-obs's `sudo tar -cf - -C <snapshots> <name> | gzip -1`: a gzipped tar of <name>/ (meta.json
    and one chunk), what the snapshot directory Prometheus wrote for the POST holds."""
    name = cmd[len(PROM_SNAPSHOTS):].split("|", 1)[0].strip()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, data in (("meta.json", b'{"ulid": "01FAKE"}\n'), ("chunks/000001", b"\x00" * 512)):
            info = tarfile.TarInfo(name + "/01FAKE/" + rel)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    sys.stdout.buffer.write(buf.getvalue())


def on_node(node, cmd, stdin, span):
    """Run one session on the sandbox node <node> (see the module docstring); its rc is gcloud's."""
    var = node.rstrip("/") + "/var/"
    env = dict(os.environ, PATH=os.path.join(node, "bin") + os.pathsep + os.environ.get("PATH", ""))
    p = subprocess.run(["bash", "-c", cmd.replace("/var/", var)], input=stdin.replace("/var/", var).encode(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=node)
    out = p.stdout.replace(var.encode(), b"/var/") if span else p.stdout
    sys.stdout.buffer.write(out)
    sys.stderr.buffer.write(p.stderr)
    sys.stdout.flush()
    sys.exit(p.returncode)


def span_session(inst):
    """`# bench-pull: span`: one LOGSPAN line per stream and generation (logspan/<inst>, else a default)."""
    p = os.path.join(ROOT, "logspan", inst)
    if os.path.exists(p):
        sys.stdout.write(open(p).read())
        return
    base = "/var/log/telcoin/"
    print("LOGSPAN %s stream=stdout gen=0 file=%stelcoin.log bytes=4096 "
          "first=2099-12-31T09:00:00.000001Z last=2099-12-31T10:00:00.000001Z" % (inst, base))
    print("LOGSPAN %s stream=stdout gen=1 file=%stelcoin.log.1 bytes=8192 "
          "first=2099-12-31T08:00:00.000001Z last=2099-12-31T08:59:59.000001Z" % (inst, base))
    print("LOGSPAN %s stream=stderr gen=0 file=%stelcoin-error.log bytes=0 first=- last=-" % (inst, base))


def rotated_session(inst):
    """`# bench-pull: rotated`: an uncompressed tar of unit-<stream>.rotated-<N>.log.gz files
    (rotated/<inst>/*, else one default file)."""
    d = os.path.join(ROOT, "rotated", inst)
    if os.path.isdir(d):
        files = [(f, open(os.path.join(d, f), "rb").read()) for f in sorted(os.listdir(d))]
    else:
        files = [("unit-stdout.rotated-1.log.gz",
                  gzip.compress(b"2099-12-31T08:00:00.000001Z  INFO rotated generation of " + inst.encode() + b"\n",
                                mtime=0))]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    sys.stdout.buffer.write(buf.getvalue())


def auth(pos):
    if pos[1:2] != ["print-access-token"]:
        die("fake gcloud: unexpected auth %s" % " ".join(pos[1:]))
    if os.environ.get("FAKE_AUTH") == "fail":
        die(REAUTH_ERR)
    print("fake-access-token")


def main():
    argv = sys.argv[1:]
    stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    log(argv, stdin)
    joined = " ".join(argv)
    for word in (os.environ.get("FAKE_FAIL") or "").split(","):
        if word and word in joined:
            die("ERROR: fake failure (%s)" % word)
    pos = [a for a in argv if not a.startswith("-")]
    if pos[:1] == ["storage"]:
        storage(argv, pos)
    elif pos[:1] == ["compute"]:
        compute(argv, pos, stdin)
    elif pos[:1] == ["auth"]:
        auth(pos)
    elif pos[:2] == ["secrets", "get-iam-policy"]:
        print("{}")
    else:
        die("fake gcloud: unexpected: " + joined)


if __name__ == "__main__":
    main()
