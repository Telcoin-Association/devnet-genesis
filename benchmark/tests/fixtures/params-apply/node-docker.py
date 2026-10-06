#!/usr/bin/env python3
"""docker on a fake node (tests/test_params_apply.py). The node is $STUB_NODE_DIR:
  role          validator | observer
  mode          healthy | unhealthy | stale (boots with its first parameters.yaml) | nocontainer
                (no container until the first restart)
  pre.log       the container log before the restart
  state/restarted   written by the systemctl stub's restart
After the restart the log is generated: the boot lines, with the delays of data/parameters.yaml
(mode stale: of data/first-parameters.yaml), then progress lines past pre.log's (healthy, stale)
or behind them (unhealthy). Every call is appended to calls.log."""
import os
import re
import sys

d = os.environ["STUB_NODE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as fh:
    fh.write("docker %s\n" % " ".join(args))


def read(name, default=""):
    try:
        with open(os.path.join(d, name)) as fh:
            return fh.read()
    except OSError:
        return default


mode = read("mode", "healthy").strip()
role = read("role", "validator").strip()
restarted = os.path.exists(os.path.join(d, "state", "restarted"))
if mode == "nocontainer" and not restarted:
    sys.stderr.write("Error: No such container: telcoin\n")
    sys.exit(1)


def ms(text, key):
    m = re.search(r"(?m)^%s:\s*([0-9]+(?:\.[0-9]+)?)(ms|s)\b" % key, text)
    if not m:
        return None
    return int(round(float(m.group(1)) * (1 if m.group(2) == "ms" else 1000)))


def post_log():
    y = read("data/first-parameters.yaml" if mode == "stale" else "data/parameters.yaml")
    ts = "ts=2026-10-06T12:00:00.000000000Z level=info"
    lines = ['%s target=cli message="telcoin-network 0.1.0 (ba43a1f0e270ca1c572d1b8378b39d2fc6360b57) starting"' % ts]
    for key, words in (("max_header_delay", "Max header delay"), ("min_header_delay", "Min header delay"),
                       ("max_batch_delay", "Max batch delay"), ("vote_timeout", "Vote timeout")):
        v = ms(y, key)
        if v is None and key == "vote_timeout":
            v = 5000
        if v is not None:
            lines.append('%s target=tn_config::node message="%s set to %d ms"' % (ts, words, v))
    ahead = mode != "unhealthy"
    if role == "validator":
        lines.append('%s target=consensus::metrics message="header proposed" round=%d epoch=%d num_batches=0'
                     % (ts, 3 if ahead else 90, 1 if ahead else 0))
        lines.append('%s target=consensus::metrics message="quorum reached" round=%d epoch=%d voting_power=7'
                     % (ts, 4 if ahead else 91, 1 if ahead else 0))
    else:
        lines.append('%s target=tn::observer message="catching up consensus blocks" last_consensus_height=%d'
                     % (ts, 60 if ahead else 40))
    return "\n".join(lines) + "\n"


cmd = args[0] if args else ""
if cmd == "inspect":           # docker inspect -f '{{.State.Running}}' telcoin
    print("true")
elif cmd == "container":       # docker container inspect telcoin
    pass
elif cmd == "logs":
    sys.stdout.write(post_log() if restarted else read("pre.log"))
else:
    sys.stderr.write("fake docker: unexpected %r\n" % (args,))
    sys.exit(3)
