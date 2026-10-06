#!/usr/bin/env python3
"""Offline stand-in for gcloud (test_teardown_archive.py, test_collect_retry.py).

State lives under $FAKE_ROOT:
  gcs/<bucket>/<object name>   objects; a bucket exists when its directory does
  labels/<bucket>.json         bucket labels
  instances.json               the project's instances (compute instances list/describe/delete)
  scp-attempts                 compute scp attempts so far

Every call appends {"argv": [...], "stdin": "<what it read on stdin>"} to $FAKE_ROOT/calls.jsonl,
so a test can check the order of calls and that a call's stdin was closed (empty).

Knobs (environment):
  FAKE_FAIL=<word>[,<word>...]  fail any call whose argv, joined by spaces, contains a word
  FAKE_DESCRIBE_ERR=<text>      `storage buckets describe` fails with <text> on stderr
  FAKE_TRUNCATE=<suffix>        rsync/cp write an object whose name ends with <suffix> one byte short
  FAKE_SCP=<outcome>[,...]      compute scp outcome per attempt: ok | 4003 | 4033 | 4047 | fail
                                (the last one repeats); a failing attempt leaves a partial file

Storage semantics follow gcloud where the harness depends on them: rsync's --exclude is a
Python regex matched with re.match against the path relative to the source; rsync only adds
or replaces objects; `ls` of a URL that matches nothing fails after listing the rest.
"""
import io
import json
import os
import re
import shutil
import sys
import tarfile

ROOT = os.environ["FAKE_ROOT"]
GCS = os.path.join(ROOT, "gcs")
LABELS = os.path.join(ROOT, "labels")
SCHEME = "gs" + "://"


def log(argv, stdin):
    with open(os.path.join(ROOT, "calls.jsonl"), "a") as fh:
        fh.write(json.dumps({"argv": argv, "stdin": stdin}) + "\n")


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


def compute(args, pos):
    what, verb = pos[1], pos[2]
    if what == "instances":
        state = instances_state()
        if verb == "list":
            print(json.dumps(state))
            return
        name, zone = pos[3], flag(args, "--zone")
        match = [i for i in state if i["name"] == name and i["zone"].split("/")[-1] == zone]
        if not match:
            die("ERROR: (gcloud.compute.instances.%s) instance %s not found" % (verb, name))
        if verb == "describe":
            print(json.dumps(match[0]))
        elif verb == "delete":
            with open(os.path.join(ROOT, "instances.json"), "w") as fh:
                json.dump([i for i in state if i is not match[0]], fh)
        else:
            die("fake gcloud: unexpected compute instances %s" % verb)
    elif what in ("firewall-rules", "disks"):
        if verb == "list":
            print("[]")
        else:
            die("ERROR: not found")
    elif what == "ssh":
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
        compute(argv, pos)
    elif pos[:2] == ["secrets", "get-iam-policy"]:
        print("{}")
    else:
        die("fake gcloud: unexpected: " + joined)


if __name__ == "__main__":
    main()
