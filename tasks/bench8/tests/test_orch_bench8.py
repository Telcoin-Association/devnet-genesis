"""Shim tests for what bench 8 adds to the orchestrator scripts in tasks/bench8/: the chain's credential
checks, the idle check's endpoint fallback and floor count, the endpoint sampler as a segment, and the
export's per-series coverage check. Offline: the fakes in tasks/bench8/tests/fakes/ stand in for launch.sh,
curl (Prometheus) and gcloud (the token call, compute ssh); the sandbox and helpers are test_orch_scripts'.

  python3 -m unittest tasks/bench8/tests/test_orch_bench8.py -v      (from the repo root)
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_orch_scripts as base  # noqa: E402

RUN = base.RUN
NODES = base.NODES
OBSERVER = base.OBSERVER
REAUTH = ("ERROR: (gcloud.compute.ssh) There was a problem refreshing your current auth tokens: "
          "Reauthentication failed. cannot prompt during non-interactive execution.")


def endpoint_text(node, mode=None, gauges=None):
    """A node's own metrics text as its exporter serves it (no node label: the exporter does not add one)."""
    mode = mode or ("observer" if node == OBSERVER else "cvv_active")
    lines = ["# HELP tn_node_mode the node's mode", 'tn_node_mode{mode="%s"} 1' % mode]
    for k, v in sorted((gauges or base.GAUGES).items()):
        lines.append('tn_node_switch{name="%s"} %s' % (k, v))
    return "\n".join(lines) + "\n"


def prom_without(node, keys=("up",)):
    p = base.green_prom()
    for k in keys:
        p[k] = [r for r in p[k] if r["metric"]["node"] != node]
    return p


# ---- 1. credentials ----------------------------------------------------------------------------------

class TestChainCredentials(base.SandboxCase):
    def test_plan_prints_the_login_age(self):
        self.arm_green(gcloud=False)
        rc, out = self.chain(live=False)
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN credentials ok at=preconditions token=ok "
                              r"login_age=\d+ source=credentials\.db-mtime max=3600s ")
        self.assertRegex(out, r"(?m)^CHAIN plan credentials: gcloud auth print-access-token again before blast15 ")
        self.assertNotIn("fake-token", out)

    def test_failed_token_refuses_before_any_launch(self):
        self.arm_green()
        self.sb.write_json("auth.json", {"rc": 1, "stderr": REAUTH})
        for live in (False, True):
            rc, out = self.chain(live=live)
            self.assertEqual(rc, 4, out)
            self.assertRegex(out, r"(?m)^CHAIN stop reason=credentials token-failed at=preconditions rc=1 "
                                  r"login_age=\d+ source=credentials\.db-mtime \(ERROR: .*Reauthentication failed")
            self.assertIn("run `gcloud auth login`, then start the chain again", out)
            self.assertEqual(self.sb.live_calls(), [], out)

    def test_login_older_than_the_threshold_refuses(self):
        self.arm_green()
        old = time.time() - 4000
        os.utime(self.sb.creds, (old, old))
        rc, out = self.chain()
        self.assertEqual(rc, 4, out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=credentials login-too-old at=preconditions "
                              r"login_age=40\d\ds max=3600s ")
        self.assertEqual(self.sb.live_calls(), [], out)
        rc, out = self.chain(live=False, CHAIN_LOGIN_MAX_AGE_SECS="5000")
        self.assertEqual(rc, 0, out)

    def test_unknown_age_refuses_unless_allowed(self):
        self.arm_green()
        os.unlink(self.sb.creds)
        rc, out = self.chain(live=False)
        self.assertEqual(rc, 4, out)
        self.assertIn("CHAIN stop reason=credentials login-age-unknown at=preconditions "
                      "(unknown source=no-credential-store)", out)
        rc, out = self.chain(live=False, CHAIN_LOGIN_AGE_UNKNOWN_OK="1")
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN credentials ok at=preconditions token=ok "
                              r"login_age=unknown source=no-credential-store ")

    def test_login_too_old_for_blast15_leaves_the_fleet_idle(self):
        self.arm_green()
        old = time.time() - 100
        os.utime(self.sb.creds, (old, old))
        rc, out = self.chain(CHAIN_LOGIN_MAX_AGE_BLAST_SECS="50")
        self.assertEqual(rc, 4, out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=credentials login-too-old at=blast15 login_age=1\d\ds max=50s ")
        self.assertIn("then launch blast15 by hand: bash ", out)
        self.assertIn("CHAIN FLEET IS UP AND IDLE", out)
        self.assertEqual(self.sb.live_calls(), ["deploy12"], out)

    def test_reauth_failure_in_the_blast_log_is_credentials_not_a_failed_blast(self):
        self.arm_green()
        self.sb.arm_launch(blast={"end": "rc=1", "body": [REAUTH, "BENCH_DEPLOY_RESULT rc=1 last_step=14 first_error=x"]})
        rc, out = self.chain()
        self.assertEqual(rc, 4, out)
        self.assertEqual(len(re.findall(r"(?m)^CHAIN credentials refresh-failed seg=blast15 ", out)), 1, out)
        self.assertIn("the fleet is UP: run `gcloud auth login`, then read `launch.sh <env> status`", out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=credentials seg=blast15 blast15 rc=1 result=missing ")

    def test_reauth_failure_in_the_deploy_log_stops_with_4(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"end": "rc=1", "body": [REAUTH]})
        rc, out = self.chain()
        self.assertEqual(rc, 4, out)
        self.assertIn("CHAIN credentials refresh-failed seg=deploy12 ", out)
        self.assertIn("the fleet MAY BE UP (deploy12 has not ended)", out)
        self.assertRegex(out, r"(?m)^CHAIN stop reason=credentials seg=deploy12 deploy rc=1 ")
        self.assertEqual(self.sb.live_calls(), ["deploy12"], out)

    def test_a_clean_failed_blast_is_still_12(self):
        self.arm_green()
        self.sb.arm_launch(blast={"end": "rc=1", "body": ["BENCH_DEPLOY_RESULT rc=1 last_step=14 first_error=x"]})
        rc, out = self.chain()
        self.assertEqual(rc, 12, out)
        self.assertNotIn("CHAIN credentials refresh-failed", out)


# ---- 2. the idle check's up rule and the floor count -------------------------------------------------

class TestChainIdleFallback(base.SandboxCase):
    NODE = "bench-validator-03"

    def arm(self, prom, ssh=None, m=None):
        self.arm_green(prom=prom)
        if m is not None:
            self.sb.arm_launch(deploy={"manifest": m})
        if ssh is not None:
            self.sb.write_json("ssh.json", ssh)

    def assert_passed_by_fallback(self, rc, out):
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN idle-check endpoint-fallback need=%s answered=%s failed=- " % (self.NODE, self.NODE))
        self.assertRegex(out, r"(?m)^CHAIN idle-check up ok up=11/11 missing=- fallback=%s " % self.NODE)
        self.assertRegex(out, r"(?m)^CHAIN idle-checks ok round=1 .* up_fallback=%s "
                              r"quorum_exec_block_floor_outputs=8 " % self.NODE)
        self.assertEqual(self.sb.live_calls(), ["deploy12", "blast15"], out)

    def test_a_node_without_up_passes_by_its_endpoint(self):
        self.arm(prom_without(self.NODE), ssh={self.NODE: endpoint_text(self.NODE)})
        self.assert_passed_by_fallback(*self.chain())

    def test_a_node_without_any_series_passes_by_its_endpoint(self):
        self.arm(prom_without(self.NODE, ("up", "tn_node_mode", "tn_node_switch")),
                 ssh={self.NODE: endpoint_text(self.NODE)})
        self.assert_passed_by_fallback(*self.chain())

    def test_all_green_takes_no_fallback(self):
        self.arm(base.green_prom())
        rc, out = self.chain()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("endpoint-fallback", out)
        self.assertRegex(out, r"(?m)^CHAIN idle-check up ok up=11/11 missing=- round=1 ")
        self.assertRegex(out, r"(?m)^CHAIN idle-checks ok .* up_fallback=- quorum_exec_block_floor_outputs=8 ")

    def test_an_endpoint_that_does_not_answer_stops(self):
        self.arm(prom_without(self.NODE), ssh={self.NODE: None})
        rc, out = self.chain()
        self.assertEqual(rc, 11, out)
        self.assertRegex(out, r"(?m)^CHAIN idle-check endpoint-fallback need=%s answered=- failed=%s " % (self.NODE, self.NODE))
        self.assertRegex(out, r"(?m)^CHAIN stop reason=idle-check up up=10/11 missing=%s after " % self.NODE)
        self.assertEqual(self.sb.live_calls(), ["deploy12"], out)

    def test_an_endpoint_without_the_mode_stops(self):
        text = "\n".join(l for l in endpoint_text(self.NODE).splitlines() if "tn_node_mode" not in l) + "\n"
        self.arm(prom_without(self.NODE, ("up", "tn_node_mode", "tn_node_switch")), ssh={self.NODE: text})
        rc, out = self.chain()
        self.assertEqual(rc, 11, out)
        self.assertIn("wrong=%s:none" % self.NODE, out)
        self.assertEqual(self.sb.live_calls(), ["deploy12"], out)

    def test_floor_differing_on_one_node_stops(self):
        p = base.green_prom()
        for r in p["tn_node_switch"]:
            if r["metric"]["node"] == "bench-validator-04" and r["metric"]["name"] == "quorum_exec_block_floor_outputs":
                r["value"][1] = "16"
        self.arm(p)
        rc, out = self.chain()
        self.assertEqual(rc, 11, out)
        self.assertIn("wrong:quorum_exec_block_floor_outputs@bench-validator-04=16(want:8)", out)
        self.assertEqual(self.sb.live_calls(), ["deploy12"], out)

    def test_floor_differing_on_a_fallback_endpoint_stops(self):
        g = dict(base.GAUGES, quorum_exec_block_floor_outputs=16)
        self.arm(prom_without(self.NODE), ssh={self.NODE: endpoint_text(self.NODE, gauges=g)})
        rc, out = self.chain()
        self.assertEqual(rc, 11, out)
        self.assertIn("wrong:quorum_exec_block_floor_outputs@%s=16(want:8)" % self.NODE, out)

    def test_floor16_everywhere_passes(self):
        m = base.manifest(engine="tn-lmdb")
        m["param_arms"][0]["switches"]["quorum_exec_block_floor_outputs"] = "16"
        p = base.green_prom()
        for r in p["tn_node_switch"]:
            if r["metric"]["name"] == "quorum_exec_block_floor_outputs":
                r["value"][1] = "16"
        self.arm(p, m=m)
        rc, out = self.chain()
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN idle-checks ok .* quorum_exec_block_floor_outputs=16 ")

    def test_a_manifest_without_the_floor_stops(self):
        m = base.manifest(engine="tn-lmdb")
        del m["param_arms"][0]["switches"]["quorum_exec_block_floor_outputs"]
        self.arm(base.green_prom(), m=m)
        rc, out = self.chain()
        self.assertEqual(rc, 11, out)
        self.assertIn("CHAIN stop reason=idle-check manifest .param_arms[0].switches.quorum_exec_block_floor_outputs="
                      "'absent' is not a count", out)


# ---- 3. the endpoint sampler as a segment -------------------------------------------------------------

def wait_gone(pid, secs=15):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    return False


class TestChainSampler(base.SandboxCase):
    def test_the_sampler_runs_from_deploy12_to_the_chain_end(self):
        self.arm_green()
        self.sb.write_json("ssh.json", {n: endpoint_text(n) for n in NODES})
        self.sb.arm_launch(blast={"end": "rc=0", "alive": True})
        rc, out = self.chain(CHAIN_WATCH_END_SECS="3")
        self.assertEqual(rc, 0, out)
        lines = [l for l in out.splitlines() if l.startswith("CHAIN ")]
        i = next(k for k, l in enumerate(lines) if l.startswith("CHAIN deploy12 rc=0 result=ok "))
        m = re.match(r"CHAIN sampler started pid=(\d+) interval=1s out=tasks/bench8/%s/endpoint-samples "
                     r"log=(tasks/bench8/%s/endpoint-sampler-\S+\.log) stop_file=tasks/bench8/%s/endpoint-sampler\.stop "
                     % (RUN, RUN, RUN), lines[i + 1])
        self.assertIsNotNone(m, lines[i:i + 2])
        self.assertTrue(wait_gone(int(m.group(1))), "the sampler outlived the chain")
        with open(os.path.join(self.sb.root, m.group(2))) as f:
            log = f.read()
        self.assertRegex(log, r"(?m)^ENDPOINT_SAMPLE run=%s round=1 ok=11/11 failed=- " % RUN)
        self.assertRegex(log, r"(?m)^ENDPOINT_SAMPLE (stop-file endpoint-sampler\.stop seen|parent pid=\d+ gone); ended ")
        files = glob.glob(os.path.join(self.sb.root, "tasks", "bench8", RUN, "endpoint-samples", "*-metrics-*.txt.gz"))
        self.assertEqual(sorted({os.path.basename(f).split("-metrics-")[0] for f in files}), sorted(NODES))
        self.assertNotIn("CHAIN sampler ended", out)

    def test_a_sampler_that_dies_is_said_once_and_the_chain_goes_on(self):
        self.arm_green()
        dead = os.path.join(self.sb.dir, "dead-sampler.sh")
        with open(dead, "w") as f:
            f.write("#!/usr/bin/env bash\necho dying\nexit 3\n")
        self.sb.arm_launch(blast={"end": "rc=0", "alive": True})
        rc, out = self.chain(CHAIN_SAMPLER=dead, CHAIN_WATCH_END_SECS="3")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(re.findall(r"(?m)^CHAIN sampler ended rc=3 log=\S+: the chain goes on without it ", out)), 1, out)
        self.assertEqual(self.sb.live_calls(), ["deploy12", "blast15"], out)

    def test_no_sampler_when_deploy12_fails(self):
        self.arm_green()
        self.sb.arm_launch(deploy={"end": "rc=1"})
        rc, out = self.chain()
        self.assertEqual(rc, 10, out)
        self.assertNotIn("CHAIN sampler started", out)

    def test_the_plan_names_the_sampler_and_starts_none(self):
        self.arm_green(gcloud=False)
        rc, out = self.chain(live=False)
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN plan step=2b sampler: right after deploy12 rc=0: bash \S+orch-endpoint-sampler\.sh %s "
                              r"tasks/bench8/%s/endpoint-samples --interval 1 " % (RUN, RUN))
        self.assertEqual([c for c in self.sb.all_gcloud_calls() if c[:2] == ["compute", "ssh"]], [])


class TestSampler(base.SandboxCase):
    def sampler(self, *args, **env):
        p = subprocess.run(["bash", base.SAMPLER, RUN, os.path.join(self.sb.dir, "out")] + list(args), cwd=self.sb.root,
                           env=self.sb.env(SAMPLER_ROOT=self.sb.root, **env), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
        return p.returncode, p.stdout

    def setUp(self):
        super(TestSampler, self).setUp()
        self.sb.write_manifest()
        self.sb.write_json("ssh.json", {n: endpoint_text(n) for n in NODES})

    def test_a_stop_file_ends_it_without_another_round(self):
        stop = os.path.join(self.sb.dir, "s.stop")
        open(stop, "w").close()
        t0 = time.time()
        rc, out = self.sampler("--interval", "30", "--stop-file", stop)
        self.assertEqual(rc, 0, out)
        self.assertLess(time.time() - t0, 20, out)
        self.assertEqual(len(re.findall(r"(?m)^ENDPOINT_SAMPLE run=", out)), 1, out)
        self.assertRegex(out, r"(?m)^ENDPOINT_SAMPLE stop-file s\.stop seen; ended ")

    def test_a_gone_parent_ends_it(self):
        p = subprocess.Popen(["true"])
        p.wait()
        rc, out = self.sampler("--interval", "30", "--parent-pid", str(p.pid))
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^ENDPOINT_SAMPLE parent pid=%d gone; ended " % p.pid)

    def test_the_project_comes_from_config_sh(self):
        with open(os.path.join(self.sb.root, "config.sh"), "w") as f:
            f.write('export PROJECT_ID="fake-proj-from-config"\n')
        rc, out = self.sampler("--once", "--nodes", "bench-validator-01", SAMPLER_PROJECT="")
        self.assertEqual(rc, 0, out)
        ssh = [c for c in self.sb.all_gcloud_calls() if c[:2] == ["compute", "ssh"]]
        self.assertEqual(len(ssh), 1, ssh)
        self.assertIn("--project=fake-proj-from-config", ssh[0])
        os.unlink(os.path.join(self.sb.root, "config.sh"))
        rc, out = self.sampler("--once", SAMPLER_PROJECT="")
        self.assertEqual(rc, 2, out)
        self.assertIn("no project", out)


# ---- 4. the export's coverage check -------------------------------------------------------------------

class TestExportCoverage(unittest.TestCase):
    T0 = 1794750000
    T1 = T0 + 3600
    KILLED = "bench-validator-05"

    def setUp(self):
        mod = base.load_export_module()
        self.must = list(mod.MUST_HAVE)
        self.prom = base.FakeProm({m: list(NODES) for m in self.must})
        self.addCleanup(self.prom.stop)
        self.dir = tempfile.mkdtemp(prefix="hb8-2-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def export(self, *args, chaos=None):
        m = base.manifest()
        if chaos is not None:
            m["chaos"] = chaos
        mp = os.path.join(self.dir, "manifest.json")
        with open(mp, "w") as f:
            json.dump(m, f)
        p = subprocess.run([sys.executable, base.EXPORT, os.path.join(self.dir, "out"), str(self.T0), str(self.T1),
                            "--manifest", mp] + list(args), env=dict(os.environ, PROM_URL=self.prom.url),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
        return p.returncode, p.stdout

    def kill_and_start(self, kill=600, start=900):
        return [{"node": self.KILLED, "action": "docker kill -s KILL telcoin", "begin_unix": self.T0 + kill},
                {"node": self.KILLED, "action": "systemctl start telcoin", "begin_unix": self.T0 + start}]

    def test_whole_series_pass_with_0(self):
        rc, out = self.export("--check-only")
        self.assertEqual(rc, 0, out)
        self.assertIn("EXPORT_COVERAGE_RESULT whole metrics=%d broken=0 expected=0 scrape=15s gap_max=120s" % len(self.must), out)
        self.assertNotRegex(out, r"(?m)^EXPORT_COVERAGE metric=\S+ node=")

    def test_a_stopped_series_refuses_with_3(self):
        self.prom.holes = {"bench-validator-08": [(1800, 99999)], OBSERVER: [(3000, 99999)]}
        rc, out = self.export("--check-only")
        self.assertEqual(rc, 3, out)
        self.assertRegex(out, r"(?m)^EXPORT_COVERAGE metric=%s node=bench-validator-08 first=\S+ last=2026-\S+ "
                              r"samples=120/241 longest_gap=1815s status=stopped breaks=\S+\(1815s,unexpected\)$" % self.must[0])
        self.assertRegex(out, r"(?m)^EXPORT_COVERAGE metric=%s nodes=11 whole=9 expected=- stopped=%s,bench-validator-08 "
                              % (self.must[0], OBSERVER))
        self.assertIn("EXPORT_COVERAGE_RESULT broken", out)
        rc, out = self.export()
        self.assertEqual(rc, 3, out)
        self.assertIn("EXPORT_REFUSED coverage_broken=", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out")))

    def test_the_killed_validators_gap_is_expected_with_4(self):
        self.prom.holes = {self.KILLED: [(600, 960)]}
        rc, out = self.export("--check-only", chaos=self.kill_and_start())
        self.assertEqual(rc, 4, out)
        self.assertRegex(out, r"(?m)^EXPORT_COVERAGE metric=%s node=%s first=\S+ last=\S+ samples=217/241 "
                              r"longest_gap=375s status=gap-expected breaks=\S+\(375s,expected\)$" % (self.must[0], self.KILLED))
        self.assertIn("EXPORT_COVERAGE_RESULT expected-gaps-only", out)
        rc, out = self.export(chaos=self.kill_and_start())
        self.assertEqual(rc, 4, out)
        self.assertIn("EXPORT_DONE", out)

    def test_a_gap_outside_the_chaos_window_refuses(self):
        self.prom.holes = {self.KILLED: [(600, 960), (2000, 2300)]}
        rc, out = self.export("--check-only", chaos=self.kill_and_start())
        self.assertEqual(rc, 3, out)
        self.assertRegex(out, r"(?m)^EXPORT_COVERAGE metric=%s node=%s .* status=gap breaks=\S+\(375s,expected\),"
                              r"\S+\(315s,unexpected\)$" % (self.must[0], self.KILLED))

    def test_a_kill_without_a_start_makes_its_stop_expected(self):
        self.prom.holes = {self.KILLED: [(600, 99999)]}
        rc, out = self.export("--check-only", chaos=self.kill_and_start()[:1])
        self.assertEqual(rc, 4, out)
        self.assertIn("status=stopped-expected", out)

    def test_short_holes_under_the_threshold_are_whole(self):
        self.prom.holes = {"bench-validator-02": [(k * 300, k * 300 + 30) for k in range(1, 11)]}
        rc, out = self.export("--check-only")
        self.assertEqual(rc, 0, out)
        rc, out = self.export("--check-only", "--gap-max", "30")
        self.assertEqual(rc, 3, out)

    def test_no_coverage_keeps_the_old_check(self):
        self.prom.holes = {"bench-validator-08": [(1800, 99999)]}
        rc, out = self.export("--check-only", "--no-coverage")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("EXPORT_COVERAGE", out)


# ---- 5. the plan for a bench 8 launch file ------------------------------------------------------------

class TestChainPlanBench8(base.SandboxCase):
    def test_plan_with_a_bench8_launch_file(self):
        env = os.path.join(base.REPO, "benchmark", "launch", "bench8-floor16.env")
        if not os.path.exists(env):
            env = os.path.join(base.REPO, "benchmark", "launch", "bench7-always.env")
        with open(base.REAL_LAUNCH) as f:
            fleet_pat = re.search(r"^readonly FLEET_PAT='([^']+)'", f.read(), re.M).group(1)
        if subprocess.run(["pgrep", "-f", "--", fleet_pat], stdout=subprocess.DEVNULL).returncode == 0:
            self.skipTest("a fleet driver runs on this host: the real launcher's dry run refuses")
        for d in ("launch", "arms"):
            src = os.path.join(base.REPO, "benchmark", d)
            dst = os.path.join(self.sb.root, "benchmark", d)
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(src):
                if os.path.isfile(os.path.join(src, f)) and (d == "arms" or f in ("launch.sh", os.path.basename(env))):
                    shutil.copy(os.path.join(src, f), dst)
        git = ["git", "-C", self.sb.root, "-c", "user.name=hb8", "-c", "user.email=hb8@example.invalid"]
        subprocess.run(git + ["add", "benchmark"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "sandbox"], check=True)
        self.sb.env_file = os.path.join(self.sb.root, "benchmark", "launch", os.path.basename(env))
        # The launch file's <...> placeholders are filled at the gate: fill them here (the run id is the sandbox's).
        def fill(m):
            key = m.group(1)
            val = RUN if key == "BENCH_RUN_ID" else ("sha256:" + "a" * 64 if "DIGEST" in key else
                                                     ("a" * 40 if ("COMMIT" in key or "SHA" in key) else "x"))
            return "%s=%s" % (key, val)
        with open(self.sb.env_file) as f:
            text = re.sub(r"(?m)^([A-Z0-9_]+)=<[^>\n]*>", fill, f.read())
        with open(self.sb.env_file, "w") as f:
            f.write(text)
        rc, out = self.chain(live=False, CHAIN_LAUNCH=os.path.join(self.sb.root, "benchmark", "launch", "launch.sh"),
                             CHAIN_DRIVER_PAT=fleet_pat)
        print("\nPLAN-ENV %s rc=%d\n%s" % (os.path.basename(env), rc, "\n".join(l for l in out.splitlines() if l.startswith("CHAIN ")))[:3000])
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"(?m)^CHAIN credentials ok at=preconditions token=ok ")
        self.assertRegex(out, r"(?m)^CHAIN plan step=2b sampler: ")
        self.assertRegex(out, r"(?m)^CHAIN plan step=3 also: .* read back from every node: quorum_exec_block_floor_outputs$")
        self.assertIn("CHAIN dry done: nothing was started", out)


if __name__ == "__main__":
    unittest.main()
