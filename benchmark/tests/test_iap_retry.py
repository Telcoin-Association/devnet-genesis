"""devnet-lib.sh's IAP transport retry (_tn_iap_retry), its fault names (tn_iap_fault_kind) and the
node IP reads that go through it (tn_node_ext_ip / tn_node_int_ip), fully offline.

Every test sources the repo's devnet-lib.sh under bash with CONFIG_FILE pointing at a one-line
config in a sandbox, a fake gcloud first on PATH (fixtures/iap-retry/fake-gcloud.py: one scripted
outcome per call, every call logged with its argv and stdin) and a fake `sleep` that records its
argument and returns at once, so the default 5 s backoff costs nothing and is still checked.
TMPDIR is the sandbox's, so a leaked per-attempt stderr file would show.

Fault kinds: rc 0 -> ok; TN_IAP_REAUTH_PAT on stderr -> reauth (any rc); rc 255 or "gcloud crashed"
-> transport (the only kind retried); an IAP [4003|4033|4047] refusal under another rc ->
iap-refused; anything else -> other. The tests find the library and the fixture relative to their
own location (check_mutations.py copies them into a temporary tree laid out like the repo).
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
LIB = REPO / "devnet-lib.sh"
FIX = TESTS / "fixtures" / "iap-retry"
FAKE = FIX / "fake-gcloud.py"

# The fixture's named outcomes and addresses, read from the fixture itself.
_spec = importlib.util.spec_from_file_location("iap_retry_fake_gcloud", str(FAKE))
fake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake)

REAUTH_MSG = "❌ {}: gcloud needs re-authentication (run: gcloud auth login) — not retried\n"
RETRY_MSG = "⚠️  {}: transport fault (rc {}) — retry {}/{} in {} s\n"
# Knobs the caller's environment must not leak into a test.
SCRUB = ("TN_IAP_RETRIES", "TN_IAP_RETRY_SECS", "TN_IAP_REAUTH_PAT", "TN_SSH_TRANSPORT", "CONFIG_FILE",
         "PROJECT_ID", "TN_USE_VPN")


class Sandbox(unittest.TestCase):

    def setUp(self):
        self.sb = Path(tempfile.mkdtemp(prefix="iap-retry-"))
        self.addCleanup(shutil.rmtree, str(self.sb), True)
        for d in ("bin", "tmp", "fake"):
            (self.sb / d).mkdir()
        self.write("bin/gcloud", '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, FAKE), 0o755)
        self.write("bin/sleep", '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "${IAP_FAKE_DIR}/sleeps"\n', 0o755)
        self.write("config.sh", "PROJECT_ID=fake-project\n")

    def write(self, rel, text, mode=0o644):
        p = self.sb / rel
        p.write_text(text, encoding="utf-8")
        p.chmod(mode)
        return p

    def run_lib(self, snippet, outcomes=(), stdin=None, **env):
        """Source devnet-lib.sh and run <snippet> with the scenario <outcomes>; knobs in **env."""
        self.write("fake/outcomes.json", json.dumps(list(outcomes)))
        for f in ("calls.jsonl", "sleeps"):
            p = self.sb / "fake" / f
            if p.exists():
                p.unlink()
        e = {k: v for k, v in os.environ.items() if k not in SCRUB}
        e.update(PATH="%s:%s" % (self.sb / "bin", os.environ.get("PATH", "/usr/bin:/bin")),
                 CONFIG_FILE=str(self.sb / "config.sh"), IAP_FAKE_DIR=str(self.sb / "fake"),
                 TMPDIR=str(self.sb / "tmp"), LC_ALL="C.UTF-8")
        e.update(env)
        return subprocess.run(["bash", "-c", 'source "$1" || exit 90\n' + snippet, "bash", str(LIB)],
                              input=stdin if stdin is not None else "", stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=e, timeout=60, encoding="utf-8")

    def calls(self):
        p = self.sb / "fake" / "calls.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def sleeps(self):
        p = self.sb / "fake" / "sleeps"
        return p.read_text(encoding="utf-8").split() if p.exists() else []

    def assert_no_temp_left(self):
        self.assertEqual(sorted(os.listdir(str(self.sb / "tmp"))), [])

    def err(self, name):
        return fake.OUTCOMES[name][1]


class FaultKindTests(Sandbox):
    """tn_iap_fault_kind <rc> <stderr-file>: one word on stdout, rc 0, for every class."""

    def kinds(self, rows, **env):
        """[(rc, stderr text or None for a missing file)] -> [(stdout, rc)] from one bash run."""
        lines = []
        for i, (rc, text) in enumerate(rows):
            f = self.sb / "fake" / ("err-%d" % i)
            if text is not None:
                f.write_text(text, encoding="utf-8")
            lines.append('k="$(tn_iap_fault_kind %s "%s")"; echo "$?|${k}"' % ("'%s'" % rc, f))
        p = self.run_lib("\n".join(lines) + "\n", **env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return [tuple(line.split("|", 1)) for line in p.stdout.splitlines()]

    def test_every_class_from_the_fixture_texts(self):
        table = [
            (0, "ok", "ok"), (0, "reauth", "ok"), (0, "crash", "ok"),
            (1, "reauth", "reauth"), (255, "reauth255", "reauth"), (1, "crash-reauth", "reauth"),
            (1, "invalid-grant", "reauth"),
            (255, "drop", "transport"), (1, "crash", "transport"), (255, "refused255", "transport"),
            (1, "refused", "iap-refused"), (1, "refused4033", "iap-refused"), (1, "refused4047", "iap-refused"),
            (1, "notfound", "other"), (2, "fail", "other"), (127, "ok", "other"),
            (1, "remote-hint", "other"), (255, "remote-hint255", "transport"),
        ]
        got = self.kinds([(rc, self.err(name)) for rc, name, _ in table])
        for (rc, name, want), (status, kind) in zip(table, got):
            with self.subTest(rc=rc, stderr=name):
                self.assertEqual((status, kind), ("0", want))
        self.assertEqual(len(got), len(table))

    def test_each_reauth_phrase_alone(self):
        phrases = ["Reauthentication failed.", "There was a problem refreshing your current auth tokens",
                   "invalid_grant"]
        got = self.kinds([(1, "ERROR: %s\n" % s) for s in phrases] + [(255, "ERROR: %s\n" % phrases[0])])
        self.assertEqual(got, [("0", "reauth")] * 4)

    def test_a_bare_login_hint_classifies_by_its_rc(self):
        # A remote script or node-side gcloud that prints only the hint is not the operator's login,
        # and neither is _tn_iap_retry's own ❌ line read back on its own.
        own_line = REAUTH_MSG.format("tn_iap_ssh n1")
        rows = [(1, "gcloud auth login\n"), (255, "gcloud auth login\n"), (2, "Please run: gcloud auth login\n"),
                (1, own_line), (255, own_line), (1, "gcloud auth login\n[4033: 'not authorized']\n")]
        self.assertEqual(self.kinds(rows), [("0", "other"), ("0", "transport"), ("0", "other"),
                                            ("0", "other"), ("0", "transport"), ("0", "iap-refused")])
        # gcloud's real failure followed by the ❌ line (what a caller captures) is still reauth.
        self.assertEqual(self.kinds([(1, self.err("reauth") + own_line)]), [("0", "reauth")])

    def test_bare_backend_refusal_and_missing_file_and_odd_rc(self):
        got = self.kinds([(1, "failed to connect to backend\n"), (1, None), (255, None), ("", "gcloud crashed\n"),
                          ("x", ""), (0, None)])
        self.assertEqual(got, [("0", "iap-refused"), ("0", "other"), ("0", "transport"), ("0", "transport"),
                               ("0", "other"), ("0", "ok")])

    def test_pattern_knob_replaces_the_default(self):
        rows = [(1, "token expired: custom-expired\n"), (1, self.err("reauth")), (1, self.err("invalid-grant"))]
        self.assertEqual(self.kinds(rows, TN_IAP_REAUTH_PAT="custom-expired|other-phrase"),
                         [("0", "reauth"), ("0", "other"), ("0", "other")])
        # Empty means unset: the default pattern.
        self.assertEqual(self.kinds(rows, TN_IAP_REAUTH_PAT=""),
                         [("0", "other"), ("0", "reauth"), ("0", "reauth")])


class TransportRetryTests(Sandbox):
    """`transport` is retried TN_IAP_RETRIES (2) times, TN_IAP_RETRY_SECS (5) apart; wording unchanged."""

    def test_drop_retried_with_the_default_knobs_exact_streams(self):
        p = self.run_lib("tn_iap_ssh n1 z1 'echo hi'", ["drop", "drop", "ok"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "fake gcloud ok\n")
        label = "tn_iap_ssh n1"
        self.assertEqual(p.stderr, self.err("drop") + RETRY_MSG.format(label, 255, 1, 2, 5)
                         + self.err("drop") + RETRY_MSG.format(label, 255, 2, 2, 5))
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(self.sleeps(), ["5", "5"])
        self.assertEqual(self.calls()[0]["argv"],
                         ["compute", "ssh", "n1", "--zone=z1", "--project=fake-project", "--tunnel-through-iap",
                          "--ssh-flag=-o ConnectTimeout=20", "--ssh-flag=-o StrictHostKeyChecking=accept-new",
                          "--command=echo hi"])
        self.assert_no_temp_left()

    def test_retries_run_out_and_the_last_rc_is_returned(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["drop"] * 4, TN_IAP_RETRIES="3", TN_IAP_RETRY_SECS="7")
        self.assertEqual(p.returncode, 255)
        self.assertEqual(len(self.calls()), 4)
        self.assertEqual(self.sleeps(), ["7", "7", "7"])
        self.assertEqual(p.stderr.count("transport fault"), 3)
        self.assertIn(RETRY_MSG.format("tn_iap_ssh n1", 255, 3, 3, 7), p.stderr)
        self.assert_no_temp_left()

    def test_gcloud_crash_is_a_transport_fault(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["crash", "ok"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(p.stderr, self.err("crash") + RETRY_MSG.format("tn_iap_ssh n1", 1, 1, 2, 5))

    def test_retries_off_means_one_attempt(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["drop", "ok"], TN_IAP_RETRIES="0")
        self.assertEqual(p.returncode, 255)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(p.stderr, self.err("drop"))
        self.assertEqual(self.sleeps(), [])

    def test_stdin_reaches_every_attempt_byte_for_byte(self):
        secret = "pass phrase\n\n"
        p = self.run_lib("printf 'pass phrase\\n\\n' | tn_iap_ssh_cmd_stdin n1 z1 'sudo setup --passphrase-stdin'",
                         ["drop", "crash", "ok"])
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.calls()
        self.assertEqual([c["stdin"] for c in calls], [secret] * 3)
        for c in calls:
            self.assertNotIn("pass phrase", " ".join(c["argv"]))
            self.assertIn("--ssh-flag=-T", c["argv"])
        self.assert_no_temp_left()

    def test_every_wrapper_retries_with_its_own_label(self):
        # (snippet, label, forwards the caller's stdin); the others close it for every attempt.
        cases = [("tn_iap_ssh n1 z1 true", "tn_iap_ssh n1", False),
                 ("tn_iap_ssh_stdin n1 z1", "tn_iap_ssh_stdin n1", True),
                 ("tn_iap_ssh_cmd_stdin n1 z1 'cat >/dev/null'", "tn_iap_ssh_cmd_stdin n1", True),
                 ("tn_iap_scp local.txt n1 z1 remote.txt", "tn_iap_scp n1", False),
                 ("tn_node_ext_ip n1 z1", "tn_node_ext_ip n1", False),
                 ("tn_node_int_ip n1 z1", "tn_node_int_ip n1", False)]
        for snippet, label, forwards in cases:
            with self.subTest(snippet=snippet):
                p = self.run_lib(snippet, ["drop", "ok"], stdin="echo remote\n")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(len(self.calls()), 2)
                self.assertEqual(p.stderr, self.err("drop") + RETRY_MSG.format(label, 255, 1, 2, 5))
                self.assertEqual([c["stdin"] for c in self.calls()], ["echo remote\n" if forwards else ""] * 2)


class ReauthTests(Sandbox):
    """`reauth` is named once and never retried, whatever its rc and however many retries are left."""

    def test_reauth_is_not_retried_and_named(self):
        for outcome, rc in (("reauth", 1), ("reauth255", 255), ("crash-reauth", 1)):
            with self.subTest(outcome=outcome):
                p = self.run_lib("tn_iap_ssh n1 z1 true", [outcome, "ok"])
                self.assertEqual(p.returncode, rc)
                self.assertEqual(p.stdout, "")
                self.assertEqual(p.stderr, self.err(outcome) + REAUTH_MSG.format("tn_iap_ssh n1"))
                self.assertEqual(len(self.calls()), 1)
                self.assertEqual(self.sleeps(), [])
                self.assert_no_temp_left()

    def test_reauth_after_a_transport_retry_stops_there(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["drop", "reauth", "ok"])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(p.stderr, self.err("drop") + RETRY_MSG.format("tn_iap_ssh n1", 255, 1, 2, 5)
                         + self.err("reauth") + REAUTH_MSG.format("tn_iap_ssh n1"))

    def test_named_even_with_retries_off_and_on_the_ip_reads(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["reauth"], TN_IAP_RETRIES="0")
        self.assertEqual((p.returncode, len(self.calls())), (1, 1))
        self.assertTrue(p.stderr.endswith(REAUTH_MSG.format("tn_iap_ssh n1")), p.stderr)
        p = self.run_lib("tn_node_int_ip n1 z1", ["invalid-grant", "ok"])
        self.assertEqual((p.returncode, p.stdout, len(self.calls())), (1, "", 1))
        self.assertTrue(p.stderr.endswith(REAUTH_MSG.format("tn_node_int_ip n1")), p.stderr)

    def test_a_remote_login_hint_is_retried_or_returned_by_its_rc(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["remote-hint255", "ok"])
        self.assertEqual((p.returncode, p.stdout, len(self.calls())), (0, "fake gcloud ok\n", 2))
        self.assertEqual(p.stderr, self.err("remote-hint255") + RETRY_MSG.format("tn_iap_ssh n1", 255, 1, 2, 5))
        p = self.run_lib("tn_iap_ssh n1 z1 true", ["remote-hint", "ok"])
        self.assertEqual((p.returncode, len(self.calls())), (1, 1))
        self.assertEqual(p.stderr, self.err("remote-hint"))

    def test_the_pattern_knob_reaches_the_retry(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", [{"like": "drop", "stderr": "custom-expired\n"}, "ok"],
                         TN_IAP_REAUTH_PAT="custom-expired")
        self.assertEqual((p.returncode, len(self.calls())), (255, 1))
        self.assertTrue(p.stderr.endswith(REAUTH_MSG.format("tn_iap_ssh n1")), p.stderr)


class NoRetryTests(Sandbox):
    """rc 0, `iap-refused` and `other` are returned after one attempt, as before."""

    def test_success_is_never_retried_whatever_stderr_says(self):
        for item in ("ok", {"stderr": self.err("crash")}, {"stderr": self.err("reauth")},
                     {"stderr": self.err("refused")}):
            with self.subTest(item=item):
                p = self.run_lib("tn_iap_ssh n1 z1 true", [item, "drop"])
                self.assertEqual((p.returncode, p.stdout), (0, "fake gcloud ok\n"))
                self.assertEqual(len(self.calls()), 1)
                self.assertEqual(p.stderr, item["stderr"] if isinstance(item, dict) else "")
                self.assertEqual(self.sleeps(), [])

    def test_refusal_and_other_failures_are_returned_at_once(self):
        for outcome, rc in (("refused", 1), ("refused4033", 1), ("notfound", 1), ("fail", 2)):
            with self.subTest(outcome=outcome):
                p = self.run_lib("tn_iap_scp /etc/hostname n1 z1 /tmp/x", [outcome, "ok"])
                self.assertEqual((p.returncode, len(self.calls())), (rc, 1))
                self.assertEqual(p.stderr, self.err(outcome))
                self.assertEqual(self.sleeps(), [])

    def test_an_unscripted_call_would_show(self):
        p = self.run_lib("tn_iap_ssh n1 z1 true", [])
        self.assertEqual(p.returncode, 97)
        self.assertEqual([c["outcome"] for c in self.calls()], ["unscripted"])


class NodeIpTests(Sandbox):
    """tn_node_ext_ip / tn_node_int_ip go through _tn_iap_retry; the success output is the describe's."""

    def test_success_output_and_argv_unchanged(self):
        for fn, ip, fmt in (("tn_node_ext_ip", fake.EXT_IP, "value(networkInterfaces[0].accessConfigs[0].natIP)"),
                            ("tn_node_int_ip", fake.INT_IP, "value(networkInterfaces[0].networkIP)")):
            with self.subTest(fn=fn):
                p = self.run_lib('%s n1 z1' % fn, ["ok"], stdin="not for gcloud\n")
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, ip + "\n", ""))
                self.assertEqual(self.calls(), [{"seq": 1, "outcome": "ok", "stdin": "", "argv": [
                    "compute", "instances", "describe", "n1", "--zone=z1", "--project=fake-project",
                    "--format=" + fmt]}])

    def test_a_crashed_describe_no_longer_ends_a_set_e_run(self):
        # bench 3 D4/D5: `intIP="$(tn_node_int_ip …)"` under set -e, one gcloud ReadTimeout.
        script = 'set -e\nintIP="$(tn_node_int_ip n1 z1)"\nextIP="$(tn_node_ext_ip n1 z1)"\necho "IPS ${intIP} ${extIP}"\n'
        p = self.run_lib(script, ["crash", "ok", "crash", "crash", "ok"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "IPS %s %s\n" % (fake.INT_IP, fake.EXT_IP))
        self.assertEqual(len(self.calls()), 5)
        self.assertEqual(p.stderr.count("transport fault (rc 1)"), 3)
        self.assertIn(RETRY_MSG.format("tn_node_int_ip n1", 1, 1, 2, 5), p.stderr)
        self.assertIn(RETRY_MSG.format("tn_node_ext_ip n1", 1, 2, 2, 5), p.stderr)
        self.assert_no_temp_left()

    def test_a_missing_instance_is_not_retried(self):
        p = self.run_lib("tn_node_ext_ip n1 z1", ["notfound", "ok"])
        self.assertEqual((p.returncode, p.stdout, len(self.calls())), (1, "", 1))
        self.assertEqual(p.stderr, self.err("notfound"))


if __name__ == "__main__":
    unittest.main()
