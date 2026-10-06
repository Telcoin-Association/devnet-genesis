#!/usr/bin/env python3
"""Find commit stalls in a run's sampler CSVs: stretches where the fleet's highest block stood still.

Reads results/<run>/sampler/*.csv (node-sampler.sh: ts_unix and block columns, one row per node
every 30 s) and the planned phases in results/<run>/manifest.json, and prints a JSON array for
manifest.commit_stalls_sampled. The fleet maximum is taken per 30 s bucket. A stretch counts when
it starts inside the mixed phase, lasts at least --min-secs and ends (or the window does) by the
end of cooldown; one that starts in cooldown is the generator's drain, not a stall. A note only:
benchmark-blast.sh never aborts on it.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def iso(unix):
    return datetime.fromtimestamp(unix, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unix(text):
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def phase_window(manifest):
    """(mixed start, mixed end, cooldown end) from the planned manifest.phases."""
    phases = {p.get("name"): p for p in manifest.get("phases") or [] if isinstance(p, dict)}
    try:
        return unix(phases["mixed"]["start"]), unix(phases["mixed"]["end"]), unix(phases["cooldown"]["end"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"manifest.phases lacks a mixed/cooldown window: {error}") from None


def read_samples(paths):
    """(ts_unix, block) of every row with both values; a file without a block column adds none."""
    samples = []
    for path in paths:
        with open(path, newline="") as stream:
            for row in csv.DictReader(stream):
                ts, block = (row.get("ts_unix") or "").strip(), (row.get("block") or "").strip()
                if ts.isdigit() and block.isdigit():
                    samples.append((int(ts), int(block)))
    return samples


def fleet_max(samples, start, end, bucket):
    """{bucket start: highest block any node reported in it}, for samples inside [start, end]."""
    out = {}
    for ts, block in samples:
        if start <= ts <= end:
            key = ts - ts % bucket
            out[key] = max(out.get(key, block), block)
    return out


def flat_stretches(series, mixed_end, min_secs):
    """Stretches where the running fleet maximum did not rise for at least min_secs."""
    out = []
    keys = sorted(series)
    block = since = None

    def add(end, still_open):
        if since < mixed_end and end - since >= min_secs:
            entry = dict(start=iso(since), end=iso(end), secs=end - since, block=block, source="sampler")
            if still_open:
                entry["open"] = True
            out.append(entry)

    for key in keys:
        if block is None or series[key] > block:
            if block is not None:
                add(key, False)
            block, since = series[key], key
    if block is not None:
        add(keys[-1], True)
    return out


def scan(results, min_secs, bucket=30):
    manifest = json.loads((results / "manifest.json").read_text())
    start, mixed_end, end = phase_window(manifest)
    samples = read_samples(sorted((results / "sampler").glob("*.csv")))
    return flat_stretches(fleet_max(samples, start, end, bucket), mixed_end, min_secs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", required=True, type=Path, help="results/<run> directory")
    parser.add_argument("--min-secs", type=int, default=60)
    parser.add_argument("--bucket-secs", type=int, default=30)
    args = parser.parse_args(argv)
    if args.min_secs <= 0 or args.bucket_secs <= 0:
        parser.error("--min-secs and --bucket-secs must be positive")
    try:
        print(json.dumps(scan(args.results, args.min_secs, args.bucket_secs)))
    except (OSError, ValueError) as error:
        print(f"stall-scan: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
