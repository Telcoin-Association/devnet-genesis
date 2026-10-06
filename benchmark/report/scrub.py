#!/usr/bin/env python3
"""Input-side leak scrubber for benchmark bundles (stdlib only, Python 3.9+).

Raw run results carry internal detail that must never reach the public site:
internal and external IPs, GCE instance ids, the GCP project, bucket names,
the Grafana host, operator notes and local paths. This module is the first
gate. The site repository's scrub.py runs later as the second, final gate.

Two jobs:

1. ``scrub_inputs(scratch_dir, scrubbed_dir)`` writes scrubbed copies of
   manifest.json, metrics.json, combined.json and sizing.json (and copies
   sampler/*.csv) so build-report.py only ever sees clean inputs.
2. ``scan_dir(bundle_dir, manifest)`` scans a finished bundle. Findings name
   the file, line and rule, never the matched text, so a public CI log does
   not re-publish the leak it reports.

What the scrub does to strings, in every file:

* Dotted quads in the manifest's IP map become the instance name. Every other
  dotted quad (except 0.0.0.0 and 127.0.0.1) becomes ``redacted-ip``. This is
  wider than RFC 1918 on purpose: the site gate rejects any dotted quad.
* An image path in a private registry (``<host>pkg.dev/<private-project>/<repo>/``)
  loses that prefix, so ``txgen_image`` keeps its image name and tag.
* An absolute host path (/Users, /home, /private, /var/folders, /root, /tmp)
  becomes its basename. Container paths such as /var/lib/bench or /etc/txgen
  are not secrets and are kept.

Keys named ``internal_ip``, ``external_ip``, ``instance_id``, ``node_url``,
``grafana_url``, ``bucket``, ``bucket_name`` or ``bucket_prefix`` are dropped
wherever they occur, because the site gate flags those names on their own.

Command line::

    python3 scrub.py inputs <scratch_dir> <scrubbed_dir>
    python3 scrub.py scan <dir> [--manifest raw-manifest.json]

Both exit 1 when the scrubbed or scanned tree has findings.
"""

import argparse
import ipaddress
import json
import os
import re
import shutil
import sys
from urllib.parse import urlsplit

__all__ = [
    "DENYLIST",
    "REDACTED_IP",
    "ip_label_map",
    "replace_ips",
    "scan_dir",
    "scan_text",
    "scrub_combined",
    "scrub_inputs",
    "scrub_manifest",
    "scrub_metrics",
    "scrub_sizing",
]

REDACTED_IP = "redacted-ip"
REDACTED_HOST_PORT = 8545

# Dotted quads that are never a leak (the site gate allows the same two).
ALLOWED_IPV4 = ("0.0.0.0", "127.0.0.1")

# RFC 1918, shared address space (RFC 6598) and link-local.
PRIVATE_NETS = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16")
)

# GCP projects whose registry paths and names are internal. The manifest's own
# ``project`` is added at run time. Written in two pieces so this file does not
# contain the literal it scans for.
PRIVATE_PROJECTS = ("tn-" "devnet",)

# Keys dropped wherever they occur, in every scrubbed file.
DROP_KEYS_ANYWHERE = (
    "internal" "_ip",
    "external" "_ip",
    "instance" "_id",
    "node" "_url",
    "grafana_url",
    "bucket",
    "bucket_name",
    "bucket_prefix",
)

# Per-entry keys on manifest instances/blasters that identify a host.
_HOST_KEY = re.compile(r"(?:^|_)(?:ip|ips|id|ids)$")

_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
# Same boundaries as the site gate: not glued to a word character or a dot.
IPV4_RE = re.compile(r"(?<![\w.])" + _OCTET + r"(?:\." + _OCTET + r"){3}(?!\w|\.[0-9])")

# Host-local absolute paths. Container paths (/var/lib, /etc, /out) are kept.
_LOCAL_PATH_RE = re.compile(
    r"(?<![\w.-])(?:/Users|/home|/private|/var/folders|/root|/tmp)/[^\s\"'<>|,;]*"
)

_SAMPLER_HEADER_CELL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAMPLER_VALUE_CELL = re.compile(r"^(?:-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)?$")


def _registry_re(projects):
    alt = "|".join(re.escape(p) for p in sorted(set(projects), key=len, reverse=True))
    return re.compile(r"[A-Za-z0-9.-]*pkg\.dev/(?:%s)/[^/\s\"'@:]+/" % alt)


def _is_private(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in PRIVATE_NETS)


# ---------------------------------------------------------------------------
# Scrub context: carries the IP map and project names, collects the report
# ---------------------------------------------------------------------------


class _Ctx(object):
    def __init__(self, ipmap, projects=()):
        self.ipmap = dict(ipmap or {})
        self.names = set(self.ipmap.values())
        self.projects = tuple(sorted(set(PRIVATE_PROJECTS) | set(p for p in projects if p)))
        self.registry = _registry_re(self.projects)
        self.dropped = []
        self.replaced_ips = 0
        self.replaced_paths = 0
        self.rewritten_images = 0

    def drop(self, path):
        if path not in self.dropped:
            self.dropped.append(path)

    # String rewrites ------------------------------------------------------

    def _ip(self, match):
        ip = match.group(0)
        if ip in ALLOWED_IPV4:
            return ip
        self.replaced_ips += 1
        return self.ipmap.get(ip, REDACTED_IP)

    def _path(self, match):
        self.replaced_paths += 1
        base = os.path.basename(match.group(0).rstrip("/"))
        return base or "redacted-path"

    def _image(self, match):
        self.rewritten_images += 1
        return ""

    def ips(self, s):
        return IPV4_RE.sub(self._ip, s)

    def string(self, s):
        s = self.ips(s)
        s = self.registry.sub(self._image, s)
        return _LOCAL_PATH_RE.sub(self._path, s)

    def walk(self, obj, fn):
        """New copy of ``obj`` with ``fn`` applied to every string and key."""
        if isinstance(obj, dict):
            return {(fn(k) if isinstance(k, str) else k): self.walk(v, fn) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.walk(v, fn) for v in obj]
        if isinstance(obj, str):
            return fn(obj)
        return obj

    # Key drops -------------------------------------------------------------

    def drop_anywhere(self, obj, prefix):
        """New copy of ``obj`` without DROP_KEYS_ANYWHERE keys, recorded under ``prefix``."""
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                path = "%s.%s" % (prefix, k)
                if k in DROP_KEYS_ANYWHERE:
                    self.drop(path)
                    continue
                out[k] = self.drop_anywhere(v, path)
            return out
        if isinstance(obj, list):
            return [self.drop_anywhere(v, prefix + "[]") for v in obj]
        return obj


def _ctx_for(ipmap, ctx, projects=()):
    return ctx if ctx is not None else _Ctx(ipmap, projects)


def _drop_entry_keys(entries, prefix, ctx, extra=()):
    """Copy of a list of dicts without host-identifying keys."""
    out = []
    for e in entries or []:
        if not isinstance(e, dict):
            out.append(e)
            continue
        kept = {}
        for k, v in e.items():
            if _HOST_KEY.search(k) or k in extra:
                ctx.drop("%s[].%s" % (prefix, k))
                continue
            kept[k] = v
        out.append(kept)
    return out


def _drop(d, key, path, ctx):
    if isinstance(d, dict) and key in d:
        del d[key]
        ctx.drop(path)


# ---------------------------------------------------------------------------
# Public scrub API
# ---------------------------------------------------------------------------


def ip_label_map(manifest):
    """``{ip: instance_name}`` for every IP the manifest's instances and blasters carry."""
    ipmap = {}
    for group in ("instances", "blasters"):
        for e in (manifest or {}).get(group) or []:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            for k, v in e.items():
                if not k.endswith(("_ip", "_ips")):
                    continue
                for ip in v if isinstance(v, list) else [v]:
                    if isinstance(ip, str) and IPV4_RE.fullmatch(ip) and ip not in ALLOWED_IPV4:
                        ipmap.setdefault(ip, e["name"])
    return ipmap


def replace_ips(obj, ipmap):
    """New copy of any JSON value with dotted quads mapped to instance names.

    A quad in ``ipmap`` becomes its instance name; any other quad except
    0.0.0.0 and 127.0.0.1 becomes ``redacted-ip``. Keys are rewritten too.
    """
    ctx = _Ctx(ipmap)
    return ctx.walk(obj, ctx.ips)


def scrub_manifest(m, ipmap, ctx=None):
    """Scrubbed copy of a tn-bench-manifest/v1 document."""
    ctx = _ctx_for(ipmap, ctx, [(m or {}).get("project")])
    out = json.loads(json.dumps(m))
    _drop(out, "project", "manifest.project", ctx)
    _drop(out, "notes", "manifest.notes", ctx)
    # The harness's archive record: its uri names the private archive bucket and the project.
    _drop(out, "archive", "manifest.archive", ctx)
    if isinstance(out.get("instances"), list):
        out["instances"] = _drop_entry_keys(out["instances"], "manifest.instances", ctx)
    if isinstance(out.get("blasters"), list):
        out["blasters"] = _drop_entry_keys(out["blasters"], "manifest.blasters", ctx, extra=("node" "_url",))
    prom = out.get("prometheus")
    if isinstance(prom, dict):
        for k in [k for k in prom if k == "url" or k.endswith("_url")]:
            _drop(prom, k, "manifest.prometheus." + k, ctx)
    for section in ("fund", "blast"):
        sec = out.get(section)
        if isinstance(sec, dict):
            for k in [k for k in sec if "bucket" in k]:
                _drop(sec, k, "manifest.%s.%s" % (section, k), ctx)
    out = ctx.drop_anywhere(out, "manifest")
    return ctx.walk(out, ctx.string)


def scrub_metrics(m, ipmap, ctx=None):
    """Scrubbed copy of a tn-bench-gcp-metrics/v1 document."""
    ctx = _ctx_for(ipmap, ctx, [(m or {}).get("project")])
    out = json.loads(json.dumps(m))
    _drop(out, "project", "metrics.project", ctx)
    if isinstance(out.get("instances"), list):
        out["instances"] = _drop_entry_keys(out["instances"], "metrics.instances", ctx)
    prom = out.get("prometheus")
    if isinstance(prom, dict):
        # The Prometheus proxy URL names the observability host.
        for k in [k for k in prom if k == "url" or k.endswith("_url")]:
            _drop(prom, k, "metrics.prometheus." + k, ctx)
    out = ctx.drop_anywhere(out, "metrics")
    return ctx.walk(out, ctx.string)


def _node_url(url, ctx):
    try:
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port
    except ValueError:
        host, port, parts = "", None, None
    if host in ctx.ipmap:
        label = ctx.ipmap[host]
    elif host and host in ctx.names:
        label = host
    else:
        label = REDACTED_IP
    if host != label:
        ctx.replaced_ips += 1
    scheme = (parts.scheme if parts is not None and parts.scheme else "http")
    return "%s://%s:%d" % (scheme, label, port or REDACTED_HOST_PORT)


def scrub_combined(c, ipmap, ctx=None):
    """Scrubbed copy of a tn-blast-combined/v2 (or single tn-blast/v2) document.

    ``nodes[].url`` becomes ``http://<instance-name>:<port>``. Strings in
    ``args`` dicts (and everywhere else) go through the IP, registry and
    local-path rewrites; container paths are kept.
    """
    ctx = _ctx_for(ipmap, ctx)
    out = json.loads(json.dumps(c))
    for n in out.get("nodes") or []:
        if isinstance(n, dict) and isinstance(n.get("url"), str):
            n["url"] = _node_url(n["url"], ctx)
    out = ctx.drop_anywhere(out, "combined")
    return ctx.walk(out, ctx.string)


def scrub_sizing(s, ipmap, ctx=None):
    """Scrubbed copy of a tn-bench-sizing/v1 document (string rewrites only)."""
    ctx = _ctx_for(ipmap, ctx)
    out = ctx.drop_anywhere(s, "sizing")
    return ctx.walk(out, ctx.string)


def _check_sampler_csv(path):
    """Raise ValueError unless the CSV is a name header plus numeric rows."""
    with open(path, "r", encoding="utf-8", errors="strict") as fh:
        lines = fh.read().splitlines()
    if not lines:
        return
    for cell in lines[0].split(","):
        if not _SAMPLER_HEADER_CELL.match(cell):
            raise ValueError("%s:1: non-identifier header cell" % os.path.basename(path))
    for i, line in enumerate(lines[1:], 2):
        for cell in line.split(","):
            if not _SAMPLER_VALUE_CELL.match(cell):
                raise ValueError("%s:%d: non-numeric cell" % (os.path.basename(path), i))


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _dump(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=False, ensure_ascii=False)
        fh.write("\n")


def scrub_inputs(scratch_dir, scrubbed_dir):
    """Write scrubbed report inputs from ``scratch_dir`` into ``scrubbed_dir``.

    manifest.json, metrics.json and combined.json are required; sizing.json
    and sampler/*.csv are optional. Returns a summary with the IP map size,
    the dropped key paths and replacement counts.
    """
    manifest = _load(os.path.join(scratch_dir, "manifest.json"))
    ipmap = ip_label_map(manifest)
    ctx = _Ctx(ipmap, [manifest.get("project")])
    os.makedirs(scrubbed_dir, exist_ok=True)

    jobs = (
        ("manifest.json", scrub_manifest, True),
        ("metrics.json", scrub_metrics, True),
        ("combined.json", scrub_combined, True),
        ("sizing.json", scrub_sizing, False),
    )
    written = []
    for name, fn, required in jobs:
        src = os.path.join(scratch_dir, name)
        if not os.path.exists(src):
            if required:
                raise FileNotFoundError(src)
            continue
        doc = manifest if name == "manifest.json" else _load(src)
        _dump(fn(doc, ipmap, ctx=ctx), os.path.join(scrubbed_dir, name))
        written.append(name)

    sampler_src = os.path.join(scratch_dir, "sampler")
    csvs = []
    if os.path.isdir(sampler_src):
        sampler_dst = os.path.join(scrubbed_dir, "sampler")
        os.makedirs(sampler_dst, exist_ok=True)
        for fn in sorted(os.listdir(sampler_src)):
            src = os.path.join(sampler_src, fn)
            if not fn.endswith(".csv") or not os.path.isfile(src) or os.path.islink(src):
                continue
            _check_sampler_csv(src)
            shutil.copyfile(src, os.path.join(sampler_dst, fn))
            csvs.append(fn)

    return {
        "ipmap_size": len(ipmap),
        "dropped": list(ctx.dropped),
        "replaced_ips": ctx.replaced_ips,
        "replaced_paths": ctx.replaced_paths,
        "rewritten_images": ctx.rewritten_images,
        "files": written + ["sampler/" + c for c in csvs],
    }


# ---------------------------------------------------------------------------
# Leak scan
# ---------------------------------------------------------------------------

# (rule, regex). Literals are split so this file passes its own scan.
DENYLIST = (
    ("internal-name", re.compile(
        "|".join(re.escape(w) for w in (
            "tn-" "devnet", "gs:" "//", "obs." "devnet", "bench-" "txgen-",
            "internal" "_ip", "external" "_ip", "instance" "_id", "node" "_url",
        )), re.IGNORECASE)),
    ("local-path", re.compile(
        "|".join(re.escape(w) for w in (
            "/" "Users/", "/" "home/", "/private" "/tmp/", "/private" "/var/", "/var" "/folders/",
        )) + "|(?i:" + re.escape("C:\\" "Users") + ")")),
    ("artifact-runtime", re.compile(
        "|".join(re.escape(w) for w in ("claude" ".ai", "__FRAME" "_PREAMBLE", "frame" "-runtime")),
        re.IGNORECASE)),
    ("private-key", re.compile(re.escape("-----" "BEGIN"))),
    ("secret-assignment", re.compile(r"(?:passphrase|mnemonic|private_key)[\"']?\s*[:=]", re.IGNORECASE)),
    ("email", re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}"
        r"(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24}(?![A-Za-z0-9-])")),
    ("gcp-internal-dns", re.compile(
        r"\.c\.[a-z][a-z0-9-]{0,62}\.internal\b|\bmetadata\.google\.internal\b", re.IGNORECASE)),
    ("token", re.compile(
        r"ghp_[A-Za-z0-9]{20,}|" + re.escape("github" "_pat_")
        + r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|ya29\.")),
    ("hex64", re.compile(r"\b0x[0-9a-fA-F]{64}")),
)

_ASSET_SUFFIXES = frozenset(
    "png jpg jpeg gif svg webp avif ico bmp js mjs css json html htm woff woff2 ttf otf map wasm".split()
)
_HEX64_KEY_LINE = re.compile(r"\"(?:sha256|digest|image_digest)\"\s*:")
EXPECTED_SUFFIXES = (".json", ".csv", ".html")


def _manifest_rules(manifest):
    """Literal rules built from the raw (unscrubbed) manifest."""
    if isinstance(manifest, str):
        manifest = _load(manifest)
    manifest = manifest or {}
    ips, ids, names = set(), set(), set()
    for group in ("instances", "blasters"):
        for e in manifest.get(group) or []:
            if not isinstance(e, dict):
                continue
            for k, v in e.items():
                vals = v if isinstance(v, list) else [v]
                if k.endswith(("_ip", "_ips")):
                    ips.update(x for x in vals if isinstance(x, str) and x and x not in ALLOWED_IPV4)
                elif k.endswith(("_id", "_ids")):
                    ids.update(str(x) for x in vals if isinstance(x, (str, int)) and str(x))
    project = manifest.get("project")
    if isinstance(project, str) and project:
        names.add(project)
    for v in _strings(manifest):
        for m in re.finditer(r"gs://([A-Za-z0-9._-]+)", v):
            names.add(m.group(1))
    graf = (manifest.get("prometheus") or {}).get("grafana_url")
    if isinstance(graf, str):
        try:
            host = urlsplit(graf).hostname
        except ValueError:
            host = None
        if host:
            names.add(host)
    rules = []

    def lit(rule, values, flags=0):
        values = sorted(values, key=len, reverse=True)
        if values:
            alt = "|".join(re.escape(x) for x in values)
            rules.append((rule, re.compile(r"(?<![\w.])(?:%s)(?![\w]|\.[0-9])" % alt, flags)))

    lit("manifest-ip", ips)
    lit("manifest-instance-id", ids)
    lit("manifest-name", names, re.IGNORECASE)
    return rules


def _strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            for s in _strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in _strings(v):
                yield s
    elif isinstance(obj, str):
        yield obj


def scan_text(text, name, manifest=None, _rules=None):
    """Findings ``"<name>:<line>: <rule>"`` for ``text``. Never echoes the match."""
    rules = list(DENYLIST) + (_rules if _rules is not None else _manifest_rules(manifest))
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        hit = []
        for m in IPV4_RE.finditer(line):
            ip = m.group(0)
            if ip in ALLOWED_IPV4:
                continue
            rule = "private-ip" if _is_private(ip) else "ipv4"
            if rule not in hit:
                hit.append(rule)
        for rule, rx in rules:
            if rule in hit:
                continue
            for m in rx.finditer(line):
                if rule == "email" and m.group(0).rsplit(".", 1)[-1].lower() in _ASSET_SUFFIXES:
                    continue
                if rule == "hex64" and _HEX64_KEY_LINE.search(line):
                    continue
                hit.append(rule)
                break
        findings.extend("%s:%d: %s" % (name, lineno, r) for r in hit)
    return findings


def scan_dir(path, manifest=None):
    """Scan every file under ``path``; returns findings (empty when clean)."""
    rules = _manifest_rules(manifest)
    findings = []
    if os.path.isfile(path):
        entries = [(os.path.dirname(path), os.path.basename(path))]
    else:
        entries = []
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for d in list(dirs):
                if os.path.islink(os.path.join(root, d)):
                    entries.append((root, d))
            for fn in sorted(files):
                entries.append((root, fn))
    base = path if os.path.isdir(path) else os.path.dirname(path)
    for root, fn in entries:
        full = os.path.join(root, fn)
        rel = os.path.relpath(full, base)
        if os.path.islink(full):
            findings.append("%s:0: symlink" % rel)
            continue
        if not os.path.isfile(full):
            findings.append("%s:0: unexpected-file" % rel)
            continue
        with open(full, "rb") as fh:
            raw = fh.read()
        if not fn.endswith(EXPECTED_SUFFIXES) or b"\x00" in raw or raw[:2] == b"\x1f\x8b":
            findings.append("%s:0: unexpected-file" % rel)
        findings.extend(scan_text(raw.decode("utf-8", errors="replace"), rel, _rules=rules))
    return findings


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _rule_counts(findings):
    counts = {}
    for f in findings:
        rule = f.rsplit(": ", 1)[-1]
        counts[rule] = counts.get(rule, 0) + 1
    return counts


def _print_findings(findings, limit=200):
    for f in findings[:limit]:
        print(f)
    if len(findings) > limit:
        print("... %d more" % (len(findings) - limit))
    print("findings by rule: %s" % json.dumps(_rule_counts(findings), sort_keys=True))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scrub benchmark inputs and scan bundles for leaks.")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    p_in = sub.add_parser("inputs", help="write scrubbed report inputs")
    p_in.add_argument("scratch_dir")
    p_in.add_argument("scrubbed_dir")
    p_scan = sub.add_parser("scan", help="scan a directory or file for leaks")
    p_scan.add_argument("dir")
    p_scan.add_argument("--manifest", help="raw (unscrubbed) manifest.json")
    a = ap.parse_args(argv)

    if a.cmd == "inputs":
        summary = scrub_inputs(a.scratch_dir, a.scrubbed_dir)
        print(json.dumps(summary, indent=1))
        raw_manifest = os.path.join(a.scratch_dir, "manifest.json")
        findings = scan_dir(a.scrubbed_dir, raw_manifest)
    else:
        findings = scan_dir(a.dir, a.manifest)
    if findings:
        _print_findings(findings)
        return 1
    print("scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
