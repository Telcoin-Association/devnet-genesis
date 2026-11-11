#!/usr/bin/env python3
"""A fake gcloud for test_probe.py: just enough compute semantics for benchmark-probe.sh's live paths.

State: $FAKE_STATE (a JSON file) holds {"instances": [...], "disks": [...]}, each entry the fields the
driver reads (name, zone, labels, users). Every call is appended to $FAKE_CALLS as one JSON line
{"argv": [...], "stdin": "<first 200 chars of the remote script for ssh>"}.

Behaviour switches (environment):
  FAKE_SCP_RC     exit code of `compute scp` (default 0)
  FAKE_SSH_FAIL   exit code of every `compute ssh` that is not the readiness probe (default 0)
  FAKE_DISK_LAG   after an instance delete, its boot disk stays listed (attached) for this many more
                  `disks list` calls before the auto-delete takes it (default 0: at once)
  FAKE_VM_DIR     plays the VM for `run`: ssh answers each remote script by its first-line header
                  comment (setup, host probe, arm start / wait / finish) and the finish leaves the
                  arm's tarball here for the scp down. Unset: ssh answers only the readiness probe.
  FAKE_HOST_JSON  the host probe's JSON object (unset: no HOST_PROBE line, so the record fails)
  FAKE_SUMMARY    the file every arm's results/<arm>.summary.txt is copied from
  FAKE_ARM_RC     the exit code every arm reports (default 0)
  FAKE_PULL_FAILS the first this many arm tarball pulls fail (counted in the state file; default 0)
  FAKE_START_SILENT=1  every arm start session prints nothing and exits 255 (the arm runs all the same)
  FAKE_I1, FAKE_OUTPUT  the files every arm's results/summary-i1.csv and results/<arm>.csv are copied from
  FAKE_DROP_PREFAULT_ARM  for this arm, pg_prefault reads 0 from output 2 on (a read-ahead opener's mark)

It never runs the remote script it receives.
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import time

ZONE_URL = "https://www.googleapis.com/compute/v1/projects/p/zones/"


def load():
    p = os.environ["FAKE_STATE"]
    if not os.path.exists(p):
        return {"instances": [], "disks": []}
    with open(p) as fh:
        return json.load(fh)


def save(st):
    with open(os.environ["FAKE_STATE"], "w") as fh:
        json.dump(st, fh)


def flag(argv, name, default=""):
    for a in argv:
        if a.startswith(name + "="):
            return a[len(name) + 1:]
    return default


def labels_of(argv):
    out = {}
    v = flag(argv, "--labels")
    for kv in v.split(","):
        if "=" in kv:
            k, x = kv.split("=", 1)
            out[k] = x
    return out


def add_file(tar, name, text):
    data = text.encode()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def arm_tarball(vm, arm):
    """The arm dir the VM's finish would tar: start/end/rc, cmd.txt, the summary, g7's census lines."""
    path = os.path.join(vm, arm + ".tar.gz")
    now = int(time.time())
    with tarfile.open(path, "w:gz") as tar:
        add_file(tar, arm + "/start", "%d\n" % (now - 200))
        add_file(tar, arm + "/end", "%d\n" % now)
        add_file(tar, arm + "/rc", os.environ.get("FAKE_ARM_RC", "0") + "\n")
        add_file(tar, arm + "/cmd.txt", "/var/lib/bench-probe/bin/mdbx-writeback-probe --tag %s\n" % arm)
        summary = os.environ.get("FAKE_SUMMARY", "")
        if summary:
            with open(summary) as fh:
                add_file(tar, "%s/results/%s.summary.txt" % (arm, arm), fh.read())
        i1 = os.environ.get("FAKE_I1", "")
        if i1:
            with open(i1) as fh:
                add_file(tar, "%s/results/summary-i1.csv" % arm, fh.read())
        per_output = os.environ.get("FAKE_OUTPUT", "")
        if per_output:
            with open(per_output) as fh:
                lines = fh.read().splitlines()
            if os.environ.get("FAKE_DROP_PREFAULT_ARM") == arm:
                head = lines[0].split(",")
                p, x = head.index("pg_prefault"), head.index("idx")
                for i in range(1, len(lines)):
                    cells = lines[i].split(",")
                    if int(cells[x]) >= 2:
                        cells[p] = "0"
                    lines[i] = ",".join(cells)
            add_file(tar, "%s/results/%s.csv" % (arm, arm), "\n".join(lines) + "\n")
        if arm.startswith("g9-"):
            lines = ["CENSUS_SAFETY live i=%d res_before=100 res_after=104 census_rc=0" % i for i in range(1, 6)]
            lines.append("CENSUS_SAFETY_IO live runs=5 unchanged=0 read_bytes=0")
            lines += ["CENSUS_SAFETY quiet i=%d res_before=900 res_after=900 census_rc=0" % i for i in range(1, 6)]
            lines.append("CENSUS_SAFETY_IO quiet runs=5 unchanged=5 read_bytes=0")
            add_file(tar, arm + "/census-safety.txt", "\n".join(lines) + "\n")
    with open(path, "rb") as fh:
        data = fh.read()
    return len(data), hashlib.sha256(data).hexdigest()


def play_vm(inst, script):
    """The VM's answer to one remote script, by its first-line header comment."""
    vm = os.environ["FAKE_VM_DIR"]
    first = script.split("\n", 1)[0]
    out = []
    for m in re.finditer(r'echo "HOST_STEP (\S+) read-ahead-kb (\d+) \$\*"; exit 0', script):
        out.append("HOST_STEP %s read-ahead-kb %s read_ahead_kb_before=128 read_ahead_kb_after=%s" % (m.group(1), m.group(2), m.group(2)))
    if first.startswith("# setup:"):
        out.append("SETUP_OK kernel=6.8.0-fake")
    elif "# >>> bench-lib: bench_host_probe_script" in script:
        if os.environ.get("FAKE_HOST_JSON"):
            out.append("HOST_PROBE %s %s" % (inst, os.environ["FAKE_HOST_JSON"]))
    else:
        m = re.match(r"# arm (\S+): (start|wait|finish)", first)
        if m:
            arm, step = m.group(1), m.group(2)
            if step == "start":
                if os.environ.get("FAKE_START_SILENT") == "1":   # the session dropped after the unit started
                    return 255
                out.append("ARM_START %s ok disk=nvme0n1 unix=%d" % (arm, int(time.time())))
            elif step == "wait":
                out.append("ARM_DONE %s rc=%s timed_out=0" % (arm, os.environ.get("FAKE_ARM_RC", "0")))
            else:
                n, sha = arm_tarball(vm, arm)
                out.append("ARM_TAR %s bytes=%d sha256=%s" % (arm, n, sha))
    print("\n".join(out))
    return 0


def main(argv):
    stdin = ""
    if argv[:2] == ["compute", "ssh"]:
        stdin = sys.stdin.read()
    with open(os.environ["FAKE_CALLS"], "a") as fh:
        fh.write(json.dumps({"argv": argv, "stdin": stdin[:200]}) + "\n")
    st = load()
    words = [a for a in argv if not a.startswith("-")]
    if words[:2] == ["auth", "print-access-token"]:
        print("fake-token")
        return 0
    if words[:3] == ["compute", "images", "describe"]:
        print(json.dumps({"name": words[3], "status": "READY", "family": "ubuntu-2404-lts-amd64"}))
        return 0
    if words[:3] == ["compute", "machine-types", "describe"]:
        print("8")
        return 0
    if words[:3] == ["compute", "regions", "describe"]:
        print(json.dumps({"quotas": [{"metric": "C3_CPUS", "limit": 200, "usage": 0}]}))
        return 0
    if words[:2] == ["compute", "firewall-rules"]:
        print("[]")
        return 0
    if len(words) >= 3 and words[0] == "compute" and words[1] in ("instances", "disks"):
        kind, verb = words[1], words[2]
        if verb == "list":
            lag = st.get("lag")
            if kind == "disks" and lag:
                lag["left"] -= 1
                if lag["left"] <= 0:
                    st["disks"] = [d for d in st["disks"] if d["name"] != lag["disk"]]
                    st.pop("lag")
                save(st)
            print(json.dumps(st[kind]))
            return 0
        name, zone = (words[3] if len(words) > 3 else ""), flag(argv, "--zone")
        if verb == "create":
            if any(r["name"] == name for r in st[kind]):
                sys.stderr.write("ERROR: already exists\n")
                return 1
            entry = {"name": name, "zone": ZONE_URL + zone, "labels": labels_of(argv)}
            if kind == "instances":
                disk = flag(argv, "--disk").split(",")[0].split("=", 1)[1]
                for d in st["disks"]:
                    if d["name"] == disk:
                        d["users"] = [name]
                entry["boot_disk"] = disk
            else:
                entry["users"] = []
            st[kind].append(entry)
            save(st)
            print("Created [%s]." % name)
            return 0
        if verb == "delete":
            keep = [r for r in st[kind] if r["name"] != name]
            if len(keep) == len(st[kind]):
                sys.stderr.write("ERROR: was not found\n")
                return 1
            if kind == "disks" and [r for r in st[kind] if r["name"] == name][0].get("users"):
                sys.stderr.write("ERROR: The disk resource is already being used by an instance\n")
                return 1
            gone = [r for r in st[kind] if r["name"] == name][0]
            st[kind] = keep
            if kind == "instances":   # the boot disk is auto-delete=yes
                lag = int(os.environ.get("FAKE_DISK_LAG", "0"))
                if lag > 0:
                    st["lag"] = {"disk": gone.get("boot_disk"), "left": lag}
                else:
                    st["disks"] = [d for d in st["disks"] if d["name"] != gone.get("boot_disk")]
            save(st)
            print("Deleted [%s]." % name)
            return 0
    if words[:2] == ["compute", "ssh"]:
        if "PROBE_SSH_READY" in stdin:
            print("PROBE_SSH_READY")
            return 0
        rc = int(os.environ.get("FAKE_SSH_FAIL", "0"))
        if rc == 0 and os.environ.get("FAKE_VM_DIR"):
            return play_vm(words[2], stdin)
        return rc
    if words[:2] == ["compute", "scp"]:
        rc = int(os.environ.get("FAKE_SCP_RC", "0"))
        if rc:
            sys.stderr.write("ERROR: scp failed\n")
            return rc
        src, dst = words[2], words[3]
        m = re.match(r"[^:]+:/var/tmp/bench-probe-(\S+)\.tar\.gz$", src)
        if m and st.get("pull_fails", 0) < int(os.environ.get("FAKE_PULL_FAILS", "0")):
            st["pull_fails"] = st.get("pull_fails", 0) + 1
            save(st)
            sys.stderr.write("scp: connection closed\n")
            return 1
        if m and os.environ.get("FAKE_VM_DIR"):
            got = os.path.join(os.environ["FAKE_VM_DIR"], m.group(1) + ".tar.gz")
            if not os.path.exists(got):
                sys.stderr.write("scp: no such file\n")
                return 1
            shutil.copyfile(got, dst)
        return 0
    sys.stderr.write("fake-gcloud: unhandled %r\n" % (argv,))
    return 9


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
