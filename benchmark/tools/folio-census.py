#!/usr/bin/env python3
"""Folio-order census of one file's page cache that never faults a page of the file in.

The bench-6 persist sampler (benchmark/node-persist-sampler.sh) runs it as root every 900 s against the
node's mdbx.dat and appends the rows to <host>.folios.txt. Columns (frozen in
benchmark/tools/folio-census-header.txt):

    ts_unix,census_secs,mdbx_dat_size_bytes,mdbx_dat_resident_pages,unresolved_pages,
    folio_order,folios,dirty_folios,writeback_folios,active_folios

One row per folio order found, orders ascending; ts_unix, census_secs, the size, resident and unresolved
pages repeat on every row of one census. A census that resolves no folio (no resident page, or none it
could resolve) writes one row with the five order columns empty, so every census leaves at least one row.
A field that could not be read is empty.

How it reads the page cache without touching it:
- Residency: mincore(2) on this process's own PROT_NONE, MAP_PRIVATE mapping of the file, one 1 GiB
  window at a time (what util-linux fincore does). The mapping grants no access at all: a stray access
  would be SIGSEGV, never a read of the file. The file is opened O_RDONLY|O_NOATIME and never read.
- Folio order: the page frame of a resident page comes from the WRITER's page table: --pid names the
  process that maps the file (the node), and /proc/<pid>/pagemap is read over that process's mappings of
  the file (matched by inode, and by device or file name). /proc/kpageflags then gives the frame's flags:
  COMPOUND_HEAD / COMPOUND_TAIL give the folio's size (folios are naturally aligned powers of two), and
  DIRTY, WRITEBACK and ACTIVE are read on the head page.
- Both need root: /proc/kpageflags is mode 0400 root, and pagemap reports page frame numbers only to
  CAP_SYS_ADMIN (others read 0). Without them, or for a resident page the writer has not mapped (cached
  before the writer started, written with pwrite and not yet touched through the map, or read ahead and
  never accessed), the page counts as unresolved. Before the node starts nothing is resolvable.
- mincore reports page-cache residency of a file mapping only to the file's owner, a writer of it or
  CAP_FOWNER; for anyone else the kernel reports every page resident, so the census then leaves the
  resident and unresolved columns empty.

Bounded: the residency scan and the resolution stop at --deadline-secs (default 12). Pages the
resolution has not reached by then count as unresolved; a residency scan cut short leaves the resident
and unresolved columns empty. census_secs shows the time taken. The rows of one census are written with
one write(2) at the end, so a killed census leaves no partial census. Cost, measured on a 4 GiB file held
whole in the page cache, against a fake writer whose frames are scattered single pages (the slowest
shape): 0.45-0.48 s and 69 MB of memory (kpageflags is read whole, 8 bytes per frame of RAM, when the
host has at most 32 GiB; otherwise in 4 KiB blocks on demand).

Usage:
    folio-census.py --file PATH [--pid PID] [--proc DIR] [--out FILE | --header] [--deadline-secs S]
    folio-census.py --file PATH --resident-only [--from-bytes N]

--out FILE appends the rows to FILE and writes the header first when FILE is new or empty (a FILE whose
first line is another header is moved aside to FILE.old-<ts>). Without --out the rows go to stdout,
after the header when --header is given. --resident-only prints the number of resident pages (from byte
--from-bytes on, rounded up to a page) and nothing else; an empty line and exit 1 when residency cannot
be read. --proc is the /proc to read pagemap and kpageflags from (tests point it at a fake tree).
"""
import argparse
import ctypes
import ctypes.util
import os
import re
import sys
import time
from array import array
from collections import Counter
from itertools import compress

HEADER = ("ts_unix,census_secs,mdbx_dat_size_bytes,mdbx_dat_resident_pages,unresolved_pages,"
          "folio_order,folios,dirty_folios,writeback_folios,active_folios")

# /proc/kpageflags bits (include/uapi/linux/kernel-page-flags.h).
KPF_DIRTY = 1 << 4
KPF_ACTIVE = 1 << 6
KPF_SLAB = 1 << 7
KPF_WRITEBACK = 1 << 8
KPF_ANON = 1 << 12
KPF_COMPOUND_HEAD = 1 << 15
KPF_COMPOUND_TAIL = 1 << 16
KPF_NOPAGE = 1 << 20
NOT_FILE = KPF_SLAB | KPF_ANON | KPF_NOPAGE

# /proc/<pid>/pagemap entry: bit 63 present, bits 0-54 the page frame number.
PM_PRESENT = 1 << 63
PM_PFN_MASK = (1 << 55) - 1

MAX_ORDER = 13           # the largest folio searched for (PMD order with 64 KiB pages); x86-64 caps at 9
WINDOW_PAGES = 1 << 18   # mincore window (1 GiB with 4 KiB pages); aligned, so no folio straddles two
SEGMENT_PAGES = 1 << 16  # pagemap read size (512 KiB of entries); the deadline is checked per segment
FLAT_MAX_ENTRIES = 1 << 23  # kpageflags is read whole up to 32 GiB of RAM (a 64 MiB table), else by block
PROT_NONE = 0
MAP_PRIVATE = 2
RESIDENT_BIT = bytes(b & 1 for b in range(256))  # mincore's vector: bit 0 is residency, the rest reserved
PRESENT_BIT = bytes(1 if b & 0x80 else 0 for b in range(256))  # the top byte of a pagemap entry: bit 63
LOW7 = bytes(b & 0x7F for b in range(256))  # the top byte's PFN bits (48-54)

_libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
_libc.mmap.restype = ctypes.c_void_p
_libc.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_long)
_libc.munmap.restype = ctypes.c_int
_libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
_libc.mincore.restype = ctypes.c_int
_libc.mincore.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
MAP_FAILED = ctypes.c_void_p(-1).value


def page_size():
    return os.sysconf("SC_PAGE_SIZE")


def open_noatime(path):
    """An O_RDONLY descriptor, O_NOATIME when allowed (owner or CAP_FOWNER), so the census writes nothing."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags | getattr(os, "O_NOATIME", 0))
    except PermissionError:
        return os.open(path, flags)


def mincore_trusted(path, st):
    """True when the kernel reports real residency to this process: root (CAP_FOWNER), the owner or a writer."""
    return os.geteuid() == 0 or st.st_uid == os.geteuid() or os.access(path, os.W_OK)


def residency(fd, size, ps, deadline=None):
    """[(first_page, vector)] per window: one byte per page, 1 = in the page cache. None past the deadline.

    Each window is mapped PROT_NONE / MAP_PRIVATE, asked with mincore and unmapped; nothing dereferences it.
    """
    out = []
    pages = (size + ps - 1) // ps
    first = 0
    while first < pages:
        if deadline is not None and time.monotonic() > deadline:
            return None
        n = min(WINDOW_PAGES, pages - first)
        length = n * ps
        addr = _libc.mmap(None, length, PROT_NONE, MAP_PRIVATE, fd, first * ps)
        if addr is None or addr == MAP_FAILED:
            err = ctypes.get_errno()
            raise OSError(err, "mmap: " + os.strerror(err))
        try:
            vec = bytearray(n)
            buf = (ctypes.c_char * n).from_buffer(vec)
            if _libc.mincore(addr, length, ctypes.addressof(buf)) != 0:
                err = ctypes.get_errno()
                raise OSError(err, "mincore: " + os.strerror(err))
            del buf
        finally:
            _libc.munmap(addr, length)
        out.append((first, bytes(vec).translate(RESIDENT_BIT)))
        first += n
    return out


def writer_mappings(proc, pid, st, path, ps):
    """[(vaddr_start, vaddr_end, first_file_page)] of the writer's mappings of the file, from its maps."""
    maps = []
    suffix = "/" + os.path.basename(path)
    want_dev = (os.major(st.st_dev), os.minor(st.st_dev))
    try:
        with open(os.path.join(proc, str(pid), "maps")) as f:
            lines = f.read().splitlines()
    except OSError:
        return maps
    for line in lines:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            ino = int(parts[4])
            if ino != st.st_ino:
                continue
            major, minor = (int(x, 16) for x in parts[3].split(":"))
            start, end = (int(x, 16) for x in parts[0].split("-"))
            offset = int(parts[2], 16)
        except ValueError:
            continue
        if (major, minor) != want_dev and not parts[5].endswith(suffix):
            continue
        maps.append((start, end, offset // ps))
    return maps


class KpageFlags:
    """/proc/kpageflags: read whole into one table when it holds at most flat_max entries, else in
    512-entry blocks on demand (an aligned block holds any folio up to order 9)."""

    def __init__(self, fd, flat_max=None):
        self.fd = fd
        self.blocks = {}
        self.flat = self._read_all(FLAT_MAX_ENTRIES if flat_max is None else flat_max)

    def _read_all(self, flat_max):
        table = array("Q")
        while True:
            data = os.pread(self.fd, 8 << 20, 8 * len(table))
            if len(data) < 8:
                return table
            table.frombytes(data[:len(data) // 8 * 8])
            if len(table) > flat_max:
                return None

    def get(self, pfn):
        """The flags of frame pfn, or None past the end of the table."""
        if self.flat is not None:
            return self.flat[pfn] if pfn < len(self.flat) else None
        entries = self.blocks.get(pfn >> 9)
        if entries is None:
            data = os.pread(self.fd, 4096, (pfn >> 9) << 12)
            entries = array("Q")
            entries.frombytes(data[:len(data) // 8 * 8])
            self.blocks[pfn >> 9] = entries
        i = pfn & 511
        return entries[i] if i < len(entries) else None


def folio_of(flags, pfn):
    """(head_pfn, order, head_flags) of the folio holding frame pfn, or None when it cannot be told."""
    f = flags.get(pfn)
    if f is None or f & NOT_FILE:
        return None
    if f & KPF_COMPOUND_TAIL:
        head = None
        for k in range(1, MAX_ORDER + 1):
            c = pfn & ~((1 << k) - 1)
            fc = flags.get(c)
            if fc is None:
                return None
            if fc & KPF_COMPOUND_HEAD:
                head, f = c, fc
                break
            if not fc & KPF_COMPOUND_TAIL:
                return None
        if head is None:
            return None
    elif f & KPF_COMPOUND_HEAD:
        head = pfn
    else:
        return pfn, 0, f
    order = 0
    while order < MAX_ORDER:
        ft = flags.get(head + (1 << order))
        if ft is None or not ft & KPF_COMPOUND_TAIL or ft & KPF_COMPOUND_HEAD:
            break
        order += 1
    if pfn - head >= (1 << order):
        return None  # the frame is not inside the folio found (a split or free raced the reads)
    return head, order, f


def pagemap_bytes(pm_fd, maps, first, count, ps):
    """The writer's raw pagemap entries (8 native bytes each) for file pages [first, first + count);
    zero where nothing maps them."""
    out = bytearray(8 * count)
    last = first + count
    for start, end, fpage in maps:
        lo = max(first, fpage)
        hi = min(last, fpage + (end - start) // ps)
        if lo >= hi:
            continue
        data = os.pread(pm_fd, 8 * (hi - lo), (start // ps + (lo - fpage)) * 8)
        n = len(data) // 8 * 8
        out[8 * (lo - first):8 * (lo - first) + n] = data[:n]
    return bytes(out)


def mapped_frames(raw):
    """(mask with one byte per entry, 1 = mapped; the frame of every mapped entry, in file order).

    On little-endian hosts with frames below 2**32 (16 TiB of RAM) this runs on byte slices, translate
    and compress, all C-level: a Python loop over the entries costs about 2 us a page, which on a large
    resident file is most of the census."""
    n = len(raw) // 8
    if sys.byteorder == "little" and raw[4::8].count(0) == n and raw[5::8].count(0) == n \
            and raw[6::8].translate(LOW7).count(0) == n:
        present = raw[7::8].translate(PRESENT_BIT)
        return present, list(compress(memoryview(raw).cast("I")[0::2].tolist(), present))
    ent = array("Q")
    ent.frombytes(raw)
    return bytes(1 if e & PM_PRESENT else 0 for e in ent), [e & PM_PFN_MASK for e in ent if e & PM_PRESENT]


def resolve(windows, maps, pm_fd, flags, ps, deadline):
    """({order: [folios, dirty, writeback, active]}, resolved resident pages)."""
    counts = {}
    if pm_fd is None or flags is None or not maps:
        return counts, 0
    large = 0  # resident pages resolved into folios of order 1 and up
    n0 = dirty0 = wb0 = active0 = 0  # single-page folios
    special = KPF_COMPOUND_HEAD | KPF_COMPOUND_TAIL | NOT_FILE
    getter = flags.flat.__getitem__ if flags.flat is not None else flags.get
    try:
        for base, vec in windows:
            straddling = set()  # heads of folios that run past the segment they were found in
            for run in re.finditer(b"\x01+", vec):
                a0, b0 = base + run.start(), base + run.end()
                seg = a0
                while seg < b0:
                    if time.monotonic() > deadline:
                        return counts, large + n0
                    a = seg
                    b = min(b0, (a // SEGMENT_PAGES + 1) * SEGMENT_PAGES)
                    seg = b
                    present, pfns = mapped_frames(pagemap_bytes(pm_fd, maps, a, b - a, ps))
                    if 0 in pfns:
                        return counts, large + n0  # no CAP_SYS_ADMIN: pagemap hides every frame
                    try:
                        fl = list(map(getter, pfns))
                    except IndexError:  # a frame past the end of the table
                        fl = list(map(flags.get, pfns))
                    # Single-page file folios (the shape an advised DB has) are tallied by flag value.
                    mixed = False
                    for f, k in Counter(fl).items():
                        if f is None:
                            continue
                        if f & special:
                            mixed = True
                            continue
                        n0 += k
                        dirty0 += k if f & KPF_DIRTY else 0
                        wb0 += k if f & KPF_WRITEBACK else 0
                        active0 += k if f & KPF_ACTIVE else 0
                    if not mixed:
                        continue
                    # Large folios (and frames that are not file pages): walk the special frames in
                    # file order; a folio's other frames are skipped once it is counted.
                    idx = list(compress(range(a, b), present))
                    covered = a  # file pages below this belong to a folio already counted
                    for k, f in enumerate(fl):
                        if f is None or not f & special or idx[k] < covered:
                            continue
                        found = folio_of(flags, pfns[k])
                        if found is None:
                            continue
                        head, order, hf = found
                        if order == 0:  # a head with no tail after it: a split raced the reads
                            n0 += 1
                            dirty0 += 1 if hf & KPF_DIRTY else 0
                            wb0 += 1 if hf & KPF_WRITEBACK else 0
                            active0 += 1 if hf & KPF_ACTIVE else 0
                            continue
                        start = idx[k] - (pfns[k] - head)
                        end = min(start + (1 << order), b)
                        large += end - max(start, covered)
                        covered = end
                        if head in straddling:
                            continue
                        if start + (1 << order) > b:
                            straddling.add(head)
                        c = counts.setdefault(order, [0, 0, 0, 0])
                        c[0] += 1
                        c[1] += 1 if hf & KPF_DIRTY else 0
                        c[2] += 1 if hf & KPF_WRITEBACK else 0
                        c[3] += 1 if hf & KPF_ACTIVE else 0
        return counts, large + n0
    finally:
        if n0:
            counts[0] = [n0, dirty0, wb0, active0]


def open_or_none(path):
    try:
        return os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None


def census(path, pid, proc, deadline_secs):
    """The rows (lists of strings) of one census of path."""
    t0 = time.time()
    m0 = time.monotonic()
    deadline = m0 + deadline_secs
    size = resident = unresolved = ""
    counts = {}
    ps = page_size()
    try:
        fd = open_noatime(path)
    except OSError:
        fd = None
    if fd is not None:
        try:
            st = os.fstat(fd)
            size = str(st.st_size)
            if mincore_trusted(path, st):
                windows = residency(fd, st.st_size, ps, deadline)
                if windows is not None:
                    total = sum(v.count(1) for _, v in windows)
                    resident = str(total)
                    pm_fd = flags_fd = None
                    try:
                        maps = writer_mappings(proc, pid, st, path, ps) if pid else []
                        if maps and total:
                            pm_fd = open_or_none(os.path.join(proc, str(pid), "pagemap"))
                            flags_fd = open_or_none(os.path.join(proc, "kpageflags"))
                        try:
                            flags = KpageFlags(flags_fd) if flags_fd is not None else None
                            counts, done = resolve(windows, maps, pm_fd, flags, ps, deadline)
                        except OSError:  # a /proc file that cannot be read: nothing resolved
                            counts, done = {}, 0
                    finally:
                        for x in (pm_fd, flags_fd):
                            if x is not None:
                                os.close(x)
                    unresolved = str(total - done)
        except OSError:
            pass
        finally:
            os.close(fd)
    secs = "%.3f" % (time.monotonic() - m0)
    lead = [str(int(t0)), secs, size, resident, unresolved]
    rows = [lead + [str(o)] + [str(x) for x in counts[o]] for o in sorted(counts)]
    return rows or [lead + ["", "", "", "", ""]]


def resident_only(path, from_bytes):
    """Resident pages of path at or past from_bytes (rounded up to a page), or None."""
    ps = page_size()
    try:
        fd = open_noatime(path)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not mincore_trusted(path, st):
            return None
        windows = residency(fd, st.st_size, ps)
    except OSError:
        return None
    finally:
        os.close(fd)
    skip = (from_bytes + ps - 1) // ps
    total = 0
    for base, vec in windows:
        if base + len(vec) <= skip:
            continue
        total += vec.count(1, max(0, skip - base))
    return total


def append_rows(out, text, ts):
    """Append text to out with one write; the header first when out is new or empty; a foreign header moves aside."""
    try:
        with open(out, "rb") as f:
            first = f.readline().rstrip(b"\n").decode("utf-8", "replace")
    except FileNotFoundError:
        first = None
    if first is not None and first != "" and first != HEADER:
        os.replace(out, "%s.old-%d" % (out, ts))
        sys.stderr.write("folio-census: %s had another header; moved to %s.old-%d\n" % (out, out, ts))
    fd = os.open(out, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        if os.fstat(fd).st_size == 0:
            text = HEADER + "\n" + text
        data = text.encode()
        while data:
            data = data[os.write(fd, data):]
    finally:
        os.close(fd)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Folio-order census of a file's page cache (never faults a page in).")
    ap.add_argument("--file", required=True, help="the file (the node's mdbx.dat)")
    ap.add_argument("--pid", default="", help="the process that maps the file (the node); empty = none")
    ap.add_argument("--proc", default="/proc", help="where to read <pid>/maps, <pid>/pagemap and kpageflags")
    ap.add_argument("--out", default="", help="append the rows here (header first when new or empty)")
    ap.add_argument("--header", action="store_true", help="stdout mode: print the header line first")
    ap.add_argument("--deadline-secs", type=float, default=12.0, help="stop resolving after this many seconds")
    ap.add_argument("--resident-only", action="store_true", help="print the resident page count only")
    ap.add_argument("--from-bytes", type=int, default=0, help="--resident-only: count from this byte on")
    args = ap.parse_args(argv)
    if args.pid and not args.pid.isdigit():
        ap.error("--pid must be a number")
    if args.resident_only:
        n = resident_only(args.file, max(0, args.from_bytes))
        print("" if n is None else n)
        return 0 if n is not None else 1
    rows = census(args.file, args.pid, args.proc, max(0.0, args.deadline_secs))
    text = "".join(",".join(r) + "\n" for r in rows)
    if args.out:
        append_rows(args.out, text, int(rows[0][0]))
    else:
        sys.stdout.write((HEADER + "\n" if args.header else "") + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
