#!/usr/bin/env python3
"""orch-prom-export.py — bench 6, orchestrator only: copy a run's node metrics out of the bench Prometheus
while the fleet is up (read-only HTTP range queries through the local forward, one metric at a time).

  tasks/bench6/orch-prom-export.py <out-dir> <start RFC3339> <end RFC3339> [--step 15] [--match REGEX]

One file per metric name: <out-dir>/<metric>.json.gz, the body of /api/v1/query_range (matrix), plus
<out-dir>/INDEX.tsv (metric, series, points, bytes, seconds, status). The teardown's TSDB snapshot stays the
full copy; this export is what the analysis units read without a replay container.
Last line on stdout: PROM-EXPORT metrics=<n> ok=<n> failed=<n> series=<n> points=<n> <UTC>
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PROM = os.environ.get("PROM_URL", "http://localhost:19090")


def main():
    args = sys.argv[1:]
    step = 15
    match = r"^(tn_|reth_db_(table_size|table_pages|table_entries|freelist)$|reth_storage_providers_database_save_blocks)"
    pos = []
    i = 0
    while i < len(args):
        if args[i] == "--step":
            step = int(args[i + 1]); i += 2
        elif args[i] == "--match":
            match = args[i + 1]; i += 2
        else:
            pos.append(args[i]); i += 1
    out, start, end = pos
    os.makedirs(out, exist_ok=True)
    with urllib.request.urlopen(PROM + "/api/v1/label/__name__/values", timeout=30) as r:
        names = [n for n in json.load(r)["data"] if re.search(match, n)]
    ok = failed = series = points = 0
    with open(os.path.join(out, "INDEX.tsv"), "w") as idx:
        idx.write("metric\tseries\tpoints\tgz_bytes\tseconds\tstatus\n")
        for n in names:
            t0 = time.time()
            path = os.path.join(out, n + ".json.gz")
            try:
                url = PROM + "/api/v1/query_range?" + urllib.parse.urlencode(
                    {"query": n, "start": start, "end": end, "step": f"{step}s"})
                with urllib.request.urlopen(url, timeout=180) as r:
                    body = r.read()
                d = json.loads(body)
                if d.get("status") != "success":
                    raise RuntimeError(d.get("error", "not success"))
                res = d["data"]["result"]
                ns, npts = len(res), sum(len(s["values"]) for s in res)
                with gzip.open(path, "wb", compresslevel=6) as g:
                    g.write(body)
                series += ns; points += npts; ok += 1
                idx.write(f"{n}\t{ns}\t{npts}\t{os.path.getsize(path)}\t{time.time() - t0:.1f}\tok\n")
            except Exception as e:  # one metric that fails does not stop the export
                failed += 1
                idx.write(f"{n}\t0\t0\t0\t{time.time() - t0:.1f}\tFAILED {str(e)[:120]}\n")
            idx.flush()
            time.sleep(0.2)
    print(f"PROM-EXPORT metrics={len(names)} ok={ok} failed={failed} series={series} points={points} "
          f"{datetime.now(timezone.utc).strftime('%FT%TZ')}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
