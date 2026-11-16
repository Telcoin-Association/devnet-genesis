#!/usr/bin/env python3
"""orch-prom-export.py — bench 8 (bench 7's export plus the per-series coverage check), orchestrator only: tasks/bench6/orch-prom-export.py with a completeness check
before the export (bench 6 run 3's export lacked one validator's tn_primary_vote_stage_seconds series and
nobody saw it before the teardown).

  tasks/bench8/orch-prom-export.py <out-dir> <start RFC3339> <end RFC3339> [--step 15] [--match REGEX]
                                   [--manifest benchmark/results/<run>/manifest.json] [--network bench]
                                   [--allow-missing] [--check-only] [--scrape 15] [--gap-max 120]
                                   [--restart-grace 300] [--no-coverage]

The check comes first. For each must-have metric (MUST_HAVE: the series the bench-6 analysis scripts read
most) one instant query at <end>, count by (node) (last_over_time(<metric>{network="<label>"}[<end - start>s])),
and one line:
  EXPORT_CHECK metric=<m> nodes=<n>/<expected> missing=<node,...|-> status=<ok|incomplete|lazy|absent|error>
The nodes are the manifest's (.instances, else .zones_used; without --manifest, every node any must-have
metric shows). A metric some node shows must be on every node: in bench 6 the observer carried all twenty
(run r20261114-0000's export). Two exceptions, per metric:
  VALIDATORS_ONLY: the proposer's series (bench 6: tn_primary_digests_requeued_total on the ten validators,
    never the observer) must be on every validator (.instances[].role, else a name without "observer");
  LAZY: a series registered at its first increment or set (metrics::counter!/gauge! at the event, not when
    a handle is built): a node without it has not counted one yet. Missing nodes are listed with
    status=lazy, which never refuses the export.
A metric no node shows is "absent" (not on this node build, or a lazy series nothing counted yet):
reported, not fatal. Any "incomplete" or "error" line makes it exit 3 before anything is written, unless
--allow-missing is given; --check-only stops after the check.

The export, as in bench 6: one file per metric name, <out-dir>/<metric>.json.gz, the body of
/api/v1/query_range (matrix), plus <out-dir>/INDEX.tsv (metric, series, points, bytes, seconds, status).
Then on stdout:
  PROM-EXPORT metrics=<n> ok=<n> failed=<n> series=<n> points=<n> <UTC>
  EXPORT_DONE metrics=<n> series=<n> nodes=<n>
The coverage check (bench 8; --no-coverage skips it): per must-have metric one range query at the scrape
interval (--scrape), count by (node) (count_over_time(<metric>{network="<label>"}[<scrape>s])), so a step
without a raw sample is a hole. Per node: the first and last sample time, the samples against the count
expected from the scrape interval, the longest stretch without a sample. A series whose last sample is more
than two scrape intervals before the window's end is "stopped"; one with a stretch longer than --gap-max
(seconds) is "gap". A break inside a node's chaos window from the manifest (.chaos[]: a kill or stop of the
node until its next start plus --restart-grace; no start: to the window's end) is expected
("gap-expected", "stopped-expected"). Lines:
  EXPORT_COVERAGE metric=<m> node=<n> first=<UTC> last=<UTC> samples=<n>/<expected> longest_gap=<s>s
                  status=<stopped|gap|stopped-expected|gap-expected> breaks=<from>..<to>(<s>s,<expected|unexpected>),...
  EXPORT_COVERAGE metric=<m> node=<n> samples=0/<expected> status=missing
  EXPORT_COVERAGE metric=<m> nodes=<n> whole=<n> expected=<nodes|-> stopped=<nodes|-> gap=<nodes|-> missing=<nodes|->
                  lazy=<nodes|-> status=<whole|expected|broken>      (one per metric; "absent" or "error" lines too)
  EXPORT_COVERAGE_RESULT <whole|expected-gaps-only|broken> metrics=<n> broken=<n> expected=<n> scrape=<s>s gap_max=<s>s
A broken metric refuses the export like an incomplete one ("EXPORT_REFUSED coverage_broken=<n>: ...").
Exit: 0 (all whole; exported unless --check-only), 4 (gaps only where expected; exported unless --check-only),
3 (the check refused: a series stopped, missing or with an unexpected gap, or incomplete; with
--allow-missing the export goes on and ends 0 or 1, while --check-only still says 3), 1 (a metric failed to
export), 2 usage.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PROM = os.environ.get("PROM_URL", "http://localhost:19090")
USAGE = ("usage: tasks/bench8/orch-prom-export.py <out-dir> <start RFC3339> <end RFC3339> [--step 15] [--match REGEX] "
         "[--manifest <manifest.json>] [--network bench] [--allow-missing] [--check-only]")

# The series the bench-6 analysis scripts (benchmark/private/bench6-r20261113-1351/*/scripts/*.py) read most,
# ranked by the number of scripts that query them; histograms by their _count series. The first six are
# named for themselves: the vote stages (the series run 3 lost), the switch gauges, and the persist and
# commit histograms.
MUST_HAVE = (
    "tn_primary_vote_stage_seconds_count",
    "tn_node_switch",
    "tn_engine_persist_duration_seconds_count",
    "tn_reth_persist_commit_seconds_count",
    "tn_reth_persist_save_blocks_seconds_count",
    "tn_engine_executed_transactions_total",
    "tn_engine_busy_milliseconds_total",
    "tn_primary_consensus_exec_lag_rounds",
    "tn_engine_queued_outputs",
    "reth_db_table_pages",
    "reth_db_table_entries",
    "tn_primary_votes_refused_execution_behind_total",
    "tn_primary_committed_round",
    "tn_executor_output_transactions_count",
    "tn_engine_channel_depth",
    "tn_engine_outputs_executed_total",
    # bench 7 (tasks/bench7-contract.md section 3, Prometheus names; bench 6's tn_engine_persist_wait_seconds,
    # tn_engine_unpersisted_outputs, tn_engine_commit_interval_seconds and tn_node_execution_backlog_outputs
    # are gone from this build, section 6): the vote outcomes, the order hold, the certifier's dropped
    # reports, the orphan re-pool, the epoch-record collector and its vote rounds, the closing-block and
    # close-identity checks, the leftover drain, and main's worker quota refusals (with the order hold on, a
    # far validator's held digests keep their quota slots at its peers until they commit).
    "tn_primary_vote_outcomes_total",
    "tn_primary_requeued_out_of_order_total",
    "tn_primary_requeued_order_unknown_total",
    "tn_primary_headers_held_total",
    "tn_primary_digests_held",
    "tn_primary_uncertified_report_dropped_total",
    "tn_node_orphan_txs_total",
    "tn_node_orphan_batches_total",
    "tn_state_sync_epoch_records_certified_through",
    "tn_state_sync_epoch_record_gap_walks_total",
    "tn_state_sync_epoch_record_walk_parent_mismatches_total",
    "tn_state_sync_epoch_record_conflicts_total",
    "tn_state_sync_epoch_record_conflicts_below_halt_threshold_total",
    "tn_epoch_epoch_record_closing_block_check_total",
    "tn_epoch_epoch_close_identity_check_total",
    "tn_node_epoch_record_recertify_rounds_total",
    "tn_node_epoch_record_round_conflicts_total",
    "tn_node_epoch_record_round_ended_certified_total",
    "tn_node_epoch_record_retained_votes",
    "tn_node_leftover_output_gaps_total",
    "tn_node_leftover_outputs_skipped_total",
    "tn_worker_batch_reports_over_quota_total",
    # bench 8 (tasks/bench8/node-fields.md): the voter's execution deficit, one sample per vote request, label
    # open; all three series of the histogram, since the analysis reads its buckets.
    "tn_primary_vote_exec_deficit_outputs_bucket",
    "tn_primary_vote_exec_deficit_outputs_sum",
    "tn_primary_vote_exec_deficit_outputs_count",
)

# Registered when the proposer builds its handles (crates/consensus/primary/src/metrics.rs
# RequeuedOutOfOrderHandles, RequeuedOrderUnknownHandles, OrderHoldHandles): every validator, not the observer.
VALIDATORS_ONLY = frozenset((
    "tn_primary_requeued_out_of_order_total",
    "tn_primary_requeued_order_unknown_total",
    "tn_primary_headers_held_total",
    "tn_primary_digests_held",
    # Recorded by a voter answering a vote request: every validator from its first rounds, never the observer.
    "tn_primary_vote_exec_deficit_outputs_bucket",
    "tn_primary_vote_exec_deficit_outputs_sum",
    "tn_primary_vote_exec_deficit_outputs_count",
))

# Registered at the event (metrics::counter!/gauge! where it is counted or set): the certifier's dropped report,
# the orphan re-pool at an epoch start, the closing-block and close-identity checks at a close, the vote
# rounds' re-certify picks, conflicts, short certified rounds and kept votes (the last two switches on), the
# leftover drain's skips and gaps (none on an honest run).
LAZY = frozenset((
    "tn_primary_uncertified_report_dropped_total",
    "tn_node_orphan_txs_total",
    "tn_node_orphan_batches_total",
    "tn_epoch_epoch_record_closing_block_check_total",
    "tn_epoch_epoch_close_identity_check_total",
    "tn_node_epoch_record_recertify_rounds_total",
    "tn_node_epoch_record_round_conflicts_total",
    "tn_node_epoch_record_round_ended_certified_total",
    "tn_node_epoch_record_retained_votes",
    "tn_node_leftover_output_gaps_total",
    "tn_node_leftover_outputs_skipped_total",
))

# What the export takes after the check: every tn_ series (tn_primary_, tn_node_ with tn_node_switch, tn_epoch_,
# tn_state_sync_, tn_engine_, tn_executor_, tn_worker_, tn_reth_, ...), the store's gauges (reth_db_*: tn-lmdb
# reports reth's table and free-list gauges under the same names, then its own page size, timed-out readers,
# oldest reader age and latch) and reth's save_blocks histogram.
MATCH = (r"^(tn_|reth_db_(table_size|table_pages|table_entries|freelist|page_size|timed_out_not_aborted_transactions"
         r"|oldest_reader_age_seconds|latched)$|reth_storage_providers_database_save_blocks)")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(t):
    """RFC3339 (with Z or an offset) or unix seconds, as Prometheus takes them."""
    try:
        return float(t)
    except ValueError:
        pass
    s = t.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def get_json(path, params, timeout):
    url = PROM + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = r.read()
    return body, json.loads(body)


def expected_nodes(manifest_path):
    """The run's node names from the manifest, or None without one."""
    if not manifest_path:
        return None
    with open(manifest_path) as f:
        m = json.load(f)
    nodes = sorted({inst["name"] for inst in (m.get("instances") or []) if inst.get("name")})
    return nodes or sorted(m.get("zones_used") or {})


def observers(manifest_path, nodes):
    """The observer nodes: the manifest's role, else (or without one) a name holding "observer"."""
    roles = {}
    if manifest_path:
        with open(manifest_path) as f:
            roles = {i.get("name"): i.get("role") for i in (json.load(f).get("instances") or [])}
    return {n for n in nodes if roles.get(n) == "observer" or (roles.get(n) is None and "observer" in n)}


CHAOS_DOWN = re.compile(r"\b(kill|stop|halt)\b", re.I)
CHAOS_UP = re.compile(r"\bstart\b", re.I)


def chaos_windows(manifest_path, scrape, grace, end):
    """{node: [(from, to)]}: each node's expected outage from the manifest's .chaos[] (a kill or stop until the
    node's next start plus grace; without a start, to the window's end)."""
    if not manifest_path:
        return {}
    with open(manifest_path) as f:
        chaos = json.load(f).get("chaos") or []
    events = []
    for c in chaos:
        if not isinstance(c, dict) or not c.get("node"):
            continue
        t = c.get("begin_unix", c.get("planned_unix"))
        if t is None and c.get("ts"):
            t = epoch(str(c["ts"]))
        action = str(c.get("action", ""))
        kind = "down" if CHAOS_DOWN.search(action) else ("up" if CHAOS_UP.search(action) else None)
        if t is not None and kind:
            events.append((float(t), c["node"], kind))
    windows, opened = {}, {}
    for t, node, kind in sorted(events):
        if kind == "down":
            opened.setdefault(node, t)
        elif node in opened:
            windows.setdefault(node, []).append((opened.pop(node) - scrape, t + grace))
    for node, t in opened.items():
        windows.setdefault(node, []).append((t - scrape, end + scrape))
    return windows


def fmt_utc(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def coverage(start, end, network, nodes, observer_nodes, scrape, gap_max, windows):
    """EXPORT_COVERAGE lines; returns (broken, expected): the metrics with a stopped, missing or unexpected-gap
    series, and those whose only breaks fall inside a chaos window."""
    t0, t1 = epoch(start), epoch(end)
    want_n = int((t1 - t0) // scrape) + 1
    broken = expected = 0

    def in_window(node, a, b):
        return any(a >= w0 - scrape and b <= w1 for w0, w1 in windows.get(node, []))

    for metric in MUST_HAVE:
        query = 'count by (node) (count_over_time(%s{network="%s"}[%ds]))' % (metric, network, scrape)
        try:
            _, d = get_json("/api/v1/query_range", {"query": query, "start": t0, "end": t1, "step": "%ds" % scrape}, 180)
            if d.get("status") != "success":
                raise RuntimeError(d.get("error", "not success"))
            series = {}
            for s in d["data"]["result"]:
                series.setdefault(s["metric"].get("node", ""), []).extend(float(v[0]) for v in s.get("values") or [])
        except Exception as e:  # a check that cannot be made is not a pass
            broken += 1
            print(f"EXPORT_COVERAGE metric={metric} status=error {str(e)[:120]}")
            continue
        names = nodes if nodes is not None else sorted(n for n in series if n)
        want = [n for n in names if metric not in VALIDATORS_ONLY or n not in observer_nodes]
        if not any(series.get(n) for n in want):
            print(f"EXPORT_COVERAGE metric={metric} nodes=0/{len(want)} status=absent")
            continue
        kinds = {k: [] for k in ("whole", "expected", "stopped", "gap", "missing", "lazy")}
        for n in want:
            ts = sorted(set(series.get(n) or []))
            if not ts:
                kind = "lazy" if metric in LAZY else "missing"
                kinds[kind].append(n)
                if kind == "missing":
                    print(f"EXPORT_COVERAGE metric={metric} node={n} samples=0/{want_n} status=missing")
                continue
            lead = 0.0 if metric in LAZY else ts[0] - t0
            stretches = [b - a for a, b in zip(ts, ts[1:])] + [lead, t1 - ts[-1]]
            breaks = [(a, b, "gap") for a, b in zip(ts, ts[1:]) if b - a > gap_max]
            if lead > gap_max:
                breaks.insert(0, (t0, ts[0], "gap"))
            if t1 - ts[-1] > 2 * scrape:
                breaks.append((ts[-1], t1, "stopped"))
            if not breaks:
                kinds["whole"].append(n)
                continue
            bad = [k for a, b, k in breaks if not in_window(n, a, b)]
            if bad:
                status = "stopped" if "stopped" in bad else "gap"
                kinds[status].append(n)
            else:
                status = ("stopped" if breaks[-1][2] == "stopped" else "gap") + "-expected"
                kinds["expected"].append(n)
            text = ",".join("%s..%s(%ds,%s)" % (fmt_utc(a), fmt_utc(b), int(b - a),
                                                 "expected" if in_window(n, a, b) else "unexpected") for a, b, _ in breaks)
            print(f"EXPORT_COVERAGE metric={metric} node={n} first={fmt_utc(ts[0])} last={fmt_utc(ts[-1])} "
                  f"samples={len(ts)}/{want_n} longest_gap={int(max(stretches))}s status={status} breaks={text}")
        status = "broken" if (kinds["stopped"] or kinds["gap"] or kinds["missing"]) else (
            "expected" if kinds["expected"] else "whole")
        broken += status == "broken"
        expected += status == "expected"
        print(f"EXPORT_COVERAGE metric={metric} nodes={len(want)} whole={len(kinds['whole'])} "
              + " ".join("%s=%s" % (k, ",".join(kinds[k]) or "-") for k in ("expected", "stopped", "gap", "missing", "lazy"))
              + f" status={status}")
    return broken, expected


def check(start, end, network, nodes, observer_nodes=frozenset()):
    """One EXPORT_CHECK line per must-have metric; returns the number of incomplete or failed ones."""
    window = max(int(epoch(end) - epoch(start)), 60)
    seen = {}
    errors = {}
    for metric in MUST_HAVE:
        query = 'count by (node) (last_over_time(%s{network="%s"}[%ds]))' % (metric, network, window)
        try:
            _, d = get_json("/api/v1/query", {"query": query, "time": end}, 60)
            if d.get("status") != "success":
                raise RuntimeError(d.get("error", "not success"))
            seen[metric] = sorted({s["metric"].get("node", "") for s in d["data"]["result"]} - {""})
        except Exception as e:  # a check that cannot be made is not a pass
            errors[metric] = str(e)[:120]
    if nodes is None:
        nodes = sorted({n for names in seen.values() for n in names})
        observer_nodes = {n for n in nodes if "observer" in n}
    bad = 0
    for metric in MUST_HAVE:
        want = [n for n in nodes if metric not in VALIDATORS_ONLY or n not in observer_nodes]
        if metric in errors:
            bad += 1
            print(f"EXPORT_CHECK metric={metric} nodes=?/{len(want)} missing=? status=error {errors[metric]}")
            continue
        have = set(seen[metric])
        if not have:
            print(f"EXPORT_CHECK metric={metric} nodes=0/{len(want)} missing=- status=absent")
            continue
        missing = [n for n in want if n not in have]
        status = "ok" if not missing else ("lazy" if metric in LAZY else "incomplete")
        if status == "incomplete":
            bad += 1
        print(f"EXPORT_CHECK metric={metric} nodes={len(want) - len(missing)}/{len(want)} "
              f"missing={','.join(missing) if missing else '-'} status={status}")
    return bad


def main():
    args = sys.argv[1:]
    step = 15
    match = MATCH
    manifest = None
    network = None
    allow_missing = check_only = False
    scrape, gap_max, grace, coverage_on = 15, 120, 300, True
    pos = []
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a == "--step":
                step = int(args[i + 1]); i += 2
            elif a == "--match":
                match = args[i + 1]; i += 2
            elif a == "--manifest":
                manifest = args[i + 1]; i += 2
            elif a == "--network":
                network = args[i + 1]; i += 2
            elif a == "--allow-missing":
                allow_missing = True; i += 1
            elif a == "--check-only":
                check_only = True; i += 1
            elif a == "--scrape":
                scrape = int(args[i + 1]); i += 2
            elif a == "--gap-max":
                gap_max = int(args[i + 1]); i += 2
            elif a == "--restart-grace":
                grace = int(args[i + 1]); i += 2
            elif a == "--no-coverage":
                coverage_on = False; i += 1
            elif a.startswith("--"):
                raise ValueError("unknown option " + a)
            else:
                pos.append(a); i += 1
        out, start, end = pos
        if epoch(end) <= epoch(start):
            raise ValueError("the end is not after the start")
        if scrape <= 0 or gap_max <= 0 or grace < 0:
            raise ValueError("--scrape and --gap-max are positive, --restart-grace not negative")
    except (IndexError, ValueError) as e:
        print(f"{USAGE}  ({e})", file=sys.stderr)
        return 2

    nodes = expected_nodes(manifest)
    if network is None and manifest:
        with open(manifest) as f:
            network = (json.load(f).get("prometheus") or {}).get("network_label")
    network = network or "bench"
    bad = check(start, end, network, nodes, observers(manifest, nodes or []))
    cov_broken = cov_expected = 0
    if coverage_on:
        cov_broken, cov_expected = coverage(start, end, network, nodes, observers(manifest, nodes or []), scrape, gap_max,
                                            chaos_windows(manifest, scrape, grace, epoch(end)))
        verdict = "broken" if cov_broken else ("expected-gaps-only" if cov_expected else "whole")
        print(f"EXPORT_COVERAGE_RESULT {verdict} metrics={len(MUST_HAVE)} broken={cov_broken} expected={cov_expected} "
              f"scrape={scrape}s gap_max={gap_max}s")
    if bad and not allow_missing:
        print(f"EXPORT_REFUSED incomplete={bad}: nothing exported (read the EXPORT_CHECK lines; --allow-missing exports anyway)")
        return 3
    if cov_broken and not allow_missing:
        print(f"EXPORT_REFUSED coverage_broken={cov_broken}: nothing exported (read the EXPORT_COVERAGE lines; --allow-missing exports anyway)")
        return 3
    rc_ok = 4 if cov_expected and not (bad or cov_broken) else 0
    if check_only:
        return 3 if (bad or cov_broken) else rc_ok

    os.makedirs(out, exist_ok=True)
    _, d = get_json("/api/v1/label/__name__/values", None, 30)
    names = [n for n in d["data"] if re.search(match, n)]
    ok = failed = series = points = 0
    node_names = set()
    with open(os.path.join(out, "INDEX.tsv"), "w") as idx:
        idx.write("metric\tseries\tpoints\tgz_bytes\tseconds\tstatus\n")
        for n in names:
            t0 = time.time()
            path = os.path.join(out, n + ".json.gz")
            try:
                body, d = get_json("/api/v1/query_range", {"query": n, "start": start, "end": end, "step": f"{step}s"}, 180)
                if d.get("status") != "success":
                    raise RuntimeError(d.get("error", "not success"))
                res = d["data"]["result"]
                ns, npts = len(res), sum(len(s["values"]) for s in res)
                node_names.update(s["metric"]["node"] for s in res if s["metric"].get("node"))
                with gzip.open(path, "wb", compresslevel=6) as g:
                    g.write(body)
                series += ns; points += npts; ok += 1
                idx.write(f"{n}\t{ns}\t{npts}\t{os.path.getsize(path)}\t{time.time() - t0:.1f}\tok\n")
            except Exception as e:  # one metric that fails does not stop the export
                failed += 1
                idx.write(f"{n}\t0\t0\t0\t{time.time() - t0:.1f}\tFAILED {str(e)[:120]}\n")
            idx.flush()
            time.sleep(float(os.environ.get("PROM_EXPORT_PAUSE_SECS", "0.2")))
    print(f"PROM-EXPORT metrics={len(names)} ok={ok} failed={failed} series={series} points={points} {utc_now()}")
    print(f"EXPORT_DONE metrics={ok} series={series} nodes={len(node_names)}")
    return rc_ok if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
