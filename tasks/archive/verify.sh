#!/usr/bin/env bash
#
# verify.sh — before gs://tn-devnet-benchmark-archive is deleted: does every object in it have an
# identical local copy under benchmark/results/? Read-only on both sides (one bucket listing, one
# object listing, local reads); it deletes and writes nothing but its report.
#
# Layout of the retired archive (bench-lib.sh before the local gate):
#   runs/<run>/results/<rel>         -> benchmark/results/<run>/<rel>
#   runs/<run>/bucket/<name>/<rel>   -> benchmark/results/<run>/bucket/<name>/<rel>
#                                       (the teardown copies each run bucket there before its delete)
# An object matches when the local file has its size and its MD5 (GCS md5Hash, base64).
# "Local-only" lists the files of each archived run that the archive lacks; the archive never
# took genesis*/, tunnel.pid or dot-files (its exclude rule), so those are listed apart.
#
# Usage: tasks/archive/verify.sh [<results root>] [<report>]
#   defaults: <main checkout>/benchmark/results and tasks/archive/verify.md beside this script.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS="${1:-/Users/grant/coding/telcoin/devnet-genesis/benchmark/results}"
REPORT="${2:-${HERE}/verify.md}"
PROJECT="tn-devnet"
BUCKET="tn-devnet-benchmark-archive"

[ -d "${RESULTS}" ] || { echo "❌ ${RESULTS} is not a directory" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

echo "+ gcloud storage buckets list --project ${PROJECT}"
perl -e 'alarm shift; exec @ARGV' 120 gcloud storage buckets list --project="${PROJECT}" \
    --format='table(name,location,labels)' </dev/null > "${tmp}/buckets.txt"
echo "+ gcloud storage ls -r -l gs://${BUCKET}"
perl -e 'alarm shift; exec @ARGV' 600 gcloud storage ls -r -l "gs://${BUCKET}" --project="${PROJECT}" \
    </dev/null > "${tmp}/ls.txt"
echo "+ gcloud storage objects list gs://${BUCKET}/** (name, size, md5)"
perl -e 'alarm shift; exec @ARGV' 600 gcloud storage objects list "gs://${BUCKET}/**" --project="${PROJECT}" \
    --format=json </dev/null > "${tmp}/objects.json"

python3 -I - "${tmp}" "${RESULTS}" "${REPORT}" "${BUCKET}" <<'PY'
import base64, hashlib, json, os, re, sys
from datetime import datetime, timezone

tmp, results, report, bucket = sys.argv[1:5]
objects = json.load(open(os.path.join(tmp, "objects.json")))
ls_lines = open(os.path.join(tmp, "ls.txt")).read().splitlines()
buckets = open(os.path.join(tmp, "buckets.txt")).read().rstrip("\n")

# The long listing, as gcloud prints it: "<size>  <time>  gs://<bucket>/<name>" per object.
ls = {}
for line in ls_lines:
    m = re.match(r"^\s*(\d+)\s+\S+\s+gs://[^/]+/(.+)$", line)
    if m:
        ls[m.group(2)] = int(m.group(1))


def local_path(name):
    """(run, local path relative to results/, kind) for an archive object name; None if unknown."""
    m = re.match(r"^runs/([^/]+)/results/(.+)$", name)
    if m:
        return m.group(1), os.path.join(m.group(1), m.group(2))
    m = re.match(r"^runs/([^/]+)/bucket/(.+)$", name)
    if m:
        return m.group(1), os.path.join(m.group(1), "bucket", m.group(2))
    return None, None


def md5_b64(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


matched, size_bad, md5_bad, missing, unmapped, no_md5 = [], [], [], [], [], []
runs, seen_local, total = set(), set(), 0
for o in objects:
    name = o.get("name") or ""
    size = int(o.get("size") or 0)
    total += size
    run, rel = local_path(name)
    if run is None:
        unmapped.append(name)
        continue
    runs.add(run)
    p = os.path.join(results, rel)
    if not os.path.isfile(p):
        missing.append((name, size))
        continue
    seen_local.add(os.path.normpath(rel))
    lsize = os.path.getsize(p)
    if lsize != size:
        size_bad.append((name, size, lsize))
        continue
    want = o.get("md5_hash") or o.get("md5Hash")
    if not want:
        no_md5.append(name)
        matched.append(name)
        continue
    if md5_b64(p) != want:
        md5_bad.append(name)
        continue
    matched.append(name)

excluded_re = re.compile(r"^(genesis[^/]*/|(.*/)?tunnel\.pid$|(.*/)?\.)")
local_only, local_excluded = [], []
for run in sorted(runs):
    root = os.path.join(results, run)
    for d, _, files in os.walk(root):
        for f in files:
            rel_run = os.path.relpath(os.path.join(d, f), root)
            rel = os.path.normpath(os.path.join(run, rel_run))
            if rel in seen_local:
                continue
            (local_excluded if excluded_re.match(rel_run) else local_only).append(rel)

ls_note = "agrees" if ls == {o["name"]: int(o.get("size") or 0) for o in objects} else \
    "DIFFERS from the JSON listing (%d vs %d objects)" % (len(ls), len(objects))
bad = size_bad or md5_bad or missing or unmapped
verdict = ("SAFE TO DELETE: all %d archive objects have an identical local copy (size%s)."
           % (len(objects), "" if no_md5 else " and MD5")) if objects and not bad else \
          ("NOT SAFE: %d of %d archive objects lack an identical local copy." % (
              len(size_bad) + len(md5_bad) + len(missing) + len(unmapped), len(objects)) if objects
           else "NOTHING TO VERIFY: the bucket lists no object.")

out = ["# gs://%s vs local results" % bucket, "",
       "Generated %s by tasks/archive/verify.sh (read-only). Local root: `%s`." % (
           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), results), "",
       "**Verdict:** " + verdict, "",
       "| count | what |", "|---:|---|",
       "| %d | objects in the bucket (%d bytes, %.1f MiB; runs: %s) |" % (
           len(objects), total, total / 1048576.0, ", ".join(sorted(runs)) or "none"),
       "| %d | matched: local file of the same size and MD5 |" % len(matched),
       "| %d | size mismatch |" % len(size_bad),
       "| %d | MD5 mismatch (same size) |" % len(md5_bad),
       "| %d | missing locally |" % len(missing),
       "| %d | object outside runs/<run>/results or runs/<run>/bucket |" % len(unmapped),
       "| %d | local-only (in results/<run>/, not in the archive) |" % len(local_only),
       "| %d | local-only that the archive's exclude rule never took (genesis*/, tunnel.pid, dot-files) |" % len(local_excluded),
       "", "`gcloud storage ls -r -l` %s (%d objects)." % (ls_note, len(ls)), ""]
if no_md5:
    out += ["%d object(s) had no MD5 (composite uploads); judged by size only." % len(no_md5), ""]
for title, rows in (("Size mismatches (object, archive bytes, local bytes)", ["%s: %d vs %d" % r for r in size_bad]),
                    ("MD5 mismatches", md5_bad),
                    ("Missing locally (object, bytes)", ["%s (%d bytes)" % r for r in missing]),
                    ("Outside the known layout", unmapped),
                    ("Local-only", local_only),
                    ("Local-only, never archived by rule", local_excluded)):
    if rows:
        out += ["## " + title, ""] + ["- `%s`" % r for r in rows] + [""]
out += ["## Buckets in the project", "", "```", buckets, "```", ""]
with open(report, "w") as fh:
    fh.write("\n".join(out))
print(verdict)
print("report: " + report)
PY
