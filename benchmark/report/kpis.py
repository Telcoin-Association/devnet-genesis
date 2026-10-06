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

Windows. "all_generators" is [latest mixed start, earliest mixed end), when every load generator
was running; "merged_mixed" is [earliest mixed start, latest mixed end), the window aggregate.py
reports as landed.window_secs; "run" means the whole blast. Per-second chain series are
half-open, as in aggregate.py. GCP, Prometheus and sampler points use inclusive bounds
lo <= t <= hi, as derive-sizing.py summarize() does.

Healthy validators are the manifest's validators minus the chaos targets; "busiest" is the healthy
validator with the highest p95 of that measure over the window.

Python 3.9+, standard library only.
"""

import csv
import datetime
import glob
import json
import os
import re
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
    "commit_latency_p95_s": 2,
    "execution_time_per_output_s": 2,
    "disk_write_p95_mibps_busiest": 1,
    "disk_write_iops_p95_busiest": 0,
    "cpu_p95_pct_busiest": 1,
    "rss_p95_gib_busiest": 2,
    "psi_io_max_pct": 1,
}


# Nearest-rank percentile, copied verbatim from tn-transaction-generator bench/derive-sizing.py:25-26
# so every p95 here is the statistic the sizing report and the 29 Sep report publish.
def pct(xs, q):
    xs = sorted(xs); i = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1))))); return xs[i]


def best_window_mean(vals: List[float], width: int) -> Optional[float]:
    """Highest mean over any `width` consecutive seconds (aggregate.py best_window_mean)."""
    if not vals:
        return None
    if len(vals) <= width:
        return sum(vals) / len(vals)
    cur = best = sum(vals[:width])
    for i in range(width, len(vals)):
        cur += vals[i] - vals[i - width]
        best = max(best, cur)
    return best / width


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
        out.append(_kpi(
            "best_60s_chain_tps_all_generators", "Best 60 seconds, all load generators running",
            "Best 60 s TPS", "tx/s", W_ALL, "combined.series.per_second[chain_tx]",
            "Highest mean chain tx/s over any 60 consecutive seconds inside the all-generators window "
            "(aggregate.py best_window_mean).",
            value=best_window_mean(chain, SUSTAIN_SECS)))

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

_RATE_WINDOW_RE = re.compile(r"\[(\d+)([smh])\]")


def _rate_window_secs(query: Optional[str]) -> int:
    m = _RATE_WINDOW_RE.search(query or "")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)] if m else 60


def recovery(metrics: dict, manifest: dict, target: str, caveats: List[str]) -> dict:
    """Outage and catch-up of one chaos target from manifest.chaos and the Prometheus series.

    killed/restarted: the target's first down event and the next up event in manifest.chaos.
    demoted/rejoined: first tn_node_mode{mode="cvv_inactive"} sample at or after the restart that
    reads 1, then the first sample after it that reads 0 (15-s resolution). catch_up_secs is
    rejoined - demoted, the time the node spent in catch-up mode. failed_reports integrates the
    per-second rate of tn_batch_builder_seal_failures_total{reason="failed_to_report"} over the
    samples from the kill to one rate window after the rejoin.
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
    demoted = rejoined = None
    if not mode or "cvv_inactive" not in q:
        caveats.append(f"recovery: no tn_node_mode{{mode=\"cvv_inactive\"}} series for {target}; "
                       "demoted / rejoined / catch-up unavailable")
    else:
        after = [(t, v) for t, v in mode if t >= since]
        demoted = next((t for t, v in after if v >= 0.5), None)
        if demoted is not None:
            rejoined = next((t for t, v in after if t > demoted and v < 0.5), None)
        else:
            rejoined = next((t for t, v in after if v < 0.5), None)
        rec["demoted_utc"] = unix_to_iso(demoted)
        rec["rejoined_utc"] = unix_to_iso(rejoined)
        if rejoined is not None:
            # No demotion sample at all means the catch-up length is unknown, not zero.
            rec["catch_up_secs"] = rejoined - demoted if demoted is not None else None
        else:
            caveats.append(f"recovery: {target} did not leave catch-up mode inside the metrics window")
        caveats.append("recovery: demoted / rejoined are the first 15-s Prometheus samples showing the change, "
                       "so they trail the node's own log times by up to a scrape interval plus one step")

    name = "tn_batch_builder_seal_failures_total"
    sf = _prom(metrics, name)
    rate = sorted(_prom_points(metrics, name, "rate", target))
    step = ((metrics or {}).get("prometheus") or {}).get("step")
    if not rate or not step:
        caveats.append(f"recovery: no {name} rate series for {target}; failed_reports unavailable")
    else:
        hi = rejoined + _rate_window_secs((sf.get("queries") or {}).get("rate")) if rejoined is not None else None
        n = sum(v * step for t, v in rate if t >= down["ts_unix"] and (hi is None or t <= hi))
        rec["failed_reports"] = int(round(n))
        if hi is None:
            caveats.append(f"recovery: failed_reports for {target} runs to the end of the metrics window "
                           "(no rejoin seen) and is a lower bound")
        caveats.append(f"recovery: failed_reports integrates the 1-m rate at the {step}-s step, which misses the "
                       "increment that creates the counter series and so can read a few low")
        whole = (sf.get("count") or {}).get(target)
        if whole is not None:
            caveats.append(f"recovery: the collector's exact {name} increase for {target} over the whole metrics "
                           f"window (metrics.prometheus.series.{name}.count) is {whole}, outage or not")
    return rec


# ---------------------------------------------------------------- entry point

def healthy_validators(manifest: dict, chaos_targets: List[str]) -> List[str]:
    vals = [i["name"] for i in (manifest or {}).get("instances") or [] if i.get("role") == "validator"]
    return sorted(n for n in vals if n not in set(chaos_targets or []))


def compute(combined: dict, metrics: dict, sampler: dict, manifest: dict, windows: dict,
            chaos_targets: list) -> dict:
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
    return {"kpis": round_kpis(kpis), "recovery": rec, "caveats": caveats}
