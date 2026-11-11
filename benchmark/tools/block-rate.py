#!/usr/bin/env python3
"""Rounds/s, blocks/s, tx/s and commit latency per time window, from a run's local artifacts.

Usage:
  block-rate.py (--run DIR | --sampler CSV [--sampler CSV ...])
                [--windows MANIFEST | --from ISO --to ISO | --bucket-min N]
                [--prom-url URL [--prom-selector SEL]] [--format md|json]

Sources (each optional; a column with no source stays empty):
  chain     DIR/blasters/*.json .blocks (columns number, timestamp, epoch, round, tx_count): every
            block the generators saw, de-duplicated by number. blocks/s and tx/s are the blocks
            and their transactions timestamped in the window, per second; committed rounds/s is
            the leader-round advance between consecutive blocks (a new epoch restarts at its
            first block's round).
  sampler   DIR/sampler/<node>.csv or each --sampler CSV (node-sampler.sh: ts_unix, block): per
            node, (last block - first block) / (last ts - first ts) over the window's samples.
            The sampler records no consensus round and no transaction count.
  metrics   DIR/metrics.json prometheus.series (deploy step 15): per node, rounds/s from
            tn_primary_round, committed rounds/s from tn_primary_committed_round (the increase over
            the window's points; a drop, i.e. a new epoch or a restart, and a catch-up jump faster
            than 10x the window's median step add nothing), and commit latency p50 / p95
            as the median of tn_primary_commit_latency_seconds's p50 / p95 points in the window.
  --prom-url the same three series by a range query instead of metrics.json: URL is the
            Prometheus HTTP API base (…/api/v1), SEL a label selector such as {network="bench"},
            basic auth from $BENCH_PROM_AUTH (user:password) when set.

Windows: --windows MANIFEST (default DIR/manifest.json with --run) takes manifest.param_arms[]
({name, begin|start, end}; from `ready` instead of begin when the arm records it, and each
marks[] {label, begin, end} as "mark <arm>/<label>") and .phases[] ({name, start, end}) plus one
"run" window from the first start to the last end; without them, or with --bucket-min N,
N-minute buckets (N = 10) over the data. --from/--to is one window.

Exit status: 0 = report written; 1 = bad arguments or unreadable input; 2 = no data at all.
Stdlib only.
"""
import argparse
import base64
import calendar
import csv
import glob
import json
import math
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ISO_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?(Z|\+00:00)?$")
COLUMNS = (("rounds_per_s", "rounds/s"), ("committed_rounds_per_s", "committed rounds/s"),
           ("blocks_per_s", "blocks/s"), ("tx_per_s", "tx/s"), ("latency_p50_s", "commit latency p50 (s)"),
           ("latency_p95_s", "commit latency p95 (s)"))
SERIES = {"round": "tn_primary_round", "committed": "tn_primary_committed_round",
          "latency": "tn_primary_commit_latency_seconds"}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    m = ISO_RE.match(text.strip())
    if not m:
        raise ValueError("not an ISO-8601 UTC time: %r" % text)
    y, mo, d, h, mi, s, frac, _ = m.groups()
    return calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s))) + (float(frac) if frac else 0.0)


def manifest_windows(path):
    """(windows, note) from manifest.param_arms[] and .phases[] plus a "run" window.

    An arm's window starts at its `ready` (bench 6) when recorded, else at `begin`; each of its
    `marks[]` with a begin and an end is a sub-window "mark <arm>/<label>" after it."""
    with open(path) as fh:
        m = json.load(fh)
    out = []
    for key, label in (("param_arms", "arm"), ("phases", "phase")):
        for w in m.get(key) or []:
            if not isinstance(w, dict):
                continue
            begin, end = w.get("begin") or w.get("start"), w.get("end")
            if key == "param_arms" and w.get("ready"):
                begin = w["ready"]
            if begin and end:
                out.append(("%s %s" % (label, w.get("name") or "?"), parse_iso(begin), parse_iso(end)))
            for mk in (w.get("marks") or []) if key == "param_arms" else []:
                if isinstance(mk, dict) and mk.get("begin") and mk.get("end"):
                    out.append(("mark %s/%s" % (w.get("name") or "?", mk.get("label") or "?"),
                                parse_iso(mk["begin"]), parse_iso(mk["end"])))
    if not out:
        return None, "%s has no param_arms or phases: buckets instead" % os.path.basename(path)
    out.append(("run", min(w[1] for w in out), max(w[2] for w in out)))
    return out, None


def buckets(span, minutes):
    if not span:
        return []
    step = minutes * 60
    t = int(span[0]) // step * step
    out = []
    while t <= span[1]:
        out.append((iso(t)[:16] + "Z", t, t + step))
        t += step
    return out


# --- sources ------------------------------------------------------------------------------------

def read_chain(run):
    """[(number, timestamp, epoch, round, tx_count)] of every block in blasters/*.json, by number."""
    blocks = {}
    for path in sorted(glob.glob(os.path.join(run, "blasters", "*.json"))):
        with open(path) as fh:
            doc = json.load(fh)
        b = doc.get("blocks") if isinstance(doc, dict) else None
        if not isinstance(b, dict) or not b.get("rows"):
            continue
        cols = b.get("columns") or []
        try:
            ix = [cols.index(c) for c in ("number", "timestamp", "epoch", "round", "tx_count")]
        except ValueError:
            continue
        for row in b["rows"]:
            vals = [row[i] for i in ix]
            if all(isinstance(v, (int, float)) for v in vals):
                blocks[int(vals[0])] = tuple(int(v) for v in vals)
    return [blocks[n] for n in sorted(blocks)]


def read_sampler(paths):
    """{node: [(ts, block)]} from node-sampler CSVs (rows without a block are skipped)."""
    out = {}
    for path in paths:
        node = os.path.basename(path)[:-len(".csv")] if path.endswith(".csv") else os.path.basename(path)
        rows = []
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                ts, block = (row.get("ts_unix") or "").strip(), (row.get("block") or "").strip()
                if ts.isdigit() and block.isdigit():
                    rows.append((int(ts), int(block)))
        if rows:
            out[node] = sorted(rows)
    return out


def read_metrics(path):
    """{series key: {node: {query: [(ts, value)]}}} for SERIES from metrics.json."""
    with open(path) as fh:
        doc = json.load(fh)
    series = ((doc.get("prometheus") or {}).get("series") or {})
    out = {}
    for key, name in SERIES.items():
        ent = series.get(name) or {}
        for node, queries in (ent.get("by_node") or {}).items():
            for q, pts in (queries or {}).items():
                clean = [(float(t), float(v)) for t, v in pts or [] if v is not None and not math.isnan(float(v))]
                out.setdefault(key, {}).setdefault(node, {})[q] = sorted(clean)
    return out


def prom_metrics(url, selector, start, end, step=15):
    """The same shape as read_metrics, from a Prometheus range query per series."""
    sel = selector or ""
    queries = {
        ("round", "max"): "max by (node) (tn_primary_round%s)" % sel,
        ("committed", "max"): "max by (node) (tn_primary_committed_round%s)" % sel,
    }
    for q, p in (("p50", 0.5), ("p95", 0.95)):
        queries[("latency", q)] = ("histogram_quantile(%s, sum by (node, le) (rate(tn_primary_commit_latency_seconds_bucket%s[1m])))"
                                   % (p, sel))
    headers = {}
    auth = os.environ.get("BENCH_PROM_AUTH")
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    out = {}
    for (key, q), promql in queries.items():
        t = start
        while t < end:   # Prometheus caps a range query at 11000 points per series
            e = min(end, t + step * 10000)
            qs = urllib.parse.urlencode({"query": promql, "start": t, "end": e, "step": step})
            req = urllib.request.Request(url.rstrip("/") + "/query_range?" + qs, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            if d.get("status") != "success":
                raise ValueError("prometheus: %s" % d.get("error", d.get("status")))
            for res in d["data"]["result"]:
                node = res.get("metric", {}).get("node", "?")
                pts = [(float(ts), float(v)) for ts, v in res.get("values", []) if v not in ("NaN", "+Inf", "-Inf")]
                out.setdefault(key, {}).setdefault(node, {}).setdefault(q, []).extend(pts)
            t = e
    for key in out:
        for node in out[key]:
            for q in out[key][node]:
                out[key][node][q].sort()
    return out


# --- per-window numbers -------------------------------------------------------------------------

def increase_rate(points, start, end):
    """Increase per second of a round gauge over the window's points. A drop (a new epoch, or a
    restart) adds nothing, nor does a step faster than 10x the window's median step (a restarted
    node jumping to the current round as it catches up)."""
    pts = [(t, v) for t, v in points if start <= t < end]
    if len(pts) < 2 or pts[-1][0] <= pts[0][0]:
        return None
    steps = [(b - a, tb - ta) for (ta, a), (tb, b) in zip(pts, pts[1:]) if tb > ta and b >= a]
    rates = [d / dt for d, dt in steps]
    cap = 10 * statistics.median(rates) if rates and statistics.median(rates) > 0 else float("inf")
    return sum(d for d, dt in steps if d / dt <= cap) / (pts[-1][0] - pts[0][0])


def median_in(points, start, end):
    vals = [v for t, v in points if start <= t < end]
    return statistics.median(vals) if vals else None


def chain_window(chain, start, end):
    """(committed rounds/s, blocks/s, tx/s) from the chain's blocks timestamped in [start, end)."""
    secs = end - start
    rows = [i for i, b in enumerate(chain) if start <= b[1] < end]
    if not rows:
        return {"committed_rounds_per_s": None, "blocks_per_s": 0.0 if chain else None,
                "tx_per_s": 0.0 if chain else None, "blocks": 0}
    adv = 0
    for i in rows:
        if i == 0:
            continue
        prev, cur = chain[i - 1], chain[i]
        if cur[0] != prev[0] + 1:
            continue                              # a gap in the generators' view: no delta across it
        adv += cur[3] - prev[3] if cur[2] == prev[2] and cur[3] >= prev[3] else cur[3]
    txs = sum(chain[i][4] for i in rows)
    return {"committed_rounds_per_s": adv / secs, "blocks_per_s": len(rows) / secs, "tx_per_s": txs / secs,
            "blocks": len(rows)}


def sampler_rate(rows, start, end):
    pts = [(t, b) for t, b in rows if start <= t < end]
    if len(pts) < 2 or pts[-1][0] <= pts[0][0]:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])


def report(windows, chain, sampler, metrics, sources, notes):
    nodes = sorted(set(sampler) | {n for k in metrics.values() for n in k})
    doc = {"sources": sources, "notes": notes, "windows": []}
    for name, start, end in windows:
        rows = []
        if chain:
            r = {k: None for k, _ in COLUMNS}
            r.update(chain_window(chain, start, end))
            rows.append(("chain (blasters/*.json)", r))
        for node in nodes:
            m = {k: (metrics.get(k) or {}).get(node) or {} for k in SERIES}
            r = {"rounds_per_s": increase_rate(m["round"].get("max", []), start, end),
                 "committed_rounds_per_s": increase_rate(m["committed"].get("max", []), start, end),
                 "blocks_per_s": sampler_rate(sampler.get(node, []), start, end),
                 "tx_per_s": None,
                 "latency_p50_s": median_in(m["latency"].get("p50", []), start, end),
                 "latency_p95_s": median_in(m["latency"].get("p95", []), start, end)}
            rows.append((node, r))
        doc["windows"].append({"name": name, "start": iso(start), "end": iso(end), "secs": int(end - start),
                               "rows": [dict(source=s, **r) for s, r in rows]})
    return doc


def cell(v):
    if v is None:
        return "–"
    return "%.2f" % v if isinstance(v, float) else str(v)


def to_markdown(doc):
    out = ["# Block and round rate", "", "Sources: %s." % "; ".join(doc["sources"]), ""]
    for n in doc["notes"]:
        out.append("- " + n)
    if doc["notes"]:
        out.append("")
    for w in doc["windows"]:
        out += ["## %s: %s → %s (%d s)" % (w["name"], w["start"], w["end"], w["secs"]), ""]
        out.append("| source | " + " | ".join(h for _, h in COLUMNS) + " |")
        out.append("|--------|" + "|".join("-" * (len(h) + 1) + ":" for _, h in COLUMNS) + "|")
        for r in w["rows"]:
            out.append("| %s | %s |" % (r["source"], " | ".join(cell(r[k]) for k, _ in COLUMNS)))
        out.append("")
    return "\n".join(out)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", metavar="DIR", help="results/<run> directory")
    src.add_argument("--sampler", action="append", metavar="CSV", help="a node-sampler CSV (repeatable)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--windows", metavar="MANIFEST", help="manifest.json: param_arms[] and phases[]")
    g.add_argument("--from", dest="start", metavar="ISO", help="one window from ISO (needs --to)")
    g.add_argument("--bucket-min", type=int, metavar="N", help="N-minute buckets (default 10)")
    p.add_argument("--to", dest="end", metavar="ISO", help="end of the --from window")
    p.add_argument("--prom-url", metavar="URL", help="Prometheus API base (…/api/v1) instead of metrics.json")
    p.add_argument("--prom-selector", default="", metavar="SEL", help='label selector, e.g. {network="bench"}')
    p.add_argument("--format", choices=("md", "json"), default="md")
    a = p.parse_args(argv)
    if (a.start is None) != (a.end is None):
        p.error("--from and --to go together")
    if a.bucket_min is not None and a.bucket_min <= 0:
        p.error("--bucket-min must be positive")
    return a


def main(argv=None):
    a = parse_args(argv)
    try:
        notes, sources = [], []
        chain, metrics = [], {}
        if a.run:
            chain = read_chain(a.run)
            sampler = read_sampler(sorted(glob.glob(os.path.join(a.run, "sampler", "*.csv"))))
            mpath = os.path.join(a.run, "metrics.json")
            if not a.prom_url and os.path.isfile(mpath):
                metrics = read_metrics(mpath)
                sources.append("metrics.json")
        else:
            sampler = read_sampler(a.sampler)
        if chain:
            sources.append("blasters/*.json (%d blocks)" % len(chain))
        if sampler:
            sources.append("sampler CSV (%d node(s))" % len(sampler))
        windows = None
        if a.start:
            windows = [("window", parse_iso(a.start), parse_iso(a.end))]
            if windows[0][2] <= windows[0][1]:
                raise ValueError("--to must be after --from")
        elif a.bucket_min is None:
            mf = a.windows or (os.path.join(a.run, "manifest.json") if a.run else None)
            if mf and os.path.isfile(mf):
                windows, note = manifest_windows(mf)
                if note:
                    notes.append(note)
            elif a.windows:
                raise ValueError("no such manifest: %s" % a.windows)
        if windows is None:
            ts = [b[1] for b in chain] + [t for rows in sampler.values() for t, _ in rows] \
                + [t for k in metrics.values() for n in k.values() for pts in n.values() for t, _ in pts]
            windows = buckets((min(ts), max(ts)) if ts else None, a.bucket_min or 10)
        if a.prom_url and windows:
            metrics = prom_metrics(a.prom_url, a.prom_selector, min(w[1] for w in windows), max(w[2] for w in windows))
            sources.append("Prometheus %s" % a.prom_url)
        if not (chain or sampler or metrics) or not windows:
            print("block-rate: no blocks, sampler rows or metrics to rate", file=sys.stderr)
            return 2
        doc = report(windows, chain, sampler, metrics, sources, notes)
    except (OSError, ValueError, KeyError) as e:
        print("block-rate: %s" % e, file=sys.stderr)
        return 1
    if a.format == "json":
        print(json.dumps(doc, indent=1))
    else:
        print(to_markdown(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
