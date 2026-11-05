"""benchmark/obs-lib.sh, offline: bench-obs, the run's own metrics VM (Prometheus + Grafana).

Bench 4 (r20261105-0036) stopped at the deploy's obs-devnet disk gate: the bench shipped its metrics
to devnet's obs VM, whose Loki disk the live devnet fills. Now every run creates its own throwaway
VM (bench_obs_create, deploy step 2), brings a metrics-only stack up on it over IAP
(bench_obs_ensure, step 8), checks it before every phase that reads Prometheus (bench_obs_require)
and pulls a Prometheus TSDB snapshot before the teardown deletes it (bench_obs_prom_snapshot_pull).

Each test runs the real bench-lib.sh (which sources config.sh, the root config.sh and devnet-lib.sh)
in a copy of those scripts, as benchmark-deploy.sh would ($0 = benchmark-deploy.sh: config.sh loads
only for its allowlisted callers), then sources obs-lib.sh once more (harmless by design). GCP is
fixtures/obs/fake-gcloud.py, curl is fixtures/obs/stub-curl.sh (Prometheus and Grafana answer on a
local port once tunnel.log shows a forward to it), and sleep is a shell function that records its
argument and waits 0.2 s. TN_IAP_RETRIES=0 is pinned, as in every test that counts ssh sessions.
The dashboards are a fixture directory (one metrics dashboard, one Loki dashboard that must stay
behind) and the startup script a stub, so nothing here needs the common submodule. _bench_tunnel_start belongs to bench-lib.sh (unit U-O3); until it is
there the shim defines a stand-in with its contract.
"""
import base64
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIX = TESTS / "fixtures" / "obs"
OBS_LIB = BENCH / "obs-lib.sh"
CREATE_INSTANCES = REPO / "common" / "create-instances.sh"
COMMON_DASHBOARDS = REPO / "common" / "observability" / "obs-vm" / "grafana" / "dashboards"

RUN = "r20991231-0101"
OTHER_RUN = "r20991230-2359"
INST, ZONE = "bench-obs", "us-west2-a"
IP = "192.0.2.10"
PLACEHOLDER = "bench-obs-internal-ip.invalid"
SNAPSHOT = "20261105T120000Z-1a2b3c4d5e6f7a8b"
SCOPES = ",".join("https://www.googleapis.com/auth/" + s for s in (
    "devstorage.read_only", "logging.write", "monitoring.write", "service.management.readonly",
    "servicecontrol", "trace.append"))
ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
STEP8_HINT = "re-run with --only 8 (then continue with --from 9)"
RESUME_HINT = "resume with --only 8 (then re-run your segment: --from 10 --to 12 or --from 13 --to 15)"
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/obs-lib.sh", "benchmark/obs")
B64_RE = re.compile(r"<<'BENCH_OBS_BUNDLE_B64'.*?\n(.*?)\nBENCH_OBS_BUNDLE_B64\n", re.S)

SHIM = r"""
set -euo pipefail
source "$1/bench-lib.sh"
# bench-lib.sh sources obs-lib.sh itself (unit U-O3); a second source must change nothing.
source "$1/obs-lib.sh"
sleep() { printf '%s\n' "$1" >> "${FAKE_ROOT}/sleeps"; command sleep 0.2; }
# _bench_tunnel_start belongs to bench-lib.sh (unit U-O3). Until it lands, a stand-in with its
# contract: <pidfile> <inst> <zone> <local-port> <remote-host:port> <probe-cmd> <desc>; the plan line,
# BENCH_APPLY, the "already up" check, one tunnel.log start line, the pidfile, a probe of <= 45 s.
declare -F _bench_tunnel_start >/dev/null || _bench_tunnel_start() {
    local pidf="$1" inst="$2" zone="$3" lport="$4" target="$5" probe="$6" desc="$7" pid waited=0
    if [ -f "${pidf}" ] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "    tunnel already up (pid $(cat "${pidf}")) -> ${desc}"; return 0
    fi
    printf '    + gcloud compute ssh %s --zone=%s --project=%s --tunnel-through-iap --ssh-flag=-N --ssh-flag=-L --ssh-flag=localhost:%s:%s ... &   (supervised; >> %s)\n' \
        "${inst}" "${zone}" "${PROJECT_ID}" "${lport}" "${target}" "${BENCH_RESULTS_DIR}/tunnel.log"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    mkdir -p "${BENCH_RESULTS_DIR}"
    nohup sleep 300 >/dev/null 2>&1 &
    pid=$!
    echo "tunnel: start $(bench_now_iso) mode=ssh target=${inst}:${target##*:} local=${lport} pid=${pid}" >> "${BENCH_RESULTS_DIR}/tunnel.log"
    echo "${pid}" > "${pidf}"
    while [ "${waited}" -lt 45 ]; do
        if eval "${probe}" >/dev/null 2>&1; then echo "    ✓ tunnel up (pid ${pid}) -> ${desc}"; return 0; fi
        sleep 3; waited=$((waited + 3))
    done
    echo "❌ IAP tunnel to ${inst}:${target##*:} did not come up; see ${BENCH_RESULTS_DIR}/tunnel.log" >&2
    return 1
}
eval "$2"
"""


def vm_json(tags=("bench-obs",), run=RUN, benchmark="1", name=INST, status="RUNNING"):
    labels = {"network": "bench", "tn-role": "obs"}
    if benchmark is not None:
        labels["benchmark"] = benchmark
    if run is not None:
        labels["bench-run"] = run
    return {"name": name, "id": "777", "status": status, "creationTimestamp": "2026-11-05T03:00:00.000-08:00",
            "machineType": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/machineTypes/e2-standard-4" % ZONE,
            "tags": {"items": list(tags)}, "labels": labels,
            "networkInterfaces": [{"networkIP": IP, "accessConfigs": [{"natIP": "203.0.113.10"}]}],
            "disks": [{"boot": True, "deviceName": name, "diskSizeGb": "20",
                       "source": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/disks/%s" % (ZONE, name)},
                      {"boot": False, "deviceName": "obs-data", "diskSizeGb": "50",
                       "source": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/disks/%s-data" % (ZONE, name)}]}


class ObsCase(unittest.TestCase):
    """One sandbox per test: a copy of the scripts, a bin dir with the fakes, the fake's state."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="obs-test-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        for rel in TREE:
            src, dst = REPO / rel, self.tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
        self.bench = self.tree / "benchmark"
        self.results = self.bench / "results" / RUN
        self.results.mkdir(parents=True)
        self.state, self.bin, self.tmpdir = self.root / "state", self.root / "bin", self.root / "tmp"
        for d in (self.state, self.bin, self.tmpdir):
            d.mkdir()
        for name, src in (("gcloud", "fake-gcloud.py"), ("curl", "stub-curl.sh")):
            shutil.copyfile(str(FIX / src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.params = self.root / "consensus-params.yaml"
        self.params.write_text("max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n")
        self.startup = FIX / "startup-obs-stub.sh"
        self.dashboards = FIX / "dashboards"

    def tearDown(self):
        for pidf in self.results.glob("tunnel*.pid"):
            try:
                pid = int(pidf.read_text().strip())
            except ValueError:
                continue
            for target in (-pid, pid):
                try:
                    os.kill(target, 9)
                except OSError:
                    pass
        self._tmp.cleanup()

    def env(self, **extra):
        # Nothing from the developer's shell that the scripts read (BENCH_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir),
               "BENCH_RUN_ID": RUN, "BENCH_APPLY": "1", "BENCH_TXGEN_SHA": "abcdef1",
               "BENCH_PARAMETERS_FILE": str(self.params), "TN_IAP_RETRIES": "0", "BENCH_IAP_RETRIES": "1",
               "BENCH_OBS_DASHBOARDS_DIR": str(self.dashboards), "BENCH_OBS_STARTUP_SCRIPT": str(self.startup),
               "FAKE_ROOT": str(self.state), "FAKE_TUNNEL_LOG": str(self.results / "tunnel.log"),
               "FAKE_FORWARD_SECS": "30", "FAKE_SNAPSHOT_NAME": SNAPSHOT}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update({k: v for k, v in extra.items() if v is not None})
        for k in [k for k, v in extra.items() if v is None]:
            env.pop(k, None)
        return env

    def run_obs(self, script, **env):
        return subprocess.run(["bash", "-c", SHIM, "benchmark-deploy.sh", str(self.bench), script],
                              env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=120)

    # --- fake state ---------------------------------------------------------------------------
    def put(self, name, text):
        (self.state / name).write_text(text)

    def put_vm(self, **kw):
        self.put("vm.json", json.dumps(vm_json(**kw)))

    def calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def argvs(self, *prefix):
        return [c["argv"] for c in self.calls() if tuple(c["argv"][:len(prefix)]) == prefix]

    def ssh_commands(self):
        out = []
        for argv in self.argvs("compute", "ssh"):
            cmd = [a.split("=", 1)[1] for a in argv if a.startswith("--command=")]
            out.append(cmd[0] if cmd else None)
        return out

    def curl_calls(self):
        p = self.state / "curl-calls"
        return p.read_text().splitlines() if p.exists() else []

    def sleeps(self):
        p = self.state / "sleeps"
        return p.read_text().split() if p.exists() else []

    def manifest(self):
        return json.loads((self.results / "manifest.json").read_text())

    def write_manifest(self, **extra):
        doc = {"schema": "tn-bench-manifest/v1", "run_id": RUN}
        doc.update(extra)
        (self.results / "manifest.json").write_text(json.dumps(doc))

    def profile(self):
        """PROJECT_ID, SERVICE_ACCOUNT and BENCH_LABELS as the bench profile sets them."""
        p = self.run_obs('printf "%s\\n" "${PROJECT_ID}" "${SERVICE_ACCOUNT}" "${BENCH_LABELS}"')
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.splitlines()

    def assertDied(self, p, *phrases):
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        for phrase in phrases:
            self.assertIn(phrase, p.stderr)


class UrlTests(ObsCase):
    PRINT = ('bench_obs_urls; printf "IP=%s\\nPUSH=%s\\nLOGS=%s\\n" "${BENCH_OBS_INTERNAL_IP}" '
             '"${OBS_METRICS_PUSH_URL}" "${OBS_PUSH_URL}"; bash -c \'echo "EXPORTED=${BENCH_OBS_INTERNAL_IP:-no}"\'')

    def values(self, p):
        self.assertEqual(p.returncode, 0, p.stderr)
        return dict(line.split("=", 1) for line in p.stdout.splitlines())

    def test_without_a_manifest_the_placeholder_is_used(self):
        v = self.values(self.run_obs(self.PRINT))
        self.assertEqual(v["IP"], PLACEHOLDER)
        self.assertEqual(v["PUSH"], "http://%s:9090/api/v1/write" % PLACEHOLDER)
        self.assertEqual(v["EXPORTED"], PLACEHOLDER)
        self.assertEqual(self.calls(), [], "bench_obs_urls must not call gcloud")

    def test_the_manifest_ip_is_used(self):
        self.write_manifest(obs={"internal_ip": IP})
        v = self.values(self.run_obs(self.PRINT))
        self.assertEqual(v["IP"], IP)
        self.assertEqual(v["PUSH"], "http://%s:9090/api/v1/write" % IP)
        self.assertEqual(self.calls(), [])

    def test_an_explicit_ip_wins_and_the_log_push_url_is_untouched(self):
        self.write_manifest(obs={"internal_ip": IP})
        before = self.values(self.run_obs('printf "LOGS=%s\\n" "${OBS_PUSH_URL}"'))["LOGS"]
        v = self.values(self.run_obs(self.PRINT, BENCH_OBS_INTERNAL_IP="198.51.100.7"))
        self.assertEqual(v["IP"], "198.51.100.7")
        self.assertEqual(v["PUSH"], "http://198.51.100.7:9090/api/v1/write")
        self.assertEqual(v["LOGS"], before)


class CreateTests(ObsCase):
    def expected_create(self, project, account, labels):
        return ["compute", "instances", "create", INST, "--project=%s" % project, "--zone=%s" % ZONE,
                "--machine-type=e2-standard-4",
                "--image-family=debian-12", "--image-project=debian-cloud", "--boot-disk-size=20GB",
                "--boot-disk-type=pd-balanced",
                "--create-disk=name=%s-data,device-name=obs-data,size=50GB,type=pd-ssd,auto-delete=yes" % INST,
                "--tags=bench-obs", "--labels=%s,tn-role=obs" % labels,
                "--metadata-from-file=startup-script=%s" % self.startup,
                "--service-account=%s" % account, "--scopes=%s" % SCOPES, "--format=none"]

    def test_create_on_an_absent_vm_issues_the_contract_line(self):
        project, account, labels = self.profile()
        self.assertEqual(labels, "benchmark=1,network=bench,bench-run=%s" % RUN)
        self.write_manifest()
        p = self.run_obs('bench_obs_create; printf "IP=%s\\nPUSH=%s\\n" "${BENCH_OBS_INTERNAL_IP}" "${OBS_METRICS_PUSH_URL}"')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        creates = self.argvs("compute", "instances", "create")
        self.assertEqual(creates, [self.expected_create(project, account, labels)])
        flat = " ".join(creates[0])
        self.assertNotIn("--address", flat)
        self.assertNotIn("--no-address", flat)
        self.assertEqual(sorted(a[3] for a in self.argvs("compute", "disks", "add-labels")), [INST, INST + "-data"])
        for argv in self.argvs("compute", "disks", "add-labels"):
            self.assertIn("--labels=%s,tn-role=obs" % labels, argv)
            self.assertIn("--zone=%s" % ZONE, argv)
        self.assertIn("OBS_CREATE inst=%s zone=%s ip=%s id=4242424242424242424 existing=0" % (INST, ZONE, IP),
                      p.stdout.splitlines())
        self.assertIn("IP=%s" % IP, p.stdout.splitlines())
        self.assertIn("PUSH=http://%s:9090/api/v1/write" % IP, p.stdout.splitlines())
        obs = self.manifest()["obs"]
        created = obs.pop("created_at")
        self.assertRegex(created, "^%s$" % ISO)
        self.assertEqual(obs, {"instance": INST, "zone": ZONE, "machine_type": "e2-standard-4", "disk_gb": 50,
                               "internal_ip": IP, "instance_id": "4242424242424242424"})

    def test_dry_run_prints_the_create_and_calls_nothing(self):
        p = self.run_obs("bench_obs_create", BENCH_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("    + gcloud compute instances create %s --project=" % INST, p.stdout)
        self.assertIn("--tags=bench-obs", p.stdout)
        self.assertIn("(dry run — not executed)", p.stdout)
        self.assertEqual(p.stdout.splitlines()[-1],
                         "OBS_CREATE inst=%s zone=%s ip=%s id=- existing=dry" % (INST, ZONE, PLACEHOLDER))
        self.assertEqual(self.calls(), [])

    def test_a_failed_create_stops_the_run(self):
        self.put("create-fail", "")
        p = self.run_obs("bench_obs_create; echo AFTER")
        self.assertDied(p, "gcloud compute instances create %s failed" % INST,
                        "re-run with --from 2 (nodes are kept, this run's VM is adopted)")
        self.assertNotIn("AFTER", p.stdout)
        self.assertEqual(self.argvs("compute", "disks", "add-labels"), [])

    def test_a_transient_describe_is_retried_before_the_create(self):
        self.write_manifest()
        self.put("describe-transient", "2")
        p = self.run_obs("bench_obs_create")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.sleeps(), ["5", "5"])
        self.assertEqual(len(self.argvs("compute", "instances", "create")), 1)
        self.assertIn("existing=0", p.stdout.splitlines()[-1])

    def test_a_describe_that_keeps_failing_never_creates(self):
        self.put_vm()
        self.put("describe-transient", "always")
        p = self.run_obs("bench_obs_create; echo AFTER")
        self.assertDied(p, "describe failed 3× (transient API/auth error? re-run the step)")
        self.assertNotIn("AFTER", p.stdout)
        self.assertEqual(self.argvs("compute", "instances", "create"), [])
        self.assertEqual(len(self.argvs("compute", "instances", "describe")), 3)

    def test_a_missing_startup_script_is_refused_before_any_create(self):
        p = self.run_obs("bench_obs_create", BENCH_OBS_STARTUP_SCRIPT=str(self.root / "absent.sh"))
        self.assertDied(p, "startup script")
        self.assertEqual(self.argvs("compute", "instances", "create"), [])

    def test_the_scopes_are_the_nodes_scopes(self):
        if not CREATE_INSTANCES.is_file():
            self.skipTest("the common submodule is not checked out")
        m = re.search(r"--scopes=(\S+)", CREATE_INSTANCES.read_text())
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), SCOPES)
        self.assertIn('BENCH_OBS_SCOPES="%s"' % SCOPES, OBS_LIB.read_text())


class ExistingVmTests(ObsCase):
    def test_an_existing_vm_of_this_run_is_adopted(self):
        self.put_vm()
        self.write_manifest(obs={"created_at": "2026-11-05T11:00:00Z", "ready_at": "2026-11-05T11:09:00Z"})
        p = self.run_obs("bench_obs_create")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1],
                         "OBS_CREATE inst=%s zone=%s ip=%s id=777 existing=1" % (INST, ZONE, IP))
        self.assertEqual(self.argvs("compute", "instances", "create"), [])
        self.assertEqual(self.argvs("compute", "disks", "add-labels"), [])
        obs = self.manifest()["obs"]
        self.assertEqual(obs["created_at"], "2026-11-05T11:00:00Z", "an adopted VM keeps its recorded created_at")
        self.assertEqual(obs["ready_at"], "2026-11-05T11:09:00Z")
        self.assertEqual(obs["internal_ip"], IP)
        self.assertEqual(obs["instance_id"], "777")

    def test_a_vm_of_another_run_is_refused(self):
        # Only this run's bench-obs is ever adopted: another run's VM under the name, one without
        # benchmark=1, or one carrying another tag (a bench node's) with this run's labels is refused.
        cases = {"another run": dict(run=OTHER_RUN), "no bench-run label": dict(run=None),
                 "no benchmark label": dict(benchmark=None),
                 "a bench node's tag, this run's labels": dict(tags=("bench-node",)),
                 "an extra tag": dict(tags=("bench-obs", "http-server"))}
        for what, kw in cases.items():
            with self.subTest(what):
                for name in ("calls.jsonl", "vm.json"):
                    if (self.state / name).exists():
                        (self.state / name).unlink()
                self.put_vm(**kw)
                self.write_manifest()
                p = self.run_obs("bench_obs_create; echo AFTER")
                self.assertDied(p, "is not this run's bench-obs", "never adopted")
                self.assertNotIn("AFTER", p.stdout)
                self.assertNotIn("OBS_CREATE", p.stdout)
                self.assertEqual(self.argvs("compute", "instances", "create"), [])
                self.assertNotIn("obs", self.manifest())


    def test_a_stopped_vm_of_this_run_dies_with_the_start_hint(self):
        self.put_vm(status="TERMINATED")
        self.write_manifest()
        p = self.run_obs("bench_obs_create; echo AFTER")
        self.assertDied(p, "TERMINATED, not RUNNING", "gcloud compute instances start %s --zone %s" % (INST, ZONE))
        self.assertNotIn("AFTER", p.stdout)
        self.assertEqual(self.argvs("compute", "instances", "create"), [])
        self.assertEqual(self.argvs("compute", "instances", "get-serial-port-output"), [])
        self.assertNotIn("obs", self.manifest())


class BootTests(ObsCase):
    def test_returns_once_the_serial_shows_done(self):
        self.put("serial-done-at", "3")
        p = self.run_obs("bench_obs_wait_boot")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout.splitlines()[-1], r"^OBS_BOOT inst=%s secs=\d+$" % INST)
        self.assertEqual(len(self.argvs("compute", "instances", "get-serial-port-output")), 3)
        self.assertEqual(self.sleeps(), ["10", "10"])
        for argv in self.argvs("compute", "instances", "get-serial-port-output"):
            self.assertEqual(argv[3], INST)
            self.assertIn("--zone=%s" % ZONE, argv)

    def test_dies_on_timeout(self):
        self.put("serial-done-at", "never")
        p = self.run_obs("bench_obs_wait_boot; echo AFTER", BENCH_OBS_BOOT_TIMEOUT_SECS="20")
        self.assertDied(p, "within 20 s", "get-serial-port-output %s --zone=%s" % (INST, ZONE), STEP8_HINT)
        self.assertNotIn("AFTER", p.stdout)
        self.assertNotIn("OBS_BOOT", p.stdout)
        self.assertEqual(len(self.argvs("compute", "instances", "get-serial-port-output")), 3)
        self.assertEqual(self.sleeps(), ["10", "10"])


class BringupScriptTests(ObsCase):
    def script(self, **env):
        p = self.run_obs("bench_obs_bringup_script", **env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def bundle(self, script):
        m = B64_RE.search(script)
        self.assertIsNotNone(m, "no base64 bundle in the bring-up script")
        raw = gzip.decompress(base64.b64decode(m.group(1)))
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            members = {re.sub(r"^\./", "", t.name): t for t in tar.getmembers()}
            files = {n: tar.extractfile(t).read() for n, t in members.items() if t.isfile()}
        self.root_mode = members["."].mode if "." in members else None
        return files

    def test_script_carries_the_bundle_and_the_dashboards(self):
        script = self.script()
        self.assertEqual(script.splitlines()[0], "# bench-obs: bringup")
        files = self.bundle(script)
        self.assertEqual(sorted(files), ["docker-compose.yml", "grafana/dashboards/bench-metrics.json",
                                         "grafana/provisioning/dashboards/provider.yaml",
                                         "grafana/provisioning/datasources/prometheus.yaml", "prometheus.yml"])
        for rel in ("docker-compose.yml", "prometheus.yml", "grafana/provisioning/datasources/prometheus.yaml",
                    "grafana/provisioning/dashboards/provider.yaml"):
            self.assertEqual(files[rel], (BENCH / "obs" / rel).read_bytes(), rel)
        self.assertEqual(files["grafana/dashboards/bench-metrics.json"], (self.dashboards / "bench-metrics.json").read_bytes())
        # node-logs.json (Loki panels; bench-obs has no Loki) stays behind.
        self.assertTrue((self.dashboards / "node-logs.json").is_file())
        # The root entry becomes /opt/obs on the VM: 755, not mktemp's 700.
        self.assertEqual(self.root_mode & 0o777, 0o755)

    def test_script_writes_env_once_and_ends_with_the_stack_poll(self):
        script = self.script(BENCH_PROM_RETENTION="3d")
        p = subprocess.run(["bash", "-n"], input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        for needle in ("set -euo pipefail", "mkdir -p /opt/obs /mnt/obs-data/prometheus /mnt/obs-data/grafana",
                       "chown 65534:65534 /mnt/obs-data/prometheus", "chown 472:472 /mnt/obs-data/grafana",
                       "-C /opt/obs", "if [ ! -s /opt/obs/.env ]; then",
                       "computeMetadata/v1/instance/network-interfaces/0/ip", "openssl rand -hex 16",
                       "    retention=3d\n", "OBS_BIND_IP=%s\\nPROM_RETENTION=%s\\nGF_ADMIN_PASSWORD=%s\\n",
                       "chmod 600 /opt/obs/.env",
                       "docker compose -f /opt/obs/docker-compose.yml --env-file /opt/obs/.env up -d --remove-orphans",
                       "curl -sf --max-time 5 http://127.0.0.1:9090/-/ready",
                       "curl -sf --max-time 5 http://127.0.0.1:3000/api/health",
                       "-ge 120", "OBS_STACK_FAIL bench-obs reason="):
            self.assertIn(needle, script)
        self.assertEqual(script.rstrip("\n").splitlines()[-1],
                         'echo "OBS_STACK_OK bench-obs prom=ready grafana=ok secs=$(( $(date +%s) - t0 ))"')

    def test_the_real_dashboards_stage_metrics_only(self):
        if not COMMON_DASHBOARDS.is_dir():
            self.skipTest("the common submodule is not checked out")
        files = self.bundle(self.script(BENCH_OBS_DASHBOARDS_DIR=str(COMMON_DASHBOARDS)))
        staged = sorted(n[len("grafana/dashboards/"):] for n in files if n.startswith("grafana/dashboards/"))
        want = sorted(f.name for f in COMMON_DASHBOARDS.glob("*metrics*.json"))
        self.assertTrue(want, "no *metrics*.json in %s" % COMMON_DASHBOARDS)
        self.assertEqual(staged, want)
        self.assertNotIn("node-logs.json", staged)

    def test_a_dashboards_dir_without_a_metrics_dashboard_is_refused(self):
        only_logs = self.root / "logs-only"
        only_logs.mkdir()
        shutil.copyfile(str(self.dashboards / "node-logs.json"), str(only_logs / "node-logs.json"))
        p = self.run_obs("bench_obs_bringup_script", BENCH_OBS_DASHBOARDS_DIR=str(only_logs))
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertIn("no metrics dashboard", p.stderr)

    def test_a_missing_dashboards_dir_is_refused(self):
        p = self.run_obs("bench_obs_bringup_script", BENCH_OBS_DASHBOARDS_DIR=str(self.root / "absent"))
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertIn("dashboards dir", p.stderr)


class BringupTests(ObsCase):
    def test_an_ok_answer_passes_and_the_script_goes_to_sudo_bash(self):
        p = self.run_obs("bench_obs_bringup; echo AFTER")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "AFTER")
        self.assertIn("      OBS_STACK_OK bench-obs prom=ready grafana=ok secs=7", p.stdout)
        self.assertEqual(self.ssh_commands(), ["sudo bash -s"])
        self.assertEqual([c["stdin_head"] for c in self.calls()], ["# bench-obs: bringup"])
        self.assertTrue((self.state / "bringup-script.sh").read_text().startswith("# bench-obs: bringup\n"))

    def test_a_failed_stack_stops_the_run(self):
        self.put("bringup-answer", "OBS_STACK_FAIL bench-obs reason=grafana-not-healthy")
        self.put("bringup-rc", "1")
        p = self.run_obs("bench_obs_bringup; echo AFTER")
        self.assertDied(p, "the stack did not come up", "OBS_STACK_FAIL bench-obs reason=grafana-not-healthy", STEP8_HINT)
        self.assertNotIn("AFTER", p.stdout)

    def test_an_ok_line_that_is_not_last_is_not_enough(self):
        self.put("bringup-answer", "OBS_STACK_OK bench-obs prom=ready grafana=ok secs=7\nsomething after")
        p = self.run_obs("bench_obs_bringup; echo AFTER")
        self.assertDied(p, "the stack did not come up")


class TunnelTests(ObsCase):
    def test_dry_run_prints_both_forwards(self):
        p = self.run_obs("bench_obs_tunnel_up", BENCH_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        plan = [l for l in p.stdout.splitlines() if l.startswith("    + gcloud compute ssh ")]
        self.assertEqual(len(plan), 2, p.stdout)
        self.assertTrue(plan[0].startswith("    + gcloud compute ssh %s --zone=%s " % (INST, ZONE)), plan[0])
        self.assertIn("--ssh-flag=-L --ssh-flag=localhost:19090:127.0.0.1:9090 ", plan[0])
        self.assertIn("--ssh-flag=-L --ssh-flag=localhost:13000:127.0.0.1:3000 ", plan[1])
        self.assertEqual(p.stdout.count("(dry run — not executed)"), 2)
        self.assertEqual(list(self.results.glob("tunnel*.pid")), [])
        self.assertEqual(self.calls(), [])

    def test_two_forwards_start_with_their_pid_files(self):
        p = self.run_obs("bench_obs_tunnel_up")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sorted(f.name for f in self.results.glob("tunnel*.pid")),
                         ["tunnel-obs-grafana.pid", "tunnel-obs-prom.pid"])
        for name in ("tunnel-obs-grafana.pid", "tunnel-obs-prom.pid"):
            pid = int((self.results / name).read_text().strip())
            os.kill(pid, 0)   # alive
        log = (self.results / "tunnel.log").read_text().splitlines()
        for port, local in (("9090", "19090"), ("3000", "13000")):
            pat = re.compile(r"^tunnel: start %s mode=ssh target=%s:%s local=%s pid=\d+$" % (ISO, INST, port, local))
            self.assertTrue(any(pat.match(l) for l in log), "no start line for %s:%s in %s" % (INST, port, log))
        self.assertIn("✓ tunnel up (pid ", p.stdout)
        self.assertIn("-> http://127.0.0.1:19090/api/v1", p.stdout)
        self.assertIn("-> http://127.0.0.1:13000", p.stdout)
        # Both probes went through the forwards just opened.
        self.assertTrue(any("http://127.0.0.1:19090/api/v1/query?query=up" in c for c in self.curl_calls()))
        self.assertTrue(any("http://127.0.0.1:13000/api/health" in c for c in self.curl_calls()))
        # A second call finds both up and starts nothing.
        again = self.run_obs("bench_obs_tunnel_up")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout.count("tunnel already up"), 2, again.stdout)


    def test_a_failed_prometheus_forward_is_rc_1_and_a_failed_grafana_forward_rc_2(self):
        for down, want in (("prom-down", "1"), ("grafana-down", "2")):
            with self.subTest(down):
                for pidf in self.results.glob("tunnel*.pid"):
                    pid = int(pidf.read_text().strip())
                    for target in (-pid, pid):
                        try:
                            os.kill(target, 9)
                        except OSError:
                            pass
                    pidf.unlink()
                for name in ("prom-down", "grafana-down"):
                    if (self.state / name).exists():
                        (self.state / name).unlink()
                self.put(down, "")
                p = self.run_obs('rc=0; bench_obs_tunnel_up || rc=$?; echo "TRC=${rc}"')
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout.splitlines()[-1], "TRC=" + want)


class EnsureTests(ObsCase):
    def test_ensure_from_scratch(self):
        self.write_manifest()
        p = self.run_obs("bench_obs_ensure")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = p.stdout.splitlines()
        markers = [l.split()[0] for l in out if l.startswith("OBS_")]
        self.assertEqual(markers, ["OBS_CREATE", "OBS_BOOT", "OBS_READY"])
        self.assertRegex(out[-1], r"^OBS_READY inst=%s ip=%s secs=\d+$" % (INST, re.escape(IP)))
        self.assertEqual(len(self.argvs("compute", "instances", "create")), 1)
        self.assertIn("sudo bash -s", self.ssh_commands())
        obs = self.manifest()["obs"]
        self.assertRegex(obs["ready_at"], "^%s$" % ISO)
        self.assertEqual((obs["prom_local_port"], obs["grafana_local_port"], obs["ship_logs"]), (19090, 13000, False))
        self.assertEqual(obs["internal_ip"], IP)

    def test_ensure_on_a_ready_vm_skips_the_boot_wait(self):
        self.put_vm()
        self.write_manifest()
        p = self.run_obs("bench_obs_ensure")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("OBS_CREATE inst=%s zone=%s ip=%s id=777 existing=1" % (INST, ZONE, IP), p.stdout)
        self.assertNotIn("OBS_BOOT", p.stdout)
        self.assertIn("no boot wait", p.stdout)
        self.assertEqual(len(self.argvs("compute", "instances", "get-serial-port-output")), 1)
        self.assertEqual(self.argvs("compute", "instances", "create"), [])
        self.assertRegex(p.stdout.splitlines()[-1], r"^OBS_READY inst=%s ip=%s secs=\d+$" % (INST, re.escape(IP)))


    def test_a_failed_grafana_forward_only_warns(self):
        self.write_manifest()
        self.put("grafana-down", "")
        p = self.run_obs("bench_obs_ensure")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("the Grafana forward (localhost:13000) did not come up", p.stderr)
        self.assertRegex(p.stdout.splitlines()[-1], r"^OBS_READY inst=%s " % INST)

    def test_forwards_already_up_but_prometheus_silent_dies_before_ready(self):
        self.write_manifest()
        first = self.run_obs("bench_obs_ensure")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.put("prom-down", "")
        p = self.run_obs("bench_obs_ensure; echo AFTER")
        self.assertEqual(p.stdout.count("tunnel already up"), 2, p.stdout)
        self.assertDied(p, "Prometheus does not answer at http://127.0.0.1:19090/api/v1/query?query=up", STEP8_HINT)
        self.assertNotIn("OBS_READY", p.stdout)
        self.assertNotIn("AFTER", p.stdout)


class RequireTests(ObsCase):
    def test_a_gone_vm_dies_with_the_only_8_hint(self):
        p = self.run_obs("bench_obs_require; echo AFTER")
        self.assertDied(p, "%s is gone — %s" % (INST, RESUME_HINT))
        self.assertNotIn("--from 8", p.stderr)
        self.assertNotIn("AFTER", p.stdout)
        self.assertEqual(len(self.argvs("compute", "instances", "describe")), 1, "a 'not found' is not retried")
        self.assertEqual(list(self.results.glob("tunnel*.pid")), [])
        self.assertEqual(self.ssh_commands(), [])

    def test_a_transient_describe_is_retried(self):
        self.put_vm()
        self.put("describe-transient", "2")
        p = self.run_obs("bench_obs_require; echo AFTER")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "AFTER")
        self.assertEqual(self.sleeps()[:2], ["5", "5"])
        self.assertIn("again in 5 s (2/3)", p.stderr)
        self.assertNotIn("is gone", p.stderr)

    def test_a_describe_that_keeps_failing_dies_without_the_resume_hint(self):
        self.put_vm()
        self.put("describe-transient", "always")
        p = self.run_obs("bench_obs_require; echo AFTER")
        self.assertDied(p, "describe failed 3× (transient API/auth error? re-run the step)")
        self.assertNotIn("is gone", p.stderr)
        self.assertNotIn("AFTER", p.stdout)
        self.assertEqual(len(self.argvs("compute", "instances", "describe")), 3)
        self.assertEqual(self.sleeps(), ["5", "5"])
        self.assertEqual(list(self.results.glob("tunnel*.pid")), [])

    def test_a_failed_grafana_forward_only_warns(self):
        self.put_vm()
        self.put("grafana-down", "")
        p = self.run_obs("bench_obs_require; echo AFTER")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "AFTER")
        self.assertIn("the Grafana forward (localhost:13000) did not come up", p.stderr)

    def test_disk_over_the_threshold_warns_and_continues(self):
        self.put_vm()
        self.write_manifest(obs={"internal_ip": IP})
        self.put("df-pct", "85")
        p = self.run_obs("bench_obs_require; echo AFTER")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "AFTER")
        self.assertIn("85%", p.stderr)
        self.assertIn("warn only", p.stderr)
        self.assertIn("df --output=pcent /mnt/obs-data", self.ssh_commands())
        self.assertTrue(any(c.startswith("-sf --max-time 20 http://127.0.0.1:19090/api/v1/query?query=up")
                            for c in self.curl_calls()), self.curl_calls())

    def test_disk_under_the_threshold_is_quiet(self):
        self.put_vm()
        p = self.run_obs("bench_obs_require")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("data disk 12%", p.stdout)
        self.assertNotIn("⚠", p.stderr)

    def test_prometheus_not_answering_dies(self):
        self.put_vm()
        self.put("prom-down", "")
        p = self.run_obs("bench_obs_require; echo AFTER", BENCH_APPLY="1")
        self.assertDied(p, "the Prometheus forward (localhost:19090) did not come up", RESUME_HINT)
        self.assertNotIn("AFTER", p.stdout)


class SnapshotTests(ObsCase):
    PULL = 'bench_obs_prom_snapshot_pull "${BENCH_RESULTS_DIR}/logs"; echo "RC=$?"'

    def test_the_snapshot_is_pulled_and_recorded(self):
        self.write_manifest(obs={"internal_ip": IP})
        p = self.run_obs(self.PULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "RC=0")
        self.assertIn("-sS --max-time 120 -XPOST http://127.0.0.1:19090/api/v1/admin/tsdb/snapshot", self.curl_calls())
        cmd = "sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots %s | gzip -1" % SNAPSHOT
        self.assertEqual(self.ssh_commands(), [cmd])
        files = list((self.results / "logs").glob("bench-obs-prometheus-*.tar.gz"))
        self.assertEqual(len(files), 1, files)
        self.assertRegex(files[0].name, r"^bench-obs-prometheus-\d{8}T\d{6}Z\.tar\.gz$")
        with tarfile.open(str(files[0])) as tar:
            self.assertTrue(all(n.startswith(SNAPSHOT + "/") for n in tar.getnames()), tar.getnames())
        rel = "logs/" + files[0].name
        snap = self.manifest()["obs"]["prom_snapshot"]
        at = snap.pop("at")
        self.assertRegex(at, "^%s$" % ISO)
        self.assertEqual(snap, {"name": SNAPSHOT, "file": rel, "bytes": files[0].stat().st_size})
        self.assertIn("OBS_SNAPSHOT inst=%s name=%s bytes=%d file=%s" % (INST, SNAPSHOT, files[0].stat().st_size, rel),
                      p.stdout.splitlines())
        self.assertNotIn("does not list", p.stderr)
        self.assertEqual(self.manifest()["obs"]["internal_ip"], IP, "the rest of manifest.obs is kept")

    def test_a_failed_snapshot_request_is_warn_only(self):
        self.write_manifest()
        self.put("curl-snapshot-fail", "")
        p = self.run_obs(self.PULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "RC=0")
        self.assertIn("snapshot request failed", p.stderr)
        self.assertEqual(self.ssh_commands(), [])
        self.assertNotIn("obs", self.manifest())
        self.assertFalse((self.results / "logs").exists() and list((self.results / "logs").iterdir()))

    def test_a_failed_stream_is_warn_only(self):
        self.write_manifest()
        self.put("snapshot-fail", "")
        p = self.run_obs(self.PULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[-1], "RC=0")
        self.assertIn("not pulled", p.stderr)
        self.assertEqual(list((self.results / "logs").iterdir()), [], "no partial or temp file is left")
        self.assertNotIn("obs", self.manifest())
        self.assertNotIn("OBS_SNAPSHOT", p.stdout)

    def test_a_cut_archive_is_kept_with_a_warning(self):
        self.write_manifest()
        self.put("snapshot-cut", "")
        p = self.run_obs(self.PULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("does not list as a whole tar archive", p.stderr)
        self.assertEqual(len(list((self.results / "logs").glob("bench-obs-prometheus-*.tar.gz"))), 1)
        self.assertIn("OBS_SNAPSHOT inst=%s name=%s " % (INST, SNAPSHOT), p.stdout)

    def test_pull_prom_0_skips_it(self):
        self.write_manifest()
        p = self.run_obs(self.PULL, BENCH_OBS_PULL_PROM="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), ["    bench-obs: Prometheus snapshot skipped (BENCH_OBS_PULL_PROM=0)", "RC=0"])
        self.assertEqual(self.curl_calls(), [])
        self.assertEqual(self.calls(), [])

    def test_dry_run_prints_the_argv_only(self):
        p = self.run_obs(self.PULL, BENCH_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("curl -sS -XPOST http://127.0.0.1:19090/api/v1/admin/tsdb/snapshot", p.stdout)
        self.assertIn("'sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots <name> | gzip -1'", p.stdout)
        self.assertIn("(dry run — not executed)", p.stdout)
        self.assertEqual(self.curl_calls(), [])
        self.assertEqual(self.calls(), [])


class PlanTests(ObsCase):
    def test_plan_lines_for_steps_2_and_8(self):
        p = self.run_obs("bench_obs_plan_lines 2; echo ---; bench_obs_plan_lines 8", BENCH_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        two, eight = p.stdout.split("---\n")
        for needle in (INST, ZONE, "e2-standard-4", "50 GB pd-ssd", "tag bench-obs", "tn-role=obs", RUN):
            self.assertIn(needle, two)
        for needle in ("prom/prometheus:v3.1.0", "grafana/grafana:11.4.0", "localhost:19090", "localhost:13000",
                       ":9090/api/v1/write", "[obs-startup]"):
            self.assertIn(needle, eight)
        self.assertEqual(self.calls(), [])

    def test_an_unknown_step_is_refused(self):
        p = self.run_obs("bench_obs_plan_lines 5", BENCH_APPLY="0")
        self.assertEqual(p.returncode, 2)
        self.assertIn("no plan text for step '5'", p.stderr)


if __name__ == "__main__":
    unittest.main()
