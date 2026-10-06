"""Boundary scheduling and fleet watchers with local RPC/command fixtures."""
import csv
import gzip
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
        for recorded in (encoded_epoch(epoch=7), encoded_epoch(height=0, epoch=8)):
            with mock.patch.object(schedule, "rpc", side_effect=[dict(number="0x50"), recorded]):
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
BENCH_CHAOS_STAGE_SECS=30; BENCH_CHAOS_GUARD_SECS=90; BENCH_STALL_NOTE_SECS=60
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

    def test_staged_script_saves_the_log_then_begins_on_the_node_clock(self):
        run = run_chaos_shell(self.STAGED + r'''
tn_iap_ssh_stdin() { tee "$WORK/script.sh" | sudo bash -s; }
DUE=$(( $(date +%s) + 2 ))
echo "DUE $DUE"
chaos_stage_send 0 kill "$DUE" pre-kill
echo "RC $?"
''')
        out = run["out"]
        due = int(re.search(r"^DUE (\d+)$", out, re.M).group(1))
        begin = marker_time(out, "BEGIN")
        self.assertGreaterEqual(begin, due)
        self.assertLess(begin, due + 1)
        self.assertIn("BENCH_CHAOS_END node=bench-validator-05 rc=0 ", out)
        self.assertIn("RC 0", out)
        # The log is saved, under bench_save_node_log's name, before BEGIN and before the kill.
        saved = re.search(r"^BENCH_CHAOS_SAVED (\S+)$", out, re.M)
        self.assertLess(saved.start(), out.index("BENCH_CHAOS_BEGIN "))
        (name, content), = run["saved"].items()
        self.assertRegex(name, r"^telcoin-pre-kill-\d{8}T\d{6}Z\.log\.gz$")
        self.assertTrue(saved.group(1).endswith("/node-logs/" + name))
        self.assertEqual(content, "container line 1\ncontainer line 2\n")
        calls = run["calls"].splitlines()
        self.assertLess(calls.index("docker logs telcoin"), calls.index("docker kill -s KILL telcoin"))
        self.assertIn("systemctl stop telcoin", calls)
        # What went over stdin: assignment lines, then the script; it parses as is.
        self.assertTrue(run["script"].startswith(
            "CHAOS_NODE=bench-validator-05\nCHAOS_ACTION=kill\nCHAOS_DUE=%d\nCHAOS_SAVE=pre-kill\n" % due))
        self.assertIn("\nCHAOS_MAX_WAIT=90\n", run["script"])
        subprocess.run(["bash", "-n", "-c", run["script"]], check=True)

    def test_session_failing_before_begin_falls_back_to_the_direct_path(self):
        run = run_chaos_shell(self.STAGED + r'''
tn_iap_ssh_stdin() { cat > /dev/null; return 255; }      # IAP refused the session
tn_iap_ssh() { bash -c "$3"; }                           # the direct --command, run here
save_log_first() { echo "save_log_first $*" >> "$CALLS"; }
DUE=$(( $(date +%s) - 1 ))
echo "DUE $DUE"
chaos_staged 0 kill "$DUE" pre-kill "docker kill -s KILL telcoin" "kill note"
echo "RC $CHAOS_RC"
chaos_stage_send 0 "rm -rf" "$DUE" "" || echo "bad action rc $?"
''')
        due = int(re.search(r"^DUE (\d+)$", run["out"], re.M).group(1))
        self.assertIn("failed before it began (rc=255)", run["out"])
        self.assertIn("RC 0", run["out"])
        self.assertIn("bad action rc 2", run["out"])
        calls = run["calls"].splitlines()
        self.assertEqual(calls[0], "save_log_first 0 pre-kill")
        self.assertIn("docker kill -s KILL telcoin", calls)
        entry, = run["manifest"]["chaos"]
        self.assertEqual((entry["staged"], entry["rc"], entry["planned_unix"], entry["note"]),
                         (False, 0, due, "kill note"))
        self.assertGreaterEqual(entry["begin_unix"], due)
        self.assertGreaterEqual(entry["late_secs"], 0)

    def test_due_time_beyond_the_wait_limit_is_refused_and_not_saved_twice(self):
        run = run_chaos_shell(self.STAGED + r'''
tn_iap_ssh_stdin() { sudo bash -s; }
tn_iap_ssh() { bash -c "$3"; }
save_log_first() { echo "save_log_first $*" >> "$CALLS"; }
sleep() { echo "sleep $*" >> "$CALLS"; }                 # the fallback waits for the due time
chaos_staged 1 restart "$(( $(date +%s) + 200 ))" pre-restart "systemctl restart telcoin" "observer restart"
''')
        self.assertIn("BENCH_CHAOS_STAGE_FAIL due in", run["out"])
        calls = run["calls"]
        self.assertNotIn("save_log_first", calls)                  # the staged session saved it
        self.assertRegex(calls, r"(?m)^sleep (19\d|200)$")
        self.assertIn("systemctl restart telcoin", calls)
        self.assertEqual(len(run["saved"]), 1)
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


class CommitFlatTests(unittest.TestCase):
    FUNCTIONS = blast_functions("status_samples", "status_collect", "fleet_round", "round_text",
                                "commit_flat_check", "commit_stall_record", "commit_flat_flush")
    STATE = r'''
STATUS_SEEN=(); POLL_SAMPLES=""
FLAT_BLOCK=""; FLAT_SINCE=0; FLAT_WARNED=0; FLAT_ROUND=""; FLAT_LAST_TS=0
STALL_WIN_START=1000; STALL_MIXED_END=5000; STALL_WIN_END=6000
PREV_ROUNDS='{"bench-validator-01":300000123,"bench-observer-11":300000100}'
'''

    def test_flat_commits_noted_once_and_never_abort(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + r'''
commit_flat_check $'400 5\n520 5\n640 5\n760 5'          # preamble: flat, before the mixed phase
commit_flat_check $'1000 10\n1120 15\n1240 15'           # one poll ...
PREV_ROUNDS='{"bench-validator-01":300000400}'
commit_flat_check $'1360 15\n1480 20'                    # ... and the next
commit_flat_flush
''')
        self.assertEqual([line for line in run["out"].splitlines() if "commits flat" in line], [
            "    ⚠ commits flat at block 15 since 1970-01-01T00:18:40Z (120s; round 123 (epoch 3)) — note only"])
        self.assertEqual(run["manifest"]["commit_stalls"], [dict(
            start="1970-01-01T00:18:40Z", end="1970-01-01T00:24:40Z", secs=360, block=15,
            round_start=300000123, round_end=300000400, source="watch")])
        note, = run["manifest"]["notes"]
        self.assertIn("stayed at 15", note)
        self.assertEqual(run["aborts"], "")

    def test_cooldown_drain_ignored_and_open_stretch_flushed(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + r'''
STALL_MIXED_END=1100
commit_flat_check $'1000 10\n1120 15\n1240 15\n1360 15'  # starts after the mixed phase: the drain
echo "WARNED $FLAT_WARNED"
FLAT_BLOCK=""; STALL_MIXED_END=5000; STALL_WIN_END=1400
commit_flat_check $'1120 15\n1240 15\n1360 15\n1480 20'  # 1480 falls after the window
commit_flat_flush
''')
        self.assertIn("WARNED 0", run["out"])
        stall, = run["manifest"]["commit_stalls"]
        self.assertEqual((stall["start"], stall["end"], stall["secs"], stall["open"]),
                         ("1970-01-01T00:18:40Z", "1970-01-01T00:22:40Z", 240, True))
        self.assertEqual(run["aborts"], "")

    def test_status_samples_since_the_last_poll(self):
        run = run_chaos_shell(self.FUNCTIONS + self.STATE + r'''
LINES=$'[ 12.3] bench-node-sampler.sh[812]: BENCH_STATUS host=v1 ts=1000 root_used_pct=6 fatal_db=0 block=10 rss_total_kb=1\r\nBENCH_STATUS host=v1 ts=1120 root_used_pct=6 fatal_db=0 block=15 rss_total_kb=1\r'
status_collect 0 "$LINES"; status_collect 0 "$LINES"     # the second read finds nothing new
status_collect 1 $'BENCH_STATUS host=v2 ts=1100 root_used_pct=6 fatal_db=0 block= rss_total_kb=1'
printf 'SAMPLES<%s>\n' "$POLL_SAMPLES"; echo "SEEN ${STATUS_SEEN[0]} ${STATUS_SEEN[1]}"
''')
        self.assertIn("SAMPLES<1000 10\n1120 15\n1100 \n>", run["out"])
        self.assertIn("SEEN 1120 1100", run["out"])


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
