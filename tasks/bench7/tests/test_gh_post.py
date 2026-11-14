"""Shim tests for tasks/bench7/orch-gh-post.sh, the script that posts issues, comments and PRs.

Every test runs the real script against a sandbox copy of fixtures/gh-post/root (POST_ROOT) with a
fake gh first on PATH (fixtures/gh-post/fake_gh.py). Unarmed, the fake prints REACHED and exits 9,
so a dry run that reaches gh fails; armed, it prints a URL or fails. No test can reach the real gh.
Run from the repository root:  python3 -m unittest tasks/bench7/tests/test_gh_post.py -v
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "orch-gh-post.sh"
FIX = HERE / "fixtures" / "gh-post"
REPO = "Telcoin-Association/telcoin-network"
ALPHA_TITLE = "A node stopped between two writes can never start again"
PR1_TITLE = "feat(node): the first topic of the stack"
# Expansions for the lint-rules fixture, written in pieces so no file here carries them whole.
TOKENS = {
    "@HOME@": "/" + "home" + "/",
    "@HOST@": "xer" + "xes",
    "@PROJECT@": "tn-" + "devnet",
    "@IP@": ".".join(["10", "11", "12", "13"]),
}


def lint_rule_rows():
    rows = []
    for line in (FIX / "lint-rules.tsv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        rule, text = line.split("\t", 1)
        for token, value in TOKENS.items():
            text = text.replace(token, value)
        rows.append((rule, text))
    return rows


class GhPostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gh-post-test-"))
        self.root = self.tmp / "root"
        shutil.copytree(str(FIX / "root"), str(self.root))
        (self.root / "tasks" / "bench7").mkdir(parents=True, exist_ok=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        shutil.copyfile(str(FIX / "fake_gh.py"), str(gh))
        gh.chmod(0o755)
        self.ghlog = self.tmp / "gh.log"
        self.tmpdir = self.tmp / "t"
        self.tmpdir.mkdir()
        self.bodycopy = self.tmp / "posted-body.md"
        self.record = self.root / "tasks" / "bench7" / "gh-posted.tsv"

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    # ---- helpers ----
    def run_script(self, *args, mode=None, **extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("FAKE_GH_") and k not in ("GH_REPO", "POST_ROOT")}
        env.update({
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "POST_ROOT": str(self.root),
            "TMPDIR": str(self.tmpdir),
            "FAKE_GH_LOG": str(self.ghlog),
            "FAKE_GH_BODY_COPY": str(self.bodycopy),
        })
        if mode:
            env["FAKE_GH_MODE"] = mode
        env.update(extra)
        p = subprocess.run(["bash", str(SCRIPT)] + list(args), env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120)
        p.both = p.stdout + p.stderr
        return p

    def gh_calls(self):
        if not self.ghlog.exists():
            return []
        return [json.loads(x) for x in self.ghlog.read_text(encoding="utf-8").splitlines() if x]

    def record_rows(self):
        if not self.record.exists():
            return []
        return [x.split("\t") for x in self.record.read_text(encoding="utf-8").splitlines()
                if x and not x.startswith("#")]

    def seed_record(self, kind, key, number):
        with self.record.open("a", encoding="utf-8") as fh:
            fh.write("2026-11-14T00:00:00Z\t%s\t%s\t%s\thttps://github.com/x/y/issues/%s\t%s\n"
                     % (kind, key, number, number, "0" * 64))

    def write_body(self, rel, text):
        p = self.root / "tasks" / rel
        p.write_text(text, encoding="utf-8")
        return p

    def assert_rc(self, p, rc):
        self.assertEqual(p.returncode, rc, "rc=%s\n%s" % (p.returncode, p.both))

    def assert_no_gh(self, p):
        self.assertEqual(self.gh_calls(), [], p.both)
        self.assertNotIn("REACHED", p.both)

    # ---- dry runs ----
    def test_dry_issue_runs_no_gh_and_prints_the_argv(self):
        p = self.run_script("issue", "alpha")
        self.assert_rc(p, 0)
        self.assert_no_gh(p)
        self.assertIn("DRY issue alpha\n", p.stdout)
        self.assertRegex(p.stdout, r"create: gh issue create --repo %s --title '%s' --body-file \S+ --assignee grantkee\n"
                         % (re.escape(REPO), re.escape(ALPHA_TITLE)))
        self.assertIn("precheck: gh issue list --repo %s --search '%s in:title' --state all --json number,title"
                      % (REPO, ALPHA_TITLE), p.stdout)
        self.assertIn("title: %s (55 characters)" % ALPHA_TITLE, p.stdout)
        self.assertRegex(p.stdout, r"\(\d+ words, \d+ characters posted\)")
        self.assertIn("    | ## Problem", p.stdout)
        self.assertIn("DRY issue alpha ok: nothing posted", p.stdout)
        self.assertFalse(self.record.exists())

    def test_dry_comment_runs_no_gh_and_prints_the_argv(self):
        p = self.run_script("comment", "1802")
        self.assert_rc(p, 0)
        self.assert_no_gh(p)
        self.assertRegex(p.stdout, r"create: gh issue comment 1802 --repo %s --body-file \S+\n" % re.escape(REPO))
        self.assertIn("precheck: none", p.stdout)

    def test_dry_pr_runs_no_gh_and_prints_the_argv(self):
        p = self.run_script("pr", "01")
        self.assert_rc(p, 0)
        self.assert_no_gh(p)
        self.assertRegex(p.stdout, r"create: gh pr create --repo %s --base staging/benchmark-bench6-2026-11 "
                         r"--head b7/first-topic --title '%s' --body-file \S+ --assignee grantkee "
                         r"--reviewer MavenRain --reviewer sstanfield\n" % (re.escape(REPO), re.escape(PR1_TITLE)))
        self.assertIn("precheck: gh pr list --repo %s --head b7/first-topic --base staging/benchmark-bench6-2026-11"
                      % REPO, p.stdout)

    def test_repo_comes_from_the_environment(self):
        p = self.run_script("comment", "1802", GH_REPO="example/sandbox")
        self.assert_rc(p, 0)
        self.assertIn("gh issue comment 1802 --repo example/sandbox", p.stdout)

    # ---- the lint ----
    def test_each_lint_rule_refuses(self):
        rows = lint_rule_rows()
        self.assertGreaterEqual(len({r for r, _ in rows}), 19)
        for rule, text in rows:
            with self.subTest(rule=rule, text=text):
                body = self.write_body("issue-comments/lint-probe.md", "## Problem\n\n%s\n" % text)
                p = self.run_script("lint", str(body))
                self.assert_rc(p, 3)
                hits = set(re.findall(r"^LINT \S+:(\d+): ([a-z0-9-]+):", p.stdout, re.M))
                self.assertEqual(hits, {("3", rule)}, p.stdout)
        self.assert_no_gh(p)

    def test_clean_fixture_body_passes(self):
        p = self.run_script("lint", str(FIX / "clean-body.md"))
        self.assert_rc(p, 0)
        self.assertIn("LINT-OK", p.stdout)

    def test_allow_marker_is_not_honoured_outside_the_fixtures(self):
        body = self.write_body("issue-comments/copy.md", (FIX / "clean-body.md").read_text(encoding="utf-8"))
        p = self.run_script("lint", str(body))
        self.assert_rc(p, 3)
        hits = set(re.findall(r"^LINT \S+:(\d+): ([a-z0-9-]+):", p.stdout, re.M))
        self.assertEqual(hits, {("7", "unit-name"), ("7", "allow-marker")}, p.stdout)

    def test_a_lint_hit_refuses_a_dry_post_with_exit_3(self):
        p = self.run_script("issue", "dirty")
        self.assert_rc(p, 3)
        self.assertRegex(p.stdout, r"LINT \S+bench6-dirty\.md:5: claude: ")
        self.assertIn("REFUSED 1 lint hit(s)", p.stdout)
        self.assertNotIn("DRY issue dirty ok", p.stdout)
        self.assert_no_gh(p)

    def test_a_lint_hit_refuses_a_live_post_before_any_gh_call(self):
        p = self.run_script("--live", "issue", "dirty", mode="ok")
        self.assert_rc(p, 3)
        self.assertEqual(self.gh_calls(), [])
        self.assertFalse(self.record.exists())

    def test_title_ending_in_a_period_is_refused(self):
        p = self.run_script("issue", "period")
        self.assert_rc(p, 3)
        self.assertIn("LINT title: title-period", p.stdout)
        self.assert_no_gh(p)

    def test_title_over_120_characters_is_refused(self):
        p = self.run_script("issue", "toolong")
        self.assert_rc(p, 3)
        self.assertIn("LINT title: title-length: 125 characters, over 120", p.stdout)

    def test_a_lint_hit_in_the_title_is_refused(self):
        with (self.root / "tasks" / "issue-bodies" / "TITLES-bench6.md").open("a", encoding="utf-8") as fh:
            fh.write("| 12 | titled | A title drafted with Claude | 27 |\n")
        self.write_body("issue-bodies/bench6-titled.md", "## Problem\n\nA clean body.\n")
        p = self.run_script("issue", "titled")
        self.assert_rc(p, 3)
        self.assertIn("LINT title:1: claude:", p.stdout)

    def test_empty_body_is_refused(self):
        p = self.run_script("issue", "empty")
        self.assert_rc(p, 3)
        self.assertIn("empty-body", p.stdout)

    def test_body_length_counts_characters_not_bytes(self):
        line = "\u00b5" * 99 + "\n"
        self.write_body("issue-bodies/bench6-toolongbody.md", line * 600)
        p = self.run_script("issue", "toolongbody")
        self.assert_rc(p, 0)
        self.assertIn("60000 characters posted", p.stdout)
        self.write_body("issue-bodies/bench6-toolongbody.md", line * 600 + "\u00b5")
        p = self.run_script("issue", "toolongbody")
        self.assert_rc(p, 3)
        self.assertIn("body-length: 60001 characters, over 60000", p.stdout)

    # ---- the H1 and the titles ----
    def test_h1_equal_to_the_title_is_dropped(self):
        p = self.run_script("--live", "issue", "alpha", mode="ok")
        self.assert_rc(p, 0)
        src = (self.root / "tasks" / "issue-bodies" / "bench6-alpha.md").read_text(encoding="utf-8")
        expected = src.split("\n", 2)[2]
        self.assertEqual(self.bodycopy.read_text(encoding="utf-8"), expected)

    def test_h1_equal_to_the_long_form_is_dropped(self):
        p = self.run_script("issue", "beta")
        self.assert_rc(p, 0)
        self.assertIn("h1: dropped", p.stdout)
        self.assertNotIn("    | # The beta defect", p.stdout)
        self.assertIn("    | ## Problem", p.stdout)

    def test_h1_that_differs_is_kept(self):
        p = self.run_script("--live", "issue", "epsilon", mode="ok")
        self.assert_rc(p, 0)
        self.assertIn("NOTE the body starts with an H1", p.stdout)
        src = (self.root / "tasks" / "issue-bodies" / "bench6-epsilon.md").read_text(encoding="utf-8")
        self.assertEqual(self.bodycopy.read_text(encoding="utf-8"), src)

    def test_pr_h1_equal_to_the_stack_title_is_dropped(self):
        p = self.run_script("pr", "02")
        self.assert_rc(p, 0)
        self.assertIn("h1: dropped", p.stdout)
        self.assertIn("--base b7/first-topic --head b7/second-topic", p.stdout)

    def test_pipe_in_a_title_survives_the_table(self):
        p = self.run_script("issue", "pipe")
        self.assert_rc(p, 0)
        self.assertIn("title: A title with a | pipe in it (27 characters)", p.stdout)

    def test_missing_rows_and_files_exit_2(self):
        for args in (("issue", "nosuch"), ("comment", "9999"), ("pr", "03"), ("pr", "07")):
            with self.subTest(args=args):
                p = self.run_script(*args)
                self.assert_rc(p, 2)
                self.assertIn("MISSING", p.stdout)
        self.assert_no_gh(p)

    def test_usage_errors_exit_2(self):
        for args in ((), ("issue",), ("issue", "Bad_Slug"), ("comment", "12a"), ("pr", "x1"),
                     ("--live", "lint", "x.md"), ("--bogus", "issue", "alpha"), ("post", "alpha"),
                     ("issue", "alpha", "extra"), ("status", "extra")):
            with self.subTest(args=args):
                p = self.run_script(*args)
                self.assert_rc(p, 2)
        self.assert_no_gh(p)

    # ---- placeholders ----
    def test_placeholder_resolved_from_the_record(self):
        self.seed_record("issue", "alpha", "1801")
        p = self.run_script("issue", "gamma")
        self.assert_rc(p, 0)
        self.assertIn("SUBST {{alpha}} -> #1801", p.stdout)
        p = self.run_script("--live", "issue", "gamma", mode="ok")
        self.assert_rc(p, 0)
        posted = self.bodycopy.read_text(encoding="utf-8")
        self.assertIn("This follows from #1801; the fix for #1801 does not cover it.", posted)
        self.assertNotIn("{{", posted)

    def test_unresolved_placeholder_is_refused_and_named(self):
        p = self.run_script("issue", "delta")
        self.assert_rc(p, 3)
        self.assertIn("UNRESOLVED {{nowhere-posted}}", p.stdout)
        self.assertRegex(p.stdout, r"LINT \S+bench6-delta\.md:5: placeholder: ")
        self.assert_no_gh(p)
        p = self.run_script("--live", "issue", "delta", mode="ok")
        self.assert_rc(p, 3)
        self.assertEqual(self.gh_calls(), [])

    # ---- live posts and the record ----
    def test_live_issue_post_records_number_and_url(self):
        p = self.run_script("--live", "issue", "alpha", mode="ok")
        self.assert_rc(p, 0)
        self.assertIn("POSTED issue alpha https://github.com/x/y/issues/123\n", p.stdout)
        calls = self.gh_calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertEqual(calls[0], ["issue", "list", "--repo", REPO, "--search", ALPHA_TITLE + " in:title",
                                    "--state", "all", "--json", "number,title",
                                    "--jq", ".[] | [.number, .title] | @tsv"])
        self.assertEqual(calls[1][:6], ["issue", "create", "--repo", REPO, "--title", ALPHA_TITLE])
        self.assertEqual(calls[1][6], "--body-file")
        self.assertEqual(calls[1][8:], ["--assignee", "grantkee"])
        rows = self.record_rows()
        self.assertEqual(len(rows), 1, rows)
        utc, kind, key, number, url, sha = rows[0]
        self.assertRegex(utc, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual((kind, key, number, url), ("issue", "alpha", "123", "https://github.com/x/y/issues/123"))
        self.assertEqual(sha, hashlib.sha256(self.bodycopy.read_bytes()).hexdigest())
        self.assertTrue(self.record.read_text(encoding="utf-8").startswith("# utc\tkind\tkey\tnumber\turl\t"))

    def test_second_post_of_a_recorded_key_is_refused(self):
        self.assert_rc(self.run_script("--live", "issue", "alpha", mode="ok"), 0)
        before = len(self.gh_calls())
        p = self.run_script("--live", "issue", "alpha", mode="ok")
        self.assert_rc(p, 4)
        self.assertIn("DUPLICATE issue alpha: the record already has it as #123", p.stdout)
        self.assertEqual(len(self.gh_calls()), before)
        self.assertEqual(len(self.record_rows()), 1)
        p = self.run_script("issue", "alpha")
        self.assert_rc(p, 4)

    def test_again_posts_a_comment_twice(self):
        self.assert_rc(self.run_script("--live", "comment", "1802", mode="ok"), 0)
        self.assert_rc(self.run_script("--live", "comment", "1802", mode="ok"), 4)
        p = self.run_script("--live", "--again", "comment", "1802", mode="ok")
        self.assert_rc(p, 0)
        self.assertIn("!!!!! AGAIN comment 1802: the record already has it as #1802", p.stdout)
        rows = self.record_rows()
        self.assertEqual([(r[1], r[2], r[3]) for r in rows], [("comment", "1802", "1802")] * 2)
        self.assertEqual(rows[0][4], "https://github.com/x/y/issues/1802#issuecomment-4242")
        self.assertEqual([c[:3] for c in self.gh_calls()], [["issue", "comment", "1802"]] * 2)

    def test_duplicate_found_by_the_precheck_refuses_without_creating(self):
        p = self.run_script("--live", "issue", "alpha", mode="ok",
                            FAKE_GH_LIST="77\t%s\n" % ALPHA_TITLE.lower())
        self.assert_rc(p, 4)
        self.assertIn("DUPLICATE issue alpha: already on GitHub as #77", p.stdout)
        self.assertEqual([c[:2] for c in self.gh_calls()], [["issue", "list"]])
        self.assertFalse(self.record.exists())
        self.ghlog.unlink()
        p = self.run_script("--live", "pr", "01", mode="ok", FAKE_GH_LIST="88\n")
        self.assert_rc(p, 4)
        self.assertIn("DUPLICATE pr 01: already on GitHub as #88", p.stdout)
        self.assertEqual([c[:2] for c in self.gh_calls()], [["pr", "list"]])
        self.assertFalse(self.record.exists())

    def test_a_similar_title_does_not_refuse(self):
        p = self.run_script("--live", "issue", "alpha", mode="ok", FAKE_GH_LIST="78\tA node stopped between two writes\n")
        self.assert_rc(p, 0)
        self.assertIn("NOTE a similar issue exists, not a duplicate: #78", p.stdout)
        self.assertIn("POSTED issue alpha", p.stdout)

    def test_gh_failure_records_nothing(self):
        p = self.run_script("--live", "issue", "alpha", mode="fail-create")
        self.assert_rc(p, 5)
        self.assertIn("HTTP 422: fake failure", p.stderr)
        self.assertIn("GH-FAILED issue alpha", p.stdout)
        self.assertFalse(self.record.exists())
        self.ghlog.unlink()
        p = self.run_script("--live", "pr", "01", mode="fail")
        self.assert_rc(p, 5)
        self.assertEqual([c[:2] for c in self.gh_calls()], [["pr", "list"]])
        self.assertFalse(self.record.exists())

    def test_gh_without_a_url_is_recorded_unparsed(self):
        p = self.run_script("--live", "issue", "alpha", mode="no-url")
        self.assert_rc(p, 6)
        rows = self.record_rows()
        self.assertEqual([(r[1], r[2], r[3], r[4]) for r in rows], [("issue", "alpha", "-", "-")])
        self.assert_rc(self.run_script("--live", "issue", "alpha", mode="ok"), 4)

    def test_pr_argv_carries_base_head_assignee_and_both_reviewers(self):
        p = self.run_script("--live", "pr", "01", mode="ok", FAKE_GH_NUMBER="45")
        self.assert_rc(p, 0)
        self.assertIn("POSTED pr 01 https://github.com/x/y/pull/45", p.stdout)
        pre, create = self.gh_calls()
        self.assertEqual(pre, ["pr", "list", "--repo", REPO, "--head", "b7/first-topic",
                               "--base", "staging/benchmark-bench6-2026-11", "--state", "all",
                               "--json", "number", "--jq", ".[].number"])
        body_file = create[create.index("--body-file") + 1]
        self.assertEqual(create, ["pr", "create", "--repo", REPO, "--base", "staging/benchmark-bench6-2026-11",
                                  "--head", "b7/first-topic", "--title", PR1_TITLE, "--body-file", body_file,
                                  "--assignee", "grantkee", "--reviewer", "MavenRain", "--reviewer", "sstanfield"])
        self.assertEqual([r[1:4] for r in self.record_rows()], [["pr", "01", "45"]])

    def test_body_never_appears_in_an_argument(self):
        for args, marker in ((("issue", "alpha"), "only this body carries"),
                             (("comment", "1802"), "only this body carries"),
                             (("pr", "01"), "only this body carries")):
            with self.subTest(args=args):
                if self.ghlog.exists():
                    self.ghlog.unlink()
                p = self.run_script("--live", *args, mode="ok")
                self.assert_rc(p, 0)
                creates = [c for c in self.gh_calls() if c[1] in ("create", "comment")]
                self.assertEqual(len(creates), 1, self.gh_calls())
                for call in self.gh_calls():
                    self.assertNotIn("--body", call)
                    self.assertFalse(any(marker in a for a in call), call)
                body_file = creates[0][creates[0].index("--body-file") + 1]
                self.assertTrue(body_file.startswith(str(self.tmpdir)), body_file)
                self.assertFalse(os.path.exists(body_file))
                self.assertIn(marker, self.bodycopy.read_text(encoding="utf-8"))

    def test_temp_files_are_removed(self):
        self.assert_rc(self.run_script("issue", "alpha"), 0)
        self.assert_rc(self.run_script("--live", "issue", "alpha", mode="ok"), 0)
        self.assert_rc(self.run_script("issue", "dirty"), 3)
        self.assertEqual(os.listdir(str(self.tmpdir)), [])

    def test_status_lists_the_record(self):
        p = self.run_script("status")
        self.assert_rc(p, 0)
        self.assertIn("STATUS nothing recorded yet", p.stdout)
        self.assert_rc(self.run_script("--live", "issue", "alpha", mode="ok"), 0)
        p = self.run_script("status")
        self.assert_rc(p, 0)
        self.assertRegex(p.stdout, r"issue\s+alpha\s+#123\s+https://github.com/x/y/issues/123")
        self.assertEqual(len(self.gh_calls()), 2)

    def test_script_parses(self):
        p = subprocess.run(["bash", "-n", str(SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           encoding="utf-8", errors="replace")
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
