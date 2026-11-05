#!/usr/bin/env python3
"""Fake gcloud for benchmark/tests/test_iap_retry.py (devnet-lib.sh's IAP wrappers, fully offline).

The test puts a wrapper named gcloud first on PATH that runs this file. Every call takes the next
outcome from the scenario file $IAP_FAKE_DIR/outcomes.json, a JSON list consumed in order (call 1
takes item 1, ...). An item is the name of an outcome in OUTCOMES, or an object
{"like": <name>, "rc": N, "stderr": "...", "stdout": "..."} whose keys override the named outcome
(no "like" = "ok"). A call past the end of the list fails with rc 97 and says so on stderr, so a
retry the scenario did not expect shows up as an unscripted call.

An outcome writes its stdout, then its stderr, and exits with its rc. The stdout of "ok" depends on
the call: `compute instances describe` answers the --format it was asked for (natIP -> 203.0.113.7,
networkIP -> 192.0.2.7), anything else prints "fake gcloud ok".

Each call appends one JSON object to $IAP_FAKE_DIR/calls.jsonl when it begins: seq (1-based),
argv, stdin (every byte gcloud was handed; "" for a closed stdin), outcome (the item's name or
"unscripted"). The wrappers under test run their attempts one after another, so the log needs no
lock.
"""
import json
import os
import sys

EXT_IP = "203.0.113.7"
INT_IP = "192.0.2.7"

REAUTH_TEXT = ("ERROR: (gcloud.compute.ssh) There was a problem refreshing your current auth tokens: "
               "Reauthentication failed. cannot prompt during non-interactive execution.\n"
               "Please run:\n\n  $ gcloud auth login\n\nto obtain new credentials.\n")
REFUSED_TEXT = ("ERROR: (gcloud.compute.start-iap-tunnel) Error while connecting "
                "[4003: 'failed to connect to backend'].\n")

# name -> (rc, stderr); stdout is "" except for "ok".
OUTCOMES = {
    "ok": (0, ""),
    # ssh's own exit code when IAP refuses or drops the tunnel.
    "drop": (255, "Connection closed by remote host (fake drop)\n"),
    # A compute API ReadTimeout: gcloud itself crashes, rc 1 (bench 3, bench09's describe).
    "crash": (1, "ERROR: gcloud crashed (ReadTimeout): HTTPSConnectionPool(host='compute.googleapis.com', "
                 "port=443): Read timed out. (read timeout=300)\n\nIf you would like to report this issue, "
                 "please run the following command:\n  gcloud feedback\n"),
    # The Workspace reauth session expired (r20261007-0316 teardown).
    "reauth": (1, REAUTH_TEXT),
    "reauth255": (255, REAUTH_TEXT),
    "crash-reauth": (1, "ERROR: gcloud crashed (RefreshError): Reauthentication failed. cannot prompt "
                        "during non-interactive execution.\n"),
    "invalid-grant": (1, "ERROR: (gcloud.compute.instances.describe) There was a problem refreshing your "
                         "current auth tokens: ('invalid_grant: Bad Request', {'error': 'invalid_grant'})\n"),
    # A remote command's own stderr that echoes gcloud's login hint (a node-side script or gcloud
    # call), without any of gcloud's own reauth phrases: not the operator's login.
    "remote-hint": (1, "node script: credentials on this node are stale. Please run: gcloud auth login\n"),
    "remote-hint255": (255, "node script: credentials on this node are stale. Please run: gcloud auth login\n"),
    # An IAP refusal that reaches the caller with rc 1 (gcloud compute scp), and with ssh's 255.
    "refused": (1, REFUSED_TEXT),
    "refused255": (255, REFUSED_TEXT),
    "refused4033": (1, "ERROR: (gcloud.compute.start-iap-tunnel) Error while connecting [4033: 'not authorized'].\n"),
    "refused4047": (1, "ERROR: (gcloud.compute.start-iap-tunnel) Error while connecting "
                       "[4047: 'Failed to lookup instance'].\n"),
    "notfound": (1, "ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n"
                    " - The resource 'projects/fake-project/zones/z1/instances/n1' was not found\n"),
    # The remote command's own failure, passed through by gcloud compute ssh.
    "fail": (2, "remote command failed (fake)\n"),
}


def ok_stdout(argv):
    if argv[:3] == ["compute", "instances", "describe"]:
        fmt = " ".join(a for a in argv if a.startswith("--format="))
        if "natIP" in fmt:
            return EXT_IP + "\n"
        if "networkIP" in fmt:
            return INT_IP + "\n"
    return "fake gcloud ok\n"


def resolve(item, argv):
    """(name, rc, stdout, stderr) for one scenario item."""
    if isinstance(item, str):
        item = {"like": item}
    name = item.get("like", "ok")
    rc, err = OUTCOMES[name]
    out = ok_stdout(argv) if rc == 0 else ""
    return (name, int(item.get("rc", rc)), item.get("stdout", out), item.get("stderr", err))


def main():
    base = os.environ["IAP_FAKE_DIR"]
    argv = sys.argv[1:]
    data = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    with open(os.path.join(base, "outcomes.json"), encoding="utf-8") as fh:
        scenario = json.load(fh)
    log = os.path.join(base, "calls.jsonl")
    seq = 1
    if os.path.exists(log):
        with open(log, encoding="utf-8") as fh:
            seq += sum(1 for line in fh if line.strip())
    if seq <= len(scenario):
        name, rc, out, err = resolve(scenario[seq - 1], argv)
    else:
        name, rc, out = "unscripted", 97, ""
        err = "fake gcloud: no outcome scripted for call %d (%d scripted)\n" % (seq, len(scenario))
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"seq": seq, "argv": argv, "stdin": data, "outcome": name}) + "\n")
    sys.stdout.write(out)
    sys.stdout.flush()
    sys.stderr.write(err)
    sys.stderr.flush()
    return rc


if __name__ == "__main__":
    sys.exit(main())
