"""The bench pre-start step's launch-flag edits on a v2 node's start script, through the real library.

The pre-start script (bench-lib.sh `bench_prestart_script`, contract C3) edits the stopped node's
/usr/local/libexec/telcoin/tn-start-docker with `tnlib tn_launch_flag_set $S <flag> <value>`, where
`tnlib` runs the call in a subshell that exports DEVNET_RPC_URL (the bench guard RPC) and sources
tn-node-deployment/lib/common.sh. This suite makes the same calls, the same way, on a temporary copy
of the shared v2 fixture (fixtures/v2-node, rendered by the library at d9446f7: see its README).

Entry point. `tn_launch_flag_set` itself is called, not `_tn_launch_awk set`. Unprivileged it cannot
finish a write: `_tn_launch_write` hands the staged copy to `tn_write_root_file`, which refuses unless
every directory up to / is root-owned and not group/other-writable (`tn_root_dir_ok`; /tmp's 1777
fails it even as root) and then chowns the temp file root:GROUP. So the edit tests replace exactly
those two ownership steps (`tn_root_dir_ok` returns 0, `chown` does nothing) after sourcing; flag and
value validation, the parser, the staged-copy check, mktemp in the file's directory, chmod, the
`mv -f -T` rename and the post-write `cmp` all run for real. One test runs without the stubs and
shows the refusal (rc 3, file untouched). Observed rc table (tn_launch_flag_set at d9446f7):
0 set, 1 the flag already reads that value, 3 bad value (a space: not a single shell word) or a
refused write, 4 missing file. The bench accepts 0 or 1 and fails on anything else.

Skipped when the tn-node-deployment submodule is not checked out, when bash is missing, or on a
userland without GNU `stat -c` and `mv -T` (the library's write path needs them, as a node has).
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
LIB = REPO / "tn-node-deployment" / "lib" / "common.sh"
FIX = TESTS / "fixtures" / "v2-node"
SCRIPT_REL = "usr/local/libexec/telcoin/tn-start-docker"
GUARD_RPC = "http://127.0.0.1:9"   # BENCH_GUARD_PUBLIC_RPC (contract C5a)
DATA_BIND = " -v /var/lib/telcoin:/home/nonroot "   # what the pre-start script greps for
# benchmark/config.sh defaults for BENCH_NODE_LOG_FILTER and BENCH_NODE_LOG_MAX_FILES.
LOG_FILTER = ("info,primary::certifier=debug,primary::proposer=debug,primary=debug,"
              "primary::cert_validator=info,primary::cert_manager=info,primary::cert_fetcher=info,"
              "tn_primary::network::handler=debug")
MAX_FILES = "20"
# The pre-start edits, in the order the pre-start script makes them (METRICS_PORT 9101 from .node-meta).
EDITS = (("--http.addr", "0.0.0.0"), ("--ws.addr", "0.0.0.0"), ("--metrics", "127.0.0.1:9101"),
         ("--log.stdout.filter", LOG_FILTER), ("--log.file.filter", LOG_FILTER),
         ("--log.file.max-files", MAX_FILES))
NODE_TAIL = "--http --http.addr 127.0.0.1 --ws --ws.addr 127.0.0.1\n"
EDITED_TAIL = ("--http --http.addr 0.0.0.0 --ws --ws.addr 0.0.0.0 --metrics 127.0.0.1:9101"
               " --log.stdout.filter %s --log.file.filter %s --log.file.max-files %s\n"
               % (LOG_FILTER, LOG_FILTER, MAX_FILES))

# $1 lib, $2 1 = replace the two root-ownership steps, then the library call. tnlib is C3's helper
# (a subshell that exports the guard RPC and sources the library); it runs in a || context, as the
# pre-start script checks each rc, so the library's set -e does not end it early.
DRIVER = r'''
lib=$1 stub=$2 guard=$3
shift 3
tnlib() {
    ( export DEVNET_RPC_URL="$guard"; . "$lib"
      if [ "$stub" = 1 ]; then
          tn_root_dir_ok() { return 0; }
          chown() { return 0; }
      fi
      "$@" )
}
rc=0
tnlib "$@" || rc=$?
exit "$rc"
'''

# Re-render the three files the way the fixture was made. A `docker` shell function makes
# `command -v docker` print a bare name, which the library replaces with /usr/bin/docker (the
# node's client), whatever this host has on PATH.
RENDER = r'''
lib=$1 guard=$2 out=$3 image=$4 args=$5
export DEVNET_RPC_URL="$guard"
. "$lib"
set +e
docker() { :; }
t="$(_tn_node_env_text /ip4/0.0.0.0/udp/49590/quic-v1 /ip4/0.0.0.0/udp/49594/quic-v1)" || exit 11
printf '%s\n' "$t" > "$out/node.env"
t="$(_tn_start_script_checked docker "$image" "$args")" || exit 12
printf '%s\n' "$t" > "$out/tn-start-docker"
t="$(_tn_node_unit_text docker)" || exit 13
printf '%s\n' "$t" > "$out/telcoin.service"
'''


def _gnu_userland():
    """GNU stat -c and mv -T, which the library's write path uses (lib/common.sh _tn_launch_write)."""
    d = tempfile.mkdtemp()
    try:
        a, b = os.path.join(d, "a"), os.path.join(d, "b")
        open(a, "w").close()
        ok = subprocess.run(["stat", "-c", "%a %g", a], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
        return ok and subprocess.run(["mv", "-f", "-T", a, b], stderr=subprocess.PIPE).returncode == 0
    except OSError:
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(LIB.is_file(), "tn-node-deployment is not checked out (%s missing)" % LIB)
@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class V2LaunchEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _gnu_userland():
            raise unittest.SkipTest("needs GNU stat -c and mv -T (the library's write path, as on a node)")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-launch-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "root"
        shutil.copytree(str(FIX), str(self.root), symlinks=True)
        self.script = self.root / SCRIPT_REL
        self.original = (FIX / SCRIPT_REL).read_text()
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp), "LC_ALL": "C",
                    "TMPDIR": str(self.tmp), "TN_ROOT_PREFIX": str(self.root)}

    def lib(self, *argv, stub=True):
        """One `tnlib <argv>` call; the CompletedProcess (returncode = the library function's rc)."""
        return subprocess.run(["bash", "-c", DRIVER, "driver", str(LIB), "1" if stub else "0", GUARD_RPC]
                              + list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, env=self.env, cwd=str(self.tmp), timeout=60)

    def set_all(self):
        return [(flag, self.lib("tn_launch_flag_set", str(self.script), flag, value).returncode)
                for flag, value in EDITS]

    def test_fixture_is_the_renderers_output(self):
        """The fixture is byte-for-byte what the library at this submodule pin renders from its .node-meta."""
        out = self.tmp / "render"
        out.mkdir()
        meta = dict(line.split("=", 1) for line in (FIX / "etc/telcoin/.node-meta").read_text().splitlines())
        image = meta["DOCKER_IMAGE"]
        self.assertEqual(image.rsplit("@", 1)[1], meta["DOCKER_IMAGE_DIGEST"])
        self.assertTrue(image.startswith("us-docker.pkg.dev/telcoin-network/tn-public/adiri@sha256:"), image)
        args = "--datadir /home/nonroot --log.stdout.format log-fmt -vvv " + NODE_TAIL.strip()
        env = dict(self.env, TN_DOCKER_IDS="998:998", TN_MEMINFO=str(self.tmp / "meminfo"), SERVICE_NAME="telcoin")
        (self.tmp / "meminfo").write_text("MemTotal:       32873892 kB\n")
        p = subprocess.run(["bash", "-c", RENDER, "render", str(LIB), GUARD_RPC, str(out), image, args],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env,
                           timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        for name, rel in (("node.env", "etc/telcoin/node.env"), ("tn-start-docker", SCRIPT_REL),
                          ("telcoin.service", "etc/systemd/system/telcoin.service")):
            with self.subTest(rel=rel):
                self.assertEqual((out / name).read_text(), (FIX / rel).read_text())
        self.assertTrue(os.access(str(FIX / SCRIPT_REL), os.X_OK), "the fixture start script is not executable")

    def test_prestart_edits_set_and_read_back(self):
        self.assertEqual(self.original.count(NODE_TAIL), 1, "fixture node line changed shape")
        self.assertEqual(self.set_all(), [(flag, 0) for flag, _ in EDITS])
        for flag, value in EDITS:
            with self.subTest(flag=flag):
                p = self.lib("tn_launch_flag_get", str(self.script), flag)
                self.assertEqual((p.returncode, p.stdout), (0, value + "\n"), p.stderr)
        text = self.script.read_text()
        self.assertNotIn("--http.addr 127.0.0.1", text)
        self.assertNotIn("--ws.addr 127.0.0.1", text)
        # Only the node arguments changed: every other line, and every docker run option, as rendered.
        self.assertEqual(text, self.original.replace(NODE_TAIL, EDITED_TAIL))
        self.assertIn(DATA_BIND, text)
        self.assertIn(" --pull=never ", text)
        self.assertEqual(os.stat(str(self.script)).st_mode & 0o7777, 0o755)
        p = subprocess.run(["bash", "-n", str(self.script)], stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sorted(os.listdir(str(self.script.parent))), ["tn-start-docker"], "temp file left behind")

    def test_second_pass_is_rc_1_and_changes_nothing(self):
        self.assertEqual(self.set_all(), [(flag, 0) for flag, _ in EDITS])
        before = sha(self.script)
        self.assertEqual(self.set_all(), [(flag, 1) for flag, _ in EDITS])
        self.assertEqual(sha(self.script), before)

    def test_value_with_a_space_is_refused(self):
        before = sha(self.script)
        p = self.lib("tn_launch_flag_set", str(self.script), "--log.stdout.filter", "info primary=debug")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("not a single shell word", p.stderr)
        self.assertEqual(sha(self.script), before)

    def test_missing_file_is_rc_4(self):
        missing = str(self.script) + ".absent"
        self.assertEqual(self.lib("tn_launch_flag_set", missing, "--http.addr", "0.0.0.0").returncode, 4)
        self.assertEqual(self.lib("tn_launch_flag_get", missing, "--http.addr").returncode, 4)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root may pass tn_root_dir_ok on a private TMPDIR")
    def test_unprivileged_write_is_refused_untouched(self):
        """Why the edit tests stub the ownership steps: without them the real write path refuses."""
        before = sha(self.script)
        p = self.lib("tn_launch_flag_set", str(self.script), "--http.addr", "0.0.0.0", stub=False)
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("not a root-owned, root-only-writable directory", p.stderr)
        self.assertEqual(sha(self.script), before)
        self.assertEqual(sorted(os.listdir(str(self.script.parent))), ["tn-start-docker"])


if __name__ == "__main__":
    unittest.main()
