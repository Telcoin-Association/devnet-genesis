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


# Step 9's gcloud for Step9Tests: like fixtures/node-image/stub-gcloud.sh, but the POSTCFG_OK line it
# answers carries the readback fields too, taken from the script it was sent, as a node that applied
# it would report them: the delays and threshold of its setp lines (else the fleet file's 500/250/250
# ms and 5) and the filter of its F= line. STUB_BAD_INST answers STUB_BAD_SHA and STUB_BAD_MHD (boot
# line) instead; STUB_MHD sets every node's boot max header delay.
STEP9_GCLOUD = r"""#!/usr/bin/env bash
printf 'gcloud %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    "compute ssh "*)
        inst="$3"; cmd=""
        for a in "$@"; do case "${a}" in --command=*) cmd="${a#--command=}" ;; esac; done
        [ "${cmd}" = "sudo bash -s" ] || exit 0
        f="${STUB_SPOOL:?}/${inst}.sh"; cat > "${f}"
        val() { sed -n "s/^setp $1 \([0-9]*\)ms$/\1/p" "${f}" | tail -1; }
        mx="$(val max_header_delay)"; mx="${mx:-500}"; mn="$(val min_header_delay)"; mn="${mn:-250}"
        mb="$(val max_batch_delay)"; mb="${mb:-250}"
        thr="$(sed -n 's/^setp header_num_of_batches_threshold \([0-9]*\)$/\1/p' "${f}" | tail -1)"
        fl="$(sed -n "s/^F='\([^']*\)'; MF='[0-9]*'$/\1/p" "${f}")"; mf="$(sed -n "s/^F='[^']*'; MF='\([0-9]*\)'$/\1/p" "${f}")"
        sha="${STUB_SHA:?}"; bmx="${STUB_MHD:-${mx}}"
        if [ "${inst}" = "${STUB_BAD_INST:-}" ]; then sha="${STUB_BAD_SHA:-${sha}}"; bmx="${STUB_BAD_MHD:-${bmx}}"; fi
        echo "Warning: Permanently added 'compute.0000' (ED25519) to the list of known hosts."
        echo "POSTCFG_OK ${inst} chain=0x7e1e block=0x5 ip=192.0.2.9 progress=blocks 3->5 sha=${sha} mhd=${bmx} nhd=${mn} mbd=${mb} vt=? forks=subsecond-from-genesis max=${mx} min=${mn} batch=${mb} thr=${thr:-5} vote=- filter=${fl:--} maxfiles=${mf:--}"
        ;;
    *) echo "stub gcloud: unexpected: $*" >&2; exit 1 ;;
esac
"""
FILTER = "info,primary::certifier=debug,primary::proposer=debug"


class Step9Tests(BashCase):
    """`benchmark-deploy.sh --yes --only 9` on a mock run whose manifest names the build."""

    RUN = "rtest-step9"

    def setUp(self):
        super().setUp()
        (self.bin / "gcloud").write_text(STEP9_GCLOUD)
        (self.bin / "gcloud").chmod(0o755)
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
            self.assertEqual(m["node_startup"][inst], {
                "sha": FULL_SHA, "mhd": 500, "nhd": 250, "mbd": 250, "vt": None, "forks": "subsecond-from-genesis",
                "params": {"max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250,
                           "header_num_of_batches_threshold": 5, "vote_timeout_ms": None},
                "log_filter": FILTER, "log_max_files": 20}, inst)
        self.assertEqual(m["consensus_parameters"]["overrides"], {})
        script = (self.spool / "bench-validator-01.sh").read_text()
        self.assertIn("F='%s'; MF='20'" % FILTER, script)
        self.assertNotIn("\nsetp ", script)
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
        # The gate recorded every node's planned log filter; only the restarted node has boot fields.
        self.assertEqual([i for i, v in m["node_startup"].items() if "sha" in v], ["bench-validator-01"])
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

    OVERRIDE = "2:min_header_delay=50ms,max_header_delay=250ms"

    def test_override_on_one_node_only(self):
        p = self.deploy(BENCH_NODE_PARAM_OVERRIDES=self.OVERRIDE)
        self.assertEqual(p.returncode, 0, p.stdout)
        m = json.loads(self.manifest.read_text())
        self.assertEqual(m["consensus_parameters"]["overrides"],
                         {"bench-validator-03": {"min_header_delay": "50ms", "max_header_delay": "250ms"}})
        for inst in NODES:
            got = m["node_startup"][inst]
            want = (250, 50) if inst == "bench-validator-03" else (500, 250)
            self.assertEqual((got["mhd"], got["nhd"]), want, inst)
            self.assertEqual((got["params"]["max_header_delay_ms"], got["params"]["min_header_delay_ms"]), want, inst)
        three = (self.spool / "bench-validator-03.sh").read_text()
        self.assertIn("\nsetp min_header_delay 50ms\nsetp max_header_delay 250ms\n", three)
        self.assertIn('cat "$P.bak" > "$P"', three)       # the yaml rewrite itself travels in the script
        for inst in NODES:
            if inst != "bench-validator-03":
                self.assertNotIn("\nsetp ", (self.spool / (inst + ".sh")).read_text(), inst)
        self.assertIn("bench-validator-03: http.addr 0.0.0.0, assert alloy labels, parameters.yaml "
                      "(min_header_delay=50ms,max_header_delay=250ms)", p.stdout)

    def test_wrong_value_on_one_node_stops_the_fleet(self):
        p = self.deploy(BENCH_NODE_PARAM_OVERRIDES=self.OVERRIDE, STUB_BAD_INST="bench-validator-03",
                        STUB_BAD_MHD="500")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-03: max_header_delay = 500 ms, expected 250 ms (manifest "
                      "consensus_parameters + BENCH_NODE_PARAM_OVERRIDES)", p.stdout)
        self.assertEqual(self.ssh_targets(), [n for n in NODES[:3] for _ in (0, 1)])

    def test_empty_log_filter_leaves_the_command_line_alone(self):
        p = self.deploy(BENCH_NODE_LOG_FILTER="")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("\nF=", (self.spool / "bench-validator-01.sh").read_text())
        m = json.loads(self.manifest.read_text())
        self.assertEqual({(v["log_filter"], v["log_max_files"]) for v in m["node_startup"].values()}, {(None, None)})

    def test_fleet_minimum_max_header_delay_feeds_fork_delay_check(self):
        # A pre-subsecond build at 1 s delays passes, until one node is given 500 ms.
        m = json.loads(self.manifest.read_text())
        m["node_fork_schedule"] = "pre-subsecond"
        m["consensus_parameters"].update(max_header_delay_ms=1000, min_header_delay_ms=250, max_batch_delay_ms=250)
        self.manifest.write_text(json.dumps(m, indent=2) + "\n")
        self.params.write_text("max_header_delay: 1s\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n")
        p = self.deploy(BENCH_NODE_PARAM_OVERRIDES="2:max_header_delay=500ms", STUB_MHD="1000")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("max_header_delay is 500 ms (BENCH_NODE_PARAM_OVERRIDES (bench-validator-03))", p.stdout)
        self.assertEqual(self.ssh_targets(), [])

    def test_gate_refuses_parameters_a_node_would_refuse(self):
        p = self.deploy(BENCH_NODE_PARAM_OVERRIDES="4:min_header_delay=600ms 6:max_header_delay=1s,vote_timeout=1s")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("✗ bench-validator-05: min_header_delay 600 ms > max_header_delay 500 ms", p.stdout)
        self.assertIn("✗ bench-validator-07: vote_timeout 1000 ms < max_header_delay 1000 ms + 250 ms", p.stdout)
        self.assertEqual(self.ssh_targets(), [])


# docker on the node for RemoteScriptTests: `docker logs telcoin ...` prints the boot log fixture,
# `docker inspect` the telcoin command of the wrapper $STUB_WRAPPER as the restarted container's
# command line (continuation lines joined); every other call succeeds silently.
NODE_DOCKER = r"""#!/usr/bin/env bash
printf 'docker %s\n' "$*" >> "${STUB_LOG:?}"
case "${1:-}" in
    logs) cat "${STUB_BOOT_LOG:?}" ;;
    inspect) sed -n '/^telcoin node/,$p' "${STUB_WRAPPER:?}" | tr -d '\\' | tr '\n' ' '; echo ;;
    *) exit 0 ;;
esac
"""


class RemoteScriptTests(BashCase):
    """Step 9's remote script (--print-postconfig) against a stubbed node."""

    RELOCATE = ("/opt/telcoin/", "/etc/telcoin/", "/etc/systemd/system/",
                "/usr/local/bin/bench-node-sampler.sh")

    def setUp(self):
        super().setUp()
        self.node = self.root / "node-root"
        self.script = self.script_for()
        (self.node / "opt/telcoin").mkdir(parents=True)
        (self.node / "etc/telcoin/alloy").mkdir(parents=True)
        (self.node / "etc/systemd/system").mkdir(parents=True)
        (self.node / "usr/local/bin").mkdir(parents=True)
        # The node's wrapper as setup-node.sh writes it: the datadir bind-mounted at the container's
        # --datadir, whose host side holds the parameters.yaml step 7 staged (the committed file).
        self.datadir = self.node / "home/telcoin/data"
        self.datadir.mkdir(parents=True)
        self.yaml = self.datadir / "parameters.yaml"
        self.yaml.write_text((BENCH / "consensus-parameters.yaml").read_text())
        self.wrapper = self.node / "opt/telcoin/start-telcoin.sh"
        self.wrapper.write_text(
            "#!/usr/bin/env bash\n# Auto-generated by setup-node.sh (--datadir in a comment is not the flag)\n"
            "exec docker run --rm \\\n--name telcoin \\\n-v %s:/home/nonroot \\\n-v /etc/tn:/etc/telcoin:ro \\\n"
            "img \\\ntelcoin node \\\n--datadir /home/nonroot \\\n--log.stdout.format log-fmt \\\n-vvv \\\n"
            "--http --http.addr 127.0.0.1 --ws --ws.addr 127.0.0.1\n" % self.datadir)
        (self.node / "etc/telcoin/alloy/telcoin-alloy.env").write_text(
            "TN_CHAIN=%s\nTN_NODE=bench-validator-01\n" % self.label)
        self.nodebin = self.root / "node-bin"
        for name in ("curl", "systemctl", "date", "sleep"):
            install(self.nodebin, name, "stub-node-%s.sh" % name)
        (self.nodebin / "docker").write_text(NODE_DOCKER)
        (self.nodebin / "docker").chmod(0o755)
        if not host_sed_is_gnu():
            install(self.nodebin, "sed", "stub-sed-gnu-inplace.sh")
        self.state = self.root / "node-state"
        self.state.mkdir()

    def script_for(self, **env):
        """Step 9's script for bench-validator-01 (--print-postconfig), node paths moved into the sandbox."""
        p = subprocess.run(["bash", str(self.bench / "benchmark-deploy.sh"),
                            "--print-postconfig", "bench-validator-01"],
                           env=self.env(BENCH_RUN_ID="rtest-postcfg", **env), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), [])   # printing the script contacts nothing
        script = p.stdout
        self.chain_hex = re.search(r'\[ "\$cid" = "(0x[0-9a-f]+)" \]', script).group(1)
        self.label = re.search(r"grep -qx 'TN_CHAIN=([^']+)'", script).group(1)
        for rel in self.RELOCATE:
            self.assertIn(rel, script)
            script = script.replace(rel, str(self.node) + rel)
        # Every redirection now lands in the sandbox (or /dev/null).
        for target in re.findall(r"(?<![0-9&-])>\s*(/[^\s;|&)]*)", script):
            self.assertTrue(target == "/dev/null" or target.startswith(str(self.node) + "/"), target)
        return script

    def run_remote(self, boot_log, script=None):
        env = {"PATH": str(self.nodebin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "STUB_LOG": str(self.log),
               "STUB_BOOT_LOG": str(FIX / boot_log), "STUB_STATE": str(self.state),
               "STUB_CHAIN_HEX": self.chain_hex, "POSTCFG_WAIT_SECS": "10", "STUB_WRAPPER": str(self.wrapper)}
        p = subprocess.run(["bash", "-s"], input=script or self.script, env=env, cwd=str(self.node),
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
                                          " max=500 min=250 batch=250 thr=5 vote=- filter=%s maxfiles=20"
                                          % (FULL_SHA, FILTER)), lines[0])
        self.assertIn("--http.addr 0.0.0.0", self.wrapper.read_text())
        self.assertIn("\n--datadir /home/nonroot --log.stdout.filter %s --log.file.filter %s --log.file.max-files 20 \\\n"
                      % (FILTER, FILTER), self.wrapper.read_text())
        # No override: the staged file is untouched, and kept as the .bak.
        original = (BENCH / "consensus-parameters.yaml").read_text()
        self.assertEqual(self.yaml.read_text(), original)
        self.assertEqual((self.datadir / "parameters.yaml.bak").read_text(), original)
        self.assertEqual((self.node / "usr/local/bin/bench-node-sampler.sh").read_bytes(),
                         (BENCH / "node-sampler.sh").read_bytes())
        self.assertTrue((self.node / "etc/systemd/system/bench-node-sampler.service").is_file())
        calls = self.calls()
        self.assertIn("systemctl restart telcoin", calls)
        self.assertIn("systemctl enable --now bench-node-sampler.service", calls)

    def test_baseline_boot_reports_vote_timeout_and_pre_subsecond(self):
        p, lines = self.run_remote("node-log-boot-baseline.txt")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(" sha=%s mhd=3000 nhd=1000 mbd=1000 vt=1500 forks=pre-subsecond max=" % FULL_SHA, lines[-1])

    def test_no_starting_line_fails(self):
        p, lines = self.run_remote("node-log-boot-nostart.txt")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertEqual(lines, ["POSTCFG_FAIL no 'telcoin-network <version> (<sha>) starting' line "
                                 "in docker logs since the restart"], p.stdout)
        self.assertFalse((self.node / "usr/local/bin/bench-node-sampler.sh").exists())

    def test_overrides_rewrite_the_yaml_in_place_and_a_rerun_starts_from_the_bak(self):
        script = self.script_for(BENCH_NODE_PARAM_OVERRIDES="0:min_header_delay=50ms,max_header_delay=250ms,vote_timeout=2s")
        original = self.yaml.read_text()
        for attempt in (1, 2):
            p, lines = self.run_remote("node-log-boot-good.txt", script)
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertIn(" max=250 min=50 batch=250 thr=5 vote=2000 filter=%s maxfiles=20" % FILTER, lines[-1])
            got = self.yaml.read_text().splitlines()
            want = [l.replace("max_header_delay: 500ms", "max_header_delay: 250ms  # bench-override")
                     .replace("min_header_delay: 250ms", "min_header_delay: 50ms  # bench-override")
                    for l in original.splitlines()] + ["vote_timeout: 2s  # bench-override"]
            self.assertEqual(got, want, attempt)
            self.assertEqual((self.datadir / "parameters.yaml.bak").read_text(), original, attempt)
            self.assertEqual(self.wrapper.read_text().count("--log.stdout.filter"), 1, attempt)

    def test_block_form_key_is_refused_before_the_restart(self):
        self.yaml.write_text(self.yaml.read_text().replace("max_header_delay: 500ms\n",
                                                           "max_header_delay:\n  secs: 0\n  nanos: 500000000\n"))
        before = self.yaml.read_text()
        p, lines = self.run_remote("node-log-boot-good.txt",
                                   self.script_for(BENCH_NODE_PARAM_OVERRIDES="0:max_header_delay=250ms"))
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertEqual(len(lines), 1, p.stdout)
        self.assertTrue(lines[0].startswith("POSTCFG_FAIL max_header_delay is a block (secs/nanos) in "), lines)
        self.assertEqual(self.yaml.read_text(), before)
        self.assertNotIn("systemctl restart telcoin", self.calls())


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
