"""benchmark-deploy.sh on a fleet of several machine types (bench 6, unit L1d), fully offline.

What is under test: deploy step 0 and the plan (one machine type check per type over its nodes' zones, each
fallback zone against its node's own type, one CPU quota line per node, LOCAL_SSD_TOTAL_GB for a -lssd node, C4
vCPUs "not checked", the fleet line) and step 2 (one common/create-instances.sh call per machine type that is not
-lssd, with BENCH_CREATE_MACHINE_TYPE in that call's environment only; bench_create_node for each -lssd node with
create-instances.sh's argv and --maintenance-policy=TERMINATE; the stockout rounds shared; BENCH_NODE_ZONES's
zones.env and manifest.zone_overrides[]).

Every test runs the real scripts in a sandbox copy of the tree, with the REAL common/create-instances.sh (the
argv-parity test needs it). The knob-unset proof compares the changed scripts with the harness base
(`git show ae43747:<path>` for benchmark-deploy.sh, config.sh and bench-lib.sh, in a second sandbox): the dry
plan, --print-prestart for every instance, and every gcloud call of step 2. The gcloud on PATH is a recording
shim: it records each call; it answers the reads step 0 and step 2 make from its spool; it records an instance
create only in a live run (SHIM_LIVE=1, a create the deploy is meant to make) and otherwise prints REACHED and
exits 9, as it does on any other call that creates or deletes. Every dry run asserts zero REACHED. The bench-obs
VM's calls go to fixtures/node-image/stub-gcloud.sh. Tests that need the base skip when git or the commit is
missing; every test skips when the `common` submodule is not checked out.
"""
import functools
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
FIX = TESTS / "fixtures" / "node-image"
BASE_COMMIT = "ae43747"
RUN = "rtest-node-deploy"
BASE_FILES = ("benchmark/benchmark-deploy.sh", "benchmark/config.sh", "benchmark/bench-lib.sh")
# Scripts the deploy sources or runs, relative to the repo root (test_node_image.py's TREE, plus the fleet file
# and the shared create).
TREE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
        "benchmark/obs-lib.sh", "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
        "benchmark/node-image-contract.txt", "benchmark/arms/switches.tsv", "benchmark/arms/v-vote.arm",
        "benchmark/arms/final.arm", "benchmark/tools/params-apply.sh", "benchmark/node-persist-sampler.sh",
        "benchmark/tools/folio-census.py", "benchmark/consensus-parameters.yaml",
        "common/create-instances.sh", "common/wgvpn/wg-config.sh")
NODES = ["bench-validator-%02d" % n for n in range(1, 11)] + ["bench-observer-11"]
ZONES = ["us-west2-a", "europe-west2-b", "australia-southeast1-c", "asia-northeast1-b", "us-east4-b",
         "europe-west4-a", "asia-southeast1-b", "asia-east2-a", "asia-northeast3-a", "asia-south1-c", "us-west2-a"]
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Option (e) (l-common.md, the facts): three machine types, the data directory on the local SSD of the six
# -lssd validators, BENCH_MACHINE_TYPE unset so indices 7 and 8 keep the default c3-highcpu-8.
STD, LSSD, HIGHCPU = "c3-standard-8", "c3-standard-8-lssd", "c3-highcpu-8"
OPTION_E = ("0:c3-standard-8 1:c3-standard-8 2:c3-standard-8-lssd 3:c3-standard-8-lssd 4:c3-standard-8-lssd "
            "5:c3-standard-8-lssd 6:c3-standard-8-lssd 9:c3-standard-8-lssd 10:c3-standard-8")
E_TYPES = [STD, STD, LSSD, LSSD, LSSD, LSSD, LSSD, HIGHCPU, HIGHCPU, LSSD, STD]
E_ENV = {"BENCH_NODE_MACHINE_TYPES": OPTION_E, "BENCH_NODE_DATADIR_LSSD": "1", "BENCH_FLEET": "c3-lssd-e"}
KNOBS = ("BENCH_NODE_MACHINE_TYPES", "BENCH_NODE_ZONES", "BENCH_NODE_DATADIR_LSSD", "BENCH_CREATE_MACHINE_TYPE")
C4_REASON = ("C4 vCPUs count against the per-VM-family quota CPUS-PER-VM-FAMILY-per-project-region (C4), "
             "which regions describe does not list")

# The recording gcloud. SHIM_REC is its record directory (one per run); the instances it created live in
# $SHIM_SPOOL/instances/<inst> ("<zone> <machine type>"), kept from one run to the next of a test.
#   SHIM_LIVE=1                  a `beta compute instances create` is recorded (NUL-separated argv in create.*)
#                                and made; without it, it is REACHED
#   SHIM_STOCKOUT="<inst>@<zone> ..."  that create fails with gcloud's stockout text, rc 1
#   SHIM_MT_MISSING="<type>@<zone> ..." machine-types describe answers "was not found"
GCLOUD = r'''#!/bin/bash
rec="${SHIM_REC:?}"
printf '%s\n' "$*" >> "${rec}/calls.log"
case " $3 $4 " in
    *" bench-obs "*|*" bench-obs-data "*) exec bash "$(dirname "$0")/stub-gcloud.sh" "$@" ;;
esac
fmt=""; zone=""; mt=""
for a in "$@"; do
    case "${a}" in --format=*) fmt="${a#--format=}" ;; --zone=*) zone="${a#--zone=}" ;; --machine-type=*) mt="${a#--machine-type=}" ;; esac
done
spool="${SHIM_SPOOL:?}/instances"
mkdir -p "${spool}"
reached() { echo REACHED; printf '%s\n' "$*" >> "${rec}/reached.log"; exit 9; }
case "$*" in
    "auth print-access-token"*) echo fake-token ;;
    "config get-value account"*) echo bench@example.com ;;
    "beta compute instances create "*)
        [ "${SHIM_LIVE:-0}" = 1 ] || reached "$@"
        f="$(mktemp "${rec}/create.XXXXXX")"
        printf '%s\0' "$@" > "${f}"
        case " ${SHIM_STOCKOUT:-} " in
            *" $5@${zone} "*)
                printf "ERROR: (gcloud.beta.compute.instances.create) Could not fetch resource:\n - code: ZONE_RESOURCE_POOL_EXHAUSTED\n   message: The zone 'projects/x/zones/%s' does not have enough resources available to fulfill the request.\n" "${zone}" >&2
                exit 1 ;;
        esac
        printf '%s %s\n' "${zone}" "${mt}" > "${spool}/$5"
        echo "Created [https://x/zones/${zone}/instances/$5]." ;;
    "compute instances describe "*)
        inst="$4"
        if [ ! -f "${spool}/${inst}" ] || [ "$(cut -d' ' -f1 "${spool}/${inst}")" != "${zone}" ]; then
            echo "ERROR: (gcloud.compute.instances.describe) Could not fetch resource: The resource 'projects/x/zones/${zone}/instances/${inst}' was not found" >&2
            exit 1
        fi
        t="$(cut -d' ' -f2 "${spool}/${inst}")"; n="${inst##*-}"; n=$((10#${n}))
        case "${fmt}" in
            'value(name)') echo "${inst}" ;;
            'get(networkInterfaces[0].accessConfigs[0].natIP)') echo "203.0.113.${n}" ;;
            *) printf '{"name":"%s","id":"%d","tags":{"items":["bench-node"]},"labels":{"benchmark":"1"},"machineType":"https://x/zones/%s/machineTypes/%s","networkInterfaces":[{"networkIP":"198.51.100.%d","accessConfigs":[{"natIP":"203.0.113.%d"}]}],"disks":[{"boot":true,"source":"https://x/zones/%s/disks/%s"}]}\n' \
                   "${inst}" "$((4200 + n))" "${zone}" "${t}" "${n}" "${n}" "${zone}" "${inst}" ;;
        esac ;;
    "compute disks add-labels "*) ;;
    "compute disks describe "*)
        printf '{"name":"%s","sizeGb":"100","type":"https://x/diskTypes/hyperdisk-balanced","sourceImage":"https://www.googleapis.com/compute/v1/%s"}\n' "$4" "${IMAGE}" ;;
    "compute machine-types describe "*)
        case " ${SHIM_MT_MISSING:-} " in
            *" $4@${zone} "*) echo "ERROR: (gcloud.compute.machine-types.describe) Could not fetch resource: The resource 'projects/x/zones/${zone}/machineTypes/$4' was not found" >&2; exit 1 ;;
        esac
        case "${fmt}" in
            'value(name)') echo "$4" ;;
            'value(guestCpus,memoryMb)') printf '8\t32768\n' ;;
            'value(guestCpus)') echo 8 ;;
            'value(bundledLocalSsds.partitionCount)') case "$4" in c3-*-lssd) echo 2 ;; c4-*-lssd) echo 1 ;; esac ;;
        esac ;;
    "compute regions describe "*) cat "${SHIM_REGION_JSON:?}" ;;
    "beta quotas info describe "*) cat "${SHIM_QUOTA_JSON:?}" ;;
    "compute disks list "*) echo '[]' ;;
    *" create "*|*" delete "*|*" create-"*|*" delete-"*|*" add-"*|*" remove-"*|*" set-"*|*" update "*) reached "$@" ;;
esac
exit 0
'''
# $1 = the benchmark dir, $2 = deploy functions, $3 = the body (deploy's step-0 functions run alone, as
# test_node_image.py's PREFLIGHT does).
FUNCS = r'''
set -euo pipefail
source "$1/bench-lib.sh"
eval "$2"
BENCH_APPLY="${TEST_APPLY:-1}"
eval "$3"
'''
STEP0_FNS = ("node_machine_type", "machine_groups", "type_nodes", "type_zones", "node_type_checks", "fleet_zones",
             "fleet_regions", "quota_regions", "machine_type_check", "zone_fallback_zones", "zone_fallback_check",
             "machine_vcpus", "lssd_gb", "region_needs", "hdb_headroom", "quota_check")
FLEET_REGIONS = sorted({z[:-2] for z in ZONES})


def shell_functions(script, *names):
    """The named functions of <script> (a one-line function is its own line)."""
    lines = Path(script).read_text().splitlines()
    out = []
    for name in names:
        start = next(i for i, line in enumerate(lines) if line.startswith(name + "() {"))
        end = start if lines[start].rstrip().endswith("}") else lines.index("}", start)
        out.extend(lines[start:end + 1])
    return "\n".join(out) + "\n"


@functools.lru_cache(maxsize=None)
def base_file(rel):
    """<rel> at the harness base, or None when git or the commit is missing."""
    if shutil.which("git") is None:
        return None
    p = subprocess.run(["git", "-C", str(REPO), "show", "%s:%s" % (BASE_COMMIT, rel)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.stdout if p.returncode == 0 and p.stdout else None


def flag(argv, name):
    pre = "--" + name + "="
    vals = [a[len(pre):] for a in argv if a.startswith(pre)]
    return vals[0] if len(vals) == 1 else vals


class Sandbox(unittest.TestCase):
    """A copy of the tree (self.tree) with the recording gcloud on PATH; self.base_tree, on demand, the same tree
    with the three base files."""

    def setUp(self):
        if not (REPO / "common" / "create-instances.sh").is_file():
            self.skipTest("the common submodule is not checked out")
        self._tmp = tempfile.TemporaryDirectory(prefix="node-deploy-test-")
        self.root = Path(self._tmp.name)
        self.tree = self.make_tree("tree")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "gcloud").write_text(GCLOUD)
        (self.bin / "gcloud").chmod(0o755)
        shutil.copy2(str(FIX / "stub-gcloud.sh"), str(self.bin / "stub-gcloud.sh"))
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.region_json = self.root / "region.json"
        self.region_json.write_text(json.dumps({"name": "x", "quotas": [
            {"metric": m, "limit": float(v), "usage": 0.0}
            for m, v in (("C3_CPUS", 300), ("CPUS", 1500), ("IN_USE_ADDRESSES", 575), ("SSD_TOTAL_GB", 40960),
                         ("LOCAL_SSD_TOTAL_GB", 9.2e18))]}))
        self.quota_json = self.root / "quota.json"
        self.quota_json.write_text(json.dumps({"quotaId": "x", "dimensionsInfos": [
            {"dimensions": {}, "applicableLocations": FLEET_REGIONS, "details": {"value": "-1"}}]}))
        self.runs = 0
        self.rec = None

    def tearDown(self):
        self._tmp.cleanup()

    def make_tree(self, name, base=False):
        root = self.root / name
        for rel in TREE:
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / rel), str(dst))
        shutil.copytree(str(REPO / "benchmark" / "obs"), str(root / "benchmark" / "obs"))
        if base:
            for rel in BASE_FILES:
                (root / rel).write_bytes(base_file(rel))
        return root

    def need_base(self):
        if any(base_file(rel) is None for rel in BASE_FILES):
            self.skipTest("git or commit %s is missing: no base scripts to compare with" % BASE_COMMIT)
        return self.make_tree("base", base=True)

    def env(self, spool="spool", **extra):
        # Nothing from the developer's shell (BENCH_*, TN_*, ...) leaks in. <spool>: the cloud the run sees
        # (its instances, and the bench-obs VM's state for stub-gcloud.sh).
        self.runs += 1
        self.rec = self.root / ("rec-%d" % self.runs)
        self.rec.mkdir()
        env = {"SHIM_SPOOL": str(self.root / spool), "STUB_OBSVM_DIR": str(self.root / spool / "obsvm"),
               "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "BENCH_TXGEN_SHA": "abcdef1",
               "SHIM_REC": str(self.rec), "STUB_LOG": str(self.rec / "stub-obs.log"),
               "SHIM_REGION_JSON": str(self.region_json), "SHIM_QUOTA_JSON": str(self.quota_json),
               "BENCH_OBS_STARTUP_SCRIPT": str(FIX / "obs-startup-stub.sh"),
               "BENCH_OBS_DASHBOARDS_DIR": str(FIX / "obs-dashboards")}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        return env

    def run_deploy(self, tree, *args, **env):
        if tree != self.tree:
            env.setdefault("spool", "spool-" + tree.name)
        return subprocess.run(["bash", str(tree / "benchmark" / "benchmark-deploy.sh")] + list(args),
                              env=self.env(**env), cwd=str(self.root), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
                              universal_newlines=True, errors="replace")

    def plan(self, tree=None, **env):
        p = self.run_deploy(tree or self.tree, BENCH_RUN_ID=RUN, **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assert_dry(p)
        return p.stdout

    def assert_dry(self, p):
        self.assertNotIn("REACHED", p.stdout)
        self.assertFalse((self.rec / "reached.log").exists(), p.stdout)

    def calls(self):
        f = self.rec / "calls.log"
        return f.read_text().splitlines() if f.exists() else []

    def creates(self, rec=None):
        """Every recorded instance create, in no order: [argv]."""
        out = []
        for f in sorted((rec or self.rec).glob("create.*")):
            argv = f.read_text().split("\0")[:-1]
            self.assertEqual(argv[:4], ["beta", "compute", "instances", "create"], argv)
            out.append(argv)
        return out

    def run_dir(self, tree=None):
        return (tree or self.tree) / "benchmark" / "results" / RUN

    def write_manifest(self, tree=None):
        d = self.run_dir(tree)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({
            "schema": "tn-bench-manifest/v1", "run_id": RUN, "timestamps": {}, "phases": [], "chaos": [],
            "instances": [], "notes": []}, indent=2) + "\n")

    def manifest(self, tree=None):
        return json.loads((self.run_dir(tree) / "manifest.json").read_text())

    def step2(self, tree=None, **env):
        """`benchmark-deploy.sh --run RUN --yes --only 2` with instance creates allowed."""
        tree = tree or self.tree
        if not (self.run_dir(tree) / "manifest.json").exists():
            self.write_manifest(tree)
        return self.run_deploy(tree, "--run", RUN, "--yes", "--only", "2", SHIM_LIVE="1", **env)

    def funcs(self, body, *names, **env):
        fns = shell_functions(self.tree / "benchmark" / "benchmark-deploy.sh", *(names or STEP0_FNS))
        return subprocess.run(["bash", "-c", FUNCS, "benchmark-deploy.sh", str(self.tree / "benchmark"), fns, body],
                              env=self.env(BENCH_RUN_ID=RUN, **env), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
                              universal_newlines=True, errors="replace")

    def norm(self, text, tree):
        return text.replace(str(tree), "<TREE>")


class KnobUnsetTests(Sandbox):
    """Every new knob unset: the deploy behaves as at the base."""

    def test_dry_plan_equals_the_base(self):
        base = self.need_base()
        want = self.norm(self.plan(base), base)
        got = self.norm(self.plan(), self.tree)
        self.assertEqual(got, want)
        self.assertIn("  fleet    11 x c3-highcpu-8, 100 GB hyperdisk-balanced", got)
        self.assertNotIn("bench_create_node", got)
        self.assertNotIn("LOCAL_SSD_TOTAL_GB", got)

    def test_print_prestart_equals_the_base(self):
        base = self.need_base()
        for inst in NODES:
            with self.subTest(inst=inst):
                outs = []
                for tree in (base, self.tree):
                    p = self.run_deploy(tree, "--print-prestart", inst, BENCH_RUN_ID=RUN)
                    self.assertEqual(p.returncode, 0, p.stdout)
                    self.assert_dry(p)
                    self.assertEqual(self.calls(), [])
                    outs.append(self.norm(p.stdout, tree))
                self.assertEqual(outs[1], outs[0])

    def test_step2_gcloud_calls_equal_the_base(self):
        base = self.need_base()
        runs = []
        for tree in (base, self.tree):
            p = self.step2(tree)
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertNotIn("REACHED", p.stdout)
            creates = {a[4]: [self.norm(x, tree) for x in a] for a in self.creates()}
            self.assertEqual(sorted(creates), sorted(NODES))
            runs.append((creates, sorted(self.norm(c, tree) for c in self.calls()), p.stdout))
        (bc, bcalls, _), (nc, ncalls, out) = runs
        self.assertEqual(nc, bc)
        self.assertEqual(ncalls, bcalls)
        self.assertEqual(out.count("+ CONFIG_FILE="), 1)
        self.assertNotIn("BENCH_CREATE_MACHINE_TYPE", out)
        self.assertEqual({flag(a, "maintenance-policy") for a in nc.values()}, {"MIGRATE"})
        self.assertFalse((self.run_dir() / "zones.env").exists())
        self.assertNotIn("zone_overrides", self.manifest())


class OptionETests(Sandbox):
    """Option (e): c3-standard-8 (0, 1, 10), c3-highcpu-8 (7, 8), c3-standard-8-lssd (the other six)."""

    def test_plan_names_every_type_and_calls_nothing(self):
        out = self.plan(**E_ENV)
        self.assertEqual(self.calls(), [])
        self.assertIn("  fleet    11 nodes: 3 x c3-standard-8, 6 x c3-standard-8-lssd (data dir on local SSD), "
                      "2 x c3-highcpu-8, 100 GB hyperdisk-balanced (provisioned 20000 IOPS, 800 MiB/s) boot disk, ", out)
        for t, zones in ((STD, "europe-west2-b us-west2-a"), (HIGHCPU, "asia-east2-a asia-northeast3-a"),
                         (LSSD, "asia-northeast1-b asia-south1-c asia-southeast1-b australia-southeast1-c "
                                "europe-west4-a us-east4-b")):
            self.assertIn("%s must exist in every zone it is created in (%s)" % (t, zones), out)
        self.assertIn("BENCH_CREATE_MACHINE_TYPE=c3-standard-8 CONFIG_FILE=benchmark/config.sh", out)
        self.assertIn("(bench-validator-01 bench-validator-02 bench-observer-11)", out)
        self.assertIn("(bench-validator-08 bench-validator-09)", out)
        lines = [l for l in out.splitlines() if "bench_create_node " in l]
        self.assertEqual([l.split("bench_create_node ")[1].split(":")[0] for l in lines], ["2", "3", "4", "5", "6", "9"])
        self.assertIn("bench_create_node 2: bench-validator-03, c3-standard-8-lssd in australia-southeast1-c: "
                      "create-instances.sh's argv with --maintenance-policy=TERMINATE", out)

    def test_two_create_instances_calls_and_six_bench_creates(self):
        p = self.step2(**E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("REACHED", p.stdout)
        made = self.creates()
        names = [a[4] for a in made]
        self.assertEqual(sorted(names), sorted(NODES))          # eleven creates, none twice
        for argv in made:
            i = NODES.index(argv[4])
            with self.subTest(inst=argv[4]):
                self.assertEqual(flag(argv, "zone"), ZONES[i])
                self.assertEqual(flag(argv, "machine-type"), E_TYPES[i])
                self.assertEqual(flag(argv, "description"), "%s node %d" % ("observer" if i == 10 else "validator", i + 1))
                self.assertEqual(flag(argv, "maintenance-policy"), "TERMINATE" if E_TYPES[i] == LSSD else "MIGRATE")
        # Two create-instances.sh calls, each with its own type's nodes; the -lssd nodes by bench_create_node.
        self.assertEqual(re.findall(r"\+ BENCH_CREATE_MACHINE_TYPE=(\S+) CONFIG_FILE=", p.stdout), [STD, HIGHCPU])
        self.assertEqual(re.findall(r"Starting parallel instance creation for (\d+) instances", p.stdout), ["3", "2"])
        self.assertIn("+ bench_create_nodes 2 3 4 5 6 9   (-lssd:", p.stdout)
        logs = sorted(f.name.split("-2")[0] for f in (self.run_dir() / "logs").glob("create-bench-*.log"))
        self.assertEqual(logs, ["create-bench-validator-%02d" % (i + 1) for i in (2, 3, 4, 5, 6, 9)])
        self.assertEqual(len(list((self.run_dir() / "logs").glob("create-instances-*.log"))), 1)
        # Each bench create printed its argv (bench_run) into its own log before it ran.
        log = next((self.run_dir() / "logs").glob("create-bench-validator-03-*.log")).read_text()
        self.assertTrue(log.startswith("    + gcloud beta compute instances create bench-validator-03 "), log)
        m = self.manifest()
        self.assertEqual({i["name"]: i["machine_type"] for i in m["instances"]}, dict(zip(NODES, E_TYPES)))
        self.assertNotIn("zone_fallbacks", m)
        self.assertNotIn("zone_overrides", m)
        self.assertFalse((self.run_dir() / "zones.env").exists())

    def test_bench_argv_is_create_instances_argv_but_the_maintenance_policy(self):
        # The REAL create-instances.sh, narrowed to the -lssd type, records the argv it would give each node.
        real = subprocess.run(["bash", str(self.tree / "common" / "create-instances.sh")], cwd=str(self.tree),
                              env=self.env(spool="spool-real", CONFIG_FILE=str(self.tree / "benchmark" / "config.sh"),
                                           SHIM_LIVE="1",
                                           BENCH_RUN_ID=RUN, BENCH_CREATE_MACHINE_TYPE=LSSD, **E_ENV),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
                              universal_newlines=True, errors="replace")
        self.assertEqual(real.returncode, 0, real.stdout)
        want = {a[4]: a for a in self.creates()}
        self.assertEqual(sorted(want), [NODES[i] for i in (2, 3, 4, 5, 6, 9)])
        p = self.step2(**E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        got = {a[4]: a for a in self.creates() if flag(a, "maintenance-policy") == "TERMINATE"}
        self.assertEqual(sorted(got), sorted(want))
        for inst in sorted(want):
            with self.subTest(inst=inst):
                self.assertEqual(flag(want[inst], "maintenance-policy"), "MIGRATE")
                expect = ["--maintenance-policy=TERMINATE" if a == "--maintenance-policy=MIGRATE" else a
                          for a in want[inst]]
                self.assertEqual(got[inst], expect)

    def test_a_rerun_skips_every_node_that_exists(self):
        p = self.step2(**E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        p = self.step2(**E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.creates(), [])
        for i in (2, 3, 4, 5, 6, 9):
            self.assertIn("Instance %s already exists in %s — skipping." % (NODES[i], ZONES[i]), p.stdout)

    def test_the_live_guard_makes_a_dry_bench_create_print_and_call_nothing(self):
        fns = ("node_machine_type", "bench_create_node")
        p = self.funcs('bench_create_node 2; echo "RC=$?"', *fns, TEST_APPLY="0", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout, "RC=0\n")
        self.assertEqual(self.calls(), [])

    def test_one_type_for_every_node_is_one_narrowed_call(self):
        every = " ".join("%d:%s" % (i, STD) for i in range(11))
        out = self.plan(BENCH_NODE_MACHINE_TYPES=every)
        self.assertIn("  fleet    11 x c3-standard-8, 100 GB hyperdisk-balanced", out)
        p = self.step2(BENCH_NODE_MACHINE_TYPES=every)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(re.findall(r"\+ BENCH_CREATE_MACHINE_TYPE=(\S+) CONFIG_FILE=", p.stdout), [STD])
        self.assertEqual({flag(a, "machine-type") for a in self.creates()}, {STD})
        self.assertEqual(len(self.creates()), 11)


class StockoutTests(Sandbox):
    """A stockout of a -lssd node moves it to its fallback zone, and only it is created again."""

    def test_a_lssd_stockout_moves_that_node_alone(self):
        p = self.step2(SHIM_STOCKOUT="bench-validator-04@asia-northeast1-b", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        made = self.creates()
        self.assertEqual(len(made), 12, [(a[4], flag(a, "zone")) for a in made])
        again = [a for a in made if a[4] == "bench-validator-04"]
        self.assertEqual(sorted(flag(a, "zone") for a in again), ["asia-northeast1-b", "asia-northeast1-c"])
        self.assertEqual({flag(a, "maintenance-policy") for a in again}, {"TERMINATE"})
        self.assertEqual(sum(1 for a in made if a[4] != "bench-validator-04"), 10)   # no other node twice
        self.assertIn("⚠ bench-validator-04: asia-northeast1-b is out of c3-standard-8-lssd (stockout) — it moves to "
                      "asia-northeast1-c (BENCH_ZONE_FALLBACKS)", p.stdout)
        self.assertIn("❌ Error: Failed to create instance bench-validator-04 - See %s/logs/create-bench-validator-04-"
                      % self.run_dir(), p.stdout)
        m = self.manifest()
        fb = m["zone_fallbacks"]
        ts = fb[0].pop("ts")
        self.assertRegex(ts, ISO_RE)
        self.assertEqual(fb, [{"inst": "bench-validator-04", "from": "asia-northeast1-b", "to": "asia-northeast1-c",
                               "reason": "stockout"}])
        self.assertIn("zone fallback: bench-validator-04 runs in asia-northeast1-c, not asia-northeast1-b "
                      "(c3-standard-8-lssd stockout, %s); its latency is that zone's, a comparability caveat" % ts,
                      m["notes"])
        moved = list(ZONES)
        moved[3] = "asia-northeast1-c"
        self.assertEqual(m["zones_used"], dict(zip(NODES, moved)))
        self.assertIn("BENCH_ZONES_USED=%s\n" % " ".join(moved), (self.run_dir() / "zones.env").read_text())
        # Round 2: the create-instances.sh calls skip every node; bench_create_nodes creates validator-04 alone.
        self.assertEqual(p.stdout.count("+ bench_create_nodes 2 3 4 5 6 9"), 2)
        self.assertIn("Instance bench-validator-03 already exists in australia-southeast1-c — skipping.", p.stdout)

    def test_a_lssd_node_out_of_fallback_zones_stops_naming_its_type(self):
        p = self.step2(SHIM_STOCKOUT="bench-validator-04@asia-northeast1-b bench-validator-04@asia-northeast1-c",
                       BENCH_ZONE_FALLBACKS="3:asia-northeast1-c", **E_ENV)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("bench-validator-04: asia-northeast1-c is out of c3-standard-8-lssd (stockout) and "
                      "BENCH_ZONE_FALLBACKS has no zone left for index 3", p.stdout)
        self.assertNotIn("step_2_done", self.manifest()["timestamps"])

    def test_a_fallback_zone_without_the_nodes_type_is_reported_by_step_0(self):
        p = self.funcs("zone_fallback_check; echo PASSED", SHIM_MT_MISSING="c3-standard-8-lssd@asia-northeast1-c",
                       **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("PASSED", p.stdout)
        self.assertIn("⚠ zone fallback asia-northeast1-c: c3-standard-8-lssd not offered in this zone", p.stdout)
        self.assertIn("✓ c3-highcpu-8 offered in all 2 fallback zones", p.stdout)
        asked = sorted((c.split()[3], c.split()[4]) for c in self.calls() if c.startswith("compute machine-types describe "))
        self.assertEqual(asked, [(HIGHCPU, "--zone=asia-east1-a"), (HIGHCPU, "--zone=asia-northeast3-b"),
                                 (LSSD, "--zone=asia-northeast1-c"), (LSSD, "--zone=us-east4-a"),
                                 (LSSD, "--zone=us-east4-c")])
        p = self.funcs("zone_fallback_check", TEST_APPLY="0", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        self.assertEqual(p.stdout.count("(dry run — not executed)"), 2)


class QuotaTests(Sandbox):
    """Step 0's quota needs per node: a mixed C3/C4 fleet, the C4 'not checked' line, LOCAL_SSD_TOTAL_GB."""

    MIXED = {"BENCH_NODE_MACHINE_TYPES": "0:c4-standard-8 2:c3-standard-8-lssd 5:c4-standard-8-lssd",
             "BENCH_NODE_DATADIR_LSSD": "1", "BENCH_FLEET": "mixed"}

    def needs(self, apply, **env):
        body = 'for r in us-west2 australia-southeast1 europe-west4 asia-east2; do echo "$r: $(region_needs "$r" | tr "\\n" " ")"; done'
        p = self.funcs(body, TEST_APPLY=apply, **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        return dict(l.split(": ", 1) for l in p.stdout.splitlines() if ": " in l)

    def test_one_cpu_line_per_node_and_local_ssd(self):
        live = self.needs("1", **self.MIXED)
        # us-west2: validator-01 on c4-standard-8, the observer on c3-highcpu-8, bench-obs; C4 first (first seen).
        self.assertEqual(live["us-west2"], "C4_CPUS 8 C3_CPUS 8 CPUS 6 IN_USE_ADDRESSES 4 HDB_TOTAL_GB 200 "
                                           "HDB_TOTAL_IOPS 40000 HDB_TOTAL_THROUGHPUT 1600 SSD_TOTAL_GB 90 ")
        self.assertEqual(live["australia-southeast1"], "C3_CPUS 8 CPUS 2 IN_USE_ADDRESSES 2 HDB_TOTAL_GB 100 "
                         "HDB_TOTAL_IOPS 20000 HDB_TOTAL_THROUGHPUT 800 LOCAL_SSD_TOTAL_GB 750 SSD_TOTAL_GB 20 ")
        self.assertIn("C4_CPUS 8 ", live["europe-west4"])
        self.assertIn("LOCAL_SSD_TOTAL_GB 375 ", live["europe-west4"])
        self.assertNotIn("LOCAL_SSD", live["asia-east2"])
        described = [c for c in self.calls() if "bundledLocalSsds" in c]
        self.assertEqual(sorted(c.split()[3] for c in described), ["c3-standard-8-lssd", "c4-standard-8-lssd"])
        dry = self.needs("0", **self.MIXED)
        self.assertIn("C3_CPUS 8 ", dry["australia-southeast1"])      # -lssd: the vCPUs from the name
        self.assertIn("LOCAL_SSD_TOTAL_GB ? ", dry["australia-southeast1"])
        self.assertEqual(self.calls(), [])

    def test_c4_cpus_are_not_checked_with_the_reason_and_never_stop(self):
        p = self.funcs("quota_check; echo PASSED", **self.MIXED)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("PASSED", p.stdout)
        self.assertIn("⚠ us-west2: C4_CPUS not checked (need 8): %s" % C4_REASON, p.stdout)
        self.assertIn("⚠ europe-west4: C4_CPUS not checked (need 8): %s" % C4_REASON, p.stdout)
        self.assertRegex(p.stdout, r"✓ australia-southeast1 need/headroom: C3_CPUS 8/300, .*LOCAL_SSD_TOTAL_GB 750/unlimited")
        self.assertNotIn("❌", p.stdout)
        p = self.funcs("quota_check", TEST_APPLY="0", **self.MIXED)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        self.assertIn("      us-west2: C4_CPUS 8, C3_CPUS 8, CPUS 6,", p.stdout)
        self.assertIn("--format='value(bundledLocalSsds.partitionCount)'", p.stdout)


class ZoneOverrideTests(Sandbox):
    """BENCH_NODE_ZONES: zones.env before the first create, manifest.zone_overrides[] and a note, once."""

    def test_overrides_are_recorded_once_and_zones_env_is_written(self):
        env = dict(E_ENV, BENCH_NODE_ZONES="8:asia-northeast3-b")
        out = self.plan(**env)
        self.assertIn("BENCH_NODE_ZONES (8:asia-northeast3-b): first ", out)
        p = self.step2(**env)
        self.assertEqual(p.returncode, 0, p.stdout)
        m = self.manifest()
        zo = m["zone_overrides"]
        ts = zo[0].pop("ts")
        self.assertRegex(ts, ISO_RE)
        self.assertEqual(zo, [{"inst": "bench-validator-09", "from": "asia-northeast3-a", "to": "asia-northeast3-b",
                               "reason": "BENCH_NODE_ZONES"}])
        note = ("zone override: bench-validator-09 runs in asia-northeast3-b, not asia-northeast3-a (BENCH_NODE_ZONES); "
                "its latency is that zone's, a comparability caveat")
        self.assertEqual(m["notes"], [note])
        moved = list(ZONES)
        moved[8] = "asia-northeast3-b"
        self.assertEqual(m["zones_used"], dict(zip(NODES, moved)))
        made = {a[4]: a for a in self.creates()}
        self.assertEqual(flag(made["bench-validator-09"], "zone"), "asia-northeast3-b")
        zenv = (self.run_dir() / "zones.env").read_text()
        self.assertIn("BENCH_ZONES_USED=%s\n" % " ".join(moved), zenv)
        self.assertIn("(BENCH_NODE_ZONES, stockout fallback)", zenv)
        # A re-run records nothing again.
        p = self.step2(**env)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(len(self.manifest()["zone_overrides"]), 1)
        self.assertEqual(self.manifest()["notes"], [note])
        # A later script without the knob (the teardown) still sees the moved node.
        show = subprocess.run(["bash", "-c", '. "$1"; echo "ZONES ${ZONES[*]}"', "benchmark-teardown.sh",
                               str(self.tree / "benchmark" / "config.sh")],
                              env=self.env(BENCH_RUN_ID=RUN), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=120, universal_newlines=True, errors="replace")
        self.assertIn("ZONES %s\n" % " ".join(moved), show.stdout)


if __name__ == "__main__":
    unittest.main()
