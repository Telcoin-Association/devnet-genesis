"""The admission gate and fleet readiness helpers of bench-lib.sh (contract C3/C4a), fully offline.

What runs is the real bench-lib.sh, sourced the way benchmark-deploy.sh sources it: a temporary copy
of the scripts it loads (TREE), `$0` = benchmark-deploy.sh (benchmark/config.sh only loads for its
allowlisted callers), BENCH_RUN_ID set, and a clean environment. Nothing reaches GCP or a node:

* `gcloud` on PATH is a fake (FAKE_GCLOUD) that only answers `compute ssh <inst> ...`. The admission
  read (`--ssh-flag=-T --command=sudo bash -s`, script on stdin) and the tn_nodeMode read
  (`--command=curl ... tn_nodeMode ...`) are answered from a per-instance plan: step n of the plan
  answers the n-th read of that kind on that instance, the last step repeats. A step either fails like
  a dropped IAP session (ssh rc 255) or runs the remote command here, under bash, with a node-side
  `curl` stub (NODE_CURL) first on PATH serving one of fixtures/admission/*.prom as the node's
  /metrics body and a given tn_nodeMode answer. So the remote script bench-lib.sh sends is parsed
  and executed, not just matched. Every call is logged; the tests count reads per instance from it.
* `curl` on the host PATH refuses (the harness side never curls a node itself).
* `sleep` and `_bench_next_boundary` are redefined after sourcing (bench-lib.sh allows both): sleep
  records its argument instead of waiting, the boundary is "now".

The fixtures and their expected parse are documented in fixtures/admission/README.md.
VerdictTests.test_grace_worker_is_not_closed is the target of mutation M1 (`_bench_adm_closed`).
"""
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
REPO = BENCH.parent
FIX = TESTS / "fixtures" / "admission"
SCRUB_PY = BENCH / "report" / "scrub.py"

# Scripts the bash under test sources, relative to the repo root.
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh")
RUN_ID = "rtest-admission"
PARAMS_YAML = "max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n"
NODES = ["bench-validator-%02d" % n for n in range(1, 11)] + ["bench-observer-11"]
VALIDATORS = NODES[:10]
OBSERVER = NODES[10]
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# The C3 filter bench_admission_read applies on the node.
FILTER_RE = re.compile(r"^tn_network_(admission_mode|admission_fallback|closed_admission_denied_total)[{ ]")
PARSE_KEYS = ("mode_primary", "mode_worker", "fallback", "fallback_n", "denied_in", "denied_out", "node_mode")
# fixtures/admission/README.md, "Expected parse and verdict": filtered lines, then PARSE_KEYS in order.
README_TABLE = {
    "closed": (8, "2", "2", "0", "2", "3", "1", "CvvActive"),
    "grace-worker": (8, "2", "1", "0", "2", "0", "0", "CvvActive"),
    "fallback-active": (8, "2", "2", "1", "2", "0", "0", "CvvActive"),
    "missing-worker": (4, "2", "-", "0", "1", "0", "0", "Observer"),
    "reordered-labels-with-ts": (8, "2", "2", "0", "2", "3", "1", "CvvActive"),
}
DECOY_FAMILIES = ("tn_network_source_admission_denied_total", "tn_network_admission_contradicted",
                  "tn_network_admission_required_current", "tn_network_admission_resolved_current")
OK_CLOSED = "ADM_OK %s primary=2 worker=2 fallback=0 denied_in=3 denied_out=1 mode=CvvActive"
# C4a admission[] entry keys. No ip/id keys: the scrubber drops those.
ADMISSION_KEYS = {"inst", "mode_primary", "mode_worker", "fallback", "denied_in", "denied_out", "node_mode", "ts"}
FLEET_READY_KEYS = {"label", "ts", "ok", "waited_secs", "passes", "modes"}

FAKE_GCLOUD = r'''#!/usr/bin/env python3
"""Fake gcloud (test_admission_gate): `compute ssh <inst> ... --command=<cmd>` only; see the module doc."""
import json
import os
import subprocess
import sys

state = os.environ["FAKE_STATE"]
argv = sys.argv[1:]


def log(rec):
    with open(os.path.join(state, "calls.jsonl"), "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def refuse(inst):
    log({"inst": inst, "kind": "other", "argv": argv, "rc": 2})
    sys.stderr.write("fake gcloud: unexpected call %r\n" % (argv,))
    sys.exit(2)


if argv[:2] != ["compute", "ssh"] or len(argv) < 3 or argv[2].startswith("-"):
    refuse("")
inst = argv[2]
cmds = [a[len("--command="):] for a in argv[3:] if a.startswith("--command=")]
if len(cmds) != 1:
    refuse(inst)
cmd = cmds[0]
if cmd == "sudo bash -s" and "--ssh-flag=-T" in argv:
    kind = "adm"
elif cmd.startswith("curl ") and "tn_nodeMode" in cmd:
    kind = "mode"
else:
    refuse(inst)

counts_path = os.path.join(state, "counts.json")
counts = {}
if os.path.exists(counts_path):
    with open(counts_path) as fh:
        counts = json.load(fh)
n = counts.get(inst + " " + kind, 0) + 1
counts[inst + " " + kind] = n
with open(counts_path, "w") as fh:
    json.dump(counts, fh)

with open(os.environ["FAKE_PLAN"]) as fh:
    plan = json.load(fh)
steps = plan.get(inst, {}).get(kind) or [{"prom": "closed"} if kind == "adm" else {"mode": "CvvActive"}]
step = steps[min(n, len(steps)) - 1]
script = sys.stdin.read() if kind == "adm" else ""

if "rc" in step:
    log({"inst": inst, "kind": kind, "n": n, "rc": step["rc"]})
    sys.stderr.write("ssh: connect to host %s port 22: Connection timed out\n" % inst)
    sys.exit(step["rc"])

env = dict(os.environ)
env["PATH"] = os.environ["FAKE_NODEBIN"] + os.pathsep + os.environ.get("PATH", "")
if kind == "adm":
    syntax = subprocess.run(["bash", "-n"], input=script, universal_newlines=True)
    if syntax.returncode != 0:
        log({"inst": inst, "kind": kind, "n": n, "rc": 99, "error": "remote script does not parse"})
        sys.exit(99)
    prom = step.get("prom") or ""
    env["FAKE_PROM"] = os.path.join(os.environ["FAKE_FIXTURES"], prom + ".prom") if prom else ""
    mode = step.get("node_mode")
    if "node_mode" not in step and prom:
        with open(env["FAKE_PROM"]) as fh:
            modes = [l.strip()[len("NODE_MODE="):] for l in fh if l.startswith("NODE_MODE=")]
        mode = modes[-1] if modes else None
    run = ["bash", "-s"]
else:
    mode = step.get("mode")
    run = ["bash", "-c", cmd]
env["FAKE_NODE_MODE"] = "" if mode in (None, "-") else mode
proc = subprocess.run(run, input=script, env=env, universal_newlines=True)
log({"inst": inst, "kind": kind, "n": n, "rc": proc.returncode})
sys.exit(proc.returncode)
'''

# The node's curl, as the remote commands use it: /metrics on 127.0.0.1 serves $FAKE_PROM without its
# NODE_MODE line; the tn_nodeMode call on 127.0.0.1:8545 answers $FAKE_NODE_MODE. An empty source
# fails like a refused connection (rc 7); any other call is a test error (rc 2).
NODE_CURL = r'''#!/usr/bin/env bash
url="" data=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -s) shift ;;
        --max-time|-H) shift 2 ;;
        --data) data="$2"; shift 2 ;;
        http://*) url="$1"; shift ;;
        *) echo "node curl stub: unexpected argument '$1'" >&2; exit 2 ;;
    esac
done
case "$url" in
    http://127.0.0.1:[0-9]*/metrics)
        [ -z "$data" ] || exit 2
        [ -n "${FAKE_PROM:-}" ] && [ -r "$FAKE_PROM" ] || exit 7
        grep -v '^NODE_MODE=' "$FAKE_PROM"
        exit 0 ;;
    http://127.0.0.1:8545)
        case "$data" in *'"method":"tn_nodeMode"'*) ;; *) exit 2 ;; esac
        [ -n "${FAKE_NODE_MODE:-}" ] || exit 7
        printf '{"jsonrpc":"2.0","id":1,"result":"%s"}' "$FAKE_NODE_MODE"
        exit 0 ;;
esac
exit 2
'''

HOST_CURL = r'''#!/usr/bin/env bash
printf '{"kind": "host-curl", "rc": 2}\n' >> "$FAKE_STATE/calls.jsonl"
echo "host curl stub: the harness must not curl from this host" >&2
exit 2
'''

PRELUDE = r'''
set -euo pipefail
source "$1/bench-lib.sh"
# No real waiting: record every sleep (in a file, not on stdout: some run inside $(...)).
sleep() { printf '%s\n' "$*" >> "${SLEEP_LOG}"; }
'''

GATE = PRELUDE + r'''
bench_manifest_init >/dev/null
bench_admission_gate
'''

FLEET = PRELUDE + r'''
_bench_next_boundary() { bench_now_unix; }
bench_manifest_init >/dev/null
bench_fleet_ready "$2" "$3"
'''

# parse <file>... : "== <file>" then bench_admission_parse's output, per file.
PARSE = r'''
set -euo pipefail
source "$1/bench-lib.sh"
shift
for f in "$@"; do echo "== $f"; bench_admission_parse < "$f"; done
'''

# verdict <inst> <file> ... : bench_admission_verdict over the file's parse, then RC=<status>.
VERDICT = r'''
set -euo pipefail
source "$1/bench-lib.sh"
shift
while [ "$#" -ge 2 ]; do
    rc=0; bench_admission_verdict "$1" "$(bench_admission_parse < "$2")" || rc=$?
    echo "RC=${rc}"
    shift 2
done
'''

# M1: what _bench_adm_closed accepts, the grace-worker and closed verdicts as shipped, then the
# grace-worker verdict with _bench_adm_closed redefined to accept 1 as well.
M1 = r'''
set -euo pipefail
source "$1/bench-lib.sh"
for v in 2 1 0 3 4 '' 2.0 02 ' 2' '2 ' -2 22 Closed -n; do
    if _bench_adm_closed "$v" 2>/dev/null; then echo "ACCEPTS [$v]"; fi
done
rc=0; bench_admission_verdict bench-validator-04 "$(bench_admission_parse < "$2")" || rc=$?; echo "RC=${rc}"
rc=0; bench_admission_verdict bench-validator-01 "$(bench_admission_parse < "$3")" || rc=$?; echo "RC=${rc}"
_bench_adm_closed(){ [ "${1:-}" = 2 ] || [ "${1:-}" = 1 ]; }
rc=0; bench_admission_verdict bench-validator-04 "$(bench_admission_parse < "$2")" || rc=$?; echo "RC=${rc}"
'''


def make_tree(root):
    """Copy the scripts into <root> (same layout as the repo); returns <root>/benchmark."""
    for rel in TREE:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    return root / "benchmark"


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def filtered(text):
    """What bench_admission_read prints for a node serving <text>: the C3 lines, then NODE_MODE."""
    lines = text.splitlines()
    return "\n".join([l for l in lines if FILTER_RE.match(l)] +
                     [l for l in lines if l.startswith("NODE_MODE=")][-1:]) + "\n"


def expected_parse(name):
    return ["%s=%s" % kv for kv in zip(PARSE_KEYS, README_TABLE[name][1:])]


def adm_lines(out):
    return [l for l in out.splitlines() if l.startswith(("ADM_OK ", "ADM_BAD "))]


def listed_after(out, line_marker, list_marker=None):
    """The whitespace-separated words after <list_marker> (default <line_marker>) on the one output
    line that carries <line_marker>."""
    lines = [l for l in out.splitlines() if line_marker in l]
    if len(lines) != 1:
        raise AssertionError("want one line with %r, found %d:\n%s" % (line_marker, len(lines), out))
    return set(lines[0].split(list_marker or line_marker, 1)[1].split())


FLEET_FAILED = "fleet not ready (step13)"


class Sandbox(unittest.TestCase):
    """One sandbox per test: a copy of the scripts, the fake gcloud, a plan, a call log, a TMPDIR."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="admission-test-")
        self.root = Path(self._tmp.name)
        self.bench = make_tree(self.root / "tree")
        self.bin = self.root / "bin"
        self.nodebin = self.root / "nodebin"
        write_exec(self.bin / "gcloud", FAKE_GCLOUD)
        write_exec(self.bin / "curl", HOST_CURL)
        write_exec(self.nodebin / "curl", NODE_CURL)
        self.state = self.root / "state"
        self.state.mkdir()
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.params = self.root / "consensus-params.yaml"
        self.params.write_text(PARAMS_YAML)
        self.plan_file = self.root / "plan.json"
        self.sleep_log = self.root / "sleeps.txt"
        self.plan({})

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, plan):
        """{inst: {"adm": [step, ...], "mode": [step, ...]}}; resets the read counts and logs."""
        self.plan_file.write_text(json.dumps(plan))
        for name in ("calls.jsonl", "counts.json"):
            if (self.state / name).exists():
                (self.state / name).unlink()
        self.sleep_log.write_text("")

    def env(self, **extra):
        # Nothing from the developer's shell that the scripts read (BENCH_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "LC_ALL": "C",
               "BENCH_RUN_ID": RUN_ID, "BENCH_APPLY": "0", "BENCH_PARAMETERS_FILE": str(self.params),
               "FAKE_STATE": str(self.state), "FAKE_PLAN": str(self.plan_file),
               "FAKE_NODEBIN": str(self.nodebin), "FAKE_FIXTURES": str(FIX),
               "SLEEP_LOG": str(self.sleep_log),
               "TN_IAP_RETRIES": "0"}   # the lib's transport retry is off: ssh attempts are counted exactly
        env.update(extra)
        return env

    def bash(self, script, *args, **env):
        # $0 = benchmark-deploy.sh: config.sh only loads for its allowlisted callers.
        return subprocess.run(["bash", "-c", script, "benchmark-deploy.sh", str(self.bench)] + [str(a) for a in args],
                              env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=300, universal_newlines=True, errors="replace")

    def calls(self):
        path = self.state / "calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def reads(self, kind):
        """{inst: how many <kind> reads the fake answered or failed}."""
        return Counter(c["inst"] for c in self.calls() if c["kind"] == kind)

    def sleeps(self):
        return self.sleep_log.read_text().split()

    def manifest(self):
        return json.loads((self.bench / "results" / RUN_ID / "manifest.json").read_text())

    def assertNoStrayCalls(self, out):
        stray = [c for c in self.calls() if c["kind"] not in ("adm", "mode") or c.get("rc") == 99]
        self.assertEqual(stray, [], out)

    def gate(self, plan):
        self.plan(plan)
        r = self.bash(GATE)
        self.assertNoStrayCalls(r.stdout)
        return r

    def fleet(self, plan, max_wait, label="step13", **env):
        self.plan(plan)
        r = self.bash(FLEET, max_wait, label, **env)
        self.assertNoStrayCalls(r.stdout)
        return r

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path


class ParseTests(Sandbox):
    def parse(self, *files):
        r = self.bash(PARSE, *files)
        self.assertEqual(r.returncode, 0, r.stdout)
        out, cur = {}, None
        for line in r.stdout.splitlines():
            if line.startswith("== "):
                cur = line[3:]
                out[cur] = []
            elif cur is not None:
                out[cur].append(line)
        return [out[str(f)] for f in files]

    def test_fixtures_parse_to_readme_table_filtered_or_not(self):
        files = []
        for name in README_TABLE:
            text = (FIX / (name + ".prom")).read_text()
            short = filtered(text)
            self.assertEqual(len(short.splitlines()) - 1, README_TABLE[name][0], name)
            files += [FIX / (name + ".prom"), self.write(name + ".filtered", short)]
        results = self.parse(*files)
        for i, name in enumerate(README_TABLE):
            with self.subTest(fixture=name):
                self.assertEqual(results[2 * i], expected_parse(name), "unfiltered " + name)
                self.assertEqual(results[2 * i + 1], expected_parse(name), "filtered " + name)

    def test_decoy_families_are_ignored(self):
        text = (FIX / "closed.prom").read_text()
        decoys = [l for l in text.splitlines() if l.startswith(DECOY_FAMILIES)]
        self.assertGreaterEqual(len(decoys), 10)
        only_decoys = self.write("decoys.prom", "\n".join(decoys + ["NODE_MODE=CvvActive"]) + "\n")
        without = self.write("closed-no-decoys.prom", "\n".join(
            l for l in text.splitlines() if not l.startswith(DECOY_FAMILIES)) + "\n")
        got_decoys, got_without = self.parse(only_decoys, without)
        self.assertEqual(got_decoys, ["mode_primary=-", "mode_worker=-", "fallback=-", "fallback_n=0",
                                      "denied_in=0", "denied_out=0", "node_mode=CvvActive"])
        self.assertEqual(got_without, expected_parse("closed"))

    def test_a_second_worker_series_is_summed_and_the_lowest_mode_wins(self):
        text = (FIX / "closed.prom").read_text().replace(
            'tn_network_admission_mode{network="worker-0"} 2',
            'tn_network_admission_mode{network="worker-0"} 2\ntn_network_admission_mode{network="worker-1"} 1'
        ).replace(
            'tn_network_closed_admission_denied_total{network="worker-0",direction="in"} 1',
            'tn_network_closed_admission_denied_total{network="worker-0",direction="in"} 1\n'
            'tn_network_closed_admission_denied_total{network="worker-1",direction="in"} 4')
        (got,) = self.parse(self.write("two-workers.prom", text))
        self.assertIn("mode_worker=1", got)
        self.assertIn("denied_in=7", got)


class VerdictTests(Sandbox):
    def verdicts(self, *pairs):
        args = [a for inst, f in pairs for a in (inst, f)]
        r = self.bash(VERDICT, *args)
        self.assertEqual(r.returncode, 0, r.stdout)
        lines = r.stdout.splitlines()
        out = []
        for i, line in enumerate(lines):
            if line.startswith("RC="):
                out.append((lines[i - 1], int(line[3:])))
        self.assertEqual(len(out), len(pairs), r.stdout)
        return out

    def test_closed_fixtures_are_adm_ok(self):
        got = self.verdicts(("bench-validator-01", FIX / "closed.prom"),
                            ("bench-validator-02", FIX / "reordered-labels-with-ts.prom"))
        self.assertEqual(got, [(OK_CLOSED % "bench-validator-01", 0), (OK_CLOSED % "bench-validator-02", 0)])

    def test_not_closed_fixtures_are_adm_bad_with_the_reason(self):
        down = self.write("node-down.prom", "NODE_MODE=-\n")
        cases = (("bench-validator-04", FIX / "grace-worker.prom", "worker mode 1 (Grace), not 2"),
                 ("bench-validator-05", FIX / "fallback-active.prom", "fallback 1 (missing), not 0"),
                 ("bench-observer-11", FIX / "missing-worker.prom", "no worker series"),
                 ("bench-validator-06", down, "no primary series"))
        got = self.verdicts(*[(inst, f) for inst, f, _ in cases])
        for (inst, _, reason), (line, rc) in zip(cases, got):
            with self.subTest(inst=inst):
                self.assertEqual(rc, 1, line)
                self.assertTrue(line.startswith("ADM_BAD %s " % inst), line)
                self.assertIn(reason, line)

    def test_grace_worker_is_not_closed(self):
        """Mutation M1's target: `_bench_adm_closed` accepts 2 and nothing else, and it is the gate."""
        r = self.bash(M1, FIX / "grace-worker.prom", FIX / "closed.prom")
        self.assertEqual(r.returncode, 0, r.stdout)
        accepted = [l for l in r.stdout.splitlines() if l.startswith("ACCEPTS ")]
        self.assertEqual(accepted, ["ACCEPTS [2]"],
                         "M1: _bench_adm_closed must accept the admission mode 2 (Closed) and nothing else\n"
                         + r.stdout)
        verdicts = [l for l in r.stdout.splitlines() if l.startswith(("ADM_", "RC="))]
        self.assertEqual(len(verdicts), 6, r.stdout)
        grace, grace_rc, closed, closed_rc, lenient, lenient_rc = verdicts
        # As shipped: Grace on the worker is the one defect, and the primary at 2 is not one.
        self.assertEqual(grace_rc, "RC=1", "M1: a worker in Grace (1) passed the admission gate\n" + r.stdout)
        self.assertTrue(grace.startswith("ADM_BAD bench-validator-04 "), grace)
        self.assertEqual(grace[len("ADM_BAD bench-validator-04 "):].split(" [", 1)[0],
                         "worker mode 1 (Grace), not 2", grace)
        self.assertEqual((closed, closed_rc), (OK_CLOSED % "bench-validator-01", "RC=0"))
        # The verdict asks _bench_adm_closed: redefine it to accept 1 and the Grace worker passes.
        self.assertEqual(lenient_rc, "RC=0", r.stdout)
        self.assertTrue(lenient.startswith("ADM_OK bench-validator-04 primary=2 worker=1 fallback=0 "), lenient)


class GateTests(Sandbox):
    def entries(self):
        adm = self.manifest()["admission"]
        self.assertEqual(sorted(e["inst"] for e in adm), sorted(NODES), "one admission entry per node")
        return {e["inst"]: e for e in adm}

    def assertBadOnly(self, r, inst, reason):
        self.assertEqual(r.returncode, 1, r.stdout)
        bad = [l for l in adm_lines(r.stdout) if l.startswith("ADM_BAD ")]
        self.assertEqual(len(bad), 1, r.stdout)
        self.assertTrue(bad[0].startswith("ADM_BAD %s " % inst), bad[0])
        self.assertIn(reason, bad[0])
        self.assertEqual(len(adm_lines(r.stdout)), len(NODES), r.stdout)
        self.assertEqual(listed_after(r.stdout, "admission is not Closed on:"), {inst})

    def test_all_closed_records_every_node(self):
        plan = {"bench-validator-07": {"adm": [{"prom": "reordered-labels-with-ts"}]},
                OBSERVER: {"adm": [{"prom": "closed", "node_mode": "Observer"}]}}
        r = self.gate(plan)
        self.assertEqual(r.returncode, 0, r.stdout)
        want = [OK_CLOSED % n for n in VALIDATORS] + [
            "ADM_OK %s primary=2 worker=2 fallback=0 denied_in=3 denied_out=1 mode=Observer" % OBSERVER]
        self.assertEqual(adm_lines(r.stdout), want)
        self.assertEqual(self.reads("adm"), Counter({n: 1 for n in NODES}))
        self.assertEqual(self.reads("mode"), Counter())
        self.assertEqual(self.sleeps(), [])
        m = self.manifest()
        self.assertEqual(len(m["admission"]), 11)
        for e in m["admission"]:
            with self.subTest(inst=e["inst"]):
                self.assertEqual(set(e), ADMISSION_KEYS)
                self.assertFalse([k for k in e if re.search(r"(^|_)(ip|ips|id|ids)$", k)])
                self.assertRegex(e["ts"], ISO_RE)
                self.assertEqual({k: e[k] for k in ADMISSION_KEYS - {"inst", "ts"}},
                                 {"mode_primary": 2, "mode_worker": 2, "fallback": 0, "denied_in": 3,
                                  "denied_out": 1,
                                  "node_mode": "Observer" if e["inst"] == OBSERVER else "CvvActive"})
        self.assertEqual(m["fleet_modes"], dict({n: "CvvActive" for n in VALIDATORS}, **{OBSERVER: "Observer"}))

    def test_grace_worker_fails_only_that_node(self):
        r = self.gate({"bench-validator-04": {"adm": [{"prom": "grace-worker"}]}})
        self.assertBadOnly(r, "bench-validator-04", "worker mode 1 (Grace), not 2")
        self.assertEqual(self.reads("adm")["bench-validator-04"], 1, "a Grace mode is not read again")
        e = self.entries()["bench-validator-04"]
        self.assertEqual((e["mode_primary"], e["mode_worker"], e["fallback"]), (2, 1, 0))

    def test_transient_fallback_is_read_again_once(self):
        r = self.gate({"bench-validator-02": {"adm": [{"prom": "fallback-active"}, {"prom": "closed"}]}})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(OK_CLOSED % "bench-validator-02", adm_lines(r.stdout))
        self.assertEqual(self.reads("adm"), Counter(dict({n: 1 for n in NODES}, **{"bench-validator-02": 2})))
        self.assertEqual(self.sleeps(), ["10"])
        self.assertEqual(self.entries()["bench-validator-02"]["fallback"], 0)

    def test_persistent_fallback_fails_after_two_reads(self):
        r = self.gate({"bench-validator-02": {"adm": [{"prom": "fallback-active"}]}})
        self.assertBadOnly(r, "bench-validator-02", "fallback 1 (missing), not 0")
        self.assertEqual(self.reads("adm")["bench-validator-02"], 2)
        self.assertEqual(self.sleeps(), ["10"])
        self.assertEqual(self.entries()["bench-validator-02"]["fallback"], 1)

    def test_ssh_failure_is_retried_once(self):
        r = self.gate({"bench-validator-05": {"adm": [{"rc": 255}, {"prom": "closed"}]}})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(OK_CLOSED % "bench-validator-05", adm_lines(r.stdout))
        self.assertEqual(self.reads("adm")["bench-validator-05"], 2)
        self.assertEqual(self.sleeps(), ["5"])

    def test_ssh_failure_twice_fails_that_node(self):
        r = self.gate({"bench-validator-05": {"adm": [{"rc": 255}]}})
        self.assertBadOnly(r, "bench-validator-05", "ssh failed")
        self.assertEqual(self.reads("adm")["bench-validator-05"], 2)
        e = self.entries()["bench-validator-05"]
        self.assertEqual({k: e[k] for k in ADMISSION_KEYS - {"inst", "ts"}},
                         {"mode_primary": None, "mode_worker": None, "fallback": None, "denied_in": 0,
                          "denied_out": 0, "node_mode": None})
        fm = self.manifest()["fleet_modes"]
        self.assertNotIn("bench-validator-05", fm)
        self.assertEqual(len(fm), 10)

    def test_rerun_replaces_entries(self):
        self.assertEqual(self.gate({}).returncode, 0)
        r = self.gate({"bench-validator-03": {"adm": [{"prom": "grace-worker"}]},
                       "bench-validator-05": {"adm": [{"prom": "closed", "node_mode": "CvvInactive"}]}})
        self.assertBadOnly(r, "bench-validator-03", "worker mode 1 (Grace), not 2")
        m = self.manifest()
        self.assertEqual(len(m["admission"]), 11, "a re-run replaces each node's entry")
        e = self.entries()
        self.assertEqual(e["bench-validator-03"]["mode_worker"], 1)
        self.assertEqual(e["bench-validator-05"]["node_mode"], "CvvInactive")
        self.assertEqual(m["fleet_modes"]["bench-validator-05"], "CvvInactive")
        self.assertEqual(len(m["fleet_modes"]), 11)


class FleetReadyTests(Sandbox):
    SETTLE = 7
    BACK = 11

    def fleet(self, plan, max_wait, label="step13", **env):
        env.setdefault("BENCH_FLEET_READY_SETTLE_SECS", str(self.SETTLE))
        env.setdefault("BENCH_NODE_BACK_SECS", str(self.BACK))
        return super().fleet(plan, max_wait, label, **env)

    def ready(self, label="step13"):
        m = self.manifest()
        fr = m["fleet_ready"]
        self.assertEqual(set(fr), FLEET_READY_KEYS)
        self.assertEqual(fr["label"], label)
        self.assertRegex(fr["ts"], ISO_RE)
        self.assertEqual(sorted(fr["modes"]), sorted(VALIDATORS), "fleet_ready.modes covers the validators only")
        return fr, m["fleet_modes"]

    def test_all_validators_active_one_pass_observer_never_read(self):
        r = self.fleet({OBSERVER: {"mode": [{"mode": "Observer"}]}}, 600)
        self.assertEqual(r.returncode, 0, r.stdout)
        fr, fm = self.ready()
        self.assertEqual((fr["ok"], fr["passes"], fr["waited_secs"]), (True, 1, 0))
        self.assertEqual(fr["modes"], {n: "CvvActive" for n in VALIDATORS})
        self.assertEqual(fm, {n: "CvvActive" for n in VALIDATORS})
        self.assertEqual(self.reads("mode"), Counter({n: 1 for n in VALIDATORS}))
        self.assertEqual(self.reads("adm"), Counter())
        self.assertEqual(self.sleeps(), [])

    def test_inactive_then_active_after_the_boundary(self):
        r = self.fleet({"bench-validator-03": {"mode": [{"mode": "CvvInactive"}, {"mode": "CvvActive"}]}}, 600)
        self.assertEqual(r.returncode, 0, r.stdout)
        fr, fm = self.ready()
        self.assertEqual((fr["ok"], fr["passes"]), (True, 2))
        self.assertIn(fr["waited_secs"], (self.SETTLE, self.SETTLE + 1), "boundary (now) + settle")
        self.assertEqual(fr["modes"]["bench-validator-03"], "CvvActive")
        self.assertEqual(self.reads("mode"), Counter({n: 2 for n in VALIDATORS}))

    def test_still_inactive_fails_listing_the_node(self):
        r = self.fleet({"bench-validator-03": {"mode": [{"mode": "CvvInactive"}]},
                        OBSERVER: {"mode": [{"mode": "Observer"}]}}, 600)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("%s after 2 pass(es), waited %ds;" % (FLEET_FAILED, sum(int(s) for s in self.sleeps())),
                      r.stdout)
        self.assertEqual(listed_after(r.stdout, FLEET_FAILED, "not CvvActive:"), {"bench-validator-03=CvvInactive"})
        fr, fm = self.ready()
        self.assertEqual((fr["ok"], fr["passes"]), (False, 2))
        self.assertEqual(fr["modes"]["bench-validator-03"], "CvvInactive")
        self.assertEqual(fm["bench-validator-03"], "CvvInactive")
        self.assertEqual(fr["waited_secs"], sum(int(s) for s in self.sleeps()), "the seconds slept between passes")
        # pass 1, pass 2, and the one read BENCH_NODE_BACK_SECS after pass 2 began.
        self.assertEqual(self.reads("mode"), Counter(dict({n: 2 for n in VALIDATORS}, **{"bench-validator-03": 3})))
        self.assertEqual(len(self.sleeps()), 2, self.sleeps())
        self.assertIn(int(self.sleeps()[0]), (self.SETTLE, self.SETTLE + 1))
        self.assertLessEqual(int(self.sleeps()[1]), self.BACK)

    def test_max_wait_zero_is_one_pass(self):
        r = self.fleet({"bench-validator-03": {"mode": [{"mode": "CvvInactive"}, {"mode": "CvvActive"}]}}, 0)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("%s after 1 pass(es), waited 0s;" % FLEET_FAILED, r.stdout)
        self.assertEqual(listed_after(r.stdout, FLEET_FAILED, "not CvvActive:"), {"bench-validator-03=CvvInactive"})
        fr, _ = self.ready()
        self.assertEqual((fr["ok"], fr["passes"], fr["waited_secs"]), (False, 1, 0))
        self.assertEqual(self.reads("mode"), Counter({n: 1 for n in VALIDATORS}))
        self.assertEqual(self.sleeps(), [])

    def test_unreadable_validator_is_null_and_not_ready(self):
        r = self.fleet({"bench-validator-08": {"mode": [{"rc": 255}]}}, 0)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(listed_after(r.stdout, FLEET_FAILED, "not CvvActive:"), {"bench-validator-08=unreadable"})
        fr, fm = self.ready()
        self.assertIsNone(fr["modes"]["bench-validator-08"])
        self.assertEqual((fr["ok"], fr["passes"], fr["waited_secs"]), (False, 1, 0), "a read retry is not a wait")
        self.assertNotIn("bench-validator-08", fm)
        self.assertEqual(self.reads("mode")["bench-validator-08"], 2, "one retry after a failed read")
        self.assertEqual(self.sleeps(), ["5"])


class ScrubTests(Sandbox):
    """report/scrub.py's scrub_manifest (the bundle's manifest scrub) keeps the C4a sections as written."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("report_scrub_for_admission", SCRUB_PY)
        cls.scrub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.scrub)

    def scrubbed(self, m):
        return self.scrub.scrub_manifest(m, self.scrub.ip_label_map(m))

    def test_synthetic_manifest_sections_survive(self):
        adm = [{"inst": n, "mode_primary": 2, "mode_worker": 2, "fallback": 0, "denied_in": 3, "denied_out": 1,
                "node_mode": "CvvActive", "ts": "2026-11-03T18:00:00Z"} for n in VALIDATORS]
        adm.append({"inst": OBSERVER, "mode_primary": None, "mode_worker": None, "fallback": None,
                    "denied_in": 0, "denied_out": 0, "node_mode": None, "ts": "2026-11-03T18:00:01Z"})
        fleet_ready = {"label": "step13", "ts": "2026-11-03T18:05:00Z", "ok": False, "waited_secs": 97,
                       "passes": 2, "modes": dict({n: "CvvActive" for n in VALIDATORS[1:]},
                                                  **{VALIDATORS[0]: None})}
        fleet_modes = {n: "CvvActive" for n in VALIDATORS[1:]}
        m = {"schema": "tn-bench-manifest/v1", "project": "some-project", "notes": ["operator note"],
             "instances": [{"name": n, "internal_ip": "192.0.2.%d" % (i + 1), "instance_id": str(i)}
                           for i, n in enumerate(NODES)],
             "admission": adm, "fleet_modes": fleet_modes, "fleet_ready": fleet_ready}
        out = self.scrubbed(m)
        self.assertNotIn("project", out)
        self.assertEqual(out["instances"], [{"name": n} for n in NODES], "the scrub did run")
        self.assertEqual(out["admission"], adm)
        self.assertEqual(out["fleet_modes"], fleet_modes)
        self.assertEqual(out["fleet_ready"], fleet_ready)

    def test_manifest_written_by_gate_and_fleet_ready_survives(self):
        self.assertEqual(self.gate({"bench-validator-04": {"adm": [{"prom": "grace-worker"}]},
                                    "bench-validator-05": {"adm": [{"rc": 255}]}}).returncode, 1)
        self.plan({"bench-validator-03": {"mode": [{"mode": "CvvInactive"}]}})
        self.assertEqual(self.bash(FLEET, 0, "step8").returncode, 1)
        m = self.manifest()
        self.assertEqual(len(m["admission"]), 11)
        out = self.scrubbed(m)
        for key in ("admission", "fleet_modes", "fleet_ready"):
            with self.subTest(key=key):
                self.assertEqual(out[key], m[key])


if __name__ == "__main__":
    unittest.main()
