"""tools/arms-summary.py on a small synthetic bench-6 run, plus the arm-window change in block-rate.py and
propose-latency.py.

The run (T0 = 2026-11-12T00:00:00Z; times are T0 + seconds), four validators (f = 1):
  arm a0   control  begin 0,    ready 120,  end 1800; idle mark 200-500; M16 blast index 0, mixed 600-1080
  arm p1   persist  begin 1800, ready 1920, end 3600; mdbx_random_advice on, evict (v02 keeps 5 pages);
                    M16 index 1, mixed 2400-2880; index 2 failed (rc 1)
  arm v    vote     begin 3600, ready 3720, end 5400; + quorum_exec_block, vote_queue_fix; L index 3, mixed
                    3650-4010 (clipped to 3720 by ready); M16 index 4, mixed 4400-4880
  arm a0b  control  begin 5400, ready 5520, end 7200; M16 index 5 (the main blasters/), mixed 6000-6480
Blocks: one a second over each mixed phase, 1000 tx (L: 50). Outputs every 10 s at T0 + 10k + 5 with
1000 txs, execute 50 ms, commit 100 / 60 / 115 / 130 ms by arm (persist = commit + 20), 200 newly + 100
cow pages. Persist CSVs (v01-v03; v04 has none) every 30 s: the disk writes 245,760 B/s (amplification
2.0), 122,880 B/s during p1 (1.0). Drift (chain Mtx at the window midpoints): a0 0.24, p1 0.72, v M16
1.218, a0b 1.698, so the slope is 30 / 1.458 us/tx per Mtx and a0 -> a0b moved +30 %.
With disk=<node_disk> the CSVs also carry the diskstats counters of disk_rate() against 20,000 IOPS / 800 MiB/s
(H18): a0 IOPS-bound, p1 throughput-bound, v far from both, a0b mixed; v03's CSV has no tick columns.
"""
import ast
import csv
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
TOOLS = TESTS.parent / "tools"
TOOL = TOOLS / "arms-summary.py"
FIX = TESTS / "fixtures" / "arms-summary"
T0 = 1794441600                                  # 2026-11-12T00:00:00Z
VALIDATORS = ["bench-validator-0%d" % i for i in range(1, 5)]
DEFAULTS = {"quorum_exec_block": "false", "quorum_exec_block_starved_rounds": "0", "vote_queue_fix": "false",
            "mdbx_random_advice": "false", "sealed_tx_keep": "false", "digest_dedupe": "false", "recovery_threads": "0",
            "epoch_close_task_drain": "false", "epoch_record_state_check": "false", "parent_grace": "0ms",
            "rpc_admission_backlog_outputs": "0", "pipelined_persist": "false"}
# (index, arm, senders, mixed from, mixed to, rc, tx per block, commit ms)
BLASTS = [(0, "a0", 600, 600, 1080, 0, 1000, 100), (1, "p1", 600, 2400, 2880, 0, 1000, 60),
          (2, "p1", 600, 3000, 3480, 1, 0, 60), (3, "v", 8, 3650, 4010, 0, 50, 115),
          (4, "v", 600, 4400, 4880, 0, 1000, 115), (5, "a0b", 600, 6000, 6480, 0, 1000, 130)]


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 + t))


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(T0 + int(t))) + ".%06d000Z" % int(round((t % 1) * 1e6))


def shapes():
    out = {}
    for line in (FIX / "lines.txt").read_text().splitlines():
        k, _, v = line.partition("\t")
        out[k] = v
    return out


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def arm(name, b, e, sw=None, **extra):
    d = {"name": name, "begin": iso(b), "ready": iso(b + 120), "end": iso(e), "nodes": {}, "via": "params-apply",
         "switches": dict(DEFAULTS, **(sw or {}))}
    d.update(extra)
    return d


def make_run(root, page_fields=True, persist=True, arms=True, a0b_control=True, hand=False, bench6=False, disk=None):
    """The synthetic run under <root>/r20261112-0000; returns its path. hand=True: every blast run by hand,
    as run-arms runs them in bench 6 run 1 (benchmark-blast.sh fund/run): no blasts[], a blast_runs[] `run`
    entry per index (and one more, index 6, rc 1, that left no blasters/ directory), and each archived
    manifest copy holding its own .blast. bench6=True: the node units' fields and lines (BENCH6 below).
    disk=<dict>: the manifest's node_disk, and the persist CSVs carry the diskstats counters of disk_rate()
    (v03's CSV has no tick columns)."""
    S = shapes()
    run = Path(root) / "r20261112-0000"
    (run / "logs").mkdir(parents=True)
    pa = [arm("a0", 0, 1800, marks=[{"label": "idle", "begin": iso(200), "end": iso(500)}]),
          arm("p1", 1800, 3600, {"mdbx_random_advice": "true"},
              host=[{"step": "evict-mdbx", "value": None,
                     "nodes": {"bench-validator-01": {"resident_pages_before": 9, "resident_pages_after": 0},
                               "bench-validator-02": {"resident_pages_before": 9, "resident_pages_after": 5}}}]),
          arm("v", 3600, 5400, {"mdbx_random_advice": "true", "quorum_exec_block": "true", "vote_queue_fix": "true"}),
          arm("a0b", 5400, 7200, A0B_BENCH6 if bench6 else None if a0b_control else {"recovery_threads": "3"})]
    manifest = {"run_id": "r20261112-0000",
                "instances": [{"name": n, "role": "validator"} for n in VALIDATORS],
                "blast": {"run_index": 5, "chaos": 0}, "chaos": [],
                "blasts": [{"index": i, "senders": s, "window": 16, "chaos": 0, "kind": "load", "arm": a,
                            "started": iso(f - 300), "ended": iso(t + 200), "rc": rc,
                            "phases": [{"name": "mixed", "start": iso(f), "end": iso(t)}],
                            "phases_planned": [{"name": "mixed", "start": iso(f), "end": iso(t)}]}
                           for i, a, s, f, t, rc, _, _ in BLASTS]}
    if arms:
        manifest["param_arms"] = pa
    if disk is not None:
        manifest["node_disk"] = disk
    if hand:
        del manifest["blasts"]
        manifest["blast_runs"] = [{"action": act, "index": i, "started": iso(f - 300), "ended": iso(t + 200),
                                   "rc": rc if act == "run" else 0, "log": None}
                                  for i, a, s, f, t, rc, _, _ in BLASTS for act in ("fund", "run")]
        manifest["blast_runs"].append({"action": "run", "index": 6, "started": iso(6600), "ended": iso(6700), "rc": 1,
                                       "log": None})
    number = 1000
    for i, a, s, f, t, rc, txb, _ in BLASTS:
        d = run / "blasters" if i == 5 else run / ("blast-%d-20261112T%02d0000Z" % (i, i)) / "blasters"
        d.mkdir(parents=True)
        rows = []
        for k in range(f, t) if txb else []:
            rows.append([number, T0 + k, txb])
            number += 1
        doc = {"schema": "tn-blast/v2",
               "run": {"label": "bench-blaster-01", "args": {"senders": s, "window": 16, "landings_sample": 100,
                                                             "duration_secs": 360 if s == 8 else 480,
                                                             "nodes": ["bench-validator-01=http://192.0.2.1:8545"]},
                       "phases": [{"name": "mixed", "start_unix": T0 + f, "end_unix": T0 + t}]},
               "totals": {}, "blocks": {"columns": ["number", "timestamp", "tx_count"], "rows": rows},
               "series": {"per_second_columns": ["s", "own_tx"], "per_second_t0_unix": T0 + f,
                          "per_second": [[k, 100] for k in range(t - f)]}}
        if a == "v":
            doc["totals"]["resends"] = {"transient": 2, "other": 1, "gap_episodes": 1, "gap_txs": 4, "resign_nonce": 0,
                                        "resign_fee": 0, "dropped": 0}
            doc["series"].update({"send_per_second_columns": ["s", "submitted", "accepted", "resent", "resigned"],
                                  "send_per_second_t0_unix": T0 + f,
                                  "send_per_second": [[k, 0 if 100 <= k < 135 else 5, 5, 0, 0] for k in range(t - f)]})
        if a == "a0b":
            doc["run"]["tail_scan"] = {"secs": 180, "landed_late": 3, "unlanded_after": 1}
            if bench6:
                doc["nodes"] = [{"label": "bench-validator-01", "errors": {"pool_full": 12, "conn": 1}}]
                doc["totals"]["resends"] = {"transient": 0, "other": 0, "gap_episodes": 0, "gap_txs": 0,
                                            "resign_nonce": 0, "resign_fee": 0, "dropped": 3}
        (d / "bench-blaster-01.json").write_text(json.dumps(doc))
        if a in ("a0", "v"):
            land = [{"phase": "mixed", "submit_ms": (T0 + f) * 1000, "seen_ms": (T0 + f) * 1000 + (
                400000 if (a == "a0" and j < 2) else 3000)} for j in range(10)]
            land.append({"phase": "warmup", "submit_ms": 0, "seen_ms": 900000})
            (d / "landings-bench-blaster-01.ndjson.gz").write_bytes(
                gzip.compress("".join(json.dumps(x) + "\n" for x in land).encode()))
        bm = {"blasters": [{"name": "bench-blaster-01", "late_secs": 2.5}, {"name": "bench-blaster-02", "late_secs": 7.0}]} \
            if a == "p1" else {"blasters": [{"name": "bench-blaster-01"}]}
        if hand:
            # its own .blast; index 0's generators lost run.phases (the copy's real phases stand in), and a
            # kill landed inside index 4's mixed phase (its copy's chaos[])
            bm["blast"] = {"run_index": i, "chaos": 0, "start_at": iso(f - 30)}
            if i == 0:
                del doc["run"]["phases"]
                (d / "bench-blaster-01.json").write_text(json.dumps(doc))
                bm["phases"] = bm["phases_planned"] = [{"name": "mixed", "start": iso(f), "end": iso(t)}]
            if i == 4:
                bm["chaos"] = [{"ts": iso(4600), "action": "kill", "node": "bench-validator-05"}]
        if i != 5:
            (d.parent / "manifest.json").write_text(json.dumps(bm))
    (run / "manifest.json").write_text(json.dumps(manifest))
    # node logs
    commit = {}
    for i, a, s, f, t, rc, txb, cm in BLASTS:
        if rc == 0:
            commit[(f, t)] = cm
    for vi, node in enumerate(VALIDATORS):
        lines = []
        cn = 1
        for (f, t), cm in sorted(commit.items()):
            for k in range(f - 30, t + 30, 10):       # a few outputs outside the window too
                ts = k + 5
                lines.append(S["executed"].format(ts=stamp(ts), cn=cn, round=cn * 2, execute_ms=50, persist_ms=cm + 20,
                                                  txs=1000))
                if bench6:
                    lines.append(S["persisted6"].format(ts=stamp(ts + 0.001), cn=cn, txs=1000, commit_ms=cm,
                                                        pages=bench6_pages(node, ts, cn)))
                    # a0b's recovery pool: v03 recovers on the global pool from 6200, v04's pool failed to build
                    off = (vi == 2 and ts >= 6200) or (vi == 3 and ts >= 5450)
                    lines.append(S["recovered"].format(ts=stamp(ts - 0.5), cn=cn, txs=1000,
                                                       pool="global" if off else "dedicated"))
                else:
                    lines.append(S["persisted" if page_fields else "persisted_bench5"].format(
                        ts=stamp(ts + 0.001), cn=cn, txs=1000, commit_ms=cm, newly=200, cow=100, pw=2000000))
                lines.append(S["task"].format(ts=stamp(ts + 0.002), cn=cn, task_ms=70 + cm))
                cn += 1
        for w0, w1 in [(200, 500)] + sorted(commit):
            for r in range(int(w0), int(w1), 2):
                if bench6:
                    grace = 40 if r % 10 == 0 else 100 if r % 10 == 2 else 0
                    if grace:
                        lines.append(S["grace_ended"].format(ts=stamp(r + 0.05), author="A%d" % vi, round=r - 1,
                                                             outcome="complete" if grace == 40 else "expired", grace=grace))
                    lines.append(S["proposed6"].format(ts=stamp(r + 0.1), round=r, eb=r - 3, et=r, grace=grace,
                                                       pol="starved" if r % 4 == 0 else "tip"))
                else:
                    lines.append(S["proposed"].format(ts=stamp(r + 0.1), round=r))
                starved = node == "bench-validator-03" and w0 == 600 and r % 4 == 0   # a0's M16: v03 at 50 %
                if not starved:
                    lines.append(S["quorum"].format(ts=stamp(r + 0.4), round=r))
        for r in range(4400, 4880, 2):              # votes in v's M16: header (A1, 4500) refused "behind" by v01, v02
            if r == 4500 and vi == 0:               # v01 refuses it twice (a re-request): still one voter
                lines.append(S["vote"].format(ts=stamp(r + 0.2), author="A1", round=r, outcome="behind", lock_ms=0))
            outcome = "behind" if (r == 4500 and vi < 2) else "created"
            lines.append(S["vote"].format(ts=stamp(r + 0.3), author="A1", round=r, outcome=outcome, lock_ms=(r - 4400) // 2))
        if node == "bench-validator-01":
            lines.append(S["tracker"].format(ts=stamp(700.5)))
        if bench6:
            lines.append(S["builder"].format(ts=stamp(60), keep="false"))                   # arm a0: switch off
            lines.append(S["builder"].format(ts=stamp(5460), keep="false" if vi == 3 else "true"))   # a0b: v04 not
            if vi == 3:
                lines.append(S["advice_refused"].format(ts=stamp(1850)))                  # p1: v04's advice refused
                lines.append(S["pool_failed"].format(ts=stamp(5450)))                     # a0b: v04's pool failed
            if vi == 0:
                lines.append(S["pool_failed"].format(ts=stamp(100)))                      # a0: before a0b's begin
        lines.sort()
        (run / "logs" / (node + "-unit-stdout.log.gz")).write_bytes(gzip.compress(("\n".join(lines) + "\n").encode()))
    if persist:
        header = (TOOLS / "persist-csv-header.txt").read_text().strip().split(",")
        (run / "persist").mkdir()
        for node in VALIDATORS[:3]:
            cols = [c for c in header if disk is None or node != "bench-validator-03" or c not in NO_TICKS]
            with open(str(run / "persist" / (node + ".csv")), "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                written = ios = ticks = 0
                for k in range(0, 7201, 30):
                    row = dict.fromkeys(cols, "")
                    row.update(ts_unix=T0 + k, pid=4242, disk_wr_bytes_total=written)
                    if disk is not None:      # one flush an output (3 per 30 s), 2 ms of device time each
                        row.update(disk_wr_ios_total=ios, disk_wr_ticks_ms_total=ticks, disk_flush_ios_total=k // 10,
                                   disk_flush_ticks_ms_total=k // 5)
                    if bench6:      # 10 refaults and 3 major faults per 30 s; the memcg column stays blank
                        row.update(vm_workingset_refault_file_pages_total=10 * k // 30, vm_pgmajfault_total=3 * k // 30)
                    if k % 300 == 0:
                        row.update(mdbx_dat_vma_bytes=10 ** 9, mdbx_dat_rr_bytes=10 ** 9 if k >= 1800 else 0,
                                   mdbx_dat_size_bytes=5 * 10 ** 8)
                    w.writerow([row[c] for c in cols])
                    if disk is None:
                        written += 30 * (122880 if 1800 <= k < 3600 else 245760)
                    else:
                        iops, kib, ms = disk_rate(node, k)
                        ios += 30 * iops
                        written += 30 * iops * kib * 1024
                        ticks += int(round(30 * iops * ms))
    if bench6:
        (run / "metrics.json").write_text(json.dumps({"prometheus": {"series": {
            "tn_reth_sealed_txs_marked": {"by_node": {"bench-validator-01": {
                "max": [[T0 + 6000, 5], [T0 + 6200, 77], [T0 + 6400, 12]]},
                "bench-validator-02": {"max": [[T0 + 5000, 3]]}}},
            # v02 was sampled at 5000, so its counter, first seen at 6100, was created there and counts from 0
            "tn_reth_rpc_admission_refused_total": {"by_node": {
                "bench-validator-01": {"max": [[T0 + 6000, 100], [T0 + 6200, 110], [T0 + 6480, 125]]},
                "bench-validator-02": {"max": [[T0 + 6100, 1], [T0 + 6300, 4]]}}}}}}))
    return run


# bench6=True: arm a0b turns on sealed keep, parent grace, the admission bound, pipelined persist and the recovery pool.
A0B_BENCH6 = {"sealed_tx_keep": "true", "parent_grace": "150ms", "rpc_admission_backlog_outputs": "2",
              "pipelined_persist": "true", "recovery_threads": "3"}


NO_TICKS = ("disk_wr_ticks_ms_total", "disk_flush_ticks_ms_total")
CAPS = {"size_gb": 100, "type": "hyperdisk-balanced", "provisioned_iops": 20000, "provisioned_throughput": 800}


def disk_rate(node, k):
    """(write IOPS, KiB per write, device ms per write) of a node's 30-s step from T0 + k, against CAPS: a0 at 90 % of
    the IOPS cap (v02 at 26,000 for the step from 900: its peak), p1 at 93.75 % of the throughput cap in 256-KiB
    writes, v far from both, a0b mixed (90 / 60 / 30 % of the IOPS cap)."""
    if k < 1800:
        return (26000 if node == "bench-validator-02" and k == 900 else 18000), 4, 1.3
    if k < 3600:
        return 3000, 256, 59
    if k < 5400:
        return 2000, 8, 1.5
    return {"bench-validator-01": 18000, "bench-validator-02": 12000}.get(node, 6000), 4, 1.3


def bench6_pages(node, ts, cn):
    """The storage fields of one 'persisted output' line: the map grows 50 pages an output, prefaulted on every
    node but v03; the advice applied (1 MiB) except on v04 in arm p1; and three fields left off, each on one node in
    one window (v03's page_cow at 2405 in p1, v02's proc_write_bytes at 605 in a0, v04's mdbx_last_pgno in a0b)."""
    f = [("page_newly", 200), ("page_cow", 100), ("page_prefault", 0 if node == "bench-validator-03" else 50),
         ("page_wops", 7), ("proc_write_bytes", 2000000), ("mdbx_used_bytes", (1001 + 50 * cn) * 4096),
         ("mdbx_advised_bytes", 0 if (node == "bench-validator-04" and 1800 <= ts < 3600) else 1048576),
         ("mdbx_last_pgno", 1000 + 50 * cn)]
    drop = {("bench-validator-03", 2405): "page_cow", ("bench-validator-02", 605): "proc_write_bytes"}.get((node, ts))
    if node == "bench-validator-04" and 5900 <= ts < 6600:
        drop = "mdbx_last_pgno"
    return "".join(" %s=%s" % kv for kv in f if kv[0] != drop)


class ArmsSummaryTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="arms-summary-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def summary(self, run, *args, rc=0):
        out = self.tmp / ("out-%d" % len(list(self.tmp.glob("out-*"))))
        p = subprocess.run([sys.executable, str(TOOL), "--run-dir", str(run), "--out-dir", str(out),
                            "--cache-dir", str(Path(run).parent / "cache"), "--prefiltered", str(self.tmp / "none")] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=300)
        self.assertEqual(p.returncode, rc, p.stderr + p.stdout)
        if rc:
            return None, p
        doc = json.loads((out / "arms.json").read_text())
        return doc, (out / "arms.md").read_text()

    def rows(self, doc):
        return dict((r["row_id"], r) for r in doc["summary_rows"])

    def test_rows_windows_and_types(self):
        doc, md = self.summary(make_run(self.tmp), "--no-stages")
        rows = self.rows(doc)
        self.assertEqual(list(rows), ["a0/I", "a0/M16", "p1/M16", "v/L", "v/M16", "a0b/M16"])
        self.assertEqual((rows["a0/M16"]["utc_from"], rows["a0/M16"]["utc_to"], rows["a0/M16"]["seconds"]),
                         (iso(600), iso(1080), 480))
        self.assertEqual((rows["v/L"]["utc_from"], rows["v/L"]["seconds"]), (iso(3720), 290))   # clipped at ready
        self.assertEqual((rows["a0/I"]["utc_from"], rows["a0/I"]["utc_to"]), (iso(200), iso(500)))
        self.assertEqual(rows["a0b/M16"]["blast_idx"], 5)
        self.assertTrue(any("blast index 2: rc 1" in n for n in doc["notes"]))
        self.assertEqual(rows["a0/M16"]["switch_set"], "all defaults")
        self.assertEqual(rows["v/M16"]["switch_set"], "mdbx_random_advice=true,quorum_exec_block=true,vote_queue_fix=true")
        self.assertEqual(rows["a0/M16"]["chain_txps"], 1000.0)
        self.assertEqual(rows["v/L"]["chain_txps"], 50.0)
        self.assertEqual(rows["a0/M16"]["landed_txps"], 100.0)
        self.assertEqual([a["roles"] for a in doc["arm_list"]], [["control"], ["persist"], ["vote"], ["control", "drift"]])
        self.assertIn("| a0/M16 | 00:10:00 → 00:18:00 | 480 | all defaults | 1,000.0 |", md)

    def test_blasts_run_by_hand(self):
        """Run 1 records no blasts[]: blast_runs[] and the archived directories give the same rows, the failed
        index is listed from its rc, and a run that left no directory is listed too."""
        ref, _ = self.summary(make_run(self.tmp), "--no-stages")
        hand_root = self.tmp / "hand"
        hand_root.mkdir()
        doc, _ = self.summary(make_run(hand_root, hand=True), "--no-stages")
        cols = ("row_id", "arm_name", "blast_type", "blast_idx", "utc_from", "utc_to", "chain_txps", "commit_us_tx")
        cut = dict(ref=None)
        for r in ref["summary_rows"]:
            if r["row_id"] == "v/M16":
                r["utc_to"], cut["ref"] = iso(4600), r["window_basis"]     # the kill in index 4's manifest copy
        self.assertEqual([[r[c] for c in cols] for r in doc["summary_rows"]],
                         [[r[c] for c in cols] for r in ref["summary_rows"]])
        rows = self.rows(doc)
        self.assertEqual(rows["v/M16"]["window_basis"], cut["ref"] + ", cut at chaos kill bench-validator-05")
        self.assertEqual(rows["a0/M16"]["window_basis"], "blasts[].phases mixed (real)")
        # without its blast_runs[] entry, the failed blast's outcome comes from its manifest copy's blasters[]
        run = hand_root / "r20261112-0000"
        man = json.loads((run / "manifest.json").read_text())
        man["blast_runs"] = [r for r in man["blast_runs"] if (r["action"], r["index"]) != ("run", 2)]
        (run / "manifest.json").write_text(json.dumps(man))
        copy = next(run.glob("blast-2-*")) / "manifest.json"
        bm = json.loads(copy.read_text())
        bm["blasters"][0]["rc"] = 1
        copy.write_text(json.dumps(bm))
        doc, _ = self.summary(run, "--no-stages")
        self.assertIn("not measured: blast index 2: rc 1, not measured", doc["notes"])
        self.assertNotIn(2, [r["blast_idx"] for r in doc["summary_rows"]])
        self.assertIn("not measured: blast index 2: rc 1, not measured", doc["notes"])
        self.assertIn("not measured: blast index 6: rc 1, not measured", doc["notes"])
        self.assertEqual(self.rows(doc)["v/L"]["blast_type"], "L")

    def test_a_resumed_arm_keeps_its_roles(self):
        mod = load("arms_summary_resume", TOOL)
        sw = mod.switch_table(str(TOOLS.parent / "arms" / "switches.tsv"))
        vote = {"quorum_exec_block": "true", "vote_queue_fix": "true"}
        host = [{"step": "evict-mdbx", "value": None, "nodes": {}}]
        man = {"param_arms": [arm("a0", 0, 100), arm("v", 100, 200, vote, host=host), arm("v-r2", 200, 300, vote, host=host),
                              arm("a0p", 300, 400, host=host)]}
        self.assertEqual([(a["arm_name"], a["roles"], a["control"]) for a in mod.arm_list(man, sw)],
                         [("a0", ["control"], True), ("v", ["vote"], False), ("v-r2", ["vote"], False),
                          ("a0p", ["control", "drift"], True)])

    def test_engine_and_amplification_arithmetic(self):
        doc, _ = self.summary(make_run(self.tmp), "--no-stages")
        rows = self.rows(doc)
        a0, p1 = rows["a0/M16"], rows["p1/M16"]
        self.assertEqual((a0["execute_us_tx"], a0["persist_us_tx"], a0["commit_us_tx"], a0["commit_ms_output"],
                          a0["task_us_tx"], a0["txs_per_output"], a0["exec_txps"]), (50.0, 120.0, 100.0, 100.0, 170.0, 1000, 100.0))
        e = a0["engine_by_node"]["bench-validator-01"]
        # first and last 30-s samples in [600, 1080]: 600 and 1080; 48 outputs between them
        self.assertEqual((e["device_bytes"], e["page_bytes"], e["amp"]), (480 * 245760, 48 * 300 * 4096, 2.0))
        self.assertEqual(e["proc_written_bytes"], 48 * 2000000)
        self.assertEqual(e["page_wops"], 48 * 7)
        self.assertEqual(a0["amp_fleet_median"], 2.0)
        self.assertEqual(p1["amp_fleet_median"], 1.0)
        self.assertTrue(p1["engine_by_node"]["bench-validator-04"]["amp"].startswith(
            "n/a (missing: persist/bench-validator-04.csv"))
        self.assertEqual((a0["rr_vma_min"], p1["rr_vma_min"]), (0.0, 1.0))
        self.assertEqual(p1["evict_resident_after_max"], 5)

    def test_certification_votes_generators(self):
        doc, _ = self.summary(make_run(self.tmp), "--no-stages")
        rows = self.rows(doc)
        a0, v, p1 = rows["a0/M16"], rows["v/M16"], rows["p1/M16"]
        self.assertEqual((a0["cert_min_pct"], a0["cert_min_node"]), (50.0, "bench-validator-03"))
        self.assertEqual(v["cert_min_pct"], 100.0)
        self.assertEqual(rows["a0/I"]["cert_by_validator"]["bench-validator-03"]["certified_pct"], 100.0)
        self.assertEqual((v["behind_per_header_max"], v["behind_per_header_max_minus_f"]), (2, 1))
        self.assertEqual(v["vote_lock_p95_ms"], 227)
        self.assertEqual((a0["tracker_errors"], v["tracker_errors"]), (1, 0))
        self.assertEqual((a0["landings_ge300"], a0["landings_sampled"], v["landings_ge300"]), (2, 10, 0))
        self.assertEqual((v["resends_total"], v["gen_silent_max_s"]), (7, 35))         # 2 + 1 + 4 + 0 + 0
        self.assertEqual(p1["late_secs_max"], 7.0)
        self.assertEqual((rows["a0b/M16"]["tail_landed_late"], rows["a0b/M16"]["tail_unlanded_after"]), (3, 1))

    def test_drift_fit_and_correction(self):
        doc, md = self.summary(make_run(self.tmp), "--no-stages")
        rows, d = self.rows(doc), doc["drift"]["M16"]
        self.assertEqual([rows[k]["drift_x"] for k in ("a0/M16", "p1/M16", "v/M16", "a0b/M16")], [0.24, 0.72, 1.218, 1.698])
        self.assertEqual((d["first"], d["last"], d["moved_pct"], d["adjacent_only"]), ("a0/M16", "a0b/M16", 30.0, True))
        slope = 30.0 / 1.458
        self.assertAlmostEqual(d["slope_us_tx_per_x"], slope, places=3)
        self.assertEqual(rows["p1/M16"]["commit_us_tx_corrected"], round(60 - slope * 0.48, 1))
        self.assertEqual(rows["v/M16"]["commit_us_tx_corrected"], round(115 - slope * 0.978, 1))
        self.assertEqual(rows["a0b/M16"]["commit_us_tx_corrected"], 100.0)
        self.assertEqual(rows["a0/M16"]["commit_ms_output_corrected"], 100.0)
        self.assertEqual((rows["a0/M16"]["commit_fit"]["b_s_per_1k_txs"], rows["a0/M16"]["commit_fit"]["c_s_per_min"]),
                         (None, 0.0))
        self.assertIn("compare adjacent arms only", md)
        self.assertTrue(rows["v/L"]["commit_us_tx_corrected"].startswith("n/a (missing: two control arms with a L row"))
        wall, _ = self.summary(make_run(self.tmp / "wall"), "--no-stages", "--drift-axis", "wall-min")
        self.assertEqual(self.rows(wall)["a0b/M16"]["drift_x"], 94.0)         # (6240 - 600) / 60 from the first block

    def test_within_window_fit_recovers_a_known_slope(self):
        mod = load("arms_summary", TOOL)
        pts = [(0.691 + 0.0285 * x + 0.0306 * m, x, m) for x in (4.0, 5.5, 7.0, 8.0) for m in (0.5, 3.0, 6.5, 9.0, 12.0)]
        a, b, c, r2 = mod.lsq3(pts)
        self.assertEqual((round(a, 4), round(b, 4), round(c, 4), round(r2, 3)), (0.691, 0.0285, 0.0306, 1.0))
        self.assertIsNone(mod.lsq3(pts[:2]))                    # two points fit neither model
        flat = [(0.5 + 0.0306 * m, 5.0, m) for m in (0.5, 3.0, 6.5, 9.0, 12.0)]   # one output size: b is not identifiable
        a, b, c, _ = mod.lsq3(flat)
        self.assertEqual((round(a, 4), b, round(c, 4)), (0.5, None, 0.0306))

    def test_the_15_percent_flag_and_verdicts(self):
        doc, _ = self.summary(make_run(self.tmp), "--no-stages")
        rows = self.rows(doc)

        def verdict(row):
            return dict((v["check"], (v["value"], v["met"])) for v in rows[row]["verdict"])
        a0, p1, v, a0b = verdict("a0/M16"), verdict("p1/M16"), verdict("v/M16"), verdict("a0b/M16")
        self.assertEqual(a0["amplification > 1.2 (bench-5 signature)"], (2.0, True))
        self.assertEqual(a0["min own-header certification < 98 % (starved validators)"], (50.0, True))
        self.assertEqual(a0["landings >= 300 s > 0 (the cliff)"], (2, True))
        self.assertEqual(p1["amplification <= 1.2"], (1.0, True))
        self.assertEqual(p1["resident pages after eviction = 0"], (5, False))
        self.assertEqual(p1["rr bytes / VMA bytes >= 0.99 on every node"], (1.0, True))
        self.assertEqual(v["own-header certification >= 98 % on every validator"], (100.0, True))
        self.assertEqual(v["behind refusals per header <= f"], (1, False))
        self.assertEqual(v["no generator silent > 30 s"], (35, False))
        self.assertEqual(a0b["commit us/tx moved <= 15 % against the first control"], (30.0, False))
        self.assertTrue(a0b["landings >= 300 s > 0 (the cliff)"][0].startswith("n/a (missing: landings-"))
        self.assertEqual(rows["a0/I"]["verdict"], [])
        # a 10 % move: no flag, the drift check is met
        run = make_run(self.tmp / "ten")
        logs = run / "logs"
        for f in logs.iterdir():
            text = gzip.decompress(f.read_bytes()).decode().replace("commit_ms=130 ", "commit_ms=110 ")
            f.write_bytes(gzip.compress(text.encode()))
        ten, _ = self.summary(run, "--no-stages")
        self.assertEqual((ten["drift"]["M16"]["moved_pct"], ten["drift"]["M16"]["adjacent_only"]), (10.0, False))

    def test_every_na_path(self):
        doc, _ = self.summary(make_run(self.tmp), "--no-stages")
        a0 = self.rows(doc)["a0/M16"]
        expect = {"resends_total": "totals.resends", "gen_silent_max_s": "series.send_per_second",
                  "late_secs_max": "manifest blasters[].late_secs", "tail_landed_late": "run.tail_scan",
                  "stages": "tools/stage-latency.py output"}
        for k, what in expect.items():
            self.assertTrue(a0[k].startswith("n/a (missing: %s" % what), (k, a0[k]))
        self.assertTrue(self.rows(doc)["p1/M16"]["landings_ge300"].startswith("n/a (missing: landings-"))
        self.assertTrue(self.rows(doc)["a0/I"]["chain_txps"].startswith("n/a (missing: generator block tables"))
        self.assertTrue(self.rows(doc)["a0/I"]["land_p50_s"].startswith("n/a (missing: generator files"))
        nopages, _ = self.summary(make_run(self.tmp / "np", page_fields=False), "--no-stages")
        self.assertEqual(self.rows(nopages)["a0/M16"]["amp_fleet_median"],
                         "n/a (missing: page_newly / page_cow on 'persisted output')")
        nocsv, _ = self.summary(make_run(self.tmp / "nc", persist=False), "--no-stages")
        r = self.rows(nocsv)["p1/M16"]
        self.assertTrue(r["amp_fleet_median"].startswith("n/a (missing: persist/bench-validator-0"))
        self.assertTrue(r["rr_vma_min"].startswith("n/a (missing: persist/"))
        onectl, _ = self.summary(make_run(self.tmp / "oc", a0b_control=False), "--no-stages")
        self.assertTrue(self.rows(onectl)["p1/M16"]["commit_us_tx_corrected"].startswith(
            "n/a (missing: two control arms with a M16 row"))
        implicit, md = self.summary(make_run(self.tmp / "im", arms=False), "--no-stages", "--types", "M16")
        rows = self.rows(implicit)
        self.assertEqual(list(rows), ["implicit/M16", "implicit/M16-2", "implicit/M16-3", "implicit/M16-4"])
        self.assertTrue(rows["implicit/M16"]["switch_set"].startswith("n/a (missing: param_arms[].switches"))
        self.assertTrue(any("not in --types" in n for n in implicit["notes"]))
        empty = self.tmp / "empty"
        (empty / "logs").mkdir(parents=True)
        (empty / "manifest.json").write_text("{}")
        _, p = self.summary(empty, "--no-stages", rc=2)
        self.assertIn("no row", p.stderr)

    def test_stages_join_and_cache_reuse(self):
        run = make_run(self.tmp)
        doc, md = self.summary(run, "--types", "M16")
        r = self.rows(doc)["a0/M16"]
        self.assertIsInstance(r["stages"], dict)
        self.assertIn("S10", r["stages"])
        self.assertIn("Stages (p50 ms): S0 ", md)
        cache = run.parent / "cache" / "bench-validator-01-unit-stdout.log.gz"
        before = cache.stat().st_mtime_ns
        self.summary(run, "--no-stages")
        self.assertEqual(cache.stat().st_mtime_ns, before)
        self.assertTrue(gzip.decompress(cache.read_bytes()).decode().count('message="persisted output"') > 0)

    def test_bench6_arm_inputs(self):
        """H14b: the node units' fields (storage, sealed keep, admission bound, parent grace, vote fix, cycle time),
        each n/a with what is missing, never 0, and None in an arm whose switch is off."""
        doc, md = self.summary(make_run(self.tmp, bench6=True), "--no-stages")
        rows = self.rows(doc)
        a0, p1, v, a0b = rows["a0/M16"], rows["p1/M16"], rows["v/M16"], rows["a0b/M16"]
        # storage: prefault ratio = sum(page_prefault) / growth of mdbx_last_pgno; a field left off is n/a
        self.assertEqual(a0["prefault_ratio_by_node"], {"bench-validator-01": 1.0, "bench-validator-02": 1.0,
                                                        "bench-validator-03": 0.0, "bench-validator-04": 1.0})
        self.assertEqual((a0["prefault_on_all"], a0["prefault_ratio_min"]), (False, 0.0))
        self.assertEqual(a0b["prefault_on_all"], "n/a (missing: the prefault ratio of bench-validator-04)")
        self.assertTrue(str(p1["engine_by_node"]["bench-validator-03"]["amp"]).startswith(
            "n/a (missing: page_newly / page_cow on 1 of 48 'persisted output' lines"))
        self.assertEqual(p1["amp_fleet_median"], 1.0)
        self.assertTrue(str(a0["engine_by_node"]["bench-validator-02"]["proc_written_bytes"]).startswith(
            "n/a (missing: proc_write_bytes on 47 of 48"))
        # the advice by what the node measured: v04 logged the refusal in p1 (and advised 0); v is clean
        self.assertEqual(p1["advice_on_by_node"]["bench-validator-04"], False)
        self.assertEqual((p1["mdbx_advised_all_nodes"], p1["mdbx_advised_min_bytes"]), (False, 0))
        self.assertIn("advice not in force on bench-validator-04 ('mdbx random-access advice not applied; the database "
                      "works without it' at %s)" % iso(1850), p1["storage_note"])
        self.assertEqual((v["mdbx_advised_all_nodes"], v["mdbx_advised_min_bytes"], v["storage_note"]), (True, 1048576, None))
        self.assertEqual((a0["mdbx_advised_all_nodes"], a0["storage_note"]), (None, None))       # switch off
        # refaults per minute beside the amplification (10 / 30 s and 3 / 30 s; the memcg column blank; v04 no CSV)
        e = a0["engine_by_node"]
        self.assertEqual((e["bench-validator-01"]["refault_per_min"], e["bench-validator-01"]["majfault_per_min"]), (20.0, 6.0))
        self.assertTrue(str(e["bench-validator-01"]["memcg_refault_per_min"]).startswith(
            "n/a (missing: two persist samples with memcg_workingset_refault_file_pages_total"))
        self.assertTrue(str(e["bench-validator-04"]["refault_per_min"]).startswith("n/a (missing: persist/bench-validator-04.csv"))
        self.assertEqual((a0["refault_per_min_median"], a0["majfault_per_min_median"]), (20.0, 6.0))
        # recovery pool: on it only with every line pool=dedicated and no build failure since the arm's begin (v01's
        # failure in a0 is an earlier process); the switch is off in a0
        self.assertEqual(a0b["recovery_pool_by_node"], {"bench-validator-01": True, "bench-validator-02": True,
                                                        "bench-validator-03": False, "bench-validator-04": False})
        self.assertEqual(a0b["recovery_pool_note"], (
            "dedicated recovery pool not in use on bench-validator-03 (pool=global on 28 of 48 'signers recovered' "
            "lines); bench-validator-04 ('signer recovery pool failed to build - recovering on the global pool' at %s): "
            "this arm does not measure the pool on that node" % iso(5450)))
        self.assertEqual((a0["recovery_pool_by_node"], a0["recovery_pool_note"]), (None, None))
        # sealed keep: v04's builder says keeps_sealed=false; the marked gauge's peak from metrics.json
        self.assertEqual(a0b["sealed_keep"], "switch not acting (keeps_sealed not true on bench-validator-04)")
        self.assertEqual((a0b["sealed_marked_peak"], a0["sealed_keep"]), (77, None))
        self.assertTrue(str(a0["sealed_marked_peak"]).startswith("n/a (missing: metrics.json tn_reth_sealed_txs_marked"))
        # admission bound: the node counter's increase (25 + 1 + 3), the generator's pool_full class and its drops
        self.assertEqual((a0b["admission_refused"], a0b["gen_pool_full"], a0b["gen_dropped"]), (29, 12, 3))
        self.assertTrue(str(a0["admission_refused"]).startswith("n/a (missing: metrics.json tn_reth_rpc_admission_refused_total"))
        self.assertTrue(str(a0["gen_pool_full"]).startswith("n/a (missing: nodes[].errors.pool_full"))
        # parent grace: 96 of 240 headers per validator waited (40 or 100 ms), and how each grace ended
        self.assertEqual((a0b["grace_share_pct"], a0b["grace_wait_p50_ms"], a0b["grace_wait_p90_ms"]), (40.0, 40, 100))
        self.assertEqual(a0b["grace_outcomes"], {"complete": 192, "expired": 192})
        self.assertEqual(a0b["grace_nodes_certified_min_pct"], 100.0)
        # vote fix: policy shares, the lag the policy allowed, votes refused as behind per voter
        self.assertEqual((a0b["exec_policy_pct"], a0b["exec_lag_p50"]), ({"starved": 50.0, "tip": 50.0}, 3))
        self.assertEqual(v["votes_refused_behind"], {"bench-validator-01": 2, "bench-validator-02": 1,
                                                     "bench-validator-03": 0, "bench-validator-04": 0})
        # cycle time: the commit interval on every row; pipelined marks proc_write_bytes an upper bound
        self.assertEqual((a0["commit_interval_ms"], a0b["commit_interval_ms"]), (10000.0, 10000.0))
        self.assertEqual((a0["pipelined"], a0b["pipelined"]), (False, True))
        self.assertIs(a0b["engine_by_node"]["bench-validator-01"].get("proc_written_bytes_upper_bound"), True)
        self.assertNotIn("proc_written_bytes_upper_bound", a0["engine_by_node"]["bench-validator-01"])
        for k in ("D47", "D55", "in-flight sealed transactions"):
            self.assertTrue(any(k in n and n.startswith("arm a0b: ") for n in doc["notes"]), k)
        for want in ("| a0b/M16 | n/a (missing: the prefault ratio of bench-validator-04) (0.000) | – (–) | 20.0 / 6.000 / ",
                     "| 29 / 12 / 3 | 40.0 (40 / 100) | complete 192, expired 192 | 100.0 / ",
                     "\n- p1/M16: advice not in force on bench-validator-04 (",
                     "\n- a0b/M16: dedicated recovery pool not in use on bench-validator-03 ("):
            self.assertTrue(want in md, want)
        # without the node units' fields every new column is n/a (bench 5's shape), never 0
        plain, _ = self.summary(make_run(self.tmp / "plain"), "--no-stages")
        for k in ("prefault_on_all", "grace_share_pct", "exec_policy_pct", "exec_lag_p50", "sealed_marked_peak",
                  "admission_refused", "refault_per_min_median"):
            self.assertTrue(str(self.rows(plain)["a0/M16"][k]).startswith("n/a (missing: "), k)

    def test_a_counter_restart_and_first_use_inside_the_window(self):
        """H16: a counter's increase follows the collector's window_count: a drop is a restart and adds the new
        value, and a series first seen inside the window on a node sampled before counts from 0."""
        mod = load("arms_summary_counter", TOOL)
        # the collector's own WindowCount cases (60-s steps, the window [0, 300], the node sampled from step 0)
        for pts, want in (({3: 1, 4: 1, 5: 1}, 1), ({3: 2, 4: 5}, 5), ({0: 5, 1: 5, 2: 5}, 0), ({0: 5, 1: 7}, 2),
                          ({0: 5, 1: 6, 4: 6, 5: 7}, 2), ({0: 5, 1: 9, 4: 2, 5: 3}, 7), ({2: 1, 5: 1}, 1)):
            got = mod.counter_rise([(60.0 * k, float(v)) for k, v in sorted(pts.items())], 0, 300, 0.0)
            self.assertEqual(got, want, pts)
        name = "tn_reth_rpc_admission_refused_total"
        (self.tmp / "metrics.json").write_text(json.dumps({"prometheus": {"series": {
            "tn_node_switch": {"by_node": dict((n, {"max": [[5000, 1], [6480, 1]]}) for n in VALIDATORS[1:])},
            name: {"by_node": {
                # a restart inside the window: 60 is the base, +10, the restart adds 3, +5
                "bench-validator-01": {"max": [[5900, 50], [6000, 60], [6200, 70], [6300, 3], [6480, 8]]},
                # created at its first use inside the window on a node sampled since 5000: from 0
                "bench-validator-02": {"max": [[6300, 2], [6480, 6]]},
                # a restart in the step that straddles the window's start, then +4
                "bench-validator-03": {"max": [[5990, 40], [6010, 5], [6200, 9]]},
                # one point, created inside the window
                "bench-validator-04": {"max": [[6400, 7]]},
                # one point, the node never sampled before it: not measurable
                "bench-observer-05": {"max": [[6400, 9]]}}}}}}))
        prom, first = mod.read_series(str(self.tmp), (name,))
        self.assertEqual((first["bench-validator-01"], first["bench-validator-02"]), (5900.0, 5000.0))
        a, b = 6000.0, 6480.0
        self.assertEqual([mod.counter_rise(prom[name][n], a, b, first.get(n)) for n in VALIDATORS + ["bench-observer-05"]],
                         [18.0, 6.0, 9.0, 7.0, None])
        self.assertEqual(mod.counter_total(prom, first, name, a, b), 40.0)
        self.assertIsNone(mod.counter_total(prom, first, name, 7000.0, 8000.0))
        self.assertIsNone(mod.counter_total(prom, first, "tn_absent_total", a, b))

    DISK = ("wr_ops_per_output", "wr_kib_per_op", "flush_ops_per_output", "wr_iops", "wr_mibps", "wr_iops_peak",
            "wr_mibps_peak", "wr_ms_per_op", "flush_ms_per_op", "iops_pct_of_cap", "mibps_pct_of_cap", "binds",
            "cap_floor_ms_per_output")

    def disk(self, row, node):
        return tuple(row["engine_by_node"][node][k] for k in self.DISK)

    def test_disk_writes_against_the_caps(self):
        """H18 (D84): per node the write operations, sizes and flushes per output, the sustained and peak rates, the
        device time per operation and the shares of the provisioned caps; binds, the row medians, one reading a row."""
        doc, md = self.summary(make_run(self.tmp, disk=dict(CAPS)), "--no-stages")
        rows = self.rows(doc)
        a0, p1, v, a0b = rows["a0/M16"], rows["p1/M16"], rows["v/M16"], rows["a0b/M16"]
        # an IOPS-bound arm: 18,000 writes/s of 4 KiB, 90 % of 20,000; 48 outputs between the samples at 600 and 1080
        self.assertEqual(self.disk(a0, "bench-validator-01"),
                         (180000.0, 4.0, 1.0, 18000.0, 70.31, 18000.0, 70.31, 1.3, 2.0, 90.0, 8.8, "iops", 9000.0))
        # v02's step from 900 ran at 26,000: its peak, and 18,500 sustained over the 480 s
        self.assertEqual(self.disk(a0, "bench-validator-02"),
                         (185000.0, 4.0, 1.0, 18500.0, 72.27, 26000.0, 101.56, 1.3, 2.0, 92.5, 9.0, "iops", 9250.0))
        # a throughput-bound arm: 256-KiB writes at 750 MiB/s, 93.75 % of 800, 15 % of the IOPS cap
        self.assertEqual(self.disk(p1, "bench-validator-01"),
                         (30000.0, 256.0, 1.0, 3000.0, 750.0, 3000.0, 750.0, 59.0, 2.0, 15.0, 93.8, "throughput", 9375.0))
        # far from both caps
        self.assertEqual(self.disk(v, "bench-validator-01"),
                         (20000.0, 8.0, 1.0, 2000.0, 15.62, 2000.0, 15.62, 1.5, 2.0, 10.0, 2.0, "neither", 1000.0))
        # v03's CSV has no tick columns: its device time per operation is n/a, the rest is measured
        v03 = a0["engine_by_node"]["bench-validator-03"]
        self.assertEqual((v03["wr_ms_per_op"], v03["flush_ms_per_op"]), (
            "n/a (missing: two persist samples with disk_wr_ios_total and disk_wr_ticks_ms_total in the window)",
            "n/a (missing: two persist samples with disk_flush_ios_total and disk_flush_ticks_ms_total in the window)"))
        self.assertEqual((v03["wr_iops"], v03["binds"]), (18000.0, "iops"))
        self.assertEqual(set(self.disk(a0, "bench-validator-04")), {"n/a (missing: persist/bench-validator-04.csv)"})
        # the row medians over the nodes that have the value, and how many nodes each cap binds
        self.assertEqual([a0[k + "_median"] for k in ("wr_ops_per_output", "wr_iops", "wr_iops_peak", "wr_ms_per_op",
                                                      "iops_pct_of_cap", "mibps_pct_of_cap", "cap_floor_ms_per_output")],
                         [180000.0, 18000.0, 18000.0, 1.3, 90.0, 8.8, 9000.0])
        self.assertEqual([r["binds_nodes"] for r in (a0, p1, v, a0b)],
                         [{"iops": 3, "throughput": 0, "neither": 0}, {"iops": 0, "throughput": 3, "neither": 0},
                          {"iops": 0, "throughput": 0, "neither": 3}, {"iops": 1, "throughput": 0, "neither": 2}])
        self.assertEqual(doc["disk_caps"], {"iops": 20000, "iops_from": "manifest node_disk.provisioned_iops", "mibps": 800,
                                            "mibps_from": "manifest node_disk.provisioned_throughput"})
        tail = "; not measured on bench-validator-04"
        readings = {
            "a0/M16": "write IOPS within 20 % of the provisioned 20,000 IOPS on 3 of 3 nodes (sustained over the window; "
                      "median 90.0 % of the cap): the disk's IOPS cap bounds this arm" + tail,
            "p1/M16": "write MiB/s within 20 % of the provisioned 800 MiB/s on 3 of 3 nodes (sustained over the window; "
                      "median 93.8 % of the cap): the disk's throughput cap bounds this arm" + tail,
            "v/M16": "no node above 50 % of either cap (sustained over the window; median 10.0 % of 20,000 IOPS, 2.0 % of "
                     "800 MiB/s)" + tail,
            "a0b/M16": "1 of 3 nodes within 20 % of a cap (IOPS 1), the highest 90.0 % of the IOPS cap on bench-validator-01 "
                       "(sustained over the window; median 60.0 % of 20,000 IOPS, 5.9 % of 800 MiB/s): no cap bounds most "
                       "nodes" + tail}
        for rid, want in readings.items():
            self.assertEqual(rows[rid]["disk_reading"], want, rid)
            self.assertIn("\nDisk: %s.\n" % want, md)
        self.assertIn("| node | write ops / output | KiB / op | flushes / output | write IOPS (peak) | write MiB/s (peak) | "
                      "ms / write | ms / flush | % of IOPS cap | % of MiB/s cap | binds | cap floor ms / output |", md)
        self.assertIn("| bench-validator-02 | 185,000.0 | 4.000 | 1.000 | 18,500.0 (26,000.0) | 72.3 (101.6) | 1.300 | "
                      "2.000 | 92.5 | 9.000 | iops | 9,250.0 |", md)

    def test_disk_caps_unknown_partial_or_given(self):
        """H18: without the provisioning every share, binds and the floor are n/a (never 0) while the rates stay
        measured; --disk-iops / --disk-mibps give the caps; a cap the manifest leaves null is n/a on its own."""
        run = make_run(self.tmp, disk={})
        doc, md = self.summary(run, "--no-stages")
        a0 = self.rows(doc)["a0/M16"]
        e = a0["engine_by_node"]["bench-validator-01"]
        iops_na = "n/a (missing: the provisioned IOPS (manifest node_disk.provisioned_iops, or --disk-iops))"
        mibps_na = "n/a (missing: the provisioned MiB/s (manifest node_disk.provisioned_throughput, or --disk-mibps))"
        self.assertEqual((e["iops_pct_of_cap"], e["mibps_pct_of_cap"], e["binds"], e["cap_floor_ms_per_output"]),
                         (iops_na, mibps_na, iops_na, iops_na))
        self.assertEqual((e["wr_iops"], e["wr_ops_per_output"]), (18000.0, 180000.0))
        self.assertEqual((a0["iops_pct_of_cap_median"], a0["binds_nodes"]), (iops_na, iops_na))
        self.assertEqual(a0["disk_reading"], iops_na + " against the caps; sustained write IOPS 18,000.0, MiB/s 70.3 "
                                                       "(median of 3 nodes); not measured on bench-validator-04")
        self.assertEqual((doc["disk_caps"]["iops"], doc["disk_caps"]["iops_from"]), (iops_na, None))
        given, _ = self.summary(run, "--no-stages", "--disk-iops", "20000", "--disk-mibps", "800")
        g = self.rows(given)["a0/M16"]
        self.assertEqual(self.disk(g, "bench-validator-01"),
                         (180000.0, 4.0, 1.0, 18000.0, 70.31, 18000.0, 70.31, 1.3, 2.0, 90.0, 8.8, "iops", 9000.0))
        self.assertTrue(g["disk_reading"].startswith("write IOPS within 20 % of the provisioned 20,000 IOPS on 3 of 3"))
        self.assertEqual((given["disk_caps"]["iops_from"], given["disk_caps"]["mibps_from"]), ("--disk-iops", "--disk-mibps"))
        part, _ = self.summary(make_run(self.tmp / "part", disk={"provisioned_iops": 20000, "provisioned_throughput": None}),
                               "--no-stages")
        e = self.rows(part)["a0/M16"]["engine_by_node"]["bench-validator-01"]
        self.assertEqual((e["iops_pct_of_cap"], e["mibps_pct_of_cap"], e["binds"], e["cap_floor_ms_per_output"]),
                         (90.0, mibps_na, mibps_na, mibps_na))
        _, p = self.summary(run, "--no-stages", "--disk-iops", "0", rc=2)
        self.assertIn("--disk-iops must be positive", p.stderr)

    def test_disk_columns_without_the_counters(self):
        """H18: bench 5's persist CSV shape (bytes only) leaves every disk column n/a with the counter it lacks; a
        counter that goes back is n/a; the peak is the busiest step between consecutive samples, whatever its length."""
        doc, md = self.summary(make_run(self.tmp), "--no-stages")
        a0 = self.rows(doc)["a0/M16"]
        e = a0["engine_by_node"]["bench-validator-01"]
        why = "n/a (missing: two persist samples with disk_wr_ios_total and disk_wr_bytes_total in the window)"
        self.assertEqual((e["wr_iops"], e["wr_ops_per_output"], e["iops_pct_of_cap"], e["binds"]), (why, why, why, why))
        self.assertEqual(e["flush_ops_per_output"], "n/a (missing: two persist samples with disk_flush_ios_total in the window)")
        reading = why + "; no node measured (0 of 4)"
        self.assertEqual((a0["wr_iops_median"], a0["binds_nodes"], a0["disk_reading"]), (why, why, reading))
        self.assertIn("\nDisk: %s.\n" % reading, md)
        self.assertNotIn("| node | write ops / output", md)
        mod = load("arms_summary_disk", TOOL)
        node = type("N", (), {"name": "n1", "persisted": [(15.0,), (45.0,), (75.0,)]})()
        caps = mod.disk_caps({"node_disk": CAPS})

        def rows(ios):
            return [dict(c_ts=t, c_wr_ios=x, c_disk_wr=x * 4096, c_wr_ticks=x, c_flush_ios=None, c_flush_ticks=None)
                    for t, x in zip((0.0, 30.0, 90.0), ios)]
        d = mod.disk_row(node, rows((0, 300, 1500)), 0.0, 90.0, caps)      # 10 writes/s for 30 s, 20/s for 60 s
        self.assertEqual((d["wr_iops"], d["wr_iops_peak"], d["wr_ops_per_output"]), (16.7, 20.0, 500.0))
        self.assertEqual(d["flush_ms_per_op"], "n/a (missing: two persist samples with disk_flush_ios_total and "
                                               "disk_flush_ticks_ms_total in the window)")
        d = mod.disk_row(node, rows((0, 300, 100)), 0.0, 90.0, caps)       # a reboot restarted /proc/diskstats
        self.assertEqual((d["wr_iops"], d["wr_ms_per_op"]), (
            "n/a (missing: a monotonic disk_wr_ios_total (it went back at 1970-01-01T00:01:30Z))",
            "n/a (missing: a monotonic disk_wr_ios_total (it went back at 1970-01-01T00:01:30Z))"))

    def test_field_names_live_only_in_the_table(self):
        src = TOOL.read_text()
        lines = src.splitlines()
        lo = next(i for i, l in enumerate(lines, 1) if l.startswith("# ---- FIELDS (begin)"))
        hi = next(i for i, l in enumerate(lines, 1) if l.startswith("# ---- FIELDS (end)"))
        mod = load("arms_summary_names", TOOL)
        names = set(mod.F.values()) | set(mod.TOPIC_ROLES) | set(mod.GRACE_NODES)
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and \
                    isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
                docstrings.add(id(node.body[0].value))
        # the role column of CHECKS is the plan's own vocabulary (the "pool" role is not the node's `pool` field)
        roles = set(id(row.elts[0]) for node in tree.body if isinstance(node, ast.Assign)
                    and [getattr(t, "id", None) for t in node.targets] == ["CHECKS"] for row in node.value.elts)
        self.assertTrue(roles)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings | roles:
                if not (lo <= node.lineno <= hi) and node.value in names:
                    found.append((node.lineno, node.value))
        self.assertEqual(found, [])
        # every frozen persist CSV column the tool reads is in the header file
        header = (TOOLS / "persist-csv-header.txt").read_text().strip().split(",")
        for k in ("c_ts", "c_disk_wr", "c_vma", "c_rr", "c_size", "c_wr_ios", "c_wr_ticks", "c_flush_ios", "c_flush_ticks"):
            self.assertIn(mod.F[k], header)

    def test_self_check_refuses_to_write_under_results(self):
        p = subprocess.run([sys.executable, str(TOOL), "--self-check", "--results-root", str(self.tmp / "results"),
                            "--out-dir", str(self.tmp / "results" / "x")], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("never writes under", p.stderr)


class ArmWindowToolsTests(unittest.TestCase):
    """block-rate.py and propose-latency.py: an arm's window starts at `ready`; old manifests read as before."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="arm-windows-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def manifest(self, ready=None, marks=None):
        a = {"name": "a1", "begin": "2026-10-06T06:00:00Z", "end": "2026-10-06T06:15:00Z", "nodes": {}}
        if ready:
            a["ready"] = ready
        if marks:
            a["marks"] = marks
        m = json.loads((TESTS / "fixtures" / "analysis" / "run" / "manifest.json").read_text())
        m["param_arms"] = [a]
        p = self.tmp / ("m-%d.json" % len(list(self.tmp.glob("m-*.json"))))
        p.write_text(json.dumps(m))
        return p

    def run_tool(self, tool, *args):
        p = subprocess.run([sys.executable, str(TOOLS / tool)] + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_block_rate_arm_from_ready_and_marks(self):
        run = str(TESTS / "fixtures" / "analysis" / "run")
        old = json.loads(self.run_tool("block-rate.py", "--run", run, "--windows", str(self.manifest()), "--format", "json"))
        same = json.loads(self.run_tool("block-rate.py", "--run", run, "--windows",
                                        str(self.manifest(ready="2026-10-06T06:00:00Z")), "--format", "json"))
        self.assertEqual(old, same)
        new = json.loads(self.run_tool("block-rate.py", "--run", run, "--format", "json", "--windows", str(self.manifest(
            ready="2026-10-06T06:05:00Z", marks=[{"label": "idle", "begin": "2026-10-06T06:01:00Z", "end": "2026-10-06T06:04:00Z"}]))))
        w = dict((x["name"], x) for x in new["windows"])
        self.assertEqual((w["arm a1"]["start"], w["arm a1"]["secs"]), ("2026-10-06T06:05:00Z", 600))
        self.assertEqual((w["mark a1/idle"]["start"], w["mark a1/idle"]["secs"]), ("2026-10-06T06:01:00Z", 180))
        self.assertEqual(w["arm a1"]["rows"][0]["blocks"], 10)      # blocks at T0 + 60 n, n = 5..14

    def test_propose_latency_arm_from_ready(self):
        lines = []
        for r in range(1, 41):
            ms = 1791266400000 + r * 20000
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + ".%03d000000Z" % (ms % 1000)
            lines.append('ts=%s level=info message="header proposed" round=%d epoch=0' % (ts, r))
        logs = self.tmp / "logs"
        logs.mkdir()
        (logs / "bench-validator-01-unit-stdout.log.gz").write_bytes(gzip.compress(("\n".join(lines) + "\n").encode()))
        old = self.run_tool("propose-latency.py", "--logs", str(logs), "--windows", str(self.manifest()))
        same = self.run_tool("propose-latency.py", "--logs", str(logs), "--windows",
                             str(self.manifest(ready="2026-10-06T06:00:00Z")))
        self.assertEqual(old, same)
        new = self.run_tool("propose-latency.py", "--logs", str(logs), "--windows",
                            str(self.manifest(ready="2026-10-06T06:10:00Z")))
        self.assertIn("## arm a1: 2026-10-06T06:10:00Z → 2026-10-06T06:15:00Z (300 s)", new)
        self.assertIn("## arm a1: 2026-10-06T06:00:00Z → 2026-10-06T06:15:00Z (900 s)", old)


if __name__ == "__main__":
    unittest.main()
