#!/usr/bin/env python3
"""orch-host-readings.py — bench 8: the host readings the endpoint sampler saves beside each metrics snapshot.

  python3 tasks/bench8/orch-host-readings.py <samples dir>

Reads <samples dir>/<node>-host-<YYYYmmddTHHMMSSZ>.txt (written by tasks/bench8/orch-endpoint-sampler.sh) and
prints a header line, then one TSV row per node per round, ordered by time, then node:
  utc  node  clock_offset_s  clock_source  steal_jiffies  total_jiffies  steal_share_since_previous_round

clock_offset_s   the node's clock minus its time source, in seconds, signed (positive: the node is ahead).
                 chrony: "System time : X seconds fast|slow of NTP time" (fast is +X, slow is -X); without that
                 line, "Last offset" as chrony prints it (positive: the node was ahead). timesyncd: the
                 "Offset:" line of `timedatectl timesync-status` is the NTP offset (the source minus the node),
                 so its sign is flipped here. Empty for none or an unreadable line.
clock_source     chrony | timesyncd | none, as the sampler's session found it on the node.
steal_jiffies    running total since the node booted, from the aggregate cpu line of /proc/stat.
total_jiffies    user+nice+system+idle+iowait+irq+softirq+steal of the same line (guest and guest_nice are
                 already counted inside user and nice, so they are not added).
steal_share_since_previous_round
                 steal delta / total delta against the node's previous file; empty for a node's first file,
                 when the total did not grow, or when a counter went down (a reboot).
A file that is not a valid host block is skipped with a line on stderr. Exit 0; 2 for a bad argument.
"""
import os
import re
import sys

NAME = re.compile(r"^(?P<node>.+)-host-(?P<stamp>\d{8}T\d{6}Z)\.txt$")
SYSTEM_TIME = re.compile(r"^System time\s*:\s*(\d+(?:\.\d+)?)\s+seconds\s+(fast|slow)\b")
LAST_OFFSET = re.compile(r"^Last offset\s*:\s*([+-]?\d+(?:\.\d+)?)\s+seconds\b")
TIMESYNCD = re.compile(r"^\s*Offset:\s*([+-]?)\s*(.+?)\s*$")
SPAN = re.compile(u"(\\d+(?:\\.\\d+)?)\\s*(ns|us|µs|ms|min|s|h)(?![a-z])")
UNIT = {"ns": 1e-9, "us": 1e-6, u"µs": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0}
COLUMNS = ("utc", "node", "clock_offset_s", "clock_source", "steal_jiffies", "total_jiffies",
           "steal_share_since_previous_round")


def timespan(text):
    """Seconds of a systemd time span such as 1.234ms, 56us or 1min 2.5s; None when nothing parses."""
    parts = SPAN.findall(text)
    if not parts or SPAN.sub("", text).strip():
        return None
    return sum(float(v) * UNIT[u] for v, u in parts)


def parse(text):
    """(clock_source, clock_offset_s or None, cpu counters) of one host block; None when it is not valid."""
    lines = text.splitlines()
    clock = [ln.split() for ln in lines if ln.split()[:1] == ["clock"]]
    cpu = [ln.split() for ln in lines if ln.split()[:1] == ["cpu"]]
    tck = [ln.split() for ln in lines if ln.split()[:1] == ["clk_tck"]]
    if len(clock) != 1 or len(clock[0]) != 2 or clock[0][1] not in ("chrony", "timesyncd", "none"):
        return None
    if len(cpu) != 1 or len(cpu[0]) < 9 or not all(x.isdigit() for x in cpu[0][1:9]):
        return None
    if len(tck) != 1 or len(tck[0]) != 2 or not tck[0][1].isdigit():
        return None
    source = clock[0][1]
    offset = None
    if source == "chrony":
        for ln in lines:
            m = SYSTEM_TIME.match(ln)
            if m:
                offset = float(m.group(1)) * (1.0 if m.group(2) == "fast" else -1.0)
        if offset is None:
            for ln in lines:
                m = LAST_OFFSET.match(ln)
                if m:
                    offset = float(m.group(1))
    elif source == "timesyncd":
        for ln in lines:
            m = TIMESYNCD.match(ln)
            if m:
                span = timespan(m.group(2))
                if span is not None:
                    offset = -span if m.group(1) != "-" else span
    return source, offset, [int(x) for x in cpu[0][1:9]]


def rows(directory):
    found = []
    for name in sorted(os.listdir(directory)):
        m = NAME.match(name)
        if not m:
            continue
        with open(os.path.join(directory, name), errors="replace") as f:
            got = parse(f.read())
        if got is None:
            sys.stderr.write("skipped, not a host block: %s\n" % name)
            continue
        s = m.group("stamp")
        utc = "%s-%s-%sT%s:%s:%sZ" % (s[0:4], s[4:6], s[6:8], s[9:11], s[11:13], s[13:15])
        found.append((utc, m.group("node")) + got)
    found.sort(key=lambda r: (r[0], r[1]))
    previous = {}
    out = []
    for utc, node, source, offset, cpu in found:
        steal, total = cpu[7], sum(cpu)
        share = ""
        if node in previous:
            ps, pt = previous[node]
            if total > pt and steal >= ps:
                share = "%.6f" % (float(steal - ps) / float(total - pt))
        previous[node] = (steal, total)
        out.append((utc, node, "" if offset is None else "%.9f" % offset, source, str(steal), str(total), share))
    return out


def main(argv):
    if len(argv) != 2 or not os.path.isdir(argv[1]):
        sys.stderr.write("usage: orch-host-readings.py <samples dir>\n")
        return 2
    sys.stdout.write("\t".join(COLUMNS) + "\n")
    for r in rows(argv[1]):
        sys.stdout.write("\t".join(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
