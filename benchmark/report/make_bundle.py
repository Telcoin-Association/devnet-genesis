#!/usr/bin/env python3
"""Turn one private benchmark run into a scrubbed, schema-valid bundle for the public site.

A bundle is the directory ``runs/<id>/`` of the tn-benchmarks site repository:

    run.json             tn-bench-site-run/v1 (the schema is RUN_SCHEMA in the site's scrub.py)
    report.html          build-report.py output, or an archived report copied byte for byte
    series/tps-1s.json   chain TPS over the merged mixed window, at most 2000 rows

Command line::

    python3 benchmark/report/make_bundle.py --run R [--blast-index N] [--compare R2]
        [--compare-blast-index M] [--backfill F.json] [--out DIR] [--force]
        [--allow-provenance-mismatch] [--analysis-sha SHA] [--archived-report PATH]
        [--no-results] [--txgen-bench DIR]

Paths:
    results    <repo>/benchmark/results/<R>/ (read only)
    scratch    <repo>/benchmark/work/report/<R>/ (gitignored; kept after the run so a
               --compare of a later run can reuse it; --force deletes and rebuilds it). Each
               scratch dir holds a .source.json marker {run, blast_index, source, built_at}.
    tools      ${BENCH_TXGEN_REPO:-<repo>/../tn-transaction-generator}/bench, or --txgen-bench
    out        ${BENCH_SITE_REPO:-<repo>/../tn-benchmarks}/runs/<R>/, or --out. The last path
               component must be <R>. When the out dir lies inside a git checkout, that
               checkout's origin must be Telcoin-Association/tn-benchmarks.

--compare R2 builds R2's scratch from its top-level results, or from blast-<M>-*/ with
--compare-blast-index M. An existing R2 scratch is reused only when its marker names the same
blast; any other (or unmarked) R2 scratch is refused at setup, before any work, and --force
rebuilds it from the requested blast.

Pipeline, one log line per step, numbered in execution order:
    0 setup       out dir (origin must end in Telcoin-Association/tn-benchmarks[.git]), backfill
                  and compare-scratch checks.
    1 scratch     copy an allowlist (manifest.json, metrics.json, blasters/*.json, sampler/*.csv)
                  into the scratch dir, plus an empty reference-chains.json. With --blast-index N
                  the manifest, metrics and blasters come from blast-N-*/. The node logs are not
                  copied (tens of GB for a debug-filter run); step 2 reads them in place.
    2 provenance  node logs in results/<run>/logs/, read in place, vs the expected upstream sha
                  (manifest node_git_sha, else the backfill's upstream.sha). A mismatch refuses
                  here, before the slow steps, unless --allow-provenance-mismatch.
    3 tools       aggregate.py -> combined.json, derive-sizing.py -> sizing.json (cwd=scratch).
    4 scrub       scrub.scrub_inputs() -> scratch/scrubbed/.
    5 report      build-report.py in scratch/scrubbed with relative paths only
                  (--compare ../../<R2>/scrubbed, built or reused on demand). After step 7, a
                  "Certification by node" section from manifest.certification goes into the built
                  report (never an archived one); manifest.cert_failures becomes a caveat at step 8.
    6 windows     merged / all-generators windows, 5-minute blocks and the 1-s series.
    7 kpis        kpis.compute() plus the backfill's published KPIs; recovery.
    8 assemble    run.json, every RUN_SCHEMA key, nothing else.
    9 write       run.json, report.html, series/ into a staging dir next to the out dir
                  (<parent>/.<R>.tmp-<pid>/<R>; inside the site that is runs/.<R>.tmp-<pid>/<R>).
    10 gates      on the staged bundle: harness scrub.scan_dir() must be clean, then the site's
                  `build.py --check <staged path>` (out inside the site repo and build.py present)
                  or `scrub.py <staged path>`.
    11 install    the previous bundle (if any) is moved aside, the staged one moved into place,
                  and the site check runs again on <out>; if that fails the previous bundle is
                  restored. Any failure in 9-11 leaves <out> as it was and exits 1; the staging
                  dir is always removed.

--archived-report PATH copies PATH as report.html instead of running build-report.py (the
rest of the pipeline still runs). --no-results skips steps 1-7 altogether: run.json comes
from the backfill alone and the archived report is required.

Backfill JSON (a single object; every key optional unless marked; keys starting with "_" are
comments and ignored; any other unknown key is an error; a value still holding a <<...>>
placeholder refuses the build, naming the field). Backfill values only win where this
list says so; elsewhere they fill a value the run did not record.

    title, summary       text (default: a generated title/summary; required with --no-results)
    status               complete | aborted | superseded. "aborted" from manifest.abort wins.
    date                 YYYY-MM-DD; wins over the deploy date (required with --no-results)
    started_utc, ended_utc   YYYY-MM-DDTHH:MM:SSZ; used with --no-results only
    compare_to           run id; used when --compare is not given
    upstream             {sha (7-40 hex; a full sha is published, a short one only as `short`),
                          branch (wins; default null), evidence (inferred | not-recorded; used
                          when the run has no node logs), evidence_detail [text] (appended)}
    node_image           {ref, digest (sha256:<64 hex>), version, fork_schedule}: fills nulls
    generator            {sha, image_digest, analysis_sha}: fills nulls (--analysis-sha wins)
    harness              {sha, submodules {name: sha|null}}: used when the manifest has none
    fleet                {label, validators, observers, machine_type, vcpus, memory_gb,
                          disk {type, size_gb, iops, throughput_mibps}, regions [text],
                          load {blasters, machine_type, senders_each, placement}}: every key
                          given wins (disk and load merge key by key)
    chain                {chain_id, network, epoch_secs}: fills nulls
    consensus            {max_header_delay_ms, min_header_delay_ms, max_batch_delay_ms,
                          vote_timeout_ms, file, confirmed_by}: numbers fill values the run did
                          not record (a conflicting number is an error); file / confirmed_by
                          labels win. The node does not log its vote timeout, so without
                          vote_timeout_ms here run.json carries consensus: null.
    workload             {warmup_secs, mixed_secs, cooldown_secs, tx_types [text]}: fills nulls
    methodology, caveats [text]; caveats come first (as written), then the computed caveats,
                         each sentence-cased with a final period; exact duplicates are dropped
    kpis_published       [{id, label, short_label, value | range [lo, hi], unit, window|null,
                          source, method|null, provenance: "published"}], appended to the
                          computed KPIs; ids must not collide with computed ones
    recovery             {node, killed_utc, restarted_utc, rejoined_utc, catch_up_secs,
                          failed_reports}: fills null fields (noted in a caveat)
    report               {archived_from, modifications [text]}: used with --archived-report
                          (archived_from defaults to the archived file's name)

With --no-results the backfill must also carry fleet (label, validators, observers,
machine_type, disk {type, size_gb}, regions) and chain (chain_id, network); consensus and
workload are published only when the backfill gives every key, else null.

Python 3.9+, standard library only. Exit status: 0 ok, 1 refused or a gate failed, 2 usage.
"""

import argparse
import datetime
import glob
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from decimal import ROUND_HALF_UP, Decimal

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import kpis as kpis_mod  # noqa: E402
import provenance  # noqa: E402
import scrub as hscrub  # noqa: E402  (the harness-side scrubber next to this file)
import windows as win  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
RESULTS_ROOT = os.path.join(REPO_ROOT, "benchmark", "results")
WORK_ROOT = os.path.join(REPO_ROOT, "benchmark", "work", "report")

SCHEMA_ID = "tn-bench-site-run/v1"
SERIES_SCHEMA_ID = "tn-bench-site-series/v1"
UPSTREAM_REPO = "https://github.com/Telcoin-Association/telcoin-network"
SITE_ORIGIN_MARK = "Telcoin-Association/tn-benchmarks"
# The site checkout's origin must end in <owner>/<repo>[.git] after a "/" or ":" (any scheme or
# host form: git@host:owner/repo.git, https://host/owner/repo, ssh://git@host/owner/repo.git).
SITE_ORIGIN_RE = re.compile(r"(?:^|[/:])telcoin-association/tn-benchmarks(?:\.git)?$", re.IGNORECASE)

RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
RESERVED_SCRATCH_NAMES = ("archived",)
HEX_RE = re.compile(r"[0-9a-f]+")
FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

MAX_1S_ROWS = 2000
TPS_5MIN_COLUMNS = ["start_utc", "end_utc", "generators_active", "chain_tps"]
DEFAULT_PLACEMENT = "one blaster per validator in the validator's zone"
NOT_RECORDED = "not recorded"
LOGS_PARAMS_FILE = "parameters.yaml (devnet defaults)"
LOGS_CONFIRMED_BY = "node startup logs"
DELAY_KEYS = ("max_header_delay_ms", "min_header_delay_ms", "max_batch_delay_ms")
CONSENSUS_NUM_KEYS = DELAY_KEYS + ("vote_timeout_ms",)
RECOVERY_KEYS = ("node", "killed_utc", "restarted_utc", "rejoined_utc", "catch_up_secs", "failed_reports")
KPI_KEYS = ("id", "label", "short_label", "value", "range", "unit", "window", "source", "method", "provenance")

BACKFILL_KEYS = {
    "schema": None, "title": None, "summary": None, "status": None, "date": None,
    "started_utc": None, "ended_utc": None, "compare_to": None,
    "upstream": ("sha", "branch", "evidence", "evidence_detail"),
    "node_image": ("ref", "digest", "version", "fork_schedule"),
    "generator": ("sha", "image_digest", "analysis_sha"),
    "harness": ("sha", "submodules"),
    "fleet": ("label", "validators", "observers", "machine_type", "vcpus", "memory_gb", "disk",
              "regions", "load"),
    "chain": ("chain_id", "network", "epoch_secs"),
    "consensus": CONSENSUS_NUM_KEYS + ("file", "confirmed_by"),
    "workload": ("warmup_secs", "mixed_secs", "cooldown_secs", "tx_types"),
    "methodology": None, "caveats": None, "kpis_published": None,
    "recovery": RECOVERY_KEYS,
    "report": ("archived_from", "modifications"),
}

# Step labels, numbered in execution order.
S_SETUP, S_SCRATCH, S_PROV, S_TOOLS, S_SCRUB, S_REPORT = (
    "0 setup", "1 scratch", "2 provenance", "3 tools", "4 scrub", "5 report")
S_WINDOWS, S_KPIS, S_ASSEMBLE, S_WRITE, S_GATES, S_INSTALL = (
    "6 windows", "7 kpis", "8 assemble", "9 write", "10 gates", "11 install")

# Reference-chains file build-report.py reads; always written as [] (see write_empty_reference).
REFERENCE_FILE = "reference-chains.json"

# Marker in every scratch dir: {run, blast_index, source, built_at}.
SOURCE_MARKER = ".source.json"
OLD_SOURCE_MARKERS = (".bundle-source.json",)

_T0 = time.time()


class BundleError(Exception):
    """A refusal: printed as one error and exit status 1."""


def log(step, msg):
    print("[make_bundle %6.1fs] %s: %s" % (time.time() - _T0, step, msg), flush=True)


def warn(msg):
    print("make_bundle: warning: %s" % msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------------- small helpers

def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_input(path):
    """_load_json for run inputs: a missing or malformed file is a BundleError naming the file."""
    try:
        return _load_json(path)
    except (OSError, ValueError) as e:
        raise BundleError("cannot read %s: %s" % (path, e))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _r(x, nd):
    """Half-up rounding to nd decimals (the KPI convention), None passes through."""
    if x is None:
        return None
    return float(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


def _round_floats(obj, nd=3):
    if isinstance(obj, float):
        return _r(obj, nd) if math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, nd) for v in obj]
    return obj


def _utc(value):
    """Any ISO-8601 timestamp -> YYYY-MM-DDTHH:MM:SSZ (UTC), or None."""
    if not value or not isinstance(value, str):
        return None
    try:
        return kpis_mod.unix_to_iso(kpis_mod.iso_to_unix(value))
    except ValueError:
        return None


def _strip_comments(d):
    return {k: v for k, v in d.items() if not (isinstance(k, str) and k.startswith("_"))}


def _git(args, cwd):
    try:
        p = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _is_inside(path, base):
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def _run_tool(argv, cwd, step):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-B"] + argv, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True, env=env)
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-4000:] + p.stderr[-4000:])
        raise BundleError("%s: %s exited %d" % (step, os.path.basename(argv[0]), p.returncode))
    tail = (p.stdout.strip().splitlines() or [""])[-1]
    return tail


# ------------------------------------------------------------------------- backfill

PLACEHOLDER_RE = re.compile(r"<<.*?>>", re.S)


def find_placeholders(obj, where=""):
    """Dotted paths (a.b[2].c) of every string in a JSON document that still holds a <<...>> placeholder."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).startswith("_"):
                continue  # a comment key, dropped before publishing
            hits.extend(find_placeholders(v, "%s.%s" % (where, k) if where else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_placeholders(v, "%s[%d]" % (where, i)))
    elif isinstance(obj, str) and PLACEHOLDER_RE.search(obj):
        hits.append(where or "<root>")
    return hits


def refuse_placeholders(obj, what):
    """Refuse a document (the backfill, or the assembled run.json) that still carries <<...>> placeholders."""
    hits = find_placeholders(obj)
    if hits:
        raise BundleError("%s: unfilled <<...>> placeholder in %s" % (what, ", ".join(hits)))


def load_backfill(path):
    """Read and lightly validate a backfill file (format in the module docstring)."""
    if not path:
        return {}
    try:
        doc = _load_json(path)
    except (OSError, ValueError) as e:
        raise BundleError("backfill %s: %s" % (path, e))
    if not isinstance(doc, dict):
        raise BundleError("backfill must be a JSON object")
    doc = _strip_comments(doc)
    refuse_placeholders(doc, "backfill")
    for key in list(doc):
        if key not in BACKFILL_KEYS:
            raise BundleError("backfill: unknown key %r" % key)
        sub = BACKFILL_KEYS[key]
        if sub is not None and doc[key] is not None:
            if not isinstance(doc[key], dict):
                raise BundleError("backfill: %s must be an object" % key)
            doc[key] = _strip_comments(doc[key])
            for k in doc[key]:
                if k not in sub:
                    raise BundleError("backfill: unknown key %s.%s" % (key, k))
    for key in ("title", "summary"):
        if key in doc and (not isinstance(doc[key], str) or not doc[key].strip()):
            raise BundleError("backfill: %s must be non-empty text" % key)
    if doc.get("status") not in (None, "complete", "aborted", "superseded"):
        raise BundleError("backfill: status must be complete, aborted or superseded")
    if doc.get("date") is not None and not DATE_RE.fullmatch(str(doc["date"])):
        raise BundleError("backfill: date must be YYYY-MM-DD")
    for key in ("started_utc", "ended_utc"):
        if doc.get(key) is not None and not UTC_RE.fullmatch(str(doc[key])):
            raise BundleError("backfill: %s must be YYYY-MM-DDTHH:MM:SSZ" % key)
    if doc.get("compare_to") is not None and not RUN_ID_RE.fullmatch(str(doc["compare_to"])):
        raise BundleError("backfill: compare_to is not a run id")
    for key in ("methodology", "caveats"):
        v = doc.get(key)
        if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v)):
            raise BundleError("backfill: %s must be a list of non-empty strings" % key)
    up = doc.get("upstream") or {}
    sha = up.get("sha")
    if sha is not None and not (isinstance(sha, str) and 7 <= len(sha) <= 40 and HEX_RE.fullmatch(sha)):
        raise BundleError("backfill: upstream.sha must be 7-40 lowercase hex digits")
    if up.get("evidence") not in (None, "verified", "inferred", "not-recorded"):
        raise BundleError("backfill: upstream.evidence must be inferred or not-recorded")
    det = up.get("evidence_detail")
    if det is not None and (not isinstance(det, list) or not all(isinstance(x, str) for x in det)):
        raise BundleError("backfill: upstream.evidence_detail must be a list of strings")
    if doc.get("kpis_published") is not None and not isinstance(doc["kpis_published"], list):
        raise BundleError("backfill: kpis_published must be a list")
    rep = doc.get("report") or {}
    mods = rep.get("modifications")
    if mods is not None and (not isinstance(mods, list) or not all(isinstance(x, str) for x in mods)):
        raise BundleError("backfill: report.modifications must be a list of strings")
    return doc


def published_kpis(entries):
    """Backfill kpis_published -> schema KPI dicts with provenance "published"."""
    out = []
    for i, e in enumerate(entries or []):
        where = "backfill kpis_published[%d]" % i
        if not isinstance(e, dict):
            raise BundleError("%s: must be an object" % where)
        e = _strip_comments(e)
        unknown = sorted(k for k in e if k not in KPI_KEYS)
        if unknown:
            raise BundleError("%s: unknown key(s) %s" % (where, ", ".join(unknown)))
        if e.get("provenance", "published") != "published":
            raise BundleError("%s: provenance must be \"published\"" % where)
        missing = [k for k in ("id", "label", "short_label", "unit", "source") if e.get(k) is None]
        if missing:
            raise BundleError("%s: missing %s" % (where, ", ".join(missing)))
        if ("value" in e) == ("range" in e):
            raise BundleError("%s: needs exactly one of value / range" % where)
        k = {"id": e["id"], "label": e["label"], "short_label": e["short_label"], "unit": e["unit"],
             "window": e.get("window"), "source": e["source"], "method": e.get("method"),
             "provenance": "published"}
        if "value" in e:
            k["value"] = e["value"]
        else:
            k["range"] = e["range"]
        out.append(k)
    return out


# ------------------------------------------------------------------------- paths and out dir

def scratch_path(run_id):
    if not RUN_ID_RE.fullmatch(run_id) or run_id in RESERVED_SCRATCH_NAMES:
        raise BundleError("%r is not a usable run id" % run_id)
    return os.path.join(WORK_ROOT, run_id)


def remove_scratch(path):
    """Delete one scratch dir, and only a direct child of WORK_ROOT named like a run id."""
    real = os.path.realpath(path)
    name = os.path.basename(real)
    if (os.path.dirname(real) != os.path.realpath(WORK_ROOT) or not RUN_ID_RE.fullmatch(name)
            or name in RESERVED_SCRATCH_NAMES or os.path.islink(path)):
        raise BundleError("refusing to delete %s (not a scratch dir under %s)" % (path, WORK_ROOT))
    shutil.rmtree(real)


def git_checkout_of(path):
    """Top level of the git checkout holding `path` (or its nearest existing parent), or None."""
    probe = os.path.abspath(path)
    while not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    return _git(["rev-parse", "--show-toplevel"], probe)


def check_out_dir(out, run_id):
    """Validate the out dir; returns the site checkout that holds it, or None."""
    if os.path.basename(os.path.normpath(out)) != run_id:
        raise BundleError("out dir %s must end in /%s (the site checks id == directory name)" % (out, run_id))
    for forbidden in (RESULTS_ROOT, WORK_ROOT):
        if _is_inside(out, forbidden):
            raise BundleError("out dir %s lies inside %s" % (out, forbidden))
    top = git_checkout_of(out)
    if top is None:
        return None
    origin = _git(["remote", "get-url", "origin"], top) or ""
    if not SITE_ORIGIN_RE.search(origin.strip()):
        raise BundleError("out dir %s is inside the git checkout %s whose origin is not %s"
                          % (out, top, SITE_ORIGIN_MARK))
    return top


# ------------------------------------------------------------------------- step 1: scratch

def _copy_file(src, dst):
    if os.path.islink(src) or not os.path.isfile(src):
        raise BundleError("not a regular file: %s" % src)
    shutil.copyfile(src, dst)


def blast_label(blast_index):
    return "top level" if blast_index is None else "blast %d" % blast_index


def read_marker(scratch):
    """The scratch dir's source marker {run, blast_index, source, built_at}, or None. Scratch
    dirs from before the rename carry the same fields in .bundle-source.json."""
    for name in (SOURCE_MARKER,) + OLD_SOURCE_MARKERS:
        try:
            doc = _load_json(os.path.join(scratch, name))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return doc
    return None


def scratch_state(run_id, blast_index):
    """('absent' | 'reuse' | 'mismatch', reason) for the scratch dir of a compare run."""
    scratch = scratch_path(run_id)
    if not os.path.lexists(scratch):
        return "absent", None
    marker = read_marker(scratch)
    if marker is None or marker.get("run") != run_id or "blast_index" not in marker:
        return "mismatch", "has no source marker, so the blast it was built from is unknown"
    if marker["blast_index"] != blast_index:
        return "mismatch", "was built from the %s results" % blast_label(marker["blast_index"])
    need = ("combined.json", "metrics.json", "manifest.json", "sizing.json", "reference-chains.json")
    if not all(os.path.isfile(os.path.join(scratch, "scrubbed", n)) for n in need):
        return "mismatch", "is incomplete (no scrubbed report inputs)"
    return "reuse", None


def compare_mismatch_error(r2, blast_index, reason):
    return BundleError("compare scratch %s %s, but --compare %s asks for the %s results%s; pass --force "
                       "to rebuild it from the %s results, or pass the --compare-blast-index it was built with"
                       % (scratch_path(r2), reason, r2, blast_label(blast_index),
                          "" if blast_index is not None else " (no --compare-blast-index)", blast_label(blast_index)))


def results_path(run_id):
    return os.path.join(RESULTS_ROOT, run_id)


def prepare_scratch(run_id, blast_index, force, step=None):
    """Allowlisted copy of results/<run_id> (or its blast-<N>-*/) into the scratch dir. The scratch
    dir holds inputs the tools rewrite and their outputs only: the node logs stay in the results
    dir, where provenance_step reads them."""
    step = step or S_SCRATCH
    results = results_path(run_id)
    if not os.path.isdir(results):
        raise BundleError("results dir does not exist: %s" % results)
    scratch = scratch_path(run_id)
    if os.path.lexists(scratch) and not force:
        raise BundleError("scratch dir %s exists; pass --force to delete and rebuild it" % scratch)
    src = results
    if blast_index is not None:
        matches = sorted(d for d in glob.glob(os.path.join(results, "blast-%d-*" % blast_index))
                         if os.path.isdir(d) and not os.path.islink(d))
        if len(matches) != 1:
            raise BundleError("blast index %d of %s: expected exactly one blast-%d-* dir in %s, found %d"
                              % (blast_index, run_id, blast_index, results, len(matches)))
        src = matches[0]
    for name in ("manifest.json", "metrics.json"):
        if not os.path.isfile(os.path.join(src, name)):
            raise BundleError("missing %s" % os.path.join(src, name))
    blasters = sorted(glob.glob(os.path.join(src, "blasters", "*.json")))
    if not blasters:
        raise BundleError("no blasters/*.json in %s" % src)

    for p in [os.path.join(src, "manifest.json"), os.path.join(src, "metrics.json")] + blasters:
        _load_input(p)  # malformed JSON is refused here, by file name, before anything is deleted
    if os.path.lexists(scratch):  # --force, and only once the sources are known to be usable
        remove_scratch(scratch)
    os.makedirs(os.path.join(scratch, "blasters"), mode=0o700)
    for name in ("manifest.json", "metrics.json"):
        _copy_file(os.path.join(src, name), os.path.join(scratch, name))
    for p in blasters:
        _copy_file(p, os.path.join(scratch, "blasters", os.path.basename(p)))
    csvs = sorted(glob.glob(os.path.join(results, "sampler", "*.csv")))
    if csvs:
        os.makedirs(os.path.join(scratch, "sampler"))
        for p in csvs:
            _copy_file(p, os.path.join(scratch, "sampler", os.path.basename(p)))
    write_empty_reference(os.path.join(scratch, REFERENCE_FILE))
    with open(os.path.join(scratch, SOURCE_MARKER), "w") as fh:
        json.dump({"run": run_id, "blast_index": blast_index, "source": os.path.relpath(src, RESULTS_ROOT),
                   "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, fh)
    log(step, "%s <- %s (%d blasters, %d sampler csv)"
        % (os.path.relpath(scratch, REPO_ROOT), os.path.relpath(src, REPO_ROOT), len(blasters), len(csvs)))
    return scratch


# ------------------------------------------------------------------------- steps 3-5: tools, scrub, report

def run_tools(scratch, tool_dir, step=None):
    """aggregate.py and derive-sizing.py, cwd=scratch, relative arguments."""
    step = step or S_TOOLS
    t = _run_tool([os.path.join(tool_dir, "aggregate.py"), "--out", "combined.json", "blasters"], scratch, step)
    log(step, "aggregate.py: %s" % t)
    t = _run_tool([os.path.join(tool_dir, "derive-sizing.py"), ".", "--out", "sizing.json"], scratch, step)
    log(step, "derive-sizing.py -> sizing.json %s" % t)


def scrub_scratch(scratch, step=None):
    """Scrubbed copies of the report inputs in scratch/scrubbed/."""
    step = step or S_SCRUB
    scrubbed = os.path.join(scratch, "scrubbed")
    try:
        summary = hscrub.scrub_inputs(scratch, scrubbed)
    except (OSError, ValueError) as e:  # a sampler CSV that is not plain numbers, unreadable JSON
        raise BundleError("scrubbing %s failed: %s" % (scratch, e))
    _copy_file(os.path.join(scratch, REFERENCE_FILE), os.path.join(scrubbed, REFERENCE_FILE))
    log(step, "scrubbed %d files (ip map %d, %d keys dropped, %d ips replaced)"
        % (len(summary.get("files") or []), summary.get("ipmap_size", 0), len(summary.get("dropped") or []),
           summary.get("replaced_ips", 0)))
    return scrubbed


def write_empty_reference(path):
    """Write `[]` as the reference-chains file. build-report.py then prints its "Reference chains"
    heading with a one-line "Not collected: reference chains." note and no table. The tools' own
    reference-chains.json is deliberately not used: its table puts this run's busiest single second
    beside other chains' sustained figures, which misleads on a page that can be shared on its own.
    The site's "Other networks" section carries cited figures with their method instead."""
    with open(path, "w") as fh:
        fh.write("[]\n")


def build_report(scrubbed, tool_dir, compare_rel):
    """build-report.py in scratch/scrubbed with relative paths only. --reference stays a relative
    path (the footer prints it verbatim) and names an empty list (see write_empty_reference)."""
    write_empty_reference(os.path.join(scrubbed, REFERENCE_FILE))
    argv = [os.path.join(tool_dir, "build-report.py"), "--blast", "combined.json", "--metrics", "metrics.json"]
    if os.path.isdir(os.path.join(scrubbed, "sampler")):
        argv += ["--sampler", "sampler"]
    argv += ["--manifest", "manifest.json", "--sizing", "sizing.json", "--reference", REFERENCE_FILE,
             "--out", "report.html"]
    if compare_rel:
        argv += ["--compare", compare_rel]
    t = _run_tool(argv, scrubbed, S_REPORT)
    path = os.path.join(scrubbed, "report.html")
    log(S_REPORT, "%s (sha256 %s)" % (t, _sha256(path)[:12]))
    return path


def check_compare(r2, blast_index, run_id, force):
    """Setup-time check of the compare run: refuses a scratch built from another blast (or of
    unknown origin) unless --force, before any work is done."""
    if r2 == run_id:
        raise BundleError("--compare names the run itself")
    if not os.path.isdir(os.path.join(RESULTS_ROOT, r2)):
        raise BundleError("--compare %s: results dir does not exist" % r2)
    state, reason = scratch_state(r2, blast_index)
    if state == "mismatch" and not force:
        raise compare_mismatch_error(r2, blast_index, reason)


def ensure_compare(r2, blast_index, tool_dir, force):
    """Scratch + scrubbed inputs of the compare run, from its top level or blast-<N>-*/. A scratch
    is reused only when its marker names the same blast; --force rebuilds a mismatching one."""
    step = "%s (compare %s, %s)" % (S_REPORT, r2, blast_label(blast_index))
    scratch = scratch_path(r2)
    state, reason = scratch_state(r2, blast_index)
    if state == "reuse":
        log(step, "reusing %s" % os.path.relpath(scratch, REPO_ROOT))
    else:
        if state == "mismatch":
            if not force:
                raise compare_mismatch_error(r2, blast_index, reason)
            log(step, "scratch %s; --force rebuilds it" % reason)
        prepare_scratch(r2, blast_index, True, step=step)
        run_tools(scratch, tool_dir, step=step)
        scrub_scratch(scratch, step=step)
    return "../../%s/scrubbed" % r2


# ------------------------------------------------------------------------- step 2: provenance

def provenance_step(run_dir, manifest, backfill, allow_mismatch):
    """Upstream block, logged version / fork schedule / parameters, and caveats, from the node logs
    in <run_dir>/logs/ (the run's results dir: read in place, never copied)."""
    bf_up = backfill.get("upstream") or {}
    expected = manifest.get("node_git_sha") or bf_up.get("sha")
    expected = str(expected).strip().lower() if expected else None
    scan = provenance.scan_run(run_dir)
    caveats, detail = [], []
    out = {"version": None, "fork_schedule": None, "params": {}, "param_values": {}}
    sha = expected if expected and FULL_SHA_RE.fullmatch(expected) else None
    if scan["files"]:
        res = provenance.check(scan, manifest, expect_sha=expected)
        starts = scan["starts"]
        versions = sorted({s["version"] for s in starts if s.get("version")})
        out.update(version=", ".join(versions) or None, fork_schedule=scan.get("fork_schedule"),
                   params=scan.get("params") or {}, param_values=scan.get("param_values") or {})
        if scan.get("unreadable"):
            caveats.append("%d node log file(s) could not be read to the end; provenance covers the rest"
                           % len(scan["unreadable"]))
        if res["ok"]:
            evidence = "verified"
            logged = [s for s in res["shas"] if FULL_SHA_RE.fullmatch(s or "")]
            if len(logged) == 1:
                sha = logged[0]
            instances = sorted({s["instance"] for s in starts})
            detail.append("%d node starts across %d instances logged telcoin-network %s (%s)"
                          % (len(starts), len(instances), out["version"] or "?", ", ".join(res["shas"])))
            if manifest.get("node_git_sha"):
                detail.append("The node image probe recorded the same commit before deploy")
            if scan.get("fork_schedule_line"):
                detail.append("Node logs: %s" % scan["fork_schedule_line"])
        else:
            problems = res["problems"]
            if not allow_mismatch:
                raise BundleError("provenance check failed (pass --allow-provenance-mismatch to publish "
                                  "with a caveat):\n  - " + "\n  - ".join(problems))
            evidence = bf_up.get("evidence") if bf_up.get("evidence") in ("inferred", "not-recorded") \
                else ("inferred" if expected else "not-recorded")
            caveats.append("The node logs did not confirm the upstream commit: %s" % "; ".join(problems))
        log(S_PROV, "%d log files, %d starts, shas %s, expected %s -> %s"
            % (len(scan["files"]), len(scan["starts"]), ",".join(s[:9] for s in scan["shas"]) or "-",
               (expected or "-")[:12], evidence))
    else:
        evidence = bf_up.get("evidence") or ("inferred" if expected else "not-recorded")
        if evidence == "verified":
            raise BundleError("backfill upstream.evidence is 'verified' but the run has no node logs")
        log(S_PROV, "no node logs; evidence %s from %s" % (evidence, "backfill" if bf_up.get("evidence") else "default"))
    for line in bf_up.get("evidence_detail") or []:
        if line not in detail:
            detail.append(line)
    short = (sha or expected or "")[:9] or None
    if short is not None and len(short) < 7:
        short = None
    out["upstream"] = {"repo": UPSTREAM_REPO, "sha": sha, "short": short, "branch": bf_up.get("branch"),
                       "evidence": evidence, "evidence_detail": detail}
    out["caveats"] = caveats
    return out


# ------------------------------------------------------------------------- step 6: windows

def windows_step(scratch, combined):
    blasters = win.load_blasters(os.path.join(scratch, "blasters"))
    if not blasters:
        raise BundleError("no tn-blast results in %s/blasters" % scratch)
    built = win.build(blasters, combined)
    if built["problems"]:
        raise BundleError("windows: " + "; ".join(built["problems"]))
    m = built["merged"]
    blocks = win.blocks(combined, built["mixed_windows"], m["start_unix"], m["end_unix"])
    tps5 = {"columns": list(TPS_5MIN_COLUMNS),
            "rows": [[win.iso(b["start_unix"]), win.iso(b["end_unix"]), _r(b["generators_active"], 1),
                      _r(b["chain_tps"], 1)] for b in blocks]}
    vals = win._chain_series(combined, m["start_unix"], m["end_unix"])
    step = max(1, int(math.ceil(len(vals) / float(MAX_1S_ROWS))))
    rows = []
    for i in range(0, len(vals), step):
        chunk = vals[i:i + step]
        rows.append([i, _r(sum(chunk) / float(len(chunk)), 1)])
    series = {"schema": SERIES_SCHEMA_ID, "unit": "tx/s", "start_utc": win.iso(m["start_unix"]),
              "step_s": step, "columns": ["offset_s", "chain_tps"], "rows": rows}
    gens = built.get("all_generators")
    log(S_WINDOWS, "merged %s +%ds, all-generators %s, %d 5-min rows, %d 1-s rows (step %ds)"
        % (win.iso(m["start_unix"]), m["secs"], ("%ds" % gens["secs"]) if gens else "undefined",
           len(tps5["rows"]), len(rows), step))
    return built, tps5, series


# ------------------------------------------------------------------------- step 7: kpis

def kpis_step(scrubbed, combined, metrics, manifest, built, backfill):
    targets = kpis_mod.chaos_targets_from_manifest(manifest)
    sampler_dir = os.path.join(scrubbed, "sampler")
    sampler = kpis_mod.load_sampler(sampler_dir) if os.path.isdir(sampler_dir) else {}
    res = kpis_mod.compute(combined, metrics, sampler, manifest, built, targets)
    computed = res["kpis"]
    published = published_kpis(backfill.get("kpis_published"))
    clash = sorted({k["id"] for k in computed} & {k["id"] for k in published})
    if clash:
        raise BundleError("backfill kpis_published reuses computed KPI id(s): %s" % ", ".join(clash))
    all_kpis = computed + published
    caveats = list(res["caveats"])
    rec = res["recovery"]
    rec = {k: rec.get(k) for k in RECOVERY_KEYS} if rec else None
    rec, rec_caveats = merge_recovery(rec, backfill.get("recovery"))
    caveats += rec_caveats
    log(S_KPIS, "%d computed + %d published, headline %s, recovery %s"
        % (len(computed), len(published), kpis_mod.headline_id(all_kpis),
           "none" if rec is None else "%s catch-up %s s, failed reports %s"
           % (rec.get("node"), rec.get("catch_up_secs"), rec.get("failed_reports"))))
    return all_kpis, kpis_mod.headline_id(all_kpis), rec, caveats


def merge_recovery(rec, bf_rec):
    """Fill null recovery fields from the backfill; returns (recovery, caveats)."""
    caveats = []
    if not bf_rec:
        return rec, caveats
    if rec is None:
        rec = {k: bf_rec.get(k) for k in RECOVERY_KEYS}
        caveats.append("Recovery figures are the published values; the run's own data has no chaos target "
                       "to recompute them from.")
        return rec, caveats
    filled = []
    for k in RECOVERY_KEYS:
        if rec.get(k) is None and bf_rec.get(k) is not None:
            rec[k] = bf_rec[k]
            filled.append(k)
        elif rec.get(k) is not None and k in bf_rec and bf_rec[k] != rec[k]:
            warn("backfill recovery.%s ignored: the run data gives %r" % (k, rec[k]))
    if filled:
        caveats.append("recovery.%s %s the published value%s, not recomputed from the run data."
                       % (", recovery.".join(filled), "is" if len(filled) == 1 else "are",
                          "" if len(filled) == 1 else "s"))
    return rec, caveats


# ------------------------------------------------------------------------- step 8: assemble

def _image_parts(docker_image):
    """'<registry>/<path>/<name>[:tag][@sha256:<hex>]' -> ('<name>:<tag>' | None, 'sha256:<hex>' | None)."""
    if not docker_image:
        return None, None
    ref, digest = docker_image, None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
        digest = digest if IMAGE_DIGEST_RE.fullmatch(digest) else None
    name = ref.rsplit("/", 1)[-1]
    return (name if ":" in name else None), digest


def _fill(base, extra):
    """base with None values filled from extra (both dicts)."""
    out = dict(base)
    for k, v in (extra or {}).items():
        if out.get(k) is None and v is not None:
            out[k] = v
    return out


def node_image_block(manifest, prov, backfill):
    ref, digest = _image_parts(manifest.get("docker_image"))
    block = {"ref": manifest.get("node_image_ref") or ref,
             "digest": manifest.get("node_image_digest") or digest,
             "version": manifest.get("node_version") or prov.get("version"),
             "fork_schedule": manifest.get("node_fork_schedule") or prov.get("fork_schedule")}
    return _fill(block, backfill.get("node_image"))


def generator_block(manifest, blasters_docs, backfill, analysis_sha, tool_dir, caveats):
    gen_sha = manifest.get("txgen_git_sha")
    if not gen_sha:
        shas = sorted({(b.get("run") or {}).get("generator_git_sha") for b in blasters_docs} - {None})
        gen_sha = shas[0] if len(shas) == 1 else None
    bf = backfill.get("generator") or {}
    a_sha = analysis_sha or bf.get("analysis_sha")
    if not a_sha and tool_dir:
        a_sha = _git(["rev-parse", "--short=7", "HEAD"], tool_dir)
        if a_sha and _git(["status", "--porcelain", "--", "."], tool_dir):
            caveats.append("The report tools (tn-transaction-generator bench/) had uncommitted changes on top "
                           "of analysis_sha %s." % a_sha)
    block = {"sha": gen_sha, "image_digest": manifest.get("txgen_image_digest"), "analysis_sha": a_sha}
    return _fill(block, bf)


def harness_block(manifest, backfill, caveats):
    h = manifest.get("harness")
    if isinstance(h, dict):
        if h.get("dirty"):
            caveats.append("The harness working tree had uncommitted changes when the run was deployed.")
        subs = {k: (v or None) for k, v in (h.get("submodules") or {}).items()}
        return {"sha": h.get("sha") or None, "submodules": subs}
    bf = backfill.get("harness") or {}
    return {"sha": bf.get("sha"), "submodules": dict(bf.get("submodules") or {})}


def _region(zone):
    return re.sub(r"-[a-z]$", "", zone or "")


# The city (or area) of each GCP region a bench fleet has run in or may move to, so fleet.regions
# reads "asia-northeast1 (Tokyo)". A region missing here is published as its bare id.
REGION_LABELS = {
    "us-west2": "Los Angeles", "us-east1": "South Carolina", "us-central1": "Iowa",
    "northamerica-northeast1": "Montréal", "southamerica-east1": "São Paulo",
    "europe-west2": "London", "europe-west3": "Frankfurt", "europe-west4": "Netherlands",
    "me-west1": "Tel Aviv", "asia-south1": "Mumbai", "asia-southeast1": "Singapore",
    "asia-southeast2": "Jakarta", "asia-east1": "Taiwan", "asia-east2": "Hong Kong",
    "asia-northeast1": "Tokyo", "asia-northeast2": "Osaka", "asia-northeast3": "Seoul",
    "australia-southeast1": "Sydney", "australia-southeast2": "Melbourne",
}


def region_label(region):
    """'<region> (<city>)' for a region in REGION_LABELS, else the region id as given."""
    name = REGION_LABELS.get(region)
    return "%s (%s)" % (region, name) if name else region


def fleet_block(manifest, metrics, backfill, caveats):
    nodes = [i for i in manifest.get("instances") or [] if i.get("role") in ("validator", "observer")]
    validators = [i for i in nodes if i.get("role") == "validator"]
    shape = next((i for i in (metrics.get("instances") or []) if i.get("role") == "validator"
                  and i.get("vcpus") is not None), None) or (validators[0] if validators else {})
    mem = shape.get("memory_mb")
    disk = manifest.get("node_disk") or {}
    mblasters = manifest.get("blasters") or []
    blast = manifest.get("blast") or {}
    machine = blast.get("machine_type") or next((b.get("machine_type") for b in mblasters if b.get("machine_type")), None)
    senders = blast.get("senders")
    if senders is None:
        values = sorted({b.get("senders") for b in mblasters if b.get("senders") is not None})
        if len(values) > 1:
            caveats.append("Blasters ran different sender counts (%s); senders_each is the largest."
                           % ", ".join(str(v) for v in values))
        senders = values[-1] if values else None
    bf = backfill.get("fleet") or {}
    bf_load = bf.get("load") or {}
    load = {"blasters": len(mblasters) or None, "machine_type": machine, "senders_each": senders,
            "placement": None}
    load = {k: (bf_load[k] if k in bf_load else v) for k, v in load.items()}
    if load["placement"] is None:
        load["placement"] = DEFAULT_PLACEMENT
    if load["machine_type"] is None:
        load["machine_type"] = NOT_RECORDED
        caveats.append("The load generators' machine type was not recorded for this run.")
    if load["blasters"] is None or load["senders_each"] is None:
        load = None
    disk_block = {"type": disk.get("type"), "size_gb": disk.get("size_gb"),
                  "iops": disk.get("provisioned_iops", disk.get("iops")),
                  "throughput_mibps": disk.get("provisioned_throughput", disk.get("throughput_mibps"))}
    disk_block.update(bf.get("disk") or {})
    fleet = {"label": manifest.get("fleet"), "validators": len(validators),
             "observers": sum(1 for i in nodes if i.get("role") == "observer"),
             "machine_type": manifest.get("machine_type"), "vcpus": shape.get("vcpus"),
             "memory_gb": _r(mem / 1024.0, 1) if mem is not None else None, "disk": disk_block,
             "regions": [region_label(r) for r in sorted({_region(i.get("zone")) for i in nodes if i.get("zone")})],
             "load": load}
    for k, v in bf.items():
        if k not in ("disk", "load"):
            fleet[k] = v
    return fleet


# Per-node values in the published consensus block: names and values are tool-written
# (benchmark-deploy.sh step 9, tools/params-apply.sh); anything else in the manifest is refused.
_NODE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_PARAM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_PARAM_VALUE_RE = re.compile(r"^(?:\d{1,12}(?:\.\d{1,9})?(?:ms|s|m)?|true|false)$")
_ARM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_UTC_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def _node_values(where, nodes):
    """{instance: {key: value}} from the manifest, checked; sorted [(instance, key, value)]."""
    if not isinstance(nodes, dict):
        raise BundleError("%s is not an object" % where)
    rows = []
    for inst, kv in nodes.items():
        if not _NODE_NAME_RE.match(str(inst)) or not isinstance(kv, dict):
            raise BundleError("%s: %r is not an instance name with {key: value}" % (where, inst))
        for k, v in kv.items():
            if not _PARAM_KEY_RE.match(str(k)) or not isinstance(v, str) or not _PARAM_VALUE_RE.match(v):
                raise BundleError("%s.%s: %r=%r is not a parameter key and value" % (where, inst, k, v))
            rows.append((inst, k, v))
    return sorted(rows)


def override_rows(manifest):
    """consensus_parameters.overrides as table rows [{instance, key, value}] ([] when none)."""
    cp = manifest.get("consensus_parameters") if isinstance(manifest.get("consensus_parameters"), dict) else {}
    if not cp.get("overrides"):
        return []
    return [{"instance": i, "key": k, "value": v}
            for i, k, v in _node_values("manifest consensus_parameters.overrides", cp["overrides"])]


def _arm_values_text(rows):
    """One arm's values as text: what every node of the arm got first ("all 11 nodes: k=v"), then
    per node what differs ("bench-validator-03: k=v")."""
    by_inst = {}
    for inst, k, v in rows:
        by_inst.setdefault(inst, {})[k] = v
    insts = sorted(by_inst)
    common = {}
    if len(insts) > 1:
        common = {k: v for k, v in by_inst[insts[0]].items() if all(by_inst[i].get(k) == v for i in insts)}
    parts = []
    if common:
        parts.append("all %d nodes: %s" % (len(insts), ", ".join("%s=%s" % kv for kv in sorted(common.items()))))
    for inst in insts:
        rest = sorted((k, v) for k, v in by_inst[inst].items() if k not in common)
        if rest:
            parts.append("%s: %s" % (inst, ", ".join("%s=%s" % kv for kv in rest)))
    return "; ".join(parts)


def arm_rows(manifest):
    """manifest.param_arms (tools/params-apply.sh) as table rows [{arm, begin_utc, end_utc, values}]
    in begin order ([] when none); values is _arm_values_text, plus the node an arm stopped at."""
    arms = manifest.get("param_arms")
    if not arms:
        return []
    if not isinstance(arms, list):
        raise BundleError("manifest param_arms is not a list")
    out = []
    for n, arm in enumerate(arms):
        where = "manifest param_arms[%d]" % n
        if not isinstance(arm, dict) or not _ARM_NAME_RE.match(str(arm.get("name"))):
            raise BundleError("%s: no arm name of [a-z0-9-]" % where)
        for k in ("begin", "end"):
            if not (arm.get(k) is None and k == "end") and not _UTC_RE.match(str(arm.get(k))):
                raise BundleError("%s.%s: %r is not YYYY-MM-DDTHH:MM:SSZ" % (where, k, arm.get(k)))
        text = _arm_values_text(_node_values(where + ".nodes", arm.get("nodes")))
        failed = arm.get("failed")
        if failed is not None:
            if not _NODE_NAME_RE.match(str(failed)):
                raise BundleError("%s.failed: %r is not an instance name" % (where, failed))
            text += " (stopped at %s, which did not come back after its restart)" % failed
        out.append({"arm": arm["name"], "begin_utc": arm["begin"], "end_utc": arm.get("end"), "values": text})
    return sorted(out, key=lambda r: r["begin_utc"])


def _per_node_explains(manifest, key, values):
    """True when every logged value of <key> (a provenance PARAM_KEYS name) is the fleet value, an
    override or a param arm's value for some node."""
    insts = set()
    cp = manifest.get("consensus_parameters") if isinstance(manifest.get("consensus_parameters"), dict) else {}
    insts.update((cp.get("overrides") or {}) if isinstance(cp.get("overrides"), dict) else {})
    for arm in manifest.get("param_arms") or []:
        if isinstance(arm, dict) and isinstance(arm.get("nodes"), dict):
            insts.update(arm["nodes"])
    allowed = set()
    for inst in insts:
        allowed.update(provenance.expected_param_values(manifest, inst, key))
    return bool(insts) and all(v in allowed for v in values)


def consensus_block(manifest, prov, backfill, caveats):
    """run.json "consensus": the fleet's values (manifest, node logs, backfill), plus, only when the
    run had them, "overrides" (per-node values deploy step 9 wrote: rows instance / key / value)
    and "param_arms" (tools/params-apply.sh's arms: rows arm / begin_utc / end_utc / values)."""
    cp = manifest.get("consensus_parameters") if isinstance(manifest.get("consensus_parameters"), dict) else None
    logs = prov.get("params") or {}
    overrides, arms = override_rows(manifest), arm_rows(manifest)
    bf = backfill.get("consensus") or {}
    vals, file_label, confirmed = {}, None, None
    if cp:
        for k in DELAY_KEYS:
            if cp.get(k) is not None:
                vals[k] = int(cp[k])
        file_label = cp.get("file") or "parameters.yaml"
        confirmed = LOGS_CONFIRMED_BY if all(k in logs for k in DELAY_KEYS) else "harness manifest (consensus_parameters)"
    elif all(k in logs for k in DELAY_KEYS):
        vals = {k: int(logs[k]) for k in DELAY_KEYS}
        file_label, confirmed = LOGS_PARAMS_FILE, LOGS_CONFIRMED_BY
    for k, values in (prov.get("param_values") or {}).items():
        if len(values) > 1 and (overrides or arms) and _per_node_explains(manifest, k, values):
            caveats.append("The nodes ran more than one %s (%s) by design: the fleet value is published here, "
                           "and the per-node values are listed under %s."
                           % (k, ", ".join(str(v) for v in values),
                              " and ".join(t for t, rows in (("consensus.overrides", overrides),
                                                             ("consensus.param_arms", arms)) if rows)))
        elif len(values) > 1:
            caveats.append("The node logs show more than one %s (%s); the last one logged is published."
                           % (k, ", ".join(str(v) for v in values)))
    if logs.get("vote_timeout_ms") is not None:
        vals["vote_timeout_ms"] = int(logs["vote_timeout_ms"])
    from_backfill = []
    for k in CONSENSUS_NUM_KEYS:
        if bf.get(k) is None:
            continue
        if k in vals and vals[k] != bf[k]:
            raise BundleError("backfill consensus.%s=%r contradicts the run's recorded %r" % (k, bf[k], vals[k]))
        if k not in vals:
            vals[k] = bf[k]
            from_backfill.append(k)
    file_label = bf.get("file") or file_label
    confirmed = bf.get("confirmed_by") or confirmed
    missing = [k for k in CONSENSUS_NUM_KEYS if k not in vals]
    if missing or not file_label or not confirmed:
        if len(missing) == len(CONSENSUS_NUM_KEYS):
            caveats.append("The consensus parameters were not recorded for this run, so none are published.")
        else:
            caveats.append("Consensus parameters are not published for this run: %s not recorded."
                           % (", ".join(missing) or "the parameters file"))
        return None
    if from_backfill:
        caveats.append("consensus.%s %s not in the node logs or the manifest; the published value%s from the "
                       "run's backfill." % (", consensus.".join(from_backfill),
                                            "is" if len(from_backfill) == 1 else "are",
                                            " comes" if len(from_backfill) == 1 else "s come"))
    block = {k: vals[k] for k in CONSENSUS_NUM_KEYS}
    block.update(file=file_label, confirmed_by=confirmed)
    if overrides:
        block["overrides"] = overrides
    if arms:
        block["param_arms"] = arms
    return block


def workload_block(blasters_docs, combined, backfill, caveats):
    keys = (("warmup_secs", "warmup_secs"), ("mixed_secs", "duration_secs"), ("cooldown_secs", "cooldown_secs"))
    block = {}
    for out_key, arg_key in keys:
        values = sorted({((b.get("run") or {}).get("args") or {}).get(arg_key) for b in blasters_docs} - {None})
        if len(values) > 1:
            caveats.append("Blasters ran different %s (%s); the largest is published."
                           % (arg_key, ", ".join(str(v) for v in values)))
        block[out_key] = values[-1] if values else None
    types = combined.get("types") or {}
    block["tx_types"] = sorted(t for t, v in types.items()
                               if isinstance(v, dict) and (v.get("submitted") or v.get("landed_own")))
    bf = dict(backfill.get("workload") or {})
    if not block["tx_types"] and bf.get("tx_types"):
        block["tx_types"] = bf.pop("tx_types")
    bf.pop("tx_types", None)
    block = _fill(block, bf)
    if any(block[k] is None for k in ("warmup_secs", "mixed_secs", "cooldown_secs")):
        caveats.append("Workload phase lengths were not recorded for this run.")
        return None
    return block


def chaos_block(manifest):
    out = []
    for e in manifest.get("chaos") or []:
        t = _utc(e.get("ts"))
        if not t or not e.get("node") or not e.get("action"):
            continue
        detail = e.get("note") or None
        if e.get("rc") not in (0, None):
            detail = ("%s; " % detail if detail else "") + "the command failed (rc %s)" % e.get("rc")
        out.append({"t_utc": t, "node": e["node"], "action": e["action"], "detail": detail})
    out.sort(key=lambda c: c["t_utc"])
    return out


def run_times(manifest):
    ts = manifest.get("timestamps") or {}
    started = _utc(ts.get("deploy_start"))
    stamps = sorted(t for t in (_utc(v) for v in ts.values()) if t)
    return started, (stamps[-1] if stamps else None)


def default_title(run_id, fleet, workload):
    title = "Benchmark run %s" % run_id
    summary = "%d validators and %d observer(s) on %s" % (fleet["validators"], fleet["observers"], fleet["machine_type"])
    if workload and workload.get("mixed_secs"):
        summary += ", %d-minute mixed workload" % int(round(workload["mixed_secs"] / 60.0))
    return title, summary + "."


def report_block(report_src, archived_path, backfill):
    rep = backfill.get("report") or {}
    block = {"file": "report.html", "sha256": _sha256(report_src), "bytes": os.path.getsize(report_src),
             "archived_from": None, "modifications": []}
    if archived_path:
        block["archived_from"] = rep.get("archived_from") or os.path.basename(archived_path)
        block["modifications"] = list(rep.get("modifications") or [])
    elif rep:
        warn("backfill report.* is used only with --archived-report; ignored")
    return block


# ------------------------------------------------------------------------- certification by node
# The harness records which validators got their own headers certified (bench_certification_record:
# manifest.certification, .certification_meta, .cert_failures). The site's run.json schema has no key
# for it, so the table goes into the built report (a section after "Consensus health") and a failure
# also becomes a run.json caveat. An archived report is kept byte for byte: no table, caveat only.

CERT_SECTION_ID = "certification-by-node"
CERT_DEFAULT_FAIL_PCT = 90
CERT_DEFAULT_MIN_PROPOSED = 50


def _cert_failures(manifest):
    return [f for f in (manifest.get("cert_failures") or []) if isinstance(f, dict) and isinstance(f.get("inst"), str)]


def _cert_meta(manifest):
    meta = manifest.get("certification_meta") if isinstance(manifest.get("certification_meta"), dict) else {}
    pct = meta.get("fail_below_pct")
    minp = meta.get("min_proposed")
    return (pct if isinstance(pct, (int, float)) and not isinstance(pct, bool) else CERT_DEFAULT_FAIL_PCT,
            minp if isinstance(minp, int) and not isinstance(minp, bool) else CERT_DEFAULT_MIN_PROPOSED,
            [w for w in (meta.get("windows") or []) if isinstance(w, str)])


def _words(items):
    """'a', 'a and b', 'a, b and c' ('' for none)."""
    items = list(items)
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _pct_text(v):
    return "–" if not isinstance(v, (int, float)) or isinstance(v, bool) else "%.1f" % v


def _threshold_text(p):
    return "%d" % p if float(p).is_integer() else "%.1f" % p


def certification_table(manifest):
    """The "Certification by node" table, or None when the run recorded no certification: {threshold_pct,
    min_proposed, windows, fair_share_pct, validators, failing, rows}. A row per validator: inst, region
    (from manifest.instances), cells {window: {rate_pct, proposed, certified, judged, failing}}, and the
    own leader share and not-committed share over the "run" window (the last window when there is none)."""
    cert = manifest.get("certification")
    if not isinstance(cert, dict) or not cert:
        return None
    pct, minp, windows = _cert_meta(manifest)
    for node in cert.values():
        for w in (node if isinstance(node, dict) else {}):
            if w not in windows:
                windows.append(w)
    whole = "run" if "run" in windows else (windows[-1] if windows else None)
    zones = {i.get("name"): i.get("zone") for i in manifest.get("instances") or [] if isinstance(i, dict)}
    validators = sum(1 for i in manifest.get("instances") or [] if isinstance(i, dict) and i.get("role") == "validator")
    validators = validators or len(cert)
    failing = {f["inst"]: set(f.get("windows") or [f.get("window")]) for f in _cert_failures(manifest)}
    rows = []
    for inst in sorted(cert):
        node = cert[inst] if isinstance(cert[inst], dict) else {}
        cells = {}
        for w in windows:
            c = node.get(w) if isinstance(node.get(w), dict) else {}
            proposed = c.get("proposed") if isinstance(c.get("proposed"), int) else 0
            cells[w] = {"rate_pct": c.get("rate_pct"), "proposed": proposed, "certified": c.get("certified"),
                        "judged": proposed >= minp, "failing": w in failing.get(inst, ())}
        run = node.get(whole) if isinstance(node.get(whole), dict) else {}
        zone = zones.get(inst)
        rows.append({"inst": inst, "region": region_label(_region(zone)) if zone else None, "cells": cells,
                     "own_leader_share_pct": run.get("own_leader_share_pct"),
                     "not_committed_pct": run.get("not_committed_pct"), "failing": inst in failing})
    return {"threshold_pct": pct, "min_proposed": minp, "windows": windows, "share_window": whole,
            "fair_share_pct": 100.0 / validators, "validators": validators,
            "failing": sorted(failing),
            "rows": rows}


def certification_html(manifest):
    """The report section for certification_table(manifest); "" when the run recorded none."""
    t = certification_table(manifest)
    if t is None:
        return ""
    esc = html.escape
    pct = _threshold_text(t["threshold_pct"])
    head = "".join("<th class='num'>%s</th>" % esc(w) for w in t["windows"])
    body = []
    for r in t["rows"]:
        tds = []
        for w in t["windows"]:
            c = r["cells"][w]
            title = "%s of %s own headers certified%s" % (
                c["certified"] if c["certified"] is not None else "?", c["proposed"],
                "" if c["judged"] else " (fewer than %d proposed: not judged)" % t["min_proposed"])
            text = esc(_pct_text(c["rate_pct"]))
            if c["failing"]:
                text = "<strong>%s</strong>" % text
            tds.append("<td class='num%s' title='%s'>%s</td>" % ("" if c["judged"] else " muted", esc(title, quote=True), text))
        body.append("<tr><td>%s%s</td><td>%s</td>%s<td class='num'>%s</td><td class='num'>%s</td></tr>" % (
            esc(r["inst"]), " <strong>below %s %%</strong>" % pct if r["failing"] else "", esc(r["region"] or "–"),
            "".join(tds), esc(_pct_text(r["own_leader_share_pct"])), esc(_pct_text(r["not_committed_pct"]))))
    share = esc(t["share_window"] or "run")
    if t["failing"]:
        verdict = "%s certified fewer than %s %% of %s own headers in a window where %s at least %d." % (
            esc(_words(t["failing"])), pct, "its" if len(t["failing"]) == 1 else "their",
            "it proposed" if len(t["failing"]) == 1 else "they proposed", t["min_proposed"])
    else:
        verdict = ("Every validator certified at least %s %% of its own headers in every window where it proposed at "
                   "least %d." % (pct, t["min_proposed"]))
    return ("<section id='%s'><h2>Certification by node</h2>"
            "<p class='lede'>The share of each validator's own headers that formed a certificate, per window "
            "(tools/cert-rate.py on the node logs). %s Own leader %% is the validator's share of the committed "
            "leaders and not committed %% the share of its certificates no committed leader reached, both over "
            "the %s window; the fair share is 100 / %d validators = %.1f %%. Greyed: fewer than %d headers "
            "proposed, not judged.</p>"
            "<div class='scroll'><table class='data' id='certification-table'><thead><tr><th>Validator</th>"
            "<th>Region</th>%s<th class='num'>Own leader %%</th><th class='num'>Not committed %%</th></tr></thead>"
            "<tbody>%s</tbody></table></div></section>"
            % (CERT_SECTION_ID, verdict, share, t["validators"], t["fair_share_pct"], t["min_proposed"], head,
               "".join(body)))


def certification_caveat(manifest, run_id):
    """The caveat naming the validators in manifest.cert_failures and their failing windows, or None
    when there are none. Validators that failed different windows get theirs in parentheses."""
    failures = _cert_failures(manifest)
    if not failures:
        return None
    pct, _, order = _cert_meta(manifest)
    groups = {}   # failing windows (in window order) -> validators; dicts keep insertion order
    for f in sorted(failures, key=lambda f: f["inst"]):
        seen = {w for w in (f.get("windows") or [f.get("window")]) if isinstance(w, str)}
        key = tuple([w for w in order if w in seen] + sorted(seen - set(order))) or ("a window",)
        if f["inst"] not in groups.setdefault(key, []):
            groups[key].append(f["inst"])
    one = sum(len(v) for v in groups.values()) == 1
    if len(groups) == 1:
        (windows, names), = groups.items()
        who, where = _words(names), " in %s" % _words(windows)
    else:
        who, where = _words("%s (in %s)" % (_words(n), _words(w)) for w, n in groups.items()), ""
    return ("%s %s certified fewer than %s %% of %s own headers%s; %s logs are preserved under results/%s/logs/ "
            "(see INDEX.md)." % ("Validator" if one else "Validators", who, _threshold_text(pct),
                                 "its" if one else "their", where, "its" if one else "their", run_id))


def add_certification_section(report_path, section):
    """Put <section> into the built report at <report_path>: after its "Consensus health" section, else
    before its footer, else before </body>, else at the end. An earlier certification section is
    replaced, so a rebuild never holds two. Nothing to add ("") leaves the file as it is."""
    if not section:
        return False
    with open(report_path, encoding="utf-8") as fh:
        text = fh.read()
    text = re.sub(r"<section id='%s'>.*?</section>" % re.escape(CERT_SECTION_ID), "", text, flags=re.S)
    m = re.search(r"<section id=['\"]consensus['\"]>.*?</section>", text, re.S)
    if m:
        at = m.end()
    else:
        at = next((i for i in (text.find("<footer"), text.lower().rfind("</body>")) if i >= 0), len(text))
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(text[:at] + section + text[at:])
    return True


def assemble(run_id, a, manifest, metrics, combined, blasters_docs, prov, built, tps5, kpis_list, headline,
             recovery, computed_caveats, report, compare_to, backfill, tool_dir):
    caveats = []
    generator = generator_block(manifest, blasters_docs, backfill, a.analysis_sha, tool_dir, caveats)
    harness = harness_block(manifest, backfill, caveats)
    fleet = fleet_block(manifest, metrics, backfill, caveats)
    consensus = consensus_block(manifest, prov, backfill, caveats)
    workload = workload_block(blasters_docs, combined, backfill, caveats)
    started, ended = run_times(manifest)
    title, summary = default_title(run_id, fleet, workload)
    if not backfill.get("title") or not backfill.get("summary"):
        warn("no backfill title/summary; publishing generated placeholders")
    status = "aborted" if manifest.get("abort") else (backfill.get("status") or "complete")
    chain_bf = backfill.get("chain") or {}
    chain = _fill({"chain_id": manifest.get("chain_id"),
                   "network": (manifest.get("prometheus") or {}).get("network_label"),
                   "epoch_secs": manifest.get("epoch_duration_secs")}, chain_bf)
    cert_caveat = certification_caveat(manifest, run_id)
    if cert_caveat:
        caveats.append(cert_caveat)
    return {
        "schema": SCHEMA_ID,
        "id": run_id,
        "status": status,
        "title": backfill.get("title") or title,
        "summary": backfill.get("summary") or summary,
        "date": backfill.get("date") or (started or "")[:10],
        "started_utc": started,
        "ended_utc": ended,
        "compare_to": compare_to,
        "upstream": prov["upstream"],
        "node_image": node_image_block(manifest, prov, backfill),
        "generator": generator,
        "harness": harness,
        "fleet": fleet,
        "chain": chain,
        "consensus": consensus,
        "workload": workload,
        "windows": win.to_run_json(built),
        "chaos": chaos_block(manifest),
        "kpis": kpis_list,
        "headline": headline,
        "series": {"tps_5min": tps5, "tps_1s": "series/tps-1s.json"},
        "recovery": recovery,
        "methodology": list(backfill.get("methodology") or []),
        "caveats": _dedup(list(backfill.get("caveats") or [])
                          + [_sentence(c) for c in list(built.get("caveats") or []) + computed_caveats
                             + caveats + prov["caveats"] if c and c.strip()]),
        "report": report,
    }


def _sentence(text):
    """Computed caveats are tool text: capitalise the first character and end with a period."""
    t = (text or "").strip()
    if not t:
        return t
    t = t[0].upper() + t[1:]
    return t if t.endswith((".", "!", "?")) else t + "."


def _dedup(items):
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def _complete(block, keys):
    return isinstance(block, dict) and all(block.get(k) is not None for k in keys)


def assemble_from_backfill(run_id, a, backfill, report, compare_to):
    """--no-results: run.json from the backfill alone."""
    for key in ("title", "summary", "date"):
        if not backfill.get(key):
            raise BundleError("--no-results: the backfill must give %s" % key)
    bf_up = backfill.get("upstream") or {}
    evidence = bf_up.get("evidence") or "not-recorded"
    if evidence == "verified":
        raise BundleError("--no-results: upstream.evidence cannot be 'verified' without node logs")
    sha = bf_up.get("sha")
    short = sha[:9] if sha else None
    bf_fleet = backfill.get("fleet") or {}
    need = ("label", "validators", "observers", "machine_type", "disk", "regions")
    if not _complete(bf_fleet, need) or not _complete(bf_fleet.get("disk"), ("type", "size_gb")):
        raise BundleError("--no-results: backfill fleet needs %s and disk {type, size_gb}" % ", ".join(need))
    fleet = {"label": None, "validators": None, "observers": None, "machine_type": None, "vcpus": None,
             "memory_gb": None, "regions": None, "load": None}
    fleet.update({k: v for k, v in bf_fleet.items() if k != "disk"})
    fleet["disk"] = dict({"iops": None, "throughput_mibps": None}, **bf_fleet["disk"])
    chain = backfill.get("chain") or {}
    if not _complete(chain, ("chain_id", "network")):
        raise BundleError("--no-results: backfill chain needs chain_id and network")
    gen = backfill.get("generator") or {}
    consensus = backfill.get("consensus")
    workload = backfill.get("workload")
    rec = backfill.get("recovery")
    kpis_list = published_kpis(backfill.get("kpis_published"))
    return {
        "schema": SCHEMA_ID,
        "id": run_id,
        "status": backfill.get("status") or "complete",
        "title": backfill["title"],
        "summary": backfill["summary"],
        "date": backfill["date"],
        "started_utc": backfill.get("started_utc"),
        "ended_utc": backfill.get("ended_utc"),
        "compare_to": compare_to,
        "upstream": {"repo": UPSTREAM_REPO, "sha": sha if sha and FULL_SHA_RE.fullmatch(sha) else None,
                     "short": short, "branch": bf_up.get("branch"), "evidence": evidence,
                     "evidence_detail": list(bf_up.get("evidence_detail") or [])},
        "node_image": _fill({"ref": None, "digest": None, "version": None, "fork_schedule": None},
                            backfill.get("node_image")),
        "generator": {"sha": gen.get("sha"), "image_digest": gen.get("image_digest"),
                      "analysis_sha": a.analysis_sha or gen.get("analysis_sha")},
        "harness": {"sha": (backfill.get("harness") or {}).get("sha"),
                    "submodules": dict((backfill.get("harness") or {}).get("submodules") or {})},
        "fleet": fleet,
        "chain": {"chain_id": chain["chain_id"], "network": chain["network"], "epoch_secs": chain.get("epoch_secs")},
        "consensus": consensus if _complete(consensus, BACKFILL_KEYS["consensus"]) else None,
        "workload": workload if _complete(workload, BACKFILL_KEYS["workload"]) else None,
        "windows": None,
        "chaos": [],
        "kpis": kpis_list,
        "headline": kpis_mod.headline_id(kpis_list),
        "series": None,
        "recovery": {k: rec.get(k) for k in RECOVERY_KEYS} if rec else None,
        "methodology": list(backfill.get("methodology") or []),
        "caveats": list(backfill.get("caveats") or []),
        "report": report,
    }


# ------------------------------------------------------------------------- step 9: write

def _dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def prepare_out(out):
    """Refuse an out dir holding anything a bundle does not produce."""
    if not os.path.lexists(out):
        return
    if os.path.islink(out) or not os.path.isdir(out):
        raise BundleError("out path %s exists and is not a directory" % out)
    for name in sorted(os.listdir(out)):
        full = os.path.join(out, name)
        if name in ("run.json", "report.html") and os.path.isfile(full) and not os.path.islink(full):
            continue
        if name == "series" and os.path.isdir(full) and not os.path.islink(full):
            bad = [n for n in os.listdir(full) if not n.endswith(".json") or os.path.islink(os.path.join(full, n))
                   or not os.path.isfile(os.path.join(full, n))]
            if not bad:
                continue
            raise BundleError("out dir %s/series holds %s; refusing to touch it" % (out, ", ".join(sorted(bad))))
        raise BundleError("out dir %s holds %s, which a bundle never contains; refusing to touch it" % (out, name))


def write_bundle(out, run_doc, report_src, series_doc):
    prepare_out(out)
    os.makedirs(out, exist_ok=True)
    produced = {"run.json", "report.html"}
    shutil.copyfile(report_src, os.path.join(out, "report.html"))
    series_dir = os.path.join(out, "series")
    if series_doc is not None:
        os.makedirs(series_dir, exist_ok=True)
        _dump_json(_round_floats(series_doc), os.path.join(series_dir, "tps-1s.json"))
        produced.add("series")
        for n in sorted(os.listdir(series_dir)):
            if n != "tps-1s.json":
                os.remove(os.path.join(series_dir, n))
                log(S_WRITE, "removed stale series/%s" % n)
    elif os.path.isdir(series_dir):
        shutil.rmtree(series_dir)
        log(S_WRITE, "removed stale series/")
    _dump_json(_round_floats(run_doc), os.path.join(out, "run.json"))
    log(S_WRITE, "%s: run.json (%d B), report.html (%d B)%s"
        % (out, os.path.getsize(os.path.join(out, "run.json")), os.path.getsize(os.path.join(out, "report.html")),
           ", series/tps-1s.json (%d B)" % os.path.getsize(os.path.join(series_dir, "tps-1s.json"))
           if series_doc is not None else ""))


# ------------------------------------------------------------------------- steps 9-11: stage, gates, install

def harness_gate(path, raw_manifest):
    findings = hscrub.scan_dir(path, manifest=raw_manifest)
    if findings:
        for f in findings[:200]:
            print("  " + f, file=sys.stderr)
        raise BundleError("harness leak scan found %d issue(s) in %s" % (len(findings), path))
    log(S_GATES, "harness scan_dir: clean")


def site_gate(path, site_checkout, site_repo, step):
    """The site's own check of one bundle dir: `build.py --check <path relative to the checkout>`
    when the dir lies in a site checkout that has build.py, else the site's `scrub.py <path>`."""
    if site_checkout and os.path.isfile(os.path.join(site_checkout, "build.py")) and _is_inside(path, site_checkout):
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(site_checkout))
        argv, cwd, label = [os.path.join(site_checkout, "build.py"), "--check", rel], site_checkout, "build.py --check " + rel
    else:
        site_scrub = os.path.join(site_checkout or site_repo, "scrub.py")
        if not os.path.isfile(site_scrub):
            raise BundleError("site gate unavailable: %s does not exist" % site_scrub)
        argv, cwd, label = [site_scrub, os.path.abspath(path)], os.path.dirname(site_scrub), "scrub.py"
    p = subprocess.run([sys.executable, "-B"] + argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-8000:] + p.stderr[-4000:])
        raise BundleError("site gate (%s) failed with exit %d" % (label, p.returncode))
    last = (p.stderr.strip().splitlines() or p.stdout.strip().splitlines() or [""])[-1]
    log(step, "site %s: %s" % (label, last))


def install_bundle(out, run_doc, report_src, series_doc, raw_manifest, site_checkout, site_repo):
    """Write the bundle into a staging dir next to <out> (same filesystem; inside the site this is
    runs/.<id>.tmp-<pid>/<id>), run both leak gates on it, then swap it into place and run the site
    check once more on the installed dir. A failed gate, move or final check leaves <out> as it was
    before the run: the previous bundle, or nothing. The staging dir is always removed."""
    refuse_placeholders(run_doc, "run.json")
    prepare_out(out)
    parent, name = os.path.split(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    stage_root = os.path.join(parent, ".%s.tmp-%d" % (name, os.getpid()))
    staged, backup, rejected = (os.path.join(stage_root, n) for n in (name, "previous", "rejected"))
    had_previous = os.path.isdir(out)
    unchanged = ("the previous bundle at %s is unchanged" % out) if had_previous else ("nothing exists at %s" % out)
    if os.path.lexists(stage_root):
        shutil.rmtree(stage_root)
    os.makedirs(stage_root)
    try:
        try:
            write_bundle(staged, run_doc, report_src, series_doc)
            harness_gate(staged, raw_manifest)
            site_gate(staged, site_checkout, site_repo, S_GATES)
        except BundleError as e:
            raise BundleError("%s\nNothing was installed: %s." % (e, unchanged))
        if had_previous:
            os.rename(out, backup)
        try:
            os.rename(staged, out)
        except OSError as e:
            if had_previous:
                os.rename(backup, out)
            raise BundleError("could not move the staged bundle into place (%s). Nothing was installed: %s."
                              % (e, unchanged))
        log(S_INSTALL, "%s installed (%s)" % (out, "replaced the previous bundle" if had_previous else "new bundle"))
        try:
            site_gate(out, site_checkout, site_repo, S_INSTALL)
        except BundleError as e:
            os.rename(out, rejected)
            if had_previous:
                os.rename(backup, out)
            raise BundleError("%s\nThe installed bundle was removed again: %s." % (
                e, ("the previous bundle at %s is restored" % out) if had_previous else ("nothing exists at %s" % out)))
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


# ------------------------------------------------------------------------- main

def parse_args(argv):
    ap = argparse.ArgumentParser(description="Build a public site bundle from one private benchmark run.")
    ap.add_argument("--run", required=True, help="run id (benchmark/results/<run>)")
    ap.add_argument("--blast-index", type=int, help="take manifest/metrics/blasters from blast-<N>-*/")
    ap.add_argument("--compare", help="run id to compare against in the report (and compare_to)")
    ap.add_argument("--compare-blast-index", type=int,
                    help="build the compare run's scratch from its blast-<N>-*/ (default: its top level)")
    ap.add_argument("--backfill", help="human-authored backfill JSON (format: module docstring)")
    ap.add_argument("--out", help="bundle dir (default ${BENCH_SITE_REPO:-<repo>/../tn-benchmarks}/runs/<run>)")
    ap.add_argument("--force", action="store_true", help="delete and rebuild benchmark/work/report/<run>")
    ap.add_argument("--allow-provenance-mismatch", action="store_true",
                    help="publish even when the node logs do not confirm the upstream sha (adds a caveat)")
    ap.add_argument("--analysis-sha", help="generator.analysis_sha (default: backfill, else the tools' git HEAD)")
    ap.add_argument("--archived-report", help="copy this report.html byte for byte instead of building one")
    ap.add_argument("--no-results", action="store_true", help="no raw run: run.json from the backfill alone")
    ap.add_argument("--txgen-bench", help="tool dir (default ${BENCH_TXGEN_REPO:-<repo>/../tn-transaction-generator}/bench)")
    a = ap.parse_args(argv)
    if a.analysis_sha and not (7 <= len(a.analysis_sha) <= 40 and HEX_RE.fullmatch(a.analysis_sha)):
        ap.error("--analysis-sha must be 7-40 lowercase hex digits")
    for name in ("run", "compare"):
        v = getattr(a, name)
        if v is not None and (not RUN_ID_RE.fullmatch(v) or v in RESERVED_SCRATCH_NAMES):
            ap.error("--%s %r is not a run id" % (name, v))
    if a.no_results:
        if not a.archived_report or not a.backfill:
            ap.error("--no-results needs --archived-report and --backfill")
        if a.blast_index is not None:
            ap.error("--no-results and --blast-index exclude each other")
    for name in ("blast_index", "compare_blast_index"):
        if getattr(a, name) is not None and getattr(a, name) < 0:
            ap.error("--%s must be >= 0" % name.replace("_", "-"))
    if a.compare_blast_index is not None and not a.compare:
        ap.error("--compare-blast-index needs --compare")
    return a


def main(argv=None):
    a = parse_args(argv)
    try:
        return _main(a)
    except BundleError as e:
        print("make_bundle: error: %s" % e, file=sys.stderr)
        return 1


def _main(a):
    run_id = a.run
    site_repo = os.environ.get("BENCH_SITE_REPO") or os.path.join(os.path.dirname(REPO_ROOT), "tn-benchmarks")
    txgen = os.environ.get("BENCH_TXGEN_REPO") or os.path.join(os.path.dirname(REPO_ROOT), "tn-transaction-generator")
    tool_dir = os.path.abspath(a.txgen_bench or os.path.join(txgen, "bench"))
    out = os.path.abspath(a.out or os.path.join(site_repo, "runs", run_id))
    site_checkout = check_out_dir(out, run_id)
    prepare_out(out)  # refuse a foreign out dir before any work (checked again when writing)
    backfill = load_backfill(a.backfill)
    compare_to = a.compare or backfill.get("compare_to")
    archived = os.path.abspath(a.archived_report) if a.archived_report else None
    if archived and (os.path.islink(archived) or not os.path.isfile(archived)):
        raise BundleError("--archived-report %s is not a regular file" % a.archived_report)
    log(S_SETUP, "run %s (%s)%s -> %s (tools %s)"
        % (run_id, blast_label(a.blast_index),
           ", compare %s (%s)" % (a.compare, blast_label(a.compare_blast_index)) if a.compare else "", out, tool_dir))

    if a.no_results:
        if os.path.isdir(os.path.join(RESULTS_ROOT, run_id)):
            warn("--no-results: ignoring the existing results dir for %s" % run_id)
        report = report_block(archived, archived, backfill)
        run_doc = assemble_from_backfill(run_id, a, backfill, report, compare_to)
        log(S_ASSEMBLE, "run.json from the backfill (no results)")
        install_bundle(out, run_doc, archived, None, None, site_checkout, site_repo)
        return _summary(run_doc)

    for f in ("aggregate.py", "derive-sizing.py", "build-report.py"):
        if not os.path.isfile(os.path.join(tool_dir, f)):
            raise BundleError("tool dir %s lacks %s" % (tool_dir, f))
    if a.compare and not archived:
        check_compare(a.compare, a.compare_blast_index, run_id, a.force)
    elif a.compare_blast_index is not None:
        warn("--compare-blast-index is unused: with --archived-report no compare inputs are built")

    scratch = prepare_scratch(run_id, a.blast_index, a.force)
    raw_manifest = _load_input(os.path.join(scratch, "manifest.json"))
    # Provenance first (it only needs the node logs, read in place in results/<run>/logs/, and the
    # raw manifest, where node_git_sha and friends are unscrubbed), so a mismatch refuses before
    # the slow report build.
    prov = provenance_step(results_path(run_id), raw_manifest, backfill, a.allow_provenance_mismatch)
    run_tools(scratch, tool_dir)
    scrubbed = scrub_scratch(scratch)
    if archived:
        report_src = archived
        log(S_REPORT, "archived report %s (sha256 %s)" % (os.path.basename(archived), _sha256(archived)[:12]))
    else:
        compare_rel = ensure_compare(a.compare, a.compare_blast_index, tool_dir, a.force) if a.compare else None
        report_src = build_report(scrubbed, tool_dir, compare_rel)

    manifest = _load_input(os.path.join(scrubbed, "manifest.json"))
    metrics = _load_input(os.path.join(scrubbed, "metrics.json"))
    combined = _load_input(os.path.join(scrubbed, "combined.json"))
    built, tps5, series_doc = windows_step(scratch, combined)
    blasters_docs = win.load_blasters(os.path.join(scratch, "blasters"))
    kpis_list, headline, recovery, kpi_caveats = kpis_step(scrubbed, combined, metrics, manifest, built, backfill)
    cert_section = certification_html(manifest)
    if archived:
        if cert_section:
            log(S_REPORT, "archived report kept byte for byte: no Certification by node table (caveat only)")
    elif add_certification_section(report_src, cert_section):
        log(S_REPORT, "Certification by node table added (%d below threshold)" % len(_cert_failures(manifest)))
    report = report_block(report_src, archived, backfill)
    run_doc = assemble(run_id, a, manifest, metrics, combined, blasters_docs, prov, built, tps5, kpis_list,
                       headline, recovery, kpi_caveats, report, compare_to, backfill, tool_dir)
    log(S_ASSEMBLE, "%d kpis, %d caveats, %d chaos events, consensus %s, workload %s"
        % (len(run_doc["kpis"]), len(run_doc["caveats"]), len(run_doc["chaos"]),
           "set" if run_doc["consensus"] else "null", "set" if run_doc["workload"] else "null"))
    install_bundle(out, run_doc, report_src, series_doc, raw_manifest, site_checkout, site_repo)
    return _summary(run_doc)


def _summary(doc):
    head = next((k for k in doc["kpis"] if k["id"] == doc.get("headline")), None)
    if head is None:
        head_txt = "none"
    elif "value" in head:
        head_txt = "%s = %s %s" % (head["id"], head["value"], head["unit"])
    else:
        head_txt = "%s = %s-%s %s" % (head["id"], head["range"][0], head["range"][1], head["unit"])
    up = doc["upstream"]
    print("make_bundle: OK %s in %.1fs | headline %s | upstream %s (%s) | report sha256 %s"
          % (doc["id"], time.time() - _T0, head_txt, up.get("sha") or up.get("short") or "unknown",
             up["evidence"], doc["report"]["sha256"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
