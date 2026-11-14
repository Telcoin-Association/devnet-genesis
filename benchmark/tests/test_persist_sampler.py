"""node-persist-sampler.sh and tools/folio-census.py (bench 6 persist sampler), offline.

The sampler runs under bash against a fake /proc and /sys tree (PERSIST_ROOT) with shims on PATH:
`docker` prints the container id and State.Pid from a state file and logs each call, and `sleep`
returns at once after running the hook script of that tick (the tests change the fake tree between
ticks that way). mdbx.dat is a real scratch file, so its residency (fincore / mincore) is real. Bench 7:
the same host with db/tn-lmdb.dat (a sparse scratch file) and a few static files instead, a data dir with
both (tn-lmdb wins), one with neither, and shims that log any tool handed a store file to read.

The census is checked against a fake /proc (a writer's maps and pagemap, kpageflags) laid over a real
scratch file, and in a real-file smoke: a live writer maps a disk-backed scratch file, and five censuses
(then five sampler ticks) must leave the file's page-cache residency exactly as it was.
Never against a live database.
"""
import ctypes
import ctypes.util
import importlib.util
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
SAMPLER = BENCH / "node-persist-sampler.sh"
CENSUS = BENCH / "tools" / "folio-census.py"
PERSIST_HEADER = (BENCH / "tools" / "persist-csv-header.txt").read_text()
FOLIO_HEADER = (BENCH / "tools" / "folio-census-header.txt").read_text()
NCOLS = len(PERSIST_HEADER.strip().split(","))
COL = {name: i for i, name in enumerate(PERSIST_HEADER.strip().split(","))}
MDBX_COLS = ("mdbx_dat_size_bytes", "mdbx_dat_resident_pages", "mdbx_dat_vma_bytes", "mdbx_dat_rr_bytes",
             "mdbx_dat_resident_past_used_pages")
PAST = "mdbx_dat_resident_past_used_pages"
# bench 7: appended after the frozen bench-6 columns; the first five every tick, the last three every 300 s
LMDB_FAST = ("tn_lmdb_dat_size_bytes", "tn_lmdb_dat_allocated_bytes", "static_files_size_bytes",
             "static_files_files_total", "tn_lmdb_used_bytes")
LMDB_SLOW = ("tn_lmdb_dat_resident_pages", "tn_lmdb_dat_vma_bytes", "tn_lmdb_dat_rr_bytes")
LMDB_COLS = LMDB_FAST + LMDB_SLOW
# The node's tn-lmdb gauges: tables 40,960 + 8,192 bytes, 3 free pages of 4,096: 61,440 bytes used.
LMDB_METRICS = ('# TYPE reth_db_table_size gauge\nreth_db_table_size{table="PlainAccountState"} 40960\n'
                'reth_db_table_size{table="HashedStorages"} 8.192e+03\n'
                'reth_db_table_pages{table="PlainAccountState",type="leaf"} 9\nreth_db_table_size_bytes_other 7\n'
                "reth_db_freelist 3\nreth_db_page_size 4096\ntn_reth_mdbx_used_bytes 999\n")
LMDB_USED = 40960 + 8192 + 3 * 4096
STATIC = (("static_file_headers_0_499999", 3000), ("static_file_headers_0_499999.conf", 100),
          ("static_file_account-change-sets_0_499999.csoff", 0))
PS = os.sysconf("SC_PAGE_SIZE")

_spec = importlib.util.spec_from_file_location("folio_census", str(CENSUS))
census_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census_mod)

_libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
_libc.mmap.restype = ctypes.c_void_p
_libc.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long)
_libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
_libc.mincore.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)


def residency(path):
    """The test's own mincore of path (PROT_NONE private map, never touched): one 0/1 per page."""
    size = os.path.getsize(path)
    n = (size + PS - 1) // PS
    if n == 0:
        return b""
    fd = os.open(path, os.O_RDONLY)
    try:
        addr = _libc.mmap(None, n * PS, 0, 2, fd, 0)
        assert addr not in (None, ctypes.c_void_p(-1).value), "mmap failed"
        try:
            vec = (ctypes.c_ubyte * n)()
            assert _libc.mincore(addr, n * PS, ctypes.addressof(vec)) == 0, "mincore failed"
            return bytes(b & 1 for b in vec)
        finally:
            _libc.munmap(addr, n * PS)
    finally:
        os.close(fd)


def fs_type(path):
    """The file system type of the mount holding path (the longest matching mount point)."""
    best, typ = "", None
    with open("/proc/self/mounts") as f:
        for line in f:
            parts = line.split()
            mnt = parts[1].replace("\\040", " ")
            if (path == mnt or path.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best):
                best, typ = mnt, parts[2]
    return typ


DOCKER_SHIM = """#!/bin/sh
echo "docker $*" >> "$FAKE_STATE/docker.log"
[ -f "$FAKE_STATE/docker.out" ] || exit 1
cat "$FAKE_STATE/docker.out"
"""
SLEEP_SHIM = """#!/bin/sh
n=$(cat "$FAKE_STATE/ticks" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$FAKE_STATE/ticks"
if [ -f "$FAKE_STATE/hook-$n.sh" ]; then sh "$FAKE_STATE/hook-$n.sh"; fi
exit 0
"""
DISKSTATS = (" 259       0 nvme0n1 100 1 2000 30 400 2 8000 50 3 60 70 0 0 0 0 9 11\n"
             " 259       1 nvme0n1p1 90 1 1800 25 390 2 7900 45 2 55 65 0 0 0 0 8 10\n"
             "   7       0 loop0 5 0 10 1 0 0 0 0 0 1 1 0 0 0 0 0 0\n")
VMSTAT = ("nr_free_pages 1000\nnr_dirty 501\nnr_writeback 502\nnr_dirtied 503\nnr_written 504\n"
          "workingset_refault_anon 1\nworkingset_refault_file 505\npgmajfault 506\nthp_file_alloc 507\n"
          "thp_file_fallback 508\nthp_file_mapped 0\n")
MEMINFO = ("MemTotal:       16000000 kB\nMemFree:          100000 kB\nMemAvailable:    9000001 kB\n"
           "Buffers:            1000 kB\nCached:          7000002 kB\nSwapCached:            0 kB\n"
           "Dirty:              3003 kB\nWriteback:            44 kB\nWritebackTmp:          0 kB\n")
MEMCG_STAT = ("anon 1000\nfile 2000\nkernel 10\nfile_mapped 5\nfile_dirty 300\nfile_writeback 40\n"
              "workingset_refault_anon 0\nworkingset_refault_file 7\n")


def proc_io(base):
    keys = ("rchar", "wchar", "syscr", "syscw", "read_bytes", "write_bytes", "cancelled_write_bytes")
    return "".join("%s: %d\n" % (k, base + i) for i, k in enumerate(keys))


class SamplerCase(unittest.TestCase):
    """A fake host: /proc and /sys under root/, the node's data dir with a real db/mdbx.dat."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="persist-sampler-")
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "root"
        self.bin = self.tmp / "bin"
        self.state = self.tmp / "state"
        self.out = self.tmp / "out"
        self.data = self.tmp / "data"
        for d in (self.root / "proc", self.bin, self.state, self.out, self.data / "db"):
            d.mkdir(parents=True)
        for name, text in (("docker", DOCKER_SHIM), ("sleep", SLEEP_SHIM)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.mdbx = self.data / "db" / "mdbx.dat"
        fd = os.open(str(self.mdbx), os.O_RDWR | os.O_CREAT, 0o644)
        os.pwrite(fd, b"\x5a" * (8 * PS), 0)  # 8 written pages, then a hole
        os.ftruncate(fd, 32 * PS)
        os.close(fd)
        self.st = os.stat(str(self.mdbx))
        # The node's /metrics as a file curl reads: used size 4 pages, so pages 4-7 are past it.
        self.metrics_url = self.metrics("# TYPE tn_reth_mdbx_used_bytes gauge\ntn_reth_mdbx_used_bytes %d\n" % (4 * PS))
        proc = self.root / "proc"
        (proc / "diskstats").write_text(DISKSTATS)
        (proc / "vmstat").write_text(VMSTAT)
        (proc / "meminfo").write_text(MEMINFO)
        # The data dir's device -> a partition of nvme0n1 in the fake /sys.
        dst = os.stat(str(self.data)).st_dev
        part = self.root / "sys" / "devices" / "pci0000:00" / "nvme" / "nvme0n1" / "nvme0n1p1"
        part.mkdir(parents=True)
        (part / "partition").write_text("1\n")
        link = self.root / "sys" / "dev" / "block" / ("%d:%d" % (os.major(dst), os.minor(dst)))
        link.parent.mkdir(parents=True)
        os.symlink("../../devices/pci0000:00/nvme/nvme0n1/nvme0n1p1", str(link))

    def tearDown(self):
        self._tmp.cleanup()

    def cgroup_dir(self, cid):
        return self.root / "sys" / "fs" / "cgroup" / "system.slice" / ("docker-%s.scope" % cid)

    def add_node(self, pid, cid, io_base=11, argv=("telcoin", "node", "--datadir", "/home/nonroot"), smaps=None):
        """The containerised node: /proc/<pid>/{cmdline,cgroup,io,smaps} and its v2 memory cgroup."""
        d = self.root / "proc" / str(pid)
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
        (d / "cgroup").write_text("0::/system.slice/docker-%s.scope\n" % cid)
        (d / "io").write_text(proc_io(io_base))
        if smaps is not None:
            (d / "smaps").write_text(smaps)
        cg = self.cgroup_dir(cid)
        cg.mkdir(parents=True, exist_ok=True)
        (cg / "memory.current").write_text("123456789\n")
        (cg / "memory.stat").write_text(MEMCG_STAT)
        with open(str(cg / "cgroup.procs"), "a") as f:
            f.write("%d\n" % pid)

    def smaps(self, st=None, path="/home/nonroot/db/mdbx.dat"):
        st = st or self.st
        dev = "%02x:%02x" % (os.major(st.st_dev), os.minor(st.st_dev))
        ino = st.st_ino
        vmas = (
            ("7f0000000000-7f0010000000 rw-s 00000000 %s %d %s" % (dev, ino, path), 262144, "rd wr sh mr mw me ms sd rr nh"),
            ("7f0010000000-7f0020000000 rw-s 10000000 %s %d %s" % (dev, ino, path), 262144, "rd wr sh mr mw me ms sd nh"),
            # same inode, another device number, the file's name: counted (bind mounts can differ in dev)
            ("7f0030000000-7f0030100000 r--s 00000000 fe:00 %d %s" % (ino, path), 1024, "rd sh mr mw me ms sd rr"),
            # same inode, another device, another name: not the file
            ("7f0040000000-7f0040100000 r--s 00000000 fe:00 %d /home/nonroot/other.dat" % ino, 2048, "rd sh rr"),
            # another inode with the same name: not the file
            ("7f0050000000-7f0050100000 r--s 00000000 %s %d %s" % (dev, ino + 1, path), 4096, "rd sh rr"),
            ("7ffd00000000-7ffd00021000 rw-p 00000000 00:00 0                          [stack]", 132, "rd wr mr mw me gd ac"),
        )
        out = []
        for head, size_kb, flags in vmas:
            out.append("%s\nSize:           %8d kB\nKernelPageSize:        4 kB\nRss:                   0 kB\n"
                       "VmFlags: %s\n" % (head, size_kb, flags))
        return "".join(out)

    def metrics(self, body, name="metrics.txt"):
        """A file:// URL serving body as the node's Prometheus text."""
        (self.state / name).write_text(body)
        return "file://" + str(self.state / name)

    def run_sampler(self, ticks, mdbx_every=60, census_every=0, extra=None, path_first=None, metrics_url=True):
        env = {"PATH": os.pathsep.join([str(p) for p in (path_first or [])] + [str(self.bin), os.environ.get("PATH", "/usr/bin:/bin")]),
               "HOME": str(self.tmp), "FAKE_STATE": str(self.state), "PERSIST_ROOT": str(self.root),
               "PERSIST_DATA_DIR": str(self.data), "PERSIST_OUT_DIR": str(self.out), "PERSIST_HOST": "bench-validator-01",
               "PERSIST_INTERVAL_SECS": "30", "PERSIST_MDBX_EVERY_SECS": str(mdbx_every),
               "PERSIST_CENSUS_EVERY_SECS": str(census_every), "PERSIST_TICKS": str(ticks),
               "PERSIST_CENSUS": str(CENSUS)}
        if metrics_url:  # never the host's own 127.0.0.1:9101
            env["PERSIST_METRICS_URL"] = self.metrics_url if metrics_url is True else metrics_url
        env.update(extra or {})
        t0 = time.monotonic()
        p = subprocess.run(["bash", str(SAMPLER)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=120)
        self.secs = time.monotonic() - t0
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def rows(self):
        lines = (self.out / "bench-validator-01.persist.csv").read_text().splitlines()
        self.assertEqual(lines[0] + "\n", PERSIST_HEADER)
        return [line.split(",") for line in lines[1:]]

    def hook(self, tick, script):
        (self.state / ("hook-%d.sh" % tick)).write_text(script)

    def docker(self, cid, pid):
        (self.state / "docker.out").write_text("%s %d\n" % (cid, pid))


class SamplerTests(SamplerCase):
    def test_header_is_the_frozen_file_byte_for_byte(self):
        self.run_sampler(1)
        text = (self.out / "bench-validator-01.persist.csv").read_bytes()
        self.assertEqual(text.split(b"\n", 1)[0] + b"\n", PERSIST_HEADER.encode())
        self.assertEqual(census_mod.HEADER + "\n", FOLIO_HEADER)

    def test_full_row(self):
        self.add_node(4242, "c0ffee", smaps=self.smaps())
        self.docker("c0ffee", 4242)
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual(len(row), NCOLS)
        got = {name: row[i] for name, i in COL.items()}
        want = {
            "pid": "4242",
            "disk_rd_ios_total": "100", "disk_rd_bytes_total": str(2000 * 512), "disk_rd_ticks_ms_total": "30",
            "disk_wr_ios_total": "400", "disk_wr_bytes_total": str(8000 * 512), "disk_wr_ticks_ms_total": "50",
            "disk_flush_ios_total": "9", "disk_flush_ticks_ms_total": "11", "disk_in_flight_ios": "3",
            "disk_io_ticks_ms_total": "60",
            "vm_nr_dirty_pages": "501", "vm_nr_writeback_pages": "502", "vm_nr_dirtied_pages_total": "503",
            "vm_nr_written_pages_total": "504", "vm_workingset_refault_file_pages_total": "505",
            "vm_pgmajfault_total": "506", "vm_thp_file_alloc_total": "507", "vm_thp_file_fallback_total": "508",
            "mem_available_kb": "9000001", "mem_cached_kb": "7000002", "mem_dirty_kb": "3003", "mem_writeback_kb": "44",
            "memcg_current_bytes": "123456789", "memcg_file_bytes": "2000", "memcg_file_dirty_bytes": "300",
            "memcg_file_writeback_bytes": "40", "memcg_workingset_refault_file_pages_total": "7",
            "proc_rchar_bytes_total": "11", "proc_wchar_bytes_total": "12", "proc_syscr_total": "13",
            "proc_syscw_total": "14", "proc_read_bytes_total": "15", "proc_write_bytes_total": "16",
            "proc_cancelled_write_bytes_total": "17",
            "mdbx_dat_size_bytes": str(32 * PS), "mdbx_dat_resident_pages": str(sum(residency(str(self.mdbx)))),
            "mdbx_dat_vma_bytes": str((262144 + 262144 + 1024) * 1024), "mdbx_dat_rr_bytes": str((262144 + 1024) * 1024),
            PAST: "4",
        }
        for name, value in want.items():
            self.assertEqual(got[name], value, name)
        self.assertTrue(got["ts_unix"].isdigit())
        self.assertEqual(want["mdbx_dat_resident_pages"], "8")

    def test_every_source_missing_keeps_the_column_count(self):
        for name in ("diskstats", "vmstat", "meminfo"):
            (self.root / "proc" / name).unlink()
        self.mdbx.unlink()
        self.run_sampler(2)  # no docker answer: no pid, no cgroup, no io, no smaps
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row), NCOLS)
            self.assertTrue(row[0].isdigit())
            self.assertEqual(row[1:], [""] * (NCOLS - 1))

    def test_one_missing_source_blanks_only_its_cells(self):
        self.add_node(4242, "c0ffee", smaps=self.smaps())
        self.docker("c0ffee", 4242)
        (self.root / "proc" / "vmstat").unlink()
        (self.root / "proc" / "4242" / "io").unlink()
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual(len(row), NCOLS)
        for name, i in COL.items():
            if name.startswith("vm_") or name.startswith("proc_") or name in LMDB_COLS:   # an mdbx.dat data dir
                self.assertEqual(row[i], "", name)
            else:
                self.assertNotEqual(row[i], "", name)

    def test_a_failing_reader_still_writes_a_full_row(self):
        shim = self.tmp / "badawk"
        shim.mkdir()
        (shim / "awk").write_text("#!/bin/sh\nexit 1\n")
        (shim / "awk").chmod(0o755)
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        self.run_sampler(2, path_first=[shim])
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row), NCOLS)
            self.assertEqual(row[1], "4242")
            self.assertEqual(row[2:], [""] * (NCOLS - 2))

    def test_mdbx_columns_only_on_their_cadence(self):
        self.add_node(4242, "c0ffee", smaps=self.smaps())
        self.docker("c0ffee", 4242)
        self.run_sampler(7, mdbx_every=90)  # every 3rd 30-s tick: rows 0, 3, 6
        rows = self.rows()
        self.assertEqual(len(rows), 7)
        for k, row in enumerate(rows):
            cells = [row[COL[c]] for c in MDBX_COLS]
            if k % 3 == 0:
                self.assertTrue(all(cells), (k, cells))
            else:
                self.assertEqual(cells, [""] * len(MDBX_COLS), k)
            self.assertNotEqual(row[COL["vm_nr_dirty_pages"]], "", k)

    def test_default_cadence_is_ten_ticks(self):
        self.run_sampler(11, mdbx_every=300)
        filled = [k for k, row in enumerate(self.rows()) if row[COL["mdbx_dat_size_bytes"]]]
        self.assertEqual(filled, [0, 10])

    def test_pid_change_is_followed(self):
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        # After the first row the node restarts: new container, new pid, the old /proc entry gone.
        self.add_node(5151, "beef01", io_base=900)
        (self.state / "docker.next").write_text("beef01 5151\n")
        self.hook(1, "rm -rf '%s'\ncp '%s' '%s'\n" % (self.root / "proc" / "4242", self.state / "docker.next",
                                                    self.state / "docker.out"))
        # 5151 exists from the start, but docker names 4242 until the restart.
        self.run_sampler(3)
        rows = self.rows()
        self.assertEqual([r[COL["pid"]] for r in rows], ["4242", "5151", "5151"])
        self.assertEqual(rows[0][COL["proc_rchar_bytes_total"]], "11")
        self.assertEqual(rows[1][COL["proc_rchar_bytes_total"]], "900")
        calls = (self.state / "docker.log").read_text().splitlines()
        self.assertEqual(len(calls), 2, calls)  # tick 0 and the tick after the restart; then cached

    def test_cached_pid_needs_no_docker(self):
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        self.hook(1, "rm -f '%s'\n" % (self.state / "docker.out"))
        self.run_sampler(3)
        self.assertEqual([r[COL["pid"]] for r in self.rows()], ["4242"] * 3)
        self.assertEqual(len((self.state / "docker.log").read_text().splitlines()), 1)

    def test_node_gone_leaves_pid_blank(self):
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        self.hook(1, "rm -rf '%s' '%s'\n" % (self.root / "proc" / "4242", self.state / "docker.out"))
        self.run_sampler(2)
        rows = self.rows()
        self.assertEqual([r[COL["pid"]] for r in rows], ["4242", ""])
        self.assertEqual(rows[1][COL["memcg_current_bytes"]], "")
        self.assertEqual(rows[1][COL["proc_rchar_bytes_total"]], "")

    def test_entrypoint_wrapper_searches_the_container_cgroup(self):
        self.add_node(70, "c0ffee", argv=("/bin/sh", "-c", "exec /usr/local/bin/start"))
        self.add_node(71, "c0ffee", io_base=500)
        self.docker("c0ffee", 70)
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual(row[COL["pid"]], "71")
        self.assertEqual(row[COL["proc_rchar_bytes_total"]], "500")

    def test_host_docker_client_is_not_the_node(self):
        # The host-side `docker run ... telcoin node` matches the command line but sits outside the container.
        d = self.root / "proc" / "60"
        d.mkdir()
        (d / "cmdline").write_bytes(b"docker\0run\0--name\0telcoin\0telcoin\0node\0")
        (d / "cgroup").write_text("0::/system.slice/telcoin.service\n")
        self.add_node(70, "c0ffee", argv=("/bin/sh", "-c", "start"))
        self.docker("c0ffee", 70)
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual(row[COL["pid"]], "")

    def test_pid_file_mode(self):
        self.add_node(4242, "c0ffee")
        self.add_node(5151, "c0ffee", io_base=900)
        pid_file = self.state / "probe.pid"
        pid_file.write_text("4242\n")
        self.hook(1, "echo 5151 > '%s'\n" % pid_file)
        self.run_sampler(2, extra={"PERSIST_PID_FILE": str(pid_file)})
        self.assertEqual([r[COL["pid"]] for r in self.rows()], ["4242", "5151"])
        self.assertFalse((self.state / "docker.log").exists())

    def test_disk_override_and_unresolvable_disk(self):
        self.run_sampler(1, extra={"PERSIST_DISK": "loop0"})
        (row,) = self.rows()
        self.assertEqual(row[COL["disk_rd_ios_total"]], "5")
        shutil.rmtree(str(self.root / "sys" / "dev"))
        (self.out / "bench-validator-01.persist.csv").unlink()
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual([row[COL[c]] for c in COL if c.startswith("disk_")], [""] * 10)

    def test_whole_disk_data_dir_counts_the_namespace_itself(self):
        """Bench 6 local SSD: the data dir is an ext4 made on the whole namespace, so its sysfs node has no
        partition file and DISK is nvme1n1 itself: the CSV counts the SSD alone, not the boot disk."""
        (link,) = (self.root / "sys" / "dev" / "block").iterdir()
        link.unlink()
        (self.root / "sys" / "devices" / "pci0000:00" / "nvme" / "nvme1n1").mkdir(parents=True)
        os.symlink("../../devices/pci0000:00/nvme/nvme1n1", str(link))
        (self.root / "proc" / "diskstats").write_text(
            DISKSTATS + " 259       2 nvme1n1 7 0 56 4 70 0 560 6 1 8 9 0 0 0 0 2 3\n")
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual({c: row[COL[c]] for c in COL if c.startswith("disk_")}, {
            "disk_rd_ios_total": "7", "disk_rd_bytes_total": str(56 * 512), "disk_rd_ticks_ms_total": "4",
            "disk_wr_ios_total": "70", "disk_wr_bytes_total": str(560 * 512), "disk_wr_ticks_ms_total": "6",
            "disk_flush_ios_total": "2", "disk_flush_ticks_ms_total": "3", "disk_in_flight_ios": "1",
            "disk_io_ticks_ms_total": "8"})

    def test_v1_memory_cgroup(self):
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        (self.root / "proc" / "4242" / "cgroup").write_text(
            "12:pids:/docker/c0ffee\n4:memory:/docker/c0ffee\n0::/system.slice/containerd.service\n")
        v1 = self.root / "sys" / "fs" / "cgroup" / "memory" / "docker" / "c0ffee"
        v1.mkdir(parents=True)
        (v1 / "memory.usage_in_bytes").write_text("555\n")
        (v1 / "memory.stat").write_text("cache 66\nrss 1\ndirty 77\nwriteback 88\n")
        self.run_sampler(1)
        (row,) = self.rows()
        got = [row[COL[c]] for c in ("memcg_current_bytes", "memcg_file_bytes", "memcg_file_dirty_bytes",
                                     "memcg_file_writeback_bytes", "memcg_workingset_refault_file_pages_total")]
        self.assertEqual(got, ["555", "66", "77", "88", ""])

    def test_resident_pages_without_fincore(self):
        self.run_sampler(1, extra={"PERSIST_FINCORE": ""})
        (row,) = self.rows()
        self.assertEqual(row[COL["mdbx_dat_resident_pages"]], "8")

    def test_old_header_moves_aside(self):
        csv = self.out / "bench-validator-01.persist.csv"
        csv.write_text("ts_unix,pid,something_else\n1,2,3\n")
        self.run_sampler(1)
        self.assertEqual(len(self.rows()), 1)
        aside = [p for p in self.out.iterdir() if p.name.startswith("bench-validator-01.persist.csv.old-")]
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_text(), "ts_unix,pid,something_else\n1,2,3\n")

    def test_appends_after_a_restart(self):
        self.run_sampler(2)
        self.run_sampler(1)
        self.assertEqual(len(self.rows()), 3)

    def test_census_every_900_s(self):
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        self.run_sampler(7, census_every=90)  # census on ticks 0, 3, 6
        lines = (self.out / "bench-validator-01.folios.txt").read_text().splitlines()
        self.assertEqual(lines[0] + "\n", FOLIO_HEADER)
        self.assertEqual(len(lines), 4, lines)
        for line in lines[1:]:
            cells = line.split(",")
            self.assertEqual(len(cells), 10)
            # the fake node has no maps: nothing resolvable, one row per census with the order columns empty
            self.assertEqual(cells[2:], [str(32 * PS), "8", "8", "", "", "", "", ""])

    def test_census_off(self):
        self.run_sampler(2, census_every=0)
        self.assertFalse((self.out / "bench-validator-01.folios.txt").exists())

    def test_bad_knob_refused(self):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PERSIST_OUT_DIR": str(self.out),
               "PERSIST_INTERVAL_SECS": "3O"}
        p = subprocess.run(["bash", str(SAMPLER)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn("INTERVAL", p.stderr)
        self.assertFalse(any(self.out.iterdir()))

    def past_used(self, **kw):
        self.run_sampler(1, **kw)
        (row,) = self.rows()
        self.assertEqual(len(row), NCOLS)
        self.assertEqual(row[COL["mdbx_dat_resident_pages"]], "8")  # the other 300-s columns still filled
        (self.out / "bench-validator-01.persist.csv").unlink()
        return row[COL[PAST]]

    def test_used_size_gauge_present(self):
        self.assertEqual(self.past_used(), "4")
        url = self.metrics('# HELP x\ntn_reth_mdbx_used_bytes_total 1\ntn_reth_mdbx_used_bytes{db="state"} 2.4576e+04\n'
                           "tn_reth_mdbx_random_advice_bytes 0\n", "labels.txt")
        self.assertEqual(self.past_used(metrics_url=url), "2")  # used 6 pages: pages 6-7
        self.assertEqual(self.past_used(metrics_url=self.metrics("tn_reth_mdbx_used_bytes 1048576\n", "big.txt")), "0")

    def test_used_size_gauge_absent(self):
        body = "# an image without the gauge\ntn_reth_mdbx_random_advice_bytes 0\ntn_reth_mdbx_used_bytes NaN\n"
        self.assertEqual(self.past_used(metrics_url=self.metrics(body, "absent.txt")), "")
        self.assertEqual(self.past_used(metrics_url="file://" + str(self.state / "missing.txt")), "")

    def test_used_size_endpoint_unreachable(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens there now: connection refused
        self.assertEqual(self.past_used(metrics_url="http://127.0.0.1:%d/metrics" % port), "")
        self.assertLess(self.secs, 10)

    def test_used_size_endpoint_that_never_answers(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(4)  # connections complete, nothing is ever read or sent
        try:
            self.assertEqual(self.past_used(metrics_url="http://127.0.0.1:%d/metrics" % s.getsockname()[1]), "")
        finally:
            s.close()
        self.assertLess(self.secs, 10)  # curl --max-time 3, not the 20-s timeout

    def test_default_metrics_url_from_node_meta(self):
        shim = self.tmp / "curlshim"
        shim.mkdir()
        (shim / "curl").write_text('#!/bin/sh\necho "$*" >> "$FAKE_STATE/curl.log"\n'
                                   'printf "tn_reth_mdbx_used_bytes %d\\n"\n' % (6 * PS))
        (shim / "curl").chmod(0o755)
        meta = self.root / "etc" / "telcoin" / ".node-meta"
        meta.parent.mkdir(parents=True)
        log = self.state / "curl.log"
        for content, want_url, want in (
                (None, "http://127.0.0.1:9101/metrics", "2"),
                ("NODE=x\nMETRICS_PORT=9555\n", "http://127.0.0.1:9555/metrics", "2"),
                ("METRICS_PORT=\n", "http://127.0.0.1:9101/metrics", "2"),
                ("METRICS_PORT=9555\nMETRICS_PORT=9666\n", "http://127.0.0.1:9101/metrics", "2"),
                ("METRICS_PORT=95x5\n", None, "")):
            with self.subTest(meta=content):
                if content is None:
                    if meta.exists():
                        meta.unlink()
                else:
                    meta.write_text(content)
                if log.exists():
                    log.unlink()
                self.assertEqual(self.past_used(metrics_url=False, path_first=[shim]), want)
                calls = log.read_text().splitlines() if log.exists() else []
                self.assertEqual(calls, ["-s --max-time 3 " + want_url] if want_url else [])

    @unittest.skipUnless(shutil.which("mawk"), "mawk not installed")
    def test_mawk_reads_the_same_row(self):
        # Ubuntu 24.04 nodes run mawk as awk.
        self.add_node(4242, "c0ffee", smaps=self.smaps())
        self.docker("c0ffee", 4242)
        self.run_sampler(1)
        mawk_dir = self.tmp / "mawk"
        mawk_dir.mkdir()
        os.symlink(shutil.which("mawk"), str(mawk_dir / "awk"))
        self.run_sampler(1, path_first=[mawk_dir])
        a, b = self.rows()
        self.assertEqual(a[1:], b[1:])


# ---- bench7 HB-3: tn-lmdb store ----
READ_TOOLS = ("awk", "cat", "head", "tail", "dd", "od", "xxd", "hexdump", "strings", "md5sum", "sha256sum", "cp", "wc",
              "grep", "sed", "cut", "tr", "less")
READ_SHIM = """#!/bin/sh
for a in "$@"; do
    case "$a" in */tn-lmdb.dat|*/mdbx.dat|*/static_files/*) [ ! -f "$a" ] || echo "%(name)s $*" >> "$FAKE_STATE/reads.log" ;; esac
done
%(tail)s
"""
PYTHON_SHIM = """#!/bin/sh
[ "$1" = "%(census)s" ] || echo "python3 $*" >> "$FAKE_STATE/reads.log"
exec "%(python)s" "$@"
"""


class TnLmdbSamplerTests(SamplerCase):
    """A tn-lmdb data dir: db/tn-lmdb.dat (8 written pages, then a hole to 64), static_files/ with three
    files, the node's db gauges; mdbx.dat gone."""

    def setUp(self):
        super().setUp()
        self.mdbx.unlink()
        self.lmdb = self.data / "db" / "tn-lmdb.dat"
        fd = os.open(str(self.lmdb), os.O_RDWR | os.O_CREAT, 0o644)
        os.pwrite(fd, b"\x6c" * (8 * PS), 0)
        os.ftruncate(fd, 64 * PS)
        os.close(fd)
        self.lst = os.stat(str(self.lmdb))
        self.static = self.data / "static_files"
        self.static.mkdir()
        for name, size in STATIC:
            (self.static / name).write_bytes(b"s" * size)
        self.metrics_url = self.metrics(LMDB_METRICS, "lmdb.txt")

    def lmdb_smaps(self):
        return self.smaps(self.lst, "/home/nonroot/db/tn-lmdb.dat")

    def test_tn_lmdb_row(self):
        self.add_node(4242, "c0ffee", smaps=self.lmdb_smaps())
        self.docker("c0ffee", 4242)
        p = self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual(len(row), NCOLS)
        got = dict((c, row[COL[c]]) for c in MDBX_COLS + LMDB_COLS)
        self.assertEqual(got, dict([(c, "") for c in MDBX_COLS] + [
            ("tn_lmdb_dat_size_bytes", str(64 * PS)), ("tn_lmdb_dat_allocated_bytes", str(self.lst.st_blocks * 512)),
            ("static_files_size_bytes", "3100"), ("static_files_files_total", "3"), ("tn_lmdb_used_bytes", str(LMDB_USED)),
            ("tn_lmdb_dat_resident_pages", str(sum(residency(str(self.lmdb))))),
            ("tn_lmdb_dat_vma_bytes", str((262144 + 262144 + 1024) * 1024)),
            ("tn_lmdb_dat_rr_bytes", str((262144 + 1024) * 1024))]))
        self.assertEqual(got["tn_lmdb_dat_resident_pages"], "8")
        self.assertEqual(row[COL["proc_write_bytes_total"]], "16")       # the node's own writes stay apart
        self.assertEqual(row[COL["disk_wr_ios_total"]], "400")
        self.assertEqual(p.stderr.count("node-persist-sampler: store tn-lmdb: "), 1, p.stderr)

    def test_fast_columns_every_tick_slow_on_the_cadence(self):
        self.add_node(4242, "c0ffee", smaps=self.lmdb_smaps())
        self.docker("c0ffee", 4242)
        p = self.run_sampler(4, mdbx_every=90)      # rows 0 and 3 carry the 300-s columns
        rows = self.rows()
        for k, row in enumerate(rows):
            self.assertTrue(all(row[COL[c]] for c in LMDB_FAST), (k, row))
            self.assertEqual(all(row[COL[c]] for c in LMDB_SLOW), k % 3 == 0, k)
            self.assertEqual([row[COL[c]] for c in MDBX_COLS], [""] * 5, k)
        self.assertEqual(p.stderr.count("store tn-lmdb"), 1)    # one line, not one a tick

    def test_tn_lmdb_wins_over_mdbx_and_no_knob_picks(self):
        # A migrated data dir keeps mdbx.dat beside tn-lmdb.dat; PERSIST_MDBX_FILE only says where mdbx.dat lies.
        fd = os.open(str(self.mdbx), os.O_RDWR | os.O_CREAT, 0o644)
        os.ftruncate(fd, 4 * PS)
        os.close(fd)
        for extra in ({}, {"PERSIST_MDBX_FILE": str(self.mdbx)}):
            with self.subTest(extra=extra):
                self.run_sampler(1, extra=extra)
                (row,) = self.rows()
                self.assertEqual(row[COL["tn_lmdb_dat_size_bytes"]], str(64 * PS))
                self.assertEqual([row[COL[c]] for c in MDBX_COLS], [""] * 5)
                (self.out / "bench-validator-01.persist.csv").unlink()
        self.lmdb.unlink()
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual(row[COL["mdbx_dat_size_bytes"]], str(4 * PS))
        self.assertEqual([row[COL[c]] for c in LMDB_COLS], [""] * len(LMDB_COLS))

    def test_used_bytes_needs_the_three_gauges(self):
        for body, want in ((LMDB_METRICS, str(LMDB_USED)),
                           (LMDB_METRICS.replace("reth_db_freelist 3\n", ""), ""),
                           (LMDB_METRICS.replace("reth_db_page_size 4096", "reth_db_page_size NaN"), ""),
                           ("tn_reth_mdbx_used_bytes 4096\n", ""),
                           (LMDB_METRICS.replace("reth_db_freelist 3", "reth_db_freelist 0"), str(40960 + 8192))):
            with self.subTest(body=body[-60:]):
                self.run_sampler(1, metrics_url=self.metrics(body, "m.txt"))
                (row,) = self.rows()
                self.assertEqual(row[COL["tn_lmdb_used_bytes"]], want)
                self.assertEqual(row[COL["tn_lmdb_dat_size_bytes"]], str(64 * PS))
                (self.out / "bench-validator-01.persist.csv").unlink()
        self.run_sampler(1, metrics_url="file://" + str(self.state / "missing.txt"))
        (row,) = self.rows()
        self.assertEqual(row[COL["tn_lmdb_used_bytes"]], "")

    def test_static_files_absent_is_empty_and_an_empty_dir_is_zero(self):
        shutil.rmtree(str(self.static))
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual((row[COL["static_files_size_bytes"]], row[COL["static_files_files_total"]]), ("", ""))
        self.static.mkdir()
        (self.out / "bench-validator-01.persist.csv").unlink()
        self.run_sampler(1)
        (row,) = self.rows()
        self.assertEqual((row[COL["static_files_size_bytes"]], row[COL["static_files_files_total"]]), ("0", "0"))

    def test_neither_store_logs_once_and_samples_the_rest(self):
        self.lmdb.unlink()
        self.add_node(4242, "c0ffee")
        self.docker("c0ffee", 4242)
        # the node creates its store after the second row
        self.hook(2, "cp '%s' '%s'\n" % (self.static / STATIC[0][0], self.lmdb))
        p = self.run_sampler(3, census_every=30)
        rows = self.rows()
        for row in rows[:2]:
            self.assertEqual([row[COL[c]] for c in MDBX_COLS + LMDB_COLS], [""] * (5 + len(LMDB_COLS)))
            self.assertEqual(row[COL["disk_wr_ios_total"]], "400")
            self.assertEqual(row[COL["proc_write_bytes_total"]], "16")
        self.assertEqual(rows[2][COL["tn_lmdb_dat_size_bytes"]], "3000")
        self.assertEqual(p.stderr.count("node-persist-sampler: neither "), 1, p.stderr)
        self.assertEqual(p.stderr.count("store tn-lmdb"), 1, p.stderr)
        folios = (self.out / "bench-validator-01.folios.txt").read_text().splitlines()
        self.assertEqual(len(folios), 2, folios)     # the header and the third tick's census only

    def test_census_sums_the_static_files(self):
        self.run_sampler(1, census_every=30)
        (_, line) = (self.out / "bench-validator-01.folios.txt").read_text().splitlines()
        cells = line.split(",")
        resident = sum(residency(str(self.lmdb))) + sum(sum(residency(str(self.static / n))) for n, _ in STATIC)
        self.assertEqual(cells[2:5], [str(64 * PS + 3100), str(resident), str(resident)])
        self.assertEqual(cells[5:], [""] * 5)

    def test_no_store_file_is_handed_to_a_reader(self):
        shim = self.tmp / "readshims"
        shim.mkdir()
        for name in READ_TOOLS + ("mdbx_stat", "telcoin-network", "telcoin"):
            real = shutil.which(name)
            (shim / name).write_text(READ_SHIM % {"name": name, "tail": 'exec "%s" "$@"' % real if real else "exit 0"})
            (shim / name).chmod(0o755)
        (shim / "python3").write_text(PYTHON_SHIM % {"census": CENSUS, "python": sys.executable})
        (shim / "python3").chmod(0o755)
        self.add_node(4242, "c0ffee", smaps=self.lmdb_smaps())
        self.docker("c0ffee", 4242)
        for extra in ({}, {"PERSIST_FINCORE": ""}):     # fincore, then the census tool's --resident-only
            with self.subTest(extra=extra):
                self.run_sampler(2, census_every=30, path_first=[shim], extra=extra)
                rows = self.rows()
                self.assertEqual(rows[0][COL["tn_lmdb_dat_resident_pages"]], "8")
                self.assertFalse((self.state / "reads.log").exists(), (self.state / "reads.log").read_text()
                                 if (self.state / "reads.log").exists() else "")
                (self.out / "bench-validator-01.persist.csv").unlink()

    def test_the_script_never_redirects_from_a_store_file(self):
        src = SAMPLER.read_text()
        for var in ("LMDB", "MDBX", "STATIC_DIR"):
            self.assertNotRegex(src, r'<\s*"?\$\{?%s\b' % var)
        # every use of a store path: stat, the existence test, the residency and smaps helpers, find (a listing),
        # the census arguments, or a message
        uses = [l.strip() for l in src.splitlines() if re.search(r"\$\{(LMDB|MDBX|STATIC_DIR)\}", l)
                and not l.lstrip().startswith("#")]
        allowed = re.compile(r'(stat -L -c|\[ -[fd] |resident_pages "|map_bytes "|find "\$\{STATIC_DIR\}" -type f -printf|'
                             r'census_args=\(--file|--file "\$\{MDBX\}" --resident-only --from-bytes|echo "node-persist-sampler: )')
        self.assertEqual([u for u in uses if not allowed.search(u)], [])


class CensusFakeTreeTests(unittest.TestCase):
    """The census over a real scratch file (64 written pages, then 64 hole pages) and a fake /proc."""

    VBASE = 0x10000000
    HEAD, TAIL = 1 << 15, 1 << 16
    LRU, DIRTY, ACTIVE, WRITEBACK, ANON = 1 << 5, 1 << 4, 1 << 6, 1 << 8, 1 << 12

    def setUp(self):
        if PS != 4096:
            self.skipTest("the fake tree assumes 4 KiB pages")
        self._tmp = tempfile.TemporaryDirectory(prefix="folio-census-")
        self.tmp = Path(self._tmp.name)
        self.file = self.tmp / "mdbx.dat"
        fd = os.open(str(self.file), os.O_RDWR | os.O_CREAT, 0o644)
        os.pwrite(fd, b"\x33" * (64 * PS), 0)
        os.ftruncate(fd, 128 * PS)
        os.close(fd)
        res = residency(str(self.file))
        if res != b"\x01" * 64 + b"\x00" * 64:
            self.skipTest("scratch file residency is not as written (memory pressure?)")
        self.proc = self.tmp / "proc"
        (self.proc / "77").mkdir(parents=True)
        st = os.stat(str(self.file))
        (self.proc / "77" / "maps").write_text(
            "00400000-00401000 r-xp 00000000 00:00 0 /usr/bin/telcoin\n"
            "%x-%x rw-s 00000000 %02x:%02x %d /home/nonroot/db/mdbx.dat\n"
            % (self.VBASE, self.VBASE + 128 * PS, os.major(st.st_dev), os.minor(st.st_dev), st.st_ino))

    def tearDown(self):
        self._tmp.cleanup()

    def write_tree(self, pagemap, kflags, kpageflags=True):
        with open(str(self.proc / "77" / "pagemap"), "wb") as f:
            for i, entry in pagemap.items():
                f.seek((self.VBASE // PS + i) * 8)
                f.write(struct.pack("=Q", entry))
        if kpageflags:
            with open(str(self.proc / "kpageflags"), "wb") as f:
                for pfn, flags in kflags.items():
                    f.seek(pfn * 8)
                    f.write(struct.pack("=Q", flags))
                f.seek(0x8000 * 8)
                f.write(struct.pack("=Q", 0))

    def layout(self):
        P = 1 << 63
        pm, kf = {}, {}
        for i in range(8):  # order 3, every page mapped, head dirty and active
            pm[i] = P | (0x1000 + i)
            kf[0x1000 + i] = self.TAIL
        kf[0x1000] = self.HEAD | self.LRU | self.DIRTY | self.ACTIVE
        pm[10] = P | 0x2002  # order 2, only a tail mapped; head under writeback
        kf.update({0x2000: self.HEAD | self.LRU | self.WRITEBACK, 0x2001: self.TAIL, 0x2002: self.TAIL,
                   0x2003: self.TAIL})
        pm[12] = P | 0x3000  # order 0, dirty
        kf[0x3000] = self.LRU | self.DIRTY
        pm[13] = P | 0x3005  # order 0
        kf[0x3005] = self.LRU
        pm[16] = P | 0x4000  # order 5, only the head mapped (pages 16-47)
        kf[0x4000] = self.HEAD | self.LRU
        for k in range(1, 32):
            kf[0x4000 + k] = self.TAIL
        pm[48] = P | 0x5000  # an anonymous frame: not a page of the file
        kf[0x5000] = self.ANON
        pm[70] = P | 0x6000  # a mapped page of the hole that mincore says is not resident: ignored
        kf[0x6000] = self.HEAD
        return pm, kf

    def census(self, *extra):
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.file), "--proc", str(self.proc)] + list(extra),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return [line.split(",") for line in p.stdout.splitlines()]

    def test_folio_orders_and_flags(self):
        self.write_tree(*self.layout())
        rows = self.census("--pid", "77", "--header")
        self.assertEqual(",".join(rows[0]) + "\n", FOLIO_HEADER)
        body = rows[1:]
        for r in body:
            self.assertEqual(len(r), 10)
            self.assertEqual(r[0], body[0][0])
            self.assertEqual(r[2:5], [str(128 * PS), "64", "18"])  # unresolved: pages 14-15 and 48-63
        self.assertEqual([r[5:] for r in body], [
            ["0", "2", "1", "0", "0"],
            ["2", "1", "0", "1", "0"],
            ["3", "1", "1", "0", "1"],
            ["5", "1", "0", "0", "0"],
        ])

    def test_single_page_folios_fast_path(self):
        # Every mapped frame a single-page file folio (an advised DB): the segment takes the fast path.
        P = 1 << 63
        pm, kf = {}, {}
        for i in range(64):
            if i == 5:
                continue  # resident but not mapped by the writer
            pfn = 0x9000 + 37 * i  # scattered frames, several kpageflags blocks
            pm[i] = P | pfn
            kf[pfn] = self.LRU | (self.DIRTY if i % 4 == 0 else 0) | (self.WRITEBACK if i % 8 == 1 else 0) \
                | (self.ACTIVE if i % 2 else 0)
        self.write_tree(pm, kf)
        (row,) = self.census("--pid", "77")
        self.assertEqual(row[2:], [str(128 * PS), "64", "1", "0", "63", "16", "8", "31"])
        # A frame number above 2**32 takes the generic entry decoding; past the table it stays unresolved.
        pm[3] = P | (1 << 33)
        self.write_tree(pm, kf)
        (row,) = self.census("--pid", "77")
        self.assertEqual(row[2:], [str(128 * PS), "64", "2", "0", "62", "16", "8", "30"])

    def test_block_reads_match_the_whole_table(self):
        # A host with more RAM than FLAT_MAX_ENTRIES covers reads kpageflags by block, per page.
        def both():
            flat = census_mod.census(str(self.file), "77", str(self.proc), 30)
            saved = census_mod.FLAT_MAX_ENTRIES
            census_mod.FLAT_MAX_ENTRIES = 0
            try:
                blocks = census_mod.census(str(self.file), "77", str(self.proc), 30)
            finally:
                census_mod.FLAT_MAX_ENTRIES = saved
            return [r[2:] for r in flat], [r[2:] for r in blocks]
        self.write_tree(*self.layout())
        fd = os.open(str(self.proc / "kpageflags"), os.O_RDONLY)
        try:
            self.assertIsNone(census_mod.KpageFlags(fd, 0).flat)
            self.assertEqual(len(census_mod.KpageFlags(fd).flat), 0x8001)
        finally:
            os.close(fd)
        flat, blocks = both()
        self.assertEqual(len(flat), 4)
        self.assertEqual(blocks, flat)
        P = 1 << 63
        self.write_tree({i: P | (0x9000 + 37 * i) for i in range(64)}, {0x9000 + 37 * i: self.LRU for i in range(64)})
        flat, blocks = both()
        self.assertEqual(flat, [[str(128 * PS), "64", "0", "0", "64", "0", "0", "0"]])
        self.assertEqual(blocks, flat)

    def test_no_frame_numbers_means_all_unresolved(self):
        pm, kf = self.layout()
        self.write_tree({i: (e & ~((1 << 55) - 1)) for i, e in pm.items()}, kf)  # present, frame 0
        (row,) = self.census("--pid", "77")
        self.assertEqual(row[2:], [str(128 * PS), "64", "64", "", "", "", "", ""])

    def test_no_kpageflags_means_all_unresolved(self):
        self.write_tree(*self.layout(), kpageflags=False)
        (row,) = self.census("--pid", "77")
        self.assertEqual(row[2:], [str(128 * PS), "64", "64", "", "", "", "", ""])

    def test_no_pid_means_all_unresolved(self):
        self.write_tree(*self.layout())
        (row,) = self.census()
        self.assertEqual(row[2:], [str(128 * PS), "64", "64", "", "", "", "", ""])

    def test_no_resident_page_row(self):
        sparse = self.tmp / "sparse.dat"
        with open(str(sparse), "wb") as f:
            f.truncate(1 << 20)
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(sparse), "--header"], stdout=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        lines = p.stdout.splitlines()
        self.assertEqual(lines[0] + "\n", FOLIO_HEADER)
        self.assertEqual(len(lines), 2)
        row = lines[1].split(",")
        self.assertEqual(len(row), 10)
        self.assertTrue(row[0].isdigit())
        float(row[1])
        self.assertEqual(row[2:], [str(1 << 20), "0", "0", "", "", "", "", ""])

    def test_missing_file_row(self):
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.tmp / "nope")], stdout=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0)
        row = p.stdout.strip().split(",")
        self.assertEqual(len(row), 10)
        self.assertEqual(row[2:], [""] * 8)

    def test_deadline_still_writes_a_row(self):
        self.write_tree(*self.layout())
        (row,) = self.census("--pid", "77", "--deadline-secs", "0")
        self.assertEqual(len(row), 10)
        self.assertEqual(row[2], str(128 * PS))
        self.assertEqual(row[3:], ["", "", "", "", "", "", ""])

    def test_out_appends_with_one_header(self):
        self.write_tree(*self.layout())
        out = self.tmp / "h.folios.txt"
        self.census("--pid", "77", "--out", str(out))
        self.census("--out", str(out))
        lines = out.read_text().splitlines()
        self.assertEqual(lines[0] + "\n", FOLIO_HEADER)
        self.assertEqual(len(lines), 1 + 4 + 1)
        self.assertEqual(lines.count(FOLIO_HEADER.strip()), 1)
        out.write_text("ts,other\n1,2\n")
        self.census("--out", str(out))
        self.assertEqual(out.read_text().splitlines()[0] + "\n", FOLIO_HEADER)
        self.assertEqual(len([p for p in self.tmp.iterdir() if p.name.startswith("h.folios.txt.old-")]), 1)

    def test_resident_only(self):
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.file), "--resident-only"],
                           stdout=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.stdout, "64\n")
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.file), "--resident-only",
                            "--from-bytes", str(60 * PS - 1)], stdout=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.stdout, "4\n")  # pages 60-63: the partly used page 59 does not count
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.tmp / "nope"), "--resident-only"],
                           stdout=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (1, "\n"))

    def test_writer_mappings_match_rule(self):
        st = os.stat(str(self.file))
        dev = "%02x:%02x" % (os.major(st.st_dev), os.minor(st.st_dev))
        (self.proc / "77" / "maps").write_text(
            "1000-3000 r--s 00002000 %s %d /x/mdbx.dat\n"
            "5000-6000 r--s 00000000 fe:00 %d /home/nonroot/db/mdbx.dat\n"
            "7000-8000 r--s 00000000 fe:00 %d /home/nonroot/db/other\n"
            "9000-a000 r--s 00000000 %s %d /x/mdbx.dat\n" % (dev, st.st_ino, st.st_ino, st.st_ino, dev, st.st_ino + 1))
        maps = census_mod.writer_mappings(str(self.proc), "77", st, str(self.file), 4096)
        self.assertEqual(maps, [(0x1000, 0x3000, 2), (0x5000, 0x6000, 0)])

    # ---- bench7 HB-3: a static file summed in, and nothing of a target ever read ----
    def static_file(self, pages=16):
        static = self.tmp / "static_files"
        static.mkdir(exist_ok=True)
        f = static / "static_file_receipts_0_499999"
        with open(str(f), "wb") as fh:
            fh.write(b"\x44" * (pages * PS))
        if sum(residency(str(f))) != pages:
            self.skipTest("scratch file residency is not as written (memory pressure?)")
        return f

    def test_a_static_target_is_summed_into_the_same_rows(self):
        self.write_tree(*self.layout())
        f = self.static_file()
        p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.file), "--static-dir", str(f.parent),
                            "--proc", str(self.proc), "--pid", "77"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        body = [line.split(",") for line in p.stdout.splitlines()]
        for r in body:
            # the writer does not map the static file: its 16 resident pages are unresolved
            self.assertEqual(r[2:5], [str(128 * PS + 16 * PS), str(64 + 16), str(18 + 16)])
        self.assertEqual([r[5:] for r in body], [["0", "2", "1", "0", "0"], ["2", "1", "0", "1", "0"],
                                                 ["3", "1", "1", "0", "1"], ["5", "1", "0", "0", "0"]])

    def test_the_census_never_reads_a_target(self):
        """Only open, fstat and a PROT_NONE mapping touch the store's files: no read, no other mapping."""
        self.write_tree(*self.layout())
        f = self.static_file()
        live, opened, bad = set(), [], []      # the target descriptors open now; every target opened
        real_open, real_noatime, real_libc, real_close = open, census_mod.open_noatime, census_mod._libc, os.close

        def noatime(path):
            fd = real_noatime(path)
            live.add(fd)
            opened.append(path)
            return fd

        def close(fd):
            live.discard(fd)
            return real_close(fd)

        def guard(name, fn):
            def call(fd, *a, **k):
                if fd in live:
                    bad.append((name, fd))
                return fn(fd, *a, **k)
            return call

        def guarded_open(file, *a, **k):
            if str(file) in (str(self.file), str(f)):
                bad.append(("open", str(file)))
            return real_open(file, *a, **k)

        class Libc(object):
            def __getattr__(self, name):
                return getattr(real_libc, name)

            def mmap(self, addr, length, prot, flags, fd, off):
                if prot != census_mod.PROT_NONE:
                    bad.append(("mmap", prot))
                return real_libc.mmap(addr, length, prot, flags, fd, off)

        patches = [mock.patch.object(census_mod, "open_noatime", noatime), mock.patch.object(census_mod, "_libc", Libc()),
                   mock.patch("builtins.open", guarded_open), mock.patch.object(os, "close", close)]
        for name in ("read", "pread", "readv", "preadv"):
            if hasattr(os, name):
                patches.append(mock.patch.object(os, name, guard(name, getattr(os, name))))
        for x in patches:
            x.start()
        try:
            rows = census_mod.census(str(self.file), "77", str(self.proc), 30, [str(f)])
        finally:
            for x in reversed(patches):
                x.stop()
        self.assertEqual(opened, [str(self.file), str(f)])
        self.assertEqual((bad, live), ([], set()))
        self.assertEqual([r[5] for r in rows], ["0", "2", "3", "5"])


class CensusTargetsTests(unittest.TestCase):
    """The census's targets (bench 7): --data-dir picks them by what the data dir holds, --static-dir sums a
    directory in, the store file missing makes the empty row, and every row any census writes parses."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="census-targets-")
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"
        (self.data / "db").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, path, written, total):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        os.pwrite(fd, b"\x21" * (written * PS), 0) if written else None
        os.ftruncate(fd, total * PS)
        os.close(fd)
        return sum(residency(str(path)))

    def census(self, *args, rc=0):
        p = subprocess.run([sys.executable, str(CENSUS)] + [str(a) for a in args], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, rc, p.stderr)
        return [line.split(",") for line in p.stdout.splitlines()]

    def test_data_dir_picks_the_store(self):
        res_m = self.put(self.data / "db" / "mdbx.dat", 3, 10)
        (row,) = self.census("--data-dir", self.data)
        self.assertEqual(row[2:], [str(10 * PS), str(res_m), str(res_m), "", "", "", "", ""])
        res_l = self.put(self.data / "db" / "tn-lmdb.dat", 5, 20)
        res_s = self.put(self.data / "static_files" / "static_file_headers_0_499999", 2, 2)
        res_s += self.put(self.data / "static_files" / "sub" / "x.conf", 1, 1)
        (row,) = self.census("--data-dir", self.data)          # tn-lmdb wins, the static files summed in
        self.assertEqual(row[2:5], [str((20 + 2 + 1) * PS), str(res_l + res_s), str(res_l + res_s)])
        self.assertEqual(self.census("--data-dir", self.data, "--resident-only"), [[str(res_l)]])
        empty = self.tmp / "empty"
        (empty / "db").mkdir(parents=True)
        (row,) = self.census("--data-dir", empty)
        self.assertEqual((len(row), row[2:]), (10, [""] * 8))
        self.assertEqual(self.census("--data-dir", empty, "--resident-only", rc=1), [[""]])

    def test_static_dir_is_optional_and_needs_the_store_file(self):
        f = self.data / "db" / "tn-lmdb.dat"
        res = self.put(f, 2, 4)
        (row,) = self.census("--file", f, "--static-dir", self.tmp / "absent")
        self.assertEqual(row[2:5], [str(4 * PS), str(res), str(res)])
        self.put(self.data / "static_files" / "a", 1, 3)
        (row,) = self.census("--file", self.data / "db" / "gone.dat", "--static-dir", self.data / "static_files")
        self.assertEqual(row[2:], [""] * 8)

    def test_arguments(self):
        f = self.data / "db" / "tn-lmdb.dat"
        self.put(f, 1, 1)
        for args in ((), ("--file", f, "--data-dir", self.data), ("--data-dir", self.data, "--static-dir", self.data)):
            with self.subTest(args=args):
                self.census(*args, rc=2)

    def test_every_row_parses(self):
        f = self.data / "db" / "tn-lmdb.dat"
        self.put(f, 4, 8)
        self.put(self.data / "static_files" / "a", 1, 1)
        rows = []
        for args in (("--file", self.data / "nope"), ("--data-dir", self.data), ("--file", f, "--deadline-secs", "0"),
                     ("--data-dir", self.tmp)):
            rows += self.census(*args)
        text = census_mod.HEADER + "\n" + "".join(",".join(r) + "\n" for r in rows)
        import csv as _csv
        import io as _io
        n = 0
        for r in _csv.DictReader(_io.StringIO(text)):
            n += 1
            self.assertEqual(len(r), 10)
            self.assertNotIn(None, r)
            for k, v in r.items():
                self.assertRegex(v, r"^(?:[0-9]+(?:\.[0-9]+)?)?$", k)
            if r["folio_order"] == "":
                self.assertEqual([r[k] for k in ("folios", "dirty_folios", "writeback_folios", "active_folios")], [""] * 4)
        self.assertEqual(n, 4)

    def test_clean(self):
        clean = census_mod.clean
        self.assertEqual(clean(["1", "0.5", "x", "-3", "", "2", "1", "0", "0", "0", "extra"]),
                         ["1", "0.5", "", "", "", "2", "1", "0", "0", "0"])
        self.assertEqual(clean(["1", "0.1", "8", "2", "2", "", "5", "1", "1", "1"]), ["1", "0.1", "8", "2", "2"] + [""] * 5)
        self.assertEqual(clean(["1", "0.1"]), ["1", "0.1"] + [""] * 8)
        self.assertEqual(clean(["1", "None", "nan", "2", "2", "0", "1", "0", "0", "0"]),
                         ["1", "", "", "2", "2", "0", "1", "0", "0", "0"])


class RealFileSmokeTests(unittest.TestCase):
    """A live writer maps a disk-backed scratch file; censuses and sampler ticks must not change residency."""

    def setUp(self):
        candidates = [os.environ.get("PERSIST_SMOKE_DIR", ""), tempfile.gettempdir(), str(BENCH / "work")]
        base = next((c for c in candidates if c and os.path.isdir(c) and os.access(c, os.W_OK)
                     and fs_type(os.path.realpath(c)) not in ("tmpfs", "ramfs", None)), None)
        if base is None:
            self.skipTest("no disk-backed scratch directory (set PERSIST_SMOKE_DIR)")
        self._tmp = tempfile.TemporaryDirectory(prefix="persist-smoke-", dir=base)
        self.tmp = Path(self._tmp.name)
        (self.tmp / "data" / "db").mkdir(parents=True)
        self.file = self.tmp / "data" / "db" / "mdbx.dat"
        fd = os.open(str(self.file), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            data = os.urandom(512 * PS)
            for i in range(512):  # one page per write: single-page folios, which DONTNEED below can drop
                os.pwrite(fd, data[i * PS:(i + 1) * PS], i * PS)
            os.fsync(fd)
            os.posix_fadvise(fd, 128 * PS, 256 * PS, os.POSIX_FADV_DONTNEED)  # pages 128-383: on disk, not cached
            os.ftruncate(fd, 768 * PS)  # pages 512-767: a hole
        finally:
            os.close(fd)
        self.writer = None

    def tearDown(self):
        if self.writer is not None:
            self.writer.kill()
            self.writer.wait()
            self.writer.stdout.close()
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def start_writer(self):
        code = ("import mmap, os, sys, time\n"
                "fd = os.open(sys.argv[1], os.O_RDWR)\n"
                "m = mmap.mmap(fd, os.fstat(fd).st_size)\n"
                "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
                "i = 0\n"
                "while True:\n"
                "    m[(i % 16) * 4096] = i & 255\n"
                "    i += 1\n"
                "    time.sleep(0.002)\n")
        self.writer = subprocess.Popen([sys.executable, "-c", code, str(self.file)], stdout=subprocess.PIPE,
                                       universal_newlines=True)
        self.assertEqual(self.writer.stdout.readline(), "ready\n")
        time.sleep(0.05)

    def before(self):
        res = residency(str(self.file))
        if res[128:384] != b"\x00" * 256 or res[:16] != b"\x01" * 16:
            self.skipTest("could not set up the eviction pattern on this file system")
        return res

    def assert_unchanged(self, res0):
        res1 = residency(str(self.file))
        faulted = [i for i in range(len(res0)) if res1[i] and not res0[i]]
        self.assertEqual(faulted, [], "pages became resident")
        dropped = [i for i in range(len(res0)) if res0[i] and not res1[i]]
        self.assertEqual(dropped, [], "pages left the page cache (memory pressure on the host?)")

    def test_five_censuses_leave_residency_unchanged(self):
        self.start_writer()
        res0 = self.before()
        for _ in range(5):
            p = subprocess.run([sys.executable, str(CENSUS), "--file", str(self.file), "--pid", str(self.writer.pid)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            (row,) = [line.split(",") for line in p.stdout.splitlines()]
            self.assertEqual(row[2:4], [str(768 * PS), str(sum(res0))])
        self.assert_unchanged(res0)

    def test_five_sampler_ticks_leave_residency_unchanged(self):
        self.start_writer()
        res0 = self.before()
        shim = self.tmp / "bin"
        shim.mkdir()
        (shim / "sleep").write_text("#!/bin/sh\nexit 0\n")
        (shim / "sleep").chmod(0o755)
        out = self.tmp / "out"
        env = {"PATH": str(shim) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
               "PERSIST_DATA_DIR": str(self.tmp / "data"), "PERSIST_PID": str(self.writer.pid),
               "PERSIST_OUT_DIR": str(out), "PERSIST_HOST": "smoke", "PERSIST_INTERVAL_SECS": "30",
               "PERSIST_MDBX_EVERY_SECS": "30", "PERSIST_CENSUS_EVERY_SECS": "30", "PERSIST_TICKS": "5",
               "PERSIST_CENSUS": str(CENSUS), "PERSIST_METRICS_URL": "file://" + str(self.tmp / "metrics.txt")}
        (self.tmp / "metrics.txt").write_text("tn_reth_mdbx_used_bytes %d\n" % (300 * PS))
        p = subprocess.run(["bash", str(SAMPLER)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assert_unchanged(res0)
        rows = [line.split(",") for line in (out / "smoke.persist.csv").read_text().splitlines()[1:]]
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(len(row), NCOLS)
            self.assertEqual(row[COL["pid"]], str(self.writer.pid))
            self.assertEqual(row[COL["mdbx_dat_resident_pages"]], str(sum(res0)))
            self.assertEqual(row[COL["mdbx_dat_vma_bytes"]], str(768 * PS))
            self.assertEqual(row[COL[PAST]], str(sum(res0[300:])))  # pages 384-511: 128
        folios = (out / "smoke.folios.txt").read_text().splitlines()
        self.assertEqual(len(folios), 1 + 5)


    def test_five_sampler_ticks_on_tn_lmdb_leave_residency_unchanged(self):
        """Bench 7: the same file as db/tn-lmdb.dat, a static file beside it; ticks and censuses fault nothing in."""
        lmdb = self.file.parent / "tn-lmdb.dat"
        os.rename(str(self.file), str(lmdb))
        self.file = lmdb
        static = self.tmp / "data" / "static_files"
        static.mkdir()
        (static / "static_file_headers_0_499999").write_bytes(b"h" * 4096)
        self.start_writer()
        res0 = self.before()
        shim = self.tmp / "bin"
        shim.mkdir()
        (shim / "sleep").write_text("#!/bin/sh\nexit 0\n")
        (shim / "sleep").chmod(0o755)
        out = self.tmp / "out"
        (self.tmp / "metrics.txt").write_text(LMDB_METRICS)
        env = {"PATH": str(shim) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
               "PERSIST_DATA_DIR": str(self.tmp / "data"), "PERSIST_PID": str(self.writer.pid),
               "PERSIST_OUT_DIR": str(out), "PERSIST_HOST": "smoke", "PERSIST_INTERVAL_SECS": "30",
               "PERSIST_MDBX_EVERY_SECS": "30", "PERSIST_CENSUS_EVERY_SECS": "30", "PERSIST_TICKS": "5",
               "PERSIST_CENSUS": str(CENSUS), "PERSIST_METRICS_URL": "file://" + str(self.tmp / "metrics.txt")}
        p = subprocess.run(["bash", str(SAMPLER)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assert_unchanged(res0)
        rows = [line.split(",") for line in (out / "smoke.persist.csv").read_text().splitlines()[1:]]
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row[COL["tn_lmdb_dat_resident_pages"]], str(sum(res0)))
            self.assertEqual(row[COL["tn_lmdb_dat_vma_bytes"]], str(768 * PS))
            self.assertEqual(row[COL["tn_lmdb_used_bytes"]], str(LMDB_USED))
            self.assertEqual([row[COL[c]] for c in MDBX_COLS], [""] * 5)
        self.assertEqual(len((out / "smoke.folios.txt").read_text().splitlines()), 1 + 5)


if __name__ == "__main__":
    unittest.main()
