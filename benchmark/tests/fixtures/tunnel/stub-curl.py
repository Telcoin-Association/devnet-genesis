#!/usr/bin/env python3
"""Stand-in for curl (test_tunnel.py): records each call as {"argv": [...], "stdin": "..."} in
$FAKE_ROOT/curl-calls.jsonl (stdin is read in full: bench_prom_query's proxy path sends its
credentials there with -K -) and prints $FAKE_CURL_OUT, a Prometheus answer by default."""
import json
import os
import sys

data = sys.stdin.read()
with open(os.path.join(os.environ["FAKE_ROOT"], "curl-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": data}) + "\n")
sys.stdout.write(os.environ.get("FAKE_CURL_OUT", '{"status":"success","data":{"resultType":"vector","result":[]}}'))
