#!/usr/bin/env python3
"""docker on a fake node (tests/test_params_apply.py). The node is $STUB_NODE_DIR:
  role          validator | observer
  mode          healthy | unhealthy | stale (boots with its first parameters.yaml) | nocontainer
                (no container until the first restart)
  switches      what the restarted node logs as its `node switches` line (absent: full):
                  full                every row of $PA_SWITCHES_TSV, from data/parameters.yaml (a
                                      key the file leaves out at its default), durations in the
                                      node's humantime form (0s for zero)
                  none                no line (an image that does not log it)
                  no-optional         the rows whose optional column is "no" only
                  stuck <key> <value> that key always reads <value> (a node that ignores the file)
                  stale               no new line, and the log after the restart still holds pre.log
                                      (with the old start's line) before the new lines
  pre.log       the container log before the restart (the test writes its switches line)
  state/restarted   written by the systemctl stub's start (or restart)
After the restart the log is generated, stamped with the current time: the boot lines, with the
delays of data/parameters.yaml (mode stale: of data/first-parameters.yaml), the switches line, then
progress lines past pre.log's (healthy, stale) or behind them (unhealthy). Every call is appended
to calls.log."""
import datetime
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
switches = read("switches", "full").split()
restarted = os.path.exists(os.path.join(d, "state", "restarted"))
if mode == "nocontainer" and not restarted:
    sys.stderr.write("Error: No such container: telcoin\n")
    sys.exit(1)


def ms(text, key):
    m = re.search(r"(?m)^%s:\s*([0-9]+(?:\.[0-9]+)?)(ms|s)\b" % key, text)
    if not m:
        return None
    return int(round(float(m.group(1)) * (1 if m.group(2) == "ms" else 1000)))


def humantime(value):
    """A duration as the node renders it: 150ms, 2s, and 0s for zero."""
    m = re.match(r"^([0-9]+)(ms|s)$", value)
    if not m:
        return value
    ms_ = int(m.group(1)) * (1 if m.group(2) == "ms" else 1000)
    return "0s" if ms_ == 0 else ("%ds" % (ms_ // 1000) if ms_ % 1000 == 0 else "%dms" % ms_)


def switches_line(y, ts):
    """The `node switches` line the node logs at its start (the names contract's shape)."""
    if not switches or switches[0] in ("none", "stale"):
        return None
    fields = []
    with open(os.environ["PA_SWITCHES_TSV"]) as fh:
        rows = [l.rstrip("\n").split("\t") for l in fh.read().splitlines()[1:] if l.strip()]
    for key, typ, default, _vals, _topic, optional in rows:
        if switches[0] == "no-optional" and optional == "yes":
            continue
        m = re.search(r"(?m)^%s:\s*([^\s#]+)" % re.escape(key), y)
        value = m.group(1) if m else default
        if typ == "dur":
            value = humantime(value)
        if switches[0] == "stuck" and switches[1] == key:
            value = switches[2]
        fields.append("%s=%s" % (key, value))
    return '%s level=info target=node::switches message="node switches" %s' % (ts, " ".join(fields))


def post_log():
    y = read("data/first-parameters.yaml" if mode == "stale" else "data/parameters.yaml")
    ts = "ts=%s level=info" % datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
    lines = ['%s target=cli message="telcoin-network 0.1.0 (ba43a1f0e270ca1c572d1b8378b39d2fc6360b57) starting"' % ts]
    for key, words in (("max_header_delay", "Max header delay"), ("min_header_delay", "Min header delay"),
                       ("max_batch_delay", "Max batch delay"), ("vote_timeout", "Vote timeout")):
        v = ms(y, key)
        if v is None and key == "vote_timeout":
            v = 5000
        if v is not None:
            lines.append('%s target=tn_config::node message="%s set to %d ms"' % (ts, words, v))
    sw = switches_line(y, ts.split(" ")[0])
    if sw:
        lines.append(sw)
    ahead = mode != "unhealthy"
    if role == "validator":
        lines.append('%s target=consensus::metrics message="header proposed" round=%d epoch=%d num_batches=0'
                     % (ts, 3 if ahead else 90, 1 if ahead else 0))
        lines.append('%s target=consensus::metrics message="quorum reached" round=%d epoch=%d voting_power=7'
                     % (ts, 4 if ahead else 91, 1 if ahead else 0))
    else:
        lines.append('%s target=tn::observer message="catching up consensus blocks" last_consensus_height=%d'
                     % (ts, 60 if ahead else 40))
    text = "\n".join(lines) + "\n"
    if switches and switches[0] == "stale":
        text = read("pre.log") + text
    return text


cmd = args[0] if args else ""
if cmd == "inspect":           # docker inspect -f '{{.State.Running}}' | '{{.State.StartedAt}}' telcoin
    print("2026-10-06T11:50:00.000000000Z" if "{{.State.StartedAt}}" in args else "true")
elif cmd == "container":       # docker container inspect telcoin
    pass
elif cmd == "logs":            # --since / --tail are not applied
    sys.stdout.write(post_log() if restarted else read("pre.log"))
else:
    sys.stderr.write("fake docker: unexpected %r\n" % (args,))
    sys.exit(3)
