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
          "bench_pull_rotated_logs", "bench_log_coverage_check", "bench_logrotate_text", "bench_drop_if_identical",
          "bench_bucket_write_scope", "bench_bucket_logs_script", "bench_pull_node_logs_bucket")

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



# ---------------------------------------------------------------------------------------------
# The whole node-log pull on a fake fleet: bench_pull_node_logs (bench-lib.sh, over IAP) and
# bench_pull_node_logs_bucket (this library, through the run bucket), run from the teardown's own
# call site. bench-lib.sh's pull functions are cut out by name (as test_certification.py does);
# GCP, the bucket and the nodes are fixtures/pull/fake-gcloud-fleet.py, the node's sudo and docker
# fixtures/pull/stub-{sudo,docker}.sh.

BENCH_LIB = (BENCH / "bench-lib.sh").read_text()
TEARDOWN = (BENCH / "benchmark-teardown.sh").read_text()
GS = "gs" + "://"
RUN = "r20991231-0101"
BUCKET = "tn-" + "devnet-bench-" + RUN
FLEET = ("bench-validator-01", "bench-validator-02", "bench-validator-03")
FLEET_ZONES = ("us-west2-a", "europe-west2-b", "asia-northeast1-c")
SCOPE = "https://www.googleapis.com/auth/"
LIB_FUNCTIONS = (
    "bench_warn", "bench_now_iso", "bench_now_unix", "bench_iso_from_unix", "_bench_in_lines", "_bench_log_name_ok",
    "_bench_unstamp_names", "_bench_log_sources_of", "_bench_logs_here", "_bench_marker_verdict",
    "bench_node_vouched_logs", "bench_instance_json", "_bench_instance_ident", "_bench_unit_log_cmd",
    "_bench_pull_node_log", "_bench_pull_unit_log", "_bench_saved_log_cmd_skip", "_bench_saved_log_cmd",
    "_bench_pull_saved_logs", "_bench_write_marker", "_bench_pull_rc", "_bench_pull_node", "bench_pull_node_logs",
    "bench_bucket_names")
LIB_ASSIGNMENTS = ("BENCH_NODE_LOG_DIR", "BENCH_PULL_MARKER_V", "BENCH_MARKER_MAX_AGE_SECS", "BENCH_NODE_UNIT_LOGS")
GOLDEN = FIX / "iap-golden.json"


def shell_function(source, name):
    """The text of shell function <name> in <source>: a block ending in a column-0 brace, or one line."""
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.M | re.S) \
        or re.search(r"^%s\(\) \{ .*\}\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("function %s not found" % name)
    return m.group()


def shell_assignment(source, name):
    m = re.search(r"^%s=.*\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("assignment %s not found" % name)
    return m.group()


def pull_call_site(teardown):
    """The teardown's pull: from `pull_rc=0` through `stop_if_reauth "the log pull"`, its if closed."""
    m = re.search(r"^pull_rc=0\n.*?^    stop_if_reauth \"the log pull\"\n", teardown, re.M | re.S)
    if not m:
        raise AssertionError("the teardown's pull call site was not found")
    return m.group() + "fi\n"


FLEET_SHIM = (
    "set -euo pipefail\n"
    'source "${DEVNET_LIB}"\n'
    "declare -F tn_iap_fault_kind >/dev/null || tn_iap_fault_kind() {\n"
    '    [ "$1" -eq 0 ] && { echo ok; return 0; }\n'
    '    grep -Eq -- "Reauthentication failed|There was a problem refreshing your current auth tokens|invalid_grant" "$2" '
    "&& { echo reauth; return 0; }\n"
    '    { [ "$1" -eq 255 ] || grep -q \'gcloud crashed\' "$2"; } && { echo transport; return 0; }\n'
    "    echo other\n"
    "}\n"
    "sleep() { printf '%s\\n' \"$1\" >> \"${FAKE_ROOT}/sleeps\"; }\n"
    + "".join(shell_assignment(BENCH_LIB, n) for n in LIB_ASSIGNMENTS)
    + "".join(shell_function(BENCH_LIB, n) for n in LIB_FUNCTIONS)
    + 'source "${PULL_LIB}"\n'
    + "stop_if_reauth() { [ -e \"${BENCH_PULL_STOP_FILE}\" ] && echo \"STOP_IF_REAUTH $1\" || true; }\n"
    + 'LOG_DIR="$1"; shift\n'
    + 'PULL_NAMES=(); PULL_ZONES=()\n'
    + 'while [ "$#" -gt 0 ]; do PULL_NAMES+=("$1"); PULL_ZONES+=("$2"); shift 2; done\n')


def gz0(text):
    """gzip of <text> with a zero time in the header, so the bytes depend on the text alone."""
    return gzip.compress(text.encode(), mtime=0)


class FleetCase(unittest.TestCase):
    """Three fake nodes with every kind of log the pull takes: the current container's log, a saved
    log, the unit's stdout and stderr files, and two rotated generations of stdout (.1 plain, .2.gz)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pull-fleet-")
        self.root = Path(self._tmp.name)
        self.bin, self.state, self.tmpdir = self.root / "bin", self.root / "state", self.root / "tmp"
        self.dest = self.root / "results" / RUN / "logs"
        for d in (self.bin, self.state, self.tmpdir, self.dest.parent, self.state / "gcs" / BUCKET):
            d.mkdir(parents=True)
        for name, src in (("gcloud", "fake-gcloud-fleet.py"), ("sudo", "stub-sudo.sh"), ("docker", "stub-docker.sh")):
            shutil.copyfile(str(FIX / src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        config = self.root / "config.sh"
        config.write_text("# empty: the test environment sets what devnet-lib.sh reads\n")
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "LC_ALL": "C",
            "FAKE_ROOT": str(self.state), "PROJECT_ID": "acme-project", "CONFIG_FILE": str(config),
            "TN_SSH_TRANSPORT": "iap", "TN_IAP_RETRIES": "0", "BENCH_IAP_RETRIES": "1",
            "BENCH_APPLY": "1", "BENCH_RUN_ID": RUN, "BENCH_BUCKET": BUCKET,
            "BENCH_PULL_STOP_FILE": str(self.state / "pull-stop"),   # the teardown exports one of its own
            "DEVNET_LIB": str(DEVNET_LIB), "PULL_LIB": str(PULL_LIB),
        }
        self.set_instances(FLEET)
        for i, inst in enumerate(FLEET):
            self.give_logs(inst, i)

    def tearDown(self):
        self._tmp.cleanup()

    def set_instances(self, names, scopes=("cloud-platform",)):
        (self.state / "instances.json").write_text(json.dumps([
            {"name": n, "zone": "projects/acme-project/zones/" + FLEET_ZONES[FLEET.index(n)], "id": str(4200 + i),
             "creationTimestamp": "2026-11-05T00:00:00.000-08:00", "status": "RUNNING",
             "serviceAccounts": [{"email": "bench@acme-project.iam.gserviceaccount.com",
                                  "scopes": [SCOPE + s for s in scopes]}]}
            for i, n in enumerate(names)]))

    def give_logs(self, inst, k):
        node = self.state / "nodes" / inst
        unit = node / "var" / "log" / "telcoin"
        saved = node / "var" / "lib" / "bench-logs"
        unit.mkdir(parents=True)
        saved.mkdir(parents=True)
        (unit / "telcoin.log").write_text(log_text(T0, 60 + k))
        (unit / "telcoin.log.1").write_text(log_text(T0 - 3600, 30 + k))
        (unit / "telcoin.log.2.gz").write_bytes(gz0(log_text(T0 - 7200, 20 + k)))
        (unit / "telcoin-error.log").write_text("an error on %s\n" % inst)
        (saved / "telcoin-cert-fail-20261105T120000Z.log.gz").write_bytes(gz0("saved snapshot of %s\n" % inst))
        (node / "container.log").write_text(log_text(T0 + 1800, 40 + k))

    def pull(self, names=FLEET[:1], teardown=None, **extra):
        """The teardown's call site (pull_call_site) for <names>; its stdout, stderr and pull_rc."""
        env = dict(self.env)
        env.update(extra)
        script = FLEET_SHIM + pull_call_site(TEARDOWN if teardown is None else teardown) + 'echo "PULL_RC=${pull_rc}"\n'
        args = [str(self.dest)]
        for n in names:
            args += [n, FLEET_ZONES[FLEET.index(n)]]
        p = subprocess.run(["bash", "-c", script, "fleet-test"] + args, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=300)
        m = re.search(r"^PULL_RC=(\d+)$", p.stdout, re.M)
        self.assertIsNotNone(m, p.stdout + p.stderr)
        return p, int(m.group(1))

    def calls(self, name="calls.jsonl"):
        p = self.state / name
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def ssh_calls(self):
        return [c for c in self.calls() if c["argv"][:2] == ["compute", "ssh"]]

    def marker(self, inst):
        m = self.dest / (inst + ".pulled")
        return m.read_text() if m.exists() else None

    def marker_rows(self, inst):
        """The marker's file rows, {name: bytes}, and its sources line."""
        text = self.marker(inst) or ""
        rows = {line.split()[2]: int(line.split()[1]) for line in text.splitlines() if line.startswith("file ")}
        src = [line[len("sources "):] for line in text.splitlines() if line.startswith("sources ")]
        return rows, (src[0] if src else None)

    def landed(self):
        return {p.name: p.stat().st_size for p in self.dest.iterdir() if p.is_file() and not p.name.startswith(".")} \
            if self.dest.exists() else {}

    def leftovers(self):
        left = [p.name for p in self.dest.iterdir() if p.name.startswith(".") and not p.name.endswith(".pulled")] \
            if self.dest.exists() else []
        return sorted(left + ["tmp/" + p.name for p in self.tmpdir.iterdir()])

    def normalized(self, text):
        text = text.replace(str(self.root), "<ROOT>")
        text = re.sub(STAMP_RE, "<STAMP>", text)
        return re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "<TIME>", text)

    def capture(self, p):
        """What the golden pins: every gcloud call (argv, stdin, session), stdout, stderr, the marker
        and the landed files with their sizes, with the temp root, stamps and pull times normalized."""
        return {
            "calls": [{k: (self.normalized(v) if isinstance(v, str) else [self.normalized(a) for a in v])
                       for k, v in c.items()} for c in self.calls()],
            "node_calls": self.calls("node-calls.jsonl"),
            "stdout": self.normalized(p.stdout).splitlines(),
            "stderr": self.normalized(p.stderr).splitlines(),
            "markers": {i: self.normalized(self.marker(i) or "") for i in FLEET if self.marker(i)},
            "files": self.landed(),
        }


@unittest.skipUnless(shutil.which("jq") and shutil.which("tar"), "needs jq and tar")
class IapGoldenTests(FleetCase):
    def test_the_default_transfer_is_the_bench_4_iap_pull_byte_for_byte(self):
        # Captured from the pull before the bucket transfer existed (pull-lib.sh and the teardown's
        # one-line call site as they were): argv and stdin of every session, stdout, stderr, the marker.
        want = json.loads(GOLDEN.read_text())
        for extra in ({}, {"BENCH_LOG_TRANSFER": "iap"}):
            with self.subTest(**extra):
                shutil.rmtree(str(self.dest), ignore_errors=True)
                for f in ("calls.jsonl", "node-calls.jsonl"):
                    if (self.state / f).exists():
                        (self.state / f).unlink()
                p, rc = self.pull(**extra)
                self.assertEqual(rc, 0, p.stdout + p.stderr)
                self.assertEqual(self.capture(p), want)
                self.assertNotIn("LOG_TRANSFER", p.stdout)



def gcloud_inventory():
    """td_gcloud_argv (benchmark-teardown.sh) with devnet-lib.sh's TN_SSH_FLAGS: {command words: flags}."""
    script = 'source "$1" >/dev/null 2>&1; ' + shell_function(TEARDOWN, "td_gcloud_argv") + "td_gcloud_argv\n"
    out = subprocess.run(["bash", "-c", script, "_", str(DEVNET_LIB)], stdout=subprocess.PIPE, universal_newlines=True,
                         check=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                          "CONFIG_FILE": os.devnull, "TN_SSH_TRANSPORT": "iap"}).stdout
    inv = {}
    for line in out.splitlines():
        words = line.split()
        inv[tuple(w for w in words if not w.startswith("-"))] = {w for w in words if w.startswith("-")}
    return inv


@unittest.skipUnless(shutil.which("jq") and shutil.which("tar") and shutil.which("mkfifo"), "needs jq, tar and mkfifo")
class BucketTransferTests(FleetCase):
    """BENCH_LOG_TRANSFER=bucket through the teardown's call site: one session per node that sends every
    log to the run bucket from the node, one local download, then the IAP pull's files and markers."""

    EXPECTED = ("telcoin.log.gz", "telcoin-cert-fail-20261105T120000Z.log.gz", "unit-stdout.log.gz",
                "unit-stderr.log.gz", "unit-stdout.rotated-1.log.gz", "unit-stdout.rotated-2.log.gz")

    def bucket(self, names=FLEET, **extra):
        return self.pull(names=names, BENCH_LOG_TRANSFER="bucket", **extra)

    def objects(self):
        base = self.state / "gcs" / BUCKET
        return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())

    def logs(self):
        return {p.name: p.read_bytes() for p in self.dest.iterdir()
                if p.is_file() and (p.name.endswith(".log.gz") or p.name.endswith(".logspan"))}

    def reset_calls(self):
        for f in ("calls.jsonl", "node-calls.jsonl"):
            if (self.state / f).exists():
                (self.state / f).unlink()

    def assert_local_calls_listed(self):
        """Every gcloud call made on the operator's side is on its td_gcloud_argv line (A10's inventory)."""
        inv = gcloud_inventory()
        for c in self.calls():
            words = tuple(a for a in c["argv"] if not a.startswith("-"))
            flags = {a.split("=", 1)[0] for a in c["argv"] if a.startswith("-")}
            cmd = next((k for k in inv if words[:len(k)] == k), None)
            self.assertIsNotNone(cmd, "not in td_gcloud_argv: gcloud " + " ".join(c["argv"]))
            self.assertEqual(flags - inv[cmd], set(), "td_gcloud_argv lacks a flag of gcloud " + " ".join(c["argv"]))

    def test_one_session_per_node_one_download_and_the_iap_pulls_files_and_markers(self):
        # The IAP pull of the same three nodes first: what the bucket transfer must reproduce.
        p, rc = self.pull(names=FLEET)
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        iap_logs = self.logs()
        iap_rows = {i: self.marker_rows(i) for i in FLEET}
        shutil.rmtree(str(self.dest))
        self.reset_calls()

        p, rc = self.bucket(BENCH_PULL_JOBS="2")
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        out = p.stdout
        # One session per node, each a `sudo bash -s` script that streams every log to the bucket.
        ssh = self.ssh_calls()
        self.assertEqual(sorted(c["argv"][2] for c in ssh), sorted(FLEET))
        for c in ssh:
            inst = c["argv"][2]
            self.assertEqual(c["session"], "# bench-pull: bucket")
            self.assertIn("--command=sudo bash -s", c["argv"])
            self.assertIn("--tunnel-through-iap", c["argv"])
            self.assertIn("\ninst=%s\ndst=%s%s/logs/%s\n" % (inst, GS, BUCKET, inst), c["stdin"])
            self.assertIn('"$@" | tee -- "$w/f" | gcloud storage cp - "$dst/$o"', c["stdin"])
            self.assertIn("clog() { docker logs telcoin 2>&1 | gzip -1; }", c["stdin"])
            self.assertIn("gz1() { gzip -1 < \"$1\"; }", c["stdin"])
            self.assertIn("gzn() { gzip -1 -n < \"$1\"; }", c["stdin"])
            self.assertIn("pairs=( stdout:/var/log/telcoin/telcoin.log stderr:/var/log/telcoin/telcoin-error.log )",
                          c["stdin"])
        # The node's own gcloud sent each log, rotated generations included, to <bucket>/logs/<inst>/ in GCS.
        sent = sorted((c["node"], c["argv"][-1]) for c in self.calls("node-calls.jsonl"))
        self.assertEqual(sent, sorted((i, "%s%s/logs/%s/%s-%s" % (GS, BUCKET, i, i, n)) for i in FLEET for n in self.EXPECTED))
        for c in self.calls("node-calls.jsonl"):
            self.assertEqual(c["argv"][:3], ["storage", "cp", "-"])
        # Then exactly one download, after every session, and the objects are removed after it.
        local = [c["argv"] for c in self.calls() if c["argv"][:1] == ["storage"]]
        self.assertEqual([a[:3] for a in local], [["storage", "buckets", "list"], ["storage", "cp", "-r"],
                                                  ["storage", "rm", GS + BUCKET + "/logs/**"]])
        download = next(a for a in local if a[:2] == ["storage", "cp"])
        self.assertEqual(download[3], GS + BUCKET + "/logs/*")
        self.assertTrue(download[4].startswith(str(self.dest) + "/.bucket-pull.") and download[4].endswith("/objects/"))
        order = [c["argv"][:2] for c in self.calls()]
        self.assertLess(max(i for i, a in enumerate(order) if a == ["compute", "ssh"]), order.index(["storage", "cp"]))
        self.assertEqual(self.objects(), [], "the logs left in the bucket would be copied again by the bucket backup")
        self.assert_local_calls_listed()
        # The same files, byte for byte, the same spans, and markers with the same rows and sources.
        self.assertEqual(self.logs(), iap_logs)
        for inst in FLEET:
            self.assertEqual(self.marker_rows(inst), iap_rows[inst])
            self.assertEqual(self.marker_rows(inst)[1], "current-container log, 1 saved log(s), unit stdout, "
                                                        "unit stderr, 2 rotated unit stdout log(s)")
            self.assertIn("      ✓ %s: current-container log, 1 saved log(s)" % inst, out)
        # The stdout markers bracket the transfer; bytes = what the nodes sent = the landed logs.
        self.assertTrue(out.startswith("LOG_TRANSFER mode=bucket nodes=3\n"), out)
        done = re.search(r"^LOG_TRANSFER_DONE mode=bucket bytes=(\d+) secs=(\d+)$", out, re.M)
        self.assertIsNotNone(done, out)
        self.assertEqual(int(done.group(1)), sum(len(b) for n, b in self.logs().items() if n.endswith(".log.gz")))
        self.assertLess(out.index("LOG_TRANSFER mode=bucket"), out.index("↑ "))
        self.assertLess(out.index("LOG_TRANSFER_DONE"), out.index("    ✓ logs of 3 nodes in "))
        self.assertNotIn("STOP_IF_REAUTH", out)
        self.assertEqual(self.leftovers(), [])

    def test_a_node_whose_session_fails_is_recorded_and_the_others_complete(self):
        for knob, why in ((dict(FAKE_SSH_FAIL=FLEET[1]), "✗ %s: the bucket session failed (rc 2)" % FLEET[1]),
                          (dict(FAKE_UPLOAD_FAIL=FLEET[1] + "-unit-stdout.rotated-1"),
                           "✗ %s: %s-unit-stdout.rotated-1.log.gz: the node could not send it" % (FLEET[1], FLEET[1])),
                          (dict(FAKE_DOWNLOAD="skip:%s-unit-stderr" % FLEET[1]),
                           "✗ %s: %s-unit-stderr.log.gz was not downloaded" % (FLEET[1], FLEET[1]))):
            with self.subTest(**knob):
                if self.dest.exists():
                    shutil.rmtree(str(self.dest))
                self.reset_calls()
                p, rc = self.bucket(**knob)
                self.assertEqual(rc, 1, p.stdout + p.stderr)
                self.assertIn(why, p.stderr)
                self.assertIn("❌ node logs not pulled from: %s\n" % FLEET[1], p.stderr)
                self.assertIsNone(self.marker(FLEET[1]), "a node with a failed transfer gets no marker")
                for inst in (FLEET[0], FLEET[2]):
                    self.assertEqual(sorted(self.marker_rows(inst)[0]), sorted("%s-%s" % (inst, n) for n in self.EXPECTED))
                self.assertEqual(len([c for c in self.calls() if c["argv"][:2] == ["storage", "cp"]]), 1)
                self.assertRegex(p.stdout, r"(?m)^LOG_TRANSFER_DONE mode=bucket bytes=\d+ secs=\d+$")
                self.assertEqual(self.leftovers(), [])
                self.assertEqual(self.objects(), [])

    def test_a_re_run_sends_only_what_no_marker_vouches_for(self):
        p, rc = self.bucket(names=FLEET[:1])
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        first = self.logs()
        self.reset_calls()
        p, rc = self.bucket(names=FLEET[:1])
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        # The marker vouches for everything but the current container's log, which is always taken:
        # it lands beside the first copy, is identical, and is dropped again.
        self.assertEqual([c["argv"][-1] for c in self.calls("node-calls.jsonl")],
                         ["%s%s/logs/%s/%s-telcoin.log.gz" % (GS, BUCKET, FLEET[0], FLEET[0])])
        self.assertIn("- %s: %s-telcoin.log.gz counts as this pull's (the copy just pulled was identical)"
                      % (FLEET[0], FLEET[0]), p.stdout)
        self.assertEqual(self.logs(), first)
        self.assertEqual(len(list(self.dest.glob(FLEET[0] + ".pulled*"))), 2)

    def test_the_preflight_refuses_a_fleet_that_cannot_write_to_the_bucket(self):
        read_only = ("devstorage.read_only", "logging.write", "monitoring.write")
        for case in ("scopes", "bucket"):
            with self.subTest(case=case):
                self.reset_calls()
                if case == "scopes":
                    self.set_instances(FLEET, scopes=read_only)
                else:
                    self.set_instances(FLEET)
                    shutil.rmtree(str(self.state / "gcs" / BUCKET))
                p, rc = self.bucket()
                self.assertEqual(rc, 1, p.stdout + p.stderr)
                self.assertIn("❌ BENCH_LOG_TRANSFER=bucket cannot run here (✗ above) — nothing was sent; run with "
                              "BENCH_LOG_TRANSFER=iap", p.stderr)
                if case == "scopes":
                    for inst in FLEET:
                        self.assertIn("✗ %s: the access scopes of its service account (%s) allow no GCS write"
                                      % (inst, ",".join(read_only)), p.stderr)
                else:
                    self.assertIn("✗ the run bucket %s%s does not exist" % (GS, BUCKET), p.stderr)
                self.assertEqual(self.ssh_calls(), [])
                self.assertEqual(self.calls("node-calls.jsonl"), [])
                self.assertFalse(self.dest.exists(), "nothing created")
                self.assertNotIn("LOG_TRANSFER_DONE", p.stdout)
                # A dry run says the same and goes on with its plan.
                self.reset_calls()
                p, rc = self.bucket(BENCH_APPLY="0")
                self.assertEqual(rc, 0, p.stdout + p.stderr)
                self.assertIn("✗ with --yes the bucket transfer stops here, before any session: run with "
                              "BENCH_LOG_TRANSFER=iap", p.stdout)
                self.assertIn("      (dry run — not executed)", p.stdout)
                self.assertEqual([c["argv"][:2] for c in self.calls() if c["argv"][:2] != ["compute", "instances"]],
                                 [["storage", "buckets"]])
                self.assertFalse(self.dest.exists())
                (self.state / "gcs" / BUCKET).mkdir(parents=True, exist_ok=True)

    def bare(self, overrides):
        """bench_pull_node_logs_bucket called bare under the shim's `set -e` (the teardown's subshell turns
        errexit off; a caller that does not must still get the per-node failure, not a silent abort)."""
        script = (FLEET_SHIM + overrides + 'INSTANCE_NAMES=("${PULL_NAMES[@]}"); ZONES=("${PULL_ZONES[@]}")\n'
                  'bench_pull_node_logs_bucket "${LOG_DIR}" "${BENCH_BUCKET}"\necho "BARE_RC=0"\n')
        args = [str(self.dest)]
        for n in FLEET:
            args += [n, FLEET_ZONES[FLEET.index(n)]]
        return subprocess.run(["bash", "-c", script, "fleet-test"] + args, stdin=subprocess.DEVNULL,
                              env=dict(self.env, BENCH_LOG_TRANSFER="bucket"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=300)

    def test_a_failed_lookup_fails_that_node_with_its_message_under_set_e(self):
        # The preflight's describe (bench_instance_json) fails: every node gets its ✗ line, then the refusal.
        p = self.bare("bench_instance_json() { return 1; }\n")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        for inst in FLEET:
            self.assertIn("✗ %s: the access scopes of its service account (none) allow no GCS write" % inst, p.stderr)
        self.assertIn("❌ BENCH_LOG_TRANSFER=bucket cannot run here", p.stderr)
        self.assertEqual(self.ssh_calls(), [])
        # The instance id lookup fails before the session: each node says so and is not pulled.
        self.reset_calls()
        p = self.bare("_bench_instance_ident() { return 1; }\n")
        self.assertNotIn("BARE_RC=0", p.stdout)
        for inst in FLEET:
            self.assertIn("✗ %s: its instance id could not be looked up — not pulled (the marker must name it)" % inst,
                          p.stderr)
        self.assertEqual(self.ssh_calls(), [])
        # The second lookup (after the download, before the marker) fails: no marker, and the node says why.
        self.reset_calls()
        once = ('eval "$(declare -f _bench_instance_ident | sed \'1s/_bench_instance_ident/_first_ident/\')"\n'
                '_bench_instance_ident() { [ ! -e "${FAKE_ROOT}/ident-$1" ] || return 1; : > "${FAKE_ROOT}/ident-$1"; '
                '_first_ident "$@"; }\n')
        p = self.bare(once)
        self.assertNotIn("BARE_RC=0", p.stdout)
        for inst in FLEET:
            self.assertIn("✗ %s: the instance changed during the pull (" % inst, p.stderr)
            self.assertIsNone(self.marker(inst), inst)

    def test_a_dry_run_plans_the_sessions_and_the_two_local_calls(self):
        p, rc = self.bucket(BENCH_APPLY="0")
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        out = p.stdout
        self.assertTrue(out.startswith("LOG_TRANSFER mode=bucket nodes=3\n"), out)
        for inst in FLEET:
            self.assertIn("+ tn_iap_ssh_stdin %s %s <<< \"$(bench_bucket_logs_script %s %s)\"" % (
                inst, FLEET_ZONES[FLEET.index(inst)], inst, BUCKET), out)
        self.assertIn("    + gcloud storage cp -r %s%s/logs/\\* " % (GS, BUCKET), out)
        self.assertIn("    + gcloud storage rm %s%s/logs/\\*\\* --project=acme-project" % (GS, BUCKET), out)
        self.assertNotIn("LOG_TRANSFER_DONE", out)
        self.assertEqual(self.ssh_calls(), [])
        self.assertFalse(self.dest.exists())

    def test_reauth_during_the_download_stops_with_nothing_marked(self):
        p, rc = self.bucket(FAKE_REAUTH="download")
        self.assertEqual(rc, 1, p.stdout + p.stderr)
        self.assertIn("STOP_IF_REAUTH the log pull", p.stdout)
        self.assertIn("Reauthentication failed", p.stderr)
        self.assertIn("❌ node logs: gcloud needs re-authentication; 0 node(s) not attempted; not pulled from: "
                      + " ".join(FLEET), p.stderr)
        self.assertEqual([i for i in FLEET if self.marker(i)], [])
        self.assertEqual([c["argv"][:2] for c in self.calls() if c["argv"][:2] == ["storage", "rm"]], [],
                         "no further gcloud call once it needs re-authentication")
        self.assertIn("the objects under %s%s/logs/ are left (gcloud needs re-authentication)" % (GS, BUCKET), p.stderr)
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()


# ---- bench6 prefilter and persist files (H6a) ----
# D44: bench_logs_prefilter keeps the lines tools/log-shapes.txt names, one job per log; the readers
# (tools/cert-rate.py, report/provenance.py, the certification record) must report the same from the
# copy as from the full logs. bench_pull_persist_files lands the persist sampler's two files.
CERT_RATE = BENCH / "tools" / "cert-rate.py"
SHAPES = BENCH / "tools" / "log-shapes.txt"
ANALYSIS_FIX = TESTS / "fixtures" / "analysis"
PROV_FIX = TESTS / "fixtures" / "provenance"
PREFILTER_SHIM = 'set -euo pipefail; source "$PULL_LIB"; "$@"'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shape_lines():
    """The patterns of tools/log-shapes.txt: its lines but the "#" comments."""
    return [line for line in SHAPES.read_text().split("\n")[:-1] if not line.startswith("#")]


# The shapes kept for other units' tools (tools/arms-summary.py, tools/stage-latency.py): they read the
# prefiltered copy when it holds what they match, else stream the full logs.
OTHER_TOOLS_SHAPES = ("Failed to track spawned task", "batch built", "batch reported", "batch sealed",
                      "consensus output ready", "digests resent", "header uncertified", "next block executed",
                      "output executed", "output execution task finished", "output queued", "output saved",
                      "subdag sequenced", "vote path timing", "waited for execution before assembling the output")


class ShapeCoverageTests(unittest.TestCase):
    def test_every_literal_a_reader_matches_is_a_shape(self):
        shapes = shape_lines()
        self.assertTrue(SHAPES.read_text().endswith("\n"))
        self.assertNotIn("", SHAPES.read_text().split("\n")[:-1], "an empty line in a grep -f file matches every line")
        self.assertEqual(len(shapes), len(set(shapes)))
        cert = _load("cert_rate_shapes", CERT_RATE)
        events = cert.EVENT_RE.pattern.split("|")
        for lit in events:
            self.assertRegex(lit, r"^[A-Za-z0-9 _-]+$", "cert-rate's EVENT_RE alternative %r is not a literal" % lit)
        prov = _load("provenance_shapes", PROVENANCE)
        markers = [m.decode() for m in prov._CANDIDATE_MARKERS]
        missing = [lit for lit in events + markers if lit not in shapes]
        self.assertEqual(missing, [], "tools/log-shapes.txt lacks what a reader matches")
        # The bench-6 node lines the report code reads.
        for lit in ("node switches", "persisted output"):
            self.assertIn(lit, shapes)
        # The file may hold more than these readers match: the other tools' shapes, under their comment.
        lines = SHAPES.read_text().split("\n")[:-1]
        at = lines.index("# for tools/arms-summary.py and tools/stage-latency.py:")
        self.assertEqual(lines[at + 1:at + 1 + len(OTHER_TOOLS_SHAPES)], list(OTHER_TOOLS_SHAPES))


class PrefilterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="prefilter-")
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "results" / "r1"
        self.logs = self.run_dir / "logs"
        self.out = self.root / "work" / "prefilter" / "r1"
        self.logs.mkdir(parents=True)
        noise = "".join('ts=2026-10-06T06:0%d:00.000000000Z level=debug target=x message="noise %d"\n' % (i % 10, i)
                        for i in range(200))
        v1 = (ANALYSIS_FIX / "node-logs" / "bench-validator-01-telcoin.log").read_text()
        v2 = (ANALYSIS_FIX / "node-logs" / "bench-validator-02-telcoin.log").read_text()
        files = {
            "bench-validator-01-unit-stdout.log.gz": noise + v1 + noise + (PROV_FIX / "node-log-validator-unit-stdout.txt").read_text(),
            "bench-validator-02-unit-stdout.log.gz": v2 + noise,
            "bench-validator-02-unit-stdout.rotated-1.log.gz": noise + v2,
            "bench-validator-01-telcoin.log.gz": (PROV_FIX / "node-log-validator-container.txt").read_text() + v1,
            "bench-validator-03-telcoin-pre-kill-20260101T000000Z.log.gz": (PROV_FIX / "node-log-adiri.txt").read_text(),
            "bench-observer-11-telcoin.log": (PROV_FIX / "node-log-observer-json.txt").read_text() + "a\rline starting here\r\n",
            "deploy-20260101T000000Z.log": (PROV_FIX / "deploy-output.txt").read_text(),
        }
        for name, text in files.items():
            data = text.encode()
            (self.logs / name).write_bytes(gzip.compress(data, mtime=0) if name.endswith(".gz") else data)
        (self.logs / "bench-validator-01.pulled").write_text("marker\n")
        (self.logs / ".hidden.log").write_text("starting\n")
        m = json.loads((ANALYSIS_FIX / "manifest.json").read_text())
        m.update({"node_git_sha": "ba43a1f0e270ca1c572d1b8378b39d2fc6360b57", "node_fork_schedule": "subsecond-from-genesis"})
        (self.run_dir / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root), "TMPDIR": str(self.root),
                    "PULL_LIB": str(PULL_LIB), "BENCH_DIR": str(BENCH), "BENCH_APPLY": "1"}

    def tearDown(self):
        self._tmp.cleanup()

    def prefilter(self, *extra_args, **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run(["bash", "-c", PREFILTER_SHIM, "_", "bench_logs_prefilter", str(self.logs), str(self.out)]
                              + list(extra_args), env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=120)

    def tool(self, *argv, **kw):
        p = subprocess.run(["python3"] + [str(a) for a in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=120)
        self.assertIn(p.returncode, kw.get("rcs", (0,)), p.stderr)
        return p.stdout if "rcs" not in kw else (p.returncode, p.stdout)

    def test_every_reader_reports_the_same_from_the_prefiltered_copy(self):
        p = self.prefilter()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"PREFILTER logs=7 read=7 reused=0 in_bytes=\d+ out_bytes=\d+ secs=\d+ failed=0\n$")
        copy = self.out / "logs"
        self.assertEqual(sorted(x.name for x in copy.iterdir()), sorted(x.name for x in self.logs.iterdir()
                                                                         if x.name.endswith((".log", ".log.gz"))
                                                                         and not x.name.startswith(".")))
        full_bytes = sum(len(gzip.decompress(x.read_bytes())) for x in self.logs.glob("*-unit-stdout*.log.gz"))
        copy_bytes = sum(len(gzip.decompress(x.read_bytes())) for x in copy.glob("*-unit-stdout*.log.gz"))
        self.assertLess(copy_bytes * 2, full_bytes)
        manifest = self.run_dir / "manifest.json"
        for glob in ("bench-validator-*-unit-stdout*.log.gz", "bench-validator-*.log.gz"):
            for fmt in ("md", "json", "csv"):
                with self.subTest(glob=glob, fmt=fmt):
                    full = self.tool(CERT_RATE, "--logs", self.logs, "--windows", manifest, "--node-glob", glob, "--format", fmt)
                    self.assertEqual(self.tool(CERT_RATE, "--logs", copy, "--windows", manifest, "--node-glob", glob,
                                               "--format", fmt), full)
                    self.assertIn("bench-validator-02", full)
        # The certification record's JSON renders the same cert-rate.md the logs give (the teardown's
        # analysis/cert-rate.md, cert-rate.py --from-json).
        record = self.root / "certification.json"
        record.write_text(self.tool(CERT_RATE, "--logs", copy, "--windows", manifest, "--format", "json"))
        self.assertEqual(self.tool(CERT_RATE, "--from-json", record),
                         self.tool(CERT_RATE, "--logs", self.logs, "--windows", manifest))
        # Provenance: the copy as a run directory beside a copy of the manifest, as the teardown runs it.
        shutil.copyfile(str(manifest), str(self.out / "manifest.json"))
        # checked_at is the wall-clock second each run made its check: not part of what the logs say.
        def stable(doc):
            if isinstance(doc, dict):
                return {k: stable(v) for k, v in doc.items() if k != "checked_at"}
            return [stable(v) for v in doc] if isinstance(doc, list) else doc
        rc, full = self.tool(PROVENANCE, "--run-dir", self.run_dir, "--json", rcs=(0, 1))
        rc2, copied = self.tool(PROVENANCE, "--run-dir", self.out, "--json", rcs=(0, 1))
        self.assertIn("checked_at", json.loads(full))
        self.assertEqual((rc2, stable(json.loads(copied))), (rc, stable(json.loads(full))))
        self.assertTrue(json.loads(full)["starts"])
        rc, text = self.tool(PROVENANCE, "--run-dir", self.run_dir, rcs=(0, 1))
        rc2, text2 = self.tool(PROVENANCE, "--run-dir", self.out, rcs=(0, 1))
        self.assertEqual((rc2, text2.split("\n", 1)[1]), (rc, text.split("\n", 1)[1]))

    def test_a_second_pass_reads_only_new_logs_and_drops_copies_of_gone_ones(self):
        self.assertEqual(self.prefilter().returncode, 0)
        (self.logs / "bench-validator-02-telcoin-cert-fail-20260101T000000Z.log.gz").write_bytes(gzip.compress(b"x starting\n"))
        (self.logs / "deploy-20260101T000000Z.log").unlink()
        p = self.prefilter()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("PREFILTER logs=7 read=1 reused=6 ", p.stdout)
        self.assertFalse((self.out / "logs" / "deploy-20260101T000000Z.log").exists())
        self.assertEqual(gzip.decompress((self.out / "logs" / "bench-validator-02-telcoin-cert-fail-20260101T000000Z.log.gz")
                                         .read_bytes()), b"x starting\n")

    def test_a_cut_log_fails_the_pass_and_keeps_no_copy_of_it(self):
        whole = (self.logs / "bench-validator-02-unit-stdout.log.gz").read_bytes()
        (self.logs / "bench-validator-02-unit-stdout.log.gz").write_bytes(whole[:len(whole) // 2])
        p = self.prefilter(BENCH_PREFILTER_JOBS="2")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("✗ bench-validator-02-unit-stdout.log.gz rc=1 ", p.stderr)
        self.assertIn(" failed=1\n", p.stdout)
        self.assertFalse((self.out / "logs" / "bench-validator-02-unit-stdout.log.gz").exists())
        self.assertEqual([x.name for x in (self.out / "logs").iterdir() if x.name.startswith(".")], [])

    def test_comment_lines_are_no_pattern_and_new_shapes_redo_every_copy(self):
        (self.logs / "deploy-20260101T000000Z.log").write_text("# not a shape\nkeep starting here\n")
        shapes = self.root / "shapes.txt"
        shapes.write_text("# not a shape\nstarting\n")
        p = self.prefilter(str(shapes))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.out / "logs" / "deploy-20260101T000000Z.log").read_text(), "keep starting here\n")
        self.assertEqual((self.out / ".shapes.txt").read_text(), "starting\n")
        self.assertIn("PREFILTER logs=7 read=0 reused=7 ", self.prefilter(str(shapes)).stdout)
        shapes.write_text("# not a shape\nstarting\nshape\n")
        p = self.prefilter(str(shapes))
        self.assertIn("PREFILTER logs=7 read=7 reused=0 ", p.stdout)
        self.assertEqual((self.out / "logs" / "deploy-20260101T000000Z.log").read_text(),
                         "# not a shape\nkeep starting here\n")
        self.assertFalse((self.out / ".shapes.txt.new").exists())

    def test_the_dry_run_writes_nothing_and_a_bad_shapes_file_is_refused(self):
        p = self.prefilter(BENCH_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("+ prefilter 7 log(s) of %s -> %s/logs/ (8 at a time)" % (self.logs, self.out), p.stdout)
        self.assertFalse(self.out.exists())
        bad = self.root / "shapes.txt"
        bad.write_text("starting\n\nquorum reached\n")
        p = self.prefilter(str(bad))
        self.assertEqual(p.returncode, 1)
        self.assertIn("has an empty line", p.stderr)
        p = self.prefilter(BENCH_PREFILTER_JOBS="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("BENCH_PREFILTER_JOBS='0' is not 1-64 — using 8", p.stderr)


class PersistPullTests(PullCase):
    def setUp(self):
        super().setUp()
        self.host = subprocess.run(["hostname", "-s"], stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        self.sampler = self.root / "node" / "var" / "lib" / "bench-sampler"
        self.sampler.mkdir(parents=True)
        self.results = self.root / "run"
        self.env.update({"BENCH_APPLY": "1", "BENCH_PERSIST_REMOTE_DIR": str(self.sampler)})

    def test_both_files_land_under_the_instance_name(self):
        (self.sampler / (self.host + ".persist.csv")).write_text("ts_unix,pid\n1,2\n")
        (self.sampler / (self.host + ".folios.txt")).write_text("ts_unix,folio_order\n1,0\n")
        p = self.run_lib("bench_pull_persist_files", "bench-validator-01", "us-west2-a", self.results)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("✓ persist files: bench-validator-01.csv bench-validator-01.folios.txt", p.stdout)
        persist = self.results / "persist"
        self.assertEqual(sorted(x.name for x in persist.iterdir()), ["bench-validator-01.csv", "bench-validator-01.folios.txt"])
        self.assertEqual((persist / "bench-validator-01.csv").read_text(), "ts_unix,pid\n1,2\n")
        self.assertEqual(len(self.calls()), 1)
        self.assertTrue(self.calls()[0]["stdin"].startswith("# bench-pull: persist\n"))

    def test_a_node_without_them_is_a_note_and_keeps_an_earlier_copy(self):
        (self.results / "persist").mkdir(parents=True)
        (self.results / "persist" / "bench-validator-01.csv").write_text("earlier\n")
        p = self.run_lib("bench_pull_persist_files", "bench-validator-01", "us-west2-a", self.results)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("- bench-validator-01: no persist sampler file on the node", p.stdout)
        self.assertEqual(sorted(x.name for x in (self.results / "persist").iterdir()), ["bench-validator-01.csv"])
        self.assertEqual((self.results / "persist" / "bench-validator-01.csv").read_text(), "earlier\n")

    def test_the_dry_run_calls_nothing(self):
        p = self.run_lib("bench_pull_persist_files", "bench-validator-01", "us-west2-a", self.results, BENCH_APPLY="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("+ persist files: bench-validator-01 %s/<host>.{persist.csv,folios.txt}" % self.sampler, p.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.results.exists())
