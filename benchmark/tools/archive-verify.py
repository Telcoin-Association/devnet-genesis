#!/usr/bin/env python3
"""The archive rule for a benchmark run's results, and the check that the archive holds them.

Since 2026-10-08 the archive bucket is the canonical copy of every finished run, under
runs/<run>/results/; benchmark/results/<run>/ here is a transient working copy. tools/archive-run.sh
uploads with `gcloud storage rsync` (composite uploads off, so every object carries an MD5) by the
rule this file defines, and runs this file to check the result.

Usage:
  archive-verify.py --run R [--results-root DIR] [--report FILE] [--bucket B] [--project P]
      Every local file under <results root>/R/ that the rule takes must have an object of the same
      size and MD5 (base64) under the run's prefix; an object without an MD5 is a problem, and so is
      any object under the prefix that the rule excludes. Objects with no local file are counted and
      listed, never a problem (the archive keeps what the local copy has pruned). Writes a short
      Markdown report (default <bench>/work/archive/R-verify.md) and prints a summary; the last line is
      `ARCHIVE_VERIFY ok=<0|1> run=R files=<n> bytes=<b> objects=<n> problems=<n> report=<file>`, and
      on success the line before it is `ARCHIVE_REMOTE {"uri", "verified_at", "files", "bytes"}`
      (manifest.archive.remote). One `gcloud storage objects list`; reads nothing else remote.
  archive-verify.py --run R --print-target
      PROJECT=, BUCKET=, URI= and EXCLUDE= lines for archive-run.sh; no gcloud call.
  archive-verify.py --run R --check-dry-run FILE
      FILE is the output of `gcloud storage rsync --dry-run` to the run's prefix: exit 1 when a file
      it would copy is one the rule excludes, or would land outside the prefix. No gcloud call.

The rule takes every file under results/<run>/ except: genesis*/ at the top (node keys), any path
with a component that starts with "." (.DS_Store, temp files), and tunnel*.pid files. EXCLUDE is the
same rule as gcloud's --exclude value: a Python regex matched with re.match against the path
relative to the source. It never starts with "^" (gcloud reads a list-flag value that starts with
"^" as a delimiter spec and then ignores the rule without a word: a 2026-11-10 dry run queued the
node keys for upload) and holds no comma (the flag splits its value at commas).

Project: --project, else the PROJECT_ID the repo's config.sh exports (the harness configuration,
read by bash in a subshell). Bucket: --bucket, else BENCH_ARCHIVE_BUCKET, else <project> plus
ARCHIVE_SUFFIX. Exit status: 0 ok; 1 a problem found (or the dry-run output refused); 2 usage, a
missing results directory, or a project that cannot be read.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(TOOLS)
REPO = os.path.dirname(BENCH)
SCHEME = "gs" + "://"
ARCHIVE_SUFFIX = "-benchmark-archive"
EXCLUDE = r"genesis[^/]*/.*|(.*/)?tunnel[^/]*\.pid$|(.*/)?\..*"
RUN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
WOULD_COPY_RE = re.compile(r"^Would copy (.+) to (\S+)\s*$")
LIST_TIMEOUT = 1800
REPORT_LINES = 200


class UsageError(Exception):
    """A usage or configuration error: exit 2."""


def excluded(rel):
    """True when the archive rule leaves <rel> (a path relative to results/<run>/, "/"-separated) out.
    Written without the regex on purpose: the dry-run check must not share EXCLUDE's mistakes."""
    parts = rel.split("/")
    if len(parts) > 1 and parts[0].startswith("genesis"):
        return True
    if any(p.startswith(".") for p in parts):
        return True
    return parts[-1].startswith("tunnel") and parts[-1].endswith(".pid")


def md5_b64(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii")


def config_project():
    """PROJECT_ID as the repo's config.sh exports it, or None."""
    cfg = os.path.join(REPO, "config.sh")
    if not os.path.isfile(cfg):
        return None
    p = subprocess.run(["bash", "-c", '. "$1" >/dev/null 2>&1; printf "%s" "${PROJECT_ID:-}"', "_", cfg],
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                       universal_newlines=True, timeout=60)
    return p.stdout.strip() or None


def target(args):
    """(project, bucket, prefix, uri) for the run."""
    project = args.project or config_project()
    if not project or not re.match(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$", project):
        raise UsageError("no usable project (got %r): pass --project or check the repo's config.sh" % project)
    bucket = args.bucket or os.environ.get("BENCH_ARCHIVE_BUCKET") or project + ARCHIVE_SUFFIX
    if not re.match(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$", bucket):
        raise UsageError("%r is not a bucket name" % bucket)
    prefix = "runs/%s/results/" % args.run
    return project, bucket, prefix, "%s%s/%s" % (SCHEME, bucket, prefix)


def local_files(root):
    """{rel: path} of the regular files under <root> the rule takes, and the sorted excluded rels."""
    take, skip = {}, []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(d, name)
            if not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if excluded(rel):
                skip.append(rel)
            else:
                take[rel] = full
    return take, skip


def list_objects(bucket, prefix, project, timeout):
    """{rel: (size, md5 or None)} of the objects under <bucket>/<prefix>, from one gcloud call."""
    argv = ["gcloud", "storage", "objects", "list", "%s%s/%s**" % (SCHEME, bucket, prefix),
            "--project=" + project, "--format=json(name,size,md5_hash)"]
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("gcloud storage objects list exited %d: %s"
                           % (p.returncode, (p.stderr.strip().splitlines() or ["no message"])[-1]))
    out = {}
    for o in json.loads(p.stdout or "[]"):
        name = o.get("name") or ""
        if not name.startswith(prefix):
            continue
        size = o.get("size")
        out[name[len(prefix):]] = (int(size) if size is not None else -1, o.get("md5_hash") or None)
    return out


def verify(args):
    project, bucket, prefix, uri = target(args)
    root = os.path.join(args.results_root, args.run)
    if not os.path.isdir(root):
        raise UsageError("%s is not a directory" % root)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    take, skip = local_files(root)
    problems, notes = [], []
    try:
        objs = list_objects(bucket, prefix, project, args.list_timeout)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
        objs = {}
        problems.append("object listing failed: %s" % e)
    counts = dict.fromkeys(("matched", "size", "md5", "missing", "no_md5", "excluded_present"), 0)
    nbytes = 0
    for rel, full in sorted(take.items()):
        size = os.path.getsize(full)
        nbytes += size
        if rel not in objs:
            counts["missing"] += 1
            problems.append("missing in the bucket: %s" % rel)
            continue
        osize, omd5 = objs[rel]
        if osize != size:
            counts["size"] += 1
            problems.append("size %d here, %d in the bucket: %s" % (size, osize, rel))
        elif not omd5:
            counts["no_md5"] += 1
            problems.append("object has no MD5 (a composite upload?): %s" % rel)
        elif md5_b64(full) != omd5:
            counts["md5"] += 1
            problems.append("MD5 differs: %s" % rel)
        else:
            counts["matched"] += 1
    for rel in sorted(objs):
        if excluded(rel):
            counts["excluded_present"] += 1
            problems.append("EXCLUDED FILE IN THE BUCKET (the rule keeps it out): %s" % rel)
    bucket_only = sorted(r for r in objs if r not in take and not excluded(r))
    for rel in bucket_only[:20]:
        notes.append("in the bucket only (no local file): %s" % rel)
    ok = not problems
    lines = ["# Archive verify: %s" % args.run, "",
             "Checked %s by tools/archive-verify.py (size and MD5 of every file the archive rule takes)." % started, "",
             "| local files | local bytes | excluded here | objects | matched | size differs | MD5 differs "
             "| missing | no MD5 | excluded in bucket | bucket only |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
             "| %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (
                 len(take), nbytes, len(skip), len(objs), counts["matched"], counts["size"], counts["md5"],
                 counts["missing"], counts["no_md5"], counts["excluded_present"], len(bucket_only)), "",
             "**Verdict:** %s" % ("every file matches by size and MD5" if ok else "%d problem(s)" % len(problems)), ""]
    lines += ["- " + p for p in problems[:REPORT_LINES]]
    if len(problems) > REPORT_LINES:
        lines.append("- ... and %d more" % (len(problems) - REPORT_LINES))
    lines += ["- " + n for n in notes]
    report = args.report or os.path.join(BENCH, "work", "archive", "%s-verify.md" % args.run)
    os.makedirs(os.path.dirname(os.path.abspath(report)), exist_ok=True)
    with open(report, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("archive verify %s -> %s" % (root, uri))
    print("  local files %d (%d bytes), excluded here %d; objects %d; matched %d" % (
        len(take), nbytes, len(skip), len(objs), counts["matched"]))
    for p in problems[:20]:
        print("  ✗ " + p)
    if len(problems) > 20:
        print("  ✗ ... and %d more (see the report)" % (len(problems) - 20))
    if ok:
        print("ARCHIVE_REMOTE " + json.dumps({"uri": uri, "verified_at": started, "files": len(take), "bytes": nbytes},
                                             sort_keys=True))
    print("ARCHIVE_VERIFY ok=%d run=%s files=%d bytes=%d objects=%d problems=%d report=%s" % (
        1 if ok else 0, args.run, len(take), nbytes, len(objs), len(problems), report))
    return 0 if ok else 1


def check_dry_run(args):
    """Refuse a dry-run listing that would copy an excluded file or land outside the run's prefix."""
    _project, _bucket, _prefix, uri = target(args)
    with open(args.check_dry_run, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    would = bad = outside = 0
    for line in text.splitlines():
        m = WOULD_COPY_RE.match(line.strip())
        if not m:
            continue
        would += 1
        dst = m.group(2)
        if not dst.startswith(uri):
            outside += 1
            print("  ✗ would land outside %s: %s" % (uri, dst))
        elif excluded(dst[len(uri):]):
            bad += 1
            print("  ✗ would copy a file the rule excludes: %s" % dst[len(uri):])
    print("DRYRUN would_copy=%d excluded=%d outside=%d" % (would, bad, outside))
    return 1 if bad or outside else 0


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", required=True, help="the run id (results/<run>/)")
    p.add_argument("--results-root", default=os.path.join(BENCH, "results"), help="default: %(default)s")
    p.add_argument("--report", help="the report file (default <bench>/work/archive/<run>-verify.md)")
    p.add_argument("--bucket", help="the archive bucket (default BENCH_ARCHIVE_BUCKET, else <project>%s)" % ARCHIVE_SUFFIX)
    p.add_argument("--project", help="the project (default: PROJECT_ID from the repo's config.sh)")
    p.add_argument("--list-timeout", type=int, default=LIST_TIMEOUT, help="seconds (default %(default)s)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--print-target", action="store_true", help="print PROJECT=, BUCKET=, URI=, EXCLUDE= and exit")
    g.add_argument("--check-dry-run", metavar="FILE", help="check `gcloud storage rsync --dry-run` output")
    a = p.parse_args(argv)
    if not RUN_RE.match(a.run):
        p.error("--run %r is not a run id" % a.run)
    if a.list_timeout <= 0:
        p.error("--list-timeout must be positive")
    return a


def main(argv=None):
    a = parse_args(argv)
    try:
        if a.print_target:
            project, bucket, _prefix, uri = target(a)
            print("PROJECT=%s\nBUCKET=%s\nURI=%s\nEXCLUDE=%s" % (project, bucket, uri, EXCLUDE))
            return 0
        if a.check_dry_run:
            return check_dry_run(a)
        return verify(a)
    except UsageError as e:
        print("archive-verify: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("archive-verify: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
