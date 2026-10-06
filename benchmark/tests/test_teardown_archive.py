"""The persistent archive: bench-lib.sh's archive helpers and benchmark-teardown.sh's archive gate,
fully offline.

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
ARCHIVE = PROJECT + "-benchmark-archive"     # config.sh's default BENCH_ARCHIVE_BUCKET
RUN = "r20991231-0101"
RUN_BUCKET = PROJECT + "-bench-" + RUN
PREFIX = "runs/" + RUN                        # object prefix of BENCH_ARCHIVE_PREFIX
INST, ZONE, INST_ID = "bench-validator-01", "us-west2-a", "4242"
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DELETES = (("compute", "instances", "delete"), ("storage", "rm"), ("storage", "buckets", "delete"),
           ("compute", "firewall-rules", "delete"), ("compute", "disks", "delete"))
MUTATIONS = DELETES + (("storage", "rsync"), ("storage", "cp"), ("storage", "buckets", "create"),
                       ("storage", "buckets", "update"))

# Scripts the teardown sources or runs, relative to the repo root.
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
        "benchmark/benchmark-teardown.sh", "benchmark/recovery-lib.sh")


def shell_function(source, name):
    """The text of shell function <name> in <source>: a block ending in a column-0 brace, or one line."""
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.M | re.S) \
        or re.search(r"^%s\(\) \{ .*\}\n" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("function %s not found" % name)
    return m.group()


EXCLUDE_LINE = re.search(r"^BENCH_ARCHIVE_EXCLUDE='[^']*'\n", LIB, re.M).group()
EXCLUDE = EXCLUDE_LINE.split("'")[1]
LIB_SCRIPT = "set -euo pipefail\n" + EXCLUDE_LINE + "".join(shell_function(LIB, n) for n in (
    "bench_run", "bench_warn", "bench_now_iso", "bench_manifest", "_bench_in_lines", "bench_archive_ensure",
    "bench_archive_results", "bench_archive_manifest", "bench_archive_verify", "bench_bucket_names"))


def gz(text):
    return gzip.compress(text.encode())


def results_files():
    """A results/<run>/ tree: what the archive must carry, and what it must never carry."""
    keep = {
        "manifest.json": json.dumps({"schema": "tn-bench-manifest/v1", "run_id": RUN, "notes": [],
                                     "timestamps": {}}).encode(),
        "logs/%s-telcoin.log.gz" % INST: gz("node log\n" * 50),
        "logs/%s-unit-stdout.log.gz" % INST: gz("unit stdout\n"),
        "logs/%s.pulled" % INST: b"marker\n",
        "logs/%s-recovery-%s.Ab12Cd.tgz" % (INST, INST_ID): b"evidence bytes",
        "sampler/%s.csv" % INST: b"ts,block\n1,2\n",
        "blasters/bench-blaster-01.json": b"{}\n",
        "bucket/%s/blasters/bench-blaster-01.json" % RUN_BUCKET: b"{}\n",
        "tunnel.log": b"tunnel output\n",
        "genesis-notes.txt": b"a file, not the genesis workspace\n",
    }
    never = {
        "genesis/validators/v1/bls-keystore.json": b"KEYSTORE",
        "genesis.20261006120000/committee.yaml": b"moved genesis",
        "tunnel.pid": b"123\n",
        ".DS_Store": b"x",
        "logs/.%s.pulled.Zz9Yy8" % INST: b"half-written marker",
    }
    return keep, never


def write_tree(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


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

    def objects(self, bucket, prefix=""):
        base = self.state / "gcs" / bucket
        if not base.is_dir():
            return {}
        return {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*")
                if p.is_file() and p.relative_to(base).as_posix().startswith(prefix)}

    def labels(self, bucket):
        p = self.state / "labels" / (bucket + ".json")
        return json.loads(p.read_text()) if p.exists() else None

    def calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def alarms(self):
        p = self.state / "alarms"
        return p.read_text().splitlines() if p.exists() else []


def is_call(call, words):
    pos = [a for a in call["argv"] if not a.startswith("-")]
    return tuple(pos[:len(words)]) == tuple(words)


def indices(calls, words):
    return [i for i, c in enumerate(calls) if is_call(c, words)]


class ExcludeRegexTests(unittest.TestCase):
    """BENCH_ARCHIVE_EXCLUDE as gcloud applies it: re.match on the path relative to results/<run>/."""

    def test_secrets_and_scratch_are_excluded_and_results_kept(self):
        keep, never = results_files()
        for rel in never:
            self.assertTrue(re.match(EXCLUDE, rel), "must not be archived: " + rel)
        for rel in keep:
            self.assertIsNone(re.match(EXCLUDE, rel), "must be archived: " + rel)
        for rel in ("blast-0-20261006T010203Z/manifest.json", "meta/tunnel.pid.txt", "logs/genesis/x"):
            self.assertIsNone(re.match(EXCLUDE, rel), rel)

    def test_one_pattern_no_comma(self):
        # gcloud splits --exclude on commas: a comma would cut the pattern in two.
        self.assertNotIn(",", EXCLUDE)


class ArchiveHelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="archive-helpers-")
        self.root = Path(self._tmp.name)
        self.cloud = FakeCloud(self.root)
        self.results = self.root / "results" / RUN
        self.keep, self.never = results_files()
        write_tree(self.results, self.keep)
        write_tree(self.results, self.never)

    def tearDown(self):
        self._tmp.cleanup()

    def run_lib(self, body, *args, apply=True, **extra):
        """Run <body> after the cut-out helpers; "$1".. are <args>."""
        env = self.cloud.env(BENCH_APPLY="1" if apply else "0", BENCH_RESULTS_DIR=str(self.results),
                             BENCH_RUN_ID=RUN, PROJECT_ID=PROJECT, BENCH_ARCHIVE_BUCKET=ARCHIVE,
                             BENCH_ARCHIVE_PREFIX=GS + ARCHIVE + "/" + PREFIX,
                             BENCH_ARCHIVE_LOCATION="us-west2",
                             BENCH_ARCHIVE_LABELS="purpose=bench-archive,retain=true",
                             BENCH_ARCHIVE_TIMEOUT_SECS="1800", **extra)
        # Data waiting on stdin: a gcloud call that is not given </dev/null would read it.
        return subprocess.run(["bash", "-c", LIB_SCRIPT + body + "\n", "t"] + list(args), env=env,
                              input="LEAK-STDIN\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)

    def assert_stdin_closed(self):
        calls = self.cloud.calls()
        self.assertTrue(calls)
        for c in calls:
            if not is_call(c, ("storage", "buckets", "list")):   # bench_bucket_names predates the rule
                self.assertEqual(c["stdin"], "", "gcloud %s read stdin" % " ".join(c["argv"]))

    def test_ensure_creates_an_absent_bucket_locked_down_and_labelled(self):
        p = self.run_lib("bench_archive_ensure")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.cloud.calls()
        self.assertEqual([tuple(c["argv"][:3]) for c in calls], [("storage", "buckets", "describe"),
                                                               ("storage", "buckets", "create"),
                                                               ("storage", "buckets", "update")])
        create = calls[1]["argv"]
        for f in ("--location=us-west2", "--uniform-bucket-level-access", "--public-access-prevention",
                  "--project=" + PROJECT):
            self.assertIn(f, create)
        self.assertEqual(self.cloud.labels(ARCHIVE), {"purpose": "bench-archive", "retain": "true"})
        self.assertEqual(self.cloud.alarms(), ["120 gcloud"] * 3)
        self.assert_stdin_closed()

    def test_ensure_leaves_an_existing_bucket_alone(self):
        self.cloud.bucket(ARCHIVE, labels={"purpose": "bench-archive"})
        p = self.run_lib("bench_archive_ensure")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("exists", p.stdout)
        self.assertEqual(len(self.cloud.calls()), 1)

    def test_ensure_dry_run_says_it_would_create(self):
        p = self.run_lib("bench_archive_ensure", apply=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("would be created", p.stdout)
        self.assertIn("buckets create", p.stdout)
        self.assertIn("(dry run — not executed)", p.stdout)
        self.assertEqual([tuple(c["argv"][:3]) for c in self.cloud.calls()], [("storage", "buckets", "describe")])

    def test_ensure_never_creates_blind_when_describe_is_denied(self):
        p = self.run_lib("bench_archive_ensure",
                         FAKE_DESCRIBE_ERR="ERROR: HTTPError 403: caller does not have storage.buckets.get access")
        self.assertEqual(p.returncode, 1)
        self.assertIn("could not be described", p.stderr)
        self.assertEqual(len(self.cloud.calls()), 1)

    def test_results_copy_excludes_secrets_and_never_deletes(self):
        self.cloud.bucket(ARCHIVE)
        old = PREFIX + "/results/from-an-earlier-sync.txt"
        write_tree(self.cloud.state / "gcs" / ARCHIVE, {old: b"kept"})
        self.cloud.bucket(RUN_BUCKET, files={"blasters/bench-blaster-01.json": b"{}\n"})
        p = self.run_lib('bench_archive_results "$1"', RUN_BUCKET)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = self.cloud.objects(ARCHIVE)
        want = {PREFIX + "/results/" + rel for rel in self.keep} | {old} \
            | {PREFIX + "/bucket/%s/blasters/bench-blaster-01.json" % RUN_BUCKET}
        self.assertEqual(set(got), want)
        for c in self.cloud.calls():
            self.assertNotIn("--delete-unmatched-destination-objects", c["argv"])
        self.assertEqual(self.cloud.alarms(), ["1800 gcloud"] * 2)   # results + the bucket
        self.assert_stdin_closed()

    def test_results_copy_tries_every_copy_and_reports_failure(self):
        self.cloud.bucket(ARCHIVE)
        self.cloud.bucket(RUN_BUCKET, files={"x.json": b"{}"})
        # Only the results copy carries --exclude: it fails, the bucket copy still runs.
        p = self.run_lib('bench_archive_results "$1"', RUN_BUCKET, FAKE_FAIL="--exclude")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not fully archived", p.stderr)
        self.assertEqual(set(self.cloud.objects(ARCHIVE)), {PREFIX + "/bucket/%s/x.json" % RUN_BUCKET})

    def test_verify_counts_what_it_requires(self):
        self.cloud.bucket(ARCHIVE)
        p = self.run_lib("bench_archive_results && bench_archive_verify")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("✓ archive verified: 5 file(s)", p.stdout)
        self.assertIn("(2 log(s), 1 pull marker(s), 1 recovery archive(s), manifest.json)", p.stdout)
        ls = [c for c in self.cloud.calls() if is_call(c, ("storage", "ls"))]
        self.assertEqual(len(ls), 1, "one listing")
        self.assertIn("-l", ls[0]["argv"])
        self.assertIn("300 gcloud", self.cloud.alarms())
        self.assert_stdin_closed()

    def test_verify_fails_on_a_size_mismatch_and_on_a_missing_object(self):
        self.cloud.bucket(ARCHIVE)
        p = self.run_lib("bench_archive_results", FAKE_TRUNCATE="-telcoin.log.gz")
        self.assertEqual(p.returncode, 0, p.stderr)
        p = self.run_lib("bench_archive_verify")
        self.assertEqual(p.returncode, 1)
        self.assertIn("lacks 1 of 5 file(s)", p.stderr)
        self.assertIn("logs/%s-telcoin.log.gz" % INST, p.stderr)
        self.assertIn("bytes in the archive", p.stderr)
        (self.cloud.state / "gcs" / ARCHIVE / PREFIX / "results" / "logs" / (INST + ".pulled")).unlink()
        p = self.run_lib("bench_archive_verify")
        self.assertEqual(p.returncode, 1)
        self.assertIn("lacks 2 of 5 file(s)", p.stderr)
        self.assertIn("logs/%s.pulled: 7 bytes here, absent in the archive" % INST, p.stderr)

    def test_verify_dry_run_lists_nothing(self):
        p = self.run_lib("bench_archive_verify", apply=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("gcloud storage ls -l", p.stdout)
        self.assertIn("requires 5 file(s)", p.stdout)
        self.assertEqual(self.cloud.calls(), [])

    def test_manifest_upload_alone(self):
        self.cloud.bucket(ARCHIVE)
        p = self.run_lib("bench_archive_manifest")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.cloud.objects(ARCHIVE), {PREFIX + "/results/manifest.json": self.keep["manifest.json"]})
        self.assert_stdin_closed()

    def test_teardown_bucket_list_never_names_the_archive(self):
        # Even labelled benchmark=1 (a mislabel), the archive is not a teardown candidate.
        self.cloud.bucket(ARCHIVE, labels={"benchmark": "1"})
        self.cloud.bucket(RUN_BUCKET)
        self.cloud.bucket("acme-unrelated", labels={})
        p = self.run_lib("bench_bucket_names")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.split(), [RUN_BUCKET])


class TeardownSourceOrderTests(unittest.TestCase):
    """Where the gate sits in benchmark-teardown.sh, read from the source."""

    def line_of(self, needle, start=0):
        for i, line in enumerate(TEARDOWN.splitlines()):
            if i >= start and needle in line and not line.lstrip().startswith("#"):
                return i
        self.fail("%r not in benchmark-teardown.sh" % needle)

    def test_gate_after_the_evidence_and_before_every_delete(self):
        evidence = self.line_of("bench_pull_recovery_evidence ")
        gate = self.line_of("if ! archive_gate; then")
        self.assertLess(evidence, gate)
        for needle in ("bench_run kill", "bench_run gcloud compute instances delete",
                       "bench_run gcloud compute firewall-rules delete", "bench_run gcloud compute disks delete",
                       "bench_run gcloud storage buckets delete", "bench_run gcloud storage rm",
                       "bench_run gcloud secrets remove-iam-policy-binding", "bench_run gcloud secrets delete",
                       "worktree remove", "branch -D", 'bench_run mv "${BENCH_DIR}/genesis"'):
            self.assertLess(gate, self.line_of(needle), needle)

    def test_final_sync_after_provenance_and_before_the_checks(self):
        prov = self.line_of("node_startup_check || ")
        final = self.line_of("archive_final_sync || ")
        checks = self.line_of('echo ">>> left-nothing checks')
        self.assertLess(prov, final)
        self.assertLess(final, checks)


@unittest.skipUnless(shutil.which("git") and shutil.which("jq"), "needs git and jq")
class TeardownArchiveGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="teardown-archive-")
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
        pulled = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2))
        (logs / (INST + ".pulled")).write_text("\n".join([
            "tn-bench-pulled/v2", "instance " + INST, "id " + INST_ID, "created 2099-12-31T00:00:00.000-08:00",
            "run " + RUN, "pulled " + pulled, "sources current-container log",
            "file %d %s" % (log.stat().st_size, log.name), "end"]) + "\n")
        write_tree(self.results, {
            "manifest.json": json.dumps({"schema": "tn-bench-manifest/v1", "run_id": RUN, "notes": [],
                                         "timestamps": {}}).encode(),
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

    def tearDown(self):
        self._tmp.cleanup()

    def teardown(self, *args, **extra):
        env = self.cloud.env(BENCH_TXGEN_SHA="abcdef1", BENCH_PARAMETERS_FILE=str(self.params),
                             BENCH_CONTRACTS_SRC_DIR=str(self.contracts), **extra)
        return subprocess.run(["bash", str(self.tree / "benchmark" / "benchmark-teardown.sh"), "--run", RUN] + list(args),
                              env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=180)

    def manifest(self):
        return json.loads((self.results / "manifest.json").read_text())

    def instance_names(self):
        return [i["name"] for i in json.loads((self.cloud.state / "instances.json").read_text())]

    def tree_digest(self):
        h = hashlib.sha256()
        for p in sorted(self.results.rglob("*")):
            if p.is_file():
                h.update(p.relative_to(self.results).as_posix().encode() + b"\0" + p.read_bytes())
        return h.hexdigest()

    def assert_nothing_deleted(self, p):
        calls = self.cloud.calls()
        for words in DELETES:
            self.assertEqual(indices(calls, words), [], "%s ran: %s" % (" ".join(words), p.stdout[-2000:]))
        self.assertIn(INST, self.instance_names())
        self.assertTrue(self.cloud.objects(RUN_BUCKET))

    def test_archive_verified_before_the_first_delete(self):
        p = self.teardown("--yes")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("✓ teardown left nothing behind.", p.stdout)
        calls = self.cloud.calls()
        ssh = indices(calls, ("compute", "ssh"))
        rsync = indices(calls, ("storage", "rsync"))
        ls = [i for i in indices(calls, ("storage", "ls")) if "-l" in calls[i]["argv"]]
        first_delete = min(i for words in DELETES for i in indices(calls, words))
        self.assertEqual(len(ssh), 1, "the recovery evidence of the one live node")
        self.assertTrue(rsync and ls)
        # Evidence first, then the copy and its verification, then the deletes.
        self.assertLess(ssh[-1], rsync[0])
        self.assertLess(rsync[0], ls[0])
        self.assertLess(ls[0], first_delete)
        bucket_copy = [i for i in rsync if (GS + RUN_BUCKET) in calls[i]["argv"]]
        self.assertEqual(len(bucket_copy), 1)
        self.assertLess(bucket_copy[0], indices(calls, ("storage", "rm"))[0])
        # The gate's archive: logs, marker, evidence, manifest and the run bucket; never genesis,
        # the tunnel pid or dot-files. The final sync adds the run bucket's local copy.
        got = set(self.cloud.objects(ARCHIVE))
        res = PREFIX + "/results/"
        for name in ("logs/%s-telcoin.log.gz" % INST, "logs/%s.pulled" % INST, "manifest.json",
                     "bucket/%s/blasters/bench-blaster-01.json" % RUN_BUCKET):
            self.assertIn(res + name, got)
        self.assertTrue([n for n in got if n.startswith(res + "logs/%s-recovery-%s." % (INST, INST_ID))
                         and n.endswith(".tgz")])
        self.assertIn(PREFIX + "/bucket/%s/blasters/bench-blaster-01.json" % RUN_BUCKET, got)
        for n in got:
            self.assertNotRegex(n, r"/results/(genesis|tunnel\.pid|\.DS_Store|logs/\.)")
        # Manifest: verified before the deletes, synced after; the archived copy is the final one.
        a = self.manifest()["archive"]
        self.assertEqual(a["uri"], GS + ARCHIVE + "/" + PREFIX)
        self.assertEqual(a["status"], "verified-before-delete")
        self.assertRegex(a["verified_at"], ISO_RE)
        self.assertRegex(a["final_sync_at"], ISO_RE)
        self.assertEqual(self.cloud.objects(ARCHIVE, res + "manifest.json")[res + "manifest.json"],
                         (self.results / "manifest.json").read_bytes())
        # The archive bucket: created locked down and labelled, never deleted, counted at the end.
        self.assertEqual(self.cloud.labels(ARCHIVE), {"purpose": "bench-archive", "retain": "true"})
        self.assertIn("· archive (kept; cleaned by hand once the results are qualified): %d object(s)" % len(got),
                      p.stdout)
        self.assertNotIn(INST, self.instance_names())
        self.assertEqual(set(self.devnet), set(self.instance_names()))
        self.assertEqual(self.cloud.objects(RUN_BUCKET), {})
        for c in calls:
            self.assertNotIn("--delete-unmatched-destination-objects", c["argv"])

    def test_failed_copy_stops_before_any_delete(self):
        p = self.teardown("--yes", FAKE_FAIL="rsync")
        self.assertEqual(p.returncode, 1, p.stdout[-2000:])
        self.assertIn("failed — NOTHING was deleted.", p.stderr)
        self.assertIn("BENCH_TEARDOWN_SKIP_ARCHIVE=1 benchmark/benchmark-teardown.sh --yes --run " + RUN, p.stderr)
        self.assert_nothing_deleted(p)
        self.assertEqual(self.manifest()["archive"]["status"], "pending")
        self.assertTrue(list((self.results / "logs").glob(INST + "-recovery-*.tgz")), "evidence pulled first")

    def test_failed_verification_stops_before_any_delete(self):
        p = self.teardown("--yes", FAKE_TRUNCATE="-telcoin.log.gz")
        self.assertEqual(p.returncode, 1, p.stdout[-2000:])
        self.assertIn("lacks 1 of 4 file(s)", p.stderr)
        self.assertIn("NOTHING was deleted", p.stderr)
        self.assert_nothing_deleted(p)

    def test_skip_override_deletes_and_says_so(self):
        p = self.teardown("--yes", FAKE_FAIL="--exclude", BENCH_TEARDOWN_SKIP_ARCHIVE="1")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("deleting WITHOUT a verified archive", p.stderr)
        self.assertNotIn(INST, self.instance_names())
        m = self.manifest()
        self.assertEqual(m["archive"]["status"], "unverified")
        self.assertTrue(any("BENCH_TEARDOWN_SKIP_ARCHIVE=1" in n for n in m["notes"]), m["notes"])
        self.assertTrue(any("final archive sync failed" in n for n in m["notes"]), m["notes"])

    def test_config_refuses_an_archive_the_teardown_would_delete(self):
        for bucket, why in ((PROJECT + "-bench-archive", PROJECT + "-bench-* rule"), ("Bad_Name", "not a bucket name")):
            p = self.teardown("--yes", BENCH_ARCHIVE_BUCKET=bucket)
            self.assertEqual(p.returncode, 1)
            self.assertIn(why, p.stderr)
            self.assertEqual(self.cloud.calls(), [])
        p = self.teardown("--yes", BENCH_TEARDOWN_SKIP_ARCHIVE="yes")
        self.assertEqual(p.returncode, 1)
        self.assertIn("BENCH_TEARDOWN_SKIP_ARCHIVE='yes' must be 0 or 1", p.stderr)

    def test_dry_run_prints_the_gate_and_changes_nothing(self):
        before = self.tree_digest()
        p = self.teardown()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        out = p.stdout
        logs_at, gate_at, plan_at = (out.index(">>> node logs"), out.index(">>> archive -> " + GS + ARCHIVE),
                                     out.index(">>> plan / execution"))
        self.assertLess(logs_at, gate_at)
        self.assertLess(gate_at, plan_at)
        gate = out[gate_at:plan_at]
        self.assertIn("would be created", gate)
        self.assertIn("gcloud storage rsync -r --exclude=", gate)
        self.assertIn("gcloud storage ls -l", gate)
        self.assertIn("requires 3 file(s)", gate)   # dry run pulls no evidence: log, marker, manifest
        for c in self.cloud.calls():
            for words in MUTATIONS:
                self.assertFalse(is_call(c, words), "dry run executed gcloud " + " ".join(c["argv"]))
        self.assertEqual(self.tree_digest(), before)
        self.assertNotIn("archive", self.manifest())


if __name__ == "__main__":
    unittest.main()
