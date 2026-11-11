"""benchmark/tests/gate.sh, the harness gate (bench 6, D41), fully offline.

Each test copies gate.sh into a temporary tree laid out like the repo (<tmp>/benchmark/tests/gate.sh) beside
stub test modules and a stub check_mutations.py, and puts a fake `ps` first on PATH that prints a canned
process list (GATE_STUB_PS), so the load check sees what the test says. The stubs record what ran in a state
directory: each stub module's name and the BENCH_TEST_TIMEOUT_SCALE it saw, and the checker's argv. One test
runs the gate with the real ps and checks that the gate never lists its own processes; two list this repo's
own cases (gate.sh --list, check_mutations.py --list), which runs nothing.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
GATE = TESTS / "gate.sh"
RESULT_RE = re.compile(r"^GATE unittest=(\S+) isolated=(\S+) mutations=(\S+) load=(quiet|loaded) secs=(\d+)$")

RECORD = '''import os
def record():
    with open(os.path.join(os.environ["GATE_STUB_STATE"], "ran"), "a") as fh:
        fh.write("%s %s\\n" % (__name__, os.environ.get("BENCH_TEST_TIMEOUT_SCALE", "-")))
'''
STUBS = {
    "pass": RECORD + '''import unittest
class T(unittest.TestCase):
    def test_ok(self):
        record()
''',
    # Fails on its first run in a tree, passes after: the load-sensitive module the isolated re-run is for.
    "flaky": RECORD + '''import unittest
class T(unittest.TestCase):
    def test_once(self):
        record()
        path = os.path.join(os.environ["GATE_STUB_STATE"], "count-" + __name__)
        n = int(open(path).read()) + 1 if os.path.exists(path) else 1
        open(path, "w").write(str(n))
        self.assertGreater(n, 1, "first run fails")
''',
    "fail": RECORD + '''import unittest
class T(unittest.TestCase):
    def test_broken(self):
        record()
        self.fail("always fails")
''',
    "noimport": RECORD + '''record()
raise ImportError("this stub module does not import")
''',
    "setupclass": RECORD + '''import unittest
class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        record()
        raise RuntimeError("setUpClass fails")
    def test_never(self):
        pass
''',
}
CHECKER = '''import os, sys
st = os.environ["GATE_STUB_STATE"]
with open(os.path.join(st, "checker-argv"), "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
if "--list" in sys.argv:
    print("  test_alpha.T.test_ok  stub.sh")
    print("1 mutation case(s)")
    sys.exit(0)
rc = int(os.environ.get("GATE_STUB_MUT_RC", "0"))
print("test_ok: " + ("mutation rejected by assertion" if rc == 0 else "survived: stub"))
print("\\n%d of 1 mutations killed" % (1 - min(rc, 1)))
print("  %-9s %-34s %s" % ("killed" if rc == 0 else "survived", "stub.sh", "test_alpha.T.test_ok"))
sys.exit(rc)
'''
FAKE_PS = '''#!/usr/bin/env bash
# A canned process list: GATE_STUB_PS names a file of "pid ppid args" lines (none: an idle host).
[ -z "${GATE_STUB_PS:-}" ] || cat "${GATE_STUB_PS}"
'''
CARGO = "4242 1 /opt/rust/.rustup/toolchains/stable/bin/cargo build --release -p tn-node\n"


class Tree(object):
    """<tmp>/benchmark/tests/{gate.sh, test_*.py stubs, check_mutations.py stub}, <tmp>/bin/ps, state and logs."""

    def __init__(self, modules):
        self._tmp = tempfile.TemporaryDirectory(prefix="gate-test-")
        self.root = Path(self._tmp.name)
        self.tests = self.root / "benchmark" / "tests"
        self.tests.mkdir(parents=True)
        shutil.copy2(str(GATE), str(self.tests / "gate.sh"))
        for name, kind in modules.items():
            (self.tests / (name + ".py")).write_text(STUBS[kind])
        (self.tests / "check_mutations.py").write_text(CHECKER)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "ps").write_text(FAKE_PS)
        (self.bin / "ps").chmod(0o755)
        self.state = self.root / "state"
        self.state.mkdir()
        self.ps_file = self.root / "ps.txt"
        self.ps_file.write_text("")

    def cleanup(self):
        self._tmp.cleanup()

    def env(self, extra):
        env = dict((k, v) for k, v in os.environ.items()
                   if not k.startswith(("GATE_", "BENCH_TEST_TIMEOUT_SCALE", "PYTHON")))
        env.update(PATH="%s:%s" % (self.bin, env.get("PATH", "/usr/bin:/bin")), GATE_STUB_STATE=str(self.state),
                   GATE_STUB_PS=str(self.ps_file), GATE_LOG_DIR=str(self.root / "logs"), TMPDIR=str(self.root))
        env.update(extra)
        return env

    def gate(self, *args, **extra):
        return subprocess.run(["bash", str(self.tests / "gate.sh")] + list(args), cwd=str(self.root),
                              env=self.env(extra), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=300)

    def ran(self):
        p = self.state / "ran"
        return [tuple(line.split()) for line in p.read_text().splitlines()] if p.exists() else []

    def checker_argv(self):
        p = self.state / "checker-argv"
        return p.read_text().splitlines() if p.exists() else []


class GateCase(unittest.TestCase):
    MODULES = {"test_alpha": "pass", "test_beta": "pass"}

    def setUp(self):
        self.t = Tree(self.MODULES)
        self.addCleanup(self.t.cleanup)

    def result(self, r):
        """The GATE line's fields; it must be the one GATE line and the last line of stdout."""
        lines = r.stdout.splitlines()
        self.assertEqual([l for l in lines if l.startswith("GATE")], lines[-1:], r.stdout + r.stderr)
        m = RESULT_RE.match(lines[-1])
        self.assertIsNotNone(m, lines[-1])
        return dict(zip(("unittest", "isolated", "mutations", "load", "secs"), m.groups()))


class LoadTests(GateCase):
    def assertRefused(self, ps_lines):
        self.t.ps_file.write_text(ps_lines)
        r = self.t.gate()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        res = self.result(r)
        self.assertEqual((res["unittest"], res["isolated"], res["mutations"], res["load"]), ("-", "none", "-", "loaded"))
        self.assertIn("refused", r.stderr)
        self.assertIn("--under-load", r.stderr)
        self.assertEqual(self.t.ran(), [], "no module may run on a loaded host")
        self.assertEqual(self.t.checker_argv(), [])
        return r

    def test_a_cargo_build_refuses_the_gate_and_is_named(self):
        r = self.assertRefused(CARGO + "7 1 /usr/sbin/sshd -D\n")
        self.assertIn("4242 /opt/rust/.rustup/toolchains/stable/bin/cargo build --release -p tn-node", r.stdout)
        self.assertNotIn("sshd", r.stdout)

    def test_every_kind_of_load_refuses(self):
        for line in ("5 1 /usr/local/bin/rustc --crate-name tn_node --edition=2021 crates/node/src/lib.rs",
                     "5 1 /opt/rust/.cargo/bin/cargo-nextest nextest run -p tn-primary",
                     "5 1 cargo check --locked",
                     "5 1 bash benchmark/benchmark-blast.sh run --yes",
                     "5 1 /bin/bash /repo/benchmark/benchmark-deploy.sh --yes --to 12",
                     "5 1 bash ./benchmark-teardown.sh --yes",
                     "5 1 bash benchmark/benchmark-probe.sh all",
                     "5 1 bash benchmark/launch/launch.sh benchmark/launch/bench6-run1.env deploy12",
                     "5 1 bash /repo/benchmark/launch/run-arms.sh",
                     "5 1 bash benchmark/tools/params-apply.sh --arm-file benchmark/arms/v-vote.arm",
                     "5 1 python3 benchmark/tests/check_mutations.py",
                     "5 1 /usr/bin/python3.12 /repo/benchmark/tests/check_mutations.py --jobs 4",
                     "5 1 bash /other/benchmark/tests/gate.sh"):
            with self.subTest(line=line):
                self.assertRefused(line + "\n")

    def test_what_does_not_load_the_host_does_not_refuse(self):
        idle = ("11 1 /opt/rust/.cargo/bin/sccache\n"                         # the cache daemon, idle
                "12 1 /bin/bash -c source snap.sh && eval 'cargo build -p x'\n"  # a shell's text, not cargo
                "13 1 vim benchmark/tests/gate.sh\n"
                "14 1 grep -n cargo notes.md\n"
                "15 1 tail -f benchmark/results/r1/benchmark-blast.log\n"
                "16 1 python3 -m unittest discover -s benchmark/tests\n"
                "17 1 [kworker/3:1-events]\n")
        self.t.ps_file.write_text(idle)
        r = self.t.gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.result(r)["load"], "quiet")

    def test_under_load_runs_and_the_result_line_says_loaded(self):
        self.t.ps_file.write_text(CARGO)
        r = self.t.gate("--under-load")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = self.result(r)
        self.assertEqual((res["unittest"], res["isolated"], res["mutations"], res["load"]), ("0", "none", "0", "loaded"))
        self.assertEqual(sorted(m for m, _ in self.t.ran()), ["test_alpha", "test_beta"])

    def test_a_job_that_starts_during_the_run_makes_it_loaded(self):
        # The stub checker starts "cargo": the check after the mutations sees it.
        (self.t.tests / "check_mutations.py").write_text(
            CHECKER.replace("sys.exit(rc)\n", "open(os.environ['GATE_STUB_PS'], 'w').write(%r)\nsys.exit(rc)\n" % CARGO))
        r = self.t.gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.result(r)["load"], "loaded")
        self.assertIn("the host is loaded (after the mutations)", r.stdout)

    def test_the_gate_never_lists_its_own_processes(self):
        # The real ps: whatever else runs on this host, nothing under this tree may be listed.
        shutil.rmtree(str(self.t.bin))
        self.t.bin.mkdir()
        r = self.t.gate("--under-load")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        listed = [l for l in r.stdout.splitlines() if l.startswith("  ") and str(self.t.root) in l]
        self.assertEqual(listed, [], r.stdout)


class OutcomeTests(GateCase):
    def test_all_green_on_a_quiet_host(self):
        r = self.t.gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = self.result(r)
        self.assertEqual((res["unittest"], res["isolated"], res["mutations"], res["load"]), ("0", "none", "0", "quiet"))
        self.assertEqual(sorted(self.t.ran()), [("test_alpha", "3"), ("test_beta", "3")])
        self.assertEqual(self.t.checker_argv(), ["--jobs 1"])

    def test_a_caller_set_timeout_scale_is_kept(self):
        r = self.t.gate(BENCH_TEST_TIMEOUT_SCALE="5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(self.t.ran()), [("test_alpha", "5"), ("test_beta", "5")])

    def test_surviving_mutations_fail_the_gate(self):
        r = self.t.gate(GATE_STUB_MUT_RC="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        res = self.result(r)
        self.assertEqual((res["unittest"], res["isolated"], res["mutations"]), ("0", "none", "1"))
        self.assertIn("survived", r.stdout)

    def test_jobs_reach_the_checker(self):
        r = self.t.gate("--jobs", "4")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.t.checker_argv(), ["--jobs 4"])
        r = self.t.gate(GATE_MUTATION_JOBS="3")
        self.assertEqual(self.t.checker_argv()[-1], "--jobs 3")
        for bad in ("0", "x", ""):
            r = self.t.gate("--jobs", bad)
            self.assertEqual(r.returncode, 2, bad)

    def test_an_unknown_argument_is_refused(self):
        r = self.t.gate("--bogus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown argument", r.stderr)
        self.assertEqual(self.t.ran(), [])


class IsolatedTests(GateCase):
    MODULES = {"test_alpha": "pass", "test_flaky": "flaky", "test_zeta": "flaky"}

    def test_a_module_that_passes_alone_passes_the_gate(self):
        r = self.t.gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = self.result(r)
        self.assertEqual((res["unittest"], res["isolated"], res["mutations"]), ("1", "test_flaky:0,test_zeta:0", "0"))
        # the suite once, then each failed module alone once; the passing module never again
        self.assertEqual(sorted(m for m, _ in self.t.ran()), ["test_alpha", "test_flaky", "test_flaky",
                                                             "test_zeta", "test_zeta"])
        self.assertTrue((self.t.root / "logs" / "isolated-test_flaky.log").is_file())


class IsolatedFailTests(GateCase):
    MODULES = {"test_alpha": "pass", "test_broken": "fail", "test_flaky": "flaky", "test_noimport": "noimport",
               "test_setup": "setupclass"}

    def test_a_module_that_fails_alone_fails_the_gate_and_each_is_named(self):
        r = self.t.gate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        res = self.result(r)
        self.assertEqual(res["unittest"], "1")
        self.assertEqual(res["isolated"], "test_broken:1,test_flaky:0,test_noimport:1,test_setup:1")
        self.assertEqual(res["mutations"], "0", "the checker runs even when the suite failed")


class ListAndModulesTests(GateCase):
    MODULES = {"test_alpha": "pass", "test_beta": "pass", "test_gamma": "fail"}

    def test_list_prints_the_plan_and_runs_nothing_even_under_load(self):
        self.t.ps_file.write_text(CARGO)
        r = self.t.gate("--list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for want in ("  test_alpha", "  test_beta", "  test_gamma", "BENCH_TEST_TIMEOUT_SCALE=3", "once more alone",
                     "check_mutations.py --jobs 1", "  test_alpha.T.test_ok  stub.sh", "1 mutation case(s)"):
            self.assertIn(want, r.stdout)
        self.assertNotIn("GATE ", r.stdout)
        self.assertEqual(self.t.ran(), [])
        self.assertEqual(self.t.checker_argv(), ["--list --jobs 1"])

    def test_modules_runs_only_those_and_narrows_the_checker(self):
        r = self.t.gate("--modules", "alpha,test_beta.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(m for m, _ in self.t.ran()), ["test_alpha", "test_beta"])
        self.assertEqual(self.t.checker_argv(), ["--jobs 1 --modules test_alpha,test_beta"])
        self.assertEqual(self.result(r)["unittest"], "0")

    def test_modules_with_a_failing_module(self):
        r = self.t.gate("--modules=gamma")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.result(r)["isolated"], "test_gamma:1")
        self.assertEqual(sorted(m for m, _ in self.t.ran()), ["test_gamma", "test_gamma"])

    def test_list_with_modules(self):
        r = self.t.gate("--list", "--modules", "beta")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 module(s)", r.stdout)
        self.assertNotIn("  test_alpha\n", r.stdout)
        self.assertEqual(self.t.checker_argv(), ["--list --jobs 1 --modules test_beta"])

    def test_an_unknown_module_is_refused(self):
        r = self.t.gate("--modules", "alpha,nosuch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no module test_nosuch", r.stderr)
        self.assertEqual(self.t.ran(), [])


class RealCheckerListTests(unittest.TestCase):
    """The repo's own gate.sh and check_mutations.py, --list only (nothing runs)."""

    def run_list(self, *args):
        env = dict((k, v) for k, v in os.environ.items() if not k.startswith("GATE_"))
        return subprocess.run(["bash", str(GATE), "--list"] + list(args), env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)

    def test_list_names_every_module_and_case(self):
        r = self.run_list()
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in sorted(TESTS.glob("test_*.py")):
            self.assertIn("  %s\n" % f.stem, r.stdout)
        n = int(re.search(r"^(\d+) mutation case\(s\)$", r.stdout, re.M).group(1))
        self.assertGreater(n, 300)

    def test_list_narrowed_to_one_module(self):
        # The checker alone: the module's file need not be beside it (check_mutations copies only this one).
        r = subprocess.run(["python3", str(TESTS / "check_mutations.py"), "--list", "--modules", "keygen"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("test_keygen.ReuseTests.test_reuse_refuses_another_address  devnet-keygen.sh", r.stdout)
        self.assertIn("\n1 mutation case(s)", r.stdout)


if __name__ == "__main__":
    unittest.main()
