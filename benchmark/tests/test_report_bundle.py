"""report/make_bundle.py: everything that runs without the tn-transaction-generator tools.

make_bundle reads benchmark/results/<R> and writes benchmark/work/report/<R>; both roots are
module globals (RESULTS_ROOT, WORK_ROOT), so every test that touches them patches both to a
temporary directory first. Bundles are written to temporary out dirs only.

The site gate is ${BENCH_SITE_REPO}/scrub.py. CI has no site checkout, so the page-only path runs
there against a stub gate (a tiny scrub.py written at run time); the same path against the real
site scrub.py, and one full build of the 29 Sep blast-0 bundle, run only where the sibling
checkouts and benchmark/results exist.

Seeded leak values (IPs, links) are assembled at run time so this file stays clean.
"""
import argparse
import contextlib
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
MAKE_BUNDLE_PY = BENCH / "report" / "make_bundle.py"
SPEC = importlib.util.spec_from_file_location("report_make_bundle", MAKE_BUNDLE_PY)
mb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mb)

FIX = TESTS / "fixtures" / "report"
SYNTH = FIX / "synthetic-run"
PAGE_BACKFILL = FIX / "bundle-backfill" / "page-only.json"
PAGE_REPORT = FIX / "bundle-backfill" / "page-report.html"

SITE_REPO = REPO.parent / "tn-benchmarks"
SITE_SCRUB = SITE_REPO / "scrub.py"
SITE_BUILD = SITE_REPO / "build.py"
TXGEN_BENCH = REPO.parent / "tn-transaction-generator" / "bench"
RESULTS_29 = BENCH / "results" / "r20260929-1647"
HAS_GIT = shutil.which("git") is not None
SITE_ORIGIN = "git@github.com:" + "Telcoin-Association/tn-benchmarks.git"

# Name of the scratch dir's source marker (renamed once; both names are read back).
MARKER = getattr(mb, "SOURCE_MARKER", ".bundle-source.json")

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
RUN_KEYS = sorted([
    "caveats", "chain", "chaos", "compare_to", "consensus", "date", "ended_utc", "fleet", "generator",
    "harness", "headline", "id", "kpis", "methodology", "node_image", "recovery", "report", "schema",
    "series", "started_utc", "status", "summary", "title", "upstream", "windows", "workload"])

STUB_GATE = (
    "import json, os, sys\n"
    "here = os.path.dirname(os.path.abspath(__file__))\n"
    "with open(os.path.join(here, 'argv.json'), 'w') as fh:\n"
    "    json.dump(sys.argv[1:], fh)\n"
    "sys.exit(%d)\n")


def ip(*octets):
    return ".".join(str(o) for o in octets)


def load_json(path):
    with open(str(path)) as fh:
        return json.load(fh)


def write_json(path, doc):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh)


def write_text(path, text):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def sha256(path):
    with open(str(path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def tree(root):
    """Every file under root as a sorted list of relative paths."""
    out = []
    for d, _, files in os.walk(root):
        for f in files:
            out.append(os.path.relpath(os.path.join(d, f), root))
    return sorted(out)


def quiet(fn, *args, **kwargs):
    """Call fn with stdout/stderr captured; returns (result, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = fn(*args, **kwargs)
    return result, out.getvalue(), err.getvalue()


def node_log(sha, version="0.1.0", vote_timeout=None):
    lines = ["2026-01-01T00:00:00Z INFO telcoin-network %s (%s) starting" % (version, sha),
             "2026-01-01T00:00:01Z INFO Max header delay set to 3000 ms",
             "2026-01-01T00:00:01Z INFO Min header delay set to 1000 ms",
             "2026-01-01T00:00:01Z INFO Max batch delay set to 1000 ms"]
    if vote_timeout is not None:
        lines.append("2026-01-01T00:00:01Z INFO Vote timeout set to %d ms" % vote_timeout)
    return "\n".join(lines) + "\n"


def outside_git(path):
    return not HAS_GIT or mb.git_checkout_of(path) is None


class TmpMixin(object):
    """A temp dir with RESULTS_ROOT and WORK_ROOT patched inside it."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="tb2-bundle-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.results_root = os.path.join(self.tmp, "results")
        self.work_root = os.path.join(self.tmp, "work", "report")
        os.makedirs(self.results_root)
        for name, value in (("RESULTS_ROOT", self.results_root), ("WORK_ROOT", self.work_root)):
            p = mock.patch.object(mb, name, value)
            p.start()
            self.addCleanup(p.stop)

    def main(self, *argv, **env):
        with mock.patch.dict(os.environ, env):
            return quiet(mb.main, [str(a) for a in argv])


# --------------------------------------------------------------------------- arguments


class ParseArgsTests(unittest.TestCase):
    def exit_code(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            mb.parse_args(argv)
        return cm.exception.code

    def test_valid(self):
        a = mb.parse_args(["--run", "r20260101-0000", "--blast-index", "0", "--analysis-sha", "abcdef0"])
        self.assertEqual((a.run, a.blast_index, a.analysis_sha, a.force, a.no_results),
                         ("r20260101-0000", 0, "abcdef0", False, False))
        a = mb.parse_args(["--run", "r1", "--no-results", "--archived-report", "x.html", "--backfill", "b.json"])
        self.assertTrue(a.no_results)

    def test_usage_errors_exit_2(self):
        cases = [
            [],
            ["--run", "R1"],
            ["--run", "archived"],
            ["--run", "a" * 65],
            ["--run", "r1", "--compare", "Bad"],
            ["--run", "r1", "--compare", "archived"],
            ["--run", "r1", "--analysis-sha", "abc123"],
            ["--run", "r1", "--analysis-sha", "ABCDEF0"],
            ["--run", "r1", "--analysis-sha", "xyz1234"],
            ["--run", "r1", "--analysis-sha", "a" * 41],
            ["--run", "r1", "--no-results"],
            ["--run", "r1", "--no-results", "--archived-report", "x.html"],
            ["--run", "r1", "--no-results", "--backfill", "b.json"],
            ["--run", "r1", "--no-results", "--archived-report", "x", "--backfill", "b", "--blast-index", "0"],
            ["--run", "r1", "--blast-index", "-1"],
            ["--run", "r1", "--blast-index", "one"],
            ["--run", "r1", "--bogus"],
        ]
        for argv in cases:
            self.assertEqual(self.exit_code(argv), 2, argv)

    def test_cli_usage_exit_2(self):
        for extra in ([], ["--run", "Bad"]):
            p = subprocess.run([sys.executable, "-B", str(MAKE_BUNDLE_PY)] + extra, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("usage:", p.stderr)


# --------------------------------------------------------------------------- out dir


class OutDirTests(TmpMixin, unittest.TestCase):
    def test_last_component_must_be_run_id(self):
        with self.assertRaisesRegex(mb.BundleError, "must end in /r1"):
            mb.check_out_dir(os.path.join(self.tmp, "out", "r2"), "r1")
        if outside_git(self.tmp):
            self.assertIsNone(mb.check_out_dir(os.path.join(self.tmp, "out", "r1") + os.sep, "r1"))

    def test_refuses_results_and_work_roots(self):
        with self.assertRaisesRegex(mb.BundleError, "lies inside"):
            mb.check_out_dir(os.path.join(self.results_root, "r1"), "r1")
        with self.assertRaisesRegex(mb.BundleError, "lies inside"):
            mb.check_out_dir(os.path.join(self.work_root, "x", "r1"), "r1")

    def test_prepare_out(self):
        out = os.path.join(self.tmp, "out", "r1")
        mb.prepare_out(out)  # absent: fine
        write_text(os.path.join(out, "run.json"), "{}\n")
        write_text(os.path.join(out, "report.html"), "<p>x</p>\n")
        write_text(os.path.join(out, "series", "tps-1s.json"), "{}\n")
        write_text(os.path.join(out, "series", "old.json"), "{}\n")
        mb.prepare_out(out)
        write_text(os.path.join(out, "series", "x.csv"), "a\n")
        with self.assertRaisesRegex(mb.BundleError, "series holds x.csv"):
            mb.prepare_out(out)
        os.remove(os.path.join(out, "series", "x.csv"))
        write_text(os.path.join(out, "notes.txt"), "mine\n")
        with self.assertRaisesRegex(mb.BundleError, "holds notes.txt"):
            mb.prepare_out(out)
        os.remove(os.path.join(out, "notes.txt"))
        os.makedirs(os.path.join(out, "logs-copy"))
        with self.assertRaisesRegex(mb.BundleError, "holds logs-copy"):
            mb.prepare_out(out)
        f = os.path.join(self.tmp, "out", "r3")
        write_text(f, "file\n")
        with self.assertRaisesRegex(mb.BundleError, "not a directory"):
            mb.prepare_out(f)

    def test_main_refusals_write_nothing(self):
        bad = os.path.join(self.tmp, "out", "wrong")
        rc, _, err = self.main("--run", "r1", "--out", bad)
        self.assertEqual(rc, 1)
        self.assertIn("must end in /r1", err)
        self.assertFalse(os.path.exists(bad))
        out = os.path.join(self.tmp, "out", "r1")
        write_text(os.path.join(out, "keep.txt"), "mine\n")
        rc, _, err = self.main("--run", "r1", "--out", out, "--no-results", "--archived-report", PAGE_REPORT,
                               "--backfill", PAGE_BACKFILL)
        self.assertEqual(rc, 1)
        self.assertIn("refusing to touch it", err)
        self.assertEqual(tree(out), ["keep.txt"])


@unittest.skipUnless(HAS_GIT, "git is not installed")
class OutDirGitTests(TmpMixin, unittest.TestCase):
    def git_repo(self, name, origin):
        top = os.path.join(self.tmp, name)
        os.makedirs(top)
        subprocess.run(["git", "init", "-q", top], check=True)
        if origin:
            subprocess.run(["git", "-C", top, "remote", "add", "origin", origin], check=True)
        return top

    def test_foreign_checkout_refused(self):
        top = self.git_repo("other", "git@github.com:" + "example/other-repo.git")
        with self.assertRaisesRegex(mb.BundleError, "whose origin is not"):
            mb.check_out_dir(os.path.join(top, "runs", "r1"), "r1")
        rc, _, err = self.main("--run", "r1", "--out", os.path.join(top, "runs", "r1"), "--no-results",
                               "--archived-report", PAGE_REPORT, "--backfill", PAGE_BACKFILL)
        self.assertEqual(rc, 1)
        self.assertIn("whose origin is not", err)
        self.assertFalse(os.path.exists(os.path.join(top, "runs")))

    def test_checkout_without_origin_refused(self):
        top = self.git_repo("bare", None)
        with self.assertRaisesRegex(mb.BundleError, "whose origin is not"):
            mb.check_out_dir(os.path.join(top, "r1"), "r1")

    def test_site_checkout_accepted(self):
        top = self.git_repo("site", SITE_ORIGIN)
        got = mb.check_out_dir(os.path.join(top, "runs", "r1"), "r1")  # runs/ does not exist yet
        self.assertEqual(os.path.realpath(got), os.path.realpath(top))


# --------------------------------------------------------------------------- setup: MDBX sync mode


class SafeNoSyncTests(TmpMixin, unittest.TestCase):
    """A run whose nodes ran MDBX sync mode safe-no-sync is refused at setup unless --allow-safe-no-sync."""
    RUN = "r20260101-0000"

    def setUp(self):
        super(SafeNoSyncTests, self).setUp()
        self.tools = os.path.join(self.tmp, "tools")
        for f in ("aggregate.py", "derive-sizing.py", "build-report.py"):
            write_text(os.path.join(self.tools, f), "raise SystemExit('the refusal comes first')\n")
        r = os.path.join(self.results_root, self.RUN)
        write_json(os.path.join(r, "manifest.json"), {"node_startup": {
            "val-1": {"db_sync_mode": "durable"}, "val-2": {"db_sync_mode": "safe-no-sync"}}})
        write_json(os.path.join(r, "metrics.json"), {})
        write_json(os.path.join(r, "blasters", "load-a.json"), {"schema": "tn-blast/v2"})
        self.out = os.path.join(self.tmp, "out", self.RUN)

    def test_check(self):
        refusal = ("MDBX sync mode safe-no-sync on val-2 (manifest node_startup[].db_sync_mode): durability relaxed, "
                   "not comparable with durable runs; pass --allow-safe-no-sync to publish it with a caveat")
        m = {"node_startup": {"val-1": {"db_sync_mode": "durable"}, "val-2": {"db_sync_mode": "safe-no-sync"}}}
        with self.assertRaises(mb.BundleError) as cm:
            mb.sync_mode_check(m, False)
        self.assertEqual(str(cm.exception), refusal)
        _, _, err = quiet(mb.sync_mode_check, m, True)
        self.assertIn("--allow-safe-no-sync: publishing a run with MDBX sync mode safe-no-sync on val-2", err)
        for durable in ({}, {"node_startup": {"val-1": {"db_sync_mode": "durable"}, "val-2": {}}}):
            self.assertEqual(quiet(mb.sync_mode_check, durable, False), (None, "", ""))
        self.assertTrue(mb.parse_args(["--run", self.RUN, "--allow-safe-no-sync"]).allow_safe_no_sync)
        self.assertFalse(mb.parse_args(["--run", self.RUN]).allow_safe_no_sync)

    def test_main_refuses_before_provenance_and_writes_nothing(self):
        rc, out, err = self.main("--run", self.RUN, "--out", self.out, "--txgen-bench", self.tools)
        self.assertEqual(rc, 1, err)
        self.assertIn("make_bundle: error: MDBX sync mode safe-no-sync on val-2", err)
        self.assertNotIn("provenance", out)
        self.assertFalse(os.path.exists(self.out))
        # With the flag the run goes on to provenance (which this bare run then fails: no logs, no backfill sha).
        rc, out, err = self.main("--run", self.RUN, "--out", self.out, "--txgen-bench", self.tools, "--force",
                                 "--allow-safe-no-sync")
        self.assertNotIn("make_bundle: error: MDBX sync mode", err)
        self.assertIn("make_bundle: warning: --allow-safe-no-sync: publishing a run with MDBX sync mode safe-no-sync "
                      "on val-2 (caveat added)", err)


# --------------------------------------------------------------------------- step 1: scratch


class ScratchTests(TmpMixin, unittest.TestCase):
    RUN = "r20260101-0000"

    def setUp(self):
        super(ScratchTests, self).setUp()
        self.tools = os.path.join(self.tmp, "tools")
        write_json(os.path.join(self.tools, "reference-chains.json"), {"chains": []})
        r = self.results = os.path.join(self.results_root, self.RUN)
        write_json(os.path.join(r, "manifest.json"), {"which": "top"})
        write_json(os.path.join(r, "metrics.json"), {"which": "top"})
        write_json(os.path.join(r, "blasters", "load-a.json"), {"schema": "tn-blast/v2"})
        write_text(os.path.join(r, "blasters", "notes.txt"), "not json\n")
        write_text(os.path.join(r, "sampler", "val-1.csv"), "ts_unix,rss\n1,2\n")
        write_text(os.path.join(r, "sampler", "val-1.txt"), "x\n")
        write_text(os.path.join(r, "logs", "val-1-telcoin.log"), node_log(SHA))
        with gzip.open(os.path.join(r, "logs", "val-2-telcoin-kill-20260101T000500Z.log.gz"), "wt") as fh:
            fh.write(node_log(SHA))
        write_text(os.path.join(r, "logs", "val-2-unit-stdout.log"), "x\n")
        write_text(os.path.join(r, "logs", "deploy-20260101T000000Z.log"), "deploy\n")
        write_text(os.path.join(r, "logs", "blast-0.log"), "blast\n")
        for forbidden in ("bucket/x.json", "funder/f.json", "genesis/g.yaml", "evidence/e.json", "meta/m.json",
                          ".secrets/k", "tunnel.log", "deployments-bench.json", "pre-instances.json"):
            write_text(os.path.join(r, forbidden), "{}\n")
        b0 = os.path.join(r, "blast-0-20260101T010000Z")
        write_json(os.path.join(b0, "manifest.json"), {"which": "blast-0"})
        write_json(os.path.join(b0, "metrics.json"), {"which": "blast-0"})
        write_json(os.path.join(b0, "blasters", "load-b.json"), {"schema": "tn-blast/v2"})
        for d in ("blast-1-20260101T020000Z", "blast-1-20260101T030000Z"):
            write_json(os.path.join(r, d, "manifest.json"), {})
        write_text(os.path.join(r, "blast-2-file"), "not a dir\n")

    def prepare(self, blast_index=None, force=False, run=None):
        return quiet(mb.prepare_scratch, run or self.RUN, blast_index, force)[0]

    def test_allowlist_copy(self):
        scratch = self.prepare()
        self.assertEqual(scratch, os.path.join(self.work_root, self.RUN))
        # The node logs are not copied: provenance_step reads them in place in results/<run>/logs/.
        self.assertEqual(tree(scratch), sorted([
            MARKER, "blasters/load-a.json", "manifest.json", "metrics.json", "reference-chains.json",
            "sampler/val-1.csv"]))
        self.assertEqual(len(os.listdir(os.path.join(self.results, "logs"))), 5)
        self.assertEqual(load_json(os.path.join(scratch, "manifest.json")), {"which": "top"})
        marker = load_json(os.path.join(scratch, MARKER))
        self.assertEqual({k: marker[k] for k in ("run", "blast_index", "source")},
                         {"run": self.RUN, "blast_index": None, "source": self.RUN})

    def test_provenance_reads_the_logs_in_place(self):
        """The same provenance as from a copy of the logs (the old scratch/logs), without the copy."""
        self.prepare()
        in_place = quiet(mb.provenance_step, mb.results_path(self.RUN), {"node_git_sha": SHA}, {}, False)[0]
        copy_dir = os.path.join(self.tmp, "copied")
        shutil.copytree(os.path.join(self.results, "logs"), os.path.join(copy_dir, "logs"))
        copied = quiet(mb.provenance_step, copy_dir, {"node_git_sha": SHA}, {}, False)[0]
        self.assertEqual(in_place, copied)
        self.assertEqual(in_place["upstream"]["evidence"], "verified")
        self.assertIn("2 node starts across 2 instances", in_place["upstream"]["evidence_detail"][0])

    def test_blast_index_picks_its_dir(self):
        scratch = self.prepare(blast_index=0)
        self.assertEqual(load_json(os.path.join(scratch, "manifest.json")), {"which": "blast-0"})
        self.assertEqual(load_json(os.path.join(scratch, "metrics.json")), {"which": "blast-0"})
        self.assertEqual(os.listdir(os.path.join(scratch, "blasters")), ["load-b.json"])
        self.assertTrue(os.path.isfile(os.path.join(scratch, "sampler", "val-1.csv")))
        self.assertEqual(load_json(os.path.join(scratch, MARKER))["source"],
                         os.path.join(self.RUN, "blast-0-20260101T010000Z"))

    def test_blast_index_ambiguous_or_missing(self):
        for index, found in ((1, 2), (2, 0), (7, 0)):
            with self.assertRaisesRegex(mb.BundleError, "expected exactly one blast-%d-\\* dir.*found %d"
                                        % (index, found)):
                self.prepare(blast_index=index)
        self.assertFalse(os.path.exists(os.path.join(self.work_root, self.RUN)))

    def test_missing_sources(self):
        with self.assertRaisesRegex(mb.BundleError, "results dir does not exist"):
            self.prepare(run="r20990101-0000")
        os.remove(os.path.join(self.results, "blasters", "load-a.json"))
        with self.assertRaisesRegex(mb.BundleError, "no blasters"):
            self.prepare()
        os.remove(os.path.join(self.results, "metrics.json"))
        with self.assertRaisesRegex(mb.BundleError, "missing .*metrics.json"):
            self.prepare()

    def test_existing_scratch_needs_force(self):
        scratch = self.prepare()
        sentinel = os.path.join(scratch, "sentinel.json")
        write_text(sentinel, "{}\n")
        with self.assertRaisesRegex(mb.BundleError, "pass --force"):
            self.prepare()
        self.assertTrue(os.path.exists(sentinel))
        # --force with unusable sources refuses before deleting anything.
        with self.assertRaises(mb.BundleError):
            self.prepare(blast_index=1, force=True)
        self.assertTrue(os.path.exists(sentinel))
        self.prepare(blast_index=0, force=True)
        self.assertFalse(os.path.exists(sentinel))
        self.assertEqual(load_json(os.path.join(scratch, "manifest.json")), {"which": "blast-0"})

    def test_scratch_path(self):
        self.assertEqual(mb.scratch_path("r1"), os.path.join(self.work_root, "r1"))
        for bad in ("archived", "R1", "", "../r1", "r1/x"):
            with self.assertRaises(mb.BundleError):
                mb.scratch_path(bad)

    def test_remove_scratch_limited_to_work_report_children(self):
        os.makedirs(os.path.join(self.work_root, "r1", "sub"))
        os.makedirs(os.path.join(self.work_root, "archived"))
        elsewhere = os.path.join(self.tmp, "elsewhere", "r1")
        os.makedirs(elsewhere)
        refused = [self.work_root, os.path.join(self.work_root, "archived"), os.path.join(self.work_root, "r1", "sub"),
                   elsewhere, self.results]
        if hasattr(os, "symlink"):
            link = os.path.join(self.work_root, "r2")
            os.symlink(elsewhere, link)
            refused.append(link)
        for path in refused:
            with self.assertRaisesRegex(mb.BundleError, "refusing to delete"):
                mb.remove_scratch(path)
            self.assertTrue(os.path.exists(path), path)
        mb.remove_scratch(os.path.join(self.work_root, "r1"))
        self.assertFalse(os.path.exists(os.path.join(self.work_root, "r1")))
        self.assertTrue(os.path.isdir(elsewhere))


class CompareScratchTests(TmpMixin, unittest.TestCase):
    """A compare run's scratch is reused only when its marker names the requested blast."""
    R2 = "r20251201-0000"

    def scratch(self, marker=None, marker_name=MARKER, complete=True):
        s = os.path.join(self.work_root, self.R2)
        os.makedirs(s)
        if marker is not None:
            write_json(os.path.join(s, marker_name), marker)
        if complete:
            for n in ("combined.json", "metrics.json", "manifest.json", "sizing.json", "reference-chains.json"):
                write_json(os.path.join(s, "scrubbed", n), {})
        return s

    def test_scratch_state(self):
        self.assertEqual(mb.scratch_state(self.R2, None), ("absent", None))
        s = self.scratch({"run": self.R2, "blast_index": None})
        self.assertEqual(mb.scratch_state(self.R2, None), ("reuse", None))
        state, reason = mb.scratch_state(self.R2, 0)
        self.assertEqual(state, "mismatch")
        self.assertIn("top level", reason)
        os.remove(os.path.join(s, "scrubbed", "sizing.json"))
        self.assertEqual(mb.scratch_state(self.R2, None)[0], "mismatch")
        shutil.rmtree(s)
        self.scratch({"run": self.R2, "blast_index": 1}, marker_name=".bundle-source.json")
        self.assertEqual(mb.scratch_state(self.R2, 1), ("reuse", None))
        self.assertIn("blast 1", mb.scratch_state(self.R2, None)[1])

    def test_unmarked_scratch_is_a_mismatch(self):
        self.scratch(None)
        state, reason = mb.scratch_state(self.R2, None)
        self.assertEqual(state, "mismatch")
        self.assertIn("no source marker", reason)

    def test_check_compare(self):
        with self.assertRaisesRegex(mb.BundleError, "names the run itself"):
            mb.check_compare("r1", None, "r1", False)
        with self.assertRaisesRegex(mb.BundleError, "results dir does not exist"):
            mb.check_compare(self.R2, None, "r1", False)
        os.makedirs(os.path.join(self.results_root, self.R2))
        mb.check_compare(self.R2, None, "r1", False)  # no scratch yet: fine
        self.scratch({"run": self.R2, "blast_index": 2})
        with self.assertRaisesRegex(mb.BundleError, "pass --force.*--compare-blast-index"):
            mb.check_compare(self.R2, None, "r1", False)
        mb.check_compare(self.R2, None, "r1", True)
        mb.check_compare(self.R2, 2, "r1", False)

    def test_compare_blast_index_arguments(self):
        err = io.StringIO()
        for argv in (["--run", "r1", "--compare-blast-index", "0"],
                     ["--run", "r1", "--compare", "r2", "--compare-blast-index", "-1"]):
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                mb.parse_args(argv)
            self.assertEqual(cm.exception.code, 2, argv)
        a = mb.parse_args(["--run", "r1", "--compare", "r2", "--compare-blast-index", "3"])
        self.assertEqual((a.compare, a.compare_blast_index), ("r2", 3))


# --------------------------------------------------------------------------- backfill


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tb2-bf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def load(self, doc):
        path = os.path.join(self.tmp, "bf.json")
        with open(path, "w") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))
        return mb.load_backfill(path)

    def test_fixture_and_comments(self):
        doc = mb.load_backfill(str(PAGE_BACKFILL))
        self.assertNotIn("_comment", doc)
        self.assertNotIn("_comment", doc["upstream"])
        self.assertEqual(doc["upstream"]["sha"], SHA)
        self.assertEqual(self.load({"_note": "x", "fleet": {"_why": "y", "label": "L"}}), {"fleet": {"label": "L"}})
        self.assertEqual(mb.load_backfill(None), {})
        self.assertEqual(mb.load_backfill(""), {})

    def test_errors(self):
        cases = [
            ({"titel": "x"}, "unknown key 'titel'"),
            ({"fleet": {"labl": "x"}}, "unknown key fleet.labl"),
            ({"consensus": {"vote_timeout": 1}}, "unknown key consensus.vote_timeout"),
            ({"fleet": "x"}, "fleet must be an object"),
            ({"title": " "}, "title must be non-empty"),
            ({"status": "done"}, "status must be"),
            ({"date": "2026-1-2"}, "date must be"),
            ({"started_utc": "2026-01-02 00:00:00"}, "started_utc must be"),
            ({"compare_to": "Bad Id"}, "compare_to is not a run id"),
            ({"caveats": "one"}, "caveats must be a list"),
            ({"methodology": [""]}, "methodology must be a list"),
            ({"upstream": {"sha": "ABCDEF0"}}, "upstream.sha must be"),
            ({"upstream": {"sha": "abc12"}}, "upstream.sha must be"),
            ({"upstream": {"evidence": "trusted"}}, "upstream.evidence"),
            ({"upstream": {"evidence_detail": "x"}}, "evidence_detail"),
            ({"kpis_published": {}}, "kpis_published must be a list"),
            ({"report": {"modifications": [1]}}, "report.modifications"),
        ]
        for doc, msg in cases:
            with self.assertRaisesRegex(mb.BundleError, msg):
                self.load(doc)
        for text in ("[1, 2]", "{not json"):
            with self.assertRaises(mb.BundleError):
                self.load(text)
        with self.assertRaisesRegex(mb.BundleError, "backfill"):
            mb.load_backfill(os.path.join(self.tmp, "missing.json"))

    def test_placeholders_refused_naming_the_field(self):
        """A draft marker anywhere in a value stops the build; the message names the field, nested or indexed."""
        cases = [
            ({"summary": "fell 21%. <<RESULT>> one sentence on the tail."}, r"backfill: unfilled <<\.\.\.>> placeholder in summary$"),
            ({"upstream": {"sha": "a" * 40, "branch": "<<RESULT>> branch name"}}, r"placeholder in upstream\.branch$"),
            ({"caveats": ["fine", "<<RESULT>> decide the wording"]}, r"placeholder in caveats\[1\]$"),
            ({"upstream": {"evidence_detail": ["ok", "<<RESULT>>\nconfirm"]}}, r"upstream\.evidence_detail\[1\]$"),
            ({"title": "<<RESULT>> a", "methodology": ["<<x>>"]}, r"placeholder in title, methodology\[0\]$"),
        ]
        for doc, msg in cases:
            with self.assertRaisesRegex(mb.BundleError, msg):
                self.load(doc)
        # A comment key is dropped before publishing, so a marker there is not a leak; single angle
        # brackets and an unpaired "<<" are ordinary text.
        self.assertEqual(self.load({"_comment": "Every <<RESULT>> needs a human", "title": "T"}), {"title": "T"})
        self.assertEqual(self.load({"fleet": {"_todo": "<<RESULT>>", "label": "L"}}), {"fleet": {"label": "L"}})
        self.assertEqual(self.load({"title": "a <b> c", "summary": "x << y"})["summary"], "x << y")
        self.assertEqual(mb.find_placeholders({"a": [{"b": "<<R>>"}], "c": 1, "d": None}), ["a[0].b"])

    def test_run_json_with_a_placeholder_is_never_installed(self):
        """The assembled run.json is checked too, before the staging dir or anything under out/ exists."""
        out = os.path.join(self.tmp, "runs", "r20260101-0000")
        doc = {"id": "r20260101-0000", "title": "T", "caveats": ["ok", "<<RESULT>> wording"], "kpis": []}
        with self.assertRaisesRegex(mb.BundleError, r"^run\.json: unfilled <<\.\.\.>> placeholder in caveats\[1\]$"):
            mb.install_bundle(out, doc, os.path.join(self.tmp, "no-report.html"), None, {}, None, self.tmp)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "runs")))
        mb.refuse_placeholders({"summary": "clean", "kpis": [{"label": "<b>"}]}, "run.json")  # no error

    def test_published_kpis(self):
        kpi = {"id": "k", "label": "K", "short_label": "K", "value": 1.5, "unit": "tx/s", "source": "s"}
        self.assertEqual(mb.published_kpis([dict(kpi, _note="x")]),
                         [{"id": "k", "label": "K", "short_label": "K", "unit": "tx/s", "window": None, "source": "s",
                           "method": None, "provenance": "published", "value": 1.5}])
        rng = dict(kpi, range=[1, 2])
        del rng["value"]
        self.assertEqual(mb.published_kpis([rng])[0]["range"], [1, 2])
        bad = [(dict(kpi, range=[1, 2]), "exactly one of value / range"),
               ({k: v for k, v in kpi.items() if k != "label"}, "missing label"),
               (dict(kpi, provenance="computed"), "provenance must be"),
               (dict(kpi, extra=1), "unknown key"),
               ("k", "must be an object")]
        for entry, msg in bad:
            with self.assertRaisesRegex(mb.BundleError, msg):
                mb.published_kpis([entry])


# --------------------------------------------------------------------------- step 4: provenance


class ProvenanceStepTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="tb2-prov-")
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def logs(self, sha, **kw):
        write_text(os.path.join(self.scratch, "logs", "val-1-telcoin.log"), node_log(sha, **kw))
        write_text(os.path.join(self.scratch, "logs", "val-2-telcoin.log"), node_log(sha, **kw))

    def step(self, manifest, backfill, allow=False):
        return quiet(mb.provenance_step, self.scratch, manifest, backfill, allow)[0]

    def test_logs_verify_manifest_sha(self):
        self.logs(SHA)
        p = self.step({"node_git_sha": SHA}, {})
        up = p["upstream"]
        self.assertEqual((up["evidence"], up["sha"], up["short"]), ("verified", SHA, SHA[:9]))
        self.assertEqual(len(up["short"]), 9)
        self.assertEqual(up["repo"], mb.UPSTREAM_REPO)
        self.assertIn("2 node starts across 2 instances", up["evidence_detail"][0])
        self.assertIn("The node image probe recorded the same commit before deploy", up["evidence_detail"])
        self.assertEqual(p["version"], "0.1.0")
        self.assertEqual(p["params"], {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000,
                                       "max_batch_delay_ms": 1000})
        self.assertEqual(p["caveats"], [])

    def test_short_backfill_sha_upgraded_to_logged_sha(self):
        self.logs(SHA)
        up = self.step({}, {"upstream": {"sha": SHA[:9], "evidence_detail": ["extra line"]}})["upstream"]
        self.assertEqual((up["evidence"], up["sha"], up["short"]), ("verified", SHA, SHA[:9]))
        self.assertEqual(up["evidence_detail"][-1], "extra line")

    def test_mismatch_refused_unless_allowed(self):
        self.logs(SHA)
        with self.assertRaisesRegex(mb.BundleError, "provenance check failed"):
            self.step({}, {"upstream": {"sha": OTHER_SHA}})
        p = self.step({}, {"upstream": {"sha": OTHER_SHA}}, allow=True)
        self.assertEqual((p["upstream"]["evidence"], p["upstream"]["sha"]), ("inferred", OTHER_SHA))
        self.assertEqual(len(p["caveats"]), 1)
        self.assertIn("did not confirm the upstream commit", p["caveats"][0])
        p = self.step({}, {"upstream": {"sha": OTHER_SHA, "evidence": "not-recorded"}}, allow=True)
        self.assertEqual(p["upstream"]["evidence"], "not-recorded")

    def test_no_logs_uses_backfill_evidence(self):
        up = self.step({}, {"upstream": {"sha": SHA}})["upstream"]
        self.assertEqual((up["evidence"], up["sha"], up["short"]), ("inferred", SHA, SHA[:9]))
        up = self.step({}, {"upstream": {"sha": SHA, "evidence": "not-recorded", "branch": "main"}})["upstream"]
        self.assertEqual((up["evidence"], up["branch"]), ("not-recorded", "main"))
        up = self.step({}, {})["upstream"]
        self.assertEqual((up["evidence"], up["sha"], up["short"]), ("not-recorded", None, None))
        up = self.step({}, {"upstream": {"sha": "abcdef0"}})["upstream"]
        self.assertEqual((up["sha"], up["short"]), (None, "abcdef0"))
        with self.assertRaisesRegex(mb.BundleError, "no node logs"):
            self.step({}, {"upstream": {"sha": SHA, "evidence": "verified"}})


# --------------------------------------------------------------------------- step 7: assembly helpers


def fleet_manifest():
    return {
        "fleet": "three validators", "machine_type": "n2-standard-8",
        "node_disk": {"type": "hyperdisk-balanced", "size_gb": 200, "provisioned_iops": 6000,
                      "provisioned_throughput": 400},
        "instances": [
            {"name": "val-1", "role": "validator", "zone": "us-west2-a"},
            {"name": "val-2", "role": "validator", "zone": "us-east1-b"},
            {"name": "val-3", "role": "validator", "zone": "europe-west4-c"},
            {"name": "obs-1", "role": "observer", "zone": "us-west2-b"},
            {"name": "load-1", "role": "blaster", "zone": "asia-east1-a"},
        ],
        "blasters": [{"name": "load-1", "senders": 100}, {"name": "load-2", "senders": 200}],
    }


class AssembleHelperTests(unittest.TestCase):
    def test_fleet_block(self):
        metrics = {"instances": [{"name": "obs-1", "role": "observer", "vcpus": 2, "memory_mb": 4096},
                                 {"name": "val-1", "role": "validator", "vcpus": 8, "memory_mb": 32768}]}
        caveats = []
        fleet = mb.fleet_block(fleet_manifest(), metrics, {}, caveats)
        self.assertEqual(fleet, {
            "label": "three validators", "validators": 3, "observers": 1, "machine_type": "n2-standard-8",
            "vcpus": 8, "memory_gb": 32.0,
            "disk": {"type": "hyperdisk-balanced", "size_gb": 200, "iops": 6000, "throughput_mibps": 400},
            "regions": ["europe-west4 (Netherlands)", "us-east1 (South Carolina)", "us-west2 (Los Angeles)"],
            "load": {"blasters": 2, "machine_type": "not recorded", "senders_each": 200,
                     "placement": mb.DEFAULT_PLACEMENT}})
        self.assertEqual(len(caveats), 2)
        self.assertIn("different sender counts (100, 200)", caveats[0])
        self.assertIn("machine type was not recorded", caveats[1])

    def test_fleet_backfill_wins_and_merges(self):
        caveats = []
        bf = {"fleet": {"label": "BF label", "disk": {"iops": 3000},
                        "load": {"machine_type": "e2-standard-8", "placement": "custom"}}}
        fleet = mb.fleet_block(fleet_manifest(), {}, bf, caveats)
        self.assertEqual(fleet["label"], "BF label")
        self.assertEqual(fleet["disk"], {"type": "hyperdisk-balanced", "size_gb": 200, "iops": 3000,
                                         "throughput_mibps": 400})
        self.assertEqual(fleet["load"]["machine_type"], "e2-standard-8")
        self.assertEqual(fleet["load"]["placement"], "custom")
        self.assertEqual((fleet["vcpus"], fleet["memory_gb"]), (None, None))
        self.assertFalse(any("machine type" in c for c in caveats))

    def test_region_from_zone(self):
        self.assertEqual(mb._region("us-west2-a"), "us-west2")
        self.assertEqual(mb._region("europe-west4"), "europe-west4")
        self.assertEqual(mb._region(None), "")

    def test_region_labels_cover_the_fleet_and_its_alternates(self):
        fleet = {"us-west2": "Los Angeles", "europe-west2": "London", "australia-southeast1": "Sydney",
                 "asia-northeast1": "Tokyo", "northamerica-northeast1": "Montréal", "europe-west4": "Netherlands",
                 "asia-southeast1": "Singapore", "asia-east2": "Hong Kong", "asia-northeast3": "Seoul",
                 "asia-south1": "Mumbai"}
        alternates = {"asia-southeast2": "Jakarta", "asia-east1": "Taiwan", "asia-northeast2": "Osaka",
                      "australia-southeast2": "Melbourne", "europe-west3": "Frankfurt",
                      "southamerica-east1": "São Paulo", "me-west1": "Tel Aviv",
                      "us-east4": "Ashburn"}  # validator-05 in bench 3 (r20261103-1922): Montréal had no c3
        for region, city in list(fleet.items()) + list(alternates.items()):
            self.assertEqual(mb.region_label(region), "%s (%s)" % (region, city))
        self.assertEqual(mb.region_label("xx-nowhere9"), "xx-nowhere9")
        self.assertEqual(mb.region_label(mb._region("asia-south1-c")), "asia-south1 (Mumbai)")

    def test_chaos_block(self):
        m = {"chaos": [
            {"ts": "2026-01-01T00:05:00Z", "node": "val-2", "action": "systemctl start", "note": "", "rc": 0},
            {"ts": "2026-01-01T00:01:00Z", "node": "val-2", "action": "docker kill", "note": "outage", "rc": 0},
            {"ts": "2026-01-01T00:08:00Z", "node": "val-1", "action": "docker kill", "note": "retry", "rc": 1},
            {"ts": "2026-01-01T00:09:00Z", "node": "val-3", "action": "docker kill", "rc": 2},
            {"ts": "not a time", "node": "val-1", "action": "x"},
            {"ts": "2026-01-01T00:10:00Z", "node": "", "action": "x"},
            {"ts": "2026-01-01T00:11:00Z", "node": "val-1"},
        ]}
        self.assertEqual(mb.chaos_block(m), [
            {"t_utc": "2026-01-01T00:01:00Z", "node": "val-2", "action": "docker kill", "detail": "outage"},
            {"t_utc": "2026-01-01T00:05:00Z", "node": "val-2", "action": "systemctl start", "detail": None},
            {"t_utc": "2026-01-01T00:08:00Z", "node": "val-1", "action": "docker kill",
             "detail": "retry; the command failed (rc 1)"},
            {"t_utc": "2026-01-01T00:09:00Z", "node": "val-3", "action": "docker kill",
             "detail": "the command failed (rc 2)"}])
        self.assertEqual(mb.chaos_block({}), [])

    def consensus(self, manifest, prov, backfill):
        caveats = []
        return mb.consensus_block(manifest, prov, backfill, caveats), caveats

    def test_consensus_from_manifest_plus_backfill_vote_timeout(self):
        m = {"consensus_parameters": {"file": "consensus-parameters.yaml", "max_header_delay_ms": 3000,
                                      "min_header_delay_ms": 1000, "max_batch_delay_ms": 1000}}
        block, caveats = self.consensus(m, {}, {"consensus": {"vote_timeout_ms": 5000, "max_header_delay_ms": 3000}})
        self.assertEqual(block, {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000, "max_batch_delay_ms": 1000,
                                 "vote_timeout_ms": 5000, "file": "consensus-parameters.yaml",
                                 "confirmed_by": "harness manifest (consensus_parameters)"})
        self.assertEqual(len(caveats), 1)
        self.assertIn("consensus.vote_timeout_ms is not in the node logs", caveats[0])

    def test_consensus_contradiction_is_an_error(self):
        m = {"consensus_parameters": {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000,
                                      "max_batch_delay_ms": 1000}}
        with self.assertRaisesRegex(mb.BundleError, "consensus.max_header_delay_ms=2000 contradicts"):
            self.consensus(m, {}, {"consensus": {"max_header_delay_ms": 2000}})
        logs = {"params": {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000, "max_batch_delay_ms": 1000,
                           "vote_timeout_ms": 4000}}
        with self.assertRaisesRegex(mb.BundleError, "vote_timeout_ms=5000 contradicts"):
            self.consensus({}, logs, {"consensus": {"vote_timeout_ms": 5000}})
        block, caveats = self.consensus({}, logs, {})
        self.assertEqual((block["vote_timeout_ms"], block["file"], block["confirmed_by"]),
                         (4000, mb.LOGS_PARAMS_FILE, mb.LOGS_CONFIRMED_BY))
        self.assertEqual(caveats, [])

    def test_consensus_incomplete_is_null(self):
        block, caveats = self.consensus({}, {"params": {"max_header_delay_ms": 3000, "min_header_delay_ms": 1000,
                                                        "max_batch_delay_ms": 1000}}, {})
        self.assertIsNone(block)
        self.assertIn("vote_timeout_ms not recorded", caveats[0])
        block, caveats = self.consensus({}, {}, {})
        self.assertIsNone(block)
        self.assertIn("were not recorded", caveats[0])

    def test_workload_block(self):
        docs = [{"run": {"args": {"warmup_secs": 120, "duration_secs": 2400, "cooldown_secs": 180}}},
                {"run": {"args": {"warmup_secs": 120, "duration_secs": 2300, "cooldown_secs": 180}}}]
        combined = {"types": {"native_transfer": {"submitted": 5}, "wtel_wrap": {"landed_own": 1},
                              "unused": {"submitted": 0}, "odd": 3}}
        caveats = []
        self.assertEqual(mb.workload_block(docs, combined, {}, caveats), {
            "warmup_secs": 120, "mixed_secs": 2400, "cooldown_secs": 180,
            "tx_types": ["native_transfer", "wtel_wrap"]})
        self.assertEqual(len(caveats), 1)
        self.assertIn("different duration_secs (2300, 2400)", caveats[0])
        caveats = []
        self.assertIsNone(mb.workload_block([{}], {}, {}, caveats))
        self.assertIn("phase lengths were not recorded", caveats[0])
        bf = {"workload": {"warmup_secs": 60, "mixed_secs": 600, "cooldown_secs": 60, "tx_types": ["a"]}}
        self.assertEqual(mb.workload_block([{}], {}, bf, []),
                         {"warmup_secs": 60, "mixed_secs": 600, "cooldown_secs": 60, "tx_types": ["a"]})

    def test_harness_block(self):
        caveats = []
        h = mb.harness_block({"harness": {"sha": "abc", "dirty": True, "submodules": {"a": "x", "b": ""}}}, {}, caveats)
        self.assertEqual(h, {"sha": "abc", "submodules": {"a": "x", "b": None}})
        self.assertEqual(len(caveats), 1)
        self.assertEqual(mb.harness_block({}, {"harness": {"sha": "def", "submodules": {"c": None}}}, []),
                         {"sha": "def", "submodules": {"c": None}})

    def test_image_and_generator_blocks(self):
        digest = "sha256:" + "ab" * 32
        self.assertEqual(mb._image_parts("reg.example/p/r/node:v1@" + digest), ("node:v1", digest))
        self.assertEqual(mb._image_parts("reg.example/p/r/node@sha256:abc"), (None, None))
        self.assertEqual(mb._image_parts(None), (None, None))
        block = mb.node_image_block({"docker_image": "reg.example/p/r/node:v1@" + digest},
                                    {"version": "0.1.0", "fork_schedule": None},
                                    {"node_image": {"fork_schedule": "pre-subsecond", "version": "9.9"}})
        self.assertEqual(block, {"ref": "node:v1", "digest": digest, "version": "0.1.0",
                                 "fork_schedule": "pre-subsecond"})
        docs = [{"run": {"generator_git_sha": "aaa1111"}}, {"run": {"generator_git_sha": "aaa1111"}}]
        g = mb.generator_block({}, docs, {"generator": {"analysis_sha": "bbb2222"}}, None, None, [])
        self.assertEqual(g, {"sha": "aaa1111", "image_digest": None, "analysis_sha": "bbb2222"})
        g = mb.generator_block({"txgen_git_sha": "ccc3333"}, docs, {"generator": {"analysis_sha": "bbb2222"}},
                               "ddd4444", None, [])
        self.assertEqual((g["sha"], g["analysis_sha"]), ("ccc3333", "ddd4444"))
        docs.append({"run": {"generator_git_sha": "eee5555"}})
        self.assertIsNone(mb.generator_block({}, docs, {}, None, None, [])["sha"])

    def test_run_times_and_title(self):
        m = {"timestamps": {"deploy_start": "2026-01-01T00:00:00Z", "b": "2026-01-01T02:00:00Z",
                            "a": "2026-01-01T01:00:00Z", "bad": "x"}}
        self.assertEqual(mb.run_times(m), ("2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z"))
        self.assertEqual(mb.run_times({}), (None, None))
        # The teardown's end is the run's end when recorded, even with a later stamp (a --note after it).
        m["timestamps"].update(teardown_start="2026-01-01T01:30:00Z", teardown_done="2026-01-01T01:45:00+00:00")
        self.assertEqual(mb.run_times(m), ("2026-01-01T00:00:00Z", "2026-01-01T01:45:00Z"))
        m["timestamps"]["teardown_done"] = "not a time"  # unreadable: the latest stamp, as without one
        self.assertEqual(mb.run_times(m), ("2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z"))
        title, summary = mb.default_title("r1", {"validators": 3, "observers": 1, "machine_type": "n2"},
                                          {"mixed_secs": 2400})
        self.assertEqual((title, summary), ("Benchmark run r1", "3 validators and 1 observer(s) on n2, "
                                                                "40-minute mixed workload."))

    def test_merge_recovery(self):
        rec = {k: None for k in mb.RECOVERY_KEYS}
        rec.update(node="val-3", catch_up_secs=120)
        out, caveats = quiet(mb.merge_recovery, dict(rec), {"failed_reports": 7, "catch_up_secs": 99})[0]
        self.assertEqual((out["catch_up_secs"], out["failed_reports"]), (120, 7))
        self.assertEqual(caveats, ["recovery.failed_reports is the published value, not recomputed from the run data."])
        out, caveats = mb.merge_recovery(None, {"node": "val-9", "catch_up_secs": 5})
        self.assertEqual(sorted(out), sorted(mb.RECOVERY_KEYS))
        self.assertEqual(out["node"], "val-9")
        self.assertEqual(len(caveats), 1)
        self.assertEqual(mb.merge_recovery(None, None), (None, []))


# --------------------------------------------------------------------------- step 5: series


class ConsensusPerNodeTests(unittest.TestCase):
    """consensus_block with per-node values: consensus_parameters.overrides (deploy step 9) and
    param_arms (tools/params-apply.sh) become tables, and explain a spread of logged values."""

    FLEET = {"file": "consensus-parameters.yaml", "max_header_delay_ms": 500, "min_header_delay_ms": 250,
             "max_batch_delay_ms": 250}
    LOGS = {"max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250, "vote_timeout_ms": 5000}
    ARMS = [
        {"name": "a2", "begin": "2026-10-06T14:00:00Z", "end": None, "failed": "bench-validator-02",
         "nodes": {"bench-validator-01": {"max_header_delay": "700ms"},
                   "bench-validator-02": {"max_header_delay": "700ms"}}},
        {"name": "a1", "begin": "2026-10-06T13:00:00Z", "end": "2026-10-06T14:00:00Z",
         "nodes": {"bench-validator-01": {"max_header_delay": "600ms", "min_header_delay": "300ms"},
                   "bench-validator-02": {"max_header_delay": "600ms", "min_header_delay": "250ms"},
                   "bench-observer-11": {"max_header_delay": "600ms", "min_header_delay": "300ms"}}}]

    def manifest(self, overrides=None, arms=None):
        cp = dict(self.FLEET)
        if overrides is not None:
            cp["overrides"] = overrides
        m = {"consensus_parameters": cp}
        if arms is not None:
            m["param_arms"] = arms
        return m

    def consensus(self, manifest, param_values):
        caveats = []
        block = mb.consensus_block(manifest, {"params": dict(self.LOGS), "param_values": param_values}, {}, caveats)
        return block, caveats

    def test_overrides_and_arms_are_tables_and_explain_the_spread(self):
        m = self.manifest({"bench-validator-03": {"min_header_delay": "50ms", "max_header_delay": "250ms"}},
                          copy.deepcopy(self.ARMS))
        block, caveats = self.consensus(m, {"max_header_delay_ms": [250, 500, 600, 700],
                                            "min_header_delay_ms": [50, 250, 300]})
        self.assertEqual({k: block[k] for k in mb.CONSENSUS_NUM_KEYS},
                         {"max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250,
                          "vote_timeout_ms": 5000})
        self.assertEqual(block["overrides"], [
            {"instance": "bench-validator-03", "key": "max_header_delay", "value": "250ms"},
            {"instance": "bench-validator-03", "key": "min_header_delay", "value": "50ms"}])
        self.assertEqual(block["param_arms"], [
            {"arm": "a1", "begin_utc": "2026-10-06T13:00:00Z", "end_utc": "2026-10-06T14:00:00Z",
             "values": "all 3 nodes: max_header_delay=600ms; bench-observer-11: min_header_delay=300ms; "
                       "bench-validator-01: min_header_delay=300ms; bench-validator-02: min_header_delay=250ms"},
            {"arm": "a2", "begin_utc": "2026-10-06T14:00:00Z", "end_utc": None,
             "values": "all 2 nodes: max_header_delay=700ms (stopped at bench-validator-02, which did not come "
                       "back after its restart)"}])
        self.assertEqual(caveats, [
            "The nodes ran more than one max_header_delay_ms (250, 500, 600, 700) by design: the fleet value is "
            "published here, and the per-node values are listed under consensus.overrides and consensus.param_arms.",
            "The nodes ran more than one min_header_delay_ms (50, 250, 300) by design: the fleet value is "
            "published here, and the per-node values are listed under consensus.overrides and consensus.param_arms."])
        self.assertFalse(any("more than one max_header_delay_ms (250, 500, 600, 700);" in c for c in caveats))
        json.dumps(block)   # serialisable as is

    def test_a_value_no_node_was_given_keeps_the_old_caveat(self):
        m = self.manifest({"bench-validator-03": {"max_header_delay": "250ms"}})
        block, caveats = self.consensus(m, {"max_header_delay_ms": [250, 500, 900]})
        self.assertEqual(caveats, ["The node logs show more than one max_header_delay_ms (250, 500, 900); "
                                   "the last one logged is published."])
        self.assertEqual(block["overrides"], [{"instance": "bench-validator-03", "key": "max_header_delay",
                                               "value": "250ms"}])
        self.assertNotIn("param_arms", block)

    def test_without_per_node_values_the_block_is_unchanged(self):
        for m in (self.manifest(), self.manifest({}, [])):
            block, caveats = self.consensus(m, {"max_header_delay_ms": [500, 600]})
            self.assertEqual(sorted(block), sorted(mb.CONSENSUS_NUM_KEYS + ("file", "confirmed_by")))
            self.assertEqual(len(caveats), 1)
            self.assertIn("more than one max_header_delay_ms (500, 600); the last one logged is published", caveats[0])

    def test_rows_that_are_not_tool_written_are_refused(self):
        bad_overrides = [
            {"bench-validator-03": {"max_header_delay": "/" + "tmp/x"}},
            {"bench-validator-03": {"max_header_delay": "192.0.2.7"}},
            {"bench-validator-03": {"max_header_delay": 250}},
            {"Bench Validator": {"max_header_delay": "250ms"}},
            {"bench-validator-03": {"Max-Header": "250ms"}},
        ]
        for ov in bad_overrides:
            with self.assertRaises(mb.BundleError, msg=ov):
                self.consensus(self.manifest(ov), {})
        arm = self.ARMS[1]
        for bad in ({"name": "Arm_1"}, {"begin": "13:00"}, {"end": "tomorrow"}, {"failed": "x y"},
                    {"nodes": ["bench-validator-01"]}):
            with self.assertRaises(mb.BundleError, msg=bad):
                self.consensus(self.manifest(None, [dict(arm, **bad)]), {})
        with self.assertRaisesRegex(mb.BundleError, "param_arms is not a list"):
            self.consensus(self.manifest(None, {"a1": arm}), {})


class SeriesTests(unittest.TestCase):
    T0 = 1767225600

    def windows_step(self, secs):
        scratch = tempfile.mkdtemp(prefix="tb2-series-")
        self.addCleanup(shutil.rmtree, scratch, True)
        t0 = self.T0
        for label, lo, hi in (("load-a", t0, t0 + secs), ("load-b", t0 + 1, t0 + secs - 1)):
            write_json(os.path.join(scratch, "blasters", label + ".json"), {
                "schema": "tn-blast/v2",
                "run": {"label": label, "phases": [{"name": "mixed", "start_unix": lo, "end_unix": hi}]}})
        combined = {"landed": {"window_secs": {"start_unix": t0, "end_unix": t0 + secs}},
                    "series": {"per_second_columns": ["s", "chain_tx"], "per_second_t0_unix": t0,
                               "per_second": [[i, 100 + (i % 7)] for i in range(secs)]}}
        built, tps5, series = quiet(mb.windows_step, scratch, combined)[0]
        return combined, built, tps5, series

    def test_downsampled_to_at_most_2000_rows(self):
        for secs, step, rows in ((700, 1, 700), (2000, 1, 2000), (2001, 2, 1001), (5000, 3, 1667)):
            combined, _, _, series = self.windows_step(secs)
            self.assertEqual((series["step_s"], len(series["rows"])), (step, rows), secs)
            self.assertLessEqual(len(series["rows"]), mb.MAX_1S_ROWS)
            self.assertEqual([r[0] for r in series["rows"]], list(range(0, secs, step)))
            vals = [100 + (i % 7) for i in range(secs)]
            for off, value in series["rows"]:
                chunk = vals[off:off + step]
                self.assertEqual(value, mb._r(sum(chunk) / float(len(chunk)), 1))
            self.assertEqual(series["schema"], mb.SERIES_SCHEMA_ID)
            self.assertEqual(series["columns"], ["offset_s", "chain_tps"])
            self.assertEqual(series["start_utc"], "2026-01-01T00:00:00Z")

    def test_five_minute_blocks(self):
        _, built, tps5, _ = self.windows_step(700)
        self.assertEqual(tps5["columns"], ["start_utc", "end_utc", "generators_active", "chain_tps"])
        self.assertEqual([r[:2] for r in tps5["rows"]], [
            ["2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z"], ["2026-01-01T00:05:00Z", "2026-01-01T00:10:00Z"],
            ["2026-01-01T00:10:00Z", "2026-01-01T00:11:40Z"]])
        self.assertEqual(built["merged"]["secs"], 700)

    def test_window_problems_refused(self):
        scratch = tempfile.mkdtemp(prefix="tb2-series-")
        self.addCleanup(shutil.rmtree, scratch, True)
        write_json(os.path.join(scratch, "blasters", "a.json"), {
            "schema": "tn-blast/v2", "run": {"label": "a", "phases": [{"name": "mixed", "start_unix": 0,
                                                                       "end_unix": 10}]}})
        with self.assertRaisesRegex(mb.BundleError, "windows:"):
            quiet(mb.windows_step, scratch, {"landed": {"window_secs": {"start_unix": 0, "end_unix": 11}}})
        os.remove(os.path.join(scratch, "blasters", "a.json"))
        with self.assertRaisesRegex(mb.BundleError, "no tn-blast results"):
            mb.windows_step(scratch, {})


# --------------------------------------------------------------------------- step 8: write + rounding


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tb2-write-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_half_up_rounding(self):
        self.assertEqual(mb._r(2.675, 2), 2.68)      # round() gives 2.67
        self.assertEqual(mb._r(1.005, 2), 1.01)      # round() gives 1.0
        self.assertEqual(mb._r(0.125, 2), 0.13)
        self.assertEqual(mb._r(-0.25, 1), -0.3)
        self.assertEqual(mb._r(4177.24999, 1), 4177.2)
        self.assertEqual(mb._r(7, 1), 7.0)
        self.assertIsNone(mb._r(None, 1))
        out = mb._round_floats({"a": [1.23456, {"b": 2}], "c": float("nan"), "d": True, "e": "1.23456"})
        self.assertEqual((out["a"], out["d"], out["e"]), ([1.235, {"b": 2}], True, "1.23456"))
        self.assertTrue(math.isnan(out["c"]))
        self.assertEqual(mb._round_floats([0.33333], nd=1), [0.3])

    def test_dump_json_sorted_with_trailing_newline(self):
        path = os.path.join(self.tmp, "x.json")
        mb._dump_json({"b": 1, "a": {"d": "é", "c": 2}}, path)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{\n  "a": {\n    "c": 2,\n    "d": "é"\n  },\n  "b": 1\n}\n')

    def test_write_bundle(self):
        out = os.path.join(self.tmp, "out", "r1")
        doc = {"z": 1.23456, "a": [0.5]}
        series = {"rows": [[0, 10.04], [1, 1 / 3.0]]}
        quiet(mb.write_bundle, out, doc, str(PAGE_REPORT), series)
        self.assertEqual(tree(out), ["report.html", "run.json", "series/tps-1s.json"])
        with open(os.path.join(out, "run.json")) as fh:
            text = fh.read()
        self.assertEqual(text, '{\n  "a": [\n    0.5\n  ],\n  "z": 1.235\n}\n')
        self.assertEqual(load_json(os.path.join(out, "series", "tps-1s.json")), {"rows": [[0, 10.04], [1, 0.333]]})
        self.assertEqual(sha256(os.path.join(out, "report.html")), sha256(PAGE_REPORT))
        write_text(os.path.join(out, "series", "stale.json"), "{}\n")
        quiet(mb.write_bundle, out, doc, str(PAGE_REPORT), series)
        self.assertEqual(tree(out), ["report.html", "run.json", "series/tps-1s.json"])
        quiet(mb.write_bundle, out, doc, str(PAGE_REPORT), None)
        self.assertEqual(tree(out), ["report.html", "run.json"])
        write_text(os.path.join(out, "extra.txt"), "x\n")
        with self.assertRaises(mb.BundleError):
            mb.write_bundle(out, doc, str(PAGE_REPORT), None)
        self.assertTrue(os.path.exists(os.path.join(out, "extra.txt")))


# --------------------------------------------------------------------------- steps 5-9 offline


def enriched_synthetic_manifest():
    """The synthetic-run manifest plus the fleet/chain fields a publishable run.json needs."""
    m = load_json(SYNTH / "manifest.json")
    m.update({"fleet": "3 validators + 1 observer", "machine_type": "n2-standard-4", "chain_id": 2017,
              "epoch_duration_secs": 86400, "node_disk": {"type": "pd-ssd", "size_gb": 100},
              "prometheus": {"network_label": "bench"},
              "timestamps": {"deploy_start": "2025-12-31T23:30:00Z", "blast_end": "2026-01-01T00:20:00Z"}})
    zones = {"val-1": "us-west2-a", "val-2": "us-east1-b", "val-3": "us-west2-c", "obs-1": "us-west2-a"}
    for inst in m["instances"]:
        if inst["name"] in zones:
            inst["zone"] = zones[inst["name"]]
    return m


def load_site_scrub():
    spec = importlib.util.spec_from_file_location("site_scrub_for_tests", str(SITE_SCRUB))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OfflineAssemblyTests(unittest.TestCase):
    """Steps 4-8 on the synthetic run (no tools): run.json shape, harness scan, site schema."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tb2-asm-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, backfill, all_generators_secs=None, manifest_update=None):
        manifest = enriched_synthetic_manifest()
        manifest.update(manifest_update or {})
        metrics, combined = load_json(SYNTH / "metrics.json"), load_json(SYNTH / "combined.json")
        a = mb.parse_args(["--run", "r20260101-synth", "--analysis-sha", "abcdef0"])

        def run():
            prov = mb.provenance_step(self.tmp, manifest, backfill, False)
            built, tps5, series = mb.windows_step(str(SYNTH), combined)
            if all_generators_secs is not None:
                start = built["all_generators"]["start_unix"]
                built["all_generators"] = {"start_unix": start, "end_unix": start + all_generators_secs,
                                           "secs": all_generators_secs}
            kp, head, rec, kc = mb.kpis_step(str(SYNTH), combined, metrics, manifest, built, backfill)
            report = mb.report_block(str(PAGE_REPORT), None, backfill)
            docs = mb.win.load_blasters(str(SYNTH / "blasters"))
            doc = mb.assemble("r20260101-synth", a, manifest, metrics, combined, docs, prov, built, tps5, kp, head,
                              rec, kc, report, None, backfill, None)
            out = os.path.join(self.tmp, "out", "r20260101-synth")
            mb.write_bundle(out, doc, str(PAGE_REPORT), series)
            return doc, out
        (doc, out), _, err = quiet(run)
        return manifest, doc, out, err

    def test_run_json(self):
        bf = {"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA},
              "caveats": ["First caveat."], "kpis_published": [
                  {"id": "x_published", "label": "X", "short_label": "X", "value": 1, "unit": "u", "source": "s"}]}
        manifest, doc, out, err = self.build(bf)
        self.assertEqual(sorted(doc), RUN_KEYS)
        self.assertEqual((doc["schema"], doc["id"], doc["status"], doc["date"]),
                         (mb.SCHEMA_ID, "r20260101-synth", "complete", "2025-12-31"))
        self.assertEqual((doc["started_utc"], doc["ended_utc"]), ("2025-12-31T23:30:00Z", "2026-01-01T00:20:00Z"))
        self.assertEqual(doc["upstream"]["evidence"], "inferred")
        self.assertEqual(doc["upstream"]["short"], SHA[:9])
        self.assertEqual(doc["headline"], "avg_chain_tps_all_generators")
        self.assertEqual([k["provenance"] for k in doc["kpis"]].count("computed"), 14)  # 13 + time_to_land_corrected_p50_s
        self.assertEqual(doc["kpis"][-1]["id"], "x_published")
        self.assertEqual(doc["fleet"]["regions"], ["us-east1 (South Carolina)", "us-west2 (Los Angeles)"])
        self.assertEqual(doc["chain"], {"chain_id": 2017, "network": "bench", "epoch_secs": 86400})
        self.assertEqual(doc["windows"]["merged_mixed"]["secs"], 700)
        self.assertEqual(doc["series"]["tps_1s"], "series/tps-1s.json")
        self.assertEqual(len(doc["chaos"]), 4)
        self.assertEqual(doc["recovery"]["node"], "val-3")
        self.assertEqual(doc["caveats"][0], "First caveat.")
        self.assertEqual(len(doc["caveats"]), len(set(doc["caveats"])))
        self.assertEqual(doc["report"]["archived_from"], None)
        self.assertEqual(doc["generator"]["analysis_sha"], "abcdef0")
        self.assertNotIn("no backfill title/summary", err)
        self.assertEqual(mb.hscrub.scan_dir(out, manifest), [])
        series = load_json(os.path.join(out, "series", "tps-1s.json"))
        self.assertEqual((series["step_s"], len(series["rows"])), (1, 700))

    def test_short_all_generators_window_is_a_caveat_not_a_best_60s(self):
        # Fewer than 60 s with every generator running: no best-60-s figure (the old code published the
        # window's plain mean under that label); run.json says why instead.
        _, doc, out, _ = self.build({"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA}},
                                    all_generators_secs=45)
        ids = [k["id"] for k in doc["kpis"]]
        self.assertNotIn("best_60s_chain_tps_all_generators", ids)
        self.assertEqual(len(ids), 13)
        self.assertEqual(doc["headline"], "avg_chain_tps_all_generators")
        self.assertEqual(doc["windows"]["all_generators"]["secs"], 45)
        self.assertIn("The all-generators window is 45 s, shorter than 60 s: best-60-s chain throughput not computed.",
                      doc["caveats"])
        if SITE_SCRUB.is_file():
            self.assertEqual(load_site_scrub().validate_run(load_json(os.path.join(out, "run.json"))), [])

    def test_placeholders_without_title(self):
        _, doc, _, err = self.build({})
        self.assertIn("no backfill title/summary", err)
        self.assertEqual(doc["title"], "Benchmark run r20260101-synth")
        self.assertEqual(doc["upstream"]["evidence"], "not-recorded")

    @unittest.skipUnless(SITE_SCRUB.is_file(), "no tn-benchmarks checkout next to this repo")
    def test_site_schema_accepts_it(self):
        site = load_site_scrub()
        _, doc, out, _ = self.build({"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA}})
        self.assertEqual(site.validate_run(load_json(os.path.join(out, "run.json"))), [])
        self.assertEqual([f.format() for f in site.check_bundle(out)], [])


def certification_manifest(failing=True):
    """enriched_synthetic_manifest plus the certification outcome the harness records for its three
    validators; with <failing>, val-3 certified none of its headers in the mixed phase."""
    def cell(proposed, certified, leader, not_committed):
        return {"proposed": proposed, "certified": certified, "rate_pct": round(100.0 * certified / proposed, 1),
                "own_cert_share_pct": leader, "own_leader_share_pct": leader, "not_committed_pct": not_committed}
    m = enriched_synthetic_manifest()
    v3_mixed = 0 if failing else 594
    m["certification"] = {
        "val-1": {"phase warmup": cell(120, 120, 34.0, 0.0), "phase mixed": cell(600, 600, 45.0, 0.0),
                  "run": cell(720, 720, 43.0, 0.0)},
        "val-2": {"phase warmup": cell(120, 119, 33.0, 0.8), "phase mixed": cell(600, 597, 50.0, 0.5),
                  "run": cell(720, 716, 47.0, 0.6)},
        "val-3": {"phase warmup": cell(30, 30, 33.0, 0.0), "phase mixed": cell(600, v3_mixed, 5.0, 2.5),
                  "run": cell(630, 30 + v3_mixed, 10.0, 2.4)}}
    m["certification_meta"] = {"fail_below_pct": 90, "min_proposed": 50, "source": "analysis/certification.json",
                               "windows": ["phase warmup", "phase mixed", "run"], "recorded_at": "2026-01-01T00:30:00Z"}
    m["cert_failures"] = [{"inst": "val-3", "window": "phase mixed", "rate_pct": 0.0, "proposed": 600, "certified": 0,
                           "windows": ["phase mixed", "run"],
                           "logs": ["logs/val-3-telcoin-cert-fail-20260101T003000Z.log.gz", "logs/val-3-telcoin.log.gz"]}] \
        if failing else []
    return m


class CertificationBundleTests(unittest.TestCase):
    """The "Certification by node" table (built report) and the caveat (run.json) from manifest.certification."""
    RUN = "r20260101-synth"
    CAVEAT = ("Validator val-3 certified fewer than 90 % of its own headers in phase mixed and run; its logs are "
              "preserved under results/r20260101-synth/logs/ (see INDEX.md).")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tb2-cert-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, manifest):
        """Steps 6-9 as _main runs them: the section goes into the report before its digest is taken."""
        metrics, combined = load_json(SYNTH / "metrics.json"), load_json(SYNTH / "combined.json")
        a = mb.parse_args(["--run", self.RUN, "--analysis-sha", "abcdef0"])
        backfill = {"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA}}
        report_src = os.path.join(self.tmp, "report.html")
        shutil.copyfile(str(PAGE_REPORT), report_src)

        def run():
            mb.add_certification_section(report_src, mb.certification_html(manifest))
            prov = mb.provenance_step(self.tmp, manifest, backfill, False)
            built, tps5, series = mb.windows_step(str(SYNTH), combined)
            kp, head, rec, kc = mb.kpis_step(str(SYNTH), combined, metrics, manifest, built, backfill)
            report = mb.report_block(report_src, None, backfill)
            docs = mb.win.load_blasters(str(SYNTH / "blasters"))
            doc = mb.assemble(self.RUN, a, manifest, metrics, combined, docs, prov, built, tps5, kp, head,
                              rec, kc, report, None, backfill, None)
            out = os.path.join(self.tmp, "out", self.RUN)
            mb.write_bundle(out, doc, report_src, series)
            return doc, out
        (doc, out), _, _ = quiet(run)
        with open(os.path.join(out, "report.html"), encoding="utf-8") as fh:
            return doc, out, fh.read()

    def test_table_rows_and_caveat_for_a_failing_validator(self):
        m = certification_manifest()
        doc, out, page = self.build(m)
        self.assertEqual(page.count("<h2>Certification by node</h2>"), 1)
        rows = [r for r in page.split("<tr>") if r.startswith("<td>val-")]
        self.assertEqual([r[4:9] for r in rows], ["val-1", "val-2", "val-3"])
        for r in rows:
            self.assertEqual(r.count("<td"), 2 + 3 + 2, r)   # validator, region, three windows, two shares
        self.assertIn("<td>us-west2 (Los Angeles)</td>", rows[0])
        self.assertIn("<td>us-east1 (South Carolina)</td>", rows[1])
        self.assertIn("val-3 <strong>below 90 %</strong>", rows[2])
        self.assertIn("<strong>0.0</strong>", rows[2])
        self.assertIn("<td class='num muted' title='30 of 30 own headers certified (fewer than 50 proposed: not judged)'>"
                      "100.0</td>", rows[2])
        self.assertIn("<td class='num'>10.0</td><td class='num'>2.4</td></tr>", rows[2], "run-window shares")
        self.assertNotIn("<strong>", rows[0] + rows[1])
        self.assertIn("val-3 certified fewer than 90 % of its own headers in a window where it proposed at least 50.", page)
        self.assertIn("the fair share is 100 / 3 validators = 33.3 %", page)
        self.assertIn(self.CAVEAT, doc["caveats"])
        self.assertEqual(mb.certification_caveat(m, self.RUN), self.CAVEAT)
        # The report's digest is taken after the section went in; the bundle passes the leak scan.
        self.assertEqual(doc["report"]["sha256"], sha256(os.path.join(out, "report.html")))
        self.assertEqual(mb.hscrub.scan_dir(out, m), [])

    def test_every_validator_at_or_above_the_threshold(self):
        m = certification_manifest(failing=False)
        doc, _, page = self.build(m)
        self.assertIn("Every validator certified at least 90 % of its own headers in every window where it proposed "
                      "at least 50.", page)
        self.assertNotIn("below 90 %", page)
        self.assertNotIn("<strong>", page.split("<section id='certification-by-node'>")[1])
        self.assertIsNone(mb.certification_caveat(m, self.RUN))
        self.assertFalse([c for c in doc["caveats"] if "certified fewer than" in c])

    def test_caveat_names_every_failing_validator(self):
        m = certification_manifest()
        m["cert_failures"].append({"node": "hand-written entry", "logs": []})
        m["cert_failures"].insert(0, {"inst": "val-2", "window": "run", "rate_pct": 80.0,
                                      "windows": ["run", "phase mixed"], "logs": []})
        self.assertEqual(mb.certification_caveat(m, self.RUN),
                         "Validators val-2 and val-3 certified fewer than 90 % of their own headers in phase mixed "
                         "and run; their logs are preserved under results/r20260101-synth/logs/ (see INDEX.md).")
        # Different windows: each validator's own, in window order.
        m["certification_meta"]["fail_below_pct"] = 92.5
        m["cert_failures"].insert(0, {"inst": "val-1", "window": "phase warmup", "rate_pct": 80.0,
                                      "windows": ["phase warmup"], "logs": []})
        self.assertEqual(mb.certification_caveat(m, self.RUN),
                         "Validators val-1 (in phase warmup) and val-2 and val-3 (in phase mixed and run) certified "
                         "fewer than 92.5 % of their own headers; their logs are preserved under "
                         "results/r20260101-synth/logs/ (see INDEX.md).")

    def test_no_certification_recorded(self):
        m = enriched_synthetic_manifest()
        self.assertEqual(mb.certification_html(m), "")
        self.assertIsNone(mb.certification_caveat(m, self.RUN))
        doc, _, page = self.build(m)
        with open(str(PAGE_REPORT), encoding="utf-8") as fh:
            self.assertEqual(page, fh.read(), "nothing added")
        self.assertFalse([c for c in doc["caveats"] if "certified fewer than" in c])

    def test_section_placement_and_rebuild(self):
        section = mb.certification_html(certification_manifest())
        cases = (
            ("<body><section id='consensus'><h2>Consensus health</h2></section><section id='sampler'></section>"
             "<footer>f</footer></body>", "<section id='consensus'><h2>Consensus health</h2></section>" + section
             + "<section id='sampler'>"),
            ("<body><main>x</main><footer>f</footer></body>", "<main>x</main>" + section + "<footer>"),
            ("<html><body><p>x</p></BODY></html>", "<p>x</p>" + section + "</BODY>"),
            ("<p>no body</p>", "<p>no body</p>" + section))
        for text, expect in cases:
            with self.subTest(text=text):
                path = os.path.join(self.tmp, "r.html")
                write_text(path, text)
                self.assertTrue(mb.add_certification_section(path, section))
                self.assertTrue(mb.add_certification_section(path, section), "a rebuild replaces the section")
                with open(path, encoding="utf-8") as fh:
                    got = fh.read()
                self.assertIn(expect, got)
                self.assertEqual(got.count("id='certification-by-node'"), 1)
        self.assertFalse(mb.add_certification_section(path, ""))

    def test_values_are_escaped(self):
        m = certification_manifest()
        m["certification"]["val-<b>"] = m["certification"].pop("val-2")
        m["certification_meta"]["windows"][0] = "arm a<b"
        for node in m["certification"].values():
            node["arm a<b"] = node.pop("phase warmup")
        page = mb.certification_html(m)
        self.assertIn("val-&lt;b&gt;", page)
        self.assertIn("<th class='num'>arm a&lt;b</th>", page)
        self.assertNotIn("<b>", page)

    def test_safe_no_sync_nodes_get_a_caveat(self):
        # benchmark-deploy.sh step 7 records node_startup[<inst>].db_sync_mode; any safe-no-sync node is named.
        m = certification_manifest(failing=False)
        m["node_startup"] = {"val-3": {"db_sync_mode": "safe-no-sync"}, "val-1": {"db_sync_mode": "durable"},
                             "val-2": {"db_sync_mode": "safe-no-sync", "params_bak": "written"}}
        caveat = "MDBX sync mode safe-no-sync on val-2 and val-3: durability relaxed; not comparable with durable runs"
        self.assertEqual(mb.sync_mode_caveat(m), caveat)
        doc, out, _ = self.build(m)
        self.assertIn(caveat + ".", doc["caveats"])
        self.assertEqual(mb.hscrub.scan_dir(out, m), [])
        # Durable (or unrecorded, a bench-4 manifest) everywhere: no caveat.
        m["node_startup"] = {"val-1": {"db_sync_mode": "durable"}, "val-2": {}, "val-3": "not a record"}
        self.assertIsNone(mb.sync_mode_caveat(m))
        doc, _, _ = self.build(m)
        self.assertFalse([c for c in doc["caveats"] if "safe-no-sync" in c])

    def test_main_adds_the_table_before_the_digest(self):
        src = MAKE_BUNDLE_PY.read_text()
        main = src[src.index("def _main(a):"):]
        self.assertLess(main.index("add_certification_section(report_src, cert_section)"),
                        main.index("report = report_block(report_src, archived, backfill)"))
        self.assertLess(main.index("if archived:"), main.index("add_certification_section(report_src, cert_section)"))

    @unittest.skipUnless(SITE_SCRUB.is_file(), "no tn-benchmarks checkout next to this repo")
    def test_site_accepts_the_bundle(self):
        site = load_site_scrub()
        _, out, _ = self.build(certification_manifest())
        self.assertEqual(site.validate_run(load_json(os.path.join(out, "run.json"))), [])
        self.assertEqual([f.format() for f in site.check_bundle(out)], [])


# --------------------------------------------------------------------------- synthetic run end to end


@unittest.skipUnless((TXGEN_BENCH / "aggregate.py").is_file() and SITE_SCRUB.is_file(),
                     "needs tn-transaction-generator and tn-benchmarks checkouts next to this repo")
class SyntheticEndToEndTests(TmpMixin, unittest.TestCase):
    """The synthetic run built by main() with the real tools and the site's scrub.py as the gate: the
    node logs are read in place and nothing under the work dir is a log."""
    RUN = "r20260101-synth"

    def setUp(self):
        super(SyntheticEndToEndTests, self).setUp()
        results = os.path.join(self.results_root, self.RUN)
        shutil.copytree(str(SYNTH), results)
        write_json(os.path.join(results, "manifest.json"), enriched_synthetic_manifest())
        self.logs = os.path.join(results, "logs")
        # One start per node the manifest lists (val-1..3, obs-1; the load-* blasters run no node).
        write_text(os.path.join(self.logs, "val-1-telcoin.log"), node_log(SHA, vote_timeout=5000))
        with gzip.open(os.path.join(self.logs, "val-2-telcoin.log.gz"), "wt") as fh:
            fh.write(node_log(SHA, vote_timeout=5000))
        with gzip.open(os.path.join(self.logs, "val-3-unit-stdout.rotated-1.log.gz"), "wt") as fh:
            fh.write(node_log(SHA, vote_timeout=5000))
        write_text(os.path.join(self.logs, "obs-1-telcoin.log"), node_log(SHA, vote_timeout=5000))
        self.site = os.path.join(self.tmp, "site")
        os.makedirs(self.site)
        shutil.copyfile(str(SITE_SCRUB), os.path.join(self.site, "scrub.py"))
        self.out = os.path.join(self.tmp, "out", self.RUN)
        self.backfill = os.path.join(self.tmp, "bf.json")
        write_json(self.backfill, {"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA}})

    def test_bundle_without_copying_the_logs(self):
        before = {n: sha256(os.path.join(self.logs, n)) for n in os.listdir(self.logs)}
        rc, out, err = self.main("--run", self.RUN, "--backfill", self.backfill, "--out", self.out,
                                 "--txgen-bench", TXGEN_BENCH, "--analysis-sha", "abcdef0", BENCH_SITE_REPO=self.site)
        self.assertEqual(rc, 0, err[-3000:])
        self.assertIn("2 provenance: 4 log files, 4 starts", out)
        self.assertIn("gates: site scrub.py: scrub: 0 error(s)", out)
        scratch = os.path.join(self.work_root, self.RUN)
        self.assertFalse(os.path.lexists(os.path.join(scratch, "logs")))
        self.assertEqual([p for p in tree(self.work_root) if ".log" in os.path.basename(p)], [])
        self.assertEqual({n: sha256(os.path.join(self.logs, n)) for n in os.listdir(self.logs)}, before)
        with open(os.path.join(self.out, "run.json"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn(self.tmp, text)
        doc = json.loads(text)
        self.assertEqual(doc["upstream"], {
            "repo": mb.UPSTREAM_REPO, "sha": SHA, "short": SHA[:9], "branch": None, "evidence": "verified",
            "evidence_detail": ["4 node starts across 4 instances logged telcoin-network 0.1.0 (%s)" % SHA]})
        self.assertEqual(doc["consensus"], {
            "max_header_delay_ms": 3000, "min_header_delay_ms": 1000, "max_batch_delay_ms": 1000,
            "vote_timeout_ms": 5000, "file": mb.LOGS_PARAMS_FILE, "confirmed_by": mb.LOGS_CONFIRMED_BY})
        # The KPIs from the fixture's metrics and sampler (aggregate.py computes the others).
        kpis = dict((k["id"], k.get("value", k.get("range"))) for k in doc["kpis"])
        self.assertEqual({k: kpis.get(k) for k in (
            "commit_latency_p95_s", "execution_time_per_output_s", "disk_write_p95_mibps_busiest",
            "disk_write_iops_p95_busiest", "cpu_p95_pct_busiest", "rss_p95_gib_busiest", "psi_io_max_pct")}, {
            "commit_latency_p95_s": [2.0, 2.5], "execution_time_per_output_s": [0.11, 0.22],
            "disk_write_p95_mibps_busiest": 24.0, "disk_write_iops_p95_busiest": 1200, "cpu_p95_pct_busiest": 60.0,
            "rss_p95_gib_busiest": 3.0, "psi_io_max_pct": [7.3, 12.5]})

    def test_a_node_without_a_start_line_is_refused_unless_allowed(self):
        # D20: obs-1's log lost its boot (rotated away before the pull). The logged starts all match, but
        # they do not vouch for obs-1, so the bundle refuses; allowed, it says so in a caveat.
        os.unlink(os.path.join(self.logs, "obs-1-telcoin.log"))
        argv = ["--run", self.RUN, "--backfill", self.backfill, "--out", self.out, "--txgen-bench", TXGEN_BENCH,
                "--analysis-sha", "abcdef0"]
        rc, out, err = self.main(*argv, BENCH_SITE_REPO=self.site)
        self.assertEqual(rc, 1, out[-2000:])
        self.assertIn("provenance check failed", err)
        self.assertIn("no start line for obs-1", err)
        self.assertFalse(os.path.lexists(self.out))
        rc, out, err = self.main(*(argv + ["--force", "--allow-provenance-mismatch"]), BENCH_SITE_REPO=self.site)
        self.assertEqual(rc, 0, err[-3000:])
        doc = load_json(os.path.join(self.out, "run.json"))
        self.assertEqual((doc["upstream"]["evidence"], doc["upstream"]["sha"]), ("inferred", SHA))
        self.assertIn("The node logs did not confirm the upstream commit: no start line for obs-1.", doc["caveats"])


# --------------------------------------------------------------------------- page-only end to end


class PageOnlyStubGateTests(TmpMixin, unittest.TestCase):
    """--no-results --archived-report into a temp out dir, gate = a stub scrub.py (runs in CI)."""
    RUN = "r20260102-page"

    def setUp(self):
        super(PageOnlyStubGateTests, self).setUp()
        if not outside_git(self.tmp):
            self.skipTest("the temp dir lies inside a git checkout")
        self.site = os.path.join(self.tmp, "site")
        self.out = os.path.join(self.tmp, "out", self.RUN)

    def stub(self, rc):
        write_text(os.path.join(self.site, "scrub.py"), STUB_GATE % rc)

    def page(self, *extra, **kw):
        backfill = kw.get("backfill", PAGE_BACKFILL)
        return self.main("--run", self.RUN, "--no-results", "--archived-report", PAGE_REPORT, "--backfill", backfill,
                         "--out", self.out, *extra, BENCH_SITE_REPO=self.site)

    def test_page_only_bundle(self):
        self.stub(0)
        rc, out, err = self.page()
        self.assertEqual(rc, 0, err)
        self.assertIn("make_bundle: OK %s" % self.RUN, out)
        self.assertIn("gates: harness scan_dir: clean", out)
        self.assertEqual(load_json(os.path.join(self.site, "argv.json")), [self.out])
        self.assertEqual(tree(self.out), ["report.html", "run.json"])
        self.assertEqual(sha256(os.path.join(self.out, "report.html")), sha256(PAGE_REPORT))
        with open(os.path.join(self.out, "run.json")) as fh:
            text = fh.read()
        doc = json.loads(text)
        self.assertEqual(text, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        bf = load_json(PAGE_BACKFILL)
        self.assertEqual(sorted(doc), RUN_KEYS)
        self.assertEqual((doc["schema"], doc["id"], doc["status"], doc["date"], doc["title"], doc["summary"]),
                         (mb.SCHEMA_ID, self.RUN, "superseded", "2026-01-02", bf["title"], bf["summary"]))
        self.assertEqual(doc["upstream"], {"repo": mb.UPSTREAM_REPO, "sha": SHA, "short": SHA[:9], "branch": "main",
                                           "evidence": "inferred",
                                           "evidence_detail": ["Synthetic: the image tag was built from this commit."]})
        self.assertEqual(doc["report"], {"file": "report.html", "sha256": sha256(PAGE_REPORT),
                                         "bytes": os.path.getsize(str(PAGE_REPORT)),
                                         "archived_from": "synthetic archived page",
                                         "modifications": ["Synthetic modification."]})
        self.assertEqual(doc["kpis"], bf["kpis_published"])
        self.assertEqual(doc["headline"], "tps_published")
        for key in ("windows", "series", "consensus", "workload", "recovery", "compare_to"):
            self.assertIsNone(doc[key], key)
        self.assertEqual(doc["chaos"], [])
        self.assertEqual(doc["fleet"]["disk"], {"type": "pd-ssd", "size_gb": 100, "iops": None, "throughput_mibps": None})
        self.assertEqual(doc["generator"], {"sha": None, "image_digest": None, "analysis_sha": None})
        self.assertEqual((doc["caveats"], doc["methodology"]), (bf["caveats"], bf["methodology"]))
        # A second run into the same out dir is byte-identical.
        rc, _, err = self.page("--analysis-sha", "abcdef0", "--compare", "r20260101-0000")
        self.assertEqual(rc, 0, err)
        doc2 = load_json(os.path.join(self.out, "run.json"))
        self.assertEqual((doc2["generator"]["analysis_sha"], doc2["compare_to"]), ("abcdef0", "r20260101-0000"))
        doc2["generator"]["analysis_sha"], doc2["compare_to"] = None, None
        self.assertEqual(doc2, doc)

    def test_no_results_backfill_requirements(self):
        self.stub(0)
        bf = load_json(PAGE_BACKFILL)
        for mutate, msg in ((lambda d: d.pop("date"), "must give date"),
                            (lambda d: d["fleet"].pop("regions"), "backfill fleet needs"),
                            (lambda d: d["fleet"]["disk"].pop("size_gb"), "backfill fleet needs"),
                            (lambda d: d["chain"].pop("network"), "chain needs chain_id and network"),
                            (lambda d: d["upstream"].update(evidence="verified"), "cannot be 'verified'")):
            doc = copy.deepcopy(bf)
            mutate(doc)
            path = os.path.join(self.tmp, "bf.json")
            write_json(path, doc)
            rc, _, err = self.page(backfill=path)
            self.assertEqual(rc, 1, msg)
            self.assertIn(msg, err)
            self.assertFalse(os.path.exists(self.out), msg)

    def test_gate_failures_keep_the_bundle(self):
        self.stub(1)
        rc, _, err = self.page()
        self.assertEqual(rc, 1)
        self.assertIn("site gate (scrub.py) failed", err)
        self.assertEqual(tree(self.out), [])  # staged write: a failed gate installs nothing
        os.remove(os.path.join(self.site, "scrub.py"))
        rc, _, err = self.page()
        self.assertEqual(rc, 1)
        self.assertIn("site gate unavailable", err)

    def test_harness_scan_blocks_a_leak_before_the_site_gate(self):
        self.stub(0)
        doc = load_json(PAGE_BACKFILL)
        leak = ip(10, 168, 0, 21)
        doc["caveats"] = ["leak test %s here" % leak]
        path = os.path.join(self.tmp, "bf-leak.json")
        write_json(path, doc)
        rc, _, err = self.page(backfill=path)
        self.assertEqual(rc, 1)
        self.assertIn("harness leak scan found 1 issue(s)", err)
        self.assertIn("run.json:", err)
        self.assertNotIn(leak, err)
        self.assertFalse(os.path.exists(os.path.join(self.site, "argv.json")), "the site gate must not run")
        self.assertFalse(os.path.exists(os.path.join(self.out, "run.json")), "a failed gate installs nothing")


@unittest.skipUnless(SITE_SCRUB.is_file() and SITE_BUILD.is_file(), "no tn-benchmarks checkout next to this repo")
class PageOnlyRealSiteTests(TmpMixin, unittest.TestCase):
    """The same path against a temp copy of the real site scrub.py / build.py."""
    RUN = "r20260102-page"

    def setUp(self):
        super(PageOnlyRealSiteTests, self).setUp()
        self.site = os.path.join(self.tmp, "site")
        os.makedirs(self.site)
        for f in (SITE_SCRUB, SITE_BUILD):
            shutil.copyfile(str(f), os.path.join(self.site, f.name))

    def page(self, out=None, backfill=PAGE_BACKFILL):
        argv = ["--run", self.RUN, "--no-results", "--archived-report", PAGE_REPORT, "--backfill", backfill]
        if out:
            argv += ["--out", out]
        return self.main(*argv, BENCH_SITE_REPO=self.site)

    def test_outside_a_checkout_uses_site_scrub(self):
        if not outside_git(self.tmp):
            self.skipTest("the temp dir lies inside a git checkout")
        out = os.path.join(self.tmp, "out", self.RUN)
        rc, stdout, err = self.page(out)
        self.assertEqual(rc, 0, err)
        self.assertIn("gates: site scrub.py: scrub: 0 error(s)", stdout)
        doc = load_json(PAGE_BACKFILL)
        doc["caveats"] = ["see https://" + "grafana.example.com/d/abc for details"]
        path = os.path.join(self.tmp, "bf-link.json")
        write_json(path, doc)
        rc, _, err = self.page(out, backfill=path)
        self.assertEqual(rc, 1)
        self.assertIn("site gate (scrub.py) failed", err)

    @unittest.skipUnless(HAS_GIT, "git is not installed")
    def test_inside_the_site_checkout_uses_build_check(self):
        subprocess.run(["git", "init", "-q", self.site], check=True)
        subprocess.run(["git", "-C", self.site, "remote", "add", "origin", SITE_ORIGIN], check=True)
        rc, stdout, err = self.page()
        self.assertEqual(rc, 0, err)
        self.assertIn("build.py --check runs/%s: check: ok" % self.RUN, stdout)
        self.assertEqual(tree(os.path.join(self.site, "runs")),
                         [self.RUN + "/report.html", self.RUN + "/run.json"])


# --------------------------------------------------------------------------- full integration (local only)


@unittest.skipUnless(RESULTS_29.is_dir() and (TXGEN_BENCH / "build-report.py").is_file()
                     and (TXGEN_BENCH / "aggregate.py").is_file() and (TXGEN_BENCH / "derive-sizing.py").is_file()
                     and SITE_SCRUB.is_file(),
                     "needs benchmark/results/r20260929-1647, ../tn-transaction-generator/bench and ../tn-benchmarks")
class Run20260929IntegrationTests(unittest.TestCase):
    """SLOW (~15 s): the 29 Sep blast-0 bundle built end to end into a temp out dir."""
    RUN = "r20260929-1647"

    def test_slow_blast0_bundle(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="tb2-r0929-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        real_scratch = os.path.join(mb.WORK_ROOT, self.RUN)
        existed = os.path.lexists(real_scratch)
        work = os.path.join(tmp, "work", "report")
        site = os.path.join(tmp, "site")
        os.makedirs(site)
        shutil.copyfile(str(SITE_SCRUB), os.path.join(site, "scrub.py"))
        out = os.path.join(tmp, "out", self.RUN)
        backfill = os.path.join(tmp, "bf.json")
        write_json(backfill, {
            "title": "Ten validators on Hyperdisk, blast 0", "summary": "Integration test bundle.",
            "upstream": {"sha": "e85bd7a3f07f510c548cac9d783fb907fdf7fcca", "branch": None},
            "consensus": {"vote_timeout_ms": 5000},
            "kpis_published": [{"id": "failed_reports_published", "label": "Failed reports (published)",
                                "short_label": "Failed reports", "value": 1207, "unit": "reports", "window": None,
                                "source": "published report", "method": None, "provenance": "published"}]})
        argv = ["--run", self.RUN, "--blast-index", "0", "--backfill", backfill, "--out", out,
                "--txgen-bench", str(TXGEN_BENCH), "--analysis-sha", "abcdef0"]
        with mock.patch.object(mb, "WORK_ROOT", work), mock.patch.dict(os.environ, {"BENCH_SITE_REPO": site}):
            rc, stdout, err = quiet(mb.main, argv)
        self.assertEqual(rc, 0, err[-3000:])
        self.assertEqual(os.path.lexists(real_scratch), existed, "the real work/report dir must not be touched")
        self.assertTrue(os.path.isfile(os.path.join(work, self.RUN, "scrubbed", "report.html")))
        self.assertFalse(os.path.lexists(os.path.join(work, self.RUN, "logs")), "node logs are read in place")
        self.assertIn("gates: harness scan_dir: clean", stdout)
        self.assertIn("gates: site scrub.py: scrub: 0 error(s)", stdout)
        self.assertEqual(tree(out), ["report.html", "run.json", "series/tps-1s.json"])
        doc = load_json(os.path.join(out, "run.json"))
        head = next(k for k in doc["kpis"] if k["id"] == doc["headline"])
        self.assertEqual(head["value"], 4177.2)
        self.assertEqual([k["provenance"] for k in doc["kpis"]].count("computed"), 16)  # 13 + corrected + time_to_seen p50/p95
        self.assertEqual([k["provenance"] for k in doc["kpis"]].count("published"), 1)
        self.assertEqual(doc["upstream"]["short"], "e85bd7a3f")
        # The run's node logs may have moved to the archive bucket, leaving only the .pulled markers here.
        # With them, provenance_step checks every listed node's start line (a gap would refuse the bundle:
        # this test passes no --allow-provenance-mismatch) and the delays come from the logs. Without them
        # nothing is checked: the backfill's sha is published as inferred, with no provenance caveat, and
        # this manifest predates consensus_parameters, so no consensus block is published.
        if mb.provenance.node_log_files(str(RESULTS_29)):
            self.assertEqual(doc["upstream"]["evidence"], "verified")
            self.assertEqual(doc["consensus"]["vote_timeout_ms"], 5000)
        else:
            self.assertEqual(doc["upstream"]["evidence"], "inferred")
            self.assertEqual([c for c in doc["caveats"] if "did not confirm the upstream commit" in c], [])
            self.assertIsNone(doc["consensus"])
            self.assertIn("Consensus parameters are not published for this run: max_header_delay_ms, "
                          "min_header_delay_ms, max_batch_delay_ms not recorded.", doc["caveats"])
        self.assertEqual(doc["fleet"]["validators"], 10)
        series = load_json(os.path.join(out, "series", "tps-1s.json"))
        secs = doc["windows"]["merged_mixed"]["secs"]
        self.assertLessEqual(len(series["rows"]), mb.MAX_1S_ROWS)
        self.assertEqual(series["step_s"], int(math.ceil(secs / 2000.0)))
        raw_manifest = os.path.join(work, self.RUN, "manifest.json")
        self.assertEqual(mb.hscrub.scan_dir(out, raw_manifest), [])
        self.assertEqual(doc["report"]["sha256"], sha256(os.path.join(out, "report.html")))



# ---- bench6 switch provenance and the prestart arm ----

SWITCHES_OFF = {"quorum_exec_block": "false", "quorum_exec_block_starved_rounds": "0", "vote_queue_fix": "false",
                "mdbx_random_advice": "false", "sealed_tx_keep": "false", "digest_dedupe": "false",
                "recovery_threads": "0", "epoch_close_task_drain": "false", "epoch_record_state_check": "false",
                "parent_grace": "0ms", "rpc_admission_backlog_outputs": "0", "pipelined_persist": "false"}
SWITCHES_FINAL = dict(SWITCHES_OFF, vote_queue_fix="true", mdbx_random_advice="true", recovery_threads="3",
                      parent_grace="150ms")


def final_arm(**extra):
    """The arm deploy step 7 applies before the first start (BENCH_ARM_FILE=benchmark/arms/final.arm)."""
    a = {"name": "final", "begin": "2026-01-01T00:00:30Z", "end": None, "via": "prestart",
         "file": "benchmark/arms/final.arm", "sha256": "0" * 64, "switches": dict(SWITCHES_FINAL)}
    a.update(extra)
    return a


def switch_line(switches):
    return ('2026-01-01T00:00:01Z INFO node::switches: node switches %s\n'
            % " ".join("%s=%s" % kv for kv in switches.items()))


class SwitchProvenanceStepTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="tb2-sw-")
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def logs(self, sha, v2_switches=SWITCHES_FINAL):
        write_text(os.path.join(self.scratch, "logs", "val-1-telcoin.log"), node_log(sha) + switch_line(SWITCHES_FINAL))
        write_text(os.path.join(self.scratch, "logs", "val-2-telcoin.log"), node_log(sha) + switch_line(v2_switches))

    def step(self, manifest, backfill, allow=False):
        return quiet(mb.provenance_step, self.scratch, manifest, backfill, allow)

    def test_matching_switches_are_a_detail_line(self):
        self.logs(SHA)
        p, out, err = self.step({"node_git_sha": SHA, "param_arms": [final_arm()]}, {})
        up = p["upstream"]
        self.assertEqual((up["evidence"], up["sha"], p["caveats"]), ("verified", SHA, []))
        self.assertIn("Each of the 2 node starts logged its node switches line, and each matched the switch state "
                      "the manifest records for that start", up["evidence_detail"])
        self.assertIn("node switches: 2 start(s) checked, 2 matched the arm in force, 0 without a line -> ok", out)
        self.assertEqual(err, "")

    def test_a_mismatch_refuses_unless_allowed_and_keeps_the_commit_verified(self):
        self.logs(SHA, v2_switches=dict(SWITCHES_FINAL, recovery_threads="0"))
        m = {"node_git_sha": SHA, "param_arms": [final_arm()]}
        with self.assertRaisesRegex(mb.BundleError, "node switch check failed .*\n  - node switches show "
                                                    "recovery_threads=0 at 1 start"):
            self.step(m, {})
        p, out, err = self.step(m, {}, allow=True)
        up = p["upstream"]
        self.assertEqual((up["evidence"], up["sha"]), ("verified", SHA))
        self.assertEqual(p["caveats"], [
            "The node switch lines did not match the switch state the manifest records: node switches show "
            "recovery_threads=0 at 1 start(s) (val-2 at 2026-01-01T00:00:00Z); arm final sets recovery_threads=3"])
        self.assertIn("Node switch lines: 1 of 2 start(s) matched the switch state the manifest records, and 0 "
                      "start(s) logged none; see the caveats", up["evidence_detail"])
        self.assertIn("-> 1 problem(s)", out)
        self.assertIn("warning: --allow-provenance-mismatch: the node switch lines do not match", err)

    def test_a_missing_line_the_contract_requires_refuses(self):
        write_text(os.path.join(self.scratch, "logs", "val-1-telcoin.log"), node_log(SHA))
        m = {"node_git_sha": SHA, "node_probe": {"strings": {"node switches": 1}}}
        with self.assertRaisesRegex(mb.BundleError, "no node switches line at 1 start"):
            self.step(m, {})
        # The same logs without the contract: the build checks out and no switch line is judged.
        p, out, _ = self.step({"node_git_sha": SHA}, {})
        self.assertEqual(p["upstream"]["evidence"], "verified")
        self.assertNotIn("node switches", out)
        self.assertFalse(any("switches" in d for d in p["upstream"]["evidence_detail"]))

    def test_build_and_switch_mismatches_are_separate_caveats(self):
        self.logs(SHA, v2_switches=dict(SWITCHES_FINAL, recovery_threads="0"))
        m = {"param_arms": [final_arm()]}
        with self.assertRaisesRegex(mb.BundleError, "provenance check failed"):
            self.step(m, {"upstream": {"sha": OTHER_SHA}})
        p, _, _ = self.step(m, {"upstream": {"sha": OTHER_SHA}}, allow=True)
        self.assertEqual(p["upstream"]["evidence"], "inferred")
        self.assertEqual(len(p["caveats"]), 2)
        self.assertTrue(p["caveats"][0].startswith("The node logs did not confirm the upstream commit: "))
        self.assertNotIn("switches", p["caveats"][0])
        self.assertTrue(p["caveats"][1].startswith("The node switch lines did not match"))


class PrestartArmTests(unittest.TestCase):
    """An arm deploy step 7 applied before the first start (via "prestart") is published as a
    consensus.param_arms row of its switches (the headline's switch configuration)."""

    def manifest(self, *arms, nodes=11):
        insts = [{"name": "bench-validator-%02d" % i, "role": "validator"} for i in range(1, nodes)]
        insts.append({"name": "bench-observer-%02d" % nodes, "role": "observer"})
        return {"consensus_parameters": dict(ConsensusPerNodeTests.FLEET), "instances": insts, "param_arms": list(arms)}

    def consensus(self, manifest):
        caveats = []
        block = mb.consensus_block(manifest, {"params": dict(ConsensusPerNodeTests.LOGS), "param_values": {}}, {},
                                   caveats)
        return block, caveats

    def test_row_states_the_switches_away_from_their_default(self):
        block, caveats = self.consensus(self.manifest(final_arm()))
        self.assertEqual(block["param_arms"], [
            {"arm": "final", "begin_utc": "2026-01-01T00:00:30Z", "end_utc": None,
             "values": "all 11 nodes: mdbx_random_advice=true, parent_grace=150ms, recovery_threads=3, "
                       "vote_queue_fix=true"}])
        self.assertEqual(caveats, [])
        self.assertEqual(mb.headline_switches(self.manifest(final_arm())),
                         ("final", "all 11 nodes: mdbx_random_advice=true, parent_grace=150ms, recovery_threads=3, "
                                   "vote_queue_fix=true"))
        # A later params-apply arm keeps its written values as before.
        later = {"name": "p2", "begin": "2026-01-01T02:00:00Z", "end": None, "switches": dict(SWITCHES_OFF),
                 "nodes": {"bench-validator-01": {"mdbx_random_advice": "false"}}}
        block, _ = self.consensus(self.manifest(final_arm(end="2026-01-01T02:00:00Z"), later))
        self.assertEqual([r["values"] for r in block["param_arms"]][1], "bench-validator-01: mdbx_random_advice=false")

    def test_all_defaults_has_no_row_and_bad_values_refuse(self):
        block, _ = self.consensus(self.manifest(final_arm(switches=dict(SWITCHES_OFF, parent_grace="0s"))))
        self.assertNotIn("param_arms", block)
        self.assertIsNone(mb.headline_switches(self.manifest(final_arm(switches=dict(SWITCHES_OFF)))))
        for bad in ({"parent_grace": "/" + "tmp/x"}, {"recovery_threads": 3}, {"vote_queue_fix": "yes please"}):
            with self.assertRaises(mb.BundleError, msg=bad):
                self.consensus(self.manifest(final_arm(switches=dict(SWITCHES_FINAL, **bad))))
        with self.assertRaisesRegex(mb.BundleError, "lists no node"):
            self.consensus({"param_arms": [final_arm()]})
        # Its nodes are not read: deploy step 7 records what it likes there.
        block, _ = self.consensus(self.manifest(final_arm(nodes=["not", "a", "map"])))
        self.assertEqual(len(block["param_arms"]), 1)


class PrestartArmAssemblyTests(unittest.TestCase):
    """Steps 4-8 on the synthetic run with a prestart arm (OfflineAssemblyTests' build, not its tests)."""

    setUp = OfflineAssemblyTests.setUp
    build = OfflineAssemblyTests.build
    BACKFILL = {"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA},
                "consensus": {"max_header_delay_ms": 500, "min_header_delay_ms": 250, "max_batch_delay_ms": 250,
                              "vote_timeout_ms": 5000, "file": "consensus-parameters.yaml",
                              "confirmed_by": "harness manifest"}}

    def test_run_json_carries_the_switches_in_consensus(self):
        _, doc, out, _ = self.build(self.BACKFILL, manifest_update={"param_arms": [final_arm()]})
        self.assertEqual(doc["consensus"]["param_arms"], [
            {"arm": "final", "begin_utc": "2026-01-01T00:00:30Z", "end_utc": None,
             "values": "all 4 nodes: mdbx_random_advice=true, parent_grace=150ms, recovery_threads=3, "
                       "vote_queue_fix=true"}])
        self.assertFalse(any("switches of arm" in c for c in doc["caveats"]))
        if SITE_SCRUB.is_file():
            site = load_site_scrub()
            self.assertEqual(site.validate_run(load_json(os.path.join(out, "run.json"))), [])
            self.assertEqual([f.format() for f in site.check_bundle(out)], [])

    def test_without_a_consensus_block_a_caveat_states_them(self):
        bf = {k: v for k, v in self.BACKFILL.items() if k != "consensus"}
        _, doc, _, _ = self.build(bf, manifest_update={"param_arms": [final_arm()]})
        self.assertIsNone(doc["consensus"])
        self.assertIn("The nodes ran the switches of arm final from their first start (all 4 nodes: "
                      "mdbx_random_advice=true, parent_grace=150ms, recovery_threads=3, vote_queue_fix=true); the "
                      "consensus block is not published for this run, so they are stated here.", doc["caveats"])



GEN_FIELDS = load_json(FIX / "generator-fields" / "additions.json")


@unittest.skipUnless((TXGEN_BENCH / "aggregate.py").is_file() and SITE_SCRUB.is_file(),
                     "needs the tn-transaction-generator and tn-benchmarks checkouts next to this repo")
class GeneratorFieldsEndToEndTests(TmpMixin, unittest.TestCase):
    """The synthetic run built by main() twice, the second time with the generator's bench-6 additions
    (fixtures/report/generator-fields) in every blaster and a landings export whose rows carry `late`: the
    tools' aggregate.py takes them in, and every KPI, window and series comes out as before."""

    def make_run(self, run, extra):
        results = os.path.join(self.results_root, run)
        shutil.copytree(str(SYNTH), results)
        write_json(os.path.join(results, "manifest.json"), enriched_synthetic_manifest())
        for name in ("val-1", "val-2", "val-3", "obs-1"):
            write_text(os.path.join(results, "logs", "%s-telcoin.log" % name), node_log(SHA, vote_timeout=5000))
        if extra:
            add = copy.deepcopy(GEN_FIELDS["blaster"])
            node_resends = add.pop("node_resends")
            for path in sorted(Path(results, "blasters").glob("*.json")):
                doc = load_json(path)
                doc["run"].update(add["run"])
                for k in ("series", "senders", "totals"):
                    doc.setdefault(k, {}).update(add[k])
                doc["nodes"] = [{"label": "val-1", "resends": dict(node_resends)}]
                write_json(path, doc)
            with gzip.open(os.path.join(results, "blasters", "landings-load-a.ndjson.gz"), "wt") as fh:
                fh.write(json.dumps(GEN_FIELDS["landings_row"]) + "\n")
        out = os.path.join(self.tmp, "out", run)
        rc, stdout, err = self.main("--run", run, "--backfill", self.backfill, "--out", out, "--txgen-bench",
                                    TXGEN_BENCH, "--analysis-sha", "abcdef0", BENCH_SITE_REPO=self.site)
        self.assertEqual(rc, 0, err[-3000:])
        return load_json(os.path.join(out, "run.json")), load_json(os.path.join(out, "series", "tps-1s.json"))

    def setUp(self):
        super(GeneratorFieldsEndToEndTests, self).setUp()
        self.site = os.path.join(self.tmp, "site")
        os.makedirs(self.site)
        shutil.copyfile(str(SITE_SCRUB), os.path.join(self.site, "scrub.py"))
        self.backfill = os.path.join(self.tmp, "bf.json")
        write_json(self.backfill, {"title": "Synthetic", "summary": "Synthetic run.", "upstream": {"sha": SHA}})

    def test_new_generator_fields_change_no_kpi(self):
        plain, plain_series = self.make_run("r20260101-synth", False)
        extra, extra_series = self.make_run("r20260101-gen6", True)
        for key in ("kpis", "headline", "windows", "series", "recovery", "workload", "consensus", "chaos"):
            self.assertEqual(json.dumps(extra[key]), json.dumps(plain[key]), key)
        self.assertEqual(extra_series, plain_series)
        self.assertEqual(extra["caveats"], plain["caveats"])
        marker = mb.read_marker(os.path.join(self.work_root, "r20260101-gen6"))
        self.assertEqual([e["path"] for e in marker["landings"]], ["r20260101-gen6/blasters/landings-load-a.ndjson.gz"])


if __name__ == "__main__":
    unittest.main()
