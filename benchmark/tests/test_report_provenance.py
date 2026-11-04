"""report/provenance.py against synthetic node logs (fixtures/provenance/node-log-*.txt).

Each test lays the fixtures out as a run directory in a temp dir: <run>/logs/<bench log name>,
gzip-compressed or plain as bench-lib.sh writes them, plus <run>/manifest.json.

  node-log-validator-container.txt   logfmt, two boots of build 5ca1ab1e (500/250/250 ms, vote
                                     timeout 1500 ms, sub-second fork line), lookalike lines
  node-log-validator-unit-stdout.txt the systemd unit's copy of the same two start lines
  node-log-observer-json.txt         --log.stdout.format json, one boot of the same build
  node-log-baseline.txt              the 29 Sep 2026 baseline shape: another sha, 3000/1000/1000,
                                     no vote timeout, a fork line without subsecond_timestamp
  node-log-adiri.txt                 a "fork schedule (adiri)" line
  node-log-plain-ansi.txt            plain text with ANSI colours, upper-case sha, seconds units
  deploy-output.txt                  a deploy log (not a node log) quoting another sha
"""
import gzip
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

BENCH = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "provenance"
SCRIPT = BENCH / "report" / "provenance.py"
SPEC = importlib.util.spec_from_file_location("provenance", SCRIPT)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)

FULL = "5ca1ab1e0ddba11c0ffee0123456789abcdef012"
BASE = "ba5e11e0" * 5
OTHER = "0badc0de" * 5
SUB_LINE = ("fork schedule: seed_signature, multi_workers, prevrandao, leader_seeded_ordering, "
            "and subsecond_timestamp active from genesis")
GOOD_PARAMS = {"max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250}

# The standard run: name in logs/ -> (fixture, gzip it).
STANDARD = {
    "bench-validator-01-telcoin.log.gz": ("node-log-validator-container.txt", True),
    "bench-validator-01-unit-stdout.log.gz": ("node-log-validator-unit-stdout.txt", True),
    "bench-observer-11-telcoin-pre-kill-20260101T000500Z.log": ("node-log-observer-json.txt", False),
    "deploy-20260101T000000Z.log": ("deploy-output.txt", False),
}


def lines(name):
    return (FIX / name).read_text(encoding="utf-8").splitlines()


def manifest_for(**over):
    m = {"schema": "tn-bench-manifest/v1", "run_id": "rtest-prov", "node_git_sha": FULL,
         "node_fork_schedule": "subsecond-from-genesis", "consensus_parameters": dict(GOOD_PARAMS)}
    m.update(over)
    return {k: v for k, v in m.items() if v is not None}


class RunDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="provenance-test-")
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_run(self, layout, manifest=None, name=None):
        run = self.root / (name or "run-%d" % len(os.listdir(str(self.root))))
        (run / "logs").mkdir(parents=True)
        for log_name, (fixture, gz) in layout.items():
            data = (FIX / fixture).read_bytes()
            if gz:
                with gzip.open(str(run / "logs" / log_name), "wb") as fh:
                    fh.write(data)
            else:
                (run / "logs" / log_name).write_bytes(data)
        if manifest is not None:
            (run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return run

    def cli(self, run, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(run)] + list(args),
                              cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)


class ParseTests(unittest.TestCase):
    def test_parse_startups_logfmt(self):
        got = P.parse_startups(lines("node-log-validator-container.txt"), "bench-validator-01")
        self.assertEqual(got, [
            {"instance": "bench-validator-01", "ts": "2026-01-01T00:00:00.100000000Z", "version": "0.1.0",
             "sha": FULL},
            {"instance": "bench-validator-01", "ts": "2026-01-01T00:10:00.100000000Z", "version": "0.1.0",
             "sha": FULL}])

    def test_parse_startups_json_and_plain_ansi(self):
        got = P.parse_startups(lines("node-log-observer-json.txt"), "obs")
        self.assertEqual([(s["ts"], s["version"], s["sha"]) for s in got],
                         [("2026-01-01T00:00:01.000000Z", "0.1.0", FULL)])
        got = P.parse_startups(lines("node-log-plain-ansi.txt"), "x")
        self.assertEqual([(s["ts"], s["version"], s["sha"]) for s in got],
                         [("2026-01-01T00:20:00.500000Z", "0.1.1", FULL)])   # sha lower-cased

    def test_parse_startups_ignores_lookalikes(self):
        self.assertEqual(P.parse_startups([
            'ts=t message="starting node and launching first epoch"',
            'ts=t message="telcoin-network 0.1.0 starting"',
            'ts=t message="telcoin-network 0.1.0 (abc) started"'], "x"), [])

    def test_parse_params_three_delays_and_vote_timeout(self):
        self.assertEqual(P.parse_params(lines("node-log-validator-container.txt")),
                         dict(GOOD_PARAMS, vote_timeout_ms=1500))

    def test_parse_params_without_vote_timeout(self):
        got = P.parse_params(lines("node-log-baseline.txt"))
        self.assertEqual(got, {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000,
                               "max_batch_delay_ms": 1000})
        self.assertNotIn("vote_timeout_ms", got)

    def test_parse_params_seconds_units_and_last_value_wins(self):
        self.assertEqual(P.parse_params(lines("node-log-plain-ansi.txt")),
                         {"max_header_delay_ms": 500, "vote_timeout_ms": 2000})
        self.assertEqual(P.parse_params(lines("node-log-baseline.txt") + lines("node-log-validator-container.txt")),
                         dict(GOOD_PARAMS, vote_timeout_ms=1500))
        self.assertEqual(P.parse_params(['ts=t message="Sync retry delay set to 5000 ms"']), {})

    def test_parse_fork_schedule_labels(self):
        cases = [("node-log-validator-container.txt", "subsecond-from-genesis"),
                 ("node-log-observer-json.txt", "subsecond-from-genesis"),
                 ("node-log-baseline.txt", "pre-subsecond"),
                 ("node-log-adiri.txt", "adiri-schedule"),
                 # subsecond_timestamp listed after "active from genesis": not from genesis
                 ("node-log-plain-ansi.txt", "pre-subsecond"),
                 ("node-log-validator-unit-stdout.txt", None)]
        for fixture, want in cases:
            with self.subTest(fixture=fixture):
                self.assertEqual(P.parse_fork_schedule(lines(fixture)), want)
        self.assertEqual(P.parse_fork_schedule(lines("node-log-baseline.txt") + lines("node-log-adiri.txt")),
                         "adiri-schedule")
        self.assertEqual(P.parse_fork_schedule(lines("node-log-validator-container.txt")
                                               + lines("node-log-baseline.txt")), "pre-subsecond")
        self.assertIsNone(P.parse_fork_schedule(['message="subsecond_timestamp active from genesis"']))

    def test_instance_of_bench_log_names(self):
        cases = {
            "logs/bench-validator-01-telcoin.log.gz": "bench-validator-01",
            "bench-validator-10-telcoin-20260929T181157Z.log.gz": "bench-validator-10",
            "bench-validator-05-telcoin-pre-kill-20260929T181157Z.log.gz": "bench-validator-05",
            "bench-validator-02-telcoin-pre-step9-20261005T010203Z.log": "bench-validator-02",
            "bench-observer-11-unit-stdout.log.gz": "bench-observer-11",
            "bench-observer-11-unit-stderr-20260929T181157Z.log.gz": "bench-observer-11",
            "bench-validator-01-unit-stdout.rotated-1.log.gz": "bench-validator-01",
            "bench-telcoin-x-telcoin.log.gz": "bench-telcoin-x",
        }
        for name, want in cases.items():
            with self.subTest(name=name):
                self.assertEqual(P.instance_of(name), want)


class ScanTests(RunDirCase):
    def test_scan_run_reads_node_logs_only_and_drops_unit_repeats(self):
        run = self.make_run(STANDARD)
        scan = P.scan_run(str(run))
        self.assertEqual([os.path.basename(f) for f in scan["files"]], [
            "bench-observer-11-telcoin-pre-kill-20260101T000500Z.log",
            "bench-validator-01-telcoin.log.gz", "bench-validator-01-unit-stdout.log.gz"])
        self.assertEqual(scan["instances"], ["bench-observer-11", "bench-validator-01"])
        self.assertEqual([(s["instance"], s["ts"]) for s in scan["starts"]], [
            ("bench-observer-11", "2026-01-01T00:00:01.000000Z"),
            ("bench-validator-01", "2026-01-01T00:00:00.100000000Z"),
            ("bench-validator-01", "2026-01-01T00:10:00.100000000Z")])
        self.assertEqual(scan["shas"], [FULL])   # the deploy log's quoted sha is not a node start
        self.assertEqual(scan["params"], dict(GOOD_PARAMS, vote_timeout_ms=1500))
        self.assertEqual(scan["param_values"], {k: [v] for k, v in dict(GOOD_PARAMS, vote_timeout_ms=1500).items()})
        self.assertEqual(scan["fork_schedule"], "subsecond-from-genesis")
        self.assertEqual(scan["fork_schedules"], ["subsecond-from-genesis"])
        self.assertEqual(scan["fork_schedule_line"], SUB_LINE)
        self.assertEqual(scan["unreadable"], [])

    def test_unit_copy_alone_still_counts_its_starts(self):
        run = self.make_run({"bench-validator-01-unit-stdout.log.gz": ("node-log-validator-unit-stdout.txt", True)})
        scan = P.scan_run(str(run))
        self.assertEqual(len(scan["starts"]), 2)
        self.assertEqual((scan["params"], scan["fork_schedule"]), ({}, None))

    def test_rotated_unit_log_is_a_node_log(self):
        # The teardown rescue saves a unit log the node rotated as <inst>-unit-<stream>.rotated-<N>.log.gz,
        # next to a rescue-rotated-<stamp>.log of its own, which is not a node log.
        run = self.make_run({
            "bench-validator-01-unit-stdout.rotated-1.log.gz": ("node-log-validator-unit-stdout.txt", True),
            "bench-validator-01-unit-stdout.rotated-12.log": ("node-log-validator-unit-stdout.txt", False),
            "rescue-rotated-20260101T000000Z.log": ("deploy-output.txt", False),
            "bench-validator-01-unit-stdout.rotated-x.log.gz": ("node-log-validator-unit-stdout.txt", True),
            "bench-validator-01-telcoin.rotated-1.log.gz": ("node-log-validator-unit-stdout.txt", True),
        })
        self.assertEqual([os.path.basename(f) for f in P.node_log_files(str(run))], [
            "bench-validator-01-unit-stdout.rotated-1.log.gz", "bench-validator-01-unit-stdout.rotated-12.log"])
        scan = P.scan_run(str(run))
        self.assertEqual(scan["instances"], ["bench-validator-01"])
        self.assertEqual(len(scan["starts"]), 2)  # both rotated copies hold the same two starts: counted once

    def test_truncated_gzip_is_reported_unreadable(self):
        run = self.make_run({"bench-validator-01-telcoin.log.gz": ("node-log-validator-container.txt", True)})
        path = run / "logs" / "bench-validator-01-telcoin.log.gz"
        path.write_bytes(path.read_bytes()[:-12])
        scan = P.scan_run(str(run))
        self.assertEqual([u["file"] for u in scan["unreadable"]], [str(path)])


class CheckTests(RunDirCase):
    def scan(self, layout=None):
        return P.scan_run(str(self.make_run(layout or STANDARD)))

    def test_ok_with_full_sha(self):
        r = P.check(self.scan(), manifest_for())
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual((r["expected_sha"], r["shas"], r["fork_schedule"]),
                         (FULL, [FULL], "subsecond-from-genesis"))
        self.assertEqual(set(r), {"starts", "shas", "fork_schedule", "params", "expected_sha", "ok",
                                  "problems", "checked_at"})
        self.assertRegex(r["checked_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_ok_with_short_prefix(self):
        scan = self.scan()
        self.assertTrue(P.check(scan, manifest_for(node_git_sha=FULL[:7]))["ok"])
        self.assertTrue(P.check(scan, manifest_for(node_git_sha=None), expect_sha=FULL[:9].upper())["ok"])
        r = P.check(scan, manifest_for(node_git_sha=FULL[:6]))
        self.assertFalse(r["ok"])
        self.assertIn("not a hex git sha of at least 7 digits", r["problems"][0])

    def test_sha_mismatch_names_sha_and_instance(self):
        layout = dict(STANDARD)
        layout["bench-validator-02-telcoin.log.gz"] = ("node-log-baseline.txt", True)
        r = P.check(self.scan(layout), manifest_for())
        self.assertFalse(r["ok"])
        self.assertIn("1 start(s) ran sha %s, expected %s (bench-validator-02)" % (BASE, FULL), r["problems"])
        r = P.check(self.scan(), manifest_for(), expect_sha=OTHER)   # the argument beats the manifest
        self.assertEqual(r["problems"], ["3 start(s) ran sha %s, expected %s (bench-observer-11, "
                                         "bench-validator-01)" % (FULL, OTHER)])

    def test_fork_mismatch(self):
        r = P.check(self.scan(), manifest_for(node_fork_schedule="adiri-schedule"))
        self.assertEqual(r["problems"], ["logs show fork schedule subsecond-from-genesis, manifest "
                                         "node_fork_schedule is adiri-schedule"])

    def test_params_mismatch(self):
        cp = dict(GOOD_PARAMS, max_header_delay_ms=3000)
        r = P.check(self.scan(), manifest_for(consensus_parameters=cp))
        self.assertEqual(r["problems"], ["logs show max_header_delay_ms=500, manifest "
                                         "consensus_parameters.max_header_delay_ms is 3000"])

    def test_missing_params_and_fork_line_ok(self):
        scan = self.scan({"bench-validator-01-unit-stdout.log.gz": ("node-log-validator-unit-stdout.txt", True)})
        cp = {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000, "max_batch_delay_ms": 1000}
        r = P.check(scan, manifest_for(consensus_parameters=cp, node_fork_schedule="adiri-schedule"))
        self.assertTrue(r["ok"], r["problems"])
        # A parameter the manifest does not record is not compared either.
        self.assertTrue(P.check(self.scan(), manifest_for(consensus_parameters={"max_header_delay_ms": 500}))["ok"])

    def test_no_expected_sha_not_ok(self):
        r = P.check(self.scan(), {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["problems"], ["no expected sha (pass --expect-sha or set manifest node_git_sha)"])
        self.assertIsNone(r["expected_sha"])


def boot_log(ts, max_ms, min_ms=250, batch_ms=250):
    """One logfmt boot of build FULL at <ts> (YYYY-mm-ddTHH:MM:SS) with these delays."""
    return "".join('ts=%s.%03dZ level=INFO target=%s message="%s"\n' % (ts, i, t, m) for i, (t, m) in enumerate([
        ("cli", "telcoin-network 0.1.0 (%s) starting" % FULL),
        ("tn_config::node", "Max header delay set to %d ms" % max_ms),
        ("tn_config::node", "Min header delay set to %d ms" % min_ms),
        ("tn_config::node", "Max batch delay set to %d ms" % batch_ms)]))


class PerNodeValuesTests(RunDirCase):
    """check() (d) with consensus_parameters.overrides (deploy step 9) and param_arms
    (tools/params-apply.sh): per instance, the fleet value, its override or an arm's value."""

    def run_with(self, logs, **manifest):
        run = self.make_run({})
        for name, text in logs.items():
            (run / "logs" / name).write_text(text)
        return P.scan_run(str(run)), manifest_for(**manifest)

    def test_override_node_passes_with_its_own_value(self):
        logs = {"bench-validator-01-telcoin.log": boot_log("2026-01-01T00:00:00", 500),
                "bench-validator-03-telcoin.log": boot_log("2026-01-01T00:00:01", 600),
                "bench-validator-03-unit-stdout.log": boot_log("2026-01-01T00:00:01", 600)}
        cp = dict(GOOD_PARAMS, overrides={"bench-validator-03": {"max_header_delay": "600ms"}})
        scan, m = self.run_with(logs, consensus_parameters=cp)
        self.assertEqual([(e["instance"], e["value"]) for e in scan["param_events"] if e["key"] == "max_header_delay_ms"],
                         [("bench-validator-01", 500), ("bench-validator-03", 600)])   # the unit copy is a repeat
        r = P.check(scan, m)
        self.assertTrue(r["ok"], r["problems"])
        # Without the override the old message stands.
        r = P.check(scan, manifest_for())
        self.assertEqual(r["problems"], ["logs show max_header_delay_ms=600, manifest "
                                         "consensus_parameters.max_header_delay_ms is 500"])

    def test_an_override_covers_only_its_own_node(self):
        logs = {"bench-validator-01-telcoin.log": boot_log("2026-01-01T00:00:00", 600)}
        cp = dict(GOOD_PARAMS, overrides={"bench-validator-03": {"max_header_delay": "600ms"}})
        r = P.check(*self.run_with(logs, consensus_parameters=cp))
        self.assertEqual(r["problems"], ["logs show max_header_delay_ms=600 on bench-validator-01; expected the fleet "
                                         "value, its override or a param arm's (bench-validator-01: 500)"])

    def test_arm_values_apply_from_the_arm_begin_and_stay(self):
        logs = {"bench-validator-02-telcoin-pre-arm-a1-20260101T010000Z.log": boot_log("2026-01-01T00:00:00", 500),
                "bench-validator-02-telcoin.log": boot_log("2026-01-01T01:00:05", 700, min_ms=350)
                + boot_log("2026-01-01T03:00:00", 700, min_ms=350)}   # a restart after the arm closed
        arms = [{"name": "a1", "begin": "2026-01-01T01:00:00Z", "end": "2026-01-01T02:00:00Z",
                 "nodes": {"bench-validator-02": {"max_header_delay": "700ms", "min_header_delay": "350ms"}}}]
        r = P.check(*self.run_with(logs, param_arms=arms))
        self.assertTrue(r["ok"], r["problems"])
        # An arm that began after the line does not cover it.
        late = [dict(arms[0], begin="2026-01-01T01:30:00Z")]
        r = P.check(*self.run_with(logs, param_arms=late))
        self.assertEqual(r["problems"], [
            "logs show max_header_delay_ms=700 on bench-validator-02; expected the fleet value, its override or a "
            "param arm's (bench-validator-02: 500)",
            "logs show min_header_delay_ms=350 on bench-validator-02; expected the fleet value, its override or a "
            "param arm's (bench-validator-02: 250)"])

    def test_mismatch_still_fails_with_overrides_and_arms(self):
        logs = {"bench-validator-03-telcoin.log": boot_log("2026-01-01T01:00:10", 650)}
        cp = dict(GOOD_PARAMS, overrides={"bench-validator-03": {"max_header_delay": "600ms"}})
        arms = [{"name": "a1", "begin": "2026-01-01T01:00:00Z", "end": None,
                 "nodes": {"bench-validator-03": {"max_header_delay": "1s"}}}]
        r = P.check(*self.run_with(logs, consensus_parameters=cp, param_arms=arms))
        self.assertFalse(r["ok"])
        self.assertEqual(r["problems"], ["logs show max_header_delay_ms=650 on bench-validator-03; expected the fleet "
                                         "value, its override or a param arm's (bench-validator-03: 500, 600, 1000)"])

    def test_helpers(self):
        self.assertEqual([P.dur_ms(v) for v in ("500ms", "2s", "1.5s", "2m", 250, "x", None, True)],
                         [500, 2000, 1500, 120000, 250, None, None, None])
        self.assertEqual(P.ts_epoch("2026-01-01T00:00:01.5Z") - P.ts_epoch("2026-01-01T00:00:00Z"), 1.5)
        self.assertEqual(P.ts_epoch("2026-01-01T02:00:00+02:00"), P.ts_epoch("2026-01-01T00:00:00Z"))
        self.assertIsNone(P.ts_epoch("yesterday"))
        m = {"consensus_parameters": dict(GOOD_PARAMS, overrides={"v1": {"max_header_delay": "300ms"}}),
             "param_arms": [{"name": "a", "begin": "2026-01-01T01:00:00Z", "end": None,
                             "nodes": {"v1": {"max_header_delay": "400ms"}, "v2": {"max_header_delay": "450ms"}}}]}
        self.assertEqual(P.expected_param_values(m, "v1", "max_header_delay_ms", "2026-01-01T00:59:59Z"), [300, 500])
        self.assertEqual(P.expected_param_values(m, "v1", "max_header_delay_ms", "2026-01-01T01:00:00Z"), [300, 400, 500])
        self.assertEqual(P.expected_param_values(m, "v1", "max_header_delay_ms"), [300, 400, 500])
        self.assertEqual(P.expected_param_values(m, "v3", "max_header_delay_ms"), [500])
        self.assertTrue(P.per_node_values(m))
        self.assertFalse(P.per_node_values(manifest_for()))
        self.assertFalse(P.per_node_values({"consensus_parameters": {"overrides": {}}, "param_arms": []}))


class CliTests(RunDirCase):
    def test_exit_codes(self):
        run = self.make_run(STANDARD, manifest=manifest_for())
        p = self.cli(run)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "OK")
        p = self.cli(run, "--expect-sha", OTHER, "--json")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(json.loads(p.stdout)["ok"])
        empty = self.make_run({"deploy-20260101T000000Z.log": ("deploy-output.txt", False)},
                              manifest=manifest_for(), name="no-node-logs")
        p = self.cli(empty)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p = self.cli(self.root / "absent")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is not a directory", p.stderr)

    def test_update_manifest_adds_one_key_and_keeps_the_rest(self):
        run = self.make_run(STANDARD)
        original = manifest_for(notes=["kept as written: café ✓"], timestamps={"deploy_start": "2026-01-01T00:00:00Z"})
        text = json.dumps(original, indent=2, ensure_ascii=False) + "\n"
        path = run / "manifest.json"
        path.write_bytes(text.encode("utf-8"))
        path.chmod(0o640)
        p = self.cli(run, "--update-manifest")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        new_text = path.read_bytes().decode("utf-8")
        new = json.loads(new_text)
        self.assertEqual(list(new), list(original) + ["node_startup_check"])
        self.assertEqual({k: new[k] for k in original}, original)
        self.assertTrue(new["node_startup_check"]["ok"])
        self.assertEqual(new["node_startup_check"]["expected_sha"], FULL)
        self.assertTrue(new_text.startswith(text[:-len("\n}\n")]))   # every byte before the new key
        self.assertTrue(new_text.endswith("}\n") and not new_text.endswith("\n\n"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(sorted(os.listdir(str(run))), ["logs", "manifest.json"])   # no temp file left

    def test_update_manifest_without_manifest_fails(self):
        run = self.make_run(STANDARD)
        p = self.cli(run, "--update-manifest", "--expect-sha", FULL)
        self.assertEqual(p.returncode, 1)
        self.assertIn("does not exist", p.stderr)
        self.assertFalse((run / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
