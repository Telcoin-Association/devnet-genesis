"""Boundary scheduling and fleet watchers with local RPC/command fixtures."""
import contextlib
import csv
import gzip
import importlib.util
import io
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
        for recorded in (encoded_epoch(epoch=7), encoded_epoch(height=0, epoch=8)):
            with mock.patch.object(schedule, "rpc", side_effect=[dict(number="0x50"), recorded]):
                with self.assertRaisesRegex(ValueError, "has not opened"):
                    schedule.snapshot("unused", 8)

    def test_refresh_uses_the_opened_epochs_start(self):
        # Planned from epoch 7 (opened 1000, 1200 s): the kill falls in epoch 8, projected to open at
        # 2200. Epoch 7's close waited for execution, so epoch 8 opened at 2237: the kill follows it.
        plan = schedule.schedule(dict(epoch=7, epoch_start_unix=1000, duration_secs=1200), 3000, 59, 300)
        self.assertEqual((plan["closing_epoch"], plan["kill_unix"]), (8, 3341))
        opened = dict(epoch=8, block_height=99, epoch_start_unix=2237, duration_secs=1200)
        fresh = schedule.refresh(opened, 59, 300)
        self.assertEqual((fresh["closing_epoch"], fresh["kill_unix"], fresh["boundary_unix"], fresh["restart_unix"],
                          fresh["seconds_before_close"], fresh["downtime_secs"]), (8, 3378, 3437, 3678, 59, 300))
        self.assertEqual((fresh["epoch_start_unix"], fresh["block_height"]), (2237, 99))
        # An epoch that opened on time re-plans the kill schedule() projected.
        self.assertEqual(schedule.refresh(dict(opened, epoch_start_unix=2200), 59, 300)["kill_unix"], plan["kill_unix"])
        for offset, downtime in ((0, 300), (1200, 1500), (59, 59)):
            with self.assertRaises(ValueError):
                schedule.refresh(opened, offset, downtime)

    def test_cli_epoch_read_refresh_form_and_schedule_defaults(self):
        def rpc(url, method, params):
            if method == "eth_call":
                return encoded_epoch(height=42, epoch=8, duration=1200)
            if params[0] == "latest":
                return dict(number="0x50")
            return dict(number=params[0], timestamp=hex(2237), hash="0xabc")

        def main(*argv):
            out, err, code = io.StringIO(), io.StringIO(), 0
            with mock.patch.object(schedule, "rpc", rpc), \
                    mock.patch("sys.argv", ["recovery-schedule.py", "--rpc-url", "unused"] + list(argv)), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    schedule.main()
                except SystemExit as stop:
                    code = stop.code
            return code, out.getvalue(), err.getvalue()

        # --epoch alone stays the bare read chaos_boundary_check asks for.
        code, out, _ = main("--epoch", "8")
        bare = json.loads(out)
        self.assertEqual((code, bare["epoch_start_unix"]), (0, 2237))
        self.assertNotIn("kill_unix", bare)
        code, out, _ = main("--epoch", "8", "--before-close", "59", "--downtime", "300")
        fresh = json.loads(out)
        self.assertEqual((code, fresh["closing_epoch"], fresh["kill_unix"], fresh["restart_unix"]), (0, 8, 3378, 3678))
        code, out, err = main("--epoch", "9", "--before-close", "59", "--downtime", "300")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("epoch 9 has not opened", err)
        code, out, err = main("--epoch", "8", "--before-close", "1200", "--downtime", "1500")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("kill offset must be within the epoch", err)
        # The schedule form keeps its defaults (59 s before the close, 300 s down).
        code, out, _ = main("--earliest-kill", "3000")
        plan = json.loads(out)
        self.assertEqual((code, plan["kill_unix"], plan["restart_unix"]), (0, 3378, 3678))


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


def blast_functions(*names):
    """The named functions of benchmark-blast.sh (a one-line function is its own line)."""
    lines = (BENCH / "benchmark-blast.sh").read_text().splitlines()
    out = []
    for name in names:
        start = next(i for i, line in enumerate(lines) if line.startswith(name + "() {"))
        end = start if lines[start].rstrip().endswith("}") else lines.index("}", start)
        out.extend(lines[start:end + 1])
    return "\n".join(out) + "\n"


def stage_script_block():
    source = (BENCH / "benchmark-blast.sh").read_text()
    return re.search(r"^CHAOS_STAGE_SCRIPT=\$\(cat <<'EOS'\n.*?^EOS\n\)$", source, re.M | re.S).group() + "\n"


CHAOS_PREAMBLE = r"""
set -euo pipefail
bench_now_unix() { date -u +%s; }
bench_now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
bench_iso_from_unix() { date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
bench_log() { printf '%s\n' "$*"; }
bench_warn() { printf 'WARN %s\n' "$*"; }
bench_manifest() { printf '%s' "$MANIFEST"; }
bench_manifest_jq() { local t; t="$(mktemp)"; jq "$@" "$MANIFEST" > "$t" && mv "$t" "$MANIFEST"; }
bench_manifest_note() { bench_manifest_jq --arg n "$1" '.notes += [$n]'; }
record_abort() { printf '%s\n' "$1" >> "$ABORT_LOG"; }
INSTANCE_NAMES=(bench-validator-05 bench-observer-11); ZONES=(zone-a zone-b)
BENCH_RESULTS_DIR="$WORK"; BENCH_NODE_LOG_DIR="$WORK/node-logs"
BENCH_CHAOS_STAGE_SECS=30; BENCH_CHAOS_GUARD_SECS=90; BENCH_CHAOS_SAVE_WAIT_SECS=60; BENCH_STALL_NOTE_SECS=60
"""

# The node's tools, as the staged script and the direct path call them (root via `sudo bash -s`).
NODE_STUBS = dict(
    docker='echo "docker $*" >> "$CALLS"\ncase "$1" in logs) printf "container line 1\\ncontainer line 2\\n" ;; '
           'kill) echo telcoin ;; esac\nexit 0',
    systemctl='echo "systemctl $*" >> "$CALLS"\ncase "$1" in is-active) echo inactive; exit 3 ;; esac',
    sudo='exec "$@"')


def run_chaos_shell(code, stubs=NODE_STUBS):
    """Run <code> after CHAOS_PREAMBLE; returns stdout, the manifest, aborts, calls and saved logs."""
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        manifest = work / "manifest.json"
        manifest.write_text(json.dumps(dict(chaos=[], notes=[])))
        commands = work / "bin"
        commands.mkdir()
        for name, body in stubs.items():
            executable = commands / name
            executable.write_text("#!/usr/bin/env bash\n" + body + "\n")
            executable.chmod(0o755)
        env = dict(os.environ, WORK=str(work), MANIFEST=str(manifest), ABORT_LOG=str(work / "abort"),
                   CALLS=str(work / "calls"), PATH=str(commands) + os.pathsep + os.environ["PATH"])
        result = subprocess.run(["bash", "-c", CHAOS_PREAMBLE + code], env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(f"shell failed rc={result.returncode}:\n{result.stdout}\n{result.stderr}")
        logs = work / "node-logs"
        saved = {f.name: gzip.decompress(f.read_bytes()).decode()
                 for f in sorted(logs.iterdir()) if not f.name.startswith(".")} if logs.is_dir() else {}
        script = work / "script.sh"
        return dict(out=result.stdout, manifest=json.loads(manifest.read_text()), saved=saved,
                    aborts=(work / "abort").read_text() if (work / "abort").exists() else "",
                    calls=(work / "calls").read_text() if (work / "calls").exists() else "",
                    script=script.read_text() if script.exists() else "")


def marker_time(out, mark):
    line = next(line for line in out.splitlines() if line.startswith("BENCH_CHAOS_" + mark + " "))
    return float(line.split()[-1])


class ChaosTimingTests(unittest.TestCase):
    STAGED = stage_script_block() + blast_functions(
        "chaos_mark", "record_chaos", "chaos_do", "chaos_direct_cmd", "chaos_stage_send",
        "chaos_save_report", "chaos_staged", "sleep_until")

    def test_staged_script_saves_the_log_alongside_and_begins_on_the_node_clock(self):
        run = run_chaos_shell(self.STAGED + r"""
tn_iap_ssh_stdin() { tee "$WORK/script.sh" | sudo bash -s; }
DUE=$(( $(date +%s) + 2 ))
echo "DUE $DUE"
chaos_stage_send 0 kill "$DUE" pre-kill
echo "RC $?"
""")
        out = run["out"]
        due = int(re.search(r"^DUE (\d+)$", out, re.M).group(1))
        begin = marker_time(out, "BEGIN")
        self.assertGreaterEqual(begin, due)
        self.assertLess(begin, due + 1)
        self.assertIn("BENCH_CHAOS_END node=bench-validator-05 rc=0 ", out)
        self.assertIn("RC 0", out)
        # The save starts before BEGIN, under bench_save_node_log's name; its outcome follows END
        # and says it had finished when the kill began.
        started = re.search(r"^BENCH_CHAOS_SAVE_STARTED (\S+)$", out, re.M)
        saved = re.search(r"^BENCH_CHAOS_SAVED (\S+) at_action=finished$", out, re.M)
        self.assertLess(started.start(), out.index("BENCH_CHAOS_BEGIN "))
        self.assertGreater(saved.start(), out.index("BENCH_CHAOS_END "))
        self.assertEqual(started.group(1), saved.group(1))
        (name, content), = run["saved"].items()
        self.assertRegex(name, r"^telcoin-pre-kill-\d{8}T\d{6}Z\.log\.gz$")
        self.assertTrue(saved.group(1).endswith("/node-logs/" + name))
        self.assertEqual(content, "container line 1\ncontainer line 2\n")
        calls = run["calls"].splitlines()
        self.assertLess(calls.index("docker logs telcoin"), calls.index("docker kill -s KILL telcoin"))
        self.assertIn("systemctl stop telcoin", calls)
        # What went over stdin: assignment lines, then the script; it parses as is, under macOS
        # /bin/bash 3.2 too (a bare `pattern)` inside $(...) does not).
        self.assertTrue(run["script"].startswith(
            "CHAOS_NODE=bench-validator-05\nCHAOS_ACTION=kill\nCHAOS_DUE=%d\nCHAOS_SAVE=pre-kill\n" % due))
        self.assertIn("\nCHAOS_MAX_WAIT=90\nCHAOS_SAVE_WAIT=60\n", run["script"])
        subprocess.run(["bash", "-n", "-c", run["script"]], check=True)
        if Path("/bin/bash").exists():
            subprocess.run(["/bin/bash", "-n", "-c", run["script"]], check=True)

    # `docker logs` that takes SLOW seconds, longer than the time to the due time (r20261007-0316:
    # a 70 s save put the kill 41.8 s late).
    SLOW = 4
    SLOW_STUBS = dict(NODE_STUBS, docker='echo "docker $*" >> "$CALLS"\ncase "$1" in '
                      'logs) sleep %d; printf "container line 1\\ncontainer line 2\\n"; echo "docker logs done" >> "$CALLS" ;; '
                      'kill) echo telcoin ;; esac\nexit 0' % SLOW)

    def test_a_slow_save_does_not_delay_the_kill(self):
        run = run_chaos_shell(self.STAGED + r"""
tn_iap_ssh_stdin() { sudo bash -s; }
DUE=$(( $(date +%s) + 2 ))
echo "DUE $DUE"
chaos_staged 0 kill "$DUE" pre-kill "docker kill -s KILL telcoin" "kill note"
echo "RC $CHAOS_RC"
""", stubs=self.SLOW_STUBS)
        out = run["out"]
        due = int(re.search(r"^DUE (\d+)$", out, re.M).group(1))
        # On time: the wait polls every 0.2 s (live: late <= 0.2 s); 0.5 s allows a busy test host.
        entry, = run["manifest"]["chaos"]
        self.assertEqual((entry["staged"], entry["rc"], entry["planned_unix"]), (True, 0, due))
        self.assertGreaterEqual(entry["begin_unix"], due)
        self.assertLess(entry["late_secs"], 0.5)
        # The kill ran while the save was still reading; the save then finished, complete, and
        # its marker says it was running when the kill began.
        calls = run["calls"].splitlines()
        self.assertLess(calls.index("docker kill -s KILL telcoin"), calls.index("docker logs done"))
        self.assertRegex(out, r"(?m)^ *BENCH_CHAOS_SAVED \S+/node-logs/telcoin-pre-kill-\S+ at_action=running$")
        self.assertIn("(running when the kill began)", out)
        self.assertEqual(list(run["saved"].values()), ["container line 1\ncontainer line 2\n"])
        self.assertIn("RC 0", out)
        self.assertEqual(run["manifest"]["notes"], [])

    def test_a_save_longer_than_the_wait_is_left_to_finish_on_the_node(self):
        run = run_chaos_shell(self.STAGED + r"""
tn_iap_ssh_stdin() { sudo bash -s; }
BENCH_CHAOS_SAVE_WAIT_SECS=0
DUE=$(( $(date +%s) + 1 ))
chaos_staged 0 kill "$DUE" pre-kill "docker kill -s KILL telcoin" "kill note"
echo "RETURNED $(date +%s) RC $CHAOS_RC"
for _ in $(seq 1 100); do
    ls "$WORK/node-logs"/telcoin-pre-kill-* >/dev/null 2>&1 && { echo "COMPLETED LATER $(date +%s)"; break; }
    sleep 0.1
done
""", stubs=self.SLOW_STUBS)
        out = run["out"]
        self.assertIn("RC 0", out)
        self.assertRegex(out, r"(?m)^ *BENCH_CHAOS_SAVE_RUNNING \S+/node-logs/telcoin-pre-kill-\S+ at_action=running$")
        self.assertNotIn("BENCH_CHAOS_SAVED ", out)
        self.assertIn("still being saved on the node when the session ended", out)
        note, = run["manifest"]["notes"]
        self.assertTrue(note.startswith("log-save-unconfirmed: bench-validator-05 pre-kill at "))
        # The session ended before the save did; the save then completed on its own.
        returned = int(re.search(r"^RETURNED (\d+)", out, re.M).group(1))
        later = int(re.search(r"^COMPLETED LATER (\d+)$", out, re.M).group(1))
        self.assertGreaterEqual(later, returned)
        self.assertEqual(list(run["saved"].values()), ["container line 1\ncontainer line 2\n"])

    def test_session_failing_before_begin_falls_back_to_the_direct_path(self):
        run = run_chaos_shell(self.STAGED + r"""
tn_iap_ssh_stdin() { cat > /dev/null; return 255; }      # IAP refused the session
tn_iap_ssh() { bash -c "$3"; }                           # the direct --command, run here
save_log_first() { echo "save_log_first $*" >> "$CALLS"; }
DUE=$(( $(date +%s) - 1 ))
echo "DUE $DUE"
chaos_staged 0 kill "$DUE" pre-kill "docker kill -s KILL telcoin" "kill note"
echo "RC $CHAOS_RC"
chaos_stage_send 0 "rm -rf" "$DUE" "" || echo "bad action rc $?"
""")
        due = int(re.search(r"^DUE (\d+)$", run["out"], re.M).group(1))
        self.assertIn("failed before it began (rc=255)", run["out"])
        self.assertIn("RC 0", run["out"])
        self.assertIn("bad action rc 2", run["out"])
        # No save of its own: it would delay the action. The note says the log was not saved.
        calls = run["calls"].splitlines()
        self.assertNotIn("save_log_first 0 pre-kill", calls)
        self.assertEqual(calls[0], "docker kill -s KILL telcoin")
        self.assertIn("container log not saved (pre-kill)", run["out"])
        note, = run["manifest"]["notes"]
        self.assertTrue(note.startswith("log-save-failed: bench-validator-05 pre-kill at "))
        entry, = run["manifest"]["chaos"]
        self.assertEqual((entry["staged"], entry["rc"], entry["planned_unix"], entry["note"]),
                         (False, 0, due, "kill note"))
        self.assertGreaterEqual(entry["begin_unix"], due)
        self.assertGreaterEqual(entry["late_secs"], 0)

    def test_due_time_beyond_the_wait_limit_is_refused_before_saving(self):
        run = run_chaos_shell(self.STAGED + r"""
tn_iap_ssh_stdin() { sudo bash -s; }
tn_iap_ssh() { bash -c "$3"; }
save_log_first() { echo "save_log_first $*" >> "$CALLS"; }
sleep() { echo "sleep $*" >> "$CALLS"; }                 # the fallback waits for the due time
chaos_staged 1 restart "$(( $(date +%s) + 200 ))" pre-restart "systemctl restart telcoin" "observer restart"
""")
        self.assertIn("BENCH_CHAOS_STAGE_FAIL due in", run["out"])
        self.assertNotIn("BENCH_CHAOS_SAVE_STARTED", run["out"])
        calls = run["calls"]
        self.assertNotIn("save_log_first", calls)
        self.assertNotIn("docker logs", calls)
        self.assertRegex(calls, r"(?m)^sleep (19\d|200)$")
        self.assertIn("systemctl restart telcoin", calls)
        self.assertEqual(run["saved"], {})
        self.assertFalse(run["manifest"]["chaos"][0]["staged"])

    def test_poll_deferred_when_a_chaos_action_is_due_within_the_guard(self):
        run = run_chaos_shell(blast_functions("next_action_due", "poll_deferred") + r'''
chaos_on=1; ABORTED=""; RUN_DID_KILL=0; RUN_DID_BACK=0; RUN_DID_OBS=0
t_kill=1030; t_back=1330; t_obs=1630; next_poll=1000
poll_deferred 1000 && echo "deferred, next poll $next_poll"
t_kill=1200; next_poll=1000
poll_deferred 1000 || echo "poll runs, next poll $next_poll"
ABORTED=quorum-lost; t_kill=1030; t_obs=1050
poll_deferred 1000 || echo "poll runs after an abort"
RUN_DID_KILL=1; t_back=1050
poll_deferred 1000 && echo "deferred, next poll $next_poll"
chaos_on=0
poll_deferred 1000 || echo "poll runs without chaos"
''')
        self.assertEqual(run["out"].splitlines(), [
            "    poll deferred: kill due in 30s", "deferred, next poll 1030",
            "poll runs, next poll 1000", "poll runs after an abort",
            "    poll deferred: restart due in 50s", "deferred, next poll 1050",
            "poll runs without chaos"])

    def test_overdue_target_sleeps_one_second(self):
        run = run_chaos_shell(blast_functions("sleep_until") + r'''
bench_now_unix() { echo 1000; }
sleep() { echo "sleep $*"; }
sleep_until 990; sleep_until 1000; sleep_until 1042; sleep_until 990 0
''')
        self.assertEqual(run["out"].splitlines(), ["sleep 1", "sleep 1", "sleep 42"])

    def test_record_chaos_reads_node_side_begin_and_end(self):
        run = run_chaos_shell(blast_functions("chaos_mark", "record_chaos") + r'''
OUT=$'BENCH_CHAOS_SAVED /var/lib/bench-logs/telcoin-pre-kill-x.log.gz\nBENCH_CHAOS_BEGIN node=bench-validator-05 1791252578.204\r\ntelcoin\ninactive\nBENCH_CHAOS_END node=bench-validator-05 rc=0 1791252578.611'
record_chaos bench-validator-05 "docker kill -s KILL telcoin" "kill" 255 "$OUT" 1791252578 true '{"planned":{"closing_epoch":2}}'
echo "RC $CHAOS_RC BEGIN $CHAOS_BEGIN"
OUT=$'BENCH_CHAOS_BEGIN node=bench-observer-11 1791253201.827389593\nactive\nBENCH_CHAOS_END node=bench-observer-11 rc=0 1791253204.190845440'
record_chaos bench-observer-11 "systemctl restart telcoin" "observer restart" 0 "$OUT" 1791253200 false
record_chaos bench-validator-05 "systemctl start telcoin" "owed restart" 255 ""
echo "RC $CHAOS_RC"
''')
        self.assertIn("RC 0 BEGIN 1791252578.204", run["out"])   # END rc=0 outranks the ssh rc 255
        self.assertIn("RC 255", run["out"])
        kill, observer, owed = run["manifest"]["chaos"]
        self.assertEqual((kill["ts"], kill["begin_unix"], kill["end_unix"], kill["late_secs"], kill["staged"],
                          kill["rc"], kill["planned"]),
                         ("2026-10-06T02:09:38Z", 1791252578.204, 1791252578.611, 0.204, True, 0,
                          dict(closing_epoch=2)))
        self.assertEqual((observer["ts"], observer["begin_unix"], observer["late_secs"], observer["staged"]),
                         ("2026-10-06T02:20:01Z", 1791253201.827, 1.827, False))
        self.assertAlmostEqual(observer["end_unix"], 1791253204.19)
        self.assertEqual((owed["begin_unix"], owed["end_unix"], owed["late_secs"], owed["planned_unix"], owed["rc"]),
                         (None, None, None, None, 255))

    def test_kill_note_makes_no_boundary_claim(self):
        source = (BENCH / "benchmark-blast.sh").read_text()
        self.assertNotIn("across the epoch boundary", source)
        kill = re.search(r'chaos_staged "\$\{CHAOS_KILL_IDX\}" kill .*?\n\s+"(.*?)"', source, re.S)
        self.assertTrue(kill.group(1).startswith("systemctl stop holds it down"))

    def boundary(self, body, schedule='{"closing_epoch":2,"boundary_unix":1059,"restart_unix":1300}'):
        return run_chaos_shell(blast_functions("chaos_boundary_check") + r'''
bench_tunnel_up() { :; }
DIR=/unused; RPC_URL=http://unused
recovery_schedule='%s'
RUN_DID_BACK=1; BOUNDARY_DONE=0; KILL_ENTRY=0; KILL_BEGIN=1000.250; BACK_BEGIN=1300.100
python3() {
    echo "python3 $*" >> "$CALLS"
    [ -n "$EPOCH_START" ] || { echo "cannot measure recovery schedule: epoch 3 has not opened" >&2; return 1; }
    printf '{"epoch":3,"block_height":99,"epoch_start_unix":%%s}\n' "$EPOCH_START"
}
bench_manifest_jq '.chaos = [{"action": "docker kill -s KILL telcoin"}]'
''' % schedule + body)

    def test_boundary_verdict_crossed_did_not_cross_and_not_opened(self):
        for start, crossed in ((1059, True), (1400, False), (999, False)):
            run = self.boundary("EPOCH_START=%d; chaos_boundary_check; chaos_boundary_check\n" % start)
            kill = run["manifest"]["chaos"][0]
            self.assertEqual((kill["crossed_boundary"], kill["boundary_unix"]), (crossed, start))
            self.assertEqual(run["manifest"]["chaos_boundary"]["epoch_start_unix"], start)
            note, = run["manifest"]["notes"]
            self.assertIn("the outage %s the boundary" % ("crossed" if crossed else "did not cross"), note)
            self.assertIn("1970-01-01T00:16:40Z", note)                      # the kill's node-side begin
            self.assertEqual(run["calls"].count("--epoch 3"), 1)               # recorded once, not re-asked
        # Not opened yet: asked again at the next poll (F2), until it opens or the watch ends.
        run = self.boundary('EPOCH_START=""; chaos_boundary_check; EPOCH_START=1059; chaos_boundary_check\n')
        self.assertEqual(run["calls"].count("--epoch 3"), 2)
        self.assertTrue(run["manifest"]["chaos"][0]["crossed_boundary"])
        run = self.boundary('EPOCH_START=""; chaos_boundary_check; chaos_boundary_check final\n')
        self.assertIsNone(run["manifest"]["chaos"][0]["crossed_boundary"])
        self.assertIn("epoch 3 not opened by the end of the watch", run["manifest"]["notes"][0])
        # Mixed timing has no boundary: nothing is asked or recorded.
        run = self.boundary("EPOCH_START=1059; chaos_boundary_check final\n", schedule="")
        self.assertEqual((run["calls"], run["manifest"]["chaos"][0], run["manifest"]["notes"]),
                         ("", {"action": "docker kill -s KILL telcoin"}, []))

    # A fake gcloud for the chaos sessions: it logs each session's shape (staged: `sudo bash -s` with
    # the script on stdin; direct: the action in --command), fails the first FAIL_FIRST with ssh rc
    # 255 (a transport fault, which devnet-lib retries) and runs the rest here as the node would.
    GCLOUD = r'''cmd=""; for a in "$@"; do case "$a" in --command=*) cmd="${a#--command=}" ;; esac; done
n=$(( $(grep -c "^session " "$CALLS" 2>/dev/null) + 1 ))
if [ "$cmd" = "sudo bash -s" ]; then echo "session staged" >> "$CALLS"; else echo "session direct" >> "$CALLS"; fi
if [ "$n" -le "$FAIL_FIRST" ]; then cat > /dev/null; echo "ssh: connect to host: Connection timed out" >&2; exit 255; fi
exec bash -c "$cmd"'''

    def chaos_sessions(self, fail_first):
        """The kill through devnet-lib's real IAP wrappers; the sessions the fake gcloud saw."""
        run = run_chaos_shell(self.STAGED + r'''
PROJECT_ID=bench-test; TN_SSH_TRANSPORT=iap; CONFIG_FILE=/dev/null
source "@LIB@"
# devnet-lib's default (2 more attempts on a transport fault) is in force: these tests count the
# sessions to prove the chaos sessions pin TN_IAP_RETRIES=0 themselves, so it is not pinned here.
TN_IAP_RETRIES=2; TN_IAP_RETRY_SECS=0; export FAIL_FIRST=@FAIL@
DUE=$(( $(date +%s) - 1 ))
chaos_staged 0 kill "$DUE" pre-kill "docker kill -s KILL telcoin" "kill note"
echo "RC $CHAOS_RC"
'''.replace("@LIB@", str(BENCH.parent / "devnet-lib.sh")).replace("@FAIL@", str(fail_first)),
            stubs=dict(NODE_STUBS, gcloud=self.GCLOUD))
        sessions = [line.split()[1] for line in run["calls"].splitlines() if line.startswith("session ")]
        return run, sessions

    def test_chaos_sessions_never_retry_the_transport(self):
        # The staged session drops before BEGIN: no second staged session (a re-sent script could
        # fire twice, or late); the staged path's own fallback, the direct path, is the retry.
        run, sessions = self.chaos_sessions(1)
        self.assertEqual(sessions, ["staged", "direct"])
        self.assertIn("failed before it began (rc=255)", run["out"])
        self.assertIn("RC 0", run["out"])
        entry, = run["manifest"]["chaos"]
        self.assertEqual((entry["staged"], entry["rc"]), (False, 0))
        self.assertIn("docker kill -s KILL telcoin", run["calls"])
        # The direct session drops too: recorded as failed, not sent again; the caller owns that retry.
        run, sessions = self.chaos_sessions(2)
        self.assertEqual(sessions, ["staged", "direct"])
        self.assertIn("RC 255", run["out"])
        entry, = run["manifest"]["chaos"]
        self.assertEqual((entry["staged"], entry["rc"], entry["begin_unix"]), (False, 255, None))
        self.assertNotIn("docker kill", run["calls"])

    # recovery-schedule.py as the refresh runs it (under perl's alarm, so a file, not a function): logs
    # its argv, sleeps RS_SLEEP, refuses until EPOCH_START is set, then answers with the real refresh().
    FAKE_RECOVERY_SCHEDULE = r"""
import importlib.util, json, os, sys, time
with open(os.environ["CALLS"], "a") as calls:
    calls.write("recovery-schedule.py " + " ".join(sys.argv[1:]) + "\n")
time.sleep(float(os.environ["RS_SLEEP"]))
if not os.environ["EPOCH_START"]:
    sys.exit("cannot measure recovery schedule: epoch 8 has not opened")
spec = importlib.util.spec_from_file_location("rs", os.environ["RS_REAL"])
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
opt = dict(zip(sys.argv[1::2], sys.argv[2::2]))
info = dict(epoch=8, block_height=99, duration_secs=1200, epoch_start_unix=int(os.environ["EPOCH_START"]))
print(json.dumps(rs.refresh(info, int(opt["--before-close"]), int(opt["--downtime"]))))
"""
    REFRESH = blast_functions("chaos_schedule_refresh", "next_action_due") + r'''
bench_now_unix() { echo "$NOW"; }
bench_tunnel_pidfile() { printf '%s' "$WORK/tunnel.pid"; }
echo "$$" > "$WORK/tunnel.pid"                   # the tunnel is up
DIR="$WORK"; RPC_URL=http://unused
cat > "$DIR/recovery-schedule.py" <<'EOF'
@FAKE@
EOF
export EPOCH_START="" RS_SLEEP=0 RS_REAL="@REAL@"
chaos_on=1; RUN_DID_BACK=0; RUN_DID_OBS=0
PLAN='{"epoch":7,"duration_secs":1200,"closing_epoch":8,"kill_unix":3341,"boundary_unix":3400,"restart_unix":3641}'
recovery_schedule="$PLAN"; ABORTED=""; RUN_DID_KILL=0; SCHEDULE_REFRESHED=0
BENCH_CHAOS_BEFORE_CLOSE_SECS=59; BENCH_CHAOS_DOWNTIME_SECS=300; BENCH_CHAOS_OBS_AFTER_BACK_SECS=300
t_kill=3341; t_back=3641; t_obs=3941
kill_extra='{"planned":{"closing_epoch":8,"boundary_unix":3400,"restart_unix":3641}}'
show() { echo "T $t_kill $t_back $t_obs R $SCHEDULE_REFRESHED X $kill_extra"; }
bench_manifest_jq '.chaos_schedule = {"kill_unix": 3341}'
'''.replace("@FAKE@", FAKE_RECOVERY_SCHEDULE.strip()).replace("@REAL@", str(BENCH / "recovery-schedule.py"))
    ORIGINAL = 'T 3341 3641 3941 R 0 X {"planned":{"closing_epoch":8,"boundary_unix":3400,"restart_unix":3641}}'
    REFRESHED = 'T 3378 3678 3978 R 1 X {"planned":{"closing_epoch":8,"boundary_unix":3437,"restart_unix":3678}}'

    def test_schedule_refresh_moves_the_kill_once_the_closing_epoch_has_opened(self):
        run = run_chaos_shell(self.REFRESH + r'''
NOW=2100; chaos_schedule_refresh; show           # before epoch 8's projected start (2200): not asked
NOW=2300; chaos_schedule_refresh; show           # asked: not opened yet
EPOCH_START=2237; NOW=2540; chaos_schedule_refresh; show     # opened 37 s late
NOW=2800; chaos_schedule_refresh; show           # re-planned once: not asked again
''')
        self.assertEqual(run["out"].splitlines(), [
            self.ORIGINAL,
            "    chaos schedule: closing epoch 8 not opened (or not readable) yet — asked again at the next poll",
            self.ORIGINAL,
            "    chaos schedule: epoch 8 opened 1970-01-01T00:37:17Z; kill moved 37s to 1970-01-01T00:56:18Z, "
            "restart 1970-01-01T01:01:18Z, observer restart 1970-01-01T01:06:18Z",
            self.REFRESHED, self.REFRESHED])
        self.assertEqual(run["calls"].splitlines(),
                         ["recovery-schedule.py --rpc-url http://unused --epoch 8 --before-close 59 --downtime 300"] * 2)
        refresh = run["manifest"]["chaos_schedule_refresh"]
        self.assertRegex(refresh.pop("ts"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(refresh, dict(planned_kill_unix=3341, kill_unix=3378, drift_secs=37, closing_epoch=8,
                                       epoch_start_unix=2237))
        self.assertEqual(run["manifest"]["chaos_schedule"], dict(kill_unix=3341))   # the first plan stays
        # do_run asks at the start of every poll, before the poll's reads.
        source = (BENCH / "benchmark-blast.sh").read_text()
        self.assertRegex(source, r'bench_log "poll: [^"]*"\n\s+chaos_schedule_refresh\n\s+if poll_blasters; then')

    def test_schedule_refresh_skipped_near_the_kill_after_it_and_without_epoch_timing(self):
        run = run_chaos_shell(self.REFRESH + r'''
EPOCH_START=2237
NOW=3221; chaos_schedule_refresh                 # 120 s before the kill: within GUARD 90 + STAGE 30
NOW=2540
BENCH_CHAOS_REFRESH_SCHEDULE=0; chaos_schedule_refresh
BENCH_CHAOS_REFRESH_SCHEDULE=1; RUN_DID_KILL=1; chaos_schedule_refresh
RUN_DID_KILL=0; ABORTED=quorum-lost; chaos_schedule_refresh
ABORTED=""; recovery_schedule=""; chaos_schedule_refresh       # mixed timing
show
recovery_schedule="$PLAN"; NOW=3220; chaos_schedule_refresh >/dev/null; show   # 121 s: still in time
''')
        self.assertEqual(run["out"].splitlines(), [self.ORIGINAL, self.REFRESHED])
        self.assertEqual(len(run["calls"].splitlines()), 1)
        self.assertEqual(run["manifest"]["chaos_schedule_refresh"]["drift_secs"], 37)

    def test_schedule_refresh_is_bounded_and_needs_the_tunnel_up(self):
        # A registry read that hangs past the bound, then a tunnel down (no pid file, then a dead
        # pid): the poll goes on, nothing is recorded, the kill stays due at the first plan's time;
        # the next poll that finds the tunnel up and an answer in time re-plans it.
        run = run_chaos_shell(self.REFRESH + r'''
BENCH_CHAOS_REFRESH_TIMEOUT_SECS=1; EPOCH_START=2237; NOW=2540; RS_SLEEP=5
t0=$(date +%s); chaos_schedule_refresh; echo "ELAPSED $(( $(date +%s) - t0 ))"; show
echo "RECORDED $(jq -c '.chaos_schedule_refresh // "none"' "$MANIFEST")"
echo "DUE $(next_action_due)"
RS_SLEEP=0
rm "$WORK/tunnel.pid"; chaos_schedule_refresh; show
( exit 0 ) & dead=$!; wait "$dead"; echo "$dead" > "$WORK/tunnel.pid"; chaos_schedule_refresh; show
echo "$$" > "$WORK/tunnel.pid"; NOW=2780; chaos_schedule_refresh; show
''')
        lines = run["out"].splitlines()
        elapsed = int(lines[1].split()[1])
        self.assertLess(elapsed, 4)                      # the alarm, not the 5 s hang
        del lines[1]
        self.assertEqual(lines, [
            "    chaos schedule: no answer from the registry within 1s — not refreshed at this poll",
            self.ORIGINAL, 'RECORDED "none"', "DUE 3341 kill",
            "    chaos schedule: the RPC tunnel is not up — not refreshed at this poll", self.ORIGINAL,
            "    chaos schedule: the RPC tunnel is not up — not refreshed at this poll", self.ORIGINAL,
            "    chaos schedule: epoch 8 opened 1970-01-01T00:37:17Z; kill moved 37s to 1970-01-01T00:56:18Z, "
            "restart 1970-01-01T01:01:18Z, observer restart 1970-01-01T01:06:18Z",
            self.REFRESHED])
        self.assertEqual(len(run["calls"].splitlines()), 2)   # the hung read and the last one
        self.assertEqual(run["manifest"]["chaos_schedule_refresh"]["kill_unix"], 3378)


class CommitFlatTests(unittest.TestCase):
    FUNCTIONS = blast_functions("status_samples", "status_collect", "fleet_round_at", "round_text",
                                "commit_flat_check", "commit_flat_judge", "commit_flat_close",
                                "commit_stall_record", "commit_flat_flush")
    STATE = r'''
STATUS_SEEN=(); POLL_SAMPLES=""
FLAT_BLOCK=""; FLAT_SINCE=0; FLAT_UNTIL=0; FLAT_STATE=""; FLAT_ROUND=""; FLAT_ROUNDS_UP=""
STALL_WIN_START=1000; STALL_MIXED_END=5000; BENCH_STALL_NOTE_MAX_ROUNDS=4
'''
    # Fleet-max round (epoch 3) at a time, as Prometheus would answer with `offset`.
    ROUNDS_FLAT = r'''
fleet_round_at() {   # 1 round/s, flat from 1150 (blocks went flat at 1120: the stall's leading edge)
    echo "fleet_round_at $1" >> "$CALLS"
    if [ "$1" -lt 1150 ]; then echo $(( 300000000 + $1 )); else echo 300001150; fi
}
'''
    ROUNDS_ADVANCING = r'''
fleet_round_at() { echo $(( 300000000 + $1 )); }   # 1 round/s throughout: an idle chain
'''

    def flat_lines(self, out):
        return [line for line in out.splitlines() if "commits flat" in line or "idle:" in line]

    def test_blocks_and_rounds_flat_is_a_stall_noted_once_without_abort(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + self.ROUNDS_FLAT + r'''
commit_flat_check $'400 5\n520 5\n640 5\n760 5'          # preamble: flat, before the mixed phase
commit_flat_check $'1000 10\n1120 15\n1240 15'           # one poll ...
commit_flat_check $'1360 15\n1480 20'                    # ... and the next
commit_flat_flush
''')
        self.assertEqual(self.flat_lines(run["out"]), [
            "    ⚠ commits flat at block 15 since 1970-01-01T00:18:40Z (120s; rounds +0 in its last 60s, "
            "at 1150 (epoch 3)) — note only"])
        self.assertEqual(run["manifest"]["commit_stalls"], [dict(
            start="1970-01-01T00:18:40Z", end="1970-01-01T00:24:40Z", secs=360, block=15,
            round_start=300001120, round_end=300001150, source="watch")])
        note, = run["manifest"]["notes"]
        self.assertIn("stayed at 15", note)
        self.assertIn("rounds +0 in its last 60s", note)
        self.assertEqual(run["aborts"], "")
        self.assertNotIn("fleet_round_at 760", run["calls"])     # the preamble is never judged

    def test_blocks_flat_while_rounds_advance_is_idle_not_recorded(self):
        # r20261006-0458: the generators finished before the planned mixed end; blocks sat still for
        # 213 s while rounds kept rising, then an epoch close moved the block after cooldown.
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + self.ROUNDS_ADVANCING + r'''
commit_flat_check $'1000 10\n1120 15\n1240 15'
commit_flat_check $'1360 15\n1480 15'
commit_flat_check $'5300 16'
commit_flat_flush
''')
        self.assertEqual(self.flat_lines(run["out"]), [
            "    idle: blocks flat at 15 since 1970-01-01T00:18:40Z (120s), consensus rounds advancing "
            "(+60 in 60s) — not a stall"])
        self.assertNotIn("commit_stalls", run["manifest"])
        self.assertEqual((run["manifest"]["notes"], run["aborts"]), ([], ""))

    def test_close_after_cooldown_takes_end_and_round_from_the_advance(self):
        # Judged a stall at one poll, still flat at the next, closed by a sample the poll after the
        # window: end and round_end come from that sample, and nothing stays open.
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + r'''
fleet_round_at() { if [ "$1" -lt 1150 ]; then echo $(( 300000000 + $1 )); elif [ "$1" -lt 5600 ]; then echo 300001150; else echo 400000003; fi; }
STALL_MIXED_END=1500
commit_flat_check $'1000 10\n1120 15\n1240 15'
commit_flat_check $'1360 15\n1480 15\n1600 15'
commit_flat_check $'5650 16'
commit_flat_flush
''')
        stall, = run["manifest"]["commit_stalls"]
        self.assertEqual((stall["end"], stall["secs"], stall["round_start"], stall["round_end"]),
                         ("1970-01-01T01:34:10Z", 4530, 300001120, 400000003))
        self.assertNotIn("open", stall)
        self.assertEqual(len(self.flat_lines(run["out"])), 1)

    def test_stall_still_flat_at_the_end_of_the_watch_is_open(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + self.ROUNDS_FLAT + r'''
commit_flat_check $'1000 10\n1120 15\n1240 15\n1360 15'
commit_flat_flush
''')
        stall, = run["manifest"]["commit_stalls"]
        self.assertEqual((stall["end"], stall["secs"], stall["round_end"], stall["open"]),
                         ("1970-01-01T00:22:40Z", 240, 300001150, True))

    def test_cooldown_drain_ignored(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + self.ROUNDS_FLAT + r'''
STALL_MIXED_END=1100
commit_flat_check $'1000 10\n1120 15\n1240 15\n1360 15\n1480 20'   # starts after the mixed phase
commit_flat_flush
''')
        self.assertEqual(self.flat_lines(run["out"]), [])
        self.assertNotIn("commit_stalls", run["manifest"])

    def test_rounds_unknown_judged_again_at_the_next_poll(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + r'''
fleet_round_at() { [ -f "$WORK/prom-up" ] || return 0; echo 300001150; }
commit_flat_check $'1000 10\n1120 15\n1240 15'
touch "$WORK/prom-up"
commit_flat_check $'1360 15'
commit_flat_flush
''')
        lines = run["out"].splitlines()
        self.assertIn("    blocks flat at 15 since 1970-01-01T00:18:40Z (120s); consensus rounds unknown — "
                      "judged again at the next poll", lines)
        self.assertEqual(len(run["manifest"]["commit_stalls"]), 1)

    def test_fleet_round_at_reads_prometheus_with_an_offset(self):
        run = run_chaos_shell(self.FUNCTIONS + r'''
BENCH_PROM_NETWORK_LABEL=bench
bench_now_unix() { echo 2000; }
bench_prom_query() { printf '%s\n' "$1" >> "$CALLS"; printf '{"status":"success","data":{"result":[{"value":[2000,"300000123"]}]}}'; }
echo "AT $(fleet_round_at 1880) NOW $(fleet_round_at 2000)"
bench_prom_query() { return 1; }
echo "DOWN <$(fleet_round_at 1880)>"
''')
        self.assertIn("AT 300000123 NOW 300000123", run["out"])
        self.assertIn("DOWN <>", run["out"])
        past, now = run["calls"].splitlines()
        self.assertEqual(past, 'max(max by (node) (tn_epoch_current{network="bench"} offset 120s) * 100000000 '
                               '+ max by (node) (tn_primary_round{network="bench"} offset 120s))')
        self.assertNotIn("offset", now)

    def test_status_samples_since_the_last_poll(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + r'''
LINES=$'[ 12.3] bench-node-sampler.sh[812]: BENCH_STATUS host=v1 ts=1000 root_used_pct=6 fatal_db=0 block=10 rss_total_kb=1\r\nBENCH_STATUS host=v1 ts=1120 root_used_pct=6 fatal_db=0 block=15 rss_total_kb=1\r'
status_collect 0 "$LINES"; status_collect 0 "$LINES"     # the second read finds nothing new
status_collect 1 $'BENCH_STATUS host=v2 ts=1100 root_used_pct=6 fatal_db=0 block= rss_total_kb=1'
printf 'SAMPLES<%s>\n' "$POLL_SAMPLES"; echo "SEEN ${STATUS_SEEN[0]} ${STATUS_SEEN[1]}"
''')
        self.assertIn("SAMPLES<1000 10\n1120 15\n1100 \n>", run["out"])
        self.assertIn("SEEN 1120 1100", run["out"])


class BenchObsTests(unittest.TestCase):
    """The run's metrics live on bench-obs (the bench's own obs VM), never on obs-devnet."""

    SOURCE = (BENCH / "benchmark-blast.sh").read_text()

    def test_obs_memory_abort_records_the_bench_obs_instance(self):
        # The poll's obs-memory block, run as it stands in do_run.
        block = re.search(r'^ +local mem; mem="\$\(bench_obs_mem_pct \|\| true\)"\n.*?^ +fi\n',
                          self.SOURCE, re.M | re.S).group()
        run = run_chaos_shell(r'''
BENCH_OBS_INSTANCE=bench-obs-7; BENCH_ABORT_OBS_MEM_PCT=85; MEM=""
bench_obs_mem_pct() { printf '%s' "$MEM"; }
record_abort() { printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$ABORT_LOG"; }
obs_memory() {
''' + block + r'''
}
obs_memory; MEM=85; obs_memory; MEM=91.5; obs_memory
''')
        self.assertEqual(run["out"].splitlines(), ["    bench-obs-7 memory: n/a%", "    bench-obs-7 memory: 85%",
                                                   "    bench-obs-7 memory: 91.5%"])
        self.assertEqual(run["aborts"], "obs-memory|bench-obs-7|bench-obs-7 memory 91.5% > 85%\n")
        self.assertNotIn("obs-devnet", self.SOURCE)
        self.assertNotIn("OBS_INSTANCE_NAME", self.SOURCE)

    def test_run_requires_bench_obs_before_the_chaos_schedule_and_every_prometheus_read(self):
        body = blast_functions("do_run")
        # At the function's own level (not inside the chaos or epoch branch), apply mode only, fatal.
        guard = re.search(r'\n    if \[ "\$\{BENCH_APPLY\}" = "1" \]; then\n'
                          r'        bench_obs_require \|\| bench_die "[^"]+"\n    fi\n', body)
        self.assertIsNotNone(guard)
        self.assertEqual(body.count("bench_obs_require"), 1)
        at = guard.start()
        for later in ('if [ "${chaos_on}" = "1" ]; then', 'case "${BENCH_CHAOS_TIMING}" in',
                      'bench_tunnel_up || bench_die', "trap on_run_exit EXIT", "round_stall_check",
                      "node_health_check", "commit_flat_check"):
            self.assertLess(at, body.index(later), later)


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
