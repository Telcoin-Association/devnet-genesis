#!/usr/bin/env python3
"""Per node: time from `header proposed` to the node's own `quorum reached`, and the round period.

Usage: propose-latency.py --logs DIR [--from HH:MM:SS|ISO --to ...] [--node-glob 'bench-validator-*-telcoin.log.gz']

Reads logfmt telcoin logs (gzip or plain), pairs the two lines by round, prints per node: proposals,
certified, rate, C p50/p90/p95 (propose -> own quorum, ms), round period p50/p95 (ms, consecutive
proposals), `Canceled` vote errors, and own quorum -> next proposal p50/p95. This is the calibration
input of cadence-model.py (the processing residual is C minus the UDP RTT to the 6th-nearest voter).
"""
import argparse, glob, gzip, os, re, sys

TS = re.compile(r'^ts=(\d{4}-\d\d-\d\d)T(\d\d):(\d\d):(\d\d(?:\.\d+)?)Z')
RND = re.compile(r' round=(\d+)')


def tsec(m):
    return int(m.group(2)) * 3600 + int(m.group(3)) * 60 + float(m.group(4))


def bound(s):
    if s is None:
        return None
    s = s.strip()
    if "T" in s:
        s = s.split("T", 1)[1].rstrip("Z")
    h, mi, se = s.split(":")
    return int(h) * 3600 + int(mi) * 60 + float(se)


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))]) if xs else None


def fmt(x):
    return "—" if x is None else str(x)


def opener(path):
    return gzip.open(path, "rt", errors="replace") if path.endswith(".gz") else open(path, errors="replace")


def analyse(path, lo, hi):
    prop, quor, canc, rounds = {}, {}, 0, []
    with opener(path) as fh:
        for line in fh:
            m = TS.match(line)
            if not m:
                continue
            t = tsec(m)
            if lo is not None and t < lo:
                continue
            if hi is not None and t > hi:
                break
            if 'message="header proposed"' in line:
                r = RND.search(line)
                if r:
                    prop.setdefault(int(r.group(1)), t); rounds.append((int(r.group(1)), t))
            elif 'message="quorum reached"' in line:
                r = RND.search(line)
                if r:
                    quor.setdefault(int(r.group(1)), t)
            elif "failed to get vote for header" in line and "Canceled" in line:
                canc += 1
    C = [(quor[r] - prop[r]) * 1000 for r in prop if r in quor]
    gap = [(prop[r + 1] - quor[r]) * 1000 for r in quor if r + 1 in prop and prop[r + 1] > quor[r]]
    rounds.sort()
    per = [(rounds[i + 1][1] - rounds[i][1]) * 1000 for i in range(len(rounds) - 1) if rounds[i + 1][0] == rounds[i][0] + 1]
    return {"proposed": len(prop), "certified": len(C), "C": C, "period": per, "canceled": canc, "gap": gap}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", required=True)
    ap.add_argument("--node-glob", default="bench-validator-*-telcoin.log.gz")
    ap.add_argument("--from", dest="lo"); ap.add_argument("--to", dest="hi")
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.logs, a.node_glob)))
    if not files:
        print("no file matches %s in %s" % (a.node_glob, a.logs), file=sys.stderr); return 2
    lo, hi = bound(a.lo), bound(a.hi)
    print("| node | proposed | certified | rate % | C p50/p90/p95 ms | period p50/p95 ms | quorum->next p50/p95 ms | canceled |")
    print("|---|---:|---:|---:|---|---|---|---:|")
    for f in files:
        node = os.path.basename(f).split("-telcoin")[0].split(".")[0]
        s = analyse(f, lo, hi)
        rate = 100.0 * s["certified"] / s["proposed"] if s["proposed"] else 0.0
        print("| %s | %d | %d | %.1f | %s/%s/%s | %s/%s | %s/%s | %d |" % (
            node, s["proposed"], s["certified"], rate, fmt(pct(s["C"], .5)), fmt(pct(s["C"], .9)), fmt(pct(s["C"], .95)),
            fmt(pct(s["period"], .5)), fmt(pct(s["period"], .95)), fmt(pct(s["gap"], .5)), fmt(pct(s["gap"], .95)), s["canceled"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
