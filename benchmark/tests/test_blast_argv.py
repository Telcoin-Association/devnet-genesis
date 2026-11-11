"""benchmark-blast.sh's blasts: the light-load arm (BENCH_LIGHT_LOAD), BENCH_WINDOW, the LOG_RATE check and
the bench-6 create path (bounded creates, one retry, the late-start guard, node URLs read once, late_secs).

The scripts run in a sandbox copy of the tree with a fake gcloud (it logs its argv and answers only
`auth print-access-token`) and a fake `date` (a fixed clock), so a plan-only run (no --yes) is
byte-for-byte reproducible. fixtures/blast/golden-*.txt were captured from the bench-4 driver and
startup script (main @ 8bc75e1), before the light-load arm existed: with every bench-5 knob at its
default, the plan, the gcloud argv and the rendered generator argv must still equal them, apart from
the two bench-6 changes bench6() spells out. The create path with --yes runs do_run's create section
against a fake gcloud with state (fixtures/blast/fake-gcloud-live.sh); fixtures/blast/golden-live-create.json
is what the bench-5 driver (85fb888) sent and recorded there (`--capture-bench5-create <ref>` rewrites it).
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "blast"
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/obs-lib.sh", "benchmark/recovery-lib.sh", "benchmark/benchmark-blast.sh",
        "benchmark/blaster-startup.sh")
PROJECT = "tn-" + "devnet"
SA_RE = re.compile(r"[0-9]+-compute@developer\.gserviceaccount\.com")
FAKE_NOW = 1767225600          # 2026-01-01T00:00:00Z
RUN_ID = "rtest-blast"
GS = "gs" + "://"

# gcloud: every call logged; only a token is ever handed out (no instance, no IP, no bucket).
GCLOUD = r'''#!/usr/bin/env bash
{ printf 'gcloud'; printf ' %q' "$@"; printf '\n'; } >> "$CALLS"
case "$1 $2" in "auth print-access-token") echo fake-token; exit 0 ;; esac
exit 1
'''
# date: `+%s` reads the sandbox clock (NOW_FILE); every other form is the real date.
DATE = r'''#!/usr/bin/env bash
for a in "$@"; do [ "$a" = "+%s" ] && { cat "$NOW_FILE"; exit 0; }; done
exec @DATE@ "$@"
'''


class Sandbox(object):
    """A copy of the scripts (<root>/tree, laid out like the repo), a bin dir with the fakes, a clock.
    <overrides> maps a TREE path to the file copied in its place (the golden capture's pristine copies)."""

    def __init__(self, overrides=None):
        self._tmp = tempfile.TemporaryDirectory(prefix="blast-argv-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        for rel in TREE:
            dst = self.tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str((overrides or {}).get(rel, REPO / rel)), str(dst))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, body in (("gcloud", GCLOUD), ("date", DATE.replace("@DATE@", shutil.which("date")))):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        (self.root / "tmp").mkdir()
        self.params = self.root / "params.yaml"
        self.params.write_text("max_header_delay: 500ms\nmin_header_delay: 250ms\nmax_batch_delay: 250ms\n")
        self.now = self.root / "now"
        self.now.write_text("%d\n" % FAKE_NOW)
        self.calls = self.root / "calls"

    def close(self):
        self._tmp.cleanup()

    def env(self, **extra):
        # Nothing from the developer's shell that the scripts read (BENCH_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.root / "tmp"), "CALLS": str(self.calls),
               "NOW_FILE": str(self.now), "BENCH_TXGEN_SHA": "abcdef1", "TN_IAP_RETRIES": "0",
               "BENCH_PARAMETERS_FILE": str(self.params)}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        return env

    def normalize(self, text):
        for root in sorted({str(self.root), os.path.realpath(str(self.root))}, key=len, reverse=True):
            text = text.replace(root, "<ROOT>")
        return SA_RE.sub("<SA>", text.replace(PROJECT, "<PROJECT>"))

    def blast(self, *args, **env):
        """benchmark-blast.sh <args> --run RUN_ID; (rc, stdout+stderr, gcloud calls), normalized."""
        if self.calls.exists():
            self.calls.unlink()
        p = subprocess.run(["bash", str(self.tree / "benchmark/benchmark-blast.sh")] + list(args) + ["--run", RUN_ID],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env(**env),
                           cwd=str(self.root), universal_newlines=True, timeout=300)
        calls = self.calls.read_text() if self.calls.exists() else ""
        return p.returncode, self.normalize(p.stdout), self.normalize(calls)

    def render(self, metadata, out_files=()):
        """blaster-startup.sh in DRY_RUN with <metadata> (key -> value) as the VM's attributes; <out_files>
        are already in its /out when it uploads (as if the generator had written them)."""
        md = self.root / "md"
        state = self.root / "state"
        for d in (md, state):
            if d.exists():
                shutil.rmtree(str(d))
            d.mkdir()
        for key, value in metadata.items():
            (md / key).write_text(value)
        (md / "txgen-config").write_text("[bench]\n")
        (md / "txgen-deployments").write_text("{}\n")
        (state / "out").mkdir()
        for name in out_files:
            (state / "out" / name).write_text("x\n")
        p = subprocess.run(["bash", str(self.tree / "benchmark/blaster-startup.sh")], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True, timeout=60,
                           env=self.env(DRY_RUN="1", BENCH_MD_DIR=str(md), BENCH_STATE_DIR=str(state)))
        return p.returncode, self.normalize(p.stdout)


def golden_text(rc, out, calls):
    return "rc=%d\n--- output\n%s--- gcloud\n%s" % (rc, out, calls)


# Bench 6 changes two things in a plan and nothing else (D36, D48). Every load VM create runs under a 90-s alarm
# with gcloud's own HTTP timeout at 60 s (bench 4 and 5: a 600-s alarm around gcloud's 300-s default). `run`
# reads the node IPs once, before its creates, from manifest.instances[] or else ONE instances list (the sandbox
# has no manifest), where bench 5 described one node per create, inside the create loop.
ALARM_BENCH5 = "@ARGV 600 gcloud compute instances create "
ALARM_BENCH6 = "@ARGV 90 env CLOUDSDK_CORE_HTTP_TIMEOUT=60 gcloud compute instances create "
VALIDATORS = ["bench-validator-%02d" % i for i in range(1, 11)]
NODE_LIST = ("gcloud compute instances list --project=<PROJECT> --filter=name=\\(%s\\) --format=json\n"
             % "\\ ".join(VALIDATORS))


def bench6(golden, creates, run=False):
    """<golden>, a bench-4 plan with <creates> load VM creates, as bench 6 prints it; with <run>, its ten node
    describes become the one node list, made before the token check."""
    assert golden.count(ALARM_BENCH5) == creates, golden
    text = golden.replace(ALARM_BENCH5, ALARM_BENCH6)
    if not run:
        return text
    lines = text.splitlines(True)
    nodes = [line for line in lines
             if line.startswith("gcloud compute instances describe bench-validator-") and "networkIP" in line]
    assert len(nodes) == 10, nodes
    lines = [line for line in lines if line not in nodes]
    lines.insert(lines.index("gcloud auth print-access-token\n"), NODE_LIST)
    return "".join(lines)


def create_lines(out, name=None):
    """The `+ … gcloud compute instances create <name> …` argv lines of a plan, as argv lists."""
    argvs = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("+ ") and " compute instances create " in line:
            argv = shlex.split(line[2:])
            argv = argv[argv.index("gcloud"):]
            if name is None or argv[4] == name:
                argvs.append(argv)
    return argvs


def metadata_of(argv):
    """The --metadata=^##^K=V##… pairs of a create argv, as a dict (the `##` meta-line mechanism)."""
    meta = next(a for a in argv if a.startswith("--metadata="))[len("--metadata="):]
    assert meta.startswith("^##^"), meta
    return dict(kv.split("=", 1) for kv in meta[len("^##^"):].split("##"))


def startup_metadata(argv):
    """What a load VM created with <argv> reads as attributes (NODE_URLS travels as a file)."""
    md = metadata_of(argv)
    md["NODE_URLS"] = "bench-validator-01=http://node-01.invalid:8545"
    return md


def shell_functions(path, *names):
    """The named functions of a script (a one-line function is its own line; others end at `}`)."""
    lines = Path(path).read_text().splitlines()
    out = []
    for name in names:
        start = next(i for i, line in enumerate(lines) if line.startswith(name + "() {"))
        end = start if lines[start].rstrip().endswith("}") else lines.index("}", start)
        out.extend(lines[start:end + 1])
    return "\n".join(out) + "\n"


def blast_meta(out, name="bench-blaster-01"):
    """(RUN_INDEX, SENDERS, SENDER_START, WARMUP, DURATION, COOLDOWN, WINDOW or None) per create of <name>."""
    rows = []
    for argv in create_lines(out, name):
        md = metadata_of(argv)
        rows.append((int(md["RUN_INDEX"]), int(md["SENDERS"]), int(md["SENDER_START"]), int(md["WARMUP_SECS"]),
                     int(md["DURATION_SECS"]), int(md["COOLDOWN_SECS"]), md.get("WINDOW")))
    return rows


def markers(out):
    return [line for line in out.splitlines() if line.startswith("LIGHT_LOAD_")]


def rendered_windows(sb, out):
    """The generator's --window in the rendered startup of each bench-blaster-01 the plan creates."""
    windows = []
    for argv in create_lines(out, "bench-blaster-01"):
        rc, render = sb.render(startup_metadata(argv))
        assert rc == 0, render
        found = re.findall(r" --window ([0-9]+) ", render)
        assert len(found) == 1, render
        windows.append(int(found[0]))
    return windows


LIGHT = (60, 360, 60)            # BENCH_LIGHT_{WARMUP,DURATION,COOLDOWN}_SECS defaults
PROFILE = (120, 2400, 180)       # BENCH_{WARMUP,DURATION,COOLDOWN}_SECS defaults


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.close()


class UnsetKnobTests(SandboxCase):
    """Every bench-5 knob at its default: the bench-4 plan, gcloud argv and generator argv, byte for byte."""

    def test_run_plan_and_generator_argv_equal_the_bench4_golden(self):
        rc, out, calls = self.sb.blast("run")
        self.assertEqual(golden_text(rc, out, calls), bench6((FIX / "golden-run-plan.txt").read_text(), 10, run=True))
        argvs = create_lines(out)
        self.assertEqual(len(argvs), 10)
        self.assertTrue(all("WINDOW" not in metadata_of(a) for a in argvs))
        rc, render = self.sb.render(startup_metadata(argvs[0]))
        self.assertEqual("rc=%d\n%s" % (rc, render), (FIX / "golden-startup-render.txt").read_text())
        self.assertEqual(render.count("--window"), 1)
        self.assertIn(" --window 16 ", render)

    def test_fund_plan_equals_the_bench4_golden(self):
        self.assertEqual(golden_text(*self.sb.blast("fund")), bench6((FIX / "golden-fund-plan.txt").read_text(), 1))

    def test_the_bench6_blast_knobs_at_their_defaults_keep_the_golden(self):
        # H1b: no tail scan, a load blast (the light lead never reaches it), byte for byte the golden plan and argv
        for env in ({"BENCH_TAIL_SCAN_SECS": "0"}, {"BENCH_BLAST_KIND": "load", "BENCH_LIGHT_START_DELAY_SECS": "150"}):
            with self.subTest(env=env):
                rc, out, calls = self.sb.blast("run", **env)
                self.assertEqual(golden_text(rc, out, calls),
                                 bench6((FIX / "golden-run-plan.txt").read_text(), 10, run=True))
                self.assertEqual(golden_text(*self.sb.blast("fund", **env)),
                                 bench6((FIX / "golden-fund-plan.txt").read_text(), 1))

    def test_light_load_off_is_the_single_blast_even_with_the_other_light_knobs_set(self):
        rc, out, calls = self.sb.blast("run", BENCH_LIGHT_LOAD="0", BENCH_LIGHT_LOAD_AFTER="1",
                                       BENCH_LIGHT_SENDERS="4 5 6")
        self.assertEqual(golden_text(rc, out, calls), bench6((FIX / "golden-run-plan.txt").read_text(), 10, run=True))


class WindowTests(SandboxCase):
    def test_window_reaches_the_generator_argv(self):
        rc, out, _ = self.sb.blast("run", BENCH_WINDOW="4")
        self.assertEqual(rc, 0, out)
        argvs = create_lines(out)
        self.assertEqual([metadata_of(a).get("WINDOW") for a in argvs], ["4"] * 10)
        rc, render = self.sb.render(startup_metadata(argvs[0]))
        self.assertEqual(rc, 0, render)
        self.assertEqual(render.count("--window"), 1)
        self.assertIn(" --window 4 ", render)
        # the funder has no window: its plan is the bench-4 one
        self.assertEqual(golden_text(*self.sb.blast("fund", BENCH_WINDOW="4")),
                         bench6((FIX / "golden-fund-plan.txt").read_text(), 1))

    def test_a_bad_window_fails_the_vm_before_the_generator(self):
        _, out, _ = self.sb.blast("run")
        md = startup_metadata(create_lines(out)[0])
        md["WINDOW"] = "0"
        rc, render = self.sb.render(md)
        self.assertEqual(rc, 2)
        self.assertIn("BENCH_BLAST_DONE rc=2 reason=bad-WINDOW:'0'", render)
        self.assertNotIn("docker run", render)


class LandingsTests(SandboxCase):
    def test_landings_flags_only_when_sampled(self):
        _, out, _ = self.sb.blast("run")
        rc, render = self.sb.render(startup_metadata(create_lines(out)[0]))
        self.assertEqual(rc, 0, render)
        self.assertNotIn("landings", out + render)
        rc, out, _ = self.sb.blast("run", BENCH_LANDINGS_SAMPLE="100")
        self.assertEqual(rc, 0, out)
        argvs = create_lines(out)
        self.assertEqual([metadata_of(a).get("LANDINGS_SAMPLE") for a in argvs], ["100"] * 10)
        rc, render = self.sb.render(startup_metadata(argvs[0]), out_files=("landings-bench-blaster-01.ndjson.gz",))
        self.assertEqual(rc, 0, render)
        self.assertEqual(render.count("--landings-out"), 1)
        self.assertIn(" --stdout-json chunked --landings-out /out/landings-bench-blaster-01.ndjson.gz"
                      " --landings-sample 100\n", render)
        # uploaded flat under the blasters prefix, which run and collect copy into results/<run>/blasters/
        self.assertIn("would upload <ROOT>/state/out/landings-bench-blaster-01.ndjson.gz -> " + GS
                      + "<PROJECT>-bench-rtest-blast/rtest-blast/index-0/blasters/landings-bench-blaster-01.ndjson.gz",
                      render)
        # the funder never samples landings
        self.assertEqual(golden_text(*self.sb.blast("fund", BENCH_LANDINGS_SAMPLE="100")),
                         bench6((FIX / "golden-fund-plan.txt").read_text(), 1))

    def test_a_bad_landings_sample_fails_the_vm_before_the_generator(self):
        _, out, _ = self.sb.blast("run")
        md = startup_metadata(create_lines(out)[0])
        md["LANDINGS_SAMPLE"] = "01"
        rc, render = self.sb.render(md)
        self.assertEqual(rc, 2)
        self.assertIn("BENCH_BLAST_DONE rc=2 reason=bad-LANDINGS_SAMPLE:'01'", render)
        self.assertNotIn("docker run", render)


class LightPlanTests(SandboxCase):
    """BENCH_LIGHT_LOAD=1 without --yes: the sequence's own plan, then each blast's real single-blast plan.
    The default arm: BENCH_LIGHT_SENDERS "8 16 600" at BENCH_LIGHT_WINDOWS "16 16 4", then 600 at 16."""

    def test_light_blasts_then_the_configured_profile(self):
        rc, out, _ = self.sb.blast("run", BENCH_LIGHT_LOAD="1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(blast_meta(out), [(0, 8, 0) + LIGHT + (None,), (1, 16, 100000) + LIGHT + (None,),
                                           (2, 600, 200000) + LIGHT + ("4",), (3, 600, 300000) + PROFILE + (None,)])
        self.assertEqual(rendered_windows(self.sb, out), [16, 16, 4, 16])
        self.assertEqual([m[1:3] for m in blast_meta(out, "bench-blaster-02")],
                         [(8, 8), (16, 100016), (600, 200600), (600, 300600)])
        self.assertEqual([line.strip() for line in out.splitlines() if line.startswith("    chaos: ")],
                         ["chaos: disabled (BENCH_CHAOS=0)"] * 3
                         + ["chaos: epoch-relative kill/restart times require the measured RPC snapshot"])
        self.assertEqual(out.count("lag injection: off (BENCH_LAG_INJECT=0)"), 4)
        # A plan is not a run: no LIGHT_LOAD_* marker (a log watcher reads those), one plan line per light blast,
        # each before its own blast's plan.
        self.assertEqual(markers(out), [])
        self.assertNotIn("LIGHT_LOAD_", out)
        plan = ">>> light-load arm (plan): light blast, index %d, %d senders per blaster at window %d\n"
        order = [out.index(s) for s in (plan % (0, 8, 16), ">>> run %s index 0:" % RUN_ID,
                                        plan % (1, 16, 16), ">>> run %s index 1:" % RUN_ID,
                                        plan % (2, 600, 4), ">>> run %s index 2:" % RUN_ID,
                                        "the configured profile, index 3", ">>> run %s index 3:" % RUN_ID)]
        self.assertEqual(order, sorted(order))
        self.assertEqual(out.count(">>> light-load arm (plan): light blast, "), 3)
        self.assertEqual(out.count(">>> light-load arm (BENCH_LIGHT_LOAD=1): run 4 blasts"), 1)
        self.assertIn("index 2: light, 600 senders per blaster at window 4,", out)
        self.assertNotIn("move the configured profile", out)

    def test_light_load_after_adds_the_first_entry_after_the_load(self):
        rc, out, _ = self.sb.blast("run", BENCH_LIGHT_LOAD="1", BENCH_LIGHT_LOAD_AFTER="1")
        self.assertEqual(rc, 0, out)
        self.assertEqual([m[:2] for m in blast_meta(out)], [(0, 8), (1, 16), (2, 600), (3, 600), (4, 8)])
        self.assertEqual(blast_meta(out)[4][2:], (400000,) + LIGHT + (None,))
        self.assertEqual(markers(out), [])
        after = ">>> light-load arm (plan): light blast, index 4, 8 senders per blaster at window 16\n"
        self.assertLess(out.index(">>> run %s index 3:" % RUN_ID), out.index(after))
        self.assertLess(out.index(">>> run %s index 4:" % RUN_ID), out.index("move the configured profile (index 3) back"))

    def test_base_index_and_windows_carry_into_every_blast(self):
        rc, out, _ = self.sb.blast("run", BENCH_LIGHT_LOAD="1", BENCH_RUN_INDEX="5", BENCH_LIGHT_SENDERS="3",
                                   BENCH_LIGHT_WINDOWS="5", BENCH_WINDOW="8")
        self.assertEqual(rc, 0, out)
        self.assertEqual(blast_meta(out), [(5, 3, 500000) + LIGHT + ("5",), (6, 600, 600000) + PROFILE + ("8",)])
        self.assertEqual(rendered_windows(self.sb, out), [5, 8])

    def test_fund_funds_every_index_the_configured_profile_last(self):
        rc, out, _ = self.sb.blast("fund", BENCH_LIGHT_LOAD="1", BENCH_LIGHT_LOAD_AFTER="1")
        self.assertEqual(rc, 0, out)
        funds = [metadata_of(a) for a in create_lines(out, "bench-funder")]
        self.assertEqual([(m["RUN_INDEX"], m["SENDERS"], m["SENDER_START"]) for m in funds],
                         [("0", "80", "0"), ("1", "160", "100000"), ("2", "6000", "200000"), ("4", "80", "400000"),
                          ("3", "6000", "300000")])
        self.assertTrue(all("WINDOW" not in m for m in funds))
        self.assertEqual(markers(out), [])

    def test_keep_is_refused(self):
        rc, out, _ = self.sb.blast("run", "--keep", BENCH_LIGHT_LOAD="1")
        self.assertEqual(rc, 1)
        self.assertIn("--keep cannot be used with BENCH_LIGHT_LOAD=1", out)
        self.assertNotIn("compute instances create", out)


# The sequence with --yes, its single-blast children stubbed: a stub child archives the blast in place as
# a real `run` does (archive_blast_outputs), then writes its own outputs and .blast; FAIL_AT=<index>
# makes that child (run or fund) end FAIL_RC.
SEQ_FUNCTIONS = ("light_plan", "light_env", "light_show_plan", "light_check_indices", "arm_in_force", "light_record",
                 "light_stop", "light_swap_back", "light_fund", "light_run", "blaster_name", "prev_blast_index",
                 "prev_blast_recorded", "blast_indices_used", "prev_blast_items", "blast_items_in", "archive_blast_outputs")
SEQ_PREAMBLE = r'''
set -euo pipefail
BENCH_RESULTS_DIR="$WORK/results"; mkdir -p "$BENCH_RESULTS_DIR"
BENCH_APPLY=1; CONFIRM=1; BENCH_RUN_ID=rtest; BLAST_LOG=""; DIR=/unused
BENCH_RUN_INDEX="${BASE:-0}"; BENCH_LIGHT_SENDERS="${SENDERS:-8 16}"; BENCH_LIGHT_WINDOWS="${WINDOWS:-}"
BENCH_LIGHT_LOAD_AFTER="${AFTER:-0}"; BENCH_SENDERS=600
BENCH_WARMUP_SECS=120; BENCH_DURATION_SECS=2400; BENCH_COOLDOWN_SECS=180
BENCH_LIGHT_WARMUP_SECS=60; BENCH_LIGHT_DURATION_SECS=360; BENCH_LIGHT_COOLDOWN_SECS=60
BENCH_CHAOS=1; BENCH_LAG_INJECT=0; BENCH_WINDOW=16
bench_now_iso() { local n; n=$(( $(cat "$WORK/clock" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$WORK/clock"; printf '2026-01-01T00:%02d:00Z' "$n"; }
light_child() {
    local action="$1" p="$2" idx
    shift 2
    idx="${LIGHT_IDX[$p]}"
    echo "CHILD ${action} $(light_env "${p}")${*:+ $*}" >> "$WORK/children"
    if [ "${action}" = run ]; then
        archive_blast_outputs > /dev/null
        mkdir -p "$BENCH_RESULTS_DIR/blasters" "$BENCH_RESULTS_DIR/logs"
        echo "index ${idx}" > "$BENCH_RESULTS_DIR/blasters/bench-blaster-01.json"
        echo "index ${idx}" > "$BENCH_RESULTS_DIR/logs/blast-run-${idx}.log"
        bench_manifest_jq --argjson i "${idx}" '.blast = {run_index: $i} | .blasters = [{name: "bench-blaster-01"}]'
    fi
    [ "${idx}" != "${FAIL_AT:-none}" ] || return "${FAIL_RC:-1}"
}
'''


class SequenceTests(unittest.TestCase):
    LIB = shell_functions(BENCH / "bench-lib.sh", "bench_die", "bench_warn", "bench_manifest", "bench_manifest_jq",
                          "bench_manifest_note")
    FLOOR_NOTE = ("   A light blast run by hand is not in blasts[], so the floor KPIs miss it: pass its "
                  "blast-<index>-<UTC>/ as --floor-blast-dir to report/make_bundle.py and report/kpis.py.\n")

    def sequence(self, action, manifest=None, extra="", **env):
        """light_<action> with --yes; (rc, stdout, stderr, children, results dir listing, live manifest)."""
        with tempfile.TemporaryDirectory(prefix="blast-seq-") as directory:
            work = Path(directory)
            results = work / "results"
            results.mkdir()
            (results / "manifest.json").write_text(json.dumps(manifest or {"notes": [], "timestamps": {}}))
            code = SEQ_PREAMBLE + self.LIB + shell_functions(BENCH / "benchmark-blast.sh", *SEQ_FUNCTIONS) \
                + extra + "light_%s\n" % action
            p = subprocess.run(["bash", "-c", code], env=dict(os.environ, WORK=str(work), **env),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
            children = (work / "children").read_text().splitlines() if (work / "children").exists() else []
            tree = {}
            for f in sorted(results.rglob("*")):
                if f.is_file() and f.name != "manifest.json":
                    tree[re.sub(r"-[0-9]{8}T[0-9]{6}Z", "-<UTC>", str(f.relative_to(results)))] = f.read_text()
            archived = {re.sub(r"-[0-9]{8}T[0-9]{6}Z", "-<UTC>", d.name): json.loads((d / "manifest.json").read_text())
                        for d in results.glob("blast-*") if (d / "manifest.json").exists()}
            return dict(rc=p.returncode, out=p.stdout, err=p.stderr, children=children, tree=tree, archived=archived,
                        manifest=json.loads((results / "manifest.json").read_text()))

    def test_markers_children_and_blasts_in_order(self):
        run = self.sequence("run")
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertEqual(markers(run["out"]), ["LIGHT_LOAD_START i=0 senders=8 window=16", "LIGHT_LOAD_DONE i=0 rc=0",
                                               "LIGHT_LOAD_START i=1 senders=16 window=16", "LIGHT_LOAD_DONE i=1 rc=0"])
        light = (" BENCH_WINDOW=16 BENCH_WARMUP_SECS=60 BENCH_DURATION_SECS=360 BENCH_COOLDOWN_SECS=60 BENCH_CHAOS=0"
                 " BENCH_LAG_INJECT=0 BENCH_BLAST_KIND=light")
        self.assertEqual(run["children"], [
            "CHILD run BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=0 BENCH_SENDERS=8" + light + " BENCH_LOG_RATE_CHECK=1",
            "CHILD run BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=1 BENCH_SENDERS=16" + light + " BENCH_LOG_RATE_CHECK=1",
            "CHILD run BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=2 BENCH_LOG_RATE_CHECK=1"])
        blasts = run["manifest"]["blasts"]
        self.assertEqual([(b["index"], b["senders"], b["window"], b["chaos"], b["rc"]) for b in blasts],
                         [(0, 8, 16, 0, 0), (1, 16, 16, 0, 0), (2, 600, 16, 1, 0)])
        # bench 5's keys, then D45's kind and arm (null: the manifest has no param_arms)
        self.assertEqual(list(blasts[0]), ["index", "senders", "window", "chaos", "started", "ended", "rc", "kind", "arm"])
        self.assertEqual([(b["kind"], b["arm"]) for b in blasts], [("light", None), ("light", None), ("load", None)])
        stamps = [t for b in blasts for t in (b["started"], b["ended"])]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(len(set(stamps)), 6)
        # every light blast archived; the configured profile current
        self.assertEqual(run["tree"]["blasters/bench-blaster-01.json"], "index 2\n")
        self.assertEqual(run["tree"]["blast-0-<UTC>/blasters/bench-blaster-01.json"], "index 0\n")
        self.assertEqual(run["tree"]["blast-1-<UTC>/logs/blast-run-1.log"], "index 1\n")
        self.assertEqual(run["manifest"]["blast"], {"run_index": 2})
        self.assertIn("light-load arm complete: indices 0 1 2;", run["out"])

    def test_after_light_blast_is_archived_and_the_configured_profile_moved_back(self):
        run = self.sequence("run", AFTER="1")
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertEqual(markers(run["out"])[-2:], ["LIGHT_LOAD_START i=3 senders=8 window=16", "LIGHT_LOAD_DONE i=3 rc=0"])
        self.assertEqual(run["tree"], {
            "blasters/bench-blaster-01.json": "index 2\n", "logs/blast-run-2.log": "index 2\n",
            "blast-0-<UTC>/blasters/bench-blaster-01.json": "index 0\n", "blast-0-<UTC>/logs/blast-run-0.log": "index 0\n",
            "blast-1-<UTC>/blasters/bench-blaster-01.json": "index 1\n", "blast-1-<UTC>/logs/blast-run-1.log": "index 1\n",
            "blast-3-<UTC>/blasters/bench-blaster-01.json": "index 3\n", "blast-3-<UTC>/logs/blast-run-3.log": "index 3\n"})
        m = run["manifest"]
        self.assertEqual((m["blast"], m["blasters"]), ({"run_index": 2}, [{"name": "bench-blaster-01"}]))
        self.assertEqual([(b["index"], b["senders"], b["chaos"]) for b in m["blasts"]],
                         [(0, 8, 0), (1, 16, 0), (2, 600, 1), (3, 8, 0)])
        self.assertTrue(any("moved back from blast-2-" in n for n in m["notes"]), m["notes"])
        self.assertTrue(any("blast index 3 archived" in n for n in m["notes"]), m["notes"])
        self.assertEqual(sorted(run["archived"]), ["blast-0-<UTC>", "blast-1-<UTC>", "blast-3-<UTC>"])
        self.assertEqual(run["archived"]["blast-3-<UTC>"]["blast"], {"run_index": 3})
        self.assertEqual(len(run["archived"]["blast-3-<UTC>"]["blasts"]), 4)

    def test_swap_back_says_what_to_do_when_its_temporary_file_cannot_be_made(self):
        # The configured profile's outputs are back in place; its manifest copy is not live yet.
        fail = 'mktemp() { [ "${FUNCNAME[1]}" != light_swap_back ] || return 1; command mktemp "$@"; }\n'
        run = self.sequence("run", AFTER="1", extra=fail)
        self.assertEqual(run["rc"], 1, run["err"])
        self.assertIn("❌ light-load arm: index 2's outputs are back in ", run["err"])
        self.assertIn(" but no temporary file could be made next to ", run["err"])
        self.assertRegex(run["err"], r"its manifest copy \S+/blast-2-[0-9]{8}T[0-9]{6}Z/manifest\.json is not live yet: "
                                     r"put it in place of \S+/manifest\.json by hand")
        self.assertEqual(run["tree"]["blasters/bench-blaster-01.json"], "index 2\n")
        self.assertEqual(run["archived"]["blast-2-<UTC>"]["blast"], {"run_index": 2})
        self.assertEqual(run["archived"]["blast-3-<UTC>"]["blast"], {"run_index": 3})
        self.assertNotIn("blast", run["manifest"])   # the live manifest is the reset one the archive left
        self.assertNotIn("light-load arm complete", run["out"])

    def test_a_failed_light_blast_stops_the_sequence(self):
        run = self.sequence("run", FAIL_AT="1", FAIL_RC="3")
        self.assertEqual(run["rc"], 3)
        self.assertEqual([c.split()[3] for c in run["children"]], ["BENCH_RUN_INDEX=0", "BENCH_RUN_INDEX=1"])
        self.assertEqual(markers(run["out"])[-1], "LIGHT_LOAD_DONE i=1 rc=3")
        self.assertEqual([(b["index"], b["rc"]) for b in run["manifest"]["blasts"]], [(0, 0), (1, 3)])
        self.assertNotIn("light-load arm complete", run["out"])
        self.assertIn("run of index 1 (light, 16 senders per blaster at window 16) ended rc=3", run["err"])
        # D38: the whole sequence the arm still owes, in order: the failed light blast funded and run under a
        # fresh index, the load, each run measuring LOG_RATE as the sequence's children do, then deploy step 15.
        resume = [line.strip() for line in run["err"].splitlines() if "benchmark/benchmark-" in line]
        light = ("BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=3 BENCH_SENDERS=16 BENCH_WINDOW=16 BENCH_WARMUP_SECS=60 BENCH_DURATION_SECS=360 "
                 "BENCH_COOLDOWN_SECS=60 BENCH_CHAOS=0 BENCH_LAG_INJECT=0 BENCH_BLAST_KIND=light ")
        self.assertEqual(resume, [
            light + "benchmark/benchmark-blast.sh fund --yes --run rtest",
            light + "BENCH_LOG_RATE_CHECK=1 benchmark/benchmark-blast.sh run --yes --run rtest",
            "BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=2 BENCH_LOG_RATE_CHECK=1 benchmark/benchmark-blast.sh run --yes --run rtest",
            "benchmark/benchmark-deploy.sh --yes --from 15 --to 15 --run rtest"])
        self.assertIn("   Resume by hand, one command at a time, each once the one before it succeeded (the last is the "
                      "collect, deploy step 15):\n", run["err"])
        self.assertEqual(run["err"].count(self.FLOOR_NOTE), 1)

    def test_the_default_arm_pairs_each_light_entry_with_its_window(self):
        run = self.sequence("run", SENDERS="8 16 600", WINDOWS="16 16 4")
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertEqual([(b["index"], b["senders"], b["window"], b["chaos"]) for b in run["manifest"]["blasts"]],
                         [(0, 8, 16, 0), (1, 16, 16, 0), (2, 600, 4, 0), (3, 600, 16, 1)])
        self.assertEqual([m for m in markers(run["out"]) if "START" in m],
                         ["LIGHT_LOAD_START i=0 senders=8 window=16", "LIGHT_LOAD_START i=1 senders=16 window=16",
                          "LIGHT_LOAD_START i=2 senders=600 window=4"])
        self.assertIn("BENCH_RUN_INDEX=2 BENCH_SENDERS=600 BENCH_WINDOW=4 BENCH_WARMUP_SECS=60", run["children"][2])
        self.assertTrue(run["children"][2].endswith("BENCH_CHAOS=0 BENCH_LAG_INJECT=0 BENCH_BLAST_KIND=light "
                                                    "BENCH_LOG_RATE_CHECK=1"))
        self.assertEqual(run["children"][3], "CHILD run BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=3 BENCH_LOG_RATE_CHECK=1")

    def test_a_failed_configured_blast_stops_before_the_light_blast_after_it(self):
        run = self.sequence("run", AFTER="1", FAIL_AT="2")
        self.assertEqual(run["rc"], 1)
        self.assertEqual(len(run["children"]), 3)
        self.assertEqual(markers(run["out"])[-1], "LIGHT_LOAD_DONE i=1 rc=0")
        self.assertEqual(run["manifest"]["blasts"][-1]["rc"], 1)
        self.assertIn("configured profile's outputs are then in its blast-<index>-<UTC>/", run["err"])
        self.assertIn("BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=4 benchmark/benchmark-blast.sh fund --yes", run["err"])
        self.assertIn(self.FLOOR_NOTE, run["err"])            # the light blast after the load is left
        # Only the configured profile left: no light blast to point the floor KPIs at.
        run = self.sequence("run", FAIL_AT="2")
        self.assertEqual(run["rc"], 1)
        self.assertIn("BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=3 BENCH_LOG_RATE_CHECK=1 benchmark/benchmark-blast.sh run --yes",
                      run["err"])
        self.assertTrue(run["err"].endswith("     benchmark/benchmark-deploy.sh --yes --from 15 --to 15 --run rtest\n"
                                            "   blasts[] records this sequence's blasts only; a blast run by hand is "
                                            "recorded in its own manifest .blast and in blast_runs[].\n"), run["err"])
        self.assertNotIn(self.FLOOR_NOTE, run["err"])

    def test_fund_order_and_a_failed_fund(self):
        run = self.sequence("fund", AFTER="1")
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertEqual([c.split()[3] for c in run["children"]],
                         ["BENCH_RUN_INDEX=0", "BENCH_RUN_INDEX=1", "BENCH_RUN_INDEX=3", "BENCH_RUN_INDEX=2"])
        self.assertTrue(all(c.startswith("CHILD fund ") for c in run["children"]))
        self.assertNotIn("blasts", run["manifest"])
        run = self.sequence("fund", AFTER="1", FAIL_AT="3")
        self.assertEqual(run["rc"], 1)
        resume = [line.strip() for line in run["err"].splitlines() if "benchmark/benchmark-" in line]
        self.assertEqual([r.split(" benchmark/")[0].split()[1] for r in resume[:2]],
                         ["BENCH_RUN_INDEX=3", "BENCH_RUN_INDEX=2"])
        # the sequence's own run gives every child BENCH_LOG_RATE_CHECK=1; then deploy step 15 (D38)
        self.assertEqual(resume[2:], ["BENCH_LIGHT_LOAD=1 BENCH_RUN_INDEX=0 benchmark/benchmark-blast.sh run --yes --run rtest",
                                      "benchmark/benchmark-deploy.sh --yes --from 15 --to 15 --run rtest"])

    def test_an_index_an_earlier_blast_used_is_refused_before_anything_runs(self):
        run = self.sequence("run", manifest={"notes": [], "blast": {"run_index": 1}, "blasters": [{"name": "x"}]})
        self.assertEqual(run["rc"], 1)
        self.assertEqual(run["children"], [])
        self.assertIn("used BENCH_RUN_INDEX=1 (the sequence is 0 1 2)", run["err"])
        self.assertIn("BENCH_RUN_INDEX=3", run["err"])
        run = self.sequence("run", BASE="4", manifest={"notes": [], "blast": {"run_index": 1}, "blasters": [{"name": "x"}]})
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertEqual([b["index"] for b in run["manifest"]["blasts"]], [4, 5, 6])


LOG_RATE_FUNCTIONS = ("log_rate_cmd", "log_rate_sample", "log_rate_mb_per_min", "log_rate_check", "sleep_until")
LOG_RATE_PREAMBLE = r'''
set -euo pipefail
INSTANCE_NAMES=(bench-validator-01 bench-validator-02); ZONES=(zone-a zone-b)
BENCH_RESULTS_DIR="$WORK"; BENCH_LOG_RATE_WARN_MB_MIN="${WARN_AT:-30}"; BENCH_RUN_INDEX="${RUN_INDEX:-0}"
BENCH_NODE_UNIT_LOGS="${UNIT_LOGS:-stdout:/var/log/telcoin/telcoin.log stderr:/var/log/telcoin/telcoin-error.log}"
bench_log() { printf 'LOG %s\n' "$*"; }
bench_now_unix() { cat "$WORK/clock"; }
'''
# One answer per session, in order: "rc=<n>" fails the session with <n>, anything else is its stdout.
STUB_SSH = r'''
sleep() { echo "SLEEP $*" >> "$WORK/sessions"; }
tn_iap_ssh() {
    local n a
    echo "SESSION $1 $2 $3" >> "$WORK/sessions"
    n=$(grep -c '^SESSION ' "$WORK/sessions")
    a=$(sed -n "${n}p" "$WORK/answers")
    case "$a" in rc=*) return "${a#rc=}" ;; esac
    printf '%s\r\n' "$a"
}
'''


class LogRateTests(unittest.TestCase):
    LIB = shell_functions(BENCH / "bench-lib.sh", "bench_warn", "bench_manifest", "bench_manifest_jq")

    def check(self, answers, stubs=STUB_SSH, extra="", manifest=None, **env):
        """log_rate_check 0 <now>; (stdout, stderr, sessions log, manifest .log_rate)."""
        with tempfile.TemporaryDirectory(prefix="blast-lograte-") as directory:
            work = Path(directory)
            (work / "manifest.json").write_text(json.dumps(manifest or {"notes": []}))
            (work / "answers").write_text("".join(a + "\n" for a in answers))
            (work / "clock").write_text("1000\n")
            code = LOG_RATE_PREAMBLE + self.LIB + shell_functions(BENCH / "benchmark-blast.sh", *LOG_RATE_FUNCTIONS) \
                + stubs + extra + 'log_rate_check 0 "$(cat "$WORK/clock")"\necho "RC $?"\n'
            p = subprocess.run(["bash", "-c", code], env=dict(os.environ, WORK=str(work), **env),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            sessions = (work / "sessions").read_text() if (work / "sessions").exists() else ""
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("RC 0", p.stdout)
            return p.stdout, p.stderr, sessions, json.loads((work / "manifest.json").read_text()).get("log_rate")

    def rate_line(self, out):
        return next(line for line in out.splitlines() if line.startswith("LOG_RATE "))

    def test_rate_at_the_threshold_is_not_a_warning(self):
        out, err, sessions, rec = self.check(["LOG_BYTES 1000000 100", "LOG_BYTES 31000000 160"])
        self.assertEqual(self.rate_line(out), "LOG_RATE bench-validator-01 blast=0 mb_per_min=30.0")
        self.assertNotIn("⚠", out + err)
        self.assertEqual(rec, [{"blast": 0, "inst": "bench-validator-01", "mb_per_min": 30.0, "warn": False}])
        lines = sessions.splitlines()
        self.assertEqual([l.split()[0] for l in lines], ["SESSION", "SLEEP", "SESSION"])
        self.assertEqual(lines[1], "SLEEP 60")
        self.assertIn("SESSION bench-validator-01 zone-a sudo sh -c 't=0; for g in /var/log/telcoin/telcoin.log "
                      "/var/log/telcoin/telcoin.log.[0-9]*; do", lines[0])

    def test_rate_above_the_threshold_warns_and_never_stops(self):
        out, _, _, rec = self.check(["LOG_BYTES 2000000 100", "LOG_BYTES 6500000 165"], WARN_AT="3")
        self.assertEqual(self.rate_line(out), "LOG_RATE bench-validator-01 blast=0 mb_per_min=4.2 ⚠ above "
                         "BENCH_LOG_RATE_WARN_MB_MIN=3: check the node log filter before the teardown pull (the run continues)")
        self.assertEqual(rec, [{"blast": 0, "inst": "bench-validator-01", "mb_per_min": 4.2, "warn": True}])
        out, _, _, rec = self.check(["LOG_BYTES 0 100", "LOG_BYTES 1170000000 160"], RUN_INDEX="3")
        self.assertTrue(self.rate_line(out).startswith("LOG_RATE bench-validator-01 blast=3 mb_per_min=1170.0 ⚠ above "
                                                       "BENCH_LOG_RATE_WARN_MB_MIN=30"))
        self.assertTrue(rec[0]["warn"])

    def test_each_blast_appends_its_own_entry(self):
        # The sequence's blasts measure one after the other on one live manifest (an archive keeps .log_rate):
        # each appends {blast, inst, mb_per_min, warn}; an older single-object record becomes the list's first.
        first = {"blast": 0, "inst": "bench-validator-01", "mb_per_min": 1.5, "warn": False}
        out, _, _, rec = self.check(["LOG_BYTES 0 100", "LOG_BYTES 40000000 160"], RUN_INDEX="3",
                                    manifest={"notes": [], "log_rate": [first]})
        self.assertEqual(self.rate_line(out), "LOG_RATE bench-validator-01 blast=3 mb_per_min=40.0 ⚠ above "
                         "BENCH_LOG_RATE_WARN_MB_MIN=30: check the node log filter before the teardown pull (the run continues)")
        self.assertEqual(rec, [first, {"blast": 3, "inst": "bench-validator-01", "mb_per_min": 40.0, "warn": True}])
        old = {"inst": "bench-validator-01", "mb_per_min": 2.0, "warn": False}
        _, _, _, rec = self.check(["LOG_BYTES 1000 100", "rc=255"], RUN_INDEX="1", manifest={"notes": [], "log_rate": old})
        self.assertEqual(rec, [old, {"blast": 1, "inst": "bench-validator-01", "mb_per_min": None, "warn": False}])

    def test_unmeasured_rate_is_a_question_mark_and_null(self):
        for answers in (["LOG_BYTES 1000 100", "rc=255"], ["rc=1", "LOG_BYTES 1000 160"],
                        ["LOG_BYTES 90000000 100", "LOG_BYTES 1000 160"],      # rotated in between: the total shrank
                        ["LOG_BYTES 1000 100", "LOG_BYTES 9000 100"],          # no time passed on the node
                        ["garbage", "LOG_BYTES 9000 160"]):
            with self.subTest(answers=answers):
                out, err, sessions, rec = self.check(answers)
                self.assertEqual(self.rate_line(out), "LOG_RATE bench-validator-01 blast=0 mb_per_min=?")
                self.assertIn("LOG_RATE bench-validator-01: not measured", err)
                self.assertEqual(rec, [{"blast": 0, "inst": "bench-validator-01", "mb_per_min": None, "warn": False}])
                self.assertEqual(sessions.count("SESSION "), 2)

    # The real devnet-lib wrapper and a fake gcloud that runs the session's command here, as the node would
    # (sudo is a pass-through, the node clock is $WORK/clock); `sleep` lets 60 s pass and the log grow 3 MB.
    GCLOUD = r'''#!/usr/bin/env bash
cmd=""; for a in "$@"; do case "$a" in --command=*) cmd="${a#--command=}" ;; esac; done
echo "SESSION $*" >> "$WORK/sessions"
exec bash -c "$cmd"
'''
    REAL = r'''
PROJECT_ID=bench-test; TN_SSH_TRANSPORT=iap; CONFIG_FILE=/dev/null
source "@LIB@"
TN_IAP_RETRIES=2; TN_IAP_RETRY_SECS=0
sleep() { echo "$(( $(cat "$WORK/clock") + $1 ))" > "$WORK/clock"; head -c 3000000 /dev/zero >> "$WORK/node/telcoin.log"; }
echo "SAMPLE $(log_rate_sample 0)"
'''

    def test_one_session_per_sample_through_the_lib_wrapper_with_rotated_siblings(self):
        with tempfile.TemporaryDirectory(prefix="blast-lograte-bin-") as bindir:
            bindir = Path(bindir)
            for name, body in (("gcloud", self.GCLOUD), ("sudo", '#!/usr/bin/env bash\nexec "$@"\n'),
                               ("date", DATE.replace("@DATE@", shutil.which("date")))):
                (bindir / name).write_text(body)
                (bindir / name).chmod(0o755)
            setup = r'''
mkdir -p "$WORK/node"
head -c 5000 /dev/zero > "$WORK/node/telcoin.log"
head -c 700 /dev/zero > "$WORK/node/telcoin.log.1"
head -c 60 /dev/zero > "$WORK/node/telcoin.log.2.gz"
'''
            extra = setup + self.REAL.replace("@LIB@", str(REPO / "devnet-lib.sh"))
            work_unit_logs = "stdout:@WORK@/node/telcoin.log stderr:@WORK@/node/telcoin-error.log"
            with tempfile.TemporaryDirectory(prefix="blast-lograte-") as directory:
                work = Path(directory)
                (work / "manifest.json").write_text(json.dumps({"notes": []}))
                (work / "clock").write_text("1000\n")
                code = LOG_RATE_PREAMBLE + self.LIB + shell_functions(BENCH / "benchmark-blast.sh", *LOG_RATE_FUNCTIONS) \
                    + extra + 'log_rate_check 0 "$(cat "$WORK/clock")"\n'
                env = dict(os.environ, WORK=str(work), NOW_FILE=str(work / "clock"),
                           UNIT_LOGS=work_unit_logs.replace("@WORK@", str(work)),
                           PATH=str(bindir) + os.pathsep + os.environ["PATH"])
                p = subprocess.run(["bash", "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True, timeout=60)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("SAMPLE 5760 1000", p.stdout)          # the unit log and both rotated siblings
                self.assertIn("LOG_RATE bench-validator-01 blast=0 mb_per_min=3.0\n", p.stdout)
                sessions = (work / "sessions").read_text().splitlines()
                self.assertEqual(len(sessions), 3)                    # the SAMPLE above, then one per sample
                self.assertTrue(all("compute ssh bench-validator-01 --zone=zone-a" in s for s in sessions))
                self.assertEqual(json.loads((work / "manifest.json").read_text())["log_rate"],
                                 [{"blast": 0, "inst": "bench-validator-01", "mb_per_min": 3.0, "warn": False}])

    def test_do_run_measures_only_when_the_sequence_asks_before_the_watch_loop(self):
        source = (BENCH / "benchmark-blast.sh").read_text()
        body = source[source.index("\ndo_run() {"):source.index("\n# ================================ collect")]
        call = '    [ "${BENCH_LOG_RATE_CHECK:-0}" != 1 ] || log_rate_check 0 "$(( start_at + BENCH_PREAMBLE_SECS ))"\n'
        self.assertEqual(body.count("|| log_rate_check"), 1)
        self.assertLess(body.index("'.blasters = $b'"), body.index(call))
        self.assertLess(body.index(call), body.index("# --- watch loop"))
        # set by light_run for every blast, and printed on every run line of light_stop's resume (D38); nowhere else
        code = [line.strip() for line in source.splitlines()
                if "BENCH_LOG_RATE_CHECK=1" in line and not line.lstrip().startswith("#")]
        self.assertEqual(code, ['for q in "$@"; do echo "     $(light_env "${q}") BENCH_LOG_RATE_CHECK=1 ${cmd} run --yes '
                                '--run ${BENCH_RUN_ID}" >&2; done',
                                'light_child run "${p}" BENCH_LOG_RATE_CHECK=1 || rc=$?'])


# ---- bench6 create path (H1a: D36, D37, D39, D48) ----
# do_run's create section with --yes: its functions come from the sandbox's benchmark-blast.sh and run against
# fixtures/blast/fake-gcloud-live.sh. The manifest holds manifest.instances[] as deploy step 2 records it (node k at
# 192.0.2.<k+1>) unless a test drops nodes from it. The clock stands at FAKE_NOW, so start_at is FAKE_NOW + 300 and
# the late-start limit FAKE_NOW + 270 (2026-01-01T00:04:30Z).
BLASTERS = ["bench-blaster-%02d" % i for i in range(1, 11)]
LIVE_FNS = ("blaster_name", "node_url", "resolve_node_urls", "is_stockout", "create_vm", "blasters_json", "blaster_created",
            "assert_load_vm", "assert_load_vms", "delete_vms", "delete_vm_bg", "delete_state", "await_deletes", "marker_rc",
            "marker_reason", "settle_load_vm", "bucket_prefix", "copy_prefix", "record_abort", "try_up_to", "stop_blasters",
            "poll_blasters", "bucket_done_check", "done_wait_extra_secs", "settle_blasters", "exit_relay", "exit_step",
            "delete_unstarted_blasters", "wait_blasters_done", "on_run_exit", "start_delay_secs", "create_errors",
            "create_error_detail", "create_blasters", "record_late_secs", "record_real_phases", "prev_attempt_unsent",
            "blast_run_end")
LIVE_TOP = re.compile(r"^(NODE_IP|CREATE_[A-Z_]+|ABORT_REASON|UNSTARTED_DELETED|RELABEL_WAIT_SECS|DELETE_[A-Z_]+"
                      r"|BUCKET_[A-Z_]+|UNLANDED_LOOKUP_SECS|BLAST_RUN_[A-Z_]+)=")
LIVE_PREAMBLE = r"""
set -euo pipefail
source "$TREE/benchmark/bench-lib.sh"
source "$WORK/functions.sh"
BENCH_APPLY=1; KEEP=0; BLAST_LOG=""; ACTION=run
STARTUP="$TREE/benchmark/blaster-startup.sh"; DEPLOYMENTS_FILE="$WORK/deployments.json"; BENCH_TXGEN_CONFIG="$WORK/config.toml"
VAL_COUNT=0; for r in "${NODE_ROLES[@]}"; do [ "$r" = validator ] && VAL_COUNT=$((VAL_COUNT + 1)); done
ABORTED=""; RUN_CREATED=0; RUN_FINISHED=0; RUN_STOPPED=0; RUN_START_AT=0; DONE_LINE=()
RUN_DID_KILL=0; RUN_DID_BACK=0; RUN_DID_OBS=0; RUN_DID_PAUSE=0; RUN_DID_UNPAUSE=0
mkdir -p "$BENCH_RESULTS_DIR/logs" "$BENCH_RESULTS_DIR/meta"
[ -f "$(bench_manifest)" ] || echo '{"notes": [], "timestamps": {}, "instances": [], "blasters": [], "chaos": [], "abort": null, "phases": []}' > "$(bench_manifest)"
for k in "${!INSTANCE_NAMES[@]}"; do
    echo "192.0.2.$((k + 1))" > "$STUB/ip-${INSTANCE_NAMES[$k]}"
    case " ${DROP_INSTANCES:-} " in *" ${INSTANCE_NAMES[$k]} "*) continue ;; esac
    bench_manifest_jq --arg n "${INSTANCE_NAMES[$k]}" --arg z "${ZONES[$k]}" --arg ip "192.0.2.$((k + 1))" \
        '.instances += [{name: $n, zone: $z, internal_ip: $ip}]'
done
"""
# do_run from the node URLs to manifest blasters[] (benchmark-blast.sh, bench 6).
NEW_GLUE = r"""
start_at=$(( $(bench_now_unix) + $(start_delay_secs) ))
RUN_START_AT="${start_at}"
resolve_node_urls
gcloud auth print-access-token >/dev/null
RUN_CREATED=1
trap on_run_exit EXIT
create_blasters "${start_at}"
assert_load_vms
bench_manifest_jq --argjson b "$(blasters_json)" '.blasters = $b'
trap - EXIT
echo "CREATES DONE"
"""
# The same section of the bench-5 driver (85fb888 do_run, the create loop through `.blasters = $b`), for the capture.
BENCH5_FNS = ("blaster_name", "node_url", "is_stockout", "create_vm", "blasters_json", "assert_load_vm")
BENCH5_GLUE = r"""
start_at=$(( $(bench_now_unix) + BENCH_START_DELAY_SECS ))
gcloud auth print-access-token >/dev/null
pids=(); names=(); logs=()
for k in $(seq 0 $((VAL_COUNT - 1))); do
    name="$(blaster_name "$k")"; zone="${ZONES[$k]}"
    [ "${NODE_ROLES[$k]}" = "validator" ] || bench_die "index ${k} is not a validator"
    urls="$(node_url "$k")"
    start=$(( k * BENCH_SENDERS + BENCH_RUN_INDEX * 100000 ))
    echo ">>> ${name} (${zone}) -> ${urls} senders ${BENCH_SENDERS}@${start}"
    create_vm "${name}" "${zone}" blast "${urls}" "${BENCH_SENDERS}" "${start}" "${start_at}" \
        > "${BENCH_RESULTS_DIR}/logs/create-${name}.log" 2>&1 &
    pids+=("$!"); names+=("${name}"); logs+=("${BENCH_RESULTS_DIR}/logs/create-${name}.log")
done
failed=0
for j in "${!pids[@]}"; do
    if wait "${pids[$j]}"; then
        used="$(cat "${BENCH_RESULTS_DIR}/meta/${names[$j]}/MACHINE_TYPE" 2>/dev/null || true)"; note=""
        [ -z "${used}" ] || [ "${used}" = "${BENCH_BLASTER_MACHINE_TYPES%% *}" ] || note=", fallback after a stockout"
        echo "    ✓ created ${names[$j]} (${used:-type not recorded}${note})"
    else echo "❌ create ${names[$j]} failed:" >&2; tail -5 "${logs[$j]}" >&2; failed=1; fi
done
[ "${failed}" -eq 0 ] || bench_die "blaster creation failed — clean up with: benchmark/benchmark-blast.sh delete --yes"
for k in $(seq 0 $((VAL_COUNT - 1))); do assert_load_vm "$(blaster_name "$k")" "${ZONES[$k]}"; done
bench_manifest_jq --argjson b "$(blasters_json)" '.blasters = $b'
echo "CREATES DONE"
"""
CRASH_LINE = ("ERROR: gcloud crashed (ReadTimeout): HTTPSConnectionPool(host='compute.googleapis.com', port=443): "
              "Read timed out. (read timeout=300)")


class LiveCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        gcloud = self.sb.bin / "gcloud"
        gcloud.write_text((FIX / "fake-gcloud-live.sh").read_text())
        gcloud.chmod(0o755)
        self.stub = self.sb.root / "stub"
        self.stub.mkdir()
        self.results = self.sb.tree / "benchmark" / "results" / RUN_ID

    def tearDown(self):
        self.sb.close()

    def live(self, glue=NEW_GLUE, fns=LIVE_FNS, outcomes=None, wait_creates=0, manifest=None, **env):
        """The preamble, then <glue>; <outcomes> maps a blaster to its create calls' outcomes (fake-gcloud-live.sh).
        A dict: rc, out (stdout and stderr), calls, manifest, deleted [(name, fake time)], timeouts, vms (left)."""
        for name, outcome in (outcomes or {}).items():
            (self.stub / ("create-" + name)).write_text("".join(o + "\n" for o in outcome))
        script = self.sb.tree / "benchmark" / "benchmark-blast.sh"
        top = "".join(line + "\n" for line in script.read_text().splitlines() if LIVE_TOP.match(line))
        (self.sb.root / "functions.sh").write_text(top + shell_functions(script, *fns))
        for name in ("deployments.json", "config.toml"):
            (self.sb.root / name).write_text("{}\n")
        if manifest is not None:
            self.results.mkdir(parents=True, exist_ok=True)
            (self.results / "manifest.json").write_text(json.dumps(manifest))
        e = self.sb.env(TREE=str(self.sb.tree), WORK=str(self.sb.root), STUB=str(self.stub), STUB_FIX=str(FIX),
                        STUB_META=str(self.results / "meta"), STUB_WAIT_CREATES=str(wait_creates), BENCH_RUN_ID=RUN_ID,
                        **env)
        # $0 is the driver's name: benchmark/config.sh refuses any other caller.
        p = subprocess.run(["bash", "-c", LIVE_PREAMBLE + glue, "benchmark-blast.sh"], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT,
                           env=e, cwd=str(self.sb.root), universal_newlines=True, timeout=180)

        def read(name):
            f = self.stub / name
            return f.read_text() if f.exists() else ""
        calls = self.sb.calls.read_text() if self.sb.calls.exists() else ""
        return dict(rc=p.returncode, out=self.sb.normalize(p.stdout), calls=self.sb.normalize(calls).splitlines(),
                    manifest=json.loads((self.results / "manifest.json").read_text()),
                    deleted=sorted((n, int(t)) for n, t in (line.split() for line in read("deleted").splitlines())),
                    timeouts=sorted(read("http-timeout").splitlines()),
                    vms=sorted(f.name[len("vm-"):] for f in self.stub.glob("vm-*")))

    def creates(self, run, name):
        return [c for c in run["calls"] if c.startswith("gcloud compute instances create %s " % name)]

    def log(self, name):
        return (self.results / "logs" / ("create-%s.log" % name)).read_text()

    def entry(self, run, name):
        return next(b for b in run["manifest"]["blasters"] if b["name"] == name)


class CreatePathTests(LiveCase):
    """D36 (+D37, D39): a failed or timed-out create is described before anything is decided, retried once, and a
    create that failed or was not done by start_at - 30 s stops the run before any blaster sends."""

    def test_a_create_on_time_sends_and_records_what_bench5_did(self):
        run = self.live()
        self.assertEqual(run["rc"], 0, run["out"])
        ref = json.loads((FIX / "golden-live-create.json").read_text())
        # D48: bench 5 described each node inside the loop; bench 6 reads manifest.instances[] and asks gcloud nothing.
        nodes = [c for c in ref["calls"] if c.startswith("gcloud compute instances describe bench-validator-")]
        self.assertEqual(len(nodes), 10)
        self.assertEqual(sorted(run["calls"]), sorted(c for c in ref["calls"] if c not in nodes))
        self.assertEqual(run["out"], ref["output"])
        # blasters[]: bench 5's entries, key for key and in its order, then the three new keys.
        self.assertEqual([b["name"] for b in run["manifest"]["blasters"]], [b["name"] for b in ref["blasters"]])
        for got, want in zip(run["manifest"]["blasters"], ref["blasters"]):
            self.assertEqual(list(got)[:len(want)], list(want))
            self.assertEqual({k: got[k] for k in want}, want)
            self.assertEqual(list(got)[len(want):], ["created_at", "create_secs", "attempts"])
            self.assertEqual((got["created_at"], got["create_secs"], got["attempts"]), ("2026-01-01T00:00:00Z", 0, 1))
        self.assertIsNone(run["manifest"]["abort"])
        self.assertEqual(run["timeouts"], sorted("%s 60" % b for b in BLASTERS))
        self.assertIn(" @ARGV 90 env CLOUDSDK_CORE_HTTP_TIMEOUT=60 gcloud compute instances create bench-blaster-01 ",
                      self.log("bench-blaster-01"))
        self.assertEqual(run["deleted"], [])

    def check_created_anyway(self, outcome, rc):
        run = self.live(outcomes={"bench-blaster-06": [outcome]})
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertEqual(len(self.creates(run, "bench-blaster-06")), 1)      # no second create
        self.assertIn("gcloud compute instances describe bench-blaster-06 --zone=europe-west4-a --project=<PROJECT> "
                      "--format=json", run["calls"])
        self.assertIn("bench-blaster-06: create call 1 ended rc %d, but the instance exists (e2-standard-2): counted as "
                      "created" % rc, self.log("bench-blaster-06"))
        self.assertIn("    ✓ created bench-blaster-06 (e2-standard-2)\n", run["out"])
        self.assertEqual(self.entry(run, "bench-blaster-06")["attempts"], 1)
        self.assertEqual(self.entry(run, "bench-blaster-06")["machine_type"], "e2-standard-2")
        self.assertIsNone(run["manifest"]["abort"])
        self.assertEqual(run["vms"], BLASTERS)

    def test_a_crashed_create_whose_instance_exists_is_used(self):
        self.check_created_anyway("crash-created", 1)

    def test_a_timed_out_create_whose_instance_exists_is_used(self):
        self.check_created_anyway("alarm-created", 142)

    def test_a_crashed_create_is_retried_once(self):
        run = self.live(outcomes={"bench-blaster-06": ["crash", "ok"]})
        self.assertEqual(run["rc"], 0, run["out"])
        first, second = self.creates(run, "bench-blaster-06")
        self.assertEqual(first, second)
        self.assertIn("    ✓ created bench-blaster-06 (e2-standard-2, 2 create calls)\n", run["out"])
        self.assertIn("bench-blaster-06: create call 1 failed (rc 1) and the instance does not exist: one more try",
                      self.log("bench-blaster-06"))
        self.assertEqual((self.entry(run, "bench-blaster-06")["attempts"], self.entry(run, "bench-blaster-01")["attempts"]),
                         (2, 1))
        self.assertIsNone(run["manifest"]["abort"])

    def test_two_failures_stop_the_run_and_delete_every_blaster_before_start_at(self):
        run = self.live(outcomes={"bench-blaster-06": ["crash", "crash"]})
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertEqual(len(self.creates(run, "bench-blaster-06")), 2)
        # D39: the cause is printed, not gcloud's boilerplate after it.
        failure = run["out"][run["out"].index("❌ create bench-blaster-06 failed:\n"):]
        self.assertTrue(failure.startswith("❌ create bench-blaster-06 failed:\n" + CRASH_LINE + "\n"), failure)
        self.assertNotIn("If you would like to report this issue", run["out"])
        self.assertIn("❌ blaster creation failed (bench-blaster-06)", run["out"])
        # D37: the record names the create, not the operator; every blaster was deleted before start_at.
        abort = run["manifest"]["abort"]
        self.assertEqual({k: abort[k] for k in ("reason", "node", "detail", "unsent")},
                         {"reason": "create_failed", "node": "bench-blaster-06", "detail": CRASH_LINE, "unsent": True})
        self.assertIn("❌❌ ABORT: create_failed node=bench-blaster-06 — " + CRASH_LINE + " (unsent=true)", run["out"])
        self.assertIn("❌ run stopped (create_failed bench-blaster-06) (exit 1)", run["out"])
        self.assertNotIn("operator", run["out"])
        self.assertEqual(run["deleted"], [(b, FAKE_NOW) for b in BLASTERS if b != "bench-blaster-06"])
        self.assertEqual(run["vms"], [])
        self.assertFalse(any(c.startswith("gcloud compute ssh ") for c in run["calls"]))
        # each create that succeeded was recorded as soon as it was known
        self.assertEqual(sorted(b["name"] for b in run["manifest"]["blasters"]),
                         [b for b in BLASTERS if b != "bench-blaster-06"])

    def test_a_quota_failure_is_not_retried_and_its_detail_is_the_whole_error(self):
        run = self.live(outcomes={"bench-blaster-06": ["quota"]})
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertEqual(len(self.creates(run, "bench-blaster-06")), 1)
        self.assertEqual(run["manifest"]["abort"]["detail"],
                         "ERROR: (gcloud.compute.instances.create) Could not fetch resource: - Quota 'CPUS' exceeded.  "
                         "Limit: 24.0 in region europe-west4.")
        self.assertIn("❌ create bench-blaster-06 failed:\nERROR: (gcloud.compute.instances.create) Could not fetch "
                      "resource:\n - Quota 'CPUS' exceeded.", run["out"])
        self.assertEqual(run["manifest"]["abort"]["unsent"], True)

    def test_a_blaster_whose_delete_failed_may_have_sent(self):
        (self.stub / "delete-fail").write_text("")
        run = self.live(outcomes={"bench-blaster-06": ["quota"]})
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertEqual((run["manifest"]["abort"]["reason"], run["manifest"]["abort"]["unsent"]), ("create_failed", False))
        self.assertIn("❌ exit cleanup (c) delete the blasters before their start time: FAILED (rc=1)", run["out"])
        self.assertEqual(len(run["vms"]), 9)

    def test_deletes_that_return_after_start_at_may_have_let_a_blaster_send(self):
        # The run stops 285 s in, and its deletes take 20 s: they return after start_at, so nothing proves no blaster sent.
        (self.stub / "delete-secs").write_text("20\n")
        run = self.live(outcomes={"bench-blaster-06": ["ok@285"]}, wait_creates=9)
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertEqual((run["manifest"]["abort"]["reason"], run["manifest"]["abort"]["unsent"]), ("late_create", False))
        self.assertEqual(run["vms"], [])
        self.assertIn("✓ exit cleanup (c) delete the blasters before their start time: done", run["out"])

    def test_a_create_done_after_the_late_start_limit_stops_the_run_unsent(self):
        # bench-blaster-06's create answers 285 s in, after start_at - 30 s and before start_at.
        run = self.live(outcomes={"bench-blaster-06": ["ok@285"]}, wait_creates=9)
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertIn("❌ create bench-blaster-06 not done by the late-start limit 2026-01-01T00:04:30Z (start_at - 30 s): "
                      "it ended 2026-01-01T00:04:45Z, 1 create calls", run["out"])
        abort = run["manifest"]["abort"]
        self.assertEqual((abort["reason"], abort["node"], abort["unsent"]), ("late_create", "bench-blaster-06", True))
        self.assertEqual(abort["detail"], "create not done by 2026-01-01T00:04:30Z = start_at - 30 s (ok, 1 create calls, 285 s)")
        self.assertEqual(run["deleted"], [(b, FAKE_NOW + 285) for b in BLASTERS])
        self.assertEqual(run["vms"], [])
        self.assertEqual(self.entry(run, "bench-blaster-06")["created_at"], "2026-01-01T00:04:45Z")

    def test_no_call_outlasts_the_late_start_limit(self):
        # The crash answers 250 s in: the describe and the retry get the 20 s left before the limit, not 60 and 90.
        run = self.live(outcomes={"bench-blaster-06": ["crash@250", "ok"]}, wait_creates=9)
        self.assertEqual(run["rc"], 0, run["out"])
        log = self.log("bench-blaster-06")
        self.assertIn(" @ARGV 90 env CLOUDSDK_CORE_HTTP_TIMEOUT=60 gcloud compute instances create bench-blaster-06 ", log)
        self.assertIn(" @ARGV 20 env CLOUDSDK_CORE_HTTP_TIMEOUT=60 gcloud compute instances create bench-blaster-06 ", log)
        self.assertEqual(self.entry(run, "bench-blaster-06")["create_secs"], 250)

    def test_a_create_past_the_limit_makes_no_further_call(self):
        # The crash answers 280 s in, past the limit: no describe, no retry, and the run stops.
        run = self.live(outcomes={"bench-blaster-06": ["crash@280"]}, wait_creates=9)
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertEqual(len(self.creates(run, "bench-blaster-06")), 1)
        self.assertNotIn("instances.describe", self.log("bench-blaster-06"))
        # its one describe is the exit cleanup's, which deletes whatever exists
        self.assertEqual(len([c for c in run["calls"] if c.startswith("gcloud compute instances describe bench-blaster-06 ")]), 1)
        self.assertEqual(run["manifest"]["abort"]["reason"], "late_create")
        self.assertTrue(run["manifest"]["abort"]["detail"].startswith(
            "create not done by 2026-01-01T00:04:30Z = start_at - 30 s (late, 1 create calls, 280 s); " + CRASH_LINE),
            run["manifest"]["abort"])

    def test_a_failure_after_start_at_stops_only_the_blasters_that_exist(self):
        # The create fails 310 s in: the others have started, so nothing is unsent; bench-blaster-06 never existed, so
        # the exit cleanup neither stops it nor waits for its marker (bench 5 tried it 3 times and waited 5m36s).
        run = self.live(outcomes={"bench-blaster-06": ["quota@310"]}, wait_creates=9, BENCH_TRAP_WAIT_SECS="0")
        self.assertEqual(run["rc"], 1, run["out"])
        abort = run["manifest"]["abort"]
        self.assertEqual((abort["reason"], abort["node"], abort["unsent"]), ("create_failed", "bench-blaster-06", False))
        stopped = sorted(c.split()[3] for c in run["calls"] if c.startswith("gcloud compute ssh "))
        self.assertEqual(stopped, [b for b in BLASTERS if b != "bench-blaster-06"])
        serial = [c.split()[4] for c in run["calls"] if c.startswith("gcloud compute instances get-serial-port-output ")]
        self.assertNotIn("bench-blaster-06", serial)
        self.assertEqual(len(serial), 9)

    def test_the_lead_fits_two_create_calls_and_a_describe(self):
        rc, out, _ = self.sb.blast("run", BENCH_START_DELAY_SECS="100")
        self.assertEqual(rc, 0, out)
        self.assertIn("    start_at lead: 240s, not BENCH_START_DELAY_SECS=100: two create calls and the describe between "
                      "them must fit before it\n", out)
        self.assertIn(", start_at 2026-01-01T00:04:00Z\n", out)
        rc, out, _ = self.sb.blast("run", BENCH_START_DELAY_SECS="600")
        self.assertIn(", start_at 2026-01-01T00:10:00Z\n", out)
        self.assertNotIn("start_at lead", out)


class NodeUrlTests(LiveCase):
    """D48: node URLs are read once, before the creates, and each blaster's late start is recorded."""

    def node_urls(self, run):
        return {b["name"]: b["node_url"] for b in run["manifest"]["blasters"]}

    def test_node_urls_come_from_the_manifest_without_a_call(self):
        run = self.live()
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertFalse([c for c in run["calls"] if " bench-validator-" in c or "instances list" in c], run["calls"])
        self.assertEqual(self.node_urls(run), {b: "http://192.0.2.%d:8545" % (i + 1) for i, b in enumerate(BLASTERS)})

    def test_nodes_the_manifest_lacks_cost_one_list(self):
        listed = [{"name": "bench-validator-03", "zone": "https://x/zones/australia-southeast1-c",
                   "networkInterfaces": [{"networkIP": "198.51.100.3"}]},
                  {"name": "bench-validator-07", "zone": "https://x/zones/elsewhere-1a",
                   "networkInterfaces": [{"networkIP": "198.51.100.99"}]},
                  {"name": "bench-validator-07", "zone": "https://x/zones/asia-southeast1-b",
                   "networkInterfaces": [{"networkIP": "198.51.100.7"}]}]
        (self.stub / "list.json").write_text(json.dumps(listed))
        run = self.live(DROP_INSTANCES="bench-validator-03 bench-validator-07")
        self.assertEqual(run["rc"], 0, run["out"])
        lists = [c for c in run["calls"] if c.startswith("gcloud compute instances list ")]
        self.assertEqual(lists, ["gcloud compute instances list --project=<PROJECT> "
                                 "--filter=name=\\(bench-validator-03\\ bench-validator-07\\) --format=json"])
        self.assertIn("list 60", run["timeouts"])
        urls = self.node_urls(run)
        self.assertEqual((urls["bench-blaster-03"], urls["bench-blaster-07"], urls["bench-blaster-04"]),
                         ("http://198.51.100.3:8545", "http://198.51.100.7:8545", "http://192.0.2.4:8545"))
        self.assertFalse([c for c in run["calls"] if c.startswith("gcloud compute instances describe bench-validator-")])

    def test_a_node_without_an_ip_stops_the_run_before_any_create(self):
        run = self.live(DROP_INSTANCES="bench-validator-03")
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertIn("❌ bench-validator-03 has no internal IP — is the fleet up?", run["out"])
        self.assertFalse([c for c in run["calls"] if " instances create " in c])

    LATE = r"""
bench_manifest_jq '.blasters = [{name: "bench-blaster-01"}, {name: "bench-blaster-02"}, {name: "bench-blaster-03"}]'
mkdir -p "$BENCH_RESULTS_DIR/blasters"
phases() { printf '{"run": {"phases": [{"name": "preamble", "start_unix": %s, "end_unix": %s}]}}' "$1" "$(( $1 + 9 ))"; }
phases $(( 1767225600 + 302 )) > "$BENCH_RESULTS_DIR/blasters/bench-blaster-01.json"
phases $(( 1767225600 + 401 )) > "$BENCH_RESULTS_DIR/blasters/bench-blaster-02.json"
echo '{"run": {"phases": []}}' > "$BENCH_RESULTS_DIR/blasters/bench-blaster-04.json"
record_late_secs $(( 1767225600 + 300 ))
"""

    def test_late_secs_from_each_blasters_own_preamble(self):
        run = self.live(glue=self.LATE)
        self.assertEqual(run["rc"], 0, run["out"])
        blasters = run["manifest"]["blasters"]
        self.assertEqual([b.get("late_secs") for b in blasters], [2.0, 101.0, None])
        self.assertNotIn("late_secs", blasters[2])
        self.assertEqual([line for line in run["out"].splitlines() if line.startswith("⚠")],
                         ["⚠ bench-blaster-02 began its preamble 101.0s after start_at 2026-01-01T00:05:00Z "
                          "(blasters[].late_secs)"])


class UnsentRetryTests(LiveCase):
    """prev_attempt_unsent: an attempt a create stopped may be retried under its index once nothing can have sent."""

    def unsent(self, abort, start_at_offset, run_index=0):
        manifest = {"notes": [], "blasters": [], "abort": abort,
                    "blast": {"run_index": run_index, "start_at": time_iso(FAKE_NOW + start_at_offset)}}
        run = self.live(glue='prev_attempt_unsent && echo UNSENT=yes || echo UNSENT=no\n', manifest=manifest,
                        BENCH_RUN_INDEX="0")
        self.assertEqual(run["rc"], 0, run["out"])
        return "UNSENT=yes" in run["out"]

    def test_the_reasons_and_unsent(self):
        cases = [({"reason": "interrupted"}, 300, True), ({"reason": "interrupted", "unsent": True}, -10, False),
                 ({"reason": "create_failed", "unsent": True}, -10, True),
                 ({"reason": "late_create", "unsent": True}, 20, True),
                 ({"reason": "late_create", "unsent": False}, -10, False),
                 ({"reason": "create_failed", "unsent": False}, 300, True),
                 ({"reason": "late_create"}, -10, False), ({"reason": "disk-full", "unsent": True}, 300, False)]
        for abort, offset, want in cases:
            with self.subTest(abort=abort, offset=offset):
                self.assertEqual(self.unsent(abort, offset), want)
        self.assertFalse(self.unsent({"reason": "create_failed", "unsent": True}, -10, run_index=1))


def time_iso(unix):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(unix))


class DryRunShimTests(SandboxCase):
    """A dry run makes no live call: every gcloud verb that is not a read, and every docker, curl or credential
    helper call of the startup script, prints REACHED and exits 9 here."""

    READS = ("auth print-access-token", "compute instances describe", "compute instances list",
             "compute instances get-serial-port-output")
    SHIM = r"""#!/usr/bin/env bash
{ printf '%s'; printf ' %q' "$@"; printf '\n'; } >> "$CALLS"
case "$1 $2 ${3:-}" in
    "auth print-access-token ") echo fake-token; exit 0 ;;
@READS@
esac
echo REACHED; exit 9
"""

    def setUp(self):
        super(DryRunShimTests, self).setUp()
        reads = "".join('    "%s"*) exit 1 ;;\n' % r for r in self.READS[1:])
        for name in ("gcloud", "docker", "curl", "docker-credential-gcr"):
            shim = self.sb.bin / name
            shim.write_text(self.SHIM.replace("@READS@", reads if name == "gcloud" else "").replace("'%s'", "'%s'" % name))
            shim.chmod(0o755)

    def test_driver_dry_runs_reach_nothing(self):
        for args, env in ((("run",), {}), (("fund",), {}), (("delete",), {}), (("run",), {"BENCH_START_DELAY_SECS": "100"}),
                          (("run",), {"BENCH_LIGHT_LOAD": "1"}), (("fund",), {"BENCH_LIGHT_LOAD": "1"}),
                          # H1b: the tail scan, the landings export, a light blast's short lead, the sequence with it
                          (("run",), {"BENCH_TAIL_SCAN_SECS": "60", "BENCH_LANDINGS_SAMPLE": "100"}),
                          (("run",), {"BENCH_BLAST_KIND": "light", "BENCH_LIGHT_START_DELAY_SECS": "150"}),
                          (("run",), {"BENCH_LIGHT_LOAD": "1", "BENCH_LIGHT_START_DELAY_SECS": "150",
                                      "BENCH_TAIL_SCAN_SECS": "60"}),
                          (("fund",), {"BENCH_LIGHT_LOAD": "1", "BENCH_TAIL_SCAN_SECS": "60"})):
            with self.subTest(args=args, env=env):
                rc, out, calls = self.sb.blast(*args, **env)
                self.assertEqual(rc, 0, out)
                self.assertNotIn("REACHED", out)
                live = [c for c in calls.splitlines() if not any(c.startswith("gcloud " + r) for r in self.READS)]
                self.assertEqual(live, [])
                if args != ("delete",):            # a delete with no load VM listed prints no argv
                    self.assertIn("(dry run — not executed)", out)

    def test_startup_render_reaches_nothing(self):
        _, out, _ = self.sb.blast("run")
        self.sb.calls.unlink()
        rc, render = self.sb.render(startup_metadata(create_lines(out)[0]), out_files=("bench-blaster-01.json",))
        self.assertEqual(rc, 0, render)
        self.assertNotIn("REACHED", render)
        self.assertFalse(self.sb.calls.exists() and self.sb.calls.read_text())
        self.assertIn("DRY_RUN: docker run ", render)

    def test_each_live_create_and_delete_sits_behind_a_dry_run_guard(self):
        lines = (BENCH / "benchmark-blast.sh").read_text().splitlines()
        guard = '[ "${BENCH_APPLY}" = "1" ] || return 0'
        live = [i for i, line in enumerate(lines)
                if 'gcloud "${pre[@]}" --machine-type="${t}"' in line or '|| delete_vms "${ZONES[$k]}"' in line]
        self.assertEqual(len(live), 2)
        for i in live:
            before = lines[i - 1] if 'machine-type="${t}"' not in lines[i] else lines[i - 2]
            self.assertEqual(before.strip(), guard, lines[i])
        spawn = next(i for i, line in enumerate(lines) if '"${start_at}" "${limit}" \\' in line)
        self.assertTrue(lines[spawn - 1].strip().startswith('if [ "${BENCH_APPLY}" != "1" ]; then create_vm ')
                        and lines[spawn - 1].rstrip().endswith("; continue; fi"), lines[spawn - 1])
        # H1b: delete_vms' own call, the blasters' background deletes (D40) and the disk relabel; each dry branch
        # (delete_vms, delete_vm_bg) prints the argv and returns on the line before the guard.
        for start in ('    bench_run gcloud compute instances delete "$@" ', '    delete_vms "$1" "$2" < /dev/null &',
                      '    bench_run gcloud compute disks add-labels "$1" '):
            found = [i for i, line in enumerate(lines) if line.startswith(start)]
            self.assertEqual(len(found), 1, start)
            self.assertEqual(lines[found[0] - 1].strip(), guard, lines[found[0]])
        for fn in ("delete_vms", "delete_vm_bg"):
            body = lines[lines.index(fn + "() {" if fn == "delete_vm_bg" else "delete_vms() { # <zone> <name...>"):]
            dry = next(line for line in body if line.lstrip().startswith('if [ "${BENCH_APPLY}" != "1" ]; then '))
            self.assertTrue(dry.rstrip().endswith("; return 0; fi"), dry)
            self.assertEqual(body[body.index(dry) + 1].strip(), guard, fn)


# ---- bench6 blast driver (H1b: D38, D40, D42, D45-D47, the light lead, the tail scan, the pools at start) ----
def plan_line(out, prefix):
    return next(line for line in out.splitlines() if line.startswith(prefix))


def run_bash(code, timeout=120, **env):
    """bash -c <code> with no BENCH_* knob from the developer's shell; (rc, stdout, stderr)."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("BENCH_")}
    p = subprocess.run(["bash", "-c", code], env=dict(base, **env), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


class TailScanTests(SandboxCase):
    """BENCH_TAIL_SCAN_SECS: the generator's --tail-scan-secs, set only when the knob is; every wait for the done
    markers grows by it, and by the generator's 30 s of unlanded lookups whenever the landings export is on."""

    def test_the_flag_reaches_every_blaster_only_when_set(self):
        rc, out, _ = self.sb.blast("run", BENCH_TAIL_SCAN_SECS="60")
        self.assertEqual(rc, 0, out)
        argvs = create_lines(out)
        self.assertEqual([metadata_of(a).get("TAIL_SCAN_SECS") for a in argvs], ["60"] * 10)
        rc, render = self.sb.render(startup_metadata(argvs[0]))
        self.assertEqual(rc, 0, render)
        self.assertEqual(render.count("--tail-scan-secs"), 1)
        self.assertIn(" --stdout-json chunked --tail-scan-secs 60\n", render)
        self.assertIn("    blast: BENCH_RUN_INDEX=0 chaos=1 lag_inject=0 (node idx 2, mixed+300s for 180s) tail_scan=60s\n", out)
        # the funder never scans: its plan stays bench 4's
        self.assertEqual(golden_text(*self.sb.blast("fund", BENCH_TAIL_SCAN_SECS="60")),
                         bench6((FIX / "golden-fund-plan.txt").read_text(), 1))
        # unset: no key, no flag
        _, out, _ = self.sb.blast("run")
        self.assertTrue(all("TAIL_SCAN_SECS" not in metadata_of(a) for a in create_lines(out)))
        rc, render = self.sb.render(startup_metadata(create_lines(out)[0]))
        for text in ("TAIL_SCAN", "tail_scan", "tail scan", "--tail-scan-secs"):
            self.assertNotIn(text, out + render)

    def test_every_done_wait_grows_by_the_tail_and_the_unlanded_lookups(self):
        # cooldown end 00:51:30 (start_at 00:05:00 + 90 + 120 + 2400 + 180 s), then 600 s, then the extra
        note = " (cooldown end + 600 s + %d s for the tail scan and the unlanded lookups)"
        for env, deadline, extra in (({}, "01:01:30", None), ({"BENCH_TAIL_SCAN_SECS": "60"}, "01:02:30", 60),
                                     ({"BENCH_LANDINGS_SAMPLE": "100"}, "01:02:00", 30),
                                     ({"BENCH_TAIL_SCAN_SECS": "60", "BENCH_LANDINGS_SAMPLE": "100"}, "01:03:00", 90)):
            with self.subTest(env=env):
                rc, out, _ = self.sb.blast("run", **env)
                self.assertEqual(rc, 0, out)
                line = plan_line(out, "    phases (planned): ")
                self.assertTrue(line.endswith("; wait deadline 2026-01-01T%sZ%s" % (deadline, note % extra if extra else "")),
                                line)
        self.assertEqual(line, "    phases (planned): preamble 90s, warmup 120s, mixed 2400s, cooldown 180s, tail scan 60s "
                               "(not a phase); wait deadline 2026-01-01T01:03:00Z" + note % 90)
        source = (BENCH / "benchmark-blast.sh").read_text()
        # the exit cleanup's wait and the deadline after an abort grow by the same amount
        self.assertIn("    wait_secs=$(( BENCH_TRAP_WAIT_SECS + $(done_wait_extra_secs) ))\n", source)
        self.assertIn("            deadline=$(( now + 600 + extra ))\n", source)

    def test_a_bad_tail_scan_fails_the_vm_before_the_generator(self):
        _, out, _ = self.sb.blast("run")
        md = startup_metadata(create_lines(out)[0])
        md["TAIL_SCAN_SECS"] = "01"
        rc, render = self.sb.render(md)
        self.assertEqual(rc, 2)
        self.assertIn("BENCH_BLAST_DONE rc=2 reason=bad-TAIL_SCAN_SECS:'01'", render)
        self.assertNotIn("docker run", render)

    def test_the_result_goes_up_last_and_the_unlanded_file_beside_the_landings(self):
        # The driver reads completion from a listing of the bucket's *.json: once <label>.json is there, so is the rest.
        _, out, _ = self.sb.blast("run", BENCH_LANDINGS_SAMPLE="100", BENCH_TAIL_SCAN_SECS="60")
        files = ("bench-blaster-01.json", "landings-bench-blaster-01.ndjson.gz", "unlanded-bench-blaster-01.ndjson.gz",
                 "zz-late.txt")
        rc, render = self.sb.render(startup_metadata(create_lines(out)[0]), out_files=files)
        self.assertEqual(rc, 0, render)
        prefix = GS + "<PROJECT>-bench-rtest-blast/rtest-blast/index-0/blasters/"
        ups = re.findall(r"would upload <ROOT>/state/out/(\S+) -> (\S+)", render)
        self.assertEqual(sorted(ups), sorted((f, prefix + f) for f in files))
        self.assertEqual(ups[-1], ("bench-blaster-01.json", prefix + "bench-blaster-01.json"))
        self.assertLess(render.rindex("uploaded bench-blaster-01.json"), render.index("BENCH_BLAST_DONE rc=0 reason=ok"))


class TxgenProbeTests(unittest.TestCase):
    """preflight's image probe requires --tail-scan-secs exactly when BENCH_TAIL_SCAN_SECS is set: an image without
    it would fail on every blaster after start_at."""

    DOCKER = r'''#!/usr/bin/env bash
case " $* " in
    *" info "*) exit 0 ;;
    *" login "*) cat > /dev/null; exit 0 ;;
    *" blast --help "*) cat "$HELP"; exit 0 ;;
esac
exit 1
'''
    PREAMBLE = r'''
set -euo pipefail
bench_warn() { echo "⚠ $*" >&2; }
bench_die() { echo "❌ $*" >&2; exit 1; }
BENCH_TXGEN_IMAGE=registry.invalid/txgen:blast-v2-abcdef1
'''

    def probe(self, help_flags, **env):
        lib = (BENCH / "bench-lib.sh").read_text().splitlines()
        contract = next(line for line in lib if line.startswith("BENCH_TXGEN_CONTRACT_FLAGS="))
        code = (self.PREAMBLE + contract + "\n" + shell_functions(BENCH / "bench-lib.sh", "bench_txgen_cli_probe")
                + shell_functions(BENCH / "benchmark-blast.sh", "txgen_cli_probe") + "txgen_cli_probe\necho PROBE OK\n")
        flags = contract.split('"')[1].split() + list(help_flags)
        with tempfile.TemporaryDirectory(prefix="blast-probe-") as directory:
            work = Path(directory)
            (work / "bin").mkdir()
            for name, body in (("docker", self.DOCKER), ("gcloud", GCLOUD)):
                (work / "bin" / name).write_text(body)
                (work / "bin" / name).chmod(0o755)
            (work / "help").write_text("".join("      %s <VALUE>\n" % f for f in flags))
            return run_bash(code, PATH=str(work / "bin") + os.pathsep + os.environ["PATH"], HELP=str(work / "help"),
                            CALLS=str(work / "calls"), TMPDIR=str(work), **env)

    def test_the_flag_is_required_only_with_the_tail_on(self):
        rc, out, err = self.probe((), BENCH_TAIL_SCAN_SECS="60")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("'blast --help' lacks: --tail-scan-secs (or the image could not be run;", err)
        rc, out, err = self.probe(("--tail-scan-secs",), BENCH_TAIL_SCAN_SECS="60")
        self.assertEqual((rc, out.splitlines()[-1]), (0, "PROBE OK"), err)
        rc, out, err = self.probe((), BENCH_TAIL_SCAN_SECS="0")
        self.assertEqual((rc, out.splitlines()[-1]), (0, "PROBE OK"), err)
        rc, out, err = self.probe(())
        self.assertEqual((rc, out.splitlines()[-1]), (0, "PROBE OK"), err)


class LightLeadTests(SandboxCase):
    """A light blast of the sequence (BENCH_BLAST_KIND=light) starts BENCH_LIGHT_START_DELAY_SECS after the announce,
    not raised to the 240-s floor; the load blast keeps BENCH_START_DELAY_SECS."""

    def start_at(self, out):
        return re.findall(r"^>>> run \S+ index ([0-9]+): .*, start_at (\S+)$", out, re.M)

    def test_a_light_blast_takes_its_own_lead_without_the_floor(self):
        rc, out, _ = self.sb.blast("run", BENCH_BLAST_KIND="light", BENCH_LIGHT_START_DELAY_SECS="150")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.start_at(out), [("0", "2026-01-01T00:02:30Z")])
        self.assertIn("    start_at lead: 150s (BENCH_LIGHT_START_DELAY_SECS, a light blast), not raised to 240s: a create "
                      "that needs its retry stops the blast unsent at start_at - 30 s\n", out)
        # the load blast keeps BENCH_START_DELAY_SECS whatever the light knob says
        rc, out, _ = self.sb.blast("run", BENCH_LIGHT_START_DELAY_SECS="150")
        self.assertEqual(self.start_at(out), [("0", "2026-01-01T00:05:00Z")])
        self.assertNotIn("start_at lead", out)
        # unset, a light blast's lead is bench 5's 300 s and its plan has no new line
        rc, out, _ = self.sb.blast("run", BENCH_BLAST_KIND="light")
        self.assertEqual(self.start_at(out), [("0", "2026-01-01T00:05:00Z")])
        self.assertNotIn("start_at lead", out)

    def test_the_sequence_gives_the_short_lead_to_its_light_blasts_only(self):
        rc, out, _ = self.sb.blast("run", BENCH_LIGHT_LOAD="1", BENCH_LIGHT_LOAD_AFTER="1", BENCH_LIGHT_START_DELAY_SECS="150")
        self.assertEqual(rc, 0, out)
        short, load = "2026-01-01T00:02:30Z", "2026-01-01T00:05:00Z"
        self.assertEqual(self.start_at(out), [("0", short), ("1", short), ("2", short), ("3", load), ("4", short)])
        self.assertEqual(out.count("    start_at lead: 150s "), 4)

    def test_an_unknown_blast_kind_is_refused(self):
        rc, out, _ = self.sb.blast("run", BENCH_BLAST_KIND="heavy")
        self.assertEqual(rc, 1, out)
        self.assertIn("❌ BENCH_BLAST_KIND='heavy' must be light or load", out)
        self.assertNotIn("compute instances create", out)


# In front of fixtures/blast/fake-gcloud-live.sh (renamed gcloud-live): the bucket listing ($STUB/listing), each
# blaster's serial console ($STUB/serial-<name>), a status describe, and slow deletes and relabels.
H1B_GCLOUD = r'''#!/usr/bin/env bash
logged() { { printf 'gcloud'; printf ' %q' "$@"; printf '\n'; } >> "$CALLS"; }
case "$1 $2 ${3:-}" in
    "storage ls "*) logged "$@"; [ -f "$STUB/listing" ] || exit 1; cat "$STUB/listing"; exit 0 ;;
    "compute instances get-serial-port-output") logged "$@"; cat "$STUB/serial-$4" 2>/dev/null; exit 0 ;;
    "compute instances describe")
        case "$*" in *"value(status)"*)
            logged "$@"
            [ -f "$STUB/vm-$4" ] || { echo "ERROR: (gcloud.compute.instances.describe) The resource '$4' was not found" >&2; exit 1; }
            jq -r '.status // "?"' "$STUB/vm-$4"; exit 0 ;;
        esac ;;
    "compute instances delete") sleep "${STUB_DELETE_SLEEP:-0}" ;;
    "compute disks add-labels") sleep "${STUB_LABEL_SLEEP:-0}" ;;
esac
exec "$(dirname "$0")/gcloud-live" "$@"
'''
# N_BLASTERS created blasters (meta/<name>/MACHINE_TYPE and a running instance), except the names in NOT_CREATED;
# BAD_TAG names one whose instance lacks the bench-blaster tag.
CREATED = r'''
VAL_COUNT="${N_BLASTERS:-4}"
for k in $(seq 0 $((VAL_COUNT - 1))); do
    n="$(blaster_name "$k")"
    case " ${NOT_CREATED:-} " in *" ${n} "*) continue ;; esac
    mkdir -p "$BENCH_RESULTS_DIR/meta/$n"; echo e2-standard-2 > "$BENCH_RESULTS_DIR/meta/$n/MACHINE_TYPE"
    tags='["bench-blaster"]'; [ "${n}" != "${BAD_TAG:-}" ] || tags='[]'
    printf '{"name": "%s", "status": "RUNNING", "tags": {"items": %s}, "labels": {"benchmark": "1"}}\n' "$n" "$tags" > "$STUB/vm-$n"
done
'''


class H1bLiveCase(LiveCase):
    def setUp(self):
        super(H1bLiveCase, self).setUp()
        (self.sb.bin / "gcloud").rename(self.sb.bin / "gcloud-live")
        (self.sb.bin / "gcloud").write_text(H1B_GCLOUD)
        (self.sb.bin / "gcloud").chmod(0o755)

    def lines(self, out, prefix):
        return [line for line in out.splitlines() if line.startswith(prefix)]


class BucketCompletionTests(H1bLiveCase):
    """D40 (a): one listing of the bucket per check; a blaster's serial marker is read once its result file is listed
    (the startup uploads that file last), and never for a blaster that was not created."""

    CHECKS = CREATED + r'''
p="$(bucket_prefix blasters)"
listed() { for n in "$@"; do echo "$p/$n"; done > "$STUB/listing"; }
check() { local rc=0; bucket_done_check || rc=$?; echo "CHECK RC ${rc}"; }
listed bench-blaster-01.json bench-blaster-02.json landings-bench-blaster-03.ndjson.gz bench-blaster-03.json.part
printf 'boot\nBENCH_BLAST_DONE rc=0 reason=ok\n' > "$STUB/serial-bench-blaster-01"
check
printf 'BENCH_BLAST_DONE rc=0 reason=ok\n' > "$STUB/serial-bench-blaster-02"
printf 'BENCH_BLAST_DONE rc=75 reason=upload-failed gen_rc=0\n' > "$STUB/serial-bench-blaster-03"
listed bench-blaster-01.json bench-blaster-02.json bench-blaster-03.json
check
printf 'BENCH_BLAST_DONE rc=0 reason=ok\n' > "$STUB/serial-bench-blaster-04"
listed bench-blaster-01.json bench-blaster-02.json bench-blaster-03.json bench-blaster-04.json
check
rm -f "$STUB/listing"
check
'''

    def test_one_listing_per_check_and_a_serial_read_per_listed_result(self):
        run = self.live(glue=self.CHECKS, N_BLASTERS="5", NOT_CREATED="bench-blaster-05")
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertEqual(self.lines(run["out"], "CHECK RC "), ["CHECK RC 1", "CHECK RC 1", "CHECK RC 0", "CHECK RC 0"])
        listings = [c for c in run["calls"] if c.startswith("gcloud storage ls ")]
        self.assertEqual(listings, ["gcloud storage ls " + GS + "<PROJECT>-bench-rtest-blast/rtest-blast/index-0/blasters/"
                                    "\\*.json --project=<PROJECT>"] * 4)
        serial = [c.split()[4] for c in run["calls"] if " get-serial-port-output " in c]
        # check 1: 01 and 02 (02 has no marker yet); check 2: 02 again, 03; check 3: 04; check 4: nothing left
        self.assertEqual(serial, ["bench-blaster-01", "bench-blaster-02", "bench-blaster-02", "bench-blaster-03",
                                  "bench-blaster-04"])
        self.assertEqual(self.lines(run["out"], "    bench-blaster-"), [
            "    bench-blaster-01: BENCH_BLAST_DONE rc=0 reason=ok (result in the bucket)",
            "    bench-blaster-02: BENCH_BLAST_DONE rc=0 reason=ok (result in the bucket)",
            "    bench-blaster-03: BENCH_BLAST_DONE rc=75 reason=upload-failed gen_rc=0 (result in the bucket)",
            "    bench-blaster-04: BENCH_BLAST_DONE rc=0 reason=ok (result in the bucket)"])

    DEFER = r'''
chaos_on=1; ABORTED=""; RUN_DID_KILL=0; RUN_DID_BACK=0; RUN_DID_OBS=1; t_kill=1000; t_back=2000; t_obs=0
BENCH_CHAOS_GUARD_SECS=90
for now in 850 910 999 1000; do
    next_check=500
    if bucket_check_deferred "${now}"; then echo "AT ${now} deferred to ${next_check}"; else echo "AT ${now} runs (${next_check})"; fi
done
chaos_on=0; next_check=500
bucket_check_deferred 910 || echo "AT 910 runs without chaos"
'''

    def test_a_check_gives_way_to_a_chaos_action_and_runs_right_after_it(self):
        run = self.live(glue=self.DEFER, fns=("next_action_due", "bucket_check_deferred"))
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertEqual(self.lines(run["out"], "AT "), ["AT 850 runs (500)", "AT 910 deferred to 1000",
                                                         "AT 999 deferred to 1000", "AT 1000 runs (500)",
                                                         "AT 910 runs without chaos"])
        self.assertFalse(run["calls"])

    def test_the_watch_loop_checks_the_bucket_from_the_planned_mixed_end(self):
        source = (BENCH / "benchmark-blast.sh").read_text()
        body = source[source.index("\ndo_run() {"):source.index("\n# ================================ collect")]
        loop = body[body.index("    while :; do\n"):body.index("\n    done\n", body.index("    while :; do\n"))]
        self.assertIn('n next_check="${p3}"\n', body)
        self.assertIn('        if [ "${all_done}" -eq 0 ] && [ "${now}" -ge "${next_check}" ] && ! bucket_check_deferred '
                      '"${now}"; then\n            if bucket_done_check; then all_done=1; fi\n'
                      '            next_check=$(( now + BUCKET_CHECK_SECS ))\n', loop)
        self.assertIn('        [ "${next_check}" -ge "${target}" ] || target="${next_check}"\n', loop)
        self.assertIn("\nBUCKET_CHECK_SECS=20; BUCKET_LS_ALARM_SECS=60\n", source)
        # the 240-s poll stays: it reads every node's status and catches a blaster that ends without a result file
        self.assertIn("            if poll_blasters; then all_done=1; else all_done=0; fi\n", loop)


class BackgroundDeleteTests(H1bLiveCase):
    """D40 (b): each safe blaster's delete runs in the background, then one describe per VM still there per pass until
    all are gone or the cap; bench 5 deleted them one after another (about 20 s each)."""

    SETTLE = CREATED + r'''
for k in $(seq 0 $((VAL_COUNT - 1))); do DONE_LINE[k]="BENCH_BLAST_DONE rc=0 reason=ok"; done
DONE_LINE[$((VAL_COUNT - 1))]=""     # the last one sent no marker: its results are fetched over IAP or it is kept
DELETE_POLL_SECS="${POLL_SECS:-1}"; DELETE_WAIT_SECS="${WAIT_SECS:-10}"
t0="$(date +%s%N)"
settle_blasters
echo "SETTLE RC $? MS $(( ($(date +%s%N) - t0) / 1000000 )) JOBS ${#DELETE_JOBS[@]}"
'''

    def test_the_deletes_run_in_the_background_then_a_describe_loop(self):
        # four deletes of 2 s each: about 2 s in the background, 8 s or more one after another
        run = self.live(glue=self.SETTLE, N_BLASTERS="5", STUB_DELETE_SLEEP="2")
        self.assertEqual(run["rc"], 0, run["out"])
        settle = self.lines(run["out"], "SETTLE RC ")[0].split()
        self.assertEqual((settle[2], settle[6]), ("0", "0"))
        self.assertLess(int(settle[4]), 6000, run["out"])
        self.assertIn("    waiting for 4 blaster delete(s): a describe each every 1 s, at most 10 s\n", run["out"])
        self.assertEqual(sorted(self.lines(run["out"], "    ✓ ")), ["    ✓ bench-blaster-0%d deleted" % i for i in range(1, 5)])
        self.assertEqual(sorted(n for n, _ in run["deleted"]), BLASTERS[:4])
        self.assertEqual(run["vms"], ["bench-blaster-05"])
        self.assertIn("❌ bench-blaster-05 KEPT: its results could not be fetched (no marker).", run["out"])
        status = [c.split()[4] for c in run["calls"] if "--format=value\\(status\\)" in c]
        self.assertEqual(sorted(set(status)), BLASTERS[:4])          # the describe loop asks about the deleted VMs only
        self.assertNotIn("❌ bench-blaster-0", run["out"].replace("❌ bench-blaster-05 KEPT", ""))

    def test_a_vm_still_there_at_the_cap_is_named_and_the_run_goes_on(self):
        (self.stub / "delete-fail").write_text("")
        run = self.live(glue=self.SETTLE, N_BLASTERS="3", POLL_SECS="0", WAIT_SECS="2")
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertEqual(self.lines(run["out"], "SETTLE RC ")[0].split()[2], "0")
        still = self.lines(run["out"], "❌ bench-blaster-0")
        self.assertEqual([s.split(" (")[0] for s in still if "still there" in s], ["❌ bench-blaster-01", "❌ bench-blaster-02"])
        self.assertTrue(all(s.endswith(") still there after 2 s (status RUNNING) — benchmark/benchmark-blast.sh delete "
                                       "--yes removes it") for s in still if "still there" in s), still)
        status = [c.split()[4] for c in run["calls"] if "--format=value\\(status\\)" in c]
        # three passes (DELETE_WAIT_SECS / max(DELETE_POLL_SECS, 1) + 1) of one describe per VM still there
        self.assertEqual(sorted(status), sorted(["bench-blaster-01", "bench-blaster-02"] * 3))
        self.assertEqual(run["vms"], BLASTERS[:3])


class ParallelRelabelTests(H1bLiveCase):
    """D40 (c): every blaster's check and disk relabel at once (bench 5: about 1.3 min one after another), the output in
    blaster order, at most RELABEL_WAIT_SECS."""

    GLUE = CREATED + r'''
RELABEL_WAIT_SECS="${RELABEL_WAIT:-180}"
t0="$(date +%s%N)"
rc=0; ( assert_load_vms ) || rc=$?
echo "RELABEL RC ${rc} MS $(( ($(date +%s%N) - t0) / 1000000 ))"
'''

    def relabels(self, run):
        return [line.split()[5] for line in run["out"].splitlines() if " compute disks add-labels " in line
                and line.startswith("    + ")]

    def test_the_relabels_run_at_once_and_print_in_order(self):
        run = self.live(glue=self.GLUE, STUB_LABEL_SLEEP="2")
        self.assertEqual(run["rc"], 0, run["out"])
        result = self.lines(run["out"], "RELABEL RC ")[0].split()
        self.assertEqual(result[2], "0", run["out"])
        self.assertLess(int(result[4]), 6000, run["out"])              # 8 s or more one after another
        self.assertEqual(self.relabels(run), BLASTERS[:4])
        self.assertEqual(len([c for c in run["calls"] if c.startswith("gcloud compute disks add-labels ")]), 4)

    def test_a_failed_check_stops_the_run_and_names_the_blaster(self):
        run = self.live(glue=self.GLUE, BAD_TAG="bench-blaster-03")
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertEqual(self.lines(run["out"], "RELABEL RC ")[0].split()[2], "1")
        self.assertIn("❌ bench-blaster-03 lacks tag bench-blaster / label benchmark=1", run["out"])
        self.assertIn("❌ blaster check or disk relabel failed: bench-blaster-03 — the exit cleanup deletes the blasters; "
                      "if it cannot: benchmark/benchmark-blast.sh delete --yes", run["out"])
        self.assertEqual(self.relabels(run), ["bench-blaster-01", "bench-blaster-02", "bench-blaster-04"])

    def test_a_relabel_past_the_wait_counts_as_failed(self):
        run = self.live(glue=self.GLUE, N_BLASTERS="2", STUB_LABEL_SLEEP="3", RELABEL_WAIT="1")
        time.sleep(3)                                                   # the stopped relabels' gcloud calls end
        self.assertEqual(run["rc"], 0, run["out"])
        result = self.lines(run["out"], "RELABEL RC ")[0].split()
        self.assertEqual(result[2], "1", run["out"])
        self.assertLess(int(result[4]), 3000, run["out"])
        self.assertIn("❌ blaster check or disk relabel failed: bench-blaster-01 (still running after 1 s) "
                      "bench-blaster-02 (still running after 1 s) — the exit cleanup deletes the blasters;", run["out"])


class DryRunLivePathTests(LiveCase):
    """D40's live paths with BENCH_APPLY=0 under the REACHED shim: each prints its argv, none reaches gcloud, and no
    background delete is started."""

    GLUE = CREATED + r'''
BENCH_APPLY=0
for k in $(seq 0 $((VAL_COUNT - 1))); do DONE_LINE[k]="BENCH_BLAST_DONE rc=0 reason=ok"; done
assert_load_vms; echo "RELABEL RC $?"
delete_vm_bg zone-x bench-blaster-01; echo "JOBS ${#DELETE_JOBS[@]}"
await_deletes; echo "AWAIT RC $?"
settle_blasters; echo "SETTLE RC $? JOBS ${#DELETE_JOBS[@]}"
'''

    def setUp(self):
        super(DryRunLivePathTests, self).setUp()
        reads = "".join('    "%s"*) exit 1 ;;\n' % r for r in DryRunShimTests.READS[1:])
        (self.sb.bin / "gcloud").write_text(DryRunShimTests.SHIM.replace("@READS@", reads).replace("'%s'", "'gcloud'"))

    def test_the_new_live_paths_reach_nothing_in_a_dry_run(self):
        run = self.live(glue=self.GLUE)
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertNotIn("REACHED", run["out"])
        self.assertEqual(run["calls"], [])
        self.assertEqual([line for line in run["out"].splitlines() if " RC " in line or line.startswith("JOBS ")],
                         ["RELABEL RC 0", "JOBS 0", "AWAIT RC 0", "SETTLE RC 0 JOBS 0"])
        # the copy, the direct delete and one delete per blaster: printed, not run
        self.assertEqual(run["out"].count("      (dry run — not executed)\n"), 6)
        self.assertEqual(run["out"].count("    + gcloud compute instances delete bench-blaster-0"), 5)
        self.assertNotIn("waiting for", run["out"])
        self.assertEqual(run["vms"], BLASTERS[:4])


class RealPhasesTests(H1bLiveCase):
    """D42: once every created blaster's result holds run.phases, manifest .phases is the real schedule (earliest start
    rounded down, latest end rounded up, per phase) and the plan is .phases_planned. The blasters here start their
    mixed phase 77 s before the plan, as bench 5's load did."""

    PHASES = CREATED + r'''
T0=$(( 1767225600 + 300 ))
i() { bench_iso_from_unix "$(( T0 + $1 ))"; }
bench_manifest_jq --arg a "$(i 0)" --arg b "$(i 90)" --arg c "$(i 210)" --arg d "$(i 2610)" --arg e "$(i 2790)" \
    '.phases = [{name:"preamble",start:$a,end:$b},{name:"warmup",start:$b,end:$c},{name:"mixed",start:$c,end:$d},{name:"cooldown",start:$d,end:$e}]'
mkdir -p "$BENCH_RESULTS_DIR/blasters"
phases() { # <name> <preamble start> <preamble end> <cooldown end>: seconds after start_at; warmup 120 s, mixed 2400 s
    jq -n --argjson t "${T0}" --argjson a "$2" --argjson b "$3" --argjson e "$4" '{run: {phases: [
        {name: "preamble", start_unix: ($t + $a), end_unix: ($t + $b)},
        {name: "warmup", start_unix: ($t + $b), end_unix: ($t + $b + 120)},
        {name: "mixed", start_unix: ($t + $b + 120), end_unix: ($t + $b + 2520)},
        {name: "cooldown", start_unix: ($t + $b + 2520), end_unix: ($t + $e)}]}}' > "$BENCH_RESULTS_DIR/blasters/$1.json"
}
phases bench-blaster-01 0.4 13.1 2534.6
phases bench-blaster-02 2.7 13.6 2580.2
[ -n "${NO_THIRD:-}" ] || phases bench-blaster-03 0.9 13.3 2541.0
record_real_phases
cp "$(bench_manifest)" "$WORK/first.json"
phases bench-blaster-02 2.7 13.6 2590.2
record_real_phases
'''
    PLAN = [("preamble", "00:05:00", "00:06:30"), ("warmup", "00:06:30", "00:08:30"), ("mixed", "00:08:30", "00:48:30"),
            ("cooldown", "00:48:30", "00:51:30")]

    def phases(self, rows):
        return [{"name": n, "start": "2026-01-01T%sZ" % a, "end": "2026-01-01T%sZ" % b} for n, a, b in rows]

    def test_phases_become_the_blasters_own_and_the_plan_is_kept(self):
        run = self.live(glue=self.PHASES, N_BLASTERS="4", NOT_CREATED="bench-blaster-04")
        self.assertEqual(run["rc"], 0, run["out"])
        real = [("preamble", "00:05:00", "00:05:14"), ("warmup", "00:05:13", "00:07:14"), ("mixed", "00:07:13", "00:47:14"),
                ("cooldown", "00:47:13", "00:48:01")]
        first = json.loads((self.sb.root / "first.json").read_text())
        self.assertEqual(first["phases"], self.phases(real))
        self.assertEqual(first["phases_planned"], self.phases(self.PLAN))
        self.assertTrue(any(n.startswith("phases rewritten at ") for n in first["notes"]), first["notes"])
        self.assertIn("    phases (real, the blasters' run.phases; the plan is kept as phases_planned): preamble "
                      "2026-01-01T00:05:00Z - 2026-01-01T00:05:14Z, warmup 2026-01-01T00:05:13Z - 2026-01-01T00:07:14Z, "
                      "mixed 2026-01-01T00:07:13Z - 2026-01-01T00:47:14Z, cooldown 2026-01-01T00:47:13Z - "
                      "2026-01-01T00:48:01Z\n", run["out"])
        # a second rewrite takes the newer results and keeps the first plan, never the first rewrite
        self.assertEqual(run["manifest"]["phases"][3], {"name": "cooldown", "start": "2026-01-01T00:47:13Z",
                                                        "end": "2026-01-01T00:48:11Z"})
        self.assertEqual(run["manifest"]["phases_planned"], self.phases(self.PLAN))

    def test_without_every_result_the_plan_stays(self):
        run = self.live(glue=self.PHASES, N_BLASTERS="3", NO_THIRD="1")
        self.assertEqual(run["rc"], 0, run["out"])
        self.assertEqual(self.lines(run["out"], "    phases: "),
                         ["    phases: kept as planned (no run.phases from: bench-blaster-03)"] * 2)
        self.assertEqual(run["manifest"]["phases"], self.phases(self.PLAN))
        self.assertNotIn("phases_planned", run["manifest"])


class BlastRecordTests(H1bLiveCase):
    """manifest .blast carries tail_scan_secs, the blasters' --tail-scan-secs (0 when off)."""

    GLUE = 'record_blast $(( 1767225600 + 300 ))\n'

    def test_tail_scan_secs_is_recorded_with_the_blast(self):
        for env, want in (({}, 0), ({"BENCH_TAIL_SCAN_SECS": "60"}, 60)):
            with self.subTest(env=env):
                run = self.live(glue=self.GLUE, fns=LIVE_FNS + ("record_blast",), **env)
                self.assertEqual(run["rc"], 0, run["out"])
                blast = run["manifest"]["blast"]
                self.assertEqual(list(blast), ["run_index", "chaos", "lag_inject", "lag_idx", "lag_at_secs", "lag_pause_secs",
                                               "start_at", "bucket_prefix", "tail_scan_secs"])
                self.assertEqual((blast["start_at"], blast["tail_scan_secs"]), ("2026-01-01T00:05:00Z", want))


class ExitCleanupTests(H1bLiveCase):
    """The exit cleanup's wait for the done markers grows by the tail scan and the unlanded lookups, and a run started
    by hand records its blast_runs[] entry on the way out (D46)."""

    def test_the_wait_covers_the_tail_and_the_hand_run_is_recorded(self):
        glue = "sleep() { :; }\nBLAST_RUN_STARTED=2026-01-01T00:00:00Z\n" + NEW_GLUE
        run = self.live(glue=glue, outcomes={"bench-blaster-06": ["quota@310"]}, wait_creates=9, BENCH_TRAP_WAIT_SECS="0",
                        BENCH_TAIL_SCAN_SECS="60", BENCH_LANDINGS_SAMPLE="100")
        self.assertEqual(run["rc"], 1, run["out"])
        self.assertIn(" This takes up to 90s of waiting for the blasters' results plus a few minutes", run["out"])
        self.assertIn("❌ exit cleanup (d) wait up to 90s for every blaster's done marker: FAILED (rc=1)", run["out"])
        serial = [c for c in run["calls"] if " get-serial-port-output " in c]
        self.assertEqual(len(serial), 9 * 4)                            # a poll at 0, 30, 60 and 90 s
        entry = run["manifest"]["blast_runs"]
        self.assertEqual([(e["action"], e["index"], e["started"], e["rc"], e["log"]) for e in entry],
                         [("run", 0, "2026-01-01T00:00:00Z", 1, None)])
        self.assertNotIn("step_14_done", run["manifest"]["timestamps"])


# blast_runs[] (D46): a `fund` or `run` started by hand records itself; the deploy and the sequence's children do not.
BLAST_RUN_HARNESS = r'''
set -euo pipefail
BENCH_RESULTS_DIR="$WORK"; BENCH_APPLY="${APPLY:-1}"; ACTION="${ACT:-run}"; BENCH_RUN_INDEX=4
BLAST_LOG="$WORK/logs/blast-${ACTION}-20260101T000000Z.log"
bench_now_iso() { local n; n=$(( $(cat "$WORK/clock" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$WORK/clock"; printf '2026-01-01T00:00:%02dZ' "$n"; }
@FUNCTIONS@
BLAST_RUN_STARTED=""; BLAST_RUN_RECORDED=0
blast_run_begin
echo "CALLER $(blast_caller)"
[ -z "${END_FIRST:-}" ] || blast_run_end "${RC:-0}"
exit "${RC:-0}"
'''


class BlastRunTests(unittest.TestCase):
    LIB = shell_functions(BENCH / "bench-lib.sh", "bench_warn", "bench_manifest", "bench_manifest_jq", "bench_manifest_ts")

    def hand(self, via_deploy=False, **env):
        """(rc, stdout, manifest) of the harness, run by hand or from a parent script named benchmark-deploy.sh."""
        fns = self.LIB + shell_functions(BENCH / "benchmark-blast.sh", "blast_caller", "blast_run_begin", "blast_run_end",
                                         "blast_run_exit")
        with tempfile.TemporaryDirectory(prefix="blast-runs-") as directory:
            work = Path(directory)
            (work / "manifest.json").write_text(json.dumps({"notes": [], "timestamps": {}}))
            (work / "harness.sh").write_text(BLAST_RUN_HARNESS.replace("@FUNCTIONS@", fns))
            (work / "benchmark-deploy.sh").write_text('bash "$WORK/harness.sh"\nexit $?\n')
            script = "benchmark-deploy.sh" if via_deploy else "harness.sh"
            base = {k: v for k, v in os.environ.items() if not k.startswith("BENCH_")}
            p = subprocess.run(["bash", str(work / script)], env=dict(base, WORK=str(work), **env),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            return p.returncode, p.stdout, json.loads((work / "manifest.json").read_text())

    def test_a_hand_run_records_its_entry_and_step_14(self):
        rc, out, m = self.hand(RC="0")
        self.assertEqual((rc, out), (0, "CALLER hand\n"))
        self.assertEqual(m["blast_runs"], [{"action": "run", "index": 4, "started": "2026-01-01T00:00:01Z",
                                            "ended": "2026-01-01T00:00:02Z", "rc": 0,
                                            "log": "logs/blast-run-20260101T000000Z.log"}])
        self.assertEqual(m["timestamps"], {"step_14_done": "2026-01-01T00:00:03Z"})

    def test_a_failed_run_or_a_fund_sets_no_step_14(self):
        rc, _, m = self.hand(RC="3")
        self.assertEqual(rc, 3)
        self.assertEqual([(e["action"], e["rc"]) for e in m["blast_runs"]], [("run", 3)])
        self.assertEqual(m["timestamps"], {})
        rc, _, m = self.hand(ACT="fund", RC="0")
        self.assertEqual(rc, 0)
        self.assertEqual([(e["action"], e["rc"], e["log"]) for e in m["blast_runs"]],
                         [("fund", 0, "logs/blast-fund-20260101T000000Z.log")])
        self.assertEqual(m["timestamps"], {})

    def test_one_entry_when_the_run_records_itself_before_the_exit(self):
        # on_run_exit calls blast_run_end before its exit; the EXIT trap's call then adds nothing
        rc, _, m = self.hand(RC="5", END_FIRST="1")
        self.assertEqual(rc, 5)
        self.assertEqual([e["rc"] for e in m["blast_runs"]], [5])

    def test_the_deploy_the_sequence_and_a_dry_run_record_nothing(self):
        for via_deploy, env, caller in ((True, {}, "deploy"), (False, {"BENCH_BLAST_SEQUENCE": "1"}, "sequence"),
                                        (False, {"APPLY": "0"}, "hand"), (False, {"ACT": "collect"}, "hand")):
            with self.subTest(via_deploy=via_deploy, env=env):
                rc, out, m = self.hand(via_deploy=via_deploy, RC="0", **env)
                self.assertEqual((rc, out), (0, "CALLER %s\n" % caller))
                self.assertNotIn("blast_runs", m)
                self.assertEqual(m["timestamps"], {})


class FunderSetAsideTests(unittest.TestCase):
    """D47: a fund under a new index MOVES the previous index's funder/ and meta/bench-funder/ aside (bench 5 copied
    them, so each funder-<i>-<UTC>/ held every earlier index's logs too) beside a copy of manifest.json."""

    LIB = shell_functions(BENCH / "bench-lib.sh", "bench_die", "bench_warn", "bench_manifest", "bench_manifest_jq",
                          "bench_manifest_note")
    HARNESS = r'''
set -euo pipefail
BENCH_RESULTS_DIR="$WORK/results"; BENCH_APPLY="${APPLY:-1}"; BENCH_RUN_INDEX="${IDX:-1}"
bench_now_iso() { echo 2026-01-01T00:00:00Z; }
'''

    def set_aside(self, **env):
        code = self.HARNESS + self.LIB + shell_functions(BENCH / "benchmark-blast.sh", "prev_funder_index",
                                                         "set_aside_prev_funder") + "set_aside_prev_funder\n"
        with tempfile.TemporaryDirectory(prefix="blast-funder-") as directory:
            work = Path(directory)
            results = work / "results"
            for rel in ("funder/prepare.json", "funder/bench-funder.txgen-1.log",
                        "meta/bench-funder/MACHINE_TYPE"):
                (results / rel).parent.mkdir(parents=True, exist_ok=True)
                (results / rel).write_text(rel + "\n")
            (results / "manifest.json").write_text(json.dumps({"fund": {"run_index": 0}, "notes": []}))
            rc, out, err = run_bash(code, WORK=str(work), **env)
            tree = sorted(re.sub(r"-[0-9]{8}T[0-9]{6}Z", "-<UTC>", str(f.relative_to(results)))
                          for f in results.rglob("*") if f.is_file())
            notes = json.loads((results / "manifest.json").read_text())["notes"]
            return rc, out, err, tree, notes

    def test_the_previous_index_is_moved_not_copied(self):
        rc, out, err, tree, notes = self.set_aside()
        self.assertEqual(rc, 0, err)
        self.assertEqual(tree, ["funder-0-<UTC>/funder/bench-funder.txgen-1.log",
                                "funder-0-<UTC>/funder/prepare.json", "funder-0-<UTC>/manifest.json",
                                "funder-0-<UTC>/meta/bench-funder/MACHINE_TYPE", "manifest.json"])
        self.assertIn("    mv funder\n    mv meta/bench-funder\n    cp manifest.json\n", out)
        self.assertIn("    ✓ funder output moved: ", out)
        self.assertEqual(len(notes), 1)
        self.assertRegex(notes[0], r"^funder output of index 0 moved into funder-0-[0-9]{8}T[0-9]{6}Z/ at "
                                   r"2026-01-01T00:00:00Z; funder/ now receives index 1$")

    def test_a_dry_run_or_the_same_index_moves_nothing(self):
        before = ["funder/bench-funder.txgen-1.log", "funder/prepare.json", "manifest.json",
                  "meta/bench-funder/MACHINE_TYPE"]
        rc, out, err, tree, notes = self.set_aside(APPLY="0")
        self.assertEqual((rc, tree, notes), (0, before, []), err)
        self.assertIn("    mv funder\n    mv meta/bench-funder\n    cp manifest.json\n      (dry run — nothing moved)\n", out)
        rc, out, err, tree, notes = self.set_aside(IDX="0")
        self.assertEqual((rc, tree, notes), (0, before, []), err)
        self.assertEqual(out, "    funder/ holds the output of BENCH_RUN_INDEX 0: funding it again overwrites it\n")


class PoolAtStartTests(unittest.TestCase):
    """blasts[].pool_at_start: each node's pending and queued sub-pools at start_at - 1 s, from bench-obs Prometheus
    (TN serves no txpool_* RPC), one bounded query for the fleet; a ⚠ names every node above 1,000 queued.
    Record only: a failed query records nulls and never stops the run."""

    LIB = shell_functions(BENCH / "bench-lib.sh", "bench_warn", "bench_manifest", "bench_manifest_jq", "bench_iso_from_unix")
    HARNESS = r'''
set -euo pipefail
BENCH_RESULTS_DIR="$WORK"; BENCH_PROM_NETWORK_LABEL=bench; BENCH_RUN_INDEX=3
INSTANCE_NAMES=(bench-validator-01 bench-validator-02 bench-validator-03 bench-observer-11)
bench_now_unix() { cat "$WORK/clock"; }
sleep() { echo "SLEEP $1" >> "$WORK/sleeps"; echo $(( $(cat "$WORK/clock") + $1 )) > "$WORK/clock"; }
bench_prom_query() { printf '%s\n' "$1" >> "$WORK/queries"; [ -f "$WORK/prom.json" ] || return 7; cat "$WORK/prom.json"; }
'''
    START = FAKE_NOW + 300

    def series(self, node, kind, value, **labels):
        metric = dict(__name__="reth_transaction_pool_%s_pool_transactions" % kind, node=node, network="bench", **labels)
        return {"metric": metric, "value": [self.START - 1, str(value)]}

    def pool(self, clock, prom=None):
        top = "".join(line + "\n" for line in (BENCH / "benchmark-blast.sh").read_text().splitlines()
                      if line.startswith("POOL_QUEUED_WARN="))
        code = (self.HARNESS + self.LIB + top + shell_functions(BENCH / "benchmark-blast.sh", "sleep_until", "pool_at_start")
                + 'pool_at_start %d\necho "RC $?"\n' % self.START)
        with tempfile.TemporaryDirectory(prefix="blast-pool-") as directory:
            work = Path(directory)
            (work / "manifest.json").write_text(json.dumps({"notes": [], "blast": {"run_index": 3}}))
            (work / "clock").write_text("%d\n" % clock)
            if prom is not None:
                (work / "prom.json").write_text(json.dumps(prom))
            rc, out, err = run_bash(code, WORK=str(work))
            read = lambda name: (work / name).read_text() if (work / name).exists() else ""
            return (rc, out, err, json.loads(read("manifest.json")), read("queries").splitlines(),
                    read("sleeps").splitlines())

    def test_each_node_at_start_and_a_warning_above_1000_queued(self):
        prom = {"status": "success", "data": {"resultType": "vector", "result": [
            self.series("bench-validator-01", "pending", 12), self.series("bench-validator-01", "queued", 1001),
            self.series("bench-validator-01", "queued", 3, instance="another-target"),
            self.series("bench-validator-02", "pending", 0), self.series("bench-validator-02", "queued", 1000),
            self.series("bench-observer-11", "pending", 5), self.series("bench-observer-11", "queued", 0),
            self.series("bench-validator-99", "queued", 50000)]}}
        rc, out, err, manifest, queries, sleeps = self.pool(self.START - 100, prom)
        self.assertEqual(rc, 0, err)
        self.assertEqual(manifest["blast"]["pool_at_start"], {
            "bench-validator-01": {"pending": 12, "queued": 1001}, "bench-validator-02": {"pending": 0, "queued": 1000},
            "bench-validator-03": None, "bench-observer-11": {"pending": 5, "queued": 0}})
        self.assertEqual(manifest["blast"]["run_index"], 3)
        self.assertEqual(out, "POOL_AT_START blast=3 at=2026-01-01T00:04:59Z read=3/4 queued_max=1001 (bench-validator-01) "
                              "pending_max=12 (bench-validator-01)\nRC 0\n")
        self.assertEqual(err, "⚠ POOL_AT_START blast=3: more than 1000 queued on bench-validator-01 (1001); stale "
                              "transactions from earlier blasts take queued-pool room this blast needs (blast.pool_at_start)\n")
        # read as the blast starts: the driver waits for start_at, then asks for the values one second before it
        self.assertEqual(sleeps, ["SLEEP 100"])
        self.assertEqual(queries, ['{__name__=~"reth_transaction_pool_(pending|queued)_pool_transactions",network="bench"}'
                                   ' offset 1s'])

    def test_a_late_read_still_asks_for_the_start_and_a_failed_one_records_nulls(self):
        prom = {"status": "success", "data": {"resultType": "vector", "result": [
            self.series("bench-validator-02", "queued", 7)]}}
        rc, out, err, manifest, queries, sleeps = self.pool(self.START + 20, prom)
        self.assertEqual((rc, sleeps, err), (0, [], ""))
        self.assertTrue(queries[0].endswith("} offset 21s"), queries)
        self.assertEqual(manifest["blast"]["pool_at_start"]["bench-validator-02"], {"pending": None, "queued": 7})
        rc, out, err, manifest, queries, _ = self.pool(self.START - 5)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(len(queries), 1)
        self.assertEqual(manifest["blast"]["pool_at_start"], {n: None for n in (
            "bench-validator-01", "bench-validator-02", "bench-validator-03", "bench-observer-11")})
        self.assertEqual(out, "POOL_AT_START blast=3 at=2026-01-01T00:04:59Z read=0/4 queued_max=? pending_max=?\nRC 0\n")

    def test_do_run_reads_the_pools_after_the_blasters_are_recorded(self):
        source = (BENCH / "benchmark-blast.sh").read_text()
        body = source[source.index("\ndo_run() {"):source.index("\n# ================================ collect")]
        self.assertEqual(body.count("pool_at_start "), 1)
        self.assertLess(body.index("'.blasters = $b'"), body.index('    pool_at_start "${start_at}"\n'))
        self.assertLess(body.index('    pool_at_start "${start_at}"\n'), body.index("# --- watch loop"))


class SequenceRecordTests(unittest.TestCase):
    """D45 and D42 in blasts[]: each entry's kind, the arm in force when it started (the latest param_arms[] entry whose
    begin is at or before it), and its child's own phases, plan and pools once the child recorded them."""

    LIB = SequenceTests.LIB
    sequence = SequenceTests.sequence

    CHILD = r'''
light_child() {
    local action="$1" p="$2" idx
    shift 2
    idx="${LIGHT_IDX[$p]}"
    echo "CHILD ${action} $(light_env "${p}")${*:+ $*}" >> "$WORK/children"
    archive_blast_outputs > /dev/null
    [ "${idx}" != "${NO_RECORD:-none}" ] || return 0
    bench_manifest_jq --argjson i "${idx}" '.blast = {run_index: $i, pool_at_start: {"bench-validator-01": {pending: $i, queued: 0}}}
        | .phases = [{name: "mixed", start: "real-\($i)", end: "real-end-\($i)"}]
        | .phases_planned = [{name: "mixed", start: "plan-\($i)", end: "plan-end-\($i)"}]
        | .blasters = [{name: "bench-blaster-01"}]'
}
'''
    ARMS = [{"name": "a0", "begin": "2025-12-31T23:00:00Z", "end": "2026-01-01T00:02:30Z", "via": "prestart"},
            {"name": "p2", "begin": "2026-01-01T00:02:30Z", "end": "2026-01-02T00:00:00Z"},
            {"name": "later", "begin": "2026-01-02T00:00:00Z", "end": None}, {"name": "broken"}]

    def test_each_entry_carries_its_kind_its_arm_and_its_own_record(self):
        run = self.sequence("run", manifest={"notes": [], "timestamps": {}, "param_arms": self.ARMS}, extra=self.CHILD,
                            NO_RECORD="1")
        self.assertEqual(run["rc"], 0, run["err"])
        blasts = run["manifest"]["blasts"]
        self.assertEqual([(b["index"], b["kind"]) for b in blasts], [(0, "light"), (1, "light"), (2, "load")])
        self.assertEqual([(b["started"], b["arm"]) for b in blasts],
                         [("2026-01-01T00:01:00Z", "a0"), ("2026-01-01T00:03:00Z", "p2"), ("2026-01-01T00:06:00Z", "p2")])
        for b in (blasts[0], blasts[2]):
            i = b["index"]
            self.assertEqual({k: b.get(k) for k in ("phases", "phases_planned", "pool_at_start")}, {
                "phases": [{"name": "mixed", "start": "real-%d" % i, "end": "real-end-%d" % i}],
                "phases_planned": [{"name": "mixed", "start": "plan-%d" % i, "end": "plan-end-%d" % i}],
                "pool_at_start": {"bench-validator-01": {"pending": i, "queued": 0}}})
        # index 1's child recorded nothing of its own (it stopped before record_blast): the entry has none of it
        self.assertEqual(sorted(blasts[1]), ["arm", "chaos", "ended", "index", "kind", "rc", "senders", "started", "window"])


def capture_bench5_create(ref):
    """Rewrite fixtures/blast/golden-live-create.json: <ref>'s benchmark-blast.sh (git show) through BENCH5_GLUE, every
    create on time."""
    text = subprocess.run(["git", "-C", str(REPO), "show", "%s:benchmark/benchmark-blast.sh" % ref], check=True,
                          stdout=subprocess.PIPE, universal_newlines=True).stdout
    case = LiveCase("setUp")   # any existing method name: the case is driven by hand
    case.setUp()
    try:
        (case.sb.tree / "benchmark" / "benchmark-blast.sh").write_text(text)
        run = case.live(glue=BENCH5_GLUE, fns=BENCH5_FNS)
        assert run["rc"] == 0, run["out"]
        out = {"ref": ref, "output": run["out"], "calls": sorted(run["calls"]), "blasters": run["manifest"]["blasters"]}
    finally:
        case.tearDown()
    (FIX / "golden-live-create.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--capture-bench5-create"] and len(sys.argv) == 3:
        capture_bench5_create(sys.argv[2])
    else:
        unittest.main()
