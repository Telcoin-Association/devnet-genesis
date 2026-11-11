#!/usr/bin/env python3
"""What a load VM of the run-1 rehearsal uploads and prints (called by fixtures/run1-rehearsal/bin/gcloud
at its create). It stages, under <stub>/staged/<name>-<index>-<now>/: `at` (the clock time its work ends),
`vm`, `serial` (its done marker) and `objects/` (its bucket objects, under <bucket>/<run>/index-<i>/).

A blaster (BENCH_MODE=blast) writes the generator's files in the shapes the names contract fixes
(tasks/bench6-contract.md, schema tn-blast/v2): <label>.json with run.args, run.phases (four phases from
its own start, a little after BENCH_START_AT), run.tail_scan when TAIL_SCAN_SECS is set, totals.resends,
the chain's blocks (one a second over its mixed phase, numbered by time so every generator agrees),
series.per_second and series.send_per_second; landings-<label>.ndjson.gz (one sampled row per 10 s of
the mixed phase, plus a warm-up row) and unlanded-<label>.ndjson.gz. A run index listed in
<stub>/fail-indices makes bench-blaster-03 end rc=1 (its files still go up). The funder (BENCH_MODE=fund)
ends 120 s after its create with funder/funder.json.
"""
import argparse
import gzip
import json
import os

PREAMBLE = 90          # the generator's own preamble (benchmark/config.sh BENCH_PREAMBLE_SECS)
GENESIS = 1794441600   # block number = seconds since this time, so every generator numbers a second alike
TAIL_USED = 60         # a tail scan ends early: every acknowledged transaction landed
TX_PER_BLOCK = {8: 50, 600: 3000}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stub", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--now", type=int, required=True)
    a = p.parse_args()
    text = a.meta[len("^##^"):] if a.meta.startswith("^##^") else a.meta     # gcloud's ^<delim>^ list syntax
    meta = dict(kv.split("=", 1) for kv in text.split("##") if "=" in kv)
    idx = int(meta["RUN_INDEX"])
    stage = os.path.join(a.stub, "staged", "%s-%d-%d" % (a.name, idx, a.now))
    base = os.path.join(meta["BENCH_BUCKET"], meta["RUN_ID"], "index-%d" % idx)
    objects = []
    if meta.get("BENCH_MODE") == "fund":
        at = a.now + 120
        objects.append(("funder/funder.json", json.dumps({"funded": int(meta["SENDERS"]), "index": idx}).encode()))
        serial = "BENCH_FUND_DONE rc=0 reason=ok\n"
    else:
        at, serial, objects = blaster(a.stub, a.name, meta, idx)
    os.makedirs(os.path.join(stage, "objects"))
    for rel, data in objects:
        path = os.path.join(stage, "objects", base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    for name, text in (("serial", serial), ("vm", a.name), ("at", "%d\n" % at)):
        with open(os.path.join(stage, name), "w") as fh:
            fh.write(text)


def blaster(stub, name, meta, idx):
    k = int(name.rsplit("-", 1)[1])
    senders, window = int(meta["SENDERS"]), int(meta.get("WINDOW", "16"))
    wu, mix, cd = int(meta["WARMUP_SECS"]), int(meta["DURATION_SECS"]), int(meta["COOLDOWN_SECS"])
    tail = int(meta.get("TAIL_SCAN_SECS", "0"))
    sample = int(meta.get("LANDINGS_SAMPLE", "0"))
    s0 = int(meta["BENCH_START_AT"]) + 0.5 + 0.2 * k
    bounds = [s0, s0 + PREAMBLE, s0 + PREAMBLE + wu, s0 + PREAMBLE + wu + mix, s0 + PREAMBLE + wu + mix + cd]
    phases = [{"name": n, "start_unix": round(bounds[i], 3), "end_unix": round(bounds[i + 1], 3)}
              for i, n in enumerate(("preamble", "warmup", "mixed", "cooldown"))]
    m0, m1 = int(bounds[2]) + 1, int(bounds[3])
    txb = TX_PER_BLOCK.get(senders, 1000 if window == 4 else 2000)
    args = {"senders": senders, "window": window, "landings_sample": sample, "warmup_secs": wu, "duration_secs": mix,
            "cooldown_secs": cd, "label": name, "nodes": ["bench-validator-%02d=http://192.0.2.%d:8545" % (k, k)]}
    run = {"label": name, "args": args, "phases": phases, "started_unix": round(s0, 3)}
    end = bounds[4]
    if tail:
        args["tail_scan_secs"] = tail
        run["tail_scan"] = {"secs": tail, "start_ms": int(bounds[4] * 1000), "end_ms": int((bounds[4] + TAIL_USED) * 1000),
                            "end_reason": "all_landed", "boundary_block": int(bounds[4]) - GENESIS, "landed_late": 2,
                            "by_type": {}, "unlanded_after": 0}
        end += TAIL_USED
    run["ended_unix"] = round(end, 3)
    t0 = int(bounds[1])
    doc = {"schema": "tn-blast/v2", "run": run,
           "totals": {"resends": {"transient": 1, "other": 0, "gap_episodes": 0, "gap_txs": 0, "resign_nonce": 0,
                                  "resign_fee": 0, "dropped": 0},
                      "unlanded_own_at_cooldown_end": 2, "unlanded_own": 0},
           "blocks": {"columns": ["number", "timestamp", "tx_count"],
                      "rows": [[t - GENESIS, t, txb] for t in range(m0, m1)]},
           "series": {"per_second_columns": ["s", "own_tx"], "per_second_t0_unix": t0,
                      "per_second": [[s, txb // 10] for s in range(int(bounds[3]) - t0)],
                      "send_per_second_columns": ["s", "submitted", "accepted", "resent", "resigned"],
                      "send_per_second_t0_unix": t0,
                      "send_per_second": [[s, 5, 5, 0, 0] for s in range(int(bounds[3]) - t0)]}}
    land = [{"phase": "warmup", "submit_ms": int(bounds[1] * 1000), "seen_ms": int(bounds[1] * 1000) + 900}]
    land += [{"phase": "mixed", "submit_ms": t * 1000, "seen_ms": t * 1000 + 1500, "late": False} for t in range(m0, m1, 10)]
    unlanded = [{"hash": "0x%064x" % (idx * 100 + k), "type": "transfer", "node": args["nodes"][0].split("=")[0],
                 "phase": "mixed", "submit_ms": m0 * 1000, "accept_ms": m0 * 1000 + 5, "resends": 0}]
    objects = [("blasters/%s.json" % name, json.dumps(doc).encode()),
               ("blasters/landings-%s.ndjson.gz" % name, gzip.compress("".join(json.dumps(r) + "\n" for r in land).encode())),
               ("blasters/unlanded-%s.ndjson.gz" % name, gzip.compress("".join(json.dumps(r) + "\n" for r in unlanded).encode()))]
    fail, failed = os.path.join(stub, "fail-indices"), False
    if os.path.exists(fail) and k == 3:
        with open(fail) as fh:
            failed = str(idx) in fh.read().split()
    serial = "BENCH_BLAST_DONE rc=1 reason=gen-failed gen_rc=1\n" if failed else "BENCH_BLAST_DONE rc=0 reason=ok\n"
    return int(end) + 2, serial, objects


if __name__ == "__main__":
    main()
