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
"""
import json
import os
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

INST, ZONE, PROJECT, PORT = "bench-validator-01", "us-west2-a", "acme-project", "18545"
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
PRELUDE = ("set -euo pipefail\n" + SUPERVISOR
           + "".join(shell_function(LIB, n) for n in (
               "bench_warn", "bench_now_iso", "bench_tunnel_pidfile", "bench_tunnel_up", "bench_tunnel_down"))
           + "INSTANCE_NAMES=(%s bench-validator-02)\nZONES=(%s us-east4-b)\n" % (INST, ZONE))


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tunnel-")
        self.root = Path(self._tmp.name)
        self.state = self.root / "state"
        self.results = self.root / "results" / "r20991231-0101"
        self.bin = self.root / "bin"
        for d in (self.state, self.results, self.bin):
            d.mkdir(parents=True)
        for name, src in (("gcloud", "fake-gcloud.py"), ("sleep", "stub-sleep.sh"), ("cast", "stub-cast.sh")):
            shutil.copyfile(str(FIX / src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.log = self.results / "tunnel.log"
        self.pids = []

    def tearDown(self):
        pidf = self.results / "tunnel.pid"
        if pidf.exists():
            self.pids.append(int(pidf.read_text().strip()))
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


class SupervisorTests(Case):
    """The supervisor alone, started as bench_tunnel_up starts it, its output collected as tunnel.log."""

    def supervise(self, timeout=40, **env):
        script = PRELUDE + 'bash -c "${BENCH_TUNNEL_SUPERVISOR}" tn-bench-tunnel-supervisor "$@"\n'
        try:
            return subprocess.run(["bash", "-c", script, "t", INST, ZONE, PROJECT, PORT], env=self.env(**env),
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


class TunnelUpTests(Case):
    """bench_tunnel_up / bench_tunnel_down: plan line per mode, append-only tunnel.log, the supervisor's group."""

    def run_lib(self, body, apply=True, **extra):
        env = self.env(BENCH_APPLY="1" if apply else "0", BENCH_RESULTS_DIR=str(self.results), PROJECT_ID=PROJECT,
                       BENCH_TUNNEL_PORT=PORT, RPC_URL="http://localhost:%s" % PORT, **extra)
        return subprocess.run(["bash", "-c", PRELUDE + body + "\n"], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def wait_for(self, pred, secs=10):
        end = time.time() + secs
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.1)
        return False

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
            pat = m.group(1).replace("${BENCH_TUNNEL_PORT}", PORT)
            found = subprocess.run(["pgrep", "-f", pat], stdout=subprocess.PIPE, universal_newlines=True).stdout.split()
            self.assertIn(str(pid), found)
        # A second up finds it running and starts nothing.
        p = self.run_lib("bench_tunnel_up")
        self.assertIn("tunnel already up (pid %d)" % pid, p.stdout)
        self.assertEqual(len(self.ssh_calls()), 1)
        p = self.run_lib("bench_tunnel_down")
        self.assertIn("stopped tunnel pid %d" % pid, p.stdout)
        self.assertTrue(self.wait_for(lambda: subprocess.run(["pgrep", "-g", str(pid)], stdout=subprocess.PIPE).returncode != 0),
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


if __name__ == "__main__":
    unittest.main()
