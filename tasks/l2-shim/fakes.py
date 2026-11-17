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
              "usr/local/libexec", "opt", "run"):  # /run: a tmpfs on every real VM (start-at marks live there)
        os.makedirs(os.path.join(root, d), exist_ok=True)
    units = {"docker": {"active": True, "enabled": True}, "ufw": {"active": False, "enabled": True},
             "nftables": {"active": False, "enabled": False}, "ssh": {"active": True, "enabled": True}}
    lines = ["Starting startup scripts", "startup-script: [devnet-startup] docker installed"]
    ref = rec["metadata"].get("tn-scripts-ref")
    if "startup-script" in rec["metadata"] and ref:
        sd = os.path.join(root, NODE_SCRIPTS.lstrip("/"))
        os.makedirs(sd, exist_ok=True)
        nft = os.path.join(root, "usr/sbin/nft")  # nftables is on the image; executing it is a finding
        os.makedirs(os.path.dirname(nft), exist_ok=True)
        with open(nft, "w") as f:
            f.write('#!/usr/bin/env bash\nexec "${L2_SHIM_PY}" "${L2_SHIM_DIR}/fakes.py" tnd nft "$@"\n')
        os.chmod(nft, 0o755)
        flags = jload(sp("flags.json"), {"scripts": {}})
        for script in flags["scripts"]:
            p = os.path.join(sd, script)
            os.makedirs(os.path.dirname(p), exist_ok=True)
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
    # Real ssh forwards stdin with or without -T (-T only refuses a pty); a remote `bash -s` reads it to
    # EOF. So stdin is read for -T or a shell-from-stdin command, and otherwise inherited (None).
    reads = "-T" in ssh_flags or (isinstance(cmd, str) and shell_stdin(cmd))
    data = sys.stdin.buffer.read() if reads else None
    shown = cmd if isinstance(cmd, str) else "<no --command>"
    log_call("ssh", inst, shown, len(data) if reads else None)
    if not isinstance(cmd, str) or not cmd.strip():
        strict_fail("UNSAFE", inst, cmdline, "gcloud compute ssh without a command opens a login shell")
    if not f1(fl, "tunnel-through-iap"):
        finding("SUSPECT", inst, shown, "gcloud compute ssh without --tunnel-through-iap", fatal=False)
    running_instance(inst, f1(fl, "zone"), cmdline, "ssh")
    fw = jload(sp("hosts", inst, "ufw.json"), {"active": False, "rules": []})
    if fw["active"] and not ({"22/tcp from any", "22/tcp from %s" % IAP_RANGE} & set(fw["rules"])):
        sys.stderr.write("ssh: connect to host %s port 22: Connection timed out (ufw, l2-shim)\n" % inst)
        sys.exit(255)
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
REWRITE = re.compile(r"(?<![\w.~/:-])/(etc|var|opt|tmp|home|root|run|srv|mnt|usr/local|usr/sbin|lib/systemd|usr/lib/systemd|proc(?!/self\b))(?=[/'\"\s;|&)]|$)")
OUTSIDE = re.compile(r"(?<![\w.~/:-])/(usr|bin|sbin|lib|lib64|boot|dev|proc|sys|snap|media)\b(/[\w.+-]+)*")
ALLOWED_OUTSIDE = re.compile(r"^/(dev/(null|stdin|stdout|stderr|fd/\d+|urandom)|usr/bin/env|bin/(ba)?sh|usr/bin/(ba)?sh|proc/self/\S*|usr/share/\S*)$")
SAFE_REAL = ("bash sh cat grep sed awk test [ cp mv rm mkdir rmdir chmod ln ls head tail sha256sum md5sum "
             "printf echo date sleep tr cut wc sort uniq find xargs base64 mktemp tee dirname basename readlink "
             "realpath true false env touch cmp diff seq od timeout nproc flock sync python3 jq awk mawk gawk "
             "comm paste fold rev nl expr yes du df cksum").split()


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


def shell_stdin(cmd):
    return re.search(r"(^|[\s;&|])(ba)?sh\s+-s(\s|$)", cmd) is not None


def run_remote(inst, cmd, data):
    root = sp("hosts", inst, "root")
    rcmd = rewrite(cmd, root)
    # A shell reading its script from stdin (`sudo [VAR=v …] bash -s`, any prefix): the script's paths
    # are rewritten and checked like a command's. Any other stdin (a passphrase, a token) is passed as is.
    is_shell_stdin = shell_stdin(cmd) and data is not None
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
    if argv and argv[0] in ("show", "cat"):
        return r_systemctl_read(inst, root, argv)
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
        elif verb in ("daemon-reload", "reset-failed"):
            pass
        elif verb == "list-unit-files":
            for u in targets:
                if os.path.exists(os.path.join(root, "etc/systemd/system", u + ".service")):
                    print("%s.service %s enabled" % (u, "enabled" if units.get(u, {}).get("enabled") else "disabled"))
        else:
            strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "systemctl %s not emulated" % verb)
        jsave(units_path(), units)
    if "telcoin" in targets and verb in ("start", "stop", "restart", "enable", "disable"):
        node_runtime(inst, root, units.get("telcoin", {}).get("active", False))
    sys.exit(rc)


def r_systemctl_read(inst, root, argv):
    cmd = os.environ.get("L2_SHIM_CMD", "")
    props, value, units_, i = [], False, [], 1
    while i < len(argv):
        a = argv[i]
        if a == "-p" or a == "--property":
            props += argv[i + 1].split(",")
            i += 1
        elif a.startswith("--property=") or a.startswith("-p") and len(a) > 2:
            props += a.split("=", 1)[1].split(",") if "=" in a else a[2:].split(",")
        elif a == "--value":
            value = True
        elif a in ("--no-pager",):
            pass
        elif a.startswith("-"):
            strict_fail("UNRECOGNISED", inst, cmd, "systemctl %s %s not emulated" % (argv[0], a))
        else:
            units_.append(unit_name(a))
        i += 1
    st = jload(units_path(), {})
    for u in units_:
        path = os.path.join(root, "etc/systemd/system", u + ".service")
        if argv[0] == "cat":
            if not os.path.exists(path):
                sys.stderr.write("No files found for %s.service.\n" % u)
                sys.exit(1)
            with open(path) as f:
                sys.stdout.write("# /etc/systemd/system/%s.service\n%s" % (u, f.read()))
            continue
        rec = st.get(u) if (u in st or os.path.exists(path)) else None
        act = bool(rec and rec.get("active"))
        vals = {"ActiveState": "active" if act else "inactive", "SubState": "running" if act else "dead",
                "UnitFileState": ("enabled" if rec.get("enabled") else "disabled") if rec else "",
                "LoadState": "loaded" if rec else "not-found", "NRestarts": "0", "Result": "success",
                "MainPID": str(rec.get("pid", 0)) if act else "0",
                "ActiveEnterTimestampMonotonic": str(rec.get("enter", 0)) if rec else "0"}
        for k in props or ["ActiveState", "SubState", "UnitFileState", "NRestarts", "Result", "MainPID"]:
            if k not in vals:
                strict_fail("UNRECOGNISED", inst, cmd, "systemctl show property %s not emulated" % k)
            print(vals[k] if value else "%s=%s" % (k, vals[k]))
    sys.exit(0)


# ----------------------------------------------------------------------------- the fake node runtime
NODE_PID, CONTAINER_PID = 4242, 4343


def journal_add(inst, unit, msgs):
    with Locked():
        j = jload(sp("hosts", inst, "journal.json"), [])
        j += [[unit, m] for m in msgs]
        jsave(sp("hosts", inst, "journal.json"), j)


def node_runtime(inst, root, active):
    """What a started (or stopped) docker-form telcoin unit leaves: the docker client as MainPID with
    /proc/<pid>/{cmdline,environ}, the container, journal lines, a line in the log file."""
    import shutil as _sh
    start = os.path.join(root, "usr/local/libexec/telcoin/tn-start-docker")
    for pid in (NODE_PID, CONTAINER_PID):
        _sh.rmtree(os.path.join(root, "proc", str(pid)), ignore_errors=True)
    with Locked():
        units = jload(units_path(), {})
        if "telcoin" in units:
            units["telcoin"]["pid"] = NODE_PID if active else 0
            if active:
                units["telcoin"]["enter"] = int(time.monotonic() * 1e6)
        jsave(units_path(), units)
        dock = jload(sp("hosts", inst, "containers.json"), {})
        dock.pop("telcoin", None)
        line = ""
        if active and os.path.exists(start):
            with open(start) as f:
                line = [l for l in f if l.startswith("exec ") and " node " in l][-1].strip()
            argv = shlex.split(line)[1:]
            image = argv[argv.index("telcoin", argv.index("--pull=never")) - 1]
            dock["telcoin"] = {"Running": True, "ReadonlyRootfs": "--read-only" in argv, "Pid": CONTAINER_PID,
                               "Image": image}
            for pid, cl, env in ((NODE_PID, argv, ["PATH=/usr/bin", "PRIMARY_LISTENER_MULTIADDR=x"]),
                                 (CONTAINER_PID, argv[argv.index(image) + 1:], ["HOME=/home/nonroot"])):
                d = os.path.join(root, "proc", str(pid))
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "cmdline"), "w") as f:
                    f.write("\0".join(cl) + "\0")
                with open(os.path.join(d, "environ"), "w") as f:
                    f.write("\0".join(env) + "\0")
        jsave(sp("hosts", inst, "containers.json"), dock)
    msg = ["l2-shim: telcoin node started (fake)"] if active else ["l2-shim: telcoin node stopped (fake)"]
    journal_add(inst, "telcoin", msg)
    logd = os.path.join(root, "var/log/telcoin")
    if os.path.isdir(logd):
        with open(os.path.join(logd, "telcoin.log"), "a") as f:
            f.write("INFO %s\n" % msg[0])


def node_health(inst, root, path):
    up = jload(units_path(), {}).get("telcoin", {}).get("active")
    meta = os.path.join(root, "etc/telcoin/.node-meta")
    hc = os.path.exists(meta) and "ENABLE_HEALTHCHECK_MONITOR=true" in open(meta).read()
    return (200, "OK") if up and hc else (0, "")


def r_journalctl(argv):
    remote_detail("journalctl", argv)
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    unit, after, n, cursor = None, None, None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-u", "--unit"):
            unit = unit_name(argv[i + 1])
            i += 1
        elif a.startswith("--after-cursor="):
            after = a.split("=", 1)[1]
        elif a == "-n":
            n = int(argv[i + 1])
            i += 1
        elif a == "--show-cursor":
            cursor = True
        elif a == "-o" and argv[i + 1] == "cat":
            i += 1
        elif a in ("--no-pager", "-b", "-q"):
            pass
        else:
            strict_fail("UNRECOGNISED", inst, cmd, "journalctl %s not emulated" % a)
        i += 1
    j = jload(sp("hosts", inst, "journal.json"), [])
    idx = [k for k in range(len(j)) if unit is None or j[k][0] == unit]
    if after is not None:
        m = re.match(r"^s=l2shim;i=(\d+)$", after)
        if not m:
            sys.stderr.write("Failed to seek to cursor: Invalid argument\n")
            sys.exit(1)
        idx = [k for k in idx if k >= int(m.group(1))]
    if n is not None:
        idx = idx[-n:] if n else []
    for k in idx:
        print(j[k][1])
    if cursor:
        print("-- cursor: s=l2shim;i=%d" % ((idx[-1] + 1) if idx else len(j)))
    sys.exit(0)


def r_pgrep(argv):
    remote_detail("pgrep", argv)
    inst, root = host()
    if len(argv) != 2 or argv[0] != "-f":
        strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "pgrep %s not emulated" % " ".join(argv))
    rc = 1
    pd = os.path.join(root, "proc")
    for pid in sorted(os.listdir(pd)) if os.path.isdir(pd) else []:
        with open(os.path.join(pd, pid, "cmdline")) as f:
            if re.search(argv[1], f.read().replace("\0", " ")):
                print(pid)
                rc = 0
    sys.exit(rc)


def r_ss(argv):
    remote_detail("ss", argv)
    inst, root = host()
    if not argv or not re.match(r"^-[ltnHp]+$", argv[0]) or "l" not in argv[0] or "t" not in argv[0] or len(argv) > 1:
        strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "ss %s not emulated" % " ".join(argv))
    units = jload(units_path(), {})
    socks = ["0.0.0.0:22"]
    if units.get("telcoin", {}).get("active"):
        socks += node_binds(root)
    socks += LISTEN_EXTRA(inst, root, units)
    if "H" not in argv[0]:
        print("State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process")
    for a in socks:
        print("LISTEN 0      4096   %s %s" % (a, "0.0.0.0:*"))
    sys.exit(0)


def LISTEN_EXTRA(inst, root, units):
    out = []
    if units.get("telcoin-gateway", {}).get("active"):
        out += ["127.0.0.1:8655", "127.0.0.1:8656", "127.0.0.1:9655"]
    if units.get("caddy", {}).get("active"):
        out += ["0.0.0.0:80", "0.0.0.0:443"]
    return out


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


# ----------------------------------------------------------------------------- remote curl / docker
CURL_VALUE_OPTS = {"-H", "--header", "-w", "--write-out", "-o", "--output", "-m", "--max-time", "--connect-timeout",
                   "-X", "--request", "--retry", "--retry-delay"}
CURL_BOOL_OPTS = set("sSfLk") | {"--silent", "--show-error", "--fail", "--location", "--insecure", "--no-progress-meter"}
HEALTH_URLS = {}  # port -> handler(inst, root, path) -> (http code, body); 0 = connection refused


def curl_answer(inst, root, url, headers):
    """(http code, body) for the URLs a VM really reaches: the metadata server's token, Secret Manager's
    REST access (the obs bring-up) and the node's loopback health port. Anything else is refused."""
    m = re.match(r"^http://metadata\.google\.internal/computeMetadata/v1/instance/service-accounts/default/token$", url)
    if m:
        if "Metadata-Flavor: Google" not in headers:
            return 403, "Missing Metadata-Flavor:Google header."
        return 200, json.dumps({"access_token": "l2-shim-fake-vm-token", "expires_in": 3599, "token_type": "Bearer"})
    m = re.match(r"^https://secretmanager\.googleapis\.com/v1/projects/([^/]+)/secrets/([^/]+)/versions/latest:access$", url)
    if m:
        if not any(h.startswith("Authorization: Bearer ") for h in headers):
            return 401, json.dumps({"error": {"code": 401, "message": "missing credentials"}})
        vers = cloud()["secrets"].get(m.group(2)) if m.group(1) == PROJECT else None
        if not vers:
            return 404, json.dumps({"error": {"code": 404, "message": "Secret [%s] not found or has no versions." % m.group(2)}})
        import base64
        return 200, json.dumps({"name": "projects/%s/secrets/%s/versions/%d" % (PROJECT, m.group(2), len(vers)),
                                "payload": {"data": base64.b64encode(vers[-1].encode()).decode()}})
    m = re.match(r"^(?:https?://)?(127\.0\.0\.1|localhost):(\d+)(/[^?#]*)?$", url)
    if m:
        fn = HEALTH_URLS.get(int(m.group(2))) or ({43174: node_health, 8656: gw_probe}).get(int(m.group(2)))
        if fn is None:
            return 0, ""  # nothing listens there: connection refused (curl rc 7)
        return fn(inst, root, m.group(3) or "/")
    return None, None


def r_curl(argv):
    remote_detail("curl", argv)
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    vals, flags, urls, i = {}, set(), [], 0
    while i < len(argv):
        a = argv[i]
        if a in CURL_VALUE_OPTS:
            vals.setdefault(a, []).append(argv[i + 1])
            i += 2
            continue
        if a.startswith("--") and "=" in a and a.split("=", 1)[0] in CURL_VALUE_OPTS:
            k, v = a.split("=", 1)
            vals.setdefault(k, []).append(v)
        elif a in CURL_BOOL_OPTS or (re.match(r"^-[sSfLk]+$", a)):
            flags.update(a[1:] if not a.startswith("--") else [a])
        elif a.startswith("-"):
            strict_fail("UNRECOGNISED", inst, cmd, "remote curl option %s not emulated" % a)
        else:
            urls.append(a)
        i += 1
    if len(urls) != 1:
        strict_fail("UNRECOGNISED", inst, cmd, "remote curl with %d URLs not emulated" % len(urls))
    headers = vals.get("-H", []) + vals.get("--header", [])
    CURL_CTX["data"] = (vals.get("--data") or vals.get("-d") or vals.get("--data-raw") or [""])[-1]
    code, body = curl_answer(inst, root, urls[0], headers)
    if code is None:
        strict_fail("UNSAFE", inst, cmd, "remote curl to %s (no emulator; a VM would reach the network)" % urls[0])
    fail = "f" in flags or "--fail" in flags
    wout = (vals.get("-w") or vals.get("--write-out") or [""])[-1]
    if code == -28:  # a dropped packet: the client gives up at --max-time / --connect-timeout
        sys.stdout.write(wout.replace("%{http_code}", "000").replace("\\n", "\n"))
        sys.exit(28)
    if code == 0:
        if "S" in flags or not ("s" in flags or "--silent" in flags):
            sys.stderr.write("curl: (7) Failed to connect to %s: Connection refused\n" % urls[0])
        sys.stdout.write(wout.replace("%{http_code}", "000").replace("\\n", "\n"))
        sys.exit(7)
    out = body if not (fail and code >= 400) else ""
    dest = (vals.get("-o") or vals.get("--output") or [None])[-1]
    if dest and dest != "/dev/null":
        with open(dest, "w") as f:
            f.write(out)
    elif not dest:
        sys.stdout.write(out)
    sys.stdout.write(wout.replace("%{http_code}", str(code)).replace("\\n", "\n"))
    sys.exit(22 if fail and code >= 400 else 0)


def docker_inspect(inst, cmd, argv):
    if len(argv) != 3 or argv[0] != "-f":
        strict_fail("UNRECOGNISED", inst, cmd, "docker inspect %s not emulated" % " ".join(argv))
    c = jload(sp("hosts", inst, "containers.json"), {}).get(argv[2])
    if c is None:
        sys.stderr.write("Error: No such object: %s\n" % argv[2])
        sys.exit(1)
    out = argv[1]
    for k, v in (("State.Running", c["Running"]), ("HostConfig.ReadonlyRootfs", c["ReadonlyRootfs"]),
                 ("State.Pid", c["Pid"]), ("Config.Image", c["Image"])):
        out = out.replace("{{.%s}}" % k, str(v).lower() if isinstance(v, bool) else str(v))
    if "{{" in out:
        strict_fail("UNRECOGNISED", inst, cmd, "docker inspect template %s not emulated" % argv[1])
    print(out)
    sys.exit(0)


def compose_services(path):
    svcs, inside = [], False
    with open(path) as f:
        for line in f:
            if re.match(r"^services:\s*$", line):
                inside = True
            elif re.match(r"^\S", line):
                inside = False
            elif inside:
                m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
                if m:
                    svcs.append(m.group(1))
    return svcs


def r_docker(argv):
    """`docker compose` in a directory holding docker-compose.yml (the obs VM's /opt/obs): up/ps/down/
    restart/kill/exec. Any other docker command on a VM is refused (strict)."""
    remote_detail("docker", argv)
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    if argv[:1] == ["inspect"]:
        return docker_inspect(inst, cmd, argv[1:])
    if not argv or argv[0] != "compose":
        strict_fail("UNRECOGNISED", inst, cmd, "remote docker %s not emulated" % " ".join(argv[:2]))
    if os.environ.get("L2_SHIM_SUDO") != "1":
        sys.stderr.write("permission denied while trying to connect to the Docker daemon socket\n")
        sys.exit(1)
    cwd = os.getcwd()
    yml = os.path.join(cwd, "docker-compose.yml")
    if not os.path.exists(yml):
        sys.stderr.write("no configuration file provided: not found\n")
        sys.exit(1)
    svcs = compose_services(yml)
    verb, rest = (argv[1] if len(argv) > 1 else ""), argv[2:]
    with Locked():
        st = jload(sp("hosts", inst, "compose.json"), {})
        proj = st.setdefault(unroot(cwd), {})
        rc = 0
        if verb == "up":
            if "-d" not in rest:
                strict_fail("UNRECOGNISED", inst, cmd, "docker compose up without -d attaches")
            for sv in svcs:
                proj[sv] = "running"
                print(" Container obs-%s-1  Started" % sv)
        elif verb == "down":
            for sv in svcs:
                proj[sv] = "removed"
        elif verb == "ps":
            print("NAME\tSERVICE\tSTATUS")
            for sv in svcs:
                if proj.get(sv) == "running":
                    print("obs-%s-1\t%s\tUp" % (sv, sv))
        elif verb in ("restart", "kill", "exec"):
            names = [a for a in rest if not a.startswith("-") and a not in ("SIGHUP", "SIGTERM")]
            target = names[0] if names else ""
            if target not in svcs:
                strict_fail("UNRECOGNISED", inst, cmd, "docker compose %s of unknown service %s" % (verb, target))
            if verb == "restart":
                proj[target] = "running"
            elif proj.get(target) != "running":
                sys.stderr.write("service %s is not running\n" % target)
                rc = 1
        else:
            strict_fail("UNRECOGNISED", inst, cmd, "docker compose %s not emulated" % verb)
        jsave(sp("hosts", inst, "compose.json"), st)
    sys.exit(rc)


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
    if phase == "finalize":
        return tnd_finalize(inst, root, o, cmd)
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


TND_DIR = os.environ.get("L2_SHIM_TND") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(SHIM_DIR))),
                                                       "tnd-l2-gateway")
MULTIADDR = re.compile(r"^/ip4/\d+\.\d+\.\d+\.\d+/udp/\d+/quic-v1$")


def meta_get(root):
    p = os.path.join(root, "etc/telcoin/.node-meta")
    kv = {}
    if os.path.exists(p):
        for l in open(p):
            if "=" in l:
                k, v = l.rstrip("\n").split("=", 1)
                kv[k] = v
    return kv


def fin_fail(msg):
    emit(event="done", ok=False, phase="finalize", msg=msg)
    sys.exit(1)


def tnd_finalize(inst, root, o, cmd):
    """setup-node.sh --json --phase=finalize (fact sheet tnd-node.md 1-4): installs the maps, renders
    network-config with the REAL tn_network_config_render, writes node.env, the docker start script, the
    unit, the service .node-meta keys, then starts and enables the unit (no --no-start exists)."""
    meta = meta_get(root)
    if not meta.get("PASSPHRASE_METHOD"):
        fin_fail("No keygen recorded in /etc/telcoin/.node-meta: run --phase=keygen first.")
    for k in ("listener-primary", "listener-worker", "external-primary", "external-worker"):
        if not isinstance(o.get(k), str) or not MULTIADDR.match(o[k]):
            fin_fail("--%s must be /ip4/<addr>/udp/<port>/quic-v1" % k)
    for k in ("network", "address", "public-ip"):
        if not isinstance(o.get(k), str):
            fin_fail("missing --%s" % k)
    if o.get("install-method", meta.get("INSTALL_METHOD")) != "docker":
        strict_fail("UNRECOGNISED", inst, cmd, "finalize emulated for the docker install method only")
    image = o.get("docker-image") if isinstance(o.get("docker-image"), str) else meta.get("DOCKER_IMAGE", "")
    if not re.match(r"^[^@\s]+@sha256:[0-9a-f]{64}$", image):
        fin_fail("devnet needs --docker-image <repo>@sha256:<digest>")
    ddir_v = meta.get("DATA_DIR") or "/var/lib/telcoin"
    ddir = os.path.join(root, ddir_v.lstrip("/"))
    adm = o.get("admission")
    if ("trusted-nodes" in o or "bootstrap-peers" in o) and not isinstance(adm, str):
        fin_fail("--trusted-nodes needs --admission open, grace or closed")
    emit(event="step", name="finalize_node_extra_flags")
    installed = {}
    for flag, dest in (("bootstrap-peers", "bootstrap-peers.yaml"), ("trusted-nodes", "trusted-nodes.yaml")):
        if flag not in o:
            continue
        src = o[flag]
        if not isinstance(src, str) or not os.path.isfile(src):
            fin_fail("--%s: %s is not a regular file" % (flag, unroot(src) if isinstance(src, str) else ""))
        st = os.stat(src)
        if st.st_mode & 0o044 != 0o044 or st.st_size > 65536:
            fin_fail("--%s: %s must be readable by all (chmod 644) and at most 65536 bytes" % (flag, unroot(src)))
        target = os.path.join(root, "etc/telcoin", dest)
        if os.path.realpath(src) != os.path.realpath(target):
            shutil.copyfile(src, target)
        os.chmod(target, 0o644)
        set_owner(inst, "/etc/telcoin/" + dest, "root:root")
        installed[flag] = target
    emit(event="step", name="config")
    if isinstance(adm, str):
        env = dict(os.environ, TN_ROOT_PREFIX=root)
        prog = ('set +eu; source "$1" >/dev/null 2>&1; set -eu; tn_as_service_user() { "$@"; }; '
                'tn_network_config_render "$2" "$3" "$4" "$5"')
        r = subprocess.run([sp("sandbox-real", "bash"), "-c", prog, "_", os.path.join(TND_DIR, "lib/common.sh"), ddir, adm,
                            installed.get("trusted-nodes", "none"), installed.get("bootstrap-peers", "none")],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode:
            fin_fail("network-config render failed: %s" % oneline(r.stderr.decode()[-300:]))
        set_owner(inst, ddir_v + "/network-config", "telcoin:telcoin")
    emit(event="step", name="step_write_config")
    os.makedirs(os.path.join(root, "var/log/telcoin"), exist_ok=True)
    set_owner(inst, "/var/log/telcoin", "root:telcoin-log")
    with open(os.path.join(root, "etc/telcoin/node.env"), "w") as f:
        f.write("PRIMARY_LISTENER_MULTIADDR=%s\nWORKER_LISTENER_MULTIADDR=%s\nTN_RPC_ADDR=127.0.0.1\n" % (
            o["listener-primary"], o["listener-worker"]))
    args = "--datadir /home/nonroot --log.stdout.format log-fmt -vvv --http --http.addr 127.0.0.1 --ws --ws.addr 127.0.0.1"
    if "enable-healthcheck-monitor" in o:
        args += " --healthcheck 43174"
    if "bootstrap-peers" in installed:
        args += ' --bootstrap-peers "$(cat /etc/telcoin/bootstrap-peers.yaml)"'
    os.makedirs(os.path.join(root, "usr/local/libexec/telcoin"), exist_ok=True)
    start = os.path.join(root, "usr/local/libexec/telcoin/tn-start-docker")
    with open(start, "w") as f:  # the docker line of lib/common.sh (LC:3760), fields filled for this host
        f.write('#!/bin/bash\nset -euo pipefail\nexec < "${CREDENTIALS_DIRECTORY:?not set: start the node with systemctl}'
                '/bls-passphrase"\nexec /usr/bin/docker run -i --rm --name telcoin --user 999:999 -e HOME=/home/nonroot '
                '-e PRIMARY_LISTENER_MULTIADDR -e WORKER_LISTENER_MULTIADDR --network=host --cap-drop ALL --security-opt '
                'no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --pids-limit 4096 --ulimit '
                'nofile=65536:65536 --ulimit core=0 --log-driver json-file --log-opt max-size=50m --log-opt max-file=3 '
                '--stop-timeout 80 --pull=never -v %s:/home/nonroot %s telcoin node --bls-passphrase-source stdin %s\n'
                % (ddir_v, image, args))
    os.chmod(start, 0o755)
    emit(event="step", name="step_create_service")
    with open(os.path.join(root, "etc/systemd/system/telcoin.service"), "w") as f:
        f.write("[Unit]\nDescription=Telcoin Network node\nAfter=network-online.target docker.service\n\n[Service]\n"
                "User=root\nUMask=0077\nEnvironmentFile=-/etc/telcoin/node.env\nExecStartPre=-/usr/bin/docker stop telcoin\n"
                "ExecStartPre=-/usr/bin/docker rm telcoin\nExecStart=/usr/local/libexec/telcoin/tn-start-docker\n"
                "LoadCredential=bls-passphrase:/etc/telcoin/bls-passphrase\nRestart=on-failure\n"
                "StandardOutput=append:/var/log/telcoin/telcoin.log\nStandardError=append:/var/log/telcoin/telcoin-error.log\n"
                "\n[Install]\nWantedBy=multi-user.target\n")
    kv = {"HOST_SERVICE_USER": "telcoin", "HOST_SERVICE_GROUP": "telcoin", "INSTALL_METHOD": "docker",
          "PASSPHRASE_METHOD": meta["PASSPHRASE_METHOD"], "NETWORK": o["network"], "DATA_DIR": ddir_v, "RPC_PORT": "8545",
          "WS_PORT": "8546", "PUBLIC_RPC_DOMAIN": "", "PUBLIC_IP": o["public-ip"],
          "EXTERNAL_PRIMARY_ADDR": o["external-primary"], "EXTERNAL_WORKER_ADDR": o["external-worker"],
          "VALIDATOR_ADDRESS": o["address"], "ENABLE_HEALTHCHECK_MONITOR": "true" if "enable-healthcheck-monitor" in o else "false",
          "PUBLIC_RPC_URL": o.get("public-rpc-url", "") if isinstance(o.get("public-rpc-url"), str) else "",
          "PUBLIC_WS_URL": o.get("public-ws-url", "") if isinstance(o.get("public-ws-url"), str) else "",
          "LOG_TARGET": "file", "OWNERSHIP_LAYOUT": "v2", "DOCKER_IMAGE": image,
          "DOCKER_IMAGE_DIGEST": image.split("@", 1)[1], "STATE_EXPORT": "off"}
    if isinstance(adm, str):
        kv["ADMISSION_MODE"] = adm.lower()
        kv["BOOTSTRAP_PEERS_FILE"] = "/etc/telcoin/bootstrap-peers.yaml" if "bootstrap-peers" in installed else ""
        kv["TRUSTED_NODES_FILE"] = "/etc/telcoin/trusted-nodes.yaml" if "trusted-nodes" in installed else ""
    meta_set(root, kv)
    with Locked():  # json mode: start, then enable, unconditionally (SN:2857-2895)
        units = jload(units_path(), {})
        units["telcoin"] = {"active": True, "enabled": True}
        jsave(units_path(), units)
    node_runtime(inst, root, True)
    emit(event="step", name="public rpc")
    emit(event="done", ok=True, phase="finalize", node_type="observer", msg="finalized and started")


IAP_RANGE = "35.235.240.0/20"
SRC_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+(/\d+)?$")
FW_PORTS = ("49590/udp", "49594/udp", "43174/tcp")


def gw_meta(root):
    p = os.path.join(root, "etc/telcoin/gateway/gateway.meta")
    kv = {}
    if os.path.exists(p):
        for l in open(p):
            if "=" in l:
                k, v = l.rstrip("\n").split("=", 1)
                kv[k] = v
    return kv


def node_installed(root):
    return os.path.exists(os.path.join(root, "etc/systemd/system/telcoin.service"))


def ufw_state(inst):
    return jload(sp("hosts", inst, "ufw.json"), {"active": False, "rules": []})


def fw_rules(root, meta):
    """The rule set of fw_apply_rules (fact sheet tnd-firewall.md 2, contract 5), as 'port/proto from src'."""
    net = meta.get("NETWORK") or gw_meta(root).get("NETWORK", "")
    r = []
    ssh = [x for x in meta.get("SSH_ALLOW_FROM", "").split(",") if x]
    r += (["22/tcp from %s" % x for x in [IAP_RANGE] + ssh] if ssh else ["22/tcp from any"])
    if net in ("testnet", "devnet") and node_installed(root):
        r.append("43174/tcp from kuma-src")
    if node_installed(root):
        p2p = [x for x in meta.get("P2P_ALLOW_FROM", "").split(",") if x]
        for port in ("49590/udp", "49594/udp"):
            r += (["%s from %s" % (port, x) for x in p2p] if p2p and meta.get("P2P_COMMITTEE") != "on"
                  else ["%s from any" % port])
        for x in [x for x in meta.get("GATEWAY_ALLOW_FROM", "").split(",") if x]:
            r += ["%s/tcp from %s" % (meta.get("RPC_PORT") or "8545", x), "43174/tcp from %s" % x]
    cf = os.path.join(root, "etc/caddy/Caddyfile")
    if os.path.exists(cf):
        t = open(cf).read()
        if "Managed by the Telcoin Node Manager" in t.splitlines()[0] or re.search(r"^# >>> tn-(rpc|dashboard|gateway) >>>", t, re.M):
            r += ["80/tcp from any", "443/tcp from any"]
    return r


def tnd_firewall(argv):
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    if os.environ.get("L2_SHIM_SUDO") != "1":
        emit(event="done", ok=False, msg="firewall-setup.sh must run as root")
        sys.exit(1)
    if "--json" not in argv:
        strict_fail("UNRECOGNISED", inst, cmd, "firewall-setup.sh without --json is interactive")
    o = opts_of(argv)
    for a, b in (("ssh-from", "ssh-anywhere"), ("p2p-from", "p2p-anywhere")):
        if a in o and b in o:
            emit(event="done", ok=False, msg="--ssh-from/--p2p-from and --ssh-anywhere/--p2p-anywhere cannot be combined.")
            sys.exit(1)
    action = "enable" if ("enable" in o or "reset" in o) else ("status" if "status" in o else ("port" if "port" in o else ""))
    if any(k in o for k in ("ssh-from", "p2p-from", "gateway-from", "ssh-anywhere", "p2p-anywhere")) and action != "enable":
        emit(event="done", ok=False, msg="source flags go with --enable or --reset")
        sys.exit(1)
    meta = meta_get(root)
    with Locked():
        st = ufw_state(inst)
    if action == "status":
        emit(event="done", ok=True, action="status", active=st["active"], network=meta.get("NETWORK") or None,
             rules=st["rules"], gateway_from=[x for x in meta.get("GATEWAY_ALLOW_FROM", "").split(",") if x])
        sys.exit(0)
    if action == "port":
        i = argv.index("--port")
        spec, onoff = argv[i + 1], (argv[i + 2] if i + 2 < len(argv) else "")
        if spec not in FW_PORTS or onoff not in ("on", "off"):
            emit(event="done", ok=False, msg="--port takes one of %s and on|off" % " ".join(FW_PORTS))
            sys.exit(1)
        rule = "%s from any" % spec
        st["rules"] = [r for r in st["rules"] if r != rule] + ([rule] if onoff == "on" else [])
        jsave(sp("hosts", inst, "ufw.json"), st)
        emit(event="done", ok=True, action="port", port=spec, state=onoff, msg="port %s %s" % (spec, onoff))
        sys.exit(0)
    if action != "enable":
        emit(event="done", ok=False, msg="unknown or missing --json action")
        sys.exit(1)
    if "gateway-from" in o:
        v = o["gateway-from"]
        if not node_installed(root):
            emit(event="done", ok=False, action="enable", msg="--gateway-from needs an installed node")
            sys.exit(1)
        if v != "none" and not all(SRC_RE.match(x) for x in str(v).split(",")):
            emit(event="done", ok=False, action="enable", msg="--gateway-from: not an IPv4 or CIDR list: %s" % v)
            sys.exit(1)
    upd = {}
    for k, key in (("ssh-from", "SSH_ALLOW_FROM"), ("p2p-from", "P2P_ALLOW_FROM"), ("gateway-from", "GATEWAY_ALLOW_FROM")):
        if k in o:
            upd[key] = "" if o[k] == "none" else o[k]
    for k, key in (("ssh-anywhere", "SSH_ALLOW_FROM"), ("p2p-anywhere", "P2P_ALLOW_FROM")):
        if k in o:
            upd[key] = ""
    if upd and os.path.exists(os.path.join(root, "etc/telcoin/.node-meta")):
        meta_set(root, upd)
        meta = meta_get(root)
    rules = fw_rules(root, meta)
    with Locked():
        jsave(sp("hosts", inst, "ufw.json"), {"active": True, "rules": rules})
        units = jload(units_path(), {})
        units.setdefault("ufw", {"active": False, "enabled": True})["active"] = True
        jsave(units_path(), units)
    emit(event="step", name="apply_recommended_firewall")
    emit(event="done", ok=True, action="enable", ssh_port="22", active=True,
         msg="ufw enabled with recommended lockout-safe defaults (SSH + overlay + kuma)")


def obs_restarts(inst):
    """Which hosts' installer restarts the node: odd host numbers do, even ones refuse ("Not restarting"), so a
    rehearsal runs both of the driver's paths (stop again / nothing to stop)."""
    m = re.search(r"-(\d+)-", inst)
    return bool(m and int(m.group(1)) % 2 == 1)


def tnd_observability(argv):
    """setup-observability.sh --json (fact sheet tnd-node.md 6): launch flags into the start script, the Alloy
    agent (config + unit, active), .node-meta keys; the node restart only on some hosts (see obs_restarts)."""
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    o = opts_of(argv)
    if os.environ.get("L2_SHIM_SUDO") != "1":
        emit(event="done", ok=False, msg="setup-observability.sh must run as root")
        sys.exit(1)
    if "json" not in o:
        strict_fail("UNRECOGNISED", inst, cmd, "setup-observability.sh without --json is interactive")
    if not node_installed(root):
        emit(event="done", ok=False, msg="No node is installed on this host.")
        sys.exit(1)
    alloy = "enable-logs" in o or "enable-metrics" in o
    if alloy:
        if "token-stdin" not in o or not sys.stdin.readline().strip():
            emit(event="done", ok=False, msg="--enable-logs/--enable-metrics need the ingest token (--token-stdin)")
            sys.exit(1)
        for k in ("push-url", "metrics-push-url", "region"):
            if not isinstance(o.get(k), str):
                emit(event="done", ok=False, msg="missing --%s" % k)
                sys.exit(1)
    start = os.path.join(root, "usr/local/libexec/telcoin/tn-start-docker")
    with open(start) as f:
        lines = f.read().split("\n")
    k = [i for i, l in enumerate(lines) if l.startswith("exec ") and " node " in l][-1]
    add = []
    if "enable-logs" in o and "--log.file.format" not in lines[k]:
        add.append("--log.file.format json --log.file.directory /home/nonroot/logs --log.file.max-size 100 --log.file.max-files 5")  # lib/observability.sh:146
    if "enable-metrics" in o and " --metrics " not in lines[k]:
        add.append("--metrics 127.0.0.1:9101")
    warn_hc = False
    if "enable-health" in o:
        if not ufw_state(inst)["active"]:
            emit(event="done", ok=False, msg="--enable-health needs ufw active (the health port binds on every interface)")
            sys.exit(1)
        if "--healthcheck" not in lines[k]:
            add.append("--healthcheck 43174")
            warn_hc = True
        with Locked():
            st = ufw_state(inst)
            if "43174/tcp from kuma-src" not in st["rules"]:
                st["rules"].append("43174/tcp from kuma-src")
            jsave(sp("hosts", inst, "ufw.json"), st)
    if add:
        lines[k] += " " + " ".join(add)
        with open(start, "w") as f:
            f.write("\n".join(lines))
        emit(event="step", name="launch flags", msg="added " + " ".join(add))
    if warn_hc:
        emit(event="warn", msg="Added --healthcheck 43174 to the launch file")
    if alloy:
        os.makedirs(os.path.join(root, "etc/telcoin/alloy"), exist_ok=True)
        with open(os.path.join(root, "etc/telcoin/alloy/config.alloy"), "w") as f:
            f.write("// l2-shim fake alloy config: push %s, metrics %s\n" % (o["push-url"], o["metrics-push-url"]))
        with open(os.path.join(root, "etc/systemd/system/telcoin-alloy.service"), "w") as f:
            f.write("[Service]\nExecStart=/usr/local/bin/alloy run /etc/telcoin/alloy/config.alloy\n")
        with Locked():
            units = jload(units_path(), {})
            units["telcoin-alloy"] = {"active": True, "enabled": True}
            jsave(units_path(), units)
        emit(event="step", name="alloy")
    meta_set(root, {"ENABLE_OBSERVABILITY": "true" if alloy else "false",
                    "ENABLE_METRICS": "true" if "enable-metrics" in o else "false", "METRICS_PORT": "9101",
                    "REGION": o.get("region", "") if isinstance(o.get("region"), str) else ""})
    if add:
        if obs_restarts(inst):
            with Locked():
                units = jload(units_path(), {})
                units["telcoin"]["active"] = True
                jsave(units_path(), units)
            node_runtime(inst, root, True)
            emit(event="step", name="restart", msg="Restarted telcoin to apply the new flags")
        else:
            emit(event="warn", msg="Not restarting: the committee could lose its quorum (see above). Restart later, or set TN_ALLOW_QUORUM_RISK=1 for a coordinated restart.")  # lib/observability.sh:1148
    emit(event="done", ok=True, msg="observability enabled")


PRIV_RE = re.compile(r"^(10\.\d+|172\.(1[6-9]|2\d|3[01])|192\.168)\.\d+\.\d+$")


def upstream_up(host_ip):
    """True when the node behind a gateway answers: its telcoin unit is active (same-host: this host)."""
    if host_ip in ("127.0.0.1", None):
        return jload(units_path(), {}).get("telcoin", {}).get("active", False)
    for name, rec in cloud()["instances"].items():
        if rec.get("int_ip") == host_ip:
            return jload(sp("hosts", name, "units.json"), {}).get("telcoin", {}).get("active", False)
    return False


def gw_probe(inst, root, path):
    if not jload(units_path(), {}).get("telcoin-gateway", {}).get("active"):
        return 0, ""
    if path == "/health":
        return 200, "ok"
    up = upstream_up(gw_meta(root).get("UPSTREAM_HOST"))
    return (200, "ready") if up else (503, "not ready: upstream node not answering")


def gw_fields(inst, root):
    m = gw_meta(root)
    units = jload(units_path(), {}).get("telcoin-gateway", {})
    inst_ = bool(m)
    h = m.get("UPSTREAM_HOST")
    ready = inst_ and units.get("active", False) and upstream_up(h)
    return {"installed": inst_, "enabled": bool(units.get("enabled")), "active": bool(units.get("active")),
            "network": m.get("NETWORK") or None, "mode": m.get("MODE") or None, "front": m.get("FRONT") or None,
            "domain": m.get("DOMAIN") or None, "image": m.get("IMAGE") or None, "image_held": inst_,
            "listen": "127.0.0.1:8655" if inst_ else None, "probe": "127.0.0.1:8656" if inst_ else None,
            "metrics": "127.0.0.1:9655" if inst_ else None,
            "upstream_rpc": ("http://%s:8545" % h) if inst_ else None,
            "upstream_readiness": ("http://%s:43174/health/workers" % h) if inst_ else None,
            "redirect_queries": m.get("REDIRECT") or None, "health": bool(units.get("active")), "ready": bool(ready),
            "ready_any": bool(ready), "caddy_block": (m.get("FRONT") == "caddy") if inst_ else None, "issues": 0}


def tnd_gateway(argv):
    """setup-gateway.sh (contract 3): --enable writes /etc/telcoin/gateway/gateway.meta, the telcoin-gateway unit
    (enabled, active), the Caddy block (front caddy: install-caddy.sh gateway-enable, which opens 80/443); does
    not wait for readiness. --status reports. The done line carries every field of 3.2."""
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    o = opts_of(argv)
    def fail(msg):
        emit(event="done", ok=False, msg=msg + " Nothing was changed.")
        sys.exit(1)
    if "status" in o:
        f = gw_fields(inst, root)
        emit(event="done", ok=True, **dict(f, msg="status"))
        sys.exit(0)
    if "enable" not in o:
        strict_fail("UNRECOGNISED", inst, cmd, "setup-gateway.sh action not emulated")
    if os.environ.get("L2_SHIM_SUDO") != "1":
        fail("setup-gateway.sh --enable must run as root.")
    if "json" not in o and "yes" not in o:
        strict_fail("UNRECOGNISED", inst, cmd, "setup-gateway.sh --enable without --json/--yes asks")
    mode, front = o.get("mode"), o.get("front", "caddy")
    node = node_installed(root)
    net = o.get("network") if isinstance(o.get("network"), str) else meta_get(root).get("NETWORK")
    if not net:
        fail("--network is required on a host with no node.")
    if mode == "same-host":
        if not node:
            fail("--mode same-host needs a node on this host.")
        start = open(os.path.join(root, "usr/local/libexec/telcoin/tn-start-docker")).read()
        if "--healthcheck" not in start:
            fail("--mode same-host needs --healthcheck in the node's launch file (setup-observability.sh --enable-health).")
        if net == "mainnet":
            fail("on mainnet the gateway runs on its own host")
        uh = "127.0.0.1"
    elif mode == "standalone":
        if node:
            fail("--mode standalone on a host that runs a node.")
        if not isinstance(o.get("upstream"), str) or not PRIV_RE.match(o["upstream"]):
            fail("--mode standalone needs --upstream <private-ipv4>.")
        uh = o["upstream"]
    else:
        fail("--mode must be same-host or standalone.")
    if front == "caddy" and not isinstance(o.get("domain"), str):
        fail("--front caddy needs --domain.")
    if not re.match(r"^[^@\s]+@sha256:[0-9a-f]{64}$", str(o.get("image", ""))):
        fail("--image must be <repo>@sha256:<digest>.")
    if not re.match(r"^https?://\S+$", str(o.get("redirect-queries", ""))):
        fail("--redirect-queries must be a URL.")
    want = {"NETWORK": net, "MODE": mode, "FRONT": front, "DOMAIN": o.get("domain", ""), "IMAGE": o["image"],
            "UPSTREAM_HOST": uh, "REDIRECT": o["redirect-queries"]}
    applied = []
    gdir = os.path.join(root, "etc/telcoin/gateway")
    units = jload(units_path(), {})
    if gw_meta(root) != want or not units.get("telcoin-gateway", {}).get("active"):
        os.makedirs(gdir, exist_ok=True)
        with open(os.path.join(gdir, "gateway.meta"), "w") as f:
            f.write("".join("%s=%s\n" % kv for kv in want.items()))
        with open(os.path.join(root, "etc/systemd/system/telcoin-gateway.service"), "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/docker run --rm --name telcoin-gateway --network=host --pull=never %s\n"
                    % o["image"])
        with Locked():
            units = jload(units_path(), {})
            units["telcoin-gateway"] = {"active": True, "enabled": True}
            jsave(units_path(), units)
        applied.append("gateway:enabled")
    if front == "caddy":
        cf = os.path.join(root, "etc/caddy/Caddyfile")
        block = "# >>> tn-gateway >>>\n# tn-gateway block v1\n%s {\n  reverse_proxy 127.0.0.1:8655\n}\n# <<< tn-gateway <<<\n" % o["domain"]
        cur = open(cf).read() if os.path.exists(cf) else "# Managed by the Telcoin Node Manager\n"
        if block not in cur:
            os.makedirs(os.path.dirname(cf), exist_ok=True)
            cur = re.sub(r"# >>> tn-gateway >>>.*?# <<< tn-gateway <<<\n", "", cur, flags=re.S) + block
            with open(cf, "w") as f:
                f.write(cur)
            applied.append("gateway:caddy")
        with Locked():
            units = jload(units_path(), {})
            units["caddy"] = {"active": True, "enabled": True}
            jsave(units_path(), units)
            st = ufw_state(inst)
            if st["active"]:
                st["rules"] += [r for r in ("80/tcp from any", "443/tcp from any") if r not in st["rules"]]
                jsave(sp("hosts", inst, "ufw.json"), st)
    f = gw_fields(inst, root)
    emit(event="done", ok=True, applied=applied, **dict(f, msg="gateway enabled" if applied else "nothing had to change"))


def tnd_edit_config(argv):
    """edit-config.sh --json --set gateway_upstream=<list>|off (contract 5, C3). Only this key is emulated."""
    inst, root = host()
    cmd = os.environ.get("L2_SHIM_CMD", "")
    o = opts_of(argv)
    if os.environ.get("L2_SHIM_SUDO") != "1" or "json" not in o or not isinstance(o.get("set"), str):
        strict_fail("UNRECOGNISED", inst, cmd, "edit-config.sh emulated only as root with --json --set")
    field, _, value = o["set"].partition("=")
    if field != "gateway_upstream":
        strict_fail("UNRECOGNISED", inst, cmd, "edit-config.sh --set %s not emulated" % field)
    def done(ok, msg):
        emit(event="done", ok=ok, rolled_back=False, field=field, value=value, msg=msg)
        sys.exit(0 if ok else 1)
    if not node_installed(root):
        done(False, "No node is installed on this host; nothing was changed")
    meta = meta_get(root)
    start = os.path.join(root, "usr/local/libexec/telcoin/tn-start-docker")
    body = open(start).read()
    if value == "off":
        prev = meta.get("GATEWAY_PREV_HEALTHCHECK", "")
        body = body.replace("--http.addr 0.0.0.0", "--http.addr 127.0.0.1")
        body = re.sub(r" --healthcheck 0\.0\.0\.0:\d+", "" if prev == "none" else " --healthcheck %s" % prev, body)
        meta_set(root, {"GATEWAY_UPSTREAM": "", "GATEWAY_PREV_HEALTHCHECK": ""})
    else:
        ips = value.split(",")
        rules = set(ufw_state(inst)["rules"])
        port = meta.get("RPC_PORT") or "8545"
        if not all(SRC_RE.match(x) and "%s/tcp from %s" % (port, x) in rules and "43174/tcp from %s" % x in rules
                   for x in ips):
            done(False, "the firewall does not let %s reach the RPC and health ports: run firewall-setup.sh --enable "
                        "--gateway-from %s first; nothing was changed" % (value, value))
        m = re.search(r" --healthcheck (\S+)", body)
        body = body.replace("--http.addr 127.0.0.1", "--http.addr 0.0.0.0")
        body = re.sub(r" --healthcheck \S+", " --healthcheck 0.0.0.0:43174", body) if m else \
            body.rstrip("\n") + " --healthcheck 0.0.0.0:43174\n"
        kv = {"GATEWAY_UPSTREAM": value}
        if "GATEWAY_PREV_HEALTHCHECK" not in meta:
            kv["GATEWAY_PREV_HEALTHCHECK"] = m.group(1) if m else "none"
        meta_set(root, kv)
    with open(start, "w") as f:
        f.write(body)
    units = jload(units_path(), {})
    if not units.get("telcoin", {}).get("active"):
        done(True, "gateway_upstream=%s applied; telcoin was not running and stays stopped" % value)
    node_runtime(inst, root, True)
    done(True, "gateway_upstream=%s applied and telcoin healthy" % value)


TND = {"setup-node.sh": tnd_setup_node, "firewall-setup.sh": tnd_firewall, "setup-observability.sh": tnd_observability,
       "setup-gateway.sh": tnd_gateway, "edit-config.sh": tnd_edit_config}


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
    for name in sorted(os.listdir(tnd_dir)) + ["ui/install-ui.sh"]:
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
        if tool == "pas":
            return r_pas(argv)
        if tool == "stat":
            return r_stat(argv)
        if tool == "curl":
            return r_curl(argv)
        if tool == "docker":
            return r_docker(argv)
        if tool == "journalctl":
            return r_journalctl(argv)
        if tool == "pgrep":
            return r_pgrep(argv)
        if tool == "ss":
            return r_ss(argv)
        return r_simple(tool, argv)
    table = {"dig": local_dig, "cast": local_cast, "docker": local_docker, "init": init, "gen-flags": gen_flags, "pty-run": pty_run,
             "report": report, "sentinel": sentinel,
             "curl": local_curl, "stub-driver": stub_driver}
    if tool in table:
        return table[tool](argv)
    return local_strict(tool, argv)


# ----------------------------------------------------------------------------- SH3: deploy steps 15..20
# Step 15 install-caddy.sh rpc-enable/rpc-status; 16 the post-check's node, gateway and https answers; 17
# ui/install-ui.sh and install-caddy.sh enable/gateway-status; 18/19 a stub at the driver boundary (run.sh);
# 20 firewall-setup.sh --p2p-committee and tn-p2p-allow-sync. Answer shapes: install-caddy.sh 2587/2971/3143
# and its json_done lines, tnd-firewall.md 5-6, PAS docs/contract.md 516-543; the chain advances with time.
CURL_VALUE_OPTS |= {"--data", "-d", "--data-raw", "--proto"}
CURL_BOOL_OPTS |= {"--retry-connrefused", "--http1.1"}
CURL_CTX = {}
FENCES = {"gateway": ("# >>> tn-gateway >>>", "# <<< tn-gateway <<<"), "rpc": ("# >>> tn-rpc >>>", "# <<< tn-rpc <<<"),
          "dashboard": ("# >>> tn-dashboard >>>", "# <<< tn-dashboard <<<")}
PAS_DIR = "var/lib/telcoin-p2p-allow"
PAS_BIN = "usr/local/libexec/telcoin/tn-p2p-allow-sync"


def vm_by_ip(ip):
    for name, rec in cloud()["instances"].items():
        if ip in (rec.get("int_ip"), rec.get("ext_ip")):
            return name
    return None


def vm_root(name):
    return sp("hosts", name, "root")


def vm_units(name):
    return jload(sp("hosts", name, "units.json"), {})


def node_binds(root):
    """The node's sockets from its launch line (contract: a bare --healthcheck <port> binds 127.0.0.1)."""
    p = os.path.join(root, "usr/local/libexec/telcoin/tn-start-docker")
    ls = [l for l in open(p).read().split("\n") if l.startswith("exec ") and " node " in l] if os.path.exists(p) else []
    line, out = (ls[-1] if ls else ""), []

    def val(flag, default):
        m = re.search(r"\s%s[ =](\S+)" % re.escape(flag), line)
        return m.group(1) if m else default
    if re.search(r"\s--http(\s|$)", line):
        out.append("%s:8545" % val("--http.addr", "127.0.0.1"))
    if re.search(r"\s--ws(\s|$)", line):
        out.append("%s:8546" % val("--ws.addr", "127.0.0.1"))
    hc = val("--healthcheck", None)
    if hc:
        out.append(hc if ":" in hc else "127.0.0.1:" + hc)
    return out


_listen_extra_sh2 = LISTEN_EXTRA


def LISTEN_EXTRA(inst, root, units):  # noqa: F811 (extends the step-13 version)
    out = _listen_extra_sh2(inst, root, units)
    if units.get("telcoin-ui", {}).get("active"):
        out.append("127.0.0.1:8080")
    return out


def chain_now():
    """(execution head, consensus header number): both rise with wall time from the first read."""
    with Locked():
        c = jload(sp("chain.json"), {})
        if "t0" not in c:
            c["t0"] = time.time()
            jsave(sp("chain.json"), c)
    dt = max(0.0, time.time() - c["t0"])
    return 1 + int(dt), 1 + int(2 * dt)


def chain_id():
    for f in ("config.sh", "devnet-lib.sh"):
        p = sp("repo", f)
        if os.path.exists(p):
            m = re.search(r'CHAIN_ID\}?[:=-]+"?(\d{3,})', open(p).read())
            if m:
                return int(m.group(1))
    return 2017


def node_b58(root):
    for base in ("home", "opt", "var/lib", "etc/telcoin"):
        for d, _, fs in os.walk(os.path.join(root, base)):
            if "node-info.yaml" in fs:
                for l in open(os.path.join(d, "node-info.yaml")):
                    m = re.match(r"^\s*bls_public_key:\s*['\"]?([1-9A-HJ-NP-Za-km-z]+)", l)
                    if m:
                        return m.group(1)
    return None


def b58hex(s):
    a, n = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", 0
    for ch in s:
        n = n * 58 + a.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return (b"\0" * (len(s) - len(s.lstrip("1"))) + body).hex()


def rpc_vm():
    return next((n for n in sorted(cloud()["instances"]) if n.startswith("rpc-")), None)


def node_mode(name):
    return "CvvActive" if name.startswith("validator-") else "Observer"


def node_rpc_answer(name, data):
    try:
        req = json.loads(data or "")
    except ValueError:
        return 400, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    meth, head_cons = req.get("method"), chain_now()
    res = KeyError
    if meth == "eth_chainId":
        res = "0x%x" % chain_id()
    elif meth == "eth_blockNumber":
        res = "0x%x" % head_cons[0]
    elif meth == "tn_latestConsensusHeader":
        res = {"number": head_cons[1], "epoch": 0, "round": 2 * head_cons[1]}
    elif meth == "tn_nodeMode":
        res = node_mode(name)
    elif meth == "tn_info":
        res = {"bls_public_key": node_b58(vm_root(name)), "node_mode": node_mode(name)}
    elif meth == "tn_admissionSnapshot":
        rv, entries = rpc_vm(), []
        for other in sorted(cloud()["instances"]):
            k = node_b58(vm_root(other)) if other != name else None
            if k:
                slots = ["trusted"] if other == rv else (["committee"] if other.startswith("validator-") else ["pool"])
                entries.append({"bls_pubkey": "0x" + b58hex(k), "slots": slots, "admitted": True})
        res = {"version": 1, "epoch": 0, "swarms": [{"network": "primary", "available": True, "tracked_epoch": 0,
               "admission": {"effective": "Open" if name == rv else "Closed", "fallback": None, "epoch": 0,
                             "connected_current": len(entries)}, "entries": entries}]}
    body = {"jsonrpc": "2.0", "id": req.get("id"), "result": res} if res is not KeyError else \
        {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "the method %s does not exist" % meth}}
    return 200, json.dumps(body, separators=(",", ":"))


_curl_answer_sh2 = curl_answer


def curl_answer(inst, root, url, headers):  # noqa: F811 (adds the node's RPC, gateway metrics, the UI)
    m = re.match(r"^http://(127\.0\.0\.1|localhost|\d+\.\d+\.\d+\.\d+):(8545|8546|9655|8080)(/[^?#]*)?$", url)
    if not m:
        return _curl_answer_sh2(inst, root, url, headers)
    ip, port = m.group(1), int(m.group(2))
    local = ip in ("127.0.0.1", "localhost")
    target = inst if local else vm_by_ip(ip)
    if target is None:
        return -28, ""
    troot, units = vm_root(target), vm_units(target)
    socks = (node_binds(troot) if units.get("telcoin", {}).get("active") else []) + LISTEN_EXTRA(target, troot, units)
    addrs = [s.rsplit(":", 1)[0] for s in socks if s.endswith(":%d" % port)]
    if not [a for a in addrs if a == "0.0.0.0" or a == ("127.0.0.1" if local else ip)]:
        return 0, ""  # nothing bound there: refused
    if not local and target != inst and ufw_state(target).get("active"):
        src = cloud()["instances"][inst]["int_ip"]
        if port != 8545 or src not in [x for x in meta_get(troot).get("GATEWAY_ALLOW_FROM", "").split(",") if x]:
            return -28, ""  # ufw drops it: the client times out
    if port == 8545:
        return node_rpc_answer(target, CURL_CTX.get("data"))
    if port == 9655:
        up = upstream_up(gw_meta(troot).get("UPSTREAM_HOST"))
        return 200, "# TYPE tn_worker_gateway_upstream_ready gauge\ntn_worker_gateway_upstream_ready %d\n" % (1 if up else 0)
    if port == 8080:
        return 200, "<html><title>Telcoin Node Manager</title></html>"
    return 400, "WebSocket only"


# --- install-caddy.sh
def caddy_blocks(root):
    p = os.path.join(root, "etc/caddy/Caddyfile")
    cur, out = (open(p).read() if os.path.exists(p) else ""), {}
    for k, (b, e) in FENCES.items():
        m = re.search(re.escape(b) + r"\n(.*?)" + re.escape(e), cur, re.S)
        if m:
            d = re.search(r"^([A-Za-z0-9][^\s{]*)\s*\{\s*$", m.group(1), re.M)
            pm = re.search(r"reverse_proxy 127\.0\.0\.1:(\d+)", m.group(1))
            out[k] = {"domain": d.group(1) if d else "", "port": int(pm.group(1)) if pm else None}
    return cur, out


def caddy_put(root, kind, body):
    cur, _ = caddy_blocks(root)
    b, e = FENCES[kind]
    cur = re.sub(re.escape(b) + r".*?" + re.escape(e) + r"\n?", "", cur, flags=re.S) or "# Managed by the Telcoin Node Manager\n"
    p = os.path.join(root, "etc/caddy/Caddyfile")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(cur + "%s\n%s%s\n" % (b, body, e))
    with Locked():
        units = jload(units_path(), {})
        units.setdefault("caddy", {"active": False, "enabled": False}).update(active=True, enabled=True)
        jsave(units_path(), units)


def cdone(ok, msg, **kw):
    emit(event="done", ok=ok, **dict(kw, msg=msg))
    sys.exit(0 if ok else 1)


def tnd_caddy(argv):
    inst, root = host()
    cmd, o = os.environ.get("L2_SHIM_CMD", ""), opts_of(argv)
    phase, units = o.get("phase"), jload(units_path(), {})
    _, blocks = caddy_blocks(root)
    caddy_on = units.get("caddy", {}).get("active", False)
    advp = os.path.join(root, "etc/telcoin/.shim-rpc-advertised")
    adv = (open(advp).read().strip() if os.path.exists(advp) else "|").split("|")
    node_up = units.get("telcoin", {}).get("active", False)
    ws_listen = node_up and any(s.endswith(":8546") for s in node_binds(root))
    if phase == "rpc-status":
        r = blocks.get("rpc", {})
        print(json.dumps({"installed": "caddy" in units, "running": caddy_on, "enabled": "rpc" in blocks,
                          "domain": r.get("domain", ""), "advertised_http": adv[0], "advertised_ws": adv[1],
                          "ws_listening": ws_listen, "block_stale": False}, separators=(",", ":")))
        sys.exit(0)
    if phase == "gateway-status":
        g = blocks.get("gateway", {})
        print(json.dumps({"installed": "caddy" in units, "running": caddy_on, "enabled": "gateway" in blocks,
                          "domain": g.get("domain", ""), "port": g.get("port"), "probe_port": 8656 if g else None,
                          "block_stale": False}, separators=(",", ":")))
        sys.exit(0)
    if phase == "status":
        dsh = blocks.get("dashboard", {})
        print(json.dumps({"installed": "caddy" in units, "running": caddy_on, "enabled": "dashboard" in blocks,
                          "domain": dsh.get("domain", ""), "username": o.get("username", "")}, separators=(",", ":")))
        sys.exit(0)
    if phase == "rpc-enable":
        d = o.get("rpc-domain")
        if not isinstance(d, str) or not node_installed(root):
            cdone(False, "rpc-enable needs --rpc-domain and an installed node")
        if "gateway" in blocks:
            cdone(False, "this host serves the worker gateway; the tn-rpc and tn-gateway sites are never served from one host")
        if blocks.get("dashboard", {}).get("domain") == d:
            cdone(False, "%s already serves the Node Manager dashboard -- the dashboard and the public RPC endpoint need DIFFERENT hostnames." % d)
        for s in ("Checking ports 80 and 443 are free", "Installing Caddy (if needed)",
                  "Configuring the public RPC endpoint for %s" % d, "Opening the firewall (80, 443) and reloading Caddy",
                  "Advertising the endpoint in node-info.yaml"):
            emit(event="step", msg=s)
        caddy_put(root, "rpc", "%s {\n  reverse_proxy 127.0.0.1:8545\n}\n" % d)
        want = "https://%s/|%s" % (d, ("wss://%s/" % d) if ws_listen else "")
        if "|".join(adv) != want:
            with open(advp, "w") as f:
                f.write(want + "\n")
            if not node_up:
                finding("SUSPECT", inst, cmd, "install-caddy.sh rpc-enable restarts a STOPPED node (starts it alone)", fatal=False)
            with Locked():
                units = jload(units_path(), {})
                units["telcoin"]["active"] = True
                jsave(units_path(), units)
            node_runtime(inst, root, True)
            remote_detail("node-restart", ["telcoin", "by install-caddy.sh rpc-enable"])
        cdone(True, "public RPC endpoint enabled -- certificate issues on first request", domain=d)
    if phase == "enable":
        d, user = o.get("domain"), o.get("username")
        pw = sys.stdin.readline().rstrip("\n") if o.get("password-stdin") is True else ""
        if not isinstance(d, str) or not isinstance(user, str) or len(pw) < 16:
            cdone(False, "enable needs --domain, --username and a password of at least 16 characters on stdin")
        if d in (blocks.get("gateway", {}).get("domain"), blocks.get("rpc", {}).get("domain")):
            cdone(False, "%s already serves another site -- each Caddy site needs its own hostname. Nothing was changed." % d)
        caddy_put(root, "dashboard", "%s {\n  basic_auth {\n    %s $2a$14$l2shim.fake.bcrypt.hash\n  }\n"
                  "  header X-TN-Dashboard-Public 1\n  reverse_proxy 127.0.0.1:8080\n}\n" % (d, user))
        cdone(True, "external dashboard access enabled -- certificate will be issued on first request", domain=d)
    strict_fail("UNRECOGNISED", inst, cmd, "install-caddy.sh --phase %s not emulated" % phase)


# --- ui/install-ui.sh (contract: --update keeps enable-on-boot; a first install starts and enables the unit)
def tnd_install_ui(argv):
    inst, root = host()
    uf = os.path.join(root, "etc/systemd/system/telcoin-ui.service")
    first = not os.path.exists(uf)
    if "--update" in argv and first:
        print("telcoin-ui is not installed; run install-ui.sh without --update")
        sys.exit(1)
    os.makedirs(os.path.dirname(uf), exist_ok=True)
    with open(uf, "w") as f:
        f.write("[Service]\nExecStart=/opt/telcoin-ui/venv/bin/gunicorn -b 127.0.0.1:8080 app:app\n"
                "[Install]\nWantedBy=multi-user.target\n")
    with Locked():
        units = jload(units_path(), {})
        u = units.setdefault("telcoin-ui", {"active": False, "enabled": False})
        u["active"] = True
        u["enabled"] = u["enabled"] or first
        jsave(units_path(), units)
    print("telcoin-ui %s: listening on 127.0.0.1:8080" % ("installed" if first else "updated"))
    sys.exit(0)


# --- firewall-setup.sh --p2p-committee (tnd-firewall.md 5) and tn-p2p-allow-sync (6)
def pas_kv(inst, root):
    peers = [n for n in cloud()["instances"] if n != inst and node_b58(vm_root(n))]
    return {"STATUS_VERSION": 1, "TOOL_VERSION": "v0.1.1", "RESULT": "applied", "EPOCH": 0, "EPOCH_DURATION": 86400,
            "ALLOWED_V4": len(peers), "ALLOWED_V6": 0, "KEYS": len(peers), "LOADED": "true", "STALE": "false",
            "COUNTER_ACCEPT_PACKETS": 1000 + chain_now()[1], "COUNTER_DROP_PACKETS": 0}


def tnd_firewall_sh3(argv):
    if "--p2p-committee" not in argv:
        return tnd_firewall(argv)
    inst, root = host()
    cmd, verb = os.environ.get("L2_SHIM_CMD", ""), opts_of(argv).get("p2p-committee")
    if "--json" in argv or verb not in ("on", "off", "sync", "status"):
        strict_fail("UNRECOGNISED", inst, cmd, "firewall-setup.sh --p2p-committee %s not emulated" % verb)
    on = meta_get(root).get("P2P_COMMITTEE") == "on"
    sd = os.path.join(root, PAS_DIR)
    if verb == "status":
        if not on:
            print("[INFO] P2P committee allowlist: off (sudo bash %s/firewall-setup.sh --p2p-committee on turns it on)" % NODE_SCRIPTS)
        else:
            kv = pas_kv(inst, root)
            print("[OK] P2P committee allowlist: on; table inet tn_p2p_allow holds %s IPv4 and 0 IPv6 sources" % kv["ALLOWED_V4"])
            print("[INFO] P2P committee allowlist counters: accepted %s packets, dropped 0" % kv["COUNTER_ACCEPT_PACKETS"])
        sys.exit(0)
    if verb == "off":
        meta_set(root, {"P2P_COMMITTEE": "off"})
        print("[OK] P2P committee allowlist: off")
        sys.exit(0)
    if not node_installed(root):
        print("[ERROR] No node is installed here. Nothing was changed.")
        sys.exit(1)
    if not ufw_state(inst).get("active"):
        print("[ERROR] ufw is not active; turn the firewall on first (sudo bash %s/firewall-setup.sh --enable). Nothing was changed." % NODE_SCRIPTS)
        sys.exit(1)
    if not jload(units_path(), {}).get("telcoin", {}).get("active"):
        print("[ERROR] the node's admission snapshot is not authoritative (reason=rpc-unreachable). Nothing was changed.")
        sys.exit(1)
    if verb == "sync" and not on:
        print("P2P committee mode is off; turn it on with: sudo bash %s/firewall-setup.sh --p2p-committee on" % NODE_SCRIPTS)
        sys.exit(1)
    os.makedirs(sd, exist_ok=True)
    b = os.path.join(root, PAS_BIN)
    os.makedirs(os.path.dirname(b), exist_ok=True)
    with open(b, "w") as f:
        f.write('#!/usr/bin/env bash\n# l2-shim fake of tn-p2p-allow-sync v0.1.1\nexec "${L2_SHIM_PY}" "${L2_SHIM_DIR}/fakes.py" pas "$@"\n')
    os.chmod(b, 0o755)
    with open(os.path.join(sd, "config"), "w") as f:
        f.write("# tn-p2p-allow-sync config, written by firewall-setup.sh\nCONFIG_VERSION=1\nRPC_PORT=8545\nP2P_PORTS=49590,49595\nP2P_ALLOW_FROM=\n")
    kv = pas_kv(inst, root)
    with open(os.path.join(sd, "status"), "w") as f:
        f.write("".join("%s=%s\n" % x for x in kv.items()))
    with Locked():
        units = jload(units_path(), {})
        for u in ("telcoin-p2p-allow", "telcoin-p2p-allow-sync.timer"):
            units[u] = {"active": True, "enabled": True}
        jsave(units_path(), units)
    meta_set(root, {"P2P_COMMITTEE": "on"})
    print("result=applied reason= epoch=0 v4=%s v6=0 static=1 floor=1 keys=%s dns_skipped=0 unparsed=0" % (kv["ALLOWED_V4"], kv["KEYS"]))
    print("[OK] P2P committee allowlist: on")
    sys.exit(0)


def r_pas(argv):
    remote_detail("tn-p2p-allow-sync", argv)
    inst, root = host()
    verb = [a for a in argv if not a.startswith("-")][:1]
    if not os.path.exists(os.path.join(root, PAS_DIR, "config")):
        print("result=error reason=no-config")
        sys.exit(2)
    up = jload(units_path(), {}).get("telcoin", {}).get("active", False)
    if verb == ["check"]:
        print("result=ok missing_total=0 mismatch_total=0" if up else "result=stale reason=rpc-unreachable missing_total=0 mismatch_total=0")
        sys.exit(0 if up else 3)
    if verb == ["status"]:
        print("".join("%s=%s\n" % x for x in pas_kv(inst, root).items()), end="")
        sys.exit(0)
    strict_fail("UNRECOGNISED", inst, os.environ.get("L2_SHIM_CMD", ""), "tn-p2p-allow-sync %s not emulated" % " ".join(argv))


_r_simple_sh2 = r_simple


def r_simple(tool, argv):  # noqa: F811 (adds plain `ufw status`, which the committee probe reads)
    if tool == "ufw" and argv in (["status"], ["status", "verbose"]):
        remote_detail("ufw", argv)
        st = ufw_state(host()[0])
        print("Status: %s" % ("active" if st.get("active") else "inactive"))
        if st.get("active"):
            print("\nTo                         Action      From\n--                         ------      ----")
            for r in st.get("rules", []):
                print(r if isinstance(r, str) else " ".join(str(x) for x in (r.values() if isinstance(r, dict) else r)))
        sys.exit(0)
    return _r_simple_sh2(tool, argv)


TND["install-caddy.sh"] = tnd_caddy
TND["ui/install-ui.sh"] = tnd_install_ui
TND["firewall-setup.sh"] = tnd_firewall_sh3


# --- operator side: curl over https (post-check, dashboards) and the step-18/19 stub
def local_curl(argv):
    cmd = "curl " + " ".join(shlex.quote(a) for a in argv)
    log_call("curl", None, cmd)
    vals, urls, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in CURL_VALUE_OPTS:
            vals.setdefault(a, []).append(argv[i + 1])
            i += 1
        elif a.startswith("-") and not (a in CURL_BOOL_OPTS or re.match(r"^-[sSfLk]+$", a)):
            strict_fail("UNRECOGNISED", None, cmd, "operator-side curl option %s not emulated" % a)
        elif not a.startswith("-"):
            urls.append(a)
        i += 1
    m = re.match(r"^https://([a-z0-9.-]+)(/[^?#]*)?$", urls[0]) if len(urls) == 1 else None
    if not m:
        strict_fail("UNRECOGNISED", None, cmd, "operator-side curl to %s not emulated" % urls)
    dom, path = m.group(1), m.group(2) or "/"
    headers = vals.get("-H", []) + vals.get("--header", [])
    data = (vals.get("--data") or vals.get("-d") or [""])[-1]
    wout = (vals.get("-w") or vals.get("--write-out") or [""])[-1]
    owner = kind = None
    for name in sorted(cloud()["instances"]):
        for k, b in caddy_blocks(vm_root(name))[1].items():
            if b["domain"] == dom:
                owner, kind = name, k
    rc, code, body = 0, 0, ""
    if owner is None:
        rc = 6
    elif not vm_units(owner).get("caddy", {}).get("active"):
        rc = 7
    elif kind == "dashboard":
        code, body = 401, "Unauthorized"
    else:
        ws = any(h.lower().replace(" ", "") == "upgrade:websocket" for h in headers)
        up_ip = gw_meta(vm_root(owner)).get("UPSTREAM_HOST") if kind == "gateway" else "127.0.0.1"
        node = owner if up_ip in (None, "127.0.0.1") else vm_by_ip(up_ip)
        up = bool(node) and vm_units(node).get("telcoin", {}).get("active", False)
        meth = (json.loads(data).get("method") if data.startswith("{") else None)
        if ws:
            code = 101 if (kind == "rpc" and up) else (405 if kind == "gateway" else 502)
        elif not up:
            code, body = 502, "Bad Gateway"
        elif data:
            who = rpc_vm() if (kind == "gateway" and meth in ("tn_nodeMode", "tn_info")) else node
            code, body = node_rpc_answer(who, data)
        elif kind == "gateway" and path in ("/health", "/ready/any"):
            code, body = 200, "ok"
        else:
            code, body = 405, "Method Not Allowed"
    dest = (vals.get("-o") or vals.get("--output") or [None])[-1]
    if dest and dest != "/dev/null":
        with open(dest, "w") as f:
            f.write(body)
    elif not dest:
        sys.stdout.write(body)
    sys.stdout.write(wout.replace("%{http_code}", "%03d" % code).replace("%{ssl_verify_result}", "0"))
    sys.exit(rc)


def stub_driver(argv):
    log_call("stub", None, "%s (l2-shim: NOT rehearsed, stubbed at the driver boundary)" % " ".join(argv))
    print("l2-shim: %s is NOT rehearsed: the call is recorded in calls.log and answers exit 0" % argv[0])
    sys.exit(0)


if __name__ == "__main__":
    main()
