"""tools/params-apply.sh against fake nodes.

A fake gcloud (fixtures/params-apply/gcloud.py) is first on PATH. For `gcloud compute ssh <node>`
it runs the script params-apply.sh sends on stdin with bash, on a fake node: a directory holding
the node's launch file (by default a v2 node: /usr/local/libexec/telcoin/tn-start-docker and
/etc/telcoin/.node-meta from fixtures/params-apply/v2-*; else the pre-v2 /opt/telcoin wrapper),
its datadir with parameters.yaml and /var/lib/bench-logs, with stubs for docker, systemctl,
systemd-run, curl, date and sleep, and a stub of the v2 library (the committee guard and the epoch
timing, fixtures/params-apply/node-lib-common.sh). So the remote scripts themselves run: the
datadir lookup, the guard samples, the epoch wait, the log save, the in-place rewrite, the
stop/start unit, the health wait and the readback of the `node switches` line. Every gcloud call
is logged with its argv and stdin.

Run: python3 -m unittest discover -s benchmark/tests -v
"""
import datetime
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
DEPLOYMENT = BENCH.parent / "tn-node-deployment"   # the pinned submodule (absent in a plain CI checkout)
TOOL = BENCH / "tools" / "params-apply.sh"
ARMS = BENCH / "arms"
TSV = ARMS / "switches.tsv"
FIX = TESTS / "fixtures" / "params-apply"
COMMITTED = BENCH / "consensus-parameters.yaml"
# The v2 fixtures name the node's real datadir; a fake node gets its own in its place.
V2_DATADIR = "/var/lib/telcoin"
V2_START = "usr/local/libexec/telcoin/tn-start-docker"
V2_META = "etc/telcoin/.node-meta"
LEGACY_WRAPPER = "opt/telcoin/start-telcoin.sh"
PROJECT = "example-proj"
ZONE = "us-west2-a"
PRE_TS = "ts=2026-10-06T11:50:00.200000000Z"   # the time of the switches line in a fake node's pre.log
UTC_RE = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"


def pin_params(text, **values):
    """<text> with each key's `key: value` line set to the given value. A key that is not exactly
    one such line (absent, or a secs/nanos block the tool refuses) fails loudly here."""
    for key, value in values.items():
        text, n = re.subn(r"^%s: .*$" % re.escape(key), "%s: %s" % (key, value), text, flags=re.M)
        if n != 1:
            raise AssertionError("%s: want one '%s: <value>' line, found %d" % (COMMITTED, key, n))
    return text


# Every fake node's parameters.yaml: the committed fleet file (each key, comment and line the tool
# must carry through a rewrite) with its timing values pinned, so the expectations below are the
# test's own and do not move when the committed values do.
YAML = pin_params(COMMITTED.read_text(), max_header_delay="500ms", min_header_delay="250ms",
                  max_batch_delay="250ms")


def switch_rows():
    """switches.tsv as [{key, type, default, arm_values, topic, optional}] in row order."""
    lines = TSV.read_text().splitlines()
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


SWITCHES = switch_rows()
DEFAULTS = {r["key"]: r["default"] for r in SWITCHES}
DUR_KEYS = {r["key"] for r in SWITCHES if r["type"] == "dur"}


def humantime(value):
    """A duration as the node renders it on its switches line: 150ms, 2s, and 0s for zero."""
    m = re.match(r"^([0-9]+)(ms|s)$", value)
    ms = int(m.group(1)) * (1 if m.group(2) == "ms" else 1000)
    return "0s" if ms == 0 else ("%ds" % (ms // 1000) if ms % 1000 == 0 else "%dms" % ms)


def rendered(values):
    """{key: value} as the node prints it (durations in humantime form)."""
    return {k: (humantime(v) if k in DUR_KEYS else v) for k, v in values.items()}


def switches_line(values=None, drop=(), ts=PRE_TS):
    """A `node switches` line in the names contract's shape: every switch in row order with its
    effective value as the node renders it (its default unless <values> gives it; durations in
    humantime form, 0s for zero); <drop> leaves keys out (an image that does not know them)."""
    vals = dict(DEFAULTS)
    vals.update(values or {})
    vals = rendered(vals)
    fields = " ".join("%s=%s" % (r["key"], vals[r["key"]]) for r in SWITCHES if r["key"] not in drop)
    return '%s level=info target=node::switches message="node switches" %s' % (ts, fields)


def _install(src, dest):
    shutil.copyfile(str(src), str(dest))
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def load_make_bundle():
    """report/make_bundle.py as a module (it imports provenance and scrub beside it)."""
    sys.path.insert(0, str(BENCH / "report"))
    try:
        spec = importlib.util.spec_from_file_location("pa_make_bundle", str(BENCH / "report" / "make_bundle.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.pop(0)


class ParamsApplyCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="params-apply-test."))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.bin = self.tmp / "bin"
        self.nodebin = self.tmp / "node-bin"
        self.nodes = self.tmp / "nodes"
        self.scratch = self.tmp / "scratch"
        self.scripts = self.tmp / "node-scripts"
        for d in (self.bin, self.nodebin, self.nodes, self.scratch, self.scripts / "lib"):
            d.mkdir(parents=True)
        _install(FIX / "gcloud.py", self.bin / "gcloud")
        _install(FIX / "node-docker.py", self.nodebin / "docker")
        for name in ("systemctl", "systemd-run", "curl", "date", "sleep"):
            _install(FIX / ("node-%s.sh" % name), self.nodebin / name)
        shutil.copyfile(str(FIX / "node-lib-common.sh"), str(self.scripts / "lib" / "common.sh"))
        self.log = self.tmp / "gcloud-calls.jsonl"
        self.results = self.tmp / "results"

    # --- fake nodes, files, runs ---------------------------------------------------------

    def node(self, name, role="validator", mode="healthy", yaml=YAML, launch="v2", meta=True, live=None,
             live_drop=(), pre_switches=True):
        """A fake node. launch: "v2" (tn-start-docker), "legacy" (the pre-v2 wrapper), "both" or
        None (then the nodes-file line or .node-meta must name the host datadir). meta: True (the
        fixture .node-meta), False (none) or the file's text. Every file binds or names the node's
        own data dir. Its pre-restart log ends with the `node switches` line of its current start
        (every default, overlaid with <live>, without <live_drop>), unless pre_switches is False."""
        d = self.nodes / name
        for sub in ("data", "var/lib/bench-logs", "state", "tmp"):
            (d / sub).mkdir(parents=True)
        (d / "data" / "parameters.yaml").write_text(yaml)
        (d / "data" / "first-parameters.yaml").write_text(yaml)
        if launch in ("v2", "both"):
            self.put(d / V2_START, (FIX / "v2-tn-start-docker").read_text().replace(V2_DATADIR, str(d / "data")))
        if launch in ("legacy", "both"):
            self.put(d / LEGACY_WRAPPER,
                     "#!/usr/bin/env bash\n# Auto-generated by setup-node.sh (--datadir in a comment is not the flag)\n"
                     "exec docker run --rm \\\n--name telcoin \\\n-v %s:/home/nonroot \\\n-v /etc/tn:/etc/telcoin:ro \\\n"
                     "img \\\ntelcoin node \\\n--datadir /home/nonroot \\\n--log.stdout.format log-fmt \\\n-vvv \\\n"
                     "--http --http.addr 0.0.0.0\n" % (d / "data"))
        if meta:
            text = (FIX / "v2-node-meta").read_text() if meta is True else meta
            self.put(d / V2_META, text.replace(V2_DATADIR, str(d / "data")))
        (d / "role").write_text(role)
        (d / "mode").write_text(mode)
        pre = (FIX / ("node-log-pre-%s.txt" % role)).read_text()
        if pre_switches:
            pre += switches_line(live, live_drop) + "\n"
        (d / "pre.log").write_text(pre)
        return d

    @staticmethod
    def put(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def retarget(self, name, rel):
        """Point the node's file <rel> at <node>/decoy (a directory without parameters.yaml)
        instead of its data dir: a run that reads the datadir from that file fails."""
        d = self.nodes / name
        (d / "decoy").mkdir(exist_ok=True)
        p = d / rel
        text = p.read_text()
        self.assertIn(str(d / "data"), text)
        p.write_text(text.replace(str(d / "data"), str(d / "decoy")))

    def nodes_file(self, *lines, name="nodes.txt"):
        p = self.tmp / name
        p.write_text("# name zone project role [hostdatadir]\n\n" + "\n".join(lines) + "\n")
        return p

    def line(self, name, role="validator", datadir=False, project=PROJECT):
        return " ".join([name, ZONE, project, role] + ([str(self.nodes / name / "data")] if datadir else []))

    def manifest(self, extra=None):
        self.results.mkdir(exist_ok=True)
        m = {"schema": "tn-bench-manifest/v1", "run_id": "rtest-pa", "notes": []}
        m.update(extra or {})
        (self.results / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
        return self.results / "manifest.json"

    def arm_file(self, text, name="t1.arm", where=None):
        p = (where or self.tmp) / name
        p.write_bytes(text.encode("latin-1") if isinstance(text, str) else text)
        return p

    def run_tool(self, *args, tool=TOOL, **env):
        e = dict(os.environ)
        e.update({"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
                  "PA_SHIM_LOG": str(self.log), "PA_NODES": str(self.nodes), "PA_NODE_BIN": str(self.nodebin),
                  "PA_SWITCHES_TSV": str(TSV), "PARAMS_APPLY_NODE_SCRIPTS_DIR": str(self.scripts),
                  "PARAMS_APPLY_HEALTH_SECS": "30", "PARAMS_APPLY_RETRY_SECS": "0", "PARAMS_APPLY_GUARD_SECS": "0",
                  "PARAMS_APPLY_GUARD_DEFER_SECS": "0", "TMPDIR": str(self.scratch)})
        e.update(env)
        return subprocess.run(["bash", str(tool)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=e, cwd=str(self.tmp), timeout=300, universal_newlines=True)

    def tree(self, tsv=None, hook=None):
        """A copy of the tool in <tmp>/tree/benchmark/tools beside its own arms/switches.tsv (<tsv>,
        else the real one), so the copy's repo root is <tmp>/tree. <hook>: the text that replaces the
        host-steps hook function (from `host_steps_hook() {` to the end-of-hook marker)."""
        root = self.tmp / "tree"
        (root / "benchmark" / "tools").mkdir(parents=True, exist_ok=True)
        (root / "benchmark" / "arms").mkdir(parents=True, exist_ok=True)
        text = TOOL.read_text()
        if hook is not None:
            text, n = re.subn(r"(?ms)^host_steps_hook\(\) \{.*?^(# ===== end of HOOK)", lambda m: hook + m.group(1), text)
            self.assertEqual(n, 1)
        (root / "benchmark" / "tools" / "params-apply.sh").write_text(text)
        (root / "benchmark" / "arms" / "switches.tsv").write_text(tsv if tsv is not None else TSV.read_text())
        return root

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines() if l.strip()]

    @staticmethod
    def phase(call):
        m = re.match(r"# params-apply phase (A|B) on ", call["stdin"])
        return m.group(1) if m else None

    def phase_calls(self, ph):
        return sorted((c for c in self.calls() if self.phase(c) == ph), key=lambda c: c["start"])

    def yaml_of(self, name):
        return (self.nodes / name / "data" / "parameters.yaml").read_text()

    def node_calls(self, name):
        p = self.nodes / name / "calls.log"
        return p.read_text().splitlines() if p.exists() else []

    def ok_lines(self, p):
        return [l for l in p.stdout.splitlines() if l.startswith("PARAMS_OK ")]

    def tagged(self, p, tag):
        return [l for l in p.stdout.splitlines() if l.startswith(tag + " ")]

    def arms(self, path=None):
        return json.loads((path or (self.results / "manifest.json")).read_text())["param_arms"]

    def three(self, **modes):
        """bench-validator-01..03, each with <modes>[name] keyword arguments to node()."""
        for i in (1, 2, 3):
            n = "bench-validator-0%d" % i
            self.node(n, **modes.get(n, {}))
        return self.nodes_file(*(self.line("bench-validator-0%d" % i) for i in (1, 2, 3)))


class KeyListTests(ParamsApplyCase):

    def test_timing_keys_match_the_config_literal(self):
        tool = re.search(r'^readonly PARAM_KEYS="([^"]+)"', TOOL.read_text(), re.M).group(1)
        cfg = re.search(r'^export BENCH_NODE_PARAM_KEYS="([^"]+)"', (BENCH / "config.sh").read_text(), re.M).group(1)
        self.assertEqual(tool.split(), cfg.split())

    def test_known_keys_are_the_timing_keys_and_the_switches_tsv_rows(self):
        cfg = (BENCH / "config.sh").read_text()
        timing = re.search(r'^export BENCH_NODE_PARAM_KEYS="([^"]+)"', cfg, re.M).group(1).split()
        sw = re.search(r'^export BENCH_NODE_SWITCH_KEYS="([^"]+)"', cfg, re.M).group(1).split()
        self.assertEqual(sw, ["%s:%s" % (r["type"], r["key"]) for r in SWITCHES])
        self.node("bench-validator-01")
        p = self.run_tool("--nodes", str(self.nodes_file(self.line("bench-validator-01"))),
                          "--set", "all:no_such_key=1", "--arm", "x")
        self.assertEqual(p.returncode, 2, p.stderr)
        known = re.search(r"\(known: ([^)]*)\)", p.stderr).group(1).split()
        self.assertEqual(known, [k.split(":", 1)[1] for k in timing + sw])
        self.assertEqual(self.calls(), [])

    def test_the_switch_keys_come_from_the_tsv(self):
        # A copy of the tool beside a tsv with one more row knows that key; the real one does not.
        extra = TSV.read_text() + "extra_switch\tbool\tfalse\ttrue\textra-topic\tno\n"
        root = self.tree(tsv=extra)
        nf = self.nodes_file(self.line("bench-validator-01"))
        args = ("--nodes", str(nf), "--set", "all:extra_switch=true", "--arm", "x", "--dry-run")
        p = self.run_tool(*args, tool=root / "benchmark" / "tools" / "params-apply.sh")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("setp extra_switch true\n", p.stdout)
        p = self.run_tool(*args)
        self.assertEqual(p.returncode, 2)
        self.assertIn("unknown key 'extra_switch'", p.stderr)
        # A broken registry stops the tool before anything else.
        root = self.tree(tsv=TSV.read_text().replace("\tbool\tfalse\ttrue\tvoter-lock\tno", "\tflag\tfalse\ttrue\tvoter-lock\tno"))
        p = self.run_tool(*args, tool=root / "benchmark" / "tools" / "params-apply.sh")
        self.assertEqual(p.returncode, 2)
        self.assertRegex(p.stderr, r"switches\.tsv:4: type 'flag' is not bool, int or dur")
        self.assertEqual(self.calls(), [])


class SetSwitchTests(ParamsApplyCase):
    """--set with node switches: the tsv's arm values or the default; bools written as YAML booleans."""

    def test_switch_values_are_checked_against_the_tsv(self):
        nf = self.nodes_file(self.line("bench-validator-01"))
        for spec in ("all:quorum_exec_block_starved_rounds=0", "all:quorum_exec_block_starved_rounds=4",
                     "all:vote_queue_fix=true", "all:vote_queue_fix=false", "all:parent_grace=150ms",
                     "all:recovery_threads=3"):
            p = self.run_tool("--nodes", str(nf), "--set", spec, "--arm", "x", "--dry-run")
            self.assertEqual(p.returncode, 0, (spec, p.stderr))
            self.assertIn("setp %s %s\n" % tuple(spec[4:].split("=")), p.stdout)
        for spec, needle in (
                ("all:quorum_exec_block_starved_rounds=5", "is not one of its values (0,4, or the default 0;"),
                ("all:vote_queue_fix=yes", "vote_queue_fix=yes is not one of its values (true, or the default false"),
                ("all:parent_grace=150", "parent_grace=150 is not one of its values"),
                ("all:recovery_threads=03", "recovery_threads=03 is not one of its values")):
            p = self.run_tool("--nodes", str(nf), "--set", spec, "--arm", "x", "--dry-run")
            self.assertEqual(p.returncode, 2, spec)
            self.assertIn(needle, p.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_bool_switch_is_written_as_a_yaml_boolean_and_read_back(self):
        self.node("bench-validator-01")
        nf = self.nodes_file(self.line("bench-validator-01"))
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--set", "all:vote_queue_fix=true",
                          "--arm", "s1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("\nvote_queue_fix: true  # bench-override\n", self.yaml_of("bench-validator-01"))
        ok = self.tagged(p, "SWITCHES_OK")
        self.assertEqual(len(ok), 1)
        self.assertIn(" vote_queue_fix=true ", ok[0])
        arm = self.arms(mpath)[0]
        self.assertEqual(arm["nodes"], {"bench-validator-01": {"vote_queue_fix": "true"}})
        self.assertEqual((arm["via"], arm["file"]), ("params-apply", None))
        self.assertNotIn("switches", arm)
        self.assertNotIn("sha256", arm)

    def test_a_switch_at_its_default_is_not_written_when_the_file_leaves_it_out(self):
        self.node("bench-validator-01")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:quorum_exec_block_starved_rounds=0", "--arm", "s0")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("arm s0 recorded: 0 node(s) restarted, 1 already at these values", p.stdout)
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)
        self.assertEqual(self.phase_calls("B"), [])


class ApplyTests(ParamsApplyCase):

    def test_arm_applies_serially_observer_first_and_records_the_arm(self):
        for n in ("bench-validator-01", "bench-validator-02"):
            self.node(n)
        self.node("bench-observer-11", role="observer", launch=None, meta=False)
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-validator-02"),
                             self.line("bench-observer-11", "observer", datadir=True))
        mpath = self.manifest({"param_arms": []})
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--set", "all:max_header_delay=600ms,min_header_delay=300ms",
                          "--set", "bench-validator-02:min_header_delay=250ms", "--arm", "a1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.ok_lines(p), [
            "PARAMS_OK bench-observer-11 max=600 min=300 batch=250 thr=5 vote=-",
            "PARAMS_OK bench-validator-01 max=600 min=300 batch=250 thr=5 vote=-",
            "PARAMS_OK bench-validator-02 max=600 min=250 batch=250 thr=5 vote=-"])
        # Phase A read all three before phase B touched anything; phase B one node at a time.
        a, b = self.phase_calls("A"), self.phase_calls("B")
        self.assertEqual(sorted(c["node"] for c in a), ["bench-observer-11", "bench-validator-01", "bench-validator-02"])
        self.assertEqual([c["node"] for c in b], ["bench-observer-11", "bench-validator-01", "bench-validator-02"])
        self.assertLessEqual(max(c["end"] for c in a), b[0]["start"])
        for prev, nxt in zip(b, b[1:]):
            self.assertLessEqual(prev["end"], nxt["start"])
        # Each restart only after the previous node's PARAMS_OK.
        out = p.stdout
        self.assertLess(out.index("PARAMS_OK bench-observer-11"), out.index("phase B 2/3: bench-validator-01"))
        self.assertLess(out.index("PARAMS_OK bench-validator-01"), out.index("phase B 3/3: bench-validator-02"))
        for c in a + b:
            self.assertEqual(c["argv"][:3], ["compute", "ssh", c["node"]])
            for flag in ("--zone=%s" % ZONE, "--project=%s" % PROJECT, "--tunnel-through-iap", "--command=sudo bash -s"):
                self.assertIn(flag, c["argv"])
        # The file: rewritten in place, marked; the original kept as .bak and .bak-<UTC>.
        y = self.yaml_of("bench-validator-02").splitlines()
        # min_header_delay was 250ms already there: only max is rewritten.
        want = [l.replace("max_header_delay: 500ms", "max_header_delay: 600ms  # bench-override")
                for l in YAML.splitlines()]
        self.assertEqual(y, want)
        y1 = self.yaml_of("bench-validator-01")
        self.assertIn("\nmax_header_delay: 600ms  # bench-override\nmin_header_delay: 300ms  # bench-override\n", y1)
        data = self.nodes / "bench-validator-01" / "data"
        self.assertEqual((data / "parameters.yaml.bak").read_text(), YAML)
        baks = sorted(data.glob("parameters.yaml.bak-*"))
        self.assertEqual(len(baks), 1)
        self.assertRegex(baks[0].name, r"^parameters\.yaml\.bak-\d{8}T\d{6}Z$")
        self.assertEqual(baks[0].read_text(), YAML)
        # The container log was saved before the stop, under the harness's naming scheme.
        for n in ("bench-validator-01", "bench-observer-11"):
            saved = list((self.nodes / n / "var/lib/bench-logs").glob("*.log.gz"))
            self.assertEqual(len(saved), 1, n)
            self.assertRegex(saved[0].name, r"^telcoin-pre-arm-a1-\d{8}T\d{6}Z\.log\.gz$")
            with gzip.open(str(saved[0]), "rt") as fh:
                self.assertEqual(fh.read(), (self.nodes / n / "pre.log").read_text())
            calls = self.node_calls(n)
            self.assertLess(calls.index("docker logs telcoin"), calls.index("systemctl stop telcoin"), n)
            self.assertNotIn("systemctl restart telcoin", calls, n)
        # The record: one open arm, every node with its values as written, and the bench-6 fields.
        m = json.loads(mpath.read_text())
        self.assertEqual(m["run_id"], "rtest-pa")
        self.assertEqual(len(m["param_arms"]), 1)
        arm = m["param_arms"][0]
        self.assertEqual((arm["name"], arm["end"], arm["via"], arm["file"]), ("a1", None, "params-apply", None))
        self.assertRegex(arm["begin"], UTC_RE)
        self.assertRegex(arm["ready"], UTC_RE)
        self.assertEqual(arm["nodes"], {
            "bench-observer-11": {"max_header_delay": "600ms", "min_header_delay": "300ms"},
            "bench-validator-01": {"max_header_delay": "600ms", "min_header_delay": "300ms"},
            "bench-validator-02": {"max_header_delay": "600ms", "min_header_delay": "250ms"}})
        self.assertEqual(arm["guard"], {n: {"samples": 1, "refused": 0} for n in arm["nodes"]})
        self.assertEqual(sorted(arm["restart_secs"]), sorted(arm["nodes"]))
        self.assertEqual((arm["host"], arm["marks"]), ([], []))
        self.assertNotIn("failed", arm)
        self.assertEqual(self.tagged(p, "ARM_READY"), ["ARM_READY a1 ready=%s restarted=3 nodes=3" % arm["ready"]])

    def test_unhealthy_node_stops_the_run_and_later_nodes_are_untouched(self):
        nf = self.three(**{"bench-validator-02": {"mode": "unhealthy"}})
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--set", "all:max_header_delay=600ms", "--arm", "a1")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.ok_lines(p), ["PARAMS_OK bench-validator-01 max=600 min=250 batch=250 thr=5 vote=-"])
        self.assertIn("bench-validator-02 did not come back", p.stderr)
        self.assertIn("no consensus progress", p.stderr)
        fail = self.tagged(p, "PA_FAIL")
        self.assertEqual(len(fail), 1)
        self.assertTrue(fail[0].startswith("PA_FAIL bench-validator-02 no consensus progress within 30 s"), fail)
        self.assertIn("gcloud compute ssh bench-validator-02 --zone=%s --project=%s --tunnel-through-iap"
                      % (ZONE, PROJECT), p.stderr)
        self.assertIn("rollback: sudo cp -p ", p.stderr)
        self.assertIn("later nodes were not touched: bench-validator-03", p.stderr)
        self.assertIn("to resume, re-run with --arm <new name>", p.stderr)
        self.assertEqual([c["node"] for c in self.phase_calls("B")], ["bench-validator-01", "bench-validator-02"])
        self.assertEqual(self.yaml_of("bench-validator-03"), YAML)
        self.assertFalse((self.nodes / "bench-validator-03" / "state" / "restarted").exists())
        self.assertNotIn("systemctl stop telcoin", self.node_calls("bench-validator-03"))
        self.assertEqual(self.tagged(p, "ARM_READY"), [])
        arm = self.arms(mpath)[0]
        self.assertEqual(arm["failed"], "bench-validator-02")
        self.assertEqual(sorted(arm["nodes"]), ["bench-validator-01", "bench-validator-02"])
        self.assertNotIn("ready", arm)

    def test_a_node_that_boots_with_other_values_fails(self):
        self.node("bench-validator-01", mode="stale")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "a1")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("booted with max header delay 500 ms but", p.stdout + p.stderr)
        self.assertIn("does not read this file", p.stderr)
        self.assertEqual(self.ok_lines(p), [])

    def test_arms_chain_cumulatively_and_close(self):
        self.node("bench-validator-01")
        self.node("bench-observer-11", role="observer")
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-observer-11", "observer"))
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--set", "all:max_header_delay=600ms,min_header_delay=300ms", "--arm", "a1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for n in ("bench-validator-01", "bench-observer-11"):   # the next restart starts from a fresh container
            (self.nodes / n / "state" / "restarted").unlink()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--set", "bench-validator-01:min_header_delay=250ms", "--arm", "a2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        # Cumulative: a2 changes min on validator-01 only; its max stays a1's. The observer is unchanged.
        self.assertEqual(self.ok_lines(p), ["PARAMS_OK bench-validator-01 max=600 min=250 batch=250 thr=5 vote=-"])
        self.assertIn("bench-observer-11", p.stdout)
        self.assertIn("no change; not restarted", p.stdout)
        self.assertEqual([c["node"] for c in self.phase_calls("B")],
                         ["bench-observer-11", "bench-validator-01", "bench-validator-01"])
        arms = self.arms(mpath)
        self.assertEqual([a["name"] for a in arms], ["a1", "a2"])
        self.assertEqual(arms[0]["end"], arms[1]["begin"])
        self.assertIsNone(arms[1]["end"])
        self.assertEqual(arms[1]["nodes"], {"bench-validator-01": {"min_header_delay": "250ms"}})
        # A used name is refused before any node is contacted.
        before = len(self.calls())
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--set", "all:max_header_delay=700ms", "--arm", "a1")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("arm 'a1' is already recorded", p.stderr)
        self.assertEqual(len(self.calls()), before)
        # --close-arm: end = now; contacts nothing; a second close finds no open arm.
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--close-arm", "a2")
        self.assertEqual(p.returncode, 0, p.stderr)
        arms = self.arms(mpath)
        self.assertRegex(arms[1]["end"], UTC_RE)
        self.assertEqual(arms[0]["end"], arms[1]["begin"])
        self.assertEqual(len(self.calls()), before)
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--close-arm", "a2")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no open arm named 'a2'", p.stderr)

    def test_without_a_manifest_the_arm_goes_to_param_arms_json_beside_the_nodes_file(self):
        self.node("bench-validator-01")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_batch_delay=200ms", "--arm", "b1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads((self.tmp / "param-arms.json").read_text())
        self.assertEqual([a["name"] for a in doc["param_arms"]], ["b1"])
        self.assertEqual(doc["param_arms"][0]["nodes"], {"bench-validator-01": {"max_batch_delay": "200ms"}})
        self.assertEqual(self.ok_lines(p), ["PARAMS_OK bench-validator-01 max=500 min=250 batch=200 thr=5 vote=-"])

    def test_nothing_to_change_restarts_nothing_and_still_records_the_arm(self):
        self.node("bench-validator-01")
        self.node("bench-observer-11", role="observer")
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-observer-11", "observer"))
        prev = {"name": "a0", "begin": "2026-10-06T20:00:00Z", "end": None,
                "nodes": {"bench-validator-01": {"max_header_delay": "500ms"}}}
        mpath = self.manifest({"param_arms": [prev]})
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--set", "all:max_header_delay=500ms,min_header_delay=250ms", "--arm", "base")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("arm base recorded: 0 node(s) restarted, 2 already at these values", p.stdout)
        # Every node's current values, from the file phase A read; no PARAMS_OK (nothing restarted).
        self.assertEqual(sorted(l for l in p.stdout.splitlines() if l.startswith("PARAMS_CURRENT ")), [
            "PARAMS_CURRENT bench-observer-11 max=500 min=250 batch=250 thr=5 vote=-",
            "PARAMS_CURRENT bench-validator-01 max=500 min=250 batch=250 thr=5 vote=-"])
        self.assertEqual(self.ok_lines(p), [])
        # Phase A read both nodes; nothing else was sent, and no node saw a restart or a rewrite.
        self.assertEqual(sorted(c["node"] for c in self.phase_calls("A")), ["bench-observer-11", "bench-validator-01"])
        self.assertEqual(self.phase_calls("B"), [])
        self.assertEqual(len(self.calls()), 2)
        for n in ("bench-validator-01", "bench-observer-11"):
            self.assertNotIn("systemctl stop telcoin", self.node_calls(n), n)
            self.assertEqual(self.yaml_of(n), YAML, n)
            self.assertEqual(list((self.nodes / n / "var/lib/bench-logs").iterdir()), [], n)
        # The record: the shape of a restarted arm, plus no_restart, ready = begin; it closes the arm open before it.
        arms = self.arms(mpath)
        self.assertEqual([a["name"] for a in arms], ["a0", "base"])
        arm = arms[1]
        self.assertRegex(arm["begin"], UTC_RE)
        self.assertEqual(arms[0]["end"], arm["begin"])
        self.assertEqual(arm, {"name": "base", "begin": arm["begin"], "end": None, "via": "params-apply", "file": None,
                               "nodes": {
                                   "bench-validator-01": {"max_header_delay": "500ms", "min_header_delay": "250ms"},
                                   "bench-observer-11": {"max_header_delay": "500ms", "min_header_delay": "250ms"}},
                               "host": [], "restart_secs": {}, "guard": {}, "marks": [], "no_restart": True,
                               "ready": arm["begin"]})
        self.assertEqual(self.tagged(p, "ARM_READY"), ["ARM_READY base ready=%s restarted=0 nodes=2" % arm["begin"]])
        # --close-arm on it sets end and contacts nothing.
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--close-arm", "base")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        arms = self.arms(mpath)
        self.assertRegex(arms[1]["end"], UTC_RE)
        self.assertGreaterEqual(arms[1]["end"], arms[1]["begin"])
        self.assertEqual(len(self.calls()), 2)

    def test_nothing_to_change_on_a_stopped_node_records_nothing(self):
        self.node("bench-validator-01", mode="nocontainer")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=500ms", "--arm", "same")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("arm same NOT recorded", p.stderr)
        self.assertIn("bench-validator-01: the telcoin container is NOT running", p.stderr)
        self.assertEqual(self.phase_calls("B"), [])
        self.assertFalse((self.tmp / "param-arms.json").exists())

    def test_missing_container_is_noted_and_the_restart_still_checked(self):
        self.node("bench-validator-01", mode="nocontainer")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "a1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("no telcoin container: no log to save", p.stdout)
        self.assertIn("container NOT running", p.stdout)
        self.assertEqual(list((self.nodes / "bench-validator-01" / "var/lib/bench-logs").glob("*.log.gz")), [])
        self.assertEqual(len(self.ok_lines(p)), 1)

    def test_iap_refusal_is_retried_once(self):
        d = self.node("bench-validator-01")
        (d / "iap-refuse-once").write_text("")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "a1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("IAP refused the tunnel; retrying once", p.stderr)
        self.assertEqual([c["rc"] for c in self.phase_calls("A")], [255, 0])

    def test_validators_only_leaves_observers_out(self):
        self.node("bench-validator-01")
        self.node("bench-observer-11", role="observer")
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-observer-11", "observer"))
        p = self.run_tool("--nodes", str(nf), "--validators-only", "--set", "all:max_header_delay=600ms", "--arm", "a1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual({c["node"] for c in self.calls()}, {"bench-validator-01"})
        self.assertEqual(self.yaml_of("bench-observer-11"), YAML)
        p = self.run_tool("--nodes", str(nf), "--validators-only", "--set", "bench-observer-11:max_header_delay=600ms",
                          "--arm", "a2")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--validators-only leaves observers out", p.stderr)


class GuardTests(ParamsApplyCase):
    """The committee guard: a refusal is a sample; GT refusals in a row a deferral; two stop the run."""

    def guard_calls(self, name):
        return self.node_calls(name).count("tnlib tn_committee_down_guard")

    def test_refusals_are_resampled_until_one_passes(self):
        nf = self.three()
        (self.nodes / "bench-validator-02" / "guard").write_text("1 2 w 0")
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--set", "all:max_header_delay=600ms",
                          "--arm", "g1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.guard_calls("bench-validator-02"), 4)
        samples = [l.strip() for l in p.stdout.splitlines() if l.strip().startswith("PA_GUARD bench-validator-02 ")]
        self.assertEqual([re.search(r"sample=(\S+) rc=(\S+)", s).groups() for s in samples],
                         [("1/8", "1"), ("2/8", "2"), ("3/8", "blind"), ("4/8", "0")])
        self.assertIn("Refused.", samples[0])
        guard = self.arms(mpath)[0]["guard"]
        self.assertEqual(guard["bench-validator-02"], {"samples": 4, "refused": 3})
        self.assertEqual(guard["bench-validator-01"], {"samples": 1, "refused": 0})
        # The guard came before the stop.
        calls = self.node_calls("bench-validator-02")
        self.assertLess(max(i for i, c in enumerate(calls) if c == "tnlib tn_committee_down_guard"),
                        calls.index("systemctl stop telcoin"))

    def test_two_deferrals_stop_the_run_before_the_node_is_touched(self):
        nf = self.three()
        (self.nodes / "bench-validator-02" / "guard").write_text("1")
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--set", "all:max_header_delay=600ms",
                          "--arm", "g2", PARAMS_APPLY_GUARD_TRIES="3")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.guard_calls("bench-validator-02"), 6)
        self.assertIn("PA_GUARD_DEFER bench-validator-02 all 3 samples refused; again in 0 s", p.stdout)
        self.assertEqual(self.tagged(p, "PA_FAIL"), [
            "PA_FAIL bench-validator-02 the committee guard refused 3 samples in a row twice (6 of 6 refused); "
            "the node was not restarted"])
        self.assertIn("bench-validator-02 was not restarted", p.stderr)
        self.assertIn("it was NOT restarted", p.stderr)
        self.assertNotIn("rollback:", p.stderr)
        for n in ("bench-validator-02", "bench-validator-03"):
            self.assertNotIn("systemctl stop telcoin", self.node_calls(n), n)
            self.assertEqual(self.yaml_of(n), YAML, n)
        self.assertEqual(self.guard_calls("bench-validator-03"), 0)
        arm = self.arms(mpath)[0]
        self.assertEqual(arm["failed"], "bench-validator-02")
        self.assertEqual(arm["guard"]["bench-validator-02"], {"samples": 6, "refused": 6})
        self.assertEqual(sorted(arm["nodes"]), ["bench-validator-01"])

    def test_a_first_node_refused_records_no_arm(self):
        self.node("bench-validator-01")
        (self.nodes / "bench-validator-01" / "guard").write_text("w")
        nf = self.nodes_file(self.line("bench-validator-01"))
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--set", "all:max_header_delay=600ms",
                          "--arm", "g3", PARAMS_APPLY_GUARD_TRIES="2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("refused 2 samples in a row twice (4 of 4 refused)", p.stderr)
        self.assertNotIn("param_arms", json.loads(mpath.read_text()))


class EpochTests(ParamsApplyCase):

    def test_a_stop_waits_until_the_boundary_is_90_s_behind_and_takes_the_guard_again(self):
        self.node("bench-validator-01")
        (self.nodes / "bench-validator-01" / "epoch").write_text("30 1200\n-20 1200\n1150 1200\n1000 1200\n")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "e1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        waits = [l.strip() for l in p.stdout.splitlines() if "PA_EPOCH_WAIT" in l]
        self.assertEqual(len(waits), 3)
        self.assertIn("the epoch boundary is 30 s away, the last one 1170 s ago; looking again in 15 s", waits[0])
        self.assertIn("the epoch boundary is -20 s away", waits[1])
        self.assertIn("the epoch boundary is 1150 s away, the last one 50 s ago; looking again in 15 s", waits[2])
        self.assertRegex(p.stdout, r"PA_EPOCH bench-validator-01 secs_left=1000 since_boundary=200 waited=[1-9]")
        calls = self.node_calls("bench-validator-01")
        self.assertEqual(calls.count("tnlib tn_committee_down_guard"), 2)
        self.assertLess(max(i for i, c in enumerate(calls) if c == "tnlib tn_epoch_secs_left"),
                        calls.index("systemctl stop telcoin"))
        self.assertLess(max(i for i, c in enumerate(calls) if c == "tnlib tn_committee_down_guard"),
                        calls.index("systemctl stop telcoin"))

    def test_the_epoch_wait_gives_up_at_its_deadline_and_changes_nothing(self):
        self.node("bench-validator-01")
        (self.nodes / "bench-validator-01" / "epoch").write_text("30 1200\n")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "e2",
                          PARAMS_APPLY_EPOCH_WAIT_SECS="20")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("PA_FAIL bench-validator-01 gave up after 20 s waiting to be 90 s clear of an epoch boundary: "
                      "the epoch boundary is 30 s away", p.stdout)
        self.assertNotIn("systemctl stop telcoin", self.node_calls("bench-validator-01"))
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)
        self.assertEqual(list((self.nodes / "bench-validator-01" / "data").glob("parameters.yaml.bak*")), [])
        self.assertFalse((self.tmp / "param-arms.json").exists())


class UnitTests(ParamsApplyCase):
    """stop -> host steps -> start run in one systemd-run unit on the node."""

    def test_stop_and_start_run_inside_one_transient_unit(self):
        d = self.node("bench-validator-01")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "u1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        calls = self.node_calls("bench-validator-01")
        run = [c for c in calls if c.startswith("systemd-run ")]
        self.assertEqual(len(run), 1)
        unit = re.search(r"--unit=(bench-arm-u1-\d{8}T\d{6}Z) ", run[0]).group(1)
        units = d / "var/lib/bench-logs/arm-units"
        self.assertEqual(run[0], "systemd-run --unit=%s --description=params-apply pre-arm-u1 on bench-validator-01: "
                         "stop telcoin, host steps, start telcoin --collect --quiet -- /bin/bash %s/%s.sh %s/%s.out %s "
                         "bench-validator-01 %s" % (unit, units, unit, units, unit, d / "data", unit))
        i = calls.index(run[0])
        self.assertEqual([c for c in calls[i:] if c.startswith("systemctl ") and "is-active" not in c],
                         ["systemctl stop telcoin", "systemctl start telcoin"])
        self.assertNotIn("systemctl restart telcoin", calls)
        script = (units / ("%s.sh" % unit)).read_text()
        self.assertLess(script.index("systemctl stop telcoin"), script.index("host_steps || h=$?"))
        self.assertLess(script.index("host_steps || h=$?"), script.index("systemctl start telcoin"))
        self.assertNotIn("set -e", script)
        out = (units / ("%s.out" % unit)).read_text().splitlines()
        self.assertEqual([l.split()[0] for l in out], ["STOP_AT", "STOP_RC", "HOOK_RC", "START_AT", "START_RC"])
        self.assertEqual([l for l in out if l.endswith("_RC 0")], ["STOP_RC 0", "HOOK_RC 0", "START_RC 0"])
        self.assertIn("      PA_UNIT_LAUNCHED %s " % unit, p.stdout)

    def test_a_start_that_fails_in_the_unit_stops_the_run(self):
        nf = self.three()
        (self.nodes / "bench-validator-02" / "start-fails").write_text("")
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--set", "all:max_header_delay=600ms",
                          "--arm", "u2")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^PA_FAIL bench-validator-02 systemctl start telcoin failed in bench-arm-u2-\S+ \(rc 1\)$")
        self.assertRegex(p.stderr, r"its stop and start ran in the unit bench-arm-u2-\d{8}T\d{6}Z: sudo systemctl status")
        self.assertNotIn("systemctl stop telcoin", self.node_calls("bench-validator-03"))
        self.assertEqual(self.arms(mpath)[0]["failed"], "bench-validator-02")

    def test_a_unit_that_does_not_launch_restores_the_file_and_stops_nothing(self):
        self.node("bench-validator-01")
        (self.nodes / "bench-validator-01" / "systemd-run-fails").write_text("")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "u3")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"PA_FAIL bench-validator-01 systemd-run --unit=bench-arm-u3-\S+ failed \(rc 1\) "
                                   r"\(file restored, node not restarted\)")
        self.assertNotIn("systemctl stop telcoin", self.node_calls("bench-validator-01"))
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)
        self.assertFalse((self.tmp / "param-arms.json").exists())


class ArmFileParseTests(ParamsApplyCase):
    """benchmark/arms/README.md "What a parser refuses": the whole file, before any node is contacted."""

    def setUp(self):
        super().setUp()
        self.node("bench-validator-01")
        self.nf = self.nodes_file(self.line("bench-validator-01"))

    def refused(self, text, line, needle, name="bad.arm"):
        f = self.arm_file(text, name=name)
        p = self.run_tool("--nodes", str(self.nf), "--arm-file", str(f))
        self.assertEqual(p.returncode, 2, (text, p.stdout, p.stderr))
        where = "%s:%s: " % (f, line) if line else "%s: " % f
        self.assertIn(where + needle, p.stderr, text)
        self.assertIn("the arm file is refused, nothing was contacted", p.stderr)
        self.assertEqual(self.calls(), [], text)

    def test_every_refusal_of_the_readme(self):
        cases = [
            ("name a\nfoo bar\n", 2, "unknown directive 'foo' (name, param, host; '#' starts a comment)"),
            ("name a\nparam nope true\n", 2, "unknown switch 'nope' (benchmark/arms/switches.tsv: quorum_exec_block "),
            ("name a\nhost drop-caches\n", 2, "unknown host step 'drop-caches' (evict-mdbx, read-ahead-kb <n>)"),
            ("name a\nparam vote_queue_fix yes\n", 2, "vote_queue_fix yes: not one of its arm values (true)"),
            ("name a\nparam vote_queue_fix false\n", 2, "vote_queue_fix false: not one of its arm values (true)"),
            ("name a\nparam recovery_threads 03\n", 2, "recovery_threads 03: not one of its arm values (3)"),
            ("name a\nparam parent_grace 150\n", 2, "parent_grace 150: not one of its arm values (150ms,100ms)"),
            ("name a\nparam vote_queue_fix true\nparam vote_queue_fix true\n", 3, "switch 'vote_queue_fix' is given twice"),
            ("name a\nhost evict-mdbx\nhost evict-mdbx\n", 3, "'host evict-mdbx' is given twice"),
            ("name a\nhost read-ahead-kb 16\nhost read-ahead-kb 32\n", 3, "'host read-ahead-kb' is given twice"),
            ("name a\nname b\n", 2, "a second 'name' line"),
            ("param vote_queue_fix true\n", None, "no 'name' line"),
            ("# only a comment\n\n", None, "no 'name' line"),
            ("name a\nparam vote_queue_fix\n", 2, "'param' takes <key> <value>, got 1 field(s)"),
            ("name a\nparam vote_queue_fix true # on\n", 2, "'param' takes <key> <value>, got 4 field(s) (a directive has no trailing comment)"),
            ("name a b\n", 1, "'name' takes one value, got 2"),
            ("name\n", 1, "'name' takes one value, got 0"),
            ("name a\nhost\n", 2, "'host' takes a step"),
            ("name a\nhost evict-mdbx now\n", 2, "'host evict-mdbx' takes no value, got 1"),
            ("name a\nhost read-ahead-kb\n", 2, "'host read-ahead-kb' takes one value (KiB), got 0"),
            ("name a\nhost read-ahead-kb 016\n", 2, "read-ahead-kb '016' is not a non-negative integer without leading zeros"),
            ("name a\nhost read-ahead-kb 1x\n", 2, "read-ahead-kb '1x' is not a non-negative integer without leading zeros"),
            ("name Arm\n", 1, "'Arm' is not an arm name ([a-z0-9][a-z0-9-]{0,39})"),
            ("name %s\n" % ("a" * 41), 1, "'%s' is not an arm name" % ("a" * 41)),
            ("name a\r\nparam vote_queue_fix true\n", 1, "a carriage return (the file must have LF line ends)"),
            ("name a\nparam vote_queue_fix true\n# caf\xe9\n", 3, "a byte outside printable ASCII, space and tab"),
            ("name a\nparam vote_queue_fix\x0btrue\n", 2, "a byte outside printable ASCII, space and tab"),
        ]
        for text, line, needle in cases:
            self.refused(text, line, needle)

    def test_a_file_that_is_not_an_arm_file_is_refused(self):
        f = self.arm_file("name a\n", name="a.txt")
        p = self.run_tool("--nodes", str(self.nf), "--arm-file", str(f))
        self.assertEqual(p.returncode, 2)
        self.assertIn("is not an arm file (<name>.arm", p.stderr)
        for extra, needle in ((("--set", "all:vote_queue_fix=true"), "no --set beside it"),
                              (("--stage-test", "bench-validator-01"), "it takes no --arm-file")):
            p = self.run_tool("--nodes", str(self.nf), "--arm-file", str(self.arm_file("name a\n", name="a.arm")), *extra)
            self.assertEqual(p.returncode, 2)
            self.assertIn(needle, p.stderr)
        self.assertEqual(self.calls(), [])

    def test_comments_blank_lines_and_tabs_parse_and_unlisted_switches_are_defaults(self):
        f = self.arm_file("# a comment\n\n  name\tok-1\n\tparam  parent_grace\t150ms\n   # indented comment\n"
                          "param quorum_exec_block_starved_rounds 0\nhost read-ahead-kb 0\n", name="other.arm")
        p = self.run_tool("--nodes", str(self.nf), "--arm-file", str(f), "--dry-run")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)   # read-ahead-kb: host steps are not available yet
        self.assertIn("host steps not available: this params-apply.sh cannot run read-ahead-kb 0 yet", p.stderr)
        want = dict(DEFAULTS, parent_grace="150ms")
        self.assertIn("switches: " + " ".join("%s=%s" % (r["key"], want[r["key"]]) for r in SWITCHES), p.stdout)
        self.assertIn("note: %s's name line says 'ok-1', not the file name" % f, p.stdout)
        self.assertIn("plan for arm ok-1:", p.stdout)
        self.assertIn("parent_grace 0ms -> 150ms; restart (params,host); host steps: read-ahead-kb 0", p.stdout)
        self.assertEqual(self.calls(), [])


class TargetStateTests(ParamsApplyCase):
    """The arm is the full state: what it leaves out goes to its default; only differing keys move."""

    def test_a_dry_run_starts_from_the_latest_recorded_arm(self):
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-observer-11", "observer"))
        prev = {"name": "v", "begin": "2026-11-12T03:10:05Z", "end": None,
                "switches": dict(DEFAULTS, vote_queue_fix="true", mdbx_random_advice="true"), "nodes": {}}
        self.manifest({"param_arms": [prev]})
        f = self.arm_file("name next\nparam vote_queue_fix true\nparam parent_grace 150ms\n", name="next.arm")
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--arm-file", str(f), "--dry-run")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("dry run: each node starts from the switches of arm v in the record;", p.stdout)
        plan = [l for l in p.stdout.splitlines() if l.startswith("  bench-")]
        self.assertEqual([l.split()[0] for l in plan], ["bench-observer-11", "bench-validator-01"])
        for l in plan:
            self.assertTrue(l.endswith("mdbx_random_advice true -> false, parent_grace 0ms -> 150ms; restart (params)"), l)
        self.assertIn("setp mdbx_random_advice false\nsetp parent_grace 150ms\n", p.stdout)
        self.assertNotIn("setp vote_queue_fix", p.stdout)
        self.assertEqual(self.calls(), [])
        # Without a recorded arm, every switch starts at its default.
        p = self.run_tool("--nodes", str(nf), "--arm-file", str(f), "--dry-run")
        self.assertIn("starts from every switch at its default (no arm with switches in ", p.stdout)
        self.assertIn("vote_queue_fix false -> true, parent_grace 0ms -> 150ms; restart (params)", p.stdout)

    def test_only_keys_that_differ_are_rewritten_and_back_to_default_writes_the_default(self):
        y = YAML + "vote_queue_fix: true\nmdbx_random_advice: true\n"
        for n in ("bench-validator-01", "bench-validator-02"):
            self.node(n, yaml=y, live={"vote_queue_fix": "true", "mdbx_random_advice": "true"})
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-validator-02"))
        f = self.arm_file("name t2\nparam vote_queue_fix true\n", name="t2.arm")
        mpath = self.manifest()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--arm-file", str(f))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for n in ("bench-validator-01", "bench-validator-02"):
            self.assertIn("\nvote_queue_fix: true\nmdbx_random_advice: false  # bench-override\n", self.yaml_of(n))
        self.assertIn("mdbx_random_advice true -> false; restart (params,live)", p.stdout)
        arm = self.arms(mpath)[0]
        self.assertEqual(arm["nodes"], {n: {"mdbx_random_advice": "false"} for n in ("bench-validator-01", "bench-validator-02")})
        self.assertEqual(arm["switches"], dict(DEFAULTS, vote_queue_fix="true"))

    def test_a_duration_back_to_its_default_is_written_out_and_reads_back_as_0s(self):
        # A switch absent from the file is at its default; one the arm returns to its default is
        # written with the default. The node prints a zero duration as 0s: compared by value.
        y = YAML + "parent_grace: 150ms\n"
        self.node("bench-validator-01", yaml=y, live={"parent_grace": "150ms"})
        self.node("bench-validator-02", yaml=YAML + "parent_grace: 0ms\n")
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-validator-02"))
        p = self.run_tool("--nodes", str(nf), "--arm-file", str(ARMS / "a0-control.arm"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("bench-validator-01       validator parent_grace 150ms -> 0ms; restart (params,live)", p.stdout)
        self.assertIn("bench-validator-02       validator no change; not restarted", p.stdout)
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML + "parent_grace: 0ms  # bench-override\n")
        self.assertEqual(self.yaml_of("bench-validator-02"), YAML + "parent_grace: 0ms\n")
        ok = self.tagged(p, "SWITCHES_OK")
        self.assertEqual(len(ok), 1)
        self.assertIn(" parent_grace=0s ", ok[0])
        self.assertIn(" parent_grace=0s ", self.tagged(p, "SWITCHES_CURRENT")[0])
        arm = json.loads((self.tmp / "param-arms.json").read_text())["param_arms"][0]
        self.assertEqual(arm["nodes"], {"bench-validator-01": {"parent_grace": "0ms"}})
        self.assertEqual(arm["switches"]["parent_grace"], "0ms")

    def test_a_node_whose_running_switches_differ_restarts_without_a_rewrite(self):
        # The file already says the arm's state, but the running node logged another (it was not
        # restarted since the file changed): it restarts, nothing is rewritten.
        self.node("bench-validator-01", live={"vote_queue_fix": "true"})
        self.node("bench-validator-02", pre_switches=False)
        self.node("bench-validator-03")
        nf = self.nodes_file(*(self.line("bench-validator-0%d" % i) for i in (1, 2, 3)))
        p = self.run_tool("--nodes", str(nf), "--arm-file", str(ARMS / "a0-control.arm"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("bench-validator-01       validator no key to rewrite; restart (live)", p.stdout)
        self.assertIn("bench-validator-02       validator no key to rewrite; restart (unread)", p.stdout)
        self.assertIn("bench-validator-03       validator no change; not restarted", p.stdout)
        self.assertEqual([c["node"] for c in self.phase_calls("B")], ["bench-validator-01", "bench-validator-02"])
        for n in ("bench-validator-01", "bench-validator-02", "bench-validator-03"):
            self.assertEqual(self.yaml_of(n), YAML, n)
        self.assertEqual([l.split()[1] for l in self.tagged(p, "SWITCHES_OK")], ["bench-validator-01", "bench-validator-02"])
        self.assertEqual(self.tagged(p, "SWITCHES_CURRENT"),
                         ["SWITCHES_CURRENT bench-validator-03 " + switches_line().split('"node switches" ')[1]])
        arm = json.loads((self.tmp / "param-arms.json").read_text())["param_arms"][0]
        self.assertEqual(arm["nodes"], {"bench-validator-01": {}, "bench-validator-02": {}})
        self.assertEqual(arm["file"], "benchmark/arms/a0-control.arm")


class ReadbackTests(ParamsApplyCase):
    """After each start: the `node switches` line of THIS start against the arm's full state."""

    ARM = "name rb\nparam vote_queue_fix true\nparam parent_grace 150ms\n"

    def apply(self, nf, text=ARM, name="rb.arm"):
        self.manifest()
        return self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                             "--arm-file", str(self.arm_file(text, name=name)))

    def test_every_node_reads_back_and_the_arm_is_ready(self):
        nf = self.three()
        p = self.apply(nf)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        want = " ".join("%s=%s" % (r["key"], rendered(dict(DEFAULTS, vote_queue_fix="true", parent_grace="150ms"))[r["key"]])
                        for r in SWITCHES)
        self.assertEqual(self.tagged(p, "SWITCHES_OK"), ["SWITCHES_OK bench-validator-0%d %s" % (i, want) for i in (1, 2, 3)])
        for i in (1, 2, 3):
            y = self.yaml_of("bench-validator-0%d" % i)
            self.assertIn("\nvote_queue_fix: true  # bench-override\nparent_grace: 150ms  # bench-override\n", y)
        ready = self.tagged(p, "ARM_READY")
        self.assertEqual(len(ready), 1)
        self.assertRegex(ready[0], r"^ARM_READY rb ready=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ restarted=3 nodes=3$")

    def test_a_value_that_does_not_read_back_stops_the_run(self):
        nf = self.three(**{"bench-validator-02": {}})
        (self.nodes / "bench-validator-02" / "switches").write_text("stuck vote_queue_fix false\n")
        p = self.apply(nf)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.tagged(p, "PA_FAIL"),
                         ["PA_FAIL bench-validator-02 switches readback: vote_queue_fix=false (expected true)"])
        self.assertIn("bench-validator-02 did not come back: switches readback", p.stderr)
        self.assertNotIn("systemctl stop telcoin", self.node_calls("bench-validator-03"))
        arm = self.arms()[0]
        self.assertEqual(arm["failed"], "bench-validator-02")
        self.assertEqual([l.split()[1] for l in self.ok_lines(p)], ["bench-validator-01"])

    def test_an_older_start_s_line_is_not_a_readback(self):
        nf = self.three()
        (self.nodes / "bench-validator-01" / "switches").write_text("stale\n")
        p = self.apply(nf)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        fail = self.tagged(p, "PA_FAIL")
        self.assertEqual(len(fail), 1)
        self.assertRegex(fail[0], r"^PA_FAIL bench-validator-01 switches readback: stale: the newest 'node switches' line "
                                  r"\(2026-10-06T11:50:00Z\) is older than this restart \(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\)$")
        self.assertEqual([c["node"] for c in self.phase_calls("B")], ["bench-validator-01"])

    def test_a_start_without_the_line_fails(self):
        nf = self.three()
        (self.nodes / "bench-validator-01" / "switches").write_text("none\n")
        p = self.apply(nf)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("PA_FAIL bench-validator-01 switches readback: no 'node switches' line since the restart", p.stdout)

    def test_an_optional_switch_the_image_lacks_passes_only_at_its_default(self):
        pipe = [r["key"] for r in SWITCHES if r["optional"] == "yes"]
        self.assertEqual(pipe, ["pipelined_persist"])
        nf = self.three(**{"bench-validator-0%d" % i: {"live_drop": pipe} for i in (1, 2, 3)})
        for i in (1, 2, 3):
            (self.nodes / ("bench-validator-0%d" % i) / "switches").write_text("no-optional\n")
        p = self.apply(nf)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("pipelined_persist", " ".join(self.tagged(p, "SWITCHES_OK")))
        # The arm sets it: refused from the running nodes' lines, before any change.
        before = len(self.calls())
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results),
                          "--arm-file", str(self.arm_file(self.ARM.replace("name rb", "name rb2") + "param pipelined_persist true\n",
                                                          name="rb2.arm")))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("refused before any change", p.stderr)
        self.assertIn("bench-validator-01: its image does not know pipelined_persist (its running 'node switches' line "
                      "has no pipelined_persist); the arm sets pipelined_persist=true", p.stderr)
        self.assertEqual([self.phase(c) for c in self.calls()[before:]], ["A", "A", "A"])

    def test_a_required_switch_missing_from_the_running_line_refuses_the_arm(self):
        nf = self.three(**{"bench-validator-03": {"live_drop": ("parent_grace",)}})
        p = self.apply(nf)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("bench-validator-03: its image does not know parent_grace", p.stderr)
        self.assertEqual(self.phase_calls("B"), [])
        for i in (1, 2, 3):
            self.assertEqual(self.yaml_of("bench-validator-0%d" % i), YAML)

    def test_the_line_parser_and_its_time(self):
        """The readback's parser on the contract's shapes, through the tool's own functions."""
        tool = TOOL.read_text()
        funcs = "\n".join(re.search(r"(?ms)^%s\(\) \{.*?^\}\n" % f, tool).group(0)
                          for f in ("sw_line_values", "sw_line_ts"))
        cases = [
            (switches_line({"parent_grace": "150ms"}), "2026-10-06T11:50:00Z", "parent_grace=150ms"),
            ('{"timestamp":"2026-11-12T03:10:05.1Z","level":"INFO","fields":{"message":"node switches"}} '
             'vote_queue_fix=true', "2026-11-12T03:10:05Z", "vote_queue_fix=true"),
            ('2026 no time here message="node switches" recovery_threads="3" junk', "", "recovery_threads=3"),
        ]
        for line, ts, kv in cases:
            p = subprocess.run(["bash", "-c", funcs + '\nsw_line_ts "$1"; echo ---; sw_line_values "$1"', "x", line],
                               stdout=subprocess.PIPE, universal_newlines=True, timeout=30)
            got_ts, vals = p.stdout.split("---\n")
            self.assertEqual(got_ts.strip(), ts, line)
            self.assertIn(kv, vals.splitlines(), line)
            self.assertNotIn("junk", vals)


class ManifestAndHookTests(ParamsApplyCase):
    """The param_arms entry an arm file writes, and the host-step hook's contract (H5b), on a copy
    of the tool whose hook runs fake steps."""

    HOOK = r'''host_steps_hook() {
    [ -n "${ARM_HOST_STEPS}" ] || { echo 'host_steps() { return 0; }'; return 0; }
    cat <<'HOOK'
host_steps() {
    echo 'HOST_RESULT read-ahead-kb 16 {"read_ahead_kb_before": 128, "read_ahead_kb_after": 16}'
    if [ -f "$D/../hook-fails" ]; then echo 'HOST_RESULT evict-mdbx - {"failed": "fincore reads 7 pages"}'; return 1; fi
    echo 'HOST_RESULT evict-mdbx - {"resident_pages_before": 812345, "resident_pages_after": 0}'
}
HOOK
}
'''
    ARM = "# m1\nname m1\nhost evict-mdbx\nparam vote_queue_fix true\nhost read-ahead-kb 16\n"

    def setUp(self):
        super().setUp()
        self.root = self.tree(hook=self.HOOK)
        self.tool = self.root / "benchmark" / "tools" / "params-apply.sh"
        self.armf = self.arm_file(self.ARM, name="m1.arm", where=self.root / "benchmark" / "arms")
        self.node("bench-validator-01")
        self.node("bench-validator-02")
        self.node("bench-observer-11", role="observer")
        self.nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-validator-02"),
                                  self.line("bench-observer-11", "observer"))
        self.mpath = self.manifest()

    def run_arm(self, *extra):
        return self.run_tool("--nodes", str(self.nf), "--results-dir", str(self.results), *extra, tool=self.tool)

    def test_the_entry_has_every_frozen_field(self):
        p = self.run_arm("--arm-file", str(self.armf))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        arm = self.arms(self.mpath)[0]
        self.assertEqual(list(arm), ["name", "begin", "end", "via", "file", "sha256", "switches", "nodes", "host",
                                     "restart_secs", "guard", "marks", "ready"])
        nodes = ["bench-observer-11", "bench-validator-01", "bench-validator-02"]
        self.assertEqual((arm["name"], arm["end"], arm["via"], arm["file"]), ("m1", None, "params-apply", "benchmark/arms/m1.arm"))
        self.assertEqual(arm["sha256"], hashlib.sha256(self.armf.read_bytes()).hexdigest())
        self.assertEqual(list(arm["switches"]), [r["key"] for r in SWITCHES])
        self.assertEqual(arm["switches"], dict(DEFAULTS, vote_queue_fix="true"))
        self.assertTrue(all(isinstance(v, str) for v in arm["switches"].values()))
        self.assertEqual(arm["nodes"], {n: {"vote_queue_fix": "true"} for n in nodes})
        # Host steps in run order (read-ahead before the eviction, whatever the file's order).
        self.assertEqual(arm["host"], [
            {"step": "read-ahead-kb", "value": "16",
             "nodes": {n: {"read_ahead_kb_before": 128, "read_ahead_kb_after": 16} for n in nodes}},
            {"step": "evict-mdbx", "value": None,
             "nodes": {n: {"resident_pages_before": 812345, "resident_pages_after": 0} for n in nodes}}])
        self.assertEqual(arm["guard"], {n: {"samples": 1, "refused": 0} for n in nodes})
        self.assertEqual(sorted(arm["restart_secs"]), nodes)
        for v in arm["restart_secs"].values():
            self.assertIsInstance(v, (int, float))
            self.assertGreaterEqual(v, 0)
        self.assertEqual(arm["marks"], [])
        # ready = the last node's consensus progress + 120 s, and the tool says so.
        prog = max(re.findall(r"PA_PROGRESS_AT (\S+)", p.stdout))
        want = (datetime.datetime.strptime(prog, "%Y-%m-%dT%H:%M:%SZ") + datetime.timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(arm["ready"], want)
        self.assertEqual(self.tagged(p, "ARM_READY"), ["ARM_READY m1 ready=%s restarted=3 nodes=3" % want])
        self.assertLessEqual(arm["begin"], arm["ready"])
        # The bench-4 readers still take it.
        rows = load_make_bundle().arm_rows(json.loads(self.mpath.read_text()))
        self.assertEqual([(r["arm"], r["begin_utc"], r["end_utc"]) for r in rows], [("m1", arm["begin"], None)])
        self.assertIn("vote_queue_fix=true", rows[0]["values"])
        p = subprocess.run([sys.executable, str(BENCH / "tools" / "cert-rate.py"), "--help"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_marks_close_arm_and_the_next_arm(self):
        p = self.run_arm("--arm-file", str(self.armf))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        n = len(self.calls())
        for args, rc, needle in ((("--end-mark", "idle"), 1, "no open mark 'idle'"),
                                 (("--mark", "idle"), 0, "mark idle opened at "),
                                 (("--mark", "idle"), 1, "already has a mark 'idle'"),
                                 (("--end-mark", "idle"), 0, "mark idle ended at "),
                                 (("--mark", "m16"), 0, "on the open arm m1"),
                                 (("--mark", "Bad_label"), 2, "--mark 'Bad_label' must be [a-z0-9-]"),
                                 (("--mark", "x", "--close-arm", "m1"), 2, "runs on its own")):
            p = self.run_arm(*args)
            self.assertEqual(p.returncode, rc, (args, p.stdout, p.stderr))
            self.assertIn(needle, p.stdout + p.stderr, args)
        self.assertEqual(len(self.calls()), n)
        marks = self.arms(self.mpath)[0]["marks"]
        self.assertEqual([(m["label"], m["end"] is None) for m in marks], [("idle", False), ("m16", True)])
        self.assertLessEqual(marks[0]["begin"], marks[0]["end"])
        # The next arm closes the open one and its open mark at its begin.
        for nd in ("bench-validator-01", "bench-validator-02", "bench-observer-11"):
            (self.nodes / nd / "state" / "restarted").unlink()
        p = self.run_arm("--arm-file", str(self.armf), "--arm", "m1-r2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        arms = self.arms(self.mpath)
        self.assertEqual([a["name"] for a in arms], ["m1", "m1-r2"])
        self.assertEqual(arms[0]["end"], arms[1]["begin"])
        self.assertEqual(arms[0]["marks"][1]["end"], arms[1]["begin"])
        # --close-arm closes the arm and its open marks.
        self.assertEqual(self.run_arm("--mark", "tail").returncode, 0)
        self.assertEqual(self.run_arm("--close-arm", "m1-r2").returncode, 0)
        last = self.arms(self.mpath)[1]
        self.assertEqual(last["marks"][0]["end"], last["end"])
        p = self.run_arm("--mark", "late")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no open arm in", p.stderr)

    def test_a_host_step_that_fails_starts_the_node_and_stops_the_run(self):
        (self.nodes / "bench-validator-01" / "hook-fails").write_text("")
        p = self.run_arm("--arm-file", str(self.armf))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^PA_FAIL bench-validator-01 the host steps failed in bench-arm-m1-\S+ \(rc 1\): "
                                   r'HOST_RESULT evict-mdbx - \{"failed": "fincore reads 7 pages"\}; '
                                   r"telcoin was started again \(rc 0\)$")
        calls = self.node_calls("bench-validator-01")
        self.assertLess(calls.index("systemctl stop telcoin"), calls.index("systemctl start telcoin"))
        self.assertNotIn("systemctl stop telcoin", self.node_calls("bench-validator-02"))
        arm = self.arms(self.mpath)[0]
        self.assertEqual(arm["failed"], "bench-validator-01")
        self.assertEqual(arm["host"][1], {"step": "evict-mdbx", "value": None, "nodes": {
            "bench-observer-11": {"resident_pages_before": 812345, "resident_pages_after": 0},
            "bench-validator-01": {"failed": "fincore reads 7 pages"}}})

    def test_the_stub_hook_refuses_host_steps_before_any_node_is_contacted(self):
        armf = self.arm_file(self.ARM, name="m1.arm")
        p = self.run_tool("--nodes", str(self.nf), "--results-dir", str(self.results), "--arm-file", str(armf))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("host steps not available: this params-apply.sh cannot run read-ahead-kb 16, evict-mdbx yet", p.stderr)
        self.assertEqual(self.calls(), [])


class StageTestTests(ParamsApplyCase):

    def test_stage_test_rewrites_current_values_and_restarts_only_that_node(self):
        self.node("bench-validator-01")
        self.node("bench-observer-11", role="observer")
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-observer-11", "observer"))
        mpath = self.manifest()
        before = mpath.read_text()
        p = self.run_tool("--nodes", str(nf), "--results-dir", str(self.results), "--stage-test", "bench-observer-11",
                          "--set", "all:max_header_delay=600ms,min_header_delay=300ms", "--arm", "a1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.ok_lines(p), ["PARAMS_OK bench-observer-11 max=500 min=250 batch=250 thr=5 vote=-"])
        self.assertEqual(len(self.tagged(p, "SWITCHES_OK")), 1)
        self.assertIn("stage test passed on bench-observer-11", p.stdout)
        self.assertEqual({c["node"] for c in self.calls()}, {"bench-observer-11"})
        self.assertEqual([self.phase(c) for c in sorted(self.calls(), key=lambda c: c["start"])], ["A", "B"])
        # Identical values: only the marker comments differ.
        got = self.yaml_of("bench-observer-11")
        self.assertEqual(got.replace("  # bench-override", ""), YAML)
        self.assertIn("max_header_delay: 500ms  # bench-override", got)
        self.assertIn("systemctl start telcoin", self.node_calls("bench-observer-11"))
        saved = list((self.nodes / "bench-observer-11" / "var/lib/bench-logs").glob("*.log.gz"))
        self.assertEqual(len(saved), 1)
        self.assertRegex(saved[0].name, r"^telcoin-stage-test-\d{8}T\d{6}Z\.log\.gz$")
        self.assertTrue(list((self.nodes / "bench-observer-11" / "var/lib/bench-logs/arm-units").glob("bench-arm-stage-test-*.out")))
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)
        self.assertEqual(mpath.read_text(), before)   # no arm recorded

    def test_stage_test_notes_an_image_without_the_switches_line(self):
        self.node("bench-validator-01")
        (self.nodes / "bench-validator-01" / "switches").write_text("none\n")
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--stage-test", "bench-validator-01")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("note: bench-validator-01 logged no 'node switches' line since the restart", p.stdout)
        self.assertEqual(self.tagged(p, "SWITCHES_OK"), [])


class RefusalTests(ParamsApplyCase):

    def setUp(self):
        super().setUp()
        self.node("bench-validator-01")
        self.node("bench-validator-02")
        self.nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-validator-02"))

    def refused(self, *args, needle, code=None):
        p = self.run_tool("--nodes", str(self.nf), *args)
        self.assertNotEqual(p.returncode, 0, (args, p.stdout))
        if code is not None:
            self.assertEqual(p.returncode, code, (args, p.stderr))
        self.assertIn(needle, p.stderr, args)
        return p

    def test_values_a_node_would_refuse_are_refused_before_any_ssh(self):
        cases = [
            (["--set", "all:min_header_delay=700ms,max_header_delay=600ms"],
             "bench-validator-01: min_header_delay 700 ms > max_header_delay 600 ms"),
            (["--set", "all:max_header_delay=600ms,vote_timeout=800ms"],
             "vote_timeout 800 ms < max_header_delay 600 ms + 250 ms drift tolerance"),
            (["--set", "all:vote_timeout=10s"], "vote_timeout 10000 ms is not below the 10 s libp2p request timeout"),
            (["--set", "all:header_num_of_batches_threshold=12,max_header_num_of_batches=10"],
             "header_num_of_batches_threshold 12 is outside 1..max_header_num_of_batches 10"),
            # A node's own value wins over all:, and is checked with the all: values.
            (["--set", "bench-validator-02:min_header_delay=700ms", "--set", "all:max_header_delay=600ms"],
             "bench-validator-02: min_header_delay 700 ms > max_header_delay 600 ms"),
        ]
        for args, needle in cases:
            self.refused(*(args + ["--arm", "x"]), needle=needle, code=1)
        self.assertEqual(self.calls(), [])

    def test_bad_keys_and_values_are_refused_before_any_ssh(self):
        cases = [
            ("all:gc_depth=60", "gc_depth must stay fleet-wide"),
            ("all:basefee_address=0x1", "basefee_address must stay fleet-wide"),
            ("all:batch_vote_timeout=5s", "secs/nanos block"),
            ("all:parallel_fetch_request_delay_interval=5s", "secs/nanos block"),
            ("all:max_header_dely=600ms", "unknown key 'max_header_dely'"),
            ("all:max_header_delay=600", "is not <int>ms or <int>s"),
            ("all:max_header_delay=1.5s", "is not <int>ms or <int>s"),
            ("all:sync_retry_nodes=0", "is not a positive integer"),
            ("all:allow_private_forward_targets=yes", "is not true or false"),
            ("nobody:max_header_delay=600ms", "nobody is not in the node list"),
            ("all:max_header_delay", "is not <key>=<value>"),
            ("max_header_delay=600ms", "want <all|node>:<key>=<value>"),
        ]
        for spec, needle in cases:
            self.refused("--set", spec, "--arm", "x", needle=needle, code=2)
        self.refused("--set", "all:max_header_delay=600ms", "--set", "all:max_header_delay=700ms", "--arm", "x",
                     needle="max_header_delay is given twice for all", code=2)
        self.refused("--set", "all:max_header_delay=600ms", needle="--set needs --arm", code=2)
        self.refused("--set", "all:max_header_delay=600ms", "--arm", "Arm_1", needle="must be [a-z0-9-]", code=2)
        self.refused("--close-arm", "a1", "--arm", "a2", needle="--close-arm runs on its own", code=2)
        self.refused("--stage-test", "bench-validator-09", needle="not in the node list", code=2)
        for knob in ("PARAMS_APPLY_GUARD_TRIES", "PARAMS_APPLY_UNIT_SECS"):
            p = self.run_tool("--nodes", str(self.nf), "--set", "all:max_header_delay=600ms", "--arm", "x", **{knob: "0"})
            self.assertEqual(p.returncode, 2)
            self.assertIn("%s='0' must be a positive integer" % knob, p.stderr)
        self.assertEqual(self.calls(), [])

    def test_resulting_file_is_validated_after_the_read_and_before_any_restart(self):
        with_vote = YAML.replace("max_batch_delay: 250ms\n", "max_batch_delay: 250ms\nvote_timeout: 700ms\n")
        (self.nodes / "bench-validator-02" / "data" / "parameters.yaml").write_text(with_vote)
        p = self.refused("--set", "all:max_header_delay=600ms", "--arm", "x",
                         needle="bench-validator-02: vote_timeout 700 ms < max_header_delay 600 ms + 250 ms", code=1)
        self.assertIn("refused before any change", p.stderr)
        self.assertEqual({self.phase(c) for c in self.calls()}, {"A"})
        self.assertEqual(self.phase_calls("B"), [])
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)

    def test_a_block_form_key_in_the_file_is_refused_before_any_restart(self):
        block = YAML.replace("max_header_delay: 500ms\n", "max_header_delay:\n  secs: 0\n  nanos: 500000000\n")
        (self.nodes / "bench-validator-01" / "data" / "parameters.yaml").write_text(block)
        self.refused("--set", "all:max_header_delay=600ms", "--arm", "x",
                     needle="bench-validator-01: max_header_delay is a secs/nanos block", code=1)
        self.assertEqual(self.phase_calls("B"), [])

    def test_markers_without_a_bak_are_refused(self):
        marked = YAML.replace("max_header_delay: 500ms\n", "max_header_delay: 400ms  # bench-override\n")
        (self.nodes / "bench-validator-01" / "data" / "parameters.yaml").write_text(marked)
        self.refused("--set", "all:max_header_delay=600ms", "--arm", "x", needle="bench-override lines but no .bak", code=1)
        self.assertEqual(self.phase_calls("B"), [])

    def test_phase_a_failure_on_one_node_changes_nothing(self):
        for rel in (V2_START, V2_META):
            (self.nodes / "bench-validator-02" / rel).unlink()
        p = self.refused("--set", "all:max_header_delay=600ms", "--arm", "x", needle="phase A failed", code=1)
        self.assertIn("tn-start-docker or ", p.stderr)
        self.assertIn("start-telcoin.sh (start script), no DATA_DIR in ", p.stderr)
        self.assertIn("and no hostdatadir in the nodes file", p.stderr)
        self.assertEqual(self.phase_calls("B"), [])
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)

    def test_a_node_without_the_guard_library_is_refused_before_any_change(self):
        p = self.run_tool("--nodes", str(self.nf), "--set", "all:max_header_delay=600ms", "--arm", "x",
                          PARAMS_APPLY_NODE_SCRIPTS_DIR=str(self.tmp / "nowhere"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("bench-validator-01: no %s/lib/common.sh (the v2 scripts' library)" % (self.tmp / "nowhere"), p.stderr)
        self.assertEqual(self.phase_calls("B"), [])
        self.assertEqual(self.yaml_of("bench-validator-01"), YAML)


class NodesFileTests(ParamsApplyCase):

    def run_with(self, *lines, extra=()):
        nf = self.nodes_file(*lines)
        return self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms", "--arm", "x", *extra)

    def test_bad_lines_are_refused_before_any_ssh(self):
        cases = [
            (("bench-validator-01 %s %s" % (ZONE, PROJECT),), "want 'name zone project role [hostdatadir]', got 3 fields"),
            (("bench-validator-01 %s %s leader" % (ZONE, PROJECT),), "role 'leader' is not validator or observer"),
            (("bench-validator-01 us-west2 %s validator" % PROJECT,), "'us-west2' is not a zone"),
            (("Bench-Validator %s %s validator" % (ZONE, PROJECT),), "is not an instance name"),
            (("bench-validator-01 %s %s validator data/x" % (ZONE, PROJECT),), "is not an absolute path"),
            (("bench-validator-01 %s - validator" % ZONE,), "project '-' needs --project"),
            (("bench-validator-01 %s %s validator" % (ZONE, PROJECT),) * 2, "bench-validator-01 is listed twice"),
        ]
        for lines, needle in cases:
            p = self.run_with(*lines)
            self.assertEqual(p.returncode, 2, (lines, p.stderr))
            self.assertIn(needle, p.stderr)
        self.assertEqual(self.calls(), [])

    def test_project_dash_takes_the_project_option_and_a_datadir_column_needs_no_wrapper(self):
        self.node("bench-validator-01", launch=None, meta=False)
        p = self.run_with("bench-validator-01 %s - validator %s   # comment" % (ZONE, self.nodes / "bench-validator-01" / "data"),
                          extra=("--project", "other-proj"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("--project=other-proj", self.calls()[0]["argv"])
        self.assertIn("HD=%s" % (self.nodes / "bench-validator-01" / "data"), self.calls()[0]["stdin"])
        self.assertEqual(len(self.ok_lines(p)), 1)


class LayoutTests(ParamsApplyCase):
    """Where the datadir comes from: the nodes file, .node-meta, the v2 start script, the legacy
    wrapper. Each run rewrites the same file the same way."""

    def apply(self, *lines):
        return self.run_tool("--nodes", str(self.nodes_file(*lines)), "--set", "all:max_header_delay=600ms",
                             "--arm", "a1")

    def assert_rewritten(self, p, name):
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.ok_lines(p), ["PARAMS_OK %s max=600 min=250 batch=250 thr=5 vote=-" % name])
        self.assertEqual(self.yaml_of(name).splitlines(),
                         [l.replace("max_header_delay: 500ms", "max_header_delay: 600ms  # bench-override")
                          for l in YAML.splitlines()])
        self.assertEqual((self.nodes / name / "data" / "parameters.yaml.bak").read_text(), YAML)
        self.assertIn("systemctl start telcoin", self.node_calls(name))

    def summary(self, name, launch, source):
        d = self.nodes / name
        return "launch file %s/%s; datadir %s/data (from %s)" % (d, launch, d, source % {"d": d})

    def test_the_v2_start_script_is_read_when_both_launch_files_exist(self):
        n = "bench-validator-01"
        self.node(n, launch="both", meta=False)
        self.retarget(n, LEGACY_WRAPPER)
        p = self.apply(self.line(n))
        self.assert_rewritten(p, n)
        self.assertIn(self.summary(n, V2_START, "the bind mount in %(d)s/" + V2_START), p.stdout)

    def test_the_legacy_wrapper_is_the_fallback_without_the_v2_start_script(self):
        n = "bench-validator-01"
        self.node(n, launch="legacy", meta=False)
        p = self.apply(self.line(n))
        self.assert_rewritten(p, n)
        self.assertIn(self.summary(n, LEGACY_WRAPPER, "the bind mount in %(d)s/" + LEGACY_WRAPPER), p.stdout)

    def test_data_dir_from_node_meta_comes_first(self):
        n = "bench-validator-01"
        self.node(n)
        self.retarget(n, V2_START)
        p = self.apply(self.line(n))
        self.assert_rewritten(p, n)
        self.assertIn(self.summary(n, V2_START, "%(d)s/" + V2_META), p.stdout)

    def test_a_data_dir_set_twice_in_node_meta_is_refused(self):
        self.node("bench-validator-01", meta=(FIX / "v2-node-meta").read_text() + "DATA_DIR=/srv/telcoin\n")
        self.node("bench-validator-02")
        for lines in ((self.line("bench-validator-01"), self.line("bench-validator-02")),
                      (self.line("bench-validator-01", datadir=True),)):
            p = self.apply(*lines)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("phase A failed", p.stderr)
            self.assertIn("FAIL bench-validator-01: PA_FAIL bench-validator-01 DATA_DIR is set 2 times in %s/%s (no single value)"
                          % (self.nodes / "bench-validator-01", V2_META), p.stderr)
        self.assertEqual(self.phase_calls("B"), [])
        for n in ("bench-validator-01", "bench-validator-02"):
            self.assertEqual(self.yaml_of(n), YAML, n)
            self.assertNotIn("systemctl stop telcoin", self.node_calls(n), n)

    def test_a_hostdatadir_other_than_the_node_meta_data_dir_is_refused(self):
        n = "bench-validator-01"
        d = self.node(n)
        (d / "other").mkdir()
        (d / "other" / "parameters.yaml").write_text(YAML)
        p = self.apply("%s %s %s validator %s" % (n, ZONE, PROJECT, d / "other"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("the nodes file's hostdatadir %s/other is not DATA_DIR %s/data of %s/%s" % (d, d, d, V2_META),
                      p.stderr)
        self.assertEqual(self.phase_calls("B"), [])
        # The same directory as .node-meta's is accepted.
        p = self.apply(self.line(n, datadir=True))
        self.assert_rewritten(p, n)
        self.assertIn(self.summary(n, V2_START, "the nodes file"), p.stdout)


class V2FixtureTests(unittest.TestCase):
    """fixtures/params-apply/v2-tn-start-docker is what the pinned tn-node-deployment renders for
    a bench node: lib/common.sh _tn_start_script_text (docker form) with setup-node.sh's docker
    node arguments and the metrics launch flag deploy step 8 adds."""
    NODE_ARGS = "--datadir /home/nonroot --log.stdout.format log-fmt -vvv --http --http.addr 127.0.0.1 --ws --ws.addr 127.0.0.1"
    LAUNCH_FLAGS = "--metrics 127.0.0.1:9101"

    @unittest.skipUnless((DEPLOYMENT / "lib" / "common.sh").is_file(), "the tn-node-deployment submodule is not checked out")
    def test_start_script_fixture_is_what_the_pinned_library_renders(self):
        self.assertIn('node_args="%s${launch_flags:+ ${launch_flags}}"' % self.NODE_ARGS,
                      (DEPLOYMENT / "setup-node.sh").read_text())
        meta = (FIX / "v2-node-meta").read_text()
        digest = re.search(r"^DOCKER_IMAGE_DIGEST=(sha256:[0-9a-f]{64})$", meta, re.M).group(1)
        root = Path(tempfile.mkdtemp(prefix="params-apply-render."))
        self.addCleanup(shutil.rmtree, str(root), True)
        (root / "etc" / "telcoin").mkdir(parents=True)
        (root / V2_META).write_text(meta)
        (root / "meminfo").write_text("MemTotal:       16384000 kB\n")
        # A fixed PATH: the docker client path is part of the text (absent there: /usr/bin/docker).
        env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "DEVNET_RPC_URL": "http://127.0.0.1:9",
               "TN_ROOT_PREFIX": str(root), "TN_DOCKER_IDS": "999:988", "TN_MEMINFO": str(root / "meminfo"),
               "SERVICE_NAME": "telcoin"}
        p = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; _tn_start_script_text docker "$2" "$3"', "render",
                            str(DEPLOYMENT / "lib" / "common.sh"), "us-docker.pkg.dev/telcoin-network/tn-public/adiri@" + digest,
                            self.NODE_ARGS + " " + self.LAUNCH_FLAGS],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, (FIX / "v2-tn-start-docker").read_text())
        self.assertIn(" -v %s:/home/nonroot " % V2_DATADIR, p.stdout)

    @unittest.skipUnless((DEPLOYMENT / "lib" / "common.sh").is_file(), "the tn-node-deployment submodule is not checked out")
    def test_the_library_stub_mirrors_the_functions_the_tool_calls(self):
        """The two v2 functions the tool calls through tnlib exist in the pinned library, with the
        argument and output shapes the stub (and the tool) assume."""
        lib = (DEPLOYMENT / "lib" / "common.sh").read_text()
        self.assertIn("# tn_committee_down_guard [URL] [progress-fn] --", lib)
        self.assertIn('"$3" "$1" "$2" || true', lib)    # _tn_guard_say: fn <log|warn> <message>
        self.assertIn("#   <secs_left> <epoch_id> <boundary_unix> <epoch_duration>", lib)


class DryRunTests(ParamsApplyCase):

    def test_dry_run_prints_every_argv_and_script_and_contacts_nothing(self):
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-observer-11", "observer"))
        p = self.run_tool("--nodes", str(nf), "--set", "all:max_header_delay=600ms,min_header_delay=300ms",
                          "--arm", "a1", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.tmp / "param-arms.json").exists())
        argv = [l for l in p.stderr.splitlines() if "+ gcloud compute ssh" in l]
        self.assertEqual(len(argv), 4)   # phase A and phase B, both nodes
        for ln in argv:
            for flag in ("--zone=%s" % ZONE, "--project=%s" % PROJECT, "--tunnel-through-iap"):
                self.assertIn(flag, ln)
            self.assertIn("--command=sudo\\ bash\\ -s", ln)
            self.assertNotRegex(ln, r"=\^")   # never a list-flag value that starts with ^
        out = p.stdout
        for n in ("bench-validator-01", "bench-observer-11"):
            self.assertIn("----- phase A script for %s" % n, out)
            self.assertIn("----- phase B script for %s" % n, out)
        self.assertIn("setp max_header_delay 600ms\nsetp min_header_delay 300ms\n", out)
        self.assertIn("LABEL=pre-arm-a1", out)
        self.assertIn("\nUNIT_PREFIX=bench-arm-a1\nGT=8\nGS=0\nGD=0\nEM=90\nEW=600\nUW=600\nGUARD_RPC=http://127.0.0.1:9\n", out)
        self.assertIn("\nHD=''\nROLE=validator\nSTART=/usr/local/libexec/telcoin/tn-start-docker\n"
                      "LEGACY=/opt/telcoin/start-telcoin.sh\nMETA=/etc/telcoin/.node-meta\n", out)
        # The stop and the start: one transient unit, its script between the heredoc markers.
        self.assertIn('systemd-run --unit="$UNIT" --description="params-apply $LABEL on $NODE: stop telcoin, host steps, '
                      'start telcoin" \\\n    --collect --quiet -- /bin/bash "$US" "$UO" "$D" "$NODE" "$UNIT" || r=$?', out)
        unit = re.search(r"(?s)<<'PA_UNIT_SCRIPT' \|\| rfail \"cannot write \$US\"\n(.*?)\nPA_UNIT_SCRIPT\n", out).group(1)
        self.assertTrue(unit.startswith("#!/bin/bash\n"))
        self.assertIn("host_steps() { return 0; }", unit)
        self.assertLess(unit.index("systemctl stop telcoin"), unit.index("host_steps || h=$?"))
        self.assertLess(unit.index("host_steps || h=$?"), unit.index("systemctl start telcoin"))
        self.assertNotIn("systemctl restart telcoin", out)
        self.assertIn("dry run: nothing was contacted or changed", out)

    def test_from_config_dry_run_lists_the_bench_fleet_and_writes_nothing(self):
        run = "rtest-pa-dryrun"
        p = self.run_tool("--from-config", "--set", "all:max_header_delay=600ms", "--arm", "a1", "--dry-run",
                          BENCH_RUN_ID=run, PARAMS_APPLY_NODE_SCRIPTS_DIR="")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.log.exists())
        for i in range(1, 11):
            self.assertIn("gcloud compute ssh bench-validator-%02d " % i, p.stderr)
        self.assertIn("gcloud compute ssh bench-observer-11 ", p.stderr)
        # Every node's datadir is the config's VALIDATOR_DATA_DIR (the nodes file's hostdatadir), and
        # the guard's library is the config's TN_NODE_SCRIPTS_DIR.
        self.assertEqual(len(re.findall(r"^# params-apply phase A on ", p.stdout, re.M)), 11)
        self.assertEqual(len(re.findall(r"^HD=/var/lib/telcoin$", p.stdout, re.M)), 22)   # phase A and B
        self.assertEqual(len(re.findall(r"^SD=/opt/telcoin-node-scripts$", p.stdout, re.M)), 22)
        self.assertFalse((BENCH / "results" / run).exists())
        p = self.run_tool("--from-config", "--set", "all:max_header_delay=600ms", "--arm", "a1", "--dry-run",
                          BENCH_RUN_ID="")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--from-config needs BENCH_RUN_ID", p.stderr)

    def test_no_arm_file_reaches_gcloud_in_a_dry_run(self):
        """A gcloud that prints REACHED and exits 9 is first on PATH: no dry run of any arm file in
        benchmark/arms calls it. An arm with host steps is refused after its plan (rc 2) while the
        hook is a stub; every other arm prints its plan and ends rc 0."""
        shim, hits = self.tmp / "shim", self.tmp / "shim-hits"
        shim.mkdir()
        # The tool sends a call's output to its own files, so the shim also leaves a mark of its own.
        (shim / "gcloud").write_text("#!/bin/sh\necho REACHED >> '%s'\necho REACHED\necho REACHED >&2\nexit 9\n" % hits)
        (shim / "gcloud").chmod(0o755)
        path = str(shim) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
        nf = self.nodes_file(self.line("bench-validator-01"), self.line("bench-validator-02"),
                             self.line("bench-observer-11", "observer"))
        # Phase B's call too: an arm that restarts every node.
        p = self.run_tool("--nodes", str(nf), "--set", "all:vote_queue_fix=true", "--arm", "x", "--dry-run", PATH=path)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(re.findall(r"----- phase B script for ", p.stdout)), 3)
        self.assertNotIn("REACHED", p.stdout + p.stderr)
        self.assertFalse(hits.exists())
        files = sorted(ARMS.glob("*.arm"))
        self.assertGreaterEqual(len(files), 11)
        for f in files:
            p = self.run_tool("--nodes", str(nf), "--arm-file", str(f), "--dry-run", PATH=path)
            self.assertNotIn("REACHED", p.stdout + p.stderr, f.name)
            self.assertFalse(hits.exists(), f.name)
            name = re.search(r"(?m)^name (\S+)$", f.read_text()).group(1)
            self.assertIn("plan for arm %s:" % name, p.stdout, f.name)
            if re.search(r"(?m)^host ", f.read_text()):
                self.assertEqual(p.returncode, 2, (f.name, p.stderr))
                self.assertIn("host steps not available", p.stderr)
            else:
                self.assertEqual(p.returncode, 0, (f.name, p.stderr))
        self.assertFalse(self.log.exists())


class ArmFilesTests(ParamsApplyCase):
    """benchmark/arms/*.arm: each parses, is named after its file, starts with a comment block, and
    run 1's schedule is cumulative."""

    def parsed(self, f):
        nf = self.nodes_file(self.line("bench-validator-01"))
        p = self.run_tool("--nodes", str(nf), "--arm-file", str(f), "--dry-run")
        self.assertIn(p.returncode, (0, 2), (f.name, p.stderr))
        self.assertNotIn("the arm file is refused", p.stderr, f.name)
        sw = re.search(r"switches: (.*)$", p.stdout, re.M).group(1)
        host = re.search(r"^  host steps: (.*)$", p.stdout, re.M).group(1)
        return dict(kv.split("=", 1) for kv in sw.split()), host

    def test_every_arm_file_parses(self):
        state = {}
        for f in sorted(ARMS.glob("*.arm")):
            text = f.read_text()
            self.assertTrue(text.startswith("# "), f.name)
            self.assertIn("\nname %s\n" % f.stem, "\n" + text)
            state[f.stem] = self.parsed(f)
        for name in ("a0-control", "p1-mdbx-advice", "v-vote", "v-vote-floor", "pool-local", "pipe", "bound",
                     "gr150", "gr100", "a0-prime", "final"):
            self.assertIn(name, state)
        on = {n: {k for k, v in s.items() if v != DEFAULTS[k]} for n, (s, _h) in state.items()}
        self.assertEqual(on["a0-control"], set())
        self.assertEqual(on["final"], set())
        self.assertEqual(on["a0-prime"], set())
        self.assertEqual(on["p1-mdbx-advice"], {"mdbx_random_advice"})
        self.assertEqual(on["v-vote"] - on["p1-mdbx-advice"],
                         {"quorum_exec_block", "quorum_exec_block_starved_rounds", "vote_queue_fix", "epoch_record_state_check"})
        self.assertEqual(state["v-vote"][0]["quorum_exec_block_starved_rounds"], "4")
        self.assertEqual(state["v-vote-floor"][0], dict(state["v-vote"][0], quorum_exec_block_starved_rounds="0"))
        self.assertEqual(on["pool-local"] - on["v-vote"],
                         {"sealed_tx_keep", "digest_dedupe", "recovery_threads", "epoch_close_task_drain"})
        self.assertEqual(state["pool-local"][0]["recovery_threads"], "3")
        self.assertEqual(on["pipe"] - on["pool-local"], {"pipelined_persist"})
        self.assertEqual(on["bound"] - on["pipe"], {"rpc_admission_backlog_outputs"})
        self.assertEqual(state["bound"][0]["rpc_admission_backlog_outputs"], "2")
        self.assertEqual(state["gr150"][0], dict(state["bound"][0], parent_grace="150ms"))
        self.assertEqual(state["gr100"][0], dict(state["bound"][0], parent_grace="100ms"))
        for prev, nxt in (("p1-mdbx-advice", "v-vote"), ("v-vote", "pool-local"), ("pool-local", "pipe"),
                          ("pipe", "bound"), ("bound", "gr150")):
            self.assertLessEqual(on[prev], on[nxt], (prev, nxt))
        for name in ("p1-mdbx-advice", "v-vote", "v-vote-floor", "pool-local", "pipe", "bound", "gr150", "gr100", "a0-prime"):
            self.assertEqual(state[name][1], "evict-mdbx", name)
        for name in ("a0-control", "final"):
            self.assertEqual(state[name][1], "none", name)


if __name__ == "__main__":
    unittest.main()
