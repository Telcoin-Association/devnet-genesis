"""tools/archive-run.sh and tools/archive-verify.py, offline.

The archive bucket is the canonical copy of a finished run (runs/<run>/results/). archive-run.sh refuses
to upload when gcloud's own dry run would copy a file the archive rule keeps out (node keys under
genesis*/, tunnel pidfiles, dot-files), uploads with composite uploads off and never deletes, then
archive-verify.py checks the size and MD5 of every file the rule takes.

Each test copies the two tools and the repo's config.sh (the project comes from it) into a temporary
tree. gcloud is one of: a shim that prints REACHED and exits 9 (the dry run must not reach it), a
shim whose dry run lists what a broken exclude would (the refusal), or fixtures/teardown/fake-gcloud.py
(storage semantics: rsync with its list-flag exclude, --dry-run lines, objects list with MD5s).
"""
import base64
import hashlib
import importlib.util
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
REPO = BENCH.parent
FAKE_GCLOUD = TESTS / "fixtures" / "teardown" / "fake-gcloud.py"
STUB_PERL = TESTS / "fixtures" / "teardown" / "stub-perl.sh"
GS = "gs" + "://"
PROJECT = "tn-" + "devnet"
BUCKET = PROJECT + "-benchmark-archive"
RUN = "r20991231-0101"
URI = "%s%s/runs/%s/results/" % (GS, BUCKET, RUN)

_spec = importlib.util.spec_from_file_location("archive_verify", str(BENCH / "tools" / "archive-verify.py"))
AV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AV)

# What a run directory holds, the files the rule keeps out included.
TREE = {
    "manifest.json": b'{"run_id": "%s"}\n' % RUN.encode(),
    "INDEX.md": b"# index\n",
    "logs/bench-validator-01-telcoin.log.gz": b"\x1f\x8b" + b"x" * 300,
    "logs/bench-validator-01.pulled": b"tn-bench-pulled/v2\n",
    "analysis/cert-rate.md": b"# Certification rate\n",
    "genesis/validators/v1/bls-keystore.json": b"KEYSTORE",
    "genesis-old/node.key": b"KEY",
    "tunnel.pid": b"123\n",
    "tunnel-obs-prom.pid": b"124\n",
    ".DS_Store": b"x",
    "logs/.cert-rate.md.Ab12Cd": b"temp",
}
KEPT = sorted(r for r in TREE if not (r.startswith("genesis") or "tunnel" in r or "/." in "/" + r))


def b64md5(data):
    return base64.b64encode(hashlib.md5(data).digest()).decode()


class Tree(object):
    """A temporary repo copy with the two tools, config.sh, results/<RUN>/ and a bin dir first on PATH."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="archive-")
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        for rel in ("config.sh", "benchmark/tools/archive-run.sh", "benchmark/tools/archive-verify.py"):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / rel), str(self.repo / rel))
        self.results = self.repo / "benchmark" / "results" / RUN
        for rel, data in TREE.items():
            (self.results / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.results / rel).write_bytes(data)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "state"
        (self.state / "gcs" / BUCKET).mkdir(parents=True)
        self.calls = self.root / "calls.log"

    def cleanup(self):
        self._tmp.cleanup()

    def tool(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def fake_cloud(self):
        """fixtures/teardown/fake-gcloud.py as gcloud, and the alarm-recording perl stub."""
        for name, src in (("gcloud", FAKE_GCLOUD), ("perl", STUB_PERL)):
            shutil.copyfile(str(src), str(self.bin / name))
            (self.bin / name).chmod(0o755)

    def env(self, **extra):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "FAKE_ROOT": str(self.state), "CALLS": str(self.calls)}
        env.update(extra)
        return env

    def run(self, *args, **extra):
        return subprocess.run(["bash", str(self.repo / "benchmark" / "tools" / "archive-run.sh"), "--run", RUN] + list(args),
                              env=self.env(**extra), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=120)

    def verify(self, *args, **extra):
        return subprocess.run(["python3", str(self.repo / "benchmark" / "tools" / "archive-verify.py"), "--run", RUN]
                              + list(args), env=self.env(**extra), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=120)

    def gcloud_calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line)["argv"] for line in p.read_text().splitlines()] if p.exists() else []

    def archived(self):
        base = self.state / "gcs" / BUCKET / "runs" / RUN / "results"
        out = {}
        for d, _, files in os.walk(str(base)):
            for f in files:
                p = Path(d) / f
                out[str(p.relative_to(base))] = p.read_bytes()
        return out

    def report(self):
        return (self.repo / "benchmark" / "work" / "archive" / ("%s-verify.md" % RUN)).read_text()


class RuleTests(unittest.TestCase):
    PATHS = ("manifest.json", "genesis/a", "genesis/validators/v1/bls-keystore.json", "genesis-old/x", "genesis",
             "genesisfile", "logs/genesis/x", "tunnel.pid", "tunnel-obs-prom.pid", "logs/tunnel.pid", "tunnel.pid.gz",
             "tunnelpid", ".DS_Store", "logs/.DS_Store", ".hidden/x", "logs/.cert-rate.md.Ab12Cd", "a.b/c.d",
             "logs/bench-validator-01-telcoin.log.gz", "bucket/tn-x/blasters/b.json", "x/.y/z", "dot.file")

    def test_the_gcloud_regex_and_the_plain_rule_agree(self):
        for p in self.PATHS:
            with self.subTest(p=p):
                self.assertEqual(bool(re.match(AV.EXCLUDE, p)), AV.excluded(p))
        self.assertEqual([p for p in self.PATHS if AV.excluded(p)],
                         ["genesis/a", "genesis/validators/v1/bls-keystore.json", "genesis-old/x", "tunnel.pid",
                          "tunnel-obs-prom.pid", "logs/tunnel.pid", ".DS_Store", "logs/.DS_Store", ".hidden/x",
                          "logs/.cert-rate.md.Ab12Cd", "x/.y/z"])

    def test_the_regex_is_a_value_gcloud_reads_as_one_rule(self):
        # A list-flag value that starts with "^" is a delimiter spec (the rule is then dropped); a comma
        # splits it in two.
        self.assertFalse(AV.EXCLUDE.startswith("^"))
        self.assertNotIn(",", AV.EXCLUDE)

    def test_print_target_reads_the_project_from_config_sh(self):
        t = Tree()
        self.addCleanup(t.cleanup)
        p = t.verify("--print-target")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "PROJECT=%s\nBUCKET=%s\nURI=%s\nEXCLUDE=%s\n" % (PROJECT, BUCKET, URI, AV.EXCLUDE))
        p = t.verify("--print-target", BENCH_ARCHIVE_BUCKET="other-archive")
        self.assertIn("\nBUCKET=other-archive\nURI=%sother-archive/runs/%s/results/\n" % (GS, RUN), p.stdout)
        p = t.verify("--print-target", "--project", "Bad_Project")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(t.verify("--run", "../x", "--print-target").returncode, 2)


class ArchiveRunTests(unittest.TestCase):
    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.cleanup)

    def test_the_dry_run_calls_no_gcloud(self):
        self.t.tool("gcloud", "#!/bin/sh\necho REACHED\necho \"$*\" >> \"$CALLS\"\nexit 9\n")
        p = self.t.run("--dry-run")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("REACHED", p.stdout + p.stderr)
        self.assertFalse(self.t.calls.exists())
        self.assertIn(" + gcloud storage rsync -r --dry-run --exclude=", p.stdout)
        self.assertIn("--project=%s %s %s" % (PROJECT, self.t.results, URI.rstrip("/")), p.stdout)
        self.assertIn("(dry run — no gcloud call was made)", p.stdout)
        self.assertTrue(p.stdout.endswith("== archive-run run=%s rc=0 dry_run=1\n" % RUN), p.stdout)
        self.assertFalse((self.t.repo / "benchmark" / "work").exists())

    def test_a_dry_run_listing_with_an_excluded_file_is_refused_before_any_upload(self):
        # gcloud ignoring the rule (as it does a value starting with "^"): its dry run lists the node keys.
        self.t.tool("perl", STUB_PERL.read_text())
        self.t.tool("gcloud", "#!/bin/sh\necho \"$*\" >> \"$CALLS\"\n"
                    "case \"$*\" in *--dry-run*) ;; *) echo UPLOADED; exit 0 ;; esac\n"
                    "echo \"Would copy file://$7/manifest.json to $8/manifest.json\" >&2\n"
                    "echo \"Would copy file://$7/genesis/validators/v1/bls-keystore.json to $8/genesis/validators/v1/bls-keystore.json\" >&2\n")
        p = self.t.run()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("✗ would copy a file the rule excludes: genesis/validators/v1/bls-keystore.json", p.stdout)
        self.assertIn("DRYRUN would_copy=2 excluded=1 outside=0", p.stdout)
        self.assertIn("nothing was uploaded", p.stderr)
        calls = self.t.calls.read_text().splitlines()
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("--dry-run", calls[0])
        self.assertNotIn("UPLOADED", p.stdout)

    def test_a_dry_run_listing_outside_the_prefix_is_refused(self):
        self.t.tool("perl", STUB_PERL.read_text())
        self.t.tool("gcloud", "#!/bin/sh\necho \"$*\" >> \"$CALLS\"\n"
                    "echo \"Would copy file://$7/manifest.json to %sother/manifest.json\" >&2\n" % GS)
        p = self.t.run()
        self.assertEqual(p.returncode, 1)
        self.assertIn("DRYRUN would_copy=1 excluded=0 outside=1", p.stdout)
        self.assertEqual(len(self.t.calls.read_text().splitlines()), 1)

    def test_upload_then_verify_against_the_fake_bucket(self):
        self.t.fake_cloud()
        (self.t.state / "gcs" / BUCKET / "runs" / "r20261006-0458" / "results").mkdir(parents=True)
        (self.t.state / "gcs" / BUCKET / "runs" / "r20261006-0458" / "results" / "manifest.json").write_bytes(b"{}")
        p = self.t.run()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sorted(self.t.archived()), KEPT)
        self.assertEqual(self.t.archived(), {r: TREE[r] for r in KEPT})
        calls = self.t.gcloud_calls()
        self.assertEqual([c[:3] + [a for a in c if a == "--dry-run"] for c in calls],
                         [["storage", "rsync", "-r", "--dry-run"], ["storage", "rsync", "-r"], ["storage", "objects", "list"]])
        self.assertEqual([a for a in calls[0] if a != "--dry-run"], calls[1])
        self.assertIn("--exclude=" + AV.EXCLUDE, calls[1])
        self.assertTrue(all("--delete-unmatched-destination-objects" not in c for c in calls))
        self.assertEqual(calls[2], ["storage", "objects", "list", URI + "**", "--project=" + PROJECT,
                                    "--format=json(name,size,md5_hash)"])
        self.assertEqual((self.t.state / "alarms").read_text().split(), ["900", "gcloud", "28800", "gcloud"])
        rec = [json.loads(line[len("ARCHIVE_REMOTE "):]) for line in p.stdout.splitlines() if line.startswith("ARCHIVE_REMOTE ")]
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["uri"], URI)
        self.assertEqual((rec[0]["files"], rec[0]["bytes"]), (len(KEPT), sum(len(TREE[r]) for r in KEPT)))
        self.assertIn("ARCHIVE_VERIFY ok=1 run=%s files=%d " % (RUN, len(KEPT)), p.stdout)
        self.assertTrue(p.stdout.endswith("== archive-run run=%s rc=0\n" % RUN), p.stdout[-300:])
        self.assertEqual((self.t.state / "gcs" / BUCKET / "runs" / "r20261006-0458" / "results" / "manifest.json").read_bytes(), b"{}")
        # Composite uploads off for every gcloud call: the fake cannot see it, the script's export can.
        self.assertIn("export CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED=False",
                      (BENCH / "tools" / "archive-run.sh").read_text())
        # A re-run resumes: nothing new to copy, verified again.
        (self.t.results / "analysis" / "late.md").write_bytes(b"late\n")
        p = self.t.run()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.t.archived()["analysis/late.md"], b"late\n")

    def test_a_short_upload_fails_the_verify(self):
        self.t.fake_cloud()
        p = self.t.run(FAKE_TRUNCATE="telcoin.log.gz")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("✗ size 302 here, 301 in the bucket: logs/bench-validator-01-telcoin.log.gz", p.stdout)
        self.assertNotIn("ARCHIVE_REMOTE", p.stdout)
        self.assertTrue(p.stdout.endswith("== archive-run run=%s rc=1\n" % RUN))

    def test_a_failed_rsync_uploads_nothing_and_verifies_nothing(self):
        self.t.fake_cloud()
        p = self.t.run(FAKE_FAIL="--exclude=genesis")   # both rsyncs fail: the dry run first
        self.assertEqual(p.returncode, 1)
        self.assertIn("the rsync dry run failed", p.stderr)
        self.assertEqual(self.t.archived(), {})


class VerifyTests(unittest.TestCase):
    """archive-verify.py against a fake objects list: one case per problem it must catch."""

    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.cleanup)
        self.objs = {r: {"size": len(TREE[r]), "md5_hash": b64md5(TREE[r])} for r in KEPT}

    def listing(self, objs, rc=0):
        rows = [dict({"name": "runs/%s/results/%s" % (RUN, n)}, **o) for n, o in sorted(objs.items())]
        self.t.tool("gcloud", "#!/bin/sh\necho \"$*\" >> \"$CALLS\"\ncat <<'EOF'\n%s\nEOF\nexit %d\n" % (json.dumps(rows), rc))

    def check(self, objs, want_rc, *needles):
        self.listing(objs)
        p = self.t.verify()
        self.assertEqual(p.returncode, want_rc, p.stdout + p.stderr)
        for n in needles:
            self.assertIn(n, p.stdout)
        self.assertIn("ARCHIVE_VERIFY ok=%d " % (1 - want_rc), p.stdout.splitlines()[-1])
        self.assertEqual(len(self.t.calls.read_text().splitlines()), 1)
        return p

    def test_every_file_matches(self):
        p = self.check(self.objs, 0)
        last = p.stdout.splitlines()
        self.assertTrue(last[-2].startswith("ARCHIVE_REMOTE "))
        self.assertEqual(json.loads(last[-2][len("ARCHIVE_REMOTE "):])["files"], len(KEPT))
        self.assertIn("**Verdict:** every file matches by size and MD5", self.t.report())
        self.assertIn("| %d | %d | 6 | %d | %d | 0 | 0 | 0 | 0 | 0 | 0 |" % (
            len(KEPT), sum(len(TREE[r]) for r in KEPT), len(KEPT), len(KEPT)), self.t.report())

    def test_size_mismatch(self):
        self.objs["INDEX.md"]["size"] += 1
        self.check(self.objs, 1, "✗ size 8 here, 9 in the bucket: INDEX.md")

    def test_md5_mismatch(self):
        self.objs["INDEX.md"]["md5_hash"] = b64md5(b"other")
        self.check(self.objs, 1, "✗ MD5 differs: INDEX.md")

    def test_missing_object(self):
        del self.objs["analysis/cert-rate.md"]
        self.check(self.objs, 1, "✗ missing in the bucket: analysis/cert-rate.md")

    def test_object_without_md5(self):
        del self.objs["manifest.json"]["md5_hash"]
        self.check(self.objs, 1, "✗ object has no MD5 (a composite upload?): manifest.json")

    def test_an_excluded_file_in_the_bucket(self):
        for rel in ("genesis/validators/v1/bls-keystore.json", "tunnel.pid", ".DS_Store"):
            self.objs[rel] = {"size": len(TREE[rel]), "md5_hash": b64md5(TREE[rel])}
        p = self.check(self.objs, 1, "✗ EXCLUDED FILE IN THE BUCKET (the rule keeps it out): genesis/validators/v1/bls-keystore.json")
        self.assertIn("problems=3 ", p.stdout)

    def test_bucket_only_objects_are_listed_not_problems(self):
        self.objs["logs/pruned.log.gz"] = {"size": 1, "md5_hash": b64md5(b"x")}
        self.check(self.objs, 0)
        self.assertIn("- in the bucket only (no local file): logs/pruned.log.gz", self.t.report())

    def test_a_failed_listing_is_a_problem(self):
        self.t.tool("gcloud", "#!/bin/sh\necho 'ERROR: (gcloud.storage.objects.list) 403' >&2\nexit 1\n")
        p = self.t.verify()
        self.assertEqual(p.returncode, 1)
        self.assertIn("✗ object listing failed: gcloud storage objects list exited 1: ERROR: (gcloud.storage.objects.list) 403",
                      p.stdout)


class FakeGcloudExcludeTests(unittest.TestCase):
    """The fake models the trap the rule avoids: a "^" value is a delimiter spec and the rule is lost."""

    def test_a_caret_value_leaks_and_the_rule_does_not(self):
        t = Tree()
        self.addCleanup(t.cleanup)
        t.fake_cloud()

        def dry(value):
            p = subprocess.run(["gcloud", "storage", "rsync", "-r", "--dry-run", "--exclude=" + value,
                                "--project=" + PROJECT, str(t.results), URI.rstrip("/")], env=t.env(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            return [line.rsplit("/results/", 1)[1] for line in p.stderr.splitlines() if line.startswith("Would copy ")]

        self.assertEqual(sorted(dry(AV.EXCLUDE)), KEPT)
        self.assertIn("genesis/validators/v1/bls-keystore.json", dry("^" + AV.EXCLUDE))
        self.assertEqual(t.archived(), {})


if __name__ == "__main__":
    unittest.main()
