"""The operator-side RPC tunnel of bench-lib.sh (bench_tunnel_up, its ssh-mode supervisor), offline.

Bench 3 (D9/D10/D11): the ssh-mode supervisor restarted its forward forever once the teardown had
deleted bench-validator-01, tunnel.log was truncated on every start, and the plan line named the old
websocket command. Now the supervisor (BENCH_TUNNEL_SUPERVISOR, a heredoc variable) counts
consecutive failures and gives up after BENCH_TUNNEL_MAX_FAILS; a session that stayed up at least
BENCH_TUNNEL_MIN_UP_SECS starts the count again; an instance that GCP no longer knows ends it; every
start appends `tunnel: start <ISO> mode= target= local= pid=` to tunnel.log; the plan line follows
BENCH_TUNNEL_MODE.

The supervisor text and the tunnel functions are cut out of bench-lib.sh and run under bash, the
supervisor exactly as bench_tunnel_up starts it (`bash -c "$BENCH_TUNNEL_SUPERVISOR"
tn-bench-tunnel-supervisor <inst> <zone> <project> <port>`). GCP is fixtures/tunnel/fake-gcloud.py,
whose `compute ssh` follows a per-call plan (fail at once, hold for <s> seconds, or delete the
instance); `sleep` is a stub that returns at once (the 3-s restart delay), so a test's run time is
the time the fake forwards stay up.

Bench 4 (D-C): the bench-obs VM's Prometheus (:9090) and Grafana (:3000) reach the operator through
the same supervisor, so it takes the forward's target as its 5th argument and logs that port, and
one function, _bench_tunnel_start, starts any supervised forward (bench_tunnel_up's ssh mode is one
call of it). bench_tunnel_down stops every tunnel*.pid of the run. bench_prom_query asks bench-obs
straight through its forward (BENCH_PROM_AUTH=0, no secret read) and keeps the Grafana proxy call
for BENCH_PROM_AUTH=1. The RPC tunnel's output must not change: fixtures/tunnel/baseline-28c7623.sh
holds the supervisor and functions as they were before (checked against that commit when the
checkout has it), and the parity tests run both copies side by side and compare stdout, stderr,
tunnel.log and the gcloud/curl argv.
"""
import json
import os
import signal
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
FIX = TESTS / "fixtures" / "tunnel"
LIB = (BENCH / "bench-lib.sh").read_text()
TEARDOWN = (BENCH / "benchmark-teardown.sh").read_text()

REPO = BENCH.parent
BASELINE_COMMIT = "28c7623"
BASELINE = (FIX / ("baseline-%s.sh" % BASELINE_COMMIT)).read_text()
REAL_SLEEP = shutil.which("sleep") or "/bin/sleep"

INST, ZONE, PROJECT, PORT = "bench-validator-01", "us-west2-a", "acme-project", "18545"
OBS, OBS_ZONE, PROM_PORT = "bench-obs", "us-west2-a", "19090"
PROM_URL = "http://127.0.0.1:%s/api/v1" % PROM_PORT
ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
START_RE = re.compile(r"^tunnel: start %s mode=ssh target=%s:8545 local=%s pid=\d+$" % (ISO, INST, PORT))


def shell_function(source, name):
    """The text of shell function <name> in <source>: a block ending in a column-0 brace, or one line."""
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.M | re.S) \
        or re.search(r"^%s\(\) \{ .*\}\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("function %s not found" % name)
    return m.group()


def supervisor_assignment(source):
    """bench-lib.sh's `IFS= read -r -d '' BENCH_TUNNEL_SUPERVISOR <<'EOS' || true` ... `EOS` block."""
    m = re.search(r"^IFS= read -r -d '' BENCH_TUNNEL_SUPERVISOR <<'EOS' \|\| true\n.*?^EOS\n", source, re.M | re.S)
    if not m:
        raise AssertionError("the BENCH_TUNNEL_SUPERVISOR heredoc is not in bench-lib.sh")
    return m.group()


SUPERVISOR = supervisor_assignment(LIB)
COMMON = "".join(shell_function(LIB, n) for n in ("bench_warn", "bench_now_iso"))
FLEET = "INSTANCE_NAMES=(%s bench-validator-02)\nZONES=(%s us-east4-b)\n" % (INST, ZONE)
PRELUDE = ("set -euo pipefail\n" + COMMON + SUPERVISOR
           + "".join(shell_function(LIB, n) for n in (
               "bench_tunnel_pidfile", "_bench_tunnel_start", "bench_tunnel_up", "bench_tunnel_down",
               "bench_prom_query", "bench_obs_mem_pct", "_bench_index_kind"))
           + FLEET)
# The same, with the supervisor and functions of the baseline commit (no _bench_tunnel_start).
BASE_PRELUDE = "set -euo pipefail\n" + COMMON + BASELINE + FLEET



def normalized(text):
    """<text> with its ISO times and pids masked: what differs between two runs of the same tunnel."""
    return re.sub(r"\bpid([= ])\d+", r"pid\1<PID>", re.sub(ISO, "<ISO>", text))


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tunnel-")
        self.root = Path(self._tmp.name)
        self.state = self.root / "state"
        self.results = self.root / "results" / "r20991231-0101"
        self.bin = self.root / "bin"
        for d in (self.state, self.results, self.bin):
            d.mkdir(parents=True)
        for name, src in (("gcloud", "fake-gcloud.py"), ("sleep", "stub-sleep.sh"), ("cast", "stub-cast.sh"),
                          ("curl", "stub-curl.py")):
            shutil.copyfile(str(FIX / src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.log = self.results / "tunnel.log"
        self.pids = []

    def tearDown(self):
        for pidf in self.root.rglob("tunnel*.pid"):
            try:
                self.pids.append(int(pidf.read_text().strip()))
            except ValueError:
                pass
        for pid in self.pids:
            for target in (-pid, pid):
                try:
                    os.kill(target, 9)
                except OSError:
                    pass
        self._tmp.cleanup()

    def env(self, **extra):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.root), "FAKE_ROOT": str(self.state),
               "FAKE_TUNNEL_LOG": str(self.log)}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        return env

    def plan(self, *steps):
        (self.state / "ssh-plan").write_text("\n".join(steps) + "\n")

    def calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line)["argv"] for line in p.read_text().splitlines()] if p.exists() else []

    def ssh_calls(self):
        return [c for c in self.calls() if c[:2] == ["compute", "ssh"]]

    def curl_calls(self):
        p = self.state / "curl-calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def reset_fakes(self):
        """Forget every call and the tunnel log (between the two runs of a parity test)."""
        for name in ("calls.jsonl", "ssh-count", "gone", "curl-calls.jsonl", "sleeps", "tn-secret-calls", "fds.jsonl"):
            if (self.state / name).exists():
                (self.state / name).unlink()
        if self.log.exists():
            self.log.unlink()

    def run_lib(self, body, apply=True, prelude=PRELUDE, **extra):
        env = self.env(BENCH_APPLY="1" if apply else "0", BENCH_RESULTS_DIR=str(self.results), PROJECT_ID=PROJECT,
                       BENCH_TUNNEL_PORT=PORT, RPC_URL="http://localhost:%s" % PORT, **extra)
        return subprocess.run(["bash", "-c", prelude + body + "\n"], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def wait_for(self, pred, secs=10):
        end = time.time() + secs
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.1)
        return False

    def group_gone(self, pid):
        return subprocess.run(["pgrep", "-g", str(pid)], stdout=subprocess.PIPE).returncode != 0


class SupervisorTests(Case):
    """The supervisor alone, started as bench_tunnel_up starts it, its output collected as tunnel.log."""

    def supervise(self, timeout=40, args=(INST, ZONE, PROJECT, PORT, "127.0.0.1:8545"), **env):
        script = PRELUDE + 'bash -c "${BENCH_TUNNEL_SUPERVISOR}" tn-bench-tunnel-supervisor "$@"\n'
        try:
            return subprocess.run(["bash", "-c", script, "t"] + list(args), env=self.env(**env),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  universal_newlines=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            out = e.output.decode() if isinstance(e.output, bytes) else (e.output or "")
            self.fail("the supervisor was still restarting after %d s (%d ssh sessions); its output ends:\n%s"
                      % (timeout, len(self.ssh_calls()), out[-600:]))

    def starts(self, out):
        return [line for line in out.splitlines() if line.startswith("tunnel: start ")]

    def test_gives_up_after_max_fails(self):
        self.plan("fail")
        p = self.supervise(BENCH_TUNNEL_MAX_FAILS="3", BENCH_TUNNEL_MIN_UP_SECS="2")
        self.assertEqual(p.returncode, 1, p.stdout)
        lines = p.stdout.splitlines()
        self.assertRegex(lines[-1], r"^tunnel: giving up after 3 consecutive failures at %s$" % ISO)
        self.assertEqual(len(self.starts(p.stdout)), 3, p.stdout)
        for line in self.starts(p.stdout):
            self.assertRegex(line, START_RE)
        self.assertEqual(len(self.ssh_calls()), 3)
        exits = [l for l in lines if l.startswith("tunnel: exit ")]
        self.assertEqual(len(exits), 3, p.stdout)
        for n, line in enumerate(exits, 1):   # a quick failure: up 0 s, or 1 s across a second boundary
            self.assertRegex(line, r"^tunnel: exit %s rc=255 up=[01]s fails=%d/3$" % (ISO, n))
        # The forward it runs: one IAP ssh session, -N -L localhost:<port>:127.0.0.1:8545.
        ssh = self.ssh_calls()[0]
        self.assertEqual(ssh[:3], ["compute", "ssh", INST])
        for word in ("--zone=" + ZONE, "--project=" + PROJECT, "--tunnel-through-iap",
                     "--ssh-flag=localhost:%s:127.0.0.1:8545" % PORT, "--ssh-flag=-o ExitOnForwardFailure=yes"):
            self.assertIn(word, ssh)

    def test_default_is_five_consecutive_failures(self):
        self.plan("fail")
        p = self.supervise()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(len(self.starts(p.stdout)), 5)
        self.assertRegex(p.stdout.splitlines()[-1], r"^tunnel: giving up after 5 consecutive failures at ")

    def test_a_session_that_stays_up_starts_the_count_again(self):
        # Two quick failures, a 3-s session (>= 2 s: a drop, not a failure), twice; then the instance
        # goes. Without the reset the third failure in a row would have ended it at max 3.
        self.plan("fail", "fail", "up:3", "fail", "fail", "up:3", "fail", "fail", "gone")
        p = self.supervise(BENCH_TUNNEL_MAX_FAILS="3", BENCH_TUNNEL_MIN_UP_SECS="2")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("giving up", p.stdout)
        self.assertEqual(len(self.starts(p.stdout)), 9, p.stdout)
        fails = [re.search(r"fails=(\d+)/3$", l).group(1) for l in p.stdout.splitlines() if l.startswith("tunnel: exit ")]
        self.assertEqual(fails, ["1", "2", "0", "1", "2", "0", "1", "2", "3"])
        self.assertRegex(p.stdout.splitlines()[-1],
                         r"^tunnel: %s is gone \(instances describe: not found\) at %s; not restarting$" % (INST, ISO))

    def test_an_instance_that_is_gone_ends_it_at_once(self):
        self.plan("up:3", "gone")
        p = self.supervise(BENCH_TUNNEL_MIN_UP_SECS="2")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(len(self.ssh_calls()), 2)
        describes = [c for c in self.calls() if c[:3] == ["compute", "instances", "describe"]]
        self.assertEqual(len(describes), 2, "one describe after each exit")
        self.assertEqual(describes[0][3:6], [INST, "--zone=" + ZONE, "--project=" + PROJECT])
        self.assertIn("not restarting", p.stdout.splitlines()[-1])

    def test_a_9090_target_is_forwarded_and_logged_with_its_port(self):
        # bench-obs's Prometheus: localhost:19090 -> 127.0.0.1:9090 on the obs VM.
        self.plan("gone")
        p = self.supervise(args=(OBS, OBS_ZONE, PROJECT, PROM_PORT, "127.0.0.1:9090"))
        self.assertEqual(p.returncode, 0, p.stdout)
        starts = self.starts(p.stdout)
        self.assertEqual(len(starts), 1, p.stdout)
        self.assertRegex(starts[0], r"^tunnel: start %s mode=ssh target=%s:9090 local=%s pid=\d+$" % (ISO, OBS, PROM_PORT))
        ssh = self.ssh_calls()[0]
        self.assertEqual(ssh[:3], ["compute", "ssh", OBS])
        self.assertIn("--ssh-flag=localhost:%s:127.0.0.1:9090" % PROM_PORT, ssh)
        self.assertNotIn("--ssh-flag=localhost:%s:127.0.0.1:8545" % PROM_PORT, ssh)


class TunnelUpTests(Case):
    """bench_tunnel_up / bench_tunnel_down: plan line per mode, append-only tunnel.log, the supervisor's group."""

    def test_plan_line_follows_the_mode_and_a_dry_run_runs_nothing(self):
        p = self.run_lib("bench_tunnel_up", apply=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        plan = p.stdout.splitlines()[0]
        self.assertIn("+ gcloud compute ssh %s --zone=%s --project=%s --tunnel-through-iap" % (INST, ZONE, PROJECT), plan)
        self.assertIn("--ssh-flag=localhost:%s:127.0.0.1:8545" % PORT, plan)
        self.assertIn("gives up after 5 consecutive failures shorter than 20 s", plan)
        self.assertNotIn("start-iap-tunnel", plan)
        self.assertIn("(dry run — not executed)", p.stdout)
        p = self.run_lib("bench_tunnel_up", apply=False, BENCH_TUNNEL_MODE="websocket", BENCH_TUNNEL_MAX_FAILS="7")
        plan = p.stdout.splitlines()[0]
        self.assertIn("+ gcloud compute start-iap-tunnel %s 8545 --local-host-port=localhost:%s --zone=%s --project=%s &"
                      % (INST, PORT, ZONE, PROJECT), plan)
        self.assertNotIn("compute ssh", plan)
        p = self.run_lib("bench_tunnel_up", apply=False, BENCH_TUNNEL_MAX_FAILS="many", BENCH_TUNNEL_MIN_UP_SECS="x")
        self.assertIn("BENCH_TUNNEL_MAX_FAILS='many' is not a positive integer — using 5", p.stderr)
        self.assertIn("BENCH_TUNNEL_MIN_UP_SECS='x' is not a whole number of seconds — using 20", p.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.log.exists())

    def test_ssh_mode_appends_to_the_log_and_down_stops_the_whole_group(self):
        self.log.write_text("an earlier start's lines\n")
        self.plan("up:60")
        p = self.run_lib("bench_tunnel_up")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        pid = int((self.results / "tunnel.pid").read_text())
        self.pids.append(pid)
        self.assertIn("✓ tunnel up (pid %d)" % pid, p.stdout)
        text = self.log.read_text()
        self.assertTrue(text.startswith("an earlier start's lines\n"), "tunnel.log is appended, never truncated")
        self.assertRegex(text.splitlines()[1], START_RE)
        # The teardown finds the supervisor by its pattern (benchmark-teardown.sh TUNNEL_PAT).
        m = re.search(r'^TUNNEL_PAT="(.*)"$', TEARDOWN, re.M)
        if m:
            ports = {"BENCH_TUNNEL_PORT": PORT, "BENCH_OBS_PROM_LOCAL_PORT": PROM_PORT,
                     "BENCH_OBS_GRAFANA_LOCAL_PORT": "13000"}
            pat = re.sub(r"\$\{(\w+)\}", lambda v: ports.get(v.group(1), "0"), m.group(1))
            found = subprocess.run(["pgrep", "-f", pat], stdout=subprocess.PIPE, universal_newlines=True).stdout.split()
            self.assertIn(str(pid), found)
        # A second up finds it running and starts nothing.
        p = self.run_lib("bench_tunnel_up")
        self.assertIn("tunnel already up (pid %d)" % pid, p.stdout)
        self.assertEqual(len(self.ssh_calls()), 1)
        p = self.run_lib("bench_tunnel_down")
        self.assertIn("stopped tunnel pid %d" % pid, p.stdout)
        self.assertTrue(self.wait_for(lambda: self.group_gone(pid)),
                        "the supervisor's process group (supervisor, gcloud) is gone")
        self.assertFalse((self.results / "tunnel.pid").exists())

    def test_websocket_mode_appends_its_start_line(self):
        self.log.write_text("before\n")
        p = self.run_lib("bench_tunnel_up", BENCH_TUNNEL_MODE="websocket")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        pid = int((self.results / "tunnel.pid").read_text())
        self.pids.append(pid)
        self.assertTrue(self.wait_for(lambda: "Listening on port" in self.log.read_text()))
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines[0], "before")
        starts = [l for l in lines if l.startswith("tunnel: start ")]
        self.assertEqual(len(starts), 1)
        self.assertRegex(starts[0], r"^tunnel: start %s mode=websocket target=%s:8545 local=%s pid=%d$" % (ISO, INST, PORT, pid))
        self.assertEqual([c[:3] for c in self.calls()], [["compute", "start-iap-tunnel", INST]])
        self.run_lib("bench_tunnel_down")


class TunnelStartTests(Case):
    """_bench_tunnel_start alone, as obs-lib.sh's bench_obs_tunnel_up calls it for bench-obs:9090."""

    PIDF_NAME = "tunnel-obs-prom.pid"
    # The probe is eval'd: here it answers once tunnel.log holds the 9090 forward's start line.
    PROBE = "grep -q '^tunnel: start .* target=%s:9090 local=%s ' \"${FAKE_TUNNEL_LOG}\"" % (OBS, PROM_PORT)

    def start(self, probe=PROBE, apply=True, **extra):
        body = '_bench_tunnel_start "$P" %s %s %s 127.0.0.1:9090 "$PROBE" "$DESC"' % (OBS, OBS_ZONE, PROM_PORT)
        return self.run_lib(body, apply=apply, P=str(self.results / self.PIDF_NAME), PROBE=probe, DESC=PROM_URL, **extra)

    def plan_line(self, maxf=5, minup=20):
        return ("    + gcloud compute ssh %s --zone=%s --project=%s --tunnel-through-iap --ssh-flag=-N --ssh-flag=-L "
                "--ssh-flag=localhost:%s:127.0.0.1:9090 ... &   (supervised: restarted on a drop, gives up after %d "
                "consecutive failures shorter than %d s or when the instance is gone; >> %s)"
                % (OBS, OBS_ZONE, PROJECT, PROM_PORT, maxf, minup, self.results / "tunnel.log"))

    def test_writes_the_pidfile_waits_for_the_probe_and_names_the_desc(self):
        self.plan("up:60")
        p = self.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        pidf = self.results / self.PIDF_NAME
        pid = int(pidf.read_text())
        self.pids.append(pid)
        self.assertEqual(p.stdout.splitlines(), [self.plan_line(), "    ✓ tunnel up (pid %d) -> %s" % (pid, PROM_URL)])
        self.assertFalse((self.results / "tunnel.pid").exists(), "the RPC tunnel's pidfile is not touched")
        starts = [l for l in self.log.read_text().splitlines() if l.startswith("tunnel: start ")]
        self.assertEqual(len(starts), 1)
        self.assertRegex(starts[0], r"^tunnel: start %s mode=ssh target=%s:9090 local=%s pid=\d+$" % (ISO, OBS, PROM_PORT))
        # The start line comes right after the supervisor forks gcloud, so the fake may record its call later.
        self.assertTrue(self.wait_for(self.ssh_calls), "the forward's gcloud ssh ran")
        ssh = self.ssh_calls()
        self.assertEqual(len(ssh), 1)
        self.assertEqual(ssh[0][:3], ["compute", "ssh", OBS])
        for word in ("--zone=" + OBS_ZONE, "--project=" + PROJECT, "--ssh-flag=localhost:%s:127.0.0.1:9090" % PROM_PORT):
            self.assertIn(word, ssh[0])
        # The supervisor is found by its $0, like the RPC tunnel's.
        found = subprocess.run(["pgrep", "-f", "tn-bench-tunnel-supervisor %s " % OBS], stdout=subprocess.PIPE,
                               universal_newlines=True).stdout.split()
        self.assertIn(str(pid), found)
        p = self.start()
        self.assertEqual(p.stdout, "    tunnel already up (pid %d) -> %s\n" % (pid, PROM_URL))
        self.assertEqual(len(self.ssh_calls()), 1, "an already-up forward starts nothing")

    def fds(self):
        p = self.state / "fds.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_tunnel_processes_are_born_with_fds_5_and_6_closed(self):
        # The deploy logs through fds 5 and 6; a tunnel that inherited them would hold the deploy's
        # log open after it exits. The caller here has both open; the forward must see neither.
        opener = 'exec 5>"${BENCH_RESULTS_DIR}/fd5" 6>"${BENCH_RESULTS_DIR}/fd6"\n'
        self.plan("up:60")
        p = self.run_lib(opener + '_bench_tunnel_start "$P" %s %s %s 127.0.0.1:9090 "$PROBE" "$DESC"'
                         % (OBS, OBS_ZONE, PROM_PORT), P=str(self.results / self.PIDF_NAME), PROBE=self.PROBE, DESC=PROM_URL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(self.wait_for(self.fds), "the forward's gcloud ssh ran")
        self.assertEqual([(f["argv"][:3], f["open"]) for f in self.fds()], [(["compute", "ssh", OBS], [])])
        self.run_lib("bench_tunnel_down")
        # The RPC tunnel in both modes; the baseline copy (no closes) shows the check sees inherited fds.
        for prelude, mode, expect in ((BASE_PRELUDE, "ssh", [5, 6]), (PRELUDE, "ssh", []), (PRELUDE, "websocket", [])):
            with self.subTest(baseline=prelude is BASE_PRELUDE, mode=mode):
                self.reset_fakes()
                self.plan("up:60")
                p = self.run_lib(opener + "bench_tunnel_up", prelude=prelude, BENCH_TUNNEL_MODE=mode)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                pid = int((self.results / "tunnel.pid").read_text())
                self.pids.append(pid)
                self.assertTrue(self.wait_for(self.fds), "the tunnel's gcloud ran")
                self.assertEqual([f["open"] for f in self.fds()], [expect])
                self.run_lib("bench_tunnel_down", prelude=prelude)
                self.assertTrue(self.wait_for(lambda: self.group_gone(pid)))

    def test_a_dry_run_prints_the_plan_line_only(self):
        p = self.start(apply=False, BENCH_TUNNEL_MAX_FAILS="3", BENCH_TUNNEL_MIN_UP_SECS="9")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), [self.plan_line(3, 9), "      (dry run — not executed)"])
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.results / self.PIDF_NAME).exists())
        self.assertFalse(self.log.exists())

    def test_a_forward_that_never_answers_names_its_port(self):
        self.plan("fail")
        p = self.start(probe="false", BENCH_TUNNEL_MAX_FAILS="1")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("✓", p.stdout)
        self.assertEqual(p.stderr.splitlines()[-1],
                         "❌ IAP tunnel to %s:9090 did not come up; see %s" % (OBS, self.results / "tunnel.log"))
        self.assertTrue((self.results / self.PIDF_NAME).exists(), "the pidfile names the supervisor that was started")


class BaselineParityTests(Case):
    """The RPC tunnel and the proxy query against the baseline commit's copies: byte for byte."""

    def test_the_baseline_fixture_is_that_commit_text(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        p = subprocess.run(["git", "-C", str(REPO), "show", "%s:benchmark/bench-lib.sh" % BASELINE_COMMIT],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode != 0:
            self.skipTest("commit %s is not in this checkout (shallow clone?)" % BASELINE_COMMIT)
        body = supervisor_assignment(p.stdout) + "".join(shell_function(p.stdout, n) for n in (
            "bench_tunnel_pidfile", "bench_tunnel_up", "bench_tunnel_down", "bench_prom_query"))
        self.assertTrue(BASELINE.endswith(body), "fixtures/tunnel/baseline-%s.sh is not that commit's text" % BASELINE_COMMIT)
        self.assertEqual(BASELINE[:-len(body)].count("\n"), len(re.findall(r"^#", BASELINE[:-len(body)], re.M)),
                         "only comment lines precede the baseline text")

    def both(self, body, apply, between=None, **extra):
        """(baseline run, current run) of <body> in the same sandbox, the fakes reset in between."""
        out = []
        for prelude in (BASE_PRELUDE, PRELUDE):
            self.reset_fakes()
            p = self.run_lib(body, apply=apply, prelude=prelude, **extra)
            out.append((p, self.calls(), self.log.read_text() if self.log.exists() else None))
            if between:
                between()
        return out

    def test_dry_run_output_is_unchanged(self):
        for extra in ({}, {"BENCH_TUNNEL_MAX_FAILS": "7", "BENCH_TUNNEL_MIN_UP_SECS": "30"},
                      {"BENCH_TUNNEL_MAX_FAILS": "many", "BENCH_TUNNEL_MIN_UP_SECS": "x"},
                      {"BENCH_TUNNEL_MAX_FAILS": "0"}, {"BENCH_TUNNEL_MODE": "websocket"},
                      {"BENCH_TUNNEL_MODE": "websocket", "BENCH_TUNNEL_MAX_FAILS": "-1"}):
            with self.subTest(**extra):
                (old, old_calls, old_log), (new, new_calls, new_log) = self.both("bench_tunnel_up", False, **extra)
                self.assertEqual(old.returncode, 0, old.stderr)
                self.assertEqual((new.returncode, new.stdout, new.stderr), (old.returncode, old.stdout, old.stderr))
                self.assertEqual((new_calls, new_log), ([], None))
        # A pidfile whose process is alive: "already up", in a dry run too.
        holder = subprocess.Popen([REAL_SLEEP, "60"], start_new_session=True)
        self.pids.append(holder.pid)
        (self.results / "tunnel.pid").write_text("%d\n" % holder.pid)
        (old, _, _), (new, _, _) = self.both("bench_tunnel_up", False)
        self.assertEqual(old.stdout, "    tunnel already up (pid %d) -> http://localhost:%s\n" % (holder.pid, PORT))
        self.assertEqual((new.returncode, new.stdout, new.stderr), (old.returncode, old.stdout, old.stderr))
        (self.results / "tunnel.pid").unlink()
        holder.kill()
        holder.wait(timeout=10)

    def test_apply_mode_stdout_tunnel_log_and_argv_are_unchanged(self):
        for mode in ("ssh", "websocket"):
            with self.subTest(mode=mode):
                runs = []
                for prelude in (BASE_PRELUDE, PRELUDE):
                    self.reset_fakes()
                    self.plan("up:60")
                    up = self.run_lib("bench_tunnel_up", prelude=prelude, BENCH_TUNNEL_MODE=mode)
                    self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
                    pid = int((self.results / "tunnel.pid").read_text())
                    self.pids.append(pid)
                    if mode == "websocket":
                        self.assertTrue(self.wait_for(lambda: "Listening on port" in self.log.read_text()))
                    self.assertTrue(self.wait_for(self.calls), "the fake recorded the tunnel's gcloud call")
                    log = self.log.read_text()
                    again = self.run_lib("bench_tunnel_up", prelude=prelude, BENCH_TUNNEL_MODE=mode)
                    down = self.run_lib("bench_tunnel_down", prelude=prelude)
                    self.assertTrue(self.wait_for(lambda: self.group_gone(pid)), "tunnel %d stopped" % pid)
                    runs.append([normalized(x) for x in (up.stdout, up.stderr, log, again.stdout, down.stdout)]
                                + [self.calls()])
                    self.assertFalse((self.results / "tunnel.pid").exists())
                self.assertEqual(runs[1], runs[0])
                self.assertIn("✓ tunnel up (pid <PID>) -> http://localhost:%s" % PORT, runs[0][0])
                self.assertIn("tunnel: start <ISO> mode=%s target=%s:8545 local=%s pid=<PID>" % (mode, INST, PORT), runs[0][2])

    def test_a_tunnel_that_never_answers_fails_the_same_way(self):
        def run(prelude):
            self.reset_fakes()
            self.plan("fail")
            # cast reads a log that never gets a start line: the RPC never answers.
            p = self.run_lib("bench_tunnel_up", prelude=prelude, BENCH_TUNNEL_MAX_FAILS="1",
                             FAKE_TUNNEL_LOG=str(self.root / "no-such.log"))
            pid = int((self.results / "tunnel.pid").read_text())
            self.pids.append(pid)
            (self.results / "tunnel.pid").unlink()
            self.assertTrue(self.wait_for(lambda: self.group_gone(pid)), "the supervisor gave up")
            return p.returncode, normalized(p.stdout), p.stderr
        old, new = run(BASE_PRELUDE), run(PRELUDE)
        self.assertEqual(old[0], 1)
        self.assertEqual(new, old)
        self.assertEqual(old[2].splitlines()[-1],
                         "❌ IAP tunnel to %s:8545 did not come up; see %s" % (INST, self.results / "tunnel.log"))


class TunnelDownTests(Case):
    """bench_tunnel_down stops every tunnel*.pid of the run (the RPC tunnel and the bench-obs forwards)."""

    def test_every_tunnel_pidfile_is_stopped_with_its_group(self):
        procs = {}
        for name in ("tunnel.pid", "tunnel-obs-prom.pid", "tunnel-obs-grafana.pid", "other.pid"):
            # a session leader with a child, as the supervisor and its gcloud are
            pr = subprocess.Popen(["bash", "-c", '"$0" 60 & wait', REAL_SLEEP], start_new_session=True)
            self.pids.append(pr.pid)
            (self.results / name).write_text("%d\n" % pr.pid)
            procs[name] = pr
        p = self.run_lib("bench_tunnel_down")
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertEqual(lines[0], "    stopped tunnel pid %d" % procs["tunnel.pid"].pid, "the RPC tunnel first, as before")
        self.assertEqual(sorted(lines[1:]), sorted("    stopped tunnel pid %d (%s)" % (procs[n].pid, n)
                                                  for n in ("tunnel-obs-prom.pid", "tunnel-obs-grafana.pid")))
        for name in ("tunnel.pid", "tunnel-obs-prom.pid", "tunnel-obs-grafana.pid"):
            procs[name].wait(timeout=10)
            self.assertTrue(self.wait_for(lambda: self.group_gone(procs[name].pid)), "%s's group is gone" % name)
            self.assertFalse((self.results / name).exists())
        self.assertIsNone(procs["other.pid"].poll(), "a pidfile that is not tunnel*.pid is left alone")
        self.assertTrue((self.results / "other.pid").exists())
        os.killpg(procs["other.pid"].pid, signal.SIGKILL)
        procs["other.pid"].wait(timeout=10)
        (self.results / "other.pid").unlink()
        self.assertEqual(self.run_lib("bench_tunnel_down").stdout, "", "nothing left to stop")


class PromQueryTests(Case):
    """bench_prom_query: bench-obs straight through its forward by default; the Grafana proxy on BENCH_PROM_AUTH=1."""

    QUERY = 'max by (node) (tn_primary_round{network="bench"})'
    PW = 'pa"ss\\wd'
    STUB = ('tn_secret() { printf "%s\\n" "$*" >> "${FAKE_ROOT}/tn-secret-calls"; [ -z "${SECRET_FAILS:-}" ] || return 1; '
            "printf '%s' \"${SECRET}\"; }\n")

    def query(self, prelude=PRELUDE, **extra):
        env = dict(BENCH_PROM_URL=PROM_URL, BENCH_GRAFANA_URL="https://grafana.example.invalid",
                   BENCH_PROM_DATASOURCE_UID="prometheus", OBS_GRAFANA_SECRET_NAME="obs-grafana-admin-password",
                   SECRET=self.PW, Q=self.QUERY)
        env.update(extra)
        return self.run_lib(self.STUB + 'bench_prom_query "$Q"', prelude=prelude, **env)

    def secret_reads(self):
        p = self.state / "tn-secret-calls"
        return p.read_text().splitlines() if p.exists() else []

    def test_no_auth_path_never_reads_a_secret(self):
        for extra in ({}, {"BENCH_PROM_AUTH": "0"}):
            with self.subTest(**extra):
                self.reset_fakes()
                p = self.query(**extra)
                self.assertEqual(self.secret_reads(), [], "tn_secret must not be called without BENCH_PROM_AUTH=1")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, '{"status":"success","data":{"resultType":"vector","result":[]}}')
                calls = self.curl_calls()
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["argv"], ["-sS", "--max-time", "20", "--get", "--data-urlencode",
                                                    "query=" + self.QUERY, PROM_URL + "/query"])
                self.assertNotIn("-K", calls[0]["argv"])
                self.assertEqual(calls[0]["stdin"], "", "no credentials on stdin")

    def test_auth_path_refuses_the_local_forward_before_reading_a_secret(self):
        # The obs-devnet Grafana password must never go to the bench-obs Grafana behind the forward.
        for url in ("http://127.0.0.1:13000", "http://localhost:13000"):
            with self.subTest(url=url):
                self.reset_fakes()
                p = self.query(BENCH_PROM_AUTH="1", BENCH_GRAFANA_URL=url)
                self.assertEqual(self.secret_reads(), [], "tn_secret must not be called for a local Grafana URL")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertEqual(self.curl_calls(), [])
                self.assertEqual(p.stdout, "")
                self.assertEqual(p.stderr, "❌ bench_prom_query: BENCH_PROM_AUTH=1 needs BENCH_GRAFANA_URL to point at "
                                           "the obs-devnet Grafana, not the bench-obs forward (%s)\n" % url)

    def test_auth_path_is_the_baseline_proxy_call(self):
        runs = []
        for prelude in (BASE_PRELUDE, PRELUDE):
            self.reset_fakes()
            p = self.query(prelude=prelude, BENCH_PROM_AUTH="1")
            runs.append((p.returncode, p.stdout, p.stderr, self.curl_calls(), self.secret_reads()))
        self.assertEqual(runs[1], runs[0])
        rc, _, _, calls, reads = runs[0]
        self.assertEqual(rc, 0)
        self.assertEqual(reads, ["obs-grafana-admin-password"])
        self.assertEqual(calls, [{"argv": ["-sS", "--max-time", "20", "-K", "-", "--get", "--data-urlencode",
                                           "query=" + self.QUERY,
                                           "https://grafana.example.invalid/api/datasources/proxy/uid/prometheus/api/v1/query"],
                                  "stdin": 'user = "admin:pa\\"ss\\\\wd"\n'}])
        # A secret that cannot be read: rc 1 and no query, as before.
        runs = []
        for prelude in (BASE_PRELUDE, PRELUDE):
            self.reset_fakes()
            p = self.query(prelude=prelude, BENCH_PROM_AUTH="1", SECRET_FAILS="1")
            runs.append((p.returncode, p.stdout, p.stderr, self.curl_calls()))
        self.assertEqual(runs[1], runs[0])
        self.assertEqual((runs[0][0], runs[0][3]), (1, []))


class ObsMemPctTests(Case):
    """bench_obs_mem_pct reads the bench-obs VM named by the BENCH_OBS_* knobs, never obs-devnet."""

    BODY = "bench_monitoring_max() { printf 'MAX %s\\n' \"$1\"; }\nbench_obs_mem_pct\n"
    KNOBS = dict(BENCH_OBS_INSTANCE="bench-obs-r7", BENCH_OBS_ZONE="europe-west4-a",
                 OBS_INSTANCE_NAME="obs-devnet", OBS_ZONE="us-central1-f", FAKE_INSTANCE_ID="777")

    def test_describes_the_knob_instance_and_zone(self):
        p = self.run_lib(self.BODY, **self.KNOBS)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [["compute", "instances", "describe", "bench-obs-r7", "--zone=europe-west4-a",
                                         "--project=" + PROJECT, "--format=value(id)"]])
        self.assertEqual(p.stdout, 'MAX metric.type="agent.googleapis.com/memory/percent_used" AND '
                                   'metric.labels.state="used" AND resource.labels.instance_id="777"\n')

    def test_an_absent_vm_is_empty_output(self):
        (self.state / "gone").write_text("")
        p = self.run_lib(self.BODY, **self.KNOBS)
        self.assertEqual((p.returncode, p.stdout), (0, ""))


class IndexAndSourceTests(Case):
    """INDEX.md rows for the bench-obs files; bench-lib.sh refuses to load without obs-lib.sh."""

    def kind(self, path):
        p = self.run_lib('_bench_index_kind "$F"', F=path)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip().split("|")

    def test_index_rows_for_the_obs_forwards_and_the_snapshot(self):
        self.assertEqual(self.kind("tunnel.pid")[:2], ["10", "tunnel.log, tunnel.pid"], "the RPC tunnel's row is unchanged")
        for name in ("tunnel-obs-prom.pid", "tunnel-obs-grafana.pid"):
            row = self.kind(name)
            self.assertEqual(row[:2], ["10", "tunnel-<forward>.pid"], name)
            self.assertIn("bench_obs_tunnel_up", row[3])
        for path, group in (("logs/bench-obs-prometheus-20991231T010203Z.tar.gz", "logs/bench-obs-prometheus-<UTC>.tar.gz"),
                            ("bench-obs-prometheus-20991231T010203Z.tar.gz", "bench-obs-prometheus-<UTC>.tar.gz")):
            row = self.kind(path)
            self.assertEqual(row[1], group, path)
            self.assertNotEqual(row[0], "99", "%s is known to the harness" % path)
            self.assertIn("bench_obs_prom_snapshot_pull", row[3])

    def tree(self):
        root = self.root / "tree"
        for rel in ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(REPO / rel), str(root / rel))
        (root / "params.yaml").write_text("")
        return root

    def source(self, root):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root), "TMPDIR": str(self.root),
               "BENCH_RUN_ID": "rtest-tunnel", "BENCH_APPLY": "0", "BENCH_PARAMETERS_FILE": str(root / "params.yaml")}
        # $0 = benchmark-deploy.sh: config.sh only loads for its allowlisted callers.
        return subprocess.run(["bash", "-c", 'set -euo pipefail; source "$1/bench-lib.sh"; echo LOADED',
                               "benchmark-deploy.sh", str(root / "benchmark")], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def test_a_missing_obs_lib_refuses_to_load(self):
        root = self.tree()
        p = self.source(root)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("LOADED", p.stdout)
        self.assertIn("❌ bench-lib.sh: %s/obs-lib.sh is missing or unreadable — refusing to run." % (root / "benchmark"),
                      p.stderr)
        # With it (the real file once U-O1's lands; an empty stand-in until then) the lib loads.
        obs = root / "benchmark" / "obs-lib.sh"
        if (BENCH / "obs-lib.sh").exists():
            shutil.copyfile(str(BENCH / "obs-lib.sh"), str(obs))
        else:
            obs.write_text("# stand-in for benchmark/obs-lib.sh (unit U-O1), not in this checkout yet\n")
        p = self.source(root)
        self.assertEqual((p.returncode, p.stdout.splitlines()[-1:]), (0, ["LOADED"]), p.stderr)

    def test_obs_lib_is_sourced_right_after_pull_lib(self):
        pull_line = '. "${BENCH_LIB_DIR}/pull-lib.sh"\n'
        pull_end = LIB.index(pull_line) + len(pull_line)
        guard = LIB.index('if [ ! -r "${BENCH_LIB_DIR}/obs-lib.sh" ]; then\n')
        source = LIB.index('. "${BENCH_LIB_DIR}/obs-lib.sh"\n')
        self.assertLess(pull_end, guard)
        self.assertLess(guard, source)
        between = LIB[pull_end:guard].splitlines()
        self.assertTrue(all(l == "" or l.startswith("#") for l in between), "only comments between the two: %r" % between)
        # bench-obs is a bench name: never in the protected pattern.
        m = re.search(r"^BENCH_PROTECTED_RE='(.*)'$", LIB, re.M)
        self.assertIsNone(re.search(m.group(1), OBS))


if __name__ == "__main__":
    unittest.main()
