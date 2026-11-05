#!/usr/bin/env python3
"""Fake gcloud for benchmark/tests/test_log_filter.py (devnet-log-filter.sh, fully offline).

Installed as <sandbox>/bin/gcloud. Only `gcloud compute ssh <inst> ... --command=<cmd>` is served:
  kind apply    --command="sudo bash -s", stdin's first line "# logfilter: apply"
  kind verify   --command="sudo bash -s", stdin's first line "# logfilter: verify"
  kind health   devnet-lib's wait_healthy probe (its command echoes HEALTHY / NOLISTEN / INACTIVE:)
Anything else: a message on stderr, rc 1.
$LF_SB/plan.json answers per instance and kind: {"<inst>": {"apply": "<stdout>", "apply_rc": 0,
"verify": "<stdout>", "verify_rc": 0, "health": "HEALTHY"}}. A missing stdout is empty, a missing rc
0, a missing health HEALTHY.
$LF_SB/calls.jsonl gets one JSON object per call: seq, argv, inst, kind, cmd, stdin, and
skip_epoch_env (TN_SKIP_EPOCH_WAIT as this process got it, null when unset).
"""
import json
import os
import sys

SB = os.environ["LF_SB"]


def main(argv):
    inst, cmd = "", ""
    if argv[:2] == ["compute", "ssh"] and len(argv) > 2:
        inst = argv[2]
    for a in argv:
        if a.startswith("--command="):
            cmd = a[len("--command="):]
    stdin = ""
    if cmd == "sudo bash -s":
        stdin = sys.stdin.read()
        first = stdin.split("\n", 1)[0]
        kind = {"# logfilter: apply": "apply", "# logfilter: verify": "verify"}.get(first, "script?")
    elif "HEALTHY" in cmd and "NOLISTEN" in cmd:
        kind = "health"
    else:
        kind = "unknown"
    calls = os.path.join(SB, "calls.jsonl")
    seq = 0
    if os.path.exists(calls):
        with open(calls) as f:
            seq = sum(1 for _ in f)
    with open(calls, "a") as f:
        f.write(json.dumps({"seq": seq, "argv": argv, "inst": inst, "kind": kind, "cmd": cmd, "stdin": stdin,
                            "skip_epoch_env": os.environ.get("TN_SKIP_EPOCH_WAIT")}) + "\n")
    if kind in ("unknown", "script?") or not inst:
        sys.stderr.write("fake gcloud: unserved call %r\n" % (argv,))
        return 1
    try:
        with open(os.path.join(SB, "plan.json")) as f:
            plan = json.load(f).get(inst, {})
    except (IOError, OSError, ValueError):
        plan = {}
    if kind == "health":
        sys.stdout.write(plan.get("health", "HEALTHY") + "\n")
        return 0
    out = plan.get(kind, "")
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return int(plan.get(kind + "_rc", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
