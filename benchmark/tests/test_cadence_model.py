"""cadence-model.py and propose-latency.py: the model reproduces the r20261006-0458 idle regime on the
committed 2026-10-06 matrix, and the latency reader pairs proposals with quorums by round."""
import gzip, importlib.util, os, statistics, subprocess, sys, tempfile, unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
MATRIX = Path(__file__).resolve().parents[1] / "latency" / "2026-10-06" / "matrix-udp.csv"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


OLD = ["us-west2-a", "us-west2-a", "australia-southeast1-c", "australia-southeast1-c", "northamerica-northeast1-b",
       "northamerica-northeast1-b", "europe-west4-a", "europe-west4-a", "europe-west2-b", "europe-west2-b"]
FINAL = ["us-west2-a", "europe-west2-b", "australia-southeast1-c", "asia-northeast1-b", "northamerica-northeast1-b",
         "europe-west4-a", "asia-southeast1-b", "asia-east2-a", "asia-northeast3-a", "asia-south1-a"]


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = load("cadence-model"); cls.m = cls.cm.load_matrix(str(MATRIX))

    def run_layout(self, layout, mn, mx=None):
        return self.cm.simulate(layout, self.m, mn, mx or max(500, 2 * mn), rounds=200)

    def test_old_layout_reproduces_0458_idle(self):
        res = self.run_layout(OLD, 250)
        T = statistics.median(r["T_p50"] for r in res)
        self.assertTrue(330 <= T <= 380, T)                       # measured 349 ms
        syd = [r for r in res if r["zone"] == "australia-southeast1-c"]
        self.assertTrue(all(r["cert_pct"] == 0.0 for r in syd))   # measured 0/3205
        near = [r for r in res if r["zone"] in ("us-west2-a", "europe-west2-b", "europe-west4-a")]
        self.assertTrue(all(r["cert_pct"] >= 99 for r in near))
        self.assertTrue(all(250 <= r["C_p50"] <= 320 for r in near), [r["C_p50"] for r in near])

    def test_min_delay_below_quorum_time_does_not_change_the_round(self):
        T = [statistics.median(r["T_p50"] for r in self.run_layout(FINAL, mn)) for mn in (50, 250)]
        self.assertAlmostEqual(T[0], T[1], delta=5)

    def test_final_layout_every_node_certifies_at_250(self):
        res = self.run_layout(FINAL, 250)
        self.assertTrue(all(r["cert_pct"] >= 99 for r in res), [(r["zone"], r["cert_pct"]) for r in res])
        self.assertTrue(all(r["ref_pct"] >= 99 for r in res))

    def test_large_min_delay_paces_the_round(self):
        T250 = statistics.median(r["T_p50"] for r in self.run_layout(FINAL, 250))
        T500 = statistics.median(r["T_p50"] for r in self.run_layout(FINAL, 500, 1000))
        self.assertGreater(T500, T250 + 100)

    def test_cli_table(self):
        out = subprocess.run([sys.executable, str(TOOLS / "cadence-model.py"), "--matrix", str(MATRIX),
                              "--layout", "x=" + ",".join(FINAL), "--min", "250", "--rounds", "120"],
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("| x | 250 | 500 |", out)


class ProposeLatencyTests(unittest.TestCase):
    def test_pairs_by_round(self):
        with tempfile.TemporaryDirectory() as d:
            lines = []
            t = 0.0
            for r in range(1, 21):
                lines.append('ts=2026-10-06T05:30:%06.3fZ level=info target=consensus::metrics message="header proposed" round=%d epoch=0\n' % (t, r))
                if r % 4:
                    lines.append('ts=2026-10-06T05:30:%06.3fZ level=info target=consensus::metrics message="quorum reached" round=%d epoch=0\n' % (t + 0.287, r))
                else:
                    lines.append('ts=2026-10-06T05:30:%06.3fZ level=error target=primary::certifier message="failed to get vote for header: Canceled" round=%d\n' % (t + 0.3, r))
                t += 0.35
            with gzip.open(os.path.join(d, "bench-validator-01-telcoin.log.gz"), "wt") as fh:
                fh.writelines(lines)
            out = subprocess.run([sys.executable, str(TOOLS / "propose-latency.py"), "--logs", d],
                                 capture_output=True, text=True, check=True).stdout
            row = [l for l in out.splitlines() if l.startswith("| bench-validator-01")][0]
            cells = [c.strip() for c in row.strip("|").split("|")]
            self.assertEqual(cells[1:4], ["20", "15", "75.0"])
            self.assertEqual(cells[4].split("/")[0], "287")
            self.assertEqual(cells[5].split("/")[0], "350")
            self.assertEqual(cells[7], "5")


if __name__ == "__main__":
    unittest.main()
