#!/usr/bin/env python3
"""Per-validator certification rate from telcoin node logs, per time window.

Usage:
  cert-rate.py --logs DIR [--node-glob GLOB] [--node-name-regex RE] [--authority NODE=ID ...]
               [--windows MANIFEST | --from ISO --to ISO | --bucket-min N] [--format md|json|csv]
  cert-rate.py --from-json REPORT [--format md|json|csv]

Reads every file in DIR matching --node-glob (gzip or plain text; default bench-validator-*.log.gz:
each validator's container logs, the container logs saved before a restart or kill, and the unit's
stdout file, which alone covers the seconds between a pre-kill save and the kill), groups them by
node (group 1 of --node-name-regex on the file name; default ^(bench-validator-[0-9]+)-) and counts,
per node and window, from the default log filter (an event line found in two files of a node counts
once):

  proposed        "header proposed"                 own headers proposed (re-proposals included)
  quorum          "quorum reached"                  own headers that formed a certificate
  rate %          quorum / proposed
  re-proposals    "re-proposing last header"
  vote errors     "failed to get vote for header"   every vote request that failed
  canceled        ... ending "): Canceled"          the subset cancelled by a newer proposal
  could not form  "Could not form a certificate"
  subdags         "subdag committed"                subdags this node committed
  own cert %      share of the certificates committed in the window ("certificate committed
                  origin=") whose origin is this node's authority
  own leader %    share of the window's committed leaders that are this node's: a subdag's leader
                  is its certificate committed at round == leader_round
  not committed % own certificates formed in the window that this node never logged as
                  committed (epoch from subdag_index >> 32, round): never reached by a committed
                  leader. Certificates formed after the node's last logged commit are not judged.

The node's authority comes from the auth= field of its certifier lines (the most frequent value),
or from --authority. Without one, the two share columns and "not committed" stay empty. Strict
orphans (certificates no later header lists as a parent) need the parents of every header, which
the default filter does not log: run the node with RUST_LOG including primary=debug and the
header's parents appear in the proposer's debug lines; "not committed" is the default-filter proxy.

Windows: --windows MANIFEST takes manifest.param_arms[] ({name, ready|begin|start, end}; each of
its marks[] {label, begin, end}, e.g. an idle mark, as "mark <arm>/<label>" after it) and
manifest.phases[] ({name, start, end}) plus one "run" window from the first start to the last end;
a manifest with neither falls back to buckets. An arm's window starts at its "ready" time when the
manifest records one (the last node's progress after its restart, plus 120 s), else at its begin; an
arm whose ready time is not before its end has no window (a note says so). Bench-6 blasts[] entries
that carry `phases` add each rc-0 blast's phases as "blast <index> <phase>"; a failed blast (rc not
0) gets a note instead, and the top-level phases, a copy of the latest entry's, are not read twice.
--from/--to is one window. Default (or --bucket-min N): the whole log in N-minute buckets (N = 10).

--from-json REPORT renders a report this tool wrote with --format json (the teardown's
analysis/certification.json) as md, json or csv, reading no log: the same bytes as the run that
wrote it would have printed in that format.

Exit status: 0 = report written; 1 = bad arguments or unreadable input (a --from-json file that is
not a cert-rate report included); 2 = no file matched.
Stdlib only.
"""
import argparse
import bisect
import calendar
import collections
import csv
import fnmatch
import gzip
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

TS_RE = re.compile(r"^(?:ts=)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?")
EVENT_RE = re.compile(r"header proposed|quorum reached|re-proposing last header|failed to get vote for header"
                      r"|Could not form a certificate|subdag committed|certificate committed")
ROUND_RE = re.compile(r"\bround=(\d+)")
EPOCH_RE = re.compile(r"\bepoch=(\d+)")
ORIGIN_RE = re.compile(r"\borigin=([1-9A-HJ-NP-Za-km-z]+)")
LEADER_RE = re.compile(r"\bleader_round=(\d+)")
INDEX_RE = re.compile(r"\bsubdag_index=(\d+)")
AUTH_RE = re.compile(r"\bauth=([1-9A-HJ-NP-Za-km-z]{20,})")

COUNTS = ("proposed", "quorum", "repropose", "vote_errors", "canceled", "noform", "subdags")
COLUMNS = (("proposed", "proposed"), ("quorum", "quorum"), ("rate_pct", "rate %"),
           ("repropose", "re-proposals"), ("vote_errors", "vote errors"), ("canceled", "canceled"),
           ("noform", "could not form"), ("subdags", "subdags"), ("committed_certs", "certs committed"),
           ("own_cert_pct", "own cert %"), ("own_leader_pct", "own leader %"),
           ("not_committed_pct", "not committed %"))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    """Seconds since the epoch of an ISO-8601 UTC time (Z or +00:00; fraction optional)."""
    m = TS_RE.match(text.strip())
    rest = text.strip()[m.end():] if m else ""
    if not m or rest not in ("", "Z", "+00:00"):
        raise ValueError("not an ISO-8601 UTC time: %r" % text)
    return line_ts(m)


def line_ts(m):
    y, mo, d, h, mi, s, frac = m.groups()
    t = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s)))
    return t + (float(frac) if frac else 0.0)


def open_text(path):
    """A text stream of <path>, gunzipped when it starts with the gzip magic."""
    with open(path, "rb") as fh:
        magic = fh.read(2)
    raw = gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace")


class Node(object):
    """Every event of one node, from all of its files."""

    def __init__(self, name):
        self.name = name
        self.files = []
        self.times = {k: [] for k in COUNTS}
        self.formed = []          # (ts, epoch, round) of own certificates ("quorum reached")
        self.committed = []       # (ts, epoch, round, origin) of every certificate it committed
        self.leaders = []         # (ts, origin or None) per subdag committed
        self.auth = collections.Counter()
        self.authority = None
        self.last_commit_ts = None
        self._seen = set()

    def read(self, path):
        pending = []              # certificates committed since the last "subdag committed"
        with open_text(path) as fh:
            for line in fh:
                ev = EVENT_RE.search(line)
                if not ev:
                    continue
                m = TS_RE.match(line)
                if not m:
                    continue
                key = hash(line)
                if key in self._seen:          # the same line from another copy of the log
                    continue
                self._seen.add(key)
                self.event(ev.group(), line_ts(m), line, pending)
        self.files.append(os.path.basename(path))

    def event(self, kind, ts, line, pending):
        if kind == "header proposed":
            self.times["proposed"].append(ts)
        elif kind == "quorum reached":
            self.times["quorum"].append(ts)
            r, e = ROUND_RE.search(line), EPOCH_RE.search(line)
            if r and e:
                self.formed.append((ts, int(e.group(1)), int(r.group(1))))
        elif kind == "re-proposing last header":
            self.times["repropose"].append(ts)
        elif kind == "failed to get vote for header":
            self.times["vote_errors"].append(ts)
            if "): Canceled" in line:
                self.times["canceled"].append(ts)
            self.note_auth(line)
        elif kind == "Could not form a certificate":
            self.times["noform"].append(ts)
            self.note_auth(line)
        elif kind == "certificate committed":
            r, o = ROUND_RE.search(line), ORIGIN_RE.search(line)
            if r and o:
                pending.append((ts, int(r.group(1)), o.group(1)))
        elif kind == "subdag committed":
            self.times["subdags"].append(ts)
            idx, lr = INDEX_RE.search(line), LEADER_RE.search(line)
            epoch = int(idx.group(1)) >> 32 if idx else None
            leader = None
            if lr:
                at = [o for _, r, o in pending if r == int(lr.group(1))]
                leader = at[0] if len(at) == 1 else None
            for cts, r, o in pending:
                self.committed.append((cts, epoch, r, o))
            self.leaders.append((ts, leader))
            self.last_commit_ts = ts
            del pending[:]

    def note_auth(self, line):
        a = AUTH_RE.search(line)
        if a:
            self.auth[a.group(1)] += 1

    def finish(self, override=None):
        for k in self.times:
            self.times[k].sort()
        self.formed.sort()
        self.committed.sort(key=lambda c: c[0])
        self.leaders.sort(key=lambda c: c[0])
        self._seen = set()
        if override:
            self.authority = override
        elif self.auth:
            self.authority = self.auth.most_common(1)[0][0]

    def span(self):
        ts = [v[0] for v in self.times.values() if v] + [v[-1] for v in self.times.values() if v]
        return (min(ts), max(ts)) if ts else None


def count(sorted_ts, start, end):
    return bisect.bisect_left(sorted_ts, end) - bisect.bisect_left(sorted_ts, start)


def in_window(rows, start, end):
    """The rows (sorted by their first field, a time) with start <= time < end."""
    keys = [r[0] for r in rows]
    return rows[bisect.bisect_left(keys, start):bisect.bisect_left(keys, end)]


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def node_window(node, start, end, committed_own):
    out = {k: count(node.times[k], start, end) for k in COUNTS}
    out["rate_pct"] = pct(out["quorum"], out["proposed"])
    certs = in_window(node.committed, start, end)
    leaders = [lead for _, lead in in_window(node.leaders, start, end) if lead]
    out["committed_certs"] = len(certs)
    out["committee_seen"] = len({c[3] for c in certs})
    if node.authority:
        out["own_cert_pct"] = pct(sum(1 for c in certs if c[3] == node.authority), len(certs))
        out["own_leader_pct"] = pct(sum(1 for lead in leaders if lead == node.authority), len(leaders))
        judged = [f for f in in_window(node.formed, start, end)
                  if node.last_commit_ts is not None and f[0] <= node.last_commit_ts]
        out["formed_judged"] = len(judged)
        out["not_committed_pct"] = pct(sum(1 for f in judged if (f[1], f[2]) not in committed_own), len(judged))
    else:
        out["own_cert_pct"] = out["own_leader_pct"] = out["not_committed_pct"] = None
    return out


def fleet_row(rows):
    out = {k: sum(r[k] for r in rows) for k in COUNTS}
    out["rate_pct"] = pct(out["quorum"], out["proposed"])
    out["committed_certs"] = max((r["committed_certs"] for r in rows), default=0)
    out["own_cert_pct"] = out["own_leader_pct"] = out["not_committed_pct"] = None
    return out


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
    """(windows, note) from manifest.param_arms[] (each arm's marks[] after it), .phases[] and the
    bench-6 blasts[] phases (blast_phase_windows) plus a "run" window."""
    with open(path) as fh:
        m = json.load(fh)
    out, notes = [], []
    blasts, bnotes, top_copied = blast_phase_windows(m)
    for key, label in (("param_arms", "arm"), ("phases", "phase")):
        for w in (m.get(key) or []) if not (key == "phases" and top_copied) else []:
            if not isinstance(w, dict):
                continue
            begin, end = w.get("begin") or w.get("start"), w.get("end")
            ready = w.get("ready") if key == "param_arms" else None
            name = "%s %s" % (label, w.get("name") or "?")
            marks = [("mark %s/%s" % (w.get("name") or "?", mk.get("label") or "?"), parse_iso(mk["begin"]),
                      parse_iso(mk["end"])) for mk in ((w.get("marks") or []) if key == "param_arms" else [])
                     if isinstance(mk, dict) and mk.get("begin") and mk.get("end")]
            if ready and end:
                # An arm is measured from ready (its last node back in step) to its end.
                if parse_iso(ready) >= parse_iso(end):
                    notes.append("%s: ready %s is not before its end %s: no window" % (name, ready, end))
                    out.extend(marks)
                    continue
                begin = ready
            if begin and end:
                out.append((name, parse_iso(begin), parse_iso(end)))
            out.extend(marks)
    out.extend(blasts)
    notes.extend(bnotes)
    if not out:
        return None, notes + ["%s has no param_arms or phases: 10-minute buckets instead" % os.path.basename(path)]
    out.append(("run", min(w[1] for w in out), max(w[2] for w in out)))
    return out, notes


def buckets(nodes, minutes):
    spans = [n.span() for n in nodes if n.span()]
    if not spans:
        return []
    step = minutes * 60
    first = int(min(s[0] for s in spans)) // step * step
    last = max(s[1] for s in spans)
    out = []
    t = first
    while t <= last:
        out.append((iso(t)[:16] + "Z", t, t + step))
        t += step
    return out


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


def report(nodes, windows, notes):
    doc = {"windows": [], "notes": notes,
           "nodes": {n.name: {"files": n.files, "authority": n.authority,
                              "authority_source": ("--authority" if n.authority and n.authority not in n.auth
                                                   else "auth= field" if n.authority else None)}
                     for n in nodes}}
    committed_own = {}
    for n in nodes:
        committed_own[n.name] = {(c[1], c[2]) for c in n.committed if c[3] == n.authority}
    for name, start, end in windows:
        rows = collections.OrderedDict((n.name, node_window(n, start, end, committed_own[n.name])) for n in nodes)
        doc["windows"].append({"name": name, "start": iso(start), "end": iso(end), "secs": int(end - start),
                               "nodes": rows, "fleet": fleet_row(list(rows.values()))})
    return doc


def cell(v):
    return "–" if v is None else ("%.1f" % v if isinstance(v, float) else str(v))


def to_markdown(doc):
    out = ["# Certification rate", ""]
    srcs = ", ".join("%s (%s)" % (n, ", ".join(v["files"])) for n, v in doc["nodes"].items())
    out += ["Logs: %s." % srcs, ""]
    for n, v in doc["nodes"].items():
        if not v["authority"]:
            out.append("- %s: authority unknown (no auth= line; pass --authority %s=<id>): no share columns." % (n, n))
    for note in doc["notes"]:
        out.append("- " + note)
    out += ["- own cert % / own leader %: fair share is 100 / committee size; \"not committed %\" is own "
            "certificates formed in the window that the node never logged as committed (the default-filter "
            "proxy for orphans; see tools/ANALYSIS.md).", ""]
    for w in doc["windows"]:
        out += ["## %s: %s → %s (%d s)" % (w["name"], w["start"], w["end"], w["secs"]), ""]
        out.append("| node | authority | " + " | ".join(h for _, h in COLUMNS) + " |")
        out.append("|------|-----------|" + "|".join("-" * (len(h) + 1) + ":" for _, h in COLUMNS) + "|")
        for name, r in w["nodes"].items():
            auth = (doc["nodes"][name]["authority"] or "?")[:8]
            out.append("| %s | %s | %s |" % (name, auth, " | ".join(cell(r[k]) for k, _ in COLUMNS)))
        out.append("| **fleet** | | %s |" % " | ".join(cell(w["fleet"][k]) for k, _ in COLUMNS))
        seen = max((r["committee_seen"] for r in w["nodes"].values()), default=0)
        if seen:
            out += ["", "Committee seen committing in this window: %d authorities (fair share %.1f %%)." % (seen, 100.0 / seen)]
        out.append("")
    return "\n".join(out)


def to_csv(doc):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["window", "start", "end", "node", "authority"] + [k for k, _ in COLUMNS])
    for win in doc["windows"]:
        for name, r in list(win["nodes"].items()) + [("fleet", win["fleet"])]:
            auth = doc["nodes"].get(name, {}).get("authority") or ""
            w.writerow([win["name"], win["start"], win["end"], name, auth] + ["" if r[k] is None else r[k] for k, _ in COLUMNS])
    return buf.getvalue()


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--logs", help="directory holding the node logs (required unless --from-json)")
    p.add_argument("--from-json", metavar="REPORT",
                   help="render a report written with --format json instead of reading logs")
    p.add_argument("--node-glob", default="bench-validator-*.log.gz",
                   help="file names to read (fnmatch; default %(default)s)")
    p.add_argument("--node-name-regex", default=r"^(bench-validator-[0-9]+)-",
                   help="group 1 on the file name is the node (default %(default)s)")
    p.add_argument("--authority", action="append", default=[], metavar="NODE=ID",
                   help="the node's authority id, when its log has no auth= line")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--windows", metavar="MANIFEST", help="manifest.json: param_arms[] and phases[]")
    g.add_argument("--from", dest="start", metavar="ISO", help="one window from ISO (needs --to)")
    g.add_argument("--bucket-min", type=int, metavar="N", help="whole log in N-minute buckets (default 10)")
    p.add_argument("--to", dest="end", metavar="ISO", help="end of the --from window")
    p.add_argument("--format", choices=("md", "json", "csv"), default="md")
    a = p.parse_args(argv)
    if a.from_json is not None:
        if a.logs is not None or a.windows or a.start or a.bucket_min is not None or a.authority:
            p.error("--from-json takes only --format")
    elif a.logs is None:
        p.error("--logs is required (or --from-json REPORT)")
    if (a.start is None) != (a.end is None):
        p.error("--from and --to go together")
    if a.bucket_min is not None and a.bucket_min <= 0:
        p.error("--bucket-min must be positive")
    try:
        a.name_re = re.compile(a.node_name_regex)
    except re.error as e:
        p.error("--node-name-regex: %s" % e)
    a.authorities = {}
    for item in a.authority:
        node, sep, ident = item.partition("=")
        if not sep or not node or not ident:
            p.error("--authority wants NODE=ID, got %r" % item)
        a.authorities[node] = ident
    return a


def load_report(path):
    """A report written with --format json, checked for the shape the renderers read."""
    with open(path) as fh:
        doc = json.load(fh)
    ok = (isinstance(doc, dict) and isinstance(doc.get("windows"), list) and isinstance(doc.get("nodes"), dict)
          and isinstance(doc.get("notes"), list)
          and all(isinstance(v, dict) and isinstance(v.get("files"), list) for v in doc["nodes"].values())
          and all(isinstance(w, dict) and isinstance(w.get("nodes"), dict) and isinstance(w.get("fleet"), dict)
                  for w in doc["windows"]))
    if not ok:
        raise ValueError("%s is not a cert-rate report (--format json)" % path)
    return doc


def main(argv=None):
    a = parse_args(argv)
    try:
        notes = []
        windows = None
        if a.from_json is not None:
            doc = load_report(a.from_json)
        elif a.windows:
            windows, wnotes = manifest_windows(a.windows)
            notes.extend(wnotes)
        elif a.start:
            windows = [("window", parse_iso(a.start), parse_iso(a.end))]
            if windows[0][2] <= windows[0][1]:
                raise ValueError("--to must be after --from")
        if a.from_json is None:
            groups = find_files(a.logs, a.node_glob, a.name_re)
            if not groups:
                print("cert-rate: no file in %s matches %s" % (a.logs, a.node_glob), file=sys.stderr)
                return 2
            nodes = []
            for name, paths in groups.items():
                n = Node(name)
                for p in paths:
                    n.read(p)
                n.finish(a.authorities.get(name))
                nodes.append(n)
            if windows is None:
                windows = buckets(nodes, a.bucket_min or 10)
            doc = report(nodes, windows, notes)
        if a.format == "json":
            text = json.dumps(doc, indent=1) + "\n"
        elif a.format == "csv":
            text = to_csv(doc)
        else:
            text = to_markdown(doc) + "\n"
    except (OSError, ValueError, EOFError) as e:
        print("cert-rate: %s" % e, file=sys.stderr)
        return 1
    except (KeyError, TypeError, AttributeError) as e:
        # A --from-json report that passed load_report but lacks a field the renderer reads.
        print("cert-rate: incomplete cert-rate report: %r" % (e,), file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
