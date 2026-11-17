#!/usr/bin/env python3
"""l2-shim: the fake outside world for a devnet-deploy.sh rehearsal (standard library only).

One file, many entry points (argv[1] = the tool name; bin/ and remote-bin/ hold symlinks to
bin/_dispatch, which calls this file with the link's basename):

  operator-side fakes : gcloud dig docker cast curl ssh scp
  remote-side fakes   : sudo systemctl journalctl ss curl ufw docker whoami id getent chown
                        chgrp install hostname ip git   (run inside a host sandbox, see run_remote)
  tn-node-deployment  : tnd <script> <args>   (the fake /opt/telcoin-node-scripts/<script>)
  harness             : init gen-flags pty-run report sentinel

State lives in $L2_SHIM_STATE (see README.md): cloud.json (instances, addresses, firewall rules,
secrets), dns.json, hosts/<instance>/root (a fake filesystem), hosts/<instance>/units.json,
calls.log, findings.log, sentinel.log, current_step.
STRICT: a command no emulator recognises is a finding (findings.log) and fails with rc 97.
"""
import fcntl
import hashlib
import json
import os
import pty
import random
import re
import select
import shlex
import shutil
import subprocess
import sys
import time

SHIM_DIR = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("L2_SHIM_STATE", "")
PROJECT = os.environ.get("L2_SHIM_PROJECT", "tn-devnet")
UNKNOWN_RC = 97
NODE_SCRIPTS = "/opt/telcoin-node-scripts"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# ----------------------------------------------------------------------------- state + logs
def sp(*parts):
    if not STATE:
        sys.stderr.write("L2-SHIM: L2_SHIM_STATE is not set\n")
        sys.exit(UNKNOWN_RC)
    return os.path.join(STATE, *parts)


class Locked:
    """Exclusive lock over the whole state dir (drivers may run jobs in parallel)."""
    def __enter__(self):
        self.fh = open(sp(".lock"), "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def jsave(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def cur_step():
    try:
        with open(sp("current_step")) as f:
            return f.read().strip() or "-"
    except FileNotFoundError:
        return "-"


def oneline(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def log_call(tool, inst, cmd, stdin_len=None):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    extra = "" if stdin_len is None else "\t<stdin %d bytes>" % stdin_len
    with open(sp("calls.log"), "a") as f:
        f.write("%s\tstep=%s\t%s\t%s\t%s%s\n" % (ts, cur_step(), tool, inst or "-", oneline(cmd), extra))


def finding(kind, inst, cmd, detail, fatal=True):
    """kind: UNRECOGNISED | FLAGCHECK | UNSAFE | SUSPECT (SUSPECT is listed, not fatal)."""
    line = "%s\tstep=%s\t%s\t%s\t%s\t%s\n" % (kind, cur_step(), inst or "-", oneline(detail),
                                                oneline(cmd), "fatal" if fatal else "note")
    with open(sp("findings.log"), "a") as f:
        f.write(line)
    sys.stderr.write("L2-SHIM %s [step %s] %s: %s\n    command: %s\n" % (
        kind, cur_step(), inst or "-", detail, cmd[:600]))


def strict_fail(kind, inst, cmd, detail):
    finding(kind, inst, cmd, detail)
    sys.exit(UNKNOWN_RC)


def cloud():
    return jload(sp("cloud.json"), {"instances": {}, "addresses": {}, "firewall_rules": {}, "secrets": {}})


# ----------------------------------------------------------------------------- gcloud
BOOL_FLAGS = {"quiet", "tunnel-through-iap", "internal-ip", "no-address", "can-ip-forward",
              "shielded-secure-boot", "shielded-vtpm", "shielded-integrity-monitoring",
              "no-restart-on-failure", "recurse", "dry-run", "async", "no-user-output-enabled",
              "no-boot-disk-auto-delete", "boot-disk-auto-delete", "global", "compress",
              "enable-oslogin", "no-shielded-secure-boot", "disabled", "no-disabled"}


def parse_gcloud(argv):
    pos, fl = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if "=" in a:
                k, v = a[2:].split("=", 1)
            else:
                k = a[2:]
                if k in BOOL_FLAGS or i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                    v = True
                else:
                    v = argv[i + 1]
                    i += 1
            fl.setdefault(k, []).append(v)
        elif a in ("-q",):
            fl.setdefault("quiet", []).append(True)
        else:
            pos.append(a)
        i += 1
    return pos, fl


def f1(fl, k, default=None):
    v = fl.get(k)
    return v[-1] if v else default


def region_of(zone):
    return zone.rsplit("-", 1)[0]


def det_ip(seed, first):
    h = hashlib.sha256(seed.encode()).digest()
    return "%d.%d.%d.%d" % (first, h[0] % 250 + 2, h[1] % 250 + 2, h[2] % 250 + 2)


def gerr(msg, rc=1):
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(rc)


def not_found(kind, path):
    gerr("(gcloud.compute.%s) Could not fetch resource:\n - The resource 'projects/%s/%s' was not found"
         % (kind, PROJECT, path))


def inst_json(name, rec):
    return {
        "name": name, "status": rec["status"],
        "zone": "https://www.googleapis.com/compute/v1/projects/%s/zones/%s" % (PROJECT, rec["zone"]),
        "networkInterfaces": [{"networkIP": rec["int_ip"], "accessConfigs": [{"natIP": rec["ext_ip"]}]}],
        "tags": {"items": list(rec.get("tags", []))},
        "metadata": {"items": [{"key": k, "value": v} for k, v in sorted(rec.get("metadata", {}).items())]},
        "labels": rec.get("labels", {}),
    }


def addr_json(name, rec):
    return {"name": name, "address": rec["address"], "status": rec["status"], "addressType": "EXTERNAL",
            "region": "https://www.googleapis.com/compute/v1/projects/%s/regions/%s" % (PROJECT, rec["region"]),
            "users": rec.get("users", [])}


def fw_json(name, rec):
    out = dict(rec)
    out["name"] = name
    return out


def fw_rule_transform(r):
    """gcloud's firewall_rule() transform: {IPProtocol: tcp, ports: [80, 443]} -> tcp:80,tcp:443."""
    if not isinstance(r, dict) or r.get("IPProtocol") is None:
        return ""
    ports = r.get("ports") or []
    return ",".join("%s:%s" % (r["IPProtocol"], p) for p in ports) if ports else r["IPProtocol"]


def ev_path(obj, expr):
    """gcloud projection subset: a.b[0].c, a[].b, .basename(), .list(), .map().firewall_rule()."""
    cur, mapped = obj, False
    for part in [x for x in re.split(r"\.(?![^(]*\))", expr.strip()) if x]:
        m = re.match(r"^(\w+)\(\)$", part)
        if m:
            fn = m.group(1)
            if fn == "map":
                mapped = True
                continue
            if fn == "list":
                cur = ",".join(fmt_value(x) for x in cur) if isinstance(cur, list) else fmt_value(cur)
                mapped = False
                continue
            f = {"basename": lambda v: v.rstrip("/").rsplit("/", 1)[-1] if isinstance(v, str) else v,
                 "firewall_rule": fw_rule_transform}.get(fn)
            if f is None:
                strict_fail("UNRECOGNISED", None, expr, "gcloud projection transform %s() not emulated" % fn)
            cur = [f(x) for x in cur] if (mapped or isinstance(cur, list)) and isinstance(cur, list) else f(cur)
            continue
        m = re.match(r"^(\w+)(?:\[(\d*)\])?$", part)
        if not m:
            strict_fail("UNRECOGNISED", None, expr, "gcloud projection %s not emulated" % part)
        name, idx = m.group(1), m.group(2)
        if isinstance(cur, list):
            cur = [x.get(name) if isinstance(x, dict) else None for x in cur]
        else:
            cur = cur.get(name) if isinstance(cur, dict) else None
        if idx:
            cur = cur[int(idx)] if isinstance(cur, list) and int(idx) < len(cur) else None
        if cur is None:
            return None
    return cur


def fmt_value(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return ";".join(fmt_value(x) for x in v)
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v)


def render(objs, fmt, single, cmdline):
    if fmt is None or fmt is True:
        fmt = "json" if single else "value(name)"
    if fmt == "json":
        print(json.dumps(objs[0] if single else objs, indent=2))
        return
    m = re.match(r"^(value|get|csv)(\[[^\]]*\])?\((.*)\)$", fmt.strip(), re.S)
    if not m:
        strict_fail("UNRECOGNISED", None, cmdline, "gcloud --format not emulated: %s" % fmt)
    fields = [x for x in re.split(r",(?![^(]*\))", m.group(3)) if x.strip()]
    attrs = m.group(2) or ""
    sepm = re.search(r'separator="([^"]*)"', attrs)
    sep = sepm.group(1) if sepm else ("," if m.group(1) == "csv" else "\t")
    if re.sub(r'separator="[^"]*"|no-heading|,', "", attrs.strip("[]")).strip():
        strict_fail("UNRECOGNISED", None, cmdline, "gcloud --format attributes not emulated: %s" % attrs)
    for o in objs:
        print(sep.join(fmt_value(ev_path(o, f)) for f in fields))


def match_filter(obj, flt, cmdline):
    if not flt:
        return True
    terms = re.findall(r"[\w.\[\]()]+\s*[=:~]\s*(?:\([^)]*\)|\S+)", flt.replace(" AND ", " "))
    rest = re.sub(r"[\w.\[\]()]+\s*[=:~]\s*(?:\([^)]*\)|\S+)", "", flt.replace(" AND ", " ")).strip()
    if rest or not terms or re.search(r"\b(OR|NOT)\b", flt):
        strict_fail("UNRECOGNISED", None, cmdline, "gcloud --filter not emulated: %s" % flt)
    for t in terms:
        k, op, want = re.match(r"([\w.\[\]()]+)\s*([=:~])\s*(.*)", t).groups()
        got = fmt_value(ev_path(obj, k))
        gotb = got.rstrip("/").rsplit("/", 1)[-1]
        wants = want[1:-1].split() if want.startswith("(") else [want]
        wants = [w.strip("'\"") for w in wants]
        if op == "~":
            ok = any(re.search(w, got) for w in wants)
        elif op == "=":
            ok = any(w in (got, gotb) for w in wants)
        else:
            ok = any(w in got.split(";") or gotb == w or (w == "*" and got) for w in wants)
        if not ok:
            return False
    return True


def gcloud(argv):
    cmdline = "gcloud " + " ".join(shlex.quote(a) for a in argv)
    pos, fl = parse_gcloud(argv)
    if pos[:1] in (["beta"], ["alpha"]):
        pos = pos[1:]
    key = tuple(pos[:3])
    inst_name = pos[2] if len(pos) > 2 and pos[0] == "compute" and pos[1] in ("ssh", "scp") else (
        pos[3] if len(pos) > 3 and pos[:2] == ["compute", "instances"] else None)
    if pos[:2] == ["compute", "ssh"]:
        return gc_ssh(pos, fl, cmdline)
    if pos[:2] == ["compute", "scp"]:
        return gc_scp(pos, fl, cmdline)
    log_call("gcloud", inst_name, cmdline)
    proj = f1(fl, "project")
    if proj not in (None, PROJECT) and pos[:1] != ["config"]:
        strict_fail("UNSAFE", inst_name, cmdline, "--project %s is not the devnet project %s" % (proj, PROJECT))
    handler = GCLOUD.get(key) or GCLOUD.get(tuple(pos[:2]))
    if not handler:
        strict_fail("UNRECOGNISED", inst_name, cmdline, "no gcloud emulator for '%s'" % " ".join(pos[:3]))
    return handler(pos, fl, cmdline)


def gc_instances_create(pos, fl, cmdline):
    zone = f1(fl, "zone")
    if not zone or len(pos) < 4:
        gerr("(gcloud.compute.instances.create) --zone and a name are required")
    with Locked():
        c = cloud()
        for name in pos[3:]:
            if name in c["instances"]:
                gerr("(gcloud.compute.instances.create) The resource 'projects/%s/zones/%s/instances/%s' already exists"
                     % (PROJECT, zone, name))
            addr = f1(fl, "address")
            nic = dict(kv.split("=", 1) for kv in str(f1(fl, "network-interface", "")).split(",") if "=" in kv)
            if nic.get("address"):
                addr = nic["address"]
            if "no-address" in str(f1(fl, "network-interface", "")):
                fl["no-address"] = [True]
            ext = None
            if addr and addr is not True:
                for an, ar in c["addresses"].items():
                    if addr in (an, ar["address"]):
                        if ar["region"] != region_of(zone):
                            gerr("address %s is in region %s, not %s" % (addr, ar["region"], region_of(zone)))
                        if ar["status"] == "IN_USE":
                            gerr("IP %s is already being used by another resource" % ar["address"])
                        ar["status"], ar["users"], ext = "IN_USE", [name], ar["address"]
                if ext is None:
                    gerr("(gcloud.compute.instances.create) address '%s' is not reserved in %s" % (addr, region_of(zone)))
            if ext is None and not f1(fl, "no-address"):
                ext = det_ip("eph-" + name, 34)
            meta = {}
            for spec in fl.get("metadata", []):
                for kv in str(spec).split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        meta[k] = v
            for spec in fl.get("metadata-from-file", []):
                for kv in str(spec).split(","):
                    k, v = kv.split("=", 1)
                    if not os.path.isfile(v):
                        gerr("(gcloud.compute.instances.create) Unable to read file [%s]" % v)
                    meta[k] = "<file %s, %d bytes>" % (os.path.basename(v), os.path.getsize(v))
            tags = []
            for t in fl.get("tags", []):
                tags += [x for x in str(t).split(",") if x]
            rec = {"zone": zone, "status": "RUNNING", "int_ip": det_ip("int-" + name, 10), "ext_ip": ext or "",
                   "tags": sorted(set(tags)), "metadata": meta, "serial": ""}
            c["instances"][name] = rec
            boot_host(name, rec)
        jsave(sp("cloud.json"), c)
    print("Created [https://www.googleapis.com/compute/v1/projects/%s/zones/%s/instances/%s]." % (PROJECT, zone, pos[3]))


def boot_host(name, rec):
    """First boot: what devnet-startup.sh leaves (docker, ufw, nftables, the node scripts at
    tn-scripts-ref, /etc/telcoin/devnet-ips.env) and its serial-console marker."""
    root = sp("hosts", name, "root")
    for d in ("etc/telcoin", "etc/systemd/system", "tmp", "home/tnadmin", "var/lib", "var/log",
              "usr/local/libexec", "opt"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    units = {"docker": {"active": True, "enabled": True}, "ufw": {"active": False, "enabled": True},
             "nftables": {"active": False, "enabled": False}, "ssh": {"active": True, "enabled": True}}
    lines = ["Starting startup scripts", "startup-script: [devnet-startup] docker installed"]
    ref = rec["metadata"].get("tn-scripts-ref")
    if "startup-script" in rec["metadata"] and ref:
        sd = os.path.join(root, NODE_SCRIPTS.lstrip("/"))
        os.makedirs(sd, exist_ok=True)
        flags = jload(sp("flags.json"), {"scripts": {}})
        for script in flags["scripts"]:
            p = os.path.join(sd, script)
            with open(p, "w") as f:
                f.write('#!/usr/bin/env bash\n# l2-shim fake of tn-node-deployment %s at %s\n'
                        'exec "${L2_SHIM_PY}" "${L2_SHIM_DIR}/fakes.py" tnd %s "$@"\n' % (script, ref, script))
            os.chmod(p, 0o755)
        with open(os.path.join(sd, ".shim-ref"), "w") as f:
            f.write(ref + "\n")
        with open(os.path.join(root, "etc/telcoin/devnet-ips.env"), "w") as f:
            f.write("EXTERNAL_IP=%s\nINTERNAL_IP=%s\n" % (rec["ext_ip"], rec["int_ip"]))
        lines.append("startup-script: devnet-startup.sh complete — tn-scripts-ref=%s" % ref)
    else:
        lines.append("startup-script: no tn-scripts-ref metadata: node scripts not fetched (no marker)")
    rec["serial"] = "\n".join(lines) + "\n"
    jsave(sp("hosts", name, "units.json"), units)


def gc_instances_simple(pos, fl, cmdline):
    verb = pos[2]
    names = pos[3:]
    with Locked():
        c = cloud()
        if verb == "list":
            objs = [inst_json(n, r) for n, r in sorted(c["instances"].items())]
            objs = [o for o in objs if match_filter(o, f1(fl, "filter"), cmdline)]
            render(objs, f1(fl, "format"), False, cmdline)
            return
        if not names:
            gerr("(gcloud.compute.instances.%s) an instance name is required" % verb)
        for n in names:
            rec = c["instances"].get(n)
            if rec is None or (f1(fl, "zone") and rec["zone"] != f1(fl, "zone")):
                not_found("instances.%s" % verb, "zones/%s/instances/%s" % (f1(fl, "zone"), n))
            if verb == "describe":
                render([inst_json(n, rec)], f1(fl, "format"), True, cmdline)
            elif verb == "get-serial-port-output":
                sys.stdout.write(rec["serial"])
            elif verb in ("add-tags", "remove-tags"):
                tags = [x for t in fl.get("tags", []) for x in str(t).split(",") if x]
                cur = set(rec["tags"])
                cur = cur | set(tags) if verb == "add-tags" else cur - set(tags)
                rec["tags"] = sorted(cur)
                print("Updated [%s]." % n)
            elif verb == "delete":
                for a in c["addresses"].values():
                    if n in a.get("users", []):
                        a["users"], a["status"] = [], "RESERVED"
                del c["instances"][n]
                shutil.rmtree(sp("hosts", n), ignore_errors=True)
                print("Deleted [%s]." % n)
            else:
                strict_fail("UNRECOGNISED", n, cmdline, "no emulator for gcloud compute instances %s" % verb)
        jsave(sp("cloud.json"), c)


def gc_addresses(pos, fl, cmdline):
    verb = pos[2]
    with Locked():
        c = cloud()
        if verb == "list":
            objs = [addr_json(n, r) for n, r in sorted(c["addresses"].items())]
            objs = [o for o in objs if match_filter(o, f1(fl, "filter"), cmdline)]
            render(objs, f1(fl, "format"), False, cmdline)
            return
        region = f1(fl, "region")
        for n in pos[3:]:
            rec = c["addresses"].get(n)
            if verb == "describe":
                if rec is None or (region and rec["region"] != region):
                    not_found("addresses.describe", "regions/%s/addresses/%s" % (region, n))
                render([addr_json(n, rec)], f1(fl, "format"), True, cmdline)
            elif verb == "create":
                if rec is not None:
                    gerr("(gcloud.compute.addresses.create) The resource 'projects/%s/regions/%s/addresses/%s' already exists"
                         % (PROJECT, region, n))
                if not region:
                    gerr("(gcloud.compute.addresses.create) --region is required")
                ip = f1(fl, "addresses") or det_ip("static-" + n, 35)
                c["addresses"][n] = {"address": ip, "region": region, "status": "RESERVED", "users": []}
                print("Created [https://www.googleapis.com/compute/v1/projects/%s/regions/%s/addresses/%s]." % (PROJECT, region, n))
            elif verb == "delete":
                if rec is None:
                    not_found("addresses.delete", "regions/%s/addresses/%s" % (region, n))
                del c["addresses"][n]
                print("Deleted [%s]." % n)
            else:
                strict_fail("UNRECOGNISED", None, cmdline, "no emulator for gcloud compute addresses %s" % verb)
        jsave(sp("cloud.json"), c)


def gc_firewall(pos, fl, cmdline):
    verb = pos[2]
    with Locked():
        c = cloud()
        rules = c["firewall_rules"]
        if verb == "list":
            objs = [fw_json(n, r) for n, r in sorted(rules.items())]
            objs = [o for o in objs if match_filter(o, f1(fl, "filter"), cmdline)]
            render(objs, f1(fl, "format"), False, cmdline)
            return
        for n in pos[3:]:
            rec = rules.get(n)
            if verb == "describe":
                if rec is None:
                    not_found("firewall-rules.describe", "global/firewalls/%s" % n)
                render([fw_json(n, rec)], f1(fl, "format"), True, cmdline)
            elif verb in ("create", "update"):
                if verb == "create" and rec is not None:
                    gerr("(gcloud.compute.firewall-rules.create) The resource 'projects/%s/global/firewalls/%s' already exists" % (PROJECT, n))
                if verb == "update" and rec is None:
                    not_found("firewall-rules.update", "global/firewalls/%s" % n)
                rec = rec or {"network": "default", "direction": "INGRESS", "priority": 1000}
                for k, field in (("network", "network"), ("direction", "direction"), ("priority", "priority"),
                                 ("description", "description")):
                    if f1(fl, k) is not None:
                        rec[field] = f1(fl, k)
                for k, field in (("source-ranges", "sourceRanges"), ("target-tags", "targetTags"),
                                 ("destination-ranges", "destinationRanges"), ("source-tags", "sourceTags")):
                    if f1(fl, k) is not None:
                        rec[field] = [x for x in str(f1(fl, k)).split(",") if x]
                kind = "denied" if str(f1(fl, "action", "ALLOW")).upper() == "DENY" else "allowed"
                for k in ("allow", "rules"):
                    v = f1(fl, k)
                    if v is not None:
                        rec.pop("allowed", None)
                        rec.pop("denied", None)
                        rec[kind] = [{"IPProtocol": p.split(":")[0], "ports": p.split(":")[1:]}
                                     for p in str(v).split(",") if p]
                rec.setdefault("disabled", False)
                unknown = set(fl) - {"network", "direction", "priority", "description", "source-ranges",
                                     "target-tags", "destination-ranges", "source-tags", "allow", "rules",
                                     "action", "project", "quiet", "format"}
                if unknown:
                    strict_fail("UNRECOGNISED", None, cmdline, "firewall-rules flags not emulated: %s" % sorted(unknown))
                rules[n] = rec
                print("%s [%s]." % ("Created" if verb == "create" else "Updated", n))
            elif verb == "delete":
                if rec is None:
                    not_found("firewall-rules.delete", "global/firewalls/%s" % n)
                del rules[n]
                print("Deleted [%s]." % n)
            else:
                strict_fail("UNRECOGNISED", None, cmdline, "no emulator for gcloud compute firewall-rules %s" % verb)
        jsave(sp("cloud.json"), c)


def gc_disks(pos, fl, cmdline):
    verb = pos[2]
    with Locked():
        c = cloud()
        disks = c.setdefault("disks", {})
        if verb == "list":
            objs = [dict(r, name=n) for n, r in sorted(disks.items())]
            render([o for o in objs if match_filter(o, f1(fl, "filter"), cmdline)], f1(fl, "format"), False, cmdline)
            return
        zone = f1(fl, "zone")
        for n in pos[3:]:
            rec = disks.get(n)
            if verb == "describe":
                if rec is None or rec["zone"] != zone:
                    not_found("disks.describe", "zones/%s/disks/%s" % (zone, n))
                render([dict(rec, name=n)], f1(fl, "format"), True, cmdline)
            elif verb == "create":
                if rec is not None:
                    gerr("(gcloud.compute.disks.create) The resource 'projects/%s/zones/%s/disks/%s' already exists" % (PROJECT, zone, n))
                disks[n] = {"zone": zone, "sizeGb": str(f1(fl, "size", "10")), "type": str(f1(fl, "type", "pd-standard")),
                            "users": [], "status": "READY"}
                print("Created [%s]." % n)
            else:
                strict_fail("UNRECOGNISED", None, cmdline, "no emulator for gcloud compute disks %s" % verb)
        jsave(sp("cloud.json"), c)


def gc_secrets(pos, fl, cmdline):
    sub = pos[1] if len(pos) > 1 else ""
    with Locked():
        c = cloud()
        s = c["secrets"]
        if sub == "versions" and pos[2:3] == ["access"]:
            name = f1(fl, "secret")
            if name not in s or not s[name]:
                gerr("(gcloud.secrets.versions.access) NOT_FOUND: Secret [%s] not found or has no versions." % name)
            sys.stdout.write(s[name][-1])
            return
        if sub == "versions" and pos[2:3] == ["add"]:
            name = pos[3]
            if name not in s:
                gerr("(gcloud.secrets.versions.add) NOT_FOUND: Secret [%s] not found." % name)
            if f1(fl, "data-file") != "-":
                strict_fail("UNSAFE", None, cmdline, "secret value not read from stdin")
            s[name].append(sys.stdin.read())
        elif sub == "add-iam-policy-binding":
            if pos[2] not in s:
                gerr("(gcloud.secrets.add-iam-policy-binding) NOT_FOUND: Secret [%s] not found." % pos[2])
            c.setdefault("iam", {}).setdefault(pos[2], [])
            b = "%s %s" % (f1(fl, "member"), f1(fl, "role"))
            if b not in c["iam"][pos[2]]:
                c["iam"][pos[2]].append(b)
            print("Updated IAM policy for secret [%s]." % pos[2])
        elif sub == "describe":
            if pos[2] not in s:
                gerr("(gcloud.secrets.describe) NOT_FOUND: Secret [%s] not found." % pos[2])
            print("name: projects/%s/secrets/%s" % (PROJECT, pos[2]))
        elif sub == "create":
            if pos[2] in s:
                gerr("(gcloud.secrets.create) ALREADY_EXISTS: Secret [%s] exists." % pos[2])
            s[pos[2]] = []
            if f1(fl, "data-file") == "-":
                s[pos[2]].append(sys.stdin.read())
        else:
            strict_fail("UNRECOGNISED", None, cmdline, "no emulator for gcloud secrets %s" % " ".join(pos[1:3]))
        jsave(sp("cloud.json"), c)


def gc_config(pos, fl, cmdline):
    if pos[:2] == ["services", "enable"]:
        print("Operation finished successfully (l2-shim: services are always enabled).")
    elif pos[:2] == ["auth", "print-access-token"]:
        print("l2-shim-fake-access-token")  # a fake bearer token: nothing can use it
    elif pos[:2] == ["auth", "list"]:
        print("l2-shim@example.invalid")
    elif pos[1:3] == ["get-value", "project"]:
        print(PROJECT)
    elif pos[1:3] == ["get-value", "account"]:
        print("l2-shim@example.invalid")
    else:
        strict_fail("UNRECOGNISED", None, cmdline, "no emulator for gcloud config %s" % " ".join(pos[1:]))


GCLOUD = {
    ("compute", "instances", "create"): gc_instances_create,
    ("compute", "instances", "describe"): gc_instances_simple,
    ("compute", "instances", "list"): gc_instances_simple,
    ("compute", "instances", "get-serial-port-output"): gc_instances_simple,
    ("compute", "instances", "add-tags"): gc_instances_simple,
    ("compute", "instances", "remove-tags"): gc_instances_simple,
    ("compute", "instances", "delete"): gc_instances_simple,
    ("compute", "addresses", "describe"): gc_addresses,
    ("compute", "addresses", "create"): gc_addresses,
    ("compute", "addresses", "list"): gc_addresses,
    ("compute", "addresses", "delete"): gc_addresses,
    ("compute", "firewall-rules", "describe"): gc_firewall,
    ("compute", "firewall-rules", "create"): gc_firewall,
    ("compute", "firewall-rules", "update"): gc_firewall,
    ("compute", "firewall-rules", "delete"): gc_firewall,
    ("compute", "firewall-rules", "list"): gc_firewall,
    ("compute", "disks", "describe"): gc_disks,
    ("compute", "disks", "create"): gc_disks,
    ("compute", "disks", "list"): gc_disks,
    ("secrets", "versions", "access"): gc_secrets,
    ("secrets", "versions", "add"): gc_secrets,
    ("secrets", "describe"): gc_secrets,
    ("secrets", "create"): gc_secrets,
    ("secrets", "add-iam-policy-binding"): gc_secrets,
    ("config", "get-value"): gc_config,
    ("auth", "print-access-token"): gc_config,
    ("auth", "list"): gc_config,
    ("services", "enable"): gc_config,
}


def running_instance(name, zone, cmdline, verb):
    c = cloud()
    rec = c["instances"].get(name)
    if rec is None or (zone and rec["zone"] != zone):
        not_found(verb, "zones/%s/instances/%s" % (zone, name))
    if rec["status"] != "RUNNING":
        gerr("(gcloud.compute.%s) instance %s is %s" % (verb, name, rec["status"]), 255)
    return rec


def gc_ssh(pos, fl, cmdline):
    inst = pos[2].split("@")[-1] if len(pos) > 2 else ""
    cmd = f1(fl, "command")
    ssh_flags = [str(x) for x in fl.get("ssh-flag", [])]
    data = sys.stdin.buffer.read() if "-T" in ssh_flags else b""
    shown = cmd if isinstance(cmd, str) else "<no --command>"
    log_call("ssh", inst, shown, len(data) if "-T" in ssh_flags else None)
    if not isinstance(cmd, str) or not cmd.strip():
        strict_fail("UNSAFE", inst, cmdline, "gcloud compute ssh without a command opens a login shell")
    if not f1(fl, "tunnel-through-iap"):
        finding("SUSPECT", inst, shown, "gcloud compute ssh without --tunnel-through-iap", fatal=False)
    running_instance(inst, f1(fl, "zone"), cmdline, "ssh")
    sys.exit(run_remote(inst, cmd, data))


def gc_scp(pos, fl, cmdline):
    paths = pos[2:]
    if len(paths) < 2:
        gerr("(gcloud.compute.scp) source and destination required")
    srcs, dest = paths[:-1], paths[-1]
    remote = [p for p in paths if re.match(r"^[\w@.-]+:", p)]
    if len(remote) != 1 or (remote[0] != dest and len(srcs) != 1):
        strict_fail("UNRECOGNISED", None, cmdline, "scp form not emulated (exactly one remote side)")
    inst = remote[0].split(":", 1)[0].split("@")[-1]
    log_call("scp", inst, " ".join(paths))
    running_instance(inst, f1(fl, "zone"), cmdline, "scp")
    root = sp("hosts", inst, "root")
    try:
        if dest == remote[0]:
            rdest = inroot(root, dest.split(":", 1)[1], cmdline, inst)
            for s in srcs:
                if os.path.isdir(s):
                    if not f1(fl, "recurse"):
                        gerr("scp: %s: not a regular file" % s)
                    shutil.copytree(s, os.path.join(rdest, os.path.basename(s)) if os.path.isdir(rdest) else rdest,
                                    dirs_exist_ok=True)
                else:
                    shutil.copy(s, rdest)
                    tgt = os.path.join(rdest, os.path.basename(s)) if os.path.isdir(rdest) else rdest
                    set_owner(inst, tgt[len(root):], "tnadmin:tnadmin")
        else:
            rsrc = inroot(root, srcs[0].split(":", 1)[1], cmdline, inst)
            if not os.path.exists(rsrc):
                sys.stderr.write("scp: %s: No such file or directory\n" % srcs[0].split(":", 1)[1])
                sys.exit(1)
            shutil.copy(rsrc, dest)
    except (OSError, shutil.Error) as e:
        sys.stderr.write("scp: %s\n" % e)
        sys.exit(1)


# ----------------------------------------------------------------------------- remote sandbox
REWRITE = re.compile(r"(?<![\w.~/:-])/(etc|var|opt|tmp|home|root|run|srv|mnt|usr/local|lib/systemd|usr/lib/systemd)(?=[/'\"\s;|&)]|$)")
OUTSIDE = re.compile(r"(?<![\w.~/:-])/(usr|bin|sbin|lib|lib64|boot|dev|proc|sys|snap|media)\b(/[\w.+-]+)*")
ALLOWED_OUTSIDE = re.compile(r"^/(dev/(null|stdin|stdout|stderr|fd/\d+|urandom)|usr/bin/env|bin/(ba)?sh|usr/bin/(ba)?sh|proc/self/\S*|usr/share/\S*)$")
SAFE_REAL = ("bash sh cat grep sed awk test [ cp mv rm mkdir rmdir chmod ln ls head tail sha256sum md5sum "
             "printf echo date sleep tr cut wc sort uniq find xargs base64 mktemp tee dirname basename readlink "
             "realpath true false env touch cmp diff seq od timeout nproc flock sync python3 jq awk mawk gawk "
             "comm paste fold rev nl expr yes du df").split()


def inroot(root, path, cmd, inst):
    if not path.startswith("/"):
        path = "/home/tnadmin/" + path
    if not REWRITE.match(path):
        strict_fail("UNSAFE", inst, cmd, "remote path %s is outside the fake filesystem" % path)
    return root + path


def unroot(p):
    root = os.environ.get("L2_SHIM_ROOT", "")
    return p[len(root):] if root and p.startswith(root) else p


def rewrite(text, root):
    return REWRITE.sub(lambda m: root + m.group(0), text)


def run_remote(inst, cmd, data):
    root = sp("hosts", inst, "root")
    rcmd = rewrite(cmd, root)
    # A shell reading its script from stdin (`sudo [VAR=v …] bash -s`, any prefix): the script's paths
    # are rewritten and checked like a command's. Any other stdin (a passphrase, a token) is passed as is.
    is_shell_stdin = re.search(r"(^|[\s;&|])(ba)?sh\s+-s(\s|$)", cmd) is not None
    payload = rewrite(data.decode("utf-8", "replace"), root).encode() if is_shell_stdin else data
    for text in (rcmd, payload.decode("utf-8", "replace") if is_shell_stdin else ""):
        for m in OUTSIDE.finditer(text):
            if not ALLOWED_OUTSIDE.match(m.group(0)):
                strict_fail("UNSAFE", inst, cmd, "remote command names %s, outside the fake filesystem" % m.group(0))
    home = os.path.join(root, "home/tnadmin")
    env = {"PATH": "%s:%s" % (os.path.join(SHIM_DIR, "remote-bin"), sp("sandbox-real")),
           "HOME": home, "USER": "tnadmin", "LOGNAME": "tnadmin", "LANG": "C.UTF-8", "TERM": "dumb",
           "TMPDIR": os.path.join(root, "tmp"), "L2_SHIM_HOST": inst, "L2_SHIM_ROOT": root,
           "L2_SHIM_STATE": STATE, "L2_SHIM_DIR": SHIM_DIR, "L2_SHIM_PY": sys.executable,
           "L2_SHIM_CMD": cmd}
    bash = os.path.join(sp("sandbox-real"), "bash")
    p = subprocess.run([bash, "-c", rcmd], input=payload, cwd=home, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    out = p.stdout.decode("utf-8", "replace").replace(root, "")
    err = p.stderr.decode("utf-8", "replace").replace(root, "")
    sys.stdout.write(out)
    sys.stderr.write(err)
    for m in re.finditer(r"(?:^|\n)\S*(?:bash|sh)(?:: line \d+)?: ([^:\n]+): command not found", err):
        finding("UNRECOGNISED", inst, cmd, "remote command '%s' has no emulator" % m.group(1))
    if p.returncode == 127 and "command not found" not in err:
        finding("UNRECOGNISED", inst, cmd, "remote program missing in the fake host (rc 127)")
    return p.returncode


def host():
    h = os.environ.get("L2_SHIM_HOST")
    if not h:
        sys.stderr.write("L2-SHIM: a remote fake ran outside a host sandbox\n")
        sys.exit(UNKNOWN_RC)
    return h, os.environ["L2_SHIM_ROOT"]


def units_path():
    return sp("hosts", host()[0], "units.json")


def remote_detail(tool, argv):
    with open(sp("remote-detail.log"), "a") as f:
        f.write("step=%s\t%s\t%s\t%s\n" % (cur_step(), host()[0], tool, oneline(" ".join(shlex.quote(a) for a in argv))))


def r_sudo(argv):
    remote_detail("sudo", argv)
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] == "--":
            i += 1
            break
        if argv[i] in ("-u", "-g"):
            i += 1
        elif argv[i] not in ("-n", "-E", "-H"):
            strict_fail("UNRECOGNISED", host()[0], os.environ.get("L2_SHIM_CMD", ""), "sudo option %s" % argv[i])
        i += 1
    os.environ["L2_SHIM_SUDO"] = "1"
    while i < len(argv) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[i]):  # sudo VAR=value cmd
        k, v = argv[i].split("=", 1)
        os.environ[k] = v
        i += 1
    if i >= len(argv):
        strict_fail("UNRECOGNISED", host()[0], os.environ.get("L2_SHIM_CMD", ""), "sudo with no command")
    try:
        os.execvp(argv[i], argv[i:])
    except FileNotFoundError:
        sys.stderr.write("sudo: %s: command not found\n" % argv[i])
        finding("UNRECOGNISED", host()[0], os.environ.get("L2_SHIM_CMD", ""), "remote command '%s' has no emulator" % argv[i])
        sys.exit(1)


def unit_name(u):
    return u[:-len(".service")] if u.endswith(".service") else u


def r_systemctl(argv):
    remote_detail("systemctl", argv)
    inst, root = host()
    args = [a for a in argv if not a.startswith("-")]
    opts = [a for a in argv if a.startswith("-")]
    verb, targets = (args[0], [unit_name(u) for u in args[1:]]) if args else ("", [])
    with Locked():
        units = jload(units_path(), {})
        for u in targets:
            if os.path.exists(os.path.join(root, "etc/systemd/system", u + ".service")):
                units.setdefault(u, {"active": False, "enabled": False})
        rc = 0
        if verb in ("is-active", "is-enabled"):
            for u in targets:
                st = units.get(u)
                key = "active" if verb == "is-active" else "enabled"
                word = ("active" if st and st["active"] else "inactive") if key == "active" else \
                       ("enabled" if st and st["enabled"] else ("disabled" if st else "not-found"))
                if "--quiet" not in opts and "-q" not in opts:
                    print(word)
                if not (st and st[key]):
                    rc = 3 if key == "active" else 1
        elif verb in ("start", "stop", "restart", "enable", "disable"):
            for u in targets:
                if u not in units:
                    sys.stderr.write("Failed to %s %s.service: Unit %s.service not found.\n" % (verb, u, u))
                    rc = 5
                    continue
                if verb == "restart" and u == "telcoin" and not units[u]["active"]:
                    finding("SUSPECT", inst, os.environ.get("L2_SHIM_CMD", ""),
                            "systemctl restart of a STOPPED telcoin unit (starts the node)", fatal=False)
                if verb in ("start", "restart"):
                    units[u]["active"] = True
                elif verb == "stop":
                    units[u]["active"] = False
                elif verb == "enable":
                    units[u]["enabled"] = True
                    if "--now" in opts:
                        units[u]["active"] = True
                else:
                    units[u]["enabled"] = False
                    if "--now" in opts:
                        units[u]["active"] = False
        elif verb == "daemon-reload":
            pass
        else:
            strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "systemctl %s not emulated" % verb)
        jsave(units_path(), units)
    sys.exit(rc)


def owners_path(inst):
    return sp("hosts", inst, "owners.json")


def set_owner(inst, rpath, owner, recursive=False):
    """rpath: the path as the VM sees it. owners.json: path -> user:group (path/** = recursive)."""
    with Locked():
        o = jload(owners_path(inst), {})
        if recursive:
            o = {k: v for k, v in o.items() if not (k == rpath or k.startswith(rpath + "/"))}
            o[rpath + "/**"] = owner
        o[rpath] = owner
        jsave(owners_path(inst), o)


def get_owner(inst, rpath):
    """Everything on a fresh VM is root:root unless a chown/install -o/scp/setup-node said otherwise."""
    o = jload(owners_path(inst), {})
    if rpath in o:
        return o[rpath]
    best = None
    for k, v in o.items():
        if k.endswith("/**") and (rpath + "/").startswith(k[:-2]):
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return best[1] if best else "root:root"


UIDS = {"root": "0", "tnadmin": "1000", "telcoin": "999", "telcoin-log": "998"}


def r_stat(argv):
    remote_detail("stat", argv)
    inst, root = host()
    fmt_i = [i for i, a in enumerate(argv) if a in ("-c", "--format", "--printf") or a.startswith(("--format=", "--printf="))]
    if len(fmt_i) != 1:
        strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "stat without a single -c/--format not emulated")
    i = fmt_i[0]
    if "=" in argv[i]:
        flag, fmt = argv[i].split("=", 1)
        rest = argv[:i] + argv[i + 1:]
    else:
        flag, fmt = argv[i], argv[i + 1]
        rest = argv[:i] + argv[i + 2:]
    files = [a for a in rest if not a.startswith("-")]
    marked = fmt.replace("%U", "\x01U").replace("%G", "\x01G").replace("%u", "\x01u").replace("%g", "\x01g")
    outs, rc = [], 0
    for f in files:
        p = subprocess.run([sp("real-tools", "stat"), flag if flag != "--format" else "-c", marked] +
                           [a for a in rest if a.startswith("-")] + [f], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            sys.stderr.write(p.stderr.decode().replace(root, ""))
            rc = p.returncode
            continue
        user, group = get_owner(inst, unroot(f)).split(":")
        txt = p.stdout.decode().replace("\x01U", user).replace("\x01G", group)
        txt = txt.replace("\x01u", UIDS.get(user, "1001")).replace("\x01g", UIDS.get(group, "1001"))
        outs.append(txt)
    sys.stdout.write("".join(outs))
    sys.exit(rc)


def r_simple(tool, argv):
    remote_detail(tool, argv)
    inst, root = host()
    sudo = os.environ.get("L2_SHIM_SUDO") == "1"
    if tool == "whoami":
        print("root" if sudo else "tnadmin")
    elif tool == "id" and argv in (["-u"], ["-g"]):
        print("0" if sudo else "1000")
    elif tool == "id" and argv == ["-un"]:
        print("root" if sudo else "tnadmin")
    elif tool == "mountpoint":
        target = unroot([a for a in argv if not a.startswith("-")][-1]).rstrip("/")
        mounted = target in jload(sp("hosts", inst, "mounts.json"), [])
        if "-q" not in argv:
            print("%s is %sa mountpoint" % (target, "" if mounted else "not "))
        sys.exit(0 if mounted else 32)
    elif tool == "hostname" and not argv:
        print(inst)
    elif tool in ("chown", "chgrp"):
        if not sudo and any(not a.startswith("tnadmin") for a in argv[:1]):
            sys.stderr.write("%s: changing ownership: Operation not permitted\n" % tool)
            sys.exit(1)
        words = [a for a in argv if not a.startswith("-")]
        spec, paths = words[0], words[1:]
        for p in paths:
            if not os.path.lexists(p):
                sys.stderr.write("%s: cannot access '%s': No such file or directory\n" % (tool, unroot(p)))
                sys.exit(1)
        for p in paths:
            cur_u, cur_g = get_owner(inst, unroot(p)).split(":")
            if tool == "chgrp":
                owner = "%s:%s" % (cur_u, spec)
            else:
                u, _, g = spec.partition(":") if ":" in spec else spec.partition(".")
                owner = "%s:%s" % (u or cur_u, g or (u if ":" in spec and not g else cur_g))
            set_owner(inst, unroot(p).rstrip("/"), owner, recursive=("-R" in argv or "--recursive" in argv))
    elif tool == "install":
        out, i, own = [], 0, {}
        while i < len(argv):
            if argv[i] in ("-o", "-g", "--owner", "--group"):
                own["u" if argv[i] in ("-o", "--owner") else "g"] = argv[i + 1]
                i += 2
                continue
            out.append(argv[i])
            i += 1
        if own and not sudo:
            sys.stderr.write("install: cannot change ownership: Operation not permitted\n")
            sys.exit(1)
        rc = subprocess.call([sp("real-tools", "install")] + out)  # the real one, by path (not PATH)
        if rc == 0:
            paths = [a for a in out if not a.startswith("-") and a not in (own.get("u"), own.get("g"))]
            if "-m" in out:
                mi = out.index("-m")
                paths = [a for a in paths if a != out[mi + 1]]
            targets = paths if "-d" in out else paths[-1:]
            for t in targets:
                dest = t
                if "-d" not in out and os.path.isdir(t) and len(paths) > 1:
                    dest = os.path.join(t, os.path.basename(paths[0]))
                set_owner(inst, unroot(dest).rstrip("/"), "%s:%s" % (own.get("u", "root"), own.get("g", "root")))
        sys.exit(rc)
    else:
        strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "remote %s %s not emulated" % (tool, " ".join(argv)))


# ----------------------------------------------------------------------------- tn-node-deployment
def flag_check(script, argv):
    table = jload(sp("flags.json"), {"scripts": {}})["scripts"]
    known = table.get(script)
    inst = host()[0]
    cmd = os.environ.get("L2_SHIM_CMD", script)
    if known is None:
        strict_fail("FLAGCHECK", inst, cmd, "%s is not a script of the tn-node-deployment branch" % script)
    bad = []
    for a in argv:
        if re.match(r"^--?[A-Za-z]", a):
            flag = a.split("=", 1)[0]
            if flag not in known:
                bad.append(flag)
    if bad:
        strict_fail("FLAGCHECK", inst, cmd, "%s does not accept %s (flags from the real parser)" % (script, ", ".join(bad)))


def opts_of(argv):
    o, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            o[k] = v
        elif a.startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                o[a[2:]] = argv[i + 1]
                i += 1
            else:
                o[a[2:]] = True
        i += 1
    return o


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")))


def meta_set(root, kv):
    p = os.path.join(root, "etc/telcoin/.node-meta")
    cur = []
    if os.path.exists(p):
        with open(p) as f:
            cur = [l.rstrip("\n") for l in f if l.strip()]
    keys = set(kv)
    cur = [l for l in cur if l.split("=", 1)[0] not in keys]
    cur += ["%s=%s" % (k, v) for k, v in kv.items()]
    with open(p, "w") as f:
        f.write("\n".join(cur) + "\n")
    os.chmod(p, 0o600)


def b58(rng, n):
    return "".join(rng.choice(B58) for _ in range(n))


def b58enc(raw):
    n, out = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def libp2p_key(rng):
    """(network_key, peer id) of a fake ed25519 libp2p key: protobuf-encoded public key, and its
    identity-multihash peer id (12D3KooW...), consistent with each other as the real ones are."""
    pk = b"\x08\x01\x12\x20" + bytes(rng.getrandbits(8) for _ in range(32))
    return b58enc(pk), b58enc(b"\x00\x24" + pk)


def tnd_setup_node(argv):
    inst, root = host()
    o = opts_of(argv)
    phase = o.get("phase")
    cmd = os.environ.get("L2_SHIM_CMD", "")
    if os.environ.get("L2_SHIM_SUDO") != "1":
        emit(event="done", ok=False, msg="setup-node.sh must run as root")
        sys.exit(1)
    if "json" not in o:
        strict_fail("UNRECOGNISED", inst, cmd, "setup-node.sh without --json is interactive")
    unit = os.path.join(root, "etc/systemd/system/telcoin.service")
    if phase in ("keygen", "finalize") and os.path.exists(unit):
        emit(event="done", ok=False, phase=phase, msg="A node is already installed (/etc/systemd/system/telcoin.service), "
             "so --phase=%s does not run. Use edit-config.sh to change it, or remove-node.sh first." % phase)
        sys.exit(1)
    if phase == "keygen":
        return tnd_keygen(inst, root, o, cmd)
    strict_fail("UNRECOGNISED", inst, cmd, "setup-node.sh --phase=%s has no emulator yet" % phase)


def tnd_keygen(inst, root, o, cmd):
    need = ["network", "install-method", "address", "external-primary", "external-worker", "listener-primary",
            "listener-worker", "public-ip", "data-dir"]
    missing = [k for k in need if not isinstance(o.get(k), str)]
    if missing:
        emit(event="done", ok=False, phase="keygen", msg="missing --%s" % ", --".join(missing))
        sys.exit(1)
    if o["install-method"] == "docker" and not re.match(r"^[^@\s]+@sha256:[0-9a-f]{64}$", str(o.get("docker-image", ""))):
        emit(event="done", ok=False, phase="keygen", msg="devnet needs --docker-image <repo>@sha256:<digest>")
        sys.exit(1)
    if "passphrase-stdin" in o:
        secret = sys.stdin.read()
        if not secret.strip():
            emit(event="done", ok=False, phase="keygen", msg="--passphrase-stdin: empty passphrase on stdin")
            sys.exit(1)
    ddir = o["data-dir"]
    if os.path.exists(os.path.join(ddir, "node-keys")):
        emit(event="done", ok=False, phase="keygen", msg="node-keys already exist in %s" % unroot(ddir))
        sys.exit(1)
    rng = random.Random("keys-" + inst)
    emit(event="step", name="preflight")
    emit(event="step", name="infrastructure")
    os.makedirs(os.path.join(ddir, "node-keys"), exist_ok=True)
    with open(os.path.join(ddir, "node-keys", "shim-fake-keys"), "w") as f:
        f.write("fake key material for %s (l2-shim)\n" % inst)
    pkey, ppid = libp2p_key(rng)
    wkey, wpid = libp2p_key(rng)
    bls = b58enc(bytes(rng.getrandbits(8) for _ in range(96)))
    # The shape of a real node-info.yaml (launch 1's genesis/validators/node1.yaml); keys are fake.
    rpc = "      rpc: ~\n"
    if isinstance(o.get("rpc-http"), str) or isinstance(o.get("rpc-ws"), str):
        rpc = "      rpc:\n"
        if isinstance(o.get("rpc-http"), str):
            rpc += '        http: "%s"\n' % o["rpc-http"]
        if isinstance(o.get("rpc-ws"), str):
            rpc += '        ws: "%s"\n' % o["rpc-ws"]
    info = ("---\nname: node-%s\nbls_public_key: %s\np2p_info:\n  primary:\n    network_address: %s/p2p/%s\n"
            "    network_key: %s\n    rpc: ~\n  workers:\n    - network_address: %s/p2p/%s\n      network_key: %s\n%s" % (
                b58(rng, 11), bls, o["external-primary"], ppid, pkey, o["external-worker"], wpid, wkey, rpc))
    info += 'execution_address: "%s"\nproof_of_possession: %s\n' % (
        o["address"], b58enc(bytes(rng.getrandbits(8) for _ in range(48))))
    with open(os.path.join(ddir, "node-info.yaml"), "w") as f:
        f.write(info)
    set_owner(inst, unroot(ddir).rstrip("/"), "telcoin:telcoin", recursive=True)
    meta_set(root, {"HOST_SERVICE_USER": "telcoin", "HOST_SERVICE_GROUP": "telcoin",
                    "INSTALL_METHOD": o["install-method"], "DATA_DIR": unroot(ddir), "OWNERSHIP_LAYOUT": "v2",
                    "PASSPHRASE_METHOD": "stdin", "DOCKER_IMAGE": o.get("docker-image", ""),
                    "NETWORK": o["network"], "VALIDATOR_ADDRESS": o["address"]})
    emit(event="step", name="generate keys")
    emit(event="done", ok=True, phase="keygen", msg="keys generated", node_info_path=unroot(ddir) + "/node-info.yaml")


TND = {"setup-node.sh": tnd_setup_node}


def tnd(argv):
    script, args = argv[0], argv[1:]
    remote_detail("tnd:" + script, args)
    flag_check(script, args)
    fn = TND.get(script)
    if fn is None:
        strict_fail("UNRECOGNISED", host()[0], os.environ.get("L2_SHIM_CMD", script), "no emulator for %s" % script)
    fn(args)


# ----------------------------------------------------------------------------- operator-side docker
DOCKER_VALUE_OPTS = {"--platform", "-v", "--volume", "--workdir", "-w", "--user", "-u", "-e", "--env", "--entrypoint",
                     "--network", "--name"}
DOCKER_BOOL_OPTS = {"-i", "--interactive", "--rm", "-t"}


def local_docker(argv):
    cmd = "docker " + " ".join(shlex.quote(a) for a in argv)
    data = b""
    if argv[:1] == ["run"] and ("-i" in argv or "--interactive" in argv):
        data = sys.stdin.buffer.read()
    log_call("docker", None, cmd, len(data) if data else None)
    if argv[:1] != ["run"]:
        strict_fail("UNRECOGNISED", None, cmd, "operator-side docker %s has no emulator" % (argv[:1] or ["<none>"])[0])
    i, opts = 1, {}
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        k, v = (a.split("=", 1) + [None])[:2] if a.startswith("--") and "=" in a else (a, None)
        if k in DOCKER_VALUE_OPTS:
            if v is None:
                i += 1
                v = argv[i]
            opts.setdefault(k, []).append(v)
        elif k not in DOCKER_BOOL_OPTS:
            strict_fail("UNRECOGNISED", None, cmd, "docker run option %s not emulated" % k)
        i += 1
    image, prog = argv[i], argv[i + 1:]
    if image != os.environ.get("DOCKER_IMAGE", image):
        finding("SUSPECT", None, cmd, "docker image %s is not DOCKER_IMAGE" % image, fatal=False)
    if not re.match(r"^[^@\s]+@sha256:[0-9a-f]{64}$", image):
        strict_fail("UNSAFE", None, cmd, "docker image not pinned by digest")
    mounts = {}
    for vol in opts.get("-v", []) + opts.get("--volume", []):
        h, c = vol.split(":")[:2]
        mounts[c.rstrip("/") or "/"] = os.path.abspath(h)
    wd = (opts.get("--workdir") or opts.get("-w") or ["/"])[-1]

    def hostp(p):
        p = p if p.startswith("/") else os.path.join(wd, p)
        for c, h in sorted(mounts.items(), key=lambda x: -len(x[0])):
            if p == c or p.startswith(c + "/"):
                return h + p[len(c):]
        strict_fail("UNSAFE", None, cmd, "container path %s is not on a mounted volume" % p)
    if prog[:1] in (["telcoin"], ["/usr/local/bin/telcoin"]) and prog[1:2] == ["genesis"]:
        return telcoin_genesis(prog[2:], hostp, data, cmd)
    strict_fail("UNRECOGNISED", None, cmd, "no emulator for container command %s" % " ".join(prog[:2]))


def ms_human(ms):
    ms = int(ms)
    return "%ds" % (ms // 1000) if ms % 1000 == 0 else "%dms" % ms


def telcoin_genesis(argv, hostp, data, cmd):
    """The image's `telcoin genesis`: committee.yaml from genesis/validators/*.yaml, the delays into
    parameters.yaml. genesis.yaml itself is NOT generated: the existing file is kept as the template
    (the real one embeds the committee and the accounts; nothing downstream in the shim reads that)."""
    o = opts_of(argv)
    if o.get("bls-passphrase-source") == "stdin" and not data.strip():
        sys.stderr.write("Error: empty BLS passphrase on stdin\n")
        sys.exit(1)
    if str(o.get("chain-id")) != os.environ.get("CHAIN_ID", str(o.get("chain-id"))):
        strict_fail("UNSAFE", None, cmd, "--chain-id %s is not CHAIN_ID" % o.get("chain-id"))
    datadir = hostp(o.get("datadir", "./"))
    if not os.path.isfile(hostp(o["accounts"])):
        sys.stderr.write("Error: accounts file %s not found\n" % o["accounts"])
        sys.exit(1)
    vdir = os.path.join(datadir, "genesis", "validators")
    infos = sorted(os.path.join(vdir, f) for f in os.listdir(vdir) if f.endswith(".yaml"))
    auth, boot = [], []
    for p in infos:
        txt = open(p).read()
        bls = re.search(r"^bls_public_key: (\S+)", txt, re.M).group(1)
        addr = re.search(r'^execution_address: "?(0x[0-9a-fA-F]{40})', txt, re.M).group(1).lower()
        p2p = re.search(r"^p2p_info:\n((?:  .*\n)+)", txt, re.M).group(1)
        auth.append('  %s:\n    protocol_key: %s\n    execution_address: "%s"\n' % (bls, bls[:114], addr))
        boot.append("  %s:\n%s" % (bls, "".join("  " + l + "\n" for l in p2p.splitlines())))
    gdir = os.path.join(datadir, "genesis")
    with open(os.path.join(gdir, "committee.yaml"), "w") as f:
        f.write("---\nauthorities:\n%sepoch: 0\nbootstrap_servers:\n%s" % ("".join(auth), "".join(boot)))
    if not os.path.isfile(os.path.join(gdir, "genesis.yaml")):
        strict_fail("UNRECOGNISED", None, cmd, "fake telcoin genesis needs a template genesis/genesis.yaml")
    pfile = os.path.join(datadir, "parameters.yaml")
    txt = open(pfile).read() if os.path.exists(pfile) else ""
    for key, flag in (("min_header_delay", "min-header-delay-ms"), ("max_header_delay", "max-header-delay-ms"),
                      ("max_batch_delay", "max-batch-delay-ms")):
        if flag in o:
            txt = re.sub(r"^%s: .*$" % key, "%s: %s" % (key, ms_human(o[flag])), txt, flags=re.M)
    with open(pfile, "w") as f:
        f.write(txt)
    print("genesis created (l2-shim fake): %d validators" % len(infos))


# ----------------------------------------------------------------------------- operator-side fakes
def local_dig(argv):
    log_call("dig", None, "dig " + " ".join(argv))
    names = [a for a in argv if not a.startswith("+") and a not in ("A", "IN")]
    dns = jload(sp("dns.json"), {})
    if len(names) != 1 or "+short" not in argv:
        strict_fail("UNRECOGNISED", None, "dig " + " ".join(argv), "dig form not emulated")
    if names[0] in dns:
        print(dns[names[0]])


def local_cast(argv):
    log_call("cast", None, "cast " + " ".join(shlex.quote(a) for a in argv))
    real = os.environ.get("L2_SHIM_REAL_CAST", "")
    if argv[:1] and argv[0] in CAST_OFFLINE and real:
        os.execv(real, [real] + argv)  # a pure conversion: no RPC, no key
    strict_fail("UNRECOGNISED", None, "cast " + " ".join(argv),
                "cast subcommand not emulated (only the offline ones in CAST_OFFLINE pass through)")


CAST_OFFLINE = {"keccak", "keccak256", "to-check-sum-address", "to-checksum-address", "to-checksum", "to-hex",
                "to-dec", "to-uint256", "to-bytes32", "abi-encode", "calldata", "sig", "from-wei", "to-wei",
                "concat-hex", "max-uint", "address-zero", "hash-zero", "compute-address", "index",
                "index-erc7201", "to-int256", "pad"}


def local_strict(tool, argv):
    cmd = tool + " " + " ".join(shlex.quote(a) for a in argv)
    log_call(tool, None, cmd)
    strict_fail("UNRECOGNISED", None, cmd, "operator-side %s has no emulator for this call" % tool)


def sentinel(argv):
    tool = argv[0]
    with open(sp("sentinel.log"), "a") as f:
        f.write("step=%s\t%s\t%s\n" % (cur_step(), tool, oneline(" ".join(argv[1:]))))
    sys.stderr.write("L2-SHIM SENTINEL: a call reached the sentinel for '%s' (no fake for it): refused\n" % tool)
    sys.exit(99)


# ----------------------------------------------------------------------------- harness
def gen_flags(argv):
    tnd_dir = argv[0]
    pat = re.compile(r"^\s*(-{1,2}[A-Za-z0-9][-A-Za-z0-9]*(?:=\*)?(?:\s*\|\s*-{1,2}[A-Za-z0-9][-A-Za-z0-9]*(?:=\*)?)*)\s*(?:\)|\|\s*\\$)")
    out = {}
    for name in sorted(os.listdir(tnd_dir)):
        p = os.path.join(tnd_dir, name)
        if not (name.endswith(".sh") and os.path.isfile(p)):
            continue
        flags = set()
        with open(p, errors="replace") as f:
            for line in f:
                m = pat.match(line)
                if m:
                    flags.update(re.findall(r"-{1,2}[A-Za-z0-9][-A-Za-z0-9]*", m.group(1)))
        out[name] = sorted(flags)
    head = subprocess.run(["git", "-C", tnd_dir, "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL).stdout.decode().strip()
    print(json.dumps({"tnd_dir": tnd_dir, "tnd_head": head, "scripts": out}, indent=1, sort_keys=True))


def init(argv):
    """stdin: lines '<inst> <zone> <static_ip_name> <reserve 0|1>'; then secrets 'secret <name>'."""
    c = {"instances": {}, "addresses": {}, "firewall_rules": {}, "secrets": {}}
    for line in sys.stdin:
        w = line.split()
        if not w:
            continue
        if w[0] == "vm":  # a VM the teardown keeps (the obs VM), on its reserved address
            ip = det_ip("static-" + w[3], 35)
            c["addresses"][w[3]] = {"address": ip, "region": region_of(w[2]), "status": "IN_USE", "users": [w[1]]}
            c["instances"][w[1]] = {"zone": w[2], "status": "RUNNING", "int_ip": det_ip("int-" + w[1], 10),
                                    "ext_ip": ip, "tags": ["obs"], "metadata": {}, "serial": "kept by the teardown\n"}
            for d in ("etc", "tmp", "home/tnadmin", "var/lib", "opt"):
                os.makedirs(sp("hosts", w[1], "root", d), exist_ok=True)
            jsave(sp("hosts", w[1], "units.json"), {"docker": {"active": True, "enabled": True}})
            if len(w) > 4:  # its data disk, mounted
                os.makedirs(sp("hosts", w[1], "root", w[4].lstrip("/")), exist_ok=True)
                jsave(sp("hosts", w[1], "mounts.json"), [w[4]])
        elif w[0] == "disk":  # a disk the teardown keeps (the obs data disk), attached to its VM
            c.setdefault("disks", {})[w[1]] = {"zone": w[2], "sizeGb": w[3], "type": "pd-ssd", "status": "READY",
                                               "users": [w[4]]}
        elif w[0] == "secret":
            c["secrets"][w[1]] = ["l2-shim-fake-%s-%s\n" % (w[1], hashlib.sha256(w[1].encode()).hexdigest()[:24])]
        elif w[3] == "1":
            c["addresses"][w[2]] = {"address": det_ip("static-" + w[2], 35), "region": region_of(w[1]),
                                    "status": "RESERVED", "users": []}
    os.makedirs(sp("hosts"), exist_ok=True)
    jsave(sp("cloud.json"), c)
    jsave(sp("dns.json"), {})
    real = sp("sandbox-real")
    os.makedirs(real, exist_ok=True)
    os.makedirs(sp("real-tools"), exist_ok=True)
    for t in ("install", "stat"):  # tools a remote fake wraps: reached by absolute path only
        w = shutil.which(t, path=os.environ.get("L2_SHIM_ORIG_PATH", os.environ.get("PATH", "")))
        if w and not os.path.lexists(sp("real-tools", t)):
            os.symlink(w, sp("real-tools", t))
    for t in SAFE_REAL:
        w = shutil.which(t, path=os.environ.get("L2_SHIM_ORIG_PATH", os.environ.get("PATH", "")))
        if w and not os.path.lexists(os.path.join(real, t)):
            os.symlink(w, os.path.join(real, t))


def pty_run(argv):
    logpath, cmd = argv[0], argv[argv.index("--") + 1:]
    sig = os.environ.get("L2_SHIM_SIG", "pending")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    buf, signed, log = "", False, open(logpath, "ab")
    expected, seen = int(os.environ.get("L2_SHIM_FROM", "1")), 0
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 1.0)
        except InterruptedError:
            continue
        if fd not in r:
            continue
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        sys.stdout.buffer.write(data)
        sys.stdout.flush()
        log.write(data)
        buf += data.decode("utf-8", "replace").replace("\r", "")
        # Sub-scripts print their own ">>> Step N:" lines: only the deploy's next step counts
        # (the one after its last "## step N done").
        for m in re.finditer(r"^## step (\d+) done|^>>> Step (\d+):", buf, re.M):
            if m.group(1):
                expected = int(m.group(1)) + 1
            elif int(m.group(2)) == expected and seen != expected:
                seen = expected
                with open(sp("current_step"), "w") as f:
                    f.write(str(seen))
                if sig == "ok" and seen >= 7 and not signed:
                    signed = sign_release()
        if "Press ENTER when this manual step is complete" in buf:
            section = buf[buf.rfind(">>> Step 4"):]
            recs = re.findall(r"^\s+(\S+)\s+A\s+(\d+\.\d+\.\d+\.\d+)\s", section, re.M)
            dns = jload(sp("dns.json"), {})
            dns.update(dict(recs))
            jsave(sp("dns.json"), dns)
            log_call("operator", None, "DNS pause: created %d A records as printed, pressed ENTER" % len(recs))
            os.write(fd, b"\n")
            buf = buf.replace("Press ENTER when this manual step is complete", "[answered]")
        keep = buf.rfind("\n")
        buf = buf[keep + 1:] if "Press ENTER" not in buf and keep >= 0 and ">>> Step 4" not in buf else buf[-20000:]
    _, status = os.waitpid(pid, 0)
    sys.exit(os.waitstatus_to_exitcode(status))


def sign_release():
    """--sig ok: the out-of-band signer signs SHA256SUMS once step 6 has written it."""
    rel = os.environ.get("L2_SHIM_RELEASE_DIR", "")
    sums = os.path.join(rel, "SHA256SUMS")
    if not rel or not os.path.exists(sums) or os.path.exists(sums + ".asc"):
        return os.path.exists(sums + ".asc")
    rc = subprocess.call(["gpg", "--homedir", sp("gnupg"), "--batch", "--yes", "--quiet", "--detach-sign", "--armor",
                          "--output", sums + ".asc", sums])
    log_call("operator", None, "signed %s with the shim's throwaway key (rc %d)" % (unroot(sums), rc))
    return rc == 0


def report(argv):
    o = opts_of(argv)
    rc, frm, to, sig = int(o["rc"]), o.get("from", "1"), o.get("to", "20"), o.get("sig", "pending")
    calls = []
    try:
        with open(sp("calls.log")) as f:
            calls = [l.rstrip("\n").split("\t") for l in f if l.strip()]
    except FileNotFoundError:
        pass
    per_step, per_inst = {}, {}
    for c in calls:
        step, tool, inst = c[1][5:], c[2], c[3]
        if tool in ("ssh", "scp"):
            per_step[step] = per_step.get(step, 0) + 1
            per_inst[inst] = per_inst.get(inst, 0) + 1
    findings = []
    try:
        with open(sp("findings.log")) as f:
            findings = [l.rstrip("\n").split("\t") for l in f if l.strip()]
    except FileNotFoundError:
        pass
    sentinel_hits = open(sp("sentinel.log")).read().splitlines() if os.path.exists(sp("sentinel.log")) else []
    gc_logs = []
    for d, _, fs in os.walk(sp("poison", "gcloud-config")):
        gc_logs += [os.path.join(d, x) for x in fs]
    reached = cur_step()
    out = open(sp("deploy-output.log"), errors="replace").read() if os.path.exists(sp("deploy-output.log")) else ""
    print("==== l2-shim report ====")
    print("deploy exit code : %d" % rc)
    print("step reached     : %s (range %s..%s, --sig %s)" % (reached, frm, to, sig))
    print("remote commands per step     : %s" % ", ".join("%s=%d" % (k, per_step[k]) for k in sorted(per_step, key=lambda x: int(x) if x.isdigit() else 0)))
    print("remote commands per instance : %s" % ", ".join("%s=%d" % (k, v) for k, v in sorted(per_inst.items())))
    print("gcloud calls total: %d (calls.log lines %d)" % (sum(1 for c in calls if c[2] == "gcloud"), len(calls)))
    fatal = [f for f in findings if f[-1] == "fatal"]
    for f in findings:
        print("%-12s step %-3s %-22s %s\n             command: %s" % (f[0], f[1][5:], f[2], f[3], f[4][:400]))
    print("sentinel hits    : %d%s" % (len(sentinel_hits), "".join("\n   " + s for s in sentinel_hits)))
    print("real gcloud logs : %d (files under poison/gcloud-config: a real gcloud would have written one)" % len(gc_logs))
    crashes = out.count("Traceback (most recent call last)")
    print("shim crashes     : %d (a Python traceback from fakes.py is a shim bug, never a pass)" % crashes)
    ok = not fatal and not sentinel_hits and not gc_logs and not crashes
    if sig == "pending" and int(frm) <= 10 <= int(to):
        gate = rc == 3 and reached == "10" and "RELEASE_SIG_PENDING" in out
        print("signature gate   : %s (expect exit 3 at step 10 with RELEASE_SIG_PENDING)" % ("held" if gate else "NOT held"))
        ok = ok and gate
    else:
        ok = ok and rc == 0
    print("RESULT: %s" % ("CLEAN" if ok else "NOT CLEAN"))
    sys.exit(0 if ok else 1)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        sys.exit(2)
    tool, argv = sys.argv[1], sys.argv[2:]
    remote = bool(os.environ.get("L2_SHIM_HOST"))
    if tool == "gcloud" and not remote:
        return gcloud(argv)
    if remote:
        if tool == "sudo":
            return r_sudo(argv)
        if tool == "systemctl":
            return r_systemctl(argv)
        if tool == "tnd":
            return tnd(argv)
        if tool == "stat":
            return r_stat(argv)
        return r_simple(tool, argv)
    table = {"dig": local_dig, "cast": local_cast, "docker": local_docker, "init": init, "gen-flags": gen_flags, "pty-run": pty_run,
             "report": report, "sentinel": sentinel}
    if tool in table:
        return table[tool](argv)
    return local_strict(tool, argv)


if __name__ == "__main__":
    main()
