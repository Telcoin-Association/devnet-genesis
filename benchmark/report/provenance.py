#!/usr/bin/env python3
"""Node build provenance for a benchmark run, read from the run's saved node logs.

Every telcoin-network node logs, each time it starts:

    telcoin-network <version> (<40-hex git sha>) starting

and, while it loads its configuration, parameter lines such as

    Max header delay set to 3000 ms
    Min header delay set to 1000 ms
    Max batch delay set to 1000 ms
    Vote timeout set to <N> ms          (later builds; the 29 Sep 2026 baseline does not log it)

plus, on builds that have one, a fork-schedule line, classified (same labels as the image
probe), first rule that applies:

    ... fork schedule (adiri) ...                                  -> "adiri-schedule"
    fork schedule: <forks incl. subsecond_timestamp> active from genesis
                                                                   -> "subsecond-from-genesis"
    any other "fork schedule:" line (the 29 Sep 2026 baseline: "fork schedule: seed_signature,
    multi_workers, prevrandao, and leader_seeded_ordering active from genesis")
                                                                   -> "pre-subsecond"
    no fork-schedule line                                          -> None

The raw text of the last such line is kept in scan_run()'s "fork_schedule_line".

Bench-6 images also log, once per start after parameters.yaml is loaded, the node switch line

    message="node switches" quorum_exec_block=false ... parent_grace=150ms ...   (target node::switches)

with one key=value field per switch of benchmark/arms/switches.tsv that the image knows, named as
its parameters.yaml key, values as YAML scalars. scan_run() attaches each one to the start it
follows in the same file (start["switches"], only on starts that logged one), and check() compares
it with the switch state the manifest says was in force at that start (check_switches()). A run
none of whose starts logged the line and whose image contract does not require it (benches 3-5)
is checked exactly as before.

Lines may be logfmt (`ts=... level=... message="..."`, what the bench nodes write), JSON
(`--log.stdout.format json`: `fields.message` / `message` / `msg`, `timestamp` / `ts` / `time`)
or plain text with an optional leading ISO timestamp. ANSI colour codes are stripped.

The run directory's logs/ holds, per instance (see bench-lib.sh, bench_pull_node_logs):
    <inst>-telcoin.log.gz                       current container log
    <inst>-telcoin-<stamp>.log.gz               a second pull of the current container log
    <inst>-telcoin-<label>-<stamp>.log.gz       log saved before a kill/restart/pause
    <inst>-unit-{stdout,stderr}[-<stamp>].log.gz  the systemd unit's append files
    <inst>-unit-<stream>[-<stamp>].rotated-<N>.log.gz  a generation logrotate moved aside on the
                                                node (the stamp only when that name was taken)
The unit files repeat the container logs' lines, so scan_run() drops repeated starts (same
instance, timestamp, version and sha). Other files in logs/ (deploy-*, blast-*, create-*) are
not node logs and are skipped.

Module use (the directory is not a package):
    sys.path.insert(0, "<repo>/benchmark/report"); import provenance

CLI:
    python3 provenance.py --run-dir DIR [--expect-sha SHA] [--update-manifest] [--json]
Exit 0 when the check passes, 1 when it does not (or on a usage/IO error), 2 when no node start
line was found at all. --update-manifest writes the check result to DIR/manifest.json as
"node_startup_check" (atomic replace; every other key, its order and the file mode kept).

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import gzip
import json
import os
import re
import stat
import sys
import tempfile
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

# --- patterns ------------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ISO_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
# logfmt: a quoted value (backslash escapes) or a bare one.
_LOGFMT_MSG_RE = re.compile(r'(?:^|\s)(?:message|msg)=("(?:[^"\\]|\\.)*"|\S+)')
_LOGFMT_TS_RE = re.compile(r"(?:^|\s)(?:ts|time|timestamp)=(\"[^\"]*\"|\S+)")

_START_RE = re.compile(
    r"telcoin-network\s+(?P<version>\S+)\s+\((?P<sha>[^()\s]+)\)\s+starting\b"
)
_PARAM_RE = re.compile(
    r"\b(?P<name>max header delay|min header delay|max batch delay|vote timeout)"
    r"\s+set\s+to\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|milliseconds|millis|s|secs|seconds)?\b",
    re.IGNORECASE,
)
_PARAM_KEYS = {
    "max header delay": "max_header_delay_ms",
    "min header delay": "min_header_delay_ms",
    "max batch delay": "max_batch_delay_ms",
    "vote timeout": "vote_timeout_ms",
}
PARAM_KEYS = ("max_header_delay_ms", "min_header_delay_ms", "max_batch_delay_ms", "vote_timeout_ms")
# Keys check() compares against manifest["consensus_parameters"] (when both sides have them).
_CHECKED_PARAM_KEYS = PARAM_KEYS

# subsecond_timestamp listed among the forks that are "active from genesis": followed by
# words, commas and spaces only up to that phrase, so "... active from genesis;
# subsecond_timestamp at epoch 5" does not count.
_SUBSECOND_RE = re.compile(r"\bsubsecond_timestamp\b[\w\s,]*?\bactive from genesis", re.IGNORECASE)
_ADIRI_RE = re.compile(r"fork schedule\s*\(adiri\)", re.IGNORECASE)
_FORK_COLON_RE = re.compile(r"fork schedule\s*:", re.IGNORECASE)

FORK_ADIRI = "adiri-schedule"
FORK_SUBSECOND = "subsecond-from-genesis"
FORK_PRE_SUBSECOND = "pre-subsecond"

# The node switch line's message (bench 6; one line per start, target node::switches).
SWITCH_MESSAGE = "node switches"

# Byte substrings a line must contain to be worth parsing (superset of the patterns above).
_CANDIDATE_MARKERS = (b"starting", b"et to", b"ET TO", b"chedule", b"CHEDULE", b"node switches")

# Node log file names (bench-lib.sh). The instance part is greedy (the last "-telcoin" /
# "-unit-" starts the suffix), so an instance name containing "-telcoin" still parses; a saved
# log's label is always followed by a UTC stamp. A unit log rotated on the node and pulled at
# teardown keeps its rotation number: <inst>-unit-<stream>.rotated-<N>.log.gz, or
# <inst>-unit-<stream>-<stamp>.rotated-<N>.log.gz when the first name was already taken.
_STAMP = r"\d{8}T\d{6}Z"
_NODE_LOG_RE = re.compile(
    r"^(?P<inst>[A-Za-z0-9][A-Za-z0-9._-]*)-"
    r"(?:telcoin(?:-[a-z0-9-]+?-" + _STAMP + r")?(?:-" + _STAMP + r")*"
    r"|unit-[a-z]+(?:-" + _STAMP + r")*(?:\.rotated-[0-9]+)?)"
    r"\.log(?:\.gz)?$"
)


# --- files and lines -----------------------------------------------------------------------


def node_log_files(run_dir: str) -> List[str]:
    """Sorted paths of the node logs in <run_dir>/logs: *.log.gz and *.log files named like a
    node log (<inst>-telcoin*.log[.gz], <inst>-unit-<stream>*[.rotated-<N>].log[.gz]). Non-node
    logs in the same directory (deploy-*, blast-*, create-*, rescue-*) and dot-named temp files
    are left out."""
    logs = os.path.join(run_dir, "logs")
    paths = glob.glob(os.path.join(logs, "*.log.gz")) + glob.glob(os.path.join(logs, "*.log"))
    return sorted(p for p in paths if os.path.isfile(p) and _NODE_LOG_RE.match(os.path.basename(p)))


def iter_lines(path: str) -> Iterator[str]:
    """Yield the text lines (no trailing newline) of a .gz or plain file; undecodable bytes are
    replaced. A truncated gzip raises EOFError once its readable lines are exhausted."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:  # type: ignore[operator]
        for line in fh:
            yield line.rstrip("\r\n")


def _iter_candidate_lines(path: str) -> Iterator[str]:
    """Like iter_lines, but decodes and yields only lines that may hold a start, parameter or
    fork-schedule message. Node logs run to gigabytes; this keeps a scan fast."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:  # type: ignore[operator]
        for raw in fh:
            for marker in _CANDIDATE_MARKERS:
                if marker in raw:
                    yield raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    break


def instance_of(path: str) -> str:
    """The instance name from a node log's file name, e.g. "bench-validator-05" for
    logs/bench-validator-05-telcoin-pre-kill-20260929T181157Z.log.gz."""
    name = os.path.basename(path)
    m = _NODE_LOG_RE.match(name)
    if m:
        return m.group("inst")
    for sep in ("-telcoin", "-unit-"):
        if sep in name:
            return name.rsplit(sep, 1)[0]
    for ext in (".gz", ".log"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


# --- line parsing --------------------------------------------------------------------------


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            out = json.loads(value)
            if isinstance(out, str):
                return out
        except ValueError:
            pass
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_line(line: str) -> Tuple[Optional[str], str]:
    """(timestamp or None, message text) for one log line in JSON, logfmt or plain form."""
    line = _ANSI_RE.sub("", line).strip()
    if line.startswith("{"):
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            fields = obj.get("fields") if isinstance(obj.get("fields"), dict) else {}
            msg = fields.get("message") or obj.get("message") or obj.get("msg")
            ts = obj.get("timestamp") or obj.get("ts") or obj.get("time")
            return (str(ts) if ts else None, str(msg) if msg is not None else line)
    ts = None
    m = _LOGFMT_TS_RE.search(line)
    if m:
        ts = _unquote(m.group(1))
    else:
        m = _ISO_RE.match(line)
        if m:
            ts = m.group(1)
    m = _LOGFMT_MSG_RE.search(line)
    if m:
        return ts, _unquote(m.group(1))
    return ts, line


def parse_startups(lines: Iterable[str], instance: str) -> List[Dict[str, Any]]:
    """One dict per "telcoin-network <version> (<sha>) starting" line, in line order:
    {"instance", "ts" (ISO string or None), "version", "sha" (lower case)}."""
    out = []  # type: List[Dict[str, Any]]
    for line in lines:
        if "starting" not in line:
            continue
        ts, msg = _parse_line(line)
        m = _START_RE.search(msg)
        if m:
            out.append(
                {"instance": instance, "ts": ts, "version": m.group("version"), "sha": m.group("sha").lower()}
            )
    return out


def _param_events(lines: Iterable[str]) -> Iterator[Tuple[Optional[str], str, int]]:
    """(ts, key, value in ms) for every parameter line, in line order."""
    for line in lines:
        if "et to" not in line and "ET TO" not in line:
            continue
        ts, msg = _parse_line(line)
        for m in _PARAM_RE.finditer(msg):
            value = float(m.group("value"))
            unit = (m.group("unit") or "ms").lower()
            if unit in ("s", "secs", "seconds"):
                value *= 1000.0
            yield ts, _PARAM_KEYS[m.group("name").lower()], int(round(value))


def parse_params(lines: Iterable[str]) -> Dict[str, int]:
    """{"max_header_delay_ms", "min_header_delay_ms", "max_batch_delay_ms", "vote_timeout_ms"}
    as ints, from lines like "Max header delay set to 3000 ms". Keys never logged are omitted;
    a key logged several times keeps its last value."""
    out = {}  # type: Dict[str, int]
    for _ts, key, value in _param_events(lines):
        out[key] = value
    return out


def _fork_events(lines: Iterable[str]) -> Iterator[Tuple[Optional[str], Optional[str], str]]:
    """(ts, label, message) for every fork-schedule line, in line order (rules in the module
    docstring)."""
    for line in lines:
        if "chedule" not in line and "CHEDULE" not in line:
            continue
        ts, msg = _parse_line(line)
        if _ADIRI_RE.search(msg):
            label = FORK_ADIRI
        elif _FORK_COLON_RE.search(msg):
            label = FORK_SUBSECOND if _SUBSECOND_RE.search(msg) else FORK_PRE_SUBSECOND
        else:
            continue
        yield ts, label, msg


def parse_fork_schedule(lines: Iterable[str]) -> Optional[str]:
    """The last fork-schedule line's label: "adiri-schedule", "subsecond-from-genesis" or
    "pre-subsecond"; None when no fork-schedule line is present."""
    label = None
    for _ts, lab, _msg in _fork_events(lines):
        if lab is not None:
            label = lab
    return label


# logfmt fields: key=value, the value quoted (backslash escapes) or bare.
_LOGFMT_FIELD_RE = re.compile(r'(?:^|\s)([A-Za-z_][A-Za-z0-9_.]*)=("(?:[^"\\]|\\.)*"|\S*)')
_SWITCH_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Line keys that are never a switch: the logfmt / JSON envelope.
_SWITCH_META_KEYS = frozenset(("ts", "time", "timestamp", "level", "target", "span", "span_path", "spans",
                               "message", "msg", "fields", "filename", "line_number", "thread_id", "thread_name"))


def _switch_text(value: Any) -> str:
    """A logged switch value as text: true / false for a JSON boolean, digits for a JSON integer,
    a string without the extra quotes a Debug-formatted value carries."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else repr(value)
    text = str(value).strip()
    for _layer in range(2):  # the logfmt quotes, then the Debug quotes of a string field
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            text = _unquote(text).strip()
    return text


def parse_switch_line(line: str) -> Optional[Tuple[Optional[str], Dict[str, str]]]:
    """(timestamp or None, {switch key: value as text}) for a node switch line (message exactly
    "node switches") in logfmt, JSON or plain form; None for any other line. Fields are the ones
    after the message (logfmt, plain) or the event's fields (JSON), envelope keys left out."""
    if SWITCH_MESSAGE not in line:
        return None
    ts, msg = _parse_line(line)
    clean = _ANSI_RE.sub("", line).strip()
    pairs = []  # type: List[Tuple[str, Any]]
    if clean.startswith("{"):
        try:
            obj = json.loads(clean)
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or str(msg).strip() != SWITCH_MESSAGE:
            return None
        fields = obj.get("fields") if isinstance(obj.get("fields"), dict) else obj
        pairs = list(fields.items())
    else:
        m = _LOGFMT_MSG_RE.search(clean)
        if m:
            if _unquote(m.group(1)).strip() != SWITCH_MESSAGE:
                return None
            rest = clean[m.end():]
        else:
            # Plain text: "<ts> INFO node::switches: node switches key=value ...".
            at = clean.find(SWITCH_MESSAGE)
            rest = clean[at + len(SWITCH_MESSAGE):]
            if rest[:1] not in ("", " ", "\t"):
                return None
        pairs = [(k, v) for k, v in _LOGFMT_FIELD_RE.findall(rest)]
    values = {}  # type: Dict[str, str]
    for key, value in pairs:
        key = str(key)
        if key in _SWITCH_META_KEYS or not _SWITCH_KEY_RE.match(key) or isinstance(value, (dict, list)):
            continue
        values[key] = _switch_text(value)
    return ts, values


# --- run scan and check --------------------------------------------------------------------


def _chrono_key(ts: Optional[str], seq: int) -> Tuple[int, str, int]:
    # Lines without a timestamp sort before timestamped ones, then by read order.
    return (0 if ts is None else 1, ts or "", seq)


def _starts_and_switches(lines: List[str], instance: str, seen: Dict[Tuple[Any, ...], Dict[str, Any]],
                         starts: List[Dict[str, Any]]) -> None:
    """parse_startups() over one file's lines, appending new starts to `starts` (a start already in
    `seen`, the same instance / ts / version / sha from another file, is not added again), and
    each node switch line's values to the start it follows in this file as start["switches"]
    (the first one per start; a line before any start of the file is not attached)."""
    current = None  # type: Optional[Dict[str, Any]]
    for line in lines:
        if "starting" in line:
            got = parse_startups([line], instance)
            if got:
                s = got[0]
                key = (s["instance"], s["ts"], s["version"], s["sha"])
                if s["ts"] is not None and key in seen:
                    current = seen[key]
                    continue
                seen[key] = s
                starts.append(s)
                current = s
                continue
        if current is not None and "switches" not in current:
            sw = parse_switch_line(line)
            if sw is not None:
                current["switches"] = sw[1]


def scan_run(run_dir: str) -> Dict[str, Any]:
    """Scan every node log of a run. Returns
    {"starts": [start dicts, repeats across files dropped, sorted by instance then ts; a start
                followed by a node switch line carries its values as "switches"],
     "shas": sorted unique start shas,
     "params": {key: chronologically last value},
     "fork_schedule": label of the chronologically last fork-schedule line, or None,
     "files": [scanned paths],
     plus detail: "instances" (every instance with a node log, sorted), "param_values"
     ({key: sorted unique values}), "param_events" ([{"instance", "ts", "key", "value"}], every
     parameter line per instance, repeats across files dropped, chronological),
     "fork_schedules" (sorted unique labels), "fork_schedule_line" (that line's message, or None),
     "unreadable" ([{"file", "error"}] for files that could not be read to the end)}."""
    files = node_log_files(run_dir)
    starts = []  # type: List[Dict[str, Any]]
    seen = {}  # type: Dict[Tuple[Any, ...], Dict[str, Any]]
    params_ev = []  # type: List[Tuple[Tuple[int, str, int], str, int]]
    inst_ev = []  # type: List[Tuple[Tuple[int, str, int], Dict[str, Any]]]
    seen_ev = set()
    fork_ev = []  # type: List[Tuple[Tuple[int, str, int], Optional[str], str]]
    instances = set()
    unreadable = []  # type: List[Dict[str, str]]
    seq = 0
    for path in files:
        inst = instance_of(path)
        instances.add(inst)
        lines = []  # type: List[str]
        try:
            for line in _iter_candidate_lines(path):
                lines.append(line)
        except (OSError, EOFError, ValueError) as exc:
            unreadable.append({"file": path, "error": "%s: %s" % (type(exc).__name__, exc)})
        _starts_and_switches(lines, inst, seen, starts)
        for ts, key, value in _param_events(lines):
            seq += 1
            params_ev.append((_chrono_key(ts, seq), key, value))
            ident = (inst, ts, key, value)
            if ts is not None and ident in seen_ev:
                continue
            seen_ev.add(ident)
            inst_ev.append((_chrono_key(ts, seq), {"instance": inst, "ts": ts, "key": key, "value": value}))
        for ts, label, msg in _fork_events(lines):
            seq += 1
            fork_ev.append((_chrono_key(ts, seq), label, msg))

    starts.sort(key=lambda s: (s["instance"], s["ts"] or ""))
    params = {}  # type: Dict[str, int]
    param_values = {}  # type: Dict[str, List[int]]
    for _k, key, value in sorted(params_ev, key=lambda e: e[0]):
        params[key] = value
        if value not in param_values.setdefault(key, []):
            param_values[key].append(value)
    fork_ev.sort(key=lambda e: e[0])
    labels = [lab for _k, lab, _m in fork_ev if lab is not None]
    return {
        "starts": starts,
        "shas": sorted({s["sha"] for s in starts}),
        "params": {k: params[k] for k in PARAM_KEYS if k in params},
        "fork_schedule": labels[-1] if labels else None,
        "files": files,
        "instances": sorted(instances),
        "param_values": {k: sorted(param_values[k]) for k in PARAM_KEYS if k in param_values},
        "param_events": [e for _k, e in sorted(inst_ev, key=lambda e: e[0])],
        "fork_schedules": sorted(set(labels)),
        "fork_schedule_line": fork_ev[-1][2] if fork_ev else None,
        "unreadable": unreadable,
    }


_HEX_RE = re.compile(r"^[0-9a-f]+$")


def _sha_matches(sha: str, expected: str) -> bool:
    """Equal, or one a prefix of the other when the shorter has at least 7 hex digits."""
    sha, expected = sha.lower(), expected.lower()
    if sha == expected:
        return True
    short, full = (sha, expected) if len(sha) < len(expected) else (expected, sha)
    return len(short) >= 7 and bool(_HEX_RE.match(short)) and full.startswith(short)


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else None


# --- per-node values: consensus_parameters.overrides and param_arms ------------------------
# deploy step 9 records consensus_parameters.overrides = {<instance>: {<yaml key>: "<value as
# written>"}} (BENCH_NODE_PARAM_OVERRIDES); tools/params-apply.sh records param_arms = [{name,
# begin, end, nodes: {<instance>: {<yaml key>: "<value>"}}}]. Durations are written "500ms" / "2s".

_DUR_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*$")
_TS_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:[.,](\d+))?(Z|[+-]\d\d:?\d\d)?$")


def dur_ms(value: Any) -> Optional[int]:
    """A duration as written in parameters.yaml ("500ms", "2s", "1.5s", "2m") or a plain number
    (taken as ms) in whole milliseconds; None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    m = _DUR_RE.match(str(value)) if value is not None else None
    if not m:
        return None
    mul = {"ms": 1, None: 1, "s": 1000, "m": 60000}[m.group(2)]
    return int(round(float(m.group(1)) * mul))


def ts_epoch(ts: Any) -> Optional[float]:
    """An ISO-8601 UTC timestamp (any number of fraction digits, Z or an offset, none = UTC) as
    Unix seconds; None when it is not one."""
    m = _TS_RE.match(str(ts).strip()) if ts else None
    if not m:
        return None
    y, mo, d, h, mi, s, frac, tz = m.groups()
    try:
        dt = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    off = 0
    if tz and tz != "Z":
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        off = sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    return dt.timestamp() - off + (float("0." + frac) if frac else 0.0)


def yaml_key(key: str) -> str:
    """The parameters.yaml key of a PARAM_KEYS name: max_header_delay_ms -> max_header_delay."""
    return key[:-3] if key.endswith("_ms") else key


def per_node_values(manifest: Optional[Dict[str, Any]]) -> bool:
    """True when the manifest records per-node values: consensus_parameters.overrides or param_arms."""
    manifest = manifest or {}
    cp = manifest.get("consensus_parameters")
    ov = cp.get("overrides") if isinstance(cp, dict) else None
    arms = manifest.get("param_arms")
    return bool(isinstance(ov, dict) and any(isinstance(v, dict) and v for v in ov.values())) or \
        bool(isinstance(arms, list) and arms)


def expected_param_values(manifest: Optional[Dict[str, Any]], instance: str, key: str,
                          ts: Optional[str] = None) -> List[int]:
    """Every value <instance> may log for <key> (a PARAM_KEYS name) at <ts>, sorted: the fleet
    value (consensus_parameters.<key>), the instance's consensus_parameters.overrides entry, and
    what each param arm that began at or before <ts> set for it (every arm when <ts> is None or
    not a timestamp). An arm's values stay after its end: params-apply rewrites the node's file
    and the next arm starts from it, so a later restart still reads them."""
    manifest = manifest or {}
    cp = manifest.get("consensus_parameters") if isinstance(manifest.get("consensus_parameters"), dict) else {}
    yk = yaml_key(key)
    out = set()
    fleet = _as_int(cp.get(key))
    if fleet is not None:
        out.add(fleet)
    ov = cp.get("overrides") if isinstance(cp.get("overrides"), dict) else {}
    mine = ov.get(instance) if isinstance(ov.get(instance), dict) else {}
    v = dur_ms(mine.get(yk)) if yk in mine else None
    if v is not None:
        out.add(v)
    when = ts_epoch(ts)
    for arm in manifest.get("param_arms") or []:
        if not isinstance(arm, dict) or not isinstance(arm.get("nodes"), dict):
            continue
        begin = ts_epoch(arm.get("begin"))
        if when is not None and begin is not None and begin > when:
            continue
        mine = arm["nodes"].get(instance)
        if isinstance(mine, dict) and yk in mine:
            v = dur_ms(mine[yk])
            if v is not None:
                out.add(v)
    return sorted(out)


# manifest["instances"] roles that run a telcoin-network node (older manifests list the load
# generators there too, as role "blaster").
NODE_ROLES = ("validator", "observer")


def listed_instances(manifest: Optional[Dict[str, Any]]) -> List[str]:
    """Sorted names of the nodes a run's manifest lists: manifest["instances"][] entries whose
    role is a NODE_ROLES one. The coordinated start (manifest["coordinated_start"]) started every
    one of them; it records counts only (nodes, started), so the names come from "instances"."""
    out = set()
    for entry in (manifest or {}).get("instances") or []:
        if not isinstance(entry, dict) or entry.get("role") not in NODE_ROLES:
            continue
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            out.add(name.strip())
    return sorted(out)


# --- node switches (bench 6): the switch line of every start against the arm in force -------
# benchmark/arms/switches.tsv (columns key, type, default, arm_values, topic, optional) is the one
# list of switches; manifest param_arms[].switches holds the full state an arm file puts every
# node in, and an arm given with --set changes the switches its nodes[<instance>] entry wrote;
# before the first arm every switch is at its default, or at the value
# consensus_parameters.overrides gave that node. A `via: "prestart"` arm is in force from its
# begin, the coordinated start of deploy step 7: the stage-only start before it ran each node
# once with every switch at its default (a pre-arm start). A prestart arm without a begin (older
# manifests) counts from the first start on.

SWITCHES_TSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "arms", "switches.tsv")
_SWITCH_TSV_COLUMNS = ("key", "type", "default", "arm_values", "topic", "optional")
# A Rust Duration's Debug form ("150ms", "1.5s", "0ns", "20\u00b5s") or a YAML duration; bare = ms.
_SWITCH_DUR_RE = re.compile("^\\s*(\\d+(?:\\.\\d+)?)\\s*(ns|us|\u00b5s|ms|s|m)?\\s*$")
_SWITCH_DUR_US = {"ns": 0.001, "us": 1.0, "\u00b5s": 1.0, "ms": 1000.0, None: 1000.0, "s": 1e6, "m": 6e7}


def switch_rows(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """The rows of switches.tsv in file order: [{"key", "type" (bool | int | dur), "default",
    "optional" (bool)}]. Raises OSError, or ValueError for a file that is not the frozen format."""
    path = path or SWITCHES_TSV
    with open(path, encoding="utf-8") as fh:
        text = fh.read().splitlines()
    if not text or tuple(text[0].split("\t")) != _SWITCH_TSV_COLUMNS:
        raise ValueError("%s: the header is not %s" % (path, " ".join(_SWITCH_TSV_COLUMNS)))
    rows = []
    for n, line in enumerate(text[1:], 2):
        cells = line.split("\t")
        if len(cells) != len(_SWITCH_TSV_COLUMNS) or cells[1] not in ("bool", "int", "dur"):
            raise ValueError("%s:%d: not a switch row" % (path, n))
        rows.append({"key": cells[0], "type": cells[1], "default": cells[2], "optional": cells[5] == "yes"})
    return rows


def switch_value(kind: str, value: Any) -> Any:
    """A switch value in comparable form: True / False for a bool ("true" / "false", any case),
    a non-negative int for an int, microseconds for a dur ("150ms", "0ms", "1.5s", "0ns"; a bare
    number is ms); None when the value is not one of its type."""
    if value is None:
        return None
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        return True if text == "true" else (False if text == "false" else None)
    if kind == "int":
        v = _as_int(value)
        return v if v is not None and v >= 0 else None
    if kind == "dur":
        if isinstance(value, bool):
            return None
        m = _SWITCH_DUR_RE.match(str(value))
        return None if not m else round(float(m.group(1)) * _SWITCH_DUR_US[m.group(2)], 3)
    return None


def switch_line_required(manifest: Optional[Dict[str, Any]]) -> bool:
    """True when the image probe checked the node switch line as part of the image contract
    (a manifest node_probe.strings key holding "node switches")."""
    strings = ((manifest or {}).get("node_probe") or {}).get("strings")
    return isinstance(strings, dict) and any(SWITCH_MESSAGE in str(k) for k in strings)


def _switch_state(rows: List[Dict[str, Any]], values: Dict[str, Any]) -> Dict[str, str]:
    """Every switch of `rows` as text: the value given, else the default."""
    return {r["key"]: str(values[r["key"]]) if values.get(r["key"]) is not None else r["default"] for r in rows}


def _arms_by_begin(manifest: Dict[str, Any]) -> List[Tuple[float, int, Dict[str, Any]]]:
    """[(begin as Unix seconds, index, arm)] of manifest param_arms in begin order. An arm counts
    from its recorded begin; a `via: "prestart"` arm without a usable one (older manifests) from
    minus infinity, the first start; any other arm without one is left out."""
    arms = []  # type: List[Tuple[float, int, Dict[str, Any]]]
    for n, arm in enumerate(manifest.get("param_arms") or []):
        if not isinstance(arm, dict):
            continue
        begin = ts_epoch(arm.get("begin"))
        if begin is None and arm.get("via") == "prestart":
            begin = float("-inf")
        if begin is not None:
            arms.append((begin, n, arm))
    return sorted(arms, key=lambda a: (a[0], a[1]))


def expected_switches(manifest: Optional[Dict[str, Any]], instance: str, ts: Optional[str],
                      rows: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, str]]]:
    """[(label, full switch state)] a start of <instance> at <ts> may log, the state in force
    first. The defaults with the instance's consensus_parameters.overrides, then each param arm
    whose begin is at or before <ts> in begin order (_arms_by_begin: a `via: "prestart"` arm
    without a begin counts from the first start): an arm with a `switches` state (an arm file)
    puts every node in that state; one without (`--set`) changes only the switches its `nodes`
    entry wrote for <instance>. An arm that `failed` also allows the state before it (the node it
    stopped at may be put back by hand). Without a usable <ts>, every state the manifest names is
    allowed."""
    manifest = manifest or {}
    cp = manifest.get("consensus_parameters") if isinstance(manifest.get("consensus_parameters"), dict) else {}
    ov = cp.get("overrides") if isinstance(cp.get("overrides"), dict) else {}
    mine = ov.get(instance) if isinstance(ov.get(instance), dict) else {}
    keys = {r["key"] for r in rows}
    base = _switch_state(rows, {k: v for k, v in mine.items() if k in keys})
    when = ts_epoch(ts)
    allowed = [("the defaults" + (" with this node's overrides" if any(k in keys for k in mine) else ""), base)]
    for begin, _n, arm in _arms_by_begin(manifest):
        if isinstance(arm.get("switches"), dict):
            new = _switch_state(rows, arm["switches"])
        else:
            nodes = arm.get("nodes") if isinstance(arm.get("nodes"), dict) else {}
            wrote = nodes.get(instance) if isinstance(nodes.get(instance), dict) else {}
            wrote = {k: v for k, v in wrote.items() if k in keys and v is not None}
            if not wrote:
                continue  # this arm left the instance's switches as they were
            new = dict(allowed[0][1], **{k: str(v) for k, v in wrote.items()})
        state = ("arm %s" % arm.get("name"), new)
        if when is None:
            allowed.append(state)
            continue
        if begin > when:
            break
        allowed = [state] + ([allowed[0]] if arm.get("failed") else [])
    return allowed


def _switch_diff(rows: List[Dict[str, Any]], logged: Dict[str, str], want: Dict[str, str]) -> List[Tuple[str, str, str]]:
    """[(key, logged text or "(absent)", expected text)] for every switch the line does not match.
    A key the line lacks is fine only for an optional switch the state leaves at its default."""
    out = []
    for r in rows:
        k, kind = r["key"], r["type"]
        exp = switch_value(kind, want[k])
        if k not in logged:
            if not (r["optional"] and exp == switch_value(kind, r["default"])):
                out.append((k, "(absent)", want[k]))
            continue
        got = switch_value(kind, logged[k])
        if got is None or got != exp:
            out.append((k, logged[k], want[k]))
    return out


def check_switches(starts: List[Dict[str, Any]], manifest: Optional[Dict[str, Any]],
                   rows: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """The node switch line of every start against expected_switches(). None when no start logged
    one and the image contract does not require it (benches 3-5: nothing to check). Otherwise
    {"required", "checked" (starts compared), "matched", "missing" (starts without a line while
    the contract requires one), "problems" ([text])}, plus, when a checked start came before the
    begin of a first arm that is `via: "prestart"` (deploy step 7's stage-only start, judged
    against the defaults like any start before the first arm): "pre_arm" (how many),
    "pre_arm_off" (how many of them were not at the defaults), "pre_arm_starts" ([{"instance",
    "ts"}]) and "pre_arm_begin" (that arm's begin as the manifest records it)."""
    required = switch_line_required(manifest)
    if not required and not any(isinstance(s.get("switches"), dict) for s in starts):
        return None
    problems = []  # type: List[str]
    try:
        rows = rows if rows is not None else switch_rows()
    except (OSError, ValueError) as exc:
        return {"required": required, "checked": 0, "matched": 0, "missing": 0,
                "problems": ["node switches not checked: %s" % exc]}
    first = (_arms_by_begin(manifest or {}) or [None])[0]
    staged_until = first[0] if first is not None and first[2].get("via") == "prestart" else None
    checked = matched = pre_off = 0
    missing = []  # type: List[str]
    pre_arm = []  # type: List[Dict[str, Any]]
    bad = {}  # type: Dict[Tuple[str, str, str, str], List[str]]
    for s in starts:
        inst = s.get("instance") or "?"
        logged = s.get("switches")
        if not isinstance(logged, dict):
            if required:
                missing.append("%s at %s" % (inst, s.get("ts") or "?"))
            continue
        checked += 1
        when = ts_epoch(s.get("ts"))
        pre = staged_until is not None and when is not None and when < staged_until
        if pre:
            pre_arm.append({"instance": inst, "ts": s.get("ts")})
        allowed = expected_switches(manifest, inst, s.get("ts"), rows)
        if any(not _switch_diff(rows, logged, state) for _label, state in allowed):
            matched += 1
            continue
        if pre:
            pre_off += 1
        label = " or ".join(lab for lab, _state in allowed)
        for key, got, want in _switch_diff(rows, logged, allowed[0][1]):
            bad.setdefault((label, key, got, want), []).append("%s at %s" % (inst, s.get("ts") or "?"))
    if missing:
        problems.append("no node switches line at %d start(s), though the image contract requires one: %s"
                        % (len(missing), ", ".join(missing)))
    for (label, key, got, want) in sorted(bad):
        where = bad[(label, key, got, want)]
        shown = "lack %s" % key if got == "(absent)" else "show %s=%s" % (key, got)
        problems.append("node switches %s at %d start(s) (%s); %s sets %s=%s"
                        % (shown, len(where), ", ".join(where), label, key, want))
    out = {"required": required, "checked": checked, "matched": matched, "missing": len(missing),
           "problems": problems}  # type: Dict[str, Any]
    if pre_arm:  # only with a first prestart arm that has a begin (staged_until)
        out.update(pre_arm=len(pre_arm), pre_arm_off=pre_off, pre_arm_starts=pre_arm,
                   pre_arm_begin=first[2].get("begin"))
    return out


def check(scan: Dict[str, Any], manifest: Optional[Dict[str, Any]], expect_sha: Optional[str] = None) -> Dict[str, Any]:
    """Check a scan_run() result against the expected build and the manifest.

    ok iff (a) at least one start was found, and one for every instance the manifest lists
    (listed_instances; each one without is named: "no start line for <inst>"); (b) every start's
    sha is the expected sha (expect_sha, else manifest["node_git_sha"]; a short sha matches by
    prefix); (c) when the logs carry a fork schedule and the manifest has "node_fork_schedule",
    every logged schedule equals it; (d) when the logs carry parameters and the manifest has
    "consensus_parameters", every logged value of each parameter present on both sides equals
    the manifest's; when the manifest records per-node values (consensus_parameters.overrides or
    param_arms) and the scan has "param_events", per instance and line: the fleet value, that
    instance's override, or a value a param arm begun by then set for it
    (expected_param_values); (e) when a start logged a node switch line or the image contract
    requires one, every start's switches equal the state in force (check_switches(); its result
    is returned as "switches", and its problems are among "problems"). No expected sha at all
    fails with "no expected sha".

    Returns {"starts", "shas", "fork_schedule", "params", "expected_sha", "ok", "problems",
    "checked_at" (ISO UTC)}, plus "switches" when (e) ran."""
    manifest = manifest or {}
    starts = list(scan.get("starts") or [])
    shas = sorted({s.get("sha") for s in starts if s.get("sha")})
    params = dict(scan.get("params") or {})
    fork = scan.get("fork_schedule")
    problems = []  # type: List[str]

    # (a)
    if not starts:
        problems.append("no node start line (\"telcoin-network <version> (<sha>) starting\") in the node logs")
    # A listed node without a start line ran a build its logs cannot vouch for (the early log was
    # rotated away or never pulled): a gap, not a pass.
    expected_instances = set(listed_instances(manifest))
    started = {s.get("instance") for s in starts if s.get("instance")}
    for inst in sorted(expected_instances - started):
        problems.append("no start line for %s" % inst)

    # (b)
    expected = expect_sha if expect_sha else manifest.get("node_git_sha")
    expected = str(expected).strip().lower() if expected else None
    if not expected:
        problems.append("no expected sha (pass --expect-sha or set manifest node_git_sha)")
    elif len(expected) < 7 or not _HEX_RE.match(expected):
        problems.append("expected sha %r is not a hex git sha of at least 7 digits" % expected)
    else:
        bad = {}  # type: Dict[str, List[str]]
        for s in starts:
            sha = s.get("sha") or ""
            if not _sha_matches(sha, expected):
                bad.setdefault(sha or "<none>", []).append(s.get("instance") or "?")
        for sha in sorted(bad):
            insts = sorted(set(bad[sha]))
            problems.append(
                "%d start(s) ran sha %s, expected %s (%s)" % (len(bad[sha]), sha, expected, ", ".join(insts))
            )

    # (c)
    want_fork = manifest.get("node_fork_schedule")
    logged_forks = list(scan.get("fork_schedules") or ([fork] if fork else []))
    if logged_forks and want_fork:
        for lab in logged_forks:
            if lab != want_fork:
                problems.append("logs show fork schedule %s, manifest node_fork_schedule is %s" % (lab, want_fork))

    # (d)
    cp = manifest.get("consensus_parameters")
    events = scan.get("param_events")
    if params and isinstance(cp, dict) and events is not None and per_node_values(manifest):
        # Per instance: the fleet value, the instance's override or a param arm's value.
        bad = {}  # type: Dict[Tuple[str, int], Dict[str, List[int]]]
        for ev in events:
            key = ev.get("key")
            if key not in _CHECKED_PARAM_KEYS or key not in cp:
                continue
            if _as_int(cp.get(key)) is None:
                bad.setdefault((key, ev.get("value")), {})
                continue
            allowed = expected_param_values(manifest, ev.get("instance") or "", key, ev.get("ts"))
            if ev.get("value") not in allowed:
                bad.setdefault((key, ev.get("value")), {})[ev.get("instance") or "?"] = allowed
        for (key, v) in sorted(bad, key=lambda kv: (kv[0], str(kv[1]))):
            insts = bad[(key, v)]
            if not insts:
                problems.append("logs show %s=%s, manifest consensus_parameters.%s is %r" % (key, v, key, cp.get(key)))
                continue
            problems.append(
                "logs show %s=%s on %s; expected the fleet value, its override or a param arm's (%s)"
                % (key, v, ", ".join(sorted(insts)),
                   "; ".join("%s: %s" % (i, ", ".join(str(a) for a in insts[i])) for i in sorted(insts)))
            )
    elif params and isinstance(cp, dict):
        values = scan.get("param_values") or {}
        for key in _CHECKED_PARAM_KEYS:
            if key not in params or key not in cp:
                continue
            want = _as_int(cp.get(key))
            logged = list(values.get(key) or [params[key]])
            for v in logged:
                if want is None or v != want:
                    problems.append(
                        "logs show %s=%s, manifest consensus_parameters.%s is %r" % (key, v, key, cp.get(key))
                    )

    # (e)
    switches = check_switches(starts, manifest)
    if switches is not None:
        problems.extend(switches["problems"])

    result = {
        "starts": starts,
        "shas": shas,
        "fork_schedule": fork,
        "params": params,
        "expected_sha": expected,
        "ok": not problems,
        "problems": problems,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if switches is not None:
        result["switches"] = switches
    return result


# --- manifest and CLI ----------------------------------------------------------------------


def update_manifest(manifest_path: str, result: Dict[str, Any]) -> None:
    """Set manifest["node_startup_check"] = result in place: the file is re-read, the key set
    (other keys and their order untouched), and the new text written to a temp file beside it
    that replaces the manifest atomically, keeping its file mode."""
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if not isinstance(manifest, dict):
        raise ValueError("%s is not a JSON object" % manifest_path)
    manifest["node_startup_check"] = result
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    mode = stat.S_IMODE(os.stat(manifest_path).st_mode)
    d = os.path.dirname(os.path.abspath(manifest_path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".manifest.json.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, manifest_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _report(run_dir: str, scan: Dict[str, Any], result: Dict[str, Any]) -> str:
    lines = ["node startup check: %s" % run_dir]
    by_inst = {}  # type: Dict[str, List[Dict[str, Any]]]
    for s in scan.get("starts") or []:
        by_inst.setdefault(s["instance"], []).append(s)
    for inst in sorted(set(scan.get("instances") or []) | set(by_inst)):
        ss = by_inst.get(inst, [])
        shas = ",".join(sorted({s["sha"] for s in ss})) or "-"
        tss = sorted(s["ts"] for s in ss if s.get("ts"))
        lines.append("  %-22s starts=%-2d sha=%s first=%s" % (inst, len(ss), shas, tss[0] if tss else "-"))
    params = scan.get("params") or {}
    if params:
        shown = ["%s=%s" % (k, params[k]) for k in PARAM_KEYS if k in params]
        missing = [k for k in PARAM_KEYS if k not in params]
        varied = ["%s varies %s" % (k, v) for k, v in (scan.get("param_values") or {}).items() if len(v) > 1]
        lines.append(
            "  params: " + " ".join(shown)
            + ("  (not logged: %s)" % ", ".join(missing) if missing else "")
            + ("  [%s]" % "; ".join(varied) if varied else "")
        )
    else:
        lines.append("  params: none logged")
    raw = scan.get("fork_schedule_line")
    lines.append(
        "  fork schedule: %s%s"
        % (scan.get("fork_schedule") or "none logged", ' (last line: "%s")' % raw if raw else "")
    )
    sw = result.get("switches")
    if sw is not None:
        lines.append("  node switches: %d start(s) checked, %d matched the arm in force, %d without a line%s"
                     % (sw["checked"], sw["matched"], sw["missing"],
                        " (the image contract requires one)" if sw["required"] else ""))
        if sw.get("pre_arm"):
            lines.append("  node switches: %d start(s) before the arm began (staging), %s"
                         % (sw["pre_arm"], "%d NOT at the defaults" % sw["pre_arm_off"] if sw["pre_arm_off"]
                            else "all at the defaults"))
    for u in scan.get("unreadable") or []:
        lines.append("  warning: %s not read to the end: %s" % (u["file"], u["error"]))
    lines.append("  expected sha: %s" % (result.get("expected_sha") or "-"))
    if result["ok"]:
        lines.append("OK")
    else:
        lines.append("PROBLEMS:")
        lines.extend("  - %s" % p for p in result["problems"])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check which node build a benchmark run ran, from its node logs.")
    ap.add_argument("--run-dir", required=True, help="the run's results directory (holds logs/ and manifest.json)")
    ap.add_argument("--expect-sha", help="the expected node git sha (full or a prefix of at least 7 digits); "
                    "default: manifest node_git_sha")
    ap.add_argument("--update-manifest", action="store_true",
                    help="write the result to <run-dir>/manifest.json as node_startup_check")
    ap.add_argument("--json", action="store_true", help="print the check result as JSON")
    args = ap.parse_args(argv)

    run_dir = args.run_dir
    if not os.path.isdir(run_dir):
        print("provenance: %s is not a directory" % run_dir, file=sys.stderr)
        return 1
    manifest_path = os.path.join(run_dir, "manifest.json")
    manifest = {}  # type: Dict[str, Any]
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:
            print("provenance: cannot read %s: %s" % (manifest_path, exc), file=sys.stderr)
            return 1
        if not isinstance(manifest, dict):
            print("provenance: %s is not a JSON object" % manifest_path, file=sys.stderr)
            return 1
    elif args.update_manifest:
        print("provenance: --update-manifest but %s does not exist" % manifest_path, file=sys.stderr)
        return 1

    scan = scan_run(run_dir)
    result = check(scan, manifest, args.expect_sha)

    if args.update_manifest:
        try:
            update_manifest(manifest_path, result)
        except (OSError, ValueError) as exc:
            print("provenance: could not update %s: %s" % (manifest_path, exc), file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(_report(run_dir, scan, result))
        if args.update_manifest:
            print("manifest updated: %s (node_startup_check)" % manifest_path)

    if not result["starts"]:
        return 2
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
