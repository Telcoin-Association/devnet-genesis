"""The node image probe (bench-lib.sh) and the deploy steps that touch v2 nodes, fully offline.

Every bash run happens in a temporary copy of the scripts (the deploy script's results root is
fixed to <its dir>/results, so nothing here ever runs the scripts in place), with stub `docker`,
`gcloud` and `curl` first on PATH (fixtures/node-image/stub-*.sh). The "image" the stub docker
serves is a directory: the -V / --version / --help texts and the fake binary the probe copies out
and greps (fixtures/node-image/{out-*,help-*,fake-node-bin}.txt), varied per test. The stub curl
fails the run if anything tries the network.

The remote scripts (step 7's pre-start config, step 8's observability session, step 9's verify
script) run on sandbox v2 nodes: directories laid out like a node's root from the shared C8
fixture (fixtures/v2-node), with stub systemctl/docker/date/git/stat/curl/sleep, a stub
lib/common.sh standing in for the v2 lib's launch-flag functions, and the scripts' absolute node
paths relocated (fixtures/node-image/v2-node-run.sh). The deploy steps reach them through a fake
gcloud that runs each `sudo bash -s` session on that node's sandbox
(fixtures/node-image/stub-gcloud-v2-node.sh); on a BSD-sed host (macOS) a shim gives the scripts
the GNU `sed -i` they target.
"""
import base64
import functools
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
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
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/obs-lib.sh", "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
        "benchmark/node-image-contract.txt")
# What the bench-obs functions (obs-lib.sh) read from the tree: the bundle. The VM's startup script and
# the Grafana dashboards live in the `common` submodule, which a CI checkout lacks: every test points
# BENCH_OBS_STARTUP_SCRIPT and BENCH_OBS_DASHBOARDS_DIR at fixtures instead (BashCase.env).
OBS_BUNDLE = "benchmark/obs"
# Contract stand-ins appended to the sandbox copy of bench-lib.sh, each defined only when the real
# function is absent (the owning unit has not landed it yet); production code never carries them.
LIB_SHIMS = r'''
# --- test shims (test_node_image.py), only for functions bench-lib.sh does not define ---
# bench_is_stockout <text> (U-H2): benchmark-blast.sh's is_stockout, whitespace folded.
declare -F bench_is_stockout >/dev/null || bench_is_stockout() {
    case "$(printf '%s' "$1" | tr -s ' \t\n' '   ')" in
        *ZONE_RESOURCE_POOL_EXHAUSTED*|*stockout*|*"does not have enough resources"*) return 0 ;;
    esac
    return 1
}
'''
PARAMS_YAML = "max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n"


def pin_params(text, **values):
    """<text> with each key's `key: value` line set to the given value. A key that is not exactly
    one such line (absent, or a secs/nanos block the tool refuses) fails loudly here."""
    for key, value in values.items():
        text, n = re.subn(r"^%s: .*$" % re.escape(key), "%s: %s" % (key, value), text, flags=re.M)
        if n != 1:
            raise AssertionError("consensus-parameters.yaml: want one '%s: <value>' line, found %d" % (key, n))
    return text


def staged_yaml():
    """The parameters.yaml step 7 stages on a node (RemoteScriptTests): the committed fleet file,
    every key, comment and line the rewrite must keep, with its timing values pinned to PARAMS_YAML's
    (and the good boot log's), so the expectations are the test's own and do not move with the fleet
    file. Read per test, not at import: check_mutations.py's copy of this suite has no fleet file."""
    return pin_params((BENCH / "consensus-parameters.yaml").read_text(), max_header_delay="500ms",
                      min_header_delay="250ms", max_batch_delay="250ms")


def make_tree(root):
    """Copy the scripts into <root> (same layout as the repo); returns <root>/benchmark."""
    for rel in TREE:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    shutil.copytree(str(REPO / OBS_BUNDLE), str(root / OBS_BUNDLE))
    with open(str(root / "benchmark/bench-lib.sh"), "a") as f:
        f.write(LIB_SHIMS)
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


@functools.lru_cache(maxsize=None)
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
               "TN_IAP_RETRIES": "0",   # the lib's transport retry is off: ssh attempts are counted exactly
               "BENCH_PARAMETERS_FILE": str(self.params), "STUB_LOG": str(self.log),
               "STUB_IMAGE_DIR": str(self.image), "STUB_DIGEST": DIGEST,
               # bench-obs's startup script and dashboards without the `common` submodule
               "BENCH_OBS_STARTUP_SCRIPT": str(FIX / "obs-startup-stub.sh"),
               "BENCH_OBS_DASHBOARDS_DIR": str(FIX / "obs-dashboards")}
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


# --------------------------------------------------------------------------- v2 nodes (steps 7, 8, 9)
# A sandbox v2 node is a directory laid out like a node's root: the C8 fixture (fixtures/v2-node:
# .node-meta, node.env, tn-start-docker, telcoin.service) with DATA_DIR moved under it, the Alloy
# env, <DATA_DIR>/parameters.yaml, the scripts' checkout with a stub lib/common.sh
# (fixtures/node-image/v2-lib-common.sh), the node stubs in bin/, and state/ files the stubs answer
# from. fixtures/node-image/v2-node-run.sh runs a remote script there, its node paths relocated
# (RELOCATED, kept in step with the script by test_relocation_list_matches_the_runner).
V2 = Path(__file__).resolve().parent / "fixtures" / "v2-node"
RELOCATED = ("/etc/telcoin/", "/etc/systemd/system/", "/etc/logrotate.d/", "/usr/local/libexec/telcoin/",
             "/usr/local/bin/bench-node-sampler.sh", "/opt/telcoin-node-scripts", "/var/lib/telcoin-alloy/",
             "/tmp/bench-obs")
NODE_STUBS = (("systemctl", "stub-v2-node-systemctl.sh"), ("docker", "stub-v2-node-docker.sh"),
              ("date", "stub-v2-node-date.sh"), ("git", "stub-v2-node-git.sh"), ("stat", "stub-v2-node-stat.sh"),
              ("curl", "stub-node-curl.sh"), ("sleep", "stub-node-sleep.sh"), ("logrotate", "stub-v2-node-logrotate.sh"),
              ("python3", "stub-node-python3.sh"))
STARTED = "2026-01-01T00:00:00.000000000Z"     # the container's StartedAt (stub date -d: 1767225600)
CHAIN_HEX = "0x7e1e"                           # the bench chain 32286, as the nodes' RPC answers it
GUARD_RPC = "http://127.0.0.1:9"               # BENCH_GUARD_PUBLIC_RPC (contract C5a)
# benchmark/config.sh's default node log filter (the bench-4 design's D2 string).
FILTER = ("info,primary=debug,engine=debug,subscriber=debug,worker::network=debug,network::reqres=debug,"
          "primary::cert_validator=info,primary::cert_manager=info,primary::cert_fetcher=info")
STEP9_PARAMS = PARAMS_YAML + "header_num_of_batches_threshold: 5\n"
FORK_LINE = "fork schedule: seed_signature, multi_workers, prevrandao, leader_seeded_ordering, and subsecond_timestamp active from genesis"
PRE_SUBSECOND_LINE = "fork schedule: seed_signature, multi_workers, prevrandao, and leader_seeded_ordering active from genesis"


def scripts_ref():
    """TN_NODE_SCRIPTS_REF as config.sh pins it (the checkout every node must be at)."""
    return re.search(r'^export TN_NODE_SCRIPTS_REF="([0-9a-f]{40})"', (REPO / "config.sh").read_text(), re.M).group(1)


def v2_node_line():
    """(docker run prefix up to the image, node command) of the C8 start script's one live line."""
    line = [l for l in (V2 / "usr/local/libexec/telcoin/tn-start-docker").read_text().splitlines()
            if l.startswith("exec /usr/bin/docker run ")]
    assert len(line) == 1, "fixtures/v2-node tn-start-docker: want one docker run line"
    prefix, _, args = line[0].partition(" telcoin node ")
    return prefix + " ", "telcoin node " + args


def v2_cmdline(http="0.0.0.0", ws="0.0.0.0", metrics="127.0.0.1:9101", log_filter=FILTER, max_files="20"):
    """The node command of a node step 7's pre-start config edited (C3), as `docker inspect -f
    '{{.Path}} {{join .Args " "}}' telcoin` shows it: the C8 command, its RPC/WS addresses set in
    place, --metrics and the log flags appended (the order tn_launch_flag_set leaves them in). A
    None value leaves that flag out (http/ws: the C8 loopback value stays)."""
    cmd = v2_node_line()[1]
    if http is not None:
        cmd = cmd.replace(" --http.addr 127.0.0.1", " --http.addr " + http)
    if ws is not None:
        cmd = cmd.replace(" --ws.addr 127.0.0.1", " --ws.addr " + ws)
    for flag, value in (("--metrics", metrics), ("--log.stdout.filter", log_filter),
                        ("--log.file.filter", log_filter), ("--log.file.max-files", max_files)):
        if value is not None:
            cmd += " %s %s" % (flag, value)
    return cmd


def boot_log(sha=FULL_SHA, mhd=500, nhd=250, mbd=250, vt=None, fork=FORK_LINE):
    """`docker logs telcoin --since <start>` of a node that booted the given build and delays: the
    good boot fixture's lines, values swapped in (vote timeout only when given)."""
    text = (FIX / "node-log-boot-good.txt").read_text().replace(FULL_SHA, sha).replace(FORK_LINE, fork)
    for name, value in (("Max header delay", mhd), ("Min header delay", nhd), ("Max batch delay", mbd)):
        text, n = re.subn(r"%s set to \d+ ms" % name, "%s set to %d ms" % (name, value), text)
        assert n == 1, name
    if vt is not None:
        lines = text.splitlines(True)
        i = next(i for i, l in enumerate(lines) if "Max batch delay set to" in l)
        lines.insert(i + 1, re.sub(r"Max batch delay set to \d+ ms", "Vote timeout set to %d ms" % vt, lines[i]))
        text = "".join(lines)
    return text


class V2Node:
    """One sandbox v2 node (see above). unit: the telcoin unit's state; start: the node command
    on tn-start-docker (None: the C8 start script as staged, unedited)."""

    def __init__(self, root, inst, unit="active", params=STEP9_PARAMS, start=None, cmdline=None, log=None,
                 label="bench"):
        self.root, self.inst = Path(root), inst
        r = str(self.root)
        shutil.rmtree(str(self.root / "state"), ignore_errors=True)   # a node rebuilt in place starts afresh
        for rel in ("etc/telcoin/alloy", "etc/systemd/system", "etc/logrotate.d", "usr/local/bin", "usr/local/libexec/telcoin",
                    "var/lib/telcoin", "var/lib/telcoin-alloy", "var/log/telcoin", "opt/telcoin-node-scripts/lib", "tmp",
                    "state", "bin"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        for rel in ("etc/telcoin/.node-meta", "etc/telcoin/node.env", "etc/systemd/system/telcoin.service"):
            (self.root / rel).write_text((V2 / rel).read_text().replace("=/var/lib/telcoin\n", "=%s/var/lib/telcoin\n" % r)
                                         .replace("/var/log/telcoin", r + "/var/log/telcoin"))
        # The unit's append file (telcoin.service StandardOutput=append:, under NODE_LOG_DIR): every run since finalize.
        self.unit_log = self.root / "var/log/telcoin/telcoin.log"
        self.start_script = self.root / "usr/local/libexec/telcoin/tn-start-docker"
        text = (V2 / "usr/local/libexec/telcoin/tn-start-docker").read_text()
        if start is not None:
            prefix, staged = v2_node_line()
            text = text.replace(prefix + staged, prefix + start)
        self.start_script.write_text(text.replace(" -v /var/lib/telcoin:", " -v %s/var/lib/telcoin:" % r))
        self.start_script.chmod(0o755)
        self.datadir = self.root / "var/lib/telcoin"
        self.yaml = self.datadir / "parameters.yaml"
        self.yaml.write_text(params)
        self.alloy = self.root / "etc/telcoin/alloy/telcoin-alloy.env"
        self.alloy.write_text("TN_CHAIN=%s\nTN_NODE=%s\nOBS_METRICS_PUSH_URL=http://127.0.0.1:9/bench-hold\n"
                              % (label, inst if label == "bench" else "node"))
        (self.root / "var/lib/telcoin-alloy/wal").write_text("devnet-labelled samples\n")
        shutil.copyfile(FIX / "v2-lib-common.sh", self.root / "opt/telcoin-node-scripts/lib/common.sh")
        for name, fixture in NODE_STUBS:
            install(self.root / "bin", name, fixture)
        if not host_sed_is_gnu():
            install(self.root / "bin", "sed", "stub-sed-gnu-inplace.sh")
        self.put("unit", unit)
        self.put("started", STARTED)
        self.put("git-head", scripts_ref())
        self.put("cmdline", cmdline if cmdline is not None else v2_cmdline())
        self.put("boot.log", log if log is not None else boot_log())
        (self.root / "calls").write_text("")

    def put(self, name, text):
        (self.root / "state" / name).write_text(text + ("" if text.endswith("\n") else "\n"))

    def calls(self):
        return (self.root / "calls").read_text().splitlines()

    def node_command(self):
        """The node command on its start script now (from `telcoin node`)."""
        live = [l for l in self.start_script.read_text().splitlines() if l.startswith("exec /usr/bin/docker run ")]
        return "telcoin node " + live[0].split(" telcoin node ", 1)[1]

    def run(self, script, stdin=None, name=None, **env):
        """<script> on this node: `bash -s` (stdin = the script), or with <name> `bash -c <script>
        <name>` with <stdin> on its stdin (step 8's session). Returns (process, its RESULT lines)."""
        base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "STUB_CHAIN_HEX": CHAIN_HEX}
        base.update(env)
        cmd = ["bash", str(FIX / "v2-node-run.sh"), str(self.root)]
        if name is not None:
            f = self.root / "session.sh"
            f.write_text(script)
            cmd += [str(f), name]
        p = subprocess.run(cmd, input=script if name is None else stdin, env=base, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=60, universal_newlines=True, errors="replace")
        return p, [l for l in p.stdout.splitlines() if re.match(r"^(PRECFG|POSTCFG|OBSCFG)_(OK|FAIL) ", l)]


def relocation_problems(script):
    """Absolute node paths <script> writes (a `>` redirection) that v2-node-run.sh would not move
    into the sandbox (/dev/null aside)."""
    return [t for t in re.findall(r"(?<![0-9&-])>\s*(/[^\s;|&)\"']*)", script)
            if t != "/dev/null" and not t.startswith(RELOCATED)]


class RemoteScriptTests(BashCase):
    """Step 7's pre-start config (--print-prestart, bench_prestart_script) on a stopped sandbox
    v2 node: the start script edits through the lib's tn_launch_flag_set, the per-node overrides
    into parameters.yaml, the readback, and the C5b PRECFG_OK line."""

    INST = "bench-validator-01"

    def setUp(self):
        super().setUp()
        self.node = V2Node(self.root / "node", self.INST, unit="inactive", params=staged_yaml())
        self.staged = self.yaml_text()

    def yaml_text(self):
        return self.node.yaml.read_text()

    def script_for(self, **env):
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-prestart", self.INST],
                           env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                           universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])   # printing the script contacts nothing
        self.assertEqual(relocation_problems(p.stdout), [])
        return p.stdout

    def lib_calls(self, op):
        return [l for l in self.node.calls() if l.startswith("lib %s " % op)]

    def precfg_ok(self, filt="-", maxfiles="-", params=0, logrotate="20G", paramsbak="written"):
        return ("PRECFG_OK %s datadir=%s/var/lib/telcoin http=0.0.0.0 ws=0.0.0.0 metrics=127.0.0.1:9101 filter=%s "
                "maxfiles=%s params=%d owner=root:root mode=755 unit=inactive logrotate=%s paramsbak=%s"
                % (self.INST, self.node.root, filt, maxfiles, params, logrotate, paramsbak))

    def test_default_filter_sets_six_flags_and_reports_precfg_ok(self):
        p, lines = self.node.run(self.script_for())
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(lines, [self.precfg_ok(FILTER, "20")], p.stdout)
        self.assertEqual(self.lib_calls("set"), [
            "lib set --http.addr 0.0.0.0 rc=0", "lib set --ws.addr 0.0.0.0 rc=0", "lib set --metrics 127.0.0.1:9101 rc=0",
            "lib set --log.stdout.filter %s rc=0" % FILTER, "lib set --log.file.filter %s rc=0" % FILTER,
            "lib set --log.file.max-files 20 rc=0"])
        self.assertEqual([l.split(" rc=")[1] for l in self.lib_calls("get")], ["0"] * 6)
        # Every lib call sourced lib/common.sh with the guard's black hole exported, never a real RPC.
        sources = self.lib_calls("source")
        self.assertGreaterEqual(len(sources), 13)   # 6 setters, 6 readbacks, the logrotate write (+ its reads)
        self.assertEqual(set(sources), {"lib source DEVNET_RPC_URL=" + GUARD_RPC})
        # 7a: parameters.yaml kept as .bak before any override; 7b: the bench logrotate file, through the lib
        # (no maxsize, rotating at BENCH_LOGROTATE_SIZE), parsed by logrotate -d.
        self.assertEqual((self.node.datadir / "parameters.yaml.bak").read_text(), self.staged)
        lr = self.node.root / "etc/logrotate.d/telcoin"
        self.assertEqual(self.lib_calls("write"), ["lib write %s 0644 rc=0" % lr])
        text = lr.read_text()
        self.assertIn("%s/var/log/telcoin/*.log" % self.node.root, text)
        self.assertRegex(text, r"(?m)^\s*size 20G\s*$")
        self.assertNotIn("maxsize", text)
        self.assertIn("logrotate -d %s" % lr, self.node.calls())
        # The start script is what step 9 will read off the running container; nothing else moved.
        self.assertEqual(self.node.node_command(), v2_cmdline())
        self.assertEqual(self.yaml_text(), self.staged)
        self.assertIn("git -C %s/opt/telcoin-node-scripts rev-parse HEAD" % self.node.root, self.node.calls())
        unit_calls = [l for l in self.node.calls() if l.startswith("systemctl ")]
        self.assertEqual(unit_calls, ["systemctl is-active telcoin"] * 2)   # read twice, never started

    def test_empty_filter_leaves_the_log_flags_alone(self):
        p, lines = self.node.run(self.script_for(BENCH_NODE_LOG_FILTER="", BENCH_LOGROTATE_SIZE=""))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(lines, [self.precfg_ok(logrotate="-")], p.stdout)
        self.assertFalse((self.node.root / "etc/logrotate.d/telcoin").exists())
        self.assertEqual(self.lib_calls("write"), [])
        self.assertEqual([l.split()[2] for l in self.lib_calls("set")], ["--http.addr", "--ws.addr", "--metrics"])
        self.assertEqual(self.node.node_command(), v2_cmdline(log_filter=None, max_files=None))

    def test_rerun_converges_with_rc_1_setters(self):
        script = self.script_for(BENCH_NODE_PARAM_OVERRIDES="0:min_header_delay=50ms,max_header_delay=250ms,vote_timeout=2s")
        p, lines = self.node.run(script)
        self.assertEqual(lines, [self.precfg_ok(FILTER, "20", 3)], p.stdout)
        first = (self.node.start_script.read_text(), self.yaml_text())
        want = [l.replace("max_header_delay: 500ms", "max_header_delay: 250ms  # bench-override")
                 .replace("min_header_delay: 250ms", "min_header_delay: 50ms  # bench-override")
                for l in self.staged.splitlines()] + ["vote_timeout: 2s  # bench-override"]
        self.assertEqual(self.yaml_text().splitlines(), want)
        (self.node.root / "calls").write_text("")
        p, lines = self.node.run(script)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(lines, [self.precfg_ok(FILTER, "20", 3, paramsbak="kept")], p.stdout)
        self.assertEqual((self.node.datadir / "parameters.yaml.bak").read_text(), self.staged)   # the first copy stays
        self.assertEqual([l.rsplit(" ", 1)[1] for l in self.lib_calls("set")], ["rc=1"] * 6)
        self.assertEqual((self.node.start_script.read_text(), self.yaml_text()), first)

    def test_db_sync_mode_is_set_read_back_and_reported(self):
        # bench 5 D-IV H2: BENCH_NODE_DB_SYNC_MODE puts --db.sync-mode <v> on the node command once, through the
        # lib like the other launch flags, reads it back, and names it on the PRECFG_OK line; a re-run converges.
        script = self.script_for(BENCH_NODE_DB_SYNC_MODE="safe-no-sync")
        for n, (rc, bak) in enumerate((("0", "written"), ("1", "kept"))):
            with self.subTest(run=n):
                (self.node.root / "calls").write_text("")
                p, lines = self.node.run(script)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertEqual(lines, [self.precfg_ok(FILTER, "20", paramsbak=bak) + " dbsync=safe-no-sync"], p.stdout)
                self.assertEqual(self.lib_calls("set")[-1], "lib set --db.sync-mode safe-no-sync rc=%s" % rc)
                self.assertEqual(self.lib_calls("get")[-1], "lib get --db.sync-mode rc=0")
                self.assertEqual(self.node.node_command(), v2_cmdline() + " --db.sync-mode safe-no-sync")
                self.assertEqual(self.node.node_command().count("--db.sync-mode"), 1)

    def test_setter_rc_3_fails_naming_the_flag(self):
        p, lines = self.node.run(self.script_for(), STUB_LIB_FORCE="set:--ws.addr=3")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(lines, ["PRECFG_FAIL %s tn_launch_flag_set --ws.addr 0.0.0.0: rc 3" % self.INST], p.stdout)
        self.assertEqual([l.split()[2] for l in self.lib_calls("set")], ["--http.addr", "--ws.addr"])

    def test_running_unit_or_wrong_checkout_refused_before_any_edit(self):
        cases = (("unit", "active", "unit telcoin is 'active', want inactive"),
                 ("git-head", "0" * 40, "is at '%s', want %s" % ("0" * 40, scripts_ref())))
        for name, value, phrase in cases:
            with self.subTest(state=name):
                node = V2Node(self.root / ("node-" + name), self.INST, unit="inactive", params=staged_yaml())
                node.put(name, value)
                p, lines = node.run(self.script_for())
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertEqual(len(lines), 1, p.stdout)
                self.assertTrue(lines[0].startswith("PRECFG_FAIL %s " % self.INST), lines)
                self.assertIn(phrase, lines[0])
                self.assertFalse([l for l in node.calls() if l.startswith("lib ")])
                self.assertEqual(node.node_command(), v2_node_line()[1])


class PreStartScriptTests(BashCase):
    """--print-prestart <instance>: the review aid prints exactly step 7's pre-start script."""

    # The C3 steps, in the order the script must take them.
    ORDER = ('h="$(git -C "$SD" rev-parse HEAD', 'u="$(systemctl is-active telcoin', 'D="$(meta DATA_DIR)"',
             'grep -qF " -v $D:/home/nonroot " "$S"', 'MP="$(meta METRICS_PORT)"', "setf --http.addr 0.0.0.0",
             "setf --ws.addr 0.0.0.0", 'setf --metrics "127.0.0.1:$MP"', 'setf --log.stdout.filter "$F"',
             'setf --log.file.filter "$F"', 'setf --log.file.max-files "$MF"', 'P="$D/parameters.yaml"',
             "getf --http.addr 0.0.0.0", "getf --ws.addr 0.0.0.0", 'getf --metrics "127.0.0.1:$MP"',
             'getf --log.stdout.filter "$F"', 'getf --log.file.filter "$F"', 'getf --log.file.max-files "$MF"',
             "o=\"$(stat -c '%U:%G %a' \"$S\"", 'bash -n "$S"', 'u="$(systemctl is-active telcoin', 'echo "PRECFG_OK ')

    def prestart(self, inst, **env):
        return subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-prestart", inst],
                              env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                              universal_newlines=True)

    def test_script_parses_takes_the_c3_steps_in_order_and_contacts_nothing(self):
        p = self.prestart("bench-validator-01")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])
        syntax = subprocess.run(["bash", "-n"], input=p.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True)
        self.assertEqual(syntax.returncode, 0, syntax.stdout)
        lines = p.stdout.splitlines()
        self.assertEqual(lines[2:4], ["SD=/opt/telcoin-node-scripts",
                                      'tnlib(){ ( export DEVNET_RPC_URL=%s; . "$SD/lib/common.sh"; "$@" ); }' % GUARD_RPC])
        self.assertIn("REF='%s'; NOV=0" % scripts_ref(), lines)
        at, pos = [], 0
        for step in self.ORDER:
            pos = next(i for i in range(pos, len(lines)) if step in lines[i] and not lines[i].startswith("#"))
            at.append(pos)
            pos += 1
        self.assertEqual(at, sorted(at))
        # The contract line (bench-4 design D3, PRECFG_OK … unit=$u logrotate=<size|-> paramsbak=<written|kept|->).
        self.assertEqual(lines[-1], 'echo "PRECFG_OK bench-validator-01 datadir=$D http=0.0.0.0 ws=0.0.0.0 '
                         'metrics=127.0.0.1:$MP filter=${F:--} maxfiles=${MF:--} params=$NOV owner=root:root mode=755 '
                         'unit=$u logrotate=${LRS:--} paramsbak=${BAK:--}"')
        self.assertFalse([l for l in lines if re.search(r"systemctl (start|restart|stop)|docker ", l)])

    def test_script_differs_per_instance_by_its_overrides(self):
        env = {"BENCH_NODE_PARAM_OVERRIDES": "0:max_header_delay=250ms 3:vote_timeout=2s,min_header_delay=50ms"}
        one, two, four = (self.prestart(i, **env).stdout for i in ("bench-validator-01", "bench-validator-02",
                                                                      "bench-validator-04"))

        def setp(script):
            return [l for l in script.splitlines() if re.match(r"^setp [a-z_]+ \S+$", l)]
        self.assertEqual(setp(one), ["setp max_header_delay 250ms"])
        self.assertEqual(setp(two), [])
        self.assertEqual(setp(four), ["setp vote_timeout 2s", "setp min_header_delay 50ms"])
        self.assertIn("; NOV=1\n", one)
        self.assertIn("; NOV=0\n", two)
        self.assertIn("; NOV=2\n", four)
        self.assertIn('echo "PRECFG_FAIL bench-validator-04 $*"', four)
        self.assertEqual(two.replace("bench-validator-02", "bench-validator-01"),
                         one.replace("; NOV=1\n", "; NOV=0\n").replace("setp max_header_delay 250ms\n", ""))

    def test_unknown_instance_refused(self):
        p = self.prestart("bench-validator-99")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertIn("bench-validator-99", p.stderr)
        self.assertEqual(self.calls(), [])

    def test_relocation_list_matches_the_runner(self):
        runner = (FIX / "v2-node-run.sh").read_text()
        for path in RELOCATED:
            self.assertIn('"s#%s#${R}%s#g"' % (path, path), runner)


# <tree>/benchmark <fn> <args...>: one bench-lib.sh function with its arguments. They are saved before the
# source: a sourced file may reuse the positional parameters (`set --`), and sourcing shares them.
LIB_CALL = r'''
set -euo pipefail
lib="$1"; shift
argv=("$@")
source "$lib/bench-lib.sh"
"${argv[@]}"
'''


class PreStartKnobTests(BashCase):
    """Bench 5 (D-IV H2): with every knob unset the pre-start script is bench 4's byte for byte (the fixture was
    rendered by the unmodified bench-lib.sh: bench-validator-01, BENCH_LOGROTATE_SIZE empty so the logrotate text of
    pull-lib.sh stays out of it, the default log filter pinned, TN_NODE_SCRIPTS_REF as a placeholder);
    BENCH_NODE_DB_SYNC_MODE adds --db.sync-mode in the launch-flag block and nothing else."""

    INST = "bench-validator-01"
    PINNED = {"BENCH_LOGROTATE_SIZE": "", "BENCH_NODE_LOG_FILTER": FILTER}

    def prestart(self, **env):
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-prestart", self.INST],
                           env=self.env(**dict(self.PINNED, **env)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=60, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])
        return p.stdout

    def bench4(self):
        return (FIX / "prestart-knobs-unset.txt").read_text().replace("@TN_NODE_SCRIPTS_REF@", scripts_ref())

    def test_knobs_unset_is_byte_identical_to_bench_4(self):
        for value in (None, ""):
            with self.subTest(BENCH_NODE_DB_SYNC_MODE=value):
                script = self.prestart(BENCH_NODE_DB_SYNC_MODE=value)
                self.assertEqual(script, self.bench4())
                self.assertNotIn("db.sync-mode", script)
                self.assertNotIn("FSYNC_PROBE", script)   # the probe is its own script, sent ahead of this one

    def test_db_sync_mode_adds_the_flag_once_in_the_launch_flag_block(self):
        for mode in ("durable", "safe-no-sync"):
            with self.subTest(mode=mode):
                lines = self.prestart(BENCH_NODE_DB_SYNC_MODE=mode).splitlines()
                flagged = [l for l in lines if "--db.sync-mode" in l]
                self.assertEqual(flagged, ["setf --db.sync-mode %s" % mode, "getf --db.sync-mode %s" % mode])
                # Exactly bench 4's script plus the setter after the log flags, its readback after theirs, and the
                # value on the PRECFG_OK line.
                want = self.bench4().splitlines()
                want.insert(want.index('setf --log.file.max-files "$MF"') + 1, "setf --db.sync-mode %s" % mode)
                want.insert(want.index('getf --log.file.max-files "$MF"') + 1, "getf --db.sync-mode %s" % mode)
                self.assertTrue(want[-1].endswith(' paramsbak=${BAK:--}"'), want[-1])
                want[-1] = want[-1][:-1] + ' dbsync=%s"' % mode
                self.assertEqual(lines, want)

    def test_an_unknown_db_sync_mode_prints_nothing(self):
        # config.sh refuses it first; the lib refuses it too when the variable changes after config.sh loaded.
        p = self.bash('i="$2"; source "$1/bench-lib.sh"; BENCH_NODE_DB_SYNC_MODE=fast; bench_prestart_script "$i"',
                      self.bench, self.INST)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("BENCH_NODE_DB_SYNC_MODE='fast' is not empty, durable or safe-no-sync", p.stdout)
        self.assertNotIn("set -euo pipefail", p.stdout)


FSYNC_LINE = re.compile(r"^FSYNC_PROBE (\S+) p50_us=(0|[1-9]\d*) p95_us=(0|[1-9]\d*)$")


class FsyncProbeTests(BashCase):
    """Bench 5 (D-IV H2): the datadir fsync probe (bench_fsync_probe_script) on a sandbox v2 node, the record step 7
    keeps of it (bench_fsync_probe_record) and the fleet summary (bench_fsync_probe_summary)."""

    INST = "bench-validator-01"

    def lib(self, *argv, **env):
        return self.bash(LIB_CALL, self.bench, *argv, **env)

    def probe_script(self, inst=None):
        p = self.lib("bench_fsync_probe_script", inst or self.INST)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        return p.stdout

    def node(self, name="node"):
        return V2Node(self.root / name, self.INST, unit="inactive", params=staged_yaml())

    def test_probe_times_fsync_in_the_datadir_and_leaves_nothing(self):
        script = self.probe_script()
        self.assertEqual(subprocess.run(["bash", "-n"], input=script, universal_newlines=True).returncode, 0)
        self.assertEqual(relocation_problems(script), [])
        self.assertIn('D="$(meta DATA_DIR)"', script)   # the pre-start script's own getter, never a fixed path
        node = self.node()
        before = sorted(os.listdir(str(node.datadir)))
        p, _ = node.run(script)
        self.assertEqual(p.returncode, 0, p.stdout)
        got = [l for l in p.stdout.splitlines() if l.startswith("FSYNC_PROBE ")]
        self.assertEqual(len(got), 1, p.stdout)
        m = FSYNC_LINE.match(got[0])
        self.assertTrue(m and m.group(1) == self.INST, got)
        self.assertLessEqual(int(m.group(2)), int(m.group(3)))
        self.assertEqual(sorted(os.listdir(str(node.datadir))), before)   # the temp file is gone
        self.assertIn("python3 - %s %s" % (node.datadir, self.INST), node.calls())

    def test_probe_failure_never_stops_the_session(self):
        # The probe's python3 dies (rc 3, no line): one probe_failed line, and the pre-start script that follows in
        # the same session still runs to its PRECFG_OK.
        pre = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-prestart", self.INST],
                             env=self.env(), stdout=subprocess.PIPE, universal_newlines=True, timeout=60).stdout
        node = self.node()
        node.put("fsync-probe", "Traceback (most recent call last):")
        node.put("fsync-probe-rc", "3")
        p, lines = node.run(self.probe_script() + pre)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("FSYNC_PROBE %s probe_failed python3 exited 3" % self.INST, p.stdout.splitlines())
        self.assertEqual(len(lines), 1, p.stdout)
        self.assertTrue(lines[0].startswith("PRECFG_OK %s " % self.INST), lines)

    def test_probe_reports_an_unusable_datadir(self):
        cases = [("DATA_DIR=%s/nowhere", "DATA_DIR %s/nowhere is not a directory"),
                 ("DATA_DIR=relative/dir", "DATA_DIR 'relative/dir' in /etc/telcoin/.node-meta is not an absolute path")]
        for meta, want in cases:
            with self.subTest(meta=meta):
                node = self.node("node-%d" % len(meta))
                f = node.root / "etc/telcoin/.node-meta"
                r = str(node.root)
                f.write_text(re.sub(r"(?m)^DATA_DIR=.*$", (meta % r) if "%s" in meta else meta, f.read_text()))
                p, _ = node.run(self.probe_script())
                self.assertEqual(p.returncode, 0, p.stdout)
                want_line = "FSYNC_PROBE %s probe_failed %s" % (self.INST, (want % r) if "%s" in want else want)
                self.assertEqual([l for l in p.stdout.splitlines() if l.startswith("FSYNC_PROBE")],
                                 [want_line.replace("/etc/telcoin/", r + "/etc/telcoin/")])
                self.assertFalse([c for c in node.calls() if c.startswith("python3 ")])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes into a 0555 directory")
    def test_probe_reports_an_io_error_from_python(self):
        node = self.node()
        node.datadir.chmod(0o555)
        try:
            p, _ = node.run(self.probe_script())
        finally:
            node.datadir.chmod(0o755)
        self.assertEqual(p.returncode, 0, p.stdout)
        got = [l for l in p.stdout.splitlines() if l.startswith("FSYNC_PROBE")]
        self.assertEqual(len(got), 1, p.stdout)
        self.assertTrue(got[0].startswith("FSYNC_PROBE %s probe_failed PermissionError: " % self.INST), got)

    def test_record_from_a_session_output(self):
        text = (FIX / "fsync-probe-sessions.txt").read_text()
        want = {
            "bench-validator-01": {"p50_us": 1180, "p95_us": 2410},   # not bench-validator-010's line
            "bench-validator-02": {"probe_failed": True, "reason": "OSError: [Errno 28] No space left on device"},
            "bench-validator-03": {"probe_failed": True, "reason": "unparsed: p50_us=0912 p95_us=1000"},
            "bench-validator-04": {"probe_failed": True, "reason": "unparsed: p50_us=1500"},
            "bench-validator-05": {"probe_failed": True, "reason": "no FSYNC_PROBE line in the session output"},
            "bench-validator-06": {"p50_us": 1300, "p95_us": 2600},   # the last line wins
            "bench-validator-07": {"probe_failed": True, "reason": "no FSYNC_PROBE line in the session output"},
            "bench-validator-08": {"p50_us": 0, "p95_us": 7},
            "bench-validator-09": {"probe_failed": True, "reason": "(no reason given)"},
        }
        for inst, record in want.items():
            with self.subTest(inst=inst):
                p = subprocess.run(["bash", "-c", LIB_CALL, "benchmark-deploy.sh", str(self.bench),
                                    "bench_fsync_probe_record", inst], input=text, env=self.env(),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertEqual(json.loads(p.stdout), record)
                self.assertEqual(p.stdout.count("\n"), 1)

    def summary(self, records, insts=None):
        m = self.root / "manifest.json"
        m.write_text(json.dumps({"node_startup": {i: ({"fsync_probe": r} if r is not None else {"params_bak": "kept"})
                                                  for i, r in records.items()}}))
        p = self.lib("bench_fsync_probe_summary", m, *(insts or NODES))
        self.assertEqual(p.returncode, 0, p.stdout)   # never fatal, slow nodes or not
        return p.stdout

    def test_summary_names_the_node_over_twenty_percent(self):
        fail = {"probe_failed": True, "reason": "x"}
        records = {"bench-validator-01": {"p50_us": 1000, "p95_us": 1}, "bench-validator-02": {"p50_us": 1100, "p95_us": 1},
                   "bench-validator-03": {"p50_us": 1100, "p95_us": 1},
                   "bench-validator-04": {"p50_us": 1320, "p95_us": 1},   # exactly 20 % over: not slow
                   "bench-validator-05": {"p50_us": 1321, "p95_us": 1},   # more than 20 % over
                   "bench-validator-06": fail, "bench-validator-07": None}  # 07: no probe record, left out
        self.assertEqual(self.summary(records),
                         "⚠ FSYNC_PROBE_SUMMARY median_us=1100 slow=[bench-validator-05] probe_failed=[bench-validator-06]\n")

    def test_summary_without_a_slow_node_has_no_warning(self):
        records = {"bench-validator-0%d" % (i + 1): {"p50_us": v, "p95_us": 2 * v} for i, v in enumerate((1000, 1300, 1100, 1200))}
        # An even count: the mean of the middle two, 1150; 1380 would be 20 % over it.
        self.assertEqual(self.summary(records), "FSYNC_PROBE_SUMMARY median_us=1150 slow=[] probe_failed=[]\n")

    def test_summary_median_leaves_failed_probes_out(self):
        fail = {"probe_failed": True, "reason": "no python3 on the node"}
        records = {"bench-validator-01": fail, "bench-validator-02": {"p50_us": 1000, "p95_us": 1},
                   "bench-validator-03": {"p50_us": 1250, "p95_us": 1}, "bench-validator-04": fail,
                   "bench-validator-05": {"p50_us": 1100, "p95_us": 1}}
        # Counted as anything the failures would move the median to 1000, which would make 1250 slow.
        self.assertEqual(self.summary(records),
                         "⚠ FSYNC_PROBE_SUMMARY median_us=1100 slow=[] probe_failed=[bench-validator-01 bench-validator-04]\n")
        self.assertEqual(self.summary({"bench-validator-01": fail}),
                         "⚠ FSYNC_PROBE_SUMMARY median_us=- slow=[] probe_failed=[bench-validator-01]\n")

    def test_summary_of_an_unreadable_manifest_is_a_warning_not_a_failure(self):
        p = self.lib("bench_fsync_probe_summary", self.root / "absent.json", *NODES)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout, "⚠ FSYNC_PROBE_SUMMARY median_us=- slow=[] probe_failed=[] (cannot read %s)\n"
                         % (self.root / "absent.json"))


class FleetCase(BashCase):
    """A deploy run against eleven sandbox v2 nodes: gcloud is fixtures/node-image/
    stub-gcloud-v2-node.sh, which runs every `sudo bash -s` session on the node's sandbox."""

    RUN = "rtest-fleet"
    NODE_UNIT = "active"

    def setUp(self):
        super().setUp()
        install(self.bin, "gcloud", "stub-gcloud-v2-node.sh")
        install(self.bin, "v2-node-run.sh", "v2-node-run.sh")
        install(self.bin, "stub-gcloud.sh", "stub-gcloud.sh")   # the bench-obs VM's calls (steps 2, 8)
        self.params.write_text(STEP9_PARAMS)
        self.run_dir = self.bench / "results" / self.RUN
        self.run_dir.mkdir(parents=True)
        self.manifest = self.run_dir / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema": "tn-bench-manifest/v1", "run_id": self.RUN, "docker_image": PINNED, "node_image_ref": REF,
            "node_image_pinned": PINNED, "node_git_sha": FULL_SHA, "node_fork_schedule": "subsecond-from-genesis",
            "consensus_parameters": {
                "file": self.params.name, "sha256": hashlib.sha256(self.params.read_bytes()).hexdigest(),
                "max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250},
            "timestamps": {}, "phases": [], "chaos": [], "instances": [], "notes": []}, indent=2) + "\n")
        self.spool = self.root / "remote-stdin"
        self.spool.mkdir()
        self.nodes = {inst: V2Node(self.root / "nodes" / inst, inst, unit=self.NODE_UNIT, **self.node_args(inst))
                      for inst in NODES}

    def node_args(self, inst):
        """V2Node keywords for <inst>: a node step 7 configured (pre-start edits on its start script)."""
        return {"start": v2_cmdline()}

    def edit_manifest(self, **values):
        m = json.loads(self.manifest.read_text())
        m.update(values)
        self.manifest.write_text(json.dumps(m, indent=2) + "\n")

    def deploy_argv_env(self, step, env):
        env.setdefault("BENCH_NODE_JOBS", "1")   # the serial loop; JobsTests run the nodes side by side
        return (["bash", str(self.bench / "benchmark-deploy.sh"), "--run", self.RUN, "--yes", "--only", str(step)],
                self.env(BENCH_RUN_ID=None, STUB_NODES=str(self.root / "nodes"), STUB_SPOOL=str(self.spool),
                         STUB_CHAIN_HEX=CHAIN_HEX, POSTCFG_WAIT_SECS="10", **env))

    def deploy(self, step, cwd=None, **env):
        argv, env = self.deploy_argv_env(step, env)
        return subprocess.run(argv, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
                              universal_newlines=True, errors="replace")

    def ssh_targets(self):
        return [c.split()[3] for c in self.calls() if c.startswith("gcloud compute ssh ")]

    def m(self):
        return json.loads(self.manifest.read_text())

    def deploy_logs(self):
        return sorted((self.run_dir / "logs").glob("deploy-*.log"))

    def status(self):
        """results/<run>/last-deploy.status as a dict (key=value lines)."""
        return dict(l.split("=", 1) for l in (self.run_dir / "last-deploy.status").read_text().splitlines())

    def test_result_line_status_file_and_manifest_on_failure(self):
        # D12: an applied deploy's last line on its own stdout is BENCH_DEPLOY_RESULT, written after
        # the log copy drained; the same outcome is in last-deploy.status and manifest deploy_result /
        # deploy_runs[]. The step that failed and the first ❌ line of the log are named.
        if type(self) is not FleetCase:
            self.skipTest("runs once, on FleetCase")
        self.nodes["bench-validator-01"].put("boot.log", boot_log(sha=BAD_SHA))
        p = self.deploy(9)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        die = [l for l in p.stdout.splitlines() if l.startswith("❌ ")]
        self.assertTrue(die and "bench-validator-01: boot sha = %s" % BAD_SHA in die[0], p.stdout)
        logs = self.deploy_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(p.stdout.rstrip("\n").splitlines()[-1],
                         "BENCH_DEPLOY_RESULT rc=1 last_step=9 first_error=%s log=%s" % (die[0], logs[0]))
        self.assertEqual(p.stdout.count("BENCH_DEPLOY_RESULT"), 1)
        self.assertNotIn("BENCH_DEPLOY_RESULT", logs[0].read_text())   # the operator's stream only
        st = self.status()
        for key in ("started", "ended"):
            self.assertRegex(st.pop(key), ISO_RE)
        self.assertEqual(st, {"rc": "1", "last_step": "9", "first_error": die[0], "scope": "step 9", "log": str(logs[0])})
        m = self.m()
        r = m["deploy_result"]
        self.assertTrue(ISO_RE.match(r.pop("started")) and ISO_RE.match(r.pop("ended")), r)
        self.assertEqual(r, {"rc": 1, "last_step": 9, "first_error": die[0], "scope": "step 9",
                             "log": "logs/" + logs[0].name})
        self.assertEqual(len(m["deploy_runs"]), 1)
        self.assertEqual(m["deploy_runs"][0]["first_error"], die[0])
        # D15: the log copy carries the UTC time each line was read; the terminal gets the lines as printed.
        logged = logs[0].read_text().splitlines()
        self.assertTrue(logged and all(re.match(r"^\d\d:\d\d:\d\dZ ", l) for l in logged), logged[:3])
        self.assertEqual([l[10:] for l in logged], p.stdout.splitlines()[:-1])


class StatusTests(FleetCase):
    """results/<run>/last-deploy.status belongs to the newest applied invocation from its first moment
    (rc=- while it runs), so a watcher never reads an earlier invocation's outcome as this one's."""

    STALE = "rc=0\nlast_step=12\nfirst_error=-\nstarted=2026-01-01T00:00:00Z\nended=2026-01-01T01:00:00Z\nscope=steps 0..12\nlog=x\n"

    def setUp(self):
        super().setUp()
        (self.run_dir / "last-deploy.status").write_text(self.STALE)
        self.t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))

    def test_an_exit_before_the_deploy_log_starts_replaces_the_old_status(self):
        p = self.deploy(9, BENCH_NODE_JOBS="0")   # config.sh refuses the knob before anything runs
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("❌ benchmark/config.sh: BENCH_NODE_JOBS='0'", p.stdout)
        st = self.status()
        self.assertGreaterEqual(st.pop("started"), self.t0)
        self.assertRegex(st.pop("ended"), ISO_RE)
        self.assertEqual(st, {"rc": "1", "last_step": "starting", "first_error": "-", "scope": "step 9", "log": "-"})

    def test_a_failure_at_step_0_records_rc_1(self):
        p = self.deploy(0)
        self.assertEqual(p.returncode, 1, p.stdout)
        st = self.status()
        self.assertEqual((st["rc"], st["last_step"]), ("1", "0"), p.stdout)
        self.assertGreaterEqual(st["started"], self.t0)

    def test_a_killed_deploy_leaves_rc_dash_with_its_start_and_step(self):
        argv, env = self.deploy_argv_env(9, {"STUB_SSH_HANG": "60"})
        proc = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            deadline = time.time() + 60
            while time.time() < deadline and self.status().get("last_step") != "9":
                time.sleep(0.2)
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        st = self.status()
        self.assertEqual((st["rc"], st["last_step"], st["ended"]), ("-", "9", "-"))
        self.assertGreaterEqual(st["started"], self.t0)
        self.assertTrue(st["log"].endswith(".log") and "/logs/deploy-" in st["log"], st)


class NoteTests(BashCase):
    """`--run <id> --note <text>`: one manifest note, nothing else run or contacted."""

    def note(self, *args, **env):
        return subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh")] + list(args), env=self.env(**env),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, universal_newlines=True)

    def test_note_appends_to_the_manifest_and_exits(self):
        run = self.bench / "results" / "rtest-note"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({"schema": "tn-bench-manifest/v1", "notes": ["first"]}))
        p = self.note("--run", "rtest-note", "--note", "v05 restarted by hand at 00:12Z", BENCH_RUN_ID=None)
        self.assertEqual(p.returncode, 0, p.stdout)
        notes = json.loads((run / "manifest.json").read_text())["notes"]
        self.assertEqual(notes[0], "first")
        self.assertRegex(notes[1], r"^v05 restarted by hand at 00:12Z \(operator note, \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\)$")
        self.assertEqual(len(notes), 2)
        self.assertEqual(self.calls(), [])
        self.assertEqual(sorted(f.name for f in run.iterdir()), ["manifest.json"])   # no log, no status file
        for args, phrase in ((("--note", "x"), "--note needs --run <id>"),
                             (("--run", "rtest-none", "--note", "x"), "run rtest-none has no manifest"),
                             (("--run", "rtest-note", "--note", ""), "--note needs a non-empty text")):
            with self.subTest(args=args):
                p = self.note(*args)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(phrase, p.stdout)
        self.assertEqual(len(json.loads((run / "manifest.json").read_text())["notes"]), 2)


class Step8Tests(FleetCase):
    """`benchmark-deploy.sh --yes --only 8`: bench-obs up first (obs-lib.sh's bench_obs_ensure against the stub
    gcloud: create, serial marker, bring-up, two supervised forwards), then every validator CvvActive, then one
    session per node: a throwaway token
    on stdin, setup-observability.sh, bench-obs's /-/ready from the node, the Alloy relabel to
    http://<bench-obs internal IP>:9090/api/v1/write. No secret is read and obs-devnet is never named."""

    OBS_IP = "192.0.2.50"     # the stub's bench-obs internal IP (stub-gcloud.sh STUB_OBSVM_IP)

    def node_args(self, inst):
        # setup-observability.sh's own relabel (TN_CHAIN=devnet, the black hole), as step 8 finds Alloy mid-session
        return {"start": v2_cmdline(), "label": "devnet"}

    def setUp(self):
        super().setUp()
        install(self.bin, "curl", "stub-curl-bench-obs.sh")   # the forwards, for the real bench_obs_tunnel_up
        for node in self.nodes.values():
            obs = node.root / "opt/telcoin-node-scripts/setup-observability.sh"
            shutil.copyfile(FIX / "stub-v2-setup-observability.sh", obs)
            obs.chmod(0o755)

    def tearDown(self):
        # The real bench_obs_tunnel_up leaves supervised forwards (setsid; the stub ssh sleeps): end them.
        for pidf in self.run_dir.glob("tunnel*.pid"):
            try:
                os.killpg(int(pidf.read_text().strip()), signal.SIGKILL)
            except (ValueError, OSError):
                pass
        super().tearDown()

    def deploy8(self, **env):
        return self.deploy(8, STUB_OBS_EVENTS=str(FIX / "obs-events-ok.jsonl"), STUB_OBSVM_IP=self.OBS_IP,
                           STUB_TUNNEL_SECS="30", BENCH_FLEET_READY_SETTLE_SECS="0", **env)

    def obscfg_targets(self):
        return [c.split()[3] for c in self.calls() if c.startswith("gcloud compute ssh ") and c.endswith(" bench-obscfg")]

    def test_bench_obs_first_then_every_node_ships_to_it(self):
        p = self.deploy8()
        self.assertEqual(p.returncode, 0, p.stdout)
        out = p.stdout
        self.assertIn(">>> Step 8: per-node observability, metrics only → bench-obs, labelled network=bench", out)
        ready = re.search(r"(?m)^\s*OBS_READY inst=bench-obs ip=192\.0\.2\.50 ", out)
        self.assertIsNotNone(ready, out)
        self.assertIn("    metrics -> http://192.0.2.50:9090/api/v1/write\n", out)
        self.assertLess(ready.start(), out.index("fleet ready (step8)"))
        self.assertLess(out.index("fleet ready (step8)"), out.index("OBSCFG_OK bench-validator-01 "))
        self.assertEqual(self.obscfg_targets(), NODES)
        # The token is openssl's, not a secret: no Secret Manager call, nothing of obs-devnet's.
        calls = self.calls()
        self.assertFalse([c for c in calls if " secrets " in c], calls)
        self.assertNotIn("obs-devnet", "\n".join(calls))
        tokens = set()
        for inst, node in self.nodes.items():
            with self.subTest(inst=inst):
                self.assertIn("OBSCFG_OK %s restarted=none " % inst, out)
                self.assertEqual(node.alloy.read_text(), "TN_CHAIN=bench\nTN_NODE=%s\nOBS_METRICS_PUSH_URL=http://%s:9090/api/v1/write\n"
                                 % (inst, self.OBS_IP))
                nc = node.calls()
                ready_call = "curl -sf --max-time 5 http://%s:9090/-/ready" % self.OBS_IP
                self.assertLess(nc.index(ready_call), nc.index("systemctl stop telcoin-alloy.service"))
                tok = (node.root / "state" / "obs-stdin").read_text()
                self.assertRegex(tok, r"^[0-9a-f]{32}\n$")
                tokens.add(tok.strip())
        self.assertEqual(len(tokens), 1)    # one throwaway token for the step
        tok = tokens.pop()
        self.assertNotIn(tok, out)
        self.assertNotIn(tok, "\n".join(calls))
        m = self.m()
        self.assertEqual(m["obs"]["internal_ip"], self.OBS_IP)
        self.assertTrue(m["fleet_ready"]["ok"], m["fleet_ready"])

    def test_unreachable_bench_obs_stops_at_the_first_node(self):
        p = self.deploy8(STUB_OBS_READY="0")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("OBSCFG_FAIL bench-validator-01 bench-obs unreachable", p.stdout)
        self.assertIn("observability failed on bench-validator-01", p.stdout)
        self.assertEqual(self.obscfg_targets(), ["bench-validator-01"])
        first = self.nodes["bench-validator-01"]
        self.assertIn("TN_CHAIN=devnet\n", first.alloy.read_text())
        self.assertNotIn("systemctl stop telcoin-alloy.service", first.calls())

    def test_a_failed_bring_up_still_ends_with_the_result_line(self):
        # obs-lib dies inside the bring-up: the deploy dies again in its own shell with the resume, and the
        # EXIT trap still has fd 5 for BENCH_DEPLOY_RESULT (the last line), naming obs-lib's own cause.
        p = self.deploy8(STUB_OBSVM_STACK="fail")
        self.assertEqual(p.returncode, 1, p.stdout)
        last = p.stdout.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.startswith("BENCH_DEPLOY_RESULT rc=1 last_step=8 first_error=❌ "), last)
        self.assertIn("❌ bench-obs is not up (above) — re-run with --only 8, then your segment "
                      "(--from 10 --to 12 or --from 13 --to 15)", p.stdout)
        self.assertLess(p.stdout.index("OBS_STACK_FAIL"), p.stdout.index("❌ bench-obs is not up"))
        self.assertEqual(self.obscfg_targets(), [])
        self.assertEqual((self.status()["rc"], self.status()["last_step"]), ("1", "8"))

    def test_a_missing_startup_script_fails_the_gate_before_any_gcloud_call(self):
        p = self.deploy8(BENCH_OBS_STARTUP_SCRIPT=str(self.root / "no-such-startup-obs.sh"))
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("    ✗ bench-obs startup script %s is missing or unreadable" % (self.root / "no-such-startup-obs.sh"),
                      p.stdout)
        self.assertIn("❌ prerequisites missing — nothing was started", p.stdout)
        self.assertIn("    ✓ bench-obs bring-up session (bundle ", p.stdout)   # the other two checks still ran
        self.assertEqual([c for c in self.calls() if c.startswith("gcloud ")], [])

    def test_an_existing_bench_obs_of_this_run_is_kept(self):
        # --from 8 after step 2: the run's own VM is kept, not created again.
        p = self.deploy8(STUB_OBSVM_EXISTS="1")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertRegex(p.stdout, r"(?m)^\s*OBS_CREATE inst=bench-obs zone=us-west2-a ip=192\.0\.2\.50 id=\S+ existing=1$")
        self.assertFalse([c for c in self.calls() if c.startswith("gcloud compute instances create ")], self.calls())
        self.assertEqual(self.obscfg_targets(), NODES)


class Step9Tests(FleetCase):
    """`benchmark-deploy.sh --yes --only 9`: verify only. One session per node runs step 9's script
    on the node's sandbox; nothing restarts, nothing is edited."""

    def deploy9(self, **env):
        return self.deploy(9, **env)

    def node_line(self, out, inst):
        return [l.strip() for l in out.splitlines() if l.strip().startswith("POSTCFG_OK %s " % inst)]

    def test_every_node_boots_the_manifest_build(self):
        p = self.deploy9()
        self.assertEqual(p.returncode, 0, p.stdout)
        m = self.m()
        self.assertEqual(sorted(m["node_startup"]), sorted(NODES))
        for inst in NODES:
            self.assertEqual(m["node_startup"][inst], {
                "sha": FULL_SHA, "mhd": 500, "nhd": 250, "mbd": 250, "vt": None, "forks": "subsecond-from-genesis",
                "params": {"max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250,
                           "header_num_of_batches_threshold": 5, "vote_timeout_ms": None},
                "log_filter": FILTER, "log_max_files": 20}, inst)
            line = self.node_line(p.stdout, inst)
            self.assertEqual(len(line), 1, p.stdout)
            self.assertTrue(line[0].endswith(" filter=%s maxfiles=20 back=-" % FILTER), line)
            self.assertIn(" chain=%s block=0x" % CHAIN_HEX, line[0])
            self.assertIn(" ip=192.0.2.7 progress=consensus log (1 subdag committed/quorum reached lines", line[0])
        self.assertIn("step_9_done", m["timestamps"])
        # One session per node, in fleet order, and gcloud did nothing else.
        self.assertEqual(self.ssh_targets(), NODES)
        self.assertFalse([c for c in self.calls() if not c.startswith("gcloud compute ssh ")])
        for inst, node in self.nodes.items():
            calls = node.calls()
            # Verify only: no unit or container action, the start script and the yaml untouched.
            self.assertFalse([c for c in calls if re.match(r"systemctl (start|stop|restart|reset-failed) telcoin$", c)
                              or re.match(r"docker (run|stop|restart|rm|start) ", c)], inst)
            self.assertEqual(node.node_command(), v2_cmdline(), inst)
            self.assertEqual(node.yaml.read_text(), STEP9_PARAMS, inst)
            self.assertEqual([c for c in calls if c.startswith("systemctl show ")], ["systemctl show -p NRestarts --value telcoin"])
            self.assertEqual(calls.count("docker inspect -f {{.State.StartedAt}} telcoin"), 2, inst)
            logs = [c for c in calls if c.startswith("docker logs ")]
            self.assertTrue(logs, inst)
            self.assertEqual([c for c in logs if not re.match(r"docker logs telcoin --since \S+$", c)], [], inst)
            self.assertIn("docker logs telcoin --since " + STARTED, logs)
            # No coordinated_start in the manifest: progress counts from the container's StartedAt.
            self.assertIn("date -d %s +%%s" % STARTED, calls)
            self.assertEqual((node.root / "usr/local/bin/bench-node-sampler.sh").read_bytes(),
                             (BENCH / "node-sampler.sh").read_bytes())
            self.assertTrue((node.root / "etc/systemd/system/bench-node-sampler.service").is_file())
            self.assertIn("systemctl enable --now bench-node-sampler.service", calls)
        script = (self.spool / "bench-validator-01.sh").read_text()
        self.assertEqual(relocation_problems(script), [])
        self.assertNotIn("tn_launch_flag_set", script)
        self.assertNotIn("setp ", script)

    def test_wrong_sha_on_first_node_stops_the_fleet(self):
        self.nodes["bench-validator-01"].put("boot.log", boot_log(sha=BAD_SHA))
        p = self.deploy9()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-01: boot sha = %s, expected %s" % (BAD_SHA, FULL_SHA), p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01"])
        m = self.m()
        self.assertEqual([i for i, v in m["node_startup"].items() if "sha" in v], ["bench-validator-01"])
        self.assertEqual(m["node_startup"]["bench-validator-01"]["sha"], BAD_SHA)
        self.assertNotIn("step_9_done", m["timestamps"])

    def test_short_manifest_sha_matches_by_prefix_and_delay_mismatch_stops(self):
        self.edit_manifest(node_git_sha=FULL_SHA[:9])
        self.nodes["bench-validator-01"].put("boot.log", boot_log(mhd=3000))
        p = self.deploy9()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-01: max_header_delay = 3000 ms, expected 500 ms", p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01"])
        self.assertNotIn("boot sha =", p.stdout)

    def test_fork_schedule_mismatch_stops(self):
        self.nodes["bench-validator-01"].put("boot.log", boot_log(fork=PRE_SUBSECOND_LINE))
        p = self.deploy9()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-01: fork schedule = pre-subsecond, expected subsecond-from-genesis "
                      "(manifest node_fork_schedule)", p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01"])

    OVERRIDE = "2:min_header_delay=50ms,max_header_delay=250ms"
    OVERRIDDEN_YAML = STEP9_PARAMS.replace("max_header_delay: 500ms", "max_header_delay: 250ms  # bench-override") \
        .replace("min_header_delay: 250ms", "min_header_delay: 50ms  # bench-override")

    def test_override_on_one_node_only(self):
        three = self.nodes["bench-validator-03"]
        three.yaml.write_text(self.OVERRIDDEN_YAML)
        three.put("boot.log", boot_log(mhd=250, nhd=50))
        self.edit_manifest(coordinated_start={"due": 1767225660, "nodes": 11, "started": 11, "skipped_running": 0,
                                              "spread_secs": 2, "max_late_secs": 1, "ts": "2026-01-01T00:01:00Z"})
        p = self.deploy9(BENCH_NODE_PARAM_OVERRIDES=self.OVERRIDE)
        self.assertEqual(p.returncode, 0, p.stdout)
        m = self.m()
        for inst in NODES:
            got = m["node_startup"][inst]
            want = (250, 50) if inst == "bench-validator-03" else (500, 250)
            self.assertEqual((got["mhd"], got["nhd"]), want, inst)
            self.assertEqual((got["params"]["max_header_delay_ms"], got["params"]["min_header_delay_ms"]), want, inst)
            # Progress counts from the coordinated start's due time, not from a date -d of StartedAt.
            self.assertFalse([c for c in self.nodes[inst].calls() if c.startswith("date -d")], inst)
            self.assertIn("\nT0='1767225660'\n", (self.spool / (inst + ".sh")).read_text())
        self.assertEqual(three.yaml.read_text(), self.OVERRIDDEN_YAML)   # read, never rewritten
        self.assertIn("bench-validator-03: running args (http/ws 0.0.0.0, --metrics, log filter), parameters.yaml "
                      "(min_header_delay=50ms,max_header_delay=250ms)", p.stdout)

    def test_wrong_value_on_one_node_stops_the_fleet(self):
        self.nodes["bench-validator-03"].yaml.write_text(self.OVERRIDDEN_YAML)
        p = self.deploy9(BENCH_NODE_PARAM_OVERRIDES=self.OVERRIDE)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-03: max_header_delay = 500 ms, expected 250 ms (manifest "
                      "consensus_parameters + BENCH_NODE_PARAM_OVERRIDES)", p.stdout)
        self.assertEqual(self.ssh_targets(), NODES[:3])

    CONSENSUS_ONLY = "".join(l + "\n" for l in (FIX / "node-log-boot-good.txt").read_text().splitlines()
                             if "subdag committed" in l)

    def test_boot_lines_rotated_out_of_docker_logs_come_from_the_unit_file(self):
        # The capped json-file log kept only consensus lines; the unit's append file holds the stage-only
        # run (other values, a vote timeout, pre-subsecond) and then this run: step 9 reads the last block.
        run1 = boot_log(sha=BAD_SHA, mhd=3000, nhd=1000, mbd=1000, vt=1500, fork=PRE_SUBSECOND_LINE)
        cases = (("telcoin.service StandardOutput=append:", None),
                 ("NODE_LOG_DIR/telcoin.log", "var/log/telcoin-alt"))
        for where, alt in cases:
            with self.subTest(source=where):
                node = V2Node(self.root / "nodes" / "bench-validator-01", "bench-validator-01", start=v2_cmdline(),
                              log=self.CONSENSUS_ONLY)
                unit_log = node.unit_log
                if alt is not None:   # no StandardOutput= line: the unit file is $NODE_LOG_DIR/telcoin.log
                    svc = node.root / "etc/systemd/system/telcoin.service"
                    svc.write_text("".join(l for l in svc.read_text().splitlines(True)
                                           if not l.startswith("StandardOutput=")))
                    meta = node.root / "etc/telcoin/.node-meta"
                    meta.write_text(meta.read_text().replace("/var/log/telcoin\n", "/%s\n" % alt))
                    (node.root / alt).mkdir(parents=True, exist_ok=True)
                    unit_log = node.root / alt / "telcoin.log"
                unit_log.write_text(run1 + boot_log())
                self.log.write_text("")
                p = self.deploy9()
                self.assertEqual(p.returncode, 0, p.stdout)
                line = self.node_line(p.stdout, "bench-validator-01")
                self.assertEqual(len(line), 1, p.stdout)
                self.assertIn(" sha=%s mhd=500 nhd=250 mbd=250 vt=? forks=subsecond-from-genesis " % FULL_SHA, line[0])
                got = self.m()["node_startup"]["bench-validator-01"]
                self.assertEqual((got["sha"], got["mhd"], got["vt"], got["forks"]),
                                 (FULL_SHA, 500, None, "subsecond-from-genesis"))
                self.assertEqual(self.ssh_targets(), NODES)

    def test_boot_lines_from_a_rotated_unit_file_generation(self):
        # logrotate moved the boot block on: telcoin.log has no 'starting' line any more, so step 9 reads
        # telcoin.log.1, else telcoin.log.2.gz (delaycompress), from that file's last 'starting' line on.
        run1 = boot_log(sha=BAD_SHA, mhd=3000, nhd=1000, mbd=1000, vt=1500, fork=PRE_SUBSECOND_LINE)
        for gen in ("telcoin.log.1", "telcoin.log.2.gz"):
            with self.subTest(gen=gen):
                node = V2Node(self.root / "nodes" / "bench-validator-01", "bench-validator-01", start=v2_cmdline(),
                              log=self.CONSENSUS_ONLY)
                node.unit_log.write_text(self.CONSENSUS_ONLY)
                (node.unit_log.parent / "telcoin.log.1").write_text(self.CONSENSUS_ONLY)
                data = (run1 + boot_log()).encode()
                if gen.endswith(".gz"):
                    (node.unit_log.parent / gen).write_bytes(gzip.compress(data))
                else:
                    (node.unit_log.parent / gen).write_bytes(data)
                self.log.write_text("")
                p = self.deploy9()
                self.assertEqual(p.returncode, 0, p.stdout)
                line = self.node_line(p.stdout, "bench-validator-01")
                self.assertEqual(len(line), 1, p.stdout)
                self.assertIn(" sha=%s mhd=500 nhd=250 mbd=250 vt=? forks=subsecond-from-genesis " % FULL_SHA, line[0])

    def test_no_starting_line_in_docker_logs_nor_the_unit_file_fails_naming_both(self):
        node = self.nodes["bench-validator-01"]
        node.put("boot.log", self.CONSENSUS_ONLY)
        node.unit_log.write_text(self.CONSENSUS_ONLY)
        p = self.deploy9()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("POSTCFG_FAIL no 'telcoin-network <version> (<sha>) starting' line in docker logs since the "
                      "container started (%s) nor in the unit file %s" % (STARTED, node.unit_log), p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01"])

    def test_yaml_that_disagrees_with_the_boot_lines_stops(self):
        self.nodes["bench-validator-02"].yaml.write_text(STEP9_PARAMS.replace("max_batch_delay: 250ms", "max_batch_delay: 300ms"))
        p = self.deploy9()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-02: parameters.yaml has max/min header delay 500/250 ms and max batch delay "
                      "300 ms, expected 500/250/250 ms", p.stdout)
        self.assertEqual(self.ssh_targets(), NODES[:2])

    def test_empty_log_filter_leaves_the_command_line_alone(self):
        for node in self.nodes.values():
            node.put("cmdline", v2_cmdline(log_filter=None, max_files=None))
        p = self.deploy9(BENCH_NODE_LOG_FILTER="")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("--log.stdout.filter/--log.file.filter '$rf'", (self.spool / "bench-validator-01.sh").read_text())
        m = self.m()
        self.assertEqual({(v["log_filter"], v["log_max_files"]) for v in m["node_startup"].values()}, {(None, None)})

    def test_node_without_the_log_filter_stops(self):
        self.nodes["bench-validator-01"].put("cmdline", v2_cmdline(log_filter=None, max_files=None))
        p = self.deploy9()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("POSTCFG_FAIL running --log.stdout.filter/--log.file.filter '' --log.file.max-files '', "
                      "expected '%s' / 20" % FILTER, p.stdout)
        self.assertIn("post-config verification failed on bench-validator-01", p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-01"])

    def test_restart_or_missing_flags_fail_the_session(self):
        cases = (("nrestarts", "1", "POSTCFG_FAIL telcoin NRestarts=1, expected 0 (no restart after the coordinated start)"),
                 ("started-flip", "1", "POSTCFG_FAIL the telcoin container restarted while step 9 ran"),
                 ("cmdline", v2_cmdline(http=None), "POSTCFG_FAIL running --http.addr is '127.0.0.1', expected 0.0.0.0"),
                 ("cmdline", v2_cmdline(ws=None), "POSTCFG_FAIL running --ws.addr is '127.0.0.1', expected 0.0.0.0"),
                 ("cmdline", v2_cmdline(metrics=None), "POSTCFG_FAIL running --metrics is '', expected 127.0.0.1:9101"))
        for name, value, line in cases:
            with self.subTest(line=line):
                node = V2Node(self.root / "nodes" / "bench-validator-01", "bench-validator-01", start=v2_cmdline())
                node.put(name, value)
                self.log.write_text("")
                p = self.deploy9()
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn(line, p.stdout)
                self.assertNotIn("POSTCFG_OK", p.stdout)
                self.assertEqual(self.ssh_targets(), ["bench-validator-01"])
                self.assertFalse((node.root / "usr/local/bin/bench-node-sampler.sh").exists())

    def test_fleet_minimum_max_header_delay_feeds_fork_delay_check(self):
        # A pre-subsecond build at 1 s delays passes, until one node is given 500 ms.
        m = self.m()
        m["node_fork_schedule"] = "pre-subsecond"
        m["consensus_parameters"].update(max_header_delay_ms=1000, min_header_delay_ms=250, max_batch_delay_ms=250)
        self.manifest.write_text(json.dumps(m, indent=2) + "\n")
        self.params.write_text("max_header_delay: 1s\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n")
        p = self.deploy9(BENCH_NODE_PARAM_OVERRIDES="2:max_header_delay=500ms")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("max_header_delay is 500 ms (BENCH_NODE_PARAM_OVERRIDES (bench-validator-03))", p.stdout)
        self.assertEqual(self.ssh_targets(), [])

    def test_gate_refuses_parameters_a_node_would_refuse(self):
        p = self.deploy9(BENCH_NODE_PARAM_OVERRIDES="4:min_header_delay=600ms 6:max_header_delay=1s,vote_timeout=1s")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("✗ bench-validator-05: min_header_delay 600 ms > max_header_delay 500 ms", p.stdout)
        self.assertIn("✗ bench-validator-07: vote_timeout 1000 ms < max_header_delay 1000 ms + 250 ms", p.stdout)
        self.assertEqual(self.ssh_targets(), [])

    def test_print_postconfig_contacts_nothing_and_writes_only_node_paths(self):
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-postconfig", "bench-validator-01"],
                           env=self.env(BENCH_RUN_ID=self.RUN), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=60, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(relocation_problems(p.stdout), [])
        self.assertTrue(p.stdout.rstrip().endswith('vote=$(ms "$(pv vote_timeout)") filter=${rf:--} maxfiles=${rmf:--} back=-"'))


class KeygenTests(FleetCase):
    """`benchmark-deploy.sh --yes --only 5` over a stub devnet-keygen.sh (D16): the output copied to
    logs/keygen-<UTC>.log, its KEYGEN_DONE lines -> manifest keygen_timing / node_info_rpc."""

    DONE = ("KEYGEN_DONE bench-validator-01 rc=0 secs=41 reused=0 rpc_http=http://192.0.2.11:8545/ rpc_ws=ws://192.0.2.11:8546/\n"
            "  KEYGEN_DONE bench-validator-02 rc=0 secs=7 reused=1 rpc_http=http://192.0.2.12:8545/ rpc_ws=ws://192.0.2.12:8546/\r\n"
            "KEYGEN_DONE bench-validator-03 rc=1 secs=12 reused=0 rpc_http=- rpc_ws=-\n"
            "unrelated KEYGEN_DONE text in a line\n")

    def setUp(self):
        super().setUp()
        install(self.root / "tree", "devnet-keygen.sh", "stub-devnet-keygen.sh")

    def test_keygen_done_lines_are_recorded_even_when_keygen_fails(self):
        for rc in ("0", "3"):
            with self.subTest(rc=rc):
                self.edit_manifest(keygen_timing={"bench-validator-09": {"secs": 5, "reused": False}})
                p = self.deploy(5, STUB_KEYGEN_OUT=self.DONE, STUB_KEYGEN_RC=rc)
                # This run's copy (two runs within one second: keygen-<UTC>.log, then keygen-<UTC>-1.log).
                copy = re.search(r"devnet-keygen\.sh   \(copy: (\S+)\)", p.stdout)
                self.assertTrue(copy, p.stdout)
                logs = [Path(copy.group(1))]
                self.assertEqual(logs[0].parent, self.run_dir / "logs")
                self.assertIn("KEYGEN_DONE bench-validator-03 rc=1", logs[-1].read_text())
                m = self.m()
                self.assertEqual(m["keygen_timing"], {"bench-validator-09": {"secs": 5, "reused": False},
                                                      "bench-validator-01": {"secs": 41, "reused": False},
                                                      "bench-validator-02": {"secs": 7, "reused": True},
                                                      "bench-validator-03": {"secs": 12, "reused": False}})
                self.assertEqual(m["node_info_rpc"], {
                    "bench-validator-01": {"http": "http://192.0.2.11:8545/", "ws": "ws://192.0.2.11:8546/"},
                    "bench-validator-02": {"http": "http://192.0.2.12:8545/", "ws": "ws://192.0.2.12:8546/"}})
                if rc == "0":
                    self.assertEqual(p.returncode, 0, p.stdout)
                    self.assertIn("step_5_done", m["timestamps"])
                else:
                    self.assertNotEqual(p.returncode, 0, p.stdout)
                    self.assertIn("❌ devnet-keygen.sh exited 3 (%s)" % logs[-1], p.stdout)
        # The bench profile's keygen knobs reach the driver (benchmark/config.sh, only when unset).
        self.assertIn("KEYGEN_JOBS=4 KEYGEN_REUSE_EXISTING=1 KEYGEN_RPC_ADVERTISE=internal-ip KEYGEN_REPORT=1",
                      [c for c in self.calls() if c.startswith("devnet-keygen.sh")][0])

    def test_no_report_lines_change_nothing(self):
        p = self.deploy(5, STUB_KEYGEN_OUT="keyed bench-validator-01")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("keygen_timing", self.m())
        self.assertIn("no KEYGEN_DONE line in", p.stdout)


class JobsTests(FleetCase):
    """BENCH_NODE_JOBS > 1 (D8): step 9's sessions run side by side and each node's output is printed in
    fleet order; 1 is the serial loop (Step9Tests, Step7Tests)."""

    def block(self, out):
        """Step 9's lines from its header to its end, 'serially' / 'up to N at a time' made equal, and
        the block number (the stub RPC counts up per call) left out."""
        lines = out.splitlines()
        s = next(i for i, l in enumerate(lines) if l.startswith(">>> Step 9"))
        e = next(i for i, l in enumerate(lines) if l == "## step 9 done")
        return [re.sub(r" block=0x[0-9a-f]+ ", " block=<n> ", re.sub(r"(serially|up to \d+ at a time)$", "<jobs>", l))
                for l in lines[s:e]]

    def heads(self, out):
        return [l.split(":")[0].strip() for l in out.splitlines() if re.match(r"^    bench-\S+: running args ", l)]

    def test_side_by_side_output_and_records_match_the_serial_run(self):
        p1 = self.deploy(9)
        self.assertEqual(p1.returncode, 0, p1.stdout)
        self.assertIn("one IAP session per node, serially\n", p1.stdout)
        serial = (self.block(p1.stdout), self.m()["node_startup"])
        self.edit_manifest(node_startup={})
        self.log.write_text("")
        p4 = self.deploy(9, BENCH_NODE_JOBS="4")
        self.assertEqual(p4.returncode, 0, p4.stdout)
        self.assertIn("one IAP session per node, up to 4 at a time\n", p4.stdout)
        # Every node recorded (no lost manifest update), and the same lines in the same order.
        self.assertEqual((self.block(p4.stdout), self.m()["node_startup"]), serial)
        self.assertEqual(self.heads(p4.stdout), NODES)
        self.assertEqual(sorted(self.ssh_targets()), sorted(NODES))
        self.assertEqual(list(self.tmpdir.glob("bench-node-jobs.*")), [])   # the job spool is gone

    def test_a_failing_node_does_not_stop_the_others_and_is_named(self):
        self.nodes["bench-validator-03"].put("boot.log", boot_log(sha=BAD_SHA))
        p = self.deploy(9, BENCH_NODE_JOBS="4")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertEqual(sorted(self.ssh_targets()), sorted(NODES))
        self.assertEqual(self.heads(p.stdout), NODES)
        errors = [l for l in p.stdout.splitlines() if l.startswith("❌ ")]
        self.assertEqual(len(errors), 2, p.stdout)
        self.assertTrue(errors[0].startswith("❌ bench-validator-03: boot sha = %s" % BAD_SHA), errors)
        self.assertEqual(errors[1], "❌ post-config verification (nothing was restarted): failed on bench-validator-03 "
                                    "(each node's own error is in its output above)")
        self.assertEqual(sorted(self.m()["node_startup"]), sorted(NODES))
        self.assertNotIn("step_9_done", self.m()["timestamps"])
        self.assertIn("first_error=%s log=" % errors[0], p.stdout.splitlines()[-1])


# bench_node_jobs_run and node_startup_merge as extracted functions over a real manifest: each node's job
# records {"n": <index>} (rec); TEST_BREAK=spool points that node's spool at a missing directory, manifest
# turns manifest.json into garbage before the parent applies the records.
NODE_JOBS = r'''
set -euo pipefail
source "$1/bench-lib.sh"
eval "$2"
NODE_JOBS_SPOOL=""
mkdir -p "${BENCH_RESULTS_DIR}"
echo '{"schema": "tn-bench-manifest/v1", "node_startup": {"bench-validator-01": {"keep": true}}}' > "$(bench_manifest)"
rec() {
    echo "job ${INSTANCE_NAMES[$1]}"
    case "${TEST_BREAK:-}:$1" in "spool:${TEST_NODE:-}") NODE_JOBS_SPOOL=/nonexistent/spool ;; esac
    node_startup_merge "${INSTANCE_NAMES[$1]}" "{\"n\": $1}" || bench_die "${INSTANCE_NAMES[$1]}: could not record node_startup"
    case "${TEST_BREAK:-}" in manifest) echo garbage > "$(bench_manifest)" ;; esac
}
bench_node_jobs_run "${TEST_JOBS:-4}" "test step" rec 0 1 2 3 4 5 6 7 8 9 10
echo DONE
'''


class NodeJobsRunnerTests(BashCase):
    """The node records of jobs run side by side are spooled per node and applied by the parent after the
    jobs end: none is lost, and a record that cannot be written fails loudly, naming the node."""

    def run_jobs(self, **env):
        fns = shell_functions(self.bench / "benchmark-deploy.sh", "node_startup_merge", "bench_node_jobs_run")
        p = self.bash(NODE_JOBS, self.bench, fns, **env)
        m = self.bench / "results" / "rtest-node-image" / "manifest.json"
        return p, m

    def test_every_record_lands_inline_and_side_by_side(self):
        for jobs in ("1", "4", "11"):
            with self.subTest(jobs=jobs):
                p, m = self.run_jobs(TEST_JOBS=jobs)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertIn("DONE", p.stdout)
                self.assertEqual([l[4:] for l in p.stdout.splitlines() if l.startswith("job ")], NODES)
                want = {n: {"n": i} for i, n in enumerate(NODES)}
                want["bench-validator-01"]["keep"] = True
                self.assertEqual(json.loads(m.read_text())["node_startup"], want)
                self.assertEqual(list(self.tmpdir.glob("bench-node-jobs.*")), [])

    def test_a_record_that_cannot_be_spooled_fails_that_node_loudly(self):
        p, m = self.run_jobs(TEST_BREAK="spool", TEST_NODE="6")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertNotIn("DONE", p.stdout)
        self.assertIn("❌ bench-validator-07: could not record node_startup", p.stdout)
        self.assertIn("❌ test step: failed on bench-validator-07 (each node's own error", p.stdout)
        got = json.loads(m.read_text())["node_startup"]
        self.assertEqual(sorted(got), sorted(n for n in NODES if n != "bench-validator-07"))   # the others landed

    def test_a_record_the_parent_cannot_apply_is_named(self):
        p, m = self.run_jobs(TEST_BREAK="manifest")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertNotIn("DONE", p.stdout)
        self.assertIn("❌ test step: could not record node_startup in %s for: %s" % (m, " ".join(NODES)), p.stdout)


class ObsScriptTests(BashCase):
    """Step 8's session (--print-obs-script): the token on stdin only, setup-observability.sh with
    --metrics already on the node command (no restart), bench-obs's /-/ready from the node, then the
    same-session Alloy relabel to bench-obs (metrics only; obs-devnet is never a target)."""

    INST = "bench-validator-03"
    TOKEN = "tok-3f9b0709-not-a-secret"
    PLACEHOLDER = "bench-obs-internal-ip.invalid"    # no BENCH_OBS_INTERNAL_IP: the print's stand-in host

    def print_obs(self, **env):
        return subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-obs-script", self.INST],
                              env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                              universal_newlines=True)

    def setUp(self):
        super().setUp()
        p = self.print_obs()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])
        self.printed = p.stdout
        lines = p.stdout.splitlines()
        n = next(i for i, l in enumerate(lines) if not l.startswith("#"))
        self.header, self.body = lines[:n], "\n".join(lines[n:]) + "\n"
        self.zone = re.search(r"tn_iap_ssh_cmd_stdin %s (\S+) " % self.INST, self.header[1]).group(1)
        self.node = V2Node(self.root / "node", self.INST, start=v2_cmdline(), label="devnet")
        obs = self.node.root / "opt/telcoin-node-scripts/setup-observability.sh"
        shutil.copyfile(FIX / "stub-v2-setup-observability.sh", obs)
        obs.chmod(0o755)
        # The log push URL handed to setup-observability.sh (the black hole: logs stay off) and the bench-obs
        # remote-write URL the relabel writes.
        self.config = {"OBS_PUSH_URL": re.search(r"--push-url '([^']+)'", self.body).group(1),
                       "OBS_METRICS_PUSH_URL": re.search(r"grep -qx 'OBS_METRICS_PUSH_URL=([^']+)'", self.body).group(1)}

    def session(self, events="obs-events-ok.jsonl", stdin=None, **env):
        return self.node.run(self.body, stdin=self.TOKEN + "\n" if stdin is None else stdin, name="bench-obscfg",
                             STUB_OBS_EVENTS=str(FIX / events), **env)

    def ready_call(self, ip=PLACEHOLDER):
        return "curl -sf --max-time 5 http://%s:9090/-/ready" % ip

    def state(self, name):
        f = self.node.root / "state" / name
        return f.read_text() if f.exists() else None

    def test_printed_header_keeps_the_token_on_stdin(self):
        self.assertEqual(self.header[0], "# step 8 session for %s (--print-obs-script). Sent as:" % self.INST)
        sent = self.header[1]
        left, bar, remote = sent.partition(" | ")
        self.assertEqual(left, "#   printf '%s\\n' PLACEHOLDER-TOKEN")
        self.assertTrue(remote.startswith("tn_iap_ssh_cmd_stdin %s %s 'sudo bash -c " % (self.INST, self.zone)), sent)
        self.assertNotIn("PLACEHOLDER-TOKEN", remote)
        for line in self.printed.splitlines():
            if "PLACEHOLDER-TOKEN" in line:
                self.assertIn(line, self.header)
        self.assertNotIn("PLACEHOLDER-TOKEN", self.body)
        syntax = subprocess.run(["bash", "-n"], input=self.body, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True)
        self.assertEqual(syntax.returncode, 0, syntax.stdout)
        self.assertEqual(relocation_problems(self.body), [])
        # The only command the token reaches: setup-observability.sh, on its stdin.
        self.assertIn("printf '%s\\n' \"${TOKEN}\" | DEVNET_RPC_URL='" + GUARD_RPC + "' ", self.body)
        self.assertIn(" --token-stdin ", self.body)
        self.assertNotRegex(self.body, r"--token[ =]")
        # bench-obs, not obs-devnet: the remote-write URL is the VM's internal IP (here the placeholder), and
        # its /-/ready is asked from the node after setup-observability.sh and before Alloy is touched.
        self.assertEqual(self.config["OBS_METRICS_PUSH_URL"], "http://%s:9090/api/v1/write" % self.PLACEHOLDER)
        ready = 'curl -sf --max-time 5 "http://%s:9090/-/ready" >/dev/null || fail "bench-obs unreachable"' % self.PLACEHOLDER
        self.assertEqual(self.body.count(ready), 1, self.body)
        self.assertLess(self.body.index("setup-observability.sh' --json"), self.body.index(ready))
        self.assertLess(self.body.index(ready), self.body.index("systemctl stop telcoin-alloy.service"))
        self.assertIn("# bench-obs: %s (BENCH_OBS_INTERNAL_IP, else the placeholder)" % self.PLACEHOLDER, self.header)

    def test_no_obs_devnet_endpoint_reaches_the_node(self):
        # setup-observability.sh gets the black hole for its log push URL too (logs stay off), so neither
        # config.sh's OBS_PUSH_URL nor any obs-devnet host is in the session or lands in Alloy's env.
        p = self.bash('source "$1/bench-lib.sh"; printf "%s" "${OBS_PUSH_URL}"', self.bench)
        self.assertEqual(p.returncode, 0, p.stdout)
        devnet_push = p.stdout.strip()
        self.assertIn("obs." + "devnet", devnet_push)   # what config.sh carries for the live devnet
        self.assertNotIn(devnet_push, self.printed)
        self.assertNotIn("obs." + "devnet", self.printed)
        self.assertEqual(self.config["OBS_PUSH_URL"], "http://127.0.0.1:9/bench-hold")
        p, lines = self.session()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("OBS_PUSH_URL=http://127.0.0.1:9/bench-hold\n", self.state("obs-env"))
        for where, text in (("setup env", self.state("obs-env")), ("setup argv", self.state("obs-argv")),
                            ("alloy env", self.node.alloy.read_text())):
            self.assertNotIn("obs." + "devnet", text, where)

    def test_print_uses_the_bench_obs_ip_when_known(self):
        p = self.print_obs(BENCH_OBS_INTERNAL_IP="192.0.2.50")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])
        self.assertIn("OBS_METRICS_PUSH_URL=http://192.0.2.50:9090/api/v1/write#", p.stdout)
        self.assertIn('curl -sf --max-time 5 "http://192.0.2.50:9090/-/ready"', p.stdout)
        self.assertNotIn(self.PLACEHOLDER, p.stdout)

    def test_print_obs_bringup_is_obs_libs_session_and_contacts_nothing(self):
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-obs-bringup"], env=self.env(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(p.stdout.splitlines()[0], "# bench-obs: bringup")
        self.assertIn("OBS_STACK_OK bench-obs ", p.stdout)
        syntax = subprocess.run(["bash", "-n"], input=p.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True)
        self.assertEqual(syntax.returncode, 0, syntax.stdout)
        self.assertFalse((self.bench / "results").exists())
        bad = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--no-such-flag"], env=self.env(),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, universal_newlines=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("--print-obs-script INST, --print-obs-bringup, --print-postconfig INST)", bad.stdout)

    def test_remote_command_is_the_printed_script(self):
        fns = shell_functions(self.bench / "benchmark-deploy.sh", "obs_script", "obs_remote_cmd")
        script = ('set -euo pipefail\nsource "$1/bench-lib.sh"\neval "$2"\n'
                  'obs_remote_cmd "$3" "$(tn_region_from_zone "$4")"\n')
        p = self.bash(script, self.bench, fns, self.INST, self.zone)
        self.assertEqual(p.returncode, 0, p.stdout)
        m = re.fullmatch(r'sudo bash -c "\$\(printf %s ([A-Za-z0-9+/=]+) \| base64 -d\)" bench-obscfg', p.stdout.strip())
        self.assertIsNotNone(m, p.stdout)
        self.assertEqual(base64.b64decode(m.group(1)).decode(), self.body)
        self.assertEqual(self.calls(), [])

    def test_token_reaches_only_the_stdin_of_setup_observability(self):
        p, lines = self.session()
        self.assertEqual(p.returncode, 0, p.stdout)
        done = (FIX / "obs-events-ok.jsonl").read_text().splitlines()[-1]
        self.assertEqual(lines, ["OBSCFG_OK %s restarted=none %s" % (self.INST, done)], p.stdout)
        self.assertEqual(self.state("obs-stdin"), self.TOKEN + "\n")
        argv = self.state("obs-argv").splitlines()
        self.assertEqual(argv, ["--json", "--enable-metrics", "--region", self.zone.rsplit("-", 1)[0], "--token-stdin",
                                "--push-url", "http://127.0.0.1:9/bench-hold", "--metrics-push-url",
                                "http://127.0.0.1:9/bench-hold"])
        env = self.state("obs-env")
        self.assertIn("DEVNET_RPC_URL=%s\n" % GUARD_RPC, env)
        for where, text in (("argv", "\n".join(argv)), ("env", env), ("node calls", "\n".join(self.node.calls())),
                            ("session output", p.stdout)):
            self.assertNotIn(self.TOKEN, text, where)
        # No restart; bench-obs ready, then Alloy stopped, its WAL wiped, relabelled, started, all in this session.
        self.assertFalse([c for c in self.node.calls() if re.match(r"systemctl (start|stop|restart) telcoin$", c)])
        self.assertEqual([c for c in self.node.calls() if re.match(r"systemctl (start|stop) ", c) or c == self.ready_call()],
                         [self.ready_call(), "systemctl stop telcoin-alloy.service", "systemctl start telcoin-alloy.service"])
        self.assertEqual(list((self.node.root / "var/lib/telcoin-alloy").iterdir()), [])
        self.assertEqual(self.node.alloy.read_text(), "TN_CHAIN=bench\nTN_NODE=%s\nOBS_METRICS_PUSH_URL=%s\n"
                         % (self.INST, self.config["OBS_METRICS_PUSH_URL"]))

    def assertObsFails(self, phrase, p, lines, called=True):
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(len(lines), 1, p.stdout)
        self.assertTrue(lines[0].startswith("OBSCFG_FAIL %s " % self.INST), lines)
        self.assertIn(phrase, lines[0])
        self.assertEqual(self.state("obs-argv") is not None, called)
        # The Alloy env still points at the black hole: nothing labelled devnet goes anywhere.
        self.assertIn("TN_CHAIN=devnet\n", self.node.alloy.read_text())
        self.assertNotIn("TN_NODE=%s\n" % self.INST, self.node.alloy.read_text())

    def test_unreachable_obs_fails_before_alloy_restarts(self):
        # bench-obs gone, a wrong IP or no internal path: the node's /-/ready fails, and the session stops with
        # Alloy as setup-observability.sh left it (running, on the black hole, its WAL kept), never restarted.
        p, lines = self.session(STUB_OBS_READY="0")
        self.assertObsFails("bench-obs unreachable", p, lines)
        calls = self.node.calls()
        self.assertIn(self.ready_call(), calls)
        self.assertFalse([c for c in calls if c.startswith("systemctl ") and "telcoin-alloy" in c
                          and re.search(r" (stop|start|restart) ", c)], calls)
        self.assertTrue((self.node.root / "var/lib/telcoin-alloy/wal").exists())
        self.assertNotIn("OBSCFG_OK", p.stdout)

    def test_done_ok_false_fails(self):
        p, lines = self.session("obs-events-fail.jsonl")
        self.assertObsFails('done event: {"event":"done","ok":false,', p, lines)

    def test_missing_no_restart_phrase_is_contract_drift(self):
        p, lines = self.session(STUB_OBS_PHRASE="0")
        self.assertObsFails("contract drift: setup-observability.sh did not report 'Node already serves a metrics "
                            "endpoint (--metrics).'", p, lines)

    def test_changed_started_at_fails(self):
        self.node.put("started-flip", "1")
        p, lines = self.session()
        self.assertObsFails("the node restarted: container StartedAt %s -> 2026-01-01T00:09:00.000000000Z" % STARTED,
                            p, lines)

    def err_lines(self, out):
        """(OBSCFG_ERR lines, index of the OBSCFG_FAIL line) of a session's output."""
        lines = out.splitlines()
        fail = next(i for i, l in enumerate(lines) if l.startswith("OBSCFG_FAIL %s " % self.INST))
        errs = [(i, l) for i, l in enumerate(lines) if l.startswith("OBSCFG_ERR ")]
        self.assertTrue(all(i < fail for i, _ in errs), out)
        return [l for _, l in errs]

    def test_failure_reports_the_last_five_stderr_lines_ansi_stripped(self):
        p, lines = self.session("obs-events-fail.jsonl", STUB_OBS_ERR_LINES="6")
        self.assertObsFails('done event: {"event":"done","ok":false,', p, lines)
        self.assertEqual(self.err_lines(p.stdout), ["OBSCFG_ERR %s   [ERROR] alloy check %d failed" % (self.INST, n)
                                                    for n in range(2, 7)])
        self.assertNotIn("\x1b", p.stdout)

    def test_a_stderr_line_holding_the_token_is_withheld(self):
        p, lines = self.session("obs-events-fail.jsonl", STUB_OBS_ERR_LINES="1", STUB_OBS_LEAK="1")
        self.assertObsFails('done event: {"event":"done","ok":false,', p, lines)
        self.assertIn(self.TOKEN, (self.node.root / "tmp/bench-obscfg.err").read_text())   # the stub did leak it
        self.assertEqual(self.err_lines(p.stdout)[-2:], [
            "OBSCFG_ERR %s   [ERROR] alloy check 1 failed" % self.INST,
            "OBSCFG_ERR %s (line withheld: it holds the ingest token)" % self.INST])
        self.assertNotIn(self.TOKEN, p.stdout)
        self.assertNotIn(self.TOKEN, "\n".join(self.node.calls()))

    def test_no_metrics_flag_refused_before_the_call(self):
        s = self.node.start_script
        s.write_text(s.read_text().replace(" --metrics 127.0.0.1:9101", ""))
        self.assertNotIn("--metrics", self.node.node_command())
        p, lines = self.session()
        self.assertObsFails("contract drift: no --metrics 127.0.0.1:<port> on the node command", p, lines, called=False)
        self.assertNotIn("OBSCFG_ERR", p.stdout)   # nothing ran, so no stderr tail


class PlanTests(BashCase):
    """The dry run's step plan (no --yes): what steps 7-10 and 13 will do, and nothing executed."""

    def plan(self, **env):
        """(process, {step: its plan lines})."""
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh")], env=self.env(BENCH_RUN_ID="rtest-plan", **env),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, universal_newlines=True,
                           errors="replace")
        steps, cur = {}, None
        for line in p.stdout.splitlines():
            head = re.match(r"^ {2}([ 0-9]{2})  \S", line)
            if head:
                cur = int(head.group(1))
            elif not line.startswith("     "):
                cur = None
            if cur is not None:
                steps.setdefault(cur, []).append(line)
        return p, steps

    def test_plan_names_the_tunnel_of_the_mode_in_use(self):
        # D11: the step-10 line shows the transport bench_tunnel_up will use, not the old command.
        p, steps = self.plan()
        self.assertEqual(p.returncode, 0, p.stdout)
        ten = "\n".join(steps[10])
        self.assertIn("gcloud compute ssh bench-validator-01 --zone=us-west2-a --tunnel-through-iap -- -N -L "
                      "localhost:18545:127.0.0.1:8545 (BENCH_TUNNEL_MODE=ssh", ten)
        self.assertIn("gives up after 5 consecutive failures", ten)
        self.assertNotIn("start-iap-tunnel", ten)
        p, steps = self.plan(BENCH_TUNNEL_MODE="websocket")
        ten = "\n".join(steps[10])
        self.assertIn("gcloud compute start-iap-tunnel bench-validator-01 8545 --local-host-port=localhost:18545 "
                      "--zone=us-west2-a (BENCH_TUNNEL_MODE=websocket", ten)
        self.assertNotIn("--tunnel-through-iap", ten)
        # The plan also names the stockout fallbacks (step 2, step 0) and step 15's window wait.
        self.assertIn("BENCH_ZONE_FALLBACKS (3:asia-northeast1-c 4:us-east4-c,us-east4-a 7:asia-east1-a "
                      "8:asia-northeast3-b)", "\n".join(steps[2]))
        self.assertIn("zone fallbacks 3:asia-northeast1-c", "\n".join(steps[0]))
        self.assertIn("after a landed chaos kill: bench_fleet_ready", "\n".join(steps[15]))
        self.assertNotIn("BENCH_DEPLOY_RESULT", p.stdout)   # a dry run prints no result line

    def test_plan_steps_13_and_14_name_the_light_load_arm_only_when_it_is_on(self):
        p, off = self.plan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("light-load arm", p.stdout)
        self.assertEqual(len(off[13]), 2, off[13])
        self.assertEqual(len(off[14]), 1, off[14])
        p, on = self.plan(BENCH_LIGHT_LOAD="1")
        self.assertEqual(p.returncode, 0, p.stdout)
        # The knob only adds lines: every line of the plan without it is still there, in order.
        self.assertEqual(on[13][:2], off[13])
        self.assertEqual(on[14][:1], off[14])
        self.assertEqual(on[13][2:], [
            "                     light-load arm (BENCH_LIGHT_LOAD=1): one fund per blast from BENCH_RUN_INDEX=0 up, "
            "senders per blaster x window 8 x 16, 16 x 16, 600 x 4, the configured profile (600 x 16) funded last"])
        self.assertEqual(on[14][1:], [
            "                     light-load arm (BENCH_LIGHT_LOAD=1): first one light blast per senders x window "
            "(8 x 16, 16 x 16, 600 x 4; 60s warmup, 360s mixed, 60s cooldown, chaos off), then the configured profile above;",
            "                     LIGHT_LOAD_START/DONE around each light blast, manifest blasts[], one LOG_RATE line per "
            "blast; about 15-20 min per light blast"])
        p, after = self.plan(BENCH_LIGHT_LOAD="1", BENCH_LIGHT_LOAD_AFTER="1", BENCH_LIGHT_SENDERS="3",
                             BENCH_LIGHT_WINDOWS="", BENCH_WINDOW="8", BENCH_RUN_INDEX="4")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertTrue(after[13][2].endswith("BENCH_RUN_INDEX=4 up, senders per blaster x window 3 x 8, the configured "
                                              "profile (600 x 8) funded last, then one more light blast like the first"),
                        after[13])
        self.assertIn("(3 x 8; 60s warmup", after[14][1])

    def test_plan_lists_the_coordinated_start_and_the_gates(self):
        p, steps = self.plan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("DRY RUN — re-run with --yes to execute.", p.stdout)
        labels = [m.group(1) for m in (re.match(r"^ {21}(network-config|stage-only|pre-start config|start-all) ", l)
                                       for l in steps[7]) if m]
        self.assertEqual(labels, ["network-config", "stage-only", "pre-start config", "start-all"])
        seven = "\n".join(steps[7])
        self.assertIn("devnet-network-config.sh --yes", seven)
        self.assertIn("devnet-finalize.sh --stage-only", seven)
        self.assertIn("devnet-finalize.sh --start-all", seven)
        self.assertIn("--print-prestart <instance>", seven)
        self.assertIn("COORDINATED_START -> manifest.coordinated_start", seven)
        eight = "\n".join(steps[8])
        self.assertIn("--token-stdin", eight)
        self.assertIn("restarted=none", eight)
        self.assertIn("bench_fleet_ready 0", eight)
        self.assertIn("verify only", "\n".join(steps[9]))
        self.assertIn("bench_admission_gate", "\n".join(steps[10]))
        self.assertIn("bench_fleet_ready", "\n".join(steps[13]))
        # A dry run executes nothing and leaves no trace: no GCP call, no results directory.
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.bench / "results").exists())

    def test_plan_names_bench_obs_its_forwards_and_never_reads_obs_devnet(self):
        p, steps = self.plan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("  metrics  -> http://bench-obs-internal-ip.invalid:9090/api/v1/write as network=\"bench\" (bench-obs: "
                      "bench-obs, e2-standard-4 in us-west2-a, metrics only; obs-devnet is never touched)\n", p.stdout)
        self.assertIn("forwards 127.0.0.1:19090 -> bench-obs:9090 (Prometheus, http://127.0.0.1:19090/api/v1), "
                      "127.0.0.1:13000 -> bench-obs:3000 (Grafana, http://127.0.0.1:13000)", p.stdout)
        zero = "\n".join(steps[0])
        self.assertIn("e2-standard-4 must exist in every zone it is created in (us-west2-a)", zero)
        self.assertIn("us-west2: C3_CPUS 16, CPUS 6, IN_USE_ADDRESSES 4, HDB_TOTAL_GB 200, HDB_TOTAL_IOPS 40000, "
                      "HDB_TOTAL_THROUGHPUT 1600, SSD_TOTAL_GB 90", zero)
        self.assertIn("(and bench-obs in us-west2)", zero)
        self.assertIn("bench_obs_create: bench-obs", "\n".join(steps[2]))
        eight = "\n".join(steps[8])
        for phrase in ("bench_obs_ensure", "--print-obs-bringup", "127.0.0.1:19090 -> :9090", "127.0.0.1:13000 -> :3000",
                       "openssl rand -hex 16", "/-/ready", "bench-obs unreachable", "obs-devnet never touched",
                       "OBS_METRICS_PUSH_URL=http://bench-obs-internal-ip.invalid:9090/api/v1/write"):
            self.assertIn(phrase, eight)
        self.assertLess(eight.index("bench_obs_ensure"), eight.index("bench_fleet_ready 0"))
        self.assertIn("bench_obs_require", "\n".join(steps[10]))
        self.assertIn("bench_obs_require", "\n".join(steps[13]))
        self.assertIn("--prom-url http://127.0.0.1:19090/api/v1 --prom-no-auth", "\n".join(steps[15]))
        # obs-devnet is not a gate any more: no df over IAP, no disk threshold on devnet's VM.
        self.assertNotIn("obs-devnet df", p.stdout)
        self.assertNotIn("df over IAP", zero)
        self.assertNotIn("obs-devnet /mnt/obs-data", p.stdout)
        self.assertEqual(self.calls(), [])


@unittest.skipUnless(subprocess.run(["python3", "-c", "import yaml"], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL).returncode == 0,
                     "python3 has no PyYAML: deploy step 7's gate refuses to run")
class Step7Tests(FleetCase):
    """`benchmark-deploy.sh --yes --only 7`: network-config, stage-only, pre-start config on every
    stopped node (the real script, run on its sandbox), start-all; repo-root scripts stubbed."""

    NODE_UNIT = "inactive"
    START = "COORDINATED_START due=1767225660 nodes=11 started=11 skipped_running=0 spread_secs=%d max_late_secs=1"

    def setUp(self):
        super().setUp()
        for name in ("devnet-finalize.sh", "devnet-network-config.sh"):
            install(self.root / "tree", name, "stub-%s" % name)

    def node_args(self, inst):
        return {}   # staged, not configured yet: the C8 start script as devnet-finalize.sh --stage-only left it

    def deploy7(self, start=None, stage="", **env):
        return self.deploy(7, STUB_STAGE_OUT=stage, STUB_START_OUT=start or self.START % 3, **env)

    def sequence(self):
        return [c.split(" CONFIG_FILE=")[0] if not c.startswith("gcloud ") else "ssh " + c.split()[3]
                for c in self.calls() if not c.startswith("docker ")]

    def test_one_coordinated_start_after_every_node_is_configured(self):
        p = self.deploy7()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.sequence(), ["devnet-network-config.sh --yes", "devnet-finalize.sh --stage-only"]
                         + ["ssh " + n for n in NODES] + ["devnet-finalize.sh --start-all"])
        self.assertTrue(all(c.endswith("/benchmark/config.sh")
                            for c in self.calls() if c.startswith("devnet-")), self.calls())
        cs = self.m()["coordinated_start"]
        self.assertRegex(cs.pop("ts"), ISO_RE)
        self.assertEqual(cs, {"due": 1767225660, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 3,
                              "max_late_secs": 1})
        startup = self.m()["node_startup"]
        for inst, node in self.nodes.items():
            self.assertIn("PRECFG_OK %s datadir=%s/var/lib/telcoin " % (inst, node.root), p.stdout)
            self.assertEqual(node.node_command(), v2_cmdline(), inst)
            # From the PRECFG_OK line: the bench logrotate size and the parameters.yaml backup.
            self.assertEqual((startup[inst]["logrotate_size"], startup[inst]["params_bak"]), ("20G", "written"), inst)
        logs = sorted(f.name.split("-")[1] for f in (self.run_dir / "logs").glob("finalize-*.log"))
        self.assertEqual(logs, ["stage", "start"])
        self.assertIn("step_7_done", self.m()["timestamps"])

    def test_db_sync_mode_is_recorded_per_node(self):
        # The PRECFG_OK line's dbsync= field goes into node_startup[<inst>].db_sync_mode; with the knob unset
        # the line has none and the record says durable (the node's default, no flag passed).
        for mode, want in (("", "durable"), ("safe-no-sync", "safe-no-sync"), ("durable", "durable")):
            with self.subTest(mode=mode):
                m = self.m()
                for key in ("node_startup", "coordinated_start", "coordinated_start_reruns"):
                    m.pop(key, None)
                self.manifest.write_text(json.dumps(m, indent=2) + "\n")
                p = self.deploy7(BENCH_NODE_DB_SYNC_MODE=mode)
                self.assertEqual(p.returncode, 0, p.stdout)
                startup = self.m()["node_startup"]
                self.assertEqual(sorted(startup), sorted(NODES))
                for inst in NODES:
                    self.assertEqual(startup[inst]["db_sync_mode"], want, inst)
                oks = [l for l in p.stdout.splitlines() if l.startswith("      PRECFG_OK ")]
                self.assertEqual(len(oks), len(NODES), p.stdout)
                self.assertEqual(sum(" dbsync=" in l for l in oks), len(NODES) if mode else 0, oks)

    def test_spread_over_ten_seconds_stops_after_recording_it(self):
        p = self.deploy7(start=self.START % 12)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("the coordinated start spread 12 s > 10 s", p.stdout)
        self.assertEqual(self.m()["coordinated_start"]["spread_secs"], 12)
        self.assertNotIn("step_7_done", self.m()["timestamps"])

    FIRST = {"due": 1767225000, "nodes": 11, "started": 11, "skipped_running": 0, "spread_secs": 2,
             "max_late_secs": 1, "ts": "2026-01-01T00:00:00Z"}

    def test_running_unit_before_any_coordinated_start_stops_step_7(self):
        # A stage-only that failed after v2 finalize started the unit leaves it running alone; with no
        # coordinated start yet, step 7 stops before any pre-start (the node must be stopped by hand).
        self.nodes["bench-validator-04"].put("unit", "active")
        p = self.deploy7(stage="STAGED bench-validator-01 state=inactive enabled=enabled\nRUNNING bench-validator-04")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        die = [l for l in p.stdout.splitlines()
               if l.startswith("❌ ") and "stage-only found running unit(s) before any coordinated start" in l]
        self.assertEqual(len(die), 1, p.stdout)
        self.assertIn("bench-validator-04", die[0])
        self.assertIn("--from 7", die[0])
        self.assertEqual(self.ssh_targets(), [])
        self.assertNotIn("devnet-finalize.sh --start-all", self.sequence())
        self.assertNotIn("coordinated_start", self.m())

    def test_rerun_after_the_coordinated_start_keeps_it_and_records_the_late_start(self):
        # The fleet started; one start-at failed. --from 7: stage-only reports the ten RUNNING, pre-start
        # runs for the straggler only, start-all starts it late. The first start stays the record.
        self.edit_manifest(coordinated_start=self.FIRST)
        running = [n for n in NODES if n != "bench-validator-04"]
        for inst in running:
            self.nodes[inst].put("unit", "active")
        late = "COORDINATED_START due=1767226000 nodes=11 started=1 skipped_running=10 spread_secs=0 max_late_secs=0"
        p = self.deploy7(start=late, stage="\n".join("RUNNING " + n for n in running))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.ssh_targets(), ["bench-validator-04"])
        for inst in running:
            self.assertIn("%s: running — skipped" % inst, p.stdout)
            self.assertEqual(self.nodes[inst].node_command(), v2_node_line()[1], inst)
        self.assertEqual(self.nodes["bench-validator-04"].node_command(), v2_cmdline())
        self.assertIn("devnet-finalize.sh --start-all", self.sequence())
        m = self.m()
        self.assertEqual(m["coordinated_start"], self.FIRST)
        self.assertEqual([sorted(r) for r in m["coordinated_start_reruns"]], [["line", "ts"]])
        self.assertEqual(m["coordinated_start_reruns"][0]["line"], late)
        self.assertRegex(m["coordinated_start_reruns"][0]["ts"], ISO_RE)
        self.assertIn("start-all started 1 node(s) on a re-run", p.stdout)

    def test_rerun_that_starts_nobody_keeps_the_coordinated_start(self):
        self.edit_manifest(coordinated_start=self.FIRST)
        for node in self.nodes.values():
            node.put("unit", "active")
        none = "COORDINATED_START due=1767226000 nodes=11 started=0 skipped_running=11 spread_secs=0 max_late_secs=0"
        p = self.deploy7(start=none, stage="\n".join("RUNNING " + n for n in NODES))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.ssh_targets(), [])
        self.assertIn("start-all started nothing (11 already running): manifest.coordinated_start keeps the first "
                      "start", p.stdout)
        m = self.m()
        self.assertEqual(m["coordinated_start"], self.FIRST)
        self.assertEqual([r["line"] for r in m["coordinated_start_reruns"]], [none])
        self.assertIn("step_7_done", m["timestamps"])

    def test_side_by_side_pre_start_failure_configures_the_rest_and_stops_before_start_all(self):
        self.nodes["bench-validator-05"].put("git-head", "0" * 40)
        p = self.deploy7(BENCH_NODE_JOBS="4")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("(bench_prestart_script; review: --print-prestart <instance>), up to 4 at a time\n", p.stdout)
        self.assertEqual(sorted(self.ssh_targets()), sorted(NODES))
        self.assertIn("❌ pre-start config failed on bench-validator-05", p.stdout)
        self.assertIn("❌ pre-start config (no node has been started; re-run with --from 7): failed on bench-validator-05 ",
                      p.stdout)
        self.assertNotIn("devnet-finalize.sh --start-all", self.sequence())
        self.assertNotIn("coordinated_start", self.m())
        # The gate records every node's log_filter; the pre-start record is the configured nodes' only.
        self.assertEqual(sorted(i for i, v in self.m()["node_startup"].items() if "params_bak" in v),
                         sorted(n for n in NODES if n != "bench-validator-05"))
        for inst in NODES:
            if inst != "bench-validator-05":
                self.assertEqual(self.nodes[inst].node_command(), v2_cmdline(), inst)

    def test_the_result_line_stays_last_when_a_child_outlives_the_deploy(self):
        # network-config leaves a child holding the log FIFO for 13 s; the step then fails. After the
        # 10-s drain cap the copier is stopped, so nothing can be copied after BENCH_DEPLOY_RESULT.
        p = self.deploy7(STUB_NETCFG_STRAY="13", STUB_STAGE_RC="1")
        self.assertEqual(p.returncode, 1, p.stdout)
        lines = p.stdout.rstrip("\n").splitlines()
        self.assertTrue(lines[-1].startswith("BENCH_DEPLOY_RESULT rc=1 last_step=7 "), lines[-3:])
        self.assertIn("⚠ the deploy log copier was still busy 10 s after the end", lines[-2])
        self.assertNotIn("STRAY LINE", p.stdout)

    def test_side_by_side_pre_start_records_every_node_every_time(self):
        # Repeated runs of the jobs=4 path: every node's PRECFG_OK record reaches node_startup, each time.
        for n in range(5):
            with self.subTest(run=n):
                self.edit_manifest(node_startup={})
                p = self.deploy7(BENCH_NODE_JOBS="4")
                self.assertEqual(p.returncode, 0, p.stdout)
                got = {i: (v.get("logrotate_size"), v.get("params_bak")) for i, v in self.m()["node_startup"].items()}
                self.assertEqual(got, {i: ("20G", "written" if n == 0 else "kept") for i in NODES})

    def test_fsync_probes_are_recorded_and_summarised_never_fatal(self):
        # bench 5 D-IV H2: canned probe results (the node's python3 stub): one node 50 % over the median, one whose
        # probe failed. Both the serial loop and side-by-side jobs record every node and print one summary after
        # the last node's pre-start, before start-all; the step goes on to the coordinated start.
        want = {}
        for inst, node in self.nodes.items():
            if inst == "bench-validator-07":
                node.put("fsync-probe", "FSYNC_PROBE %s probe_failed OSError: [Errno 5] Input/output error" % inst)
                want[inst] = {"probe_failed": True, "reason": "OSError: [Errno 5] Input/output error"}
            else:
                p50 = 1500 if inst == "bench-validator-03" else 1000
                node.put("fsync-probe", "FSYNC_PROBE %s p50_us=%d p95_us=%d" % (inst, p50, 3 * p50))
                want[inst] = {"p50_us": p50, "p95_us": 3 * p50}
        for jobs in ("1", "4"):
            with self.subTest(jobs=jobs):
                m = self.m()
                for key in ("node_startup", "coordinated_start", "coordinated_start_reruns"):
                    m.pop(key, None)
                self.manifest.write_text(json.dumps(m, indent=2) + "\n")
                p = self.deploy7(BENCH_NODE_JOBS=jobs)
                self.assertEqual(p.returncode, 0, p.stdout)
                out = p.stdout.splitlines()
                for inst, node in self.nodes.items():
                    self.assertIn("      " + node.root.joinpath("state/fsync-probe").read_text().strip(), out)
                    self.assertEqual(self.m()["node_startup"][inst]["fsync_probe"], want[inst], inst)
                    self.assertIn("python3 - %s %s" % (node.datadir, inst), node.calls())
                summary = [i for i, l in enumerate(out) if "FSYNC_PROBE_SUMMARY" in l]
                self.assertEqual([out[i] for i in summary], ["⚠ FSYNC_PROBE_SUMMARY median_us=1000 "
                                                             "slow=[bench-validator-03] probe_failed=[bench-validator-07]"])
                last_ok = max(i for i, l in enumerate(out) if l.startswith("      PRECFG_OK "))
                start_all = next(i for i, l in enumerate(out) if l.startswith("    start-all: "))
                self.assertTrue(last_ok < summary[0] < start_all, (last_ok, summary, start_all))
                self.assertEqual(self.m()["coordinated_start"]["started"], 11)

    def test_each_session_is_the_probe_then_the_pre_start_script(self):
        # The real probe (python3 on each sandbox datadir): integer percentiles for every node, and each node's
        # session stdin is bench_fsync_probe_script followed by exactly what --print-prestart prints.
        p = self.deploy7()
        self.assertEqual(p.returncode, 0, p.stdout)
        for inst in NODES:
            probe = self.bash(LIB_CALL, self.bench, "bench_fsync_probe_script", inst)
            pre = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-prestart", inst],
                                 env=self.env(), stdout=subprocess.PIPE, universal_newlines=True, timeout=60)
            self.assertEqual((probe.returncode, pre.returncode), (0, 0), probe.stdout)
            self.assertEqual((self.spool / (inst + ".sh")).read_text(), probe.stdout + pre.stdout, inst)
            rec = self.m()["node_startup"][inst]["fsync_probe"]
            self.assertEqual(sorted(rec), ["p50_us", "p95_us"], inst)
            self.assertTrue(all(isinstance(v, int) and v >= 0 for v in rec.values()), rec)
        summary = [l for l in p.stdout.splitlines() if "FSYNC_PROBE_SUMMARY" in l]
        self.assertEqual(len(summary), 1, p.stdout)
        self.assertRegex(summary[0], r"^(⚠ )?FSYNC_PROBE_SUMMARY median_us=\d+ slow=\[[^\]]*\] probe_failed=\[\]$")

    def test_pre_start_failure_stops_before_start_all(self):
        self.nodes["bench-validator-05"].put("git-head", "0" * 40)
        p = self.deploy7()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("pre-start config failed on bench-validator-05", p.stdout)
        self.assertEqual(self.ssh_targets(), NODES[:5])
        self.assertNotIn("devnet-finalize.sh --start-all", self.sequence())
        self.assertNotIn("coordinated_start", self.m())


# --------------------------------------------------------------------------- deploy step 2 + config zones
FLEET_ZONES = ["us-west2-a", "europe-west2-b", "australia-southeast1-c", "asia-northeast1-b", "us-east4-b",
               "europe-west4-a", "asia-southeast1-b", "asia-east2-a", "asia-northeast3-a", "asia-south1-c", "us-west2-a"]
ZONES_OF = r'''
set -euo pipefail
. "$1/config.sh"
echo "ZONES ${ZONES[*]}"
echo "FALLBACKS ${BENCH_ZONE_FALLBACKS}"
'''


class ConfigTests(BashCase):
    """benchmark/config.sh: results/<run>/zones.env replaces ZONES (count and characters checked) and
    BENCH_ZONE_FALLBACKS is validated before anything can use it."""

    def zones(self, zones_env=None, **env):
        run = self.bench / "results" / "rtest-node-image"
        if zones_env is not None:
            run.mkdir(parents=True, exist_ok=True)
            (run / "zones.env").write_text(zones_env)
        return self.bash(ZONES_OF, self.bench, **env)

    def test_zones_env_is_validated(self):
        p = self.zones()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("ZONES %s\n" % " ".join(FLEET_ZONES), p.stdout)
        moved = list(FLEET_ZONES)
        moved[4] = "us-east4-c"
        p = self.zones("# step 2\nBENCH_ZONES_USED=%s\n" % " ".join(moved))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("ZONES %s\n" % " ".join(moved), p.stdout)
        for text, phrase in (("BENCH_ZONES_USED=%s\n" % " ".join(moved[:-1]), "zones.env lists 10 zone(s), INSTANCE_NAMES has 11."),
                             ("# nothing\n", "zones.env lists 0 zone(s), INSTANCE_NAMES has 11."),
                             ("BENCH_ZONES_USED=%s $(id)\n" % " ".join(moved[:-1]), "may hold only zone names")):
            with self.subTest(phrase=phrase):
                p = self.zones(text)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("❌ benchmark/config.sh: ", p.stdout)
                self.assertIn(phrase, p.stdout)
                self.assertNotIn("ZONES ", p.stdout)

    KNOBS = r'''
set -euo pipefail
. "$1/config.sh"
for k in BENCH_NODE_LOG_FILTER BENCH_LOGROTATE_SIZE BENCH_CERT_LOG_GLOB BENCH_NODE_JOBS BENCH_COLLECT_WAIT_REJOIN \
         BENCH_TUNNEL_MAX_FAILS BENCH_TUNNEL_MIN_UP_SECS BENCH_ADMISSION_DENIED_MAX BENCH_CHAOS_REFRESH_SCHEDULE \
         FINALIZE_JOBS KEYGEN_JOBS NETCFG_JOBS NETCFG_FAST NETCFG_TRUST_OBSERVERS_EVERYWHERE KEYGEN_REUSE_EXISTING \
         KEYGEN_RPC_ADVERTISE KEYGEN_REPORT; do
    printf 'KNOB %s=%s exported=%s\n' "$k" "${!k-<unset>}" "$(bash -c "[ -n \"\${$k+x}\" ] && echo 1 || echo 0")"
done
'''
    BENCH = {"BENCH_NODE_LOG_FILTER": FILTER, "BENCH_LOGROTATE_SIZE": "20G",
             "BENCH_CERT_LOG_GLOB": "bench-validator-*-unit-stdout*.log.gz", "BENCH_NODE_JOBS": "4",
             "BENCH_COLLECT_WAIT_REJOIN": "1", "BENCH_TUNNEL_MAX_FAILS": "5", "BENCH_TUNNEL_MIN_UP_SECS": "20",
             "BENCH_ADMISSION_DENIED_MAX": "0", "BENCH_CHAOS_REFRESH_SCHEDULE": "1", "FINALIZE_JOBS": "4",
             "KEYGEN_JOBS": "4", "NETCFG_JOBS": "4", "NETCFG_FAST": "1", "NETCFG_TRUST_OBSERVERS_EVERYWHERE": "1",
             "KEYGEN_REUSE_EXISTING": "1", "KEYGEN_RPC_ADVERTISE": "internal-ip", "KEYGEN_REPORT": "1"}

    def knobs(self, **env):
        p = self.bash(self.KNOBS, self.bench, **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        out = {}
        for line in p.stdout.splitlines():
            if line.startswith("KNOB "):
                kv, _, exp = line[5:].rpartition(" exported=")
                k, _, v = kv.partition("=")
                out[k] = v
                self.assertEqual(exp, "1", k)   # every one reaches the drivers the deploy runs
        return out

    def test_bench_values_are_set_only_when_unset(self):
        self.assertEqual(self.knobs(), self.BENCH)
        # An operator's value wins, the root drivers' devnet defaults included; empty turns the
        # logrotate file and the denied-count check off.
        mine = self.knobs(KEYGEN_JOBS="1", NETCFG_FAST="0", KEYGEN_RPC_ADVERTISE="domain", BENCH_NODE_JOBS="1",
                          BENCH_LOGROTATE_SIZE="", BENCH_ADMISSION_DENIED_MAX="")
        self.assertEqual({k: mine[k] for k in ("KEYGEN_JOBS", "NETCFG_FAST", "KEYGEN_RPC_ADVERTISE", "BENCH_NODE_JOBS",
                                               "BENCH_LOGROTATE_SIZE", "BENCH_ADMISSION_DENIED_MAX")},
                         {"KEYGEN_JOBS": "1", "NETCFG_FAST": "0", "KEYGEN_RPC_ADVERTISE": "domain", "BENCH_NODE_JOBS": "1",
                          "BENCH_LOGROTATE_SIZE": "", "BENCH_ADMISSION_DENIED_MAX": ""})
        # Without trust-everywhere a denial is expected (the observer's hub-only trust): no check by default.
        self.assertEqual(self.knobs(NETCFG_TRUST_OBSERVERS_EVERYWHERE="0")["BENCH_ADMISSION_DENIED_MAX"], "")
        for knob, value in (("BENCH_NODE_JOBS", "0"), ("BENCH_COLLECT_WAIT_REJOIN", "2"), ("BENCH_LOGROTATE_SIZE", "20"),
                            ("BENCH_LOGROTATE_SIZE", "20g"), ("BENCH_TUNNEL_MAX_FAILS", "x"),
                            ("BENCH_CHAOS_REFRESH_SCHEDULE", "yes")):
            with self.subTest(knob=knob, value=value):
                p = self.bash(self.KNOBS, self.bench, **{knob: value})
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("❌ benchmark/config.sh: %s='%s'" % (knob, value), p.stdout)

    def test_zone_fallbacks_default_and_validation(self):
        p = self.zones()
        self.assertIn("FALLBACKS 3:asia-northeast1-c 4:us-east4-c,us-east4-a 7:asia-east1-a 8:asia-northeast3-b\n", p.stdout)
        # Index -> node: 3 = validator-04 (Tokyo), 4 = validator-05 (Ashburn), 7 = validator-08 (Hong Kong),
        # 8 = validator-09 (Seoul); each fallback stays in or next to its node's region.
        for idx, zone in ((3, "asia-northeast1-b"), (4, "us-east4-b"), (7, "asia-east2-a"), (8, "asia-northeast3-a")):
            self.assertEqual(FLEET_ZONES[idx], zone)
        self.assertEqual(self.zones(BENCH_ZONE_FALLBACKS="").returncode, 0)
        for value, phrase in (("11:us-east4-c", "index 11 is past the last node (10)"),
                              ("4:us-east4-c 4:us-east4-a", "index 4 appears twice"),
                              ("x:us-east4-c", "index 'x' is not a number"),
                              ("4", "not <index>:<zone>"),
                              ("4:us-east4-c,US-EAST4", "'US-EAST4' is not a zone name"),
                              ("4:us-east4", "'us-east4' is not a zone name"),
                              ("4:*", "holds a glob character")):
            with self.subTest(value=value):
                p = self.zones(BENCH_ZONE_FALLBACKS=value)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("❌ benchmark/config.sh: BENCH_ZONE_FALLBACKS", p.stdout)
                self.assertIn(phrase, p.stdout)


class ZoneFallbackTests(FleetCase):
    """`benchmark-deploy.sh --yes --only 2` over the stub create-instances.sh (fixtures/node-image/
    stub-create-instances.sh): a stockout moves that node to its next BENCH_ZONE_FALLBACKS zone and the
    create runs again; anything else stops."""

    def setUp(self):
        super().setUp()
        install(self.root / "tree" / "common", "create-instances.sh", "stub-create-instances.sh")
        shutil.copyfile(FIX / "stub-create-stockout.txt", self.root / "tree" / "common" / "stub-create-stockout.txt")

    def creates(self):
        return [c.split(" CONFIG_FILE=")[0].split()[1:] for c in self.calls() if c.startswith("create-instances.sh")]

    def zones_env(self):
        f = self.run_dir / "zones.env"
        return f.read_text() if f.exists() else None

    def test_a_stockout_moves_the_node_to_its_fallback_zone(self):
        p = self.deploy(2, cwd=str(self.root), STUB_STOCKOUT="bench-validator-05")   # not the repo root
        self.assertEqual(p.returncode, 0, p.stdout)
        moved = list(FLEET_ZONES)
        moved[4] = "us-east4-c"
        self.assertEqual(self.creates(), [["%s@%s" % (n, z) for n, z in zip(NODES, FLEET_ZONES)],
                                          ["bench-validator-05@us-east4-c"]])
        self.assertIn("BENCH_ZONES_USED=%s\n" % " ".join(moved), self.zones_env())
        m = self.m()
        fb = m["zone_fallbacks"]
        ts = fb[0].pop("ts")
        self.assertRegex(ts, ISO_RE)
        self.assertEqual(fb, [{"inst": "bench-validator-05", "from": "us-east4-b", "to": "us-east4-c", "reason": "stockout"}])
        self.assertEqual([n for n in m["notes"] if n.startswith("zone fallback: ")],
                         ["zone fallback: bench-validator-05 runs in us-east4-c, not us-east4-b (c3-highcpu-8 stockout, %s); "
                          "its latency is that zone's, a comparability caveat" % ts])
        self.assertEqual(m["zones_used"], dict(zip(NODES, moved)))
        self.assertEqual([(i["name"], i["zone"]) for i in m["instances"]], list(zip(NODES, moved)))
        self.assertIn("gcloud compute instances describe bench-validator-05 --zone=us-east4-c --project=%s --format=json"
                      % ("tn-" + "devnet"),
                      self.calls())
        self.assertEqual(len(list((self.run_dir / "logs").glob("create-instances-*.log"))), 2)
        self.assertIn("⚠ bench-validator-05: us-east4-b is out of c3-highcpu-8 (stockout) — it moves to us-east4-c", p.stdout)
        # Then the run's own bench-obs (bench_obs_create, after manifest.instances[]) -> manifest.obs.
        obs = re.search(r"(?m)^\s*OBS_CREATE inst=bench-obs zone=us-west2-a ip=192\.0\.2\.50 id=\S+ existing=0$", p.stdout)
        self.assertIsNotNone(obs, p.stdout)
        self.assertLess(p.stdout.index("✓ manifest.instances[] recorded (11)"), obs.start())
        self.assertEqual(self.m()["obs"]["internal_ip"], "192.0.2.50")
        # Every later script of the run (they all source config.sh) sees the new zone.
        z = self.bash(ZONES_OF, self.bench, BENCH_RUN_ID=self.RUN)
        self.assertIn("ZONES %s\n" % " ".join(moved), z.stdout)

    def test_a_non_stockout_failure_still_stops(self):
        p = self.deploy(2, STUB_CREATE_FAIL="bench-validator-05")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        # create-instances.sh names it relative to REPO_ROOT, where it runs
        own = self.root / "tree" / "logs" / "instance-creation" / "bench-validator-05_creation_1.log"
        self.assertIn("❌ bench-validator-05: create failed for another reason than a stockout (%s)" % own, p.stdout)
        self.assertEqual(len(self.creates()), 1)
        self.assertIsNone(self.zones_env())
        self.assertNotIn("zone_fallbacks", self.m())
        self.assertNotIn("step_2_done", self.m()["timestamps"])

    def test_each_node_is_judged_on_its_own_log_from_any_working_directory(self):
        # One round: validator-05 stocks out, validator-06 hits a quota. Run from another directory, each
        # node's own log (./logs/... under REPO_ROOT) is still what decides: 06 stops the step.
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        p = self.deploy(2, cwd=str(elsewhere), STUB_STOCKOUT="bench-validator-05", STUB_CREATE_FAIL="bench-validator-06")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        own = self.root / "tree" / "logs" / "instance-creation" / "bench-validator-06_creation_1.log"
        self.assertIn("❌ bench-validator-06: create failed for another reason than a stockout (%s)" % own, p.stdout)
        self.assertIsNone(self.zones_env())
        self.assertNotIn("zone_fallbacks", self.m())
        self.assertFalse((elsewhere / "logs").exists())
        # A node whose own log cannot be read is never judged on the round log (05's stockout is in it).
        self.tearDown()
        self.setUp()
        p = self.deploy(2, STUB_STOCKOUT="bench-validator-05", STUB_LOSE_LOG="bench-validator-05")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("❌ bench-validator-05: create failed and its own create log (named in ", p.stdout)
        self.assertIn("cannot be read — not judged a stockout", p.stdout)
        self.assertIsNone(self.zones_env())

    def test_the_second_fallback_after_two_stockouts_and_the_limits(self):
        p = self.deploy(2, STUB_STOCKOUT_ZONES="us-east4-b us-east4-c")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual([c[-1] for c in self.creates()], ["bench-observer-11@us-west2-a", "bench-validator-05@us-east4-c",
                                                           "bench-validator-05@us-east4-a"])
        self.assertEqual([(f["from"], f["to"]) for f in self.m()["zone_fallbacks"]],
                         [("us-east4-b", "us-east4-c"), ("us-east4-c", "us-east4-a")])
        self.assertEqual(self.m()["zones_used"]["bench-validator-05"], "us-east4-a")
        cases = (("us-east4-b us-east4-c us-east4-a", "still hits stockouts after 3 rounds (bench-validator-05)"),
                 ("us-west2-a", "bench-validator-01: us-west2-a is out of c3-highcpu-8 (stockout) and BENCH_ZONE_FALLBACKS "
                                "has no zone left for index 0"))
        for zones, phrase in cases:
            with self.subTest(zones=zones):
                self.tearDown()
                self.setUp()
                p = self.deploy(2, STUB_STOCKOUT_ZONES=zones)
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn(phrase, p.stdout)
                self.assertNotIn("step_2_done", self.m()["timestamps"])


# --------------------------------------------------------------------------- deploy step 15
# step_15 and prom_window_wait run as extracted functions: the blast collect is a stub script, the
# collector a stub that prints its argv, and bench_tunnel_up / bench_fleet_ready / the local analysis
# are test doubles (TEST_READY=0: the fleet is not ready within the cap).
STEP15 = r'''
set -euo pipefail
source "$1/bench-lib.sh"
BENCH_APPLY=1
eval "$2"
bench_tunnel_up() { echo "TUNNEL_UP fd5=$( { : >&5; } 2>/dev/null && echo open || echo closed)"; }
bench_obs_require() { echo "OBS_REQUIRE"; }   # its forwards close fd 5/6 themselves (_bench_tunnel_start)
bench_obs_exists() { echo "OBS_EXISTS"; [ "${TEST_OBS_EXISTS:-1}" = 1 ]; }
bench_fleet_ready() { echo "FLEET_READY $*"; [ "${TEST_READY:-1}" = 1 ]; }
# the n-th read of a node's mode answers the n-th word of TEST_MODES (the last one from then on)
bench_node_mode() {
    local n; n=$(( $(cat "${TMPDIR}/modes.n" 2>/dev/null || echo 0) + 1 )); echo "${n}" > "${TMPDIR}/modes.n"
    echo "MODE_READ ${n} ${INSTANCE_NAMES[$1]}" >&2
    set -- ${TEST_MODES:-CvvActive}; [ "${n}" -le "$#" ] || n=$#; eval "echo \${${n}}"
}
bench_local_analysis() { echo LOCAL_ANALYSIS; }
bench_local_index() { echo LOCAL_INDEX; }
DIR="$3"; COLLECT_METRICS_PY="$3/cgm.py"
exec 5>&1
step_15
'''
COLLECTOR = "import json, sys\nprint('CGM ' + json.dumps(sys.argv[1:]))\n"
BLAST_COLLECT = "#!/usr/bin/env bash\necho \"BLAST $*\"\n"


class PromWindowTests(BashCase):
    """Step 15's Prometheus window (24): after a chaos kill that landed, wait for the fleet before the
    window ends; otherwise the collector keeps deriving the manifest's window."""

    TS = {"nodes_healthy": "2026-01-01T00:00:00Z", "fund_start": "2026-01-01T00:05:00Z",
          "blast_start_at": "2026-01-01T00:10:00Z", "blast_end": "2026-01-01T00:50:00Z",
          "collect_start": "2026-01-01T00:52:00Z"}
    KILL = {"ts": "2026-01-01T00:30:00Z", "node": "bench-validator-05", "action": "docker kill -s KILL telcoin",
            "note": "x", "rc": 0}

    def step15(self, chaos=(), **env):
        run = self.bench / "results" / "rtest-node-image"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({
            "schema": "tn-bench-manifest/v1", "timestamps": self.TS, "chaos": list(chaos), "notes": [],
            "phases": [{"name": "mixed", "start": "2026-01-01T00:12:00Z", "end": "2026-01-01T00:51:00Z"}]}))
        stubs = self.root / "stubs"
        stubs.mkdir()
        (stubs / "cgm.py").write_text(COLLECTOR)
        (stubs / "benchmark-blast.sh").write_text(BLAST_COLLECT)
        (stubs / "benchmark-blast.sh").chmod(0o755)
        fns = shell_functions(self.bench / "benchmark-deploy.sh", "obs_or_die", "prom_window_wait", "step_15")
        env.setdefault("BENCH_NODE_BACK_SECS", "1")
        p = self.bash(STEP15, self.bench, "PROM_WINDOW_ARGS=()\n" + fns, stubs, **env)
        cgm = [json.loads(l[4:]) for l in p.stdout.splitlines() if l.startswith("CGM ")]
        return p, json.loads((run / "manifest.json").read_text()), cgm

    def collector_argv(self, extra=(), prom=True):
        """The collector's argv: the window flags <extra>, then (BENCH_PROM_AUTH=0, the default) bench-obs's
        Prometheus through its local forward, no auth."""
        run = self.bench / "results" / "rtest-node-image"
        return (["--manifest", str(run / "manifest.json"), "--out", str(run / "metrics.json")] + list(extra)
                + (["--prom-url", "http://127.0.0.1:19090/api/v1", "--prom-no-auth"] if prom else []))

    def test_landed_kill_waits_for_the_fleet_and_passes_the_window(self):
        p, m, cgm = self.step15(chaos=[self.KILL], BENCH_COLLECT_WAIT_REJOIN="1", BENCH_FLEET_READY_MAX_WAIT_SECS="1500")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("TUNNEL_UP fd5=closed", p.stdout)    # a surviving tunnel never holds fd 5
        self.assertIn("FLEET_READY 1500 step15", p.stdout)
        w = dict(m["prom_window"])
        self.assertRegex(w.pop("end"), ISO_RE)
        self.assertIsInstance(w.pop("waited_secs"), int)
        self.assertEqual(w, {"start": "2026-01-01T00:00:00Z", "end_reason": "fleet_ready", "confirm_secs": 1})
        self.assertIn("MODE_READ 1 bench-validator-05", p.stdout)   # the killed node, read again after the confirm wait
        self.assertEqual(cgm, [self.collector_argv(["--start", "2026-01-01T00:00:00Z", "--end", m["prom_window"]["end"]])])
        self.assertLess(p.stdout.index("BLAST collect --yes"), p.stdout.index("FLEET_READY"))
        self.assertLess(p.stdout.index("FLEET_READY"), p.stdout.index("OBS_REQUIRE"))
        self.assertLess(p.stdout.index("OBS_REQUIRE"), p.stdout.index("CGM "))
        self.assertIn(" --start 2026-01-01T00:00:00Z --end %s --prom-url http://127.0.0.1:19090/api/v1 --prom-no-auth\n"
                      % m["prom_window"]["end"], p.stdout)   # the printed command is the argv

    def test_bench_obs_gone_at_collect_names_the_lost_series(self):
        # The VM held the run's only copy of its series: the stop says so, and never sends the operator to
        # --from 8 (an empty VM, then a re-fund and a re-blast). Nothing reads Prometheus after it.
        p, m, cgm = self.step15(TEST_OBS_EXISTS="0")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("❌ bench-obs is gone: the run's Prometheus series went with it; do NOT --from 8 (it would "
                      "re-fund and re-blast) — collect without Prometheus (--no-prom) or accept the gap", p.stdout)
        self.assertLess(p.stdout.index("BLAST collect --yes"), p.stdout.index("OBS_EXISTS"))
        self.assertNotIn("OBS_REQUIRE", p.stdout)
        self.assertEqual(cgm, [])

    def test_prom_auth_keeps_the_collectors_own_prometheus_path(self):
        # BENCH_PROM_AUTH=1 (the Grafana proxy path): no --prom-url / --prom-no-auth, bench-obs still required.
        p, m, cgm = self.step15(BENCH_PROM_AUTH="1")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(cgm, [self.collector_argv(prom=False)])
        self.assertIn("OBS_REQUIRE", p.stdout)
        self.assertNotIn("--prom-no-auth", p.stdout)

    def test_fleet_not_ready_is_a_warning_and_ends_at_the_cap(self):
        p, m, cgm = self.step15(chaos=[self.KILL], BENCH_COLLECT_WAIT_REJOIN="1", TEST_READY="0")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("⚠ step 15: no confirmed rejoin within 1500 s", p.stdout)
        self.assertNotIn("MODE_READ", p.stdout)   # never ready: no confirm read
        self.assertNotIn("❌", p.stdout)
        self.assertEqual((m["prom_window"]["end_reason"], m["prom_window"]["confirm_secs"]), ("max_wait", None))
        self.assertEqual(cgm, [self.collector_argv(["--start", "2026-01-01T00:00:00Z", "--end", m["prom_window"]["end"]])])

    def test_a_transient_promotion_does_not_end_the_window(self):
        # Bench 3's target was promoted and demoted again within seconds, 11 times: one CvvActive reading
        # is not a rejoin. Here the first confirm read finds it fallen back, the wait starts over, and the
        # second holds.
        p, m, cgm = self.step15(chaos=[self.KILL], BENCH_COLLECT_WAIT_REJOIN="1", TEST_MODES="CvvInactive CvvActive")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout.count("FLEET_READY "), 2, p.stdout)
        self.assertIn("⚠ step 15: CvvActive did not hold 1 s later: bench-validator-05=CvvInactive", p.stdout)
        self.assertEqual((m["prom_window"]["end_reason"], m["prom_window"]["confirm_secs"]), ("fleet_ready", 1))
        self.assertGreaterEqual(m["prom_window"]["waited_secs"], 2)
        self.assertEqual(cgm, [self.collector_argv(["--start", "2026-01-01T00:00:00Z", "--end", m["prom_window"]["end"]])])

    def test_a_target_that_never_holds_ends_at_the_cap(self):
        p, m, cgm = self.step15(chaos=[self.KILL], BENCH_COLLECT_WAIT_REJOIN="1", TEST_MODES="CvvInactive",
                                BENCH_FLEET_READY_MAX_WAIT_SECS="3")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual((m["prom_window"]["end_reason"], m["prom_window"]["confirm_secs"]), ("max_wait", None))
        self.assertIn("⚠ step 15: no confirmed rejoin within 3 s", p.stdout)
        self.assertLessEqual(m["prom_window"]["waited_secs"], 5)
        self.assertEqual(cgm, [self.collector_argv(["--start", "2026-01-01T00:00:00Z", "--end", m["prom_window"]["end"]])])

    def test_no_landed_kill_or_knob_off_keeps_the_manifest_window(self):
        failed_kill = dict(self.KILL, rc=1)
        restart = dict(self.KILL, action="systemctl restart telcoin")
        for chaos, env, reason in (([failed_kill, restart], {"BENCH_COLLECT_WAIT_REJOIN": "1"}, "no_chaos"),
                                   ([self.KILL], {"BENCH_COLLECT_WAIT_REJOIN": "0"}, "knob_off")):
            with self.subTest(reason=reason):
                shutil.rmtree(str(self.bench / "results"), ignore_errors=True)
                shutil.rmtree(str(self.root / "stubs"), ignore_errors=True)
                p, m, cgm = self.step15(chaos=chaos, **env)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertNotIn("FLEET_READY", p.stdout)
                self.assertNotIn("TUNNEL_UP", p.stdout)
                self.assertEqual(m["prom_window"], {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:52:00Z",
                                                    "end_reason": reason, "waited_secs": 0, "confirm_secs": None})
                self.assertEqual(cgm, [self.collector_argv()])


# --------------------------------------------------------------------------- deploy step 0 + blasters
# The preflight checks (benchmark-deploy.sh) and the blaster create path (benchmark-blast.sh) run as
# extracted functions under an inline fake gcloud: the fixture stub-gcloud.sh knows only the probe
# and step 9. The stockout text is a real one (r20261006-0458, create-bench-blaster-03.log), line
# wrap included, project renamed.
STOCKOUT = """ERROR: (gcloud.compute.instances.create) Could not fetch resource:
---
code: ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS
errorDetails:
- localizedMessage:
    locale: en-US
    message: A e2-standard-2 VM instance is currently unavailable in the australia-southeast1-c
      zone. Try requesting the VM in another zone. For more information, view the
      troubleshooting documentation.
- errorInfo:
    domain: compute.googleapis.com
    metadatas:
      vmType: e2-standard-2
      zone: australia-southeast1-c
      zonesAvailable: ''
    reason: stockout
message: The zone 'projects/tn-fake/zones/australia-southeast1-c' does not have
  enough resources available to fulfill the request.  '(resource type:compute)'.
"""
QUOTA_EXCEEDED = """ERROR: (gcloud.compute.instances.create) Could not fetch resource:
 - Quota 'N2_CPUS' exceeded.  Limit: 0.0 in region australia-southeast1.
"""
FAKE_GCLOUD = r"""#!/usr/bin/env bash
# Inline fake gcloud for the preflight and blaster tests; every call is logged to $STUB_LOG.
printf 'gcloud %s\n' "$*" >> "${STUB_LOG:?}"
zone=""; mt=""
for a in "$@"; do
    case "$a" in --zone=*) zone="${a#--zone=}" ;; --machine-type=*) mt="${a#--machine-type=}" ;; esac
done
case "$*" in
    "compute machine-types describe "*)
        case " ${STUB_MT_MISSING:-} " in *" ${zone} "*)
            printf "ERROR: (gcloud.compute.machine-types.describe) Could not fetch resource:\n - The resource 'projects/tn-fake/zones/%s/machineTypes/%s' was not found\n" "${zone}" "$4" >&2
            exit 1 ;;
        esac
        case " ${STUB_MT_BROKEN:-} " in *" ${zone} "*) echo "ERROR: (gcloud) There was a problem refreshing your credentials." >&2; exit 1 ;; esac
        case "$*" in *guestCpus*) echo 2 ;; *) echo "$4" ;; esac ;;
    "compute disk-types list "*)
        f="${*#*zone:(}"; f="${f%%)*}"
        for z in ${f}; do case " ${STUB_DISK_MISSING:-} " in *" ${z} "*) ;; *) echo "${z}" ;; esac; done ;;
    "compute regions describe "*)
        if [ -f "${STUB_DIR}/region-$4.json" ]; then cat "${STUB_DIR}/region-$4.json"; else cat "${STUB_DIR}/region-default.json"; fi ;;
    "beta quotas info describe "*) cat "${STUB_DIR}/qi-$5.json" 2>/dev/null || exit 1 ;;
    "compute disks list "*) cat "${STUB_DIR}/disks.json" ;;
    "compute instances create "*)
        case " ${STUB_STOCKOUT:-} " in *" ${zone}/${mt} "*) cat "${STUB_DIR}/stockout.txt" >&2; exit 1 ;; esac
        case " ${STUB_CREATE_FAIL:-} " in *" ${mt} "*) cat "${STUB_DIR}/quota-exceeded.txt" >&2; exit 1 ;; esac
        echo "Created [https://www.googleapis.com/compute/v1/projects/tn-fake/zones/${zone}/instances/$4]." ;;
    "compute instances describe "*) echo 4242 ;;
    *) echo "fake gcloud: unexpected: $*" >&2; exit 1 ;;
esac
"""
FLEET_REGIONS = ["asia-east2", "asia-northeast1", "asia-northeast3", "asia-south1", "asia-southeast1",
                 "australia-southeast1", "europe-west2", "europe-west4", "us-east4", "us-west2"]
PREFLIGHT_FNS = ("fleet_zones", "validator_zones", "fleet_regions", "quota_regions", "disk_type_check",
                 "machine_type_check", "machine_vcpus", "region_needs", "hdb_headroom", "quota_check")


def shell_functions(script, *names):
    """The named functions of <script> (a one-line function is its own line)."""
    lines = Path(script).read_text().splitlines()
    out = []
    for name in names:
        start = next(i for i, line in enumerate(lines) if line.startswith(name + "() {"))
        end = start if lines[start].rstrip().endswith("}") else lines.index("}", start)
        out.extend(lines[start:end + 1])
    return "\n".join(out) + "\n"


def region_json(**headroom):
    """A `regions describe` answer: ample quotas, minus <metric>=<headroom> overrides."""
    limits = {"C3_CPUS": 300, "CPUS": 1500, "N2_CPUS": 500, "IN_USE_ADDRESSES": 575, "SSD_TOTAL_GB": 40960,
              "DISKS_TOTAL_GB": 102400}
    quotas = [{"metric": m, "limit": float(v), "usage": 0.0} for m, v in limits.items()]
    for q in quotas:
        if q["metric"] in headroom:
            q["usage"] = q["limit"] - headroom[q["metric"]]
    return json.dumps({"name": "x", "quotas": quotas})


def quota_info(default, **per_region):
    """A `gcloud beta quotas info describe` answer: per-region values, else <default> for the rest."""
    infos = [{"dimensions": {"region": r}, "details": {"value": str(v)}, "applicableLocations": [r]}
             for r, v in per_region.items()]
    infos.append({"details": {"value": str(default)},
                  "applicableLocations": [r for r in FLEET_REGIONS if r not in per_region]})
    return json.dumps({"quotaId": "x", "dimensionsInfos": infos})


class FakeGcloudCase(BashCase):
    def setUp(self):
        super().setUp()
        (self.bin / "gcloud").write_text(FAKE_GCLOUD)
        (self.bin / "gcloud").chmod(0o755)
        self.stub = self.root / "stub-data"
        self.stub.mkdir()
        (self.stub / "region-default.json").write_text(region_json())
        (self.stub / "qi-HDB-TOTAL-GB-per-project-region.json").write_text(quota_info(40960))
        (self.stub / "qi-HDB-TOTAL-IOPS-per-project-region.json").write_text(quota_info(-1))
        (self.stub / "qi-HDB-TOTAL-THROUGHPUT-per-project-region.json").write_text(quota_info(-1))
        (self.stub / "disks.json").write_text("[]")
        (self.stub / "stockout.txt").write_text(STOCKOUT)
        (self.stub / "quota-exceeded.txt").write_text(QUOTA_EXCEEDED)

    def env(self, **extra):
        return super().env(STUB_DIR=str(self.stub), **extra)


PREFLIGHT = r'''
set -euo pipefail
source "$1/bench-lib.sh"
eval "$2"
BENCH_APPLY="${TEST_APPLY:-1}"
[ -z "${TEST_ZONES:-}" ] || read -r -a ZONES <<< "${TEST_ZONES}"
eval "$3"
'''


class PreflightTests(FakeGcloudCase):
    """Deploy step 0's machine type, disk type and quota checks (all zones/regions, one die)."""

    def preflight(self, body, **env):
        fns = shell_functions(self.bench / "benchmark-deploy.sh", *PREFLIGHT_FNS)
        return self.bash(PREFLIGHT, self.bench, fns, body, **env)

    def test_fleet_spans_ten_regions_one_validator_each(self):
        p = self.preflight('echo "Z $(fleet_zones)"; echo "V $(validator_zones)"; echo "R $(fleet_regions)"')
        self.assertEqual(p.returncode, 0, p.stdout)
        out = dict(line.split(" ", 1) for line in p.stdout.splitlines() if line[:2] in ("Z ", "V ", "R "))
        self.assertEqual(out["R"].split(), FLEET_REGIONS)
        self.assertEqual(len(out["Z"].split()), 10)
        self.assertEqual(out["V"], out["Z"])          # the observer shares validator-01's zone
        self.assertEqual(self.calls(), [])

    def test_machine_type_check_lists_every_failing_zone_in_one_die(self):
        zones = ("us-west2-a europe-west2-b australia-southeast1-c asia-northeast1-b northamerica-northeast1-b "
                 "europe-west4-a asia-southeast2-a asia-east2-a asia-northeast3-a asia-south1-a us-west2-a")
        p = self.preflight('machine_type_check "${MACHINE_TYPE}" BENCH_MACHINE_TYPE "$(fleet_zones)"; echo PASSED',
                           TEST_ZONES=zones, STUB_MT_MISSING="asia-southeast2-a asia-south1-a",
                           STUB_MT_BROKEN="asia-east2-a")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("PASSED", p.stdout)
        self.assertIn("c3-highcpu-8 cannot be created in every zone it needs — change ZONES "
                      "(benchmark/config.sh) or BENCH_MACHINE_TYPE:", p.stdout)
        self.assertIn("     asia-south1-a: not offered in this zone\n", p.stdout)
        self.assertIn("     asia-southeast2-a: not offered in this zone\n", p.stdout)
        self.assertIn("     asia-east2-a: describe failed (rc 1): ERROR: (gcloud) There was a problem", p.stdout)
        # Every distinct zone was asked (all failures collected, not the first one only).
        described = [c for c in self.calls() if c.startswith("gcloud compute machine-types describe c3-highcpu-8 ")]
        self.assertEqual(len(described), 10, self.calls())

    def test_machine_type_check_passes_and_dry_run_calls_nothing(self):
        p = self.preflight('machine_type_check e2-standard-2 BENCH_BLASTER_MACHINE_TYPES "$(validator_zones)"')
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("✓ e2-standard-2 offered in all 10 zones", p.stdout)
        self.log.write_text("")
        p = self.preflight('machine_type_check "${MACHINE_TYPE}" BENCH_MACHINE_TYPE "$(fleet_zones)"; disk_type_check; '
                           'quota_check', TEST_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        self.assertIn("gcloud compute machine-types describe c3-highcpu-8 --zone=<each zone>", p.stdout)
        # us-west2 holds bench-obs too (e2-standard-4: CPUS +4, one address, 20 GB boot + 50 GB data SSD_TOTAL_GB).
        self.assertIn("      us-west2: C3_CPUS 16, CPUS 6, IN_USE_ADDRESSES 4, HDB_TOTAL_GB 200, HDB_TOTAL_IOPS 40000, "
                      "HDB_TOTAL_THROUGHPUT 1600, SSD_TOTAL_GB 90\n", p.stdout)
        self.assertIn("      asia-south1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, ", p.stdout)
        self.assertEqual(p.stdout.count("(dry run — not executed)"), 3)

    def test_zone_fallback_check_warns_and_never_stops(self):
        fns = shell_functions(self.bench / "benchmark-deploy.sh", "zone_fallback_zones", "zone_fallback_check")
        body = "zone_fallback_check; echo PASSED"
        p = self.bash(PREFLIGHT, self.bench, fns, body, STUB_MT_MISSING="asia-east1-a")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("PASSED", p.stdout)
        self.assertIn("⚠ zone fallback asia-east1-a: c3-highcpu-8 not offered in this zone", p.stdout)
        self.assertNotIn("❌", p.stdout)
        described = sorted(c.split()[5] for c in self.calls() if c.startswith("gcloud compute machine-types describe "))
        self.assertEqual(described, ["--zone=asia-east1-a", "--zone=asia-northeast1-c", "--zone=asia-northeast3-b",
                                     "--zone=us-east4-a", "--zone=us-east4-c"])
        self.log.write_text("")
        p = self.bash(PREFLIGHT, self.bench, fns, body, TEST_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        self.assertIn("(dry run — not executed)", p.stdout)
        p = self.bash(PREFLIGHT, self.bench, fns, body, BENCH_ZONE_FALLBACKS="")
        self.assertIn("no zone fallbacks (BENCH_ZONE_FALLBACKS is empty)", p.stdout)
        self.assertEqual(self.calls(), [])

    def test_quota_check_passes_with_headroom(self):
        p = self.preflight("quota_check")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("✓ us-west2 need/headroom: C3_CPUS 16/300, CPUS 6/1500, IN_USE_ADDRESSES 4/575, "
                      "HDB_TOTAL_GB 200/40960, HDB_TOTAL_IOPS 40000/unlimited, HDB_TOTAL_THROUGHPUT 1600/unlimited, "
                      "SSD_TOTAL_GB 90/40960", p.stdout)
        self.assertEqual(p.stdout.count("need/headroom:"), 10)
        calls = self.calls()
        self.assertEqual(sorted(c.split()[4] for c in calls if c.startswith("gcloud compute regions describe ")),
                         FLEET_REGIONS)
        self.assertEqual(len([c for c in calls if c.startswith("gcloud beta quotas info describe HDB-TOTAL-")]), 3)

    def test_quota_check_lists_every_shortfall_in_one_table(self):
        (self.stub / "region-asia-northeast1.json").write_text(region_json(C3_CPUS=4))
        (self.stub / "region-us-west2.json").write_text(region_json(IN_USE_ADDRESSES=2, CPUS=1))
        (self.stub / "qi-HDB-TOTAL-GB-per-project-region.json").write_text(quota_info(40960, **{"asia-south1": 50}))
        (self.stub / "qi-HDB-TOTAL-IOPS-per-project-region.json").write_text(quota_info(-1, **{"europe-west2": 30000}))
        # Disks already in europe-west4 / europe-west2 count against the hyperdisk limits; a pd-ssd does not.
        (self.stub / "disks.json").write_text(json.dumps([
            {"name": "other", "zone": ".../zones/europe-west4-b", "type": ".../diskTypes/hyperdisk-balanced",
             "sizeGb": "40900", "provisionedIops": "3000", "provisionedThroughput": "140"},
            {"name": "other2", "zone": ".../zones/europe-west2-a", "type": ".../diskTypes/hyperdisk-balanced",
             "sizeGb": "10", "provisionedIops": "15000", "provisionedThroughput": "140"},
            {"name": "ssd", "zone": ".../zones/asia-east2-a", "type": ".../diskTypes/pd-ssd", "sizeGb": "40960"}]))
        p = self.preflight("quota_check; echo PASSED")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("PASSED", p.stdout)
        rows = [line.split() for line in p.stdout.split("quota shortfalls — nothing was created:", 1)[1].splitlines()[1:]
                if line.startswith("     ") and len(line.split()) == 4]
        self.assertEqual(rows[0], ["region", "metric", "need", "headroom"])
        self.assertEqual(sorted(rows[1:]), sorted([
            ["asia-northeast1", "C3_CPUS", "8", "4"],
            ["asia-south1", "HDB_TOTAL_GB", "100", "50"],
            ["europe-west2", "HDB_TOTAL_IOPS", "20000", "15000"],
            ["europe-west4", "HDB_TOTAL_GB", "100", "60"],
            ["us-west2", "CPUS", "6", "1"],
            ["us-west2", "IN_USE_ADDRESSES", "4", "2"]]))
        # All ten regions were read before the die.
        self.assertEqual(len([c for c in self.calls() if c.startswith("gcloud compute regions describe ")]), 10)

    def test_region_needs_sum_a_shared_metric_and_count_pd_disks(self):
        # The e2 baseline (fleet A): nodes and blasters both on CPUS, node disks on SSD_TOTAL_GB.
        p = self.preflight('region_needs us-west2; region_needs asia-south1; echo "SHARED $(machine_vcpus e2-medium x)"',
                           BENCH_MACHINE_TYPE="e2-custom-4-8192", BENCH_NODE_DISK_TYPE="pd-ssd",
                           BENCH_BLASTER_MACHINE_TYPES="e2-medium")
        self.assertEqual(p.returncode, 0, p.stdout)
        lines = [l for l in p.stdout.splitlines() if l and l[0].isupper()]
        # us-west2 adds bench-obs: CPUS +4 (e2-standard-4, from its name), one address, 20 + 50 GB SSD.
        self.assertEqual(lines, ["CPUS 14", "IN_USE_ADDRESSES 4", "SSD_TOTAL_GB 290",
                                 "CPUS 6", "IN_USE_ADDRESSES 2", "SSD_TOTAL_GB 120", "SHARED 2"])
        # e2-medium's name carries no vCPU count: an alarmed describe answered it.
        self.assertTrue(any(c.startswith("gcloud compute machine-types describe e2-medium --zone=")
                            and "guestCpus" in c for c in self.calls()), self.calls())

    def test_bench_obs_in_a_region_of_its_own_is_checked_there(self):
        # BENCH_OBS_ZONE outside the fleet's regions: one more region read, with bench-obs alone in it.
        p = self.preflight("quota_check", TEST_APPLY="0", BENCH_OBS_ZONE="europe-north1-a", BENCH_OBS_DISK_GB="100")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("      europe-north1: CPUS 4, IN_USE_ADDRESSES 1, SSD_TOTAL_GB 120\n", p.stdout)
        self.assertIn("      us-west2: C3_CPUS 16, CPUS 2, IN_USE_ADDRESSES 3, ", p.stdout)
        self.assertIn("(and bench-obs in europe-north1)", p.stdout)
        self.assertEqual(self.calls(), [])
        p = self.preflight("quota_check", BENCH_OBS_ZONE="europe-north1-a", BENCH_OBS_MACHINE_TYPE="e2-standard-8")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("✓ europe-north1 need/headroom: CPUS 8/1500, IN_USE_ADDRESSES 1/575, SSD_TOTAL_GB 70/40960", p.stdout)
        self.assertEqual(sorted(c.split()[4] for c in self.calls() if c.startswith("gcloud compute regions describe ")),
                         sorted(FLEET_REGIONS + ["europe-north1"]))

    def test_machine_type_check_for_bench_obs_asks_its_zone_only(self):
        p = self.preflight('machine_type_check "${BENCH_OBS_MACHINE_TYPE}" BENCH_OBS_MACHINE_TYPE "${BENCH_OBS_ZONE}"',
                           STUB_MT_MISSING="us-west2-a")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("e2-standard-4 cannot be created in every zone it needs — change ZONES (benchmark/config.sh) or "
                      "BENCH_OBS_MACHINE_TYPE:\n     us-west2-a: not offered in this zone", p.stdout)
        self.assertEqual([c for c in self.calls() if c.startswith("gcloud compute machine-types describe ")],
                         ["gcloud compute machine-types describe e2-standard-4 --zone=us-west2-a --project=%s "
                          "--format=value(name)" % ("tn-" + "devnet")])


BLAST = r'''
set -euo pipefail
source "$1/bench-lib.sh"
eval "$2"
BENCH_APPLY=1
STARTUP="$3/startup.sh"; DEPLOYMENTS_FILE="$3/deployments.json"; BENCH_TXGEN_CONFIG="$3/config.toml"
VAL_COUNT=2
blaster_name() { printf 'bench-blaster-%02d' "$(( $1 + 1 ))"; }
rc=0
create_vm bench-blaster-01 "${ZONES[0]}" blast "bench-validator-01=http://192.0.2.1:8545" 600 0 1700000000 || rc=$?
echo "RC1=${rc}"; rc=0
create_vm bench-blaster-02 "${ZONES[1]}" blast "bench-validator-02=http://192.0.2.2:8545" 600 600 1700000000 || rc=$?
echo "RC2=${rc}"
[ "${TEST_MANIFEST:-1}" = "0" ] || echo "MANIFEST $(blasters_json | jq -c .)"
'''


class BlasterFallbackTests(FakeGcloudCase):
    """benchmark-blast.sh create_vm: a stockout retries the same blaster on the next type."""

    def blast(self, **env):
        fns = shell_functions(BENCH / "benchmark-blast.sh", "is_stockout", "create_vm", "blasters_json")
        files = self.root / "blast-files"
        files.mkdir(exist_ok=True)
        p = self.bash(BLAST, self.bench, fns, files, **env)
        manifest = None
        for line in p.stdout.splitlines():
            if line.startswith("MANIFEST "):
                manifest = json.loads(line[len("MANIFEST "):])
        return p, manifest

    def creates(self):
        return [(c.split()[4], re.search(r"--machine-type=(\S+)", c).group(1))
                for c in self.calls() if c.startswith("gcloud compute instances create ")]

    def meta(self, name):
        f = self.bench / "results" / "rtest-node-image" / "meta" / name / "MACHINE_TYPE"
        return f.read_text().strip() if f.exists() else None

    def test_stockout_retries_next_type_and_manifest_records_it(self):
        p, manifest = self.blast(STUB_STOCKOUT="us-west2-a/e2-standard-2")
        self.assertIn("RC1=0", p.stdout)
        self.assertIn("RC2=0", p.stdout)
        self.assertEqual(self.creates(), [("bench-blaster-01", "e2-standard-2"), ("bench-blaster-01", "n2-standard-2"),
                                          ("bench-blaster-02", "e2-standard-2")])
        self.assertIn("bench-blaster-01: e2-standard-2 is out of stock in us-west2-a (stockout); "
                      "trying the next blaster type", p.stdout)
        self.assertIn("bench-blaster-01: created on n2-standard-2 in us-west2-a after a stockout of e2-standard-2",
                      p.stdout)
        self.assertEqual((self.meta("bench-blaster-01"), self.meta("bench-blaster-02")),
                         ("n2-standard-2", "e2-standard-2"))
        self.assertEqual([(b["name"], b["zone"], b["machine_type"], b["instance_id"]) for b in manifest],
                         [("bench-blaster-01", "us-west2-a", "n2-standard-2", "4242"),
                          ("bench-blaster-02", "europe-west2-b", "e2-standard-2", "4242")])
        # The retry is the same create: only --machine-type differs.
        first, second = [c for c in self.calls() if c.startswith("gcloud compute instances create bench-blaster-01 ")]
        self.assertEqual(first.replace("--machine-type=e2-standard-2", "--machine-type=n2-standard-2"), second)

    def test_other_failure_is_not_retried(self):
        p, _ = self.blast(STUB_CREATE_FAIL="e2-standard-2", TEST_MANIFEST="0")
        self.assertIn("RC1=1", p.stdout)
        self.assertEqual(self.creates(), [("bench-blaster-01", "e2-standard-2"), ("bench-blaster-02", "e2-standard-2")])
        self.assertIn("Quota 'N2_CPUS' exceeded", p.stdout)
        self.assertIsNone(self.meta("bench-blaster-01"))

    def test_pinned_type_has_no_fallback(self):
        p, _ = self.blast(BENCH_BLASTER_MACHINE_TYPE="n2d-standard-2", STUB_STOCKOUT="us-west2-a/n2d-standard-2",
                          TEST_MANIFEST="0")
        self.assertIn("RC1=1", p.stdout)
        self.assertIn("RC2=0", p.stdout)
        self.assertEqual(self.creates(), [("bench-blaster-01", "n2d-standard-2"), ("bench-blaster-02", "n2d-standard-2")])
        self.assertIn("bench-blaster-01: every blaster type is out of stock in us-west2-a (n2d-standard-2)", p.stdout)
        self.assertIsNone(self.meta("bench-blaster-01"))
        self.assertEqual(self.meta("bench-blaster-02"), "n2d-standard-2")

    def test_dry_run_prints_the_first_type_and_the_fallback(self):
        fns = shell_functions(BENCH / "benchmark-blast.sh", "is_stockout", "create_vm")
        script = BLAST.split("BENCH_APPLY=1")[0] + ("BENCH_APPLY=0\nSTARTUP=s DEPLOYMENTS_FILE=d BENCH_TXGEN_CONFIG=c\n"
                                                    "create_vm bench-blaster-03 australia-southeast1-c blast u 600 1200 1\n")
        p = self.bash(script, self.bench, fns, self.root)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        argv = [l for l in p.stdout.splitlines() if l.startswith("    + perl -e")]
        self.assertEqual(len(argv), 1, p.stdout)
        self.assertIn(" 600 gcloud compute instances create bench-blaster-03 ", argv[0])
        self.assertIn(" --zone=australia-southeast1-c --machine-type=e2-standard-2 ", argv[0])
        self.assertIn(" --boot-disk-size=20GB --boot-disk-type=pd-balanced ", argv[0])
        self.assertIn("on a zone stockout: the same create with --machine-type=n2-standard-2 n2d-standard-2 (in turn)",
                      p.stdout)

    def test_is_stockout_reads_each_marker_through_line_wraps(self):
        fn = shell_functions(BENCH / "benchmark-blast.sh", "is_stockout")
        cases = [(STOCKOUT, 0), (QUOTA_EXCEEDED, 1), ("code: ZONE_RESOURCE_POOL_EXHAUSTED\n", 0),
                 ("    reason: stockout\n", 0), ("The zone 'z' does not have\n  enough resources available\n", 0),
                 ("The resource 'projects/p/zones/z/machineTypes/t' was not found\n", 1)]
        for text, want in cases:
            with self.subTest(text=text[:40]):
                p = subprocess.run(["bash", "-c", fn + 'is_stockout "$1"', "x", text])
                self.assertEqual(p.returncode, want)

    def test_every_type_out_of_stock_fails(self):
        p, _ = self.blast(STUB_STOCKOUT="us-west2-a/e2-standard-2 us-west2-a/n2-standard-2 us-west2-a/n2d-standard-2",
                          TEST_MANIFEST="0")
        self.assertIn("RC1=1", p.stdout)
        self.assertEqual([t for n, t in self.creates() if n == "bench-blaster-01"],
                         ["e2-standard-2", "n2-standard-2", "n2d-standard-2"])
        self.assertIn("every blaster type is out of stock in us-west2-a "
                      "(e2-standard-2 n2-standard-2 n2d-standard-2)", p.stdout)


if __name__ == "__main__":
    unittest.main()
