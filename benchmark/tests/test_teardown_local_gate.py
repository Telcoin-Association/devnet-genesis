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
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
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
               "STUB_LOG": str(self.root / "curl.log")}
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


if __name__ == "__main__":
    unittest.main()
