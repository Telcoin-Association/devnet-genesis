#!/usr/bin/env python3
"""devnet-network-config.py: render, merge and validate each devnet node's network-config.

The node reads <datadir>/network-config once, at startup
(telcoin-network crates/node/src/manager/node.rs:1014). When the file is missing it writes
a serde_yaml dump of NetworkConfig::default() and runs with it (crates/config/src/traits.rs:56-86),
which means admission Open. So ours has to be in place before the first start.

What a rendered file holds (field names and shapes pinned at telcoin-network 3f9b0709c):

  admission:                      # network.rs:479-493 AdmissionConfig
    mode: Closed                  # network.rs:467-477 AdmissionMode, no rename: case-sensitive
    snapshot_max_age_secs: 300
  bootstrap_peers:                # observers only. MAP keyed by BLS key (network.rs:59); a
    <hub BLS>: <BootstrapServer>  # nonempty map replaces the genesis bootstrap set in full
  trusted_nodes:                  # the hub and the observers. MAP keyed by BLS key (network.rs:64)
    <peer BLS>:                   # TrustedNode, deny_unknown_fields (trusted.rs:12-19)
      primary: <P2pNode>
      workers:                    # MAP keyed by worker id, exactly 0..<LOCAL worker count>
        0: <P2pNode>              # (trusted.rs:92-104; node.rs:1037 passes the local count)
  committee_peers:                # every node. MAP keyed by BLS key (network.rs:72), the
    <BLS>: <BootstrapServer>      # committee.yaml bootstrap_servers block copied verbatim

  BootstrapServer = {primary: P2pNode, workers: [P2pNode, ...]}  (LIST; types committee.rs:215-231)
  P2pNode         = {network_address, network_key, rpc}          (types committee.rs:87-100)

Top-level keys appear in NetworkConfig's declaration order (network.rs:43-72), with a merged
`hostname:` line in its own slot after `admission`.

NetworkConfig is #[serde(default)] WITHOUT deny_unknown_fields, so the node silently ignores an
unknown or misspelt top-level key, and a misspelt `admission` leaves it Open. AdmissionConfig is
the same. Hence the strict validator here: exact key names, exact nesting, `Closed` exactly,
list-vs-map worker shapes, one committee_peers entry per committee member, every /p2p/<PeerId>
equal to the PeerId derived from its network_key, a trailing newline, and on merge the
existing `hostname:` line kept verbatim. Those checks run on PyYAML's reading of the file,
and the node parses with serde_yaml 0.8, which reads some YAML differently (a leading BOM,
`<<` merge keys). So outside its one `hostname:` line a file must also be byte for byte the
emitter's output, and a BOM, merge keys, anchors, aliases and tags are refused by name.

PeerId derivation (stdlib): network_key is base58(protobuf-encoded libp2p PublicKey)
(types crypto/network.rs:18-23,51-62). The PeerId is base58 of the multihash of those bytes:
identity (0x00) when they are at most 42 bytes long (every ed25519 key), else sha256 (0x12).

Subcommands (all share the context flags --committee/--genesis-dir/--nodes/--hub):
  render   --out-dir DIR                  write <node>.yaml for every node, then validate each
  validate --node N FILE [--existing E]   check FILE as node N's network-config
  merge    --rendered R [--existing E] --out O
                                          R with E's hostname line, nothing else of E
                                          (no context flags needed)

DEPENDENCY: PyYAML (`import yaml`), used ONLY to PARSE (committee.yaml, node-info files, the
files being validated). Duplicate keys are rejected. Every byte written comes from the
deterministic emitter below (2-space indent, stable key order, committee.yaml's quoting), and
render checks that the emitter reproduces committee.yaml's bootstrap_servers block byte for byte.
Install PyYAML with `sudo apt-get install python3-yaml` or `python3 -m pip install --user pyyaml`.
"""

import argparse
import copy
import difflib
import hashlib
import itertools
import json
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - environment check
    sys.stderr.write(
        "devnet-network-config.py needs PyYAML to PARSE YAML (it never uses it to write).\n"
        "Install it with: sudo apt-get install python3-yaml   (or: python3 -m pip install --user pyyaml)\n"
    )
    sys.exit(3)

ADMISSION_MODE = "Closed"
SNAPSHOT_MAX_AGE_SECS = 300
# Top-level keys we write, in NetworkConfig's declaration order (network.rs:43-72).
TOP_ORDER = ("admission", "hostname", "bootstrap_peers", "trusted_nodes", "committee_peers")
# Every NetworkConfig field (network.rs:27-75), for "did you mean" hints on misspelt keys.
NETWORK_CONFIG_FIELDS = (
    "libp2p_config", "sync_config", "quic_config", "process_budget", "serve_budget",
    "peer_config", "admission", "source_admission", "peer_readiness_timeout", "hostname",
    "bootstrap_peers", "trusted_nodes", "committee_peers", "endpoints",
)
HOSTNAME_RE = re.compile(r"^hostname:")


class ConfigError(Exception):
    """A problem with an input or the file under check."""


# --------------------------------------------------------------------------- parsing (PyYAML)

class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (serde rejects them; PyYAML keeps the last)."""


def _construct_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    out = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in out
        except TypeError:
            raise yaml.constructor.ConstructorError(
                None, None, "unhashable mapping key", key_node.start_mark)
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None, None, "duplicate key %r" % (key,), key_node.start_mark)
        out[key] = loader.construct_object(value_node, deep=True)
    return out


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def parse_yaml(text, what):
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ConfigError("%s: YAML parse error: %s" % (what, exc))


def load_yaml_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    return parse_yaml(text, path), text


# --------------------------------------------------------------------------- emitting (own writer)

_NULL_RE = re.compile(r"^(~|null|Null|NULL)$")
_BOOL_RE = re.compile(
    r"^(y|Y|yes|Yes|YES|n|N|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$")
_INT_RE = re.compile(r"^([-+]?(0|[1-9][0-9]*)|0[0-7]+|0o[0-7]+|0x[0-9a-fA-F]+|0b[01]+)$")
_FLOAT_RE = re.compile(
    r"^([-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?|[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN))$")
_PLAIN_RE = re.compile(r"^[A-Za-z0-9/][A-Za-z0-9._/-]*$")


def _plain_ok(text):
    """A plain scalar only when it is unambiguously a string in YAML 1.1 and 1.2."""
    if not _PLAIN_RE.match(text):
        return False
    return not (_NULL_RE.match(text) or _BOOL_RE.match(text)
                or _INT_RE.match(text) or _FLOAT_RE.match(text))


def emit_scalar(value):
    if value is None:
        return "~"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value if _plain_ok(value) else json.dumps(value, ensure_ascii=True)
    raise ConfigError("cannot emit a value of type %s" % type(value).__name__)


def _emit_node(value, indent, lines):
    """Emit a mapping body at `indent` spaces (serde_yaml block style, as committee.yaml)."""
    pad = " " * indent
    for key, item in value.items():
        head = "%s%s:" % (pad, emit_scalar(key))
        _emit_value(head, item, indent, lines)


def _emit_value(head, item, indent, lines):
    if isinstance(item, dict):
        if not item:
            lines.append(head + " {}")
        else:
            lines.append(head)
            _emit_node(item, indent + 2, lines)
    elif isinstance(item, list):
        if not item:
            lines.append(head + " []")
        else:
            lines.append(head)
            _emit_list(item, indent + 2, lines)
    else:
        lines.append("%s %s" % (head, emit_scalar(item)))


def _emit_list(items, indent, lines):
    pad = " " * indent
    for item in items:
        if isinstance(item, dict) and item:
            sub = []
            _emit_node(item, indent + 2, sub)
            sub[0] = pad + "- " + sub[0][indent + 2:]
            lines.extend(sub)
        elif isinstance(item, (dict, list)):
            raise ConfigError("cannot emit an empty or nested list item")
        else:
            lines.append("%s- %s" % (pad, emit_scalar(item)))


def emit_config(cfg, hostname_line=None):
    """Emit our top-level keys in TOP_ORDER; `hostname_line` is a raw line kept verbatim."""
    unknown = [key for key in cfg if key not in TOP_ORDER or key == "hostname"]
    if unknown:
        raise ConfigError("emit_config: unexpected keys %s" % unknown)
    lines = []
    for key in TOP_ORDER:
        if key == "hostname":
            if hostname_line is not None:
                lines.append(hostname_line)
        elif key in cfg:
            _emit_value("%s:" % key, cfg[key], 0, lines)
    text = "\n".join(lines) + "\n"
    # The emitter's output must parse back to exactly what it was given.
    back = parse_yaml(text, "emitter output")
    back.pop("hostname", None)
    if back != cfg:
        raise ConfigError("emitter round trip mismatch (bug in devnet-network-config.py)")
    return text


# --------------------------------------------------------------------------- PeerId derivation

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(text):
    num = 0
    for char in text:
        index = _B58.find(char)
        if index < 0:
            raise ValueError("not base58: %r" % char)
        num = num * 58 + index
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * (len(text) - len(text.lstrip("1"))) + body


def b58encode(data):
    num = int.from_bytes(data, "big")
    out = ""
    while num:
        num, rem = divmod(num, 58)
        out = _B58[rem] + out
    return "1" * (len(data) - len(data.lstrip(b"\x00"))) + out


def peer_id_from_network_key(network_key):
    """PeerId text for a base58 protobuf-encoded libp2p public key (see module docstring)."""
    try:
        raw = b58decode(network_key)
    except ValueError as exc:
        raise ConfigError("network_key %r: %s" % (network_key, exc))
    # protobuf PublicKey: field 1 (varint key type 0..3), field 2 (length-delimited key bytes)
    if len(raw) < 4 or raw[0] != 0x08 or raw[1] > 3 or raw[2] != 0x12 or raw[3] != len(raw) - 4:
        raise ConfigError("network_key %r is not a protobuf-encoded libp2p public key" % network_key)
    if len(raw) <= 42:
        multihash = bytes([0x00, len(raw)]) + raw
    else:
        multihash = bytes([0x12, 32]) + hashlib.sha256(raw).digest()
    return b58encode(multihash)


# --------------------------------------------------------------------------- structural checks

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _keyset(value, where, required, optional=()):
    """Errors for a mapping whose keys must be `required` plus any of `optional`, exactly."""
    if not isinstance(value, dict):
        return ["%s: expected a mapping, found %s" % (where, _describe(value))]
    errs = []
    allowed = set(required) | set(optional)
    for key in value:
        if key not in allowed:
            hint = difflib.get_close_matches(str(key), sorted(allowed), n=1)
            errs.append("%s: unknown key %r%s" % (
                where, key, " (did you mean %r?)" % hint[0] if hint else ""))
    for key in required:
        if key not in value:
            errs.append("%s: missing key %r" % (where, key))
    return errs


def _describe(value):
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    return "%s %r" % (type(value).__name__, value)


def check_p2p_node(node, where, bindings, ident):
    """P2pNode {network_address, network_key, rpc}; records (where, PeerId, ident) in `bindings`.

    `ident` is (BLS key, swarm), swarm being "primary" or "worker <id>".
    """
    errs = _keyset(node, where, ("network_address", "network_key"), ("rpc",))
    if not isinstance(node, dict):
        return errs
    key = node.get("network_key")
    addr = node.get("network_address")
    peer = None
    if not isinstance(key, str) or not key:
        errs.append("%s.network_key: expected a base58 string, found %s" % (where, _describe(key)))
    else:
        try:
            peer = peer_id_from_network_key(key)
        except ConfigError as exc:
            errs.append("%s: %s" % (where, exc))
    if not isinstance(addr, str) or not addr.startswith("/"):
        errs.append("%s.network_address: expected a multiaddr string, found %s" % (where, _describe(addr)))
    else:
        parts = addr.split("/")[1:]
        p2p = [i for i, part in enumerate(parts) if part == "p2p"]
        if len(parts) < 2 or "" in parts:
            errs.append("%s.network_address %r: not a multiaddr" % (where, addr))
        elif not p2p:
            pass  # no /p2p suffix: nothing to compare (the node accepts that)
        elif len(p2p) != 1 or p2p[0] != len(parts) - 2:
            errs.append("%s.network_address %r: /p2p/<PeerId> must appear once, last" % (where, addr))
        elif peer and parts[-1] != peer:
            errs.append("%s.network_address: /p2p/%s does not match network_key %s (PeerId %s)"
                        % (where, parts[-1], key, peer))
    rpc = node.get("rpc")
    if rpc is not None:
        errs.extend(_keyset(rpc, where + ".rpc", ("http",), ("ws",)))
        if isinstance(rpc, dict):
            http, ws = rpc.get("http"), rpc.get("ws")
            if not (isinstance(http, str) and re.match(r"^https?://", http)):
                errs.append("%s.rpc.http: expected an http(s) URL, found %s" % (where, _describe(http)))
            if ws is not None and not (isinstance(ws, str) and re.match(r"^wss?://", ws)):
                errs.append("%s.rpc.ws: expected a ws(s) URL, found %s" % (where, _describe(ws)))
    if peer:
        bindings.append((where, peer, ident))
    return errs


def check_bootstrap_server(entry, where, bindings, min_workers, bls):
    """BootstrapServer {primary, workers: LIST}; the legacy `worker:` shape is refused."""
    errs = _keyset(entry, where, ("primary", "workers"))
    if not isinstance(entry, dict):
        return errs
    if "primary" in entry:
        errs.extend(check_p2p_node(entry["primary"], where + ".primary", bindings, (bls, "primary")))
    workers = entry.get("workers")
    if "workers" in entry:
        if not isinstance(workers, list):
            errs.append("%s.workers: must be a LIST (`- network_address: ...`, as committee.yaml "
                        "bootstrap_servers), found %s" % (where, _describe(workers)))
        elif len(workers) < max(1, min_workers):
            errs.append("%s.workers: %d entries, needs at least %d" % (where, len(workers), max(1, min_workers)))
        else:
            for index, worker in enumerate(workers):
                errs.extend(check_p2p_node(worker, "%s.workers[%d]" % (where, index), bindings,
                                           (bls, "worker %d" % index)))
    return errs


def check_trusted_node(entry, where, bindings, local_workers, bls):
    """TrustedNode {primary, workers: MAP 0..local_workers-1} (deny_unknown_fields)."""
    errs = _keyset(entry, where, ("primary", "workers"))
    if not isinstance(entry, dict):
        return errs
    if "primary" in entry:
        errs.extend(check_p2p_node(entry["primary"], where + ".primary", bindings, (bls, "primary")))
    workers = entry.get("workers")
    if "workers" in entry:
        if not isinstance(workers, dict):
            errs.append("%s.workers: must be a MAP keyed by worker id (`0: {...}`), found %s"
                        % (where, _describe(workers)))
        else:
            keys = list(workers)
            if not all(_is_int(k) for k in keys) or sorted(keys) != list(range(local_workers)):
                errs.append("%s.workers: keys must be exactly the integers 0..%d (this node's worker "
                            "count is %d), found %r" % (where, local_workers - 1, local_workers, keys))
            for key in keys:
                errs.extend(check_p2p_node(workers[key], "%s.workers[%s]" % (where, key), bindings,
                                           (bls, "worker %s" % key)))
    return errs


# --------------------------------------------------------------------------- context + expectations

class Context(object):
    """committee.yaml + every node's node-info file, cross-checked."""

    def __init__(self, committee_path, genesis_dir, nodes_spec, hub):
        self.committee_path = committee_path
        self.committee, self.committee_text = load_yaml_file(committee_path)
        if not isinstance(self.committee, dict) or not all(
                k in self.committee for k in ("authorities", "bootstrap_servers")):
            raise ConfigError("%s: needs top-level authorities and bootstrap_servers" % committee_path)
        self.authorities = self.committee["authorities"]
        self.bootstrap_servers = self.committee["bootstrap_servers"]
        self.num_workers = self.committee.get("num_workers", 1)
        if not isinstance(self.authorities, dict) or not isinstance(self.bootstrap_servers, dict):
            raise ConfigError("%s: authorities and bootstrap_servers must be mappings" % committee_path)
        if set(self.authorities) != set(self.bootstrap_servers):
            raise ConfigError("%s: authorities and bootstrap_servers name different BLS keys" % committee_path)
        if not _is_int(self.num_workers) or self.num_workers < 1:
            raise ConfigError("%s: num_workers must be a positive integer" % committee_path)
        bindings = []
        cerrs = []
        for bls, entry in self.bootstrap_servers.items():
            cerrs.extend(check_bootstrap_server(entry, "%s bootstrap_servers[%s]" % (committee_path, _short(bls)),
                                                bindings, self.num_workers, bls))
        if cerrs:
            raise ConfigError("; ".join(cerrs))

        self.nodes = []      # [(name, role)] in fleet order
        self.info = {}       # name -> node-info mapping
        self.bls = {}        # name -> BLS key
        for item in nodes_spec.split(","):
            name, _, role = item.partition("=")
            if not name or role not in ("validator", "observer"):
                raise ConfigError("--nodes: expected name=validator|observer, got %r" % item)
            sub = "validators" if role == "validator" else "observers"
            path = os.path.join(genesis_dir, sub, name + ".yaml")
            info, _ = load_yaml_file(path)
            if not isinstance(info, dict) or not isinstance(info.get("bls_public_key"), str):
                raise ConfigError("%s: no bls_public_key" % path)
            ierrs = _keyset(info.get("p2p_info"), path + " p2p_info", ("primary", "workers"))
            if not ierrs:
                ierrs = check_bootstrap_server(info["p2p_info"], path + " p2p_info", [], 1,
                                               info["bls_public_key"])
            if ierrs:
                raise ConfigError("; ".join(ierrs))
            self.nodes.append((name, role))
            self.info[name] = info
            self.bls[name] = info["bls_public_key"]
            in_committee = self.bls[name] in self.bootstrap_servers
            if role == "validator" and not in_committee:
                raise ConfigError("%s is a validator but its BLS key is not in %s (stale committee.yaml?)"
                                  % (name, committee_path))
            if role == "observer" and in_committee:
                raise ConfigError("%s is an observer but its BLS key is in %s" % (name, committee_path))
            if in_committee:
                self._same_keys(name, path)
        if len(set(self.bls.values())) != len(self.bls):
            raise ConfigError("two nodes share a BLS key")
        validators = set(self.bls[n] for n, r in self.nodes if r == "validator")
        if validators != set(self.authorities):
            raise ConfigError("committee members %d != validators in --nodes %d (stale committee.yaml?)"
                              % (len(self.authorities), len(validators)))
        if hub not in self.bls or dict(self.nodes)[hub] != "validator":
            raise ConfigError("--hub %r must be a validator in --nodes" % hub)
        self.hub = hub
        self.observers = [n for n, r in self.nodes if r == "observer"]

    def _same_keys(self, name, path):
        """A validator's node-info must carry the keys and addresses committee.yaml lists for it."""
        mine = self.info[name]["p2p_info"]
        theirs = self.bootstrap_servers[self.bls[name]]
        pairs = [("primary", mine["primary"], theirs["primary"])]
        pairs += [("workers[%d]" % i, a, b) for i, (a, b) in enumerate(zip(mine["workers"], theirs["workers"]))]
        for label, a, b in pairs:
            for field in ("network_key", "network_address"):
                if a.get(field) != b.get(field):
                    raise ConfigError("%s %s.%s differs from %s (stale committee.yaml or node-info?)"
                                      % (path, label, field, self.committee_path))

    def local_workers(self, name):
        return len(self.info[name]["p2p_info"]["workers"])

    def server_for(self, name):
        """The BootstrapServer-shaped source for a node: committee.yaml, else its node-info."""
        bls = self.bls[name]
        if bls in self.bootstrap_servers:
            return self.bootstrap_servers[bls]
        return self.info[name]["p2p_info"]

    def trusted_entry(self, peer, local):
        source = self.server_for(peer)
        count = self.local_workers(local)
        if len(source["workers"]) < count:
            raise ConfigError("%s has %d workers; trusted_nodes on %s needs workers 0..%d"
                              % (peer, len(source["workers"]), local, count - 1))
        return {"primary": copy.deepcopy(source["primary"]),
                "workers": dict((i, copy.deepcopy(source["workers"][i])) for i in range(count))}

    def trusted_peers_of(self, name):
        if name == self.hub:
            return list(self.observers)
        if name in self.observers:
            return [self.hub]
        return []

    def expected(self, name):
        if name not in self.bls:
            raise ConfigError("unknown node %r (not in --nodes)" % name)
        cfg = {"admission": {"mode": ADMISSION_MODE, "snapshot_max_age_secs": SNAPSHOT_MAX_AGE_SECS}}
        if name in self.observers:
            cfg["bootstrap_peers"] = {self.bls[self.hub]: copy.deepcopy(self.server_for(self.hub))}
        peers = self.trusted_peers_of(name)
        if peers:
            cfg["trusted_nodes"] = dict((self.bls[p], self.trusted_entry(p, name)) for p in peers)
        cfg["committee_peers"] = copy.deepcopy(self.bootstrap_servers)
        return cfg

    def verbatim_check(self, rendered_text):
        """The committee_peers body must equal committee.yaml's bootstrap_servers body, byte for byte."""
        source = _top_block(self.committee_text, "bootstrap_servers")
        ours = _top_block(rendered_text, "committee_peers")
        if source is None or ours is None or source != ours:
            raise ConfigError("committee_peers is not byte-identical to %s bootstrap_servers (the "
                              "emitter's formatting differs from the source; review by hand)" % self.committee_path)


def _short(bls):
    return bls[:12] + "..." if isinstance(bls, str) and len(bls) > 15 else repr(bls)


def _top_block(text, key):
    """The lines under a top-level `key:` up to the next top-level key, or None."""
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if line == key + ":":
            body = []
            for nxt in lines[start + 1:]:
                if nxt and not nxt.startswith(" "):
                    break
                body.append(nxt)
            return body
    return None


# --------------------------------------------------------------------------- hostname + merge

def hostname_line_of(text, what):
    """The existing file's effective `hostname:` line (verbatim), or None when unset or empty."""
    if not text:
        return None
    lines = [line.rstrip("\r") for line in text.split("\n") if HOSTNAME_RE.match(line)]
    if len(lines) > 1:
        raise ConfigError("%s sets hostname %d times (the node refuses a duplicate field); fix it by hand"
                          % (what, len(lines)))
    if not lines:
        return None
    parsed = parse_yaml(lines[0] + "\n", "%s hostname line" % what)
    value = parsed.get("hostname") if isinstance(parsed, dict) else None
    if value is None or value == "":
        return None  # the default file's `hostname: ''`: nothing to keep
    if not isinstance(value, str) or "\n" in value:
        raise ConfigError("%s: hostname must be a one-line string, found %r" % (what, value))
    return lines[0]


def top_level_keys(text):
    """Top-level keys as written at column 0, odd spellings included (for the merge log only)."""
    return [m.group(1) for m in re.finditer(r"^([^\s#][^:\n]*?):(?:[ \t]|$)", text or "", re.M)]


def merge(rendered_text, existing_text, what):
    cfg = parse_yaml(rendered_text, "rendered file")
    if not isinstance(cfg, dict) or "hostname" in cfg:
        raise ConfigError("rendered file must be a mapping without hostname")
    if emit_config(cfg) != rendered_text:
        raise ConfigError("rendered file is not canonical emitter output; re-render it")
    line = hostname_line_of(existing_text, what)
    keys = list(dict.fromkeys(top_level_keys(existing_text)))  # order kept, each once
    replaced = [k for k in keys if k in cfg]
    dropped = [k for k in keys if k not in cfg and k != "hostname"]
    return emit_config(cfg, line), line, replaced, dropped


# --------------------------------------------------------------------------- validation

def _syntax_errors(text, what):
    """YAML features PyYAML and the node's serde_yaml 0.8 read differently, refused outright.

    PyYAML skips a leading byte-order mark and applies `<<` merge keys; serde_yaml 0.8 does
    neither (it reads a key '\\ufeffadmission' or a key '<<', ignores both, and the node runs
    Open). Anchors, aliases and tags are refused too: the emitter never writes them.
    """
    errs = []
    if text.startswith("\ufeff"):
        errs.append("%s: starts with a UTF-8 byte-order mark: the node's serde_yaml reads the first "
                    "key with the mark in front, ignores it as unknown, and runs Open; save without "
                    "a BOM" % what)
    try:
        for token in yaml.scan(text, Loader=_StrictLoader):
            line = token.start_mark.line + 1
            source = text[token.start_mark.index:token.end_mark.index]
            if isinstance(token, yaml.ScalarToken) and token.plain and token.value == "<<":
                errs.append("%s line %d: YAML merge key `<<`: the node's serde_yaml does not merge, "
                            "so the merged keys never reach it; write the keys out" % (what, line))
            elif isinstance(token, (yaml.AnchorToken, yaml.AliasToken, yaml.TagToken)):
                kind = {yaml.AnchorToken: "anchor", yaml.AliasToken: "alias", yaml.TagToken: "tag"}
                errs.append("%s line %d: YAML %s `%s`: not allowed (the emitter never writes one)"
                            % (what, line, kind[type(token)], source))
    except yaml.YAMLError:
        pass  # the parse reports it
    return errs


def _canonical_errors(text, cfg, what):
    """`text` minus its hostname line must be byte for byte what the emitter writes for `cfg`.

    The structural checks run on PyYAML's reading of the file; the node reads it with serde_yaml
    0.8. Holding every byte outside the hostname line to the emitter's output (whose reading the
    serde mirror confirmed) closes any gap between the two parsers: quoting, comments, flow
    style, indentation tricks.
    """
    want = emit_config(dict((k, v) for k, v in cfg.items() if k != "hostname")).split("\n")
    kept = [(num, line) for num, line in enumerate(text.split("\n"), 1) if not HOSTNAME_RE.match(line)]
    lines = [line for _, line in kept]
    if lines == want:
        return []
    index = next(i for i, (a, b) in enumerate(itertools.zip_longest(lines, want)) if a != b)
    num = kept[index][0] if index < len(kept) else kept[-1][0] + 1
    found = repr(lines[index]) if index < len(lines) else "end of file"
    expect = repr(want[index]) if index < len(want) else "end of file"
    return ["%s line %d: not the canonical rendering (found %s, want %s); outside its hostname line "
            "the file must be byte-identical to what `render` writes, so that the node's parser "
            "reads what this one checked; re-render and merge instead of editing by hand"
            % (what, num, found, expect)]


def validate_text(ctx, name, text, what, existing_text=None):
    """Every error found in `text` as node `name`'s network-config (empty list = valid)."""
    errs = []
    if not text:
        return ["%s: empty file" % what]
    if not text.endswith("\n"):
        errs.append("%s: no trailing newline (a later `>> network-config` append would join the last line)" % what)
    if "\r" in text:
        errs.append("%s: carriage return found; use LF line endings" % what)
    errs.extend(_syntax_errors(text, what))
    try:
        cfg = parse_yaml(text, what)
    except ConfigError as exc:
        return errs + [str(exc)]
    if not isinstance(cfg, dict):
        return errs + ["%s: top level must be a mapping, found %s" % (what, _describe(cfg))]

    exp = ctx.expected(name)
    expected_keys = [k for k in TOP_ORDER if k in exp]
    for key in cfg:
        if key not in expected_keys and key != "hostname":
            hint = difflib.get_close_matches(str(key), list(NETWORK_CONFIG_FIELDS), n=1)
            if key in NETWORK_CONFIG_FIELDS:
                why = "not one of the keys %s is meant to carry" % name
            else:
                why = ("the node silently ignores unknown keys, so a misspelt key leaves it Open%s"
                       % (" (did you mean %r?)" % hint[0] if hint else ""))
            errs.append("%s: unexpected top-level key %r: %s" % (what, key, why))
    for key in expected_keys:
        if key not in cfg:
            errs.append("%s: missing top-level key %r" % (what, key))

    adm = cfg.get("admission")
    if "admission" in cfg:
        errs.extend(_keyset(adm, what + " admission", ("mode", "snapshot_max_age_secs")))
        if isinstance(adm, dict):
            mode, age = adm.get("mode"), adm.get("snapshot_max_age_secs")
            if mode != ADMISSION_MODE:
                note = (" (case-sensitive: serde accepts only Open, Grace, Closed)"
                        if isinstance(mode, str) and mode.lower() == ADMISSION_MODE.lower() else "")
                errs.append("%s admission.mode: must be exactly %r, found %r%s" % (what, ADMISSION_MODE, mode, note))
            if not _is_int(age) or age != SNAPSHOT_MAX_AGE_SECS:
                errs.append("%s admission.snapshot_max_age_secs: must be the integer %d, found %r"
                            % (what, SNAPSHOT_MAX_AGE_SECS, age))

    bindings = []
    members = set(ctx.authorities)
    peers = cfg.get("committee_peers")
    if "committee_peers" in cfg:
        if not isinstance(peers, dict):
            errs.append("%s committee_peers: must be a mapping keyed by BLS key, found %s" % (what, _describe(peers)))
        else:
            for bls in members - set(peers):
                errs.append("%s committee_peers: missing committee member %s" % (what, bls))
            for bls in set(peers) - members:
                errs.append("%s committee_peers: %s is not a committee member" % (what, bls))
            for bls, entry in peers.items():
                errs.extend(check_bootstrap_server(entry, "%s committee_peers[%s]" % (what, _short(bls)),
                                                   bindings, ctx.num_workers, bls))

    for key, checker in (("bootstrap_peers", "bootstrap"), ("trusted_nodes", "trusted")):
        if key not in cfg:
            continue
        section = cfg[key]
        want = set(exp.get(key, {}))
        if not isinstance(section, dict):
            errs.append("%s %s: must be a mapping keyed by BLS key, found %s" % (what, key, _describe(section)))
            continue
        if set(section) != want:
            errs.append("%s %s: keys must be %s, found %s"
                        % (what, key, sorted(_short(k) for k in want), sorted(_short(k) for k in section)))
        for bls, entry in section.items():
            where = "%s %s[%s]" % (what, key, _short(bls))
            if bls == ctx.bls[name]:
                errs.append("%s: names this node's own BLS key" % where)
            if checker == "bootstrap":
                errs.extend(check_bootstrap_server(entry, where, bindings, 1, bls))
            else:
                errs.extend(check_trusted_node(entry, where, bindings, ctx.local_workers(name), bls))

    errs.extend(_binding_errors(ctx, name, what, bindings))

    if "hostname" in cfg:
        host = cfg["hostname"]
        if not isinstance(host, str) or not host or "\n" in host:
            errs.append("%s hostname: must be a non-empty one-line string, found %r" % (what, host))
    if existing_text is not None:
        try:
            keep = hostname_line_of(existing_text, "existing file")
        except ConfigError as exc:
            errs.append(str(exc))
            keep = None
        mine = [line.rstrip("\r") for line in text.split("\n") if HOSTNAME_RE.match(line)]
        if keep is not None and mine != [keep]:
            errs.append("%s: hostname line not preserved from the existing file (want %r, found %r)"
                        % (what, keep, mine))
        if keep is None and mine:
            errs.append("%s: hostname %r present but the existing file set none" % (what, mine))

    if not errs:
        got = dict((k, v) for k, v in cfg.items() if k != "hostname")
        if got != exp:
            diff = [k for k in TOP_ORDER if got.get(k) != exp.get(k)]
            errs.append("%s: content differs from what committee.yaml + node-info imply in %s "
                        "(re-render from the current genesis/)" % (what, diff))
    if not errs:
        errs.extend(_canonical_errors(text, cfg, what))
    return errs


def _binding_errors(ctx, name, what, bindings):
    """One PeerId per (BLS, swarm), one (BLS, swarm) per PeerId, and no other BLS key may use
    one of this node's own network keys (network.rs:233-256, trusted.rs:106-167)."""
    errs = []
    by_ident = {}
    by_peer = {}
    for where, peer, ident in bindings:
        if by_ident.setdefault(ident, peer) != peer:
            errs.append("%s: binds PeerId %s, but %s %s is bound to %s elsewhere in the file"
                        % (where, peer, _short(ident[0]), ident[1], by_ident[ident]))
        if by_peer.setdefault(peer, ident) != ident:
            errs.append("%s: PeerId %s is already %s %s" % (where, peer, _short(by_peer[peer][0]), by_peer[peer][1]))
    local = ctx.info[name]["p2p_info"]
    own = [peer_id_from_network_key(local["primary"]["network_key"])]
    own += [peer_id_from_network_key(w["network_key"]) for w in local["workers"]]
    for where, peer, ident in bindings:
        if peer in own and ident[0] != ctx.bls[name]:
            errs.append("%s: uses this node's own network key (PeerId %s)" % (where, peer))
    return errs


# --------------------------------------------------------------------------- CLI

def _context(args):
    return Context(args.committee, args.genesis_dir, args.nodes, args.hub)


def cmd_render(args):
    """Render and validate every node in memory; write the files only when all of them pass.

    All or nothing across nodes, so <out-dir> never holds a mix of fresh and stale files.
    """
    ctx = _context(args)
    rendered = []
    failed = 0
    for name, _ in ctx.nodes:
        path = os.path.join(args.out_dir, name + ".yaml")
        try:
            text = emit_config(ctx.expected(name))
            ctx.verbatim_check(text)
            errs = validate_text(ctx, name, text, path)
        except ConfigError as exc:
            text, errs = None, ["%s: %s" % (name, exc)]
        for err in errs:
            print("FAIL %s" % err, file=sys.stderr)
        failed += bool(errs)
        print("%s %s%s" % ("FAIL" if errs else "ok  ", path,
                           "" if errs else " (%d bytes)" % len(text)), flush=True)
        rendered.append((path, text))
    if failed:
        print("FAIL %d of %d node(s) failed; wrote nothing under %s"
              % (failed, len(rendered), args.out_dir), file=sys.stderr)
        return 1
    try:
        os.makedirs(args.out_dir, exist_ok=True)
        for path, text in rendered:
            with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
    except OSError as exc:
        for path, _ in rendered:
            if os.path.exists(path + ".tmp"):
                os.remove(path + ".tmp")
        raise ConfigError("cannot write under %s: %s (no file replaced)" % (args.out_dir, exc))
    for path, _ in rendered:
        os.replace(path + ".tmp", path)
    print("wrote %d file(s) under %s" % (len(rendered), args.out_dir))
    return 0


def cmd_validate(args):
    ctx = _context(args)
    existing = None
    if args.existing is not None:
        existing = _read_optional(args.existing)
    failed = 0
    for path in args.files:
        try:
            with open(path, "r", encoding="utf-8", newline="") as handle:
                text = handle.read()
        except OSError as exc:
            print("FAIL cannot read %s: %s" % (path, exc), file=sys.stderr)
            failed += 1
            continue
        errs = validate_text(ctx, args.node, text, path, existing)
        for err in errs:
            print("FAIL %s" % err, file=sys.stderr)
        failed += bool(errs)
        if not errs:
            print("ok   %s is a valid network-config for %s" % (path, args.node))
    return 1 if failed else 0


def _read_optional(path):
    """File contents; '' for an empty or absent file (an absent existing file is normal)."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def cmd_merge(args):
    with open(args.rendered, "r", encoding="utf-8", newline="") as handle:
        rendered = handle.read()
    existing = _read_optional(args.existing) if args.existing else ""
    text, line, replaced, dropped = merge(rendered, existing, args.existing or "existing file")
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    notes = ["hostname %s" % ("kept (%s)" % line if line else "none")]
    if replaced:
        notes.append("replaced with the rendered values: %s" % ", ".join(replaced))
    shown = [k if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) else repr(k) for k in dropped]
    notes.append("dropped %d existing key(s) the rendered file does not set: %s"
                 % (len(shown), ", ".join(shown)) if shown else "dropped none")
    print("merged %s: %s" % (args.out, "; ".join(notes)))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    def context_flags(p):
        p.add_argument("--committee", required=True, help="genesis/committee.yaml")
        p.add_argument("--genesis-dir", required=True, help="dir with validators/<n>.yaml, observers/<n>.yaml")
        p.add_argument("--nodes", required=True, help="fleet order: node1=validator,...,node5=observer")
        p.add_argument("--hub", required=True, help="the validator that trusts the observers (node1)")

    p_render = sub.add_parser("render", help="write <out-dir>/<node>.yaml for every node and validate it")
    context_flags(p_render)
    p_render.add_argument("--out-dir", required=True)
    p_render.set_defaults(func=cmd_render)

    p_val = sub.add_parser("validate", help="check files as one node's network-config")
    context_flags(p_val)
    p_val.add_argument("--node", required=True)
    p_val.add_argument("--existing", help="the pre-merge file: its hostname line must be kept")
    p_val.add_argument("files", nargs="+")
    p_val.set_defaults(func=cmd_validate)

    p_merge = sub.add_parser("merge", help="rendered file + the existing file's hostname line")
    p_merge.add_argument("--rendered", required=True)
    p_merge.add_argument("--existing", help="the node's current network-config (absent or empty is fine)")
    p_merge.add_argument("--out", required=True)
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print("FAIL %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
