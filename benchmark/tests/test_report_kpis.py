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
  time to land corrected ts p50 + 0.5 s (the whole-second floor bias)       1.75
  (the synthetic combined result has no latency.seen_ms and the run no light blast, so the
  time-to-seen and floor KPIs are absent there; the light-load tests at the end build their own)
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
import contextlib
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

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
    "time_to_land_corrected_p50_s": ("value", 1.75),
    "commit_latency_p95_s": ("range", [2.0, 2.5]),
    "execution_time_per_output_s": ("range", [0.11, 0.22]),
    "disk_write_p95_mibps_busiest": ("value", 24.0),
    "disk_write_iops_p95_busiest": ("value", 1200),
    "cpu_p95_pct_busiest": ("value", 60.0),
    "rss_p95_gib_busiest": ("value", 3.0),
    "psi_io_max_pct": ("range", [7.3, 12.5]),
}

SEEN_IDS = ["time_to_seen_p50_s", "time_to_seen_p95_s"]
FLOOR_IDS = ["floor_time_to_land_p50_s", "floor_time_to_seen_p50_s"]
NEW_IDS = ["time_to_land_corrected_p50_s"] + SEEN_IDS + FLOOR_IDS
# The KPIs the synthetic run yields: every id but the time-to-seen and floor ones.
SYNTH_IDS = [i for i in kpis.DECIMALS if i not in SEEN_IDS + FLOOR_IDS]

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

    def compute(self, combined=None, metrics=None, manifest=None, windows=None, targets=("val-3",), floor=None):
        return kpis.compute(self.combined if combined is None else combined,
                            self.metrics if metrics is None else metrics,
                            self.sampler,
                            self.manifest if manifest is None else manifest,
                            WINDOWS if windows is None else windows,
                            list(targets), floor)

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
        self.assertEqual(len(kpis.DECIMALS), 18)
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
    def test_all_fourteen_kpis_hand_computed(self):
        out = self.compute()
        self.assertEqual([k["id"] for k in out["kpis"]], SYNTH_IDS)
        self.assertEqual(len(SYNTH_IDS), 14)
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
        self.assertEqual(ids, SYNTH_IDS[2:])
        self.assertEqual(kpis.headline_id(out["kpis"]), "landed_total")
        self.assertTrue(any(c.startswith("all-generators window undefined") for c in out["caveats"]))

    def test_all_generators_window_shorter_than_60s_has_no_best_60s(self):
        short = {"merged": WINDOWS["merged"], "all_generators": {"start_unix": T0 + 100, "end_unix": T0 + 145, "secs": 45}}
        out = self.compute(windows=short)
        ids = [k["id"] for k in out["kpis"]]
        self.assertNotIn("best_60s_chain_tps_all_generators", ids)
        self.assertEqual(ids, [i for i in SYNTH_IDS if i != "best_60s_chain_tps_all_generators"])
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
                         ["landed_total", "time_to_land_p50_s", "time_to_land_p95_s",
                          "time_to_land_corrected_p50_s"])
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


# --------------------------------------------------------------------------- light-load arm
#
# A light-load run (benchmark-blast.sh BENCH_LIGHT_LOAD=1) built in a temp results dir:
# manifest blasts[] = index 0 light8 (8 x 16), 1 light16, 2 light600x4, 3 the load (chaos 1,
# manifest.blast.run_index 3). blast-0-<UTC>/ holds two light8 generators and a manifest copy:
#
#   gen-a  mixed [T0+100, T0+460)  landed_own 100  ts p50 900 / seen p50 1900 (its own quantiles)
#          native_transfer hist_ts [0,10,40,0,0,0], erc20_transfer hist_ts [0,0,0,50,0,0]
#          hist_seen native [0,0,0,70,30,0]; a closes_epoch block at T0+200 (and one at T0+1000,
#          outside every window); U-T column order
#   gen-b  mixed [T0+105, T0+465)  landed_own 100  ts p50 1100 / seen p50 2000
#          native_transfer hist_ts [0,0,20,60,20,0], hist_seen [0,0,0,50,50,0]; a closes_epoch
#          block at T0+430; its block columns in another order (read by name)
#   bounds [250, 500, 1000, 2000, 4000]
#
# Pooled (aggregate.py merge_latency: two live parts -> the summed histogram, interpolated):
#   ts   [0,10,60,110,20,0], n 200, rank 100: 70 below the 1000-2000 bucket of 110
#        -> 1000 + 1000 * 30/110 = 1272.727 ms -> floor_time_to_land_p50_s 1.27
#   seen [0,0,0,120,80,0], rank 100 -> 1000 + 1000 * 100/120 = 1833.333 ms -> 1.83
# light8 window = merged mixed [T0+100, T0+465) (365 s, from its blasters); boundaries inside it
# T0+200 and T0+430; minus +/- 30 s: [T0+100,T0+170) [T0+230,T0+400) [T0+460,T0+465) = 245 s.
# blast-1 (light16) has blasters without a mixed phase but a manifest copy with phases
# (mixed [T0+600, T0+960)); blast-2 (light600x4) archived nothing: blasts[] started T0+1000 +
# warm-up 60 = T0+1060 to ended T0+1600 - cool-down 60 = T0+1540.

BOUNDS = [250, 500, 1000, 2000, 4000]
LIGHT_RUN = "r20260101-0000"
BLOCK_COLUMNS = ["number", "timestamp", "epoch", "round", "closes_epoch", "gas_used", "gas_limit", "tx_count",
                 "own_tx", "own_reverted", "own_gas_used", "base_fee_wei", "batch_index", "batch_digest_prefix",
                 "seen_ms", "own_submit_min_ms", "own_submit_p50_ms", "own_submit_max_ms", "own_accept_p50_ms"]


def _hist(counts):
    return {"bounds_ms": list(BOUNDS), "counts": list(counts)}


def _row(columns, **cells):
    return [cells.get(c, 0) for c in columns]


def light_doc(label, mixed, landed, ts, seen, types, blocks_columns, closes):
    return {
        "schema": "tn-blast/v2",
        "run": {"label": label, "phases": [{"name": "mixed", "start_unix": mixed[0], "end_unix": mixed[1]}]},
        "totals": {"landed_own": landed},
        "latency": {"ts_ms": ts, "seen_ms": seen},
        "types": types,
        "blocks": {"columns": list(blocks_columns),
                   "rows": [_row(blocks_columns, number=n, timestamp=t, closes_epoch=c, batch_digest_prefix="00")
                            for n, (t, c) in enumerate([(mixed[0] + 1, 0)] + [(b, 1) for b in closes], 1)]},
    }


GEN_A = light_doc("gen-a", (T0 + 100, T0 + 460), 100,
                  {"p50": 900, "p95": 1800, "p99": 1950, "mean": 950.0, "saturated": False},
                  {"p50": 1900, "p95": 3200, "p99": 3900, "mean": 2000.0, "saturated": False},
                  {"native_transfer": {"landed_own": 50, "latency_hist_ts": _hist([0, 10, 40, 0, 0, 0]),
                                       "latency_hist_seen": _hist([0, 0, 0, 70, 30, 0])},
                   "erc20_transfer": {"landed_own": 50, "latency_hist_ts": _hist([0, 0, 0, 50, 0, 0])}},
                  BLOCK_COLUMNS, [T0 + 200, T0 + 1000])
GEN_B = light_doc("gen-b", (T0 + 105, T0 + 465), 100,
                  {"p50": 1100, "p95": 2600, "p99": 3000, "mean": 1150.0, "saturated": False},
                  {"p50": 2000, "p95": 3500, "p99": 3900, "mean": 2100.0, "saturated": False},
                  {"native_transfer": {"landed_own": 100, "latency_hist_ts": _hist([0, 0, 20, 60, 20, 0]),
                                       "latency_hist_seen": _hist([0, 0, 0, 50, 50, 0])}},
                  ["closes_epoch", "number", "seen_ms", "timestamp"], [T0 + 430])

LIGHT_MANIFEST = {
    "schema": "tn-bench-manifest/v1", "run_id": LIGHT_RUN,
    "blast": {"run_index": 3, "chaos": 1},
    "instances": [{"name": "val-1", "role": "validator"}, {"name": "val-2", "role": "validator"}],
    "blasts": [
        {"index": 0, "senders": 8, "window": 16, "chaos": 0, "started": "2026-01-01T00:00:00Z",
         "ended": "2026-01-01T00:09:00Z", "rc": 0},
        {"index": 1, "senders": 16, "window": 16, "chaos": 0, "started": "2026-01-01T00:09:00Z",
         "ended": "2026-01-01T00:16:40Z", "rc": 0},
        {"index": 2, "senders": 600, "window": 4, "chaos": 0, "started": "2026-01-01T00:16:40Z",
         "ended": "2026-01-01T00:26:40Z", "rc": 0},
        {"index": 3, "senders": 600, "window": 16, "chaos": 1, "started": "2026-01-01T00:26:40Z",
         "ended": "2026-01-01T01:10:00Z", "rc": 0},
    ],
}


def _write(path, doc):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w") as fh:
        json.dump(doc, fh)


def build_light_run(root):
    """The light-load run above under root/<LIGHT_RUN>; returns its path."""
    r = os.path.join(root, LIGHT_RUN)
    _write(os.path.join(r, "manifest.json"), LIGHT_MANIFEST)
    _write(os.path.join(r, "metrics.json"), {"schema": "tn-bench-gcp-metrics/v1"})
    load = copy.deepcopy(GEN_A)
    load["run"]["label"] = "load-a"
    _write(os.path.join(r, "blasters", "load-a.json"), load)
    with gzip.open(os.path.join(r, "blasters", "landings-load-a.ndjson.gz"), "wt") as fh:
        fh.write('{"phase": "mixed"}\n')
    b0 = os.path.join(r, "blast-0-20260101T000900Z")
    _write(os.path.join(b0, "manifest.json"), {"blast": {"run_index": 0}, "phases": [
        {"name": "warmup", "start": "2026-01-01T00:00:40Z", "end": "2026-01-01T00:01:40Z"},
        {"name": "mixed", "start": "2026-01-01T00:01:40Z", "end": "2026-01-01T00:07:40Z"}]})
    _write(os.path.join(b0, "blasters", "gen-a.json"), GEN_A)
    _write(os.path.join(b0, "blasters", "gen-b.json"), GEN_B)
    with gzip.open(os.path.join(b0, "blasters", "landings-gen-a.ndjson.gz"), "wt") as fh:
        fh.write('{"phase": "mixed"}\n')
    os.makedirs(os.path.join(r, "blast-0-20260101T001000Z"))  # a later archive of the index that holds nothing
    b1 = os.path.join(r, "blast-1-20260101T001640Z")
    _write(os.path.join(b1, "manifest.json"), {"phases": [
        {"name": "mixed", "start": "2026-01-01T00:10:00Z", "end": "2026-01-01T00:16:00Z"}]})
    _write(os.path.join(b1, "blasters", "gen-a.json"), {"schema": "tn-blast/v2", "run": {"label": "gen-a"}})
    _write(os.path.join(b1, "metrics.json"), {"schema": "tn-bench-gcp-metrics/v1"})
    return r


class LightRunMixin(object):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="kpis-light-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = build_light_run(self.tmp)
        self.light_manifest = load_json(os.path.join(self.run_dir, "manifest.json"))


class LightWindowTests(LightRunMixin, unittest.TestCase):
    def test_light_blasts_from_manifest(self):
        got = windows_mod.light_blasts(self.run_dir, self.light_manifest)
        self.assertEqual([(b["name"], b["index"], b["senders"], b["window"]) for b in got],
                         [("light8", 0, 8, 16), ("light16", 1, 16, 16), ("light600x4", 2, 600, 4)])
        # blast-0 has two archives: the one with blasters wins over the newer empty one; blast-2 archived nothing.
        self.assertEqual([os.path.basename(b["dir"]) if b["dir"] else None for b in got],
                         ["blast-0-20260101T000900Z", "blast-1-20260101T001640Z", None])
        # A load run without chaos is still the load: the blast at the top of the results dir.
        calm = copy.deepcopy(self.light_manifest)
        calm["blasts"][3]["chaos"] = 0
        self.assertEqual([b["index"] for b in windows_mod.light_blasts(self.run_dir, calm)], [0, 1, 2])

    def test_names(self):
        self.assertEqual(windows_mod.light_name(8, 16), "light8")
        self.assertEqual(windows_mod.light_name(8, None), "light8")
        self.assertEqual(windows_mod.light_name(600, 4), "light600x4")

    def test_light_windows_sources_and_boundaries(self):
        got = {w["name"]: w for w in windows_mod.light_windows(self.run_dir, self.light_manifest)}
        w8 = got["light8"]
        self.assertEqual((w8["start_unix"], w8["end_unix"], w8["secs"], w8["source"]),
                         (T0 + 100, T0 + 465, 365, "blasters"))
        self.assertEqual(w8["boundaries"], [T0 + 200, T0 + 430])
        self.assertNotIn("intervals", w8)
        w16 = got["light16"]
        self.assertEqual((w16["start_unix"], w16["end_unix"], w16["source"]), (T0 + 600, T0 + 960, "manifest.phases"))
        w600 = got["light600x4"]
        self.assertEqual((w600["start_unix"], w600["end_unix"], w600["source"]),
                         (T0 + 1060, T0 + 1540, "blasts[] (approximate)"))

    def test_exclude_boundaries(self):
        w8 = windows_mod.light_windows(self.run_dir, self.light_manifest, exclude_secs=30)[0]
        self.assertEqual([(i["start_unix"] - T0, i["end_unix"] - T0) for i in w8["intervals"]],
                         [(100, 170), (230, 400), (460, 465)])
        self.assertEqual((w8["kept_secs"], w8["exclude_secs"]), (245, 30))
        # A boundary just outside the window still trims its edge.
        self.assertEqual(windows_mod.subtract(T0, T0 + 100, [T0 - 10], 30),
                         [{"start_unix": T0 + 20, "end_unix": T0 + 100, "secs": 80}])
        self.assertEqual(windows_mod.subtract(T0, T0 + 100, [], 30),
                         [{"start_unix": T0, "end_unix": T0 + 100, "secs": 100}])

    def test_cli_light_only_with_run_dir(self):
        args = [str(RUN / "blasters"), str(RUN / "combined.json")]
        plain = io.StringIO()
        with contextlib.redirect_stdout(plain):
            rc = windows_mod.main(args)
        self.assertEqual(rc, 0)
        built = windows_mod.build(windows_mod.load_blasters(str(RUN / "blasters")), load_json(RUN / "combined.json"))
        self.assertEqual(plain.getvalue(), json.dumps(built, indent=2) + "\n")  # unchanged without --run-dir
        # With --run-dir the light windows lose +/- 30 s around each epoch boundary by default.
        for extra in ([], ["--exclude-boundaries"], ["--exclude-boundaries", "30"]):
            with self.subTest(extra=extra):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = windows_mod.main(args + ["--run-dir", self.run_dir] + extra)
                self.assertEqual(rc, 0)
                light = json.loads(out.getvalue())["light"]
                self.assertEqual([w["name"] for w in light], ["light8", "light16", "light600x4"])
                self.assertEqual((light[0].get("kept_secs"), light[0].get("exclude_secs")), (245, 30))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = windows_mod.main(args + ["--run-dir", self.run_dir, "--keep-boundaries"])
        w8 = json.loads(out.getvalue())["light"][0]
        self.assertEqual((w8["secs"], w8["boundaries"]), (365, [T0 + 200, T0 + 430]))
        self.assertNotIn("intervals", w8)
        self.assertNotIn("exclude_secs", w8)
        for bad in (["--exclude-boundaries", "30"], ["--keep-boundaries"],
                    ["--run-dir", self.run_dir, "--keep-boundaries", "--exclude-boundaries"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                windows_mod.main(args + bad)

    def test_floor_blast(self):
        blast, caveats = windows_mod.floor_blast(self.run_dir, self.light_manifest)
        self.assertEqual((blast["name"], blast["index"], caveats), ("light8", 0, []))
        self.assertEqual(windows_mod.floor_blast(self.run_dir, {"blast": {"run_index": 0}}), (None, []))
        failed = copy.deepcopy(self.light_manifest)
        failed["blasts"][0]["rc"] = 3
        blast, caveats = windows_mod.floor_blast(self.run_dir, failed)
        self.assertIsNone(blast)
        self.assertEqual(caveats, ["light8 blast (index 0) ended rc=3; floor KPIs not computed from it"])
        lost = copy.deepcopy(self.light_manifest)
        lost["blasts"][0]["index"] = 7
        self.assertIn("has no archived blast-7-*/blasters/*.json", windows_mod.floor_blast(self.run_dir, lost)[1][0])


class FloorKpiTests(LightRunMixin, Fixture):
    def floor(self):
        blast, _ = windows_mod.floor_blast(self.run_dir, self.light_manifest)
        return kpis.floor_input(blast)

    def test_pooled_matches_hand_computation(self):
        docs = [GEN_A, GEN_B]
        lat = kpis.pooled_latency(docs)
        self.assertEqual((lat["ts_ms"]["p50"], lat["seen_ms"]["p50"]), (1272.727, 1833.333))
        self.assertEqual(lat["ts_ms"]["mean"], 1050.0)  # weighted by landed_own
        # One live document passes its own quantiles through (aggregate.py merge_latency).
        self.assertEqual(kpis.pooled_latency([GEN_A])["ts_ms"], GEN_A["latency"]["ts_ms"])

    def test_floor_kpis_hand_computed(self):
        out = self.compute(floor=self.floor())
        got = self.by_id(out)
        self.assertEqual((got["floor_time_to_land_p50_s"]["value"], got["floor_time_to_seen_p50_s"]["value"]),
                         (1.27, 1.83))
        for kid in FLOOR_IDS:
            k = got[kid]
            self.assertEqual((k["unit"], k["window"], k["provenance"]), ("s", "light8", "computed"))
            self.assertEqual(k["source"].split(" ")[0], "blast-0-20260101T000900Z/blasters")
        ids = [k["id"] for k in out["kpis"]]
        self.assertEqual(ids, [i for i in kpis.DECIMALS if i not in SEEN_IDS])
        self.assertIn("2 epoch boundaries fell inside the light8 mixed window (2026-01-01T00:03:20Z, "
                      "2026-01-01T00:07:10Z); the floor KPIs pool its whole mixed phase (windows.py "
                      "--exclude-boundaries gives the boundary-free intervals)", out["caveats"])
        self.assertEqual(out["floor_by_generator"], [
            {"generator": "gen-a", "samples": 100, "time_to_land_p50_s": 0.9, "time_to_land_p95_s": 1.8,
             "time_to_seen_p50_s": 1.9, "time_to_seen_p95_s": 3.2},
            {"generator": "gen-b", "samples": 100, "time_to_land_p50_s": 1.1, "time_to_land_p95_s": 2.6,
             "time_to_seen_p50_s": 2.0, "time_to_seen_p95_s": 3.5}])

    def test_without_light_blast_nothing_changes(self):
        plain = self.compute()
        self.assertNotIn("floor_by_generator", plain)
        self.assertFalse(set(FLOOR_IDS) & {k["id"] for k in plain["kpis"]})
        self.assertFalse(any("light8" in c for c in plain["caveats"]))

    def test_mismatched_histograms_are_a_caveat(self):
        floor = self.floor()
        floor["docs"][1] = copy.deepcopy(floor["docs"][1])
        floor["docs"][1]["types"]["native_transfer"]["latency_hist_ts"]["bounds_ms"] = [1, 2, 3, 4, 5]
        out = self.compute(floor=floor)
        self.assertFalse(set(FLOOR_IDS) & {k["id"] for k in out["kpis"]})
        self.assertTrue(any(c.startswith("light8 blast: latency histogram bounds differ") for c in out["caveats"]))

    def test_time_to_seen_and_corrected(self):
        combined = copy.deepcopy(self.combined)
        combined["latency"]["seen_ms"] = {"p50": 2345.0, "p95": 6000.0, "saturated": False}
        got = self.by_id(self.compute(combined=combined))
        self.assertEqual((got["time_to_seen_p50_s"]["value"], got["time_to_seen_p95_s"]["value"]), (2.35, 6.0))
        self.assertEqual(got["time_to_seen_p50_s"]["source"], "combined.latency.seen_ms.p50")
        self.assertEqual(got["time_to_land_corrected_p50_s"]["value"], 1.75)
        self.assertEqual(kpis.LAND_FLOOR_BIAS_S, 0.5)
        missing = self.compute()
        self.assertIn("combined.latency.seen_ms.p50 missing: time_to_seen_p50_s not computed", missing["caveats"])
        combined["latency"]["seen_ms"]["saturated"] = True
        self.assertTrue(any(c.startswith("combined.latency.seen_ms is saturated")
                            for c in self.compute(combined=combined)["caveats"]))


class KpisCliTests(LightRunMixin, unittest.TestCase):
    def run_main(self, *extra):
        combined = os.path.join(self.tmp, "combined.json")
        _write(combined, {"latency": {"ts_ms": {"p50": 1000.0, "p95": 2000.0},
                                      "seen_ms": {"p50": 3000.0, "p95": 4000.0}}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = kpis.main(["--run-dir", self.run_dir, "--combined", combined] + list(extra))
        self.assertEqual(rc, 0)
        return json.loads(out.getvalue())

    def test_default_reads_the_top_and_finds_light8(self):
        doc = self.run_main()
        self.assertEqual((doc["blast_dir"], doc["floor_blast_dir"]), (".", "blast-0-20260101T000900Z"))
        got = {k["id"]: k.get("value") for k in doc["kpis"]}
        self.assertEqual((got["time_to_seen_p50_s"], got["time_to_land_corrected_p50_s"]), (3.0, 1.5))
        self.assertEqual((got["floor_time_to_land_p50_s"], got["floor_time_to_seen_p50_s"]), (1.27, 1.83))
        self.assertEqual([r["generator"] for r in doc["floor_by_generator"]], ["gen-a", "gen-b"])

    def test_blast_dir_and_floor_blast_dir(self):
        b1 = os.path.join(self.run_dir, "blast-1-20260101T001640Z")
        doc = self.run_main("--blast-dir", b1, "--floor-blast-dir", os.path.join(self.run_dir, "blast-0-20260101T000900Z"))
        self.assertEqual(doc["blast_dir"], "blast-1-20260101T001640Z")
        self.assertEqual(doc["floor_blast_dir"], "blast-0-20260101T000900Z")
        self.assertIn("floor_time_to_land_p50_s", {k["id"] for k in doc["kpis"]})
        # A light16 dir named as the floor keeps its own name as the KPI window.
        doc = self.run_main("--floor-blast-dir", b1)
        self.assertEqual(doc["floor_blast_dir"], "blast-1-20260101T001640Z")
        self.assertTrue(any(c.startswith("light16 blast: latency.ts_ms.p50 missing") for c in doc["caveats"]))

    def test_floor_blast_dir_takes_the_last_rc0_entry_of_its_index(self):
        b1 = os.path.join(self.run_dir, "blast-1-20260101T001640Z")
        m = copy.deepcopy(self.light_manifest)
        m["blasts"].insert(1, dict(m["blasts"][1], senders=8, rc=1))     # index 1 failed first, then its retry
        got = kpis.blast_from_dir(m, b1)
        self.assertEqual((got["name"], got["index"], got["senders"], got["rc"]), ("light16", 1, 16, 0))
        bare = kpis.blast_from_dir({"blasts": []}, b1)                   # no entry of the index: the defaults
        self.assertEqual((bare["name"], bare["index"], bare["senders"], bare["rc"]), ("light8", 1, 8, None))
        self.assertEqual(kpis.floor_from_dir(m, b1), (got, []))
        m["blasts"][2]["rc"] = 2                                          # every entry of the index failed
        self.assertIsNone(kpis.blast_from_dir(m, b1))
        _write(os.path.join(self.run_dir, "manifest.json"), m)
        doc = self.run_main("--floor-blast-dir", b1)
        self.assertIsNone(doc["floor_blast_dir"])
        self.assertIn("floor blast dir blast-1-20260101T001640Z (index 1) ended rc=1,2; floor KPIs not computed from it",
                      doc["caveats"])
        self.assertFalse({"floor_time_to_land_p50_s", "floor_time_to_seen_p50_s"} & {k["id"] for k in doc["kpis"]})

    def test_table(self):
        combined = os.path.join(self.tmp, "c.json")
        _write(combined, {"latency": {"ts_ms": {"p50": 1000.0}}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kpis.main(["--run-dir", self.run_dir, "--combined", combined, "--table"])
        text = out.getvalue()
        self.assertIn("| floor_time_to_seen_p50_s | 1.83 | s | light8 |", text)
        self.assertIn("| gen-b | 100 | 1.1 | 2.6 | 2.0 | 3.5 |", text)


# --------------------------------------------------------------------------- make_bundle.py

mb = _load("report_make_bundle_for_kpis", BENCH / "report" / "make_bundle.py")


class BundleFloorTests(LightRunMixin, unittest.TestCase):
    def setUp(self):
        super(BundleFloorTests, self).setUp()
        self.work = os.path.join(self.tmp, "work")
        for name, value in (("RESULTS_ROOT", self.tmp), ("WORK_ROOT", self.work)):
            p = mock.patch.object(mb, name, value)
            p.start()
            self.addCleanup(p.stop)

    def prepare(self, floor_dir=None):
        with contextlib.redirect_stdout(io.StringIO()):
            scratch = mb.prepare_scratch(LIGHT_RUN, None, True)
            blast, caveats = mb.prepare_floor(scratch, LIGHT_RUN, floor_dir)
        return scratch, blast, caveats

    def test_floor_copied_and_hashed_in_the_marker(self):
        scratch, blast, caveats = self.prepare()
        self.assertEqual((blast["name"], blast["index"], caveats), ("light8", 0, []))
        self.assertEqual(sorted(os.listdir(os.path.join(scratch, mb.FLOOR_SCRATCH, "blasters"))),
                         ["gen-a.json", "gen-b.json"])
        marker = mb.read_marker(scratch)
        self.assertEqual(marker["floor"], {"name": "light8", "index": 0,
                                           "source": LIGHT_RUN + "/blast-0-20260101T000900Z"})
        paths = [e["path"] for e in marker["inputs"]]
        self.assertEqual(paths, [LIGHT_RUN + "/manifest.json", LIGHT_RUN + "/metrics.json",
                                 LIGHT_RUN + "/blasters/load-a.json",
                                 LIGHT_RUN + "/blast-0-20260101T000900Z/manifest.json",
                                 LIGHT_RUN + "/blast-0-20260101T000900Z/blasters/gen-a.json",
                                 LIGHT_RUN + "/blast-0-20260101T000900Z/blasters/gen-b.json"])
        e = marker["inputs"][3]
        self.assertEqual((e["bytes"], e["sha256"]),
                         (os.path.getsize(os.path.join(self.tmp, e["path"])), mb._sha256(os.path.join(self.tmp, e["path"]))))
        self.assertEqual(marker["archives"], [LIGHT_RUN + "/blast-0-20260101T000900Z",
                                              LIGHT_RUN + "/blast-0-20260101T001000Z",
                                              LIGHT_RUN + "/blast-1-20260101T001640Z"])
        self.assertEqual([e["path"] for e in marker["landings"]],
                         [LIGHT_RUN + "/blast-0-20260101T000900Z/blasters/landings-gen-a.ndjson.gz",
                          LIGHT_RUN + "/blasters/landings-load-a.ndjson.gz"])
        # Never copied: the landings exports stay in the results dir.
        self.assertFalse([f for _, _, fs in os.walk(scratch) for f in fs if f.endswith(".gz")])

    def test_kpis_step_with_the_floor(self):
        scratch, blast, caveats = self.prepare()
        floor = kpis.floor_input(blast, os.path.join(scratch, mb.FLOOR_SCRATCH))
        combined = load_json(RUN / "combined.json")
        with contextlib.redirect_stdout(io.StringIO()):
            kp, head, rec, cav = mb.kpis_step(self.tmp, combined, {}, self.light_manifest, WINDOWS, {}, floor, ["first"])
        got = {k["id"]: k for k in kp}
        self.assertEqual((got["floor_time_to_land_p50_s"]["value"], got["floor_time_to_seen_p50_s"]["value"]),
                         (1.27, 1.83))
        self.assertEqual(cav[0], "first")

    def test_floor_blast_dir_and_no_light_arm(self):
        _, blast, _ = self.prepare("blast-1-20260101T001640Z")  # relative to results/<run>/
        self.assertEqual((blast["name"], blast["index"]), ("light16", 1))
        with self.assertRaises(mb.BundleError):
            self.prepare("blast-9-nowhere")
        _write(os.path.join(self.run_dir, "manifest.json"), {"blast": {"run_index": 0}})
        scratch, blast, caveats = self.prepare()
        self.assertEqual((blast, caveats), (None, []))
        self.assertFalse(os.path.exists(os.path.join(scratch, mb.FLOOR_SCRATCH)))
        self.assertIsNone(mb.read_marker(scratch)["floor"])

    def test_parse_args(self):
        a = mb.parse_args(["--run", LIGHT_RUN, "--floor-blast-dir", "blast-0-x"])
        self.assertEqual(a.floor_blast_dir, "blast-0-x")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mb.parse_args(["--run", LIGHT_RUN, "--no-results", "--archived-report", "r.html", "--backfill", "b.json",
                           "--floor-blast-dir", "blast-0-x"])


# --------------------------------------------------------------------------- bench 4, byte for byte

BENCH4 = "r20261105-0803"
BENCH4_DIR = BENCH / "results" / BENCH4
BENCH4_FIX = TESTS / "fixtures" / "report" / "bench4-r20261105-0803"
TXGEN_BENCH = Path(os.environ.get("BENCH_TXGEN_REPO") or (BENCH.parent.parent / "tn-transaction-generator")) / "bench"


@unittest.skipUnless((BENCH4_DIR / "manifest.json").is_file() and (TXGEN_BENCH / "aggregate.py").is_file(),
                     "needs benchmark/results/%s and the generator's bench/aggregate.py" % BENCH4)
class Bench4IdentityTests(unittest.TestCase):
    """make_bundle steps 1, 3, 4, 6 and 7 on the bench-4 results (about 20 s): the windows and every
    pre-bench-5 KPI, caveat and recovery field equal the output captured before the bench-5 change
    (fixtures/report/bench4-r20261105-0803, itself equal to the A1 analysis' bundle_kpis.json and
    bundle_windows.json); the only difference is the three new KPI ids the run has data for."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix="kpis-bench4-"))
        with mock.patch.object(mb, "WORK_ROOT", cls.tmp), contextlib.redirect_stdout(io.StringIO()):
            scratch = mb.prepare_scratch(BENCH4, None, True)
            blast, floor_caveats = mb.prepare_floor(scratch, BENCH4)
            mb.run_tools(scratch, str(TXGEN_BENCH))
            scrubbed = mb.scrub_scratch(scratch)
            ld = lambda n: mb._load_input(os.path.join(scrubbed, n))  # noqa: E731
            manifest, metrics, combined = ld("manifest.json"), ld("metrics.json"), ld("combined.json")
            built, tps5, series_doc = mb.windows_step(scratch, combined)
            cls.kpis = mb.kpis_step(scrubbed, combined, metrics, manifest, built, {}, None, floor_caveats)
        cls.windows = {"built": built, "run_json_windows": mb.win.to_run_json(built), "tps_5min": tps5,
                       "series_meta": {k: v for k, v in series_doc.items() if k != "rows"},
                       "series_rows_n": len(series_doc["rows"])}
        cls.blast, cls.marker = blast, mb.read_marker(scratch)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_windows_byte_identical(self):
        with open(str(BENCH4_FIX / "bundle_windows.json")) as fh:
            self.assertEqual(json.dumps(self.windows, indent=1), fh.read())

    def test_old_kpis_byte_identical_and_new_ones_added(self):
        kp, head, rec, cav = self.kpis
        old = load_json(BENCH4_FIX / "bundle_kpis.json")
        self.assertEqual(json.dumps([k for k in kp if k["id"] not in NEW_IDS], indent=1),
                         json.dumps(old["kpis"], indent=1))
        self.assertEqual((head, rec, cav), (old["headline"], old["recovery"], old["caveats"]))
        got = {k["id"]: k["value"] for k in kp if k["id"] in NEW_IDS}
        self.assertEqual(got, {"time_to_land_corrected_p50_s": 3.8, "time_to_seen_p50_s": 12.92,
                               "time_to_seen_p95_s": 29.78})

    def test_no_light_arm_no_floor(self):
        self.assertIsNone(self.blast)
        self.assertIsNone(self.marker["floor"])
        self.assertEqual((self.marker["archives"], self.marker["landings"]), ([], []))
        self.assertEqual(len(self.marker["inputs"]), 2 + 10 + 11)  # manifest, metrics, blasters, sampler csv


# ---- bench6 generator fields ----
#
# fixtures/report/generator-fields/additions.json holds the generator's bench-6 additions (series.send_per_second*,
# senders.blocked, nodes[].resends, totals.resends, run.tail_scan, the landings rows' late). Merged into the
# synthetic run's blasters and combined result, they change no window, KPI, recovery figure or caveat.

GEN_FIELDS = load_json(TESTS / "fixtures" / "report" / "generator-fields" / "additions.json")


def with_generator_fields(doc, part):
    """A copy of a blaster (part "blaster") or combined (part "combined") document with the additions merged
    in: objects key by key, and every nodes[] entry (one is made when there is none) gets its resends."""
    add = copy.deepcopy(GEN_FIELDS[part])
    node_resends = add.pop("node_resends")
    out = copy.deepcopy(doc)

    def merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
    merge(out, add)
    out["nodes"] = [dict(n, resends=dict(node_resends)) for n in out.get("nodes") or [{"label": "val-1"}]]
    return out


class GeneratorFieldsTests(Fixture):
    def test_fixture_carries_every_addition(self):
        b = with_generator_fields(load_json(RUN / "blasters" / "load-a.json"), "blaster")
        self.assertEqual(set(b["series"]), {"send_per_second_columns", "send_per_second_t0_unix", "send_per_second"})
        self.assertEqual((sorted(b["senders"]), sorted(b["totals"])), (["blocked"], ["resends", "unlanded_own_at_cooldown_end"]))
        self.assertIn("tail_scan", b["run"])
        self.assertIn("resends", b["nodes"][0])
        self.assertIs(GEN_FIELDS["landings_row"]["late"], True)

    def test_kpis_windows_and_floor_unchanged(self):
        plain = windows_mod.load_blasters(str(RUN / "blasters"))
        extra = [with_generator_fields(d, "blaster") for d in plain]
        combined = with_generator_fields(self.combined, "combined")
        self.assertNotEqual(combined, self.combined)
        built_plain, built_extra = windows_mod.build(plain, self.combined), windows_mod.build(extra, combined)
        self.assertEqual(json.dumps(built_extra), json.dumps(built_plain))
        m = built_plain["merged"]
        self.assertEqual(windows_mod.blocks(combined, built_extra["mixed_windows"], m["start_unix"], m["end_unix"]),
                         windows_mod.blocks(self.combined, built_plain["mixed_windows"], m["start_unix"], m["end_unix"]))
        self.assertEqual(json.dumps(self.compute(combined=combined)), json.dumps(self.compute()))
        # The floor KPIs read light blasters: the same documents with the additions give the same figures.
        floor_docs = [GEN_A, GEN_B]
        floor = {"name": "light8", "index": 0, "senders": 8, "window": 16, "dir": "blast-0-x", "boundaries": []}
        with_plain = self.compute(floor=dict(floor, docs=floor_docs))
        with_extra = self.compute(floor=dict(floor, docs=[with_generator_fields(d, "blaster") for d in floor_docs]))
        self.assertEqual(json.dumps(with_extra), json.dumps(with_plain))
        self.assertIn("floor_time_to_land_p50_s", self.by_id(with_extra))

    def test_bundle_blocks_unchanged(self):
        def blocks(docs, combined):
            caveats = []
            return (mb.workload_block(docs, combined, {}, caveats),
                    mb.generator_block(self.manifest, docs, {}, "abcdef0", None, caveats), caveats)
        plain = windows_mod.load_blasters(str(RUN / "blasters"))
        extra = [with_generator_fields(d, "blaster") for d in plain]
        self.assertEqual(blocks(extra, with_generator_fields(self.combined, "combined")), blocks(plain, self.combined))
