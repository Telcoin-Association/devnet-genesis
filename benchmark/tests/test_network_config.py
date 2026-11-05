"""devnet-network-config.sh / .py (bench 4 unit U-H9), fully offline.

Every shell test runs a copy of devnet-network-config.sh, devnet-lib.sh and devnet-network-config.py
(TREE) in a sandbox against a five-node fleet: three validators (node1 is the hub) and two observers,
with synthetic keys (fixtures/network-config/fleet, RFC 5737 addresses). CONFIG_FILE is
fixtures/network-config/config.sh. A fake gcloud (fixtures/network-config/gcloud.py) is first on
PATH: it runs each session's remote command under bash against the node's directory in the sandbox
(/etc/telcoin and /tmp/tn-network-config moved there; sudo, install, find and systemctl stubbed),
logs one record per session with its kind (a stdin session's kind is its first-line header,
`# netcfg: read` / `# netcfg: write`), and can drop a session with rc 255 before or after it runs.
The real python3 + PyYAML render, merge and validate. Nothing reaches GCP, ssh or a network.

Goldens (fixtures/network-config/golden) were produced by the code as it was before the bench-4
change: the five rendered files, and the stdout, stderr and per-node session list of an install
and a verify run with every NETCFG_* knob unset. With the knobs unset the driver must still match
them byte for byte; the only deliberate change (D6) is on the transport-fault path, which the
goldens do not take.

The tests find the scripts and fixtures relative to their own location: check_mutations.py copies
this module and what it reads into a temporary tree laid out like the repo.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
FIX = TESTS / "fixtures" / "network-config"
FLEET = FIX / "fleet"
GOLDEN = FIX / "golden"

TREE = ("devnet-network-config.sh", "devnet-lib.sh", "devnet-network-config.py")
INSTS = ("nc-validator-1", "nc-validator-2", "nc-validator-3", "nc-observer-4", "nc-observer-5")
NODES = ("node1", "node2", "node3", "node4", "node5")
ROLES = ("validator", "validator", "validator", "observer", "observer")
VALIDATORS = ("node1", "node2", "node3")
OBSERVERS = ("node4", "node5")
SPEC = ",".join("%s=%s" % (n, r) for n, r in zip(NODES, ROLES))
KNOBS = ("NETCFG_TRUST_OBSERVERS_EVERYWHERE", "NETCFG_FAST", "NETCFG_JOBS")
# Existing network-config on node2 before the install: a node default dump with a hostname.
NODE2_DEFAULT_DUMP = ("libp2p_config:\n  max_rpc_message_size: 1048576\nadmission:\n  mode: Open\n"
                      "  snapshot_max_age_secs: 300\nhostname: \"node2.example.invalid\"\n"
                      "trusted_nodes: {}\n")


def load_py():
    spec = importlib.util.spec_from_file_location("netcfg_py_under_test", str(REPO / "devnet-network-config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def with_hostname(text, line):
    """`text` (a rendered file) with `line` in the hostname slot, right after the admission block."""
    lines = text.split("\n")
    at = next(i for i, l in enumerate(lines[1:], 1) if l and not l.startswith(" "))
    return "\n".join(lines[:at] + [line] + lines[at:])


class RenderCase(unittest.TestCase):
    """devnet-network-config.py in-process on the fixture fleet (hub node1)."""

    @classmethod
    def setUpClass(cls):
        cls.py = load_py()
        cls.yaml = cls.py.yaml

    def ctx(self, trust=False):
        return self.py.Context(str(FLEET / "committee.yaml"), str(FLEET), SPEC, "node1", trust)

    def render(self, trust=False):
        ctx = self.ctx(trust)
        return dict((n, self.py.emit_config(ctx.expected(n))) for n in NODES)

    def matrix(self, texts):
        """{node: (trusted node names, bootstrap node names)} read back from the rendered texts."""
        ctx = self.ctx()
        by_bls = dict((v, k) for k, v in ctx.bls.items())
        out = {}
        for name, text in texts.items():
            cfg = self.yaml.safe_load(text)
            out[name] = (sorted(by_bls[b] for b in cfg.get("trusted_nodes", {})),
                         sorted(by_bls[b] for b in cfg.get("bootstrap_peers", {})))
        return out

    def cli(self, *args):
        return subprocess.run([sys.executable, str(REPO / "devnet-network-config.py")] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)

    def context_args(self):
        return ["--committee", str(FLEET / "committee.yaml"), "--genesis-dir", str(FLEET), "--nodes", SPEC,
                "--hub", "node1"]


class GoldenRenderTests(RenderCase):
    def test_render_without_the_flag_is_byte_identical_to_the_golden(self):
        for name, text in self.render().items():
            with self.subTest(node=name):
                self.assertEqual(text, (GOLDEN / (name + ".yaml")).read_text())

    def test_cli_render_without_the_flag_writes_the_golden_files(self):
        with tempfile.TemporaryDirectory(prefix="netcfg-render-") as out:
            p = self.cli("render", *(self.context_args() + ["--out-dir", out]))
            self.assertEqual(p.returncode, 0, p.stderr)
            for name in NODES:
                self.assertEqual(Path(out, name + ".yaml").read_bytes(), (GOLDEN / (name + ".yaml")).read_bytes())


class TrustTests(RenderCase):
    def test_without_the_flag_only_the_hub_and_the_observers_trust_each_other(self):
        m = self.matrix(self.render())
        self.assertEqual(m["node1"], (["node4", "node5"], []))
        self.assertEqual(m["node2"], ([], []))
        self.assertEqual(m["node3"], ([], []))
        self.assertEqual(m["node4"], (["node1"], ["node1"]))
        self.assertEqual(m["node5"], (["node1"], ["node1"]))

    def test_observer_is_trusted_by_every_validator_with_the_flag(self):
        m = self.matrix(self.render(trust=True))
        for v in VALIDATORS:
            with self.subTest(validator=v):
                self.assertEqual(m[v], (list(OBSERVERS), []))

    def test_observer_trusts_every_validator_and_bootstraps_from_the_hub_alone_with_the_flag(self):
        m = self.matrix(self.render(trust=True))
        for o in OBSERVERS:
            with self.subTest(observer=o):
                self.assertEqual(m[o], (list(VALIDATORS), ["node1"]))

    def test_the_hub_file_is_the_same_with_and_without_the_flag(self):
        self.assertEqual(self.render(trust=True)["node1"], (GOLDEN / "node1.yaml").read_text())

    def test_validate_follows_the_flag(self):
        with tempfile.TemporaryDirectory(prefix="netcfg-render-") as out:
            p = self.cli("render", *(self.context_args() + ["--out-dir", out, "--trust-observers-everywhere"]))
            self.assertEqual(p.returncode, 0, p.stderr)
            files = [str(Path(out, n + ".yaml")) for n in NODES]
            for name, path in zip(NODES, files):
                with self.subTest(node=name):
                    ok = self.cli("validate", *(self.context_args() + ["--trust-observers-everywhere",
                                                                      "--node", name, path]))
                    self.assertEqual(ok.returncode, 0, ok.stderr)
                    plain = self.cli("validate", *(self.context_args() + ["--node", name, path]))
                    if name == "node1":
                        self.assertEqual(plain.returncode, 0, plain.stderr)
                    else:
                        self.assertEqual(plain.returncode, 1)
                        self.assertIn("trusted_nodes", plain.stderr)


class ScriptCase(unittest.TestCase):
    """One sandbox per test: the scripts, the fake gcloud, the fake fleet, a genesis workspace."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="netcfg-test-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        self.tree.mkdir()
        for rel in TREE:
            shutil.copy2(str(REPO / rel), str(self.tree / rel))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(str(FIX / "gcloud.py"), str(self.bin / "gcloud"))
        (self.bin / "gcloud").chmod(0o755)
        self.sb = self.root / "sb"
        (self.sb / "faults").mkdir(parents=True)
        (self.sb / "nodebin").mkdir()
        for name in ("sudo", "install", "find", "systemctl"):
            os.symlink(str(self.bin / "gcloud"), str(self.sb / "nodebin" / name))
        self.genesis = self.root / "workspace" / "genesis"
        self.genesis.mkdir(parents=True)
        shutil.copyfile(str(FLEET / "committee.yaml"), str(self.genesis / "committee.yaml"))
        for sub in ("validators", "observers"):
            shutil.copytree(str(FLEET / sub), str(self.genesis / sub))
        (self.root / "tmp").mkdir()
        for i, inst in enumerate(INSTS):
            node = self.node_root(i)
            (node / "etc" / "telcoin").mkdir(parents=True)
            (node / "data").mkdir()
            (node / "tmp").mkdir()
            self.write_meta(i, HOST_SERVICE_USER="telcoin", HOST_SERVICE_GROUP="telcoin", DATA_DIR=str(node / "data"))
            sub = "validators" if ROLES[i] == "validator" else "observers"
            shutil.copyfile(str(FLEET / sub / (NODES[i] + ".yaml")), str(node / "data" / "node-info.yaml"))

    def tearDown(self):
        self._tmp.cleanup()

    # --- the fake fleet ---------------------------------------------------------------------

    def node_root(self, i):
        return self.sb / "nodes" / INSTS[i]

    def nc_path(self, i):
        return self.node_root(i) / "data" / "network-config"

    def write_meta(self, i, **kv):
        text = "".join("%s=%s\n" % (k, v) for k, v in kv.items())
        (self.node_root(i) / "etc" / "telcoin" / ".node-meta").write_text(text)

    def existing(self, i, text, owner="telcoin:telcoin:640"):
        self.nc_path(i).write_text(text)
        Path(str(self.nc_path(i)) + ".owner").write_text(owner + "\n")

    def owner(self, i):
        f = Path(str(self.nc_path(i)) + ".owner")
        return f.read_text().strip() if f.exists() else None

    def unit(self, i, state):
        (self.node_root(i) / "unit").write_text(state + "\n")

    def fault(self, i, **groups):
        (self.sb / "faults" / (INSTS[i] + ".json")).write_text(json.dumps(groups))

    def golden_fleet(self):
        """The fleet the goldens were taken on (see the module docstring)."""
        self.existing(1, NODE2_DEFAULT_DUMP)
        self.unit(1, "active")
        node4 = (GOLDEN / "node4.yaml").read_text()
        self.existing(3, with_hostname(node4, 'hostname: "node4.example.invalid"'))

    # --- running the driver -----------------------------------------------------------------

    def run_script(self, *args, **knobs):
        return subprocess.run(["bash", str(self.tree / "devnet-network-config.sh")] + list(args),
                              env=self.script_env(**knobs), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=300)

    def script_env(self, **knobs):
        env = dict(os.environ)
        for k in KNOBS:
            env.pop(k, None)
        env.update({"PATH": "%s%s%s" % (self.bin, os.pathsep, os.environ.get("PATH", "")),
                    "CONFIG_FILE": str(FIX / "config.sh"), "NETCFG_TREE": str(self.tree),
                    "NETCFG_WORKSPACE": str(self.genesis.parent), "NETCFG_SB": str(self.sb),
                    "TMPDIR": str(self.root / "tmp"), "TN_IAP_RETRIES": "0", "TN_SSH_TRANSPORT": "iap"})
        env.pop("GENESIS_WORKSPACE", None)
        env.update(knobs)
        return env

    def calls(self):
        f = self.sb / "calls.jsonl"
        if not f.exists():
            return []
        return sorted((json.loads(l) for l in f.read_text().splitlines() if l.strip()), key=lambda r: r["seq"])

    def kinds(self, i):
        return [c["kind"] for c in self.calls() if c["inst"] == INSTS[i]]

    def norm(self, text):
        """Sandbox paths and per-run names replaced by stable tokens (the goldens are normalised)."""
        text = text.replace(str(self.root), "<ROOT>")
        text = re.sub(r"tn-network-config\.[A-Za-z0-9]{6}\b", "tn-network-config.<WORK>", text)
        return re.sub(r"(tn-network-config\.node[0-9]+)\.[0-9]+", r"\1.<PID>", text)

    def session_list(self):
        return "".join("%s %s %s\n" % (c["inst"], c["kind"], c["rc"]) for c in self.calls())

    def reset_calls(self):
        for name in ("calls.jsonl", "seq"):
            f = self.sb / name
            if f.exists():
                f.unlink()

    def golden_kinds(self, name, i):
        """The per-node session kinds of a golden session list."""
        return [line.split()[1] for line in (GOLDEN / name).read_text().splitlines() if line.split()[0] == INSTS[i]]

    def expected(self, i, host=None):
        text = (GOLDEN / (NODES[i] + ".yaml")).read_text()
        return with_hostname(text, host) if host else text

    def block(self, out, node, what=r"(?:install|verify) network-config"):
        """One node's part of the driver's stdout: its `>>> [node] ...` header up to the next header."""
        m = re.search(r"^>>> \[%s\] %s.*?(?=^>>> |^=====)" % (node, what), out, re.M | re.S)
        self.assertIsNotNone(m, "no block for %s in:\n%s" % (node, out))
        return m.group(0)

    def assertSummary(self, out, ok, failed=()):
        tail = out.split("=========================================\n")[-1]
        want = "ok (%d):\n%s" % (len(ok), "".join("  - %s\n" % n for n in ok))
        if failed:
            want += "failed (%d):\n%s" % (len(failed), "".join("  - %s\n" % n for n in failed))
        self.assertTrue(tail.startswith(want), "summary:\n%s\nwant:\n%s" % (tail, want))


class LegacyGoldenTests(ScriptCase):
    """Every NETCFG_* knob unset: the driver is byte for byte what it was before bench 4."""

    def test_local_render_is_byte_identical_to_the_golden(self):
        p = self.run_script()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.norm(p.stdout), (GOLDEN / "local.stdout").read_text())
        self.assertEqual(self.norm(p.stderr), (GOLDEN / "local.stderr").read_text())
        self.assertEqual(self.calls(), [])
        for name in NODES:
            self.assertEqual((self.genesis / "network-config" / (name + ".yaml")).read_bytes(),
                             (GOLDEN / (name + ".yaml")).read_bytes())

    def test_install_then_verify_are_byte_identical_to_the_golden(self):
        self.golden_fleet()
        p = self.run_script("--yes")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.norm(p.stdout), (GOLDEN / "install.stdout").read_text())
        self.assertEqual(self.norm(p.stderr), (GOLDEN / "install.stderr").read_text())
        self.assertEqual(self.session_list(), (GOLDEN / "install.sessions").read_text())
        hosts = {1: 'hostname: "node2.example.invalid"', 3: 'hostname: "node4.example.invalid"'}
        for i in range(len(NODES)):
            self.assertEqual(self.nc_path(i).read_text(), self.expected(i, hosts.get(i)))
            self.assertEqual(self.owner(i), "telcoin:telcoin:640")
        self.reset_calls()
        p = self.run_script("--verify")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.norm(p.stdout), (GOLDEN / "verify.stdout").read_text())
        self.assertEqual(self.norm(p.stderr), (GOLDEN / "verify.stderr").read_text())
        self.assertEqual(self.session_list(), (GOLDEN / "verify.sessions").read_text())


class OwnershipFaultTests(ScriptCase):
    """D6: a transport fault on the ownership check is named as one and checked once more at the end."""

    def test_transport_fault_on_the_ownership_check_is_named_and_rechecked_once(self):
        self.fault(1, fail255={"perm": 1})
        p = self.run_script("--yes", "node2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        nc = str(self.nc_path(1))
        self.assertIn("could not check %s (transport rc 255)" % nc, p.stdout)
        self.assertNotIn("is not owned by", p.stdout)
        # node1's golden list: the same 11 sessions as node2's here (neither had a network-config yet)
        self.assertEqual(self.kinds(1), self.golden_kinds("install.sessions", 0) + ["perm"])
        self.assertIn(">>> [node2] re-check on nc-validator-2", p.stdout)
        self.assertEqual(self.nc_path(1).read_text(), self.expected(1))
        self.assertSummary(p.stdout, ["node2"])

    def test_a_second_fault_fails_the_node_without_calling_it_a_wrong_owner(self):
        self.fault(1, fail255={"perm": 2})
        p = self.run_script("--yes", "node2")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(p.stdout.count("could not check %s (transport rc 255)" % self.nc_path(1)), 2)
        self.assertNotIn("is not owned by", p.stdout)
        self.assertEqual(self.kinds(1).count("perm"), 2)
        self.assertSummary(p.stdout, [], ["node2"])

    def test_a_wrong_owner_is_still_reported_as_one_and_not_rechecked(self):
        self.existing(2, self.expected(2), owner="root:root:644")
        p = self.run_script("--verify", "node3")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("%s is not owned by telcoin:telcoin with no group/world write bit" % self.nc_path(2), p.stdout)
        self.assertNotIn("re-check", p.stdout)
        self.assertEqual(self.kinds(2), self.golden_kinds("verify.sessions", 2))

    def test_a_verify_fault_is_rechecked_at_the_end(self):
        self.existing(2, self.expected(2))
        self.fault(2, fail255={"perm": 1})
        p = self.run_script("--verify", "node3")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("could not check %s (transport rc 255)" % self.nc_path(2), p.stdout)
        self.assertEqual(self.kinds(2), self.golden_kinds("verify.sessions", 2) + ["perm"])
        self.assertSummary(p.stdout, ["node3"])


class FastTests(ScriptCase):
    """D7 NETCFG_FAST=1: one `# netcfg: read` session, and one `# netcfg: write` only for a changed file."""

    FAST = {"NETCFG_FAST": "1"}

    def test_unchanged_file_is_read_once_and_not_written(self):
        self.golden_fleet()
        before = self.nc_path(3).read_bytes()
        p = self.run_script("--yes", "node4", **self.FAST)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.kinds(3), ["read"])
        self.assertEqual([c["header"] for c in self.calls()], ["# netcfg: read"])
        self.assertIn("    ✓ unchanged (not written)\n", self.block(p.stdout, "node4"))
        self.assertEqual(self.nc_path(3).read_bytes(), before)
        self.assertSummary(p.stdout, ["node4"])

    def test_fast_install_writes_the_legacy_bytes_in_at_most_two_sessions_then_reads_once(self):
        self.golden_fleet()
        p = self.run_script("--yes", **self.FAST)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for i in range(len(NODES)):
            self.assertEqual(self.kinds(i), ["read"] if i == 3 else ["read", "write"], NODES[i])
        self.assertEqual(sorted(set(c["header"] for c in self.calls())), ["# netcfg: read", "# netcfg: write"])
        hosts = {1: 'hostname: "node2.example.invalid"', 3: 'hostname: "node4.example.invalid"'}
        for i in range(len(NODES)):
            self.assertEqual(self.nc_path(i).read_text(), self.expected(i, hosts.get(i)), NODES[i])
            self.assertEqual(self.owner(i), "telcoin:telcoin:640")
        self.assertIn("telcoin is already running", self.block(p.stdout, "node2"))
        self.assertIn("✓ installed + re-read + validated", self.block(p.stdout, "node1"))
        self.assertEqual(list(self.sb.glob("nodes/*/tmp/*")), [])
        self.assertSummary(p.stdout, list(NODES))
        self.reset_calls()
        p = self.run_script("--yes", **self.FAST)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for i in range(len(NODES)):
            self.assertEqual(self.kinds(i), ["read"], NODES[i])
            self.assertIn("✓ unchanged (not written)", self.block(p.stdout, NODES[i]))

    def test_a_wrong_owner_on_the_same_content_is_installed_again(self):
        self.golden_fleet()
        Path(str(self.nc_path(3)) + ".owner").write_text("root:root:644\n")
        p = self.run_script("--yes", "node4", **self.FAST)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.kinds(3), ["read", "write"])
        self.assertIn("installing it again", p.stdout)
        self.assertEqual(self.owner(3), "telcoin:telcoin:640")

    def test_fast_verify_is_one_session_a_node(self):
        for i in range(len(NODES)):
            self.existing(i, self.expected(i))
        Path(str(self.nc_path(4)) + ".owner").write_text("telcoin:telcoin:664\n")
        p = self.run_script("--verify", **self.FAST)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        for i in range(len(NODES)):
            self.assertEqual(self.kinds(i), ["read"], NODES[i])
        self.assertIn("is not owned by telcoin:telcoin with no group/world write bit", self.block(p.stdout, "node5"))
        self.assertSummary(p.stdout, ["node1", "node2", "node3", "node4"], ["node5"])

    def test_a_write_dropped_after_the_install_is_rechecked_at_the_end(self):
        self.fault(0, drop_after_run={"write": 1})
        p = self.run_script("--yes", "node1", **self.FAST)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("could not check %s (transport rc 255)" % self.nc_path(0), p.stdout)
        self.assertEqual(self.kinds(0), ["read", "write", "read"])
        self.assertIn("✓ re-read + validated", self.block(p.stdout, "node1", "re-check"))
        self.assertEqual(self.nc_path(0).read_text(), self.expected(0))
        self.assertSummary(p.stdout, ["node1"])

    def test_a_write_refused_before_the_install_fails_its_recheck(self):
        self.fault(0, fail255={"write": 1})
        p = self.run_script("--yes", "node1", **self.FAST)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.kinds(0), ["read", "write", "read"])
        self.assertFalse(self.nc_path(0).exists())
        self.assertSummary(p.stdout, [], ["node1"])

    def test_sessions_cut_by_a_transport_fault_are_read_from_the_retry(self):
        # devnet-lib's retry streams both attempts' stdout into one capture: the cut attempt's
        # half NC_B64= line comes first, and only the retry's answer may be read.
        self.golden_fleet()
        self.fault(1, partial255={"read": 1, "write": 1})
        self.fault(3, partial255={"read": 1})
        p = self.run_script("--yes", "node2", "node4", TN_IAP_RETRIES="1", TN_IAP_RETRY_SECS="0", **self.FAST)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([(c["kind"], c["fault"]) for c in self.calls() if c["inst"] == INSTS[1]],
                         [("read", "partial255"), ("read", ""), ("write", "partial255"), ("write", "")])
        self.assertEqual([(c["kind"], c["fault"]) for c in self.calls() if c["inst"] == INSTS[3]],
                         [("read", "partial255"), ("read", "")])
        self.assertIn("✓ installed + re-read + validated", self.block(p.stdout, "node2"))
        self.assertIn("✓ unchanged (not written)", self.block(p.stdout, "node4"))
        self.assertNotIn("re-check", p.stdout)
        self.assertEqual(self.nc_path(1).read_text(), self.expected(1, 'hostname: "node2.example.invalid"'))
        self.assertSummary(p.stdout, ["node2", "node4"])

    def test_a_read_fault_changes_nothing(self):
        self.fault(0, fail255={"read": 1})
        p = self.run_script("--yes", "node1", **self.FAST)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.kinds(0), ["read"])
        self.assertIn("could not read nc-validator-1 (transport rc 255); nothing was changed", p.stdout)
        self.assertSummary(p.stdout, [], ["node1"])

    def test_a_wrong_node_is_refused_before_anything_is_written(self):
        shutil.copyfile(str(FLEET / "validators" / "node3.yaml"), str(self.node_root(1) / "data" / "node-info.yaml"))
        p = self.run_script("--yes", "node2", **self.FAST)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.kinds(1), ["read"])
        self.assertIn("is not the local node2's", p.stdout)


class JobsTests(ScriptCase):
    """D8 NETCFG_JOBS: nodes in background jobs, each node's output whole and in fleet order."""

    def test_parallel_output_is_the_inline_output_in_fleet_order(self):
        self.golden_fleet()
        p = self.run_script("--yes", NETCFG_JOBS="3")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        want = (GOLDEN / "install.stdout").read_text().replace(
            "— 0 1 2 3 4\n", "— 0 1 2 3 4 (3 at a time)\n")
        self.assertEqual(self.norm(p.stdout), want)
        for i in range(len(NODES)):
            self.assertEqual(self.kinds(i), self.golden_kinds("install.sessions", i), NODES[i])

    def test_parallel_fast_install_with_one_failing_node(self):
        shutil.copyfile(str(FLEET / "validators" / "node3.yaml"), str(self.node_root(1) / "data" / "node-info.yaml"))
        p = self.run_script("--yes", NETCFG_JOBS="5", NETCFG_FAST="1")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        order = [m.group(1) for m in re.finditer(r"^>>> \[(node[0-9])\] install", p.stdout, re.M)]
        self.assertEqual(order, list(NODES))
        self.assertIn("is not the local node2's", self.block(p.stdout, "node2"))
        self.assertSummary(p.stdout, ["node1", "node3", "node4", "node5"], ["node2"])
        for i in range(len(NODES)):
            self.assertEqual(self.kinds(i), ["read"] if i == 1 else ["read", "write"], NODES[i])


    def test_term_stops_every_job_before_work_is_removed(self):
        for i in range(len(NODES)):
            self.fault(i, hold={"read": 1})
        proc = subprocess.Popen(["bash", str(self.tree / "devnet-network-config.sh"), "--yes"],
                                env=self.script_env(NETCFG_JOBS="3", NETCFG_FAST="1"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        try:
            marks = []
            deadline = time.time() + 120
            while time.time() < deadline and len(marks) < 3 and proc.poll() is None:
                time.sleep(0.2)
                marks = sorted(f for f in (self.sb / "held").glob("*") if not f.name.endswith(".term")) \
                    if (self.sb / "held").exists() else []
            self.assertEqual(len(marks), 3, "three held read sessions (NETCFG_JOBS=3)")
            proc.send_signal(signal.SIGTERM)
            out, err = proc.communicate(timeout=120)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 143, out + err)
        self.assertEqual(sorted(f.name.split(".")[0] for f in marks), sorted(INSTS[:3]))
        for f in marks:
            # the session got TERM while the run's work dir was still there (it is removed after)
            self.assertEqual(Path(str(f) + ".term").read_text(), "work=1\n", f.name)
        self.assertEqual(list((self.root / "tmp").glob("tn-network-config.*")), [])
        left = [l for l in subprocess.run(["ps", "-A", "-o", "pid=,args="], stdout=subprocess.PIPE,
                                          universal_newlines=True).stdout.splitlines() if str(self.root) in l]
        self.assertEqual(left, [], "processes of the run still alive after it exited")
        self.assertEqual(self.kinds(3) + self.kinds(4), [], "nodes 4 and 5 were never started")


class KnobTests(ScriptCase):
    def test_the_trust_knob_renders_and_validates_with_the_flag(self):
        p = self.run_script("--yes", "node2", "node4", NETCFG_TRUST_OBSERVERS_EVERYWHERE="1", NETCFG_FAST="1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("(hub node1; observers trusted by every validator)", p.stdout)
        py = load_py()
        ctx = py.Context(str(FLEET / "committee.yaml"), str(FLEET), SPEC, "node1", True)
        for i in (1, 3):
            want = py.emit_config(ctx.expected(NODES[i]))
            self.assertEqual((self.genesis / "network-config" / (NODES[i] + ".yaml")).read_text(), want)
            self.assertEqual(self.nc_path(i).read_text(), want)
        node2 = py.yaml.safe_load(self.nc_path(1).read_text())
        self.assertEqual(sorted(node2["trusted_nodes"]), sorted(ctx.bls[o] for o in OBSERVERS))

    def test_bad_knob_values_stop_before_anything_runs(self):
        for knob, value in (("NETCFG_FAST", "yes"), ("NETCFG_TRUST_OBSERVERS_EVERYWHERE", "2"),
                            ("NETCFG_JOBS", "0"), ("NETCFG_JOBS", "two")):
            with self.subTest(knob=knob, value=value):
                p = self.run_script("--yes", **{knob: value})
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn(knob, p.stderr)
                self.assertEqual(p.stdout, "")
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
