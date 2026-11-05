"""tools/cert-rate.py on two small validator logs (fixtures/analysis/node-logs/), gzipped per test.

The fixture: two nodes, A1… (bench-validator-01) and B2… (bench-validator-02), two 10-minute phases.
In the warmup v01 certifies both its headers and v02 none of its three (0 %); one subdag commits
A1 r1, B2 r1, A1 r2 (leader A1). In the mixed phase v01 certifies one of two, v02 one of one; one
subdag commits B2 r2..r4 (leader B2), so v01's round-3 certificate is never committed.
"""
import csv
import gzip
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
TOOL = TESTS.parent / "tools" / "cert-rate.py"
LIB = (TESTS.parent / "bench-lib.sh").read_text()
FIX = TESTS / "fixtures" / "analysis"
A1 = "A1" + "a" * 30
B2 = "B2" + "b" * 30


class CertRateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="cert-rate-")
        self.logs = Path(self._tmp.name) / "logs"
        self.logs.mkdir()
        for src in sorted((FIX / "node-logs").glob("*.log")):
            (self.logs / (src.name + ".gz")).write_bytes(gzip.compress(src.read_bytes()))

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args):
        p = subprocess.run([sys.executable, str(TOOL), "--logs", str(self.logs)] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return p

    def doc(self, *args):
        p = self.run_tool("--format", "json", *args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def window(self, doc, name):
        return next(w for w in doc["windows"] if w["name"] == name)

    def test_manifest_phases_and_run_window(self):
        doc = self.doc("--windows", str(FIX / "manifest.json"))
        self.assertEqual([w["name"] for w in doc["windows"]], ["phase warmup", "phase mixed", "run"])
        self.assertEqual(doc["nodes"]["bench-validator-01"]["authority"], A1)
        self.assertEqual(doc["nodes"]["bench-validator-02"]["authority"], B2)
        warm = self.window(doc, "phase warmup")
        v1, v2 = warm["nodes"]["bench-validator-01"], warm["nodes"]["bench-validator-02"]
        self.assertEqual((v1["proposed"], v1["quorum"], v1["rate_pct"]), (2, 2, 100.0))
        self.assertEqual((v1["repropose"], v1["vote_errors"], v1["canceled"], v1["noform"]), (1, 2, 1, 0))
        self.assertEqual((v1["subdags"], v1["committed_certs"]), (1, 3))
        self.assertEqual((v1["own_cert_pct"], v1["own_leader_pct"], v1["not_committed_pct"]), (66.7, 100.0, 0.0))
        # The 0 % window: three proposals, no quorum, two could-not-form.
        self.assertEqual((v2["proposed"], v2["quorum"], v2["rate_pct"], v2["noform"]), (3, 0, 0.0, 2))
        self.assertEqual((v2["own_cert_pct"], v2["own_leader_pct"], v2["not_committed_pct"]), (33.3, 0.0, None))
        self.assertEqual((warm["fleet"]["proposed"], warm["fleet"]["quorum"], warm["fleet"]["rate_pct"]), (5, 2, 40.0))
        mixed = self.window(doc, "phase mixed")
        v1, v2 = mixed["nodes"]["bench-validator-01"], mixed["nodes"]["bench-validator-02"]
        self.assertEqual((v1["proposed"], v1["quorum"], v1["rate_pct"]), (2, 1, 50.0))
        self.assertEqual((v1["own_cert_pct"], v1["own_leader_pct"], v1["not_committed_pct"]), (0.0, 0.0, 100.0))
        self.assertEqual((v2["proposed"], v2["quorum"], v2["rate_pct"]), (1, 1, 100.0))
        self.assertEqual((v2["own_cert_pct"], v2["own_leader_pct"], v2["not_committed_pct"]), (100.0, 100.0, 0.0))
        run = self.window(doc, "run")
        self.assertEqual((run["start"], run["end"]), ("2026-10-06T06:00:00Z", "2026-10-06T06:20:00Z"))
        self.assertEqual(run["nodes"]["bench-validator-01"]["rate_pct"], 75.0)
        self.assertEqual(run["nodes"]["bench-validator-02"]["rate_pct"], 25.0)
        self.assertEqual(run["fleet"]["rate_pct"], 50.0)

    def test_param_arms_come_first(self):
        manifest = Path(self._tmp.name) / "m.json"
        m = json.loads((FIX / "manifest.json").read_text())
        m["param_arms"] = [{"name": "delay-250ms", "begin": "2026-10-06T06:00:00Z", "end": "2026-10-06T06:05:00Z"}]
        manifest.write_text(json.dumps(m))
        doc = self.doc("--windows", str(manifest))
        self.assertEqual([w["name"] for w in doc["windows"]], ["arm delay-250ms", "phase warmup", "phase mixed", "run"])
        self.assertEqual(doc["windows"][0]["nodes"]["bench-validator-01"]["proposed"], 2)

    def test_buckets_by_default_and_from_to(self):
        # Buckets span the counted events (the 05:59:59 startup line is none of them).
        doc = self.doc()
        self.assertEqual([(w["name"], w["secs"]) for w in doc["windows"]],
                         [("2026-10-06T06:00Z", 600), ("2026-10-06T06:10Z", 600)])
        self.assertEqual(doc["windows"][0]["nodes"]["bench-validator-02"]["rate_pct"], 0.0)
        self.assertEqual(doc["windows"][1]["nodes"]["bench-validator-02"]["quorum"], 1)
        doc = self.doc("--bucket-min", "30")
        self.assertEqual([w["name"] for w in doc["windows"]], ["2026-10-06T06:00Z"])
        doc = self.doc("--from", "2026-10-06T06:00:03Z", "--to", "2026-10-06T06:00:05Z")
        self.assertEqual(len(doc["windows"]), 1)
        self.assertEqual(doc["windows"][0]["nodes"]["bench-validator-01"]["proposed"], 1)   # 06:00:03.1
        self.assertEqual(doc["windows"][0]["nodes"]["bench-validator-02"]["proposed"], 1)   # 06:00:03.2

    def test_a_second_copy_of_a_log_is_not_counted_twice(self):
        shutil.copyfile(str(self.logs / "bench-validator-02-telcoin.log.gz"),
                        str(self.logs / "bench-validator-02-telcoin-pre-restart-20261006T061500Z.log.gz"))
        doc = self.doc("--windows", str(FIX / "manifest.json"))
        self.assertEqual(len(doc["nodes"]["bench-validator-02"]["files"]), 2)
        run = self.window(doc, "run")["nodes"]["bench-validator-02"]
        self.assertEqual((run["proposed"], run["quorum"], run["committed_certs"]), (4, 1, 6))

    def test_the_bench_glob_reads_the_unit_files_and_their_rotated_generations(self):
        # bench-lib.sh passes --node-glob <BENCH_CERT_LOG_GLOB default> (teardown analysis and the
        # certification record): the unit's append files, split by logrotate into the live file and
        # .rotated-<N> generations (one also pulled beside its name, -<UTC>.rotated-<N>), hold the
        # whole run once; the container logs are not read.
        m = re.search(r'^_bench_cert_log_glob\(\) \{ printf .*"\$\{BENCH_CERT_LOG_GLOB:-([^}]+)\}"; \}$', LIB, re.M)
        self.assertIsNotNone(m, "bench-lib.sh _bench_cert_log_glob")
        glob = m.group(1)
        self.assertEqual(glob, "bench-validator-*-unit-stdout*.log.gz")
        whole = self.doc("--windows", str(FIX / "manifest.json"))
        for src in sorted((FIX / "node-logs").glob("*.log")):
            node = src.name[:len("bench-validator-01")]
            lines = src.read_text().splitlines(True)
            # Rotated at the phase boundary: a subdag's "certificate committed" lines and its "subdag
            # committed" line stay in one file (cert-rate.py pairs them within a file).
            half = next(i for i, line in enumerate(lines) if line >= "ts=2026-10-06T06:10")
            for name, text in (("unit-stdout.rotated-1", lines[:half]), ("unit-stdout", lines[half:]),
                               ("unit-stdout-20261104T003616Z.rotated-1", lines[:half])):
                (self.logs / ("%s-%s.log.gz" % (node, name))).write_bytes(gzip.compress("".join(text).encode()))
            # The container log holds a header the unit files do not: it must not be read.
            (self.logs / ("%s-telcoin.log.gz" % node)).write_bytes(gzip.compress(
                (src.read_text() + 'ts=2026-10-06T06:05:00.000000000Z level=info target=consensus::metrics '
                 'message="header proposed" round=99 epoch=1 num_batches=1 num_parents=7\n').encode()))
        split = self.doc("--windows", str(FIX / "manifest.json"), "--node-glob", glob)
        self.assertEqual(sorted(split["nodes"]), sorted(whole["nodes"]))
        self.assertEqual(len(split["nodes"]["bench-validator-01"]["files"]), 3)
        for w in whole["windows"]:
            with self.subTest(window=w["name"]):
                self.assertEqual(self.window(split, w["name"])["nodes"], w["nodes"])
        # Without the glob the container log's extra header is counted.
        every = self.doc("--windows", str(FIX / "manifest.json"))
        run = self.window(every, "run")["nodes"]["bench-validator-01"]
        self.assertEqual(run["proposed"], self.window(whole, "run")["nodes"]["bench-validator-01"]["proposed"] + 1)

    def test_without_an_authority_the_shares_stay_empty_unless_given(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        text = (FIX / "node-logs" / "bench-validator-01-telcoin.log").read_text().replace(" auth=" + A1, "")
        (plain / "validator-1-clean.log").write_text(text)       # devnet download-logs.sh naming, not gzipped
        args = ["--logs", str(plain), "--node-glob", "*-clean.log", "--node-name-regex", r"^(.+)-clean\.log$",
                "--format", "json", "--from", "2026-10-06T06:00:00Z", "--to", "2026-10-06T06:10:00Z"]
        p = subprocess.run([sys.executable, str(TOOL)] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        doc = json.loads(p.stdout)
        v = doc["windows"][0]["nodes"]["validator-1"]
        self.assertIsNone(doc["nodes"]["validator-1"]["authority"])
        self.assertEqual((v["proposed"], v["quorum"]), (2, 2))
        self.assertEqual((v["own_cert_pct"], v["own_leader_pct"], v["not_committed_pct"]), (None, None, None))
        p = subprocess.run([sys.executable, str(TOOL)] + args + ["--authority", "validator-1=" + A1],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        doc = json.loads(p.stdout)
        self.assertEqual(doc["nodes"]["validator-1"]["authority_source"], "--authority")
        self.assertEqual(doc["windows"][0]["nodes"]["validator-1"]["own_leader_pct"], 100.0)

    def test_markdown_and_csv(self):
        p = self.run_tool("--windows", str(FIX / "manifest.json"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.count("\n## "), 3)
        self.assertIn("| bench-validator-02 | B2bbbbbb | 3 | 0 | 0.0 |", p.stdout)
        self.assertIn("| **fleet** | | 5 | 2 | 40.0 |", p.stdout)
        self.assertIn("fair share 50.0 %", p.stdout)
        p = self.run_tool("--windows", str(FIX / "manifest.json"), "--format", "csv")
        rows = list(csv.DictReader(io.StringIO(p.stdout)))
        self.assertEqual(len(rows), 3 * 3)   # two nodes + fleet, per window
        self.assertEqual(rows[1]["rate_pct"], "0.0")
        self.assertEqual(rows[2]["node"], "fleet")

    def test_exit_codes(self):
        self.assertEqual(self.run_tool("--node-glob", "nothing-*.gz").returncode, 2)
        self.assertEqual(self.run_tool("--from", "2026-10-06T06:00:00Z").returncode, 2)       # argparse error
        self.assertEqual(self.run_tool("--from", "2026-10-06T06:10:00Z", "--to", "2026-10-06T06:00:00Z").returncode, 1)
        self.assertEqual(self.run_tool("--windows", str(Path(self._tmp.name) / "absent.json")).returncode, 1)
        p = self.run_tool("--windows", str(FIX / "node-logs" / "bench-validator-01-telcoin.log"))
        self.assertEqual(p.returncode, 1)


if __name__ == "__main__":
    unittest.main()
