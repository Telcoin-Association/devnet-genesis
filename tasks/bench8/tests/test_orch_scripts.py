"""Shim tests for the bench 8 copies of the bench 7 orchestrator scripts, in tasks/bench8/ (run against
the bench 8 scripts; the fleet-health watch is bench 7's, unchanged): orch-run-chain.sh (deploy12, the idle
checks, blast15), orch-fleet-health.sh (the watch) and orch-prom-export.py (the export with its check).

Nothing here reaches the cloud: every run happens in a temp sandbox (a git repo standing in for the harness
tree) with fakes on PATH from tasks/bench8/tests/fakes/: launch.sh (records its argv and writes the segment
log the test asks for), curl (answers Prometheus queries from fixture JSON), gcloud (prints REACHED and
exits 9 unless the test arms it). The export runs against a local HTTP server on 127.0.0.1.

  python3 -m unittest tasks/bench8/tests/test_orch_scripts.py -v      (from the repo root)
"""
import glob
import gzip
import http.server
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH8 = os.path.dirname(HERE)
BENCH7 = os.path.join(os.path.dirname(BENCH8), "bench7")
REPO = os.path.dirname(os.path.dirname(BENCH8))
CHAIN = os.path.join(BENCH8, "orch-run-chain.sh")
WATCH = os.path.join(BENCH7, "orch-fleet-health.sh")
EXPORT = os.path.join(BENCH8, "orch-prom-export.py")
SAMPLER = os.path.join(BENCH8, "orch-endpoint-sampler.sh")
FAKES = os.path.join(HERE, "fakes")
REAL_LAUNCH = os.path.join(REPO, "benchmark", "launch", "launch.sh")

RUN = "r20261114-1500"
OTHER_RUN = "r20261113-1351"
VALIDATORS = ["bench-validator-%02d" % i for i in range(1, 11)]
OBSERVER = "bench-observer-11"
NODES = VALIDATORS + [OBSERVER]
# The manifest's switches (strings, as .param_arms[0].switches holds them) and what the gauge shows.
SWITCHES = {"quorum_exec_block": "true", "quorum_exec_block_starved_rounds": "4", "vote_queue_fix": "true",
            "sealed_tx_keep": "false", "parent_grace": "150ms", "recovery_threads": "0",
            "quorum_exec_block_floor_outputs": "8"}
GAUGES = {"quorum_exec_block": 1, "quorum_exec_block_starved_rounds": 4, "vote_queue_fix": 1,
          "sealed_tx_keep": 0, "parent_grace": 150, "recovery_threads": 0, "quorum_exec_block_floor_outputs": 8,
          "digest_dedupe": 0}  # a switch the manifest does not list, off: fine


def load_export_module():
    spec = importlib.util.spec_from_file_location("orch_prom_export_b7", EXPORT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def manifest(engine=None):
    m = {"run_id": RUN, "prometheus": {"network_label": "bench"},
         "zones_used": {n: "us-west2-a" for n in NODES},
         "instances": [{"name": n, "role": "observer" if n == OBSERVER else "validator"} for n in NODES],
         "param_arms": [{"name": "final", "via": "prestart", "switches": dict(SWITCHES)}]}
    if engine:
        m["storage_engine"] = engine
    return m


def vec(metric, value):
    return {"metric": metric, "value": [1763132400, str(value)]}


def green_prom():
    return {
        "up": [vec({"node": n, "network": "bench", "job": "telcoin-node"}, 1) for n in NODES],
        "tn_node_mode": [vec({"node": n, "mode": "observer" if n == OBSERVER else "cvv_active"}, 1) for n in NODES],
        "tn_node_switch": [vec({"node": n, "name": k}, v) for n in NODES for k, v in sorted(GAUGES.items())],
    }


def serial_line(node, pct=20, fatal=0, block=100, halt=0):
    return ("Nov 14 15:00:00 %s node-sampler[812]: BENCH_STATUS host=%s ts=1763132400 root_used_pct=%d "
            "fatal_db=%d %sblock=%d rss_total_kb=1\n" % (node, node, pct, fatal,
                                                         "" if halt is None else "halt=%d " % halt, block))


def gcloud_fleet(labels=None, serial=None):
    labels = labels or {}
    return {"list": [{"name": n, "zone": "https://www.googleapis.com/compute/v1/projects/p/zones/us-west2-a",
                      "labels": {"benchmark": "1", "bench-run": labels.get(n, RUN)}} for n in NODES],
            "serial": serial or {n: serial_line(n) for n in NODES}}


DEPLOY_OK = ["HOST_PROBE_SUMMARY kernel=7.0.0 image=20261105 ra_kb=128 uniform=yes differ=[] probe_failed=[]",
             "BENCH_DEPLOY_RESULT rc=0 last_step=12 first_error=- log=benchmark/results/x/logs/deploy.log"]
BLAST_OK = ["BENCH_BLAST_DONE index=1", "BENCH_DEPLOY_RESULT rc=0 last_step=15 first_error=- log=x"]


SHELLS = ("bash", "sh", "dash", "zsh", "ksh")


def driver_executing(fleet_pat, ps_args=None):
    """True while a fleet driver executes on this host: a driver's name (launch.sh's FLEET_PAT) is the program or
    the script a shell runs, read from the first two words of each process's arguments (`ps -eo args=`, or
    ps_args), as tasks/bench6/e2e-lane2.sh's foreign() reads them. A grep, an editor or an agent's shell whose
    command line only names a driver does not count; `pgrep -f` would count it (it matches the whole line)."""
    if ps_args is None:
        ps_args = subprocess.run(["ps", "-eo", "args="], stdout=subprocess.PIPE, universal_newlines=True,
                                 check=True).stdout
    for line in ps_args.splitlines():
        words = [os.path.basename(w) for w in line.split()[:2]]
        if words and re.fullmatch(fleet_pat, words[0]):
            return True
        if len(words) == 2 and words[0].lstrip("-") in SHELLS and re.fullmatch(fleet_pat, words[1]):
            return True
    return False


class Sandbox(object):
    """A harness-tree stand-in (a git repo), the fakes on PATH, and the fake state directory."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="hb4a-")
        self.root = os.path.join(self.dir, "root")
        self.fake = os.path.join(self.dir, "fake")
        self.bin = os.path.join(self.dir, "bin")
        for d in (self.root, self.fake, self.bin, os.path.join(self.root, "benchmark")):
            os.makedirs(d, exist_ok=True)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        with open(os.path.join(self.root, ".gitignore"), "w") as f:
            f.write("benchmark/results/\ntasks/\n")
        os.symlink(os.path.join(FAKES, "fake_curl.py"), os.path.join(self.bin, "curl"))
        os.symlink(os.path.join(FAKES, "fake_gcloud.py"), os.path.join(self.bin, "gcloud"))
        self.launch = os.path.join(self.fake, "launch.sh")
        with open(self.launch, "w") as f:
            f.write('#!/usr/bin/env bash\nexec python3 "%s" "$@"\n' % os.path.join(FAKES, "fake_launch.py"))
        self.env_file = os.path.join(self.dir, "bench7-test.env")
        with open(self.env_file, "w") as f:
            f.write("BENCH_RUN_ID=%s\n" % RUN)
        self.creds = os.path.join(self.dir, "credentials.db")
        open(self.creds, "w").close()
        self.started = []

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items()
             if not re.match(r"^(BENCH|RUN_ARMS|PARAMS_APPLY|LAUNCH|CHAIN|FLEET_HEALTH)_", k)}
        e["PATH"] = self.bin + os.pathsep + e.get("PATH", "")
        e.update({"CHAIN_ROOT": self.root, "CHAIN_LAUNCH": self.launch, "CHAIN_PROM_URL": "http://127.0.0.1:1",
                  "FAKE_DIR": self.fake, "CHAIN_POLL_SECS": "1", "CHAIN_IDLE_WAIT_SECS": "2",
                  "CHAIN_IDLE_RETRY_SECS": "1", "CHAIN_DEPLOY_DEADLINE_SECS": "30", "CHAIN_BLAST_DEADLINE_SECS": "30",
                  "CHAIN_WATCH_SECS": "1", "CHAIN_WATCH_END_SECS": "20", "CHAIN_WATCH_MAX_SECS": "40",
                  "CHAIN_DRIVER_PAT": r"[h]b4a-no-such-driver\.sh", "FLEET_HEALTH_PROJECT": "fake-project",
                  "CHAIN_GCLOUD_CREDS_FILE": self.creds, "CHAIN_SAMPLER_INTERVAL_SECS": "1", "SAMPLER_PROJECT": "fake-project"})
        e.update(extra)
        return e

    def write_json(self, name, obj):
        with open(os.path.join(self.fake, name), "w") as f:
            json.dump(obj, f)

    def arm_launch(self, deploy=None, blast=None, dry_rc=None):
        d = {"body": DEPLOY_OK, "end": "rc=0", "alive": False, "manifest": manifest(engine="tn-lmdb")}
        b = {"body": BLAST_OK, "end": "rc=0", "alive": False}
        d.update(deploy or {})
        b.update(blast or {})
        self.write_json("launch.json", {"run": RUN, "dry_rc": dry_rc or {}, "segments": {"deploy12": d, "blast15": b}})

    def write_manifest(self, m=None):
        d = os.path.join(self.root, "benchmark", "results", RUN)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump(m or manifest(), f)

    def lines(self, name):
        p = os.path.join(self.fake, name)
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [l.rstrip("\n") for l in f if l.strip()]

    def live_calls(self):
        return [l.split(" ", 1)[1] for l in self.lines("launch.calls") if l.startswith("LIVE ")]

    def gcloud_calls(self):
        """The fleet calls (bench 8: without the chain's read-only token check and the endpoint sampler's ssh)."""
        return [c for c in self.all_gcloud_calls() if c[:2] not in (["auth", "print-access-token"], ["compute", "ssh"])]

    def all_gcloud_calls(self):
        return [json.loads(l) for l in self.lines("gcloud.calls")]

    def start(self, argv):
        """A helper process of the test's own (a stand-in driver); stopped in cleanup."""
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        self.started.append(p)
        return p

    def cleanup(self):
        for pid in [int(x) for x in self.lines("alive.pids")]:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for p in self.started:
            p.terminate()
            p.wait(timeout=10)
        shutil.rmtree(self.dir, ignore_errors=True)


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.watch_pids = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # A watch the chain left behind (the deadline paths) is a process of this test: stop it.
        for pid in self.watch_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        self.sb.cleanup()

    def chain(self, live=True, popen=False, **env):
        argv = ["bash", CHAIN] + (["--live"] if live else []) + [self.sb.env_file]
        p = subprocess.Popen(argv, cwd=self.sb.root, env=self.sb.env(**env), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True)
        out, _ = p.communicate(timeout=180)
        for m in re.finditer(r"^CHAIN watch started pid=(\d+) ", out, re.M):
            self.watch_pids.append(int(m.group(1)))
        if popen:
            return p, out
        return p.returncode, out

    def watch(self, *args, **env):
        p = subprocess.run(["bash", WATCH, RUN] + list(args), cwd=self.sb.root, env=self.sb.env(**env),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
        return p.returncode, p.stdout

    def arm_green(self, prom=None, gcloud=True):
        self.sb.arm_launch()
        self.sb.write_json("prom.json", prom or green_prom())
        if gcloud:
            self.sb.write_json("gcloud.json", gcloud_fleet())


# ---- orch-run-chain.sh -------------------------------------------------------------------------------

class TestChainDryAndPreconditions(SandboxCase):
    def test_dry_plan_starts_nothing(self):
        self.arm_green(gcloud=False)
        rc, out = self.chain(live=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("CHAIN preconditions ok run=%s" % RUN, out)
        self.assertRegex(out, r"(?m)^CHAIN plan step=1 launch: bash \S+ \S+ deploy12 ")
        self.assertRegex(out, r"(?m)^CHAIN plan step=4 launch: bash \S+ \S+ blast15 ")
        self.assertIn("CHAIN dry done: nothing was started", out)
        self.assertEqual(self.sb.live_calls(), [], out)
        self.assertEqual(self.sb.lines("launch.calls"), ["DRY deploy12", "DRY blast15"])
        # bench 8: the plan's only gcloud call is the read-only token check
        self.assertEqual([c for c in self.sb.gcloud_calls() if c[:2] != ["auth", "print-access-token"]], [])
        self.assertEqual(self.sb.lines("curl.calls"), [])

    def test_dry_plan_against_the_real_launcher(self):
        # A copy of the real launch.sh, committed in the sandbox repo (it finds its root from its own path):
        # its --dry-run output is what the chain reads the run id from. Its pgrep sees the whole host.
        with open(REAL_LAUNCH) as f:
            fleet_pat = re.search(r"^readonly FLEET_PAT='([^']+)'", f.read(), re.M).group(1)
        if driver_executing(fleet_pat):
            self.skipTest("a fleet driver executes on this host: the real launcher's dry run refuses")
        ldir = os.path.join(self.sb.root, "benchmark", "launch")
        os.makedirs(ldir)
        shutil.copy(REAL_LAUNCH, os.path.join(ldir, "launch.sh"))
        git = ["git", "-C", self.sb.root, "-c", "user.name=hb4a", "-c", "user.email=hb4a@example.invalid"]
        subprocess.run(git + ["add", "benchmark"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "sandbox"], check=True)
        rc, out = self.chain(live=False, CHAIN_LAUNCH=os.path.join(ldir, "launch.sh"),
                             CHAIN_DRIVER_PAT=fleet_pat)
        self.assertEqual(rc, 0, out)
        self.assertIn("CHAIN precondition ok launch-dry seg=deploy12 run=%s" % RUN, out)
        self.assertIn("CHAIN precondition ok launch-dry seg=blast15 run=%s" % RUN, out)
        self.assertIn("CHAIN dry done: nothing was started", out)
        self.assertEqual(self.sb.gcloud_calls(), [])
        self.assertFalse(os.path.exists(os.path.join(self.sb.root, "tasks", "bench6", RUN)))

    def assert_precondition_stop(self, which, out, rc):
        self.assertEqual(rc, 3, out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=precondition %s" % re.escape(which))
        self.assertEqual(self.sb.live_calls(), [], out)
        self.assertNotIn("FLEET", out)

    def test_run_id_not_new_refuses(self):
        self.arm_green()
        self.sb.write_manifest()
        rc, out = self.chain()
        self.assert_precondition_stop("run-id", out, rc)

    def test_dirty_harness_tree_refuses(self):
        self.arm_green()
        with open(os.path.join(self.sb.root, "benchmark", "new-driver.sh"), "w") as f:
            f.write("true\n")
        rc, out = self.chain()
        self.assert_precondition_stop("harness-tree", out, rc)

    def test_bench5_originals_do_not_make_the_tree_dirty(self):
        self.arm_green(gcloud=False)
        os.makedirs(os.path.join(self.sb.root, "benchmark", "launch", "bench5"))
        with open(os.path.join(self.sb.root, "benchmark", "launch", "bench5", "x.env"), "w") as f:
            f.write("BENCH_RUN_ID=r20261107-1504\n")
        rc, out = self.chain(live=False)
        self.assertEqual(rc, 0, out)

    def test_running_driver_refuses(self):
        self.arm_green()
        self.sb.start(["bash", "-c", 'exec -a "$0" sleep 30', "hb4a-fake-driver.sh"])
        time.sleep(0.3)
        rc, out = self.chain(CHAIN_DRIVER_PAT=r"[h]b4a-fake-driver\.sh")
        self.assert_precondition_stop("driver-running", out, rc)

    def test_dry_launch_refusal_refuses(self):
        self.sb.arm_launch(dry_rc={"blast15": 1})
        rc, out = self.chain()
        self.assert_precondition_stop("launch-dry seg=blast15 rc=1", out, rc)


class TestChainDeploy(SandboxCase):
    def assert_deploy_stop(self, out, rc, reason):
        self.assertEqual(rc, 10, out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=deploy %s" % reason)
        self.assertEqual(self.sb.live_calls(), ["deploy12"], out)
        self.assertEqual(self.sb.lines("curl.calls"), [], "an idle check ran after a failed deploy")
        self.assertEqual(self.sb.gcloud_calls(), [])

    def test_deploy_rc_nonzero_stops_before_any_check(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"end": "rc=1"})
        rc, out = self.chain()
        self.assert_deploy_stop(out, rc, r"rc=1 ")
        self.assertIn("CHAIN FLEET MAY BE UP: nothing is torn down by this script", out)

    def test_deploy_result_line_missing_stops(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"body": DEPLOY_OK[:1]})
        rc, out = self.chain()
        self.assert_deploy_stop(out, rc, "result-missing")

    def test_deploy_left_running_stops(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"end": "LEFT_RUNNING exit=0 pids=4242"})
        rc, out = self.chain()
        self.assert_deploy_stop(out, rc, r"rc=125 ")

    def test_deploy_deadline_stops(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"end": None, "alive": True})
        rc, out = self.chain(CHAIN_DEPLOY_DEADLINE_SECS="2")
        self.assert_deploy_stop(out, rc, "deadline=2s")

    def test_deploy_wrapper_died_stops(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"end": None, "alive": False})
        rc, out = self.chain()
        self.assert_deploy_stop(out, rc, "died")

    def test_deploy_launch_refused_stops_with_no_fleet(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"refuse": True})
        rc, out = self.chain()
        self.assertEqual(rc, 10, out)
        self.assertIn("CHAIN stop reason=deploy launch-refused rc=1", out)
        self.assertNotIn("FLEET", out)


class TestChainIdleChecks(SandboxCase):
    def assert_idle_stop(self, out, rc, which, detail):
        self.assertEqual(rc, 11, out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=idle-check %s .*%s" % (which, re.escape(detail)))
        self.assertIn("CHAIN FLEET IS UP AND IDLE: decide teardown or blast by hand", out)
        self.assertEqual(self.sb.live_calls(), ["deploy12"], "blast15 was launched after a failed idle check")
        self.assertEqual(self.sb.gcloud_calls(), [], "the watch started after a failed idle check")

    def test_switch_missing_on_one_node_stops(self):
        prom = green_prom()
        prom["tn_node_switch"] = [r for r in prom["tn_node_switch"]
                                  if not (r["metric"]["node"] == "bench-validator-07"
                                          and r["metric"]["name"] == "quorum_exec_block_starved_rounds")]
        self.arm_green(prom=prom)
        rc, out = self.chain()
        self.assert_idle_stop(out, rc, "switches", "missing:quorum_exec_block_starved_rounds@bench-validator-07")

    def test_integer_switch_wrong_value_stops(self):
        prom = green_prom()
        for r in prom["tn_node_switch"]:
            if r["metric"]["node"] == "bench-validator-05" and r["metric"]["name"] == "quorum_exec_block_starved_rounds":
                r["value"][1] = "0"
        self.arm_green(prom=prom)
        rc, out = self.chain()
        self.assert_idle_stop(out, rc, "switches", "wrong:quorum_exec_block_starved_rounds@bench-validator-05=0(want:4)")

    def test_unexpected_switch_on_stops(self):
        prom = green_prom()
        for r in prom["tn_node_switch"]:
            if r["metric"]["node"] == "bench-validator-03" and r["metric"]["name"] == "digest_dedupe":
                r["value"][1] = "1"
        self.arm_green(prom=prom)
        rc, out = self.chain()
        self.assert_idle_stop(out, rc, "switches", "unexpected-on:digest_dedupe@bench-validator-03=1")

    def test_wrong_mode_stops(self):
        prom = green_prom()
        prom["tn_node_mode"][1]["metric"]["mode"] = "cvv_inactive"
        self.arm_green(prom=prom)
        rc, out = self.chain()
        self.assert_idle_stop(out, rc, "modes", "wrong=bench-validator-02:cvv_inactive")

    def test_node_not_scraped_stops(self):
        prom = green_prom()
        prom["up"] = [r for r in prom["up"] if r["metric"]["node"] != "bench-validator-09"]
        self.arm_green(prom=prom)
        rc, out = self.chain()
        self.assert_idle_stop(out, rc, "up", "up=10/11 missing=bench-validator-09")

    def test_prometheus_unreachable_stops(self):
        self.arm_green(prom={"fail": True})
        rc, out = self.chain()
        self.assertEqual(rc, 11, out)
        self.assertIn("query-failed", out)
        self.assertEqual(self.sb.live_calls(), ["deploy12"])

    def test_gauges_late_by_a_scrape_pass_on_a_retry(self):
        late = green_prom()
        first = dict(late)
        first["tn_node_switch"] = []
        first["late"] = {"after": 3, "answers": late}
        self.arm_green(prom=first)
        rc, out = self.chain(CHAIN_IDLE_WAIT_SECS="10")
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN idle-check switches fail .* round=1 ")
        self.assertRegex(out, r"(?m)^CHAIN idle-checks ok round=2 ")


class TestChainBlast(SandboxCase):
    def test_all_green_launches_blast15_once_with_the_watch(self):
        self.arm_green()
        rc, out = self.chain()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sb.live_calls(), ["deploy12", "blast15"], out)
        lines = [l for l in out.splitlines() if l.startswith("CHAIN ")]
        i = next(k for k, l in enumerate(lines) if l.startswith("CHAIN idle-checks ok "))
        self.assertIn("engine=tn-lmdb key=.storage_engine host_probe=uniform", lines[i])
        self.assertTrue(lines[i + 1].startswith("CHAIN blast15 launch "), lines[i:i + 2])
        t_ok, t_launch = (time.mktime(time.strptime(l.split()[-1], "%Y-%m-%dT%H:%M:%SZ")) for l in lines[i:i + 2])
        self.assertLessEqual(t_launch - t_ok, 1, "blast15 did not start the moment the checks passed")
        self.assertRegex(out, r"(?m)^CHAIN watch started pid=\d+ log=tasks/bench8/%s/fleet-health-blast15-" % RUN)
        self.assertRegex(out, r"(?m)^CHAIN blast15 rc=0 result=present ")
        self.assertRegex(out, r"(?m)^CHAIN watch rc=0 ")
        self.assertRegex(out, r"(?m)^CHAIN done rc=0 ")
        self.assertIn("CHAIN FLEET IS UP: read and export while it is", out)
        logs = glob.glob(os.path.join(self.sb.root, "tasks", "bench8", RUN, "fleet-health-blast15-*.log"))
        self.assertEqual(len(logs), 1)
        with open(logs[0]) as f:
            wlog = f.read()
        self.assertIn("FLEET_HEALTH run=%s nodes=11/11 disk_max=20" % RUN, wlog)
        self.assertIn("FLEET_HEALTH the walk ended (== blast15 rc=0", wlog)
        serials = [c for c in self.sb.gcloud_calls() if c[:3] == ["compute", "instances", "get-serial-port-output"]]
        self.assertEqual(sorted({c[3] for c in serials}), sorted(NODES))

    def test_blast_deadline_stops(self):
        self.arm_green()
        self.sb.arm_launch(blast={"end": None, "alive": True})
        rc, out = self.chain(CHAIN_BLAST_DEADLINE_SECS="2", CHAIN_WATCH_MAX_SECS="4")
        self.assertEqual(rc, 12, out)
        self.assertIn("CHAIN stop reason=blast deadline=2s", out)
        self.assertIn("CHAIN FLEET IS UP: blast15 may still run", out)
        self.assertEqual(self.sb.live_calls(), ["deploy12", "blast15"])

    def test_blast_rc_nonzero_ends_rc_12(self):
        self.arm_green()
        self.sb.arm_launch(blast={"end": "rc=1", "body": ["BENCH_DEPLOY_RESULT rc=1 last_step=14 first_error=x"]})
        rc, out = self.chain()
        self.assertEqual(rc, 12, out)
        self.assertRegex(out, r"(?m)^CHAIN blast15 rc=1 result=missing ")
        self.assertRegex(out, r"(?m)^CHAIN done rc=1 ")

    def test_blast_launch_refused_leaves_the_fleet_idle(self):
        self.arm_green()
        self.sb.arm_launch(blast={"refuse": True})
        rc, out = self.chain()
        self.assertEqual(rc, 12, out)
        self.assertIn("CHAIN stop reason=blast launch-refused rc=1", out)
        self.assertIn("CHAIN FLEET IS UP AND IDLE: decide teardown or blast by hand", out)
        self.assertEqual(self.sb.gcloud_calls(), [])


class TestChainCommandLines(SandboxCase):
    def test_chain_command_lines_never_match_launch_patterns(self):
        with open(REAL_LAUNCH) as f:
            text = f.read()
        pats = re.findall(r"^readonly FLEET_PAT='([^']+)'", text, re.M) + re.findall(r"\bPAT='([^']+)'", text)
        self.assertGreaterEqual(len(pats), 4, pats)
        self.assertTrue(re.search(pats[0], "bash benchmark/benchmark-deploy.sh --yes --to 12"), "the matcher reads ERE")
        self.arm_green()
        p, out = self.chain(popen=True)
        self.assertEqual(p.returncode, 0, out)
        procs = {}
        for snap in glob.glob(os.path.join(self.sb.fake, "ps", "*.txt")):
            with open(snap) as f:
                for line in f:
                    parts = line.split(None, 2)
                    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                        procs.setdefault(snap, []).append((int(parts[0]), int(parts[1]), parts[2].rstrip("\n")))
        seen = set()
        for rows in procs.values():
            parent = {pid: ppid for pid, ppid, _ in rows}
            for pid, _, args in rows:
                q, hops = pid, 0
                while q not in (0, 1, p.pid) and q in parent and hops < 64:
                    q, hops = parent[q], hops + 1
                if q == p.pid:
                    seen.add(args)
        self.assertTrue(any("orch-run-chain.sh --live" in a for a in seen), seen)
        self.assertTrue(any("orch-fleet-health.sh %s" % RUN in a for a in seen), seen)
        self.assertTrue(any("fake_launch.py" in a for a in seen), seen)
        for args in seen:
            for pat in pats:
                self.assertIsNone(re.search(pat, args), "launch.sh's pgrep -f '%s' would match: %s" % (pat, args))


# ---- orch-fleet-health.sh ----------------------------------------------------------------------------

class TestWatch(SandboxCase):
    def setUp(self):
        super(TestWatch, self).setUp()
        self.sb.write_manifest()
        self.until = os.path.join(self.sb.dir, "blast15.log")
        with open(self.until, "w") as f:
            f.write("== blast15 start 2026-11-14T15:00:00Z bench6-launch:%s:blast15 pid=1 harness=x\n" % RUN)

    def end_segment(self, line):
        with open(self.until, "a") as f:
            f.write(line + "\n")

    def serial_reads(self):
        return [c[3] for c in self.sb.gcloud_calls() if c[:3] == ["compute", "instances", "get-serial-port-output"]]

    def test_watch_ends_on_blast15_rc(self):
        self.sb.write_json("gcloud.json", gcloud_fleet())
        self.end_segment("== blast15 rc=0 2026-11-14T16:35:00Z")
        rc, out = self.watch("--watch", "1", "--max-secs", "6", "--until-file", self.until)
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^FLEET_HEALTH run=%s nodes=11/11 disk_max=20 \(bench-validator-01\) fatal_db=0 "
                              r"halt=0 block_min=100 block_max=100 \S+Z$" % RUN)
        self.assertNotIn("HALTED", out)
        self.assertIn("FLEET_HEALTH the walk ended (== blast15 rc=0 2026-11-14T16:35:00Z)", out)

    def test_watch_ends_on_left_running(self):
        self.sb.write_json("gcloud.json", gcloud_fleet())
        self.end_segment("== blast15 LEFT_RUNNING exit=0 pids=4242 2026-11-14T16:35:00Z")
        rc, out = self.watch("--watch", "1", "--max-secs", "6", "--until-file", self.until)
        self.assertEqual(rc, 0, out)
        self.assertIn("FLEET_HEALTH the walk ended (== blast15 LEFT_RUNNING", out)

    def test_watch_ends_on_max_secs(self):
        self.sb.write_json("gcloud.json", gcloud_fleet())
        t0 = time.time()
        rc, out = self.watch("--watch", "1", "--max-secs", "2", "--until-file", self.until)
        self.assertEqual(rc, 4, out)
        self.assertRegex(out, r"(?m)^FLEET_HEALTH run=%s max-secs=2 reached " % RUN)
        self.assertLess(time.time() - t0, 30)

    def test_foreign_instance_is_reported_and_not_read(self):
        self.sb.write_json("gcloud.json", gcloud_fleet(labels={"bench-validator-02": OTHER_RUN}))
        rc, out = self.watch()
        self.assertEqual(rc, 0, out)
        self.assertIn("  bench-validator-02: foreign (bench-run=%s) not read" % OTHER_RUN, out)
        self.assertIn("FLEET_HEALTH run=%s nodes=10/11 " % RUN, out)
        self.assertNotIn("bench-validator-02", self.serial_reads())
        self.assertEqual(len(self.serial_reads()), 10)

    def test_gone_fleet_ends_the_watch(self):
        fleet = gcloud_fleet(labels={n: OTHER_RUN for n in NODES})
        fleet["list"] = fleet["list"][:3]
        self.sb.write_json("gcloud.json", fleet)
        rc, out = self.watch("--watch", "1", "--max-secs", "20", "--until-file", self.until)
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^FLEET_HEALTH run=%s gone " % RUN)
        self.assertIn("  bench-validator-05: absent", out)
        self.assertEqual(self.serial_reads(), [])
        rc, out = self.watch()
        self.assertEqual(rc, 4, out)

    def test_failed_list_is_not_a_gone_fleet(self):
        self.sb.write_json("gcloud.json", {"list": None, "serial": {}})
        rc, out = self.watch("--watch", "1", "--max-secs", "2", "--until-file", self.until)
        self.assertEqual(rc, 4, out)
        self.assertIn("FLEET_HEALTH run=%s list-failed" % RUN, out)
        self.assertNotIn(" gone ", out)
        self.assertEqual(self.serial_reads(), [])

    def test_disk_alarm_ends_the_watch(self):
        serial = {n: serial_line(n) for n in NODES}
        serial["bench-validator-04"] = serial_line("bench-validator-04", pct=85)
        self.sb.write_json("gcloud.json", gcloud_fleet(serial=serial))
        rc, out = self.watch("--watch", "1", "--max-secs", "20", "--until-file", self.until)
        self.assertEqual(rc, 3, out)
        self.assertIn("FLEET_HEALTH ALARM (disk >= 80 % or fatal_db > 0 or halt > 0)\n", out)
        self.assertIn("disk_max=85 (bench-validator-04)", out)

    # ---- bench7 halt watch (HB-5a) ----
    def test_halt_alarm_names_the_halted_nodes(self):
        serial = {n: serial_line(n) for n in NODES}
        serial["bench-validator-03"] = serial_line("bench-validator-03", halt=1)
        serial["bench-validator-07"] = serial_line("bench-validator-07", halt=2)
        self.sb.write_json("gcloud.json", gcloud_fleet(serial=serial))
        rc, out = self.watch("--watch", "1", "--max-secs", "20", "--until-file", self.until)
        self.assertEqual(rc, 3, out)
        self.assertRegex(out, r"(?m)^FLEET_HEALTH run=%s nodes=11/11 disk_max=20 \(bench-validator-01\) fatal_db=0 "
                              r"halt=3 block_min=100 block_max=100 \S+Z$" % RUN)
        self.assertIn("  bench-validator-03: root_used_pct=20 fatal_db=0 halt=1 block=100\n", out)
        self.assertIn("FLEET_HEALTH HALTED bench-validator-03=1 bench-validator-07=2 (", out)
        self.assertIn("FLEET_HEALTH ALARM (disk >= 80 % or fatal_db > 0 or halt > 0) halted: bench-validator-03=1 "
                      "bench-validator-07=2\n", out)
        rc, out = self.watch()
        self.assertEqual(rc, 3, out)

    def test_a_status_line_without_halt_counts_nothing(self):
        serial = {n: serial_line(n, halt=None) for n in NODES}
        self.sb.write_json("gcloud.json", gcloud_fleet(serial=serial))
        rc, out = self.watch()
        self.assertEqual(rc, 0, out)
        self.assertIn("  bench-validator-02: root_used_pct=20 fatal_db=0 halt=? block=100\n", out)
        self.assertIn(" fatal_db=0 halt=0 block_min=100 ", out)

    # ---- bench7 halt baseline (HB-5b) ----
    def test_a_restarted_watch_alarms_only_above_the_halt_baseline(self):
        serial = {n: serial_line(n) for n in NODES}
        serial["bench-validator-03"] = serial_line("bench-validator-03", halt=1)
        serial["bench-validator-07"] = serial_line("bench-validator-07", halt=2)
        self.sb.write_json("gcloud.json", gcloud_fleet(serial=serial))
        halted = "FLEET_HEALTH HALTED bench-validator-03=1 bench-validator-07=2 ("
        # at the baseline: the real sum and the halted nodes are printed, no alarm
        rc, out = self.watch("--halt-baseline", "3")
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^FLEET_HEALTH run=%s nodes=11/11 \S+ \(bench-validator-01\) fatal_db=0 halt=3 " % RUN)
        self.assertIn(halted, out)
        self.end_segment("== blast15 rc=0 2026-11-14T16:35:00Z")
        rc, out = self.watch("--watch", "1", "--max-secs", "20", "--until-file", self.until, "--halt-baseline", "3")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("ALARM", out)
        self.assertIn(halted, out)
        self.assertIn("FLEET_HEALTH the walk ended (", out)
        # one new halt line above the baseline alarms again
        rc, out = self.watch("--watch", "1", "--max-secs", "20", "--until-file", self.until, "--halt-baseline", "2")
        self.assertEqual(rc, 3, out)
        self.assertIn("FLEET_HEALTH ALARM (disk >= 80 % or fatal_db > 0 or halt > 2) halted: bench-validator-03=1 "
                      "bench-validator-07=2\n", out)
        # the baseline never hides the other alarms
        serial["bench-validator-04"] = serial_line("bench-validator-04", fatal=1)
        self.sb.write_json("gcloud.json", gcloud_fleet(serial=serial))
        rc, out = self.watch("--halt-baseline", "9")
        self.assertEqual(rc, 3, out)
        rc, out = self.watch("--halt-baseline", "x")
        self.assertEqual(rc, 64, out)


# ---- orch-prom-export.py -----------------------------------------------------------------------------

class FakeProm(object):
    """A Prometheus HTTP API on 127.0.0.1: presence {metric: [nodes]} answers the check and the export."""

    def __init__(self, presence):
        self.presence = presence
        self.holes = {}  # bench 8: {node: [(from, to)]} seconds after the start without a sample (the coverage check)
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                query = q.get("query", [""])[0]
                outer.requests.append((u.path, query))
                if u.path == "/api/v1/label/__name__/values":
                    body = {"status": "success", "data": sorted(list(outer.presence) + ["go_goroutines"])}
                elif u.path == "/api/v1/query":
                    m = re.search(r"last_over_time\(([A-Za-z0-9_:]+)\{", query)
                    nodes = outer.presence.get(m.group(1), []) if m else []
                    body = {"status": "success", "data": {"resultType": "vector",
                                                          "result": [vec({"node": n}, 1) for n in nodes]}}
                elif u.path == "/api/v1/query_range" and "count_over_time(" in query:
                    m = re.search(r"count_over_time\(([A-Za-z0-9_:]+)\{", query)
                    s0, s1 = float(q["start"][0]), float(q["end"][0])
                    st = float(q["step"][0].rstrip("s"))
                    result = []
                    for n in (outer.presence.get(m.group(1), []) if m else []):
                        steps = int((s1 - s0) // st) + 1
                        vals = [[s0 + k * st, "1"] for k in range(steps)
                                if not any(a <= k * st < b for a, b in outer.holes.get(n, []))]
                        if vals:
                            result.append({"metric": {"node": n}, "values": vals})
                    body = {"status": "success", "data": {"resultType": "matrix", "result": result}}
                elif u.path == "/api/v1/query_range":
                    nodes = outer.presence.get(query, [])
                    body = {"status": "success", "data": {"resultType": "matrix", "result": [
                        {"metric": {"__name__": query, "node": n}, "values": [[1, "1"], [16, "2"]]} for n in nodes]}}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def ranges(self):
        return [r for r in self.requests if r[0] == "/api/v1/query_range" and "count_over_time(" not in r[1]]


class TestExport(SandboxCase):
    def setUp(self):
        super(TestExport, self).setUp()
        mod = load_export_module()
        self.must, self.validators_only, self.lazy = mod.MUST_HAVE, mod.VALIDATORS_ONLY, mod.LAZY
        self.sb.write_manifest()
        self.manifest = os.path.join(self.sb.root, "benchmark", "results", RUN, "manifest.json")
        self.out = os.path.join(self.sb.dir, "prom-export")

    def presence(self):
        p = {m: list(VALIDATORS if m in self.validators_only else NODES) for m in self.must}
        del p["reth_db_table_pages"]  # gone with MDBX: reported, not fatal
        # registered at the event: on the nodes that counted one; the leftover drain's on none (an honest run)
        for m in self.lazy:
            p[m] = [] if m.startswith("tn_node_leftover_") else list(VALIDATORS[:3])
        return p

    def export(self, presence, *extra):
        prom = FakeProm(presence)
        self.addCleanup(prom.stop)
        argv = ["python3", EXPORT, self.out, "2026-11-14T15:15:00Z", "2026-11-14T17:00:00Z"] + list(extra)
        env = self.sb.env(PROM_URL=prom.url, PROM_EXPORT_PAUSE_SECS="0")
        p = subprocess.run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=120)
        return p.returncode, p.stdout, prom

    def test_must_have_list_names_forty_one_series(self):
        self.assertEqual(len(self.must), 41)
        self.assertEqual(len(set(self.must)), 41)
        for m in ("tn_primary_vote_stage_seconds_count", "tn_node_switch", "tn_reth_persist_commit_seconds_count"):
            self.assertIn(m, self.must)
        self.assertLessEqual(self.validators_only | self.lazy, set(self.must))
        self.assertEqual(self.validators_only & self.lazy, frozenset())

    def test_complete_export_passes(self):
        rc, out, prom = self.export(self.presence(), "--manifest", self.manifest)
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(re.findall(r"(?m)^EXPORT_CHECK ", out)), 41)
        self.assertIn("EXPORT_CHECK metric=tn_primary_vote_stage_seconds_count nodes=11/11 missing=- status=ok", out)
        self.assertIn("EXPORT_CHECK metric=tn_node_switch nodes=11/11 missing=- status=ok", out)
        self.assertIn("EXPORT_CHECK metric=reth_db_table_pages nodes=0/11 missing=- status=absent", out)
        self.assertRegex(out, r"(?m)^EXPORT_DONE metrics=40 series=\d+ nodes=11$")
        self.assertTrue(os.path.exists(os.path.join(self.out, "INDEX.tsv")))
        with gzip.open(os.path.join(self.out, "tn_node_switch.json.gz"), "rb") as f:
            self.assertEqual(len(json.loads(f.read())["data"]["result"]), 11)

    def test_incomplete_must_have_series_refuses(self):
        p = self.presence()
        p["tn_primary_vote_stage_seconds_count"].remove("bench-validator-07")
        for extra in (["--manifest", self.manifest], []):
            rc, out, prom = self.export(p, *extra)
            self.assertEqual(rc, 3, out)
            self.assertIn("EXPORT_CHECK metric=tn_primary_vote_stage_seconds_count nodes=10/11 "
                          "missing=bench-validator-07 status=incomplete", out)
            self.assertIn("EXPORT_REFUSED incomplete=1", out)
            self.assertEqual(prom.ranges(), [])
            self.assertFalse(os.path.exists(os.path.join(self.out, "INDEX.tsv")))
            self.assertNotIn("EXPORT_DONE", out)

    def test_series_missing_on_the_observer_refuses(self):
        p = self.presence()
        p["tn_node_switch"].remove(OBSERVER)
        rc, out, prom = self.export(p, "--manifest", self.manifest, "--check-only")
        self.assertEqual(rc, 3, out)
        self.assertIn("EXPORT_CHECK metric=tn_node_switch nodes=10/11 missing=%s status=incomplete" % OBSERVER, out)

    def test_node_silent_on_every_series_is_missing_with_the_manifest(self):
        p = {m: [n for n in nodes if n != "bench-validator-10"] for m, nodes in self.presence().items()}
        rc, out, prom = self.export(p, "--manifest", self.manifest, "--check-only")
        self.assertEqual(rc, 3, out)
        self.assertIn("EXPORT_CHECK metric=tn_engine_queued_outputs nodes=10/11 missing=bench-validator-10 "
                      "status=incomplete", out)
        # every series but the lazy ones and the absent reth_db_table_pages
        self.assertIn("EXPORT_REFUSED incomplete=%d" % (len(self.must) - len(self.lazy) - 1), out)

    def test_allow_missing_exports_anyway(self):
        p = self.presence()
        p["tn_primary_vote_stage_seconds_count"].remove("bench-validator-07")
        rc, out, prom = self.export(p, "--manifest", self.manifest, "--allow-missing")
        self.assertEqual(rc, 0, out)
        self.assertIn("status=incomplete", out)
        self.assertRegex(out, r"(?m)^EXPORT_DONE metrics=40 series=\d+ nodes=11$")
        self.assertGreater(len(prom.ranges()), 0)

    # ---- bench7 must-have scopes (HB-5a) ----
    def test_proposer_series_are_checked_on_the_validators_only(self):
        rc, out, prom = self.export(self.presence(), "--manifest", self.manifest, "--check-only")
        self.assertEqual(rc, 0, out)
        self.assertIn("EXPORT_CHECK metric=tn_primary_digests_held nodes=10/10 missing=- status=ok", out)
        p = self.presence()
        p["tn_primary_headers_held_total"].remove("bench-validator-04")
        for extra in (["--manifest", self.manifest], []):
            rc, out, prom = self.export(p, "--check-only", *extra)
            self.assertEqual(rc, 3, out)
            self.assertIn("EXPORT_CHECK metric=tn_primary_headers_held_total nodes=9/10 missing=bench-validator-04 "
                          "status=incomplete", out)
            self.assertIn("EXPORT_REFUSED incomplete=1", out)

    def test_a_lazy_series_on_some_nodes_is_listed_and_never_refuses(self):
        rc, out, prom = self.export(self.presence(), "--manifest", self.manifest, "--check-only")
        self.assertEqual(rc, 0, out)
        self.assertIn("EXPORT_CHECK metric=tn_node_orphan_txs_total nodes=3/11 missing=%s,bench-validator-04,"
                      "bench-validator-05,bench-validator-06,bench-validator-07,bench-validator-08,bench-validator-09,"
                      "bench-validator-10 status=lazy" % OBSERVER, out)
        self.assertIn("EXPORT_CHECK metric=tn_node_leftover_output_gaps_total nodes=0/11 missing=- status=absent", out)
        # a series registered when its handles are built is not lazy: a node without it refuses the export
        p = self.presence()
        p["tn_worker_batch_reports_over_quota_total"].remove(OBSERVER)
        p["tn_state_sync_epoch_records_certified_through"].remove("bench-validator-02")
        rc, out, prom = self.export(p, "--manifest", self.manifest, "--check-only")
        self.assertEqual(rc, 3, out)
        self.assertIn("EXPORT_CHECK metric=tn_worker_batch_reports_over_quota_total nodes=10/11 missing=%s "
                      "status=incomplete" % OBSERVER, out)
        self.assertIn("EXPORT_REFUSED incomplete=2", out)

    def test_the_pattern_takes_every_prefix_of_the_build(self):
        match = load_export_module().MATCH
        for name in ("tn_primary_vote_outcomes_total", "tn_node_switch", "tn_state_sync_epoch_record_conflicts_total",
                     "tn_epoch_epoch_record_closing_block_check_total", "tn_engine_recover_seconds_bucket",
                     "tn_worker_batch_reports_over_quota_total", "tn_reth_block_execute_seconds_count",
                     "reth_db_table_pages", "reth_db_latched", "reth_db_oldest_reader_age_seconds",
                     "reth_db_timed_out_not_aborted_transactions", "reth_db_page_size", "reth_db_freelist"):
            self.assertRegex(name, match)
        for name in ("go_goroutines", "reth_db_transaction_open_total", "process_cpu_seconds_total"):
            self.assertNotRegex(name, match)

    def test_check_only_exports_nothing(self):
        rc, out, prom = self.export(self.presence(), "--manifest", self.manifest, "--check-only")
        self.assertEqual(rc, 0, out)
        self.assertEqual(prom.ranges(), [])
        self.assertNotIn("EXPORT_DONE", out)


class TestDriverExecuting(unittest.TestCase):
    """The plan tests skip only while a driver executes, not while a command line merely names one."""

    def test_only_an_executing_driver_counts(self):
        with open(REAL_LAUNCH) as f:
            pat = re.search(r"^readonly FLEET_PAT='([^']+)'", f.read(), re.M).group(1)
        for args in ("/bin/bash /srv/dg/benchmark/benchmark-blast.sh --run-id r1",
                     "bash benchmark/run-arms.sh plan.txt", "/srv/dg/benchmark/params-apply.sh --dry-run",
                     "-bash benchmark/benchmark-deploy.sh"):
            with self.subTest(args=args):
                self.assertTrue(driver_executing(pat, "sshd: x\n" + args + "\n"))
        for args in ("bash -c grep -n x benchmark/benchmark-blast.sh", "grep -n x benchmark/benchmark-blast.sh",
                     "vim benchmark/run-arms.sh", "shellcheck -S warning benchmark/params-apply.sh",
                     "python3 -m unittest test_launch", "bash benchmark/benchmark-blast.sh.orig",
                     "/bin/bash -c sed -n 1,9p benchmark/benchmark-teardown.sh"):
            with self.subTest(args=args):
                self.assertFalse(driver_executing(pat, args + "\n"))


if __name__ == "__main__":
    unittest.main()
