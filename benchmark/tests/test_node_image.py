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


# --------------------------------------------------------------------------- v2 nodes (steps 7, 8, 9)
# A sandbox v2 node is a directory laid out like a node's root: the C8 fixture (fixtures/v2-node:
# .node-meta, node.env, tn-start-docker, telcoin.service) with DATA_DIR moved under it, the Alloy
# env, <DATA_DIR>/parameters.yaml, the scripts' checkout with a stub lib/common.sh
# (fixtures/node-image/v2-lib-common.sh), the node stubs in bin/, and state/ files the stubs answer
# from. fixtures/node-image/v2-node-run.sh runs a remote script there, its node paths relocated
# (RELOCATED, kept in step with the script by test_relocation_list_matches_the_runner).
V2 = Path(__file__).resolve().parent / "fixtures" / "v2-node"
RELOCATED = ("/etc/telcoin/", "/etc/systemd/system/", "/usr/local/libexec/telcoin/",
             "/usr/local/bin/bench-node-sampler.sh", "/opt/telcoin-node-scripts", "/var/lib/telcoin-alloy/",
             "/tmp/bench-obs")
NODE_STUBS = (("systemctl", "stub-v2-node-systemctl.sh"), ("docker", "stub-v2-node-docker.sh"),
              ("date", "stub-v2-node-date.sh"), ("git", "stub-v2-node-git.sh"), ("stat", "stub-v2-node-stat.sh"),
              ("curl", "stub-node-curl.sh"), ("sleep", "stub-node-sleep.sh"))
STARTED = "2026-01-01T00:00:00.000000000Z"     # the container's StartedAt (stub date -d: 1767225600)
CHAIN_HEX = "0x7e1e"                           # the bench chain 32286, as the nodes' RPC answers it
GUARD_RPC = "http://127.0.0.1:9"               # BENCH_GUARD_PUBLIC_RPC (contract C5a)
FILTER = "info,primary::certifier=debug,primary::proposer=debug,primary=debug,primary::cert_validator=info,primary::cert_manager=info,primary::cert_fetcher=info,tn_primary::network::handler=debug"
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
        for rel in ("etc/telcoin/alloy", "etc/systemd/system", "usr/local/bin", "usr/local/libexec/telcoin",
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

    def precfg_ok(self, filt="-", maxfiles="-", params=0):
        return ("PRECFG_OK %s datadir=%s/var/lib/telcoin http=0.0.0.0 ws=0.0.0.0 metrics=127.0.0.1:9101 filter=%s "
                "maxfiles=%s params=%d owner=root:root mode=755 unit=inactive" % (self.INST, self.node.root, filt,
                                                                                  maxfiles, params))

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
        self.assertEqual(len(sources), 12)
        self.assertEqual(set(sources), {"lib source DEVNET_RPC_URL=" + GUARD_RPC})
        # The start script is what step 9 will read off the running container; nothing else moved.
        self.assertEqual(self.node.node_command(), v2_cmdline())
        self.assertEqual(self.yaml_text(), self.staged)
        self.assertIn("git -C %s/opt/telcoin-node-scripts rev-parse HEAD" % self.node.root, self.node.calls())
        unit_calls = [l for l in self.node.calls() if l.startswith("systemctl ")]
        self.assertEqual(unit_calls, ["systemctl is-active telcoin"] * 2)   # read twice, never started

    def test_empty_filter_leaves_the_log_flags_alone(self):
        p, lines = self.node.run(self.script_for(BENCH_NODE_LOG_FILTER=""))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(lines, [self.precfg_ok()], p.stdout)
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
        self.assertEqual(lines, [self.precfg_ok(FILTER, "20", 3)], p.stdout)
        self.assertEqual([l.rsplit(" ", 1)[1] for l in self.lib_calls("set")], ["rc=1"] * 6)
        self.assertEqual((self.node.start_script.read_text(), self.yaml_text()), first)

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
        self.assertEqual(lines[-1], 'echo "PRECFG_OK bench-validator-01 datadir=$D http=0.0.0.0 ws=0.0.0.0 '
                         'metrics=127.0.0.1:$MP filter=${F:--} maxfiles=${MF:--} params=$NOV owner=root:root mode=755 '
                         'unit=$u"')
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


class FleetCase(BashCase):
    """A deploy run against eleven sandbox v2 nodes: gcloud is fixtures/node-image/
    stub-gcloud-v2-node.sh, which runs every `sudo bash -s` session on the node's sandbox."""

    RUN = "rtest-fleet"
    NODE_UNIT = "active"

    def setUp(self):
        super().setUp()
        install(self.bin, "gcloud", "stub-gcloud-v2-node.sh")
        install(self.bin, "v2-node-run.sh", "v2-node-run.sh")
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

    def deploy(self, step, **env):
        return subprocess.run(
            ["bash", str(self.bench / "benchmark-deploy.sh"), "--run", self.RUN, "--yes", "--only", str(step)],
            env=self.env(BENCH_RUN_ID=None, STUB_NODES=str(self.root / "nodes"), STUB_SPOOL=str(self.spool),
                         STUB_CHAIN_HEX=CHAIN_HEX, POSTCFG_WAIT_SECS="10", **env),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, universal_newlines=True, errors="replace")

    def ssh_targets(self):
        return [c.split()[3] for c in self.calls() if c.startswith("gcloud compute ssh ")]

    def m(self):
        return json.loads(self.manifest.read_text())


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


class ObsScriptTests(BashCase):
    """Step 8's session (--print-obs-script): the ingest token on stdin only, setup-observability.sh
    with --metrics already on the node command (no restart), then the same-session Alloy relabel."""

    INST = "bench-validator-03"
    TOKEN = "tok-3f9b0709-not-a-secret"

    def setUp(self):
        super().setUp()
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"), "--print-obs-script", self.INST],
                           env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                           universal_newlines=True)
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
        # The two obs-devnet URLs, as config.sh gives them to the script.
        self.config = {"OBS_PUSH_URL": re.search(r"--push-url '([^']+)'", self.body).group(1),
                       "OBS_METRICS_PUSH_URL": re.search(r"grep -qx 'OBS_METRICS_PUSH_URL=([^']+)'", self.body).group(1)}

    def session(self, events="obs-events-ok.jsonl", stdin=None, **env):
        return self.node.run(self.body, stdin=self.TOKEN + "\n" if stdin is None else stdin, name="bench-obs",
                             STUB_OBS_EVENTS=str(FIX / events), **env)

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

    def test_remote_command_is_the_printed_script(self):
        fns = shell_functions(self.bench / "benchmark-deploy.sh", "obs_script", "obs_remote_cmd")
        script = ('set -euo pipefail\nsource "$1/bench-lib.sh"\neval "$2"\n'
                  'obs_remote_cmd "$3" "$(tn_region_from_zone "$4")"\n')
        p = self.bash(script, self.bench, fns, self.INST, self.zone)
        self.assertEqual(p.returncode, 0, p.stdout)
        m = re.fullmatch(r'sudo bash -c "\$\(printf %s ([A-Za-z0-9+/=]+) \| base64 -d\)" bench-obs', p.stdout.strip())
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
                                "--push-url", self.config["OBS_PUSH_URL"], "--metrics-push-url",
                                "http://127.0.0.1:9/bench-hold"])
        env = self.state("obs-env")
        self.assertIn("DEVNET_RPC_URL=%s\n" % GUARD_RPC, env)
        for where, text in (("argv", "\n".join(argv)), ("env", env), ("node calls", "\n".join(self.node.calls())),
                            ("session output", p.stdout)):
            self.assertNotIn(self.TOKEN, text, where)
        # No restart; Alloy stopped, its WAL wiped, relabelled, started, all in this session.
        self.assertFalse([c for c in self.node.calls() if re.match(r"systemctl (start|stop|restart) telcoin$", c)])
        self.assertEqual([c for c in self.node.calls() if re.match(r"systemctl (start|stop) ", c)],
                         ["systemctl stop telcoin-alloy.service", "systemctl start telcoin-alloy.service"])
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
        self.assertIn(self.TOKEN, (self.node.root / "tmp/bench-obs.err").read_text())   # the stub did leak it
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

    def test_plan_lists_the_coordinated_start_and_the_gates(self):
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh")], env=self.env(BENCH_RUN_ID="rtest-plan"),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, universal_newlines=True,
                           errors="replace")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("DRY RUN — re-run with --yes to execute.", p.stdout)
        steps, cur = {}, None
        for line in p.stdout.splitlines():
            head = re.match(r"^ {2}([ 0-9]{2})  \S", line)
            if head:
                cur = int(head.group(1))
            elif not line.startswith("     "):
                cur = None
            if cur is not None:
                steps.setdefault(cur, []).append(line)
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
        for inst, node in self.nodes.items():
            self.assertIn("PRECFG_OK %s datadir=%s/var/lib/telcoin " % (inst, node.root), p.stdout)
            self.assertEqual(node.node_command(), v2_cmdline(), inst)
        logs = sorted(f.name.split("-")[1] for f in (self.run_dir / "logs").glob("finalize-*.log"))
        self.assertEqual(logs, ["stage", "start"])
        self.assertIn("step_7_done", self.m()["timestamps"])

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
        die = [l for l in p.stdout.splitlines() if "stage-only found running unit(s) before any coordinated start" in l]
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

    def test_pre_start_failure_stops_before_start_all(self):
        self.nodes["bench-validator-05"].put("git-head", "0" * 40)
        p = self.deploy7()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("pre-start config failed on bench-validator-05", p.stdout)
        self.assertEqual(self.ssh_targets(), NODES[:5])
        self.assertNotIn("devnet-finalize.sh --start-all", self.sequence())
        self.assertNotIn("coordinated_start", self.m())


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
                 "australia-southeast1", "europe-west2", "europe-west4", "northamerica-northeast1", "us-west2"]
PREFLIGHT_FNS = ("fleet_zones", "validator_zones", "fleet_regions", "disk_type_check", "machine_type_check",
                 "machine_vcpus", "region_needs", "hdb_headroom", "quota_check")


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
        self.assertIn("      us-west2: C3_CPUS 16, CPUS 2, IN_USE_ADDRESSES 3, HDB_TOTAL_GB 200, HDB_TOTAL_IOPS 40000, "
                      "HDB_TOTAL_THROUGHPUT 1600, SSD_TOTAL_GB 20\n", p.stdout)
        self.assertIn("      asia-south1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, ", p.stdout)
        self.assertEqual(p.stdout.count("(dry run — not executed)"), 3)

    def test_quota_check_passes_with_headroom(self):
        p = self.preflight("quota_check")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("✓ us-west2 need/headroom: C3_CPUS 16/300, CPUS 2/1500, IN_USE_ADDRESSES 3/575, "
                      "HDB_TOTAL_GB 200/40960, HDB_TOTAL_IOPS 40000/unlimited, HDB_TOTAL_THROUGHPUT 1600/unlimited, "
                      "SSD_TOTAL_GB 20/40960", p.stdout)
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
            ["us-west2", "CPUS", "2", "1"],
            ["us-west2", "IN_USE_ADDRESSES", "3", "2"]]))
        # All ten regions were read before the die.
        self.assertEqual(len([c for c in self.calls() if c.startswith("gcloud compute regions describe ")]), 10)

    def test_region_needs_sum_a_shared_metric_and_count_pd_disks(self):
        # The e2 baseline (fleet A): nodes and blasters both on CPUS, node disks on SSD_TOTAL_GB.
        p = self.preflight('region_needs us-west2; region_needs asia-south1; echo "SHARED $(machine_vcpus e2-medium x)"',
                           BENCH_MACHINE_TYPE="e2-custom-4-8192", BENCH_NODE_DISK_TYPE="pd-ssd",
                           BENCH_BLASTER_MACHINE_TYPES="e2-medium")
        self.assertEqual(p.returncode, 0, p.stdout)
        lines = [l for l in p.stdout.splitlines() if l and l[0].isupper()]
        self.assertEqual(lines, ["CPUS 10", "IN_USE_ADDRESSES 3", "SSD_TOTAL_GB 220",
                                 "CPUS 6", "IN_USE_ADDRESSES 2", "SSD_TOTAL_GB 120", "SHARED 2"])
        # e2-medium's name carries no vCPU count: an alarmed describe answered it.
        self.assertTrue(any(c.startswith("gcloud compute machine-types describe e2-medium --zone=")
                            and "guestCpus" in c for c in self.calls()), self.calls())


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
