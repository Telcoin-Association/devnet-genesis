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
import contextlib
import copy
import importlib.util
import io
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


# ---- bench6 blasts kind, real phases, load windows and arm windows ----
#
# A bench-6 manifest (benchmark/arms/MANIFEST-FIELDS.md) built in a temp results dir; blast.run_index 7
# (the headline, at the top of the results dir). T0 = 2026-01-01T00:00:00Z.
#
#   0  light 8x16    rc 0  arm a0  blast-0-<UTC>/blasters: mixed [T0+100, T0+460)        -> light8, "blasters"
#   1  light 8x16    rc 1  arm a0  never sent                                             -> not light; floor caveat
#   2  load 600x16   rc 0  arm a0  chaos off; blast-2-<UTC>/manifest.json with real phases (phases_planned):
#                                  mixed [T0+1000, T0+1480)                               -> load600, "manifest.phases"
#   3  load 600x16   rc 0  arm p1  nothing archived; real phases in the entry, mixed [T0+2000, T0+2480)
#                                  -> load600, "blasts[].phases"
#   4  light 600x4   rc 0  arm p1  blast-4-<UTC>/manifest.json with the plan only (mixed [T0+3000, T0+3360))
#                                  and the entry's real phases (mixed [T0+3010, T0+3372)) -> the entry's real ones
#   5  load 600x4    rc 0  arm p1  nothing archived, no phases                            -> load600x4, no window
#   6  load 600x16   rc 3  arm p1  failed                                                 -> not a load window
#   7  load 600x16   rc 0  arm p1  the headline                                           -> not a load window

def _utc(secs):
    return windows.iso(T0 + secs)


def _phases(mixed_lo, mixed_hi):
    return [{"name": "warmup", "start": _utc(mixed_lo - 60), "end": _utc(mixed_lo)},
            {"name": "mixed", "start": _utc(mixed_lo), "end": _utc(mixed_hi)},
            {"name": "cooldown", "start": _utc(mixed_hi), "end": _utc(mixed_hi + 60)}]


def _entry(index, kind, senders, window, rc, arm, started, **extra):
    e = {"index": index, "senders": senders, "window": window, "chaos": 0, "started": _utc(started),
         "ended": _utc(started + 600), "rc": rc, "kind": kind, "arm": arm}
    e.update(extra)
    return e


BENCH6_MANIFEST = {
    "schema": "tn-bench-manifest/v1", "run_id": "r20260101-0006",
    "blast": {"run_index": 7, "chaos": 0},
    "param_arms": [
        {"name": "a0", "begin": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:30:00Z", "via": "prestart",
         "nodes": {}, "switches": {"vote_queue_fix": "false"}},
        {"name": "p1", "begin": "2026-01-01T00:30:00Z", "end": None, "ready": "2026-01-01T00:31:40Z",
         "nodes": {"bench-validator-01": {"mdbx_random_advice": "true"}}, "switches": {"mdbx_random_advice": "true"}},
    ],
    "blasts": [
        _entry(0, "light", 8, 16, 0, "a0", 0),
        _entry(1, "light", 8, 16, 1, "a0", 600),
        _entry(2, "load", 600, 16, 0, "a0", 900, phases=_phases(1000, 1480), phases_planned=_phases(1000, 1440)),
        _entry(3, "load", 600, 16, 0, "p1", 1900, phases=_phases(2000, 2480), phases_planned=_phases(2000, 2440)),
        _entry(4, "light", 600, 4, 0, "p1", 2900, phases=_phases(3010, 3372), phases_planned=_phases(3000, 3360)),
        _entry(5, "load", 600, 4, 0, "p1", 3500),
        _entry(6, "load", 600, 16, 3, "p1", 4200),
        _entry(7, "load", 600, 16, 0, "p1", 5000),
    ],
}


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f)


def build_bench6_run(root):
    """The bench-6 run above under root/; returns its path."""
    run = os.path.join(root, "r20260101-0006")
    _write_json(os.path.join(run, "manifest.json"), BENCH6_MANIFEST)
    b0 = os.path.join(run, "blast-0-20260101T001000Z")
    _write_json(os.path.join(b0, "blasters", "gen-a.json"), blaster("gen-a", T0 + 100, T0 + 460))
    _write_json(os.path.join(b0, "blasters", "gen-b.json"), blaster("gen-b", T0 + 105, T0 + 455))
    _write_json(os.path.join(run, "blast-2-20260101T002600Z", "manifest.json"),
                {"phases": _phases(1000, 1480), "phases_planned": _phases(1000, 1440)})
    _write_json(os.path.join(run, "blast-4-20260101T005900Z", "manifest.json"), {"phases": _phases(3000, 3360)})
    return run


class Bench6BlastTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="windows-bench6-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = build_bench6_run(self.tmp)
        self.manifest = load_json(os.path.join(self.run_dir, "manifest.json"))

    def test_light_blasts_select_kind_light_and_rc_0(self):
        got = windows.light_blasts(self.run_dir, self.manifest)
        self.assertEqual([(b["name"], b["index"], b["kind"], b["arm"]) for b in got],
                         [("light8", 0, "light", "a0"), ("light600x4", 4, "light", "p1")])
        # The chaos-off load blast 2 is not light once kind is recorded (the bench-5 rule would take it).
        bare = copy.deepcopy(self.manifest)
        for e in bare["blasts"]:
            del e["kind"]
        self.assertEqual([b["index"] for b in windows.light_blasts(self.run_dir, bare)], [0, 1, 2, 3, 4, 5, 6])
        # Without kind the failed blast 1 stays a light blast, as in bench 5; with kind it does not.
        self.assertNotIn(1, [b["index"] for b in got])

    def test_floor_blast_names_a_failed_light8_with_kind(self):
        blast, caveats = windows.floor_blast(self.run_dir, self.manifest)
        self.assertEqual((blast["name"], blast["index"], caveats), ("light8", 0, []))
        only_failed = copy.deepcopy(self.manifest)
        only_failed["blasts"] = [e for e in only_failed["blasts"] if e["index"] != 0]
        self.assertEqual(windows.floor_blast(self.run_dir, only_failed),
                         (None, ["light8 blast (index 1) ended rc=1; floor KPIs not computed from it"]))

    def test_light_windows_read_real_phases_before_planned_ones(self):
        got = {w["index"]: w for w in windows.light_windows(self.run_dir, self.manifest)}
        self.assertEqual((got[0]["start_unix"], got[0]["end_unix"], got[0]["source"], got[0]["arm"]),
                         (T0 + 100, T0 + 460, "blasters", "a0"))
        # The copy holds the plan only; the entry's phases are real (phases_planned): they win.
        w4 = got[4]
        self.assertEqual((w4["start_unix"], w4["end_unix"], w4["secs"], w4["source"]),
                         (T0 + 3010, T0 + 3372, 362, "blasts[].phases"))
        self.assertEqual((w4["phases"], w4["phases_real"]), (_phases(3010, 3372), True))
        # Without the entry's real phases the copy's plan is read, as before.
        planned = copy.deepcopy(self.manifest)
        del planned["blasts"][4]["phases_planned"]
        w4 = {w["index"]: w for w in windows.light_windows(self.run_dir, planned)}[4]
        self.assertEqual((w4["start_unix"], w4["end_unix"], w4["source"], w4["phases_real"]),
                         (T0 + 3000, T0 + 3360, "manifest.phases", False))

    def test_load_blasts_and_windows(self):
        got = windows.load_blasts(self.run_dir, self.manifest)
        self.assertEqual([(b["name"], b["index"], b["arm"]) for b in got],
                         [("load600", 2, "a0"), ("load600", 3, "p1"), ("load600x4", 5, "p1")])
        w = windows.load_windows(self.run_dir, self.manifest)
        self.assertEqual([(x["index"], x["start_unix"], x["end_unix"], x["source"]) for x in w], [
            (2, T0 + 1000, T0 + 1480, "manifest.phases"),     # the copy's real phases
            (3, T0 + 2000, T0 + 2480, "blasts[].phases"),     # the entry's real phases
            (5, None, None, None)])                           # no approximate fallback for a load blast
        self.assertEqual((w[0]["arm"], w[0]["phases"], w[0]["phases_real"]), ("a0", _phases(1000, 1480), True))
        self.assertNotIn("phases", w[2])
        # A manifest without kind has no load windows (bench 5 and older).
        bare = copy.deepcopy(self.manifest)
        for e in bare["blasts"]:
            del e["kind"]
        self.assertEqual(windows.load_blasts(self.run_dir, bare), [])

    def test_cli_prints_load_windows_only_when_there_are_some(self):
        args = [str(BLASTERS), str(RUN / "combined.json"), "--run-dir", self.run_dir, "--keep-boundaries"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(windows.main(args), 0)
        doc = json.loads(out.getvalue())
        self.assertEqual([w["index"] for w in doc["light"]], [0, 4])
        self.assertEqual([w["index"] for w in doc["load"]], [2, 3, 5])
        bare = copy.deepcopy(self.manifest)
        for e in bare["blasts"]:
            del e["kind"]
        _write_json(os.path.join(self.run_dir, "manifest.json"), bare)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(windows.main(args), 0)
        self.assertNotIn("load", json.loads(out.getvalue()))

    def test_arm_window_starts_at_ready(self):
        a0, p1 = self.manifest["param_arms"]
        self.assertEqual(windows.arm_window(p1), {"name": "p1", "start_unix": T0 + 1900, "end_unix": None,
                                                  "secs": None, "start": "ready"})
        self.assertEqual(windows.arm_window(a0), {"name": "a0", "start_unix": T0, "end_unix": T0 + 1800,
                                                  "secs": 1800, "start": "begin"})
        closed = dict(p1, end="2026-01-01T01:00:00Z")
        self.assertEqual((windows.arm_window(closed)["start_unix"], windows.arm_window(closed)["secs"]),
                         (T0 + 1900, 1700))
        self.assertEqual([w["name"] for w in windows.arm_windows(self.manifest)], ["a0", "p1"])
        for broken in (None, "a0", {"name": "x"}, {"name": "x", "begin": "soon"}):
            self.assertIsNone(windows.arm_window(broken))
        self.assertEqual(windows.arm_windows({}), [])


class Bench5BlastsPinTests(unittest.TestCase):
    """The bench-5 manifest's blasts[] (no kind, arm or phases) selects exactly what it always did."""

    FIXTURE = TESTS / "fixtures" / "report" / "bench5-r20261107-1504" / "manifest-blasts.json"

    def test_light_and_load_blasts_unchanged(self):
        m = load_json(self.FIXTURE)
        with tempfile.TemporaryDirectory() as d:
            got = windows.light_blasts(d, m)
            self.assertEqual(got, [
                {"name": "light8", "index": 0, "senders": 8, "window": 16, "rc": 0,
                 "started": "2026-11-07T16:10:48Z", "ended": "2026-11-07T16:30:44Z", "dir": None},
                {"name": "light16", "index": 1, "senders": 16, "window": 16, "rc": 0,
                 "started": "2026-11-07T16:30:44Z", "ended": "2026-11-07T16:50:39Z", "dir": None},
                {"name": "light600x4", "index": 2, "senders": 600, "window": 4, "rc": 0,
                 "started": "2026-11-07T16:50:40Z", "ended": "2026-11-07T17:12:21Z", "dir": None}])
            self.assertEqual(windows.load_blasts(d, m), [])
            self.assertEqual(json.dumps(windows.light_windows(d, m)), json.dumps([
                {"name": "light8", "index": 0, "senders": 8, "window": 16, "start_unix": 1794067908,
                 "end_unix": 1794068984, "secs": 1076, "source": "blasts[] (approximate)", "boundaries": []},
                {"name": "light16", "index": 1, "senders": 16, "window": 16, "start_unix": 1794069104,
                 "end_unix": 1794070179, "secs": 1075, "source": "blasts[] (approximate)", "boundaries": []},
                {"name": "light600x4", "index": 2, "senders": 600, "window": 4, "start_unix": 1794070300,
                 "end_unix": 1794071481, "secs": 1181, "source": "blasts[] (approximate)", "boundaries": []}]))


if __name__ == "__main__":
    unittest.main()
