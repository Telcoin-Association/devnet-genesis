#!/usr/bin/env python3
"""Preliminary read of run 1's blasts from the bench Prometheus (read-only HTTP queries).

For every blast with a mixed phase: the window is [mixed.start + 60 s, mixed.end - 30 s]; every figure is a
rate or an increase over that window, per validator, shown as min / median / max over the ten validators.
"""
import json
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PROM = "http://localhost:19090"
manifest = json.load(open(sys.argv[1]))
kinds = {}
for line in open(sys.argv[2]):
    parts = dict(p.split("=", 1) for p in line.split() if "=" in p)
    if "index" in parts:
        kinds[int(parts["index"])] = (parts["arm"], parts["kind"])


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def q(expr, at):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": expr, "time": f"{at:.0f}"})
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.load(r)
    out = {}
    for s in d["data"]["result"]:
        m = s["metric"]
        node = m.get("node") or m.get("instance") or m.get("host") or "?"
        out[node] = float(s["value"][1])
    return out


def vals(d):
    v = [x for n, x in sorted(d.items()) if "validator" in n and x == x]
    return v


def mmm(v, fmt="{:.0f}"):
    if not v:
        return "n/a"
    return "/".join(fmt.format(x) for x in (min(v), statistics.median(v), max(v)))


blasts = list(manifest.get("blasts", []))
have = {b["index"] for b in blasts}
cur = manifest.get("blast") or {}
ci = cur.get("index", cur.get("run_index"))
if cur and ci is not None and ci not in have:
    cur = dict(cur)
    cur["index"] = ci
    cur.setdefault("phases", manifest.get("phases"))
    blasts.append(cur)

hdr = ("idx arm kind window_s | tx/s | out/s | tx/out | persist_s/out | persist_us/tx | evm_s/out | root_s/out | finish_s/out | "
       "busy_ms/s | commit_s | save_s | refused_behind(sum;max) | hdr/s | vote_to | rpc_refused | unpersisted_max | queued_max | exec_lag_max")
print(hdr)
for b in sorted(blasts, key=lambda x: x["index"]):
    i = b["index"]
    ph = {p["name"]: p for p in (b.get("phases") or [])}
    if "mixed" not in ph:
        print(i, kinds.get(i), "no mixed phase recorded")
        continue
    t0 = ts(ph["mixed"]["start"]) + 60
    t1 = ts(ph["mixed"]["end"]) - 30
    w = int(t1 - t0)
    if w < 60:
        print(i, kinds.get(i), "mixed phase too short", ph["mixed"])
        continue
    W = f"[{w}s]"

    def rate(m):
        return q(f"sum by (node) (rate({m}{W}))", t1)

    def inc(m):
        return q(f"sum by (node) (increase({m}{W}))", t1)

    def mx(m):
        return q(f"max by (node) (max_over_time({m}{W}))", t1)

    tx = rate("tn_engine_executed_transactions_total")
    outs = rate("tn_engine_outputs_executed_total")
    pers_s = rate("tn_engine_persist_duration_seconds_sum")
    pers_c = rate("tn_engine_persist_duration_seconds_count")
    evm_s = rate("tn_engine_evm_seconds_sum")
    root_s = rate("tn_engine_root_seconds_sum")
    fin_s = rate("tn_engine_finish_seconds_sum")
    busy = rate("tn_engine_busy_milliseconds_total")
    com_s = rate("tn_reth_persist_commit_seconds_sum")
    com_c = rate("tn_reth_persist_commit_seconds_count")
    sav_s = rate("tn_reth_persist_save_blocks_seconds_sum")
    sav_c = rate("tn_reth_persist_save_blocks_seconds_count")
    refused = inc("tn_primary_votes_refused_execution_behind_total")
    hdrs = rate("tn_primary_headers_proposed_total")
    vto = inc("tn_primary_vote_timeouts_total")
    rpcref = inc("tn_reth_rpc_admission_refused_total")
    unp = mx("tn_engine_unpersisted_outputs")
    qd = mx("tn_engine_queued_outputs")
    lag = mx("tn_primary_consensus_exec_lag_rounds")

    def per(a, bb, scale=1.0):
        return {n: scale * a[n] / bb[n] for n in a if n in bb and bb[n] > 0}

    arm, kind = kinds.get(i, (b.get("arm", "?"), b.get("kind", "?")))
    rv = vals(refused)
    print(" | ".join([
        f"{i} {arm} {kind} {w}",
        mmm(vals(tx)),
        mmm(vals(outs), "{:.2f}"),
        mmm(vals(per(tx, outs))),
        mmm(vals(per(pers_s, pers_c)), "{:.3f}"),
        mmm(vals(per(pers_s, tx, 1e6))),
        mmm(vals(per(evm_s, outs)), "{:.3f}"),
        mmm(vals(per(root_s, outs)), "{:.3f}"),
        mmm(vals(per(fin_s, outs)), "{:.3f}"),
        mmm(vals(busy)),
        mmm(vals(per(com_s, com_c)), "{:.3f}"),
        mmm(vals(per(sav_s, sav_c)), "{:.3f}"),
        (f"{sum(rv):.0f};{max(rv):.0f}" if rv else "n/a"),
        mmm(vals(hdrs), "{:.2f}"),
        (f"{sum(vals(vto)):.0f}" if vals(vto) else "n/a"),
        (f"{sum(vals(rpcref)):.0f}" if vals(rpcref) else "n/a"),
        mmm(vals(unp)),
        mmm(vals(qd)),
        mmm(vals(lag)),
    ]))
