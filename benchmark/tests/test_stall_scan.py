"""stall-scan.py: commit stalls from the sampler CSVs, inside the planned mixed + cooldown window."""
import importlib.util
import json
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


class StallScanTests(unittest.TestCase):
    def test_fixture_run_finds_only_the_mixed_phase_stall(self):
        # The fixture also holds a flat preamble (before the window), a lagging node with a blank
        # block, a sampler file from before the block column, and a flat cooldown drain.
        self.assertEqual(scan.scan(RUN, 60), [dict(
            start="2026-10-06T01:30:00Z", end="2026-10-06T01:35:00Z", secs=300, block=26,
            source="sampler")])
        self.assertEqual(scan.scan(RUN, 301), [])

    def test_fleet_maximum_ignores_a_lagging_node(self):
        samples = [(T, 10), (T + 30, 11), (T + 40, 3), (T + 60, 11), (T + 70, 4), (T + 90, 12)]
        series = scan.fleet_max(samples, T, T + 600, 30)
        self.assertEqual(series, {T: 10, T + 30: 11, T + 60: 11, T + 90: 12})
        self.assertEqual(scan.flat_stretches(series, T + 600, 60), [dict(
            start=scan.iso(T + 30), end=scan.iso(T + 90), secs=60, block=11, source="sampler")])

    def test_stall_running_past_the_window_is_open(self):
        samples = [(T + i * 30, min(i, 50)) for i in range(80)]   # flat from T+1500 on
        series = scan.fleet_max(samples, T, T + 1980, 30)
        self.assertEqual(scan.flat_stretches(series, T + 1800, 60), [dict(
            start=scan.iso(T + 1500), end=scan.iso(T + 1980), secs=480, block=50, source="sampler",
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


if __name__ == "__main__":
    unittest.main()
