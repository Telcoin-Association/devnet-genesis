#!/usr/bin/env python3
"""A rehearsal node's startup lines: node-start.py <node dir>. Appends to <node dir>/unit-stdout.log the
version line (`... starting`) and the `node switches` line the node logs once at its start (tasks/bench6-contract.md: target node::switches,
every row of switches.tsv in order, the value from data/parameters.yaml or the row's default, durations
in humantime form with 0s for zero), stamped with the rehearsal's clock ($CLOCK)."""
import datetime
import os
import re
import sys

SHA = "ba43a1f0e270ca1c572d1b8378b39d2fc6360b57"      # the version line of the arm tool's fake node


def humantime(value):
    m = re.match(r"^([0-9]+)(ms|s)$", value)
    if not m:
        return value
    ms = int(m.group(1)) * (1 if m.group(2) == "ms" else 1000)
    return "0s" if ms == 0 else ("%ds" % (ms // 1000) if ms % 1000 == 0 else "%dms" % ms)


def main():
    node = sys.argv[1]
    with open(os.environ["CLOCK"]) as fh:
        t = int(fh.read().strip())
    with open(os.environ["PA_SWITCHES_TSV"]) as fh:
        lines = fh.read().splitlines()
    head = lines[0].split("\t")
    rows = [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]
    with open(os.path.join(node, "data", "parameters.yaml")) as fh:
        # top-level `key: value` lines; the arm tool marks what it writes with a trailing `# bench-override`
        yaml = dict(m.groups() for m in re.finditer(r"^([a-z_]+):[ \t]*([^\s#]+)", fh.read(), re.M))
    fields = []
    for r in rows:
        v = yaml.get(r["key"], r["default"])
        fields.append("%s=%s" % (r["key"], humantime(v) if r["type"] == "dur" else v))
    ts = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    with open(os.path.join(node, "unit-stdout.log"), "a") as fh:
        fh.write('ts=%s level=info target=cli message="telcoin-network 0.1.0 (%s) starting"\n' % (ts, SHA))
        fh.write('ts=%s level=info target=node::switches message="node switches" %s\n' % (ts, " ".join(fields)))


if __name__ == "__main__":
    main()
