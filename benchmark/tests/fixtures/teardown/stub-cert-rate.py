#!/usr/bin/env python3
"""Stand-in for tools/cert-rate.py in the teardown's temporary tree (test_teardown_local_gate.py, B9):
appends its argv to $FAKE_ROOT/cert-rate.calls (one JSON list per line) and prints an empty cert-rate
report, which bench_certification_record accepts (windows [], nodes {}). The certification pass calls
it with --format json; the after-delete analysis (bench_local_analysis) without."""
import json
import os
import sys

with open(os.path.join(os.environ["FAKE_ROOT"], "cert-rate.calls"), "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
print(json.dumps({"windows": [], "nodes": {}}))
