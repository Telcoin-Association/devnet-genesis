"""devnet-keygen.sh (bench 4 unit U-H8: D2/D17 reuse, D4/D5 faults, F9 RPC advertise, D16 report,
D8 jobs, --pull-only), fully offline.

Every test runs a copy of devnet-keygen.sh and devnet-lib.sh in a sandbox against a four-node fleet,
three validators and one observer (fixtures/keygen/config.sh is CONFIG_FILE). A fake gcloud
(fixtures/keygen/gcloud.py) is first on PATH: it keeps each node's keygen state on disk (keyed,
installed, the VALIDATOR_ADDRESS keygen recorded, node-info.yaml present), answers the IP lookups,
the keygen session (passphrase on stdin), the .node-meta read, the node-info probe, the staging copy
and the download, logs every call (argv, stdin) and the environment it ran with, and can be told per
node to drop a kind of call (rc 255), crash it (rc 1, "gcloud crashed"), drop the keygen ssh after
the keys were written, slow keygen down, or hold keygen until named calls of other nodes were made
(which proves those nodes ran at the same time). Nothing reaches GCP, ssh or a network.

With every KEYGEN_* knob unset the script's stdout, stderr and every gcloud argv and stdin must be what
the script printed and sent before bench 4: fixtures/keygen/baseline-knobs-unset.json was captured from
the unmodified script (git HEAD c0f3ca1) by this module's Sandbox with the same normalisation (the
sandbox root and the per-run log dir name replaced, the passphrase on stdin shown as <PASSPHRASE>).

The tests find the scripts and fixtures relative to their own location: check_mutations.py copies
this module and what it reads into a temporary tree laid out like the repo.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
FIX = TESTS / "fixtures" / "keygen"
BASELINE = FIX / "baseline-knobs-unset.json"

TREE = ("devnet-keygen.sh", "devnet-lib.sh")
INSTS = ("kg-validator-1", "kg-validator-2", "kg-validator-3", "kg-observer-4")   # = fixtures/keygen/config.sh
NODES = ("node1", "node2", "node3", "node4")
ROLES = ("validator", "validator", "validator", "observer")
ADDRS = tuple("0x" + d * 40 for d in "1234")
INT_IPS = tuple("198.51.100.%d" % (11 + i) for i in range(4))     # the fake's networkIP per node
DATA_DIR = "/var/lib/telcoin"
PASSPHRASE = "kg-Passphrase-7f3e9a-never-on-argv"
DEFAULTS = {"KEYGEN_JOBS": "1", "KEYGEN_REUSE_EXISTING": "0", "KEYGEN_RPC_ADVERTISE": "domain",
            "KEYGEN_RPC_HTTP_PORT": "8545", "KEYGEN_RPC_WS_PORT": "8546", "KEYGEN_REPORT": "0"}
# devnet-lib.sh's transport retry is off unless a test turns it on: the tests count gcloud calls.
BASE_ENV = {"TN_IAP_RETRIES": "0", "TN_IAP_RETRY_SECS": "0"}
PER_NODE_FRESH = ("ext-ip", "int-ip", "keygen", "stage", "scp")
REPORT_RE = re.compile(r"^KEYGEN_DONE (\S+) rc=(\d+) secs=(\d+) reused=([01]) rpc_http=(\S+) rpc_ws=(\S+)$")
RUNLOG_RE = re.compile(r"/logs/[0-9]{8}_[0-9]{6}-keygen")
# The two waits on background keygen runs are wall-clock budgets: a loaded host stretches them, so the gate
# (benchmark/tests/gate.sh) scales them with BENCH_TEST_TIMEOUT_SCALE (3 there; unset or invalid: 1).
try:
    TIMEOUT_SCALE = max(1.0, float(os.environ.get("BENCH_TEST_TIMEOUT_SCALE") or 1))
except ValueError:
    TIMEOUT_SCALE = 1.0


def keyed(i, address=None, installed=False, info=True, rpc_http=None, rpc_ws=None):
    """Fake-node state of a node an earlier keygen (domain advertise) already keyed."""
    return {"keyed": True, "installed": installed, "info": info, "data_dir": DATA_DIR,
            "address": ADDRS[i] if address is None else address,
            "rpc_http": rpc_http or "https://%s.example.invalid/" % NODES[i],
            "rpc_ws": rpc_ws or "wss://%s.example.invalid/" % NODES[i], "staged": []}


def alive(pid):
    """True while <pid> runs (a zombie, already dead, is not alive)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (IOError, OSError, IndexError):
        return True


class Sandbox(object):
    """The scripts (copied from <src>), a bin dir with the fake gcloud, the fake fleet, the genesis
    workspace and REPO_ROOT (where the per-run log dir lands). reset() empties the fleet and outputs."""

    def __init__(self, src=REPO):
        self._tmp = tempfile.TemporaryDirectory(prefix="keygen-test-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        for rel in TREE:
            dst = self.tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(Path(src) / rel), str(dst))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(str(FIX / "gcloud.py"), str(self.bin / "gcloud"))
        (self.bin / "gcloud").chmod(0o755)
        self.secret = self.root / "secrets" / "bls-passphrase"
        self.secret.parent.mkdir()
        self.secret.write_text(PASSPHRASE)
        self.secret.chmod(0o600)
        self.sb = self.root / "fleet"
        self.workspace = self.root / "workspace"
        self.repo_root = self.root / "repo"
        self.tmpdir = self.root / "tmp"
        self.work = self.root / "work"
        self.last = None
        self.reset()

    def close(self):
        self._tmp.cleanup()

    def reset(self):
        for d in (self.sb, self.workspace, self.repo_root, self.tmpdir, self.work):
            if d.exists():
                shutil.rmtree(str(d))
            d.mkdir()
        for sub in ("state", "faults"):
            (self.sb / sub).mkdir()

    # --- the fake fleet ---------------------------------------------------------------------

    def node(self, i, state):
        (self.sb / "state" / (INSTS[i] + ".json")).write_text(json.dumps(state))

    def fault(self, i, **faults):
        (self.sb / "faults" / (INSTS[i] + ".json")).write_text(json.dumps(faults))

    def jsonl(self, name):
        f = self.sb / name
        if not f.exists():
            return []
        rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        return sorted(rows, key=lambda r: r["seq"])

    def jsonl_unordered(self, name):
        f = self.sb / name
        return [json.loads(line) for line in f.read_text().splitlines() if line.strip()] if f.exists() else []

    def calls(self, kind=None, inst=None):
        return [c for c in self.jsonl("calls.jsonl")
                if (kind is None or c["kind"] == kind) and (inst is None or c["inst"] == inst)]

    def kinds(self, inst):
        return [c["kind"] for c in self.calls(inst=inst)]

    # --- the run ----------------------------------------------------------------------------

    def env(self, knobs):
        # Nothing from the developer's shell that the scripts read (KEYGEN_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir),
               "CONFIG_FILE": str(FIX / "config.sh"), "KG_SB": str(self.sb),
               "KG_ROOT": str(self.repo_root), "KG_WORKSPACE": str(self.workspace),
               "TN_BLS_PASSPHRASE_FILE": str(self.secret)}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        merged = dict(BASE_ENV)
        merged.update(knobs)
        for key, value in merged.items():
            if value is not None:
                env[key] = value
        return env

    def run(self, *args, **knobs):
        self.last = subprocess.run(["bash", str(self.tree / "devnet-keygen.sh")] + list(args),
                                   cwd=str(self.work), env=self.env(knobs), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True, timeout=300)
        return self.last

    def start(self, *args, **knobs):
        """The script in the background, stdout/stderr to files (a pipe would stay open as long as
        any orphaned child lives). finish() waits for it and fills self.last."""
        self._out = open(str(self.root / "run.out"), "w")
        self._err = open(str(self.root / "run.err"), "w")
        return subprocess.Popen(["bash", str(self.tree / "devnet-keygen.sh")] + list(args),
                                cwd=str(self.work), env=self.env(knobs), stdin=subprocess.DEVNULL,
                                stdout=self._out, stderr=self._err)

    def finish(self, proc, timeout=60):
        rc = proc.wait(timeout=timeout * TIMEOUT_SCALE)
        self._out.close()
        self._err.close()
        self.last = subprocess.CompletedProcess(proc.args, rc, (self.root / "run.out").read_text(),
                                                (self.root / "run.err").read_text())
        return rc

    def wait_held(self, insts, timeout=60):
        """{inst: pid} of the fake keygen sessions keygen_wait_for holds, once all of <insts> are held."""
        deadline = time.time() + timeout * TIMEOUT_SCALE
        while True:
            files = {inst: self.sb / "held" / (inst + ".pid") for inst in insts}
            if all(f.exists() for f in files.values()):
                return {inst: int(f.read_text()) for inst, f in files.items()}
            if time.time() > deadline:
                raise AssertionError("keygen sessions not held within %ss: %s"
                                     % (timeout * TIMEOUT_SCALE, sorted(files)))
            time.sleep(0.05)

    def leftovers(self):
        """pids of live processes whose environment names this sandbox's fleet (KG_SB): the
        script's subshells and every fake gcloud. None where /proc is missing (macOS)."""
        if not os.path.isdir("/proc/self"):
            return None
        tag = ("KG_SB=%s" % self.sb).encode()
        out = []
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open("/proc/%s/environ" % d, "rb") as f:
                    if tag in f.read().split(b"\0"):
                        out.append(int(d))
            except (IOError, OSError):
                continue
        return out

    def collected(self, i):
        sub = "observers" if ROLES[i] == "observer" else "validators"
        return self.workspace / "genesis" / sub / (NODES[i] + ".yaml")

    def run_log_dirs(self):
        logs = self.repo_root / "logs"
        return sorted(logs.iterdir()) if logs.exists() else []

    def normalized(self, by_node=False):
        """rc, stdout lines and every gcloud call (argv, stdin), with the sandbox root, the per-run
        log dir's timestamp and the passphrase replaced. by_node: calls grouped per node in fleet
        order, each node's own calls in the order they were made (KEYGEN_JOBS runs overlap)."""
        root = str(self.root)

        def norm(text):
            return RUNLOG_RE.sub("/logs/<RUN>-keygen", text.replace(root, "<ROOT>"))

        calls = self.calls()
        if by_node:
            calls = sorted(calls, key=lambda c: INSTS.index(c["inst"]) if c["inst"] in INSTS else -1)
        return {"rc": self.last.returncode,
                "stdout": [norm(line) for line in self.last.stdout.splitlines()],
                "stderr": [norm(line) for line in self.last.stderr.splitlines()],
                "calls": [{"argv": [norm(a) for a in c["argv"]],
                           "stdin": c["stdin"].replace(PASSPHRASE, "<PASSPHRASE>")} for c in calls]}


# The fleets the baseline was captured on. Each returns the knobs-unset run's normalised result.
def scenario_fresh(sb, **knobs):
    sb.reset()
    sb.run(**knobs)
    return sb.normalized()


def mixed_fleet(sb):
    """node1 keyed by an earlier run (v2 refuses: node-keys already exist), node2's keygen ssh drops
    after the keys were written (no done line), node3 fresh, node4 finalized (already installed)."""
    sb.node(0, keyed(0))
    sb.fault(1, keygen_drop=1)
    sb.node(3, keyed(3, installed=True))


def scenario_mixed(sb, **knobs):
    sb.reset()
    mixed_fleet(sb)
    sb.run(**knobs)
    return sb.normalized()


def scenario_download_fault(sb, **knobs):
    """node2's node-info download fails with ssh rc 255 (its stderr reaches the script's stderr)."""
    sb.reset()
    sb.fault(1, fail255={"scp": 1})
    sb.run(**knobs)
    return sb.normalized()


SCENARIOS = (("fresh", scenario_fresh), ("mixed", scenario_mixed), ("download_fault", scenario_download_fault))


class KeygenCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.close()

    def why(self):
        p = self.sb.last
        if p is None:
            return ""
        out, err = ("\n".join(text.splitlines()[-40:]) for text in (p.stdout, p.stderr))
        return "\nrc %d\n--- stdout (tail)\n%s\n--- stderr (tail)\n%s" % (p.returncode, out, err)

    def assertExit(self, rc):
        self.assertEqual(self.sb.last.returncode, rc, self.why())

    def lines(self, prefix):
        return [line for line in self.sb.last.stdout.splitlines() if line.startswith(prefix)]

    def report(self):
        """{inst: (rc, secs, reused, http, ws)} from the KEYGEN_DONE lines, which must parse."""
        out = {}
        for line in self.lines("KEYGEN_DONE"):
            m = REPORT_RE.match(line)
            self.assertIsNotNone(m, "KEYGEN_DONE grammar: %r" % line)
            inst, rc, secs, reused, http, ws = m.groups()
            self.assertNotIn(inst, out, "one KEYGEN_DONE per node")
            out[inst] = (int(rc), int(secs), int(reused), http, ws)
        return out

    def keygen_cmd(self, i):
        found = self.sb.calls("keygen", INSTS[i])
        self.assertEqual(len(found), 1, self.why())
        return found[0]["cmd"]

    def assertCollected(self, i, address=None, http=None):
        f = self.sb.collected(i)
        self.assertTrue(f.is_file(), "%s not collected%s" % (NODES[i], self.why()))
        text = f.read_text()
        self.assertIn('execution_address: "%s"' % (address or ADDRS[i]).lower(), text)
        if http:
            self.assertIn('http: "%s"' % http, text)

    def assertNotCollected(self, i):
        self.assertFalse(self.sb.collected(i).exists(), "%s must not be collected" % NODES[i])


class BaselineTests(KeygenCase):
    """Knobs unset == the script before bench 4, byte for byte (stdout, argv, stdin)."""

    def setUp(self):
        super(BaselineTests, self).setUp()
        with open(str(BASELINE)) as f:
            self.baseline = json.load(f)

    def test_fresh_fleet_matches_the_snapshot(self):
        self.assertEqual(scenario_fresh(self.sb), self.baseline["fresh"], self.why())

    def test_refusals_and_a_dropped_keygen_match_the_snapshot(self):
        self.assertEqual(scenario_mixed(self.sb), self.baseline["mixed"], self.why())

    def test_a_dropped_download_matches_the_snapshot(self):
        got = scenario_download_fault(self.sb)
        self.assertTrue(got["stderr"], "the scenario writes to stderr")
        self.assertEqual(got, self.baseline["download_fault"], self.why())

    def test_every_knob_at_its_default_is_the_unset_run(self):
        for name, scenario in SCENARIOS:
            with self.subTest(scenario=name):
                unset = scenario(self.sb)
                self.assertEqual(scenario(self.sb, **DEFAULTS), unset, self.why())

    def test_jobs_1_is_the_no_knob_run(self):
        unset = scenario_fresh(self.sb)
        self.sb.reset()
        self.sb.run(KEYGEN_JOBS="1")
        self.assertEqual(self.sb.normalized(), unset, self.why())


class FreshTests(KeygenCase):
    def test_fresh_keygen_collects_every_node(self):
        self.sb.run()
        self.assertExit(0)
        for i, inst in enumerate(INSTS):
            with self.subTest(node=NODES[i]):
                self.assertEqual(self.sb.kinds(inst), list(PER_NODE_FRESH))
                self.assertCollected(i, http="https://%s.example.invalid/" % NODES[i])
                call = self.sb.calls("keygen", inst)[0]
                self.assertEqual(call["stdin"], PASSPHRASE + "\n", "the passphrase rides the ssh stdin")
                self.assertIn("--address %s " % ADDRS[i], call["cmd"])
        self.assertEqual(self.lines("KEYGEN_DONE"), [], "no report line unless KEYGEN_REPORT=1")
        self.assertIn("all targeted nodes keyed and collected. Next: ./devnet-genesis-build.sh",
                      self.sb.last.stdout)


class FaultTests(KeygenCase):
    """D4/D5: an IP-lookup fault fails that node only; the download rides devnet-lib's retry."""

    def test_an_internal_ip_lookup_fault_fails_that_node_only(self):
        self.sb.fault(1, crash={"int-ip": 1})
        self.sb.run()
        self.assertExit(1)
        self.assertEqual(self.sb.kinds(INSTS[1]), ["ext-ip", "int-ip"], "node2 stops at the lookup")
        self.assertIn("❌ [node2] could not resolve IPs (ext='203.0.113.12' int='') — skipping",
                      self.sb.last.stdout)
        for i in (0, 2, 3):
            self.assertCollected(i)
        self.assertNotCollected(1)
        self.assertIn("failed nodes (1):\n  - node2\n", self.sb.last.stdout)

    def test_an_external_ip_lookup_fault_fails_that_node_only(self):
        self.sb.fault(2, crash={"ext-ip": 1})
        self.sb.run()
        self.assertExit(1)
        self.assertNotIn("keygen", self.sb.kinds(INSTS[2]))
        for i in (0, 1, 3):
            self.assertCollected(i)
        self.assertIn("failed nodes (1):\n  - node3\n", self.sb.last.stdout)

    def test_the_download_is_retried_after_a_transport_fault(self):
        self.sb.fault(2, fail255={"scp": 1})
        self.sb.run(TN_IAP_RETRIES="1")
        self.assertExit(0)
        self.assertEqual(len(self.sb.calls("scp", INSTS[2])), 2, self.why())
        self.assertCollected(2)
        self.assertIn("tn_iap_scp_down %s: transport fault (rc 255)" % INSTS[2], self.sb.last.stderr)

    def test_a_download_fault_without_retries_fails_that_node(self):
        self.sb.fault(2, fail255={"scp": 1})
        self.sb.run()
        self.assertExit(1)
        self.assertEqual(len(self.sb.calls("scp", INSTS[2])), 1)
        self.assertIn("❌ [node3] failed to download node-info.yaml", self.sb.last.stdout)


class ReuseTests(KeygenCase):
    """KEYGEN_REUSE_EXISTING=1: a node that refuses keygen (already keyed or installed) or whose
    keygen ssh dropped is reused only when its .node-meta names this node's address and its
    node-info.yaml is there."""

    def test_reuse_recovers_every_already_keyed_node(self):
        mixed_fleet(self.sb)
        self.sb.run(KEYGEN_REUSE_EXISTING="1")
        self.assertExit(0)
        for i in range(4):
            self.assertCollected(i)
        reprobe = ["ext-ip", "int-ip", "keygen", "meta", "info", "stage", "scp"]
        for i in (0, 1, 3):
            with self.subTest(node=NODES[i]):
                self.assertEqual(self.sb.kinds(INSTS[i]), reprobe)
                self.assertEqual(len(self.lines(">>> [%s] already keyed for %s on %s: reusing"
                                                 % (NODES[i], ADDRS[i], INSTS[i]))), 1, self.why())
        self.assertEqual(self.sb.kinds(INSTS[2]), list(PER_NODE_FRESH), "a fresh node is not re-probed")
        meta = self.sb.calls("meta", INSTS[0])[0]["cmd"]
        self.assertIn("'^VALIDATOR_ADDRESS='", meta)
        info = self.sb.calls("info", INSTS[0])[0]["cmd"]
        self.assertTrue(info.startswith("sudo test -s '%s/node-info.yaml'" % DATA_DIR), info)

    def test_reuse_refuses_another_address(self):
        self.sb.node(0, keyed(0, address="0x" + "9" * 40, installed=True))
        self.sb.run(KEYGEN_REUSE_EXISTING="1")
        self.assertExit(1)
        self.assertEqual(self.sb.kinds(INSTS[0]), ["ext-ip", "int-ip", "keygen", "meta", "info"],
                         "nothing is staged or downloaded from a node keyed for another address")
        self.assertNotCollected(0)
        self.assertEqual(self.lines(">>> [node1] already keyed"), [])
        self.assertIn("❌ [node1] not reusing %s:" % INSTS[0], self.sb.last.stdout)
        self.assertIn("VALIDATOR_ADDRESS=0x" + "9" * 40, self.sb.last.stdout)
        for i in (1, 2, 3):
            self.assertCollected(i)
        self.assertIn("failed nodes (1):\n  - node1\n", self.sb.last.stdout)

    def test_reuse_refuses_a_node_without_node_info(self):
        self.sb.node(1, keyed(1, info=False))
        self.sb.run(KEYGEN_REUSE_EXISTING="1")
        self.assertExit(1)
        self.assertEqual(self.sb.kinds(INSTS[1]), ["ext-ip", "int-ip", "keygen", "meta", "info"])
        self.assertNotCollected(1)
        self.assertIn("node-info.yaml=missing", self.sb.last.stdout)

    def test_reuse_refuses_when_the_meta_read_fails(self):
        self.sb.node(0, keyed(0))
        self.sb.fault(0, fail255={"meta": 1})
        self.sb.run(KEYGEN_REUSE_EXISTING="1")
        self.assertExit(1)
        self.assertNotCollected(0)
        self.assertNotIn("stage", self.sb.kinds(INSTS[0]))

    def test_another_keygen_failure_is_not_reused(self):
        self.sb.node(0, dict(keyed(0), keyed=False, installed=False))   # fresh, but ...
        self.sb.fault(0, fail255={"keygen": 1})                         # ... the ssh never connects
        self.sb.run(KEYGEN_REUSE_EXISTING="1")
        self.assertExit(1)
        # No done line: re-probed, and a node keygen never reached has no .node-meta.
        self.assertEqual(self.sb.kinds(INSTS[0]), ["ext-ip", "int-ip", "keygen", "meta", "info"])
        self.assertNotCollected(0)


class PullOnlyTests(KeygenCase):
    def test_pull_only_downloads_the_named_targets_only(self):
        for i in range(4):
            self.sb.node(i, keyed(i))
        os.unlink(str(self.sb.secret))       # no passphrase needed: nothing is generated
        self.sb.run("--pull-only", "node2", INSTS[3])
        self.assertExit(0)
        self.assertEqual([(c["inst"], c["kind"]) for c in self.sb.calls()],
                         [(INSTS[1], "stage"), (INSTS[1], "scp"), (INSTS[3], "stage"), (INSTS[3], "scp")])
        self.assertCollected(1)
        self.assertCollected(3)
        self.assertNotCollected(0)
        self.assertNotCollected(2)
        self.assertNotIn("resolving BLS passphrase", self.sb.last.stdout)

    def test_pull_only_fails_a_node_with_nothing_to_pull(self):
        self.sb.node(0, keyed(0))
        self.sb.run("--pull-only", "0", "1", KEYGEN_REPORT="1")
        self.assertExit(1)
        self.assertCollected(0)
        self.assertNotCollected(1)
        self.assertEqual(self.sb.kinds(INSTS[1]), ["stage"])
        rep = self.report()
        self.assertEqual(rep[INSTS[0]][0], 0)
        self.assertEqual(rep[INSTS[0]][2], 1, "pull-only generates nothing: reused=1")
        self.assertEqual(rep[INSTS[1]][0], 1)

    def test_pull_only_refuses_an_unknown_target(self):
        self.sb.run("--pull-only", "node9")
        self.assertExit(1)
        self.assertEqual(self.sb.calls(), [])


class AdvertiseTests(KeygenCase):
    """F9: KEYGEN_RPC_ADVERTISE=internal-ip advertises reth's own ports on the internal IP."""

    def test_internal_ip_advertise(self):
        self.sb.run(KEYGEN_RPC_ADVERTISE="internal-ip")
        self.assertExit(0)
        for i in range(4):
            with self.subTest(node=NODES[i]):
                http, ws = "http://%s:8545/" % INT_IPS[i], "ws://%s:8546/" % INT_IPS[i]
                self.assertIn("--rpc-http %s --rpc-ws %s" % (http, ws), self.keygen_cmd(i))
                self.assertCollected(i, http=http)

    def test_internal_ip_ports_follow_their_knobs(self):
        self.sb.run(KEYGEN_RPC_ADVERTISE="internal-ip", KEYGEN_RPC_HTTP_PORT="18545", KEYGEN_RPC_WS_PORT="18546")
        self.assertExit(0)
        self.assertIn("--rpc-http http://%s:18545/ --rpc-ws ws://%s:18546/" % (INT_IPS[0], INT_IPS[0]),
                      self.keygen_cmd(0))

    def test_domain_keeps_the_public_urls(self):
        self.sb.run(KEYGEN_RPC_ADVERTISE="domain")
        self.assertIn("--rpc-http https://node1.example.invalid/ --rpc-ws wss://node1.example.invalid/",
                      self.keygen_cmd(0))

    def test_bad_knob_values_stop_before_anything_runs(self):
        for knob, value in (("KEYGEN_RPC_ADVERTISE", "public"), ("KEYGEN_JOBS", "0"), ("KEYGEN_JOBS", "two"),
                            ("KEYGEN_REUSE_EXISTING", "yes"), ("KEYGEN_REPORT", "2"),
                            ("KEYGEN_RPC_HTTP_PORT", "85x5")):
            with self.subTest(knob=knob, value=value):
                self.sb.reset()
                knobs = {knob: value}
                if knob == "KEYGEN_RPC_HTTP_PORT":
                    knobs["KEYGEN_RPC_ADVERTISE"] = "internal-ip"
                self.sb.run(**knobs)
                self.assertExit(1)
                self.assertIn(knob, self.sb.last.stderr)
                self.assertEqual(self.sb.calls(), [])
                self.assertEqual(self.sb.last.stdout, "")


class ReportTests(KeygenCase):
    """D16: KEYGEN_REPORT=1 prints one KEYGEN_DONE line per node."""

    def test_report_line_shape(self):
        self.sb.node(0, keyed(0, installed=True))
        self.sb.fault(2, crash={"int-ip": 1})
        self.sb.run(KEYGEN_REPORT="1", KEYGEN_REUSE_EXISTING="1", KEYGEN_RPC_ADVERTISE="internal-ip")
        self.assertExit(1)
        rep = self.report()
        self.assertEqual([line.split()[1] for line in self.lines("KEYGEN_DONE")], list(INSTS), "index order")
        # node1 reused: its node-info (an earlier domain keygen) is what it advertises.
        self.assertEqual(rep[INSTS[0]][0], 0)
        self.assertEqual(rep[INSTS[0]][2:], (1, "https://node1.example.invalid/", "wss://node1.example.invalid/"))
        self.assertEqual(rep[INSTS[1]][0], 0)
        self.assertEqual(rep[INSTS[1]][2:], (0, "http://%s:8545/" % INT_IPS[1], "ws://%s:8546/" % INT_IPS[1]))
        self.assertEqual(rep[INSTS[2]][0], 1)
        self.assertEqual(rep[INSTS[2]][2:], (0, "-", "-"))
        self.assertEqual(rep[INSTS[3]][2:], (0, "http://%s:8545/" % INT_IPS[3], "ws://%s:8546/" % INT_IPS[3]))

    def test_report_secs_count_the_node(self):
        self.sb.fault(1, keygen_delay=1.2)
        self.sb.run(KEYGEN_REPORT="1")
        self.assertExit(0)
        self.assertGreaterEqual(self.report()[INSTS[1]][1], 1)


class JobsTests(KeygenCase):
    """D8: KEYGEN_JOBS=N runs up to N nodes at once and prints each node's output whole, in index order."""

    def test_jobs_3_prints_the_same_lines_in_order(self):
        serial = scenario_mixed(self.sb)
        serial_by_node = self.sb.normalized(by_node=True)
        self.sb.reset()
        mixed_fleet(self.sb)
        # node1's keygen returns only once node3 was downloaded and node4 reached its keygen:
        # node3 ran beside node1, and node4 took the slot node2 or node3 freed while node1 still
        # held its own (a pool that waited on the oldest job would leave node4 waiting here).
        self.sb.fault(0, keygen_wait_for=[[INSTS[2], "scp"], [INSTS[3], "keygen"]])
        self.sb.run(KEYGEN_JOBS="3")
        par = self.sb.normalized(by_node=True)
        self.assertEqual(par["rc"], serial["rc"], self.why())
        self.assertEqual(par["stdout"], serial["stdout"], self.why())
        self.assertEqual(par["calls"], serial_by_node["calls"])
        gates = self.sb.jsonl_unordered("gates.jsonl")
        self.assertEqual([(g["inst"], g["satisfied"]) for g in gates], [(INSTS[0], True)], gates)

    def test_jobs_1_runs_one_node_at_a_time(self):
        self.sb.fault(0, keygen_wait_for=[[INSTS[1], "ext-ip"]], keygen_wait_secs=1)
        self.sb.run(KEYGEN_JOBS="1")
        self.assertExit(0)
        gates = self.sb.jsonl_unordered("gates.jsonl")
        self.assertEqual([(g["inst"], g["satisfied"]) for g in gates], [(INSTS[0], False)], gates)

    def test_jobs_with_report_and_reuse(self):
        self.sb.node(0, keyed(0))
        self.sb.run(KEYGEN_JOBS="4", KEYGEN_REPORT="1", KEYGEN_REUSE_EXISTING="1")
        self.assertExit(0)
        self.assertEqual([line.split()[1] for line in self.lines("KEYGEN_DONE")], list(INSTS))
        self.assertEqual([r[2] for r in (self.report()[inst] for inst in INSTS)], [1, 0, 0, 0])
        for i in range(4):
            self.assertCollected(i)
        logs = self.sb.run_log_dirs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(sorted(p.name for p in logs[0].glob("*.out")), sorted(i + ".out" for i in INSTS))


class SignalTests(KeygenCase):
    """INT, TERM or HUP during a KEYGEN_JOBS run stops every node job and its gcloud before the
    script exits 128+N: nothing runs on, nothing is collected afterwards."""

    def test_a_signal_stops_every_node_job_and_its_gcloud(self):
        for sig, rc in ((signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129)):
            with self.subTest(signal=sig.name):
                self.sb.reset()
                for i in range(3):   # nodes 1-3 hold their keygen session until killed
                    self.sb.fault(i, keygen_wait_for=[["nobody", "never"]], keygen_wait_secs=120)
                proc = self.sb.start(KEYGEN_JOBS="3")
                try:
                    held = self.sb.wait_held(INSTS[:3])
                    before = self.sb.calls()
                    proc.send_signal(sig)
                    self.assertEqual(self.sb.finish(proc), rc, self.why())
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        self.sb.finish(proc)
                self.assertEqual([inst for inst, pid in sorted(held.items()) if alive(pid)], [],
                                 "held keygen sessions outlived the script" + self.why())
                left = self.sb.leftovers()
                if left is not None:
                    self.assertEqual([pid for pid in left if alive(pid)], [], "processes of the run outlived it")
                self.assertIn("SIG" + sig.name[3:], self.sb.last.stderr)
                self.assertNotIn("keygen summary", self.sb.last.stdout)
                time.sleep(0.5)
                self.assertEqual(self.sb.calls(), before, "no gcloud call after the signal")
                self.assertEqual(sorted({c["inst"] for c in before}), sorted(INSTS[:3]))
                for i in range(4):
                    self.assertNotCollected(i)


class SecretTests(KeygenCase):
    """The passphrase reaches the node on the keygen ssh's stdin and nowhere else: not on any gcloud
    argv, not in any gcloud environment, not in stdout/stderr or any file of the run log dir."""

    def assertSecretOnlyOnStdin(self):
        p = self.sb.last
        self.assertNotIn(PASSPHRASE, p.stdout)
        self.assertNotIn(PASSPHRASE, p.stderr)
        # Every file of the sandbox: the run log dir (.log, .out, .err), TMPDIR, the genesis
        # workspace, the fake fleet (env.jsonl included), ... except the secret file itself and the
        # fake's call log, whose stdin fields are checked call by call below.
        skip = {self.sb.secret, self.sb.sb / "calls.jsonl"}
        secret = PASSPHRASE.encode()
        scanned = []
        for f in sorted(self.sb.root.rglob("*")):
            if f.is_file() and f not in skip:
                scanned.append(f.relative_to(self.sb.root).parts[0])
                self.assertNotIn(secret, f.read_bytes(), str(f.relative_to(self.sb.root)))
        for top in ("fleet", "workspace", "tree", "bin"):   # repo/ (the run log dir) is empty under --pull-only
            self.assertIn(top, scanned, "the walk covered %s/" % top)
        calls = self.sb.calls()
        self.assertTrue(calls)
        for c in calls:
            self.assertNotIn(PASSPHRASE, " ".join(c["argv"]), "argv of call %d" % c["seq"])
            if c["kind"] != "keygen":
                self.assertNotIn(PASSPHRASE, c["stdin"], "stdin of %s call %d" % (c["kind"], c["seq"]))
        for e in self.sb.jsonl("env.jsonl"):
            self.assertNotIn(PASSPHRASE, json.dumps(e["environ"]), "environment of call %d" % e["seq"])
            self.assertNotIn("TN_BLS_PASSPHRASE", e["environ"])
        for c in self.sb.calls("keygen"):
            if not c["injected"]:
                self.assertEqual(c["stdin"], PASSPHRASE + "\n")

    def test_secret_never_on_argv_env_or_log(self):
        for jobs in ("1", "3"):
            with self.subTest(jobs=jobs):
                self.sb.reset()
                self.sb.node(0, keyed(0))
                self.sb.fault(1, keygen_drop=1)
                self.sb.fault(2, fail255={"scp": 1})
                self.sb.run(KEYGEN_JOBS=jobs, KEYGEN_REUSE_EXISTING="1", KEYGEN_REPORT="1", TN_IAP_RETRIES="1")
                self.assertExit(0)
                # node2's dropped keygen is sent again by devnet-lib's retry (TN_IAP_RETRIES=1),
                # refused ("node-keys already exist") and reused: five keygen sessions, each with
                # the passphrase on its stdin.
                self.assertEqual(len(self.sb.calls("keygen")), 5)
                self.assertSecretOnlyOnStdin()

    def test_an_exported_passphrase_is_not_inherited(self):
        for args, jobs in (((), "3"), (("--pull-only", "node1"), "1")):
            with self.subTest(args=args):
                self.sb.reset()
                if args:
                    self.sb.node(0, keyed(0))
                self.sb.run(*args, KEYGEN_JOBS=jobs, TN_BLS_PASSPHRASE=PASSPHRASE)
                self.assertExit(0)
                self.assertSecretOnlyOnStdin()


if __name__ == "__main__":
    unittest.main()
