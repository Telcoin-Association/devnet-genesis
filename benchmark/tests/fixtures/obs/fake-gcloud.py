#!/usr/bin/env python3
"""Offline stand-in for gcloud (test_obs.py): the calls benchmark/obs-lib.sh makes for bench-obs.

State lives under $FAKE_ROOT:
  vm.json          the instance as `compute instances describe --format=json` prints it; absent:
                   there is no VM (describe fails as gcloud does: "... was not found", rc 1).
                   `compute instances create` writes it from its own flags.
  describe-transient
                   N: the first N `instances describe` calls fail as an API error does (rc 1,
                   no "not found"); "always": every one does. describe-count counts the calls.
  serial-done-at   N: `compute instances get-serial-port-output` shows the startup script's last
                   line (`[obs-startup] <date> done`) from its Nth call on; "never": never.
                   Default 1. serial-count counts the calls.
  bringup-answer   what the bring-up session prints (`--command=sudo bash -s` with the script on
                   stdin, first line "# bench-obs: bringup"); default an OBS_STACK_OK line.
                   bringup-rc is its exit status (default 0). The script received is saved as
                   bringup-script.sh.
  df-pct           the data disk use `df --output=pcent /mnt/obs-data` reports (default 12).
  snapshot-fail    when it exists, the snapshot stream (`sudo tar -cf - -C .../snapshots <name> |
                   gzip -1`) fails at once (rc 1); otherwise it sends a tar.gz of <name>/.
  snapshot-cut     when it exists, that tar is cut short inside a whole gzip stream (rc 0), as
                   when the remote tar dies mid-way (the pipeline's status is gzip's).
  create-fail      when it exists, `compute instances create` fails (rc 1).
A forward (`compute ssh ... --ssh-flag=-N`, the tunnel supervisor's) holds for $FAKE_FORWARD_SECS
(default 30) seconds, then exits 255. Every call appends {"argv": [...], "stdin_head": <first line
of stdin or null>} to calls.jsonl. Anything else fails (rc 2), so a test notices a call shape it
does not model.
"""
import gzip
import io
import json
import os
import sys
import tarfile
import time

root = os.environ["FAKE_ROOT"]
argv = sys.argv[1:]


def path(name):
    return os.path.join(root, name)


def flag(name):
    """The value of --<name>=<value> in argv, or None."""
    for a in argv:
        if a.startswith("--%s=" % name):
            return a.split("=", 1)[1]
    return None


def read(name, default):
    return open(path(name)).read().strip() if os.path.exists(path(name)) else default


stdin_data = None
if argv[:2] == ["compute", "ssh"] and flag("command") == "sudo bash -s":
    stdin_data = sys.stdin.read()
with open(path("calls.jsonl"), "a") as f:
    head = stdin_data.splitlines()[0] if stdin_data else None
    f.write(json.dumps({"argv": argv, "stdin_head": head}) + "\n")


def not_found(name):
    print("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
          " - The resource 'projects/p/zones/z/instances/%s' was not found" % name, file=sys.stderr)
    sys.exit(1)


if argv[:3] == ["compute", "instances", "describe"]:
    n = int(read("describe-count", "0")) + 1
    with open(path("describe-count"), "w") as f:
        f.write(str(n))
    transient = read("describe-transient", "0")
    if transient == "always" or n <= int(transient):
        print("ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
              " - Internal error. Please try again or contact Google Support. (fake, call %d)" % n, file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(path("vm.json")):
        not_found(argv[3])
    vm = json.load(open(path("vm.json")))
    fmt = flag("format")
    if fmt == "json":
        print(json.dumps(vm, indent=2))
    elif fmt == "value(name)":
        print(vm["name"])
    elif fmt == "value(status)":
        print(vm.get("status", "RUNNING"))
    elif fmt == "value(id)":
        print(vm["id"])
    else:
        print("fake gcloud: describe format %r not modelled" % fmt, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)

if argv[:3] == ["compute", "instances", "create"]:
    if os.path.exists(path("create-fail")):
        print("ERROR: (gcloud.compute.instances.create) fake failure", file=sys.stderr)
        sys.exit(1)
    name, zone = argv[3], flag("zone")
    labels = dict(kv.split("=", 1) for kv in (flag("labels") or "").split(",") if kv)
    disk = dict(kv.split("=", 1) for kv in (flag("create-disk") or "").split(",") if kv)
    vm = {"name": name, "id": "4242424242424242424", "status": "RUNNING",
          "creationTimestamp": "2026-11-05T04:00:00.000-08:00",
          "machineType": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/machineTypes/%s"
                         % (zone, flag("machine-type")),
          "tags": {"items": (flag("tags") or "").split(",")}, "labels": labels,
          "networkInterfaces": [{"networkIP": "192.0.2.10", "accessConfigs": [{"natIP": "203.0.113.10"}]}],
          "disks": [{"boot": True, "deviceName": name, "diskSizeGb": "20",
                     "source": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/disks/%s" % (zone, name)},
                    {"boot": False, "deviceName": disk.get("device-name"),
                     "diskSizeGb": disk.get("size", "").replace("GB", ""),
                     "source": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/disks/%s"
                               % (zone, disk.get("name"))}]}
    with open(path("vm.json"), "w") as f:
        json.dump(vm, f)
    sys.exit(0)

if argv[:3] == ["compute", "disks", "add-labels"]:
    sys.exit(0)

if argv[:3] == ["compute", "instances", "get-serial-port-output"]:
    n = int(read("serial-count", "0")) + 1
    with open(path("serial-count"), "w") as f:
        f.write(str(n))
    at = read("serial-done-at", "1")
    print("Nov  5 12:00:01 %s google_metadata_script_runner[612]: startup-script: [obs-startup] "
          "Thu Nov  5 12:00:01 UTC 2026 begin" % argv[3])
    print("Nov  5 12:00:02 %s google_metadata_script_runner[612]: startup-script: [obs-startup] "
          "installing Docker..." % argv[3])
    if at != "never" and n >= int(at):
        print("Nov  5 12:03:00 %s google_metadata_script_runner[612]: startup-script: [obs-startup] "
              "Thu Nov  5 12:03:00 UTC 2026 done" % argv[3])
    sys.exit(0)

if argv[:2] == ["compute", "ssh"]:
    cmd = flag("command")
    if cmd is None and "--ssh-flag=-N" in argv:
        time.sleep(float(os.environ.get("FAKE_FORWARD_SECS", "30")))
        sys.exit(255)
    if cmd == "sudo bash -s":
        if stdin_data.splitlines()[:1] != ["# bench-obs: bringup"]:
            print("fake gcloud: session script header %r not modelled" % stdin_data.splitlines()[:1], file=sys.stderr)
            sys.exit(2)
        with open(path("bringup-script.sh"), "w") as f:
            f.write(stdin_data)
        print(read("bringup-answer", "[bench-obs] stack up\nOBS_STACK_OK bench-obs prom=ready grafana=ok secs=7"))
        sys.exit(int(read("bringup-rc", "0")))
    if cmd == "df --output=pcent /mnt/obs-data":
        print("Use%%\n %s%%" % read("df-pct", "12"))
        sys.exit(0)
    prefix, suffix = "sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots ", " | gzip -1"
    if cmd and cmd.startswith(prefix) and cmd.endswith(suffix):
        if os.path.exists(path("snapshot-fail")):
            print("tar: snapshot: Cannot stat: No such file or directory", file=sys.stderr)
            sys.exit(1)
        name = cmd[len(prefix):-len(suffix)]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            data = b"fake tsdb block\n"
            info = tarfile.TarInfo("%s/01JCDE0000000000000000000/chunks/000001" % name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        raw = buf.getvalue()
        if os.path.exists(path("snapshot-cut")):
            raw = raw[:600]
        sys.stdout.buffer.write(gzip.compress(raw))
        sys.exit(0)

print("fake gcloud: unexpected call: %s" % " ".join(argv), file=sys.stderr)
sys.exit(2)
