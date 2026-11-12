"""benchmark-deploy.sh with the data directory on the local SSD (bench 6, unit L1c), fully offline.

What is under test: with BENCH_NODE_DATADIR_LSSD=1, step 2 gives every instances[] entry a data_disk (the
local-SSD nodes {"class": "local-ssd"}, the others the boot disk's class), step 3 runs bench_lssd_mount_script on
each local-SSD node after the serial markers and merges its LSSD_MOUNT line into that node's data_disk, step 7
starts a local-SSD node's pre-start session with bench_lssd_check_script, the plan gets the step-3 lines, and
--print-lssd-mount prints one node's mount script. With the knob unset, the dry plan, --print-prestart for every
instance, step 3 and every pre-start session are the harness base's (`git show ae43747:<path>`).

The sandbox, the recording gcloud and the base tree are test_node_deploy.py's (Sandbox). In front of that gcloud
sits a second shim (SSH_SHIM) for the two calls a node answers: the serial port (the bootstrap marker at once)
and `compute ssh <inst> ... --command=sudo bash -s`, whose stdin it keeps in <rec>/ssh.<inst>.* and answers:
  a mount session (first line from bench_lssd_mount_script): the canned LSSD_MOUNT line of the state SHIM_LSSD
      gives the node ("<inst>=<state> ..."; default SHIM_LSSD_DEFAULT, else done): done, kept or resumed (the
      success line, mount= as the script asks), lost (`LSSD_MOUNT <inst> failed lost: ...`, rc 1), none (nothing);
  any other session (step 7's pre-start): PRECFG_OK <inst>, or with SHIM_LSSD_CHECK=fail and the check first in
      the session, the check's PRECFG_FAIL line alone.
Every other call goes to test_node_deploy.py's gcloud: REACHED and rc 9 on a create or delete it is not told to
make; every run here asserts zero REACHED. Tests that need the base skip when git or the commit is missing;
every test skips when the `common` submodule is not checked out.
"""
import json
import re
import subprocess
import unittest

import test_node_deploy as tnd

NODES, ZONES, RUN, E_ENV, ISO_RE = tnd.NODES, tnd.ZONES, tnd.RUN, tnd.E_ENV, tnd.ISO_RE
LSSD_IDX = (2, 3, 4, 5, 6, 9)
BOOT_IDX = (0, 1, 7, 8, 10)
DATADIR = "/var/lib/telcoin"
MOUNT_HEAD = "# local-SSD data directory (bench_lssd_mount_script)"
CHECK_HEAD = "# local-SSD check (bench_lssd_check_script)"
MKFS = "mkfs.ext4 -q -F -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard"
ROOT_OPTS = "discard,commit=30,errors=remount-ro"
MOUNT_OPTS = "rw,relatime,discard,errors=remount-ro,commit=30"   # findmnt reads them in its own order
BOOT_DISK = {"class": "boot", "type": "hyperdisk-balanced", "size_gb": 100, "provisioned_iops": 20000,
             "provisioned_throughput": 800}

SSH_SHIM = r'''#!/bin/bash
rec="${SHIM_REC:?}"
case "$1 $2" in
    "compute ssh")
        printf '%s\n' "$*" >> "${rec}/calls.log"
        inst="$3"
        f="$(mktemp "${rec}/ssh.${inst}.XXXXXX")"
        cat > "${f}"
        n="${inst##*-}"; n=$((10#${n}))
        if [ "$(head -1 "${f}" | cut -c1-52)" = "# local-SSD data directory (bench_lssd_mount_script)" ]; then
            m="$(sed -n 's/^M=//p' "${f}" | head -1)"
            state="${SHIM_LSSD_DEFAULT:-done}"
            for kv in ${SHIM_LSSD:-}; do [ "${kv%%=*}" != "${inst}" ] || state="${kv#*=}"; done
            case "${state}" in
                done|kept|resumed)
                    printf 'some ssh banner\r\nLSSD_MOUNT %s dev=/dev/nvme1n1 by_id=google-local-nvme-ssd-0 size_bytes=402653184000 uuid=00000000-0000-4000-8000-0000000000%02d mount=%s mkfs=%s options=rw,relatime,discard,errors=remount-ro,commit=30 fstab_root_options=discard,commit=30,errors=remount-ro ra_kb=128\r\n' \
                        "${inst}" "${n}" "${m}" "${state}" ;;
                lost) echo "LSSD_MOUNT ${inst} failed lost: the marker says 00000000-0000-4000-8000-0000000000${n} but ${m} is not that file system (the SSD was wiped)"; exit 1 ;;
                none) ;;
            esac
            exit 0
        fi
        if [ "${SHIM_LSSD_CHECK:-ok}" = fail ] && [ "$(head -1 "${f}" | cut -c1-43)" = "# local-SSD check (bench_lssd_check_script)" ]; then
            echo "PRECFG_FAIL ${inst} local SSD not mounted at /var/lib/telcoin"; exit 1
        fi
        echo "PRECFG_OK ${inst} logrotate=- paramsbak=-"
        exit 0 ;;
    "compute instances")
        if [ "$3" = get-serial-port-output ]; then
            printf '%s\n' "$*" >> "${rec}/calls.log"
            echo "boot noise"; echo "devnet-startup.sh complete"; exit 0
        fi ;;
esac
exec "$(dirname "$0")/gcloud-node-deploy" "$@"
'''


def success_line(i, mkfs="done"):
    return ("LSSD_MOUNT %s dev=/dev/nvme1n1 by_id=google-local-nvme-ssd-0 size_bytes=402653184000 "
            "uuid=00000000-0000-4000-8000-0000000000%02d mount=%s mkfs=%s options=%s "
            "fstab_root_options=%s ra_kb=128" % (NODES[i], i + 1, DATADIR, mkfs, MOUNT_OPTS, ROOT_OPTS))


def lssd_record(i, mkfs="done"):
    return {"class": "local-ssd", "by_id": "google-local-nvme-ssd-0", "device": "/dev/nvme1n1",
            "size_bytes": 402653184000, "uuid": "00000000-0000-4000-8000-0000000000%02d" % (i + 1),
            "fstype": "ext4", "mount": DATADIR, "mount_options": MOUNT_OPTS,
            "fstab_root_options": ROOT_OPTS, "mkfs": mkfs, "read_ahead_kb": 128, "provisioned_iops": None,
            "provisioned_throughput": None}


class LssdSandbox(tnd.Sandbox):
    """test_node_deploy.py's sandbox with SSH_SHIM in front of its gcloud."""

    def setUp(self):
        super().setUp()
        (self.bin / "gcloud").rename(self.bin / "gcloud-node-deploy")
        (self.bin / "gcloud").write_text(SSH_SHIM)
        (self.bin / "gcloud").chmod(0o755)

    def step(self, n, tree=None, **env):
        """`benchmark-deploy.sh --run RUN --yes --only <n>` (step 2 with instance creates allowed)."""
        tree = tree or self.tree
        if not (self.run_dir(tree) / "manifest.json").exists():
            self.write_manifest(tree)
        if n == 2:
            env.setdefault("SHIM_LIVE", "1")
        p = self.run_deploy(tree, "--run", RUN, "--yes", "--only", str(n), **env)
        self.assertNotIn("REACHED", p.stdout)
        self.assertFalse((self.rec / "reached.log").exists(), p.stdout)
        return p

    def ssh_sessions(self, rec=None):
        """{inst: [session stdin, ...]} of every recorded `compute ssh` session."""
        out = {}
        for f in sorted((rec or self.rec).glob("ssh.*")):
            out.setdefault(f.name.split(".")[1], []).append(f.read_text())
        return out

    def ssh_calls(self):
        return [c.split()[2] for c in self.calls() if c.startswith("compute ssh ")]

    def data_disks(self, tree=None):
        return {i["name"]: i.get("data_disk") for i in self.manifest(tree)["instances"]}

    def lib(self, body, **env):
        """<body> after sourcing bench-lib.sh (the builders), as the deploy does."""
        return self.funcs(body, "node_datadir", "data_disk_plan", **env)

    def builder(self, fn, i, **env):
        p = self.lib('%s %s %s' % (fn, NODES[i], DATADIR), **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        return p.stdout

    def prestart(self, tree, i, **env):
        """step 7's prestart_node <i> alone (extracted from <tree>'s deploy, as test_node_image.py extracts
        functions), against SSH_SHIM: (rc + output, the one session's stdin or None)."""
        names = ["prestart_node", "postcfg_field", "node_startup_merge"]
        if tree == self.tree:
            names.append("node_datadir")
        fns = tnd.shell_functions(tree / "benchmark" / "benchmark-deploy.sh", *names)
        env.setdefault("BENCH_RUN_ID", RUN)
        p = subprocess.run(["bash", "-c", tnd.FUNCS, "benchmark-deploy.sh", str(tree / "benchmark"), fns,
                            'STEP7_RUNNING=""; prestart_node %d; echo "RC=$?"' % i],
                           env=self.env(**env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=120, universal_newlines=True, errors="replace")
        sessions = self.ssh_sessions().get(NODES[i], [])
        self.assertLessEqual(len(sessions), 1)
        self.assertNotIn("REACHED", p.stdout)
        return p, (sessions[0] if sessions else None)


class KnobUnsetTests(LssdSandbox):
    """BENCH_NODE_DATADIR_LSSD unset: the plan, --print-prestart, step 3 and step 7's sessions are the base's."""

    def test_dry_plan_equals_the_base_and_has_no_step_3_lines(self):
        base = self.need_base()
        want = self.norm(self.plan(base), base)
        self.assertEqual(self.calls(), [])
        got = self.norm(self.plan(), self.tree)
        self.assertEqual(self.calls(), [])
        self.assertEqual(got, want)
        for word in ("LSSD", "local SSD", "lssd-mount", "data_disk"):
            self.assertNotIn(word, got)

    def test_print_prestart_equals_the_base_for_every_instance(self):
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

    def test_step_3_equals_the_base(self):
        base = self.need_base()
        runs = []
        for tree in (base, self.tree):
            p = self.step(3, tree)
            self.assertEqual(p.returncode, 0, p.stdout)
            body = p.stdout.split("##########################################\n", 1)[1].split("## step 3 done")[0]
            runs.append((sorted(self.norm(c, tree) for c in self.calls()), self.norm(body, tree),
                         [i.get("data_disk") for i in self.manifest(tree)["instances"]]))
            self.assertEqual(self.ssh_calls(), [])
            self.assertFalse(list((self.run_dir(tree) / "logs").glob("lssd-mount-*")))
            self.assertIn("step_3_done", self.manifest(tree)["timestamps"])
        self.assertEqual(runs[1], runs[0])
        self.assertEqual(len([c for c in runs[1][0] if "get-serial-port-output" in c]), 11)
        self.assertNotIn("LSSD", runs[1][1])

    def test_step_3_is_the_serial_markers_alone(self):
        # Without the base too: the knob unset, and the knob at 0 on a fleet with -lssd nodes.
        for env in ({}, dict(E_ENV, BENCH_NODE_DATADIR_LSSD="0")):
            with self.subTest(env=sorted(env)):
                p = self.step(3, **env)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertEqual(self.ssh_calls(), [])
                self.assertEqual(len([c for c in self.calls() if "get-serial-port-output" in c]), 11)
                self.assertNotIn("LSSD", p.stdout)
                self.assertNotIn("local SSD", p.stdout)
                self.assertFalse(list((self.run_dir() / "logs").glob("lssd-mount-*")))
                self.assertIn("step_3_done", self.manifest()["timestamps"])

    def test_step_2_writes_no_data_disk(self):
        p = self.step(2)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(set(self.data_disks().values()), {None})
        self.assertNotIn("data_disk", p.stdout)

    def test_every_pre_start_session_equals_the_base(self):
        base = self.need_base()
        for i in range(11):
            with self.subTest(inst=NODES[i]):
                got = []
                for tree in (base, self.tree):
                    p, s = self.prestart(tree, i)
                    self.assertIn("RC=0", p.stdout)
                    self.assertIsNotNone(s, p.stdout)
                    got.append(s)
                self.assertEqual(got[1], got[0])
                self.assertNotIn(CHECK_HEAD, got[1])

    def test_print_lssd_mount_is_refused_for_every_node(self):
        for inst in (NODES[2], NODES[0]):
            p = self.run_deploy(self.tree, "--print-lssd-mount", inst, BENCH_RUN_ID=RUN)
            self.assertNotEqual(p.returncode, 0, p.stdout)
            self.assert_dry(p)
            self.assertEqual(self.calls(), [])
            self.assertIn("%s keeps its data directory on the boot disk" % inst, p.stdout)
            self.assertIn("BENCH_NODE_DATADIR_LSSD=0", p.stdout)
            self.assertNotIn(MOUNT_HEAD, p.stdout)


class OptionEStep2Tests(LssdSandbox):
    """Option (e): step 2's half of instances[].data_disk for all eleven nodes."""

    def test_every_instance_gets_its_data_disk_and_none_under_disks(self):
        p = self.step(2, **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn('    instances[].data_disk: "local-ssd" on 6 node(s) (step 3 mounts them and fills it in), '
                      '"boot" on the others', p.stdout)
        dd = self.data_disks()
        for i in range(11):
            with self.subTest(inst=NODES[i]):
                self.assertEqual(dd[NODES[i]], {"class": "local-ssd"} if i in LSSD_IDX else BOOT_DISK)
        for inst in self.manifest()["instances"]:
            self.assertNotIn("disks", inst)
            self.assertNotIn("data_disk", inst["boot_disk"])
        self.assertEqual(self.ssh_calls(), [])

    def test_a_boot_disk_without_provisioned_figures_records_null(self):
        env = dict(E_ENV, BENCH_NODE_DISK_SIZE="200", BENCH_NODE_DISK_IOPS="", BENCH_NODE_DISK_THROUGHPUT="")
        p = self.lib("data_disk_plan", **env)
        self.assertEqual(p.returncode, 0, p.stdout)
        got = json.loads(p.stdout)
        self.assertEqual(sorted(got), sorted(NODES))
        for i in range(11):
            self.assertEqual(got[NODES[i]], {"class": "local-ssd"} if i in LSSD_IDX else
                             {"class": "boot", "type": "hyperdisk-balanced", "size_gb": 200, "provisioned_iops": None,
                              "provisioned_throughput": None})
        self.assertEqual(self.calls(), [])


class OptionEStep3Tests(LssdSandbox):
    """Option (e): step 3 mounts the six local SSDs and records them."""

    def deploy_2(self, **env):
        p = self.step(2, **dict(E_ENV, **env))
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_the_six_are_mounted_recorded_and_summed(self):
        self.deploy_2()
        p = self.step(3, **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(sorted(self.ssh_calls()), sorted(NODES[i] for i in LSSD_IDX))
        self.assertEqual(len([c for c in self.calls() if "get-serial-port-output" in c]), 11)
        sessions = self.ssh_sessions()                   # (read before self.builder: each run has its own record)
        self.assertEqual(sorted(sessions), sorted(NODES[i] for i in LSSD_IDX))
        for i in LSSD_IDX:
            with self.subTest(inst=NODES[i]):
                self.assertEqual(sessions[NODES[i]], [self.builder("bench_lssd_mount_script", i, **E_ENV)])
                self.assertIn("      " + success_line(i) + "\n", p.stdout)
        dd = self.data_disks()
        for i in range(11):
            with self.subTest(inst=NODES[i]):
                got = dict(dd[NODES[i]])
                if i in LSSD_IDX:
                    self.assertRegex(got.pop("ts"), ISO_RE)
                    self.assertEqual(got, lssd_record(i))
                else:
                    self.assertEqual(got, BOOT_DISK)
        self.assertIn("\nLSSD_MOUNT_SUMMARY nodes=6 done=6 kept=0 resumed=0 failed=[]\n", p.stdout)
        self.assertIn("up to 4 at a time", p.stdout)
        logs = list((self.run_dir() / "logs").glob("lssd-mount-*.log"))
        self.assertEqual(len(logs), 1)
        self.assertRegex(logs[0].name, r"^lssd-mount-\d{8}T\d{6}Z\.log$")
        log = logs[0].read_text()
        self.assertEqual(re.findall(r"^== (\S+) ", log, re.M), [NODES[i] for i in LSSD_IDX])
        for i in LSSD_IDX:
            self.assertIn(success_line(i) + "\n", log)
        self.assertNotIn("\r", log)
        self.assertIn("step_3_done", self.manifest()["timestamps"])
        # The serial markers came first, for every node.
        self.assertLess(p.stdout.rindex("'devnet-startup.sh complete'"), p.stdout.index("local SSD -> data directory"))

    def test_a_lost_node_stops_the_step_naming_it_and_the_others_are_kept(self):
        self.deploy_2()
        p = self.step(3, SHIM_LSSD="bench-validator-05=lost", **E_ENV)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertEqual(sorted(self.ssh_calls()), sorted(NODES[i] for i in LSSD_IDX))
        self.assertIn("      LSSD_MOUNT bench-validator-05 failed lost: ", p.stdout)
        self.assertIn("      ✗ bench-validator-05: bench-validator-05 failed lost: ", p.stdout)
        self.assertIn("LSSD_MOUNT_SUMMARY nodes=6 done=5 kept=0 resumed=0 failed=[bench-validator-05]\n", p.stdout)
        self.assertIn("step 3: the data directory is not on the local SSD of bench-validator-05 ", p.stdout)
        dd = self.data_disks()
        self.assertEqual(dd["bench-validator-05"], {"class": "local-ssd"})
        for i in LSSD_IDX:
            if NODES[i] != "bench-validator-05":
                self.assertEqual(dd[NODES[i]]["mkfs"], "done", NODES[i])
        self.assertNotIn("step_3_done", self.manifest()["timestamps"])

    def test_a_node_answering_nothing_stops_the_step_one_at_a_time(self):
        self.deploy_2()
        p = self.step(3, SHIM_LSSD="bench-validator-10=none bench-validator-03=lost", BENCH_NODE_JOBS="1", **E_ENV)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("at a time", p.stdout)
        self.assertEqual(self.ssh_calls(), [NODES[i] for i in LSSD_IDX])      # serially, in order, every node
        self.assertIn("      ✗ bench-validator-10: no 'LSSD_MOUNT bench-validator-10 ' line", p.stdout)
        self.assertIn("LSSD_MOUNT_SUMMARY nodes=6 done=4 kept=0 resumed=0 "
                      "failed=[bench-validator-03 bench-validator-10]\n", p.stdout)
        self.assertIn("not on the local SSD of bench-validator-03 bench-validator-10 ", p.stdout)
        dd = self.data_disks()
        self.assertEqual(dd["bench-validator-10"], {"class": "local-ssd"})
        self.assertEqual(dd["bench-validator-03"], {"class": "local-ssd"})
        self.assertEqual(dd["bench-validator-04"]["mkfs"], "done")
        log = next((self.run_dir() / "logs").glob("lssd-mount-*.log")).read_text()
        self.assertIn("== bench-validator-10 (asia-south1-c) ", log)

    def test_a_rerun_keeps_and_resumes(self):
        self.deploy_2()
        p = self.step(3, SHIM_LSSD="bench-validator-07=resumed", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("LSSD_MOUNT_SUMMARY nodes=6 done=5 kept=0 resumed=1 failed=[]\n", p.stdout)
        self.assertEqual(self.data_disks()["bench-validator-07"]["mkfs"], "resumed")
        first = self.data_disks()
        p = self.step(3, SHIM_LSSD_DEFAULT="kept", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("LSSD_MOUNT_SUMMARY nodes=6 done=0 kept=6 resumed=0 failed=[]\n", p.stdout)
        dd = self.data_disks()
        for i in LSSD_IDX:
            got, was = dict(dd[NODES[i]]), dict(first[NODES[i]])
            self.assertEqual(got.pop("mkfs"), "kept")
            got.pop("ts"); was.pop("ts"); was.pop("mkfs")
            self.assertEqual(got, was)
        for i in BOOT_IDX:
            self.assertEqual(dd[NODES[i]], BOOT_DISK)
        self.assertEqual(len(list((self.run_dir() / "logs").glob("lssd-mount-*.log"))), 2)
        # A lost node on a re-run stops it; its earlier record is kept as it was.
        p = self.step(3, SHIM_LSSD_DEFAULT="kept", SHIM_LSSD="bench-validator-04=lost", **E_ENV)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("kept=5 resumed=0 failed=[bench-validator-04]", p.stdout)
        self.assertEqual(self.data_disks()["bench-validator-04"], dd["bench-validator-04"])

    def test_the_live_guard_keeps_a_dry_mount_session_from_any_call(self):
        p = self.funcs('LSSD_MOUNT_DIR="$TMPDIR"; lssd_mount_node 2; echo "RC=$?"; ls "$TMPDIR"',
                       "node_datadir", "lssd_mount_node", TEST_APPLY="0", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout, "RC=0\n")
        self.assertEqual(self.calls(), [])
        p = self.funcs('LSSD_MOUNT_DIR="$TMPDIR"; lssd_mount_node 2; cat "$TMPDIR/2.out"',
                       "node_datadir", "lssd_mount_node", TEST_APPLY="1", **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.ssh_calls(), [NODES[2]])
        self.assertIn(success_line(2), p.stdout)


class OptionEStep7Tests(LssdSandbox):
    """Option (e): step 7's pre-start session starts with the check on the six, and only on them."""

    def test_the_check_comes_first_on_the_six_and_nowhere_else(self):
        for i in range(11):
            with self.subTest(inst=NODES[i]):
                p, off = self.prestart(self.tree, i)
                self.assertIn("RC=0", p.stdout)
                p, on = self.prestart(self.tree, i, **E_ENV)
                self.assertIn("RC=0", p.stdout)
                if i in LSSD_IDX:
                    check = self.builder("bench_lssd_check_script", i, **E_ENV)
                    self.assertTrue(check.startswith(CHECK_HEAD), check)
                    self.assertTrue(check.endswith(") || exit 1\n"), check)
                    self.assertEqual(on, check + off)
                else:
                    self.assertEqual(on, off)
                    self.assertNotIn(CHECK_HEAD, on)

    def test_a_check_that_fails_stops_the_node_before_any_start(self):
        p, s = self.prestart(self.tree, 3, SHIM_LSSD_CHECK="fail", **E_ENV)
        self.assertTrue(s.startswith(CHECK_HEAD), s[:200])
        self.assertNotIn("RC=0", p.stdout)
        self.assertIn("      PRECFG_FAIL bench-validator-04 local SSD not mounted at /var/lib/telcoin", p.stdout)
        self.assertIn("pre-start config failed on bench-validator-04 — no node has been started", p.stdout)
        p, s = self.prestart(self.tree, 1, SHIM_LSSD_CHECK="fail", **E_ENV)       # a boot-disk node: no check
        self.assertIn("RC=0", p.stdout)


class DryPathTests(LssdSandbox):
    """The plan's step-3 and step-7 lines, and --print-lssd-mount; no call in any of them."""

    def test_the_plan_has_the_step_3_lines(self):
        out = self.plan(**E_ENV)
        self.assertEqual(self.calls(), [])
        step3 = out.split("   3  bootstrap ", 1)[1].split("\n   4  firewall ", 1)[0]
        self.assertIn("local SSD -> data directory (BENCH_NODE_DATADIR_LSSD=1), per node (BENCH_NODE_JOBS=4 at a "
                      "time), one IAP session, script on stdin (bench_lssd_mount_script; --print-lssd-mount "
                      "<instance>):", step3)
        self.assertIn("\n                       %s\n" % " ".join(NODES[i] for i in LSSD_IDX), step3)
        self.assertIn("device /dev/disk/by-id/google-local-nvme-ssd-0 (only); first time (no marker "
                      "/var/lib/bench-lssd/uuid): " + MKFS, step3)
        self.assertIn("mount at /var/lib/telcoin with the fstab options of /; fstab UUID=<uuid> <dir> ext4 "
                      "<options of />,nofail,x-systemd.device-timeout=30s 0 2;", step3)
        self.assertIn("telcoin.service.d/bench-lssd.conf RequiresMountsFor=<dir>", step3)
        self.assertIn("LSSD_MOUNT <instance> ... mkfs=done|kept|resumed -> manifest.instances[].data_disk", step3)
        self.assertIn("/logs/lssd-mount-<utc>.log; a failed or missing line stops the step and names the node", step3)
        self.assertIn("after every node: LSSD_MOUNT_SUMMARY nodes= done= kept= resumed= failed=[]", step3)
        self.assertIn("on the 6 local-SSD node(s), before anything else: bench_lssd_check_script (the data "
                      "directory must be the SSD mount, else PRECFG_FAIL <instance> local SSD not mounted at <dir>)",
                      out.split("   7  finalize ", 1)[1])
        # What the plan says the script does is what the script does.
        script = self.builder("bench_lssd_mount_script", 2, **E_ENV)
        for text in (MKFS, "google-local-nvme-ssd-0", "/var/lib/bench-lssd/uuid", "nofail,x-systemd.device-timeout=30s 0 2",
                     "RequiresMountsFor=", "telcoin.service.d/bench-lssd.conf"):
            self.assertIn(text, script)

    def test_print_lssd_mount_prints_the_script_and_calls_nothing(self):
        p = self.run_deploy(self.tree, "--print-lssd-mount", NODES[9], BENCH_RUN_ID=RUN, **E_ENV)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assert_dry(p)
        self.assertEqual(self.calls(), [])
        self.assertEqual(p.stdout, self.builder("bench_lssd_mount_script", 9, **E_ENV))
        self.assertTrue(p.stdout.startswith(MOUNT_HEAD))
        self.assertIn("\nM=/var/lib/telcoin\n", p.stdout)
        self.assertFalse(self.run_dir().exists())

    def test_print_lssd_mount_refuses_a_boot_disk_node_and_a_stranger(self):
        for inst, why in (("bench-validator-08", "keeps its data directory on the boot disk (machine type "
                                                 "c3-highcpu-8, BENCH_NODE_DATADIR_LSSD=1)"),
                          ("bench-observer-11", "keeps its data directory on the boot disk (machine type "
                                                "c3-standard-8, BENCH_NODE_DATADIR_LSSD=1)"),
                          ("devnet-validator-1", "is not a bench instance")):
            with self.subTest(inst=inst):
                p = self.run_deploy(self.tree, "--print-lssd-mount", inst, BENCH_RUN_ID=RUN, **E_ENV)
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assert_dry(p)
                self.assertEqual(self.calls(), [])
                self.assertIn("%s %s" % (inst, why), p.stdout)
                self.assertNotIn(MOUNT_HEAD, p.stdout)

    def test_a_lssd_node_with_the_knob_off_is_refused(self):
        env = dict(E_ENV, BENCH_NODE_DATADIR_LSSD="0")
        p = self.run_deploy(self.tree, "--print-lssd-mount", NODES[2], BENCH_RUN_ID=RUN, **env)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("(machine type c3-standard-8-lssd, BENCH_NODE_DATADIR_LSSD=0)", p.stdout)
        self.assertEqual(self.calls(), [])
        out = self.plan(**env)
        self.assertNotIn("LSSD_MOUNT", out)
        self.assertNotIn("bench_lssd_check_script", out)


if __name__ == "__main__":
    unittest.main()
