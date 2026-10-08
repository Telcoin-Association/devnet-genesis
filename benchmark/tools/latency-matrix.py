#!/usr/bin/env python3
"""latency-matrix.py: RTT tables from a latency-probe.sh run directory.

Reads <raw dir>/<zone>.json (one per probing VM) and <raw dir>/run.json, and writes:

  matrix-udp.csv/.md    zone x zone UDP echo RTT, median ms
  matrix-tcp.csv/.md    zone x zone TCP connect RTT, median ms
  matrix-icmp.csv/.md   zone x zone ping RTT, avg ms
  tcp-vs-udp.md         per zone pair: UDP and TCP medians, delta, UDP loss, flags
  kth-nearest.md        per zone: the other zones by UDP RTT, 5th and 6th nearest called out
  kth-nearest-<n>.md    the same for a validator layout given with --layout <n>=zone,zone,...
  summary.json          all of the above, machine-readable

A run made with --addresses external or both (the probe VMs' external IPs) adds:

  matrix-{udp,tcp,icmp}-external.csv/.md   the three matrices over external IPs
  kth-nearest-external.md                  nearest zones by external UDP RTT
  external-vs-internal.md                  per ordered pair: internal and external UDP medians, delta,
                                           ratio, flags, and the external RTT via one hub zone
                                           (--via, default us-west2-a)
  summary.json "external"                  the same, machine-readable

The tables without a suffix are internal-address tables; they are left out of an external-only run.

A cell averages the two directions (a->b and b->a) when both were measured; `*` marks a cell
measured in one direction only; an em dash marks no data (not measured, or every probe lost).

Usage: latency-matrix.py <raw dir> [--out DIR] [--zones a,b,...|@file] [--layout name=z1,z2,...]...
                         [--via ZONE]
Python 3.9+, standard library only.
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys

DASH = "—"
ONE_WAY = "*"
INTRA = "†"
ASSUMED_INTRA_MS = 1.0
UDP_OVER_TCP_PCT = 10.0
KS = (5, 6)
METRICS = ("udp", "tcp", "icmp")
FLAG_SLOWER = "UDP > TCP by >10%"
FLAG_LOSS = "UDP loss"
FLAG_NO_UDP = "no UDP data"
TITLES = {"udp": "UDP echo RTT (median, ms)", "tcp": "TCP connect RTT (median, ms)",
          "icmp": "ICMP ping RTT (avg, ms)"}
# Where each address kind's records sit in a probe result.
PEER_KEYS = {"internal": "peers", "external": "peers_external"}
EXT_TAG = " — external IPs"
VIA_DEFAULT = "us-west2-a"
EXT_OVER_INT_PCT = 25.0
EXT_OVER_INT_MS = 30.0
VIA_MATCH_PCT = 10.0
FLAG_EXT_SLOWER = "external > internal"
FLAG_VIA = "external ≈ via %s"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def split_zones(spec):
    """'a,b c' or '@file' (one per line, # comments) -> ordered unique zone names."""
    if spec.startswith("@"):
        with open(spec[1:], encoding="utf-8") as fh:
            spec = "\n".join(line.split("#", 1)[0] for line in fh)
    out = []
    for z in re.split(r"[\s,]+", spec.strip()):
        if z and z not in out:
            out.append(z)
    return out


class Data:
    """One probe run: per-source JSON documents plus run.json."""

    def __init__(self, src, run=None):
        self.src = src
        self.run = run or {}

    @classmethod
    def from_dir(cls, raw_dir):
        run_path = os.path.join(raw_dir, "run.json")
        run = load_json(run_path) if os.path.exists(run_path) else {}
        src = {}
        for name in sorted(os.listdir(raw_dir)):
            if not name.endswith(".json") or name in ("run.json", "summary.json"):
                continue
            doc = load_json(os.path.join(raw_dir, name))
            if isinstance(doc, dict) and doc.get("src_zone") and isinstance(doc.get("peers"), dict):
                src[doc["src_zone"]] = doc
            else:
                print("latency-matrix: ignoring %s (not a probe result)" % name, file=sys.stderr)
        return cls(src, run)

    @property
    def skipped(self):
        return list(self.run.get("skipped") or [])

    @property
    def failed(self):
        return list(self.run.get("failed") or [])

    def zones(self):
        """run.json's zone order minus skipped zones, then any other zone seen in the data."""
        skipped = {s.get("zone") for s in self.skipped}
        out = [z for z in self.run.get("zones") or [] if z not in skipped]
        seen = set(self.src)
        for doc in self.src.values():
            for key in PEER_KEYS.values():
                seen.update(doc.get(key) or {})
        out += sorted(z for z in seen if z not in out)
        return out

    def has(self, address):
        """True when any probe result holds records for this address kind."""
        return any(doc.get(PEER_KEYS[address]) for doc in self.src.values())

    def view(self, address):
        """The run seen through one address kind: each result's `peers` holds that kind's records."""
        key = PEER_KEYS[address]
        return Data({z: dict(doc, peers=doc.get(key) or {}) for z, doc in self.src.items()}, self.run)

    def udp_loss_directed(self, a, b):
        udp = (self.peer(a, b) or {}).get("udp") or {}
        return None if udp.get("loss_pct") is None else float(udp["loss_pct"])

    def peer(self, a, b):
        return (self.src.get(a) or {}).get("peers", {}).get(b)

    def directed(self, metric, a, b):
        """a -> b RTT in ms, or None (not measured, or every probe lost)."""
        m = (self.peer(a, b) or {}).get(metric) or {}
        if metric == "icmp":
            v = m.get("avg")
        else:
            v = m.get("median_ms")
            if v is None and m.get("samples_ms"):
                v = statistics.median(m["samples_ms"])
        return None if v is None else float(v)

    def pair(self, metric, a, b):
        """(ms, one_way): both directions averaged; one_way when only one was measured."""
        vals = [v for v in (self.directed(metric, a, b), self.directed(metric, b, a)) if v is not None]
        if not vals:
            return None, False
        return sum(vals) / len(vals), len(vals) == 1

    def udp_loss(self, a, b):
        """Worst-direction UDP loss % over the directions that were measured, or None."""
        losses = []
        for x, y in ((a, b), (b, a)):
            udp = (self.peer(x, y) or {}).get("udp")
            if udp and udp.get("loss_pct") is not None:
                losses.append(float(udp["loss_pct"]))
        return max(losses) if losses else None

    def samples(self, metric, a, b):
        """Every sample of both directions (ms)."""
        out = []
        for x, y in ((a, b), (b, a)):
            out += [float(v) for v in ((self.peer(x, y) or {}).get(metric) or {}).get("samples_ms") or []]
        return out

    def udp_p95(self, a, b):
        vals = []
        for x, y in ((a, b), (b, a)):
            v = ((self.peer(x, y) or {}).get("udp") or {}).get("p95_ms")
            if v is not None:
                vals.append(float(v))
        return max(vals) if vals else None


def fmt(ms, one_way=False):
    return DASH if ms is None else "%.2f%s" % (ms, ONE_WAY if one_way else "")


def rnd(v):
    return None if v is None else round(v, 3)


def matrix(data, metric, zones):
    """{a: {b: (ms, one_way)}} over zones, a != b."""
    return {a: {b: data.pair(metric, a, b) for b in zones if b != a} for a in zones}


def matrix_rows(mx, zones):
    rows = []
    for a in zones:
        rows.append([a] + [DASH if a == b else fmt(*mx[a][b]) for b in zones])
    return rows


def md_table(header, rows, right=()):
    align = ["---:" if i in right else "---" for i in range(len(header))]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def pairs(data, zones):
    """Every unordered zone pair with its UDP/TCP/ICMP numbers and flags."""
    out = []
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            udp, udp_one = data.pair("udp", a, b)
            tcp, tcp_one = data.pair("tcp", a, b)
            icmp, icmp_one = data.pair("icmp", a, b)
            loss = data.udp_loss(a, b)
            delta = delta_pct = None
            if udp is not None and tcp is not None:
                delta = udp - tcp
                delta_pct = 100.0 * delta / tcp if tcp > 0 else None
            tcp_all = data.samples("tcp", a, b)
            flags = []
            if delta_pct is not None and delta_pct > UDP_OVER_TCP_PCT:
                flags.append(FLAG_SLOWER)
            if loss is not None and loss > 0:
                flags.append(FLAG_LOSS)
            if udp is None:
                flags.append(FLAG_NO_UDP)
            out.append({"a": a, "b": b, "udp_ms": rnd(udp), "tcp_ms": rnd(tcp), "icmp_ms": rnd(icmp),
                        "udp_ab_ms": rnd(data.directed("udp", a, b)), "udp_ba_ms": rnd(data.directed("udp", b, a)),
                        "udp_p95_ms": rnd(data.udp_p95(a, b)),
                        "tcp_min_ms": rnd(min(tcp_all)) if tcp_all else None,
                        "tcp_max_ms": rnd(max(tcp_all)) if tcp_all else None, "delta_ms": rnd(delta),
                        "delta_pct": None if delta_pct is None else round(delta_pct, 2),
                        "udp_loss_pct": loss,
                        "one_way": {"udp": udp_one, "tcp": tcp_one, "icmp": icmp_one}, "flags": flags})
    return out


def ranked(entries, order):
    """entries [(zone, ms, note)] -> (reachable sorted by (ms, zone order), unreachable zones)."""
    reach = sorted((e for e in entries if e[1] is not None), key=lambda e: (e[1], order.get(e[0], 0)))
    return reach, [e[0] for e in entries if e[1] is None]


def kth(reach, k):
    return reach[k - 1] if len(reach) >= k else None


def kth_nearest(data, zones):
    order = {z: i for i, z in enumerate(zones)}
    out = {}
    for a in zones:
        entries = []
        for b in zones:
            if b != a:
                ms, one = data.pair("udp", a, b)
                entries.append((b, ms, ONE_WAY if one else ""))
        reach, unreachable = ranked(entries, order)
        out[a] = {"sorted": reach, "unreachable": unreachable, "k": {k: kth(reach, k) for k in KS}}
    return out


def layout_kth(data, validators):
    """Per distinct zone of a validator layout: the other validators' UDP RTTs, ascending."""
    zones = []
    for z in validators:
        if z not in zones:
            zones.append(z)
    order = {z: i for i, z in enumerate(zones)}
    out, assumed = {}, False
    for a in zones:
        entries = []
        others = list(validators)
        others.remove(a)
        for b in others:
            if b == a:
                ms = data.directed("udp", a, a)
                if ms is None:
                    ms, note, assumed = ASSUMED_INTRA_MS, INTRA, True
                else:
                    note = ""
            else:
                ms, one = data.pair("udp", a, b)
                note = ONE_WAY if one else ""
            entries.append((b, ms, note))
        reach, unreachable = ranked(entries, order)
        out[a] = {"validators": validators.count(a), "sorted": reach, "unreachable": unreachable,
                  "k": {k: kth(reach, k) for k in KS}}
    return out, assumed


def cell(entry):
    return DASH if entry is None else "%.2f%s (%s)" % (entry[1], entry[2], entry[0])


def chain(reach, unreachable):
    parts = ["%s %.2f%s" % (z, ms, note) for z, ms, note in reach]
    parts += ["%s %s" % (z, DASH) for z in unreachable]
    return " · ".join(parts) if parts else DASH


def run_line(data, zones):
    run = data.run
    bits = ["run %s" % run["stamp"]] if run.get("stamp") else []
    if run.get("machine_type"):
        bits.append("probe VMs %s" % run["machine_type"])
    if run.get("addresses") and run["addresses"] != "internal":
        bits.append("addresses %s (%s tier)" % (run["addresses"], run.get("network_tier") or "default"))
    bits.append("%d zones" % len(zones))
    return " · ".join(bits)


LEGEND = ("Cells average both directions; `%s` = one direction only; `%s` = no data (not measured "
          "or every probe lost)." % (ONE_WAY, DASH))


def ordinal(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def quorum_note(n):
    f = (n - 1) // 3
    return ("With %d validators (f = %d) a quorum is 2f+1 = %d votes: a validator's own vote plus "
            "%d from peers, so its %s-nearest peer bounds the vote round trip. The 5th and 6th nearest "
            "are shown." % (n, f, 2 * f + 1, 2 * f, ordinal(2 * f)))


IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
PROJECT_PATH = re.compile(r"projects/[^/\s'\"]+")


def scrub(text):
    """Error excerpts go into committed tables: drop project ids and addresses."""
    return IPV4.sub("<ip>", PROJECT_PATH.sub("projects/<project>", text or ""))


CODE = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]{3,}\b")


def reason(error):
    """A short reason for a table header: the API error code when there is one."""
    m = CODE.search(error or "")
    return m.group(0) if m else (error or "").strip()[:160]


def scrubbed(records):
    return [dict(r, error=scrub(r.get("error"))) for r in records]


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def matrix_files(data, zones, head, files, suffix="", tag=""):
    """matrix-<metric><suffix>.csv/.md for every metric into files; returns summary's matrices block."""
    out = {}
    for metric in METRICS:
        mx = matrix(data, metric, zones)
        out[metric] = {
            a: {b: (None if mx[a][b][0] is None else {"ms": rnd(mx[a][b][0]), "one_way": mx[a][b][1]})
                for b in mx[a]} for a in zones}
        rows = matrix_rows(mx, zones)
        csv_lines = [",".join(["zone"] + zones)] + [",".join(r) for r in rows]
        files["matrix-%s%s.csv" % (metric, suffix)] = "\n".join(csv_lines)
        files["matrix-%s%s.md" % (metric, suffix)] = "# %s%s\n\n%s\n\n%s\n\n%s" % (
            TITLES[metric], tag, head, LEGEND, md_table(["zone"] + zones, rows, range(1, len(zones) + 1)))
    return out


def kth_file(data, zones, head, tag=""):
    """(kth-nearest markdown, summary block) for one address kind."""
    kn = kth_nearest(data, zones)
    rows = [[a, cell(v["k"][5]), cell(v["k"][6])] for a, v in kn.items()]
    detail = "\n".join("- **%s**: %s" % (a, chain(v["sorted"], v["unreachable"])) for a, v in kn.items())
    text = (
        "# Nearest zones by UDP RTT%s\n\n%s\n\nFor each zone, the other zones in this table ordered by UDP "
        "echo RTT (ms). The 5th and 6th nearest set the vote-quorum window for a 10-validator committee "
        "with one validator per zone. %s\n\n%s\n\n## Every zone, ascending\n\n%s" % (
            tag, head, LEGEND, md_table(["zone", "5th nearest", "6th nearest"], rows), detail))
    return text, {a: kth_json(v) for a, v in kn.items()}


def compare(internal, external, zones, via):
    """Per ordered pair a -> b: the internal and external UDP medians of that one flow, side by side.

    via_ms = external RTT(a, via) + external RTT(via, b), each the direction-averaged cell of the
    external UDP matrix: what a -> b would measure if its external path ran through the via zone.
    """
    out = []
    for a in zones:
        for b in zones:
            if a == b:
                continue
            i_ms, e_ms = internal.directed("udp", a, b), external.directed("udp", a, b)
            via_ms = None
            if via not in (a, b):
                legs = (external.pair("udp", a, via)[0], external.pair("udp", via, b)[0])
                if None not in legs:
                    via_ms = legs[0] + legs[1]
            delta = ratio = None
            flags = []
            if i_ms is not None and e_ms is not None:
                delta = e_ms - i_ms
                ratio = e_ms / i_ms if i_ms > 0 else None
                if delta > EXT_OVER_INT_MS or delta > EXT_OVER_INT_PCT / 100.0 * i_ms:
                    flags.append(FLAG_EXT_SLOWER)
                    if via_ms is not None and abs(e_ms - via_ms) <= VIA_MATCH_PCT / 100.0 * via_ms:
                        flags.append(FLAG_VIA % via)
            else:
                flags.append(FLAG_NO_UDP)
            losses = (internal.udp_loss_directed(a, b), external.udp_loss_directed(a, b))
            if any(v for v in losses if v is not None):
                flags.append(FLAG_LOSS)
            out.append({"src": a, "dst": b, "internal_udp_ms": rnd(i_ms), "external_udp_ms": rnd(e_ms),
                        "delta_ms": rnd(delta), "ratio": None if ratio is None else round(ratio, 3),
                        "via_zone": via, "via_ms": rnd(via_ms),
                        "external_minus_via_ms": None if via_ms is None or e_ms is None else rnd(e_ms - via_ms),
                        "internal_loss_pct": losses[0], "external_loss_pct": losses[1], "flags": flags})
    return out


def compare_text(cmp, head, via):
    def num(v, sign=False):
        return DASH if v is None else ("%+.2f" if sign else "%.2f") % v

    def loss(v):
        return DASH if v is None else "%g" % v

    rows = [["%s → %s" % (c["src"], c["dst"]), num(c["internal_udp_ms"]), num(c["external_udp_ms"]),
             num(c["delta_ms"], True), DASH if c["ratio"] is None else "%.2f" % c["ratio"], num(c["via_ms"]),
             num(c["external_minus_via_ms"], True),
             "%s / %s" % (loss(c["internal_loss_pct"]), loss(c["external_loss_pct"])), ", ".join(c["flags"])]
            for c in cmp]
    slower = [c for c in cmp if FLAG_EXT_SLOWER in c["flags"]]
    near_via = [c for c in slower if FLAG_VIA % via in c["flags"]]
    lines = ["%d of %d ordered pairs flagged: external median more than %g %% or more than %g ms above "
             "internal; %d of them within %g %% of the via-%s sum."
             % (len(slower), len(cmp), EXT_OVER_INT_PCT, EXT_OVER_INT_MS, len(near_via), VIA_MATCH_PCT, via)]
    for c in sorted(slower, key=lambda c: -(c["delta_ms"] or 0.0)):
        lines.append("- %s → %s: internal %.2f, external %.2f (%+.2f ms, x%.2f), via %s %s" % (
            c["src"], c["dst"], c["internal_udp_ms"], c["external_udp_ms"], c["delta_ms"], c["ratio"] or 0.0,
            via, num(c["via_ms"])))
    return (
        "# External vs internal UDP RTT per ordered pair\n\n%s\n\nOne row per direction a → b: the median of "
        "that flow's UDP echoes to the peer's internal IP and to its external IP. Both targets were probed "
        "from the same VM in the same seconds, so the two columns differ only by path. Delta = external - "
        "internal; ratio = external / internal. `via %s` = external RTT(a, %s) + external RTT(%s, b), each "
        "the direction-averaged cell of `matrix-udp-external.csv`: what a → b would measure if its "
        "external path went through %s (`%s` for pairs that include it). UDP loss is a → b only, "
        "internal / external. `%s` = no data.\n\n%s\n\n%s" % (
            head, via, via, via, via, DASH, DASH, "\n".join(lines),
            md_table(["pair", "internal ms", "external ms", "delta ms", "ratio", "via %s ms" % via,
                      "ext - via ms", "UDP loss % int / ext", "flags"], rows, (1, 2, 3, 4, 5, 6, 7))))


def build(data, zones, layouts, via=VIA_DEFAULT):
    """Everything summary.json holds, plus the markdown and CSV texts: {filename: text}."""
    files, summary = {}, {"zones": zones, "skipped": scrubbed(data.skipped), "failed": scrubbed(data.failed)}
    run = data.run
    summary["run"] = {k: run.get(k) for k in ("stamp", "started_at", "finished_at", "machine_type", "params",
                                              "addresses", "network_tier") if k in run}
    summary["run"]["vm_machine_types"] = {z: v.get("machine_type") for z, v in (run.get("vms") or {}).items()}
    head = run_line(data, zones)
    if data.skipped:
        head += "\n\nSkipped (no VM): " + ", ".join(
            "%s (%s)" % (s["zone"], reason(s["error"])) for s in summary["skipped"])
    has_ext = data.has("external")
    has_int = data.has("internal") or not has_ext
    summary["addresses"] = [a for a, present in (("internal", has_int), ("external", has_ext)) if present]
    if has_ext:
        ext = data.view("external")
        files_ext = {}
        summary["external"] = {"matrices": matrix_files(ext, zones, head, files_ext, "-external", EXT_TAG)}
        files_ext["kth-nearest-external.md"], summary["external"]["kth_nearest"] = kth_file(ext, zones, head, EXT_TAG)
        if has_int:
            cmp = compare(data.view("internal"), ext, zones, via)
            summary["external"]["via_zone"] = via
            summary["external"]["vs_internal"] = cmp
            summary["external"]["flags"] = [c for c in cmp if c["flags"]]
            files_ext["external-vs-internal.md"] = compare_text(cmp, head, via)
    if not has_int:
        files.update(files_ext)
        return files, summary
    data = data.view("internal")
    summary["matrices"] = matrix_files(data, zones, head, files)

    prs = pairs(data, zones)
    summary["pairs"] = prs
    summary["flags"] = [p for p in prs if p["flags"]]
    by_udp = sorted(prs, key=lambda p: (p["udp_ms"] is None, p["udp_ms"] or 0.0))
    summary["widest_pairs"] = [{"a": p["a"], "b": p["b"], "udp_ms": p["udp_ms"]}
                               for p in sorted((p for p in prs if p["udp_ms"] is not None),
                                               key=lambda p: -p["udp_ms"])[:10]]
    rows = []
    for p in by_udp:
        ow = p["one_way"]
        rows.append(["%s ↔ %s" % (p["a"], p["b"]), fmt(p["udp_ms"], ow["udp"]),
                     "%s / %s" % (fmt(p["udp_ab_ms"]), fmt(p["udp_ba_ms"])), fmt(p["tcp_ms"], ow["tcp"]),
                     DASH if p["tcp_min_ms"] is None else "%.2f–%.2f" % (p["tcp_min_ms"], p["tcp_max_ms"]),
                     DASH if p["delta_ms"] is None else "%+.2f" % p["delta_ms"],
                     DASH if p["delta_pct"] is None else "%+.2f%%" % p["delta_pct"],
                     DASH if p["udp_loss_pct"] is None else "%g" % p["udp_loss_pct"],
                     ", ".join(p["flags"]) or ""])
    flagged = summary["flags"]
    flag_text = ("%d of %d pairs flagged (UDP median more than %g%% above TCP, or any UDP loss)."
                 % (len(flagged), len(prs), UDP_OVER_TCP_PCT))
    if flagged:
        flag_text += "\n\n" + "\n".join("- %s ↔ %s: %s" % (p["a"], p["b"], ", ".join(p["flags"]))
                                        for p in flagged)
    files["tcp-vs-udp.md"] = (
        "# UDP vs TCP per zone pair\n\n%s\n\n%s Delta = UDP - TCP (percent of TCP). UDP loss is the "
        "worse direction.\n\nPaths: the UDP probe keeps one socket per peer, so each direction is one "
        "flow on one ECMP path, as a QUIC connection would be (`a→b / b→a` shows the two). Every TCP "
        "connect uses a fresh source port, so the TCP min–max spans the paths between the two zones. "
        "A UDP-over-TCP flag with a wide TCP range usually means the UDP flow was hashed onto a slower "
        "path, not that UDP is treated differently.\n\n%s\n\n%s" % (
            head, LEGEND, flag_text,
            md_table(["pair", "UDP ms", "UDP a→b / b→a", "TCP ms", "TCP min–max", "delta ms", "delta %",
                      "UDP loss %", "flags"], rows, (1, 2, 3, 4, 5, 6, 7))))

    files["kth-nearest.md"], summary["kth_nearest"] = kth_file(data, zones, head)

    summary["layouts"] = {}
    for name, validators in layouts:
        lk, assumed = layout_kth(data, validators)
        k6 = sorted((v["k"][6][1], z) for z, v in lk.items() for _ in range(v["validators"]) if v["k"][6])
        fleet = {}
        if k6:
            fleet = {"max_k6_ms": rnd(k6[-1][0]), "max_k6_zone": k6[-1][1],
                     "median_k6_ms": rnd(statistics.median(v for v, _ in k6))}
        k5 = [v["k"][5][1] for v in lk.values() if v["k"][5]]
        if k5:
            fleet["max_k5_ms"] = rnd(max(k5))
        missing = [z for z in lk if z not in data.src]
        summary["layouts"][name] = {
            "validators": validators, "assumed_intra_ms": ASSUMED_INTRA_MS if assumed else None,
            "zones_without_data": missing, "fleet": fleet,
            "per_zone": {z: dict(kth_json(v), validators=v["validators"]) for z, v in lk.items()}}
        rows = [[z, str(v["validators"]), cell(v["k"][5]), cell(v["k"][6])] for z, v in lk.items()]
        detail = "\n".join("- **%s** (x%d): %s" % (z, v["validators"], chain(v["sorted"], v["unreachable"]))
                           for z, v in lk.items())
        notes = [LEGEND]
        if assumed:
            notes.append("`%s` = two validators in one zone; intra-zone RTT was not measured and is assumed "
                         "to be %.2f ms." % (INTRA, ASSUMED_INTRA_MS))
        if missing:
            notes.append("No probe data for: %s." % ", ".join(missing))
        fleet_line = ""
        if fleet:
            fleet_line = ("Slowest validator's 6th-nearest: **%.2f ms** (%s); median over validators %.2f ms; "
                          "slowest 5th-nearest %.2f ms." % (fleet["max_k6_ms"], fleet["max_k6_zone"],
                                                            fleet["median_k6_ms"], fleet.get("max_k5_ms", 0.0)))
        files["kth-nearest-%s.md" % name] = (
            "# Nearest validators by UDP RTT — layout `%s`\n\n%s\n\nValidators (%d): %s\n\n%s\n\n%s\n\n"
            "%s\n\n## Every zone, ascending\n\n%s" % (
                name, run_line(data, lk), len(validators), ", ".join(validators), quorum_note(len(validators)),
                " ".join(notes), md_table(["zone", "validators", "5th nearest", "6th nearest"], rows, (1,)),
                detail) + ("\n\n" + fleet_line if fleet_line else ""))
    if has_ext:
        files.update(files_ext)
    return files, summary


def kth_json(v):
    return {"sorted": [[z, rnd(ms), note] for z, ms, note in v["sorted"]], "unreachable": v["unreachable"],
            "k5": None if v["k"][5] is None else [v["k"][5][0], rnd(v["k"][5][1])],
            "k6": None if v["k"][6] is None else [v["k"][6][0], rnd(v["k"][6][1])]}


def parse_layout(spec):
    name, sep, rest = spec.partition("=")
    if not sep or not NAME_RE.match(name):
        raise argparse.ArgumentTypeError("--layout wants name=zone,zone,... (name [A-Za-z0-9_-]), got %r" % spec)
    validators = [z for z in re.split(r"[\s,]+", rest.strip()) if z]
    if len(validators) < 2:
        raise argparse.ArgumentTypeError("--layout %s needs at least two validators" % name)
    return name, validators


def main(argv=None):
    ap = argparse.ArgumentParser(description="RTT tables from a latency-probe.sh run directory.")
    ap.add_argument("raw_dir", help="directory holding <zone>.json files and run.json")
    ap.add_argument("--out", help="output directory (default: the raw directory)")
    ap.add_argument("--zones", help="restrict the tables to these zones: a,b,... or @file")
    ap.add_argument("--layout", action="append", default=[], type=parse_layout, metavar="NAME=Z1,Z2,...",
                    help="validator layout (zones may repeat); writes kth-nearest-NAME.md (repeatable)")
    ap.add_argument("--via", default=VIA_DEFAULT, metavar="ZONE",
                    help="hub zone for the via column of external-vs-internal.md (default: %(default)s)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.raw_dir):
        ap.error("%s is not a directory" % args.raw_dir)
    data = Data.from_dir(args.raw_dir)
    if not data.src:
        print("latency-matrix: no probe results in %s" % args.raw_dir, file=sys.stderr)
        return 2
    zones = data.zones()
    if args.zones:
        wanted = split_zones(args.zones)
        unknown = [z for z in wanted if z not in zones]
        if unknown:
            print("latency-matrix: no data for %s (cells will be empty)" % ", ".join(unknown), file=sys.stderr)
        zones = wanted
    names = [n for n, _ in args.layout]
    if len(set(names)) != len(names):
        ap.error("--layout names must be unique")

    out = args.out or args.raw_dir
    os.makedirs(out, exist_ok=True)
    files, summary = build(data, zones, args.layout, args.via)
    for name, text in files.items():
        write(os.path.join(out, name), text)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
        fh.write("\n")

    print("wrote %d files to %s" % (len(files) + 1, out))
    if summary.get("widest_pairs"):
        w = summary["widest_pairs"][0]
        print("  widest UDP pair: %s <-> %s %.2f ms" % (w["a"], w["b"], w["udp_ms"]))
    if "pairs" in summary:
        print("  flagged pairs: %d of %d" % (len(summary["flags"]), len(summary["pairs"])))
    if "vs_internal" in summary.get("external", {}):
        cmp = summary["external"]["vs_internal"]
        print("  external > internal: %d of %d ordered pairs (see external-vs-internal.md)" % (
            sum(FLAG_EXT_SLOWER in c["flags"] for c in cmp), len(cmp)))
    for name, lay in summary.get("layouts", {}).items():
        if lay["fleet"]:
            print("  layout %s: slowest 6th-nearest %.2f ms (%s)" % (
                name, lay["fleet"]["max_k6_ms"], lay["fleet"]["max_k6_zone"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
