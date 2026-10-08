"""tools/propose-latency.py on small synthetic logs, gzipped in a temporary directory per test.

A node's history is split the way a restart-per-arm sweep leaves it: container logs saved before a
restart (<node>-telcoin-pre-arm-<arm>-<UTC>.log.gz), the last container (<node>-telcoin.log.gz) and
the unit's stdout file (<node>-unit-stdout.log.gz), which repeats the lines of both. The generator
proposes a round every 350 ms; three rounds of four reach quorum 287 ms later, the fourth gets a
`Canceled` vote error instead.
"""
import calendar
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "propose-latency.py"


def stamp(ms):
    """logfmt ts= of <ms> milliseconds since the epoch, nanosecond digits like the node's."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + ".%03d000000Z" % (ms % 1000)


def secs(ms):
    """The time the tool reads back from stamp(ms) (whole seconds plus the fraction, as floats)."""
    return ms // 1000 + (ms % 1000) / 1000.0


def at(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


def rounds(t0, first, last, epoch=0):
    """[(proposal time, round, lines, quorum time or None)] for rounds first..last, one proposal
    every 350 ms from the whole second t0."""
    out = []
    for i, r in enumerate(range(first, last + 1)):
        ms = t0 * 1000 + 350 * i
        lines = ['ts=%s level=info target=consensus::metrics message="header proposed" round=%d epoch=%d '
                 'num_batches=0 num_parents=7\n' % (stamp(ms), r, epoch)]
        quorum = None
        if r % 4:
            quorum = secs(ms + 287)
            lines.append('ts=%s level=info target=consensus::metrics message="quorum reached" round=%d epoch=%d\n'
                         % (stamp(ms + 287), r, epoch))
        else:
            lines.append('ts=%s level=error target=primary::certifier message="failed to get vote for header h%d: '
                         'B%d(vAuth, e%d, 0wbs, exec: NumHash { number: 0 }): Canceled" auth=Auth\n'
                         % (stamp(ms + 300), r, r, epoch))
        out.append((secs(ms), r, lines, quorum))
    return out


def text(rs):
    return "".join(l for _, _, lines, _ in rs for l in lines)


class ProposeLatencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="propose-latency-")
        self.logs = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, body):
        with gzip.open(str(self.logs / name), "wt") as fh:
            fh.write(body)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), "--logs", str(self.logs)] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def tables(self, *args):
        """{window heading name: {node: [cells]}} of a successful run, and its stdout."""
        p = self.run_tool(*args)
        self.assertEqual(p.returncode, 0, p.stderr)
        out, current = {}, None
        for line in p.stdout.splitlines():
            if line.startswith("## "):
                current = out.setdefault(line[3:].split(":", 1)[0], {})
            elif line.startswith("| bench-"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                current[cells[0]] = cells[1:]
        return out, p.stdout

    def test_one_node_over_overlapping_files_counts_each_event_once(self):
        rs = rounds(at("2026-10-06T12:00:00Z"), 1, 20)
        self.write("bench-validator-01-telcoin-pre-arm-a1-20261006T120004Z.log.gz", text(rs[:12]))
        self.write("bench-validator-01-telcoin.log.gz", text(rs[8:]))
        self.write("bench-validator-01-unit-stdout.log.gz", text(rs))
        self.write("bench-validator-02-telcoin.log.gz", text(rs[:8]))
        self.write("bench-observer-11-telcoin.log.gz", text(rs))       # not a validator: not read
        tables, out = self.tables()
        self.assertEqual(list(tables), ["whole log"])
        t = tables["whole log"]
        self.assertEqual(sorted(t), ["bench-validator-01", "bench-validator-02"])
        v1 = t["bench-validator-01"]
        self.assertEqual(v1[:3], ["20", "15", "75.0"])
        self.assertEqual(v1[3].split("/")[0], "287")     # C p50
        self.assertEqual(v1[4].split("/")[0], "350")     # period p50
        self.assertEqual(v1[6], "5")                     # Canceled, each once
        self.assertEqual(t["bench-validator-02"][:3], ["8", "6", "75.0"])
        self.assertIn("bench-validator-01 (bench-validator-01-telcoin-pre-arm-a1-20261006T120004Z.log.gz, "
                      "bench-validator-01-telcoin.log.gz, bench-validator-01-unit-stdout.log.gz)", out)
        self.assertNotIn("bench-observer-11", out)
        # The columns of the single-file tool, unchanged.
        self.assertIn("| node | proposed | certified | rate % | C p50/p90/p95 ms | period p50/p95 ms | "
                      "quorum->next p50/p95 ms | canceled |", out)
        # A time of day is taken on the logs' one day; the window is start <= t < end.
        tod, _ = self.tables("--from", "12:00:00.7", "--to", "12:00:02.1")
        iso, _ = self.tables("--from", "2026-10-06T12:00:00.7Z", "--to", "2026-10-06T12:00:02.1Z")
        self.assertEqual(tod["window"], iso["window"])
        self.assertEqual(iso["window"]["bench-validator-01"][0], "4")     # rounds 3..6

    def test_rounds_pair_within_their_epoch(self):
        t0 = at("2026-10-06T12:00:00Z")
        self.write("bench-validator-01-telcoin.log.gz", text(rounds(t0, 1, 7, epoch=3) + rounds(t0 + 10, 1, 7, epoch=4)))
        tables, _ = self.tables()
        self.assertEqual(tables["whole log"]["bench-validator-01"][:3], ["14", "12", "85.7"])

    def test_window_across_midnight(self):
        rs = rounds(at("2026-10-06T23:59:53Z"), 1, 40)      # 23:59:53.00 .. 00:00:06.65
        self.write("bench-validator-01-unit-stdout.log.gz", text(rs))
        start, end = at("2026-10-06T23:59:58Z"), at("2026-10-07T00:00:03Z")
        proposed = [r for t, r, _, _ in rs if start <= t < end]
        certified = [r for t, r, _, q in rs if start <= t < end and q is not None and q < end]
        self.assertEqual((proposed[0], proposed[-1], len(certified)), (16, 29, 9))   # rounds 16..29 span midnight
        tables, out = self.tables("--from", "2026-10-06T23:59:58Z", "--to", "2026-10-07T00:00:03Z")
        row = tables["window"]["bench-validator-01"]
        self.assertEqual(row[:2], [str(len(proposed)), str(len(certified))])
        self.assertIn("## window: 2026-10-06T23:59:58Z → 2026-10-07T00:00:03Z (5 s)", out)
        # A time of day is ambiguous across midnight: refused, naming both days.
        p = self.run_tool("--from", "23:59:58", "--to", "00:00:03")
        self.assertEqual(p.returncode, 1)
        self.assertIn("--from 23:59:58 is a time of day, but the logs span 2026-10-06 to 2026-10-07", p.stderr)
        self.assertIn("2026-10-06T23:59:58Z", p.stderr)
        p = self.run_tool("--from", "2026-10-07T00:00:03Z", "--to", "2026-10-06T23:59:58Z")
        self.assertEqual(p.returncode, 1)
        self.assertIn("--to must be after --from", p.stderr)

    def test_manifest_windows_one_arm_one_phase_and_run(self):
        t0 = at("2026-10-06T12:00:00Z")
        self.write("bench-validator-01-unit-stdout.log.gz", text(rounds(t0, 1, 40)))     # 12:00:00 .. 12:00:13.65
        self.write("bench-validator-02-telcoin.log.gz", text(rounds(t0, 1, 8)))          # 12:00:00 .. 12:00:02.45
        manifest = self.logs / "manifest.json"
        manifest.write_text(json.dumps({
            "param_arms": [{"name": "a1", "begin": "2026-10-06T12:00:00Z", "end": "2026-10-06T12:00:07Z", "nodes": {}},
                           {"name": "a2", "begin": "2026-10-06T12:00:07Z", "end": None, "nodes": {}}],
            "phases": [{"name": "blast", "start": "2026-10-06T12:00:07Z", "end": "2026-10-06T12:00:14Z"}]}))
        tables, out = self.tables("--windows", str(manifest))
        self.assertEqual(list(tables), ["arm a1", "phase blast", "run"])
        self.assertIn("- arm a2 has no end: left out", out)
        self.assertIn("## arm a1: 2026-10-06T12:00:00Z → 2026-10-06T12:00:07Z (7 s)", out)
        self.assertIn("## run: 2026-10-06T12:00:00Z → 2026-10-06T12:00:14Z (14 s)", out)
        self.assertEqual(tables["arm a1"]["bench-validator-01"][:3], ["20", "15", "75.0"])
        self.assertEqual(tables["phase blast"]["bench-validator-01"][:3], ["20", "15", "75.0"])
        self.assertEqual(tables["run"]["bench-validator-01"][:3], ["40", "30", "75.0"])
        self.assertEqual(tables["arm a1"]["bench-validator-02"][:3], ["8", "6", "75.0"])
        # A node with no event in a window: no rate, and a note naming what its files span.
        self.assertEqual(tables["phase blast"]["bench-validator-02"][:3], ["0", "0", "—"])
        self.assertIn("- bench-validator-02: no event in this window (its files span 2026-10-06T12:00:00Z → "
                      "2026-10-06T12:00:02Z)", out)

    def test_no_matching_file_exits_2(self):
        self.write("bench-observer-11-telcoin.log.gz", "")
        p = self.run_tool()
        self.assertEqual(p.returncode, 2)
        self.assertIn("no file in", p.stderr)


if __name__ == "__main__":
    unittest.main()
