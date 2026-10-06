"""report/windows.py against the synthetic run in fixtures/report/synthetic-run.

The fixture (T0 = 1767225600 = 2026-01-01T00:00:00Z) has three blasters whose mixed phases are
staggered so the two windows differ:

    load-a  [T0,       T0 + 600)
    load-b  [T0 + 60,  T0 + 660)
    load-c  [T0 + 100, T0 + 700)

    merged          [T0,       T0 + 700)   700 s
    all generators  [T0 + 100, T0 + 600)   500 s

combined.series.per_second chain_tx: 10 outside the merged window, 100 on [T0, T0+100) and
[T0+600, T0+700), 200 on the all-generators window except a 500 burst on [T0+300, T0+360) and a
10-s gap [T0+400, T0+410) that is absent from the series (counts as 0). So:

    all generators  200*500 + 300*60 - 200*10 = 116000 tx   -> 232.0 tx/s
    merged          100*100 + 116000 + 100*100 = 136000 tx  -> 194.2857 tx/s
    best 60 s       the burst, 500.0 tx/s
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
WINDOWS_PY = BENCH / "report" / "windows.py"
SPEC = importlib.util.spec_from_file_location("report_windows", WINDOWS_PY)
windows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(windows)

RUN = TESTS / "fixtures" / "report" / "synthetic-run"
BLASTERS = RUN / "blasters"
T0 = 1767225600


def load_json(path):
    with open(path) as f:
        return json.load(f)


def blaster(label, start, end, name="mixed"):
    return {"schema": "tn-blast/v2",
            "run": {"label": label, "phases": [{"name": name, "start_unix": start, "end_unix": end}]}}


class FixtureMixin:
    @classmethod
    def setUpClass(cls):
        cls.blasters = windows.load_blasters(str(BLASTERS))
        cls.combined = load_json(RUN / "combined.json")
        cls.mixed = windows.mixed_windows(cls.blasters)


class WindowTests(FixtureMixin, unittest.TestCase):
    def test_mixed_windows_sorted_by_label(self):
        shuffled = list(reversed(self.blasters))
        self.assertEqual(windows.mixed_windows(shuffled), [
            {"label": "load-a", "start_unix": T0, "end_unix": T0 + 600},
            {"label": "load-b", "start_unix": T0 + 60, "end_unix": T0 + 660},
            {"label": "load-c", "start_unix": T0 + 100, "end_unix": T0 + 700},
        ])

    def test_merged_and_all_generators_differ(self):
        m = windows.merged(self.mixed)
        g = windows.all_generators(self.mixed)
        self.assertEqual(m, {"start_unix": T0, "end_unix": T0 + 700, "secs": 700})
        self.assertEqual(g, {"start_unix": T0 + 100, "end_unix": T0 + 600, "secs": 500})
        self.assertNotEqual(m, g)

    def test_all_generators_none_without_overlap(self):
        touching = [{"label": "a", "start_unix": 100, "end_unix": 200},
                    {"label": "b", "start_unix": 200, "end_unix": 300}]
        disjoint = [{"label": "a", "start_unix": 100, "end_unix": 150},
                    {"label": "b", "start_unix": 200, "end_unix": 300}]
        self.assertIsNone(windows.all_generators(touching))  # half-open: no common second
        self.assertIsNone(windows.all_generators(disjoint))
        self.assertIsNone(windows.all_generators([]))
        self.assertEqual(windows.merged(disjoint), {"start_unix": 100, "end_unix": 300, "secs": 200})
        with self.assertRaises(ValueError):
            windows.merged([])

    def test_check_merged_agrees_with_combined(self):
        self.assertEqual(windows.check_merged.key, "landed.window_secs")
        self.assertEqual(windows.check_merged(windows.merged(self.mixed), self.combined), [])

    def test_check_merged_reports_mismatch(self):
        m = windows.merged(self.mixed)
        shifted = copy.deepcopy(self.combined)
        shifted["landed"]["window_secs"] = {"start_unix": T0 + 5, "end_unix": T0 + 705}
        problems = windows.check_merged(m, shifted)
        self.assertEqual(len(problems), 1)  # same length, different position
        self.assertIn("differs from landed.window_secs", problems[0])

        longer = copy.deepcopy(self.combined)
        longer["landed"]["window_secs"]["end_unix"] = T0 + 710
        problems = windows.check_merged(m, longer)
        self.assertEqual(len(problems), 2)
        self.assertIn("700 s but landed.window_secs spans 710 s", problems[0])

        for broken in ({}, {"landed": {}}, {"landed": {"window_secs": {"start_unix": T0}}}):
            problems = windows.check_merged(m, broken)
            self.assertEqual(len(problems), 1)
            self.assertIn("cannot check", problems[0])


class SeriesTests(FixtureMixin, unittest.TestCase):
    def test_blocks_over_merged_window(self):
        out = windows.blocks(self.combined, self.mixed, T0, T0 + 700)
        self.assertEqual([(b["start_unix"] - T0, b["end_unix"] - T0, b["secs"]) for b in out],
                         [(0, 300, 300), (300, 600, 300), (600, 700, 100)])
        # [T0,T0+300): 100*100 + 200*200; [T0+300,T0+600): 500*60 + 200*230; tail: 100*100
        self.assertEqual([b["chain_tx"] for b in out], [50000, 76000, 10000])
        for b, tps in zip(out, (50000 / 300, 76000 / 300, 100.0)):
            self.assertAlmostEqual(b["chain_tps"], tps)
        # 10-s samples: block 1 has 30 samples, covered by a 30x, b 24x (x >= T0+60), c 20x
        # (x >= T0+100) -> 74/30; block 2 all three always; tail 10 samples: b 6x, c 10x -> 1.6
        for b, active in zip(out, (74 / 30, 3.0, 1.6)):
            self.assertAlmostEqual(b["generators_active"], active)
            self.assertIsInstance(b["generators_active"], float)
        self.assertEqual(sum(b["chain_tx"] for b in out), 136000)

    def test_blocks_keep_a_trailing_one_second_block(self):
        out = windows.blocks(self.combined, self.mixed, T0, T0 + 301)
        self.assertEqual(len(out), 2)
        self.assertEqual((out[1]["start_unix"], out[1]["secs"], out[1]["chain_tx"]), (T0 + 300, 1, 500))
        self.assertEqual(out[1]["generators_active"], 3.0)
        custom = windows.blocks(self.combined, self.mixed, T0, T0 + 700, step=250, sample=50)
        self.assertEqual([b["secs"] for b in custom], [250, 250, 200])
        # samples T0, T0+50, ..., T0+200: a 5x, b 3x (x >= T0+60), c 3x (x >= T0+100)
        self.assertAlmostEqual(custom[0]["generators_active"], 11 / 5)

    def test_window_mean_counts_missing_seconds_as_zero(self):
        c = self.combined
        self.assertEqual(windows.window_mean_tps(c, T0 + 100, T0 + 600), 232.0)
        self.assertAlmostEqual(windows.window_mean_tps(c, T0, T0 + 700), 136000 / 700)
        self.assertEqual(windows.window_mean_tps(c, T0 + 400, T0 + 410), 0.0)
        self.assertEqual(windows.window_mean_tps(c, T0 + 395, T0 + 415), 100.0)  # 5*200 + 10*0 + 5*200
        self.assertEqual(windows.window_mean_tps(c, T0 + 2000, T0 + 2010), 0.0)  # past the series
        with self.assertRaises(ValueError):
            windows.window_mean_tps(c, T0, T0)
        no_column = {"series": {"per_second_columns": ["s", "own_tx"], "per_second_t0_unix": T0,
                                "per_second": [[0, 5]]}}
        self.assertEqual(windows.window_mean_tps(no_column, T0, T0 + 1), 0.0)

    def test_best_60s(self):
        c = self.combined
        self.assertEqual(windows.best_60s_tps(c, T0, T0 + 700), 500.0)
        self.assertEqual(windows.best_60s_tps(c, T0, T0 + 700),
                         c["landed"]["sustained_mixed_tps_chain_60s"])
        self.assertIsNone(windows.best_60s_tps(c, T0, T0 + 59))
        self.assertEqual(windows.best_60s_tps(c, T0, T0 + 60), 100.0)
        self.assertEqual(windows.best_60s_tps(c, T0 + 330, T0 + 390), 350.0)  # 30*500 + 30*200

    def test_iso(self):
        self.assertEqual(windows.iso(T0), "2026-01-01T00:00:00Z")
        self.assertEqual(windows.iso(T0 + 3725.9), "2026-01-01T01:02:05Z")  # truncated, UTC
        self.assertEqual(windows.iso(str(T0 + 700)), "2026-01-01T00:11:40Z")


class BuildTests(FixtureMixin, unittest.TestCase):
    def test_build_clean_run(self):
        out = windows.build(self.blasters, self.combined)
        self.assertEqual(out["caveats"], [])
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["merged"]["secs"], 700)
        self.assertEqual(out["all_generators"]["secs"], 500)
        self.assertEqual([w["label"] for w in out["mixed_windows"]], ["load-a", "load-b", "load-c"])

    def test_build_caveats_blaster_without_mixed_phase(self):
        bl = copy.deepcopy(self.blasters)
        bl[1]["run"]["phases"] = [p for p in bl[1]["run"]["phases"] if p["name"] != "mixed"]
        out = windows.build(bl, self.combined)
        self.assertEqual(out["caveats"], ["load-b: no mixed phase; excluded from the windows"])
        self.assertEqual(out["problems"], [])  # a and c still span [T0, T0+700)
        self.assertEqual([w["label"] for w in out["mixed_windows"]], ["load-a", "load-c"])
        self.assertEqual(out["all_generators"], {"start_unix": T0 + 100, "end_unix": T0 + 600, "secs": 500})

    def test_build_caveats_unusable_span_and_label_fallbacks(self):
        bl = [blaster("good", T0, T0 + 100), blaster("flat", T0 + 50, T0 + 50),
              {"run": {"run_id": "rid-only", "phases": [{"name": "mixed", "start_unix": T0}]}},
              {"run": {"phases": []}}]
        out = windows.build(bl, None)
        self.assertEqual(out["caveats"], [
            "flat: mixed phase has no usable span (%d..%d); excluded from the windows" % (T0 + 50, T0 + 50),
            "rid-only: mixed phase has no usable span (%d..None); excluded from the windows" % T0,
            "blaster-3: no mixed phase; excluded from the windows",
            "no combined result; merged window not checked against landed.window_secs",
        ])
        self.assertEqual(out["merged"], {"start_unix": T0, "end_unix": T0 + 100, "secs": 100})

    def test_build_without_overlap_or_mixed_phases(self):
        out = windows.build([blaster("b", T0 + 200, T0 + 300), blaster("a", T0, T0 + 100)], None)
        self.assertIsNone(out["all_generators"])
        self.assertIn(windows.UNDEFINED_ALL_GENERATORS, out["caveats"])
        self.assertIsNone(windows.to_run_json(out)["all_generators"])

        empty = windows.build([], self.combined)
        self.assertEqual(empty["problems"], ["no blaster has a usable mixed phase"])
        self.assertIsNone(empty["merged"])
        self.assertIsNone(windows.to_run_json(empty))

    def test_to_run_json_shape(self):
        out = windows.to_run_json(windows.build(self.blasters, self.combined))
        self.assertEqual(out, {
            "merged_mixed": {"start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-01-01T00:11:40Z", "secs": 700},
            "all_generators": {"start_utc": "2026-01-01T00:01:40Z", "end_utc": "2026-01-01T00:10:00Z",
                               "secs": 500},
        })
        self.assertIsNone(windows.to_run_json(None))
        self.assertIsNone(windows.to_run_json({}))

    def test_load_blasters_ignores_combined_and_other_json(self):
        with tempfile.TemporaryDirectory() as d:
            for p in BLASTERS.glob("*.json"):
                shutil.copy(str(p), d)
            shutil.copy(str(RUN / "combined.json"), d)
            shutil.copy(str(RUN / "manifest.json"), d)
            with open(os.path.join(d, "array.json"), "w") as f:
                f.write("[1, 2]\n")
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write("not json\n")
            docs = windows.load_blasters(d)
        self.assertEqual([doc["run"]["label"] for doc in docs], ["load-a", "load-b", "load-c"])
        self.assertTrue(all(doc["schema"] == "tn-blast/v2" for doc in docs))


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(WINDOWS_PY)] + [str(a) for a in args],
                              capture_output=True, text=True)

    def test_exit_0_on_clean_run(self):
        res = self.run_cli(BLASTERS, RUN / "combined.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual(out["merged"]["secs"], 700)
        self.assertNotIn("blocks", out)
        res = self.run_cli(BLASTERS, RUN / "combined.json", "--blocks")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([b["chain_tx"] for b in json.loads(res.stdout)["blocks"]], [50000, 76000, 10000])

    def test_exit_1_on_window_mismatch(self):
        combined = load_json(RUN / "combined.json")
        combined["landed"]["window_secs"]["end_unix"] += 5
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "combined.json")
            with open(path, "w") as f:
                json.dump(combined, f)
            res = self.run_cli(BLASTERS, path)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertEqual(len(json.loads(res.stdout)["problems"]), 2)

    def test_exit_2_on_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("{not json")
            for args in ((BLASTERS, os.path.join(d, "missing.json")),   # no combined file
                         (BLASTERS, bad),                               # unparsable combined
                         (d, RUN / "combined.json")):                   # unparsable blaster in dir
                res = self.run_cli(*args)
                self.assertEqual(res.returncode, 2, (args, res.stdout))
                self.assertIn("windows.py:", res.stderr)
            empty = os.path.join(d, "empty")
            os.mkdir(empty)
            res = self.run_cli(empty, RUN / "combined.json")            # no tn-blast results
            self.assertEqual(res.returncode, 2)
            self.assertIn("no tn-blast results", res.stderr)


if __name__ == "__main__":
    unittest.main()
