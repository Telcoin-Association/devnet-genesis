"""Bench 6: the pre-start host probe and the host steps of bench-lib.sh, offline.

bench_host_probe_script and bench_host_step_script run on a fake node root (Host): /proc, /sys and
/etc files under a temporary directory, the scripts' absolute paths relocated there, stub findmnt,
lsblk and fincore first on PATH (fixtures/host-probe/stub-answer.sh: each answers from a state file
and logs its argv), and the real python3. Nothing here reads or writes the real /proc or /sys: a
script that still names either after relocation is refused before it runs. The pre-start script's
host steps (BENCH_NODE_READ_AHEAD_KB, BENCH_NODE_EVICT_MDBX) run on test_node_image's sandbox v2 node
with the same relocation and stubs. The records and the fleet summary are fed session text and
manifests. The python helpers are also loaded from the printed program, for docker's memory values
and for a read-back that differs from the write (a sandbox cannot stage one).

With both knobs unset (or off) the pre-start script must stay byte for byte what the unmodified
bench-lib.sh printed: fixtures/host-probe/prestart-golden-*.txt were rendered from it, with
TN_NODE_SCRIPTS_REF replaced by a placeholder.
"""
import ctypes
import io
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_node_image as tni

TESTS = Path(__file__).resolve().parent
FIX = TESTS / "fixtures" / "host-probe"
MANIFEST_FIELDS = tni.BENCH / "arms" / "MANIFEST-FIELDS.md"
INST = "bench-validator-01"
PS = mmap.PAGESIZE

KERNEL = "6.8.0-1015-gcp"
CMDLINE = "BOOT_IMAGE=/boot/vmlinuz-6.8.0-1015-gcp root=PARTUUID=0f0e0d0c-01 ro console=ttyS0,115200"
VM = {"dirty_ratio": 20, "dirty_background_ratio": 10, "dirty_bytes": 0, "dirty_background_bytes": 0,
      "dirty_expire_centisecs": 3000, "dirty_writeback_centisecs": 500, "swappiness": 60, "vfs_cache_pressure": 100}
FINDMNT = {"filesystems": [{"source": "/dev/nvme0n1p1", "fstype": "ext4",
                            "options": "rw,relatime,discard,errors=remount-ro,commit=30"}]}
LSBLK = {"blockdevices": [{"pkname": "nvme0n1", "kname": "nvme0n1p1"}]}
V2_MEMORY = 28893 * 1024 * 1024    # fixtures/v2-node tn-start-docker: --memory 28893m

# Paths the host scripts read, moved under the fake root (one pass; a path is moved only where it starts).
RELOCATED = ("/proc/", "/sys/", "/etc/", "/usr/local/libexec/telcoin/", "/opt/telcoin-node-scripts")
_START = r"(?<![\w/.~-])"


def relocate(text, root, prefixes=RELOCATED):
    pattern = re.compile(_START + "(" + "|".join(re.escape(p) for p in prefixes) + ")")
    return pattern.sub(lambda m: str(root) + m.group(1), text)


def unrelocated(text):
    """/proc/ or /sys/ paths a relocated script still names: running it would touch the real host."""
    return re.findall(_START + r"/(?:proc|sys)/\S*", text)


def manifest_host_table():
    """(key, type) rows of the `host` table in arms/MANIFEST-FIELDS.md, in order."""
    text = MANIFEST_FIELDS.read_text()
    section = text.split("`host` holds these fields", 1)[1].split("A probe that failed", 1)[0]
    return re.findall(r"^\| `([a-z0-9_]+)` \| ([^|]+?) \|", section, re.M)


def manifest_uniform_fields():
    """The uniformity fields MANIFEST-FIELDS.md names for HOST_PROBE_SUMMARY, `vm_*` expanded in table order."""
    sentence = re.search(r"The uniformity fields are (.*?)\.\n", MANIFEST_FIELDS.read_text(), re.S).group(1)
    out = []
    for name in re.findall(r"`([a-z0-9_*]+)`", sentence):
        out += [k for k, _ in manifest_host_table() if k.startswith("vm_")] if name == "vm_*" else [name]
    return out


def install_stub(bindir, name):
    bindir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(FIX / "stub-answer.sh"), str(bindir / name))
    (bindir / name).chmod(0o755)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def mincore_pages(path):
    """Resident pages of <path>, counted here with mincore over an untouched map."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long)
    libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    libc.mincore.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
    size = os.path.getsize(str(path))
    vec = (ctypes.c_ubyte * ((size + PS - 1) // PS))()
    fd = os.open(str(path), os.O_RDONLY)
    try:
        a = libc.mmap(None, size, mmap.PROT_READ, mmap.MAP_SHARED, fd, 0)
        assert a and a != ctypes.c_void_p(-1).value, "mmap failed"
        try:
            assert libc.mincore(a, size, vec) == 0, "mincore failed"
        finally:
            libc.munmap(a, size)
    finally:
        os.close(fd)
    return sum(1 for b in bytes(vec) if b & 1)


def sparse_file(path, pages, written):
    """<path>: <pages> pages long, data only in the pages listed in <written> (the rest are holes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "wb") as f:
        f.truncate(pages * PS)
        for i in written:
            f.seek(i * PS)
            f.write(b"\x5a" * PS)


def expected_host(datadir, **over):
    """The host record the probe takes on a default Host whose datadir is <datadir>, <over> applied."""
    h = {"kernel": KERNEL, "cmdline": CMDLINE, "os_release": "Ubuntu 24.04.3 LTS", "image_serial": "20261105",
         "mem_total_kb": 16374764, "nproc": len(os.sched_getaffinity(0)), "datadir": str(datadir),
         "datadir_mount_source": "/dev/nvme0n1p1", "datadir_fstype": "ext4",
         "datadir_mount_options": "rw,relatime,discard,errors=remount-ro,commit=30", "disk": "nvme0n1",
         "read_ahead_kb": 128, "max_sectors_kb": 128, "max_hw_sectors_kb": 2048, "scheduler": "none",
         "nr_requests": 1023, "thp_enabled": "madvise", "thp_defrag": "madvise", "thp_shmem_enabled": "never",
         "khugepaged_defrag": "1"}
    h.update(("vm_" + k, v) for k, v in VM.items())
    h.update(container_memory_limit_bytes=V2_MEMORY, mdbx_dat_size_bytes=None, mdbx_dat_resident_pages=None,
             mdbx_dat_folios=None, lru_gen_enabled="0x0007")
    h.update(over)
    return h


class Host:
    """A fake node root for the host scripts (see the module docstring). datadir is <root>/var/lib/telcoin,
    named by /etc/telcoin/.node-meta; the data disk is nvme0n1 under the partition nvme0n1p1."""

    def __init__(self, root, python=True):
        self.root = r = Path(root)
        self.datadir = r / "var/lib/telcoin"
        (self.datadir / "db").mkdir(parents=True, exist_ok=True)
        for d in ("state", "tmp"):
            (r / d).mkdir(parents=True, exist_ok=True)
        files = {
            "proc/sys/kernel/osrelease": KERNEL, "proc/cmdline": CMDLINE,
            "proc/meminfo": "MemTotal:       16374764 kB\nMemFree:          912348 kB\n",
            "etc/os-release": 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.3 LTS"\nVERSION_ID="24.04"',
            "etc/cloud/build.info": "build_name: server\nserial: 20261105",
            "etc/telcoin/.node-meta": "INSTALL_METHOD=docker\nDATA_DIR=%s\nMETRICS_PORT=9101" % self.datadir,
            "sys/kernel/mm/transparent_hugepage/enabled": "always [madvise] never",
            "sys/kernel/mm/transparent_hugepage/defrag": "always defer defer+madvise [madvise] never",
            "sys/kernel/mm/transparent_hugepage/shmem_enabled": "always within_size advise [never] deny force",
            "sys/kernel/mm/transparent_hugepage/khugepaged/defrag": "1",
            "sys/kernel/mm/lru_gen/enabled": "0x0007",
            "state/findmnt": json.dumps(FINDMNT), "state/lsblk": json.dumps(LSBLK),
        }
        files.update(("proc/sys/vm/" + k, str(v)) for k, v in VM.items())
        self.queue("nvme0n1", read_ahead_kb=128, max_sectors_kb=128, max_hw_sectors_kb=2048,
                   scheduler="[none] mq-deadline", nr_requests=1023)
        for rel, text in files.items():
            write(r / rel, text + "\n")
        start = r / "usr/local/libexec/telcoin/tn-start-docker"
        write(start, (tni.V2 / "usr/local/libexec/telcoin/tn-start-docker").read_text())
        for name in ("findmnt", "lsblk", "fincore"):
            install_stub(r / "bin", name)
        tools = r / "tools"
        tools.mkdir(exist_ok=True)
        for name in ("bash", "awk", "cat", "basename") + (("python3",) if python else ()):
            os.symlink(shutil.which(name), str(tools / name))
        (r / "calls").write_text("")

    def queue(self, disk, **values):
        for k, v in values.items():
            write(self.root / "sys/block" / disk / "queue" / k, "%s\n" % v)

    def put(self, name, text):
        write(self.root / "state" / name, text if text.endswith("\n") else text + "\n")

    def calls(self, tool=None):
        lines = (self.root / "calls").read_text().splitlines()
        return [l for l in lines if tool is None or l.startswith(tool + " ")]

    def run(self, script, errexit=False):
        """<script> as `bash -s` on this root; with errexit, under `set -euo pipefail` with a line after it."""
        text = relocate(script, self.root)
        assert not unrelocated(text), "the script would touch the real host: %s" % unrelocated(text)[:3]
        if errexit:
            text = "set -euo pipefail\n" + text + "\necho SESSION-GOES-ON\n"
        r = str(self.root)
        env = {"PATH": "%s/bin:%s/tools" % (r, r), "HOME": r, "TMPDIR": r + "/tmp", "LC_ALL": "C",
               "STUB_STATE": r + "/state", "STUB_LOG": r + "/calls"}
        return subprocess.run([shutil.which("bash"), "-s"], input=text, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=120, universal_newlines=True, errors="replace")

    def expected(self, **over):
        return expected_host(self.datadir, **over)

def lines_of(p, tag):
    return [l for l in p.stdout.splitlines() if l.startswith(tag + " ")]


class HostCase(tni.BashCase):
    def lib(self, *argv, **env):
        return self.bash(tni.LIB_CALL, self.bench, *argv, **env)

    def text_of(self, *argv, **env):
        p = self.lib(*argv, **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])   # a builder contacts nothing
        return p.stdout

    def host(self, name="host", **kw):
        return Host(self.root / name, **kw)

    def py(self):
        """_bench_host_py loaded as a module (its main does not run)."""
        ns = {"__name__": "bench_host_py"}
        exec(compile(self.text_of("_bench_host_py"), "bench_host_py", "exec"), ns)
        return ns


# ------------------------------------------------------------------------------------------- the probe
class HostProbeScriptTests(HostCase):
    def probe(self, host, inst=INST, *datadir):
        p = host.run(self.text_of("bench_host_probe_script", inst, *datadir))
        self.assertEqual(p.returncode, 0, p.stdout)
        got = lines_of(p, "HOST_PROBE")
        self.assertEqual(len(got), 1, p.stdout)
        return got[0], p

    def record(self, line, inst=INST):
        p = subprocess.run(["bash", "-c", tni.LIB_CALL, "benchmark-deploy.sh", str(self.bench), "bench_host_probe_record",
                            inst], input=line + "\n", env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout)
        return json.loads(p.stdout)

    def test_frozen_keys_match_the_manifest_contract(self):
        table = manifest_host_table()
        self.assertEqual(len(table), 33, table)
        kinds = {"string": "s", "int": "i", "int or null": "i", "{order: int} or null": "o"}
        fields = self.text_of("_bench_host_fields").split()
        self.assertEqual(fields, ["%s:%s" % (k, kinds[t]) for k, t in table])
        self.assertEqual(self.text_of("_bench_host_uniform_fields").split(), manifest_uniform_fields())
        self.assertEqual(list(expected_host("/var/lib/telcoin")), [k for k, _ in table])

    def test_probe_reads_every_field_from_the_host_and_writes_nothing(self):
        host = self.host()
        sparse_file(host.datadir / "db/mdbx.dat", 256, (0, 5))
        script = self.text_of("bench_host_probe_script", INST)
        self.assertEqual(subprocess.run(["bash", "-n"], input=script, universal_newlines=True).returncode, 0)
        self.assertIn(self.text_of("_bench_host_py"), script)   # the shipped program is the one tested below
        before = sorted(str(p) for p in host.root.rglob("*"))
        line, _ = self.probe(host)
        prefix = "HOST_PROBE %s " % INST
        self.assertTrue(line.startswith(prefix + "{"), line)
        h = json.loads(line[len(prefix):])
        # fincore failed (no answer): residency is mincore's, 2 written pages of 256.
        self.assertEqual(h, host.expected(mdbx_dat_size_bytes=256 * PS, mdbx_dat_resident_pages=2))
        self.assertEqual(list(h), [k for k, _ in manifest_host_table()])
        self.assertEqual(line[len(prefix):], json.dumps(h, separators=(",", ":")))   # compact, one line
        self.assertEqual(self.record(line), h)
        mdbx = str(host.datadir / "db/mdbx.dat")
        self.assertEqual(host.calls(), ["findmnt --json --output SOURCE,FSTYPE,OPTIONS --target %s" % host.datadir,
                                        "lsblk --json --nodeps --output PKNAME,KNAME /dev/nvme0n1p1",
                                        "fincore --noheadings --raw --output PAGES %s" % mdbx])
        # Nothing was written on the host, and the probe faulted no page of mdbx.dat in.
        self.assertEqual(sorted(str(p) for p in host.root.rglob("*") if not p.name.endswith(".calls")), before)
        self.assertEqual((host.root / "sys/block/nvme0n1/queue/read_ahead_kb").read_text(), "128\n")
        self.assertEqual(mincore_pages(host.datadir / "db/mdbx.dat"), 2)

    def test_probe_takes_fincore_count_and_a_given_datadir(self):
        host = self.host()
        other = host.root / "data/probe"
        sparse_file(other / "db/mdbx.dat", 4, (0,))
        host.put("fincore", "812")
        (host.root / "etc/telcoin/.node-meta").unlink()   # the one-VM probe has no v2 node meta
        line, _ = self.probe(host, "bench-probe-01", str(other))
        h = json.loads(line[len("HOST_PROBE bench-probe-01 "):])
        self.assertEqual(h, expected_host(other, mdbx_dat_size_bytes=4 * PS, mdbx_dat_resident_pages=812))
        self.assertEqual(host.calls("fincore"), ["fincore --noheadings --raw --output PAGES %s/db/mdbx.dat" % other])

    def test_probe_without_lsblk_finds_the_disk_through_the_device_number(self):
        host = self.host()
        (host.root / "state/lsblk").unlink()
        st = os.stat(str(host.datadir))
        dev = host.root / "sys/devices/virtual/block/sdb/sdb1"
        write(dev / "partition", "1\n")
        link = host.root / "sys/dev/block" / ("%d:%d" % (os.major(st.st_dev), os.minor(st.st_dev)))
        link.parent.mkdir(parents=True)
        os.symlink("../../devices/virtual/block/sdb/sdb1", str(link))
        host.queue("sdb", read_ahead_kb=4096, max_sectors_kb=512, max_hw_sectors_kb=512, scheduler="none",
                   nr_requests=64)
        (host.root / "usr/local/libexec/telcoin/tn-start-docker").unlink()
        line, _ = self.probe(host)
        h = json.loads(line[len("HOST_PROBE %s " % INST):])
        self.assertEqual(h, host.expected(disk="sdb", read_ahead_kb=4096, max_sectors_kb=512, max_hw_sectors_kb=512,
                                          scheduler="none", nr_requests=64, container_memory_limit_bytes=None))

    def test_unreadable_host_files_are_null_not_a_failure(self):
        host = self.host()
        for rel in ("etc/cloud/build.info", "proc/sys/vm/swappiness", "sys/kernel/mm/transparent_hugepage/defrag",
                    "sys/kernel/mm/lru_gen/enabled"):
            (host.root / rel).unlink()
        (host.root / "state/findmnt").unlink()
        (host.root / "state/lsblk").unlink()
        line, _ = self.probe(host)
        h = json.loads(line[len("HOST_PROBE %s " % INST):])
        none = dict.fromkeys(("read_ahead_kb", "max_sectors_kb", "max_hw_sectors_kb", "scheduler", "nr_requests"))
        self.assertEqual(h, host.expected(image_serial=None, vm_swappiness=None, thp_defrag=None, lru_gen_enabled=None,
                                          datadir_mount_source=None,
                                          datadir_fstype=None, datadir_mount_options=None, disk=None, **none))

    def test_a_failed_probe_is_one_line_and_the_session_goes_on(self):
        cases = (("no-python", {"python": False}, None, "no python3 on the node"),
                 ("relative", {}, "DATA_DIR=relative/dir", "datadir 'relative/dir' is not an absolute path"),
                 ("missing", {}, "DATA_DIR=/nowhere/at/all", "datadir /nowhere/at/all is not a directory"),
                 ("no-meta", {}, "", "DATA_DIR unreadable in %s/etc/telcoin/.node-meta (meta rc 1)"))
        for name, kw, meta, reason in cases:
            with self.subTest(case=name):
                host = self.host(name, **kw)
                if meta is not None:
                    write(host.root / "etc/telcoin/.node-meta", meta + "\n")
                p = host.run(self.text_of("bench_host_probe_script", INST), errexit=True)
                self.assertEqual(p.returncode, 0, p.stdout)
                want = "HOST_PROBE %s probe_failed %s" % (INST, reason.replace("%s", str(host.root)))
                self.assertEqual(lines_of(p, "HOST_PROBE"), [want], p.stdout)
                self.assertEqual(p.stdout.splitlines()[-1], "SESSION-GOES-ON")
                self.assertEqual(self.record(want), {"probe_failed": True, "reason": want.split(" probe_failed ", 1)[1]})

    def test_python_that_dies_is_reported(self):
        host = self.host()
        fake = host.root / "bin/python3"
        write(fake, "#!/usr/bin/env bash\ncat > /dev/null\nexit 3\n")
        fake.chmod(0o755)
        p = host.run(self.text_of("bench_host_probe_script", INST), errexit=True)
        self.assertEqual(lines_of(p, "HOST_PROBE"), ["HOST_PROBE %s probe_failed python3 exited 3" % INST], p.stdout)
        self.assertEqual(p.stdout.splitlines()[-1], "SESSION-GOES-ON")

    def test_builder_refuses_bad_names_and_relative_datadirs(self):
        for argv in (("",), ("Bench-1",), ("1bench",), ("bench_1",), ("b" * 64,), (INST, "relative/dir")):
            with self.subTest(argv=argv):
                p = self.lib("bench_host_probe_script", *argv)
                self.assertNotEqual(p.returncode, 0)
                self.assertNotIn("HOST_PROBE", p.stdout)
                self.assertIn("bench_host_probe_script:", p.stdout)
        self.assertIn("I=bench-probe-01\nD=/srv/probe\n", self.text_of("bench_host_probe_script", "bench-probe-01", "/srv/probe"))


class HostProbeRecordTests(HostCase):
    def good(self, **over):
        return expected_host("/var/lib/telcoin", **over)

    def record(self, text, inst):
        p = subprocess.run(["bash", "-c", tni.LIB_CALL, "benchmark-deploy.sh", str(self.bench), "bench_host_probe_record",
                            inst], input=text, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout.count("\n"), 1, p.stdout)
        return json.loads(p.stdout)

    def test_record_from_a_session_output(self):
        h = self.good(mdbx_dat_size_bytes=8192, mdbx_dat_resident_pages=2, mdbx_dat_folios={"0": 2, "9": 1})
        scrambled = dict(reversed(list(h.items())), extra=1)
        def j(d):
            return json.dumps(d, separators=(",", ":"))
        missing = dict(h)
        del missing["disk"]
        lines = [
            "FSYNC_PROBE bench-validator-01 p50_us=1 p95_us=2",
            "HOST_PROBE bench-validator-01 " + j(scrambled),
            "HOST_PROBE bench-validator-010 probe_failed not this one",
            "HOST_PROBE bench-validator-02 probe_failed no python3 on the node",
            "HOST_PROBE bench-validator-03 " + j(missing),
            "HOST_PROBE bench-validator-04 " + j(dict(h, read_ahead_kb="128", nproc=2.5)),
            "HOST_PROBE bench-validator-05 " + j(h),
            "HOST_PROBE bench-validator-05 probe_failed python3 exited 1",
            "HOST_PROBE bench-validator-06 probe_failed",
            "HOST_PROBE bench-validator-07 {oops",
            "HOST_PROBE bench-validator-08 " + j(dict(h, mdbx_dat_folios={"x": 1})),
            "HOST_PROBE bench-validator-09 [1, 2]",
            "HOST_PROBE bench-validator-10 probe_failed early",
            "HOST_PROBE bench-validator-10 " + j(h),
        ]
        text = "\n".join(lines) + "\n"
        fail = lambda r: {"probe_failed": True, "reason": r}
        want = {
            "bench-validator-01": h,   # every frozen key, in table order; the unknown key dropped
            "bench-validator-02": fail("no python3 on the node"),
            "bench-validator-03": fail("unparsed: no disk"),
            "bench-validator-04": fail("unparsed: wrong type: nproc, read_ahead_kb"),
            "bench-validator-05": fail("python3 exited 1"),   # the last line wins
            "bench-validator-06": fail("(no reason given)"),
            "bench-validator-07": fail("unparsed: not JSON: {oops"),
            "bench-validator-08": fail("unparsed: wrong type: mdbx_dat_folios"),
            "bench-validator-09": fail("unparsed: [1, 2]"),
            "bench-validator-10": h,
            "bench-observer-11": fail("no HOST_PROBE line in the session output"),
        }
        for inst, record in want.items():
            with self.subTest(inst=inst):
                got = self.record(text, inst)
                self.assertEqual(got, record)
                if "probe_failed" not in got:
                    self.assertEqual(list(got), [k for k, _ in manifest_host_table()])


class HostProbeSummaryTests(HostCase):
    def summary(self, records, insts=None):
        m = self.root / "manifest.json"
        m.write_text(json.dumps({"node_startup": {i: ({"host": r} if r is not None else {"params_bak": "kept"})
                                                  for i, r in records.items()}}))
        p = self.lib("bench_host_probe_summary", m, *(insts or tni.NODES))
        self.assertEqual(p.returncode, 0, p.stdout)   # never fatal
        return p.stdout

    def fleet(self, **per_node):
        base = expected_host("/var/lib/telcoin")
        return {i: dict(base, **per_node.get(i.replace("-", "_"), {})) for i in tni.NODES}

    def test_a_uniform_fleet(self):
        recs = self.fleet()
        # Fields outside the uniformity list may differ: the datadir's device name, RAM, the boot line, the cache.
        recs["bench-validator-04"].update(datadir_mount_source="/dev/sda1", disk="sda", mem_total_kb=1, cmdline="x",
                                          mdbx_dat_resident_pages=5, mdbx_dat_folios={"0": 5})
        self.assertEqual(self.summary(recs), "HOST_PROBE_SUMMARY kernel=%s image=20261105 ra_kb=128 uniform=yes "
                                             "differ=[] probe_failed=[]\n" % KERNEL)

    def test_one_differing_node_is_named(self):
        for field, value in (("kernel", "6.8.0-1016-gcp"), ("read_ahead_kb", 16), ("vm_dirty_ratio", 40),
                             ("thp_enabled", "always"), ("container_memory_limit_bytes", 0), ("nproc", 4),
                             ("datadir_mount_options", "rw,noatime"), ("image_serial", None),
                             ("lru_gen_enabled", "0x0000")):
            with self.subTest(field=field):
                recs = self.fleet()
                recs["bench-validator-03"][field] = value
                self.assertEqual(self.summary(recs), "⚠ HOST_PROBE_SUMMARY kernel=%s image=20261105 ra_kb=128 "
                                                     "uniform=no differ=[bench-validator-03] probe_failed=[]\n" % KERNEL)

    def test_failed_probes_and_missing_records(self):
        recs = self.fleet()
        recs["bench-validator-02"] = {"probe_failed": True, "reason": "no python3 on the node"}
        recs["bench-validator-05"] = None    # no host record: left out
        recs["bench-observer-11"] = {"probe_failed": True, "reason": "x"}
        self.assertEqual(self.summary(recs), "⚠ HOST_PROBE_SUMMARY kernel=%s image=20261105 ra_kb=128 uniform=yes "
                                             "differ=[] probe_failed=[bench-validator-02 bench-observer-11]\n" % KERNEL)

    def test_most_common_value_and_ties_go_to_the_fleet_order(self):
        base = expected_host("/var/lib/telcoin")
        recs = {"bench-validator-01": dict(base, read_ahead_kb=16), "bench-validator-02": dict(base),
                "bench-validator-03": dict(base, read_ahead_kb=16), "bench-validator-04": dict(base)}
        self.assertEqual(self.summary(recs), "⚠ HOST_PROBE_SUMMARY kernel=%s image=20261105 ra_kb=16 uniform=no "
                                             "differ=[bench-validator-02 bench-validator-04] probe_failed=[]\n" % KERNEL)
        recs["bench-validator-04"]["read_ahead_kb"] = 16
        self.assertEqual(self.summary(recs), "⚠ HOST_PROBE_SUMMARY kernel=%s image=20261105 ra_kb=16 uniform=no "
                                             "differ=[bench-validator-02] probe_failed=[]\n" % KERNEL)

    def test_null_values_print_as_a_dash(self):
        recs = {i: dict(r, image_serial=None, read_ahead_kb=None) for i, r in self.fleet().items()}
        self.assertEqual(self.summary(recs), "HOST_PROBE_SUMMARY kernel=%s image=- ra_kb=- uniform=yes differ=[] "
                                             "probe_failed=[]\n" % KERNEL)

    def test_no_node_probed_is_not_uniform(self):
        recs = {"bench-validator-01": {"probe_failed": True, "reason": "x"}}
        self.assertEqual(self.summary(recs), "⚠ HOST_PROBE_SUMMARY kernel=- image=- ra_kb=- uniform=no differ=[] "
                                             "probe_failed=[bench-validator-01]\n")
        self.assertEqual(self.summary({}), "⚠ HOST_PROBE_SUMMARY kernel=- image=- ra_kb=- uniform=no differ=[] "
                                           "probe_failed=[]\n")

    def test_unreadable_manifest_is_a_warning(self):
        p = self.lib("bench_host_probe_summary", self.root / "absent.json", *tni.NODES)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout, "⚠ HOST_PROBE_SUMMARY kernel=- image=- ra_kb=- uniform=no differ=[] probe_failed=[] "
                                   "(cannot read %s)\n" % (self.root / "absent.json"))


# ------------------------------------------------------------------------------------------- the python helpers
class HostPyTests(HostCase):
    def test_docker_memory_values(self):
        ns = self.py()
        for value, want in (("28893m", V2_MEMORY), ("2g", 2 << 30), ("512MiB", 512 << 20), ("1.5g", 3 << 29),
                            ("1024", 1024), ("100kb", 102400), ("12x", None), ("", None)):
            with self.subTest(value=value):
                self.assertEqual(ns["docker_bytes"](value), want)
        start = self.root / "tn-start-docker"
        for line, want in (("exec /usr/bin/docker run -i --rm --memory=2g img telcoin node", 2 << 30),
                           ("exec /usr/bin/docker run -i -m 1g --memory-swap 3g img telcoin node", 1 << 30),
                           ("exec /usr/bin/docker run -i --memory-reservation 1g img telcoin node", 0),
                           ("# exec /usr/bin/docker run --memory 1g img", None), ("echo hello", None)):
            with self.subTest(line=line):
                start.write_text("#!/bin/bash\nset -eu\n%s\n" % line)
                self.assertEqual(ns["container_memory"](str(start)), want)
        self.assertEqual(ns["container_memory"](str(tni.V2 / "usr/local/libexec/telcoin/tn-start-docker")), V2_MEMORY)
        self.assertIsNone(ns["field"](ns["container_memory"], str(self.root / "absent")))

    def test_read_back_that_differs_fails_the_step(self):
        ns = self.py()
        reads, written = iter([128, 12]), []

        class Sysfs(io.StringIO):
            def close(self):
                written.append(self.getvalue())
                super().close()

        ns.update(mount_of=lambda d: ("/dev/nvme0n1p1", "ext4", "rw"), data_disk=lambda d, s: "nvme0n1",
                  number=lambda path: next(reads), open=lambda path, mode="r", **kw: Sysfs())
        with self.assertRaises(ns["StepFailed"]) as cm:
            ns["read_ahead"]("/data", 15)
        self.assertEqual(written, ["15\n"])
        self.assertEqual(str(cm.exception), "/sys/block/nvme0n1/queue/read_ahead_kb reads 12 after writing 15 "
                                            "(it was 128; the kernel keeps whole pages)")


# ------------------------------------------------------------------------------------------- the host steps
class HostStepScriptTests(HostCase):
    def step(self, host, *argv, errexit=True):
        script = self.text_of("bench_host_step_script", INST, *argv)
        self.assertEqual(subprocess.run(["bash", "-n"], input=script, universal_newlines=True).returncode, 0)
        p = host.run(script + 'echo "RC=$HOST_STEP_RC"\n', errexit=errexit)
        self.assertEqual(p.returncode, 0, p.stdout)
        if errexit:
            self.assertEqual(p.stdout.splitlines()[-1], "SESSION-GOES-ON")   # a failed step never stops the script
        steps = lines_of(p, "HOST_STEP")
        self.assertEqual(len(steps), 1, p.stdout)
        rc = [l for l in p.stdout.splitlines() if l.startswith("RC=")]
        return steps[0], rc[-1][3:]

    def step_record(self, text, inst=INST):
        p = subprocess.run(["bash", "-c", tni.LIB_CALL, "benchmark-deploy.sh", str(self.bench), "bench_host_step_record",
                            inst], input=text, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout.count("\n"), 1, p.stdout)
        return json.loads(p.stdout)

    def test_read_ahead_is_written_and_read_back(self):
        host = self.host()
        line, rc = self.step(host, "read-ahead-kb", "16")
        self.assertEqual((line, rc), ("HOST_STEP %s read-ahead-kb 16 read_ahead_kb_before=128 read_ahead_kb_after=16"
                                      % INST, "0"))
        self.assertEqual((host.root / "sys/block/nvme0n1/queue/read_ahead_kb").read_text(), "16\n")
        self.assertEqual(self.step_record(line + "\n"), [{"step": "read-ahead-kb", "value": "16", "result": {
            "read_ahead_kb_before": 128, "read_ahead_kb_after": 16}}])

    def test_read_ahead_without_a_disk_fails(self):
        host = self.host()
        for name in ("findmnt", "lsblk"):
            (host.root / "state" / name).unlink()
        line, rc = self.step(host, "read-ahead-kb", "16")
        self.assertEqual((line, rc), ("HOST_STEP %s read-ahead-kb 16 failed no block device found under %s"
                                      % (INST, host.datadir), "1"))

    def test_eviction_with_fincore(self):
        for name, answers, want, rc in (
                ("dropped", ("812345", "0"), "resident_pages_before=812345 resident_pages_after=0", "0"),
                ("kept", ("812345", "3"), "failed %s keeps 3 resident page(s) after fsync and posix_fadvise DONTNEED "
                                          "(812345 before)", "1")):
            with self.subTest(case=name):
                host = self.host(name)
                mdbx = host.datadir / "db/mdbx.dat"
                sparse_file(mdbx, 4, (0, 1))
                for n, a in enumerate(answers, 1):
                    host.put("fincore.%d" % n, a)
                line, got_rc = self.step(host, "evict-mdbx")
                self.assertEqual((line, got_rc), ("HOST_STEP %s evict-mdbx - %s" % (INST, want.replace("%s", str(mdbx))), rc))
                self.assertEqual(host.calls("fincore"), ["fincore --noheadings --raw --output PAGES %s" % mdbx] * 2)

    def test_eviction_measured_with_mincore(self):
        # No fincore: the real fsync + posix_fadvise(DONTNEED) on this filesystem, judged by mincore. A disk keeps no
        # page (the step holds); tmpfs cannot drop them (the step fails, naming what it found). Either way the line
        # agrees with what this test counts afterwards.
        host = self.host()
        mdbx = host.datadir / "db/mdbx.dat"
        sparse_file(mdbx, 64, range(0, 64, 2))
        line, rc = self.step(host, "evict-mdbx", str(host.datadir))
        left = mincore_pages(mdbx)
        if left == 0:
            self.assertEqual((line, rc), ("HOST_STEP %s evict-mdbx - resident_pages_before=32 resident_pages_after=0"
                                          % INST, "0"))
        else:
            self.assertEqual((line, rc), ("HOST_STEP %s evict-mdbx - failed %s keeps %d resident page(s) after fsync "
                                          "and posix_fadvise DONTNEED (32 before)" % (INST, mdbx, left), "1"))

    def test_eviction_without_mdbx_dat_has_nothing_to_drop(self):
        host = self.host()
        line, rc = self.step(host, "evict-mdbx")
        self.assertEqual((line, rc), ("HOST_STEP %s evict-mdbx - resident_pages_before=0 resident_pages_after=0" % INST,
                                      "0"))
        self.assertEqual(host.calls("fincore"), [])

    def test_unusable_datadir_or_no_python(self):
        host = self.host("no-python", python=False)
        self.assertEqual(self.step(host, "evict-mdbx"),
                         ("HOST_STEP %s evict-mdbx - failed no python3 on the node" % INST, "1"))
        host = self.host("relative")
        write(host.root / "etc/telcoin/.node-meta", "DATA_DIR=relative\n")
        self.assertEqual(self.step(host, "read-ahead-kb", "0"),
                         ("HOST_STEP %s read-ahead-kb 0 failed datadir 'relative' is not an absolute path" % INST, "1"))

    def test_python_output_must_be_ok_and_two_numbers(self):
        for out, want in (("ok 5", "python3 printed 'ok 5'"), ("ok 1 2 3", "python3 printed 'ok 1 2 3'"),
                          ("ok x 0", "python3 printed 'ok x 0'"), ("", "python3 exited 0")):
            with self.subTest(out=out):
                host = self.host("out-%d" % len(out))
                fake = host.root / "bin/python3"
                write(fake, "#!/usr/bin/env bash\ncat > /dev/null\nprintf '%s\\n' " + repr(out) + "\n")
                fake.chmod(0o755)
                self.assertEqual(self.step(host, "evict-mdbx"),
                                 ("HOST_STEP %s evict-mdbx - failed %s" % (INST, want), "1"))

    def test_builder_refuses_bad_arguments(self):
        for argv in (("Bench-1", "evict-mdbx"), (INST, "drop-caches"), (INST, "read-ahead-kb"), (INST, "read-ahead-kb", "016"),
                     (INST, "read-ahead-kb", "16k"), (INST, "read-ahead-kb", "16", "rel"), (INST, "evict-mdbx", "rel"),
                     (INST, "evict-mdbx", "/a", "/b"), (INST, "read-ahead-kb", "16", "/a", "/b")):
            with self.subTest(argv=argv):
                p = self.lib("bench_host_step_script", *argv)
                self.assertNotEqual(p.returncode, 0)
                self.assertNotIn("HOST_STEP_RC", p.stdout)
                self.assertIn("bench_host_step_script:", p.stdout)

    def test_record_of_host_step_lines(self):
        lines = [
            "HOST_STEP bench-validator-01 read-ahead-kb 16 read_ahead_kb_before=128 read_ahead_kb_after=16",
            "HOST_STEP bench-validator-010 evict-mdbx - resident_pages_before=1 resident_pages_after=0",
            "PRECFG_OK bench-validator-01 datadir=/x",
            "HOST_STEP bench-validator-01 evict-mdbx - resident_pages_before=812345 resident_pages_after=0",
            "HOST_STEP bench-validator-02 evict-mdbx - failed /x/db/mdbx.dat keeps 3 page(s)  (two spaces)",
            "HOST_STEP bench-validator-02 read-ahead-kb 16 failed",
            "HOST_STEP bench-validator-03 read-ahead-kb 016 read_ahead_kb_before=1 read_ahead_kb_after=16",
            "HOST_STEP bench-validator-03 drop-caches - failed x",
            "HOST_STEP bench-validator-03 evict-mdbx 5 resident_pages_before=1 resident_pages_after=0",
            "HOST_STEP bench-validator-03 read-ahead-kb 16 read_ahead_kb_before=128",
            "HOST_STEP bench-validator-03 evict-mdbx - resident_pages_after=0 resident_pages_before=1",
        ]
        text = "\n".join(lines) + "\n"
        un = lambda l: {"failed": "unparsed: " + l.split(" ", 2)[2]}
        self.assertEqual(self.step_record(text), [
            {"step": "read-ahead-kb", "value": "16", "result": {"read_ahead_kb_before": 128, "read_ahead_kb_after": 16}},
            {"step": "evict-mdbx", "value": None, "result": {"resident_pages_before": 812345, "resident_pages_after": 0}}])
        self.assertEqual(self.step_record(text, "bench-validator-02"), [
            {"step": "evict-mdbx", "value": None, "result": {"failed": "/x/db/mdbx.dat keeps 3 page(s)  (two spaces)"}},
            {"step": "read-ahead-kb", "value": "16", "result": {"failed": "(no reason given)"}}])
        self.assertEqual(self.step_record(text, "bench-validator-03"), [
            {"step": "read-ahead-kb", "value": "016", "result": un(lines[6])},
            {"step": "drop-caches", "value": None, "result": un(lines[7])},
            {"step": "evict-mdbx", "value": "5", "result": un(lines[8])},
            {"step": "read-ahead-kb", "value": "16", "result": un(lines[9])},
            {"step": "evict-mdbx", "value": None, "result": un(lines[10])}])
        self.assertEqual(self.step_record(text, "bench-validator-04"), [])
        self.assertEqual(self.step_record(""), [])


# ------------------------------------------------------------------------------------------- the pre-start script
class PrestartHostStepTextTests(HostCase):
    """The pre-start script with the host-step knobs: unset or off, byte for byte the unmodified script; each knob
    adds its own block (the host step's shared body) before the PRECFG_OK line, and its field to that line."""

    PINNED = {"BENCH_LOGROTATE_SIZE": "", "BENCH_NODE_LOG_FILTER": tni.FILTER}
    GOLDEN = {"a-default-filter": {}, "b-empty-filter": {"BENCH_NODE_LOG_FILTER": ""},
              "c-dbsync-overrides": {"BENCH_NODE_DB_SYNC_MODE": "durable",
                                     "BENCH_NODE_PARAM_OVERRIDES": "0:max_header_delay=250ms,vote_timeout=2s"}}
    RA_SFX = ' ra=${RA_OLD}->${RA_NEW}'
    EV_SFX = ' evict=${EV_BEFORE}/${EV_AFTER}'

    def prestart(self, after_source="", **env):
        script = tni.LIB_CALL.replace('"${argv[@]}"', after_source + '\n"${argv[@]}"')
        p = self.bash(script, self.bench, "bench_prestart_script", INST, **dict(self.PINNED, **env))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls(), [])
        return p.stdout

    def golden(self, name):
        return (FIX / ("prestart-golden-%s.txt" % name)).read_text().replace("@TN_NODE_SCRIPTS_REF@", tni.scripts_ref())

    def block(self, step, value):
        head = {"read-ahead-kb": "# 11. host step read-ahead-kb %s (BENCH_NODE_READ_AHEAD_KB): the data disk's "
                                 "queue/read_ahead_kb, written and read back" % value,
                "evict-mdbx": "# 12. host step evict-mdbx (BENCH_NODE_EVICT_MDBX=1): mdbx.dat out of the page cache, "
                              "the last thing before the start"}[step]
        tail = {"read-ahead-kb": "RA_OLD=$HS_A; RA_NEW=$HS_B", "evict-mdbx": "EV_BEFORE=$HS_A; EV_AFTER=$HS_B"}[step]
        body = self.text_of("_bench_host_step_body", step, value)
        # The same body is the standalone step's (one code path for deploy step 7 and the arm tool).
        argv = ("read-ahead-kb", value) if step == "read-ahead-kb" else ("evict-mdbx",)
        self.assertIn(body, self.text_of("bench_host_step_script", INST, *argv))
        hs = "HOST_STEP %s %s %s" % (INST, step, value)
        return ([head, 'hsok(){ echo "%s $*"; }' % hs,
                 'hsfail(){ echo "%s failed $*"; fail "host step %s: $*"; }' % (hs, step)]
                + body.splitlines() + [tail])

    def test_knobs_unset_or_off_are_byte_identical_to_the_unmodified_script(self):
        for name, env in self.GOLDEN.items():
            for ev, ra in ((None, None), ("0", ""), ("0", None), (None, "")):
                with self.subTest(golden=name, evict=ev, read_ahead=ra):
                    self.assertEqual(self.prestart(BENCH_NODE_EVICT_MDBX=ev, BENCH_NODE_READ_AHEAD_KB=ra, **env),
                                     self.golden(name))
            with self.subTest(golden=name, unset_after_config=True):
                self.assertEqual(self.prestart("unset BENCH_NODE_EVICT_MDBX BENCH_NODE_READ_AHEAD_KB", **env),
                                 self.golden(name))

    def test_each_knob_adds_only_its_own_block_and_field(self):
        cases = (({"BENCH_NODE_READ_AHEAD_KB": "16"}, [("read-ahead-kb", "16")], self.RA_SFX),
                 ({"BENCH_NODE_READ_AHEAD_KB": "0"}, [("read-ahead-kb", "0")], self.RA_SFX),
                 ({"BENCH_NODE_EVICT_MDBX": "1"}, [("evict-mdbx", "-")], self.EV_SFX),
                 ({"BENCH_NODE_EVICT_MDBX": "1", "BENCH_NODE_READ_AHEAD_KB": "4096"},
                  [("read-ahead-kb", "4096"), ("evict-mdbx", "-")], self.RA_SFX + self.EV_SFX))
        for golden, extra in (("a-default-filter", {}), ("c-dbsync-overrides", self.GOLDEN["c-dbsync-overrides"])):
            for env, blocks, sfx in cases:
                with self.subTest(golden=golden, knobs=env):
                    got = self.prestart(**dict(extra, **env)).splitlines()
                    want = self.golden(golden).splitlines()
                    last = want.pop()
                    self.assertTrue(last.endswith('"'), last)
                    for step, value in blocks:
                        want += self.block(step, value)
                    want.append(last[:-1] + sfx + '"')
                    self.assertEqual(got, want)
                    script = "\n".join(got) + "\n"
                    self.assertEqual(subprocess.run(["bash", "-n"], input=script, universal_newlines=True).returncode, 0)
                    self.assertEqual(script.count("python3 - read-ahead-kb"), int("BENCH_NODE_READ_AHEAD_KB" in env))
                    self.assertEqual(script.count("python3 - evict-mdbx"), int("BENCH_NODE_EVICT_MDBX" in env))

    def test_bad_knob_values_print_nothing(self):
        for knob, value in (("BENCH_NODE_EVICT_MDBX", "2"), ("BENCH_NODE_EVICT_MDBX", "yes"),
                            ("BENCH_NODE_READ_AHEAD_KB", "016"), ("BENCH_NODE_READ_AHEAD_KB", "16k"),
                            ("BENCH_NODE_READ_AHEAD_KB", "-1")):
            with self.subTest(knob=knob, value=value):
                # config.sh refuses them first; the lib refuses them too when the variable changes after config.sh.
                p = self.bash('i="$2"; source "$1/bench-lib.sh"; %s=%s; bench_prestart_script "$i"' % (knob, value),
                              self.bench, INST)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("%s='%s'" % (knob, value), p.stdout)
                self.assertNotIn("set -euo pipefail", p.stdout)


class PrestartHostStepRunTests(HostCase):
    """The pre-start script with both host-step knobs on a stopped sandbox v2 node (test_node_image.V2Node), its
    /proc and /sys paths moved under the node and findmnt, lsblk and fincore stubbed."""

    def node(self, fincore=("812", "0"), disk=True):
        node = tni.V2Node(self.root / "node", INST, unit="inactive", params=tni.staged_yaml())
        sparse_file(node.datadir / "db/mdbx.dat", 4, (0,))
        for name in ("findmnt", "lsblk", "fincore"):
            install_stub(node.root / "bin", name)
        # The real python3, logged, with the node's bin/ kept first on its PATH (test_node_image's python3 stub drops
        # it, and the step's python must reach the stubs above, never the host's own tools).
        write(node.root / "bin/python3", '#!/usr/bin/env bash\nprintf "python3 %%s\\n" "$*" >> "${STUB_LOG:?}"\n'
                                         'exec %s "$@"\n' % shutil.which("python3"))
        (node.root / "bin/python3").chmod(0o755)
        if disk:
            write(node.root / "state/findmnt", json.dumps(FINDMNT) + "\n")
            write(node.root / "state/lsblk", json.dumps(LSBLK) + "\n")
            write(node.root / "sys/block/nvme0n1/queue/read_ahead_kb", "128\n")
        for n, a in enumerate(fincore, 1):
            write(node.root / ("state/fincore.%d" % n), a + "\n")
        return node

    def run_prestart(self, node, **env):
        p = self.lib("bench_prestart_script", INST, BENCH_NODE_READ_AHEAD_KB="16", BENCH_NODE_EVICT_MDBX="1", **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        script = relocate(p.stdout, node.root, ("/proc/", "/sys/"))
        self.assertFalse(unrelocated(script), unrelocated(script)[:3])
        proc, precfg = node.run(script)
        return proc, precfg, lines_of(proc, "HOST_STEP")

    def test_both_steps_run_last_and_are_on_the_precfg_ok_line(self):
        node = self.node()
        p, precfg, steps = self.run_prestart(node)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(steps, ["HOST_STEP %s read-ahead-kb 16 read_ahead_kb_before=128 read_ahead_kb_after=16" % INST,
                                 "HOST_STEP %s evict-mdbx - resident_pages_before=812 resident_pages_after=0" % INST])
        self.assertEqual(len(precfg), 1, p.stdout)
        self.assertTrue(precfg[0].startswith("PRECFG_OK %s datadir=%s " % (INST, node.datadir)), precfg)
        self.assertTrue(precfg[0].endswith(" paramsbak=written ra=128->16 evict=812/0"), precfg)
        self.assertEqual((node.root / "sys/block/nvme0n1/queue/read_ahead_kb").read_text(), "16\n")
        out = p.stdout.splitlines()
        self.assertLess(out.index(steps[0]), out.index(steps[1]))
        self.assertLess(out.index(steps[1]), out.index(precfg[0]))
        # The unit was read inactive twice and never started; the steps ran after the last check.
        self.assertEqual([l for l in node.calls() if l.startswith("systemctl ")], ["systemctl is-active telcoin"] * 2)
        mdbx = node.datadir / "db/mdbx.dat"
        self.assertEqual([l for l in node.calls() if l.startswith(("python3 ", "fincore "))],
                         ["python3 - read-ahead-kb %s 16" % node.datadir, "python3 - evict-mdbx %s" % node.datadir,
                          "fincore --noheadings --raw --output PAGES %s" % mdbx,
                          "fincore --noheadings --raw --output PAGES %s" % mdbx])
        record = subprocess.run(["bash", "-c", tni.LIB_CALL, "benchmark-deploy.sh", str(self.bench),
                                 "bench_host_step_record", INST], input=p.stdout, env=self.env(), stdout=subprocess.PIPE,
                                universal_newlines=True, timeout=60).stdout
        self.assertEqual(json.loads(record), [
            {"step": "read-ahead-kb", "value": "16", "result": {"read_ahead_kb_before": 128, "read_ahead_kb_after": 16}},
            {"step": "evict-mdbx", "value": None, "result": {"resident_pages_before": 812, "resident_pages_after": 0}}])

    def test_pages_left_after_the_eviction_fail_the_pre_start(self):
        node = self.node(fincore=("812", "3"))
        p, precfg, steps = self.run_prestart(node)
        self.assertEqual(p.returncode, 1, p.stdout)
        reason = "%s/db/mdbx.dat keeps 3 resident page(s) after fsync and posix_fadvise DONTNEED (812 before)" % node.datadir
        self.assertEqual(steps[-1], "HOST_STEP %s evict-mdbx - failed %s" % (INST, reason))
        self.assertEqual(precfg, ["PRECFG_FAIL %s host step evict-mdbx: %s" % (INST, reason)])

    def test_a_failed_read_ahead_stops_before_the_eviction(self):
        node = self.node(disk=False)
        p, precfg, steps = self.run_prestart(node)
        self.assertEqual(p.returncode, 1, p.stdout)
        reason = "no block device found under %s" % node.datadir
        self.assertEqual(steps, ["HOST_STEP %s read-ahead-kb 16 failed %s" % (INST, reason)])
        self.assertEqual(precfg, ["PRECFG_FAIL %s host step read-ahead-kb: %s" % (INST, reason)])
        self.assertFalse([l for l in node.calls() if l.startswith(("fincore ", "python3 - evict-mdbx"))])


if __name__ == "__main__":
    unittest.main()
