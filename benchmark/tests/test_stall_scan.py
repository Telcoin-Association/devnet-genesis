"""stall-scan.py: commit stalls from the sampler CSVs, inside manifest.phases' mixed + cooldown window (the plan, or
the blasters' real phases once benchmark-blast.sh has rewritten them)."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

BENCH = Path(__file__).resolve().parents[1]
RUN = Path(__file__).resolve().parent / "fixtures" / "stall-scan" / "run"
SPEC = importlib.util.spec_from_file_location("stall_scan", BENCH / "stall-scan.py")
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)

T = 1791249600  # the fixture's planned mixed start


def shell_functions(path, *names):
    """The named functions of a script (a one-line function is its own line; others end at `}`)."""
    lines = Path(path).read_text().splitlines()
    out = []
    for name in names:
        start = next(i for i, line in enumerate(lines) if line.startswith(name + "() {"))
        end = start if lines[start].rstrip().endswith("}") else lines.index("}", start)
        out.extend(lines[start:end + 1])
    return "\n".join(out) + "\n"


class StallScanTests(unittest.TestCase):
    def test_fixture_run_finds_only_the_mixed_phase_stall(self):
        # The fixture also holds a flat preamble (before the window), a lagging node with a blank
        # block, a sampler file from before the block column, and a flat cooldown drain.
        self.assertEqual(scan.scan(RUN, 60), [dict(
            start="2026-10-06T01:30:00Z", end="2026-10-06T01:35:00Z", secs=300, block=26,
            source="sampler-blocks-only")])
        self.assertEqual(scan.scan(RUN, 301), [])

    def test_fleet_maximum_ignores_a_lagging_node(self):
        samples = [(T, 10), (T + 30, 11), (T + 40, 3), (T + 60, 11), (T + 70, 4), (T + 90, 12)]
        series = scan.fleet_max(samples, T, T + 600, 30)
        self.assertEqual(series, {T: 10, T + 30: 11, T + 60: 11, T + 90: 12})
        self.assertEqual(scan.flat_stretches(series, T + 600, 60), [dict(
            start=scan.iso(T + 30), end=scan.iso(T + 90), secs=60, block=11, source="sampler-blocks-only")])

    def test_stall_running_past_the_window_is_open(self):
        samples = [(T + i * 30, min(i, 50)) for i in range(80)]   # flat from T+1500 on
        series = scan.fleet_max(samples, T, T + 1980, 30)
        self.assertEqual(scan.flat_stretches(series, T + 1800, 60), [dict(
            start=scan.iso(T + 1500), end=scan.iso(T + 1980), secs=480, block=50, source="sampler-blocks-only",
            open=True)])
        # The same flat stretch starting after the mixed phase is the cooldown drain.
        self.assertEqual(scan.flat_stretches(series, T + 1500, 60), [])

    def test_cli_prints_json_and_fails_without_phases(self):
        result = subprocess.run([sys.executable, str(BENCH / "stall-scan.py"), "--results", str(RUN)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)[0]["block"], 26)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            shutil.copytree(RUN, run)
            (run / "manifest.json").write_text(json.dumps(dict(phases=[])))
            result = subprocess.run([sys.executable, str(BENCH / "stall-scan.py"), "--results", str(run)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("mixed/cooldown window", result.stderr)
            self.assertEqual(result.stdout, "")


class RealPhasesTests(unittest.TestCase):
    """D42. Bench 5's plan put the idle chain after the load inside the planned cooldown: a stall that did not happen.
    Once benchmark-blast.sh (record_real_phases) rewrites manifest.phases from the blasters' own run.phases, whose mixed
    phase starts 77 s before the plan as bench 5's load did, the same samples hold none."""

    P0 = 1791249000   # start_at, on a 30-s bucket; the plan: preamble 90 s, warmup 120 s, mixed 2400 s, cooldown 180 s
    PLAN = (("preamble", 0, 90), ("warmup", 90, 210), ("mixed", 210, 2610), ("cooldown", 2610, 2790))
    # Each blaster: preamble start, preamble end, cooldown end (s after start_at); warmup 120 s, mixed 2400 s.
    BLASTERS = ((0.4, 13.1, 2534.6), (2.7, 13.6, 2580.2), (0.9, 13.3, 2541.0))
    DRIVER = r'''
set -euo pipefail
BENCH_RESULTS_DIR="$RUN"; VAL_COUNT=3
bench_warn() { echo "⚠ $*" >&2; }
bench_now_iso() { echo 2026-11-12T00:00:00Z; }
'''

    def phases(self, rows):
        return [dict(name=n, start=scan.iso(self.P0 + a), end=scan.iso(self.P0 + b)) for n, a, b in rows]

    def make_run(self, root):
        run = root / "run"
        (run / "sampler").mkdir(parents=True)
        (run / "blasters").mkdir()
        (run / "manifest.json").write_text(json.dumps({"phases": self.phases(self.PLAN), "notes": []}))
        # The chain commits while the blasters load it and a little past their mixed phase (it ends at +2534), then
        # idles: no transactions, no blocks.
        rows = ["ts_unix,block"] + ["%d,%d" % (self.P0 + s, min(s, 2550) // 30) for s in range(0, 3001, 30)]
        (run / "sampler" / "bench-validator-01.csv").write_text("\n".join(rows) + "\n")
        for k, (a, b, e) in enumerate(self.BLASTERS):
            name = "bench-blaster-%02d" % (k + 1)
            (run / "meta" / name).mkdir(parents=True)
            (run / "meta" / name / "MACHINE_TYPE").write_text("e2-standard-2\n")
            t = self.P0
            phases = [dict(name="preamble", start_unix=t + a, end_unix=t + b),
                      dict(name="warmup", start_unix=t + b, end_unix=t + b + 120),
                      dict(name="mixed", start_unix=t + b + 120, end_unix=t + b + 2520),
                      dict(name="cooldown", start_unix=t + b + 2520, end_unix=t + e)]
            (run / "blasters" / (name + ".json")).write_text(json.dumps({"run": {"phases": phases}}))
        return run

    def rewrite(self, run):
        code = (self.DRIVER + shell_functions(BENCH / "bench-lib.sh", "bench_manifest", "bench_manifest_jq")
                + shell_functions(BENCH / "benchmark-blast.sh", "blaster_name", "blaster_created", "record_real_phases")
                + "record_real_phases\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("BENCH_")}
        result = subprocess.run(["bash", "-c", code], env=dict(env, RUN=str(run)), capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_the_idle_tail_is_a_stall_under_the_plan_and_none_under_the_real_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_run(Path(directory))
            self.assertEqual(scan.scan(run, 60), [dict(
                start=scan.iso(self.P0 + 2550), end=scan.iso(self.P0 + 2790), secs=240, block=85,
                source="sampler-blocks-only", open=True)])
            out = self.rewrite(run)
            self.assertTrue(out.startswith("    phases (real, the blasters' run.phases; the plan is kept as "
                                           "phases_planned): preamble "), out)
            manifest = json.loads((run / "manifest.json").read_text())
            self.assertEqual(manifest["phases_planned"], self.phases(self.PLAN))
            self.assertEqual(manifest["phases"], self.phases((("preamble", 0, 14), ("warmup", 13, 134),
                                                              ("mixed", 133, 2534), ("cooldown", 2533, 2581))))
            self.assertEqual(scan.scan(run, 60), [])
            result = subprocess.run([sys.executable, str(BENCH / "stall-scan.py"), "--results", str(run)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [])
            # a stall inside the real mixed phase is still found
            rows = ["ts_unix,block"] + ["%d,%d" % (self.P0 + s, (min(s, 1200) + max(0, s - 1500)) // 30)
                                        for s in range(0, 3001, 30)]
            (run / "sampler" / "bench-validator-01.csv").write_text("\n".join(rows) + "\n")
            self.assertEqual(scan.scan(run, 60), [dict(
                start=scan.iso(self.P0 + 1200), end=scan.iso(self.P0 + 1530), secs=330, block=40,
                source="sampler-blocks-only")])


if __name__ == "__main__":
    unittest.main()
