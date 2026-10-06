#!/usr/bin/env python3
"""Measurement windows for a published benchmark run.

Each blaster (`tn-blast/v2`) records its own `mixed` phase in `run.phases`. Blasters start
at different times (some wait out a long preamble), so the fleet has two windows:

- merged mixed: from the earliest mixed start to the latest mixed end. This is the window
  `aggregate.py` reports as `landed.window_secs`, and the one `landed.avg_tps_chain` and
  `landed.sustained_mixed_tps_chain_60s` are computed over.
- all generators: from the latest mixed start to the earliest mixed end, the stretch when
  every blaster was in its mixed phase. It is undefined when the mixed phases do not overlap.

All windows are half-open `[start_unix, end_unix)` in whole unix seconds. Chain throughput
comes from the combined result (`tn-blast-combined/v2`): `series.per_second` holds one row per
block-timestamp second, `s` is the offset from `series.per_second_t0_unix`, and seconds
missing from the series count as zero.

Usage: python3 windows.py <blasters-dir> <combined.json> [--blocks]
Prints the build() dict as JSON (with a "blocks" list of 5-minute blocks over the merged
window when --blocks is given). Exits 1 when build() reports problems, 2 on bad input.

Python 3.9+, standard library only.
"""

import argparse
import datetime
import glob
import json
import os
import statistics
import sys
from typing import Dict, List, Optional, Tuple

# The combined-result key check_merged() compares against. aggregate.py writes it as
# {"start_unix", "end_unix"} (the merged `mixed` phase, half-open) with no secs field, so
# the compared length is end_unix - start_unix.
COMBINED_WINDOW_KEY = "landed.window_secs"

BLOCK_SECS = 300
SAMPLE_SECS = 10
SUSTAIN_SECS = 60
UNDEFINED_ALL_GENERATORS = "all-generators window undefined"


def iso(ts_unix) -> str:
    """Unix seconds -> `YYYY-MM-DDTHH:MM:SSZ` (UTC)."""
    t = datetime.datetime.fromtimestamp(int(ts_unix), datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _label(blaster: dict, index: int) -> str:
    run = blaster.get("run") or {}
    return run.get("label") or run.get("run_id") or "blaster-%d" % index


def _split(blasters: List[dict]) -> Tuple[List[dict], List[str]]:
    """-> (mixed windows sorted by label, caveats for blasters without a usable mixed phase)."""
    windows, caveats = [], []
    for i, b in enumerate(blasters):
        label = _label(b, i)
        phases = (b.get("run") or {}).get("phases") or []
        mixed = next((p for p in phases if p.get("name") == "mixed"), None)
        if mixed is None:
            caveats.append("%s: no mixed phase; excluded from the windows" % label)
            continue
        start, end = mixed.get("start_unix"), mixed.get("end_unix")
        if start is None or end is None or int(end) <= int(start):
            caveats.append("%s: mixed phase has no usable span (%s..%s); excluded from the windows"
                           % (label, start, end))
            continue
        windows.append({"label": label, "start_unix": int(start), "end_unix": int(end)})
    windows.sort(key=lambda w: w["label"])
    return windows, caveats


def mixed_windows(blasters: List[dict]) -> List[dict]:
    """Each blaster's mixed phase as {"label", "start_unix", "end_unix"}, sorted by label.
    Blasters without one are skipped (build() lists them in its caveats)."""
    return _split(blasters)[0]


def merged(mixed: List[dict]) -> dict:
    """Earliest mixed start to latest mixed end. Raises ValueError on an empty list."""
    if not mixed:
        raise ValueError("no mixed windows to merge")
    start = min(w["start_unix"] for w in mixed)
    end = max(w["end_unix"] for w in mixed)
    return {"start_unix": start, "end_unix": end, "secs": end - start}


def all_generators(mixed: List[dict]) -> Optional[dict]:
    """Latest mixed start to earliest mixed end, or None when the mixed phases do not overlap."""
    if not mixed:
        return None
    start = max(w["start_unix"] for w in mixed)
    end = min(w["end_unix"] for w in mixed)
    if start >= end:
        return None
    return {"start_unix": start, "end_unix": end, "secs": end - start}


def check_merged(merged_window: dict, combined: dict) -> List[str]:
    """Compare the merged mixed window with the combined result's COMBINED_WINDOW_KEY.
    Returns the mismatches; an empty list means they agree."""
    win = (combined.get("landed") or {}).get("window_secs")
    if not isinstance(win, dict) or win.get("start_unix") is None or win.get("end_unix") is None:
        return ["combined result has no %s; cannot check the merged window" % COMBINED_WINDOW_KEY]
    start, end = int(win["start_unix"]), int(win["end_unix"])
    problems = []
    if end - start != merged_window["secs"]:
        problems.append("merged mixed window is %d s but %s spans %d s"
                        % (merged_window["secs"], COMBINED_WINDOW_KEY, end - start))
    if start != merged_window["start_unix"] or end != merged_window["end_unix"]:
        problems.append("merged mixed window %d..%d differs from %s %d..%d"
                        % (merged_window["start_unix"], merged_window["end_unix"],
                           COMBINED_WINDOW_KEY, start, end))
    return problems


check_merged.key = COMBINED_WINDOW_KEY


def _chain_series(combined: dict, start_unix: int, end_unix: int) -> List[int]:
    """Per-second chain_tx over [start, end); seconds absent from the series are 0."""
    series = combined.get("series") or {}
    cols = series.get("per_second_columns") or []
    t0 = series.get("per_second_t0_unix")
    by_sec = {}
    if t0 is not None and "chain_tx" in cols:
        i_s = cols.index("s") if "s" in cols else 0
        i_tx = cols.index("chain_tx")
        for row in series.get("per_second") or []:
            by_sec[int(t0) + int(row[i_s])] = row[i_tx] or 0
    return [by_sec.get(s, 0) for s in range(int(start_unix), int(end_unix))]


def window_mean_tps(combined: dict, start_unix: int, end_unix: int) -> float:
    """Mean chain tx per second over [start, end). Raises ValueError on an empty window."""
    if end_unix <= start_unix:
        raise ValueError("empty window %s..%s" % (start_unix, end_unix))
    vals = _chain_series(combined, start_unix, end_unix)
    return sum(vals) / len(vals)


def best_60s_tps(combined: dict, start_unix: int, end_unix: int) -> Optional[float]:
    """Highest mean chain tx/s over any 60 consecutive seconds inside [start, end), or None
    when the range is shorter than 60 s. Over the merged mixed window this is the same
    computation as aggregate.py's landed.sustained_mixed_tps_chain_60s (unrounded)."""
    vals = _chain_series(combined, start_unix, end_unix)
    if len(vals) < SUSTAIN_SECS:
        return None
    cur = best = sum(vals[:SUSTAIN_SECS])
    for i in range(SUSTAIN_SECS, len(vals)):
        cur += vals[i] - vals[i - SUSTAIN_SECS]
        best = max(best, cur)
    return best / SUSTAIN_SECS


def blocks(combined: dict, mixed: List[dict], start_unix: int, end_unix: int,
           step: int = BLOCK_SECS, sample: int = SAMPLE_SECS) -> List[dict]:
    """Consecutive `step`-second blocks over [start, end); the last may be shorter.

    generators_active is the mean, over samples x = start, start+sample, ... inside the block,
    of how many mixed windows contain x (start <= x < end). Unlike s4b_trajectory.py, a
    trailing 1-second block is kept rather than dropped."""
    start_unix, end_unix = int(start_unix), int(end_unix)
    vals = _chain_series(combined, start_unix, end_unix)
    out = []
    for s in range(start_unix, end_unix, step):
        e = min(s + step, end_unix)
        chain_tx = sum(vals[s - start_unix:e - start_unix])
        active = statistics.mean(
            sum(1 for w in mixed if w["start_unix"] <= x < w["end_unix"])
            for x in range(s, e, sample))
        out.append({"start_unix": s, "end_unix": e, "secs": e - s, "chain_tx": chain_tx,
                    "chain_tps": chain_tx / (e - s), "generators_active": float(active)})
    return out


def build(blasters: List[dict], combined: Optional[dict]) -> dict:
    """Windows, caveats and problems for one blast."""
    windows, caveats = _split(blasters)
    problems = []
    if windows:
        merged_window = merged(windows)
        if combined is None:
            caveats.append("no combined result; merged window not checked against %s"
                           % COMBINED_WINDOW_KEY)
        else:
            problems.extend(check_merged(merged_window, combined))
    else:
        merged_window = None
        problems.append("no blaster has a usable mixed phase")
    gens = all_generators(windows)
    if gens is None:
        caveats.append(UNDEFINED_ALL_GENERATORS)
    return {"mixed_windows": windows, "merged": merged_window, "all_generators": gens,
            "caveats": caveats, "problems": problems}


def _utc_window(w: Optional[dict]) -> Optional[dict]:
    if w is None:
        return None
    return {"start_utc": iso(w["start_unix"]), "end_utc": iso(w["end_unix"]), "secs": w["secs"]}


def to_run_json(windows: Optional[dict]) -> Optional[dict]:
    """build() output -> the windows block of a published run.json, or None without a merged window."""
    if not windows or windows.get("merged") is None:
        return None
    return {"merged_mixed": _utc_window(windows["merged"]),
            "all_generators": _utc_window(windows.get("all_generators"))}


def load_blasters(directory: str) -> List[dict]:
    """Every `tn-blast/*` result in `directory` (other JSON, e.g. a combined file, is ignored)."""
    docs = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path) as f:
            doc = json.load(f)
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("tn-blast/"):
            docs.append(doc)
    return docs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Measurement windows for a benchmark blast.")
    ap.add_argument("blasters_dir", help="directory of per-blaster tn-blast/v2 JSON results")
    ap.add_argument("combined", help="aggregate.py output (tn-blast-combined/v2)")
    ap.add_argument("--blocks", action="store_true",
                    help="also print %d-second blocks over the merged window" % BLOCK_SECS)
    args = ap.parse_args(argv)
    try:
        blasters = load_blasters(args.blasters_dir)
        with open(args.combined) as f:
            combined = json.load(f)
    except (OSError, ValueError) as e:
        print("windows.py: %s" % e, file=sys.stderr)
        return 2
    if not blasters:
        print("windows.py: no tn-blast results in %s" % args.blasters_dir, file=sys.stderr)
        return 2
    out = build(blasters, combined)
    if args.blocks and out["merged"] is not None:
        m = out["merged"]
        out["blocks"] = blocks(combined, out["mixed_windows"], m["start_unix"], m["end_unix"])
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
