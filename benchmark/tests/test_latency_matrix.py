"""latency-matrix.py tables from fixture probe output, and latency-probe.sh's dry run.

The fixture run (fixtures/latency/run) has four zones (A..D) and one skipped zone:
  A-B  UDP 10/12 -> 11.00, TCP 10.00: exactly +10 %, so NOT flagged (the rule is strictly above)
  A-C  UDP 51.00 vs TCP 40.00: +27.5 %, flagged
  A-D  D has no entry for A (one direction only, `*`); A->D lost 1 of 10 UDP echoes, flagged
  C-D  C->D lost every UDP echo and ping (one direction only), flagged with 100 % loss
"""
import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BENCH = Path(__file__).resolve().parents[1]
TOOLS = BENCH / "tools"
RUN = Path(__file__).resolve().parent / "fixtures" / "latency" / "run"
SPEC = importlib.util.spec_from_file_location("latency_matrix", str(TOOLS / "latency-matrix.py"))
lm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lm)

A, B, C, D = "aa-west1-a", "bb-east1-b", "cc-north1-c", "dd-south1-d"
DASH = "—"
LAYOUT = "t=%s" % ",".join([A, A, A, B, B, B, C, C, D, D])


def run_cli(*args):
    """latency-matrix.py's main() with its progress lines swallowed."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return lm.main(list(args))


def read_csv(path):
    with open(str(path), encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    return {r[0]: dict(zip(rows[0][1:], r[1:])) for r in rows[1:]}, rows[0][1:]


class MatrixRun(unittest.TestCase):
    """Runs the CLI once on the fixture into a temporary directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="latency-matrix-")
        cls.out = Path(cls.tmp) / "out"
        assert run_cli(str(RUN), "--out", str(cls.out), "--layout", LAYOUT) == 0
        with open(str(cls.out / "summary.json"), encoding="utf-8") as fh:
            cls.summary = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def pair(self, a, b):
        return next(p for p in self.summary["pairs"] if {p["a"], p["b"]} == {a, b})

    def test_writes_every_table(self):
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(names, sorted([
            "matrix-udp.csv", "matrix-udp.md", "matrix-tcp.csv", "matrix-tcp.md", "matrix-icmp.csv",
            "matrix-icmp.md", "tcp-vs-udp.md", "kth-nearest.md", "kth-nearest-t.md", "summary.json"]))

    def test_udp_csv_cells_average_directions_and_mark_one_way(self):
        cells, header = read_csv(self.out / "matrix-udp.csv")
        self.assertEqual(header, [A, B, C, D])   # run.json order, skipped zone left out
        self.assertEqual(cells[A], {A: DASH, B: "11.00", C: "51.00", D: "100.00*"})
        self.assertEqual(cells[C], {A: "51.00", B: "30.00", C: DASH, D: "118.00*"})
        self.assertEqual(cells[D][A], "100.00*")   # symmetric: the missing D->A is not a second value

    def test_tcp_and_icmp_cells(self):
        tcp, _ = read_csv(self.out / "matrix-tcp.csv")
        icmp, _ = read_csv(self.out / "matrix-icmp.csv")
        self.assertEqual(tcp[C][D], "117.50")     # both directions measured
        self.assertEqual(tcp[A][D], "99.00*")
        self.assertEqual(icmp[A][B], "9.10")      # ping avg, averaged over the two directions
        self.assertEqual(icmp[C][D], "116.00*")   # C->D ping lost everything

    def test_delta_flags(self):
        ab, ac, bc = self.pair(A, B), self.pair(A, C), self.pair(B, C)
        self.assertEqual((ab["udp_ms"], ab["tcp_ms"], ab["delta_pct"], ab["flags"]), (11.0, 10.0, 10.0, []))
        self.assertEqual((ac["delta_ms"], ac["delta_pct"], ac["flags"]), (11.0, 27.5, [lm.FLAG_SLOWER]))
        self.assertEqual(bc["flags"], [])
        self.assertEqual((ab["udp_ab_ms"], ab["udp_ba_ms"]), (10.0, 12.0))   # the two flows, unaveraged
        self.assertEqual((self.pair(C, D)["tcp_min_ms"], self.pair(C, D)["tcp_max_ms"]), (117.0, 118.0))
        flagged = sorted((p["a"], p["b"]) for p in self.summary["flags"])
        self.assertEqual(flagged, [(A, C), (A, D), (C, D)])
        text = (self.out / "tcp-vs-udp.md").read_text(encoding="utf-8")
        self.assertIn("3 of 6 pairs flagged", text)
        self.assertIn("| %s \u2194 %s | 11.00 | 10.00 / 12.00 | 10.00 | 10.00\u201310.00 | +1.00 | +10.00%% | 0 |  |"
                      % (A, B), text)

    def test_loss_handling(self):
        ad, cd = self.pair(A, D), self.pair(C, D)
        self.assertEqual((ad["udp_loss_pct"], ad["flags"], ad["one_way"]["udp"]), (10.0, [lm.FLAG_LOSS], True))
        self.assertEqual((cd["udp_ms"], cd["udp_loss_pct"], cd["flags"]), (118.0, 100.0, [lm.FLAG_LOSS]))
        self.assertTrue(cd["one_way"]["udp"])
        self.assertFalse(cd["one_way"]["tcp"])

    def test_kth_nearest_orders_ascending(self):
        kn = self.summary["kth_nearest"]
        self.assertEqual([z for z, _, _ in kn[C]["sorted"]], [B, A, D])
        self.assertEqual([z for z, _, _ in kn[D]["sorted"]], [B, A, C])
        self.assertEqual(kn[D]["sorted"][1], [A, 100.0, "*"])
        self.assertIsNone(kn[A]["k5"])    # three other zones: no 5th or 6th
        self.assertIsNone(kn[A]["k6"])

    def test_layout_cut(self):
        lay = self.summary["layouts"]["t"]
        self.assertEqual(lay["assumed_intra_ms"], 1.0)
        pz = lay["per_zone"]
        self.assertEqual({z: (v["validators"], v["k5"], v["k6"]) for z, v in pz.items()}, {
            A: (3, [B, 11.0], [C, 51.0]),     # 1 1 | 11 11 11 | 51 51 | 100 100
            B: (3, [A, 11.0], [C, 30.0]),     # 1 1 | 11 11 11 | 30 30 | 80 80
            C: (2, [A, 51.0], [A, 51.0]),     # 1 | 30 30 30 | 51 51 51 | 118 118
            D: (2, [A, 100.0], [A, 100.0]),   # 1 | 80 80 80 | 100 100 100 | 118 118
        })
        self.assertEqual(pz[A]["sorted"][0], [A, 1.0, lm.INTRA])
        self.assertEqual(len(pz[A]["sorted"]), 9)
        self.assertEqual((lay["fleet"]["max_k6_ms"], lay["fleet"]["max_k6_zone"]), (100.0, D))
        self.assertEqual(lay["fleet"]["median_k6_ms"], 51.0)
        text = (self.out / "kth-nearest-t.md").read_text(encoding="utf-8")
        self.assertIn("2f+1 = 7", text)
        self.assertIn("| %s | 3 | 11.00 (%s) | 51.00 (%s) |" % (A, B, C), text)
        self.assertIn("assumed to be 1.00 ms", text)

    def test_skipped_zone_error_is_scrubbed(self):
        self.assertEqual([s["zone"] for s in self.summary["skipped"]], ["ee-gone1-a"])
        err = self.summary["skipped"][0]["error"]
        self.assertIn("projects/<project>/", err)
        self.assertNotIn("example-proj", json.dumps(self.summary))
        self.assertNotIn("192.0.2.", json.dumps(self.summary))
        self.assertIn("ee-gone1-a (ZONE_RESOURCE_POOL_EXHAUSTED)",
                      (self.out / "matrix-udp.md").read_text(encoding="utf-8"))


class ZoneSubsetTests(unittest.TestCase):
    def test_zones_subset_recuts_tables_and_marks_unknown_zone(self):
        tmp = tempfile.mkdtemp(prefix="latency-matrix-")
        try:
            out = Path(tmp)
            self.assertEqual(run_cli(str(RUN), "--out", tmp, "--zones", "%s,%s,ee-gone1-a" % (B, A)), 0)
            cells, header = read_csv(out / "matrix-udp.csv")
            self.assertEqual(header, [B, A, "ee-gone1-a"])
            self.assertEqual(cells[B], {B: DASH, A: "11.00", "ee-gone1-a": DASH})
            with open(str(out / "summary.json"), encoding="utf-8") as fh:
                summary = json.load(fh)
            self.assertEqual(len(summary["pairs"]), 3)
            self.assertIsNone(summary["matrices"]["udp"][A]["ee-gone1-a"])
            no_data = next(p for p in summary["pairs"] if "ee-gone1-a" in (p["a"], p["b"]) and A in (p["a"], p["b"]))
            self.assertEqual(no_data["flags"], [lm.FLAG_NO_UDP])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def synthetic(n):
    """n zones on a line, z<i> to z<j> = 10 * |i - j| ms one way, so z0's k-th nearest is z<k>."""
    zones = ["zz-line%d-a" % i for i in range(n)]
    src = {}
    for i, a in enumerate(zones):
        peers = {}
        for j, b in enumerate(zones):
            if a != b:
                ms = 10.0 * abs(i - j)
                peers[b] = {"udp": {"samples_ms": [ms], "median_ms": ms, "loss_pct": 0.0},
                            "tcp": {"samples_ms": [ms], "median_ms": ms}, "icmp": {"avg": ms}}
        src[a] = {"src_zone": a, "peers": peers}
    return zones, lm.Data(src, {"zones": zones})


class KthSelectionTests(unittest.TestCase):
    def test_fifth_and_sixth_nearest(self):
        zones, data = synthetic(8)
        kn = lm.kth_nearest(data, zones)
        self.assertEqual(kn[zones[0]]["k"][5][:2], (zones[5], 50.0))
        self.assertEqual(kn[zones[0]]["k"][6][:2], (zones[6], 60.0))
        # z3 has neighbours on both sides: 10 10 20 20 30 30 40 50 -> 5th and 6th are both 30 ms,
        # and ties keep the zone order (z0 before z6).
        self.assertEqual(kn[zones[3]]["k"][5][:2], (zones[0], 30.0))
        self.assertEqual(kn[zones[3]]["k"][6][:2], (zones[6], 30.0))

    def test_unreachable_zones_sort_last_and_do_not_count(self):
        zones, data = synthetic(7)
        for a in (zones[0], zones[1]):
            other = zones[1] if a == zones[0] else zones[0]
            data.src[a]["peers"][other]["udp"] = {"samples_ms": [], "median_ms": None, "loss_pct": 100.0}
        kn = lm.kth_nearest(data, zones)
        self.assertEqual(kn[zones[0]]["unreachable"], [zones[1]])
        self.assertEqual(kn[zones[0]]["k"][5][:2], (zones[6], 60.0))
        self.assertIsNone(kn[zones[0]]["k"][6])   # z1 lost every echo: five reachable zones remain

    def test_layout_uses_measured_intra_zone_rtt_when_present(self):
        zones, data = synthetic(3)
        data.src[zones[0]]["peers"][zones[0]] = {"udp": {"median_ms": 0.25}}
        lk, assumed = lm.layout_kth(data, [zones[0], zones[0], zones[1]])
        self.assertFalse(assumed)
        self.assertEqual(lk[zones[0]]["sorted"][0], (zones[0], 0.25, ""))


class CliTests(unittest.TestCase):
    def test_bad_layout_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_cli(str(RUN), "--layout", "no-equals-sign")
        with self.assertRaises(SystemExit):
            run_cli(str(RUN), "--layout", "x=%s" % A)

    def test_empty_directory_is_an_error(self):
        tmp = tempfile.mkdtemp(prefix="latency-matrix-")
        try:
            self.assertEqual(run_cli(tmp), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class ProbeDryRunTests(unittest.TestCase):
    """latency-probe.sh --dry-run prints the gcloud argv and the remote scripts; it runs no gcloud."""

    def run_probe(self, *args):
        return subprocess.run(["bash", str(TOOLS / "latency-probe.sh")] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True, timeout=60,
                              cwd=tempfile.gettempdir(), env={"PATH": "/usr/bin:/bin"})

    def test_dry_run_prints_argv_for_three_zones(self):
        zones = ["us-west2-a", "europe-west2-b", "asia-northeast1-b"]
        p = self.run_probe("--project", "example-proj", "--zones", ",".join(zones + zones[:1]), "--dry-run")
        self.assertEqual(p.returncode, 0, p.stdout)
        lines = p.stdout.splitlines()
        creates = [ln for ln in lines if "gcloud compute instances create" in ln]
        self.assertEqual(len(creates), 3)    # duplicate zone dropped
        for z, ln in zip(zones, creates):
            for part in ("lat-%s" % z, "--zone=%s" % z, "--no-address", "--image-family=debian-12",
                         "--tags=latency-probe", "--labels=purpose=latency-probe", "--project=example-proj"):
                self.assertIn(part, ln)
        for kind in ("ssh lat-%s" % z for z in zones):
            self.assertEqual(sum(kind in ln for ln in lines), 3)   # ssh ready, echo servers, measure
        self.assertEqual(sum("firewall-rules create" in ln for ln in lines), 2)
        self.assertEqual(sum("instances delete" in ln for ln in lines), 3)
        self.assertIn("--source-tags=latency-probe", p.stdout)
        self.assertIn("--source-ranges=", p.stdout)
        self.assertIn("ECHO_READY", p.stdout)                  # the echo script is shown
        self.assertIn("LAT_PEERS=europe-west2-b=", p.stdout)   # the measure script is shown
        for ln in lines:   # never a list-flag value that starts with ^ (gcloud's delimiter syntax)
            self.assertNotIn("=^", ln)

    def test_needs_project_and_two_zones(self):
        self.assertEqual(self.run_probe("--zones", "us-west2-a,europe-west2-b", "--dry-run").returncode, 2)
        p = self.run_probe("--project", "example-proj", "--zones", "us-west2-a", "--dry-run")
        self.assertEqual(p.returncode, 2)
        p = self.run_probe("--project", "example-proj", "--zones", "us-west2-a,not_a_zone", "--dry-run")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
