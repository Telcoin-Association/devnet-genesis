"""Bench 6: the local-SSD data directory builders of bench-lib.sh, offline.

bench_lssd_mount_script and bench_lssd_check_script run on a fake node (Node): a temporary root with
dev/disk/by-id symlinks, /sys/block queue files, /etc/fstab and /var/lib under it, the scripts' paths
for those relocated there, and one python stub installed as findmnt, lsblk, mkfs.ext4, mount, umount,
readlink, stat, systemctl, udevadm and sleep. The stubs share a state file (state.json): the block
devices (size, file-system UUID and type), the mount table, failure switches, and a log of every call
with whether the marker existed at that moment. mount makes lost+found in its target, as a fresh ext4
shows it; umount always fails (nothing may unmount). The data directory is a real directory under the
root. Nothing here touches the real /dev, /etc, /sys or /var/lib.

bench_lssd_mount_record is fed lines; the probe driver's device id and mkfs options are read from
benchmark-probe.sh and must equal the mount script's; the C4 quota helpers are called directly.
"""
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
PROBE = BENCH / "benchmark-probe.sh"
INST = "bench-validator-03"
ROOT_OPTS = "discard,commit=30,errors=remount-ro"
SSD0 = "/dev/nvme1n1"
SSD1 = "/dev/nvme2n1"
SSD_BYTES = 375 * 1024 ** 3
NEW_UUID = "3f1c2b4a-0d5e-4f60-8a7b-1c2d3e4f5a6b"
OTHER_UUID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
MKFS_ARGS = ["-q", "-F", "-m", "0", "-E", "lazy_itable_init=0,lazy_journal_init=0,discard", SSD0]
FSTAB = ("LABEL=cloudimg-rootfs\t/\t ext4\t%s\t0 1\n"
         "LABEL=UEFI\t/boot/efi\tvfat\tumask=0077\t0 1\n") % ROOT_OPTS
TIMEOUT_SCALE = float(os.environ.get("BENCH_TEST_TIMEOUT_SCALE", "1") or "1")

# Paths the node scripts name, moved under the fake root (only where a path starts).
RELOCATED = ("/etc/", "/sys/", "/var/lib/bench-lssd", "/dev/disk/")
_START = r"(?<![\w/.~-])"

LIB_CALL = r'''
set -euo pipefail
lib="$1"; shift
argv=("$@")
source "$lib/bench-lib.sh"
"${argv[@]}"
'''

STUB = r'''#!@PYTHON@
"""A node tool on test_local_ssd.py's fake node; state and call log in $STUB_ROOT/state.json."""
import json, os, sys

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
root = os.environ["STUB_ROOT"]
path = os.path.join(root, "state.json")
with open(path) as f:
    st = json.load(f)
marker = os.path.join(root, "var/lib/bench-lssd/uuid")


def rel(p):
    return p[len(root):] if p.startswith(root + "/") else p


def done(rc=0, out=None):
    with open(path, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    if out is not None:
        sys.stdout.write(out)
    sys.exit(rc)


st["calls"].append({"tool": name, "args": [rel(a) for a in args], "marker": os.path.exists(marker)})


def parse(short_values, long_values):
    flags, opts, pos, i = set(), {}, [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            k, eq, v = a[2:].partition("=")
            if k in long_values and not eq:
                i += 1
                v = args[i]
            opts[k] = v if (eq or k in long_values) else True
        elif a.startswith("-") and len(a) > 1:
            for j, c in enumerate(a[1:]):
                if c in short_values:
                    v = a[j + 2:]
                    if not v:
                        i += 1
                        v = args[i]
                    opts[c] = v
                    break
                flags.add(c)
        else:
            pos.append(a)
        i += 1
    return flags, opts, pos


def under(t, m):
    return m == "/" or t == m or t.startswith(m + "/")


devs = st["devices"]
if name == "findmnt":
    flags, opts, pos = parse("o", ("output", "target", "mountpoint", "source"))
    cols = (opts.get("o") or opts.get("output") or "SOURCE,TARGET,FSTYPE,OPTIONS").split(",")
    if "s" in flags:
        rows = []
        with open(os.path.join(root, "etc/fstab")) as f:
            for line in f:
                w = line.split()
                if len(w) >= 4 and not w[0].startswith("#"):
                    rows.append({"SOURCE": w[0], "TARGET": w[1], "FSTYPE": w[2], "OPTIONS": w[3], "UUID": ""})
    else:
        rows = [{"SOURCE": m["source"], "TARGET": m["target"], "FSTYPE": m["fstype"], "OPTIONS": m["options"],
                 "UUID": devs.get(m["source"], {}).get("uuid", "")} for m in st["mounts"]]
    if "mountpoint" in opts:
        rows = [r for r in rows if r["TARGET"] == opts["mountpoint"]]
    if "source" in opts:
        rows = [r for r in rows if r["SOURCE"] == opts["source"]]
    if "target" in opts:
        rows = sorted((r for r in rows if under(opts["target"], r["TARGET"])), key=lambda r: -len(r["TARGET"]))[:1]
    if not rows:
        done(1)
    done(0, "".join(" ".join(r[c] for c in cols) + "\n" for r in rows))
if name == "lsblk":
    flags, opts, pos = parse("o", ("output",))
    cols = (opts.get("o") or opts.get("output")).split(",")
    out = []
    for d in pos:
        if d not in devs:
            sys.stderr.write("lsblk: %s: not a block device\n" % d)
            done(32)
        dev, vals = devs[d], []
        for c in cols:
            if c == "UUID" and dev.get("uuid_pending", 0) > 0:
                dev["uuid_pending"] -= 1
                vals.append("")
            elif c == "UUID":
                vals.append(dev.get("uuid", ""))
            elif c == "SIZE":
                vals.append(str(dev["size"]))
            else:
                done(2)
        out.append(" ".join(vals) + "\n")
    done(0, "".join(out))
if name == "mkfs.ext4":
    d = args[-1]
    if st.get("mkfs_rc") or d not in devs:
        done(st.get("mkfs_rc") or 1)
    devs[d].update(uuid=st["next_uuid"], fstype="ext4", uuid_pending=st.get("uuid_delay", 0))
    done(0)
if name == "mount":
    flags, opts, pos = parse("to", ())
    if st.get("mount_rc") or len(pos) != 2 or devs.get(pos[0], {}).get("fstype") != opts.get("t") \
            or not os.path.isdir(pos[1]):
        done(st.get("mount_rc") or 32)
    st["mounts"].append({"source": pos[0], "target": pos[1], "fstype": opts["t"],
                         "options": "rw,relatime," + opts["o"]})
    os.makedirs(os.path.join(pos[1], "lost+found"), exist_ok=True)
    done(0)
if name == "readlink":
    done(0, rel(os.path.realpath(args[-1])) + "\n")
if name == "stat":
    if args[:2] != ["-c", "%u"] or not os.path.exists(args[2]):
        done(1)
    done(0, "%s\n" % st["uids"].get(rel(args[2]), 0))
if name == "systemctl":
    if args == ["daemon-reload"]:
        def read(p):
            try:
                with open(os.path.join(root, p)) as f:
                    return f.read()
            except OSError:
                return None
        st["at_reload"] = {"fstab": read("etc/fstab"), "dropin": read("etc/systemd/system/telcoin.service.d/bench-lssd.conf")}
        done(st.get("reload_rc", 0))
    done(1)
if name in ("udevadm", "sleep"):
    done(0)
done(1)    # umount and anything else: nothing on this node may do it
'''


def relocate(text, root, prefixes=RELOCATED):
    pattern = re.compile(_START + "(" + "|".join(re.escape(p) for p in prefixes) + ")")
    return pattern.sub(lambda m: str(root) + m.group(1), text)


def unrelocated(text):
    """Real host paths a relocated script still names."""
    return re.findall(_START + r"/(?:etc|sys|dev/disk|var/lib/bench-lssd)/\S*", text)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class Node:
    """A fake -lssd node (module docstring): boot disk nvme0n1 with / on nvme0n1p1, the local SSD
    google-local-nvme-ssd-0 = nvme1n1 (and -1 = nvme2n1 when ssds=2), datadir <root>/var/lib/telcoin
    (absent until a test makes it)."""

    def __init__(self, root, ssds=1):
        self.root = r = Path(root)
        self.datadir = r / "var/lib/telcoin"
        (r / "var/lib").mkdir(parents=True)
        (r / "tmp").mkdir()
        devices = {"/dev/nvme0n1": {"size": 100 * 1024 ** 3},
                   "/dev/nvme0n1p1": {"size": 100 * 1024 ** 3 - 2 ** 27, "uuid": "0e1d2c3b-4a59-4687-9a5b-0c1d2e3f4a5b",
                                      "fstype": "ext4"},
                   SSD0: {"size": SSD_BYTES}}
        links = {"google-persistent-disk-0": "nvme0n1", "google-local-nvme-ssd-0": "nvme1n1"}
        if ssds == 2:
            devices[SSD1] = {"size": SSD_BYTES}
            links["google-local-nvme-ssd-1"] = "nvme2n1"
        for name in devices:
            write(r / name.lstrip("/"), "")
        for link, dev in links.items():
            (r / "dev/disk/by-id").mkdir(parents=True, exist_ok=True)
            os.symlink("../../" + dev, str(r / "dev/disk/by-id" / link))
        for disk in ("nvme0n1", "nvme1n1", "nvme2n1"):
            write(r / "sys/block" / disk / "queue/read_ahead_kb", "128\n")
        write(r / "etc/fstab", FSTAB)
        self.state = {"devices": devices, "calls": [], "uids": {}, "next_uuid": NEW_UUID,
                      "mounts": [{"source": "/dev/nvme0n1p1", "target": "/", "fstype": "ext4",
                                  "options": "rw,relatime,discard,errors=remount-ro,commit=30"}]}
        self.save()
        stub = STUB.replace("@PYTHON@", sys.executable)
        for name in ("findmnt", "lsblk", "mkfs.ext4", "mount", "umount", "readlink", "stat", "systemctl",
                     "udevadm", "sleep"):
            write(r / "bin" / name, stub)
            (r / "bin" / name).chmod(0o755)
        tools = r / "tools"
        tools.mkdir()
        for name in ("bash", "awk", "cat", "cp", "mv", "chmod", "mkdir", "ls", "timeout"):
            os.symlink(shutil.which(name), str(tools / name))

    def load(self):
        self.state = json.loads((self.root / "state.json").read_text())
        return self.state

    def save(self):
        (self.root / "state.json").write_text(json.dumps(self.state, indent=1, sort_keys=True))

    def change(self, **kv):
        self.load()
        self.state.update(kv)
        self.save()

    def calls(self, tool=None):
        return [c for c in self.load()["calls"] if tool is None or c["tool"] == tool]

    def argv(self, tool=None):
        return [" ".join([c["tool"]] + c["args"]) for c in self.calls(tool)]

    def forget_calls(self):
        self.change(calls=[])

    def run(self, script, after=""):
        text = relocate(script, self.root)
        assert not unrelocated(text), "the script would touch the real host: %s" % unrelocated(text)[:3]
        r = str(self.root)
        env = {"PATH": "%s/bin:%s/tools" % (r, r), "HOME": r, "TMPDIR": r + "/tmp", "LC_ALL": "C", "STUB_ROOT": r}
        return subprocess.run([shutil.which("bash"), "-s"], input=text + after, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=120 * TIMEOUT_SCALE, universal_newlines=True,
                              errors="replace")

    def marker(self):
        p = self.root / "var/lib/bench-lssd/uuid"
        return p.read_text() if p.exists() else None

    def fstab(self):
        return (self.root / "etc/fstab").read_text()

    def dropin(self):
        p = self.root / "etc/systemd/system/telcoin.service.d/bench-lssd.conf"
        return p.read_text() if p.exists() else None

    def wipe_ssd(self):
        """A VM stop and start: the SSD comes back blank and unmounted; the boot disk keeps everything."""
        self.load()
        self.state["mounts"] = [m for m in self.state["mounts"] if m["source"] != SSD0]
        self.state["devices"][SSD0] = {"size": SSD_BYTES}
        self.save()
        shutil.rmtree(str(self.datadir / "lost+found"), ignore_errors=True)

    def mounted_without_marker(self, source=SSD0, fstype="ext4", uuid=NEW_UUID):
        """What a first run leaves when its session drops right after the mount: <source> made <fstype> and
        mounted at the datadir (an empty lost+found in it), no fstab line, no drop-in, no marker."""
        self.load()
        self.state["devices"][source].update(uuid=uuid, fstype=fstype)
        self.state["mounts"].append({"source": source, "target": str(self.datadir), "fstype": fstype,
                                     "options": "rw,relatime," + ROOT_OPTS})
        self.save()
        (self.datadir / "lost+found").mkdir(parents=True)


def mounted_line(datadir, mkfs="done", uuid=NEW_UUID):
    return ("LSSD_MOUNT %s dev=%s by_id=google-local-nvme-ssd-0 size_bytes=%d uuid=%s mount=%s mkfs=%s "
            "options=rw,relatime,%s fstab_root_options=%s ra_kb=128" % (INST, SSD0, SSD_BYTES, uuid, datadir, mkfs,
                                                                         ROOT_OPTS, ROOT_OPTS))


class LssdCase(unittest.TestCase):
    _rendered = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="local-ssd-test-")
        self.tmp = Path(self._tmp.name)
        self.bin = self.tmp / "hostbin"
        self.gcloud_log = self.tmp / "gcloud-calls.txt"
        write(self.bin / "gcloud", "#!/bin/sh\necho \"gcloud $*\" >> '%s'\necho REACHED\nexit 9\n" % self.gcloud_log)
        (self.bin / "gcloud").chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def lib(self, *argv, stdin=None):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
               "TMPDIR": str(self.tmp), "BENCH_RUN_ID": "rtest-local-ssd", "BENCH_APPLY": "0", "LC_ALL": "C"}
        p = subprocess.run(["bash", "-c", LIB_CALL, "benchmark-deploy.sh", str(BENCH)] + list(argv), input=stdin,
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120 * TIMEOUT_SCALE,
                           universal_newlines=True, errors="replace")
        self.assertFalse(self.gcloud_log.exists(), "a builder or parser called gcloud")
        return p

    def text_of(self, *argv):
        if argv not in self._rendered:
            p = self.lib(*argv)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stderr, "")
            LssdCase._rendered[argv] = p.stdout
        return self._rendered[argv]

    def node(self, ssds=1):
        return Node(self.tmp / "node", ssds=ssds)

    def mount(self, node, inst=INST):
        return node.run(self.text_of("bench_lssd_mount_script", inst, str(node.datadir)))

    def lines(self, p, tag="LSSD_MOUNT"):
        return [l for l in p.stdout.splitlines() if l.startswith(tag + " ")]

    def assert_failed(self, p, node, reason_re):
        """rc 1 and exactly one `LSSD_MOUNT <inst> failed <reason>` line, matching reason_re."""
        self.assertEqual(p.returncode, 1, p.stdout)
        got = self.lines(p)
        self.assertEqual(len(got), 1, p.stdout)
        prefix = "LSSD_MOUNT %s failed " % INST
        self.assertTrue(got[0].startswith(prefix), got[0])
        self.assertRegex(got[0][len(prefix):], reason_re)
        return got[0]

    def assert_nothing_written(self, node):
        self.assertEqual(node.argv("mkfs.ext4"), [])
        self.assertEqual(node.argv("mount"), [])
        self.assertEqual(node.argv("umount"), [])
        self.assertEqual(node.argv("systemctl"), [])
        self.assertIsNone(node.marker())
        self.assertEqual(node.fstab(), FSTAB)
        self.assertIsNone(node.dropin())


# ------------------------------------------------------------------------------------------ the mount script
class MountScriptTests(LssdCase):
    def test_first_time_formats_mounts_and_writes_the_marker_last(self):
        node = self.node()
        p = self.mount(node)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir)])
        self.assertEqual(p.stdout.strip(), mounted_line(node.datadir))   # nothing else on stdout
        m = "/var/lib/telcoin"
        self.assertEqual(node.argv("mkfs.ext4"), ["mkfs.ext4 " + " ".join(MKFS_ARGS)])
        self.assertEqual(node.argv("mount"), ["mount -t ext4 -o %s %s %s" % (ROOT_OPTS, SSD0, m)])
        self.assertEqual(node.argv("systemctl"), ["systemctl daemon-reload"])
        self.assertEqual(node.argv("umount"), [])
        # Only the first local SSD's namespace is ever named, and the boot disk is never written.
        named = {a for c in node.calls() for a in c["args"] if a.startswith("/dev/nvme")}
        self.assertEqual(named, {SSD0})
        # The marker is the last write: every call up to the reload ran without it, only reads followed, and
        # the reload saw fstab and the drop-in in place.
        calls = node.calls()
        reload_at = [c["tool"] for c in calls].index("systemctl")
        self.assertEqual([c["marker"] for c in calls[:reload_at + 1]], [False] * (reload_at + 1), calls)
        self.assertEqual([" ".join([c["tool"]] + c["args"]) for c in calls[reload_at + 1:]],
                         ["lsblk -bdno SIZE %s" % SSD0, "findmnt -no OPTIONS --mountpoint /var/lib/telcoin"])
        self.assertEqual(node.marker(), NEW_UUID + "\n")
        st = node.load()
        line = "UUID=%s %s ext4 %s,nofail,x-systemd.device-timeout=30s 0 2\n" % (NEW_UUID, node.datadir, ROOT_OPTS)
        self.assertEqual(st["at_reload"], {"fstab": FSTAB + line,
                                           "dropin": "[Unit]\nRequiresMountsFor=%s\n" % node.datadir})
        self.assertEqual(node.fstab(), FSTAB + line)
        self.assertEqual((node.root / "etc/fstab.bench-lssd.bak").read_text(), FSTAB)
        self.assertEqual(node.dropin(), "[Unit]\nRequiresMountsFor=%s\n" % node.datadir)
        mode = lambda p: stat.S_IMODE(os.stat(str(node.root / p)).st_mode)
        self.assertEqual(mode("var/lib/bench-lssd/uuid"), 0o600)
        self.assertEqual(mode("var/lib/bench-lssd"), 0o700)
        self.assertEqual(mode("etc/fstab"), 0o644)
        self.assertEqual(mode("etc/systemd/system/telcoin.service.d/bench-lssd.conf"), 0o644)
        # The data directory is the fresh file system's root, left as mkfs made it (no chown anywhere).
        self.assertEqual(sorted(os.listdir(str(node.datadir))), ["lost+found"])
        self.assertNotIn("chown", self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
        self.assertEqual(st["mounts"][-1], {"source": SSD0, "target": str(node.datadir), "fstype": "ext4",
                                            "options": "rw,relatime," + ROOT_OPTS})

    def test_first_time_on_an_empty_root_owned_directory_replaces_its_old_fstab_line(self):
        node = self.node()
        node.datadir.mkdir()
        old = "UUID=%s %s ext4 defaults 0 2\n" % (OTHER_UUID, node.datadir)
        write(node.root / "etc/fstab", FSTAB + old)
        p = self.mount(node)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir)], p.stdout)
        self.assertEqual(node.fstab(), FSTAB + "UUID=%s %s ext4 %s,nofail,x-systemd.device-timeout=30s 0 2\n"
                         % (NEW_UUID, node.datadir, ROOT_OPTS))
        self.assertEqual((node.root / "etc/fstab.bench-lssd.bak").read_text(), FSTAB + old)

    def test_a_re_run_keeps_the_mount_and_writes_nothing(self):
        node = self.node()
        self.assertEqual(self.mount(node).returncode, 0)
        fstab, dropin = node.fstab(), node.dropin()
        node.forget_calls()
        p = self.mount(node)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir, mkfs="kept")])
        for tool in ("mkfs.ext4", "mount", "umount", "systemctl", "udevadm", "sleep"):
            self.assertEqual(node.argv(tool), [], tool)
        self.assertEqual((node.fstab(), node.dropin(), node.marker()), (fstab, dropin, NEW_UUID + "\n"))

    def test_marker_without_the_mount_is_lost_and_never_formatted_again(self):
        node = self.node()
        self.assertEqual(self.mount(node).returncode, 0)
        node.wipe_ssd()
        node.forget_calls()
        line = self.assert_failed(self.mount(node), node, r"^lost: ")
        self.assertIn("is not a mount", line)
        self.assertEqual(node.argv("mkfs.ext4"), [])
        self.assertEqual(node.argv("mount"), [])
        self.assertEqual(node.argv("systemctl"), [])
        self.assertEqual(node.marker(), NEW_UUID + "\n")

    def test_marker_with_a_mount_of_another_uuid_is_lost(self):
        node = self.node()
        self.assertEqual(self.mount(node).returncode, 0)
        st = node.load()
        st["devices"][SSD0]["uuid"] = OTHER_UUID    # someone made a new file system on it
        node.save()
        node.forget_calls()
        line = self.assert_failed(self.mount(node), node, r"^lost: ")
        self.assertIn(OTHER_UUID, line)
        self.assertEqual(node.argv("mkfs.ext4"), [])

    def test_a_data_directory_that_is_not_empty_is_refused(self):
        node = self.node()
        write(node.datadir / "node-keys/primary.key", "k")
        self.assert_failed(self.mount(node), node, r"is not empty$")
        self.assert_nothing_written(node)

    def test_a_data_directory_that_root_does_not_own_is_refused(self):
        node = self.node()
        node.datadir.mkdir()
        node.change(uids={"/var/lib/telcoin": 999})
        self.assert_failed(self.mount(node), node, r"is not owned by root$")
        self.assert_nothing_written(node)

    def test_a_data_directory_that_is_a_mount_point_or_a_file_is_refused(self):
        node = self.node()
        node.datadir.mkdir()
        st = node.load()
        st["mounts"].append({"source": "/dev/sdb", "target": str(node.datadir), "fstype": "ext4", "options": "rw"})
        node.save()
        self.assert_failed(self.mount(node), node, r"is a mount point \(of /dev/sdb\)")
        self.assert_nothing_written(node)
        st["mounts"].pop()
        node.save()
        node.datadir.rmdir()
        write(node.datadir, "")
        self.assert_failed(self.mount(node), node, r"is not a directory$")
        self.assert_nothing_written(node)

    def test_a_device_mounted_elsewhere_is_left_alone(self):
        node = self.node()
        st = node.load()
        st["devices"][SSD0].update(uuid=OTHER_UUID, fstype="ext4")
        st["mounts"].append({"source": SSD0, "target": "/mnt/bench-probe-nvme", "fstype": "ext4", "options": "rw"})
        node.save()
        self.assert_failed(self.mount(node), node, r"^/dev/nvme1n1 is mounted on /mnt/bench-probe-nvme")
        self.assert_nothing_written(node)

    def test_no_by_id_link_fails_without_a_fallback(self):
        node = self.node(ssds=2)
        (node.root / "dev/disk/by-id/google-local-nvme-ssd-0").unlink()   # -1 is still there: never used
        self.assert_failed(self.mount(node), node, r"^no .*/dev/disk/by-id/google-local-nvme-ssd-0 ")
        self.assert_nothing_written(node)
        self.assertEqual(node.argv("lsblk"), [])

    def test_a_by_id_link_to_the_root_disk_or_a_partition_is_refused(self):
        node = self.node()
        link = node.root / "dev/disk/by-id/google-local-nvme-ssd-0"
        link.unlink()
        os.symlink("../../nvme0n1", str(link))
        self.assert_failed(self.mount(node), node, r"^/dev/nvme0n1 holds / \(/dev/nvme0n1p1\)$")
        self.assert_nothing_written(node)
        link.unlink()
        os.symlink("../../nvme0n1p1", str(link))
        self.assert_failed(self.mount(node), node, r"is '/dev/nvme0n1p1', not an NVMe namespace$")
        self.assert_nothing_written(node)

    def test_a_failed_mkfs_writes_nothing_and_a_re_run_starts_over(self):
        node = self.node()
        node.change(mkfs_rc=1)
        self.assert_failed(self.mount(node), node, r"^mkfs\.ext4 /dev/nvme1n1 failed$")
        self.assertEqual(node.argv("mkfs.ext4"), ["mkfs.ext4 " + " ".join(MKFS_ARGS)])
        self.assertEqual(node.argv("mount"), [])
        self.assertEqual(node.argv("systemctl"), [])
        self.assertIsNone(node.marker())
        self.assertEqual(node.fstab(), FSTAB)
        node.change(mkfs_rc=0)
        p = self.mount(node)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir)], p.stdout)

    def test_a_failed_mount_or_reload_leaves_no_marker(self):
        node = self.node()
        node.change(mount_rc=32)
        self.assert_failed(self.mount(node), node, r"^mount /dev/nvme1n1 on .* failed$")
        self.assertIsNone(node.marker())
        self.assertEqual(node.fstab(), FSTAB)
        node = Node(self.tmp / "node2")
        node.change(reload_rc=1)
        p = node.run(self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
        self.assert_failed(p, node, r"^systemctl daemon-reload failed$")
        self.assertIsNone(node.marker())

    def test_the_uuid_is_read_again_until_udev_has_it(self):
        node = self.node()
        node.change(uuid_delay=2)
        p = self.mount(node)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir)], p.stdout)
        self.assertEqual(node.argv("udevadm"), ["udevadm settle --timeout=30"])
        self.assertEqual(len(node.argv("sleep")), 2)
        node = Node(self.tmp / "node2")
        node.change(uuid_delay=99)
        p = node.run(self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
        self.assert_failed(p, node, r"^lsblk gives no UUID for /dev/nvme1n1 \(''\)$")
        self.assertIsNone(node.marker())
        self.assertEqual(node.fstab(), FSTAB)

    def fstab_line(self, node, uuid=NEW_UUID):
        return "UUID=%s %s ext4 %s,nofail,x-systemd.device-timeout=30s 0 2\n" % (uuid, node.datadir, ROOT_OPTS)

    def assert_resumed(self, p, node, fstab_before):
        """mkfs=resumed: no mkfs, no mount, the reload ran without the marker, the marker came last, and
        fstab and the drop-in hold one entry each for the datadir."""
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir, mkfs="resumed")])
        for tool in ("mkfs.ext4", "mount", "umount"):
            self.assertEqual(node.argv(tool), [], tool)
        self.assertEqual(node.argv("systemctl"), ["systemctl daemon-reload"])
        self.assertEqual([c["marker"] for c in node.calls("systemctl")], [False])
        self.assertEqual(node.marker(), NEW_UUID + "\n")
        self.assertEqual(node.fstab(), FSTAB + self.fstab_line(node))
        self.assertEqual(node.fstab().count(" %s " % node.datadir), 1)
        self.assertEqual((node.root / "etc/fstab.bench-lssd.bak").read_text(), fstab_before)
        self.assertEqual(os.listdir(str(node.root / "etc/systemd/system/telcoin.service.d")), ["bench-lssd.conf"])
        self.assertEqual(node.dropin(), "[Unit]\nRequiresMountsFor=%s\n" % node.datadir)
        self.assertEqual(sorted(os.listdir(str(node.datadir))), ["lost+found"])

    def test_a_first_run_stopped_after_its_mount_is_resumed(self):
        node = self.node()
        node.mounted_without_marker()
        self.assert_resumed(self.mount(node), node, FSTAB)
        node.forget_calls()
        p = self.mount(node)    # and from there on it is kept
        self.assertEqual(self.lines(p), [mounted_line(node.datadir, mkfs="kept")], p.stdout)
        self.assertEqual(node.argv("systemctl"), [])

    def test_a_first_run_stopped_after_fstab_and_drop_in_is_resumed_without_duplicates(self):
        node = self.node()
        node.change(reload_rc=1)    # mkfs, mount, fstab, drop-in done; the reload fails, so no marker
        self.assert_failed(self.mount(node), node, r"^systemctl daemon-reload failed$")
        self.assertIsNone(node.marker())
        self.assertEqual(node.fstab(), FSTAB + self.fstab_line(node))
        node.change(reload_rc=0, calls=[])
        self.assert_resumed(self.mount(node), node, FSTAB)

    def test_a_mount_of_the_device_with_data_and_no_marker_is_refused(self):
        for i, extra in enumerate(("node-keys/primary.key", "lost+found/#12")):
            node = Node(self.tmp / ("node-%d" % i))
            node.mounted_without_marker()
            write(node.datadir / extra, "k")
            p = node.run(self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
            self.assert_failed(p, node, r"^%s is a mount of /dev/nvme1n1 that holds data and the marker .*/var/lib/bench-lssd/uuid "
                               r"is absent: it is neither formatted again nor adopted$" % re.escape(str(node.datadir)))
            self.assert_nothing_written(node)

    def test_resume_refuses_another_device_a_second_mount_or_another_file_system(self):
        node = Node(self.tmp / "other-device", ssds=2)
        node.mounted_without_marker(source=SSD1)
        p = node.run(self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
        self.assert_failed(p, node, r"is a mount point \(of /dev/nvme2n1\) and the marker .* is absent$")
        self.assert_nothing_written(node)
        node = Node(self.tmp / "second-mount")
        node.mounted_without_marker()
        st = node.load()
        st["mounts"].append({"source": SSD0, "target": "/mnt/bench-probe-nvme", "fstype": "ext4", "options": "rw"})
        node.save()
        p = node.run(self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
        self.assert_failed(p, node, r"^/dev/nvme1n1 is mounted on /mnt/bench-probe-nvme ")
        self.assert_nothing_written(node)
        node = Node(self.tmp / "xfs")
        node.mounted_without_marker(fstype="xfs")
        p = node.run(self.text_of("bench_lssd_mount_script", INST, str(node.datadir)))
        self.assert_failed(p, node, r"with file system 'xfs', not ext4, and the marker .* is absent$")
        self.assert_nothing_written(node)

    def test_a_mkfs_whose_mount_never_happened_is_made_again(self):
        """The other half of the window: the mkfs finished and the mount did not. The re-run formats again,
        which is safe: nothing was ever written into that file system."""
        node = self.node()
        node.change(mount_rc=32)
        self.assert_failed(self.mount(node), node, r"^mount /dev/nvme1n1 on .* failed$")
        st = node.load()
        self.assertEqual((st["devices"][SSD0]["fstype"], st["devices"][SSD0]["uuid"]), ("ext4", NEW_UUID))
        self.assertEqual(sorted(os.listdir(str(node.datadir))), [])   # mkdir ran, the mount did not
        node.change(mount_rc=0, next_uuid=OTHER_UUID, calls=[])
        p = self.mount(node)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir, uuid=OTHER_UUID)], p.stdout)
        self.assertEqual(node.argv("mkfs.ext4"), ["mkfs.ext4 " + " ".join(MKFS_ARGS)])
        self.assertEqual(node.marker(), OTHER_UUID + "\n")
        self.assertEqual(node.fstab(), FSTAB + self.fstab_line(node, OTHER_UUID))

    def test_with_two_local_ssds_only_the_first_is_touched(self):
        node = self.node(ssds=2)
        p = self.mount(node)
        self.assertEqual(self.lines(p), [mounted_line(node.datadir)], p.stdout)
        self.assertEqual({a for c in node.calls() for a in c["args"] if a.startswith("/dev/nvme")}, {SSD0})
        self.assertEqual(node.load()["devices"][SSD1], {"size": SSD_BYTES})

    def test_a_missing_tool_fails_before_anything_runs(self):
        node = self.node()
        (node.root / "bin/systemctl").unlink()
        self.assert_failed(self.mount(node), node, r"^no systemctl on the node$")
        self.assertEqual(node.calls(), [])

    def test_the_rendered_script_parses_and_lints(self):
        text = self.text_of("bench_lssd_mount_script", INST, "/var/lib/telcoin")
        self.assertTrue(text.startswith("# local-SSD data directory (bench_lssd_mount_script)"))
        self.assertIn("\nset -euo pipefail\nI=%s\nM=/var/lib/telcoin\n" % INST, text)
        self.assertNotIn("blkid", text)
        self.assertEqual(subprocess.run(["bash", "-n"], input=text, universal_newlines=True).returncode, 0)
        if shutil.which("shellcheck"):
            p = subprocess.run(["shellcheck", "-S", "warning", "-s", "bash", "-"], input=text,
                               stdout=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(p.returncode, 0, p.stdout)

    def test_builders_refuse_bad_names_and_data_directories(self):
        for fn in ("bench_lssd_mount_script", "bench_lssd_check_script"):
            for argv in (("Bad_Name", "/var/lib/telcoin"), ("", "/var/lib/telcoin"), (INST,), (INST, ""),
                         (INST, "var/lib/telcoin"), (INST, "/"), (INST, "/var/lib/telcoin/"), (INST, "/var//lib"),
                         (INST, "/var/lib/../etc"), (INST, "/var/./lib"), (INST, "/var/lib/tel coin"),
                         (INST, "/var/lib/tel$coin"), (INST, "/var/lib/.."), (INST, "/var/lib/te\nlcoin")):
                p = self.lib(fn, *argv)
                self.assertNotEqual(p.returncode, 0, (fn, argv))
                self.assertEqual(p.stdout, "", (fn, argv))


# ----------------------------------------------------------------------------------------------- the record
class MountRecordTests(LssdCase):
    def record(self, text, inst=INST):
        return self.lib("bench_lssd_mount_record", inst, stdin=text)

    def test_a_good_line_is_the_data_disk_object(self):
        for mk in ("done", "kept", "resumed"):
            p = self.record("noise\r\n" + mounted_line("/var/lib/telcoin", mkfs=mk) + "\r\nPRECFG_OK x\n")
            self.assertEqual(p.returncode, 0, p.stderr)
            got = json.loads(p.stdout)
            ts = got.pop("ts")
            self.assertRegex(ts, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertEqual(list(got.items()), [
                ("class", "local-ssd"), ("by_id", "google-local-nvme-ssd-0"), ("device", SSD0),
                ("size_bytes", SSD_BYTES), ("uuid", NEW_UUID), ("fstype", "ext4"), ("mount", "/var/lib/telcoin"),
                ("mount_options", "rw,relatime," + ROOT_OPTS), ("fstab_root_options", ROOT_OPTS), ("mkfs", mk),
                ("read_ahead_kb", 128), ("provisioned_iops", None), ("provisioned_throughput", None)])
            self.assertEqual(p.stdout.count("\n"), 1)

    def test_the_last_line_of_this_instance_counts(self):
        other = mounted_line("/var/lib/telcoin").replace(INST, "bench-validator-04")
        p = self.record(mounted_line("/var/lib/telcoin", uuid=OTHER_UUID) + "\n" + mounted_line("/var/lib/telcoin")
                        + "\n" + other + "\n")
        self.assertEqual(json.loads(p.stdout)["uuid"], NEW_UUID)
        p = self.record(mounted_line("/var/lib/telcoin") + "\nLSSD_MOUNT %s failed lost: wiped\n" % INST)
        self.assertEqual((p.returncode, p.stdout), (1, ""))

    def test_a_failed_line_or_any_other_shape_is_a_failure(self):
        good = mounted_line("/var/lib/telcoin")
        bad = {
            "failed": "LSSD_MOUNT %s failed lost: the marker holds UUID x" % INST,
            "failed, no reason": "LSSD_MOUNT %s failed" % INST,
            "no line": "PRECFG_OK %s\n" % INST,
            "another instance": good.replace(INST, "bench-validator-04"),
            "a partition": good.replace("dev=/dev/nvme1n1", "dev=/dev/nvme1n1p1"),
            "not nvme": good.replace("dev=/dev/nvme1n1", "dev=/dev/sdb"),
            "the second SSD id": good.replace("google-local-nvme-ssd-0", "google-local-nvme-ssd-1"),
            "mkfs other": good.replace("mkfs=done", "mkfs=again"),
            "upper-case uuid": good.replace(NEW_UUID, NEW_UUID.upper()),
            "short uuid": good.replace(NEW_UUID, NEW_UUID[:-1]),
            "size not a number": good.replace("size_bytes=%d" % SSD_BYTES, "size_bytes=375G"),
            "size with a leading zero": good.replace("size_bytes=%d" % SSD_BYTES, "size_bytes=0%d" % SSD_BYTES),
            "ra empty": good.replace("ra_kb=128", "ra_kb="),
            "a field missing": good.replace(" fstab_root_options=%s" % ROOT_OPTS, ""),
            "fields swapped": good.replace("mount=/var/lib/telcoin mkfs=done", "mkfs=done mount=/var/lib/telcoin"),
            "an extra field": good + " extra=1",
            "a relative mount": good.replace("mount=/var/lib/telcoin", "mount=var/lib/telcoin"),
            "empty options": good.replace("options=rw,relatime," + ROOT_OPTS, "options="),
        }
        for why, text in bad.items():
            p = self.record(text + "\n")
            self.assertEqual((p.returncode, p.stdout), (1, ""), why)
            self.assertTrue(p.stderr.startswith("❌ bench_lssd_mount_record: "), (why, p.stderr))
        p = self.record(bad["failed"] + "\n")
        self.assertEqual(p.stderr, "❌ bench_lssd_mount_record: %s failed lost: the marker holds UUID x\n" % INST)

    def test_the_manifest_contract_names_every_key_and_field_in_order(self):
        text = (BENCH / "arms" / "MANIFEST-FIELDS.md").read_text()
        section = text.split("### instances[].data_disk\n", 1)[1].split("\n### ", 1)[0]
        keys = [k for cell in re.findall(r"^\| (`[^|]+) \|", section, re.M) for k in re.findall(r"`([a-z_]+)`", cell)]
        p = self.record(mounted_line("/var/lib/telcoin"))
        self.assertEqual(keys, list(json.loads(p.stdout)))
        (doc,) = re.findall(r"^LSSD_MOUNT <inst> dev=.*$", text, re.M)
        script = self.text_of("bench_lssd_mount_script", INST, "/var/lib/telcoin")
        (echo,) = re.findall(r'^echo "LSSD_MOUNT \$I (dev=.*)"$', script, re.M)
        self.assertEqual(re.findall(r"(\w+)=", doc), re.findall(r"(\w+)=", echo))
        self.assertIn("\nPRECFG_FAIL <inst> local SSD not mounted at <datadir>\n", text)
        self.assertIn("\nLSSD_MOUNT <inst> failed <reason>\n", text)

    def test_the_script_line_round_trips(self):
        node = self.node()
        p = self.mount(node)
        rec = json.loads(self.record(p.stdout).stdout)
        self.assertEqual((rec["mount"], rec["mkfs"], rec["uuid"], rec["device"]), (str(node.datadir), "done", NEW_UUID, SSD0))
        rec = json.loads(self.record(self.mount(node).stdout).stdout)
        self.assertEqual(rec["mkfs"], "kept")


# ------------------------------------------------------------------------------------------ the step-7 check
class CheckScriptTests(LssdCase):
    AFTER = 'echo "SESSION-GOES-ON NV=${NV:-unset} MS=${MS:-unset} L=${L:-unset}"\n'

    def check(self, node, inst=INST):
        return node.run(self.text_of("bench_lssd_check_script", inst, str(node.datadir)), after=self.AFTER)

    def assert_fails(self, p, node):
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(p.stdout, "PRECFG_FAIL %s local SSD not mounted at %s\n" % (INST, node.datadir))

    def test_a_mounted_node_passes_silently_and_leaves_no_variable(self):
        node = self.node()
        self.assertEqual(self.mount(node).returncode, 0)
        node.forget_calls()
        p = self.check(node)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout, "SESSION-GOES-ON NV=unset MS=unset L=unset\n")
        self.assertEqual(node.argv("findmnt"), ["findmnt -no SOURCE --mountpoint /var/lib/telcoin"])
        for tool in ("mkfs.ext4", "mount", "umount", "systemctl"):
            self.assertEqual(node.argv(tool), [], tool)

    def test_an_unmounted_node_ends_the_session(self):
        node = self.node()
        node.datadir.mkdir()
        self.assert_fails(self.check(node), node)
        self.assertEqual(self.mount(node).returncode, 0)
        node.wipe_ssd()     # stopped and started between step 3 and step 7
        self.assert_fails(self.check(node), node)

    def test_another_device_or_no_local_ssd_ends_the_session(self):
        node = self.node(ssds=2)
        node.datadir.mkdir()
        st = node.load()
        st["devices"][SSD1]["fstype"] = "ext4"
        st["mounts"].append({"source": SSD1, "target": str(node.datadir), "fstype": "ext4", "options": "rw"})
        node.save()
        self.assert_fails(self.check(node), node)
        st["mounts"][-1]["source"] = SSD0
        node.save()
        (node.root / "dev/disk/by-id/google-local-nvme-ssd-0").unlink()
        self.assert_fails(self.check(node), node)

    def test_the_rendered_check_parses_and_lints(self):
        text = self.text_of("bench_lssd_check_script", INST, "/var/lib/telcoin")
        self.assertTrue(text.startswith("# local-SSD check (bench_lssd_check_script)"))
        self.assertTrue(text.endswith(") || exit 1\n"))
        self.assertEqual(subprocess.run(["bash", "-n"], input=text, universal_newlines=True).returncode, 0)
        if shutil.which("shellcheck"):
            p = subprocess.run(["shellcheck", "-S", "warning", "-s", "bash", "-"], input=text,
                               stdout=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(p.returncode, 0, p.stdout)


# ------------------------------------------------------------------------- the probe driver's copy, and C4
class ProbeMirrorTests(LssdCase):
    def test_device_id_and_mkfs_options_equal_the_probe_drivers(self):
        probe = PROBE.read_text()
        (opts,) = re.findall(r'^NVME_MKFS="([^"]*)"$', probe, re.M)
        setup = probe.split("script_setup_nvme() {", 1)[1].split("\n}\n", 1)[0]
        (probe_dev,) = re.findall(r"^L=(/dev/disk/by-id/\S+)$", setup, re.M)
        self.assertEqual(len(re.findall(r'^\s*timeout 600 mkfs\.ext4 \$\{NVME_MKFS\} "\\\$NV" \|\|', setup, re.M)), 1)
        mount = self.text_of("bench_lssd_mount_script", INST, "/var/lib/telcoin")
        check = self.text_of("bench_lssd_check_script", INST, "/var/lib/telcoin")
        self.assertEqual(re.findall(r'^\s*timeout 600 mkfs\.ext4 (.*) "\$NV" \|\|', mount, re.M), [opts])
        self.assertEqual(re.findall(r"^L=(\S+)$", mount, re.M), [probe_dev])
        self.assertEqual(re.findall(r"^L=(\S+)$", check, re.M), [probe_dev])
        self.assertEqual(" ".join(MKFS_ARGS[:-1]), opts)


class C4QuotaTests(LssdCase):
    def test_c4_has_its_own_sum_and_says_why_it_is_not_checked(self):
        got = {}
        for t in ("c4-standard-8", "c4-standard-8-lssd", "c3-standard-8-lssd", "c3-standard-8", "e2-medium"):
            p = self.lib("bench_cpu_quota_metric", t)
            self.assertEqual(p.returncode, 0, p.stderr)
            got[t] = p.stdout.strip()
        self.assertEqual(got, {"c4-standard-8": "C4_CPUS", "c4-standard-8-lssd": "C4_CPUS",
                               "c3-standard-8-lssd": "C3_CPUS", "c3-standard-8": "C3_CPUS", "e2-medium": "CPUS"})
        p = self.lib("bench_cpu_quota_unlisted", "C4_CPUS")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("CPUS-PER-VM-FAMILY-per-project-region", p.stdout)
        self.assertEqual(p.stdout.count("\n"), 1)
        for m in ("C3_CPUS", "CPUS", "N2_CPUS", "IN_USE_ADDRESSES", ""):
            p = self.lib("bench_cpu_quota_unlisted", m)
            self.assertEqual((p.returncode, p.stdout), (0, ""), m)


if __name__ == "__main__":
    unittest.main()
