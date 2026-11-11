"""benchmark-probe.sh (the one-VM GCE probe driver) and tools/build-probe-bin.sh, offline.

Three kinds of gcloud stand in for the real one:
- a shim that prints REACHED and exits 9: `plan` and every subcommand under --dry-run must never call it;
- fixtures/probe/fake-gcloud.py: instances and disks with labels in a JSON state file, ssh that answers
  the readiness probe (and, with FAKE_VM_DIR, each remote script by its header line, playing the VM),
  scp that can be told to fail; every call logged. The live paths (`down`, `all` through three arms,
  `all` after a failed run or a TERM, `up` beside a fleet) run against it in a copy of the repo tree,
  so nothing is written under the real benchmark/results/;
- none at all for the static checks on the driver's source (every GCP call behind the dry-run guard,
  a deadline on every loop, no list-flag value starting with ^, hygiene).

The golden plan is fixtures/probe/plan-default.txt: the plan of the default arm list with the project id
replaced by <project> and every block bench-lib.sh renders (between "# >>> bench-lib:" and
"# <<< bench-lib:") collapsed. PROBE_UPDATE_GOLDEN=1 rewrites it.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
DRIVER = BENCH / "benchmark-probe.sh"
BUILD = BENCH / "tools" / "build-probe-bin.sh"
FIX = TESTS / "fixtures" / "probe"
GOLDEN = FIX / "plan-default.txt"
FAKE_GCLOUD = FIX / "fake-gcloud.py"
PROJECT = "tn-" + "devnet"
RUN = "r20991231-0101"
INST = "bench-probe-" + RUN
GUARD = '[ "${DRY}" = "0" ] || return 0'
# The nineteen arms of benchmark/private/bench6-prep/I-1r/gce-arms.md §2, in run order, and its "never cut" eight.
ALL_ARMS = ["g0-baseline", "g1-node", "g2-readall", "g3-ra16-readall", "g4-mrand", "g4-mrand-readall", "g5-7default",
            "g5-7pfoff", "g5-7pfoff-mrand", "g6-peer", "g6-peer-nr", "g6-peer-mrand", "g7-ovf64", "g7-ovf64-mrand",
            "g7-ovf8", "g7-longreader", "g8-nowritemap", "g8-nowritemap-readall", "g9-sampler"]
CORE = ["g0-baseline", "g1-node", "g5-7default", "g5-7pfoff", "g6-peer", "g6-peer-nr", "g7-ovf64", "g9-sampler"]
# The driver's table, column by column: name -> (host step, sampler cadence, probe flags as written).
TABLE = dict((m.group(1), (m.group(2), m.group(3), m.group(4))) for m in re.finditer(
    r'(?m)^    "(g\d-[a-z0-9-]+)\|([^|]+)\|([^|]+)\|([^"]+)"$', DRIVER.read_text()))
RA16 = [n for n in ALL_ARMS if TABLE[n][0] == "ra16"]
SAFETY = [n for n in ALL_ARMS if TABLE[n][1] == "safety"]

_spec = importlib.util.spec_from_file_location("repo_hygiene", str(TESTS / "test_repo_hygiene.py"))
HYG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HYG)


def shim_dir(tmp):
    """A bin dir whose gcloud prints REACHED (stdout and stderr), leaves a mark, and exits 9."""
    d = Path(tmp) / "shim"
    d.mkdir()
    hits = Path(tmp) / "hits"
    (d / "gcloud").write_text("#!/bin/sh\necho REACHED >> '%s'\necho REACHED\necho REACHED >&2\nexit 9\n" % hits)
    (d / "gcloud").chmod(0o755)
    return d, hits


def run_driver(driver, args, path_dir, timeout=300, **env):
    e = dict(os.environ)
    e.update({"PATH": str(path_dir) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "BENCH_RUN_ID": RUN})
    e.update(env)
    return subprocess.run(["bash", str(driver)] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True, env=e, timeout=timeout)


def normalize(text):
    text = text.replace(PROJECT, "<project>")
    return re.sub(r"(?s)(# >>> bench-lib: [^\n]*\n).*?(# <<< bench-lib: [^\n]*\n)",
                  lambda m: m.group(1) + "<rendered by bench-lib.sh>\n" + m.group(2), text)


def remote_blocks(text):
    """{label: body} of every remote script the plan prints (the last one wins for a repeated label)."""
    return dict(re.findall(r"(?s)----- remote script (\S+) -----\n(.*?)\n----- end \1 -----", text))


class DryRunTests(unittest.TestCase):
    """The real tree, dry: nothing may be written or called."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="probe-dry-")
        cls.shim, cls.hits = shim_dir(cls._tmp.name)
        cls.results = BENCH / "results" / RUN
        assert not cls.results.exists(), "%s exists; the dry-run tests need it absent" % cls.results
        cls.plan = run_driver(DRIVER, ["plan"], cls.shim)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assert_before(self, text, first, then):
        """Both occur in text and `first` occurs first: a missing one fails here, at an assertion, not in str.index."""
        self.assertIn(first, text)
        self.assertIn(then, text)
        self.assertLess(text.index(first), text.index(then))

    def test_plan_matches_the_golden_file(self):
        p = self.plan
        self.assertEqual(p.returncode, 0, p.stderr)
        got = normalize(p.stdout)
        if os.environ.get("PROBE_UPDATE_GOLDEN") == "1":
            GOLDEN.write_text(got)
        self.assertEqual(got, GOLDEN.read_text())

    def test_plan_and_every_dry_subcommand_reach_no_gcloud(self):
        runs = [("plan",), ("up", "--dry-run"), ("run", "--dry-run"), ("collect", "--dry-run"), ("down", "--dry-run"),
                ("all", "--dry-run"), ("down", "--dry-run", "--keep"), ("all", "--dry-run", "--arms", "g3,g9")]
        for args in runs:
            with self.subTest(args=args):
                p = run_driver(DRIVER, list(args), self.shim)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertNotIn("REACHED", p.stdout + p.stderr)
                self.assertFalse(self.hits.exists())
                self.assertFalse(self.results.exists(), "a dry run wrote %s" % self.results)
                self.assertIn("dry run: no gcloud call is made", p.stdout)

    def test_the_plan_names_every_step(self):
        out = self.plan.stdout
        steps = ["gcloud auth print-access-token", "compute images describe ubuntu-2404-noble-amd64-v20261105 --project=ubuntu-os-cloud",
                 "compute regions describe us-west2", "compute firewall-rules list", "compute disks create " + INST,
                 "compute instances create " + INST, "compute scp", "remote script setup", "remote script host-probe",
                 "compute instances delete " + INST, "compute disks delete " + INST, "== plan complete"]
        pos = [out.index(s) for s in steps]
        self.assertEqual(pos, sorted(pos))
        blocks = remote_blocks(out)
        for name in ALL_ARMS:
            for part in ("start", "wait", "finish"):
                self.assertIn("arm-%s-%s" % (name, part), blocks)
            self.assertIn("compute scp %s:/var/tmp/bench-probe-%s.tar.gz benchmark/results/%s/probe/arms/%s.tar.gz"
                          % (INST, name, RUN, name), out)
        # The fleet's exact shape, the pinned image, the run's labels; no service account, no external IP.
        create = re.search(r"compute instances create [^\n]*", out).group(0)
        for want in ("--machine-type=c3-highcpu-8", "no-address", "--no-service-account", "--labels=benchmark=1\\,network=bench\\,"
                     "bench-run=%s\\,tn-role=probe" % RUN, "boot=yes\\,auto-delete=yes"):
            self.assertIn(want, create)
        disk = re.search(r"compute disks create [^\n]*", out).group(0)
        for want in ("--type=hyperdisk-balanced", "--size=100GB", "--provisioned-iops=20000", "--provisioned-throughput=800",
                     "--image=projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105"):
            self.assertIn(want, disk)

    def test_arm_commands(self):
        b = remote_blocks(self.plan.stdout)
        cmd = {n: re.search(r"(?m)^/var/lib/bench-probe/bin/mdbx-writeback-probe (.*) > \"\$A/probe.log\"", b["arm-%s-start" % n]).group(1)
               for n in ALL_ARMS}
        quiet = "--quiet-secs 10 --quiet-max-mbps 2 --quiet-retries 6 --quiet-wait-secs 20 --require-quiet"
        a7 = "--arm 7 --preload-gb 0.05 --txs 2000 --outputs 240 --warmup 40 --pause-ms 500 --reader-hold 10"
        self.assertTrue(cmd["g0-baseline"].startswith("--arm 1 --preload-gb 6 --outputs 40 --warmup 3 " + quiet + " --tag g0-baseline"))
        a7n = "--arm 7 --preload-gb 0.05 --txs 6500 --outputs 150 --warmup 30 --pause-ms 1000 --reader-hold 20"
        self.assertEqual(list(TABLE), ALL_ARMS)
        self.assertEqual((RA16, SAFETY), (["g3-ra16-readall"], ["g9-sampler"]))
        self.assertTrue(cmd["g1-node"].startswith(a7n + " --overflow-per-tx 0.05 " + quiet))
        self.assertIn("--arm 5 --preload-gb 6 --outputs 40 --warmup 3 --cache-prep readused", cmd["g4-mrand-readall"])
        self.assertTrue(cmd["g5-7default"].startswith(a7 + " " + quiet))
        self.assertIn(a7 + " --peer-open-at 60 --peer-nordahead", cmd["g6-peer-nr"])
        self.assertIn(a7 + " --overflow-per-tx 0.001 --overflow-value 258000 --madvise-random", cmd["g7-ovf64-mrand"])
        self.assertIn(a7 + " --overflow-per-tx 0.05 --long-reader-at 60 --long-reader-for 60", cmd["g7-longreader"])
        self.assertIn("--arm 3 --preload-gb 6 --outputs 40 --warmup 3 --cache-prep readused", cmd["g8-nowritemap-readall"])
        self.assertIn(a7 + " --keep-db", cmd["g9-sampler"])
        for n in ALL_ARMS:
            self.assertIn("--tag %s --data-dir /var/lib/bench-probe/data --results-dir $A/results --disk \"$1\"" % n, cmd[n])
        # Every arm sets its read_ahead_kb before it starts: g2 16, the others the boot value (128 in the plan);
        # only g2's finish puts the boot value back.
        step = re.compile(r'hsok\(\)\{ echo "HOST_STEP %s read-ahead-kb (\d+) ' % INST)
        for n in ALL_ARMS:
            s, f = b["arm-%s-start" % n], b["arm-%s-finish" % n]
            want = 16 if TABLE[n][0] == "ra16" else 128
            self.assertEqual(step.findall(s), [str(want)], n)
            self.assert_before(s, '[ "$HOST_STEP_RC" = 0 ] || ', "--unit=bench-probe-sampler-" + n)
            self.assertEqual(step.findall(f), ["128"] if TABLE[n][0] == "ra16" else [], n)
            # The finish removes this arm's DB files by name (never a tree, never another arm's) before the tar.
            rm = 'rm -f -- "$D/mdbx.dat" "$D/mdbx.lck" "$D/probe-meta.txt" "$B/data/%s.appender.log"' % n
            self.assertIn("D=/var/lib/bench-probe/data/%s\n" % n, f)
            self.assert_before(f, "systemctl stop bench-probe-arm-" + n, rm)
            self.assert_before(f, rm, "tar -C")
            self.assertNotIn("rm -rf", s + f)
        # The sampler points at the arm's DB and pid file; g7 polls every 5 s and runs the census check.
        for n in ALL_ARMS:
            s = b["arm-%s-start" % n]
            self.assertIn("PERSIST_PID_FILE=$A/probe.pid PERSIST_MDBX_FILE=/var/lib/bench-probe/data/%s/mdbx.dat" % n, s)
            self.assert_before(s, "--unit=bench-probe-sampler-" + n, "--unit=bench-probe-arm-" + n)
        g7 = b["arm-%s-start" % SAFETY[0]]
        self.assertIn("PERSIST_INTERVAL_SECS=5 PERSIST_MDBX_EVERY_SECS=5", g7)
        self.assertIn("PERSIST_CENSUS_EVERY_SECS=5", g7)
        self.assertIn('bash "$A/safety.sh" live "$p"', g7)
        self.assertIn('bash "$A/safety.sh" quiet', g7)
        self.assertIn("for i in 1 2 3 4 5; do", g7)
        self.assertIn('python3 "$C" --file "$F" --pid "$p" --header', g7)
        # The census's own start-up reads (python3, its modules, fincore) happen before read_bytes is counted.
        self.assert_before(g7, 'python3 "$C" --file "$C" --header', 'io0="$(rb)"')
        self.assertNotIn("safety.sh", b["arm-g5-7default-start"])

    def test_arm_selection(self):
        cases = [("g0,g5-7pfoff", ["g0-baseline", "g5-7pfoff"]), ("g4,g0", ["g0-baseline", "g4-mrand", "g4-mrand-readall"]),
                 ("g6", ["g6-peer", "g6-peer-nr", "g6-peer-mrand"]), ("g8,g9-sampler", ALL_ARMS[-3:]),
                 ("core", CORE), ("core,g2-readall", [n for n in ALL_ARMS if n in CORE or n == "g2-readall"]),
                 ("g9,core", CORE)]
        for arg, want in cases:
            with self.subTest(arms=arg):
                p = run_driver(DRIVER, ["plan", "--arms", arg], self.shim)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("arms (%d):" % len(want), p.stdout)
                self.assertEqual(re.findall(r"(?m)^== arm (\S+):", p.stdout), want)
        p = run_driver(DRIVER, ["plan", "--arms", "g0,g10"], self.shim)
        self.assertEqual(p.returncode, 2)
        self.assertIn("'g10' is not an arm, a group (g0..g9) or core", p.stderr)
        self.assertFalse(self.hits.exists())

    def test_deadlines_in_the_rendered_scripts(self):
        for secs, out in ((900, self.plan.stdout), (300, run_driver(DRIVER, ["plan", "--arm-deadline-secs", "300"], self.shim).stdout)):
            b = remote_blocks(out)
            for n in ALL_ARMS:
                s = b["arm-%s-start" % n]
                self.assertIn("( sleep %d; if kill -0 \"$p\"" % secs, s)
                self.assertIn("--unit=bench-probe-arm-%s --collect --quiet -p RuntimeMaxSec=%d " % (n, secs + 300), s)
                self.assertIn("--unit=bench-probe-sampler-%s --collect --quiet -p RuntimeMaxSec=%d " % (n, secs + 600), s)
            self.assertIn("deadlines: run 120 min, arm %d s, ssh ready 300 s, delete 300 s each" % secs, out)
        # Every remote loop ends by time; every remote wait is bounded by timeout.
        norm = normalize(self.plan.stdout)
        for label, body in remote_blocks(norm).items():
            for m in re.finditer(r"(?m)^\s*while (.*)$", body):
                tail = body[m.start():m.start() + 1200]
                self.assertRegex(tail, r'-lt (300|"\$e")|"\$e" -lt 300|"\$n" -lt 300', label)
        setup = remote_blocks(norm)["setup"]
        self.assertIn("timeout 300 cloud-init status --wait", setup)
        self.assertIn("timeout 300 systemctl is-system-running --wait", setup)
        # Every session and every gcloud call has a local alarm.
        for line in self.plan.stdout.splitlines():
            if line.startswith("  + "):
                self.assertRegex(line, r"^  \+ \[alarm \d+s( x3)?\] gcloud ", line)


class SourceTests(unittest.TestCase):
    """Static checks on the driver's text."""

    def setUp(self):
        self.src = DRIVER.read_text()
        self.lines = self.src.splitlines()

    def test_every_gcp_call_sits_behind_the_dry_guard(self):
        call = re.compile(r"exec @ARGV' \"\$\{secs\}\" gcloud |\btn_iap_ssh_stdin\b|\btn_iap_scp\b|\bbench_iap_scp_down\b"
                          r"|\bbench_leftovers\b|\btn_iap_ssh\b")
        hits = []
        for i, line in enumerate(self.lines):
            code = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
            if not call.search(code):
                continue
            prev = self.lines[i - 1].strip()
            self.assertEqual(prev, GUARD, "line %d (%s) is not behind the guard" % (i + 1, line.strip()))
            hits.append(line.strip().split()[0])
        # gc (every gcloud), remote (ssh), upload (scp), pull (scp down): four call sites, nothing else.
        self.assertEqual(hits, ["perl", "with_deadline", "with_deadline", "with_deadline"])
        self.assertEqual(self.src.count(GUARD) >= 4, True)
        # Nothing else runs gcloud: no other `gcloud` in command position.
        for i, line in enumerate(self.lines):
            s = line.strip()
            if s.startswith("#") or "gcloud" not in s:
                continue
            ok = (s.startswith(("show ", "perl -e 'alarm shift; exec @ARGV' \"${secs}\" gcloud"))
                  or "gcloud auth login" in s or s.startswith(("echo ", "die ", "bench_warn ", "#", "--"))
                  or "gcloud compute instances list / disks list" in s or "gcloud compute ssh" in s and s.startswith("show"))
            if not ok and re.search(r"(^|[;&|(]\s*)gcloud\b", s):
                self.fail("line %d runs gcloud directly: %s" % (i + 1, s))

    def test_every_loop_has_a_deadline(self):
        deadline = re.compile(r"\$\(now\)|waited|SSH_READY_SECS|WAIT_CHUNK_SECS|ARM_DEADLINE \+ 300|-lt \"\$3\"|-lt 300")
        for i, line in enumerate(self.lines):
            m = re.match(r"^(\s*)while (.*)$", line)
            if not m:
                continue
            cond = m.group(2)
            if cond.startswith("[ $# -gt 0 ]") or "read " in cond:
                continue   # the argument list and line reads are finite
            body = []
            for nxt in self.lines[i:]:
                body.append(nxt)
                if re.match(r"^%sdone\b" % re.escape(m.group(1)), nxt):
                    break
            self.assertRegex("\n".join(body), deadline, "the loop at line %d has no deadline" % (i + 1))

    def test_delete_path_checks_the_generated_name_and_labels_first(self):
        for fn, kind in (("delete_instance", "instances"), ("delete_disk", "disks")):
            body = re.search(r"(?s)\n%s\(\) \{\n(.*?)\n\}\n" % fn, self.src).group(1)
            call = body.index("compute %s delete" % kind)
            self.assertLess(body.index("find_named"), body.index("! ours "))
            self.assertLess(body.index("! ours "), call)
            self.assertEqual(body.count("compute %s delete" % kind), 1)
            self.assertIn('compute %s delete "${%s}"' % (kind, "INST" if kind == "instances" else "DISK"), body)
        # An attached disk is waited for (it goes with the instance), never deleted while attached.
        body = re.search(r"(?s)\ndelete_disk\(\) \{\n(.*?)\n\}\n", self.src).group(1)
        self.assertLess(body.index('attached "${json}"'), body.index("compute disks delete"))
        # "Not there" comes from an exact-name match over the whole listing, never from a gcloud filter.
        find = re.search(r"(?s)\nfind_named\(\) \{\n(.*?)\n\}\n", self.src).group(1)
        self.assertNotIn("--filter", find)
        self.assertIn("select(.name == $n)", find)
        self.assertIn('INST="bench-probe-${BENCH_RUN_ID}"', self.src)
        self.assertIn('DISK="${INST}"', self.src)
        ours = re.search(r"(?s)\nours\(\) \{\n(.*?)\n\}\n", self.src).group(1)
        for want in ('.name == $n', '(.labels.benchmark // "") == "1"', '(.labels["bench-run"] // "") == $r',
                     '(.labels["tn-role"] // "") == "probe"'):
            self.assertIn(want, ours)

    def test_no_list_flag_value_starts_with_a_caret(self):
        for f in (DRIVER, BUILD):
            self.assertIsNone(re.search(r"--[a-z-]+=['\"]?\^", f.read_text()), f.name)

    def test_hygiene(self):
        files = [DRIVER, BUILD, Path(__file__)] + sorted(p for p in FIX.iterdir() if p.is_file())
        for f in files:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for word in HYG.FORBIDDEN:
                    self.assertNotIn(word, line, "%s:%d" % (f.name, n))
                self.assertIsNone(HYG.HOME_RE.search(line), "%s:%d names a home directory" % (f.name, n))
                self.assertIsNone(HYG.GS_NAMED_RE.search(line), "%s:%d names a bucket" % (f.name, n))
                quads = [m.group(0) for m in HYG.IPV4_RE.finditer(line)
                         if m.group(0) not in HYG.ALLOWED_IPV4 and not HYG.is_documentation(m.group(0))]
                self.assertEqual(quads, [], "%s:%d" % (f.name, n))


TREE_SKIP = shutil.ignore_patterns("results", "work", "private", "tests", "latency", "report", "logs", "launch", "obs",
                                  "genesis", ".secrets", "__pycache__", "*.pyc")


class Tree(object):
    """A copy of the repo's shell parts (no results, work, private or secrets) with the fake gcloud first on
    PATH, so the live paths write only under the copy."""

    def __init__(self, state=None):
        self._tmp = tempfile.TemporaryDirectory(prefix="probe-live-")
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for f in ("config.sh", "devnet-lib.sh"):
            shutil.copy2(str(REPO / f), str(self.repo / f))
        shutil.copytree(str(BENCH), str(self.repo / "benchmark"), ignore=TREE_SKIP)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(str(FAKE_GCLOUD), str(self.bin / "gcloud"))
        (self.bin / "gcloud").chmod(0o755)
        self.state = self.root / "state.json"
        self.calls = self.root / "calls.jsonl"
        self.state.write_text(json.dumps(state or {"instances": [], "disks": []}))
        (self.root / "tmp").mkdir()
        self.results = self.repo / "benchmark" / "results" / RUN / "probe"

    def cleanup(self):
        self._tmp.cleanup()

    def fake_bin(self):
        d = self.root / "probe-bin"
        d.mkdir()
        b = d / "mdbx-writeback-probe"
        b.write_text("#!/bin/sh\necho fake probe\n")
        b.chmod(0o755)
        sha = subprocess.run(["sha256sum", str(b)], stdout=subprocess.PIPE, universal_newlines=True).stdout.split()[0]
        (d / "build-info.txt").write_text("binary_sha256=%s\nsource_sha256=%s\nimage=rust:1.94-bookworm\n" % (sha, "ab" * 32))
        return b

    def run(self, *args, **env):
        e = {"FAKE_STATE": str(self.state), "FAKE_CALLS": str(self.calls), "TN_IAP_RETRIES": "0", "BENCH_IAP_RETRIES": "1",
             "HOME": str(self.root), "TMPDIR": str(self.root / "tmp")}
        e.update(env)
        return run_driver(self.repo / "benchmark" / "benchmark-probe.sh", list(args), self.bin, **e)

    def calls_list(self):
        if not self.calls.exists():
            return []
        return [json.loads(line)["argv"] for line in self.calls.read_text().splitlines()]

    def st(self):
        return json.loads(self.state.read_text())


def host_json(**vals):
    """A HOST_PROBE object bench_host_probe_record accepts: every key of bench-lib's _bench_host_fields
    (read from its source, so the frozen list is not copied here) null, then <vals>."""
    src = (BENCH / "bench-lib.sh").read_text()
    body = re.search(r"(?s)\n_bench_host_fields\(\) \{\n(.*?)\n\}\n", src).group(1)
    out = subprocess.run(["bash", "-c", "f() {\n%s\n}\nf" % body], stdout=subprocess.PIPE, universal_newlines=True).stdout
    obj = dict((k.split(":")[0], None) for k in out.split())
    assert "read_ahead_kb" in obj and len(obj) > 20, obj
    obj.update(vals)
    return json.dumps(obj, separators=(",", ":"))


def assert_checksums(case, run_dir):
    """The run's CHECKSUMS.sha256 matches every file it lists (down rewrote it after its own edits)."""
    p = subprocess.run(["sha256sum", "-c", "--quiet", "CHECKSUMS.sha256"], cwd=str(run_dir), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    case.assertEqual(p.returncode, 0, p.stdout)


def inst(name, run=RUN, role="probe", zone="us-west2-a"):
    return {"name": name, "zone": "https://www.googleapis.com/compute/v1/projects/p/zones/" + zone,
            "labels": {"benchmark": "1", "network": "bench", "bench-run": run, "tn-role": role}, "boot_disk": name}


def disk(name, run=RUN, role="probe", users=None):
    d = inst(name, run, role)
    d.pop("boot_disk")
    d["users"] = users if users is not None else []
    return d


class LiveFakeTests(unittest.TestCase):
    def tree(self, state=None):
        t = Tree(state)
        self.addCleanup(t.cleanup)
        return t

    def test_down_deletes_only_its_own_labelled_instance_and_disk(self):
        # A fleet node, and a near name that carries this run's very labels: neither is touched.
        near = INST + "-2"
        t = self.tree({"instances": [inst(near), inst(INST), inst("bench-validator-01", role="validator")],
                       "disks": [disk(near, users=[near]), disk(INST, users=[INST]),
                                 disk("bench-validator-01", role="validator", users=["x"])]})
        p = t.run("down")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("DOWN_OK " + INST, p.stdout)
        calls = t.calls_list()
        deletes = [c for c in calls if len(c) > 2 and c[2] == "delete"]
        self.assertEqual([c[:4] for c in deletes], [["compute", "instances", "delete", INST]])
        first_list = min(i for i, c in enumerate(calls) if c[:3] == ["compute", "instances", "list"])
        self.assertLess(first_list, calls.index(deletes[0]))
        self.assertEqual([c for c in calls if any(a.startswith("--filter") for a in c)], [])
        self.assertEqual([i["name"] for i in t.st()["instances"]], [near, "bench-validator-01"])
        self.assertEqual([d["name"] for d in t.st()["disks"]], [near, "bench-validator-01"])

    def test_down_waits_for_the_boot_disk_to_go_with_the_instance(self):
        # The boot disk stays listed, attached, for two more lists after the instance's delete.
        t = self.tree({"instances": [inst(INST)], "disks": [disk(INST, users=[INST])]})
        p = t.run("down", FAKE_DISK_LAG="2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("disk %s: deleted with the instance" % INST, p.stdout)
        self.assertIn("DOWN_OK " + INST, p.stdout)
        self.assertEqual([c[:4] for c in t.calls_list() if "delete" in c], [["compute", "instances", "delete", INST]])
        self.assertEqual(t.st(), {"instances": [], "disks": []})

    def test_down_refuses_its_name_without_its_labels(self):
        for bad in (inst(INST, run="r20991231-0202"), inst(INST, role="validator")):
            with self.subTest(labels=bad["labels"]):
                t = self.tree({"instances": [bad], "disks": [disk(INST, users=[INST])]})
                p = t.run("down")
                self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
                self.assertIn("NOT deleting it", p.stderr)
                self.assertIn("DOWN_INCOMPLETE", p.stderr)
                self.assertEqual([c for c in t.calls_list() if "delete" in c], [])
                self.assertEqual(len(t.st()["instances"]), 1)

    def test_down_deletes_a_left_over_disk_and_keep_deletes_nothing(self):
        t = self.tree({"instances": [], "disks": [disk(INST)]})
        p = t.run("down", "--keep")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(t.calls_list(), [])
        p = t.run("down")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([c[:4] for c in t.calls_list() if "delete" in c], [["compute", "disks", "delete", INST]])
        self.assertEqual(t.st()["disks"], [])

    def test_up_refuses_beside_a_fleet_unless_allowed(self):
        fleet = {"instances": [inst("bench-validator-01", role="validator")], "disks": []}
        t = self.tree(fleet)
        p = t.run("up")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("other bench resources exist", p.stderr)
        self.assertIn("instance bench-validator-01", p.stderr)
        self.assertEqual([c for c in t.calls_list() if "create" in c], [])
        p = t.run("up", "--allow-fleet")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ssh ready on " + INST, p.stdout)
        creates = [c[:4] for c in t.calls_list() if "create" in c]
        self.assertEqual(creates, [["compute", "disks", "create", INST], ["compute", "instances", "create", INST]])
        self.assertEqual(sorted(i["name"] for i in t.st()["instances"]), sorted(["bench-validator-01", INST]))

    def test_all_deletes_the_vm_after_a_failed_run(self):
        t = self.tree()
        b = t.fake_bin()
        p = t.run("all", "--bin", str(b), "--arms", "g0", FAKE_SCP_RC="1")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("the bundle upload failed", p.stderr)
        self.assertNotIn("leaving early", p.stderr)   # all's own down ran, not only the exit trap's
        calls = [c[:4] for c in t.calls_list()]
        self.assertIn(["compute", "instances", "create", INST], calls)
        scp = [i for i, c in enumerate(calls) if c[:2] == ["compute", "scp"]]
        self.assertTrue(scp)
        self.assertLess(scp[-1], calls.index(["compute", "instances", "delete", INST]))
        self.assertEqual(t.st(), {"instances": [], "disks": []})
        self.assertIn("DOWN_OK " + INST, p.stdout)
        m = json.loads((t.results / "manifest.json").read_text())
        self.assertEqual(m["schema"], "bench-probe/v1")
        self.assertEqual(m["vm"]["machine_type"], "c3-highcpu-8")
        self.assertEqual(m["binary"]["source_sha256"], "ab" * 32)
        self.assertIsNotNone(m["vm"]["deleted_unix"])
        self.assertEqual(m["arms"], [])
        assert_checksums(self, t.results.parent)

    def run_arms(self, arms, **env):
        """all through <arms> against the fake VM, every arm handing back the fixtures' summaries."""
        t = self.tree()
        b = t.fake_bin()
        vm = t.root / "vm"
        vm.mkdir()
        e = dict(FAKE_VM_DIR=str(vm), FAKE_SUMMARY=str(FIX / "arm-summary.txt"), FAKE_I1=str(FIX / "arm-summary-i1.csv"),
                 FAKE_OUTPUT=str(FIX / "arm-output.csv"), FAKE_HOST_JSON=host_json(kernel="6.8.0-fake", read_ahead_kb=128))
        e.update(env)
        return t, b, t.run("all", "--bin", str(b), "--arms", arms, **e)

    def test_all_runs_the_arms_and_writes_the_summary(self):
        names = ["g0-baseline", "g3-ra16-readall", "g5-7default", "g9-sampler"]
        t, b, p = self.run_arms("g0,g3,g5-7default,g9")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("RUN_SUMMARY arms=4 ok=4 failed=0", p.stdout)
        self.assertIn("DOWN_OK " + INST, p.stdout)
        self.assertEqual(t.st(), {"instances": [], "disks": []})
        # The arms in order, each start -> wait -> finish -> pull before the next arm's start.
        seq = []
        for line in t.calls.read_text().splitlines():
            c = json.loads(line)
            head = c["stdin"].split("\n", 1)[0]
            if c["argv"][:2] == ["compute", "ssh"] and head.startswith("# arm "):
                seq.append(head.split()[2].rstrip(":") + " " + head.split()[3])
            elif c["argv"][:2] == ["compute", "scp"] and c["argv"][2].startswith(INST + ":"):
                seq.append(c["argv"][2].split("bench-probe-", 2)[-1].replace(".tar.gz", "") + " pull")
        self.assertEqual(seq, ["%s %s" % (n, step) for n in names for step in ("start", "wait", "finish", "pull")])
        summary = (t.results / "SUMMARY.txt").read_text().splitlines()
        arms = [l for l in summary if l.startswith("PROBE_ARM ")]
        self.assertEqual([l.split()[1] for l in arms], names)
        for l in arms:   # jq 1.7 keeps the probe's "1.000" as written, 1.6 prints 1
            self.assertRegex(l, r"result=done rc=0 device/mdbx=4\.31 commit/mdbx=4\.125 process/mdbx=3\.97 past_used_end=41"
                             r" commit_ms=19\.7 prefault/grown=1(\.000)? past_used_max=3 no_prefault_outputs=0$")
        self.assertIn("  g9-sampler CENSUS_SAFETY_IO quiet runs=5 unchanged=5 read_bytes=0", summary)
        self.assertRegex("\n".join(summary), r"(?m)^SAFETY g9-sampler ref=g5-7default ratio_proc_med=1\.002/1\.002"
                         r" prefault_per_grown=1(\.000)?/1(\.000)? past_used_max=3/3 read_bytes_live=0 read_bytes_quiet=0"
                         r" quiet_unchanged=5/5 no_prefault_outputs=0 -> PASS$")
        m = json.loads((t.results / "manifest.json").read_text())
        by = {a["name"]: a for a in m["arms"]}
        self.assertEqual(sorted(by), names)
        self.assertEqual(by["g0-baseline"]["host_steps"], [{"step": "read-ahead-kb", "value": "128",
                         "result": {"read_ahead_kb_before": 128, "read_ahead_kb_after": 128}}])
        self.assertEqual([h["value"] for h in by["g3-ra16-readall"]["host_steps"]], ["16", "128"])
        self.assertEqual([by[n]["sampler_cadence"] for n in names], ["std", "std", "std", "safety"])
        # The probe's own summary-i1.csv row, under its own column names.
        i1 = by["g0-baseline"]["i1"]
        self.assertEqual((i1["pwritev_max_pages"], i1["pwritev_pages_per_out"], i1["freelist_max"], i1["peer_rc"]),
                         (63, 126.0, 25600, -1))
        self.assertEqual((i1["cache_prep"], i1["prefault_per_grown_pre_peer"]), ("None", "NaN"))
        self.assertEqual(by["g0-baseline"]["outputs_grown_without_prefault"], 0)
        self.assertNotIn("safety", by["g5-7default"])
        safety = by["g9-sampler"]["safety"]
        self.assertEqual((safety["reference"], safety["pass"]), ("g5-7default", True))
        self.assertEqual(set(safety["checks"].values()), {True})
        self.assertEqual(by["g9-sampler"]["exit_code"], 0)
        self.assertIn("--tag g9-sampler", by["g9-sampler"]["command"])
        self.assertEqual(len(by["g9-sampler"]["census_safety"]), 12)
        self.assertEqual(m["host_probe"]["read_ahead_kb"], 128)
        self.assertEqual(m["binary"]["binary_sha256"], hashlib.sha256(b.read_bytes()).hexdigest())
        self.assertEqual(sorted(m["bundle_sha256"]), ["folio-census.py", "mdbx-writeback-probe", "node-persist-sampler.sh"])
        self.assertTrue((t.results / "arms" / "g9-sampler" / "census-safety.txt").exists())
        self.assertIn("boot_read_ahead_kb=128", (t.results / "probe-state.txt").read_text())
        assert_checksums(self, t.results.parent)

    def test_the_safety_arm_fails_when_its_prefault_drops_and_is_incomplete_alone(self):
        t, b, p = self.run_arms("g5-7default,g9", FAKE_DROP_PREFAULT_ARM="g9-sampler")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        summary = (t.results / "SUMMARY.txt").read_text()
        self.assertIn("PROBE_ARM g9-sampler result=done", summary)
        self.assertIn("no_prefault_outputs=2 -> FAIL (prefault_never_dropped)", summary)
        st = json.loads((t.results / "arms" / "g9-sampler.status.json").read_text())
        self.assertEqual((st["first_output_grown_without_prefault"], st["safety"]["pass"]), (2, False))
        # Without its reference arm in the run the verdict is incomplete, never a pass.
        t, b, p = self.run_arms("g9")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex((t.results / "SUMMARY.txt").read_text(),
                         r"SAFETY g9-sampler ref=g5-7default ratio_proc_med=1\.002/- prefault_per_grown=1(\.000)?/- past_used_max=3/-")
        self.assertIn("-> INCOMPLETE (not measured: ratio_proc_med,prefault_per_grown,beyond_used_resident_max)",
                      (t.results / "SUMMARY.txt").read_text())

    def test_a_start_session_that_dropped_is_settled_by_the_wait(self):
        # The start session dies after the unit started: the arm is waited for, not stopped as failed.
        t = self.tree()
        b = t.fake_bin()
        vm = t.root / "vm"
        vm.mkdir()
        p = t.run("all", "--bin", str(b), "--arms", "g0", FAKE_VM_DIR=str(vm), FAKE_START_SILENT="1",
                  FAKE_SUMMARY=str(FIX / "arm-summary.txt"), FAKE_HOST_JSON=host_json(read_ahead_kb=128))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("arm g0-baseline: the start session printed no ARM_START line; asking the VM", p.stdout)
        self.assertIn("PROBE_ARM g0-baseline result=done rc=0", (t.results / "SUMMARY.txt").read_text())

    def test_collect_pulls_again_what_the_run_lost(self):
        t = self.tree()
        b = t.fake_bin()
        vm = t.root / "vm"
        vm.mkdir()
        p = t.run("all", "--bin", str(b), "--arms", "g0", FAKE_VM_DIR=str(vm), FAKE_PULL_FAILS="1",
                  FAKE_SUMMARY=str(FIX / "arm-summary.txt"), FAKE_HOST_JSON=host_json(read_ahead_kb=128))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)   # the run lost a pull; collect got it back
        self.assertIn("RUN_SUMMARY arms=1 ok=0 failed=1", p.stdout)
        self.assertIn("collect: g0-baseline was not pulled; trying again", p.stdout)
        heads = [json.loads(l)["stdin"].split("\n", 1)[0] for l in t.calls.read_text().splitlines()]
        self.assertEqual(len([h for h in heads if h.startswith("# arm g0-baseline: finish")]), 2)
        summary = (t.results / "SUMMARY.txt").read_text()
        self.assertIn("PROBE_ARM g0-baseline result=done rc=0 device/mdbx=4.31", summary)
        self.assertTrue((t.results / "arms" / "g0-baseline" / "results" / "g0-baseline.summary.txt").exists())
        self.assertEqual([t.st()["instances"], t.st()["disks"]], [[], []])
        assert_checksums(self, t.results.parent)

    def test_all_starts_no_arm_that_would_end_past_the_run_deadline(self):
        t = self.tree()
        b = t.fake_bin()
        vm = t.root / "vm"
        vm.mkdir()
        p = t.run("all", "--bin", str(b), "--arms", "g0", "--deadline-min", "1", FAKE_VM_DIR=str(vm),
                  FAKE_HOST_JSON=host_json(read_ahead_kb=128))
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("arm g0-baseline: skipped, the run deadline is too close", p.stdout)
        heads = [json.loads(l)["stdin"].split("\n", 1)[0] for l in t.calls.read_text().splitlines()]
        self.assertIn("# setup: settle the fresh VM, unpack and check the bundle, check the tools the arms use", heads)
        self.assertEqual([h for h in heads if h.startswith("# arm ")], [])
        st = json.loads((t.results / "arms" / "g0-baseline.status.json").read_text())
        self.assertEqual(st["result"], "skipped: run deadline")
        self.assertIn("DOWN_OK " + INST, p.stdout)
        self.assertEqual(t.st(), {"instances": [], "disks": []})

    def test_all_deletes_the_vm_when_interrupted(self):
        t = self.tree()
        b = t.fake_bin()
        # The host probe session never answers: TERM the driver while it waits, down must still run.
        slow = t.bin / "gcloud-real"
        shutil.move(str(t.bin / "gcloud"), str(slow))
        (t.bin / "gcloud").write_text('#!/bin/sh\ncase "$*" in *"compute ssh"*) [ -e "%s" ] && sleep 60 ;; esac\n'
                                      'exec "%s" "$@"\n' % (t.root / "slow", slow))
        (t.bin / "gcloud").chmod(0o755)
        e = dict(os.environ)
        e.update({"PATH": str(t.bin) + os.pathsep + os.environ.get("PATH", ""), "BENCH_RUN_ID": RUN, "FAKE_STATE": str(t.state),
                  "FAKE_CALLS": str(t.calls), "TN_IAP_RETRIES": "0", "HOME": str(t.root), "TMPDIR": str(t.root / "tmp")})
        proc = subprocess.Popen(["bash", str(t.repo / "benchmark" / "benchmark-probe.sh"), "all", "--bin", str(b), "--arms", "g0"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e,
                                universal_newlines=True)
        import time
        deadline = time.time() + 120
        while time.time() < deadline and not any(c[:2] == ["compute", "scp"] for c in t.calls_list()):
            time.sleep(0.5)
        (t.root / "slow").write_text("")
        time.sleep(3)
        proc.terminate()
        out, err = proc.communicate(timeout=240)
        self.assertEqual(proc.returncode, 143, out + err)
        self.assertIn("deleting " + INST + " first", err)
        self.assertEqual(t.st(), {"instances": [], "disks": []})


class BuildToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="probe-build-")
        self.root = Path(self._tmp.name)
        self.crate = self.root / "crate"
        (self.crate / "src").mkdir(parents=True)
        (self.crate / "Cargo.toml").write_text("[package]\nname = \"x\"\n")
        (self.crate / "Cargo.lock").write_text("# lock\n")
        (self.crate / "src" / "main.rs").write_text("fn main() {}\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "docker.log"
        # A docker that records its argv and plays the container: the binary and .glibc into the /out mount.
        (self.bin / "docker").write_text(
            "#!/bin/sh\necho \"$*\" >> '%s'\n"
            "if [ \"$1\" = image ]; then echo sha256:feed; exit 0; fi\n"
            "out=''; for a in \"$@\"; do case \"$a\" in *:/out) out=\"${a%%:/out}\" ;; esac; done\n"
            "printf 'ELF' > \"$out/mdbx-writeback-probe\"\nprintf 'glibc_max=2.34\\nrustc=rustc 1.94.1\\n' > \"$out/.glibc\"\n"
            % self.log)
        (self.bin / "docker").chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args):
        e = dict(os.environ)
        e["PATH"] = str(self.bin) + os.pathsep + os.environ.get("PATH", "")
        return subprocess.run(["bash", str(BUILD)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, env=e, timeout=60)

    def test_print_runs_nothing(self):
        p = self.run_tool("--crate", str(self.crate), "--out", str(self.root / "out"), "--print")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(":/src:ro", p.stdout)
        self.assertIn("rust:1.94-bookworm", p.stdout)
        self.assertIn("cargo build --release --locked --manifest-path /src/Cargo.toml", p.stdout)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.root / "out").exists())

    def test_build_writes_build_info_and_the_two_hashes(self):
        out = self.root / "out"
        p = self.run_tool("--crate", str(self.crate), "--out", str(out))
        self.assertEqual(p.returncode, 0, p.stderr)
        argv = self.log.read_text().splitlines()[0]
        self.assertIn("run --rm -v %s:/src:ro -v %s:/out rust:1.94-bookworm bash -c" % (self.crate, out), argv)
        info = dict(l.split("=", 1) for l in (out / "build-info.txt").read_text().splitlines())
        sha = subprocess.run(["sha256sum", str(out / "mdbx-writeback-probe")], stdout=subprocess.PIPE,
                             universal_newlines=True).stdout.split()[0]
        self.assertEqual(info["binary_sha256"], sha)
        self.assertEqual(info["glibc_max"], "2.34")
        self.assertIn("BINARY_SHA256 " + sha, p.stdout)
        self.assertIn("SOURCE_SHA256 " + info["source_sha256"], p.stdout)
        self.assertFalse((out / ".glibc").exists())
        # The source hash depends on the sources only, not on where the crate lives.
        moved = self.root / "elsewhere"
        shutil.copytree(str(self.crate), str(moved))
        p2 = self.run_tool("--crate", str(moved), "--out", str(self.root / "out2"))
        self.assertIn("SOURCE_SHA256 " + info["source_sha256"], p2.stdout)
        (moved / "src" / "main.rs").write_text("fn main() { }\n")
        p3 = self.run_tool("--crate", str(moved), "--out", str(self.root / "out3"))
        self.assertNotIn("SOURCE_SHA256 " + info["source_sha256"], p3.stdout)

    def test_refuses_a_non_bookworm_image_and_a_non_crate(self):
        p = self.run_tool("--crate", str(self.crate), "--out", str(self.root / "o"), "--image", "rust:1.94-alpine", "--print")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not a bookworm image", p.stderr)
        p = self.run_tool("--crate", str(self.root), "--out", str(self.root / "o"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("is not the probe crate", p.stderr)


if __name__ == "__main__":
    unittest.main()
