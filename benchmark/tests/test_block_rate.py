"""tools/block-rate.py on a small run directory (fixtures/analysis/run/).

The fixture (T0 = 2026-10-06T06:00:00Z, phases warmup [T0, T0+600) and mixed [T0+600, T0+1200)):
  blasters  blocks 1..19 at T0 + 60 n, split over two overlapping files (8..12 in both); warmup
            blocks 1..9 epoch 1 round 10 n, 100 tx; mixed 10..14 epoch 1 round 10 n, then 15..19
            epoch 2 round 5 (n - 14), 200 tx.
  sampler   every 30 s; v01 one block per 30 s, v02 two (one row without a block).
  metrics   round gauges every 15 s, 3 rounds a step: v01 drops to 0 at T0+900 (new epoch), v02
            jumps by 1000 at T0+705 (catch-up); commit latency p50/p95 points for v01.
"""
import base64
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

TESTS = Path(__file__).resolve().parent
TOOL = TESTS.parent / "tools" / "block-rate.py"
RUN = TESTS / "fixtures" / "analysis" / "run"
T0 = 1791266400


def run_tool(*args, env=None):
    return subprocess.run([sys.executable, str(TOOL)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=60, env=env)


def rows(doc, window):
    w = next(w for w in doc["windows"] if w["name"] == window)
    return {r["source"]: r for r in w["rows"]}


class BlockRateTests(unittest.TestCase):
    def doc(self, *args):
        p = run_tool("--format", "json", *args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_chain_rates_per_phase(self):
        doc = self.doc("--run", str(RUN))
        self.assertEqual([w["name"] for w in doc["windows"]], ["phase warmup", "phase mixed", "run"])
        self.assertIn("blasters/*.json (19 blocks)", doc["sources"])
        chain = "chain (blasters/*.json)"
        warm, mixed, run = rows(doc, "phase warmup")[chain], rows(doc, "phase mixed")[chain], rows(doc, "run")[chain]
        self.assertEqual((warm["blocks"], mixed["blocks"], run["blocks"]), (9, 10, 19))
        self.assertAlmostEqual(warm["blocks_per_s"], 9 / 600)
        self.assertAlmostEqual(warm["tx_per_s"], 900 / 600)
        self.assertAlmostEqual(mixed["tx_per_s"], 2000 / 600)
        # Warmup: 8 steps of 10 (block 1 has no predecessor). Mixed: 10 from block 9, 4 x 10, the new
        # epoch's first round 5, then 4 x 5.
        self.assertAlmostEqual(warm["committed_rounds_per_s"], 80 / 600)
        self.assertAlmostEqual(mixed["committed_rounds_per_s"], 75 / 600)
        self.assertAlmostEqual(run["committed_rounds_per_s"], 155 / 1200)
        self.assertIsNone(warm["rounds_per_s"])

    def test_node_rows_from_sampler_and_metrics(self):
        doc = self.doc("--run", str(RUN))
        warm, mixed, run = rows(doc, "phase warmup"), rows(doc, "phase mixed"), rows(doc, "run")
        v1, v2 = warm["bench-validator-01"], warm["bench-validator-02"]
        self.assertAlmostEqual(v1["blocks_per_s"], 1 / 30)
        self.assertAlmostEqual(v2["blocks_per_s"], 2 / 30)
        self.assertAlmostEqual(v1["rounds_per_s"], 117 / 585)
        self.assertAlmostEqual(v2["rounds_per_s"], 117 / 585)
        # The new epoch's drop and the catch-up jump add nothing.
        self.assertAlmostEqual(mixed["bench-validator-01"]["rounds_per_s"], 114 / 585)
        self.assertAlmostEqual(mixed["bench-validator-02"]["rounds_per_s"], 114 / 585)
        self.assertAlmostEqual(run["bench-validator-01"]["rounds_per_s"], 234 / 1185)
        self.assertAlmostEqual(mixed["bench-validator-01"]["committed_rounds_per_s"], 114 / 585)
        self.assertIsNone(mixed["bench-validator-02"]["committed_rounds_per_s"])
        self.assertEqual((v1["latency_p50_s"], v1["latency_p95_s"]), (2.0, 4.0))
        self.assertEqual(mixed["bench-validator-01"]["latency_p50_s"], 0.8)
        self.assertIsNone(mixed["bench-validator-01"]["latency_p95_s"])
        self.assertIsNone(v1["tx_per_s"])

    def test_sampler_alone_buckets_and_from_to(self):
        doc = self.doc("--sampler", str(RUN / "sampler" / "bench-validator-02.csv"), "--bucket-min", "5")
        self.assertEqual(len(doc["windows"]), 4)
        for w in doc["windows"]:
            self.assertEqual([r["source"] for r in w["rows"]], ["bench-validator-02"])
            self.assertAlmostEqual(w["rows"][0]["blocks_per_s"], 2 / 30)
        doc = self.doc("--run", str(RUN), "--from", "2026-10-06T06:00:00Z", "--to", "2026-10-06T06:20:00Z")
        self.assertEqual(rows(doc, "window")["chain (blasters/*.json)"]["blocks"], 19)

    def test_bench6_blast_phases_from_rc0_entries_only(self):
        # Each rc-0 blasts[] entry's phases are windows ("blast <i> <phase>"), a failed one is a note, and the
        # top-level phases (a copy of the latest entry's) are not read twice.
        warm = {"name": "warmup", "start": "2026-10-06T06:00:00Z", "end": "2026-10-06T06:10:00Z"}
        mixed = {"name": "mixed", "start": "2026-10-06T06:10:00Z", "end": "2026-10-06T06:20:00Z"}
        failed = {"index": 0, "kind": "light", "rc": 1, "phases": [dict(mixed, start="2026-10-06T06:05:00Z")]}
        m = {"param_arms": [{"name": "a0", "begin": "2026-10-06T06:00:00Z", "end": "2026-10-06T06:20:00Z",
                             "marks": [{"label": "idle-1", "begin": "2026-10-06T06:00:00Z", "end": "2026-10-06T06:05:00Z"}]}],
             "blasts": [failed, {"index": 1, "kind": "load", "rc": 0, "phases": [warm, mixed]}], "phases": [warm, mixed]}
        with tempfile.TemporaryDirectory(prefix="block-rate-") as d:
            manifest = os.path.join(d, "m.json")
            with open(manifest, "w") as fh:
                json.dump(m, fh)
            doc = self.doc("--run", str(RUN), "--windows", manifest)
            self.assertEqual([w["name"] for w in doc["windows"]],
                             ["arm a0", "mark a0/idle-1", "blast 1 warmup", "blast 1 mixed", "run"])
            self.assertIn("blast 0: rc 1, not measured", doc["notes"])
            plain = self.doc("--run", str(RUN))
            for ours, theirs in (("blast 1 warmup", "phase warmup"), ("blast 1 mixed", "phase mixed")):
                self.assertEqual(rows(doc, ours), rows(plain, theirs), ours)
            m["phases"] = failed["phases"]                     # the latest blast failed: its copy is not a window
            with open(manifest, "w") as fh:
                json.dump(m, fh)
            self.assertNotIn("phase mixed", [w["name"] for w in self.doc("--run", str(RUN), "--windows", manifest)["windows"]])

    def test_markdown_has_one_table_per_window(self):
        p = run_tool("--run", str(RUN))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.count("\n## "), 3)
        self.assertEqual(p.stdout.count("| source | rounds/s |"), 3)
        self.assertIn("| chain (blasters/*.json) | – | 0.13 | 0.01 | 1.50 | – | – |", p.stdout)

    def test_a_run_without_manifest_or_data(self):
        with tempfile.TemporaryDirectory(prefix="block-rate-") as d:
            p = run_tool("--run", d)
            self.assertEqual(p.returncode, 2, p.stdout)
            shutil.copytree(str(RUN / "sampler"), os.path.join(d, "sampler"))
            doc = json.loads(run_tool("--run", d, "--format", "json").stdout)
            self.assertEqual(doc["windows"][0]["name"], "2026-10-06T06:00Z")
            self.assertEqual(len(doc["windows"]), 2)
        self.assertEqual(run_tool("--run", str(RUN), "--windows", "/nonexistent.json").returncode, 1)


class _Prom(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):   # noqa: N802 (http.server's name)
        _Prom.seen.append((self.path, self.headers.get("Authorization")))
        body = {"status": "success", "data": {"result": [
            {"metric": {"node": "bench-validator-01"}, "values": [[T0 + 15 * i, str(1.5 * i)] for i in range(40)]}]}}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class PromTests(unittest.TestCase):
    def test_range_query_replaces_metrics_json(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Prom)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            env = dict(os.environ, BENCH_PROM_AUTH="bench:secret")
            p = run_tool("--run", str(RUN), "--format", "json", "--prom-url",
                         "http://127.0.0.1:%d/api/v1" % srv.server_address[1], "--prom-selector", '{network="bench"}',
                         env=env)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(p.returncode, 0, p.stderr)
        doc = json.loads(p.stdout)
        self.assertTrue(any(s.startswith("Prometheus http://127.0.0.1") for s in doc["sources"]))
        self.assertNotIn("metrics.json", doc["sources"])
        v1 = rows(doc, "phase warmup")["bench-validator-01"]
        self.assertAlmostEqual(v1["rounds_per_s"], 0.1)          # 1.5 a 15 s step
        self.assertEqual(v1["latency_p50_s"], 29.25)             # the stub answers every query alike
        self.assertIsNone(rows(doc, "phase warmup")["bench-validator-02"]["rounds_per_s"])
        paths = [s[0] for s in _Prom.seen]
        self.assertTrue(all(s.startswith("/api/v1/query_range?") for s in paths))
        self.assertTrue(any("network%3D%22bench%22" in s for s in paths))
        self.assertEqual({s[1] for s in _Prom.seen}, {"Basic " + base64.b64encode(b"bench:secret").decode()})


if __name__ == "__main__":
    unittest.main()
