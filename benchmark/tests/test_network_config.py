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


# --------------------------------------------------------------------------- native admission (launch 2)

NATIVE = FIX / "native"
NATIVE_NODES = ("node1", "node2", "node3", "node4", "node5", "node6")
NATIVE_ROLES = ("validator", "validator", "validator", "validator", "observer", "rpc")
NATIVE_SPEC = ",".join("%s=%s" % (n, r) for n, r in zip(NATIVE_NODES, NATIVE_ROLES))
# The native fleet's node-info files: the legacy fleet's keys with node4 now a validator
# (native/committee.yaml adds its entries), plus the rpc node6 (native/observers/node6.yaml).
NATIVE_INFO = (("validators/node1.yaml", FLEET / "validators" / "node1.yaml"),
               ("validators/node2.yaml", FLEET / "validators" / "node2.yaml"),
               ("validators/node3.yaml", FLEET / "validators" / "node3.yaml"),
               ("validators/node4.yaml", FLEET / "observers" / "node4.yaml"),
               ("observers/node5.yaml", FLEET / "observers" / "node5.yaml"),
               ("observers/node6.yaml", NATIVE / "observers" / "node6.yaml"))


def top_span(lines, key):
    """[start, end) of the top-level entry `key:` in `lines`."""
    start = lines.index(key + ":")
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")), len(lines))
    return start, end


def entry_span(lines, key, bls):
    """[start, end) of map entry `bls` under the top-level entry `key:`."""
    start, end = top_span(lines, key)
    first = lines.index("  %s:" % bls, start, end)
    return first, next((i for i in range(first + 1, end) if not lines[i].startswith("    ")), end)


def without(lines, span):
    return "\n".join(lines[:span[0]] + lines[span[1]:]) + "\n"


class NativeCase(RenderCase):
    """`maps` and `validate --native` on the native fleet: validators node1-4, observer node5, rpc node6.

    native/golden is what `maps` wrote for that fleet. native/rendered is what tn-node-deployment's own
    renderer (tn_network_config_render in tnd-l2-gateway lib/common.sh, commit 405af9e, run once by hand
    with TN_ROOT_PREFIX and tn_as_service_user overridden) wrote from those maps: node1 closed with its
    trusted map over an existing `hostname:` line, node5 closed with its trusted map, node6 open without.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nc-native-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.genesis = self.tmp / "genesis"
        for rel, src in NATIVE_INFO:
            (self.genesis / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(src), str(self.genesis / rel))
        self.committee = self.tmp / "committee.yaml"
        shutil.copyfile(str(NATIVE / "committee.yaml"), str(self.committee))
        self.out = self.tmp / "maps"

    def native_args(self, spec=NATIVE_SPEC):
        return ["--committee", str(self.committee), "--genesis-dir", str(self.genesis), "--nodes", spec]

    def maps(self, spec=NATIVE_SPEC):
        return self.cli("maps", *(self.native_args(spec) + ["--out-dir", str(self.out)]))

    def native_ctx(self):
        return self.py.Context(str(self.committee), str(self.genesis), NATIVE_SPEC, None, native=True)

    def rendered(self, name):
        return (NATIVE / "rendered" / (name + ".network-config")).read_text()

    def golden(self, name):
        return self.yaml.safe_load((NATIVE / "golden" / name).read_text())

    def edit(self, path, old, new):
        text = path.read_text()
        self.assertEqual(text.count(old), 1, old)
        path.write_text(text.replace(old, new))


class NativeMapsTests(NativeCase):
    def test_maps_writes_the_golden_files(self):
        p = self.maps()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        self.assertEqual(sorted(os.listdir(str(self.out))), sorted(os.listdir(str(NATIVE / "golden"))))
        for name in os.listdir(str(self.out)):
            self.assertEqual((self.out / name).read_bytes(), (NATIVE / "golden" / name).read_bytes(), name)
        self.assertIn("wrote 11 file(s) under %s" % self.out, p.stdout)

    def test_every_map_key_is_a_plain_key_line_at_column_0(self):
        for path in sorted((NATIVE / "golden").iterdir()):
            text = path.read_text()
            lines = text.split("\n")
            self.assertEqual(lines[-1], "", path.name)
            top = [line for line in lines[:-1] if not line.startswith("  ")]
            self.assertTrue(top, path.name)
            for line in lines[:-1]:
                self.assertFalse(line.startswith("?"), (path.name, line))
                self.assertNotIn(line, ("---", "..."), path.name)
            for line in top:
                self.assertRegex(line, r"^[A-Za-z0-9_][A-Za-z0-9_.-]*:$")
            self.assertEqual(self.py._syntax_errors(text, path.name), [])
            # Why the keys are written by hand: PyYAML's safe_dump writes these as `? key`.
            self.assertIn("\n? ", "\n" + self.yaml.safe_dump(self.yaml.safe_load(text)))

    def test_the_bootstrap_map_is_the_committee_bootstrap_servers_in_its_order(self):
        servers = self.yaml.safe_load((NATIVE / "committee.yaml").read_text())["bootstrap_servers"]
        ctx = self.native_ctx()
        self.assertEqual(sorted(servers), sorted(ctx.bls[n] for n in NATIVE_NODES[:4]))
        for name in NATIVE_NODES:
            got = self.golden(name + ".bootstrap-peers.yaml")
            self.assertEqual(got, servers)
            self.assertEqual(list(got), list(servers))

    def test_validators_and_the_observer_trust_the_rpc_node_and_it_trusts_none(self):
        ctx = self.native_ctx()
        info = self.yaml.safe_load((NATIVE / "observers" / "node6.yaml").read_text())["p2p_info"]
        want = {ctx.bls["node6"]: {"primary": info["primary"], "workers": {0: info["workers"][0]}}}
        for name in NATIVE_NODES[:5]:
            self.assertEqual(self.golden(name + ".trusted-nodes.yaml"), want)
        self.assertFalse((NATIVE / "golden" / "node6.trusted-nodes.yaml").exists())

    def test_a_stale_trusted_map_is_removed_and_none_is_written_without_an_rpc_node(self):
        self.out.mkdir()
        stale = self.out / "node6.trusted-nodes.yaml"
        stale.write_text("stale\n")
        p = self.maps()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(stale.exists())
        self.assertIn("removed stale %s (node6 gets no trusted-nodes map)" % stale, p.stdout)
        p = self.maps(",".join(NATIVE_SPEC.split(",")[:5]))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.count("removed stale "), 5)
        self.assertEqual(sorted(os.listdir(str(self.out))), sorted(n + ".bootstrap-peers.yaml" for n in NATIVE_NODES))


class NativeValidateTests(NativeCase):
    def native_errors(self, name, text):
        errs, _ = self.py.native_errors(self.native_ctx(), name, text, "nc")
        return errs

    def test_the_real_renderer_output_validates_for_each_role(self):
        for name, mode in (("node1", "Closed"), ("node5", "Closed"), ("node6", "Open")):
            path = NATIVE / "rendered" / (name + ".network-config")
            p = self.cli("validate", "--native", *(self.native_args() + ["--node", name, str(path)]))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stderr, "")
            self.assertEqual(len(p.stdout.splitlines()), 1, p.stdout)
            self.assertTrue(p.stdout.startswith("ok   %s is %s's native network-config (mode %s," % (path, name, mode)))

    def test_the_rendered_entries_are_the_map_files_two_spaces_deeper(self):
        for name in ("node1", "node5", "node6"):
            text = self.rendered(name)
            for key, suffix in (("committee_peers", "bootstrap-peers"), ("trusted_nodes", "trusted-nodes")):
                path = NATIVE / "golden" / ("%s.%s.yaml" % (name, suffix))
                if not path.exists():
                    self.assertNotIn(key + ":", text)
                    continue
                body = "".join("  %s\n" % line for line in path.read_text().splitlines())
                self.assertIn("%s:\n%s" % (key, body), text)

    def test_content_is_compared_not_bytes(self):
        cfg = self.yaml.safe_load(self.rendered("node1"))
        cfg["admission"]["snapshot_max_age_secs"] = 300
        cfg["libp2p_config"] = {"max_rpc_message_size": 1048576}
        text = self.yaml.safe_dump(cfg, sort_keys=True)  # `? key` keys, `null`, another order
        self.assertNotEqual(text, self.rendered("node1"))
        errs, others = self.py.native_errors(self.native_ctx(), "node1", text, "nc")
        self.assertEqual(errs, [])
        self.assertEqual(others, ["libp2p_config"])

    def test_each_compared_field_fails_with_its_own_message(self):
        bls = self.native_ctx().bls
        short = self.py._short
        n1, n6 = self.rendered("node1"), self.rendered("node6")
        lines1, lines6 = n1.splitlines(), n6.splitlines()
        servers = self.yaml.safe_load((NATIVE / "committee.yaml").read_text())["bootstrap_servers"]
        n3 = servers[bls["node3"]]["primary"]
        s, e = entry_span(lines1, "committee_peers", bls["node4"])
        w = lines1.index("    workers:", s, e)
        two_workers = "\n".join(lines1[:e] + lines1[w + 1:e] + lines1[e:]) + "\n"
        trusted = lines1[slice(*top_span(lines1, "trusted_nodes"))]
        rpc6 = next(line for line in trusted if line.strip().startswith("network_address: ")).split(": ", 1)[1]
        cases = (
            ("node1", n1.replace("  mode: Closed\n", "  mode: Open\n"),
             "nc admission.mode: found 'Open', want 'Closed' (node1 is a validator)"),
            ("node6", n6.replace("  mode: Open\n", "  mode: Closed\n"),
             "nc admission.mode: found 'Closed', want 'Open' (node6 is an rpc node)"),
            ("node1", n1.replace("  mode: Closed\n", "  snapshot_max_age_secs: 300\n"),
             "nc admission: missing key 'mode'"),
            ("node1", without(lines1, top_span(lines1, "admission")),
             "nc: missing top-level key 'admission' (want mode Closed)"),
            ("node1", without(lines1, entry_span(lines1, "committee_peers", bls["node2"])),
             "nc committee_peers: missing node2 "),
            ("node1", n1.replace(n3["network_address"], n3["network_address"].replace("/49590/", "/49591/")),
             "nc committee_peers[node3 %s].primary.network_address: found " % short(bls["node3"])),
            ("node1", n1.replace(n3["network_key"], servers[bls["node2"]]["primary"]["network_key"]),
             "nc committee_peers[node3 %s].primary.network_key: found " % short(bls["node3"])),
            ("node1", two_workers, "nc committee_peers[node4 %s].workers: 2 entries, want 1" % short(bls["node4"])),
            ("node1", without(lines1, top_span(lines1, "committee_peers")),
             "nc: missing top-level key 'committee_peers' (want 4 entries)"),
            ("node1", n1.replace(rpc6, rpc6.replace("/49590/", "/49591/")),
             "nc trusted_nodes[node6 %s].primary.network_address: found " % short(bls["node6"])),
            ("node1", without(lines1, top_span(lines1, "trusted_nodes")),
             "nc: missing top-level key 'trusted_nodes' (want 1 entries)"),
            ("node6", "\n".join(lines6[:2] + trusted + lines6[2:]) + "\n",
             "nc: unexpected top-level key 'trusted_nodes': node6 gets no trusted-nodes map (an rpc node)"),
            ("node1", n1 + "trusted_peers: {}\n",
             "nc: unknown top-level key 'trusted_peers': the node silently ignores it (did you mean 'trusted_nodes'?)"),
        )
        for name, text, want in cases:
            with self.subTest(want=want):
                self.assertNotEqual(text, n1 if name == "node1" else n6)
                errs = self.native_errors(name, text)
                self.assertEqual(len(errs), 1, errs)
                self.assertTrue(errs[0].startswith(want), errs)

    def test_cli_failure_is_exit_1_with_one_line_per_difference(self):
        bad = self.tmp / "network-config"
        bad.write_text(self.rendered("node5").replace("  mode: Closed\n", "  mode: Grace\n") + "admision: {}\n")
        p = self.cli("validate", "--native", *(self.native_args() + ["--node", "node5", str(bad)]))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")
        self.assertEqual(p.stderr.splitlines(), [
            "FAIL %s: unknown top-level key 'admision': the node silently ignores it (did you mean 'admission'?)" % bad,
            "FAIL %s admission.mode: found 'Grace', want 'Closed' (node5 is an observer)" % bad])


class NativeRefusalTests(NativeCase):
    ONLY = "role rpc is accepted only by `maps` and `validate --native`"

    def test_render_and_validate_refuse_the_rpc_role(self):
        p = self.cli("render", *(self.native_args() + ["--hub", "node1", "--out-dir", str(self.out)]))
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL --nodes: 'node6=rpc': " + self.ONLY, p.stderr)
        self.assertFalse(self.out.exists())
        p = self.cli("validate", *(self.native_args() + ["--hub", "node1", "--node", "node1",
                                                         str(NATIVE / "rendered" / "node1.network-config")]))
        self.assertEqual(p.returncode, 1)
        self.assertIn(self.ONLY, p.stderr)
        with self.assertRaises(self.py.ConfigError):
            self.py.Context(str(self.committee), str(self.genesis), NATIVE_SPEC, "node1")

    def test_validate_without_native_needs_the_hub_and_native_takes_no_existing(self):
        p = self.cli("validate", *(self.context_args()[:-2] + ["--node", "node1", str(GOLDEN / "node1.yaml")]))
        self.assertEqual(p.returncode, 2)
        self.assertIn("the following arguments are required: --hub", p.stderr)
        p = self.cli("validate", "--native", *(self.native_args() + [
            "--node", "node1", "--existing", str(GOLDEN / "node1.yaml"), str(NATIVE / "rendered" / "node1.network-config")]))
        self.assertEqual(p.returncode, 2)
        self.assertIn("--existing does not apply to --native", p.stderr)

    def test_dns_multiaddrs_are_refused_naming_the_node(self):
        node6 = self.genesis / "observers" / "node6.yaml"
        self.edit(node6, "/ip4/192.0.2.16/udp/49590/", "/dns/rpc.example.invalid/udp/49590/")
        p = self.maps()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL node6 primary.network_address '/dns/rpc.example.invalid/udp/49590/quic-v1/p2p/", p.stderr)
        self.assertIn("is a /dns multiaddr: the admission maps take /ip4/... only", p.stderr)
        self.assertFalse(self.out.exists())
        shutil.copyfile(str(NATIVE / "observers" / "node6.yaml"), str(node6))
        for path in (self.committee, self.genesis / "validators" / "node2.yaml"):
            self.edit(path, "/ip4/192.0.2.12/udp/49594/", "/dns4/node2.example.invalid/udp/49594/")
        p = self.maps()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL node2 workers[0].network_address '/dns4/node2.example.invalid/", p.stderr)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
