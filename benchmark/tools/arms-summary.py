#!/usr/bin/env python3
"""Per-arm summary of a bench run: one row per arm and blast type, with its window and drift correction.

Usage:
  arms-summary.py --run-dir results/<run> [--out-dir DIR] [--prefiltered DIR] [--cache-dir DIR]
                  [--types T[,T...]] [--drift-axis chain-mtx|wall-min] [--no-stages] [--jobs N]
  arms-summary.py --self-check [--results-root DIR] [--out-dir DIR] [--no-stages] [--jobs N]

Writes <out-dir>/arms.md and <out-dir>/arms.json (default out-dir: <run-dir>/analysis).

Rows. An arm is a manifest param_arms[] entry; its window runs from `ready` (else `begin`) to `end`.
A run without param_arms[] (bench 5 and older) is one implicit arm, `implicit`, over the whole run.
Each blast (manifest blasts[], plus the main blasters/ directory, whose index is blast.run_index) is
one row, under its blasts[].arm or else the arm in force when its window starts; each arm's
marks[] (the idle windows) are rows of type I. A blast's window is the span in which every one of
its generators was in its mixed phase (the blasters' own run.phases), else its recorded real mixed
phase, clipped to the arm's window and cut at the first chaos action inside it. Blasts whose rc is
not 0 are listed, not measured. The type is the first row of TYPES that matches the blast.

Columns (each "n/a (missing: <what>)" when its input is absent; never a silent zero):
  chain tx/s     sum of tx_count over the blocks timestamped in the window (every generator's block
                 table, de-duplicated by number) / seconds
  landed tx/s    the blast's generators' own landings per second (series.per_second own_tx)
  land, seen     p50/p95 seconds, the generators' pooled histograms (report/kpis.py pooled_latency:
                 mixed-phase submissions of the whole blast, not cut to the window)
  engine         per node, from the node log: execute and persist us/tx ("output executed"), commit
                 us/tx and ms per output ("persisted output"), task us/tx ("output execution task
                 finished" joined on consensus_number); the fleet value is the validators' median
  amplification  per node: persist CSV disk_wr_bytes_total delta between the first and the last 30-s
                 sample inside the window / ((page_newly + page_cow) x 4096) summed over the
                 "persisted output" lines between those two samples; fleet = median of the nodes
  rr / vma       the last 300-s persist sample in the window: mdbx_dat_rr_bytes / mdbx_dat_vma_bytes
  certification  per validator, tools/cert-rate.py (imported, unmodified) over the same log files:
                 own headers certified (quorum / proposed) and own certificates committed
  landings       sampled landings rows (1 in run.args.landings_sample) of the mixed phase with
                 seen_ms - submit_ms >= 300 s; resends = totals.resends summed over the generators
                 (total = transient + other + gap_txs + resign_nonce + resign_fee);
                 late = run.tail_scan.landed_late summed; late_secs = max of manifest blasters[]
  silent         the longest run of seconds in the window in which a generator made no send call
                 (series.send_per_second: submitted + resent + resigned == 0), max over generators
  stages         tools/stage-latency.py (imported) with the rows as its windows: chain seen p50/p95
                 and the S10 / S11 / S12 p50
  drift          inside each row: commit s/output = a + b x (txs/1000) + c x minutes since the window
                 start, least squares over the validators' whole minutes (I-3's model: per validator and
                 minute, the mean commit and txs per output; b is dropped when the output size never
                 varies). Across arms: the
                 first and the last control arm (every switch at its default) with the same blast type
                 give a slope of commit us/tx and ms/output along the drift axis (cumulative chain
                 transactions, in millions, at the window's midpoint; or wall minutes); every row of
                 that type gets its commit cost raw and corrected to the first control's position.
                 When the commit us/tx moved more than 15 % between the two controls, only adjacent
                 arms are compared (the flag is in the header and in the drift block).
  verdict        the CHECKS rows that apply to the arm's role (from the topic of the switches it
                 turned on, switches.tsv) and the row's type: "<threshold>: <value> met|not met", or
                 n/a with the missing input. No other judgement.

Logs. Per node the files are stage-latency.py's choice ({node}-unit-stdout*.log*, else every
{node}-*.log* but stderr). They are read from --prefiltered (default benchmark/work/prefilter/<run>/,
the teardown's grep pass) when that directory has the node's files and tools/log-shapes.txt holds
every literal this tool, cert-rate.py and stage-latency.py match; otherwise from the run's logs/,
streamed once through `gzip -dc | grep -F` (python gzip when those are missing) into --cache-dir
(default benchmark/work/arms-summary/<run>/), which later runs reuse.

--self-check runs on bench 5 (results/r20261107-1504, read-only; output under
benchmark/work/bench6-scratch/H7b/self-check unless --out-dir) with --types M4,M16 and compares the
two windows and chain tx/s with the I-3 recut (600 x 4: 16:57:31-17:02:55, 3,868.5 tx/s; 600 x 16
to the kill: 17:41:01-17:54:44, 3,466.2 tx/s) and checks every bench-6-only column is n/a.

Exit status: 0 = written (self-check: every figure matched); 1 = bad arguments or unreadable
input; 2 = no row; 3 = self-check mismatch. Stdlib only (plus the sibling tools it imports).
"""
import argparse
import bisect
import collections
import concurrent.futures
import csv
import datetime
import fnmatch
import gzip
import importlib.util
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

# ---- FIELDS (begin): every name this tool reads from another writer, spelled once. A rename is a one-line edit.
F = {
    # node log lines (message text) and their fields; the page_* and proc_write_bytes fields are U3's (contract, FROZEN)
    "msg_persisted": "persisted output", "msg_executed": "output executed",
    "msg_task": "output execution task finished", "msg_vote": "vote path timing",
    "lit_tracker": "Failed to track spawned task",
    "f_epoch": "epoch", "f_cn": "consensus_number", "f_txs": "txs", "f_commit_ms": "commit_ms",
    "f_execute_ms": "execute_ms", "f_persist_ms": "persist_ms", "f_task_ms": "task_ms",
    "f_newly": "page_newly", "f_cow": "page_cow", "f_spill": "page_spill", "f_unspill": "page_unspill",
    "f_prefault": "page_prefault", "f_wops": "page_wops", "f_msync": "page_msync", "f_proc_write": "proc_write_bytes",
    "f_author": "author", "f_round": "round", "f_outcome": "outcome", "f_lock_ms": "lock_ms", "v_behind": "behind",
    # persist CSV (benchmark/tools/persist-csv-header.txt)
    "c_ts": "ts_unix", "c_disk_wr": "disk_wr_bytes_total", "c_vma": "mdbx_dat_vma_bytes", "c_rr": "mdbx_dat_rr_bytes",
    "c_size": "mdbx_dat_size_bytes",
    # switches.tsv columns
    "s_key": "key", "s_default": "default", "s_topic": "topic",
    # manifest (benchmark/arms/MANIFEST-FIELDS.md)
    "m_arms": "param_arms", "m_name": "name", "m_begin": "begin", "m_ready": "ready", "m_end": "end",
    "m_switches": "switches", "m_host": "host", "m_step": "step", "m_nodes": "nodes", "m_evict": "evict-mdbx",
    "m_res_after": "resident_pages_after", "m_marks": "marks", "m_label": "label",
    "m_blasts": "blasts", "m_index": "index", "m_senders": "senders", "m_window": "window", "m_chaos": "chaos",
    "m_arm": "arm", "m_phases": "phases", "m_planned": "phases_planned", "m_rc": "rc",
    "m_start": "start", "m_ts": "ts", "m_action": "action", "m_node": "node", "m_blasters": "blasters",
    "m_late": "late_secs", "m_blast": "blast", "m_run_index": "run_index", "m_instances": "instances",
    "m_role": "role", "m_run_id": "run_id", "v_validator": "validator", "v_observer": "observer",
    # blaster JSON (tn-blast/v2; send_per_second, resends: H9a; tail_scan: H9b)
    "b_schema": "schema", "b_run": "run", "b_start_unix": "start_unix", "b_end_unix": "end_unix",
    "b_args": "args", "b_senders": "senders", "b_window": "window", "b_duration": "duration_secs", "b_sample": "landings_sample", "b_label": "label",
    "b_blocks": "blocks", "b_columns": "columns", "b_rows": "rows", "b_number": "number", "b_timestamp": "timestamp",
    "b_tx_count": "tx_count", "b_series": "series", "b_ps_cols": "per_second_columns", "b_ps": "per_second",
    "b_ps_t0": "per_second_t0_unix", "b_own_tx": "own_tx", "b_send_cols": "send_per_second_columns",
    "b_send": "send_per_second", "b_send_t0": "send_per_second_t0_unix", "b_s": "s", "b_submitted": "submitted",
    "b_resent": "resent", "b_resigned": "resigned", "b_totals": "totals", "b_resends": "resends",
    "b_r_transient": "transient", "b_r_other": "other", "b_r_gap_txs": "gap_txs", "b_r_nonce": "resign_nonce",
    "b_r_fee": "resign_fee", "b_tail": "tail_scan", "b_landed_late": "landed_late", "b_unlanded_after": "unlanded_after",
    "v_mixed": "mixed",
    # landings rows (landings-<label>.ndjson.gz)
    "l_submit": "submit_ms", "l_seen": "seen_ms", "l_phase": "phase",
    # report/kpis.py pooled_latency, tools/cert-rate.py and tools/stage-latency.py outputs
    "k_ts": "ts_ms", "k_seen": "seen_ms", "k_p50": "p50", "k_p95": "p95",
    "r_windows": "windows", "r_nodes": "nodes", "r_rate": "rate_pct", "r_not_committed": "not_committed_pct",
    "r_proposed": "proposed",
    "t_headline": "headline", "t_pooled": "pooled", "t_seen50": "seen_p50_s", "t_seen95": "seen_p95_s",
    "t_p50ms": "p50_ms", "t_count": "count", "t_wstart": "start_unix", "t_wend": "end_unix",
}
# switches.tsv topic -> the arm role whose "must show" thresholds apply when an arm turns that topic on.
TOPIC_ROLES = {
    "mdbx-advice": "persist", "quorum-exec-block": "vote", "voter-lock": "vote", "sealed-keep": "pool",
    "digest-dedupe": "pool", "recovery-pool": "pool", "tracker-drain": "pool", "pipelined-persist": "pipe",
    "inflight-bound": "bound", "parent-grace": "grace",
}
HOST_ROLE = "persist"                                        # an arm that adds a host step (evict, read-ahead)
GRACE_NODES = ("bench-validator-02", "bench-validator-06")   # the plan's v02 / v06 (London, Netherlands)
CERT_RATE, STAGE_LATENCY, KPIS = "cert-rate.py", "stage-latency.py", "kpis.py"
LOG_SHAPES = "log-shapes.txt"
# ---- FIELDS (end)

# Blast types, first match wins: (type, senders, window, minimum planned mixed seconds or None).
TYPES = (("L", 8, 16, None), ("M4", 600, 4, None), ("M16", 600, 16, 400), ("M16s", 600, 16, 0))
IDLE_TYPE = "I"
IMPLICIT_ARM = "implicit"
CONTROL, DRIFT = "control", "drift"
# The plan's "must show" thresholds (W4 run-1 table): (role, label, row types or None for every type,
# metric key of the row, operator, threshold). A metric that is n/a makes the check n/a.
CHECKS = (
    (CONTROL, "amplification > 1.2 (bench-5 signature)", ("M16",), "amp_fleet_median", ">", 1.2),
    (CONTROL, "min own-header certification < 98 % (starved validators)", ("M16",), "cert_min_pct", "<", 98.0),
    (CONTROL, "landings >= 300 s > 0 (the cliff)", ("M16",), "landings_ge300", ">", 0),
    ("persist", "amplification <= 1.2", ("M16",), "amp_fleet_median", "<=", 1.2),
    ("persist", "resident pages after eviction = 0", None, "evict_resident_after_max", "==", 0),
    ("persist", "rr bytes / VMA bytes >= 0.99 on every node", ("M16",), "rr_vma_min", ">=", 0.99),
    ("vote", "own-header certification >= 98 % on every validator", ("L", "M16"), "cert_min_pct", ">=", 98.0),
    ("vote", "behind refusals per header <= f", ("L", "M16"), "behind_per_header_max_minus_f", "<=", 0),
    ("vote", "lock_ms p95 < 1100", ("L", "M16"), "vote_lock_p95_ms", "<", 1100.0),
    ("vote", "no generator silent > 30 s", ("L", "M16"), "gen_silent_max_s", "<=", 30),
    ("pool", "landings >= 300 s = 0", ("M16",), "landings_ge300", "==", 0),
    ("pool", "task-tracker errors = 0", ("M16",), "tracker_errors", "==", 0),
    ("bound", "chain tx/s >= the previous arm's (same type)", ("M16",), "chain_txps_vs_prev", ">=", 0.0),
    ("grace", "own certificates committed >= 90 %% on %s" % " and ".join(GRACE_NODES), (IDLE_TYPE, "L"),
     "grace_nodes_committed_min_pct", ">=", 90.0),
    (DRIFT, "commit us/tx moved <= 15 % against the first control", ("M16",), "drift_moved_pct_abs", "<=", 15.0),
)
LANDING_CLIFF_MS = 300000
DRIFT_LIMIT = 0.15
PAGE = 4096
RECUT = (("M4", "2026-11-07T16:57:31Z", "2026-11-07T17:02:55Z", 3868.5),
         ("M16", "2026-11-07T17:41:01Z", "2026-11-07T17:54:44Z", 3466.2))
SELF_CHECK_RUN = "r20261107-1504"
# Columns that only a bench-6 run can fill; the self-check expects each of them n/a on bench 5.
BENCH6_ONLY = ("amp_fleet_median", "rr_vma_min", "evict_resident_after_max", "resends_total", "late_secs_max",
               "gen_silent_max_s", "tail_landed_late", "switch_set")

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
TS_RE = re.compile(r"^(?:ts=)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?")
MSG_RE = re.compile(r'message="([^"]*)"')
KV_RE = re.compile(r'(?:^|\s)([A-Za-z_]\w*)=("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\S+)')
NODE_FILE_RE = re.compile(r"^(bench-(?:validator|observer)-\d+)-")
BLAST_DIR_RE = re.compile(r"^blast-(\d+)-")


def na(what):
    return "n/a (missing: %s)" % what


def is_na(v):
    return isinstance(v, str) and v.startswith("n/a")


def iso(t):
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    m = TS_RE.match(str(text).strip())
    if not m:
        raise ValueError("not an ISO-8601 UTC time: %r" % text)
    y, mo, d, h, mi, s, frac = m.groups()
    base = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=datetime.timezone.utc)
    return base.timestamp() + (float(frac) if frac else 0.0)


def line_ts(line):
    m = TS_RE.match(line)
    if not m:
        return None
    y, mo, d, h, mi, s, frac = m.groups()
    base = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=datetime.timezone.utc)
    return base.timestamp() + (float(frac) if frac else 0.0)


def num(v):
    if v is None:
        return None
    try:
        return float(v) if ("." in v or "e" in v) else int(v)
    except (TypeError, ValueError):
        return None


def r1(x):
    return None if x is None else round(x, 1)


def median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def pctl(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(-(-q * len(xs) // 1)) - 1))     # nearest rank
    return xs[k]


def load_tool(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def open_bin(path):
    with open(path, "rb") as fh:
        magic = fh.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")


# ---------------------------------------------------------------- inputs: manifest, blasts, arms

def read_json(path):
    with open(path) as fh:
        return json.load(fh)


def switch_table(path):
    """[(key, default, topic)] from switches.tsv, or [] when it is unreadable."""
    try:
        with open(path) as fh:
            return [(r[F["s_key"]], r[F["s_default"]], r[F["s_topic"]]) for r in csv.DictReader(fh, delimiter="\t")]
    except (OSError, KeyError):
        return []


def arm_list(manifest, switches):
    """[{name, from, to, switches, host, marks, role, control}] in manifest order; one implicit arm without param_arms."""
    arms = []
    defaults = dict((k, d) for k, d, _ in switches)
    topic = dict((k, t) for k, _, t in switches)
    prev = dict(defaults)
    for a in manifest.get(F["m_arms"]) or []:
        if not isinstance(a, dict):
            continue
        start = a.get(F["m_ready"]) or a.get(F["m_begin"]) or a.get(F["m_start"])
        if not start:
            continue
        sw = a.get(F["m_switches"])
        host = [h for h in (a.get(F["m_host"]) or []) if isinstance(h, dict)]
        roles = set()
        if isinstance(sw, dict):
            for k, v in sorted(sw.items()):
                if str(v) != str(prev.get(k, defaults.get(k))) and str(v) != str(defaults.get(k)):
                    role = TOPIC_ROLES.get(topic.get(k))
                    if role:
                        roles.add(role)
            control = bool(defaults) and all(str(sw.get(k, d)) == str(d) for k, d in defaults.items())
            prev = dict((k, str(v)) for k, v in sw.items())
        else:
            control = False
        if host and not roles and not control:
            roles.add(HOST_ROLE)
        arms.append({"arm_name": str(a.get(F["m_name"]) or "?"), "from": parse_iso(start),
                     "to": parse_iso(a[F["m_end"]]) if a.get(F["m_end"]) else float("inf"),
                     "switch_set": sw if isinstance(sw, dict) else None, "defaults": defaults, "host_steps": host,
                     "mark_list": [m for m in (a.get(F["m_marks"]) or []) if isinstance(m, dict)],
                     "roles": sorted(roles) or ([CONTROL] if control else []), "control": control})
    if not arms:
        arms.append({"arm_name": IMPLICIT_ARM, "from": float("-inf"), "to": float("inf"), "switch_set": None,
                     "defaults": defaults, "host_steps": [], "mark_list": [], "roles": [CONTROL], "control": True})
    controls = [a for a in arms if a["control"]]
    if len(controls) > 1:
        controls[-1]["roles"] = sorted(set(controls[-1]["roles"]) | {DRIFT})
    return arms


def load_docs(directory):
    out = []
    if not os.path.isdir(directory):
        return out
    for f in sorted(os.listdir(directory)):
        if f.endswith(".json"):
            try:
                d = read_json(os.path.join(directory, f))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and str(d.get(F["b_schema"], "")).startswith("tn-blast/"):
                out.append(d)
    return out


def doc_mixed(doc):
    for p in (doc.get(F["b_run"]) or {}).get(F["m_phases"]) or []:
        if p.get(F["m_name"]) == F["v_mixed"] and p.get(F["b_start_unix"]) is not None and p.get(F["b_end_unix"]) is not None:
            return float(p[F["b_start_unix"]]), float(p[F["b_end_unix"]])
    return None


def blast_groups(run_dir, manifest):
    """[{idx, dir, docs, entry, blast_manifest}] for blasters/ and every blast-<i>-<UTC>/blasters."""
    entries = dict((int(b[F["m_index"]]), b) for b in manifest.get(F["m_blasts"]) or []
                   if isinstance(b, dict) and b.get(F["m_index"]) is not None)
    top = manifest.get(F["m_blast"]) or {}
    groups = []
    for f in sorted(os.listdir(run_dir)):
        m = BLAST_DIR_RE.match(f)
        d = os.path.join(run_dir, f, F["m_blasters"])
        if m and os.path.isdir(d):
            mp = os.path.join(run_dir, f, "manifest.json")
            groups.append({"idx": int(m.group(1)), "dir": d, "bm": read_json(mp) if os.path.isfile(mp) else {}})
    main_idx = top.get(F["m_run_index"])
    if main_idx is None:
        rest = [i for i in entries if i not in {g["idx"] for g in groups}]
        main_idx = rest[0] if len(rest) == 1 else None
    groups.append({"idx": main_idx, "dir": os.path.join(run_dir, F["m_blasters"]), "bm": manifest})
    out = []
    for g in groups:
        g["docs"] = load_docs(g["dir"])
        entry = dict(entries.get(g["idx"]) or {})
        if not entry and g["docs"]:
            args = (g["docs"][0].get(F["b_run"]) or {}).get(F["b_args"]) or {}
            entry = {F["m_senders"]: args.get(F["b_senders"]), F["m_window"]: args.get(F["b_window"]),
                     F["m_chaos"]: top.get(F["m_chaos"]) if g["idx"] == top.get(F["m_run_index"]) else None}
        g["entry"] = entry
        if g["docs"] or entry:
            out.append(g)
    return out


def blast_type(entry, docs, mixed_secs):
    s, w = entry.get(F["m_senders"]), entry.get(F["m_window"]) or 16
    planned = None
    for d in docs:
        planned = ((d.get(F["b_run"]) or {}).get(F["b_args"]) or {}).get(F["b_duration"])
        if planned is not None:
            break
    length = planned if planned is not None else mixed_secs
    for name, ts, tw, min_mixed in TYPES:
        if str(s) == str(ts) and str(w) == str(tw) and (min_mixed is None or (length or 0) >= min_mixed):
            return name
    return "%sx%s" % (s, w)


def entry_real_mixed(entry):
    if not entry.get(F["m_planned"]):
        return None
    for p in entry.get(F["m_phases"]) or []:
        if isinstance(p, dict) and p.get(F["m_name"]) == F["v_mixed"] and p.get(F["m_start"]) and p.get(F["m_end"]):
            return parse_iso(p[F["m_start"]]), parse_iso(p[F["m_end"]])
    return None


def chaos_times(manifest):
    out = []
    events = manifest.get(F["m_chaos"])
    for c in events if isinstance(events, list) else []:
        if isinstance(c, dict) and c.get(F["m_ts"]):
            out.append((parse_iso(c[F["m_ts"]]), "%s %s" % (c.get(F["m_action"]) or "?", c.get(F["m_node"]) or "")))
    return sorted(out)


def build_rows(run_dir, manifest, arms, types):
    rows, skipped = [], []
    chaos = chaos_times(manifest)

    def arm_at(t, name=None):
        if name is not None:
            for a in arms:
                if a["arm_name"] == name:
                    return a
        cands = [a for a in arms if a["from"] <= t]
        return cands[-1] if cands else arms[0]

    for g in blast_groups(run_dir, manifest):
        e, docs = g["entry"], g["docs"]
        label = "blast index %s" % g["idx"]
        rc = e.get(F["m_rc"])
        if rc not in (None, 0):
            skipped.append("%s: rc %s, not measured" % (label, rc))
            continue
        spans = [s for s in (doc_mixed(d) for d in docs) if s]
        if spans:
            a, b, basis = max(s[0] for s in spans), min(s[1] for s in spans), "every generator in mixed (%d)" % len(spans)
        elif entry_real_mixed(e):
            (a, b), basis = entry_real_mixed(e), "blasts[].phases mixed (real)"
        else:
            skipped.append("%s: %s" % (label, na("generator files and a real mixed phase")))
            continue
        arm = arm_at(a, e.get(F["m_arm"]))
        a, b = max(a, arm["from"]), min(b, arm["to"])
        cut = next(((t, what) for t, what in chaos if a < t < b), None)
        if cut:
            b = cut[0]
            basis += ", cut at chaos %s" % cut[1]
        if b <= a:
            skipped.append("%s: empty window after clipping to arm %s" % (label, arm["arm_name"]))
            continue
        typ = blast_type(e, docs, b - a)
        rows.append({"arm_rec": arm, "blast_type": typ, "blast_idx": g["idx"], "from": a, "to": b, "basis": basis,
                     "docs": docs, "group": g})
    for arm in arms:
        for mk in arm["mark_list"]:
            if mk.get(F["m_begin"]) and mk.get(F["m_end"]):
                rows.append({"arm_rec": arm, "blast_type": IDLE_TYPE, "blast_idx": None, "from": parse_iso(mk[F["m_begin"]]),
                             "to": parse_iso(mk[F["m_end"]]), "basis": "mark %s" % mk.get(F["m_label"]), "docs": [],
                             "group": None})
    if types:
        kept = [r for r in rows if r["blast_type"] in types]
        skipped += ["%s/%s: not in --types" % (r["arm_rec"]["arm_name"], r["blast_type"]) for r in rows if r not in kept]
        rows = kept
    rows.sort(key=lambda r: r["from"])
    seen = collections.Counter()
    for r in rows:
        rid = "%s/%s" % (r["arm_rec"]["arm_name"], r["blast_type"])
        seen[rid] += 1
        r["row_id"] = rid if seen[rid] == 1 else "%s-%d" % (rid, seen[rid])
    return rows, skipped


# ---------------------------------------------------------------- inputs: logs

def node_names(manifest, logs_dir):
    names = []
    for i in manifest.get(F["m_instances"]) or []:
        if isinstance(i, dict) and i.get(F["m_role"]) in (F["v_validator"], F["v_observer"]) and i.get(F["m_name"]):
            names.append(i[F["m_name"]])
    if not names and os.path.isdir(logs_dir):
        names = sorted({m.group(1) for m in (NODE_FILE_RE.match(f) for f in os.listdir(logs_dir)) if m})
    return names


def literals(sl, cr):
    """Every substring a line must hold for this tool, stage-latency.py or cert-rate.py to read it."""
    lits = [F["msg_persisted"], F["msg_executed"], F["msg_task"], F["msg_vote"], F["lit_tracker"]]
    lits += list(sl.MSGS)
    for part in cr.EVENT_RE.pattern.split("|"):
        if re.search(r"[\\.^$*+?{}\[\]()]", part):
            raise ValueError("cert-rate.py EVENT_RE is no longer a list of literals: %r" % part)
        lits.append(part)
    return sorted(set(lits))


def prefilter_usable(prefiltered, lits):
    """None when <prefiltered> holds every literal per tools/log-shapes.txt, else what is missing."""
    if not prefiltered or not os.path.isdir(prefiltered):
        return "prefiltered directory %s" % (prefiltered or "-")
    try:
        with open(os.path.join(HERE, LOG_SHAPES)) as fh:
            shapes = [l.rstrip("\n") for l in fh if l.strip() and not l.startswith("#")]
    except OSError:
        return "tools/%s" % LOG_SHAPES
    lacking = [x for x in lits if not any(s in x for s in shapes)]
    return ("%s lacks %s" % (LOG_SHAPES, ", ".join(lacking))) if lacking else None


def filter_one(src, dst, lits):
    """Stream <src> (gzip or plain) through a fixed-string grep into <dst> (gzip); reuse a finished <dst>."""
    side = os.path.join(os.path.dirname(dst), ".filtered-from", os.path.basename(dst))   # out of every log glob
    st = os.stat(src)
    want = "%s %d %d\n" % (os.path.realpath(src), st.st_size, st.st_mtime_ns) + "\n".join(lits) + "\n"
    if os.path.isfile(dst) and os.path.isfile(side):
        with open(side) as fh:
            if fh.read() == want:
                return dst
    tmp = dst + ".part"
    pat = tmp + ".lits"
    with open(pat, "w") as fh:
        fh.write("\n".join(lits) + "\n")
    try:
        with open(tmp, "wb") as out:
            unz = subprocess.Popen(["gzip", "-dcf", src], stdout=subprocess.PIPE)
            grep = subprocess.Popen(["grep", "-F", "-f", pat], stdin=unz.stdout, stdout=subprocess.PIPE)
            unz.stdout.close()
            zp = subprocess.Popen(["gzip", "-1"], stdin=grep.stdout, stdout=out)
            grep.stdout.close()
            rcs = (zp.wait(), grep.wait(), unz.wait())
        if rcs[0] != 0 or rcs[1] not in (0, 1) or rcs[2] != 0:
            raise OSError("filter of %s ended rc %s" % (src, rcs))
    except FileNotFoundError:                                   # no gzip/grep binaries: python, still streamed
        enc = [x.encode() for x in lits]
        with open_bin(src) as fin, gzip.open(tmp, "wb", compresslevel=1) as fout:
            for raw in fin:
                if any(x in raw for x in enc):
                    fout.write(raw)
    finally:
        if os.path.exists(pat):
            os.remove(pat)
    os.replace(tmp, dst)
    os.makedirs(os.path.dirname(side), exist_ok=True)
    with open(side, "w") as fh:
        fh.write(want)
    return dst


class NodeData(object):
    """One node's engine, vote and tracker events inside any row window."""

    def __init__(self, name, windows):
        self.name = name
        merged = []
        for a, b in sorted(windows):            # the union of the row windows, as disjoint spans
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.spans = merged
        self.starts = [w[0] for w in merged]
        self.executed, self.persisted, self.votes, self.tracker = [], [], [], []
        self.task = {}
        self.page_fields = False
        self.files = []
        self._seen = set()

    def inside(self, t):
        i = bisect.bisect_right(self.starts, t) - 1
        return i >= 0 and t < self.spans[i][1]

    def read(self, path, dedupe):
        want = (F["msg_persisted"], F["msg_executed"], F["msg_task"], F["msg_vote"])
        with open_bin(path) as fh:
            for raw in fh:
                line = raw.decode("utf-8", "replace")
                tracker = F["lit_tracker"] in line
                m = MSG_RE.search(line)
                msg = m.group(1) if m else None
                if msg not in want and not tracker:
                    continue
                t = line_ts(line)
                if t is None or not self.inside(t):
                    continue
                if dedupe:
                    h = hash(line)
                    if h in self._seen:
                        continue
                    self._seen.add(h)
                if tracker:
                    self.tracker.append(t)
                    continue
                f = {}
                for k, v in KV_RE.findall(line[m.end():]):
                    f.setdefault(k, v)
                if msg == F["msg_executed"]:
                    self.executed.append((t, num(f.get(F["f_txs"])), num(f.get(F["f_execute_ms"])),
                                          num(f.get(F["f_persist_ms"])), num(f.get(F["f_cn"]))))
                elif msg == F["msg_persisted"]:
                    pages = dict((k, num(f.get(F[k]))) for k in ("f_newly", "f_cow", "f_spill", "f_unspill",
                                                                 "f_prefault", "f_wops", "f_msync", "f_proc_write"))
                    if pages["f_newly"] is not None and pages["f_cow"] is not None:
                        self.page_fields = True
                    self.persisted.append((t, num(f.get(F["f_txs"])), num(f.get(F["f_commit_ms"])), pages))
                elif msg == F["msg_task"]:
                    self.task.setdefault(num(f.get(F["f_cn"])), num(f.get(F["f_task_ms"])))
                elif msg == F["msg_vote"]:
                    self.votes.append((t, f.get(F["f_author"]), num(f.get(F["f_epoch"])), num(f.get(F["f_round"])),
                                       f.get(F["f_outcome"]), num(f.get(F["f_lock_ms"]))))
        self.files.append(os.path.basename(path))

    def finish(self):
        for xs in (self.executed, self.persisted, self.votes, self.tracker):
            xs.sort(key=lambda x: x[0] if isinstance(x, tuple) else x)
        self._seen = set()


def between(xs, a, b, key=lambda x: x[0]):
    return [x for x in xs if a <= key(x) < b]


# ---------------------------------------------------------------- inputs: persist CSV, blasters

def persist_rows(path):
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            row = {}
            for k in ("c_ts", "c_disk_wr", "c_vma", "c_rr", "c_size"):
                v = (r.get(F[k]) or "").strip()
                row[k] = float(v) if v else None
            if row["c_ts"] is not None:
                rows.append(row)
    rows.sort(key=lambda r: r["c_ts"])
    return rows


def block_table(docs_lists):
    """Sorted [(timestamp, tx_count)] over every generator's blocks, de-duplicated by number."""
    by_num = {}
    for docs in docs_lists:
        for d in docs:
            b = d.get(F["b_blocks"]) or {}
            cols = list(b.get(F["b_columns"]) or [])
            if not all(c in cols for c in (F["b_number"], F["b_timestamp"], F["b_tx_count"])):
                continue
            i_n, i_t, i_x = cols.index(F["b_number"]), cols.index(F["b_timestamp"]), cols.index(F["b_tx_count"])
            for r in b.get(F["b_rows"]) or []:
                by_num.setdefault(r[i_n], (float(r[i_t]), int(r[i_x] or 0)))
    return sorted(by_num.values())


def series(doc, cols_key, rows_key, t0_key):
    s = doc.get(F["b_series"]) or {}
    cols, rows = s.get(F[cols_key]), s.get(F[rows_key])
    if not cols or rows is None or s.get(F[t0_key]) is None:
        return None
    return list(cols), rows, float(s[F[t0_key]])


def landings(group, docs):
    """(count >= 300 s, sampled mixed landings, sample rate) over the blast's landings files, or None."""
    total, cliff, rate = 0, 0, None
    found = False
    for d in docs:
        args = (d.get(F["b_run"]) or {}).get(F["b_args"]) or {}
        rate = args.get(F["b_sample"], rate)
        p = os.path.join(group["dir"], "landings-%s.ndjson.gz" % ((d.get(F["b_run"]) or {}).get(F["b_label"]) or "?"))
        if not os.path.isfile(p):
            continue
        found = True
        with open_bin(p) as fh:
            for raw in fh:
                try:
                    x = json.loads(raw)
                except ValueError:
                    continue
                if x.get(F["l_phase"]) != F["v_mixed"] or x.get(F["l_seen"]) is None or x.get(F["l_submit"]) is None:
                    continue
                total += 1
                if x[F["l_seen"]] - x[F["l_submit"]] >= LANDING_CLIFF_MS:
                    cliff += 1
    return (cliff, total, rate) if found else None


# ---------------------------------------------------------------- measurements

def lsq(X, y):
    """Least squares by the normal equations: (coefficients, r2), or None when singular or too few points."""
    n = len(X[0]) if X else 0
    if len(X) <= n:
        return None
    A = [[sum(r[i] * r[j] for r in X) for j in range(n)] + [sum(r[i] * v for r, v in zip(X, y))] for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda k: abs(A[k][i]))
        A[i], A[p] = A[p], A[i]
        if abs(A[i][i]) < 1e-9 * max(1.0, max(abs(u) for u in A[i][:n])):
            return None
        for k in range(n):
            if k != i:
                f = A[k][i] / A[i][i]
                A[k] = [u - f * v for u, v in zip(A[k], A[i])]
    co = [A[i][n] / A[i][i] for i in range(n)]
    ybar = sum(y) / len(y)
    ss = sum((v - ybar) ** 2 for v in y)
    res = sum((v - sum(c * x for c, x in zip(co, r))) ** 2 for v, r in zip(y, X))
    return co, ((1 - res / ss) if ss else None)


def lsq3(pts):
    """commit = a + b x1 + c x2 over [(commit, x1, x2)]: (a, b, c, r2); b is None when x1 never varies
    (then c comes from commit = a + c x2); None when even that is singular."""
    y = [p[0] for p in pts]
    full = lsq([[1.0, x1, x2] for _, x1, x2 in pts], y)
    if full:
        return full[0][0], full[0][1], full[0][2], full[1]
    two = lsq([[1.0, x2] for _, _, x2 in pts], y)
    return (two[0][0], None, two[0][1], two[1]) if two else None


def engine_row(nd, a, b):
    ex = [e for e in between(nd.executed, a, b) if e[1] is not None]
    ps = [p for p in between(nd.persisted, a, b) if p[1] is not None]
    out = {}
    txs = sum(e[1] for e in ex)
    ptx = sum(p[1] for p in ps)
    if not txs:
        for k in ("exec_txps", "execute_us_tx", "persist_us_tx", "task_us_tx"):
            out[k] = na("'%s' lines in the window" % F["msg_executed"])
    else:
        out["exec_txps"] = r1(txs / (b - a))
        out["execute_us_tx"] = r1(sum(e[2] or 0 for e in ex) * 1000.0 / txs)
        out["persist_us_tx"] = r1(sum(e[3] or 0 for e in ex) * 1000.0 / txs)
        tasks = [nd.task.get(e[4]) for e in ex]
        out["task_us_tx"] = (r1(sum(tasks) * 1000.0 / txs) if all(x is not None for x in tasks)
                             else na("'%s' for every output" % F["msg_task"]))
    if not ptx:
        for k in ("commit_us_tx", "commit_ms_output", "txs_per_output"):
            out[k] = na("'%s' lines in the window" % F["msg_persisted"])
    else:
        out["commit_us_tx"] = r1(sum(p[2] or 0 for p in ps) * 1000.0 / ptx)
        out["commit_ms_output"] = r1(sum(p[2] or 0 for p in ps) / float(len(ps)))
        out["txs_per_output"] = round(ptx / float(len(ps)))
    return out


def amp_row(nd, csv_rows, a, b):
    """(amplification dict, rr dict) of one node in [a, b)."""
    if csv_rows is None:
        miss = na("persist/%s.csv" % nd.name)
        return {"amp": miss}, {"rr_vma": miss}
    inside = [r for r in csv_rows if a <= r["c_ts"] <= b and r["c_disk_wr"] is not None]
    amp = {}
    if len(inside) < 2:
        amp["amp"] = na("two persist samples with %s in the window" % F["c_disk_wr"])
    elif not nd.page_fields:
        amp["amp"] = na("%s / %s on '%s'" % (F["f_newly"], F["f_cow"], F["msg_persisted"]))
    else:
        t1, t2 = inside[0]["c_ts"], inside[-1]["c_ts"]
        dev = inside[-1]["c_disk_wr"] - inside[0]["c_disk_wr"]
        ps = [p for p in nd.persisted if t1 < p[0] <= t2]
        pages = sum((p[3]["f_newly"] or 0) + (p[3]["f_cow"] or 0) for p in ps)
        if dev < 0:
            amp["amp"] = na("a monotonic %s (it went back)" % F["c_disk_wr"])
        elif not pages:
            amp["amp"] = na("page operations in '%s' between the samples" % F["msg_persisted"])
        else:
            amp["amp"] = round(dev / (pages * float(PAGE)), 3)
            amp["device_bytes"] = int(dev)
            amp["page_bytes"] = int(pages * PAGE)
            amp["proc_written_bytes"] = int(sum(p[3]["f_proc_write"] or 0 for p in ps))
            amp["samples"] = [iso(t1), iso(t2)]
            for k in ("f_spill", "f_unspill", "f_prefault", "f_wops", "f_msync"):
                amp[F[k]] = int(sum(p[3][k] or 0 for p in ps))
    rr = [r for r in csv_rows if a <= r["c_ts"] <= b and r["c_rr"] is not None and r["c_vma"]]
    if not rr:
        rrd = {"rr_vma": na("a 300-s persist sample with %s in the window" % F["c_rr"])}
    else:
        last = rr[-1]
        rrd = {"rr_vma": round(last["c_rr"] / last["c_vma"], 4), "rr_bytes": int(last["c_rr"]),
               "vma_bytes": int(last["c_vma"]), "dat_bytes": None if last["c_size"] is None else int(last["c_size"])}
    return amp, rrd


def commit_fit(nds, validators, a, b):
    """I-3's fit: per validator and whole minute of the window (the minute ending a + 60 k), the mean commit
    s per output and the mean txs per output of its persists, against k."""
    pts = []
    for n in validators:
        ps = [p for p in (nds[n].persisted if n in nds else []) if a <= p[0] < b and p[1] is not None and p[2] is not None]
        k = 1
        while a + 60 * k <= b:
            sel = [p for p in ps if a + 60 * (k - 1) <= p[0] < a + 60 * k]
            if sel and sum(p[1] for p in sel):
                pts.append((sum(p[2] for p in sel) / 1000.0 / len(sel), sum(p[1] for p in sel) / 1000.0 / len(sel), float(k)))
            k += 1
    fit = lsq3(pts)
    if not fit:
        return na("validator outputs with '%s' spread over the window (the fit is singular)" % F["msg_persisted"])
    return {"a_s": round(fit[0], 4), "b_s_per_1k_txs": None if fit[1] is None else round(fit[1], 4),
            "c_s_per_min": round(fit[2], 4),
            "r2": None if fit[3] is None else round(fit[3], 3), "n": len(pts)}


def vote_rows(nds, validators, a, b):
    out = {}
    votes = [v for n in validators if n in nds for v in between(nds[n].votes, a, b)]
    if not votes:
        miss = na("'%s' lines in the window" % F["msg_vote"])
        return {"vote_lock_p95_ms": miss, "behind_per_header_max": miss, "behind_per_header_max_minus_f": miss}
    locks = [v[5] for v in votes if v[5] is not None]
    out["vote_lock_p95_ms"] = pctl(locks, 0.95) if locks else na("%s on '%s'" % (F["f_lock_ms"], F["msg_vote"]))
    per = collections.defaultdict(set)                         # header -> the voters that refused it as behind
    for n in validators:
        for v in between(nds[n].votes, a, b) if n in nds else []:
            if v[4] == F["v_behind"]:
                per[(v[1], v[2], v[3])].add(n)
    f = (len(validators) - 1) // 3
    worst = max(len(x) for x in per.values()) if per else 0
    out["behind_per_header_max"] = worst
    out["behind_per_header_max_minus_f"] = worst - f
    return out


# ---------------------------------------------------------------- the report

def measure(run_dir, manifest, rows, nds, validators, persist_dir, cert_doc, stage_doc, blocks, axis):
    t_first = blocks[0][0] if blocks else None
    cum = []
    acc = 0
    for t, x in blocks:
        acc += x
        cum.append(acc)
    btimes = [t for t, _ in blocks]
    csv_cache = {}
    for name in nds:
        p = os.path.join(persist_dir, "%s.csv" % name)
        csv_cache[name] = persist_rows(p) if os.path.isfile(p) else None
    for r in rows:
        a, b = r["from"], r["to"]
        m = collections.OrderedDict()
        sw = r["arm_rec"]["switch_set"]
        m["switch_set"] = (",".join("%s=%s" % (k, v) for k, v in sorted(sw.items())
                                    if str(v) != str(r["arm_rec"]["defaults"].get(k))) or "all defaults") if sw else \
            na("param_arms[].%s" % F["m_switches"])
        i0, i1 = bisect.bisect_left(btimes, a), bisect.bisect_left(btimes, b)
        if r["docs"] or i1 > i0:
            m["chain_txps"] = r1(sum(x for _, x in blocks[i0:i1]) / (b - a)) if i1 > i0 else na("blocks in the window")
            m["chain_blocks"] = i1 - i0
        else:
            m["chain_txps"] = na("generator block tables")
        own = 0
        have = False
        for d in r["docs"]:
            s = series(d, "b_ps_cols", "b_ps", "b_ps_t0")
            if s and F["b_own_tx"] in s[0]:
                have = True
                io_ = s[0].index(F["b_own_tx"])
                i_s = s[0].index(F["b_s"]) if F["b_s"] in s[0] else 0
                own += sum(row[io_] for row in s[1] if a <= s[2] + row[i_s] < b)
        m["landed_txps"] = r1(own / (b - a)) if have else na("series.%s %s" % (F["b_ps"], F["b_own_tx"]))
        lat = pooled_latency(r["docs"])
        for k, src, q in (("land_p50_s", "k_ts", "k_p50"), ("land_p95_s", "k_ts", "k_p95"),
                          ("gen_seen_p50_s", "k_seen", "k_p50"), ("gen_seen_p95_s", "k_seen", "k_p95")):
            v = (lat.get(F[src]) or {}).get(F[q]) if isinstance(lat, dict) else None
            m[k] = round(v / 1000.0, 2) if isinstance(v, (int, float)) else (lat if is_na(lat) else na("generator latency histograms"))
        # engine, amplification, rr per node
        per_node = collections.OrderedDict()
        for n in sorted(nds):
            e = engine_row(nds[n], a, b)
            amp, rr = amp_row(nds[n], csv_cache.get(n), a, b)
            e.update(amp)
            e.update(rr)
            per_node[n] = e
        m["engine_by_node"] = per_node
        for k in ("exec_txps", "execute_us_tx", "persist_us_tx", "commit_us_tx", "commit_ms_output", "task_us_tx",
                  "txs_per_output"):
            vals = [per_node[n][k] for n in validators if n in per_node and not is_na(per_node[n][k])]
            m[k] = r1(median(vals)) if vals else (next((per_node[n][k] for n in validators if n in per_node), None)
                                                 or na("validator logs"))
        amps = [v["amp"] for v in per_node.values() if not is_na(v["amp"])]
        m["amp_fleet_median"] = round(median(amps), 3) if amps else next((v["amp"] for v in per_node.values()),
                                                                         na("node logs"))
        rrs = [v["rr_vma"] for v in per_node.values() if not is_na(v["rr_vma"])]
        m["rr_vma_min"] = min(rrs) if rrs else next((v["rr_vma"] for v in per_node.values()), na("node logs"))
        m["rr_vma_median"] = round(median(rrs), 4) if rrs else m["rr_vma_min"]
        ev = [res.get(F["m_res_after"]) for h in r["arm_rec"]["host_steps"] if h.get(F["m_step"]) == F["m_evict"]
              for res in (h.get(F["m_nodes"]) or {}).values() if isinstance(res, dict)]
        ev = [x for x in ev if isinstance(x, (int, float))]
        m["evict_resident_after_max"] = max(ev) if ev else na("param_arms[].%s %s results" % (F["m_host"], F["m_evict"]))
        m["commit_fit"] = commit_fit(nds, validators, a, b)
        # certification
        cw = (cert_doc or {}).get(r["row_id"])
        if cw:
            certs = collections.OrderedDict()
            for n in validators:
                c = cw.get(n)
                if c:
                    nc = c.get(F["r_not_committed"])
                    certs[n] = {"certified_pct": c.get(F["r_rate"]), "proposed_n": c.get(F["r_proposed"]),
                                "committed_pct": None if nc is None else round(100.0 - nc, 1)}
            m["cert_by_validator"] = certs
            rates = [(v["certified_pct"], n) for n, v in certs.items() if v["certified_pct"] is not None]
            m["cert_min_pct"] = min(rates)[0] if rates else na("own headers proposed in the window")
            m["cert_min_node"] = min(rates)[1] if rates else None
            gn = [certs[n]["committed_pct"] for n in GRACE_NODES if n in certs and certs[n]["committed_pct"] is not None]
            m["grace_nodes_committed_min_pct"] = min(gn) if gn else na("%s committed share" % "/".join(GRACE_NODES))
        else:
            m["cert_by_validator"] = {}
            m["cert_min_pct"] = m["grace_nodes_committed_min_pct"] = na("validator logs for cert-rate.py")
        m.update(vote_rows(nds, validators, a, b))
        trk = [t for n in nds for t in between(nds[n].tracker, a, b, key=lambda x: x)]
        m["tracker_errors"] = len(trk) if nds else na("node logs")
        # generators
        lnd = landings(r["group"], r["docs"]) if r["group"] else None
        m["landings_ge300"] = lnd[0] if lnd else na("landings-<blaster>.ndjson.gz")
        m["landings_sampled"] = lnd[1] if lnd else None
        m["landings_sample_rate"] = lnd[2] if lnd else None
        res = [((d.get(F["b_totals"]) or {}).get(F["b_resends"])) for d in r["docs"]]
        res = [x for x in res if isinstance(x, dict)]
        if res:
            tot = collections.OrderedDict()
            for x in res:
                for k, v in x.items():
                    if isinstance(v, (int, float)):
                        tot[k] = tot.get(k, 0) + v
            m["resends_by_cause"] = tot
            m["resends_total"] = sum(tot.get(F[k], 0) for k in ("b_r_transient", "b_r_other", "b_r_gap_txs", "b_r_nonce",
                                                                "b_r_fee"))
        else:
            m["resends_by_cause"] = m["resends_total"] = na("%s.%s (tn-blast H9a)" % (F["b_totals"], F["b_resends"]))
        tails = [(d.get(F["b_run"]) or {}).get(F["b_tail"]) for d in r["docs"]]
        tails = [t for t in tails if isinstance(t, dict)]
        m["tail_landed_late"] = (sum(t.get(F["b_landed_late"]) or 0 for t in tails) if tails
                                 else na("run.%s (tn-blast H9b)" % F["b_tail"]))
        m["tail_unlanded_after"] = (sum(t.get(F["b_unlanded_after"]) or 0 for t in tails) if tails
                                    else m["tail_landed_late"])
        bl = (r["group"] or {}).get("bm") or {}
        lates = [x.get(F["m_late"]) for x in bl.get(F["m_blasters"]) or [] if isinstance(x, dict)]
        lates = [x for x in lates if isinstance(x, (int, float))]
        m["late_secs_max"] = max(lates) if lates else na("manifest %s[].%s" % (F["m_blasters"], F["m_late"]))
        silent = []
        for d in r["docs"]:
            s = series(d, "b_send_cols", "b_send", "b_send_t0")
            if not s:
                continue
            idx = [s[0].index(F[k]) for k in ("b_submitted", "b_resent", "b_resigned") if F[k] in s[0]]
            i_s = s[0].index(F["b_s"]) if F["b_s"] in s[0] else 0
            run_len = best = 0
            for row in s[1]:
                if not (a <= s[2] + row[i_s] < b):
                    continue
                run_len = run_len + 1 if sum(row[i] for i in idx) == 0 else 0
                best = max(best, run_len)
            silent.append(best)
        m["gen_silent_max_s"] = max(silent) if silent else na("series.%s (tn-blast H9a)" % F["b_send"])
        # stages
        sw_ = (stage_doc or {}).get(r["row_id"])
        if sw_ is None:
            m["stages"] = na("tools/stage-latency.py output for this window")
            m["stage_seen_p50_s"] = m["stage_seen_p95_s"] = m["stages"]
        else:
            m["stage_seen_p50_s"] = sw_["h"].get(F["t_seen50"])
            m["stage_seen_p95_s"] = sw_["h"].get(F["t_seen95"])
            m["stages"] = collections.OrderedDict((s, {"median_ms": v.get(F["t_p50ms"]), "n": v.get(F["t_count"])})
                                                  for s, v in sw_["p"].items())
        # drift axis position
        mid = (a + b) / 2.0
        if axis == "wall-min":
            m["drift_x"] = r1((mid - (t_first if t_first is not None else rows[0]["from"])) / 60.0)
        else:
            m["drift_x"] = round(cum[bisect.bisect_left(btimes, mid) - 1] / 1e6, 3) if btimes and mid > btimes[0] else 0.0
        r["m"] = m


_KPIS = []


def pooled_latency(docs):
    if not docs:
        return na("generator files")
    try:
        if not _KPIS:
            _KPIS.append(load_tool(os.path.join(BENCH, "report", KPIS), "kpis_for_arms"))
        return _KPIS[0].pooled_latency(docs)
    except (OSError, ImportError, AttributeError, ValueError) as e:
        return na("report/%s pooled_latency (%s)" % (KPIS, e))


def apply_drift(rows):
    """Per blast type: slope from the first and last control rows of distinct arms; corrected values per row."""
    out = collections.OrderedDict()
    for typ in sorted({r["blast_type"] for r in rows}):
        ctl = [r for r in rows if r["blast_type"] == typ and r["arm_rec"]["control"] and not is_na(r["m"]["commit_us_tx"])]
        arms_seen = []
        for r in ctl:
            if r["arm_rec"]["arm_name"] not in [x["arm_rec"]["arm_name"] for x in arms_seen]:
                arms_seen.append(r)
        if len(arms_seen) < 2:
            out[typ] = {"note": na("two control arms with a %s row and engine logs" % typ)}
            for r in rows:
                if r["blast_type"] == typ:
                    r["m"]["commit_us_tx_corrected"] = r["m"]["commit_ms_output_corrected"] = out[typ]["note"]
                    r["m"]["drift_moved_pct_abs"] = out[typ]["note"]
            continue
        first, last = arms_seen[0], arms_seen[-1]
        dx = last["m"]["drift_x"] - first["m"]["drift_x"]
        moved = last["m"]["commit_us_tx"] / first["m"]["commit_us_tx"] - 1.0
        d = {"first": first["row_id"], "last": last["row_id"], "x_first": first["m"]["drift_x"], "x_last": last["m"]["drift_x"],
             "commit_us_tx_first": first["m"]["commit_us_tx"], "commit_us_tx_last": last["m"]["commit_us_tx"],
             "moved_pct": round(100.0 * moved, 1), "adjacent_only": abs(moved) > DRIFT_LIMIT}
        if not dx:
            d["note"] = na("a drift-axis distance between %s and %s" % (first["row_id"], last["row_id"]))
        else:
            d["slope_us_tx_per_x"] = round((last["m"]["commit_us_tx"] - first["m"]["commit_us_tx"]) / dx, 3)
            mo = (first["m"]["commit_ms_output"], last["m"]["commit_ms_output"])
            d["slope_ms_output_per_x"] = None if any(is_na(v) for v in mo) else round((mo[1] - mo[0]) / dx, 3)
        out[typ] = d
        for r in rows:
            if r["blast_type"] != typ:
                continue
            m = r["m"]
            if "slope_us_tx_per_x" not in d or is_na(m["commit_us_tx"]):
                m["commit_us_tx_corrected"] = d.get("note") or m["commit_us_tx"]
            else:
                m["commit_us_tx_corrected"] = r1(m["commit_us_tx"] - d["slope_us_tx_per_x"] * (m["drift_x"] - d["x_first"]))
            if d.get("slope_ms_output_per_x") is None or is_na(m["commit_ms_output"]):
                m["commit_ms_output_corrected"] = d.get("note") or na("commit ms/output on both controls")
            else:
                m["commit_ms_output_corrected"] = r1(m["commit_ms_output"] - d["slope_ms_output_per_x"] *
                                                     (m["drift_x"] - d["x_first"]))
            m["drift_moved_pct_abs"] = abs(d["moved_pct"])
    return out


def apply_checks(rows):
    done = []
    for r in rows:
        m = r["m"]
        p = next((x for x in reversed(done) if x["blast_type"] == r["blast_type"] and
                  x["arm_rec"]["arm_name"] != r["arm_rec"]["arm_name"]), None)
        done.append(r)
        if p is not None and not is_na(m["chain_txps"]) and not is_na(p["m"]["chain_txps"]):
            m["chain_txps_vs_prev"] = r1(m["chain_txps"] - p["m"]["chain_txps"])
        else:
            m["chain_txps_vs_prev"] = na("a previous arm's %s row with chain tx/s" % r["blast_type"])
        verdict = []
        for role, label, types, key, op, thr in CHECKS:
            if role not in r["arm_rec"]["roles"] or (types is not None and r["blast_type"] not in types):
                continue
            v = m.get(key)
            if v is None or is_na(v):
                verdict.append({"check": label, "value": v if is_na(v) else na(key), "met": None})
                continue
            ok = {">": v > thr, ">=": v >= thr, "<": v < thr, "<=": v <= thr, "==": v == thr}[op]
            verdict.append({"check": label, "value": v, "met": ok})
        m["verdict"] = verdict


def cell(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return "{:,.1f}".format(v) if abs(v) >= 100 else ("%.3f" % v if abs(v) < 10 else "%.1f" % v)
    return str(v)


def verdict_text(vs):
    if not vs:
        return "– (no threshold for this arm and type)"
    return "; ".join("%s: %s" % (x["check"], x["value"] if x["met"] is None else "%s %s" % (
        cell(x["value"]), "met" if x["met"] else "not met")) for x in vs)


def to_markdown(doc, rows, drift, axis):
    out = ["# Arms summary: %s" % doc["run_name"], ""]
    for s in doc["notes"]:
        out.append("- %s" % s)
    flags = [t for t, d in drift.items() if d.get("adjacent_only")]
    out.append("- drift axis: %s; %s" % (axis, ("commit us/tx moved > 15 %% between the controls for %s: compare "
                                                "adjacent arms only" % ", ".join(flags)) if flags else
                                       "no control pair moved > 15 %"))
    for t, d in drift.items():
        out.append("- drift %s: %s" % (t, d.get("note") or "%s -> %s, commit %s -> %s us/tx (%+.1f %%), slope %s us/tx per "
                                       "axis unit" % (d["first"], d["last"], cell(d["commit_us_tx_first"]),
                                                      cell(d["commit_us_tx_last"]), d["moved_pct"],
                                                      cell(d.get("slope_us_tx_per_x")))))
    out += ["", "| row | window (UTC) | s | switches on | chain tx/s | landed tx/s | land p50 / p95 s | seen p50 / p95 s "
            "| execute / persist / commit us/tx | commit ms/output | commit us/tx corrected | drift fit c s/min | amp "
            "(median) | rr/vma (min) | cert min % | landings >= 300 s | resends | late_secs max | silent max s "
            "| tracker errors | verdict |", "|---|---|---:|---|" + "---:|" * 16 + "---|"]
    for r in rows:
        m = r["m"]
        fit = m["commit_fit"]
        out.append("| %s | %s → %s | %d | %s | %s | %s | %s / %s | %s / %s | %s / %s / %s | %s | %s | %s | %s | %s | %s | "
                   "%s | %s | %s | %s | %s | %s |" % (
                       r["row_id"], iso(r["from"])[11:19], iso(r["to"])[11:19], int(r["to"] - r["from"]), m["switch_set"],
                       cell(m["chain_txps"]), cell(m["landed_txps"]), cell(m["land_p50_s"]), cell(m["land_p95_s"]),
                       cell(m["gen_seen_p50_s"]), cell(m["gen_seen_p95_s"]), cell(m["execute_us_tx"]), cell(m["persist_us_tx"]),
                       cell(m["commit_us_tx"]), cell(m["commit_ms_output"]), cell(m.get("commit_us_tx_corrected")),
                       fit if is_na(fit) else "%.4f" % fit["c_s_per_min"], cell(m["amp_fleet_median"]), cell(m["rr_vma_min"]),
                       cell(m["cert_min_pct"]) + (" (%s)" % m["cert_min_node"] if m.get("cert_min_node") else ""),
                       cell(m["landings_ge300"]), cell(m["resends_total"]), cell(m["late_secs_max"]),
                       cell(m["gen_silent_max_s"]), cell(m["tracker_errors"]), verdict_text(m["verdict"])))
    out.append("")
    for r in rows:
        m = r["m"]
        out += ["## %s: %s → %s (%d s; %s; blast index %s)" % (r["row_id"], iso(r["from"]), iso(r["to"]),
                                                               int(r["to"] - r["from"]), r["basis"], r["blast_idx"]), ""]
        out += ["| node | exec tx/s | execute | persist | commit | task us/tx | tx/output | commit ms/output | amp | "
                "rr/vma | certified % | committed % |", "|---|" + "---:|" * 11]
        for n, e in m["engine_by_node"].items():
            c = m["cert_by_validator"].get(n) or {}
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                n, cell(e["exec_txps"]), cell(e["execute_us_tx"]), cell(e["persist_us_tx"]), cell(e["commit_us_tx"]),
                cell(e["task_us_tx"]), cell(e["txs_per_output"]), cell(e["commit_ms_output"]), cell(e["amp"]),
                cell(e["rr_vma"]), cell(c.get("certified_pct")), cell(c.get("committed_pct"))))
        st = m["stages"]
        out += ["", "Stages (p50 ms): %s." % (st if is_na(st) else ", ".join(
            "%s %s" % (k, cell(v["median_ms"])) for k, v in st.items())),
            "Votes: lock_ms p95 %s; behind refusals per header, max %s. Commit fit: %s." % (
                cell(m["vote_lock_p95_ms"]), cell(m["behind_per_header_max"]),
                m["commit_fit"] if is_na(m["commit_fit"]) else "a %.4f s + b %s s per 1k txs + c %.4f s/min, r2 %s, n %d" % (
                    m["commit_fit"]["a_s"], cell(m["commit_fit"]["b_s_per_1k_txs"]), m["commit_fit"]["c_s_per_min"],
                    m["commit_fit"]["r2"], m["commit_fit"]["n"])), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- driver

def run_cert(cr, files_by_node, validators, rows):
    nodes = []
    for n in validators:
        if not files_by_node.get(n):
            continue
        node = cr.Node(n)
        for p in files_by_node[n]:
            node.read(p)
        node.finish(None)
        nodes.append(node)
    if not nodes:
        return {}
    doc = cr.report(nodes, [(r["row_id"], r["from"], r["to"]) for r in rows], [])
    return dict((w[F["m_name"]], w[F["r_nodes"]]) for w in doc[F["r_windows"]])


def run_stages(sl, logs_dir, groups_dirs, manifest_path, rows, tmp):
    wins = [{F["m_name"]: r["row_id"], F["t_wstart"]: r["from"], F["t_wend"]: r["to"]} for r in rows if r["docs"]]
    if not wins:
        return {}
    wf, of = os.path.join(tmp, "windows.json"), os.path.join(tmp, "stages.json")
    with open(wf, "w") as fh:
        json.dump(wins, fh)
    argv = ["--logs", logs_dir, "--windows", wf, "--keep-boundaries", "--out-json", of]
    for d in groups_dirs:
        argv += ["--blasters", d]
    if manifest_path and os.path.isfile(manifest_path):
        argv += ["--manifest", manifest_path]
    if sl.main(argv) != 0 or not os.path.isfile(of):
        return {}
    doc = read_json(of)
    return dict((w, {"h": doc[F["t_headline"]].get(w) or {}, "p": doc[F["t_pooled"]].get(w) or {}})
                for w in doc[F["t_headline"]])


def summarize(a):
    run_dir = os.path.abspath(a.run_dir)
    run = os.path.basename(os.path.normpath(run_dir))
    manifest_path = os.path.join(run_dir, "manifest.json")
    manifest = read_json(manifest_path) if os.path.isfile(manifest_path) else {}
    run = manifest.get(F["m_run_id"]) or run
    notes = []
    switches = switch_table(os.path.join(BENCH, "arms", "switches.tsv"))
    arms = arm_list(manifest, switches)
    if not manifest.get(F["m_arms"]):
        notes.append("no param_arms[]: one implicit arm, %s, over the whole run (treated as a control)" % IMPLICIT_ARM)
    rows, skipped = build_rows(run_dir, manifest, arms, a.types)
    notes += ["not measured: %s" % s for s in skipped]
    if not rows:
        print("arms-summary: no row in %s" % run_dir, file=sys.stderr)
        return None, 2
    sl = load_tool(os.path.join(HERE, STAGE_LATENCY), "stage_latency_for_arms")
    cr = load_tool(os.path.join(HERE, CERT_RATE), "cert_rate_for_arms")
    lits = literals(sl, cr)
    logs_dir = os.path.join(run_dir, "logs")
    nodes = node_names(manifest, logs_dir)
    validators = [n for n in nodes if F["v_validator"] in n]
    prefiltered = a.prefiltered or os.path.join(BENCH, "work", "prefilter", run)
    why = prefilter_usable(prefiltered, lits)
    files_by_node = {}
    if why is None and all(sl.node_logs(prefiltered, n, None) for n in nodes):
        src_dir = prefiltered
        for n in nodes:
            files_by_node[n] = sl.node_logs(prefiltered, n, None)
        notes.append("logs: prefiltered %s" % prefiltered)
    else:
        src_dir = a.cache_dir or os.path.join(BENCH, "work", "arms-summary", run)
        os.makedirs(src_dir, exist_ok=True)
        jobs = []
        for n in nodes:
            for p in (sl.node_logs(logs_dir, n, None) if os.path.isdir(logs_dir) else []):
                base = os.path.basename(p)
                dst = os.path.join(src_dir, base if base.endswith(".gz") else base + ".gz")
                jobs.append((n, p, dst))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            futs = [(n, ex.submit(filter_one, p, dst, lits)) for n, p, dst in jobs]
            for n, fu in futs:
                files_by_node.setdefault(n, []).append(fu.result())
        notes.append("logs: %s streamed through a fixed-string filter into %s (%s)" % (
            logs_dir, src_dir, why or "prefiltered files incomplete"))
    windows = sorted((r["from"], r["to"]) for r in rows)
    nds = collections.OrderedDict()
    for n in nodes:
        if files_by_node.get(n):
            nd = NodeData(n, windows)
            for p in files_by_node[n]:
                nd.read(p, len(files_by_node[n]) > 1)
            nd.finish()
            nds[n] = nd
    missing_logs = [n for n in nodes if n not in nds]
    if missing_logs:
        notes.append("no log file for %s" % ", ".join(missing_logs))
    cert_doc = run_cert(cr, files_by_node, validators, rows)
    groups = blast_groups(run_dir, manifest)
    stage_doc = {}
    if not a.no_stages:
        tmp = tempfile.mkdtemp(prefix="arms-stages-")
        try:
            stage_doc = run_stages(sl, src_dir, [g["dir"] for g in groups if g["docs"]], manifest_path, rows, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        notes.append("stages: skipped (--no-stages)")
    blocks = block_table([g["docs"] for g in groups])
    measure(run_dir, manifest, rows, nds, validators, os.path.join(run_dir, "persist"), cert_doc, stage_doc, blocks,
            a.drift_axis)
    drift = apply_drift(rows)
    apply_checks(rows)
    doc = collections.OrderedDict([
        ("tool", "arms-summary/v1"), ("run_name", run), ("generated_utc", iso(datetime.datetime.now(datetime.timezone.utc).timestamp())),
        ("drift_axis", a.drift_axis), ("notes", notes), ("drift", drift),
        ("arm_list", [collections.OrderedDict([("arm_name", x["arm_name"]), ("utc_from", None if x["from"] == float("-inf") else iso(x["from"])),
                                               ("utc_to", None if x["to"] == float("inf") else iso(x["to"])),
                                               ("roles", x["roles"]), ("control", x["control"]),
                                               ("switch_set", x["switch_set"])]) for x in arms]),
        ("summary_rows", [collections.OrderedDict([("row_id", r["row_id"]), ("arm_name", r["arm_rec"]["arm_name"]),
                                                   ("blast_type", r["blast_type"]), ("blast_idx", r["blast_idx"]),
                                                   ("utc_from", iso(r["from"])), ("utc_to", iso(r["to"])),
                                                   ("seconds", int(r["to"] - r["from"])), ("window_basis", r["basis"])]
                                                  + list(r["m"].items())) for r in rows]),
        ("log_files", dict((n, nd.files) for n, nd in nds.items()))])
    return (doc, to_markdown(doc, rows, drift, a.drift_axis)), 0


def under(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def self_check(doc):
    """[(what, expected, got, ok)] against the I-3 recut and the bench-6-only columns."""
    out = []
    rows = dict((r["blast_type"], r) for r in doc["summary_rows"])
    for typ, a, b, txps in RECUT:
        r = rows.get(typ)
        if r is None:
            out.append(("%s row" % typ, "present", "absent", False))
            continue
        out.append(("%s window" % typ, "%s → %s" % (a, b), "%s → %s" % (r["utc_from"], r["utc_to"]),
                    (r["utc_from"], r["utc_to"]) == (a, b)))
        got = r["chain_txps"]
        out.append(("%s chain tx/s" % typ, txps, got, isinstance(got, float) and abs(got - txps) <= 0.05))
        for k in BENCH6_ONLY:
            out.append(("%s %s" % (typ, k), "n/a", r.get(k), is_na(r.get(k))))
    out.append(("row count", 2, len(doc["summary_rows"]), len(doc["summary_rows"]) == 2))
    return out


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.splitlines()[2:]))
    p.add_argument("--run-dir", help="results/<run>")
    p.add_argument("--self-check", action="store_true", help="run on bench 5 and compare with the I-3 recut")
    p.add_argument("--results-root", help="the results directory for --self-check (default benchmark/results)")
    p.add_argument("--out-dir", help="where arms.md and arms.json go (default <run-dir>/analysis)")
    p.add_argument("--prefiltered", help="the teardown's prefiltered logs (default benchmark/work/prefilter/<run>)")
    p.add_argument("--cache-dir", help="the filtered-log cache (default benchmark/work/arms-summary/<run>)")
    p.add_argument("--types", help="only these blast types, comma-separated (e.g. M16,L)")
    p.add_argument("--drift-axis", choices=("chain-mtx", "wall-min"), default="chain-mtx",
                   help="the drift coordinate: cumulative chain transactions in millions (default) or wall minutes")
    p.add_argument("--no-stages", action="store_true", help="skip the stage-latency pass")
    p.add_argument("--jobs", type=int, default=4, help="log files filtered at once (default 4)")
    a = p.parse_args(argv)
    if a.self_check:
        if a.run_dir:
            p.error("--self-check takes no --run-dir")
        a.run_dir = os.path.join(a.results_root or os.path.join(BENCH, "results"), SELF_CHECK_RUN)
        base = os.path.join(BENCH, "work", "bench6-scratch", "H7b", "self-check")
        a.out_dir = a.out_dir or base
        a.cache_dir = a.cache_dir or os.path.join(base, "logs")
        a.types = a.types or "M4,M16"
        results = os.path.dirname(os.path.abspath(a.run_dir))
        for d in (a.out_dir, a.cache_dir):
            if under(d, results):
                p.error("--self-check never writes under %s (%s)" % (results, d))
    elif not a.run_dir:
        p.error("give --run-dir or --self-check")
    if a.jobs < 1:
        p.error("--jobs must be positive")
    a.types = [t.strip() for t in a.types.split(",") if t.strip()] if a.types else None
    a.out_dir = a.out_dir or os.path.join(a.run_dir, "analysis")
    return a


def main(argv=None):
    a = parse_args(argv)
    if not os.path.isdir(a.run_dir):
        print("arms-summary: no run directory %s" % a.run_dir, file=sys.stderr)
        return 1
    try:
        res, rc = summarize(a)
    except (OSError, ValueError, KeyError) as e:
        print("arms-summary: %s" % e, file=sys.stderr)
        return 1
    if res is None:
        return rc
    doc, md = res
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "arms.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    with open(os.path.join(a.out_dir, "arms.md"), "w") as fh:
        fh.write(md + "\n")
    print("arms-summary: %d rows -> %s" % (len(doc["summary_rows"]), os.path.join(a.out_dir, "arms.{md,json}")))
    if a.self_check:
        checks = self_check(doc)
        for what, exp, got, ok in checks:
            print("%s  %s: expected %s, got %s" % ("ok  " if ok else "FAIL", what, exp, got))
        return 0 if all(c[3] for c in checks) else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
