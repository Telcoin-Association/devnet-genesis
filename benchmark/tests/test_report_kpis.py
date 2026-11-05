"""report/kpis.py against the synthetic run in fixtures/report/synthetic-run.

T0 = 1767225600 (2026-01-01T00:00:00Z). Windows: merged [T0, T0+700), all generators
[T0+100, T0+600) (see test_report_windows.py for the chain series). Validators val-1, val-2,
val-3, observer obs-1; manifest.chaos kills val-3 at T0+200 and starts it at T0+260 (plus an
observer `systemctl restart` and a failed kill with rc=1, neither of which is a target), so the
healthy validators are val-1 and val-2. Hand-computed expectations:

  avg chain tps          116000 / 500                                     232.0
  best 60 s              the 500 tx/s burst                               500.0
  landed total           combined.totals.landed_chain                     136400
  blocks/s               70 blocks in [T0, T0+700) / 700 (3 at T0-1 and
                         7 at T0+700 sit outside the half-open window)     0.1
  time to land           ts_ms p50 1250, p95 4865 -> s, half-up            1.25, 4.87
  GCP series             12 in-window 60-s points = base * a permutation of 1..12 (12 at exactly
                         T0), one more of 13 * base at exactly T0+700, and x100 outliers just
                         outside the window; nearest-rank p95 of 13 is the 12th smallest
                         -> 12 * base (11 * base if either inclusive end point were dropped)
    disk write bytes     val-1 1 MiB, val-2 2 MiB (val-3 10, obs-1 50)    24.0 MiB/s (val-2)
    disk write ops       val-1 100, val-2 50 (val-3 1000)                 1200 (val-1)
    cpu                  val-1 5, val-2 4 (val-3 9)                       60.0 (val-1)
    rss                  val-1 GiB/8, val-2 GiB/4 (val-3 1 GiB)           3.0 GiB (val-2)
  Prometheus series      21 in-window points = scale * a permutation of 1..21; p95 is the
                         20th smallest, the median the 11th
    commit p95           val-1 0.125, val-2 0.1 (val-3 1.0, obs-1 2.0)    [2.0, 2.5]
    execution mean       val-1 0.01, val-2 0.02 (val-3 0.5)               [0.11, 0.22]
  psi io max             val-2 7.25 at exactly T0+700 (inclusive bound),
                         val-1 12.5; 90/95 spikes outside the window       [7.3, 12.5]
  recovery (val-3)       tn_node_mode reads 1 from T0+285 to T0+390 (and a stale 1 at T0+45,
                         before the kill), then 0 to the window's end at T0+690; failed_reports
                         is the seal-failure counter's rise over the window, count[val-3] -> 42
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kpis = _load("report_kpis", BENCH / "report" / "kpis.py")
windows_mod = _load("report_windows_for_kpis", BENCH / "report" / "windows.py")

RUN = TESTS / "fixtures" / "report" / "synthetic-run"
T0 = 1767225600
WINDOWS = {"merged": {"start_unix": T0, "end_unix": T0 + 700, "secs": 700},
           "all_generators": {"start_unix": T0 + 100, "end_unix": T0 + 600, "secs": 500}}

EXPECTED = {
    "avg_chain_tps_all_generators": ("value", 232.0),
    "best_60s_chain_tps_all_generators": ("value", 500.0),
    "landed_total": ("value", 136400),
    "blocks_per_sec": ("value", 0.1),
    "time_to_land_p50_s": ("value", 1.25),
    "time_to_land_p95_s": ("value", 4.87),
    "commit_latency_p95_s": ("range", [2.0, 2.5]),
    "execution_time_per_output_s": ("range", [0.11, 0.22]),
    "disk_write_p95_mibps_busiest": ("value", 24.0),
    "disk_write_iops_p95_busiest": ("value", 1200),
    "cpu_p95_pct_busiest": ("value", 60.0),
    "rss_p95_gib_busiest": ("value", 3.0),
    "psi_io_max_pct": ("range", [7.3, 12.5]),
}

EXPECTED_RECOVERY = {
    "node": "val-3",
    "killed_utc": "2026-01-01T00:03:20Z",
    "restarted_utc": "2026-01-01T00:04:20Z",
    "demoted_utc": "2026-01-01T00:04:45Z",
    "rejoined_utc": "2026-01-01T00:06:45Z",
    "catch_up_secs": 120,
    "failed_reports": 42,
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.combined = load_json(RUN / "combined.json")
        cls.metrics = load_json(RUN / "metrics.json")
        cls.manifest = load_json(RUN / "manifest.json")
        cls.sampler = kpis.load_sampler(str(RUN / "sampler"))

    def compute(self, combined=None, metrics=None, manifest=None, windows=None, targets=("val-3",)):
        return kpis.compute(self.combined if combined is None else combined,
                            self.metrics if metrics is None else metrics,
                            self.sampler,
                            self.manifest if manifest is None else manifest,
                            WINDOWS if windows is None else windows,
                            list(targets))

    @staticmethod
    def by_id(out):
        return {k["id"]: k for k in out["kpis"]}


class HelperTests(unittest.TestCase):
    def test_pct_is_nearest_rank(self):
        # derive-sizing.py definition: index round(q * (n - 1)) into the sorted list
        self.assertEqual(kpis.pct(range(1, 101), 0.95), 95)
        self.assertEqual(kpis.pct(list(range(100, 0, -1)), 0.95), 95)  # input order is irrelevant
        self.assertEqual(kpis.pct(range(1, 101), 0.5), 51)  # round(49.5) == 50 (half to even)
        self.assertEqual(kpis.pct(range(1, 13), 0.95), 11)  # 12 points: round(10.45) -> 11th smallest
        self.assertEqual(kpis.pct(range(1, 22), 0.95), 20)
        self.assertEqual(kpis.pct(range(1, 22), 0.5), 11)
        self.assertEqual(kpis.pct([3, 1, 2], 0.0), 1)
        self.assertEqual(kpis.pct([3, 1, 2], 1.0), 3)
        self.assertEqual(kpis.pct([7.5], 0.95), 7.5)

    def test_best_window_mean(self):
        self.assertIsNone(kpis.best_window_mean([], 60))
        # Fewer samples than the width: no such window, so no figure (aggregate.py would give the plain mean).
        self.assertIsNone(kpis.best_window_mean([1, 2, 3], 60))
        self.assertIsNone(kpis.best_window_mean([5] * 59, 60))
        self.assertEqual(kpis.best_window_mean([5] * 60, 60), 5.0)  # exactly one window
        self.assertEqual(kpis.best_window_mean([0, 0, 6, 6, 0], 2), 6.0)
        self.assertEqual(kpis.best_window_mean([1, 5, 1, 1], 3), 7 / 3)

    def test_iso_round_trip(self):
        self.assertEqual(kpis.iso_to_unix("2026-01-01T00:03:20Z"), T0 + 200)
        self.assertEqual(kpis.iso_to_unix("2026-01-01T01:03:20+01:00"), T0 + 200)
        self.assertEqual(kpis.iso_to_unix("2026-01-01T00:03:20"), T0 + 200)  # naive -> UTC
        self.assertEqual(kpis.unix_to_iso(T0 + 200.9), "2026-01-01T00:03:20Z")
        self.assertIsNone(kpis.unix_to_iso(None))

    def test_round_kpis_half_up_to_decimals(self):
        self.assertEqual(len(kpis.DECIMALS), 13)
        src = [
            {"id": "time_to_land_p95_s", "value": 2.675},
            {"id": "psi_io_max_pct", "range": [7.25, 12.04]},
            {"id": "landed_total", "value": 136400.4},
            {"id": "disk_write_iops_p95_busiest", "value": 1100.5},
            {"id": "not_a_kpi", "value": 1.005},
            {"id": "blocks_per_sec", "value": None},
        ]
        before = copy.deepcopy(src)
        out = kpis.round_kpis(src)
        self.assertEqual(src, before)  # inputs untouched
        self.assertEqual(round(2.675, 2), 2.67)  # float round() would publish 2.67
        self.assertEqual(out[0]["value"], 2.68)
        self.assertEqual(out[1]["range"], [7.3, 12.0])
        self.assertEqual(out[2]["value"], 136400)
        self.assertIsInstance(out[2]["value"], int)
        self.assertEqual(out[3]["value"], 1101)
        self.assertIsInstance(out[3]["value"], int)
        self.assertEqual(out[4]["value"], 1.01)  # unknown ids get 2 decimals
        self.assertIsNone(out[5]["value"])

    def test_headline_id(self):
        self.assertEqual(kpis.headline_id([{"id": "landed_total"}, {"id": kpis.HEADLINE_ID}]), kpis.HEADLINE_ID)
        self.assertEqual(kpis.headline_id([{"id": "landed_total"}, {"id": "blocks_per_sec"}]), "landed_total")
        self.assertIsNone(kpis.headline_id([]))
        self.assertIsNone(kpis.headline_id(None))


class LoaderTests(unittest.TestCase):
    def test_load_sampler(self):
        s = kpis.load_sampler(str(RUN / "sampler"))
        self.assertEqual(sorted(s), ["val-1", "val-2", "val-3"])
        self.assertEqual(len(s["val-2"]), 38)  # T0-20 .. T0+720 every 20 s
        last_in_window = [r for r in s["val-2"] if r["ts_unix"] == str(T0 + 700)]
        self.assertEqual(last_in_window[0]["psi_io_some_avg10"], "7.25")
        self.assertIn("rss_total_kb", s["val-1"][0])

    def test_load_blasters_skips_unreadable_and_non_objects(self):
        with tempfile.TemporaryDirectory() as d:
            for p in (RUN / "blasters").glob("*.json"):
                shutil.copy(str(p), d)
            for name, text in (("bad.json", "{oops"), ("array.json", "[1]"), ("norun.json", '{"run": 1}')):
                with open(os.path.join(d, name), "w") as f:
                    f.write(text)
            docs = kpis.load_blasters(d)
        self.assertEqual([doc["run"]["label"] for doc in docs], ["load-a", "load-b", "load-c"])

    def test_load_blasters_ignores_combined_file(self):
        with tempfile.TemporaryDirectory() as d:
            for p in (RUN / "blasters").glob("*.json"):
                shutil.copy(str(p), d)
            shutil.copy(str(RUN / "combined.json"), d)
            docs = kpis.load_blasters(d)
        self.assertEqual(len(docs), 3)


class ChaosTests(Fixture):
    def test_chaos_events_from_fixture(self):
        events = kpis.chaos_events(self.manifest)  # the rc=1 kill on val-1 is dropped
        self.assertEqual([(e["ts_unix"] - T0, e["node"], e["kind"]) for e in events],
                         [(150, "obs-1", "bounce"), (200, "val-3", "down"), (260, "val-3", "up")])
        self.assertEqual(events[1]["ts"], "2026-01-01T00:03:20Z")

    def test_targets_count_kill_but_not_restart(self):
        self.assertEqual(kpis.chaos_targets_from_manifest(self.manifest), ["val-3"])

    def test_targets_action_kinds_and_order(self):
        ts = lambda s: kpis.unix_to_iso(T0 + s)  # noqa: E731
        manifest = {"chaos": [
            {"ts": ts(50), "node": "v4", "action": "lag-unpause", "rc": 0},
            {"ts": ts(40), "node": "v4", "action": "lag-pause", "rc": 0},
            {"ts": ts(30), "node": "v2", "action": "systemctl stop"},  # rc missing counts as success
            {"ts": ts(20), "node": "v1", "action": "systemctl restart", "rc": 0},
            {"ts": ts(60), "node": "v2", "action": "docker kill", "rc": 0},  # already a target
            {"ts": ts(70), "node": "v5", "action": "snapshot", "rc": 0},  # unknown action
            {"ts": ts(80), "node": "v6", "action": "docker kill", "rc": 137},
            {"node": "v7", "action": "docker kill", "rc": 0},  # no timestamp
            {"ts": "not a time", "node": "v8", "action": "docker kill", "rc": 0},
        ]}
        self.assertEqual(kpis.chaos_targets_from_manifest(manifest), ["v2", "v4"])
        self.assertEqual([e["kind"] for e in kpis.chaos_events(manifest)],
                         ["bounce", "down", "down", "up", "down"])
        self.assertEqual(kpis.chaos_targets_from_manifest({}), [])
        self.assertEqual(kpis.chaos_targets_from_manifest(None), [])

    def test_healthy_validators_exclude_targets_and_other_roles(self):
        self.assertEqual(kpis.healthy_validators(self.manifest, ["val-3"]), ["val-1", "val-2"])
        self.assertEqual(kpis.healthy_validators(self.manifest, []), ["val-1", "val-2", "val-3"])
        self.assertEqual(kpis.healthy_validators(self.manifest, ["obs-1"]), ["val-1", "val-2", "val-3"])
        self.assertEqual(kpis.healthy_validators({}, []), [])


class ComputeTests(Fixture):
    def test_all_thirteen_kpis_hand_computed(self):
        out = self.compute()
        self.assertEqual([k["id"] for k in out["kpis"]], list(kpis.DECIMALS))
        got = self.by_id(out)
        for kid, (field, expected) in EXPECTED.items():
            with self.subTest(kpi=kid):
                self.assertEqual(got[kid][field], expected)
        self.assertIsInstance(got["landed_total"]["value"], int)
        self.assertIsInstance(got["disk_write_iops_p95_busiest"]["value"], int)
        self.assertEqual(kpis.headline_id(out["kpis"]), "avg_chain_tps_all_generators")

    def test_kpi_record_shape(self):
        for k in self.compute()["kpis"]:
            with self.subTest(kpi=k["id"]):
                self.assertEqual(("value" in k) + ("range" in k), 1)
                for field in ("label", "short_label", "unit", "source", "method", "window"):
                    self.assertTrue(isinstance(k.get(field), str) and k[field], field)
                self.assertIn(k["window"], (kpis.W_ALL, kpis.W_MERGED, kpis.W_RUN))
                self.assertEqual(k["provenance"], "computed")
                if "range" in k:
                    self.assertLessEqual(k["range"][0], k["range"][1])

    def test_busiest_node_per_measure(self):
        got = self.by_id(self.compute())
        self.assertEqual(got["disk_write_p95_mibps_busiest"]["source"], "metrics.gcp[val-2].disk_write_bytes_per_sec p95")
        self.assertEqual(got["disk_write_iops_p95_busiest"]["source"], "metrics.gcp[val-1].disk_write_ops_per_sec p95")
        self.assertEqual(got["cpu_p95_pct_busiest"]["source"], "metrics.gcp[val-1].cpu_utilization p95")
        self.assertEqual(got["rss_p95_gib_busiest"]["source"], "metrics.gcp[val-2].telcoin_rss_bytes p95")
        self.assertIn("(val-2)", got["disk_write_p95_mibps_busiest"]["method"])

    def test_busiest_tie_goes_to_later_name(self):
        metrics = copy.deepcopy(self.metrics)
        metrics["gcp"]["val-2"]["cpu_utilization"] = copy.deepcopy(metrics["gcp"]["val-1"]["cpu_utilization"])
        got = self.by_id(self.compute(metrics=metrics))
        self.assertEqual(got["cpu_p95_pct_busiest"]["source"], "metrics.gcp[val-2].cpu_utilization p95")
        self.assertEqual(got["cpu_p95_pct_busiest"]["value"], 60.0)

    def test_killed_validator_excluded(self):
        out = self.compute()
        self.assertIn("per-validator rows cover 2 validators; val-3 excluded as chaos target(s)", out["caveats"])
        # without the exclusion val-3 (and never the observer) dominates every per-validator row
        everyone = self.by_id(self.compute(targets=()))
        self.assertEqual(everyone["disk_write_p95_mibps_busiest"]["value"], 120.0)
        self.assertEqual(everyone["disk_write_iops_p95_busiest"]["value"], 12000)
        self.assertEqual(everyone["commit_latency_p95_s"]["range"], [2.0, 20.0])
        self.assertEqual(everyone["execution_time_per_output_s"]["range"], [0.11, 5.5])
        self.assertEqual(everyone["psi_io_max_pct"]["range"], [7.3, 50.0])

    def test_missing_node_series_is_a_caveat(self):
        metrics = copy.deepcopy(self.metrics)
        del metrics["gcp"]["val-2"]["disk_write_bytes_per_sec"]
        out = self.compute(metrics=metrics)
        got = self.by_id(out)
        self.assertEqual(got["disk_write_p95_mibps_busiest"]["value"], 12.0)  # val-1 alone
        self.assertIn("disk_write_p95_mibps_busiest: no disk_write_bytes_per_sec points for val-2", out["caveats"])
        del metrics["gcp"]["val-1"]["disk_write_bytes_per_sec"]
        out = self.compute(metrics=metrics)
        self.assertNotIn("disk_write_p95_mibps_busiest", self.by_id(out))
        self.assertTrue(any("disk_write_p95_mibps_busiest not computed" in c for c in out["caveats"]))

    def test_headline_fallback_without_all_generators_window(self):
        out = self.compute(windows={"merged": WINDOWS["merged"], "all_generators": None})
        ids = [k["id"] for k in out["kpis"]]
        self.assertEqual(ids, list(kpis.DECIMALS)[2:])
        self.assertEqual(kpis.headline_id(out["kpis"]), "landed_total")
        self.assertTrue(any(c.startswith("all-generators window undefined") for c in out["caveats"]))

    def test_all_generators_window_shorter_than_60s_has_no_best_60s(self):
        short = {"merged": WINDOWS["merged"], "all_generators": {"start_unix": T0 + 100, "end_unix": T0 + 145, "secs": 45}}
        out = self.compute(windows=short)
        ids = [k["id"] for k in out["kpis"]]
        self.assertNotIn("best_60s_chain_tps_all_generators", ids)
        self.assertEqual(ids, [i for i in kpis.DECIMALS if i != "best_60s_chain_tps_all_generators"])
        self.assertEqual(kpis.headline_id(out["kpis"]), kpis.HEADLINE_ID)  # the average still stands
        self.assertIn("the all-generators window is 45 s, shorter than 60 s: best-60-s chain throughput not computed",
                      out["caveats"])
        # A 60-s window is one window: its mean is the figure, and no caveat.
        sixty = {"merged": WINDOWS["merged"], "all_generators": {"start_unix": T0 + 100, "end_unix": T0 + 160, "secs": 60}}
        out = self.compute(windows=sixty)
        best = self.by_id(out)["best_60s_chain_tps_all_generators"]["value"]
        self.assertEqual(best, self.by_id(out)["avg_chain_tps_all_generators"]["value"])
        self.assertFalse(any("shorter than 60 s" in c for c in out["caveats"]))

    def test_without_any_window_only_run_kpis_remain(self):
        out = self.compute(windows={})
        self.assertEqual([k["id"] for k in out["kpis"]],
                         ["landed_total", "time_to_land_p50_s", "time_to_land_p95_s"])
        self.assertIn("merged window undefined: commit latency and execution time not computed", out["caveats"])

    def test_agrees_with_windows_module(self):
        built = windows_mod.build(windows_mod.load_blasters(str(RUN / "blasters")), self.combined)
        self.assertEqual(built["problems"], [])
        self.assertEqual(self.compute(windows=built), self.compute())
        got = self.by_id(self.compute())
        g = built["all_generators"]
        self.assertEqual(got["avg_chain_tps_all_generators"]["value"],
                         windows_mod.window_mean_tps(self.combined, g["start_unix"], g["end_unix"]))
        self.assertEqual(got["best_60s_chain_tps_all_generators"]["value"],
                         windows_mod.best_60s_tps(self.combined, g["start_unix"], g["end_unix"]))


class RecoveryTests(Fixture):
    def test_recovery_fields(self):
        out = self.compute()
        self.assertEqual(out["recovery"], EXPECTED_RECOVERY)
        self.assertIn("recovery: failed_reports is the rise of the batch-seal failure counter on val-3 over the "
                      "whole metrics window (metrics.prometheus.series.tn_batch_builder_seal_failures_total.count), "
                      "outage or not", out["caveats"])
        self.assertFalse(any("promoted" in c or "still rejoining" in c for c in out["caveats"]))

    def test_no_recovery_without_chaos_target(self):
        out = self.compute(targets=())
        self.assertIsNone(out["recovery"])
        self.assertFalse(any(c.startswith("recovery") for c in out["caveats"]))

    def test_recovery_prefers_a_validator_target(self):
        out = self.compute(targets=("obs-1", "val-3"))
        self.assertEqual(out["recovery"]["node"], "val-3")
        self.assertIn("recovery covers val-3 only; other chaos targets: obs-1", out["caveats"])

    def test_recovery_without_down_event(self):
        caveats = []
        rec = kpis.recovery(self.metrics, self.manifest, "obs-1", caveats)  # obs-1 was only bounced
        self.assertEqual(rec, {"node": "obs-1", "killed_utc": None, "restarted_utc": None, "demoted_utc": None,
                               "rejoined_utc": None, "catch_up_secs": None, "failed_reports": None})
        self.assertEqual(caveats, ["recovery: no down event for obs-1 in manifest.chaos"])

    def test_recovery_without_node_mode_series(self):
        metrics = copy.deepcopy(self.metrics)
        del metrics["prometheus"]["series"]["tn_node_mode"]
        caveats = []
        rec = kpis.recovery(metrics, self.manifest, "val-3", caveats)
        self.assertEqual((rec["demoted_utc"], rec["rejoined_utc"], rec["catch_up_secs"]), (None, None, None))
        self.assertEqual(rec["failed_reports"], 42)  # the counter does not depend on the mode series
        self.assertTrue(any("demoted / rejoined / catch-up unavailable" in c for c in caveats))

    def test_recovery_never_rejoins(self):
        metrics = copy.deepcopy(self.metrics)
        pts = metrics["prometheus"]["series"]["tn_node_mode"]["by_node"]["val-3"]["max"]
        for p in pts:
            if p[0] >= T0 + 285:
                p[1] = 1.0
        caveats = []
        rec = kpis.recovery(metrics, self.manifest, "val-3", caveats)
        self.assertEqual(rec["demoted_utc"], "2026-01-01T00:04:45Z")
        self.assertIsNone(rec["rejoined_utc"])
        self.assertIsNone(rec["catch_up_secs"])
        self.assertEqual(rec["failed_reports"], 42)
        self.assertIn("recovery: the metrics window ended while val-3 was still rejoining (inactive at its last "
                      "sample, 2026-01-01T00:11:30Z); rejoined and catch-up unavailable", caveats)

    def test_recovery_never_demoted(self):
        metrics = copy.deepcopy(self.metrics)
        for p in metrics["prometheus"]["series"]["tn_node_mode"]["by_node"]["val-3"]["max"]:
            p[1] = 0.0
        rec = kpis.recovery(metrics, self.manifest, "val-3", [])
        self.assertIsNone(rec["demoted_utc"])
        self.assertEqual(rec["rejoined_utc"], "2026-01-01T00:04:30Z")  # first sample after the restart
        self.assertIsNone(rec["catch_up_secs"])  # no demotion sample: length unknown, not zero
        self.assertEqual(rec["failed_reports"], 42)

    def test_recovery_without_restart_or_seal_series(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["chaos"] = [e for e in manifest["chaos"] if e["action"] != "systemctl start"]
        metrics = copy.deepcopy(self.metrics)
        del metrics["prometheus"]["series"]["tn_batch_builder_seal_failures_total"]
        caveats = []
        rec = kpis.recovery(metrics, manifest, "val-3", caveats)
        self.assertIsNone(rec["restarted_utc"])
        self.assertEqual(rec["catch_up_secs"], 120)  # measured from the kill instead
        self.assertIsNone(rec["failed_reports"])
        self.assertTrue(any("failed_reports unavailable" in c for c in caveats))

    # A small tn_node_mode series of its own after the restart at T0+260: (offset from T0, cvv_inactive).
    def _mode(self, samples):
        metrics = copy.deepcopy(self.metrics)
        metrics["prometheus"]["series"]["tn_node_mode"]["by_node"]["val-3"]["max"] = \
            [[T0 + dt, float(v)] for dt, v in samples]
        caveats = []
        return kpis.recovery(metrics, self.manifest, "val-3", caveats), caveats

    def test_transient_promotion_then_inactive_is_not_a_rejoin(self):
        rec, caveats = self._mode([(270, 0), (285, 1), (300, 1), (315, 0), (330, 1), (345, 1)])
        self.assertEqual(rec["demoted_utc"], "2026-01-01T00:04:45Z")
        self.assertIsNone(rec["rejoined_utc"])  # null, so a backfill can fill it
        self.assertIsNone(rec["catch_up_secs"])
        self.assertIn("recovery: the metrics window ended while val-3 was still rejoining (inactive at its last "
                      "sample, 2026-01-01T00:05:45Z); rejoined and catch-up unavailable", caveats)
        self.assertIn("recovery: the 15-s samples show val-3 promoted 1 time(s) (2026-01-01T00:05:15Z to "
                      "2026-01-01T00:05:15Z) and inactive again at a later sample each time; a rejoin counts "
                      "only once the node stays active to the end of the metrics window", caveats)

    def test_promotion_sustained_to_the_end_is_the_rejoin(self):
        # Two transient promotions (T0+315, T0+360), then active from T0+405 to the last sample.
        rec, caveats = self._mode([(270, 0), (285, 1), (300, 1), (315, 0), (330, 1), (345, 1), (360, 0),
                                   (375, 1), (390, 1), (405, 0), (420, 0), (435, 0)])
        self.assertEqual(rec["demoted_utc"], "2026-01-01T00:04:45Z")
        self.assertEqual(rec["rejoined_utc"], "2026-01-01T00:06:45Z")
        self.assertEqual(rec["catch_up_secs"], 120)
        self.assertIn("recovery: the 15-s samples show val-3 promoted 2 time(s) (2026-01-01T00:05:15Z to "
                      "2026-01-01T00:06:00Z) and inactive again at a later sample each time; a rejoin counts "
                      "only once the node stays active to the end of the metrics window", caveats)
        self.assertFalse(any("still rejoining" in c for c in caveats))

    def test_promotion_at_the_last_sample_is_the_rejoin(self):
        rec, caveats = self._mode([(270, 0), (285, 1), (300, 1), (315, 0)])
        self.assertEqual((rec["rejoined_utc"], rec["catch_up_secs"]), ("2026-01-01T00:05:15Z", 30))
        self.assertFalse(any("promoted" in c or "still rejoining" in c for c in caveats))

    def test_no_mode_sample_after_the_restart(self):
        rec, caveats = self._mode([(45, 1), (60, 0)])
        self.assertEqual((rec["demoted_utc"], rec["rejoined_utc"], rec["catch_up_secs"]), (None, None, None))
        self.assertIn("recovery: no tn_node_mode sample for val-3 after the restart; "
                      "demoted / rejoined / catch-up unavailable", caveats)

    def test_failed_reports_is_the_counter_delta(self):
        metrics = copy.deepcopy(self.metrics)
        seal = metrics["prometheus"]["series"]["tn_batch_builder_seal_failures_total"]
        del seal["by_node"]  # the rate series plays no part
        seal["count"] = {"val-1": 3, "val-3": 2}
        caveats = []
        self.assertEqual(kpis.recovery(metrics, self.manifest, "val-3", caveats)["failed_reports"], 2)
        self.assertIn("recovery: failed_reports is the rise of the batch-seal failure counter on val-3 over the "
                      "whole metrics window (metrics.prometheus.series.tn_batch_builder_seal_failures_total.count), "
                      "outage or not", caveats)
        seal["count"] = {"val-1": 3}  # a series on other nodes only: val-3 has no count
        caveats = []
        self.assertIsNone(kpis.recovery(metrics, self.manifest, "val-3", caveats)["failed_reports"])
        self.assertIn("recovery: no tn_batch_builder_seal_failures_total count for val-3; failed_reports "
                      "unavailable", caveats)
        del seal["count"]  # a collector without counts
        self.assertIsNone(kpis.recovery(metrics, self.manifest, "val-3", [])["failed_reports"])


if __name__ == "__main__":
    unittest.main()
