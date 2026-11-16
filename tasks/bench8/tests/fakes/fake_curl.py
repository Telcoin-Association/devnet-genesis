#!/usr/bin/env python3
"""A stand-in for curl in the shim tests: answers the chain's Prometheus instant queries from fixture JSON.

$FAKE_DIR/prom.json: {"up": [results], "tn_node_mode": [results], "tn_node_switch": [results],
  "fail": bool, "late": {"after": <calls>, "answers": {same keys}}}
The answer is picked by the metric the query names; once $FAKE_DIR/curl.calls holds "after" queries, the
"late" answers replace the first ones (a gauge that needs a scrape or two). Every query is appended to
$FAKE_DIR/curl.calls as one JSON string per line.
"""
import json
import os
import sys


def main():
    fake = os.environ["FAKE_DIR"]
    args = sys.argv[1:]
    query = ""
    for i, a in enumerate(args):
        if a == "--data-urlencode" and i + 1 < len(args) and args[i + 1].startswith("query="):
            query = args[i + 1][len("query="):]
    calls = os.path.join(fake, "curl.calls")
    before = 0
    if os.path.exists(calls):
        with open(calls) as f:
            before = sum(1 for _ in f)
    with open(calls, "a") as f:
        f.write(json.dumps(query) + "\n")
    path = os.path.join(fake, "prom.json")
    cfg = {}
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    if cfg.get("fail"):
        return 7
    answers = cfg
    late = cfg.get("late")
    if late and before >= int(late["after"]):
        answers = late["answers"]
    result = []
    for key in ("tn_node_switch", "tn_node_mode", "up"):
        if key in query:
            result = answers.get(key, [])
            break
    print(json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
