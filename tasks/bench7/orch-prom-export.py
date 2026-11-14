#!/usr/bin/env python3
"""orch-prom-export.py — bench 7, orchestrator only: tasks/bench6/orch-prom-export.py with a completeness check
before the export (bench 6 run 3's export lacked one validator's tn_primary_vote_stage_seconds series and
nobody saw it before the teardown).

  tasks/bench7/orch-prom-export.py <out-dir> <start RFC3339> <end RFC3339> [--step 15] [--match REGEX]
                                   [--manifest benchmark/results/<run>/manifest.json] [--network bench]
                                   [--allow-missing] [--check-only]

The check comes first. For each must-have metric (MUST_HAVE: the series the bench-6 analysis scripts read
most) one instant query at <end>, count by (node) (last_over_time(<metric>{network="<label>"}[<end - start>s])),
and one line:
  EXPORT_CHECK metric=<m> nodes=<n>/<expected> missing=<node,...|-> status=<ok|incomplete|absent|error>
The nodes are the manifest's (.instances, else .zones_used; without --manifest, every node any must-have
metric shows). A metric some node shows must be on every node: in bench 6 the observer carried all twenty
(run r20261114-0000's export). A metric no node shows is "absent" (not on this node build): reported, not
fatal. Any "incomplete" or "error" line makes it exit 3 before anything is written, unless --allow-missing
is given; --check-only stops after the check.

The export, as in bench 6: one file per metric name, <out-dir>/<metric>.json.gz, the body of
/api/v1/query_range (matrix), plus <out-dir>/INDEX.tsv (metric, series, points, bytes, seconds, status).
Then on stdout:
  PROM-EXPORT metrics=<n> ok=<n> failed=<n> series=<n> points=<n> <UTC>
  EXPORT_DONE metrics=<n> series=<n> nodes=<n>
Exit: 0, 1 (a metric failed to export), 2 usage, 3 (the check refused).
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
USAGE = ("usage: tasks/bench7/orch-prom-export.py <out-dir> <start RFC3339> <end RFC3339> [--step 15] [--match REGEX] "
         "[--manifest <manifest.json>] [--network bench] [--allow-missing] [--check-only]")

# The series the bench-6 analysis scripts (benchmark/private/bench6-r20261113-1351/*/scripts/*.py) read most,
# ranked by the number of scripts that query them; histograms by their _count series. The first six are
# named for themselves: the vote stages (the series run 3 lost), the switch gauges, and the persist and
# commit histograms.
MUST_HAVE = (
    "tn_primary_vote_stage_seconds_count",
    "tn_node_switch",
    "tn_engine_persist_duration_seconds_count",
    "tn_engine_persist_wait_seconds_count",
    "tn_reth_persist_commit_seconds_count",
    "tn_reth_persist_save_blocks_seconds_count",
    "tn_engine_executed_transactions_total",
    "tn_engine_busy_milliseconds_total",
    "tn_primary_consensus_exec_lag_rounds",
    "tn_engine_queued_outputs",
    "reth_db_table_pages",
    "reth_db_table_entries",
    "tn_primary_votes_refused_execution_behind_total",
    "tn_primary_committed_round",
    "tn_executor_output_transactions_count",
    "tn_node_execution_backlog_outputs",
    "tn_engine_channel_depth",
    "tn_engine_outputs_executed_total",
    "tn_engine_unpersisted_outputs",
    "tn_engine_commit_interval_seconds_count",
)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(t):
    """RFC3339 (with Z or an offset) or unix seconds, as Prometheus takes them."""
    try:
        return float(t)
    except ValueError:
        pass
    s = t.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def get_json(path, params, timeout):
    url = PROM + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = r.read()
    return body, json.loads(body)


def expected_nodes(manifest_path):
    """The run's node names from the manifest, or None without one."""
    if not manifest_path:
        return None
    with open(manifest_path) as f:
        m = json.load(f)
    nodes = sorted({inst["name"] for inst in (m.get("instances") or []) if inst.get("name")})
    return nodes or sorted(m.get("zones_used") or {})


def check(start, end, network, nodes):
    """One EXPORT_CHECK line per must-have metric; returns the number of incomplete or failed ones."""
    window = max(int(epoch(end) - epoch(start)), 60)
    seen = {}
    errors = {}
    for metric in MUST_HAVE:
        query = 'count by (node) (last_over_time(%s{network="%s"}[%ds]))' % (metric, network, window)
        try:
            _, d = get_json("/api/v1/query", {"query": query, "time": end}, 60)
            if d.get("status") != "success":
                raise RuntimeError(d.get("error", "not success"))
            seen[metric] = sorted({s["metric"].get("node", "") for s in d["data"]["result"]} - {""})
        except Exception as e:  # a check that cannot be made is not a pass
            errors[metric] = str(e)[:120]
    if nodes is None:
        nodes = sorted({n for names in seen.values() for n in names})
    bad = 0
    for metric in MUST_HAVE:
        if metric in errors:
            bad += 1
            print(f"EXPORT_CHECK metric={metric} nodes=?/{len(nodes)} missing=? status=error {errors[metric]}")
            continue
        have = set(seen[metric])
        if not have:
            print(f"EXPORT_CHECK metric={metric} nodes=0/{len(nodes)} missing=- status=absent")
            continue
        missing = [n for n in nodes if n not in have]
        status = "incomplete" if missing else "ok"
        if missing:
            bad += 1
        print(f"EXPORT_CHECK metric={metric} nodes={len(nodes) - len(missing)}/{len(nodes)} "
              f"missing={','.join(missing) if missing else '-'} status={status}")
    return bad


def main():
    args = sys.argv[1:]
    step = 15
    match = r"^(tn_|reth_db_(table_size|table_pages|table_entries|freelist)$|reth_storage_providers_database_save_blocks)"
    manifest = None
    network = None
    allow_missing = check_only = False
    pos = []
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a == "--step":
                step = int(args[i + 1]); i += 2
            elif a == "--match":
                match = args[i + 1]; i += 2
            elif a == "--manifest":
                manifest = args[i + 1]; i += 2
            elif a == "--network":
                network = args[i + 1]; i += 2
            elif a == "--allow-missing":
                allow_missing = True; i += 1
            elif a == "--check-only":
                check_only = True; i += 1
            elif a.startswith("--"):
                raise ValueError("unknown option " + a)
            else:
                pos.append(a); i += 1
        out, start, end = pos
        if epoch(end) <= epoch(start):
            raise ValueError("the end is not after the start")
    except (IndexError, ValueError) as e:
        print(f"{USAGE}  ({e})", file=sys.stderr)
        return 2

    nodes = expected_nodes(manifest)
    if network is None and manifest:
        with open(manifest) as f:
            network = (json.load(f).get("prometheus") or {}).get("network_label")
    network = network or "bench"
    bad = check(start, end, network, nodes)
    if bad and not allow_missing:
        print(f"EXPORT_REFUSED incomplete={bad}: nothing exported (read the EXPORT_CHECK lines; --allow-missing exports anyway)")
        return 3
    if check_only:
        return 0

    os.makedirs(out, exist_ok=True)
    _, d = get_json("/api/v1/label/__name__/values", None, 30)
    names = [n for n in d["data"] if re.search(match, n)]
    ok = failed = series = points = 0
    node_names = set()
    with open(os.path.join(out, "INDEX.tsv"), "w") as idx:
        idx.write("metric\tseries\tpoints\tgz_bytes\tseconds\tstatus\n")
        for n in names:
            t0 = time.time()
            path = os.path.join(out, n + ".json.gz")
            try:
                body, d = get_json("/api/v1/query_range", {"query": n, "start": start, "end": end, "step": f"{step}s"}, 180)
                if d.get("status") != "success":
                    raise RuntimeError(d.get("error", "not success"))
                res = d["data"]["result"]
                ns, npts = len(res), sum(len(s["values"]) for s in res)
                node_names.update(s["metric"]["node"] for s in res if s["metric"].get("node"))
                with gzip.open(path, "wb", compresslevel=6) as g:
                    g.write(body)
                series += ns; points += npts; ok += 1
                idx.write(f"{n}\t{ns}\t{npts}\t{os.path.getsize(path)}\t{time.time() - t0:.1f}\tok\n")
            except Exception as e:  # one metric that fails does not stop the export
                failed += 1
                idx.write(f"{n}\t0\t0\t0\t{time.time() - t0:.1f}\tFAILED {str(e)[:120]}\n")
            idx.flush()
            time.sleep(float(os.environ.get("PROM_EXPORT_PAUSE_SECS", "0.2")))
    print(f"PROM-EXPORT metrics={len(names)} ok={ok} failed={failed} series={series} points={points} {utc_now()}")
    print(f"EXPORT_DONE metrics={ok} series={series} nodes={len(node_names)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
