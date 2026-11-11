"""The certification outcome: bench_certification_record and bench_cert_failures_snapshot, offline.

A validator whose own headers are not certified is a recorded result of a run: after collect and at
the teardown (before the local gate) the harness runs tools/cert-rate.py over the pulled logs,
records manifest.certification / .certification_meta / .cert_failures, and snapshots the container
log of every failing validator into logs/, where the local gate then requires it.

The functions are cut out of bench-lib.sh by name (as test_teardown_local_gate.py does) and run
under bash, with benchmark/pull-lib.sh (bench_pull_stream, through which the saved-log tar is pulled)
sourced when it is there. GCP is fixtures/teardown/fake-gcloud.py (instance describe) behind the perl
alarm stub.
The node side is real: tn_iap_ssh is a function that runs the harness's remote command string under
a local bash, with fixtures/certification/ stubs for sudo (maps the node's log dir to a directory
per fake node) and docker (the container's log is a file). So the save and saved-log tar scripts
the harness sends to a node are parsed and run here as they are.

The logs: three nodes, two 10-minute phases (warmup, mixed) and a "run" window. bench-validator-01
certifies every header it proposes; bench-validator-02 certifies all of them in warmup and none in
mixed (0 %, and 50 % over the run); bench-validator-03 is also at 0 % but its role is observer, so
it is never judged.
"""
import calendar
import gzip
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
FIX = TESTS / "fixtures" / "certification"
TEARDOWN_FIX = TESTS / "fixtures" / "teardown"
LIB = (BENCH / "bench-lib.sh").read_text()
TEARDOWN = (BENCH / "benchmark-teardown.sh").read_text()
BLAST = (BENCH / "benchmark-blast.sh").read_text()

RUN = "r20991231-0101"
PROJECT = "acme-project"
V1, V2, V3 = "bench-validator-01", "bench-validator-02", "bench-validator-03"
SNAP_RE = re.compile(r"^logs/bench-validator-02-telcoin-cert-fail-\d{8}T\d{6}Z\.log\.gz$")


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


FUNCTIONS = (
    "bench_warn", "bench_now_iso", "bench_now_unix", "bench_iso_from_unix", "bench_index_of", "_bench_in_lines",
    "_bench_log_name_ok", "_bench_unstamp_names", "_bench_log_sources_of", "_bench_marker_verdict",
    "bench_node_vouched_logs",
    "bench_save_node_log", "_bench_saved_log_cmd_skip", "_bench_saved_log_cmd", "_bench_pull_saved_logs",
    "bench_local_gate_check", "_bench_index_kind", "_bench_cert_log_glob", "bench_local_analysis",
    "_bench_cert_fail_pct", "_bench_cert_validators_json", "_bench_cert_rel", "_bench_cert_jq", "_bench_cert_insts",
    "bench_certification_record", "_bench_cert_logs_here", "bench_cert_failures_snapshot",
    "bench_certification_summary",
    # the node log pull (NodePullTests)
    "bench_instance_json", "_bench_instance_ident", "_bench_unit_log_cmd", "_bench_pull_node_log",
    "_bench_pull_unit_log", "_bench_logs_here", "_bench_write_marker", "_bench_pull_rc", "_bench_pull_node",
    "bench_pull_node_logs")

# pull-lib.sh (unit U-H1) when it is there; until then a stand-in that keeps its bench_pull_stream
# contract for the `cmd` form used here: one attempt into a fresh temp file beside <out>, the gzip or
# tar checked, then renamed to <out>; rc 0 landed, 1 empty, 2 failed. tn_iap_fault_kind is unit
# U-H6's (devnet-lib.sh), not sourced here: a stand-in with its <rc> <stderr-file> contract.
PULL_SHIM = (
    '[ ! -r "${BENCH_DIR}/pull-lib.sh" ] || . "${BENCH_DIR}/pull-lib.sh"\n'
    "declare -F tn_iap_fault_kind >/dev/null || tn_iap_fault_kind() {\n"
    "    case \"$1\" in 0) echo ok ;; 255) echo transport ;; *) echo other ;; esac\n"
    "}\n"
    "declare -F bench_pull_stream >/dev/null || bench_pull_stream() {\n"
    "    local tmp rc=0\n"
    "    tmp=\"$(mktemp \"$4.aXXXXXX\")\" || return 2\n"
    "    TN_IAP_RETRIES=0 tn_iap_ssh \"$1\" \"$2\" \"$6\" > \"${tmp}\" || rc=$?\n"
    "    if [ \"${rc}\" -ne 0 ]; then rm -f \"${tmp}\"; return 2; fi\n"
    "    if [ ! -s \"${tmp}\" ]; then rm -f \"${tmp}\"; return 1; fi\n"
    "    case \"$3\" in gz) gzip -t \"${tmp}\" 2>/dev/null ;; tar) tar -tf \"${tmp}\" >/dev/null 2>&1 ;; *) true ;; esac \\\n"
    "        || { rm -f \"${tmp}\"; return 2; }\n"
    "    mv -f \"${tmp}\" \"$4\"\n"
    "}\n")

PRELUDE = (
    "set -euo pipefail\n"
    + shell_assignment(LIB, "BENCH_NODE_LOG_DIR") + shell_assignment(LIB, "BENCH_CERT_MIN_PROPOSED")
    + shell_assignment(LIB, "BENCH_PULL_MARKER_V") + shell_assignment(LIB, "BENCH_MARKER_MAX_AGE_SECS")
    + "INSTANCE_NAMES=(%s %s %s)\nNODE_ROLES=(validator validator observer)\n"
      "ZONES=(us-west2-a europe-west2-b us-west2-a)\n" % (V1, V2, V3)
    # The node's side of IAP ssh: the command string, run by a local bash as the node's shell would.
    + "tn_iap_ssh() {\n"
      "    printf '%s\\t%s\\n' \"$1\" \"$3\" >> \"${FAKE_ROOT}/ssh.log\"\n"
      "    case \"$3\" in *\"${FAKE_SSH_FAIL:-@none@}\"*) echo \"ssh: connection to $1 failed\" >&2; return 255 ;; esac\n"
      "    FAKE_NODE=\"$1\" bash -c \"$3\"\n"
      "}\n"
    # A script on stdin (`sudo bash -s` on the node): run by a local bash. FAKE_SSH_FAIL fails a session
    # whose script holds that text; FAKE_SSH_EMPTY makes one answer nothing (rc 0, no output).
    + "tn_iap_ssh_stdin() {\n"
      "    local s; s=\"$(cat)\"\n"
      "    printf '%s\\tstdin %s\\n' \"$1\" \"$(printf '%s\\n' \"$s\" | head -n 1)\" >> \"${FAKE_ROOT}/ssh.log\"\n"
      "    case \"$s\" in *\"${FAKE_SSH_FAIL:-@none@}\"*) echo \"ssh: connection to $1 failed\" >&2; return 255 ;; esac\n"
      "    case \"$s\" in *\"${FAKE_SSH_EMPTY:-@none@}\"*) return 0 ;; esac\n"
      "    printf '%s\\n' \"$s\" | FAKE_NODE=\"$1\" bash -s\n"
      "}\n"
    + "".join(shell_function(LIB, n) for n in FUNCTIONS) + PULL_SHIM)

T0 = calendar.timegm((2026, 10, 6, 6, 0, 0))   # the fixture manifest's first phase start


def utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".100000000Z"


def node_log(certified_warmup, certified_mixed, n=60):
    """logfmt lines: <n> proposals per phase, 5 s apart; the first <certified_*> of each reach quorum."""
    lines, rnd = [], 0
    for start, certified in ((T0, certified_warmup), (T0 + 600, certified_mixed)):
        for k in range(n):
            rnd += 1
            t = start + 5 + 5 * k
            lines.append('ts=%s level=info target=consensus::metrics message="header proposed" round=%d epoch=1 '
                         'num_batches=1 num_parents=7' % (utc(t), rnd))
            if k < certified:
                lines.append('ts=%s level=info target=consensus::metrics message="quorum reached" round=%d epoch=1 '
                             'voting_power=7 quorum_threshold=7 num_votes=7' % (utc(t + 1), rnd))
    return "\n".join(lines) + "\n"


def gz(text):
    return gzip.compress(text.encode())


class FakeFleet(unittest.TestCase):
    """Three fake nodes, their logs in results/<run>/logs, GCP and the node side as described above."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="certification-")
        self.root = Path(self._tmp.name)
        self.results = self.root / "results" / RUN
        self.logs = self.results / "logs"
        self.logs.mkdir(parents=True)
        self.manifest = self.results / "manifest.json"
        shutil.copyfile(str(FIX / "manifest.json"), str(self.manifest))
        self.v2_log = node_log(60, 0)
        for inst, text in ((V1, node_log(60, 60)), (V2, self.v2_log), (V3, node_log(0, 0))):
            (self.logs / ("%s-telcoin.log.gz" % inst)).write_bytes(gz(text))
            (self.logs / ("%s-unit-stdout.log.gz" % inst)).write_bytes(gz(text))   # same lines: counted once
        # An earlier saved log, already pulled: never sent again.
        (self.logs / ("%s-telcoin-pre-step9-20261006T055000Z.log.gz" % V2)).write_bytes(gz("pre-step9\n"))
        (self.logs / ("%s-blast-run-x.log" % V2)).write_text("not a node log\n")
        # GCP and the nodes.
        self.bin = self.root / "bin"
        self.state = self.root / "state"
        self.nodes = self.state / "nodes"
        self.bin.mkdir()
        self.nodes.mkdir(parents=True)
        for name, src in (("gcloud", TEARDOWN_FIX / "fake-gcloud.py"), ("perl", TEARDOWN_FIX / "stub-perl.sh"),
                          ("sudo", FIX / "stub-sudo.sh"), ("docker", FIX / "stub-docker.sh")):
            shutil.copyfile(str(src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.set_instances(V1, V2, V3)
        node_dir = self.nodes / V2
        node_dir.mkdir()
        (node_dir / "telcoin-pre-step9-20261006T055000Z.log.gz").write_bytes(gz("pre-step9\n"))
        (self.nodes / (V2 + ".container")).write_text("the container log of v02 at the snapshot\n" + self.v2_log)

    def tearDown(self):
        self._tmp.cleanup()

    def set_instances(self, *names):
        zones = dict(zip((V1, V2, V3), ("us-west2-a", "europe-west2-b", "us-west2-a")))
        (self.state / "instances.json").write_text(json.dumps([
            {"name": n, "zone": "projects/%s/zones/%s" % (PROJECT, zones[n]), "id": str(100 + i), "status": "RUNNING"}
            for i, n in enumerate(names)]))

    def run_lib(self, body, apply=True, **extra):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.root), "FAKE_ROOT": str(self.state),
               "BENCH_APPLY": "1" if apply else "0", "BENCH_DIR": str(BENCH), "BENCH_RESULTS_DIR": str(self.results),
               "BENCH_RUN_ID": RUN, "PROJECT_ID": PROJECT, "FAKE_NODE_LOG_DIR": "/var/lib/bench-logs",
               "BENCH_IAP_RETRIES": "1"}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        script = PRELUDE + 'L="$1"; M="$2"\n' + body + "\n"
        return subprocess.run(["bash", "-c", script, "t", str(self.logs), str(self.manifest)], env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=120)

    def record(self, **extra):
        p = self.run_lib('bench_certification_record "$L" "$M"', **extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def snapshot(self, **extra):
        p = self.run_lib('bench_cert_failures_snapshot "$L" "$M"', **extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def m(self):
        return json.loads(self.manifest.read_text())

    def ssh_calls(self):
        p = self.state / "ssh.log"
        return [line.split("\t", 1) for line in p.read_text().splitlines()] if p.exists() else []

    def gcloud_calls(self):
        p = self.state / "calls.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def files(self):
        return {p.relative_to(self.results).as_posix(): p.read_bytes() for p in self.results.rglob("*") if p.is_file()}


@unittest.skipUnless(shutil.which("jq") and shutil.which("python3") and shutil.which("tar"), "needs jq, python3 and tar")
class CertificationTests(FakeFleet):
    # ------------------------------------------------------------------ record

    def test_record_fills_certification_and_failures(self):
        p = self.record()
        m = self.m()
        self.assertEqual(sorted(m["certification"]), [V1, V2], "the observer is never judged")
        self.assertEqual(list(m["certification"][V2]), ["phase warmup", "phase mixed", "run"])
        self.assertEqual(m["certification"][V2]["phase mixed"], {
            "proposed": 60, "certified": 0, "rate_pct": 0.0, "own_cert_share_pct": None,
            "own_leader_share_pct": None, "not_committed_pct": None})
        self.assertEqual(m["certification"][V2]["run"]["rate_pct"], 50.0)
        self.assertEqual([m["certification"][V1][w]["rate_pct"] for w in m["certification"][V1]], [100.0] * 3)
        self.assertEqual(m["cert_failures"], [{
            "inst": V2, "window": "phase mixed", "rate_pct": 0.0, "proposed": 60, "certified": 0,
            "windows": ["phase mixed", "run"], "logs": []}])
        meta = m["certification_meta"]
        self.assertEqual((meta["fail_below_pct"], meta["min_proposed"], meta["source"]),
                         (90, 50, "analysis/certification.json"))
        self.assertEqual(meta["windows"], ["phase warmup", "phase mixed", "run"])
        self.assertRegex(meta["recorded_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        raw = json.loads((self.results / "analysis" / "certification.json").read_text())
        self.assertEqual(raw["windows"][1]["nodes"][V2]["quorum"], 0)
        self.assertIn(V3, raw["nodes"], "the raw report keeps every node the tool read")
        self.assertIn("✗ %s: 0.0 %% of 60 own headers certified in phase mixed (below 90 %% in: phase mixed, run)" % V2,
                      p.stdout)
        self.assertIn("✓ %s: at or above 90 %% in every window it was judged in (lowest 100.0 %% in phase warmup)" % V1, p.stdout)
        self.assertNotIn(V3, p.stdout)
        self.assertFalse([f for f in self.files() if os.path.basename(f).startswith(".")], "no temp file left")

    def test_threshold_knob(self):
        self.record(BENCH_CERT_FAIL_PCT="0")
        m = self.m()
        self.assertEqual((m["cert_failures"], m["certification_meta"]["fail_below_pct"]), ([], 0))
        self.assertEqual(sorted(m["certification"]), [V1, V2])
        self.record(BENCH_CERT_FAIL_PCT="40")
        self.assertEqual([(f["inst"], f["windows"]) for f in self.m()["cert_failures"]], [(V2, ["phase mixed"])])
        p = self.record(BENCH_CERT_FAIL_PCT="ninety")
        self.assertIn("BENCH_CERT_FAIL_PCT='ninety' is not an integer from 0 to 100 — using 90", p.stderr)
        self.assertEqual(self.m()["certification_meta"]["fail_below_pct"], 90)
        self.assertEqual(self.m()["cert_failures"][0]["windows"], ["phase mixed", "run"])

    def test_too_few_proposals_are_not_judged(self):
        # 24 per phase, 48 over the run: no window reaches 50 proposals.
        for inst in (V1, V2):
            for kind in ("telcoin", "unit-stdout"):
                (self.logs / ("%s-%s.log.gz" % (inst, kind))).write_bytes(gz(node_log(0, 0, n=24)))
        p = self.record()
        self.assertEqual(self.m()["cert_failures"], [])
        self.assertEqual(self.m()["certification"][V2]["run"]["proposed"], 48)
        self.assertIn("- %s: fewer than 50 headers proposed in every window — not judged" % V2, p.stdout)
        # 49 per phase: only the run window (98) is judged.
        for kind in ("telcoin", "unit-stdout"):
            (self.logs / ("%s-%s.log.gz" % (V2, kind))).write_bytes(gz(node_log(0, 0, n=49)))
        self.record()
        self.assertEqual([(f["inst"], f["windows"]) for f in self.m()["cert_failures"]], [(V2, ["run"])])

    def test_failures_never_stop_the_caller(self):
        before = self.manifest.read_bytes()
        script = 'bench_certification_record "$L" "$M"; bench_cert_failures_snapshot "$L" "$M"; echo AFTER'
        # cert-rate.py exits non-zero: a phase whose time does not parse.
        m = self.m()
        m["phases"][0]["start"] = "yesterday"
        self.manifest.write_text(json.dumps(m))
        bad = self.manifest.read_bytes()
        p = self.run_lib(script)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("AFTER", p.stdout)
        self.assertIn("certification: cert-rate.py failed (exit 1) — not recorded", p.stderr)
        self.assertEqual(self.manifest.read_bytes(), bad)
        self.assertFalse((self.results / "analysis" / "certification.json").exists())
        # No phase yet, and no validator log yet (the collect before any teardown pull).
        self.manifest.write_bytes(before)
        m = self.m()
        m["phases"] = []
        self.manifest.write_text(json.dumps(m))
        p = self.run_lib(script)
        self.assertEqual((p.returncode, "AFTER" in p.stdout), (0, True))
        self.assertIn("has no phases or param_arms yet", p.stderr)
        self.manifest.write_bytes(before)
        for f in self.logs.glob("bench-validator-*.log.gz"):
            f.unlink()
        p = self.run_lib(script)
        self.assertEqual((p.returncode, "AFTER" in p.stdout), (0, True))
        self.assertIn("    certification: deferred to the teardown (node logs are pulled there)\n", p.stdout)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertEqual(self.ssh_calls(), [])

    def test_rerun_merges_by_instance(self):
        self.record()
        self.snapshot()
        first = self.m()
        self.assertEqual(len(first["cert_failures"][0]["logs"]), 3)
        self.record()
        second = self.m()
        self.assertEqual(second["cert_failures"], first["cert_failures"], "the logs still on disk are kept")
        self.assertEqual(second["certification"], first["certification"])
        self.record()
        self.assertEqual(self.m()["cert_failures"], first["cert_failures"])

    def test_merge_drops_a_node_that_passes_now_and_keeps_the_rest(self):
        m = self.m()
        m["cert_failures"] = [
            {"inst": V1, "window": "phase mixed", "rate_pct": 10.0, "logs": ["logs/%s-telcoin.log.gz" % V1]},
            {"inst": V2, "window": "phase warmup", "rate_pct": 1.0,
             "logs": ["logs/%s-unit-stdout.log.gz" % V2, "logs/%s-telcoin-cert-fail-20261006T000000Z.log.gz" % V2]},
            {"inst": "bench-validator-09", "window": "run", "rate_pct": 5.0,
             "logs": ["logs/%s-telcoin.log.gz" % V1, "logs/gone.log.gz"]},
            {"node": "hand-written", "logs": ["logs/whatever.log.gz"]}]
        self.manifest.write_text(json.dumps(m))
        p = self.record()
        cf = self.m()["cert_failures"]
        self.assertEqual(cf[0], {"inst": V2, "window": "phase mixed", "rate_pct": 0.0, "proposed": 60, "certified": 0,
                                 "windows": ["phase mixed", "run"], "logs": ["logs/%s-unit-stdout.log.gz" % V2]})
        self.assertEqual(cf[1], {"node": "hand-written", "logs": ["logs/whatever.log.gz"]}, "not ours: untouched")
        self.assertEqual(cf[2], {"inst": "bench-validator-09", "window": "run", "rate_pct": 5.0,
                                 "logs": ["logs/%s-telcoin.log.gz" % V1]}, "not judged now: kept, logs cut to disk")
        self.assertEqual(len(cf), 3)
        self.assertIn("- %s: no longer below 90 %% — its cert_failures entry is dropped" % V1, p.stdout)
        self.assertTrue(any(n.startswith("certification: %s no longer below 90 %%" % V1) for n in self.m()["notes"]))
        self.assertIn("✗ bench-validator-09: kept from an earlier record (not in this report): 5.0 % in run", p.stdout)

    # ------------------------------------------------------------------ snapshot

    def test_snapshot_saves_pulls_and_lists_the_logs(self):
        self.record()
        p = self.snapshot()
        cf = self.m()["cert_failures"]
        logs = cf[0]["logs"]
        self.assertEqual(len(logs), 3, logs)
        snap = [x for x in logs if SNAP_RE.match(x)]
        self.assertEqual(len(snap), 1, logs)
        self.assertEqual(sorted(set(logs) - set(snap)),
                         ["logs/%s-telcoin.log.gz" % V2, "logs/%s-unit-stdout.log.gz" % V2])
        # The snapshot is the container log as the node had it, saved there and pulled here.
        body = gzip.decompress((self.results / snap[0]).read_bytes()).decode()
        self.assertTrue(body.startswith("the container log of v02 at the snapshot\n"))
        on_node = sorted(f.name for f in (self.nodes / V2).iterdir())
        self.assertEqual(on_node, sorted(["telcoin-pre-step9-20261006T055000Z.log.gz", snap[0][len("logs/" + V2 + "-"):]]))
        # Only the failing node is reached: one save, one pull that skips what logs/ holds already.
        calls = self.ssh_calls()
        self.assertEqual([c[0] for c in calls], [V2, V2])
        self.assertIn("telcoin-cert-fail-", calls[0][1])
        self.assertIn("telcoin-pre-step9-20261006T055000Z.log.gz", calls[1][1])
        self.assertEqual(len(list(self.logs.glob(V2 + "-telcoin-pre-step9-*"))), 1, "not pulled twice")
        describes = [c for c in self.gcloud_calls() if c["argv"][:3] == ["compute", "instances", "describe"]]
        self.assertEqual([c["argv"][3] for c in describes], [V2])
        self.assertEqual(describes[0]["stdin"], "")
        self.assertIn("60 gcloud", (self.state / "alarms").read_text())
        self.assertIn("✓ %s: snapshot %s; 3 log(s) listed in cert_failures[].logs" % (V2, snap[0]), p.stdout)
        # The local gate now requires all three, and passes.
        g = self.run_lib('bench_local_gate_check')
        self.assertEqual(g.returncode, 0, g.stdout)
        self.assertIn("manifest.cert_failures logs", g.stdout)
        # The INDEX rows for what this wrote.
        k = self.run_lib('_bench_index_kind "$1"; _bench_index_kind analysis/certification.json'.replace('"$1"', snap[0]))
        rows = k.stdout.splitlines()
        self.assertTrue(rows[0].startswith("16|logs/<node>-telcoin-cert-fail-<UTC>.log.gz|"), rows[0])
        self.assertTrue(rows[1].startswith("04|analysis/certification.json|"), rows[1])

    def test_gone_node_lists_its_logs_on_disk_and_notes_it(self):
        self.record()
        self.set_instances(V1)
        p = self.snapshot()
        cf = self.m()["cert_failures"][0]
        self.assertEqual(cf["logs"], ["logs/%s-telcoin.log.gz" % V2, "logs/%s-unit-stdout.log.gz" % V2])
        self.assertEqual(self.ssh_calls(), [])
        self.assertIn("⚠ %s: instance gone — no snapshot; 2 log(s) on disk listed" % V2, p.stdout)
        self.assertTrue(any("certification: %s: instance gone" % V2 in n for n in self.m()["notes"]))

    def test_failed_save_lists_the_logs_on_disk(self):
        self.record()
        (self.nodes / (V2 + ".container")).unlink()   # no telcoin container on the node
        p = self.snapshot()
        self.assertEqual(self.m()["cert_failures"][0]["logs"],
                         ["logs/%s-telcoin.log.gz" % V2, "logs/%s-unit-stdout.log.gz" % V2])
        self.assertEqual(len(self.ssh_calls()), 1, "no pull after a failed save")
        self.assertIn("its container log could not be saved", p.stdout)

    def test_failed_pull_leaves_the_snapshot_required(self):
        self.record()
        p = self.snapshot(FAKE_SSH_FAIL="tar -cf")
        logs = self.m()["cert_failures"][0]["logs"]
        snap = [x for x in logs if SNAP_RE.match(x)]
        self.assertEqual(len(snap), 1, logs)
        self.assertFalse((self.results / snap[0]).exists())
        self.assertIn("is saved on the node but not pulled — the local gate requires %s" % snap[0], p.stderr)
        self.assertIn("✗ %s: snapshot %s is on the node only; listed with 3 log(s)" % (V2, snap[0]), p.stdout)
        g = self.run_lib('bench_local_gate_check')
        self.assertEqual(g.returncode, 1)
        self.assertIn("✗ missing or empty: %s (manifest.cert_failures)" % snap[0], g.stdout)
        # A re-run pulls what the node still holds; the gate passes.
        self.record()
        self.snapshot()
        self.assertEqual(self.run_lib('bench_local_gate_check').returncode, 0)

    # ------------------------------------------------------------------ rotated unit logs, glob, re-runs

    def split_v2(self):
        """v02's record as logrotate leaves it: warmup in telcoin.log.1 (pulled as unit-stdout.rotated-1),
        mixed in the live unit file and the container log; an older generation pulled beside a file of
        that name already here (the -<UTC>.rotated-<N> form); a rotated stderr generation."""
        lines = self.v2_log.splitlines(True)
        warmup, mixed = "".join(lines[:120]), "".join(lines[120:])
        for name, text in (("unit-stdout.rotated-1", warmup), ("unit-stdout", mixed), ("telcoin", mixed),
                           ("unit-stdout-20261104T003616Z.rotated-2", "ts=2026-10-06T05:00:00Z earlier\n"),
                           ("unit-stderr.rotated-1", "an error\n")):
            (self.logs / ("%s-%s.log.gz" % (V2, name))).write_bytes(gz(text))

    def test_rotated_unit_logs_are_listed_for_a_failing_validator(self):
        self.split_v2()
        self.record()
        cert = self.m()["certification"][V2]
        self.assertEqual((cert["phase warmup"]["proposed"], cert["phase warmup"]["rate_pct"]), (60, 100.0),
                         "warmup is read from the rotated generation")
        self.assertEqual((cert["phase mixed"]["proposed"], cert["phase mixed"]["certified"]), (60, 0))
        p = self.snapshot()
        logs = self.m()["cert_failures"][0]["logs"]
        snap = [x for x in logs if SNAP_RE.match(x)]
        self.assertEqual(len(snap), 1, logs)
        self.assertEqual(sorted(set(logs) - set(snap)), [
            "logs/%s-telcoin.log.gz" % V2, "logs/%s-unit-stdout-20261104T003616Z.rotated-2.log.gz" % V2,
            "logs/%s-unit-stdout.log.gz" % V2, "logs/%s-unit-stdout.rotated-1.log.gz" % V2])
        self.assertIn("✓ %s: snapshot %s; 5 log(s) listed in cert_failures[].logs: current-container log, "
                      "1 saved log(s), unit stdout, 2 rotated unit stdout log(s)\n" % (V2, snap[0]), p.stdout)
        # The local gate requires every listed log, the rotated ones included.
        (self.logs / ("%s-unit-stdout.rotated-1.log.gz" % V2)).unlink()
        g = self.run_lib('bench_local_gate_check')
        self.assertEqual(g.returncode, 1)
        self.assertIn("✗ missing or empty: logs/%s-unit-stdout.rotated-1.log.gz (manifest.cert_failures)" % V2, g.stdout)

    def test_rotated_names_are_known_to_the_name_helpers_and_the_index(self):
        stamped = "%s-unit-stdout-20261104T003616Z.rotated-2.log.gz" % V2
        p = self.run_lib('_bench_unstamp_names "$L/%s" %s-unit-stderr.rotated-1.log.gz %s-telcoin-20261104T003616Z.log.gz'
                         % (stamped, V2, V2))
        self.assertEqual(p.stdout.splitlines(), ["%s-unit-stdout.rotated-2.log.gz" % V2,
                                                 "%s-unit-stderr.rotated-1.log.gz" % V2, "%s-telcoin.log.gz" % V2])
        p = self.run_lib('_bench_log_sources_of %s %s-unit-stdout.rotated-1.log.gz %s %s-unit-stderr.rotated-3.log.gz '
                         '%s-unit-stdout.log.gz' % (V2, V2, stamped, V2, V2))
        self.assertEqual(p.stdout, "unit stdout, 2 rotated unit stdout log(s), 1 rotated unit stderr log(s)\n")
        self.split_v2()
        p = self.run_lib('_bench_cert_logs_here "$L" %s' % V2)
        self.assertEqual(sorted(os.path.basename(x) for x in p.stdout.split()), sorted([
            "%s-telcoin.log.gz" % V2, stamped, "%s-unit-stdout.log.gz" % V2, "%s-unit-stdout.rotated-1.log.gz" % V2]))
        rows = self.run_lib(" ".join('_bench_index_kind %s;' % f for f in (
            "logs/%s" % stamped, "logs/%s-unit-stderr.rotated-1.log.gz" % V2, "logs/%s-unit-stdout.log.gz" % V2,
            "logs/%s.logspan" % V2, "last-deploy.status", "zones.env", "logs/create-instances-20261104T003616Z.log",
            "logs/keygen-20261104T003616Z.log", "logs/create-bench-blast-1.log"))).stdout.splitlines()
        groups = [r.split("|")[1] for r in rows]
        self.assertEqual(groups[:3], ["logs/<node>-unit-{stdout,stderr}.rotated-<N>.log.gz"] * 2
                         + ["logs/<node>-unit-{stdout,stderr}.log.gz"])
        self.assertEqual(groups[3:], ["logs/<node>.logspan", "last-deploy.status", "zones.env",
                                      "logs/create-instances-<UTC>.log", "logs/keygen-<UTC>.log", "logs/create-<vm>.log"])
        self.assertFalse([r for r in rows if r.startswith("99|")], rows)

    def test_record_reads_the_unit_logs_only_by_default(self):
        # A container log holding 60 more proposals of v01 that no unit file has: not read by default.
        extra = node_log(0, 0).replace("round=", "round=9")
        (self.logs / ("%s-telcoin.log.gz" % V1)).write_bytes(gz(node_log(60, 60) + extra))
        self.record()
        self.assertEqual(self.m()["certification"][V1]["run"]["proposed"], 120)
        self.record(BENCH_CERT_LOG_GLOB="bench-validator-*.log.gz")
        self.assertEqual(self.m()["certification"][V1]["run"]["proposed"], 240)
        # No unit file at all: nothing to read with the default glob, so nothing is recorded.
        for f in self.logs.glob("bench-validator-*-unit-stdout*.log.gz"):
            f.unlink()
        p = self.record()
        self.assertIn("certification: no validator log in %s yet (the teardown pulls them; glob "
                      "bench-validator-*-unit-stdout*.log.gz) — not recorded" % self.logs, p.stderr)
        p = self.run_lib('bench_certification_record "$L" "$M"', apply=False)
        self.assertIn("--format json --node-glob 'bench-validator-*-unit-stdout*.log.gz' > ", p.stdout)

    def test_local_analysis_skip_knob_and_glob(self):
        a = self.results / "analysis" / "cert-rate.md"
        p = self.run_lib("bench_local_analysis", BENCH_TEARDOWN_SKIP_ANALYSIS="1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("- skipped (BENCH_TEARDOWN_SKIP_ANALYSIS=1)", p.stdout)
        self.assertFalse((self.results / "analysis").exists())
        p = self.run_lib("bench_local_analysis", apply=False)
        self.assertIn("+ python3 %s/tools/cert-rate.py --logs %s --windows %s/manifest.json --node-glob "
                      "'bench-validator-*-unit-stdout*.log.gz' > " % (BENCH, self.logs, self.results), p.stdout)
        p = self.run_lib("bench_local_analysis")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("✓ %s" % a, p.stdout)
        self.assertIn(V2, a.read_text())

    def write_marker(self, inst, inst_id, *names):
        lines = ["tn-bench-pulled/v2", "instance " + inst, "id %s" % inst_id, "created 2026-10-06T05:00:00Z",
                 "run " + RUN, "pulled " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources test"]
        lines += ["file %d %s" % ((self.logs / n).stat().st_size, n) for n in names]
        (self.logs / ("%s.pulled" % inst)).write_text("\n".join(lines + ["end"]) + "\n")

    def test_a_vouched_snapshot_is_not_taken_again(self):
        self.record()
        self.snapshot()
        first = self.m()["cert_failures"][0]["logs"]
        snap = [x for x in first if SNAP_RE.match(x)][0]
        saves = len([c for c in self.ssh_calls() if "docker logs telcoin" in c[1]])
        # The teardown re-run's pull brought it in as a saved log, and its marker (this instance's id) vouches for it.
        self.write_marker(V2, 101, os.path.basename(snap), "%s-telcoin.log.gz" % V2)
        p = self.snapshot()
        self.assertIn("- %s: %s is this instance's snapshot (instance 101; a pull marker vouches for it) — not taken again"
                      % (V2, snap), p.stdout)
        self.assertIn("✓ %s: snapshot %s; 3 log(s) listed" % (V2, snap), p.stdout)
        self.assertEqual(len([c for c in self.ssh_calls() if "docker logs telcoin" in c[1]]), saves, "no new save")
        self.assertEqual(self.m()["cert_failures"][0]["logs"], first)
        # A marker of another instance of that name vouches for nothing here: a new snapshot.
        time.sleep(1.1)
        self.write_marker(V2, 999, os.path.basename(snap))
        p = self.snapshot()
        self.assertNotIn("not taken again", p.stdout)
        self.assertEqual(len([c for c in self.ssh_calls() if "docker logs telcoin" in c[1]]), saves + 1)
        self.assertEqual(len([x for x in self.m()["cert_failures"][0]["logs"] if SNAP_RE.match(x)]), 2)

    def test_dry_run_changes_nothing(self):
        self.record()
        before = self.files()
        p = self.run_lib('bench_certification_record "$L" "$M"; bench_cert_failures_snapshot "$L" "$M"', apply=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("+ python3 %s/tools/cert-rate.py --logs %s --windows %s --format json" % (BENCH, self.logs, self.manifest),
                      p.stdout)
        self.assertIn("+ %s: if it still exists, bench_save_node_log 1 cert-fail" % V2, p.stdout)
        self.assertEqual(self.files(), before)
        self.assertEqual((self.ssh_calls(), self.gcloud_calls()), ([], []))

    def test_summary_line(self):
        p = self.run_lib('bench_certification_summary "$M"')
        self.assertEqual(p.stdout.strip(), "not recorded (no validator log or phase when it ran)")
        self.record()
        p = self.run_lib('bench_certification_summary "$M"')
        self.assertEqual(p.stdout.strip(),
                         "1 validator(s) below 90 %%: %s 0.0 %% in phase mixed; logs in manifest.cert_failures" % V2)
        self.record(BENCH_CERT_FAIL_PCT="0")
        p = self.run_lib('bench_certification_summary "$M"')
        self.assertEqual(p.stdout.strip(), "no validator below 0 % of its own headers certified (2 validator(s))")


@unittest.skipUnless(shutil.which("jq") and shutil.which("python3") and shutil.which("tar"), "needs jq, python3 and tar")
@unittest.skipUnless((BENCH / "pull-lib.sh").exists(), "needs benchmark/pull-lib.sh (unit U-H1)")
class NodePullTests(FakeFleet):
    """bench_pull_node_logs / _bench_pull_node on one fake node, with pull-lib.sh's real span and rotated
    sessions: span first, then container, saved, unit and rotated logs, then the marker. The node's unit
    files live in a directory of the test (BENCH_NODE_UNIT_LOGS points there)."""

    def setUp(self):
        super().setUp()
        self.unit = self.state / "unit"
        self.unit.mkdir()
        (self.unit / "telcoin.log").write_text("ts=2026-10-06T06:20:00Z live line\n")
        (self.unit / "telcoin.log.1").write_text("ts=2026-10-06T06:10:00Z generation 1\n")
        (self.unit / "telcoin.log.2.gz").write_bytes(gz("ts=2026-10-06T06:00:00Z generation 2\n"))
        (self.unit / "telcoin-error.log").write_text("an error\n")
        self.dest = self.root / "pulled"

    def pull(self, **extra):
        body = ('INSTANCE_NAMES=(%s); ZONES=(europe-west2-b)\n'
                'BENCH_NODE_UNIT_LOGS="stdout:%s/telcoin.log stderr:%s/telcoin-error.log"\n'
                'rc=0; bench_pull_node_logs "%s" || rc=$?; echo "RC=${rc}"' % (V2, self.unit, self.unit, self.dest))
        p = self.run_lib(body, **extra)
        return p, int(re.search(r"^RC=(\d+)$", p.stdout, re.M).group(1))

    def marker_files(self):
        m = self.dest / (V2 + ".pulled")
        return sorted(line.split()[2] for line in m.read_text().splitlines() if line.startswith("file ")) if m.exists() else None

    def test_every_source_lands_and_the_marker_lists_it(self):
        p, rc = self.pull()
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        span = (self.dest / (V2 + ".logspan")).read_text()
        self.assertIn("LOGSPAN %s stream=stdout gen=0 " % V2, span)
        self.assertIn("LOGSPAN %s stream=stdout gen=2 " % V2, span)
        logs = ["%s-%s.log.gz" % (V2, n) for n in (
            "telcoin", "telcoin-pre-step9-20261006T055000Z", "unit-stderr", "unit-stdout",
            "unit-stdout.rotated-1", "unit-stdout.rotated-2")]
        self.assertEqual(sorted(f.name for f in self.dest.glob("*.log.gz")), sorted(logs))
        self.assertEqual(self.marker_files(), sorted(logs))
        read = lambda n: gzip.decompress((self.dest / ("%s-%s.log.gz" % (V2, n))).read_bytes()).decode()
        self.assertEqual(read("unit-stdout"), "ts=2026-10-06T06:20:00Z live line\n")
        self.assertEqual(read("unit-stdout.rotated-1"), "ts=2026-10-06T06:10:00Z generation 1\n")
        self.assertEqual((self.dest / ("%s-unit-stdout.rotated-2.log.gz" % V2)).read_bytes(),
                         (self.unit / "telcoin.log.2.gz").read_bytes(), "a .N.gz generation is the node's own bytes")
        self.assertTrue(read("telcoin").startswith("the container log of v02 at the snapshot\n"))
        self.assertIn("✓ %s: current-container log, 1 saved log(s), unit stdout, unit stderr, "
                      "2 rotated unit stdout log(s)" % V2, p.stdout)
        sessions = [c[1] for c in self.ssh_calls()]
        self.assertTrue(sessions[0].startswith("stdin # bench-pull: span"), sessions)
        self.assertTrue(sessions[-1].startswith("stdin # bench-pull: rotated"), sessions)

    def test_a_span_that_answers_nothing_fails_the_node_and_drops_an_old_span(self):
        self.dest.mkdir()
        (self.dest / (V2 + ".logspan")).write_text("LOGSPAN %s stream=stdout gen=0 an earlier pass\n" % V2)
        p, rc = self.pull(FAKE_SSH_EMPTY="# bench-pull: span")
        self.assertEqual(rc, 1, p.stdout)
        self.assertIn("✗ %s: the span session answered nothing" % V2, p.stderr)
        self.assertFalse((self.dest / (V2 + ".logspan")).exists(), "a span of an earlier pull is not read as now")
        self.assertIsNone(self.marker_files(), "no marker")
        self.assertIn("node logs not pulled from: %s" % V2, p.stderr)

    def test_a_failed_rotated_pull_fails_the_node(self):
        p, rc = self.pull(FAKE_SSH_FAIL="# bench-pull: rotated")
        self.assertEqual(rc, 1, p.stdout)
        self.assertIn("✗ %s: rotated unit logs: not all pulled" % V2, p.stderr)
        self.assertIsNone(self.marker_files(), "no marker: the record lacks a generation")
        self.assertFalse(list(self.dest.glob("*rotated*")))

    def test_a_zero_byte_leftover_is_pulled_again_under_its_name(self):
        self.dest.mkdir()
        for n in ("telcoin", "unit-stdout"):
            (self.dest / ("%s-%s.log.gz" % (V2, n))).write_bytes(b"")
        p, rc = self.pull()
        self.assertEqual(rc, 0, p.stdout + p.stderr)
        self.assertGreater((self.dest / ("%s-telcoin.log.gz" % V2)).stat().st_size, 0)
        self.assertEqual(gzip.decompress((self.dest / ("%s-unit-stdout.log.gz" % V2)).read_bytes()).decode(),
                         "ts=2026-10-06T06:20:00Z live line\n")
        self.assertEqual(len(list(self.dest.glob("*.log.gz"))), 6, "no stamped copy beside the leftovers")
        self.assertIn("%s-unit-stdout.log.gz" % V2, self.marker_files())


class CallSiteTests(unittest.TestCase):
    """Where collect and the teardown record the outcome, read from the source."""

    @staticmethod
    def line_of(text, needle):
        for i, line in enumerate(text.splitlines()):
            if needle in line and not line.lstrip().startswith("#"):
                return i
        raise AssertionError("%r not found" % needle)

    def test_teardown_records_after_the_pulls_and_before_the_gate(self):
        evidence = self.line_of(TEARDOWN, "bench_pull_recovery_evidence ")
        # D44: the record reads the prefiltered copy (CERT_LOGS), the snapshots land in the real logs dir.
        prefilter = self.line_of(TEARDOWN, 'if bench_logs_prefilter "${LOG_DIR}" "${PREFILTER_DIR}"; then')
        record = self.line_of(TEARDOWN, 'bench_certification_record "${CERT_LOGS}" "$(bench_manifest)" ||')
        snap = self.line_of(TEARDOWN, 'bench_cert_failures_snapshot "${LOG_DIR}" "$(bench_manifest)" ||')
        gate = self.line_of(TEARDOWN, 'if bench_local_gate_check "${INSTANCE_NAMES[@]}"; then')
        self.assertLess(self.line_of(TEARDOWN, 'bench_pull_node_logs "${LOG_DIR}"'), evidence)
        self.assertLess(evidence, prefilter)
        self.assertLess(prefilter, record)
        self.assertLess(record, snap)
        self.assertLess(snap, gate)
        self.assertLess(gate, self.line_of(TEARDOWN, "bench_certification_summary"))

    def test_collect_records_after_the_analysis_and_before_the_index(self):
        body = shell_function(BLAST, "do_collect")
        analysis = self.line_of(body, "bench_local_analysis")
        record = self.line_of(body, 'bench_certification_record "${BENCH_RESULTS_DIR}/logs" "$(bench_manifest)" ||')
        snap = self.line_of(body, 'bench_cert_failures_snapshot "${BENCH_RESULTS_DIR}/logs" "$(bench_manifest)" ||')
        index = self.line_of(body, "bench_local_index ||")
        self.assertLess(analysis, record)
        self.assertLess(record, snap)
        self.assertLess(snap, index)

    def test_threshold_knob_next_to_the_abort_thresholds(self):
        config = (BENCH / "config.sh").read_text()
        self.assertIn('export BENCH_CERT_FAIL_PCT="${BENCH_CERT_FAIL_PCT:-90}"', config)
        self.assertLess(config.index("BENCH_ABORT_STALL_SECS="), config.index("BENCH_CERT_FAIL_PCT="))


if __name__ == "__main__":
    unittest.main()
