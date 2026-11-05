"""The local gate: bench-lib.sh's local-results helpers and benchmark-teardown.sh's gate, offline.

results/<run>/ is the only copy of a run (no persistent bucket keeps another), so before its first
delete the teardown proves every node's logs and the manifest are there, then writes INDEX.md and
CHECKSUMS.sha256 and records manifest.archive.

The helpers are cut out of bench-lib.sh by name (as test_recovery.py cuts out its watcher) and run
under bash. The teardown runs for real, in a temporary copy of the scripts (its results root is
fixed to <its dir>/results, so nothing here runs it in place). Both talk to fixtures/teardown/:
a fake gcloud backed by a directory (it logs every call with the stdin it was given), a perl
stub that records each alarm and execs the command, and stubs for sleep and pgrep (so a real
local IAP tunnel is never seen, or killed). curl fails if anything reaches for the network.

The teardown's world: one live bench instance whose logs a fresh pull marker vouches for, its
run bucket, and the devnet instances it must leave alone.
"""
import calendar
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIX = TESTS / "fixtures" / "teardown"
CURL_STUB = TESTS / "fixtures" / "node-image" / "stub-curl-forbidden.sh"
LIB = (BENCH / "bench-lib.sh").read_text()
TEARDOWN = (BENCH / "benchmark-teardown.sh").read_text()

GS = "gs" + "://"
PROJECT = "tn-" + "devnet"
OLD_ARCHIVE = PROJECT + "-benchmark-archive"   # the retired persistent bucket: never touched again
RUN = "r20991231-0101"
RUN_BUCKET = PROJECT + "-bench-" + RUN
INST, ZONE, INST_ID = "bench-validator-01", "us-west2-a", "4242"
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DELETES = (("compute", "instances", "delete"), ("storage", "rm"), ("storage", "buckets", "delete"),
           ("compute", "firewall-rules", "delete"), ("compute", "disks", "delete"))
MUTATIONS = DELETES + (("storage", "rsync"), ("storage", "cp"), ("storage", "buckets", "create"),
                       ("storage", "buckets", "update"))

# Scripts the teardown sources or runs, relative to the repo root.
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/benchmark-teardown.sh", "benchmark/recovery-lib.sh",
        "benchmark/tools/cert-rate.py", "benchmark/tools/block-rate.py")


def shell_function(source, name):
    """The text of shell function <name> in <source>: a block ending in a column-0 brace, or one line."""
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.M | re.S) \
        or re.search(r"^%s\(\) \{ .*\}\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("function %s not found" % name)
    return m.group()


LIB_SCRIPT = "set -euo pipefail\n" + "".join(shell_function(LIB, n) for n in (
    "bench_run", "bench_warn", "bench_now_iso", "bench_manifest", "bench_manifest_jq", "_bench_sha256_cmd",
    "_bench_results_files", "_bench_results_totals", "_bench_index_kind", "_bench_write_index",
    "_bench_write_checksums", "bench_local_index", "bench_local_gate_check", "bench_bucket_names"))


def shell_assignment(source, name):
    """The column-0 line that sets <name> in <source>."""
    m = re.search(r"^%s=.*\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("assignment %s not found" % name)
    return m.group()


# The pull-marker verdict and its report, with the constants they read, as bench-lib.sh has them.
MARKER_SCRIPT = "set -euo pipefail\n" + "".join(shell_assignment(LIB, n) for n in (
    "BENCH_MARKER_MAX_AGE_SECS", "BENCH_PULL_MARKER_V")) + "".join(shell_function(LIB, n) for n in (
    "bench_now_unix", "bench_iso_from_unix", "_bench_log_name_ok", "_bench_marker_verdict",
    "bench_node_markers_report"))
TRUSTED_NOTE = ("teardown: saved logs accepted from markers older than the freshness window "
                "(BENCH_TEARDOWN_TRUST_MARKERS=1): ")


def utc_ago(secs):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - secs))


def unix(iso):
    """Unix seconds of a UTC "YYYY-MM-DDTHH:MM:SSZ"."""
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


# The run's window as the manifest records it: coordinated_start.due (unix) and timestamps.blast_end.
DUE_ISO, END_ISO = "2099-12-31T08:00:00Z", "2099-12-31T09:00:00Z"
COVERS = ("2099-12-31T07:59:30.000001Z", "2099-12-31T09:05:00.000001Z")
STARTS_LATE = ("2099-12-31T08:40:00.000001Z", "2099-12-31T09:05:00.000001Z")   # bench 3: logrotate ate the start
LOGCOV_RE = re.compile(r"^LOGCOV (\S+) gens=\S+ first=\S+ last=\S+ due=\S+ end=\S+ ok=([01-])$", re.M)
DONE_RE = re.compile(r"^TEARDOWN_DONE run=(\S+) deleted=(\d+) left=(\d+) at=(\S+)( dry_run=1)?$")
LOGSPAN_RE = re.compile(r"^LOGSPAN (\S+) stream=(stdout|stderr) gen=(\d+) file=(\S+) bytes=(\d+) first=(\S+) last=(\S+)$")
ANCHOR = 'if [ "${cov_bad}" -gt 0 ] && [ "${SKIP_COVERAGE}" != "1" ]; then'


def node_lines(start_iso, count, step=300):
    """<count> node log lines, the first at <start_iso>, <step> s apart, as the node writes them."""
    t0 = unix(start_iso)
    return "".join("%s.000001Z  INFO tn_node: line %d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t0 + k * step)), k)
                   for k in range(count)).encode()


def logspan_text(inst, first, last):
    """The span pull's LOGSPAN lines for a node whose stdout generations run from <first> to <last>:
    telcoin.log.1 up to 08:30 and telcoin.log after it, or telcoin.log alone when <first> is later."""
    mid = "2099-12-31T08:30:00.000001Z"
    rows = []
    if first < mid:
        rows.append("stdout gen=1 file=/var/log/telcoin/telcoin.log.1 bytes=900 first=%s last=%s" % (first, mid))
        first = mid
    rows.append("stdout gen=0 file=/var/log/telcoin/telcoin.log bytes=700 first=%s last=%s" % (first, last))
    rows.append("stderr gen=0 file=/var/log/telcoin/telcoin-error.log bytes=0 first=- last=-")
    return "".join("LOGSPAN %s stream=%s\n" % (inst, r) for r in rows)


def marker_text(inst, node_id, pulled, files, end=True):
    """A tn-bench-pulled/v2 marker vouching for <files> (Paths) at their sizes now."""
    lines = ["tn-bench-pulled/v2", "instance " + inst, "id " + node_id, "created 2099-12-31T00:00:00.000-08:00",
             "run " + RUN, "pulled " + pulled, "sources current-container log, unit stdout"]
    lines += ["file %d %s" % (f.stat().st_size, f.name) for f in files]
    return "\n".join(lines + (["end"] if end else [])) + "\n"


def gz(text):
    return gzip.compress(text.encode())


def node_logs(inst, node_id="4242"):
    """What the pulls leave for one node: container log, unit stdout, marker, recovery evidence."""
    return {
        "logs/%s-telcoin.log.gz" % inst: gz("node log\n" * 50),
        "logs/%s-unit-stdout.log.gz" % inst: gz("unit stdout\n"),
        "logs/%s.pulled" % inst: b"marker\n",
        "logs/%s-recovery-%s.Ab12Cd.tgz" % (inst, node_id): b"evidence bytes",
    }


def manifest_bytes(**extra):
    m = {"schema": "tn-bench-manifest/v1", "run_id": RUN, "notes": [], "timestamps": {}}
    m.update(extra)
    return json.dumps(m).encode()


def write_tree(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def tree_files(root):
    """{relative path: bytes} of every regular file under <root>."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def read_checksums(root):
    """{path: hex} from <root>/CHECKSUMS.sha256 ("<hex>  <path>" lines)."""
    out = {}
    for line in (root / "CHECKSUMS.sha256").read_text().splitlines():
        hexd, _, path = line.partition("  ")
        out[path] = hexd
    return out


def index_rows(root):
    """[(count, path cell, what, by)] from the table in <root>/INDEX.md."""
    rows = []
    for line in (root / "INDEX.md").read_text().splitlines():
        m = re.match(r"^\| (\d+) \| `([^`]*)` \| (.*) \| (.*) \|$", line)
        if m:
            rows.append((int(m.group(1)), m.group(2), m.group(3), m.group(4)))
    return rows


class FakeCloud(object):
    """The stub bin dir and the fake gcloud's state, under one temporary root."""

    def __init__(self, root):
        self.root = root
        self.bin = root / "bin"
        self.state = root / "state"
        self.bin.mkdir(parents=True)
        (self.state / "gcs").mkdir(parents=True)
        for name, src in (("gcloud", FIX / "fake-gcloud.py"), ("perl", FIX / "stub-perl.sh"),
                          ("sleep", FIX / "stub-sleep.sh"), ("pgrep", FIX / "stub-pgrep.sh"),
                          ("curl", CURL_STUB)):
            shutil.copyfile(str(src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.tmp = root / "tmp"
        self.tmp.mkdir()

    def env(self, **extra):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmp), "FAKE_ROOT": str(self.state),
               "STUB_LOG": str(self.root / "curl.log"), "TN_IAP_RETRIES": "0"}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        return env

    def bucket(self, name, labels=None, files=None):
        (self.state / "gcs" / name).mkdir(parents=True, exist_ok=True)
        if labels is not None:
            (self.state / "labels").mkdir(exist_ok=True)
            (self.state / "labels" / (name + ".json")).write_text(json.dumps(labels))
        write_tree(self.state / "gcs" / name, files or {})

    def node(self, inst, files):
        """A sandbox node for <inst> (fake-gcloud.py runs its pull sessions there): <files> are
        {node path: bytes}, e.g. "/var/log/telcoin/telcoin.log"; docker.log is the container's log."""
        base = self.state / "nodes" / inst
        (base / "bin").mkdir(parents=True)
        for name, src in (("sudo", FIX / "node-sudo.sh"), ("docker", FIX / "node-docker.sh")):
            shutil.copyfile(str(src), str(base / "bin" / name))
            (base / "bin" / name).chmod(0o755)
        write_tree(base, {rel.lstrip("/"): data for rel, data in files.items()})
        return base

    def objects(self, bucket):
        base = self.state / "gcs" / bucket
        return tree_files(base) if base.is_dir() else {}

    def calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def is_call(call, words):
    pos = [a for a in call["argv"] if not a.startswith("-")]
    return tuple(pos[:len(words)]) == tuple(words)


def indices(calls, words):
    return [i for i, c in enumerate(calls) if is_call(c, words)]


@unittest.skipUnless(shutil.which("jq"), "needs jq")
class LocalHelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="local-gate-helpers-")
        self.root = Path(self._tmp.name)
        self.cloud = FakeCloud(self.root)
        self.results = self.root / "results" / RUN
        files = {"manifest.json": manifest_bytes(), "sampler/%s.csv" % INST: b"ts_unix,block\n1,2\n",
                 "genesis/validators/v1/bls-keystore.json": b"KEYSTORE", "notes-by-hand.txt": b"mine\n",
                 "path with space/x.json": b"{}\n", ".DS_Store": b"x", "genesis/.DS_Store": b"x"}
        files.update(node_logs("bench-validator-01"))
        files.update(node_logs("bench-validator-02", "77"))
        write_tree(self.results, files)

    def tearDown(self):
        self._tmp.cleanup()

    def run_lib(self, body, *args, apply=True):
        """Run <body> after the cut-out helpers; "$1".. are <args>."""
        env = self.cloud.env(BENCH_APPLY="1" if apply else "0", BENCH_RESULTS_DIR=str(self.results),
                             BENCH_RUN_ID=RUN, PROJECT_ID=PROJECT)
        return subprocess.run(["bash", "-c", LIB_SCRIPT + body + "\n", "t"] + list(args), env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)

    def gate(self, *insts):
        return self.run_lib('bench_local_gate_check "$@"', *insts)

    def test_gate_passes_when_every_node_has_its_logs(self):
        p = self.gate("bench-validator-01", "bench-validator-02")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("✓ 7 required file(s)", p.stdout)
        self.assertIn("logs of 2 node(s)", p.stdout)

    def test_gate_names_every_missing_file(self):
        (self.results / "logs" / "bench-validator-02-unit-stdout.log.gz").unlink()
        (self.results / "logs" / "bench-validator-02-recovery-77.Ab12Cd.tgz").unlink()
        (self.results / "logs" / "bench-validator-01-telcoin.log.gz").write_bytes(b"")   # empty = missing
        p = self.gate("bench-validator-01", "bench-validator-02", "bench-observer-11")
        self.assertEqual(p.returncode, 1)
        missing = re.findall(r"✗ missing or empty: (\S+)", p.stdout)
        self.assertEqual(missing, [
            "logs/bench-validator-01-telcoin.log.gz",
            "logs/bench-validator-02-unit-stdout.log.gz", "logs/bench-validator-02-recovery-*.tgz",
            "logs/bench-observer-11-telcoin.log.gz", "logs/bench-observer-11-unit-stdout.log.gz",
            "logs/bench-observer-11-recovery-*.tgz"])
        self.assertNotIn("✓", p.stdout)

    def test_gate_requires_a_manifest_that_parses(self):
        (self.results / "manifest.json").write_text("{not json")
        p = self.gate("bench-validator-01")
        self.assertEqual(p.returncode, 1)
        self.assertIn("manifest.json (does not parse as a JSON object)", p.stdout)
        (self.results / "manifest.json").unlink()
        p = self.gate("bench-validator-01")
        self.assertEqual(p.returncode, 1)
        self.assertIn("✗ missing or empty: manifest.json", p.stdout)

    def test_gate_honours_cert_failure_logs(self):
        absolute = self.root / "elsewhere.log.gz"
        absolute.write_bytes(gz("x"))
        (self.results / "manifest.json").write_bytes(manifest_bytes(cert_failures=[
            {"node": "bench-validator-03", "logs": ["logs/cf-v03.log.gz", str(absolute)]},
            {"node": "bench-validator-04", "logs": ["logs/cf-v04.log.gz"]}, {"node": "no logs key"}, "junk"]))
        p = self.gate("bench-validator-01")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(re.findall(r"✗ missing or empty: (.+)", p.stdout),
                         ["logs/cf-v03.log.gz (manifest.cert_failures)", "logs/cf-v04.log.gz (manifest.cert_failures)"])
        write_tree(self.results, {"logs/cf-v03.log.gz": gz("a"), "logs/cf-v04.log.gz": gz("b")})
        p = self.gate("bench-validator-01")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("✓ 7 required file(s)", p.stdout)   # 3 node logs + manifest + 3 cert-failure logs
        self.assertIn("manifest.cert_failures logs", p.stdout)
        for empty in ([], None):
            (self.results / "manifest.json").write_bytes(manifest_bytes(cert_failures=empty))
            self.assertEqual(self.gate("bench-validator-01").returncode, 0)

    def test_index_checksums_and_manifest_totals(self):
        p = self.run_lib('bench_local_index --arg p "$1" \'.archive = {kind: "local", path: $p}\'', str(self.results))
        self.assertEqual(p.returncode, 0, p.stderr)
        files = tree_files(self.results)
        sums = read_checksums(self.results)
        # Every file but CHECKSUMS.sha256 itself, at its content's SHA-256; no temp file left behind.
        self.assertEqual(set(sums), set(files) - {"CHECKSUMS.sha256"})
        for rel, hexd in sums.items():
            self.assertEqual(hexd, hashlib.sha256(files[rel]).hexdigest(), rel)
        self.assertFalse([f for f in files if os.path.basename(f).startswith(".") and not f.endswith(".DS_Store")], files)
        # The manifest records what CHECKSUMS covers, at the manifest's own final size.
        a = json.loads(files["manifest.json"])["archive"]
        self.assertEqual(a["kind"], "local")
        self.assertEqual(a["path"], str(self.results))
        self.assertEqual(a["files"], len(sums))
        self.assertEqual(a["bytes"], sum(len(files[rel]) for rel in sums))
        # INDEX.md: one row per group, counts adding up to every file (itself and CHECKSUMS included).
        rows = index_rows(self.results)
        self.assertEqual(sum(r[0] for r in rows), len(files))
        by_path = {r[1]: r for r in rows}
        self.assertEqual(by_path["logs/<node>-telcoin.log.gz"][0], 2)
        self.assertEqual(by_path["logs/<node>.pulled*"][0], 2)
        self.assertEqual(by_path["genesis*/*"][0], 1)
        self.assertEqual(by_path[".DS_Store, */.DS_Store"][0], 2)
        for unknown in ("notes-by-hand.txt", "path with space/x.json"):
            self.assertEqual(by_path[unknown][:3], (1, unknown, "not known to the harness"))
        self.assertIn("✓ %s/INDEX.md and CHECKSUMS.sha256: %d file(s)" % (self.results, len(sums)), p.stdout)

    def test_checksums_check_out_with_the_system_tool(self):
        p = self.run_lib("bench_local_index")
        self.assertEqual(p.returncode, 0, p.stderr)
        tool = ["shasum", "-a", "256"] if shutil.which("shasum") else ["sha256sum"]
        c = subprocess.run(tool + ["-c", "CHECKSUMS.sha256"], cwd=str(self.results), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertNotIn("archive", json.loads((self.results / "manifest.json").read_text()))

    def test_dry_run_writes_nothing(self):
        before = tree_files(self.results)
        p = self.run_lib("bench_local_index '.archive = {}'", apply=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("(dry run) would write", p.stdout)
        self.assertIn("and set manifest.archive", p.stdout)
        self.assertEqual(tree_files(self.results), before)

    def test_bucket_list_is_the_run_buckets_only(self):
        self.cloud.bucket(OLD_ARCHIVE, labels={"purpose": "bench-archive", "retain": "true"})
        self.cloud.bucket(RUN_BUCKET)
        self.cloud.bucket("acme-labelled", labels={"benchmark": "1"})
        self.cloud.bucket("acme-unrelated", labels={})
        p = self.run_lib("bench_bucket_names")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sorted(p.stdout.split()), sorted(["acme-labelled", RUN_BUCKET]))


class MarkerVerdictTests(unittest.TestCase):
    """The pull-marker verdict (bench_node_markers_report over _bench_marker_verdict): a marker
    older than the freshness window is rejected unless BENCH_TEARDOWN_TRUST_MARKERS=1, which lifts
    the age rule and nothing else."""

    OLD = 9 * 3600   # a teardown re-run 9 h after the interrupted one

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="marker-verdict-")
        self.logs = Path(self._tmp.name) / "logs"
        self.logs.mkdir()
        self.files = [self.logs / (INST + "-telcoin.log.gz"), self.logs / (INST + "-unit-stdout.log.gz")]
        self.files[0].write_bytes(gz("node log line\n" * 100))
        self.files[1].write_bytes(gz("unit stdout line\n" * 100))
        self.pulled = None

    def tearDown(self):
        self._tmp.cleanup()

    def mark(self, age, node_id=INST_ID, end=True, head=None):
        self.pulled = utc_ago(age)
        text = marker_text(INST, node_id, self.pulled, self.files, end)
        if head is not None:
            text = head + "\n" + text.split("\n", 1)[1]
        (self.logs / (INST + ".pulled")).write_text(text)

    def report(self, trust=None):
        env = {"PATH": os.environ["PATH"]}
        if trust is not None:
            env["BENCH_TEARDOWN_TRUST_MARKERS"] = trust
        return subprocess.run(["bash", "-c", MARKER_SCRIPT + 'bench_node_markers_report "$@"\n', "t",
                               str(self.logs), INST, INST_ID], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def rejected(self, p, why):
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(p.stdout, "        marker %s.pulled: not accepted — %s\n" % (INST, why))

    def test_an_old_marker_is_rejected_by_default_and_accepted_with_trust(self):
        self.mark(self.OLD)
        for trust in (None, "0", "yes", "true"):
            with self.subTest(trust=trust):
                self.rejected(self.report(trust), "pulled %s, more than 15 min ago; the node has logged since" % self.pulled)
        p = self.report("1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout, "        marker %s.pulled: accepted — instance %s (created 2099-12-31T00:00:00.000-08:00), "
                         "run %s, pulled %s; its 2 log(s) are here at their recorded sizes "
                         "(BENCH_TEARDOWN_TRUST_MARKERS=1)\n" % (INST, INST_ID, RUN, self.pulled))

    def test_a_fresh_marker_is_accepted_either_way_without_the_suffix(self):
        self.mark(2)
        for trust in (None, "1"):
            with self.subTest(trust=trust):
                p = self.report(trust)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue(p.stdout.endswith("its 2 log(s) are here at their recorded sizes\n"), p.stdout)

    def test_trust_rejects_a_missing_vouched_file(self):
        self.mark(self.OLD)
        self.files[1].unlink()
        self.rejected(self.report("1"), "%s is gone" % self.files[1].name)

    def test_trust_rejects_a_vouched_file_of_another_size(self):
        size = self.files[0].stat().st_size
        for label, data in (("grown", self.files[0].read_bytes() + b"x"),
                            ("cut short", self.files[0].read_bytes()[:-1])):
            with self.subTest(label):
                self.files[0].write_bytes(gz("node log line\n" * 100))
                self.mark(self.OLD)
                self.files[0].write_bytes(data)
                self.rejected(self.report("1"), "%s is %d bytes, the marker says %d" % (self.files[0].name, len(data), size))

    def test_trust_keeps_every_other_check(self):
        for label, kwargs, age, why in (
                ("another instance", {"node_id": "999"}, self.OLD,
                 "it is for instance 999 (created 2099-12-31T00:00:00.000-08:00); %s now is instance %s" % (INST, INST_ID)),
                ("no end line", {"end": False}, self.OLD, "incomplete (no end line)"),
                ("older format", {"head": "tn-bench-pulled/v1"}, self.OLD, "older format, names no instance id"),
                ("future pull time", {}, -3600, None)):
            with self.subTest(label):
                self.mark(age, **kwargs)
                self.rejected(self.report("1"), why or "pulled %s, which is in the future" % self.pulled)


class TeardownSourceOrderTests(unittest.TestCase):
    """Where the gate sits in benchmark-teardown.sh, read from the source."""

    def line_of(self, needle, start=0):
        for i, line in enumerate(TEARDOWN.splitlines()):
            if i >= start and needle in line and not line.lstrip().startswith("#"):
                return i
        self.fail("%r not in benchmark-teardown.sh" % needle)

    def test_gate_after_the_evidence_and_before_every_delete(self):
        evidence = self.line_of("bench_pull_recovery_evidence ")
        gate = self.line_of('if bench_local_gate_check "${INSTANCE_NAMES[@]}"; then')
        self.assertLess(evidence, gate)
        for needle in ("bench_run kill", "bench_run gcloud compute instances delete",
                       "bench_run gcloud compute firewall-rules delete", "bench_run gcloud compute disks delete",
                       "bench_run gcloud storage buckets delete", "bench_run gcloud storage rm",
                       "bench_run gcloud secrets remove-iam-policy-binding", "bench_run gcloud secrets delete",
                       "worktree remove", "branch -D", 'bench_run mv "${BENCH_DIR}/genesis"'):
            self.assertLess(gate, self.line_of(needle), needle)

    def test_credentials_before_the_first_listing_and_the_pull(self):
        creds = self.line_of("perl -e 'alarm shift; exec @ARGV' 60 gcloud auth print-access-token </dev/null >/dev/null")
        self.assertLess(creds, self.line_of('ALL_INST="$(gcloud compute instances list'))
        self.assertLess(creds, self.line_of('bench_pull_node_logs "${LOG_DIR}"'))
        self.assertLess(self.line_of('bench_pull_node_logs "${LOG_DIR}"'), self.line_of('stop_if_reauth "the log pull"'))

    def test_coverage_gate_after_certification_and_before_the_local_gate(self):
        self.assertEqual(TEARDOWN.count(ANCHOR), 1)
        cert = self.line_of("bench_cert_failures_snapshot ")
        cov = self.line_of(ANCHOR)
        self.assertLess(cert, self.line_of("bench_log_coverage_check "))
        self.assertLess(self.line_of("bench_log_coverage_check "), cov)
        self.assertLess(cov, self.line_of('if bench_local_gate_check "${INSTANCE_NAMES[@]}"; then'))

    def test_deletes_are_async_and_polled_before_the_disks(self):
        delete = self.line_of("bench_run gcloud compute instances delete")
        self.assertIn("--quiet --async", TEARDOWN.splitlines()[delete])
        self.assertLess(self.line_of("now_id=\"$(bench_instance_json"), delete)
        self.assertLess(delete, self.line_of('st="$(delete_state '))
        self.assertLess(self.line_of('st="$(delete_state '), self.line_of("bench_run gcloud compute disks delete"))

    def test_final_index_after_provenance_and_before_the_checks(self):
        prov = self.line_of("node_startup_check || ")
        final = self.line_of("final_local_index || ")
        checks = self.line_of('echo ">>> left-nothing checks')
        self.assertLess(prov, final)
        self.assertLess(final, checks)

    def test_no_persistent_archive_left(self):
        for text in (TEARDOWN, LIB, (BENCH / "config.sh").read_text(), (BENCH / "benchmark-deploy.sh").read_text()):
            self.assertNotIn("BENCH_ARCHIVE", text)
            self.assertNotIn("benchmark-archive", text)
            self.assertNotIn("storage rsync", text)


@unittest.skipUnless(shutil.which("git") and shutil.which("jq"), "needs git and jq")
class TeardownLocalGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="teardown-local-gate-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        for rel in TREE:
            (self.tree / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / rel), str(self.tree / rel))
        self.cloud = FakeCloud(self.root)
        self.params = self.root / "consensus-params.yaml"
        self.params.write_text("max_header_delay: 3s\n")
        self.contracts = self.root / "contracts"
        self.contracts.mkdir()
        subprocess.run(["git", "init", "-q", str(self.contracts)], check=True)
        self.results = self.tree / "benchmark" / "results" / RUN
        logs = self.results / "logs"
        logs.mkdir(parents=True)
        log = logs / (INST + "-telcoin.log.gz")
        log.write_bytes(gz("node log line\n" * 100))
        # The marker vouches for the container log only, so the log gate passes whether or not a
        # test removes the unit log: the local gate alone decides on it.
        (logs / (INST + "-unit-stdout.log.gz")).write_bytes(gz("unit stdout line\n" * 100))
        pulled = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2))
        (logs / (INST + ".pulled")).write_text("\n".join([
            "tn-bench-pulled/v2", "instance " + INST, "id " + INST_ID, "created 2099-12-31T00:00:00.000-08:00",
            "run " + RUN, "pulled " + pulled, "sources current-container log",
            "file %d %s" % (log.stat().st_size, log.name), "end"]) + "\n")
        write_tree(self.results, {
            "manifest.json": manifest_bytes(),
            "genesis/validators/v1/bls-keystore.json": b"KEYSTORE",
            "tunnel.pid": b"123\n", ".DS_Store": b"x"})
        devnet = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; printf "%s\\n" "${INSTANCE_NAMES[@]}"',
                                 "_", str(self.tree / "config.sh")], stdout=subprocess.PIPE,
                                universal_newlines=True, check=True, env={"PATH": os.environ["PATH"]}).stdout.split()
        self.devnet = devnet + ["obs-devnet", "txgen-devnet", "devnet-indexer"]
        self.assertGreaterEqual(len(self.devnet), 4)
        zone_url = "projects/%s/zones/%s" % (PROJECT, ZONE)
        instances = [{"name": n, "zone": zone_url, "status": "RUNNING", "labels": {}, "id": str(1000 + i)}
                     for i, n in enumerate(self.devnet)]
        instances.append({"name": INST, "zone": zone_url, "status": "RUNNING", "id": INST_ID,
                          "creationTimestamp": "2099-12-31T00:00:00.000-08:00",
                          "labels": {"benchmark": "1", "network": "bench", "bench-run": RUN}})
        (self.cloud.state / "instances.json").write_text(json.dumps(instances))
        self.cloud.bucket(RUN_BUCKET, labels={"benchmark": "1", "bench-run": RUN},
                          files={"blasters/bench-blaster-01.json": b"{\"rc\": 0}\n"})
        # The retired persistent archive still exists until it is deleted by hand: never touched.
        self.cloud.bucket(OLD_ARCHIVE, labels={"purpose": "bench-archive", "retain": "true"},
                          files={"runs/r20261006-0458/results/manifest.json": b"{}"})

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **extra):
        return self.cloud.env(BENCH_TXGEN_SHA="abcdef1", BENCH_PARAMETERS_FILE=str(self.params),
                              BENCH_CONTRACTS_SRC_DIR=str(self.contracts), **extra)

    def teardown(self, *args, **extra):
        env = self.env(**extra)
        return subprocess.run(["bash", str(self.tree / "benchmark" / "benchmark-teardown.sh"), "--run", RUN] + list(args),
                              env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=180)

    def fleet(self):
        """INSTANCE_NAMES as the teardown sees them (benchmark/config.sh, same environment)."""
        # $0 names an allowed caller: benchmark/config.sh refuses any other.
        p = subprocess.run(["bash", "-c", 'source "$1" >/dev/null; printf "%s\\n" "${INSTANCE_NAMES[@]}"',
                            "benchmark-teardown.sh", str(self.tree / "benchmark" / "config.sh")], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, env=self.env(BENCH_RUN_ID=RUN))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split()

    def give_every_node_its_logs(self):
        """The other fleet nodes are gone from the fake project; an earlier pull left their logs."""
        for i, inst in enumerate(self.fleet()):
            if inst != INST:
                write_tree(self.results, node_logs(inst, str(9000 + i)))

    def manifest(self):
        return json.loads((self.results / "manifest.json").read_text())

    def run_window(self, **extra):
        """The manifest of a run with a coordinated start (DUE_ISO) and a blast end (END_ISO)."""
        (self.results / "manifest.json").write_bytes(manifest_bytes(
            coordinated_start={"due": unix(DUE_ISO), "nodes": 11, "started": 11},
            timestamps=dict({"blast_end": END_ISO}, **extra)))

    def spans(self, first_last, **per_node):
        """logs/<node>.logspan for every fleet node: <first_last>, or per_node[<node with _ for ->]."""
        for inst in self.fleet():
            first, last = per_node.get(inst.replace("-", "_"), first_last)
            (self.results / "logs" / (inst + ".logspan")).write_text(logspan_text(inst, first, last))

    def done_line(self, p):
        """The TEARDOWN_DONE fields of the last stdout line (it must be one)."""
        last = p.stdout.rstrip("\n").splitlines()[-1]
        m = DONE_RE.match(last)
        self.assertTrue(m, "last line is not TEARDOWN_DONE: %r" % last)
        self.assertRegex(m.group(4), ISO_RE)
        return m.group(1), int(m.group(2)), int(m.group(3)), bool(m.group(5))

    def recorded(self, name):
        p = self.cloud.state / name
        return p.read_text().split() if p.exists() else []

    def age_marker(self, secs=9 * 3600):
        """The live node's marker, as if pulled <secs> ago (an interrupted teardown's). Its pull time."""
        m = self.results / "logs" / (INST + ".pulled")
        pulled = utc_ago(secs)
        m.write_text(re.sub(r"(?m)^pulled .*$", "pulled " + pulled, m.read_text()))
        return pulled

    def stub_df(self, row):
        """A df whose -Pk output is the header and <row>."""
        df = self.cloud.bin / "df"
        df.write_text("#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\necho '%s'\n" % row)
        df.chmod(0o755)

    def log_pulls(self):
        """The ssh sessions of a node-log pull (the recovery evidence's `sudo bash -s` is not one)."""
        return [c for c in self.cloud.calls() if is_call(c, ("compute", "ssh"))
                and any("docker logs" in a or "/var/log/telcoin" in a or "tar -cf" in a for a in c["argv"])]

    def instance_names(self):
        return [i["name"] for i in json.loads((self.cloud.state / "instances.json").read_text())]

    def assert_nothing_deleted(self, p):
        calls = self.cloud.calls()
        for words in DELETES:
            self.assertEqual(indices(calls, words), [], "%s ran: %s" % (" ".join(words), p.stdout[-2000:]))
        self.assertIn(INST, self.instance_names())
        self.assertTrue(self.cloud.objects(RUN_BUCKET))

    def assert_old_archive_untouched(self):
        for c in self.cloud.calls():
            self.assertNotIn(OLD_ARCHIVE, " ".join(c["argv"]))
            self.assertFalse(is_call(c, ("storage", "rsync")), c["argv"])
        self.assertEqual(set(self.cloud.objects(OLD_ARCHIVE)), {"runs/r20261006-0458/results/manifest.json"})

    def test_local_gate_passes_then_indexes_the_final_tree(self):
        self.give_every_node_its_logs()
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✓ teardown left nothing behind.", p.stdout)
        out = p.stdout
        self.assertLess(out.index(">>> local gate"), out.index(">>> plan / execution"))
        self.assertLess(out.index(">>> plan / execution"), out.index(">>> final local index"))
        self.assertNotIn(INST, self.instance_names())
        self.assertEqual(set(self.devnet), set(self.instance_names()))
        self.assertEqual(self.cloud.objects(RUN_BUCKET), {})
        self.assert_old_archive_untouched()
        # The final CHECKSUMS.sha256 covers every file, the run bucket's copy and the moved-in
        # evidence included, at its SHA-256.
        files = tree_files(self.results)
        sums = read_checksums(self.results)
        self.assertEqual(set(sums), set(files) - {"CHECKSUMS.sha256"})
        for rel, hexd in sums.items():
            self.assertEqual(hexd, hashlib.sha256(files[rel]).hexdigest(), rel)
        self.assertIn("bucket/%s/blasters/bench-blaster-01.json" % RUN_BUCKET, sums)
        self.assertTrue([f for f in sums if f.startswith("logs/%s-recovery-%s." % (INST, INST_ID))])
        rows = index_rows(self.results)
        self.assertEqual(sum(r[0] for r in rows), len(files))
        a = self.manifest()["archive"]
        self.assertEqual(a["kind"], "local")
        self.assertEqual(a["path"], str(self.results.resolve()))
        self.assertRegex(a["verified_at"], ISO_RE)
        self.assertRegex(a["final_index_at"], ISO_RE)
        self.assertEqual(a["files"], len(sums))
        self.assertEqual(a["bytes"], sum(len(files[rel]) for rel in sums))
        self.assertNotIn("skipped_gate", a)
        self.assertIn("· results/%s/ kept, the only copy" % RUN, out)
        self.assertEqual(self.done_line(p), (RUN, 1, 0, False))

    def test_coverage_short_log_stops_before_any_delete(self):
        # Every node's logs reach back to the coordinated start but the live node's: logrotate
        # left its oldest line 40 min after it (bench 3, D19). Its logs are all present, so the
        # local gate alone would pass.
        self.give_every_node_its_logs()
        self.run_window()
        self.spans(COVERS, bench_validator_01=STARTS_LATE)
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        verdicts = dict(LOGCOV_RE.findall(p.stdout))
        self.assertEqual(set(verdicts), set(self.fleet()), "one LOGCOV line per fleet node")
        self.assertEqual(verdicts.pop(INST), "0")
        self.assertEqual(set(verdicts.values()), {"1"})
        self.assertIn("LOGCOV %s gens=1 first=%s last=%s due=%s end=%s ok=0"
                      % (INST, STARTS_LATE[0], STARTS_LATE[1], DUE_ISO, END_ISO), p.stdout)
        self.assertIn("❌ the logs of 1 node(s) do not cover the run (LOGCOV ok=0 above) — NOTHING was deleted: %s"
                      % INST, p.stderr)
        self.assertIn("BENCH_TEARDOWN_SKIP_COVERAGE=1 benchmark/benchmark-teardown.sh --yes --run " + RUN, p.stderr)
        self.assertLess(p.stdout.index(">>> certification outcome"), p.stdout.index(">>> log coverage"))
        self.assertNotIn(">>> local gate", p.stdout)
        self.assert_nothing_deleted(p)
        m = self.manifest()
        self.assertNotIn("archive", m)
        self.assertNotIn("teardown_start", m["timestamps"])
        cov = {c["inst"]: c for c in m["log_coverage"]}
        self.assertEqual(set(cov), set(self.fleet()))
        self.assertEqual(cov[INST], {"inst": INST, "generations": 1, "first_ts": STARTS_LATE[0],
                                     "last_ts": STARTS_LATE[1], "due": DUE_ISO, "blast_end": END_ISO,
                                     "ok": False, "checked_at": cov[INST]["checked_at"]})
        self.assertRegex(cov[INST]["checked_at"], ISO_RE)
        self.assertEqual({c["ok"] for i, c in cov.items() if i != INST}, {True})

    def test_coverage_of_every_node_is_recorded_and_the_teardown_deletes(self):
        self.give_every_node_its_logs()
        self.run_window()
        self.spans(COVERS)
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✓ %d node(s): %d cover the run" % (len(self.fleet()), len(self.fleet())), p.stdout)
        self.assertLess(p.stdout.index(">>> log coverage"), p.stdout.index(">>> local gate"))
        self.assertNotIn(INST, self.instance_names())
        cov = self.manifest()["log_coverage"]
        self.assertEqual(sorted(c["inst"] for c in cov), sorted(self.fleet()))
        for c in cov:
            self.assertEqual((c["generations"], c["first_ts"], c["last_ts"], c["due"], c["blast_end"], c["ok"]),
                             (2, COVERS[0], COVERS[1], DUE_ISO, END_ISO, True), c["inst"])
        self.assertIn("logs/%s.logspan" % INST, read_checksums(self.results))

    def test_unknown_coverage_is_a_note_not_a_failure(self):
        # A run with no coordinated start or blast end recorded, and nodes without a recorded span.
        self.give_every_node_its_logs()
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("the manifest has no coordinated_start.due", p.stdout)
        self.assertIn("the manifest has no timestamps.blast_end", p.stdout)
        self.assertEqual(set(LOGCOV_RE.findall(p.stdout)), {(i, "-") for i in self.fleet()})
        self.assertIn("%d unknown (ok=-, a note" % len(self.fleet()), p.stdout)
        cov = self.manifest()["log_coverage"]
        self.assertEqual({(c["inst"], c["ok"], c["due"], c["blast_end"]) for c in cov},
                         {(i, None, None, None) for i in self.fleet()})

    def test_coverage_a_live_node_without_a_span_stops_before_any_delete(self):
        # The run's start and end are known; the live node has no recorded span (its span session
        # answered nothing, or it was never pulled), a gone node has none either.
        self.give_every_node_its_logs()
        self.run_window()
        self.spans(COVERS)
        gone = [i for i in self.fleet() if i != INST][0]
        for inst in (INST, gone):
            (self.results / "logs" / (inst + ".logspan")).unlink()
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        verdicts = dict(LOGCOV_RE.findall(p.stdout))
        self.assertEqual((verdicts[INST], verdicts[gone]), ("-", "-"))
        self.assertIn("✗ %s: no recorded span (logs/%s.logspan) for a live node of a run whose start and end are "
                      "known — counted as not covered" % (INST, INST), p.stdout)
        self.assertNotIn("✗ %s: no recorded span" % gone, p.stdout)
        self.assertIn("— NOTHING was deleted: %s\n" % INST, p.stderr)
        self.assert_nothing_deleted(p)
        cov = {c["inst"]: c["ok"] for c in self.manifest()["log_coverage"]}
        self.assertEqual((cov[INST], cov[gone]), (False, None))
        # Under BENCH_TEARDOWN_SKIP_LOGS=1 a missing span is a note again.
        p = self.teardown("--yes", BENCH_TEARDOWN_SKIP_LOGS="1")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertNotIn("no recorded span", p.stdout)
        self.assertNotIn(INST, self.instance_names())

    def sandbox_node(self):
        """INST as a sandbox node with three generations of its unit log (telcoin.log, .1, .2.gz),
        an empty error log and a container log; every other fleet node covers the run already."""
        self.give_every_node_its_logs()
        self.age_marker()   # so the pull really runs
        self.run_window()
        self.spans(COVERS)
        (self.results / "logs" / (INST + ".logspan")).unlink()   # this one must come from the pull
        files = {
            "/var/log/telcoin/telcoin.log": node_lines("2099-12-31T08:30:00Z", 8),      # 08:30 .. 09:05
            "/var/log/telcoin/telcoin.log.1": node_lines("2099-12-31T07:59:30Z", 7),    # 07:59:30 .. 08:29:30
            "/var/log/telcoin/telcoin.log.2.gz": gzip.compress(node_lines("2099-12-31T07:30:00Z", 6), mtime=0),
            "/var/log/telcoin/telcoin-error.log": b"",
            "docker.log": node_lines("2099-12-31T08:50:00Z", 4)}
        self.cloud.node(INST, files)
        return files

    def new_logs(self, pattern):
        return sorted(p.name for p in (self.results / "logs").glob(pattern))

    def test_the_pull_records_every_generation_end_to_end(self):
        files = self.sandbox_node()
        p = self.teardown("--yes", BENCH_TEARDOWN_MIN_FREE_GB="0")
        self.assertEqual(p.returncode, 0, p.stdout[-4000:] + p.stderr[-4000:])
        logs = self.results / "logs"
        # The span: every generation on the node, with its first (and, for 0 and 1, last) line.
        span = (logs / (INST + ".logspan")).read_text().splitlines()
        rows = [LOGSPAN_RE.match(line) for line in span]
        self.assertTrue(all(rows), span)
        self.assertEqual([(r.group(2), r.group(3), r.group(4), r.group(6), r.group(7)) for r in rows], [
            ("stdout", "0", "/var/log/telcoin/telcoin.log", "2099-12-31T08:30:00Z", "2099-12-31T09:05:00Z"),
            ("stdout", "1", "/var/log/telcoin/telcoin.log.1", "2099-12-31T07:59:30Z", "2099-12-31T08:29:30Z"),
            ("stdout", "2", "/var/log/telcoin/telcoin.log.2.gz", "2099-12-31T07:30:00Z", "-"),
            ("stderr", "0", "/var/log/telcoin/telcoin-error.log", "-", "-")])
        # The rotated generations and this pull's copies of the unit and container logs (stamped:
        # the earlier instance's copies are here under the plain names).
        r1, r2 = logs / (INST + "-unit-stdout.rotated-1.log.gz"), logs / (INST + "-unit-stdout.rotated-2.log.gz")
        self.assertEqual(gzip.decompress(r1.read_bytes()), files["/var/log/telcoin/telcoin.log.1"])
        self.assertEqual(r2.read_bytes(), files["/var/log/telcoin/telcoin.log.2.gz"])
        unit = self.new_logs(INST + "-unit-stdout-*.log.gz")
        cont = self.new_logs(INST + "-telcoin-*.log.gz")
        self.assertEqual(len(unit), 1, unit)
        self.assertEqual(len(cont), 1, cont)
        self.assertEqual(gzip.decompress((logs / unit[0]).read_bytes()), files["/var/log/telcoin/telcoin.log"])
        self.assertEqual(gzip.decompress((logs / cont[0]).read_bytes()), files["docker.log"])
        self.assertEqual(self.new_logs(INST + "-unit-stderr*"), [], "an empty error log is not copied")
        # The new marker vouches for exactly those, at their sizes.
        markers = self.new_logs(INST + ".pulled-*")
        self.assertEqual(len(markers), 1, markers)
        listed = dict((name, int(size)) for size, name in
                      re.findall(r"^file (\d+) (\S+)$", (logs / markers[0]).read_text(), re.M))
        self.assertEqual(listed, {n: (logs / n).stat().st_size for n in (r1.name, r2.name, unit[0], cont[0])})
        self.assertIn("LOGCOV %s gens=3 first=2099-12-31T07:30:00Z last=2099-12-31T09:05:00Z due=%s end=%s ok=1"
                      % (INST, DUE_ISO, END_ISO), p.stdout)
        self.assertNotIn(INST, self.instance_names())
        for name in (r1.name, r2.name, INST + ".logspan", markers[0]):
            self.assertIn("logs/" + name, read_checksums(self.results))

    def test_a_failed_rotated_pull_leaves_no_marker_and_deletes_nothing(self):
        self.sandbox_node()
        p = self.teardown("--yes", BENCH_TEARDOWN_MIN_FREE_GB="0", BENCH_IAP_RETRIES="2",
                          FAKE_SSH_FAIL="# bench-pull: rotated")
        self.assertEqual(p.returncode, 1, p.stdout[-4000:] + p.stderr[-4000:])
        rotated = [c for c in self.cloud.calls() if is_call(c, ("compute", "ssh"))
                   and c["stdin"].startswith("# bench-pull: rotated")]
        self.assertEqual(len(rotated), 2, "every attempt of the rotated pull fails")
        self.assertIn("✗ %s: rotated unit logs: not all pulled" % INST, p.stderr)
        self.assertEqual(self.new_logs(INST + ".pulled-*"), [], "no marker for a node missing a generation")
        self.assertEqual(self.new_logs(INST + "-unit-stdout.rotated-*"), [])
        self.assertIn("node logs not saved — NOTHING was deleted", p.stderr)
        self.assertNotIn((INST, "1"), LOGCOV_RE.findall(p.stdout))
        self.assert_nothing_deleted(p)

    def test_skip_coverage_deletes_and_says_so(self):
        self.give_every_node_its_logs()
        self.run_window()
        self.spans(COVERS, bench_validator_01=STARTS_LATE)
        p = self.teardown("--yes", BENCH_TEARDOWN_SKIP_COVERAGE="1")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("BENCH_TEARDOWN_SKIP_COVERAGE=1 — deleting although the logs of %s do not cover the run" % INST,
                      p.stderr)
        self.assertNotIn(INST, self.instance_names())
        m = self.manifest()
        self.assertTrue([n for n in m["notes"] if "BENCH_TEARDOWN_SKIP_COVERAGE=1" in n and INST in n], m["notes"])
        self.assertIs({c["inst"]: c["ok"] for c in m["log_coverage"]}[INST], False)

    def test_credentials_are_checked_before_anything_else(self):
        self.give_every_node_its_logs()
        before = tree_files(self.results)
        p = self.teardown("--yes", FAKE_AUTH="fail")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("❌ gcloud has no usable credentials (gcloud auth print-access-token failed or took over 60 s)"
                      " — NOTHING was pulled or deleted.", p.stderr)
        self.assertIn("Run: gcloud auth login   then re-run: benchmark/benchmark-teardown.sh --yes --run " + RUN, p.stderr)
        self.assertEqual([c["argv"] for c in self.cloud.calls()], [["auth", "print-access-token"]])
        self.assertEqual(self.cloud.calls()[0]["stdin"], "")
        self.assertEqual(self.recorded("alarms"), ["60", "gcloud"])
        self.assertEqual(tree_files(self.results), before)
        self.assertIn(INST, self.instance_names())
        # The same check passes when gcloud prints a token, and goes first.
        p = self.teardown()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✓ gcloud prints an access token", p.stdout)
        self.assertEqual(self.cloud.calls()[1]["argv"], ["auth", "print-access-token"])

    def test_reauth_during_the_pull_stops_before_any_delete(self):
        self.give_every_node_its_logs()
        self.age_marker()   # the node needs a pull
        # Every ssh fails as an expired session does: pull-lib's stream helper touches the stop file.
        p = self.teardown("--yes", FAKE_REAUTH_SSH="1", BENCH_TEARDOWN_MIN_FREE_GB="0")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("❌ gcloud needs re-authentication (the session expired during the log pull) — NOTHING was deleted.",
                      p.stderr)
        self.assertIn("Run: gcloud auth login", p.stderr)
        self.assertTrue(self.log_pulls() or any(is_call(c, ("compute", "ssh")) for c in self.cloud.calls()))
        self.assertNotIn(">>> certification outcome", p.stdout)
        self.assertFalse(list((self.results / "logs").glob(INST + "-recovery-*.tgz")), "stopped before the evidence")
        self.assert_nothing_deleted(p)
        self.assertEqual([n for n in os.listdir(str(self.cloud.tmp)) if n.startswith("tn-bench-teardown.")], [],
                         "the stop file's directory is removed on exit")

    def test_deletes_are_async_then_polled_until_gone(self):
        self.give_every_node_its_logs()
        p = self.teardown("--yes", FAKE_DELETE_POLLS="2")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        calls = self.cloud.calls()
        deletes = indices(calls, ("compute", "instances", "delete"))
        self.assertEqual(len(deletes), 1)
        self.assertEqual([a for a in calls[deletes[0]]["argv"] if a.startswith("--") and "=" not in a],
                         ["--quiet", "--async"])
        before = [i for i in indices(calls, ("compute", "instances", "describe")) if i < deletes[0]]
        after = [i for i in indices(calls, ("compute", "instances", "describe")) if i > deletes[0]]
        self.assertTrue(before, "the id is re-checked before the delete")
        self.assertEqual(len(after), 3, "STOPPING, STOPPING, not found")
        self.assertTrue(all(INST in calls[i]["argv"] for i in after))
        self.assertLess(after[-1], indices(calls, ("compute", "firewall-rules", "list"))[-1])
        self.assertEqual(self.recorded("sleeps"), ["10", "10"])
        self.assertIn("waiting for 1 instance delete(s): a describe each every 10 s, at most 600 s", p.stdout)
        self.assertIn("✓ %s (%s) deleted" % (INST, ZONE), p.stdout)
        self.assertEqual(self.done_line(p), (RUN, 1, 0, False))
        self.assertNotIn(INST, self.instance_names())

    def test_an_instance_still_deleting_after_the_wait_is_left(self):
        self.give_every_node_its_logs()
        p = self.teardown("--yes", FAKE_DELETE_POLLS="never", BENCH_TEARDOWN_DELETE_WAIT_SECS="0")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✗ %s (%s) still there after 0 s (status STOPPING) — the left-nothing checks below count it"
                      % (INST, ZONE), p.stdout)
        self.assertEqual(self.recorded("sleeps"), [])
        self.assertIn("❌ teardown left something behind", p.stderr)
        self.assertEqual(self.done_line(p), (RUN, 0, 2, False))   # labelled benchmark=1, named bench-*
        m = self.manifest()
        self.assertRegex(m["timestamps"]["teardown_start"], ISO_RE)
        self.assertNotIn("teardown_done", m["timestamps"], "the deletes did not all finish")
        self.assertEqual([{k: v for k, v in e.items() if k != "at"} for e in m["teardown_pending"]],
                         [{"inst": INST, "zone": ZONE, "status": "STOPPING"}])
        self.assertRegex(m["teardown_pending"][0]["at"], ISO_RE)
        # The instance goes in the end; the re-run finds nothing left to wait for and writes the done time.
        (self.cloud.state / "deleting.json").write_text(json.dumps({"%s/%s" % (ZONE, INST): 0}))
        subprocess.run([str(self.cloud.bin / "gcloud"), "compute", "instances", "describe", INST, "--zone=" + ZONE],
                       env=self.cloud.env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertNotIn(INST, self.instance_names())
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        m = self.manifest()
        self.assertRegex(m["timestamps"]["teardown_done"], ISO_RE)
        self.assertNotIn("teardown_pending", m)
        self.assertEqual(m["teardown_reruns"][0]["done"], m["timestamps"]["teardown_done"])

    def test_timestamps_first_teardown_and_reruns(self):
        self.give_every_node_its_logs()
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        ts = self.manifest()["timestamps"]
        self.assertRegex(ts["teardown_start"], ISO_RE)
        self.assertRegex(ts["teardown_done"], ISO_RE)
        self.assertLessEqual(ts["teardown_start"], ts["teardown_done"])
        self.assertNotIn("teardown_reruns", self.manifest())
        self.assertEqual(self.done_line(p), (RUN, 1, 0, False))
        # A re-run (the fleet is gone): the first start and done stay, the re-run is appended.
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        m = self.manifest()
        self.assertEqual((m["timestamps"]["teardown_start"], m["timestamps"]["teardown_done"]),
                         (ts["teardown_start"], ts["teardown_done"]))
        self.assertEqual(len(m["teardown_reruns"]), 1)
        r = m["teardown_reruns"][0]
        self.assertEqual(sorted(r), ["done", "start"])
        self.assertRegex(r["start"], ISO_RE)
        self.assertRegex(r["done"], ISO_RE)
        self.assertLessEqual(ts["teardown_done"], r["start"])
        self.assertEqual(self.done_line(p), (RUN, 0, 0, False))

    def test_a_rerun_after_an_interrupted_teardown_writes_the_done_time(self):
        # The first teardown recorded its start, deleted some of the fleet and was killed (bench 3).
        self.give_every_node_its_logs()
        self.run_window(teardown_start="2099-12-31T10:00:00Z")
        self.spans(COVERS)
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        m = self.manifest()
        self.assertEqual(m["timestamps"]["teardown_start"], "2099-12-31T10:00:00Z")
        self.assertEqual(len(m["teardown_reruns"]), 1)
        self.assertEqual(m["teardown_reruns"][0]["done"], m["timestamps"]["teardown_done"])
        self.assertLessEqual(m["teardown_reruns"][0]["start"], m["teardown_reruns"][0]["done"])

    def test_missing_unit_log_stops_before_any_delete(self):
        self.give_every_node_its_logs()
        (self.results / "logs" / (INST + "-unit-stdout.log.gz")).unlink()
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-2000:])
        self.assertIn("✗ missing or empty: logs/%s-unit-stdout.log.gz" % INST, p.stdout)
        self.assertIn("NOTHING was deleted", p.stderr)
        self.assertIn("BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 benchmark/benchmark-teardown.sh --yes --run " + RUN, p.stderr)
        self.assert_nothing_deleted(p)
        self.assertNotIn("archive", self.manifest())
        self.assertFalse((self.results / "CHECKSUMS.sha256").exists())
        self.assertTrue(list((self.results / "logs").glob(INST + "-recovery-*.tgz")), "evidence pulled first")

    def test_a_gone_node_without_logs_stops_it_too(self):
        # Only the live node's logs: every other fleet node is gone and never left its logs here.
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-2000:])
        others = [i for i in self.fleet() if i != INST]
        self.assertTrue(others)
        for inst in others:
            self.assertIn("✗ missing or empty: logs/%s-telcoin.log.gz" % inst, p.stdout)
        self.assert_nothing_deleted(p)

    def test_cert_failure_logs_are_required(self):
        self.give_every_node_its_logs()
        (self.results / "manifest.json").write_bytes(manifest_bytes(
            cert_failures=[{"node": INST, "logs": ["logs/cert-failure-%s.log.gz" % INST]}]))
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-2000:])
        self.assertIn("✗ missing or empty: logs/cert-failure-%s.log.gz (manifest.cert_failures)" % INST, p.stdout)
        self.assert_nothing_deleted(p)
        write_tree(self.results, {"logs/cert-failure-%s.log.gz" % INST: gz("failure window\n")})
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("logs/cert-failure-%s.log.gz" % INST, read_checksums(self.results))

    def test_missing_cert_fail_snapshot_stops_before_any_delete(self):
        # A failing validator's snapshot, listed by an earlier record, is not in logs/. The manifest has
        # no phases, so this teardown's record step changes nothing; its snapshot step cannot save a new
        # one (the fake ssh refuses the command) and only adds the node's logs on disk.
        self.give_every_node_its_logs()
        snap = "logs/%s-telcoin-cert-fail-20991231T000000Z.log.gz" % INST
        (self.results / "manifest.json").write_bytes(manifest_bytes(cert_failures=[
            {"inst": INST, "window": "phase mixed", "rate_pct": 0.0, "logs": [snap]}]))
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-2000:])
        out = p.stdout
        self.assertLess(out.index(">>> certification outcome"), out.index(">>> local gate"))
        self.assertIn("has no phases or param_arms yet", p.stderr)
        self.assertIn("✗ missing or empty: %s (manifest.cert_failures)" % snap, out)
        self.assertIn("NOTHING was deleted", p.stderr)
        self.assert_nothing_deleted(p)
        self.assertEqual(self.manifest()["cert_failures"][0]["logs"],
                         sorted([snap, "logs/%s-telcoin.log.gz" % INST, "logs/%s-unit-stdout.log.gz" % INST]))
        self.assertTrue(any(c["argv"][:3] == ["compute", "instances", "describe"] and INST in c["argv"]
                            for c in self.cloud.calls()), "the snapshot step looked the node up")
        write_tree(self.results, {snap: gz("the snapshot\n")})
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn(snap, read_checksums(self.results))
        self.assertIn("· certification: not recorded", p.stdout)

    def test_skip_knob_deletes_and_says_so(self):
        (self.results / "logs" / (INST + "-unit-stdout.log.gz")).unlink()
        p = self.teardown("--yes", BENCH_TEARDOWN_SKIP_LOCAL_GATE="1")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 — deleting although", p.stderr)
        self.assertNotIn(INST, self.instance_names())
        m = self.manifest()
        self.assertIs(m["archive"]["skipped_gate"], True)
        self.assertEqual(m["archive"]["kind"], "local")
        self.assertNotIn("verified_at", m["archive"])
        self.assertTrue(any("BENCH_TEARDOWN_SKIP_LOCAL_GATE=1" in n for n in m["notes"]), m["notes"])
        self.assertEqual(set(read_checksums(self.results)), set(tree_files(self.results)) - {"CHECKSUMS.sha256"})

    def test_skip_knob_must_be_0_or_1(self):
        p = self.teardown("--yes", BENCH_TEARDOWN_SKIP_LOCAL_GATE="yes")
        self.assertEqual(p.returncode, 1)
        self.assertIn("BENCH_TEARDOWN_SKIP_LOCAL_GATE must be 0 or 1 (got 'yes')", p.stderr)
        self.assertEqual(self.cloud.calls(), [])

    def test_dry_run_checks_and_changes_nothing(self):
        self.give_every_node_its_logs()
        # A dry run pulls no evidence: an earlier attempt's is already here.
        write_tree(self.results, {"logs/%s-recovery-%s.Zz99.tgz" % (INST, INST_ID): b"earlier evidence"})
        before = tree_files(self.results)
        p = self.teardown()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        out = p.stdout
        logs_at, gate_at, plan_at = (out.index(">>> node logs"), out.index(">>> local gate"),
                                     out.index(">>> plan / execution"))
        self.assertLess(logs_at, gate_at)
        self.assertLess(gate_at, plan_at)
        gate = out[gate_at:plan_at]
        self.assertIn("(dry run — the pulls above did not run", gate)
        self.assertIn("✓ %d required file(s)" % (3 * len(self.fleet()) + 1), gate)
        self.assertIn("(dry run) would write", gate)
        for c in self.cloud.calls():
            for words in MUTATIONS:
                self.assertFalse(is_call(c, words), "dry run executed gcloud " + " ".join(c["argv"]))
        self.assertEqual(tree_files(self.results), before)
        self.assertNotIn("archive", self.manifest())
        self.assertLess(out.index(">>> log coverage"), gate_at)
        self.assertEqual(set(LOGCOV_RE.findall(out)), {(i, "-") for i in self.fleet()})
        self.assertIn("+ gcloud compute instances delete %s --zone=%s --project=%s --quiet --async" % (INST, ZONE, PROJECT),
                      out)
        self.assertIn("(then one describe per instance every 10 s until each is gone, at most 600 s", out)
        self.assertEqual(self.done_line(p), (RUN, 0, 3, True))   # the live instance (labelled, named) + the run bucket
        self.assertEqual(self.recorded("sleeps"), [])

    def test_dry_run_says_where_the_coverage_gate_would_stop(self):
        self.give_every_node_its_logs()
        self.run_window()
        self.spans(COVERS, bench_validator_01=STARTS_LATE)
        before = tree_files(self.results)
        p = self.teardown()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✗ with --yes the teardown stops here, before any delete: %s (BENCH_TEARDOWN_SKIP_COVERAGE=1 "
                      "deletes without their coverage)" % INST, p.stdout)
        self.assertEqual(tree_files(self.results), before, "a dry run records no log_coverage")
        self.assertTrue(self.done_line(p)[3])

    def test_reindex_indexes_files_written_after_the_teardown_and_calls_nothing(self):
        # As a teardown leaves it: the archive record, an index; then analysis written by hand.
        archive = {"kind": "local", "path": str(self.results.resolve()), "verified_at": "2099-12-31T08:00:00Z",
                   "files": 7, "bytes": 1234, "final_index_at": "2099-12-31T08:05:00Z"}
        write_tree(self.results, {"manifest.json": manifest_bytes(archive=archive),
                                  "analysis/cert-rate.md": b"# Certification rate\n",
                                  "INDEX.md": b"stale index\n", "CHECKSUMS.sha256": b"stale\n"})
        added = {"analysis/stage1-summary.md": b"# Stage 1\n", "analysis/per-arm/block-rate-a1.md": b"a1\n",
                 "analysis/per-arm/vote-path/v01-a1.json": b"{}\n"}
        write_tree(self.results, added)
        bucket_before = self.cloud.objects(RUN_BUCKET)
        p = self.teardown("--reindex")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertEqual(self.cloud.calls(), [])                 # no gcloud call at all
        self.assertIn(">>> reindex: ", p.stdout)
        self.assertNotIn(">>> local gate", p.stdout)
        self.assertIn(INST, self.instance_names())
        self.assertEqual(self.cloud.objects(RUN_BUCKET), bucket_before)
        files = tree_files(self.results)
        sums = read_checksums(self.results)
        self.assertEqual(set(sums), set(files) - {"CHECKSUMS.sha256"})
        for rel, data in added.items():
            self.assertEqual(sums[rel], hashlib.sha256(data).hexdigest(), rel)
        rows = {r[1]: r for r in index_rows(self.results)}
        self.assertEqual(rows["analysis/stage1-summary.md"][0], 1)
        self.assertEqual(rows["analysis/per-arm/*"][0], 2)
        self.assertEqual(rows["analysis/per-arm/*"][3], "not the harness")
        self.assertEqual(rows["analysis/cert-rate.md"][0], 1)
        self.assertEqual(sum(r[0] for r in rows.values()), len(files))
        # The totals it prints are the archive record's, which now describe the tree.
        a = self.manifest()["archive"]
        self.assertEqual((a["files"], a["bytes"]), (len(sums), sum(len(files[rel]) for rel in sums)))
        self.assertIn("INDEX.md and CHECKSUMS.sha256: %d file(s), %d bytes" % (a["files"], a["bytes"]), p.stdout)
        self.assertRegex(a["reindexed_at"], ISO_RE)
        self.assertEqual((a["verified_at"], a["final_index_at"]), ("2099-12-31T08:00:00Z", "2099-12-31T08:05:00Z"))

    def test_reindex_needs_run_and_runs_alone(self):
        script = str(self.tree / "benchmark" / "benchmark-teardown.sh")
        for args, needle in ((["--reindex"], "--reindex needs --run <id>"),
                             (["--reindex", "--run", RUN, "--yes"], "--reindex runs on its own"),
                             (["--purge", "--reindex", "--run", RUN], "--reindex runs on its own"),
                             (["--reindex", "--run", "r20991231-9999"], "does not exist")):
            p = subprocess.run(["bash", script] + args, env=self.env(BENCH_RUN_ID=RUN), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            self.assertEqual(p.returncode, 1, args)
            self.assertIn(needle, p.stderr, args)
        self.assertEqual(self.cloud.calls(), [])
        self.assertFalse((self.results / "INDEX.md").exists())
        self.assertFalse((self.results / "CHECKSUMS.sha256").exists())
        self.assertFalse((self.tree / "benchmark" / "results" / "r20991231-9999").exists())

    def test_an_old_marker_is_pulled_again_by_default(self):
        self.give_every_node_its_logs()
        pulled = self.age_marker()
        self.stub_df("/dev/fake 999999999 1 104857600 1% /")   # 100.0 GB free
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("marker %s.pulled: not accepted — pulled %s, more than 15 min ago; the node has logged since"
                      % (INST, pulled), p.stdout)
        self.assertIn("+ %s: to pull" % INST, p.stdout)
        self.assertIn("✓ 100.0 GB free under %s (BENCH_TEARDOWN_MIN_FREE_GB=20) for 1 node(s)"
                      % (self.results / "logs"), p.stdout)
        self.assertTrue(self.log_pulls(), "the node is pulled again")   # the fake gcloud refuses: the pull fails
        self.assertIn("node logs not saved — NOTHING was deleted", p.stderr)
        self.assert_nothing_deleted(p)
        self.assertFalse([n for n in self.manifest()["notes"] if "TRUST_MARKERS" in n])

    def test_trust_markers_accepts_an_old_intact_marker_and_pulls_nothing(self):
        self.give_every_node_its_logs()
        pulled = self.age_marker()
        logs_before = sorted(os.listdir(str(self.results / "logs")))
        # Nothing to pull, so the free-space floor is never consulted, however high.
        p = self.teardown("--yes", BENCH_TEARDOWN_TRUST_MARKERS="1", BENCH_TEARDOWN_MIN_FREE_GB="999999")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("(nothing is deleted until these are saved) — BENCH_TEARDOWN_TRUST_MARKERS=1", p.stdout)
        self.assertIn("✓ %s: already saved — not pulled again (current-container log)" % INST, p.stdout)
        self.assertIn("marker %s.pulled: accepted — instance %s (created 2099-12-31T00:00:00.000-08:00), run %s, "
                      "pulled %s; its 1 log(s) are here at their recorded sizes (BENCH_TEARDOWN_TRUST_MARKERS=1)\n"
                      % (INST, INST_ID, RUN, pulled), p.stdout)
        self.assertNotIn("GB free", p.stdout + p.stderr)
        self.assertEqual(self.log_pulls(), [])
        # No copy beside the saved logs: only the recovery evidence and the analysis inputs are new.
        new = sorted(set(os.listdir(str(self.results / "logs"))) - set(logs_before))
        self.assertTrue(all(re.match(r"^%s-recovery-%s\.\w+\.tgz$" % (INST, INST_ID), n) for n in new), new)
        notes = [n for n in self.manifest()["notes"] if "TRUST_MARKERS" in n]
        self.assertEqual(notes, [TRUSTED_NOTE + "%s@%s" % (INST, pulled)])
        self.assertNotIn(INST, self.instance_names())

    def test_trust_markers_still_pulls_a_node_whose_log_changed(self):
        self.give_every_node_its_logs()
        self.age_marker()
        log = self.results / "logs" / (INST + "-telcoin.log.gz")
        size = log.stat().st_size
        with log.open("ab") as fh:
            fh.write(b"x")
        p = self.teardown("--yes", BENCH_TEARDOWN_TRUST_MARKERS="1", BENCH_TEARDOWN_MIN_FREE_GB="0")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("marker %s.pulled: not accepted — %s is %d bytes, the marker says %d"
                      % (INST, log.name, size + 1, size), p.stdout)
        self.assertIn("+ %s: to pull" % INST, p.stdout)
        self.assertTrue(self.log_pulls())
        self.assert_nothing_deleted(p)
        self.assertFalse([n for n in self.manifest()["notes"] if "TRUST_MARKERS" in n])

    def test_free_space_floor_stops_before_the_pull(self):
        self.give_every_node_its_logs()
        self.age_marker()   # the node needs a pull
        for row, what in (("/dev/fake 2097152 1048576 1048576 50% /", "1.0 GB free"),
                          ("df: cannot read", "free space unknown (df -Pk printed no number)")):
            with self.subTest(what):
                self.stub_df(row)
                before = tree_files(self.results)
                p = self.teardown("--yes")
                self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
                self.assertIn("❌ %s under %s, below BENCH_TEARDOWN_MIN_FREE_GB=20 — the pull of 1 node(s) did not "
                              "start; NOTHING was deleted." % (what, self.results / "logs"), p.stderr)
                self.assertIn("BENCH_TEARDOWN_TRUST_MARKERS=1", p.stderr)
                self.assertEqual(self.log_pulls(), [])
                self.assertEqual(tree_files(self.results), before, "results/<run>/ untouched")
                self.assert_nothing_deleted(p)
        # A dry run says where --yes would stop, and goes on.
        p = self.teardown()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✗ free space unknown (df -Pk printed no number) under %s, below BENCH_TEARDOWN_MIN_FREE_GB=20: "
                      "with --yes the teardown stops here, before the pull" % (self.results / "logs"), p.stdout)

    def test_free_space_floor_reads_the_real_df(self):
        self.give_every_node_its_logs()
        self.age_marker()
        before = tree_files(self.results)
        p = self.teardown("--yes", BENCH_TEARDOWN_MIN_FREE_GB="999999")
        self.assertEqual(p.returncode, 1, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertRegex(p.stderr, r"❌ \d+\.\d GB free under \S+/logs, below BENCH_TEARDOWN_MIN_FREE_GB=999999 — "
                                   r"the pull of 1 node\(s\) did not start; NOTHING was deleted\.")
        self.assertEqual(self.log_pulls(), [])
        self.assertEqual(tree_files(self.results), before)
        self.assert_nothing_deleted(p)

    def test_trust_and_floor_knobs_are_validated(self):
        for knob, value, needle in (
                ("BENCH_TEARDOWN_TRUST_MARKERS", "yes", "BENCH_TEARDOWN_TRUST_MARKERS must be 0 or 1 (got 'yes')"),
                ("BENCH_TEARDOWN_MIN_FREE_GB", "08", "got '08'"),
                ("BENCH_TEARDOWN_MIN_FREE_GB", "-1", "got '-1'"),
                ("BENCH_TEARDOWN_MIN_FREE_GB", "1.5", "got '1.5'"),
                ("BENCH_TEARDOWN_MIN_FREE_GB", "1000000", "got '1000000'"),
                ("BENCH_TEARDOWN_SKIP_ANALYSIS", "yes", "BENCH_TEARDOWN_SKIP_ANALYSIS must be 0 or 1 (got 'yes')"),
                ("BENCH_TEARDOWN_SKIP_COVERAGE", "true", "BENCH_TEARDOWN_SKIP_COVERAGE must be 0 or 1 (got 'true')"),
                ("BENCH_TEARDOWN_SKIP_COVERAGE", "2", "BENCH_TEARDOWN_SKIP_COVERAGE must be 0 or 1 (got '2')"),
                ("BENCH_TEARDOWN_DELETE_WAIT_SECS", "10m", "got '10m'"),
                ("BENCH_TEARDOWN_DELETE_WAIT_SECS", "060", "got '060'"),
                ("BENCH_TEARDOWN_DELETE_WAIT_SECS", "-5", "got '-5'"),
                ("BENCH_TEARDOWN_DELETE_WAIT_SECS", "1000000", "got '1000000'")):
            with self.subTest(knob=knob, value=value):
                p = self.teardown("--yes", **{knob: value})
                self.assertEqual(p.returncode, 1)
                self.assertIn(needle, p.stderr)
                if knob.endswith("MIN_FREE_GB"):
                    self.assertIn("BENCH_TEARDOWN_MIN_FREE_GB must be a whole number of GB, 0 to 999999", p.stderr)
                if knob.endswith("DELETE_WAIT_SECS"):
                    self.assertIn("BENCH_TEARDOWN_DELETE_WAIT_SECS must be a whole number of seconds, 0 to 999999",
                                  p.stderr)
        self.assertEqual(self.cloud.calls(), [])


class FakeGcloudTests(unittest.TestCase):
    """The fake's answers the teardown's pull relies on: the two `# bench-pull:` sessions (told apart
    by the first line of the script on stdin), the credential check and an --async delete."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="fake-gcloud-")
        self.cloud = FakeCloud(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def gcloud(self, args, stdin="", **extra):
        return subprocess.run([str(self.cloud.bin / "gcloud")] + args, input=stdin.encode(),
                              env=self.cloud.env(**extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)

    def ssh(self, header, **extra):
        return self.gcloud(["compute", "ssh", INST, "--zone=" + ZONE, "--project=p", "--ssh-flag=-T",
                            "--command=sudo bash -s"], header + "\nset -eu\necho from the script\n", **extra)

    def test_span_session_prints_logspan_lines(self):
        p = self.ssh("# bench-pull: span")
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.decode().splitlines()
        self.assertTrue(lines)
        rows = [LOGSPAN_RE.match(line) for line in lines]
        self.assertTrue(all(rows), lines)
        self.assertEqual({r.group(1) for r in rows}, {INST})
        self.assertEqual({(r.group(2), r.group(3)) for r in rows}, {("stdout", "0"), ("stdout", "1"), ("stderr", "0")})
        (self.cloud.state / "logspan").mkdir()
        (self.cloud.state / "logspan" / INST).write_text(logspan_text(INST, *STARTS_LATE))
        p = self.ssh("# bench-pull: span")
        self.assertEqual(p.stdout.decode(), logspan_text(INST, *STARTS_LATE))

    def test_rotated_session_writes_a_tar_of_gzip_files(self):
        p = self.ssh("# bench-pull: rotated")
        self.assertEqual(p.returncode, 0, p.stderr)
        with tarfile.open(fileobj=io.BytesIO(p.stdout), mode="r:") as tar:
            members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}
        self.assertTrue(members)
        for name, data in members.items():
            self.assertRegex(name, r"^unit-(stdout|stderr)\.rotated-\d+\.log\.gz$")
            self.assertIn(INST.encode(), gzip.decompress(data))

    def test_other_scripts_get_the_recovery_tar_and_reauth_fails_every_ssh(self):
        p = self.ssh("set -e -o pipefail")
        self.assertEqual(p.returncode, 0, p.stderr)
        with tarfile.open(fileobj=io.BytesIO(p.stdout), mode="r:gz") as tar:
            self.assertEqual(tar.getnames(), ["./telcoin.journal"])
        for header in ("# bench-pull: span", "# bench-pull: rotated", "set -e -o pipefail"):
            p = self.ssh(header, FAKE_REAUTH_SSH="1")
            self.assertEqual((p.returncode, p.stdout), (1, b""), header)
            self.assertIn(b"Reauthentication failed", p.stderr)
            self.assertIn(b"gcloud auth login", p.stderr)

    def test_auth_token_switch(self):
        p = self.gcloud(["auth", "print-access-token"])
        self.assertEqual((p.returncode, p.stdout.strip()), (0, b"fake-access-token"))
        p = self.gcloud(["auth", "print-access-token"], FAKE_AUTH="fail")
        self.assertEqual((p.returncode, p.stdout), (1, b""))
        self.assertIn(b"gcloud auth login", p.stderr)

    def test_async_delete_is_found_for_n_describes_then_not_found(self):
        zone_url = "projects/p/zones/" + ZONE
        (self.cloud.state / "instances.json").write_text(json.dumps([{"name": INST, "zone": zone_url, "id": INST_ID,
                                                                      "status": "RUNNING"}]))
        where = [INST, "--zone=" + ZONE, "--project=p"]
        self.assertEqual(self.gcloud(["compute", "instances", "delete"] + where + ["--quiet", "--async"],
                                     FAKE_DELETE_POLLS="2").returncode, 0)
        for _ in range(2):
            p = self.gcloud(["compute", "instances", "describe"] + where + ["--format=json"])
            self.assertEqual((p.returncode, json.loads(p.stdout)["status"]), (0, "STOPPING"))
            self.assertIn(INST, self.gcloud(["compute", "instances", "list"]).stdout.decode())
        p = self.gcloud(["compute", "instances", "describe"] + where + ["--format=json"])
        self.assertEqual(p.returncode, 1)
        self.assertIn(b"was not found", p.stderr)
        self.assertEqual(json.loads(self.gcloud(["compute", "instances", "list"]).stdout), [])


if __name__ == "__main__":
    unittest.main()
