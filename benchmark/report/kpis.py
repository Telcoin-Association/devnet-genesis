#!/usr/bin/env python3
"""Headline KPIs for a published benchmark run.

compute(combined, metrics, sampler, manifest, windows, chaos_targets) returns
{"kpis": [...], "recovery": dict | None, "caveats": [str]}. Each figure reproduces a row of
the 29 September Hyperdisk report (tn-3 tasks/bench-investigation/overview/
tn-hyperdisk-benchmark.html, computed by scratch-AN-07/s2_table.py, s2_tps.py, s5_prom.py)
from the run's own files:

  combined  tn-blast-combined/v2, from aggregate.py over the blast's blasters
  metrics   tn-bench-gcp-metrics/v1 (GCP 60-s series under .gcp, Prometheus 15-s series under
            .prometheus.series)
  sampler   {instance: [csv.DictReader rows]} from the on-node sampler (load_sampler)
  manifest  tn-bench-manifest/v1 (instance roles, chaos log)
  windows   {"merged": {...}, "all_generators": {...} | None, ...} from windows.py
  floor     optional: the light8 blast of a light-load arm, {name, index, dir, docs, boundaries}
            (docs = its archived tn-blast/v2 documents); see floor_input()

Latency. time_to_land_* and time_to_seen_* are the combined result's latency.ts_ms / seen_ms
(aggregate.py merge_latency over the load generators' histograms; mixed-phase submissions
only). time_to_land_corrected_p50_s adds the 0.5-s whole-second bias (see LAND_FLOOR_BIAS_S).
The floor KPIs pool the light8 blast's own documents with the same method (merge_latency below,
copied from aggregate.py), and floor_by_generator lists each generator's own quantiles; neither
exists when the run had no light blast.

Windows. "all_generators" is [latest mixed start, earliest mixed end), when every load generator
was running; "merged_mixed" is [earliest mixed start, latest mixed end), the window aggregate.py
reports as landed.window_secs; "run" means the whole blast. Per-second chain series are
half-open, as in aggregate.py. GCP, Prometheus and sampler points use inclusive bounds
lo <= t <= hi, as derive-sizing.py summarize() does.

Healthy validators are the manifest's validators minus the chaos targets; "busiest" is the healthy
validator with the highest p95 of that measure over the window.

Command line (offline; aggregate.py from the generator's bench/ dir builds the combined result)::

    python3 benchmark/report/kpis.py --run-dir benchmark/results/<run> [--blast-dir DIR]
        [--floor-blast-dir DIR] [--txgen-bench DIR] [--combined FILE] [--table] [--out FILE]

--blast-dir takes the load KPIs' manifest, metrics and blasters/ from an archived blast-<i>-<UTC>/
(default: the top of the run dir, as make_bundle.py); --floor-blast-dir names the light blast the
floor KPIs read (default: the light8 entry of the manifest's blasts[] -> its blast-<index>-<UTC>/).

Python 3.9+, standard library only.
"""

import argparse
import csv
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

MIB = 1 << 20
GIB = 1 << 30
SUSTAIN_SECS = 60  # aggregate.py SUSTAIN_WINDOW_SECS

W_ALL = "all_generators"
W_MERGED = "merged_mixed"
W_RUN = "run"

HEADLINE_ID = "avg_chain_tps_all_generators"

# Decimals each KPI is published with (0 -> int). round_kpis() applies them.
DECIMALS = {
    "avg_chain_tps_all_generators": 1,
    "best_60s_chain_tps_all_generators": 1,
    "landed_total": 0,
    "blocks_per_sec": 2,
    "time_to_land_p50_s": 2,
    "time_to_land_p95_s": 2,
    "time_to_land_corrected_p50_s": 2,
    "time_to_seen_p50_s": 2,
    "time_to_seen_p95_s": 2,
    "floor_time_to_land_p50_s": 2,
    "floor_time_to_seen_p50_s": 2,
    "commit_latency_p95_s": 2,
    "execution_time_per_output_s": 2,
    "disk_write_p95_mibps_busiest": 1,
    "disk_write_iops_p95_busiest": 0,
    "cpu_p95_pct_busiest": 1,
    "rss_p95_gib_busiest": 2,
    "psi_io_max_pct": 1,
}


# The block timestamp a time-to-land sample is read against is floor(commit_timestamp_ms / 1000):
# the leader header's millisecond creation time cut to the whole second, so every sample reads
# between 0 and 999 ms low, 0.5 s on average (I-3, tasks/bench5-land-time-baseline.md section 5:
# deconvolving bench 4's histogram with U[0, 1) s moved p50 3.30 -> 3.80 s and p95 12.84 -> 13.34 s).
LAND_FLOOR_BIAS_S = 0.5


# Nearest-rank percentile, copied verbatim from tn-transaction-generator bench/derive-sizing.py:25-26
# so every p95 here is the statistic the sizing report and the 29 Sep report publish.
def pct(xs, q):
    xs = sorted(xs); i = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1))))); return xs[i]


def best_window_mean(vals: List[float], width: int) -> Optional[float]:
    """Highest mean over any `width` consecutive seconds (aggregate.py best_window_mean), or None
    when there are fewer than `width` samples: no such window exists. aggregate.py returns the
    plain mean of a shorter series, which would publish a short window as a best-`width`-s figure
    (windows.best_60s_tps returns None there too)."""
    if not vals or len(vals) < width:
        return None
    cur = best = sum(vals[:width])
    for i in range(width, len(vals)):
        cur += vals[i] - vals[i - width]
        best = max(best, cur)
    return best / width


# Histogram pooling, copied from tn-transaction-generator bench/aggregate.py (hist_quantile,
# hist_saturated, merge_hist, merge_latency) so the floor KPIs pool a light blast's documents
# exactly as aggregate.py pools the load's into combined.latency.

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def hist_quantile(bounds, counts, q):
    total = sum(counts)
    if total <= 0 or not bounds:
        return None
    rank = q * total
    cum = 0
    for i, c in enumerate(counts):
        if c <= 0:
            continue
        if cum + c >= rank:
            if i >= len(bounds):
                return float(bounds[-1])
            lo = 0.0 if i == 0 else float(bounds[i - 1])
            hi = float(bounds[i])
            return lo + (hi - lo) * max(0.0, min(1.0, (rank - cum) / c))
        cum += c
    return float(bounds[-1])


def hist_saturated(counts, q):
    total = sum(counts)
    return total > 0 and counts[-1] > 0 and q * total > total - counts[-1]


def merge_hist(hists):
    """Summed histogram, or None; differing bounds raise ValueError (aggregate.py refuses too)."""
    hists = [h for h in hists if h and h.get("bounds_ms") is not None]
    if not hists:
        return None
    bounds = list(hists[0]["bounds_ms"])
    counts = [0] * (len(bounds) + 1)
    for h in hists:
        if list(h["bounds_ms"]) != bounds:
            raise ValueError("latency histogram bounds differ (%s vs %s)" % (h["bounds_ms"], bounds))
        hc = list(h.get("counts") or [])
        if len(hc) != len(counts):
            raise ValueError("latency histogram has %d counts, expected %d" % (len(hc), len(counts)))
        counts = [a + b for a, b in zip(counts, hc)]
    return {"bounds_ms": bounds, "counts": counts}


def merge_latency(parts, hist):
    """parts: [(weight, {"p50","p95","p99","mean"})]; one live part passes through, several are
    interpolated from the summed histogram (aggregate.py merge_latency)."""
    parts = [(w, q) for w, q in parts if q]
    if not parts:
        return {}
    live = [(w, q) for w, q in parts if w > 0] or parts
    if len(live) == 1:
        return dict(live[0][1])
    out, saturated = {}, False
    for key, qv in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
        est = hist_quantile(hist["bounds_ms"], hist["counts"], qv) if hist else None
        if est is None:
            vals = [q[key] for _, q in live if _is_num(q.get(key))]
            est = max(vals) if vals else None
            saturated = saturated or any(q.get("saturated") is True for _, q in live)
        else:
            saturated = saturated or hist_saturated(hist["counts"], qv)
        if est is not None:
            out[key] = round(est, 3)
    means = [(w, q["mean"]) for w, q in live if _is_num(q.get("mean"))]
    wsum = sum(w for w, _ in means)
    if wsum > 0:
        out["mean"] = round(sum(w * m for w, m in means) / wsum, 3)
    out["saturated"] = saturated
    return out


def pooled_latency(docs: List[dict]) -> dict:
    """{"ts_ms": {...}, "seen_ms": {...}} over tn-blast/v2 documents, as aggregate.py builds
    combined.latency: each document's latency.<key> weighted by totals.landed_own, quantiles from
    the sum of every type's latency_hist_<ts|seen> (mixed-phase submissions only)."""
    weights = [(d.get("totals") or {}).get("landed_own") for d in docs]
    weights = [w if _is_num(w) else 0 for w in weights]
    lats = [d.get("latency") or {} for d in docs]
    out = {}
    for key, hkey in (("ts_ms", "latency_hist_ts"), ("seen_ms", "latency_hist_seen")):
        by_type = {}
        for d in docs:
            for name, t in (d.get("types") or {}).items():
                if isinstance(t, dict) and t.get(hkey):
                    by_type.setdefault(name, []).append(t[hkey])
        # aggregate.py sums each type across documents, then the types.
        hist = merge_hist([merge_hist(hs) for hs in by_type.values()])
        out[key] = merge_latency(list(zip(weights, (l.get(key) for l in lats))), hist)
    return out


# ---------------------------------------------------------------- time and loaders

def iso_to_unix(ts: str) -> int:
    """'2026-09-29T18:12:05Z' (or any ISO-8601 with offset) -> unix seconds."""
    d = datetime.datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp())


def unix_to_iso(t: Optional[float]) -> Optional[str]:
    if t is None:
        return None
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_sampler(directory: str) -> Dict[str, List[dict]]:
    """{instance: rows} from <directory>/<instance>.csv files written by the on-node sampler."""
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.csv"))):
        with open(path, newline="") as f:
            out[os.path.basename(path)[:-len(".csv")]] = list(csv.DictReader(f))
    return out


def load_blasters(directory: str) -> List[dict]:
    """Per-blaster result documents (schema `tn-blast/*`) in name order; a combined file
    (`tn-blast-combined/*`) sitting in the same directory is ignored."""
    docs = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("tn-blast/") \
                and isinstance(doc.get("run"), dict):
            docs.append(doc)
    return docs


# ---------------------------------------------------------------- chaos log

_BOUNCE_RE = re.compile(r"\brestart\b")
_DOWN_RE = re.compile(r"\bkill\b|\bstop\b|\bpause\b")
_UP_RE = re.compile(r"\bstart\b")


def _chaos_kind(action: str) -> Optional[str]:
    """'down' (docker kill, systemctl stop, lag-pause), 'up' (systemctl start, lag-unpause),
    'bounce' (systemctl restart: down and straight back up), or None."""
    a = (action or "").lower()
    if "unpause" in a:
        return "up"
    if _BOUNCE_RE.search(a):
        return "bounce"
    if _DOWN_RE.search(a):
        return "down"
    if _UP_RE.search(a):
        return "up"
    return None


def chaos_events(manifest: dict) -> List[dict]:
    """manifest.chaos entries ({ts, node, action, note, rc}) that succeeded, oldest first, as
    {ts_unix, ts, node, kind, action}."""
    out = []
    for e in (manifest or {}).get("chaos") or []:
        if not isinstance(e, dict) or e.get("rc") not in (0, None) or not e.get("ts") or not e.get("node"):
            continue
        kind = _chaos_kind(e.get("action"))
        if kind is None:
            continue
        try:
            ts_unix = iso_to_unix(e["ts"])
        except ValueError:
            continue
        out.append({"ts_unix": ts_unix, "ts": unix_to_iso(ts_unix), "node": e["node"], "kind": kind,
                    "action": e.get("action")})
    out.sort(key=lambda e: e["ts_unix"])
    return out


def chaos_targets_from_manifest(manifest: dict) -> List[str]:
    """Instances the harness took down and held down (docker kill, systemctl stop, lag-pause), in
    order of the first such event. A plain `systemctl restart` (the observer bounce) is not a target."""
    seen = []
    for e in chaos_events(manifest):
        if e["kind"] == "down" and e["node"] not in seen:
            seen.append(e["node"])
    return seen


# ---------------------------------------------------------------- series access

def _window(windows: dict, name: str) -> Optional[Tuple[int, int]]:
    w = (windows or {}).get("merged" if name == W_MERGED else "all_generators")
    if not w or w.get("start_unix") is None or w.get("end_unix") is None:
        return None
    return int(w["start_unix"]), int(w["end_unix"])


def _per_second(combined: dict, column: str, lo: int, hi: int) -> Optional[List[float]]:
    """combined.series.per_second[column] for each second in [lo, hi); missing seconds are zero."""
    s = (combined or {}).get("series") or {}
    cols = s.get("per_second_columns") or []
    if column not in cols or s.get("per_second_t0_unix") is None:
        return None
    if "s" not in cols:
        return None
    ci, si, t0 = cols.index(column), cols.index("s"), s["per_second_t0_unix"]
    by = {t0 + r[si]: r[ci] for r in s.get("per_second") or []}
    return [by.get(t, 0) for t in range(lo, hi)]


def _gcp_values(metrics: dict, node: str, key: str, lo: int, hi: int) -> List[float]:
    s = ((metrics or {}).get("gcp") or {}).get(node, {}).get(key) or {}
    return [v for t, v in s.get("points") or [] if v is not None and lo <= t <= hi]


def _prom(metrics: dict, name: str) -> dict:
    return (((metrics or {}).get("prometheus") or {}).get("series") or {}).get(name) or {}


def _prom_points(metrics: dict, name: str, key: str, node: str) -> List[List[float]]:
    return [[t, v] for t, v in ((_prom(metrics, name).get("by_node") or {}).get(node) or {}).get(key) or []
            if v is not None and v == v]


def _sampler_values(sampler: dict, node: str, column: str, lo: int, hi: int) -> List[float]:
    out = []
    for r in (sampler or {}).get(node) or []:
        ts, v = r.get("ts_unix"), r.get(column)
        if ts in (None, "") or v in (None, ""):
            continue
        try:
            t, x = int(float(ts)), float(v)
        except ValueError:
            continue
        if lo <= t <= hi:
            out.append(x)
    return out


# ---------------------------------------------------------------- KPI records

def _kpi(kid, label, short_label, unit, window, source, method, value=None, rng=None) -> dict:
    k = {"id": kid, "label": label, "short_label": short_label}
    if rng is not None:
        k["range"] = [rng[0], rng[1]]
    else:
        k["value"] = value
    k.update({"unit": unit, "window": window, "source": source, "method": method, "provenance": "computed"})
    return k


def _round(x, nd: int):
    if x is None:
        return None
    q = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
    return int(q) if nd == 0 else float(q)


def round_kpis(kpis: List[dict]) -> List[dict]:
    """Copies of `kpis` with value / range rounded half-up to DECIMALS (2 for unknown ids)."""
    out = []
    for k in kpis:
        k = dict(k)
        nd = DECIMALS.get(k.get("id"), 2)
        if "range" in k and k["range"] is not None:
            k["range"] = [_round(x, nd) for x in k["range"]]
        if "value" in k:
            k["value"] = _round(k["value"], nd)
        out.append(k)
    return out


def headline_id(kpis: List[dict]) -> Optional[str]:
    ids = [k.get("id") for k in kpis or []]
    if HEADLINE_ID in ids:
        return HEADLINE_ID
    return ids[0] if ids else None


# ---------------------------------------------------------------- KPI groups

def _chain_kpis(combined: dict, windows: dict, caveats: List[str]) -> List[dict]:
    out = []
    w = _window(windows, W_ALL)
    chain = _per_second(combined, "chain_tx", *w) if w else None
    if not w:
        caveats.append("all-generators window undefined (mixed phases never all overlapped): "
                       "average and best-60-s chain throughput not computed")
    elif chain is None:
        caveats.append("combined.series.per_second has no chain_tx column: chain throughput not computed")
    else:
        secs = w[1] - w[0]
        out.append(_kpi(
            "avg_chain_tps_all_generators", "Average chain throughput, all load generators running",
            "Avg chain TPS", "tx/s", W_ALL, "combined.series.per_second[chain_tx]",
            f"Chain transactions per block-timestamp second, summed over the {secs}-s window when every load "
            "generator was in its mixed phase and divided by its length.",
            value=sum(chain) / max(secs, 1)))
        best = best_window_mean(chain, SUSTAIN_SECS)
        if best is None:
            caveats.append(f"the all-generators window is {secs} s, shorter than {SUSTAIN_SECS} s: "
                           f"best-{SUSTAIN_SECS}-s chain throughput not computed")
        else:
            out.append(_kpi(
                "best_60s_chain_tps_all_generators", "Best 60 seconds, all load generators running",
                "Best 60 s TPS", "tx/s", W_ALL, "combined.series.per_second[chain_tx]",
                "Highest mean chain tx/s over any 60 consecutive seconds inside the all-generators window "
                "(aggregate.py best_window_mean).",
                value=best))

    landed = ((combined or {}).get("totals") or {}).get("landed_chain")
    if landed is None:
        caveats.append("combined.totals.landed_chain missing: landed total not computed")
    else:
        out.append(_kpi(
            "landed_total", "Transactions landed over the whole blast", "Landed tx", "tx", W_RUN,
            "combined.totals.landed_chain",
            "Sum of tx_count over every block the load generators saw during the blast, own and foreign "
            "transactions alike.",
            value=landed))

    w = _window(windows, W_MERGED)
    blocks = (combined or {}).get("blocks") or {}
    cols = blocks.get("columns") or []
    if w and "timestamp" in cols:
        ti = cols.index("timestamp")
        n = sum(1 for r in blocks.get("rows") or [] if w[0] <= r[ti] < w[1])
        out.append(_kpi(
            "blocks_per_sec", "Blocks per second", "Blocks/s", "blocks/s", W_MERGED,
            "combined.blocks.rows[timestamp]",
            "Chain blocks whose timestamp falls in the merged mixed window, divided by its length "
            "(aggregate.py landed.capacity.blocks_per_sec over the same window).",
            value=n / max(w[1] - w[0], 1)))
    else:
        caveats.append("merged window or combined.blocks rows missing: blocks per second not computed")

    lat = ((combined or {}).get("latency") or {}).get("ts_ms") or {}
    for kid, q, label, short in (("time_to_land_p50_s", "p50", "Time to land, median", "Land p50"),
                                 ("time_to_land_p95_s", "p95", "Time to land, p95", "Land p95")):
        if lat.get(q) is None:
            caveats.append(f"combined.latency.ts_ms.{q} missing: {kid} not computed")
            continue
        out.append(_kpi(
            kid, label, short, "s", W_RUN, f"combined.latency.ts_ms.{q}",
            "Block timestamp minus submit time over every landed own transaction in the blast, from the "
            "load generators' merged latency histograms (aggregate.py merge_latency), in seconds.",
            value=lat[q] / 1000.0))
    if lat.get("saturated") is True:
        caveats.append("combined.latency.ts_ms is saturated: a time-to-land quantile fell in the open last "
                       "histogram bucket and is a lower bound")
    if lat.get("p50") is not None:
        out.append(_kpi(
            "time_to_land_corrected_p50_s", "Time to land, median, whole-second bias removed", "Land p50 corrected",
            "s", W_RUN, "combined.latency.ts_ms.p50 + %.1f s" % LAND_FLOOR_BIAS_S,
            "Time to land, median, plus 0.5 s. The block timestamp is the committing leader's header creation "
            "time cut to the whole second, so every sample reads 0 to 999 ms low, 0.5 s on average.",
            value=lat["p50"] / 1000.0 + LAND_FLOOR_BIAS_S))

    seen = ((combined or {}).get("latency") or {}).get("seen_ms") or {}
    for kid, q, label, short in (("time_to_seen_p50_s", "p50", "Time to seen, median", "Seen p50"),
                                 ("time_to_seen_p95_s", "p95", "Time to seen, p95", "Seen p95")):
        if seen.get(q) is None:
            caveats.append(f"combined.latency.seen_ms.{q} missing: {kid} not computed")
            continue
        out.append(_kpi(
            kid, label, short, "s", W_RUN, f"combined.latency.seen_ms.{q}",
            "Submit time to the moment the load generator's block scanner had the block holding the "
            "transaction (block and receipts fetched from the generator's own node), over every landed own "
            "transaction in the blast, from the load generators' merged latency histograms "
            "(aggregate.py merge_latency), in seconds.",
            value=seen[q] / 1000.0))
    if seen.get("saturated") is True:
        caveats.append("combined.latency.seen_ms is saturated: a time-to-seen quantile fell in the open last "
                       "histogram bucket and is a lower bound")
    return out


def floor_by_generator(docs: List[dict]) -> List[dict]:
    """Each light-blast generator's own mixed-phase quantiles (its document's latency.ts_ms /
    seen_ms, nearest-rank over its samples), in seconds, by label."""
    rows = []
    for i, d in enumerate(docs):
        run, lat = d.get("run") or {}, d.get("latency") or {}
        ts, seen = lat.get("ts_ms") or {}, lat.get("seen_ms") or {}

        def sec(q, key):
            return None if not _is_num(q.get(key)) else round(q[key] / 1000.0, 3)
        rows.append({"generator": run.get("label") or run.get("run_id") or "blaster-%d" % i,
                     "samples": (d.get("totals") or {}).get("landed_own"),
                     "time_to_land_p50_s": sec(ts, "p50"), "time_to_land_p95_s": sec(ts, "p95"),
                     "time_to_seen_p50_s": sec(seen, "p50"), "time_to_seen_p95_s": sec(seen, "p95")})
    rows.sort(key=lambda r: str(r["generator"]))
    return rows


def _floor_kpis(floor: dict, caveats: List[str]) -> List[dict]:
    out = []
    name, idx = floor.get("name") or "light8", floor.get("index")
    where = "%s/blasters" % (floor.get("dir") or "blast-%s-<UTC>" % idx)
    try:
        lat = pooled_latency(floor.get("docs") or [])
    except ValueError as e:
        caveats.append("%s blast: %s; floor KPIs not computed" % (name, e))
        return out
    what = ("submitted in the mixed phase of the light-load blast %s (index %s: %s senders per load "
            "generator at window %s, chaos off)" % (name, idx, floor.get("senders", 8), floor.get("window", 16)))
    for kid, key, label, short, measure in (
            ("floor_time_to_land_p50_s", "ts_ms", "Time to land at light load, median", "Floor land p50",
             "Block timestamp minus submit time"),
            ("floor_time_to_seen_p50_s", "seen_ms", "Time to seen at light load, median", "Floor seen p50",
             "Submit time to the generator's block scanner having the block")):
        q = lat.get(key) or {}
        if q.get("p50") is None:
            caveats.append("%s blast: latency.%s.p50 missing in %s: %s not computed" % (name, key, where, kid))
            continue
        out.append(_kpi(
            kid, label, short, "s", name, "%s latency.%s.p50" % (where, key),
            "%s over every landed own transaction %s, pooled from the generators' latency histograms with "
            "the aggregate.py merge_latency method, in seconds; not bias-corrected." % (measure, what),
            value=q["p50"] / 1000.0))
        if q.get("saturated") is True:
            caveats.append("%s blast: latency.%s is saturated; %s is a lower bound" % (name, key, kid))
    cuts = floor.get("boundaries") or []
    if out and cuts:
        caveats.append("%d epoch boundar%s fell inside the %s mixed window (%s); the floor KPIs pool its whole "
                       "mixed phase (windows.py --exclude-boundaries gives the boundary-free intervals)"
                       % (len(cuts), "y" if len(cuts) == 1 else "ies", name, ", ".join(unix_to_iso(b) for b in cuts)))
    return out


def _prom_range_kpis(metrics: dict, healthy: List[str], windows: dict, caveats: List[str]) -> List[dict]:
    out = []
    w = _window(windows, W_MERGED)
    if not w:
        caveats.append("merged window undefined: commit latency and execution time not computed")
        return out
    for kid, name, key, q, label, short, method in (
            ("commit_latency_p95_s", "tn_primary_commit_latency_seconds", "p95", 0.95,
             "Commit latency, p95", "Commit p95",
             "For each healthy validator, the nearest-rank p95 over the merged mixed window of its 15-s "
             "histogram_quantile(0.95) commit-latency series; reported as the range over validators."),
            ("execution_time_per_output_s", "tn_engine_execution_duration_seconds", "mean", 0.5,
             "Execution time per consensus output", "Exec per output",
             "For each healthy validator, the nearest-rank median over the merged mixed window of its 15-s "
             "mean execution-duration series; reported as the range over validators.")):
        per = {}
        for n in healthy:
            vals = [v for t, v in _prom_points(metrics, name, key, n) if w[0] <= t <= w[1]]
            if vals:
                per[n] = pct(vals, q)
        missing = [n for n in healthy if n not in per]
        if not per:
            caveats.append(f"metrics.prometheus.series.{name}.{key} has no points for healthy validators: "
                           f"{kid} not computed")
            continue
        if missing:
            caveats.append(f"{kid}: no {name}.{key} points for {', '.join(missing)}")
        out.append(_kpi(kid, label, short, "s", W_MERGED,
                        f"metrics.prometheus.series.{name}.by_node[healthy validators].{key}", method,
                        rng=(min(per.values()), max(per.values()))))
    return out


def _resource_kpis(metrics: dict, sampler: dict, healthy: List[str], windows: dict,
                   caveats: List[str]) -> List[dict]:
    out = []
    w = _window(windows, W_MERGED)
    if not w:
        caveats.append("merged window undefined: disk, CPU, memory and IO-pressure rows not computed")
        return out
    for kid, key, scale, unit, label, short, what in (
            ("disk_write_p95_mibps_busiest", "disk_write_bytes_per_sec", 1.0 / MIB, "MiB/s",
             "Write throughput, p95, busiest validator", "Disk write p95", "60-s mean write-byte rate"),
            ("disk_write_iops_p95_busiest", "disk_write_ops_per_sec", 1.0, "IOPS",
             "Write operations, p95, busiest validator", "Write IOPS p95", "60-s mean write-operation rate"),
            ("cpu_p95_pct_busiest", "cpu_utilization", 1.0, "%",
             "CPU, p95, busiest validator", "CPU p95", "60-s CPU utilisation"),
            ("rss_p95_gib_busiest", "telcoin_rss_bytes", 1.0 / GIB, "GiB",
             "Node resident memory, p95, busiest validator", "RSS p95", "60-s telcoin process resident memory")):
        per = {}
        for n in healthy:
            vals = _gcp_values(metrics, n, key, *w)
            if vals:
                per[n] = pct(vals, 0.95) * scale
        missing = [n for n in healthy if n not in per]
        if not per:
            caveats.append(f"metrics.gcp has no {key} points for healthy validators: {kid} not computed")
            continue
        if missing:
            caveats.append(f"{kid}: no {key} points for {', '.join(missing)}")
        busiest = max(per, key=lambda n: (per[n], n))
        out.append(_kpi(kid, label, short, unit, W_MERGED, f"metrics.gcp[{busiest}].{key} p95",
                        f"Nearest-rank p95 of the {what} over the merged mixed window for each healthy "
                        f"validator; the highest ({busiest}) is reported.",
                        value=per[busiest]))

    per = {}
    for n in healthy:
        vals = _sampler_values(sampler, n, "psi_io_some_avg10", *w)
        if vals:
            per[n] = max(vals)
    missing = [n for n in healthy if n not in per]
    if not per:
        caveats.append("sampler has no psi_io_some_avg10 rows for healthy validators: psi_io_max_pct not computed")
    else:
        if missing:
            caveats.append(f"psi_io_max_pct: no sampler psi_io_some_avg10 rows for {', '.join(missing)}")
        out.append(_kpi(
            "psi_io_max_pct", "IO pressure, highest reading, range over validators", "IO pressure max", "%",
            W_MERGED, "sampler[healthy validators].psi_io_some_avg10 max",
            "For each healthy validator, the highest 10-s 'some' IO pressure reading the on-node sampler "
            "logged inside the merged mixed window; reported as the range over validators.",
            rng=(min(per.values()), max(per.values()))))
    return out


# ---------------------------------------------------------------- recovery

def recovery(metrics: dict, manifest: dict, target: str, caveats: List[str]) -> dict:
    """Outage and catch-up of one chaos target from manifest.chaos and the Prometheus series.

    killed/restarted: the target's first down event and the next up event in manifest.chaos.
    demoted: the first tn_node_mode{mode="cvv_inactive"} sample at or after the restart that reads 1.
    rejoined: the first sample after it from which the series reads 0 to the end of the metrics window
    (15-s resolution); a promotion followed by another inactive sample is not a rejoin. When the
    node is still inactive at the window's last sample, the window ended while it was rejoining and
    rejoined / catch_up_secs are null. catch_up_secs is rejoined - demoted, the time the node spent
    in catch-up mode. failed_reports is the rise of
    tn_batch_builder_seal_failures_total{reason="failed_to_report"} on the target over the metrics
    window (metrics.prometheus.series.<name>.count: the last value minus the first, a series created
    inside the window counting from 0, a drop read as a restart).
    """
    rec = {"node": target, "killed_utc": None, "restarted_utc": None, "demoted_utc": None,
           "rejoined_utc": None, "catch_up_secs": None, "failed_reports": None}
    events = [e for e in chaos_events(manifest) if e["node"] == target]
    down = next((e for e in events if e["kind"] == "down"), None)
    if down is None:
        caveats.append(f"recovery: no down event for {target} in manifest.chaos")
        return rec
    up = next((e for e in events if e["kind"] == "up" and e["ts_unix"] >= down["ts_unix"]), None)
    rec["killed_utc"] = down["ts"]
    rec["restarted_utc"] = up["ts"] if up else None
    since = up["ts_unix"] if up else down["ts_unix"]

    mode = sorted(_prom_points(metrics, "tn_node_mode", "max", target))
    q = (_prom(metrics, "tn_node_mode").get("queries") or {}).get("max") or ""
    if not mode or "cvv_inactive" not in q:
        caveats.append(f"recovery: no tn_node_mode{{mode=\"cvv_inactive\"}} series for {target}; "
                       "demoted / rejoined / catch-up unavailable")
    else:
        after = [(t, v) for t, v in mode if t >= since]
        demoted = next((t for t, v in after if v >= 0.5), None)
        last_inactive = max((t for t, v in after if v >= 0.5), default=None)
        # Every sample after the last inactive one is active: the first of them is the rejoin.
        rejoined = next((t for t, v in after if last_inactive is None or t > last_inactive), None)
        # Promotions the node fell back from: an active sample right after an inactive one, before the last.
        transient = [t for (_, v0), (t, v) in zip(after, after[1:])
                     if v0 >= 0.5 and v < 0.5 and last_inactive is not None and t < last_inactive]
        rec["demoted_utc"] = unix_to_iso(demoted)
        rec["rejoined_utc"] = unix_to_iso(rejoined)
        if rejoined is not None:
            # No demotion sample at all means the catch-up length is unknown, not zero.
            rec["catch_up_secs"] = rejoined - demoted if demoted is not None else None
        elif last_inactive is None:
            caveats.append(f"recovery: no tn_node_mode sample for {target} after the restart; "
                           "demoted / rejoined / catch-up unavailable")
        else:
            caveats.append(f"recovery: the metrics window ended while {target} was still rejoining (inactive at "
                           f"its last sample, {unix_to_iso(last_inactive)}); rejoined and catch-up unavailable")
        if transient:
            caveats.append(f"recovery: the 15-s samples show {target} promoted {len(transient)} time(s) "
                           f"({unix_to_iso(transient[0])} to {unix_to_iso(transient[-1])}) and inactive again "
                           "at a later sample each time; a rejoin counts only once the node stays active to the "
                           "end of the metrics window")
        caveats.append("recovery: demoted / rejoined are the first 15-s Prometheus samples showing the change, "
                       "so they trail the node's own log times by up to a scrape interval plus one step")

    name = "tn_batch_builder_seal_failures_total"
    whole = (_prom(metrics, name).get("count") or {}).get(target)
    if whole is None:
        caveats.append(f"recovery: no {name} count for {target}; failed_reports unavailable")
    else:
        rec["failed_reports"] = int(round(whole))
        caveats.append(f"recovery: failed_reports is the rise of the batch-seal failure counter on {target} over "
                       f"the whole metrics window (metrics.prometheus.series.{name}.count), outage or not")
    return rec


# ---------------------------------------------------------------- entry point

def healthy_validators(manifest: dict, chaos_targets: List[str]) -> List[str]:
    vals = [i["name"] for i in (manifest or {}).get("instances") or [] if i.get("role") == "validator"]
    return sorted(n for n in vals if n not in set(chaos_targets or []))


def compute(combined: dict, metrics: dict, sampler: dict, manifest: dict, windows: dict,
            chaos_targets: list, floor: Optional[dict] = None) -> dict:
    """KPIs, recovery and caveats; with `floor` (a light8 blast) also the floor KPIs and the
    floor_by_generator side table."""
    caveats = []
    healthy = healthy_validators(manifest, chaos_targets)
    roles = {i["name"]: i.get("role") for i in (manifest or {}).get("instances") or []}
    excluded = [n for n in chaos_targets or [] if roles.get(n) == "validator"]
    if not healthy:
        caveats.append("no healthy validators in manifest.instances: per-validator rows not computed")
    elif excluded:
        caveats.append(f"per-validator rows cover {len(healthy)} validators; {', '.join(excluded)} excluded "
                       "as chaos target(s)")

    kpis = _chain_kpis(combined, windows, caveats)
    if floor is not None:
        kpis += _floor_kpis(floor, caveats)
    if healthy:
        kpis += _prom_range_kpis(metrics, healthy, windows, caveats)
        kpis += _resource_kpis(metrics, sampler, healthy, windows, caveats)
    order = list(DECIMALS)
    kpis.sort(key=lambda k: order.index(k["id"]) if k["id"] in order else len(order))

    rec = None
    targets = list(chaos_targets or [])
    if targets:
        target = next((n for n in targets if roles.get(n) == "validator"), targets[0])
        if len(targets) > 1:
            caveats.append(f"recovery covers {target} only; other chaos targets: "
                           f"{', '.join(n for n in targets if n != target)}")
        rec = recovery(metrics, manifest, target, caveats)
    out = {"kpis": round_kpis(kpis), "recovery": rec, "caveats": caveats}
    if floor is not None:
        out["floor_by_generator"] = floor_by_generator(floor.get("docs") or [])
    return out


# ---------------------------------------------------------------- light blast and command line

HERE = os.path.dirname(os.path.abspath(__file__))
_BLAST_DIR_RE = re.compile(r"^blast-([0-9]+)-")


def _windows():
    """windows.py next to this file (imported on demand: the tests load this module by path)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import windows  # noqa: E402
    return windows


def blast_from_dir(manifest: dict, path: str) -> dict:
    """A light-blast record for an explicit --floor-blast-dir: the index from its
    blast-<index>-<UTC> name, the rest from the manifest's blasts[] entry of that index (8 senders
    at window 16 when there is none)."""
    win = _windows()
    m = _BLAST_DIR_RE.match(os.path.basename(os.path.normpath(path)))
    idx = int(m.group(1)) if m else None
    e = next((e for e in (manifest or {}).get("blasts") or []
              if isinstance(e, dict) and idx is not None and e.get("index") == idx), {})
    senders = int(e.get("senders") or 8)
    window = int(e.get("window") or win.DEFAULT_WINDOW)
    return {"name": win.light_name(senders, window), "index": idx, "senders": senders, "window": window,
            "rc": e.get("rc"), "started": e.get("started"), "ended": e.get("ended"), "dir": path}


def floor_input(blast: dict, directory: Optional[str] = None) -> dict:
    """compute()'s `floor` for a light blast (windows.floor_blast() or blast_from_dir()): the
    tn-blast documents in <directory or blast dir>/blasters and the epoch boundaries inside its
    mixed window. `dir` keeps only the archive's own name, for the KPI source text."""
    win = _windows()
    d = directory or blast["dir"]
    w = win.light_window(dict(blast, dir=d))
    return {"name": blast["name"], "index": blast["index"], "senders": blast.get("senders"),
            "window": blast.get("window"), "dir": os.path.basename(os.path.normpath(blast["dir"])),
            "docs": win.load_blasters(os.path.join(d, "blasters")), "boundaries": w.get("boundaries") or [],
            "mixed": {k: w.get(k) for k in ("start_unix", "end_unix", "secs", "source")}}


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _aggregate(tool_dir: str, blasters_dir: str) -> dict:
    """aggregate.py over blasters_dir (as make_bundle.py step 3), in a temporary dir."""
    with tempfile.TemporaryDirectory(prefix="kpis-") as tmp:
        out = os.path.join(tmp, "combined.json")
        r = subprocess.run([sys.executable, os.path.join(tool_dir, "aggregate.py"), "--out", out,
                            os.path.abspath(blasters_dir)], cwd=tmp, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True)
        if r.returncode != 0:
            raise RuntimeError("aggregate.py exited %d: %s" % (r.returncode, r.stdout.strip()[-400:]))
        return _load_json(out)


def table(res: dict) -> str:
    """The KPIs (and the floor side table) as markdown."""
    lines = ["| KPI | value | unit | window |", "|---|---:|---|---|"]
    for k in res["kpis"]:
        v = "%s-%s" % tuple(k["range"]) if "range" in k else k["value"]
        lines.append("| %s | %s | %s | %s |" % (k["id"], v, k["unit"], k["window"]))
    rows = res.get("floor_by_generator")
    if rows:
        lines += ["", "| generator | samples | land p50 s | land p95 s | seen p50 s | seen p95 s |",
                  "|---|---:|---:|---:|---:|---:|"]
        for r in rows:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                r["generator"], r["samples"], r["time_to_land_p50_s"], r["time_to_land_p95_s"],
                r["time_to_seen_p50_s"], r["time_to_seen_p95_s"]))
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Headline KPIs of one benchmark run (offline).")
    ap.add_argument("--run-dir", required=True, help="benchmark/results/<run>")
    ap.add_argument("--blast-dir", help="take the load's manifest, metrics and blasters/ from this "
                                        "blast-<i>-<UTC>/ (default: the run dir)")
    ap.add_argument("--floor-blast-dir", help="the light blast the floor KPIs read (default: the light8 entry "
                                              "of manifest blasts[] -> its blast-<index>-<UTC>/)")
    ap.add_argument("--txgen-bench", default=os.environ.get("BENCH_TXGEN_REPO") and
                    os.path.join(os.environ["BENCH_TXGEN_REPO"], "bench"),
                    help="the generator's bench/ dir with aggregate.py (default ${BENCH_TXGEN_REPO}/bench, "
                         "else ../tn-transaction-generator/bench beside this repository)")
    ap.add_argument("--combined", help="an aggregate.py result to use instead of running aggregate.py")
    ap.add_argument("--table", action="store_true", help="print a markdown table instead of JSON")
    ap.add_argument("--out", help="write the JSON here as well")
    a = ap.parse_args(argv)
    run_dir = os.path.abspath(a.run_dir)
    src = os.path.abspath(a.blast_dir) if a.blast_dir else run_dir
    tool_dir = a.txgen_bench or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                                             "tn-transaction-generator", "bench")
    win = _windows()
    try:
        live = _load_json(os.path.join(run_dir, "manifest.json"))
        manifest = live if src == run_dir else _load_json(os.path.join(src, "manifest.json"))
        metrics = _load_json(os.path.join(src, "metrics.json"))
        blasters = win.load_blasters(os.path.join(src, "blasters"))
        combined = _load_json(a.combined) if a.combined else _aggregate(tool_dir, os.path.join(src, "blasters"))
    except (OSError, ValueError, RuntimeError) as e:
        print("kpis.py: %s" % e, file=sys.stderr)
        return 2
    if not blasters:
        print("kpis.py: no tn-blast results in %s/blasters" % src, file=sys.stderr)
        return 2
    built = win.build(blasters, combined)
    sampler_dir = os.path.join(run_dir, "sampler")
    sampler = load_sampler(sampler_dir) if os.path.isdir(sampler_dir) else {}
    floor_caveats = []
    if a.floor_blast_dir:
        blast = blast_from_dir(live, os.path.abspath(a.floor_blast_dir))
    else:
        blast, floor_caveats = win.floor_blast(run_dir, live)
    floor = floor_input(blast) if blast else None
    res = compute(combined, metrics, sampler, manifest, built, chaos_targets_from_manifest(manifest), floor)
    res["caveats"] = floor_caveats + res["caveats"]
    doc = {"run": os.path.basename(run_dir), "blast_dir": os.path.relpath(src, run_dir),
           "floor_blast_dir": floor["dir"] if floor else None, "headline": headline_id(res["kpis"])}
    doc.update(res)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
    if a.table:
        sys.stdout.write(table(doc))
    else:
        json.dump(doc, sys.stdout, indent=1)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
