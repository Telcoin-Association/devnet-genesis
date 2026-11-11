"""The run-1 rehearsal: a miniature bench-6 run 1 written by the real drivers, then read by every reader.

The walk. A sandbox copy of the tree (fixtures/run1-rehearsal/) runs the REAL sequencer
(benchmark/launch/run-arms.sh) on the plan below, and it drives the REAL arm tool
(tools/params-apply.sh --from-config: arm files, idle marks, closes) and the REAL blast driver
(benchmark-blast.sh fund / run --yes, by hand under a fresh BENCH_RUN_INDEX each) against ONE manifest.
Nothing of the drivers is replaced but the leaves fixtures/run1-rehearsal/overrides.sh names (sourced
just before the blast driver's dispatch). One fake clock ($CLOCK: fixtures/run1-rehearsal/bin/date and
sleep) serves the host, the drivers and the fake nodes, so seven hours of plan take no wall-clock time
and nothing depends on how loaded the machine is. The fake gcloud answers the nodes' sessions with the
arm tool's own fake nodes (fixtures/params-apply/) and stages each load VM's outputs (blaster.py) until
the clock reaches its end. The plan (fixtures/run1-rehearsal/rehearsal.plan):
  a0-control  I L M16    restarts nothing; the idle mark idle-1; L: index 0 fails (bench-blaster-03 ends
                         rc 1), retried as index 1; the saturated M16 is index 2
  v-vote      M16s       restarts every node (evict-mdbx); indices 3 and 4 fail: run-arms stops
                         (blast-failed-twice), leaving the arm open
  (resume: run-arms --from-arm 1)
  v-vote-r2   M16s       the resumed arm under its second name (restarted again: its evict step); index 5
  a0-prime    M16        back to the defaults: the closing control, the same type as the first; index 6
Node logs, persist and sampler CSVs come from no driver: after the walk they are synthesised in the names
contract's shapes (fixtures/arms-summary/lines.txt, tools/persist-csv-header.txt, the node sampler's
header), with each node's version and `node switches` lines written by the fake node itself at every
start (node-start.py). The walk takes a few minutes of real time (most of it the 33 node restarts); one
walk serves every test of the module.

Then every reader runs on the results tree, and the assertions pin what each must find.
Run: python3 -m unittest discover -s benchmark/tests -p test_run1_rehearsal.py -v
"""
import csv
import gzip
import importlib.util
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

import test_params_apply as tpa

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIX = TESTS / "fixtures" / "run1-rehearsal"
PA_FIX = TESTS / "fixtures" / "params-apply"
RUN_ID = "r20261104-0300"
# The clock when the walk begins: 2026-11-04T03:00:00Z. It must lie in the past: the arm tool's fake node stamps
# its container log with the real time, and the readback wants that line newer than the restart.
T_START = 1793761200
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/obs-lib.sh", "benchmark/recovery-lib.sh", "benchmark/benchmark-blast.sh",
        "benchmark/blaster-startup.sh", "benchmark/stall-scan.py", "benchmark/tools/params-apply.sh",
        "benchmark/launch/run-arms.sh", "benchmark/consensus-parameters.yaml")
NODES = ["bench-validator-%02d" % i for i in range(1, 11)] + ["bench-observer-11"]
ZONES = re.search(r"^export ZONES=\(([^)]*)\)", (BENCH / "config.sh").read_text(), re.M).group(1).replace('"', "").split()
VALIDATORS = NODES[:10]
# run 1's environment (benchmark/launch/bench6-run1.env) as far as the walk reads it
RUN1_ENV = {"BENCH_TAIL_SCAN_SECS": "180", "BENCH_LIGHT_START_DELAY_SECS": "150", "BENCH_LANDINGS_SAMPLE": "100",
            "BENCH_CHAOS": "0", "BENCH_LIGHT_LOAD": "0", "BENCH_PERSIST_SAMPLER": "1", "RUN_ARMS_MAX_QUEUED": "1000"}
DISPATCH = "blast_run_begin"
NODE_SHA = "ba43a1f0e270ca1c572d1b8378b39d2fc6360b57"   # the fake nodes' version line (fixtures/params-apply)
FAIL_INDICES = "0 3 4"   # bench-blaster-03 of these blast indices ends rc 1


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def unix(text):
    return int(time.mktime(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone)


def _exe(src, dest, text=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        shutil.copyfile(str(src), str(dest))
    else:
        dest.write_text(text)
    dest.chmod(0o755)


class Walk(object):
    """The sandbox and the walk. build() runs both run-arms invocations; the results tree is .results."""

    def __init__(self, root):
        self.root = Path(root)
        self.tree = self.root / "tree"
        self.bin = self.root / "bin"
        self.nodebin = self.root / "node-bin"
        self.nodes = self.root / "nodes"
        self.stub = self.root / "stub"
        self.clock = self.root / "clock"
        self.results = self.tree / "benchmark" / "results" / RUN_ID
        self.outputs = []

    # --- the sandbox ---------------------------------------------------------------------------------
    def setup(self):
        for rel in TREE:
            dst = self.tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / rel), str(dst))
        shutil.copytree(str(BENCH / "arms"), str(self.tree / "benchmark" / "arms"))
        shutil.copyfile(str(FIX / "rehearsal.plan"), str(self.tree / "benchmark" / "launch" / "rehearsal.plan"))
        # The blast driver: the real script, with the overrides sourced just before its dispatch.
        blast = self.tree / "benchmark" / "benchmark-blast.sh"
        lines = blast.read_text().split("\n")
        if lines.count(DISPATCH) != 1:
            raise AssertionError("benchmark-blast.sh: want one '%s' line (the dispatch), found %d" % (DISPATCH, lines.count(DISPATCH)))
        i = lines.index(DISPATCH)
        lines[i:i] = ['source "${REHEARSAL_OVERRIDES:?}"']
        blast.write_text("\n".join(lines))
        for name in ("gcloud", "date", "sleep", "curl"):
            _exe(FIX / "bin" / name, self.bin / name)
        for name in ("systemd-run", "curl", "python3"):
            _exe(PA_FIX / ("node-%s.sh" % name), self.nodebin / name)
        for name in ("systemctl", "docker"):
            _exe(FIX / "node-bin" / name, self.nodebin / name)
        for name in ("date", "sleep"):
            _exe(FIX / "bin" / name, self.nodebin / name)
        scripts = self.root / "node-scripts" / "lib"
        scripts.mkdir(parents=True)
        shutil.copyfile(str(PA_FIX / "node-lib-common.sh"), str(scripts / "common.sh"))
        for d in (self.stub, self.root / "tmp", self.root / "pa-scratch"):
            d.mkdir(parents=True, exist_ok=True)
        (self.stub / "fail-indices").write_text(FAIL_INDICES + "\n")
        self.clock.write_text("%d\n" % T_START)
        (self.root / "params.yaml").write_text("max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n")
        for k, n in enumerate(NODES):
            self.node(n, "observer" if n.endswith("-11") else "validator", k)
        self.results.mkdir(parents=True)
        # What the deploy left before the walk: manifest.instances[] as step 2 records it.
        manifest = {"schema": "tn-bench-manifest/v1", "run_id": RUN_ID, "notes": [], "timestamps": {},
                    "instances": [{"name": n, "role": "observer" if n.endswith("-11") else "validator",
                                   "zone": ZONES[k], "internal_ip": "192.0.2.%d" % (k + 1)} for k, n in enumerate(NODES)],
                    "blasters": [], "chaos": [], "abort": None, "phases": []}
        (self.results / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for name in ("deployments.json", "config.toml"):
            (self.root / name).write_text("{}\n")

    def node(self, name, role, k):
        d = self.nodes / name
        for sub in ("data", "var/lib/bench-logs", "state", "tmp"):
            (d / sub).mkdir(parents=True)
        (d / "data" / "parameters.yaml").write_text(tpa.YAML)
        (d / "data" / "first-parameters.yaml").write_text(tpa.YAML)
        for rel, src in ((tpa.V2_START, "v2-tn-start-docker"), (tpa.V2_META, "v2-node-meta")):
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text((PA_FIX / src).read_text().replace(tpa.V2_DATADIR, str(d / "data")))
        (d / "role").write_text(role)
        (d / "mode").write_text("healthy")
        (d / "pre.log").write_text((PA_FIX / ("node-log-pre-%s.txt" % role)).read_text() + tpa.switches_line() + "\n")
        # the deploy's start, an hour before the walk: every switch at its default
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(T_START - 3600 + k)) + ".000000000Z"
        (d / "unit-stdout.log").write_text('ts=%s level=info target=cli message="telcoin-network 0.1.0 (%s) starting"\n'
                                           % (ts, NODE_SHA) + tpa.switches_line(ts="ts=" + ts) + "\n")

    def env(self, **extra):
        e = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
             "HOME": str(self.root), "TMPDIR": str(self.root / "tmp"), "CLOCK": str(self.clock), "STUB": str(self.stub),
             "REHEARSAL_FIX": str(FIX), "REHEARSAL_OVERRIDES": str(FIX / "overrides.sh"),
             "REHEARSAL_NODES": " ".join(NODES), "BENCH_TXGEN_SHA": "abcdef1", "TN_IAP_RETRIES": "0",
             "BENCH_PARAMETERS_FILE": str(self.root / "params.yaml"), "BENCH_RUN_ID": RUN_ID,
             "PA_GCLOUD": str(PA_FIX / "gcloud.py"), "PA_FIX": str(PA_FIX), "PA_NODES": str(self.nodes),
             "PA_NODE_BIN": str(self.nodebin), "PA_SHIM_LOG": str(self.root / "pa-calls.jsonl"),
             "PA_SWITCHES_TSV": str(self.tree / "benchmark" / "arms" / "switches.tsv"),
             "PARAMS_APPLY_NODE_SCRIPTS_DIR": str(self.root / "node-scripts"), "PARAMS_APPLY_HEALTH_SECS": "30",
             "PARAMS_APPLY_RETRY_SECS": "0", "PARAMS_APPLY_GUARD_SECS": "0", "PARAMS_APPLY_GUARD_DEFER_SECS": "0",
             "PA_REAL_PYTHON3": sys.executable,
             "BENCH_TXGEN_CONFIG": str(self.root / "config.toml"), "BENCH_DEPLOYMENTS_FILE": str(self.root / "deployments.json")}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                e[key] = os.environ[key]
        e.update(RUN1_ENV)
        e.update(extra)
        return e

    def run_arms(self, *args):
        p = subprocess.run(["bash", str(self.tree / "benchmark" / "launch" / "run-arms.sh"),
                            "--plan", "benchmark/launch/rehearsal.plan"] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env(), cwd=str(self.tree),
                           universal_newlines=True, timeout=900)
        (self.root / ("run-arms-%d.out" % len(self.outputs))).write_text(p.stdout)
        self.outputs.append(p)
        return p

    def build(self):
        self.setup()
        first = self.run_arms()
        second = self.run_arms("--from-arm", "1")
        return first, second

    def manifest(self):
        return json.loads((self.results / "manifest.json").read_text())

    # --- what no driver writes: node logs and persist CSVs, as the teardown would pull them ---------
    def blasts(self):
        """[(index, rc, mixed start, mixed end)] of every blast in the tree, the mixed span being the
        union of its generators' run.phases (rc from the manifest's blast_runs[] `run` entries)."""
        rcs = dict((r["index"], r["rc"]) for r in self.manifest().get("blast_runs") or [] if r.get("action") == "run")
        out = []
        dirs = [(int(d.name.split("-")[1]), d / "blasters") for d in self.results.glob("blast-*")]
        dirs.append((self.manifest()["blast"]["run_index"], self.results / "blasters"))
        for idx, d in sorted(dirs):
            spans = []
            for f in sorted(d.glob("bench-blaster-*.json")):
                ph = dict((p["name"], p) for p in json.loads(f.read_text())["run"]["phases"])
                spans.append((ph["mixed"]["start_unix"], ph["mixed"]["end_unix"]))
            out.append((idx, rcs.get(idx), int(min(s for s, _ in spans)), int(max(e for _, e in spans)) + 1))
        return out

    def synthesise(self):
        """Each node's log (its own start and `node switches` lines, then engine, proposal, quorum and vote
        lines over every blast's mixed phase and the idle mark, in the names contract's shapes) into
        logs/<node>-unit-stdout.log.gz; a persist CSV per node into persist/ and a node-sampler CSV (one
        block a second) into sampler/. Commit costs by arm: 100 ms (a0-control), 115 (v-vote, v-vote-r2),
        130 (a0-prime): the drift the summary must see."""
        shapes = dict(l.split("\t", 1) for l in (TESTS / "fixtures" / "arms-summary" / "lines.txt").read_text().splitlines())
        m = self.manifest()
        arms = [(unix(a["begin"]), a["name"]) for a in m["param_arms"]]
        cost = {"a0-control": 100, "v-vote": 115, "v-vote-r2": 115, "a0-prime": 130}
        spans = [(f, t) for _, rc, f, t in self.blasts() if rc == 0]
        for a in m["param_arms"]:
            for mk in a.get("marks") or []:
                spans.append((unix(mk["begin"]), unix(mk["end"])))
        end = int(self.clock.read_text())

        def stamp(t):
            return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(t))) + ".%06d000Z" % int(round((t % 1) * 1e6))

        (self.results / "logs").mkdir(exist_ok=True)
        (self.results / "persist").mkdir(exist_ok=True)
        header = (BENCH / "tools" / "persist-csv-header.txt").read_text().strip().split(",")
        sampler_header = (TESTS / "fixtures" / "analysis" / "run" / "sampler" / "bench-validator-01.csv"
                          ).read_text().splitlines()[0].split(",")
        (self.results / "sampler").mkdir(exist_ok=True)
        for n in NODES:
            lines, cn = [], 1
            for f, t in sorted(spans):
                arm = [name for b, name in arms if b <= f][-1]
                for k in range(f - 30, t + 30, 10):
                    lines.append((k + 5, shapes["executed"].format(ts=stamp(k + 5), cn=cn, round=cn * 2, execute_ms=50,
                                                                   persist_ms=cost[arm] + 20, txs=1000)))
                    lines.append((k + 5.001, shapes["persisted"].format(ts=stamp(k + 5.001), cn=cn, txs=1000, commit_ms=cost[arm],
                                                                        newly=200, cow=100, pw=2000000)))
                    lines.append((k + 5.002, shapes["task"].format(ts=stamp(k + 5.002), cn=cn, task_ms=70 + cost[arm])))
                    cn += 1
                if n in VALIDATORS:
                    for r in range(f, t, 2):
                        lines.append((r + 0.1, shapes["proposed"].format(ts=stamp(r + 0.1), round=r)))
                        lines.append((r + 0.4, shapes["quorum"].format(ts=stamp(r + 0.4), round=r)))
                        lines.append((r + 0.3, shapes["vote"].format(ts=stamp(r + 0.3), author="A1", round=r,
                                                                     outcome="created", lock_ms=40)))
            own = (self.nodes / n / "unit-stdout.log").read_text().splitlines()
            text = "\n".join(own + [l for _, l in sorted(lines)]) + "\n"
            (self.results / "logs" / (n + "-unit-stdout.log.gz")).write_bytes(gzip.compress(text.encode()))
            with open(str(self.results / "sampler" / (n + ".csv")), "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(sampler_header)
                for k in range(T_START - 600, end + 30, 30):
                    row = dict.fromkeys(sampler_header, "")
                    row.update(ts_unix=k, pid=4242, block=k - T_START + 600)
                    w.writerow([row[c] for c in sampler_header])
            with open(str(self.results / "persist" / (n + ".csv")), "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                disk = 0
                for k in range(T_START - 600, end + 30, 30):
                    row = dict.fromkeys(header, "")
                    row.update(ts_unix=k, pid=4242, disk_wr_bytes_total=disk)
                    if k % 300 == 0:
                        row.update(mdbx_dat_vma_bytes=10 ** 9, mdbx_dat_rr_bytes=10 ** 9, mdbx_dat_size_bytes=5 * 10 ** 8)
                    w.writerow([row[c] for c in header])
                    disk += 30 * 245760

    # --- the readers -------------------------------------------------------------------------------
    def tool(self, *argv, **kw):
        p = subprocess.run([sys.executable] + [str(a) for a in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=kw.get("timeout", 300), cwd=str(self.root))
        return p

    def summary(self, *extra):
        out = self.root / "summary"
        p = self.tool(BENCH / "tools" / "arms-summary.py", "--run-dir", self.results, "--out-dir", out,
                      "--cache-dir", self.root / "summary-cache", "--prefiltered", self.root / "no-prefilter", *extra)
        doc = json.loads((out / "arms.json").read_text()) if p.returncode == 0 else None
        return p, doc


def load_module(name, path):
    sys.path.insert(0, str(Path(path).parent))
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.pop(0)


ARMS_BLAST_RE = re.compile(r"^ARMS_BLAST arm=(\S+) step=\d+ kind=(\S+) index=(\d+) attempt=(\d) fund_rc=(\S+) run_rc=(\S+) ")
# Each blast index of the walk: its run-arms type, the type's record (kind, senders, window, warmup, mixed and
# cooldown seconds: run-arms.sh type_env) and the arm in force when it started (by the arms' begin).
WALK_TYPES = {0: "L", 1: "L", 2: "M16", 3: "M16s", 4: "M16s", 5: "M16s", 6: "M16"}
TYPE_RECORD = {"L": ("light", 8, 16, 60, 360, 60), "M16": ("load", 600, 16, 120, 480, 180),
               "M16s": ("load", 600, 16, 120, 300, 180)}
WALK_ARMS = {0: "a0-control", 1: "a0-control", 2: "a0-control", 3: "v-vote", 4: "v-vote", 5: "v-vote-r2", 6: "a0-prime"}
TYPE_KEYS = ("kind", "senders", "window", "warmup_secs", "duration_secs", "cooldown_secs")
# A reader that mishandles what the drivers now record (H13's hand-back): pinned as it behaves, so the fix shows
# up here. The unit that fixes the reader flips the assertion.
FINDING = "reader finding %s is fixed: flip this assertion to the right behaviour"


class Run1RehearsalTests(unittest.TestCase):
    """One walk for the module (setUpClass), then each reader on its results tree."""
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="run1-rehearsal-")
        cls.walk = Walk(cls._tmp.name)
        cls.first, cls.second = cls.walk.build()
        cls.walk.synthesise()
        cls.m = cls.walk.manifest()
        cls.R = cls.walk.results
        cls.arms = dict((a["name"], a) for a in cls.m["param_arms"])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def mixed(self, blasters_dir):
        """(latest mixed start, earliest mixed end) over a blast's generators: the window every one was in mixed."""
        spans = []
        for f in sorted(Path(blasters_dir).glob("bench-blaster-*.json")):
            ph = dict((p["name"], p) for p in json.loads(f.read_text())["run"]["phases"])
            spans.append((ph["mixed"]["start_unix"], ph["mixed"]["end_unix"]))
        self.assertEqual(len(spans), 10, blasters_dir)
        return max(s for s, _ in spans), min(e for _, e in spans)

    def blast_dir(self, idx):
        if idx == self.m["blast"]["run_index"]:
            return self.R / "blasters"
        dirs = sorted(self.R.glob("blast-%d-*" % idx))
        self.assertEqual(len(dirs), 1, idx)
        return dirs[0] / "blasters"

    def arm_window(self, name):
        a = self.arms[name]
        return unix(a.get("ready") or a["begin"]), unix(a["end"])

    # --- the walk, as the drivers recorded it -----------------------------------------------------
    def test_the_walk_as_the_sequencer_ran_it(self):
        out1, out2 = self.first.stdout, self.second.stdout
        self.assertEqual(self.first.returncode, 1, out1[-3000:])
        self.assertIn("ARMS_STOPPED arm=v-vote step=1 reason=blast-failed-twice ", out1)
        self.assertEqual(self.second.returncode, 0, out2[-3000:])
        self.assertIn("ARMS_DONE arms=2 blasts=2 ", out2)
        blasts = [m.groups() for m in (ARMS_BLAST_RE.match(l) for l in (out1 + out2).splitlines()) if m]
        self.assertEqual(blasts, [("a0-control", "L", "0", "1", "0", "1"), ("a0-control", "L", "1", "2", "0", "0"),
                                  ("a0-control", "M16", "2", "1", "0", "0"), ("v-vote", "M16s", "3", "1", "0", "1"),
                                  ("v-vote", "M16s", "4", "2", "0", "1"), ("v-vote-r2", "M16s", "5", "1", "0", "0"),
                                  ("a0-prime", "M16", "6", "1", "0", "0")])
        # param_arms[]: the resumed arm under its second name, the arm the stop left open ended by the next apply
        self.assertEqual(list(self.arms), ["a0-control", "v-vote", "v-vote-r2", "a0-prime"])
        a0, vv, r2, prime = (self.arms[n] for n in self.arms)
        self.assertTrue(a0["no_restart"])
        self.assertEqual(a0["ready"], a0["begin"])
        self.assertEqual([mk["label"] for mk in a0["marks"]], ["idle-1"])
        self.assertEqual(unix(a0["marks"][0]["end"]) - unix(a0["marks"][0]["begin"]), 300)
        self.assertEqual(vv["end"], r2["begin"])
        for a in (vv, r2, prime):
            self.assertEqual(sorted(a["nodes"]), sorted(NODES), a["name"])
            self.assertEqual(unix(a["ready"]) - unix(a["begin"]) >= 120, True, a["name"])
            self.assertEqual([h["step"] for h in a["host"]], ["evict-mdbx"], a["name"])
        self.assertEqual(r2["switches"], vv["switches"])
        self.assertEqual(r2["file"], "benchmark/arms/v-vote.arm")
        self.assertEqual(prime["switches"], a0["switches"])
        for a in self.m["param_arms"]:
            self.assertIsNotNone(a["end"], a["name"])

    def test_what_a_hand_run_leaves(self):
        runs = self.m["blast_runs"]
        self.assertEqual([(r["action"], r["index"], r["rc"]) for r in runs],
                         [(act, i, 1 if (act == "run" and i in (0, 3, 4)) else 0) for i in range(7) for act in ("fund", "run")])
        self.assertEqual([(b["index"], b["rc"]) for b in self.m["blasts"]],
                         [(i, 1 if i in (0, 3, 4) else 0) for i in range(7)])
        self.assertEqual(sorted(re.sub(r"-[0-9]{8}T[0-9]{6}Z$", "", d.name) for d in self.R.glob("blast-*")),
                         ["blast-%d" % i for i in range(6)])
        self.assertEqual(sorted(re.sub(r"-[0-9]{8}T[0-9]{6}Z$", "", d.name) for d in self.R.glob("funder-*")),
                         ["funder-%d" % i for i in range(6)])
        top = self.m["blast"]
        self.assertEqual((top["run_index"], top["chaos"], top["tail_scan_secs"]), (6, 0, 180))
        self.assertEqual(sorted(top["pool_at_start"]), sorted(NODES))
        self.assertIn("phases_planned", self.m)
        for d in sorted(self.R.glob("blast-*")):
            idx = int(d.name.split("-")[1])
            copy = json.loads((d / "manifest.json").read_text())
            self.assertEqual(copy["blast"]["run_index"], idx)
            self.assertIn("phases_planned", copy, d.name)
            self.assertEqual(len(copy["blasters"]), 10)
            rcs = dict((b["name"], b.get("rc")) for b in copy["blasters"])
            self.assertEqual(rcs["bench-blaster-03"], 1 if idx in (0, 3, 4) else 0, d.name)
            # the failed blaster's /out, fetched over IAP before its delete, travels with the blast
            self.assertEqual((d / "blasters" / "scp-bench-blaster-03").is_dir(), idx in (0, 3, 4), d.name)

    def test_each_hand_run_is_recorded_like_a_scripted_blast(self):
        """H12's driver gaps, closed by H13: D1 and D2 (a hand run's blasts[] entry, the blast's type in .blast), D5
        (blast_runs[].log follows the archive)."""
        copies = dict((int(d.name.split("-")[1]), json.loads((d / "manifest.json").read_text())) for d in self.R.glob("blast-*"))
        copies[self.m["blast"]["run_index"]] = self.m
        self.assertEqual(sorted(copies), list(range(7)))
        # D1: every blast's own record says what it was, the archived copies included
        for i, doc in sorted(copies.items()):
            self.assertEqual(tuple(doc["blast"][k] for k in TYPE_KEYS), TYPE_RECORD[WALK_TYPES[i]], i)
        # D2: one blasts[] entry per hand `run`, failed ones too, in light_record's keys and order plus the blast's
        # own record; the same times and rc as its blast_runs[] entry; the arm in force by its begin
        runs = [r for r in self.m["blast_runs"] if r["action"] == "run"]
        blasts = self.m["blasts"]
        self.assertEqual(len(blasts), len(runs))
        for b, r in zip(blasts, runs):
            i = b["index"]
            self.assertEqual(list(b), ["index", "senders", "window", "chaos", "started", "ended", "rc", "kind", "arm",
                                       "phases", "phases_planned", "pool_at_start"], i)
            self.assertEqual((i, b["started"], b["ended"], b["rc"]), (r["index"], r["started"], r["ended"], r["rc"]))
            self.assertEqual((b["kind"], b["senders"], b["window"], b["chaos"], b["arm"]),
                             TYPE_RECORD[WALK_TYPES[i]][:3] + (0, WALK_ARMS[i]), i)
            self.assertEqual((b["phases"], b["phases_planned"], b["pool_at_start"]),
                             (copies[i]["phases"], copies[i]["phases_planned"], copies[i]["blast"]["pool_at_start"]), i)
        # a fund records no blast
        self.assertEqual(len([r for r in self.m["blast_runs"] if r["action"] == "fund"]), 7)
        # D5: every blast_runs[].log is where the log is now; an archived run's points into its blast-<i>-<UTC>/
        for r in self.m["blast_runs"]:
            self.assertTrue((self.R / r["log"]).is_file(), r)
            if r["action"] == "run" and r["index"] != self.m["blast"]["run_index"]:
                self.assertRegex(r["log"], r"^blast-%d-\d{8}T\d{6}Z/logs/blast-run-\d{8}T\d{6}Z\.log$" % r["index"])

    def test_the_sequencer_log_is_part_of_the_run(self):
        """D3: each run-arms invocation's own log under results/<run>/logs/, with its retries and its stop."""
        logs = sorted((self.R / "logs").glob("run-arms-*.log"))
        self.assertEqual([re.sub(r"\d{8}T\d{6}Z", "<UTC>", l.name) for l in logs], ["run-arms-hand-<UTC>.log"] * 2)
        for log, p in zip(logs, (self.first, self.second)):
            text = log.read_text()
            self.assertEqual([l for l in text.splitlines() if l.startswith("ARMS_")],
                             [l for l in p.stdout.splitlines() if l.startswith("ARMS_")], log.name)
        first, second = (l.read_text() for l in logs)
        self.assertEqual(len(re.findall(r"(?m)^ARMS_RETRY ", first)), 2)
        self.assertRegex(first, r"(?m)^ARMS_STOPPED arm=v-vote step=1 reason=blast-failed-twice ")
        self.assertRegex(first, r"(?m)^ARMS_RESUME BENCH_RUN_ID=%s benchmark/launch/run-arms.sh " % RUN_ID)
        self.assertRegex(second, r"(?m)^ARMS_DONE arms=2 blasts=2 ")

    # --- the readers ------------------------------------------------------------------------------
    def test_arms_summary_rows(self):
        p, doc = self.walk.summary()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = dict((r["row_id"], r) for r in doc["summary_rows"])
        self.assertEqual([(r["row_id"], r["blast_idx"], r["arm_name"], r["blast_type"]) for r in doc["summary_rows"]],
                         [("a0-control/I", None, "a0-control", "I"), ("a0-control/L", 1, "a0-control", "L"),
                          ("a0-control/M16", 2, "a0-control", "M16"), ("v-vote-r2/M16s", 5, "v-vote-r2", "M16s"),
                          ("a0-prime/M16", 6, "a0-prime", "M16")])
        for rid, r in rows.items():
            if r["blast_idx"] is None:
                mk = self.arms["a0-control"]["marks"][0]
                want = (mk["begin"], mk["end"])
            else:
                a, b = self.mixed(self.blast_dir(r["blast_idx"]))
                f, t = self.arm_window(r["arm_name"])
                want = (iso(max(a, f)), iso(min(b, t)))
            self.assertEqual((r["utc_from"], r["utc_to"]), want, rid)
        for i in (0, 3, 4):
            self.assertIn("not measured: blast index %d: rc 1, not measured" % i, doc["notes"])
        roles = dict((a["arm_name"], a["roles"]) for a in doc["arm_list"])
        self.assertEqual(roles["v-vote-r2"], roles["v-vote"])
        self.assertEqual((roles["a0-control"], roles["a0-prime"]), (["control"], ["control", "drift"]))
        d = doc["drift"]["M16"]
        self.assertEqual((d["first"], d["last"], d["moved_pct"], d["adjacent_only"]),
                         ("a0-control/M16", "a0-prime/M16", 30.0, True))
        m16, prime, r2 = rows["a0-control/M16"], rows["a0-prime/M16"], rows["v-vote-r2/M16s"]
        self.assertEqual((m16["commit_us_tx"], r2["commit_us_tx"], prime["commit_us_tx"]), (100.0, 115.0, 130.0))
        self.assertEqual((m16["amp_fleet_median"], m16["late_secs_max"], m16["tail_landed_late"]), (2.0, 2.5, 20))
        self.assertEqual((r2["evict_resident_after_max"], prime["evict_resident_after_max"]), (0, 0))
        self.assertEqual(r2["switch_set"], ",".join("%s=%s" % kv for kv in sorted(
            (k, v) for k, v in self.arms["v-vote"]["switches"].items() if v != self.arms["a0-control"]["switches"][k])))

    def test_report_windows_helpers(self):
        windows = load_module("rehearsal_windows", BENCH / "report" / "windows.py")
        self.assertEqual([(w["name"], w["start"], w["start_unix"], w["end_unix"]) for w in windows.arm_windows(self.m)],
                         [(n, "ready") + self.arm_window(n) for n in self.arms])
        # D2 closed: each helper finds the hand-run blasts in blasts[], with their kind, window and arm
        light = windows.light_blasts(str(self.R), self.m)
        load = windows.load_blasts(str(self.R), self.m)
        self.assertEqual([(b["index"], b["name"], b["kind"], b["window"], b["arm"], b["rc"]) for b in light],
                         [(1, "light8", "light", 16, "a0-control", 0)])
        self.assertEqual([(b["index"], b["name"], b["kind"], b["window"], b["arm"], b["rc"]) for b in load],
                         [(2, "load600", "load", 16, "a0-control", 0), (5, "load600", "load", 16, "v-vote-r2", 0)])
        for b in light + load:
            self.assertEqual(Path(b["dir"]) / "blasters", self.blast_dir(b["index"]))
        floor, caveats = windows.floor_blast(str(self.R), self.m)
        self.assertEqual((floor["index"], caveats), (1, []))
        # the failed blasts are recorded with their rc, and no helper that feeds a KPI returns one
        self.assertEqual([(b["index"], b["rc"]) for b in self.m["blasts"] if b["rc"] != 0], [(0, 1), (3, 1), (4, 1)])
        measured = [b["index"] for b in light + load] + [floor["index"]] + [
            w["index"] for w in windows.light_windows(str(self.R), self.m) + windows.load_windows(str(self.R), self.m)]
        self.assertEqual(sorted(set(measured)), [1, 2, 5])

    def arm_rows(self, names):
        return [(n, iso(self.arm_window(n)[0]), iso(self.arm_window(n)[1])) for n in names]

    def test_cert_rate_windows(self):
        p = self.walk.tool(BENCH / "tools" / "cert-rate.py", "--logs", self.R / "logs", "--windows",
                           self.R / "manifest.json", "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        ws = [(w["name"], w["start"], w["end"]) for w in json.loads(p.stdout)["windows"]]
        self.assertEqual([w for w in ws if w[0].startswith("arm ")],
                         [("arm " + n, f, t) for n, f, t in self.arm_rows(self.arms)])

    def test_stage_latency_windows(self):
        p = self.walk.tool(BENCH / "tools" / "stage-latency.py", "--run-dir", self.R, "--windows", self.R / "manifest.json",
                           "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        ws = json.loads(p.stdout)["windows"]
        mk = self.arms["a0-control"]["marks"][0]
        self.assertEqual(dict((k, (v["start"], v["end"])) for k, v in ws.items() if k != "all"),
                         dict([(n, (f, t)) for n, f, t in self.arm_rows(self.arms)]
                              + [("a0-control/idle-1", (mk["begin"], mk["end"]))]))

    def test_stage_latency_without_windows_still_names_failed_blasts(self):
        """FINDING R1 for the reader unit: without --windows, stage-latency.py (derived_windows) makes a window of
        every blast it finds, rc never read. Now that the hand runs are in blasts[], the failed light blast (index 0)
        takes the plain name and the measured one (index 1) gets the -2 suffix; v-vote's two windows are both
        failed blasts."""
        p = self.walk.tool(BENCH / "tools" / "stage-latency.py", "--run-dir", self.R, "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        ws = dict((k, (v["start"], v["end"])) for k, v in json.loads(p.stdout)["windows"].items())

        def mixed(i):
            b = [b for b in self.m["blasts"] if b["index"] == i][0]
            return [(ph["start"], ph["end"]) for ph in b["phases"] if ph["name"] == "mixed"][0]

        self.assertEqual(ws.get("a0-control/light8x16"), mixed(0), FINDING % "R1")
        self.assertEqual(ws.get("a0-control/light8x16-2"), mixed(1), FINDING % "R1")
        self.assertEqual((ws.get("v-vote/load600x16"), ws.get("v-vote/load600x16-2")), (mixed(3), mixed(4)), FINDING % "R1")

    def test_block_rate_and_propose_latency_windows(self):
        mk = self.arms["a0-control"]["marks"][0]
        p = self.walk.tool(BENCH / "tools" / "block-rate.py", "--run", self.R, "--windows", self.R / "manifest.json",
                           "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        ws = dict((w["name"], (w["start"], w["secs"])) for w in json.loads(p.stdout)["windows"])
        for n, f, t in self.arm_rows(self.arms):
            self.assertEqual(ws["arm " + n], (f, unix(t) - unix(f)), n)
        self.assertEqual(ws["mark a0-control/idle-1"], (mk["begin"], 300))
        p = self.walk.tool(BENCH / "tools" / "propose-latency.py", "--logs", self.R / "logs", "--windows",
                           self.R / "manifest.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        for n, f, t in self.arm_rows(self.arms):
            self.assertIn("## arm %s: %s → %s (%d s)" % (n, f, t, unix(t) - unix(f)), p.stdout)
        self.assertIn("## mark a0-control/idle-1: %s → %s (300 s)" % (mk["begin"], mk["end"]), p.stdout)

    def test_provenance_switch_lines_against_the_arm_in_force(self):
        p = self.walk.tool(BENCH / "report" / "provenance.py", "--run-dir", self.R, "--expect-sha", NODE_SHA, "--json")
        doc = json.loads(p.stdout)
        self.assertEqual(doc["problems"], [])
        self.assertTrue(doc["ok"])
        # every node: the deploy's start, then v-vote, v-vote-r2 (same state, second name) and a0-prime;
        # a0-control restarted nothing
        self.assertEqual((doc["switches"]["checked"], doc["switches"]["matched"]), (4 * len(NODES), 4 * len(NODES)))


if __name__ == "__main__":
    w = Walk(sys.argv[1])
    if not (w.results / "manifest.json").exists():
        a, b = w.build()
        print("first rc", a.returncode, "second rc", b.returncode)
        w.synthesise()
    p, doc = w.summary(*sys.argv[2:])
    print(p.returncode, p.stderr[-2000:])
    if doc:
        print(json.dumps(doc["notes"], indent=1))
        print(json.dumps(doc["arm_list"]))
        for r in doc["summary_rows"]:
            print(json.dumps(r))
