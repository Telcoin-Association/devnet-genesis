"""benchmark/config.sh's per-node shape knobs (bench 6, unit L1a), fully offline.

The knobs: BENCH_NODE_MACHINE_TYPES (-> NODE_MACHINE_TYPES[]), BENCH_NODE_ZONES (rewrites ZONES[index] before
results/<run>/zones.env is read), BENCH_NODE_DATADIR_LSSD (-> NODE_DATADIR_LSSD[]) and the internal
BENCH_CREATE_MACHINE_TYPE (narrows INSTANCE_NAMES to one machine type for one common/create-instances.sh call).

Every test sources a sandbox copy of the repo-root config.sh and benchmark/config.sh with a clean environment.
The knob-unset proof compares the changed file with the base one (`git show ae43747:benchmark/config.sh`, written
beside it in the same sandbox directory): `declare -p` of every variable, the e2 x hyperdisk refusal, and the gcloud
argv of the REAL common/create-instances.sh run with CONFIG_FILE at each. The gcloud on PATH is a recording shim: it
answers "not found" to `instances describe`, records `instances create` and prints REACHED and exits 9 on anything
else that creates or deletes. Tests that need the base skip when git or that commit is missing; the create tests skip
when the `common` submodule is not checked out.
"""
import functools
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
BASE_COMMIT = "ae43747"
RUN_ID = "rtest-node-shapes"
CREATE = REPO / "common" / "create-instances.sh"
WG_CONFIG = REPO / "common" / "wgvpn" / "wg-config.sh"

# The orchestrator's option (e) (l-common.md, the facts): three machine types, the data directory on the local SSD
# of the six -lssd validators, BENCH_MACHINE_TYPE unset so indices 7 and 8 keep the default c3-highcpu-8.
OPTION_E = ("0:c3-standard-8 1:c3-standard-8 2:c3-standard-8-lssd 3:c3-standard-8-lssd 4:c3-standard-8-lssd "
            "5:c3-standard-8-lssd 6:c3-standard-8-lssd 9:c3-standard-8-lssd 10:c3-standard-8")
STD, LSSD, HIGHCPU = "c3-standard-8", "c3-standard-8-lssd", "c3-highcpu-8"
E_TYPES = [STD, STD, LSSD, LSSD, LSSD, LSSD, LSSD, HIGHCPU, HIGHCPU, LSSD, STD]
E_DATADIR = ["0", "0", "1", "1", "1", "1", "1", "0", "0", "1", "0"]
E_ENV = {"BENCH_NODE_MACHINE_TYPES": OPTION_E, "BENCH_NODE_DATADIR_LSSD": "1", "BENCH_FLEET": "c3-lssd-e"}
KNOBS = ("BENCH_NODE_MACHINE_TYPES", "BENCH_NODE_ZONES", "BENCH_NODE_DATADIR_LSSD", "BENCH_CREATE_MACHINE_TYPE")
NEW_ARRAYS = ("NODE_MACHINE_TYPES", "NODE_DATADIR_LSSD")
# Bench 7's two start knobs are assigned by config.sh itself (validated 0|1, default 1), so they are variables the
# base file does not have.
NEW_SCALARS = ("BENCH_NODE_ALLOW_FAUCET_ON_CHAIN", "BENCH_NODE_RESERVE_PORTS")
NEW_NAMES = NEW_ARRAYS + NEW_SCALARS
# Bench 7's switch list (arms/switches.tsv, seven keys) replaced bench 6's twelve, so these two values differ from the
# base on purpose; test_node_image.Bench6KnobTests and test_params_apply.KeyListTests pin them to the tsv.
CHANGED_VALUES = ("BENCH_NODE_SWITCH_KEYS", "BENCH_NODE_PARAM_KEYS")
# Bash's own variables that change from one shell to the next (or with the sourced file's name).
VOLATILE = {"BASHPID", "BASH_ARGC", "BASH_ARGV", "BASH_ARGV0", "BASH_COMMAND", "BASH_LINENO", "BASH_MONOSECONDS",
            "BASH_SOURCE", "BASH_SUBSHELL", "EPOCHREALTIME", "EPOCHSECONDS", "FUNCNAME", "HISTCMD", "LINENO",
            "PIPESTATUS", "PPID", "RANDOM", "SECONDS", "SRANDOM", "_"}

# $1 = the config file. Every variable, one `declare -p` per NUL-terminated record.
DUMP = r'''
set -euo pipefail
. "$1"
for _shape_name in $(compgen -v); do declare -p "${_shape_name}"; printf '\0'; done
'''
# $1 = the config file. Each fleet array as "<array> <index> <value>" lines (sparse arrays keep their indices).
SHOW = r'''
set -euo pipefail
. "$1"
for i in "${!INSTANCE_NAMES[@]}"; do printf 'INSTANCE_NAMES %s %s\n' "$i" "${INSTANCE_NAMES[$i]}"; done
for i in "${!ZONES[@]}"; do printf 'ZONES %s %s\n' "$i" "${ZONES[$i]}"; done
for i in "${!NODE_ROLES[@]}"; do printf 'NODE_ROLES %s %s\n' "$i" "${NODE_ROLES[$i]}"; done
for i in "${!NODE_NAMES[@]}"; do printf 'NODE_NAMES %s %s\n' "$i" "${NODE_NAMES[$i]}"; done
for i in "${!EXECUTION_ADDRESSES[@]}"; do printf 'EXECUTION_ADDRESSES %s %s\n' "$i" "${EXECUTION_ADDRESSES[$i]}"; done
for i in "${!NODE_MACHINE_TYPES[@]}"; do printf 'NODE_MACHINE_TYPES %s %s\n' "$i" "${NODE_MACHINE_TYPES[$i]}"; done
for i in "${!NODE_DATADIR_LSSD[@]}"; do printf 'NODE_DATADIR_LSSD %s %s\n' "$i" "${NODE_DATADIR_LSSD[$i]}"; done
printf 'SCALAR MACHINE_TYPE %s\n' "${MACHINE_TYPE}"
printf 'SCALAR BENCH_FLEET %s\n' "${BENCH_FLEET}"
echo LOADED
'''
# $1 = the config file; prints LOADED only when it sourced cleanly.
LOAD = r'''
set -euo pipefail
. "$1"
echo LOADED
'''
# The recording gcloud. SHIM_REC is its record directory.
GCLOUD = r'''#!/bin/bash
rec="${SHIM_REC:?}"
printf '%s\n' "$*" >> "${rec}/calls.log"
case " $* " in
    *" auth print-access-token "*) echo fake-token; exit 0 ;;
    *" compute instances describe "*)
        echo "ERROR: (gcloud.compute.instances.describe) Could not fetch resource: The resource was not found" >&2
        exit 1 ;;
    *" compute instances create "*)
        f="$(mktemp "${rec}/create.XXXXXX")"
        printf '%s\0' "$@" > "${f}"
        exit 0 ;;
    *" create "*|*" delete "*|*" create-"*|*" delete-"*|*" add-"*|*" remove-"*|*" set-"*|*" update "*)
        echo REACHED
        printf '%s\n' "$*" >> "${rec}/reached.log"
        exit 9 ;;
esac
exit 0
'''


@functools.lru_cache(maxsize=None)
def base_config():
    """benchmark/config.sh at the harness base, or None when git or the commit is missing."""
    if shutil.which("git") is None:
        return None
    p = subprocess.run(["git", "-C", str(REPO), "show", BASE_COMMIT + ":benchmark/config.sh"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.stdout if p.returncode == 0 and p.stdout else None


def parse_show(text):
    arrays, scalars = {}, {}
    for line in text.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "SCALAR":
            scalars[parts[1]] = parts[2]
        elif len(parts) == 3 and parts[1].isdigit():
            arrays.setdefault(parts[0], {})[int(parts[1])] = parts[2]
    return arrays, scalars


def dense(values):
    return {i: v for i, v in enumerate(values)}


class Sandbox(unittest.TestCase):
    """A copy of the two config files (plus the base beside them) and, when present, common/create-instances.sh."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="node-shapes-test-")
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        (self.tree / "benchmark").mkdir(parents=True)
        shutil.copy2(str(REPO / "config.sh"), str(self.tree / "config.sh"))
        shutil.copy2(str(BENCH / "config.sh"), str(self.tree / "benchmark" / "config.sh"))
        shutil.copy2(str(BENCH / "consensus-parameters.yaml"), str(self.tree / "benchmark" / "consensus-parameters.yaml"))
        self.cfg = self.tree / "benchmark" / "config.sh"
        self.base = self.tree / "benchmark" / "config-base.sh"
        if base_config() is not None:
            self.base.write_bytes(base_config())
        if CREATE.is_file() and WG_CONFIG.is_file():
            (self.tree / "common" / "wgvpn").mkdir(parents=True)
            shutil.copy2(str(CREATE), str(self.tree / "common" / "create-instances.sh"))
            shutil.copy2(str(WG_CONFIG), str(self.tree / "common" / "wgvpn" / "wg-config.sh"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "gcloud").write_text(GCLOUD)
        (self.bin / "gcloud").chmod(0o755)
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.runs = 0

    def tearDown(self):
        self._tmp.cleanup()

    def need_base(self):
        if not self.base.is_file():
            self.skipTest("git or commit %s is missing: no base config.sh to compare with" % BASE_COMMIT)

    def need_create(self):
        if not (self.tree / "common" / "create-instances.sh").is_file():
            self.skipTest("the common submodule is not checked out")

    def env(self, **extra):
        # Nothing from the developer's shell (BENCH_*, TN_*, ...) leaks in.
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root), "TMPDIR": str(self.tmpdir), "BENCH_RUN_ID": RUN_ID,
               "BENCH_TXGEN_SHA": "abcdef1"}
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        return env

    def bash(self, script, cfg=None, caller="benchmark-deploy.sh", **env):
        # $0 = an allowlisted caller: config.sh only loads for those.
        return subprocess.run(["bash", "-c", script, caller, str(cfg or self.cfg)], env=self.env(**env),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=120, universal_newlines=True, errors="replace")

    def show(self, caller="benchmark-deploy.sh", **env):
        p = self.bash(SHOW, caller=caller, **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("LOADED", p.stdout)
        return parse_show(p.stdout)

    def dump(self, cfg, **env):
        p = subprocess.run(["bash", "-c", DUMP, "benchmark-deploy.sh", str(cfg)], env=self.env(**env),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=120, universal_newlines=True, errors="replace")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = {}
        for rec in p.stdout.split("\0"):
            rec = rec.strip("\n")
            if not rec:
                continue
            m = re.match(r"declare -\S+ ([A-Za-z_][A-Za-z0-9_]*)", rec)
            self.assertIsNotNone(m, rec)
            out[m.group(1)] = rec
        return {k: v for k, v in out.items() if k not in VOLATILE}

    def create(self, cfg=None, **env):
        """Run the real common/create-instances.sh; returns ({instance: argv}, stdout)."""
        self.runs += 1
        rec = self.root / ("rec-%d" % self.runs)
        rec.mkdir()
        p = subprocess.run(["bash", str(self.tree / "common" / "create-instances.sh")], cwd=str(self.tree),
                           env=self.env(CONFIG_FILE=str(cfg or self.cfg), SHIM_REC=str(rec), **env),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=180, universal_newlines=True, errors="replace")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("REACHED", p.stdout)
        self.assertFalse((rec / "reached.log").exists(), p.stdout)
        out = {}
        for f in sorted(rec.glob("create.*")):
            argv = f.read_text().split("\0")[:-1]
            self.assertEqual(argv[:4], ["beta", "compute", "instances", "create"], argv)
            self.assertNotIn(argv[4], out, "two creates for one instance")
            out[argv[4]] = argv
        return out, p.stdout

    def write_zones_env(self, zones):
        run = self.tree / "benchmark" / "results" / RUN_ID
        run.mkdir(parents=True, exist_ok=True)
        (run / "zones.env").write_text("# step 2\nBENCH_ZONES_USED=%s\n" % " ".join(zones))


def flag(argv, name):
    pre = "--" + name + "="
    vals = [a[len(pre):] for a in argv if a.startswith(pre)]
    return vals[0] if len(vals) == 1 else vals


class KnobUnsetTests(Sandbox):
    """Every knob unset: benchmark/config.sh behaves as at the base."""

    def test_declare_p_equals_the_base(self):
        self.need_base()
        variants = (("unset", {}), ("empty", {k: "" for k in KNOBS}), ("datadir-0", {"BENCH_NODE_DATADIR_LSSD": "0"}),
                    ("other type", {"BENCH_MACHINE_TYPE": "c3-standard-8"}))
        for label, env in variants:
            with self.subTest(variant=label):
                base, changed = self.dump(self.base, **env), self.dump(self.cfg, **env)
                for name in NEW_NAMES:
                    self.assertNotIn(name, base)
                    self.assertIn(name, changed)
                self.assertEqual(sorted(set(changed) - set(NEW_NAMES)), sorted(base))
                for name in sorted(base):
                    if name not in CHANGED_VALUES:
                        self.assertEqual(changed[name], base[name], name)
                arrays, scalars = self.show(**env)
                mt = env.get("BENCH_MACHINE_TYPE", HIGHCPU)
                self.assertEqual(scalars["MACHINE_TYPE"], mt)
                self.assertEqual(arrays["NODE_MACHINE_TYPES"], dense([mt] * 11))
                self.assertEqual(arrays["NODE_DATADIR_LSSD"], dense(["0"] * 11))
                self.assertEqual(sorted(arrays["INSTANCE_NAMES"]), list(range(11)))

    def test_e2_hyperdisk_refusal_is_the_base_message(self):
        self.need_base()
        for env in ({"BENCH_MACHINE_TYPE": "e2-standard-4"}, {"BENCH_MACHINE_TYPE": "n1-standard-8"},
                    {"BENCH_MACHINE_TYPE": "e2-standard-4", "BENCH_NODE_DISK_TYPE": "pd-ssd"}):
            with self.subTest(env=env):
                base, changed = self.bash(LOAD, cfg=self.base, **env), self.bash(LOAD, **env)
                self.assertEqual((changed.returncode, changed.stdout), (base.returncode, base.stdout))

    def test_e2_hyperdisk_refusal_message(self):
        p = self.bash(LOAD, BENCH_MACHINE_TYPE="e2-standard-4")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(p.stdout, "❌ benchmark/config.sh: MACHINE_TYPE='e2-standard-4' cannot attach a hyperdisk-balanced "
                                   "disk; set BENCH_NODE_DISK_TYPE=pd-ssd.\n")

    def test_no_scratch_variable_survives(self):
        # The file's own _bench_* scratch is unset at its end, with every knob unset and with every knob set.
        script = LOAD + 'compgen -v _bench || true\n'
        for env in ({}, dict(E_ENV, BENCH_NODE_ZONES="4:europe-west1-b", BENCH_CREATE_MACHINE_TYPE=LSSD)):
            with self.subTest(knobs=bool(env)):
                p = self.bash(script, caller="create-instances.sh", **env)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertEqual(p.stdout, "LOADED\n")

    def test_create_argv_equals_the_base(self):
        self.need_base()
        self.need_create()
        base, _ = self.create(cfg=self.base)
        changed, _ = self.create()
        arrays, _ = self.show()
        self.assertEqual(sorted(base), sorted(arrays["INSTANCE_NAMES"].values()))
        self.assertEqual(changed, base)


class RefusalTests(Sandbox):
    """Each refusal on its own: exit 1, the ❌ benchmark/config.sh line, nothing loaded."""

    def refused(self, phrase, **env):
        p = self.bash(LOAD, **env)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("❌ benchmark/config.sh: " + phrase, p.stdout)
        self.assertNotIn("LOADED", p.stdout)

    def loads(self, **env):
        p = self.bash(LOAD, **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("LOADED", p.stdout)

    def test_machine_types(self):
        k = "BENCH_NODE_MACHINE_TYPES"
        cases = (
            ("1:c3*", "BENCH_NODE_MACHINE_TYPES='1:c3*' holds a glob character."),
            ("1:c3-standard-[8]", "BENCH_NODE_MACHINE_TYPES='1:c3-standard-[8]' holds a glob character."),
            ("c3-standard-8", "BENCH_NODE_MACHINE_TYPES item 'c3-standard-8': not <index>:<machine-type>."),
            ("3:", "BENCH_NODE_MACHINE_TYPES item '3:': not <index>:<machine-type>."),
            ("x:c3-standard-8", "BENCH_NODE_MACHINE_TYPES item 'x:c3-standard-8': index 'x' is not a number."),
            (":c3-standard-8", "BENCH_NODE_MACHINE_TYPES item ':c3-standard-8': index '' is not a number."),
            ("01:c3-standard-8", "BENCH_NODE_MACHINE_TYPES item '01:c3-standard-8': index '01' is not a number."),
            ("11:c3-standard-8", "BENCH_NODE_MACHINE_TYPES item '11:c3-standard-8': index 11 is past the last node (10)."),
            ("2:c3-standard-8 2:c3-standard-8-lssd",
             "BENCH_NODE_MACHINE_TYPES item '2:c3-standard-8-lssd': index 2 appears twice (give each node one item)."),
        )
        for value, phrase in cases:
            with self.subTest(value=value):
                self.refused(phrase, **{k: value})
        for t in ("C3-standard-8", "-c3-standard-8", "^c3-standard-8", "c3-standard-8-", "c", "c3_standard_8",
                  "c3.standard", "3c-standard-8", "c3-standard-8:x"):
            with self.subTest(type=t):
                self.refused("BENCH_NODE_MACHINE_TYPES item '2:%s': '%s' is not a machine type "
                             "(lower-case letters, digits and -, e.g. c3-standard-8-lssd)." % (t, t), **{k: "2:" + t})
        for value in ("0:c3-standard-8", "10:c4-standard-8-lssd", " 3:c3-standard-8  4:n4-standard-8 ", "2:c3"):
            with self.subTest(ok=value):
                self.loads(**{k: value})

    def test_e2_n1_hyperdisk_per_type(self):
        k = "BENCH_NODE_MACHINE_TYPES"
        for t in ("e2-standard-4", "n1-standard-8"):
            with self.subTest(type=t):
                self.refused("BENCH_NODE_MACHINE_TYPES type '%s' cannot attach a hyperdisk-balanced disk; "
                             "set BENCH_NODE_DISK_TYPE=pd-ssd." % t, **{k: "1:c3-standard-8 3:%s" % t})
                self.refused("BENCH_NODE_MACHINE_TYPES type '%s' cannot attach a hyperdisk-extreme disk; " % t,
                             BENCH_NODE_DISK_TYPE="hyperdisk-extreme", BENCH_NODE_DISK_IOPS="5000", **{k: "3:" + t})
                self.loads(BENCH_NODE_DISK_TYPE="pd-ssd", **{k: "3:" + t})
        # MACHINE_TYPE keeps its own message when a node still uses it.
        self.refused("MACHINE_TYPE='e2-standard-4' cannot attach", BENCH_MACHINE_TYPE="e2-standard-4",
                     **{k: "3:c3-standard-8"})

    def test_zones(self):
        k = "BENCH_NODE_ZONES"
        cases = (
            ("4:us-east4-?", "BENCH_NODE_ZONES='4:us-east4-?' holds a glob character."),
            ("us-east4-c", "BENCH_NODE_ZONES item 'us-east4-c': not <index>:<zone>."),
            ("4:", "BENCH_NODE_ZONES item '4:': not <index>:<zone>."),
            ("x:us-east4-c", "BENCH_NODE_ZONES item 'x:us-east4-c': index 'x' is not a number."),
            ("04:us-east4-c", "BENCH_NODE_ZONES item '04:us-east4-c': index '04' is not a number."),
            ("11:us-east4-c", "BENCH_NODE_ZONES item '11:us-east4-c': index 11 is past the last node (10)."),
            ("4:us-east4-c 4:us-east4-a",
             "BENCH_NODE_ZONES item '4:us-east4-a': index 4 appears twice (give each node one item)."),
        )
        for value, phrase in cases:
            with self.subTest(value=value):
                self.refused(phrase, **{k: value})
        for z in ("us-east4", "US-east4-c", "us-east4-cc", "useast4-c", "us-east-c", "-us-east4-c", "us-east4-c-",
                  "us-east4-c,us-east4-a", "us_east4-c", "us-east4-1"):
            with self.subTest(zone=z):
                self.refused("BENCH_NODE_ZONES item '4:%s': '%s' is not a zone name (<region>-<letter>, e.g. us-east4-c)."
                             % (z, z), **{k: "4:" + z})
        self.loads(**{k: "4:northamerica-northeast1-b 0:us-west1-a"})

    def test_datadir_lssd(self):
        k = "BENCH_NODE_DATADIR_LSSD"
        for value in ("2", "yes", "true", "01", " 1"):
            with self.subTest(value=value):
                self.refused("BENCH_NODE_DATADIR_LSSD='%s' must be 0 or 1." % value, **{k: value})
        no_lssd = "BENCH_NODE_DATADIR_LSSD=1 but no node has a local SSD: no machine type ends in -lssd"
        self.refused(no_lssd, BENCH_FLEET="x", **{k: "1"})
        self.refused(no_lssd, BENCH_FLEET="x", BENCH_NODE_MACHINE_TYPES="2:c3-standard-8 3:c3-lssd-8", **{k: "1"})
        no_fleet = "BENCH_NODE_DATADIR_LSSD=1 needs BENCH_FLEET set by the caller"
        self.refused(no_fleet, BENCH_NODE_MACHINE_TYPES="2:c3-standard-8-lssd", **{k: "1"})
        self.refused(no_fleet, BENCH_NODE_MACHINE_TYPES="2:c3-standard-8-lssd", BENCH_FLEET="", **{k: "1"})
        self.refused(no_fleet, BENCH_MACHINE_TYPE="c3-standard-8-lssd", **{k: "1"})
        self.loads(BENCH_MACHINE_TYPE="c3-standard-8-lssd", BENCH_FLEET="c3-lssd", **{k: "1"})

    def test_create_machine_type(self):
        self.refused("BENCH_CREATE_MACHINE_TYPE='c3-highcpu-8' is set but BENCH_NODE_MACHINE_TYPES is empty; "
                     "it narrows a fleet of several machine types to one (deploy step 2 sets it).",
                     BENCH_CREATE_MACHINE_TYPE=HIGHCPU)
        for t in ("c4-standard-8", "c3-standard", "c3-standard-8 ", "*"):
            with self.subTest(type=t):
                self.refused("BENCH_CREATE_MACHINE_TYPE='%s' is no node's machine type (NODE_MACHINE_TYPES: %s)."
                             % (t, " ".join(E_TYPES)), BENCH_CREATE_MACHINE_TYPE=t, **E_ENV)


class OptionETests(Sandbox):
    """Option (e): three machine types, six local-SSD data directories, no zone moved."""

    def test_arrays(self):
        full, _ = self.show()
        arrays, scalars = self.show(**E_ENV)
        self.assertEqual(arrays["NODE_MACHINE_TYPES"], dense(E_TYPES))
        self.assertEqual(arrays["NODE_DATADIR_LSSD"], dense(E_DATADIR))
        self.assertEqual(scalars["MACHINE_TYPE"], HIGHCPU)
        self.assertEqual(scalars["BENCH_FLEET"], "c3-lssd-e")
        for name in ("INSTANCE_NAMES", "ZONES", "NODE_ROLES", "NODE_NAMES", "EXECUTION_ADDRESSES"):
            self.assertEqual(arrays[name], full[name], name)

    def test_lssd_nodes_with_the_knob_at_0(self):
        # Allowed: the -lssd nodes keep their data directory on the boot disk; the label is derived as usual.
        env = dict(E_ENV)
        del env["BENCH_NODE_DATADIR_LSSD"], env["BENCH_FLEET"]
        arrays, scalars = self.show(**env)
        self.assertEqual(arrays["NODE_MACHINE_TYPES"], dense(E_TYPES))
        self.assertEqual(arrays["NODE_DATADIR_LSSD"], dense(["0"] * 11))
        self.assertEqual(scalars["BENCH_FLEET"], "c3-hdb")
        arrays, _ = self.show(BENCH_NODE_DATADIR_LSSD="0", **env)
        self.assertEqual(arrays["NODE_DATADIR_LSSD"], dense(["0"] * 11))


MIXED = {"BENCH_MACHINE_TYPE": "c3-standard-8",
         "BENCH_NODE_MACHINE_TYPES": "2:c4-standard-8-lssd 4:c4-standard-8 9:c3-standard-8-lssd",
         "BENCH_NODE_ZONES": "4:europe-west1-b", "BENCH_NODE_DATADIR_LSSD": "1", "BENCH_FLEET": "c3c4-mix"}
MIXED_TYPES = [STD, STD, "c4-standard-8-lssd", STD, "c4-standard-8", STD, STD, STD, STD, LSSD, STD]


class MixedFleetTests(Sandbox):
    """A mixed C3/C4 fleet with one validator moved by BENCH_NODE_ZONES."""

    def test_arrays_and_the_move(self):
        full, _ = self.show()
        arrays, scalars = self.show(**MIXED)
        self.assertEqual(arrays["NODE_MACHINE_TYPES"], dense(MIXED_TYPES))
        self.assertEqual(arrays["NODE_DATADIR_LSSD"], dense(["0", "0", "1", "0", "0", "0", "0", "0", "0", "1", "0"]))
        self.assertEqual(scalars["MACHINE_TYPE"], STD)
        zones = dict(full["ZONES"])
        zones[4] = "europe-west1-b"
        self.assertEqual(arrays["ZONES"], zones)
        self.assertEqual(arrays["INSTANCE_NAMES"], full["INSTANCE_NAMES"])

    def test_the_moved_node_is_created_in_its_new_zone(self):
        self.need_create()
        made, _ = self.create(BENCH_CREATE_MACHINE_TYPE="c4-standard-8", **MIXED)
        self.assertEqual(sorted(made), ["bench-validator-05"])
        argv = made["bench-validator-05"]
        self.assertEqual(flag(argv, "zone"), "europe-west1-b")
        self.assertEqual(flag(argv, "machine-type"), "c4-standard-8")
        self.assertEqual(flag(argv, "description"), "validator node 5")


class ZonesEnvTests(Sandbox):
    """results/<run>/zones.env is read after BENCH_NODE_ZONES and still wins."""

    def test_zones_env_wins(self):
        full, _ = self.show()
        zones = [full["ZONES"][i] for i in range(11)]
        # Step 2 wrote zones.env from the overridden ZONES, then a stockout moved validator-08: both moves stay.
        both = list(zones)
        both[4], both[7] = "europe-west1-b", "asia-east1-a"
        self.write_zones_env(both)
        arrays, _ = self.show(BENCH_NODE_ZONES="4:europe-west1-b")
        self.assertEqual(arrays["ZONES"], dense(both))
        # A later stockout moved the overridden node itself: zones.env's zone, not the override's.
        later = list(both)
        later[4] = "europe-west1-c"
        self.write_zones_env(later)
        arrays, _ = self.show(BENCH_NODE_ZONES="4:europe-west1-b")
        self.assertEqual(arrays["ZONES"], dense(later))


class CreateNarrowTests(Sandbox):
    """BENCH_CREATE_MACHINE_TYPE narrows INSTANCE_NAMES to one machine type, every index keeping its place."""

    def test_sparse_instance_names(self):
        full, _ = self.show(**E_ENV)
        groups = {}
        for t in (STD, LSSD, HIGHCPU):
            with self.subTest(type=t):
                arrays, scalars = self.show(caller="create-instances.sh", BENCH_CREATE_MACHINE_TYPE=t, **E_ENV)
                want = [i for i, x in enumerate(E_TYPES) if x == t]
                self.assertEqual(sorted(arrays["INSTANCE_NAMES"]), want)
                self.assertEqual(scalars["MACHINE_TYPE"], t)
                for i in want:
                    self.assertEqual(arrays["INSTANCE_NAMES"][i], full["INSTANCE_NAMES"][i])
                for name in ("ZONES", "NODE_ROLES", "NODE_NAMES", "EXECUTION_ADDRESSES", "NODE_MACHINE_TYPES",
                             "NODE_DATADIR_LSSD"):
                    self.assertEqual(arrays[name], full[name], name)
                groups[t] = set(want)
        self.assertEqual(groups[HIGHCPU], {7, 8})
        self.assertEqual(sum(len(g) for g in groups.values()), 11)
        self.assertEqual(set().union(*groups.values()), set(range(11)))

    def test_create_instances_per_type(self):
        self.need_create()
        base, _ = self.create()   # every knob unset: the whole fleet on MACHINE_TYPE
        full, _ = self.show(**E_ENV)
        names = full["INSTANCE_NAMES"]
        seen = {}
        for t in (STD, LSSD, HIGHCPU):
            with self.subTest(type=t):
                made, out = self.create(BENCH_CREATE_MACHINE_TYPE=t, **E_ENV)
                want = [i for i, x in enumerate(E_TYPES) if x == t]
                self.assertEqual(sorted(made), sorted(names[i] for i in want))
                self.assertIn("Starting parallel instance creation for %d instances..." % len(want), out)
                for i in want:
                    argv = made[names[i]]
                    self.assertEqual(flag(argv, "zone"), full["ZONES"][i])
                    self.assertEqual(flag(argv, "machine-type"), t)
                    self.assertEqual(flag(argv, "description"), "%s node %d" % (full["NODE_ROLES"][i], i + 1))
                    self.assertIn("EXECUTION_ADDRESS=%s,NODE_NAME=%s," % (full["EXECUTION_ADDRESSES"][i],
                                                                         full["NODE_NAMES"][i]), flag(argv, "metadata"))
                    # The knob-unset create of the same node, with only the machine type changed.
                    expect = ["--machine-type=" + t if a == "--machine-type=" + HIGHCPU else a for a in base[names[i]]]
                    self.assertEqual(argv, expect)
                for name in made:
                    self.assertNotIn(name, seen, "created twice")
                    seen[name] = t
        self.assertEqual(sorted(seen), sorted(names.values()))


if __name__ == "__main__":
    unittest.main()
