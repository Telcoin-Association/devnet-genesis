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

Light blasts. A light-load arm (benchmark-blast.sh, BENCH_LIGHT_LOAD=1) runs light blasts before
the load on the same fleet. Each one is listed in the live manifest's `blasts[]` ({index,
senders, window, chaos, started, ended, rc}) and archived under `blast-<index>-<UTC>/` with its
own `blasters/` and a copy of the manifest; the load's files stay at the top of the results
dir. light_blasts() finds them, light_windows() gives each one's mixed phase: the merged mixed
window of its own archived blasters (the same rule as the load's merged window), else the
`mixed` entry of its manifest copy's `phases`, else `started` + warm-up to `ended` - cool-down
from `blasts[]`. That last fallback is approximate: `started` and `ended` bracket the whole
single-blast invocation (VM create, start delay, preamble, collect), so it is only used when
nothing better was archived. Epoch boundaries are the timestamps of the blocks whose
`closes_epoch` cell is set in the light blast's own block tables (read by column name). The
command line drops +/- EXCLUDE_SECS around each one from the light windows by default (a loaded
boundary waits for execution, which a floor must not average in): --exclude-boundaries SECS
changes the width, --keep-boundaries keeps the whole window. light_window() and light_windows()
exclude only when given exclude_secs.

Usage: python3 windows.py <blasters-dir> <combined.json> [--blocks]
                          [--run-dir RESULTS/<run> [--exclude-boundaries [SECS] | --keep-boundaries]]
Prints the build() dict as JSON (with a "blocks" list of 5-minute blocks over the merged
window when --blocks is given, and a "light" list of light-blast windows when --run-dir is
given; without --run-dir the output is what it always was). Exits 1 when build() reports
problems, 2 on bad input.

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

# Light-load arm defaults (benchmark/config.sh BENCH_LIGHT_WARMUP_SECS, _DURATION_SECS,
# _COOLDOWN_SECS, BENCH_WINDOW), used only by the blasts[] fallback of light_windows().
LIGHT_WARMUP_SECS = 60
LIGHT_DURATION_SECS = 360
LIGHT_COOLDOWN_SECS = 60
DEFAULT_WINDOW = 16
# Seconds dropped on each side of an epoch boundary from the light windows (the command line's
# default; --exclude-boundaries SECS changes it, --keep-boundaries turns it off).
EXCLUDE_SECS = 30
# The light blast the floor KPIs read: 8 senders per generator at the default window.
FLOOR_LIGHT = "light8"


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


def _unix(ts) -> Optional[int]:
    """'2026-11-05T09:08:29Z' (or unix seconds) -> unix seconds, or None."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return int(ts)
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        d = datetime.datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp())


def light_name(senders, window) -> str:
    """'light8' for 8 senders at the default window 16, 'light600x4' for 600 at window 4."""
    w = DEFAULT_WINDOW if window in (None, "") else int(window)
    return "light%d" % int(senders) if w == DEFAULT_WINDOW else "light%dx%d" % (int(senders), w)


def _archive_dir(run_dir: str, index: int) -> Optional[str]:
    """The newest blast-<index>-<UTC>/ under run_dir holding blasters/*.json, else the newest
    blast-<index>-<UTC>/ at all (UTC stamps sort), else None."""
    dirs = sorted(d for d in glob.glob(os.path.join(run_dir, "blast-%d-*" % index))
                  if os.path.isdir(d) and not os.path.islink(d))
    full = [d for d in dirs if glob.glob(os.path.join(d, "blasters", "*.json"))]
    return (full or dirs or [None])[-1]


def light_blasts(run_dir: str, manifest: dict) -> List[dict]:
    """The light blasts of a light-load arm, in blasts[] order, from the live manifest.

    Light = a blasts[] entry with chaos off whose index is not the blast at the top of the
    results dir (manifest.blast.run_index, the configured profile's). Each entry is
    {name, index, senders, window, rc, started, ended, dir}; dir is its blast-<index>-<UTC>/
    (None when nothing was archived). A run without blasts[] has none."""
    top = ((manifest or {}).get("blast") or {}).get("run_index")
    out = []
    for e in (manifest or {}).get("blasts") or []:
        if not isinstance(e, dict) or e.get("index") is None or e.get("senders") is None:
            continue
        if e.get("chaos") not in (0, False, None) or e.get("index") == top:
            continue
        idx = int(e["index"])
        out.append({"name": light_name(e["senders"], e.get("window")), "index": idx,
                    "senders": int(e["senders"]),
                    "window": DEFAULT_WINDOW if e.get("window") in (None, "") else int(e["window"]),
                    "rc": e.get("rc"), "started": e.get("started"), "ended": e.get("ended"),
                    "dir": _archive_dir(run_dir, idx)})
    return out


def floor_blast(run_dir: str, manifest: dict) -> Tuple[Optional[dict], List[str]]:
    """(the first light8 blast that ended rc 0 and has archived blasters, caveats). No light
    blast in blasts[] at all is (None, []): the run had no light-load arm."""
    caveats = []
    for b in light_blasts(run_dir, manifest):
        if b["name"] != FLOOR_LIGHT:
            continue
        if b["rc"] not in (0, None):
            caveats.append("%s blast (index %d) ended rc=%s; floor KPIs not computed from it"
                           % (b["name"], b["index"], b["rc"]))
            continue
        if b["dir"] is None or not glob.glob(os.path.join(b["dir"], "blasters", "*.json")):
            caveats.append("%s blast (index %d) has no archived blast-%d-*/blasters/*.json; floor KPIs "
                           "not computed from it" % (b["name"], b["index"], b["index"]))
            continue
        return b, []
    return None, caveats


def boundaries(blasters: List[dict]) -> List[int]:
    """Epoch boundaries: the timestamps of the blocks whose closes_epoch cell is set, from every
    blaster's block table (columns read by name), sorted and unique."""
    out = set()
    for b in blasters:
        blk = b.get("blocks") or {}
        cols = blk.get("columns") or []
        if "closes_epoch" not in cols or "timestamp" not in cols:
            continue
        ci, ti = cols.index("closes_epoch"), cols.index("timestamp")
        for r in blk.get("rows") or []:
            if len(r) > max(ci, ti) and r[ci] and r[ti] is not None:
                out.add(int(r[ti]))
    return sorted(out)


def subtract(start: int, end: int, cuts: List[int], secs: int) -> List[dict]:
    """[start, end) minus [b - secs, b + secs) for every b in cuts, as half-open intervals."""
    spans = [(start, end)]
    for b in sorted(cuts):
        lo, hi = b - secs, b + secs
        nxt = []
        for s, e in spans:
            if hi <= s or lo >= e:
                nxt.append((s, e))
                continue
            if s < lo:
                nxt.append((s, lo))
            if hi < e:
                nxt.append((hi, e))
        spans = nxt
    return [{"start_unix": s, "end_unix": e, "secs": e - s} for s, e in spans if e > s]


def _phase_secs(phases, name) -> Optional[int]:
    p = next((p for p in phases or [] if isinstance(p, dict) and p.get("name") == name), None)
    lo, hi = _unix((p or {}).get("start")), _unix((p or {}).get("end"))
    return hi - lo if lo is not None and hi is not None and hi >= lo else None


def light_window(blast: dict, exclude_secs: Optional[int] = None) -> dict:
    """One light blast's mixed window (see the module docstring for the sources, in order)."""
    out = {k: blast.get(k) for k in ("name", "index", "senders", "window")}
    d = blast.get("dir")
    docs = load_blasters(os.path.join(d, "blasters")) if d else []
    mixed = mixed_windows(docs)
    manifest = {}
    if d and os.path.isfile(os.path.join(d, "manifest.json")):
        try:
            with open(os.path.join(d, "manifest.json")) as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            manifest = {}
    phases = manifest.get("phases") if isinstance(manifest, dict) else None
    span, source = None, None
    if mixed:
        m = merged(mixed)
        span, source = (m["start_unix"], m["end_unix"]), "blasters"
    else:
        p = next((p for p in phases or [] if isinstance(p, dict) and p.get("name") == "mixed"), None)
        lo, hi = _unix((p or {}).get("start")), _unix((p or {}).get("end"))
        if lo is not None and hi is not None and hi > lo:
            span, source = (lo, hi), "manifest.phases"
        else:
            warm = _phase_secs(phases, "warmup")
            cool = _phase_secs(phases, "cooldown")
            warm = LIGHT_WARMUP_SECS if warm is None else warm
            cool = LIGHT_COOLDOWN_SECS if cool is None else cool
            lo, hi = _unix(blast.get("started")), _unix(blast.get("ended"))
            if lo is not None:
                lo += warm
                hi = hi - cool if hi is not None else lo + LIGHT_DURATION_SECS
                if hi > lo:
                    span, source = (lo, hi), "blasts[] (approximate)"
    if span is None:
        out.update(start_unix=None, end_unix=None, secs=None, source=None, boundaries=[])
        return out
    out.update(start_unix=span[0], end_unix=span[1], secs=span[1] - span[0], source=source)
    pad = exclude_secs or 0
    cuts = [b for b in boundaries(docs) if span[0] - pad <= b < span[1] + pad]
    out["boundaries"] = cuts
    if exclude_secs is not None:
        out["exclude_secs"] = exclude_secs
        out["intervals"] = subtract(span[0], span[1], cuts, exclude_secs)
        out["kept_secs"] = sum(i["secs"] for i in out["intervals"])
    return out


def light_windows(run_dir: str, manifest: dict, exclude_secs: Optional[int] = None) -> List[dict]:
    """light_window() for every light blast of the run, in blasts[] order."""
    return [light_window(b, exclude_secs) for b in light_blasts(run_dir, manifest)]


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
    ap.add_argument("--run-dir", help="results/<run>: also print the light blasts' windows (manifest blasts[])")
    eb = ap.add_mutually_exclusive_group()
    eb.add_argument("--exclude-boundaries", type=int, nargs="?", const=EXCLUDE_SECS, metavar="SECS",
                    help="drop SECS (default %d, also without this flag) on each side of every epoch boundary "
                         "from the light windows (needs --run-dir)" % EXCLUDE_SECS)
    eb.add_argument("--keep-boundaries", action="store_true",
                    help="keep the blocks near an epoch boundary in the light windows (needs --run-dir)")
    args = ap.parse_args(argv)
    for flag, given in (("--exclude-boundaries", args.exclude_boundaries is not None),
                        ("--keep-boundaries", args.keep_boundaries)):
        if given and not args.run_dir:
            ap.error("%s needs --run-dir" % flag)
    if args.exclude_boundaries is not None and args.exclude_boundaries < 0:
        ap.error("--exclude-boundaries SECS must not be negative")
    excl = EXCLUDE_SECS if args.exclude_boundaries is None else args.exclude_boundaries
    excl = None if args.keep_boundaries else excl
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
    if args.run_dir:
        try:
            with open(os.path.join(args.run_dir, "manifest.json")) as f:
                manifest = json.load(f)
            out["light"] = light_windows(args.run_dir, manifest, excl)
        except (OSError, ValueError) as e:
            print("windows.py: %s" % e, file=sys.stderr)
            return 2
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
