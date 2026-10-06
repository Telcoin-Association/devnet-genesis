"""bench_iap_scp_down (bench-lib.sh): collect's IAP copy retries only a refused tunnel, fully offline.

The function is cut out of bench-lib.sh by name and run under bash against
fixtures/teardown/fake-gcloud.py, whose `compute scp` plays a scripted outcome per attempt
(FAKE_SCP: ok, an IAP refusal 4003/4033/4047, or any other failure; a failing attempt leaves a
partial file), a perl stub that records each attempt's alarm, and a sleep stub that records the
backoff instead of waiting.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
FIX = TESTS / "fixtures" / "teardown"
LIB = (BENCH / "bench-lib.sh").read_text()


def shell_function(source, name):
    """The text of shell function <name> in <source>: a block ending in a column-0 brace, or one line."""
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.M | re.S) \
        or re.search(r"^%s\(\) \{ .*\}\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("function %s not found" % name)
    return m.group()


SCRIPT = "set -euo pipefail\n" + shell_function(LIB, "bench_warn") + shell_function(LIB, "bench_iap_scp_down") \
    + 'bench_iap_scp_down bench-validator-03 australia-southeast1-c /var/lib/bench-sampler/x.csv "$1"\n'


class ScpRetryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="scp-retry-")
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.state = self.root / "state"
        self.bin.mkdir()
        self.state.mkdir()
        for name, src in (("gcloud", "fake-gcloud.py"), ("perl", "stub-perl.sh"), ("sleep", "stub-sleep.sh")):
            shutil.copyfile(str(FIX / src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.dest = self.root / "sampler" / "bench-validator-03.csv"
        self.dest.parent.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def scp(self, outcomes, **extra):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.root), "FAKE_ROOT": str(self.state),
               "FAKE_SCP": outcomes, "PROJECT_ID": "acme-project"}
        env.update(extra)
        # Data waiting on stdin: an attempt that is not given </dev/null would read it.
        return subprocess.run(["bash", "-c", SCRIPT, "t", str(self.dest)], env=env, input="LEAK-STDIN\n",
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def attempts(self):
        p = self.state / "calls.jsonl"
        calls = [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []
        for c in calls:
            self.assertEqual(c["argv"][:2], ["compute", "scp"])
            self.assertEqual(c["stdin"], "", "an attempt read stdin")
            self.assertIn("--tunnel-through-iap", c["argv"])
            self.assertEqual(c["argv"][3], str(self.dest) + ".part", "the copy lands beside the file first")
        return calls

    def reset(self):
        for name in ("scp-attempts", "calls.jsonl", "sleeps", "alarms"):
            if (self.state / name).exists():
                (self.state / name).unlink()

    def recorded(self, name):
        p = self.state / name
        return p.read_text().split() if p.exists() else []

    def test_refused_tunnel_is_retried_with_backoff(self):
        p = self.scp("4033,4033,ok")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.attempts()), 3)
        self.assertEqual(self.recorded("sleeps"), ["10", "20"])
        self.assertEqual(self.recorded("alarms"), ["300", "gcloud"] * 3)
        self.assertEqual(self.dest.read_text(), "copied from bench-validator-03:/var/lib/bench-sampler/x.csv\n")
        self.assertFalse(Path(str(self.dest) + ".part").exists())
        self.assertEqual(p.stderr.count("IAP refused the tunnel"), 2)

    def test_each_transient_iap_code_is_retried(self):
        for code in ("4003", "4033", "4047"):
            with self.subTest(code=code):
                self.reset()
                p = self.scp(code + ",ok")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(len(self.attempts()), 2)

    def test_other_failures_are_not_retried(self):
        p = self.scp("fail")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(len(self.attempts()), 1)
        self.assertEqual(self.recorded("sleeps"), [])
        self.assertIn("exited with return code", p.stderr)
        self.assertFalse(self.dest.exists())
        self.assertFalse(Path(str(self.dest) + ".part").exists())

    def test_gives_up_after_the_retry_budget(self):
        p = self.scp("4033")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(len(self.attempts()), 3)
        self.assertEqual(self.recorded("sleeps"), ["10", "20"])
        self.assertFalse(Path(str(self.dest) + ".part").exists())

    def test_retry_budget_is_a_knob(self):
        p = self.scp("4033", BENCH_IAP_RETRIES="1")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(len(self.attempts()), 1)
        self.assertEqual(self.recorded("sleeps"), [])
        self.reset()
        p = self.scp("4033,4033,4033,4033,ok", BENCH_IAP_RETRIES="bogus")
        self.assertEqual(len(self.attempts()), 3, "an invalid budget falls back to 3")
        self.assertIn("BENCH_IAP_RETRIES='bogus' is not a positive integer", p.stderr)

    def test_failed_copy_never_replaces_an_earlier_one(self):
        self.dest.write_text("an earlier complete copy\n")
        p = self.scp("4033,4033,4033")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.dest.read_text(), "an earlier complete copy\n")
        self.assertFalse(Path(str(self.dest) + ".part").exists())


if __name__ == "__main__":
    unittest.main()
