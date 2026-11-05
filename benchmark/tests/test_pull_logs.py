"""benchmark/pull-lib.sh, offline: pulls that survive a cut stream, the unit-log span, the rotated
generations, the coverage gate, the bench logrotate text and the duplicate drop.

The library is sourced (twice: that must be harmless) after the real devnet-lib.sh, whose IAP
wrappers run against fixtures/pull/fake-gcloud.py. The fake runs each session on this machine (the
node's files are a temporary directory BENCH_NODE_UNIT_LOGS points at) and can cut a stream short,
refuse the tunnel, fail re-authentication or send nothing (FAKE_OUTCOMES). A sleep shell function
records each backoff instead of waiting. TN_IAP_RETRIES=0 is pinned, as in every test that counts
ssh sessions, except where a test sets it to show the pull switches devnet-lib's retry off itself.
tn_iap_fault_kind belongs to devnet-lib.sh (unit U-H6); until it is there the shim defines a
stand-in with its contract.
"""
import grp
import gzip
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIX = TESTS / "fixtures" / "pull"
PULL_LIB = BENCH / "pull-lib.sh"
DEVNET_LIB = REPO / "devnet-lib.sh"
PROVENANCE = BENCH / "report" / "provenance.py"
V2_COMMON = REPO / "tn-node-deployment" / "lib" / "common.sh"

INST, ZONE = "bench-validator-01", "us-west2-a"
SPAN_HEADER, ROTATED_HEADER = "# bench-pull: span", "# bench-pull: rotated"
STAMP_RE = r"\d{8}T\d{6}Z"
LOGSPAN_RE = re.compile(r"^LOGSPAN (\S+) stream=([a-z]+) gen=(\d+) file=(\S+) bytes=(\d+|-) first=(\S+) last=(\S+)$")
LOGCOV_RE = re.compile(r"^LOGCOV (\S+) gens=(\d+|-) first=(\S+) last=(\S+) due=(\S+) end=(\S+) ok=(0|1|-)$")
T0 = 1793740000            # 2026-11-03T21:06:40Z
PUBLIC = ("bench_pull_stream", "bench_unit_log_span_script", "bench_pull_unit_span", "bench_rotated_logs_script",
          "bench_pull_rotated_logs", "bench_log_coverage_check", "bench_logrotate_text", "bench_drop_if_identical")

SHIM = r"""
set -euo pipefail
source "${DEVNET_LIB}"
# tn_iap_fault_kind belongs to devnet-lib.sh (unit U-H6). Until it lands, a stand-in with its
# contract: <rc> <stderr file> -> ok | reauth | transport | iap-refused | other.
declare -F tn_iap_fault_kind >/dev/null || tn_iap_fault_kind() {
    [ "$1" -eq 0 ] && { echo ok; return 0; }
    grep -Eq -- "${TN_IAP_REAUTH_PAT:-Reauthentication failed|There was a problem refreshing your current auth tokens|invalid_grant}" "$2" && { echo reauth; return 0; }
    { [ "$1" -eq 255 ] || grep -q 'gcloud crashed' "$2"; } && { echo transport; return 0; }
    grep -Eq '\[(4003|4033|4047): ' "$2" && { echo iap-refused; return 0; }
    echo other
}
sleep() { printf '%s\n' "$1" >> "${FAKE_ROOT}/sleeps"; }
source "${PULL_LIB}"
source "${PULL_LIB}"
"$@"
"""


def iso(unix):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(unix))


def log_text(start, count, step=7, preamble=""):
    """<count> node log lines (logfmt, like the unit's), <step> s apart from <start>."""
    lines = [preamble] if preamble else []
    for i in range(count):
        lines.append('ts=%s.158160337Z level=info target=primary::proposer message="round" round=%d'
                     % (iso(start + i * step)[:-1], i))
    return "\n".join(lines) + "\n"


def unit_cmd(path):
    """The remote command bench-lib streams a unit log with: gzipped on the node, nothing if missing."""
    return "sudo bash -c '%s' _ %s" % ('[ -s "$1" ] || exit 0; gzip -1 < "$1"', shlex.quote(str(path)))


def node_tree(root):
    """{relative path: bytes or None for a directory} of everything under <root>, dot names included."""
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}


def node_log_re():
    spec = importlib.util.spec_from_file_location("provenance_for_pull_logs", str(PROVENANCE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._NODE_LOG_RE


class PullCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pull-logs-")
        self.root = Path(self._tmp.name)
        self.bin, self.state, self.tmpdir = self.root / "bin", self.root / "state", self.root / "tmp"
        self.node = self.root / "node" / "var" / "log" / "telcoin"
        self.dest = self.root / "results" / "logs"
        for d in (self.bin, self.state, self.tmpdir, self.node, self.dest):
            d.mkdir(parents=True)
        shutil.copyfile(str(FIX / "fake-gcloud.py"), str(self.bin / "gcloud"))
        (self.bin / "gcloud").chmod(0o755)
        config = self.root / "config.sh"
        config.write_text("# empty: the test environment sets what devnet-lib.sh reads\n")
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "LC_ALL": "C",
            "FAKE_ROOT": str(self.state), "PROJECT_ID": "acme-project", "CONFIG_FILE": str(config),
            "TN_SSH_TRANSPORT": "iap", "TN_IAP_RETRIES": "0",
            "DEVNET_LIB": str(DEVNET_LIB), "PULL_LIB": str(PULL_LIB),
            "BENCH_NODE_UNIT_LOGS": "stdout:%s stderr:%s" % (self.node / "telcoin.log", self.node / "telcoin-error.log"),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def run_lib(self, *args, **extra):
        env = dict(self.env)
        env.update(extra)
        return subprocess.run(["bash", "-c", SHIM, "pull-test"] + [str(a) for a in args], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)

    def calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def sleeps(self):
        p = self.state / "sleeps"
        return p.read_text().split() if p.exists() else []

    def reset(self):
        for name in ("calls.jsonl", "calls-made", "sleeps"):
            if (self.state / name).exists():
                (self.state / name).unlink()

    def leftovers(self):
        """Temp files or work directories a pull left behind (beside <out>, in <dest>, in TMPDIR)."""
        left = [p.name for p in self.dest.iterdir() if p.name.startswith(".") or re.search(r"\.a\w{6}$", p.name)]
        return sorted(left + ["tmp/" + p.name for p in self.tmpdir.iterdir()])

    def landed(self):
        return sorted(p.name for p in self.dest.iterdir() if p.is_file() and not p.name.startswith("."))


class StreamTests(PullCase):
    def setUp(self):
        super().setUp()
        self.src = self.node / "telcoin.log"
        self.src.write_text(log_text(T0, 400))
        self.out = self.dest / ("%s-unit-stdout.log.gz" % INST)
        # What the node sends for this file in one whole stream.
        self.full = subprocess.run(["bash", "-c", 'gzip -1 < "$1"', "_", str(self.src)],
                                   stdout=subprocess.PIPE, check=True).stdout

    def pull_gz(self, outcomes, **extra):
        return self.run_lib("bench_pull_stream", INST, ZONE, "gz", self.out, "cmd", unit_cmd(self.src),
                            FAKE_OUTCOMES=outcomes, **extra)

    def test_partial_first_attempt_is_discarded_and_retried(self):
        # The cut attempt either drops the session (rc 255) or reports success (rc 0); either way its
        # bytes must never reach <out> and the retry's whole stream must.
        for first in ("partial255", "partial0"):
            with self.subTest(first=first):
                self.reset()
                if self.out.exists():
                    self.out.unlink()
                p = self.pull_gz(first + ",ok")
                self.assertEqual([c["outcome"] for c in self.calls()], [first, "ok"], p.stderr)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(self.out.read_bytes(), self.full, "the landed copy is not the retry's whole stream")
                self.assertEqual(self.sleeps(), ["10"])
                self.assertIn("retrying in 10 s", p.stderr)
                self.assertEqual(self.leftovers(), [])

    def test_devnet_lib_never_retries_inside_an_attempt(self):
        # devnet-lib's own retry would append the retry's stream to the cut one in the same file.
        p = self.pull_gz("partial255,ok", TN_IAP_RETRIES="2")
        self.assertEqual([c["outcome"] for c in self.calls()], ["partial255", "ok"], p.stderr)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.out.read_bytes(), self.full)
        self.assertNotIn("transport fault (rc 255) — retry", p.stderr, "devnet-lib retried inside the attempt")
        self.assertEqual(self.sleeps(), ["10"])

    def test_one_session_with_the_command_and_a_closed_stdin(self):
        p = self.pull_gz("ok")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "", "a landed pull is quiet")
        (call,) = self.calls()
        self.assertEqual(call["argv"][:3], ["compute", "ssh", INST])
        self.assertIn("--zone=" + ZONE, call["argv"])
        self.assertIn("--tunnel-through-iap", call["argv"])
        self.assertIn("--command=" + unit_cmd(self.src), call["argv"])
        self.assertEqual(call["stdin"], "")
        self.assertEqual(gzip.decompress(self.out.read_bytes()), self.src.read_bytes())

    def test_reauth_stops_and_leaves_the_stop_file(self):
        stop = self.root / "pull-stop"
        p = self.pull_gz("reauth", BENCH_PULL_STOP_FILE=str(stop))
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertTrue(stop.exists(), "the stop file was not touched")
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.sleeps(), [])
        self.assertFalse(self.out.exists())
        self.assertIn("gcloud needs re-authentication (run: gcloud auth login)", p.stderr)
        self.assertEqual(self.leftovers(), [])
        # While the stop file exists no session starts.
        p = self.pull_gz("ok", BENCH_PULL_STOP_FILE=str(stop))
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(len(self.calls()), 1, "a session started after the stop")
        self.assertFalse(self.out.exists())

    def test_reauth_without_a_stop_file_still_stops(self):
        p = self.pull_gz("reauth,ok")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_nothing_to_copy_is_rc_1_and_lands_nothing(self):
        missing = self.node / "nope.log"
        for label, cmd, outcomes in (("empty session", unit_cmd(self.src), "empty"),
                                     ("missing file", unit_cmd(missing), "ok"),
                                     ("gzip of nothing", "gzip -1 < /dev/null", "ok")):
            with self.subTest(case=label):
                self.reset()
                p = self.run_lib("bench_pull_stream", INST, ZONE, "gz", self.out, "cmd", cmd, FAKE_OUTCOMES=outcomes)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertEqual(len(self.calls()), 1)
                self.assertFalse(self.out.exists())
                self.assertEqual(self.leftovers(), [])

    def test_a_refused_tunnel_is_retried_up_to_the_budget(self):
        p = self.pull_gz("refused")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(self.sleeps(), ["10", "20"])
        self.assertIn("after 3 attempt(s) — not pulled", p.stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])
        self.reset()
        p = self.pull_gz("refused", BENCH_IAP_RETRIES="1")
        self.assertEqual((p.returncode, len(self.calls()), self.sleeps()), (2, 1, []), p.stderr)
        self.reset()
        p = self.pull_gz("refused,refused,refused,refused,ok", BENCH_IAP_RETRIES="bogus")
        self.assertEqual(len(self.calls()), 3, "an invalid budget falls back to 3")
        self.assertIn("BENCH_IAP_RETRIES='bogus' is not a positive integer", p.stderr)
        self.reset()
        p = self.pull_gz("refused,ok")
        self.assertEqual((p.returncode, len(self.calls())), (0, 2), p.stderr)
        self.assertEqual(self.out.read_bytes(), self.full)

    def test_any_other_failure_is_not_retried_and_keeps_an_earlier_copy(self):
        self.out.write_bytes(b"an earlier copy")
        p = self.pull_gz("other")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.sleeps(), [])
        self.assertEqual(self.out.read_bytes(), b"an earlier copy")
        self.assertIn("Permission denied", p.stderr, "gcloud's stderr is shown")
        self.assertEqual(self.leftovers(), [])

    def test_a_cut_tar_is_retried_and_text_goes_over_stdin(self):
        out = self.dest / "saved.tar"
        cmd = "tar -cf - -C %s telcoin.log" % shlex.quote(str(self.node))
        p = self.run_lib("bench_pull_stream", INST, ZONE, "tar", out, "cmd", cmd, FAKE_OUTCOMES="partial0,ok")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.calls()), 2)
        with tarfile.open(str(out)) as tar:
            self.assertEqual(tar.getnames(), ["telcoin.log"])
        self.reset()
        out = self.dest / "probe.txt"
        script = SPAN_HEADER + "\necho 'LOGSPAN probe'"
        p = self.run_lib("bench_pull_stream", INST, ZONE, "txt", out, "stdin", script)
        self.assertEqual(p.returncode, 0, p.stderr)
        (call,) = self.calls()
        self.assertEqual(call["session"], SPAN_HEADER)
        self.assertEqual(call["stdin"], script + "\n")
        self.assertIn("--command=sudo bash -s", call["argv"])
        self.assertIn("--ssh-flag=-T", call["argv"])
        self.assertEqual(out.read_text(), "LOGSPAN probe\n")
        self.assertEqual(self.leftovers(), [])

    def test_a_tar_cut_between_members_is_not_whole(self):
        # It lists (every member it holds is complete), but its end-of-archive blocks are missing.
        size = self.src.stat().st_size
        cut = 512 + (size + 511) // 512 * 512
        cmd = "tar -cf - -C %s telcoin.log | head -c %d" % (shlex.quote(str(self.node)), cut)
        p = self.run_lib("bench_pull_stream", INST, ZONE, "tar", self.dest / "saved.tar", "cmd", cmd)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(len(self.calls()), 3, "a cut stream is retried as a transport fault")
        self.assertIn("the tar archive is not whole", p.stderr)
        self.assertFalse((self.dest / "saved.tar").exists())
        self.assertEqual(self.leftovers(), [])

    def test_bad_arguments_are_refused_without_a_session(self):
        for args in (("zip", self.out, "cmd", "true"), ("gz", self.out, "scp", "true"), ("gz", "", "cmd", "true"),
                     ("gz", self.out, "cmd", "")):
            with self.subTest(args=args):
                p = self.run_lib("bench_pull_stream", INST, ZONE, *args)
                self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.calls(), [])


class SpanTests(PullCase):
    def test_three_generations_are_listed(self):
        live, one, two = self.node / "telcoin.log", self.node / "telcoin.log.1", self.node / "telcoin.log.2.gz"
        two.write_bytes(gzip.compress(log_text(T0, 50, preamble="Unable to find image locally").encode()))
        one.write_text(log_text(T0 + 1000, 50))
        live.write_text(log_text(T0 + 2000, 50) + "ts=2026-11-03T21:50")   # a line still being written
        (self.node / "telcoin.log.old").write_text("not a generation\n")
        before = node_tree(self.node)
        p = self.run_lib("bench_pull_unit_span", INST, ZONE, self.dest)
        self.assertEqual(p.returncode, 0, p.stderr)
        (call,) = self.calls()
        self.assertEqual(call["session"], SPAN_HEADER)
        self.assertEqual(call["stdin"].split("\n", 1)[0], SPAN_HEADER)
        self.assertEqual(node_tree(self.node), before, "the span changed the node")
        lines = (self.dest / (INST + ".logspan")).read_text().splitlines()
        rows = []
        for line in lines:
            m = LOGSPAN_RE.match(line)
            self.assertIsNotNone(m, line)
            rows.append(m.groups())
        self.assertEqual(rows, [
            (INST, "stdout", "0", str(live), str(live.stat().st_size), iso(T0 + 2000), iso(T0 + 2000 + 49 * 7)),
            (INST, "stdout", "1", str(one), str(one.stat().st_size), iso(T0 + 1000), iso(T0 + 1000 + 49 * 7)),
            (INST, "stdout", "2", str(two), str(two.stat().st_size), iso(T0), "-"),
            (INST, "stderr", "0", str(self.node / "telcoin-error.log"), "-", "-", "-"),
        ])
        # The span feeds the gate: the start sits in generation 2, the end in generation 0.
        p = self.run_lib("bench_log_coverage_check", self.dest, INST, T0 + 100, iso(T0 + 2000 + 40 * 7))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(" gens=3 first=%s last=%s " % (iso(T0), iso(T0 + 2000 + 49 * 7)), p.stdout)
        self.assertTrue(p.stdout.rstrip().endswith(" ok=1"), p.stdout)

    def test_the_canned_span_lands_as_is_and_keeps_the_format(self):
        canned = FIX / "node-span.txt"
        for line in canned.read_text().splitlines():
            self.assertIsNotNone(LOGSPAN_RE.match(line), line)
        p = self.run_lib("bench_pull_unit_span", INST, ZONE, self.dest, FAKE_SPAN_FILE=str(canned))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.dest / (INST + ".logspan")).read_bytes(), canned.read_bytes())

    def test_a_cut_span_session_is_retried(self):
        (self.node / "telcoin.log").write_text(log_text(T0, 5))
        p = self.run_lib("bench_pull_unit_span", INST, ZONE, self.dest, FAKE_OUTCOMES="partial255,ok")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(len((self.dest / (INST + ".logspan")).read_text().splitlines()), 2)

    def test_devnet_lib_never_retries_inside_a_stdin_session(self):
        # Text has no integrity check of its own: a cut span plus its retry would land as one file.
        (self.node / "telcoin.log").write_text(log_text(T0, 5))
        p = self.run_lib("bench_pull_unit_span", INST, ZONE, self.dest, FAKE_OUTCOMES="partial255,ok", TN_IAP_RETRIES="2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.sleeps(), ["10"], "devnet-lib retried inside the attempt")
        lines = (self.dest / (INST + ".logspan")).read_text().splitlines()
        self.assertEqual([line.split()[2] for line in lines], ["stream=stdout", "stream=stderr"], lines)


class RotatedTests(PullCase):
    def setUp(self):
        super().setUp()
        (self.node / "telcoin.log").write_text(log_text(T0 + 2000, 10))
        self.one_text = log_text(T0 + 1000, 30)
        (self.node / "telcoin.log.1").write_text(self.one_text)
        self.two_gz = gzip.compress(log_text(T0, 30).encode(), mtime=0)
        (self.node / "telcoin.log.2.gz").write_bytes(self.two_gz)
        self.err_text = "Error response from daemon: No such container: telcoin\n"
        (self.node / "telcoin-error.log.1").write_text(self.err_text)
        self.before = node_tree(self.node)

    def name(self, stream, gen):
        return "%s-unit-%s.rotated-%d.log.gz" % (INST, stream, gen)

    def pull(self, *skip, **extra):
        return self.run_lib("bench_pull_rotated_logs", INST, ZONE, self.dest, *skip, **extra)

    def test_rotated_generations_land_under_their_names(self):
        p = self.pull()
        self.assertEqual(p.returncode, 0, p.stderr)
        (call,) = self.calls()
        self.assertEqual(call["session"], ROTATED_HEADER)
        want = [self.name("stderr", 1), self.name("stdout", 1), self.name("stdout", 2)]
        self.assertEqual(self.landed(), want)
        self.assertEqual(gzip.decompress((self.dest / self.name("stdout", 1)).read_bytes()).decode(), self.one_text)
        self.assertEqual((self.dest / self.name("stdout", 2)).read_bytes(), self.two_gz, "a .N.gz is sent as it is")
        self.assertEqual(gzip.decompress((self.dest / self.name("stderr", 1)).read_bytes()).decode(), self.err_text)
        self.assertEqual(node_tree(self.node), self.before, "the node's logs changed, or a work directory was left")
        self.assertEqual(self.leftovers(), [])
        for n in want:
            self.assertIn("✓ %s -> %s" % (INST, self.dest / n), p.stdout)
            self.assertIsNotNone(node_log_re().match(n), n)

    def test_an_unchanged_generation_pulls_to_identical_bytes(self):
        self.assertEqual(self.pull().returncode, 0)
        first = (self.dest / self.name("stdout", 1)).read_bytes()
        (self.node / "telcoin.log.1").touch()   # a new mtime, the same content
        os.utime(str(self.node / "telcoin.log.1"), (T0, T0))
        self.reset()
        p = self.pull()
        self.assertEqual(p.returncode, 0, p.stderr)
        stamped = [n for n in self.landed() if n.startswith(INST + "-unit-stdout-") and n.endswith(".rotated-1.log.gz")]
        self.assertEqual(len(stamped), 1, self.landed())
        self.assertEqual((self.dest / stamped[0]).read_bytes(), first)
        p = self.run_lib("bench_drop_if_identical", self.dest / stamped[0], self.dest / self.name("stdout", 1))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.dest / stamped[0]).exists())

    def test_a_taken_name_gets_a_stamped_copy_and_both_names_parse(self):
        old = self.dest / self.name("stdout", 1)
        old.write_bytes(b"an earlier instance's copy")
        p = self.pull()
        self.assertEqual(p.returncode, 0, p.stderr)
        stamped_re = re.compile(re.escape(INST) + r"-unit-stdout-" + STAMP_RE + r"\.rotated-1\.log\.gz$")
        stamped = [n for n in self.landed() if stamped_re.match(n)]
        self.assertEqual(len(stamped), 1, self.landed())
        self.assertEqual(old.read_bytes(), b"an earlier instance's copy", "a taken name was replaced")
        self.assertEqual(gzip.decompress((self.dest / stamped[0]).read_bytes()).decode(), self.one_text)
        rx = node_log_re()
        for n in (old.name, stamped[0]):
            m = rx.match(n)
            self.assertIsNotNone(m, "provenance.py does not read %s as a node log" % n)
            self.assertEqual(m.group("inst"), INST)

    def test_skipped_generations_are_not_sent(self):
        skip = (self.name("stdout", 2), "/elsewhere/%s-unit-stdout-20261104T003616Z.rotated-1.log.gz" % INST,
                "unit-stderr.rotated-9.log.gz", "not-a-log.txt")
        p = self.pull(*skip)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.landed(), [self.name("stderr", 1)])
        (call,) = self.calls()
        self.assertIn("skip=' unit-stdout.rotated-2.log.gz unit-stdout.rotated-1.log.gz unit-stderr.rotated-9.log.gz '",
                      call["stdin"])
        self.assertNotIn("not-a-log", call["stdin"])
        self.reset()
        p = self.pull(self.name("stdout", 1), self.name("stdout", 2), self.name("stderr", 1))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("no rotated unit log to pull", p.stdout)
        self.assertEqual(self.landed(), [self.name("stderr", 1)])
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(node_tree(self.node), self.before)

    def test_a_cut_archive_is_retried_and_a_failure_lands_nothing(self):
        # Big enough that the cut lands inside a member, not in the archive's zero padding.
        self.one_text = "".join("ts=%s round=%s\n" % (iso(T0 + i)[:-1] + "Z", os.urandom(16).hex()) for i in range(4000))
        (self.node / "telcoin.log.1").write_text(self.one_text)
        p = self.pull(FAKE_OUTCOMES="partial0,ok")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(len(self.landed()), 3)
        self.assertEqual(gzip.decompress((self.dest / self.name("stdout", 1)).read_bytes()).decode(), self.one_text)
        for f in self.dest.iterdir():
            f.unlink()
        self.reset()
        p = self.pull(FAKE_OUTCOMES="other")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.landed(), [])
        self.assertEqual(self.leftovers(), [])


class CoverageTests(PullCase):
    DUE = 1793744768                 # 2026-11-03T22:26:08Z, as manifest.coordinated_start.due has it
    END = "2026-11-04T00:19:50Z"     # as manifest.timestamps.blast_end has it

    def span(self, keep=lambda line: True, extra=""):
        text = (FIX / "node-span.txt").read_text()
        body = "".join(line for line in text.splitlines(True) if keep(line)) + extra
        (self.dest / (INST + ".logspan")).write_text(body)

    def check(self, due, end):
        p = self.run_lib("bench_log_coverage_check", self.dest, INST, due, end)
        lines = p.stdout.splitlines()
        self.assertEqual(len(lines), 1, p.stdout + p.stderr)
        self.assertIsNotNone(LOGCOV_RE.match(lines[0]), lines[0])
        return p.returncode, lines[0]

    def test_a_covering_span_passes(self):
        self.span()
        self.assertEqual(self.check(self.DUE, self.END), (0, (
            "LOGCOV bench-validator-01 gens=3 first=2026-11-03T21:11:32Z last=2026-11-04T00:29:10Z "
            "due=2026-11-03T22:26:08Z end=2026-11-04T00:19:50Z ok=1")))

    def test_a_first_line_after_due_fails_the_gate(self):
        # Bench 3: the generation holding the start of the run was never looked at.
        self.span(keep=lambda line: " gen=2 " not in line)
        self.assertEqual(self.check(self.DUE, self.END), (1, (
            "LOGCOV bench-validator-01 gens=2 first=2026-11-03T23:37:02Z last=2026-11-04T00:29:10Z "
            "due=2026-11-03T22:26:08Z end=2026-11-04T00:19:50Z ok=0")))

    def test_a_last_line_before_the_end_fails_the_gate(self):
        self.span()
        rc, line = self.check(self.DUE, "2026-11-04T00:30:00Z")
        self.assertEqual((rc, line[-5:]), (1, " ok=0"), line)
        # The live file just rotated (empty): the last line is generation 1's.
        self.span(keep=lambda line: " gen=0 " not in line or "stderr" in line,
                  extra="LOGSPAN %s stream=stdout gen=0 file=/var/log/telcoin/telcoin.log bytes=0 first=- last=-\n" % INST)
        rc, line = self.check(self.DUE, self.END)
        self.assertEqual((rc, line), (1, "LOGCOV bench-validator-01 gens=3 first=2026-11-03T21:11:32Z "
                                         "last=2026-11-04T00:00:00Z due=2026-11-03T22:26:08Z end=2026-11-04T00:19:50Z ok=0"))
        rc, line = self.check(self.DUE, "2026-11-03T23:59:59Z")
        self.assertEqual((rc, line[-5:]), (0, " ok=1"), line)

    def test_an_unknown_reference_is_a_note_not_a_failure(self):
        self.span()
        self.assertEqual(self.check("-", self.END), (0, (
            "LOGCOV bench-validator-01 gens=3 first=2026-11-03T21:11:32Z last=2026-11-04T00:29:10Z "
            "due=- end=2026-11-04T00:19:50Z ok=-")))
        rc, line = self.check("null", "-")
        self.assertEqual(rc, 0, line)
        self.assertTrue(line.endswith(" due=- end=- ok=-"), line)
        # A known side that fails still fails.
        self.span(keep=lambda line: " gen=2 " not in line)
        rc, line = self.check(self.DUE, "-")
        self.assertEqual((rc, line[-5:]), (1, " ok=0"), line)
        # No span: unknown.
        (self.dest / (INST + ".logspan")).unlink()
        self.assertEqual(self.check(self.DUE, self.END), (0, (
            "LOGCOV bench-validator-01 gens=- first=- last=- due=2026-11-03T22:26:08Z end=2026-11-04T00:19:50Z ok=-")))

    def test_a_node_without_a_log_fails_a_known_side(self):
        self.span(keep=lambda line: "stderr" in line,
                  extra="LOGSPAN %s stream=stdout gen=0 file=/var/log/telcoin/telcoin.log bytes=- first=- last=-\n" % INST)
        self.assertEqual(self.check(self.DUE, self.END), (1, (
            "LOGCOV bench-validator-01 gens=0 first=- last=- due=2026-11-03T22:26:08Z end=2026-11-04T00:19:50Z ok=0")))

    def test_other_streams_and_instances_do_not_count(self):
        early = "first=2026-11-03T20:00:00Z last=2026-11-04T01:00:00Z"
        self.span(keep=lambda line: " gen=2 " not in line, extra=(
            "LOGSPAN %s stream=stderr gen=3 file=/var/log/telcoin/telcoin-error.log.3.gz bytes=9 %s\n"
            "LOGSPAN bench-validator-02 stream=stdout gen=4 file=/var/log/telcoin/telcoin.log.4.gz bytes=9 %s\n"
            "garbage line\n" % (INST, early, early)))
        rc, line = self.check(self.DUE, self.END)
        self.assertEqual((rc, line[-5:]), (1, " ok=0"), line)
        self.assertIn(" gens=2 first=2026-11-03T23:37:02Z last=2026-11-04T00:29:10Z ", line)


class LogrotateTests(PullCase):
    SED = 'sed -e "s|@LOGGLOB@|${DEFAULT_LOG_DIR}/*.log|" -e "s|@GROUP@|${TN_LOG_GROUP}|"'

    def text(self, size="20G"):
        return self.run_lib("bench_logrotate_text", size)

    def render(self, text, log_dir, group):
        """The node's step: fill the placeholders from its DEFAULT_LOG_DIR and TN_LOG_GROUP."""
        env = dict(self.env, DEFAULT_LOG_DIR=log_dir, TN_LOG_GROUP=group)
        p = subprocess.run(["bash", "-c", self.SED], env=env, input=text, stdout=subprocess.PIPE,
                           universal_newlines=True, check=True)
        return p.stdout

    def test_no_maxsize_the_header_and_the_placeholders(self):
        p = self.text()
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertTrue(lines[0].startswith("# Managed by benchmark"), lines[0])
        self.assertNotIn("maxsize", p.stdout)
        for want in ("@LOGGLOB@ {", "    su root @GROUP@", "    size 20G", "    copytruncate", "}"):
            self.assertIn(want, lines)
        for bad in ("", "20", "G", "2.5G", "20g", "20GB", "-1G", "20 G"):
            with self.subTest(size=bad):
                p = self.text(bad)
                self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)

    def test_it_is_the_v2_template_without_maxsize(self):
        if not V2_COMMON.is_file():
            self.skipTest("tn-node-deployment is not checked out")
        m = re.search(r"^_tn_logrotate_text\(\) \{\n.*?^EOF\n\}\n", V2_COMMON.read_text(), re.M | re.S)
        self.assertIsNotNone(m, "_tn_logrotate_text not found in the v2 library")
        env = dict(self.env, DEFAULT_LOG_DIR="/var/log/telcoin", TN_LOG_GROUP="telcoin-log")
        v2 = subprocess.run(["bash", "-c", m.group() + '_tn_logrotate_text "$1"', "_", "20G"], env=env,
                            stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout.splitlines()
        ours = self.render(self.text().stdout, "/var/log/telcoin", "telcoin-log").splitlines()
        v2_body = [line for line in v2[1:] if line.split() != ["maxsize", "1G"]]
        self.assertEqual(len(v2_body), len(v2) - 2, "the v2 template no longer has exactly one maxsize 1G line")
        self.assertEqual(ours[1:], v2_body)

    @unittest.skipUnless(shutil.which("logrotate"), "logrotate is not installed")
    def test_logrotate_parses_it(self):
        log_dir = self.root / "node-logs"
        log_dir.mkdir()
        (log_dir / "telcoin.log").write_text("x\n")
        user, group = pwd.getpwuid(os.getuid()).pw_name, grp.getgrgid(os.getgid()).gr_name
        rendered = self.render(self.text().stdout, str(log_dir), group)
        # The node runs logrotate as root under `su root <group>`; a debug run as a plain user cannot
        # switch to root, so this parse names the user instead (the directive's syntax is the same).
        rendered = rendered.replace("    su root ", "    su %s " % user)
        for label, text, ok in (("bench", rendered, True), ("bad size", rendered.replace("size 20G", "size 20Q"), False)):
            with self.subTest(case=label):
                conf = self.root / ("logrotate-%s.conf" % label.replace(" ", "-"))
                conf.write_text(text)
                conf.chmod(0o644)
                p = subprocess.run(["logrotate", "-d", "-s", str(self.root / "logrotate.state"), str(conf)],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
                if ok:
                    self.assertEqual(p.returncode, 0, p.stdout)
                    self.assertNotIn("error:", p.stdout)
                else:
                    self.assertNotEqual(p.returncode, 0, "logrotate -d accepted a bad size: the parse check proves nothing")


class DropTests(PullCase):
    def write(self, name, data):
        p = self.dest / name
        p.write_bytes(data)
        return p

    def drop(self, new, old):
        return self.run_lib("bench_drop_if_identical", new, old)

    def test_an_identical_copy_is_dropped(self):
        old = self.write("a-unit-stdout.log.gz", gzip.compress(b"line\n", mtime=0))
        new = self.write("a-unit-stdout-20261104T003616Z.log.gz", gzip.compress(b"line\n", mtime=0))
        p = self.drop(new, old)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(new.exists())
        self.assertTrue(old.exists())
        self.assertIn("is identical to a-unit-stdout.log.gz", p.stdout)

    def test_anything_else_is_kept(self):
        old = self.write("old.log.gz", b"one")
        new = self.write("new.log.gz", b"two")
        empty = self.write("empty.log.gz", b"")
        empty2 = self.write("empty2.log.gz", b"")
        link = self.dest / "link.log.gz"
        os.link(str(old), str(link))
        for label, a, b in (("different", new, old), ("same path", old, old), ("hard link", link, old),
                            ("missing new", self.dest / "gone.log.gz", old), ("missing existing", new, self.dest / "gone"),
                            ("both empty", empty, empty2)):
            with self.subTest(case=label):
                p = self.drop(a, b)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(sorted(f.name for f in self.dest.iterdir()),
                         ["empty.log.gz", "empty2.log.gz", "link.log.gz", "new.log.gz", "old.log.gz"])

    def test_an_unchanged_source_pulls_to_identical_bytes(self):
        # The premise of the drop for each way a pull gzips: a pipe (docker logs), a redirected file
        # (its mtime goes in the header, unchanged with the file), and -n (the rotated script).
        src = self.node / "telcoin.log"
        src.write_text(log_text(T0, 20))
        for cmd in ('cat "$1" | gzip -1', 'gzip -1 < "$1"', 'gzip -1 -n < "$1"'):
            with self.subTest(cmd=cmd):
                a, b = (subprocess.run(["bash", "-c", cmd, "_", str(src)], stdout=subprocess.PIPE, check=True).stdout
                        for _ in range(2))
                self.assertEqual(a, b)


class TimeTests(PullCase):
    def test_unix_and_iso_agree_with_the_calendar(self):
        instants = (0, 951782400, 1709164800, 1735689599, 1793744768, 4102444799)
        script = 'for t in "$@"; do i="$(_bench_pull_iso "$t")"; printf "%s %s %s\\n" "$t" "$i" "$(_bench_pull_unix "$i")"; done'
        p = self.run_lib("bash", "-c", "source \"$PULL_LIB\"; " + script, "_", *instants)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), ["%d %s %d" % (t, iso(t), t) for t in instants])

    def test_accepted_and_refused_forms(self):
        forms = {"1793744768": "1793744768", "2026-11-03T22:26:08Z": "1793744768", "2026-11-03 22:26:08": "1793744768",
                 "2026-11-03T22:26:08.158160337Z": "1793744768", "2026-11-03T22:26:08+00:00": "1793744768",
                 "-": "", "null": "", "": "", "2026-13-01T00:00:00Z": "", "2026-11-03T22:26:08+02:00": "",
                 "2026-11-03T22:26": "", "2026-11-03T22:26:08.12x": ""}
        for text, want in forms.items():
            with self.subTest(text=text):
                p = self.run_lib("bash", "-c", 'source "$PULL_LIB"; _bench_pull_unix "$1" || true', "_", text)
                self.assertEqual(p.stdout.strip(), want, p.stderr)


class SourceTests(PullCase):
    def test_sourcing_twice_defines_functions_and_nothing_else(self):
        # One line: a multi-line command string would put newlines in BASH_EXECUTION_STRING.
        script = ('set -euo pipefail; declare -p > "$1/before"; source "$PULL_LIB"; source "$PULL_LIB"; '
                  'declare -p > "$1/after"; declare -F')
        p = subprocess.run(["bash", "-c", script, "_", str(self.root)], env=self.env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        defined = {line.split()[-1] for line in p.stdout.splitlines()}
        self.assertEqual(sorted(set(PUBLIC) - defined), [])
        volatile = re.compile(r"^(BASH\w*|_|FUNCNAME|PIPESTATUS|LINENO|SECONDS|RANDOM|SRANDOM|EPOCH\w+|COLUMNS|LINES)$")

        def variables(name):
            out = {}
            for line in (self.root / name).read_text().splitlines():
                m = re.match(r"^declare -\S+ ([A-Za-z_]\w*)", line)
                if m and not volatile.match(m.group(1)):
                    out[m.group(1)] = line
            return out

        before, after = variables("before"), variables("after")
        self.assertEqual(sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), [],
                         "sourcing pull-lib.sh set or changed variables")


if __name__ == "__main__":
    unittest.main()
