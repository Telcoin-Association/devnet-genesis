#!/usr/bin/env python3
"""Per-validator certification rate from telcoin logfmt logs.

Usage: cert_rate.py LOGDIR [BUCKET_MIN]
Reads bench-validator-*-telcoin.log.gz; per bucket prints proposals (header proposed),
quorums (quorum reached), re-proposals, Canceled vote errors, Could-not-form, commits.
"""
import gzip, re, sys, glob, os, collections
logdir = sys.argv[1]; bucket = int(sys.argv[2]) if len(sys.argv) > 2 else 10
ts_re = re.compile(r'^ts=(\d{4}-\d\d-\d\d)T(\d\d):(\d\d)')
keys = [("proposed", 'message="header proposed'), ("quorum", 'message="quorum reached'),
        ("repropose", 're-proposing last header'), ("canceled", 'failed to get vote for header'),
        ("noform", 'Could not form a certificate'), ("commit", 'leader_round=')]
for f in sorted(glob.glob(os.path.join(logdir, 'bench-validator-*-telcoin.log.gz'))):
    node = os.path.basename(f).split('-telcoin')[0]
    c = collections.OrderedDict()
    with gzip.open(f, 'rt', errors='replace') as fh:
        for line in fh:
            m = ts_re.match(line)
            if not m: continue
            b = f"{m.group(2)}:{int(m.group(3))//bucket*bucket:02d}"
            d = c.setdefault(b, collections.Counter())
            for k, pat in keys:
                if pat in line: d[k] += 1
    print(f"\n== {node}")
    print("bucket  proposed quorum  rate%  repropose canceled noform commits")
    for b, d in c.items():
        rate = 100.0*d['quorum']/d['proposed'] if d['proposed'] else 0
        print(f"{b}   {d['proposed']:7d} {d['quorum']:6d} {rate:6.1f} {d['repropose']:9d} {d['canceled']:8d} {d['noform']:6d} {d['commit']:7d}")
