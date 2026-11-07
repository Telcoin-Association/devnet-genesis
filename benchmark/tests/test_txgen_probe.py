"""bench_txgen_cli_probe (bench-lib.sh): the blaster image's `blast --help` against the CLI contract, offline.

What runs is the real bench-lib.sh, sourced the way benchmark-deploy.sh sources it: a temporary copy of the
scripts it loads (TREE), `$0` = benchmark-deploy.sh (benchmark/config.sh only loads for its allowlisted
callers), the function's name and arguments saved before the source (a sourced file may reuse the positional
parameters), and a clean environment. `docker` and `gcloud` on PATH are fakes (fixtures/txgen-probe/stub-*.sh):
docker answers `info` and `login`, and `run ... blast --help` prints a canned help text; gcloud prints a token.
Every call is logged.

Bench 5: with BENCH_LANDINGS_SAMPLE > 0 the blasters get `--landings-out --landings-sample`, so the probe
requires those two flags too, and a bench-4 image fails in preflight rather than on its VM. With the knob unset
or 0 the probe is bench 4's: the same flags, the same docker calls, the same line.

fixtures/txgen-probe/blast-help-bench4.txt is the help text of the bench-4 generator (its clap definitions);
blast-help-landings.txt is the same text with the two landings flags of the bench-5 generator added.
"""
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIX = TESTS / "fixtures" / "txgen-probe"

# Scripts the bash under test sources, relative to the repo root (bench-lib.sh refuses to load without
# pull-lib.sh and obs-lib.sh).
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/obs-lib.sh")
IMAGE = "registry.invalid/txgen/tn-transaction-generator:blast-v2-abcdef1"
HELP_BENCH4 = FIX / "blast-help-bench4.txt"
HELP_LANDINGS = FIX / "blast-help-landings.txt"
# The probe's success line, as bench 4 printed it.
OK_LINE = "    ✓ %s blast --help carries every contract flag (incl. --stdout-json)\n" % IMAGE
# The calls of one probe, as bench 4 made them (<cfg> = the throwaway --config dir): the docker calls in
# order, and the token gcloud prints into the login (the two run as one pipeline, so their log order varies).
BENCH4_CALLS = (["docker info",
                 "docker --config <cfg> login -u oauth2accesstoken --password-stdin https://registry.invalid",
                 "docker --config <cfg> run --rm --platform linux/amd64 %s blast --help" % IMAGE],
                ["gcloud auth print-access-token"])

# <tree>/benchmark <fn> <args...>: one bench-lib.sh function with its arguments, saved before the source.
LIB_CALL = r'''
set -euo pipefail
lib="$1"; shift
argv=("$@")
source "$lib/bench-lib.sh"
"${argv[@]}"
'''


class TxgenProbeTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="txgen-probe-test-")
        self.root = Path(self._tmp.name)
        for rel in TREE:
            dst = self.root / "tree" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / rel), str(dst))
        self.bench = self.root / "tree" / "benchmark"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("docker", "gcloud"):
            shutil.copyfile(str(FIX / ("stub-%s.sh" % name)), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.log = self.root / "stub-calls.txt"
        self.log.write_text("")
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.params = self.root / "consensus-params.yaml"
        self.params.write_text("max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n")

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, help_file, **extra):
        # Nothing from the developer's shell that the scripts read (BENCH_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "LC_ALL": "C",
               "BENCH_RUN_ID": "rtest-txgen-probe", "BENCH_APPLY": "0", "BENCH_TXGEN_SHA": "abcdef1",
               "BENCH_TXGEN_IMAGE": IMAGE, "BENCH_PARAMETERS_FILE": str(self.params),
               "STUB_LOG": str(self.log), "STUB_HELP": str(help_file)}
        env.update({k: v for k, v in extra.items() if v is not None})
        return env

    def probe(self, help_file, **env):
        # $0 = benchmark-deploy.sh: config.sh only loads for its allowlisted callers.
        return subprocess.run(["bash", "-c", LIB_CALL, "benchmark-deploy.sh", str(self.bench), "bench_txgen_cli_probe"],
                              env=self.env(help_file, **env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=120, universal_newlines=True, errors="replace")

    def calls(self):
        """(docker calls in order, gcloud calls in order), each argv's words joined by single spaces."""
        docker, gcloud = [], []
        for line in self.log.read_text().splitlines():
            words = line.split(" ")
            if words[:2] == ["docker", "--config"] and len(words) > 2:
                words[2] = "<cfg>"
            (docker if words[0] == "docker" else gcloud).append(" ".join(words))
        return docker, gcloud

    def test_default_is_the_bench_4_probe_byte_for_byte(self):
        """(1) Knob unset, and 0: the bench-4 image passes, with bench 4's docker calls and its line, nothing else."""
        for value in (None, "0"):
            with self.subTest(BENCH_LANDINGS_SAMPLE=value):
                self.log.write_text("")
                p = self.probe(HELP_BENCH4, BENCH_LANDINGS_SAMPLE=value)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(p.stdout, OK_LINE)
                self.assertEqual(p.stderr, "")
                self.assertEqual(self.calls(), BENCH4_CALLS)

    def test_sampled_landings_refuse_a_bench_4_image_naming_both_flags(self):
        """(2) BENCH_LANDINGS_SAMPLE=100 with the bench-4 help: bench_die names the two missing flags, no ✓ line."""
        p = self.probe(HELP_BENCH4, BENCH_LANDINGS_SAMPLE="100")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("✓", p.stdout)
        self.assertIn("❌ %s 'blast --help' lacks: --landings-out --landings-sample (or the image could not be run; "
                      "BENCH_SKIP_CLI_PROBE=1 to skip)" % IMAGE, p.stderr)
        # The contract flags of bench 4 are all there: only the two landings flags are named.
        lacks = [l for l in p.stderr.splitlines() if "lacks:" in l]
        self.assertEqual(len(lacks), 1, p.stderr)
        self.assertEqual(lacks[0].split("lacks:")[1].split(" (")[0].split(), ["--landings-out", "--landings-sample"])
        self.assertEqual(self.calls(), BENCH4_CALLS)

    def test_sampled_landings_pass_an_image_with_both_flags(self):
        """(3) BENCH_LANDINGS_SAMPLE=100 with a help text that lists both flags: the probe passes, same line."""
        p = self.probe(HELP_LANDINGS, BENCH_LANDINGS_SAMPLE="100")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout, OK_LINE)
        self.assertEqual(p.stderr, "")
        self.assertEqual(self.calls(), BENCH4_CALLS)

    def test_the_fixtures_differ_only_by_the_two_landings_flags(self):
        """The two help texts are the same image's but for the bench-5 flags, so (2) and (3) test just those."""
        old = HELP_BENCH4.read_text().splitlines()
        new = HELP_LANDINGS.read_text().splitlines()
        diff = [l for l in difflib.ndiff(old, new) if l[:1] in "+-"]
        self.assertEqual([l for l in diff if l.startswith("-")], [], "the bench-5 text drops a line")
        self.assertEqual([l[2:].split()[0] for l in diff if l.startswith("+       --")],
                         ["--landings-out", "--landings-sample"])
        self.assertNotIn("--landings", HELP_BENCH4.read_text())


if __name__ == "__main__":
    unittest.main()
