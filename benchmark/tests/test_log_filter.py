"""devnet-log-filter.sh: --log.file.filter on every devnet node's start script, one node at a time.

The driver runs from the repository against the fleet in fixtures/log-filter/config.sh (CONFIG_FILE: the
devnet layout, four validators and the observer at index 4). A fake gcloud (fixtures/log-filter/
fake-gcloud.py) is first on PATH: it records every call and answers each session from a per-node plan,
by the session script's first line (`# logfilter: apply` / `# logfilter: verify`) or, for devnet-lib's
wait_healthy probe, by its command. TN_IAP_RETRIES=0, so every ssh session is one gcloud call, and
LOGFILTER_SETTLE_SECS=0 unless a test sets it.

RemoteScriptTests run the two session scripts the driver sent, on this machine, against the real v2
library (tn-node-deployment/lib/common.sh): fixtures/log-filter/tn-start-docker is the shared v2-node
fixture's start script plus the four JSON-log flags setup-observability.sh adds to a docker install
(lib/observability.sh obs_reth_log_flags docker). Only the node's surroundings are faked: docker and
systemctl (fixtures/log-filter/node-bin), the start-script path, the library's two root-ownership
steps of a write (as test_v2_launch_edit.py does), and the committee guard, the epoch wait and the
epoch reading, which need a live chain. Those tests skip when the submodule is not checked out or the
userland lacks GNU stat -c / mv -T.

Log path: on a devnet node the JSON file log is <DATA_DIR>/logs/telcoin-network-logs/reth.log on the host
(/var/lib/telcoin/logs/...: the container writes /home/nonroot/logs, and /home/nonroot is the data dir's
bind mount). Alloy's sidecar mounts <DATA_DIR>/logs at /var/log/telcoin, so Loki labels the same file
/var/log/telcoin/telcoin-network-logs/reth.log. The verify session derives the host path on the node.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
FIX = TESTS / "fixtures" / "log-filter"
DRIVER = REPO / "devnet-log-filter.sh"
LIB = REPO / "tn-node-deployment" / "lib" / "common.sh"
INSTS = ["validator-1-devnet", "validator-2-devnet", "validator-3-devnet", "validator-4-devnet", "observer-5-devnet"]
OBS = "observer-5-devnet"
V1 = "validator-1-devnet"
START_SCRIPT = "/usr/local/libexec/telcoin/tn-start-docker"
LIB_LINE = ". '/opt/telcoin-node-scripts/lib/common.sh'"
BASE_ENV = {"TN_IAP_RETRIES": "0", "TN_IAP_RETRY_SECS": "0", "LOGFILTER_SETTLE_SECS": "0", "LOGFILTER_GUARD_SECS": "0",
            "HEALTH_TIMEOUT_SECS": "10", "HEALTH_POLL_SECS": "1"}
PLAN_RE = re.compile(r"^\s+(\d+)\. (\S+) \(")


BACKUP = START_SCRIPT + ".bak-logfilter-20261105T060000Z"


def set_line(inst, rc=0, was="-", backup=BACKUP):
    return "LOGFILTER_SET %s flag=--log.file.filter value=info rc=%d was=%s backup=%s\n" % (inst, rc, was, backup)


def ok_no_restart(inst):
    return {"apply": set_line(inst, 1, "info", "none") + "LOGFILTER_OK %s restarted=no\n" % inst}


def restarted(inst, verify, was="-"):
    return {"apply": set_line(inst, 0, was) + ("LOGFILTER_WAIT {0} secs=900\n"
                                              "LOGFILTER_RESTART {0} at=2026-11-05T06:00:08Z\n").format(inst),
            "verify": verify}


class Sandbox(object):
    """A bin dir with the fake gcloud, and the fake fleet's plan and call log."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="log-filter-test-")
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(str(FIX / "fake-gcloud.py"), str(self.bin / "gcloud"))
        (self.bin / "gcloud").chmod(0o755)
        self.sb = self.root / "fleet"
        self.sb.mkdir()
        self.last = None

    def close(self):
        self._tmp.cleanup()

    def plan(self, **per_inst):
        (self.sb / "plan.json").write_text(json.dumps(per_inst))

    def calls(self, kind=None, inst=None):
        f = self.sb / "calls.jsonl"
        rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()] if f.exists() else []
        return [c for c in rows if (kind is None or c["kind"] == kind) and (inst is None or c["inst"] == inst)]

    def run(self, *args, **knobs):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.root), "CONFIG_FILE": str(FIX / "config.sh"),
               "LF_SB": str(self.sb), "LC_ALL": "C"}
        env.update(BASE_ENV)
        env.update(knobs)
        self.last = subprocess.run(["bash", str(DRIVER)] + list(args), cwd=str(self.root), env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True, timeout=120)
        return self.last


class LogFilterCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)

    def lines(self, prefix):
        return [line for line in self.sb.last.stdout.splitlines() if line.startswith(prefix)]

    def explain(self):
        return "rc=%s\n--- stdout\n%s\n--- stderr\n%s" % (self.sb.last.returncode, self.sb.last.stdout,
                                                          self.sb.last.stderr)

    def apply_script(self, inst=OBS, *args, **knobs):
        """The session-1 script the driver sends to <inst> (run with --yes, <args> and <knobs>)."""
        self.sb.plan(**{inst: ok_no_restart(inst)})
        self.sb.run("--yes", inst, *args, **knobs)
        calls = self.sb.calls(kind="apply", inst=inst)
        self.assertEqual(len(calls), 1, self.explain())
        return calls[0]


class DryRunTests(LogFilterCase):
    def test_dry_run_opens_no_ssh_and_plans_observers_first(self):
        r = self.sb.run()
        self.assertEqual(r.returncode, 0, self.explain())
        self.assertEqual(self.sb.calls(), [], "a dry run makes no gcloud call")
        plan = [PLAN_RE.match(line).group(2) for line in r.stdout.splitlines() if PLAN_RE.match(line)]
        self.assertEqual(plan, [OBS] + INSTS[:4])
        self.assertIn("flag=--log.file.filter value=info restart=yes epoch_wait=v2", r.stdout)
        self.assertIn("no ssh opened", r.stdout)

    def test_dry_run_plan_follows_role_then_index_not_argument_order(self):
        r = self.sb.run("validator-3-devnet", "node5", "0", "--skip-epoch-wait", "--filter", "warn")
        self.assertEqual(r.returncode, 0, self.explain())
        plan = [PLAN_RE.match(line).group(2) for line in r.stdout.splitlines() if PLAN_RE.match(line)]
        self.assertEqual(plan, [OBS, V1, "validator-3-devnet"])
        self.assertIn("value=warn restart=yes epoch_wait=skipped", r.stdout)
        self.assertEqual(self.sb.calls(), [])

    def test_an_unknown_target_is_rc_2_before_any_call(self):
        r = self.sb.run("--yes", "node9")
        self.assertEqual(r.returncode, 2, self.explain())
        self.assertIn("unknown target: node9", r.stderr)
        self.assertIn(OBS, r.stderr, "the known targets are listed")
        self.assertEqual(self.sb.calls(), [])

    def test_bad_options_and_values_are_rc_2(self):
        for args, knobs in ((("--bogus",), {}), (("--filter",), {}), (("--filter", "info debug"), {}),
                            (("--filter", "-info"), {}), (("--filter", "it's"), {}),
                            ((), {"LOGFILTER_SETTLE_SECS": "1m"}), ((), {"LOGFILTER_GUARD_TRIES": "0"}),
                            ((), {"LOGFILTER_GUARD_TRIES": "x"}), ((), {"LOGFILTER_GUARD_SECS": "10s"})):
            with self.subTest(args=args, knobs=knobs):
                r = self.sb.run("--yes", *args, **knobs)
                self.assertEqual(r.returncode, 2, self.explain())
        self.assertEqual(self.sb.calls(), [])


    def test_unparsable_filter_directives_are_rc_2(self):
        for bad in ("info,", ",info", "info,,debug", "tn_node=verbose", "a=b=debug", "tn_node[span]=debug",
                    "=debug", "info;debug"):
            with self.subTest(filter=bad):
                r = self.sb.run("--filter", bad)
                self.assertEqual(r.returncode, 2, self.explain())
                self.assertIn("crash-loop", r.stderr)
        for good in ("info", "WARN", "info,tn_primary=debug", "primary::certifier=DEBUG,tn_node", "off",
                     "info,primary::cert_validator=info,tn-worker.x=trace"):
            with self.subTest(filter=good):
                self.assertEqual(self.sb.run("--filter", good).returncode, 0, self.explain())
        self.assertEqual(self.sb.calls(), [])


class ScriptTests(LogFilterCase):
    def test_apply_script_sources_the_v2_lib_and_sets_the_filter(self):
        call = self.apply_script()
        self.assertEqual(call["cmd"], "sudo bash -s")
        script = call["stdin"].splitlines()
        self.assertEqual(script[0], "# logfilter: apply")
        self.assertEqual(script[1], "set -euo pipefail")
        self.assertIn(LIB_LINE, script)
        self.assertIn("S=" + START_SCRIPT, script)
        flag_set = "tn_launch_flag_set \"${S}\" --log.file.filter 'info' || rc=$?"
        self.assertIn(flag_set, script)
        for needle in ("tn_launch_flag_get \"${S}\" --log.file.format", "cp -p \"${S}\" \"${B}\"",
                       "    tn_committee_down_guard \"\" lf_gs || g=$?", "unset TN_ALLOW_QUORUM_RISK"):
            self.assertIn(needle, call["stdin"])
        self.assertTrue(script[2].startswith("[ -r '/opt/telcoin-node-scripts/lib/common.sh' ] || "), script[2])
        lib_check = [n for n, line in enumerate(script) if line.startswith("declare -F tn_launch_flag_get ")]
        self.assertEqual(len(lib_check), 1)
        self.assertLess(lib_check[0], script.index('[ "$(systemctl is-active telcoin 2>/dev/null || true)" = active ]'
                                                   " || fail precheck_active"), "the lib check comes first")
        guards = [n for n, line in enumerate(script) if line == "lf_guard"]
        self.assertEqual(len(guards), 2, "the guard runs before and after the epoch wait")
        self.assertLess(script.index(flag_set), guards[0])
        self.assertLess(guards[0], script.index("tn_wait_restart_window || true"))
        self.assertLess(script.index("tn_wait_restart_window || true"), guards[1])
        self.assertLess(guards[1], script.index("systemctl restart telcoin || r=$?"))

    def test_the_guard_resampling_knobs_reach_the_script_and_the_banner(self):
        call = self.apply_script(OBS, LOGFILTER_GUARD_SECS="")
        self.assertIn("GT=8", call["stdin"].splitlines())
        self.assertIn("GS=10", call["stdin"].splitlines())
        self.assertIn("Guard:      up to 8 samples, 10 s apart", self.sb.last.stdout)
        (self.sb.sb / "calls.jsonl").unlink()
        call = self.apply_script(OBS, LOGFILTER_GUARD_TRIES="3", LOGFILTER_GUARD_SECS="5")
        self.assertIn("GT=3", call["stdin"].splitlines())
        self.assertIn("GS=5", call["stdin"].splitlines())
        self.assertIn("Guard:      up to 3 samples, 5 s apart", self.sb.last.stdout)

    def test_skip_epoch_wait_is_exported_inside_the_session_script_only(self):
        call = self.apply_script(OBS, "--skip-epoch-wait")
        self.assertIn("export TN_SKIP_EPOCH_WAIT=1", call["stdin"].splitlines())
        self.assertIsNone(call["skip_epoch_env"], "never exported to gcloud or the operator's shell")
        (self.sb.sb / "calls.jsonl").unlink()
        call = self.apply_script(OBS)
        self.assertNotIn("export TN_SKIP_EPOCH_WAIT=1", call["stdin"])
        self.assertIn("unset TN_SKIP_EPOCH_WAIT", call["stdin"].splitlines())

    def test_no_restart_script_never_restarts(self):
        call = self.apply_script(OBS, "--no-restart")
        self.assertNotIn("systemctl restart", call["stdin"])
        self.assertNotIn("lf_guard", call["stdin"])
        self.assertNotIn("tn_wait_restart_window ||", call["stdin"])
        self.assertIn("level_check=skipped", call["stdin"])

    def test_a_custom_filter_reaches_the_flag_and_the_resume_command(self):
        call = self.apply_script(OBS, "--filter", "info,tn_primary=debug")
        self.assertIn("tn_launch_flag_set \"${S}\" --log.file.filter 'info,tn_primary=debug' || rc=$?",
                      call["stdin"].splitlines())
        self.assertIn("F='info,tn_primary=debug'", call["stdin"].splitlines())


class ApplyTests(LogFilterCase):
    def test_apply_goes_observers_first_then_validators_in_index_order(self):
        self.sb.plan(**{i: ok_no_restart(i) for i in INSTS})
        r = self.sb.run("--yes")
        self.assertEqual(r.returncode, 0, self.explain())
        self.assertEqual([c["inst"] for c in self.sb.calls()], [OBS] + INSTS[:4])
        self.assertEqual(self.lines("LOGFILTER_OK"), ["LOGFILTER_OK %s restarted=no" % i for i in [OBS] + INSTS[:4]])

    def test_ok_restarted_no_needs_no_verify_session(self):
        self.sb.plan(**{OBS: ok_no_restart(OBS)})
        r = self.sb.run("--yes", OBS)
        self.assertEqual(r.returncode, 0, self.explain())
        self.assertEqual([c["kind"] for c in self.sb.calls()], ["apply"])

    def test_a_restart_is_waited_for_then_verified(self):
        verify = "LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=212\n" % OBS
        self.sb.plan(**{OBS: restarted(OBS, verify), V1: ok_no_restart(V1)})
        r = self.sb.run("--yes", OBS, V1)
        self.assertEqual(r.returncode, 0, self.explain())
        self.assertEqual([(c["inst"], c["kind"]) for c in self.sb.calls()],
                         [(OBS, "apply"), (OBS, "health"), (OBS, "verify"), (V1, "apply")])
        self.assertIn("LOGFILTER_OK %s restarted=yes level_check=ok" % OBS, self.lines("LOGFILTER_OK"))
        verify_script = self.sb.calls(kind="verify")[0]["stdin"]
        self.assertEqual(verify_script.splitlines()[0], "# logfilter: verify")
        self.assertIn(LIB_LINE, verify_script.splitlines())
        self.assertIn("tail -n 300", verify_script)
        self.assertIn("{{.State.StartedAt}}", verify_script)

    def test_a_session_re_sent_after_its_restart_is_still_verified(self):
        # devnet-lib re-sent session 1 after a drop that followed the restart: the second attempt found
        # the flag live. The first attempt's WAIT line shows the restart path was taken.
        p = restarted(OBS, "LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=40\n" % OBS)
        p["apply"] = ("LOGFILTER_SET {0} flag=--log.file.filter value=info rc=0\nLOGFILTER_WAIT {0} secs=900\n"
                      "LOGFILTER_SET {0} flag=--log.file.filter value=info rc=1\nLOGFILTER_OK {0} restarted=no\n"
                      ).format(OBS)
        self.sb.plan(**{OBS: p})
        r = self.sb.run("--yes", OBS)
        self.assertEqual(r.returncode, 0, self.explain())
        self.assertEqual([c["kind"] for c in self.sb.calls()], ["apply", "health", "verify"])
        self.assertIn("LOGFILTER_OK %s restarted=yes level_check=ok" % OBS, self.lines("LOGFILTER_OK"))

    def test_a_session_re_sent_while_its_restart_was_in_flight_is_verified(self):
        # The re-sent attempt found telcoin not active (the first attempt's restart was still going on).
        p = restarted(OBS, "LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=12\n" % OBS)
        p["apply"] = (set_line(OBS) + "LOGFILTER_WAIT {0} secs=900\nLOGFILTER_FAIL {0} reason=precheck_active\n"
                      ).format(OBS)
        self.sb.plan(**{OBS: p})
        r = self.sb.run("--yes", OBS)
        self.assertEqual(r.returncode, 0, self.explain())
        self.assertEqual([c["kind"] for c in self.sb.calls()], ["apply", "health", "verify"])
        self.assertIn("LOGFILTER_OK %s restarted=yes level_check=ok" % OBS, self.lines("LOGFILTER_OK"))

    def test_a_precheck_active_failure_without_a_restart_path_stops(self):
        self.sb.plan(**{OBS: {"apply": "LOGFILTER_FAIL %s reason=precheck_active\n" % OBS, "apply_rc": 1}})
        r = self.sb.run("--yes", OBS, V1)
        self.assertEqual(r.returncode, 1, self.explain())
        self.assertEqual([c["kind"] for c in self.sb.calls()], ["apply"])
        self.assertIn("    nothing changed on %s" % OBS, r.stdout.splitlines())

    def test_the_settle_wait_follows_restarted_nodes_only(self):
        verify = "LOGFILTER_VERIFY {0} flag=yes debug_lines=0 lines=30\n"
        self.sb.plan(**{OBS: restarted(OBS, verify.format(OBS)), V1: ok_no_restart(V1),
                        "validator-2-devnet": ok_no_restart("validator-2-devnet"),
                        "validator-3-devnet": restarted("validator-3-devnet", verify.format("validator-3-devnet"))})
        r = self.sb.run("--yes", OBS, V1, "validator-2-devnet", "validator-3-devnet", LOGFILTER_SETTLE_SECS="1")
        self.assertEqual(r.returncode, 0, self.explain())
        out = r.stdout.splitlines()
        settles = [n for n, line in enumerate(out) if "settling 1s" in line]
        self.assertEqual(len(settles), 1, "after the restarted observer only (not after a no-restart node or the last)")
        self.assertLess(out.index("LOGFILTER_OK %s restarted=yes level_check=ok" % OBS), settles[0])
        self.assertLess(settles[0], [n for n, line in enumerate(out) if line.startswith(">>> [2/4] ")][0])

    def test_validators_are_told_the_session_may_wait_for_the_epoch_boundary(self):
        self.sb.plan(**{i: ok_no_restart(i) for i in (OBS, V1)})
        r = self.sb.run("--yes", OBS, V1)
        out = r.stdout.split(">>> [2/2] ")
        note = "may wait up to 1800 s for the epoch boundary"
        self.assertNotIn(note, out[0], "not on the observer")
        self.assertIn(note, out[1])
        for flag in ("--skip-epoch-wait", "--no-restart"):
            with self.subTest(flag=flag):
                self.assertNotIn(note, self.sb.run("--yes", V1, flag).stdout)


class SweepTests(LogFilterCase):
    def assert_stopped_at(self, inst, untouched):
        self.assertEqual(self.sb.last.returncode, 1, self.explain())
        for u in untouched:
            self.assertEqual(self.sb.calls(inst=u), [], "%s is never contacted" % u)
        resume = [line.strip() for line in self.sb.last.stdout.splitlines() if line.strip().startswith("resume:")]
        self.assertEqual(resume, ["resume: ./devnet-log-filter.sh --yes " + " ".join([inst] + untouched)])

    def test_a_deferred_node_stops_the_sweep(self):
        self.sb.plan(**{OBS: {"apply": "LOGFILTER_SET %s flag=--log.file.filter value=info rc=0\n"
                                       "LOGFILTER_DEFERRED %s reason=guard\n" % (OBS, OBS)},
                        V1: ok_no_restart(V1)})
        self.sb.run("--yes", OBS, V1)
        self.assert_stopped_at(OBS, [V1])
        self.assertEqual([c["kind"] for c in self.sb.calls()], ["apply"])
        self.assertIn("LOGFILTER_DEFERRED %s reason=guard" % OBS, self.sb.last.stdout.splitlines())

    def test_debug_lines_after_the_restart_fail_and_stop(self):
        verify = "LOGFILTER_VERIFY %s flag=yes debug_lines=4 lines=300\n" % OBS
        self.sb.plan(**{OBS: restarted(OBS, verify), V1: ok_no_restart(V1)})
        self.sb.run("--yes", OBS, V1)
        self.assert_stopped_at(OBS, [V1])
        self.assertEqual(self.lines("LOGFILTER_FAIL"),
                         ["LOGFILTER_FAIL %s reason=debug_lines debug_lines=4 lines=300" % OBS])
        out = self.sb.last.stdout
        self.assertIn("    rollback on %s (this run changed %s; --log.file.filter was -):" % (OBS, START_SCRIPT), out)
        self.assertIn("tn_launch_flag_unset %s --log.file.filter'" % START_SCRIPT, out)
        self.assertIn("or restore the copy taken first: sudo cp -p %s %s" % (BACKUP, START_SCRIPT), out)
        self.assertIn("bypasses the committee guard", out)

    def test_the_rollback_puts_a_previous_value_back(self):
        self.sb.plan(**{OBS: restarted(OBS, "LOGFILTER_VERIFY %s flag=no debug_lines=0 lines=8\n" % OBS, was="debug")})
        self.sb.run("--yes", OBS)
        out = self.sb.last.stdout
        self.assertIn("tn_launch_flag_set %s --log.file.filter debug'" % START_SCRIPT, out)
        self.assertNotIn("tn_launch_flag_unset", out)
        self.assertIn("sudo cp -p %s %s" % (BACKUP, START_SCRIPT), out)

    def test_a_node_this_run_did_not_change_gets_no_rollback(self):
        # The flag was already in the start script (an earlier deferred run) but not live.
        p = restarted(OBS, "LOGFILTER_VERIFY %s flag=yes debug_lines=2 lines=60\n" % OBS)
        p["apply"] = p["apply"].replace(set_line(OBS), set_line(OBS, 1, "info", "none"))
        self.sb.plan(**{OBS: p})
        self.sb.run("--yes", OBS)
        self.assertEqual(self.sb.last.returncode, 1, self.explain())
        out = self.sb.last.stdout
        self.assertIn("nothing changed in %s on %s by this run" % (START_SCRIPT, OBS), out)
        self.assertNotIn("rollback on", out)

    def test_a_blind_guard_deferral_stops_the_sweep(self):
        self.sb.plan(**{OBS: {"apply": set_line(OBS) + "LOGFILTER_DEFERRED %s reason=guard_blind\n" % OBS},
                        V1: ok_no_restart(V1)})
        self.sb.run("--yes", OBS, V1)
        self.assert_stopped_at(OBS, [V1])
        self.assertIn("could not count the committee", self.sb.last.stdout)
        self.assertNotIn("rollback on", self.sb.last.stdout)

    def test_a_flag_missing_from_the_restarted_container_fails(self):
        verify = "LOGFILTER_VERIFY %s flag=no debug_lines=0 lines=50\n" % OBS
        self.sb.plan(**{OBS: restarted(OBS, verify)})
        self.sb.run("--yes", OBS, V1)
        self.assert_stopped_at(OBS, [V1])
        self.assertEqual(self.lines("LOGFILTER_FAIL"), ["LOGFILTER_FAIL %s reason=flag_not_live" % OBS])

    def test_no_new_log_lines_cannot_prove_the_level(self):
        verify = "LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=0\n" % OBS
        self.sb.plan(**{OBS: restarted(OBS, verify)})
        self.sb.run("--yes", OBS)
        self.assert_stopped_at(OBS, [])
        self.assertEqual(self.lines("LOGFILTER_FAIL"), ["LOGFILTER_FAIL %s reason=no_new_log_lines" % OBS])

    def test_a_precheck_failure_stops_the_sweep_and_says_nothing_changed(self):
        self.sb.plan(**{OBS: {"apply": "LOGFILTER_FAIL %s reason=precheck_json_format\n" % OBS, "apply_rc": 1}})
        self.sb.run("--yes", OBS, V1, "--filter", "warn")
        self.assertEqual(self.sb.last.returncode, 1, self.explain())
        self.assertEqual(self.sb.calls(inst=V1), [])
        self.assertIn("resume: ./devnet-log-filter.sh --yes --filter 'warn' %s %s" % (OBS, V1), self.sb.last.stdout)
        self.assertIn("    nothing changed on %s" % OBS, self.sb.last.stdout.splitlines())
        self.assertNotIn("rollback on", self.sb.last.stdout)

    def test_a_session_without_an_outcome_is_a_failure(self):
        self.sb.plan(**{OBS: {"apply": set_line(OBS), "apply_rc": 255}})
        self.sb.run("--yes", OBS, V1)
        self.assert_stopped_at(OBS, [V1])
        self.assertEqual(self.lines("LOGFILTER_FAIL"), ["LOGFILTER_FAIL %s reason=no_outcome ssh_rc=255" % OBS])
        self.assertIn("    rollback on %s" % OBS, self.sb.last.stdout)

    def test_a_node_that_does_not_come_back_is_never_verified(self):
        p = restarted(OBS, "LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=9\n" % OBS)
        p["health"] = "INACTIVE:activating"
        self.sb.plan(**{OBS: p})
        self.sb.run("--yes", OBS, V1, HEALTH_TIMEOUT_SECS="1", HEALTH_POLL_SECS="1")
        self.assert_stopped_at(OBS, [V1])
        self.assertEqual(self.sb.calls(kind="verify"), [])
        self.assertEqual(self.lines("LOGFILTER_FAIL"), ["LOGFILTER_FAIL %s reason=not_healthy" % OBS])


def _gnu_userland():
    """GNU stat -c and mv -T, which the library's write path uses (lib/common.sh _tn_launch_write)."""
    d = tempfile.mkdtemp()
    try:
        a, b = os.path.join(d, "a"), os.path.join(d, "b")
        open(a, "w").close()
        ok = subprocess.run(["stat", "-c", "%a %g", a], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
        return ok and subprocess.run(["mv", "-f", "-T", a, b], stderr=subprocess.PIPE).returncode == 0
    except OSError:
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


ARGS_BEFORE = "[node --bls-passphrase-source stdin --datadir /home/nonroot --log.file.format json]"
ARGS_AFTER = "[node --bls-passphrase-source stdin --datadir /home/nonroot --log.file.format json --log.file.filter info]"
STARTED_AT = "2026-11-05T06:00:08.123456789Z"


@unittest.skipUnless(LIB.is_file(), "tn-node-deployment is not checked out (%s missing)" % LIB)
class RemoteScriptTests(LogFilterCase):
    """The scripts the driver sent, run here against the real v2 library and a fake node."""

    # The committee guard, faked: one line of guard-plan per call ("<rc> <log|warn>"; missing lines
    # are "0 log"), reported through the library's own _tn_guard_say and the caller's progress
    # function. Each call is logged as guard:<argc>:<url>:<progress-fn>:<TN_ALLOW_QUORUM_RISK>.
    STUBS = r"""
tn_root_dir_ok() { return 0; }
chown() { return 0; }
tn_committee_down_guard() {
    echo "guard:$#:${1:-}:${2:-}:${TN_ALLOW_QUORUM_RISK:-unset}" >> '@N@/calls'
    local k plan
    k="$(grep -c '^guard:' '@N@/calls')"
    plan="$(sed -n "${k}p" '@N@/guard-plan' 2>/dev/null)"
    [ -n "${plan}" ] || plan="0 log"
    _tn_guard_say "${plan#* }" "fake guard says ${plan#* }" "${2:-}"
    return "${plan%% *}"
}
tn_wait_restart_window() { echo wait >> '@N@/calls'; }
tn_epoch_secs_left() { echo '420 7 1762322400 86400'; }
"""
    G = "guard:2::lf_gs:unset"

    @classmethod
    def setUpClass(cls):
        if not _gnu_userland():
            raise unittest.SkipTest("needs GNU stat -c and mv -T (the library's write path, as on a node)")

    def setUp(self):
        super(RemoteScriptTests, self).setUp()
        self.node = self.sb.root / "node"
        for d in ("docker", "systemd", "usr/local/libexec/telcoin", "var/lib/telcoin/logs/telcoin-network-logs"):
            (self.node / d).mkdir(parents=True)
        self.start = self.node / START_SCRIPT.lstrip("/")
        shutil.copy2(str(FIX / "tn-start-docker"), str(self.start))
        self.reth = self.node / "var/lib/telcoin/logs/telcoin-network-logs/reth.log"
        shutil.copyfile(str(FIX / "reth.log"), str(self.reth))
        self.docker("args", ARGS_BEFORE)
        self.docker("args.after", ARGS_AFTER)
        self.docker("started-at", STARTED_AT)
        self.docker("mounts", "/home/nonroot %s/var/lib/telcoin" % self.node)
        self.guard_plan()

    def docker(self, name, text):
        (self.node / "docker" / name).write_text(text + "\n")

    def guard_plan(self, *calls):
        (self.node / "guard-plan").write_text("".join(c + "\n" for c in calls))

    def local(self, script, lib=None, extra_stubs="", env_extra=None):
        """Run a session script on the fake node; its CompletedProcess. <lib> replaces the library path."""
        lib = str(LIB) if lib is None else lib
        self.assertIn(LIB_LINE, script.splitlines())
        self.assertIn("S=" + START_SCRIPT, script.splitlines())
        stubs = self.STUBS.replace("@N@", str(self.node)) + extra_stubs
        script = script.replace(LIB_LINE, LIB_LINE + stubs, 1).replace("S=" + START_SCRIPT, "S=%s" % self.start, 1)
        script = script.replace("/opt/telcoin-node-scripts/lib/common.sh", lib)
        env = {"PATH": str(FIX / "node-bin") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.node), "TMPDIR": str(self.node), "LC_ALL": "C", "LF_NODE": str(self.node),
               "TN_ROOT_PREFIX": str(self.node)}
        env.update(env_extra or {})
        return subprocess.run(["bash", "-s"], input=script, env=env, cwd=str(self.node), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def sent(self, kind, *args, **plan):
        """The <kind> script the driver sends to the observer."""
        verify = "LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=3\n" % OBS
        self.sb.plan(**{OBS: plan.get("plan", restarted(OBS, verify))})
        self.sb.run("--yes", OBS, *args)
        calls = self.sb.calls(kind=kind)
        self.assertEqual(len(calls), 1, self.explain())
        return calls[0]["stdin"]

    def markers(self, p):
        return [line for line in p.stdout.splitlines() if line.startswith("LOGFILTER_")]

    def node_calls(self):
        f = self.node / "calls"
        return f.read_text().split() if f.exists() else []

    def restarts(self):
        f = self.node / "systemd" / "calls"
        return f.read_text().split() if f.exists() else []

    def backups(self):
        return sorted(self.start.parent.glob("tn-start-docker.bak-logfilter-*"))

    def test_apply_writes_the_flag_backs_up_and_restarts_behind_the_guard(self):
        original = self.start.read_text()
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 0, p.stderr)
        m = self.markers(p)
        self.assertRegex(m[0], r"^LOGFILTER_SET %s flag=--log\.file\.filter value=info rc=0 was=- backup=%s\.bak-"
                               r"logfilter-\d{8}T\d{6}Z$" % (OBS, re.escape(str(self.start))))
        self.assertEqual(m[1], "LOGFILTER_WAIT %s secs=420" % OBS)
        self.assertRegex(m[2], r"^LOGFILTER_RESTART %s at=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$" % OBS)
        self.assertEqual(self.node_calls(), [self.G, "wait", self.G])
        self.assertEqual(self.restarts(), ["restart"])
        self.assertTrue(self.start.read_text().rstrip("\n").endswith("--log.file.max-files 5 --log.file.filter info"))
        self.assertEqual([str(b) for b in self.backups()], [m[0].split("backup=")[1]])
        self.assertEqual(self.backups()[0].read_text(), original)

    def test_apply_skips_the_restart_and_the_backup_when_the_flag_is_already_live(self):
        script = self.sent("apply")
        self.assertEqual(self.local(script).returncode, 0)
        p = self.local(script)
        self.assertEqual(self.markers(p), ["LOGFILTER_SET %s flag=--log.file.filter value=info rc=1 was=info backup=none"
                                           % OBS, "LOGFILTER_OK %s restarted=no" % OBS])
        self.assertEqual(self.restarts(), ["restart"], "the second run restarts nothing")
        self.assertEqual(len(self.backups()), 1, "and takes no second backup")

    def test_a_different_value_is_backed_up_and_reported_as_was(self):
        self.start.write_text(self.start.read_text().rstrip("\n") + " --log.file.filter debug\n")
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(" rc=0 was=debug backup=%s.bak-logfilter-" % self.start, self.markers(p)[0])
        self.assertIn("--log.file.filter info", self.start.read_text())
        self.assertNotIn("--log.file.filter debug", self.start.read_text())
        self.assertEqual(len(self.backups()), 1)

    def test_a_guard_that_refuses_every_sample_defers_without_waiting_or_restarting(self):
        self.guard_plan(*["1 warn"] * 8)
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.markers(p)[-1], "LOGFILTER_DEFERRED %s reason=guard" % OBS)
        self.assertEqual(self.node_calls(), [self.G] * 8, "eight samples, no epoch wait")
        self.assertEqual(self.restarts(), [])
        tries = [line for line in p.stderr.splitlines() if line.startswith("guard try ")]
        self.assertEqual(tries, ["guard try %d/8 refused — resampling in 0 s" % k for k in range(1, 8)]
                         + ["guard try 8/8 refused — deferring"])

    def test_a_guard_that_refuses_twice_then_passes_goes_on_to_the_restart(self):
        self.guard_plan("1 warn", "1 warn", "0 log")
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertRegex(self.markers(p)[-1], r"^LOGFILTER_RESTART %s at=" % OBS)
        self.assertEqual(self.node_calls(), [self.G] * 3 + ["wait", self.G],
                         "three samples before the epoch wait, one after it")
        self.assertEqual(self.restarts(), ["restart"])
        self.assertEqual(len([line for line in p.stderr.splitlines() if line.startswith("guard try ")]), 2)

    def test_a_guard_that_goes_ahead_with_a_warning_defers_blind(self):
        self.guard_plan("0 warn")
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.markers(p)[-1], "LOGFILTER_DEFERRED %s reason=guard_blind" % OBS)
        self.assertIn("fake guard says warn", p.stderr, "the guard's message reaches the operator")
        self.assertEqual(self.node_calls(), [self.G], "deferred at the first sample: no resampling, no epoch wait")
        self.assertNotIn("guard try ", p.stderr)
        self.assertEqual(self.restarts(), [])

    def test_a_blind_guard_after_the_epoch_wait_defers_too(self):
        self.guard_plan("0 log", "0 warn")
        p = self.local(self.sent("apply"))
        self.assertEqual(self.markers(p)[1:], ["LOGFILTER_WAIT %s secs=420" % OBS,
                                               "LOGFILTER_DEFERRED %s reason=guard_blind" % OBS])
        self.assertEqual(self.node_calls(), [self.G, "wait", self.G])
        self.assertEqual(self.restarts(), [])

    def test_the_quorum_risk_override_never_reaches_the_guard(self):
        p = self.local(self.sent("apply"), env_extra={"TN_ALLOW_QUORUM_RISK": "1"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.node_calls(), [self.G, "wait", self.G])

    def test_a_missing_lib_or_lib_function_is_refused_before_any_change(self):
        before = self.start.read_text()
        for name, kwargs in (("no lib", {"lib": str(self.node / "missing" / "common.sh")}),
                             ("old lib", {"extra_stubs": "unset -f tn_launch_flag_unset\n"})):
            with self.subTest(name):
                for kind in ("apply", "verify"):
                    (self.sb.sb / "calls.jsonl").unlink() if (self.sb.sb / "calls.jsonl").exists() else None
                    p = self.local(self.sent(kind), **kwargs)
                    self.assertEqual(p.returncode, 1)
                    self.assertEqual(self.markers(p), ["LOGFILTER_FAIL %s reason=precheck_lib" % OBS])
        self.assertEqual(self.start.read_text(), before)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.node_calls(), [])

    def test_a_node_without_the_json_file_log_is_refused_untouched(self):
        self.start.write_text(self.start.read_text().replace(" --log.file.format json", ""))
        before = self.start.read_text()
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.markers(p), ["LOGFILTER_FAIL %s reason=precheck_json_format" % OBS])
        self.assertEqual(self.start.read_text(), before)
        self.assertEqual(self.backups(), [])

    def test_a_node_whose_log_cannot_be_found_is_refused_before_any_change(self):
        self.docker("mounts", "/data %s/var/lib/telcoin" % self.node)
        before = self.start.read_text()
        p = self.local(self.sent("apply"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.markers(p), ["LOGFILTER_FAIL %s reason=precheck_log_path" % OBS])
        self.assertEqual(self.start.read_text(), before)
        self.assertEqual(self.restarts(), [])

    def test_no_restart_writes_the_flag_only(self):
        script = self.sent("apply", "--no-restart", plan={"apply": "LOGFILTER_OK %s restarted=no level_check=skipped" % OBS})
        p = self.local(script)
        self.assertEqual(self.markers(p)[-1], "LOGFILTER_OK %s restarted=no level_check=skipped" % OBS)
        self.assertIn("--log.file.filter info", self.start.read_text())
        self.assertEqual(self.restarts(), [])
        self.assertEqual(self.node_calls(), [])

    def test_verify_counts_only_lines_written_after_the_container_started(self):
        self.docker("args", ARGS_AFTER)
        p = self.local(self.sent("verify"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.markers(p), ["LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=3" % OBS])

    def test_verify_reports_a_debug_line_after_the_start_and_a_flag_that_is_not_live(self):
        with self.reth.open("a") as f:
            f.write('{"timestamp":"2026-11-05T06:00:12.000800Z","level":"DEBUG","fields":{"message":"new"},'
                    '"target":"tn_node"}\n')
        p = self.local(self.sent("verify"))
        self.assertEqual(self.markers(p), ["LOGFILTER_VERIFY %s flag=no debug_lines=1 lines=4" % OBS])

    def test_verify_maps_the_log_directory_through_the_longest_bind_mount(self):
        other = self.node / "srv" / "node-logs" / "telcoin-network-logs"
        other.mkdir(parents=True)
        shutil.copyfile(str(FIX / "reth.log"), str(other / "reth.log"))
        self.reth.unlink()
        self.docker("mounts", "/home/nonroot %s/var/lib/telcoin\n/home/nonroot/logs %s/srv/node-logs"
                    % (self.node, self.node))
        self.docker("args", ARGS_AFTER)
        p = self.local(self.sent("verify"))
        self.assertEqual(self.markers(p), ["LOGFILTER_VERIFY %s flag=yes debug_lines=0 lines=3" % OBS], p.stderr)

    def test_verify_without_a_mapped_log_fails(self):
        self.docker("mounts", "/data %s/var/lib/telcoin" % self.node)
        p = self.local(self.sent("verify"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.markers(p), ["LOGFILTER_FAIL %s reason=log_path" % OBS])


if __name__ == "__main__":
    unittest.main()
