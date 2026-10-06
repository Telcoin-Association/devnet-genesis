"""Repository hygiene for the benchmark publishing code.

* git tracks nothing private (results, scratch, genesis, secrets, notes, build output, bytecode),
* the ignore rules cover those paths and do not swallow files that must be committed
  (the fixtures, the committed parameter files, the report scripts),
* benchmark/report/*.py and benchmark/tests/*.py parse as Python 3.9 and carry no host path,
  dotted quad or private name. report/scrub.py defines the leak rules, so its literals are
  written in split pieces; the exceptions are its private CIDR ranges (PRIVATE_NETS) and one
  bucket-URL pattern with a capture group, which extracts bucket names from a raw manifest.
  RFC 5737 documentation addresses (192.0.2.0/24 and friends) are allowed anywhere: they never
  name a real host.

The git checks run `git -C <repo>` and skip when git is missing or this file is not inside a
git checkout of the repository.
"""
import ast
import importlib.util
import io
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import tokenize
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIXTURES = TESTS / "fixtures"
REPORT_DIR = BENCH / "report"

# Same boundaries as the leak scanners: not glued to a word character or a dot.
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
IPV4_RE = re.compile(r"(?<![\w.])" + _OCTET + r"(?:\." + _OCTET + r"){3}(?!\w|\.[0-9])")
ALLOWED_IPV4 = ("0.0.0.0", "127.0.0.1")
DOC_NETS = tuple(ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
# Literals no source file may contain (each written split here, so this file passes too).
FORBIDDEN = ("/" + "Users/", "tn-" + "devnet", "tn-" + "devnet-bench-")
GS = "gs" + "://"
# report/scrub.py's DENYLIST words: the rule definitions must keep them split.
SCRUB_SPLIT_WORDS = ("tn-" + "devnet", "obs." + "devnet", "bench-" + "txgen-", "claude" + ".ai",
                     "-----" + "BEGIN", "/" + "home/", "/" + "Users/", "github" + "_pat_",
                     "__FRAME" + "_PREAMBLE", "frame" + "-runtime", "/private" + "/tmp/", "/private" + "/var/",
                     "/var" + "/folders/")

PRIVATE_PREFIXES = ("benchmark/private/", "benchmark/results/", "benchmark/genesis/", "benchmark/work/",
                    "benchmark/.secrets/", "benchmark/logs/", "dist/")
PRIVATE_FILES = ("benchmark/parameters.yaml",)
MUST_BE_IGNORED = ("benchmark/private/x", "benchmark/work/x", "benchmark/results/x", "benchmark/genesis/x",
                   "benchmark/.secrets/x", "benchmark/parameters.yaml", "dist/x", "tasks/checkpoint-pub-x.md",
                   "benchmark/report/__pycache__/x.pyc")
MUST_NOT_BE_IGNORED = ("benchmark/consensus-parameters.yaml", "benchmark/node-image-contract.txt",
                       "benchmark/report/make_bundle.py", "benchmark/report/scrub.py",
                       "benchmark/tests/test_repo_hygiene.py")


def git(*args, **kwargs):
    return subprocess.run(["git", "-C", str(REPO)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=60, **kwargs)


def _in_git_checkout():
    if shutil.which("git") is None:
        return False
    try:
        p = git("rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and os.path.realpath(p.stdout.strip()) == os.path.realpath(str(REPO))


IN_GIT = _in_git_checkout()


def is_documentation(quad):
    addr = ipaddress.ip_address(quad)
    return any(addr in net for net in DOC_NETS)


def is_private_range(line, match):
    """A private CIDR network written as "<network>/<prefix>" (scrub.py's PRIVATE_NETS), not a host."""
    m = re.match(r"/([0-9]{1,2})\b", line[match.end():])
    if not m:
        return False
    try:
        net = ipaddress.ip_network("%s/%s" % (match.group(0), m.group(1)), strict=True)
    except ValueError:
        return False
    return not net.is_global and net.prefixlen < 32


def source_files():
    files = sorted(REPORT_DIR.glob("*.py")) + sorted(TESTS.glob("*.py"))
    return [f for f in files if f.is_file()]


def fixture_files():
    out = []
    for root, dirs, files in os.walk(str(FIXTURES)):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            if f == ".DS_Store":
                continue
            out.append(os.path.relpath(os.path.join(root, f), str(REPO)).replace(os.sep, "/"))
    return out


@unittest.skipUnless(IN_GIT, "git is not installed or %s is not a git checkout" % REPO)
class GitTrackingTests(unittest.TestCase):
    def test_nothing_private_is_tracked(self):
        p = git("ls-files", "-z")
        self.assertEqual(p.returncode, 0, p.stderr)
        tracked = [f for f in p.stdout.split("\0") if f]
        self.assertTrue(tracked)
        bad = [f for f in tracked
               if f.startswith(PRIVATE_PREFIXES) or f in PRIVATE_FILES or f.endswith(".pyc")
               or "__pycache__" in f.split("/")]
        self.assertEqual(bad, [], "private or generated files are tracked")

    def ignored(self, paths):
        """The subset of `paths` git's ignore rules match (tracking status disregarded)."""
        p = git("check-ignore", "--no-index", "--stdin", input="\n".join(paths) + "\n")
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return set(p.stdout.splitlines())

    def rule(self, path):
        return git("check-ignore", "--no-index", "-v", path).stdout.strip()

    def test_private_paths_are_ignored(self):
        got = self.ignored(MUST_BE_IGNORED)
        self.assertEqual(sorted(set(MUST_BE_IGNORED) - got), [], "these paths must be gitignored")

    def test_committed_paths_are_not_ignored(self):
        fixtures = fixture_files()
        self.assertTrue(any(f.startswith("benchmark/tests/fixtures/report/") for f in fixtures))
        paths = list(MUST_NOT_BE_IGNORED) + fixtures
        got = self.ignored(paths)
        self.assertEqual(sorted(got), [], "ignored by: %s" % "; ".join(self.rule(f) for f in sorted(got)))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.files = source_files()
        names = {f.name for f in self.files}
        self.assertIn("scrub.py", names)
        self.assertIn("make_bundle.py", names)
        self.assertIn("test_repo_hygiene.py", names)

    def read(self, path):
        with open(str(path), encoding="utf-8") as fh:
            return fh.read()

    def test_parse_as_python_39(self):
        for f in self.files:
            with self.subTest(f=f.name):
                ast.parse(self.read(f), filename=str(f), feature_version=(3, 9))

    def test_no_host_paths_or_private_names(self):
        for f in self.files:
            text = self.read(f)
            for word in FORBIDDEN:
                self.assertNotIn(word, text, "%s contains a forbidden literal" % f.name)

    def test_no_ipv4_literals(self):
        for f in self.files:
            ranges_ok = f.name == "scrub.py" and f.parent == REPORT_DIR
            for lineno, line in enumerate(self.read(f).splitlines(), 1):
                quads = [m.group(0) for m in IPV4_RE.finditer(line) if m.group(0) not in ALLOWED_IPV4
                         and not is_documentation(m.group(0)) and not (ranges_ok and is_private_range(line, m))]
                self.assertEqual(quads, [], "%s:%d has a dotted quad" % (f.name, lineno))

    def test_gs_urls_only_as_scrub_patterns(self):
        for f in self.files:
            text = self.read(f)
            if f.name != "scrub.py" or f.parent != REPORT_DIR:
                self.assertNotIn(GS, text, f.name)
                continue
            # Tokens, not AST constants: the parser folds the split pieces ("gs:" "//") into one.
            toks = [t.string for t in tokenize.generate_tokens(io.StringIO(text).readline)
                    if t.type == tokenize.STRING and GS in t.string]
            self.assertTrue(toks, "scrub.py is expected to carry its bucket-name pattern")
            for tok in toks:
                self.assertGreaterEqual(re.compile(ast.literal_eval(tok)).groups, 1,
                                        "a %s literal that is not a capture pattern" % GS)
            self.assertEqual(text.count(GS), sum(t.count(GS) for t in toks),
                             "%s outside a pattern string (comment?)" % GS)

    def test_scrub_rule_literals_are_split(self):
        text = self.read(REPORT_DIR / "scrub.py")
        for word in SCRUB_SPLIT_WORDS:
            self.assertNotIn(word, text, "scrub.py must write %r in split pieces" % word[:4])
        spec = importlib.util.spec_from_file_location("report_scrub_hygiene", str(REPORT_DIR / "scrub.py"))
        scrub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scrub)
        rules = {name for name, _ in scrub.DENYLIST}
        for name in ("internal-name", "local-path", "private-key", "email", "hex64"):
            self.assertIn(name, rules)

    def test_report_fixtures_scan_clean(self):
        spec = importlib.util.spec_from_file_location("report_scrub_hygiene2", str(REPORT_DIR / "scrub.py"))
        scrub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scrub)
        self.assertEqual(scrub.scan_dir(str(FIXTURES / "report")), [])


if __name__ == "__main__":
    unittest.main()
