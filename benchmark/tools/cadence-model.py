#!/usr/bin/env python3
"""Discrete-event model of Narwhal round cadence on a given latency matrix.

Rules (telcoin-network ba43a1f0e, crates/consensus/primary/src/proposer.rs + certifier.rs +
network/handler.rs):
- a node proposes round r+1 once it holds 2f+1 certificates of round r and its min_header_delay
  timer (armed when the previous proposal finished building) has fired; a node expecting to lead
  the next even round uses a zero min delay;
- parents from a round ahead of the node's own make it jump and propose at once;
- a voter answers MissingParents when the header's parents have not reached it; the proposer then
  re-sends with the parents (one extra round trip);
- a header is certified when 7 votes (own + 6) are in before the node proposes the next round;
  otherwise it is canceled; a certificate is "referenced" if some node has it before proposing r+1.
Idle regime only (no batches): the loaded regime adds execution waits this model does not have.

Calibration (defaults): build 60 ms, vote 45 ms, aggregate 30 ms reproduce run r20261006-0458's idle
window on the five-zone layout (round 349 ms measured vs 353 modelled; near-node certification
282-306 ms measured vs 268-284; Sydney 0 % in both). The model under-predicts how much faster the
central node (Montréal, 181 ms measured) certifies, so treat per-node C as ±40 ms.

Example:
  python3 benchmark/tools/cadence-model.py --matrix benchmark/latency/2026-10-06/matrix-udp.csv \
      --layout final=us-west2-a,europe-west2-b,australia-southeast1-c,... --min 250,400 --detail
"""
import csv, heapq, statistics, sys, argparse

def load_matrix(path):
    rows = list(csv.reader(open(path)))
    zones = [z for z in rows[0][1:] if z]
    m = {}
    for row in rows[1:]:
        z = row[0]
        for k, cell in zip(zones, row[1:]):
            if cell not in ("—", "", "-"):
                m[(z, k)] = float(cell)
    return m

def rtt(m, a, b, intra=1.0):
    if a == b: return intra
    return m.get((a, b)) or m.get((b, a))

def simulate(layout, m, min_delay, max_delay, build=60.0, vote_proc=45.0, agg=30.0, mp_extra=5.0,
             rounds=400, warm=60, leader_shortcut=True, missing_parents=True, intra=1.0):
    n = len(layout); f = (n - 1) // 3; q = 2 * f + 1
    d = [[rtt(m, layout[i], layout[j], intra) / 2.0 for j in range(n)] for i in range(n)]  # one-way
    ev = []  # (time, seq, kind, payload)
    seq = [0]
    def push(t, kind, *p): seq[0] += 1; heapq.heappush(ev, (t, seq[0], kind, p))
    certs = [dict() for _ in range(n)]       # certs[k][r] = {origin: arrival_time}
    node_round = [0] * n; last_build_done = [-1e9] * n; proposed_at = [dict() for _ in range(n)]
    inflight = [None] * n                    # (round, votes, canceled?)
    parents_of = {}                          # (i, r) -> list of origins
    pending_quorum_round = [None] * n
    stats = {"proposed": [dict() for _ in range(n)], "certified": [dict() for _ in range(n)],
             "C": [[] for _ in range(n)], "cert_time": {}, "referenced": {}}
    def leader(r): return (r // 2) % n
    def my_min_delay(i, r):  # for the proposal of round r+1 after proposing r
        nxt = r + 1
        if leader_shortcut and nxt % 2 == 0 and leader(nxt) == i: return 0.0
        return min_delay
    def try_advance(i, t):
        r = node_round[i]
        # highest round with a quorum of certs
        best = None
        for rr, cs in certs[i].items():
            if rr >= r and len(cs) >= q and (best is None or rr > best): best = rr
        if best is None: return
        if best > r:  # jump: min delay ready
            schedule_propose(i, best + 1, t)
        else:
            ready_at = max(t, last_build_done[i] + my_min_delay(i, r))
            if pending_quorum_round[i] != best + 1:
                pending_quorum_round[i] = best + 1
                push(ready_at, "propose", i, best + 1)
    def schedule_propose(i, r, t):
        if r <= node_round[i]: return
        pending_quorum_round[i] = r
        push(t, "propose", i, r)
    # genesis: everyone holds round-0 certs from everyone at t=0
    for k in range(n):
        certs[k][0] = {o: 0.0 for o in range(n)}
        push(0.0 + k * 0.01, "propose", k, 1)
    t_end = None
    while ev:
        t, _, kind, p = heapq.heappop(ev)
        if kind == "propose":
            i, r = p
            if r <= node_round[i]: continue
            # cancel the in-flight header (new digest supersedes it)
            if inflight[i] is not None and inflight[i][0] < r and not inflight[i][2]:
                inflight[i] = (inflight[i][0], inflight[i][1], True)
            node_round[i] = r; proposed_at[i][r] = t
            stats["proposed"][i][r] = t
            parents = sorted(certs[i].get(r - 1, {}).keys())
            parents_of[(i, r)] = parents
            inflight[i] = (r, {i}, False)
            tb = t + build
            last_build_done[i] = tb
            for j in range(n):
                if j == i: continue
                push(tb + d[i][j], "req", i, r, j, False)
            push(tb + max_delay, "maxdelay", i, r)
            if r > rounds: t_end = t; break
        elif kind == "req":
            i, r, j, with_parents = p
            # does j hold every parent?
            have = certs[j].get(r - 1, {})
            missing = [o for o in parents_of[(i, r)] if o not in have or have[o] > t]
            if missing and not with_parents and missing_parents:
                # MissingParents reply, proposer re-sends with parents
                push(t + mp_extra + d[j][i] + d[i][j], "req", i, r, j, True)
            else:
                push(t + vote_proc + d[j][i], "vote", i, r, j)
        elif kind == "vote":
            i, r, j = p
            fl = inflight[i]
            if fl is None or fl[0] != r or fl[2]: continue
            fl[1].add(j)
            if len(fl[1]) >= q:
                inflight[i] = (r, fl[1], True)  # done
                tc = t + agg
                stats["certified"][i][r] = tc
                stats["C"][i].append(tc - proposed_at[i][r])
                stats["cert_time"][(i, r)] = tc
                for k in range(n):
                    push(tc + (0 if k == i else d[i][k]), "cert", i, r, k)
        elif kind == "cert":
            i, r, k = p
            certs[k].setdefault(r, {})[i] = t
            try_advance(k, t)
        elif kind == "maxdelay":
            i, r = p
            if node_round[i] == r and not (inflight[i] and inflight[i][2]):
                # re-send: restarts timers (certifier keeps the aggregator)
                last_build_done[i] = t
                push(t + max_delay, "maxdelay", i, r)
    # referenced: cert (i,r) used as a parent by someone
    for (i, r), tc in stats["cert_time"].items():
        stats["referenced"][(i, r)] = any(i in parents_of.get((k, r + 1), []) for k in range(n))
    out = []
    for i in range(n):
        rs = [r for r in stats["proposed"][i] if warm <= r <= rounds]
        cert = [r for r in rs if r in stats["certified"][i]]
        ref = [r for r in cert if stats["referenced"].get((i, r))]
        Cs = [stats["certified"][i][r] - stats["proposed"][i][r] for r in cert]
        per = [stats["proposed"][i][r + 1] - stats["proposed"][i][r] for r in rs if r + 1 in stats["proposed"][i]]
        out.append({"zone": layout[i], "proposed": len(rs), "cert_pct": 100.0 * len(cert) / max(1, len(rs)),
                    "ref_pct": 100.0 * len(ref) / max(1, len(cert)) if cert else 0.0,
                    "C_p50": statistics.median(Cs) if Cs else None,
                    "T_p50": statistics.median(per) if per else None})
    return out


def parse_layout(spec):
    name, _, zones = spec.partition("=")
    if not zones:
        raise SystemExit("--layout needs NAME=zone,zone,... (a zone listed twice holds two validators)")
    return name, [z.strip() for z in zones.split(",") if z.strip()]

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", required=True, help="matrix-udp.csv from latency-matrix.py (RTT ms)")
    ap.add_argument("--layout", action="append", required=True, metavar="NAME=zone,zone,...",
                    help="validator placement; repeatable")
    ap.add_argument("--min", default="50,100,150,200,250,300,350,400,500",
                    help="min_header_delay values (ms, comma list)")
    ap.add_argument("--max", default="auto", help="max_header_delay ms, or auto = max(500, 2*min)")
    ap.add_argument("--build", type=float, default=60.0, help="header build + dispatch (ms)")
    ap.add_argument("--vote", type=float, default=45.0, help="voter-side processing per vote request (ms)")
    ap.add_argument("--agg", type=float, default=30.0, help="vote aggregation + certificate write (ms)")
    ap.add_argument("--intra", type=float, default=1.0, help="same-zone RTT (ms), never probed")
    ap.add_argument("--rounds", type=int, default=300)
    ap.add_argument("--no-missing-parents", action="store_true", help="voters never answer MissingParents")
    ap.add_argument("--no-leader-shortcut", action="store_true", help="next-even-round leader keeps the min delay")
    ap.add_argument("--detail", action="store_true", help="print every node for every arm")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    m = load_matrix(a.matrix)
    mins = [float(x) for x in a.min.split(",") if x]
    rows = []
    for spec in a.layout:
        name, zones = parse_layout(spec)
        for z in zones:
            if not any(z in k for k in m) and len(set(zones)) > 1:
                raise SystemExit("zone %s is not in the matrix" % z)
        for mn in mins:
            mx = max(500.0, 2 * mn) if a.max == "auto" else float(a.max)
            res = simulate(zones, m, mn, mx, a.build, a.vote, a.agg, rounds=a.rounds,
                           leader_shortcut=not a.no_leader_shortcut, missing_parents=not a.no_missing_parents,
                           intra=a.intra)
            T = statistics.median([r["T_p50"] for r in res if r["T_p50"]])
            rows.append({"layout": name, "min_ms": mn, "max_ms": mx, "T_p50_ms": T, "rounds_per_s": 1000.0 / T,
                         "nodes": res})
    if a.json:
        import json
        print(json.dumps(rows, indent=1)); return
    print("| layout | min | max | T p50 ms | rounds/s | certifying < 99 % | referenced < 99 % | slowest C p50 |")
    print("|---|---:|---:|---:|---:|---|---|---|")
    for r in rows:
        res = r["nodes"]
        lowc = ["%s %.0f%%" % (n["zone"], n["cert_pct"]) for n in res if n["cert_pct"] < 99]
        lowr = ["%s %.0f%%" % (n["zone"], n["ref_pct"]) for n in res if n["cert_pct"] >= 99 and n["ref_pct"] < 99]
        slow = max((n for n in res if n["C_p50"] is not None), key=lambda n: n["C_p50"], default=None)
        print("| %s | %.0f | %.0f | %.0f | %.2f | %s | %s | %s |" % (
            r["layout"], r["min_ms"], r["max_ms"], r["T_p50_ms"], r["rounds_per_s"],
            ", ".join(lowc) or "none", ", ".join(lowr) or "none",
            "%.0f (%s)" % (slow["C_p50"], slow["zone"]) if slow else "—"))
        if a.detail:
            for n in res:
                print("|   | | | %s | cert %.1f%% | ref %.1f%% | C50 %s | T50 %s |" % (
                    n["zone"], n["cert_pct"], n["ref_pct"],
                    "%.0f" % n["C_p50"] if n["C_p50"] is not None else "—",
                    "%.0f" % n["T_p50"] if n["T_p50"] is not None else "—"))

if __name__ == "__main__":
    main()
