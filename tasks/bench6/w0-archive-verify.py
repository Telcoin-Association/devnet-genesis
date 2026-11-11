#!/usr/bin/env python3
"""w0-archive-verify.py — for each run: every local file under benchmark/results/<run>/ that the archive
rule takes has an object of the same size and MD5 under gs://tn-devnet-benchmark-archive/runs/<run>/results/.
Read-only. Writes tasks/bench6/w0-archive-verify.md. Exit 0 only when every file of every run matches."""
import base64, hashlib, json, os, re, subprocess, sys
from datetime import datetime, timezone

ROOT = "/home/drtnarg/coding/telcoin/devnet-genesis"
BUCKET = "tn-devnet-benchmark-archive"
EXCLUDED = re.compile(r"^(genesis[^/]*/|(.*/)?tunnel\.pid$|(.*/)?\.)")


def md5_b64(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def main(runs):
    lines = ["# bench 6 W0: archive verify (size + MD5)", "",
             "Generated %s by tasks/bench6/w0-archive-verify.py (read-only)." % datetime.now(timezone.utc).strftime("%FT%TZ"), "",
             "| run | local files (rule) | local bytes | objects | matched | size mismatch | md5 mismatch | missing in bucket | no md5 | excluded by rule | bucket-only |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    bad_total = 0
    detail = []
    for run in runs:
        local_root = os.path.join(ROOT, "benchmark/results", run)
        prefix = "runs/%s/results/" % run
        out = subprocess.run(["gcloud", "storage", "objects", "list", "gs://%s/%s**" % (BUCKET, prefix),
                              "--project=tn-devnet", "--format=json(name,size,md5_hash)"],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800)
        if out.returncode != 0:
            detail.append("- %s: object listing failed: %s" % (run, out.stderr.strip()[-300:]))
            bad_total += 1
            continue
        objs = {}
        for o in json.loads(out.stdout or "[]"):
            objs[o["name"][len(prefix):]] = (int(o.get("size", -1)), o.get("md5_hash"))
        n = nbytes = matched = size_bad = md5_bad = missing = nomd5 = excluded = 0
        seen = set()
        for dirpath, _dirs, files in os.walk(local_root):
            for name in files:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, local_root)
                if EXCLUDED.match(rel):
                    excluded += 1
                    if rel in objs:
                        detail.append("- %s: EXCLUDED FILE PRESENT IN BUCKET: %s" % (run, rel))
                        bad_total += 1
                    continue
                n += 1
                size = os.path.getsize(full)
                nbytes += size
                seen.add(rel)
                if rel not in objs:
                    missing += 1
                    detail.append("- %s: missing in bucket: %s" % (run, rel))
                    continue
                osize, omd5 = objs[rel]
                if osize != size:
                    size_bad += 1
                    detail.append("- %s: size %d != %d: %s" % (run, size, osize, rel))
                elif not omd5:
                    nomd5 += 1
                    detail.append("- %s: object has no md5: %s" % (run, rel))
                elif md5_b64(full) != omd5:
                    md5_bad += 1
                    detail.append("- %s: md5 mismatch: %s" % (run, rel))
                else:
                    matched += 1
        bucket_only = sorted(set(objs) - seen)
        for rel in bucket_only[:20]:
            detail.append("- %s: bucket-only (no local file): %s" % (run, rel))
        bad_total += size_bad + md5_bad + missing + nomd5
        lines.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (
            run, n, nbytes, len(objs), matched, size_bad, md5_bad, missing, nomd5, excluded, len(bucket_only)))
    lines += ["", "**Verdict:** %s" % ("every archived file matches by size and MD5" if bad_total == 0 else "%d problems, see below" % bad_total), ""]
    lines += detail[:400]
    report = os.path.join(ROOT, "tasks/bench6/w0-archive-verify.md")
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:8 + len(runs)]))
    print("VERIFY problems=%d report=%s" % (bad_total, report))
    return 0 if bad_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
