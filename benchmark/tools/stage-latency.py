#!/usr/bin/env python3
"""Time to land, stage by stage: each node's log joined with its generator's block table.

Usage:
  stage-latency.py --run-dir results/<run> [--node INST ...] [--windows FILE]
                   [--exclude-boundaries [GLOB] | --keep-boundaries] [--boundary-secs 30] [--max-lines N]
                   [--out-json PATH] [--out-md PATH] [--format md|json]
  stage-latency.py --logs DIR --blasters DIR [--blasters DIR ...] [--manifest FILE] ...

A generator (tn-blast/v2, `blocks.columns` read by column name) sends to one node, and that node
batches, proposes and scans the generator's transactions, so one node log and its generator's file
hold the whole path of every own block (own_tx > 0). Per block:

  S0  RPC accept          own_accept_p50_ms (block table)
  S1  pool wait           "batch built" pool_age_p50_ms (queued_before, pending_before, build_ms: aux)
  S2  seal -> 2f+1 acks   "batch sealed" quorum_ms
  S3  report              "batch reported" report_ms
  S4  digest wait         first "header proposed" whose digests=[...] holds the batch, minus "batch
                          reported"; else that header's oldest_digest_wait_ms; else "batch sealed" by
                          digest; else the FIFO below (S3 included in the last two)
  S5  certification       "quorum reached" of the header that carried the batch minus the first
                          "header proposed" that held it (a re-proposal counts here)
  S6a own cert -> leader  leader created minus "quorum reached"; 0 for a batch in the committing
                          leader's own header
  S6b leader -> commit    "subdag committed" (else "subdag sequenced") minus leader created; for a
                          batch in the leader's own header, minus that header's "quorum reached"
  S7  execution wait      "waited for execution before assembling the output" waited_ms; 0 when that
                          line is absent on a build that logs it (seen "subdag sequenced" or the line
                          itself), unmeasured on older builds
  S8  fetch               "consensus output ready" fetch_ms
  S9  pack persist        "output saved" pack_persist_ms
  S10 channel + queue     "output execution task finished" forward_wait_ms + queue_wait_ms
  S11 execute             "output executed" execute_ms (recover/evm/root/finish/other_ms: aux)
  S12 persist + announce  "output executed" persist_ms + announce_ms
  S13 visibility          seen_ms minus the "output executed" line (an output is on RPC once it is
                          persisted and announced); minus "next block executed" when that is missing

Joins. The digest is the block's batch_digest_prefix (16 lowercase hex, no 0x), else the node's
"next block executed batch_digest="; the node logs digests as 0x + hex and the first 16 hex chars are
the key. Digest -> "batch built/sealed/reported" -> "header proposed" (epoch, round) -> "quorum
reached" (epoch, round). The block's (epoch, round) is the committing leader's: -> "subdag committed"
(epoch = subdag_index >> 32, leader_round) with the "certificate committed" lines before it. Block
number -> "next block executed" -> consensus number -> "waited for execution", "consensus output
ready", "output saved", "output queued", "output execution task finished", "output executed".
Leader created = the sub-DAG's leader_created_at_ms, else the node's own "header proposed" at the
leader round (created_at_ms, else the line time): exact when the node led, a proxy otherwise.

FIFO (logs without digests, e.g. bench 4): the node's own certificates that the block's sub-DAG
committed, by round, each holding the batches its "header proposed num_batches=" took in order from
the "batch sealed" lines before it, zipped with the generator's own blocks of that sub-DAG by number
when the counts agree. A batch whose num_txs differs from the block's tx_count is not used for S4.

Headline per block: ts = S0..S6a (submit -> leader created), commit = ts + S6b, seen = commit +
S7..S13. From the generator: submit = seen_ms - own_submit_p50_ms, then leader created - submit,
commit - submit and own_submit_p50_ms itself (ts_read = block timestamp - submit, as published).
When no block has every stage of a sum, "partial" gives the longest measured tail (e.g. from S4).
Coverage: blocks with every stage and a generator seen; |sum(S0..S13) - own_submit_p50_ms| <= 250 ms.
Events per node and window (events.<node>.<window>): header_uncertified {lines, sum} and
digests_resent {lines, sum, by_cause: {<cause>: {lines, sum}}}, sum = the lines' count= total; cause
is canceled (an own header's certification was cancelled) or committed (the commit path re-queued
them), unknown on a build whose line has no cause=.

Windows (block timestamp in [start, end)): --windows FILE takes {"windows": {name: {start, end}}}
(ISO, or start_utc/end_utc, or start_unix/end_unix), a top-level {name: {...}} map or a list of
{name, start, end}. Without it: under --run-dir, each archived light blast (blast-<i>-<UTC>/blasters)
is its mixed phase, named from manifest blasts[] as light<senders> (light<senders>x<window> when the
window is not 16) or load (chaos); the main blasters/ dir is load when manifest blasts[] exists, else
its preamble, warmup, mixed and cooldown phases. "all" (no filter) is always added.
Blocks within --boundary-secs of an epoch boundary (blocks with closes_epoch set) are dropped from the
light* windows by default (a loaded boundary waits for execution, which a floor must not average in);
--exclude-boundaries GLOB applies the exclusion to the windows matching GLOB instead, and
--keep-boundaries keeps every block in every window.

Percentiles are nearest rank. Exit status: 0 = report written; 1 = bad arguments or unreadable
input; 2 = no node has both a log and a generator file. Stdlib only.
"""
import argparse
import calendar
import collections
import datetime
import fnmatch
import gzip
import io
import json
import math
import os
import re
import sys

STAGES = (
    ("S0", "RPC accept"), ("S1", "pool wait"), ("S2", "seal -> 2f+1 acks"), ("S3", "report"),
    ("S4", "digest wait"), ("S5", "certification"), ("S6a", "own cert -> leader created"),
    ("S6b", "leader created -> commit"), ("S7", "execution wait"), ("S8", "batch fetch"),
    ("S9", "pack persist"), ("S10", "channel + engine queue"), ("S11", "execute"),
    ("S12", "persist + announce"), ("S13", "visibility (scanner)"))
STAGE_IDS = tuple(s for s, _ in STAGES)
SPANS = (("ts", "S6a"), ("commit", "S6b"), ("seen", "S13"))
AUX = ("queued_before", "pending_before", "build_ms", "slots_persist_ms", "depth", "task_ms",
       "recover_ms", "recover_wait_ms", "evm_ms", "root_ms", "finish_ms", "other_ms")

MSGS = ("batch built", "batch sealed", "batch reported", "header proposed", "quorum reached",
        "header uncertified", "digests resent", "certificate committed", "subdag committed",
        "subdag sequenced", "waited for execution before assembling the output", "consensus output ready",
        "output saved", "output queued", "output execution task finished", "output executed",
        "next block executed")
MSG_AT = re.compile(b'(' + b"|".join(re.escape(m.encode()) for m in MSGS) + b')"')
TS_RE = re.compile(r"^(?:ts=)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?")
FIELD_RE = re.compile(r'(?:^|\s)([A-Za-z_]\w*)=("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\S+)')
HEX_RE = re.compile(r"(?<![0-9A-Za-z])(?:0x)?([0-9a-fA-F]{16,})(?![0-9A-Za-z])")
AUTH_RE = re.compile(r"Some\(([1-9A-HJ-NP-Za-km-z]+)\)")
BLAST_DIR_RE = re.compile(r"^blast-(\d+)-")
DEFAULT_WINDOW = 16
_SECS = {}


def iso(sec):
    return datetime.datetime.fromtimestamp(int(sec), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_ms(text):
    """Unix ms of a line's leading ISO-8601 UTC time (`ts=` optional), or None."""
    m = TS_RE.match(text)
    if not m:
        return None
    key = m.group(0)[:-len(m.group(7))] if m.group(7) else m.group(0)
    sec = _SECS.get(key)
    if sec is None:
        sec = calendar.timegm(tuple(int(g) for g in m.groups()[:6]))
        if len(_SECS) > 4096:
            _SECS.clear()
        _SECS[key] = sec
    return sec * 1000.0 + (float(m.group(7)) * 1000.0 if m.group(7) else 0.0)


def parse_time(v):
    """Seconds since the epoch of an ISO-8601 UTC string or a number of Unix seconds."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    ms = ts_ms(s)
    rest = s[TS_RE.match(s).end():] if ms is not None else None
    if ms is None or rest not in ("", "Z", "+00:00"):
        raise ValueError("not an ISO-8601 UTC time: %r" % v)
    return ms / 1000.0


def num(f, key):
    v = f.get(key)
    if v is None:
        return None
    try:
        return float(v) if ("." in v or "e" in v) else int(v)
    except ValueError:
        return None


def d16(text):
    """First 16 hex chars (lowercase) of a digest written as 0x... or bare hex, else None."""
    if not text:
        return None
    m = HEX_RE.search(text)
    return m.group(1)[:16].lower() if m else None


def digest_key(v):
    """The join key of a block's batch digest (column or log field); None when absent or all zeros."""
    k = d16(v) if isinstance(v, str) else None
    return k if k and k.strip("0") else None


def open_bin(path):
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic == b"\x1f\x8b":
        return io.BufferedReader(gzip.open(path, "rb"), buffer_size=1 << 20)
    return open(path, "rb", buffering=1 << 20)


def first_line(path):
    try:
        with open_bin(path) as fh:
            return fh.readline().decode("utf-8", "replace")
    except (OSError, EOFError):
        return ""


class NodeLog(object):
    """The joined keys of one node's log files (only what the join needs is kept)."""

    def __init__(self, name):
        self.name = name
        self.files = []
        self.lines = 0
        self.truncated = False
        self.msg_count = collections.Counter()
        self.fields = collections.defaultdict(set)
        self.auth = collections.Counter()
        self.built, self.sealed, self.reported = {}, {}, {}
        self.fifo = collections.deque()       # (ts, num_txs) of "batch sealed", for headers without digests
        self.headers = {}                     # (epoch, round) -> dict
        self.digest_headers = collections.defaultdict(list)
        self.quorum = {}
        self.pending = []                     # certificate committed since the last subdag committed
        self.subdags = {}                     # (epoch, leader_round) -> dict
        self.sequenced = {}
        self.cn_by_leader = {}                # (epoch, leader_round) -> consensus number
        self.waited, self.ready, self.saved, self.queued, self.task, self.out = {}, {}, {}, {}, {}, {}
        self.blocks = {}                      # block number -> (ts, consensus number, digest16)
        self.events = collections.defaultdict(list)
        self.digest_unparsed = 0

    def read(self, path, max_lines):
        with open_bin(path) as fh:
            for raw in fh:
                if max_lines is not None and self.lines >= max_lines:
                    self.truncated = True
                    break
                self.lines += 1
                at = raw.find(b'message="')
                if at < 0:
                    continue
                m = MSG_AT.match(raw, at + 9)
                if not m:
                    continue
                line = raw.decode("utf-8", "replace")
                t = ts_ms(line)
                if t is None:
                    continue
                msg = m.group(1).decode()
                rest = line[line.find('message="') + 9 + len(msg) + 1:]
                f = {}
                for k, v in FIELD_RE.findall(rest):
                    f.setdefault(k, v)
                self.msg_count[msg] += 1
                self.fields[msg].update(f)
                self.event(msg, t, f)
        self.files.append(os.path.basename(path))

    def event(self, msg, t, f):
        if msg == "batch built":
            d = d16(f.get("digest"))
            if d:
                self.built.setdefault(d, dict(ts=t, pool_age=num(f, "pool_age_p50_ms"), build_ms=num(f, "build_ms"),
                                              queued_before=num(f, "queued_before"),
                                              pending_before=num(f, "pending_before")))
        elif msg == "batch sealed":
            d = d16(f.get("digest"))
            if d:
                self.sealed.setdefault(d, dict(ts=t, quorum_ms=num(f, "quorum_ms")))
            elif "digest" in f:
                self.digest_unparsed += 1
            self.fifo.append((t, num(f, "num_txs")))
        elif msg == "batch reported":
            d = d16(f.get("digest"))
            if d:
                self.reported.setdefault(d, dict(ts=t, report_ms=num(f, "report_ms")))
        elif msg == "header proposed":
            key = (num(f, "epoch"), num(f, "round"))
            if key in self.headers:
                return
            h = dict(ts=t, created=num(f, "created_at_ms"), num_batches=num(f, "num_batches") or 0,
                     oldest=num(f, "oldest_digest_wait_ms"), fifo=None)
            if "digests" in f:
                for x in HEX_RE.findall(f["digests"]):
                    self.digest_headers[x[:16].lower()].append(key)
            else:
                h["fifo"] = [self.fifo.popleft() if self.fifo else None for _ in range(int(h["num_batches"]))]
            self.headers[key] = h
        elif msg == "quorum reached":
            self.quorum.setdefault((num(f, "epoch"), num(f, "round")), t)
        elif msg == "header uncertified":
            self.events["header_uncertified"].append((t, 1))
        elif msg == "digests resent":
            # cause: canceled (a cancelled own header's digests) or committed (the commit path's
            # re-queue); a build that logs no cause counts as unknown
            cause = f.get("cause", "").strip('"') or "unknown"
            self.events["digests_resent"].append((t, num(f, "count") or 0, cause))
        elif msg == "certificate committed":
            self.pending.append((num(f, "round"), f.get("origin")))
        elif msg in ("subdag committed", "subdag sequenced"):
            idx, lr = num(f, "subdag_index"), num(f, "leader_round")
            key = (idx >> 32 if isinstance(idx, int) else num(f, "epoch"), lr)
            if msg == "subdag sequenced":
                self.sequenced.setdefault(key, t)
                return
            if key not in self.subdags:
                self.subdags[key] = dict(ts=t, leader=f.get("leader"), created=num(f, "leader_created_at_ms"),
                                         certs=self.pending)
            self.pending = []
        elif msg == "waited for execution before assembling the output":
            self.waited.setdefault(num(f, "number"), num(f, "waited_ms"))
        elif msg == "consensus output ready":
            c = num(f, "number")
            self.ready.setdefault(c, dict(ts=t, fetch_ms=num(f, "fetch_ms")))
            if num(f, "leader_epoch") is not None:
                self.cn_by_leader.setdefault((num(f, "leader_epoch"), num(f, "leader_round")), c)
            a = AUTH_RE.search(f.get("authority") or "")
            if a:
                self.auth[a.group(1)] += 1
        elif msg == "output saved":
            self.saved.setdefault(num(f, "number"), dict(pack=num(f, "pack_persist_ms"),
                                                         slots=num(f, "slots_persist_ms")))
        elif msg == "output queued":
            self.queued.setdefault(num(f, "consensus_number"), num(f, "depth"))
        elif msg == "output execution task finished":
            self.task.setdefault(num(f, "consensus_number"), dict(forward=num(f, "forward_wait_ms"),
                                                                  queue=num(f, "queue_wait_ms"),
                                                                  task_ms=num(f, "task_ms")))
        elif msg == "output executed":
            c = num(f, "consensus_number")
            if c not in self.out:
                self.out[c] = dict(ts=t, **{k: num(f, k) for k in (
                    "execute_ms", "persist_ms", "announce_ms", "recover_ms", "recover_wait_ms", "evm_ms",
                    "root_ms", "finish_ms", "other_ms")})
                if num(f, "epoch") is not None:
                    self.cn_by_leader.setdefault((num(f, "epoch"), num(f, "leader_round")), c)
        elif msg == "next block executed":
            self.blocks.setdefault(num(f, "number"), (t, num(f, "consensus_number"), d16(f.get("batch_digest"))))

    @property
    def f1_build(self):
        return bool(self.msg_count["subdag sequenced"] or
                    self.msg_count["waited for execution before assembling the output"])

    def has(self, msg, field=None):
        return self.msg_count[msg] > 0 and (field is None or field in self.fields[msg])


# ---------------------------------------------------------------- generator side

class Blocks(object):
    """One node's block rows (by column name), merged over its generators' files."""

    def __init__(self):
        self.columns = set()
        self.rows = {}
        self.files = []

    def add(self, doc, path):
        b = doc.get("blocks") or {}
        cols = list(b.get("columns") or [])
        self.columns.update(cols)
        parts = os.path.normpath(path).split(os.sep)
        self.files.append("/".join(parts[-3:] if len(parts) > 2 and BLAST_DIR_RE.match(parts[-3]) else parts[-2:]))
        for r in b.get("rows") or []:
            row = dict(zip(cols, r))
            n = row.get("number")
            if n is None:
                continue
            old = self.rows.get(n)
            if old is None or (not old.get("own_tx") and row.get("own_tx")):
                self.rows[n] = row


def blaster_node(doc):
    """The node a tn-blast result sent to: run.args.nodes[0] (`name=url`), else blaster NN -> validator NN."""
    run = doc.get("run") or {}
    nodes = (run.get("args") or {}).get("nodes") or []
    if nodes and isinstance(nodes[0], str):
        name = nodes[0].split("=", 1)[0].strip()
        if name and "://" not in name:
            return name
    m = re.match(r"^(.*)-blaster-(\d+)$", str(run.get("label") or ""))
    return "%s-validator-%s" % (m.group(1), m.group(2)) if m else None


def load_blasters(directory):
    out = []
    for f in sorted(os.listdir(directory)):
        if not f.endswith(".json"):
            continue
        p = os.path.join(directory, f)
        with open(p) as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("tn-blast/"):
            out.append((p, doc))
    return out


# ---------------------------------------------------------------- windows

def merged_phase(docs, name):
    spans = []
    for _, d in docs:
        for p in (d.get("run") or {}).get("phases") or []:
            if p.get("name") == name and p.get("start_unix") is not None and p.get("end_unix") is not None:
                spans.append((float(p["start_unix"]), float(p["end_unix"])))
    return (min(s for s, _ in spans), max(e for _, e in spans)) if spans else None


def windows_from_file(path):
    with open(path) as fh:
        doc = json.load(fh)
    src = doc.get("windows", doc) if isinstance(doc, dict) else doc
    items = []
    if isinstance(src, dict):
        items = [(k, v) for k, v in src.items() if isinstance(v, dict)]
    elif isinstance(src, list):
        items = [(v.get("name") or v.get("label"), v) for v in src if isinstance(v, dict)]
    out = []
    for name, v in items:
        s = next((v[k] for k in ("start", "start_utc", "start_unix", "begin") if v.get(k) is not None), None)
        e = next((v[k] for k in ("end", "end_utc", "end_unix") if v.get(k) is not None), None)
        if name and s is not None and e is not None:
            out.append((str(name), parse_time(s), parse_time(e)))
    if not out:
        raise ValueError("%s holds no window with a name, a start and an end" % path)
    return out


def blast_name(entry):
    if entry.get("chaos") or entry.get("kind") == "load":
        return "load"
    w = entry.get("window")
    name = "light%s" % entry.get("senders", "?")
    return name if w in (None, "", DEFAULT_WINDOW, str(DEFAULT_WINDOW)) else "%sx%s" % (name, w)


def derived_windows(groups, manifest):
    """Windows from the blast groups [(index or None, docs)] and manifest blasts[]."""
    blasts = {}
    for b in (manifest or {}).get("blasts") or []:
        if isinstance(b, dict) and b.get("index") is not None:
            blasts[int(b["index"])] = b
    archived = {i for i, _ in groups if i is not None}
    out = []
    for index, docs in sorted(groups, key=lambda g: (g[0] is None, g[0] or 0)):
        if index is None and not blasts:
            for ph in ("preamble", "warmup", "mixed", "cooldown"):
                span = merged_phase(docs, ph)
                if span:
                    out.append((ph, span[0], span[1]))
            continue
        span = merged_phase(docs, "mixed")
        if not span:
            continue
        if index is None:
            rest = [i for i in blasts if i not in archived]
            name = blast_name(blasts[rest[0]]) if len(rest) == 1 else "load"
        else:
            name = blast_name(blasts[index]) if index in blasts else "blast%d" % index
        out.append((name, span[0], span[1]))
    seen = collections.Counter()
    named = []
    for name, s, e in out:
        seen[name] += 1
        named.append((name if seen[name] == 1 else "%s-%d" % (name, seen[name]), s, e))
    return named


# ---------------------------------------------------------------- the join

class Joined(object):
    """One own block's stages (ms), with the basis each came from."""

    def __init__(self, row):
        self.row = row
        self.number = row.get("number")
        self.ts = row.get("timestamp")
        self.st = {}
        self.basis = {}
        self.aux = {}
        self.leader_created = None
        self.commit = None
        self.gen = {}

    def put(self, stage, value, basis=None):
        if value is not None:
            self.st[stage] = float(value)
            if basis:
                self.basis[stage] = basis


def leader_created(log, authority, key):
    sd = log.subdags.get(key)
    if sd and sd.get("created") is not None:
        return float(sd["created"]), "leader_created_at_ms"
    h = log.headers.get(key)
    if h is None:
        return None, None
    t = h["created"] if h.get("created") is not None else h["ts"]
    if sd and authority and sd.get("leader") == authority:
        return float(t), "own_header"
    return float(t), "proxy_own_header"


def fifo_slots(log, authority, key, own_numbers):
    """{block number: (cert round, (sealed ts, num_txs) or None)} for one sub-DAG, or {} when unsure."""
    sd = log.subdags.get(key)
    if not sd or not authority:
        return {}
    slots = []
    for r in sorted(r for r, o in sd["certs"] if o == authority):
        h = log.headers.get((key[0], r))
        if h is None or h.get("fifo") is None:
            return {}
        slots.extend((r, b) for b in h["fifo"])
    if len(slots) != len(own_numbers):
        return {}
    return dict(zip(sorted(own_numbers), slots))


def join_node(log, blocks, authority):
    own = [r for r in blocks.rows.values() if r.get("own_tx")]
    by_leader = collections.defaultdict(list)
    for r in own:
        by_leader[(r.get("epoch"), r.get("round"))].append(r["number"])
    fifo_cache = {}
    out = []
    for row in sorted(own, key=lambda r: r["number"]):
        j = Joined(row)
        e, lr, n = row.get("epoch"), row.get("round"), row["number"]
        key = (e, lr)
        # The generator writes 0 both for "0 ms" and for "no own transaction had an accept stamp"
        # (a block whose own transactions none joined the ledger); only a positive value is a sample.
        if row.get("own_accept_p50_ms"):
            j.put("S0", row["own_accept_p50_ms"])
        be = log.blocks.get(n)
        d = digest_key(row.get("batch_digest_prefix"))
        if d is None and be:
            d = digest_key(be[2])
        rc = h1 = None
        if d is not None:
            b = log.built.get(d)
            if b:
                j.put("S1", b["pool_age"])
                for k in ("queued_before", "pending_before", "build_ms"):
                    if b.get(k) is not None:
                        j.aux[k] = b[k]
            s = log.sealed.get(d)
            if s:
                j.put("S2", s["quorum_ms"])
            rep = log.reported.get(d)
            if rep:
                j.put("S3", rep["report_ms"])
            hs = log.digest_headers.get(d) or []
            if hs:
                h1 = min(hs, key=lambda k: log.headers[k]["ts"])
                cands = [k for k in hs if k in log.quorum and k[0] == e and lr is not None and k[1] <= lr]
                rc = max(cands, key=lambda k: k[1])[1] if cands else None
                ht = log.headers[h1]["ts"]
                if rep:
                    j.put("S4", ht - rep["ts"], "batch_reported")
                elif log.headers[h1].get("oldest") is not None:
                    j.put("S4", log.headers[h1]["oldest"], "oldest_digest_wait_ms")
                elif s:
                    j.put("S4", ht - s["ts"], "batch_sealed")
        if rc is None and h1 is None:
            if key not in fifo_cache:
                fifo_cache[key] = fifo_slots(log, authority, key, by_leader[key])
            slot = fifo_cache[key].get(n)
            if slot:
                rc, batch = slot
                h1 = (e, rc)
                if batch and batch[0] is not None and (batch[1] is None or row.get("tx_count") is None
                                                       or batch[1] == row.get("tx_count")):
                    j.put("S4", log.headers[h1]["ts"] - batch[0], "fifo_sealed")
        q = log.quorum.get((e, rc)) if rc is not None else None
        if q is not None and h1 is not None:
            j.put("S5", q - log.headers[h1]["ts"])
        lc, src = leader_created(log, authority, key)
        sd = log.subdags.get(key)
        commit = sd["ts"] if sd else log.sequenced.get(key)
        j.leader_created, j.commit = lc, commit
        if rc is not None and rc == lr and q is not None:
            j.put("S6a", 0.0, "leader_own_batch")
            if commit is not None:
                j.put("S6b", commit - q, "leader_own_batch")
        else:
            if q is not None and lc is not None:
                j.put("S6a", lc - q, src)
            if commit is not None and lc is not None:
                j.put("S6b", commit - lc, src)
        c = be[1] if be else log.cn_by_leader.get(key)
        if c in log.waited:
            j.put("S7", log.waited[c], "waited_line")
        elif log.f1_build and c is not None:
            j.put("S7", 0.0, "no_line_below_threshold")
        rd = log.ready.get(c)
        if rd:
            j.put("S8", rd["fetch_ms"])
        sv = log.saved.get(c)
        if sv:
            j.put("S9", sv["pack"])
            if sv["slots"] is not None:
                j.aux["slots_persist_ms"] = sv["slots"]
        if log.queued.get(c) is not None:
            j.aux["depth"] = log.queued[c]
        tk = log.task.get(c)
        if tk:
            parts = [x for x in (tk["forward"], tk["queue"]) if x is not None]
            if parts:
                j.put("S10", sum(parts), "forward+queue" if len(parts) == 2 else
                      ("queue_wait_ms only" if tk["queue"] is not None else "forward_wait_ms only"))
            if tk["task_ms"] is not None:
                j.aux["task_ms"] = tk["task_ms"]
        ox = log.out.get(c)
        if ox:
            j.put("S11", ox["execute_ms"])
            if ox["persist_ms"] is not None:
                j.put("S12", ox["persist_ms"] + (ox["announce_ms"] or 0),
                      "persist+announce" if ox["announce_ms"] is not None else "persist_ms only")
            # E2 logged recover_ms; E4 renamed it recover_wait_ms (time blocked on the recovery job).
            for k in ("recover_ms", "recover_wait_ms", "evm_ms", "root_ms", "finish_ms", "other_ms"):
                if ox.get(k) is not None:
                    j.aux[k] = ox[k]
        seen = row.get("seen_ms")
        if seen:
            if ox:
                j.put("S13", seen - ox["ts"], "output_executed")
            elif be:
                j.put("S13", seen - be[0], "next_block_executed")
        sub = row.get("own_submit_p50_ms")
        if seen and sub:
            submit = float(seen) - float(sub)
            j.gen = {"seen": float(sub)}
            if lc is not None:
                j.gen["ts"] = lc - submit
            if commit is not None:
                j.gen["commit"] = commit - submit
            if j.ts is not None:
                j.gen["ts_read"] = float(j.ts) * 1000.0 - submit
        out.append(j)
    return out


def chain(j, upto, start="S0"):
    ids = STAGE_IDS[STAGE_IDS.index(start):STAGE_IDS.index(upto) + 1]
    if all(s in j.st for s in ids):
        return sum(j.st[s] for s in ids)
    return None


def why_unmeasured(stage, log, cols):
    """A short reason a stage has no value on any block of this node."""
    digest = "batch_digest_prefix" in cols or log.has("next block executed", "batch_digest")
    need = {
        "S0": [] if "own_accept_p50_ms" in cols else ["blocks: no own_accept_p50_ms column"],
        "S1": ["log: no `batch built` pool_age_p50_ms"] if not log.has("batch built", "pool_age_p50_ms") else [],
        "S2": ["log: no `batch sealed` quorum_ms"] if not log.has("batch sealed", "quorum_ms") else [],
        "S3": ["log: no `batch reported` report_ms"] if not log.has("batch reported", "report_ms") else [],
        "S7": [] if log.f1_build else ["log: no `subdag sequenced` / `waited for execution` line (pre-F1 build)"],
        "S8": ["log: no `consensus output ready` fetch_ms"] if not log.has("consensus output ready", "fetch_ms") else [],
        "S9": ["log: no `output saved` pack_persist_ms"] if not log.has("output saved", "pack_persist_ms") else [],
        "S10": [] if log.has("output execution task finished") else ["log: no `output execution task finished`"],
        "S11": [] if log.has("output executed", "execute_ms") else ["log: no `output executed` execute_ms"],
        "S12": [] if log.has("output executed", "persist_ms") else ["log: no `output executed` persist_ms"],
        "S13": [] if "seen_ms" in cols else ["blocks: no seen_ms column"],
    }.get(stage, [])
    if stage in ("S1", "S2", "S3") and not digest:
        need = ["blocks: no batch_digest_prefix (and no `next block executed batch_digest=`)"] + need
    if stage in ("S4", "S5", "S6a") and not (digest and log.has("header proposed", "digests")):
        need.append("no digest join (`header proposed digests=`) and no FIFO match")
    if stage in ("S6a", "S6b") and not log.has("subdag committed") and not log.has("subdag sequenced"):
        need.append("log: no `subdag committed` line")
    return need or ["no block joined"]


# ---------------------------------------------------------------- aggregation

def pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[max(1, int(math.ceil(q * len(v)))) - 1]


def r1(x):
    return None if x is None else round(x, 1)


def r3s(x):
    return None if x is None else round(x / 1000.0, 3)


def stage_table(joined, reasons=None):
    out = collections.OrderedDict()
    for s in STAGE_IDS:
        vals = [j.st[s] for j in joined if s in j.st]
        row = collections.OrderedDict([("count", len(vals)), ("p50_ms", r1(pct(vals, 0.5))),
                                       ("p95_ms", r1(pct(vals, 0.95))), ("unmeasured", len(joined) - len(vals))])
        basis = collections.Counter(j.basis[s] for j in joined if s in j.basis)
        if basis:
            row["basis"] = dict(sorted(basis.items()))
        if not vals and reasons is not None and joined:
            row["missing"] = reasons.get(s, [])
        out[s] = row
    return out


def aux_table(joined):
    out = collections.OrderedDict()
    for k in AUX:
        vals = [j.aux[k] for j in joined if k in j.aux]
        if vals:
            out[k] = {"count": len(vals), "p50": r1(pct(vals, 0.5)), "p95": r1(pct(vals, 0.95))}
    return out


def headline(joined):
    h = collections.OrderedDict()
    counts = {}
    for name, upto in SPANS:
        vals = [v for v in (chain(j, upto) for j in joined) if v is not None]
        h["%s_p50_s" % name], h["%s_p95_s" % name] = r3s(pct(vals, 0.5)), r3s(pct(vals, 0.95))
        counts[name] = len(vals)
    h["count"] = counts
    partial = collections.OrderedDict()
    for name, upto in SPANS:
        if counts[name]:
            continue
        for start in STAGE_IDS[1:STAGE_IDS.index(upto) + 1]:
            vals = [v for v in (chain(j, upto, start) for j in joined) if v is not None]
            if vals:
                partial[name] = {"from": start, "p50_s": r3s(pct(vals, 0.5)), "p95_s": r3s(pct(vals, 0.95)),
                                 "count": len(vals)}
                break
    if partial:
        h["partial"] = partial
    gen = collections.OrderedDict()
    for name in ("ts", "commit", "seen", "ts_read"):
        vals = [j.gen[name] for j in joined if name in j.gen]
        gen["%s_p50_s" % name], gen["%s_p95_s" % name] = r3s(pct(vals, 0.5)), r3s(pct(vals, 0.95))
        gen.setdefault("count", {})[name] = len(vals)
    h["from_generator"] = gen
    return h


def coverage(joined, tol):
    diffs = []
    for j in joined:
        total = chain(j, "S13")
        seen = j.row.get("own_submit_p50_ms")
        if total is not None and seen:
            diffs.append(total - float(seen))
    within = sum(1 for d in diffs if abs(d) <= tol)
    return collections.OrderedDict([
        ("blocks", len(joined)), ("checked", len(diffs)), ("within", within),
        ("pct", round(100.0 * within / len(diffs), 1) if diffs else None), ("tolerance_ms", tol),
        ("diff_p50_ms", r1(pct(diffs, 0.5))), ("diff_p95_ms", r1(pct([abs(d) for d in diffs], 0.95)))])


def in_window(j, win, boundaries, excl_glob, bsecs):
    name, start, end = win
    if j.ts is None:
        return name == "all"
    if name != "all" and not (start <= float(j.ts) < end):
        return False
    if excl_glob and fnmatch.fnmatch(name, excl_glob):
        return not any(abs(float(j.ts) - b) <= bsecs for b in boundaries)
    return True


def events_in(log, start, end):
    """Per event: {lines, sum} of the lines in [start, end) (every line when start is None); an event
    logged with a cause (digests_resent) also gets by_cause {cause: {lines, sum}}."""
    out = {}
    for k, evs in sorted(log.events.items()):
        sel = [e for e in evs if start is None or start * 1000.0 <= e[0] < end * 1000.0]
        out[k] = {"lines": len(sel), "sum": sum(e[1] for e in sel)}
        if k == "digests_resent":
            by = collections.defaultdict(lambda: {"lines": 0, "sum": 0})
            for e in sel:
                by[e[2]]["lines"] += 1
                by[e[2]]["sum"] += e[1]
            out[k]["by_cause"] = collections.OrderedDict(sorted(by.items()))
    return out


def build_report(run, nodes, windows, boundaries, a):
    doc = collections.OrderedDict()
    doc["schema"] = "stage-latency/v1"
    doc["run"] = run
    doc["windows"] = collections.OrderedDict()
    for name, s, e in windows:
        w = {"start": iso(s), "end": iso(e)} if name != "all" else {"start": None, "end": None}
        w["boundaries_excluded"] = bool(a.exclude_boundaries and fnmatch.fnmatch(name, a.exclude_boundaries))
        doc["windows"][name] = w
    doc["stages"] = collections.OrderedDict(STAGES)
    doc["nodes"], doc["pooled"] = collections.OrderedDict(), collections.OrderedDict()
    doc["headline"], doc["headline_by_node"] = collections.OrderedDict(), collections.OrderedDict()
    doc["aux"] = {"pooled": collections.OrderedDict(), "nodes": collections.OrderedDict()}
    doc["events"] = collections.OrderedDict()
    doc["coverage"] = {"pooled": collections.OrderedDict(), "nodes": collections.OrderedDict()}
    doc["sources"] = collections.OrderedDict()
    pooled = collections.defaultdict(list)
    for name, log, blocks, authority, joined in nodes:
        reasons = {s: why_unmeasured(s, log, blocks.columns) for s in STAGE_IDS}
        doc["sources"][name] = collections.OrderedDict([
            ("logs", log.files), ("lines_read", log.lines), ("truncated_at_max_lines", log.truncated),
            ("blasters", blocks.files), ("authority", authority), ("f1_build", log.f1_build),
            ("own_blocks", len(joined)), ("block_columns_t1", "batch_digest_prefix" in blocks.columns),
            ("digests_unparsed", log.digest_unparsed),
            ("messages", collections.OrderedDict((m, log.msg_count[m]) for m in MSGS))])
        for k in ("nodes", "headline_by_node", "events"):
            doc[k][name] = collections.OrderedDict()
        doc["aux"]["nodes"][name] = collections.OrderedDict()
        doc["coverage"]["nodes"][name] = collections.OrderedDict()
        for win in windows:
            sel = [j for j in joined if in_window(j, win, boundaries, a.exclude_boundaries, a.boundary_secs)]
            pooled[win[0]].extend(sel)
            doc["nodes"][name][win[0]] = stage_table(sel, reasons)
            doc["headline_by_node"][name][win[0]] = headline(sel)
            doc["aux"]["nodes"][name][win[0]] = aux_table(sel)
            doc["coverage"]["nodes"][name][win[0]] = coverage(sel, a.coverage_tolerance_ms)
            doc["events"][name][win[0]] = events_in(log, *((None, None) if win[0] == "all" else win[1:]))
    for name, _, _ in windows:
        doc["pooled"][name] = stage_table(pooled[name])
        doc["headline"][name] = headline(pooled[name])
        doc["aux"]["pooled"][name] = aux_table(pooled[name])
        doc["coverage"]["pooled"][name] = coverage(pooled[name], a.coverage_tolerance_ms)
    return doc


# ---------------------------------------------------------------- markdown

def cell(v):
    if v is None:
        return "–"
    if isinstance(v, float) and v != int(v):
        return "%.3f" % v if abs(v) < 100 else "%.1f" % v
    return "%d" % v


def to_markdown(doc):
    out = ["# Stage latency: %s" % doc["run"], ""]
    for name, s in doc["sources"].items():
        out.append("- %s: authority %s, %s own blocks, %d log lines%s from %s; generator %s; F1 build: %s." % (
            name, (s["authority"] or "unknown")[:12], s["own_blocks"], s["lines_read"],
            " (stopped at --max-lines)" if s["truncated_at_max_lines"] else "", ", ".join(s["logs"]) or "-",
            ", ".join(os.path.basename(b) for b in s["blasters"]) or "-", "yes" if s["f1_build"] else "no"))
    out += ["", "## Headline (seconds; chain = summed stages, gen = from the generator's own_submit_p50_ms)", "",
            "| window | ts p50 | ts p95 | commit p50 | commit p95 | seen p50 | seen p95 | gen ts p50 | gen ts p95 "
            "| gen commit p50 | gen commit p95 | gen seen p50 | gen seen p95 | coverage |",
            "|---|" + "---:|" * 13]
    partial = []
    for w, h in doc["headline"].items():
        g = h["from_generator"]
        cov = doc["coverage"]["pooled"][w]
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            w, cell(h["ts_p50_s"]), cell(h["ts_p95_s"]), cell(h["commit_p50_s"]), cell(h["commit_p95_s"]),
            cell(h["seen_p50_s"]), cell(h["seen_p95_s"]), cell(g["ts_p50_s"]), cell(g["ts_p95_s"]),
            cell(g["commit_p50_s"]), cell(g["commit_p95_s"]), cell(g["seen_p50_s"]), cell(g["seen_p95_s"]),
            "–" if cov["pct"] is None else "%s %% of %d" % (cell(cov["pct"]), cov["checked"])))
        for span, p in (h.get("partial") or {}).items():
            partial.append("- %s: no block has every stage of `%s`; from %s on: p50 %s s, p95 %s s (%d blocks)." % (
                w, span, p["from"], cell(p["p50_s"]), cell(p["p95_s"]), p["count"]))
    out += [""] + partial + ([""] if partial else [])
    stages = doc["stages"]
    for w, win in doc["windows"].items():
        span = "all blocks" if win["start"] is None else "%s → %s" % (win["start"], win["end"])
        out += ["## %s: %s%s" % (w, span, ", epoch boundaries excluded" if win["boundaries_excluded"] else ""), "",
                "| stage | what | n | p50 ms | p95 ms | unmeasured | basis |", "|---|---|---:|---:|---:|---:|---|"]
        for s, r in doc["pooled"][w].items():
            basis = ", ".join("%s %d" % kv for kv in (r.get("basis") or {}).items())
            out.append("| %s | %s | %d | %s | %s | %d | %s |" % (s, stages[s], r["count"], cell(r["p50_ms"]),
                                                                cell(r["p95_ms"]), r["unmeasured"], basis))
        if len(doc["nodes"]) > 1:
            names = list(doc["nodes"])
            out += ["", "| stage | " + " | ".join("%s p50" % n for n in names) + " |",
                    "|---|" + "---:|" * len(names)]
            for s in stages:
                out.append("| %s | %s |" % (s, " | ".join(cell(doc["nodes"][n][w][s]["p50_ms"]) for n in names)))
        miss = set()
        for n, per in doc["nodes"].items():
            for s, r in per[w].items():
                for why in r.get("missing") or []:
                    miss.add("%s: %s" % (s, why))
        if miss:
            out += [""] + ["- unmeasured %s" % m for m in sorted(miss, key=lambda x: (STAGE_IDS.index(x.split(":")[0]), x))]
        aux = doc["aux"]["pooled"][w]
        if aux:
            out += ["", "Aux (p50 / p95): " + "; ".join("%s %s / %s" % (k, cell(v["p50"]), cell(v["p95"]))
                                                       for k, v in aux.items()) + "."]
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- inputs

def node_logs(logs_dir, node, glob):
    pat = (glob or "{node}-unit-stdout*.log*").replace("{node}", node)
    files = [f for f in sorted(os.listdir(logs_dir)) if fnmatch.fnmatch(f, pat)]
    if not files and glob is None:
        files = [f for f in sorted(os.listdir(logs_dir)) if fnmatch.fnmatch(f, node + "-*.log*")
                 and "stderr" not in f and not f.endswith((".logspan", ".pulled"))]
    picked, firsts = [], set()
    for f in files:
        p = os.path.join(logs_dir, f)
        head = first_line(p)
        if head in firsts:
            continue
        firsts.add(head)
        picked.append((ts_ms(head) or 0.0, f, p))
    return [p for _, _, p in sorted(picked)]


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.splitlines()[2:]))
    p.add_argument("--run-dir", help="results/<run>: logs/, blasters/, blast-<i>-<UTC>/blasters/, manifest.json")
    p.add_argument("--logs", help="directory of node logs (instead of --run-dir)")
    p.add_argument("--blasters", action="append", default=[], help="directory of tn-blast results (repeatable)")
    p.add_argument("--manifest", help="manifest.json for blasts[] names (default <run-dir>/manifest.json)")
    p.add_argument("--windows", metavar="FILE", help="named windows with ISO start/end")
    p.add_argument("--node", action="append", default=[], metavar="INST", help="only this node (repeatable)")
    p.add_argument("--log-glob", help="log file names per node, {node} replaced (default {node}-unit-stdout*.log*, "
                                      "else every {node}-*.log* but stderr)")
    p.add_argument("--authority", action="append", default=[], metavar="NODE=ID",
                   help="the node's authority id when its log has no `consensus output ready authority=`")
    eb = p.add_mutually_exclusive_group()
    eb.add_argument("--exclude-boundaries", nargs="?", const="light*", metavar="GLOB",
                    help="drop blocks near an epoch boundary from the windows matching GLOB (default, and without "
                         "GLOB: light*)")
    eb.add_argument("--keep-boundaries", action="store_const", const=None, dest="exclude_boundaries",
                    help="keep the blocks near an epoch boundary in every window (the light* windows too)")
    # On by default for the light windows only (the floor), off for the load and the rest.
    p.set_defaults(exclude_boundaries="light*")
    p.add_argument("--boundary-secs", type=float, default=30.0, help="half-width of the exclusion (default 30)")
    p.add_argument("--coverage-tolerance-ms", type=float, default=250.0, help="sanity tolerance (default 250)")
    p.add_argument("--max-lines", type=int, help="read at most N lines per node (tests, quick looks)")
    p.add_argument("--out-json", metavar="PATH")
    p.add_argument("--out-md", metavar="PATH")
    p.add_argument("--out-blocks", metavar="PATH", help="one JSON line per joined own block (stages, basis, aux)")
    p.add_argument("--format", choices=("md", "json"), default="md", help="stdout format without --out-*")
    a = p.parse_args(argv)
    if bool(a.run_dir) == bool(a.logs):
        p.error("give --run-dir, or --logs with --blasters")
    if a.logs and not a.blasters:
        p.error("--logs needs --blasters")
    if a.max_lines is not None and a.max_lines <= 0:
        p.error("--max-lines must be positive")
    a.authorities = {}
    for item in a.authority:
        node, sep, ident = item.partition("=")
        if not sep or not node or not ident:
            p.error("--authority wants NODE=ID, got %r" % item)
        a.authorities[node] = ident
    return a


def main(argv=None):
    a = parse_args(argv)
    try:
        if a.run_dir:
            logs_dir = os.path.join(a.run_dir, "logs")
            dirs = [(None, os.path.join(a.run_dir, "blasters"))]
            for f in sorted(os.listdir(a.run_dir)):
                m = BLAST_DIR_RE.match(f)
                if m and os.path.isdir(os.path.join(a.run_dir, f, "blasters")):
                    dirs.append((int(m.group(1)), os.path.join(a.run_dir, f, "blasters")))
            manifest_path = a.manifest or os.path.join(a.run_dir, "manifest.json")
            run = os.path.basename(os.path.normpath(a.run_dir))
        else:
            logs_dir = a.logs
            dirs = []
            for d in a.blasters:
                m = BLAST_DIR_RE.match(os.path.basename(os.path.dirname(os.path.normpath(d))))
                dirs.append((int(m.group(1)) if m else None, d))
            manifest_path, run = a.manifest, None
        manifest = None
        if manifest_path and os.path.isfile(manifest_path):
            with open(manifest_path) as fh:
                manifest = json.load(fh)
        groups, per_node, boundaries = [], collections.OrderedDict(), set()
        for index, d in dirs:
            if not os.path.isdir(d):
                continue
            docs = load_blasters(d)
            if docs:
                groups.append((index, docs))
            for path, doc in docs:
                run = run or (doc.get("run") or {}).get("run_id")
                cols = list((doc.get("blocks") or {}).get("columns") or [])
                if "closes_epoch" in cols:
                    i_c, i_t = cols.index("closes_epoch"), cols.index("timestamp")
                    boundaries.update(float(r[i_t]) for r in (doc["blocks"].get("rows") or []) if r[i_c])
                node = blaster_node(doc)
                if node and (not a.node or node in a.node):
                    per_node.setdefault(node, Blocks()).add(doc, path)
        windows = windows_from_file(a.windows) if a.windows else derived_windows(groups, manifest)
        if not any(w[0] == "all" for w in windows):
            windows.append(("all", 0.0, 0.0))
        nodes = []
        for node, blocks in per_node.items():
            files = node_logs(logs_dir, node, a.log_glob) if os.path.isdir(logs_dir) else []
            if not files:
                continue
            log = NodeLog(node)
            for f in files:
                if a.max_lines is not None and log.lines >= a.max_lines:
                    log.truncated = True
                    break
                log.read(f, a.max_lines)
            authority = a.authorities.get(node) or (log.auth.most_common(1)[0][0] if log.auth else None)
            nodes.append((node, log, blocks, authority, join_node(log, blocks, authority)))
        if not nodes:
            print("stage-latency: no node has both a log in %s and a generator file%s" % (
                logs_dir, " (--node %s)" % ",".join(a.node) if a.node else ""), file=sys.stderr)
            return 2
        doc = build_report(run or "?", nodes, windows, sorted(boundaries), a)
    except (OSError, ValueError, EOFError, KeyError) as e:
        print("stage-latency: %s" % e, file=sys.stderr)
        return 1
    md = to_markdown(doc)
    if a.out_json:
        with open(a.out_json, "w") as fh:
            json.dump(doc, fh, indent=1)
            fh.write("\n")
    if a.out_md:
        with open(a.out_md, "w") as fh:
            fh.write(md + "\n")
    if a.out_blocks:
        with open(a.out_blocks, "w") as fh:
            for node, _, _, _, joined in nodes:
                for j in joined:
                    fh.write(json.dumps(collections.OrderedDict([
                        ("node", node), ("number", j.number), ("epoch", j.row.get("epoch")),
                        ("round", j.row.get("round")), ("timestamp", j.ts), ("tx_count", j.row.get("tx_count")),
                        ("stages", {k: r1(v) for k, v in j.st.items()}), ("basis", j.basis), ("aux", j.aux),
                        ("generator", {k: r1(v) for k, v in j.gen.items()})])) + "\n")
    if not a.out_json and not a.out_md:
        print(json.dumps(doc, indent=1) if a.format == "json" else md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
