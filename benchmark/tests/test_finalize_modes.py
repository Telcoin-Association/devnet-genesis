"""devnet-finalize.sh's mode flags (bench 3 contracts C1 and C2, mutation anchor M2), fully offline.

Every test runs a copy of devnet-finalize.sh and devnet-lib.sh (TREE) in a sandbox against a
three-node fleet, two validators and one observer (fixtures/finalize/config.sh is CONFIG_FILE).
A fake gcloud (fixtures/finalize/gcloud.py) is first on PATH: it keeps each node's telcoin unit on
disk (installed, ActiveState, UnitFileState, NRestarts, container), answers every probe by its
`# tn-probe: <name>` line, logs each call (argv, stdin, probe arguments) and each unit state change,
and can be told per node to drop ssh (rc 255) N times for one kind of call, fail finalize, leave a
stopped unit `failed`, keep its container running, hang a start-at probe, or report a late start.
A python3 shim (fixtures/finalize/python3.sh) answers the PyYAML check and devnet-network-config.py
validate; the raw-shape half of the gate's network-config check runs for real on
fixtures/finalize/network-config.yaml. Nothing reaches GCP, ssh or a network.

The tests find the scripts and fixtures relative to their own location: check_mutations.py copies
this module and what it reads into a temporary tree laid out like the repo.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
FIX = TESTS / "fixtures" / "finalize"

# Scripts the run sources or hands to python3 (the shim checks that the validator is there),
# relative to the repo root. The real config.sh is not read: CONFIG_FILE is the fixture's.
TREE = ("devnet-finalize.sh", "devnet-lib.sh", "devnet-network-config.py")
INSTS = ("fin-validator-1", "fin-validator-2", "fin-observer-3")   # = fixtures/finalize/config.sh
NODES = ("node1", "node2", "node3")
IMAGE = "registry.example.invalid/tn/node@sha256:" + "a" * 64
FLEET = "node1=validator,node2=validator,node3=observer"

# Per-node gcloud calls, in order, by the fake's kind names.
PHASE_A = ("ready", "scp", "scp", "scp", "stage", "describe", "describe", "finalize", "health")
PHASE_B = ("service", "meta", "meta", "meta", "meta", "network-config", "logs", "runtime")
STAGE = PHASE_A + ("unit", "stop")
WRITES = ("scp", "stage", "finalize", "stop", "start-at")

# Every knob small so a run takes seconds; a test overrides one by name (None = unset = default).
FAST = {"FINALIZE_STABLE_SECS": "0", "FINALIZE_STABLE_POLL_SECS": "1", "FINALIZE_RO_RETRY_SECS": "1",
        "FINALIZE_START_LEAD_SECS": "2", "FINALIZE_START_LAUNCH_GAP_SECS": "0",
        "FINALIZE_START_TIMEOUT_SECS": "20", "FINALIZE_START_SPREAD_WARN_SECS": "10",
        "HEALTH_TIMEOUT_SECS": "3", "HEALTH_POLL_SECS": "1",
        # devnet-lib.sh's own transport retry is off here: these tests model the script's retry logic
        # and count ssh attempts exactly (the lib retry has its own proof, see tasks/lessons.md 2026-11-03).
        "TN_IAP_RETRIES": "0"}
MODES = ("--stage-only", "--start-all", "--defer-start", "--verify")

MARKER_RE = re.compile(r"^COORDINATED_START due=(\d+) nodes=(\d+) started=(\d+) skipped_running=(\d+)"
                       r" spread_secs=(\d+) max_late_secs=(\d+)$")
START_AT_RE = re.compile(r"^START_AT (\S+) due=(\d+) began=(\d+) late_secs=(\d+)$")
FRESH = {"installed": False, "active": "inactive", "enabled": "", "nrestarts": 0,
         "container": False, "image": "", "hostname": ""}


def per_node(kinds, insts=INSTS):
    """[(inst, kind)] for each node in turn, each running <kinds> in order."""
    return [(inst, k) for inst in insts for k in kinds]


def each(kind, insts=INSTS):
    return [(inst, kind) for inst in insts]


class FinalizeCase(unittest.TestCase):
    """One sandbox per test: the scripts, a bin dir (fake gcloud, python3 shim), the fake fleet."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="finalize-modes-test-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        for rel in TREE:
            dst = self.tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / rel), str(dst))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for src, name in (("gcloud.py", "gcloud"), ("python3.sh", "python3")):
            shutil.copyfile(str(FIX / src), str(self.bin / name))
            (self.bin / name).chmod(0o755)
        self.sb = self.root / "fleet"
        for sub in ("state", "faults"):
            (self.sb / sub).mkdir(parents=True)
        # GENESIS_WORKSPACE: the script wants <it>/genesis/{committee,genesis}.yaml, a dir name
        # benchmark/.gitignore keeps out of the fixtures, so the sandbox builds it.
        self.workspace = self.root / "workspace"
        (self.workspace / "genesis").mkdir(parents=True)
        for name in ("committee.yaml", "genesis.yaml"):
            shutil.copyfile(str(FIX / name), str(self.workspace / "genesis" / name))
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.last = None

    def tearDown(self):
        self._tmp.cleanup()

    # --- the fake fleet ---------------------------------------------------------------------

    def node(self, i, **unit):
        state = dict(FRESH, image=IMAGE, hostname=NODES[i])
        state.update(unit)
        (self.sb / "state" / (INSTS[i] + ".json")).write_text(json.dumps(state))

    def staged(self, i):
        """Finalized, then stopped: unit installed, inactive, enabled (what --stage-only leaves)."""
        self.node(i, installed=True, active="inactive", enabled="enabled")

    def running(self, i):
        self.node(i, installed=True, active="active", enabled="enabled", container=True)

    def fault(self, i, **faults):
        (self.sb / "faults" / (INSTS[i] + ".json")).write_text(json.dumps(faults))

    def state(self, i):
        f = self.sb / "state" / (INSTS[i] + ".json")
        out = dict(FRESH)
        if f.exists():
            out.update(json.loads(f.read_text()))
        return out

    def unit(self, i):
        st = self.state(i)
        return st["installed"], st["active"], st["enabled"]

    def jsonl(self, name):
        f = self.sb / name
        if not f.exists():
            return []
        rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        return sorted(rows, key=lambda r: (r.get("seq", 0), r["t"]))

    def calls(self, kind=None, inst=None):
        return [c for c in self.jsonl("calls.jsonl")
                if (kind is None or c["kind"] == kind) and (inst is None or c["inst"] == inst)]

    def pairs(self):
        """(inst, kind) per call, in call order; the start-at calls, which overlap (and begin in any
        order when FINALIZE_START_LAUNCH_GAP_SECS=0), in fleet order within their own slots."""
        out = [(c["inst"], c["kind"]) for c in self.calls()]
        slots = [k for k, (_, kind) in enumerate(out) if kind == "start-at"]
        starts = sorted((out[k] for k in slots), key=lambda pair: INSTS.index(pair[0]))
        for k, pair in zip(slots, starts):
            out[k] = pair
        return out

    def transitions(self):
        return self.jsonl("transitions.jsonl")

    def node_starts(self, inst):
        """How many `systemctl start telcoin` the real start-at text ran on <inst>."""
        return sum(1 for r in self.jsonl("node.jsonl")
                   if r["inst"] == inst and r["argv"] == ["systemctl", "start", "telcoin"])

    def peak_active(self, until_seq=None):
        """The most units active at one moment: the run's starting state, then each state change."""
        active = {INSTS[i] for i in range(3) if self.state_at_start[i]}
        peak = len(active)
        for t in self.transitions():
            if until_seq is not None and t["seq"] > until_seq:
                break
            if t["after"]["active"] == "active":
                active.add(t["inst"])
            else:
                active.discard(t["inst"])
            peak = max(peak, len(active))
        return peak

    def validate_calls(self):
        f = self.sb / "validate.log"
        if not f.exists():
            return []
        return [line.rstrip("\t").split("\t") for line in f.read_text().splitlines() if line]

    # --- the run ----------------------------------------------------------------------------

    def env(self, knobs):
        # Nothing from the developer's shell that the scripts read (FINALIZE_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir),
               "CONFIG_FILE": str(FIX / "config.sh"), "FIN_FIX": str(FIX), "FIN_SB": str(self.sb),
               "FIN_WORKSPACE": str(self.workspace), "FIN_REAL_PYTHON": sys.executable}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        merged = dict(FAST)
        merged.update(knobs)
        for key, value in merged.items():
            if value is not None:
                env[key] = value
        return env

    def finalize(self, *args, **knobs):
        self.state_at_start = [self.state(i)["active"] == "active" for i in range(3)]
        self.last = subprocess.run(["bash", str(self.tree / "devnet-finalize.sh")] + list(args),
                                   cwd=str(self.work), env=self.env(knobs), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True, timeout=300)
        return self.last

    def lines(self, prefix):
        return [line for line in self.last.stdout.splitlines() if line.startswith(prefix)]

    def why(self):
        p = self.last
        if p is None:
            return ""
        out, err = ("\n".join(text.splitlines()[-40:]) for text in (p.stdout, p.stderr))
        return "\nrc %d\n--- stdout (tail)\n%s\n--- stderr (tail)\n%s" % (p.returncode, out, err)

    def assertExit(self, rc):
        self.assertEqual(self.last.returncode, rc, self.why())

    def marker(self):
        found = self.lines("COORDINATED_START")
        self.assertEqual(len(found), 1, "want exactly one COORDINATED_START line" + self.why())
        m = MARKER_RE.match(found[0])
        self.assertIsNotNone(m, "marker grammar (six integer fields): %r" % found[0])
        keys = ("due", "nodes", "started", "skipped_running", "spread_secs", "max_late_secs")
        return dict(zip(keys, (int(v) for v in m.groups())))

    def start_at_lines(self):
        out = []
        for line in self.lines("START_AT "):
            m = START_AT_RE.match(line)
            self.assertIsNotNone(m, "START_AT grammar: %r" % line)
            out.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))))
        return out


class UsageTests(FinalizeCase):
    """C1: a bad command line stops the run (exit 2) before any gcloud call."""

    def refused(self, args, knobs=None, text="usage: ./devnet-finalize.sh"):
        with self.subTest(args=args, knobs=knobs):
            p = self.finalize(*args, **(knobs or {}))
            self.assertExit(2)
            self.assertEqual(self.calls(), [], "a refused run called gcloud")
            self.assertIn(text, p.stderr)

    def test_unknown_option(self):
        for args in (["--bogus"], ["node1", "--bogus"], ["--stage-only", "--stage"], ["--"]):
            self.refused(args)
        self.assertIn("unknown option: --", self.last.stderr)

    def test_verify_with_stage_only(self):
        self.refused(["--verify", "--stage-only"])
        self.assertIn("one mode flag at most: --verify and --stage-only", self.last.stderr)

    def test_two_mode_flags_in_any_order(self):
        for a in MODES:
            for b in MODES:
                self.refused([a, b])
                self.refused(["node1", b, "node2", a])

    def test_unknown_target(self):
        for args in (["node9"], ["--start-all", "fin-validator-9"], ["0", "7"], ["--verify", "node"]):
            self.refused(args, text="unknown target")

    def test_knob_that_is_not_whole_seconds(self):
        for knob, value in (("FINALIZE_START_LEAD_SECS", "abc"), ("FINALIZE_START_LAUNCH_GAP_SECS", "0.5"),
                            ("FINALIZE_START_TIMEOUT_SECS", "-1"), ("FINALIZE_START_SPREAD_WARN_SECS", "10s"),
                            ("FINALIZE_RO_RETRY_SECS", "five")):
            self.refused(["--start-all"], {knob: value}, text="must be whole seconds")
            self.refused([], {knob: value}, text="must be whole seconds")


class DefaultModeTests(FinalizeCase):
    """No flag: HEAD's run (phase A per node, then A1-A5 per node); the read-only retry."""

    def test_no_flag_runs_the_head_sequence(self):
        p = self.finalize()
        self.assertExit(0)
        self.assertEqual(self.pairs(), per_node(PHASE_A) + per_node(PHASE_B))
        self.assertEqual(self.lines("STAGED") + self.lines("PRESTAGED") + self.lines("RUNNING")
                         + self.lines("START_AT") + self.lines("COORDINATED_START"), [])
        self.assertIn("all targeted nodes finalized, started, enabled and verified.", p.stdout)
        self.assertNotIn("mode:", p.stdout)
        # HEAD's readiness gate: no unit-state line in the probe (that is the modes' addition).
        for c in self.calls("ready"):
            self.assertNotIn("systemctl show -p ActiveState", c["cmd"])
            self.assertEqual(c["pargs"], ["/opt/telcoin-node-scripts/setup-node.sh", "telcoin",
                                          "/var/lib/telcoin", "/var/log/telcoin"])
        for inst in INSTS:
            scp = [c["pargs"] for c in self.calls("scp", inst)]
            self.assertEqual([(Path(src).name, dst) for src, dst in scp],
                             [("committee.yaml", "/tmp/committee.yaml"), ("genesis.yaml", "/tmp/genesis.yaml"),
                              ("finalize-parameters.yaml", "/tmp/parameters.yaml")])
            self.assertEqual([c["key"] for c in self.calls("meta", inst)],
                             ["NETWORK", "DOCKER_IMAGE_DIGEST", "DATA_DIR", "NODE_LOG_DIR"])
        for i, inst in enumerate(INSTS):
            fin = self.calls("finalize", inst)[0]["pargs"]
            for flag, value in (("--docker-image", IMAGE), ("--advertised-name", NODES[i]),
                                ("--address", "0x" + str(i + 1) * 40),
                                ("--listener-primary", "/ip4/192.0.2.7/udp/49590/quic-v1"),
                                ("--external-worker", "/ip4/203.0.113.7/udp/49594/quic-v1")):
                self.assertEqual(fin[fin.index(flag) + 1], value, flag)
            self.assertEqual(self.unit(i), (True, "active", "enabled"))
        # The gate and A3 each judged every node's network-config, with the fleet as context.
        checked = self.validate_calls()
        self.assertEqual(len(checked), 6)
        for args in checked:
            self.assertEqual(args[1], "validate")
            self.assertEqual(args[args.index("--nodes") + 1], FLEET)
            self.assertEqual(args[args.index("--hub") + 1], "node1")
        self.assertEqual(sorted(a[a.index("--node") + 1] for a in checked), sorted(NODES * 2))
        self.assertIn('hostname: "node3"', p.stdout)

    def test_retry_off_fails_on_one_dropped_a3_read(self):
        # FINALIZE_RO_RETRY_SECS=0 is HEAD: one ssh 255 on A3 fails the node.
        self.fault(1, fail255={"network-config": 1})
        p = self.finalize("node2", FINALIZE_RO_RETRY_SECS="0")
        self.assertExit(1)
        self.assertEqual(len(self.calls("network-config", INSTS[1])), 1)
        self.assertIn("✗ [node2] A3 network-config: no answer from fin-validator-2 (ssh rc 255)", p.stdout)
        self.assertNotIn("one retry", p.stderr)

    def test_default_retry_survives_one_dropped_a3_read(self):
        self.fault(1, fail255={"network-config": 1})
        p = self.finalize("node2", FINALIZE_RO_RETRY_SECS=None)   # unset: the default, 5 s
        self.assertExit(0)
        a3 = self.calls("network-config", INSTS[1])
        self.assertEqual([c["injected255"] for c in a3], [True, False])
        self.assertGreaterEqual(a3[1]["t"] - a3[0]["t"], 4.5)
        self.assertIn("ssh rc 255 from fin-validator-2; one retry in 5s", p.stderr)
        self.assertEqual(self.pairs(), per_node(PHASE_A, INSTS[1:2])
                         + per_node(PHASE_B[:6] + PHASE_B[5:], INSTS[1:2]))

    def test_unresolvable_external_ip_fails_that_node_only(self):
        # D4: an API fault on node1's external-IP describe fails node1; the run goes on.
        self.fault(0, describe_fails={"external": 1})
        p = self.finalize()
        self.assertEqual(self.pairs(), per_node(PHASE_A[:7], INSTS[:1]) + per_node(PHASE_A, INSTS[1:])
                         + per_node(PHASE_B, INSTS[1:]), "the run stopped at node1's describe" + self.why())
        self.assertExit(1)
        self.assertIn("❌ [node1] could not resolve external IP for the advertised multiaddrs", p.stdout)
        self.assertIn("failed (1):\n  - node1: external IP\n", p.stdout)
        self.assertEqual(self.unit(0), (False, "inactive", ""))


class StageOnlyTests(FinalizeCase):
    """--stage-only: phase A, then the stop; PRESTAGED / RUNNING skips; no phase B."""

    def test_stage_only_stops_each_node_after_finalize(self):
        # M2 anchor (check_mutations.py): the `_defer_stop "${inst}" "${zone}"` call replaced by
        # `true` leaves every node running with no stop call and an empty STAGED observation.
        p = self.finalize("--stage-only")
        self.assertEqual([c["inst"] for c in self.calls("stop")], list(INSTS),
                         "one stop per node, after its finalize" + self.why())
        self.assertEqual(self.lines("STAGED"), ["STAGED %s state=inactive enabled=enabled" % i for i in INSTS])
        self.assertExit(0)
        self.assertEqual(self.pairs(), per_node(STAGE))
        for i in range(3):
            self.assertEqual(self.unit(i), (True, "inactive", "enabled"))
            self.assertFalse(self.state(i)["container"])
        for c in self.calls("stop"):
            self.assertEqual(c["pargs"], ["telcoin"])
            self.assertIn('systemctl stop "$svc"', c["cmd"])
            self.assertIn('systemctl reset-failed "$svc"', c["cmd"])
        for c in self.calls("ready"):   # the skip rules read the unit's state from the gate
            self.assertIn("systemctl show -p ActiveState,SubState,UnitFileState,NRestarts,Result", c["cmd"])
        self.assertIn("finalize --stage-only summary", p.stdout)
        self.assertIn("staged: finalized, then stopped, enabled (3):", p.stdout)

    def test_stage_only_never_has_two_units_active(self):
        self.finalize("--stage-only")
        self.assertExit(0)
        self.assertEqual([(t["inst"], t["kind"]) for t in self.transitions()], per_node(("finalize", "stop")))
        self.assertEqual(self.peak_active(), 1)
        for t in self.transitions():
            want = ("inactive", "active") if t["kind"] == "finalize" else ("active", "inactive")
            self.assertEqual((t["before"]["active"], t["after"]["active"]), want, t)
        # From the call log too: each node's stop comes before the next node's gate.
        seqs = {(c["inst"], c["kind"]): c["seq"] for c in self.calls()}
        for a, b in zip(INSTS, INSTS[1:]):
            self.assertLess(seqs[(a, "stop")], seqs[(b, "ready")])
            self.assertLess(seqs[(a, "finalize")], seqs[(a, "stop")])

    def test_rerun_reports_prestaged_and_stops_nothing(self):
        self.finalize("--stage-only")
        self.assertExit(0)
        for name in ("calls.jsonl", "transitions.jsonl"):
            (self.sb / name).unlink()
        p = self.finalize("--stage-only")
        self.assertExit(0)
        self.assertEqual(self.lines("PRESTAGED"), ["PRESTAGED %s" % i for i in INSTS])
        self.assertEqual(self.lines("STAGED"), [])
        self.assertEqual(self.pairs(), each("ready"))
        self.assertEqual(self.transitions(), [])
        self.assertIn("prestaged, skipped (3):", p.stdout)

    def test_running_node_is_reported_and_never_stopped(self):
        self.running(1)
        p = self.finalize("--stage-only")
        self.assertExit(0)
        self.assertEqual(self.lines("RUNNING"), ["RUNNING fin-validator-2"])
        self.assertIn("already running on fin-validator-2", p.stderr)
        self.assertIn("quorum may have formed", p.stderr)
        self.assertEqual([c["kind"] for c in self.calls(inst=INSTS[1])], ["ready"])
        self.assertEqual(self.unit(1), (True, "active", "enabled"))
        self.assertEqual(self.lines("STAGED"), ["STAGED %s state=inactive enabled=enabled" % i
                                                for i in (INSTS[0], INSTS[2])])
        self.assertIn("running, skipped, NOT stopped (1):", p.stdout)

    def test_stop_that_leaves_the_unit_failed_is_cleared_by_reset_failed(self):
        for i in range(3):
            self.fault(i, stop_leaves_failed=True)
        self.finalize("--stage-only")
        self.assertExit(0)
        self.assertEqual(len(self.lines("STAGED")), 3)
        for i in range(3):
            self.assertEqual(self.unit(i), (True, "inactive", "enabled"))

    def test_stop_without_reset_failed_leaves_failed_and_fails_the_node(self):
        # The same node behaviour against a copy of the script whose stop probe has no
        # reset-failed: the unit stays `failed`, and the stop's own check refuses it.
        script = self.tree / "devnet-finalize.sh"
        text = script.read_text()
        line = 'systemctl reset-failed "$svc" >/dev/null 2>&1; echo "reset_rc=$?"\n'
        self.assertEqual(text.count(line), 1, "the stop probe's reset-failed line moved")
        script.write_text(text.replace(line, 'echo "reset_rc=none"\n'))
        self.fault(0, stop_leaves_failed=True)
        p = self.finalize("--stage-only")
        self.assertExit(1)
        self.assertIn("❌ [node1] stop: after stop: ActiveState=failed SubState=failed Result=exit-code"
                      " UnitFileState=enabled", p.stdout)
        self.assertEqual(self.unit(0), (True, "failed", "enabled"))
        self.assertEqual(self.lines("STAGED"), ["STAGED %s state=inactive enabled=enabled" % i
                                                for i in INSTS[1:]])
        self.assertEqual(len(self.calls("stop", INSTS[0])), 1)

    def test_restarted_unit_after_finalize_is_not_stopped(self):
        # The stop needs ActiveState=active and NRestarts=0 first; a node that fails after
        # finalize started it is left as it is.
        self.fault(1, nrestarts_after_finalize=1)
        p = self.finalize("--stage-only")
        self.assertExit(1)
        self.assertIn("❌ [node2] after finalize: ActiveState=active NRestarts=1 (want active, 0); not stopped",
                      p.stdout)
        self.assertEqual([c["kind"] for c in self.calls(inst=INSTS[1])], list(PHASE_A) + ["unit"])
        self.assertEqual(self.unit(1), (True, "active", "enabled"))
        self.assertEqual(len(self.lines("STAGED")), 2)

    def test_dropped_gate_and_stop_are_retried_once(self):
        # The gate is read-only and the stop is safe to run twice: both go through the retry.
        self.fault(0, fail255={"ready": 1, "stop": 1})
        p = self.finalize("--stage-only", "node1")
        self.assertExit(0)
        self.assertEqual([c["kind"] for c in self.calls()], ["ready"] + list(STAGE) + ["stop"])
        self.assertEqual([c["injected255"] for c in self.calls("stop")], [True, False])
        self.assertEqual(p.stderr.count("ssh rc 255 from fin-validator-1; one retry in 1s"), 2)
        self.assertEqual(self.lines("STAGED"), ["STAGED fin-validator-1 state=inactive enabled=enabled"])

    def test_container_still_running_after_stop_fails_the_node(self):
        self.fault(2, container_survives_stop=True)
        p = self.finalize("--stage-only")
        self.assertExit(1)
        self.assertIn("❌ [node3] stop: after stop: ActiveState=inactive", p.stdout)
        self.assertIn("container-running=true", p.stdout)
        self.assertEqual(self.lines("STAGED"), ["STAGED %s state=inactive enabled=enabled" % i
                                                for i in INSTS[:2]])

    def test_phase_a_failure_on_node2_leaves_it_alone(self):
        self.fault(1, finalize_fails=True)
        p = self.finalize("--stage-only")
        self.assertExit(1)
        self.assertIn("❌ [node2] finalize failed", p.stdout)
        self.assertEqual([c["kind"] for c in self.calls(inst=INSTS[1])], list(PHASE_A[:-1]))
        self.assertEqual(self.unit(1), (False, "inactive", ""))
        self.assertEqual(self.lines("STAGED"), ["STAGED %s state=inactive enabled=enabled" % i
                                                for i in (INSTS[0], INSTS[2])])
        self.assertEqual(self.pairs(), per_node(STAGE, INSTS[:1]) + per_node(PHASE_A[:-1], INSTS[1:2])
                         + per_node(STAGE, INSTS[2:]))
        self.assertIn("  - node2: finalize", p.stdout)

    def test_unresolvable_internal_ip_fails_that_node_only(self):
        # U-H7 mutation anchor (D4): `intIP="$(tn_node_int_ip "${inst}" "${zone}")" || intIP=""`.
        # Without the `|| intIP=""`, node2's describe (rc 1, an API error, not a transport
        # fault) ends the whole run under `set -e`: node3 is never staged and no summary prints.
        self.fault(1, describe_fails={"internal": 1})
        p = self.finalize("--stage-only")
        self.assertEqual([c["kind"] for c in self.calls(inst=INSTS[2])], list(STAGE),
                         "node3 was not staged after node2's describe failed" + self.why())
        self.assertExit(1)
        self.assertIn("❌ [node2] could not resolve internal IP for listener multiaddrs", p.stdout)
        self.assertIn("Could not fetch resource", p.stderr)
        self.assertEqual(self.pairs(), per_node(STAGE, INSTS[:1]) + per_node(PHASE_A[:6], INSTS[1:2])
                         + per_node(STAGE, INSTS[2:]))
        self.assertEqual([c["drop"] for c in self.calls("describe", INSTS[1])], ["api-rc1"])
        self.assertEqual(self.lines("STAGED"), ["STAGED %s state=inactive enabled=enabled" % i
                                                for i in (INSTS[0], INSTS[2])])
        self.assertEqual(self.unit(1), (False, "inactive", ""))
        self.assertIn("failed (1):\n  - node2: internal IP\n", p.stdout)


class StartAllTests(FinalizeCase):
    """--start-all: start check, one start-at per node with one due, the C2 marker, phase B.

    The fake runs devnet-finalize.sh's own start-at text on each node (its /run/ moved into the
    sandbox, `systemctl` a stub that starts the unit and logs the call), so the idempotent
    record, the late refusal and began are the script's; the fake supplies only the transport
    (refused connects, drops, a hang, a late arrival) and, for the spread warning, a node clock.
    """

    def test_one_coordinated_start_with_one_due(self):
        for i in range(3):
            self.staged(i)
        p = self.finalize("--start-all", FINALIZE_START_LEAD_SECS="4", FINALIZE_START_LAUNCH_GAP_SECS="1")
        self.assertExit(0)
        self.assertEqual(self.pairs(), each("start-check") + each("start-at") + each("health")
                         + per_node(PHASE_B))
        starts = self.calls("start-at")
        due = int(starts[0]["pargs"][1])
        # service, due, instance, and the late window (= FINALIZE_START_SPREAD_WARN_SECS)
        self.assertEqual([c["pargs"] for c in starts], [["telcoin", str(due), inst, "10"] for inst in INSTS])
        self.assertEqual([self.node_starts(inst) for inst in INSTS], [1, 1, 1])
        for a, b in zip(starts, starts[1:]):   # launched in fleet order, the gap apart
            self.assertGreaterEqual(b["t"] - a["t"], 0.75)
        # due = now + FINALIZE_START_LEAD_SECS, now read after the start checks
        self.assertGreaterEqual(due, int(self.calls("start-check")[-1]["t"]) + 4)
        self.assertLessEqual(due, int(starts[0]["t"]) + 4)
        sa = self.start_at_lines()
        self.assertEqual([s[0] for s in sa], list(INSTS))
        for inst, d, began, late in sa:
            self.assertEqual(d, due)
            self.assertGreaterEqual(began, due)
            self.assertEqual(late, began - due)
        m = self.marker()
        began = [s[2] for s in sa]
        self.assertEqual(m, {"due": due, "nodes": 3, "started": 3, "skipped_running": 0,
                             "spread_secs": max(began) - min(began), "max_late_secs": max(s[3] for s in sa)})
        self.assertNotIn("too new for max round 50", p.stderr)
        for i, inst in enumerate(INSTS):
            self.assertEqual(self.unit(i), (True, "active", "enabled"))
            logs = self.calls("logs", inst)[0]["pargs"]   # A4 reads what came after the start check
            self.assertEqual(logs[2].split(), ["100:42:/var/log/telcoin/telcoin.log",
                                               "0:-:/var/log/telcoin/telcoin-error.log"])
            self.assertEqual(logs[3], "s=startcheck-" + inst)
        self.assertIn("mode: --start-all", p.stdout)
        self.assertIn("all targeted nodes finalized, started, enabled and verified.", p.stdout)
        # The run records nothing: manifest.coordinated_start is the deploy's (it parses the marker).
        made = [str(f.relative_to(self.root)) for f in self.root.rglob("*") if "manifest" in f.name.lower()]
        self.assertEqual(made, [])

    def test_running_node_is_skipped_and_counted(self):
        self.staged(0)
        self.running(1)
        self.staged(2)
        p = self.finalize("--start-all")
        self.assertExit(0)
        self.assertEqual(self.lines("RUNNING"), ["RUNNING fin-validator-2"])
        self.assertIn("already running: not started again (skipped_running)", p.stderr)
        self.assertEqual(sorted(c["inst"] for c in self.calls("start-at")), sorted([INSTS[0], INSTS[2]]))
        m = self.marker()
        self.assertEqual((m["nodes"], m["started"], m["skipped_running"]), (3, 2, 1))
        self.assertEqual(self.pairs(), each("start-check") + each("start-at", (INSTS[0], INSTS[2]))
                         + each("health", (INSTS[0], INSTS[2])) + per_node(PHASE_B))

    def test_uninstalled_node_refuses_the_whole_start(self):
        self.staged(0)
        self.staged(2)
        p = self.finalize("--start-all")
        self.assertExit(1)
        self.assertEqual(self.pairs(), each("start-check"))
        self.assertIn("coordinated start refused, nothing was started: node2", p.stdout)
        self.assertEqual(self.lines("COORDINATED_START"), [])
        self.assertEqual(self.transitions(), [])

    def test_hung_start_at_is_killed_at_the_deadline(self):
        for i in range(3):
            self.staged(i)
        hang = 8
        self.fault(2, hang_start_at=hang)
        p = self.finalize("--start-all", FINALIZE_START_TIMEOUT_SECS="2")
        self.assertExit(1)
        starts = {c["inst"]: c for c in self.calls("start-at")}
        self.assertEqual(sorted(starts), sorted(INSTS))
        due = int(starts[INSTS[0]]["pargs"][1])
        self.assertIn("❌ [node3] start-at on fin-observer-3: no answer by due + 2s (probe killed)", p.stdout)
        killed = self.jsonl("signals.jsonl")
        self.assertEqual([k["inst"] for k in killed], [INSTS[2]], "the hung probe was not killed")
        self.assertGreaterEqual(killed[0]["t"], due + 2)
        self.assertLess(killed[0]["t"], due + 2 + 3)
        m = self.marker()
        self.assertEqual((m["started"], m["skipped_running"]), (2, 0))
        self.assertEqual([s[0] for s in self.start_at_lines()], list(INSTS[:2]))
        self.assertEqual(self.calls("service", INSTS[2]), [])   # no phase B for it
        # Past the moment the hung probe would have started its node: it never did.
        time.sleep(max(0.0, starts[INSTS[2]]["t"] + hang + 1.5 - time.time()))
        self.assertEqual(self.unit(2), (True, "inactive", "enabled"))
        self.assertNotIn(INSTS[2], [t["inst"] for t in self.transitions()])

    def test_dropped_start_at_is_retried_while_due_is_far(self):
        # The start-at text is idempotent, so an ssh 255 with no answer is retried (1 s apart)
        # while now < due - 10. node2: the connect is refused once. node3: the first attempt
        # reaches the node and keeps running there, but its ssh drops: the retry finds it (or
        # wins the record), and the node is started exactly once.
        for i in range(3):
            self.staged(i)
        self.fault(1, fail255={"start-at": 1})
        self.fault(2, drop_after_send=1)
        p = self.finalize("--start-all", FINALIZE_START_LEAD_SECS="13")
        self.assertExit(0)
        self.assertEqual([len(self.calls("start-at", inst)) for inst in INSTS], [1, 2, 2])
        for inst in INSTS[1:]:
            first, second = self.calls("start-at", inst)
            self.assertEqual((first["injected255"], second["injected255"]), (True, False))
            self.assertGreaterEqual(second["t"] - first["t"], 0.9)
        self.assertEqual(len({c["pargs"][1] for c in self.calls("start-at")}), 1, "one due for every attempt")
        self.assertEqual([self.node_starts(inst) for inst in INSTS], [1, 1, 1])
        m = self.marker()
        sa = self.start_at_lines()
        self.assertEqual(sorted(s[0] for s in sa), sorted(INSTS))
        self.assertEqual((m["started"], m["skipped_running"]), (3, 0))
        self.assertEqual({s[1] for s in sa}, {m["due"]})
        self.assertEqual(m["spread_secs"], max(s[2] for s in sa) - min(s[2] for s in sa))
        self.assertLessEqual(m["spread_secs"], 1)   # the retries do not move began
        self.assertIn("… [node2] ssh rc 255 on start-at attempt 1", p.stdout)
        self.assertIn("… [node3] ssh rc 255 on start-at attempt 1", p.stdout)
        for i in range(3):
            self.assertEqual(self.unit(i), (True, "active", "enabled"))

    def test_dropped_start_at_inside_the_last_10s_is_not_retried(self):
        for i in range(3):
            self.staged(i)
        self.fault(2, fail255={"start-at": 1})
        p = self.finalize("--start-all")   # lead 2 s: already inside due - 10
        self.assertExit(1)
        self.assertEqual([len(self.calls("start-at", inst)) for inst in INSTS], [1, 1, 1])
        self.assertIn("❌ [node3] start-at on fin-observer-3: no answer from fin-observer-3 (ssh rc 255)", p.stdout)
        self.assertIn("(attempts 1)", p.stdout)
        m = self.marker()
        self.assertEqual((m["nodes"], m["started"], m["skipped_running"]), (3, 2, 0))
        self.assertEqual(self.unit(2), (True, "inactive", "enabled"))
        self.assertEqual(self.node_starts(INSTS[2]), 0)
        self.assertIn("  - node3: start", p.stdout)

    def test_start_at_retry_stops_at_three_attempts_and_after_due(self):
        # node2: three refused connects, while due is still far: 3 attempts, then the node
        # fails. node3: the ssh hangs and drops after due: no retry (a retry then would reach
        # the node inside the late window and start it).
        for i in range(3):
            self.staged(i)
        self.fault(1, fail255={"start-at": 3})
        self.fault(2, drop_after_due=1)
        p = self.finalize("--start-all", FINALIZE_START_LEAD_SECS="15")
        self.assertExit(1)
        self.assertEqual([len(self.calls("start-at", inst)) for inst in INSTS], [1, 3, 1])
        due = int(self.calls("start-at", INSTS[0])[0]["pargs"][1])
        self.assertLess(self.calls("start-at", INSTS[1])[-1]["t"], due - 10)
        self.assertIn("(attempts 3)", p.stdout)
        self.assertIn("❌ [node3] start-at on fin-observer-3: no answer from fin-observer-3 (ssh rc 255)  (attempts 1)",
                      p.stdout)
        m = self.marker()
        self.assertEqual((m["started"], m["skipped_running"]), (1, 0))
        self.assertEqual([self.node_starts(inst) for inst in INSTS], [1, 0, 0])
        self.assertEqual([self.unit(i)[1] for i in range(3)], ["active", "inactive", "inactive"])

    def test_arrival_past_the_late_window_does_not_start(self):
        # The window is FINALIZE_START_SPREAD_WARN_SECS (1 here); node3 reaches its node at
        # due + 3: the start-at text prints start_rc=late and starts nothing.
        for i in range(3):
            self.staged(i)
        self.fault(2, arrive_late=3)
        p = self.finalize("--start-all", FINALIZE_START_SPREAD_WARN_SECS="1")
        self.assertExit(1)
        self.assertIn("❌ [node3] start-at on fin-observer-3: reached the node after due + 1s; NOT started", p.stdout)
        self.assertEqual(self.node_starts(INSTS[2]), 0)
        self.assertEqual(self.unit(2), (True, "inactive", "enabled"))
        self.assertEqual(self.calls("start-at", INSTS[2])[0]["pargs"][3], "1")
        m = self.marker()
        self.assertEqual((m["started"], m["skipped_running"]), (2, 0))
        self.assertEqual([s[0] for s in self.start_at_lines()], list(INSTS[:2]))
        self.assertIn("  - node3: start (late, not started)", p.stdout)

    def test_arrival_inside_the_late_window_starts_late(self):
        # Window 10 (the default): node3 reaches its node at due + 2 and starts then.
        for i in range(3):
            self.staged(i)
        self.fault(2, arrive_late=2)
        p = self.finalize("--start-all")
        self.assertExit(0)
        sa = {s[0]: s for s in self.start_at_lines()}
        m = self.marker()
        self.assertEqual(m["started"], 3)
        self.assertIn(sa[INSTS[2]][3], (2, 3))   # late_secs: the arrival, give or take the second
        self.assertEqual(m["spread_secs"], max(s[2] for s in sa.values()) - min(s[2] for s in sa.values()))
        self.assertIn(m["spread_secs"], (2, 3))
        self.assertEqual(m["max_late_secs"], sa[INSTS[2]][3])
        self.assertNotIn("too new for max round 50", p.stderr)
        self.assertEqual([self.node_starts(inst) for inst in INSTS], [1, 1, 1])

    def test_wide_spread_warns_about_round_50(self):
        # Why a node clock and not a late arrival: the start-at text refuses an arrival past
        # due + window, and the window IS FINALIZE_START_SPREAD_WARN_SECS, so an on-time clock
        # can report began at most window (+1 at a second boundary) after due, and
        # spread_secs > FINALIZE_START_SPREAD_WARN_SECS is out of reach that way. The warning
        # fires when a node's recorded began lies past the window although it passed the late
        # check: here node3's clock steps 15 s forward right after that check (the fake's
        # node `date`), so it records began ~ due + 14 while every other node records due.
        for i in range(3):
            self.staged(i)
        self.fault(2, clock_step=15)
        p = self.finalize("--start-all")
        self.assertExit(0)
        m = self.marker()
        sa = self.start_at_lines()
        began = [s[2] for s in sa]
        self.assertGreater(m["spread_secs"], 10)
        self.assertEqual(m["spread_secs"], max(began) - min(began))
        self.assertEqual(m["max_late_secs"], max(s[3] for s in sa))
        self.assertIn("too new for max round 50", p.stderr)
        self.assertIn("FINALIZE_START_SPREAD_WARN_SECS=10s", p.stderr)
        self.assertEqual([self.node_starts(inst) for inst in INSTS], [1, 1, 1])


class DeferStartTests(FinalizeCase):
    """--defer-start: --stage-only, then --start-all on the same targets, in one run."""

    def test_fresh_fleet_stages_then_starts_in_one_run(self):
        p = self.finalize("--defer-start")
        self.assertExit(0)
        self.assertEqual(self.pairs(), per_node(STAGE) + each("start-check") + each("start-at") + each("health")
                         + per_node(PHASE_B))
        self.assertEqual(len(self.lines("STAGED")), 3)
        starts = self.calls("start-at")
        self.assertLess(max(c["seq"] for c in self.calls("stop")), min(c["seq"] for c in starts))
        self.assertEqual(len({c["pargs"][1] for c in starts}), 1)
        m = self.marker()
        self.assertEqual((m["due"], m["nodes"], m["started"]), (int(starts[0]["pargs"][1]), 3, 3))
        # One unit at a time until the coordinated start, then all three.
        first_start = min(t["seq"] for t in self.transitions() if t["kind"] == "start-at")
        self.assertEqual(self.peak_active(until_seq=first_start - 1), 1)
        self.assertEqual(self.peak_active(), 3)
        for i in range(3):
            self.assertEqual(self.unit(i), (True, "active", "enabled"))
        self.assertIn("mode: --defer-start", p.stdout)

    def test_running_node_blocks_the_start(self):
        self.running(1)
        p = self.finalize("--defer-start")
        self.assertExit(1)
        self.assertEqual(self.calls("start-at") + self.calls("start-check"), [])
        self.assertEqual(self.lines("RUNNING"), ["RUNNING fin-validator-2"])
        self.assertIn("not every target is STAGED or PRESTAGED; nothing was started", p.stdout)
        self.assertEqual(self.unit(1), (True, "active", "enabled"))
        self.assertEqual(self.calls("stop", INSTS[1]), [])
        for i in (0, 2):
            self.assertEqual(self.unit(i), (True, "inactive", "enabled"))


class VerifyTests(FinalizeCase):
    """--verify: the unit check, then A1-A5; nothing staged, finalized, stopped or started."""

    def test_verify_runs_only_the_unit_check_and_a1_to_a5(self):
        for i in range(3):
            self.running(i)
        p = self.finalize("--verify")
        self.assertExit(0)
        self.assertEqual(self.pairs(), each("unit") + per_node(PHASE_B))
        self.assertEqual(self.transitions(), [])
        for c in self.calls("logs"):   # no gate record: the whole files and this boot's journal
            self.assertEqual(c["pargs"][2:], ["", ""])
        self.assertIn("mode: --verify", p.stdout)
        self.assertEqual(len(re.findall(r"✓ \[node\d\] A[1-5] ", p.stdout)), 15)

    def test_verify_takes_the_flag_among_targets(self):
        self.running(2)
        self.finalize("node3", "--verify")
        self.assertExit(0)
        self.assertEqual(self.pairs(), each("unit", INSTS[2:]) + per_node(PHASE_B, INSTS[2:]))

    def test_verify_refuses_a_node_without_a_unit(self):
        p = self.finalize("--verify", "node2")
        self.assertExit(1)
        self.assertIn("no telcoin unit installed on fin-validator-2", p.stdout)
        self.assertEqual(self.pairs(), each("unit", INSTS[1:2]))

    def test_one_dropped_a1_read_is_retried(self):
        self.running(1)
        self.fault(1, fail255={"service": 1})
        p = self.finalize("--verify", "node2")
        self.assertExit(0)
        self.assertEqual([c["injected255"] for c in self.calls("service")], [True, False])
        self.assertIn("ssh rc 255 from fin-validator-2; one retry in 1s", p.stderr)

    def test_two_dropped_a1_reads_fail_the_node(self):
        self.running(1)
        self.fault(1, fail255={"service": 2})
        p = self.finalize("--verify", "node2")
        self.assertExit(1)
        self.assertEqual([c["injected255"] for c in self.calls("service")], [True, True])
        self.assertIn("✗ [node2] A1 service: no answer from fin-validator-2 (ssh rc 255)", p.stdout)


if __name__ == "__main__":
    unittest.main()
