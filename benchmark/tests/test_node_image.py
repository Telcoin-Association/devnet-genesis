"""The node image probe (bench-lib.sh) and deploy step 9's boot-line check, fully offline.

Every bash run happens in a temporary copy of the scripts (the deploy script's results root is
fixed to <its dir>/results, so nothing here ever runs the scripts in place), with stub `docker`,
`gcloud` and `curl` first on PATH (fixtures/node-image/stub-*.sh). The "image" the stub docker
serves is a directory: the -V / --version / --help texts and the fake binary the probe copies out
and greps (fixtures/node-image/{out-*,help-*,fake-node-bin}.txt), varied per test. The stub curl
fails the run if anything tries the network.

Step 9's remote script (--print-postconfig) is run under `bash -s` on this host, its absolute
node paths (/opt/telcoin, /etc/telcoin, /etc/systemd/system, the sampler in /usr/local/bin)
relocated into a sandbox directory, with stub docker/curl/systemctl/date/sleep standing in for
the node; on a BSD-sed host (macOS) a shim gives the script the GNU `sed -i` it targets.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "node-image"

REF = "test-docker.pkg.dev/tn-fake/node:bench-test"
DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64
PINNED = "test-docker.pkg.dev/tn-fake/node@" + DIGEST
FULL_SHA = "5ca1ab1e0ddba11c0ffee0123456789abcdef012"
BAD_SHA = "deadbeef" * 5
SUBSECOND = "subsecond_timestamp active from genesis"
ADIRI = "fork schedule (adiri)"
NODES = ["bench-validator-%02d" % n for n in range(1, 11)] + ["bench-observer-11"]
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Scripts the bash under test sources or runs, relative to the repo root.
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
        "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
        "benchmark/node-image-contract.txt")
PARAMS_YAML = "max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n"


def make_tree(root):
    """Copy the scripts into <root> (same layout as the repo); returns <root>/benchmark."""
    for rel in TREE:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    return root / "benchmark"


def install(bindir, name, fixture):
    bindir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIX / fixture, bindir / name)
    (bindir / name).chmod(0o755)


def contract_entries(path):
    """(directive, string) per line of a node-image contract, as bench-lib.sh reads it."""
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.rstrip("\r").lstrip()
        if not line or line.startswith("#"):
            continue
        directive, _, rest = line.partition(" ")
        out.append((directive, rest.lstrip(" ")))
    return out


def host_sed_is_gnu():
    return subprocess.run(["sed", "--version"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


class BashCase(unittest.TestCase):
    """One sandbox per test: a copy of the scripts, a stub bin dir, a call log, a TMPDIR."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="node-image-test-")
        self.root = Path(self._tmp.name)
        self.bench = make_tree(self.root / "tree")
        self.bin = self.root / "bin"
        install(self.bin, "docker", "stub-docker.sh")
        install(self.bin, "gcloud", "stub-gcloud.sh")
        install(self.bin, "curl", "stub-curl-forbidden.sh")
        self.log = self.root / "stub-calls.txt"
        self.log.write_text("")
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.params = self.root / "consensus-params.yaml"
        self.params.write_text(PARAMS_YAML)
        self.image = self.root / "image"
        self.make_image()

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **extra):
        # Nothing from the developer's shell that the scripts read (BENCH_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir),
               "BENCH_RUN_ID": "rtest-node-image", "BENCH_APPLY": "0", "BENCH_TXGEN_SHA": "abcdef1",
               "BENCH_PARAMETERS_FILE": str(self.params), "STUB_LOG": str(self.log),
               "STUB_IMAGE_DIR": str(self.image), "STUB_DIGEST": DIGEST}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update({k: v for k, v in extra.items() if v is not None})
        for k in [k for k, v in extra.items() if v is None]:
            env.pop(k, None)
        return env

    def make_image(self, markers=(SUBSECOND,), drop=(), short_version=None, long_version=None,
                   genesis_help=None):
        """The stub docker's image: the fixture texts, the fake binary minus <drop> plus <markers>."""
        self.image.mkdir(exist_ok=True)
        for name in ("out-short-version.txt", "out-long-version.txt", "help-node.txt",
                     "help-genesis.txt", "help-keytool.txt"):
            shutil.copyfile(FIX / name, self.image / name)
        lines = [l for l in (FIX / "fake-node-bin.txt").read_text().splitlines() if l not in drop]
        (self.image / "node-bin").write_text("\n".join(lines + list(markers)) + "\n")
        if short_version is not None:
            (self.image / "out-short-version.txt").write_text(short_version)
        if long_version is not None:
            (self.image / "out-long-version.txt").write_text(long_version)
        if genesis_help is not None:
            (self.image / "help-genesis.txt").write_text(genesis_help)

    def calls(self):
        return self.log.read_text().splitlines()

    def bash(self, script, *args, **env):
        # $0 = benchmark-deploy.sh: config.sh only loads for its allowlisted callers.
        return subprocess.run(["bash", "-c", script, "benchmark-deploy.sh"] + [str(a) for a in args],
                              env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=120, universal_newlines=True, errors="replace")


PROBE = r'''
set -euo pipefail
source "$1/bench-lib.sh"
if [ -n "${TEST_CONTRACT:-}" ]; then BENCH_NODE_CONTRACT_FILE="${TEST_CONTRACT}"; fi
bench_node_image_probe "$2"
env | LC_ALL=C sort | grep '^BENCH_NODE_' | sed 's/^/GLOBAL /'
'''


class ProbeResult:
    def __init__(self, proc):
        self.rc = proc.returncode
        self.out = proc.stdout
        self.globals = {}
        for line in self.out.splitlines():
            if line.startswith("GLOBAL "):
                key, _, value = line[len("GLOBAL "):].partition("=")
                self.globals[key] = value


class ProbeTests(BashCase):
    def probe(self, ref=REF, **env):
        return ProbeResult(self.bash(PROBE, self.bench, ref, **env))

    def assertAccepted(self, r):
        self.assertEqual(r.rc, 0, r.out)
        self.assertEqual(r.globals.get("BENCH_NODE_FLAGS_OK"), "1", r.out)

    def assertRefused(self, r, *phrases):
        self.assertNotEqual(r.rc, 0, r.out)
        self.assertEqual(r.globals, {}, "a refused probe exported results:\n" + r.out)
        for phrase in phrases:
            self.assertIn(phrase, r.out)
        # The probe's EXIT trap removed its temp dirs; no network was attempted.
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertFalse([c for c in self.calls() if c.startswith("curl ")])

    def test_fixture_binary_carries_every_required_string(self):
        binary = (FIX / "fake-node-bin.txt").read_text()
        for directive, string in contract_entries(BENCH / "node-image-contract.txt"):
            if directive == "require":
                self.assertIn(string, binary, "node-image-contract.txt gained a require line; "
                              "add it to fixtures/node-image/fake-node-bin.txt")
            else:
                self.assertNotIn(string, binary, "fake-node-bin.txt must not carry fork markers")

    def test_good_image_pins_digest_and_exports_provenance(self):
        r = self.probe()
        self.assertAccepted(r)
        g = r.globals
        self.assertEqual(g["BENCH_NODE_IMAGE_REF"], REF)
        self.assertEqual(g["BENCH_NODE_IMAGE_DIGEST"], DIGEST)
        self.assertEqual(g["BENCH_NODE_IMAGE_PINNED"], PINNED)
        self.assertEqual(g["BENCH_NODE_VERSION"], "0.1.0")
        # -V names 12 digits; the probe keeps the longer --version Commit SHA.
        self.assertEqual(g["BENCH_NODE_GIT_SHA"], FULL_SHA)
        self.assertRegex(g["BENCH_NODE_GIT_SHA"], r"^[0-9a-f]{40}$")
        self.assertEqual(g["BENCH_NODE_FORK_SCHEDULE"], "subsecond-from-genesis")
        self.assertRegex(g["BENCH_NODE_PROBE_AT"], ISO_RE)
        strings = json.loads(g["BENCH_NODE_STRINGS_JSON"])
        self.assertEqual(strings[ADIRI], 0)
        self.assertGreaterEqual(strings[SUBSECOND], 1)
        entries = contract_entries(BENCH / "node-image-contract.txt")
        self.assertEqual(set(strings), {s for _d, s in entries})
        for directive, string in entries:
            if directive == "require":
                self.assertGreaterEqual(strings[string], 1, string)
        self.assertIn("✓ fork schedule: subsecond-from-genesis", r.out)
        calls = self.calls()
        # Logged in through a throwaway --config dir, pulled by digest, and every binary run
        # (and the copy-out) used the pinned bytes, never the mutable tag.
        self.assertTrue(any(c.startswith("docker --config ") and " login -u oauth2accesstoken " in c
                            for c in calls), calls)
        self.assertTrue(any(c.startswith("docker --config ") and
                            c.endswith(" pull --quiet --platform linux/amd64 " + PINNED) for c in calls), calls)
        runs = [c for c in calls if c.startswith("docker run ") or c.startswith("docker create ")]
        self.assertEqual(len(runs), 6, calls)
        for c in runs:
            self.assertIn(" --pull=never ", c)
            self.assertIn(" " + PINNED + " ", c + " ")
            self.assertNotIn(REF, c)
        self.assertIn("docker rm -f stubcid0001", calls)
        self.assertFalse([c for c in calls if c.startswith("curl ")])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_adiri_marker_is_adiri_schedule_and_refused_when_subsecond_expected(self):
        self.make_image(markers=(ADIRI,))
        r = self.probe()
        self.assertAccepted(r)
        self.assertEqual(r.globals["BENCH_NODE_FORK_SCHEDULE"], "adiri-schedule")
        strings = json.loads(r.globals["BENCH_NODE_STRINGS_JSON"])
        self.assertEqual((strings[ADIRI], strings[SUBSECOND]), (1, 0))
        r = self.probe(BENCH_NODE_EXPECT_FORKS="subsecond-from-genesis")
        self.assertRefused(r, "fork schedule is adiri-schedule, not "
                              "BENCH_NODE_EXPECT_FORKS=subsecond-from-genesis")

    def test_neither_marker_is_pre_subsecond_and_both_markers_refused(self):
        self.make_image(markers=())
        r = self.probe()
        self.assertAccepted(r)
        self.assertEqual(r.globals["BENCH_NODE_FORK_SCHEDULE"], "pre-subsecond")
        self.make_image(markers=(SUBSECOND, ADIRI))
        r = self.probe()
        self.assertRefused(r, "image carries both markers", "'" + ADIRI + "'")

    def test_unknown_git_sha_refused(self):
        self.make_image(short_version="0.1.0 (unknown)\n")
        r = self.probe()
        self.assertRefused(r, "image built without git metadata")

    def test_genesis_help_without_max_header_delay_refused(self):
        help_text = (FIX / "help-genesis.txt").read_text()
        self.assertIn("--max-header-delay-ms", help_text)
        self.make_image(genesis_help=help_text.replace("--max-header-delay-ms <MS>\n", ""))
        r = self.probe()
        self.assertRefused(r, "'telcoin genesis --help' lacks: --max-header-delay-ms")

    def test_missing_required_string_refused_and_listed(self):
        self.make_image(drop=("FatalDBFailure", "quorum reached"))
        r = self.probe()
        self.assertRefused(r, "lacks these contract strings:")
        listed = r.out.split("lacks these contract strings:", 1)[1].split()
        self.assertIn("FatalDBFailure", listed)
        self.assertIn("quorum", listed)
        # The container it created for the copy-out is removed.
        self.assertIn("docker rm -f stubcid0001", self.calls())

    def test_expected_sha_and_digest(self):
        r = self.probe(BENCH_NODE_EXPECT_SHA="deadbeef")
        self.assertRefused(r, "is git %s, not BENCH_NODE_EXPECT_SHA=deadbeef" % FULL_SHA)
        self.log.write_text("")
        r = self.probe(BENCH_DOCKER_IMAGE_EXPECT_DIGEST=OTHER_DIGEST)
        self.assertRefused(r, "resolves to %s, not BENCH_DOCKER_IMAGE_EXPECT_DIGEST=%s"
                           % (DIGEST, OTHER_DIGEST))
        # A digest that is not the expected one stops the probe before the pull.
        self.assertFalse([c for c in self.calls() if " pull " in c or c.startswith("docker run ")])
        r = self.probe(BENCH_NODE_EXPECT_SHA=FULL_SHA[:7].upper(), BENCH_DOCKER_IMAGE_EXPECT_DIGEST=DIGEST,
                       BENCH_NODE_EXPECT_FORKS="subsecond-from-genesis")
        self.assertAccepted(r)
        self.assertEqual(r.globals["BENCH_NODE_GIT_SHA"], FULL_SHA)
        r = self.probe(BENCH_NODE_EXPECT_SHA=FULL_SHA)
        self.assertAccepted(r)

    def test_commit_sha_disagreeing_with_dash_v_refused(self):
        long_text = (FIX / "out-long-version.txt").read_text().replace(FULL_SHA, BAD_SHA)
        self.make_image(long_version=long_text)
        r = self.probe()
        self.assertRefused(r, "'-V' names %s but '--version' names Commit SHA %s" % (FULL_SHA[:12], BAD_SHA))

    def test_contract_comments_blank_lines_spacing_and_crlf(self):
        contract = self.root / "contract-variant.txt"
        contract.write_text(
            "# a comment line\n"
            "\n"
            "   \t\n"
            "    # an indented comment: require not-a-string\n"
            "require     quorum reached\r\n"
            "\trequire subdag committed\n"
            "require-if-subsecond  " + SUBSECOND + "\n"
            "forbid-if-subsecond " + ADIRI)   # no trailing newline
        r = self.probe(TEST_CONTRACT=str(contract))
        self.assertAccepted(r)
        self.assertEqual(json.loads(r.globals["BENCH_NODE_STRINGS_JSON"]),
                         {"quorum reached": 1, "subdag committed": 1, SUBSECOND: 1, ADIRI: 0})
        self.assertIn("4 contract strings checked (2 required, all present)", r.out)
        self.assertEqual(r.globals["BENCH_NODE_FORK_SCHEDULE"], "subsecond-from-genesis")

    def test_malformed_contract_refused(self):
        contract = self.root / "contract-variant.txt"
        cases = [("require quorum reached\nexpect FatalDBFailure\n", ":2: unknown directive 'expect'"),
                 ("require quorum reached\nrequire\n", ":2: 'require' is not '<directive> <string>'"),
                 ("# only markers\nrequire-if-subsecond " + SUBSECOND + "\n", "has no require line")]
        for text, phrase in cases:
            with self.subTest(phrase=phrase):
                contract.write_text(text)
                r = self.probe(TEST_CONTRACT=str(contract))
                self.assertRefused(r, str(contract) + phrase if phrase.startswith(":") else phrase)

    def test_no_digest_or_no_docker_refused(self):
        # Not a Google registry host: no registry HEAD fallback (and so no curl) either.
        r = self.probe("reg.example.invalid/tn-fake/node:bench-test", STUB_DIGEST=None)
        self.assertRefused(r, "no registry digest")
        self.assertEqual([c.split(" --format")[0] for c in self.calls()],
                         ["docker info",
                          "gcloud artifacts docker images describe reg.example.invalid/tn-fake/node:bench-test"])
        r = self.probe(STUB_DOCKER_DOWN="1")
        self.assertRefused(r, "needs a running docker")


HELPERS = r'''
set -euo pipefail
source "$1/bench-lib.sh"
for k in max_header_delay min_header_delay max_batch_delay quoted_secs minutes sync_retry_delay \
         tail_block gc_depth absent_key; do
    printf 'MS %s=%s\n' "$k" "$(bench_params_ms "$2" "$k")"
done
printf 'MS unreadable=%s\n' "$(bench_params_ms "$2.missing" max_header_delay)"
for t in c3-standard-8 c3d-highcpu-16 n2-standard-4 n2d-standard-2 n4-standard-2 e2-medium \
         n1-standard-1 t2d-standard-1 c3-custom-4-8192; do
    printf 'QUOTA %s=%s\n' "$t" "$(bench_cpu_quota_metric "$t")"
done
D=sha256:1111111111111111111111111111111111111111111111111111111111111111
for r in reg.example.invalid/tn/node:v1 reg.example.invalid:5000/tn/node:v1 \
         reg.example.invalid/tn/node "reg.example.invalid/tn/node@sha256:$(printf '2%.0s' {1..64})" \
         reg.example.invalid:5000/node; do
    printf 'PIN %s=%s\n' "$r" "$(bench_image_pin "$r" "$D")"
done
rc=0; out="$(bench_image_pin reg.example.invalid/tn/node:v1 sha256:abc)" || rc=$?
printf 'PIN bad-digest rc=%s out=%s\n' "$rc" "$out"
printf 'DIGEST at=%s\n' "$(bench_image_digest "test-docker.pkg.dev/tn/node@$D")"
printf 'DIGEST short=%s\n' "$(bench_image_digest "test-docker.pkg.dev/tn/node@sha256:1234")"
printf 'DIGEST empty=%s\n' "$(bench_image_digest '')"
'''


class HelperTests(BashCase):
    def test_params_quota_pin_and_digest_helpers(self):
        yaml = self.root / "helper-params.yaml"
        yaml.write_text(
            "# synthetic consensus timing\n"
            "max_header_delay_ms: 9ms\n"          # a longer key sharing the prefix is not the key
            "max_header_delay: 500ms\n"
            "min_header_delay: 250ms   # a trailing comment\n"
            "max_batch_delay: 1.5s\n"
            "quoted_secs: '3s'\n"
            "minutes: 2m\n"
            "gc_depth: 50\n"
            "sync_retry_delay:\n"
            "  secs: 2\n"
            "\n"
            "  nanos: 500000000\n"
            "other: 1s\n"
            "tail_block:\n"
            "  nanos: 1250000\n")
        p = self.bash(HELPERS, self.bench, yaml)
        self.assertEqual(p.returncode, 0, p.stdout)
        got = {}
        for line in p.stdout.splitlines():
            kind, _, rest = line.partition(" ")
            if kind in ("MS", "QUOTA", "PIN", "DIGEST"):
                got[kind + " " + rest.split("=", 1)[0]] = rest.split("=", 1)[1] if "=" in rest else ""
        ms = {k[3:]: v for k, v in got.items() if k.startswith("MS ")}
        self.assertEqual(ms, {"max_header_delay": "500", "min_header_delay": "250",
                              "max_batch_delay": "1500", "quoted_secs": "3000", "minutes": "120000",
                              "sync_retry_delay": "2500", "tail_block": "1", "gc_depth": "",
                              "absent_key": "", "unreadable": ""})
        quota = {k[6:]: v for k, v in got.items() if k.startswith("QUOTA ")}
        self.assertEqual(quota, {"c3-standard-8": "C3_CPUS", "c3d-highcpu-16": "C3D_CPUS",
                                 "n2-standard-4": "N2_CPUS", "n2d-standard-2": "N2D_CPUS",
                                 "n4-standard-2": "N4_CPUS", "e2-medium": "CPUS",
                                 "n1-standard-1": "CPUS", "t2d-standard-1": "CPUS",
                                 "c3-custom-4-8192": "C3_CPUS"})
        d = "sha256:" + "1" * 64
        self.assertEqual(got["PIN reg.example.invalid/tn/node:v1"], "reg.example.invalid/tn/node@" + d)
        self.assertEqual(got["PIN reg.example.invalid:5000/tn/node:v1"],
                         "reg.example.invalid:5000/tn/node@" + d)
        self.assertEqual(got["PIN reg.example.invalid/tn/node"], "reg.example.invalid/tn/node@" + d)
        self.assertEqual(got["PIN reg.example.invalid/tn/node@sha256:" + "2" * 64],
                         "reg.example.invalid/tn/node@" + d)
        self.assertEqual(got["PIN reg.example.invalid:5000/node"], "reg.example.invalid:5000/node@" + d)
        self.assertEqual(got["PIN bad-digest rc"], "1 out=")
        self.assertEqual(got["DIGEST at"], d)
        self.assertEqual(got["DIGEST short"], "")
        self.assertEqual(got["DIGEST empty"], "")
        # A digest ref answers from the ref itself: no gcloud, no registry HEAD.
        self.assertEqual(self.calls(), [])


class Step9Tests(BashCase):
    """`benchmark-deploy.sh --yes --only 9` on a mock run whose manifest names the build."""

    RUN = "rtest-step9"

    def setUp(self):
        super().setUp()
        self.run_dir = self.bench / "results" / self.RUN
        self.run_dir.mkdir(parents=True)
        self.manifest = self.run_dir / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema": "tn-bench-manifest/v1", "run_id": self.RUN, "docker_image": REF,
            "node_git_sha": FULL_SHA, "node_fork_schedule": "subsecond-from-genesis",
            "consensus_parameters": {
                "file": self.params.name, "sha256": hashlib.sha256(self.params.read_bytes()).hexdigest(),
                "max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250},
            "timestamps": {}, "phases": [], "chaos": [], "instances": [], "notes": []}, indent=2) + "\n")
        self.spool = self.root / "remote-stdin"
        self.spool.mkdir()

    def deploy(self, **env):
        return subprocess.run(
            ["bash", str(self.bench / "benchmark-deploy.sh"), "--run", self.RUN, "--yes", "--only", "9"],
            env=self.env(BENCH_RUN_ID=None, STUB_SHA=FULL_SHA, STUB_SPOOL=str(self.spool), **env),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, universal_newlines=True,
            errors="replace")

    def ssh_targets(self):
        return [c.split()[3] for c in self.calls() if c.startswith("gcloud compute ssh ")]

    def test_every_node_boots_the_manifest_build(self):
        p = self.deploy()
        self.assertEqual(p.returncode, 0, p.stdout)
        m = json.loads(self.manifest.read_text())
        self.assertEqual(sorted(m["node_startup"]), sorted(NODES))
        for inst in NODES:
            self.assertEqual(m["node_startup"][inst], {"sha": FULL_SHA, "mhd": 500, "nhd": 250, "mbd": 250,
                                                       "vt": None, "forks": "subsecond-from-genesis"}, inst)
        self.assertIn("step_9_done", m["timestamps"])
        # Serially: each node's log saved, then its post-config session, in fleet order.
        self.assertEqual(self.ssh_targets(), [n for n in NODES for _ in (0, 1)])
        self.assertIn("POSTCFG_OK bench-validator-01 ", (self.spool / "bench-validator-01.sh").read_text())
        self.assertFalse([c for c in self.calls() if not c.startswith("gcloud compute ssh ")])

    def test_wrong_sha_on_first_node_stops_the_fleet(self):
        p = self.deploy(STUB_BAD_INST="bench-validator-01", STUB_BAD_SHA=BAD_SHA)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-01: boot sha = %s, expected %s" % (BAD_SHA, FULL_SHA), p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01", "bench-validator-01"])
        m = json.loads(self.manifest.read_text())
        self.assertEqual(list(m["node_startup"]), ["bench-validator-01"])
        self.assertEqual(m["node_startup"]["bench-validator-01"]["sha"], BAD_SHA)
        self.assertNotIn("step_9_done", m["timestamps"])

    def test_short_manifest_sha_matches_by_prefix_and_delay_mismatch_stops(self):
        m = json.loads(self.manifest.read_text())
        m["node_git_sha"] = FULL_SHA[:9]
        self.manifest.write_text(json.dumps(m, indent=2) + "\n")
        p = self.deploy(STUB_MHD="3000")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-01: max_header_delay = 3000 ms, expected 500 ms", p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01", "bench-validator-01"])
        self.assertNotIn("boot sha =", p.stdout)


class RemoteScriptTests(BashCase):
    """Step 9's remote script (--print-postconfig) against a stubbed node."""

    RELOCATE = ("/opt/telcoin/", "/etc/telcoin/", "/etc/systemd/system/",
                "/usr/local/bin/bench-node-sampler.sh")

    def setUp(self):
        super().setUp()
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"),
                            "--print-postconfig", "bench-validator-01"],
                           env=self.env(BENCH_RUN_ID="rtest-postcfg"), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])   # printing the script contacts nothing
        script = p.stdout
        self.chain_hex = re.search(r'\[ "\$cid" = "(0x[0-9a-f]+)" \]', script).group(1)
        self.label = re.search(r"grep -qx 'TN_CHAIN=([^']+)'", script).group(1)
        self.node = self.root / "node-root"
        for rel in self.RELOCATE:
            self.assertIn(rel, script)
            script = script.replace(rel, str(self.node) + rel)
        # Every redirection now lands in the sandbox (or /dev/null).
        for target in re.findall(r"(?<![0-9&-])>\s*(/[^\s;|&)]*)", script):
            self.assertTrue(target == "/dev/null" or target.startswith(str(self.node) + "/"), target)
        self.script = script
        (self.node / "opt/telcoin").mkdir(parents=True)
        (self.node / "etc/telcoin/alloy").mkdir(parents=True)
        (self.node / "etc/systemd/system").mkdir(parents=True)
        (self.node / "usr/local/bin").mkdir(parents=True)
        self.wrapper = self.node / "opt/telcoin/start-telcoin.sh"
        self.wrapper.write_text("exec docker run --name telcoin img node --http --http.addr 127.0.0.1 --ws\n")
        (self.node / "etc/telcoin/alloy/telcoin-alloy.env").write_text(
            "TN_CHAIN=%s\nTN_NODE=bench-validator-01\n" % self.label)
        self.nodebin = self.root / "node-bin"
        for name in ("docker", "curl", "systemctl", "date", "sleep"):
            install(self.nodebin, name, "stub-node-%s.sh" % name)
        if not host_sed_is_gnu():
            install(self.nodebin, "sed", "stub-sed-gnu-inplace.sh")
        self.state = self.root / "node-state"
        self.state.mkdir()

    def run_remote(self, boot_log):
        env = {"PATH": str(self.nodebin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "STUB_LOG": str(self.log),
               "STUB_BOOT_LOG": str(FIX / boot_log), "STUB_STATE": str(self.state),
               "STUB_CHAIN_HEX": self.chain_hex, "POSTCFG_WAIT_SECS": "10"}
        p = subprocess.run(["bash", "-s"], input=self.script, env=env, cwd=str(self.node),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
                           universal_newlines=True, errors="replace")
        lines = [l for l in p.stdout.splitlines() if l.startswith("POSTCFG_")]
        return p, lines

    def test_good_boot_reports_build_delays_and_forks(self):
        p, lines = self.run_remote("node-log-boot-good.txt")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(len(lines), 1, p.stdout)
        self.assertTrue(lines[0].startswith("POSTCFG_OK bench-validator-01 chain=%s " % self.chain_hex), lines)
        self.assertIn(" ip=192.0.2.7 ", lines[0])
        self.assertTrue(lines[0].endswith(" sha=%s mhd=500 nhd=250 mbd=250 vt=? forks=subsecond-from-genesis"
                                          % FULL_SHA), lines[0])
        self.assertIn("--http.addr 0.0.0.0", self.wrapper.read_text())
        self.assertEqual((self.node / "usr/local/bin/bench-node-sampler.sh").read_bytes(),
                         (BENCH / "node-sampler.sh").read_bytes())
        self.assertTrue((self.node / "etc/systemd/system/bench-node-sampler.service").is_file())
        calls = self.calls()
        self.assertIn("systemctl restart telcoin", calls)
        self.assertIn("systemctl enable --now bench-node-sampler.service", calls)

    def test_baseline_boot_reports_vote_timeout_and_pre_subsecond(self):
        p, lines = self.run_remote("node-log-boot-baseline.txt")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertTrue(lines[-1].endswith(" sha=%s mhd=3000 nhd=1000 mbd=1000 vt=1500 forks=pre-subsecond"
                                           % FULL_SHA), lines)

    def test_no_starting_line_fails(self):
        p, lines = self.run_remote("node-log-boot-nostart.txt")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertEqual(lines, ["POSTCFG_FAIL no 'telcoin-network <version> (<sha>) starting' line "
                                 "in docker logs since the restart"], p.stdout)
        self.assertFalse((self.node / "usr/local/bin/bench-node-sampler.sh").exists())


if __name__ == "__main__":
    unittest.main()
