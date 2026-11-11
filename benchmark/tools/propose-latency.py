#!/usr/bin/env python3
"""Per node: time from `header proposed` to the node's own `quorum reached`, and the round period.

Usage: propose-latency.py --logs DIR [--node-glob GLOB] [--node-name-regex RE]
                          [--windows MANIFEST | --from ISO --to ISO]

Reads every file in DIR matching --node-glob (gzip or plain logfmt; default bench-validator-*.log.gz:
each validator's container logs, the container logs saved before a restart, and the unit's stdout
file, which spans every restart of the run) and groups them by node (group 1 of --node-name-regex
on the file name; default ^(bench-validator-[0-9]+)-), as cert-rate.py does. An event line found in
more than one file of a node counts once. Proposals and quorums pair by (epoch, round). Per node and
window it prints: proposals, certified, rate, C p50/p90/p95 (propose -> own quorum, ms), round
period p50/p95 (ms, consecutive proposals), own quorum -> next proposal p50/p95, and `Canceled`
vote errors. This is the calibration input of cadence-model.py (the processing residual is C minus
the UDP RTT to the 6th-nearest voter).

Windows: --windows MANIFEST takes manifest.param_arms[] ({name, begin|start, end}; from `ready`
instead of begin when the arm records it, and each marks[] {label, begin, end} as
"mark <arm>/<label>") and manifest.phases[] ({name, start, end}) plus one "run" window from the
first start to the last end, one table each; an arm or phase without an end is left out. Bench-6
blasts[] entries that carry `phases` add each rc-0 blast's phases as "blast <index> <phase>"; a
failed blast (rc not 0) gets a note instead, and the top-level phases, a copy of the latest entry's,
are not read twice. --from/--to is one window (either end
may be left out); a full UTC time (2026-10-06T23:50:00Z), or HH:MM:SS when every event of the logs
falls on one UTC day. Default: the whole log. A window holds start <= t < end.

Exit status: 0 = report written; 1 = bad arguments or unreadable input; 2 = no file matched.
Stdlib only.
"""
import argparse
import calendar
import collections
import fnmatch
import gzip
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

# The time and file helpers are cert-rate.py's (TS_RE, parse_iso, line_ts, open_text, find_files).
TS_RE = re.compile(r"^(?:ts=)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?")
TOD_RE = re.compile(r"^(\d\d):(\d\d):(\d\d)(\.\d+)?$")
ROUND_RE = re.compile(r" round=(\d+)")
EPOCH_RE = re.compile(r" epoch=(\d+)")
PROPOSED, QUORUM = 'message="header proposed"', 'message="quorum reached"'


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def line_ts(m):
    y, mo, d, h, mi, s, frac = m.groups()
    t = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s)))
    return t + (float(frac) if frac else 0.0)


def parse_iso(text):
    """Seconds since the epoch of an ISO-8601 UTC time (Z or +00:00; fraction optional)."""
    m = TS_RE.match(text.strip())
    rest = text.strip()[m.end():] if m else ""
    if not m or rest not in ("", "Z", "+00:00"):
        raise ValueError("not an ISO-8601 UTC time: %r" % text)
    return line_ts(m)


def open_text(path):
    """A text stream of <path>, gunzipped when it starts with the gzip magic."""
    with open(path, "rb") as fh:
        magic = fh.read(2)
    raw = gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace")


def find_files(logs, glob, name_re):
    """{node: [paths]} for the files in <logs> whose name matches <glob>, named by <name_re>."""
    groups = collections.OrderedDict()
    for f in sorted(os.listdir(logs)):
        p = os.path.join(logs, f)
        if not os.path.isfile(p) or not fnmatch.fnmatch(f, glob):
            continue
        m = name_re.search(f)
        groups.setdefault(m.group(1) if m and m.groups() else f, []).append(p)
    return groups


class Node(object):
    """The events of one node, from all of its files, each counted once."""

    def __init__(self, name):
        self.name = name
        self.files = []
        self.proposed = []        # (ts, epoch, round); epoch -1 when the line has none
        self.quorum = []          # (ts, epoch, round)
        self.canceled = []        # ts
        self._seen = set()

    def read(self, path):
        with open_text(path) as fh:
            for line in fh:
                if PROPOSED in line:
                    kind = self.proposed
                elif QUORUM in line:
                    kind = self.quorum
                elif "failed to get vote for header" in line and "Canceled" in line:
                    kind = self.canceled
                else:
                    continue
                m = TS_RE.match(line)
                if not m:
                    continue
                key = hash(line.rstrip("\r\n"))
                if key in self._seen:          # the same line from another file of this node
                    continue
                self._seen.add(key)
                t = line_ts(m)
                if kind is self.canceled:
                    kind.append(t)
                    continue
                r = ROUND_RE.search(line)
                if r:
                    e = EPOCH_RE.search(line)
                    kind.append((t, int(e.group(1)) if e else -1, int(r.group(1))))
        self.files.append(os.path.basename(path))

    def finish(self):
        self.proposed.sort()
        self.quorum.sort()
        self.canceled.sort()
        self._seen = set()

    def times(self):
        return [x[0] for x in self.proposed] + [x[0] for x in self.quorum] + self.canceled


def inside(t, start, end):
    return (start is None or t >= start) and (end is None or t < end)


def analyse(node, start, end):
    """The node's numbers for the window: the pairing of the old single-file tool, keyed by (epoch,
    round). Proposals of a round after the first (re-proposals) only feed the period."""
    prop, quor, rounds = {}, {}, []
    for t, e, r in node.proposed:
        if inside(t, start, end):
            prop.setdefault((e, r), t)
            rounds.append((e, r, t))
    for t, e, r in node.quorum:
        if inside(t, start, end):
            quor.setdefault((e, r), t)
    canc = sum(1 for t in node.canceled if inside(t, start, end))
    C = [(quor[k] - prop[k]) * 1000 for k in prop if k in quor]
    gap = [(prop[(e, r + 1)] - quor[(e, r)]) * 1000 for (e, r) in quor
           if (e, r + 1) in prop and prop[(e, r + 1)] > quor[(e, r)]]
    rounds.sort()
    per = [(rounds[i + 1][2] - rounds[i][2]) * 1000 for i in range(len(rounds) - 1)
           if rounds[i + 1][0] == rounds[i][0] and rounds[i + 1][1] == rounds[i][1] + 1]
    return {"proposed": len(prop), "certified": len(C), "C": C, "period": per, "canceled": canc, "gap": gap}


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))]) if xs else None


def fmt(x):
    return "—" if x is None else str(x)


def blast_phase_windows(m):
    """(windows, notes, top_copied) from the bench-6 blasts[] entries that carry `phases`: each rc-0
    entry's phases as "blast <index> <phase>"; an entry with another rc is a note, never a window.
    top_copied: the top-level phases are a copy of one of these entries (the latest blast's), so they
    are read there and not twice. A manifest whose entries carry no `phases` (bench 5) gives nothing."""
    out, notes, top_copied = [], [], False
    for b in m.get("blasts") or []:
        if not isinstance(b, dict) or not isinstance(b.get("phases"), list):
            continue
        top_copied = top_copied or b["phases"] == m.get("phases")
        if b.get("rc") not in (None, 0):
            notes.append("blast %s: rc %s, not measured" % (b.get("index"), b.get("rc")))
            continue
        for p in b["phases"]:
            if isinstance(p, dict) and p.get("start") and p.get("end"):
                out.append(("blast %s %s" % (b.get("index"), p.get("name") or "?"), parse_iso(p["start"]),
                            parse_iso(p["end"])))
    return out, notes, top_copied


def manifest_windows(path):
    """(windows, notes) from manifest.param_arms[], .phases[] and the bench-6 blasts[] phases
    (blast_phase_windows) plus a "run" window.

    An arm's window starts at its `ready` (bench 6) when recorded, else at `begin`; each of its
    `marks[]` with a begin and an end is a sub-window "mark <arm>/<label>" after it."""
    with open(path) as fh:
        m = json.load(fh)
    out, notes = [], []
    blasts, bnotes, top_copied = blast_phase_windows(m)
    for key, label in (("param_arms", "arm"), ("phases", "phase")):
        for w in (m.get(key) or []) if not (key == "phases" and top_copied) else []:
            if not isinstance(w, dict):
                continue
            name = "%s %s" % (label, w.get("name") or "?")
            begin, end = w.get("begin") or w.get("start"), w.get("end")
            if key == "param_arms" and w.get("ready"):
                begin = w["ready"]
            if begin and end:
                out.append((name, parse_iso(begin), parse_iso(end)))
            else:
                notes.append("%s has no %s: left out" % (name, "end" if begin else "begin"))
            for mk in (w.get("marks") or []) if key == "param_arms" else []:
                if isinstance(mk, dict) and mk.get("begin") and mk.get("end"):
                    out.append(("mark %s/%s" % (w.get("name") or "?", mk.get("label") or "?"),
                                parse_iso(mk["begin"]), parse_iso(mk["end"])))
    out.extend(blasts)
    notes.extend(bnotes)
    if not out:
        raise ValueError("%s has no param_arms or phases with a begin and an end" % path)
    out.append(("run", min(w[1] for w in out), max(w[2] for w in out)))
    return out, notes


def bound(text, flag, nodes):
    """A --from/--to value: a full UTC time, or HH:MM:SS on the one UTC day the logs' events cover."""
    if text is None:
        return None
    text = text.strip()
    if not TOD_RE.match(text):
        return parse_iso(text)
    ts = [t for n in nodes for t in n.times()]
    if not ts:
        raise ValueError("%s %s is a time of day and the logs have no event to take the date from: "
                         "give a full UTC time (YYYY-MM-DDT%sZ)" % (flag, text, text))
    first, last = iso(min(ts))[:10], iso(max(ts))[:10]
    if first != last:
        raise ValueError("%s %s is a time of day, but the logs span %s to %s: give a full UTC time "
                         "(%sT%sZ or %sT%sZ)" % (flag, text, first, last, first, text, last, text))
    return parse_iso("%sT%s" % (first, text))


def table(nodes, start, end):
    out = ["| node | proposed | certified | rate % | C p50/p90/p95 ms | period p50/p95 ms | quorum->next p50/p95 ms | canceled |",
           "|---|---:|---:|---:|---|---|---|---:|"]
    absent = []
    for n in nodes:
        s = analyse(n, start, end)
        rate = "%.1f" % (100.0 * s["certified"] / s["proposed"]) if s["proposed"] else "—"
        out.append("| %s | %d | %d | %s | %s/%s/%s | %s/%s | %s/%s | %d |" % (
            n.name, s["proposed"], s["certified"], rate, fmt(pct(s["C"], .5)), fmt(pct(s["C"], .9)), fmt(pct(s["C"], .95)),
            fmt(pct(s["period"], .5)), fmt(pct(s["period"], .95)), fmt(pct(s["gap"], .5)), fmt(pct(s["gap"], .95)), s["canceled"]))
        ts = n.times()
        if not any(inside(t, start, end) for t in ts):
            absent.append("- %s: no event in this window (its files span %s)"
                          % (n.name, "%s → %s" % (iso(min(ts)), iso(max(ts))) if ts else "no event at all"))
    return out + ([""] + absent if absent else [])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", required=True, help="directory holding the node logs")
    ap.add_argument("--node-glob", default="bench-validator-*.log.gz",
                    help="file names to read (fnmatch; default %(default)s)")
    ap.add_argument("--node-name-regex", default=r"^(bench-validator-[0-9]+)-",
                    help="group 1 on the file name is the node (default %(default)s)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--windows", metavar="MANIFEST", help="manifest.json: param_arms[] and phases[]")
    g.add_argument("--from", dest="lo", metavar="ISO|HH:MM:SS", help="start of the one window")
    ap.add_argument("--to", dest="hi", metavar="ISO|HH:MM:SS", help="end of the one window")
    a = ap.parse_args(argv)
    if a.windows and a.hi:
        ap.error("--to goes with --from, not with --windows")
    try:
        name_re = re.compile(a.node_name_regex)
    except re.error as e:
        ap.error("--node-name-regex: %s" % e)
    try:
        notes = []
        windows = None
        if a.windows:
            windows, notes = manifest_windows(a.windows)
        groups = find_files(a.logs, a.node_glob, name_re)
        if not groups:
            print("propose-latency: no file in %s matches %s" % (a.logs, a.node_glob), file=sys.stderr)
            return 2
        nodes = []
        for name, paths in groups.items():
            n = Node(name)
            for p in paths:
                n.read(p)
            n.finish()
            nodes.append(n)
        if windows is None:
            lo, hi = bound(a.lo, "--from", nodes), bound(a.hi, "--to", nodes)
            if lo is not None and hi is not None and hi <= lo:
                raise ValueError("--to must be after --from")
            windows = [("window" if lo is not None or hi is not None else "whole log", lo, hi)]
    except (OSError, ValueError, EOFError) as e:
        print("propose-latency: %s" % e, file=sys.stderr)
        return 1
    out = ["Logs: %s." % ", ".join("%s (%s)" % (n.name, ", ".join(n.files)) for n in nodes)]
    out += ["- " + note for note in notes]
    for name, start, end in windows:
        span = "%s → %s" % ("start of log" if start is None else iso(start), "end of log" if end is None else iso(end))
        if start is not None and end is not None:
            span += " (%d s)" % int(end - start)
        out += ["", "## %s: %s" % (name, span), ""] + table(nodes, start, end)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
