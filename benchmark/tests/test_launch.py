"""benchmark/launch/: launch.sh (one detached segment of a bench run) and run-arms.sh (the run-1 arm
walk), the env files, the default plan and run 1b's (the local-SSD deployment's) plan.

Every test builds a throwaway git tree with the real launch/ scripts, env files, run 1b's plan and arm
files and fake drivers (fixtures/launch/fake-driver.py behind each driver's path) that record their argv
and environment, print REACHED and answer from a scenario. The tree's default plan is the frozen
eight-arm walk (fixtures/launch/walk-8.plan), so a hand edit of the real plan never moves a test that
addresses arms by number; test_the_default_plan and the real-plan dry run pin the real plan, and
test_the_lssd_plan and its dry runs pin run 1b's. Shims
on PATH stand in for gcloud (the token check), pgrep (the process check: it finds nothing unless a
test says so, so the host's own processes never make a test refuse) and curl (the pool gate's
Prometheus read). Nothing here reaches a real project.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
LAUNCH = BENCH / "launch"
FIX = TESTS / "fixtures" / "launch"
RUN = "r20261112-0900"
NODES = ("bench-validator-01", "bench-validator-02", "bench-observer-11")
SH_DRIVERS = ("benchmark/benchmark-deploy.sh", "benchmark/benchmark-blast.sh", "benchmark/benchmark-teardown.sh",
              "benchmark/benchmark-probe.sh", "benchmark/tools/params-apply.sh", "benchmark/tools/archive-run.sh")
PY_DRIVERS = ("benchmark/report/make_bundle.py", "benchmark/tools/arms-summary.py", "benchmark/recovery-schedule.py")
UTC_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
FILL = {"<run-id>": RUN, "<image-digest>": "ab" * 32, "<node-sha>": "c0ffee" * 6 + "abcd", "<txgen-sha>": "1234567"}
# The default walk, plan W4 with both forms of the vote fix (G1): a step line per arm, its arm file and its steps.
# It pins the real benchmark/launch/bench6-run1.plan; the sandbox walks the frozen fixtures/launch/walk-8.plan.
DEFAULT_WALK = [("a0-control", ["I", "L", "M4", "M16"]), ("p1-mdbx-advice", ["M16"]), ("v-vote", ["L", "M16"]),
                ("v-vote-floor", ["L", "M16"]), ("pool-local", ["M16@epoch"]), ("pipe", ["M4", "M16"]),
                ("bound", ["M4", "M16"]), ("gr150", ["I", "L", "M16s"]), ("a0-prime", ["M16"])]
TYPES = {"I", "L", "M4", "M16", "M16s"}
ENV_FILES = ("bench6-run1.env", "bench6-run2.env", "bench6-probe.env", "bench6-run1-lssd.env", "bench7-always.env",
             "bench7-adaptive.env")
# Run 1b, the local-SSD deployment (option e): run 1's arms a0-control, p1-mdbx-advice and a0-prime, and run 1's env
# plus the four shape knobs below (values as the env file spells them, quotes and all) and RUN_ARMS_PLAN=LSSD_PLAN.
LSSD_PLAN = "benchmark/launch/bench6-run1-lssd.plan"
LSSD_WALK = [("a0-control", ["I", "L", "M4", "M16"]), ("p1-mdbx-advice", ["M16"]), ("a0-prime", ["M16"])]
OPTION_E = ("0:c3-standard-8 1:c3-standard-8 2:c3-standard-8-lssd 3:c3-standard-8-lssd 4:c3-standard-8-lssd "
            "5:c3-standard-8-lssd 6:c3-standard-8-lssd 9:c3-standard-8-lssd 10:c3-standard-8")
LSSD_FALLBACKS = ("2:australia-southeast1-a,australia-southeast1-b 4:us-east4-c,us-east4-a 5:europe-west4-b,europe-west4-c "
                  "6:asia-southeast1-a,asia-southeast1-c 7:asia-east1-a 8:asia-northeast3-b 9:asia-south1-b,asia-south1-a")
LSSD_SHAPE = {"BENCH_NODE_MACHINE_TYPES": '"%s"' % OPTION_E, "BENCH_NODE_DATADIR_LSSD": "1", "BENCH_FLEET": "c3-lssd6-hdb4",
              "BENCH_ZONE_FALLBACKS": '"%s"' % LSSD_FALLBACKS}


def read_plan(path):
    """A plan file's walk: [(arm, [step, ...]), ...] in line order, comments and blank lines left out."""
    walk = []
    for line in Path(path).read_text().splitlines():
        w = line.split("#", 1)[0].split()
        if w:
            walk.append((w[0], w[1:]))
    return walk


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, check=True).stdout


def pool_json(values):
    return json.dumps({"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"node": n}, "value": [0, str(v)]} for n, v in zip(NODES, values)]}})


class Tree:
    """A git tree with the launch scripts, fake drivers and shims; the run's results dir holds nodes.txt."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="test-launch-"))
        self.state = self.root / ".fake"
        for d in ("benchmark/launch", "benchmark/arms", "benchmark/tools", "benchmark/report", "tasks",
                  ".fake/state", ".fake/curl", "benchmark/results/" + RUN, "benchmark/work/probe-bin"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for f in ("launch.sh", "run-arms.sh", "bench6-run1-lssd.plan") + ENV_FILES:
            shutil.copy2(str(LAUNCH / f), str(self.root / "benchmark/launch" / f))
        shutil.copy2(str(FIX / "walk-8.plan"), str(self.root / "benchmark/launch/bench6-run1.plan"))
        for f in (BENCH / "arms").glob("*.arm"):
            shutil.copy2(str(f), str(self.root / "benchmark/arms" / f.name))
        shutil.copy2(str(BENCH / ".gitignore"), str(self.root / "benchmark/.gitignore"))
        for p in SH_DRIVERS:
            self.write(p, '#!/usr/bin/env bash\nexec python3 "${FAKE_DRIVER}" %s "$@"\n' % os.path.basename(p), 0o755)
        for p in PY_DRIVERS:
            self.write(p, "import os, sys\nos.execv(sys.executable, [sys.executable, os.environ['FAKE_DRIVER'], %r] + sys.argv[1:])\n"
                       % os.path.basename(p), 0o755)
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "tree")
        self.write("benchmark/results/%s/nodes.txt" % RUN, "".join("%s us-x1-a - validator\n" % n for n in NODES))
        self.write("benchmark/work/probe-bin/mdbx-writeback-probe", "binary\n")
        self.write("benchmark/launch/bench5/old-launcher.sh", "# an untracked bench-5 original\n")
        self.curl([0, 0, 0])
        self.scenario({})

    def write(self, rel, text, mode=None):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if mode is not None:
            os.chmod(str(p), mode)
        return p

    def scenario(self, scen):
        self.write(".fake/scenario.json", json.dumps(scen))

    def curl(self, *responses):
        d = self.state / "curl"
        for f in d.iterdir():
            f.unlink()
        for i, r in enumerate(responses):
            (d / ("%d.json" % i)).write_text(r if isinstance(r, str) else pool_json(r))

    def env(self, **extra):
        e = {"PATH": "%s:%s" % (FIX / "bin", os.environ.get("PATH", "/usr/bin:/bin")), "HOME": str(self.root),
             "LANG": "C", "FAKE_DRIVER": str(FIX / "fake-driver.py"), "FAKE_LOG": str(self.state / "calls.jsonl"),
             "FAKE_STATE": str(self.state / "state"), "FAKE_SCENARIO": str(self.state / "scenario.json"),
             "FAKE_GCLOUD_LOG": str(self.state / "gcloud.log"), "FAKE_PGREP": str(self.state / "pgrep.out"),
             "FAKE_PGREP_LOG": str(self.state / "pgrep.log"), "FAKE_CURL_DIR": str(self.state / "curl"),
             "FAKE_CURL_LOG": str(self.state / "curl.log")}
        e.update(dict((k, str(v)) for k, v in extra.items()))
        return e

    def calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def lines(self, name):
        p = self.state / name
        return p.read_text().splitlines() if p.exists() else []

    def manifest(self, m):
        self.write("benchmark/results/%s/manifest.json" % RUN, json.dumps(m))

    def cleanup(self):
        for pf in self.root.glob("tasks/bench6/*/*.pid"):
            try:
                os.killpg(int(pf.read_text().strip()), signal.SIGKILL)
            except (ValueError, OSError):
                pass
        shutil.rmtree(str(self.root), ignore_errors=True)


def wait_for(pred, secs=15.0):
    end = time.time() + secs
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.05)
    return pred()


class LaunchBase(unittest.TestCase):
    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.cleanup)
        text = (LAUNCH / "bench6-run1.env").read_text()
        for k, v in FILL.items():
            text = text.replace(k, v)
        self.envf = "tasks/test.env"
        self.t.write(self.envf, text + "LAUNCH_PROBE_BIN=benchmark/work/probe-bin/mdbx-writeback-probe\n")

    def launch(self, *args, **env):
        return subprocess.run(["bash", str(self.t.root / "benchmark/launch/launch.sh")] + list(args), cwd=str(self.t.root),
                              env=self.t.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)

    def assertRefused(self, p, why, rc=1):
        self.assertEqual(p.returncode, rc, p.stdout + p.stderr)
        self.assertIn(why, p.stderr)
        self.assertEqual(self.t.calls(), [], "a refused launch reached a driver")
        self.assertEqual(list(self.t.root.glob("tasks/bench6/*/*")), [], "a refused launch wrote a pid or log file")

    def started(self, p):
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        m = re.search(r"^LAUNCHED segment=(\S+) run=(\S+) pid=(\d+) harness=\S+ log=(\S+)$", p.stdout, re.M)
        self.assertIsNotNone(m, p.stdout)
        return int(m.group(3)), self.t.root / m.group(4)

    def rc_line(self, log, seg, secs=20.0):
        return wait_for(lambda: [l for l in log.read_text().splitlines() if l.startswith("== %s rc=" % seg)], secs)

    def the_rc_line(self, log, seg, secs=20.0):
        """The segment's rc line; an assertion (not an IndexError) when the log never got one."""
        lines = self.rc_line(log, seg, secs)
        self.assertTrue(lines, "no '== %s rc=' line in %s:\n%s" % (seg, log.name, log.read_text()[-800:]))
        return lines[0]


class LaunchRefusalTests(LaunchBase):
    def env_file(self, body):
        self.t.write("tasks/bad.env", body)
        return "tasks/bad.env"

    def test_env_lines_that_break_the_rules(self):
        cases = [("BENCH_RUN_ID=%s\nBENCH_X=$(whoami)\n" % RUN, "not allowed"),
                 ("BENCH_RUN_ID=%s\nBENCH_X=`id`\n" % RUN, "not allowed"),
                 ("BENCH_RUN_ID=%s\nBENCH_X=\"${HOME}\"\n" % RUN, "not allowed"),
                 ("BENCH_RUN_ID=%s\nBENCH_X=a b\n" % RUN, "spaces or quotes"),
                 ("BENCH_RUN_ID=%s\nBENCH_X=\"a\"b\"\n" % RUN, "quote"),
                 ("BENCH_RUN_ID=%s\nBENCH_X=\"open\n" % RUN, "unterminated"),
                 ("BENCH_RUN_ID=%s\nPATH=/tmp\n" % RUN, "only BENCH_"),
                 ("BENCH_RUN_ID=%s\nexport BENCH_X=1\n" % RUN, "bad key"),
                 ("BENCH_RUN_ID=%s\nBENCH_X=1\nBENCH_X=2\n" % RUN, "set twice"),
                 ("BENCH_RUN_ID=%s\r\n" % RUN, "carriage return"),
                 ("BENCH_X=1\n", "no BENCH_RUN_ID"),
                 ("BENCH_RUN_ID=r2026\n", "not rYYYYMMDD-HHMM"),
                 ("just words\n", "not KEY=value")]
        for body, why in cases:
            with self.subTest(body=body):
                self.assertRefused(self.launch(self.env_file(body), "deploy12"), why)

    def test_a_value_is_never_run(self):
        f = self.env_file("BENCH_RUN_ID=%s\nBENCH_X='; touch PWNED'\n" % RUN)
        p = self.launch("--dry-run", f, "reindex")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("env BENCH_X=; touch PWNED", p.stdout)
        self.assertFalse((self.t.root / "PWNED").exists())

    def test_every_shipped_env_file_is_refused_until_its_placeholders_are_filled(self):
        for f in ENV_FILES:
            with self.subTest(f=f):
                self.assertRefused(self.launch("benchmark/launch/" + f, "deploy12"), "BENCH_RUN_ID is still a placeholder")
        for f in ("bench6-run1.env", "bench6-run1-lssd.env"):
            with self.subTest(f=f, run_id="filled"):
                body = (LAUNCH / f).read_text().replace("<run-id>", RUN)
                p = self.launch(self.env_file(body), "deploy12")
                self.assertRefused(p, "placeholders not filled")
                for k in ("BENCH_DOCKER_IMAGE", "BENCH_DOCKER_IMAGE_EXPECT_DIGEST", "BENCH_NODE_EXPECT_SHA", "BENCH_TXGEN_SHA"):
                    self.assertIn(" " + k, p.stderr)

    def test_a_dirty_harness_tree(self):
        self.t.write("benchmark/arms/a0-control.arm", "name a0-control\nparam vote_queue_fix true\n")
        self.assertRefused(self.launch(self.envf, "deploy12"), "the harness tree is dirty")
        git(self.t.root, "checkout", "-q", "--", "benchmark/arms/a0-control.arm")
        self.t.write("benchmark/tools/new-tool.sh", "#!/bin/sh\n")
        self.assertRefused(self.launch(self.envf, "deploy12"), "benchmark/tools/new-tool.sh")

    def test_the_bench5_originals_and_ignored_dirs_do_not_count_as_dirty(self):
        self.t.write("benchmark/results/%s/x.json" % RUN, "{}")
        self.t.write("benchmark/work/scratch.txt", "x")
        pid, log = self.started(self.launch(self.envf, "deploy12"))
        self.assertTrue(self.rc_line(log, "deploy12"))

    def test_a_stale_token(self):
        self.assertRefused(self.launch(self.envf, "deploy12", FAKE_GCLOUD_MODE="fail"), "gcloud auth print-access-token failed")
        t0 = time.time()
        self.assertRefused(self.launch(self.envf, "arms", FAKE_GCLOUD_MODE="hang", LAUNCH_TOKEN_SECS=1), "took more than 1 s")
        self.assertLess(time.time() - t0, 15)
        self.assertIn("gcloud auth print-access-token", self.t.lines("gcloud.log")[-1])

    def test_the_token_bound_comes_from_the_env_file_first(self):
        f = self.env_file(self.t.root.joinpath(self.envf).read_text() + "LAUNCH_TOKEN_SECS=1\n")
        t0 = time.time()
        self.assertRefused(self.launch(f, "deploy12", FAKE_GCLOUD_MODE="hang", LAUNCH_TOKEN_SECS=20), "took more than 1 s")
        self.assertLess(time.time() - t0, 10)
        self.assertRefused(self.launch(self.env_file("BENCH_RUN_ID=%s\nLAUNCH_TOKEN_SECS=0\n" % RUN), "deploy12"),
                           "must be positive integers")

    def test_segments_without_gcloud_skip_the_token(self):
        for seg in ("reindex", "bundle", "arms-summary"):
            with self.subTest(seg=seg):
                pid, log = self.started(self.launch(self.envf, seg, FAKE_GCLOUD_MODE="fail"))
                self.assertTrue(self.rc_line(log, seg))
        self.assertEqual(self.t.lines("gcloud.log"), [])

    def test_a_driver_that_collides_is_running(self):
        self.t.write(".fake/pgrep.out", "4242\n")
        self.assertRefused(self.launch(self.envf, "deploy12"), "pid 4242")
        pat = self.t.lines("pgrep.log")[-1]
        self.assertIn("[b]enchmark-(deploy|blast|teardown|probe)\\.sh", pat)
        self.launch(self.envf, "bundle")
        self.assertIn("[m]ake_bundle\\.py", self.t.lines("pgrep.log")[-1])

    def test_a_segment_of_the_same_run_is_running(self):
        self.t.scenario({"benchmark-deploy.sh": [{"sleep": 30}]})
        pid, log = self.started(self.launch(self.envf, "deploy12"))
        wait_for(lambda: self.t.calls())
        p = self.launch(self.envf, "blast15")
        self.assertEqual(p.returncode, 1)
        self.assertIn("segment deploy12-", p.stderr)
        self.assertIn("is still running (pid %d)" % pid, p.stderr)
        self.assertEqual(len(self.t.calls()), 1)
        os.killpg(pid, signal.SIGTERM)
        self.assertTrue(self.rc_line(log, "deploy12"))

    def test_an_unknown_segment(self):
        p = self.launch(self.envf, "deploy")
        self.assertEqual(p.returncode, 2)
        self.assertIn("unknown segment 'deploy'", p.stderr)

    def test_the_probe_needs_its_binary(self):
        (self.t.root / "benchmark/work/probe-bin/mdbx-writeback-probe").unlink()
        self.assertRefused(self.launch(self.envf, "probe"), "LAUNCH_PROBE_BIN")


class LaunchStartTests(LaunchBase):
    def test_the_pid_file_holds_the_detached_session(self):
        self.t.scenario({"benchmark-deploy.sh": [{"sleep": 2}]})
        p = self.launch(self.envf, "deploy12")
        pid, log = self.started(p)
        pidf = Path(str(log)[:-4] + ".pid")
        self.assertEqual(int(pidf.read_text()), pid)
        self.assertRegex(log.name, r"^deploy12-\d{8}T\d{6}Z\.log$")
        self.assertIn("wait for: ^== deploy12 rc=", p.stdout)
        call = wait_for(lambda: self.t.calls())[0]
        self.assertEqual(call["ppid"], pid, "the driver is the detached shell's child")
        self.assertEqual(call["sid"], pid, "the detached shell leads its own session")
        self.assertNotEqual(os.getsid(0), pid)
        self.assertEqual(call["argv"], ["--yes", "--with-contracts", "--to", "12"])
        self.assertEqual(self.the_rc_line(log, "deploy12").split()[2], "rc=0")
        head = log.read_text().splitlines()
        self.assertRegex(head[0], r"^== deploy12 start \S+ bench6-launch:%s:deploy12 pid=%d harness=[0-9a-f]{12}$" % (RUN, pid))

    def test_the_rc_line_on_failure(self):
        self.t.scenario({"benchmark-teardown.sh": [{"rc": 3}]})
        pid, log = self.started(self.launch(self.envf, "teardown"))
        self.assertRegex(self.the_rc_line(log, "teardown"), r"^== teardown rc=3 \S+Z$")
        self.assertEqual(self.t.calls()[0]["argv"], ["--run", RUN, "--yes"])

    def test_the_rc_line_when_the_session_is_killed(self):
        self.t.scenario({"benchmark-deploy.sh": [{"sleep": 30}]})
        pid, log = self.started(self.launch(self.envf, "step15"))
        wait_for(lambda: self.t.calls())
        os.kill(pid, signal.SIGTERM)
        # without the wrapper's TERM trap the TERM ends the wrapper itself: no rc line, the driver left running
        self.assertRegex(self.the_rc_line(log, "step15"), r"^== step15 rc=143 ")
        self.assertRaises(OSError, os.kill, self.t.calls()[0]["pid"], 0)

    def test_the_rc_line_when_the_driver_is_killed(self):
        self.t.scenario({"benchmark-deploy.sh": [{"sleep": 30}]})
        pid, log = self.started(self.launch(self.envf, "blast15"))
        child = wait_for(lambda: self.t.calls())[0]["pid"]
        os.kill(child, signal.SIGKILL)
        self.assertRegex(self.the_rc_line(log, "blast15"), r"^== blast15 rc=137 ")

    def test_the_segment_gets_the_env_file_and_nothing_inherited(self):
        pid, log = self.started(self.launch(self.envf, "deploy12", BENCH_LEAK="1", RUN_ARMS_LEAK="1", BENCH_CHAOS="1"))
        self.rc_line(log, "deploy12")
        env = self.t.calls()[0]["env"]
        self.assertNotIn("BENCH_LEAK", env)
        self.assertNotIn("RUN_ARMS_LEAK", env)
        self.assertEqual(env["BENCH_CHAOS"], "0", "the env file wins over the launching shell")
        self.assertEqual(env["BENCH_RUN_ID"], RUN)
        self.assertEqual(env["BENCH_TEARDOWN_SKIP_ARCHIVE"], "1")
        self.assertEqual(env["LAUNCH_ENV_FILE"], self.envf)
        self.assertEqual(env["LAUNCH_SEGMENT"], "deploy12")
        self.assertIn("BENCH_RUN_ID=%s" % RUN, log.read_text())

    def test_logs_are_never_overwritten(self):
        logs = set()
        for _ in range(2):
            pid, log = self.started(self.launch(self.envf, "reindex"))
            self.rc_line(log, "reindex")
            logs.add(log.name)
        self.assertEqual(len(logs), 2)

    def test_every_segment_maps_to_its_driver_call(self):
        want = {"probe": "benchmark/benchmark-probe.sh all --bin benchmark/work/probe-bin/mdbx-writeback-probe",
                "deploy12": "benchmark/benchmark-deploy.sh --yes --with-contracts --to 12",
                "arms": "benchmark/launch/run-arms.sh",
                "blast15": "benchmark/benchmark-deploy.sh --yes --from 13 --to 15",
                "step15": "benchmark/benchmark-deploy.sh --yes --from 15 --to 15",
                "teardown-dry": "benchmark/benchmark-teardown.sh --run %s" % RUN,
                "teardown": "benchmark/benchmark-teardown.sh --run %s --yes" % RUN,
                "archive": "benchmark/tools/archive-run.sh --run %s" % RUN,
                "reindex": "benchmark/benchmark-teardown.sh --run %s --reindex" % RUN,
                "bundle": "python3 benchmark/report/make_bundle.py --run %s" % RUN,
                "arms-summary": "python3 benchmark/tools/arms-summary.py --run-dir benchmark/results/%s" % RUN}
        for seg, cmd in want.items():
            with self.subTest(seg=seg):
                p = self.launch("--dry-run", self.envf, seg)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("  command: %s\n" % cmd, p.stdout)
        p = self.launch("--dry-run", self.envf, "bundle", "--compare", "r20261107-1504", "--force")
        self.assertIn("make_bundle.py --run %s --compare r20261107-1504 --force\n" % RUN, p.stdout)
        self.t.write(self.envf, self.t.root.joinpath(self.envf).read_text() + "LAUNCH_PROBE_ARMS=core\n")
        self.assertIn("--bin benchmark/work/probe-bin/mdbx-writeback-probe --arms core\n",
                      self.launch("--dry-run", self.envf, "probe").stdout)

    def test_the_probe_passes_its_disks_knob(self):
        # Unset: no --disks (the driver's default, hyperdisk); set: --disks after --bin and --arms, as given.
        self.assertIn("  command: benchmark/benchmark-probe.sh all --bin benchmark/work/probe-bin/mdbx-writeback-probe\n",
                      self.launch("--dry-run", self.envf, "probe").stdout)
        self.t.write(self.envf, self.t.root.joinpath(self.envf).read_text()
                     + "LAUNCH_PROBE_ARMS=g1-node,g5,g8-nowritemap\nLAUNCH_PROBE_DISKS=both\n")
        p = self.launch("--dry-run", self.envf, "probe")
        self.assertEqual(p.returncode, 0, p.stderr)
        # (the dry run prints the argv shell-quoted: a comma reads \,)
        self.assertIn("  command: benchmark/benchmark-probe.sh all --bin benchmark/work/probe-bin/mdbx-writeback-probe"
                      " --arms g1-node\\,g5\\,g8-nowritemap --disks both\n", p.stdout)
        # The shipped probe env file leaves it unset (commented), so a launch of it runs the hyperdisk mode.
        self.assertIn("# LAUNCH_PROBE_DISKS=both\n", (LAUNCH / "bench6-probe.env").read_text())

    def test_the_probe_passes_its_zone_knob(self):
        # Unset: no --zone (the driver's default, validator-01's zone); set: --zone last, as given.
        self.assertNotIn("--zone", self.launch("--dry-run", self.envf, "probe").stdout)
        self.t.write(self.envf, self.t.root.joinpath(self.envf).read_text()
                     + "LAUNCH_PROBE_DISKS=both\nLAUNCH_PROBE_ZONE=us-west1-a\n")
        p = self.launch("--dry-run", self.envf, "probe")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("  command: benchmark/benchmark-probe.sh all --bin benchmark/work/probe-bin/mdbx-writeback-probe"
                      " --disks both --zone us-west1-a\n", p.stdout)
        self.assertIn("# LAUNCH_PROBE_ZONE=us-west1-a\n", (LAUNCH / "bench6-probe.env").read_text())

    def test_the_dry_run_starts_nothing(self):
        p = self.launch("--dry-run", self.envf, "deploy12", FAKE_GCLOUD_MODE="reached")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("DRY RUN: nothing is started", p.stdout)
        self.assertIn("  env BENCH_RUN_ID=%s\n" % RUN, p.stdout)
        self.assertNotIn("REACHED", p.stdout + p.stderr)
        self.assertEqual(self.t.lines("gcloud.log"), [])
        self.assertEqual(self.t.calls(), [])
        self.assertFalse((self.t.root / "tasks/bench6").exists())

    def test_the_dry_run_refuses_like_the_live_start(self):
        self.t.write("benchmark/stray.sh", "x")
        self.assertRefused(self.launch("--dry-run", self.envf, "deploy12"), "the harness tree is dirty")


class LaunchStatusTests(LaunchBase):
    def test_status_lists_each_segment(self):
        p = self.launch(self.envf, "status")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("(no segment launched yet)", p.stdout)
        pid, log = self.started(self.launch(self.envf, "reindex"))
        self.rc_line(log, "reindex")
        self.t.scenario({"benchmark-deploy.sh": [{"sleep": 30}]})
        pid2, log2 = self.started(self.launch(self.envf, "deploy12"))
        wait_for(lambda: len(self.t.calls()) == 2)
        d = self.t.root / "tasks/bench6" / RUN
        (d / "teardown-20261112T000000Z.pid").write_text("999999\n")
        (d / "teardown-20261112T000000Z.log").write_text("== teardown start\nsomething\n")
        out = self.launch(self.envf, "status").stdout.splitlines()
        self.assertEqual(out[0], "run %s: segments in tasks/bench6/%s" % (RUN, RUN))
        rows = dict((l.split()[1].split("-2026")[0], l) for l in out[1:])
        self.assertRegex(rows["reindex"], r"pid=%d state=ended last: == reindex rc=0 " % pid)
        self.assertRegex(rows["deploy12"], r"pid=%d state=running last: " % pid2)
        self.assertIn("state=died (no rc line) last: something", rows["teardown"])
        os.killpg(pid2, signal.SIGTERM)
        self.rc_line(log2, "deploy12")


# $1 = a copy of benchmark/config.sh (the repo-root config.sh beside its parent): what option (e) sets, one line each.
CONFIG_VIEW = r'''
set -euo pipefail
. "$1"
printf 'TYPES %s\n' "${NODE_MACHINE_TYPES[*]}"
printf 'LSSD %s\n' "${NODE_DATADIR_LSSD[*]}"
printf 'MACHINE_TYPE %s\n' "${MACHINE_TYPE}"
printf 'FLEET %s\n' "${BENCH_FLEET}"
printf 'ZONES %s\n' "${ZONES[*]}"
printf 'FALLBACKS %s\n' "${BENCH_ZONE_FALLBACKS}"
'''


class LssdLaunchTests(LaunchBase):
    """Run 1b (bench6-run1-lssd.env, bench6-run1-lssd.plan) through launch.sh: the walk's dry run started as a live
    segment reaches no driver, and the env as launch.sh exports it loads in benchmark/config.sh as option (e)."""

    def setUp(self):
        super().setUp()
        text = (LAUNCH / "bench6-run1-lssd.env").read_text()
        for k, v in FILL.items():
            text = text.replace(k, v)
        self.lssd = "tasks/lssd.env"
        self.t.write(self.lssd, text)

    def test_the_walk_dry_run_as_a_segment_reaches_no_driver(self):
        # No --plan: the env file's RUN_ARMS_PLAN picks run 1b's walk (the sandbox's default plan has eight arms).
        pid, log = self.started(self.launch(self.lssd, "arms", "--dry-run"))
        self.assertRegex(self.the_rc_line(log, "arms", 90), r"^== arms rc=0 ")
        text = log.read_text()
        self.assertEqual(self.t.calls(), [])
        self.assertNotIn("REACHED", text)
        self.assertEqual(self.t.lines("gcloud.log"), ["gcloud auth print-access-token"])    # the launcher's token check
        self.assertIn("== arms command: benchmark/launch/run-arms.sh --dry-run\n", text)
        self.assertIn("\n    RUN_ARMS_PLAN=%s\n" % LSSD_PLAN, text)
        self.assertIn("\nBENCH_NODE_MACHINE_TYPES=%s\n" % OPTION_E, text)
        self.assertIn("DRY RUN: run-arms walks %s on %s; nothing is called\n" % (LSSD_PLAN, RUN), text)
        self.assertIn("\nDRY RUN END: 3 arm(s), 6 step(s), 5 blast(s)\n", text)

    def config_view(self, dry_stdout):
        """benchmark/config.sh sourced (as benchmark-deploy.sh) with exactly the environment a launch dry run printed."""
        env = dict(l[len("  env "):].split("=", 1) for l in dry_stdout.splitlines() if l.startswith("  env "))
        self.assertIn("BENCH_RUN_ID", env, dry_stdout)
        cfg = self.t.root / ".fake/cfg"
        if not cfg.exists():
            (cfg / "benchmark").mkdir(parents=True)
            shutil.copy2(str(REPO / "config.sh"), str(cfg / "config.sh"))
            for f in ("config.sh", "consensus-parameters.yaml"):
                shutil.copy2(str(BENCH / f), str(cfg / "benchmark" / f))
        p = subprocess.run(["bash", "-c", CONFIG_VIEW, "benchmark-deploy.sh", str(cfg / "benchmark/config.sh")],
                           env=self.t.env(**env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout)
        keys = ("TYPES", "LSSD", "MACHINE_TYPE", "FLEET", "ZONES", "FALLBACKS")
        return dict(l.split(" ", 1) for l in p.stdout.splitlines() if l.split(" ", 1)[0] in keys)

    def test_the_env_as_launch_exports_it_loads_in_config_as_option_e(self):
        p = self.launch("--dry-run", self.lssd, "arms", "--plan", LSSD_PLAN)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("  command: benchmark/launch/run-arms.sh --plan %s\n" % LSSD_PLAN, p.stdout)
        got = self.config_view(p.stdout)
        run1 = self.config_view(self.launch("--dry-run", self.envf, "arms").stdout)
        std, lssd, hc = "c3-standard-8", "c3-standard-8-lssd", "c3-highcpu-8"
        self.assertEqual(got["TYPES"].split(), [std, std, lssd, lssd, lssd, lssd, lssd, hc, hc, lssd, std])
        self.assertEqual(got["LSSD"].split(), ["0", "0", "1", "1", "1", "1", "1", "0", "0", "1", "0"])
        self.assertEqual(got["FLEET"], "c3-lssd6-hdb4")
        self.assertEqual(got["FALLBACKS"], LSSD_FALLBACKS)
        # run 1's default machine type (validators 08 and 09 keep it) and run 1's zones: nothing moved
        self.assertEqual(run1["TYPES"].split(), [hc] * 11)
        self.assertEqual(run1["LSSD"].split(), ["0"] * 11)
        self.assertEqual((got["MACHINE_TYPE"], got["ZONES"]), (hc, run1["ZONES"]))
        self.assertEqual(self.t.lines("gcloud.log"), [])


class ArmsBase(unittest.TestCase):
    """run-arms.sh against the fake drivers, with fast knobs."""

    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.cleanup)

    def arms(self, *args, **env):
        e = {"BENCH_RUN_ID": RUN, "BENCH_TAIL_SCAN_SECS": "180", "RUN_ARMS_IDLE_SECS": "0", "RUN_ARMS_POOL_POLL_SECS": "1",
             "RUN_ARMS_POOL_WAIT_SECS": "2", "RUN_ARMS_HEALTH_SECS": "20", "RUN_ARMS_READY_MAX_WAIT_SECS": "30"}
        e.update(env)
        p = subprocess.run(["bash", str(self.t.root / "benchmark/launch/run-arms.sh")] + list(args), cwd=str(self.t.root),
                           env=self.t.env(**e), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=180)
        p.tags = [l for l in p.stdout.splitlines() if l.startswith("ARMS_")]
        return p

    def reset(self):
        """Forget every call and scenario position (a new subtest on the same tree)."""
        shutil.rmtree(str(self.t.state / "state"))
        (self.t.state / "state").mkdir()
        for f in ("calls.jsonl", "curl.log", "curl/count"):
            if (self.t.state / f).exists():
                (self.t.state / f).unlink()

    def plan(self, text):
        self.t.write("tasks/test.plan", text)
        return "tasks/test.plan"

    def keys(self):
        return [c["key"] for c in self.t.calls()]

    def stopped(self, p, reason, k, step, arm=None):
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.tags[-2], r"^ARMS_STOPPED arm=%s step=%s reason=%s \S+Z$"
                         % (re.escape(arm) if arm else r"\S+", step, re.escape(reason)))
        self.assertTrue(p.stdout.rstrip("\n").splitlines()[-1].startswith("ARMS_RESUME "), p.stdout)
        self.assertRegex(p.tags[-1], r"--(from|only)-arm %s( |$)" % k)


def walk_render(p, calls):
    tags = [UTC_RE.sub("<UTC>", re.sub(r"wait=\d+", "wait=<s>", l)) for l in p.tags]
    out = ["# tags"] + tags + ["# driver calls"]
    keep = ("BENCH_RUN_INDEX", "BENCH_BLAST_KIND", "BENCH_SENDERS", "BENCH_WINDOW", "BENCH_WARMUP_SECS",
            "BENCH_DURATION_SECS", "BENCH_COOLDOWN_SECS", "BENCH_TAIL_SCAN_SECS", "BENCH_LIGHT_LOAD", "BENCH_CHAOS",
            "BENCH_LAG_INJECT", "BENCH_LOG_RATE_CHECK")
    for c in calls:
        argv = list(c["argv"])
        if c["name"] == "recovery-schedule.py":
            argv[argv.index("--earliest-kill") + 1] = "<now+30+lead-1>"
        line = "%s %s" % (c["name"], " ".join(argv))
        if c["key"] in ("blast:fund", "blast:run"):
            line += " | " + " ".join("%s=%s" % (k, c["env"][k]) for k in keep)
        out.append(line)
    return "\n".join(out) + "\n"


class ArmsWalkTests(ArmsBase):
    def golden(self, name, text):
        g = FIX / name
        if os.environ.get("UPDATE_GOLDEN") == "1" or not g.exists():
            g.write_text(text)
        self.assertEqual(text, g.read_text(), "the walk differs from %s (review, then UPDATE_GOLDEN=1)" % g)

    def test_the_default_plan_walk(self):
        self.t.scenario({"recovery-schedule.py": [{"delta": -29}]})
        p = self.arms()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr)
        self.assertRegex(p.tags[-1], r"^ARMS_DONE arms=8 blasts=14 \S+Z$")
        self.golden("walk-default.golden", walk_render(p, self.t.calls()))
        # every blast its own index, counting up; fund then run under the same one
        idx = [c["env"]["BENCH_RUN_INDEX"] for c in self.t.calls() if c["key"] == "blast:fund"]
        self.assertEqual(idx, [str(i) for i in range(14)])

    def test_the_dry_run_prints_the_walk_and_reaches_no_driver(self):
        p = self.arms("--dry-run", FAKE_GCLOUD_MODE="reached")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.t.calls(), [])
        self.assertEqual(self.t.lines("gcloud.log") + self.t.lines("curl.log"), [])
        self.assertNotIn("REACHED", p.stdout)
        self.assertNotIn("ARMS_STEP", p.stdout)
        self.assertNotRegex(p.stdout, r"(?m)^ARMS_")
        out = UTC_RE.sub("<UTC>", p.stdout)
        out = re.sub(r"(?m)^    (FAKE|PATH|HOME|LANG)\S*\n", "", out)
        self.golden("walk-dry.golden", out)

    def test_the_real_plan_walks_in_a_dry_run(self):
        # The sandbox's default plan is the frozen walk-8; this walks the real one as it stands, hand edits and all.
        self.dry_walk_of_the_real("benchmark/launch/bench6-run1.plan")

    def test_the_lssd_plan_walks_in_a_dry_run(self):
        p = self.dry_walk_of_the_real(LSSD_PLAN, "--plan", LSSD_PLAN)
        self.assertIn("DRY RUN: run-arms walks %s on %s; nothing is called\n" % (LSSD_PLAN, RUN), p.stdout)
        self.assertRegex(p.stdout, r"(?m)^DRY RUN END: 3 arm\(s\), 6 step\(s\), 5 blast\(s\)$")

    def test_run_arms_plan_is_the_walk_when_no_plan_is_given(self):
        # An env file pins its run's walk with RUN_ARMS_PLAN; --plan beats it; unset or empty, the default plan walks
        # with every printed line as before (the empty knob shows only in the inherited environment).
        def norm(out):
            return UTC_RE.sub("<UTC>", out)
        p = self.arms("--dry-run", RUN_ARMS_PLAN=LSSD_PLAN)
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr)
        self.assertIn("DRY RUN: run-arms walks %s on %s; nothing is called\n" % (LSSD_PLAN, RUN), p.stdout)
        self.assertRegex(p.stdout, r"(?m)^DRY RUN END: 3 arm\(s\), 6 step\(s\), 5 blast\(s\)$")
        unset = self.arms("--dry-run")
        self.assertEqual(unset.returncode, 0, unset.stderr)
        self.assertIn("DRY RUN: run-arms walks benchmark/launch/bench6-run1.plan on %s; nothing is called\n" % RUN,
                      unset.stdout)
        self.assertRegex(unset.stdout, r"(?m)^DRY RUN END: 8 arm\(s\), ")
        self.assertNotIn("RUN_ARMS_PLAN", unset.stdout)
        beat = self.arms("--dry-run", "--plan", "benchmark/launch/bench6-run1.plan", RUN_ARMS_PLAN=LSSD_PLAN).stdout
        self.assertIn("\n    RUN_ARMS_PLAN=%s\n" % LSSD_PLAN, beat)
        self.assertEqual(norm(beat.replace("    RUN_ARMS_PLAN=%s\n" % LSSD_PLAN, "")), norm(unset.stdout))
        p = self.arms("--dry-run", "--plan", self.plan("v-vote L\n"), RUN_ARMS_PLAN=LSSD_PLAN)
        self.assertIn("DRY RUN: run-arms walks tasks/test.plan on %s;" % RUN, p.stdout)
        self.assertRegex(p.stdout, r"(?m)^DRY RUN END: 1 arm\(s\), 1 step\(s\), 1 blast\(s\)$")
        empty = self.arms("--dry-run", RUN_ARMS_PLAN="")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertIn("\n    RUN_ARMS_PLAN=\n", empty.stdout)
        self.assertEqual(norm(empty.stdout.replace("    RUN_ARMS_PLAN=\n", "")), norm(unset.stdout))
        self.assertEqual(self.t.calls(), [])

    def dry_walk_of_the_real(self, rel, *args):
        """run-arms --dry-run [args] on the repo's plan <rel> as it stands (copied to the same path in the sandbox):
        every arm applied under its recorded name, one run per blast step, the END line's counts."""
        shutil.copy2(str(REPO / rel), str(self.t.root / rel))
        walk = read_plan(REPO / rel)
        p = self.arms("--dry-run", *args)
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr)
        self.assertEqual(self.t.calls(), [])
        want, used = [], set()
        for arm, _ in walk:
            f = arm if "/" in arm else "benchmark/arms/%s.arm" % re.sub(r"\.arm$", "", arm)
            name = re.search(r"(?m)^name (\S+)$", (REPO / f).read_text()).group(1)
            c, n = name, 1
            while c in used:  # an arm on a second line is recorded as <name>-r2
                n += 1
                c = "%s-r%d" % (name, n)
            used.add(c)
            want.append((f, c))
        applies = re.findall(r"(?m)^  step 0  benchmark/tools/params-apply\.sh --from-config --arm-file (\S+) --arm (\S+);",
                             p.stdout)
        self.assertEqual(applies, want)
        blasts = sum(1 for _, steps in walk for s in steps if s != "I")
        self.assertEqual(len(re.findall(r"(?m)^ +env .* benchmark/benchmark-blast\.sh run --yes ", p.stdout)), blasts)
        self.assertRegex(p.stdout, r"(?m)^DRY RUN END: %d arm\(s\), %d step\(s\), %d blast\(s\)$"
                         % (len(walk), sum(len(steps) for _, steps in walk), blasts))
        return p


class ArmsStopTests(ArmsBase):
    ONE = "a0-control I\n"

    def test_a_node_that_fails_its_restart_or_readback(self):
        for out, node in ((["PA_FAIL bench-validator-02 readback max=1 is not 2"], "bench-validator-02"),
                          (["      PARAMS_FAIL bench-observer-11 telcoin did not come back"], "bench-observer-11")):
            with self.subTest(node=node):
                self.reset()
                self.t.scenario({"pa:arm-file": [{"rc": 1, "out": out}]})
                p = self.arms("--plan", self.plan("v-vote M16\n"))
                self.stopped(p, "node-failed-" + node, 0, 0, "v-vote")
                self.assertNotIn("blast:fund", self.keys())

    def test_two_guard_deferrals(self):
        self.t.scenario({"pa:arm-file": [{"out": ["      PA_GUARD_DEFER bench-validator-01 all 8 samples refused; again in 60 s",
                                                  "      PA_GUARD_DEFER bench-validator-03 all 8 samples refused; again in 60 s",
                                                  "ARM_READY {arm} ready={ready} restarted=11 nodes=11"]}]})
        p = self.arms("--plan", self.plan("v-vote M16\n"))
        self.stopped(p, "guard-deferred-twice", 0, 0)
        self.assertNotIn("blast:fund", self.keys())

    def test_one_guard_deferral_goes_on(self):
        self.t.scenario({"pa:arm-file": [{"out": ["      PA_GUARD_DEFER bench-validator-01 all 8 samples refused; again in 60 s",
                                                  "ARM_READY {arm} ready={ready} restarted=11 nodes=11"]}]})
        self.assertEqual(self.arms("--plan", self.plan(self.ONE)).returncode, 0)

    def test_a_tool_exit_and_a_missing_ready_line(self):
        for resp, reason in (({"rc": 2, "out": ["params-apply: bad"]}, "apply-rc2"), ({"out": ["nothing"]}, "no-arm-ready")):
            with self.subTest(reason=reason):
                self.reset()
                self.t.scenario({"pa:arm-file": [resp]})
                self.stopped(self.arms("--plan", self.plan(self.ONE)), reason, 0, 0)
        self.t.scenario({"pa:mark": [{"rc": 1}]})
        self.reset()
        p = self.arms("--plan", self.plan(self.ONE))
        self.stopped(p, "mark-rc1", 0, 1)
        self.assertNotIn("pa:end-mark", self.keys())

    def test_an_arm_file_the_tool_refuses(self):
        self.t.scenario({"pa:print-state": [{}, {"rc": 1, "out": ["params-apply: x.arm:3: unknown key"]}]})
        p = self.arms("--plan", self.plan("a0-control I\np1-mdbx-advice M16\n"))
        self.stopped(p, "arm-file-refused-p1-mdbx-advice", 0, 0)
        self.assertEqual(self.keys(), ["pa:print-state", "pa:print-state"])

    def test_health_between_steps(self):
        # the console's line (behind the journal's syslog prefix, the fake driver's default) and the bare one
        for bare in (False, True):
            for status, reason in (({"bench-validator-02": [90, 0]}, "disk-bench-validator-02-90pct"),
                                   ({"bench-observer-11": [40, 2]}, "fatal-db-bench-observer-11")):
                with self.subTest(reason=reason, bare=bare):
                    self.reset()
                    self.t.scenario({"blast:status": [{"bare": bare}, {"status": status, "bare": bare}]})
                    p = self.arms("--plan", self.plan("a0-control I L\n"))
                    self.stopped(p, reason, 0, 1)
                    self.assertIn("--from-step 2", p.tags[-1])
                    self.assertNotIn("blast:fund", self.keys())

    def test_both_status_line_forms_print_the_same_health(self):
        got = {}
        for bare in (False, True):
            self.reset()
            self.t.manifest({})
            self.t.scenario({"blast:status": [{"bare": bare}, {"bare": bare}]})
            p = self.arms("--plan", self.plan(self.ONE))
            self.assertEqual(p.returncode, 0, p.stdout)
            got[bare] = [UTC_RE.sub("<UTC>", l) for l in p.tags if l.startswith("ARMS_HEALTH")]
        self.assertEqual(got[False], got[True])
        self.assertEqual(got[True], ["ARMS_HEALTH arm=a0-control after=%d verdict=ok read=3/3 disk_max=40 (bench-validator-01) "
                                     "fatal_db=0 <UTC>" % a for a in (0, 1)])

    def test_an_unreadable_health_check_goes_on(self):
        self.t.scenario({"blast:status": [{"rc": 1, "out": ["ERROR: gcloud"]}, {"out": []}]})
        p = self.arms("--plan", self.plan(self.ONE))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual([l.split()[3] for l in p.tags if l.startswith("ARMS_HEALTH")], ["verdict=unknown"] * 2)

    def test_a_check_that_read_nothing_prints_no_fatal_db(self):
        self.t.scenario({"blast:status": [{"rc": 1, "out": ["ERROR: gcloud"]}, {"out": []}]})
        p = self.arms("--plan", self.plan(self.ONE))
        self.assertEqual(p.returncode, 0, p.stdout)
        for l in [l for l in p.tags if l.startswith("ARMS_HEALTH")]:
            self.assertRegex(l, r" verdict=unknown read=0/3 disk_max=\? fatal_db=\? \S+Z$")

    def test_a_status_that_answers_but_parses_nowhere_stops(self):
        # rc 0 and a line per node, none in a form the check reads (a tab after the marker): a parser
        # fault, stopped at the first check (after the apply), before any step
        lines = ["    %s: 2026-11-12T16:49:45.123456+00:00 %s bench-node-sampler.sh[1234]: BENCH_STATUS\thost=%s "
                 "root_used_pct=95 fatal_db=3 block=100" % (n, n, n) for n in NODES]
        self.t.scenario({"blast:status": [{"out": lines}]})
        p = self.arms("--plan", self.plan(self.ONE))
        self.stopped(p, "health-unparsed", 0, 0)
        self.assertRegex(p.tags[-3], r"^ARMS_HEALTH arm=\S+ after=0 verdict=stop read=0/3 disk_max=\? fatal_db=\? \S+Z$")
        self.assertIn("printed 3 BENCH_STATUS line(s) and the check parsed none", p.stdout)
        self.assertNotIn("--from-step", p.tags[-1])
        self.assertEqual(self.keys(), ["pa:print-state", "pa:arm-file", "blast:status"])

    def test_the_health_check_is_off_at_zero(self):
        p = self.arms("--plan", self.plan(self.ONE), RUN_ARMS_HEALTH_SECS="0")
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("blast:status", self.keys())

    def test_a_commit_stall_after_a_blast(self):
        self.t.scenario({"blast:run": [{"stall": {"start": "2026-11-12T10:00:00Z", "secs": 121, "block": 5}}]})
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16 L\n"))
        self.stopped(p, "commit-stall", 0, 1)
        self.assertIn("--from-step 2", p.tags[-1])
        self.reset()
        self.t.manifest({})
        self.t.scenario({"blast:run": [{"stall": {"start": "2026-11-12T10:00:00Z", "secs": 120, "block": 5}}]})
        self.assertEqual(self.arms("--plan", self.plan("p1-mdbx-advice M16\n")).returncode, 0)

    def test_a_blast_that_aborts_on_fleet_health_is_not_retried(self):
        for reason in ("disk-full", "batch-cache-cliff", "quorum-lost", "node-stalled", "obs-memory"):
            with self.subTest(reason=reason):
                self.reset()
                self.t.manifest({})
                self.t.scenario({"blast:run": [{"rc": 1, "manifest": {"abort": {"reason": reason}}}]})
                p = self.arms("--plan", self.plan("p1-mdbx-advice M16\n"))
                self.stopped(p, "blast-abort-" + reason, 0, 1)
                self.assertEqual(self.keys().count("blast:run"), 1)
                self.assertNotIn("ARMS_RETRY", p.stdout)


class ArmsRetryTests(ArmsBase):
    def test_a_failed_blast_is_retried_once_under_the_next_index(self):
        self.t.scenario({"blast:run": [{"rc": 1, "manifest": {"abort": {"reason": "late_create", "unsent": True}}}]})
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16\n"))
        self.assertEqual(p.returncode, 0, p.stdout)
        runs = [c for c in self.t.calls() if c["key"] in ("blast:fund", "blast:run")]
        self.assertEqual([(c["key"], c["env"]["BENCH_RUN_INDEX"]) for c in runs],
                         [("blast:fund", "0"), ("blast:run", "0"), ("blast:fund", "1"), ("blast:run", "1")])
        self.assertTrue(all(c["env"]["BENCH_SENDERS"] == "600" and c["env"]["BENCH_WINDOW"] == "16" for c in runs))
        self.assertIn("ARMS_RETRY arm=p1-mdbx-advice step=1 kind=M16 index=1 reason=run-rc1-late_create", p.tags)
        self.assertRegex([l for l in p.tags if l.startswith("ARMS_STEP")][1], r"step=1 kind=M16 rc=0 ")

    def test_a_failed_fund_is_retried_too(self):
        self.t.scenario({"blast:fund": [{"rc": 1}]})
        p = self.arms("--plan", self.plan("v-vote L\n"))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.keys().count("blast:fund"), 2)
        self.assertEqual(self.keys().count("blast:run"), 1)
        self.assertIn("reason=fund-rc1", [l for l in p.tags if l.startswith("ARMS_RETRY")][0])

    def test_a_second_failure_stops_the_run(self):
        self.t.scenario({"blast:run": [{"rc": 1}, {"rc": 1}]})
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16 L\n"))
        self.stopped(p, "blast-failed-twice", 0, 1)
        self.assertEqual(self.keys().count("blast:run"), 2)
        self.assertNotIn("pa:close-arm", self.keys())


class ArmsGateTests(ArmsBase):
    def test_the_pool_gate_waits_until_every_node_is_below(self):
        self.t.curl([10, 1500, 3], [10, 999, 3])
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16\n"), RUN_ARMS_POOL_WAIT_SECS="5")
        self.assertEqual(p.returncode, 0, p.stdout)
        pool = [l for l in p.tags if l.startswith("ARMS_POOL")]
        self.assertRegex(pool[0], r"verdict=high queued_max=1500 \(bench-validator-02\) read=3/3 limit=1000 ")
        self.assertRegex(pool[1], r"verdict=ok queued_max=999 ")
        q = self.t.lines("curl.log")[0]
        self.assertIn("query=max by (node) (reth_transaction_pool_queued_pool_transactions{network=\"bench\"})", q)
        self.assertIn("http://127.0.0.1:19090/api/v1/query", q)

    def test_the_pool_gate_stops_the_run_when_the_pools_stay_high(self):
        self.t.curl([1000, 0, 0])
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16\n"))
        self.stopped(p, "pool-queued", 0, 1)
        self.assertEqual(self.keys().count("blast:fund"), 1)
        self.assertNotIn("blast:run", self.keys())

    def test_unreadable_pools_go_on_at_the_deadline(self):
        self.t.curl("FAIL")
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16\n"))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("verdict=unknown", [l for l in p.tags if l.startswith("ARMS_POOL")][-1])
        self.t.curl([0, 0])  # two of three nodes: unknown, not ok
        self.reset()
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16\n"))
        self.assertIn("read=2/3", [l for l in p.tags if l.startswith("ARMS_POOL")][0])

    def test_the_gate_runs_before_saturated_blasts_only_and_is_off_at_zero(self):
        self.arms("--plan", self.plan("v-vote L M4 M16s\n"))
        self.assertEqual(len(self.t.lines("curl.log")), 2)
        (self.t.state / "curl.log").unlink()
        self.arms("--plan", self.plan("v-vote M16\n"), RUN_ARMS_MAX_QUEUED="0")
        self.assertEqual(self.t.lines("curl.log"), [])


class ArmsTimingTests(ArmsBase):
    def test_it_waits_until_the_arm_is_ready(self):
        self.t.scenario({"pa:arm-file": [{"ready_in": 3}]})
        p = self.arms("--plan", self.plan("a0-control I\n"))
        self.assertEqual(p.returncode, 0, p.stdout)
        calls = self.t.calls()
        apply = [c for c in calls if c["key"] == "pa:arm-file"][0]
        mark = [c for c in calls if c["key"] == "pa:mark"][0]
        self.assertGreaterEqual(mark["t"] - apply["t"], 2.0)
        self.assertRegex([l for l in p.tags if l.startswith("ARMS_READY")][0], r"wait=[23] *$")

    def test_a_ready_time_too_far_off(self):
        # just past the limit, so a walk that ignored it would wait ~15 s and finish (an assertion, not a timeout)
        self.t.scenario({"pa:arm-file": [{"ready_in": 15}]})
        p = self.arms("--plan", self.plan("a0-control I\n"), RUN_ARMS_READY_MAX_WAIT_SECS="5")
        self.stopped(p, "ready-too-far", 0, 0)
        self.assertNotIn("pa:mark", self.keys())

    def test_an_epoch_aligned_blast(self):
        self.t.scenario({"recovery-schedule.py": [{"delta": -28}]})
        t0 = time.time()
        p = self.arms("--plan", self.plan("pool-local M16@epoch\n"))
        self.assertEqual(p.returncode, 0, p.stdout)
        calls = self.t.calls()
        sched = [c for c in calls if c["name"] == "recovery-schedule.py"][0]
        ek = int(sched["argv"][sched["argv"].index("--earliest-kill") + 1])
        lead = 240 + 120 + 90 + 300
        self.assertAlmostEqual(ek, sched["t"] + 30 + lead - 1, delta=3)
        self.assertEqual(sched["argv"][:2], ["--rpc-url", "http://localhost:18545"])
        self.assertIn("--before-close 1 --downtime 2", " ".join(sched["argv"]))
        run = [c for c in calls if c["key"] == "blast:run"][0]
        self.assertGreaterEqual(run["t"], ek + 1 - 28 - lead - 0.5)
        ep = [l for l in p.tags if l.startswith("ARMS_EPOCH")][0]
        self.assertRegex(ep, r"offset=240 lead=750$")
        self.assertLess(time.time() - t0, 60)

    def test_an_epoch_read_that_fails_or_is_too_far(self):
        self.t.scenario({"recovery-schedule.py": [{"rc": 1, "out": ["cannot measure recovery schedule"]}]})
        p = self.arms("--plan", self.plan("pool-local M16@epoch\n"))
        self.stopped(p, "epoch-unreadable", 0, 1)
        self.assertNotIn("blast:run", self.keys())
        self.reset()
        self.t.scenario({"recovery-schedule.py": [{"delta": 100}]})
        p = self.arms("--plan", self.plan("pool-local M16@epoch\n"), RUN_ARMS_EPOCH_WAIT_MAX_SECS="60")
        self.stopped(p, "epoch-wait-too-long", 0, 1)


class ArmsResumeTests(ArmsBase):
    def test_from_arm_starts_there_under_a_new_name_when_recorded(self):
        p = self.arms("--from-arm", "6")
        self.assertEqual(p.returncode, 0, p.stdout)
        applied = [c["argv"] for c in self.t.calls() if c["key"] == "pa:arm-file"]
        self.assertEqual([a[a.index("--arm") + 1] for a in applied], ["gr150", "a0-prime"])
        self.reset()
        self.t.manifest({"param_arms": [{"name": "gr150"}, {"name": "gr150-r2"}], "blast_runs": [{"index": 4}]})
        p = self.arms("--from-arm", "gr150", "--from-step", "3")
        self.assertEqual(p.returncode, 0, p.stdout)
        calls = self.t.calls()
        applied = [c["argv"] for c in calls if c["key"] == "pa:arm-file"]
        self.assertEqual([a[a.index("--arm") + 1] for a in applied], ["gr150-r3", "a0-prime"])
        self.assertNotIn("pa:mark", [c["key"] for c in calls], "steps 1 and 2 of gr150 are skipped")
        first = [c for c in calls if c["key"] == "blast:fund"][0]
        self.assertEqual((first["env"]["BENCH_DURATION_SECS"], first["env"]["BENCH_RUN_INDEX"]), ("300", "5"))

    def test_only_arm_runs_one_arm(self):
        self.t.scenario({"recovery-schedule.py": [{"delta": -29}]})
        p = self.arms("--only-arm", "3")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual([c["key"] for c in self.t.calls() if c["key"].startswith("pa:")],
                         ["pa:print-state", "pa:arm-file", "pa:close-arm"])
        self.assertRegex(p.tags[-1], r"^ARMS_DONE arms=1 blasts=1 ")

    def test_the_next_index_follows_what_the_run_used(self):
        self.t.manifest({"blasts": [{"index": 2}], "fund": {"run_index": 3}})
        (self.t.root / "benchmark/results" / RUN / "blast-7-20261112T010203Z").mkdir()
        self.arms("--plan", self.plan("v-vote L\n"))
        self.assertEqual([c["env"]["BENCH_RUN_INDEX"] for c in self.t.calls() if c["key"] == "blast:fund"], ["8"])

    def test_the_last_line_is_the_resume_command(self):
        self.t.scenario({"pa:arm-file": [{}, {"rc": 1, "out": ["PA_FAIL bench-validator-01 x"]}]})
        p = self.arms("--plan", "benchmark/launch/bench6-run1.plan", "--from-arm", "2", LAUNCH_ENV_FILE="tasks/run1.env")
        self.stopped(p, "node-failed-bench-validator-01", 3, 0, "pool-local")
        self.assertEqual(p.stdout.splitlines()[-1],
                         "ARMS_RESUME benchmark/launch/launch.sh tasks/run1.env arms --plan benchmark/launch/bench6-run1.plan --from-arm 3")
        self.reset()
        self.t.scenario({"blast:run": [{}, {"rc": 1}, {"rc": 1}]})
        p = self.arms("--only-arm", "4")
        self.assertEqual(p.stdout.splitlines()[-1],
                         "ARMS_RESUME BENCH_RUN_ID=%s benchmark/launch/run-arms.sh --plan benchmark/launch/bench6-run1.plan "
                         "--only-arm 4 --from-step 2" % RUN)
        # the printed command resumes at that step
        self.reset()
        p = self.arms("--plan", "benchmark/launch/bench6-run1.plan", "--only-arm", "4", "--from-step", "2")
        self.assertEqual(p.returncode, 0, p.stdout)
        fund = [c for c in self.t.calls() if c["key"] == "blast:fund"]
        self.assertEqual([c["env"]["BENCH_WINDOW"] for c in fund], ["16"])

    def test_the_resume_line_names_the_plan_the_env_picked(self):
        # A walk of RUN_ARMS_PLAN (no --plan) prints a resume command with --plan <that plan>, so the resume walks the
        # same plan whatever the variable holds then. Arm 2 of run 1b's plan is a0-prime (v-vote in the sandbox's).
        fail = {"pa:arm-file": [{"rc": 1, "out": ["PA_FAIL bench-validator-01 x"]}]}
        self.t.scenario(fail)
        p = self.arms("--from-arm", "2", LAUNCH_ENV_FILE="tasks/lssd.env", RUN_ARMS_PLAN=LSSD_PLAN)
        self.stopped(p, "node-failed-bench-validator-01", 2, 0, "a0-prime")
        self.assertRegex(p.tags[0], r"^ARMS_START plan=%s run=%s arms=2\.\.2 " % (re.escape(LSSD_PLAN), RUN))
        self.assertEqual(p.stdout.splitlines()[-1],
                         "ARMS_RESUME benchmark/launch/launch.sh tasks/lssd.env arms --plan %s --from-arm 2" % LSSD_PLAN)
        self.reset()
        self.t.scenario(fail)
        p = self.arms("--from-arm", "2", RUN_ARMS_PLAN=LSSD_PLAN)
        self.stopped(p, "node-failed-bench-validator-01", 2, 0, "a0-prime")
        self.assertEqual(p.stdout.splitlines()[-1],
                         "ARMS_RESUME BENCH_RUN_ID=%s benchmark/launch/run-arms.sh --plan %s --from-arm 2" % (RUN, LSSD_PLAN))
        # the printed command, with the variable unset, resumes the same walk at the same arm
        self.reset()
        self.t.scenario({})
        p = self.arms("--plan", LSSD_PLAN, "--from-arm", "2")
        self.assertEqual(p.returncode, 0, p.stdout)
        applied = [c["argv"] for c in self.t.calls() if c["key"] == "pa:arm-file"]
        self.assertEqual([a[a.index("--arm") + 1] for a in applied], ["a0-prime"])
        self.assertRegex(p.tags[-1], r"^ARMS_DONE arms=1 blasts=1 ")

    def test_bad_arguments_and_plans_are_refused_before_anything(self):
        bad = [(["--from-arm", "9"], "past the plan's last arm"), (["--from-arm", "nope"], "no arm named"),
               (["--from-arm", "1", "--only-arm", "2"], "not both"), (["--from-step", "2"], "needs --from-arm"),
               (["--only-arm", "1", "--from-step", "3"], "has 1 step"), ("a0-control X\n", "unknown step 'X'"),
               ("a0-control L@epoch\n", "@epoch only on M16"), ("a0-control\n", "has no step"),
               ("nope M16\n", "does not exist"), ("# nothing\n", "lists no arm"), (["--bogus"], "unknown argument")]
        for args, why in bad:
            with self.subTest(args=args):
                p = self.arms(*(args if isinstance(args, list) else ["--plan", self.plan(args)]))
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn(why, p.stderr)
        self.assertEqual(self.t.calls(), [])
        p = self.arms(BENCH_RUN_ID="")
        self.assertEqual(p.returncode, 2)


class ArmsLogTests(ArmsBase):
    """D3 (H13): the walk's own log is part of the run. From ARMS_START on, everything run-arms prints is also appended
    to results/<run>/logs/run-arms-<segment>-<UTC>.log as it is printed (<segment>: LAUNCH_SEGMENT, else hand),
    so the archive and the bundle carry it and a killed walk leaves it; the caller still sees every line."""

    LOG_RE = r"^run-arms-%s-\d{8}T\d{6}Z\.log$"

    def walk_logs(self):
        return sorted((self.t.root / "benchmark/results" / RUN / "logs").glob("run-arms-*.log"))

    def test_the_retry_and_the_stop_are_in_the_results_log(self):
        self.t.scenario({"blast:run": [{"rc": 1}, {"rc": 1}]})
        p = self.arms("--plan", self.plan("p1-mdbx-advice M16 L\n"))
        self.stopped(p, "blast-failed-twice", 0, 1)
        logs = self.walk_logs()
        self.assertEqual(len(logs), 1, logs)
        self.assertRegex(logs[0].name, self.LOG_RE % "hand")
        text = logs[0].read_text()
        self.assertEqual([l for l in text.splitlines() if l.startswith("ARMS_")], p.tags)
        self.assertTrue(p.tags[0].startswith("ARMS_START ") and "ARMS_RETRY " in text, text)
        self.assertIn(">>> run-arms: output copied to benchmark/results/%s/logs/%s\n" % (RUN, logs[0].name), p.stdout)
        # each driver's own output too, and the walk's lines on stderr (none here) would follow them in
        self.assertEqual(text.count("REACHED"), p.stdout.count("REACHED"))
        self.assertGreater(text.count("REACHED"), 0)

    def test_a_launched_walk_names_its_segment_and_a_refusal_or_a_dry_run_writes_none(self):
        p = self.arms("--plan", self.plan("a0-control I\n"), LAUNCH_SEGMENT="arms")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([l.name for l in self.walk_logs() if re.match(self.LOG_RE % "arms", l.name)],
                         [l.name for l in self.walk_logs()])
        self.assertEqual(len(self.walk_logs()), 1)
        for args in (["--dry-run"], ["--from-arm", "9"]):
            with self.subTest(args=args):
                self.arms(*args)
                self.assertEqual(len(self.walk_logs()), 1)

    def test_a_hand_walk_exits_only_once_its_log_copy_is_whole(self):
        """run-arms waits for its own tees (leave). Under launch.sh the wrapper's wait for the segment's process group
        covers that too; a walk run by hand has only its own wait. Its output goes nowhere here, so nothing but that wait
        keeps the walk from exiting while a slow tee still copies its last lines."""
        slow = self.t.write(".fake/slowbin/tee", SLOW_TEE, 0o755)
        e = {"BENCH_RUN_ID": RUN, "RUN_ARMS_IDLE_SECS": "0", "RUN_ARMS_POOL_POLL_SECS": "1", "RUN_ARMS_POOL_WAIT_SECS": "2",
             "RUN_ARMS_HEALTH_SECS": "20", "RUN_ARMS_READY_MAX_WAIT_SECS": "30",
             "PATH": "%s:%s:%s" % (slow.parent, FIX / "bin", os.environ.get("PATH", "/usr/bin:/bin"))}
        rc = subprocess.call(["bash", str(self.t.root / "benchmark/launch/run-arms.sh"), "--plan", self.plan("a0-control L\n")],
                             cwd=str(self.t.root), env=self.t.env(**e), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             timeout=180)
        self.assertEqual(rc, 0)
        tags = [l for l in self.walk_logs()[0].read_text().splitlines() if l.startswith("ARMS_")]
        self.assertRegex(tags[-1], r"^ARMS_DONE arms=1 blasts=1 ")

    def test_a_killed_walk_leaves_every_line_it_printed(self):
        self.t.scenario({"blast:run": [{"sleep": 60}]})
        e = {"BENCH_RUN_ID": RUN, "RUN_ARMS_IDLE_SECS": "0", "RUN_ARMS_POOL_POLL_SECS": "1", "RUN_ARMS_POOL_WAIT_SECS": "2",
             "RUN_ARMS_HEALTH_SECS": "20", "RUN_ARMS_READY_MAX_WAIT_SECS": "30"}
        proc = subprocess.Popen(["bash", str(self.t.root / "benchmark/launch/run-arms.sh"), "--plan",
                                 self.plan("p1-mdbx-advice M16\n")], cwd=str(self.t.root), env=self.t.env(**e),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(lambda: os.killpg(proc.pid, signal.SIGKILL) if proc.poll() is None else None)
        self.assertTrue(wait_for(lambda: "blast:run" in self.keys(), 60), self.keys())
        log = wait_for(lambda: self.walk_logs())
        self.assertTrue(log)
        self.assertTrue(wait_for(lambda: "benchmark-blast.sh run --yes" in log[0].read_text(), 10))
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
        text = log[0].read_text()
        self.assertRegex(text, r"(?m)^ARMS_START ")
        self.assertRegex(text, r"(?m)^ARMS_POOL arm=p1-mdbx-advice step=1 verdict=ok ")
        self.assertRegex(text, r"(?m)^>>> \S+ env .* benchmark/benchmark-blast.sh run --yes --run %s$" % RUN)


# A tee that writes each line 0.1 s late (to stdout and every file argument; -a appends, -i is ignored).
SLOW_TEE = r'''#!/usr/bin/env bash
append=0 files=()
for x in "$@"; do case "$x" in -a) append=1 ;; -i) ;; *) files+=("$x") ;; esac; done
if [ "${append}" = 0 ]; then for f in ${files[@]+"${files[@]}"}; do : > "$f"; done; fi
while IFS= read -r line || [ -n "${line}" ]; do
    sleep 0.1
    printf '%s\n' "${line}"
    for f in ${files[@]+"${files[@]}"}; do printf '%s\n' "${line}" >> "$f"; done
done
'''


class ArmsLaunchLogTests(LaunchBase):
    """D3 through launch.sh: the walk's lines are in the segment log as before, the same tags in the results copy,
    the rc line still the segment log's last line, and the next launch still finds a clean harness tree."""

    def test_the_arms_segment_writes_both_logs(self):
        self.t.write("tasks/one.plan", "a0-control L\n")      # the env file's 300-s idle step would only slow it
        # Every tee copies each line a tenth of a second late, so the walk's last lines are still on their way when it
        # reaches its exit: only its wait for the copies keeps launch.sh's rc line last.
        slow = self.t.write(".fake/slowbin/tee", SLOW_TEE, 0o755)
        path = "%s:%s:%s" % (slow.parent, FIX / "bin", os.environ.get("PATH", "/usr/bin:/bin"))
        pid, log = self.started(self.launch(self.envf, "arms", "--plan", "tasks/one.plan", PATH=path))
        self.assertRegex(self.the_rc_line(log, "arms", 90), r"^== arms rc=0 ")
        seg = log.read_text().splitlines()
        self.assertTrue(seg[-1].startswith("== arms rc=0 "), seg[-3:])
        copies = sorted((self.t.root / "benchmark/results" / RUN / "logs").glob("run-arms-arms-*.log"))
        self.assertEqual(len(copies), 1)
        tags = [l for l in copies[0].read_text().splitlines() if l.startswith("ARMS_")]
        self.assertEqual(tags, [l for l in seg if l.startswith("ARMS_")])
        self.assertRegex(tags[-1], r"^ARMS_DONE arms=1 blasts=1 ")
        # results/ is ignored: the next launch's clean-tree check passes
        self.assertEqual(git(self.t.root, "status", "--porcelain", "--", "benchmark/", ":(exclude)benchmark/launch/bench5"), "")
        self.assertEqual(self.launch("--dry-run", self.envf, "reindex").returncode, 0)


def group_gone(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def after_another(test, text, patterns):
    """Each pattern matches a line of text, each one later than the one before; the matches."""
    lines, at, found = text.splitlines(), -1, []
    for pat in patterns:
        hits = [i for i, l in enumerate(lines) if i > at and re.search(pat, l)]
        test.assertTrue(hits, "no line matching %r after line %d in:\n%s" % (pat, at, "\n".join(lines[-40:])))
        at = hits[0]
        found.append(lines[at])
    return found


class ArmsSignalTests(ArmsBase):
    """H14a: a TERM (or INT) never leaves a fleet action running unobserved. A driver call that runs is left alone and
    finishes; the walk prints ARMS_STOPPING at once and stops when the call returns (reason signal-TERM, the arm left
    open, exit 143). A wait between calls ends at once. A second TERM changes nothing."""

    ENV = {"BENCH_RUN_ID": RUN, "RUN_ARMS_IDLE_SECS": "0", "RUN_ARMS_POOL_POLL_SECS": "1", "RUN_ARMS_POOL_WAIT_SECS": "2",
           "RUN_ARMS_HEALTH_SECS": "20", "RUN_ARMS_READY_MAX_WAIT_SECS": "300"}

    def start(self, plan, **env):
        e = dict(self.ENV)
        e.update(env)
        # INT as at a terminal, even when this suite runs as a background job (which starts with INT ignored)
        proc = subprocess.Popen(["bash", str(self.t.root / "benchmark/launch/run-arms.sh"), "--plan", self.plan(plan)],
                                cwd=str(self.t.root), env=self.t.env(**e), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, universal_newlines=True, start_new_session=True,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        self.addCleanup(lambda: group_gone(proc.pid) or os.killpg(proc.pid, signal.SIGKILL))
        return proc

    def walk_log(self):
        logs = sorted((self.t.root / "benchmark/results" / RUN / "logs").glob("run-arms-*.log"))
        return logs[-1].read_text() if logs else ""

    def until(self, pattern, secs=60.0):
        self.assertTrue(wait_for(lambda: re.search(pattern, self.walk_log(), re.M), secs), self.walk_log()[-1500:])

    def finish(self, proc, secs):
        t0 = time.time()
        try:
            out = proc.communicate(timeout=secs)[0]
        except subprocess.TimeoutExpired:
            self.fail("the walk did not end within %d s of the signal:\n%s" % (secs, self.walk_log()[-1500:]))
        return proc.returncode, out, time.time() - t0

    def test_a_term_during_a_blast_lets_it_end_and_a_second_term_changes_nothing(self):
        self.t.scenario({"blast:run": [{"sleep": 6, "rc": 1, "after": ["FAKE_RUN_END"]}]})
        proc = self.start("p1-mdbx-advice M16 L\n")
        run = wait_for(lambda: [c for c in self.t.calls() if c["key"] == "blast:run"], 60)
        self.assertTrue(run, self.walk_log()[-1500:])
        os.kill(proc.pid, signal.SIGTERM)
        self.until(r"^ARMS_STOPPING ", 10)
        os.kill(proc.pid, signal.SIGTERM)
        self.until(r"TERM again", 10)
        rc, out, _ = self.finish(proc, 60)
        self.assertEqual(rc, 143, out)
        idx = run[0]["env"]["BENCH_RUN_INDEX"]
        found = after_another(self, out, [
            r"^ARMS_STOPPING arm=p1-mdbx-advice step=1 signal=TERM after=blast-run-%s pid=%d \S+Z$" % (idx, run[0]["pid"]),
            r"^  stopping after blast-run-%s \(pid %d\): it runs to its end, nothing new starts " % (idx, run[0]["pid"]),
            r"^  run-arms: TERM again: it changes nothing; still stopping after blast-run-%s \(pid %d\)$" % (idx, run[0]["pid"]),
            r"^FAKE_RUN_END$",
            r"^ARMS_BLAST arm=p1-mdbx-advice step=1 kind=M16 index=%s attempt=1 fund_rc=0 run_rc=1 " % idx,
            r"^ARMS_STEP arm=p1-mdbx-advice step=1 kind=M16 rc=1 ",
            r"^ARMS_STOPPED arm=p1-mdbx-advice step=1 reason=signal-TERM \S+Z$"])
        self.assertEqual(out.count("ARMS_STOPPING "), 1, out)
        self.assertNotIn("ARMS_RETRY", out, "a failed blast is not tried again after a signal")
        self.assertEqual(out.rstrip("\n").splitlines()[-1],
                         "ARMS_RESUME BENCH_RUN_ID=%s benchmark/launch/run-arms.sh --plan tasks/test.plan --from-arm 0" % RUN)
        # nothing started after the signal: no retry, no health check, no close (the arm stays open)
        self.assertEqual(self.keys()[-2:], ["blast:fund", "blast:run"])
        self.assertEqual(self.walk_log().count(found[-1]), 1)

    def test_a_term_between_calls_stops_at_once(self):
        cases = [  # name, plan, scenario, pools, env, the line to wait for, the tags at the end, calls after it
            ("ready", "a0-control L\n", {"pa:arm-file": [{"ready_in": 120}]}, [0, 0, 0], {}, r"^ARMS_READY ",
             ["ARMS_STOPPED arm=a0-control step=0 reason=signal-TERM"], ["pa:arm-file"]),
            ("idle", "a0-control I L\n", {}, [0, 0, 0], {"RUN_ARMS_IDLE_SECS": "120"}, r"^REACHED params-apply.sh .*--mark idle-1",
             ["ARMS_STEP arm=a0-control step=1 kind=I rc=143", "ARMS_STOPPED arm=a0-control step=1 reason=signal-TERM"],
             ["pa:mark", "pa:end-mark"]),
            ("pool", "p1-mdbx-advice M16\n", {}, [5000, 0, 0], {"RUN_ARMS_POOL_WAIT_SECS": "600", "RUN_ARMS_POOL_POLL_SECS": "60"},
             r"^ARMS_POOL .* verdict=high ",
             ["ARMS_BLAST arm=p1-mdbx-advice step=1 kind=M16 index=0 attempt=1 fund_rc=0 run_rc=-",
              "ARMS_STEP arm=p1-mdbx-advice step=1 kind=M16 rc=143",
              "ARMS_STOPPED arm=p1-mdbx-advice step=1 reason=signal-TERM"], ["blast:fund"]),
        ]
        for name, plan, scen, pools, env, mark, tags, last_calls in cases:
            with self.subTest(wait=name):
                self.reset()
                self.t.scenario(scen)
                self.t.curl(pools)
                for f in (self.t.root / "benchmark/results" / RUN / "logs").glob("*.log"):
                    f.unlink()
                proc = self.start(plan, **env)
                self.until(mark)
                time.sleep(0.5)
                os.kill(proc.pid, signal.SIGTERM)
                rc, out, secs = self.finish(proc, 20)
                self.assertEqual(rc, 143, out)
                self.assertLess(secs, 15, "the wait did not end at once")
                got = [UTC_RE.sub("", l).rstrip() for l in out.splitlines() if l.startswith("ARMS_")]
                self.assertRegex(got[-len(tags) - 2], r"^ARMS_STOPPING arm=\S+ step=\d signal=TERM after=(none|mark-idle-1) pid=")
                self.assertEqual(got[-len(tags) - 1:-1], tags)
                self.assertEqual(got[-1], "ARMS_RESUME BENCH_RUN_ID=%s benchmark/launch/run-arms.sh --plan tasks/test.plan "
                                          "--from-arm 0" % RUN)
                self.assertEqual(self.keys()[-len(last_calls):], last_calls)
                self.assertTrue(wait_for(lambda: group_gone(proc.pid), 5), "a sleep of the walk outlived it")

    def test_an_apply_runs_to_its_end_and_its_own_stop_keeps_its_reason(self):
        self.t.scenario({"pa:arm-file": [{"sleep": 4, "rc": 1, "out": ["PA_FAIL bench-validator-01 readback"],
                                          "after": ["FAKE_APPLY_END"]}]})
        proc = self.start("a0-control L\n")
        apply = wait_for(lambda: [c for c in self.t.calls() if c["key"] == "pa:arm-file"], 60)
        self.assertTrue(apply, self.walk_log()[-1500:])
        os.kill(proc.pid, signal.SIGTERM)
        rc, out, _ = self.finish(proc, 60)
        self.assertEqual(rc, 143, "a stop after a signal exits 128 + its number, whatever its reason:\n" + out)
        after_another(self, out, [
            r"^ARMS_STOPPING arm=a0-control step=0 signal=TERM after=apply-a0-control pid=%d " % apply[0]["pid"],
            r"^FAKE_APPLY_END$", r"^ARMS_STEP arm=a0-control step=0 kind=apply rc=1 ",
            r"^ARMS_STOPPED arm=a0-control step=0 reason=node-failed-bench-validator-01 "])
        self.assertEqual(self.keys(), ["pa:print-state", "pa:arm-file"])

    def test_an_int_on_a_hand_run_does_the_same(self):
        self.t.scenario({"pa:arm-file": [{"ready_in": 120}]})
        proc = self.start("a0-control L\n")
        self.until(r"^ARMS_READY ")
        os.kill(proc.pid, signal.SIGINT)
        rc, out, _ = self.finish(proc, 20)
        self.assertEqual(rc, 130, out)
        self.assertRegex(out, r"(?m)^ARMS_STOPPED arm=a0-control step=0 reason=signal-INT ")


class LaunchSignalTests(LaunchBase):
    """H14a through launch.sh: the rc line is written once nothing of the segment runs. A TERM to the arms segment
    lets the running blast end, `status` says what the walk is stopping after, and the rc line follows the driver's
    last line. Any other segment's driver gets the TERM as before. A process that outlives its driver holds the rc
    line back, and one still running after LAUNCH_LEFT_WAIT_SECS is named instead of an end."""

    def test_a_term_to_the_arms_segment_lets_the_blast_end(self):
        self.t.write("tasks/one.plan", "p1-mdbx-advice M16 L\n")
        self.t.scenario({"blast:run": [{"sleep": 8, "after": ["FAKE_RUN_END"]}]})
        pid, log = self.started(self.launch(self.envf, "arms", "--plan", "tasks/one.plan"))
        run = wait_for(lambda: [c for c in self.t.calls() if c["key"] == "blast:run"], 60)
        self.assertTrue(run, log.read_text()[-1500:])
        os.kill(pid, signal.SIGTERM)
        self.assertTrue(wait_for(lambda: "ARMS_STOPPING " in log.read_text(), 10), log.read_text()[-1500:])
        idx, dpid = run[0]["env"]["BENCH_RUN_INDEX"], run[0]["pid"]
        self.assertRegex(self.launch(self.envf, "status").stdout,
                         r"(?m)^SEGMENT arms-\S+ pid=%d state=stopping after blast-run-%s \(pid %d\) last: " % (pid, idx, dpid))
        rc_line = self.the_rc_line(log, "arms", 60)
        self.assertRegex(rc_line, r"^== arms rc=143 \S+Z$")
        text = log.read_text()
        self.assertEqual(text.splitlines()[-1], rc_line)
        after_another(self, text, [
            r"^== arms signal TERM \S+Z: passed to pid \d+; the rc line follows once nothing of the segment runs$",
            r"^ARMS_STOPPING arm=p1-mdbx-advice step=1 signal=TERM after=blast-run-%s pid=%d " % (idx, dpid),
            r"^FAKE_RUN_END$",
            r"^ARMS_BLAST arm=p1-mdbx-advice step=1 kind=M16 index=%s attempt=1 fund_rc=0 run_rc=0 " % idx,
            r"^ARMS_STOPPED arm=p1-mdbx-advice step=1 reason=signal-TERM ",
            r"^ARMS_RESUME benchmark/launch/launch.sh tasks/test.env arms --plan tasks/one.plan --from-arm 0 --from-step 2$",
            r"^== arms driver pid=\d+ exit=143 after TERM \S+Z$"])
        # the walk's own log holds the stop too; nothing ran after the blast (no health check, no close)
        copy = sorted((self.t.root / "benchmark/results" / RUN / "logs").glob("run-arms-arms-*.log"))[0].read_text()
        after_another(self, copy, [r"^ARMS_STOPPING ", r"^FAKE_RUN_END$", r"^ARMS_STOPPED .* reason=signal-TERM ", r"^ARMS_RESUME "])
        self.assertEqual([c["key"] for c in self.t.calls()][-2:], ["blast:fund", "blast:run"])
        self.assertEqual([c["key"] for c in self.t.calls()].count("blast:status"), 1)
        self.assertTrue(wait_for(lambda: "state=ended last: == arms rc=143 " in self.launch(self.envf, "status").stdout, 10))

    def test_a_term_to_another_segment_reaches_its_driver_as_before(self):
        self.t.scenario({"benchmark-deploy.sh": [{"sleep": 30, "on_term": 3}]})
        pid, log = self.started(self.launch(self.envf, "step15"))
        child = wait_for(lambda: self.t.calls())[0]["pid"]
        os.kill(pid, signal.SIGTERM)
        self.assertTrue(wait_for(lambda: "FAKE_TERM_CLEANUP" in log.read_text(), 10), log.read_text())
        self.assertRegex(self.launch(self.envf, "status").stdout,
                         r"(?m)^SEGMENT step15-\S+ pid=%d state=stopping after the driver \(pid %d\) last: " % (pid, child))
        rc_line = self.the_rc_line(log, "step15")
        self.assertRegex(rc_line, r"^== step15 rc=143 ")
        lines = log.read_text().splitlines()
        self.assertEqual(lines[-1], rc_line)
        after_another(self, "\n".join(lines), [r"^== step15 signal TERM \S+Z: passed to pid %d; " % child, r"^FAKE_TERM_CLEANUP$",
                                               r"^== step15 driver pid=%d exit=143 after TERM \S+Z$" % child])

    def test_a_process_that_outlives_the_driver_holds_the_rc_line_back(self):
        self.t.scenario({"benchmark-deploy.sh": [{"spawn": 3}]})
        pid, log = self.started(self.launch(self.envf, "deploy12", LAUNCH_LEFT_WAIT_SECS="60"))
        rc_line = self.the_rc_line(log, "deploy12", 30)
        text = log.read_text()
        m = re.search(r"(?m)^== deploy12 waiting up to 60 s for what is left of the segment:\n     (\d+) sleep 3$", text)
        self.assertTrue(m, text)
        self.assertRaises(OSError, os.kill, int(m.group(1)), 0)
        self.assertEqual(text.splitlines()[-1], rc_line)
        self.assertRegex(rc_line, r"^== deploy12 rc=0 ")

    def test_a_process_left_running_is_named_instead_of_an_end(self):
        self.t.scenario({"benchmark-teardown.sh": [{"spawn": 60}]})
        pid, log = self.started(self.launch(self.envf, "reindex", LAUNCH_LEFT_WAIT_SECS="1"))
        self.assertTrue(wait_for(lambda: " LEFT_RUNNING " in log.read_text(), 30), log.read_text())
        lines = log.read_text().splitlines()
        m = re.match(r"^== reindex LEFT_RUNNING exit=0 pids=(\d+) \S+Z$", lines[-1])
        self.assertTrue(m, lines[-3:])
        self.assertEqual(lines[-2], "     %s sleep 60" % m.group(1))
        os.kill(int(m.group(1)), 0)                      # still running: the log does not claim an end
        self.assertFalse(self.rc_line(log, "reindex", 0.5))
        self.assertTrue(wait_for(lambda: "state=left running (%s) last: == reindex LEFT_RUNNING " % m.group(1)
                                 in self.launch(self.envf, "status").stdout, 10))


class EnvAndPlanTests(unittest.TestCase):
    """The shipped env files and the default plan, against the sources."""

    @staticmethod
    def env_keys(name):
        out = {}
        for line in (LAUNCH / name).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k] = v
        return out

    def test_every_knob_the_env_files_set_exists_in_config_or_its_driver(self):
        srcs = [BENCH / "config.sh"] + sorted(BENCH.glob("*.sh")) + sorted((BENCH / "tools").glob("*.sh")) \
            + [LAUNCH / "launch.sh", LAUNCH / "run-arms.sh"]
        text = "\n".join(p.read_text() for p in srcs)
        checked = set()
        for f in ENV_FILES:
            for k in self.env_keys(f):
                checked.add(k)
                with self.subTest(f=f, k=k):
                    self.assertRegex(text, r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % k, "%s sets a knob no source reads" % k)
        self.assertIn("RUN_ARMS_PLAN", checked)     # run 1b's pin of its walk (run-arms.sh reads it)

    def test_the_env_files_hold_the_plan_values(self):
        r1, r2, pr = (self.env_keys(f) for f in ("bench6-run1.env", "bench6-run2.env", "bench6-probe.env"))
        boot = "projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105"
        common = {"BENCH_RUN_ID": "<run-id>", "BENCH_DOCKER_IMAGE_EXPECT_DIGEST": "sha256:<image-digest>",
                  "BENCH_NODE_EXPECT_SHA": "<node-sha>", "BENCH_NODE_EXPECT_FORKS": "subsecond-from-genesis",
                  "BENCH_TXGEN_SHA": "<txgen-sha>", "BENCH_NODE_BOOT_IMAGE": boot, "BENCH_PERSIST_SAMPLER": "1",
                  "BENCH_TAIL_SCAN_SECS": "180", "BENCH_LIGHT_START_DELAY_SECS": "150", "BENCH_LANDINGS_SAMPLE": "100",
                  "BENCH_TEARDOWN_SKIP_ARCHIVE": "1"}
        for env in (r1, r2):
            for k, v in common.items():
                self.assertEqual(env.get(k), v, k)
            self.assertTrue(env["BENCH_DOCKER_IMAGE"].endswith("@sha256:<image-digest>"))
        self.assertEqual(r1["BENCH_CHAOS"], "0")
        self.assertNotIn("BENCH_ARM_FILE", r1)
        for k, v in {"BENCH_ARM_FILE": "benchmark/arms/final.arm", "BENCH_CHAOS": "1", "BENCH_DURATION_SECS": "2400",
                     "BENCH_LIGHT_LOAD": "1", "BENCH_LIGHT_SENDERS": '"8 600"', "BENCH_LIGHT_WINDOWS": '"16 4"'}.items():
            self.assertEqual(r2.get(k), v, k)
        self.assertEqual(pr, {"BENCH_RUN_ID": "<run-id>", "LAUNCH_PROBE_BIN": "benchmark/work/probe-bin/mdbx-writeback-probe",
                              "BENCH_NODE_BOOT_IMAGE": boot})
        for k in ("BENCH_NODE_DB_SYNC_MODE", "BENCH_NODE_LOG_FILTER", "BENCH_LOG_TRANSFER", "BENCH_OBS_DISK_MAX_PCT"):
            self.assertNotIn(k, r2)

    def test_the_lssd_env_is_run_1_with_the_local_ssd_shape(self):
        # Every key of run 1 with run 1's value (image, generator, boot image, measurements: the same placeholders),
        # plus exactly five keys: the four shape knobs and the plan pin (an `arms` launch without --plan walks run
        # 1b's plan); no BENCH_MACHINE_TYPE (validators 08 and 09 keep the default) and no zone moved.
        r1, lssd = self.env_keys("bench6-run1.env"), self.env_keys("bench6-run1-lssd.env")
        extra = dict(LSSD_SHAPE, RUN_ARMS_PLAN=LSSD_PLAN)
        self.assertEqual((len(extra), set(extra) & set(r1)), (5, set()))
        self.assertEqual(lssd, dict(r1, **extra))
        for k in ("BENCH_MACHINE_TYPE", "BENCH_NODE_ZONES", "BENCH_ARM_FILE"):
            self.assertNotIn(k, lssd)
        # Tokyo (index 3) has no fallback zone that offers c3-standard-8-lssd, and the file says so
        self.assertNotIn(" 3:", " " + LSSD_FALLBACKS)
        self.assertRegex((LAUNCH / "bench6-run1-lssd.env").read_text(), r"(?m)^#.*Tokyo \(index 3\b")

    def test_the_lssd_plan(self):
        walk = read_plan(LAUNCH / "bench6-run1-lssd.plan")
        self.assertEqual(walk, LSSD_WALK)
        self.check_arms(walk)
        # Each row pairs with run 1's: the arm's own steps there, and the arms in run 1's relative order.
        run1 = read_plan(LAUNCH / "bench6-run1.plan")
        for arm, steps in walk:
            self.assertIn(steps, [s for a, s in run1 if a == arm], arm)
        self.assertEqual([a for a, _ in walk], [a for a, _ in run1 if a in dict(walk)])

    def test_the_default_plan(self):
        walk = read_plan(LAUNCH / "bench6-run1.plan")
        self.assertEqual(walk, DEFAULT_WALK)
        self.check_arms(walk)

    def check_arms(self, walk):
        """Every arm file exists, its name line is the arm's, and every step is a type (M16 and M16s may carry @epoch)."""
        for arm, steps in walk:
            self.assertTrue((BENCH / "arms" / (arm + ".arm")).is_file(), arm)
            name = re.search(r"(?m)^name (\S+)$", (BENCH / "arms" / (arm + ".arm")).read_text()).group(1)
            self.assertEqual(name, arm)
            for s in steps:
                t, _, mod = s.partition("@")
                self.assertIn(t, TYPES, s)
                self.assertIn(mod, ("", "epoch"), s)
                if mod:
                    self.assertIn(t, ("M16", "M16s"))

    def test_the_defaults_run_arms_mirrors_from_config_and_the_blast_driver(self):
        cfg = (BENCH / "config.sh").read_text()
        for s in ("BENCH_OBS_PROM_LOCAL_PORT:-19090}", "export BENCH_TUNNEL_PORT=18545", "BENCH_PREAMBLE_SECS:-90}",
                  "BENCH_START_DELAY_SECS:-300}", "BENCH_ABORT_DISK_PCT:-85}", "BENCH_ABORT_STALL_SECS:-120}",
                  'BENCH_PROM_NETWORK_LABEL="bench"', 'RPC_URL="http://localhost:${BENCH_TUNNEL_PORT}"',
                  "BENCH_LIGHT_WARMUP_SECS:-60}", "BENCH_LIGHT_DURATION_SECS:-360}", "BENCH_LIGHT_COOLDOWN_SECS:-60}",
                  "BENCH_WARMUP_SECS:-120}", "BENCH_COOLDOWN_SECS:-180}"):
            self.assertIn(s, cfg)
        blast = (BENCH / "benchmark-blast.sh").read_text()
        self.assertIn("CREATE_ALARM_SECS=90;", blast)
        self.assertIn("CREATE_WORST_SECS=$(( 2 * CREATE_ALARM_SECS + 60 ))", blast)
        self.assertIn("reth_transaction_pool_(pending|queued)_pool_transactions", blast)
        for reason in ("disk-full", "batch-cache-cliff", "quorum-lost", "node-stalled", "obs-memory"):
            self.assertIn('record_abort "%s"' % reason, blast)
        arms = (LAUNCH / "run-arms.sh").read_text()
        self.assertIn('readonly HEALTH_ABORTS=" disk-full batch-cache-cliff quorum-lost node-stalled obs-memory "', arms)
        self.assertIn("reth_transaction_pool_queued_pool_transactions{network=\"bench\"}", arms)
        self.assertIn("BENCH_STATUS host=", (BENCH / "node-sampler.sh").read_text())



# ---- bench7 launch files (HB-5a) ----
class Bench7EnvTests(unittest.TestCase):
    """bench7-always.env and bench7-adaptive.env: run r20261113-1351's env with the bench-7 differences only."""

    RAN = Path(__file__).resolve().parents[2] / "tasks" / "bench6" / "r20261113-1351" / "bench6-run2.env"
    ADDED = {"BENCH_NODE_ALLOW_FAUCET_ON_CHAIN": "1", "BENCH_NODE_RESERVE_PORTS": "1",
             "BENCH_MACHINE_TYPE": "c3-highcpu-8", "BENCH_NODE_DISK_TYPE": "hyperdisk-balanced",
             "BENCH_NODE_DISK_SIZE": "100", "BENCH_NODE_DISK_IOPS": "20000", "BENCH_NODE_DISK_THROUGHPUT": "800"}

    def keys(self, path):
        out = {}
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k] = v
        return out

    def test_each_is_the_run_that_ran_with_the_bench7_differences(self):
        # run 2's shipped file is the model; the run filled its placeholders (the copy that ran, in tasks/, when
        # this tree has it) and bench 7 keeps the generator it ran
        model = self.keys(LAUNCH / "bench6-run2.env")
        if self.RAN.is_file():
            ran = self.keys(self.RAN)
            filled = ("BENCH_RUN_ID", "BENCH_DOCKER_IMAGE", "BENCH_DOCKER_IMAGE_EXPECT_DIGEST", "BENCH_NODE_EXPECT_SHA",
                      "BENCH_TXGEN_SHA")
            self.assertEqual(dict(ran, **{k: model[k] for k in filled}), model)
            self.assertEqual(ran["BENCH_TXGEN_SHA"], "62bbd5f")
        for form in ("always", "adaptive"):
            with self.subTest(form=form):
                want = dict(model, BENCH_TXGEN_SHA="62bbd5f", BENCH_ARM_FILE="benchmark/arms/bench7-%s.arm" % form)
                want.update(self.ADDED)
                self.assertEqual(self.keys(LAUNCH / ("bench7-%s.env" % form)), want)
                self.assertTrue((BENCH / "arms" / ("bench7-%s.arm" % form)).is_file())
        # config.sh's defaults are the shape the run had: the explicit keys change nothing
        cfg = (BENCH / "config.sh").read_text()
        for k, v in (("BENCH_MACHINE_TYPE", "c3-highcpu-8"), ("BENCH_NODE_DISK_TYPE", "hyperdisk-balanced"),
                     ("BENCH_NODE_DISK_SIZE", "100"), ("BENCH_NODE_DISK_IOPS", "20000"),
                     ("BENCH_NODE_DISK_THROUGHPUT", "800"), ("BENCH_NODE_ALLOW_FAUCET_ON_CHAIN", "1"),
                     ("BENCH_NODE_RESERVE_PORTS", "1")):
            self.assertRegex(cfg, r"\$\{%s:?-%s\}" % (k, v))

    def test_the_two_files_differ_in_the_arm_and_the_header_only(self):
        always = (LAUNCH / "bench7-always.env").read_text().splitlines()
        adaptive = (LAUNCH / "bench7-adaptive.env").read_text().splitlines()
        body = lambda lines: [l for l in lines if not l.startswith("#") and not l.startswith("BENCH_ARM_FILE=")]
        self.assertEqual(body(always), body(adaptive))
        self.assertEqual([l for l in always if l.startswith("# ") and "bench7-always" in l][:1],
                         [always[0]])
        for name in ("BENCH_NODE_EVICT_MDBX", "BENCH_NODE_READ_AHEAD_KB", "BENCH_NODE_DB_SYNC_MODE"):
            self.assertNotIn(name, "\n".join(always + adaptive))



class Bench8EnvTests(LaunchBase):
    """bench8-*.env: bench7-always.env with the bench 8 arm, the kill held past the read window, and (run R) the
    load blast's senders and window; each accepted by a dry run of deploy12 and blast15, no driver reached."""

    NAMES = {"control": "bench8-control", "floor16": "bench8-floor16", "nohold": "bench8-nohold",
             "reduced": "bench8-control"}

    def keys(self, path):
        return dict(l.split("=", 1) for l in path.read_text().splitlines() if l.strip() and not l.startswith("#"))

    def test_each_is_bench7_always_with_its_differences(self):
        base = self.keys(LAUNCH / "bench7-always.env")
        for form, arm in sorted(self.NAMES.items()):
            with self.subTest(form=form):
                want = dict(base, BENCH_ARM_FILE="benchmark/arms/%s.arm" % arm, BENCH_CHAOS_MIN_LOAD_SECS="817")
                if form == "reduced":
                    want.update(BENCH_SENDERS="300", BENCH_WINDOW="3")
                self.assertEqual(self.keys(LAUNCH / ("bench8-%s.env" % form)), want)
                self.assertTrue((BENCH / "arms" / (arm + ".arm")).is_file())
        self.assertRegex((BENCH / "config.sh").read_text(), r"\$\{BENCH_CHAOS_MIN_LOAD_SECS:-600\}")

    def test_a_dry_run_accepts_each(self):
        for form in sorted(self.NAMES):
            text = (LAUNCH / ("bench8-%s.env" % form)).read_text()
            for k, v in FILL.items():
                text = text.replace(k, v)
            self.t.write("tasks/test8.env", text)
            for seg in ("deploy12", "blast15"):
                with self.subTest(form=form, seg=seg):
                    p = self.launch("--dry-run", "tasks/test8.env", seg)
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    self.assertEqual(self.t.calls(), [])


if __name__ == "__main__":
    unittest.main()
