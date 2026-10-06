"""Boundary scheduling and fleet watchers with local RPC/command fixtures."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tarfile
import unittest
from unittest import mock

BENCH = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("schedule", BENCH / "recovery-schedule.py")
schedule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schedule)


def encoded_epoch(height=42, epoch=7, duration=1200):
    """Encode the registry's dynamic tuple, including stakeVersion and an empty committee."""
    return "0x" + "".join(f"{word:064x}" for word in (32, 192, 0, height, epoch, duration, 0, 0))


class ScheduleTests(unittest.TestCase):
    def test_snapshot_pins_registry_read_and_resolves_closing_block(self):
        calls = []

        def rpc(url, method, params):
            calls.append((method, params))
            if method == "eth_call":
                return encoded_epoch()
            if params[0] == "latest":
                return dict(number="0x50")
            return dict(number=params[0], timestamp="0x3e8", hash="0xabc")

        with mock.patch.object(schedule, "rpc", rpc):
            info = schedule.snapshot("unused")
        self.assertEqual(calls[1][1][1], "0x50")
        self.assertEqual(calls[2][1], ["0x29", False])
        plan = schedule.schedule(info, 2500, 59, 300)
        self.assertEqual((plan["kill_unix"], plan["boundary_unix"], plan["restart_unix"]),
                         (3341, 3400, 3641))
        self.assertEqual(plan["closing_epoch"], 8)
        self.assertEqual(plan["start_boundary_hash"], "0xabc")

    def test_exact_boundary_and_early_crossing(self):
        info = dict(epoch=7, epoch_start_unix=1000, duration_secs=1200)
        late = schedule.schedule(info, 2141, 59, 300)
        early = schedule.schedule(info, 1500, 600, 900)
        self.assertEqual(late["kill_unix"], 2141)
        self.assertEqual(early["kill_unix"], 1600)
        self.assertGreater(early["restart_unix"], early["boundary_unix"])
        for offset, downtime in ((0, 300), (1200, 1500), (59, 59)):
            with self.assertRaises(ValueError):
                schedule.schedule(info, 1500, offset, downtime)

    def test_invalid_registry_data_and_unopened_epoch(self):
        for data in ("0x", "0x01", encoded_epoch(duration=0), encoded_epoch(height=2**64)):
            with self.assertRaises(ValueError):
                schedule.decode_epoch(data)
        with mock.patch.object(schedule, "rpc", side_effect=[
                dict(number="0x50"), encoded_epoch(epoch=7)]):
            with self.assertRaisesRegex(ValueError, "has not opened"):
                schedule.snapshot("unused", 8)


class WatcherTests(unittest.TestCase):
    def run_watcher(self, body):
        source = (BENCH / "benchmark-blast.sh").read_text()
        function = re.search(r"^round_stall_check\(\) \{\n.*?^\}", source, re.M | re.S).group()
        shell = '''
set -euo pipefail
source "$1/recovery-lib.sh"
INSTANCE_NAMES=(peer victim observer); NODE_ROLES=(validator validator observer)
RUN_DID_KILL=0; RUN_DID_BACK=0; CHAOS_KILL_IDX=1
RUN_DID_PAUSE=0; RUN_DID_UNPAUSE=0; BENCH_LAG_IDX=0
PREV_ROUNDS=""; NODE_STALL_COUNTS="{}"; STALL_POLLS=0; LAST_ADVANCE_TS=0
BENCH_ABORT_STALL_SECS=600
bench_prom_rounds() { printf '%s' "$CUR"; }
bench_rounds_advanced() { jq -cn --argjson a "$1" --argjson b "$2" '[$b | to_entries[] | select(.value > ($a[.key] // infinite)) | .key]'; }
save_log_first() { printf 'saved %s\n' "$1" >> "$SAVE_LOG"; }
record_abort() { printf '%s %s\n' "$1" "$2" >> "$ABORT_LOG"; }
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, ABORT_LOG=str(Path(directory) / "abort"),
                       SAVE_LOG=str(Path(directory) / "saved"))
            subprocess.run(["bash", "-c", shell + function + "\n" + body,
                            "watcher", str(BENCH)], env=env, check=True, capture_output=True)
            abort = Path(env["ABORT_LOG"])
            saved = Path(env["SAVE_LOG"])
            return (abort.read_text() if abort.exists() else "",
                    saved.read_text() if saved.exists() else "")

    def test_one_frozen_validator_while_peers_advance(self):
        abort, saved = self.run_watcher('''
CUR='{"peer":10,"victim":10,"observer":0}'; round_stall_check 1000 0
CUR='{"peer":11,"victim":10,"observer":0}'; round_stall_check 1240 0
CUR='{"peer":12,"victim":10,"observer":0}'; round_stall_check 1480 0
''')
        self.assertEqual(abort, "node-stalled victim\n")
        self.assertEqual(saved, "saved 1\n")

    def test_planned_outage_and_unknown_poll_do_not_count(self):
        abort, saved = self.run_watcher('''
RUN_DID_KILL=1
CUR='{"peer":10,"victim":10}'; round_stall_check 1000 0
CUR='{"peer":11,"victim":10}'; round_stall_check 1240 0
CUR='{"peer":12,"victim":10}'; round_stall_check 1480 0
RUN_DID_BACK=1
CUR='{"peer":13,"victim":10}'; round_stall_check 1720 0
CUR='{}'; round_stall_check 1960 0
CUR='{"peer":14,"victim":10}'; round_stall_check 2200 0
CUR='{"peer":15,"victim":10}'; round_stall_check 2440 0
''')
        self.assertEqual((abort, saved), ("", ""))


class SamplerTests(unittest.TestCase):
    def test_csv_upgrade_block_capture_and_minute_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            stubs = dict(hostname="echo validator", docker="exit 0",
                         curl="printf '%s' '{\"result\":\"0x2a\"}'",
                         ls="echo '64 2026-09-23T06:20:03 known.epochpack'")
            for name, body in stubs.items():
                executable = commands / name
                executable.write_text("#!/usr/bin/env bash\n" + body + "\n")
                executable.chmod(0o755)
            out = root / "output"
            out.mkdir()
            old_header = ("ts_unix,pid,rss_anon_kb,rss_file_kb,rss_total_kb,io_write_bytes,"
                          "io_read_bytes,psi_mem_some_avg10,psi_io_some_avg10,psi_cpu_some_avg10,"
                          "db_bytes,static_files_bytes,epochs_bytes,cache_bytes,epoch_bytes,"
                          "loadavg1,oom_count,root_used_pct")
            old_values = [str(i) for i in range(18)]
            csv_path = out / "validator.csv"
            csv_path.write_text(old_header + "\n" + ",".join(old_values) + "\n")
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                       SAMPLER_ONCE="1", SAMPLER_OUT_DIR=str(out),
                       SAMPLER_DATA_DIR=str(root / "data"), SAMPLER_STATUS_EVERY="0")
            for _ in range(2):
                subprocess.run(["bash", str(BENCH / "node-sampler.sh")], env=env,
                               check=True, capture_output=True)
            with csv_path.open() as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0][-1], "block")
            self.assertEqual(rows[1], old_values + [""])
            self.assertEqual([row[-1] for row in rows[2:]], ["42", "42"])
            self.assertTrue(all(len(row) == 19 for row in rows))
            inventory = (out / "validator.epochs.txt").read_text()
            self.assertIn("BENCH_EPOCH_FILES ts=", inventory)
            self.assertIn("known.epochpack", inventory)


class EvidenceTests(unittest.TestCase):
    def test_archive_bytes_preserved_and_invalid_stream_rejected(self):
        with tempfile.TemporaryDirectory(prefix="recovery evidence ") as directory:
            root = Path(directory)
            payload = root / "telcoin.journal"
            payload.write_text("actual service journal from the failed restart")
            fixture = root / "fixture.tgz"
            with tarfile.open(fixture, "w:gz") as archive:
                archive.add(payload, arcname="telcoin.journal")
            dest = root / "captured"
            dest.mkdir()
            script = '''
set -euo pipefail
source "$1/recovery-lib.sh"
BENCH_APPLY=1
tn_iap_ssh_stdin() { cat > "$REMOTE_COMMAND"; cat "$FIXTURE"; }
bench_pull_recovery_evidence victim zone "$3" "$2"
'''
            env = dict(os.environ, FIXTURE=str(fixture), REMOTE_COMMAND=str(root / "command"))
            subprocess.run(["bash", "-c", script, "capture", str(BENCH), str(dest), "123"],
                           env=env, check=True, capture_output=True)
            captured = list(dest.glob("*.tgz"))
            self.assertEqual(len(captured), 1)
            with tarfile.open(captured[0]) as archive:
                self.assertEqual(archive.extractfile("telcoin.journal").read(), payload.read_bytes())
            remote = (root / "command").read_text()
            subprocess.run(["bash", "-n", "-c", remote], check=True)
            self.assertIn("journalctl -u telcoin", remote)
            self.assertIn("csv epochs.txt", remote)
            fixture.write_text("truncated SSH stream")
            # Retry without SSH data, then prove the saved archive cannot vouch for a new VM.
            subprocess.run(["bash", "-c", script, "capture", str(BENCH), str(dest), "123"],
                           env=env, check=True, capture_output=True)
            result = subprocess.run(["bash", "-c", script, "capture", str(BENCH), str(dest), "124"],
                                    env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            captured[0].unlink()
            result = subprocess.run(["bash", "-c", script, "capture", str(BENCH), str(dest), "123"],
                                    env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(dest.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
