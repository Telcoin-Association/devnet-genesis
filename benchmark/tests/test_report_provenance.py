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
            "bench-validator-01-unit-stderr-20261104T003616Z.rotated-2.log.gz": "bench-validator-01",
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

    def test_rotated_generations_named_by_the_teardown_pull(self):
        # The teardown pull lands each rotated generation as <inst>-unit-<stream>.rotated-<N>.log.gz, and as
        # <inst>-unit-<stream>-<UTC stamp>.rotated-<N>.log.gz when that name is already taken.
        names = ["bench-validator-01-unit-stdout.rotated-1.log.gz",
                 "bench-validator-01-unit-stdout-20261104T003616Z.rotated-1.log.gz",
                 "bench-validator-01-unit-stderr.rotated-3.log.gz",
                 "bench-validator-01-unit-stderr-20261104T003616Z.rotated-12.log.gz"]
        run = self.make_run(dict((n, ("node-log-validator-unit-stdout.txt", True)) for n in names))
        self.assertEqual([os.path.basename(f) for f in P.node_log_files(str(run))], sorted(names))
        for n in names:
            with self.subTest(name=n):
                self.assertEqual(P.instance_of(n), "bench-validator-01")
        scan = P.scan_run(str(run))
        self.assertEqual(scan["instances"], ["bench-validator-01"])
        self.assertEqual(len(scan["starts"]), 2)  # the same two boots in every generation: counted once

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

    def test_a_listed_node_without_a_start_is_a_problem(self):
        # D20: the manifest lists four nodes; only bench-validator-01 and bench-observer-11 logged a start.
        # bench-validator-02's log holds no start line (its early generations were rotated away) and
        # bench-validator-03 has no log at all: both are named, and the check fails.
        run = self.make_run(STANDARD)
        (run / "logs" / "bench-validator-02-unit-stdout.log").write_text(
            'ts=2026-01-01T01:00:00.000000000Z level=INFO target=consensus message="subdag committed" round=900\n')
        scan = P.scan_run(str(run))
        listed = [{"name": "bench-validator-01", "role": "validator"}, {"name": "bench-validator-02", "role": "validator"},
                  {"name": "bench-validator-03", "role": "validator"}, {"name": "bench-observer-11", "role": "observer"},
                  {"name": "load-a", "role": "blaster"}]   # a load generator runs no node: never expected
        cs = {"due": 1767225600, "nodes": 4, "started": 4, "skipped_running": 0, "spread_secs": 0, "max_late_secs": 0}
        r = P.check(scan, manifest_for(instances=listed, coordinated_start=cs))
        self.assertFalse(r["ok"])
        self.assertEqual(r["problems"], ["no start line for bench-validator-02", "no start line for bench-validator-03"])
        # Every listed node started: ok. No list: nothing to compare, as before.
        self.assertTrue(P.check(scan, manifest_for(instances=[listed[0], listed[3]], coordinated_start=cs))["ok"])
        self.assertTrue(P.check(scan, manifest_for())["ok"])
        self.assertEqual(P.listed_instances({"instances": listed + [
            {"role": "validator"}, {"name": " ", "role": "observer"}, {"name": "bench-validator-04"}, "bench-validator-05"]}),
            ["bench-observer-11", "bench-validator-01", "bench-validator-02", "bench-validator-03"])
        self.assertEqual(P.listed_instances(None), [])

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
        listed = self.make_run(STANDARD, name="listed", manifest=manifest_for(instances=[
            {"name": "bench-validator-01", "role": "validator"}, {"name": "bench-observer-11", "role": "observer"},
            {"name": "bench-validator-09", "role": "validator"}]))
        p = self.cli(listed)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-2:], ["PROBLEMS:", "  - no start line for bench-validator-09"])
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


# ---- bench6 switch provenance ----
#
# The node logs one "node switches" line (target node::switches) after parameters.yaml is loaded at every
# start: a key=value field per switch of benchmark/arms/switches.tsv the image knows, values as YAML scalars.

ALL_OFF = {"quorum_exec_block": "false", "quorum_exec_block_starved_rounds": "0", "vote_queue_fix": "false",
           "mdbx_random_advice": "false", "sealed_tx_keep": "false", "digest_dedupe": "false",
           "recovery_threads": "0", "epoch_close_task_drain": "false", "epoch_record_state_check": "false",
           "parent_grace": "0ms", "rpc_admission_backlog_outputs": "0", "pipelined_persist": "false"}
FINAL = dict(ALL_OFF, vote_queue_fix="true", mdbx_random_advice="true", recovery_threads="3",
             parent_grace="150ms")
CONTRACT = {"at": "2026-01-01T00:00:00Z", "flags_ok": True,
            "strings": {"Max header delay set to": 1, "node switches": 1}}


def switch_boot(ts, switches, drop=()):
    """boot_log() plus the node switch line, logfmt as the bench nodes write it."""
    fields = " ".join("%s=%s" % (k, v) for k, v in switches.items() if k not in drop)
    return boot_log(ts, 500) + ('ts=%s.900Z level=info target=node::switches span=node-startup '
                                'span_path=node-startup message="node switches" %s\n' % (ts, fields))


def arm(name, begin, switches, **extra):
    a = {"name": name, "begin": begin, "end": None, "nodes": {}, "switches": dict(switches)}
    a.update(extra)
    return a


class SwitchParseTests(unittest.TestCase):
    def test_logfmt_json_and_plain_lines(self):
        line = switch_boot("2026-01-01T00:00:00", FINAL).splitlines()[-1]
        self.assertEqual(P.parse_switch_line(line), ("2026-01-01T00:00:00.900Z", FINAL))
        js = json.dumps({"timestamp": "2026-01-01T00:00:01Z", "level": "INFO", "target": "node::switches",
                         "fields": {"message": "node switches", "vote_queue_fix": True, "recovery_threads": 3,
                                    "parent_grace": "150ms"}})
        self.assertEqual(P.parse_switch_line(js), ("2026-01-01T00:00:01Z",
                                                   {"vote_queue_fix": "true", "recovery_threads": "3",
                                                    "parent_grace": "150ms"}))
        plain = "\x1b[32m2026-01-01T00:00:02Z  INFO\x1b[0m node::switches: node switches digest_dedupe=false parent_grace=0ms"
        self.assertEqual(P.parse_switch_line(plain), ("2026-01-01T00:00:02Z",
                                                      {"digest_dedupe": "false", "parent_grace": "0ms"}))
        # A Debug-formatted string value keeps no quotes.
        dbg = 'ts=2026-01-01T00:00:03Z level=info message="node switches" parent_grace="\\"150ms\\""'
        self.assertEqual(P.parse_switch_line(dbg)[1], {"parent_grace": "150ms"})
        for other in ('ts=2026-01-01T00:00:03Z message="node switches seen" a=1',
                      'ts=2026-01-01T00:00:03Z message="other" note="node switches" a=1',
                      "nothing here"):
            self.assertIsNone(P.parse_switch_line(other), other)
        self.assertIn(b"node switches", P._CANDIDATE_MARKERS)

    def test_value_comparison_by_type(self):
        self.assertEqual([P.switch_value("bool", v) for v in ("true", "False", True, "1", "yes", None)],
                         [True, False, True, None, None, None])
        self.assertEqual([P.switch_value("int", v) for v in ("3", 3, "0", "-1", "x", True)], [3, 3, 0, None, None, None])
        self.assertEqual([P.switch_value("dur", v) for v in ("150ms", "0.15s", "0ms", "0ns", "0", "150", "1m", "x", True)],
                         [150000.0, 150000.0, 0.0, 0.0, 0.0, 150000.0, 60000000.0, None, None])
        rows = P.switch_rows()
        self.assertEqual([r["key"] for r in rows], list(ALL_OFF))
        self.assertEqual([r["key"] for r in rows if r["optional"]], ["pipelined_persist"])


class SwitchCheckTests(RunDirCase):
    def run_with(self, logs, **manifest):
        run = self.make_run({})
        for name, text in logs.items():
            (run / "logs" / name).write_text(text)
        return P.scan_run(str(run)), manifest_for(**manifest)

    def test_old_runs_are_checked_as_before(self):
        scan, m = self.run_with({"bench-validator-01-telcoin.log": boot_log("2026-01-01T00:00:00", 500)},
                                param_arms=[arm("p1", "2026-01-01T00:00:00Z", FINAL)])
        self.assertNotIn("switches", scan["starts"][0])
        r = P.check(scan, m)
        self.assertTrue(r["ok"], r["problems"])
        self.assertNotIn("switches", r)

    def test_defaults_before_the_first_arm_then_the_arm_in_force(self):
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T00:00:00", ALL_OFF)
                + switch_boot("2026-01-01T01:00:05", FINAL),
                "bench-validator-01-unit-stdout.log": switch_boot("2026-01-01T00:00:00", ALL_OFF)}
        scan, m = self.run_with(logs, node_probe=CONTRACT, param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        self.assertEqual([s["switches"] for s in scan["starts"]], [ALL_OFF, FINAL])   # the unit copy is a repeat
        r = P.check(scan, m)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["switches"], {"required": True, "checked": 2, "matched": 2, "missing": 0, "problems": []})
        self.assertEqual(r["starts"][1]["switches"], FINAL)

    def test_mismatch_names_the_key_the_start_and_the_arm(self):
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T01:00:05", dict(FINAL, recovery_threads="0")),
                "bench-validator-02-telcoin.log": switch_boot("2026-01-01T01:00:06", dict(FINAL, recovery_threads="0"))}
        scan, m = self.run_with(logs, param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        r = P.check(scan, m)
        self.assertFalse(r["ok"])
        self.assertEqual(r["problems"], [
            "node switches show recovery_threads=0 at 2 start(s) (bench-validator-01 at 2026-01-01T01:00:05.000Z, "
            "bench-validator-02 at 2026-01-01T01:00:06.000Z); arm final sets recovery_threads=3"])
        self.assertEqual(r["switches"]["problems"], r["problems"])
        self.assertEqual((r["switches"]["checked"], r["switches"]["matched"]), (2, 0))
        # A start before the arm began runs the defaults: FINAL there is a mismatch too.
        scan, m = self.run_with({"bench-validator-03-telcoin.log": switch_boot("2026-01-01T00:59:00", FINAL)},
                                param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        problems = P.check(scan, m)["problems"]
        self.assertEqual(len(problems), 4)
        self.assertIn("node switches show parent_grace=150ms at 1 start(s) (bench-validator-03 at "
                      "2026-01-01T00:59:00.000Z); the defaults sets parent_grace=0ms", problems)

    def test_bools_and_durations_compare_by_value(self):
        spelled = dict(FINAL, vote_queue_fix="True", parent_grace="0.15s", mdbx_random_advice="TRUE")
        scan, m = self.run_with({"bench-validator-01-telcoin.log": switch_boot("2026-01-01T01:00:05", spelled)},
                                param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        self.assertTrue(P.check(scan, m)["ok"])
        not_bool = dict(FINAL, vote_queue_fix="1")
        scan, m = self.run_with({"bench-validator-01-telcoin.log": switch_boot("2026-01-01T01:00:05", not_bool)},
                                param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        self.assertIn("show vote_queue_fix=1", P.check(scan, m)["problems"][0])

    def test_missing_line_fails_only_where_the_contract_requires_it(self):
        logs = {"bench-validator-01-telcoin.log": boot_log("2026-01-01T00:00:00", 500),
                "bench-validator-02-telcoin.log": switch_boot("2026-01-01T00:00:01", ALL_OFF)}
        scan, m = self.run_with(logs, node_probe=CONTRACT)
        r = P.check(scan, m)
        self.assertEqual(r["problems"], ["no node switches line at 1 start(s), though the image contract requires one: "
                                         "bench-validator-01 at 2026-01-01T00:00:00.000Z"])
        self.assertEqual((r["switches"]["missing"], r["switches"]["checked"]), (1, 1))
        # Without the contract a start without the line is not judged; the one with it still is.
        scan, m = self.run_with(logs)
        r = P.check(scan, m)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["switches"], {"required": False, "checked": 1, "matched": 1, "missing": 0, "problems": []})
        # The contract alone runs the check, even with no line logged anywhere.
        scan, m = self.run_with({"bench-validator-01-telcoin.log": boot_log("2026-01-01T00:00:00", 500)},
                                node_probe=CONTRACT)
        self.assertEqual(P.check(scan, m)["switches"]["missing"], 1)

    def test_an_optional_switch_may_be_absent_only_at_its_default(self):
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T01:00:05", FINAL, drop=("pipelined_persist",))}
        scan, m = self.run_with(logs, param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        self.assertTrue(P.check(scan, m)["ok"])
        piped = dict(FINAL, pipelined_persist="true")
        scan, m = self.run_with(logs, param_arms=[arm("pipe", "2026-01-01T01:00:00Z", piped)])
        self.assertEqual(P.check(scan, m)["problems"], [
            "node switches lack pipelined_persist at 1 start(s) (bench-validator-01 at 2026-01-01T01:00:05.000Z); "
            "arm pipe sets pipelined_persist=true"])
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T01:00:05", FINAL, drop=("parent_grace",))}
        scan, m = self.run_with(logs, param_arms=[arm("final", "2026-01-01T01:00:00Z", FINAL)])
        self.assertIn("node switches lack parent_grace", P.check(scan, m)["problems"][0])

    def test_a_prestart_arm_covers_the_first_start(self):
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T00:00:00", FINAL)
                + switch_boot("2026-01-01T02:00:00", FINAL)}        # a chaos restart later on
        # An older manifest's prestart arm records no begin: it counts from the first start.
        prestart = arm("final", None, FINAL, via="prestart")
        scan, m = self.run_with(logs, node_probe=CONTRACT, param_arms=[prestart])
        r = P.check(scan, m)
        self.assertTrue(r["ok"], r["problems"])
        # Applied by params-apply at a begin, the arm would not cover a start 30 s before it.
        scan, m = self.run_with(logs, param_arms=[dict(prestart, via="params-apply", begin="2026-01-01T00:00:30Z")])
        self.assertFalse(P.check(scan, m)["ok"])

    def test_overrides_before_the_first_arm_and_a_failed_arm(self):
        cp = dict(GOOD_PARAMS, overrides={"bench-validator-03": {"vote_queue_fix": "true"}})
        logs = {"bench-validator-03-telcoin.log": switch_boot("2026-01-01T00:00:00", dict(ALL_OFF, vote_queue_fix="true"))}
        scan, m = self.run_with(logs, consensus_parameters=cp)
        self.assertTrue(P.check(scan, m)["ok"])
        scan, m = self.run_with(logs)
        self.assertIn("the defaults sets vote_queue_fix=false", P.check(scan, m)["problems"][0])
        # v02 was restarted into arm v, which failed there; put back by hand it logs arm a's state.
        a = arm("a", "2026-01-01T00:00:00Z", ALL_OFF, end="2026-01-01T01:00:00Z")
        v = arm("v", "2026-01-01T01:00:00Z", FINAL, failed="bench-validator-02")
        logs = {"bench-validator-02-telcoin.log": switch_boot("2026-01-01T01:00:05", FINAL)
                + switch_boot("2026-01-01T01:10:00", ALL_OFF)}
        scan, m = self.run_with(logs, param_arms=[a, v])
        self.assertTrue(P.check(scan, m)["ok"])
        scan, m = self.run_with(logs, param_arms=[a, dict(v, failed=None)])
        self.assertEqual(P.check(scan, m)["problems"][0].split(";")[1], " arm v sets mdbx_random_advice=true")
        self.assertEqual(P.expected_switches(m, "bench-validator-02", None, P.switch_rows())[0][0], "the defaults")
        self.assertEqual([lab for lab, _s in P.expected_switches(m, "x", None, P.switch_rows())],
                         ["the defaults", "arm a", "arm v"])

    def test_a_set_arm_changes_only_the_switches_it_wrote_on_its_nodes(self):
        # tools/params-apply.sh --set all:... or <node>:... records no switches state, only nodes[].
        a0 = arm("a0", "2026-01-01T00:00:00Z", FINAL, via="prestart")
        s1 = {"name": "s1", "begin": "2026-01-01T01:00:00Z", "end": None, "via": "params-apply", "file": None,
              "nodes": {"bench-validator-01": {"recovery_threads": "0", "max_header_delay": "700ms"}}}
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T01:00:05", dict(FINAL, recovery_threads="0")),
                "bench-validator-02-telcoin.log": switch_boot("2026-01-01T01:00:06", FINAL)}
        scan, m = self.run_with(logs, param_arms=[a0, s1])
        r = P.check_switches(scan["starts"], m)
        self.assertEqual((r["checked"], r["matched"], r["problems"]), (2, 2, []))
        # v02 restarted with v01's write would not match: the arm did not touch it.
        logs["bench-validator-02-telcoin.log"] = switch_boot("2026-01-01T01:00:06", dict(FINAL, recovery_threads="0"))
        scan, m = self.run_with(logs, param_arms=[a0, s1])
        self.assertEqual(P.check_switches(scan["starts"], m)["problems"], [
            "node switches show recovery_threads=0 at 1 start(s) (bench-validator-02 at 2026-01-01T01:00:06.000Z); "
            "arm a0 sets recovery_threads=3"])

    def test_unreadable_switch_list_is_a_problem(self):
        scan, m = self.run_with({"bench-validator-01-telcoin.log": switch_boot("2026-01-01T00:00:00", ALL_OFF)})
        orig = P.SWITCHES_TSV
        P.SWITCHES_TSV = str(self.root / "absent.tsv")
        try:
            r = P.check(scan, m)
        finally:
            P.SWITCHES_TSV = orig
        self.assertFalse(r["ok"])
        self.assertTrue(r["problems"][0].startswith("node switches not checked: "), r["problems"])

    def test_cli_reports_the_switch_check(self):
        run = self.make_run({}, manifest=manifest_for(node_probe=CONTRACT))
        (run / "logs" / "bench-validator-01-telcoin.log").write_text(switch_boot("2026-01-01T00:00:00", ALL_OFF))
        p = self.cli(run)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("  node switches: 1 start(s) checked, 1 matched the arm in force, 0 without a line "
                      "(the image contract requires one)", p.stdout)
        (run / "logs" / "bench-validator-02-telcoin.log").write_text(boot_log("2026-01-01T00:00:01", 500))
        p = self.cli(run)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("no node switches line at 1 start(s)", p.stdout)

    # ---- bench7 staging start before the prestart arm ----
    # Deploy step 7 starts each node once alone (stage-only) with every switch at its default, then
    # writes the prestart arm and starts all nodes at once: the arm's begin is that coordinated start.

    NODES = ["bench-validator-%02d" % i for i in range(1, 11)] + ["bench-observer-11"]
    BEGIN = "2026-01-01T00:01:00Z"

    def staged_run(self, staging=ALL_OFF, arm_switches=FINAL, **arm_extra):
        """11 nodes: one staging start before BEGIN, one start at BEGIN, two of them restarted later."""
        logs = {}
        for i, inst in enumerate(self.NODES):
            text = switch_boot("2026-01-01T00:00:%02d" % (10 + i), staging) + switch_boot("2026-01-01T00:01:00", FINAL)
            if inst in ("bench-validator-03", "bench-observer-11"):
                text += switch_boot("2026-01-01T02:00:00", FINAL)      # chaos restarts
            logs[inst + "-unit-stdout.log"] = text
        prestart = arm("final", self.BEGIN, arm_switches, via="prestart", ready=self.BEGIN)
        prestart.update(arm_extra)
        return self.run_with(logs, node_probe=CONTRACT, param_arms=[prestart])

    def test_staging_starts_before_the_prestart_begin_are_at_the_defaults(self):
        scan, m = self.staged_run()
        r = P.check(scan, m)
        self.assertTrue(r["ok"], r["problems"])
        staged = [{"instance": inst, "ts": "2026-01-01T00:00:%02d.000Z" % (10 + i)}
                  for i, inst in enumerate(self.NODES)]
        staged = sorted(staged, key=lambda s: s["instance"])
        self.assertEqual(r["switches"], {"required": True, "checked": 24, "matched": 24, "missing": 0, "problems": [],
                                         "pre_arm": 11, "pre_arm_off": 0, "pre_arm_starts": staged,
                                         "pre_arm_begin": self.BEGIN})
        report = P._report("run", scan, r).splitlines()
        i = report.index("  node switches: 24 start(s) checked, 24 matched the arm in force, 0 without a line "
                         "(the image contract requires one)")
        self.assertEqual(report[i + 1], "  node switches: 11 start(s) before the arm began (staging), all at the defaults")

    def test_a_staging_start_with_a_switch_on_is_a_problem(self):
        scan, m = self.staged_run(staging=dict(ALL_OFF, vote_queue_fix="true"))
        r = P.check(scan, m)
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["problems"]), 1)
        self.assertTrue(r["problems"][0].startswith(
            "node switches show vote_queue_fix=true at 11 start(s) (bench-observer-11 at 2026-01-01T00:00:20.000Z, "),
            r["problems"])
        self.assertTrue(r["problems"][0].endswith("; the defaults sets vote_queue_fix=false"), r["problems"])
        sw = r["switches"]
        self.assertEqual((sw["checked"], sw["matched"], sw["pre_arm"], sw["pre_arm_off"]), (24, 13, 11, 11))
        self.assertIn("  node switches: 11 start(s) before the arm began (staging), 11 NOT at the defaults",
                      P._report("run", scan, r).splitlines())

    def test_a_prestart_arm_without_a_begin_counts_from_the_first_start(self):
        for no_begin in ({"begin": None}, {"begin": "not a time"}):
            scan, m = self.staged_run(**no_begin)
            r = P.check(scan, m)
            self.assertEqual(r["problems"][0].split(";")[1], " arm final sets mdbx_random_advice=true", no_begin)
            self.assertEqual((r["switches"]["checked"], r["switches"]["matched"]), (24, 13))
            self.assertNotIn("pre_arm", r["switches"])
            scan, m = self.staged_run(staging=FINAL, **no_begin)
            r = P.check(scan, m)
            self.assertTrue(r["ok"], r["problems"])
            self.assertNotIn("pre_arm", r["switches"])
            self.assertNotIn("before the arm began", P._report("run", scan, r))
        m = manifest_for(param_arms=[{k: v for k, v in arm("final", None, FINAL, via="prestart").items() if k != "begin"}])
        self.assertEqual([lab for lab, _s in P.expected_switches(m, "x", "2026-01-01T00:00:00Z", P.switch_rows())],
                         ["arm final"])

    def test_an_arm_walk_is_unaffected(self):
        # params-apply arms, the first after the deploy: the starts before it are the run's baseline.
        a1 = arm("a1", "2026-01-01T01:00:00Z", FINAL, via="params-apply", end="2026-01-01T02:00:00Z")
        a2 = arm("a2", "2026-01-01T02:00:00Z", dict(FINAL, recovery_threads="0"), via="params-apply")
        logs = {"bench-validator-01-telcoin.log": switch_boot("2026-01-01T00:00:00", ALL_OFF)
                + switch_boot("2026-01-01T01:00:05", FINAL) + switch_boot("2026-01-01T02:00:05", a2["switches"]),
                "bench-validator-02-telcoin.log": switch_boot("2026-01-01T00:00:01", ALL_OFF)
                + switch_boot("2026-01-01T01:00:06", FINAL) + switch_boot("2026-01-01T02:00:06", FINAL)}
        scan, m = self.run_with(logs, param_arms=[a1, a2])
        r = P.check(scan, m)
        self.assertEqual(r["switches"], {"required": False, "checked": 6, "matched": 5, "missing": 0, "problems": [
            "node switches show recovery_threads=3 at 1 start(s) (bench-validator-02 at 2026-01-01T02:00:06.000Z); "
            "arm a2 sets recovery_threads=0"]})
        self.assertNotIn("before the arm began", P._report("run", scan, r))


if __name__ == "__main__":
    unittest.main()
